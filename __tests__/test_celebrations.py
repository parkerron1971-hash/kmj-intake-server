# __tests__/test_celebrations.py
#
# Celebrations in the church's news (celebrations.py +
# member_portal_celebrations.py; part 3 of the approved canvas "Church News
# & Celebrations"; Kevin 2026-10-23: ask each member first). Pins:
#   1. who: a birthday only for someone who said yes (or, when the church
#      celebrates everyone, didn't say no); never a teen; the day only, a
#      month and day from the member when the record has none; Feb 29 on
#      Feb 28 in a year without one
#   2. an anniversary only when BOTH said yes; its years only when they
#      chose to show them; someone the office marked as passed away stops
#      their birthday AND every anniversary of theirs
#   3. each morning, after 7 AM on the church's clock, today's are posts
#   4. the feed: today's people together in "Today we celebrate", another
#      day's not at all; Home's "From the church" leaves them to
#      "Celebrating today"
#   5. the pages: Home's strip, the church's question (only when the office
#      asks), a celebration's page with quick wishes, Me's choices
#   6. routes: answering, a day when there's none on file, a couple's yes
#   7. the office: an admin sets; a milestone only for someone who said yes;
#      Sunday's post; stopping

import pathlib
import sys
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import celebrations as cel
import church_news as cn
import member_portal_celebrations as mcl
import member_portal_church as mpc
import member_portal_news as mpn
import test_member_portal_group_space as gs
from test_member_portal_group_space import BIZ, MONIQUE, ROCHELLE, TASHA, TEEN, _params, _req  # noqa: F401

DARNELL = "cccccccc-0000-0000-0000-000000000011"
LISA = "cccccccc-0000-0000-0000-000000000012"
HOUSE = "abababab-0000-0000-0000-000000000001"
BUSINESS = {"id": BIZ, "name": "Love City Church",
            "settings": {"availability": {"timezone": "America/Detroit"}, "news": {"ask_members": True}}, "owner_id": "o1"}


def _cond(row, key, expr):
    if expr == "not.is.null":
        return row.get(key) is not None
    return gs.__dict__["_cond_orig"](row, key, expr)


@pytest.fixture
def fake(monkeypatch):
    if "_cond_orig" not in gs.__dict__:
        gs.__dict__["_cond_orig"] = gs._cond
    monkeypatch.setattr(gs, "_cond", _cond)
    f = gs.Fake()
    f.t["contacts"] += [
        {"id": DARNELL, "business_id": BIZ, "name": "Darnell Grant", "birthdate": "1975-06-01", "metadata": {}},
        {"id": LISA, "business_id": BIZ, "name": "Lisa Grant", "birthdate": "1977-08-01", "metadata": {}},
    ]
    f.t.update(member_celebrations=[], member_anniversaries=[], church_posts=[], church_post_reactions=[], church_post_seen=[],
               church_post_comments=[], church_post_comment_loves=[], church_post_reports=[], church_news_posters=[],
               household_adults=[{"household_id": HOUSE, "contact_id": DARNELL, "business_id": BIZ},
                                 {"household_id": HOUSE, "contact_id": LISA, "business_id": BIZ}],
               businesses=[dict(BUSINESS)], academy_enrollments=[], academy_courses=[], sermons=[])
    import sb_clients

    def delete(path):
        table, params = _params(path)
        f.t[table] = [r for r in f.t.get(table, []) if r not in f._rows(table, params)]
        return True
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    monkeypatch.setattr(cn, "is_pastoral", lambda biz, cid: False)
    import messaging_router as mr
    monkeypatch.setattr(mr, "officer_count", lambda biz: 2)
    monkeypatch.setattr(mpc, "upcoming_for", lambda biz, me: [])
    return f


def _yes(fake, cid, **k):
    fake.t["member_celebrations"].append({"business_id": BIZ, "contact_id": cid, "birthday": True, "birthday_md": None,
                                          "milestones": False, "stopped": None, **k})


def _set_birthday(fake, cid, iso):
    next(c for c in fake.t["contacts"] if c["id"] == cid)["birthdate"] = iso


def _due(day, business=BUSINESS):
    return [(w["sub"], w["person_id"], w["years"]) for w in cel.due(business, [day])]


# ── 1. birthdays ─────────────────────────────────────────────────────

