"""
practitioner_profile_router.py — HTTP surface for Practitioner Profile.

All endpoints live under /practitioner-profile. Registered before
public_site_router in kmj_intake_automation.py (which still owns the
catch-all `/{path:path}` route).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import practitioner_profile_agent as pp

router = APIRouter(prefix="/practitioner-profile", tags=["practitioner-profile"])
logger = logging.getLogger("practitioner_profile_router")


class ProactiveModeBody(BaseModel):
    enabled: bool


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "practitioner-profile"})


@router.get("/profile/{owner_id}")
def profile(owner_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "profile": pp.get_profile(owner_id)})


@router.post("/profile/{owner_id}")
def save_profile(owner_id: str, data: Dict[str, Any]) -> JSONResponse:
    row = pp.upsert_profile(owner_id, data or {})
    if row is None:
        return JSONResponse({"ok": False, "error": "save failed"}, status_code=500)
    return JSONResponse({"ok": True, "profile": row})


@router.post("/profile/{owner_id}/proactive-mode")
def set_proactive_mode(owner_id: str, body: ProactiveModeBody) -> JSONResponse:
    """Toggle the user-controlled practitioner-level proactive flag.
    Independent from business_profiles.proactive_capture_enabled — a
    user can have practitioner asks on while business asks are off,
    or vice versa."""
    if not owner_id:
        return JSONResponse({"ok": False, "error": "owner_id required"}, status_code=400)
    row = pp.upsert_profile(owner_id, {"proactive_capture_enabled": bool(body.enabled)})
    if row is None:
        return JSONResponse({"ok": False, "error": "save failed"}, status_code=500)
    return JSONResponse({"ok": True, "enabled": bool(body.enabled), "profile": row})


@router.get("/profile/{owner_id}/is-complete")
def complete(owner_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "complete": pp.is_complete(owner_id)})


@router.get("/profile/{owner_id}/missing")
def missing(owner_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "missing": pp.get_missing_jit_fields(owner_id)})
