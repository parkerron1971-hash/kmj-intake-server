"""
email_domains_router.py — per-business sending identity (S6).

THE GAP THIS CLOSES
  Every email left the platform as noreply@mysolutionist.app (or a
  sibling platform address). An operator with their own domain could not
  send as themselves. This router runs the domain lifecycle against the
  Resend domains API on the PLATFORM's key:

      POST   /email-domain/{business_id}/connect     — create the domain
      GET    /email-domain/{business_id}/status      — live status + DNS records
      POST   /email-domain/{business_id}/verify      — ask Resend to verify
      DELETE /email-domain/{business_id}/disconnect  — remove + clear settings

  State lives in businesses.settings.email_domain (a settings blob, same
  pattern as settings.giving — no SQL migration):

      { domain, from_local_part, from_name, resend_domain_id,
        status: pending|verified|failed, records: [...],
        connected_at, verified_at }

  The resolution seam that CONSUMES this state is
  email_sender.resolve_from_address — business-originated sends switch
  to `{from_local_part}@{domain}` the moment status flips to verified.

REPLY ROUTING (deliberate): a custom from does NOT change reply_to. The
routed reply-to (reply+{biz8}+{contact8}@INBOUND_EMAIL_DOMAIN) stays the
platform's inbound address so replies keep landing on /email/inbound and
flow back into the app. Custom INBOUND (MX on the operator's domain) is
a separate future arc.

DISCIPLINE
  - Owner-only, via the require_role ladder (rank 5).
  - Never half-write: settings are written only AFTER Resend succeeds;
    a failed settings write rolls the Resend domain back (best effort).
  - Missing RESEND_API_KEY → 503; Resend API trouble → 502 with the
    provider's message. No silent degradation.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
from email_sender import EMAIL_DOMAIN_SETTINGS_KEY, email_domain_settings

logger = logging.getLogger("email_domains")

router = APIRouter(prefix="/email-domain", tags=["email-domain"])

RESEND_DOMAINS_URL = "https://api.resend.com/domains"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

# Domains the platform itself sends from — an operator can't claim them.
_PLATFORM_DOMAINS = {"mysolutionist.app", "solutionist.studio", "resend.dev"}

_DOMAIN_RE = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
_LOCAL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$")


class ConnectBody(BaseModel):
    domain: str
    from_local_part: str
    from_name: Optional[str] = None


# ─── Gates ───────────────────────────────────────────────────────────


def _require_owner_biz(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """404 on a missing business, 403 below owner. Returns the row
    (id, name, settings) the endpoints work against."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(business_id, str(user.id), "owner")
    return rows[0]


def _resend_key() -> str:
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not key:
        raise HTTPException(
            503, "Email domain setup isn't available right now — the email "
                 "provider isn't configured on this deployment (RESEND_API_KEY).")
    return key


