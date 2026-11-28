"""church_billing.py — the extras around the church plans.

Kevin, 2026-11-03 ("I agree with the plan"; the review artifact
Pdg8hF4pB5n6efoFQmzd8d):

  * One more office login, $15 a month each (pricing_config.extra_login_cents),
    for a church between sizes that doesn't want to move up a plan. It is a
    second item on the church's own subscription, so Stripe prorates it and
    the webhook keeps the count (businesses.settings.extra_logins), which
    billing_limits.can_add_seat adds to the plan's logins. Stripe holds one
    subscription to one billing term, so the login has a price for each term
    the plans are sold in (LOGIN_PRICE_ENVS): a church paying by the year
    pays for its logins by the year. A login added is paid for that day.
  * The move from another system: three months of the plan
    (church_move_months), free for the first five churches that ask (the
    founding churches, founding_church_moves). Paid or free, the request
    lands in Mission Control as a support ticket, and the church's settings
    keep where it stands (businesses.settings.church_move).

Kevin, 2026-11-17 ("build"):

  * 100 GB more storage, $5 a month a block (pricing_config.extra_storage_offer),
    on top of the plan's storage allowance (church_storage). Built exactly as
    the login is: another item on the church's subscription, quantity = the
    number of blocks, a price per term (STORAGE_PRICE_ENVS), paid the day it
    is added, the webhook keeping the count (businesses.settings.extra_storage),
    which church_storage.extra_bytes adds to the allowance. One difference: an
    unreadable count is never read as 0 there (extra_storage_blocks answers
    None), so the storage rules decide nothing on a guess. Taking blocks off
    is allowed even when it puts the church over; the answer says what that
    means (the 14-day rule for a recording made while over).

Only for a church on a church plan (feature_gates.CHURCH_PLANS); every route
is the owner's (stripe_billing._require_owner_of). Nothing here is sold
until the church plans are: the extra-login price needs
STRIPE_PRICE_ID_EXTRA_LOGIN, extra storage STRIPE_PRICE_ID_EXTRA_STORAGE,
and the move needs a church plan.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
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
EXTRA_STORAGE = "extra_storage"  # businesses.settings[EXTRA_STORAGE]: int, blocks of 100 GB bought
MOVE = "church_move"            # businesses.settings[MOVE]: where the move stands
MAX_STORAGE_BLOCKS = 100        # 10 TB on top of a plan: far past any church today


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


def storage_blocks_value(v: Any) -> Optional[int]:
    """A stored count of storage blocks: a whole number 0 or more (a
    numeric string too, as extra_logins reads); nothing stored is 0. None
    for anything else: unreadable, never taken as 0."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float):
        return int(v) if v.is_integer() and v >= 0 else None
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def extra_storage_blocks(biz: Optional[Dict[str, Any]]) -> Optional[int]:
    """Blocks of 100 GB the church bought on top of its plan's storage
    (businesses.settings.extra_storage). 0 when none. None when it can't be
    told (no row, no settings read, a value that isn't a count): unlike a
    login, never read as 0, because 0 would make the church look fuller
    than it is and the storage rules hold and remove recordings on it."""
    if not isinstance(biz, dict) or "settings" not in biz:
        return None
    s = biz.get("settings")
    if s is None:
        return 0
    if not isinstance(s, dict):
        return None
    return storage_blocks_value(s.get(EXTRA_STORAGE))


def is_church(biz: Optional[Dict[str, Any]]) -> bool:
    import vertical_registry
    return vertical_registry.resolve((biz or {}).get("type") or "") == "ministry"


# A term is how often a price bills, as stripe_billing._term_of reads it.
MONTHLY = ("month", 1)
QUARTERLY = ("month", 3)
YEARLY = ("year", 1)
LOGIN_PRICE_ENVS = {MONTHLY: "STRIPE_PRICE_ID_EXTRA_LOGIN",
                    QUARTERLY: "STRIPE_PRICE_ID_EXTRA_LOGIN_QUARTERLY",
                    YEARLY: "STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL"}
STORAGE_PRICE_ENVS = {MONTHLY: "STRIPE_PRICE_ID_EXTRA_STORAGE",
                      QUARTERLY: "STRIPE_PRICE_ID_EXTRA_STORAGE_QUARTERLY",
                      YEARLY: "STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL"}


def _price_on(envs: Dict[tuple, str], term: tuple) -> str:
    env = envs.get(tuple(term))
    return (os.environ.get(env) or "").strip() if env else ""


