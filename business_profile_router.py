"""
business_profile_router.py — HTTP surface for Business Profile.

All endpoints live under /business-profile. This router MUST be
registered BEFORE public_site_router in kmj_intake_automation.py
(public_site_router defines a `/{path:path}` catch-all).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import business_profile_agent as bp

router = APIRouter(prefix="/business-profile", tags=["business-profile"])
logger = logging.getLogger("business_profile_router")


# ──────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────

class SeedBody(BaseModel):
    business_type: str


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "business-profile"})


@router.get("/archetypes")
def list_archetypes() -> JSONResponse:
    rows = bp.list_archetypes()
    return JSONResponse({"ok": True, "archetypes": rows})


@router.get("/archetype/{business_type}")
def archetype(business_type: str) -> JSONResponse:
    row = bp.get_archetype(business_type)
    if not row:
        return JSONResponse({"ok": False, "error": "archetype not found"}, status_code=404)
    return JSONResponse({"ok": True, "archetype": row})


@router.get("/profile/{business_id}")
def profile(business_id: str) -> JSONResponse:
    row = bp.get_profile(business_id)
    return JSONResponse({"ok": True, "profile": row})


@router.post("/profile/{business_id}")
def save_profile(business_id: str, data: Dict[str, Any]) -> JSONResponse:
    row = bp.upsert_profile(business_id, data or {})
    if row is None:
        return JSONResponse({"ok": False, "error": "save failed"}, status_code=500)
    return JSONResponse({"ok": True, "profile": row})


@router.post("/profile/{business_id}/seed-from-archetype")
def seed_from_archetype(business_id: str, body: SeedBody) -> JSONResponse:
    row = bp.apply_archetype_defaults(business_id, body.business_type)
    if row is None:
        return JSONResponse({"ok": False, "error": "unknown archetype"}, status_code=400)
    return JSONResponse({"ok": True, "profile": row})


@router.get("/profile/{business_id}/required-disclaimers")
def required_disclaimers(business_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "disclaimers": bp.get_required_disclaimers(business_id)})


@router.get("/profile/{business_id}/is-complete")
def complete(business_id: str) -> JSONResponse:
    return JSONResponse({"ok": True, "complete": bp.is_complete(business_id)})
