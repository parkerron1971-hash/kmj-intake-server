"""Phase H.1 — Bills (AP) — focused logic tests (Supabase mocked)."""
from __future__ import annotations

import sys
import pathlib
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import bills_router as br
import reports_engine as re_


def test_recurrence_stepping_and_month_clamp():
    assert br._step(date(2026, 1, 1), "weekly", 2) == date(2026, 1, 15)
    assert br._step(date(2026, 1, 1), "biweekly", 1) == date(2026, 1, 15)
    assert br._step(date(2026, 1, 15), "monthly", 2) == date(2026, 3, 15)
    assert br._step(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)   # clamp
    assert br._step(date(2026, 1, 1), "quarterly", 1) == date(2026, 4, 1)
    assert br._step(date(2026, 1, 1), "annually", 1) == date(2027, 1, 1)


def test_create_bill_validates(monkeypatch):
    from fastapi import HTTPException
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [{"id": "biz1", "owner_id": "owner"}])

    class _U:
        id = "owner"

    # bad category
    with pytest.raises(HTTPException) as e1:
        br.create_bill(br.BillBody(business_id="biz1", vendor_name="X", amount=10, category="bogus"), user=_U())
    assert e1.value.status_code == 400
    # recurring without frequency
    with pytest.raises(HTTPException) as e2:
        br.create_bill(br.BillBody(business_id="biz1", vendor_name="X", amount=10, is_recurring=True), user=_U())
    assert e2.value.status_code == 400


def test_ap_aging_buckets_by_vendor(monkeypatch):
    import sb_clients
    today = re_._today()

    def _fake_get(path):
        if path.startswith("/bills"):
            return [
                {"id": "1", "vendor_name": "Rent Co", "amount": 2500, "status": "pending",
                 "due_date": (today + timedelta(days=5)).isoformat()},          # current
                {"id": "2", "vendor_name": "SaaS Inc", "amount": 99, "status": "overdue",
                 "due_date": (today - timedelta(days=40)).isoformat()},          # 31-60
                {"id": "3", "vendor_name": "SaaS Inc", "amount": 99, "status": "overdue",
                 "due_date": (today - timedelta(days=100)).isoformat()},         # 90+ (at-risk)
            ]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    out = re_.ap_aging("biz1")
    assert out["buckets"]["current"] == 2500
    assert out["buckets"]["d31_60"] == 99
    assert out["buckets"]["d90_plus"] == 99
    assert out["total_outstanding"] == 2698
    assert out["at_risk"] == 99
    saas = next(v for v in out["by_vendor"] if v["vendor"] == "SaaS Inc")
    assert saas["total"] == 198 and saas["count"] == 2


def test_balance_sheet_includes_ap(monkeypatch):
    import sb_clients

    def _fake_get(path):
        if "type=eq.depository" in path:
            return [{"last_balance": 10000}]
        if path.startswith("/invoices"):
            return [{"id": "i1", "invoice_number": "A", "total": 2000, "status": "sent",
                     "due_date": None, "refund_amount_cents": None, "contacts": {"name": "X"}}]
        if path.startswith("/bills"):
            return [{"id": "b1", "vendor_name": "V", "amount": 1500, "status": "pending", "due_date": None}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _fake_get)
    out = re_.balance_sheet("biz1")
    assert out["assets"]["total"] == 12000           # cash 10000 + AR 2000
    assert out["liabilities"]["accounts_payable"] == 1500
    assert out["equity"]["retained_earnings"] == 10500  # 12000 − 1500
