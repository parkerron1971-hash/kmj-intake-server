"""
feature_gates.py — Phase E — tier entitlements (gate-ready, UNENFORCED).

Per Kevin's pricing ruling: pricing is locked AFTER the full build, so every
feature is free for all practitioners today. This module makes the gates
REAL but DORMANT — has_feature() returns True unless BILLING_ENFORCE=on.
The tier→feature map below is the gate-ready scaffold; final assignments are
the pricing decision, changed here in one place.

Tiers resolve from businesses.subscription_plan (a Stripe price id) via the
STRIPE_PRICE_ID_{STARTER,PROFESSIONAL,PRACTICE} env vars.
"""
from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

import pricing_config

PLANS = ("starter", "professional", "practice")
_PLAN_RANK = {"starter": 1, "professional": 2, "practice": 3}

# Gate-ready map: feature → minimum tier. Working pricing hypothesis
# (2026-06-09 review): Starter $79 / Professional $199 / Practice $399;
# re-set 2026-09-04 to $79 / $149 / $299 with a $99 Founder seat.
FEATURE_MIN_PLAN: Dict[str, str] = {
    # Starter — operational core (incl. reconciliation: it's the upgrade wedge)
    "bookkeeping_basic": "starter",        # transactions + cash flow + reconciliation
    "reports_basic": "starter",            # P&L, AR aging, balance sheet lite
    "invoicing": "starter",
    "general_ledger": "starter",           # GL, trial balance, journal.
                                           # Kevin's ruling 2026-08-19: the ledger
                                           # is the RECORD — every business gets to
                                           # see its own authoritative books
                                           # ("that's for safety"). The upgrade is
                                           # the advanced layer (reports_full,
                                           # period_close, accountant_package),
                                           # never the ledger itself.
    # Professional — the real accounting system (the hero tier)
    "period_close": "professional",
    "contractor_payments": "professional", # F.1 pay + 1099
    "reports_full": "professional",        # GL-authoritative + comparison
    "chief_bookkeeping": "professional",
    "chief_unlimited": "professional",     # Starter gets the capped Chief
    "accountant_package": "professional",  # year-end ZIP + IIF — every solo files taxes
    "vertical_ledgers": "professional",    # IOLTA trust / restricted-fund MECHANICS —
                                           # compliance is table stakes for a solo lawyer
    "site_concierge": "professional",      # customer-facing website chat
                                           # (site_concierge.py) — an AI
                                           # surface, so it rides the hero
                                           # tier with chief_unlimited
    "agent_connector": "starter",          # connect the business to the AI
                                           # the practitioner already carries
                                           # (mcp_server.py + mcp_oauth.py).
                                           # READ on every plan (2026-09-04):
                                           # their model does the thinking, so
                                           # a read costs the platform nothing,
                                           # and feeling it is the upgrade path.
    "agent_connector_write": "professional",  # the write key — records kept
                                           # by an outside agent — rides the
                                           # hero tier, like site_concierge.
                                           # NOT Practice — that tier is
                                           # collaboration and compliance
                                           # deliverables, and this is
                                           # neither.
    "sourcing_desk": "professional",       # find vendors on the live web +
                                           # RFQ them (sourcing_router).
                                           # Kevin's ruling 2026-08-22: the
                                           # same AI-surface-rides-the-hero-
                                           # tier rule. Gates NEW searches
                                           # and RFQ compose/send only —
                                           # vendors and quotes already
                                           # landed stay readable on every
                                           # plan (data is never plan-
                                           # locked).
    # Practice — collaboration + compliance deliverables + scale
    "dedicated_sms_number": "practice",    # a private texting line (sms_numbers_router).
                                           # Kevin's call 2026-09-02: included at
                                           # Practice first; a Professional add-on
                                           # is a later, separate change.
    "accountant_collaborator": "practice",
    "audit_trail": "practice",
    "vertical_reports": "practice",        # Trust Reconciliation, 990 prep (I.10)
    "multi_seat": "practice",              # seat CAPS enforce via business_users_router
                                           # (max_seats limit); the frontend still hides
                                           # this key from plan cards (HIDDEN_FEATURES)
                                           # until the full team experience ships
}

