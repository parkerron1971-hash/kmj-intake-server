"""Payroll, the free version: the quarter's and the year's worksheets
(payroll_forms.py), against numbers worked out by hand. Worksheets only:
never an official form, never filed. Every name and figure is made up.
"""
from __future__ import annotations

import csv
import io
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import payroll_forms as pf
from payroll_free_fake import (CHURCH, PASTOR, STAFF, PayrollFake, designate, install, people, run, seed,
                               standard_lines, uid)

TODAY = date(2026, 12, 20)


@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    people(db)
    return db


def _biz(db):
    return next(b for b in db.rows("businesses") if b["id"] == CHURCH)


def _q4(db):
    a = run(db, "2026-10-30", "paid", lines=standard_lines())
    b = run(db, "2026-11-30", "paid", lines=standard_lines())
    c = run(db, "2026-12-31", "approved", lines=standard_lines())
    return a, b, c


def _deposit(db, key, amount):
    db.rows("payroll_deposits").append({"business_id": CHURCH, "key": key, "kind": key.split(":")[0],
                                        "period": key.split(":", 1)[1], "amount": amount, "sent_on": "2026-11-13"})


def test_the_fourth_quarter_by_hand(db):
    _q4(db)
    designate(db)                         # $24,000 designated Dec 14, 2025: every housing part is left out
    _deposit(db, "federal:2026-10", 956.0)
    _deposit(db, "state:2026-10", 140.0)
    q = pf.quarter(_biz(db), 2026, 4, today=TODAY)
    # Two paid runs (the approved Dec 31 run isn't in yet). Each: the pastor
    # $6,000 with $2,000 housing, $500 federal; Dana $2,000, $150 federal.
    assert q["lines"] == {
        "2": 12000.0,          # (6,000 - 2,000 + 2,000) × 2: the housing allowance left out
        "3": 1300.0,           # (500 + 150) × 2
        "5a_wages": 4000.0, "5a_tax": 496.0,     # staff only: 4,000 × 12.4%; the minister isn't in
        "5c_wages": 4000.0, "5c_tax": 116.0,     # 4,000 × 2.9%
        "5d_wages": 0.0, "5d_tax": 0.0,
        "6": 1912.0,           # 1,300 + 496 + 116
        "7": 0.0, "12": 1912.0}
    assert q["months"] == [956.0, 956.0, 0.0]    # 650 + 124 × 2 + 29 × 2 a month
    assert q["runs_in"] == 2 and q["runs_expected"] == 3
    assert q["deposited"] == 956.0 and [d["key"] for d in q["deposits"]] == ["federal:2026-10"]
    assert q["due"] == "2027-02-01" and q["year"] == 2026 and q["q"] == 4 and q["schedule"] == "monthly"
    assert "Ministers aren’t in lines 5a and 5c" in " ".join(q["notes"])


def test_the_wage_base_and_additional_medicare_land_where_they_did(db):
    big = uid()
    db.rows("employees").append({"id": big, "business_id": CHURCH, "first_name": "Rowan", "last_name": "Vale",
                                 "status": "active", "pay_type": "hourly", "pay_rate": 1000.0,
                                 "pay_frequency": "monthly", "work_state": "OH"})
    run(db, "2026-03-31", "paid", lines=[{"employee_id": big, "hours": 150, "fit": 30000.0, "sit": 0.0}])
    run(db, "2026-06-30", "paid", lines=[{"employee_id": big, "hours": 100, "fit": 20000.0, "sit": 0.0,
                                          "ytd": 150000.0}])
    q1 = pf.quarter(_biz(db), 2026, 1, today=TODAY)
    assert q1["lines"]["5a_wages"] == 150000.0 and q1["lines"]["5a_tax"] == 18600.0
    assert q1["lines"]["6"] == 52950.0 and q1["months"] == [0.0, 0.0, 52950.0] and q1["lines"]["7"] == 0.0
    q2 = pf.quarter(_biz(db), 2026, 2, today=TODAY)
    # $184,500 wage base: $34,500 of June's $100,000 was Social Security wages.
    assert q2["lines"]["5a_wages"] == 34500.0 and q2["lines"]["5a_tax"] == 4278.0
    assert q2["lines"]["5c_wages"] == 100000.0 and q2["lines"]["5c_tax"] == 2900.0
    # Wages past $200,000 for the year: $50,000 × 0.9%.
    assert q2["lines"]["5d_wages"] == 50000.0 and q2["lines"]["5d_tax"] == 450.0
    assert q2["lines"]["6"] == 27628.0 and q2["lines"]["12"] == 27628.0 and q2["months"] == [0.0, 0.0, 27628.0]
    y = pf.year(_biz(db), 2026, today=TODAY)
    w2 = next(p for p in y["w2"] if p["employee"]["id"] == big)["boxes"]
    assert w2["3"] == 184500.0 and w2["4"] == 11439.0 and w2["5"] == 250000.0 and w2["6"] == 4075.0


