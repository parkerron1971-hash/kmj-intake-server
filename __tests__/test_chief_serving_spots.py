# __tests__/test_chief_serving_spots.py
#
# Chief fills an open serving spot through the serving page's own routes (chief_serving_spots.py).
# Pins:
#   * the read shows who holds each spot and who on the team could take it, best first, and who can't and why
#   * an ask, an offer, a take-back and a fill are the page's own writes, as the signed-in login: the page's
#     checks refuse (away, on another spot then, not on the team, every spot taken) and nothing is written
#   * every receipt says asked and waiting, never filled; a yes is never taken back
#   * who may schedule which team is the page's (the owner every team; a Manager by the duty that schedules
#     a team's door), never Chief's
#   * nobody signed in, an unattended run, the switch off, Love City-only owner mode at another church, and a
#     church that isn't one are all refused before any read of the schedule; a tainted turn's write is held
#   * the registry keeps every verb Chief's alone and class C; plans never carry them

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_sunday_planning import (ANA, BIZ, JO, KENDRA, LEE, MARCUS, PRODUCTION, WELCOME, api, make_team, place,  # noqa: F401
                                  services, sundays, train, away)

import action_registry
import chief_church_assignments as cca
import chief_missions
import chief_serving_spots as css
import church_duties
import sunday_planning as sp
import worship_team as wt

SUN = "2026-10-25"


@pytest.fixture
def church(api, monkeypatch):
    """Love City as a church with owners on its teams: Production (Sound: Kendra, Jo; Slides: Marcus, Ana) is
    ChurchSavvy's by its name, Welcome (Doors: Ana, Lee) the Volunteers'. Three Sundays at 10:30."""
    db, as_ = api
    db.t["businesses"][0]["type"] = "church"
    sundays(as_, 3)
    prod = make_team(as_)
    sound, slides = place(prod, "Sound"), place(prod, "Slides")
    doors = place(make_team(as_, gid=WELCOME, places=("Doors",)), "Doors")
    train(as_, sound, [(KENDRA, "trained"), (JO, "trained")])
    train(as_, slides, [(MARCUS, "trained"), (ANA, "trained")])
    train(as_, doors, [(ANA, "trained"), (LEE, "trained")])
    standing = {"u-owner": {"role": "owner", "duties": frozenset()},
                "u-mgr": {"role": "manager", "duties": frozenset({"serve_schedule"})},
                "u-care": {"role": "manager", "duties": frozenset()}}
    monkeypatch.setattr(church_duties, "standing", lambda biz, uid: standing.get(uid, {"role": None}))
    seats = {("u-owner", BIZ): "owner", ("u-mgr", BIZ): "manager", ("u-care", BIZ): "manager"}
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: seats.get((uid, biz)))
    monkeypatch.setattr(wt, "_manager_parts", lambda biz, user: set())
    monkeypatch.setenv("CHIEF_SERVING_SPOTS", "on")
    who = {"uid": "u-owner"}
    monkeypatch.setattr(cca, "_turn_user", lambda: who["uid"])
    import chief_of_staff
    taint = {"n": 0}
    monkeypatch.setattr(chief_of_staff, "untrusted_taint", lambda: taint["n"])
    return {"db": db, "who": who, "taint": taint, "sound": sound, "slides": slides, "doors": doors,
            "svc": [s["id"] for s in services(db)]}


def run(verb, **action):
    return asyncio.run(css.HANDLERS[verb](None, {"id": BIZ}, action))


def rows(c):
    return c["db"].t["serve_assignments"]


# ─── The read ─────────────────────────────────────────────────────────

def test_the_read_shows_the_spot_and_who_could_take_it(church):
    away(church["db"], JO, SUN, SUN)
    out = run("serving_spot", day=SUN, place="sound")
    assert not out.get("failed"), out
    text = out["result"]
    assert text.startswith("Sound (Production), Sunday, Oct 25 at 10:30am") and "spot 1: open" in text
    assert "Could take it, best first: Kendra Lane (trained, 0 Sundays this month)" in text
    assert "Can't: Jo Park (away that day)" in text
    assert rows(church) == [], "a read writes nothing"


def test_the_read_with_no_place_is_the_days_open_spots(church):
    run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    text = run("serving_spot", day=SUN)["result"]
    assert text.startswith("Open serving spots, Sunday, Oct 25 at 10:30am (Sunday service): 2.")
    assert "Slides (Production): 1 of 1 open" in text and "Doors (Welcome): 1 of 1 open" in text
    assert "Sound" not in text, "an asked spot isn't open"


def test_the_coming_sunday_when_no_day_is_said(church):
    assert "Sunday, Oct 25" in run("serving_spot", place="Doors")["result"]


def test_a_day_with_nothing_on_says_what_is_next(church):
    out = run("serving_spot", day="2026-10-27", place="Sound")
    assert out["failed"] and "Nothing is on Who serves when on 2026-10-27" in out["result"]
    assert "Sunday, Nov 1" in out["result"]


