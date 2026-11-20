"""Chief and the leaders schedule (chief_church_schedule.py; docs/CHURCH_SCHEDULE.md
section 9, step 5). The pastor approved this step on 2026-11-18: a leader says
"I'm out December 20 to 27" and Chief files the ask; the pastor says "Who's off
on the 27th?"; someone says "Find a Saturday for the leaders meeting";
whoever keeps the volunteers asks who's on in Kids this week; "I work every
other Saturday" adds a thing that repeats.

At New Hope (church_three: a made-up church of 500, every name in it made up),
on church_schedule_fake's tables with step 2's file applied, through Chief's
real handlers and the engine the pages use. Pins, each broken once on purpose
to see its test go red (the PR lists them):

  * each verb, in the pastor's own sentences, with a receipt in whole words
  * PRIVACY: a reason, the note with an answer and what a thing that repeats
    is reach only those the engine lets read them, on every read
  * THE LOOK BEFORE SENDING: a full, protected or paired day sends nothing,
    says what is in the way, the nearest open days and who can make an
    exception, and sends only on "ask anyway" (never in the same turn)
  * THE EXCEPTION: only whoever may give it; nothing written the first time;
    a yes lands as an exception only over the flags it said, never in the
    turn that said them
  * TAINT: other people's words read this turn hold every write after them;
    a read of only my own words doesn't
  * THE GATE: unattended, signed out, a viewer, the switch off or closed,
    and before the tables: the not-on words and no read of the schedule
  * ALWAYS AS A LOGIN: a login tied to the owner's own person never gets the
    owner's power, and every call into the engine is made as a login
  * names in words (none, several), no ids anywhere, every handler returns
    a result and a label, and no title word or role key in the rule code
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import re
import sys
from datetime import date

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import chief_church_schedule as ccs  # noqa: E402
import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_limits as csl  # noqa: E402
import church_schedule_repeats as crep  # noqa: E402
import church_three as c3  # noqa: E402
from church_schedule_fake import NOW, day  # noqa: E402

HOPE = c3.NEW_HOPE
SECRET = "Surgery for my mother that week"
LABEL = "Night shift at the hospital"
NOTE = "Praying for your mother"
SEATED = ("elena", "yusuf", "wren", "kara", "celia", "amara", "abel", "esther")   # leaders with a Member login
DEC20, DEC27, XMAS_EVE = "2026-12-20", "2026-12-27", "2026-12-24"
READS = ("who_is_away", "time_off_asks", "check_dates", "serving_week")
WRITES = ("ask_time_off", "answer_time_off", "take_back_time_off", "add_repeat", "take_off_repeat")
VERBS = READS + WRITES
SCHEDULE_TABLES = re.compile(r"^/(church_away_|church_schedule_|church_protected_days|serve_away)")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@pytest.fixture
def db(monkeypatch):
    d = fake.build(monkeypatch, limits=True)
    for h in SEATED:
        fake.seat(d, HOPE, h)
    for t in ("worship_services", "serve_teams", "serve_assignments"):
        d.t[t] = []
    import chief_duties
    monkeypatch.setattr(chief_duties, "_EMAILS", {})
    return d


# ─── helpers ──────────────────────────────────────────────────────────

@contextlib.contextmanager
def signed_in(u):
    import chief_of_staff as cos
    token = cos._TURN_USER_ID.set(u or "")
    try:
        yield
    finally:
        cos._TURN_USER_ID.reset(token)


def uid(db, handle):
    return fake.uid(db, HOPE, handle)


def church(db):
    return co.Church(c3.church(db, HOPE))


def person(db, handle):
    return co.who(co.PERSON, db.who[HOPE][handle])


def login(db, handle):
    return co.who(co.LOGIN, uid(db, handle))


def checked(got):
    """Every answer, whatever it says: a result and a label, and no id."""
    assert isinstance(got.get("result"), str) and got["result"], got
    assert isinstance(got.get("label"), str) and got["label"], got
    assert not UUID.search(json.dumps(got)), ("an id reached the screen", got)
    assert "_foreign" not in got and "_said" not in got
    return got


def turn(db, handle, *calls):
    """Several handlers in one turn (one task: one taint count, one turn's
    record of what was said), as Chief runs a read and then a write."""
    import chief_of_staff as cos

    async def go():
        cos._UNTRUSTED_TAINT.set(0)
        out = []
        for verb, action in calls:
            out.append(checked(await cos.ACTION_HANDLERS[verb](None, {"id": HOPE}, dict(action))))
        return out
    with signed_in(uid(db, handle) if handle else ""):
        return asyncio.run(go())


def run(db, handle, verb, **action):
    return turn(db, handle, (verb, action))[0]


def ok(got):
    assert not got.get("failed"), got["result"]
    return got["result"]


def no(got):
    assert got.get("failed"), got["result"]
    return got["result"]


def asks(db):
    return [r for r in db.t["church_away_asks"] if r["business_id"] == HOPE]


def facts(db):
    return [s for s in db.t["serve_away"] if s["business_id"] == HOPE]


def away(db, handle, start, end=None):
    db.t["serve_away"].append({"id": f"5f000000-0000-4000-8000-{len(db.t['serve_away']):012d}", "business_id": HOPE,
                               "contact_id": db.who[HOPE][handle], "starts_on": start, "ends_on": end or start,
                               "note": "", "ask_id": None, "kind": None, "created_at": NOW.isoformat()})


def two(db):
    """The leaders number set to two, by the owner."""
    csl.set_limit(church(db), login(db, "owner"), {"group": "leaders", "at_most": 2})


def full(db, on=DEC20):
    """Dec 20 with as many leaders away as may be: two, with the number at two."""
    two(db)
    away(db, "wren", on)
    away(db, "kara", on)


def yusufs(db, **kw):
    """Yusuf's ask for Dec 20 to 27 with a private reason, made in the
    office app as his own login (it goes to Amara, the one over him)."""
    return cs.ask(church(db), login(db, "yusuf"), {"starts_on": DEC20, "ends_on": DEC27, "kind": "time_off",
                                                   "reason": SECRET, **kw})


def wrens_shift(db, **kw):
    """Wren's thing that repeats: every other Saturday from Nov 21."""
    return crep.add_commitment(church(db), person(db, "wren"), {"label": LABEL, "weekday": 6, "pattern": "every_other",
                                                                "starts_on": "2026-11-21", **kw})


