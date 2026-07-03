"""
usage_metering.py — Arc 19 Phase B — weighted Chief-interaction metering
per the LOCKED pricing model (docs/pricing_model.md).

THE UNIT: one "Chief interaction" — a weighted count over api_usage rows:
    chat / bookkeeping Chief / proxy call = 1
    hero regeneration                     = 5
    full site build-with-loop             = 25
Weights key on the logged endpoint (no schema change; aggregation-time
lookup). Everything else on the platform is unmetered by design.

THE PROMISE: total monthly bill ≤ 2× plan price. Overage is per-tier flat
($0.40 / $0.30 / $0.25); the cap converts to a max-unit ceiling
(allotment + tier_price / overage_rate). Past the cap — or past the
allotment when the practitioner set their own hard cap — AI interactions
soft-block; bookings, invoices, bookkeeping NEVER stop.

GRANDFATHER: pre-launch accounts (user_profiles.is_grandfathered) get
unlimited usage + all features, forever, regardless of subscription.

DORMANCY: like all of Phase E, blocking + Stripe reporting activate only
with BILLING_ENFORCE=on. The counters and the usage UI are live always.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sb_clients
import feature_gates

logger = logging.getLogger("usage_metering")

# Endpoint → unit weight (default 1). Disclosed at point of use in the UI.
UNIT_WEIGHTS: Dict[str, int] = {
    "/composer/hero": 5,
    "/director/build": 25,
}
DEFAULT_WEIGHT = 1

# Overage rate (cents/unit) per tier — LOCKED 2026-06-10.
OVERAGE_CENTS = {"starter": 40, "professional": 30, "practice": 25}
TIER_PRICE_CENTS = {"starter": 7900, "professional": 19900, "practice": 39900}

THRESHOLDS = (50, 80, 100, 200)  # % of allotment; 200 ≈ the cap milestone


def _month_key(now: Optional[datetime] = None) -> str:
    n = now or datetime.now(timezone.utc)
    return f"{n.year:04d}-{n.month:02d}"


def _month_start_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def weight_for(endpoint: Optional[str]) -> int:
    return UNIT_WEIGHTS.get((endpoint or "").strip(), DEFAULT_WEIGHT)


def weighted_usage_this_month(business_id: str) -> int:
    rows = sb_clients.sb_get_as_service(
        f"/api_usage?business_id=eq.{business_id}"
        f"&created_at=gte.{_month_start_iso()}&select=endpoint&limit=10000") or []
    return sum(weight_for(r.get("endpoint")) for r in rows)


def _biz_row(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,owner_id,settings,subscription_status,subscription_plan,"
        f"stripe_subscription_id,comp_tier&limit=1") or []
    if rows:
        return rows[0]
    # comp_tier column absent (launch-ops migration not applied yet) —
    # PostgREST 400s on unknown columns; retry without it.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,owner_id,settings,subscription_status,subscription_plan,"
        f"stripe_subscription_id&limit=1") or []
    return rows[0] if rows else None


def grant_units_this_month(business_id: str) -> int:
    """Owner-granted bonus units (usage_grants table): rows with month
    NULL apply every month; rows with month == current 'YYYY-MM' apply
    that month only. Fails open to 0 when the table doesn't exist."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/usage_grants?business_id=eq.{business_id}"
            f"&or=(month.is.null,month.eq.{_month_key()})"
            f"&select=units&limit=200") or []
        return sum(int(r.get("units") or 0) for r in rows)
    except Exception:
        return 0


def is_grandfathered_user(user_id: Optional[str]) -> bool:
    if not user_id:
        return False
    rows = sb_clients.sb_get_as_service(
        f"/user_profiles?user_id=eq.{user_id}&is_grandfathered=is.true"
        f"&select=user_id&limit=1") or []
    return bool(rows)


def is_grandfathered_business(business_id: str,
                              biz_row: Optional[Dict[str, Any]] = None) -> bool:
    """Grandfather is per-USER and covers every business they own."""
    row = biz_row or _biz_row(business_id)
    return is_grandfathered_user(str((row or {}).get("owner_id") or "")) if row else False


