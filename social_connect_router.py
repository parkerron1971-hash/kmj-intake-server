"""social_connect_router.py — a business connects its social accounts
(Post for Me), part 1 of practitioner posting.

The flow mirrors the Meta / QuickBooks / Google connects
(frontend oauthConnect.startOAuthConnect):

  GET  /connect/postforme/start?business_id&platform   signed in, admin+
       -> {authorize_url: "/connect/postforme?ticket=…&platform=…"}
  GET  /connect/postforme?ticket&platform              the popup lands here
       -> 302 to the network's sign-in (via Post for Me)
  GET  /connect/postforme/done                          Post for Me sends people back here
       -> a "Connected" page that tells the opener and closes
  POST /social/sync?business_id                         the opener asks for the result
  GET  /social/connections?business_id                  what's connected
  POST /social/disconnect?business_id&connection_id

Why a ticket: the popup redirect can't carry a bearer token, and Post for
Me binds whatever account signs in to the `external_id` we name. Minting
that link from a bare business id would let anyone attach their account
to someone else's business (the hole oauth_connect_ticket closed for Meta).

/connect/postforme/done is the project redirect URL to set in the Post
for Me dashboard (Quickstart projects can't override it per request). It
takes no business id and touches nothing: it only tells the app to sync.

One social account belongs to one business. If a second business signs
in with an account another business already connected, sync refuses it
and says so, rather than moving it.

Posting is a pilot until the Booked / Boss plans are on sale
(post_for_me.allowed_for). Tokens never reach this file: post_for_me
strips them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import oauth_connect_ticket
import post_for_me
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

logger = logging.getLogger("social_connect")

router = APIRouter(tags=["social-connect"])

PROVIDER = "post_for_me"
_SELECT = "id,platform,username,profile_photo_url,status,connected_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_pilot(business_id: str) -> None:
    if not post_for_me.configured():
        raise HTTPException(503, "Posting isn't set up on the server yet.")
    if not post_for_me.allowed_for(business_id):
        raise HTTPException(403, "Posting to your social accounts isn't switched on for this business yet.")


def _platform_or_400(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p not in post_for_me.PLATFORMS:
        raise HTTPException(400, "That network isn't one we connect.")
    return p


def _rows_for(business_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/social_connections?business_id=eq.{business_id}&provider=eq.{PROVIDER}"
        f"&order=connected_at.asc&select={_SELECT}") or []


# ─── The connect handshake ───────────────────────────────────────────

@router.get("/connect/postforme/start")
async def postforme_connect_start(business_id: str, platform: str,
                                  biz: dict = Depends(business_access("admin")),
                                  session: UserSession = Depends(sb_clients.authed_request)):
    """The signed-in half: an owner or admin of THIS business asks to
    connect one network. Hands back a five-minute ticket link."""
    p = _platform_or_400(platform)
    _require_pilot(business_id)
    ticket = oauth_connect_ticket.mint(business_id, str(session.user.id))
    return {"authorize_url": f"/connect/postforme?ticket={quote(ticket)}&platform={p}"}


@router.get("/connect/postforme")
async def postforme_connect(ticket: str = "", platform: str = ""):
    """The popup lands here; the ticket names the business. Asks Post for
    Me for that business's sign-in link and sends the popup to it."""
    business_id, _uid = oauth_connect_ticket.verify(ticket) if ticket else (None, None)
    if not business_id:
        return _page("This link expired", "Start again from Solutionist.", ok=False)
    p = (platform or "").strip().lower()
    if p not in post_for_me.PLATFORMS or not post_for_me.allowed_for(business_id):
        return _page("Can't connect that here", "Start again from Solutionist.", ok=False)
    try:
        url = await post_for_me.auth_url(p, business_id)
    except post_for_me.PostForMeError:
        return _page("Couldn't reach the sign-in", "Close this window and try again in a minute.", ok=False)
    return RedirectResponse(url=url, status_code=302)


@router.get("/connect/postforme/done")
async def postforme_connect_done(request: Request):
    """Where Post for Me sends people back. Names nothing and trusts
    nothing in the query: the app syncs from Post for Me itself. Only the
    parameter NAMES are logged (their values can carry account ids), so
    we can see what Post for Me sends on success and on cancel."""
    keys = sorted(request.query_params.keys())
    logger.info("[social] connect returned with params %s", keys)
    failed = any(k.lower() in ("error", "error_description", "error_reason") for k in keys) \
        or (request.query_params.get("isSuccess") or "").lower() == "false"
    if failed:
        return _page("Not connected", "The sign-in didn't finish. Close this window and try again.",
                     ok=False, notify=True)
    return _page("Connected", "You can close this window and go back to Solutionist.", ok=True, notify=True)


def _page(title: str, message: str, *, ok: bool, notify: bool = False) -> HTMLResponse:
    """A small page the popup shows for a moment. When `notify`, it tells
    the window that opened it to refresh, then closes itself."""
    esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    script = ("""<script>
  try { if (window.opener) { window.opener.postMessage({ type: 'solutionist-social-connected' }, '*'); } } catch (e) {}
  setTimeout(function () { try { window.close(); } catch (e) {} }, 1200);
</script>""" if notify else "")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 56px 16px;
          text-align: center; background: Canvas; color: CanvasText; }}
  .card {{ max-width: 420px; margin: 0 auto; padding: 28px 24px; border-radius: 14px;
           border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); }}
  h1 {{ font-size: 20px; margin: 0 0 8px; font-weight: 600; }}
  p {{ font-size: 14px; line-height: 1.5; margin: 0; opacity: .75; }}