# ─── Wiring ───────────────────────────────────────────────────────────

def test_the_verbs_are_wired_classified_placed_and_taught():
    import action_inverse as ai
    import action_registry as ar
    import chief_areas
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    import mcp_server
    for verb in VERBS:
        assert cos.ACTION_HANDLERS[verb] is ccs.HANDLERS[verb], verb
        assert ar.classification(verb).get("chief_only"), verb
        assert not ar.may_expose_to_agent(verb, allow_writes=True), verb
        assert verb not in mcp_server.WRITE_TOOL_SCHEMAS and verb not in mcp_server.TOOL_SCHEMAS, verb
        assert chief_areas.VERBS[verb] == (chief_areas.ALL,), verb
        assert cos._ACTION_PHRASES[verb] == ccs.PROGRESS[verb], verb
    for verb in READS:
        assert ar.effect(verb) == "read" and ar.is_sensitive(verb), verb
    for verb in WRITES:
        assert ar.effect(verb) == "write" and not ar.is_bulk(verb), verb
        taught = ccs.BLOCK.replace(" ", "")
        assert f'[ACTION:{{"type":"{verb}"' in taught, f"{verb} is taught as a tag where the schedule is open"
    assert {v: ar.reversibility(v) for v in WRITES} == {
        "ask_time_off": "A", "add_repeat": "A", "answer_time_off": "C", "take_back_time_off": "C",
        "take_off_repeat": "C"}, "an answer and a take-back reach a person and are final; a removal is for good"
    assert set(READS) <= {t["name"] for t in ctl.read_tool_definitions()}
    ctl.reset_turn(writes_allowed=True)
    assert not set(VERBS) & {t["name"] for t in ctl.write_tool_definitions()}, "tags, never native write tools"
    ctl.reset_turn()
    for verb in ("ask_time_off", "add_repeat"):
        assert not ai.can_undo(verb) and "just say so" in ai.why_not(verb)
    assert not {i.verb for i in ai.INVERSES.values()} & set(VERBS)


def test_the_turns_block_only_where_the_schedule_is_open(db, monkeypatch):
    biz = c3.church(db, HOPE)
    line = ccs.turn_line(biz, uid(db, "yusuf"))
    assert line.startswith("LEADERS' DATES") and "VOLUNTEERS' WEEK" not in line, "the week is closed here (owner)"
    assert ccs.turn_line(biz, "1a000000-0000-4000-8000-000000000777") == "", "no seat here"
    assert ccs.turn_line(biz, "") == ""
    monkeypatch.setenv("CHURCH_WEEK", "on")
    assert "VOLUNTEERS' WEEK" in ccs.turn_line(biz, uid(db, "kira"))
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    line = ccs.turn_line(biz, uid(db, "kira"))
    assert "LEADERS' DATES" not in line and line.startswith("VOLUNTEERS' WEEK")
    monkeypatch.setenv("CHURCH_WEEK", "off")
    assert ccs.turn_line(biz, uid(db, "kira")) == ""
    monkeypatch.setenv("CHURCH_SCHEDULE", "on")
    monkeypatch.setattr(cs, "_FORCE", False)
    assert ccs.turn_line(biz, uid(db, "kira")) == "", "before the tables"


# ─── The pastor's sentences ───────────────────────────────────────────

def test_im_out_december_20_to_27(db):
    said = ok(run(db, "yusuf", "ask_time_off", starts_on=DEC20, ends_on=DEC27, reason=SECRET, cover="Kara"))
    assert said == ("Asked: time off, Sun, Dec 20 to Sun, Dec 27. It's waiting for Amara Stone's yes. Kara Bell "
                    "covers. It's on Leaders’ dates.")
    [r] = asks(db)
    assert (r["contact_id"], r["made_by"], r["kind"], r["reason"], r["state"]) == (
        db.who[HOPE]["yusuf"], uid(db, "yusuf"), "time_off", SECRET, "asked")
    assert r["cover_contact_id"] == db.who[HOPE]["kara"] and r["to_contact_id"] == db.who[HOPE]["amara"]
    assert facts(db) == [], "nothing is an away date until someone says yes"
    # Someone covers who isn't on the schedule: typed, as on Dates.
    said = ok(run(db, "yusuf", "ask_time_off", starts_on="2027-01-10", reason="", cover="Mrs. Lopez"))
    assert "Mrs. Lopez covers." in said and asks(db)[-1]["cover_name"] == "Mrs. Lopez"


def test_cant_make_it_needs_no_yes_and_is_never_looked_at(db):
    full(db, day(1))
    said = ok(run(db, "yusuf", "ask_time_off", kind="cant", starts_on=day(1)))
    assert said.startswith("Saved: you can't make it Thu, Nov 19. It's on the calendar now, and Amara Stone hears it "
                           "at once.")
    assert [f["contact_id"] for f in facts(db) if f.get("ask_id")] == [db.who[HOPE]["yusuf"]]
    refused = no(run(db, "yusuf", "ask_time_off", kind="cant", starts_on=day(40)))
    assert refused == f"Failed: {cs.CANT_FAR.format(n=14)[:1].lower()}{cs.CANT_FAR.format(n=14)[1:].rstrip('.')}. " \
                      "Nothing changed.", "the engine's own words"