def usage_summary(business_id: str,
                  biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything the UI + enforcement need in one read. Allotment/overage
    numbers show from the PLAN even while enforcement is dormant (the UI
    is honest early); `blocked` only ever true when enforcing."""
    row = biz_row or _biz_row(business_id)
    used = weighted_usage_this_month(business_id)
    grandfathered = is_grandfathered_business(business_id, row)
    plan = feature_gates.plan_of(row) if row else None
    enforce = feature_gates.enforcement_on()

    allotment = None
    overage_cents_rate = None
    cap_units = None
    if plan:
        allotment = (feature_gates.PLAN_LIMITS.get(plan) or {}).get("chief_messages_monthly")
        overage_cents_rate = OVERAGE_CENTS.get(plan)
        if allotment is not None and overage_cents_rate:
            # 2×-bill promise: overage spend ≤ tier price → max extra units.
            cap_units = allotment + TIER_PRICE_CENTS[plan] // overage_cents_rate

    # Launch-ops: owner-granted bonus units top up the plan allotment
    # (and lift the cap by the same amount, so grants never trigger the
    # bill-cap early). Grants without a plan do nothing — plan-less
    # businesses are already unlimited while unenforced.
    if allotment is not None:
        bonus = grant_units_this_month(business_id)
        if bonus > 0:
            allotment += bonus
            if cap_units is not None:
                cap_units += bonus

    overage_units = max(0, used - allotment) if allotment is not None else 0
    if cap_units is not None:
        overage_units = min(overage_units, cap_units - (allotment or 0))
    overage_cents = overage_units * (overage_cents_rate or 0)

    hard_cap = bool(((row or {}).get("settings") or {}).get("usage_hard_cap"))

    blocked = False
    reason = None
    if enforce and not grandfathered and allotment is not None:
        if hard_cap and used >= allotment:
            blocked, reason = True, "hard_cap"
        elif cap_units is not None and used >= cap_units:
            blocked, reason = True, "bill_cap"

    return {
        "ok": True,
        "month": _month_key(),
        "weighted_used": used,
        "allotment": None if grandfathered else allotment,
        "remaining": (None if (grandfathered or allotment is None)
                      else max(0, allotment - used)),
        "overage_units": 0 if grandfathered else overage_units,
        "overage_cents": 0 if grandfathered else overage_cents,
        "overage_rate_cents": overage_cents_rate,
        "cap_units": None if grandfathered else cap_units,
        "hard_cap": hard_cap,
        "blocked": blocked,
        "blocked_reason": reason,
        "plan": plan,
        "grandfathered": grandfathered,
        "enforce": enforce,
        "weights": {"chat": 1, "hero_regeneration": 5, "full_site_build": 25},
    }


def can_interact(business_id: str) -> bool:
    """The single AI-gate every Chief surface asks. True unless enforcement
    is on AND (bill cap reached OR practitioner hard cap reached).
    Failure of the metering read fails OPEN — metering must never brick
    Chief."""
    try:
        if not feature_gates.enforcement_on():
            return True
        s = usage_summary(business_id)
        return not s["blocked"]
    except Exception as e:
        logger.warning(f"[metering] can_interact failed open: {e}")
        return True


# ─── Threshold notifications (50 / 80 / 100 / cap) ───────────────────

def check_thresholds(business_id: str, owner_email: Optional[str] = None) -> List[int]:
    """Called after an AI interaction logs. Fires each threshold ONCE per
    month (usage_notifications unique row = the dedup). Email best-effort;
    the row alone powers the UI banner. Returns thresholds newly crossed."""
    try:
        s = usage_summary(business_id)
        if s["grandfathered"] or s["allotment"] in (None, 0):
            return []
        pct = int(s["weighted_used"] * 100 / s["allotment"])
        month = s["month"]
        fired: List[int] = []
        for t in THRESHOLDS:
            if pct < t:
                continue
            try:
                sb_clients.sb_post_as_service("/usage_notifications", {
                    "business_id": business_id, "month": month, "threshold": t,
                }, prefer=None)
            except Exception:
                continue  # unique conflict = already notified this month
            fired.append(t)
            if owner_email:
                _send_threshold_email(owner_email, t, s)
        return fired
    except Exception as e:
        logger.warning(f"[metering] threshold check failed: {e}")
        return []


def _send_threshold_email(to_email: str, threshold: int, s: Dict[str, Any]) -> None:
    try:
        import asyncio
        from email_sender import send_via_resend
        if threshold >= 200:
            subject = "Solutionist — you've reached this month's usage ceiling"
            body = ("You've hit the 2× monthly ceiling, so Chief is pausing AI "
                    "interactions until your next cycle. Everything else — "
                    "bookings, invoices, bookkeeping — keeps running.\n\n"
                    "Upgrading lifts the ceiling immediately: Settings → Billing.")
        elif threshold >= 100:
            subject = "Solutionist — you've used this month's included Chief interactions"
            body = (f"You've used {s['weighted_used']} of {s['allotment']} included "
                    f"interactions. Additional use is "
                    f"${(s['overage_rate_cents'] or 0)/100:.2f} per interaction, and "
                    "your total bill is always capped at 2× your plan.\n\n"
                    "Set a hard cap any time in Settings → Billing.")
        else:
            subject = f"Solutionist — {threshold}% of your monthly Chief interactions used"
            body = (f"Heads up: {s['weighted_used']} of {s['allotment']} included "
                    f"interactions used this month. No action needed — this is "
                    "just so you're never surprised.")
        coro = send_via_resend(
            to_email=to_email, to_name=None,
            from_email="billing@mysolutionist.app", from_name="Solutionist",
            reply_to=None, subject=subject, body=body)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as e:
        logger.warning(f"[metering] threshold email failed: {e}")


# ─── Stripe metered-usage reporting (daily incremental) ──────────────

def report_overage_to_stripe() -> Dict[str, Any]:
    """Daily job: for every enforcing, subscribed, non-grandfathered
    business, report NEW overage units (delta vs usage_stripe_reports)
    to the subscription's metered overage item. Allotment + cap logic
    stays OURS — Stripe only ever sees billable overage quantity."""
    if not feature_gates.enforcement_on():
        return {"ok": True, "skipped": "enforcement_off"}
    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        return {"ok": True, "skipped": "stripe_not_configured"}
    import stripe as _stripe
    _stripe.api_key = api_key

    month = _month_key()
    rows = sb_clients.sb_get_as_service(
        "/businesses?subscription_status=in.(active,trialing)"
        "&stripe_subscription_id=not.is.null"
        "&select=id,owner_id,settings,subscription_status,subscription_plan,"
        "stripe_subscription_id&limit=500") or []
    reported = errors = 0
    for row in rows:
        try:
            s = usage_summary(row["id"], row)
            if s["grandfathered"] or not s["overage_units"]:
                continue
            prior = sb_clients.sb_get_as_service(
                f"/usage_stripe_reports?business_id=eq.{row['id']}&month=eq.{month}"
                f"&select=reported_units&limit=1") or []
            already = int(prior[0]["reported_units"]) if prior else 0
            delta = s["overage_units"] - already
            if delta <= 0:
                continue
            overage_price = (os.environ.get(
                f"STRIPE_PRICE_ID_{(s['plan'] or '').upper()}_OVERAGE") or "").strip()
            if not overage_price:
                continue
            sub = _stripe.Subscription.retrieve(row["stripe_subscription_id"])
            item_id = next((it["id"] for it in sub["items"]["data"]
                            if it["price"]["id"] == overage_price), None)
            if not item_id:
                logger.warning(f"[metering] no overage item on sub for biz {row['id']}")
                continue
            _stripe.SubscriptionItem.create_usage_record(
                item_id, quantity=delta, action="increment")
            if prior:
                sb_clients.sb_patch_as_service(
                    f"/usage_stripe_reports?business_id=eq.{row['id']}&month=eq.{month}",
                    {"reported_units": s["overage_units"],
                     "updated_at": datetime.now(timezone.utc).isoformat()})
            else:
                sb_clients.sb_post_as_service("/usage_stripe_reports", {
                    "business_id": row["id"], "month": month,
                    "reported_units": s["overage_units"]}, prefer=None)
            reported += 1
        except Exception as e:
            errors += 1
            logger.warning(f"[metering] stripe report failed {row.get('id')}: {e}")
    return {"ok": True, "reported": reported, "errors": errors}


async def stripe_report_tick() -> None:
    try:
        report_overage_to_stripe()
    except Exception as e:
        logger.warning(f"[metering] stripe report tick failed: {e}")
