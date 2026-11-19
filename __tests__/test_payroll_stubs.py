"""Payroll, the free version: pay statements (payroll_stubs.py).

The JSON stub, year to date, a minister's statement, the PDF (only the last
four of an SSN or EIN, ever), and sending each person their own. Every name
and figure is made up.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import payroll_stubs as ps
from payroll_free_fake import (CHURCH, PASTOR, STAFF, PayrollFake, designate, install, people, run, seed,
                               standard_lines, uid)


@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    people(db)
    import business_identity
    monkeypatch.setattr(business_identity, "payer_block", lambda biz, row=None: {
        "name": "Grace Harbor Church", "ein": "12-3456789", "line1": "1200 Harbor Way",
        "city_state_zip": "Springfield, OH 45501", "line2": "", "phone": "", "complete": True})
    return db


def _biz(db):
    return next(b for b in db.rows("businesses") if b["id"] == CHURCH)


def _year(db):
    """Two paid runs before, a draft and an approved run that never count,
    a paid run after, last year's paid run, and this run (approved)."""
    run(db, "2025-12-31", "paid", lines=standard_lines())
    run(db, "2026-09-30", "paid", lines=standard_lines())
    run(db, "2026-10-30", "paid", lines=standard_lines())
    run(db, "2026-10-15", "draft", lines=[{"employee_id": STAFF, "fit": 150.0, "sit": 40.0}])
    run(db, "2026-11-13", "approved", lines=[{"employee_id": STAFF, "fit": 150.0, "sit": 40.0}])
    this = run(db, "2026-11-30", "approved", lines=standard_lines(), period=("2026-11-16", "2026-11-30"))
    run(db, "2026-12-15", "paid", lines=standard_lines())
    return this


def _stub(db, this, emp):
    ctx = ps.load(this, _biz(db))
    item = next(i for i in ctx["items"] if i["employee_id"] == emp)
    return ctx, ps.build(ctx, item)


def test_year_to_date_counts_paid_runs_this_year_up_to_this_one(db):
    this = _year(db)
    _ctx, s = _stub(db, this, STAFF)
    assert s["run_id"] == this["id"] and s["employee"]["name"] == "Dana Reyes"
    assert s["earnings"] == [{"key": "salary", "label": "Salary", "this": 2000.0, "ytd": 6000.0}]
    assert s["gross"] == {"this": 2000.0, "ytd": 6000.0}
    taxes = {t["key"]: t for t in s["taxes"]}
    assert taxes["federal"] == {"key": "federal", "label": "Federal income tax", "this": 150.0, "ytd": 450.0,
                                "note": None}
    assert taxes["state"]["ytd"] == 120.0
    assert taxes["social_security"]["this"] == 124.0 and taxes["social_security"]["ytd"] == 372.0
    assert taxes["medicare"]["this"] == 29.0 and taxes["medicare"]["ytd"] == 87.0
    assert s["total_taxes"] == {"this": 343.0, "ytd": 1029.0}
    # $2,000 - 150 - 40 - 124 - 29 = $1,657 a check, three checks.
    assert s["net"] == {"this": 1657.0, "ytd": 4971.0}
    assert s["housing"] is None and s["notes"] == [] and s["deductions"] == []
    assert s["period"] == {"start": "2026-11-16", "end": "2026-11-30", "pay_date": "2026-11-30", "index": 3,
                           "of": 26}
    assert s["employee"]["minister"] is False and s["employee"]["credential"] is None
    assert s["paid_by"] is None and s["employee"]["ssn_last4"] == "4321"


