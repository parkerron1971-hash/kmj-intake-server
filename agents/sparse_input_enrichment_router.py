"""Pass 4.0a — Sparse-Input Enrichment FastAPI router.

Mounts under `/enrichment`. The Designer Agent (Pass 4.0b) will call
`POST /enrichment/enrich` BEFORE strand selection so it works with
rich input rather than vague intake. In Pass 4.0a no caller invokes
the endpoint yet — it's stood up so the contract is in place.

Registration order: this router MUST be registered BEFORE
`public_site_router` in `kmj_intake_automation.py`. `public_site_router`
defines `/` and `/{path:path}` catch-alls and stays LAST.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.sparse_input_enrichment import enrich_intake

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enrichment", tags=["enrichment"])


class EnrichmentRequest(BaseModel):
    business_name: str
    description: Optional[str] = None
    colors: Optional[List[str]] = None
    practitioner_voice: Optional[str] = None
    strategy_track_summary: Optional[str] = None


@router.post("/enrich")
def enrich(req: EnrichmentRequest):
    """Enrich a sparse practitioner intake. Returns:

        {"enriched": { ... seven canonical keys ... }}

    `enrich_intake` soft-fails on missing API key / LLM error / parse
    error, so this endpoint typically returns 200 with `_enrichment_error`
    populated rather than raising. The 500 path here only fires for
    catastrophic exceptions — defense in depth.
    """
    try:
        enriched = enrich_intake(
            business_name=req.business_name,
            description=req.description,
            colors=req.colors,
            practitioner_voice=req.practitioner_voice,
            strategy_track_summary=req.strategy_track_summary,
        )
        return {"enriched": enriched}
    except Exception as e:
        logger.warning(f"[enrichment] handler crashed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
def health():
    """Sanity probe — does NOT call Anthropic. Verifies the router is
    mounted and reports whether ANTHROPIC_API_KEY is set so callers
    can debug 'why is enrichment falling back?' without burning a
    Sonnet call to find out."""
    import os
    return {
        "status": "ok",
        "anthropic_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }
