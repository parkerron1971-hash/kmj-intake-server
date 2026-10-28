# __tests__/test_sunday_order.py
#
# ChurchSavvy Planning, step 4: one order of service for every team
# (sunday_order.py; canvas board 3). Pins:
#   * the order is ChurchSavvy's own plan: each item's time from the start
#     and the minutes before it, "Before" items counting back to the start,
#     the end; a song is its title and key from the library, never its words
#   * a note for a team (or for everyone) on one item: only whoever
#     schedules writes it, only on an item that's in the plan, only for one
#     of the church's Sunday teams; an empty note takes it off
#   * a save in ChurchSavvy never touches a team's note; a note on an item
#     taken out of the plan, or for a team that stopped being a Sunday team,
#     isn't shown
#   * everyone on the team reads; nobody else does; the switch hides it all

import json
import pathlib
import sys
import uuid as uuidlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_sunday_planning as tsp
from test_sunday_planning import BIZ, PEOPLE, PRODUCTION, WELCOME, api, make_team, services, sundays  # noqa: F401

import sunday_order as so
import sunday_planning as sp
from auth_supabase import require_user

SONG = "5c000000-0000-4000-8000-000000000001"


@pytest.fixture
def order(api, monkeypatch):
    """Production and Welcome are Sunday teams; the first Sunday (Oct 25,
    10:30) has a plan: a welcome loop before, then a song, a passage and the
    sermon."""
    db, as_ = api
    db.KEYS = {**db.KEYS, "serve_notes": ("service_id", "item_id", "team")}
    db.t["serve_notes"] = []
    db.t["worship_songs"] = [{"id": SONG, "business_id": BIZ, "title": "Firm Foundation", "song_key": "B",
                              "sections": [{"id": "v1", "label": "V1", "lines": ["(the song's own words)"]},
                                           {"id": "c", "label": "C", "lines": ["(more of its words)"]},
                                           {"id": "b", "label": "B", "lines": ["(the bridge)"]}],
                              "arrangements": [{"id": "main", "name": "Main", "order": ["v1", "c"]},
                                               {"id": "sunday", "name": "Sunday", "order": ["v1", "c", "b", "b", "c"]}]}]
    sundays(as_, 2)
    make_team(as_)
    make_team(as_, gid=WELCOME, places=("Doors",))
    svc = services(db)[0]
    svc["items"] = [
        {"id": "s-before", "kind": "section", "title": "Before"},
        {"id": "loop", "kind": "loop", "title": "Welcome loop", "minutes": 15, "who": "Dana"},
        {"id": "s-main", "kind": "section", "title": "The service"},
        {"id": "ff", "kind": "song", "song_id": SONG, "arrangement_id": "sunday", "minutes": 6, "who": "Keisha leads"},
        {"id": "ps", "kind": "scripture", "ref": "Joshua 4:1-9", "translation": "KJV", "minutes": 3},
        {"id": "sm", "kind": "text", "title": "What Mean These Stones?", "minutes": 40, "who": "Pastor James"},
        {"id": "s-after", "kind": "section", "title": "After"},
        {"id": "bye", "kind": "loop", "title": "Goodbye loop", "minutes": 20},
    ]
    app = FastAPI()
    app.include_router(so.router)
    app.include_router(sp.router)
    who = {"user": PEOPLE["owner"]}
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as2(name):
        who["user"] = PEOPLE[name]
        return client
    return db, as2, svc


def get(as_, who="owner", **q):
    return as_(who).get("/planning/order", params={"business_id": BIZ, **q})


def note(as_, svc, item, team, text, who="owner"):
    return as_(who).put("/planning/order/notes", json={"business_id": BIZ, "service_id": svc["id"], "item_id": item,
                                                         "team": team, "note": text})


