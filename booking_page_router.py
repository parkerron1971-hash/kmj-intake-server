"""
booking_page_router.py — Phase D.2.1 backend.

Practitioner-facing endpoints for the hosted booking page:

  GET   /booking-page/{business_id}        Return current config
                                            (auto-creates the
                                            business_sites row if
                                            missing).
  PATCH /booking-page/{business_id}        Update settings.booking_page
                                            (merge into businesses.settings).
                                            Body: {published?, tagline?,
                                                   footer_text?, slug?}
  GET   /booking-page/{business_id}/url    Resolve the public URL.
                                            Used by EmailTemplates and
                                            the Embed tab.

Owner-gated via the same _require_owner pattern as
availability_router (D.1.2) — mirrors that file's shape exactly so
new code lands familiar.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user
from business_sites_helpers import (
    booking_url_for_site,
    ensure_business_site,
    resolve_slug_collision,
    slug_exists,
    derive_slug_from_name,
)

logger = logging.getLogger("booking_page_router")

router = APIRouter(prefix="/booking-page", tags=["booking-page"])


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner gate — same shape as availability_router._require_owner /
    offerings_router._require_owner. Returns the business row so
    callers can reuse it without a second lookup."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id,settings&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    return rows[0]


def _booking_page_dict(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Read settings.booking_page sub-dict; tolerate missing/malformed."""
    raw = settings.get("booking_page") or {}
    return raw if isinstance(raw, dict) else {}


@router.get("/{business_id}")
def get_booking_page(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Return the current booking_page config + the canonical URL +
    a flag indicating whether the underlying business_sites row was
    just lazy-created.

    Auto-creates the business_sites row (status='booking_only',
    html_content=NULL) if missing, so the practitioner always has a
    canonical URL to share even before they publish the page."""
    business = _require_owner(business_id, user)
    site, created = ensure_business_site(business)
    settings = business.get("settings") or {}
    page = _booking_page_dict(settings)
    return {
        "ok": True,
        "business_id": business_id,
        "slug": site.get("slug"),
        "site_status": site.get("status"),
        "site_has_html": bool(site.get("html_content")),
        "url": booking_url_for_site(site),
        "booking_page": {
            "published": bool(page.get("published")),
            "tagline": page.get("tagline"),
            "footer_text": page.get("footer_text"),
        },
        "site_row_created_now": created,
    }


@router.patch("/{business_id}")
def patch_booking_page(
    business_id: str,
    body: Dict[str, Any],
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Update settings.booking_page (and optionally the slug on the
    business_sites row). Owner-gated.

    Body fields (all optional; only present keys are touched):
      published    bool    flip the publish toggle
      tagline      str     header tagline above the widget
      footer_text  str     custom footer text (overrides the default
                           "Powered by Solutionist" attribution)
      slug         str     rename the URL slug; validated +
                           collision-resolved on the server
    """
    business = _require_owner(business_id, user)
    site, _created = ensure_business_site(business)
    settings = dict(business.get("settings") or {})
    page = dict(_booking_page_dict(settings))

    # Optional booking_page fields
    if "published" in body:
        page["published"] = bool(body["published"])
    if "tagline" in body:
        page["tagline"] = (body.get("tagline") or "").strip() or None
    if "footer_text" in body:
        page["footer_text"] = (body.get("footer_text") or "").strip() or None
    settings["booking_page"] = page

    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings},
    )

    # Optional slug rename — on the business_sites row, not settings.
    slug_changed = False
    if "slug" in body:
        desired_raw = (body.get("slug") or "").strip()
        if not desired_raw:
            raise HTTPException(400, "slug cannot be empty")
        desired = derive_slug_from_name(desired_raw)
        if not desired:
            raise HTTPException(
                400,
                "slug must contain at least one letter or number",
            )
        if desired != site.get("slug"):
            if slug_exists(desired):
                # If the practitioner asks for a slug already taken by
                # someone else, refuse rather than silently appending a
                # suffix (their input is explicit; respect it).
                raise HTTPException(
                    409,
                    f"slug {desired!r} is already taken — try another name",
                )
            sb_clients.sb_patch_as_service(
                f"/business_sites?id=eq.{site['id']}",
                {"slug": desired},
            )
            site["slug"] = desired
            slug_changed = True

    return {
        "ok": True,
        "business_id": business_id,
        "slug": site.get("slug"),
        "slug_changed": slug_changed,
        "url": booking_url_for_site(site),
        "booking_page": page,
    }


@router.get("/{business_id}/url")
def get_booking_url(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Resolve the canonical hosted booking URL. Auto-creates the
    business_sites row if missing. Used by EmailTemplates.tsx (the
    {booking_url} template substitution) and the Embed tab."""
    business = _require_owner(business_id, user)
    site, _ = ensure_business_site(business)
    return {
        "ok": True,
        "business_id": business_id,
        "url": booking_url_for_site(site),
        "slug": site.get("slug"),
    }
