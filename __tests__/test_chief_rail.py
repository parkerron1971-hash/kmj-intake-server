"""The rail's practice mode (chief_rail.py, docs/CHIEF_RAIL.md).

A records question ("Did Maria pay?") is read fresh after Chief has replied,
answered from the rows alone, proved by chief_truth's free prover, and
compared with what Chief said. Nothing here is ever shown to anyone; these
tests pin what it takes, what it says, how it proves it, how strictly it
compares, and that it can't read a business the asker does not own.
"""
from __future__ import annotations

import logging
import pathlib
import re
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chief_rail as rail

TZ = ZoneInfo("America/Detroit")
BIZ = "22222222-2222-2222-2222-222222222222"
USER = "11111111-1111-1111-1111-111111111111"
STRANGER = "33333333-3333-3333-3333-333333333333"
NOW = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)     # Friday, noon in Detroit
TODAY = date(2026, 10, 16)


def _invoice(n, total, status, due, client, cid=None, currency="usd", **kw):
    return {"id": f"i{n}", "invoice_number": f"INV-{n:04d}", "total": total, "status": status,
            "due_date": due, "currency": currency, "contact_id": cid,
            "contacts": {"name": client} if client else None, **kw}


OPEN = [
    _invoice(12, 450, "sent", "2020-01-10", "Maria Lopez", "c1"),
    _invoice(13, 300, "viewed", "2099-10-30", "Maria Lopez", "c1"),
    _invoice(14, 1200, "overdue", "2020-01-05", "Tasha Green", "c2"),
    _invoice(15, 80, "draft", None, "Dee Park", "c4"),
]
PAID = [_invoice(9, 250, "paid", "2026-10-01", "Maria Lopez", "c1", paid_at="2026-10-03T15:00:00+00:00")]
SESSIONS = [
    {"id": "s1", "title": "Haircut", "scheduled_for": "2026-10-17T14:00:00+00:00", "contact_id": "c1",
     "contacts": {"name": "Maria Lopez"}},
    {"id": "s2", "title": "", "scheduled_for": "2026-10-17T16:30:00+00:00", "contact_id": "c2",
     "contacts": {"name": "Tasha Green"}},
]
CONTACTS = [{"id": "c1", "name": "Maria Lopez"}, {"id": "c2", "name": "Tasha Green"},
            {"id": "c3", "name": "Mariah Stone"}]
MARIA = {"id": "c1", "name": "Maria Lopez"}


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


# ─── The switch fails closed ─────────────────────────────────────────

@pytest.mark.parametrize("value, want", [
    (None, "off"), ("", "off"), ("   ", "off"), ("disabled", "off"), ("on", "off"), ("true", "off"),
    ("off", "off"), ("practice", "practice"), (" Practice ", "practice"),
])
def test_only_an_explicit_practice_turns_it_on(monkeypatch, value, want):
    if value is None:
        monkeypatch.delenv("CHIEF_RAIL", raising=False)
    else:
        monkeypatch.setenv("CHIEF_RAIL", value)
    assert rail.mode() == want


# ─── What it says, and the proof ─────────────────────────────────────

def _money_records(rows=OPEN, paid=(), contact=None, today=TODAY, **kw):
    client = (contact or {}).get("name")
    return rail.Records(open_invoices=rail._chief_rows(list(rows), today, client),
                        paid_invoices=[{"number": r["invoice_number"], "client": client or "?",
                                        "total": float(r["total"]), "status": "paid",
                                        "paid_at": r.get("paid_at"), "due_date": r["due_date"]}
                                       for r in paid],
                        contact=contact, today=today, **kw)


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
    rec = _money_records(OPEN[:2], paid=PAID, contact=MARIA)
    _, a, (proof, _) = _say("Did Maria pay?", rec)
    assert a.text.startswith("Maria Lopez owes $450.00 on invoice INV-0012, due Jan 10, ")
    assert "Maria Lopez owes $300.00 on invoice INV-0013, due Oct 30." in a.text
    assert a.text.endswith("Maria Lopez paid invoice INV-0009, $250.00, on Oct 3.")
    assert a.facts["polarity"] == "owes" and proof == "prover"
    _, a, (proof, _) = _say("Did Maria pay?", _money_records([], paid=PAID, contact=MARIA))
    assert a.text == "Maria Lopez paid invoice INV-0009, $250.00, on Oct 3."
    assert a.facts["polarity"] == "paid" and proof == "prover"


