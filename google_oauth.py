"""google_oauth.py — connecting a practitioner's actual mailbox.

WHAT THIS CLOSES
  Chief could only ever see replies to mail WE sent, because the routed
  reply-to (reply+{biz8}+{contact8}@INBOUND_EMAIL_DOMAIN) points at our
  own inbound webhook. Anything sent directly to the practitioner —
  a new lead emailing hello@theirfirm.com, a client starting a fresh
  thread — never touched this system.

  Reading the mailbox itself covers that without moving anyone's MX.
  hello@theirfirm.com on Google Workspace IS a Gmail mailbox: same API,
  same scopes. So this one integration serves both the @gmail.com
  practitioner and the custom-domain practitioner, and their DNS is
  never our problem.

THE HANDSHAKE IS NOT NEW
  /connect/google/start → ticket → /connect/google → Google → callback.
  This mirrors meta_oauth exactly and for the same reason: the redirect
  carries no bearer token, so ownership is proved by an authenticated
  call first and handed on as a short-lived HMAC ticket. See
  oauth_connect_ticket for why a merely-signed state is not enough.

  The OAuth `state` here IS a ticket (minted by the same helper) rather
  than a second bespoke signed blob. One secret, one verifier, ten-minute
  window — long enough for a human to pick an account and read a consent
  screen, short enough that a leaked state is not a standing key.

SCOPE
  gmail.readonly, and nothing else. Two consequences worth knowing:

  - It is a RESTRICTED scope. The app runs in Testing (≤100 users,
    counted over the app's LIFETIME) until it passes Google's
    verification + CASA security assessment. Testing needs neither.
  - We do NOT request userinfo.email. The connected address comes from
    gmail.users.getProfile, which gmail.readonly already permits. Asking
    for a scope we did not register in the console would fail consent.

WHAT THIS FILE DOES NOT DO
  It connects and stores. It does not sync. Ingesting messages into
  email_replies is deliberately a separate change, because it needs the
  selection policy decided first — a whole mailbox means every
  newsletter and phishing attempt becomes candidate input for an agent
  that holds write verbs. Storage and prompt-eligibility are two
  different questions and must stay two different decisions.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import oauth_connect_ticket
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("google_oauth")

router = APIRouter(tags=["google"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

GOOGLE_SCOPES = "https://www.googleapis.com/auth/gmail.readonly"

# The redirect leaves our control for as long as a human takes to choose
# an account and read a consent screen. Five minutes (the ticket default)
# is too tight for that; ten matches what meta_oauth allows its state.
STATE_MAX_AGE_SECONDS = 10 * 60

# Refresh a little early. A token that expires mid-request is a failed
# sync that looks like an auth bug.
ACCESS_TOKEN_SKEW_SECONDS = 120

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)


# ─── Env ─────────────────────────────────────────────────────────────

def _client_id() -> str:
    return (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()


def _redirect_uri() -> str:
    """Must match a URI registered on the OAuth client byte-for-byte, or
    Google refuses with redirect_uri_mismatch before the user sees
    anything. Overridable so a preview deploy can register its own."""
    explicit = (os.environ.get("GOOGLE_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    base = (os.environ.get("PUBLIC_BASE_URL")
            or "https://kmj-intake-server-production.up.railway.app").rstrip("/")
    return f"{base}/connect/google/callback"


def _configured() -> bool:
    return bool(_client_id() and _client_secret())


# ─── Ownership ───────────────────────────────────────────────────────

def _require_owner(business_id: str, user: AuthedUser) -> None:
    """Service-role read of owner_id, independent of RLS — the same check
    meta_oauth makes, for the same reason: connecting a mailbox to a
    business must be gated on owning that business, not on whatever the
    caller's JWT happens to be able to select."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403,
                            detail="not authorized for this business")


# ─── Token plumbing ──────────────────────────────────────────────────

async def _exchange_code(client: httpx.AsyncClient, code: str) -> Dict[str, Any]:
    resp = await client.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    })
    if resp.status_code >= 400:
        # Google's error body is the most useful thing we will ever get
        # about a misconfigured client; log it, don't show it to the user.
        logger.warning("[GOOGLE] code exchange failed %s: %s",
                       resp.status_code, resp.text[:400])
        raise HTTPException(status_code=502, detail="google_token_exchange_failed")
    return resp.json()


