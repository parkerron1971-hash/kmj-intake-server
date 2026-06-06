"""
vertical_intelligence_router.py — Phase VABI v1.

Single public endpoint that returns the vertical-intelligence
subset the frontend needs (onboarding questions, offering
suggestions, invoice line templates, empty-state nudges, module
suggestions) so the frontend doesn't have to keep a full mirror in
sync.

Surface:
  GET /intelligence/vertical?business_type=<key>
      Returns the resolved profile (always — falls back to GENERIC).

No auth required: the data is descriptive, not business-specific.
The same payload is the same for every practitioner of the same
vertical. Future: per-business overrides ride on a separate
authenticated endpoint.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter

from vertical_intelligence import (
    get_profile,
    list_known_verticals,
)
from vertical_terminology import BASE_TERMS, VERTICAL_TERMS
import sb_clients

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/vertical")
def get_vertical(
    business_type: Optional[str] = None,
    business_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Public read endpoint.

    Phase VABI v1.5 — when business_id is passed, applies the per-
    business overrides on top of the vertical defaults so the
    frontend renders the same effective dictionary the practitioner
    sees in Settings → Terminology.
    """
    # Apply business-id resolution → look up the business_type +
    # overrides so the response reflects what the practitioner sees.
    overrides_terms: Dict[str, Any] = {}
    overrides_vi: Dict[str, Any] = {}
    if business_id:
        # Read both business.type AND the override jsonb in one round.
        biz_rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=id,type&limit=1"
        ) or []
        if biz_rows and not business_type:
            business_type = biz_rows[0].get("type")
        prof_rows = sb_clients.sb_get_as_service(
            f"/business_profiles?business_id=eq.{business_id}"
            f"&select=terminology_overrides,vertical_intelligence_overrides&limit=1"
        ) or []
        if prof_rows:
            overrides_terms = prof_rows[0].get("terminology_overrides") or {}
            overrides_vi = prof_rows[0].get("vertical_intelligence_overrides") or {}

    profile = get_profile(business_type)
    bt = (business_type or "").lower().strip()
    vertical_terms = VERTICAL_TERMS.get(bt) or {}
    effective_terms = {**BASE_TERMS, **vertical_terms, **overrides_terms}

    # VI overrides: deep-merge at the top level (per-key). The
    # practitioner replaces whole arrays (offering_suggestions, etc.)
    # if they edit them; partial replacement is supported.
    onboarding_questions = (
        overrides_vi.get("onboarding_questions")
        if overrides_vi.get("onboarding_questions") is not None
        else (profile.get("onboarding_questions") or [])
    )
    offering_suggestions = (
        overrides_vi.get("offering_suggestions")
        if overrides_vi.get("offering_suggestions") is not None
        else (profile.get("offering_suggestions") or [])
    )
    invoice_line_templates = (
        overrides_vi.get("invoice_line_templates")
        if overrides_vi.get("invoice_line_templates") is not None
        else (profile.get("invoice_line_templates") or [])
    )
    empty_state_nudges = {
        **(profile.get("empty_state_nudges") or {}),
        **(overrides_vi.get("empty_state_nudges") or {}),
    }
    module_suggestions = (
        overrides_vi.get("module_suggestions")
        if overrides_vi.get("module_suggestions") is not None
        else (profile.get("module_suggestions") or [])
    )

    return {
        "ok": True,
        "business_type": bt or "(unset)",
        "business_id": business_id,
        "is_known": bt in set(list_known_verticals()),
        "voice": profile.get("voice"),
        "onboarding_questions": onboarding_questions,
        "offering_suggestions": offering_suggestions,
        "invoice_line_templates": invoice_line_templates,
        "empty_state_nudges": empty_state_nudges,
        "module_suggestions": module_suggestions,
        "effective_terms": effective_terms,
        "has_business_overrides": bool(overrides_terms or overrides_vi),
    }


@router.get("/vertical/list")
def list_verticals() -> Dict[str, Any]:
    """Known verticals — useful for admin / debug surfaces."""
    return {"ok": True, "verticals": list_known_verticals()}