def test_whos_off_on_the_27th(db):
    a = yusufs(db, cover_contact_id=db.who[HOPE]["kara"])
    cs.answer(church(db), login(db, "amara"), a["id"], True)
    cs.ask(church(db), login(db, "elena"), {"starts_on": "2026-12-26", "ends_on": "2026-12-28", "kind": "commitment"})
    crep.add_commitment(church(db), person(db, "celia"), {"label": "Choir practice", "weekday": 7, "pattern": "weekly"})
    got = run(db, "owner", "who_is_away", day=DEC27)
    said = ok(got)
    assert said.startswith("Who is away on Sun, Dec 27 (the leaders schedule):\nLeaders (")
    assert f"- Yusuf Grant: Sun, Dec 20 to Sun, Dec 27, time off; Kara Bell covers; reason, private: “{SECRET}”" in said
    assert "- Elena Ruiz asked for Sat, Dec 26 to Mon, Dec 28 (another commitment), still waiting for " in said
    assert "- Celia Ward: something that repeats on Sun, Dec 27 (“Choir practice”)" in said
    assert "The office (" in said and got["label"] == "Who is away on Sun, Dec 27"
    # No day named: the coming Sunday (Wednesday Nov 18 -> Sunday Nov 22).
    assert ok(run(db, "owner", "who_is_away")).startswith("Who is away on Sun, Nov 22, the coming Sunday")
    assert "Celia Ward: something that repeats on Sun, Nov 22" in ok(run(db, "owner", "who_is_away"))
    assert no(run(db, "owner", "who_is_away", day="the 27th")) == "Failed: a day is like 2026-11-20"
    too_long = run(db, "owner", "who_is_away", **{"from": DEC20, "to": "2027-04-01"})
    assert no(too_long) == "Failed: pick up to three months"


def test_find_a_saturday_for_the_leaders_meeting(db):
    wrens_shift(db)                                         # Nov 21 and Dec 5
    away(db, "kara", "2026-11-28")
    cs.ask(church(db), login(db, "yusuf"), {"starts_on": "2026-11-27", "ends_on": "2026-11-29", "kind": "time_off"})
    got = run(db, "owner", "check_dates", weekday="Saturday")
    said = ok(got)
    assert said.splitlines()[1:5] == [
        "- Sat, Nov 21: 1 can't: Wren Ellis (something that repeats).",
        "- Sat, Nov 28: 2 can't: Kara Bell (away); Yusuf Grant (has asked to be away, still waiting).",
        "- Sat, Dec 5: 1 can't: Wren Ellis (something that repeats).",
        "- Sat, Dec 12: everyone is free."]
    assert said.splitlines()[5].startswith("Fewest away: Sat, Dec 12 (nobody).") and "Nothing is set" in said
    assert LABEL not in said and got["label"].startswith("Checked 4 days")
    # Another leader doesn't see Yusuf's waiting ask, so it isn't counted for her.
    celia = ok(run(db, "celia", "check_dates", days=["2026-11-28", "2026-12-12"]))
    assert "- Sat, Nov 28: 1 can't: Kara Bell (away)." in celia and "Yusuf" not in celia
    assert db.t["church_away_asks"][-1]["state"] == "asked", "a read: nothing changed"
    assert "a weekday like Saturday" in no(run(db, "owner", "check_dates", weekday="someday"))


def test_i_work_every_other_saturday_and_take_it_off(db):
    to = cs.goes_to(church(db), db.who[HOPE]["wren"])["name"]
    said = ok(run(db, "wren", "add_repeat", label="Work", weekday="Saturday", often="every_other",
                  starts_on="2026-11-21"))
    assert said == (f"Added: “Work”, every other Saturday, from Nov 21. It's on the leaders calendar, and Who serves "
                    f"when won't ask you to serve on those days. {to} hears once that you are away on those days, "
                    f"never what it is.")
    [c] = [r for r in db.t["church_away_commitments"] if r["business_id"] == HOPE]
    assert (c["contact_id"], c["weekday"], c["pattern"], c["starts_on"], c["label"]) == (
        db.who[HOPE]["wren"], 6, "every_other", "2026-11-21", "Work")
    once_a_month = ok(run(db, "wren", "add_repeat", label="Board", weekday="sun", often="month_last"))
    assert "the last Sunday of each month" in once_a_month
    assert no(run(db, "wren", "take_off_repeat", what="")).startswith("Failed: say which: ")
    said = ok(run(db, "wren", "take_off_repeat", what="the work one"))
    assert said == "Took off “Work” (Every other Saturday, from Nov 21). Those days are open again; nobody is told."
    assert [r["label"] for r in db.t["church_away_commitments"]] == ["Board"]
    refused = no(run(db, "wren", "add_repeat", label="", weekday="Saturday", often="weekly"))
    assert refused == "Failed: say what it is, in 80 letters or fewer. Nothing changed."


def test_kira_asks_whos_on_in_kids_this_week(db, monkeypatch):
    week_of(db, monkeypatch)
    got = run(db, "kira", "serving_week", week="2026-11-22", department="Kids")
    said = ok(got)
    assert said.startswith("Volunteers' week, Nov 22 to 28: 1 on, 1 open, 1 away, ")
    assert "hours served this year" in said
    assert "Kids (led by Kara Bell): 1 open." in said
    assert "- Sunday 10:30 AM: Nursery: Lila Penn, Can't serve with kids yet (" in said
    assert "Nursery: Dara Quinn, Away" in said
    assert "Look at first: Kids is short one on Sunday: Nursery. Dara Quinn is away." in said
    assert got["nav"] == ccs.WEEK_NAV and got["label"] == "Volunteers' week, Nov 22 to 28"
    assert "Choir" in no(run(db, "kira", "serving_week", department="Choir")) and "Kids" in no(
        run(db, "kira", "serving_week", department="Choir"))


# ─── Asks waiting, answers, take-backs ────────────────────────────────

def test_whats_waiting_for_my_yes_and_my_own_asks(db):
    yusufs(db)
    waiting = ok(run(db, "amara", "time_off_asks"))
    assert waiting == (f"Waiting for your yes:\n- Yusuf Grant: time off, Sun, Dec 20 to Sun, Dec 27; waiting for Amara "
                       f"Stone's yes; reason, private: “{SECRET}”.")
    mine = ok(run(db, "yusuf", "time_off_asks", box="mine"))
    assert mine.startswith("Your asks:\n- time off, Sun, Dec 20 to Sun, Dec 27; waiting for Amara Stone's yes")
    assert ok(run(db, "celia", "time_off_asks")) == "Nothing is waiting for your yes."
    assert no(run(db, "celia", "time_off_asks", box="all")) == f"Failed: {cs.NOT_ALL[:1].lower()}{cs.NOT_ALL[1:]}"
    assert SECRET in ok(run(db, "owen", "time_off_asks", box="all"))
    assert ok(run(db, "tessa", "time_off_asks", box="mine")).startswith("You have no asks"), "an Admin's own: none"


