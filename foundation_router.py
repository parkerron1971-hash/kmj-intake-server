"""
foundation_router.py — HTTP surface for Foundation Track.

All endpoints live under /foundation. This router MUST be registered
BEFORE public_site_router in kmj_intake_automation.py because
public_site_router defines a `/{path:path}` catch-all.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import foundation_agent as fa
import sb_clients
from auth_supabase import AuthedUser, require_user


def _require_owner(business_id: str, user: AuthedUser) -> None:
    # Beta-readiness audit (adversarial): this router was fully
    # unauthenticated + service-role (RLS-bypassed), and /document/{id}
    # read any tenant's legal docs by id. Owner-check every access.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")

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


class AcceptEntityBody(BaseModel):
    business_id: str
    entity_type: str
    # Disambiguates a bare "LLC" into single- vs multi-member. Without it an
    # ambiguous value is rejected rather than guessed.
    member_count: Optional[int] = None


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
async def get_progress(business_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    data = await fa.get_progress(business_id)
    return JSONResponse(data)


@router.patch("/progress/{business_id}/phase/{phase}")
async def update_phase(business_id: str, phase: int, body: UpdatePhaseBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    result = await fa.update_phase(
        business_id=business_id,
        phase=phase,
        status=body.status,
        data=body.data,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/progress/{business_id}/phase/{phase}/complete")
async def complete_phase(business_id: str, phase: int, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    result = await fa.phase_completed(business_id, phase)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


# ──────────────────────────────────────────────────────────────
# Phase 1 - Entity formation
# ──────────────────────────────────────────────────────────────

@router.post("/recommend-entity")
async def recommend_entity(body: RecommendEntityBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(body.business_id, user)
    result = await fa.recommend_entity(body.business_id, body.situation)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/entity-type")
async def accept_entity_type(body: AcceptEntityBody,
                             user: AuthedUser = Depends(require_user)) -> JSONResponse:
    """Record the entity form the owner chose (not merely the one suggested).

    Writes business_profiles.entity_type, which the Revenue set-aside estimate
    reads before deciding whether its self-employment-tax assumption holds.
    """
    _require_owner(body.business_id, user)
    result = await fa.accept_entity_type(
        body.business_id, body.entity_type, member_count=body.member_count)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.get("/state-coverage")
async def state_coverage(user: AuthedUser = Depends(require_user)) -> JSONResponse:
    """Which states have verified filing data. Not business-scoped — it is
    reference data, so no owner check, but still authenticated."""
    result = await fa.list_state_coverage()
    return JSONResponse(result, status_code=200 if result.get("ok") else 500)


@router.get("/state-filing/{state_code}")
async def state_filing(state_code: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    result = await fa.get_state_filing_info(state_code)
    return JSONResponse(result, status_code=200 if result.get("ok") else 404)


# ──────────────────────────────────────────────────────────────
# Phase 4 - Operating agreement
# ──────────────────────────────────────────────────────────────

@router.post("/operating-agreement")
async def operating_agreement(body: OperatingAgreementBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(body.business_id, user)
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
async def privacy_policy(body: PolicyBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(body.business_id, user)
    result = await fa.generate_privacy_policy(body.business_id, body.business_data)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/terms-of-service")
async def terms_of_service(body: PolicyBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(body.business_id, user)
    result = await fa.generate_terms_of_service(body.business_id, body.business_data)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


# ──────────────────────────────────────────────────────────────
# Documents
# ──────────────────────────────────────────────────────────────

@router.get("/documents/{business_id}")
async def list_documents(business_id: str, phase: Optional[int] = None, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    import httpx
    qs = f"?business_id=eq.{business_id}&order=created_at.desc"
    if phase is not None:
        qs += f"&phase=eq.{phase}"
    async with httpx.AsyncClient() as client:
        rows = await fa._sb_get(client, f"/foundation_documents{qs}") or []
    return JSONResponse({"ok": True, "documents": rows})


@router.get("/document/{document_id}")
async def get_document(document_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    import httpx
    async with httpx.AsyncClient() as client:
        rows = await fa._sb_get(client, f"/foundation_documents?id=eq.{document_id}") or []
    if not rows:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    # Owner-check the document's own business before returning it.
    _require_owner(str(rows[0].get("business_id") or ""), user)
    return JSONResponse({"ok": True, "document": rows[0]})
