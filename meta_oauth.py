"""
meta_oauth.py — Meta (Facebook + Instagram) OAuth + publishing.

Endpoints exposed:
  GET  /connect/meta?business_id=...       → redirect to Facebook OAuth
  GET  /connect/meta/callback              → code → long-lived token →
                                              Page tokens → upsert rows
                                              in social_accounts
  GET  /connect/meta/pages?business_id=... → list connected pages (no token)
  DELETE /connect/meta/disconnect?business_id=...&page_id=...
  POST /publish                            → publish to a connected Page,
                                              optionally also to Instagram
  GET  /connect/meta/health                → quick env-config check

═══════════════════════════════════════════════════════════════════════
ARCHITECTURE
═══════════════════════════════════════════════════════════════════════

One Meta app serves all tenants. Each practitioner runs OAuth, grants
access to their Page, and we store the long-lived Page token keyed by
business_id. The browser NEVER sees the token — only page_name +
ig_user_id + status.

Tenant isolation is enforced by always filtering by business_id at the
application layer (Supabase RLS is permissive, same as the rest of the
app).

═══════════════════════════════════════════════════════════════════════
ENV VARS REQUIRED
═══════════════════════════════════════════════════════════════════════

  META_APP_ID            — Meta app ID (public, but we keep it server-side)
  META_APP_SECRET        — Meta app secret (NEVER goes to the client)
  META_REDIRECT_URI      — Must MATCH what's configured in Meta Dashboard
                            → Facebook Login for Business → Settings →
                            Valid OAuth Redirect URIs. Example:
                            https://kmj-intake-server-production.up.railway.app/connect/meta/callback
  META_OAUTH_STATE_SECRET — HMAC key for CSRF protection on state param.
                            Any long random string; generated once.
  META_FRONTEND_RETURN_URL — Where to redirect the user's browser after
                              callback success/error. e.g. https://app.example.com/settings?meta=connected
                              (the app then closes the tab or polls).

═══════════════════════════════════════════════════════════════════════
META DASHBOARD CONFIG (one-time)
═══════════════════════════════════════════════════════════════════════

  1. Facebook Login for Business → Settings →
     Valid OAuth Redirect URIs: <https>://<railway>/connect/meta/callback
  2. Required permissions:
       pages_show_list
       pages_manage_posts
       pages_read_engagement
       instagram_basic
       instagram_content_publish
       business_management
  3. Dev mode: only Meta app admins/testers can complete OAuth.
     For public launch: Business Verification + App Review.

═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

FB_GRAPH = "https://graph.facebook.com/v21.0"
FB_OAUTH = "https://www.facebook.com/v21.0/dialog/oauth"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

# All five scopes the Meta brief calls out, plus business_management
# for selecting Business assets in the OAuth dialog.
META_SCOPES = ",".join([
    "pages_show_list",
    "pages_manage_posts",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_content_publish",
    "business_management",
])

# State lives for 10 minutes — long enough for a deliberate user but
# short enough that a stolen state can't be replayed indefinitely.
STATE_MAX_AGE_SECONDS = 10 * 60

logger = logging.getLogger("meta_oauth")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] meta: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["meta"])


# ─── Env helpers ─────────────────────────────────────────────────────

def _meta_app_id() -> str:
    v = os.environ.get("META_APP_ID", "")
    if not v:
        raise HTTPException(500, "META_APP_ID not configured")
    return v

def _meta_app_secret() -> str:
    v = os.environ.get("META_APP_SECRET", "")
    if not v:
        raise HTTPException(500, "META_APP_SECRET not configured")
    return v

def _meta_redirect_uri() -> str:
    v = os.environ.get("META_REDIRECT_URI", "")
    if not v:
        raise HTTPException(500, "META_REDIRECT_URI not configured")
    return v

def _state_secret() -> str:
    v = os.environ.get("META_OAUTH_STATE_SECRET", "")
    if not v:
        # Without this set, OAuth would be CSRF-vulnerable. Fail loudly.
        raise HTTPException(500, "META_OAUTH_STATE_SECRET not configured")
    return v

def _frontend_return_url(default: str = "/") -> str:
    return os.environ.get("META_FRONTEND_RETURN_URL", default)


# ─── State signing (CSRF protection, stateless) ─────────────────────

def _make_state(business_id: str) -> str:
    """Build a signed state token: base64(json{business_id, ts}).sig.
    No server-side storage needed — verified by HMAC on the way back."""
    payload = {"business_id": business_id, "ts": int(time.time())}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(_state_secret().encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"

def _parse_state(token: str) -> Dict[str, Any]:
    """Reverse of _make_state. Raises on tamper / expiry."""
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise HTTPException(400, "malformed state")
    expected = hmac.new(_state_secret().encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(400, "state signature mismatch")
    try:
        padding = "=" * (-len(body) % 4)
        raw = base64.urlsafe_b64decode(body + padding)
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "state payload corrupt")
    if not isinstance(payload, dict) or "business_id" not in payload or "ts" not in payload:
        raise HTTPException(400, "state missing fields")
    if time.time() - int(payload["ts"]) > STATE_MAX_AGE_SECONDS:
        raise HTTPException(400, "state expired — please reconnect")
    return payload


# ─── Supabase helpers ──────────────────────────────────────────────

async def _sb(client: httpx.AsyncClient, method: str, path: str, body=None) -> Any:
    url = f"{os.environ.get('SUPABASE_URL', '')}/rest/v1{path}"
    headers = {
        "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    r = await client.request(method, url, headers=headers,
                             content=json.dumps(body) if body else None,
                             timeout=HTTP_TIMEOUT)
    if r.status_code >= 400:
        logger.error(f"supabase {method} {path}: {r.status_code} {r.text[:300]}")
        return None
    return r.json() if r.text else None


# ─── Meta Graph API helpers ────────────────────────────────────────

async def _exchange_short_for_long(client: httpx.AsyncClient, short_token: str) -> str:
    """Trade a short-lived user token for a long-lived one (~60 days)."""
    r = await client.get(
        f"{FB_GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": _meta_app_id(),
            "client_secret": _meta_app_secret(),
            "fb_exchange_token": short_token,
        },
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"Meta long-lived exchange failed: {r.text[:300]}")
    data = r.json()
    return data.get("access_token", "")


async def _list_pages(client: httpx.AsyncClient, user_token: str) -> List[Dict[str, Any]]:
    """Fetch /me/accounts — returns the Pages the user manages, each
    with its own Page token. The Page tokens inherit long-lived status
    from the user token."""
    r = await client.get(
        f"{FB_GRAPH}/me/accounts",
        params={
            "access_token": user_token,
            "fields": "id,name,access_token,instagram_business_account",
        },
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"Meta /me/accounts failed: {r.text[:300]}")
    data = r.json() or {}
    return list(data.get("data") or [])


async def _publish_facebook(client: httpx.AsyncClient, page_id: str, page_token: str,
                            message: str, image_url: Optional[str]) -> Dict[str, Any]:
    """Post to a Page. Text-only uses /feed; with image uses /photos."""
    if image_url:
        endpoint = f"{FB_GRAPH}/{page_id}/photos"
        params = {"access_token": page_token, "url": image_url, "caption": message}
    else:
        endpoint = f"{FB_GRAPH}/{page_id}/feed"
        params = {"access_token": page_token, "message": message}
    r = await client.post(endpoint, params=params, timeout=HTTP_TIMEOUT)
    if r.status_code >= 400:
        raise HTTPException(502, f"FB publish failed: {r.text[:300]}")
    return r.json()


async def _publish_instagram(client: httpx.AsyncClient, ig_user_id: str, page_token: str,
                             caption: str, image_url: str) -> Dict[str, Any]:
    """Instagram 2-step container flow. Requires a PUBLIC image URL
    that Meta can fetch."""
    # 1. Create the media container
    c = await client.post(
        f"{FB_GRAPH}/{ig_user_id}/media",
        params={"access_token": page_token, "image_url": image_url, "caption": caption},
        timeout=HTTP_TIMEOUT,
    )
    if c.status_code >= 400:
        raise HTTPException(502, f"IG container failed: {c.text[:300]}")
    container_id = c.json().get("id")
    if not container_id:
        raise HTTPException(502, "IG container returned no id")
    # 2. Publish the container
    p = await client.post(
        f"{FB_GRAPH}/{ig_user_id}/media_publish",
        params={"access_token": page_token, "creation_id": container_id},
        timeout=HTTP_TIMEOUT,
    )
    if p.status_code >= 400:
        raise HTTPException(502, f"IG publish failed: {p.text[:300]}")
    return p.json()


# ─── Endpoints ─────────────────────────────────────────────────────

@router.get("/connect/meta/health")
async def meta_health():
    return {
        "status": "ok",
        "app_id_configured":         bool(os.environ.get("META_APP_ID")),
        "app_secret_configured":     bool(os.environ.get("META_APP_SECRET")),
        "redirect_uri_configured":   bool(os.environ.get("META_REDIRECT_URI")),
        "state_secret_configured":   bool(os.environ.get("META_OAUTH_STATE_SECRET")),
        "frontend_return_configured": bool(os.environ.get("META_FRONTEND_RETURN_URL")),
        "redirect_uri": os.environ.get("META_REDIRECT_URI", ""),
    }


@router.get("/connect/meta")
async def meta_connect(business_id: str):
    """Redirect the user to Facebook OAuth. The business_id is signed
    into the state param so we can recover + verify it in the callback."""
    if not business_id:
        raise HTTPException(400, "business_id required")
    state = _make_state(business_id)
    params = {
        "client_id": _meta_app_id(),
        "redirect_uri": _meta_redirect_uri(),
        "state": state,
        "scope": META_SCOPES,
        "response_type": "code",
    }
    return RedirectResponse(url=f"{FB_OAUTH}?{urlencode(params)}", status_code=302)


def _success_html(message: str) -> HTMLResponse:
    """Tiny self-contained "you can close this tab" page. Posts a
    message back to window.opener if launched from a popup."""
    safe = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Connected</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; padding: 48px 24px;
          text-align: center; background: #0a0a0a; color: #fafafa; }}
  .card {{ max-width: 460px; margin: 0 auto; padding: 32px; border-radius: 16px;
            background: rgba(255,255,255,0.04); border: 1px solid rgba(124,58,237,0.4);
            box-shadow: 0 8px 32px rgba(124,58,237,0.18); }}
  h1 {{ font-size: 22px; margin: 0 0 8px; font-weight: 600; letter-spacing: -0.01em; }}
  p  {{ font-size: 14px; color: #a3a3a3; line-height: 1.55; margin: 0 0 16px; }}
  .cta {{ margin-top: 12px; font-size: 12px; color: #737373; }}
</style></head><body>
<div class="card">
  <h1>✓ Connected</h1>
  <p>{safe}</p>
  <p class="cta">You can close this tab and return to the app.</p>
</div>
<script>
  try {{
    if (window.opener) {{
      window.opener.postMessage({{ type: 'solutionist-meta-connected' }}, '*');
    }}
  }} catch (e) {{}}
  setTimeout(function() {{ try {{ window.close(); }} catch (e) {{}} }}, 1500);
</script>
</body></html>"""
    return HTMLResponse(content=html)


