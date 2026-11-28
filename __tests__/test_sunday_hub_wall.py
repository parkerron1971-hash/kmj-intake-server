"""The one Sunday hub's read wall and its summary (sunday_summary.py; M-7).

Pins:
  * with SUNDAY_HUB on, a login holding no Sunday role, duty or part (a
    care-only Manager, a viewer seat) reads no Sunday plan: 403 on the plans,
    the songs, Who serves when and Teams. The status routes still answer,
    so the app can hide the menu. Every Sunday role, a Sunday duty alone and
    a team part all read
  * New here's "put it on Sunday's screen" reads no plan, so it's past the wall
  * with the switch off, nothing is walled (a viewer seat reads as before)
  * GET /worship/services/{id}/sunday: 404 with the switch off, 403 behind the
    wall, 404 for a stranger. It returns each step's part from one read
    (the plan and its sermon, the songs and their words, the screens, every
    team's spots, the stream, after Sunday)
  * the offering is in the answer only for a login the giving gate lets see
    it: the key is absent for anyone else, never null
  * one part that can't be read comes back null and is named in
    `unavailable`; the rest still answers"""
from __future__ import annotations

import os
import sys
import uuid as uuidlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sunday_hub as hub  # noqa: E402
import sunday_summary  # noqa: E402
import worship_team as wt  # noqa: E402
from sunday_hub_fixture import (ANA, BIZ, JO, KENDRA, LEE, PEOPLE, PRODUCTION, WELCOME, WORSHIP,  # noqa: E402,F401
                                church)

SONG = "a0000000-0000-4000-8000-000000000001"
SID = "b0000000-0000-4000-8000-000000000001"


@pytest.fixture
def sunday(church, monkeypatch):
    church.app.include_router(sunday_summary.router)
    db = church.db
    db.t["worship_songs"] = [{"id": SONG, "business_id": BIZ, "title": "It Is Well", "song_key": "D",
                              "sections": [{"id": "v1", "label": "Verse 1", "lines": ["When peace like a river"]}],
                              "archived_at": None}]
    db.t["worship_services"].append({
        "id": SID, "business_id": BIZ, "title": "Sunday service", "starts_at": "2026-10-25T16:05:00Z",
        "archived_at": None, "is_template": False, "kind": "service", "notes": "", "updated_at": None,
        "items": [
            {"id": "i1", "kind": "loop", "title": "Welcome loop", "minutes": 15},
            {"id": "i2", "kind": "countdown", "title": "We start soon", "minutes": 5},
            {"id": "i3", "kind": "song", "song_id": SONG, "minutes": 6},
            {"id": "i4", "kind": "song", "song_id": None, "minutes": 5},
            {"id": "i5", "kind": "scripture", "ref": "Joshua 4:6-7", "minutes": 3},
            {"id": "i6", "kind": "text", "title": "What Mean These Stones?", "who": "Pastor James", "minutes": 30,
             "slides": [{"text": "One"}, {"text": "Two"}, {"text": "Three"}, {"text": "Four"}]},
            {"id": "i7", "kind": "announcement", "title": "The week ahead", "image_url": None, "minutes": 1},
        ]})
    db.t["serve_notes"] = [{"business_id": BIZ, "service_id": SID, "item_id": "i3", "team": WORSHIP,
                            "note": "Keys alone first"},
                           {"business_id": BIZ, "service_id": SID, "item_id": "i1", "team": "all", "note": "Doors 10:45"},
                           {"business_id": BIZ, "service_id": SID, "item_id": "i5", "team": PRODUCTION, "note": "  "}]
    db.t["worship_screens"] = [{"id": str(uuidlib.uuid4()), "business_id": BIZ, "archived_at": None}
                               for _ in range(2)]
    db.t["worship_announcements"] = [
        {"id": "ann-1", "business_id": BIZ, "title": "Community Day", "image_url": None, "design": None,
         "show_from": "2026-10-20", "show_until": "2026-10-31", "shows": {"room": True}, "status": "approved",
         "archived_at": None, "event_on": "2026-10-31", "sort": 0},
        {"id": "ann-2", "business_id": BIZ, "title": "Baptism", "image_url": "https://x/y.png", "design": None,
         "show_from": None, "show_until": None, "shows": {"room": True}, "status": "approved", "archived_at": None,
         "event_on": None, "sort": 1}]
    # Welcome: Greeter (Ana yes) and Usher (open); Production: Sound (Kendra asked).
    db.t["serve_positions"] = [
        {"id": "p-greet", "business_id": BIZ, "group_id": WELCOME, "name": "Greeter", "needed": 1, "active": True,
         "sort": 0, "note": "", "created_at": "1"},
        {"id": "p-usher", "business_id": BIZ, "group_id": WELCOME, "name": "Usher", "needed": 1, "active": True,
         "sort": 1, "note": "", "created_at": "2"},
        {"id": "p-sound", "business_id": BIZ, "group_id": PRODUCTION, "name": "Sound", "needed": 1, "active": True,
         "sort": 0, "note": "", "created_at": "3"}]
    db.t["serve_assignments"] = [
        {"id": "a1", "business_id": BIZ, "service_id": SID, "position_id": "p-greet", "slot": 1, "contact_id": ANA,
         "status": "yes"},
        {"id": "a2", "business_id": BIZ, "service_id": SID, "position_id": "p-sound", "slot": 1, "contact_id": KENDRA,
         "status": "asked"}]
    db.t["sermons"] = []
    db.t["giving_counts"] = [{"id": "gc-1", "business_id": BIZ, "service_date": "2026-10-25"}]
    import church_work_checks as cw
    import giving_services as gs
    import stream_relay_router as srr
    monkeypatch.setattr(gs, "_gifts_of", lambda biz, ids: [{"amount_cents": 5000}, {"amount_cents": 2500}])
    monkeypatch.setattr(gs, "totals", lambda gifts: {"all": 7500, "gifts": len(gifts)})
    monkeypatch.setattr(srr, "is_ready", lambda: True)
    monkeypatch.setattr(srr, "stream_row", lambda biz: {"key_hash": "h", "youtube_on": True, "facebook_on": False})
    monkeypatch.setattr(srr, "watch_session", lambda url: "sess" if "watch" in url else None)
    monkeypatch.setattr(cw, "sunday_counted", lambda ctx, day, until: False)
    return church


