"""
business_profile_router.py — HTTP surface for Business Profile.

All endpoints live under /business-profile. This router MUST be
registered BEFORE public_site_router in kmj_intake_automation.py
(public_site_router defines a `/{path:path}` catch-all).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import business_profile_agent as bp
import sb_clients
from auth_supabase import AuthedUser, require_user


def _require_owner(business_id: str, user: AuthedUser) -> None:
    # Beta-readiness audit (adversarial): this router was fully
    # unauthenticated + service-role (RLS-bypassed). Verify the caller
    # owns the business before any read/write.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1")
    # None is a FAILED read (transport error, or PostgREST 4xx such as a
    # non-uuid id) — not an empty one. Reporting it as 404 is how the
    # shadowed-route bug above hid for four months.
    if rows is None:
        raise HTTPException(status_code=503, detail="business lookup failed")
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")

router = APIRouter(prefix="/business-profile", tags=["business-profile"])
logger = logging.getLogger("business_profile_router")


# ──────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────

class SeedBody(BaseModel):
    business_type: str


class SeedFromOnboardingBody(BaseModel):
    business_id: str
    business_type: str
    tones: Optional[List[Any]] = None
    voice_profile: Optional[Dict[str, Any]] = None


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


# ROUTE ORDER IS LOAD-BEARING. Starlette matches in declaration order, and
# `POST /profile/{business_id}` below would otherwise capture the literal
# path `/profile/seed-from-onboarding` with business_id="seed-from-onboarding"
# (it did, from 2026-05-02 to 2026-09-01: every onboarding seed answered 404
# "business not found" and no new business got a profile, a blueprint module
# set, or a vertical autopilot). Literal paths under /profile/ go ABOVE the
# parameter routes; __tests__/test_business_profile_route_order.py enforces it.
@router.post("/profile/seed-from-onboarding")
def seed_from_onboarding(body: SeedFromOnboardingBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    """
    Called from OnboardingFlow.handleLaunch after the businesses row is
    inserted. Idempotent: maps tones -> brand_voice, applies archetype
    defaults, and only fills NULL fields if a profile already exists.
    Failure is non-fatal on the client side.
    """
    _require_owner(body.business_id, user)
    row = bp.seed_from_onboarding(
        business_id=body.business_id,
        business_type=body.business_type,
        tones=body.tones,
        voice_profile=body.voice_profile,
    )
    if row is None:
        return JSONResponse({"ok": False, "error": "seed failed"}, status_code=500)

    # Phase 1: auto-assemble the business-type core module set (blueprint walk).
    # Purpose-track convergence point — mirrors the strategy-track hook in
    # chief_of_staff.handle_complete_strategy_track (Fork 5). Non-fatal.
    try:
        import module_blueprint_agent
        module_blueprint_agent.provision_modules(body.business_id, body.business_type)
    except Exception as e:
        logger.warning(f"seed-from-onboarding blueprint provision failed (non-fatal): {e}")

    # Queue this vertical's default autopilot — the one recurring job the
    # vertical would miss (a barber's rebooking cadence, a lawyer's deadline
    # sweep). Idempotent per (business, job key), so re-running onboarding
    # cannot stack duplicate schedules. Non-fatal for the same reason the
    # blueprint walk above is: a business must finish onboarding even if its
    # autopilot did not queue.
    try:
        import vertical_autopilot
        vertical_autopilot.seed_defaults(
            business_id=body.business_id,
            business_type=body.business_type,
            owner_id=str(user.id),
        )
    except Exception as e:
        logger.warning(f"seed-from-onboarding autopilot seed failed (non-fatal): {e}")

    return JSONResponse({"ok": True, "profile": row})


@router.get("/profile/{business_id}")
def profile(business_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    row = bp.get_profile(business_id)
    return JSONResponse({"ok": True, "profile": row})


@router.post("/profile/{business_id}")
def save_profile(business_id: str, data: Dict[str, Any], user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    row = bp.upsert_profile(business_id, data or {})
    if row is None:
        return JSONResponse({"ok": False, "error": "save failed"}, status_code=500)
    return JSONResponse({"ok": True, "profile": row})


@router.post("/profile/{business_id}/seed-from-archetype")
def seed_from_archetype(business_id: str, body: SeedBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    row = bp.apply_archetype_defaults(business_id, body.business_type)
    if row is None:
        return JSONResponse({"ok": False, "error": "unknown archetype"}, status_code=400)
    return JSONResponse({"ok": True, "profile": row})


@router.get("/profile/{business_id}/required-disclaimers")
def required_disclaimers(business_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    return JSONResponse({"ok": True, "disclaimers": bp.get_required_disclaimers(business_id)})


@router.get("/profile/{business_id}/is-complete")
def complete(business_id: str, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    _require_owner(business_id, user)
    return JSONResponse({"ok": True, "complete": bp.is_complete(business_id)})


class ProactiveModeBody(BaseModel):
    enabled: bool


@router.post("/profile/{business_id}/proactive-mode")
def set_proactive_mode(business_id: str, body: ProactiveModeBody, user: AuthedUser = Depends(require_user)) -> JSONResponse:
    """
    Toggle the user-controlled proactive JIT capture flag. When enabled,
    the Chief may bring up one missing profile field at natural pauses
    even without a reactive keyword trigger. Off by default.
    """
    if not business_id:
        return JSONResponse({"ok": False, "error": "business_id required"}, status_code=400)
    _require_owner(business_id, user)
    row = bp.upsert_profile(business_id, {"proactive_capture_enabled": bool(body.enabled)})
    if row is None:
        return JSONResponse({"ok": False, "error": "save failed"}, status_code=500)
    return JSONResponse({"ok": True, "enabled": bool(body.enabled), "profile": row})
