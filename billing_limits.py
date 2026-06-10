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

import sb_clients
import feature_gates

logger = logging.getLogger("billing_limits")


def _month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def owner_best_plan_row(owner_id: str) -> Optional[Dict[str, Any]]:
    """The owned business row whose subscription resolves to the highest
    tier (None if no business resolves to a plan)."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?owner_id=eq.{owner_id}&is_active=eq.true"
        f"&select=id,subscription_status,subscription_plan&limit=100") or []
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
    rows = sb_clients.sb_get_as_service(
        f"/api_usage?business_id=eq.{business_id}"
        f"&created_at=gte.{_month_start_iso()}&select=id&limit=5000") or []
    return len(rows)


def chief_usage(business_id: str, biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if biz_row is None:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            f"&select=id,subscription_status,subscription_plan&limit=1") or []
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
            f"&select=id,owner_id,subscription_status,subscription_plan&limit=1") or []
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
            f"&select=id,subscription_status,subscription_plan&limit=1") or []
        biz_row = rows[0] if rows else None
    count = seat_count(business_id)
    limit = feature_gates.limit_for(biz_row, "max_seats")
    allowed = (limit is None) or (count < limit)
    return {"ok": True, "allowed": allowed, "count": count, "limit": limit,
            "enforce": feature_gates.enforcement_on()}
