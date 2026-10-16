"""The rail's practice mode (chief_rail.py, docs/CHIEF_RAIL.md).

A records question ("Did Maria pay?") is read fresh after Chief has replied,
answered from the rows alone, proved by chief_truth's free prover, and
compared with what Chief said. Nothing here is ever shown to anyone; these
tests pin what it takes, what it says, how it proves it, and that it can't
read a business the asker does not own.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_rail as rail

TZ = ZoneInfo("America/Detroit")
BIZ = "22222222-2222-2222-2222-222222222222"
USER = "11111111-1111-1111-1111-111111111111"
STRANGER = "33333333-3333-3333-3333-333333333333"
NOW = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)     # Friday, noon in Detroit


def _invoice(n, total, status, due, client):
    return {"id": f"i{n}", "invoice_number": f"INV-{n:04d}", "total": total, "status": status,
            "due_date": due, "contacts": {"name": client} if client else None}


OPEN = [
    _invoice(12, 450, "sent", "2020-01-10", "Maria Lopez"),
    _invoice(13, 300, "viewed", "2099-10-30", "Maria Lopez"),
    _invoice(14, 1200, "overdue", "2020-01-05", "Tasha Green"),
    _invoice(15, 80, "draft", None, "Dee Park"),
]
SESSIONS = [
    {"id": "s1", "title": "Haircut", "scheduled_for": "2026-10-17T14:00:00+00:00", "contact_id": "c1",
     "contacts": {"name": "Maria Lopez"}},
    {"id": "s2", "title": "", "scheduled_for": "2026-10-17T16:30:00+00:00", "contact_id": "c2",
     "contacts": {"name": "Tasha Green"}},
]
CONTACTS = [{"id": "c1", "name": "Maria Lopez"}, {"id": "c2", "name": "Tasha Green"},
            {"id": "c3", "name": "Mariah Stone"}]


# ─── What the rail takes ─────────────────────────────────────────────

@pytest.mark.parametrize("message, shelf, form, name, day", [
    ("Who owes me money?", "money", "who_owes", None, None),
    ("Hey Chief, who still owes me?", "money", "who_owes", None, None),
    ("Who hasn't paid yet?", "money", "who_owes", None, None),
    ("How much am I owed?", "money", "owed_total", None, None),
    ("How much do my clients owe me right now?", "money", "owed_total", None, None),
    ("What's outstanding?", "money", "owed_total", None, None),
    ("Any overdue invoices?", "money", "overdue", None, None),
    ("Do I have any overdue invoices?", "money", "overdue", None, None),
    ("Who's overdue?", "money", "overdue", None, None),
    ("Did Maria pay?", "money", "did_pay", "maria", None),
    ("did maria lopez pay her invoice yet", "money", "did_pay", "maria lopez", None),
    ("Has Tasha paid?", "money", "did_pay", "tasha", None),
    ("Is Maria paid up?", "money", "did_pay", "maria", None),
    ("How much does Maria owe me?", "money", "client_balance", "maria", None),
    ("What's on my calendar tomorrow?", "schedule", "day", None, "tomorrow"),
    ("What do I have today?", "schedule", "day", None, "today"),
    ("Do I have any appointments on Monday?", "schedule", "day", None, "monday"),
    ("How many sessions do I have tomorrow?", "schedule", "day", None, "tomorrow"),
    ("Who am I seeing today?", "schedule", "day", None, "today"),
    ("When is my next appointment?", "schedule", "next", None, None),
    ("Who's my next client?", "schedule", "next", None, None),
    ("When is Maria's appointment?", "schedule", "client_next", "maria", None),
    ("When am I seeing Tasha next?", "schedule", "client_next", "tasha", None),
])
def test_the_shelves_take_these_questions_whole(message, shelf, form, name, day):
    q, why, _ = rail.read_question(message)
    assert q is not None, why
    assert (q.shelf, q.form, q.name, q.day) == (shelf, form, name, day)


@pytest.mark.parametrize("message, why", [
    ("Did she pay?", "not_a_name"),                       # leans on the conversation
    ("Did the Smiths pay?", "not_a_name"),
    ("When is my next payment due to the IRS and should I pay early?", "phrasing"),
    ("Send Maria a reminder about her invoice", "phrasing"),   # an action, not a lookup
    ("Am I free Thursday at 3?", "phrasing"),            # availability has its own readout
    ("What's on my calendar this week?", "phrasing"),    # a window the shelf does not take yet
    ("What's on my calendar next Friday?", "phrasing"),
    ("How do I grow my revenue?", "no_shelf"),
    ("", "not_a_lookup"),
])
def test_anything_else_is_declined_with_a_reason(message, why):
    q, got, _ = rail.read_question(message)
    assert q is None and got == why


# ─── What it says, and the proof ─────────────────────────────────────

def _money_records(rows=OPEN, **kw):
    return rail.Records(open_invoices=rail._chief_rows(rows), **kw)


def _say(message, rec):
    q, why, _ = rail.read_question(message)
    assert q is not None, why
    answer, left = rail.compose(q, rec, TZ)
    assert answer is not None, left
    return q, answer, rail.prove(answer, rec, TZ)


def test_who_owes_is_said_one_client_per_sentence_and_proved():
    _, a, (proof, cited) = _say("Who owes me?", _money_records())
    assert a.text == ("You're owed $1,950.00 across 3 sent invoices. "
                      "Tasha Green owes $1,200.00 across 1 invoice, $1,200.00 of it overdue. "
                      "Maria Lopez owes $750.00 across 2 invoices, $450.00 of it overdue.")
    assert proof == "prover" and cited == ["context:invoice_summary"]


def test_how_much_and_overdue_answers_are_proved():
    _, a, (proof, _) = _say("How much am I owed?", _money_records())
    assert a.text.startswith("You're owed $1,950.00 across 3 sent invoices. 2 of those invoices are overdue, "
                             "$1,650.00 in total. You also have 1 draft, $80.00, not yet sent.")
    assert proof == "prover"
    _, a, (proof, _) = _say("Any overdue invoices?", _money_records())
    assert a.text == ("2 invoices are overdue, $1,650.00 in total. Tasha Green has $1,200.00 overdue. "
                      "Maria Lopez has $450.00 overdue.")
    assert proof == "prover"


def test_did_pay_reads_one_clients_invoices():
    maria = [r for r in OPEN[:2]]
    paid = [{"number": "INV-0009", "client": "Maria Lopez", "total": 250.0, "status": "paid",
             "paid_at": "2026-10-03T15:00:00+00:00", "due_date": "2026-10-01"}]
    rec = _money_records(maria, paid_invoices=paid, contact={"id": "c1", "name": "Maria Lopez"})
    _, a, (proof, _) = _say("Did Maria pay?", rec)
    assert a.text.startswith("Maria Lopez owes $450.00 on invoice INV-0012, due Jan 10, ")
    assert "Maria Lopez owes $300.00 on invoice INV-0013, due Oct 30." in a.text
    assert a.text.endswith("Maria Lopez paid invoice INV-0009, $250.00, on Oct 3.")
    assert a.facts["polarity"] == "owes" and proof == "prover"
    rec = _money_records([], paid_invoices=paid, contact={"id": "c1", "name": "Maria Lopez"})
    _, a, (proof, _) = _say("Did Maria pay?", rec)
    assert a.text == "Maria Lopez paid invoice INV-0009, $250.00, on Oct 3."
    assert a.facts["polarity"] == "paid" and proof == "prover"


def test_a_day_on_the_calendar_is_proved_on_the_business_clock():
    rec = rail.Records(sessions=SESSIONS, label="tomorrow", window="2026-10-17, Saturday",
                       day_iso="2026-10-17")
    _, a, (proof, _) = _say("What's on my calendar tomorrow?", rec)
    # 14:00 UTC is 10 AM in Detroit; saying the UTC hour would be wrong.
    assert a.text == "You have 2 sessions tomorrow. 10:00 AM: Haircut with Maria Lopez. 12:30 PM: Tasha Green."
    assert proof == "prover" and a.facts["times"] == ["10:00", "12:30"]


def test_the_next_session_and_a_clients_next_session():
    rec = rail.Records(sessions=SESSIONS[:1], window="next booked")
    _, a, (proof, _) = _say("When is my next appointment?", rec)
    assert a.text == "Your next session is Haircut with Maria Lopez on Saturday, Oct 17 at 10:00 AM."
    assert proof == "prover"
    rec = rail.Records(sessions=SESSIONS[:1], contact={"id": "c1", "name": "Maria Lopez"}, window="next")
    _, a, (proof, _) = _say("When is Maria's appointment?", rec)
    assert a.text == "Maria Lopez is booked for Haircut on Saturday, Oct 17 at 10:00 AM." and proof == "prover"


def test_nothing_to_report_is_proved_by_the_whole_read():
    _, a, proof = _say("Who owes me?", _money_records([OPEN[3]]))          # only a draft
    assert a.text == "Nobody owes you right now: there are no sent, unpaid invoices."
    assert proof == ("empty_read", [])
    rec = rail.Records(sessions=[], label="tomorrow", window="x", day_iso="2026-10-17")
    _, a, proof = _say("What do I have tomorrow?", rec)
    assert a.text == "Nothing is booked tomorrow." and proof == ("empty_read", [])
    # A read that did not return every row proves no "nothing".
    rec = rail.Records(sessions=[], label="tomorrow", window="x", day_iso="2026-10-17", complete=False)
    _, _, proof = _say("What do I have tomorrow?", rec)
    assert proof == ("failed", [])


def test_the_proof_is_real_a_wrong_figure_fails_it():
    q, a, _ = _say("How much am I owed?", _money_records())
    wrong = rail.Answer(a.text.replace("$1,950.00", "$1,995.00"), a.sources, a.facts)
    assert rail.prove(wrong, _money_records(), TZ)[0] == "failed"
    wrong = rail.Answer(a.text.replace("3 sent invoices", "4 sent invoices"), a.sources, a.facts)
    assert rail.prove(wrong, _money_records(), TZ)[0] == "failed"


def test_long_lists_and_unnamed_clients_are_left_to_chief():
    many = [_invoice(n, 10 + n, "sent", "2099-01-01", f"Client{chr(65 + n)} Person") for n in range(7)]
    q, _, _ = rail.read_question("Who owes me?")
    assert rail.compose(q, _money_records(many), TZ) == (None, "too_long")
    nameless = [_invoice(1, 50, "sent", "2099-01-01", None)]
    assert rail.compose(q, _money_records(nameless), TZ) == (None, "unnamed_client")


# ─── Did Chief say the same? ─────────────────────────────────────────

def _money_answer(message="How much am I owed?", rows=OPEN, **kw):
    q, a, _ = _say(message, _money_records(rows, **kw))
    return q, a


@pytest.mark.parametrize("reply, outcome", [
    ("You're owed $1,950 across three invoices, and $1,650 of it is overdue.", "agrees"),
    ("Tasha owes you $1,200.00, the biggest balance.", "partial"),
    ("You're owed $2,100 right now.", "differs"),
    ("I couldn't verify your invoices right now.", "withheld"),
    ("Want me to pull up the invoices page?", "silent"),
])
def test_money_replies_are_compared_by_their_figures(reply, outcome):
    q, a = _money_answer()
    assert rail.compare(q, a, reply)[0] == outcome


def test_did_pay_compares_the_yes_or_no():
    paid = [{"number": "INV-0009", "client": "Maria Lopez", "total": 250.0, "status": "paid",
             "paid_at": "2026-10-03T15:00:00+00:00", "due_date": "2026-10-01"}]
    q, a = _money_answer("Did Maria pay?", [], paid_invoices=paid, contact={"id": "c1", "name": "Maria Lopez"})
    assert rail.compare(q, a, "Yes, Maria paid $250 on October 3.")[0] == "agrees"
    assert rail.compare(q, a, "Maria still owes $250.")[0] == "differs"


def test_empty_answers_agree_only_with_an_empty_reply():
    q, a = _money_answer("Any overdue invoices?", [OPEN[1]])
    assert a.empty
    assert rail.compare(q, a, "Nothing is overdue, you're all caught up.")[0] == "agrees"
    assert rail.compare(q, a, "Maria is $300 overdue.")[0] == "differs"


def test_calendar_replies_are_compared_by_their_times():
    rec = rail.Records(sessions=SESSIONS, label="tomorrow", window="x", day_iso="2026-10-17")
    q, a, _ = _say("What do I have tomorrow?", rec)
    assert rail.compare(q, a, "Two tomorrow: Maria at 10am for a haircut, then Tasha at 12:30 pm.")[0] == "agrees"
    assert rail.compare(q, a, "Just Maria at 10:00 AM.")[0] == "partial"
    assert rail.compare(q, a, "Maria at 10am and Tasha at 3pm.")[0] == "differs"
    assert rail.compare(q, a, "Your calendar is clear tomorrow.")[0] == "silent"


# ─── One practice run, end to end, with the reads faked ──────────────

@pytest.fixture
def reads(monkeypatch):
    seen = []
    data = {"/businesses?": [{"id": BIZ, "owner_id": USER, "availability": {"timezone": "America/Detroit"}}],
            "/contacts?": CONTACTS, "/invoices?": OPEN, "/sessions?": SESSIONS,
            "/practitioner_profiles?": []}

    def fake_get(path):
        seen.append(path)
        for prefix, rows in data.items():
            if path.startswith(prefix):
                if prefix == "/contacts?":
                    import re
                    from urllib.parse import unquote
                    want = unquote(re.search(r"name=ilike\.([^&]*)", path).group(1)).strip("*").split("*")
                    return [c for c in rows if all(w in c["name"].lower() for w in want)]
                return rows
        return None
    monkeypatch.setattr(rail, "_get", fake_get)
    return SimpleNamespace(seen=seen, data=data)


def _job(message, *, reply="", user=USER, verbs=()):
    q, why, shelf = rail.read_question(message)
    return {"q": q, "why": why, "shelf": shelf, "kind": "lookup", "bid": BIZ, "user_id": user,
            "reply": reply, "grounding": "fast", "verbs": list(verbs), "request_id": "turn-1",
            "surface": "desktop", "chief_cost_cents": 11.4, "chief_ms": 6200}


def test_a_practice_run_reads_fresh_and_keeps_one_row(reads):
    row = rail.practice(_job("How much am I owed?", reply="You're owed $1,950.00 in total."), now=NOW)
    assert row["took"] and row["proof"] == "prover" and row["outcome"] == "agrees"
    assert row["shelf"] == "money" and row["form"] == "owed_total"
    assert row["chief_cost_cents"] == 11.4 and row["chief_ms"] == 6200 and isinstance(row["rail_ms"], int)
    assert row["rail_answer"].startswith("You're owed $1,950.00")
    assert "known" not in row["rail_facts"]
    # Every read is scoped to this business.
    assert all(f"eq.{BIZ}" in p or "owner_id=eq." in p for p in reads.seen)


def test_the_rail_reads_nothing_for_someone_who_does_not_own_the_business(reads):
    assert rail.practice(_job("How much am I owed?", user=STRANGER), now=NOW) is None
    assert all(p.startswith("/businesses?") for p in reads.seen)


def test_a_client_is_found_by_first_or_last_name_and_only_when_it_is_one(reads):
    row = rail.practice(_job("Did Maria pay?", reply="Maria owes $450 on INV-0012 and $300 on INV-0013."),
                        now=NOW)
    assert row["took"] and row["outcome"] == "agrees"
    assert any("contact_id=eq.c1" in p for p in reads.seen)
    row = rail.practice(_job("Did Nobodyhere pay?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "name_not_found"
    reads.data["/contacts?"] = CONTACTS + [{"id": "c9", "name": "Maria Ortiz"}]
    row = rail.practice(_job("Did Maria pay?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "name_ambiguous"


def test_a_day_is_read_on_the_business_clock(reads):
    row = rail.practice(_job("What do I have tomorrow?", reply="Maria at 10am and Tasha at 12:30pm."), now=NOW)
    assert row["took"] and row["outcome"] == "agrees"
    day_read = [p for p in reads.seen if p.startswith("/sessions?")][0]
    # Saturday in Detroit starts at 04:00 UTC.
    assert "scheduled_for=gte.2026-10-17T04%3A00%3A00Z" in day_read
    assert "scheduled_for=lt.2026-10-18T04%3A00%3A00Z" in day_read
    # "Friday" on a Friday could mean today or a week away: left to Chief.
    row = rail.practice(_job("What do I have on Friday?"), now=NOW)
    assert row["decline_reason"] == "ambiguous_day"


def test_a_failed_read_is_a_decline_not_an_answer(reads):
    reads.data.pop("/invoices?")
    row = rail.practice(_job("Who owes me?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "read_failed"


def test_a_lookup_off_the_shelves_is_still_counted(reads):
    row = rail.practice(_job("Show me what Maria spent last year"), now=NOW)
    assert row["took"] is False and row["decline_reason"] in ("phrasing", "no_shelf")
    assert [p for p in reads.seen if not p.startswith("/businesses?")] == []


def test_a_turn_that_changed_something_is_marked(reads):
    row = rail.practice(_job("Who owes me?", verbs=["add_reminder"]), now=NOW)
    assert row["chief_wrote"] is True


# ─── When it runs ────────────────────────────────────────────────────

@pytest.fixture
def started(monkeypatch):
    jobs = []

    class Now:
        def __init__(self, target, args, **kw):
            self.target, self.args = target, args

        def start(self):
            jobs.append(self.args[0])
    monkeypatch.setattr(rail.threading, "Thread", Now)
    monkeypatch.setenv("CHIEF_RAIL", "practice")
    return jobs


def _req(message, **kw):
    return SimpleNamespace(message=message, business_id=BIZ, image_ids=[], mode="", client_surface="",
                           request_id="turn-1", **kw)


LOOKUP = SimpleNamespace(kind="lookup")
REC = SimpleNamespace(reason="needs_records", request_id="turn-1", total_ms=5000,
                      tally=SimpleNamespace(cost_cents=lambda: 9.5))


def test_after_a_full_turn_a_shelf_question_is_practised(started):
    rail.after_turn(_req("Did Maria pay?"), USER, LOOKUP, {"response": "Yes.", "actions_taken": []}, rec=REC)
    assert len(started) == 1 and started[0]["q"].form == "did_pay"
    assert started[0]["chief_cost_cents"] == 9.5 and started[0]["chief_ms"] == 5000


@pytest.mark.parametrize("change", [
    {"env": "off"},
    {"payload": None},
    {"req": {"image_ids": ["img"]}},
    {"req": {"mode": "coach"}},
    {"req": {"message": "[SYSTEM: greeting]"}},
    {"rec": SimpleNamespace(reason="checked_availability", request_id="t", total_ms=1, tally=None)},
    {"user": "not-a-uuid"},
])
def test_it_stays_out_of_the_way(started, monkeypatch, change):
    if change.get("env"):
        monkeypatch.setenv("CHIEF_RAIL", change["env"])
    req = _req("Did Maria pay?")
    for k, v in (change.get("req") or {}).items():
        setattr(req, k, v)
    payload = change["payload"] if "payload" in change else {"response": "Yes."}
    rail.after_turn(req, change.get("user", USER), LOOKUP, payload, rec=change.get("rec", REC))
    assert started == []


def test_a_question_that_is_not_about_the_records_is_not_logged(started):
    rail.after_turn(_req("How do I grow my revenue?"), USER, SimpleNamespace(kind="reasoning"),
                    {"response": "Here's a plan."}, rec=REC)
    assert started == []
    rail.after_turn(_req("Show me my best month"), USER, LOOKUP, {"response": "x"}, rec=REC)
    assert len(started) == 1 and started[0]["q"] is None


def test_the_full_turns_finish_calls_the_rail_and_the_fast_lane_does_not(monkeypatch):
    import chief_fast_track as cft
    import chief_of_staff as chief
    import model_router as mr
    import route_ledger
    calls = []
    monkeypatch.setattr(rail, "after_turn", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(route_ledger, "finish", lambda rec: {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    req = chief.ChatRequest(business_id=BIZ, message="Did Maria pay?")
    session = SimpleNamespace(user=SimpleNamespace(id=USER), token="jwt")
    track = cft.plan(req, session)
    track.turn_started = True
    track.finish({"response": "Maria paid.", "actions_taken": []})
    assert len(calls) == 1 and calls[0][3]["response"] == "Maria paid."
    fast = cft.plan(chief.ChatRequest(business_id=BIZ, message="thanks!"), session)
    fast.rec.lane = mr.LANE_FAST
    fast.finish({"response": "Anytime!"})
    assert len(calls) == 1


# ─── The record ──────────────────────────────────────────────────────

def test_summarize_gives_agreement_per_shelf():
    rows = ([{"shelf": "money", "form": "owed_total", "took": True, "proof": "prover", "outcome": "agrees",
              "chief_cost_cents": 12, "rail_ms": 80, "chief_ms": 7000}] * 3
            + [{"shelf": "money", "form": "did_pay", "took": True, "proof": "prover", "outcome": "withheld",
                "chief_cost_cents": 20, "rail_ms": 120, "chief_ms": 9000},
               {"shelf": "money", "form": "did_pay", "took": True, "proof": "failed", "outcome": "differs",
                "chief_cost_cents": 10, "rail_ms": 90, "chief_ms": 6000},
               {"shelf": "schedule", "took": False, "decline_reason": "phrasing"}])
    s = rail.summarize(rows)
    m = s["money"]
    assert (m["asked"], m["took"], m["proved"]) == (5, 5, 4)
    assert m["agreement_pct"] == 75.0                     # 3 agree of 4 compared
    assert m["walls_the_rail_answered"] == 1
    assert m["chief_cost_cents_on_took"] == 66.0
    assert m["rail_ms_p50"] == 80 and m["chief_ms_p95"] == 9000
    assert s["schedule"]["declined"] == {"phrasing": 1}


def test_the_stats_route_is_owner_only():
    from lead_admin import require_owner
    route = next(r for r in rail.router.routes if getattr(r, "path", "") == "/platform/rail/stats")
    assert any(d.call is require_owner for d in route.dependant.dependencies)