def _prices_on(envs: Dict[tuple, str]) -> set:
    return {p for term in envs if (p := _price_on(envs, term))}


def _per_term(cents: int, term: tuple) -> int:
    """A monthly price as a plan on this term bills it: three of it every
    three months, or ten months of it for a year, as the plans are."""
    if tuple(term) == YEARLY:
        import marketing_pages as mp
        return cents * mp.ANNUAL_MONTHS
    if tuple(term) == QUARTERLY:
        return cents * 3
    return cents


def every_word(term: tuple) -> str:
    """How the answer names a term: month, quarter (every three months) or year."""
    return "quarter" if tuple(term) == QUARTERLY else tuple(term)[0]


def extra_login_price(term: tuple = MONTHLY) -> str:
    """The login's Stripe price for a plan billed on this term, or ""."""
    return _price_on(LOGIN_PRICE_ENVS, term)


def extra_login_prices() -> set:
    """Every login price that is set, whichever term it bills on."""
    return _prices_on(LOGIN_PRICE_ENVS)


def extra_login_cents(term: tuple = MONTHLY) -> int:
    """What one extra login costs each time a plan on this term bills: the
    monthly price, three of it every three months, or ten months of it for
    a year, as the plans are."""
    return _per_term(pricing_config.extra_login_cents(), term)


def extra_storage_price(term: tuple = MONTHLY) -> str:
    """The storage block's Stripe price for a plan billed on this term, or ""."""
    return _price_on(STORAGE_PRICE_ENVS, term)


def extra_storage_prices() -> set:
    """Every storage price that is set, whichever term it bills on."""
    return _prices_on(STORAGE_PRICE_ENVS)


def extra_storage_cents(term: tuple = MONTHLY) -> int:
    """What one block of storage costs each time a plan on this term bills."""
    return _per_term(pricing_config.extra_storage_offer()["cents"], term)


def _price_id(item) -> Optional[str]:
    return ((item or {}).get("price") or {}).get("id")


def _quantity_on(prices: set, items) -> int:
    if not prices:
        return 0
    return sum(int(it.get("quantity") or 0) for it in (items or []) if _price_id(it) in prices)


def extra_login_quantity(items) -> int:
    """How many extra logins a subscription's items carry."""
    return _quantity_on(extra_login_prices(), items)


def extra_storage_quantity(items) -> int:
    """How many blocks of storage a subscription's items carry."""
    return _quantity_on(extra_storage_prices(), items)


def plan_term(items) -> tuple:
    """The term the church's plan bills on, from its subscription's items.
    Monthly when it can't be told, which is what every plan was."""
    import stripe_billing as sb
    catalog = feature_gates.price_to_plan()
    plan_item = next((it for it in (items or []) if _price_id(it) in catalog), None)
    term = sb._term_of((plan_item or {}).get("price"))
    return term if term[0] else MONTHLY


def row_term(biz: Optional[Dict[str, Any]]) -> tuple:
    """The term the church's plan bills on, from the plan price its row
    holds (stripe_billing._price_plans reads the env names; Stripe is not
    asked). Monthly when it can't be told, as plan_term."""
    import stripe_billing as sb
    pid = str((biz or {}).get("subscription_plan") or "").strip()
    every = (sb._price_plans().get(pid) or {}).get("every") if pid else None
    return {"year": YEARLY, "quarter": QUARTERLY}.get(every or "", MONTHLY)


def _follow_term(envs: Dict[tuple, str], items, term: tuple, refusal: str) -> list:
    prices = _prices_on(envs)
    held = [it for it in (items or []) if _price_id(it) in prices]
    if not held:
        return []
    to = _price_on(envs, term)
    if not to:
        raise HTTPException(409, refusal)
    return [{"id": it["id"], "price": to} for it in held if _price_id(it) != to]


def logins_for_term(items, term: tuple) -> list:
    """A plan is changing term (monthly to yearly, or back): the item changes
    that take its extra logins along, [] when it has none. Refused, before
    Stripe is asked, when the logins have no price on the new term."""
    return _follow_term(LOGIN_PRICE_ENVS, items, term,
                        "Your extra office logins can't follow that change from here yet. "
                        "Write to us and we'll switch you over.")


def storage_for_term(items, term: tuple) -> list:
    """The same for the church's extra storage: its blocks move to the
    price on the new term, or the change is refused before Stripe is asked."""
    return _follow_term(STORAGE_PRICE_ENVS, items, term,
                        "Your extra storage can't follow that change from here yet. "
                        "Write to us and we'll switch you over.")


