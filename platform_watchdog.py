"""
platform_watchdog.py — the system watching itself (beta-readiness arc,
2026-07-11).

Kevin: "agents to manage security of the system, bugs from issues,
users and tickets... chief on the backend sends messages to me in case
the system needs attention... autonomous connection."

One autonomous hourly sweep over the platform's own vitals:
  - external services: any registry entry missing its env keys
  - database: reachability + latency
  - stripe webhooks: unprocessed event backlog
  - support load: open tickets + queued BUILD requests
  - error pressure: server errors captured by the in-process ring
    buffer (which also closes the "backend error stream" blind spot)
    and client errors reported by the frontend

Findings flow three ways (the "autonomous connection"):
  1. platform_changelog rows (agent='watchdog') — Mission Control's
     operator log, same rail Hermes uses.
  2. Web push to the PLATFORM OWNER's devices for critical findings
     (deduped: one alert per finding-code per 22h) — Chief's backend
     voice reaching Kevin's phone.
  3. GET /platform/watchdog — the live snapshot Mission Control renders.

Ring buffer: attach_error_buffer() hooks a logging.Handler on the root
logger at WARNING+; the last 400 records are queryable via
GET /platform/errors. POST /telemetry/client-error (rate-limited,
auth'd) feeds frontend errors into the same buffer tagged [client].

Kill switch: PLATFORM_WATCHDOG=off.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("platform_watchdog")

OWNER_EMAIL = (os.environ.get("PLATFORM_OWNER_EMAIL")
               or "kmjcreativesolution@gmail.com").lower()
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)


def watchdog_enabled() -> bool:
    return (os.environ.get("PLATFORM_WATCHDOG") or "on").strip().lower() not in (
        "0", "off", "false", "no")


# ─── Error ring buffer ────────────────────────────────────────────────
# WARNING+ records from EVERY logger land here (the root handler sees
# propagated records), giving Mission Control a live error stream
# without any external service.

_ERRORS: Deque[Dict[str, Any]] = deque(maxlen=400)
_ATTACHED = False


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name == "platform_watchdog":
                return  # never self-amplify
            _ERRORS.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage()[:500],
            })
        except Exception:
            pass  # a logging handler must never throw


def attach_error_buffer() -> None:
    """Idempotent: hook the ring handler onto the root logger."""
    global _ATTACHED
    if _ATTACHED:
        return
    h = _RingHandler(level=logging.WARNING)
    logging.getLogger().addHandler(h)
    _ATTACHED = True


def recent_errors(limit: int = 100) -> List[Dict[str, Any]]:
    return list(_ERRORS)[-max(1, min(limit, 400)):][::-1]


def record_client_error(message: str, source: str = "") -> None:
    """Frontend error reports enter the same stream, tagged [client]."""
    _ERRORS.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": "ERROR",
        "logger": "client",
        "message": f"[client]{f' {source}' if source else ''} {message}"[:500],
    })


# ─── The sweep ────────────────────────────────────────────────────────

LAST_SWEEP: Dict[str, Any] = {}
_LAST_ALERTED: Dict[str, float] = {}       # finding code → epoch seconds
_ALERT_COOLDOWN_S = 22 * 3600
_OWNER_USER_ID: Optional[str] = None


async def _count(c: httpx.AsyncClient, headers: Dict[str, str],
                 path: str, params: Optional[Dict[str, str]] = None) -> int:
    r = await c.head(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={**headers, "Prefer": "count=exact", "Range": "0-0"},
        params=params or {},
    )
    if r.status_code in (200, 206):
        cr = r.headers.get("content-range", "")
        total = cr.split("/")[-1] if "/" in cr else "0"
        try:
            return int(total) if total and total != "*" else 0
        except ValueError:
            return 0
    return -1  # table missing / error — caller decides


async def watchdog_sweep() -> Dict[str, Any]:
    """One pass over the platform's vitals. Never raises."""
    headers = _service_headers()
    findings: List[Dict[str, str]] = []

    def finding(severity: str, code: str, message: str) -> None:
        findings.append({"severity": severity, "code": code, "message": message})

    # 1. Service registry — anything unconfigured?
    try:
        from platform_console import _api_registry_status
        for svc in _api_registry_status():
            if not svc["configured"]:
                finding("critical", f"svc:{svc['id']}",
                        f"{svc['name']} is missing env keys: {', '.join(svc['missing_envs'])}")
    except Exception as e:
        finding("warn", "svc:registry", f"registry check failed: {e}")

    db_latency_ms: Optional[float] = None
    webhook_backlog = 0
    open_tickets = 0
    build_queue = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        # 2. Database reachability + latency
        try:
            t0 = time.time()
            n = await _count(c, headers, "businesses")
            db_latency_ms = round((time.time() - t0) * 1000, 1)
            if n < 0:
                finding("critical", "db:reach", "database count query failed")
            elif db_latency_ms > 3000:
                finding("warn", "db:slow", f"database latency {db_latency_ms}ms")
        except Exception as e:
            finding("critical", "db:reach", f"database unreachable: {e}")

        # 3. Stripe webhook backlog
        try:
            webhook_backlog = max(0, await _count(
                c, headers, "stripe_webhook_events", {"processed_at": "is.null"}))
            if webhook_backlog > 5:
                finding("warn", "stripe:backlog",
                        f"{webhook_backlog} unprocessed Stripe webhook events")
        except Exception:
            pass

        # 4. Support load — open tickets + the BUILD queue
        try:
            open_tickets = max(0, await _count(
                c, headers, "support_tickets", {"status": "eq.open"}))
            build_queue = max(0, await _count(
                c, headers, "support_tickets",
                {"status": "eq.open", "subject": "like.BUILD:*"}))
            if open_tickets >= 10:
                finding("warn", "support:load",
                        f"{open_tickets} open support tickets")
        except Exception:
            pass

    # 5. Error pressure — last hour, from the ring buffer
    cutoff = datetime.now(timezone.utc).timestamp() - 3600
    recent = [e for e in _ERRORS
              if _ts_epoch(e.get("ts")) >= cutoff and e.get("level") == "ERROR"]
    server_errors = [e for e in recent if e.get("logger") != "client"]
    client_errors = [e for e in recent if e.get("logger") == "client"]
    if len(server_errors) >= 10:
        finding("critical", "errors:server",
                f"{len(server_errors)} server errors in the last hour "
                f"(latest: {server_errors[-1]['message'][:120]})")
    if len(client_errors) >= 15:
        finding("warn", "errors:client",
                f"{len(client_errors)} client errors in the last hour")

    snapshot = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "ok": not any(f["severity"] == "critical" for f in findings),
        "findings": findings,
        "db_latency_ms": db_latency_ms,
        "webhook_backlog": webhook_backlog,
        "open_tickets": open_tickets,
        "build_queue": build_queue,
        "errors_last_hour": {"server": len(server_errors), "client": len(client_errors)},
    }
    LAST_SWEEP.clear()
    LAST_SWEEP.update(snapshot)
    return snapshot


