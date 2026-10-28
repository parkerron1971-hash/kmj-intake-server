# __tests__/test_news_alerts.py
#
# Phone alerts and the week's email for the church's news (news_alerts.py;
# the approved canvas "Church News & Celebrations" boards 6, 7 and 9). Pins:
#   1. each member's choice: Important by default, Everything, or Off; a
#      post marked important rings Important and Everything, any other post
#      only Everything; only the people it's for; never whoever posted it;
#      nothing when the church hasn't turned News alerts on
#   2. a post rings once, when it goes up: a scheduled one waits; no more
#      than the church's three a day, counting its announcements, on its own
#      clock; a post a day and a half old never rings
#   3. "Dana replied to your comment", to the person answered, unless they
#      turned replies off
#   4. birthdays: one note after 9 AM to the people in the celebrated
#      person's own groups, never to the celebrated, and none when the
#      church chose no celebration alerts
#   5. the week's email: Saturdays after 9, the posts they haven't seen,
#      grown-ups only, once a week
#   6. the pages: Me → Celebrations "What you hear about", the Write page's
#      Important switch with the day's count, the office's settings

import pathlib
import sys
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_portal_church as mpc
import news_alerts as na
import test_member_portal_group_space as gs
from test_church_news import _me, _post
from test_member_portal_group_space import BIZ, G, MONIQUE, ROCHELLE, TASHA, TEEN, _params, _req  # noqa: F401

ON = {"member_portal": {"notifications": {"news": True}}, "availability": {"timezone": "America/Detroit"}}
CHURCH = {"id": BIZ, "name": "Love City Church", "owner_id": "o1", "settings": ON}
# Friday 2026-10-23, 10:00 AM in Detroit (14:00 UTC).
FRI_10 = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
P1 = "dddddddd-8888-0000-0000-000000000001"


def _like(row, key, expr):
    op, _, val = expr.partition(".")
    if op == "like":
        return str(row.get(key) or "").startswith(val.rstrip("*"))
    return _cond0(row, key, expr)


_cond0 = gs._cond


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(gs, "_cond", _like)
    f = gs.Fake()
    f.t.update(church_posts=[], church_post_reactions=[], church_post_seen=[], church_post_comments=[],
               church_post_comment_loves=[], church_post_reports=[], church_news_posters=[], sermons=[],
               member_push_prefs=[], member_push_sends=[], church_news_digests=[],
               member_push_subscriptions=[{"id": f"s{i}", "business_id": BIZ, "contact_id": c}
                                          for i, c in enumerate((TASHA, MONIQUE, ROCHELLE, TEEN))],
               businesses=[{**CHURCH}])
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(cn, "is_pastoral", lambda biz, cid: False)
    import member_push
    f.sent = []

    def send(business, kind, **kw):
        f.sent.append((kind, kw))
        return len(kw.get("contact_ids") or [])
    monkeypatch.setattr(member_push, "send", send)
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: fn(*a, **k))
    return f


def _pref(f, cid, **k):
    f.t["member_push_prefs"].append({"business_id": BIZ, "contact_id": cid, "off": [], **k})


def _p(**k):
    return _post(P1, **{"posted_by": TASHA, "source": "leader", "created_at": "2026-10-23T13:30:00+00:00", **k})


# ── 1. who hears ─────────────────────────────────────────────────────

def test_important_rings_important_and_everything_any_other_post_only_everything(fake):
    _pref(fake, MONIQUE, news_level="everything")
    _pref(fake, ROCHELLE, news_level="off")
    assert na.recipients(CHURCH, _p(important=True)) == sorted([MONIQUE, TEEN])     # TEEN keeps the default
    assert na.recipients(CHURCH, _p()) == [MONIQUE]
    _pref(fake, TEEN, off=["news"])                                                   # turned News off entirely
    assert na.recipients(CHURCH, _p(important=True)) == [MONIQUE]


