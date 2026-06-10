"""Phase I.4 — GL-authoritative reports: parity regression vs H.3a + the new
GL-native reports.

Seeds an in-memory Supabase fake with a full synthetic dataset, runs the GL
backfill into it, then asserts the GL-backed engine produces the SAME numbers
as the H.3a source-table engine (the ruled regression requirement) — including
after an edit cycle (reverse + repost). Also covers the reversal-edit P&L fix,
trial balance, GL detail, journal log, and PDF render of the new reports."""
from __future__ import annotations

import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

from test_i2_gl_sync import FakeSB, _enqueue   # reuse the PostgREST-ish fake
import gl_engine as gl
import gl_reports as glr
import reports_engine as re_


def _seed(fb: FakeSB):
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    fb.rows("plaid_accounts").append({
        "account_id": "acc1", "business_id": "biz1", "type": "depository",
        "included_in_bookkeeping": True, "deleted_at": None, "last_balance": 5000})
    fb.t["invoices"] = [
        {"id": "inv_paid", "business_id": "biz1", "total": 1000, "status": "paid",
         "paid_at": "2026-06-01T00:00:00Z", "sent_at": "2026-05-20T00:00:00Z",
         "created_at": "2026-05-20T00:00:00Z", "due_date": "2026-06-01",
         "payment_method": "Stripe", "stripe_payment_url": "x",
         "refund_amount_cents": None, "refunded_at": None, "invoice_number": "A",
         "contact_id": None, "contacts": None},
        {"id": "inv_open", "business_id": "biz1", "total": 600, "status": "sent",
         "paid_at": None, "sent_at": "2026-06-02T00:00:00Z",
         "created_at": "2026-06-02T00:00:00Z", "due_date": "2026-06-20",
         "payment_method": None, "stripe_payment_url": "x",
         "refund_amount_cents": None, "refunded_at": None, "invoice_number": "B",
         "contact_id": None, "contacts": {"name": "Bob"}},
        {"id": "inv_ref", "business_id": "biz1", "total": 400, "status": "paid",
         "paid_at": "2026-06-03T00:00:00Z", "sent_at": "2026-05-25T00:00:00Z",
         "created_at": "2026-05-25T00:00:00Z", "due_date": "2026-06-03",
         "payment_method": "Stripe", "stripe_payment_url": "x",
         "refund_amount_cents": 4000, "refunded_at": "2026-06-05T00:00:00Z",
         "invoice_number": "C", "contact_id": None, "contacts": None},
        {"id": "inv_draft", "business_id": "biz1", "total": 500, "status": "draft",
         "paid_at": None, "sent_at": None, "created_at": "2026-06-08T00:00:00Z",
         "due_date": "2026-06-25", "payment_method": None, "stripe_payment_url": None,
         "refund_amount_cents": None, "refunded_at": None, "invoice_number": "D",
         "contact_id": None, "contacts": None},
    ]
    fb.t["business_expenses"] = [
        {"id": "exp1", "business_id": "biz1", "amount": 150, "category": "operating",
         "subcategory": "software", "vendor": "SaaS Co", "date": "2026-06-04"},
    ]
    fb.t["bills"] = [
        {"id": "bill_open", "business_id": "biz1", "vendor_name": "Rent Co", "amount": 2500,
         "category": "operating", "subcategory": "rent", "status": "pending",
         "due_date": "2026-06-30", "created_at": "2026-06-01T00:00:00Z",
         "paid_at": None, "paid_amount": None},
        {"id": "bill_paid", "business_id": "biz1", "vendor_name": "Utility", "amount": 200,
         "category": "operating", "subcategory": "utilities", "status": "paid",
         "due_date": "2026-06-05", "created_at": "2026-06-01T00:00:00Z",
         "paid_at": "2026-06-06T00:00:00Z", "paid_amount": 200},
    ]
    fb.t["plaid_transactions"] = [
        {"transaction_id": "px_payout", "business_id": "biz1", "account_id": "acc1",
         "amount": -1000, "date": "2026-06-02", "business_category": None,
         "business_subcategory": None, "plaid_category_primary": "INCOME",
         "plaid_category_detail": None, "reconciled_to_payout_id": "po_1",
         "pending": False, "excluded_from_books": False, "reconciliation_status": "auto_matched"},
        {"transaction_id": "px_income", "business_id": "biz1", "account_id": "acc1",
         "amount": -300, "date": "2026-06-07", "business_category": None,
         "business_subcategory": None, "plaid_category_primary": "INCOME",
         "plaid_category_detail": "INCOME_WAGES", "reconciled_to_payout_id": None,
         "pending": False, "excluded_from_books": False, "reconciliation_status": "unmatched"},
        {"transaction_id": "px_exp", "business_id": "biz1", "account_id": "acc1",
         "amount": 250, "date": "2026-06-08", "business_category": "operating",
         "business_subcategory": "fuel", "plaid_category_primary": "TRANSPORTATION",
         "plaid_category_detail": None, "reconciled_to_payout_id": None,
         "pending": False, "excluded_from_books": False, "reconciliation_status": "unmatched"},
        # I.4 parity edges: uncategorized transfer-in + income-categorized outflow.
        {"transaction_id": "px_xferin", "business_id": "biz1", "account_id": "acc1",
         "amount": -750, "date": "2026-06-09", "business_category": None,
         "business_subcategory": None, "plaid_category_primary": "TRANSFER_IN",
         "plaid_category_detail": None, "reconciled_to_payout_id": None,
         "pending": False, "excluded_from_books": False, "reconciliation_status": "unmatched"},
        {"transaction_id": "px_xferout", "business_id": "biz1", "account_id": "acc1",
         "amount": 120, "date": "2026-06-09", "business_category": None,
         "business_subcategory": None, "plaid_category_primary": "INCOME",
         "plaid_category_detail": "INCOME_DIVIDENDS", "reconciled_to_payout_id": None,
         "pending": False, "excluded_from_books": False, "reconciliation_status": "unmatched"},
    ]


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    _seed(fb)
    gl.backfill("biz1", "consultant")
    return fb


