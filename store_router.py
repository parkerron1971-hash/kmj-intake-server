"""
store_router.py — Arc 27 PR2 — the practitioner e-commerce store.

Customer-facing:
  GET  /public/store/{slug}            — store data JSON (sellable offerings)
  GET  /public/store/{slug}/page       — hosted store page (deterministic
                                         HTML from brand DNA tokens + a
                                         self-contained vanilla-JS cart)
  GET  /public/store/{slug}/thank-you  — order confirmation page
  POST /payments/store-checkout        — anon multi-item checkout. Prices
                                         are ALWAYS read server-side from
                                         offerings; the client sends only
                                         {offering_id, quantity}.

Practitioner-facing (authed):
  GET  /store/orders?biz=              — order list (+items)
  POST /store/orders/{id}/fulfill      — mark fulfilled

Webhook glue (imported by stripe_connect_router):
  mark_order_paid()     — idempotent paid flip + inventory decrement +
                          receipt email (best-effort, threaded)
  record_order_refund() — refund columns (status flips on full refund)

Money flow: Stripe Checkout Session on the practitioner's connected
account (same rails as bookings, source_type="order"). Tax = flat
business-level rate (settings.store.tax_rate_pct, default 0 — real tax
engines deferred per ruling). Shipping = flat fee
(settings.store.flat_shipping_cents) applied once per order when any
item requires shipping. GL entries come from gl_engine.desired_for_order
on the next sync — the webhook never writes ledger rows directly.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, UserSession, require_user

logger = logging.getLogger("store_router")

router = APIRouter(tags=["store"])

RAILWAY_BASE = "https://kmj-intake-server-production.up.railway.app"

SELLABLE_CATEGORIES = {"product", "course", "package"}
_MAX_LINE_ITEMS = 20
_MAX_QTY = 99


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_rate(slug: str) -> bool:
    try:
        from public_site import _check_rate as pr
        return pr(slug)
    except Exception:
        return True


def _site_by_slug(slug: str, *, with_design: bool = False) -> Optional[Dict[str, Any]]:
    """with_design=True adds status + site_config — the composed site's
    stored design forensics (language, design_rationale_id, custom
    domain) that store_design.resolve reads. Only the page renders pay
    for the bigger row; data/checkout stay lean."""
    sel = "id,business_id,slug"
    if with_design:
        sel += ",status,site_config"
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{slug}&select={sel}&limit=1") or []
    return rows[0] if rows else None


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        "&select=id,name,type,settings,stripe_account_id&limit=1") or []
    return rows[0] if rows else None


def _require_owner(business_id: str, session: UserSession) -> None:
    """Arc 28c — practitioner store endpoints read via service-role
    (bypasses RLS), so the owner check MUST live here. Without it any
    authenticated user could pass another business's id and read its
    orders + customer PII. Mirrors offerings_router._require_owner."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(session.user.id):
        raise HTTPException(403, "not authorized for this business")