def test_only_the_people_its_for_and_never_whoever_posted(fake):
    _pref(fake, ROCHELLE, news_level="everything")
    _pref(fake, MONIQUE, news_level="everything")
    assert na.recipients(CHURCH, _p(group_id=G)) == [MONIQUE]                         # TASHA posted it
    assert na.recipients(CHURCH, _p(attach={"groups": [G]})) == [MONIQUE]


def test_nothing_rings_until_the_church_turns_news_alerts_on(fake):
    off = {**CHURCH, "settings": {"availability": {"timezone": "America/Detroit"}}}
    fake.t["church_posts"].append(_p(important=True))
    assert na.alert_post(off, _p(important=True), FRI_10) == {"rang": 0, "why": "off"}
    assert fake.sent == [] and fake.t["church_posts"][0].get("alerted_at") is None


# ── 2. once, when it's up, three a day ───────────────────────────────

def test_a_post_rings_once(fake):
    fake.t["church_posts"].append(_p(important=True))
    r = na.alert_post(CHURCH, _p(important=True), FRI_10)
    assert r["why"] == "" and r["rang"] == 3
    kind, kw = fake.sent[0]
    assert kind == "news" and kw["ref_id"] == f"news-post:{P1}" and kw["body"].startswith("Important: ")
    again = fake.t["church_posts"][0]
    assert again["alerted_at"] and na.alert_post(CHURCH, again, FRI_10)["why"] == "old" and len(fake.sent) == 1


def test_a_scheduled_post_waits_for_its_time(fake):
    p = _p(important=True, publish_at="2026-10-25T11:00:00+00:00")
    fake.t["church_posts"].append(p)
    assert na.alert_post(CHURCH, p, FRI_10)["why"] == "later" and fake.sent == []
    assert na.alert_post(CHURCH, p, datetime(2026, 10, 25, 11, 5, tzinfo=timezone.utc))["rang"] == 3


def test_three_a_day_counting_announcements_on_the_churchs_clock(fake):
    sends = fake.t["member_push_sends"]
    sends += [{"business_id": BIZ, "kind": "announcements", "ref_id": "a1", "created_at": "2026-10-23T12:00:00+00:00"},
              {"business_id": BIZ, "kind": "news", "ref_id": "news-post:x", "created_at": "2026-10-23T12:30:00+00:00"},
              # yesterday evening in Detroit, and notes that aren't posts: not counted
              {"business_id": BIZ, "kind": "news", "ref_id": "news-post:y", "created_at": "2026-10-23T03:00:00+00:00"},
              {"business_id": BIZ, "kind": "news", "ref_id": "news-reply:z", "created_at": "2026-10-23T13:00:00+00:00"}]
    assert na.sent_today(CHURCH, FRI_10) == 2
    sends.append({"business_id": BIZ, "kind": "news", "ref_id": "news-post:w", "created_at": "2026-10-23T13:00:00+00:00"})
    fake.t["church_posts"].append(_p(important=True))
    assert na.alert_post(CHURCH, _p(important=True), FRI_10) == {"rang": 0, "why": "full"}
    assert fake.sent == [] and fake.t["church_posts"][0]["alerted_at"]     # still on News, never rings later


def test_an_old_post_never_rings(fake):
    p = _p(important=True, created_at="2026-10-21T10:00:00+00:00")
    fake.t["church_posts"].append(p)
    assert na.alert_post(CHURCH, p, FRI_10)["why"] == "old" and fake.sent == []


# ── 3. replies ───────────────────────────────────────────────────────

def test_a_reply_tells_the_person_answered(fake):
    assert na.tell_reply(CHURCH, P1, "c1", MONIQUE, _me(ROCHELLE, "Rochelle Adams")) == 1
    kind, kw = fake.sent[0]
    assert kw["body"] == "Rochelle replied to your comment" and kw["contact_ids"] == [MONIQUE]
    assert na.tell_reply(CHURCH, P1, "c2", MONIQUE, _me(MONIQUE)) == 0              # answering yourself
    _pref(fake, ROCHELLE, news_replies=False)
    assert na.tell_reply(CHURCH, P1, "c3", ROCHELLE, _me(MONIQUE)) == 0


