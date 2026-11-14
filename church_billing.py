"""church_billing.py — the two extras around the church plans.

Kevin, 2026-11-03 ("I agree with the plan"; the review artifact
Pdg8hF4pB5n6efoFQmzd8d):

  * One more office login, $15 a month each (pricing_config.extra_login_cents),
    for a church between sizes that doesn't want to move up a plan. It is a
    second item on the church's own subscription, so Stripe prorates it and
    the webhook keeps the count (businesses.settings.extra_logins), which
    billing_limits.can_add_seat adds to the plan's logins.
  * The move from another system: three months of the plan
    (church_move_months), free for the first five churches that ask (the
    founding churches, founding_church_moves). Paid or free, the request
    lands in Mission Control as a support ticket, and the church's settings
    keep where it stands (businesses.settings.church_move).

Only for a church on a church plan (feature_gates.CHURCH_PLANS); every route
is the owner's (stripe_billing._require_owner_of). Nothing here is sold
until the church plans are: the extra-login price needs
STRIPE_PRICE_ID_EXTRA_LOGIN, and the move needs a church plan.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import feature_gates
import pricing_config
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("church_billing")

router = APIRouter(prefix="/billing/church", tags=["billing"])

EXTRA_LOGINS = "extra_logins"   # businesses.settings[EXTRA_LOGINS]: int
MOVE = "church_move"            # businesses.settings[MOVE]: where the move stands


# ─── Small readers ────────────────────────────────────────────────────

def _settings(biz: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    s = (biz or {}).get("settings")
    return s if isinstance(s, dict) else {}


def extra_logins(biz: Optional[Dict[str, Any]]) -> int:
    """Office logins bought on top of the plan's (0 when none or unreadable)."""
    try:
        return max(0, int(_settings(biz).get(EXTRA_LOGINS) or 0))
    except (TypeError, ValueError):
        return 0


def is_church(biz: Optional[Dict[str, Any]]) -> bool:
    import vertical_registry
    return vertical_registry.resolve((biz or {}).get("type") or "") == "ministry"


def extra_login_price() -> str:
    return (os.environ.get("STRIPE_PRICE_ID_EXTRA_LOGIN") or "").strip()


def extra_login_quantity(items) -> int:
    """How many extra logins a subscription's items carry."""
    price = extra_login_price()
    if not price:
        return 0
    return sum(int(it.get("quantity") or 0) for it in (items or [])
               if ((it.get("price") or {}).get("id")) == price)


async def _merge_setting(business_id: str, key: str, value: Any) -> None:
    """Write one key of businesses.settings, read fresh and merged so no other
    key is touched."""
    import stripe_billing as sb
    biz = await sb._load_business(business_id)
    settings = dict(_settings(biz))
    if value is None:
        settings.pop(key, None)
    else:
        settings[key] = value
    await sb._patch_business(business_id, {"settings": settings})


async def sync_extra_logins(business_id: str, items, status: Optional[str]) -> None:
    """From the subscription as Stripe holds it (the webhook): the count of
    extra logins, 0 once the subscription is cancelled. Writes only when it
    changed. Never raises; the plan patch is what the webhook is for."""
    try:
        count = 0 if status == "canceled" else extra_login_quantity(items)
        import stripe_billing as sb
        biz = await sb._load_business(business_id)
        if extra_logins(biz) == count:
            return
        await _merge_setting(business_id, EXTRA_LOGINS, count or None)
    except Exception as e:
        logger.warning(f"extra logins sync for {business_id} failed (non-fatal): {e}")


# ─── One more login ───────────────────────────────────────────────────

class ExtraLoginsBody(BaseModel):
    business_id: str
    count: int = Field(ge=0, le=100)