def _sellable_offerings(business_id: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&select=id,name,slug,description,category,current_price,currency,"
        "image_url,sku,inventory_qty,requires_shipping,fulfillment_note"
        "&order=created_at.asc&limit=100") or []
    out = []
    for o in rows:
        if (o.get("category") or "") not in SELLABLE_CATEGORIES:
            continue
        try:
            price = float(o.get("current_price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        inv = o.get("inventory_qty")
        o["in_stock"] = inv is None or int(inv) > 0
        out.append(o)
    return out


def _store_settings(biz: Dict[str, Any]) -> Dict[str, Any]:
    s = ((biz.get("settings") or {}).get("store")) or {}
    return {
        "tax_rate_pct": float(s.get("tax_rate_pct") or 0.0),
        "flat_shipping_cents": int(s.get("flat_shipping_cents") or 0),
    }


def _flag_instant_downloads(items: List[Dict[str, Any]],
                            biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Digital delivery — mark items that have a hosted file attached
    (settings.store.product_files) so the storefront can show the
    'Instant download' badge."""
    try:
        from store_files import product_files_of
        files = product_files_of(biz or {})
    except Exception:
        files = {}
    for o in items:
        o["instant_download"] = bool((files.get(str(o.get("id"))) or {}).get("path"))
    return items


# ─── Inventory helpers ────────────────────────────────────────────────

# The storefront's "Only X left" nudge fires at or below this quantity
# for TRACKED items with no explicit per-offering threshold. The
# practitioner low-stock ALERT (chief_notification) only fires for
# offerings with an explicit threshold in settings.store.low_stock.
DEFAULT_LOW_STOCK_THRESHOLD = 5


def low_stock_thresholds(biz: Dict[str, Any]) -> Dict[str, int]:
    """settings.store.low_stock = {offering_id: threshold} — the
    settings-blob pattern (product_files precedent), no migration."""
    raw = (((biz.get("settings") or {}).get("store") or {})
           .get("low_stock")) or {}
    out: Dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[str(k)] = max(0, int(v))
            except (TypeError, ValueError):
                continue
    return out


def _flag_low_stock(items: List[Dict[str, Any]],
                    biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Storefront urgency — tracked items at/below their threshold (or
    the default when none is set) carry units_left for 'Only X left'."""
    thresholds = low_stock_thresholds(biz or {})
    for o in items:
        inv = o.get("inventory_qty")
        units_left = None
        if inv is not None:
            qty = int(inv)
            threshold = thresholds.get(str(o.get("id")),
                                       DEFAULT_LOW_STOCK_THRESHOLD)
            if 0 < qty <= threshold:
                units_left = qty
        o["units_left"] = units_left
    return items


def _emit_stock_event(business_id: str, offering_id: str, offering_name: str,
                      delta: Optional[int], new_qty: Optional[int],
                      reason: str, actor: str) -> None:
    """Every stock change drops a stock_adjusted row on the event spine —
    the movement history, with zero new tables. Best-effort by design."""
    try:
        import event_spine
        event_spine.emit("stock_adjusted", business_id, {
            "offering_id": str(offering_id),
            "offering_name": offering_name or "",
            "delta": delta,
            "new_qty": new_qty,
            "reason": (reason or "")[:200],
            "actor": (actor or "system")[:120],
        }, source="store")
    except Exception as e:
        logger.warning(f"[store] stock event emit failed (non-fatal): {e}")


# ─── Customer: store data ─────────────────────────────────────────────

@router.get("/public/store/{slug}")
def store_data(slug: str) -> Dict[str, Any]:
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")
    site = _site_by_slug(slug)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"]) or {}
    items = _flag_low_stock(
        _flag_instant_downloads(_sellable_offerings(site["business_id"]), biz), biz)
    ss = _store_settings(biz)
    import payments_core
    return {"ok": True, "business_name": biz.get("name") or "",
            "payments_ready": payments_core.can_charge(biz),
            "items": [{k: o.get(k) for k in (
                "id", "name", "description", "category", "current_price",
                "currency", "image_url", "in_stock", "requires_shipping",
                "instant_download", "units_left")}
                for o in items],
            "tax_rate_pct": ss["tax_rate_pct"],
            "flat_shipping_cents": ss["flat_shipping_cents"]}


# ─── Customer: checkout ───────────────────────────────────────────────

class CartItem(BaseModel):
    offering_id: str
    quantity: int = Field(ge=1, le=_MAX_QTY)


class StoreCheckoutBody(BaseModel):
    slug: str
    items: List[CartItem] = Field(min_length=1, max_length=_MAX_LINE_ITEMS)
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None


@router.post("/payments/store-checkout")
async def store_checkout(body: StoreCheckoutBody) -> Dict[str, Any]:
    if not _check_rate(body.slug):
        raise HTTPException(429, "Rate limit exceeded")
    site = _site_by_slug(body.slug)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"])
    if not biz:
        raise HTTPException(404, "Business not found")
    import payments_core
    if not payments_core.can_charge(biz):
        # Was `stripe_account_id is not null`, which let a restricted or
        # half-onboarded account reach Stripe and come back as a generic
        # "Payment provider error" in front of the buyer.
        raise HTTPException(409, "This store isn't accepting payments yet.")

    sellable = {o["id"]: o for o in _sellable_offerings(site["business_id"])}

    # Server-side pricing + inventory — client quantities only.
    line_items: List[Dict[str, Any]] = []
    order_items: List[Dict[str, Any]] = []
    subtotal_cents = 0
    needs_shipping = False
    for it in body.items:
        o = sellable.get(it.offering_id)
        if not o:
            raise HTTPException(400, "An item in your cart is no longer available.")
        inv = o.get("inventory_qty")
        if inv is not None and int(inv) < it.quantity:
            raise HTTPException(409, f"Not enough stock for {o['name']} "
                                     f"({int(inv)} left).")
        unit_cents = int(round(float(o["current_price"]) * 100))
        subtotal_cents += unit_cents * it.quantity
        needs_shipping = needs_shipping or bool(o.get("requires_shipping"))
        line_items.append({"name": o["name"], "amount_cents": unit_cents,
                           "quantity": it.quantity})
        order_items.append({"offering_id": o["id"], "name_at_purchase": o["name"],
                            "unit_amount_cents": unit_cents, "quantity": it.quantity})

    ss = _store_settings(biz)
    tax_cents = int(round(subtotal_cents * ss["tax_rate_pct"] / 100.0))
    shipping_cents = ss["flat_shipping_cents"] if needs_shipping else 0
    total_cents = subtotal_cents + tax_cents + shipping_cents

    if tax_cents > 0:
        line_items.append({"name": "Sales tax", "amount_cents": tax_cents, "quantity": 1})
    if shipping_cents > 0:
        line_items.append({"name": "Shipping", "amount_cents": shipping_cents, "quantity": 1})

    # Create the order (pending) before Stripe so the webhook has a row.
    created = sb_clients.sb_post_as_service("/orders", {
        "business_id": site["business_id"],
        "customer_email": (body.customer_email or "").strip().lower() or None,
        "customer_name": (body.customer_name or "").strip()[:160] or None,
        "status": "pending",
        "subtotal_cents": subtotal_cents, "tax_cents": tax_cents,
        "shipping_cents": shipping_cents, "total_cents": total_cents,
        "currency": "usd",
    })
    order = (created or [None])[0] if isinstance(created, list) else created
    if not order:
        raise HTTPException(500, "Could not create the order.")
    for oi in order_items:
        sb_clients.sb_post_as_service("/order_items", {**oi, "order_id": order["id"]},
                                      prefer=None)

    from stripe_checkout_helpers import create_checkout_session
    store_page = f"{RAILWAY_BASE}/public/store/{body.slug}/page"
    try:
        session = await create_checkout_session(
            stripe_account_id=biz["stripe_account_id"],
            line_items=line_items,
            success_url=f"{RAILWAY_BASE}/public/store/{body.slug}/thank-you?order={order['id']}",
            cancel_url=store_page,
            source_type="order",
            source_id=str(order["id"]),
            customer_email=(body.customer_email or "").strip().lower() or None,
            collect_shipping=needs_shipping,
        )
    except Exception as e:
        sb_clients.sb_patch_as_service(f"/orders?id=eq.{order['id']}",
                                       {"status": "canceled", "updated_at": _now_iso()})
        logger.warning(f"[store] checkout session failed for order {order['id']}: {e}")
        raise HTTPException(502, "Payment provider error — please try again.")

    sb_clients.sb_patch_as_service(
        f"/orders?id=eq.{order['id']}",
        {"stripe_checkout_session_id": session.get("id"), "updated_at": _now_iso()})
    return {"ok": True, "order_id": order["id"], "checkout_url": session.get("url")}


# ─── Webhook glue (called by stripe_connect_router) ───────────────────

def mark_order_paid(order_id: str, *, payment_intent_id: Optional[str],
                    charge_id: Optional[str],
                    session: Optional[Dict[str, Any]] = None) -> None:
    """Idempotent: only the first call (paid_at IS NULL) decrements
    inventory and sends the receipt."""
    rows = sb_clients.sb_get_as_service(
        f"/orders?id=eq.{order_id}&select=*&limit=1") or []
    if not rows:
        logger.warning(f"[store] webhook for unknown order {order_id}")
        return
    order = rows[0]
    if order.get("paid_at"):
        return

    patch: Dict[str, Any] = {"status": "paid", "paid_at": _now_iso(),
                             "updated_at": _now_iso()}
    if payment_intent_id:
        patch["stripe_payment_intent_id"] = payment_intent_id
    if charge_id:
        patch["stripe_charge_id"] = charge_id
    if session:
        details = session.get("customer_details") or {}
        if details.get("email") and not order.get("customer_email"):
            patch["customer_email"] = details["email"]
        if details.get("name") and not order.get("customer_name"):
            patch["customer_name"] = details["name"]
        ship = (session.get("shipping_details")
                or session.get("collected_information", {}).get("shipping_details")
                if isinstance(session.get("collected_information"), dict) else None) \
            or session.get("shipping_details")
        if ship:
            patch["shipping_address"] = ship
    sb_clients.sb_patch_as_service(f"/orders?id=eq.{order_id}", patch)

    # Inventory decrement for tracked items.
    #
    # KNOWN RACE (documented, not fixed this arc): this is read-then-write.
    # Two simultaneous paid orders on the last unit can both read qty=1 and
    # both write qty=0 — an oversell of one. Acceptable at current volume;
    # the future fix is a SECURITY DEFINER Postgres function doing the
    # decrement atomically (UPDATE ... SET inventory_qty = GREATEST(0,
    # inventory_qty - n) RETURNING inventory_qty) called via RPC.
    biz = _business(str(order.get("business_id"))) or {}
    thresholds = low_stock_thresholds(biz)
    items = sb_clients.sb_get_as_service(
        f"/order_items?order_id=eq.{order_id}&select=offering_id,quantity&limit=100") or []
    for it in items:
        oid = it.get("offering_id")
        if not oid:
            continue
        off = sb_clients.sb_get_as_service(
            f"/offerings?id=eq.{oid}&select=inventory_qty,name&limit=1") or []
        if off and off[0].get("inventory_qty") is not None:
            old_qty = int(off[0]["inventory_qty"])
            sold = int(it.get("quantity") or 0)
            new_qty = max(0, old_qty - sold)
            sb_clients.sb_patch_as_service(f"/offerings?id=eq.{oid}",
                                           {"inventory_qty": new_qty})
            name = off[0].get("name") or ""
            _emit_stock_event(str(order["business_id"]), str(oid), name,
                              delta=new_qty - old_qty, new_qty=new_qty,
                              reason=f"order {order_id[:8]}", actor="sale")
            _maybe_low_stock_alert(str(order["business_id"]), str(oid), name,
                                   old_qty, new_qty, thresholds)

    _send_receipt_async(order_id)

    # Arc 28b — tell the practitioner. Best-effort; mirrors the
    # Stripe-webhook invoice-paid push pattern.
    try:
        import push_notifications
        total = float(order.get("total_cents") or 0) / 100.0
        n_items = sum(int(i.get("quantity") or 0) for i in items) or len(items)
        push_notifications.send_to_business(
            str(order["business_id"]),
            title="Order paid 🎉",
            body=f"${total:,.2f} — {n_items} item{'s' if n_items != 1 else ''}. "
                 f"Tap to fulfill.",
            nav="operate", tag=f"order-{order_id[:8]}")
    except Exception as e:
        logger.warning(f"[store] order push failed (non-fatal): {e}")

    logger.info(f"[store] order {order_id[:8]} marked paid")


def _maybe_low_stock_alert(business_id: str, offering_id: str, name: str,
                           old_qty: int, new_qty: int,
                           thresholds: Dict[str, int]) -> None:
    """ONE chief_notification when a sale decrement CROSSES the offering's
    threshold (from above to at/below). The crossing edge IS the dedupe:
    the next sale starts at/below the threshold, so the condition is false
    until a restock lifts the qty back above it — at which point a fresh
    dip legitimately re-alerts. No last-notified marker needed. Only fires
    for offerings with an explicit threshold (default: none). Best-effort."""
    threshold = thresholds.get(str(offering_id))
    if threshold is None:
        return
    if not (old_qty > threshold >= new_qty):
        return
    try:
        left = (f"{new_qty} left" if new_qty > 0 else "sold out")
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": business_id,
            "type": "low_stock",
            "title": f"{name or 'A product'}: {left} — restock?",
            "body": (f"Stock just crossed your alert threshold of {threshold}. "
                     f"Adjust stock from Services & Products → Stock, or tell "
                     f"Chief to update it when the restock arrives."),
            "priority": "normal",
            "status": "unread",
            "data": {"offering_id": str(offering_id), "new_qty": new_qty,
                     "threshold": threshold},
        }, prefer=None)
    except Exception as e:
        logger.warning(f"[store] low-stock alert failed (non-fatal): {e}")


def record_order_refund(order_id: str, refunded_cents: int, fully: bool) -> None:
    patch = {"refund_amount_cents": refunded_cents, "refunded_at": _now_iso(),
             "updated_at": _now_iso()}
    if fully:
        patch["status"] = "refunded"
    sb_clients.sb_patch_as_service(f"/orders?id=eq.{order_id}", patch)


def _send_receipt_async(order_id: str) -> None:
    """Receipt email, best-effort, off the webhook thread."""
    def _run() -> None:
        import asyncio
        try:
            asyncio.run(_send_receipt(order_id))
        except Exception as e:
            logger.warning(f"[store] receipt email failed for {order_id}: {e}")
    threading.Thread(target=_run, daemon=True).start()


async def _send_receipt(order_id: str) -> None:
    rows = sb_clients.sb_get_as_service(f"/orders?id=eq.{order_id}&select=*&limit=1") or []
    if not rows:
        return
    order = rows[0]
    email = order.get("customer_email")
    if not email:
        return
    items = sb_clients.sb_get_as_service(
        f"/order_items?order_id=eq.{order_id}"
        "&select=name_at_purchase,unit_amount_cents,quantity&limit=100") or []
    biz = _business(order["business_id"]) or {}
    lines = "\n".join(
        f"  {it['quantity']} × {it['name_at_purchase']} — "
        f"${it['unit_amount_cents'] * it['quantity'] / 100:,.2f}" for it in items)
    extras = ""
    if order.get("tax_cents"):
        extras += f"\n  Sales tax — ${order['tax_cents'] / 100:,.2f}"
    if order.get("shipping_cents"):
        extras += f"\n  Shipping — ${order['shipping_cents'] / 100:,.2f}"
    # Per-item fulfillment notes (pickup instructions, legacy links).
    notes = []
    offering_ids = [it.get("offering_id") for it in
                    sb_clients.sb_get_as_service(
                        f"/order_items?order_id=eq.{order_id}&select=offering_id&limit=100") or []
                    if it.get("offering_id")]
    offs: List[Dict[str, Any]] = []
    if offering_ids:
        offs = sb_clients.sb_get_as_service(
            "/offerings?id=in.(" + ",".join(offering_ids) + ")"
            "&select=id,name,fulfillment_note&limit=100") or []
        notes = [f"{o['name']}: {o['fulfillment_note']}"
                 for o in offs if (o.get("fulfillment_note") or "").strip()]
    notes_block = ("\n\n" + "\n".join(notes)) if notes else ""

    # Digital delivery — a validated instant-download link for every
    # item with a hosted file. Composes WITH fulfillment_note, not
    # instead of it.
    downloads = []
    try:
        from store_files import download_url, product_files_of
        files = product_files_of(biz)
        for o in offs:
            if not (files.get(str(o.get("id"))) or {}).get("path"):
                continue
            link = download_url(str(order["id"]), str(o["id"]))
            if link:
                downloads.append(f"  {o['name']} — {link}")
    except Exception as e:
        logger.warning(f"[store] download links skipped for {order_id}: {e}")
    downloads_block = ("\n\nYour downloads (these links are yours — "
                       "keep this email):\n" + "\n".join(downloads)) if downloads else ""

    from email_sender import send_via_resend
    await send_via_resend(
        to_email=email, to_name=order.get("customer_name"),
        from_email="receipts@mysolutionist.app",
        from_name=biz.get("name") or "Your order",
        reply_to=None,
        subject=f"Receipt — order {str(order['id'])[:8].upper()}",
        body=(f"Thank you for your order from {biz.get('name') or 'us'}!\n\n"
              f"{lines}{extras}\n\n"
              f"Total — ${order['total_cents'] / 100:,.2f}"
              f"{downloads_block}{notes_block}\n\n"
              f"Questions? Just reply to this email.\n"
              f"— {biz.get('name') or ''}"),
        business_id=order.get("business_id"))


# ─── Practitioner: orders ─────────────────────────────────────────────

@router.get("/store/orders")
def list_orders(biz: str,
                session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    _require_owner(biz, session)
    orders = sb_clients.sb_get_as_service(
        f"/orders?business_id=eq.{biz}&order=created_at.desc&select=*&limit=200") or []
    ids = [o["id"] for o in orders]
    items_by_order: Dict[str, List[Dict[str, Any]]] = {}
    if ids:
        items = sb_clients.sb_get_as_service(
            "/order_items?order_id=in.(" + ",".join(ids) + ")"
            "&select=order_id,name_at_purchase,unit_amount_cents,quantity&limit=2000") or []
        for it in items:
            items_by_order.setdefault(it["order_id"], []).append(it)
    for o in orders:
        o["items"] = items_by_order.get(o["id"], [])
    return {"ok": True, "orders": orders}


@router.post("/store/orders/{order_id}/fulfill")
def fulfill_order(order_id: str,
                  session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/orders?id=eq.{order_id}&select=business_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "order not found")
    _require_owner(str(rows[0]["business_id"]), session)
    sb_clients.sb_patch_as_service(
        f"/orders?id=eq.{order_id}&status=eq.paid",
        {"status": "fulfilled", "fulfilled_at": _now_iso(), "updated_at": _now_iso()})
    return {"ok": True}


# ─── Practitioner: inventory management ───────────────────────────────
# Authed via the shared require_role ladder (seat-access arc): reads are
# member+, stock writes are manager+. Movement history is the event
# spine's stock_adjusted rows — no inventory tables exist or are needed.

def _inventory_offering_or_404(business_id: str,
                               offering_id: str) -> Dict[str, Any]:
    """Business-scoped fetch — a cross-tenant offering id reads as 404,
    never a hint that the id exists (store_files precedent)."""
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
        "&select=id,name,category,sku,inventory_qty&limit=1") or []
    if not rows:
        raise HTTPException(404, "offering not found")
    if (rows[0].get("category") or "") not in SELLABLE_CATEGORIES:
        raise HTTPException(400, "inventory tracks sellable offerings only "
                                 "(product, course, or package)")
    return rows[0]


@router.get("/store/inventory/{business_id}")
def get_inventory(business_id: str,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    from business_users_router import require_role
    require_role(business_id, str(user.id), "member")
    biz = _business(business_id)
    if not biz:
        raise HTTPException(404, "business not found")
    thresholds = low_stock_thresholds(biz)

    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        "&select=id,name,sku,category,current_price,inventory_qty"
        "&order=created_at.asc&limit=200") or []
    items = []
    for o in rows:
        if (o.get("category") or "") not in SELLABLE_CATEGORIES:
            continue
        inv = o.get("inventory_qty")
        tracked = inv is not None
        threshold = thresholds.get(str(o["id"]))
        low = bool(tracked and int(inv) <= (
            threshold if threshold is not None else DEFAULT_LOW_STOCK_THRESHOLD))
        items.append({"id": o["id"], "name": o.get("name"),
                      "sku": o.get("sku"), "category": o.get("category"),
                      "inventory_qty": (int(inv) if tracked else None),
                      "tracked": tracked, "threshold": threshold,
                      "low_stock": low})

    # Movement history — the spine's stock_adjusted rows, newest first.
    events = sb_clients.sb_get_as_service(
        f"/events?business_id=eq.{business_id}&event_type=eq.stock_adjusted"
        "&select=id,data,created_at&order=created_at.desc&limit=200") or []
    movements = [{"id": e.get("id"), "created_at": e.get("created_at"),
                  **(e.get("data") or {})} for e in events]

    return {"ok": True, "items": items, "movements": movements,
            "default_threshold": DEFAULT_LOW_STOCK_THRESHOLD}


class InventoryAdjustBody(BaseModel):
    mode: str                       # 'delta' | 'set'
    amount: Optional[int] = None    # set + null = stop tracking
    reason: Optional[str] = None


@router.post("/store/inventory/{business_id}/{offering_id}/adjust")
def adjust_inventory(business_id: str, offering_id: str,
                     body: InventoryAdjustBody,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")
    off = _inventory_offering_or_404(business_id, offering_id)
    old = off.get("inventory_qty")
    old_qty = int(old) if old is not None else None
    actor = (getattr(user, "email", None) or str(user.id))

    if body.mode == "delta":
        if body.amount is None:
            raise HTTPException(400, "amount is required for a delta adjustment")
        if old_qty is None:
            raise HTTPException(409, "this offering isn't tracked yet — "
                                     "set a starting quantity first")
        new_qty: Optional[int] = max(0, old_qty + int(body.amount))
        reason = (body.reason or "").strip() or "manual adjustment"
    elif body.mode == "set":
        if body.amount is None:
            new_qty = None          # disable tracking
            reason = (body.reason or "").strip() or "tracking disabled"
        else:
            new_qty = max(0, int(body.amount))
            reason = (body.reason or "").strip() or (
                "tracking enabled" if old_qty is None else "manual set")
    else:
        raise HTTPException(400, "mode must be 'delta' or 'set'")

    sb_clients.sb_patch_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}",
        {"inventory_qty": new_qty})
    delta = (new_qty - old_qty) if (new_qty is not None and old_qty is not None) \
        else (new_qty if new_qty is not None and old_qty is None else None)
    _emit_stock_event(business_id, str(offering_id), off.get("name") or "",
                      delta=delta, new_qty=new_qty, reason=reason, actor=actor)
    return {"ok": True, "offering_id": offering_id,
            "inventory_qty": new_qty, "tracked": new_qty is not None}


