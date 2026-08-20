"""
counter_sale.py — THE TILL (2026-08-20).

WHAT THIS IS
  Somebody buys a product standing in front of you. Until now the only
  doors that moved stock and money together were the online store and an
  invoice, so a shop selling across the counter had to remember to go
  and adjust the count afterwards — which is exactly the habit the count
  session exists to clean up after.

THE DECISION THAT SHAPES EVERYTHING: A COUNTER SALE **IS** AN ORDER
  Same `orders` and `order_items` rows the storefront writes, with
  source='counter'. That is not a shortcut, it is the point: it inherits
  the general ledger mapping, the refund machinery, the Orders list, the
  revenue reports and the audit triggers, all of which already exist and
  are already tested. A second money table would have meant a second
  version of every one of those, and the second version is the one that
  drifts.

PAYMENT IS RECORDED, NOT PROCESSED
  This module never touches a card. It records how the money arrived —
  cash, a card on the shop's own reader, or something else — and takes
  the stock off the shelf. That is what a small shop actually needs to
  keep its count and its books honest, and it introduces no new payment
  surface, no PCI question, and no hardware.

  A practitioner who wants to CHARGE a card through us already has a
  door for that: an invoice with a payment link. Building a second one
  here would be half a payments product.

  It is load-bearing in the books: gl_engine._order_cash_account reads
  payment_method to decide whether the money lands in Stripe Clearing
  (a payout is coming to clear it) or in Cash (none is). Book a cash
  sale into the clearing account and it never reconciles again.

PRICES COME FROM THE CATALOG, NEVER FROM THE CLIENT
  Same rule as the public checkout. A till that accepts a price off the
  wire is a till where the price can be anything. A whole-order discount
  is allowed and recorded, because that is a decision somebody makes out
  loud, not a number that quietly replaces another one.

SELLING THE LAST ONE
  The till never refuses a sale for being out of stock. The customer is
  holding the product; the shelf is the truth and the count is what is
  wrong. It sells, the count clamps at zero, and the response says so
  in plain words so somebody can fix the number.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("counter_sale")

router = APIRouter(tags=["store"])

_MAX_LINES = 40
_MAX_QTY = 99

# How the money arrived. Deliberately short: each one has to mean
# something different to the ledger, and a free-text field here becomes
# a free-text field in the books.
_METHODS = {
    "cash": "Cash",
    "card": "Card (your own reader)",
    "other": "Other",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SaleLine(BaseModel):
    offering_id: str
    quantity: int = Field(default=1, ge=1, le=_MAX_QTY)


class CounterSaleBody(BaseModel):
    lines: List[SaleLine]
    payment_method: str = "cash"
    # A discount is a decision somebody makes out loud. Recorded at the
    # order level so it shows up as itself rather than hiding inside a
    # line price nobody can audit.
    discount_cents: int = Field(default=0, ge=0)
    customer_name: Optional[str] = Field(default=None, max_length=120)
    customer_email: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=200)


# ─── Pure helpers (unit-tested; no network) ──────────────────────────


def price_lines(offerings: Dict[str, Dict[str, Any]],
                lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Catalog prices × quantities. Pure, and the client's opinion about
    price never appears — it is not a parameter."""
    out: List[Dict[str, Any]] = []
    for ln in lines:
        oid = str(ln.get("offering_id"))
        off = offerings.get(oid)
        if not off:
            continue
        try:
            cents = int(round(float(off.get("current_price") or 0) * 100))
        except (TypeError, ValueError):
            cents = 0
        qty = max(1, int(ln.get("quantity") or 1))
        out.append({
            "offering_id": oid,
            "name": off.get("name") or "",
            "unit_amount_cents": cents,
            "quantity": qty,
            "line_cents": cents * qty,
        })
    return out


def totals(priced: List[Dict[str, Any]], discount_cents: int,
           tax_rate_pct: float) -> Dict[str, int]:
    """Subtotal, discount, tax, total — all in cents, all integers.

    Tax is charged on what is actually paid, so the discount comes off
    BEFORE tax. Charging tax on a price nobody paid is the kind of small
    wrongness that turns into a real problem at the end of a year.
    """
    gross = sum(int(p["line_cents"]) for p in priced)
    discount = max(0, min(int(discount_cents or 0), gross))
    subtotal = gross - discount
    tax = int(round(subtotal * (float(tax_rate_pct or 0) / 100.0)))
    return {"gross_cents": gross, "discount_cents": discount,
            "subtotal_cents": subtotal, "tax_cents": tax,
            "total_cents": subtotal + tax}


def stock_warnings(results: List[Dict[str, Any]]) -> List[str]:
    """Plain sentences about counts that were already wrong.

    A sale is never blocked for this — the customer is holding the
    thing. But the count was wrong before they walked in, and saying so
    is the only way it gets fixed.
    """
    out: List[str] = []
    for r in results:
        if r.get("oversold"):
            out.append(
                f"{r['name']}: the count said {r['had']} but you sold "
                f"{r['sold']} — it is now 0. Worth a recount.")
    return out


# ─── The sale ────────────────────────────────────────────────────────


