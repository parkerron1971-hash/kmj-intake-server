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

# Gate-ready map: feature → minimum tier. PROVISIONAL until pricing locks.
FEATURE_MIN_PLAN: Dict[str, str] = {
    # Starter — operational core
    "bookkeeping_basic": "starter",        # transactions + cash flow + reconciliation
    "reports_basic": "starter",            # P&L, AR aging, balance sheet lite
    "invoicing": "starter",
    # Professional — the real accounting system
    "general_ledger": "professional",      # GL, trial balance, journal
    "period_close": "professional",
    "contractor_payments": "professional", # F.1 pay + 1099
    "reports_full": "professional",        # GL-authoritative + comparison
    "chief_bookkeeping": "professional",
    # Practice — collaboration + year-end
    "accountant_collaborator": "practice",
    "accountant_package": "practice",      # ZIP + IIF + email
    "audit_trail": "practice",
}


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
    """The business's tier when its subscription is in good standing."""
    if not business_row:
        return None
    status = business_row.get("subscription_status")
    if status not in ("trialing", "active"):
        return None
    return price_to_plan().get(business_row.get("subscription_plan") or "")


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