async def _church_on_a_plan(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    import stripe_billing as sb
    biz = await sb._load_business(business_id)
    sb._require_owner_of(user, biz)
    if feature_gates.plan_of(biz) not in feature_gates.CHURCH_PLANS:
        raise HTTPException(409, "Extra office logins and the move come with the church plans.")
    return biz


async def _stripe_delete(path: str) -> Dict[str, Any]:
    import stripe_billing as sb
    async with httpx.AsyncClient(timeout=sb.HTTP_TIMEOUT) as c:
        r = await c.delete(f"{sb.STRIPE_API_BASE}{path}", auth=(sb._stripe_key(), ""),
                           headers=sb._stripe_headers())
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"Stripe error: {r.text[:200]}")
    return r.json()


@router.post("/extra-logins")
async def set_extra_logins(body: ExtraLoginsBody, user: AuthedUser = Depends(require_user)):
    """Set how many office logins the church buys on top of its plan. A second
    item on its subscription at $15 a month each, prorated by Stripe."""
    import stripe_billing as sb
    biz = await _church_on_a_plan(body.business_id, user)
    price = extra_login_price()
    if not price:
        raise HTTPException(409, "Extra office logins aren't open yet.")
    sub_id = (biz.get("stripe_subscription_id") or "").strip()
    if not sub_id:
        raise HTTPException(409, "Extra office logins are added to a paid church plan.")
    sub = await sb._stripe_get(f"/subscriptions/{sub_id}", [])
    items = ((sub.get("items") or {}).get("data")) or []
    item = next((it for it in items if ((it.get("price") or {}).get("id")) == price), None)
    if item and body.count == 0:
        await _stripe_delete(f"/subscription_items/{item['id']}")
    elif item:
        await sb._stripe_post(f"/subscription_items/{item['id']}",
                              {"quantity": body.count, "proration_behavior": "create_prorations"})
    elif body.count > 0:
        await sb._stripe_post("/subscription_items", {"subscription": sub_id, "price": price,
                                                     "quantity": body.count,
                                                     "proration_behavior": "create_prorations"})
    # The webhook writes the same number when Stripe confirms; this makes the
    # new login usable now instead of a webhook later.
    await _merge_setting(str(biz["id"]), EXTRA_LOGINS, body.count or None)
    base = feature_gates._limits_of(feature_gates.plan_of(biz)).get("max_seats")
    return {"ok": True, "extra_logins": body.count,
            "max_seats": (base + body.count) if base is not None else None,
            "cents_each": pricing_config.extra_login_cents()}


# ─── The move ─────────────────────────────────────────────────────────

class MoveBody(BaseModel):
    business_id: str
    # Where the church is moving from, in its own words ("Subsplash", "Planning Center").
    moving_from: Optional[str] = Field(default=None, max_length=80)
    # A church on its trial chose to pay its first month now, for a founding place.
    pay_today: bool = False


def _first_payment_due(biz: Dict[str, Any]) -> bool:
    """Still on a carded trial, so nothing has been paid. A founding place
    waits for the first payment: a free move is real work, and a trial costs
    nothing to start or to walk away from. A comped church owes no payment."""
    comped = (biz.get("comp_tier") or "").strip().lower() in feature_gates.ALL_PLANS
    return not comped and biz.get("subscription_status") == "trialing"


def _first_payment_cents(plan: Optional[str], biz: Optional[Dict[str, Any]] = None) -> int:
    """The church's own month: the founding price on a founding price."""
    import church_founding
    return church_founding.price_cents_for(biz, plan)


async def _pay_first_month(biz: Dict[str, Any]) -> None:
    """End the church's trial now, which charges its first month to the card
    it put down. Raises 402 unless the subscription comes back paid, so a
    place is never taken on a card that failed."""
    import stripe_billing as sb
    sub_id = (biz.get("stripe_subscription_id") or "").strip()
    if not sub_id:
        raise HTTPException(409, "Add a card by choosing your plan, then ask for the move.")
    path = f"/subscriptions/{quote(sub_id, safe='')}"
    sub = await sb._stripe_get(path, [])
    if sub.get("status") == "trialing":
        sub = await sb._stripe_post(path, {"trial_end": "now"})
    await sb._apply_subscription_state("customer.subscription.updated", sub, biz["id"])
    if sub.get("status") != "active":
        raise HTTPException(402, "Your card didn't go through, so nothing is held yet. "
                                 "Update it under Manage Subscription, then ask again.")