def test_a_ministers_statement(db):
    designate(db)
    this = _year(db)
    _ctx, s = _stub(db, this, PASTOR)
    assert s["employee"] == {"id": PASTOR, "name": "Marcus Ellwood", "title": "Senior pastor", "ssn_last4": "5508",
                             "minister": True, "credential": "ordained"}
    assert s["earnings"] == [{"key": "salary", "label": "Salary", "this": 4000.0, "ytd": 12000.0},
                             {"key": "housing", "label": "Housing allowance", "this": 2000.0, "ytd": 6000.0}]
    taxes = {t["key"]: t for t in s["taxes"]}
    assert taxes["social_security"] == {"key": "social_security", "label": "Social Security", "this": None,
                                        "ytd": None, "note": "none, minister"}
    assert taxes["medicare"]["this"] is None and taxes["medicare"]["note"] == "none, minister"
    assert taxes["federal"]["note"] == "asked for on their W-4" and taxes["federal"]["this"] == 500.0
    assert s["total_taxes"] == {"this": 600.0, "ytd": 1800.0}
    assert s["net"] == {"this": 5400.0, "ytd": 16200.0}
    assert s["housing"] == {"designated": 24000.0, "designated_on": "2025-12-14", "paid_ytd": 6000.0,
                            "left": 18000.0}
    assert len(s["notes"]) == 2
    assert s["notes"][0].startswith("Why no Social Security or Medicare: as a minister, Marcus Ellwood")
    assert s["notes"][1].startswith("Housing allowance: left out of federal income tax (section 107)")
    assert s["period"]["index"] == 11 and s["period"]["of"] == 12          # monthly, November
    assert s["paid_by"] == "direct_deposit"


def test_without_a_designation_the_housing_box_says_what_was_paid(db):
    this = _year(db)
    _ctx, s = _stub(db, this, PASTOR)
    assert s["housing"] == {"designated": None, "designated_on": None, "paid_ytd": 6000.0, "left": None}


def test_nothing_but_the_last_four_ever_leaves(db):
    this = _year(db)
    ctx = ps.load(this, _biz(db))
    blob = json.dumps(ps.all_stubs(ctx))
    assert "SECRET" not in blob and "CIPHER" not in blob and "ssn_encrypted" not in blob
    profile_reads = [r for r in db.reads if r.startswith("/employee_tax_profiles")]
    assert profile_reads and all("select=employee_id,ssn_last4&" in r for r in profile_reads)
    assert not any("ssn_encrypted" in r or "select=*" in r for r in profile_reads)
    s = ps.build(ctx, ctx["items"][0])
    assert s["payer"] == {"name": "Grace Harbor Church", "address": "1200 Harbor Way · Springfield, OH 45501",
                          "ein_last4": "6789"}


def _text(pdf_bytes: bytes) -> str:
    import pypdf
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_the_pdf_is_one_page_like_the_mock_and_carries_only_last_fours(db):
    designate(db)
    this = _year(db)
    ctx, s = _stub(db, this, PASTOR)
    data = ps.pdf(s, ctx["biz"])
    assert data[:5] == b"%PDF-"
    import pypdf
    assert len(pypdf.PdfReader(io.BytesIO(data)).pages) == 1
    text = _text(data)
    for want in ("Grace Harbor Church", "Pay statement", "Pay date Monday, November 30, 2026", "Paid to",
                 "Marcus Ellwood", "Social Security number ending 5508", "EIN ending 6789", "Pay period",
                 "Nov 16 to 30, 2026", "Paid once a month", "period 11 of 12", "Direct deposit", "Earnings",
                 "Housing allowance", "Pay before taxes", "Taxes taken out", "none, minister", "Total taxes",
                 "Take-home pay", "$5,400.00", "This year: $16,200.00", "Housing allowance for 2026",
                 "The board set $24,000.00", "$6,000.00 paid", "$18,000.00 left", "Why no Social Security",
                 "Prepared with Solutionist"):
        assert want in text, want
    for never in ("3456789", "123456789", "SECRET", "CIPHER"):
        assert never not in text, never
    assert ps.filename(s) == f"pay-statement-2026-11-30-{s['item_id'][:8]}.pdf"


def test_the_pdf_of_an_hourly_line_splits_overtime(db):
    hourly = uid()
    db.rows("employees").append({"id": hourly, "business_id": CHURCH, "first_name": "Andre", "last_name": "Hale",
                                 "status": "active", "pay_type": "hourly", "pay_rate": 20.0,
                                 "pay_frequency": "weekly", "email": None})
    this = run(db, "2026-11-27", "paid", lines=[{"employee_id": hourly, "hours": 40, "overtime_hours": 5,
                                                 "fit": 50.0, "sit": 10.0}])
    ctx, s = _stub(db, this, hourly)
    assert s["earnings"] == [{"key": "regular", "label": "Regular pay, 40 hours", "this": 800.0, "ytd": 800.0},
                             {"key": "overtime", "label": "Overtime, 5 hours", "this": 150.0, "ytd": 150.0}]
    assert "Regular pay, 40 hours" in _text(ps.pdf(s, ctx["biz"]))


