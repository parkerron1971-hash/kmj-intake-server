"""Physical inventory management — stock, movements, alerts, verbs.

The contract under test:
  • the adjust endpoint is manager+ (member 403), cross-tenant offering
    ids read as 404, delta/set both floor at zero, set-null disables
    tracking and delta on an untracked offering is refused;
  • EVERY stock change drops a stock_adjusted row on the event spine —
    manual adjustments AND the paid-order sale decrement (no new tables);
  • the low-stock chief_notification fires exactly ONCE, on the sale
    that crosses the per-offering threshold from above to at/below;
  • the storefront flags units_left for tracked items at/below their
    threshold (default 5 when none is set);
  • check_inventory / adjust_stock are registered, classified (read /
    class C), and their returns carry the result+label house contract.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"
OTHER_BIZ = "b2"
OFF_TEE = "off_tee"          # tracked physical product
OFF_MUG = "off_mug"          # untracked product
OFF_SERVICE = "off_service"  # not sellable
OFF_FOREIGN = "off_foreign"  # other business's product


def _user(uid: str):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


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
        "settings": {}, "stripe_account_id": "acct_1"})
    fb.rows("businesses").append({
        "id": OTHER_BIZ, "owner_id": "owner2", "name": "Other", "settings": {}})
    fb.rows("business_users").append({
        "id": "seat_m", "business_id": BIZ, "user_id": "member1",
        "role": "member", "status": "active"})
    fb.rows("business_users").append({
        "id": "seat_g", "business_id": BIZ, "user_id": "manager1",
        "role": "manager", "status": "active"})
    fb.rows("business_users").append({
        "id": "seat_v", "business_id": BIZ, "user_id": "viewer1",
        "role": "viewer", "status": "active"})
    fb.rows("offerings").append({
        "id": OFF_TEE, "business_id": BIZ, "name": "Blueprint Tee",
        "category": "product", "is_active": True, "current_price": 25,
        "sku": "TEE-1", "inventory_qty": 10})
    fb.rows("offerings").append({
        "id": OFF_MUG, "business_id": BIZ, "name": "Mug",
        "category": "product", "is_active": True, "current_price": 15,
        "inventory_qty": None})
    fb.rows("offerings").append({
        "id": OFF_SERVICE, "business_id": BIZ, "name": "Coaching",
        "category": "session", "is_active": True, "current_price": 100})
    fb.rows("offerings").append({
        "id": OFF_FOREIGN, "business_id": OTHER_BIZ, "name": "Not yours",
        "category": "product", "is_active": True, "current_price": 5,
        "inventory_qty": 3})
    return fb


def _stock_events(fb):
    return [e for e in fb.rows("events")
            if e.get("event_type") == "stock_adjusted"]


def _adjust(uid, biz=BIZ, offering=OFF_TEE, **kw):
    import store_router
    body = store_router.InventoryAdjustBody(**kw)
    return store_router.adjust_inventory(biz, offering, body, user=_user(uid))


# ─── Adjust: auth matrix ─────────────────────────────────────────────

def test_member_cannot_adjust_manager_can(fake):
    with pytest.raises(HTTPException) as e:
        _adjust("member1", mode="delta", amount=5)
    assert e.value.status_code == 403
    out = _adjust("manager1", mode="delta", amount=5, reason="restock")
    assert out["ok"] is True and out["inventory_qty"] == 15


def test_cross_tenant_offering_is_404(fake):
    # owner1 IS an owner — but the offering belongs to another business.
    with pytest.raises(HTTPException) as e:
        _adjust("owner1", offering=OFF_FOREIGN, mode="delta", amount=1)
    assert e.value.status_code == 404
    # A stranger to the business is refused before the offering is read.
    with pytest.raises(HTTPException) as e:
        _adjust("owner2", mode="delta", amount=1)
    assert e.value.status_code == 403


def test_non_sellable_category_refused(fake):
    with pytest.raises(HTTPException) as e:
        _adjust("owner1", offering=OFF_SERVICE, mode="set", amount=5)
    assert e.value.status_code == 400


# ─── Adjust: delta vs set vs floor vs tracking ───────────────────────

def test_delta_set_and_floor_at_zero(fake):
    assert _adjust("owner1", mode="delta", amount=-4)["inventory_qty"] == 6
    assert _adjust("owner1", mode="set", amount=20)["inventory_qty"] == 20
    # Floor at zero on both paths.
    assert _adjust("owner1", mode="delta", amount=-999)["inventory_qty"] == 0
    assert _adjust("owner1", mode="set", amount=-3)["inventory_qty"] == 0
    with pytest.raises(HTTPException) as e:
        _adjust("owner1", mode="upsert", amount=1)
    assert e.value.status_code == 400


def test_enable_and_disable_tracking(fake):
    # delta on an untracked offering is refused with guidance.
    with pytest.raises(HTTPException) as e:
        _adjust("owner1", offering=OFF_MUG, mode="delta", amount=5)
    assert e.value.status_code == 409
    # set turns tracking ON…
    out = _adjust("owner1", offering=OFF_MUG, mode="set", amount=12)
    assert out["tracked"] is True and out["inventory_qty"] == 12
    # …and set-null turns it OFF.
    out = _adjust("owner1", offering=OFF_MUG, mode="set", amount=None)
    assert out["tracked"] is False and out["inventory_qty"] is None
    mug = [o for o in fake.rows("offerings") if o["id"] == OFF_MUG][0]
    assert mug["inventory_qty"] is None


# ─── Movement history: the spine, both writers ───────────────────────

def test_adjust_emits_stock_event(fake):
    _adjust("manager1", mode="delta", amount=25, reason="restock arrived")
    evs = _stock_events(fake)
    assert len(evs) == 1
    d = evs[0]["data"]
    assert d["offering_id"] == OFF_TEE
    assert d["offering_name"] == "Blueprint Tee"
    assert d["delta"] == 25 and d["new_qty"] == 35
    assert d["reason"] == "restock arrived"
    assert d["actor"] == "manager1@x.com"
    assert evs[0]["business_id"] == BIZ


def _seed_paid_order(fb, order_id="ord1", qty=2):
    fb.rows("orders").append({
        "id": order_id, "business_id": BIZ, "status": "pending",
        "paid_at": None, "total_cents": 5000,
        "customer_email": None, "customer_name": None})
    fb.rows("order_items").append({
        "id": f"oi_{order_id}", "order_id": order_id,
        "offering_id": OFF_TEE, "name_at_purchase": "Blueprint Tee",
        "unit_amount_cents": 2500, "quantity": qty})


@pytest.fixture
def quiet_side_effects(monkeypatch):
    """mark_order_paid's receipt thread + push are out of scope here."""
    import store_router
    monkeypatch.setattr(store_router, "_send_receipt_async", lambda oid: None)
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_business",
                        lambda *a, **k: None)


