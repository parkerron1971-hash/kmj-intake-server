"""THE REORDER BRAIN — sweep, PO composition, verbs, and the guard.

The contract under test:
  • tripped() trips only offerings at/below their reorder point with no
    outstanding PO;
  • compose_purchase_order() carries qty, item, SKU, and the business
    name — one composer for preview and send;
  • the sweep raises ONE alert per business, worst item first, with a
    draft_purchase_order action_payload the notification tap dispatches;
  • set_reorder_plan patches only the fields given, validates the email,
    and clearing the reorder point retires the pending marker;
  • draft_purchase_order writes NOTHING and refuses without a supplier;
  • send_purchase_order emails the supplier, stamps reorder_pending_at,
    and refuses a second send while one is outstanding unless forced;
  • a restock past the reorder point clears the pending marker (both
    the helper and Chief's adjust_stock path);
  • the three verbs are registered and classified (A / read / C) and
    send_purchase_order sits in policy_engine.CLIENT_FACING.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"
OTHER_BIZ = "b2"
OFF_TEE = "off_tee"      # tracked, full reorder plan, tripped (3 <= 5)
OFF_MUG = "off_mug"      # tracked, plan, NOT tripped (20 > 5)
OFF_CAP = "off_cap"      # tracked, plan but no supplier, tripped
OFF_SERVICE = "off_service"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)

    fb.rows("businesses").append({
        "id": BIZ, "owner_id": "owner1", "name": "Studio One",
        "is_active": True, "settings": {}})
    fb.rows("offerings").append({
        "id": OFF_TEE, "business_id": BIZ, "name": "Blueprint Tee",
        "category": "product", "is_active": True, "current_price": 25,
        "sku": "TEE-1", "inventory_qty": 3, "reorder_at": 5,
        "reorder_qty": 25, "supplier_name": "Acme Apparel",
        "supplier_email": "orders@acme.com", "reorder_pending_at": None})
    fb.rows("offerings").append({
        "id": OFF_MUG, "business_id": BIZ, "name": "Mug",
        "category": "product", "is_active": True, "current_price": 15,
        "inventory_qty": 20, "reorder_at": 5, "reorder_qty": 10,
        "supplier_email": "mugs@acme.com", "reorder_pending_at": None})
    fb.rows("offerings").append({
        "id": OFF_CAP, "business_id": BIZ, "name": "Cap",
        "category": "product", "is_active": True, "current_price": 18,
        "inventory_qty": 1, "reorder_at": 4, "reorder_qty": None,
        "supplier_name": None, "supplier_email": None,
        "reorder_pending_at": None})
    fb.rows("offerings").append({
        "id": OFF_SERVICE, "business_id": BIZ, "name": "Coaching",
        "category": "session", "is_active": True, "current_price": 100})
    return fb


def _tee(fb):
    return [o for o in fb.rows("offerings") if o["id"] == OFF_TEE][0]


# ─── pure pieces ─────────────────────────────────────────────────────

def test_tripped_filters():
    from reorder_engine import tripped
    rows = [
        {"inventory_qty": 3, "reorder_at": 5},                 # trips
        {"inventory_qty": 5, "reorder_at": 5},                 # at point trips
        {"inventory_qty": 6, "reorder_at": 5},                 # above — no
        {"inventory_qty": 0, "reorder_at": 5,
         "reorder_pending_at": "2026-08-18T00:00:00Z"},        # on order — no
        {"inventory_qty": None, "reorder_at": 5},              # untracked — no
        {"inventory_qty": 2},                                  # no point — no
    ]
    assert [r.get("inventory_qty") for r in tripped(rows)] == [3, 5]


def test_compose_purchase_order():
    from reorder_engine import compose_purchase_order
    po = compose_purchase_order(
        {"name": "Studio One"},
        {"id": "abcdef12", "name": "Blueprint Tee", "sku": "TEE-1",
         "supplier_name": "Acme Apparel", "supplier_email": "orders@acme.com"},
        25)
    assert po["to_email"] == "orders@acme.com"
    assert po["po_number"].startswith("PO-") and "ABCDEF" in po["po_number"]
    assert "25 x Blueprint Tee" in po["subject"] and "Studio One" in po["subject"]
    for needle in ("Hello Acme Apparel,", "Quantity: 25", "SKU: TEE-1",
                   "Studio One"):
        assert needle in po["body"]


def test_clear_pending_only_past_the_point(fake):
    from reorder_engine import clear_reorder_pending_if_restocked
    tee = _tee(fake)
    tee["reorder_pending_at"] = "2026-08-18T00:00:00Z"
    # Restock to 4 — still at/below the point of 5: marker stays.
    assert clear_reorder_pending_if_restocked(BIZ, OFF_TEE, 4) is False
    assert _tee(fake)["reorder_pending_at"]
    # Restock to 30 — past the point: marker clears.
    assert clear_reorder_pending_if_restocked(BIZ, OFF_TEE, 30) is True
    assert _tee(fake)["reorder_pending_at"] is None
    # No marker → no-op.
    assert clear_reorder_pending_if_restocked(BIZ, OFF_TEE, 50) is False


# ─── the sweep ───────────────────────────────────────────────────────

def test_sweep_one_alert_per_business_worst_first(fake, monkeypatch):
    import notification_engine as ne
    import reorder_engine as re_
    calls = []

    async def fake_alert(client, bid, **kw):
        calls.append((bid, kw))
        return {"id": "n1"}

    async def fake_active(client):
        return [BIZ]

    monkeypatch.setattr(ne, "create_urgent_alert", fake_alert)
    monkeypatch.setattr(ne, "_all_active_business_ids", fake_active)
    monkeypatch.setattr(ne, "_within_waking_hours", lambda now=None: True)

    out = asyncio.run(re_.low_stock_reorder_sweep())
    # Tee (3<=5) and Cap (1<=4) trip; Mug doesn't. One alert, not two.
    assert out["alerts"] == 1 and out["low"] == 2
    bid, kw = calls[0]
    assert bid == BIZ
    assert "2 products" in kw["title"]
    # Worst = furthest below its point: Cap at 1-4 = -3 vs Tee 3-5 = -2.
    assert kw["action_payload"] == {"type": "draft_purchase_order",
                                    "offering_id": OFF_CAP}
    assert kw["dedup_key"] == f"reorder:{BIZ}"


def test_sweep_respects_pending_and_quiet_hours(fake, monkeypatch):
    import notification_engine as ne
    import reorder_engine as re_
    calls = []

    async def fake_alert(client, bid, **kw):
        calls.append(bid)
        return {"id": "n1"}

    async def fake_active(client):
        return [BIZ]

    monkeypatch.setattr(ne, "create_urgent_alert", fake_alert)
    monkeypatch.setattr(ne, "_all_active_business_ids", fake_active)

    monkeypatch.setattr(ne, "_within_waking_hours", lambda now=None: False)
    out = asyncio.run(re_.low_stock_reorder_sweep())
    assert out.get("skipped") == "quiet_hours" and not calls

    monkeypatch.setattr(ne, "_within_waking_hours", lambda now=None: True)
    for o in fake.rows("offerings"):
        o["reorder_pending_at"] = "2026-08-18T00:00:00Z"
    out = asyncio.run(re_.low_stock_reorder_sweep())
    assert out["alerts"] == 0 and not calls


# ─── verbs ───────────────────────────────────────────────────────────

def test_set_reorder_plan_patches_and_validates(fake):
    import chief_inventory_actions as inv
    out = asyncio.run(inv.handle_set_reorder_plan(None, {"id": BIZ}, {
        "offering_id": OFF_CAP, "reorder_at": 6, "reorder_qty": 12,
        "supplier_name": "Cap Co", "supplier_email": "po@capco.com"}))
    assert not out.get("failed") and out.get("label") and out.get("result")
    cap = [o for o in fake.rows("offerings") if o["id"] == OFF_CAP][0]
    assert (cap["reorder_at"], cap["reorder_qty"]) == (6, 12)
    assert cap["supplier_email"] == "po@capco.com"

    out = asyncio.run(inv.handle_set_reorder_plan(None, {"id": BIZ}, {
        "offering_id": OFF_CAP, "supplier_email": "not-an-address"}))
    assert out.get("failed") is True

    out = asyncio.run(inv.handle_set_reorder_plan(None, {"id": BIZ}, {
        "offering_id": OFF_SERVICE, "reorder_at": 5}))
    assert out.get("failed") is True     # not a store product

    # Clearing the point retires the pending marker with it.
    cap["reorder_pending_at"] = "2026-08-18T00:00:00Z"
    out = asyncio.run(inv.handle_set_reorder_plan(None, {"id": BIZ}, {
        "offering_id": OFF_CAP, "reorder_at": None}))
    assert not out.get("failed")
    assert cap["reorder_at"] is None and cap["reorder_pending_at"] is None


def test_draft_po_is_pure_and_guided(fake):
    import chief_inventory_actions as inv
    before = [dict(o) for o in fake.rows("offerings")]
    out = asyncio.run(inv.handle_draft_purchase_order(
        None, {"id": BIZ, "name": "Studio One"}, {"offering_id": OFF_TEE}))
    assert not out.get("failed")
    assert out["po"]["qty"] == 25                     # plan default
    assert "orders@acme.com" in out["result"]
    assert "Quantity: 25" in out["result"]
    assert fake.rows("offerings") == before           # wrote NOTHING

    # No supplier on file → guided refusal, not a silent draft to nobody.
    out = asyncio.run(inv.handle_draft_purchase_order(
        None, {"id": BIZ, "name": "Studio One"}, {"offering_id": OFF_CAP}))
    assert out.get("failed") is True and "supplier" in out["result"]

    # qty override beats the plan.
    out = asyncio.run(inv.handle_draft_purchase_order(
        None, {"id": BIZ, "name": "Studio One"},
        {"offering_id": OFF_TEE, "qty": 40}))
    assert out["po"]["qty"] == 40


def test_send_po_stamps_guard_and_refuses_duplicates(fake, monkeypatch):
    import chief_inventory_actions as inv
    import email_sender
    sent = []

    async def fake_send(**kw):
        sent.append(kw)
        return {"id": "email_1"}

    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(email_sender, "build_routed_reply_to",
                        lambda b, c: "reply+b1+anon@in.test")

    out = asyncio.run(inv.handle_send_purchase_order(
        None, {"id": BIZ, "name": "Studio One"}, {"offering_id": OFF_TEE}))
    assert not out.get("failed") and out.get("label")
    assert len(sent) == 1
    kw = sent[0]
    assert kw["to_email"] == "orders@acme.com"
    assert kw["business_id"] == BIZ                   # business identity
    assert kw["reply_to"] == "reply+b1+anon@in.test"  # replies route back
    assert _tee(fake)["reorder_pending_at"]           # guard stamped

    # Second send while outstanding → refused without force.
    out = asyncio.run(inv.handle_send_purchase_order(
        None, {"id": BIZ, "name": "Studio One"}, {"offering_id": OFF_TEE}))
    assert out.get("failed") is True and len(sent) == 1
    out = asyncio.run(inv.handle_send_purchase_order(
        None, {"id": BIZ, "name": "Studio One"},
        {"offering_id": OFF_TEE, "force": True}))
    assert not out.get("failed") and len(sent) == 2

    # No supplier → refused, nothing sent.
    out = asyncio.run(inv.handle_send_purchase_order(
        None, {"id": BIZ, "name": "Studio One"}, {"offering_id": OFF_CAP}))
    assert out.get("failed") is True and len(sent) == 2


def test_chief_restock_clears_pending(fake):
    import chief_inventory_actions as inv
    tee = _tee(fake)
    tee["reorder_pending_at"] = "2026-08-18T00:00:00Z"
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_TEE, "mode": "delta", "amount": 25,
        "reason": "restock arrived"}))
    assert not out.get("failed") and out["inventory_qty"] == 28
    assert _tee(fake)["reorder_pending_at"] is None


# ─── registry + policy ───────────────────────────────────────────────

def test_verbs_registered_and_classified():
    import action_registry as ar
    import policy_engine
    assert ar.classification("set_reorder_plan")["reversibility"] == "A"
    assert ar.classification("draft_purchase_order")["effect"] == "read"
    send = ar.classification("send_purchase_order")
    assert send["reversibility"] == "C"
    assert "send_purchase_order" in policy_engine.CLIENT_FACING
    assert not ar.is_bulk("send_purchase_order")
