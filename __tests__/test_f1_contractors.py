"""Phase F.1 — contractor payments: pay flow (Stripe transfer mocked) →
auto AP bill → GL booking, 1099 summary aggregation, guard rails."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest
from starlette.requests import Request
import ledger_unlock


def _request():
    # A danger unlock is for one business (ledger_unlock, 2026-11-18).
    token = ledger_unlock.mint('owner', scope=ledger_unlock.SCOPE_DANGER, business_id='biz1')['token']
    return Request({'type': 'http', 'headers': [(b'x-ledger-unlock', token.encode())]})

from test_i2_gl_sync import FakeSB
import gl_engine as gl
import gl_reports as glr
import contractors_router as cr
from reports_router import _summary_1099


class _U:
    id = "owner"


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(ledger_unlock, '_secret', lambda: b'test-financial-step-up-key')
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
    # biz1 is named in CONTRACTOR_PAYOUT_BUSINESS_IDS (M-6); a test unsets
    # it to play any other business.
    monkeypatch.setenv(cr.PAYOUT_IDS_ENV, "biz1")
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
                                                description="June sprint"), request=_request(), user=_U()))
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
        asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=100), request=_request(), user=_U()))
    assert e.value.status_code == 409
    assert fake.rows("outbound_transfers") == []        # nothing recorded


def test_stripe_failure_marks_transfer_failed(fake, monkeypatch):
    import asyncio
    from fastapi import HTTPException

    async def _fail(path, data):
        raise HTTPException(502, "insufficient platform balance")
    monkeypatch.setattr(cr, "_stripe_post", _fail)
    with pytest.raises(HTTPException):
        asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=100), request=_request(), user=_U()))
    ot = fake.rows("outbound_transfers")[0]
    assert ot["status"] == "failed" and "insufficient" in ot["failure_message"]
    assert fake.rows("bills") == []                     # no bill on failure


def test_1099_summary_aggregates_and_thresholds(fake, stripe_ok):
    import asyncio
    asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=450.0), request=_request(), user=_U()))
    asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=250.0), request=_request(), user=_U()))
    # Plus a manual 1099-eligible vendor bill (no contractor).
    fake.rows("bills").append({
        "id": "mb1", "business_id": "biz1", "vendor_name": "Freelance Bob", "amount": 200,
        "paid_amount": 200, "category": "operating", "status": "paid",
        "is_1099_eligible": True, "contractor_id": None, "paid_at": "2026-03-03T00:00:00Z"})
    out = _summary_1099("biz1", 2026)
    by_name = {r["name"]: r for r in out["rows"]}
    jane = by_name["Jane Dev"]
    assert jane["total_paid"] == 700.0 and jane["payments"] == 2
    # 2026's 1099-NEC line is $2,000 (form_1099.nec_threshold): $700 is under it.
    assert out["threshold"] == 2000.0
    assert jane["reaches_threshold"] is False and jane["stripe_managed"] is True
    bob = by_name["Freelance Bob"]
    assert bob["total_paid"] == 200.0 and bob["reaches_threshold"] is False
    assert bob["stripe_managed"] is False
    assert out["total_paid"] == 900.0 and out["threshold_count"] == 0
    asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=1400.0), request=_request(), user=_U()))
    jane = {r["name"]: r for r in _summary_1099("biz1", 2026)["rows"]}["Jane Dev"]
    assert jane["total_paid"] == 2100.0 and jane["reaches_threshold"] is True


# ─── Locked to the platform owner's businesses (2026-10-31) ──────────

def test_another_business_cannot_pay_from_the_platform_balance(fake, monkeypatch, stripe_ok):
    import asyncio
    from fastapi import HTTPException
    monkeypatch.delenv(cr.PAYOUT_IDS_ENV, raising=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=300), request=_request(), user=_U()))
    assert e.value.status_code == 403
    assert "own bank" in e.value.detail
    assert stripe_ok == []                              # Stripe never called
    assert fake.rows("outbound_transfers") == []        # nothing recorded
    assert fake.rows("bills") == []


def test_another_business_cannot_open_a_payout_account(fake, monkeypatch, stripe_ok):
    import asyncio
    from fastapi import HTTPException
    monkeypatch.delenv(cr.PAYOUT_IDS_ENV, raising=False)
    fake.rows("contractors")[0].update(stripe_account_id=None, onboarding_status="none")
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.onboarding_link("con1", user=_U()))
    assert e.value.status_code == 403
    assert stripe_ok == []
    assert fake.rows("contractors")[0]["stripe_account_id"] is None


@pytest.mark.parametrize("path", ["/transfers", "/accounts"])
def test_stripe_post_refuses_platform_money_for_another_business(fake, monkeypatch, path):
    """The last check before Stripe: even a new caller that forgot the
    route check can't spend the platform balance for someone else."""
    import asyncio
    from fastapi import HTTPException

    def _no_network(*a, **k):
        pytest.fail("reached Stripe")
    monkeypatch.setattr(cr.httpx, "AsyncClient", _no_network)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr._stripe_post(path, {"metadata[business_id]": "someone-else"}))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr._stripe_post(path, {}))           # no business named: a no
    assert e.value.status_code == 403


