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
from auth_supabase import UserSession

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


def _site_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{slug}&select=id,business_id,slug&limit=1") or []
    return rows[0] if rows else None


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        "&select=id,name,settings,stripe_account_id&limit=1") or []
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


# ─── Customer: store data ─────────────────────────────────────────────

@router.get("/public/store/{slug}")
def store_data(slug: str) -> Dict[str, Any]:
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")
    site = _site_by_slug(slug)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"]) or {}
    items = _flag_instant_downloads(_sellable_offerings(site["business_id"]), biz)
    ss = _store_settings(biz)
    return {"ok": True, "business_name": biz.get("name") or "",
            "payments_ready": bool(biz.get("stripe_account_id")),
            "items": [{k: o.get(k) for k in (
                "id", "name", "description", "category", "current_price",
                "currency", "image_url", "in_stock", "requires_shipping",
                "instant_download")}
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
    if not biz.get("stripe_account_id"):
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
    items = sb_clients.sb_get_as_service(
        f"/order_items?order_id=eq.{order_id}&select=offering_id,quantity&limit=100") or []
    for it in items:
        oid = it.get("offering_id")
        if not oid:
            continue
        off = sb_clients.sb_get_as_service(
            f"/offerings?id=eq.{oid}&select=inventory_qty&limit=1") or []
        if off and off[0].get("inventory_qty") is not None:
            new_qty = max(0, int(off[0]["inventory_qty"]) - int(it.get("quantity") or 0))
            sb_clients.sb_patch_as_service(f"/offerings?id=eq.{oid}",
                                           {"inventory_qty": new_qty})

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


# ─── Customer: hosted store page (renderers in store_page.py) ─────────

@router.get("/public/store/{slug}/page")
def hosted_store_page(slug: str) -> HTMLResponse:
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")
    site = _site_by_slug(slug)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"])
    if not biz:
        raise HTTPException(404, "Business not found")
    from store_page import render_store_page
    items = _flag_instant_downloads(_sellable_offerings(site["business_id"]), biz)
    html = render_store_page(slug, biz, items, _store_settings(biz))
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
    site = _site_by_slug(slug)
    if not site:
        raise HTTPException(404, "Store not found")
    biz = _business(site["business_id"]) or {"id": site["business_id"]}
    digital = _thank_you_digital(site, biz, order)
    from store_page import render_thank_you
    return HTMLResponse(render_thank_you(slug, biz, order, **digital),
                        headers={"X-Solutionist-Source": "store"})