# Numeric limits per tier. plaid_connections = connected bank account
# limit per tier (F-A2); max_businesses needs an onboarding check.
def plan_limits() -> Dict[str, Dict[str, Optional[int]]]:
    """Numeric limits per tier.

    `chief_messages_monthly` is the monthly CREDIT GRANT and now comes
    from pricing_config, where it is env-overridable — the 2026-08-08
    config-driven launch ruling: we ship conservative opening defaults
    and refine against real data once the meter works.

    Opening defaults 3,000 / 10,000 / 25,000 (7,500 / 17,500 for the two
    bigger tiers since the 2026-09-04 ladder), up ~10x from the
    300/1000/3000 of the 2026-07-12 spec. That rescale is what makes
    per-action pricing expressible at all — a build priced at 600 is
    impossible against a 300 tank. Beyond the allowance, prepaid credits
    (credit_ledger) draw down.

    A FUNCTION, not a constant, so a price change is a value change and
    there is exactly one source of truth."""
    credits = pricing_config.tier_credits()
    return {
        "starter":      {"max_businesses": 1,
                         "chief_messages_monthly": credits["starter"],
                         "max_seats": 1, "plaid_connections": 2,
                         "open_assignments": 1},
        "professional": {"max_businesses": 1,
                         "chief_messages_monthly": credits["professional"],
                         "max_seats": 1, "plaid_connections": 5,
                         "open_assignments": 3},
        "practice":     {"max_businesses": 3,
                         "chief_messages_monthly": credits["practice"],
                         "max_seats": 5, "plaid_connections": None,
                         "open_assignments": 10},
    }


def limit_for(business_row: Optional[Dict[str, Any]], limit: str) -> Optional[int]:
    """The numeric limit for a business's tier; None = unlimited. Unenforced
    (and unlimited) until BILLING_ENFORCE=on AND a plan exists."""
    if not enforcement_on():
        return None
    limits = plan_limits()
    plan = plan_of(business_row)
    if not plan:
        return limits["starter"].get(limit)
    if limit == "chief_messages_monthly":
        return monthly_credits(business_row, plan)
    return limits.get(plan, {}).get(limit)


def is_founder_price(business_row: Optional[Dict[str, Any]]) -> bool:
    """Is this business on the Founder seat? Decided by the Stripe price
    id it subscribes to, never by a flag someone could set by hand."""
    pid = str((business_row or {}).get("subscription_plan") or "").strip()
    if not pid:
        return False
    founder = {(os.environ.get("STRIPE_PRICE_ID_FOUNDER") or "").strip(),
               (os.environ.get("STRIPE_PRICE_ID_FOUNDER_ANNUAL") or "").strip()} - {""}
    return pid in founder


def monthly_credits(business_row: Optional[Dict[str, Any]],
                    plan: Optional[str] = None) -> Optional[int]:
    """The monthly tank for this business: the plan's, except on the
    Founder seat, which carries Professional's features with its own
    smaller tank (pricing_config.founder_credits). A comped business is
    never on the founder tank — comp_tier wins in plan_of and the comp
    is the whole plan. None when there is no plan."""
    plan = plan or plan_of(business_row)
    if not plan:
        return None
    comp = str((business_row or {}).get("comp_tier") or "").strip().lower()
    if plan == "professional" and comp not in PLANS and is_founder_price(business_row):
        return pricing_config.founder_credits()
    return (plan_limits().get(plan) or {}).get("chief_messages_monthly")


# Price-id env aliases → the tier they entitle (2026-07-21 pricing
# ruling). FOUNDER = the launch cohort's Professional price, locked for
# the life of the subscription and capped at FOUNDER_SEAT_LIMIT seats
# (enforced at checkout in stripe_billing.py); *_ANNUAL = yearly
# billing (2 months free) for the same tier. Entitlements never differ
# from the base tier — only the price does.
PRICE_ENV_TO_PLAN: Dict[str, str] = {
    "STARTER":             "starter",
    "PROFESSIONAL":        "professional",
    "PRACTICE":            "practice",
    "STARTER_ANNUAL":      "starter",
    "PROFESSIONAL_ANNUAL": "professional",
    "PRACTICE_ANNUAL":     "practice",
    "FOUNDER":             "professional",
    "FOUNDER_ANNUAL":      "professional",
}


def price_to_plan() -> Dict[str, str]:
    """Stripe price id → tier name, from env (empty entries skipped)."""
    out: Dict[str, str] = {}
    for env_key, plan in PRICE_ENV_TO_PLAN.items():
        pid = (os.environ.get(f"STRIPE_PRICE_ID_{env_key}") or "").strip()
        if pid:
            out[pid] = plan
    # Legacy single-plan default maps to professional.
    default = (os.environ.get("STRIPE_PRICE_ID_DEFAULT") or "").strip()
    if default and default not in out:
        out[default] = "professional"
    return out


