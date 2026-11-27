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
    # biz1 is the platform owner's own business; a test takes it out to
    # play another business.
    fb.platform = {"biz1"}
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: str(biz) in fb.platform)
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

def test_another_business_cannot_pay_from_the_platform_balance(fake, stripe_ok):
    import asyncio
    from fastapi import HTTPException
    fake.platform.clear()
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.pay("con1", cr.PayBody(business_id="biz1", amount=300), request=_request(), user=_U()))
    assert e.value.status_code == 403
    assert "own bank" in e.value.detail
    assert stripe_ok == []                              # Stripe never called
    assert fake.rows("outbound_transfers") == []        # nothing recorded
    assert fake.rows("bills") == []


def test_another_business_cannot_open_a_payout_account(fake, stripe_ok):
    import asyncio
    from fastapi import HTTPException
    fake.platform.clear()
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


def test_contractor_records_stay_open_to_every_business(fake):
    fake.platform.clear()
    out = cr.list_contractors("biz1", user=_U())
    assert out["ok"] and out["contractors"][0]["id"] == "con1"


# ─── Bills linked to a 1099 person (M-6, 2026-11-27) ─────────────────

SPEAKER = "5f0c2a1e-1b7d-4c3e-9a8b-2d4e6f8a0b1c"


def _speaker(fake, biz="biz1"):
    fake.rows("contractors").append({"id": SPEAKER, "business_id": biz, "name": "Rev. Ada Brooks",
                                     "email": None, "stripe_account_id": None, "onboarding_status": "invited",
                                     "is_1099_eligible": True, "default_category": "operating"})


def _bill(fake, vendor, amount, *, is1099=True, contractor=None, biz="biz1"):
    fake.rows("bills").append({"id": f"bill-{len(fake.rows('bills')) + 1:03d}", "business_id": biz,
                               "vendor_name": vendor, "amount": amount, "paid_amount": amount, "status": "paid",
                               "paid_at": "2026-05-03T12:00:00Z", "is_1099_eligible": is1099,
                               "contractor_id": contractor})


def test_typed_in_speaker_bills_link_to_the_contractor_and_count_for_their_1099(fake):
    """The review's dead end: a guest speaker paid by check, entered as a
    1099 bill, got 'Manual 1099 needed' and could never get a W-9 or draft."""
    _speaker(fake)
    _bill(fake, "Rev. Ada Brooks", 1500.0)
    _bill(fake, "  rev. ada brooks ", 900.0)                 # same name, other case and spaces
    _bill(fake, "Rev. Ada Brooks", 50.0, is1099=False)       # not a 1099 bill: left alone
    _bill(fake, "Office Depot", 300.0)                       # someone else: left alone
    _bill(fake, "Rev. Ada Brooks", 700.0, biz="biz2")        # another business: never touched
    before = {r["name"]: r for r in _summary_1099("biz1", 2026)["rows"]}
    assert before["Rev. Ada Brooks"]["contractor_id"] is None
    out = cr.link_bills(SPEAKER, cr.LinkBillsBody(business_id="biz1", vendor_name="Rev. Ada Brooks"), user=_U())
    assert out == {"ok": True, "linked": 2}
    linked = {b["id"] for b in fake.rows("bills") if b.get("contractor_id") == SPEAKER}
    assert len(linked) == 2 and all(b["business_id"] == "biz1" for b in fake.rows("bills") if b["id"] in linked)
    row = {r["name"]: r for r in _summary_1099("biz1", 2026)["rows"]}["Rev. Ada Brooks"]
    assert row["contractor_id"] == SPEAKER and row["total_paid"] == 2400.0 and row["reaches_threshold"] is True
    assert row["stripe_managed"] is False                  # a manual 1099: the drafts can now be made
    # Twice is harmless: nothing left to link.
    again = cr.link_bills(SPEAKER, cr.LinkBillsBody(business_id="biz1", vendor_name="Rev. Ada Brooks"), user=_U())
    assert again["linked"] == 0