def test_sale_decrement_emits_stock_event(fake, quiet_side_effects):
    import store_router
    _seed_paid_order(fake, qty=2)
    store_router.mark_order_paid("ord1", payment_intent_id="pi_1", charge_id=None)
    tee = [o for o in fake.rows("offerings") if o["id"] == OFF_TEE][0]
    assert tee["inventory_qty"] == 8
    evs = _stock_events(fake)
    assert len(evs) == 1
    d = evs[0]["data"]
    assert d["delta"] == -2 and d["new_qty"] == 8
    assert d["actor"] == "sale"
    assert d["reason"] == "order ord1"[:14]
    # Idempotent: a second webhook for the same order changes nothing.
    store_router.mark_order_paid("ord1", payment_intent_id="pi_1", charge_id=None)
    assert len(_stock_events(fake)) == 1
    assert [o for o in fake.rows("offerings") if o["id"] == OFF_TEE][0][
        "inventory_qty"] == 8


def test_untracked_item_sale_emits_nothing(fake, quiet_side_effects):
    import store_router
    fake.rows("orders").append({
        "id": "ord2", "business_id": BIZ, "status": "pending", "paid_at": None,
        "total_cents": 1500})
    fake.rows("order_items").append({
        "id": "oi_m", "order_id": "ord2", "offering_id": OFF_MUG,
        "name_at_purchase": "Mug", "unit_amount_cents": 1500, "quantity": 1})
    store_router.mark_order_paid("ord2", payment_intent_id=None, charge_id=None)
    assert _stock_events(fake) == []


# ─── Low-stock alert: exactly once, on the crossing sale ─────────────

def _low_stock_notes(fb):
    return [n for n in fb.rows("chief_notifications")
            if n.get("type") == "low_stock"]