def plan_of(business_row: Optional[Dict[str, Any]]) -> Optional[str]:
    """The business's tier when its subscription is in good standing.

    Launch-ops (2026-07-03): an owner-set `comp_tier` wins over Stripe —
    the manual override for beta testers / partners / comped accounts.
    Set via POST /access/business/{id}/tier; no subscription required."""
    if not business_row:
        return None
    comp = (business_row.get("comp_tier") or "").strip().lower()
    if comp in PLANS:
        return comp
    status = business_row.get("subscription_status")
    if status not in ("trialing", "active"):
        return None
    return price_to_plan().get(business_row.get("subscription_plan") or "")


def access_state(business_row: Optional[Dict[str, Any]],
                 grandfathered: bool = False,
                 trial_spent: bool = False) -> Dict[str, Any]:
    """Subscription access enforcement (2026-07-03, Kevin's ruling:
    'if no person paid then they lose access').

    Returns {state, reason} where state is:
      'full'   — use the app normally
      'grace'  — payment failed; warn loudly, don't lock yet (Stripe
                 Smart Retries run during past_due/incomplete)
      'locked' — no live subscription, OR a trial that has run out of
                 credits; the frontend shows the paywall (data is never
                 deleted; export stays available)

    A trial ends on WHICHEVER COMES FIRST, the calendar or the tank
    (2026-08-24). `trial_spent` is the tank half — the caller passes
    usage_metering.trial_credits_exhausted(), because this function is
    deliberately pure and does not read the database. Left False, the
    behaviour is exactly what it was: the calendar alone.

    Dormant like everything else: enforcement_on() off → always full.
    Grandfathered users and comp_tier businesses never lock.
    """
    if not enforcement_on():
        return {"state": "full", "reason": "enforcement_off"}
    if grandfathered:
        return {"state": "full", "reason": "grandfathered"}
    row = business_row or {}
    comp = (row.get("comp_tier") or "").strip().lower()
    if comp in PLANS:
        return {"state": "full", "reason": f"comp_{comp}"}
    status = (row.get("subscription_status") or "").strip().lower()
    if status == "active":
        return {"state": "full", "reason": "active"}
    if status == "trialing":
        if trial_spent:
            return {"state": "locked", "reason": "trial_credits_spent"}
        trial_end = (row.get("trial_ends_at") or "").strip()
        if trial_end:
            from datetime import datetime, timezone
            try:
                end = datetime.fromisoformat(trial_end.replace("Z", "+00:00"))
                if end < datetime.now(timezone.utc):
                    return {"state": "locked", "reason": "trial_expired"}
            except ValueError:
                pass  # unparseable date — treat the Stripe status as truth
        return {"state": "full", "reason": "trialing"}
    if status in ("past_due", "unpaid", "incomplete"):
        return {"state": "grace", "reason": "payment_failed"}
    return {"state": "locked",
            "reason": "canceled" if status == "canceled" else "no_subscription"}


# THE REHEARSAL (2026-09-04). Every gate short-circuits on enforcement_on(),
# which made "what would the flip do?" unanswerable without flipping.
# Inside rehearsal(), enforcement_on() answers True for THIS task only —
# a contextvar, so a concurrent request on the same process keeps the
# real value. billing_rehearsal uses it to ask every decision
# hypothetically; nothing else should.
_REHEARSAL: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "billing.rehearsal", default=False)


@contextmanager
def rehearsal():
    token = _REHEARSAL.set(True)
    try:
        yield
    finally:
        _REHEARSAL.reset(token)


def enforcement_on() -> bool:
    if _REHEARSAL.get():
        return True
    return (os.environ.get("BILLING_ENFORCE") or "off").lower() == "on"


def has_feature(business_row: Optional[Dict[str, Any]], feature: str) -> bool:
    """True unless enforcement is on AND the plan rank is insufficient.
    Unknown features default to allowed (fail-open by design)."""
    if not enforcement_on():
        return True
    min_plan = FEATURE_MIN_PLAN.get(feature)
    if not min_plan:
        return True
    plan = plan_of(business_row)
    if not plan:
        return False
    # .get guards: an unknown tier name (future plan key, bad comp value)
    # must read as rank 0, not crash the gate.
    return _PLAN_RANK.get(plan, 0) >= _PLAN_RANK.get(min_plan, 99)


def entitlements(business_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Full entitlement picture for the frontend: what's allowed now, and
    what WOULD be allowed per tier once enforcement turns on."""
    plan = plan_of(business_row)
    rank = _PLAN_RANK.get(plan or "", 0)
    return {
        "plan": plan,
        "subscription_status": (business_row or {}).get("subscription_status"),
        "enforce": enforcement_on(),
        "features": {
            f: {
                "allowed": has_feature(business_row, f),
                "min_plan": mp,
                "included_in_plan": rank >= _PLAN_RANK[mp],
            } for f, mp in FEATURE_MIN_PLAN.items()
        },
    }