@router.post("/store/inventory/{business_id}/counter-sale")
def counter_sale(business_id: str, body: CounterSaleBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Ring up a sale at the counter. Manager+, the same ladder as every
    other stock write.

    Writes ONE order (source='counter', already paid and handed over),
    its items, and the stock movements — then lets the existing GL
    queue, refund flow and reports treat it exactly like any other sale,
    because it is one.
    """
    from business_users_router import require_role
    from store_router import (_business, low_stock_thresholds, sell_units,
                              SELLABLE_CATEGORIES, _store_settings)
    require_role(business_id, str(user.id), "manager")

    method = (body.payment_method or "cash").strip().lower()
    if method not in _METHODS:
        raise HTTPException(
            400, f"payment method must be one of {sorted(_METHODS)}")
    if not body.lines:
        raise HTTPException(400, "a sale needs at least one product")
    if len(body.lines) > _MAX_LINES:
        raise HTTPException(413, f"a counter sale tops out at {_MAX_LINES} lines")

    biz = _business(business_id)
    if not biz:
        raise HTTPException(404, "business not found")

    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&select=id,name,category,current_price,currency,inventory_qty"
        "&limit=500") or []
    offerings = {str(o["id"]): o for o in rows
                 if (o.get("category") or "") in SELLABLE_CATEGORIES}

    # Merge repeats: scanning the same product three times is a quantity
    # of three, not three lines the customer reads three times.
    merged: Dict[str, int] = {}
    order: List[str] = []
    for ln in body.lines:
        oid = str(ln.offering_id)
        if oid not in offerings:
            raise HTTPException(404, "one of those isn't in this business's catalog")
        if oid not in merged:
            order.append(oid)
        merged[oid] = min(_MAX_QTY, merged.get(oid, 0) + int(ln.quantity))

    priced = price_lines(offerings, [{"offering_id": o, "quantity": merged[o]}
                                     for o in order])
    unpriced = [p["name"] for p in priced if p["unit_amount_cents"] <= 0]
    if unpriced:
        # A price-less product is one a manager added for stock. It is
        # deliberately not sellable until the owner prices it, and
        # inventing a price at the till would route around that.
        raise HTTPException(
            400, f"{unpriced[0]} has no price yet — the owner needs to set one "
                 f"before it can be sold")

    ss = _store_settings(biz)
    # Currency follows the PRODUCT, the way its price does — the store
    # settings blob does not carry one, and a till that priced in one
    # currency and recorded in another would be a quiet disaster.
    currency = (offerings[order[0]].get("currency") or "usd").lower()
    t = totals(priced, body.discount_cents, ss.get("tax_rate_pct") or 0)
    if t["total_cents"] <= 0:
        raise HTTPException(400, "that sale comes to nothing — check the prices")

    created = sb_clients.sb_post_as_service("/orders", {
        "business_id": business_id,
        "status": "paid",
        "source": "counter",
        "payment_method": method,
        "subtotal_cents": t["subtotal_cents"],
        "tax_cents": t["tax_cents"],
        "shipping_cents": 0,          # they are carrying it out
        "total_cents": t["total_cents"],
        "currency": currency,
        "customer_name": (body.customer_name or "").strip() or None,
        "customer_email": (body.customer_email or "").strip() or None,
        "paid_at": _now_iso(),
        "fulfilled_at": _now_iso(),
    })
    if not (isinstance(created, list) and created):
        logger.error(f"[counter] order insert failed biz={business_id[:8]}")
        raise HTTPException(500, "Something went wrong on our end — please try again.")
    order_row = created[0]
    order_id = str(order_row["id"])

    for p in priced:
        sb_clients.sb_post_as_service("/order_items", {
            "order_id": order_id,
            "offering_id": p["offering_id"],
            "name_at_purchase": p["name"],
            "unit_amount_cents": p["unit_amount_cents"],
            "quantity": p["quantity"],
        }, prefer=None)

    thresholds = low_stock_thresholds(biz)
    actor = (getattr(user, "email", None) or str(user.id))
    reason = f"counter sale {order_id[:8]}"
    if body.note:
        reason = f"{reason} — {body.note.strip()[:120]}"

    results: List[Dict[str, Any]] = []
    for p in priced:
        had = offerings[p["offering_id"]].get("inventory_qty")
        moved = sell_units(business_id, p["offering_id"], p["quantity"],
                           reason=reason, actor=actor,
                           offering_name=p["name"], thresholds=thresholds)
        results.append({
            "offering_id": p["offering_id"], "name": p["name"],
            "sold": p["quantity"],
            "had": (int(had) if had is not None else None),
            "now": (moved or {}).get("new_qty"),
            "tracked": moved is not None,
            # The count was already wrong before this customer walked in.
            "oversold": bool(moved and had is not None
                             and int(had) < p["quantity"]),
        })

    logger.info(f"[counter] biz={business_id[:8]} order={order_id[:8]} "
                f"lines={len(priced)} total={t['total_cents']} method={method}")

    return {"ok": True, "order_id": order_id,
            "lines": results, "totals": t,
            "payment_method": method,
            "payment_label": _METHODS[method],
            "currency": currency,
            "warnings": stock_warnings(results)}


@router.get("/store/inventory/{business_id}/counter-sales")
def recent_counter_sales(business_id: str, limit: int = 20,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Today's takings at the counter. Member+, because it is a read of
    the same picture the Orders list already shows."""
    from business_users_router import require_role
    require_role(business_id, str(user.id), "member")
    limit = max(1, min(int(limit or 20), 100))
    rows = sb_clients.sb_get_as_service(
        f"/orders?business_id=eq.{business_id}&source=eq.counter"
        "&select=id,total_cents,currency,payment_method,paid_at,customer_name,"
        "refund_amount_cents&order=paid_at.desc"
        f"&limit={limit}") or []
    return {"ok": True, "sales": rows}
