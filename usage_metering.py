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
import pricing_config

logger = logging.getLogger("usage_metering")

# ─── Prices live in pricing_config, not here ─────────────────────────
#
# CONFIG-DRIVEN LAUNCH (Kevin's ruling 2026-08-08): we launch on
# conservative opening defaults and refine against real data once the
# meter works — so no price may be hardcoded at a call site. Everything
# below reads pricing_config, whose every value is env-overridable, so
# tuning is a Railway value change plus a restart, never a code deploy.
#
# The endpoint table had to become a FUNCTION rather than a constant:
# the build price is now itself a dial, so the table is derived.


def unit_weights() -> Dict[str, int]:
    """Endpoint → price, live from config.

    See pricing_config.unit_weights() for the per-endpoint reasoning and
    for the rule that every key must be a label something ACTUALLY logs
    (the /director/build weight hole is what that rule is made of)."""
    return pricing_config.unit_weights()


DEFAULT_WEIGHT = pricing_config.DEFAULT_WEIGHT

# Overage rate (cents/unit) per tier — LOCKED 2026-06-10. Legacy shape
# only: the prepaid model never bills overage.
OVERAGE_CENTS = {"starter": 40, "professional": 30, "practice": 25}
TIER_PRICE_CENTS = {"starter": 7900, "professional": 19900, "practice": 39900}

# % of allotment that notifies, once each per month; 200 ≈ the cap
# milestone. Read at import — Railway env is fixed for a process life.
THRESHOLDS = pricing_config.usage_thresholds()

# Credits-surfacing (2026-08-01): the soft "running low" signal fires when
# the COMBINED remaining (monthly allowance left + pack balance) crosses
# at/below this % of the cycle's capacity (allowance + packs available
# this cycle). Distinct from THRESHOLDS, which track allowance-only usage.
LOW_CREDIT_PCT = pricing_config.low_credit_pct()


def _month_key(now: Optional[datetime] = None) -> str:
    n = now or datetime.now(timezone.utc)
    return f"{n.year:04d}-{n.month:02d}"


def _month_start_iso() -> str:
    """First instant of THIS month (UTC), Z form.

    THE METER-READS-ZERO BUG (found 2026-08-08, fixed here): this
    returned a bare .isoformat(), which emits `+00:00`. Interpolated
    into a PostgREST query string the `+` decodes as a SPACE, so
    Postgres received "2026-08-01T00:00:00 00:00" and answered
    `22007: invalid input syntax for type timestamp with time zone`.
    PostgREST 400s, sb_get_as_service returns None, the `or []` at the
    call site swallows it — and weighted_usage_this_month() returned 0
    for EVERY business, forever. The Settings meter read zero, credit
    draw-down never drew down, and every require_units() gate passed
    unconditionally.

    PR #196 (2026-07-21) swept this class repo-wide; this module dates
    to 2026-06-10 and was missed by that sweep. The Z form is the rule
    for ANY timestamp interpolated into a PostgREST URL."""
    n = datetime.now(timezone.utc)
    return (n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
             .isoformat().replace("+00:00", "Z"))


def _day_start_iso() -> str:
    """First instant of TODAY (UTC), Z form — the chat fair-use window."""
    n = datetime.now(timezone.utc)
    return (n.replace(hour=0, minute=0, second=0, microsecond=0)
             .isoformat().replace("+00:00", "Z"))


def _next_month_start_iso() -> str:
    """First instant of NEXT month (UTC) — when the allowance resets.

    Z form for consistency. This one is only ever returned to the UI
    (never interpolated into a query string), but a module that emits
    two shapes of timestamp is a trap for the next reader who copies
    the wrong one into a filter."""
    n = datetime.now(timezone.utc)
    if n.month == 12:
        nm = n.replace(year=n.year + 1, month=1, day=1,
                       hour=0, minute=0, second=0, microsecond=0)
    else:
        nm = n.replace(month=n.month + 1, day=1,
                       hour=0, minute=0, second=0, microsecond=0)
    return nm.isoformat().replace("+00:00", "Z")