def test_a_day_on_the_calendar_is_proved_on_the_business_clock():
    rec = rail.Records(sessions=SESSIONS, label="tomorrow", window="2026-10-17, Saturday",
                       day_iso="2026-10-17", today=TODAY)
    _, a, (proof, _) = _say("What's on my calendar tomorrow?", rec)
    # 14:00 UTC is 10 AM in Detroit; saying the UTC hour would be wrong.
    assert a.text == "You have 2 sessions tomorrow. 10:00 AM: Haircut with Maria Lopez. 12:30 PM: Tasha Green."
    assert proof == "prover" and [c["time"] for c in a.facts["claims"]] == ["10:00", "12:30"]


def test_the_next_session_and_a_clients_next_session():
    rec = rail.Records(sessions=SESSIONS[:1], window="next booked", today=TODAY)
    _, a, (proof, _) = _say("When is my next appointment?", rec)
    assert a.text == "Your next session is Haircut with Maria Lopez on Saturday, Oct 17 at 10:00 AM."
    assert proof == "prover"
    rec = rail.Records(sessions=SESSIONS[:1], contact=MARIA, window="next", today=TODAY)
    _, a, (proof, _) = _say("When is Maria's appointment?", rec)
    assert a.text == "Maria Lopez is booked for Haircut on Saturday, Oct 17 at 10:00 AM." and proof == "prover"


def test_nothing_to_report_is_proved_by_the_whole_read():
    _, a, proof = _say("Who owes me?", _money_records([OPEN[3]]))          # only a draft
    assert a.text == "Nobody owes you right now: there are no sent, unpaid invoices."
    assert proof == ("empty_read", [])
    rec = rail.Records(sessions=[], label="tomorrow", window="x", day_iso="2026-10-17", today=TODAY)
    _, a, proof = _say("What do I have tomorrow?", rec)
    assert a.text == "Nothing is booked tomorrow." and proof == ("empty_read", [])


def test_a_read_that_did_not_return_every_row_proves_nothing():
    rec = rail.Records(sessions=[], label="tomorrow", window="x", day_iso="2026-10-17", complete=False)
    assert _say("What do I have tomorrow?", rec)[2] == ("failed", [])
    rec = _money_records(OPEN[:1], contact=MARIA, complete=False)
    q, a, proof = _say("Did Maria pay?", rec)
    assert proof == ("failed", [])
    assert all(not s["complete"] for s in a.sources.values() if s["kind"] == "context")


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


@pytest.mark.parametrize("now, zone, overdue", [
    # 02:00 UTC on the 16th is still the 15th in Detroit: due the 15th, not late.
    (datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc), "America/Detroit", 0),
    (datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc), "America/Detroit", 1),
    # 16:00 UTC on the 15th is already the 16th in Tokyo: due the 15th, a day late.
    (datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc), "Asia/Tokyo", 1),
    (datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc), "Asia/Tokyo", 0),
])
def test_invoices_are_aged_on_the_business_date_not_utcs(monkeypatch, now, zone, overdue):
    rows = [_invoice(20, 100, "sent", "2026-10-15", "Maria Lopez", "c1")]
    monkeypatch.setattr(rail, "_get", lambda path: rows if path.startswith("/invoices?") else None)
    q, _, _ = rail.read_question("Any overdue invoices?")
    rec = rail.read(q, BIZ, ZoneInfo(zone), now=now)
    assert rec.open_invoices[0]["days_overdue"] == overdue
    answer, _ = rail.compose(q, rec, ZoneInfo(zone))
    assert answer.empty is (overdue == 0)


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
    ("You're owed $1,950 across 99 invoices.", "differs"),             # the right sum, the wrong count
    ("| Client | Owes |\n| Tasha | $1,200 |\n| Maria | $750 |", "unverified"),
])
def test_money_replies_are_compared_claim_by_claim(reply, outcome):
    q, a = _money_answer()
    assert rail.compare(q, a, reply)[0] == outcome


