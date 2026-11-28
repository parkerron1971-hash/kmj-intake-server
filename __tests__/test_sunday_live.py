"""The one Sunday hub's plan writes (sunday_live.py; M-7, Kevin's decisions
church-office-1, 2026-11-27).

Pins:
  * only the owner and Admin seats open a Sunday for live changes; it lasts
    to the end of that Sunday's day on the church's clock, and closing it
    clears it; 404 with the switch off
  * media & tech (Booth or Media part, or the stream duty): the plan is
    refused on any Sunday ("The pastor hasn't opened this Sunday..."); on the
    opened Sunday its whole plan saves, never another Sunday's, never after
    the mark runs out, never a new Sunday or taking one out
  * the booth's typo fix stays open on every Sunday
  * a team leader changes only their own team's items: a song's key in
    Worship's set yes; the sermon, the order, the title or another team's
    item no; never an item's team
  * the planner and the pastor change the whole plan, as before
  * an item keeps the team the planner gave it
  * team areas: read by readers, set in Sunday setup (the setup part), only
    to the church's own Sunday teams
  * with the switch off, every plan write is the Plan part's, exactly as
    before (the leader's set of songs, the booth refused)"""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sunday_live  # noqa: E402
from sunday_hub_fixture import BIZ, PEOPLE, PRODUCTION, WELCOME, WORSHIP, church  # noqa: E402,F401

SONG = "a0000000-0000-4000-8000-000000000001"
S1 = "b0000000-0000-4000-8000-000000000001"
S2 = "b0000000-0000-4000-8000-000000000002"
import worship_show as wsh  # noqa: E402

ITEMS = wsh.clean_items([
    {"id": "i1", "kind": "countdown", "title": "We start soon", "minutes": 5},
    {"id": "i2", "kind": "song", "song_id": SONG, "minutes": 6},
    {"id": "i3", "kind": "section", "title": "The Word"},
])

@pytest.fixture
def live(church):
    church.app.include_router(sunday_live.router)
    for sid, starts in ((S1, "2026-10-25T16:05:00Z"), (S2, "2026-11-01T17:05:00Z")):
        church.db.t["worship_services"].append({"id": sid, "business_id": BIZ, "title": "Sunday service",
                                                "starts_at": starts, "items": copy.deepcopy(ITEMS), "notes": "",
                                                "archived_at": None, "is_template": False, "kind": "service",
                                                "updated_at": None})
    church.db.t["worship_songs"] = [{"id": SONG, "business_id": BIZ, "title": "It Is Well", "song_key": "D",
                                     "sections": [{"id": "v1", "label": "Verse 1", "lines": ["When peace"]}],
                                     "archived_at": None, "has_words": True}]
    return church


def _items(db, sid):
    return copy.deepcopy(next(s for s in db.t["worship_services"] if s["id"] == sid)["items"])


def _save(c, who, sid, **fields):
    return c.as_(who).put(f"/worship/services/{sid}", json={"business_id": BIZ, **fields})


def _open(c, who, sid, on=True):
    return c.as_(who).put(f"/worship/services/{sid}/live-ok", json={"business_id": BIZ, "on": on})


# ─── the mark ─────────────────────────────────────────────────────────

def test_only_the_pastor_opens_a_sunday(live):
    for who in ("planner", "csadmin", "worship", "booth", "streamer", "ministry", "leader"):
        r = _open(live, who, S1)
        assert r.status_code == 403 and r.json()["detail"] == sunday_live.ONLY_PASTOR, who
    r = _open(live, "admin", S1)
    assert r.status_code == 200
    got = r.json()["live_ok"]
    # To the end of that Sunday's day in Chicago (CDT): 04:59:59 UTC the next morning.
    assert got["on"] is False or got["until"].startswith("2026-10-26T04:59:59")


def test_the_mark_is_the_end_of_that_day(live):
    end = sunday_live._end_of_day(BIZ, "2026-10-25T16:05:00Z")
    assert end == datetime(2026, 10, 26, 4, 59, 59, tzinfo=timezone.utc)


def _mark(db, sid, minutes=60, by="u-owner"):
    row = next(s for s in db.t["worship_services"] if s["id"] == sid)
    row["live_ok_until"] = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    row["live_ok_by"] = by


def test_closing_it_clears_it(live):
    _mark(live.db, S1)
    assert live.as_("owner").get(f"/worship/services/{S1}", params={"business_id": BIZ}).json()["service"]["live_ok"]["on"]
    assert _open(live, "owner", S1, on=False).json()["live_ok"] == {"on": False, "until": None, "by": None}
    row = next(s for s in live.db.t["worship_services"] if s["id"] == S1)
    assert row["live_ok_until"] is None and row["live_ok_by"] is None


def test_the_list_says_which_sunday_is_open(live):
    _mark(live.db, S2)
    rows = live.as_("booth").get("/worship/services", params={"business_id": BIZ}).json()["services"]
    assert {r["id"]: r["live_ok"]["on"] for r in rows} == {S1: False, S2: True}
    assert next(r for r in rows if r["id"] == S2)["live_ok"]["by"] == {"name": "The owner"}
    assert next(r for r in rows if r["id"] == S1)["live_ok"]["by"] is None


