"""
Prepaid credit ledger — Pricing v2 Phase C (docs/pricing_model_v2.md §6).

Credits are "AI action units" bought in one-time Stripe packs. They sit
in credit_ledger as signed rows (purchase/grant positive, burn negative)
and NEVER expire. Draw-down order is always: monthly plan allowance
first, then credits.

Burning is LAZY: nothing writes per-interaction. Whenever a summary is
read, sync_burn() reconciles this month's burn row (one row per
business per month, source='auto:YYYY-MM', UPSERTed) against
  min(usage beyond allowance this month, credits available).
The unique partial index on (business_id, source) where kind='burn'
makes concurrent reconciles collapse into one row instead of stacking.

Every read here fails OPEN (0 / no-op) — billing bookkeeping must never
brick Chief. Enforcement stays off until calibration + the meter UI are
live and Kevin flips it explicitly (spec §6.6).
"""

import logging
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("credit_ledger")

# Packs — LOCKED by Kevin 2026-07-12 (spec §7.1): cents charged → units.
CREDIT_PACKS: Dict[str, Dict[str, int]] = {
    "small":  {"cents": 1000, "units": 100},
    "medium": {"cents": 2500, "units": 275},
    "large":  {"cents": 5000, "units": 600},
}


def _month_key() -> str:
    from usage_metering import _month_key as mk
    return mk()


def balance(business_id: str) -> int:
    """Current credit balance = SUM(delta_units). Fails open to 0."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/credit_ledger?business_id=eq.{business_id}"
            f"&select=delta_units&limit=10000") or []
        return sum(int(r.get("delta_units") or 0) for r in rows)
    except Exception as e:
        logger.warning(f"[credits] balance read failed open: {e}")
        return 0


def grant_pack(business_id: str, pack: str, stripe_payment_id: str) -> bool:
    """Credit a purchased pack. Idempotent: the UNIQUE index on
    stripe_payment_id turns a webhook retry into a 409 no-op."""
    p = CREDIT_PACKS.get(pack)
    if not p:
        logger.error(f"[credits] unknown pack '{pack}' for {business_id}")
        return False
    try:
        res = sb_clients.sb_post_as_service("/credit_ledger", {
            "business_id": business_id,
            "delta_units": p["units"],
            "kind": "purchase",
            "source": f"stripe:pack_{pack}",
            "stripe_payment_id": stripe_payment_id,
            "note": f"{p['units']} units (${p['cents'] / 100:.0f} pack)",
        })
        if res is None:
            # POST helper returns None on non-2xx; a duplicate payment id
            # (webhook retry) lands here too — check whether it exists.
            rows = sb_clients.sb_get_as_service(
                f"/credit_ledger?stripe_payment_id=eq.{stripe_payment_id}"
                f"&select=id&limit=1") or []
            if rows:
                logger.info(f"[credits] pack already granted for {stripe_payment_id} (dedupe)")
                return True
            logger.error(f"[credits] grant insert failed for {business_id}/{pack}")
            return False
        logger.info(f"[credits] granted {p['units']} units to {business_id} ({pack})")
        return True
    except Exception as e:
        logger.exception(f"[credits] grant_pack failed: {e}")
        return False


def grant_units(business_id: str, units: int, source: str,
                note: Optional[str] = None) -> bool:
    """Owner grant (beta comps, goodwill). Same ledger, kind='grant',
    source-tagged, never expires (Kevin's ruling, spec §7.2)."""
    if units <= 0:
        return False
    try:
        return sb_clients.sb_post_as_service("/credit_ledger", {
            "business_id": business_id,
            "delta_units": units,
            "kind": "grant",
            "source": source,
            "note": note,
        }) is not None
    except Exception as e:
        logger.exception(f"[credits] grant_units failed: {e}")
        return False


def sync_burn(business_id: str, overage_units_this_month: int) -> int:
    """Reconcile this month's burn row against actual usage-past-
    allowance. Returns credits BURNED this month after the sync.

    Target burn = min(overage this month, credits that existed before
    this month's burn). One UPSERTed row per month means a re-read with
    higher usage just grows the same row — never double-counts."""
    month = _month_key()
    src = f"auto:{month}"
    try:
        rows = sb_clients.sb_get_as_service(
            f"/credit_ledger?business_id=eq.{business_id}"
            f"&kind=eq.burn&source=eq.{src}&select=id,delta_units&limit=1") or []
        already = -int(rows[0]["delta_units"]) if rows else 0

        # Credits available to burn this month = balance with this
        # month's own burn added back.
        available = balance(business_id) + already
        target = max(0, min(int(overage_units_this_month), available))

        if target == already:
            return already
        if target == 0 and rows:
            sb_clients.sb_delete_as_service(f"/credit_ledger?id=eq.{rows[0]['id']}")
            return 0
        if rows:
            sb_clients.sb_patch_as_service(
                f"/credit_ledger?id=eq.{rows[0]['id']}",
                {"delta_units": -target,
                 "note": f"usage beyond allowance, {month}"})
        else:
            res = sb_clients.sb_post_as_service("/credit_ledger", {
                "business_id": business_id,
                "delta_units": -target,
                "kind": "burn",
                "source": src,
                "note": f"usage beyond allowance, {month}",
            })
            if res is None:
                # Lost a concurrent-insert race to the unique index —
                # the other writer owns the row now; leave it be.
                logger.info(f"[credits] burn upsert race for {business_id} {month}")
        return target
    except Exception as e:
        logger.warning(f"[credits] sync_burn failed open: {e}")
        return 0


def summary(business_id: str) -> Dict[str, Any]:
    """Ledger digest for the Plan & Usage meter."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/credit_ledger?business_id=eq.{business_id}"
            f"&select=delta_units,kind&limit=10000") or []
        bal = sum(int(r.get("delta_units") or 0) for r in rows)
        bought = sum(int(r["delta_units"]) for r in rows if r.get("kind") == "purchase")
        granted = sum(int(r["delta_units"]) for r in rows if r.get("kind") == "grant")
        burned = -sum(int(r["delta_units"]) for r in rows if r.get("kind") == "burn")
        return {"balance": bal, "purchased": bought,
                "granted": granted, "burned": burned}
    except Exception as e:
        logger.warning(f"[credits] summary failed open: {e}")
        return {"balance": 0, "purchased": 0, "granted": 0, "burned": 0}
