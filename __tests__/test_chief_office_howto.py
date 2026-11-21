"""Chief knows how each office person does each thing, and says it once
(chief_office.place, church_findway, the module line, the prompt rule).

Kevin, 2026-11-18: "make sure that chief is aware of how to do each thing
with each person and help them per the list you gave about what chief can do
now. I just asked and chief said yes but then said no to certain parts so
check that to make sure." Asked to share with Laquesha how to get to an
event's volunteer list and put its volunteer spots in Services & Events,
Chief said "yes to both", then "no to the first", said it had no confirmed
path, and that the roles might go in the notes.

Pins:
  * every office duty has a place on the church's menu, read from My week's
    door and the map the frontend exports (or is done through Chief only);
    each button named beside a place is one a Help Center answer on that page
    names; the events duty's door is Services & Events, not the events page
  * THE OFFICE says each person's places: Laquesha's volunteer list and room
    request, Naiya's text alert and leaders note, Tiara's New here, Shapretta's
    waiting slide, Jessica's one-on-one and monthly report; past the cap the
    places go before the labels shorten; list_duties says them too
  * My week opens the events duty in the church's own events room
  * the map: pages a duty opens are a duty holder's (the menu's tag, the
    turn's answers); a named page brings its own answers, so Kevin's long
    question gets the volunteer-list steps
  * an events room's line says its entries hold roles and volunteers
  * one answer per part, and a known place is given: in the universal manual
    (kept by the short brief) and the church's menu
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_office as co_  # noqa: E402
import church_duties as cd  # noqa: E402
import church_findway as way  # noqa: E402
import church_my_week as mw  # noqa: E402
from test_chief_office import LOVE_CITY, NAIYA_JOB, db, line_of, ok, roster, run  # noqa: E402,F401

CHURCH = {"id": "c1", "type": "church", "name": "Love City Church"}
LAQUESHA = {"areas": ["worship_media"], "role": "manager", "lane": "sunday_serving"}
KEVINS_QUESTION = ("Could you share with Laquesha exactly how to get to the event volunteer list, and add it to "
                   "Services & Events with volunteer spots, giving her the ability to get in there?")


# ─── Every duty's place ───────────────────────────────────────────────

@pytest.mark.parametrize("duty", list(cd.CATALOG))
def test_every_duty_has_a_place_on_the_menu_or_is_done_through_chief(duty):
    door = mw.DOOR[duty]
    where = co_.place(duty)
    if where is None:
        assert duty in co_.THROUGH_CHIEF, f"{duty}: its page {door['area']}:{door['id']} isn't on the church's map"
        return
    page = way.page(door["area"], door["id"])
    assert page, f"{duty}: My week opens {door['area']}:{door['id']}, which the map doesn't have"
    assert where.startswith(page["where"]) and where.split(" › ")[0] in {d["label"] for d in way._map()["doors"]}


def test_each_button_beside_a_place_is_named_by_a_help_center_answer_on_that_page():
    pairs = [(f"{mw.DOOR[k]['area']}:{mw.DOOR[k]['id']}", b) for k, b in co_.INSIDE.items()]
    pairs += [pair for rows in co_.ALSO.values() for pair in rows]
    for key, button in pairs:
        page = way.page(key)
        assert page, key
        if button:
            assert any(button in a["a"] for a in page["answers"]), f"no Help Center answer on {key} names {button!r}"
    assert set(co_.INSIDE) <= set(cd.CATALOG) and set(co_.ALSO) <= set(cd.CATALOG)
    assert set(co_.THROUGH_CHIEF) <= set(cd.CATALOG)


def test_the_events_duty_is_done_in_services_and_events_not_on_the_events_page():
    assert mw.DOOR["events"]["id"] == mw.ROSTER and mw.DOOR["website"]["id"] == "my-site"
    assert co_.place("events") == ("Sunday › Plan and look back › Services & Events → Roles; "
                                   "also Office › Building › Rooms & spaces → Ask for a room")
    assert co_.place("clips") == "Reach › Create", "Video Clips are a tab of Create now"
    assert co_.place("weekly_text") == "Messages › Texts → Announcement"
    assert co_.place("church_email") == ("Messages › Templates and setup › Email setup; "
                                         "addresses are given out through Chief")


# ─── THE OFFICE says each person's places ─────────────────────────────

def test_the_office_says_where_each_person_does_each_thing(db, monkeypatch):
    import guest_path
    monkeypatch.setattr(guest_path, "switched_on", lambda b: False)      # the Welcome Path off: the board
    ok(run(db, LOVE_CITY, "owner", "set_job_description", who="Naiya Clark", title="Church Administrator",
           description=NAIYA_JOB, source="drafted"))
    text = roster(db)
    laq = line_of(text, "Laquesha Bailey-Smith")
    assert ("Events and sign-ups (Sunday › Plan and look back › Services & Events → Roles; also Office › "
            "Building › Rooms & spaces → Ask for a room)") in laq
    assert "Who serves when (Sunday › This week › Who serves when → Ask)" in laq
    naiya = line_of(text, "Naiya Clark")
    for said in ("The weekly text and email (Messages › Texts → Announcement)",
                 "The Monday leaders note (Office › Leaders › Leaders note → Text it too)",
                 "Rooms (Office › Building › Rooms & spaces → Waiting for a yes)"):
        assert said in naiya, said
    assert ("First-time guests and welcome calls (People › New and in need › Follow-up board → Hand to; "
            "also Messages › Texts → New here)") in line_of(text, "Tiara Adams")
    assert "Sunday announcements (Sunday › This week › Announcements → Waiting for you)" in line_of(
        text, "Shapretta McClain")
    jess = line_of(text, "Jessica McCloud")
    assert "The monthly report (Office › Leaders › Monthly report → Send to the pastor)" in jess
    assert "Over the lanes (Home › Office team → One-on-one)" in jess
    assert "Bills and pay-backs (Office › Money out › Check requests)" in line_of(text, "Minnie Tatum")
    rule = text.strip().split("\n")[-1]
    assert rule.startswith("Beside each duty is where it is done") and "confirmed" in rule
    assert len(text) <= co_.ROSTER_MAX_CHARS


def test_past_the_cap_the_places_go_before_the_labels_shorten(db, monkeypatch):
    full = roster(db)
    monkeypatch.setattr(co_, "ROSTER_MAX_CHARS", len(full) - 2)         # its text, less the newline, less one
    capped = roster(db)
    assert "→" not in "\n".join(ln for ln in capped.split("\n") if ln.startswith("- "))
    assert "The front desk; The Monday leaders note;" in capped, "every label, without its place"
    assert "Where a duty is done: job_of says it beside each of a person's duties" in capped
    assert len(capped) < len(full)


def test_list_duties_says_where_each_duty_is_done_and_fits_its_read(db):
    out = ok(run(db, LOVE_CITY, "owner", "list_duties"))
    assert "\"Done in:\" is where on the church's menu" in out["result"]
    line = next(ln for ln in out["result"].splitlines() if ln.startswith("- Events and sign-ups (events; Thu)"))
    assert line.endswith(". Done in: Sunday › Plan and look back › Services & Events → Roles; also Office › "
                         "Building › Rooms & spaces → Ask for a room.")
    assert len(json.dumps(out, default=str)) < 12000, "the tool loop's cap for list_duties"


# ─── My week opens the events room ────────────────────────────────────

def test_my_week_opens_the_events_duty_in_the_churchs_events_room(monkeypatch):
    import events_rsvp_router
    rooms = [{"id": "aaaaaaaa-0000-4000-8000-000000000001", "name": "Services &  Events"}]
    calls = []
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda b: calls.append(b) or rooms)
    memo = {}
    door = mw.room_door(CHURCH, mw.DOOR["events"], memo)
    assert door == {"area": "operate", "id": "module:aaaaaaaa-0000-4000-8000-000000000001",
                    "label": "Open Services & Events"}
    assert mw.room_door(CHURCH, mw.DOOR["events"], memo) == door and calls == ["c1"], "read once a week's build"
    assert mw.room_door(CHURCH, mw.DOOR["rooms"], {}) is mw.DOOR["rooms"], "any other door as it is"
    rooms.clear()
    assert mw.room_door(CHURCH, mw.DOOR["events"], {}) == mw.NO_ROSTER, "no events room: the calendar"
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda b: 1 / 0)
    assert mw.room_door(CHURCH, mw.DOOR["events"], {}) == mw.NO_ROSTER, "a read that fails: the calendar"


# ─── The map: a duty's pages, a named page's answers ──────────────────

def test_a_page_a_duty_opens_is_the_duty_holders():
    spaces = way.page("operate:spaces")
    assert spaces["duties"] == ["rooms", "events", "outreach_nights"]
    assert way.page("operate", "@roster")["duties"] == ["events"]
    assert not way.shown_to(spaces, LAQUESHA), "her areas alone don't have it"
    assert way.shown_to(spaces, LAQUESHA, {"events"}), "her events duty does"
    assert not way.shown_to(way.page("operate:checks"), LAQUESHA, set(cd.ALL)), "money is never a lane's"
    menu = way.menu_block(CHURCH)
    assert "Rooms & spaces (operate/spaces) [office; +Rooms / Events and sign-ups / Outreach nights]" in menu
    assert "Monthly report (operate/monthly-report) [owner; +The monthly report]" in menu
    assert "never say you have no confirmed path" in menu


def test_her_room_request_answer_reaches_her_turn_by_her_duty():
    asked = "how do I ask for a room for the fall fest"
    assert "Ask for a room for an event" not in way.turn_block(CHURCH, asked, LAQUESHA, frozenset())
    block = way.turn_block(CHURCH, asked, LAQUESHA, frozenset({"events"}))
    assert "Ask for a room for an event — Office › Building › Rooms & spaces (open with navigate operate/spaces)" in block
    assert "Your asks" in block


def test_kevins_question_gets_the_volunteer_list_steps():
    block = way.turn_block(CHURCH, KEVINS_QUESTION, LAQUESHA, frozenset({"events"}))
    assert "Make an event’s volunteer list — Sunday › Plan and look back › Services & Events" in block
    assert "Set up serving, or Roles" in block and "Save roles" in block


ASKED = [
    ("how do I make a volunteer list for an event", "make-an-events-volunteer-list"),
    ("how does Laquesha make the event volunteer list", "make-an-events-volunteer-list"),
    ("ask for a room for an event", "ask-for-a-room-for-an-event"),
    ("send a text alert", "send-a-text-alert-to-one-group"),
    ("text the leaders note", "text-the-monday-leaders-note-too"),
    ("set up new here", "set-up-new-here-for-first-time-guests"),
    ("print the seat cards", "print-the-new-here-seat-cards"),
    ("put the new here slide on the screen", "put-the-new-here-slide-on-sundays-screen"),
    ("approve a guest slide", "approve-a-guest-slide-that-is-waiting"),
    ("get ready for a one-on-one", "get-ready-for-a-one-on-one"),
    ("how many people get our texts", "see-how-many-people-get-our-texts"),
]


@pytest.mark.parametrize("question,answer", ASKED)
def test_each_persons_how_to_has_its_help_center_answer(question, answer):
    """The same questions as the app's tests/church-map-check.ts (the first two
    are on Services & Events, which the app's check leaves out of its pool)."""
    found = way.match_answers(question, None, 1)
    assert found and found[0][0]["id"] == answer