def weight_for(endpoint: Optional[str]) -> int:
    """Price of an action from its endpoint alone — the FALLBACK path.

    Prefer weight_for_row() wherever the whole row is in hand: a row
    carrying explicit `units` overrides this table."""
    return unit_weights().get((endpoint or "").strip(), DEFAULT_WEIGHT)


def weight_for_row(row: Optional[Dict[str, Any]]) -> int:
    """Price of one api_usage row.

    WHY A ROW AND NOT JUST AN ENDPOINT (2026-08-08): the endpoint->weight
    table cannot express the price list Kevin ruled. Three of the seven
    prices are context-dependent on an endpoint that logs ONE label:

      · /composer/compose is a build (base + sections x per_section) OR a
        revamp (flat) — same function, same label.
      · /composer/atelier is a standalone Studio section rewrite (120) OR
        one of the 2-3 bespoke fragments inside a build (0, because the
        build marker already carries them) — same function, same label.

    So the price is written onto the ROW at log time and read back here.
    The endpoint table remains the fallback for rows that predate the
    column and for every action whose price really is flat.

    `units` of 0 is meaningful (build internals are deliberately free),
    so this tests for None rather than truthiness."""
    if not row:
        return DEFAULT_WEIGHT
    u = row.get("units")
    if u is not None:
        try:
            return max(0, int(u))
        except (TypeError, ValueError):
            pass                      # malformed -> fall through to endpoint
    return weight_for(row.get("endpoint"))


def weighted_usage_this_month(business_id: str) -> int:
    # Paginated: the old single limit=10000 read silently under-counted
    # any business past 10k rows/month. Terminates on the first short
    # page; the offset ceiling is a runaway guard, not a real bound.
    total, offset, page = 0, 0, 10000
    while offset <= 200_000:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}"
            f"&created_at=gte.{_month_start_iso()}&select=endpoint,units"
            f"&limit={page}&offset={offset}") or []
        total += sum(weight_for_row(r) for r in rows)
        if len(rows) < page:
            break
        offset += page
    return total


def chat_turns_today(business_id: str) -> int:
    """Chief turns this business has logged since 00:00 UTC — the input
    to the fair-use brake. Counts ROWS, not weighted units: the ceiling
    is about request volume (a runaway script), not spend."""
    rows = sb_clients.sb_get_as_service(
        f"/api_usage?business_id=eq.{business_id}"
        f"&endpoint=eq./chief/backend"
        f"&created_at=gte.{_day_start_iso()}&select=id&limit=2000") or []
    return len(rows)


def chat_fair_use_ok(business_id: str) -> bool:
    """The per-day abuse brake on Chief chat. True = let the turn run.

    WHY THIS EXISTS (2026-08-08): chat is priced at 1 credit but its real
    cost is neither flat nor stable — p95 is 19.84c/turn against a 7.16c
    mean, and the mean rose ~70% in the fortnight to 2026-08-03 as
    context injectors grew. A single runaway loop is the one failure mode
    that can outrun the credit tank faster than anyone reads a dashboard.

    ABUSE-ONLY BY DESIGN. At the opening 250 turns/day a real
    practitioner never meets it: the busiest observed human day on the
    platform is 34. Sustained traffic above it is a script or a loop.

    THREE DELIBERATE CHOICES, all flagged to Kevin:

      1. NOT gated behind BILLING_ENFORCE. This is abuse protection, not
         billing. Gating it behind the billing flag would ship it as a
         no-op on day one — dead weight by the repo's own rule — and
         leave the platform with no per-account runaway brake during
         exactly the beta month it was built for. CHAT_CEILING_ENFORCE=off
         turns blocking off while still logging every trip.
      2. NO grandfather bypass. Grandfathered accounts skip BILLING
         limits; a runaway loop on a grandfathered account still burns
         real money, and the largest grandfathered account is Kevin's own.
      3. FAILS OPEN. A metering read failure must never mute Chief."""
    try:
        ceiling = pricing_config.chat_daily_soft_ceiling()
        if ceiling <= 0:
            return True
        turns = chat_turns_today(business_id)
        if turns < ceiling:
            return True
        logger.warning(
            f"[metering] chat fair-use ceiling tripped for "
            f"{business_id[:8]}: {turns} turns today (ceiling {ceiling}, "
            f"enforced={pricing_config.chat_ceiling_enforced()})")
        return not pricing_config.chat_ceiling_enforced()
    except Exception as e:
        logger.warning(f"[metering] chat_fair_use_ok failed open: {e}")
        return True


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
        allotment = (feature_gates.plan_limits().get(plan) or {}).get("chief_messages_monthly")

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
        # Live from config — this used to be a hardcoded {1, 5, 25} that
        # the UI displayed as fact while the real table said otherwise.
        # The price list the practitioner reads is now the price list
        # they are charged.
        "weights": price_list(),
    }


