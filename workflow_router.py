"""
workflow_router.py — LGS Phase 3 practitioner-facing surface for workflow runs.

Two owner-checked endpoints:
  POST /workflows/runs/{run_id}/confirm   — approve an awaiting_confirmation run
                                            (the confirmation gate, Fork 17)
  GET  /workflows/runs/{business_id}       — list this business's runs (timeline + debug)

The scan-tick drain itself is NOT exposed here — it runs in-process on the
APScheduler (Fork 7, cron-driven, never a frontend heartbeat). Owner-check
mirrors restricted_modules.py (business.owner_id == auth.uid; the 25b seam).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth_supabase import AuthedUser, require_user
import workflow_engine

logger = logging.getLogger("workflow_router")
router = APIRouter(prefix="/workflows", tags=["workflows"])

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
    """Owner-only gate (business.owner_id == auth.uid). Mirrors restricted_modules."""
    rows = _sb_get(f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


@router.get("/runs/{business_id}")
async def list_runs(business_id: str, limit: int = 50,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """All workflow runs for a business, newest first. Owner-only."""
    _require_owner(business_id, user)
    rows = _sb_get(
        f"/workflow_runs?business_id=eq.{business_id}"
        f"&order=created_at.desc&limit={max(1, min(200, limit))}&select=*"
    ) or []
    return {"ok": True, "runs": rows}


@router.post("/runs/{run_id}/confirm")
async def confirm(run_id: str, body: Dict[str, Any],
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Approve an awaiting_confirmation run so the next drain tick advances it.
    Body: {business_id}. Owner-only (the human approving a gated step)."""
    business_id = (body or {}).get("business_id")
    if not business_id:
        raise HTTPException(status_code=400, detail="business_id required")
    _require_owner(business_id, user)
    # Confirm scopes to the owner's business — verify the run belongs to it.
    rows = _sb_get(f"/workflow_runs?id=eq.{run_id}&select=business_id&limit=1") or []
    if not rows or str(rows[0].get("business_id")) != str(business_id):
        raise HTTPException(status_code=404, detail="run not found for this business")
    res = await workflow_engine.confirm_run(run_id, confirmed_by=user.email or user.id)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=res.get("error", "confirm failed"))
    return res