def test_the_order_is_the_plan_with_times(order):
    db, as_, svc = order
    r = get(as_)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["service"]["id"] == svc["id"] and (o["starts"], o["ends"]) == ("10:30", "11:19")
    rows = {i["id"]: i for i in o["items"]}
    assert [i["id"] for i in o["items"]] == ["s-before", "loop", "s-main", "ff", "ps", "sm", "s-after", "bye"]
    # After follows the end without moving it.
    assert (rows["s-after"]["time"], rows["bye"]["time"]) == ("11:19", "11:19")
    # Before counts back: the loop's 15 minutes end as the service starts.
    assert (rows["s-before"]["time"], rows["loop"]["time"]) == ("10:15", "10:15")
    assert [rows[k]["time"] for k in ("s-main", "ff", "ps", "sm")] == ["10:30", "10:30", "10:36", "10:39"]
    assert (rows["ff"]["title"], rows["ff"]["sub"], rows["ff"]["who"]) == ("Firm Foundation", "Song · key of B", "Keisha leads")
    assert rows["ps"]["title"] == "Joshua 4:1-9" and rows["sm"]["title"] == "What Mean These Stones?"
    # The band's order from the arrangement the plan picked; never a song's words.
    assert (rows["ff"]["key"], rows["ff"]["parts"]) == ("B", ["V1", "C", "B", "B", "C"])
    assert "own words" not in json.dumps(o) and "more of its words" not in json.dumps(o) and "lines" not in json.dumps(o)
    assert [t["name"] for t in o["teams"]] == ["Production", "Welcome"]
    assert len(o["upcoming"]) == 2
    # Another Sunday by its id; one that isn't this church's is not found.
    other = services(db)[1]
    assert get(as_, service_id=other["id"]).json()["items"] == []
    assert get(as_, service_id=str(uuidlib.uuid4())).status_code == 404


def test_a_note_for_a_team_and_for_everyone(order):
    db, as_, svc = order
    assert note(as_, svc, "ff", PRODUCTION, "  New slides   are in ChurchSavvy ").status_code == 200
    assert note(as_, svc, "ff", "all", "Bridge twice, then a soft chorus").status_code == 200
    assert note(as_, svc, "loop", WELCOME, "Doors open 10:45").status_code == 200
    rows = {i["id"]: i for i in get(as_).json()["items"]}
    assert rows["ff"]["notes"] == {PRODUCTION: "New slides are in ChurchSavvy", "all": "Bridge twice, then a soft chorus"}
    assert rows["loop"]["notes"] == {WELCOME: "Doors open 10:45"}
    assert db.t["serve_notes"][0]["updated_by"] == "Pastor Kevin"
    # Changed in place, then taken off with an empty note.
    note(as_, svc, "ff", PRODUCTION, "Words from verse 1")
    assert {i["id"]: i for i in get(as_).json()["items"]}["ff"]["notes"][PRODUCTION] == "Words from verse 1"
    assert note(as_, svc, "ff", PRODUCTION, "").json() == {"ok": True, "note": None}
    assert PRODUCTION not in {i["id"]: i for i in get(as_).json()["items"]}["ff"]["notes"]
    assert len(db.t["serve_notes"]) == 2


def test_notes_are_checked(order):
    db, as_, svc = order
    assert note(as_, svc, "s-main", "all", "x").status_code == 404, "a section isn't an item"
    assert note(as_, svc, "gone", "all", "x").status_code == 404
    assert note(as_, svc, "ff", str(uuidlib.uuid4()), "x").status_code == 404, "not one of the church's Sunday teams"
    assert note(as_, svc, "ff", "everyone", "x").status_code == 400
    assert note(as_, svc, "ff", "all", "x" * 301).status_code == 400
    assert note(as_, svc, "FF!", "all", "x").status_code == 400
    assert as_("owner").put("/planning/order/notes", json={"business_id": BIZ, "service_id": svc["id"], "item_id": "ff",
                                                            "team": "all", "note": 7}).status_code == 400
    assert db.t["serve_notes"] == []


def test_who_reads_and_who_writes(order, monkeypatch):
    db, as_, svc = order
    assert get(as_, who="viewer").status_code == 200 and get(as_, who="viewer").json()["can_write"] is False
    assert get(as_, who="planner").json()["can_write"] is True
    assert note(as_, svc, "ff", "all", "x", who="viewer").status_code == 403
    assert note(as_, svc, "ff", "all", "x", who="booth").status_code == 403
    assert note(as_, svc, "ff", "all", "Planner's note", who="planner").status_code == 200
    assert get(as_, who="stranger").status_code in (403, 404)
    monkeypatch.setenv("SUNDAY_PLANNING", "off")
    assert get(as_).status_code == 404
    assert note(as_, svc, "ff", "all", "x").status_code == 404


def test_a_churchsavvy_save_never_touches_a_note(order, monkeypatch):
    db, as_, svc = order
    note(as_, svc, "ff", PRODUCTION, "New slides are in ChurchSavvy")
    note(as_, svc, "sm", "all", "Altar team stand by at 12:15")
    # ChurchSavvy saves the plan again: the song moves, the sermon comes out.
    svc["items"] = [i for i in svc["items"] if i["id"] != "sm"]
    svc["items"].insert(1, svc["items"].pop(3))
    rows = {i["id"]: i for i in get(as_).json()["items"]}
    assert rows["ff"]["notes"] == {PRODUCTION: "New slides are in ChurchSavvy"}
    assert "sm" not in rows
    # A team that stops being a Sunday team: its notes aren't shown.
    db.t["serve_teams"] = [t for t in db.t["serve_teams"] if t["group_id"] != PRODUCTION]
    rows = {i["id"]: i for i in get(as_).json()["items"]}
    assert rows["ff"]["notes"] == {}


def test_the_booths_today(order):
    """Board 11: who's on, place by place (here and when, not here yet,
    waiting, open), and the plan's clock."""
    from test_sunday_planning import ANA, KENDRA, ask, place, train
    db, as_, svc = order
    team = next(t for t in as_("owner").get("/planning/teams", params={"business_id": BIZ}).json()["teams"]
                if t["group_id"] == PRODUCTION)
    sound, slides = place(team, "Sound"), place(team, "Slides")
    train(as_, sound, [(KENDRA, "trained")])
    train(as_, slides, [(ANA, "trained")])
    a = ask(as_, svc["id"], sound, KENDRA).json()["assignment"]["id"]
    as_("owner").post(f"/planning/assignments/{a}/answer", json={"business_id": BIZ, "status": "yes"})
    ask(as_, svc["id"], slides, ANA)
    r = as_("viewer").get("/planning/today", params={"business_id": BIZ})
    assert r.status_code == 200, r.text
    t = r.json()
    prod = next(x for x in t["teams"] if x["name"] == "Production")
    assert [(s["place"], s["state"], s["name"]) for s in prod["spots"]] == [
        ("Sound", "yes", "Kendra Lane"), ("Slides", "asked", "Ana Cruz")]
    welcome = next(x for x in t["teams"] if x["name"] == "Welcome")
    assert welcome["spots"] == [{"place": "Doors", "slot": 1, "state": "open", "name": None, "here": None}]
    assert t["clock"] == {"starts": "10:30", "ends": "11:19",
                          "longest": {"title": "What Mean These Stones?", "time": "10:39", "minutes": 40}}
    # Kendra tapped I'm here at 8:50 on the day.
    next(x for x in db.t["serve_assignments"] if x["id"] == a)["here_at"] = "2026-10-25T13:50:00+00:00"
    prod = next(x for x in get_today(as_)["teams"] if x["name"] == "Production")
    assert (prod["spots"][0]["state"], prod["spots"][0]["here"]) == ("here", "08:50")
    # A long rehearsal before the service isn't the sermon.
    next(i for i in svc["items"] if i["id"] == "loop")["minutes"] = 50
    assert get_today(as_)["clock"]["longest"]["title"] == "What Mean These Stones?"
    # Someone who isn't on the team doesn't read it.
    assert as_("stranger").get("/planning/today", params={"business_id": BIZ}).status_code in (403, 404)


def get_today(as_):
    return as_("owner").get("/planning/today", params={"business_id": BIZ}).json()
