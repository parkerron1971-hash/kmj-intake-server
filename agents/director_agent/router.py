"""Pass 4.0b — Director Agent FastAPI router.

Mounts under `/director`. Pass 4.0b ships:
  POST /director/critique          — punch list against a Module rubric
  POST /director/build-with-loop   — full enrichment → designer → brief
                                       expander → builder → critique →
                                       (conditional) regenerate, with a
                                       structured audit trail

Pass 4.0c PART 2 adds:
  POST /director/_diag/enrich_feedback  — diagnostic: enrich one feedback
                                           string into expanded moves.
                                           No persistence, no Builder call.

Registration order: BEFORE `public_site_router` in
`kmj_intake_automation.py`. `public_site_router` stays LAST.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.director_agent.critique import critique_site
from agents.director_agent.build_with_loop import run_build_loop
from agents.director_agent.feedback_enrichment import enrich_feedback
from agents.director_agent.refine import (
    delete_chat_history,
    get_chat_history,
    get_diagnose_question,
    run_refine,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/director", tags=["director"])


class CritiqueRequest(BaseModel):
    module_id: str
    html: str
    css: Optional[str] = ""
    enriched_brief: Optional[Dict] = None


class BuildWithLoopRequest(BaseModel):
    business_name: str
    module_id: str
    description: Optional[str] = None
    colors: Optional[List[str]] = None
    practitioner_voice: Optional[str] = None
    strategy_track_summary: Optional[str] = None
    vocab_id: str = "sovereign-authority"
    max_attempts: int = 2
    include_html: bool = True
    # Pass 4.0b.4: when supplied, the orchestrator persists final_html
    # to business_sites.site_config.generated_html for that row, making
    # the build viewable at /sites/{business_id}/preview without any
    # frontend changes. Optional — omit for ephemeral verification runs.
    business_id: Optional[str] = None


@router.get("/health")
def health():
    """Sanity probe — confirms the router is mounted and reports which
    rubrics are available on disk."""
    import os

    try:
        from agents.design_intelligence.rubrics import list_rubrics
        rubrics = list_rubrics()
    except Exception as e:
        logger.warning(f"[director] list_rubrics failed: {e}")
        rubrics = []

    return {
        "status": "ok",
        "anthropic_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "rubrics_available": rubrics,
    }


@router.post("/critique")
def critique(req: CritiqueRequest):
    """Score generated HTML against a Design Intelligence Module rubric.

    Returns the punch-list shape from `critique_site`. The endpoint
    soft-fails to a 200 with `summary.verdict = "skipped"` when the
    module has no rubric — that's a normal state for modules that
    haven't been authored yet, not an error. The 500 path here only
    fires for catastrophic exceptions inside the checkers.
    """
    try:
        return critique_site(
            module_id=req.module_id,
            html=req.html,
            css=req.css or "",
            enriched_brief=req.enriched_brief,
        )
    except Exception as e:
        logger.warning(f"[director.critique] handler crashed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/build-with-loop")
def build_with_loop(req: BuildWithLoopRequest):
    """Run the full Director build-with-loop pipeline (Pass 4.0b PART 4).

    Orchestrates: enrichment → designer → brief expander → builder v1 →
    critique v1 → (if HIGH violations) builder v2 + critique v2. Returns
    a structured audit trail with each step's elapsed time, full result,
    and CTA extraction from rendered HTML so callers can verify whether
    enrichment + punch-list are shaping creative output.

    Cost: 4–7 Claude calls per request (enrichment + designer + brief
    expander + builder ×1-2 + critique ×1-2). Latency 60–240s. Caller
    can pass include_html=false to drop the final HTML from the response
    payload (audit trail still includes html_length + CTA extraction).
    """
    try:
        return run_build_loop(
            business_name=req.business_name,
            module_id=req.module_id,
            description=req.description,
            colors=req.colors,
            practitioner_voice=req.practitioner_voice,
            strategy_track_summary=req.strategy_track_summary,
            vocab_id=req.vocab_id,
            max_attempts=req.max_attempts,
            include_html=req.include_html,
            business_id=req.business_id,
        )
    except Exception as e:
        logger.warning(
            f"[director.build-with-loop] handler crashed: {type(e).__name__}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))


# ─── Pass 4.0c PART 2 — Feedback enrichment diagnostic ─────────────

class EnrichFeedbackDiagRequest(BaseModel):
    user_text: str
    module_id: str = "cinematic_authority"
    enriched_brief: Optional[Dict[str, Any]] = None
    design_pick: Optional[Dict[str, Any]] = None


@router.post("/_diag/enrich_feedback")
def diag_enrich_feedback(req: EnrichFeedbackDiagRequest) -> Dict[str, Any]:
    """Diagnostic: run feedback_enrichment.enrich_feedback against the
    given inputs. No persistence, no Builder call. Used by Pass 4.0c
    PART 2 verification curls so we can see the expanded_moves shape
    before wiring the production /director/refine endpoint in PART 3.
    """
    return enrich_feedback(
        user_text=req.user_text,
        module_id=req.module_id,
        enriched_brief=req.enriched_brief,
        design_pick=req.design_pick,
    )


# ─── Pass 4.0c PART 3 — Refine + diagnose + chat history ────────────

class RefineRequest(BaseModel):
    business_id: str
    user_text: str
    quality: Optional[str] = "hd"


@router.post("/refine")
def refine(req: RefineRequest) -> Dict[str, Any]:
    """Run the Director refine flow.

    Insert user message → enrich feedback → insert system message →
    either trigger a slot reroll (estimated_regenerate_needed=False)
    or call build_with_loop with the enriched moves as the initial
    punch list.

    Synchronous: the slow path (Builder regenerate) blocks for 3-5
    minutes. Frontend polls /director/chat-history while inFlight to
    detect completion via build_status='completed' on the system
    message — the chat row is the source of truth even if this HTTP
    request times out at the proxy layer.

    409 Conflict when an in-flight build for this business exists
    within the last 10 minutes (prevents double-spend on parallel
    refine requests).
    """
    result = run_refine(
        business_id=req.business_id,
        user_text=req.user_text,
        quality=req.quality or "hd",
    )
    if result.get("status") == "in_flight":
        raise HTTPException(status_code=409, detail=result)
    if result.get("status") == "no_business_state":
        raise HTTPException(status_code=404, detail=result)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result)
    return result


@router.post("/diagnose")
def diagnose() -> Dict[str, Any]:
    """Return the multi-select diagnose question. Pass 4.0c v1: fixed
    6 options. Future passes can make it module-aware."""
    return get_diagnose_question()


@router.get("/chat-history/{business_id}")
def chat_history(business_id: str) -> Dict[str, Any]:
    """Return all chat messages for a business, ordered by created_at
    ascending. Used by the frontend dock for both initial hydration
    and polling-to-detect-completion."""
    return {
        "business_id": business_id,
        "messages": get_chat_history(business_id),
    }


@router.delete("/chat-history/{business_id}")
def chat_history_delete(business_id: str) -> Dict[str, Any]:
    """Wipe all chat history for a business. Used by the 'start fresh'
    UX path in the frontend dock."""
    ok = delete_chat_history(business_id)
    return {"success": ok, "business_id": business_id}


@router.get("/_diag/site_state/{business_id}")
def diag_site_state(business_id: str) -> Dict[str, Any]:
    """Diagnostic: report the presence of the four Pass 4.0c persistence
    keys on a business's site_config. Mirrors the pre-PART-4 seed
    verification SQL — equivalent of:

      SELECT site_config ? 'build_inputs' AS has_build_inputs, ...

    Returns presence flags + sample values for the keys that should
    confirm Royal Palace identity made it into the persisted state."""
    from brand_engine import _sb_get as be_get
    rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
    ) or []
    if not rows:
        return {
            "business_id": business_id,
            "found": False,
            "error": "no business_sites row",
        }
    cfg = rows[0].get("site_config") or {}
    bi = cfg.get("build_inputs") or {}
    eb = cfg.get("enriched_brief") or {}
    dr = cfg.get("design_recommendation") or {}
    gh = cfg.get("generated_html") or ""
    return {
        "business_id": business_id,
        "found": True,
        "has_build_inputs": bool(cfg.get("build_inputs")),
        "has_enriched_brief": bool(cfg.get("enriched_brief")),
        "has_design_recommendation": bool(cfg.get("design_recommendation")),
        "has_generated_html": bool(gh),
        "html_length": len(gh) if isinstance(gh, str) else 0,
        "html_generated_at": cfg.get("html_generated_at"),
        "persisted_business_name": bi.get("business_name") if isinstance(bi, dict) else None,
        "persisted_module_id": bi.get("module_id") if isinstance(bi, dict) else None,
        "persisted_brand_metaphor": eb.get("brand_metaphor") if isinstance(eb, dict) else None,
        "persisted_inferred_vibe": eb.get("inferred_vibe") if isinstance(eb, dict) else None,
        "persisted_strand_pair": (
            f"{dr.get('strand_a_id')}/{dr.get('strand_b_id')}"
            if isinstance(dr, dict) else None
        ),
        "persisted_sub_strand_id": dr.get("sub_strand_id") if isinstance(dr, dict) else None,
    }