async def _resend(method: str, path: str,
                  json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One Resend domains-API call. 502 with the provider's message on
    any failure; a 404 comes back as {"__missing__": True} so callers
    can treat an already-deleted domain as gone rather than as an error."""
    key = _resend_key()
    url = f"{RESEND_DOMAINS_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.request(
                method, url,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=json_body)
    except httpx.HTTPError as e:
        logger.warning(f"Resend {method} {path} unreachable: {e}")
        raise HTTPException(502, "The email provider didn't respond — try again "
                                 "in a moment.")
    if resp.status_code == 404:
        return {"__missing__": True}
    if resp.status_code >= 400:
        try:
            detail = (resp.json() or {}).get("message") or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        logger.warning(f"Resend {method} {path} -> {resp.status_code}: {detail}")
        raise HTTPException(502, f"Email provider error: {detail}")
    try:
        return resp.json() if resp.text else {}
    except ValueError:
        return {}


# ─── Shape helpers ───────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_status(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower()
    if s == "verified":
        return "verified"
    if s in ("failed", "failure", "temporary_failure"):
        return "failed"
    return "pending"  # not_started / pending / unknown


def _records_from(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resend's DNS records (SPF + DKIM), normalized for the UI table."""
    out: List[Dict[str, Any]] = []
    for rec in (payload.get("records") or []):
        if not isinstance(rec, dict):
            continue
        out.append({
            "record": rec.get("record"),          # SPF | DKIM
            "type": rec.get("type"),              # TXT | CNAME | MX
            "name": rec.get("name"),
            "value": rec.get("value"),
            "ttl": rec.get("ttl"),
            "priority": rec.get("priority"),
            "status": _normalize_status(rec.get("status")),
        })
    return out


def _preview(cfg: Dict[str, Any], biz: Dict[str, Any]) -> Dict[str, Any]:
    from_email = f"{cfg.get('from_local_part')}@{cfg.get('domain')}"
    from_name = cfg.get("from_name") or biz.get("name") or ""
    return {"from_email": from_email, "from_name": from_name,
            "rendered": f"{from_name} <{from_email}>" if from_name else from_email}


def _payload(cfg: Dict[str, Any], biz: Dict[str, Any],
             live_status: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "connected": True,
        "domain": cfg.get("domain"),
        "from_local_part": cfg.get("from_local_part"),
        "from_name": cfg.get("from_name"),
        "status": cfg.get("status"),
        "live_status": live_status or cfg.get("status"),
        "records": cfg.get("records") or [],
        "connected_at": cfg.get("connected_at"),
        "verified_at": cfg.get("verified_at"),
        "preview": _preview(cfg, biz),
    }


def _write_settings(biz: Dict[str, Any], cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist settings.email_domain (or remove it when cfg is None).
    Raises 500 when the write doesn't land — callers roll back."""
    settings = dict(biz.get("settings") or {})
    if cfg is None:
        settings.pop(EMAIL_DOMAIN_SETTINGS_KEY, None)
    else:
        settings[EMAIL_DOMAIN_SETTINGS_KEY] = cfg
    res = sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    if res is None:
        raise HTTPException(500, "Couldn't save the email domain settings — "
                                 "nothing was changed. Try again.")
    return settings


# ─── Endpoints ───────────────────────────────────────────────────────


@router.post("/{business_id}/connect")
async def connect_domain(business_id: str, body: ConnectBody,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner_biz(business_id, user)

    domain = (body.domain or "").strip().lower().rstrip(".")
    domain = re.sub(r"^https?://", "", domain).split("/")[0]
    local = (body.from_local_part or "").strip().lower().lstrip("@")
    from_name = (body.from_name or "").strip()[:80] or None

    if not _DOMAIN_RE.match(domain):
        raise HTTPException(400, "That doesn't look like a domain — expected "
                                 "something like studiok.com")
    root = ".".join(domain.rsplit(".", 2)[-2:])
    if root in _PLATFORM_DOMAINS or domain in _PLATFORM_DOMAINS:
        raise HTTPException(400, "That domain belongs to the platform — connect "
                                 "a domain you own.")
    if not _LOCAL_RE.match(local):
        raise HTTPException(400, "The from address must be the part before the @ "
                                 "— letters, numbers, dots (e.g. hello)")

    existing = email_domain_settings(biz.get("settings"))
    if existing.get("resend_domain_id"):
        raise HTTPException(409, f"{existing.get('domain')} is already connected "
                                 "— disconnect it first to switch domains.")

    # Resend FIRST; settings only after success (never half-write).
    created = await _resend("POST", "", {"name": domain})
    if created.get("__missing__"):
        raise HTTPException(502, "Email provider error: domain create returned 404")
    domain_id = created.get("id")
    if not domain_id:
        raise HTTPException(502, "Email provider error: no domain id returned")

    cfg = {
        "domain": domain,
        "from_local_part": local,
        "from_name": from_name,
        "resend_domain_id": domain_id,
        "status": "pending",
        "records": _records_from(created),
        "connected_at": _now_iso(),
        "verified_at": None,
    }
    try:
        _write_settings(biz, cfg)
    except HTTPException:
        # Roll the Resend domain back so a retry isn't blocked by an
        # orphan; the settings blob was never touched.
        try:
            await _resend("DELETE", f"/{domain_id}")
        except HTTPException:
            logger.warning(f"orphan Resend domain {domain_id} for biz "
                           f"{business_id[:8]} — settings write failed AND "
                           f"rollback delete failed")
        raise

    logger.info(f"[email-domain] connected {domain} biz={business_id[:8]}")
    return _payload(cfg, biz)


@router.get("/{business_id}/status")
async def domain_status(business_id: str,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner_biz(business_id, user)
    cfg = email_domain_settings(biz.get("settings"))
    if not cfg.get("resend_domain_id"):
        return {"ok": True, "connected": False}

    live = await _resend("GET", f"/{cfg['resend_domain_id']}")
    if live.get("__missing__"):
        # Deleted on the Resend side (dashboard, support) — report
        # honestly; disconnect clears the stale settings.
        return {**_payload(cfg, biz, live_status="missing"),
                "note": "This domain no longer exists at the email provider — "
                        "disconnect and reconnect it."}
    records = _records_from(live)
    if records:
        cfg = {**cfg, "records": records}
    return _payload(cfg, biz, live_status=_normalize_status(live.get("status")))


@router.post("/{business_id}/verify")
async def verify_domain(business_id: str,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner_biz(business_id, user)
    cfg = email_domain_settings(biz.get("settings"))
    if not cfg.get("resend_domain_id"):
        raise HTTPException(409, "No domain connected yet")

    domain_id = cfg["resend_domain_id"]
    kicked = await _resend("POST", f"/{domain_id}/verify")
    if kicked.get("__missing__"):
        raise HTTPException(502, "Email provider error: that domain no longer "
                                 "exists — disconnect and reconnect it.")
    live = await _resend("GET", f"/{domain_id}")
    if live.get("__missing__"):
        raise HTTPException(502, "Email provider error: that domain no longer "
                                 "exists — disconnect and reconnect it.")

    status = _normalize_status(live.get("status"))
    records = _records_from(live) or cfg.get("records") or []
    new_cfg = {**cfg, "records": records, "status": status}
    if status == "verified" and not cfg.get("verified_at"):
        new_cfg["verified_at"] = _now_iso()
    if new_cfg != cfg:
        _write_settings(biz, new_cfg)
    if status == "verified":
        # Sends resolve identity through a short TTL cache — drop it so
        # the first post-verify send already carries the new from.
        try:
            import email_sender
            email_sender._IDENTITY_CACHE.pop(f"id:{business_id}", None)
            email_sender._IDENTITY_CACHE.pop(f"pfx:{business_id[:8]}", None)
        except Exception:
            pass
        logger.info(f"[email-domain] VERIFIED {cfg.get('domain')} "
                    f"biz={business_id[:8]}")
    return _payload(new_cfg, biz, live_status=status)


@router.delete("/{business_id}/disconnect")
async def disconnect_domain(business_id: str,
                            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner_biz(business_id, user)
    cfg = email_domain_settings(biz.get("settings"))
    if not cfg.get("resend_domain_id"):
        return {"ok": True, "connected": False, "already": True}

    # Resend delete first (404 = already gone, fine); only then clear
    # settings — a provider failure leaves state intact and visible.
    await _resend("DELETE", f"/{cfg['resend_domain_id']}")
    _write_settings(biz, None)
    try:
        import email_sender
        email_sender._IDENTITY_CACHE.pop(f"id:{business_id}", None)
        email_sender._IDENTITY_CACHE.pop(f"pfx:{business_id[:8]}", None)
    except Exception:
        pass
    logger.info(f"[email-domain] disconnected {cfg.get('domain')} "
                f"biz={business_id[:8]}")
    return {"ok": True, "connected": False}
