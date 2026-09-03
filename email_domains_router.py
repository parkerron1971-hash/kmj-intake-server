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

  Setup-room rails (the guided flow that replaced the bare DNS table):

      GET    /email-domain/{business_id}/dns-check     — expected vs FOUND, per record
      POST   /email-domain/{business_id}/test-send     — one real email to the owner
      GET    /email-domain/{business_id}/test-status   — that email's delivery report
      GET    /email-domain/{business_id}/health        — status + 30-day sending stats
      POST   /email-domain/{business_id}/share-records — email the records to whoever
                                                         manages the operator's DNS

  The DMARC row in every `records` list is OURS, not Resend's — see
  email_domain_dns. It is flagged `optional` and never gates verify.
  Drift after verification is watched by email_domain_monitor.

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
import email_domain_dns
from email_sender import EMAIL_DOMAIN_SETTINGS_KEY, email_domain_settings

logger = logging.getLogger("email_domains")

router = APIRouter(prefix="/email-domain", tags=["email-domain"])

RESEND_DOMAINS_URL = "https://api.resend.com/domains"
RESEND_EMAILS_URL = "https://api.resend.com/emails"
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


class TestSendBody(BaseModel):
    to_email: Optional[str] = None   # defaults to the signed-in owner's email


class ShareRecordsBody(BaseModel):
    to_email: str
    note: Optional[str] = None


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
    url = path if path.startswith("https://") else f"{RESEND_DOMAINS_URL}{path}"
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
        "records": email_domain_dns.with_dmarc(cfg.get("records") or [],
                                               cfg.get("domain") or ""),
        "connected_at": cfg.get("connected_at"),
        "verified_at": cfg.get("verified_at"),
        "preview": _preview(cfg, biz),
        # Drift, when the monitor has seen one: the setup room shows a
        # banner instead of a green badge that stopped being true.
        "drift_detected_at": cfg.get("drift_detected_at"),
        "last_checked_at": cfg.get("last_checked_at"),
        "last_test": cfg.get("last_test"),
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
    live_status = _normalize_status(live.get("status"))
    if live_status == "verified" and cfg.get("status") != "verified":
        # Resend verified the records on its own (the operator pasted
        # them and never pressed Verify, or the setup room's auto-verify
        # saw the live answer and stopped). The identity seam reads the
        # STORED status, so until this is written every send still left
        # as the platform while the screen said Verified. Record it.
        cfg = {**cfg, "status": "verified",
               "verified_at": cfg.get("verified_at") or _now_iso()}
        _write_settings(biz, cfg)
        try:
            import email_sender
            email_sender._IDENTITY_CACHE.pop(f"id:{business_id}", None)
            email_sender._IDENTITY_CACHE.pop(f"pfx:{business_id[:8]}", None)
        except Exception:
            pass
        logger.info(f"[email-domain] VERIFIED (observed) {cfg.get('domain')} biz={business_id[:8]}")
    return _payload(cfg, biz, live_status=live_status)


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


# ─── Setup-room rails ────────────────────────────────────────────────
#
# Everything below is read-mostly and owner-only. The one write path
# (test-send) records what it sent so test-status can prove the message
# id it is asked about belongs to this business.


def _require_connected(biz: Dict[str, Any]) -> Dict[str, Any]:
    cfg = email_domain_settings(biz.get("settings"))
    if not cfg.get("resend_domain_id"):
        raise HTTPException(409, "No domain connected yet")
    return cfg


