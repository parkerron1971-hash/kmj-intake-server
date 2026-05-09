"""Pass 4.0b — Director Agent FastAPI router.

Mounts under `/director`. Pass 4.0b ships:
  POST /director/critique          — punch list against a Module rubric

Pass 4.0b PART 4 will add:
  POST /director/build-with-loop   — full enrichment → designer → builder
                                       → critique → regenerate orchestration

Registration order: BEFORE `public_site_router` in
`kmj_intake_automation.py`. `public_site_router` stays LAST.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.director_agent.critique import critique_site

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/director", tags=["director"])


class CritiqueRequest(BaseModel):
    module_id: str
    html: str
    css: Optional[str] = ""
    enriched_brief: Optional[Dict] = None


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