def _ts_epoch(ts: Optional[str]) -> float:
    try:
        return datetime.fromisoformat((ts or "").replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# ─── Owner alerting (Chief's backend voice → Kevin's phone) ───────────

async def _owner_user_id(c: httpx.AsyncClient, headers: Dict[str, str]) -> Optional[str]:
    global _OWNER_USER_ID
    if _OWNER_USER_ID:
        return _OWNER_USER_ID
    try:
        r = await c.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers=headers, params={"per_page": "200"},
        )
        if r.status_code == 200:
            users = r.json().get("users", r.json()) or []
            for u in users:
                if (u.get("email") or "").lower() == OWNER_EMAIL:
                    _OWNER_USER_ID = u.get("id")
                    break
    except Exception as e:
        logger.warning(f"owner lookup failed: {e}")
    return _OWNER_USER_ID


async def _log_finding(c: httpx.AsyncClient, headers: Dict[str, str],
                       title: str, detail: str, pending: bool) -> None:
    """Same operator-log rail Hermes uses (platform_changelog)."""
    try:
        await c.post(
            f"{SUPABASE_URL}/rest/v1/platform_changelog",
            headers={**headers, "Prefer": "return=minimal"},
            json={"category": "pending" if pending else "note",
                  "status": "pending" if pending else "done",
                  "title": title[:300], "detail": detail[:2000],
                  "agent": "watchdog"},
        )
    except Exception as e:
        logger.warning(f"changelog write failed: {e}")


async def watchdog_tick() -> Dict[str, Any]:
    """The autonomous hourly pass: sweep → operator log → owner push.
    Never raises (scheduler-safe)."""
    if not watchdog_enabled():
        return {"skipped": True}
    try:
        snap = await watchdog_sweep()
    except Exception as e:
        logger.warning(f"sweep failed: {e}")
        return {"error": str(e)}

    criticals = [f for f in snap["findings"] if f["severity"] == "critical"]
    now = time.time()
    fresh = [f for f in criticals
             if now - _LAST_ALERTED.get(f["code"], 0) > _ALERT_COOLDOWN_S]

    if fresh:
        headers = _service_headers()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            for f in fresh:
                _LAST_ALERTED[f["code"]] = now
                await _log_finding(
                    c, headers,
                    f"Watchdog: {f['message'][:120]}",
                    f"code={f['code']} severity={f['severity']}\n{f['message']}",
                    pending=True,
                )
            # One push per tick, summarizing — not one per finding.
            owner = await _owner_user_id(c, headers)
        if owner:
            try:
                from push_notifications import send_to_user
                head = fresh[0]["message"][:90]
                more = f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else ""
                send_to_user(
                    owner,
                    title="⚠ The system needs your attention",
                    body=f"{head}{more} — details in Mission Control.",
                    nav="studio",
                    tag="watchdog",
                )
            except Exception as e:
                logger.warning(f"owner push failed: {e}")

    logger.info(
        f"watchdog: ok={snap['ok']} findings={len(snap['findings'])} "
        f"alerted={len(fresh)}")
    return snap


# ─── Client-error intake (any signed-in user; rate-limited) ──────────

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from auth_supabase import AuthedUser, require_user

telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])

try:
    from booking_widget_router import _rate_limit
except Exception:  # pragma: no cover
    def _rate_limit(_label: str, _req) -> None:
        pass


class ClientErrorBody(BaseModel):
    message: str
    source: str = ""


@telemetry_router.post("/client-error")
def client_error(body: ClientErrorBody, request: Request,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Frontend window.onerror / unhandledrejection reports. Feeds the
    same ring buffer the watchdog reads — closes the 'frontend client
    errors' blind spot with zero external services."""
    _rate_limit("telemetry/client-error", request)
    msg = (body.message or "").strip()[:400]
    if msg:
        record_client_error(msg, source=(body.source or "").strip()[:120])
    return {"ok": True}
