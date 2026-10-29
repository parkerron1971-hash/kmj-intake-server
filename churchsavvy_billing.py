# churchsavvy_billing.py — what a church on ChurchSavvy alone has paid for
# (design canvas UZu4VsoY9KemkUGorz234j, boards 5 "Start your church" and 16
# "Your plan"; Kevin 2026-10-24: "the pricing is good").
#
#   ChurchSavvy           $20 a month   cs_screens    the screens: plan, rehearse, run Sunday
#   ChurchSavvy Planning  $15 a month   cs_planning   teams, who serves when, asks by email
#   Both                  $29 a month   cs_both
#
# Only a church on ChurchSavvy alone (settings.churchsavvy_only) is held to
# these. A Solutionist church opens everything as before (its $10 add-on for
# the screens comes later). The plan comes from the subscription, or from
# the owner's comp (Mission Control), so a church that started before
# checkout existed can be kept on.
#
# The switch, CHURCHSAVVY_BILLING = off | owner | on (default off):
#   off    nobody is held to a plan; checkout for these plans is closed
#   owner  only the platform owner is held (in any church on ChurchSavvy
#          alone they open), and only the owner may buy one: rehearsing it
#          end to end while every other church stays as it is
#   on     every church on ChurchSavvy alone
#
# Buying one is Solutionist's own checkout (stripe_billing /billing/checkout
# with plan=cs_*), held here to churches on ChurchSavvy alone and to the
# switch, with no promotion-code box (the price is the price) and Stripe
# sending them back to ChurchSavvy's Plan and billing. The Customer Portal
# (/billing/portal) is where the card, receipts and cancelling live.
#
#   GET  /churchsavvy-billing/status?business_id=   the plan, its parts, what it costs, renewals
#   POST /churchsavvy-billing/change {business_id, plan}   another plan, prorated, same card
#   GET  /churchsavvy-billing/receipts?business_id=   the last twelve bills, each with Stripe's receipt
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix="/churchsavvy-billing", tags=["churchsavvy"])

PARTS: Dict[str, Set[str]] = {"cs_screens": {"screens"}, "cs_planning": {"planning"}, "cs_both": {"screens", "planning"}}
PRICES = {"cs_screens": 2000, "cs_planning": 1500, "cs_both": 2900}   # cents a month, as shown; Stripe's price charges
NAMES = {"cs_screens": "ChurchSavvy", "cs_planning": "ChurchSavvy Planning", "cs_both": "ChurchSavvy and Planning"}
PART_WORDS = {"screens": "ChurchSavvy’s screens", "planning": "ChurchSavvy Planning"}


def mode() -> str:
    m = (os.environ.get("CHURCHSAVVY_BILLING") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _owner_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def standalone(biz: Optional[Dict[str, Any]]) -> bool:
    settings = (biz or {}).get("settings")
    return isinstance(settings, dict) and settings.get("churchsavvy_only") is True


def plan_of(biz: Optional[Dict[str, Any]]) -> Optional[str]:
    """Its ChurchSavvy plan, when it has one in good standing (or a comp)."""
    import feature_gates
    plan = feature_gates.plan_of(biz)
    return plan if plan in feature_gates.CHURCHSAVVY_PLANS else None


def parts(biz: Optional[Dict[str, Any]]) -> Set[str]:
    """What this church opens: everything for a Solutionist church, its
    plan's parts for a church on ChurchSavvy alone."""
    if not standalone(biz):
        return {"screens", "planning"}
    return set(PARTS.get(plan_of(biz) or "", set()))


def _church(biz_id: str, extra: str = "") -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(biz_id), safe='')}"
        f"&select=id,owner_id,type,settings,comp_tier,subscription_status,subscription_plan,"
        f"trial_ends_at,current_period_end,cancel_at_period_end,stripe_customer_id"
        f"{',' + extra if extra else ''}&limit=1")
    if rows is None:
        raise HTTPException(503, "access check unavailable")
    return rows[0] if rows else None


def _is_owner(user: Optional[AuthedUser]) -> bool:
    return (getattr(user, "email", None) or "").strip().lower() == _owner_email()


def _held(biz: Dict[str, Any], user: Optional[AuthedUser]) -> bool:
    """Whether this church is held to its plan for this person right now:
    "owner" holds only the platform owner, to rehearse it end to end."""
    m = mode()
    if m == "off" or not standalone(biz):
        return False
    return m == "on" or _is_owner(user)


