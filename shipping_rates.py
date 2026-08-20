"""
shipping_rates.py — what shipping costs, and who decides (2026-08-20).

THE PROBLEM WITH WHAT WAS HERE
  One flat fee per business, charged once per order containing anything
  physical. The same money for a keychain and a twenty-pound box, to the
  next street or across the country. A shop selling anything heavy was
  quietly losing money on every order, and one selling small things was
  overcharging people who noticed.

THE SHAPE: ONE ENGINE, SEVERAL SOURCES
  Rates come from sources, and the sources are ranked by how much they
  know:

    pickup    — free, offered when the shop says it will hand things over
    built-in  — flat + per-product surcharge, with a free-over threshold
    carrier   — live USPS/UPS prices (carriers.py, when connected)

  A checkout must NEVER fail because somebody else's server is slow, so
  the built-in rate is the FLOOR, not the fallback of last resort: if
  carrier rating errors, times out, or a product has no weight to rate
  with, the customer still sees a price and still checks out. Same rule
  as the barcode lookup — the free path always works and the clever path
  is an upgrade.

WHY THE SERVER RE-PRICES
  quote() is pure and runs in two places: once to SHOW the options, and
  again at checkout to CHARGE. The client sends back which option was
  chosen — a code, never an amount. A checkout that accepts a shipping
  price off the wire is a checkout where shipping is free for anybody
  who reads the page source.

WHY NOT PER-DESTINATION ZONES
  Deliberately not built. Zone tables are the part of shipping that
  every small shop gets wrong and then maintains forever, and the honest
  version of "it costs more to send it further" is a live carrier rate —
  which is the source above. Flat, free-over and pickup cover the shops
  this serves; anything more precise should come from a carrier, not
  from a table somebody hand-edits once and never revisits.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("shipping_rates")

# The one place a shipping price can be named. A code travels between
# the storefront and the checkout; an AMOUNT never does.
PICKUP = "pickup"
FLAT = "flat"

# Countries the storefront will take an address in. US-only was
# hardcoded into the Stripe call, so a Canadian customer could not buy a
# physical product at all — the address form simply refused them.
DEFAULT_COUNTRIES = ["US"]

_MAX_COUNTRIES = 40


def settings_of(biz: Dict[str, Any]) -> Dict[str, Any]:
    """The shipping settings, with the old flat fee honoured.

    `flat_shipping_cents` has been the whole of shipping since Arc 27,
    so it stays the fallback for `flat_cents` forever — a business that
    set one and never touches the new screen keeps charging exactly what
    it charged yesterday.
    """
    # isinstance, not `or {}` — a non-empty STRING is truthy, so a
    # settings blob holding `"shipping": "none"` would sail past a
    # falsy check and then blow up on .get(). Settings are edited by
    # hand, by Chief, and by migrations; assume nothing about shape.
    def _dict(v):
        return v if isinstance(v, dict) else {}

    store = _dict(_dict(biz.get("settings")).get("store"))
    ship = _dict(store.get("shipping"))

    def _int(v, default=0):
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return default

    legacy_flat = _int(store.get("flat_shipping_cents"))
    free_over = ship.get("free_over_cents")
    countries = ship.get("countries")
    if not isinstance(countries, list) or not countries:
        countries = DEFAULT_COUNTRIES
    countries = [str(c).upper()[:2] for c in countries if str(c).strip()][:_MAX_COUNTRIES]

    pickup = _dict(ship.get("pickup"))
    return {
        "flat_cents": _int(ship.get("flat_cents"), legacy_flat) if "flat_cents" in ship
                      else legacy_flat,
        "free_over_cents": (_int(free_over) if free_over not in (None, "") else None),
        "pickup_enabled": bool(pickup.get("enabled")),
        "pickup_note": str(pickup.get("note") or "")[:200],
        "countries": countries or DEFAULT_COUNTRIES,
        "carrier_enabled": bool(ship.get("carrier_enabled")),
    }


def needs_shipping(items: List[Dict[str, Any]]) -> bool:
    """Anything in this basket physical? Nothing physical means shipping
    is not a question the customer should be asked at all."""
    return any(bool(it.get("requires_shipping")) for it in items)


def surcharge_cents(items: List[Dict[str, Any]]) -> int:
    """Extra postage the heavy things add. Per UNIT, because two
    barber chairs cost twice as much to send as one — a per-line
    surcharge would let somebody order ten and pay for one."""
    total = 0
    for it in items:
        if not it.get("requires_shipping"):
            continue
        try:
            each = max(0, int(it.get("ship_surcharge_cents") or 0))
            qty = max(0, int(it.get("quantity") or 1))
        except (TypeError, ValueError):
            continue
        total += each * qty
    return total


def total_weight_oz(items: List[Dict[str, Any]]) -> Optional[float]:
    """Basket weight, or None when anything physical has no weight on
    file. None means "do not ask a carrier" — a quote for the wrong
    weight is worse than no quote, because it is charged."""
    total = 0.0
    for it in items:
        if not it.get("requires_shipping"):
            continue
        w = it.get("weight_oz")
        if w in (None, ""):
            return None
        try:
            total += max(0.0, float(w)) * max(0, int(it.get("quantity") or 1))
        except (TypeError, ValueError):
            return None
    return round(total, 2) if total > 0 else None


def builtin_rates(items: List[Dict[str, Any]], cfg: Dict[str, Any],
                  subtotal_cents: int) -> List[Dict[str, Any]]:
    """The rates every shop has without connecting anything. Pure."""
    if not needs_shipping(items):
        return []

    out: List[Dict[str, Any]] = []

    if cfg.get("pickup_enabled"):
        out.append({
            "code": PICKUP,
            "label": "Pick up",
            "amount_cents": 0,
            "note": cfg.get("pickup_note") or "Collect it from us",
            "source": "pickup",
        })

    amount = int(cfg.get("flat_cents") or 0) + surcharge_cents(items)
    free_over = cfg.get("free_over_cents")
    note = ""
    if free_over is not None and free_over > 0 and subtotal_cents >= free_over:
        # The threshold beats the surcharge on purpose. "Free shipping
        # over $50" that quietly still charges $40 for the heavy item is
        # a promise broken at the last screen, which is the single most
        # expensive place to break one.
        amount = 0
        note = "Free — your order is over the threshold"
    out.append({
        "code": FLAT,
        "label": "Shipping" if amount else "Free shipping",
        "amount_cents": amount,
        "note": note,
        "source": "builtin",
    })
    return out


def quote(items: List[Dict[str, Any]], cfg: Dict[str, Any], *,
          subtotal_cents: int,
          carrier_rates: Optional[List[Dict[str, Any]]] = None
          ) -> List[Dict[str, Any]]:
    """Every shipping option for this basket, cheapest first within kind.

    `carrier_rates` is whatever carriers.py managed to fetch — an empty
    list or None simply means the customer sees the built-in rate, which
    is why a carrier outage cannot stop a sale.
    """
    rates = builtin_rates(items, cfg, subtotal_cents)
    if not rates:
        return []
    for r in (carrier_rates or []):
        try:
            rates.append({
                "code": str(r["code"])[:60],
                "label": str(r.get("label") or "Shipping")[:80],
                "amount_cents": max(0, int(r["amount_cents"])),
                "note": str(r.get("note") or "")[:120],
                "source": "carrier",
            })
        except (KeyError, TypeError, ValueError):
            # One malformed carrier rate must not cost the customer the
            # options that are fine.
            continue
    # Pickup first (it is free and local), then by price.
    rates.sort(key=lambda r: (r["code"] != PICKUP, r["amount_cents"]))
    return rates


def resolve(items: List[Dict[str, Any]], cfg: Dict[str, Any], *,
            subtotal_cents: int, chosen_code: Optional[str],
            carrier_rates: Optional[List[Dict[str, Any]]] = None
            ) -> Dict[str, Any]:
    """The rate to actually CHARGE, priced here and not by the client.

    An unknown or stale code falls back to the default rather than
    failing: the basket may have changed since the page rendered, and
    dropping somebody at the last step over a stale radio button is a
    lost sale, not a security win. The price is ours either way, which
    is the part that actually matters.
    """
    rates = quote(items, cfg, subtotal_cents=subtotal_cents,
                  carrier_rates=carrier_rates)
    if not rates:
        return {"code": None, "label": "", "amount_cents": 0, "source": "none"}
    if chosen_code:
        for r in rates:
            if r["code"] == chosen_code:
                return r
        logger.info(f"[shipping] unknown rate code {chosen_code!r} — using default")
    # Default = the first non-pickup option, so nobody is silently
    # switched to collection they cannot make.
    for r in rates:
        if r["code"] != PICKUP:
            return r
    return rates[0]
