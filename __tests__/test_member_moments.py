# __tests__/test_member_moments.py
#
# A pastor or a leader posts their own moment (member_moments.py, Look 5.1):
#   - who may post: a pastor and someone the office picked (the whole church
#     or a group they lead), a group's leader (only their own groups); a
#     member is refused, and the composer isn't theirs;
#   - a group's moment reaches only that group's people (Home, the photo);
#   - it ends on its own, and an ended one is never read for Home;
#   - every line is checked: held for the safety officers (only its poster
#     sees it; Let it through / Keep it hidden in church_news' held list),
#     crisis words tell the pastor and show 988, and nothing posts when the
#     check can't run;
#   - a group with a teen in it gets no moments (members' posting's photo rule);
#   - its poster, a pastor or the church's owner takes it down; nobody else;
#   - seen and Love are the member's own row, on a moment they may see, seen
#     written once;
#   - the poster's sheet counts, never names; a leader's moment has no Share;
#   - before the tables are there nothing reads twice, nothing shows, nothing posts;
#   - with the new look off, nothing here writes or shows.

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_moments as mmo
import messaging_router as mr
import sb_clients
import test_member_messaging as tmm
from test_member_group_chat import church as gchurch  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)

PASTOR = "00000000-0000-4000-8000-0000000000f1"
PICKED = tmm.PARENT
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def world(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    monkeypatch.setenv("MEMBER_CACHE", "off")
    monkeypatch.setattr(mr, "officer_count", lambda b: 2)
    mmo._STATE["missing_until"] = 0.0
    w = gchurch
    w.t["contacts"].append({"id": PASTOR, "business_id": tmm.BIZ, "name": "James Carter", "birthdate": "1975-04-04"})
    w.t["msg_members"].append({"contact_id": PASTOR, "business_id": tmm.BIZ, "enabled": True,
                               "guidelines_at": "2026-10-01T00:00:00+00:00"})
    w.t["church_leader_roles"] = [{"id": "00000000-0000-4000-8000-0000000000f9", "business_id": tmm.BIZ, "contact_id": PASTOR,
                                   "role": "pastor", "status": "active", "scope": "", "invited_at": "2026-10-01T00:00:00+00:00"}]
    w.t["church_role_defs"] = []
    w.t["church_news_posters"] = [{"business_id": tmm.BIZ, "contact_id": PICKED}]
    w.t["church_moments"], w.t["church_moment_marks"] = [], []
    w.biz["timezone"] = "America/New_York"
    cared = []
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "care_alert", lambda b, me: cared.append(me["id"]))
    w.cared = cared
    import member_portal_write as mpw
    w.photos = []

    async def photos(biz_id, files):
        w.photos.append(len(files))
        return [{"path": f"{biz_id}/news-photos/m{len(w.photos)}.webp", "w": 900, "h": 1600}], ""
    monkeypatch.setattr(mpw, "_photos", photos)
    import chat_photos
    w.dropped = []
    monkeypatch.setattr(chat_photos, "drop", lambda path: w.dropped.append(path))
    import storage_links
    monkeypatch.setattr(storage_links, "signed_url_sync", lambda bucket, path, ttl=0, **k: f"https://cdn.test/{path}")
    # PostgREST's upsert on the marks (on_conflict + ignore or merge), which the shared fake doesn't do.
    base_post = w.post

    def post(path, body, prefer=None, **kw):
        if path.startswith("/church_moment_marks"):
            hit = next((r for r in w.t["church_moment_marks"] if r["moment_id"] == body["moment_id"]
                        and r["contact_id"] == body["contact_id"]), None)
            if hit is not None:
                if "merge-duplicates" in (prefer or ""):
                    hit.update(body)
                return []
            w.t["church_moment_marks"].append(dict(body))
            return []
        return base_post(path, body, prefer)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    return w