def test_contractor_records_stay_open_to_every_business(fake, monkeypatch):
    monkeypatch.delenv(cr.PAYOUT_IDS_ENV, raising=False)
    out = cr.list_contractors("biz1", user=_U())
    assert out["ok"] and out["contractors"][0]["id"] == "con1"
    assert out["payouts"] == {"stripe": False}          # the app offers no Pay button


# ─── Locked to an explicit list, never a church (M-6, 2026-11-27) ─────

def _refused(call, status=403):
    import asyncio
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(call)
    assert e.value.status_code == status
    return e.value


def test_the_owner_being_the_platform_owner_is_no_longer_enough(fake, monkeypatch, stripe_ok):
    """The 10-31 lock asked member_asks.platform_church: any business whose
    OWNER is the platform owner. That let Love City Church spend
    Solutionist's balance. The owner's email no longer counts at all."""
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: True)
    monkeypatch.delenv(cr.PAYOUT_IDS_ENV, raising=False)
    _refused(cr.pay("con1", cr.PayBody(business_id="biz1", amount=300), request=_request(), user=_U()))
    _refused(cr.onboarding_link("con1", user=_U()))
    assert stripe_ok == [] and fake.rows("outbound_transfers") == [] and fake.rows("bills") == []
    assert cr.list_contractors("biz1", user=_U())["payouts"] == {"stripe": False}


@pytest.mark.parametrize("kind", ["church", "ministry", "nonprofit"])
def test_a_church_is_refused_even_when_named(fake, monkeypatch, kind):
    """A church's or nonprofit's money is its own: named in the list by
    mistake, it still never spends the platform balance, at every door."""
    fake.rows("businesses")[0]["type"] = kind
    monkeypatch.setenv(cr.PAYOUT_IDS_ENV, "biz1")

    def _no_network(*a, **k):
        pytest.fail("reached Stripe")
    monkeypatch.setattr(cr.httpx, "AsyncClient", _no_network)
    err = _refused(cr.pay("con1", cr.PayBody(business_id="biz1", amount=300), request=_request(), user=_U()))
    assert "own bank" in err.detail
    for path in ("/transfers", "/accounts"):
        _refused(cr._stripe_post(path, {"metadata[business_id]": "biz1"}))
    assert fake.rows("outbound_transfers") == [] and fake.rows("bills") == []
    assert cr.payouts_open("biz1") is False


def test_unset_or_empty_list_means_nobody(fake, monkeypatch):
    for raw in (None, "", "  ,  "):
        if raw is None:
            monkeypatch.delenv(cr.PAYOUT_IDS_ENV, raising=False)
        else:
            monkeypatch.setenv(cr.PAYOUT_IDS_ENV, raw)
        assert cr.payout_business_ids() == set()
        assert cr.payouts_open("biz1") is False


def test_the_list_takes_ids_in_any_case_and_separator(fake, monkeypatch):
    bid = "7b1f2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    fake.rows("businesses").append({"id": bid, "type": "consultant", "owner_id": "owner"})
    monkeypatch.setenv(cr.PAYOUT_IDS_ENV, f" other-id ,{bid.upper()}  ")
    assert cr.payouts_open(bid) is True
    assert cr.payouts_open(bid.upper()) is True
    assert cr.payouts_open("biz1") is False             # not named


def test_a_business_that_cannot_be_read_is_a_no(fake, monkeypatch, stripe_ok):
    import sb_clients
    real = sb_clients.sb_get_as_service

    def _blip(path, *a, **k):
        if path.startswith("/businesses?id=eq.biz1&select=id,type"):
            raise RuntimeError("supabase down")
        return real(path, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _blip)
    err = _refused(cr.pay("con1", cr.PayBody(business_id="biz1", amount=300), request=_request(), user=_U()), 503)
    assert "Nothing was sent" in err.detail
    assert stripe_ok == [] and fake.rows("outbound_transfers") == []
    assert cr.payouts_open("biz1") is False


def test_a_named_business_still_pays(fake, stripe_ok):
    """The one way through: named, readable, and not a church."""
    assert cr.list_contractors("biz1", user=_U())["payouts"] == {"stripe": True}