def test_amara_says_yes_and_then_not_this_one(db):
    a = yusufs(db)
    said = ok(run(db, "amara", "answer_time_off", who="Yusuf", yes=True))
    assert said == ("Said yes to Yusuf Grant's time off, Sun, Dec 20 to Sun, Dec 27. It's on the calendar now, and "
                    "Yusuf hears it.")
    assert next(r for r in asks(db) if r["id"] == a["id"])["state"] == "yes"
    assert [f["ask_id"] for f in facts(db)] == [a["id"]]
    b = cs.ask(church(db), login(db, "yusuf"), {"starts_on": "2027-01-10", "ends_on": "2027-01-10", "kind": "time_off"})
    said = ok(run(db, "amara", "answer_time_off", who="Yusuf Grant", yes=False, note=NOTE))
    assert said == ("Said not this one to Yusuf Grant's time off, Sun, Jan 10, 2027. Yusuf hears it; your note is "
                    "kept with it, private.")
    row = next(r for r in asks(db) if r["id"] == b["id"])
    assert row["state"] == "no" and row["decided_note"] == NOTE
    assert no(run(db, "amara", "answer_time_off", who="Yusuf", yes=True)) == \
        "Failed: nothing is waiting for your yes. Nothing changed."


def test_take_back_my_own_and_the_owner_takes_back_someones(db):
    a = yusufs(db)
    said = ok(run(db, "yusuf", "take_back_time_off", day=DEC20))
    assert said == ("Took back your time off, Sun, Dec 20 to Sun, Dec 27. It's off the calendar. If Amara Stone had "
                    "heard about it, they hear it was taken back.")
    assert next(r for r in asks(db) if r["id"] == a["id"])["state"] == "withdrawn"
    b = cs.ask(church(db), login(db, "wren"), {"starts_on": "2027-01-10", "ends_on": "2027-01-10", "kind": "time_off"})
    refused = no(run(db, "abel", "take_back_time_off", who="Wren"))
    assert refused == f"Failed: {cs.NOT_ASKER[:1].lower()}{cs.NOT_ASKER[1:].rstrip('.')}. Nothing changed."
    said = ok(run(db, "owner", "take_back_time_off", who="Wren Ellis"))
    assert said == "Took back Wren Ellis's time off, Sun, Jan 10, 2027. It's off the calendar, and Wren hears it."
    assert next(r for r in asks(db) if r["id"] == b["id"])["state"] == "withdrawn"
    assert no(run(db, "yusuf", "take_back_time_off")) == "Failed: you have no ask to take back. Nothing changed."


# ─── Privacy ──────────────────────────────────────────────────────────

def test_a_reason_and_what_repeats_reach_only_who_may_read_them(db):
    yusufs(db)
    wrens_shift(db, starts_on="2026-12-26")
    assert cs.goes_to(church(db), db.who[HOPE]["wren"])["name"] == "Abel Ford"
    # (reads the reason, reads what Wren's thing that repeats is, sees Yusuf's ask while it waits)
    readers = {"amara": (True, False, True), "owen": (True, True, True), "owner": (True, True, True),
               "yusuf": (True, False, True), "wren": (False, True, False), "abel": (False, False, False),
               "celia": (False, False, False), "kira": (False, False, False), "tessa": (False, False, False)}
    for handle, (reason, label, waiting) in readers.items():
        said = ok(run(db, handle, "who_is_away", **{"from": DEC20, "to": DEC27}))
        assert (SECRET in said) is reason, (handle, "reason")
        assert (LABEL in said) is label, (handle, "the person, the owner and whoever oversees the office only: "
                                                  "not whoever her asks go to")
        assert "Wren Ellis: something that repeats on Sat, Dec 26" in said, (handle, "name and day: everyone on it")
        assert ("Yusuf Grant asked for Sun, Dec 20 to Sun, Dec 27" in said) is waiting, (handle, "a waiting ask")
    assert "private" not in ok(run(db, "celia", "who_is_away", day=DEC20)), \
        "a waiting ask isn't shown at all, so neither is that it has a reason"
    # Once said yes to, it is on everyone's calendar, and the reason still isn't.
    cs.answer(church(db), login(db, "amara"), asks(db)[0]["id"], True, None)
    said = ok(run(db, "celia", "who_is_away", day=DEC20))
    assert "- Yusuf Grant: Sun, Dec 20 to Sun, Dec 27, time off; the reason is private" in said and SECRET not in said
    # Nor through the asks, nor the candidate days.
    assert SECRET not in json.dumps(run(db, "celia", "time_off_asks", box="all"))
    for handle in ("owner", "celia"):
        assert LABEL not in ok(run(db, handle, "check_dates", days=["2026-12-26", DEC20]))


def test_the_note_with_an_answer_is_as_private_as_the_reason(db):
    a = yusufs(db)
    cs.answer(church(db), login(db, "amara"), a["id"], False, NOTE)
    assert NOTE in ok(run(db, "yusuf", "time_off_asks", box="mine"))
    assert NOTE in ok(run(db, "owen", "time_off_asks", box="all"))
    assert NOTE not in json.dumps([run(db, h, "who_is_away", day=DEC20) for h in ("celia", "kira", "abel")])


# ─── The look before sending ──────────────────────────────────────────

def test_a_full_day_sends_nothing_says_why_and_asks_anyway_sends_it(db):
    full(db)
    got = run(db, "yusuf", "ask_time_off", starts_on=DEC20, ends_on=DEC27, reason=SECRET)
    assert got["failed"] and got["needs_confirmation"] and asks(db) == [], "nothing sent"
    assert got["label"].startswith("Not sent yet. Sun, Dec 20 is full: two of the leaders are already away, and "
                                   "that’s as many as can be away at once. The nearest open ")
    assert got["label"].endswith("You can still ask for these days. It goes to Owen Diaz, who can make an exception. "
                                 "Say ask anyway, and I'll send it.")
    assert '"ask_anyway": true' in got["result"] and "Say this to them first" in got["result"]
    # Asking anyway in the same turn the look spoke: they haven't heard it yet.
    first, again = turn(db, "yusuf", ("ask_time_off", {"starts_on": DEC20, "ends_on": DEC27}),
                        ("ask_time_off", {"starts_on": DEC20, "ends_on": DEC27, "ask_anyway": True}))
    assert first["needs_confirmation"] and again["needs_confirmation"] and asks(db) == []
    # The next turn, they said to ask anyway.
    said = ok(run(db, "yusuf", "ask_time_off", starts_on=DEC20, ends_on=DEC27, reason=SECRET, ask_anyway=True))
    assert said == ("Asked: time off, Sun, Dec 20 to Sun, Dec 27. It went to Owen Diaz, who can make an exception. "
                    "It's on Leaders’ dates.")
    [r] = asks(db)
    assert r["flags"] == ["over_limit"] and r["to_user_id"] == uid(db, "owen")
    # Days with room: no look, sent at once.
    ok(run(db, "yusuf", "ask_time_off", starts_on="2027-01-10"))
    assert len(asks(db)) == 2