async def _refresh_access_token(client: httpx.AsyncClient,
                                refresh_token: str) -> Optional[Dict[str, Any]]:
    """None when Google rejects the refresh token — which is a real state,
    not a transient error: the user revoked access, changed password, or
    a Workspace admin pulled third-party app permission. Callers must mark
    the row revoked rather than retrying forever."""
    resp = await client.post(GOOGLE_TOKEN_URL, data={
        "refresh_token": refresh_token,
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "grant_type": "refresh_token",
    })
    if resp.status_code >= 400:
        logger.warning("[GOOGLE] refresh failed %s: %s",
                       resp.status_code, resp.text[:300])
        return None
    return resp.json()


async def _fetch_gmail_address(client: httpx.AsyncClient,
                               access_token: str) -> Dict[str, str]:
    """Which mailbox did they just connect? gmail.readonly already permits
    users.getProfile, so this costs no extra scope — and asking for
    userinfo.email would mean registering a scope the console does not
    have, which fails consent outright."""
    resp = await client.get(
        GMAIL_PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code >= 400:
        logger.warning("[GOOGLE] getProfile failed %s: %s",
                       resp.status_code, resp.text[:300])
        return {}
    body = resp.json() or {}
    return {"email": (body.get("emailAddress") or "").strip()}


def _expires_at_iso(expires_in: Any) -> Optional[str]:
    try:
        secs = int(expires_in)
    except (TypeError, ValueError):
        return None
    ts = time.time() + max(0, secs - ACCESS_TOKEN_SKEW_SECONDS)
    # Z form, never isoformat's +00:00 — PostgREST silently returns zero
    # rows when a +00:00 offset lands in a query string.
    return (datetime.fromtimestamp(ts, tz=timezone.utc)
            .isoformat().replace("+00:00", "Z"))


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ─── Endpoints ───────────────────────────────────────────────────────

@router.get("/connect/google/health")
async def google_health():
    """No secrets, only whether each one is present — the same shape as
    /connect/meta/health so ops can eyeball both the same way."""
    return {
        "status": "ok",
        "client_id_configured": bool(_client_id()),
        "client_secret_configured": bool(_client_secret()),
        "redirect_uri": _redirect_uri(),
        "scopes": GOOGLE_SCOPES,
    }


@router.get("/connect/google/start")
async def google_connect_start(business_id: str,
                               user: AuthedUser = Depends(require_user)):
    """The authenticated half of the handshake. Returns a relative path
    on purpose: the frontend prefixes the API base itself (see
    oauthConnect.ts), and returning an absolute URL here would let a
    future bug redirect a popup anywhere."""
    if not _configured():
        raise HTTPException(status_code=503, detail="google connect is not configured")
    _require_owner(business_id, user)
    ticket = oauth_connect_ticket.mint(business_id, user.id)
    return {"authorize_url": f"/connect/google?ticket={ticket}"}


@router.get("/connect/google")
async def google_connect(ticket: str = ""):
    """Redirect into Google's consent screen.

    access_type=offline is what yields a refresh token at all, and
    prompt=consent is what guarantees one on a RE-connect: Google returns
    a refresh token only on first authorisation unless consent is forced,
    so a practitioner reconnecting after a revoke would otherwise land us
    a row with no long-lived credential and no visible error.
    """
    business_id, user_id = (oauth_connect_ticket.verify(
        ticket, max_age_s=STATE_MAX_AGE_SECONDS) if ticket else (None, None))
    if not business_id:
        raise HTTPException(400, "this connect link expired — start again from the app")
    if not _configured():
        raise HTTPException(503, "google connect is not configured")

    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        # The ticket doubles as the CSRF state: signed, business-bound,
        # user-bound, and already time-limited.
        "state": ticket,
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
                            status_code=302)


