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
        # Path C Phase 1e — fallback chain:
        #   businesses.type           (primary; the CHECK/FK-bound column)
        #   business_profiles.business_type  (fallback; profile-side answer)
        #   passed-in business_type   (last; only honored if both empty)
        #
        # Reason: the CTS arc surfaced businesses where businesses.type
        # was clamped to 'custom' by the old constraint while
        # business_profiles.business_type held the real vertical answer
        # ('lawyer'). Reading businesses.type alone produced generic
        # output; reading profile-side alone could miss recent edits
        # via BusinessSettings. Chain picks the more specific signal.
        biz_rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=id,type&limit=1"
        ) or []
        biz_type = biz_rows[0].get("type") if biz_rows else None
        prof_rows = sb_clients.sb_get_as_service(
            f"/business_profiles?business_id=eq.{business_id}"
            f"&select=business_type,terminology_overrides,vertical_intelligence_overrides&limit=1"
        ) or []
        profile_type = prof_rows[0].get("business_type") if prof_rows else None
        if prof_rows:
            overrides_terms = prof_rows[0].get("terminology_overrides") or {}
            overrides_vi = prof_rows[0].get("vertical_intelligence_overrides") or {}
        # Fallback selection. Treat null / empty / 'custom' on
        # businesses.type as "not specific enough" — fall through.
        biz_type_norm = (biz_type or "").strip().lower()
        if biz_type_norm and biz_type_norm != "custom":
            business_type = biz_type
        elif profile_type and (profile_type or "").strip().lower() != "custom":
            business_type = profile_type
        elif not business_type:
            business_type = biz_type or profile_type

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
        # Path C Phase 1e — surface which value won the fallback chain
        # so the frontend can render diagnostic data attributes / log
        # the resolution. Equals 'business_type' but explicit + safer
        # for callers that want the unresolved input separately.
        "resolved_business_type": bt or None,
        "business_id": business_id,
        "is_known": bt in set(list_known_verticals()),
        "voice": profile.get("voice"),
        "onboarding_questions": onboarding_questions,
        "offering_suggestions": offering_suggestions,
        "invoice_line_templates": invoice_line_templates,
        "empty_state_nudges": empty_state_nudges,
        "module_suggestions": module_suggestions,
        "effective_terms": effective_terms,
        # The practitioner's OWN term customisations, unmerged.
        #
        # effective_terms is BASE -> vertical -> overrides already
        # flattened, so a caller needing the override slice back has to
        # subtract a baseline — and that subtraction is only correct if
        # they baseline against the SAME vertical merged here. When they
        # don't, every term of this vertical looks customised, and since
        # overrides apply last they win: one disagreement replaces the
        # entire dictionary. That shipped (frontend FE#400) and told a
        # church it had "Clients" instead of "Members", for a business
        # with no overrides at all.
        #
        # This is the same dict merged above, so no caller has to guess
        # again. `has_business_overrides` stays for compatibility but is
        # deliberately coarser — true when EITHER terms or
        # vertical-intelligence overrides exist, so it cannot answer
        # "are any TERMS customised" on its own.
        "terminology_overrides": overrides_terms or {},
        "has_business_overrides": bool(overrides_terms or overrides_vi),
    }


@router.get("/vertical/list")
def list_verticals() -> Dict[str, Any]:
    """Known verticals — useful for admin / debug surfaces."""
    return {"ok": True, "verticals": list_known_verticals()}