def test_an_amount_said_for_the_wrong_client_differs():
    q, a = _money_answer("Who owes me?")
    right = "You're owed $1,950. Tasha Green owes $1,200 and Maria owes $750."
    swapped = "You're owed $1,950. Maria owes $1,200 and Tasha owes $750."
    assert rail.compare(q, a, right)[0] == "agrees"
    assert rail.compare(q, a, swapped)[0] == "differs"
    # Someone the records don't have, holding a client's amount: not agreement.
    assert rail.compare(q, a, "You're owed $1,950. Jordan owes $1,200.")[0] == "unverified"


def test_amounts_are_read_however_the_sentence_runs_on():
    assert rail.amounts_said("Maria $100, Tasha $1,200, and $50.") == ["100.00", "1200.00", "50.00"]
    assert rail.amounts_said("$1,950.00 in total; $12.5 more") == ["12.50", "1950.00"]


# Codex's re-check of bec9df2: Maria owes $100, Tasha $200.
TWO = [_invoice(51, 100, "sent", "2099-01-01", "Maria Lopez", "c1"),
       _invoice(52, 200, "sent", "2099-01-01", "Tasha Green", "c2")]


def _sweep_replies():
    """Replies built from parts, each with its truth against TWO (Maria
    owes $100, Tasha owes $200, both unpaid; the business is owed $300).
    Yields (reply, true?)."""
    people = [("Maria", "M"), ("MARIA", "M"), ("maria", "M"), ("Maria Lopez", "M"),
              ("Tasha", "T"), ("TASHA GREEN", "T"), ("tasha", "T"), ("Jordan", "?"), ("She", "?")]
    owes = {"M": "100", "T": "200"}
    owed_forms = ["{s} owes ${a}.", "{s} still owes ${a}.", "{s} owes ${a} in total.",
                  "{s} hasn't paid ${a}.", "{s}'s ${a} is still unpaid.", "${a}, {s}'s balance.",
                  "{s} has ${a} outstanding.", "Not yet: {s} owes ${a}."]
    paid_forms = ["{s} paid ${a}.", "{s} has paid ${a}.", "{s} paid ${a} in full.", "{s}'s ${a} is paid.",
                  "{s}'s previously unpaid ${a} has now been paid.", "${a} from {s}, paid in full.",
                  "{s} settled the outstanding ${a}.", "{s} cleared ${a}, nothing is outstanding."]
    negated = ["{s} doesn't owe ${a}.", "{s} no longer owes ${a}."]
    for s, who in people:
        for a in ("100", "200", "300"):
            truth_owed = who in owes and owes[who] == a
            for f in owed_forms:
                yield f.format(s=s, a=a), truth_owed
            for f in paid_forms + negated:
                yield f.format(s=s, a=a), False        # nothing is paid
    business_owed = ["You're owed ${a}.", "You're owed ${a} in total.", "Overall, you're owed ${a}.",
                     "Altogether your clients owe you ${a}.", "In total, ${a} is outstanding."]
    business_paid = ["You've been paid ${a}.", "You have been paid, ${a} across 2 invoices.",
                     "${a}, paid in full.", "You've collected ${a}.", "You've been paid the outstanding ${a}.",
                     "The previously unpaid ${a} has now been paid."]
    for a in ("100", "200", "300"):
        for f in business_owed:
            yield f.format(a=a), a == "300"
        for f in business_paid:
            yield f.format(a=a), False
    # Two clauses: true only when both are.
    for (s1, w1), (s2, w2) in [(("Maria", "M"), ("Tasha", "T")), (("maria", "M"), ("tasha", "T")),
                               (("Tasha", "T"), ("Maria", "M"))]:
        for a1, a2 in (("100", "200"), ("200", "100"), ("100", "100"), ("300", "200")):
            ok = owes[w1] == a1 and owes[w2] == a2
            yield f"{s1} owes ${a1} and {s2} owes ${a2}.", ok
            yield f"{s1} owes ${a1}, {s2} ${a2}.", ok
            yield f"You're owed $300: {s1} owes ${a1} and {s2} owes ${a2}.", ok


