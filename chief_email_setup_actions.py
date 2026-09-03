"""
chief_email_setup_actions.py — "is my email set up?", answered.

THE GAP THIS CLOSES
  The things that decide whether a business's email actually works —
  a connected domain, whether it verifies, whether it has drifted since,
  whether a test ever landed, whether an inbox is connected and still
  syncing — live in three places (businesses.settings.email_domain, the
  provider, google_mailboxes) and none of them was readable from a
  conversation. Chief could only guess, and a guess about email is the
  kind that gets a practitioner to re-paste DNS records that were fine.

WHAT THIS DOES
  One read-only action, `email_setup_status`, that reports the state and
  names the next step in the setup room's own language, so Chief can say
  "your domain is waiting on DNS — open Build → Email Setup, step 2" and
  be right. It writes nothing and sends nothing.

DISCIPLINE
  - Provider unreachable → the stored status is reported, marked as
    stored. A provider outage is not a setup problem.
  - Never a raw error to the practitioner; _fail genericizes.
  - Mirrors the vocabulary of the setup room (identity / DNS / inbox /
    test) so Chief's answer and the screen agree.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sb_clients
from email_sender import DEFAULT_FROM_EMAIL, email_domain_settings

logger = logging.getLogger("chief_email_setup")

STALE_SYNC_HOURS = 24


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    from chief_of_staff import _fail as cos_fail
    return cos_fail(action_type, msg)


def _nav(page: str) -> Dict[str, Any]:
    return {"tab": "build", "sub": page}


def _hours_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
    except ValueError:
        return None


def _normalize_status(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower()
    if s == "verified":
        return "verified"
    if s in ("failed", "failure", "temporary_failure"):
        return "failed"
    return "pending"


async def _live_status(domain_id: str) -> Optional[str]:
    """What the provider says now: verified | pending | failed | missing.
    None when the provider can't be asked — the caller reports the
    stored status and says so."""
    try:
        from email_domains_router import _resend
        live = await _resend("GET", f"/{domain_id}")
    except Exception as e:  # HTTPException (503/502) or anything else
        logger.info(f"[email-setup] provider check unavailable: {e}")
        return None
    if live.get("__missing__"):
        return "missing"
    return _normalize_status(live.get("status"))


def _mailboxes(business_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/google_mailboxes?business_id=eq.{business_id}"
        f"&select=google_email,status,last_error,last_synced_at"
        f"&order=connected_at.desc&limit=5") or []


async def handle_email_setup_status(client, biz, action) -> Dict[str, Any]:
    business_id = str(biz.get("id") or "")
    if not business_id:
        return _fail("email_setup_status", "no business on record")

    cfg = email_domain_settings(biz.get("settings"))
    domain = cfg.get("domain")
    domain_id = cfg.get("resend_domain_id")
    lines: List[str] = []
    next_step: Optional[str] = None
    nav = _nav("email-setup")

    # ── identity + DNS ──
    verified = False
    if not domain_id:
        lines.append(f"sending from the platform address ({DEFAULT_FROM_EMAIL}); "
                     f"no domain connected")
        next_step = "connect a domain in Build → Email Setup, step 1"
    else:
        live = await _live_status(str(domain_id))
        status = live or _normalize_status(cfg.get("status"))
        from_email = f"{cfg.get('from_local_part')}@{domain}"
        from_name = cfg.get("from_name") or biz.get("name") or ""
        stored_note = "" if live else " (provider unreachable — reporting the last known state)"
        if status == "verified":
            verified = True
            lines.append(f"sending as {from_name} <{from_email}>, verified{stored_note}")
        elif status == "missing":
            lines.append(f"{domain} no longer exists at the email provider — "
                         f"sending from the platform address")
            next_step = "disconnect and reconnect the domain in Build → Email Setup"
        elif cfg.get("drift_detected_at"):
            hrs = _hours_since(cfg.get("drift_detected_at"))
            when = (f"{int(hrs)}h ago" if hrs is not None and hrs < 48
                    else f"{int((hrs or 0) // 24)} days ago")
            lines.append(f"{domain} STOPPED verifying {when} — a DNS record is missing "
                         f"or changed; sending from the platform address until it's back"
                         f"{stored_note}")
            next_step = "open Build → Email Setup, step 2 to see which record"
        else:
            lines.append(f"{domain} connected, waiting on DNS — sending from the "
                         f"platform address until it verifies{stored_note}")
            next_step = "add the records in Build → Email Setup, step 2 (it checks every 30s)"

    # ── inbox ──
    try:
        boxes = await asyncio.to_thread(_mailboxes, business_id)
    except Exception as e:
        logger.warning(f"[email-setup] mailbox read failed (non-fatal): {e}")
        boxes = []
    if not boxes:
        lines.append("no inbox connected — mail sent straight to their address is "
                     "invisible to you")
        if verified and not next_step:
            next_step = "connect Gmail or Google Workspace in Build → Email Setup, step 3"
    else:
        stale = [b for b in boxes if (_hours_since(b.get("last_synced_at")) or 0) > STALE_SYNC_HOURS
                 or not b.get("last_synced_at")]
        names = ", ".join(str(b.get("google_email")) for b in boxes[:3])
        if stale and len(stale) == len(boxes):
            lines.append(f"inbox {names} connected but NOT syncing (no completed check in "
                         f"{STALE_SYNC_HOURS}h)")
            if not next_step:
                next_step = "reconnect the mailbox in Build → Email Setup, step 3"
        else:
            lines.append(f"inbox {names} connected and syncing; you read mail from contacts only")

    # ── test ──
    last_test = cfg.get("last_test") or {}
    if verified and last_test.get("identity") == "custom":
        lines.append(f"a test email landed from their own address "
                     f"({str(last_test.get('sent_at'))[:10]})")
    elif verified:
        lines.append("no test sent from the verified address yet")
        if not next_step:
            next_step = "send a test in Build → Email Setup, step 4 to prove it lands"

    ready = verified and bool(boxes)
    result = "; ".join(lines)
    if next_step:
        result += f". Next: {next_step}"
    label = ("✅ Email: live" if verified and not next_step
             else "📬 Email: live, one step left" if verified
             else "✉️ Email: not set up" if not domain_id
             else "⏳ Email: waiting on DNS")
    return {
        "type": "email_setup_status",
        "result": result,
        "label": label,
        "nav": nav,
        "signal": {"ready": ready, "verified": verified, "domain": domain,
                   "mailboxes": len(boxes), "next_step": next_step},
    }
