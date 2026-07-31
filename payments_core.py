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


def providers_status(biz_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Registry truth for status surfaces: which providers exist, which
    can be connected, which IS connected for this business."""
    return [{
        "id": a.id,
        "name": a.display_name,
        "connectable": a.connectable,
        "connected": a.is_connected(biz_row),
    } for a in REGISTRY.values()]
