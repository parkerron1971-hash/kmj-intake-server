"""Owner-only endpoints for the Square connection pilot."""
from __future__ import annotations

import html
import secrets
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from auth_supabase import AuthedUser, require_user
from business_access import assert_access
import square_connector as sq

router = APIRouter(tags=["square"])
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}


def owner(business_id, user):
    assert_access(str(business_id), user, "owner")


def pilot(cfg, user):
    if str(user.id) not in cfg.owners:
        raise HTTPException(404, "Square connection is not available.")


def cookie_name(state):
    return "__Host-square-" + sq.digest(state)[:32]


def complete(cfg, message, state="", status=200):
    response = HTMLResponse("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Square connection</title><h1>Square connection</h1><p>" + html.escape(message) +
        "</p><p><a href='" + html.escape(cfg.app_url, quote=True) + "'>Return to Solutionist</a></p></html>",
        status_code=status, headers=HEADERS)
    if state:
        response.delete_cookie(cookie_name(state), path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/square/status")
async def status(business_id: UUID, response: Response, user: AuthedUser = Depends(require_user)):
    owner(business_id, user)
    response.headers["Cache-Control"] = "no-store"
    try:
        cfg = sq.config()
    except HTTPException as exc:
        if exc.status_code == 503:
            return {"available": False, "connected": False}
        raise
    if str(user.id) not in cfg.owners:
        return {"available": False, "connected": False}
    row = await sq.connection(business_id, cfg)
    return {"available": True, "environment": cfg.environment,
            "connected": bool(row and row["status"] == "connected"),
            "status": row["status"] if row else "disconnected",
            "merchant_id": row.get("merchant_id") if row else None,
            "connected_at": row.get("connected_at") if row else None,
            "booking_sync_enabled": False}


@router.post("/connect/square/start")
async def start(business_id: UUID, response: Response, user: AuthedUser = Depends(require_user)):
    owner(business_id, user)
    cfg = sq.config()
    pilot(cfg, user)
    ticket = secrets.token_urlsafe(32)
    if not await sq.rpc("start", p_business=str(business_id), p_environment=cfg.environment,
                        p_user=str(user.id), p_ticket=sq.digest(ticket)):
        raise HTTPException(409, "Disconnect the existing Square connection before connecting again.")
    response.headers["Cache-Control"] = "no-store"
    return {"authorize_url": cfg.callback.removesuffix("/callback") + "/begin?" + urlencode({"ticket": ticket})}


@router.get("/connect/square/begin")
async def begin(ticket: str = ""):
    cfg = sq.config()
    if not ticket or len(ticket) > 128:
        return complete(cfg, "This connection link is invalid. Start again in Solutionist.", status=400)
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    if not await sq.rpc("begin", p_ticket=sq.digest(ticket), p_state=sq.digest(state),
                        p_browser=sq.digest(browser), p_environment=cfg.environment):
        return complete(cfg, "This connection link has expired or was already used. Start again in Solutionist.", status=400)
    query = {"client_id": cfg.app_id, "scope": " ".join(sq.SCOPES), "state": state,
             "redirect_uri": cfg.callback, "session": "false"}
    response = RedirectResponse(cfg.base + "/oauth2/authorize?" + urlencode(query), status_code=303, headers=HEADERS)
    response.set_cookie(cookie_name(state), browser, max_age=600, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.get("/connect/square/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    cfg = sq.config()
    if not state or len(state) > 128:
        return complete(cfg, "The connection could not be verified. Start again in Solutionist.", status=400)
    browser = request.cookies.get(cookie_name(state), "")
    if not browser or len(browser) > 128:
        return complete(cfg, "Return using the browser where you started connecting Square.", state, 400)
    try:
        claims = await sq.rpc("claim", p_state=sq.digest(state), p_browser=sq.digest(browser), p_environment=cfg.environment)
        if not claims:
            return complete(cfg, "This authorization expired or was already used. Start again in Solutionist.", state, 400)
        claim = claims[0]
        user = AuthedUser(id=claim["user_id"], email=None, role="authenticated")
        owner(claim["business_id"], user)
        pilot(cfg, user)
        if error or not code or len(code) > 4096:
            return complete(cfg, "Square was not connected. You can try again from Solutionist.", state, 400)
        tokens = sq.token_payload(await sq.square(cfg, "POST", "/oauth2/token", body={
            "client_id": cfg.app_id, "client_secret": cfg.secret, "grant_type": "authorization_code",
            "code": code, "redirect_uri": cfg.callback}))
        saved = await sq.rpc("finish", p_business=claim["business_id"], p_environment=cfg.environment,
                            p_user=claim["user_id"], p_attempt=claim["attempt_id"], p_merchant=tokens["merchant_id"],
                            p_credentials=sq.seal(cfg, tokens), p_expires=tokens["expires_at"])
        if not saved:
            # Never revoke here: the same merchant might already belong to another
            # Solutionist business, and Square revocation invalidates that whole grant.
            return complete(cfg, "This Square account could not be attached. It may already be connected, or the request was replaced. Return to Solutionist to check.", state, 409)
        return complete(cfg, "Square is connected. Appointment importing is not enabled yet.", state)
    except HTTPException:
        return complete(cfg, "The connection could not be completed. Return to Solutionist to check its status before trying again.", state, 503)


@router.get("/square/locations")
async def locations(business_id: UUID, response: Response, user: AuthedUser = Depends(require_user)):
    owner(business_id, user)
    cfg = sq.config()
    pilot(cfg, user)
    token = await sq.access_token(business_id, cfg)
    payload = await sq.square(cfg, "GET", "/v2/locations", token=token)
    response.headers["Cache-Control"] = "no-store"
    # Only discovery fields; no addresses, tax identifiers or payment configuration.
    return {"locations": [{k: row.get(k) for k in ("id", "name", "status", "timezone")}
                          for row in payload.get("locations", [])]}


@router.delete("/square/connection")
async def disconnect(business_id: UUID, response: Response, user: AuthedUser = Depends(require_user)):
    owner(business_id, user)
    cfg = sq.config()
    pilot(cfg, user)
    response.headers["Cache-Control"] = "no-store"
    claims = await sq.rpc("disconnect", p_business=str(business_id), p_environment=cfg.environment, p_user=str(user.id))
    if not claims:
        row = await sq.connection(business_id, cfg)
        pending = bool(row and row["status"] == "revocation_pending")
        response.status_code = 202 if pending else 200
        return {"disconnected": not row or row["status"] != "connected", "revocation_pending": pending}
    claim = claims[0]
    if claim["merchant_id"]:
        try:
            result = await sq.square(cfg, "POST", "/oauth2/revoke", revoke=True,
                                     body={"client_id": cfg.app_id, "merchant_id": claim["merchant_id"]})
            if result.get("success") is not True:
                raise HTTPException(502, "Revocation pending")
        except HTTPException:
            response.status_code = 202
            return {"disconnected": True, "revocation_pending": True, "retry_after_seconds": 120}
    await sq.rpc("finish_disconnect", p_business=str(business_id), p_environment=cfg.environment, p_revision=claim["revision"])
    return {"disconnected": True, "revocation_pending": False}
