# __tests__/test_worship_announce.py
#
# The announcements board (worship_announce.py, worship_announce_router.py;
# ChurchSavvy round 5, canvas boards 18-21). Pins:
#   * an announcement is checked: a title, short words, an https picture, one
#     of six designs, a QR code that opens an https address, dates in order
#   * its tab on a day: waiting, coming up, showing, past (the day after it ends)
#   * "This Saturday" counts a church's week from Sunday
#   * what shows on a kind of screen, nearest first; designs that need a date or
#     a picture fall back when they have none; "this week" carries the list
#   * Sunday's spot and the welcome loop fill themselves from the board for the
#     service's day, the logo between; nothing on the board leaves the logo up
#   * over HTTP: the plan's part makes, changes, decides and takes off; a member
#     reads; a board that can't be read leaves the rest of Sunday on screen

import pathlib
import sys
import uuid as uuidlib
from datetime import date
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import sb_clients
import worship_announce as wa
import worship_announce_router as war
import worship_show as wsh
import worship_show_router as wsr
import worship_team
from auth_supabase import AuthedUser, require_user

SUN = date(2026, 11, 1)  # Sunday, Nov 1 2026: the canvas's Sunday


def row(**kw):
    base = {"id": str(uuidlib.uuid4()), "title": "Community Day", "when_text": "Sat, Nov 7 · 11 AM to 3 PM",
            "where_text": "The church lawn", "body": "Food and games.", "image_url": "https://x.example/lawn.webp",
            "design": "side", "event_on": "2026-11-07", "qr": {}, "show_from": None, "show_until": "2026-11-07",
            "shows": {"room": True, "lobby": True, "online": False, "phones": True}, "status": "on",
            "source": "typed", "sort": 0, "archived_at": None, "created_at": "2026-10-25T00:00:00+00:00"}
    base.update(kw)
    return base


# ─── checking one ────────────────────────────────────────────────────

def test_clean_checks_each_field():
    ok = wa.clean({"title": "  Community   Day ", "body": "Bring a neighbor.", "design": "card", "event_on": "2026-11-07",
                   "show_from": "2026-10-25", "show_until": "2026-11-07", "shows": {"room": 1, "lobby": 0},
                   "qr": {"kind": "form", "url": "https://forms.example/help"}})
    assert ok["title"] == "Community Day"
    assert ok["shows"] == {"room": True, "lobby": False, "online": False, "phones": False}
    assert ok["qr"] == {"kind": "form", "url": "https://forms.example/help", "label": "Scan to sign up"}
    for bad, words in [({"title": ""}, "title"), ({"title": "x" * 81}, "at most 80"),
                       ({"title": "A", "body": "x" * 141}, "at most 140"),
                       ({"title": "A", "image_url": "http://x.example/a.png"}, "https"),
                       ({"title": "A", "design": "poster"}, "designs"),
                       ({"title": "A", "qr": {"kind": "form", "url": "javascript:alert(1)"}}, "https"),
                       ({"title": "A", "qr": {"kind": "fax"}}, "QR code opens"),
                       ({"title": "A", "event_on": "11/07/2026"}, "date"),
                       ({"title": "A", "show_from": "2026-11-08", "show_until": "2026-11-07"}, "before it starts")]:
        with pytest.raises(ValueError, match=words):
            wa.clean(bad)
    assert wa.clean({"qr": {"kind": "none"}}, partial=True) == {"qr": {}}
    assert wa.clean({"body": "Just this"}, partial=True) == {"body": "Just this"}


def test_its_tab_on_a_day():
    assert wa.state(row(status="waiting"), SUN) == "wait"
    assert wa.state(row(status="declined"), SUN) == "declined"
    assert wa.state(row(show_until="2026-10-31"), SUN) == "past"
    assert wa.state(row(show_until="2026-11-01"), SUN) == "now"       # its last day still shows
    assert wa.state(row(show_from="2026-11-08", show_until="2026-11-25"), SUN) == "soon"
    assert wa.state(row(show_from=None, show_until=None), SUN) == "now"


