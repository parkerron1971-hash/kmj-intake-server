"""Phase F.1 — contractor payments: pay flow (Stripe transfer mocked) →
auto AP bill → GL booking, 1099 summary aggregation, guard rails."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

from test_i2_gl_sync import FakeSB
import gl_engine as gl
import gl_reports as glr
import contractors_router as cr
from reports_router import _summary_1099


class _U:
    id = "owner"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    fb.rows("contractors").append({
        "id": "con1", "business_id": "biz1", "name": "Jane Dev", "email": "jane@x.com",
        "stripe_account_id": "acct_jane", "onboarding_status": "active",
        "is_1099_eligible": True, "default_category": "operating", "onboarded_at": "2026-01-01"})
    return fb


@pytest.fixture
def stripe_ok(monkeypatch):
    calls = []

    async def _fake_post(path, data):
        calls.append((path, data))
        return {"id": "tr_test123", "object": "transfer"}
    monkeypatch.setattr(cr, "_stripe_post", _fake_post)
    return calls


def test_pay_creates_transfer_bill_and_gl(fake, stripe_ok):
    import asyncio
    out = asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=850.0,
                                                description="June sprint"), user=_U()))
    assert out["ok"] and out["transfer_id"] == "tr_test123"
    # Stripe called with cents + Express destination + D.4 metadata pattern.
    path, data = stripe_ok[0]
    assert path == "/transfers" and data["amount"] == 85000
    assert data["destination"] == "acct_jane"
    assert data["metadata[source_type]"] == "contractor_payment"
    # outbound_transfers row finalized.
    ot = fake.rows("outbound_transfers")[0]
    assert ot["status"] == "paid" and ot["stripe_transfer_id"] == "tr_test123"
    # Auto AP bill: PAID, 1099-eligible, contractor-linked, stripe_transfer.
    bill = fake.rows("bills")[0]
    assert bill["status"] == "paid" and bill["is_1099_eligible"] is True
    assert bill["contractor_id"] == "con1" and bill["paid_via"] == "stripe_transfer"
    assert ot["bill_id"] == bill["id"]
    # GL converge on the bill: Dr Expense/Cr AP + Dr AP/Cr Cash; AP nets 0.
    coa = gl.ensure_chart_of_accounts("biz1", "consultant")
    gl.process_source_row("biz1", "bills", bill["id"], coa, set())
    lines = glr.effective_lines("biz1")
    assert gl.gl_ap(lines) == 0.0                      # issued + paid nets out
    exp = sum(float(l["debit"]) for l in lines if l["account_type"] == "expense")
    assert exp == 850.0
    assert gl.trial_balance(lines)["difference"] == 0.0


def test_pay_blocked_until_onboarded(fake, stripe_ok):
    import asyncio
    from fastapi import HTTPException
    fake.rows("contractors")[0]["onboarding_status"] = "pending"
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=100), user=_U()))
    assert e.value.status_code == 409
    assert fake.rows("outbound_transfers") == []        # nothing recorded


def test_stripe_failure_marks_transfer_failed(fake, monkeypatch):
    import asyncio
    from fastapi import HTTPException

    async def _fail(path, data):
        raise HTTPException(502, "insufficient platform balance")
    monkeypatch.setattr(cr, "_stripe_post", _fail)
    with pytest.raises(HTTPException):
        asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=100), user=_U()))
    ot = fake.rows("outbound_transfers")[0]
    assert ot["status"] == "failed" and "insufficient" in ot["failure_message"]
    assert fake.rows("bills") == []                     # no bill on failure


def test_1099_summary_aggregates_and_thresholds(fake, stripe_ok):
    import asyncio
    asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=450.0), user=_U()))
    asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=250.0), user=_U()))
    # Plus a manual 1099-eligible vendor bill (no contractor).
    fake.rows("bills").append({
        "id": "mb1", "business_id": "biz1", "vendor_name": "Freelance Bob", "amount": 200,
        "paid_amount": 200, "category": "operating", "status": "paid",
        "is_1099_eligible": True, "contractor_id": None, "paid_at": "2026-03-03T00:00:00Z"})
    out = _summary_1099("biz1", 2026)
    by_name = {r["name"]: r for r in out["rows"]}
    jane = by_name["Jane Dev"]
    assert jane["total_paid"] == 700.0 and jane["payments"] == 2
    assert jane["reaches_threshold"] is True and jane["stripe_managed"] is True
    bob = by_name["Freelance Bob"]
    assert bob["total_paid"] == 200.0 and bob["reaches_threshold"] is False
    assert bob["stripe_managed"] is False
    assert out["total_paid"] == 900.0 and out["threshold_count"] == 1