def test_a_protected_day_and_a_pair_are_looked_at_too_and_a_pair_is_never_named(db):
    ch = church(db)
    csl.add_protected(ch, login(db, "owner"), {"day": XMAS_EVE, "name": "Christmas Eve"})
    got = run(db, "yusuf", "ask_time_off", starts_on="2026-12-23", ends_on=XMAS_EVE)
    assert got["needs_confirmation"] and "Thu, Dec 24 is a protected day (Christmas Eve)." in got["label"]
    csl.add_pair(church(db), login(db, "owner"), db.who[HOPE]["yusuf"], db.who[HOPE]["wren"])
    away(db, "wren", "2027-01-05", "2027-01-07")
    got = run(db, "yusuf", "ask_time_off", starts_on="2027-01-06", ends_on="2027-01-06")
    assert got["needs_confirmation"] and "This overlaps with someone you can’t be away with at the same time." in \
        got["label"]
    assert "Wren" not in json.dumps(got) and "nearest open" not in got["label"], "never who, never their days"
    assert asks(db) == []


# ─── The exception ────────────────────────────────────────────────────

def _flagged(db):
    full(db)
    a = yusufs(db)
    assert a["flags"] == ["over_limit"] and a["to"]["name"] == "Owen Diaz"
    return a


def test_only_whoever_may_give_the_exception_says_yes_and_only_once_told(db):
    a = _flagged(db)
    for handle in ("amara", "tessa", "kira", "celia"):
        assert no(run(db, handle, "answer_time_off", who="Yusuf", yes=True)) == \
            "Failed: nothing is waiting for your yes. Nothing changed.", handle
    got = run(db, "owen", "answer_time_off", who="Yusuf", yes=True)
    assert got["needs_confirmation"] and got["failed"]
    assert got["label"] == ("Not answered yet. Yusuf Grant's time off, Sun, Dec 20 to Sun, Dec 27, needs an exception. "
                            "Sun, Dec 20 is full: two of the leaders are already away, and that’s as many as can be "
                            "away at once. Your yes makes an exception. Say yes to the exception, and I'll send it.")
    assert '"exception": ["over_limit"]' in got["result"]
    row = next(r for r in asks(db) if r["id"] == a["id"])
    assert row["state"] == "asked" and not any(f.get("ask_id") for f in facts(db)), "nothing written"
    # In the turn that said it: not yet.
    stop, again = turn(db, "owen", ("answer_time_off", {"who": "Yusuf", "yes": True}),
                       ("answer_time_off", {"who": "Yusuf", "yes": True, "exception": ["over_limit"]}))
    assert stop["needs_confirmation"] and again["needs_confirmation"] and row["state"] == "asked"
    # A flag it didn't say: nothing written.
    assert run(db, "owen", "answer_time_off", who="Yusuf", yes=True, exception=["protected_day"])["needs_confirmation"]
    assert row["state"] == "asked"
    # The next turn, they said yes to the exception.
    said = ok(run(db, "owen", "answer_time_off", who="Yusuf", yes=True, exception=["over_limit"]))
    assert said == ("Said yes to Yusuf Grant's time off, Sun, Dec 20 to Sun, Dec 27, as an exception. It's on the "
                    "calendar now, and Yusuf hears it.")
    assert row["state"] == "yes" and row["excepted"] == ["over_limit"]


def test_the_engine_still_gives_no_exception_unsaid_if_chiefs_own_look_ever_misses(db, monkeypatch):
    """Belt and braces: the yes carries to church_schedule.answer exactly the
    flags it named (`shown`), so were Chief's own look ever to miss what is
    in the way, the engine still refuses an exception nobody heard."""
    import member_portal_dates as mpd
    a = _flagged(db)
    monkeypatch.setattr(mpd, "_shown", lambda ask: "")
    refused = no(run(db, "owen", "answer_time_off", who="Yusuf", yes=True))
    assert refused == f"Failed: {cs.YOURS_NOW[:1].lower()}{cs.YOURS_NOW[1:]}"
    row = next(r for r in asks(db) if r["id"] == a["id"])
    assert row["state"] == "asked" and row["excepted"] == [] and not any(f.get("ask_id") for f in facts(db))
    refused = no(run(db, "owen", "answer_time_off", who="Yusuf", yes=True, exception=["protected_day"]))
    assert row["state"] == "asked", "a flag that isn't the one in the way gives nothing"


def test_what_waits_says_what_is_in_the_way_and_a_guarded_ask_is_the_owners_alone(db):
    _flagged(db)
    said = ok(run(db, "owen", "time_off_asks"))
    assert "In the way now: Sun, Dec 20 is full: two of the leaders are already away" in said
    assert '"exception": ["over_limit"]' in said
    e = cs.ask(church(db), login(db, "elena"), {"starts_on": DEC20, "ends_on": DEC20, "kind": "time_off"})
    assert e["flags"] == ["over_limit"] and e["to"]["name"] == "Pastor Nathan"
    refused = no(run(db, "owen", "answer_time_off", who="Elena", yes=True, exception=["over_limit"]))
    assert refused == f"Failed: {cs.NOT_TO_YOU[:1].lower()}{cs.NOT_TO_YOU[1:].rstrip('.')}. Nothing changed."
    assert ok(run(db, "owner", "answer_time_off", who="Elena", yes=True, exception=["over_limit"])).startswith(
        "Said yes to Elena Ruiz's time off, Sun, Dec 20, as an exception.")


