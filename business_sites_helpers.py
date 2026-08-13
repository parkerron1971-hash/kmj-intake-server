"""
business_sites_helpers.py — Phase D.2.1 backend.

Shared helpers for the business_sites row that backs every business's
subdomain identity:
  - slug derivation from business name (kebab-case, lowercase,
    alphanumeric + hyphens)
  - collision resolution via numeric suffix
  - ensure_business_site: lazy-creates a booking_only row when a
    business doesn't yet have one (used by booking_page_router, the
    backfill migration, and the /book subdomain route)

Per D.2 audit E6 ruling + Kevin's ACK: slug lives on
business_sites.slug (not businesses.slug). status='booking_only' marks
rows created solely to host the booking page; status='published' marks
MySite-generated sites with html_content. Both share the slug column
which gates subdomain routing (extract_slug_from_host).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

import sb_clients

logger = logging.getLogger("business_sites_helpers")


# Per D.2 audit E2 — hosted booking pages live on the existing
# mysolutionist.app subdomain infrastructure.
PUBLIC_DOMAIN = "mysolutionist.app"

# Status tokens stored on business_sites.status.
STATUS_BOOKING_ONLY = "booking_only"


# Slug derivation: kebab-case alphanumeric only, no leading/trailing
# hyphens, no consecutive hyphens, lowercase.
# Apostrophes are *removed* (not hyphenized) so "kay's" → "kays" rather
# than "kay-s" — matches Rails-style parameterize + reads as one word.
_SLUG_DROP_CHARS = re.compile(r"['‘’ʼ]+")
_SLUG_BAD_CHARS = re.compile(r"[^a-z0-9]+")
_SLUG_MULTI_DASH = re.compile(r"-{2,}")


def derive_slug_from_name(name: Optional[str]) -> str:
    """Convert a business name to a URL-safe slug.

    Examples:
      "Royal Barbers"            → "royal-barbers"
      "KMJ Creative Solutions"   → "kmj-creative-solutions"
      "KMJ Creative  Solutions"  → "kmj-creative-solutions" (double-space normalized)
      "kay's creative fashion"   → "kays-creative-fashion"
      ""                          → "business" (defensive fallback)
    """
    base = (name or "").lower().strip()
    base = _SLUG_DROP_CHARS.sub("", base)
    base = _SLUG_BAD_CHARS.sub("-", base)
    base = _SLUG_MULTI_DASH.sub("-", base)
    base = base.strip("-")
    return base or "business"


def slug_exists(slug: str) -> bool:
    """True when any business_sites row already uses this slug."""
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?slug=eq.{slug}&select=id&limit=1"
    ) or []
    return bool(rows)


def resolve_slug_collision(desired: str) -> str:
    """Return a slug not currently in use. If `desired` is free, return
    it unchanged. Otherwise append `-2`, `-3`, ... until a free slug is
    found. Caps at 1000 attempts as a defensive guard."""
    if not slug_exists(desired):
        return desired
    for i in range(2, 1001):
        candidate = f"{desired}-{i}"
        if not slug_exists(candidate):
            return candidate
    raise RuntimeError(
        f"could not find a free slug for {desired!r} after 1000 attempts"
    )


def get_business_site(business_id: str) -> Optional[Dict[str, Any]]:
    """Return the business_sites row for this business, or None."""
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}&limit=1&select=*"
    ) or []
    return rows[0] if rows else None


def ensure_business_site(
    business: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Lazy-create a booking_only business_sites row for a business
    that doesn't yet have one. Idempotent: if a row already exists,
    return it unchanged.

    Returns: (business_sites row, created_now bool)

    Used by:
      - booking_page_router GET/PATCH endpoints (so practitioners
        without a MySite still have a slug)
      - the /book subdomain route (defensive lazy-create on first hit)
      - the backfill migration script
    """
    existing = get_business_site(business["id"])
    if existing:
        return existing, False

    name = business.get("name") or business.get("id", "")[:8]
    desired = derive_slug_from_name(name)
    slug = resolve_slug_collision(desired)

    payload = {
        "business_id": business["id"],
        "slug": slug,
        "status": STATUS_BOOKING_ONLY,
        "html_content": None,
        "site_config": {},
        "hero_composer_module": None,
    }
    created = sb_clients.sb_post_as_service("/business_sites", payload)
    if not (isinstance(created, list) and created):
        # If the POST silently failed (RLS, race, etc.) re-read so
        # callers see the canonical row OR a deterministic error.
        existing = get_business_site(business["id"])
        if existing:
            return existing, False
        raise RuntimeError(
            f"failed to create business_sites row for biz={business['id']}"
        )
    logger.info(
        f"created booking_only business_sites row for biz={business['id']!s} "
        f"slug={slug!r}"
    )
    return created[0], True


def booking_url_for_site(site: Dict[str, Any]) -> str:
    """Return the canonical booking URL for a given business_sites row:

        https://<custom domain>/book        — when one is connected
        https://<slug>.<PUBLIC_DOMAIN>/book — otherwise

    2026-08-13 (post-audit gap list): this hardcoded the platform
    subdomain, so every surface that shares a booking link — the Embed
    tab's copy button, the QR code, email templates, readiness — handed
    out a mysolutionist.app address to a practitioner who had connected
    and paid for their own domain. The backend has served /book on
    custom domains since 2026-08-02; only the URL builder never caught up.

    Callers rendering a link INTO the site's own HTML should use the
    root-relative "/book" instead, so the stored page stays correct on
    whichever host serves it.
    """
    slug = site.get("slug") or "business"
    cfg = site.get("site_config") if isinstance(site.get("site_config"), dict) else {}
    custom = str((cfg or {}).get("custom_domain") or "").strip().lower().lstrip("/")
    if custom:
        return f"https://{custom}/book"
    return f"https://{slug}.{PUBLIC_DOMAIN}/book"


def booking_url_for_business(business_id: str) -> Optional[str]:
    """Resolve a business_id to its public booking URL. Lazy-creates the
    business_sites row if missing. Returns None when the business
    itself can't be located."""
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name&limit=1"
    ) or []
    if not biz_rows:
        return None
    site, _ = ensure_business_site(biz_rows[0])
    return booking_url_for_site(site)
