"""Owner-bound Lane readiness API. This phase cannot submit or execute purchases."""
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

import business_access
import lane_mcp
import sb_clients
from auth_supabase import UserSession

router = APIRouter(prefix="/lane/wallet", tags=["wallet"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def owner(business_id, session):
    try:
        bid = str(UUID(business_id))
    except ValueError:
        raise HTTPException(400, "Invalid business.", headers=NO_STORE) from None
    try:
        business_access.assert_access(bid, session.user, "owner")
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **NO_STORE}
        raise
    return bid, str(session.user.id)


def eligible(bid, user_id):
    return bool(os.getenv("LANE_PILOT_ENABLED") == "true"
                and bid == os.getenv("LANE_PILOT_BUSINESS_ID")
                and user_id == os.getenv("LANE_PILOT_USER_ID"))


@router.get("/{business_id}")
def status(business_id: str, response: Response,
           session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    bid, user_id = owner(business_id, session)
    enabled = eligible(bid, user_id)
    from lane_purchases import configured, checkout_enabled
    return {"provider": "lane", "pilot_available": enabled,
            "purchases_available": enabled and configured() and lane_mcp.valid_key(os.getenv("LANE_PILOT_API_KEY")),
            "checkout_enabled": enabled and checkout_enabled(),
            "configured": enabled and lane_mcp.valid_key(os.getenv("LANE_PILOT_API_KEY")),
            "connection_verified": False, "live_spending_enabled": enabled and checkout_enabled(),
            "customer_connections_available": False}


@router.post("/{business_id}/verify")
def verify(business_id: str, response: Response,
           session: UserSession = Depends(sb_clients.authed_request)):
    response.headers.update(NO_STORE)
    bid, user_id = owner(business_id, session)
    if not eligible(bid, user_id):
        raise HTTPException(403, "The Lane pilot is not enabled for this account.", headers=NO_STORE)
    key = os.getenv("LANE_PILOT_API_KEY")
    if not lane_mcp.valid_key(key):
        raise HTTPException(503, "Configure the private Lane wallet key on the server.", headers=NO_STORE)
    try:
        return {"provider": "lane", **lane_mcp.probe(key)}
    except lane_mcp.LaneError as exc:
        raise HTTPException(503, str(exc), headers=NO_STORE) from None
