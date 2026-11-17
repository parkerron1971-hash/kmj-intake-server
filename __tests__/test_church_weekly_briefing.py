"""
test_church_weekly_briefing.py — a church's weekly briefing is about a
church's week, in a church's words, and a business's is what it was.

What matters most here, in order:

  1. THE WALL. The church's week is read from the tables named in
     TABLES_READ and no others: every read is recorded and held to that
     list, and nothing in it holds a gift, a payment or a total. The
     letter's facts carry no dollar sign, no payment line, no name and
     no health score, and neither does what is kept or handed back.
  2. EVERY NUMBER IS READ. A count comes from the database's own count,
     a part that couldn't be read is None and is said as "not read",
     never as zero.
  3. A BUSINESS IS UNCHANGED. A coach's briefing gets the prompt, the
     data block and the stored numbers it always got, and the church's
     reader is never called for it.

No model is called and nothing is sent: the model and the database are
fakes that record what they were asked.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import church_weekly_briefing as cwb
import growth_engine as ge

NOW = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)     # a Tuesday
TODAY = NOW.date()
LAST_SUNDAY = date(2026, 11, 15)
SUNDAY_BEFORE = date(2026, 11, 8)
NEXT_SUNDAY = date(2026, 11, 22)

CHURCH = {"id": "biz-church", "name": "Grace Chapel", "type": "church", "owner_id": "u1",
          "settings": {"practitioner_name": "Pastor Ann"}, "voice_profile": {"tone": "warm and plain"}}
COACH = {"id": "biz-coach", "name": "Peak Coaching", "type": "coach", "owner_id": "u2",
         "settings": {"practitioner_name": "Dana"}, "voice_profile": {"tone": "direct"}}

ROSTER = {"id": "mod-1", "name": "Services & Events", "archetype_params": {"occasion_noun": "services"}}
ENTRIES = [
    {"id": "svc-last", "module_id": "mod-1", "data": {"title": "Sunday service", "date": LAST_SUNDAY.isoformat()}},
    {"id": "svc-before", "module_id": "mod-1", "data": {"title": "Sunday service", "date": SUNDAY_BEFORE.isoformat()}},
    {"id": "svc-next", "module_id": "mod-1", "data": {"title": "Sunday service", "date": NEXT_SUNDAY.isoformat()}},
    # A midweek service in the days that nobody counted.
    {"id": "svc-wed", "module_id": "mod-1", "data": {"title": "Midweek service", "date": "2026-11-11"}},
]


class FakeDB:
    """sb_clients' two service reads, recording every path."""

    def __init__(self, fail: str = ""):
        self.paths: List[str] = []
        self.fail = fail

    def tables(self) -> set:
        return {p.split("?", 1)[0].lstrip("/") for p in self.paths}

    def get(self, path: str, **_: Any):
        self.paths.append(path)
        table = path.split("?", 1)[0].lstrip("/")
        if table == self.fail:
            return None
        if table == "custom_modules":
            return [ROSTER]
        if table == "module_entries":
            return [] if "offset=1000" in path else ENTRIES
        if table == "attendance_headcounts":
            return [{"entry_id": "svc-last", "count": 140}, {"entry_id": "svc-before", "count": 60},
                    {"entry_id": "svc-before", "count": 70}]
        if table == "attendance":            # first-time rows (the per-service count is a HEAD)
            return [{"contact_id": "c1", "name": "A"}, {"contact_id": None, "name": "Guest  One"},
                    {"contact_id": None, "name": "guest one"}, {"contact_id": "c1", "name": "A"}]
        if table == "church_follow_ups":     # New here cards in the days
            return [{"contact_id": "c1"}, {"contact_id": "c9"}]
        if table == "worship_services":
            return [{"id": "plan-1", "title": "Sunday service", "starts_at": "2026-11-22T16:00:00+00:00"}]
        if table == "serve_teams":
            return [{"group_id": "g1", "sort": 1}]
        if table == "groups":
            return [{"id": "g1", "name": "Welcome team"}] if "kind=eq.team" in path else []
        if table == "serve_positions":
            return [{"id": "pos-1", "group_id": "g1", "name": "Greeter", "needed": 2, "sort": 1}]
        if table == "serve_assignments":
            return [{"service_id": "plan-1", "position_id": "pos-1", "slot": 1, "status": "yes"}]
        return []

    def count(self, path: str):
        self.paths.append(path)
        table = path.split("?", 1)[0].lstrip("/")
        if table == self.fail:
            return None
        if table == "attendance":
            return 152 if "svc-last" in path else 0
        if table == "contacts":
            return 2 if "created_at=lt." in path else 4
        if table == "church_follow_ups":
            if "status=eq.done" in path:
                return 3
            if "due_at=lt." in path:
                return 1
            return 2 if "leader_contact_id.is.null" in path else 6
        return 0


