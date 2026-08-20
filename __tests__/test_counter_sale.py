"""THE TILL — a sale rung up at the counter.

The contract under test:
  • a counter sale IS an order (source='counter'), so it inherits the
    GL mapping, the refund flow, the Orders list and the audit triggers
    rather than growing a second money table;
  • prices come from the CATALOG, never from the client — a till that
    accepts a price off the wire is a till where the price can be
    anything;
  • the discount comes off BEFORE tax, because tax is charged on what
    was actually paid;
  • cash does NOT land in Stripe Clearing. This is the one that quietly
    destroys a set of books: 1150 is cleared by a Stripe payout, and no
    payout is coming for money handed over a counter;
  • a price-less product (the kind a manager adds for stock) cannot be
    sold, because pricing is the owner's decision;
  • the till NEVER refuses a sale for being out of stock — the customer
    is holding the thing — but it says the count was wrong.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import counter_sale as cs  # noqa: E402
import gl_engine  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"
OFF_TEE = "off_tee"          # tracked, priced
OFF_MUG = "off_mug"          # untracked, priced
OFF_FREE = "off_free"        # a manager's stock-only product: NO price
OTHER_BIZ = "b2"
OFF_FOREIGN = "off_foreign"


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
        "settings": {"store": {"tax_rate_pct": 10}}})
    fb.rows("businesses").append({
        "id": OTHER_BIZ, "owner_id": "owner2", "name": "Other", "settings": {}})
    for uid, role in (("member1", "member"), ("manager1", "manager")):
        fb.rows("business_users").append({
            "id": f"seat_{uid}", "business_id": BIZ, "user_id": uid,
            "role": role, "status": "active"})
    fb.rows("offerings").append({
        "id": OFF_TEE, "business_id": BIZ, "name": "Blueprint Tee",
        "category": "product", "is_active": True, "current_price": 25,
        "currency": "usd", "inventory_qty": 10})
    fb.rows("offerings").append({
        "id": OFF_MUG, "business_id": BIZ, "name": "Mug",
        "category": "product", "is_active": True, "current_price": 15,
        "currency": "usd", "inventory_qty": None})
    fb.rows("offerings").append({
        "id": OFF_FREE, "business_id": BIZ, "name": "Unpriced Pomade",
        "category": "product", "is_active": True, "current_price": None,
        "currency": "usd", "inventory_qty": 4})
    fb.rows("offerings").append({
        "id": OFF_FOREIGN, "business_id": OTHER_BIZ, "name": "Not yours",
        "category": "product", "is_active": True, "current_price": 5,
        "currency": "usd", "inventory_qty": 3})
    return fb


def _sell(uid="manager1", biz=BIZ, **kw):
    body = cs.CounterSaleBody(**kw)
    return cs.counter_sale(biz, body, user=_user(uid))


def _line(offering, qty=1):
    return {"offering_id": offering, "quantity": qty}


# ─── The maths ───────────────────────────────────────────────────────


def test_the_discount_comes_off_before_tax():
    # Tax on a price nobody paid is a small wrongness that becomes a
    # real problem at the end of a year.
    t = cs.totals([{"line_cents": 2000}, {"line_cents": 1500}], 500, 10)
    assert t["gross_cents"] == 3500
    assert t["subtotal_cents"] == 3000
    assert t["tax_cents"] == 300          # 10% of 3000, not of 3500
    assert t["total_cents"] == 3300


def test_a_discount_cannot_exceed_the_sale():
    t = cs.totals([{"line_cents": 2000}], 99999, 10)
    assert t["discount_cents"] == 2000
    assert t["subtotal_cents"] == 0 and t["total_cents"] == 0


def test_tax_rounds_to_whole_cents():
    t = cs.totals([{"line_cents": 999}], 0, 8.25)
    assert t["tax_cents"] == 82           # 82.4175 -> 82
    assert isinstance(t["total_cents"], int)


def test_prices_come_from_the_catalog_not_the_caller():
    offerings = {"a": {"name": "Tee", "current_price": 25}}
    priced = cs.price_lines(offerings, [
        {"offering_id": "a", "quantity": 2, "unit_price_cents": 1}])
    assert priced[0]["unit_amount_cents"] == 2500
    assert priced[0]["line_cents"] == 5000


def test_price_lines_survives_a_junk_price():
    offerings = {"a": {"name": "Tee", "current_price": "not a number"}}
    assert cs.price_lines(offerings, [{"offering_id": "a"}])[0]["unit_amount_cents"] == 0


# ─── The books ───────────────────────────────────────────────────────


def _debit_codes(entries):
    return [ln["code"] for e in entries for ln in e["lines"]
            if ln.get("debit")]


def test_cash_does_not_land_in_stripe_clearing():
    # THE ALARM. 1150 is cleared by a Stripe payout. No payout is coming
    # for cash over a counter, so booking it there leaves the clearing
    # account permanently out by every counter sale ever rung up.
    order = {"id": "o1", "status": "paid", "paid_at": "2026-08-20T00:00:00Z",
             "total_cents": 3300, "tax_cents": 300, "shipping_cents": 0,
             "payment_method": "cash"}
    assert _debit_codes(gl_engine.desired_for_order(order)) == ["1000"]


def test_a_store_checkout_still_lands_in_stripe_clearing():
    order = {"id": "o1", "status": "paid", "paid_at": "2026-08-20T00:00:00Z",
             "total_cents": 3300, "tax_cents": 300, "shipping_cents": 0}
    assert _debit_codes(gl_engine.desired_for_order(order)) == ["1150"]
    order["payment_method"] = "stripe"
    assert _debit_codes(gl_engine.desired_for_order(order)) == ["1150"]


def test_a_card_on_their_own_reader_is_not_our_clearing_account():
    order = {"id": "o1", "status": "paid", "paid_at": "2026-08-20T00:00:00Z",
             "total_cents": 1000, "tax_cents": 0, "shipping_cents": 0,
             "payment_method": "card"}
    assert _debit_codes(gl_engine.desired_for_order(order)) == ["1000"]


def test_a_refund_credits_the_account_the_payment_used():
    # Refunding a cash sale against the clearing account would credit an
    # account that never held the money.
    order = {"id": "o1", "status": "refunded", "paid_at": "2026-08-20T00:00:00Z",
             "total_cents": 1000, "tax_cents": 0, "shipping_cents": 0,
             "payment_method": "cash", "refund_amount_cents": 1000,
             "refunded_at": "2026-08-21T00:00:00Z"}
    entries = gl_engine.desired_for_order(order)
    refund = [e for e in entries if e["source_type"] == "order_refund"][0]
    credits = [ln["code"] for ln in refund["lines"] if ln.get("credit")]
    assert credits == ["1000"]


def test_the_ledger_still_balances_for_a_counter_sale():
    order = {"id": "o1", "status": "paid", "paid_at": "2026-08-20T00:00:00Z",
             "total_cents": 3300, "tax_cents": 300, "shipping_cents": 0,
             "payment_method": "cash"}
    for e in gl_engine.desired_for_order(order):
        debits = sum(float(ln.get("debit") or 0) for ln in e["lines"])
        credits = sum(float(ln.get("credit") or 0) for ln in e["lines"])
        assert round(debits, 2) == round(credits, 2)


# ─── The sale, end to end ────────────────────────────────────────────


def test_a_sale_writes_an_order_its_items_and_the_stock_movement(fake):
    out = _sell(lines=[_line(OFF_TEE, 2)], payment_method="cash")
    assert out["ok"] is True

    orders = fake.rows("orders")
    assert len(orders) == 1
    o = orders[0]
    assert o["source"] == "counter" and o["payment_method"] == "cash"
    assert o["status"] == "paid" and o["paid_at"]
    assert o["subtotal_cents"] == 5000 and o["tax_cents"] == 500
    assert o["total_cents"] == 5500
    assert o["shipping_cents"] == 0        # they carried it out

    items = fake.rows("order_items")
    assert len(items) == 1
    assert items[0]["quantity"] == 2 and items[0]["unit_amount_cents"] == 2500

    tee = [x for x in fake.rows("offerings") if x["id"] == OFF_TEE][0]
    assert tee["inventory_qty"] == 8

    moves = [e for e in fake.rows("events") if e["event_type"] == "stock_adjusted"]
    assert len(moves) == 1
    assert moves[0]["data"]["delta"] == -2
    assert "counter sale" in moves[0]["data"]["reason"]
    # Who rang it up, not a faceless "sale".
    assert moves[0]["data"]["actor"] == "manager1@x.com"


def test_scanning_the_same_product_twice_is_a_quantity_not_two_lines(fake):
    out = _sell(lines=[_line(OFF_TEE), _line(OFF_TEE), _line(OFF_TEE)])
    assert len(fake.rows("order_items")) == 1
    assert fake.rows("order_items")[0]["quantity"] == 3
    assert out["totals"]["gross_cents"] == 7500


def test_an_untracked_product_sells_without_a_stock_movement(fake):
    out = _sell(lines=[_line(OFF_MUG)])
    assert out["ok"] is True
    assert [e for e in fake.rows("events")
            if e["event_type"] == "stock_adjusted"] == []
    assert out["lines"][0]["tracked"] is False


def test_selling_more_than_the_count_says_still_sells(fake):
    # The customer is holding it. The shelf is the truth and the count
    # is what is wrong — refusing would be the software arguing with
    # reality.
    out = _sell(lines=[_line(OFF_TEE, 99)])
    assert out["ok"] is True
    tee = [x for x in fake.rows("offerings") if x["id"] == OFF_TEE][0]
    assert tee["inventory_qty"] == 0        # clamped, never negative
    assert out["warnings"] and "Worth a recount" in out["warnings"][0]
    assert out["lines"][0]["oversold"] is True


def test_a_normal_sale_raises_no_warning(fake):
    assert _sell(lines=[_line(OFF_TEE, 2)])["warnings"] == []


def test_a_price_less_product_cannot_be_sold(fake):
    # The manager-created stock product is countable, not sellable.
    # Inventing a price at the till would route around the owner.
    with pytest.raises(HTTPException) as e:
        _sell(lines=[_line(OFF_FREE)])
    assert e.value.status_code == 400
    assert "no price" in str(e.value.detail)
    assert fake.rows("orders") == []        # nothing half-written


def test_another_business_product_is_404(fake):
    with pytest.raises(HTTPException) as e:
        _sell(lines=[_line(OFF_FOREIGN)])
    assert e.value.status_code == 404
    assert fake.rows("orders") == []


def test_a_member_cannot_ring_up_a_sale(fake):
    with pytest.raises(HTTPException) as e:
        _sell(uid="member1", lines=[_line(OFF_TEE)])
    assert e.value.status_code == 403
    assert fake.rows("orders") == []


def test_an_unknown_payment_method_is_refused(fake):
    with pytest.raises(HTTPException) as e:
        _sell(lines=[_line(OFF_TEE)], payment_method="bitcoin")
    assert e.value.status_code == 400
    assert fake.rows("orders") == []


def test_an_empty_sale_is_refused(fake):
    with pytest.raises(HTTPException) as e:
        _sell(lines=[])
    assert e.value.status_code == 400


def test_a_fully_discounted_sale_is_refused(fake):
    # Zero money changing hands is a giveaway, and a giveaway that
    # writes a paid order would put a £0 sale in the revenue reports.
    with pytest.raises(HTTPException) as e:
        _sell(lines=[_line(OFF_TEE)], discount_cents=999999)
    assert e.value.status_code == 400
    assert fake.rows("orders") == []


def test_the_discount_reaches_the_recorded_order(fake):
    out = _sell(lines=[_line(OFF_TEE, 2)], discount_cents=1000)
    o = fake.rows("orders")[0]
    assert o["subtotal_cents"] == 4000
    assert o["tax_cents"] == 400
    assert out["totals"]["discount_cents"] == 1000


def test_the_currency_follows_the_product(fake):
    out = _sell(lines=[_line(OFF_TEE)])
    assert out["currency"] == "usd"
    assert fake.rows("orders")[0]["currency"] == "usd"


# ─── Routes ──────────────────────────────────────────────────────────


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user
    paths = {}
    for r in cs.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in paths.get("/store/inventory/{business_id}/counter-sale", set())
    assert "GET" in paths.get("/store/inventory/{business_id}/counter-sales", set())
    for r in cs.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"
