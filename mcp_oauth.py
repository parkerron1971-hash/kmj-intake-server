"""
mcp_oauth.py — OAuth 2.1 in front of the MCP surface.

WHY THIS EXISTS
  Stage 1's credential is a bearer token pasted into a local config file.
  That is fine for Claude Code on a laptop and cannot work anywhere else:
  claude.ai's custom-connector dialog speaks OAuth, and remote MCP is the
  only kind a phone can use — an iOS or Android app cannot run a local
  server. No OAuth, no phone. That is the whole motivation.

WHAT THIS IS NOT
  It is NOT a second credential system. The access token handed back by
  /oauth/token is an ordinary `mcp_tokens` credential: same HMAC format,
  same table, same revocation, same row in Mission Control → Agent Access.
  This module is a way to OBTAIN one. `mcp_server._caller_from_token`
  required no change whatsoever, which is the strongest available evidence
  that the seam is in the right place.

HOW THE OWNER PROVES IT IS THEM
  By pasting a live Agent Access key into the consent screen.

  The alternative designs were a password form on this service (a public,
  phishable surface guarding something a revocable key already guards) or
  a bounce through the Vercel app's Supabase session (correct, and the
  right answer when this opens to customers, but two repos and two deploys
  to debug from a phone). Reusing the existing credential adds no new
  authentication surface at all: the key is already revocable, already
  named, already audited, and already the thing that grants this access.

  This does NOT generalise to customers. Stage 4 needs real per-user
  login. Single tenant is what makes this acceptable, and the moment a
  second tenant exists it stops being.

OPEN DYNAMIC REGISTRATION IS SAFE HERE
  RFC 7591 registration is unauthenticated, per spec, so Claude.ai can
  register itself instead of the owner hand-managing a client secret.
  Registering grants nothing: every authorization code still requires a
  live Agent Access key at the consent screen. An attacker who registers
  a client has a client_id and no way to get a code. Rate-limited anyway.

FAIL CLOSED
  Every ambiguous case resolves to refusal — an unreadable table, a
  malformed claim, a missing secret. Same posture as `mcp_tokens`, for the
  same reason: this is the surface where being wrong is expensive.
"""
from __future__ import annotations

import base64
import hashlib
import html
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import rate_limit
import sb_clients

logger = logging.getLogger("mcp_oauth")

router = APIRouter(tags=["mcp-oauth"])

# ─── Lifetimes ───────────────────────────────────────────────────────
# Codes are seconds, not minutes: the exchange happens immediately and a
# longer window is pure exposure.
CODE_TTL_SECONDS = 60
ACCESS_TTL_DAYS = 90
REFRESH_TTL_DAYS = 365

SCOPE_READ = "read"
SUPPORTED_SCOPES = (SCOPE_READ,)

DEFAULT_BASE_URL = "https://kmj-intake-server-production.up.railway.app"