def _get(c, who, sid=SID):
    return c.as_(who).get(f"/worship/services/{sid}/sunday", params={"business_id": BIZ})


# ─── the wall ─────────────────────────────────────────────────────────

WALLED = [("/worship/services", {}), ("/worship/songs", {}), ("/planning/schedule", {}), ("/planning/teams", {})]


@pytest.mark.parametrize("who", ["carer", "viewer"])
def test_no_sunday_role_reads_no_sunday_plan(sunday, who):
    for path, extra in WALLED:
        r = sunday.as_(who).get(path, params={"business_id": BIZ, **extra})
        assert r.status_code == 403, (who, path, r.text)
        assert r.json()["detail"] == hub.WALL
    # The status routes always answer.
    assert sunday.as_(who).get("/worship/status", params={"business_id": BIZ}).status_code == 200
    assert sunday.as_(who).get("/planning/status", params={"business_id": BIZ}).status_code == 200


@pytest.mark.parametrize("who", ["owner", "admin", "planner", "csadmin", "worship", "booth", "streamer", "ministry",
                                 "volsched", "leader"])
def test_every_sunday_role_reads(sunday, who):
    for path, extra in WALLED:
        r = sunday.as_(who).get(path, params={"business_id": BIZ, **extra})
        assert r.status_code == 200, (who, path, r.text)


def test_new_heres_screen_card_is_past_the_wall(sunday):
    assert wt.roles_of(BIZ, PEOPLE["carer"], wall=False) == set()