def test_the_year_while_runs_are_still_to_pay(db):
    _q4(db)
    designate(db)
    y = pf.year(_biz(db), 2026, today=TODAY)
    assert y["projected"] is True and y["note"].startswith("Shown as they’ll be once the approved runs are paid")
    assert y["due"] == "2027-02-01"
    by = {p["employee"]["id"]: p for p in y["w2"]}
    assert by[PASTOR]["employee"] == {"id": PASTOR, "name": "Marcus Ellwood", "title": "Senior pastor",
                                      "minister": True}
    assert by[PASTOR]["boxes"] == {"1": 12000.0, "2": 1500.0, "3": None, "4": None, "5": None, "6": None,
                                   "14": [{"label": "Housing", "amount": 6000.0}], "16": 12000.0, "17": 300.0}
    assert by[STAFF]["boxes"] == {"1": 6000.0, "2": 450.0, "3": 6000.0, "4": 372.0, "5": 6000.0, "6": 87.0,
                                  "14": [], "16": 6000.0, "17": 120.0}
    assert by[STAFF]["missing"] == ["a mailing address"] and by[PASTOR]["missing"] == []
    assert y["w3"] == {"1": 18000.0, "2": 1950.0, "3": 6000.0, "4": 372.0, "5": 6000.0, "6": 87.0}
    ready = {r["key"]: r for r in y["readiness"]}
    assert list(ready) == ["runs_paid", "w4s", "addresses", "ssns", "w9s", "housing_designation"]
    assert ready["runs_paid"] == {"key": "runs_paid", "ok": True, "line": "Every 2026 pay run so far is marked paid",
                                  "fix": None}
    assert ready["addresses"]["ok"] is False
    assert ready["addresses"]["line"] == "Dana Reyes has no mailing address, and the W-2 needs one"
    assert ready["w4s"]["ok"] and ready["ssns"]["ok"] and ready["housing_designation"]["ok"]
    assert ready["w9s"] == {"key": "w9s", "ok": True, "line": "No contractor reached the $2,000 line in 2026",
                            "fix": None}


def test_paid_runs_alone_once_nothing_is_left_to_pay(db):
    run(db, "2025-11-28", "paid", lines=standard_lines())
    run(db, "2025-12-31", "paid", lines=standard_lines())
    y = pf.year(_biz(db), 2025, today=TODAY)
    assert y["projected"] is False and y["note"] is None and y["due"] == "2026-02-02"   # Jan 31, 2026: Saturday
    # Nothing was designated for 2025, so the pastor's $4,000 of housing is wages too.
    assert y["w3"]["1"] == 16000.0
    ready = {r["key"]: r for r in y["readiness"]}
    assert ready["housing_designation"]["ok"] is False
    assert "No 2025 housing allowance designation is on file for Marcus Ellwood" == ready["housing_designation"]["line"]
    pastor = next(p for p in y["w2"] if p["employee"]["id"] == PASTOR)
    assert "the board’s 2025 housing designation" in pastor["missing"]


def test_a_run_left_unpaid_is_flagged(db):
    run(db, "2026-11-30", "approved", lines=standard_lines())
    ready = {r["key"]: r for r in pf.year(_biz(db), 2026, today=TODAY)["readiness"]}
    assert ready["runs_paid"]["ok"] is False
    assert ready["runs_paid"]["line"] == "1 2026 pay run dated on or before today isn’t marked paid yet"
    assert ready["runs_paid"]["fix"]


def test_housing_paid_before_the_boards_vote_stays_in_box_1(db):
    _q4(db)
    designate(db, on="2026-11-15")
    y = pf.year(_biz(db), 2026, today=TODAY)
    pastor = next(p for p in y["w2"] if p["employee"]["id"] == PASTOR)
    assert pastor["boxes"]["1"] == 14000.0 and pastor["boxes"]["14"] == [{"label": "Housing", "amount": 4000.0}]
    assert any("before the board’s vote" in n for n in pastor["notes"])
    assert pf.quarter(_biz(db), 2026, 4, today=TODAY)["lines"]["2"] == 14000.0


