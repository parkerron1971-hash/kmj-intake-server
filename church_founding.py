"""church_founding.py — the founding churches keep the price they start at.

Kevin, 2026-11-13 ("yes founding prices ... go ahead"): the church plans are
cheap for what they carry, and the first churches are what proves it, so the
first FOUNDING_CHURCH_SPOTS (10) churches that pay for a church plan keep the
price they start at, for as long as they stay. The list price rises later
for new churches only.

What makes a church a founding church: its first PAID month on a church plan
(the webhook sees the subscription `active`), while a spot is left. A trial
holds no spot (it costs nothing to walk away from); a comped church and the
platform owner's own churches never take one. The place is written once, to
businesses.settings.founding_church = {n, at, plan, price_id}, and nothing
releases it: a founding church that cancels keeps its number, like a founding
move (church_billing).

Why a price can be kept at all: a church's plan is read from its Stripe price
id (feature_gates.price_to_plan). When a list price goes up, the new price
id goes into STRIPE_PRICE_ID_CHURCH_<SIZE>, and the old one would stop
meaning any plan. So the old id goes into STRIPE_PRICE_ID_CHURCH_<SIZE>_FOUNDING
first (docs/FOUNDING_CHURCHES.md): price_to_plan keeps reading it as the plan,
and checkout gives a founding church (or a church taking an open spot) that
price when it changes size. Unset, as today, every church pays the list price,
which is the founding price.

The free move is its own offer (pricing_config.founding_church_moves, the
first five who ask); this is the price.

The switch, FOUNDING_CHURCHES = on | off (default on): off takes the line off
the site and stops open spots getting the founding price. A church that
already holds a place keeps its price either way: off is a rollback of the
offer, never of a promise made.

The end (Kevin, 2026-11-14: "go with board C, Jan 31, build it"): the offer
closes when ten churches hold a place or at the end of FOUNDING_CHURCHES_UNTIL
(default 2027-01-31, the end of that day in US Eastern time), whichever comes
first. The site shows the regular price crossed out beside the founding price
only while it is open, so the regular price is the one every church pays
after it closes. Set FOUNDING_CHURCHES_UNTIL=none for no date.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException

logger = logging.getLogger("church_founding")

FOUNDING = "founding_church"   # businesses.settings[FOUNDING]: {n, at, plan, price_id}
_PUBLIC_TTL = 300               # the site's count may lag five minutes
_public: Dict[str, Any] = {"at": 0.0, "value": None}


def on() -> bool:
    return (os.environ.get("FOUNDING_CHURCHES") or "on").strip().lower() not in ("off", "0", "false", "no")


def spots() -> int:
    try:
        return max(0, int((os.environ.get("FOUNDING_CHURCH_SPOTS") or "10").strip()))
    except ValueError:
        return 10


_UNTIL_DEFAULT = "2027-01-31"
# The end of the last day in US Eastern time. January is standard time
# (UTC-5) every year, so the offset is fixed rather than read from a zone.
_EASTERN = timezone(timedelta(hours=-5))


def until() -> Optional[date]:
    """The offer's last day, or None for no end date (FOUNDING_CHURCHES_UNTIL=
    none). A value that doesn't parse keeps the default, never 'no end'."""
    raw = (os.environ.get("FOUNDING_CHURCHES_UNTIL") or _UNTIL_DEFAULT).strip()
    if raw.lower() in ("none", "off", "no", "never"):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        logger.warning("FOUNDING_CHURCHES_UNTIL=%r doesn't parse; using %s", raw, _UNTIL_DEFAULT)
        return date.fromisoformat(_UNTIL_DEFAULT)


def closes_at() -> Optional[datetime]:
    """When the offer closes: midnight Eastern at the end of until()."""
    last = until()
    if last is None:
        return None
    return datetime(last.year, last.month, last.day, tzinfo=_EASTERN) + timedelta(days=1)


def open_now(now: Optional[datetime] = None) -> bool:
    """The offer is on and its end date hasn't passed (the places left are
    counted separately: left())."""
    if not on():
        return False
    end = closes_at()
    return end is None or (now or datetime.now(timezone.utc)) < end


def ends_words(last: Optional[date] = None) -> str:
    """'January 31' for the site and the cards; '' when there's no date."""
    last = last or until()
    return f"{last:%B} {last.day}" if last else ""