def base_url() -> str:
    """The public origin, for metadata documents and redirects.

    An env var rather than the request's Host header on purpose: metadata
    that echoes an attacker-supplied Host is a redirect-to-anywhere waiting
    to happen, and these documents are what a client trusts to decide where
    to send the owner to log in.
    """
    return (os.environ.get("MCP_PUBLIC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def enabled() -> bool:
    """Rides the same kill switch as the surface it guards. Turning the MCP
    surface off while leaving a way to mint credentials for it open would be
    a strange definition of 'off'."""
    try:
        import mcp_server
        return mcp_server.enabled()
    except Exception:
        return (os.environ.get("MCP_ENABLED") or "on").strip().lower() not in (
            "off", "false", "0", "no")


# ─── Small helpers ───────────────────────────────────────────────────

def _sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _err(status: int, code: str, description: str) -> JSONResponse:
    """RFC 6749 §5.2 error shape, with caching disabled — these responses
    carry authorization decisions and must never be reused."""
    return JSONResponse(
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        content={"error": code, "error_description": description})


def _redirect_uri_is_registered(uri: str, registered: List[str]) -> bool:
    """Exact string match, deliberately.

    Prefix or wildcard matching on redirect URIs is the classic way an
    authorization server becomes an open redirect: `https://good.com` as a
    prefix also matches `https://good.com.evil.test`. The client registered
    its exact URIs; it can use exactly those.
    """
    return isinstance(uri, str) and uri in (registered or [])


# ─── Storage ─────────────────────────────────────────────────────────
# Every reader returns None on failure rather than raising, and every
# caller treats None as refusal. A database blip must not authorise.

def _get_client(client_id: str) -> Optional[Dict[str, Any]]:
    if not client_id:
        return None
    try:
        rows = sb_clients.sb_get_as_service(
            f"/mcp_oauth_clients?client_id=eq.{client_id}&limit=1")
    except Exception as e:
        logger.warning("[mcp_oauth] client lookup failed: %s", e)
        return None
    if not rows:
        return None
    return rows[0]


def _store_code(*, code: str, client_id: str, redirect_uri: str,
                code_challenge: str, business_id: str, scope: str) -> bool:
    try:
        sb_clients.sb_post_as_service("/mcp_oauth_codes", {
            "code_hash": _sha256(code),
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "business_id": business_id,
            "scope": scope,
            "expires_at": _iso(_now() + timedelta(seconds=CODE_TTL_SECONDS)),
        }, prefer="return=minimal")
        return True
    except Exception as e:
        logger.warning("[mcp_oauth] code store failed: %s", e)
        return False


def _consume_code(code: str) -> Optional[Dict[str, Any]]:
    """Fetch a code row and mark it used. Returns None if it is missing,
    expired, or already consumed.

    The consume-stamp is written BEFORE the caller does anything with the
    row, so two simultaneous exchanges cannot both succeed on the optimistic
    path. PostgREST returns the updated rows, and an empty result means
    somebody else got there first.
    """
    h = _sha256(code)
    try:
        rows = sb_clients.sb_get_as_service(
            f"/mcp_oauth_codes?code_hash=eq.{h}&limit=1")
    except Exception as e:
        logger.warning("[mcp_oauth] code lookup failed: %s", e)
        return None
    if not rows:
        return None
    row = rows[0]
    if row.get("consumed_at"):
        logger.warning("[mcp_oauth] REPLAY: code already consumed (client=%s)",
                       row.get("client_id"))
        return None
    try:
        expires = datetime.fromisoformat(
            str(row.get("expires_at")).replace("Z", "+00:00"))
    except Exception:
        return None
    if expires <= _now():
        return None
    try:
        updated = sb_clients.sb_patch_as_service(
            f"/mcp_oauth_codes?code_hash=eq.{h}&consumed_at=is.null",
            {"consumed_at": _iso(_now())})
    except Exception as e:
        logger.warning("[mcp_oauth] code consume failed: %s", e)
        return None
    if updated is not None and isinstance(updated, list) and not updated:
        # Somebody consumed it between the read and the write.
        logger.warning("[mcp_oauth] RACE: code consumed concurrently")
        return None
    return row


def _store_refresh(*, token: str, client_id: str, business_id: str,
                   scope: str, access_jti: str) -> bool:
    try:
        sb_clients.sb_post_as_service("/mcp_oauth_refresh", {
            "token_hash": _sha256(token),
            "client_id": client_id,
            "business_id": business_id,
            "scope": scope,
            "access_jti": access_jti,
            "expires_at": _iso(_now() + timedelta(days=REFRESH_TTL_DAYS)),
        }, prefer="return=minimal")
        return True
    except Exception as e:
        logger.warning("[mcp_oauth] refresh store failed: %s", e)
        return False


def _consume_refresh(token: str) -> Optional[Dict[str, Any]]:
    """Rotation. Same single-use discipline as codes.

    A replayed refresh token finds a row with `consumed_at` already set —
    which is not merely useless to the attacker, it is a signal, logged
    loudly, that a credential has been copied.
    """
    h = _sha256(token)
    try:
        rows = sb_clients.sb_get_as_service(
            f"/mcp_oauth_refresh?token_hash=eq.{h}&limit=1")
    except Exception as e:
        logger.warning("[mcp_oauth] refresh lookup failed: %s", e)
        return None
    if not rows:
        return None
    row = rows[0]
    if row.get("consumed_at"):
        logger.warning("[mcp_oauth] REPLAY: refresh token reused (client=%s)",
                       row.get("client_id"))
        return None
    if row.get("revoked_at"):
        return None
    try:
        expires = datetime.fromisoformat(
            str(row.get("expires_at")).replace("Z", "+00:00"))
    except Exception:
        return None
    if expires <= _now():
        return None

    # The owner's kill switch. If the access token this chain last issued
    # has been revoked in Agent Access, the chain is dead — otherwise
    # "revoke" would leave the phone quietly working off a refresh token.
    jti = str(row.get("access_jti") or "")
    if jti:
        try:
            import mcp_tokens
            if mcp_tokens.is_revoked(jti):
                logger.info("[mcp_oauth] refresh refused — access jti %s revoked", jti)
                return None
        except Exception as e:
            logger.warning("[mcp_oauth] revocation check failed, refusing: %s", e)
            return None

    try:
        updated = sb_clients.sb_patch_as_service(
            f"/mcp_oauth_refresh?token_hash=eq.{h}&consumed_at=is.null",
            {"consumed_at": _iso(_now())})
    except Exception as e:
        logger.warning("[mcp_oauth] refresh consume failed: %s", e)
        return None
    if updated is not None and isinstance(updated, list) and not updated:
        logger.warning("[mcp_oauth] RACE: refresh consumed concurrently")
        return None
    return row


# ─── Discovery documents ─────────────────────────────────────────────
# Both are unauthenticated by design: a client cannot authenticate until
# it has read them, and neither says anything about the business.

def _protected_resource_doc() -> Dict[str, Any]:
    b = base_url()
    return {
        "resource": f"{b}/mcp",
        "authorization_servers": [b],
        "scopes_supported": list(SUPPORTED_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{b}/mcp/health",
    }


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata():
    """RFC 9728. The 401 from /mcp points here; this points at the
    authorization server. That chain is how a client that knows only a URL
    discovers where to send the owner to log in."""
    return JSONResponse(content=_protected_resource_doc(),
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource_metadata_scoped():
    """The path-suffixed form. Clients derive the metadata URL from the
    resource path and differ on which form they try; serving both costs one
    route and removes a whole class of 'it just says failed'."""
    return JSONResponse(content=_protected_resource_doc(),
                        headers={"Cache-Control": "public, max-age=3600"})


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata():
    """RFC 8414."""
    b = base_url()
    return JSONResponse(
        headers={"Cache-Control": "public, max-age=3600"},
        content={
            "issuer": b,
            "authorization_endpoint": f"{b}/oauth/authorize",
            "token_endpoint": f"{b}/oauth/token",
            "registration_endpoint": f"{b}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            # S256 only. 'plain' defeats the point of PKCE and OAuth 2.1
            # drops it; advertising it would invite a client to use it.
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
            "scopes_supported": list(SUPPORTED_SCOPES),
            "service_documentation": f"{b}/mcp/health",
        })


# ─── Dynamic client registration (RFC 7591) ──────────────────────────

class _RegisterBody(BaseModel):
    client_name: Optional[str] = None
    redirect_uris: Optional[List[str]] = None
    grant_types: Optional[List[str]] = None
    response_types: Optional[List[str]] = None
    token_endpoint_auth_method: Optional[str] = None
    scope: Optional[str] = None


@router.post("/oauth/register")
async def register_client(body: _RegisterBody, request: Request):
    """Register a client. Unauthenticated, per RFC 7591 and per what
    claude.ai expects.

    This is safe because registration is not authorization. The client_id
    it returns is a name, not a permission: no code is ever issued without
    the owner pasting a live Agent Access key. Rate-limited so it cannot be
    used to fill a table.
    """
    if not enabled():
        return _err(503, "temporarily_unavailable", "MCP surface is disabled")

    ip = rate_limit.client_ip(request)
    if not rate_limit.allow_strict("mcp_oauth_register", ip):
        return _err(429, "temporarily_unavailable", "rate limit exceeded")

    uris = [u for u in (body.redirect_uris or []) if isinstance(u, str) and u]
    if not uris:
        return _err(400, "invalid_redirect_uri", "redirect_uris is required")
    for u in uris:
        parts = urlsplit(u)
        # https, or a loopback/custom scheme for native clients. Plain http
        # to a remote host would put an authorization code on the wire.
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            return _err(400, "invalid_redirect_uri",
                        "http redirect URIs are only allowed on loopback")
        if not parts.scheme:
            return _err(400, "invalid_redirect_uri", f"malformed redirect_uri: {u}")

    client_id = f"mcpc_{secrets.token_urlsafe(18)}"
    name = (body.client_name or "unnamed")[:120]
    try:
        sb_clients.sb_post_as_service("/mcp_oauth_clients", {
            "client_id": client_id,
            "client_secret_hash": None,   # public client — PKCE is the proof
            "client_name": name,
            "redirect_uris": uris,
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning("[mcp_oauth] registration failed: %s", e)
        return _err(500, "server_error", "could not register client")

    logger.info("[mcp_oauth] registered client %s (%r)", client_id, name)
    return JSONResponse(
        status_code=201,
        headers={"Cache-Control": "no-store"},
        content={
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "client_name": name,
            "redirect_uris": uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE_READ,
        })


# ─── Consent screen ──────────────────────────────────────────────────

_CONSENT_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; display:flex; align-items:center;
  justify-content:center; background:#0b0d10; color:#e8eaed;
  font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  padding:24px; }
.card { width:100%; max-width:420px; background:#14171c; border:1px solid #242932;
  border-radius:16px; padding:28px; }
h1 { margin:0 0 6px; font-size:19px; letter-spacing:-0.01em; }
p { margin:0 0 18px; color:#9aa3af; font-size:14px; }
.grant { background:#0f1216; border:1px solid #242932; border-radius:10px;
  padding:12px 14px; margin:0 0 18px; font-size:13.5px; color:#c3cad4; }
.grant b { color:#e8eaed; font-weight:600; }
label { display:block; font-size:13px; color:#9aa3af; margin:0 0 7px; }
input { width:100%; padding:11px 13px; border-radius:9px; border:1px solid #2c323c;
  background:#0f1216; color:#e8eaed; font-size:14px; font-family:ui-monospace,monospace; }
input:focus { outline:none; border-color:#2E7DFF; }
.row { display:flex; gap:10px; margin-top:20px; }
button { flex:1; padding:11px 16px; border-radius:9px; font-size:14px;
  font-weight:600; cursor:pointer; border:1px solid transparent; }
.approve { background:#2E7DFF; color:#fff; }
.deny { background:transparent; color:#9aa3af; border-color:#2c323c; }
.err { background:#2a1416; border:1px solid #5b2a2f; color:#ffb4b4;
  padding:10px 13px; border-radius:9px; margin:0 0 16px; font-size:13.5px; }
.foot { margin:18px 0 0; font-size:12px; color:#6b7280; }
"""


def _consent_page(*, client_name: str, params: Dict[str, str],
                  error: Optional[str] = None) -> HTMLResponse:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in params.items() if v)
    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorize access</title><style>{_CONSENT_CSS}</style></head>
<body><form class="card" method="post" action="/oauth/authorize" autocomplete="off">
{hidden}
<h1>Authorize access</h1>
<p><b>{html.escape(client_name)}</b> is asking to connect to your Solutionist
business.</p>
{err_html}
<div class="grant"><b>Read-only.</b> It can see contacts, revenue, pipeline and
site data. It cannot send, charge, delete, or change anything.</div>
<label for="key">Paste an Agent Access key</label>
<input id="key" name="agent_key" type="password" required autofocus
       placeholder="from Mission Control → Agent Access" spellcheck="false">
<div class="row">
  <button class="deny" type="submit" name="decision" value="deny">Deny</button>
  <button class="approve" type="submit" name="decision" value="approve">Approve</button>
</div>
<p class="foot">Revoke any time in Mission Control → Agent Access.</p>
</form></body></html>"""
    return HTMLResponse(
        content=body,
        headers={
            "Cache-Control": "no-store",
            # A consent screen in an iframe is a clickjacking target.
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
        })


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(status_code=status, headers={"Cache-Control": "no-store"},
                        content=f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cannot authorize</title><style>{_CONSENT_CSS}</style></head>
<body><div class="card"><h1>Cannot authorize</h1>
<div class="err">{html.escape(message)}</div>
<p class="foot">Nothing was granted. Close this window and try connecting again.</p>
</div></body></html>""")


def _redirect_error(redirect_uri: str, state: str, code: str,
                    description: str) -> RedirectResponse:
    q = {"error": code, "error_description": description}
    if state:
        q["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(q)}",
                            status_code=302,
                            headers={"Cache-Control": "no-store"})


@router.get("/oauth/authorize")
async def authorize_get(request: Request):
    """Render consent.

    The ordering here is a security property, not a style choice. Until the
    client_id and redirect_uri are both known-good, errors render as a page.
    Redirecting an error to an unvalidated URI would hand the request's
    parameters to whoever supplied it.
    """
    if not enabled():
        return _error_page("This service is not accepting connections right now.", 503)

    q = request.query_params
    client_id = (q.get("client_id") or "").strip()
    redirect_uri = (q.get("redirect_uri") or "").strip()
    state = (q.get("state") or "").strip()
    challenge = (q.get("code_challenge") or "").strip()
    method = (q.get("code_challenge_method") or "").strip()
    response_type = (q.get("response_type") or "").strip()

    client = _get_client(client_id)
    if not client:
        return _error_page("Unknown client. Remove the connector and add it again.")
    if not _redirect_uri_is_registered(redirect_uri, client.get("redirect_uris") or []):
        return _error_page("This redirect URI is not registered for that client.")

    # From here the redirect target is trusted, so errors may travel to it.
    if response_type != "code":
        return _redirect_error(redirect_uri, state, "unsupported_response_type",
                               "only response_type=code is supported")
    if not challenge:
        return _redirect_error(redirect_uri, state, "invalid_request",
                               "PKCE is required (code_challenge missing)")
    if method != "S256":
        return _redirect_error(redirect_uri, state, "invalid_request",
                               "code_challenge_method must be S256")

    return _consent_page(
        client_name=str(client.get("client_name") or "An application"),
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": method,
            "scope": (q.get("scope") or SCOPE_READ).strip(),
        })


@router.post("/oauth/authorize")
async def authorize_post(
    request: Request,
    client_id: str = Form(""),
    redirect_uri: str = Form(""),
    state: str = Form(""),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form(""),
    scope: str = Form(SCOPE_READ),
    agent_key: str = Form(""),
    decision: str = Form(""),
):
    """The owner's answer.

    Re-validates everything the GET validated. The hidden fields came back
    from a browser and are therefore caller-supplied input, not state we
    remembered — trusting them because we rendered them once is exactly how
    a validated redirect_uri becomes an unvalidated one.
    """
    if not enabled():
        return _error_page("This service is not accepting connections right now.", 503)

    client = _get_client(client_id)
    if not client:
        return _error_page("Unknown client. Remove the connector and add it again.")
    if not _redirect_uri_is_registered(redirect_uri, client.get("redirect_uris") or []):
        return _error_page("This redirect URI is not registered for that client.")

    if decision != "approve":
        return _redirect_error(redirect_uri, state, "access_denied",
                               "the owner declined")

    if code_challenge_method != "S256" or not code_challenge:
        return _redirect_error(redirect_uri, state, "invalid_request",
                               "PKCE (S256) is required")

    # Brute-forcing the consent form is the one way in that does not need a
    # key already, so it gets the strict limiter keyed by IP.
    ip = rate_limit.client_ip(request)
    if not rate_limit.allow_strict("mcp_oauth_consent", ip):
        return _consent_page(
            client_name=str(client.get("client_name") or "An application"),
            params={"client_id": client_id, "redirect_uri": redirect_uri,
                    "state": state, "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method, "scope": scope},
            error="Too many attempts. Wait a minute and try again.")

    import mcp_tokens
    claims = mcp_tokens.verify_mcp_token((agent_key or "").strip())
    if not claims or mcp_tokens.is_revoked(str(claims.get("jti") or "")):
        logger.warning("[mcp_oauth] consent refused — bad or revoked key from %s", ip)
        return _consent_page(
            client_name=str(client.get("client_name") or "An application"),
            params={"client_id": client_id, "redirect_uri": redirect_uri,
                    "state": state, "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method, "scope": scope},
            error="That key is not valid, has expired, or was revoked.")

    business_id = str(claims.get("biz") or "")
    if not business_id:
        return _redirect_error(redirect_uri, state, "server_error",
                               "that key names no business")

    code = secrets.token_urlsafe(32)
    if not _store_code(code=code, client_id=client_id, redirect_uri=redirect_uri,
                       code_challenge=code_challenge, business_id=business_id,
                       scope=SCOPE_READ):
        return _redirect_error(redirect_uri, state, "server_error",
                               "could not issue an authorization code")

    logger.info("[mcp_oauth] code issued to %s for business %s", client_id, business_id)
    q = {"code": code}
    if state:
        q["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(q)}",
                            status_code=302,
                            headers={"Cache-Control": "no-store"})


# ─── Token endpoint ──────────────────────────────────────────────────

def _issue(business_id: str, client_id: str, label_hint: str) -> Optional[Dict[str, Any]]:
    """Mint an access token and a fresh refresh token.

    The access token is an ordinary `mcp_tokens` row, which is what makes it
    appear in Agent Access alongside hand-minted keys and revoke by the same
    button. There is no OAuth-specific credential to reason about separately.
    """
    import mcp_tokens
    try:
        token, row = mcp_tokens.mint(
            business_id,
            label=f"OAuth · {label_hint}"[:120],
            ttl_seconds=ACCESS_TTL_DAYS * 24 * 60 * 60,
            created_by=f"oauth:{client_id}")
    except Exception as e:
        logger.warning("[mcp_oauth] mint failed: %s", e)
        return None

    refresh = secrets.token_urlsafe(40)
    if not _store_refresh(token=refresh, client_id=client_id,
                          business_id=business_id, scope=SCOPE_READ,
                          access_jti=row["jti"]):
        # An access token without a working refresh would look fine for 90
        # days and then fail with no explanation. Refuse now instead.
        return None

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL_DAYS * 24 * 60 * 60,
        "refresh_token": refresh,
        "scope": SCOPE_READ,
    }


@router.post("/oauth/token")
async def token_endpoint(
    request: Request,
    grant_type: str = Form(""),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
    code_verifier: str = Form(""),
    refresh_token: str = Form(""),
):
    if not enabled():
        return _err(503, "temporarily_unavailable", "MCP surface is disabled")

    ip = rate_limit.client_ip(request)
    if not rate_limit.allow_strict("mcp_oauth_token", ip):
        return _err(429, "temporarily_unavailable", "rate limit exceeded")

    # ── refresh_token grant ──
    if grant_type == "refresh_token":
        if not refresh_token:
            return _err(400, "invalid_request", "refresh_token is required")
        row = _consume_refresh(refresh_token)
        if not row:
            return _err(400, "invalid_grant",
                        "refresh token is invalid, expired, already used, or revoked")
        if client_id and str(row.get("client_id")) != client_id:
            return _err(400, "invalid_grant", "refresh token was issued to another client")
        issued = _issue(str(row.get("business_id")), str(row.get("client_id")),
                        "refreshed")
        if not issued:
            return _err(500, "server_error", "could not issue a token")
        return JSONResponse(headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                            content=issued)

    # ── authorization_code grant ──
    if grant_type != "authorization_code":
        return _err(400, "unsupported_grant_type",
                    "only authorization_code and refresh_token are supported")
    if not code or not code_verifier:
        return _err(400, "invalid_request", "code and code_verifier are required")

    row = _consume_code(code)
    if not row:
        return _err(400, "invalid_grant", "code is invalid, expired, or already used")

    if client_id and str(row.get("client_id")) != client_id:
        return _err(400, "invalid_grant", "code was issued to another client")
    # RFC 6749 §4.1.3: the redirect_uri must match the one used to obtain
    # the code, so a code stolen from one client cannot be redeemed against
    # another registration.
    if redirect_uri and str(row.get("redirect_uri")) != redirect_uri:
        return _err(400, "invalid_grant", "redirect_uri does not match the code")

    # PKCE. This is what proves the caller is the same party that started
    # the flow — without it, an intercepted code is enough on its own.
    expected = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    if not secrets.compare_digest(expected, str(row.get("code_challenge") or "")):
        logger.warning("[mcp_oauth] PKCE verification FAILED for client %s",
                       row.get("client_id"))
        return _err(400, "invalid_grant", "code_verifier does not match")

    issued = _issue(str(row.get("business_id")), str(row.get("client_id")),
                    "authorized")
    if not issued:
        return _err(500, "server_error", "could not issue a token")

    logger.info("[mcp_oauth] access token issued to %s", row.get("client_id"))
    return JSONResponse(headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                        content=issued)
