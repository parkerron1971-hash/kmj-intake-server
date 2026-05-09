"""Pass 4.0b.5 — Slot system FastAPI router.

Mounts under `/slots`. Pass 4.0b.5 PART 2 + PART 3 ship:

  GET  /slots/_diag/unsplash               — diagnostic: raw Unsplash
                                              query result, no persist.
  GET  /slots/_diag/build_query            — diagnostic: query
                                              composition only.
  POST /slots/_diag/dalle                  — diagnostic: live DALL-E
                                              generate, rehost to
                                              Supabase, persist to
                                              slot. Subject to budget cap.
  GET  /slots/_diag/dalle_spend            — diagnostic: today's spend
                                              + can-generate flag.
  POST /slots/_diag/dalle_spend_simulate   — diagnostic: append synthetic
                                              spend entry for budget-cap
                                              testing.

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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.slot_system.unsplash_client import (
    build_unsplash_query,
    query_unsplash,
)
from agents.slot_system.dalle_client import (
    PER_SITE_DAILY_CAP_USD,
    add_synthetic_spend_for_testing,
    build_dalle_prompt,
    can_dalle_generate,
    dalle_cost,
    generate_dalle_image,
    get_site_dalle_spend_today,
)
from agents.slot_system import slot_storage
from agents.slot_system.slot_definitions import get_slot_definition

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


# ─── PART 3 — DALL-E diagnostic endpoints ──────────────────────────

class DiagDalleRequest(BaseModel):
    business_id: str
    slot_name: str
    quality: str = "hd"
    size: str = "1024x1024"
    style: str = "natural"
    # Optional: override the auto-composed prompt with a custom one
    # (used for ad-hoc verification queries).
    prompt: Optional[str] = None
    # Optional brief context for prompt composition; falls back to
    # build_dalle_prompt defaults if any field is missing.
    inferred_vibe: Optional[str] = None
    brand_metaphor: Optional[str] = None
    content_archetype: Optional[str] = None
    accent_style: Optional[str] = None
    sub_strand_id: Optional[str] = None
    layout_archetype: Optional[str] = None


@router.post("/_diag/dalle")
def diag_dalle_generate(req: DiagDalleRequest):
    """Diagnostic: generate one DALL-E image, rehost to Supabase, log
    spend, persist as the slot's default. Returns the Supabase URL +
    cost. Subject to PER_SITE_DAILY_CAP_USD ($0.50) — a request that
    would breach the cap returns 402 with the current spend.

    Used by PART 3 verification curls (Royal Palace HD generation +
    cost cap rejection test). The endpoint is intentionally permissive
    (no auth) since it requires a valid business_id and is gated by
    the spend cap."""
    enriched_brief = {
        "inferred_vibe": req.inferred_vibe or "",
        "brand_metaphor": req.brand_metaphor or "",
        "content_archetype": req.content_archetype or "",
    }
    designer_pick = {
        "accent_style": req.accent_style or "",
        "sub_strand_id": req.sub_strand_id or "",
        "layout_archetype": req.layout_archetype or "",
    }
    composed_prompt = req.prompt or build_dalle_prompt(
        slot_name=req.slot_name,
        enriched_brief=enriched_brief,
        designer_pick=designer_pick,
    )

    expected = dalle_cost(req.quality, req.size)
    allowed, current = can_dalle_generate(req.business_id, expected)
    if not allowed:
        # 402 Payment Required is the closest semantic; budget-cap
        # rejection is exactly this. PART 5 reroll endpoint will
        # surface this same response shape.
        raise HTTPException(
            status_code=402,
            detail={
                "error": "budget_cap_exceeded",
                "current_spend_today_usd": current,
                "expected_cost_usd": expected,
                "cap_usd": PER_SITE_DAILY_CAP_USD,
                "remaining_usd": round(PER_SITE_DAILY_CAP_USD - current, 4),
            },
        )

    result = generate_dalle_image(
        prompt=composed_prompt,
        business_id=req.business_id,
        slot_name=req.slot_name,
        quality=req.quality,
        size=req.size,
        style=req.style,
    )
    if not result:
        raise HTTPException(
            status_code=502,
            detail="DALL-E generation or rehost failed (see Railway logs)",
        )

    # Persist as the slot's default so /preview surfaces it.
    persisted = slot_storage.set_slot_default(
        business_id=req.business_id,
        slot_name=req.slot_name,
        url=result["url"],
        source="dalle",
        credit=None,
    )

    return {
        "composed_prompt": composed_prompt,
        "result": result,
        "persisted_to_slot": persisted,
        "spend_today_usd_after": get_site_dalle_spend_today(req.business_id),
    }


@router.get("/_diag/dalle_spend")
def diag_dalle_spend(business_id: str) -> Dict[str, Any]:
    """Diagnostic: report current DALL-E spend for a business, plus
    a sample-cost can-generate flag for HD 1024 ($0.08)."""
    current = get_site_dalle_spend_today(business_id)
    sample_cost = dalle_cost("hd", "1024x1024")
    allowed, _ = can_dalle_generate(business_id, sample_cost)
    return {
        "business_id": business_id,
        "spend_today_usd": current,
        "cap_usd": PER_SITE_DAILY_CAP_USD,
        "remaining_usd": round(PER_SITE_DAILY_CAP_USD - current, 4),
        "can_generate_hd_1024": allowed,
        "sample_cost_used_for_check_usd": sample_cost,
    }


class SimulateSpendRequest(BaseModel):
    business_id: str
    cost_usd: float
    note: Optional[str] = "synthetic budget-cap test"


@router.post("/_diag/dalle_spend_simulate")
def diag_simulate_spend(req: SimulateSpendRequest) -> Dict[str, Any]:
    """Diagnostic: append a synthetic spend entry so the budget cap
    can be exercised without burning real DALL-E generations. The
    entry is tagged slot_name=_synthetic_test in the log so it's
    distinguishable from real spend.

    Used in PART 3 verification: pre-load $0.45, then attempt a real
    $0.08 generation, expect 402."""
    ok = add_synthetic_spend_for_testing(
        business_id=req.business_id,
        cost_usd=req.cost_usd,
        note=req.note or "synthetic budget-cap test",
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"no business_sites row for business_id={req.business_id}",
        )
    return {
        "business_id": req.business_id,
        "added_cost_usd": req.cost_usd,
        "spend_today_usd_after": get_site_dalle_spend_today(req.business_id),
    }