def _app():
    import member_portal as mp
    app = FastAPI()
    app.include_router(mmo.router)

    @app.get("/my/{rest:path}")
    async def page(rest: str, request: mp.Request):
        return await mp.serve(request, "/my/" + rest)
    return TestClient(app, base_url=f"https://{tmm.HOST}")


def _as(env, who, preview=False):
    env.who.update(id=who, preview=preview)
    return _app()


def _share(env, who, *, to="church", line="Praying for you this morning. See you Sunday.", button="none",
           lasts="day", photo=PNG):
    files = {"photo": ("p.png", photo, "image/png")} if photo else None
    return _as(env, who).post("/my/moment", data={"to": to, "line": line, "button": button, "lasts": lasts},
                              files=files, headers=tmm.ORIGIN, follow_redirects=False)


def _rows(env):
    return env.t["church_moments"]


def _moment(env, who, *, group=None, status="shown", hours=24, line="Friday night is back.", ago=1, reason=None):
    now = datetime.now(timezone.utc)
    row = {"id": f"00000000-0000-4000-a000-{len(_rows(env)) + 1:012d}", "business_id": tmm.BIZ, "posted_by": who,
           "group_id": group, "line": line, "media_path": f"{tmm.BIZ}/news-photos/x{len(_rows(env))}.webp",
           "media_kind": "photo", "button_kind": None, "button_ref": None,
           "starts_at": (now - timedelta(hours=ago)).isoformat(), "ends_at": (now + timedelta(hours=hours)).isoformat(),
           "status": status, "held_reason": reason, "created_at": (now - timedelta(hours=ago)).isoformat()}
    env.t["church_moments"].append(row)
    return row


# ─── who may post ────────────────────────────────────────────────────


def test_a_pastor_posts_to_the_whole_church(world):
    r = _share(world, PASTOR)
    assert r.headers["location"] == "/my?done=moment_up"
    (m,) = _rows(world)
    assert m["status"] == "shown" and m["group_id"] is None and m["posted_by"] == PASTOR
    assert m["media_kind"] == "photo" and m["media_path"].startswith(f"{tmm.BIZ}/news-photos/")
    assert m["line"] == "Praying for you this morning. See you Sunday."


def test_someone_the_office_picked_posts_to_the_whole_church(world):
    assert _share(world, PICKED).headers["location"] == "/my?done=moment_up"


def test_a_group_leader_posts_only_to_their_own_groups(world):
    assert "err=moment_where" in _share(world, tmm.BEN, to="church").headers["location"]
    assert "err=moment_where" in _share(world, tmm.BEN, to=tmm.YOUTH).headers["location"]
    assert _share(world, tmm.BEN, to=tmm.GRP).headers["location"] == "/my?done=moment_up"
    assert [m["group_id"] for m in _rows(world)] == [tmm.GRP]


