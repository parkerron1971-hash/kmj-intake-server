"""
payments_core.py — Rails demand-driven arc — the payment adapter seam.

The ruling: don't replace Stripe — ABSTRACT the payment layer so
Stripe is adapter #1 and a future processor drops in without a
rewrite. Stripe touches ~46 backend files; this migrates incrementally
behind an interface, not big-bang. The seam's contract:

  * NEW payment code imports payments_core, never a stripe_* module.
  * Money-moving verbs live on the adapter: create_booking_checkout,
    create_refund, is_connected. The seam grows a verb the day a
    second call site needs it — never speculatively.
  * provider_for(biz_row) picks the adapter from
    settings.payments.provider (default 'stripe'). One selection
    point, so per-business provider choice is a data change.
  * Existing stripe_* call sites migrate opportunistically — each
    edit shrinks the direct-coupling count without a flag day.

Adding a provider = one adapter class + one REGISTRY line. Until an
adapter implements a verb, callers get a clean 409 ("not supported by
<provider> yet"), never a silent Stripe fallback.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger("payments_core")


# ─── Barber-money: deposit math (provider-agnostic) ──────────────────

def compute_deposit_cents(offering: Optional[Dict[str, Any]],
                          price_cents: int) -> Optional[int]:
    """The ONE place deposit amounts are computed (server-side only —
    the widget displays what config-anon echoes back from here). Lives
    on the seam because deposit policy is money math, not a provider
    behavior — every adapter charges the same computed cents.

    Returns the deposit in cents, or None when the booking should be a
    normal full-price checkout. FAIL-SOFT by construction: the offerings
    deposit columns may not exist yet (deploy-order safety), in which
    case `offering` simply lacks the keys and every read below falls
    through to None.

    Rules:
      * requires_deposit must be truthy and deposit_type/amount valid.
      * percent → round(price_cents * amount / 100) to the cent.
      * flat    → round(amount * 100).
      * A computed deposit <= 0 or >= the full price degrades to
        full-price (None) — a "100% deposit" is just prepayment and a
        misconfigured $0 deposit must not create a free booking.
    """
    o = offering or {}
    if not o.get("requires_deposit"):
        return None
    dtype = (o.get("deposit_type") or "").strip().lower()
    try:
        amount = float(o.get("deposit_amount") or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0 or price_cents <= 0:
        return None
    if dtype == "percent":
        cents = int(round(price_cents * amount / 100.0))
    elif dtype == "flat":
        cents = int(round(amount * 100))
    else:
        return None
    if cents <= 0 or cents >= price_cents:
        return None
    return cents


class PaymentAdapter:
    """Base adapter. Verbs raise 409 unless the provider implements
    them — a caller can always ask, and always gets an honest answer."""

    id: str = "base"
    display_name: str = "Base"
    #: Can this provider be connected through the app today?
    connectable: bool = False

    def is_connected(self, biz_row: Dict[str, Any]) -> bool:
        return False

    async def create_booking_checkout(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        raise HTTPException(409, f"online checkout isn't supported by {self.display_name} yet")

    async def create_invoice_checkout(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        raise HTTPException(409, f"invoice pay links aren't supported by {self.display_name} yet")

    async def create_refund(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        raise HTTPException(409, f"refunds aren't supported by {self.display_name} yet")

    async def charge_saved_payment_method(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        # Barber-money — the operator-triggered no-show fee charges a
        # card stored at booking checkout. Grown per the seam contract:
        # a real call site (/payments/charge-no-show) needed the verb.
        raise HTTPException(409, f"saved-card charges aren't supported by {self.display_name} yet")

    async def create_giving_checkout(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        # Online giving (ministry/nonprofit) — grown per the seam
        # contract: giving_router's public checkout is the call site.
        raise HTTPException(409, f"online giving isn't supported by {self.display_name} yet")


class StripeAdapter(PaymentAdapter):
    """Adapter #1 — wraps the existing, battle-tested helpers. No
    behavior change: same calls, one import path."""

    id = "stripe"
    display_name = "Stripe"
    connectable = True

    def is_connected(self, biz_row: Dict[str, Any]) -> bool:
        return bool((biz_row or {}).get("stripe_account_id"))

    async def create_booking_checkout(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        from stripe_checkout_helpers import create_booking_checkout
        return await create_booking_checkout(
            stripe_account_id=biz_row["stripe_account_id"], **kwargs)

    async def create_invoice_checkout(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        from stripe_checkout_helpers import create_invoice_checkout
        return await create_invoice_checkout(
            stripe_account_id=biz_row["stripe_account_id"], **kwargs)

    async def create_refund(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        from stripe_checkout_helpers import create_refund
        return await create_refund(
            stripe_account_id=biz_row["stripe_account_id"], **kwargs)

    async def charge_saved_payment_method(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        from stripe_checkout_helpers import charge_saved_payment_method
        return await charge_saved_payment_method(
            stripe_account_id=biz_row["stripe_account_id"], **kwargs)

    async def create_giving_checkout(self, biz_row: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        from stripe_checkout_helpers import create_giving_checkout
        return await create_giving_checkout(
            stripe_account_id=biz_row["stripe_account_id"], **kwargs)


class SquareAdapter(PaymentAdapter):
    id = "square"
    display_name = "Square"


class PayPalAdapter(PaymentAdapter):
    id = "paypal"
    display_name = "PayPal"


REGISTRY: Dict[str, PaymentAdapter] = {
    a.id: a for a in (StripeAdapter(), SquareAdapter(), PayPalAdapter())
}


def provider_for(biz_row: Dict[str, Any]) -> PaymentAdapter:
    """The business's processing provider. settings.payments.provider,
    default stripe. Unknown values fall back to stripe LOUDLY."""
    pid = str((((biz_row or {}).get("settings") or {}).get("payments") or {})
              .get("provider") or "stripe").lower()
    adapter = REGISTRY.get(pid)
    if not adapter:
        logger.error(f"[payments] unknown provider '{pid}' on business "
                     f"{str(biz_row.get('id'))[:8]} — falling back to stripe")
        return REGISTRY["stripe"]
    return adapter


def can_charge(biz_row: Dict[str, Any]) -> bool:
    """Can this business ACTUALLY take a card right now?

    2026-08-13 site-builder audit: every gate on the platform asked
    `stripe_account_id is not null` and called that "can take money".
    That is the cheapest available proxy, not the condition that has to
    hold. Standard OAuth returns an account id for a restricted or
    half-onboarded account, and the account.updated webhook faithfully
    persists charges_enabled / payouts_enabled / details_submitted into
    settings.stripe — where, until now, NOTHING read them back. At the
    time of the audit one of the three connected businesses in
    production had charges_enabled=false and passed every gate in the
    codebase.

    Unknown is deliberately treated as chargeable. A business that
    connects before the webhook lands has no flags yet, and refusing it
    would break onboarding to fix a subset of it. Only an explicit false
    blocks — which is the state Stripe would reject anyway, so the
    practitioner hears it from us instead of from a failed checkout in
    front of a customer.
    """
    if not (biz_row or {}).get("stripe_account_id"):
        return False
    settings = (biz_row or {}).get("settings")
    stripe_cfg = settings.get("stripe") if isinstance(settings, dict) else None
    if not isinstance(stripe_cfg, dict):
        return True
    charges = stripe_cfg.get("charges_enabled")
    if charges is None or str(charges).strip() == "":
        return True          # never reported — assume yes, see docstring
    return str(charges).strip().lower() in ("true", "1", "yes")


def providers_status(biz_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Registry truth for status surfaces: which providers exist, which
    can be connected, which IS connected for this business."""
    return [{
        "id": a.id,
        "name": a.display_name,
        "connectable": a.connectable,
        "connected": a.is_connected(biz_row),
        # Connected is not the same as usable — see can_charge.
        "can_charge": can_charge(biz_row) if a.id == "stripe" else a.is_connected(biz_row),
    } for a in REGISTRY.values()]