@pytest.fixture
def db(monkeypatch):
    import church_leaders_note as ln
    import sb_clients
    fake = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_count_as_service", fake.count)
    monkeypatch.setattr(cwb, "_now", lambda: NOW)
    monkeypatch.setattr(ln, "_zone", lambda biz: timezone.utc)
    return fake


# ─── The church's week ────────────────────────────────────────────────

def test_the_week_is_read_from_the_churchs_records(db):
    w = cwb.week(CHURCH)
    # The larger of the people checked in (152) and the headcount (140).
    assert w["services"]["held"] == [
        {"title": "Sunday service", "day": "2026-11-15", "words": "Sunday, November 15", "count": 152}]
    # The service before: two headcounts added up, nobody checked in by name.
    assert w["services"]["before"]["count"] == 130 and w["services"]["before"]["day"] == "2026-11-08"
    assert w["services"]["uncounted"] == 1                      # the midweek one
    # One person once: c1 twice at check-in and on a card, the named guest twice, c9 on a card.
    assert w["first_time"] == 3
    assert w["new_people"] == {"this_week": 4, "week_before": 2}
    assert w["follow_up"] == {"open": 6, "no_one": 2, "late": 1, "finished": 3}
    assert w["needed"]["open_places"] == 1 and "Greeter" in w["needed"]["lines"][0]
    assert [c["title"] for c in w["coming"]] == ["Sunday service"]
    assert w["coming"][0]["words"] == "Sunday, November 22"
    assert w["unread"] == []


def test_the_week_reads_only_the_tables_it_names_and_none_of_them_is_giving(db):
    cwb.week(CHURCH)
    assert db.tables() <= cwb.TABLES_READ, db.tables() - cwb.TABLES_READ
    for table in cwb.TABLES_READ:
        assert not any(w in table for w in ("giving", "gift", "donation", "payment", "invoice", "ledger", "restricted",
                                            "pledge", "stripe", "bank")), table


def test_a_next_sunday_that_has_not_happened_is_never_counted(db):
    w = cwb.week(CHURCH)
    assert all(h["day"] <= TODAY.isoformat() for h in w["services"]["held"])
    assert not any("svc-next" in p for p in db.paths)


@pytest.mark.parametrize("table,part", [
    ("attendance_headcounts", "services"), ("contacts", "new_people"),
    ("church_follow_ups", "follow_up"), ("worship_services", "coming"),
])
def test_a_part_that_could_not_be_read_is_unknown_never_zero(monkeypatch, db, table, part):
    db.fail = table
    w = cwb.week(CHURCH)
    assert w[part] is None and part in w["unread"]
    stats = {"church_week": w, "pending_items": [], "sessions_completed_count": 0, "sessions_upcoming_count": 0}
    said = cwb.facts(stats)
    assert "NOT READ THIS TIME (unknown, not zero): " in said
    assert cwb.PART_WORDS[part] in said.split("NOT READ THIS TIME")[1]
    assert "**Not read this time:**" in cwb.numbers_markdown(stats)


def test_a_week_that_fails_whole_still_answers(monkeypatch, db):
    db.fail = "custom_modules"
    w = cwb.week(CHURCH)
    assert w["services"] is None and "services" in w["unread"]
    assert w["new_people"] == {"this_week": 4, "week_before": 2}


# ─── What the model is told ───────────────────────────────────────────

def _stats(db) -> Dict[str, Any]:
    return {"church": True, "church_week": cwb.week(CHURCH), "window_end": NOW.isoformat(),
            "pending_items": [{"agent": "nurture", "action_type": "check_in", "subject": "Checking in"}],
            "sessions_completed_count": 2, "sessions_upcoming_count": 1,
            # What the business letter read, which a church's never says.
            "payment_sum": 4321.0, "payment_event_count": 9,
            "at_risk": [{"name": "Riley Quiet", "health_score": 12}], "thriving": [],
            "new_contacts": [{"name": "Nina New"}]}