def test_nothing_is_walled_with_the_switch_off(sunday, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    for path, extra in WALLED:
        assert sunday.as_("viewer").get(path, params={"business_id": BIZ, **extra}).status_code == 200


# ─── the summary ──────────────────────────────────────────────────────

def test_the_summary_is_dark_and_walled(sunday, monkeypatch):
    assert _get(sunday, "carer").status_code == 403
    assert _get(sunday, "stranger").status_code == 404
    assert _get(sunday, "owner", sid="b0000000-0000-4000-8000-00000000ffff").status_code == 404
    monkeypatch.setenv("SUNDAY_HUB", "off")
    assert _get(sunday, "owner").status_code == 404


def test_the_summary_reads_each_step(sunday):
    r = _get(sunday, "owner")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["unavailable"] == []
    assert s["service"]["item_count"] == 7 and s["service"]["minutes"] == 65.0
    assert s["service"]["ends_at"].startswith("2026-10-25T17:10")
    assert s["service"]["live_ok"] == {"on": False, "until": None, "by": None}
    assert s["plan"]["sermon"] == {"title": "What Mean These Stones?", "ref": "Joshua 4:6-7", "who": "Pastor James",
                                   "points": 4}
    assert s["plan"]["notes"]["written"] == 2
    assert {t["name"]: t["written"] for t in s["plan"]["notes"]["teams"]} == {"Production": 0, "Welcome": 0, "Worship": 1}
    assert s["songs"]["count"] == 2 and s["songs"]["ready"] == 1
    first, slot = s["songs"]["items"]
    assert first == {"item_id": "i3", "song_id": SONG, "title": "It Is Well", "key": "D", "words_ready": True,
                     "team": WORSHIP}
    assert slot["title"] == "Pick a song" and slot["words_ready"] is False
    sc = s["screens"]
    assert sc["announcements_showing"] == 2 and sc["screens"] == 2 and sc["loop"] is True
    assert sc["countdown_minutes"] == 5
    assert [m["title"] for m in sc["missing_pictures"]] == ["Community Day", "The week ahead"]
    sv = s["serving"]
    assert (sv["filled"], sv["asked"], sv["open"]) == (1, 1, 1)
    welcome = next(t for t in sv["teams"] if t["group_id"] == WELCOME)
    assert welcome["spots"] == [
        {"position_id": "p-greet", "place": "Greeter", "person": "Ana Cruz", "status": "yes"},
        {"position_id": "p-usher", "place": "Usher", "person": None, "status": "open"}]
    assert welcome["owner"] == "volunteers" and welcome["open_to_ops"] is False and welcome["mine"] is False
    assert s["live"]["stream"] == {"ready": True, "destinations": ["youtube"]}
    assert s["after"]["count_recorded"] is False and s["after"]["sermon_draft"] is None
    assert s["after"]["offering"] == {"total_cents": 7500, "gifts": 2}


def test_a_leader_sees_which_team_is_theirs(sunday):
    s = _get(sunday, "leader").json()
    assert next(t for t in s["serving"]["teams"] if t["group_id"] == WELCOME)["mine"] is True
    assert next(t for t in s["serving"]["teams"] if t["group_id"] == PRODUCTION)["mine"] is False


def test_the_offering_only_with_giving_access(sunday):
    for who in ("planner", "booth", "leader", "ministry"):
        s = _get(sunday, who).json()
        assert "offering" not in s["after"], who
    sunday.state["giving"].add("u-planner")
    assert _get(sunday, "planner").json()["after"]["offering"]["total_cents"] == 7500


def test_an_admin_the_giving_keeper_holds_back_sees_no_offering(sunday):
    sunday.state["giving"].discard("u-admin")
    s = _get(sunday, "admin").json()
    assert "offering" not in s["after"]
    sunday.state["giving"].discard("u-owner")
    assert "offering" not in _get(sunday, "owner").json()["after"]


def test_the_sermon_the_stream_saved(sunday):
    sunday.db.t["sermons"].append({"id": "ser-1", "business_id": BIZ, "title": "", "published": False,
                                   "preached_on": "2026-10-25", "video_url": "https://api/stream-relay/watch/x",
                                   "created_at": "1"})
    assert _get(sunday, "booth").json()["after"]["sermon_draft"] == {"id": "ser-1", "title": ""}


def test_one_part_failing_leaves_the_rest(sunday, monkeypatch):
    import sb_clients
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/serve_notes") else real(path, *a, **k))
    s = _get(sunday, "owner").json()
    assert s["plan"] is None and s["unavailable"] == ["plan"]
    assert s["songs"]["count"] == 2 and s["serving"]["filled"] == 1