async def _merge_setting(business_id: str, key: str, value: Any) -> None:
    """Write one key of businesses.settings (None removes it) and touch no
    other, in one UPDATE in the database (business_settings.merge). It used to
    read the row and write the whole object back, and so did every other
    writer: the first church's founding place, written here, was dropped by a
    whole-object write from a copy read before it (2026-11-16)."""
    import business_settings
    if value is None:
        done = await business_settings.amerge(business_id, drop=[key])
    else:
        done = await business_settings.amerge(business_id, {key: value})
    if done is None:
        logger.error(f"settings.{key} for {business_id} did not save")
        raise HTTPException(status_code=502, detail="Failed to update business")


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


async def held_subscription(business_id: str) -> Tuple[bool, str]:
    """(read, the subscription id the church's row holds), read before a
    webhook's patch overwrites it: sync_extra_storage lowers the count only
    from the church's own subscription. (False, "") when unreadable."""
    try:
        import stripe_billing as sb
        biz = await sb._load_business(business_id)
        return True, str(biz.get("stripe_subscription_id") or "").strip()
    except Exception as e:  # noqa: BLE001  (unread: the count is never lowered on it)
        print(f"[church_billing] subscription held by {str(business_id)[:8]} unread: {type(e).__name__}", flush=True)
        return False, ""


def has_storage_item(items) -> bool:
    """The subscription carries an item on a storage price we know."""
    prices = extra_storage_prices()
    return bool(prices) and any(_price_id(it) in prices for it in (items or []))


async def sync_extra_storage(business_id: str, items, status: Optional[str], *,
                             sub_id: Optional[str] = None,
                             held_before: Optional[Tuple[bool, str]] = None) -> None:
    """The same for extra storage, from the subscription as Stripe holds it
    (the webhook): the blocks it carries, 0 once it is cancelled. Writes
    only when it changed. Never raises.

    The count is read off the items by their price ids, which come from the
    env. A storage price var missing or changed would make the blocks Stripe
    still bills look like none, and a lower count makes the church look
    over its room, where the 14-day rule removes recordings. So the count is
    raised (or a value that isn't a count replaced by one) from a storage
    item we recognise, and LOWERED only on positive evidence:
      * no storage price is configured: nothing is written at all;
      * an item whose price isn't a known plan, login or storage price is
        on the subscription: never lowered (it could be the blocks);
      * otherwise lowered when a recognised storage item shows the lower
        quantity (not cancelled), or when every item is recognised and the
        subscription is clearly the church's own: it carries a church plan
        price and it is the subscription the church's row held before this
        event (`held_before`, read before the webhook's patch; None or an
        unread row is never clearly its own). A cancelled subscription goes
        to 0 only by that second rule.
    Each skip is print()ed with why."""
    bid = str(business_id)[:8]
    try:
        storage = extra_storage_prices()
        if not storage:
            print(f"[church_billing] extra storage for {bid} not synced: no storage price is configured", flush=True)
            return
        plans = feature_gates.price_to_plan()
        known = set(plans) | extra_login_prices() | storage
        unknown = sorted({str(_price_id(it)) for it in (items or []) if _price_id(it) not in known})
        recognised = has_storage_item(items)
        count = 0 if status == "canceled" else extra_storage_quantity(items)
        import stripe_billing as sb
        biz = await sb._load_business(business_id)
        stored = extra_storage_blocks(biz)
        if stored == count:
            return
        if stored is None or count < stored:
            church_plan = any(plans.get(_price_id(it) or "") in feature_gates.CHURCH_PLANS for it in (items or []))
            own = (church_plan and bool(sub_id) and held_before is not None and held_before[0]
                   and held_before[1] in ("", str(sub_id)))
            why = None
            if unknown:
                why = f"the subscription has items on prices we don't know ({', '.join(unknown)[:200]})"
            elif not (recognised and status != "canceled") and not own:
                why = ("no storage item shows the lower count, and the subscription isn't clearly the church's "
                       "own (a church plan price, and the one its row held)")
            if why:
                print(f"[church_billing] extra storage for {bid} kept at {stored} (Stripe event shows {count}): "
                      f"{why}", flush=True)
                return
        await _merge_setting(business_id, EXTRA_STORAGE, count or None)
        print(f"[church_billing] extra storage for {bid}: {stored} -> {count} blocks", flush=True)
    except Exception as e:
        print(f"[church_billing] extra storage sync for {bid} failed (non-fatal): "
              f"{type(e).__name__}: {e}", flush=True)