def test_this_saturday_counts_the_week_from_sunday():
    assert wa.kicker("2026-11-07", SUN) == "This Saturday"
    assert wa.kicker("2026-11-01", SUN) == "Today"
    assert wa.kicker("2026-11-02", SUN) == "Tomorrow"
    assert wa.kicker("2026-11-08", SUN) == "Next Sunday"
    assert wa.kicker("2026-11-13", SUN) == "Next Friday"
    assert wa.kicker("2026-11-15", SUN) == ""
    assert wa.kicker("2026-10-30", SUN) == ""
    # From a Wednesday, the Saturday after is still this week.
    assert wa.kicker("2026-11-07", date(2026, 11, 4)) == "This Saturday"


def test_what_shows_on_a_screen_nearest_first():
    rows = [row(title="Food giveaway", event_on="2026-11-21", show_until="2026-11-21"),
            row(title="Baptism Sunday", event_on="2026-11-15", show_until="2026-11-15", design="date"),
            row(title="Lobby only", shows={"lobby": True}),
            row(title="No date", event_on=None, show_until=None),
            row(title="Waiting", status="waiting"),
            row(title="Over", show_until="2026-10-30", event_on="2026-10-30"),
            row(title="Community Day")]
    room = [r["title"] for r in wa.showing(rows, SUN, "room")]
    assert room == ["Community Day", "Baptism Sunday", "Food giveaway", "No date"]
    assert "Lobby only" in [r["title"] for r in wa.showing(rows, SUN, "lobby")]


def test_designs_fall_back_and_the_week_list():
    s = wa.slide(row(design="date"), SUN)
    assert (s["design"], s["day"], s["month"], s["kick"]) == ("date", "7", "Nov", "This Saturday")
    assert wa.slide(row(design="date", event_on=None), SUN)["design"] == "side"
    assert wa.slide(row(design="card", image_url=""), SUN)["design"] == "save"
    assert wa.slide(row(design="flyer", image_url=""), SUN)["design"] == "side"
    board = [row(title="Community Day"), row(title="New Members class", event_on="2026-11-08"), row(title="No date", event_on=None)]
    week = wa.slide(row(design="week"), SUN, board)
    assert week["list"] == [{"day": "Sat 7", "title": "Community Day", "when": "Sat, Nov 7 · 11 AM to 3 PM"},
                            {"day": "Sun 8", "title": "New Members class", "when": "Sat, Nov 7 · 11 AM to 3 PM"}]


# ─── Sunday fills itself ─────────────────────────────────────────────

BOARD = [wa.slide(row(title=t, event_on=d), SUN) for t, d in
         [("Community Day", "2026-11-07"), ("New Members class", "2026-11-08"), ("Baptism Sunday", "2026-11-15"),
          ("Youth lock-in", "2026-11-13"), ("Food giveaway", "2026-11-21")]]


