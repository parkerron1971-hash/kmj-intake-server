"""
bank_money.py — what a bank row IS, in one place.

Income or not, spending or not, "still needs a category" or not: these
questions used to be answered separately in the ledger (gl_engine), the
source-table reports (reports_engine), the cash-flow summary
(plaid_router), Chief's bookkeeping prompt, and the Bookkeeping overview.
Each one asked Plaid's category directly, and some disagreed.

plaid_transactions.money_kind (APPLY-2026-10-02-bank-money-kind.sql) is
the practitioner's answer when the bank's label is wrong:

    income    a deposit that IS business income
    owner     money between the owner and the business (in or out)
    transfer  a move between the business's own accounts
    NULL      automatic: Plaid's category decides, exactly as before

The column arrives by hand-applied migration. Until it exists, selecting
it makes PostgREST reject the whole read, so `supported()` probes once
(cached for five minutes) and every caller asks `cols()` / the filters
for the right shape. Before the migration the app behaves exactly as it
did; within five minutes after, it honours money_kind.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import sb_clients
import plaid_categorization

KINDS = ("income", "owner", "transfer")

_PROBE_TTL = 300.0
_probe: Dict[str, Any] = {"at": 0.0, "ok": False}


def supported() -> bool:
    """Does plaid_transactions.money_kind exist? Cached for five minutes. A
    failed probe reads as "not yet", which falls back to the old behaviour,
    the safe direction."""
    now = time.monotonic()
    if _probe["at"] and now - _probe["at"] < _PROBE_TTL:
        return _probe["ok"]
    rows = sb_clients.sb_get_as_service("/plaid_transactions?select=money_kind&limit=1")
    _probe.update(at=now, ok=rows is not None)
    return _probe["ok"]


def cols() -> str:
    """Append to a plaid_transactions select: ',money_kind' once it exists."""
    return ",money_kind" if supported() else ""


def kind(t: Dict[str, Any]) -> Optional[str]:
    k = t.get("money_kind")
    return k if k in KINDS else None


def _amt(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _plaid_income(t: Dict[str, Any]) -> bool:
    return plaid_categorization.is_income_category(
        t.get("plaid_category_primary"), t.get("plaid_category_detail"))


def is_income(t: Dict[str, Any]) -> bool:
    """A deposit the books count as income. Payout deposits are explained by
    Stripe (Stripe Clearing), never double-counted here. Plaid sign:
    negative = money in."""
    if _amt(t) >= 0 or t.get("reconciled_to_payout_id"):
        return False
    k = kind(t)
    if k is not None:
        return k == "income"
    return _plaid_income(t)


def is_expense(t: Dict[str, Any]) -> bool:
    """Money out the books count as an expense (in its five-bucket line)."""
    if _amt(t) <= 0:
        return False
    k = kind(t)
    if k in ("owner", "transfer"):
        return False
    return not _plaid_income(t)


def needs_category(t: Dict[str, Any]) -> bool:
    """Still waiting on the practitioner: no answer of what it is, and no
    spending bucket beyond the 'other' catch-all. The same rule as
    `uncategorized_filter()`, so a count and its list always agree."""
    if kind(t) is not None:
        return False
    return t.get("business_category") in (None, "", "other")


def _uncat_clause() -> str:
    """The predicate body (no key) for "needs a category"."""
    base = "or(business_category.is.null,business_category.eq.other)"
    return f"and(money_kind.is.null,{base})" if supported() else base


def uncategorized_filter() -> str:
    """A whole PostgREST param for "needs a category". Uses `and=` at the top
    so it can't collide with a search's `or=` in the same query."""
    return f"and=({_uncat_clause()})"


def uncategorized_or(named_buckets: List[str]) -> str:
    """'needs a category' OR one of the named buckets, as one param."""
    if not named_buckets:
        return uncategorized_filter()
    return f"and=(or({_uncat_clause()},business_category.in.({','.join(named_buckets)})))"