def test_a_yes_whose_days_filled_since_goes_up_in_the_engines_words(db):
    two(db)
    a = yusufs(db)
    assert a["flags"] == [] and a["to"]["name"] == "Amara Stone"
    away(db, "wren", DEC20)
    away(db, "kara", DEC20)
    refused = no(run(db, "amara", "answer_time_off", who="Yusuf", yes=True))
    went = cs.WENT_UP.format(name="Owen Diaz")
    assert refused == f"Failed: {went[:1].lower()}{went[1:]}", "it went on: never 'Nothing changed'"
    row = next(r for r in asks(db) if r["id"] == a["id"])
    assert row["state"] == "asked" and row["flags"] == ["over_limit"] and row["to_user_id"] == uid(db, "owen")


# ─── Taint ────────────────────────────────────────────────────────────

def test_a_tainted_turn_holds_every_write_and_reads_still_read(db, monkeypatch):
    import chief_of_staff as cos
    a = yusufs(db)
    wrens_shift(db)
    monkeypatch.setattr(cos, "untrusted_taint", lambda: 1)
    before = (json.dumps(db.t["church_away_asks"], sort_keys=True), json.dumps(db.t["church_away_commitments"]))
    for handle, verb, action in (("yusuf", "ask_time_off", {"starts_on": "2027-01-10"}),
                                 ("amara", "answer_time_off", {"who": "Yusuf", "yes": True}),
                                 ("yusuf", "take_back_time_off", {}),
                                 ("wren", "add_repeat", {"label": "Gym", "weekday": "Monday", "often": "weekly"}),
                                 ("wren", "take_off_repeat", {"what": "shift"})):
        got = run(db, handle, verb, **action)
        assert got["failed"] and got["needs_confirmation"] and "HELD" in got["result"], verb
        assert "Nothing has changed yet" in got["label"], verb
    assert (json.dumps(db.t["church_away_asks"], sort_keys=True), json.dumps(db.t["church_away_commitments"])) == before
    assert next(r for r in asks(db) if r["id"] == a["id"])["state"] == "asked"
    ok(run(db, "amara", "time_off_asks"))


def test_other_peoples_words_read_this_turn_hold_the_write_after_them(db):
    yusufs(db)
    read, answer = turn(db, "amara", ("time_off_asks", {}), ("answer_time_off", {"who": "Yusuf", "yes": True}))
    assert SECRET in ok(read) and answer["needs_confirmation"] and "HELD" in answer["result"]
    assert asks(db)[0]["state"] == "asked"
    wrens_shift(db)
    read, add = turn(db, "owner", ("who_is_away", {"from": "2026-11-21", "to": "2026-11-22"}),
                     ("add_repeat", {"label": "Retreat", "weekday": "Friday", "often": "month_1", "for": "Celia"}))
    assert LABEL in ok(read) and add["needs_confirmation"], "what someone's thing that repeats is: their words"
    # A typed cover name is someone's words too (no reason on this one).
    cs.ask(church(db), login(db, "celia"), {"starts_on": "2027-01-17", "ends_on": "2027-01-17", "kind": "time_off",
                                            "cover_name": "Sister Ada"})
    read, take = turn(db, "owner", ("who_is_away", {"day": "2027-01-17"}), ("take_back_time_off", {"who": "Celia"}))
    assert "Sister Ada covers" in ok(read) and "reason, private" not in ok(read) and take["needs_confirmation"]
    # A cover picked from the schedule is the church's own record: no hold.
    cs.ask(church(db), login(db, "celia"), {"starts_on": "2027-01-24", "ends_on": "2027-01-24", "kind": "time_off",
                                            "cover_contact_id": db.who[HOPE]["kara"]})
    read, take = turn(db, "owner", ("who_is_away", {"day": "2027-01-24"}),
                      ("take_back_time_off", {"who": "Celia", "day": "2027-01-24"}))
    assert "Kara Bell covers" in ok(read) and ok(take).startswith("Took back Celia Ward's time off, Sun, Jan 24, 2027")


def test_a_read_of_only_my_own_words_doesnt_hold(db):
    yusufs(db)
    read, back = turn(db, "yusuf", ("time_off_asks", {"box": "mine"}), ("take_back_time_off", {}))
    assert SECRET in ok(read) and ok(back).startswith("Took back your time off")
    wrens_shift(db)
    read, off = turn(db, "wren", ("who_is_away", {"day": "2026-11-21"}), ("take_off_repeat", {"what": "shift"}))
    assert LABEL in ok(read) and ok(off).startswith("Took off “Night shift at the hospital”")
    read, add = turn(db, "celia", ("check_dates", {"weekday": "Saturday"}),
                     ("add_repeat", {"label": "Choir", "weekday": "Thursday", "often": "weekly"}))
    assert ok(add).startswith("Added: “Choir”"), "check_dates reads names and days alone"


# ─── The gate ─────────────────────────────────────────────────────────

def _all_verbs(db, handle, **extra):
    for verb in VERBS:
        yield verb, run(db, handle, verb, **extra)


def test_unattended_signed_out_and_a_viewer_are_refused(db):
    for verb, got in _all_verbs(db, "yusuf", _unattended=True):
        assert got["failed"] and "only when someone at the church asks" in got["result"], verb
    for verb, got in _all_verbs(db, None):
        assert got["failed"] and "signed in" in got["result"], verb
    viewer = fake.seat(db, HOPE, "n070", role="viewer")
    with signed_in(viewer):
        import chief_of_staff as cos
        got = checked(asyncio.run(cos.ACTION_HANDLERS["who_is_away"](None, {"id": HOPE}, {})))
    assert got["failed"] and got["result"] == "Failed: the leaders schedule is for the church's office logins."
    assert asks(db) == []