def test_the_facts_are_the_churchs_week_in_church_words(db):
    said = cwb.facts(_stats(db))
    assert "Sunday service, November 15: 152 counted" in said          # the day isn't said twice
    assert "THE COUNTED SERVICE BEFORE THOSE: Sunday service, November 8: 130 counted" in said
    assert cwb._service_words({"title": "Midweek service", "day": "2026-11-11", "words": "Wednesday, November 11"}) \
        == "Midweek service, Wednesday, November 11"
    assert "FIRST-TIME GUESTS (marked at check-in or on a New here card): 3" in said
    assert "NEW PEOPLE ADDED TO THE CHURCH'S RECORDS: 4 this week, 2 the week before" in said
    assert "6 people are in follow-up; 2 have no one to reach out to them yet; 1 is late; 3 follow-ups were finished" in said
    assert "MEETINGS (booked on the Meetings page): 2 held this week, 1 coming" in said
    assert "DRAFTS WAITING IN APPROVALS: 1" in said
    assert "Sunday, November 22: 4:00 PM Sunday service" in said


def test_the_facts_never_carry_money_a_name_or_a_score(db):
    said = cwb.facts(_stats(db)) + cwb.numbers_markdown(_stats(db))
    for banned in ("$", "4321", "PAYMENT", "payment", "Riley", "Nina", "health", "HEALTH", "AT-RISK", "client",
                   "lead", "revenue", "session"):
        assert banned not in said, banned


def test_the_letter_is_told_to_write_a_churchs_letter():
    p = cwb.system_prompt(CHURCH)
    assert "weekly briefing for Grace Chapel, a church" in p
    for heading in (cwb.HEADLINE, cwb.WENT_WELL, cwb.ATTENTION, cwb.FOCUS):
        assert f"## {heading}\n" in p
    assert "Never mention giving, money, payments or scores" in p
    assert "never clients, customers, contacts or leads" in p
    assert "Address Pastor Ann by name once" in p and "Name no one else" in p
    assert "practitioner" not in p and "Growth Intelligence" not in p


def test_a_church_with_no_name_on_file_is_never_called_the_practitioner():
    p = cwb.system_prompt({"id": "b", "name": "Grace Chapel", "type": "church", "settings": {}})
    assert "Write it to the people who run the church." in p
    assert "- Name no one." in p and "practitioner" not in p
    assert cwb.reader_of({"settings": {"practitioner_name": "the practitioner"}}) == ""


def test_the_numbers_are_printed_as_read(db):
    md = cwb.numbers_markdown(_stats(db))
    assert md.startswith(f"## {cwb.NUMBERS}\n")
    assert "- **Sunday service, November 15:** 152 counted (130 at the service before)" in md
    assert "- **First-time guests:** 3" in md
    assert "- **New people added:** 4 (2 the week before)" in md
    assert "- **In follow-up:** 6, and 2 have no one yet; 1 late" in md
    assert "- **Follow-ups finished:** 3" in md
    assert "- **Meetings:** 2 held, 1 coming" in md
    assert f"## {cwb.OPEN_PLACES}\n- Sunday service, Sunday, November 22: 1 place is still open. Welcome team: Greeter." in md
    assert f"## {cwb.COMING}\n- **Sunday, November 22:** Sunday service at 4:00 PM" in md


def test_an_empty_week_prints_what_is_true_and_no_empty_headings():
    stats = {"church_week": {"services": {"held": [], "before": None, "uncounted": 0}, "first_time": 0,
                             "new_people": {"this_week": 0, "week_before": 0},
                             "follow_up": {"open": 0, "no_one": 0, "late": 0, "finished": 0},
                             "needed": {"open_places": 0, "waiting": 0, "roles": 0, "lines": []}, "coming": [],
                             "unread": []},
             "pending_items": [], "sessions_completed_count": 0, "sessions_upcoming_count": 0}
    md = cwb.numbers_markdown(stats)
    assert "- **Sunday:** no service in these days has a count yet" in md
    assert "- **In follow-up:** 0\n" in md + "\n"
    assert cwb.OPEN_PLACES not in md and cwb.COMING not in md and "Meetings" not in md and "Drafts" not in md
    said = cwb.facts(stats)
    assert "None. Every place on the Sunday teams and every event role is filled." in said
    assert "Nothing is on the church calendar." in said


# ─── The drafts ───────────────────────────────────────────────────────