def test_the_spot_and_the_loop_fill_themselves():
    spot = wsh.clean_item({"id": "week", "kind": "announcement", "from_board": True})
    assert spot["count"] == 3 and spot["title"] == "This week"
    with pytest.raises(ValueError, match="1 to 8"):
        wsh.clean_item({"id": "week", "kind": "announcement", "from_board": True, "count": 12})
    out = wsh.compile_item(spot, {}, "2026-11-01T16:05:00Z", BOARD)
    assert [s["title"] for s in out["slides"]] == ["Community Day", "New Members class", "Baptism Sunday"]

    loop = wsh.clean_item({"id": "welcome", "kind": "loop", "from_board": True, "corner": True})
    assert loop["slides"] == [] and loop["logo_every"] == 2
    out = wsh.compile_item(loop, {}, "2026-11-01T16:05:00Z", BOARD)
    kinds = [s.get("title") or s["kind"] for s in out["slides"]]
    assert kinds == ["logo", "Community Day", "New Members class", "logo", "Baptism Sunday", "Youth lock-in", "logo", "Food giveaway"]
    assert out["loop"]["corner"] is True and out["loop"]["count_to"] == "2026-11-01T16:05:00Z"
    assert all(s["seconds"] == 7 for s in out["slides"] if s["kind"] == "announcement")

    empty = wsh.compile_item(loop, {}, None, [])
    assert empty["slides"] == [{"kind": "logo", "seconds": 7}]
    # A loop of its own still needs a slide; one from the board doesn't.
    with pytest.raises(ValueError, match="1 to"):
        wsh.clean_item({"id": "own", "kind": "loop", "slides": []})
    # Old items are untouched.
    old = wsh.clean_item({"id": "ann", "kind": "announcement", "title": "Picnic"})
    assert "from_board" not in old and wsh.compile_item(old, {})["slides"][0]["title"] == "Picnic"
    assert wsh.uses_board([spot]) and not wsh.uses_board([old])


# ─── over HTTP ───────────────────────────────────────────────────────

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
PEOPLE = {"owner": AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated"),
          "member": AuthedUser(id="u-member", email="jas@lovecity.org", role="authenticated"),
          "stranger": AuthedUser(id="u-stranger", email="who@else.org", role="authenticated")}
SEATS = {("u-owner", BIZ): "owner", ("u-member", BIZ): "member"}


class FakeDb:
    def __init__(self):
        self.t = {"businesses": [{"id": BIZ, "name": "Love City Church", "settings": {}}],
                  "worship_announcements": [], "worship_services": [], "worship_songs": [], "worship_settings": [],
                  "worship_team": []}
        self.fail = set()

    @staticmethod
    def _split(path):
        table, _, q = path.lstrip("/").partition("?")
        return table, [(k, v) for k, v in parse_qsl(q, keep_blank_values=True) if k not in ("select", "order", "limit")]

    @staticmethod
    def _match(r, f):
        for k, v in f:
            if v == "is.null" and r.get(k) is not None:
                return False
            if v.startswith("eq.") and str(r.get(k)) != v[3:]:
                return False
        return True

    def get(self, path, **_):
        table, f = self._split(path)
        if table in self.fail:
            return None
        return [dict(r) for r in self.t.get(table, []) if self._match(r, f)]

    def post(self, path, body, prefer=None, **_):
        table, _f = self._split(path)
        if table in self.fail:
            return None
        r = {"id": str(uuidlib.uuid4()), "archived_at": None, **body}
        self.t[table].append(r)
        return None if prefer == "return=minimal" else [dict(r)]

    def patch(self, path, body):
        table, f = self._split(path)
        if table in self.fail:
            return None
        hit = [r for r in self.t[table] if self._match(r, f)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setattr(war, "church_zone", lambda biz: ZoneInfo("America/New_York"))
    monkeypatch.setattr(worship_team, "role_of", lambda biz, uid: SEATS.get((uid, biz)))
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(wsr.router)
    app.include_router(war.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client
    return db, as_


def test_make_change_decide_and_take_off(api):
    db, as_ = api
    r = as_("owner").post("/worship/announcements", json={"business_id": BIZ, "title": "Community Day", "event_on": "2026-11-07",
                                                           "design": "date", "shows": {"room": True, "phones": True}})
    assert r.status_code == 200, r.text
    a = r.json()["announcement"]
    # It shows until the day it happens when nobody said otherwise.
    assert a["show_until"] == "2026-11-07" and a["status"] == "on" and a["source"] == "typed"
    assert as_("owner").post("/worship/announcements", json={"business_id": BIZ, "title": ""}).status_code == 400
    # A member reads the board but doesn't change it; a stranger gets nothing.
    seen = as_("member").get(f"/worship/announcements?business_id={BIZ}&day=2026-11-01")
    assert seen.status_code == 200 and seen.json()["can_write"] is False
    assert as_("owner").get(f"/worship/announcements?business_id={BIZ}").json()["can_write"] is True
    assert as_("member").post("/worship/announcements", json={"business_id": BIZ, "title": "Mine"}).status_code in (403, 404)
    assert as_("stranger").get(f"/worship/announcements?business_id={BIZ}").status_code in (403, 404)

    r = as_("owner").put(f"/worship/announcements/{a['id']}", json={"business_id": BIZ, "body": "Bring a neighbor."})
    assert r.status_code == 200 and r.json()["announcement"]["body"] == "Bring a neighbor."
    bad = as_("owner").put(f"/worship/announcements/{a['id']}", json={"business_id": BIZ, "show_from": "2026-11-20"})
    assert bad.status_code == 400 and "before it starts" in bad.text

    # A ministry's request waits; putting it on moves it to the board.
    db.t["worship_announcements"].append(row(id=str(uuidlib.uuid4()), business_id=BIZ, title="Women's brunch",
                                             status="waiting", source="ministry", event_on="2026-11-14", show_until="2026-11-14"))
    board = as_("owner").get(f"/worship/announcements?business_id={BIZ}&day=2026-11-01").json()
    assert board["counts"] == {"now": 1, "soon": 0, "wait": 1, "past": 0}
    wait_id = next(x["id"] for x in board["announcements"] if x["tab"] == "wait")
    assert as_("owner").post(f"/worship/announcements/{wait_id}/decide", json={"business_id": BIZ, "decision": "on"}).status_code == 200
    assert as_("owner").get(f"/worship/announcements?business_id={BIZ}&day=2026-11-01").json()["counts"]["now"] == 2

    assert as_("owner").delete(f"/worship/announcements/{a['id']}?business_id={BIZ}").status_code == 200
    assert as_("owner").get(f"/worship/announcements?business_id={BIZ}&day=2026-11-01").json()["counts"]["now"] == 1
    # The past keeps a year; a declined one is off the board.
    assert as_("owner").get(f"/worship/announcements?business_id={BIZ}&day=2026-12-01").json()["counts"]["past"] == 1


def test_sunday_fills_from_the_board_for_its_day(api):
    db, as_ = api
    for t, d in [("Community Day", "2026-11-07"), ("Over already", "2026-10-25"), ("Baptism Sunday", "2026-11-15")]:
        db.t["worship_announcements"].append(row(business_id=BIZ, title=t, event_on=d, show_until=d))
    items = [{"id": "welcome", "kind": "loop", "from_board": True, "corner": True},
             {"id": "week", "kind": "announcement", "from_board": True, "count": 2}]
    # 11:05 AM Eastern on Nov 1 is 16:05 UTC.
    svc = as_("owner").post("/worship/services", json={"business_id": BIZ, "title": "Sunday, Nov 1",
                                                       "starts_at": "2026-11-01T16:05:00Z", "items": items})
    assert svc.status_code == 200, svc.text
    sid = svc.json()["service"]["id"]
    show = as_("owner").get(f"/worship/services/{sid}/show?business_id={BIZ}").json()
    loop, spot = show["items"]
    assert [s.get("title") for s in spot["slides"]] == ["Community Day", "Baptism Sunday"]
    assert spot["slides"][0]["kick"] == "This Saturday"
    assert [s["kind"] for s in loop["slides"]] == ["logo", "announcement", "announcement"]

    # A board that can't be read leaves Sunday on screen: the loop shows the logo.
    db.fail.add("worship_announcements")
    show = as_("owner").get(f"/worship/services/{sid}/show?business_id={BIZ}")
    assert show.status_code == 200
    assert show.json()["items"][0]["slides"] == [{"kind": "logo", "seconds": 7}]
    assert show.json()["items"][1]["slides"] == []