def test_switched_off_closed_or_before_the_tables_reads_nothing_of_the_schedule(db, monkeypatch):
    def schedule_reads():
        return [p for p in db.reads if SCHEDULE_TABLES.match(p)]
    for how in ("off", "owner", "tables"):
        db.reads.clear()
        if how == "tables":
            monkeypatch.setenv("CHURCH_SCHEDULE", "on")
            monkeypatch.setattr(cs, "_FORCE", False)
        else:
            monkeypatch.setenv("CHURCH_SCHEDULE", how)
            import chief_duties
            chief_duties._EMAILS[uid(db, "yusuf")] = "yusuf@newhope.church"
        for verb in VERBS:
            if verb == "serving_week":
                continue
            got = run(db, "yusuf", verb, starts_on=DEC20, label="x", weekday="Monday", often="weekly")
            assert got["result"] == f"Failed: {ccs.NOT_ON}", (how, verb, got["result"])
        assert schedule_reads() == [], (how, schedule_reads())
        if how == "off":
            assert db.reads == [], "off: nothing is read at all"
    assert asks(db) == [] and db.t["church_away_commitments"] == []
    monkeypatch.setenv("CHURCH_WEEK", "off")
    assert run(db, "kira", "serving_week")["result"] == f"Failed: {ccs.WEEK_NOT_ON}"


def test_the_platform_owners_own_church_is_open_under_owner(db, monkeypatch):
    monkeypatch.setenv("CHURCH_SCHEDULE", "owner")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", c3.OWNER_EMAIL[c3.NH_OWNER])
    import member_asks
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    assert ok(run(db, "yusuf", "time_off_asks")) == "Nothing is waiting for your yes."


# ─── Always as a login ────────────────────────────────────────────────

def test_a_login_tied_to_the_owners_own_person_never_gets_the_owners_power(db):
    _flagged(db)
    fake.seat(db, HOPE, "nathan")                          # a Member seat on the owner's own record
    assert church(db).login_person.get(uid(db, "nathan")) == church(db).owner_person
    assert no(run(db, "nathan", "time_off_asks", box="all")) == f"Failed: {cs.NOT_ALL[:1].lower()}{cs.NOT_ALL[1:]}"
    assert SECRET not in ok(run(db, "nathan", "who_is_away", day=DEC20))
    assert no(run(db, "nathan", "answer_time_off", who="Yusuf", yes=True, exception=["over_limit"])) == \
        "Failed: nothing is waiting for your yes. Nothing changed."
    refused = no(run(db, "nathan", "ask_time_off", starts_on="2027-01-10", **{"for": "Wren"}))
    assert refused == f"Failed: {cs.NOT_FOR[:1].lower()}{cs.NOT_FOR[1:].rstrip('.')}. Nothing changed."
    assert no(run(db, "nathan", "take_back_time_off", who="Yusuf")).startswith("Failed: only the one who asked")
    assert len(asks(db)) == 1 and asks(db)[0]["state"] == "asked"


def test_every_call_into_the_engine_is_made_as_a_login(db, monkeypatch):
    kinds = []

    def spy(mod, name):
        real = getattr(mod, name)

        def call(ch, me, *a, **k):
            kinds.append((name, me["kind"]))
            return real(ch, me, *a, **k)
        monkeypatch.setattr(mod, name, call)
    for name in ("calendar", "ask", "answer", "withdraw", "mine", "waiting", "everything"):
        spy(cs, name)
    for name in ("add_commitment", "drop_commitment", "commitments"):
        spy(crep, name)
    yusufs(db)
    kinds.clear()
    run(db, "owner", "who_is_away")
    run(db, "owner", "check_dates", weekday="Sunday")
    run(db, "amara", "time_off_asks")
    run(db, "amara", "answer_time_off", who="Yusuf", yes=True)
    run(db, "yusuf", "take_back_time_off")
    run(db, "yusuf", "ask_time_off", starts_on="2027-01-10")
    run(db, "wren", "add_repeat", label="Work", weekday="Saturday", often="weekly")
    run(db, "wren", "take_off_repeat", what="work")
    run(db, "owner", "time_off_asks", box="all")
    assert {n for n, _k in kinds} == {"calendar", "ask", "answer", "withdraw", "mine", "waiting", "everything",
                                      "add_commitment", "drop_commitment", "commitments"}, "each one was called"
    assert {k for _n, k in kinds} == {co.LOGIN}, kinds


# ─── Names ────────────────────────────────────────────────────────────

def test_a_name_that_is_nobody_or_several_changes_nothing_and_says_who(db):
    yusufs(db)
    cs.ask(church(db), login(db, "yusuf"), {"starts_on": "2027-01-10", "ends_on": "2027-01-10", "kind": "time_off"})
    nobody = no(run(db, "amara", "answer_time_off", who="Zelda", yes=True))
    assert "isn't anyone you can act for here" in nobody and "Yusuf Grant" in nobody
    several = no(run(db, "amara", "answer_time_off", who="Yusuf", yes=True))
    assert several == ("Failed: that could be Yusuf Grant's Sun, Dec 20 to Sun, Dec 27 and Yusuf Grant's Sun, Jan 10, "
                       "2027: say whose and which days. Nothing changed.")
    assert all(r["state"] == "asked" for r in asks(db))
    assert ok(run(db, "amara", "answer_time_off", who="Yusuf", day="2027-01-10", yes=True)).endswith(
        "Sun, Jan 10, 2027. It's on the calendar now, and Yusuf hears it.")
    els = no(run(db, "owner", "ask_time_off", starts_on="2027-02-07", **{"for": "El"}))
    assert "could be" in els and "Elena Ruiz" in els and "Elliot Shaw" in els and els.endswith("Nothing changed.")
    off = no(run(db, "owner", "ask_time_off", starts_on="2027-02-07", **{"for": "Hugo Brandt"}))
    assert "isn't anyone you can act for here" in off, "only someone on the leaders schedule"
    assert len(asks(db)) == 2
    said = ok(run(db, "owner", "ask_time_off", starts_on="2027-02-07", **{"for": "Elder Elena"}))
    assert said.startswith("Asked for Elena Ruiz: time off, Sun, Feb 7, 2027.")


# ─── Every answer, every rule ─────────────────────────────────────────