def test_a_comment_reply_rings_the_one_answered(fake, monkeypatch):
    import asyncio
    import messaging_router as mr
    import msg_screen

    async def ok(biz, text):
        return "ok"
    monkeypatch.setattr(msg_screen, "screen", ok)
    monkeypatch.setattr(mr, "officer_count", lambda biz: 2)
    fake.t["church_posts"].append(_p())
    asyncio.run(cn.comment(CHURCH, _me(MONIQUE, "Monique Brown"), P1, "We'll be there"))
    first = fake.t["church_post_comments"][0]["id"]
    asyncio.run(cn.comment(CHURCH, _me(ROCHELLE, "Rochelle Adams"), P1, "Me too", first))
    assert [kw["contact_ids"] for _k, kw in fake.sent] == [[MONIQUE]]


# ── 4. birthdays in my groups ────────────────────────────────────────

def _birthday(fake, cid, day="2026-10-23"):
    fake.t["church_posts"].append(_post(f"dddddddd-9999-0000-0000-{len(fake.t['church_posts']):012d}", kind="celebration",
                                        source="chief", person_id=cid, celebrate_on=day, attach={"sub": "birthday"}))


def test_one_9am_note_to_the_celebrated_persons_groups(fake):
    _birthday(fake, MONIQUE)
    assert na.birthday_notes(CHURCH, datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)) == 0     # 8 AM in Detroit
    assert na.birthday_notes(CHURCH, FRI_10) == 2
    told = {kw["contact_ids"][0]: kw for _k, kw in fake.sent}
    assert set(told) == {TASHA, TEEN} and MONIQUE not in told and ROCHELLE not in told
    assert told[TASHA]["body"] == "It's Monique's birthday today." and told[TASHA]["ref_id"] == f"news-bday:2026-10-23:{TASHA}"


def test_no_birthday_notes_when_the_church_says_none_or_they_turned_it_off(fake):
    _birthday(fake, MONIQUE)
    _pref(fake, TASHA, news_birthdays=False)
    assert na.birthday_notes(CHURCH, FRI_10) == 1
    quiet = {**CHURCH, "settings": {**ON, "news": {"celebration_alerts": "none"}}}
    fake.sent.clear()
    assert na.birthday_notes(quiet, FRI_10) == 0 and fake.sent == []


# ── 5. the week's email ──────────────────────────────────────────────

SAT_10 = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)


def test_saturday_the_posts_they_havent_seen_once_a_week_grownups_only(fake, monkeypatch):
    emailed = []

    async def email(business, person, posts, app):
        emailed.append((person["id"], [p["id"] for p in posts]))
    monkeypatch.setattr(na, "_email", email)
    import group_email
    monkeypatch.setattr(group_email, "app_url", lambda biz: "https://lovecityc.com")
    for c in (MONIQUE, ROCHELLE, TEEN):
        _pref(fake, c, news_email=True)
    seen_id, unseen_id, group_id = (f"dddddddd-7777-0000-0000-00000000000{i}" for i in (1, 2, 3))
    fake.t["church_posts"] += [_post(seen_id, created_at="2026-10-22T10:00:00+00:00"),
                               _post(unseen_id, created_at="2026-10-22T11:00:00+00:00"),
                               _post(group_id, created_at="2026-10-22T12:00:00+00:00", group_id=G)]
    fake.t["church_post_seen"].append({"post_id": seen_id, "contact_id": MONIQUE, "business_id": BIZ})
    assert na.digest(CHURCH, FRI_10) == 0                                           # not Saturday
    assert na.digest(CHURCH, SAT_10) == 2
    got = dict(emailed)
    assert set(got[MONIQUE]) == {group_id, unseen_id} and set(got[ROCHELLE]) == {unseen_id, seen_id} and TEEN not in got
    assert na.digest(CHURCH, SAT_10) == 0 and len(emailed) == 2                     # once a week