def test_no_false_reply_is_ever_scored_as_agreement():
    q, a = _money_answer("How much am I owed?", TWO)
    a.facts["contacts"] = [c["name"] for c in CONTACTS]      # as practice() supplies them
    wrong, true_agreed, true_total = [], 0, 0
    for reply, true in _sweep_replies():
        outcome = rail.compare(q, a, reply)[0]
        if true:
            true_total += 1
            true_agreed += outcome in ("agrees", "partial")
        elif outcome in ("agrees", "partial"):
            wrong.append((reply, outcome))
    assert not wrong, wrong[:20]
    # And it is not simply refusing everything: most true replies still read as true.
    assert true_agreed >= 0.8 * true_total, (true_agreed, true_total)


def _calendar_sweep(one_session: bool):
    """(reply, true?) against SESSIONS (Maria 10:00 AM, Tasha 12:30 PM,
    both Saturday Oct 17, which is tomorrow), or only Maria's."""
    booked = {"M": "10am"} if one_session else {"M": "10am", "T": "12:30pm"}
    people = [("Maria", "M"), ("MARIA", "M"), ("maria", "M"), ("Tasha", "T"), ("tasha", "T"),
              ("Jordan", "?"), ("She", "M" if one_session else "?")]
    days = [("", True), (" tomorrow", True), (" on Saturday", True), (" on Oct 17", True),
            (" on Sunday", False), (" on Oct 18", False)]
    forms = ["{s} is at {t}{d}.", "{s} at {t}{d}.", "{t}{d}: {s}.", "{s}, {t}{d}.", "{t}{d} with {s}.",
             "{s} is booked for {t}{d}.", "Next up{d}, {s} at {t}."]
    for s, who in people:
        for t in ("10am", "12:30pm", "3pm"):
            for d, day_ok in days:
                for f in forms:
                    yield f.format(s=s, t=t, d=d), (booked.get(who) == t and day_ok)


@pytest.mark.parametrize("one_session", [False, True])
def test_no_false_calendar_reply_is_ever_scored_as_agreement(one_session):
    if one_session:
        rec = rail.Records(sessions=SESSIONS[:1], window="next booked", today=TODAY)
        q, a, _ = _say("When is my next appointment?", rec)
    else:
        q, a = _day_answer()
    a.facts["contacts"] = [c["name"] for c in CONTACTS]      # as practice() supplies them
    wrong, true_agreed, true_total = [], 0, 0
    for reply, true in _calendar_sweep(one_session):
        outcome = rail.compare(q, a, reply)[0]
        if true:
            true_total += 1
            true_agreed += outcome in ("agrees", "partial")
        elif outcome in ("agrees", "partial"):
            wrong.append((reply, outcome))
    assert not wrong, wrong[:20]
    assert true_agreed >= 0.8 * true_total, (true_agreed, true_total)