def test_low_stock_fires_once_on_crossing(fake, quiet_side_effects):
    import store_router
    fake.rows("businesses")[0]["settings"] = {
        "store": {"low_stock": {OFF_TEE: 5}}}
    # Sale 1: 10 → 4 crosses the threshold of 5 → ONE notification.
    _seed_paid_order(fake, "ord1", qty=6)
    store_router.mark_order_paid("ord1", payment_intent_id=None, charge_id=None)
    notes = _low_stock_notes(fake)
    assert len(notes) == 1
    assert "Blueprint Tee" in notes[0]["title"]
    assert "4 left" in notes[0]["title"]
    assert notes[0]["data"]["threshold"] == 5
    # Sale 2: 4 → 3 is already below — the crossing edge IS the dedupe.
    _seed_paid_order(fake, "ord2", qty=1)
    store_router.mark_order_paid("ord2", payment_intent_id=None, charge_id=None)
    assert len(_low_stock_notes(fake)) == 1
    # Restock above the threshold, then dip again → legitimately re-alerts.
    _adjust("owner1", mode="set", amount=9, reason="restock")
    _seed_paid_order(fake, "ord3", qty=5)
    store_router.mark_order_paid("ord3", payment_intent_id=None, charge_id=None)
    assert len(_low_stock_notes(fake)) == 2


def test_no_threshold_no_alert(fake, quiet_side_effects):
    import store_router
    _seed_paid_order(fake, "ord1", qty=9)   # 10 → 1, no threshold configured
    store_router.mark_order_paid("ord1", payment_intent_id=None, charge_id=None)
    assert _low_stock_notes(fake) == []


# ─── GET inventory: roles, shape, movements ──────────────────────────

def test_get_inventory_member_ok_viewer_403(fake):
    import store_router
    with pytest.raises(HTTPException) as e:
        store_router.get_inventory(BIZ, user=_user("viewer1"))
    assert e.value.status_code == 403
    _adjust("manager1", mode="delta", amount=-6, reason="damaged")
    fake.rows("businesses")[0]["settings"] = {
        "store": {"low_stock": {OFF_TEE: 5}}}
    out = store_router.get_inventory(BIZ, user=_user("member1"))
    assert out["ok"] is True
    by_id = {i["id"]: i for i in out["items"]}
    assert set(by_id) == {OFF_TEE, OFF_MUG}          # sellable only
    tee = by_id[OFF_TEE]
    assert tee["tracked"] is True and tee["inventory_qty"] == 4
    assert tee["threshold"] == 5 and tee["low_stock"] is True
    assert tee["sku"] == "TEE-1"
    mug = by_id[OFF_MUG]
    assert mug["tracked"] is False and mug["low_stock"] is False
    assert out["movements"][0]["reason"] == "damaged"
    assert out["default_threshold"] == 5


def test_threshold_endpoint_sets_and_clears(fake):
    import store_router
    with pytest.raises(HTTPException) as e:
        store_router.set_inventory_threshold(
            BIZ, OFF_TEE, store_router.InventoryThresholdBody(threshold=3),
            user=_user("member1"))
    assert e.value.status_code == 403
    out = store_router.set_inventory_threshold(
        BIZ, OFF_TEE, store_router.InventoryThresholdBody(threshold=3),
        user=_user("manager1"))
    assert out["threshold"] == 3
    assert fake.rows("businesses")[0]["settings"]["store"]["low_stock"] == {
        OFF_TEE: 3}
    out = store_router.set_inventory_threshold(
        BIZ, OFF_TEE, store_router.InventoryThresholdBody(threshold=None),
        user=_user("manager1"))
    assert out["threshold"] is None
    assert fake.rows("businesses")[0]["settings"]["store"]["low_stock"] == {}


# ─── Storefront: units_left ──────────────────────────────────────────

def test_flag_low_stock_units_left(fake):
    import store_router
    biz = {"settings": {"store": {"low_stock": {"a": 10}}}}
    items = [
        {"id": "a", "inventory_qty": 7},    # ≤ explicit 10 → flagged
        {"id": "b", "inventory_qty": 3},    # ≤ default 5 → flagged
        {"id": "c", "inventory_qty": 6},    # above default → not flagged
        {"id": "d", "inventory_qty": None}, # untracked → never
        {"id": "e", "inventory_qty": 0},    # sold out ≠ "only 0 left"
    ]
    store_router._flag_low_stock(items, biz)
    assert [i["units_left"] for i in items] == [7, 3, None, None, None]


def test_store_page_shows_only_x_left():
    from store_page import render_store_page
    items = [{"id": "a", "name": "Tee", "current_price": 25, "in_stock": True,
              "units_left": 3, "instant_download": False},
             {"id": "b", "name": "Mug", "current_price": 15, "in_stock": False,
              "units_left": None, "instant_download": False}]
    html = render_store_page("slug", {"id": "b1", "name": "S", "settings": {}},
                             items, {"tax_rate_pct": 0, "flat_shipping_cents": 0})
    assert "Only 3 left" in html
    assert "Sold out" in html