# ── 6. pages and settings ────────────────────────────────────────────

def test_me_shows_what_you_hear_about_only_when_the_church_rings(fake):
    import member_portal_celebrations as mcl
    mine = {"birthday": None, "milestones": False}
    html, _ = mcl.render_me(CHURCH, None, _req(), _me(MONIQUE), mine, [], [], {},
                            {**na.prefs(BIZ, MONIQUE), "phone": False, "celebrations": True})
    for words in ("What you hear about", "Important", "Everything", "Only posts your pastors mark important.",
                  "Birthdays in my groups", "Replies to my comments", "The week&#x27;s news by email",
                  "Turn on alerts on this phone first", "Nothing rings between 9 PM and 7 AM"):
        assert words in html, words
    html, _ = mcl.render_me(CHURCH, None, _req(), _me(MONIQUE), mine, [], [], {}, None)
    assert "What you hear about" not in html


def test_the_alerts_route_saves_what_they_chose(fake, monkeypatch):
    import member_portal_celebrations as mcl

    async def signed_in(request):
        return {"business": CHURCH}, _me(MONIQUE), False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda church, who: True)
    app = FastAPI()
    app.include_router(mcl.router)
    c = TestClient(app, follow_redirects=False)
    r = c.post("/my/celebrate/alerts", data={"level": "everything", "birthdays": "0", "replies": ["0", "1"], "email": ["0", "1"]})
    assert r.headers["location"] == "/my/me/celebrations?done=alerts_saved#cl-hear"
    assert na.prefs(BIZ, MONIQUE) == {"level": "everything", "birthdays": False, "replies": True, "email": True, "muted": False,
                                      "texts": True, "chose_texts": None}      # the texts box wasn't on the page
    assert c.post("/my/celebrate/alerts", data={"level": "loud"}).headers["location"].endswith("err=error")


def test_the_write_page_says_where_the_day_stands(fake):
    import member_portal_write as mpw
    rights = {"church": True, "pastoral": True, "groups": []}
    auds = [("all", "Whole church", 490)]
    html, _ = mpw.render_write(CHURCH, None, _req(), _me(TASHA), rights, auds, [], [], alerts={"on": True, "sent_today": 1, "max": 3})
    assert "Important: ring their phones" in html and "2nd alert" in html and 'name="important"' in html
    html, _ = mpw.render_write(CHURCH, None, _req(), _me(TASHA), rights, auds, [], [], alerts={"on": True, "sent_today": 3, "max": 3})
    assert "sent its 3 alerts today" in html and 'name="important"' not in html
    html, _ = mpw.render_write(CHURCH, None, _req(), _me(TASHA), rights, auds, [], [], alerts=None)
    assert "Important: ring their phones" not in html


def test_the_office_turns_news_alerts_on_and_chooses_celebrations(fake, monkeypatch):
    import kids_router
    from auth_supabase import require_user

    class _User:
        id = "u1"
        email = "office@example.com"
        role = "authenticated"
    monkeypatch.setattr(kids_router, "role_for", lambda biz, user: "admin")
    app = FastAPI()
    app.include_router(cn.router)
    app.dependency_overrides[require_user] = lambda: _User()
    fake.t["businesses"] = [{"id": BIZ, "name": "Love City Church", "owner_id": "o1",
                             "settings": {"news": {"comments": False}, "member_portal": {"notifications": {"live": True}}}}]
    r = TestClient(app).post("/church/news/settings", json={"business_id": BIZ, "alerts": True, "celebration_alerts": "none"})
    assert r.status_code == 200
    s = fake.t["businesses"][0]["settings"]
    assert s["member_portal"]["notifications"] == {"live": True, "news": True}
    assert s["news"] == {"comments": False, "celebration_alerts": "none"}               # comments untouched
    v = cn._alerts_view(fake.t["businesses"][0])
    assert v == {"on": True, "sent_today": 0, "max": 3, "celebrations": "none",
                 "reach": {"on": True, "texts_month": 0, "cap": 500}}