def test_a_day_with_two_services_needs_the_time(church):
    db = church["db"]
    first = next(s for s in db.t["worship_services"] if s["starts_at"].startswith(SUN))
    db.t["worship_services"].append({**first, "id": "55555555-5555-4555-8555-555555555555",
                                     "starts_at": first["starts_at"].replace("15:30", "17:00"), "title": "Second"})
    out = run("serving_spot", day=SUN, place="Sound")
    assert out["failed"] and "say which time" in out["result"]
    assert "Sunday, Oct 25 at 12:00pm" in run("serving_spot", day=SUN, time="12pm", place="Sound")["result"]


def test_an_unknown_place_names_the_real_ones(church):
    out = run("serving_spot", day=SUN, place="parking")
    assert out["failed"] and "Sound (Production)" in out["result"] and "Doors (Welcome)" in out["result"]


# ─── The writes ───────────────────────────────────────────────────────

def test_an_ask_is_the_pages_ask_and_says_asked_not_filled(church):
    out = run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    assert not out.get("failed"), out
    [r] = rows(church)
    assert (r["contact_id"], r["status"], r["position_id"], r["service_id"]) == (KENDRA, "asked", church["sound"],
                                                                               church["svc"][0])
    assert r["asked_by"] == "Pastor Kevin" and r["notified_at"] is None, "the page's asker; the sweep sends it"
    assert "Asked Kendra Lane to serve Sound (Production), Sunday, Oct 25" in out["result"]
    assert "asked, not filled" in out["result"] and "haven't said yes" in out["result"]
    assert "filled" not in out["label"].lower()


@pytest.mark.parametrize("person,why", [
    ("Jo", "away that Sunday"),
    ("Lee", "isn't on Production"),
])
def test_the_pages_checks_refuse_and_nothing_is_written(church, person, why):
    away(church["db"], JO, SUN, SUN)
    out = run("ask_to_serve", day=SUN, place="Sound", person=person)
    assert out["failed"] and why in out["result"], out
    assert out["result"].endswith("Nothing changed."), out
    assert rows(church) == []


def test_someone_already_on_another_spot_then_is_refused(church):
    run("ask_to_serve", day=SUN, place="Slides", person="Ana")
    out = run("ask_to_serve", day=SUN, place="Doors", person="Ana")
    assert out["failed"] and "already on Slides" in out["result"]
    assert len(rows(church)) == 1


def test_every_spot_taken_says_who_holds_it(church):
    run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    out = run("ask_to_serve", day=SUN, place="Sound", person="Jo")
    assert out["failed"] and "Every Sound spot then is taken (spot 1: Kendra Lane, asked, not sent yet)" in out["result"]
    assert [r["contact_id"] for r in rows(church)] == [KENDRA]
    again = run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    assert again["failed"] and "already on Sound" in again["result"]


def test_an_offer_goes_to_the_whole_team(church):
    out = run("offer_serving_spot", day=SUN, place="Doors")
    [r] = rows(church)
    assert r["status"] == "offered" and r["contact_id"] is None
    assert "first yes takes it" in out["result"] and "still open" in out["result"]


def test_take_back_an_ask_never_a_yes(church):
    run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    out = run("take_back_serving_ask", day=SUN, place="Sound", person="Kendra")
    assert not out.get("failed") and "Took back the ask to Kendra Lane" in out["result"]
    assert rows(church) == []
    run("ask_to_serve", day=SUN, place="Sound", person="Jo")
    rows(church)[0]["status"] = "yes"
    out = run("take_back_serving_ask", day=SUN, place="Sound", person="Jo")
    assert out["failed"] and "already said yes" in out["result"] and "Nothing changed." in out["result"]
    assert len(rows(church)) == 1


def test_a_sent_ask_taken_back_says_they_may_have_seen_it(church):
    run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    rows(church)[0]["notified_at"] = "2026-10-21T15:15:00+00:00"
    assert "may have seen it" in run("take_back_serving_ask", day=SUN, place="Sound")["result"]


def test_fill_and_take_the_fill_back(church):
    out = run("fill_serving_spots", weeks=3)
    assert not out.get("failed"), out
    n = len(rows(church))
    assert n > 0 and f"Asked people for {n} open spot" in out["result"] and "can still be taken back" in out["result"]
    assert all(r["asked_by"] == sp.FILLED_BY for r in rows(church))
    rows(church)[0]["notified_at"] = "2026-10-21T15:15:00+00:00"       # one went out already: it stays
    back = run("take_back_serving_ask", fill=True)
    assert f"Took back {n - 1} asks" in back["result"]
    assert len(rows(church)) == 1


def test_fill_one_team_by_name(church):
    run("fill_serving_spots", weeks=2, team="welcome")
    assert {r["position_id"] for r in rows(church)} == {church["doors"]}
    out = run("fill_serving_spots", team="choir")
    assert out["failed"] and "isn't one of the Sunday teams" in out["result"]


# ─── Who may schedule: the page's, never Chief's ──────────────────────