# ─── Chief verbs: registration, classification, shape ────────────────

def test_verbs_registered_and_classified():
    import action_registry
    from chief_of_staff import ACTION_HANDLERS
    assert "check_inventory" in ACTION_HANDLERS
    assert "adjust_stock" in ACTION_HANDLERS
    assert action_registry.effect("check_inventory") == "read"
    assert action_registry.reversibility("adjust_stock") == "C"
    assert not action_registry.is_autonomy_eligible("adjust_stock")
    assert action_registry.may_expose_to_agent("check_inventory")
    assert not action_registry.may_expose_to_agent("adjust_stock",
                                                   allow_writes=True)


def test_stock_adjusted_event_is_cataloged():
    import event_spine
    assert "stock_adjusted" in event_spine.EVENT_CATALOG


def test_check_inventory_read_shape(fake):
    import chief_inventory_actions as inv
    out = asyncio.run(inv.handle_check_inventory(
        None, {"id": BIZ, "settings": {}}, {}))
    assert out["type"] == "check_inventory"
    assert not out.get("failed")
    assert "Blueprint Tee" in out["result"] and "10" in out["result"]
    assert "1 untracked" in out["result"]
    assert out.get("label")
    # Nothing was written by the read.
    assert fake.rows("events") == []


def test_check_inventory_flags_low_and_out(fake):
    import chief_inventory_actions as inv
    fake.rows("businesses")[0]["settings"] = {
        "store": {"low_stock": {OFF_TEE: 12}}}
    out = asyncio.run(inv.handle_check_inventory(None, {"id": BIZ}, {}))
    assert out["low_stock"] == ["Blueprint Tee (10 left)"]
    tee = [o for o in fake.rows("offerings") if o["id"] == OFF_TEE][0]
    tee["inventory_qty"] = 0
    out = asyncio.run(inv.handle_check_inventory(None, {"id": BIZ}, {}))
    assert out["out_of_stock"] == ["Blueprint Tee"]
    assert "OUT OF STOCK" in out["result"]


def test_adjust_stock_delta_set_floor_and_event(fake):
    import chief_inventory_actions as inv
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_TEE, "mode": "delta", "amount": 15,
        "reason": "restock"}))
    assert not out.get("failed")
    assert out["inventory_qty"] == 25
    assert out.get("label") and "result" in out
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_TEE, "mode": "delta", "amount": -100}))
    assert out["inventory_qty"] == 0                  # floor
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_TEE, "mode": "set", "amount": 7}))
    assert out["inventory_qty"] == 7
    evs = _stock_events(fake)
    assert len(evs) == 3
    assert all(e["data"]["actor"] == "chief" for e in evs)
    assert evs[0]["data"]["reason"] == "restock"


def test_adjust_stock_failures_carry_flag(fake):
    import chief_inventory_actions as inv
    # Unknown offering.
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": "nope", "mode": "set", "amount": 5}))
    assert out.get("failed") is True and out.get("label")
    # Cross-tenant id must not resolve.
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_FOREIGN, "mode": "set", "amount": 5}))
    assert out.get("failed") is True
    # delta on untracked → guided refusal.
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_MUG, "mode": "delta", "amount": 5}))
    assert out.get("failed") is True and "set" in out["result"]
    # Bad amount.
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_TEE, "mode": "set", "amount": "many"}))
    assert out.get("failed") is True
    # Non-sellable category.
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "offering_id": OFF_SERVICE, "mode": "set", "amount": 5}))
    assert out.get("failed") is True
    assert _stock_events(fake) == []                  # nothing was written


def test_adjust_stock_resolves_by_name(fake, monkeypatch):
    import chief_inventory_actions as inv
    import chief_of_staff as cos

    async def fake_find(client, biz_id, name):
        rows = [o for o in fake.rows("offerings")
                if o["business_id"] == biz_id
                and name.lower() in (o.get("name") or "").lower()]
        return rows[0] if rows else None
    monkeypatch.setattr(cos, "_find_offering_by_name", fake_find)
    out = asyncio.run(inv.handle_adjust_stock(None, {"id": BIZ}, {
        "name": "blueprint", "mode": "delta", "amount": 5}))
    assert not out.get("failed")
    assert out["inventory_qty"] == 15
