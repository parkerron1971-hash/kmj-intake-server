"""
offering_profiles.py — Arc 28 PR1 — category behavior profiles + readiness.

Arc 28 ruling: an offering's category is a CONTRACT, not a label. Each
category declares its behavior (bookable / sellable / both-capable),
which fields matter, where it surfaces, and what must be true before a
customer can actually book or buy it. This module is the single source
of truth consumed by:
  - GET /offerings/readiness (offerings_router) → OfferingsManager chips
  - Chief's offering_readiness action (chief_of_staff)

Readiness is computed, never stored — it derives from live business
state (booking enabled, Stripe connected, site slug) + offering fields,
so it can't drift.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import sb_clients

RAILWAY_BASE = "https://kmj-intake-server-production.up.railway.app"

SELLABLE = {"product", "course", "package"}
BOOKABLE = {"service", "session"}

# behavior: drives which checks run. surfaces: where a READY offering is
# customer-visible. hints: UI affordances (which field groups to show).
CATEGORY_PROFILES: Dict[str, Dict[str, Any]] = {
    "service": {"behavior": "bookable", "label": "Bookable service",
                "fields": ("duration", "price")},
    "session": {"behavior": "bookable", "label": "Bookable session",
                "fields": ("duration", "price")},
    "product": {"behavior": "sellable", "label": "Store product",
                "fields": ("price", "image", "stock", "shipping", "fulfillment")},
    "course":  {"behavior": "sellable", "label": "Course (sold in store)",
                "fields": ("price", "image", "fulfillment")},
    "package": {"behavior": "sellable", "label": "Package (sold in store)",
                "fields": ("price", "image", "fulfillment")},
    "event":   {"behavior": "none", "label": "Event",
                "fields": ("price",),
                "note": "Event registration isn't built yet — events are list-only today."},
    "custom":  {"behavior": "none", "label": "Other", "fields": ("price",)},
}


def business_state(business_id: str) -> Dict[str, Any]:
    """The cross-offering facts readiness depends on. One fetch, reused
    for every offering on the business."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        "&select=settings,stripe_account_id&limit=1") or []
    settings = (rows[0].get("settings") if rows else {}) or {}
    stripe_connected = bool(rows[0].get("stripe_account_id")) if rows else False
    # Booking detection fix (2026-07-10): readiness chips read the real
    # system (published booking module), not just the legacy flag.
    from booking_widget_router import booking_is_live
    booking_enabled = booking_is_live(business_id, settings)

    sites = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}&select=slug&limit=1") or []
    slug = (sites[0].get("slug") if sites else "") or ""

    # One-calendar pass (2026-07-10): canonical hosted booking URL
    # (subdomain /book), not the legacy Railway path.
    booking_url = ""
    if slug:
        try:
            from business_sites_helpers import booking_url_for_site
            booking_url = booking_url_for_site(sites[0])
        except Exception:
            booking_url = f"{RAILWAY_BASE}/public/booking/{slug}"
    return {
        "booking_enabled": booking_enabled,
        "stripe_connected": stripe_connected,
        "site_slug": slug,
        "booking_url": booking_url,
        "store_url": f"{RAILWAY_BASE}/public/store/{slug}/page" if slug else "",
    }


def offering_readiness(o: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """One offering + business state → {behavior, ready, issues, surfaces}.

    issues: [{code, msg, fix}] where fix is a frontend nav hint the UI
    turns into a one-click jump:
      {"nav": "operate:payments"} | {"nav": "build", "page": "booking"}
      | {"field": "<name>"} (fix lives on the offering itself).
    """
    cat = (o.get("category") or "custom").strip().lower()
    profile = CATEGORY_PROFILES.get(cat, CATEGORY_PROFILES["custom"])
    behavior = profile["behavior"]
    price = o.get("current_price")
    has_price = price is not None and float(price or 0) > 0

    issues: List[Dict[str, Any]] = []
    surfaces: List[Dict[str, str]] = []

    if behavior == "bookable":
        if not o.get("duration_min"):
            issues.append({"code": "no_duration",
                           "msg": "No duration — booking slots need one",
                           "fix": {"field": "duration_min"}})
        if not state["booking_enabled"]:
            issues.append({"code": "booking_off",
                           "msg": "Booking page is off — customers can't book this",
                           "fix": {"nav": "build", "page": "booking"}})
        elif state["booking_url"]:
            surfaces.append({"kind": "booking", "url": state["booking_url"]})
        if not state["site_slug"]:
            issues.append({"code": "no_site",
                           "msg": "No published site — the booking page needs an address",
                           "fix": {"nav": "build", "page": "my-site"}})

    elif behavior == "sellable":
        if not has_price:
            issues.append({"code": "no_price",
                           "msg": "No price — store items need one",
                           "fix": {"field": "current_price"}})
        if not state["site_slug"]:
            issues.append({"code": "no_site",
                           "msg": "No published site — the store lives at your site address",
                           "fix": {"nav": "build", "page": "my-site"}})
        if not state["stripe_connected"]:
            issues.append({"code": "stripe_off",
                           "msg": "Stripe not connected — checkout will refuse",
                           "fix": {"nav": "operate:payments"}})
        inv = o.get("inventory_qty")
        if inv is not None and int(inv) <= 0:
            issues.append({"code": "out_of_stock",
                           "msg": "Out of stock — shown as sold out",
                           "fix": {"field": "inventory_qty"}})
        if has_price and state["site_slug"]:
            surfaces.append({"kind": "store", "url": state["store_url"]})

    note = profile.get("note")

    return {
        "id": o.get("id"),
        "category": cat,
        "behavior": behavior,
        "behavior_label": profile["label"],
        "ready": not issues,
        "issues": issues,
        "surfaces": surfaces,
        **({"note": note} if note else {}),
    }


def business_readiness(business_id: str,
                       offerings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Full readiness report for a business. Fetches active offerings
    when not supplied (callers that already hold rows pass them in)."""
    state = business_state(business_id)
    if offerings is None:
        offerings = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
            "&select=id,name,category,current_price,duration_min,inventory_qty"
            "&order=name.asc&limit=200") or []
    per = [dict(offering_readiness(o, state), name=o.get("name")) for o in offerings]
    return {
        "business": state,
        "offerings": per,
        "summary": {
            "total": len(per),
            "ready": sum(1 for r in per if r["ready"]),
            "bookable_ready": sum(1 for r in per if r["behavior"] == "bookable" and r["ready"]),
            "sellable_ready": sum(1 for r in per if r["behavior"] == "sellable" and r["ready"]),
        },
    }