def _founding_taken() -> Optional[int]:
    """How many churches have had a founding (free) move; None when unreadable."""
    import sb_clients
    rows = sb_clients.sb_get_all_as_service(
        f"/businesses?settings->{MOVE}->>founding=eq.true&is_sample=not.is.true&select=id")
    return len(rows) if isinstance(rows, list) else None


def _move_cents(plan: str, biz: Optional[Dict[str, Any]] = None) -> int:
    """Three months of the plan, at the price this church pays for it."""
    import church_founding
    return pricing_config.church_move_months() * church_founding.price_cents_for(biz, plan)


def _ticket(biz: Dict[str, Any], record: Dict[str, Any]) -> None:
    """The move lands in Mission Control's Today queue as a support ticket."""
    import sb_clients
    name = biz.get("name") or "A church"
    paid = "founding church, no charge" if record.get("founding") else \
        f"paid ${int(record.get('amount_cents') or 0) // 100:,}"
    plan = feature_gates.plan_of(biz) or record.get("plan") or ""
    import billing_limits
    sb_clients.sb_post_as_service("/support_tickets", {
        "business_id": biz["id"],
        "category": "billing",
        "subject": f"MOVE: {name} from {record.get('moving_from') or 'their old system'} ({paid})"[:200],
        "message": (f"{name} asked to be moved over. Plan: {billing_limits.PLAN_DISPLAY.get(plan, plan)}. "
                    f"Moving from: {record.get('moving_from') or 'not said'}. "
                    "Bring over people, giving history, groups and sermons, then set up the office logins.")[:5000],
        "context": {"kind": "church_move", **{k: record.get(k) for k in
                                              ("founding", "plan", "moving_from", "amount_cents", "session_id")}},
    })


async def _tell_owner(biz: Dict[str, Any], record: Dict[str, Any]) -> bool:
    """One plain email to the platform owner the moment a church asks for its
    move (2026-11-10). The ticket sat in Mission Control until someone opened
    Today, and a move starts a clock: the church's first Sunday. Best effort:
    the ticket is the record, so a send that fails never fails the request.
    One email per ask (Stripe redelivers a paid session; Resend drops the
    repeat by its key)."""
    to = (os.environ.get("PLATFORM_OWNER_EMAIL") or "").strip()
    if not to:
        return False
    try:
        import html
        import billing_limits
        from email_sender import send_via_resend
        name = str(biz.get("name") or "A church")
        plan = feature_gates.plan_of(biz) or record.get("plan") or ""
        paid = ("Founding church, no charge for the move." if record.get("founding")
                else f"Paid ${int(record.get('amount_cents') or 0) // 100:,} for the move.")
        lines = [f"{name} asked to be moved over.",
                 f"Plan: {billing_limits.PLAN_DISPLAY.get(plan, plan) or 'not known'}.",
                 f"Moving from: {record.get('moving_from') or 'not said'}.",
                 paid,
                 "The ticket is in Mission Control, under Today."]
        await send_via_resend(
            to_email=to, to_name=None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
            from_name="Solutionist", subject=f"A church asked for its move: {name}"[:150],
            # Plain text only: a church's name never becomes email markup.
            body="".join(f"<p>{html.escape(x)}</p>" for x in lines), reply_to=None,
            idempotency_key=f"church-move-{biz.get('id')}-{record.get('session_id') or 'founding'}"[:200])
        return True
    except Exception as e:
        logger.warning("church move: the owner's email didn't send for %s: %s", biz.get("id"), e)
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/move")
async def move_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Where this church's move stands, and what it would cost now."""
    import stripe_billing as sb
    biz = await sb._load_business(business_id)
    sb._require_owner_of(user, biz)
    plan = feature_gates.plan_of(biz)
    taken = await asyncio.to_thread(_founding_taken)
    left = None if taken is None else max(0, pricing_config.founding_church_moves() - taken)
    import church_founding
    price = await asyncio.to_thread(church_founding.public_state)
    return {"ok": True, "move": _settings(biz).get(MOVE),
            "on_church_plan": plan in feature_gates.CHURCH_PLANS,
            "founding_left": left,
            # The founding churches' price (church_founding): this church's
            # place, when it holds one, and how many places are left.
            "founding_church": church_founding.record(biz),
            "founding_price": {"on": price is not None, "spots": church_founding.spots(),
                               "left": price["left"] if price else None,
                               "ends": price.get("ends") if price else None},
            "price_cents": _move_cents(plan, biz) if plan in feature_gates.CHURCH_PLANS else None,
            "first_payment_due": _first_payment_due(biz),
            "first_payment_cents": _first_payment_cents(plan, biz)}


