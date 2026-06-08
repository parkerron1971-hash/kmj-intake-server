"""
plaid_reconciliation.py — Phase F.2 v1.

Auto-match Stripe payouts to Plaid bank deposits per T5-α ruling:

    Match when:
      - same business_id
      - Plaid amount is negative (Plaid sign convention: outflow positive,
        inflow negative — deposits arrive as negative)
      - Plaid date within ±2 days of Stripe payout.arrival_date
      - abs(Plaid amount) == payout.amount (cents-aware tolerance)

Also wires the placeholder for F.1 (Stripe Transfer → Plaid debit on
practitioner side); column + match function are ready but the worker
is a no-op until outbound_transfers rows exist.

Used by:
  - the /plaid/sync handler (after upserting new transactions)
  - the Stripe payout webhook handler (after a new payout arrives,
    re-attempt matching against existing unmatched Plaid deposits)
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("plaid_reconciliation")


# Match tolerance: Stripe + Plaid arrival dates align to the same
# business day on most banks but the 1-day weekend / holiday lag is
# common. ±2 covers that without inviting false positives.
DATE_TOLERANCE_DAYS = 2

# Amount tolerance: payouts should be exact-cents. Some banks round
# (rare); 0.01 absorbs the edge case without admitting drift.
AMOUNT_TOLERANCE_CENTS = 1


def _stripe_account_for_business(business_id: str) -> Optional[str]:
    """Lookup of the connected Stripe account id used to query the
    payouts list against."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=stripe_account_id&limit=1"
    ) or []
    if not rows:
        return None
    return (rows[0].get("stripe_account_id") or "").strip() or None


def _fetch_stripe_payouts_around(
    stripe_account_id: str,
    around_date: date,
    *,
    window_days: int = DATE_TOLERANCE_DAYS,
) -> List[Dict[str, Any]]:
    """Fetch Stripe payouts on the connected account whose arrival_date
    is within ±window_days of around_date. Used by the matcher to find
    candidates for a fresh Plaid deposit.

    Returns the raw Stripe payout objects. On error returns []; the
    matcher just doesn't reconcile that transaction this pass — next
    sync will retry."""
    import httpx
    api_key = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not api_key:
        return []
    start = int((around_date - timedelta(days=window_days)).strftime("%s")) \
        if hasattr(date, "strftime") else 0
    end = int((around_date + timedelta(days=window_days + 1)).strftime("%s")) \
        if hasattr(date, "strftime") else 0
    # date.strftime doesn't take %s; use a portable conversion instead.
    from datetime import datetime, timezone
    start = int(datetime(
        around_date.year, around_date.month, around_date.day,
        tzinfo=timezone.utc,
    ).timestamp()) - window_days * 86400
    end = start + (2 * window_days + 1) * 86400
    try:
        r = httpx.get(
            "https://api.stripe.com/v1/payouts",
            auth=(api_key, ""),
            headers={"Stripe-Account": stripe_account_id},
            params={
                "limit": 25,
                "arrival_date[gte]": start,
                "arrival_date[lte]": end,
            },
            timeout=15.0,
        )
        if r.status_code >= 400:
            logger.warning(f"[reconcile] stripe payouts fetch failed: {r.status_code}")
            return []
        return (r.json() or {}).get("data") or []
    except Exception as e:
        logger.warning(f"[reconcile] stripe payouts fetch errored: {e}")
        return []


def _payout_arrival_iso(payout: Dict[str, Any]) -> Optional[str]:
    """Stripe arrival_date is a unix timestamp; render as yyyy-mm-dd."""
    ts = payout.get("arrival_date")
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except Exception:
        return None


