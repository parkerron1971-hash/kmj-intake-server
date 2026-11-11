"""Chief reads a church's move and fills an item in (chief_move_in.py).
Kevin 2026-11-11: "you can allow chief to fill items as well".

Pins:
  * the verbs are wired, classified, placed with the Office and in the
    prompt; the read is a mid-turn lookup, the fills are tags and never
    native write tools
  * who: only someone signed in and let into the room; a closed switch, a
    stranger and another area's login get nothing; a Viewer reads and
    can't fill
  * the status names every item with its key, where it stands, what it
    holds, what it still needs, what's next and each item's lines
  * a fill saves a DRAFT through the room's own cleaning: a line given
    replaces that line, lines not given stay, an unknown line or a bad
    number changes nothing and says so
  * a fill never hands in; a fill of a handed-in item takes it back and
    says so; nothing is emailed
  * giving and file-only items can't be typed into
  * an unattended run fills nothing
  * the undo puts the item's lines back
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_move_in as cmi  # noqa: E402
import church_move_in as mi  # noqa: E402
from test_church_move_in import BIZ, CSV, ID, OTHER, db, hand_in, item, room, upload  # noqa: E402,F401


@pytest.fixture
def as_(monkeypatch):
    def become(name):
        monkeypatch.setattr(cmi, "_turn_user", lambda: ID[name] if name else "")
    become("owner")
    return become


def run(handler, action=None, biz=BIZ):
    return asyncio.run(handler(None, {"id": biz}, action or {}))


def status(biz=BIZ):
    return run(cmi.handle_move_in_status, biz=biz)


def fill(key, answers, **more):
    return run(cmi.handle_fill_move_in, {"item": key, "answers": answers, **more})


# ─── Wiring ───────────────────────────────────────────────────────────

def test_the_verbs_are_wired_classified_placed_and_in_the_prompt():
    import action_inverse as ai
    import action_registry as ar
    import chief_areas as ca
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    import mcp_server
    import system_destinations
    from __tests__._chief_source import chief_source
    verbs = ("move_in_status", "fill_move_in", "undo_move_in_fill")
    for verb in verbs:
        assert verb in cos.ACTION_HANDLERS, verb
        assert ar.classification(verb).get("chief_only"), verb
        assert not ar.may_expose_to_agent(verb, allow_writes=True), verb
        assert verb not in mcp_server.WRITE_TOOL_SCHEMAS and verb not in mcp_server.TOOL_SCHEMAS, verb
        assert ca.VERBS[verb] == ca.OFFICE, verb
    assert ar.effect("move_in_status") == "read"
    assert ar.reversibility("fill_move_in") == ar.reversibility("undo_move_in_fill") == "A"
    assert not ar.is_bulk("fill_move_in")
    assert "move_in_status" in {t["name"] for t in ctl.read_tool_definitions()}
    ctl.reset_turn(writes_allowed=True)
    assert not {"fill_move_in", "undo_move_in_fill"} & {t["name"] for t in ctl.write_tool_definitions()}
    ctl.reset_turn()
    src = chief_source()
    assert "move_in_status" in src and '"type":"fill_move_in"' in src and '"type":"undo_move_in_fill"' in src
    assert "press Hand in themselves" in src
    # Chief can open the page it talks about.
    assert system_destinations.destination("operate", "move-in")
    assert ai.build_inverse("fill_move_in", {}, {"changed": True, "item": "sunday", "before": {"x": 1}}) == {
        "type": "undo_move_in_fill", "item": "sunday", "answers": {"x": 1}}
    assert ai.build_inverse("fill_move_in", {}, {"changed": False, "item": "sunday"}) is None


def test_every_item_can_be_found_by_its_key_and_its_title():
    for it in mi.ITEMS:
        assert cmi.find_item(it["key"]) is it
        assert cmi.find_item(it["title"]) is it
    assert cmi.find_item("Sunday details")["key"] == "sunday"
    assert cmi.find_item("your look")["key"] == "look"
    assert cmi.find_item("the building fund") is None and cmi.find_item("") is None


# ─── Who ──────────────────────────────────────────────────────────────

def test_only_someone_signed_in_and_let_in(db, as_, monkeypatch):
    as_(None)
    assert status()["failed"] and "signed in" in status()["result"]
    as_("stranger")
    assert status()["result"] == f"Failed: {cmi.CLOSED}"
    as_("singer")
    assert status()["failed"] and "belongs to the office" in status()["result"]
    as_("other_owner")
    assert status()["result"] == f"Failed: {cmi.CLOSED}"          # another church's room
    as_("owner")
    monkeypatch.setenv("CHURCH_MOVE_IN", "off")
    assert status()["result"] == f"Failed: {cmi.CLOSED}"
    assert fill("owner", {"name": "Ada Hill"})["failed"]


def test_a_viewer_reads_and_cant_fill(db, as_):
    as_("viewer")
    assert not status().get("failed")
    got = fill("owner", {"name": "Ada Hill"})
    assert got["failed"] and "reads the move" in got["result"]
    assert db.t["church_move_items"] == []


def test_tables_not_there_yet_is_a_refusal_in_words(db, as_):
    db.missing = True
    assert status()["failed"] and "couldn't be read" in status()["result"]


# ─── The status ───────────────────────────────────────────────────────

def test_the_status_names_every_item_and_whats_next(db, as_):
    as_("office")
    fill("owner", {"name": "Ada Hill"})
    got = status()
    assert not got.get("failed") and got["label"] == "The move · 0 of 11 in"
    text = got["result"]
    assert text.startswith("Grace Hill Church's move: 0 of 11 are in")
    for n, it in enumerate(mi.ITEMS, start=1):
        assert f"{n}. {it['title']} ({it['key']}):" in text
    assert "(owner): Started. Has: Their name: Ada Hill." in text
    assert "Before it can be handed in: Fill in at least one line first." in text
    assert "services = list of {day, time, name}, 12 at most" in text
    assert "count (People who give monthly, a number)" in text
    assert "Stripe isn't started; only the account owner can set it up." in text
    assert text.rstrip().endswith("Next: Set up giving.")
    assert got["next"] == "giving" and got["nav"] == {"tab": "operate", "sub": "move-in"}
    assert "press Hand in themselves" in got["note_for_chief"]


def test_the_status_shows_a_change_we_asked_for_first(db, as_):
    fill("owner", {"name": "Ada Hill"})
    hand_in("owner", "owner")
    db.t["church_move_items"][0].update(state="needs", note="We need Ada's mobile number.")
    got = status()
    assert "Needs a change. We asked for a change: We need Ada's mobile number." in got["result"]
    assert got["next"] == "owner"


# ─── Filling ──────────────────────────────────────────────────────────

def test_a_fill_saves_a_draft_and_never_hands_in(db, as_):
    as_("office")
    got = fill("Sunday details", {"services": [{"day": "Sunday", "time": "9:00 AM", "name": "Early service"},
                                               {"day": "Sunday", "time": "11:00 AM"}],
                                  "kids_rooms": [{"room": "Nursery", "ages": "birth to two"}]})
    assert not got.get("failed"), got
    assert got["changed"] and got["item"] == "sunday" and got["before"] == {} and got["ready"] is True
    assert got["result"].startswith("Saved a draft of “Your Sunday details”. It now holds: Services: "
                                    "Sunday · 9:00 AM · Early service; Sunday · 11:00 AM. Kids rooms: Nursery · "
                                    "birth to two.")
    assert "It is not handed in." in got["result"] and "press Hand in" in got["result"]
    mine = item(room(), "sunday")
    assert mine["state"] == "started" and mine["handed_in_at"] is None
    assert db.mail == [] and db.t["support_tickets"] == []
    row, = db.t["church_move_items"]
    assert row["updated_by"] == ID["office"]


def test_a_line_given_replaces_that_line_and_the_rest_stay(db, as_):
    fill("owner", {"name": "Ada Hill", "mobile": "555-0100"})
    got = fill("owner", {"email": "ada@example.com"})
    assert got["before"] == {"name": "Ada Hill", "mobile": "555-0100"}
    assert item(room(), "owner")["answers"] == {"name": "Ada Hill", "mobile": "555-0100", "email": "ada@example.com"}
    fill("owner", {"mobile": ""})                                   # an empty line clears it
    assert item(room(), "owner")["answers"] == {"name": "Ada Hill", "email": "ada@example.com"}
    same = fill("owner", {"name": "Ada Hill"})
    assert same["changed"] is False and "Nothing changed" in same["result"]


def test_an_unknown_line_or_a_bad_number_changes_nothing_and_says_so(db, as_):
    got = fill("owner", {"name": "Ada Hill", "role": "pastor"})
    assert got["failed"] and "has no line called role. Nothing changed." in got["result"]
    assert "name (Their name)" in got["result"]
    assert db.t["church_move_items"] == []
    got = fill("monthly_givers", {"count": "about forty"})
    assert got["failed"] and "People who give monthly: type a number. Nothing changed." in got["result"]
    got = fill("safety", {"officers": [{"name": n} for n in ("A", "B", "C")]})
    assert got["failed"] and "2 at most" in got["result"]
    got = fill("owner", {})
    assert got["failed"] and "say what goes in" in got["result"]
    got = fill("owner", "Ada Hill")
    assert got["failed"]


def test_it_says_whats_still_needed(db, as_):
    got = fill("safety", {"officers": [{"name": "Dana Moore", "contact": "dana@example.com"}]})
    assert got["ready"] is False and "Before it can be handed in: Safety officers: add 2." in got["result"]


def test_giving_and_file_only_items_cant_be_typed_into(db, as_):
    assert "set up with Stripe by the account owner" in fill("giving", {"x": 1})["result"]
    assert "takes files" in fill("giving_history", {"x": 1})["result"]
    got = fill("the building fund", {"x": 1})
    assert got["failed"] and "no move-in item called “the building fund”" in got["result"]
    assert "Your Sunday details (sunday)" in got["result"] and "(giving_history)" not in got["result"]


def test_a_fill_of_a_handed_in_item_takes_it_back_and_says_so(db, as_):
    fill("owner", {"name": "Ada Hill"})
    hand_in("owner", "owner")
    assert len(db.mail) == 1
    got = fill("owner", {"mobile": "555-0100"})
    assert "It had been handed in, and this change took it back" in got["result"]
    assert item(room(), "owner")["state"] == "started"
    assert len(db.mail) == 1                                        # a fill emails nobody


def test_an_unattended_run_fills_nothing(db, as_):
    got = fill("owner", {"name": "Ada Hill"}, _unattended=True)
    assert got["failed"] and db.t["church_move_items"] == []


def test_the_undo_puts_the_items_lines_back(db, as_):
    fill("owner", {"name": "Ada Hill"})
    got = fill("owner", {"name": "Ada Carter", "mobile": "555-0100"})
    back = run(cmi.handle_undo_move_in_fill, {"item": got["item"], "answers": got["before"]})
    assert not back.get("failed"), back
    assert back["result"].startswith("Put “Name the person who owns the move” back the way it was. It now holds: "
                                     "Their name: Ada Hill.")
    assert item(room(), "owner")["answers"] == {"name": "Ada Hill"}
    # Back to nothing at all is a real undo too.
    first = run(cmi.handle_undo_move_in_fill, {"item": "owner", "answers": {}})
    assert not first.get("failed") and item(room(), "owner")["answers"] == {}