@pytest.mark.parametrize("reply, outcome", [
    # The business's $300 is not Maria's.
    ("Maria owes $300 across 2 invoices.", "differs"),
    # Both invoices are unpaid; nothing was paid.
    ("You have been paid $300 across 2 invoices.", "differs"),
    ("Maria paid $100.", "differs"),
    # A swapped pair in lower case is still swapped.
    ("maria owes $200 and tasha owes $100.", "differs"),
    # Said right, a total said as a total, and names in lower case, agree.
    ("You're owed $300 in total: Maria owes $100 and Tasha owes $200.", "agrees"),
    ("You're owed $300. maria owes $100, tasha owes $200.", "agrees"),
    ("Neither has paid yet: you're owed $300, Maria $100 and Tasha $200.", "agrees"),
    # Codex's focused re-check of 1fdc2ed.
    # "in total" next to Maria: hers, or everyone's? Unresolved, not agreement.
    ("Maria owes $300 in total.", "unverified"),
    # Paid and owed in one breath: unresolved.
    ("You've been paid the outstanding $300.", "unverified"),
    # A comma doesn't free the $300 from "paid".
    ("You have been paid, $300 across 2 invoices.", "differs"),
    # Paid and owed in their own clauses still read right.
    ("Nothing has been paid yet, you're owed $300: Maria $100 and Tasha $200.", "agrees"),
    # Nothing contradicted, but "who owes me?" wants each client too.
    ("Nobody has paid, so you're owed $300 in total.", "partial"),
])
def test_a_figure_is_held_to_its_client_and_to_whether_it_was_paid(reply, outcome):
    q, a = _money_answer("Who owes me?", TWO)
    assert rail.compare(q, a, reply)[0] == outcome, rail.compare(q, a, reply)


def test_did_pay_compares_the_yes_or_no_and_every_open_invoice():
    q, a = _money_answer("Did Maria pay?", [], paid=PAID, contact=MARIA)
    assert rail.compare(q, a, "Yes, Maria paid $250 on October 3.")[0] == "agrees"
    assert rail.compare(q, a, "Maria still owes $250.")[0] == "differs"
    q, a = _money_answer("Did Maria pay?", OPEN[:2], paid=PAID, contact=MARIA)
    assert rail.compare(q, a, "Not yet: Maria owes $450 and $300.")[0] == "agrees"
    assert rail.compare(q, a, "Not yet, she owes $750 across 2 invoices.")[0] == "agrees"
    # One of her two open invoices left out.
    assert rail.compare(q, a, "Not yet, Maria still owes $450.")[0] == "partial"


def test_empty_answers_agree_only_with_an_empty_reply():
    q, a = _money_answer("Any overdue invoices?", [OPEN[1]])
    assert a.empty
    assert rail.compare(q, a, "Nothing is overdue, you're all caught up.")[0] == "agrees"
    assert rail.compare(q, a, "Maria is $300 overdue.")[0] == "differs"


def _day_answer(sessions=SESSIONS, form="What do I have tomorrow?"):
    rec = rail.Records(sessions=sessions, label="tomorrow", window="x", day_iso="2026-10-17", today=TODAY)
    q, a, _ = _say(form, rec)
    return q, a


def test_calendar_replies_are_compared_by_time_client_and_day():
    q, a = _day_answer()
    assert rail.compare(q, a, "Two tomorrow: Maria at 10am for a haircut, then Tasha at 12:30 pm.")[0] == "agrees"
    assert rail.compare(q, a, "Just Maria at 10:00 AM.")[0] == "partial"
    assert rail.compare(q, a, "Maria at 10am and Tasha at 3pm.")[0] == "differs"
    assert rail.compare(q, a, "Tasha at 10am and Maria at 12:30pm.")[0] == "differs"      # swapped
    assert rail.compare(q, a, "You have 3 appointments tomorrow: Maria at 10am, Tasha at 12:30pm.")[0] == "differs"
    assert rail.compare(q, a, "Your calendar is clear tomorrow.")[0] == "silent"


def test_the_next_session_is_held_to_its_client_and_day():
    rec = rail.Records(sessions=SESSIONS[:1], window="next booked", today=TODAY)
    q, a, _ = _say("When is my next appointment?", rec)
    assert rail.compare(q, a, "Your next one is Maria, Saturday, Oct 17 at 10am.")[0] == "agrees"
    assert rail.compare(q, a, "Tasha is next on Sunday, Oct 18 at 10am.")[0] == "differs"
    assert rail.compare(q, a, "Maria is next on Sunday at 10am.")[0] == "differs"            # wrong day
    assert rail.compare(q, a, "Maria tomorrow at 10am.")[0] == "agrees"


