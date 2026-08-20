"""
receipts.py — what a customer actually receives (2026-08-20).

Pulled out of store_router so the wording can be read in a test instead
of in somebody's inbox. Pure: no network, no database, no clock.

A COUNTER SALE READS DIFFERENTLY ON PURPOSE
  "Thank you for your order" is wrong when somebody handed you a note
  and walked out with the thing. So is a fulfillment note about
  shipping — they already have it. Download links still go, because a
  digital item bought across the counter still has to be delivered
  somehow, and the practitioner has no other way to get it to them.

THE DISCOUNT IS DERIVED, NOT STORED
  Line items sum to the gross; the order carries the net. The
  difference is exactly what came off, always, for every order ever
  written — no column, no migration, and no way for the two to disagree.

  Showing it is not a nicety. Without it the receipt lists items adding
  up to $50 and then says the total is $40, and a customer who cannot
  make a receipt add up stops trusting the shop.

CURRENCY
  The old renderer hardcoded "$". This one reads the order's currency
  and produces byte-identical output for USD — so nothing changes for
  the receipts customers already get, while a business billing in
  pounds stops being told its prices are in dollars.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_CURRENCY_SYMBOLS = {
    "usd": "$", "cad": "$", "aud": "$", "nzd": "$",
    "gbp": "£", "eur": "€", "jpy": "¥",
}

_PAID_LABELS = {
    "cash": "Paid in cash",
    "card": "Paid by card",
    "other": "Paid",
    "stripe": "Paid by card",
}


def money(cents: Any, currency: str = "usd") -> str:
    """Cents → what a person reads. Unknown currencies get the code
    after the number rather than a wrong symbol in front of it."""
    try:
        amount = float(cents or 0) / 100.0
    except (TypeError, ValueError):
        amount = 0.0
    cur = (currency or "usd").lower()
    symbol = _CURRENCY_SYMBOLS.get(cur)
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {cur.upper()}"


def line_total_cents(item: Dict[str, Any]) -> int:
    try:
        return int(item.get("unit_amount_cents") or 0) * int(item.get("quantity") or 0)
    except (TypeError, ValueError):
        return 0


def discount_cents(order: Dict[str, Any], items: List[Dict[str, Any]]) -> int:
    """What came off, derived from the two numbers we already have.
    Never negative: shipping and tax live outside the subtotal, so a
    well-formed order can only ever have gross >= subtotal."""
    gross = sum(line_total_cents(it) for it in items)
    try:
        subtotal = int(order.get("subtotal_cents"))
    except (TypeError, ValueError):
        return 0
    return max(0, gross - subtotal)


def is_counter(order: Dict[str, Any]) -> bool:
    return (order.get("source") or "store") == "counter"


def render(order: Dict[str, Any], items: List[Dict[str, Any]], *,
           business_name: str = "",
           notes: Optional[List[str]] = None,
           downloads: Optional[List[str]] = None) -> Dict[str, str]:
    """The receipt, as {subject, body}."""
    notes = notes or []
    downloads = downloads or []
    counter = is_counter(order)
    cur = order.get("currency") or "usd"

    body_lines = "\n".join(
        f"  {it.get('quantity')} × {it.get('name_at_purchase')} — "
        f"{money(line_total_cents(it), cur)}"
        for it in items)

    extras = ""
    off = discount_cents(order, items)
    if off > 0:
        extras += f"\n  Discount — -{money(off, cur)}"
    if order.get("tax_cents"):
        extras += f"\n  Sales tax — {money(order['tax_cents'], cur)}"
    if order.get("shipping_cents"):
        extras += f"\n  Shipping — {money(order['shipping_cents'], cur)}"

    downloads_block = (
        "\n\nYour downloads (these links are yours — keep this email):\n"
        + "\n".join(downloads)) if downloads else ""
    notes_block = ("\n\n" + "\n".join(notes)) if notes else ""

    if counter:
        paid = _PAID_LABELS.get(
            (order.get("payment_method") or "").lower(), "Paid")
        greeting = ("Thanks for stopping by"
                    + (f" {business_name}" if business_name else "") + "!")
        return {
            "subject": f"Receipt from {business_name or 'your purchase'}",
            "body": (f"{greeting}\n\n"
                     f"{body_lines}{extras}\n\n"
                     f"Total — {money(order.get('total_cents'), cur)}\n"
                     f"{paid}"
                     f"{downloads_block}\n\n"
                     f"Questions? Just reply to this email.\n"
                     f"— {business_name}"),
        }

    return {
        "subject": f"Receipt — order {str(order.get('id') or '')[:8].upper()}",
        "body": (f"Thank you for your order from {business_name or 'us'}!\n\n"
                 f"{body_lines}{extras}\n\n"
                 f"Total — {money(order.get('total_cents'), cur)}"
                 f"{downloads_block}{notes_block}\n\n"
                 f"Questions? Just reply to this email.\n"
                 f"— {business_name}"),
    }


# ─── "It's on its way" ───────────────────────────────────────────────

# Carrier tracking-URL formats. This IS a lookup table, and it earns the
# exception: these are fixed external facts published by four companies,
# not a judgement about somebody's business. An unknown carrier simply
# gets no link — the number is still in the email, and a wrong link is
# worse than none.
_TRACKING_URLS = {
    "usps": "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}",
    "ups": "https://www.ups.com/track?tracknum={n}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={n}",
    "dhl": "https://www.dhl.com/en/express/tracking.html?AWB={n}",
}

CARRIERS = ["usps", "ups", "fedex", "dhl", "other"]


def tracking_url(carrier: Optional[str], number: Optional[str]) -> Optional[str]:
    """A link the customer can actually click, or None."""
    key = (carrier or "").strip().lower()
    num = (number or "").strip()
    if not num or key not in _TRACKING_URLS:
        return None
    # A tracking number is somebody's data going into a URL. Anything
    # that is not a plain code is not a tracking number.
    if not re.fullmatch(r"[A-Za-z0-9]{6,40}", num):
        return None
    return _TRACKING_URLS[key].format(n=num)


def carrier_label(carrier: Optional[str]) -> str:
    key = (carrier or "").strip().lower()
    return {"usps": "USPS", "ups": "UPS", "fedex": "FedEx",
            "dhl": "DHL"}.get(key, "the carrier")


def render_shipped(order: Dict[str, Any], items: List[Dict[str, Any]], *,
                   business_name: str = "") -> Dict[str, str]:
    """The email a customer actually wants: it left, and here is where
    it is.

    Deliberately short. A receipt already told them what they bought and
    what it cost; repeating all of that buries the one new fact, which
    is the tracking number.
    """
    what = ", ".join(
        f"{it.get('quantity')} × {it.get('name_at_purchase')}" for it in items)
    carrier = order.get("tracking_carrier")
    number = (order.get("tracking_number") or "").strip()
    link = tracking_url(carrier, number)

    track = ""
    if number:
        track = f"\n\n{carrier_label(carrier)} tracking: {number}"
        if link:
            track += f"\n{link}"
    else:
        # Marked shipped with no number — say so plainly rather than
        # leaving a gap where a tracking number should be.
        track = "\n\nThere's no tracking number for this one."

    return {
        "subject": f"Your order from {business_name or 'us'} is on its way",
        "body": (f"Good news — your order has shipped."
                 + (f"\n\n{what}" if what else "")
                 + track
                 + "\n\nQuestions? Just reply to this email."
                 + f"\n— {business_name}"),
    }