def test_the_turn_reads_the_logins_duties_only_for_a_where_or_a_how(monkeypatch):
    calls = []
    monkeypatch.setattr(cd, "standing", lambda b, u: calls.append((b, u)) or {"duties": frozenset({"events"})})
    assert way.duties_of(CHURCH, "u1") == frozenset({"events"}) and calls == [("c1", "u1")]
    assert way.duties_of({"id": "b", "type": "coach"}, "u1") is None
    monkeypatch.setattr(cd, "standing", lambda b, u: 1 / 0)
    assert way.duties_of(CHURCH, "u1") is None, "unread duties add no page"
    assert way.asks("how do I ask for a room") and not way.asks("thanks!") and not way.asks("")


# ─── The events room's line ───────────────────────────────────────────

def _ctx(modules):
    ctx = {"business": {"id": "b1", "name": "Love City Church", "type": "church",
                        "settings": {"practitioner_name": "Kevin"}, "voice_profile": {}},
           "modules": modules, "module_counts": {m["id"]: 7 for m in modules}}
    return collections.defaultdict(lambda: [], ctx)


def test_an_events_rooms_line_says_its_entries_hold_roles_and_volunteers():
    import chief_of_staff as cos
    room = {"id": "m1", "name": "Services & Events", "archetype": "event_roster",
            "schema": {"fields": [{"name": "title", "type": "text"}, {"name": "notes", "type": "textarea"}]}}
    other = {"id": "m2", "name": "Prayer list", "archetype": "list_tracker",
             "schema": {"fields": [{"name": "title", "type": "text"}]}}
    text = cos._format_context_for_prompt(_ctx([room, other]))
    line = next(ln for ln in text.split("\n") if "Services & Events (7 entries)" in ln)
    assert line.endswith("fields: title(text), notes(textarea)" + cos.ROSTER_ROLES_NOTE)
    assert '"roles" and "volunteers" on create_module_entry/update_module_entry, never in notes' in line
    assert cos.ROSTER_ROLES_NOTE not in next(ln for ln in text.split("\n") if "Prayer list (7 entries)" in ln)


# ─── One answer per part ──────────────────────────────────────────────

RULE = "ONE ANSWER PER PART"


def test_one_answer_per_part_is_in_the_universal_manual_and_the_short_brief_keeps_it(monkeypatch):
    import chief_lean_brief as lean
    import chief_of_staff as cos
    monkeypatch.delenv("CHIEF_BRIEF", raising=False)
    prompt = cos._build_system_prompt(_ctx([]), False)
    universal = lean.segments(prompt)["universal"]
    assert RULE in universal and prompt.index(RULE) < prompt.index("[[CHIEF_GLOBAL_SPLIT]]")
    line = next(ln for ln in universal.split("\n") if RULE in ln)
    assert 'never open with "yes to both" and then say no to one' in line
    assert "never \"I don't have a confirmed path\"" in line
    assert line in lean.lean_manual(universal), "the short brief keeps the line whole"