# ─── One practice run, end to end, with the reads faked ──────────────

def _filtered(rows, path):
    """A tiny PostgREST: contact_id=eq., status=eq./in.(…)/neq., limit."""
    out = list(rows)
    m = re.search(r"contact_id=eq\.([^&]+)", path)
    if m:
        out = [r for r in out if r.get("contact_id") == m.group(1)]
    m = re.search(r"status=in\.\(([^)]*)\)", path)
    if m:
        out = [r for r in out if r.get("status") in m.group(1).split(",")]
    m = re.search(r"status=eq\.([^&]+)", path)
    if m and "/sessions?" not in path:
        out = [r for r in out if r.get("status") == m.group(1)]
    m = re.search(r"limit=(\d+)", path)
    return out[:int(m.group(1))] if m else out


@pytest.fixture
def reads(monkeypatch):
    seen = []
    data = {"/businesses?": [{"id": BIZ, "owner_id": USER, "availability": {"timezone": "America/Detroit"}}],
            "/contacts?": CONTACTS, "/invoices?": OPEN + PAID, "/sessions?": SESSIONS,
            "/practitioner_profiles?": []}

    def fake_get(path):
        seen.append(path)
        for prefix, rows in data.items():
            if path.startswith(prefix):
                if prefix == "/contacts?":
                    offset = int(re.search(r"offset=(\d+)", path).group(1))
                    limit = int(re.search(r"limit=(\d+)", path).group(1))
                    return rows[offset:offset + limit]
                if prefix == "/invoices?":
                    return _filtered(rows, path)
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
    assert set(row["rail_facts"]) == {"headline", "count", "polarity"}
    assert all(f"eq.{BIZ}" in p or "owner_id=eq." in p for p in reads.seen)


def test_the_rail_reads_nothing_for_someone_who_does_not_own_the_business(reads):
    assert rail.practice(_job("How much am I owed?", user=STRANGER), now=NOW) is None
    assert rail.practice(_job("Show me what Maria spent last year", user=STRANGER), now=NOW) is None
    assert all(p.startswith("/businesses?") for p in reads.seen)