def _error_html(message: str) -> HTMLResponse:
    safe = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Connect failed</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; padding: 48px 24px;
          text-align: center; background: #0a0a0a; color: #fafafa; }}
  .card {{ max-width: 460px; margin: 0 auto; padding: 32px; border-radius: 16px;
            background: rgba(255,255,255,0.04); border: 1px solid rgba(239,68,68,0.4); }}
  h1 {{ font-size: 22px; margin: 0 0 8px; color: #f87171; }}
  p  {{ font-size: 13px; color: #a3a3a3; line-height: 1.55; margin: 0 0 16px; }}
</style></head><body>
<div class="card">
  <h1>Connect failed</h1>
  <p>{safe}</p>
  <p>You can close this tab and try again from Settings.</p>
</div>
</body></html>"""
    return HTMLResponse(content=html, status_code=400)


@router.get("/connect/meta/callback")
async def meta_callback(code: Optional[str] = None, state: Optional[str] = None,
                        error: Optional[str] = None, error_description: Optional[str] = None):
    """Meta redirects here after the user grants permission.

    Flow:
      1. Verify state → recover business_id
      2. Exchange code → short-lived user token
      3. Exchange short → long-lived user token
      4. /me/accounts → list of Pages + their long-lived Page tokens
      5. Upsert one row per Page in social_accounts
    """
    if error:
        return _error_html(error_description or error)
    if not code or not state:
        return _error_html("Missing code or state in callback.")

    try:
        payload = _parse_state(state)
    except HTTPException as e:
        return _error_html(e.detail)
    business_id = payload["business_id"]

    async with httpx.AsyncClient() as client:
        # 2. code → short-lived user token
        r = await client.get(
            f"{FB_GRAPH}/oauth/access_token",
            params={
                "client_id": _meta_app_id(),
                "client_secret": _meta_app_secret(),
                "redirect_uri": _meta_redirect_uri(),
                "code": code,
            },
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code >= 400:
            return _error_html(f"Token exchange failed: {r.text[:200]}")
        short_token = r.json().get("access_token")
        if not short_token:
            return _error_html("Meta returned no access_token.")

        # 3. short → long-lived user token
        try:
            long_user_token = await _exchange_short_for_long(client, short_token)
        except HTTPException as e:
            return _error_html(str(e.detail))

        # 4. List the user's Pages
        try:
            pages = await _list_pages(client, long_user_token)
        except HTTPException as e:
            return _error_html(str(e.detail))
        if not pages:
            return _error_html("No Pages found on this Facebook account. "
                               "Make sure you're an admin of a Page and granted access during connect.")

        # 5. Upsert one row per Page
        upserted = []
        for p in pages:
            page_id = p.get("id")
            if not page_id:
                continue
            ig_info = p.get("instagram_business_account") or {}
            ig_user_id = ig_info.get("id") if isinstance(ig_info, dict) else None
            row = {
                "business_id": business_id,
                "provider": "meta",
                "page_id": str(page_id),
                "page_name": p.get("name") or "(unnamed Page)",
                "page_token": p.get("access_token") or "",
                "ig_user_id": str(ig_user_id) if ig_user_id else None,
                "status": "connected",
                "last_error": None,
                "last_error_at": None,
            }
            # PostgREST upsert via Prefer: resolution=merge-duplicates
            # (Prefer header is already set in _sb). The unique index on
            # (business_id, provider, page_id) is the merge key.
            inserted = await _sb(client, "POST", "/social_accounts", row)
            if inserted:
                upserted.append(p.get("name") or page_id)

    n = len(upserted)
    names = ", ".join(upserted[:3]) + (f" + {n-3} more" if n > 3 else "")

    # Optional FE redirect — when set, send the browser back to the app's
    # Settings page (works in browser mode; the popup-flow message handler
    # also fires for Tauri).
    return_url = _frontend_return_url("")
    if return_url:
        sep = "&" if "?" in return_url else "?"
        return RedirectResponse(url=f"{return_url}{sep}meta=connected&count={n}", status_code=302)
    return _success_html(f"Connected {n} Page{'s' if n != 1 else ''}: {names}")


@router.get("/connect/meta/pages")
async def meta_list_pages(business_id: str):
    """Return the connected Pages for a business — no tokens leak."""
    if not business_id:
        raise HTTPException(400, "business_id required")
    async with httpx.AsyncClient() as client:
        rows = await _sb(client, "GET",
            f"/social_accounts?business_id=eq.{business_id}&provider=eq.meta"
            f"&select=id,page_id,page_name,ig_user_id,status,connected_at,last_error"
            f"&order=connected_at.desc") or []
    return {"pages": rows}


@router.delete("/connect/meta/disconnect")
async def meta_disconnect(business_id: str, page_id: str):
    """Remove a single Page connection."""
    if not business_id or not page_id:
        raise HTTPException(400, "business_id and page_id required")
    async with httpx.AsyncClient() as client:
        await _sb(client, "DELETE",
            f"/social_accounts?business_id=eq.{business_id}&provider=eq.meta&page_id=eq.{page_id}")
    return {"ok": True}


# ─── Publish ────────────────────────────────────────────────────────

class PublishRequest(BaseModel):
    business_id: str
    page_id: str
    message: str
    image_url: Optional[str] = None
    to_instagram: Optional[bool] = False


class PublishResponse(BaseModel):
    ok: bool
    facebook: Optional[Dict[str, Any]] = None
    instagram: Optional[Dict[str, Any]] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None


@router.post("/publish", response_model=PublishResponse)
async def meta_publish(req: PublishRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(400, "message required")

    async with httpx.AsyncClient() as client:
        # Look up the connection (with token) for this tenant + page.
        rows = await _sb(client, "GET",
            f"/social_accounts?business_id=eq.{req.business_id}"
            f"&provider=eq.meta&page_id=eq.{req.page_id}"
            f"&select=page_id,page_name,page_token,ig_user_id,status&limit=1") or []
        if not rows:
            raise HTTPException(404, "No connection found for this business + page")
        acct = rows[0]
        if acct.get("status") != "connected":
            raise HTTPException(409, f"Connection status is '{acct.get('status')}' — reconnect needed")
        page_token = acct.get("page_token")
        ig_user_id = acct.get("ig_user_id")
        if not page_token:
            raise HTTPException(409, "Page token missing — reconnect needed")

        fb_result = None
        ig_result = None

        # ── Facebook publish ──
        try:
            fb_result = await _publish_facebook(client, req.page_id, page_token, req.message, req.image_url)
        except HTTPException as e:
            # Mark connection expired if Meta refuses on auth grounds.
            if "190" in str(e.detail) or "OAuth" in str(e.detail):
                await _sb(client, "PATCH",
                    f"/social_accounts?business_id=eq.{req.business_id}&page_id=eq.{req.page_id}",
                    {"status": "expired", "last_error": str(e.detail)[:300]})
            raise

        # ── Instagram publish (optional) ──
        if req.to_instagram:
            if not ig_user_id:
                raise HTTPException(400,
                    "Instagram not linked to this Page. Make sure your IG account is a "
                    "Business/Creator account linked to this Facebook Page.")
            if not req.image_url:
                raise HTTPException(400, "Instagram publishing requires an image_url.")
            try:
                ig_result = await _publish_instagram(client, ig_user_id, page_token, req.message, req.image_url)
            except HTTPException as e:
                # FB went through, IG failed — return both halves so the
                # caller can surface a partial-success state.
                return PublishResponse(
                    ok=False,
                    facebook=fb_result,
                    instagram={"error": str(e.detail)[:300]},
                    facebook_url=_fb_post_url(req.page_id, fb_result),
                    instagram_url=None,
                )

    return PublishResponse(
        ok=True,
        facebook=fb_result,
        instagram=ig_result,
        facebook_url=_fb_post_url(req.page_id, fb_result),
        instagram_url=_ig_post_url(ig_user_id, ig_result),
    )


def _fb_post_url(page_id: str, fb_result: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best-effort permalink for the FB post. /feed returns id; /photos
    returns post_id. Both let us deep-link."""
    if not fb_result:
        return None
    pid = fb_result.get("post_id") or fb_result.get("id")
    if not pid:
        return None
    return f"https://www.facebook.com/{pid}"


def _ig_post_url(ig_user_id: Optional[str], ig_result: Optional[Dict[str, Any]]) -> Optional[str]:
    """IG returns the media ID; we'd need a follow-up fetch to resolve
    the shortcode/permalink. For v1 we just return the ID-style URL."""
    if not ig_user_id or not ig_result:
        return None
    media_id = ig_result.get("id")
    if not media_id:
        return None
    # Permalink fetch requires another API call — skip for v1.
    return None
