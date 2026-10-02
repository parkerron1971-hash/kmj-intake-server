"""
email_domain_monitor.py — the sending domain, after the green badge.

THE GAP THIS CLOSES
  Verification is a moment; DNS is forever editable. An operator's web
  person tidies a zone, a registrar migration drops a TXT record, a
  Cloudflare proxy toggle eats the MX — and from that hour every send
  falls back to noreply@mysolutionist.app. That fallback is DELIBERATE
  (resolve_from_address never guesses half an address), and it is also
  silent: the badge in Integrations still says Verified, replies still
  route, nothing errors. The operator finds out when a client asks why
  the invoice came from a stranger.

WHAT THIS DOES, ONCE AN HOUR
  For every business whose stored status is `verified`:
    - ask Resend what it thinks now;
    - if it no longer says verified → mark the settings `failed`, stamp
      `drift_detected_at`, drop the identity cache so the very next send
      already carries the safe platform address, and tell the owner
      (in-app notification + push + an email to their sign-in address);
    - if a previously-drifted domain is verified again → restore it and
      say so.
  For every business already marked failed BY THIS MONITOR, the same
  check runs so recovery is noticed without the operator pressing
  Verify.

DISCIPLINE
  - Only CHANGES are written. A healthy domain costs one Resend GET and
    no database write; `last_checked_at` rides along only with a change.
  - Every notification is best-effort and wrapped: a push failure must
    not undo a correct status flip.
  - Per-tick cap. A platform with a thousand verified domains is a
    problem for a later design, not for a job that runs every hour.
  - Never raises out of the tick — the scheduler wrapper logs, but a
    monitor that dies on one bad row stops watching the other ninety-nine.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

import sb_clients
from email_sender import EMAIL_DOMAIN_SETTINGS_KEY, email_domain_settings

logger = logging.getLogger("email_domain_monitor")

MAX_PER_TICK = 200
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Reads ──────────────────────────────────────────────────────────


def _watched_businesses() -> List[Dict[str, Any]]:
    """Verified domains, plus ones this monitor itself marked failed
    (so recovery is seen). A domain the OPERATOR's verify call marked
    failed is theirs to retry; we do not poll it."""
    sel = "select=id,name,owner_id,settings"
    verified = sb_clients.sb_get_as_service(
        f"/businesses?settings->{EMAIL_DOMAIN_SETTINGS_KEY}->>status=eq.verified"
        f"&{sel}&limit={MAX_PER_TICK}") or []
    drifted = sb_clients.sb_get_as_service(
        f"/businesses?settings->{EMAIL_DOMAIN_SETTINGS_KEY}->>drift_detected_at=not.is.null"
        f"&settings->{EMAIL_DOMAIN_SETTINGS_KEY}->>status=eq.failed"
        f"&{sel}&limit={MAX_PER_TICK}") or []
    seen = set()
    out = []
    for row in list(verified) + list(drifted):
        if row.get("id") in seen:
            continue
        seen.add(row.get("id"))
        out.append(row)
    return out[:MAX_PER_TICK]


async def _resend_domain(domain_id: str) -> Optional[Dict[str, Any]]:
    """Live domain from Resend. None when the provider can't be asked
    (no key, unreachable, 5xx) — and None means "don't touch anything":
    a provider outage is not DNS drift."""
    key = (os.environ.get("RESEND_API_KEY") or "").strip()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"https://api.resend.com/domains/{domain_id}",
                headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        logger.warning(f"[domain-monitor] Resend unreachable: {e}")
        return None
    if resp.status_code == 404:
        return {"__missing__": True}
    if resp.status_code >= 400:
        logger.warning(f"[domain-monitor] Resend {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        return resp.json() or {}
    except ValueError:
        return None


def _normalize_status(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower()
    if s == "verified":
        return "verified"
    if s in ("failed", "failure", "temporary_failure"):
        return "failed"
    return "pending"


async def _owner_email(owner_id: str) -> Optional[str]:
    """The practitioner's sign-in email, via the auth admin API."""
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not service_key or not owner_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{base}/auth/v1/admin/users/{owner_id}",
                            headers={"apikey": service_key,
                                     "Authorization": f"Bearer {service_key}"})
        if r.status_code >= 400:
            return None
        return (r.json() or {}).get("email") or None
    except Exception as e:
        logger.warning(f"[domain-monitor] owner email lookup failed: {e}")
        return None


# ─── Writes ─────────────────────────────────────────────────────────


