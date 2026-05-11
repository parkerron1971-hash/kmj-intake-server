"""Pass 4.0d PART 2 — Chief unification FastAPI router.

Mounts under `/chief` (same prefix as override_system from PART 1).

Endpoints:
  POST /chief/message           — classify + dispatch in one round-trip
  POST /chief/_diag/classify    — classifier only, no dispatch (for
                                  test harnesses + debugging)

Registration: BEFORE public_site_router in kmj_intake_automation.py.
(public_site_router has the catch-all and must remain last.)

Owner gating: NONE at this layer (matches the rest of 4.0d).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from agents.chief_executive.dispatcher import compose_response, dispatch
from agents.chief_executive.intent_classifier import classify_intent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chief", tags=["chief_executive"])


class ChiefMessageRequest(BaseModel):
    business_id: str
    user_text: str
    current_view: str = "mysite"
    dry_run: bool = False  # when True, dispatchers don't touch the DB or
                           # call Director — they return what they would have done


class ClassifyDiagRequest(BaseModel):
    user_text: str
    current_view: str = "mysite"


@router.post("/message")
def chief_message(req: ChiefMessageRequest) -> Dict[str, Any]:
    """Single conversational entry point.

    Classify the practitioner's message with Sonnet, dispatch each
    intent to its specialist (content_edit → override system,
    design_refine → Director, etc.), compose a unified reply.

    Returns the composed response shape from
    dispatcher.compose_response (see that docstring for the schema).

    Always returns 200 — failures and clarification requests surface in
    overall_status / per-result status rather than HTTP error codes.
    The frontend renders the same UI for every status and reads
    next_actions to know what to suggest the user do next.
    """
    classification = classify_intent(
        user_text=req.user_text,
        current_view=req.current_view,
    )
    results = dispatch(
        classification=classification,
        business_id=req.business_id,
        dry_run=req.dry_run,
    )
    return compose_response(
        classification=classification,
        results=results,
        user_text=req.user_text,
    )


@router.post("/_diag/classify")
def diag_classify(req: ClassifyDiagRequest) -> Dict[str, Any]:
    """Run only the classifier — no dispatch, no side effects. Used by
    the PART 2 test harness to verify the classifier's accuracy on a
    suite of canonical messages without invoking the specialists."""
    return classify_intent(
        user_text=req.user_text,
        current_view=req.current_view,
    )
