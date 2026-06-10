"""Phase I.6 — accountant exports: IIF structure + balance, year-end ZIP
contents, deterministic summary email. Runs on a real backfilled fake ledger."""
from __future__ import annotations

import io
import sys
import pathlib
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

from test_i2_gl_sync import FakeSB
import gl_engine as gl
import accountant_export as ax


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    fb.rows("plaid_accounts").append({
        "account_id": "acc1", "business_id": "biz1", "type": "depository",
        "included_in_bookkeeping": True, "deleted_at": None, "last_balance": 5000})
    fb.t["invoices"] = [{"id": "inv1", "business_id": "biz1", "total": 1000, "status": "paid",
                         "paid_at": "2026-06-01T00:00:00Z", "sent_at": "2026-05-20T00:00:00Z",
                         "created_at": "2026-05-20T00:00:00Z", "due_date": "2026-06-01",
                         "payment_method": "Stripe", "stripe_payment_url": "x",
                         "refund_amount_cents": None, "refunded_at": None,
                         "invoice_number": "A", "contact_id": None, "contacts": None}]
    fb.t["business_expenses"] = [{"id": "e1", "business_id": "biz1", "amount": 150,
                                  "category": "operating", "subcategory": "software",
                                  "vendor": "SaaS", "date": "2026-06-04"}]
    gl.backfill("biz1", "consultant")
    return fb


def test_iif_structure_and_balance(fake):
    iif = ax.build_iif("biz1", 2026)
    lines = iif.strip().split("\n")
    # Header sections present.
    assert lines[0].startswith("!ACCNT\tNAME\tACCNTTYPE")
    assert any(l.startswith("!TRNS\t") for l in lines)
    assert any(l.startswith("!ENDTRNS") for l in lines)
    # Account definitions include our COA with QB types.
    assert any(l == "ACCNT\tAccounts Receivable\tAR" for l in lines)
    assert any(l == "ACCNT\tCash - Operating\tBANK" for l in lines)
    # Every transaction block balances to zero (debits positive / credits negative).
    total = 0.0
    blocks = 0
    block_sum = 0.0
    for l in lines:
        if l.startswith(("TRNS\t", "SPL\t")):
            block_sum += float(l.split("\t")[4])
        elif l == "ENDTRNS":
            assert round(block_sum, 2) == 0.0
            total += block_sum
            block_sum = 0.0
            blocks += 1
    assert blocks >= 2          # at least the invoice events + expense
    # Dates are MM/DD/YYYY.
    trns = next(l for l in lines if l.startswith("TRNS\t"))
    date = trns.split("\t")[2]
    assert len(date.split("/")) == 3 and len(date) == 10


def test_iif_excludes_reversal_noise(fake):
    fb = fake
    # Edit the expense → reverse + repost in the GL.
    exp = fb.rows("business_expenses")[0]
    exp["amount"] = 175
    coa = gl.ensure_chart_of_accounts("biz1", "consultant")
    gl.process_source_row("biz1", "business_expenses", "e1", coa, set())
    iif = ax.build_iif("biz1", 2026)
    # The reversal pair is excluded — only ONE expense transaction, at 175.
    assert iif.count("\t175.00\t") >= 1 and "reversal" not in iif.lower()
    # The old amount is gone (tab-delimited exact match; 5150.00 opening ≠ 150.00).
    assert "\t150.00\t" not in iif and "\t-150.00\t" not in iif


def test_package_zip_contents(fake):
    pytest.importorskip("reportlab")
    blob, reports = ax.build_package_zip("biz1", "KMJ", None, 2026, generated_by="kevin@x.com")
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = set(z.namelist())
    for expected in ("2026_pl.pdf", "2026_balance_sheet.pdf", "2026_cash_flow.pdf",
                     "2026_trial_balance.pdf", "2026_general_ledger.pdf",
                     "2026_general_ledger.csv", "2026_trial_balance.csv",
                     "2026_general_ledger.iif", "README.txt"):
        assert expected in names, f"missing {expected}"
    # PDFs are real PDFs.
    assert z.read("2026_pl.pdf")[:5] == b"%PDF-"
    # README carries the headline numbers.
    readme = z.read("README.txt").decode("utf-8")
    assert "Gross revenue" in readme and "Net income" in readme


def test_summary_email_numbers(fake):
    reports = ax._package_reports("biz1", 2026)
    subject, body = ax.summary_email("KMJ", 2026, reports)
    assert "2026 year-end financial package" in subject
    assert "$1,000.00" in body          # gross revenue (paid invoice)
    assert "Trial balance: in balance" in body