_FROM, _TO = "2000-01-01", "2030-01-01"


def _assert_pl_parity(fb):
    h = re_.profit_and_loss("biz1", "custom", None, _FROM, _TO)["current"]
    g = glr.gl_profit_and_loss("biz1", "custom", None, _FROM, _TO)["current"]
    assert g["revenue"]["invoiced"] == h["revenue"]["invoiced"]
    assert g["revenue"]["refunds"] == h["revenue"]["refunds"]
    assert g["revenue"]["plaid_other_income"] == h["revenue"]["plaid_other_income"]
    assert g["revenue"]["gross_revenue"] == h["revenue"]["gross_revenue"]
    assert g["expenses"]["total"] == h["expenses"]["total"]
    assert g["net_income"] == h["net_income"]
    g_buckets = {b["bucket"]: b["total"] for b in g["expenses"]["by_bucket"]}
    h_buckets = {b["bucket"]: b["total"] for b in h["expenses"]["by_bucket"]}
    assert g_buckets == h_buckets


def test_pl_parity_full_shape(fake):
    _assert_pl_parity(fake)


def test_pl_subcategory_lines_present(fake):
    g = glr.gl_profit_and_loss("biz1", "custom", None, _FROM, _TO)["current"]
    op = next(b for b in g["expenses"]["by_bucket"] if b["bucket"] == "operating")
    subs = {l["subcategory"]: l["amount"] for l in op["lines"]}
    assert subs.get("software") == 150 and subs.get("fuel") == 250


def test_balance_sheet_parity(fake):
    h = re_.balance_sheet("biz1")
    g = glr.gl_balance_sheet("biz1")
    assert g["assets"]["cash"] == h["assets"]["cash"]
    assert g["assets"]["accounts_receivable"] == h["assets"]["accounts_receivable"]
    assert g["assets"]["total"] == h["assets"]["total"]
    assert g["liabilities"]["accounts_payable"] == h["liabilities"]["accounts_payable"]
    assert g["equity"]["retained_earnings"] == h["equity"]["retained_earnings"]


def test_cash_flow_parity_including_transfers(fake):
    h = re_.cash_flow("biz1", "custom", _FROM, _TO)["operating"]
    g = glr.gl_cash_flow("biz1", "custom", _FROM, _TO)["operating"]
    assert g == h
    # The transfer-in must be counted (the I.4 equity-booking fix).
    assert g["cash_from_customers"] == 1000 + 300 + 750
    assert g["cash_to_suppliers"] == 250 + 120


def test_parity_survives_edit_cycle(fake):
    """Edit a source row (reverse + repost in the GL) → both engines still agree."""
    fb = fake
    exp = next(r for r in fb.rows("business_expenses") if r["id"] == "exp1")
    exp["amount"] = 175
    _enqueue(fb, "business_expenses", "exp1", "update")
    gl.process_queue("biz1")
    _assert_pl_parity(fb)
    # And the reversal-edit P&L fix: revenue unchanged, expense reflects 175.
    g = glr.gl_profit_and_loss("biz1", "custom", None, _FROM, _TO)["current"]
    op = next(b for b in g["expenses"]["by_bucket"] if b["bucket"] == "operating")
    assert {l["subcategory"]: l["amount"] for l in op["lines"]}.get("software") == 175


def test_trial_balance_balanced_with_names(fake):
    tb = glr.trial_balance_report("biz1")
    assert tb["totals"]["balanced"] is True
    assert tb["totals"]["difference"] == 0.0
    by_code = {a["code"]: a for a in tb["accounts"]}
    assert by_code["1100"]["name"] == "Accounts Receivable"
    assert by_code["1100"]["balance"] == 600          # the open invoice
    assert by_code["2000"]["balance"] == 2500         # the open bill


def test_general_ledger_running_balance(fake):
    gld = glr.general_ledger_report("biz1", account_code="1100")
    acct = next(a for a in gld["accounts"] if a["code"] == "1100")
    assert acct["opening_balance"] == 0.0
    assert acct["closing_balance"] == 600
    # Running balance is monotone-consistent with the entries.
    assert acct["entries"][-1]["running_balance"] == 600


def test_journal_log_shape(fake):
    j = glr.journal_report("biz1", limit=10)
    assert j["entries"] and all("lines" in e for e in j["entries"])
    # Every journal entry's lines balance.
    for e in j["entries"]:
        assert round(sum(l["debit"] for l in e["lines"]) -
                     sum(l["credit"] for l in e["lines"]), 2) == 0.0


def test_new_report_pdfs_render(fake):
    pytest.importorskip("reportlab")
    import pdf_reports as p
    meta = p.build_meta(business_name="KMJ", settings=None, report_title="Trial Balance",
                        period_label="As of 2026-06-09", generated_by="kevin@x.com")
    pdf = p.render("trial_balance", glr.trial_balance_report("biz1"), meta)
    assert pdf[:5] == b"%PDF-"
    pdf2 = p.render("general_ledger", glr.general_ledger_report("biz1"), meta)
    assert pdf2[:5] == b"%PDF-"
