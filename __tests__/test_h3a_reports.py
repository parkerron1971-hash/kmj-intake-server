"""Phase H.3a — Reports engine — focused logic tests (Supabase mocked)."""
from __future__ import annotations

import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import reports_engine as re_


def test_period_bounds_quarter_and_month():
    # this_quarter starts on a calendar-quarter boundary month.
    s, e = re_.period_bounds("this_quarter")
    assert s.month in (1, 4, 7, 10) and s.day == 1
    # last_month is a full prior calendar month.
    s, e = re_.period_bounds("last_month")
    assert s.day == 1 and e >= s and (e + __import__("datetime").timedelta(days=1)).day == 1


def test_comparison_previous_is_equal_length_window():
    s, e = date(2026, 6, 1), date(2026, 6, 30)
    cs, ce = re_.comparison_bounds(s, e, "previous")
    assert ce == s - __import__("datetime").timedelta(days=1)
    assert (e - s).days == (ce - cs).days


def test_pct_change_handles_zero_prior():
    assert re_._pct_change(10, 0) is None       # no NaN/inf
    assert re_._pct_change(150, 100) == 50.0


def test_ar_aging_buckets_and_refund_exclusion(monkeypatch):
    import sb_clients
    today = re_._today()

    def _fake_get(path):
        if path.startswith("/invoices"):
            return [
                # not due yet → current
                {"id": "1", "invoice_number": "A", "total": 100, "status": "sent",
                 "due_date": (today + __import__("datetime").timedelta(days=10)).isoformat(),
                 "refund_amount_cents": None, "contacts": {"name": "Alice"}},
                # 45 days overdue → 31_60, at-risk? no (31_60 not at-risk)
                {"id": "2", "invoice_number": "B", "total": 200, "status": "overdue",
                 "due_date": (today - __import__("datetime").timedelta(days=45)).isoformat(),
                 "refund_amount_cents": None, "contacts": {"name": "Bob"}},
                # 120 days overdue → 90_plus (at-risk)
                {"id": "3", "invoice_number": "C", "total": 300, "status": "overdue",
                 "due_date": (today - __import__("datetime").timedelta(days=120)).isoformat(),
                 "refund_amount_cents": None, "contacts": {"name": "Bob"}},
                # fully refunded → excluded entirely
                {"id": "4", "invoice_number": "D", "total": 50, "status": "sent",
                 "due_date": today.isoformat(), "refund_amount_cents": 5000,
                 "contacts": {"name": "Carol"}},
            ]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    out = re_.ar_aging("biz1")
    assert out["buckets"]["current"] == 100
    assert out["buckets"]["d31_60"] == 200
    assert out["buckets"]["d90_plus"] == 300
    assert out["total_outstanding"] == 600          # refunded $50 excluded
    assert out["at_risk"] == 300                     # only 61-90 + 90+
    # Bob aggregates two invoices.
    bob = next(c for c in out["by_contact"] if c["contact"] == "Bob")
    assert bob["total"] == 500 and bob["count"] == 2


def test_pl_revenue_and_expense_assembly(monkeypatch):
    import sb_clients

    def _fake_get(path):
        if path.startswith("/invoices"):
            return [{"total": 1000, "paid_at": "2026-06-05T00:00:00Z",
                     "refund_amount_cents": None, "refunded_at": None}]
        if path.startswith("/plaid_accounts"):
            return [{"account_id": "acc1"}]
        if path.startswith("/plaid_transactions"):
            return [
                # expense outflow (positive), operating
                {"amount": 300, "business_category": "operating", "business_subcategory": "software",
                 "plaid_category_primary": "GENERAL_SERVICES", "plaid_category_detail": None,
                 "reconciled_to_payout_id": None},
                # non-Stripe income inflow (negative), income-categorized
                {"amount": -200, "business_category": None, "business_subcategory": None,
                 "plaid_category_primary": "INCOME", "plaid_category_detail": "INCOME_WAGES",
                 "reconciled_to_payout_id": None},
            ]
        if path.startswith("/business_expenses"):
            return [{"amount": 50, "category": "operating", "subcategory": "rent"}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    res = re_.profit_and_loss("biz1", "this_month")
    cur = res["current"]
    # Revenue = invoiced 1000 + non-Stripe income 200.
    assert cur["revenue"]["invoiced"] == 1000
    assert cur["revenue"]["plaid_other_income"] == 200
    assert cur["revenue"]["gross_revenue"] == 1200
    # Expenses = 300 (plaid) + 50 (manual) in operating bucket.
    assert cur["expenses"]["total"] == 350
    op = next(b for b in cur["expenses"]["by_bucket"] if b["bucket"] == "operating")
    assert op["total"] == 350
    assert cur["net_income"] == 850


def test_balance_sheet_lite_equation(monkeypatch):
    import sb_clients

    def _fake_get(path):
        if "type=eq.depository" in path:
            return [{"last_balance": 5000}]
        if path.startswith("/invoices"):
            return [{"id": "1", "invoice_number": "A", "total": 800, "status": "sent",
                     "due_date": None, "refund_amount_cents": None, "contacts": {"name": "X"}}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    out = re_.balance_sheet("biz1")
    assert out["assets"]["cash"] == 5000
    assert out["assets"]["accounts_receivable"] == 800
    assert out["assets"]["total"] == 5800
    assert out["liabilities"]["accounts_payable"] == 0
    assert out["equity"]["retained_earnings"] == 5800  # Cash + AR − AP
