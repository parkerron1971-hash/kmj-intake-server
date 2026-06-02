"""
chief_suggestions_router.py — Phase C.1.3.

Practitioner-facing endpoints for Chief's proactive suggestion lifecycle
(per NT8b–NT8d): proposed → snoozed → dismissed → accepted.

Endpoints:
  GET    /chief-suggestions?business_id=…[&status=…]
         List suggestions for a business. Default: status in
         ('proposed','snoozed') with snoozed_until elapsed.

  POST   /chief-suggestions/{id}/snooze[?days=14]
         Move to status='snoozed' with snoozed_until = now() + days days.

  POST   /chief-suggestions/{id}/dismiss
         Body: {reason?}
         Move to status='dismissed' with dismiss_reason captured.

  POST   /chief-suggestions/{id}/accept
         Routes the suggestion's intake_seed through propose_module_from_intake,
         returning the proposal envelope. The dock renders it via the
         existing ModuleSpecProposalCard. The suggestion row is patched
         status='accepted' + resolved_spec_id once the proposal flow returns.

Owner check mirrors the established pattern (workflow_router,
module_spec_router, offerings_router): business.owner_id == auth.uid().
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_supabase import AuthedUser, require_user
import sb_clients

logger = logging.getLogger("chief_suggestions_router")
router = APIRouter(prefix="/chief-suggestions", tags=["chief-suggestions"])

DEFAULT_SNOOZE_DAYS = 14


def _require_owner(business_id: str, user: AuthedUser) -> None:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


def _owner_for_suggestion(sug_id: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(
        f"/chief_suggestions?id=eq.{sug_id}&select=business_id&limit=1"
    ) or []
    if not rows:
        return None
    biz_id = rows[0].get("business_id")
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}&select=owner_id&limit=1"
    ) or []
    return biz_rows[0].get("owner_id") if biz_rows else None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@router.get("")
def list_suggestions(
    business_id: str = Query(...),
    status: Optional[str] = Query(default=None),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """List suggestions for a business. Without status filter, returns
    'proposed' rows + 'snoozed' rows whose snoozed_until has elapsed
    (effectively re-emerged). Most-recent first."""
    _require_owner(business_id, user)

    if status:
        q = (f"/chief_suggestions?business_id=eq.{business_id}"
             f"&status=eq.{status}&order=created_at.desc&select=*")
        rows = sb_clients.sb_get_as_service(q) or []
        return {"ok": True, "suggestions": rows}

    # No filter — return proposed + re-emerged-snoozed.
    proposed = sb_clients.sb_get_as_service(
        f"/chief_suggestions?business_id=eq.{business_id}"
        f"&status=eq.proposed&order=created_at.desc&select=*"
    ) or []
    snoozed = sb_clients.sb_get_as_service(
        f"/chief_suggestions?business_id=eq.{business_id}"
        f"&status=eq.snoozed&snoozed_until=lt.{_now_iso()}"
        f"&order=created_at.desc&select=*"
    ) or []
    return {"ok": True, "suggestions": proposed + snoozed}


@router.post("/{suggestion_id}/snooze")
def snooze_suggestion(
    suggestion_id: str,
    days: int = Query(default=DEFAULT_SNOOZE_DAYS, ge=1, le=365),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    owner = _owner_for_suggestion(suggestion_id)
    if not owner:
        raise HTTPException(status_code=404, detail="suggestion not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")

    snoozed_until = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = sb_clients.sb_patch_as_service(
        f"/chief_suggestions?id=eq.{suggestion_id}",
        {
            "status": "snoozed",
            "snoozed_until": snoozed_until,
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True, "suggestion": (rows[0] if isinstance(rows, list) and rows else None),
            "snoozed_until": snoozed_until}


class DismissBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/{suggestion_id}/dismiss")
def dismiss_suggestion(
    suggestion_id: str,
    body: DismissBody = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    owner = _owner_for_suggestion(suggestion_id)
    if not owner:
        raise HTTPException(status_code=404, detail="suggestion not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")

    rows = sb_clients.sb_patch_as_service(
        f"/chief_suggestions?id=eq.{suggestion_id}",
        {
            "status": "dismissed",
            "dismiss_reason": (body.reason if body else None) or "",
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True, "suggestion": (rows[0] if isinstance(rows, list) and rows else None)}


@router.post("/{suggestion_id}/accept")
def accept_suggestion(
    suggestion_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Routes the suggestion's intake_seed through the proposal flow.
    Returns the envelope so the dock can render the spec card stack.
    Marks the suggestion accepted with the resolved spec ids."""
    rows = sb_clients.sb_get_as_service(
        f"/chief_suggestions?id=eq.{suggestion_id}&select=*&limit=1"
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="suggestion not found")
    suggestion = rows[0]
    business_id = suggestion["business_id"]

    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1"
    ) or []
    if not biz_rows or str(biz_rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")

    intake = (suggestion.get("intake_seed") or "").strip()
    if not intake:
        raise HTTPException(status_code=400, detail="suggestion has no intake_seed to propose")

    try:
        import module_spec_generator as msg
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"generator unavailable: {e}")

    res = msg.propose_module_from_intake(business_id, intake)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "proposal failed"))

    # Stamp the lineage on the suggestion row so we can analytically trace
    # accept→materialize-rate later. We don't wait for materialize here —
    # the practitioner still has to click Accept on the dock card stack;
    # at that point the suggestion is functionally accepted.
    first_spec_id = None
    for p in res.get("proposals") or []:
        if p.get("kind") == "module" or p.get("kind") is None:
            first_spec_id = p.get("spec_id")
            break

    sb_clients.sb_patch_as_service(
        f"/chief_suggestions?id=eq.{suggestion_id}",
        {
            "status": "accepted",
            "resolved_spec_id": first_spec_id,
            "updated_at": _now_iso(),
        },
    )

    return {
        "ok": True,
        "suggestion_id": suggestion_id,
        "decomposition_reasoning": res.get("decomposition_reasoning"),
        "proposals": res.get("proposals") or [],
    }