def test_every_handler_answers_with_a_result_and_a_label_and_no_id_on_every_path(db, monkeypatch):
    week_of(db, monkeypatch)
    _flagged(db)
    wrens_shift(db)
    calls = {"who_is_away": [{}, {"day": DEC20}, {"day": "x"}],
             "time_off_asks": [{}, {"box": "mine"}, {"box": "all"}, {"box": "x"}],
             "check_dates": [{"weekday": "Saturday"}, {"days": [DEC20]}, {}],
             "serving_week": [{}, {"week": "2026-11-22", "department": "Kids"}, {"department": "x"}],
             "ask_time_off": [{"starts_on": DEC20}, {"starts_on": "2027-03-07"}, {}],
             "answer_time_off": [{"who": "Yusuf", "yes": True}, {"who": "x", "yes": True}, {}],
             "take_back_time_off": [{"day": "2027-03-07"}, {"who": "Yusuf"}, {}],
             "add_repeat": [{"label": "Gym", "weekday": "Monday", "often": "weekly"}, {}],
             "take_off_repeat": [{"what": "gym"}, {"what": "zzz"}, {}]}
    assert set(calls) == set(VERBS)
    for verb, actions in calls.items():
        for handle in ("owner", "owen", "yusuf", "kira", "celia"):
            for action in actions:
                run(db, handle, verb, **action)           # checked(): a result, a label, no id


def test_no_title_word_or_role_key_decides_anything():
    titles = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                        r"treasurers?|secretary|trustees?|reverend|apostles?|prophets?)\b", re.I)
    keys = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                      r"worship_leader|team_leader|director_of_operations|childrens_director)\b")
    code = inspect.getsource(ccs)
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    code = re.sub(r"#.*", "", code)
    code = code.replace(ccs.BLOCK, "").replace(ccs.WEEK_BLOCK, "")
    assert not keys.search(code), keys.search(code)
    assert not titles.search(code), titles.search(code)


def test_the_four_reads_really_run_mid_turn(db):
    import chief_tool_loop as ctl
    ctl.reset_turn()
    with signed_in(uid(db, "owner")):
        for name, args in (("who_is_away", {}), ("time_off_asks", {}), ("check_dates", {"weekday": "Sunday"})):
            is_error, text = asyncio.run(ctl.execute_tool_use(None, c3.church(db, HOPE), name, args))
            assert not is_error and "not a mid-turn lookup" not in text, (name, text)
    ctl.reset_turn()


# ─── The volunteers' week ─────────────────────────────────────────────

KIDS = "7d000000-0000-4000-8000-0000000000a1"
NURSERY = "7e000000-0000-4000-8000-0000000000a1"
P1, SUN = "7f000000-0000-4000-8000-000000000001", "7f000000-0000-4000-8000-000000000004"


def week_of(db, monkeypatch):
    """New Hope's Kids Check-in team (the Volunteers'; it hangs from Kids by
    its name) with one place, the Nursery, for two. Sunday Nov 22: Lila Penn
    said yes and has no check on record; Dara Quinn said yes and is away Nov
    21 to 23. Lila served Nov 1 too, so she has hours."""
    import church_serving
    import church_week as cw
    import serve_dates as sd
    import sunday_planning as sp
    import test_church_week as tcw
    for t in ("worship_services", "serve_teams", "serve_positions", "serve_trained", "serve_assignments",
              "serve_prefs", "group_meetings", "group_meeting_attendance"):
        db.t[t] = []
    for k in ("CHURCH_SERVING", "SUNDAY_PLANNING"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CHURCH_WEEK", "on")
    monkeypatch.setattr(sd, "_FORCE", True)
    for mod in (cw, church_serving, sp):
        monkeypatch.setattr(mod, "_now", lambda: NOW)
    tcw._serving_reads(db, monkeypatch)
    w = db.who[HOPE]
    for h, name in (("n041", "Lila Penn"), ("n042", "Dara Quinn")):
        next(c for c in db.t["contacts"] if c["id"] == w[h])["name"] = name
    db.t["groups"].append({"id": KIDS, "business_id": HOPE, "name": "Kids Check-in", "kind": "team", "active": True})
    db.t["serve_teams"].append({"group_id": KIDS, "business_id": HOPE, "call_time": None, "max_month": 4,
                                "owner": "volunteers", "swap_needs_ok": False, "families": True, "sort": 0})
    for h in ("n041", "n042"):
        db.t["group_members"].append({"group_id": KIDS, "business_id": HOPE, "contact_id": w[h], "role": "member"})
    db.t["serve_positions"].append({"id": NURSERY, "business_id": HOPE, "group_id": KIDS, "name": "Nursery",
                                    "needed": 2, "note": "", "sort": 0, "active": True,
                                    "created_at": "2026-10-01T00:00:00+00:00"})
    db.t["worship_services"] += [tcw._service(P1, date(2026, 11, 1)), tcw._service(SUN, date(2026, 11, 22))]
    for sid, slot, h in ((P1, 1, "n041"), (SUN, 1, "n041"), (SUN, 2, "n042")):
        db.t["serve_assignments"].append({"id": f"7f100000-0000-4000-8000-{len(db.t['serve_assignments']):012d}",
                                          "business_id": HOPE, "service_id": sid, "position_id": NURSERY, "slot": slot,
                                          "contact_id": w[h], "status": "yes", "asked_at": None, "note": "",
                                          "swap_to": None, "notified_at": None})
    away(db, "n042", "2026-11-21", "2026-11-23")


def test_the_week_is_only_for_whoever_may_read_its_page_and_hours_only_where_allowed(db, monkeypatch):
    week_of(db, monkeypatch)
    import church_week as cw
    for handle in ("olive", "paige", "yusuf"):
        assert run(db, handle, "serving_week")["result"] == f"Failed: {cw.NOT_READER[:1].lower()}{cw.NOT_READER[1:]}", \
            handle
    assert "Lila Penn" in ok(run(db, "owner", "serving_week", week="2026-11-22"))
    monkeypatch.setenv("CHURCH_SERVING", "off")
    said = ok(run(db, "kira", "serving_week", week="2026-11-22", department="Kids"))
    assert "hour" not in said and "Can't serve with kids yet" not in said and "Nursery: Lila Penn, On" in said, \
        "church_serving's rule: no hours, no checks"
    monkeypatch.setenv("CHURCH_WEEK", "owner")
    import chief_duties
    chief_duties._EMAILS[uid(db, "kira")] = "kira@newhope.church"
    assert run(db, "kira", "serving_week")["result"] == f"Failed: {ccs.WEEK_NOT_ON}", "another church's under owner"