def test_a_birthday_only_for_someone_who_said_yes(fake):
    _set_birthday(fake, MONIQUE, "1984-10-23")
    _set_birthday(fake, TASHA, "1980-10-23")
    _yes(fake, MONIQUE)
    assert _due(date(2026, 10, 23)) == [("birthday", MONIQUE, None)]
    # The church celebrates everyone unless they say no.
    fake.t["member_celebrations"].append({"business_id": BIZ, "contact_id": ROCHELLE, "birthday": False})
    _set_birthday(fake, ROCHELLE, "1990-10-23")
    every = {**BUSINESS, "settings": {"news": {"celebrate": "all"}}}
    assert sorted(_due(date(2026, 10, 23), every)) == sorted([("birthday", MONIQUE, None), ("birthday", TASHA, None)])


def test_never_a_teen_and_a_day_from_the_member_when_none_on_file(fake):
    _set_birthday(fake, TEEN, f"{date.today().year - 15}-10-23")
    _yes(fake, TEEN)
    _set_birthday(fake, ROCHELLE, None)
    _yes(fake, ROCHELLE, birthday_md="10-23")
    assert _due(date(2026, 10, 23)) == [("birthday", ROCHELLE, None)]


def test_feb_29_is_celebrated_on_feb_28_in_a_year_without_one(fake):
    _set_birthday(fake, MONIQUE, "1984-02-29")
    _yes(fake, MONIQUE)
    assert _due(date(2027, 2, 28)) == [("birthday", MONIQUE, None)]
    assert _due(date(2028, 2, 28)) == [] and _due(date(2028, 2, 29)) == [("birthday", MONIQUE, None)]


# ── 2. anniversaries, and someone who passed away ────────────────────

def _couple(fake, a_yes=True, b_yes=True, show=False):
    fake.t["member_anniversaries"].append({"id": "aaaaaaaa-1111-0000-0000-000000000001", "business_id": BIZ, "a_id": DARNELL,
                                           "b_id": LISA, "married_on": "2006-10-23", "a_yes": a_yes, "b_yes": b_yes,
                                           "show_years": show})


def test_an_anniversary_needs_both_yeses_and_years_only_when_shown(fake):
    _couple(fake, b_yes=False)
    assert _due(date(2026, 10, 23)) == []
    fake.t["member_anniversaries"][0]["b_yes"] = True
    assert _due(date(2026, 10, 23)) == [("anniversary", DARNELL, None)]
    fake.t["member_anniversaries"][0]["show_years"] = True
    assert _due(date(2026, 10, 23)) == [("anniversary", DARNELL, 20)]


def test_someone_who_passed_away_stops_their_birthday_and_every_anniversary(fake):
    _couple(fake)
    _set_birthday(fake, LISA, "1977-10-23")
    _yes(fake, LISA)
    assert len(_due(date(2026, 10, 23))) == 2
    fake.t["member_celebrations"][0]["stopped"] = "passed"
    assert _due(date(2026, 10, 23)) == []   # the spouse is never shown an anniversary alone


# ── 3. each morning ──────────────────────────────────────────────────

def test_todays_celebrations_go_up_after_seven_on_the_churchs_clock(fake):
    _set_birthday(fake, MONIQUE, "1984-10-23")
    _yes(fake, MONIQUE)
    early = datetime(2026, 10, 23, 10, 30, tzinfo=timezone.utc)    # 6:30 AM in Detroit
    assert cel.make_today(BUSINESS, early) == 0 and fake.t["church_posts"] == []
    later = datetime(2026, 10, 23, 11, 30, tzinfo=timezone.utc)
    assert cel.make_today(BUSINESS, later) == 1
    p = fake.t["church_posts"][0]
    assert (p["kind"], p["person_id"], p["celebrate_on"], p["attach"]) == ("celebration", MONIQUE, "2026-10-23", {"sub": "birthday"})
    assert p["publish_at"] == "2026-10-23T11:00:00+00:00"


# ── 4. the feed ──────────────────────────────────────────────────────

def _celebration(pid, person, day, sub="birthday", partner=None):
    return {"id": pid, "business_id": BIZ, "kind": "celebration", "title": "", "body": "", "group_id": None, "posted_by": None,
            "office_user": None, "author_label": "", "source": "chief", "status": "posted", "pinned_until": None,
            "important": False, "comments": "on", "publish_at": None, "attach": {"sub": sub}, "person_id": person,
            "partner_id": partner, "celebrate_on": day, "created_at": f"{day}T11:00:00+00:00", "removed_at": None}


TODAY_P = "dddddddd-3333-0000-0000-000000000001"


