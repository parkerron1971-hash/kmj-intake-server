"""
usage_metering.py — Arc 19 Phase B — weighted Chief-interaction metering
per the LOCKED pricing model (docs/pricing_model.md).

THE UNIT: one "Chief interaction" — a weighted count over api_usage rows:
    chat / bookkeeping Chief / proxy call = 1
    hero regeneration                     = 5
    full site build-with-loop             = 25
Weights key on the logged endpoint (no schema change; aggregation-time
lookup). Everything else on the platform is unmetered by design.

THE MODEL (Pricing v2, 2026-07-12 — docs/pricing_model_v2.md): PREPAID.
Draw-down is monthly plan allowance first, then purchased/granted
credits (credit_ledger). There is NO postpaid overage and NO surprise
bill — running dry soft-blocks AI interactions only, with a friendly
top-up prompt; bookings, invoices, bookkeeping NEVER stop. The old
postpaid rates/caps below are retained only for legacy field shape.

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
import credit_ledger

logger = logging.getLogger("usage_metering")

# Endpoint → unit weight (default 1). Disclosed at point of use in the UI.
UNIT_WEIGHTS: Dict[str, int] = {
    "/composer/hero": 5,
    # FULL SITE BUILD = ONE 25-unit action (2026-07-30 weight-hole fix).
    # compose_site logs a single zero-cost marker row ("/composer/compose")
    # when a full LLM compose ships; the constituent authoring endpoints
    # below keep their rows for cost analytics at weight 0 so one build
    # never bills per-LLM-call. The old key — "/director/build" — matched
    # an endpoint NOTHING ever logged (build-with-loop was retired into
    # compose_site), so the 25 weight silently never applied and a $1-2
    # build metered as a handful of weight-1 rows.
    "/composer/compose": 25,
    "/director/build": 25,           # legacy engine marker, kept for old rows
    "/composer/canvas": 0,           # one-mind page author (build-internal)
    "/composer/canvas-review": 0,    # vision-loop repair (build-internal)
    "/composer/builder-v2": 0,       # v2 builder (build-internal)
    "/composer/builder-v2-eyes": 0,  # v2 vision walk (build-internal)
    # Spec authoring/revision is deliberately "pennies" (Arc 3: only
    # decided designs pay for builds) — and compose_spec_llm logs the
    # same label inside every build. The build marker carries the bill.
    "/composer/spec": 0,
    # /composer/atelier stays default-1: a Studio select-to-talk edit is
    # one action, and the 2-3 bespoke fragments inside a build add only
    # their honest handful on top of the marker.
    # Voice (2026-07-15): standard OpenAI TTS is included with every plan —
    # weight 0 keeps the rows attributable for analytics without billing
    # them (the default weight of 1 would otherwise start charging units
    # for every spoken sentence the moment rows carry business_id).
    # ElevenLabs premium voice bills 1 unit per spoken chunk and rides the
    # same allowance-first, credits-next draw-down as Chief messages.
    "/ai/tts": 0,
    "/ai/tts-el": 1,
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
    # Paginated: the old single limit=10000 read silently under-counted
    # any business past 10k rows/month. Terminates on the first short
    # page; the offset ceiling is a runaway guard, not a real bound.
    total, offset, page = 0, 0, 10000
    while offset <= 200_000:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}"
            f"&created_at=gte.{_month_start_iso()}&select=endpoint"
            f"&limit={page}&offset={offset}") or []
        total += sum(weight_for(r.get("endpoint")) for r in rows)
        if len(rows) < page:
            break
        offset += page
    return total


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
    """Everything the UI + enforcement need in one read. Allotment/credit
    numbers show from the PLAN even while enforcement is dormant (the UI
    is honest early); `blocked` only ever true when enforcing.

    Prepaid semantics (Pricing v2): allowance first, then credits.
    Reading the summary also reconciles this month's credit burn."""
    row = biz_row or _biz_row(business_id)
    used = weighted_usage_this_month(business_id)
    grandfathered = is_grandfathered_business(business_id, row)
    plan = feature_gates.plan_of(row) if row else None
    enforce = feature_gates.enforcement_on()

    allotment = None
    if plan:
        allotment = (feature_gates.PLAN_LIMITS.get(plan) or {}).get("chief_messages_monthly")

    # Launch-ops monthly bonus grants (usage_grants) top up the plan
    # allotment. (Distinct from credit_ledger grants, which never expire.)
    if allotment is not None:
        bonus = grant_units_this_month(business_id)
        if bonus > 0:
            allotment += bonus

    # Prepaid draw-down: usage beyond the allowance burns credits.
    # Grandfathered accounts are unlimited — never touch their ledger.
    beyond_allowance = max(0, used - allotment) if allotment is not None else 0
    burned_this_month = 0
    if allotment is not None and not grandfathered:
        burned_this_month = credit_ledger.sync_burn(business_id, beyond_allowance)
    credits_balance = credit_ledger.balance(business_id)

    hard_cap = bool(((row or {}).get("settings") or {}).get("usage_hard_cap"))

    blocked = False
    reason = None
    if enforce and not grandfathered and allotment is not None:
        if hard_cap and used >= allotment:
            # Practitioner chose "stop at my plan" — don't spend credits.
            blocked, reason = True, "hard_cap"
        elif used >= allotment and credits_balance <= 0:
            blocked, reason = True, "out_of_units"

    return {
        "ok": True,
        "month": _month_key(),
        "weighted_used": used,
        "allotment": None if grandfathered else allotment,
        "remaining": (None if (grandfathered or allotment is None)
                      else max(0, allotment - used)),
        # Prepaid credit fields (Pricing v2).
        "credits_balance": credits_balance,
        "credits_burned_month": burned_this_month,
        # Legacy postpaid fields, kept for older UI readers: nothing is
        # ever billed as overage anymore.
        "overage_units": 0 if grandfathered else beyond_allowance,
        "overage_cents": 0,
        "overage_rate_cents": None,
        "cap_units": None,
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
    is on AND (allowance + credits exhausted, OR the practitioner's own
    hard cap reached). Failure of the metering read fails OPEN — metering
    must never brick Chief."""
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
    """RETIRED by Pricing v2 (2026-07-12): there is no postpaid overage.
    Usage beyond the allowance draws down PREPAID credits instead
    (credit_ledger), so nothing must ever reach a Stripe metered item —
    that would double-charge. Permanent no-op kept so the daily job and
    any callers stay wired."""
    return {"ok": True, "skipped": "prepaid_model_v2"}
    # ── unreachable legacy body below (postpaid era) ──
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