def test_link_bills_refuses_another_business_and_a_blank_name(fake):
    from fastapi import HTTPException
    _speaker(fake)
    with pytest.raises(HTTPException) as e:
        cr.link_bills(SPEAKER, cr.LinkBillsBody(business_id="biz2", vendor_name="Rev. Ada Brooks"), user=_U())
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        cr.link_bills(SPEAKER, cr.LinkBillsBody(business_id="biz1", vendor_name="  "), user=_U())
    assert e.value.status_code == 400


def test_a_bill_names_its_contractor_only_if_it_is_this_business_s(fake):
    from fastapi import HTTPException
    import bills_router as br
    _speaker(fake)
    assert br._contractor_of("biz1", None) is None and br._contractor_of("biz1", "") is None
    assert br._contractor_of("biz1", SPEAKER)["name"] == "Rev. Ada Brooks"
    for bad, code in (("con1", 400), ("not-a-uuid&business_id=eq.x", 400),
                      ("00000000-0000-4000-8000-000000000000", 400)):
        with pytest.raises(HTTPException) as e:
            br._contractor_of("biz1", bad)
        assert e.value.status_code == code, bad
    with pytest.raises(HTTPException) as e:
        br._contractor_of("biz2", SPEAKER)                   # another business's contractor
    assert e.value.status_code == 400


def test_a_new_bill_for_a_contractor_is_linked_and_1099_and_can_be_unlinked(fake, monkeypatch):
    import bills_router as br
    import period_lock
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    _speaker(fake)
    out = br.create_bill(br.BillBody(business_id="biz1", vendor_name="Rev. Ada Brooks", amount=400,
                                     status="paid", contractor_id=SPEAKER), user=_U())
    bill = out["bill"]
    assert bill["contractor_id"] == SPEAKER and bill["is_1099_eligible"] is True
    br.update_bill(bill["id"], br.BillPatchBody(business_id="biz1", contractor_id=""), user=_U())
    row = next(b for b in fake.rows("bills") if b["id"] == bill["id"])
    assert row["contractor_id"] is None
    # A bill without one is as before.
    plain = br.create_bill(br.BillBody(business_id="biz1", vendor_name="Office Depot", amount=30), user=_U())["bill"]
    assert "contractor_id" not in plain and plain["is_1099_eligible"] is False


def test_a_stripe_paid_contractor_takes_no_typed_in_bills(fake):
    """Account-2 review S3: the 1099 summary marks a contractor with a Stripe
    account as Stripe's whole, and Stripe's 1099 counts only Stripe transfers,
    so a check-paid bill linked to them would be on no 1099. Refused, plainly."""
    from fastapi import HTTPException
    import bills_router as br
    jane = "8a9b0c1d-2e3f-4a5b-8c6d-7e8f9a0b1c2d"
    fake.rows("contractors").append({"id": jane, "business_id": "biz1", "name": "Jane Dev", "email": None,
                                     "stripe_account_id": "acct_jane2", "onboarding_status": "active",
                                     "is_1099_eligible": True, "default_category": "operating"})
    _bill(fake, "Jane Dev", 500.0)
    with pytest.raises(HTTPException) as e:
        cr.link_bills(jane, cr.LinkBillsBody(business_id="biz1", vendor_name="Jane Dev"), user=_U())
    assert e.value.status_code == 409 and "paid through Stripe" in e.value.detail
    assert all(b.get("contractor_id") is None for b in fake.rows("bills"))
    with pytest.raises(HTTPException) as e:
        br._contractor_of("biz1", jane)
    assert e.value.status_code == 409 and "stays typed in under their name" in e.value.detail
    # The typed-in bill still reaches the report as a manual row.
    row = {r["name"]: r for r in _summary_1099("biz1", 2026)["rows"]}["Jane Dev"]
    assert row["contractor_id"] is None and row["stripe_managed"] is False
