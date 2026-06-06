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

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/vertical")
def get_vertical(business_type: Optional[str] = None) -> Dict[str, Any]:
    profile = get_profile(business_type)
    return {
        "ok": True,
        "business_type": (business_type or "").lower().strip() or "(unset)",
        "is_known": (business_type or "").lower().strip() in set(list_known_verticals()),
        "voice": profile.get("voice"),
        "onboarding_questions": profile.get("onboarding_questions") or [],
        "offering_suggestions": profile.get("offering_suggestions") or [],
        "invoice_line_templates": profile.get("invoice_line_templates") or [],
        "empty_state_nudges": profile.get("empty_state_nudges") or {},
        "module_suggestions": profile.get("module_suggestions") or [],
    }


@router.get("/vertical/list")
def list_verticals() -> Dict[str, Any]:
    """Known verticals — useful for admin / debug surfaces."""
    return {"ok": True, "verticals": list_known_verticals()}