class InventoryThresholdBody(BaseModel):
    threshold: Optional[int] = None  # null clears the alert threshold


@router.post("/store/inventory/{business_id}/{offering_id}/threshold")
def set_inventory_threshold(business_id: str, offering_id: str,
                            body: InventoryThresholdBody,
                            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Low-stock alert threshold, per offering, in
    settings.store.low_stock — the settings-blob pattern. Backend-mediated
    (not a direct settings PATCH from the client) so manager seats can set
    it under the same role ladder as stock adjustments."""
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")
    _inventory_offering_or_404(business_id, offering_id)
    biz = _business(business_id)
    if not biz:
        raise HTTPException(404, "business not found")

    settings = dict(biz.get("settings") or {})
    store = dict(settings.get("store") or {})
    low = dict(store.get("low_stock") or {})
    if body.threshold is None:
        low.pop(str(offering_id), None)
    else:
        low[str(offering_id)] = max(0, int(body.threshold))
    store["low_stock"] = low
    settings["store"] = store
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                   {"settings": settings})
    return {"ok": True, "offering_id": offering_id,
            "threshold": low.get(str(offering_id))}


# ─── Customer: hosted store page (renderers in store_page.py) ─────────

@router.get("/public/store/{slug}/page")
def hosted_store_page(slug: str) -> HTMLResponse:
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")
    site = _site_by_slug(slug, with_design=True)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"])
    if not biz:
        raise HTTPException(404, "Business not found")
    from store_page import render_store_page
    items = _flag_low_stock(
        _flag_instant_downloads(_sellable_offerings(site["business_id"]), biz), biz)
    import payments_core
    html = render_store_page(slug, biz, items, _store_settings(biz), site=site,
                             payments_ready=payments_core.can_charge(biz))
    return HTMLResponse(html, headers={"X-Solutionist-Source": "store"})


def _thank_you_digital(site: Dict[str, Any], biz: Dict[str, Any],
                       order_id: str) -> Dict[str, Any]:
    """Digital-delivery state for the thank-you page: ready download
    links once the webhook has flipped the order to paid, or a
    'finalizing' flag while the race is still running. Empty dict when
    the order has no hosted digital items (or isn't this store's)."""
    if not order_id:
        return {}
    try:
        from store_files import download_url, product_files_of
        rows = sb_clients.sb_get_as_service(
            f"/orders?id=eq.{order_id}&business_id=eq.{site['business_id']}"
            "&select=id,status&limit=1") or []
        if not rows:
            return {}
        files = product_files_of(biz or {})
        if not files:
            return {}
        items = sb_clients.sb_get_as_service(
            f"/order_items?order_id=eq.{order_id}"
            "&select=offering_id,name_at_purchase&limit=100") or []
        digital = [it for it in items
                   if (files.get(str(it.get("offering_id"))) or {}).get("path")]
        if not digital:
            return {}
        if rows[0].get("status") in ("paid", "fulfilled"):
            downloads = []
            for it in digital:
                link = download_url(order_id, str(it["offering_id"]))
                if link:
                    downloads.append({"name": it.get("name_at_purchase") or "Your file",
                                      "url": link})
            return {"downloads": downloads} if downloads else {}
        if rows[0].get("status") == "pending":
            return {"digital_pending": True}
    except Exception as e:
        logger.warning(f"[store] thank-you digital state failed (non-fatal): {e}")
    return {}


@router.get("/public/store/{slug}/thank-you")
def hosted_store_thanks(slug: str, order: str = "") -> HTMLResponse:
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")
    site = _site_by_slug(slug, with_design=True)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"]) or {"id": site["business_id"]}
    digital = _thank_you_digital(site, biz, order)
    from store_page import render_thank_you
    return HTMLResponse(render_thank_you(slug, biz, order, site=site, **digital),
                        headers={"X-Solutionist-Source": "store"})