def test_todays_people_sit_together_and_another_days_never_show(fake):
    fake.t["church_posts"] += [_celebration(TODAY_P, MONIQUE, "2026-10-23"),
                               _celebration("dddddddd-3333-0000-0000-000000000002", TASHA, "2026-10-20")]
    rows = cn.feed(BIZ, ROCHELLE, "", "2026-10-23")
    assert [r["id"] for r in rows] == [TODAY_P]
    html, _ = mpn.render_news(BUSINESS, None, _req(), {"id": ROCHELLE, "name": "Rochelle"}, rows, "", [], True)
    assert "Today we celebrate" in html and "Monique Brown" in html and "Wish them well" in html
    # Home's "From the church" leaves them to "Celebrating today".
    assert cn.home_view(BIZ, ROCHELLE)[0] == []


# ── 5. the pages ─────────────────────────────────────────────────────

def test_home_strip_and_the_celebration_page(fake, monkeypatch):
    fake.t["church_posts"].append(_celebration(TODAY_P, MONIQUE, date.today().isoformat()))
    monkeypatch.setattr(cel, "local_now", lambda b, now=None: datetime.now(timezone.utc))
    today = cel.today_posts(BUSINESS, ROCHELLE)
    strip = mcl.home_strip(today)
    assert "Celebrating today" in strip and "Wish Monique a happy birthday" in strip
    p = cn.one(BIZ, ROCHELLE, TODAY_P)
    html, status = mpn.render_post(BUSINESS, None, _req(), {"id": ROCHELLE, "name": "Rochelle"}, p, [], True, today)
    assert status == 200 and "Happy birthday, <em>Monique!</em>" in html
    assert 'value="Happy birthday!"' in html and "Send a wish" in html and "said yes to this" in html
    closed, _ = mpn.render_post(BUSINESS, None, _req(), {"id": ROCHELLE, "name": "Rochelle"}, p, [], False, today)
    assert "Wishes open when comments do" in closed and 'value="Happy birthday!"' not in closed


def test_the_question_waits_for_the_office_and_asks_once(fake):
    me = {"id": MONIQUE, "name": "Monique Brown", "birthdate": "1984-03-12"}
    quiet = {**BUSINESS, "settings": {"news": {}}}
    assert mcl.ask_card(quiet, me, cel.prefs(BIZ, MONIQUE), []) == ""
    card = mcl.ask_card(BUSINESS, me, cel.prefs(BIZ, MONIQUE), [])
    assert "Want the church to celebrate your birthday?" in card and 'name="month"' not in card
    _yes(fake, MONIQUE)
    assert mcl.ask_card(BUSINESS, me, cel.prefs(BIZ, MONIQUE), []) == ""


def test_me_shows_my_choices(fake):
    _yes(fake, MONIQUE)
    me = {"id": MONIQUE, "name": "Monique Brown", "birthdate": "1984-03-12"}
    html, status = mcl.render_me(BUSINESS, None, _req(), me, cel.prefs(BIZ, MONIQUE), [], [], {})
    assert status == 200 and "Let the church <em>celebrate you.</em>" in html and "March 12" in html
    assert 'aria-label="Celebrate my birthday"' in html and 'aria-checked="true"' in html
    assert "Happy birthday, Monique!" in html


# ── 6. routes ────────────────────────────────────────────────────────

def _client(monkeypatch, me):
    async def signed_in(request):
        return {"business": BUSINESS}, me, False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mcl.router)
    return TestClient(app, follow_redirects=False)


def test_saying_yes_needs_a_day_when_none_is_on_file(fake, monkeypatch):
    me = {"id": ROCHELLE, "name": "Rochelle Taylor", "birthdate": None}
    c = _client(monkeypatch, me)
    assert c.post("/my/celebrate/answer", data={"yes": "1"}).headers["location"] == "/my?err=cel_day"
    r = c.post("/my/celebrate/answer", data={"yes": "1", "month": "10", "day": "23"})
    assert r.headers["location"] == "/my?done=cel_yes"
    row = fake.t["member_celebrations"][0]
    assert (row["birthday"], row["birthday_md"]) == (True, "10-23")
    assert c.post("/my/celebrate/answer", data={"yes": "0"}).headers["location"] == "/my?done=cel_no"


