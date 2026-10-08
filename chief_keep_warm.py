"""
chief_keep_warm.py — keep Chief's cached brief alive while a business is using it (2026-10-07).

Chief sends a ~100k-token brief with every message. Anthropic keeps the
cached copy for an hour after its last use; the first message after that
re-writes it at twice the input price (~35c on KMJ's brief), and over 30
days 37 of those re-writes came 1-4 hours after the business's previous
message. A read of the cached copy costs a twentieth of the input price on
Sonnet 5.5 and resets its hour, so a ping with no reply (max_tokens 0)
every 55 minutes costs ~1c and one re-write pays for ~40 of them.

The ping only runs while the business is active: it is scheduled after each
main Chief call and stops WINDOW minutes after the last one (default 4 h).
A business that uses Chief most days keeps it warm for 24 hours instead,
through the night, so its first message of the day is a read (~10c) and not
a re-write (~44c). Simulated on the 30 days to 2026-10-07: the cold starts
and pings of every business cost $37.27 with no keep-warm, $25.52 at 4 h for
everyone and $18.56 at 24 h; the long window is only for daily users, so a
business that tried Chief once doesn't buy a day of pings.
It re-sends exactly what the last call had in front of its 1-hour cache
breakpoints (model, effort, tools, the cached system blocks) and nothing
after them, so it reads and never writes. If a ping ever writes (the copy
was gone or the brief moved), it stops for that business instead of paying
for a copy nobody may read.

Verified against the API on 2026-10-07 with a Chief-shaped request: the
ping read all 23,377 cached tokens, wrote none, returned no output, and the
next real call read the whole prefix back.

Pings cost the platform, never the practitioner: their api_usage rows carry
units=0. CHIEF_KEEP_WARM=off turns the whole thing off without a deploy.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("chief.keep_warm")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] chief.keep_warm: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_tasks: Dict[str, "asyncio.Task"] = {}
# A ping that writes more than this found no copy to read: stop, don't pay again.
WRITE_STOP_TOKENS = 2000


def enabled() -> bool:
    return (os.environ.get("CHIEF_KEEP_WARM") or "on").strip().lower() not in ("off", "0", "false", "no")


def _minutes(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name) or default))
    except (TypeError, ValueError):
        return default


def every_s() -> float:
    return _minutes("CHIEF_KEEP_WARM_EVERY_MIN", 55) * 60


def window_s() -> float:
    return _minutes("CHIEF_KEEP_WARM_WINDOW_MIN", 240) * 60


def daily_window_s() -> float:
    return _minutes("CHIEF_KEEP_WARM_DAILY_WINDOW_MIN", 1440) * 60


# business id -> (UTC date checked, daily user?)
_daily: Dict[str, Any] = {}


def _daily_user(business_id: str) -> bool:
    """Used Chief on at least CHIEF_KEEP_WARM_DAILY_DAYS (default 3) of the
    last 7 days. Read once a day per business; any failure says no."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    hit = _daily.get(business_id)
    if hit and hit[0] == today:
        return hit[1]
    try:
        need = int(os.environ.get("CHIEF_KEEP_WARM_DAILY_DAYS") or 3)
    except ValueError:
        need = 3
    answer = False
    try:
        import sb_clients
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}&endpoint=eq./chief/backend"
            f"&created_at=gte.{since}&select=created_at&order=created_at.desc&limit=2000") or []
        days = {str(r.get("created_at") or "")[:10] for r in rows if isinstance(r, dict)}
        days.discard("")
        answer = len(days) >= need
    except Exception as e:  # a failed read keeps the short window
        logger.info("keep-warm biz=%s: daily-use read failed (%s)", business_id[:8], type(e).__name__)
    _daily[business_id] = (today, answer)
    return answer


def window_for(business_id: str) -> float:
    """How long this business's brief stays warm after its last call."""
    base = window_s()
    if _daily_user(business_id):
        return max(base, daily_window_s())
    return base


def ping_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The last call's request cut at its last 1-hour cache breakpoint, with
    no reply asked for. None when nothing in it is cached for an hour."""
    system = (payload or {}).get("system")
    if not isinstance(system, list):
        return None
    last = -1
    for i, block in enumerate(system):
        cc = block.get("cache_control") if isinstance(block, dict) else None
        if isinstance(cc, dict) and cc.get("ttl") == "1h":
            last = i
    if last < 0:
        return None
    out: Dict[str, Any] = {"model": payload.get("model"), "max_tokens": 0,
                           "system": copy.deepcopy(system[:last + 1]),
                           "messages": [{"role": "user", "content": "."}]}
    for key in ("tools", "output_config", "thinking"):
        if key in payload:
            out[key] = copy.deepcopy(payload[key])
    return out


def remember(business_id: Optional[str], payload: Dict[str, Any],
             headers: Optional[Dict[str, str]] = None) -> bool:
    """Called after each main Chief call: (re)start this business's pings."""
    if not business_id or not enabled():
        return False
    ping = ping_payload(payload)
    if ping is None:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    b = str(business_id)
    old = _tasks.pop(b, None)
    if old is not None and not old.done():
        old.cancel()
    _tasks[b] = loop.create_task(_keep_warm(b, ping, dict(headers or {})))
    return True


async def _keep_warm(business_id: str, ping: Dict[str, Any], headers: Dict[str, str]) -> None:
    started = time.monotonic()
    try:
        window = await asyncio.to_thread(window_for, business_id)
        while True:
            await asyncio.sleep(every_s())
            if time.monotonic() - started > window:
                logger.info("keep-warm biz=%s: idle past the window, stopping", business_id[:8])
                return
            if not await _ping(business_id, ping, headers):
                return
    except asyncio.CancelledError:
        pass
    finally:
        if _tasks.get(business_id) is asyncio.current_task():
            _tasks.pop(business_id, None)


async def _ping(business_id: str, ping: Dict[str, Any], headers: Dict[str, str]) -> bool:
    """One no-reply read of the cached brief. False = stop pinging."""
    try:
        import httpx
        import llm_call
        import spend_guard
        if not llm_call.api_key():
            return False
        if await asyncio.to_thread(spend_guard.over_budget, business_id):
            return False
        async with httpx.AsyncClient() as client:
            resp = await llm_call.apost(client, ping, timeout=httpx.Timeout(30.0, connect=5.0),
                                        extra_headers=headers or None, task="chief_keep_warm",
                                        business_id=business_id, units=0)
        if resp.status_code >= 400:
            logger.warning("keep-warm biz=%s: ping refused (%s), stopping", business_id[:8], resp.status_code)
            return False
        usage = (resp.json() or {}).get("usage") or {}
        read = int(usage.get("cache_read_input_tokens") or 0)
        wrote = int(usage.get("cache_creation_input_tokens") or 0)
        logger.info("keep-warm biz=%s: read %d, wrote %d", business_id[:8], read, wrote)
        if wrote > WRITE_STOP_TOKENS:
            logger.info("keep-warm biz=%s: the copy was gone (wrote %d), stopping", business_id[:8], wrote)
            return False
        return True
    except Exception as e:  # never let a ping touch anything else
        logger.warning("keep-warm biz=%s: ping failed (%s), stopping", business_id[:8], type(e).__name__)
        return False
