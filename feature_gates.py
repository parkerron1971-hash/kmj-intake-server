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

import os
from typing import Any, Dict, Optional

PLANS = ("starter", "professional", "practice")
_PLAN_RANK = {"starter": 1, "professional": 2, "practice": 3}

# Gate-ready map: feature → minimum tier. Working pricing hypothesis
# (2026-06-09 review): Starter $79 / Professional $199 / Practice $399.
FEATURE_MIN_PLAN: Dict[str, str] = {
    # Starter — operational core (incl. reconciliation: it's the upgrade wedge)
    "bookkeeping_basic": "starter",        # transactions + cash flow + reconciliation
    "reports_basic": "starter",            # P&L, AR aging, balance sheet lite
    "invoicing": "starter",
    # Professional — the real accounting system (the hero tier)
    "general_ledger": "professional",      # GL, trial balance, journal
    "period_close": "professional",
    "contractor_payments": "professional", # F.1 pay + 1099
    "reports_full": "professional",        # GL-authoritative + comparison
    "chief_bookkeeping": "professional",
    "chief_unlimited": "professional",     # Starter gets the capped Chief
    "accountant_package": "professional",  # year-end ZIP + IIF — every solo files taxes
    "vertical_ledgers": "professional",    # IOLTA trust / restricted-fund MECHANICS —
                                           # compliance is table stakes for a solo lawyer
    # Practice — collaboration + compliance deliverables + scale
    "accountant_collaborator": "practice",
    "audit_trail": "practice",
    "vertical_reports": "practice",        # Trust Reconciliation, 990 prep (I.10)
    "multi_seat": "practice",              # NOT BUILT YET — do not market until shipped
}

# Numeric limits per tier (gate-ready scaffold; UNENFORCED like everything
# else). chief_messages_monthly metering can build on the existing api_usage
# table; max_businesses needs an onboarding check. Both are Phase E v1.1
# enforcement work — registered here so the hypothesis lives in code.
# Pricing v2 allowances (docs/pricing_model_v2.md, Kevin 2026-07-12 —
# raised from 75/350/1000: "75 seems so little"):
# chief_messages_monthly = included WEIGHTED Chief interactions
# (chat=1, hero regen=5, full site build=25 — usage_metering.UNIT_WEIGHTS).
# Beyond the allowance, prepaid credits (credit_ledger) draw down.
# plaid_connections = connected bank account limit per tier (F-A2).
PLAN_LIMITS: Dict[str, Dict[str, Optional[int]]] = {
    "starter":      {"max_businesses": 1, "chief_messages_monthly": 300,
                     "max_seats": 1, "plaid_connections": 2},
    "professional": {"max_businesses": 1, "chief_messages_monthly": 1000,
                     "max_seats": 1, "plaid_connections": 5},
    "practice":     {"max_businesses": 3, "chief_messages_monthly": 3000,
                     "max_seats": 5, "plaid_connections": None},
}


def limit_for(business_row: Optional[Dict[str, Any]], limit: str) -> Optional[int]:
    """The numeric limit for a business's tier; None = unlimited. Unenforced
    (and unlimited) until BILLING_ENFORCE=on AND a plan exists."""
    if not enforcement_on():
        return None
    plan = plan_of(business_row)
    if not plan:
        return PLAN_LIMITS["starter"].get(limit)
    return PLAN_LIMITS.get(plan, {}).get(limit)


def price_to_plan() -> Dict[str, str]:
    """Stripe price id → tier name, from env (empty entries skipped)."""
    out: Dict[str, str] = {}
    for plan in PLANS:
        pid = (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}") or "").strip()
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
                 grandfathered: bool = False) -> Dict[str, Any]:
    """Subscription access enforcement (2026-07-03, Kevin's ruling:
    'if no person paid then they lose access').

    Returns {state, reason} where state is:
      'full'   — use the app normally
      'grace'  — payment failed; warn loudly, don't lock yet (Stripe
                 Smart Retries run during past_due/incomplete)
      'locked' — no live subscription; the frontend shows the paywall
                 (data is never deleted; export stays available)

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


def enforcement_on() -> bool:
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
    return _PLAN_RANK[plan] >= _PLAN_RANK[min_plan]


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
