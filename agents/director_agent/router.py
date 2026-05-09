"""Pass 4.0b — Director Agent FastAPI router.

Mounts under `/director`. Pass 4.0b ships:
  POST /director/critique          — punch list against a Module rubric
  POST /director/build-with-loop   — full enrichment → designer → brief
                                       expander → builder → critique →
                                       (conditional) regenerate, with a
                                       structured audit trail

Registration order: BEFORE `public_site_router` in
`kmj_intake_automation.py`. `public_site_router` stays LAST.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.director_agent.critique import critique_site
from agents.director_agent.build_with_loop import run_build_loop

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
