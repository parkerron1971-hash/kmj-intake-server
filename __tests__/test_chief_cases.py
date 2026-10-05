"""
test_chief_cases.py — the open-problem record (Solutionist Intelligence).

What must hold:
  1. A FORECAST IS VALIDATED AT OPENING. Unknown kinds, weekdays on a
     non-session measure, a window in the past, a window too short or too
     far out, a forecast of zero — refused before a row exists.
  2. THE NUMBER BEFORE IS REAL. It is read from the records over the same
     length of time just before the window, and a forecast that does not
     beat it is refused. A failed read opens nothing (never a zero).
  3. WEEKDAYS COUNT IN THE BUSINESS'S DAY. Cancelled and no-show sessions
     do not count.
  4. THE CHECK IS A READ AND IT IS HONEST. met / partly / not_met; a read
     that keeps failing becomes "unmeasured", never a number. The owner is
     told once, as what the records show.
  5. CHIEF SEES ITS CASES, AND THE ANSWER CHECK SEES THEM TOO, so a true
     report of a result is never withheld as unsupported.
  6. THE VERBS ARE CLASS A, REGISTERED AND DOCUMENTED; the app's door is
     owner-only.
House rules: sync tests + asyncio.run (no pytest-asyncio in CI).
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_assignments as ca
import chief_cases as cc
import sb_clients

BIZ = {"id": "11111111-1111-1111-1111-111111111111", "name": "Bloom Studio",
       "type": "salon", "owner_id": "own-1"}
NOW = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)   # a Monday
TODAY = NOW.date()


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(cc, "_now", lambda: NOW)
    monkeypatch.setattr(ca, "_now", lambda: NOW)
    monkeypatch.setattr(ca, "_tz_for", lambda bid: timezone.utc)


class FakeDB:
    """Routes sb_clients calls by path. sessions/contacts/invoices are
    lists of rows; posts and patches are recorded."""

    def __init__(self, sessions=None, cases=None, fail_reads=False):
        self.sessions = sessions or []
        self.cases = cases or []
        self.fail_reads = fail_reads
        self.posts, self.patches = [], []

    def get(self, path):
        if self.fail_reads and path.startswith("/sessions"):
            return None
        if path.startswith("/sessions"):
            lo = path.split("scheduled_for=gte.")[1].split("&")[0]
            hi = path.split("scheduled_for=lte.")[1].split("&")[0]
            return [s for s in self.sessions if lo <= s["scheduled_for"] <= hi]
        if path.startswith("/chief_cases"):
            if "status=eq.open" in path:
                return [c for c in self.cases if c.get("status") == "open"]
            return list(self.cases)
        if path.startswith("/businesses"):
            return [{"id": BIZ["id"], "owner_id": "own-1"}]
        return []

    def post(self, path, body, prefer="return=representation"):
        self.posts.append((path, body))
        if path == "/chief_cases":
            row = {"id": "case-new", "created_at": NOW.isoformat(), **body}
            self.cases.append(row)
            return [row]
        return None

    def patch(self, path, body):
        self.patches.append((path, body))
        return [{"id": path.split("id=eq.")[-1]}]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    return fake


def _s(day: str, status: str = "scheduled", hour: int = 15):
    return {"scheduled_for": f"{day}T{hour:02d}:00:00Z", "status": status}


# ─── 1. the forecast is validated at opening ──────────────────────────

def test_a_forecast_is_validated_at_opening():
    utc = timezone.utc
    err, plan = cc.normalize({"kind": "sessions_scheduled", "weekdays": ["Tue", "wednesday"]}, 9,
                             tz=utc, today=TODAY)
    assert err is None
    assert plan["measure"] == {"kind": "sessions_scheduled", "weekdays": [1, 2]}
    # Default window: the next three weeks; the number before is the same
    # length just before it; the check is the day after.
    assert plan["window"] == (date(2026, 10, 5), date(2026, 10, 25))
    assert plan["before"] == (date(2026, 9, 14), date(2026, 10, 4))
    assert plan["check_on"] == date(2026, 10, 26)

    assert "kind" in cc.normalize({"kind": "bookings"}, 3, tz=utc, today=TODAY)[0]
    assert "weekdays only apply" in cc.normalize(
        {"kind": "new_contacts", "weekdays": ["monday"]}, 3, tz=utc, today=TODAY)[0]
    assert "day names" in cc.normalize(
        {"kind": "sessions_scheduled", "weekdays": ["someday"]}, 3, tz=utc, today=TODAY)[0]
    assert "AFTER the fix" in cc.normalize(
        {"kind": "new_contacts", "from": "2026-09-01", "to": "2026-09-30"}, 3, tz=utc, today=TODAY)[0]
    assert "at least" in cc.normalize(
        {"kind": "new_contacts", "from": "2026-10-05", "to": "2026-10-06"}, 3, tz=utc, today=TODAY)[0]
    assert "too far" in cc.normalize(
        {"kind": "new_contacts", "from": "2026-10-05", "to": "2027-03-01"}, 3, tz=utc, today=TODAY)[0]
    assert "above zero" in cc.normalize({"kind": "new_contacts"}, 0, tz=utc, today=TODAY)[0]
    assert "whole number" in cc.normalize({"kind": "new_contacts"}, 2.5, tz=utc, today=TODAY)[0]
    err, plan = cc.normalize({"kind": "revenue_collected"}, 1200.456, tz=utc, today=TODAY)
    assert err is None and plan["expected"] == 1200.46


def test_an_invoice_case_needs_a_real_id_and_defaults_to_two_weeks():
    utc = timezone.utc
    assert "invoice's id" in cc.normalize({"kind": "invoice_paid"}, 1, tz=utc, today=TODAY)[0]
    err, plan = cc.normalize({"kind": "invoice_paid", "invoice_id": "22222222-2222-2222-2222-222222222222"},
                             None, tz=utc, today=TODAY)
    assert err is None and plan["expected"] == 1
    assert plan["check_on"] == date(2026, 10, 19)


# ─── 2/3. the number before is real; weekdays in the business's day ───

def test_weekdays_count_in_the_business_day_and_skip_cancellations(db):
    db.sessions = [
        _s("2026-09-15"),                       # Tuesday
        _s("2026-09-16"),                       # Wednesday
        _s("2026-09-16", status="cancelled"),   # does not count
        _s("2026-09-17"),                       # Thursday: not asked
        _s("2026-09-22", status="no_show"),     # does not count
        _s("2026-09-29"),                       # Tuesday
    ]
    m = {"kind": "sessions_scheduled", "weekdays": [1, 2]}
    assert cc.measure_value(BIZ["id"], m, date(2026, 9, 14), date(2026, 10, 4), tz=timezone.utc) == 3


def test_opening_reads_the_number_before_and_saves_the_forecast(db):
    db.sessions = [_s("2026-09-15"), _s("2026-09-16"), _s("2026-09-22"), _s("2026-09-30")]
    err, row = cc.open_case(BIZ, symptom="Tuesdays and Wednesdays are dead",
                            cause="no weekly hours set, so the booking page shows open around the clock",
                            fix="set real hours and text the regulars a midweek slot",
                            evidence="availability settings: no hours",
                            measure={"kind": "sessions_scheduled", "weekdays": ["tuesday", "wednesday"]},
                            expected=9)
    assert err is None
    assert row["baseline"]["value"] == 4
    assert row["baseline"]["from"] == "2026-09-14" and row["baseline"]["to"] == "2026-10-04"
    assert row["expected"] == 9 and row["check_on"] == "2026-10-26"
    pub = cc.public_row(row)
    assert pub["before"].startswith("4 bookings on Tuesdays and Wednesdays")
    assert pub["forecast"].startswith("9 bookings on Tuesdays and Wednesdays")


def test_a_forecast_that_does_not_beat_the_number_before_is_refused(db):
    db.sessions = [_s("2026-09-15"), _s("2026-09-16"), _s("2026-09-22")]
    err, row = cc.open_case(BIZ, symptom="slow midweek", cause="c", fix="f", evidence="",
                            measure={"kind": "sessions_scheduled", "weekdays": [1, 2]}, expected=3)
    assert row == {} and "beat the number before" in err
    assert not [p for p in db.posts if p[0] == "/chief_cases"]


def test_a_failed_read_opens_nothing_and_never_becomes_zero(db):
    db.fail_reads = True
    err, row = cc.open_case(BIZ, symptom="slow midweek", cause="c", fix="f", evidence="",
                            measure={"kind": "sessions_scheduled", "weekdays": [1]}, expected=5)
    assert row == {} and "could not read the number before" in err
    assert not db.posts


def test_one_case_per_problem_and_a_cap(db):
    db.cases = [{"id": "c-1", "status": "open", "symptom": "Slow midweek"}]
    err, _ = cc.open_case(BIZ, symptom="slow midweek", cause="c", fix="f", evidence="",
                          measure={"kind": "new_contacts"}, expected=5)
    assert "already has an open case" in err
    db.cases = [{"id": f"c-{i}", "status": "open", "symptom": f"p{i}"} for i in range(cc.MAX_OPEN)]
    err, _ = cc.open_case(BIZ, symptom="new one", cause="c", fix="f", evidence="",
                          measure={"kind": "new_contacts"}, expected=5)
    assert "close one first" in err


def test_a_case_needs_the_problem_the_cause_and_the_fix(db):
    err, _ = cc.open_case(BIZ, symptom="slow", cause="", fix="f", evidence="",
                          measure={"kind": "new_contacts"}, expected=5)
    assert "the cause you found" in err


# ─── 4. the check is a read, and it is honest ─────────────────────────

def test_the_verdict_is_honest():
    assert cc.verdict(9, 4, 9) == "met"
    assert cc.verdict(9, 4, 12) == "met"
    assert cc.verdict(9, 4, 6) == "partly"
    assert cc.verdict(9, 4, 4) == "not_met"
    assert cc.verdict(9, 4, 2) == "not_met"
    assert cc.verdict(9, 4, None) == "unmeasured"


def _due_row():
    return {"id": "case-1", "business_id": BIZ["id"], "status": "open",
            "symptom": "Tuesdays and Wednesdays are dead", "cause": "no hours", "fix": "hours + texts",
            "measure": {"kind": "sessions_scheduled", "weekdays": [1, 2]},
            "baseline": {"value": 4, "from": "2026-09-14", "to": "2026-10-04",
                         "window_from": "2026-09-14", "window_to": "2026-10-04"},
            "expected": 9, "check_on": "2026-10-05", "attempts": 0}


def test_the_check_records_what_the_records_show_and_tells_the_owner_once(db):
    db.sessions = [_s("2026-09-15"), _s("2026-09-16"), _s("2026-09-22"),
                   _s("2026-09-23"), _s("2026-09-29"), _s("2026-09-30")]
    out = _run(cc.check_one(_due_row()))
    assert out["verdict"] == "partly" and out["value"] == 6
    saved = [b for p, b in db.patches if "case-1" in p][0]
    assert saved["status"] == "checked" and saved["verdict"] == "partly"
    assert saved["result"]["value"] == 6
    notes = [b for p, b in db.posts if p == "/chief_notifications"]
    assert len(notes) == 1
    assert notes[0]["title"].startswith("Fix helped, short of the forecast")
    assert "Before: 4 bookings" in notes[0]["body"] and "The records show 6 bookings" in notes[0]["body"]
    # Observed, never credited.
    assert "because" not in notes[0]["body"].lower() and "caused" not in notes[0]["body"].lower()


def test_a_check_that_cannot_read_retries_then_says_unmeasured(db):
    db.fail_reads = True
    row = _due_row()
    out = _run(cc.check_one(row))
    assert out["verdict"] is None
    assert db.patches[-1][1]["attempts"] == 1
    assert not [p for p in db.posts if p[0] == "/chief_notifications"]
    row["attempts"] = cc.MAX_ATTEMPTS - 1
    out = _run(cc.check_one(row))
    assert out["verdict"] == "unmeasured"
    saved = db.patches[-1][1]
    assert saved["status"] == "checked" and saved["result"]["value"] is None
    assert [b for p, b in db.posts if p == "/chief_notifications"][0]["title"].startswith("Couldn't check")


def test_the_tick_is_off_with_its_switch(monkeypatch, db):
    monkeypatch.setenv("CHIEF_CASES", "off")
    called = []
    monkeypatch.setattr(cc, "due_rows", lambda *a, **k: called.append(1) or [])
    _run(cc.cases_tick())
    assert not called


# ─── 5. Chief and the answer check both see the cases ─────────────────

def test_context_lines_carry_the_forecast_and_owed_results():
    open_row = cc.public_row({**_due_row(), "check_on": "2026-10-26",
                              "baseline": {**_due_row()["baseline"], "window_from": "2026-10-05",
                                           "window_to": "2026-10-25"}})
    checked = cc.public_row({**_due_row(), "status": "checked", "verdict": "met",
                             "checked_at": "2026-10-26T06:00:00Z", "result": {"value": 10}})
    lines = cc.context_lines([open_row, checked])
    assert "Forecast: 9 bookings on Tuesdays and Wednesdays" in lines[0]
    assert "Checking on 2026-10-26" in lines[0]
    assert "RESULT" in lines[1] and "verdict met" in lines[1]
    assert "the records show 10 bookings" in lines[1]


def test_the_answer_check_treats_cases_as_records():
    import chief_truth
    src = pathlib.Path(chief_truth.__file__).read_text(encoding="utf-8")
    assert "'open_cases'" in src
    assert "'context:open_cases'" in chief_truth._FAST_CONTEXT or "context:open_cases" in chief_truth._FAST_CONTEXT


# ─── 6. registered, documented, owner-only ────────────────────────────

def test_the_verbs_are_class_a_registered_and_documented():
    import action_registry
    import chief_of_staff as cos
    from __tests__._chief_source import chief_source
    for verb in ("open_case", "close_case"):
        assert verb in cos.ACTION_HANDLERS
        assert action_registry.REGISTRY[verb]["reversibility"] == "A"
    src = chief_source()
    assert '"type":"open_case"' in src and '"type":"close_case"' in src
    assert "OPEN CASES" in src


def test_the_app_door_is_owner_only(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [{"id": BIZ["id"], "owner_id": "someone-else"}])

    class U:
        id = "own-1"
    with pytest.raises(HTTPException) as e:
        cc.list_cases(BIZ["id"], U())
    assert e.value.status_code == 403