def test_a_couple_says_yes_one_at_a_time(fake, monkeypatch):
    c = _client(monkeypatch, {"id": DARNELL, "name": "Darnell Grant", "birthdate": "1975-06-01"})
    r = c.post("/my/celebrate/anniversary", data={"with": LISA, "married_on": "2006-10-23", "show_years": "1"})
    assert r.headers["location"] == "/my/me/celebrations?done=ann_asked"
    a = fake.t["member_anniversaries"][0]
    assert (a["a_yes"], a["b_yes"]) == (True, False)
    # Someone outside the household can't be named.
    assert "err=ann_who" in c.post("/my/celebrate/anniversary", data={"with": ROCHELLE, "married_on": "2006-10-23"}).headers["location"]
    mine, asks = mcl.home_asks(BUSINESS, {"id": LISA, "name": "Lisa Grant"})
    assert len(asks) == 1 and "Darnell" in mcl.ask_card(BUSINESS, {"id": LISA}, mine, asks)
    lisa = _client(monkeypatch, {"id": LISA, "name": "Lisa Grant", "birthdate": "1977-08-01"})
    assert lisa.post("/my/celebrate/anniversary/answer", data={"id": a["id"], "yes": "1"}).headers["location"] == "/my?done=ann_yes"
    assert fake.t["member_anniversaries"][0]["b_yes"] is True


# ── 7. the office ────────────────────────────────────────────────────

class _User:
    id = "u1"
    email = "office@example.com"
    role = "authenticated"


def _office(monkeypatch, role):
    import kids_router
    from auth_supabase import require_user
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: role)
    app = FastAPI()
    app.include_router(cel.router)
    app.dependency_overrides[require_user] = lambda: _User()
    return TestClient(app)


def test_an_admin_sets_how_the_church_celebrates(fake, monkeypatch):
    body = {"business_id": BIZ, "celebrate": "all"}
    assert _office(monkeypatch, "member").post("/church/news/celebrations/settings", json=body).status_code == 403
    assert _office(monkeypatch, "admin").post("/church/news/celebrations/settings", json=body).status_code == 200
    assert fake.t["businesses"][0]["settings"]["news"]["celebrate"] == "all"


def test_a_milestone_only_for_someone_who_said_yes(fake, monkeypatch):
    fake.t["academy_courses"].append({"id": "c0c0c0c0-0000-0000-0000-000000000001", "business_id": BIZ, "title": "The Making: Foundations"})
    fake.t["academy_enrollments"].append({"id": "e0e0e0e0-0000-0000-0000-000000000001", "business_id": BIZ, "contact_id": MONIQUE,
                                          "course_id": "c0c0c0c0-0000-0000-0000-000000000001",
                                          "completed_at": datetime.now(timezone.utc).isoformat()})
    body = {"business_id": BIZ, "enrollment_id": "e0e0e0e0-0000-0000-0000-000000000001"}
    assert _office(monkeypatch, "member").post("/church/news/celebrations/milestone", json=body).status_code == 409
    _yes(fake, MONIQUE, milestones=True)
    v = _office(monkeypatch, "viewer").get(f"/church/news/celebrations?business_id={BIZ}").json()
    assert v["milestones"][0]["draft"] == "Monique finished The Making: Foundations. Celebrate with them!"
    assert _office(monkeypatch, "member").post("/church/news/celebrations/milestone", json=body).status_code == 200
    p = fake.t["church_posts"][0]
    assert (p["kind"], p["status"], p["title"]) == ("milestone", "posted", "Monique Brown finished The Making: Foundations")


def test_sundays_post_names_who_said_yes(fake, monkeypatch):
    soon = date.today()
    _set_birthday(fake, MONIQUE, f"1984-{soon.month:02d}-{soon.day:02d}")
    _yes(fake, MONIQUE)
    monkeypatch.setattr(cel, "local_now", lambda b, now=None: datetime.now(timezone.utc).replace(hour=1))
    v = _office(monkeypatch, "viewer").get(f"/church/news/celebrations?business_id={BIZ}").json()
    assert v["weekly_text"] == "This week we celebrate Monique." and v["week"][0]["name"] == "Monique Brown"
    r = _office(monkeypatch, "member").post("/church/news/celebrations/week", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    assert fake.t["church_posts"][-1]["body"] == "This week we celebrate Monique."


def test_stopping_someone_takes_down_todays_post(fake, monkeypatch):
    fake.t["church_posts"].append(_celebration(TODAY_P, MONIQUE, date.today().isoformat()))
    monkeypatch.setattr(cel, "local_now", lambda b, now=None: datetime.now(timezone.utc))
    body = {"business_id": BIZ, "contact_id": MONIQUE, "reason": "passed"}
    assert _office(monkeypatch, "member").post("/church/news/celebrations/stop", json=body).status_code == 403
    assert _office(monkeypatch, "admin").post("/church/news/celebrations/stop", json=body).status_code == 200
    assert fake.t["member_celebrations"][0]["stopped"] == "passed"
    assert fake.t["church_posts"][0]["status"] == "removed"