def _write_cfg(biz: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    settings = dict(biz.get("settings") or {})
    settings[EMAIL_DOMAIN_SETTINGS_KEY] = cfg
    res = sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    return res is not None


def _drop_identity_cache(business_id: str) -> None:
    try:
        import email_sender
        email_sender._IDENTITY_CACHE.pop(f"id:{business_id}", None)
        email_sender._IDENTITY_CACHE.pop(f"pfx:{business_id[:8]}", None)
    except Exception:
        pass


async def _notify(biz: Dict[str, Any], *, title: str, body: str,
                  kind: str, email_subject: str, email_body: str) -> Dict[str, bool]:
    """In-app, push, and email. Each best-effort; none can fail the flip."""
    out = {"in_app": False, "push": False, "email": False}
    bid = biz.get("id")
    try:
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": bid,
            "type": "alert" if kind == "drift" else "info",
            "title": title[:120],
            "body": body[:300],
            "priority": "high" if kind == "drift" else "normal",
            "status": "unread",
            "data": {"kind": f"email_domain_{kind}", "domain": (email_domain_settings(biz.get("settings")) or {}).get("domain")},
        })
        out["in_app"] = True
    except Exception as e:
        logger.warning(f"[domain-monitor] in-app notify failed biz={str(bid)[:8]}: {e}")
    try:
        import push_notifications
        out["push"] = bool(push_notifications.send_to_business(
            bid, title=title, body=body, nav="build:integrations",
            tag="email-domain-drift"))
    except Exception as e:
        logger.warning(f"[domain-monitor] push failed biz={str(bid)[:8]}: {e}")
    try:
        to_email = await _owner_email(str(biz.get("owner_id") or ""))
        if to_email:
            import email_sender
            await email_sender.send_via_resend(
                to_email=to_email, to_name=None,
                from_email=os.environ.get("RESEND_FROM_EMAIL") or email_sender.DEFAULT_FROM_EMAIL,
                from_name=email_sender.DEFAULT_FROM_NAME,
                subject=email_subject, body=email_body, reply_to=None)
            out["email"] = True
    except Exception as e:
        logger.warning(f"[domain-monitor] owner email failed biz={str(bid)[:8]}: {e}")
    return out


# ─── One business ───────────────────────────────────────────────────


async def check_one(biz: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {business_id, change: None|'drift'|'recovered'|'missing'}."""
    bid = str(biz.get("id") or "")
    cfg = email_domain_settings(biz.get("settings"))
    result: Dict[str, Any] = {"business_id": bid, "change": None}
    domain_id = cfg.get("resend_domain_id")
    if not domain_id:
        return result

    live = await _resend_domain(domain_id)
    if live is None:
        return result  # provider unavailable — not drift, don't touch
    domain = cfg.get("domain") or "your domain"
    biz_name = biz.get("name") or "your business"

    if live.get("__missing__"):
        live_status = "missing"
    else:
        live_status = _normalize_status(live.get("status"))

    was_verified = cfg.get("status") == "verified"
    drifted_before = bool(cfg.get("drift_detected_at"))

    if was_verified and live_status != "verified":
        new_cfg = {**cfg, "status": "failed",
                   "drift_detected_at": _now_iso(),
                   "drift_reason": live_status,
                   "last_checked_at": _now_iso()}
        if _write_cfg(biz, new_cfg):
            _drop_identity_cache(bid)
            result["change"] = "drift"
            logger.warning(f"[domain-monitor] DRIFT {domain} biz={bid[:8]} live={live_status}")
            await _notify(
                biz, kind="drift",
                title=f"Email from {domain} stopped verifying",
                body=(f"A DNS record for {domain} is missing or changed. Until it's "
                      f"fixed, your email sends from the platform address so nothing "
                      f"bounces. Open Email setup to see which record."),
                email_subject=f"Action needed: {domain} stopped verifying",
                email_body=(
                    f"Hi,\n\nThe DNS setup for {domain} ({biz_name}) is no longer "
                    f"verifying with the email provider (status: {live_status}).\n\n"
                    f"Nothing is bouncing: until it's fixed, your emails go out from "
                    f"the platform address instead of your own. Open Email setup in "
                    f"the app to see which record is missing, or forward this to "
                    f"whoever manages your domain.\n\n— The Solutionist System"))
        return result

    if drifted_before and live_status == "verified":
        new_cfg = {k: v for k, v in cfg.items() if k not in ("drift_detected_at", "drift_reason")}
        new_cfg.update({"status": "verified", "last_checked_at": _now_iso()})
        if not new_cfg.get("verified_at"):
            new_cfg["verified_at"] = _now_iso()
        if _write_cfg(biz, new_cfg):
            _drop_identity_cache(bid)
            result["change"] = "recovered"
            logger.info(f"[domain-monitor] RECOVERED {domain} biz={bid[:8]}")
            await _notify(
                biz, kind="recovered",
                title=f"{domain} is verifying again",
                body=f"Your DNS records are back. Email sends from your own domain again.",
                email_subject=f"{domain} is sending again",
                email_body=(
                    f"Hi,\n\nThe DNS records for {domain} ({biz_name}) are verifying "
                    f"again. Your emails are going out from your own address.\n\n"
                    f"— The Solutionist System"))
        return result

    return result


# ─── The tick ───────────────────────────────────────────────────────


async def monitor_tick() -> Dict[str, Any]:
    summary = {"checked": 0, "drift": 0, "recovered": 0, "errors": 0}
    try:
        rows = _watched_businesses()
    except Exception as e:
        logger.warning(f"[domain-monitor] listing failed: {e}")
        summary["errors"] += 1
        return summary
    for biz in rows:
        try:
            res = await check_one(biz)
            summary["checked"] += 1
            if res.get("change") == "drift":
                summary["drift"] += 1
            elif res.get("change") == "recovered":
                summary["recovered"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.warning(f"[domain-monitor] biz={str(biz.get('id'))[:8]} failed: {e}")
    if summary["drift"] or summary["recovered"] or summary["errors"]:
        logger.info(f"[domain-monitor] {summary}")
    return summary
