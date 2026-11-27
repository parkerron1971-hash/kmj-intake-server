"""Payroll, the free version: the deposit calendar's dates (payroll_calendar.py).

Every rule the calendar encodes, against dates checked by hand on a calendar:
bank holidays (Federal Reserve), IRS legal holidays (District of Columbia,
Publication 15), the monthly and semiweekly deposit rules, Form 941 and the
January forms, weekend and holiday rolls, approve-by days, projections, and
the month view's shape. Every name and figure is made up.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import payroll_calendar as pcal
from payroll_free_fake import (CHURCH, PayrollFake, install, people, run, seed, standard_lines)

D = date


# ─── Holidays ─────────────────────────────────────────────────────────

def test_the_federal_reserve_holidays_of_2026():
    h = pcal.bank_holidays(2026)
    assert h == {
        D(2026, 1, 1): "New Year’s Day", D(2026, 1, 19): "Martin Luther King Jr. Day",
        D(2026, 2, 16): "Washington’s Birthday", D(2026, 5, 25): "Memorial Day", D(2026, 6, 19): "Juneteenth",
        D(2026, 7, 4): "Independence Day",          # a Saturday: the Reserve Banks open Friday July 3
        D(2026, 9, 7): "Labor Day", D(2026, 10, 12): "Columbus Day", D(2026, 11, 11): "Veterans Day",
        D(2026, 11, 26): "Thanksgiving", D(2026, 12, 25): "Christmas"}
    assert pcal.is_bank_day(D(2026, 7, 3))      # Friday before a Saturday holiday: banks open


def test_a_sunday_holiday_closes_the_banks_on_monday():
    h = pcal.bank_holidays(2027)
    assert h[D(2027, 7, 5)] == "Independence Day (observed)"      # July 4, 2027 is a Sunday
    assert D(2027, 7, 4) not in h
    assert h[D(2027, 6, 19)] == "Juneteenth"                      # a Saturday: no Friday closing
    assert pcal.is_bank_day(D(2027, 6, 18))


def test_irs_legal_holidays_follow_the_district_of_columbia():
    h = pcal.irs_holidays(2026)
    assert h[D(2026, 4, 16)] == "DC Emancipation Day"
    assert h[D(2026, 7, 3)] == "Independence Day"                 # Saturday holiday, observed Friday
    assert not pcal.is_irs_day(D(2026, 7, 3)) and pcal.is_bank_day(D(2026, 7, 3))
    # A Saturday New Year's Day is a legal holiday on December 31 of the year before.
    assert pcal.irs_holidays(2027)[D(2027, 12, 31)] == "New Year’s Day"
    assert pcal.irs_holidays(2027)[D(2027, 12, 24)] == "Christmas"
    # Inauguration Day: January 20, 2029 is a Saturday (no Friday); 2033's is a Thursday.
    assert D(2029, 1, 19) not in pcal.irs_holidays(2029)
    assert pcal.irs_holidays(2033)[D(2033, 1, 20)] == "Inauguration Day"


# ─── Rolls ────────────────────────────────────────────────────────────

def test_january_31_2027_is_a_sunday_so_the_year_end_forms_are_due_february_1():
    assert D(2027, 1, 31).weekday() == 6
    assert pcal.year_end_due(2026) == D(2027, 2, 1)
    assert pcal.form_941_due(2026, 4) == D(2027, 2, 1)
    assert pcal.rolled_words(D(2027, 1, 31), D(2027, 2, 1), "they’re") == \
        "January 31 is a Sunday, so they’re due Monday, Feb 1."


def test_form_941_is_due_the_last_day_of_the_month_after_each_quarter():
    assert pcal.form_941_due(2026, 1) == D(2026, 4, 30)
    assert pcal.form_941_due(2026, 2) == D(2026, 7, 31)
    assert pcal.form_941_raw(2026, 3) == D(2026, 10, 31)          # a Saturday ...
    assert pcal.form_941_due(2026, 3) == D(2026, 11, 2)           # ... so Monday
    assert pcal.year_end_due(2027) == D(2028, 1, 31)


def test_a_monthly_depositor_deposits_by_the_15th_of_the_next_month():
    assert pcal.monthly_due(2026, 11) == D(2026, 12, 15)
    assert pcal.monthly_due(2026, 12) == D(2027, 1, 15)
    # February 15, 2026 is a Sunday and the 16th is Washington's Birthday.
    assert pcal.monthly_due(2026, 1) == D(2026, 2, 17)
    # April 15, 2023 was a Saturday and Emancipation Day was observed Monday the 17th: Tuesday.
    assert pcal.monthly_due(2023, 3) == D(2023, 4, 18)
    # April 15, 2022 was itself Emancipation Day observed (the 16th was a Saturday): Monday.
    assert pcal.monthly_due(2022, 3) == D(2022, 4, 18)


@pytest.mark.parametrize("pay, due", [
    (D(2026, 12, 2), D(2026, 12, 9)),    # Wednesday → following Wednesday
    (D(2026, 12, 3), D(2026, 12, 9)),    # Thursday
    (D(2026, 12, 4), D(2026, 12, 9)),    # Friday
    (D(2026, 12, 5), D(2026, 12, 11)),   # Saturday → following Friday
    (D(2026, 12, 6), D(2026, 12, 11)),   # Sunday
    (D(2026, 12, 7), D(2026, 12, 11)),   # Monday
    (D(2026, 12, 8), D(2026, 12, 11)),   # Tuesday
    (D(2026, 12, 18), D(2026, 12, 23)),  # Friday, no holiday after it
    # Tuesday Dec 22: Wed 23, Thu 24, and Christmas on a Friday is no business day: Monday 28.
    (D(2026, 12, 22), D(2026, 12, 28)),
    # Friday Jan 16: Monday the 19th is Martin Luther King Jr. Day, so a business day more: Thursday.
    (D(2026, 1, 16), D(2026, 1, 22)),
    # Tuesday before Thanksgiving: Wed 25, (Thu 26), Fri 27, Mon 30.
    (D(2026, 11, 24), D(2026, 11, 30)),
    # Saturday Dec 26: the period closes Tue 29; Wed 30, Thu 31, (New Year's Fri), Mon Jan 4.
    (D(2026, 12, 26), D(2027, 1, 4)),
])
def test_the_semiweekly_rule(pay, due):
    assert pcal.semiweekly_due(pay) == due


def test_more_monthly_rolls_from_the_review():
    assert pcal.monthly_due(2027, 12) == D(2028, 1, 18)            # Jan 15 Sat, Jan 17 MLK Day
    assert pcal.monthly_due(2027, 3) == D(2027, 4, 15)             # a Thursday; Emancipation Day is the 16th
    assert pcal.monthly_due(2028, 3) == D(2028, 4, 18)             # Sat 15; Mon 17 is Emancipation Day observed
    assert pcal.year_end_due(2027) == D(2028, 1, 31)               # a Monday
    assert pcal.approve_by(D(2026, 1, 20)) == D(2026, 1, 15)       # MLK Day Monday skipped
    assert pcal.approve_by(D(2026, 7, 6)) == D(2026, 7, 2)         # Fri Jul 3 is a bank day: Thu Jul 2, Fri Jul 3


def test_the_state_day_rolls_on_bank_days_not_dc_holidays():
    assert pcal.state_due(2026, 11, 20) == D(2026, 12, 21)        # Dec 20, 2026 is a Sunday
    assert pcal.state_due(2026, 11, 15) == D(2026, 12, 15)
    # A state's deadline doesn't follow DC: Emancipation Day (Thu Apr 16, 2026) moves nothing ...
    assert pcal.state_due(2026, 3, 16) == D(2026, 4, 16)
    # ... nor does Friday July 3, 2026, a federal "observed" day the banks stay open on.
    assert pcal.state_due(2026, 6, 3) == D(2026, 7, 3)
    assert pcal.state_due(2026, 11, 25) == D(2026, 12, 28)         # Christmas on a Friday, then the weekend
    assert pcal.due_for(pcal.parse_key("state:2026-03"), {"state_day": 16}) == D(2026, 4, 16)


def test_eftps_needs_the_deposit_by_8_pm_eastern_the_day_before():
    assert pcal.eftps_by(D(2026, 12, 15)) == D(2026, 12, 14)
    assert pcal.eftps_words(D(2026, 12, 15)) == "Submit it on EFTPS by 8 p.m. Eastern on Mon, Dec 14."
    assert pcal.eftps_words(D(2027, 2, 1)) == "Submit it on EFTPS by 8 p.m. Eastern on Sun, Jan 31."


@pytest.mark.parametrize("payday, by", [
    (D(2026, 12, 15), D(2026, 12, 11)),  # Tuesday → the Friday before
    (D(2026, 12, 31), D(2026, 12, 29)),
    (D(2026, 12, 28), D(2026, 12, 23)),  # Monday after Christmas on a Friday: Wednesday the 23rd
    (D(2027, 1, 4), D(2026, 12, 30)),    # New Year's Day on a Friday
    (D(2026, 11, 27), D(2026, 11, 24)),  # the Friday after Thanksgiving
])
def test_approve_by_is_two_bank_days_before_payday(payday, by):
    assert pcal.approve_by(payday) == by


# ─── Keys and settings ────────────────────────────────────────────────

def test_keys_are_shape_checked_and_name_their_due_date():
    s = {"deposit_schedule": "monthly", "state_day": 20, "state_label": None}
    assert pcal.parse_key("federal:2026-11")["schedule"] == "monthly"
    assert pcal.due_for(pcal.parse_key("federal:2026-11"), s) == D(2026, 12, 15)
    assert pcal.due_for(pcal.parse_key("federal:2026-12-22"), s) == D(2026, 12, 28)
    assert pcal.due_for(pcal.parse_key("state:2026-11"), s) == D(2026, 12, 21)
    assert pcal.due_for(pcal.parse_key("state:2026-11"), {**s, "state_day": None}) is None
    assert pcal.due_for(pcal.parse_key("forms:941:2026Q3"), s) == D(2026, 11, 2)
    assert pcal.due_for(pcal.parse_key("forms:w2:2026"), s) == D(2027, 2, 1)
    for bad in ("federal:2026-13", "federal:2026-02-30", "state:2026", "forms:941:2026Q5", "forms:w3:2026",
                "federal:2026-11&business_id=eq.x", "", None, "federal:2026-11\n"):
        assert pcal.parse_key(bad) is None, bad


def test_settings_are_read_safely_and_checked_before_saving():
    assert pcal.settings_of({"settings": {}}) == {"deposit_schedule": "monthly", "state_day": None,
                                                  "state_label": None}
    got = pcal.settings_of({"settings": {"payroll": {"deposit_schedule": "semiweekly", "state_day": 31,
                                                     "state_label": " Ohio <b>SD 101</b> "}}})
    assert got == {"deposit_schedule": "semiweekly", "state_day": None, "state_label": "Ohio b SD 101 /b"}
    assert pcal.settings_patch({"state_day": None, "state_label": ""}) == {"state_day": None, "state_label": None}
    for bad in ({"deposit_schedule": "weekly"}, {"state_day": 29}, {"state_day": 0}, {"state_day": True},
                {"state_day": "15"}):
        with pytest.raises(ValueError):
            pcal.settings_patch(bad)


def test_projected_paydays_keep_each_cadence_and_never_reach_past_the_horizon():
    got = pcal.projected_paydays(D(2026, 11, 30), ["semimonthly"], D(2027, 1, 31))
    assert got == [D(2026, 12, 15), D(2026, 12, 31), D(2027, 1, 15), D(2027, 1, 29)]   # Jan 31 is a Sunday
    assert pcal.projected_paydays(D(2026, 11, 20), ["biweekly", "biweekly"], D(2026, 12, 31)) == \
        [D(2026, 12, 4), D(2026, 12, 18)]
    assert pcal.projected_paydays(D(2026, 10, 31), ["monthly"], D(2027, 1, 31)) == \
        [D(2026, 11, 30), D(2026, 12, 31), D(2027, 1, 29)]
    assert pcal.projected_paydays(None, ["weekly"], D(2027, 1, 1)) == []
    assert pcal.projected_paydays(D(2026, 12, 1), ["weekly"], D(2026, 12, 20), taken=[D(2026, 12, 8)]) == \
        [D(2026, 12, 15)]


# ─── The month view ───────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    people(db)
    return db


def _row(db):
    return next(b for b in db.rows("businesses") if b["id"] == CHURCH)


def test_december_2026_with_christmas_on_a_friday(db):
    _row(db)["settings"]["payroll"] = {"deposit_schedule": "monthly", "state_day": 15, "state_label": "Ohio"}
    nov = run(db, "2026-11-30", "paid", lines=standard_lines())
    dec15 = run(db, "2026-12-15", "approved", lines=standard_lines())
    dec31 = run(db, "2026-12-31", "draft", lines=standard_lines())
    view = pcal.month_view(_row(db), "2026-12", today=D(2026, 12, 1))
    assert view["ok"] and view["month"] == "2026-12"
    assert view["settings"] == {"deposit_schedule": "monthly", "state_day": 15, "state_label": "Ohio"}
    days = {d["date"]: d["events"] for d in view["days"]}
    assert set(days) == {"2026-12-11", "2026-12-15", "2026-12-25", "2026-12-29", "2026-12-31"}
    assert days["2026-12-25"] == [{"kind": "holiday", "title": "Christmas", "sub": "banks closed", "amount": None,
                                   "run_id": None, "deposit_key": None, "status": None}]
    approve = days["2026-12-11"][0]
    assert approve["kind"] == "approve" and approve["run_id"] == dec15["id"] and approve["status"] == "done"
    assert days["2026-12-29"][0]["run_id"] == dec31["id"] and days["2026-12-29"][0]["status"] == "open"
    kinds = [e["kind"] for e in days["2026-12-15"]]
    assert kinds == ["payday", "deposit_federal", "deposit_state"]
    fed = days["2026-12-15"][1]
    # November's run: $650 withheld + $124 × 2 Social Security + $29 × 2 Medicare (the pastor owes none).
    assert fed["amount"] == 956.0 and fed["deposit_key"] == "federal:2026-11" and fed["status"] == "open"
    assert fed["sub"] == "for November. Submit it on EFTPS by 8 p.m. Eastern on Mon, Dec 14."
    assert "_for" not in fed                                    # the reminders' own words stay inside
    state = days["2026-12-15"][2]
    assert state["title"] == "Ohio" and state["amount"] == 140.0 and state["deposit_key"] == "state:2026-11"
    assert days["2026-12-15"][0]["amount"] == dec15["totals"]["net"]
    assert days["2026-12-31"][0]["status"] == "open" and days["2026-12-31"][0]["amount"] is None   # a draft
    # Next: the earliest open to-do from today.
    assert view["next"] == {"kind": "deposit_federal", "title": "IRS deposit", "date": "2026-12-15",
                            "amount": 956.0, "deposit_key": "federal:2026-11"}
    later = [(x["date"], x["title"]) for x in view["later"]]
    assert ("2027-01-15", "IRS deposit") in later and ("2027-01-15", "Ohio") in later
    assert ("2027-02-01", "Form 941") in later and ("2027-02-01", "W-2s, W-3 and 1099-NEC") in later
    w2 = next(x for x in view["later"] if x["title"].startswith("W-2s"))
    assert "January 31 is a Sunday, so they’re due Monday, Feb 1." in w2["sub"]
    assert view["deposits_ready"] is True
    _ = nov


def test_a_deposit_marked_sent_and_a_paid_payday_say_so(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    db.rows("payroll_deposits").append({"business_id": CHURCH, "key": "federal:2026-11", "kind": "federal",
                                        "period": "2026-11", "amount": 956.0, "sent_on": "2026-12-10"})
    view = pcal.month_view(_row(db), "2026-11", today=D(2026, 12, 1))
    nov30 = next(d for d in view["days"] if d["date"] == "2026-11-30")["events"]
    assert nov30[0]["kind"] == "payday" and nov30[0]["status"] == "done"
    dec = pcal.month_view(_row(db), "2026-12", today=D(2026, 12, 1))
    fed = next(e for d in dec["days"] for e in d["events"] if e["kind"] == "deposit_federal")
    assert fed["status"] == "sent"
    # Without a state day, one line asks for it.
    assert dec["later"][-1]["date"] is None and dec["later"][-1]["title"] == "Set your state’s due date"


def test_semiweekly_deposits_are_keyed_by_pay_date(db):
    _row(db)["settings"]["payroll"] = {"deposit_schedule": "semiweekly"}
    run(db, "2026-12-22", "approved", lines=standard_lines())
    view = pcal.month_view(_row(db), "2026-12", today=D(2026, 12, 1))
    fed = next(e for d in view["days"] for e in d["events"] if e["kind"] == "deposit_federal")
    day = next(d["date"] for d in view["days"] if fed in d["events"])
    assert day == "2026-12-28" and fed["deposit_key"] == "federal:2026-12-22"
    assert fed["sub"] == "for the Dec 22 payday. Submit it on EFTPS by 8 p.m. Eastern on Sun, Dec 27."


def test_projected_paydays_are_marked_and_never_more_than_three_months_out(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())    # the pastor monthly, Dana biweekly
    view = pcal.month_view(_row(db), "2026-12", today=D(2026, 12, 1))
    paydays = [(d["date"], e) for d in view["days"] for e in d["events"] if e["kind"] == "payday"]
    assert paydays and all(e["sub"] == "projected" and e["status"] is None and e["amount"] is None
                           for _d, e in paydays)
    assert ("2026-12-31", ) in [(d,) for d, _e in paydays]    # monthly, month end
    assert ("2026-12-14", ) in [(d,) for d, _e in paydays]    # biweekly from Nov 30
    far = pcal.month_view(_row(db), "2027-04", today=D(2026, 12, 1))
    assert not [e for d in far["days"] for e in d["events"] if e["kind"] == "payday"]


def test_a_payroll_that_stopped_long_ago_projects_nothing_into_the_past(db):
    run(db, "2024-03-29", "paid", lines=standard_lines())
    view = pcal.month_view(_row(db), "2026-11", today=D(2026, 11, 19))
    paydays = [d["date"] for d in view["days"] for e in d["events"] if e["kind"] == "payday"]
    assert paydays and all(p >= "2026-11-19" for p in paydays)
    assert not [e for d in pcal.month_view(_row(db), "2026-10", today=D(2026, 11, 19))["days"]
                for e in d["events"] if e["kind"] in ("payday", "approve")]


def test_a_month_must_be_a_month(db):
    for bad in ("2026-13", "26-12", "2026/12", "1999-01", "2026-12-01"):
        with pytest.raises(ValueError):
            pcal.month_view(_row(db), bad, today=D(2026, 12, 1))


def test_before_the_migration_nothing_is_marked_and_the_calendar_still_reads(db):
    db.missing.add("payroll_deposits")
    run(db, "2026-11-30", "paid", lines=standard_lines())
    view = pcal.month_view(_row(db), "2026-12", today=D(2026, 12, 1))
    assert view["deposits_ready"] is False
    fed = next(e for d in view["days"] for e in d["events"] if e["kind"] == "deposit_federal")
    assert fed["status"] == "open"


def test_a_read_that_fails_is_never_an_empty_month(db, monkeypatch):
    db.missing.add("employees")
    with pytest.raises(pcal.Unreadable):
        pcal.month_view(_row(db), "2026-12", today=D(2026, 12, 1))


# ─── Paying with the 941, and Form 944 (M-6, 2026-11-27) ──────────────

def test_the_two_small_schedules_have_keys_and_due_dates():
    q = {"deposit_schedule": "quarterly", "state_day": None, "state_label": None}
    assert pcal.federal_key("quarterly", D(2026, 11, 30)) == "federal:2026Q4"
    assert pcal.federal_key("annual", D(2026, 3, 13)) == "federal:2026"
    assert pcal.parse_key("federal:2026Q4") == {"kind": "federal", "period": "2026Q4", "year": 2026, "q": 4,
                                                "schedule": "quarterly"}
    assert pcal.parse_key("federal:2026") == {"kind": "federal", "period": "2026", "year": 2026, "schedule": "annual"}
    assert pcal.due_for(pcal.parse_key("federal:2026Q3"), q) == D(2026, 11, 2)     # with the Q3 941 (Oct 31: Sat)
    assert pcal.due_for(pcal.parse_key("federal:2026Q4"), q) == D(2027, 2, 1)
    assert pcal.due_for(pcal.parse_key("federal:2026"), q) == D(2027, 2, 1)        # with the 944: Jan 31, 2027 a Sunday
    assert pcal.due_for(pcal.parse_key("forms:944:2026"), q) == D(2027, 2, 1)
    assert pcal.parse_key("forms:944:2026")["form"] == "944"
    for bad in ("federal:2026Q5", "federal:202", "federal:20261", "forms:944:2026Q1", "forms:944:26"):
        assert pcal.parse_key(bad) is None, bad
    assert pcal.settings_patch({"deposit_schedule": "quarterly"}) == {"deposit_schedule": "quarterly"}
    assert pcal.settings_patch({"deposit_schedule": "annual"}) == {"deposit_schedule": "annual"}
    assert pcal.settings_of({"settings": {"payroll": {"deposit_schedule": "annual"}}})["deposit_schedule"] == "annual"


def test_the_table_s_key_check_matches_the_calendar_s_keys():
    """A key the calendar makes must be one payroll_deposits accepts, or Mark
    sent fails at the database. Both migration files, against KEY_RE."""
    import re
    root = pathlib.Path(__file__).resolve().parent.parent / "supabase"
    keys = ["federal:2026-11", "federal:2026-12-22", "federal:2026Q4", "federal:2026", "state:2026-11",
            "forms:941:2026Q4", "forms:944:2026", "forms:w2:2026",
            "federal:2026Q5", "federal:20261", "forms:944:2026Q1", "forms:w3:2026", "state:2026", "federal:2026-11x"]
    for name in ("APPLY-2026-11-19-payroll-deposits.sql", "APPLY-2026-11-27-payroll-deposit-keys.sql"):
        sql = (root / name).read_text(encoding="utf-8")
        pattern = re.search(r"key ~ '\^\((.+)\)\$'", sql).group(1)
        for k in keys:
            assert bool(re.fullmatch(pattern, k)) == bool(pcal.KEY_RE.fullmatch(k)), (name, k)


def _feb_2027(db):
    view = pcal.month_view(_row(db), "2027-02", today=D(2026, 12, 1))
    return [e for d in view["days"] if d["date"] == "2027-02-01" for e in d["events"]]


def test_paying_with_the_941_is_one_deposit_a_quarter_due_with_the_return(db):
    _row(db)["settings"]["payroll"] = {"deposit_schedule": "quarterly"}
    run(db, "2026-11-30", "paid", lines=standard_lines())
    feb1 = _feb_2027(db)
    fed = next(e for e in feb1 if e["kind"] == "deposit_federal")
    assert fed["deposit_key"] == "federal:2026Q4" and fed["amount"] == 956.0
    assert fed["sub"].startswith("for October to December, paid with the Form 941. Submit it on EFTPS")
    assert "can’t wait for the return" not in fed["sub"]
    assert [e["title"] for e in feb1 if e["kind"] == "forms"] == ["Form 941", "W-2s, W-3 and 1099-NEC"]


def test_a_quarter_that_reaches_2500_says_it_can_not_wait_for_the_return(db):
    _row(db)["settings"]["payroll"] = {"deposit_schedule": "quarterly"}
    for pd in ("2026-10-30", "2026-11-30", "2026-12-31"):
        run(db, pd, "paid", lines=standard_lines())            # $956 each: $2,868 for the quarter
    fed = next(e for e in _feb_2027(db) if e["kind"] == "deposit_federal")
    assert fed["amount"] == 2868.0
    assert "This quarter’s taxes have reached $2,500, so they can’t wait for the return" in fed["sub"]


def test_a_form_944_filer_files_once_a_year_and_pays_with_it(db):
    _row(db)["settings"]["payroll"] = {"deposit_schedule": "annual"}
    run(db, "2026-11-30", "paid", lines=standard_lines())
    feb1 = _feb_2027(db)
    fed = next(e for e in feb1 if e["kind"] == "deposit_federal")
    assert fed["deposit_key"] == "federal:2026" and fed["sub"].startswith("for 2026, paid with Form 944.")
    forms = [e for e in feb1 if e["kind"] == "forms"]
    assert [e["title"] for e in forms] == ["Form 944", "W-2s, W-3 and 1099-NEC"]
    assert forms[0]["deposit_key"] == "forms:944:2026"
    assert "January 31 is a Sunday" in forms[0]["sub"]
    # No 941 anywhere in the year for a 944 filer.
    for m in ("2026-04", "2026-05", "2026-07", "2026-08", "2026-10", "2026-11"):
        view = pcal.month_view(_row(db), m, today=D(2026, 12, 1))
        assert not any(e["title"] == "Form 941" for d in view["days"] for e in d["events"]), m
