"""
spend_guard.py — account-wide daily AI-spend circuit breaker.

Beta-readiness audit (AI-spend stream): nothing summed total dollars or
stopped a runaway. The dormant per-business billing caps don't help —
they're per-tenant, per-month, and blind to the unmetered paths. This
is the overnight backstop: one shared daily-dollar ceiling, checked at
the top of the paid AI entry points, that soft-blocks new AI calls and
pushes an alert to the owner when the day's spend crosses the line.

Fail-OPEN by doctrine: any error in the check ALLOWS the call. A
bookkeeping hiccup must never brick Chief. The ceiling is a backstop
against runaways, not a billing gate.

Env:
  DAILY_SPEND_CAP_USD   daily hard ceiling in dollars (default 50).
  SPEND_GUARD           'off' disables the block entirely (still logs).
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import sb_clients

logger = logging.getLogger("spend_guard")

# In-process cache so we don't sum api_usage on every single AI call.
# 60s is fine — a runaway takes minutes to matter, and this bounds the
# extra query load to at most one per minute per instance.
_CACHE_TTL_S = 60
_cache_cents: float = 0.0
_cache_at: float = 0.0

# Alert dedup: one owner push per threshold per UTC day.
_alerted: dict = {}


def _cap_cents() -> float:
    try:
        return float(os.environ.get("DAILY_SPEND_CAP_USD", "50")) * 100.0
    except (TypeError, ValueError):
        return 5000.0


def _enabled() -> bool:
    return (os.environ.get("SPEND_GUARD") or "on").strip().lower() != "off"


def _utc_day_start_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def today_spend_cents(force: bool = False) -> float:
    """Sum of api_usage.cost_cents since UTC midnight. Cached 60s.
    Fails open to 0.0 (never blocks on a read error)."""
    global _cache_cents, _cache_at
    now = time.time()
    if not force and (now - _cache_at) < _CACHE_TTL_S:
        return _cache_cents
    try:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?created_at=gte.{_utc_day_start_iso()}"
            f"&select=cost_cents&limit=100000") or []
        total = sum(float(r.get("cost_cents") or 0) for r in rows)
        _cache_cents, _cache_at = total, now
        return total
    except Exception as e:
        logger.warning(f"[spend_guard] read failed open: {e}")
        return 0.0


def over_budget() -> bool:
    """True only when spend is over the ceiling AND the guard is on.
    Never raises."""
    try:
        if not _enabled():
            return False
        spent = today_spend_cents()
        cap = _cap_cents()
        _maybe_alert(spent, cap)
        return spent >= cap
    except Exception as e:
        logger.warning(f"[spend_guard] over_budget failed open: {e}")
        return False


def _maybe_alert(spent: float, cap: float) -> None:
    """Push the owner one alert per threshold (50/80/100%) per UTC day."""
    if cap <= 0:
        return
    day = datetime.now(timezone.utc).date().isoformat()
    pct = spent / cap
    for mark in (1.0, 0.8, 0.5):
        if pct >= mark:
            key = f"{day}:{mark}"
            if key in _alerted:
                return  # highest crossed threshold already alerted today
            _alerted[key] = True
            _push_owner(spent, cap, mark)
            return


def _push_owner(spent: float, cap: float, mark: float) -> None:
    try:
        import asyncio
        import httpx
        import platform_watchdog as wd
        import push_notifications
        from lead_admin import _service_headers

        dollars = spent / 100.0
        cap_dollars = cap / 100.0
        pct_txt = f"{int(mark * 100)}%"
        crossed = "reached the daily AI-spend ceiling" if mark >= 1.0 else f"passed {pct_txt} of the daily AI-spend ceiling"
        note = (f"Today's AI spend is ${dollars:.2f} of the ${cap_dollars:.0f} "
                f"daily cap ({crossed}). "
                + ("New AI calls are paused until UTC midnight or you raise "
                   "DAILY_SPEND_CAP_USD." if mark >= 1.0
                   else "Heads up — still running normally."))

        async def _go():
            headers = _service_headers()
            async with httpx.AsyncClient(timeout=15) as c:
                await wd._log_finding(
                    c, headers,
                    f"AI spend at {pct_txt} of daily cap",
                    note, pending=(mark >= 1.0))
                owner = await wd._owner_user_id(c, headers)
            if owner:
                push_notifications.send_to_user(
                    owner,
                    title=("AI spend paused — daily cap hit" if mark >= 1.0
                           else f"AI spend at {pct_txt} of cap"),
                    body=note, nav="studio")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_go())
        except RuntimeError:
            asyncio.run(_go())
    except Exception as e:
        logger.warning(f"[spend_guard] owner alert failed (non-fatal): {e}")


def block_message() -> str:
    """The friendly reason returned to a caller when blocked."""
    return ("AI is paused for the rest of the day — the account hit its "
            "daily usage ceiling. It resets automatically, or the owner "
            "can raise the limit.")