def test_the_housing_records_switched_off_says_so(db, monkeypatch):
    import housing_allowance
    monkeypatch.setattr(housing_allowance, "switched_on", lambda biz: False)
    _q4(db)
    y = pf.year(_biz(db), 2026, today=TODAY)
    ready = {r["key"]: r for r in y["readiness"]}
    assert ready["housing_designation"]["ok"] is False and ready["housing_designation"]["fix"] is None
    assert "aren’t switched on" in ready["housing_designation"]["line"]
    # Nothing can be checked: left out as before, and the W-2 row says so.
    pastor = next(p for p in y["w2"] if p["employee"]["id"] == PASTOR)
    assert pastor["boxes"]["1"] == 12000.0 and pastor["boxes"]["14"] == [{"label": "Housing", "amount": 6000.0}]
    assert any("as if the board designated it in advance" in n for n in pastor["notes"])


def _year_of_housing(db):
    """Twelve paid months: the pastor $6,000 a month, $2,000 of it housing."""
    for m in range(1, 13):
        run(db, f"2026-{m:02d}-28", "paid", lines=standard_lines(ytd_staff=2000.0 * (m - 1)))


def test_housing_past_what_the_board_designated_is_wages(db):
    # The reviewer's case: $12,000 designated, $24,000 paid as housing.
    designate(db, amount=12000.0, on="2025-12-14")
    _year_of_housing(db)
    y = pf.year(_biz(db), 2026, today=date(2027, 1, 10))
    pastor = next(p for p in y["w2"] if p["employee"]["id"] == PASTOR)
    assert pastor["boxes"]["1"] == 60000.0                       # $72,000 pay, $12,000 left out
    assert pastor["boxes"]["14"] == [{"label": "Housing", "amount": 12000.0}]
    assert any(n.startswith("$12,000.00 of housing is more than the board designated for 2026 ($12,000.00)")
               and "Treas. Reg. 1.107-1(b)" in n for n in pastor["notes"])
    # The designation runs out in June: the second half's housing is wages on line 2.
    q2 = pf.quarter(_biz(db), 2026, 2, today=date(2027, 1, 10))
    assert q2["lines"]["2"] == 18000.0                           # (4,000 + 2,000) × 3
    q4 = pf.quarter(_biz(db), 2026, 4, today=date(2027, 1, 10))
    assert q4["lines"]["2"] == 24000.0                           # (6,000 + 2,000) × 3
    assert any(n.startswith("$6,000.00 of housing paid this quarter is counted as wages on line 2: it was more "
                            "than the board designated for the year") for n in q4["notes"])


def test_no_designation_in_advance_makes_all_the_housing_wages(db):
    _year_of_housing(db)
    y = pf.year(_biz(db), 2026, today=date(2027, 1, 10))
    pastor = next(p for p in y["w2"] if p["employee"]["id"] == PASTOR)
    assert pastor["boxes"]["1"] == 72000.0 and pastor["boxes"]["14"] == []
    assert "the board’s 2026 housing designation" in pastor["missing"]
    assert any("No housing allowance was designated in advance for 2026" in n for n in pastor["notes"])
    q1 = pf.quarter(_biz(db), 2026, 1, today=date(2027, 1, 10))
    assert q1["lines"]["2"] == 24000.0 and any("not designated in advance" in n for n in q1["notes"])


def test_a_tiny_check_is_not_taken_for_a_ministers(db):
    assert pf._exempt({"gross": 0.30, "medicare_employee": 0.0, "employer_medicare": 0.0}) is False
    assert pf._exempt({"gross": 6000.0, "medicare_employee": 0.0, "employer_medicare": 0.0}) is True
    assert pf._exempt({"gross": 6000.0, "medicare_employee": 87.0, "employer_medicare": 87.0}) is False


def _contractors(db):
    jordan, simone = uid(), uid()
    db.rows("contractors").extend([
        {"id": jordan, "business_id": CHURCH, "name": "Jordan Pike", "tin_last4": "1111", "stripe_account_id": None,
         "tin_encrypted": "gAAAA-TIN-CIPHER"},
        {"id": simone, "business_id": CHURCH, "name": "Simone Carr", "tin_last4": None, "stripe_account_id": None}])
    stripe_paid = uid()
    db.rows("contractors").append({"id": stripe_paid, "business_id": CHURCH, "name": "Remy Stripe",
                                   "tin_last4": None, "stripe_account_id": "acct_made_up"})
    for cid, name, amt, when in ((jordan, "Jordan Pike", 1200.0, "2026-03-01"), (jordan, "Jordan Pike", 1200.0,
                                                                                 "2026-09-01"),
                                 (simone, "Simone Carr", 1500.0, "2026-05-01"),
                                 (stripe_paid, "Remy Stripe", 5000.0, "2026-07-01"),
                                 (None, "=HYPERLINK(\"x\")", 2100.0, "2026-06-01")):
        db.rows("bills").append({"id": uid(), "business_id": CHURCH, "status": "paid", "is_1099_eligible": True,
                                 "paid_at": f"{when}T12:00:00Z", "paid_amount": amt, "amount": amt,
                                 "vendor_name": name, "contractor_id": cid})


