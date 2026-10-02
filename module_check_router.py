"""
module_check_router.py — the preview door and the check trigger.

  GET  /module-preview/{token}            → {module_id, business_id, name}
  GET  /module-preview/{token}/rest?path= → one scoped read for the page
  POST /module-check                      → enqueue a module_check job
                                            (signed-in owner)

The preview endpoints are token-authenticated (module_check.preview_token:
signed, twenty minutes, one business, one module) so headless Chromium on
the server can render the real surface without a sign-in. They answer
reads only; a write from the preview page is refused.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import module_check
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("module_check_router")

router = APIRouter(tags=["module-check"])


@router.get("/module-preview/{token}")
async def preview_meta(token: str) -> Dict[str, Any]:
    data = module_check.read_token(token)
    if not data:
        raise HTTPException(status_code=403, detail="preview link expired")
    import sb_clients
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/custom_modules?id=eq.{data['m']}&business_id=eq.{data['b']}&select=id,name,archetype&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="module not found")
    return {"ok": True, "module_id": data["m"], "business_id": data["b"],
            "name": rows[0].get("name"), "archetype": rows[0].get("archetype"),
            "sample": bool(data.get("s"))}


@router.get("/module-preview/{token}/rest")
async def preview_rest(token: str, path: str = Query(..., max_length=2000)) -> Any:
    data = module_check.read_token(token)
    if not data:
        raise HTTPException(status_code=403, detail="preview link expired")
    status, body = await asyncio.to_thread(module_check.answer_rest, data, path)
    if status != 200:
        raise HTTPException(status_code=status, detail=(body or {}).get("error") or "refused")
    return body


class _CheckReq(BaseModel):
    business_id: str
    module_id: str
    vision: Optional[bool] = True
    reason: Optional[str] = "manual"


@router.post("/module-check")
async def enqueue_check(req: _CheckReq, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    import chief_jobs
    import sb_clients
    owned = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/businesses?id=eq.{req.business_id}&owner_id=eq.{user.id}&select=id&limit=1") or []
    if not owned:
        raise HTTPException(status_code=403, detail="not your business")
    async with httpx.AsyncClient() as client:
        job = await chief_jobs.enqueue(
            client, user_id=str(user.id), business_id=req.business_id, kind=module_check.JOB_KIND,
            params={"module_id": req.module_id, "vision": req.vision is not False,
                    "reason": req.reason or "manual"}, source="desktop")
    out = {"ok": True, "job_id": (job or {}).get("id")}
    if (job or {}).get("deduped"):
        out["deduped"] = True
    return out


async def enqueue_after_accept(user_id: str, business_id: str, module_id: Optional[str],
                               reason: str = "accepted") -> None:
    """Best effort, never raises: every accepted module gets looked at."""
    if not module_id or not module_check.enabled():
        return
    try:
        import chief_jobs
        async with httpx.AsyncClient() as client:
            await chief_jobs.enqueue(
                client, user_id=str(user_id), business_id=str(business_id), kind=module_check.JOB_KIND,
                params={"module_id": str(module_id), "vision": True, "reason": reason}, source="system")
    except Exception as e:
        logger.info(f"[module-check] not enqueued after accept: {e}")
