"""
vertical_family.py — the ONE canonical classifier for a business's vertical
FAMILY.

WHY: vertical awareness is spread across five separately-maintained maps
(onboarding list, DB CHECK, Chief intelligence, terminology, module seeds)
that disagree on which verticals even exist. The most damaging disagreement
is around donation-funded orgs: a user can only pick "ministry" at signup,
but the chart-of-accounts and the donor/990 reports keyed on "nonprofit" —
so a church or ministry got NO restricted-fund accounts and NO giving/990
reports despite being entirely donation-funded.

This module is the reconciliation seed: instead of every gate re-deciding
"is this a nonprofit?" with its own string test, they all ask here. A
FAMILY is the accounting/compliance shape a business shares — not its exact
label:

  legal      — trust/IOLTA accounting (lawyer, law firm, attorney, …)
  nonprofit  — restricted-fund + donor/990 accounting (nonprofit, church,
               ministry, faith-based, synagogue, mosque, temple, …)
  general    — everything else (the ordinary operating book)

Membership is exact after normalization (lower/underscore), so a
"nonprofit consultant" or "sports ministry coach" does not accidentally
inherit restricted-fund routing — only genuine org types match. Extend the
sets here, in one place, when a new synonym shows up.
"""
from __future__ import annotations

from typing import Optional

# Donation-funded orgs — share restricted-fund COA + donor/990 reporting.
_NONPROFIT = {
    "nonprofit", "non_profit", "not_for_profit", "nonprofit_org",
    "church", "churches", "ministry", "ministries", "parachurch",
    "faith", "faith_based", "religious", "religious_org",
    "synagogue", "mosque", "temple", "congregation",
}

# Trust-holding practices — share IOLTA/trust accounting.
_LEGAL = {
    "lawyer", "lawyers", "law", "law_firm", "law_practice",
    "legal", "legal_services", "attorney", "attorneys",
}


def _norm(business_type: Optional[str]) -> str:
    return (business_type or "").lower().strip().replace("-", "_").replace(" ", "_")


def is_nonprofit_like(business_type: Optional[str]) -> bool:
    """True for donation-funded orgs (nonprofit, church, ministry, …) —
    the family that gets restricted-fund accounts + donor/990 reports."""
    return _norm(business_type) in _NONPROFIT


def is_legal_like(business_type: Optional[str]) -> bool:
    """True for trust-holding legal practices — the family that gets IOLTA
    trust accounts + trust reconciliation."""
    return _norm(business_type) in _LEGAL


def family_of(business_type: Optional[str]) -> str:
    """'legal' | 'nonprofit' | 'general' — the accounting/compliance shape."""
    if is_legal_like(business_type):
        return "legal"
    if is_nonprofit_like(business_type):
        return "nonprofit"
    return "general"