def require_part(biz_id: str, part: str, user: Optional[AuthedUser] = None) -> None:
    """402 when a church on ChurchSavvy alone hasn't got this part in its
    plan (and the switch holds it): the app shows Choose your plan."""
    m = mode()
    if m == "off" or (m == "owner" and not _is_owner(user)):
        return   # nothing read: the switch holds nobody this person could be
    biz = _church(biz_id)
    if not biz or not _held(biz, user):
        return
    if part not in parts(biz):
        raise HTTPException(402, {"code": "churchsavvy_plan", "part": part,
                                  "message": f"{PART_WORDS.get(part, 'This part')} isn’t in your church’s plan yet. "
                                             "Choose a plan in Setup to open it."})


def lapsed(biz: Optional[Dict[str, Any]], part: str) -> bool:
    """For work no one is signed in to (the serving sweep): this church is
    on ChurchSavvy alone, the switch is on for everyone, and its plan hasn't
    got this part. Owner mode rehearses in the app and holds no sweep."""
    return mode() == "on" and standalone(biz) and part not in parts(biz)


# What the sweep reads of each church to know its plan.
BILLING_FIELDS = "comp_tier,subscription_status,subscription_plan"


def checkout_open(user: AuthedUser) -> bool:
    m = mode()
    return m == "on" or (m == "owner" and _is_owner(user))


def app_url() -> str:
    """ChurchSavvy's app: its own address once it has one, else the platform's /churchsavvy."""
    import app_base
    return ((os.environ.get("CHURCHSAVVY_APP_URL") or "").strip().rstrip("/")
            or f"{app_base.app_base_url()}/churchsavvy")


def billing_page() -> str:
    """Setup → Plan and billing, where Stripe sends them back."""
    return f"{app_url()}/setup/billing"


LIVE = ("trialing", "active", "past_due", "unpaid", "incomplete")


def checkout_rules(biz: Dict[str, Any], user: AuthedUser, plan: str) -> Dict[str, str]:
    """Whether this church may start this plan now (stripe_billing's checkout
    asks), and where Stripe sends them back."""
    import feature_gates
    if plan not in feature_gates.CHURCHSAVVY_PLANS:
        raise HTTPException(400, "That isn't one of ChurchSavvy's plans.")
    if not checkout_open(user):
        raise HTTPException(409, "ChurchSavvy's plans aren't open yet.")
    if not standalone(biz):
        raise HTTPException(409, "Your church has ChurchSavvy through Solutionist. There's nothing to buy here.")
    if (biz.get("stripe_subscription_id") or "").strip() and biz.get("subscription_status") in LIVE:
        raise HTTPException(409, "Your church already has a plan. Change it in Setup, under Plan and billing.")
    return {"success_url": f"{billing_page()}?paid=1", "cancel_url": billing_page()}


def _iso(v: Any) -> Optional[str]:
    return str(v) if v else None


@router.get("/status")
def status(business_id: str, user: AuthedUser = Depends(require_user)):
    """The church's plan for its owner and team: what it is, what it opens,
    when it renews, and whether checkout is open to this person."""
    import feature_gates
    from worship_team import _uuid, roles_of
    biz_id = _uuid(business_id)
    roles_of(biz_id, user, part=None)
    biz = _church(biz_id, extra="stripe_subscription_id")
    if not biz:
        raise HTTPException(404, "business not found")
    plan = plan_of(biz)
    comp = (biz.get("comp_tier") or "").strip().lower()
    priced = {k: bool((os.environ.get(f"STRIPE_PRICE_ID_{k.upper()}") or "").strip()) for k in feature_gates.CHURCHSAVVY_PLANS}
    return {
        "standalone": standalone(biz), "held": _held(biz, user), "plan": plan, "plan_name": NAMES.get(plan or ""),
        "parts": sorted(parts(biz)), "comped": comp in feature_gates.CHURCHSAVVY_PLANS,
        "status": biz.get("subscription_status"), "trial_ends_at": _iso(biz.get("trial_ends_at")),
        "renews_at": _iso(biz.get("current_period_end")), "cancel_at_period_end": bool(biz.get("cancel_at_period_end")),
        "is_owner": str(biz.get("owner_id")) == str(user.id), "has_billing": bool(biz.get("stripe_customer_id")),
        "subscribed": bool((biz.get("stripe_subscription_id") or "").strip()) and biz.get("subscription_status") in LIVE,
        "checkout_open": checkout_open(user) and all(priced.values()),
        "plans": [{"key": k, "name": NAMES[k], "cents": PRICES[k], "parts": sorted(PARTS[k])} for k in feature_gates.CHURCHSAVVY_PLANS],
    }