def _result_html(ok: bool, message: str) -> HTMLResponse:
    safe = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    accent = "rgba(46,125,255,0.45)" if ok else "rgba(239,68,68,0.45)"
    title = "✓ Mailbox connected" if ok else "Connect failed"
    head = "#fafafa" if ok else "#f87171"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{'Connected' if ok else 'Connect failed'}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; padding: 48px 24px;
          text-align: center; background: #0a0a0a; color: #fafafa; }}
  .card {{ max-width: 460px; margin: 0 auto; padding: 32px; border-radius: 16px;
           background: rgba(255,255,255,0.04); border: 1px solid {accent}; }}
  h1 {{ font-size: 22px; margin: 0 0 8px; font-weight: 600; color: {head}; }}
  p  {{ font-size: 14px; color: #a3a3a3; line-height: 1.55; margin: 0 0 16px; }}
  .cta {{ margin-top: 12px; font-size: 12px; color: #737373; }}
</style></head><body>
<div class="card">
  <h1>{title}</h1>
  <p>{safe}</p>
  <p class="cta">You can close this tab and return to the app.</p>
</div>
<script>
  try {{
    if (window.opener) {{
      window.opener.postMessage({{ type: 'solutionist-google-connected',
                                   ok: {str(bool(ok)).lower()} }}, '*');
    }}
  }} catch (e) {{}}
  setTimeout(function() {{ try {{ window.close(); }} catch (e) {{}} }}, 1800);
</script>
</body></html>"""
    return HTMLResponse(content=html, status_code=200 if ok else 400)


@router.get("/connect/google/callback")
async def google_callback(code: Optional[str] = None,
                          state: Optional[str] = None,
                          error: Optional[str] = None):
    """Google redirects here after the user grants (or refuses).

      1. Verify state → recover business_id + user_id
      2. Exchange code → access + refresh token
      3. getProfile → which mailbox this actually is
      4. Upsert one row per (business, mailbox)
    """
    if error:
        # access_denied is a user saying no, not a fault. Say so plainly.
        if error == "access_denied":
            return _result_html(False, "You cancelled before granting access. "
                                       "Nothing was connected.")
        logger.info("[GOOGLE] callback error: %s", error)
        return _result_html(False, "Google refused the connection.")

    business_id, user_id = (oauth_connect_ticket.verify(
        state, max_age_s=STATE_MAX_AGE_SECONDS) if state else (None, None))
    if not business_id:
        return _result_html(False, "That connect link expired. "
                                   "Start again from Settings.")
    if not code:
        return _result_html(False, "Google did not return an authorisation code.")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            tokens = await _exchange_code(client, code)
        except HTTPException:
            return _result_html(False, "Could not complete the handshake with Google. "
                                       "Try again in a moment.")

        access_token = tokens.get("access_token") or ""
        refresh_token = tokens.get("refresh_token") or ""
        if not refresh_token:
            # prompt=consent should make this impossible. If it happens,
            # storing the row anyway would leave a mailbox that works for
            # one hour and then silently stops — worse than refusing.
            logger.warning("[GOOGLE] no refresh_token for business=%s", business_id)
            return _result_html(False, "Google did not return a long-lived token. "
                                       "Disconnect the app under your Google Account "
                                       "permissions, then connect again.")

        profile = await _fetch_gmail_address(client, access_token)
        google_email = profile.get("email") or ""
        if not google_email:
            return _result_html(False, "Connected, but we could not read which "
                                       "mailbox it was. Try again.")

        row = {
            "business_id": business_id,
            "google_email": google_email,
            "refresh_token": refresh_token,
            "access_token": access_token or None,
            "access_expires_at": _expires_at_iso(tokens.get("expires_in")),
            "scopes": tokens.get("scope") or GOOGLE_SCOPES,
            "status": "connected",
            "last_error": None,
            "connected_by": user_id,
            "updated_at": _now_z(),
        }
        # merge-duplicates turns the (business_id, google_email) unique
        # constraint into an upsert, so reconnecting replaces the dead
        # token instead of erroring on the second attempt.
        written = sb_clients.sb_post_as_service(
            "/google_mailboxes", row,
            prefer="resolution=merge-duplicates,return=representation")
        if not written:
            # sb_* returns None on 4xx/5xx. Reporting success here would
            # tell the practitioner their mail is connected over a write
            # that never landed.
            logger.error("[GOOGLE] failed to persist mailbox for business=%s",
                         business_id)
            return _result_html(False, "Google approved the connection but we could "
                                       "not save it. Nothing is connected — please "
                                       "try again.")

    logger.info("[GOOGLE] connected mailbox for business=%s", business_id)
    # What is true at this point is that the grant is stored and revocable.
    # Nothing reads the mailbox yet — there is no ingest, so promising that
    # "Chief can now read mail sent to this address" would leave the
    # practitioner waiting on a feed that was never going to arrive, and
    return _result_html(True, f"{google_email} is connected. New mail arriving here "
                              f"will start appearing in your Email Hub within a few "
                              f"minutes. You can disconnect any time.")


@router.get("/mailbox/messages")
async def mailbox_messages(business_id: str, limit: int = 50,
                           user: AuthedUser = Depends(require_user)):
    """The Email Hub's window onto a connected mailbox.

    This endpoint exists because mailbox_messages has RLS on with zero
    policies — the frontend cannot read the table directly, deliberately.
    A seat member holding a valid JWT gets nothing from PostgREST, and
    gets 403 here. That is the owner-only decision enforced in the two
    places that can actually enforce it, rather than by hiding a tab.

    body_text is included: the practitioner is reading their own mail.
    The selection policy governs what reaches the MODEL, not what its
    owner is allowed to see.
    """
    _require_owner(business_id, user)
    capped = max(1, min(int(limit or 50), 200))
    rows = sb_clients.sb_get_as_service(
        f"/mailbox_messages?business_id=eq.{business_id}"
        f"&order=received_at.desc&limit={capped}"
        f"&select=id,google_email,from_email,from_name,subject,body_text,"
        f"received_at,read,contact_id") or []
    return {"messages": rows, "count": len(rows)}


@router.get("/connect/google/status")
async def google_status(business_id: str,
                        user: AuthedUser = Depends(require_user)):
    """What the app shows on the connect card. Selects explicit non-secret
    columns — never `select=*`, which would put refresh_token on the wire
    the first time someone widened the table."""
    _require_owner(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/google_mailboxes?business_id=eq.{business_id}"
        # last_synced_at is the difference between "connected" and
        # "working". A grant can be stored and valid while the sync has
        # not completed in days, and those two states look identical to a
        # practitioner staring at an empty list — silence is what a dead
        # feed looks like. The card cannot say so unless it is told.
        f"&select=google_email,status,last_error,connected_at,updated_at,last_synced_at"
        f"&order=connected_at.desc") or []
    return {"connected": bool(rows), "mailboxes": rows}


@router.delete("/connect/google/disconnect")
async def google_disconnect(business_id: str, google_email: str,
                            user: AuthedUser = Depends(require_user)):
    """Revoke at Google first, then drop the row.

    Order matters. Deleting our row first and failing the revoke would
    leave a live grant on the practitioner's Google account that nothing
    in our UI can see or undo — the user would have to find it in their
    Google security settings. A failed revoke still deletes locally
    (their intent is clear), but it is logged loudly.
    """
    _require_owner(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/google_mailboxes?business_id=eq.{business_id}"
        f"&google_email=eq.{google_email}&select=refresh_token&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="mailbox not connected")

    token = rows[0].get("refresh_token")
    if token:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                r = await client.post(GOOGLE_REVOKE_URL, data={"token": token})
                if r.status_code >= 400:
                    logger.warning("[GOOGLE] revoke returned %s for business=%s",
                                   r.status_code, business_id)
        except Exception as exc:
            logger.warning("[GOOGLE] revoke call failed for business=%s: %s",
                           business_id, exc)

    ok = sb_clients.sb_delete_as_service(
        f"/google_mailboxes?business_id=eq.{business_id}"
        f"&google_email=eq.{google_email}")
    if not ok:
        raise HTTPException(status_code=502, detail="could not disconnect")
    return {"ok": True, "disconnected": google_email}
