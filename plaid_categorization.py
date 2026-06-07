"""
plaid_categorization.py — Phase F.2 v1.

Deterministic mapping from Plaid's Personal Finance Category (v2) onto
the Solutionist 5-bucket scheme that the Allocator + business_expenses
table already use:

    tax | owner_pay | operating | savings | other

Categorization precedence (highest → lowest):
    1. Practitioner manual override (plaid_transactions.business_category
       written via the categorize drawer) — wins always.
    2. Per-merchant rule (category_rules row matching the merchant) —
       applies on insert + on resync.
    3. Static Plaid → 5-bucket map (this file).
    4. Fallback to 'other'.

Plaid's PFC v2 taxonomy: primary categories listed at
    https://plaid.com/docs/api/products/transactions/#categoriesget

Tested as a pure-Python lookup so the rule engine is auditable +
unit-testable without hitting Plaid.
"""
from __future__ import annotations

from typing import Optional, Dict


# ─── 5-bucket constants (must match the migration's CHECK) ───────────

BUCKET_TAX        = "tax"
BUCKET_OWNER_PAY  = "owner_pay"
BUCKET_OPERATING  = "operating"
BUCKET_SAVINGS    = "savings"
BUCKET_OTHER      = "other"

ALL_BUCKETS = (
    BUCKET_TAX, BUCKET_OWNER_PAY, BUCKET_OPERATING,
    BUCKET_SAVINGS, BUCKET_OTHER,
)


# ─── Detail-level overrides (most specific match wins) ───────────────
#
# Detail values are full PFC paths like "INCOME_WAGES" or
# "TRANSFER_OUT_WITHDRAWAL". When a detail key matches it skips the
# primary lookup below. Keep the map shallow — every entry here is a
# load-bearing classification with real downstream impact on the
# Allocator / Tax Set-Aside math.

DETAIL_MAP: Dict[str, str] = {
    # Tax payments — IRS, state, EFTPS, etc. → tax bucket.
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT":  BUCKET_TAX,
    "GOVERNMENT_AND_NON_PROFIT_TAX_REFUND":   BUCKET_TAX,
    # Practitioner moving money to savings → savings bucket.
    "TRANSFER_OUT_SAVINGS":                   BUCKET_SAVINGS,
    "TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS": BUCKET_SAVINGS,
    # Practitioner paying themselves (payroll DD / owner draw) →
    # owner_pay. Heuristic: same-account transfers OUT to a known
    # payroll vendor or "OWNER" memo will route here, but the static
    # map handles only the obvious case below; rule engine handles
    # business-specific overrides.
    "TRANSFER_OUT_WITHDRAWAL":                BUCKET_OWNER_PAY,
    # Bank fees + loan payments → operating (cost of doing business).
    "BANK_FEES_OVERDRAFT_FEES":               BUCKET_OPERATING,
    "BANK_FEES_ATM_FEES":                     BUCKET_OPERATING,
    "BANK_FEES_FOREIGN_TRANSACTION_FEES":     BUCKET_OPERATING,
    "BANK_FEES_INSUFFICIENT_FUNDS":           BUCKET_OPERATING,
    "BANK_FEES_INTEREST_CHARGE":              BUCKET_OPERATING,
    "BANK_FEES_OTHER_BANK_FEES":              BUCKET_OPERATING,
    "LOAN_PAYMENTS_MORTGAGE_PAYMENT":         BUCKET_OPERATING,
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT":      BUCKET_OPERATING,
    "LOAN_PAYMENTS_PERSONAL_LOAN_PAYMENT":    BUCKET_OPERATING,
    "LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT":     BUCKET_OPERATING,
    "LOAN_PAYMENTS_CAR_PAYMENT":              BUCKET_OPERATING,
    "LOAN_PAYMENTS_OTHER_PAYMENT":            BUCKET_OPERATING,
}


# ─── Primary-level fallback ──────────────────────────────────────────
#
# When detail doesn't match, fall through to primary. Primary covers
# the broad category families Plaid documents.

PRIMARY_MAP: Dict[str, str] = {
    # Outflows that count as "running the business"
    "GENERAL_MERCHANDISE":            BUCKET_OPERATING,
    "GENERAL_SERVICES":               BUCKET_OPERATING,
    "FOOD_AND_DRINK":                 BUCKET_OPERATING,
    "TRAVEL":                         BUCKET_OPERATING,
    "TRANSPORTATION":                 BUCKET_OPERATING,
    "RENT_AND_UTILITIES":             BUCKET_OPERATING,
    "MEDICAL":                        BUCKET_OPERATING,
    "PERSONAL_CARE":                  BUCKET_OPERATING,
    "ENTERTAINMENT":                  BUCKET_OPERATING,
    "HOME_IMPROVEMENT":               BUCKET_OPERATING,
    "BANK_FEES":                      BUCKET_OPERATING,
    "LOAN_PAYMENTS":                  BUCKET_OPERATING,

    # Government → tax (most specific subcategories caught above)
    "GOVERNMENT_AND_NON_PROFIT":      BUCKET_TAX,

    # Generic transfer out — when detail didn't disambiguate, lean
    # operating because that's the most likely outflow purpose for
    # an unspecified TRANSFER_OUT.
    "TRANSFER_OUT":                   BUCKET_OPERATING,

    # Inflows. We still tag a bucket for completeness, but inflows are
    # filtered OUT of the Allocator math (Allocator computes
    # actual_per_bucket from outflows only). 'other' is a safe label.
    "INCOME":                         BUCKET_OTHER,
    "TRANSFER_IN":                    BUCKET_OTHER,
}


def map_plaid_to_bucket(
    primary: Optional[str],
    detail: Optional[str],
) -> str:
    """Deterministic lookup. Returns one of ALL_BUCKETS.

    primary / detail come straight from Plaid's
    personal_finance_category.{primary, detailed} fields. Both are
    optional — Plaid leaves them null on some pending transactions; in
    that case we fall back to 'other'.
    """
    # Detail map first — most specific.
    if detail:
        norm = detail.strip().upper()
        if norm in DETAIL_MAP:
            return DETAIL_MAP[norm]
    # Primary map second.
    if primary:
        norm = primary.strip().upper()
        if norm in PRIMARY_MAP:
            return PRIMARY_MAP[norm]
    # Default.
    return BUCKET_OTHER


def is_income_category(primary: Optional[str], detail: Optional[str]) -> bool:
    """True when the Plaid category indicates an inflow we should
    EXCLUDE from the bucket-bound expense math.

    Used by the dashboard math + the reconciliation worker to skip
    income transactions when computing 'expenses MTD'."""
    p = (primary or "").strip().upper()
    d = (detail or "").strip().upper()
    if p in ("INCOME", "TRANSFER_IN"):
        return True
    # Tax REFUND is an inflow even though its primary is government.
    if d in ("GOVERNMENT_AND_NON_PROFIT_TAX_REFUND",):
        return True
    return False
