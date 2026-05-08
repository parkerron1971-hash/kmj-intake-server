"""Pass 3.8g — hard cost-cap circuit breaker for Builder generation.

System-wide daily counter, locked, resets at midnight UTC. Returns 503
when hit so the front-end + endpoints can show a friendly message.

Process-local: the counter lives in this Python module, so a Railway
redeploy resets it. That is intentional for v1 — a redeploy is rare
and effectively a manual reset. If the counter ever needs to survive
restarts, swap _daily_counter for a Redis/Supabase row.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Tuple


_lock = threading.Lock()
_daily_counter: dict = defaultdict(int)
_last_reset_date: str = ""

# Single tunable. The 4-page multi-page generation costs 4 records.
# 50 records ≈ 12 single-page regens or ~12 multi-page regens.
DAILY_BUILDER_CAP = 50


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _maybe_reset() -> None:
    """Clear the counter when the UTC date rolls. Caller must hold _lock."""
    global _last_reset_date
    today = _today_key()
    if today != _last_reset_date:
        _daily_counter.clear()
        _last_reset_date = today


def can_generate() -> Tuple[bool, int, int]:
    """Returns (allowed, current_count, cap)."""
    with _lock:
        _maybe_reset()
        current = _daily_counter[_today_key()]
        return current < DAILY_BUILDER_CAP, current, DAILY_BUILDER_CAP


def record_generation() -> None:
    """Increment the daily counter. Call exactly once per Builder run."""
    with _lock:
        _maybe_reset()
        _daily_counter[_today_key()] += 1


def get_status() -> dict:
    """Diagnostic snapshot. Used by /system/cost-cap-status."""
    with _lock:
        _maybe_reset()
        today = _today_key()
        current = _daily_counter[today]
        return {
            "date": today,
            "generations_today": current,
            "cap": DAILY_BUILDER_CAP,
            "remaining": max(0, DAILY_BUILDER_CAP - current),
        }
