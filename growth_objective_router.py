"""
growth_objective_router.py — LGS Phase 4/5 practitioner surface for Growth
Objectives + the Growth Timeline (item 12).

Owner-checked endpoints (business.owner_id == auth.uid; same gate as
restricted_modules / workflow_router):
  GET  /growth-objectives/{business_id}            — list objectives
  POST /growth-objectives/{business_id}            — create + spawn (the agent)
  GET  /growth-objectives/{business_id}/timeline   — the rendered Timeline view

The Timeline is NOT a separate data model (Fork 26): it's the assembled view of
growth_objectives + growth_milestones + linked workflow_runs. Milestones are
rendered polymorphically (each row carries title/status/source/due_date +
optional linked_workflow_run_id), so the same renderer handles future
non-objective milestone sources without schema change.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth_supabase import AuthedUser, require_user
import growth_objective_agent

logger = logging.getLogger("growth_objective_router")
router = APIRouter(prefix="/growth-objectives", tags=["growth-objectives"])

_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)


def _service_headers() -> Dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _sb_get(path: str) -> Any:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.get(f"{url}/rest/v1{path}", headers=_service_headers())
        return r.json() if r.text and r.status_code < 400 else None
    except httpx.HTTPError as e:
        logger.warning(f"sb GET {path} failed: {e}")
        return None


def _require_owner(business_id: str, user: AuthedUser) -> None:
    rows = _sb_get(f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


@router.get("/{business_id}")
async def list_objectives(business_id: str, status: Optional[str] = None,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(business_id, user)
    import asyncio
    objs = await asyncio.to_thread(growth_objective_agent.list_objectives, business_id, status)
    return {"ok": True, "objectives": objs}


@router.post("/{business_id}")
async def create_objective(business_id: str, body: Dict[str, Any],
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Create + spawn a Growth Objective. Body: {title, decision_summary?,
    rationale?, target_date?, metrics?, spawns?}."""
    _require_owner(business_id, user)
    import asyncio
    res = await asyncio.to_thread(
        growth_objective_agent.create_growth_objective, business_id, body or {})
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "create failed"))
    return res


@router.get("/{business_id}/timeline")
async def timeline(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Assemble the Growth Timeline: each objective with its milestones +
    linked workflow-run statuses. Newest objective first; milestones ordered."""
    _require_owner(business_id, user)

    objectives = _sb_get(
        f"/growth_objectives?business_id=eq.{business_id}"
        f"&order=created_at.desc&select=*"
    ) or []
    milestones = _sb_get(
        f"/growth_milestones?business_id=eq.{business_id}"
        f"&order=order_index.asc&select=*"
    ) or []
    runs = _sb_get(
        f"/workflow_runs?business_id=eq.{business_id}"
        f"&order=created_at.desc&limit=200"
        f"&select=id,workflow_id,status,growth_objective_id,step_cursor,steps_total,created_at,completed_at"
    ) or []

    # Index milestones + runs by objective for assembly.
    ms_by_obj: Dict[str, List[Dict[str, Any]]] = {}
    for m in milestones:
        ms_by_obj.setdefault(m.get("objective_id"), []).append(m)
    runs_by_obj: Dict[str, List[Dict[str, Any]]] = {}
    for r in runs:
        oid = r.get("growth_objective_id")
        if oid:
            runs_by_obj.setdefault(oid, []).append(r)

    assembled = []
    for o in objectives:
        oid = o.get("id")
        obj_ms = ms_by_obj.get(oid, [])
        done = sum(1 for m in obj_ms if m.get("status") == "done")
        assembled.append({
            **o,
            "milestones": obj_ms,
            "milestone_progress": {"done": done, "total": len(obj_ms)},
            "workflow_runs": runs_by_obj.get(oid, []),
        })

    # Unattached runs (triggered outside an objective) — surfaced separately so
    # the Timeline can show ambient automation activity too.
    unattached_runs = [r for r in runs if not r.get("growth_objective_id")]

    return {
        "ok": True,
        "business_id": business_id,
        "objectives": assembled,
        "unattached_runs": unattached_runs[:25],
        "counts": {
            "objectives": len(objectives),
            "active": sum(1 for o in objectives if o.get("status") in ("active", "at_risk")),
            "milestones": len(milestones),
        },
    }