def record(biz: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """This church's founding place, or None."""
    settings = (biz or {}).get("settings")
    rec = settings.get(FOUNDING) if isinstance(settings, dict) else None
    return rec if isinstance(rec, dict) else None


def taken() -> Optional[int]:
    """How many churches hold a founding place; None when unreadable."""
    import sb_clients
    try:
        rows = sb_clients.sb_get_all_as_service(f"/businesses?settings->{FOUNDING}=not.is.null&select=id")
    except Exception as e:  # noqa: BLE001 — a partial read is unread, never a count
        logger.warning("founding churches: count unreadable: %s", e)
        return None
    return len(rows) if isinstance(rows, list) else None


def left() -> Optional[int]:
    n = taken()
    return None if n is None else max(0, spots() - n)


def public_state() -> Optional[Dict[str, Any]]:
    """For the site and the plan cards: {spots, left, ends}, or None while the
    offer is off, past its end date, or the count can't be read (then nothing
    is promised). `ends` is the last day as an ISO date, or None."""
    if not open_now() or not spots():
        return None
    now = time.monotonic()
    if now - _public["at"] > _PUBLIC_TTL or _public["value"] is None:
        n = left()
        if n is None:
            return None
        _public.update(at=now, value=n)
    last = until()
    return {"spots": spots(), "left": int(_public["value"]), "ends": last.isoformat() if last else None}


def offer_prices() -> Optional[Dict[str, Dict[str, int]]]:
    """The founding price per church plan, {plan: {month_cents, year_cents}},
    while a place is open: None once the offer is off, past its date, full
    or unreadable. Only a plan whose founding price is below its regular
    price is in it, so nothing is shown crossed out that isn't a saving."""
    import feature_gates
    import marketing_pages as mp
    import pricing_config
    state = public_state()
    if not state or state["left"] <= 0:
        return None
    founding = pricing_config.church_founding_price_cents()
    regular = pricing_config.church_price_cents()
    out = {p: {"month_cents": founding[p], "year_cents": founding[p] * mp.ANNUAL_MONTHS}
           for p in feature_gates.CHURCH_PLANS if 0 < founding.get(p, 0) < regular.get(p, 0)}
    return out or None


def price_cents_for(biz: Optional[Dict[str, Any]], plan: Optional[str]) -> int:
    """What this church pays a month for `plan`: the founding price for a
    church holding a place (or already on a founding price), else the
    regular price. For the first payment and the move (three months of it)."""
    import pricing_config
    regular = pricing_config.church_price_cents().get(plan or "", 0)
    sub = str((biz or {}).get("subscription_plan") or "").strip()
    if record(biz) is not None or (sub and sub in founding_price_ids()):
        return pricing_config.church_founding_price_cents().get(plan or "", regular) or regular
    return regular


def forget() -> None:
    _public.update(at=0.0, value=None)


# ─── The founding prices ─────────────────────────────────────────────

def _env_key(plan: str, annual: bool) -> str:
    return f"STRIPE_PRICE_ID_{plan.upper()}{'_ANNUAL' if annual else ''}_FOUNDING"


def founding_price_id(plan: str, annual: bool) -> str:
    return (os.environ.get(_env_key(plan, annual)) or "").strip()


def founding_price_ids() -> Set[str]:
    import feature_gates
    return {pid for plan in feature_gates.CHURCH_PLANS for annual in (False, True)
            if (pid := founding_price_id(plan, annual))}


def _is_annual(plan: str, price_id: str) -> bool:
    return price_id in {(os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}_ANNUAL") or "").strip(),
                        founding_price_id(plan, True)} - {""}


async def checkout_price(biz: Dict[str, Any], plan: str, price_id: str) -> str:
    """The price a church pays for `plan` at checkout or on a change of size.
    A founding church, or a church taking an open spot while the offer is on,
    gets the founding price when one is set; everyone else the list price.
    Asking for a founding price without a place is refused, never quietly
    swapped."""
    annual = _is_annual(plan, price_id)
    eligible = record(biz) is not None
    if not eligible and open_now():
        n = await asyncio.to_thread(left)
        eligible = bool(n)
    if price_id in founding_price_ids() and not eligible:
        raise HTTPException(409, "The founding price is for the first churches, and those places are taken. "
                                 "Your plan's price is the one on the page.")
    if eligible:
        return founding_price_id(plan, annual) or price_id
    return price_id


# ─── Taking a place ──────────────────────────────────────────────────

def _owner_is_platform(owner_id: Any) -> Optional[bool]:
    """Whether this church is the platform owner's own (a test or Love City);
    None when the owner's address can't be read."""
    try:
        import platform_suite
        return platform_suite._is_platform_owner(owner_id)
    except Exception:  # noqa: BLE001 — unread: take no place this time
        return None


async def claim(business_id: str, plan: Optional[str], price_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Record a founding place for a church whose church-plan subscription
    is paid (`active`). Returns the place it holds, or None. Idempotent:
    the webhook sees every renewal, and a place is written once."""
    import church_billing
    import feature_gates
    import stripe_billing as sb
    if plan not in feature_gates.CHURCH_PLANS:
        return None
    biz = await sb._load_business(business_id)
    held = record(biz)
    if held:
        return held
    if (biz.get("comp_tier") or "").strip().lower() in feature_gates.ALL_PLANS:
        return None
    # Past the end date (or with the offer off) a place goes only to a church
    # already paying a founding price: one that chose its plan in time.
    if not open_now() and (price_id or "") not in founding_price_ids():
        return None
    owner = await asyncio.to_thread(_owner_is_platform, biz.get("owner_id"))
    if owner is not False:
        return None
    n = await asyncio.to_thread(taken)
    if n is None or n >= spots():
        return None
    place = {"n": n + 1, "at": datetime.now(timezone.utc).isoformat(), "plan": plan, "price_id": price_id}
    await church_billing._merge_setting(str(business_id), FOUNDING, place)
    forget()
    logger.info("founding church %s of %s: %s on %s", n + 1, spots(), business_id, plan)
    return place
