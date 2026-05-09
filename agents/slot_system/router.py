"""Pass 4.0b.5 — Slot system FastAPI router.

Mounts under `/slots`. Pass 4.0b.5 PART 2 ships:

  GET  /slots/_diag/unsplash    — diagnostic: raw Unsplash query result.
                                  Used to verify integration without
                                  routing through the full build flow.
                                  Stays in the codebase as a debug
                                  surface; no auth required (returns
                                  no PII, just public Unsplash data).

PART 5 will add the user-facing endpoints:
  GET  /slots/{business_id}                       — full slot manifest
  POST /slots/{business_id}/{slot_name}/upload    — practitioner upload
  POST /slots/{business_id}/{slot_name}/clear     — revert to default
  POST /slots/{business_id}/{slot_name}/reroll    — re-query default

Registration order: BEFORE `public_site_router` in
`kmj_intake_automation.py`, alongside the other agent routers.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

from agents.slot_system.unsplash_client import (
    build_unsplash_query,
    query_unsplash,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slots", tags=["slots"])


@router.get("/_diag/unsplash")
def diag_unsplash(
    q: str,
    orientation: str = "landscape",
    min_width: int = 1200,
) -> Dict[str, Any]:
    """Diagnostic: live Unsplash query, returns raw query_unsplash output.

    Used by Pass 4.0b.5 PART 2 verification curls. The endpoint is
    intentionally permissive — no auth, no rate limiting, returns the
    full credit dict so we can confirm attribution shape matches
    Unsplash's requirements. Persisting intentionally NOT done here;
    that happens in the build pipeline at PART 4.
    """
    result = query_unsplash(
        query=q,
        orientation=orientation,
        min_width=min_width,
    )
    return {
        "query": q,
        "orientation": orientation,
        "min_width": min_width,
        "result": result,
    }


@router.get("/_diag/build_query")
def diag_build_query(
    slot_name: str,
    business_name: str = "",
    description: str = "",
    inferred_vibe: str = "",
    brand_metaphor: str = "",
    content_archetype: str = "",
    accent_style: str = "",
    sub_strand_id: str = "",
) -> Dict[str, Any]:
    """Diagnostic: show the Unsplash query that build_unsplash_query
    would compose for the given slot + brief. Pure composition, no
    Unsplash call."""
    enriched_brief = {
        "inferred_vibe": inferred_vibe,
        "brand_metaphor": brand_metaphor,
        "content_archetype": content_archetype,
    }
    designer_pick = {
        "accent_style": accent_style,
        "sub_strand_id": sub_strand_id,
    }
    business = {"name": business_name, "elevator_pitch": description}
    composed = build_unsplash_query(
        slot_name=slot_name,
        enriched_brief=enriched_brief,
        designer_pick=designer_pick,
        business=business,
    )
    return {
        "slot_name": slot_name,
        "composed_query": composed,
    }
