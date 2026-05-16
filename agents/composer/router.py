"""Composer Agent diagnostic router. Five endpoints:

  POST /composer/_diag/compose_hero { business_id, dry_run }
    Pass 4.0f Phase 3 — runs Composer only, returns the composition
    JSON (variant + treatments + content + reasoning).

  POST /composer/_diag/route_module { business_id, dry_run }
    Pass 4.0g Phase D — runs the Module Router only, returns the
    routing decision (module_id + confidence + reasoning + optional
    alternative_module). Module Router runs BEFORE the module-specific
    Composer in the full pipeline.

  POST /composer/_spike/render_hero/{business_id}
    Pass 4.0f Phase 4 — runs Composer + the four-step render pipeline,
    returns { composition, html, business_id } as JSON. Phase 5
    comparison page uses this when it wants the composition AND
    the rendered HTML in one trip.

  GET /composer/_spike/render_hero_html/{business_id}
    Pass 4.0f Phase 4 — runs Composer + render pipeline, returns the
    standalone HTML5 document directly (text/html). URL artifact for
    CHECKPOINT 4 + Phase 5 browser-side review.

  GET /composer/_spike/comparison_page
    Pass 4.0f Phase 5 — server-side comparison page rendering all
    three spike businesses' Heros side-by-side (vertically stacked
    iframes), each paired with its Composer reasoning text and
    composition metadata. Reviewers judge intent against the visible
    rationale. ~$0.15/visit (3 fresh Composer calls).

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


# ─── Phase D Module Router diagnostic endpoint ──────────────────────

class DiagRouteModuleRequest(BaseModel):
    business_id: str
    dry_run: bool = True  # placeholder for forward-compat — router
                           # doesn't write anything regardless


@router.post("/_diag/route_module")
def diag_route_module(req: DiagRouteModuleRequest) -> Dict[str, Any]:
    """Run the Module Router for a business. Returns the routing
    decision (module_id + confidence + reasoning + alternative_module
    + _route_metadata diagnostic envelope).

    Phase D-era endpoint: dry_run is reserved for forward-compat;
    routing is pure (no DB writes) so dry_run is effectively a no-op
    today. The endpoint is the canonical surface the future composition
    pipeline (Module Router -> Composer -> render) wires through."""
    from agents.composer.module_router import route_module
    return route_module(req.business_id)


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


# ─── Phase 5 spike comparison page ─────────────────────────────────

@router.get("/_spike/comparison_page", response_class=HTMLResponse)
def spike_comparison_page() -> HTMLResponse:
    """Phase 5 — side-by-side comparison page.

    Server-side renders all three spike businesses' Heros + reasoning
    in one document. Each Hero embeds via <iframe srcdoc=...> so the
    Hero markup runs in its own document scope (no CSS bleed between
    Heros or between Hero and the comparison shell). The reasoning
    panel sits adjacent so reviewers can judge variant choice intent
    against the visible explanation.

    Cost-aware: fires Composer once per business (~$0.15/visit).
    Cache-Control: no-store keeps spike output fresh during review."""
    from agents.composer.comparison_page import render_comparison_page_html
    html = render_comparison_page_html()
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