def test_a_manager_schedules_only_the_teams_their_duty_opens(church):
    church["who"]["uid"] = "u-mgr"          # serve_schedule: the Volunteers' teams
    assert not run("ask_to_serve", day=SUN, place="Doors", person="Lee").get("failed")
    out = run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    assert out["failed"] and "Nothing changed." in out["result"]
    assert [r["position_id"] for r in rows(church)] == [church["doors"]]
    assert run("serving_spot", day=SUN, place="Sound")["failed"], "no suggestion where it couldn't ask"
    text = run("serving_spot", day=SUN)["result"]
    assert "Doors" not in text and "Sound" not in text, "only the teams this login schedules (Doors is asked)"


def test_a_login_that_schedules_nothing_hears_the_pages_refusal(church):
    church["who"]["uid"] = "u-care"
    for verb, action in (("serving_spot", {"place": "Doors"}), ("ask_to_serve", {"place": "Doors", "person": "Lee"}),
                         ("fill_serving_spots", {})):
        out = run(verb, day=SUN, **action) if verb != "fill_serving_spots" else run(verb)
        assert out["failed"], (verb, out)
        assert "Lee" not in out["result"] and "Doors (Welcome)" not in out["result"], "nothing about the team said"
    assert rows(church) == []


# ─── The gates before any read ────────────────────────────────────────

def test_nobody_signed_in_or_unattended_is_refused(church):
    church["who"]["uid"] = ""
    assert "signed in" in run("ask_to_serve", day=SUN, place="Sound", person="Kendra")["result"]
    church["who"]["uid"] = "u-owner"
    out = run("ask_to_serve", day=SUN, place="Sound", person="Kendra", _unattended=True)
    assert out["failed"] and "only when someone at the church asks" in out["result"]
    assert rows(church) == []


def test_the_switch_and_love_city_first(church, monkeypatch):
    monkeypatch.setenv("CHIEF_SERVING_SPOTS", "off")
    assert run("serving_spot", day=SUN, place="Sound")["result"] == f"Failed: {css.NOT_ON}"
    monkeypatch.setenv("CHIEF_SERVING_SPOTS", "owner")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: False)
    assert run("ask_to_serve", day=SUN, place="Sound", person="Kendra")["result"] == f"Failed: {css.NOT_ON}"
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: True)
    assert not run("ask_to_serve", day=SUN, place="Sound", person="Kendra").get("failed")
    monkeypatch.delenv("CHIEF_SERVING_SPOTS")
    assert css.mode() == "owner", "Love City first by default"


def test_the_pages_own_switch(church, monkeypatch):
    monkeypatch.setenv("SUNDAY_PLANNING", "off")
    assert run("serving_spot", day=SUN, place="Sound")["result"] == f"Failed: {css.PAGE_OFF}"


def test_only_churches(church):
    church["db"].t["businesses"][0]["type"] = "coaching"
    assert "for churches" in run("serving_spot", day=SUN, place="Sound")["result"]


def test_a_tainted_turn_holds_the_write_but_not_the_read(church):
    church["taint"]["n"] = 1
    out = run("ask_to_serve", day=SUN, place="Sound", person="Kendra")
    assert out["failed"] and out["needs_confirmation"] and "HELD" in out["result"]
    assert rows(church) == []
    assert not run("serving_spot", day=SUN, place="Sound").get("failed")


# ─── The turn's block ─────────────────────────────────────────────────

def test_the_block_shows_only_where_it_is_open(church, monkeypatch):
    import church_over as co
    monkeypatch.setattr(co.Church, "role", lambda self, uid: {"u-owner": "owner", "u-vol": None}.get(uid))
    biz = {"id": BIZ, "type": "church", "settings": {}}
    assert css.turn_line(biz, "u-owner") == css.BLOCK
    assert "never that the spot is filled" in css.BLOCK
    assert css.turn_line(biz, "u-vol") == "", "no office seat"
    assert css.turn_line({**biz, "type": "coaching"}, "u-owner") == ""
    monkeypatch.setenv("CHIEF_SERVING_SPOTS", "off")
    assert css.turn_line(biz, "u-owner") == ""


# ─── The registry, plans and the toolbox ──────────────────────────────

def test_every_verb_is_chiefs_alone_and_asking_is_class_c():
    for v in css.VERBS:
        entry = action_registry.classification(v)
        assert entry and entry.get("chief_only") is True, v
        assert not action_registry.may_expose_to_agent(v), v
    assert action_registry.classification("serving_spot")["effect"] == "read"
    for v in css.WRITES:
        assert action_registry.classification(v)["reversibility"] == "C", v
    assert action_registry.classification("fill_serving_spots").get("bulk") is True


def test_plans_never_ask_people_to_serve():
    assert css.WRITES <= chief_missions._FORBIDDEN_VERBS


def test_the_read_is_a_mid_turn_lookup_and_the_writes_are_tags():
    import chief_of_staff
    import chief_tool_loop
    assert set(css.VERBS) <= set(chief_of_staff.ACTION_HANDLERS)
    reads = {t["name"] for t in chief_tool_loop.read_tool_definitions()}
    writes = {t["name"] for t in chief_tool_loop.write_tool_definitions()}
    assert "serving_spot" in reads and not (css.WRITES & (reads | writes))
