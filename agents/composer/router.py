"""Composer Agent diagnostic router. Single endpoint:

  POST /composer/_diag/compose_hero { business_id, dry_run }

dry_run=true skips the (yet-to-be-built Phase 4) render layer and
returns the Composer's JSON output verbatim. Same pattern as
/chief/_diag/classify (Pass 4.0d PART 2).

NOT WIRED into kmj_intake_automation.py during the spike — Phase 3
testing happens via direct Python invocation. Phase 5 will wire this
when the comparison page needs the endpoint live.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from agents.composer.cathedral_hero_composer import compose_cathedral_hero

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/composer", tags=["composer"])


class DiagComposeRequest(BaseModel):
    business_id: str
    dry_run: bool = True  # spike default — no render layer until Phase 4


@router.post("/_diag/compose_hero")
def diag_compose_hero(req: DiagComposeRequest) -> Dict[str, Any]:
    """Run the Cathedral Hero Composer for a business. Returns the
    composition JSON (variant + treatments + content + reasoning).

    Spike: dry_run is honored as 'no-op' since the render endpoint
    doesn't exist until Phase 4. The flag is reserved for forward
    compatibility — Phase 4's /spike/render_hero will respect it."""
    composition = compose_cathedral_hero(req.business_id)
    return composition