def price_list() -> Dict[str, Any]:
    """The practitioner-facing price list, live from config. What the
    Settings meter and the credits card disclose at point of use."""
    return {
        "chat": pricing_config.chat_price(),
        "hero_regeneration": pricing_config.hero_regen(),
        "site_build_base": pricing_config.build_base(),
        "site_build_per_section": pricing_config.build_per_section(),
        "site_revamp": pricing_config.revamp_price(),
        "section_rewrite": pricing_config.section_rewrite(),
        "small_edit": pricing_config.small_edit(),
        "document": pricing_config.doc_gen(),
        "concierge_reply": pricing_config.concierge_price(),
        "premium_voice": pricing_config.premium_voice_price(),
    }


def credits_overview(business_id: str,
                     biz_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The CreditsCard read (GET /billing/credits/{business_id}) — the
    practitioner-facing shape of the prepaid model in one payload.

    CONSUMPTION ORDER (Pricing v2, the accounting this mirrors):
    the monthly plan allowance (plus any usage_grants top-ups for the
    month) is ALWAYS spent first; only usage beyond it draws down
    purchased/granted credit packs (credit_ledger, via the lazy
    sync_burn reconcile that usage_summary() performs on every read —
    so reading this overview also keeps the burn row honest).

    monthly.used is clamped to the allowance (the bar never overflows);
    the beyond-allowance part shows up as packs consumption instead.
    Grandfathered accounts read as unlimited: allowance/total None."""
    import credit_ledger
    s = usage_summary(business_id, biz_row)
    led = credit_ledger.summary(business_id)

    allowance = s["allotment"]          # None → grandfathered or no plan
    used_raw = int(s["weighted_used"] or 0)
    grandfathered = bool(s["grandfathered"])
    monthly_used = used_raw if allowance is None else min(used_raw, allowance)
    monthly_remaining = (None if allowance is None
                         else max(0, allowance - used_raw))
    packs_remaining = int(led["balance"] or 0)
    packs_granted = int(led["purchased"] or 0) + int(led["granted"] or 0)
    packs_used = int(led["burned"] or 0)

    if grandfathered:
        total_remaining = None          # unlimited during the founder period
    else:
        total_remaining = (monthly_remaining or 0) + packs_remaining

    # Capacity this cycle = allowance + packs available at cycle start
    # (balance + this month's burn adds the burn back). Burning moves
    # units from balance→burned so capacity holds steady within a month;
    # a pack purchase raises it.
    capacity = (allowance or 0) + packs_remaining + int(s["credits_burned_month"] or 0)
    low = bool(allowance is not None and not grandfathered and capacity > 0
               and total_remaining is not None
               and total_remaining * 100 <= capacity * LOW_CREDIT_PCT)

    return {
        "ok": True,
        "month": s["month"],
        "plan": s["plan"],
        "grandfathered": grandfathered,
        "enforce": s["enforce"],
        "monthly": {
            "allowance": allowance,
            "used": monthly_used,
            "used_raw": used_raw,
            "remaining": monthly_remaining,
            "resets_at": _next_month_start_iso(),
        },
        "packs": {
            "granted": packs_granted,
            "used": packs_used,
            "remaining": packs_remaining,
        },
        "total_remaining": total_remaining,
        "low": low,
        "low_threshold_pct": LOW_CREDIT_PCT,
        # Live table, not the import-time snapshot — /billing/usage and
        # this overview must not quote two different catalogues.
        "catalog": credit_ledger.credit_packs(),
        "weights": s["weights"],
    }


def check_low_credit(business_id: str,
                     s: Optional[Dict[str, Any]] = None) -> bool:
    """ONE chief_notification when a metered action takes the combined
    remaining (allowance left + pack balance) across the LOW_CREDIT_PCT
    edge — from above to at/below. Crossing-edge dedupe (the inventory
    low-stock precedent in store_router._maybe_low_stock_alert): the
    next action starts at/below the threshold, so the edge condition is
    false until a top-up lifts capacity — at which point a fresh dip
    legitimately re-alerts. The prior value is inferred from the weight
    of the just-logged api_usage row (this runs from check_thresholds,
    directly after an interaction logs). Belt-and-suspenders: one alert
    per (month, capacity) pair — a re-check at the exact boundary can't
    double-fire, and a pack purchase (new capacity) re-arms. Best-effort:
    never raises."""
    try:
        s = s or usage_summary(business_id)
        allowance = s["allotment"]
        if s["grandfathered"] or not allowance:
            return False
        used = int(s["weighted_used"] or 0)
        balance = int(s["credits_balance"] or 0)
        burned_month = int(s["credits_burned_month"] or 0)
        remaining = max(0, allowance - used) + balance
        capacity = allowance + balance + burned_month
        if capacity <= 0:
            return False
        threshold = (capacity * LOW_CREDIT_PCT) // 100
        if remaining > threshold:
            return False
        # The edge: remaining BEFORE the action that just logged must
        # have been above the threshold.
        last = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}"
            f"&created_at=gte.{_month_start_iso()}&select=endpoint"
            f"&order=created_at.desc&limit=1") or []
        w = weight_for(last[0].get("endpoint")) if last else 0
        if w <= 0 or (remaining + w) <= threshold:
            return False
        # One alert per (month, capacity): a repeat check at the exact
        # boundary, or a race between two actions, stays a single nudge.
        existing = sb_clients.sb_get_as_service(
            f"/chief_notifications?business_id=eq.{business_id}"
            f"&type=eq.low_credits&created_at=gte.{_month_start_iso()}"
            f"&select=id,data&limit=20") or []
        for r in existing:
            d = r.get("data") or {}
            try:
                if int(d.get("capacity") or 0) >= capacity:
                    return False
            except (TypeError, ValueError):
                continue
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": business_id,
            "type": "low_credits",
            "title": f"Credits running low — {remaining} left this month. Top up?",
            "body": (f"You've used {capacity - remaining} of the {capacity} AI "
                     f"actions available this cycle. Nothing pauses yet — "
                     f"bookings, invoices and bookkeeping never stop — but a "
                     f"credit pack in Settings → Billing keeps Chief going "
                     f"without interruption."),
            "priority": "normal",
            "status": "unread",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data": {"remaining": remaining, "capacity": capacity,
                     "threshold": threshold, "month": s["month"]},
        }, prefer=None)
        return True
    except Exception as e:
        logger.warning(f"[metering] low-credit check failed: {e}")
        return False


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
        # Credits-surfacing: the combined-balance "running low" nudge
        # rides the same after-a-metered-action hook. Self-guarded
        # (grandfather / no-allowance / crossing-edge) and best-effort.
        check_low_credit(business_id, s)
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