# ─── One more login ───────────────────────────────────────────────────

class ExtraLoginsBody(BaseModel):
    business_id: str
    count: int = Field(ge=0, le=100)


async def _church_on_a_plan(business_id: str, user: AuthedUser,
                            refusal: str = "Extra office logins and the move come with the church plans."
                            ) -> Dict[str, Any]:
    import stripe_billing as sb
    biz = await sb._load_business(business_id)
    sb._require_owner_of(user, biz)
    if feature_gates.plan_of(biz) not in feature_gates.CHURCH_PLANS:
        raise HTTPException(409, refusal)
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
    item on its subscription, priced for the term the plan bills on: $15 a
    month each, or ten months of that for a year. More logins are paid for
    today, for what is left of the term, and only added if the card takes it
    (stripe_billing.PAID_TODAY); fewer leave a credit for the next bill."""
    import stripe_billing as sb
    biz = await _church_on_a_plan(body.business_id, user)
    held = extra_login_prices()
    if not held:
        raise HTTPException(409, "Extra office logins aren't open yet.")
    sub_id = (biz.get("stripe_subscription_id") or "").strip()
    if not sub_id:
        raise HTTPException(409, "Extra office logins are added to a paid church plan.")
    sub = await sb._stripe_get(f"/subscriptions/{sub_id}", [])
    items = ((sub.get("items") or {}).get("data")) or []
    term = plan_term(items)
    price = extra_login_price(term)
    item = next((it for it in items if _price_id(it) in held), None)
    had = int((item or {}).get("quantity") or 0)
    if body.count > had and not price:
        raise HTTPException(409, "Extra office logins aren't open on a plan paid this way yet. "
                                 "Write to us and we'll add them for you.")
    paid_today = body.count > had and sub.get("status") == "active"
    how = dict(sb.PAID_TODAY) if paid_today else {"proration_behavior": "create_prorations"}
    try:
        if item and body.count == 0:
            await _stripe_delete(f"/subscription_items/{item['id']}")
        elif item:
            await sb._stripe_post(f"/subscription_items/{item['id']}", {"quantity": body.count, **how})
        elif body.count > 0:
            await sb._stripe_post("/subscription_items", {"subscription": sub_id, "price": price,
                                                         "quantity": body.count, **how})
    except HTTPException as e:
        if paid_today and e.status_code == 402:
            raise HTTPException(402, sb.CARD_REFUSED)
        raise
    # The webhook writes the same number when Stripe confirms; this makes the
    # new login usable now instead of a webhook later.
    await _merge_setting(str(biz["id"]), EXTRA_LOGINS, body.count or None)
    base = feature_gates._limits_of(feature_gates.plan_of(biz)).get("max_seats")
    return {"ok": True, "extra_logins": body.count,
            "max_seats": (base + body.count) if base is not None else None,
            "cents_each": extra_login_cents(term),
            "every": every_word(term),
            "charged_today": paid_today}


# ─── More storage ─────────────────────────────────────────────────────

class ExtraStorageBody(BaseModel):
    business_id: str
    blocks: int = Field(ge=0, le=MAX_STORAGE_BLOCKS)


def _storage_unchanged(business_id: str, e: HTTPException) -> HTTPException:
    """Stripe refused or couldn't be reached: the church reads plain words
    (never Stripe's own text, which is printed for Railway instead), with
    the same status."""
    print(f"[church_billing] extra storage for {str(business_id)[:8]} unchanged: {e.status_code} "
          f"{str(e.detail)[:200]}", flush=True)
    return HTTPException(e.status_code if 400 <= e.status_code < 600 else 502,
                         "Your storage didn't change. Try again in a minute, or write to us.")


def _over_after(business_id: str, blocks: int) -> tuple:
    """After blocks were taken off: (over, words). over is True when the
    church now uses more than its plan's storage plus `blocks`, False when
    it doesn't, None when that couldn't be measured (or storage isn't
    switched on for it: then nothing is held either). The words say what
    the 14-day rule means for it, or None when there's nothing to say."""
    import church_storage as cs
    try:
        if not cs.switched_on(business_id):
            return None, None
        meter = cs.used(business_id)
        allowance = (meter or {}).get("allowance_bytes")
        if meter is None or allowance is None or not meter.get("complete"):
            return None, cs.fewer_blocks_words(None)
        total = int(allowance) + blocks * cs.block_bytes()
        if int(meter["used_bytes"]) > total:
            return True, cs.fewer_blocks_words(True)
        return False, None
    except Exception as e:  # noqa: BLE001  (the change is made; the answer still says what it can)
        print(f"[church_billing] storage after fewer blocks unread for {str(business_id)[:8]}: "
              f"{type(e).__name__}", flush=True)
        return None, cs.fewer_blocks_words(None)


@router.post("/extra-storage")
async def set_extra_storage(body: ExtraStorageBody, user: AuthedUser = Depends(require_user)):
    """Set how many blocks of 100 GB the church buys on top of its plan's
    storage, the way set_extra_logins sets logins: an item on its
    subscription, priced for the term the plan bills on ($5 a month a block,
    ten months of that for a year). More is paid for today, for what is left
    of the term, and only added if the card takes it; fewer leave a credit
    for the next bill. Fewer is allowed even when it puts the church over
    its storage: nothing is deleted then, and the answer says (`over`,
    `note`) that a recording made while over is kept 14 days, then deleted
    unless room is made (church_storage's rule). More needs storage to be
    switched on for the church (church_storage.switched_on)."""
    import stripe_billing as sb
    import church_storage as cs
    biz = await _church_on_a_plan(body.business_id, user, "Extra storage comes with the church plans.")
    bid = str(biz["id"])
    held = extra_storage_prices()
    if not held:
        raise HTTPException(409, "Extra storage isn't open yet.")
    sub_id = (biz.get("stripe_subscription_id") or "").strip()
    if not sub_id:
        raise HTTPException(409, "Extra storage is added to a paid church plan.")
    try:
        sub = await sb._stripe_get(f"/subscriptions/{quote(sub_id, safe='')}", [])
    except HTTPException as e:
        raise _storage_unchanged(bid, e)
    items = ((sub.get("items") or {}).get("data")) or []
    term = plan_term(items)
    price = extra_storage_price(term)
    item = next((it for it in items if _price_id(it) in held), None)
    had = int((item or {}).get("quantity") or 0)
    if body.blocks > had:
        if not price:
            raise HTTPException(409, "Extra storage isn't open on a plan paid this way yet. "
                                     "Write to us and we'll add it for you.")
        if not await asyncio.to_thread(cs.switched_on, bid):
            raise HTTPException(409, "Extra storage isn't open yet.")
    paid_today = body.blocks > had and sub.get("status") == "active"
    how = dict(sb.PAID_TODAY) if paid_today else {"proration_behavior": "create_prorations"}
    try:
        if item and body.blocks == 0:
            await _stripe_delete(f"/subscription_items/{item['id']}")
        elif item:
            await sb._stripe_post(f"/subscription_items/{item['id']}", {"quantity": body.blocks, **how})
        elif body.blocks > 0:
            await sb._stripe_post("/subscription_items", {"subscription": sub_id, "price": price,
                                                         "quantity": body.blocks, **how})
    except HTTPException as e:
        if paid_today and e.status_code == 402:
            raise HTTPException(402, sb.CARD_REFUSED)
        raise _storage_unchanged(bid, e)
    # The webhook writes the same number when Stripe confirms; this makes the
    # room count now instead of a webhook later. The subscription has changed
    # by here, so a write that fails doesn't say the change failed: the
    # webhook's sync_extra_storage writes the count from the subscription.
    try:
        await _merge_setting(bid, EXTRA_STORAGE, body.blocks or None)
    except HTTPException:
        print(f"[church_billing] extra storage for {bid[:8]} is {body.blocks} blocks at Stripe; "
              f"the count waits for the webhook", flush=True)
    over, note = (None, None)
    if body.blocks < had:
        over, note = await asyncio.to_thread(_over_after, bid, body.blocks)
    print(f"[church_billing] extra storage for {bid[:8]}: {had} -> {body.blocks} blocks"
          f"{' (over)' if over else ''}", flush=True)
    return {"ok": True, "extra_storage": body.blocks,
            "extra_bytes": body.blocks * cs.block_bytes(),
            "gb_each": pricing_config.extra_storage_offer()["gb"],
            "cents_each": extra_storage_cents(term),
            "every": every_word(term),
            "charged_today": paid_today,
            "over": over, "note": note}


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
    # A kept price is read from Stripe once (church_founding.kept_price); off the loop.
    await asyncio.to_thread(church_founding.kept_price, str(biz.get("subscription_plan") or ""))
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
    import church_founding
    await asyncio.to_thread(church_founding.kept_price, str(biz.get("subscription_plan") or ""))
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