</style></head><body>
<div class="card"><h1>{'&#10003; ' if ok else ''}{esc(title)}</h1><p>{esc(message)}</p></div>
{script}
</body></html>"""
    return HTMLResponse(content=html, status_code=200 if ok or notify else 400)


# ─── What's connected ────────────────────────────────────────────────

@router.get("/social/connections")
async def list_connections(business_id: str, biz: dict = Depends(business_access("viewer"))):
    enabled = post_for_me.allowed_for(business_id)
    try:
        rows = _rows_for(business_id)
    except Exception:
        rows = []
    return {"ok": True, "enabled": enabled,
            "platforms": list(post_for_me.PLATFORMS) if enabled else [],
            "connections": rows}


@router.post("/social/sync")
async def sync_connections(business_id: str, biz: dict = Depends(business_access("admin")),
                           session: UserSession = Depends(sb_clients.authed_request)):
    """Bring our record in line with Post for Me for this business: new
    accounts are added, ones that went away are marked disconnected, and
    an account another business already holds is refused, not moved."""
    _require_pilot(business_id)
    try:
        accounts = await post_for_me.accounts_for(business_id)
    except post_for_me.PostForMeError:
        raise HTTPException(502, "Couldn't reach Post for Me. Try again in a minute.")
    before = {r["id"]: r for r in _rows_for(business_id)}
    added: List[Dict[str, str]] = []
    conflicts: List[Dict[str, str]] = []
    seen_ids = set()
    for a in accounts:
        acct_id = a.get("id")
        seen_ids.add(acct_id)
        holder = sb_clients.sb_get_as_service(
            f"/social_connections?provider=eq.{PROVIDER}&provider_account_id=eq.{quote(str(acct_id))}"
            f"&select=id,business_id,status&limit=1") or []
        if holder and holder[0].get("business_id") != business_id \
                and holder[0].get("status") == "connected":
            conflicts.append({"platform": a.get("platform") or "", "username": a.get("username") or ""})
            continue
        status = "connected" if a.get("status") == "connected" else "disconnected"
        row = {"business_id": business_id, "provider": PROVIDER,
               "platform": a.get("platform"), "provider_account_id": acct_id,
               "username": a.get("username"), "profile_photo_url": a.get("profile_photo_url"),
               "status": status, "updated_at": _now()}
        if not holder or holder[0].get("business_id") != business_id:
            row.update(connected_by=str(session.user.id), connected_at=_now())
            if status == "connected":
                added.append({"platform": row["platform"] or "", "username": row["username"] or ""})
        sb_clients.sb_post_as_service(
            "/social_connections?on_conflict=provider,provider_account_id", row,
            prefer="resolution=merge-duplicates,return=minimal")
    # Accounts this business holds that Post for Me no longer lists under
    # it. Asked about BY ID before marking them gone: when another business
    # signs in with the same account, Post for Me relabels it to them (one
    # record per account), and that sign-in was refused above — so the
    # account is still this business's, still connected, just labelled
    # elsewhere. Only an account Post for Me shows as disconnected, or no
    # longer has, is marked disconnected here.
    held = sb_clients.sb_get_as_service(
        f"/social_connections?business_id=eq.{business_id}&provider=eq.{PROVIDER}"
        f"&status=eq.connected&select=id,provider_account_id") or []
    unseen = {r["provider_account_id"]: r["id"] for r in held
              if r.get("provider_account_id") not in seen_ids}
    if unseen:
        try:
            still = {a["id"] for a in await post_for_me.accounts_by_ids(list(unseen))
                     if a.get("status") == "connected"}
        except post_for_me.PostForMeError:
            still = set(unseen)           # can't tell: leave them as they are
        for acct_id, row_id in unseen.items():
            if acct_id not in still:
                sb_clients.sb_patch_as_service(f"/social_connections?id=eq.{row_id}",
                                               {"status": "disconnected", "updated_at": _now()})
    rows = _rows_for(business_id)
    logger.info("[social] sync %s: %d accounts, %d new, %d refused",
                business_id[:8], len(accounts), len(added), len(conflicts))
    return {"ok": True, "connections": rows, "added": added, "conflicts": conflicts,
            "was": len(before)}


@router.post("/social/disconnect")
async def disconnect_connection(business_id: str, connection_id: str,
                                biz: dict = Depends(business_access("admin"))):
    rows = sb_clients.sb_get_as_service(
        f"/social_connections?id=eq.{quote(connection_id)}&business_id=eq.{business_id}"
        f"&provider=eq.{PROVIDER}&select=id,provider_account_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "That account isn't connected to this business.")
    try:
        await post_for_me.disconnect(rows[0]["provider_account_id"])
    except post_for_me.PostForMeError as e:
        if e.status != 404:        # already gone there is the outcome we want
            raise HTTPException(502, "Couldn't reach Post for Me. Try again in a minute.")
    sb_clients.sb_patch_as_service(f"/social_connections?id=eq.{rows[0]['id']}",
                                   {"status": "disconnected", "updated_at": _now()})
    return {"ok": True, "connections": _rows_for(business_id)}