def test_a_client_is_found_by_first_or_last_name_and_only_when_it_is_one(reads):
    row = rail.practice(_job("Did Maria pay?", reply="Not yet: Maria owes $450 on INV-0012 and $300 on INV-0013."),
                        now=NOW)
    assert row["took"] and row["outcome"] == "agrees", row
    open_read = [p for p in reads.seen if p.startswith("/invoices?") and "status=in." in p][0]
    assert "contact_id=eq.c1" in open_read and "status=in.(sent,viewed,overdue)" in open_read
    assert any("status=eq.paid" in p and "limit=1" in p for p in reads.seen)
    row = rail.practice(_job("Did Nobodyhere pay?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "name_not_found"
    reads.data["/contacts?"] = CONTACTS + [{"id": "c9", "name": "Maria Ortiz"}]
    row = rail.practice(_job("Did Maria pay?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "name_ambiguous"
    # The typed name never leaves the process: no read carries it.
    assert not any("maria" in unquote(p).lower() for p in reads.seen)


def test_a_name_search_past_five_thousand_contacts_is_chiefs(reads):
    reads.data["/contacts?"] = [{"id": f"x{n}", "name": f"Person {n}"} for n in range(5000)]
    row = rail.practice(_job("Did Maria pay?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "too_many_contacts"
    reads.data["/contacts?"] = [{"id": f"x{n}", "name": f"Person {n}"} for n in range(2500)] + CONTACTS
    row = rail.practice(_job("Did Maria pay?", reply="Not yet: Maria owes $450 and $300."), now=NOW)
    assert row["took"] and row["outcome"] == "agrees"


def test_a_long_paid_history_cannot_hide_an_older_unpaid_invoice(reads):
    history = [_invoice(100 + n, 10, "paid", "2025-01-01", "Maria Lopez", "c1",
                        paid_at=f"2025-{1 + n % 12:02d}-02T12:00:00+00:00") for n in range(60)]
    reads.data["/invoices?"] = history + [_invoice(5, 999, "overdue", "2024-01-01", "Maria Lopez", "c1")]
    row = rail.practice(_job("Did Maria pay?"), now=NOW)
    assert row["took"] and "$999.00" in row["rail_answer"] and row["rail_facts"]["polarity"] == "owes"


def test_too_many_open_invoices_for_one_client_is_left_to_chief(reads):
    reads.data["/invoices?"] = [_invoice(n, 10, "sent", "2099-01-01", "Maria Lopez", "c1") for n in range(5)]
    row = rail.practice(_job("How much does Maria owe me?"), now=NOW)
    assert not row["took"] and row["decline_reason"] == "too_long"


@pytest.mark.parametrize("currencies", [["eur"], ["usd", "eur"], ["GBP"]])
def test_anything_but_dollars_is_left_to_chief(reads, currencies):
    reads.data["/invoices?"] = [_invoice(30 + i, 100, "sent", "2099-01-01", "Maria Lopez", "c1", currency=c)
                                for i, c in enumerate(currencies)]
    for message in ("How much am I owed?", "Did Maria pay?"):
        row = rail.practice(_job(message), now=NOW)
        assert not row["took"] and row["decline_reason"] == "currency"


def test_dollars_in_any_case_and_a_missing_currency_are_dollars(reads):
    reads.data["/invoices?"] = [_invoice(40, 100, "sent", "2099-01-01", "Maria Lopez", "c1", currency="USD"),
                                _invoice(41, 50, "sent", "2099-01-01", "Maria Lopez", "c1", currency=None)]
    row = rail.practice(_job("How much am I owed?"), now=NOW)
    assert row["took"] and row["rail_answer"].startswith("You're owed $150.00")


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


# ─── Nothing personal reaches the logs ───────────────────────────────

SECRETS = ("reviewperson", "privacysentinel", "4,321", "4321")


def _real_http(monkeypatch, handler):
    """The REAL httpx.Client (its own request logging included) on an
    in-memory transport: nothing leaves the machine."""
    import httpx
    import sb_clients
    real = httpx.Client
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(sb_clients.httpx, "Client",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    rail._skip_db_until = 0.0


@pytest.mark.parametrize("status", [200, 500])
def test_no_name_or_amount_reaches_any_log_with_the_real_http_client(monkeypatch, caplog, status):
    import httpx
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if status == 500:
            return httpx.Response(500, text="failing row contains (Reviewperson Privacysentinel, $4,321.00)")
        if request.url.path.endswith("/contacts"):
            return httpx.Response(200, json=[{"id": "c7", "name": "Reviewperson Privacysentinel"}])
        return httpx.Response(201, json=[{"id": "r1"}])
    _real_http(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):          # HTTPX logs each request URL at INFO
        found = rail._contact(BIZ, "reviewperson privacysentinel")
        rail._write({"rail_answer": "Reviewperson Privacysentinel owes $4,321.00.", "business_id": BIZ})
    assert found == ((None, "read_failed") if status == 500
                     else ({"id": "c7", "name": "Reviewperson Privacysentinel"}, ""))
    assert "HTTP Request" in caplog.text            # the transport's own logger was listened to
    assert urls and not any(s in unquote(u).lower() for u in urls for s in SECRETS)
    for secret in SECRETS:
        assert secret not in caplog.text.lower()


def test_a_transport_failure_logs_the_shape_not_the_values(monkeypatch, caplog):
    import httpx

    def handler(request):
        raise httpx.ConnectError(f"boom at {request.url}")
    _real_http(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):
        assert rail._get(f"/invoices?business_id=eq.{BIZ}&contact_id=eq.c1&select=id") is None
    assert "/invoices?business_id=eq.…&contact_id=eq.…&select=id transport error: ConnectError" in caplog.text


def test_redacted_paths_keep_the_shape_and_hide_the_values():
    import sb_clients
    assert (sb_clients.redacted_path("/contacts?business_id=eq.abc&name=ilike.*maria*&select=id,name&limit=25")
            == "/contacts?business_id=eq.…&name=ilike.…&select=id,name&limit=25")
    assert sb_clients.redacted_path("/chief_rail_practice") == "/chief_rail_practice"


# ─── Rows go with their business, and age out ────────────────────────

def test_the_table_cascades_with_its_business_and_is_not_exported():
    import account_lifecycle as al
    sql = (ROOT / "supabase" / "APPLY-2026-10-16-chief-rail-practice.sql").read_text(encoding="utf-8")
    assert re.search(r"foreign key \(business_id\) references public\.businesses\(id\) on delete cascade", sql)
    assert "chief_rail_practice" in al.EXPORT_EXCLUDED and "cascade" in al.EXPORT_EXCLUDED["chief_rail_practice"]
    assert "chief_rail_practice" not in al.BUSINESS_CHILD_TABLES


def test_old_practice_rows_are_pruned_daily_behind_the_scheduler_gate(monkeypatch):
    import sb_clients
    deleted = []
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path: deleted.append(path) or True)
    assert rail.prune_tick() == 1
    assert deleted[0].startswith("/chief_rail_practice?created_at=lt.")
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("rail_practice_retention", _rail.prune_tick)' in src


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
    {"env": ""},
    {"env": "on"},
    {"payload": None},
    {"req": {"image_ids": ["img"]}},
    {"req": {"mode": "coach"}},
    {"req": {"message": "[SYSTEM: greeting]"}},
    {"rec": SimpleNamespace(reason="checked_availability", request_id="t", total_ms=1, tally=None)},
    {"user": "not-a-uuid"},
])
def test_it_stays_out_of_the_way(started, monkeypatch, change):
    if "env" in change:
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

def test_agreement_counts_proved_answers_only_per_shelf_and_form():
    rows = ([{"shelf": "money", "form": "owed_total", "took": True, "proof": "prover", "outcome": "agrees",
              "chief_cost_cents": 12, "rail_ms": 80, "chief_ms": 7000}] * 3
            + [{"shelf": "money", "form": "did_pay", "took": True, "proof": "prover", "outcome": "withheld",
                "chief_cost_cents": 20, "rail_ms": 120, "chief_ms": 9000},
               {"shelf": "money", "form": "did_pay", "took": True, "proof": "prover", "outcome": "unverified",
                "chief_cost_cents": 10, "rail_ms": 90, "chief_ms": 6000},
               # A refused proof agreeing with Chief is no evidence at all.
               {"shelf": "money", "form": "did_pay", "took": True, "proof": "failed", "outcome": "agrees",
                "chief_cost_cents": 10, "rail_ms": 90, "chief_ms": 6000},
               {"shelf": "schedule", "took": False, "decline_reason": "phrasing"}])
    s = rail.summarize(rows)
    m = s["money"]
    assert (m["asked"], m["took"], m["proved"], m["proof_failed"]) == (6, 6, 5, 1)
    assert m["outcomes"] == {"agrees": 3, "withheld": 1, "unverified": 1}
    assert m["agreement_pct"] == 75.0                     # 3 agree of 4 compared, the failed proof left out
    assert m["forms"]["did_pay"] == {"took": 3, "proved": 2, "proof_failed": 1,
                                     "outcomes": {"withheld": 1, "unverified": 1}, "agreement_pct": 0.0}
    assert m["forms"]["owed_total"]["agreement_pct"] == 100.0
    assert m["walls_the_rail_answered"] == 1
    assert m["chief_cost_cents_on_took"] == 76.0
    assert m["rail_ms_p50"] == 80 and m["chief_ms_p95"] == 9000
    assert s["schedule"]["declined"] == {"phrasing": 1}


def test_the_stats_route_is_owner_only():
    from lead_admin import require_owner
    route = next(r for r in rail.router.routes if getattr(r, "path", "") == "/platform/rail/stats")
    assert any(d.call is require_owner for d in route.dependant.dependencies)
