"""
billing_limits.py — Phase E v1.1 — the numeric-limit plumbing behind
PLAN_LIMITS (business caps, Chief message metering, seat caps).

Everything here is GATE-READY and DORMANT: with BILLING_ENFORCE off (the
default until pricing locks), every check answers "allowed" and every limit
reads as unlimited — but the counters are real, so the UI can already show
honest usage and enforcement is one env flip.

Plan resolution for caps is per-OWNER (a cap on "businesses" can't live on
a single business row): the owner's best-ranked plan across their
businesses wins.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

import sb_clients
import feature_gates

logger = logging.getLogger("billing_limits")

# Customer-facing plan names. The top tier's KEY stays 'practice'
# everywhere (env vars, Stripe lookup keys, required_plan in the 402
# payload — the frontend maps the key itself), but its NAME has been
# "Solutionist" since the 8/19 rename. The flip test caught the 402
# message still saying "Practice-plan feature".
PLAN_DISPLAY = {"starter": "Starter", "professional": "Professional",
                "practice": "Solutionist"}


def require_feature(business_id: str, feature: str) -> None:
    """The 402 gate for tier features — the first production caller of
    feature_gates.has_feature() (7/30 tier audit: the feature→tier map
    had ZERO callers, so every plan shipped identical software).

    GATE-READY + DORMANT like everything in this module: with
    BILLING_ENFORCE off has_feature() answers True and this never
    raises. Grandfathered owners always pass. Fails OPEN on lookup
    errors — a billing hiccup must never take a feature down. The 402
    payload shape is the contract the frontend's upgrade prompt reads:
    {error: "feature_locked", feature, required_plan, message}."""
    import usage_metering
    try:
        if not feature_gates.enforcement_on():
            return
        biz_row = usage_metering._biz_row(business_id)
        if usage_metering.is_grandfathered_business(business_id, biz_row):
            return
        if feature_gates.has_feature(biz_row, feature):
            return
    except Exception as e:
        logger.warning(f"require_feature({feature}) failed open: {e}")
        return
    min_plan = feature_gates.FEATURE_MIN_PLAN.get(feature, "professional")
    raise HTTPException(status_code=402, detail={
        "error": "feature_locked",
        "feature": feature,
        "required_plan": min_plan,
        "message": (f"This is a {PLAN_DISPLAY.get(min_plan, min_plan.title())}"
                    "-plan feature. Upgrade in Settings → Billing to unlock it."),
    })


def require_units(business_id: str) -> None:
    """The 402 gate for AI-action surfaces (compose, director, Chief).
    Delegates to the weighted metering gate — allowance first, then
    credits; grandfather, fail-open, and the BILLING_ENFORCE dormancy
    all live inside usage_metering.can_interact()."""
    if chief_can_send(business_id):
        return
    raise HTTPException(status_code=402, detail={
        "error": "out_of_units",
        "message": ("You're out of AI actions for this month. Top up "
                    "credits in Settings → Billing to keep going — "
                    "bookings, invoices, and bookkeeping never stop."),
    })


def require_chat_fair_use(business_id: str) -> None:
    """The per-day runaway brake on Chief chat (see
    usage_metering.chat_fair_use_ok for the full reasoning).

    A 429, NOT a 402: this is rate limiting, not billing. The
    practitioner has not run out of anything and must never be shown an
    upgrade prompt for tripping it — a human at the opening ceiling of
    250 turns/day is not a customer to upsell, it is a loop to stop.
    The Retry-After header is the honest answer: the window is the UTC
    day, so the brake lifts at midnight."""
    import usage_metering
    if usage_metering.chat_fair_use_ok(business_id):
        return
    raise HTTPException(status_code=429, detail={
        "error": "chat_daily_limit",
        "message": ("Chief has hit today's message limit for this "
                    "business. It resets at midnight UTC — if this "
                    "wasn't you, something may be sending on a loop."),
    }, headers={"Retry-After": "3600"})


def require_live_access(business_id: str) -> None:
    """The 402 gate for a LOCKED subscription (canceled / trial expired).
    Until now access_state was advisory — the frontend showed the paywall
    while a valid JWT kept full API access. Grace passes (warn upstream,
    don't block); dormant while BILLING_ENFORCE is off; fails open."""
    import usage_metering
    try:
        if not feature_gates.enforcement_on():
            return
        biz_row = usage_metering._biz_row(business_id)
        gf = usage_metering.is_grandfathered_business(business_id, biz_row)
        state = feature_gates.access_state(biz_row, gf)
    except Exception as e:
        logger.warning(f"require_live_access failed open: {e}")
        return
    if (state or {}).get("state") != "locked":
        return
    raise HTTPException(status_code=402, detail={
        "error": "subscription_locked",
        "reason": (state or {}).get("reason"),
        "message": ("This account's subscription has ended. Restart it in "
                    "Settings → Billing to keep using AI features and "
                    "campaigns — your data is safe and exports stay open."),
    })


def _month_start_iso() -> str:
    """First instant of THIS month (UTC), Z form.

    Second copy of the meter-reads-zero bug (see the long note on
    usage_metering._month_start_iso): the bare .isoformat() emitted
    `+00:00`, which decodes as a space in a query string and made
    chief_messages_this_month() below return 0 for every business."""
    now = datetime.now(timezone.utc)
    return (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
               .isoformat().replace("+00:00", "Z"))


def owner_best_plan_row(owner_id: str) -> Optional[Dict[str, Any]]:
    """The owned business row whose subscription resolves to the highest
    tier (None if no business resolves to a plan)."""
    # comp_tier is IN the select on purpose — the flip test (2026-08-22)
    # caught a comped Solutionist business resolving to NO plan here, so
    # its owner was capped at 1 business instead of 3. plan_of() reads
    # comp_tier first; a select that omits the column silently disables
    # every comp account for whatever cap the row feeds. Same class as
    # the wrong-column-reads-as-missing-row outage: prefer select=* or
    # carry every column plan_of() consumes.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?owner_id=eq.{owner_id}&is_active=eq.true"
        f"&select=id,subscription_status,subscription_plan,comp_tier&limit=100") or []
    best, best_rank = None, 0
    for r in rows:
        plan = feature_gates.plan_of(r)
        rank = feature_gates._PLAN_RANK.get(plan or "", 0)
        if rank > best_rank:
            best, best_rank = r, rank
    return best