def fetch_stripe_payouts_range(
    stripe_account_id: str,
    start_date: date,
    end_date: date,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List Stripe payouts on the connected account whose arrival_date is
    within [start_date, end_date]. Powers the unmatched-Stripe-side table +
    manual-match suggestions. Returns [] on error (caller degrades)."""
    import httpx
    from datetime import datetime, timezone
    api_key = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not api_key:
        return []
    start = int(datetime(start_date.year, start_date.month, start_date.day,
                         tzinfo=timezone.utc).timestamp())
    end = int(datetime(end_date.year, end_date.month, end_date.day,
                       tzinfo=timezone.utc).timestamp()) + 86400
    try:
        r = httpx.get(
            "https://api.stripe.com/v1/payouts",
            auth=(api_key, ""),
            headers={"Stripe-Account": stripe_account_id},
            params={"limit": min(int(limit), 100),
                    "arrival_date[gte]": start, "arrival_date[lte]": end},
            timeout=15.0,
        )
        if r.status_code >= 400:
            logger.warning(f"[reconcile] payouts range fetch failed: {r.status_code}")
            return []
        return (r.json() or {}).get("data") or []
    except Exception as e:
        logger.warning(f"[reconcile] payouts range fetch errored: {e}")
        return []


def stripe_account_for_business(business_id: str) -> Optional[str]:
    """Public wrapper for the connected-account lookup (used by the
    reconciliation router)."""
    return _stripe_account_for_business(business_id)


def _amounts_match(plaid_amount_dollars, payout_amount_cents: int) -> bool:
    """Plaid amounts are signed dollar decimals (positive = outflow).
    Payout amounts are unsigned integer cents."""
    plaid_cents = int(round(abs(float(plaid_amount_dollars)) * 100))
    return abs(plaid_cents - int(payout_amount_cents)) <= AMOUNT_TOLERANCE_CENTS


def try_match_transaction(tx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Try to match one Plaid transaction to a Stripe payout (income side)
    or — when F.1 ships — to a Stripe Transfer (outbound side).

    Returns the patch dict to apply to the transaction row (with
    reconciled_to_* set + reconciliation_status='auto_matched') OR
    None when no confident match.
    """
    business_id = tx.get("business_id")
    if not business_id:
        return None
    if tx.get("reconciliation_status") and tx["reconciliation_status"] != "unmatched":
        return None  # already settled
    if tx.get("pending"):
        return None  # don't reconcile against pending transactions

    amount = tx.get("amount")
    if amount is None:
        return None
    try:
        amt = Decimal(str(amount))
    except Exception:
        return None

    # ─── Deposit side (Stripe payout → bank deposit) ───────────────
    # Plaid sign: deposits are negative. Match those.
    if amt < 0:
        stripe_acct = _stripe_account_for_business(str(business_id))
        if not stripe_acct:
            return None
        # Plaid 'date' is yyyy-mm-dd string.
        tx_date_str = tx.get("date")
        if not tx_date_str:
            return None
        try:
            from datetime import date as _date
            y, m, d = (int(p) for p in tx_date_str.split("-"))
            tx_date = _date(y, m, d)
        except Exception:
            return None
        candidates = _fetch_stripe_payouts_around(stripe_acct, tx_date)
        for po in candidates:
            if _amounts_match(amt, po.get("amount") or 0):
                return {
                    "reconciled_to_payout_id": po.get("id"),
                    "reconciliation_status": "auto_matched",
                    # Snapshot so the matched table renders without a live
                    # Stripe fetch per row (F.2 v1.6).
                    "reconciled_payout_amount": round((po.get("amount") or 0) / 100.0, 2),
                    "reconciled_payout_date": _payout_arrival_iso(po),
                }

    # ─── Transfer side (F.1 placeholder) ───────────────────────────
    # Outflow side: Plaid debit corresponds to a Stripe Transfer we
    # initiated to a contractor. F.1 will populate outbound_transfers.
    # Until then this path is a no-op — column exists for future use.
    # if amt > 0:
    #     transfer_row = sb_clients.sb_get_as_service(
    #         f"/outbound_transfers?business_id=eq.{business_id}"
    #         f"&amount=eq.{amount}&status=eq.paid"
    #         f"&date[gte]={tx_date - timedelta(days=2)}"
    #         f"&date[lte]={tx_date + timedelta(days=2)}&limit=1"
    #     ) or []
    #     if transfer_row:
    #         return {
    #             "reconciled_to_transfer_id": transfer_row[0].get("stripe_transfer_id"),
    #             "reconciliation_status": "auto_matched",
    #         }

    return None


def reconcile_business(business_id: str, *, limit: int = 200) -> Tuple[int, int]:
    """Run a reconciliation pass over a business's unmatched
    transactions. Returns (attempted, matched).

    Called from /plaid/sync after each cursor advance, and via a
    POST /plaid/reconcile manual trigger from the dashboard's
    Needs Review CTA."""
    # Only reconcile transactions on accounts the practitioner kept in
    # bookkeeping (included + not removed). Excluded/removed accounts'
    # deposits shouldn't auto-match to Stripe payouts.
    included_rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null"
        f"&select=account_id"
    ) or []
    included = [r["account_id"] for r in included_rows if r.get("account_id")]
    if not included:
        return (0, 0)
    acct_clause = "account_id=in.(" + ",".join(included) + ")"

    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{business_id}"
        f"&reconciliation_status=eq.unmatched"
        f"&pending=eq.false&excluded_from_books=eq.false&{acct_clause}"
        f"&order=date.desc&limit={int(limit)}"
        f"&select=transaction_id,amount,date,pending,business_id"
    ) or []
    matched = 0
    for row in rows:
        patch = try_match_transaction(row)
        if patch:
            try:
                sb_clients.sb_patch_as_service(
                    f"/plaid_transactions?transaction_id=eq.{row['transaction_id']}",
                    patch,
                )
                matched += 1
            except Exception as e:
                logger.warning(
                    f"[reconcile] patch failed for tx {row.get('transaction_id')}: {e}"
                )
    if rows:
        logger.info(
            f"[reconcile] business={business_id[:8]} attempted={len(rows)} "
            f"matched={matched}"
        )
    return (len(rows), matched)
