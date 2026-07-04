"""
hermes_agent.py — Hermes, the communications watcher (2026-07-04).

THE PATTERN (Kevin's ruling): one brain, many senses. Hermes is a
SENSE — a deterministic scheduled tick that LOOKS at the comms rails
and writes findings; it never converses and never spends LLM tokens.
The Business Chief is the one intelligence: it reads Hermes' findings
from the operator log (platform_changelog, agent='hermes') in every
snapshot and narrates them to Kevin with context.

THE BEAT (what Hermes watches, each tick):
  1. SMS delivery failures in the last 24h (status='failed')
  2. Inbound texts sitting UNREAD > 4h — per business (practitioners
     leaving customers hanging = churn signal)
  3. Outbound stuck at 'sent' > 24h (never confirmed delivered —
     meaningful once the Twilio status callback is live)
  4. Suppression growth: sms_opt_outs + email_suppressions vs the
     previous run (velocity, not just totals)
  5. Config posture: Twilio configured? auth token present?

THE FLOW (visible in Mission Control → Agents):
  Hermes tick → platform_agent_runs (every run, findings or not)
             → platform_changelog[agent=hermes] (only when something
               needs eyes — no noise)
             → Business Chief snapshot (operator_log) → Kevin.

Runs hourly via the shared APScheduler (kmj_intake_automation), plus
POST /platform/agents/hermes/run for a manual tick from the console.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("hermes")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] hermes: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)

AGENT = "hermes"
UNREAD_STALE_HOURS = 4
STUCK_SENT_HOURS = 24


async def _count(c: httpx.AsyncClient, headers: Dict[str, str],
                 table: str, params: Dict[str, str]) -> int:
    try:
        r = await c.head(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
            params=params,
        )
        if r.status_code in (200, 206):
            cr = r.headers.get("content-range", "")
            last = cr.split("/")[-1] if "/" in cr else "0"
            return int(last) if last and last != "*" else 0
    except Exception:
        pass
    return 0


async def _last_run_details(c: httpx.AsyncClient, headers: Dict[str, str]) -> Dict[str, Any]:
    try:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
            headers=headers,
            params={"agent": f"eq.{AGENT}", "select": "details",
                    "order": "started_at.desc", "limit": "1"},
        )
        if r.status_code < 400 and r.json():
            return (r.json()[0] or {}).get("details") or {}
    except Exception:
        pass
    return {}


async def _log_finding(c: httpx.AsyncClient, headers: Dict[str, str],
                       title: str, detail: str, pending: bool = False) -> None:
    try:
        await c.post(
            f"{SUPABASE_URL}/rest/v1/platform_changelog",
            headers={**headers, "Prefer": "return=minimal"},
            json={"category": "pending" if pending else "note",
                  "status": "pending" if pending else "done",
                  "title": title[:300], "detail": detail[:2000],
                  "agent": AGENT},
        )
    except Exception as e:
        logger.warning(f"finding write failed: {e}")


async def hermes_tick() -> Dict[str, Any]:
    """One full watch pass. Always records a run row; writes findings
    only when something needs eyes. Never raises."""
    headers = _service_headers()
    started = datetime.now(timezone.utc)
    findings: List[str] = []
    details: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            prev = await _last_run_details(c, headers)
            now = datetime.now(timezone.utc)

            # 1. Delivery failures (24h)
            since_24h = (now - timedelta(hours=24)).isoformat()
            failed = await _count(c, headers, "sms_messages", {
                "status": "eq.failed", "created_at": f"gte.{since_24h}"})
            details["sms_failed_24h"] = failed
            if failed > 0:
                findings.append(f"{failed} SMS delivery failure{'s' if failed != 1 else ''} in the last 24h")
                await _log_finding(
                    c, headers,
                    f"Hermes: {failed} SMS delivery failure{'s' if failed != 1 else ''} (24h)",
                    "Check Twilio Monitor → Logs for error codes (30034 = A2P registration; "
                    "30007 = carrier filtering). If the campaign is still in review, failures "
                    "are expected until approval.",
                    pending=failed >= 3,
                )

            # 2. Unanswered inbound (> 4h, still unread)
            stale_cutoff = (now - timedelta(hours=UNREAD_STALE_HOURS)).isoformat()
            unanswered = await _count(c, headers, "sms_messages", {
                "direction": "eq.inbound", "read": "eq.false",
                "created_at": f"lt.{stale_cutoff}"})
            details["inbound_unread_stale"] = unanswered
            if unanswered > 0:
                findings.append(f"{unanswered} inbound text{'s' if unanswered != 1 else ''} unanswered > {UNREAD_STALE_HOURS}h")
                await _log_finding(
                    c, headers,
                    f"Hermes: {unanswered} customer text{'s' if unanswered != 1 else ''} unanswered for {UNREAD_STALE_HOURS}+ hours",
                    "Customers texting and hearing nothing is a churn signal for the practitioner "
                    "and a platform-quality signal for us. Consider nudging the practitioner(s).",
                )

            # 3. Stuck at 'sent' (> 24h, no delivery confirmation)
            stuck_cutoff = (now - timedelta(hours=STUCK_SENT_HOURS)).isoformat()
            stuck = await _count(c, headers, "sms_messages", {
                "direction": "eq.outbound", "status": "eq.sent",
                "created_at": f"lt.{stuck_cutoff}"})
            details["outbound_stuck_sent"] = stuck
            # Only noteworthy once status callbacks are flowing — report
            # when SOME messages do reach 'delivered' but these didn't.
            delivered_ever = await _count(c, headers, "sms_messages", {
                "status": "eq.delivered", "limit": "1"})
            if stuck > 0 and delivered_ever > 0:
                findings.append(f"{stuck} outbound message{'s' if stuck != 1 else ''} never confirmed delivered")
                await _log_finding(
                    c, headers,
                    f"Hermes: {stuck} outbound SMS stuck at 'sent' > {STUCK_SENT_HOURS}h",
                    "Delivery confirmations flow for other messages, so these likely failed "
                    "silently. Check the Twilio status callback wiring and Monitor logs.",
                )

            # 4. Suppression velocity (vs previous run)
            sms_opt_outs = await _count(c, headers, "sms_opt_outs", {})
            email_sup = await _count(c, headers, "email_suppressions", {})
            details["sms_opt_outs_total"] = sms_opt_outs
            details["email_suppressions_total"] = email_sup
            d_sms = sms_opt_outs - int(prev.get("sms_opt_outs_total") or 0)
            d_email = email_sup - int(prev.get("email_suppressions_total") or 0)
            if prev and (d_sms >= 3 or d_email >= 3):
                findings.append(f"suppressions jumped (+{max(d_sms, 0)} SMS, +{max(d_email, 0)} email)")
                await _log_finding(
                    c, headers,
                    f"Hermes: opt-outs/suppressions jumped since last check (+{max(d_sms, 0)} SMS, +{max(d_email, 0)} email)",
                    "A spike usually means a broadcast landed badly or content reads as spam. "
                    "Review what was sent in the window before this run.",
                    pending=True,
                )

            # 5. Config posture (informational, in details only)
            details["twilio_configured"] = all(
                (os.environ.get(k) or "").strip()
                for k in ("TWILIO_ACCOUNT_SID", "TWILIO_API_KEY_SID",
                          "TWILIO_API_KEY_SECRET", "TWILIO_MESSAGING_SERVICE_SID"))
            details["twilio_auth_token_set"] = bool((os.environ.get("TWILIO_AUTH_TOKEN") or "").strip())

            # Record the run — every tick, findings or not.
            summary = "; ".join(findings) if findings else "all quiet on the comms rails"
            await c.post(
                f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                headers={**headers, "Prefer": "return=minimal"},
                json={"agent": AGENT,
                      "started_at": started.isoformat(),
                      "finished_at": datetime.now(timezone.utc).isoformat(),
                      "ok": True, "findings": len(findings),
                      "summary": summary[:500], "details": details},
            )
        logger.info(f"tick complete — {len(findings)} finding(s): {summary[:200]}")
        return {"ok": True, "findings": len(findings), "summary": summary, "details": details}
    except Exception as e:
        logger.error(f"tick failed: {e}")
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                await c.post(
                    f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                    headers={**headers, "Prefer": "return=minimal"},
                    json={"agent": AGENT, "started_at": started.isoformat(),
                          "finished_at": datetime.now(timezone.utc).isoformat(),
                          "ok": False, "findings": 0, "summary": f"tick failed: {e}"[:500]},
                )
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:300]}
