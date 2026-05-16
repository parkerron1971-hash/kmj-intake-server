"""Composer Agent diagnostic router. Three endpoints:

  POST /composer/_diag/compose_hero { business_id, dry_run }
    Pass 4.0f Phase 3 — runs Composer only, returns the composition
    JSON (variant + treatments + content + reasoning).

  POST /composer/_spike/render_hero/{business_id}
    Pass 4.0f Phase 4 — runs Composer + the four-step render pipeline,
    returns { composition, html, business_id } as JSON. Phase 5
    comparison page will use this when it wants the composition AND
    the rendered HTML in one trip.

  GET /composer/_spike/render_hero_html/{business_id}
    Pass 4.0f Phase 4 — runs Composer + render pipeline, returns the
    standalone HTML5 document directly (text/html). This is the URL
    artifact for CHECKPOINT 4 + Phase 5 browser-side comparison.

NOT WIRED into kmj_intake_automation.py during the spike — testing
happens via the standalone agents/composer/_spike_app.py FastAPI app
(spike-only mounting, never merges to main). The /_diag endpoint
exists for forward compatibility with the Pass 4.0g production wiring.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agents.composer.cathedral_hero_composer import compose_cathedral_hero

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/composer", tags=["composer"])


# ─── Phase 3 diagnostic endpoint ───────────────────────────────────

class DiagComposeRequest(BaseModel):
    business_id: str
    dry_run: bool = True  # spike default — no render layer until Phase 4


@router.post("/_diag/compose_hero")
def diag_compose_hero(req: DiagComposeRequest) -> Dict[str, Any]:
    """Run the Cathedral Hero Composer for a business. Returns the
    composition JSON (variant + treatments + content + reasoning).

    Phase 3-era endpoint: dry_run honored as 'no-op'. Phase 4's
    /_spike/render_hero is the live render path."""
    composition = compose_cathedral_hero(req.business_id)
    return composition


# ─── Phase 4 spike render endpoints ────────────────────────────────

@router.post("/_spike/render_hero/{business_id}")
def spike_render_hero(business_id: str) -> Dict[str, Any]:
    """Compose + render. Returns {composition, html, business_id}.

    The html is the standalone HTML5 doc (same content as the GET
    endpoint below). JSON envelope so Phase 5's comparison page can
    fetch composition metadata + rendered output in one round-trip.
    """
    from agents.composer.render_pipeline import compose_and_render
    return compose_and_render(business_id, standalone=True)


@router.get("/_spike/render_hero_html/{business_id}", response_class=HTMLResponse)
def spike_render_hero_html(business_id: str) -> HTMLResponse:
    """Browser-viewable spike endpoint. Fires Composer + renders, then
    serves the standalone HTML5 document directly as text/html.

    Phase 4 CHECKPOINT 4 verification: open this URL in a browser for
    each of the three spike businesses to confirm composition +
    rendering produce live, themed, brand-correct hero sections.

    Cache-Control: no-store so repeated visits trigger fresh Composer
    calls (cost-aware — spike review iterates quickly)."""
    from agents.composer.render_pipeline import compose_and_render
    result = compose_and_render(business_id, standalone=True)
    return HTMLResponse(
        content=result["html"],
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