# ─── media & tech ─────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["booth", "streamer"])
def test_media_and_tech_only_on_the_opened_sunday(live, who):
    items = _items(live.db, S1)
    items[1]["minutes"] = 8
    r = _save(live, who, S1, items=items)
    assert r.status_code == 403 and r.json()["detail"] == sunday_live.NOT_OPENED
    _mark(live.db, S1)
    assert _save(live, who, S1, items=items).status_code == 200
    assert _save(live, who, S1, notes="Run long on the response").status_code == 200   # its items and notes
    for change in ({"title": "Sunday, live"}, {"starts_at": "2026-10-25T17:00:00Z"}, {"is_template": True}):
        r = _save(live, who, S1, items=items, **change)                    # never its time, name or template
        assert r.status_code == 403 and r.json()["detail"] == sunday_live.LIVE_ONLY, change
    assert _save(live, who, S2, items=_items(live.db, S2)[:1]).status_code == 403  # never another Sunday
    assert live.as_(who).post("/worship/services", json={"business_id": BIZ, "title": "New"}).status_code == 403
    assert live.as_(who).delete(f"/worship/services/{S1}", params={"business_id": BIZ}).status_code == 403
    _mark(live.db, S1, minutes=-1)                                              # the mark ran out
    assert _save(live, who, S1, items=_items(live.db, S1)[:2]).status_code == 403


def test_the_typo_fix_stays_open_every_sunday(live):
    # Nobody opened either Sunday: the booth still fixes a typo on the slide that's up.
    r = live.as_("booth").post(f"/worship/songs/{SONG}/fix", json={
        "business_id": BIZ, "section_id": "v1", "old": ["When peace"], "new": ["When peace like a river"]})
    assert r.status_code == 200, r.text
    assert live.db.t["worship_songs"][0]["sections"][0]["lines"] == ["When peace like a river"]
    # It changes words only; the plan is still refused.
    assert _save(live, "booth", S1, items=_items(live.db, S1)[:1]).status_code == 403


# ─── team leaders ─────────────────────────────────────────────────────

def test_a_leader_changes_only_their_teams_items(live):
    items = _items(live.db, S1)
    items[1]["minutes"] = 9                                                 # Worship's song: theirs
    assert _save(live, "worship", S1, items=items).status_code == 200
    items = _items(live.db, S1)
    items[0]["title"] = "Almost time"                                       # the countdown: Production's
    r = _save(live, "worship", S1, items=items)
    assert r.status_code == 403 and r.json()["detail"] == "That item is the Production's."
    items = _items(live.db, S1)
    items[2]["title"] = "The message"                                       # a section: the planner's
    assert _save(live, "worship", S1, items=items).json()["detail"] == "That item is the planner's."
    r = _save(live, "worship", S1, items=list(reversed(_items(live.db, S1))))   # moving the order
    assert r.status_code == 403 and r.json()["detail"] == sunday_live.THE_ORDER
    assert _save(live, "worship", S1, items=_items(live.db, S1)[:2]).status_code == 403   # taking one out
    assert _save(live, "worship", S1, title="Mine now").json()["detail"] == sunday_live.THE_ORDER
    items = _items(live.db, S1)
    items[1]["team"] = PRODUCTION                                           # moving it to another team
    assert _save(live, "worship", S1, items=items).json()["detail"] == "Only the planner moves an item to another team."
    assert live.as_("worship").post("/worship/services", json={"business_id": BIZ}).status_code == 403


def test_a_leader_of_a_team_with_an_item(live):
    # The planner gives the countdown to Welcome; Welcome's leader (no part at all) may change it.
    items = _items(live.db, S1)
    items[0]["team"] = WELCOME
    assert _save(live, "planner", S1, items=items).status_code == 200
    assert _items(live.db, S1)[0]["team"] == WELCOME                        # the item keeps its team
    items = _items(live.db, S1)
    items[0]["minutes"] = 10
    assert _save(live, "leader", S1, items=items).status_code == 200
    items[1]["minutes"] = 1
    assert _save(live, "leader", S1, items=items).status_code == 403


def test_the_planner_and_the_pastor_change_the_whole_plan(live):
    for who in ("planner", "csadmin", "owner", "admin"):
        assert _save(live, who, S1, items=list(reversed(_items(live.db, S1))), title=f"By {who}").status_code == 200
    assert live.as_("planner").post("/worship/services", json={"business_id": BIZ}).status_code == 200


# ─── team areas ───────────────────────────────────────────────────────

def test_team_areas(live):
    got = live.as_("booth").get("/worship/team-areas", params={"business_id": BIZ}).json()
    assert got["areas"]["song"] == WORSHIP and got["areas"]["loop"] == PRODUCTION
    assert {t["name"] for t in got["teams"]} == {"Worship", "Production", "Welcome"}

    def put(path, json):
        return live.as_("owner").put(path, json=json)
    assert put("/worship/team-areas", json={"business_id": BIZ, "areas": {"song": WELCOME}}).status_code == 200
    assert live.as_("booth").get("/worship/team-areas", params={"business_id": BIZ}).json()["areas"]["song"] == WELCOME
    assert put("/worship/team-areas", json={"business_id": BIZ, "areas": {"song": SONG}}).status_code == 400
    assert put("/worship/team-areas", json={"business_id": BIZ, "areas": {"dance": WELCOME}}).status_code == 400
    assert live.as_("planner").put("/worship/team-areas",
                                   json={"business_id": BIZ, "areas": {"song": None}}).status_code == 403


# ─── the switch off ───────────────────────────────────────────────────

def test_off_the_plan_part_decides_as_before(live, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    # The Worship part plans the whole service, as it always has.
    assert _save(live, "worship", S1, items=list(reversed(_items(live.db, S1)))).status_code == 200
    _mark(live.db, S1)
    r = _save(live, "booth", S1, items=_items(live.db, S1))
    assert r.status_code == 403 and r.json()["detail"] != sunday_live.NOT_OPENED   # the Plan part's own refusal
    assert _open(live, "owner", S1).status_code == 404
    assert "live_ok" not in live.as_("owner").get(f"/worship/services/{S1}", params={"business_id": BIZ}).json()["service"]
    assert live.as_("owner").get("/worship/team-areas", params={"business_id": BIZ}).status_code == 404