def test_a_member_is_refused_and_has_no_composer(world):
    assert "err=moment_who" in _share(world, tmm.ANA).headers["location"]
    assert not _rows(world)
    r = _as(world, tmm.ANA).get("/my/moment/new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"


def test_the_composer_offers_what_they_may(world):
    html = _as(world, PASTOR).get("/my/moment/new").text
    assert 'action="/my/moment"' in html and 'name="photo"' in html and 'maxlength="120"' in html
    assert "Everyone at First Light Church" in html and "Checked like every post before anyone sees it." in html
    assert "A day" in html and "Until Sunday" in html and "3 days" in html and "Share moment" in html
    assert "video" not in html.lower()
    html = _as(world, tmm.BEN).get("/my/moment/new").text
    assert 'name="to" value="church"' not in html and f'name="to" value="{tmm.GRP}" checked' in html


def test_the_line_and_the_photo_are_required(world):
    assert "err=moment_empty" in _share(world, PASTOR, line="   ").headers["location"]
    assert "err=moment_long" in _share(world, PASTOR, line="x" * 121).headers["location"]
    assert "err=moment_photo" in _share(world, PASTOR, photo=None).headers["location"]
    assert not _rows(world) and not world.photos


def test_a_button_must_be_from_this_week(world):
    assert "err=moment_button" in _share(world, PASTOR, button="event:not-this-week").headers["location"]
    choices = [("gathering:g1@2026-11-22", "Tuesday Night · I'll be there", tmm.GRP)]
    assert mmo.check_button("gathering:g1@2026-11-22", choices, tmm.GRP) == ("gathering", "g1@2026-11-22", "")
    assert mmo.check_button("gathering:g1@2026-11-22", choices, "")[2] == "moment_button"
    assert mmo.check_button("none", choices, "") == ("", "", "")


# ─── how long ────────────────────────────────────────────────────────


def test_how_long_it_shows():
    biz = {"settings": {"timezone": "America/New_York"}}
    now = datetime(2026, 11, 23, 14, 0, tzinfo=timezone.utc)          # a Monday, 9 AM in New York
    assert mmo.ends_for("day", biz, now) - now == timedelta(days=1)
    assert mmo.ends_for("three", biz, now) - now == timedelta(days=3)
    sun = mmo.ends_for("sunday", biz, now)
    assert sun == datetime(2026, 11, 30, 4, 59, 59, tzinfo=timezone.utc)   # Sunday 11:59:59 PM in New York
    assert sun - now <= timedelta(days=7, hours=2)
    sunday = datetime(2026, 11, 29, 15, 0, tzinfo=timezone.utc)       # Sunday morning: tonight
    assert mmo.ends_for("sunday", biz, sunday) == datetime(2026, 11, 30, 4, 59, 59, tzinfo=timezone.utc)


def test_an_ended_moment_is_never_read(world):
    _moment(world, PASTOR, hours=-1)
    data = mmo.live(tmm.BIZ)
    assert data["moments"] == []
    m = _moment(world, PASTOR, hours=2)
    assert [x["id"] for x in mmo.live(tmm.BIZ)["moments"]] == [m["id"]]
    m["ends_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert not mmo.showing(m)


# ─── who sees it ─────────────────────────────────────────────────────


def _home(env, who, preview=False):
    env.who.update(id=who, preview=preview)
    return _app().get("/my").text


def test_a_group_moment_reaches_only_its_group(world):
    m = _moment(world, tmm.BEN, group=tmm.GRP, line="Friday night is back.")
    ana = _home(world, tmm.ANA)
    assert "Friday night is back." in ana and "Tuesday Night · from Ben Cole" in ana
    assert "Friday night is back." not in _home(world, tmm.TEEN)
    assert "Friday night is back." not in _home(world, tmm.CARL)
    assert _as(world, tmm.ANA).get(mmo.photo_href(m["id"]), follow_redirects=False).status_code == 302
    assert _as(world, tmm.TEEN).get(mmo.photo_href(m["id"]), follow_redirects=False).status_code == 404


def test_a_pastors_moment_reaches_everyone_with_a_private_reply_and_no_share(world):
    _moment(world, PASTOR, line="Praying for you this morning.")
    ana = _home(world, tmm.ANA)
    assert "A word from your pastor" in ana and "Praying for you this morning." in ana
    assert f'href="/my/messages/to/{PASTOR}"' in ana and "Send James a note…" in ana
    assert 'action="/my/moment/love"' in ana and 'data-seen="' in ana
    i = ana.index("Praying for you this morning.")
    section = ana[ana.rfind("<section", 0, i):ana.index("</section>", i)]
    assert "lm-share" not in section and "data-share-kind" not in section


def test_a_leaders_circle_holds_their_moments_newest_last_and_the_pastor_comes_first(world):
    _moment(world, tmm.BEN, group=tmm.GRP, line="Word from Ben", ago=1)
    _moment(world, PASTOR, line="First word", ago=3)
    _moment(world, PASTOR, line="Second word", ago=2)
    html = _home(world, tmm.ANA)
    ana = html[html.index('id="lm-mv"'):]                   # the viewer's slides, in order
    assert ana.index("First word") < ana.index("Second word") < ana.index("Word from Ben")
    assert html.count(f'data-mo="lp:{PASTOR}"') == 1 and ana.count('data-c="0"') >= 4   # two slides, two segments


def test_the_devotional_joins_its_pastors_circle():
    data = {"moments": [{"id": "m1", "posted_by": "p1", "group_id": None, "line": "Hi", "status": "shown",
                         "created_at": "2026-11-20T10:00:00+00:00", "ends_at": "2099-01-01T00:00:00+00:00"}],
            "people": {"p1": {"id": "p1", "name": "James Carter"}}, "groups": {}, "pastors": {"p1"}, "picked": set(),
            "marks": {}, "counts": {}, "write": {}}
    derived = {"id": "dv:1", "line": "Hold on", "name": "Pastor James Carter"}
    first, after, took = mmo.circles(data, me={"id": "me", "name": "Ana"}, groups={"mine": []},
                                     now=datetime(2026, 11, 20, 12, tzinfo=timezone.utc), church="First Light",
                                     button=lambda k, r: "", derived=derived, derived_who={"name": "Pastor James Carter"})
    assert took and len(first) == 1 and first[0]["slides"][-1] is derived and after == []
    _f, _a, took = mmo.circles(data, me={"id": "me"}, groups={"mine": []}, now=datetime(2026, 11, 20, 12, tzinfo=timezone.utc),
                               church="x", button=lambda k, r: "", derived=derived, derived_who={"name": "Pastor Ruth Miles"})
    assert not took


def test_a_leader_sees_their_circle_and_the_card_until_they_post(world):
    html = _home(world, tmm.BEN)
    assert 'class="lm-mo lm-mome lm-monew" href="/my/moment/new"' in html
    assert "Say something to your church today" in html and "at the start of your group's Home for a day." in html
    assert "Say something to your church today" not in _home(world, tmm.ANA)
    assert "/my/moment/new" not in _home(world, tmm.ANA)
    _moment(world, tmm.BEN, group=tmm.GRP)
    html = _home(world, tmm.BEN)
    assert "Say something to your church today" not in html and 'class="lm-moadd" href="/my/moment/new"' in html


# ─── the check ───────────────────────────────────────────────────────


def test_a_held_moment_shows_only_to_its_poster_and_the_officers(world):
    world.verdict = "harm"
    r = _share(world, PASTOR, line="Something unkind")
    assert r.headers["location"] == "/my?done=moment_held"
    (m,) = _rows(world)
    assert m["status"] == "held" and m["held_reason"] == "harm"
    assert "Something unkind" not in _home(world, tmm.ANA)
    mine = _home(world, PASTOR)
    assert "Something unkind" in mine and mmo.HELD in mine and "Only you can see this" in mine
    held = mmo.held(tmm.BIZ)
    assert [h["id"] for h in held] == [m["id"]] and held[0]["kind"] == "moment"
    assert held[0]["post_title"] == "their moment for the whole church"
    assert mmo.decide_held(tmm.BIZ, m["id"], True) is True
    assert _rows(world)[0]["status"] == "shown" and _rows(world)[0]["held_reason"] is None
    assert mmo.decide_held(tmm.BIZ, m["id"], True) is False


def test_the_officers_list_and_decide_held_moments_beside_comments(world, monkeypatch):
    m = _moment(world, PASTOR, status="held", reason="harm", line="Held words")
    world.t.setdefault("church_post_comments", [])
    world.t.setdefault("church_posts", [])
    monkeypatch.setattr(cn, "_need", lambda b, u, minimum: "owner")
    monkeypatch.setattr(mr, "require_officer", lambda b, u: None)
    got = cn.held_words(business_id=tmm.BIZ, user=None)["held"]
    assert [(h["id"], h["kind"], h["body"], h["name"]) for h in got] == [(m["id"], "moment", "Held words", "James Carter")]
    assert cn.decide_held(m["id"], cn.HeldIn(business_id=tmm.BIZ, show=False), user=None) == {"ok": True}
    assert _rows(world)[0]["status"] == "removed" and _rows(world)[0]["removed_by"] == "officer"


def test_crisis_words_are_held_the_pastor_is_told_and_988_shows(world):
    world.verdict = "self_harm"
    r = _share(world, tmm.BEN, to=tmm.GRP, line="I don't want to be here")
    assert r.headers["location"] == "/my?done=moment_care" and world.cared == [tmm.BEN]
    assert _rows(world)[0]["status"] == "held" and _rows(world)[0]["held_reason"] == "self_harm"
    assert "988" in mmo.DONE["moment_care"]
    assert "988" in _home(world, tmm.BEN)


def test_when_the_check_cant_run_nothing_posts(world):
    world.verdict = "down"
    r = _share(world, PASTOR)
    assert "err=moment_busy" in r.headers["location"] and not _rows(world) and not world.photos


def test_a_group_with_a_teen_gets_no_moments(world):
    r = _share(world, tmm.CARL, to=tmm.YOUTH)
    assert "err=moment_teens" in r.headers["location"] and not _rows(world) and not world.photos
    assert mmo.ERRORS["moment_teens"] == "Photos can't be shared in a group with teens in it."


# ─── taking it down ──────────────────────────────────────────────────


def _down(env, who, mid, preview=False):
    return _as(env, who, preview).post("/my/moment/remove", data={"id": mid}, headers=tmm.ORIGIN, follow_redirects=False)


def test_its_poster_takes_it_down(world):
    m = _moment(world, tmm.BEN, group=tmm.GRP)
    assert _down(world, tmm.BEN, m["id"]).headers["location"] == "/my?done=moment_down"
    assert m["status"] == "removed" and m["removed_by"] == "poster" and world.dropped == [m["media_path"]]


def test_a_pastor_or_the_owner_takes_anyones_down_and_nobody_else(world):
    a = _moment(world, tmm.BEN, group=tmm.GRP)
    assert "err=moment_gone" in _down(world, tmm.ANA, a["id"]).headers["location"]
    assert "err=moment_gone" in _down(world, tmm.CARL, a["id"]).headers["location"]
    assert a["status"] == "shown"
    assert _down(world, PASTOR, a["id"]).headers["location"] == "/my?done=moment_down"
    assert a["status"] == "removed" and a["removed_by"] == f"leader:{PASTOR}"
    b = _moment(world, PASTOR)
    assert "err=moment_gone" in _down(world, tmm.BEN, b["id"]).headers["location"]
    assert _down(world, tmm.ANA, b["id"], preview=True).headers["location"] == "/my?done=moment_down"
    assert b["removed_by"] == "owner"


# ─── seen and Love ───────────────────────────────────────────────────


def _mark(env, who, path, data):
    return _as(env, who).post(path, data=data, headers=tmm.ORIGIN, follow_redirects=False)


def test_seen_is_their_own_row_written_once(world):
    m = _moment(world, PASTOR)
    assert _mark(world, tmm.ANA, "/my/moment/seen", {"id": m["id"], "contact_id": tmm.BEN}).status_code == 204
    (row,) = world.t["church_moment_marks"]
    assert row["contact_id"] == tmm.ANA and row["business_id"] == tmm.BIZ and row["seen_at"]
    first = row["seen_at"]
    assert _mark(world, tmm.ANA, "/my/moment/seen", {"id": m["id"]}).status_code == 204
    assert len(world.t["church_moment_marks"]) == 1 and world.t["church_moment_marks"][0]["seen_at"] == first
    # Never their own moment, never one they may not see.
    assert _mark(world, PASTOR, "/my/moment/seen", {"id": m["id"]}).status_code == 404
    g = _moment(world, tmm.BEN, group=tmm.GRP)
    assert _mark(world, tmm.TEEN, "/my/moment/seen", {"id": g["id"]}).status_code == 404
    assert len(world.t["church_moment_marks"]) == 1


def test_love_is_one_upsert_and_can_be_taken_back(world):
    m = _moment(world, PASTOR)
    js = {**tmm.ORIGIN, "accept": "application/json"}
    c = _as(world, tmm.ANA)
    assert c.post("/my/moment/love", data={"id": m["id"], "on": "1"}, headers=js).status_code == 204
    (row,) = world.t["church_moment_marks"]
    assert row["loved_at"] and row["seen_at"]
    assert c.post("/my/moment/love", data={"id": m["id"], "on": "0"}, headers=js).status_code == 204
    assert len(world.t["church_moment_marks"]) == 1 and world.t["church_moment_marks"][0]["loved_at"] is None


def test_the_preview_marks_and_posts_nothing(world):
    m = _moment(world, PASTOR)
    env = world
    env.who.update(id=tmm.ANA, preview=True)
    c = _app()
    assert c.post("/my/moment/seen", data={"id": m["id"]}, headers=tmm.ORIGIN).status_code == 204
    r = c.post("/my/moment", data={"to": "church", "line": "Hi"}, files={"photo": ("p.png", PNG, "image/png")},
               headers=tmm.ORIGIN, follow_redirects=False)
    assert "err=preview" in r.headers["location"]
    assert not world.t["church_moment_marks"] and len(_rows(world)) == 1


def test_the_posters_sheet_counts_and_never_names(world):
    m = _moment(world, PASTOR, line="Our word")
    for who, loved in ((tmm.ANA, True), (tmm.BEN, False)):
        world.t["church_moment_marks"].append({"moment_id": m["id"], "business_id": tmm.BIZ, "contact_id": who,
                                               "seen_at": "2026-11-20T10:00:00+00:00",
                                               "loved_at": "2026-11-20T10:01:00+00:00" if loved else None})
    html = _home(world, PASTOR)
    i = html.index('class="lm-mvsheet"')
    sheet = html[i:html.index("</section>", i)]
    assert "Seen by 2" in sheet and "1 loved it" in sheet and "Take it down" in sheet
    assert "Replies come to your Messages" in sheet
    for name in ("Ana", "Rivers", "Ben", "Cole"):
        assert name not in sheet
    assert " left</small>" in html


# ─── before the tables are there ─────────────────────────────────────


def test_before_the_tables_are_there_nothing_shows_and_nothing_is_asked_twice(world, monkeypatch):
    get = sb_clients.sb_get_as_service
    asked = []

    def missing(path, **kw):
        if path.startswith("/church_moment"):
            asked.append(path)
            sb_clients._LAST.error = {"status": 404, "code": "PGRST205", "message": "not in the schema cache"}
            return None
        return get(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", missing)
    html = _home(world, tmm.BEN)
    assert "/my/moment" not in html and "Say something to your church today" not in html
    assert len(asked) == 1 and mmo.missing()
    _home(world, tmm.ANA)
    _home(world, PASTOR)
    assert len(asked) == 1                                   # kept: not asked again
    r = _as(world, PASTOR).get("/my/moment/new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert "err=moment_soon" in _share(world, PASTOR).headers["location"] and not world.photos


def test_a_failed_read_is_not_taken_for_missing_tables(world, monkeypatch):
    get = sb_clients.sb_get_as_service

    def down(path, **kw):
        if path.startswith("/church_moments"):
            sb_clients._LAST.error = {"status": 503, "code": "", "message": "upstream"}
            return None
        return get(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", down)
    assert mmo.live(tmm.BIZ) is None and not mmo.missing()


# ─── the new look off ────────────────────────────────────────────────


def test_with_the_new_look_off_nothing_writes_or_shows(world, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _moment(world, PASTOR, line="Only in the new look")
    assert _share(world, PASTOR).headers["location"] == "/my" and len(_rows(world)) == 1
    r = _as(world, PASTOR).get("/my/moment/new", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert "Only in the new look" not in _home(world, tmm.ANA)