class ChangeBody(BaseModel):
    business_id: str
    plan: str


@router.post("/change")
async def change_plan(body: ChangeBody, user: AuthedUser = Depends(require_user)):
    """The owner moves their church to another of ChurchSavvy's plans: the
    same subscription and card, Stripe prorating the month. The webhook
    writes it too; this writes it now so the page shows it at once."""
    import feature_gates
    import stripe_billing as sb
    from worship_team import _uuid
    plan = (body.plan or "").strip().lower()
    if plan not in feature_gates.CHURCHSAVVY_PLANS:
        raise HTTPException(400, "That isn't one of ChurchSavvy's plans.")
    if not checkout_open(user):
        raise HTTPException(409, "ChurchSavvy's plans aren't open yet.")
    biz_id = _uuid(body.business_id)
    biz = await sb._load_business(biz_id)
    sb._require_owner_of(user, biz)
    sub_id = (biz.get("stripe_subscription_id") or "").strip()
    if not standalone(biz) or not sub_id or biz.get("subscription_status") not in ("trialing", "active"):
        raise HTTPException(409, "Choose a plan first.")
    price = (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}") or "").strip()
    if not price:
        raise HTTPException(409, "That plan isn't open yet.")
    sub = await sb._stripe_get(f"/subscriptions/{quote(sub_id, safe='')}", [])
    items = ((sub.get("items") or {}).get("data")) or []
    if len(items) != 1 or feature_gates.price_to_plan().get(((items[0].get("price") or {}).get("id")) or "") \
            not in feature_gates.CHURCHSAVVY_PLANS:
        raise HTTPException(409, "This church's subscription isn't one of ChurchSavvy's plans.")
    if (items[0].get("price") or {}).get("id") == price:
        return {"plan": plan, "plan_name": NAMES[plan], "changed": False}
    updated = await sb._stripe_post(f"/subscriptions/{quote(sub_id, safe='')}", {
        "items": [{"id": items[0]["id"], "price": price}],
        "proration_behavior": "create_prorations",
        "cancel_at_period_end": False,
    })
    await sb._apply_subscription_state("customer.subscription.updated", updated, biz_id)
    return {"plan": plan, "plan_name": NAMES[plan], "changed": True}


SHORT = {"cs_screens": "ChurchSavvy", "cs_planning": "Planning", "cs_both": "Both"}


@router.get("/receipts")
async def receipts(business_id: str, user: AuthedUser = Depends(require_user)):
    """The church's last twelve bills (Plan and billing, board 16): when, for
    what, how much, paid or not, and Stripe's own receipt page. Owner only;
    nothing about the card."""
    import feature_gates
    import stripe_billing as sb
    from worship_team import _uuid
    biz = await sb._load_business(_uuid(business_id))
    sb._require_owner_of(user, biz)
    customer = (biz.get("stripe_customer_id") or "").strip()
    if not customer:
        return {"receipts": []}
    got = await sb._stripe_get("/invoices", [("customer", customer), ("limit", "12")])
    plans = feature_gates.price_to_plan()
    out = []
    for inv in got.get("data") or []:
        if inv.get("status") in ("draft", "void"):
            continue
        lines = ((inv.get("lines") or {}).get("data")) or []
        plan = plans.get(((lines[0].get("price") or {}).get("id")) or "") if lines else None
        out.append({
            "date": sb._ts_to_iso(inv.get("created")),
            "for": f"{SHORT[plan]}, one month" if plan in SHORT else "ChurchSavvy",
            "cents": inv.get("amount_paid") if inv.get("status") == "paid" else inv.get("amount_due"),
            "status": "paid" if inv.get("status") == "paid" else "due",
            "url": inv.get("hosted_invoice_url"),
        })
    return {"receipts": out}