def test_the_drafts_list_is_in_church_words():
    actions = [
        {"kind": "created", "agent": "nurture", "action_type": "check_in", "contact_name": "Sam"},
        {"kind": "created", "agent": "session", "action_type": "follow_up", "contact_name": "Lee"},
        {"kind": "already_queued", "agent": "nurture", "action_type": "check_in", "contact_name": "Pat",
         "existing_created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()},
    ]
    md = cwb.actions_markdown(actions, 0, ge._days_since)
    assert md.startswith(f"## {cwb.DRAFTS}\n")
    assert "- A check-in for Sam is drafted and waiting in Approvals" in md
    assert "- A follow-up after your meeting with Lee is drafted and waiting in Approvals" in md
    assert "- A check-in for Pat has been waiting in Approvals for 3 days" in md
    assert "Open Approvals to read them and send the ones you want." in md
    for banned in ("Queue", "session", "health", "→"):
        assert banned not in md
    assert cwb.actions_markdown([], 0, ge._days_since) == ""


def test_a_check_in_for_one_of_a_churchs_people_carries_no_score(monkeypatch):
    seen: Dict[str, str] = {}

    async def model(client, system, user, model=None, max_tokens=0):
        seen.update(system=system, user=user)
        return "Thinking of you."
    monkeypatch.setattr(ge, "_call_claude", model)
    last = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    person = {"id": "c1", "name": "Sam", "health_score": 12, "last_interaction": last}
    out = asyncio.run(ge._draft_nurture_check_in(None, CHURCH, person, kind="at-risk"))
    said = seen["system"] + seen["user"]
    assert "a church" in seen["system"] and "from Pastor Ann to Sam" in seen["system"]
    for banned in ("12", "Health", "health score", "at-risk", "Nurture Agent"):
        assert banned not in said, banned
    assert out["reasoning"] == "Nothing recorded in 30 days for Sam. Drafted with the weekly briefing."
    assert out["subject"] == "Checking in" and out["body"] == "Thinking of you."

    # A business's check-in is the one it always was.
    asyncio.run(ge._draft_nurture_check_in(None, COACH, person, kind="at-risk"))
    assert "You are the Nurture Agent for Peak Coaching" in seen["system"]
    assert "Health score is 12 (at-risk)" in seen["user"]


def test_a_follow_up_after_a_meeting_is_never_about_a_session(monkeypatch):
    seen: Dict[str, str] = {}

    async def model(client, system, user, model=None, max_tokens=0):
        seen.update(system=system, user=user)
        return "Good to sit with you."
    monkeypatch.setattr(ge, "_call_claude", model)
    out = asyncio.run(ge._draft_session_followup(None, CHURCH, {"name": "Lee"},
                                                 {"title": "Marriage prep", "notes": "Set a date"}))
    assert "session" not in (seen["system"] + seen["user"]).lower()
    assert "Meeting: Marriage prep" in seen["user"]
    assert out["subject"] == "Following up on Marriage prep"
    assert "session" not in out["reasoning"].lower()

    asyncio.run(ge._draft_session_followup(None, COACH, {"name": "Lee"}, {"title": "Kickoff"}))
    assert "You are the Session Agent for Peak Coaching" in seen["system"]


# ─── The whole briefing, end to end ───────────────────────────────────

class FakeSB:
    def __init__(self, biz: Dict[str, Any]):
        self.biz = biz
        self.posts: List[Any] = []

    async def __call__(self, client, method: str, path: str, body=None):
        if method == "POST":
            self.posts.append((path, body))
            return [{"id": "ins-1"}]
        if path.startswith("/businesses"):
            return [self.biz]
        if path.startswith("/contacts") and "health_score=lt.40" in path:
            return [{"id": "c7", "name": "Riley Quiet", "health_score": 12}]
        if path.startswith("/contacts") and "created_at=gte." in path:
            return [{"id": "c8", "name": "Nina New", "status": "lead", "source": "form"}]
        if path.startswith("/events"):
            return [{"event_type": "giving_received", "data": {"amount": 4321}, "created_at": NOW.isoformat()}]
        return []


def _run(monkeypatch, biz: Dict[str, Any], week_calls: List[Any], reply: str = "## The headline\nA good week.\n"):
    sb = FakeSB(biz)
    calls: List[Dict[str, str]] = []

    async def model(client, system, user, model=None, max_tokens=0):
        calls.append({"system": system, "user": user, "model": model})
        return reply

    async def no_actions(client, b):
        return {"actions": [], "total_created": 0, "total_skipped": 0, "pending_proposals_count": 0}

    def week(b):
        week_calls.append(b["id"])
        return {"ending": "Tuesday, November 17", "today": "2026-11-17", "unread": [],
                "services": {"held": [{"title": "Sunday service", "day": "2026-11-15", "words": "Sunday, November 15",
                                       "count": 152}], "before": None, "uncounted": 0},
                "first_time": 3, "new_people": {"this_week": 4, "week_before": 2},
                "follow_up": {"open": 6, "no_one": 2, "late": 0, "finished": 3},
                "needed": {"open_places": 0, "waiting": 0, "roles": 0, "lines": []}, "coming": []}

    monkeypatch.setattr(ge, "_sb", sb)
    monkeypatch.setattr(ge, "_call_claude", model)
    monkeypatch.setattr(ge, "_generate_briefing_actions", no_actions)
    monkeypatch.setattr(cwb, "week", week)
    out = asyncio.run(ge.run_growth_briefing(biz["id"]))
    return out, sb, calls


def test_a_churchs_briefing_is_one_call_about_the_churchs_week(monkeypatch):
    week_calls: List[Any] = []
    out, sb, calls = _run(monkeypatch, CHURCH, week_calls)
    assert week_calls == ["biz-church"]
    assert len(calls) == 1 and calls[0]["model"] == ge.BRIEFING_MODEL          # same lane, one call
    assert "a church" in calls[0]["system"] and "Growth Intelligence" not in calls[0]["system"]
    user = calls[0]["user"]
    assert "Sunday service, November 15: 152 counted" in user
    for banned in ("PAYMENT", "4321", "$", "Riley", "Nina", "AT-RISK", "THRIVING", "giving_received"):
        assert banned not in user, banned
    # The numbers are printed under the letter as read.
    assert out["body"].startswith("## The headline\nA good week.")
    assert "## The week in numbers\n- **Sunday service, November 15:** 152 counted" in out["body"]
    assert "Community growth" not in out["body"]

    path, row = sb.posts[-1]
    assert path == "/insights" and row["evidence"]["kind"] == "weekly_briefing"
    assert row["title"].startswith("Weekly Briefing — ")                        # the page reads the dates from it
    kept = row["evidence"]["stats"]
    assert set(kept) == {"sessions_completed", "sessions_upcoming", "drafts_by_agent"}
    assert row["evidence"]["church_week"]["first_time"] == 3
    import json
    for banned in ("4321", "Riley", "Nina", "payment"):
        assert banned not in json.dumps(row["evidence"]), banned
        assert banned not in json.dumps(out["stats"], default=str), banned


def test_a_churchs_letter_that_could_not_be_written_still_has_its_numbers(monkeypatch):
    out, sb, _ = _run(monkeypatch, CHURCH, [], reply="")
    assert out["body"].startswith("## The headline\nThe letter couldn't be written this time.")
    assert "- **First-time guests:** 3" in out["body"]
    assert "At-risk contacts" not in out["body"] and "Sessions completed" not in out["body"]
    assert sb.posts[-1][1]["evidence"]["body_fallback"] is True


def test_a_businesss_briefing_is_what_it_was(monkeypatch):
    week_calls: List[Any] = []
    out, sb, calls = _run(monkeypatch, COACH, week_calls)
    assert week_calls == []                                                     # the church's reader is never run
    assert len(calls) == 1
    assert calls[0]["system"].startswith("You are the Growth Intelligence Engine for Peak Coaching.")
    assert "## By The Numbers" in calls[0]["system"] and "Address Dana by name" in calls[0]["system"]
    user = calls[0]["user"]
    assert "PAYMENT ACTIVITY: 1 events, $4321.00 total" in user
    assert "AT-RISK CONTACTS (health < 40): 1\n  Riley Quiet (12)" in user
    assert "NEW CONTACTS: 1\n  Nina New" in user
    kept = sb.posts[-1][1]["evidence"]["stats"]
    assert kept["payment_sum"] == 4321.0 and kept["new_contacts"] == 1 and kept["at_risk"] == 1
    assert "church_week" not in sb.posts[-1][1]["evidence"]
    assert out["stats"]["payment_sum"] == 4321.0
    assert "The week in numbers" not in out["body"]
