"""
foundation_router.py — HTTP surface for Foundation Track.

All endpoints live under /foundation. This router MUST be registered
BEFORE public_site_router in kmj_intake_automation.py because
public_site_router defines a `/{path:path}` catch-all.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import foundation_agent as fa

router = APIRouter(prefix="/foundation", tags=["foundation"])
logger = logging.getLogger("foundation_router")


# ──────────────────────────────────────────────────────────────
# Request / response models
# ──────────────────────────────────────────────────────────────

class UpdatePhaseBody(BaseModel):
    status: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class RecommendEntityBody(BaseModel):
    business_id: str
    situation: Dict[str, Any]


class OperatingAgreementBody(BaseModel):
    business_id: str
    business_name: str
    state_code: str
    members: List[Dict[str, Any]]


class PolicyBody(BaseModel):
    business_id: str
    business_data: Dict[str, Any]


# ──────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────

@router.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "foundation"})


# ──────────────────────────────────────────────────────────────
# Progress
# ──────────────────────────────────────────────────────────────

@router.get("/progress/{business_id}")
async def get_progress(business_id: str) -> JSONResponse:
    data = await fa.get_progress(business_id)
    return JSONResponse(data)


@router.patch("/progress/{business_id}/phase/{phase}")
async def update_phase(business_id: str, phase: int, body: UpdatePhaseBody) -> JSONResponse:
    result = await fa.update_phase(
        business_id=business_id,
        phase=phase,
        status=body.status,
        data=body.data,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/progress/{business_id}/phase/{phase}/complete")
async def complete_phase(business_id: str, phase: int) -> JSONResponse:
    result = await fa.phase_completed(business_id, phase)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


# ──────────────────────────────────────────────────────────────
# Phase 1 - Entity formation
# ──────────────────────────────────────────────────────────────

@router.post("/recommend-entity")
async def recommend_entity(body: RecommendEntityBody) -> JSONResponse:
    result = await fa.recommend_entity(body.business_id, body.situation)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.get("/state-filing/{state_code}")
async def state_filing(state_code: str) -> JSONResponse:
    result = await fa.get_state_filing_info(state_code)
    return JSONResponse(result, status_code=200 if result.get("ok") else 404)


# ──────────────────────────────────────────────────────────────
# Phase 4 - Operating agreement
# ──────────────────────────────────────────────────────────────

@router.post("/operating-agreement")
async def operating_agreement(body: OperatingAgreementBody) -> JSONResponse:
    result = await fa.generate_operating_agreement(
        business_id=body.business_id,
        business_name=body.business_name,
        state_code=body.state_code,
        members=body.members,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


# ──────────────────────────────────────────────────────────────
# Phase 7 - Policies
# ──────────────────────────────────────────────────────────────

@router.post("/privacy-policy")
async def privacy_policy(body: PolicyBody) -> JSONResponse:
    result = await fa.generate_privacy_policy(body.business_id, body.business_data)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/terms-of-service")
async def terms_of_service(body: PolicyBody) -> JSONResponse:
    result = await fa.generate_terms_of_service(body.business_id, body.business_data)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


# ──────────────────────────────────────────────────────────────
# Documents
# ──────────────────────────────────────────────────────────────

@router.get("/documents/{business_id}")
async def list_documents(business_id: str, phase: Optional[int] = None) -> JSONResponse:
    import httpx
    qs = f"?business_id=eq.{business_id}&order=created_at.desc"
    if phase is not None:
        qs += f"&phase=eq.{phase}"
    async with httpx.AsyncClient() as client:
        rows = await fa._sb_get(client, f"/foundation_documents{qs}") or []
    return JSONResponse({"ok": True, "documents": rows})


@router.get("/document/{document_id}")
async def get_document(document_id: str) -> JSONResponse:
    import httpx
    async with httpx.AsyncClient() as client:
        rows = await fa._sb_get(client, f"/foundation_documents?id=eq.{document_id}") or []
    if not rows:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return JSONResponse({"ok": True, "document": rows[0]})