def test_contractors_at_the_2000_line_with_their_w9s(db):
    _q4(db)
    _contractors(db)
    y = pf.year(_biz(db), 2026, today=TODAY)
    assert y["nec_threshold"] == 2000.0
    # Simone's $1,500 is under the line; Remy's $5,000 went through Stripe, which files that 1099 itself
    # (excluded exactly as the 1099 drafts exclude it).
    assert sorted((c["name"], c["amount"], c["w9"]) for c in y["contractors"]) == [
        ("=HYPERLINK(\"x\")", 2100.0, False), ("Jordan Pike", 2400.0, True)]
    ready = {r["key"]: r for r in y["readiness"]}
    assert ready["w9s"]["ok"] is False and ready["w9s"]["line"] == "=HYPERLINK(\"x\") has no W-9 on file"
    assert pf.nec_threshold(2025) == 600.0 and pf.nec_threshold(2026) == 2000.0 and pf.nec_threshold(2030) == 2000.0


def test_the_csv_is_a_worksheet_that_never_runs_a_formula(db):
    _q4(db)
    designate(db)
    _contractors(db)
    data = pf.year(_biz(db), 2026, today=TODAY)
    text = pf.year_csv(_biz(db), data)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["Year-end payroll worksheet, 2026", "Grace Harbor Church"]
    assert rows[1][0].startswith("WORKSHEET ONLY") and rows[2][0] == pf.FILE_IT
    dana = next(r for r in rows if r and r[0] == "Dana Reyes")
    assert dana[3:10] == ["6000.00", "450.00", "6000.00", "372.00", "6000.00", "87.00", ""]
    pastor = next(r for r in rows if r and r[0] == "Marcus Ellwood")
    assert pastor[2] == "yes" and pastor[5:9] == ["", "", "", ""] and pastor[9] == "6000.00"
    assert next(r for r in rows if r and r[0] == "W-3 totals")[3] == "18000.00"
    assert any(r and r[0] == "'=HYPERLINK(\"x\")" for r in rows)
    assert not any(r and r[0].startswith("=") for r in rows)
    assert "5508" not in text and "4321" not in text and "CIPHER" not in text


def _text(pdf_bytes: bytes) -> str:
    import pypdf
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


# Words an official form carries and a worksheet must not.
OFFICIAL = ("Wage and Tax Statement", "Employer's QUARTERLY Federal Tax Return", "OMB No", "Copy A",
            "Department of the Treasury", "Internal Revenue Service", "For Official Use", "Employer identification number")


def test_the_pdfs_are_worksheets_not_forms(db):
    _q4(db)
    designate(db)
    _contractors(db)
    q = pf.quarter(_biz(db), 2026, 4, today=TODAY)
    qt = _text(pf.quarter_pdf(_biz(db), q))
    for want in ("Form 941 worksheet: October to December 2026", "WORKSHEET ONLY", "Solutionist doesn",
                 "You deposit monthly", "Monday, February 1, 2027", "$1,912.00", "$496.00", "IRS e-file"):
        assert want in qt, want
    yt = _text(pf.year_pdf(_biz(db), pf.year(_biz(db), 2026, today=TODAY)))
    for want in ("Year-end payroll worksheet, 2026", "WORKSHEET ONLY", "Solutionist doesn", "ssa.gov/bso",
                 "irs.gov/iris", "Marcus Ellwood (minister)", "W-3 totals", "$18,000.00", "Jordan Pike",
                 "Still needed: a mailing address"):
        assert want in yt, want
    for text in (qt, yt):
        for never in OFFICIAL + ("5508", "4321", "1111", "CIPHER"):
            assert never not in text, never


def test_the_worksheets_never_touch_the_official_forms():
    src = (pathlib.Path(pf.__file__)).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    for never in ("import irs_forms", "irs-pdf", "fw2.pdf", "f941.pdf", "fw3.pdf", "AcroForm", "tin_crypto",
                  "decrypt", "ssn_encrypted\"", "tin_encrypted"):
        assert never not in code, never


def test_a_read_that_fails_is_never_a_worksheet_of_zeros(db):
    _q4(db)
    db.missing.add("pay_run_items")
    with pytest.raises(pf.Unavailable):
        pf.quarter(_biz(db), 2026, 4, today=TODAY)
    with pytest.raises(pf.Unavailable):
        pf.year(_biz(db), 2026, today=TODAY)