@router.get("/{business_id}/dns-check")
async def dns_check(business_id: str,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Expected vs FOUND for every record, resolved by us, not by Resend.

    Resend's status says whether IT is satisfied. This says what the
    operator's DNS actually contains right now, so "pending" can become
    "we found a different value at resend._domainkey". Cheap enough to
    poll every 30s from an open setup screen; nothing is written."""
    biz = _require_owner_biz(business_id, user)
    cfg = _require_connected(biz)
    records = email_domain_dns.with_dmarc(cfg.get("records") or [], cfg.get("domain") or "")
    checked = await email_domain_dns.check_records(cfg.get("domain") or "", records)
    return {
        "ok": True,
        "domain": cfg.get("domain"),
        "status": cfg.get("status"),
        **checked,
    }


def _test_subject(biz: Dict[str, Any]) -> str:
    return f"Test from {biz.get('name') or 'your business'} — you're set up"


def _test_body(biz: Dict[str, Any], from_email: str, custom: bool) -> str:
    name = biz.get("name") or "your business"
    if custom:
        return (f"If you're reading this, {name} is sending from {from_email}.\n\n"
                f"Every invoice, receipt, campaign and Chief message from here on "
                f"carries your domain. Replies to any of them land back in your "
                f"Email room.\n\n— The Solutionist System")
    return (f"This test went out from the platform address ({from_email}) because "
            f"your domain isn't verified yet. Finish the DNS records and send "
            f"another test to see it arrive from your own address.\n\n"
            f"— The Solutionist System")


@router.post("/{business_id}/test-send")
async def test_send(business_id: str, body: TestSendBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """One real email, from the business, to the owner. The proof step.

    The recipient is pinned to the signed-in owner's own address. An
    owner-only endpoint that sent arbitrary mail on the platform's
    reputation would still be a relay; this one can only ever mail the
    person pressing the button."""
    biz = _require_owner_biz(business_id, user)
    cfg = _require_connected(biz)
    _resend_key()

    owner_email = (getattr(user, "email", None) or "").strip().lower()
    to_email = (body.to_email or owner_email).strip().lower()
    if not owner_email or to_email != owner_email:
        raise HTTPException(400, "A test can only be sent to your own sign-in email.")

    import email_sender
    from_email, from_name = email_sender.resolve_from_address(
        biz, default_email=os.environ.get("RESEND_FROM_EMAIL") or email_sender.DEFAULT_FROM_EMAIL,
        default_name=biz.get("name"))
    custom = cfg.get("status") == "verified" and from_email.endswith(f"@{cfg.get('domain')}")
    try:
        data = await email_sender.send_via_resend(
            to_email=to_email, to_name=None,
            from_email=from_email, from_name=from_name,
            subject=_test_subject(biz),
            body=_test_body(biz, from_email, custom),
            reply_to=email_sender.build_routed_reply_to(business_id, None) or from_email,
            business_id=business_id)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    message_id = (data or {}).get("id")
    if not message_id:
        raise HTTPException(502, "Email provider error: no message id returned")

    last_test = {
        "id": message_id,
        "to": to_email,
        "from_email": from_email,
        "identity": "custom" if custom else "platform",
        "sent_at": _now_iso(),
    }
    _write_settings(biz, {**cfg, "last_test": last_test})
    logger.info(f"[email-domain] test sent biz={business_id[:8]} identity={last_test['identity']}")
    return {"ok": True, **last_test}


# Resend's last_event vocabulary → the four-line report the setup room
# draws. Order matters: each step implies the ones before it.
_EVENT_STEPS = {
    "sent": 1, "delivery_delayed": 1,
    "delivered": 2,
    "opened": 3, "clicked": 3,
}
_EVENT_FAILED = {"bounced", "complained", "failed"}


def _report_from_event(last_event: Optional[str], sent_at: Optional[str]) -> Dict[str, Any]:
    ev = (last_event or "").strip().lower()
    failed = ev in _EVENT_FAILED
    step = 0 if failed else _EVENT_STEPS.get(ev, 1 if sent_at else 0)
    return {
        "last_event": ev or None,
        "accepted": step >= 1 or failed,
        "delivered": step >= 2,
        "opened": step >= 3,
        "failed": failed,
        "failure": ev if failed else None,
    }


@router.get("/{business_id}/test-status")
async def test_status(business_id: str, message_id: str,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Delivery report for the test this business sent. Reads the message
    back from Resend rather than from webhooks, so it works the moment
    the send returns and needs no extra event storage."""
    biz = _require_owner_biz(business_id, user)
    cfg = _require_connected(biz)
    last_test = cfg.get("last_test") or {}
    if not message_id or last_test.get("id") != message_id:
        raise HTTPException(404, "That test isn't on record for this business.")

    live = await _resend("GET", f"{RESEND_EMAILS_URL}/{message_id}")
    if live.get("__missing__"):
        raise HTTPException(502, "Email provider error: that message no longer exists.")
    report = _report_from_event(live.get("last_event"), last_test.get("sent_at"))
    return {
        "ok": True,
        "message_id": message_id,
        "to": last_test.get("to"),
        "from_email": last_test.get("from_email"),
        "identity": last_test.get("identity"),
        "sent_at": last_test.get("sent_at"),
        **report,
    }


_SENT_EVENT_TYPES = "email_sent,draft_and_send,agent_message_sent,invoice_sent,campaign_email_sent"
_OPENED_EVENT_TYPES = "email_opened,invoice_viewed"


def _count_events(business_id: str, types_csv: str, since_iso: str) -> int:
    rows = sb_clients.sb_get_as_service(
        f"/events?business_id=eq.{business_id}&event_type=in.({types_csv})"
        f"&created_at=gte.{since_iso}&select=id&limit=5000") or []
    return len(rows)


def _suppressed_contacts(business_id: str) -> int:
    """How many of THIS business's contacts are on the platform-wide
    suppression list. The list has no business column; the join is done
    here against the contact emails, capped so a huge book stays cheap."""
    contacts = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&select=email&limit=2000") or []
    emails = sorted({(c.get("email") or "").strip().lower()
                     for c in contacts if (c.get("email") or "").strip()})
    if not emails:
        return 0
    total = 0
    for i in range(0, len(emails), 200):
        chunk = ",".join(emails[i:i + 200])
        rows = sb_clients.sb_get_as_service(
            f"/email_suppressions?email=in.({chunk})&select=email") or []
        total += len(rows)
    return total


@router.get("/{business_id}/health")
async def domain_health(business_id: str,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The after-setup view: identity + live status + 30-day volume.

    Counts come from the events table the Email room already reads, so
    the numbers here and there agree by construction. Not every send
    path logs an open, so `opened` is a floor, and the payload says so."""
    from datetime import timedelta
    biz = _require_owner_biz(business_id, user)
    cfg = email_domain_settings(biz.get("settings"))
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    stats = {
        "window_days": 30,
        "sent": _count_events(business_id, _SENT_EVENT_TYPES, since),
        "opened": _count_events(business_id, _OPENED_EVENT_TYPES, since),
        "suppressed_contacts": _suppressed_contacts(business_id),
        "opened_is_floor": True,
    }
    if not cfg.get("resend_domain_id"):
        import email_sender
        return {"ok": True, "connected": False,
                "from_email": os.environ.get("RESEND_FROM_EMAIL") or email_sender.DEFAULT_FROM_EMAIL,
                "stats": stats}

    live = await _resend("GET", f"/{cfg['resend_domain_id']}")
    if live.get("__missing__"):
        return {**_payload(cfg, biz, live_status="missing"), "stats": stats,
                "note": "This domain no longer exists at the email provider — "
                        "disconnect and reconnect it."}
    records = _records_from(live)
    if records:
        cfg = {**cfg, "records": records}
    return {**_payload(cfg, biz, live_status=_normalize_status(live.get("status"))),
            "stats": stats}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _records_as_text(cfg: Dict[str, Any]) -> str:
    domain = cfg.get("domain") or ""
    lines = []
    for r in email_domain_dns.with_dmarc(cfg.get("records") or [], domain):
        host = email_domain_dns.fqdn_for(r.get("name"), domain)
        tag = " (recommended, optional)" if r.get("optional") else ""
        lines.append(f"{(r.get('record') or '').upper()}{tag}")
        lines.append(f"  Type:  {r.get('type')}")
        lines.append(f"  Host:  {r.get('name')}   (full name: {host})")
        if r.get("priority") not in (None, ""):
            lines.append(f"  Priority: {r.get('priority')}")
        lines.append(f"  Value: {r.get('value')}")
        lines.append("")
    return "\n".join(lines).rstrip()


@router.post("/{business_id}/share-records")
async def share_records(business_id: str, body: ShareRecordsBody,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Email the DNS records to whoever manages the operator's domain.

    Most practitioners did not set up their own DNS; a web person did.
    Goes out from the PLATFORM address on purpose: the operator's own
    domain is, by definition, not verified yet."""
    biz = _require_owner_biz(business_id, user)
    cfg = _require_connected(biz)
    _resend_key()
    to_email = (body.to_email or "").strip().lower()
    if not _EMAIL_RE.match(to_email):
        raise HTTPException(400, "Enter the email address of the person who manages your domain.")

    import email_sender
    biz_name = biz.get("name") or "a Solutionist business"
    owner_email = (getattr(user, "email", None) or "").strip()
    note = (body.note or "").strip()[:500]
    text = (
        f"{biz_name} is setting up email sending from {cfg.get('domain')}.\n"
        f"Please add these DNS records at the domain's DNS provider:\n\n"
        f"{_records_as_text(cfg)}\n\n"
        f"Values must be added exactly as shown (no extra quotes or spaces). "
        f"Records usually take a few minutes to propagate, occasionally up to an hour.\n"
        + (f"\nNote from {owner_email or 'the owner'}: {note}\n" if note else "")
        + f"\nQuestions? Reply to this email and it reaches {owner_email or 'the owner'}."
    )
    try:
        data = await email_sender.send_via_resend(
            to_email=to_email, to_name=None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or email_sender.DEFAULT_FROM_EMAIL,
            from_name=email_sender.DEFAULT_FROM_NAME,
            subject=f"DNS records for {cfg.get('domain')} ({biz_name})",
            body=text,
            reply_to=owner_email or None)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    logger.info(f"[email-domain] records shared biz={business_id[:8]}")
    return {"ok": True, "to": to_email, "id": (data or {}).get("id")}