def business_count(owner_id: str) -> int:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?owner_id=eq.{owner_id}&is_active=eq.true&select=id&limit=100") or []
    return len(rows)


def can_create_business(owner_id: str) -> Dict[str, Any]:
    """Cap check for creating ANOTHER business. Unenforced → always allowed.
    Phase B: creation is now backend-mediated (/access/businesses/create)
    so this check is REAL; grandfathered owners bypass entirely."""
    import usage_metering
    if usage_metering.is_grandfathered_user(owner_id):
        return {"ok": True, "allowed": True, "count": business_count(owner_id),
                "limit": None, "plan": None, "grandfathered": True,
                "enforce": feature_gates.enforcement_on()}
    count = business_count(owner_id)
    best = owner_best_plan_row(owner_id)
    plan = feature_gates.plan_of(best) if best else None
    limit = feature_gates.limit_for(best, "max_businesses")
    allowed = (limit is None) or (count < limit)
    return {"ok": True, "allowed": allowed, "count": count, "limit": limit,
            "plan": plan, "enforce": feature_gates.enforcement_on()}


# ─── Chief message metering ──────────────────────────────────────────

def chief_messages_this_month(business_id: str) -> int:
    """Count of AI calls logged for this business since the 1st (UTC).
    The window is computed, so the counter 'resets' on the first of the
    month with no state to maintain."""
    # Paginated: the old single limit=5000 read silently under-counted
    # past 5k rows/month. Terminates on the first short page.
    total, offset, page = 0, 0, 5000
    while offset <= 200_000:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}"
            f"&created_at=gte.{_month_start_iso()}&select=id"
            f"&limit={page}&offset={offset}") or []
        total += len(rows)
        if len(rows) < page:
            break
        offset += page
    return total


def chief_usage(business_id: str, biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if biz_row is None:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            f"&select=id,subscription_status,subscription_plan,comp_tier&limit=1") or []
        biz_row = rows[0] if rows else None
    used = chief_messages_this_month(business_id)
    limit = feature_gates.limit_for(biz_row, "chief_messages_monthly")
    return {
        "ok": True, "used": used, "limit": limit,
        "remaining": None if limit is None else max(0, limit - used),
        "month": _month_start_iso()[:7],
        "enforce": feature_gates.enforcement_on(),
        "plan": feature_gates.plan_of(biz_row),
    }


def chief_can_send(business_id: str) -> bool:
    """Phase B: delegates to the WEIGHTED metering gate (allotment + the
    2x-bill cap + practitioner hard cap + grandfather bypass)."""
    import usage_metering
    return usage_metering.can_interact(business_id)


def can_connect_account(business_id: str,
                        biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """F-A2 — Plaid connected-account limit per tier (2 / 5 / unlimited).
    Gate-ready: unenforced + grandfathered → always allowed."""
    import usage_metering
    if biz_row is None:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            f"&select=id,owner_id,subscription_status,subscription_plan,comp_tier&limit=1") or []
        biz_row = rows[0] if rows else None
    if usage_metering.is_grandfathered_business(business_id, biz_row):
        return {"ok": True, "allowed": True, "count": None, "limit": None,
                "grandfathered": True}
    accts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}&deleted_at=is.null"
        f"&select=account_id&limit=200") or []
    limit = feature_gates.limit_for(biz_row, "plaid_connections")
    allowed = (limit is None) or (len(accts) < limit)
    return {"ok": True, "allowed": allowed, "count": len(accts), "limit": limit,
            "enforce": feature_gates.enforcement_on()}


# ─── Seats ───────────────────────────────────────────────────────────

def seat_count(business_id: str) -> int:
    """Active + invited seats, owner included (the owner is always seat 1)."""
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{business_id}"
        f"&status=in.(invited,active)&select=id&limit=200") or []
    return 1 + len(rows)


def can_add_seat(business_id: str, biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if biz_row is None:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            f"&select=id,subscription_status,subscription_plan,comp_tier&limit=1") or []
        biz_row = rows[0] if rows else None
    count = seat_count(business_id)
    limit = feature_gates.limit_for(biz_row, "max_seats")
    allowed = (limit is None) or (count < limit)
    return {"ok": True, "allowed": allowed, "count": count, "limit": limit,
            "enforce": feature_gates.enforcement_on()}