@router.post("/move")
async def request_move(body: MoveBody, user: AuthedUser = Depends(require_user)):
    """Ask for the move. A founding church (one of the first five) is moved
    free once its first month is paid; after that it's three months of the
    plan, paid at Stripe Checkout. A church on its trial with a founding place
    open is told so, and takes the place by paying today. Asking twice returns
    the first request."""
    import stripe_billing as sb
    biz = await _church_on_a_plan(body.business_id, user)
    now = _settings(biz).get(MOVE)
    if isinstance(now, dict) and now.get("state") in ("requested", "paid"):
        return {"ok": True, "move": now, "already": True}
    plan = feature_gates.plan_of(biz)
    moving_from = (body.moving_from or "").strip() or None
    taken = await asyncio.to_thread(_founding_taken)
    if taken is None:
        raise HTTPException(503, "Couldn't check the founding churches. Try again in a minute.")
    if taken < pricing_config.founding_church_moves():
        if _first_payment_due(biz):
            if not body.pay_today:
                return {"ok": True, "pay_first": True, "first_payment_cents": _first_payment_cents(plan, biz)}
            await _pay_first_month(biz)
        record = {"state": "requested", "founding": True, "plan": plan,
                  "moving_from": moving_from, "requested_at": _now()}
        await _merge_setting(str(biz["id"]), MOVE, record)
        await asyncio.to_thread(_ticket, biz, record)
        await _tell_owner(biz, record)
        return {"ok": True, "move": record, "founding": True}
    cents = _move_cents(plan, biz)
    import billing_limits
    session = await sb._stripe_post("/checkout/sessions", {
        "mode": "payment",
        "customer": biz.get("stripe_customer_id") or None,
        "line_items": [{"quantity": 1, "price_data": {
            "currency": "usd", "unit_amount": cents,
            "product_data": {"name": f"Moving {biz.get('name') or 'your church'} to Solutionist "
                                     f"({billing_limits.PLAN_DISPLAY.get(plan, plan)})"}}}],
        "success_url": sb._success_url() + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": sb._cancel_url(),
        "metadata": {"kind": "church_move", "business_id": biz["id"], "plan": plan,
                     "moving_from": moving_from or "", "auth_user_id": user.id},
    })
    return {"ok": True, "url": session.get("url"), "id": session.get("id"), "price_cents": cents}


async def record_paid_move(business_id: str, session: Dict[str, Any]) -> Optional[str]:
    """The webhook's half: a paid move session becomes the church's move
    record and a ticket, once per session (Stripe redelivers). Returns an
    error string or None."""
    import stripe_billing as sb
    if session.get("payment_status") != "paid":
        return None
    biz = await sb._load_business(business_id)
    now = _settings(biz).get(MOVE)
    if isinstance(now, dict) and now.get("session_id") == session.get("id"):
        return None
    meta = session.get("metadata") or {}
    record = {"state": "paid", "founding": False, "plan": meta.get("plan") or feature_gates.plan_of(biz),
              "moving_from": meta.get("moving_from") or None, "amount_cents": session.get("amount_total"),
              "session_id": session.get("id"), "paid_at": _now()}
    await _merge_setting(business_id, MOVE, record)
    try:
        await asyncio.to_thread(_ticket, biz, record)
    except Exception as e:
        return f"move ticket failed: {e}"
    await _tell_owner(biz, record)
    return None
