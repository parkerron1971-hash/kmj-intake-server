"""
module_spec_router.py — Phase B dock-facing surface.

Owner-checked endpoints for the Chief dock's spec card stack:
  POST /module-specs/propose                  generate (1+ specs) for an intake
  POST /module-specs/{spec_id}/accept         materialize → custom_modules + workflows
  POST /module-specs/{spec_id}/reject         mark rejected
  GET  /module-specs?business_id=…&status=…   list (debug + reload)

Owner check mirrors workflow_router / restricted_modules / growth_objective_router.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth_supabase import AuthedUser, require_user
import module_spec_generator as msg

logger = logging.getLogger("module_spec_router")
router = APIRouter(prefix="/module-specs", tags=["module-specs"])
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


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


def _owner_for_spec(spec_id: str) -> Optional[str]:
    """Get the business owner_id for a spec — used by accept/reject endpoints
    where the caller passes spec_id without business_id."""
    rows = _sb_get(f"/module_specs?id=eq.{spec_id}&select=business_id&limit=1") or []
    if not rows:
        return None
    biz_id = rows[0].get("business_id")
    biz_rows = _sb_get(f"/businesses?id=eq.{biz_id}&select=owner_id&limit=1") or []
    return biz_rows[0].get("owner_id") if biz_rows else None


@router.post("/propose")
async def propose(body: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    business_id = (body or {}).get("business_id")
    intake = (body or {}).get("intake_excerpt", "")
    revise = (body or {}).get("revise_feedback")
    if not business_id or not intake:
        raise HTTPException(status_code=400, detail="business_id and intake_excerpt required")
    _require_owner(business_id, user)
    import asyncio
    res = await asyncio.to_thread(msg.propose_module_from_intake, business_id, intake, revise)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "propose failed"))
    return res


@router.post("/{spec_id}/accept")
async def accept(spec_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    owner = _owner_for_spec(spec_id)
    if not owner:
        raise HTTPException(status_code=404, detail="spec not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    import asyncio
    res = await asyncio.to_thread(msg.materialize_spec, spec_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "materialize failed"))
    return res


@router.post("/{spec_id}/reject")
async def reject(spec_id: str, body: Optional[Dict[str, Any]] = None,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    owner = _owner_for_spec(spec_id)
    if not owner:
        raise HTTPException(status_code=404, detail="spec not found")
    if str(owner) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")
    import asyncio
    res = await asyncio.to_thread(msg.reject_spec, spec_id, (body or {}).get("reason"))
    return res


@router.get("")
async def list_specs(business_id: str, status: Optional[str] = None,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(business_id, user)
    import asyncio
    rows = await asyncio.to_thread(msg.list_specs, business_id, status)
    return {"ok": True, "specs": rows}
