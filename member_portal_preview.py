"""
member_portal_preview.py — "Preview as a member" for the church owner.

Members sign in to /my with a 6-digit code sent by email or text. Until a
church has email or texting set up, nobody can receive one — including
the owner who wants to see what members will see (Kevin, 2026-09-30:
"no email or text has been allowed because they are not set up"). So the
owner can open the member app AS one of their members, from Settings →
Member page, with nothing sent anywhere:

  1. The app asks POST /member-portal/{biz}/preview {contact_id}
     (owner only). It returns a link to <church host>/my/preview?t=…
     The link is signed, names the business and the member, lasts two
     minutes and works ONCE: its nonce is a row in member_login_codes
     (email "preview:<contact id>"), consumed by a conditional write.
  2. Opening it sets a separate preview cookie (one hour) and lands on
     /my. Every page shows a "Preview" banner with "End preview".
  3. Nothing saves in a preview: every member POST refuses with "This is
     a preview, so nothing is saved." Reading only.

The owner can already see every member's giving in the app, so a preview
shows them nothing new. It works before the page is switched on (to look
before inviting anyone) for a church that could switch it on.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import sb_clients

PREVIEW_COOKIE = "__Host-sol_member_preview"
LINK_TTL_SECONDS = 120
SESSION_TTL_SECONDS = 3600
VERSION = 1


def _key(purpose: str, business_id: str) -> bytes:
    from customer_token import derive_key
    return derive_key(purpose, str(business_id))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(purpose: str, business_id: str, claims: Dict[str, Any]) -> str:
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_key(purpose, business_id), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def _verify(purpose: str, business_id: str, token: str, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Claims for THIS business, unexpired, or None. Never raises."""
    try:
        payload, sig = (token or "").split(".", 1)
        want = _b64(hmac.new(_key(purpose, business_id), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        claims = json.loads(_unb64(payload))
        if claims.get("v") != VERSION or str(claims.get("biz")) != str(business_id):
            return None
        if int(claims.get("exp") or 0) <= int(now if now is not None else time.time()):
            return None
        if not str(claims.get("cid") or ""):
            return None
        return claims
    except Exception:
        return None


def _nonce_email(contact_id: str) -> str:
    return f"preview:{str(contact_id).lower()}"


def issue_link_token(business_id: str, contact_id: str, owner_id: str, now: Optional[int] = None) -> Optional[str]:
    """A one-time, two-minute token, or None when its ticket couldn't be
    written (the caller says "try again")."""
    now = int(now if now is not None else time.time())
    nonce = secrets.token_urlsafe(24)
    row = sb_clients.sb_post_as_service("/member_login_codes", {
        "business_id": str(business_id), "email": _nonce_email(contact_id),
        "code_hash": hashlib.sha256(nonce.encode()).hexdigest(),
        "expires_at": datetime.fromtimestamp(now + LINK_TTL_SECONDS, timezone.utc).isoformat(),
    })
    if not isinstance(row, list) or not row:
        return None
    return _sign("member-preview-link", business_id, {
        "biz": str(business_id), "cid": str(contact_id), "own": str(owner_id), "n": nonce,
        "iat": now, "exp": now + LINK_TTL_SECONDS, "v": VERSION})


def redeem_link_token(business_id: str, token: str, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The link's claims if it is genuine, unexpired and unused — and
    marks it used in the same conditional write, so a second open fails."""
    claims = _verify("member-preview-link", business_id, token, now)
    if not claims:
        return None
    stamp = datetime.now(timezone.utc).isoformat()
    used = sb_clients.sb_patch_as_service(
        f"/member_login_codes?business_id=eq.{quote(str(business_id), safe='')}"
        f"&email=eq.{quote(_nonce_email(claims['cid']), safe='')}"
        f"&code_hash=eq.{hashlib.sha256(str(claims.get('n') or '').encode()).hexdigest()}"
        f"&consumed_at=is.null&expires_at=gt.{quote(stamp, safe='')}",
        {"consumed_at": stamp, "succeeded": True})
    return claims if isinstance(used, list) and used else None


def mint_session(business_id: str, contact_id: str, owner_id: str, now: Optional[int] = None) -> str:
    now = int(now if now is not None else time.time())
    return _sign("member-preview-session", business_id, {
        "biz": str(business_id), "cid": str(contact_id), "own": str(owner_id), "pv": 1,
        "iat": now, "exp": now + SESSION_TTL_SECONDS, "v": VERSION})


def read_session(value: str, business_id: str, epoch: int = 0, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
    claims = _verify("member-preview-session", business_id, value, now)
    if not claims or int(claims.get("iat") or 0) < int(epoch or 0):
        return None
    return claims


def load_contact(business_id: str, contact_id: str):
    """The member's record: a dict, False when it isn't this church's
    (or is gone), None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{quote(str(contact_id), safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
        f"&select=id,name,email,phone&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else False


def set_cookie(resp, value: str) -> None:
    resp.set_cookie(PREVIEW_COOKIE, value, max_age=SESSION_TTL_SECONDS, path="/",
                    httponly=True, secure=True, samesite="lax")


def clear_cookie(resp) -> None:
    resp.delete_cookie(PREVIEW_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


def banner(name: str) -> str:
    from member_portal import _e
    return (f'<div class="mb-preview mp-noprint" role="status"><span><strong>Preview</strong> · You\'re seeing '
            f'{_e(name or "this member")}\'s page. Nothing you tap here is saved.</span>'
            f'<form method="post" action="/my/preview/end"><button type="submit">End preview</button></form></div>')


def mark(html: str, name: str) -> str:
    """The banner at the top of the page, above the church's header."""
    return html.replace('<header class="mb-top">', banner(name) + '<header class="mb-top">', 1)