# ─── Sending ──────────────────────────────────────────────────────────

@pytest.fixture
def mail(monkeypatch):
    sent = []

    async def fake(**kw):
        sent.append(kw)
        return {"id": "re_1"}
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake)
    return sent


def test_each_person_gets_their_own_statement_at_their_own_address(db, mail):
    nobody = uid()
    db.rows("employees").append({"id": nobody, "business_id": CHURCH, "first_name": "Lucia", "last_name": "Ortega",
                                 "status": "active", "pay_type": "salary", "pay_rate": 26000.0,
                                 "pay_frequency": "biweekly", "email": ""})
    this = run(db, "2026-11-30", "paid", lines=standard_lines() + [{"employee_id": nobody, "fit": 0.0, "sit": 0.0}])
    out = ps.send(ps.load(this, _biz(db)))
    assert out == {"sent": 2, "skipped": [{"name": "Lucia Ortega", "why": "no email address on file"}]}
    assert sorted(m["to_email"] for m in mail) == ["dana@graceharbor.example", "marcus@graceharbor.example"]
    m = next(x for x in mail if x["to_email"] == "dana@graceharbor.example")
    assert m["from_name"] == "Grace Harbor Church" and m["business_id"] == CHURCH and m["reply_to"] is None
    assert m["subject"] == "Your pay statement for Nov 30, 2026"
    att = m["attachments"][0]
    assert att["content_type"] == "application/pdf" and att["filename"].endswith(".pdf")
    assert base64.b64decode(att["content"])[:5] == b"%PDF-"
    assert "4321" not in m["body"] and "$" not in m["body"]          # the body carries no numbers


def test_only_the_lines_named_are_sent_and_one_failure_never_stops_the_rest(db, monkeypatch, caplog):
    this = run(db, "2026-11-30", "paid", lines=standard_lines())
    ctx = ps.load(this, _biz(db))
    dana_item = next(i for i in ctx["items"] if i["employee_id"] == STAFF)
    calls = []

    async def flaky(**kw):
        calls.append(kw["to_email"])
        if kw["to_email"].startswith("marcus"):
            raise RuntimeError("Resend 500")
        return {}
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", flaky)
    assert ps.send(ctx, only=[str(dana_item["id"])]) == {"sent": 1, "skipped": []}
    assert calls == ["dana@graceharbor.example"]
    caplog.set_level(logging.INFO)
    out = ps.send(ps.load(this, _biz(db)))
    assert out["sent"] == 1 and out["skipped"] == [{"name": "Marcus Ellwood", "why": "the email didn’t go; try again"}]
    for never in ("marcus@", "dana@", "Ellwood", "Reyes", "1,657", "1657"):
        assert never not in caplog.text, never


def test_a_sample_church_sends_nothing(db, monkeypatch):
    import email_sender
    import sample_church

    async def refused(**kw):
        raise sample_church.SendRefused("email", "a sample church sends nothing")
    monkeypatch.setattr(email_sender, "send_via_resend", refused)
    this = run(db, "2026-11-30", "paid", lines=standard_lines())
    out = ps.send(ps.load(this, _biz(db)))
    assert out["sent"] == 0 and {s["why"] for s in out["skipped"]} == {"a sample church sends nothing"}


@pytest.mark.parametrize("mode, platform, on", [
    ("off", True, False), ("owner", False, False), ("owner", True, True), ("on", False, True),
    (None, False, True), ("sideways", True, False)])
def test_the_switch(monkeypatch, db, mode, platform, on):
    import member_asks
    if mode is None:
        monkeypatch.delenv("PAYROLL_STUB_EMAIL", raising=False)
    else:
        monkeypatch.setenv("PAYROLL_STUB_EMAIL", mode)
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: platform)
    assert ps.auto_on(CHURCH) is on
