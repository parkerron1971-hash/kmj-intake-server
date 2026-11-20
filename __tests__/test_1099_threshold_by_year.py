"""The 1099-NEC line by tax year, everywhere it is said (form_1099.nec_threshold):
$2,000 for payments made in 2026 and later, $600 before (Instructions for
Forms 1099-MISC and 1099-NEC, 2026). The 1099 summary, the drafts, the CSV
export's column, the summary PDF, the accountant's cover email and the year
worksheet all ask the one helper. Made-up names and figures only.
"""
from __future__ import annotations

import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import form_1099
import reports_router as rr
from payroll_free_fake import CHURCH, PayrollFake, install, seed, uid


@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    for year, amount in ((2025, 1500.0), (2026, 1500.0), (2026, 900.0)):
        db.rows("bills").append({"id": uid(), "business_id": CHURCH, "status": "paid", "is_1099_eligible": True,
                                 "paid_at": f"{year}-06-01T12:00:00Z", "paid_amount": amount, "amount": amount,
                                 "vendor_name": "Ellis Sound Co", "contractor_id": None})
    return db


def test_the_one_helper():
    assert form_1099.nec_threshold(2025) == 600.0 and form_1099.nec_threshold(2026) == 2000.0
    assert form_1099.nec_threshold(2031) == 2000.0 and form_1099.nec_threshold("2024") == 600.0
    assert form_1099.nec_threshold_words(2025) == "$600" and form_1099.nec_threshold_words(2026) == "$2,000"
    import payroll_forms
    assert payroll_forms.nec_threshold(2025) == 600.0 and payroll_forms.nec_threshold(2026) == 2000.0


def test_the_summary_uses_the_tax_years_line(db):
    s25, s26 = rr._summary_1099(CHURCH, 2025), rr._summary_1099(CHURCH, 2026)
    assert s25["threshold"] == 600.0 and s25["rows"][0]["total_paid"] == 1500.0
    assert s25["rows"][0]["reaches_threshold"] is True and s25["threshold_count"] == 1
    assert "2025 line of $600" in s25["note"]
    assert s26["threshold"] == 2000.0 and s26["rows"][0]["total_paid"] == 2400.0
    assert s26["rows"][0]["reaches_threshold"] is True
    db.rows("bills")[:] = [b for b in db.rows("bills") if b["paid_amount"] != 900.0]
    s26 = rr._summary_1099(CHURCH, 2026)
    assert s26["rows"][0]["total_paid"] == 1500.0 and s26["rows"][0]["reaches_threshold"] is False
    assert s26["threshold_count"] == 0 and "2026 line of $2,000" in s26["note"]


def test_the_export_column_and_the_pdf_say_the_years_line(db):
    rows25 = rr._csv_rows("summary_1099", rr._summary_1099(CHURCH, 2025))
    rows26 = rr._csv_rows("summary_1099", rr._summary_1099(CHURCH, 2026))
    assert rows25[0][3] == "Reaches $600" and rows26[0][3] == "Reaches $2,000"
    import pdf_reports
    import pypdf
    db.rows("bills")[:] = [b for b in db.rows("bills") if b["paid_amount"] != 900.0]
    meta = pdf_reports.build_meta(business_name="Grace Harbor Church", settings=None, report_title="1099 Summary",
                                  period_label="2026", basis_label="Cash Basis", currency="USD", generated_by="test")
    pdf = pdf_reports.render("summary_1099", rr._summary_1099(CHURCH, 2026), meta)
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "Below $2,000 threshold" in text and "$600" not in text


def test_the_accountants_cover_email_says_the_years_line():
    import accountant_export
    _subject, body25 = accountant_export.summary_email("Grace Harbor Church", 2025, {"summary_1099": {
        "threshold_count": 1}})
    _subject, body26 = accountant_export.summary_email("Grace Harbor Church", 2026, {"summary_1099": {
        "threshold_count": 0}})
    assert "1099 contractors at/above $600: 1" in body25
    assert "1099 contractors at/above $2,000: 0" in body26


def test_the_drafts_choose_and_say_the_same_line(db, monkeypatch):
    import types
    monkeypatch.setattr(rr, "_pay_records_wall", lambda *a, **k: None)
    monkeypatch.setattr(rr, "_payer_block", lambda b: {"name": "Grace Harbor Church", "ein": "", "line1": "",
                                                        "line2": "", "city_state_zip": "", "phone": "",
                                                        "complete": False})
    import billing_limits
    monkeypatch.setattr(billing_limits, "require_feature", lambda *a, **k: None)
    owner = types.SimpleNamespace(id=next(b for b in db.rows("businesses") if b["id"] == CHURCH)["owner_id"])
    d25 = rr.drafts_1099(CHURCH, 2025, user=owner)
    d26 = rr.drafts_1099(CHURCH, 2026, user=owner)
    assert d25["threshold"] == 600.0 and len(d25["rows"]) == 1 and "($600)" in d25["note"]
    assert d26["threshold"] == 2000.0 and len(d26["rows"]) == 1 and "($2,000)" in d26["note"]
    src = pathlib.Path(rr.__file__).read_text(encoding="utf-8")
    assert ">= 600.0" not in src and "Reaches $600" not in src
