"""
chief_keep_warm.py — keep Chief's cached brief alive while a business is using it (2026-10-07).

Chief sends a ~100k-token brief with every message. Anthropic keeps the
cached copy for an hour after its last use; the first message after that
re-writes it at twice the input price (~35c on KMJ's brief), and over 30
days 37 of those re-writes came 1-4 hours after the business's previous
message. A read of the cached copy costs a twentieth of the input price on
Sonnet 5.5 and resets its hour, so a ping with no reply (max_tokens 0)
every 50 minutes costs ~1c and one re-write pays for ~40 of them.

The ping only runs while the business is active: it is set up after each
main Chief call and stops WINDOW minutes after the last one (default 4 h).
A business that uses Chief most days keeps it warm for 24 hours instead,
so a message hours later is a read (~10c) and not a re-write (~44c).
Simulated on the 30 days to 2026-10-07: the cold starts and pings of every
business cost $37.27 with no keep-warm, $25.52 at 4 h for everyone and
$18.56 at 24 h; the long window is only for daily users, so a business
that tried Chief once doesn't buy a day of pings.
It re-sends exactly what the last call had in front of its 1-hour cache
breakpoints (model, effort, tools, the cached system blocks) and nothing
after them, so it reads and never writes. If a ping ever writes (the copy
was gone or the brief moved), it stops for that business instead of paying
for a copy nobody may read.

Verified against the API on 2026-10-07 with a Chief-shaped request: the
ping read all 23,377 cached tokens, wrote none, returned no output, and the
next real call read the whole prefix back.

Held in the database since 2026-11-03. The pings were asyncio tasks in the
web process, and every merge to main restarts it: 475 deploys in the 30
days to 2026-11-03, a median of 26 minutes apart, against a first ping due
55 minutes after a message. 33 pings went out in those 30 days; 4 of the 5
messages that came 1-4 h after the last one were full re-writes, and each
of the 4 had a deploy land 3 to 42 minutes after that last message, before
its first ping. Now the web writes the ping to chief_keep_warm after each
main call (record) and the worker sends it (tick, every TICK_MIN minutes,
scheduler leader only), so a deploy of either service costs a tick, not
the copy. Each ping claims the row on its touched_at, so two workers never
ping the same copy, and a message that lands meanwhile keeps its own
chain. The ping is stored as the JSON text it was sent as: a tool schema
with its keys in another order is another prompt to the cache. Until
supabase/APPLY-2026-11-03-chief-keep-warm.sql is applied, the web keeps
its in-process pings as before.

Never across 00:00 UTC. The cached copy is gone after midnight UTC more or
less every time: all 3 pings that crossed it in the 30 days found no copy
and paid for a whole new one (25c-45c each) while the 30 other pings read,
and 2 of the 3 real calls under 55 minutes apart across it were full
re-writes, against 57 of 1,226 otherwise. A ping there buys a copy nobody
may read, so the chain ends at the last ping before midnight UTC and the
day's first message writes its own.

Pings cost the platform, never the practitioner: their api_usage rows carry
units=0. CHIEF_KEEP_WARM=off turns the whole thing off without a deploy.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

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
TABLE = "chief_keep_warm"
# How often the worker looks for a copy that is due.
TICK_MIN = 2
# A copy last used this long ago may already be gone (its hour runs from
# the API's use, a moment before we note it), and a ping then could pay
# for a whole new one: the chain ends instead.
LATE_S = 56 * 60
# Pings the worker sends at once.
_PARALLEL = 8


def enabled() -> bool:
    return (os.environ.get("CHIEF_KEEP_WARM") or "on").strip().lower() not in ("off", "0", "false", "no")


def _minutes(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name) or default))
    except (TypeError, ValueError):
        return default


def every_s() -> float:
    """How old the cached copy gets before a ping reads it: 50 minutes, and
    never more than 52, so the worker's 2-minute look gets a second try
    before LATE_S (a tick lost to a deploy, a busy API)."""
    return min(_minutes("CHIEF_KEEP_WARM_EVERY_MIN", 50), 52.0) * 60


def window_s() -> float:
    return _minutes("CHIEF_KEEP_WARM_WINDOW_MIN", 240) * 60


def daily_window_s() -> float:
    return _minutes("CHIEF_KEEP_WARM_DAILY_WINDOW_MIN", 1440) * 60


def crosses_midnight(last_used: datetime, now: datetime) -> bool:
    """Whether 00:00 UTC came between the copy's last use and now: the copy
    is gone after it, so a ping would pay to write a new one."""
    return last_used.astimezone(timezone.utc).date() != now.astimezone(timezone.utc).date()


# business id -> (UTC date checked, daily user?)
_daily: Dict[str, Any] = {}


def _daily_user(business_id: str) -> bool:
    """Used Chief on at least CHIEF_KEEP_WARM_DAILY_DAYS (default 3) of the
    last 7 days. Read once a day per business; any failure says no."""
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


# ─── Held in the database (2026-11-03) ───────────────────────────────

_table: Dict[str, Any] = {}


def table_state() -> Optional[bool]:
    """True when chief_keep_warm answers (remembered once it does); False
    when it doesn't but businesses does (the file isn't applied; asked again
    in 10 minutes); None when the probe itself failed."""
    if _table.get("ok"):
        return True
    if _table.get("missing_until", 0) > time.time():
        return False
    try:
        import sb_clients
        if isinstance(sb_clients.sb_get_as_service(f"/{TABLE}?select=business_id&limit=1"), list):
            _table["ok"] = True
            return True
        base = sb_clients.sb_get_as_service("/businesses?select=id&limit=1")
    except Exception:
        return None
    if isinstance(base, list):
        _table["missing_until"] = time.time() + 600
        return False
    return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _q(value: Any) -> str:
    """A PostgREST filter value: a timestamp's + must reach it as %2B."""
    return quote(str(value), safe="")


def ping_text(ping: Dict[str, Any]) -> str:
    """The ping as stored: JSON text in the order it was sent."""
    return json.dumps(ping, ensure_ascii=False, separators=(",", ":"))


def prefix_hash(text: str, headers: Dict[str, str]) -> str:
    return hashlib.sha256((text + "\n" + json.dumps(headers or {}, sort_keys=True)).encode("utf-8")).hexdigest()


# business id -> the prefix_hash this process last stored (the ping is
# ~0.5 MB: it's sent again only when it changed)
_stored: Dict[str, str] = {}
# business id -> the newest remember() call, so an older write that lands
# late never replaces a newer brief
_latest: Dict[str, int] = {}
_locks: Dict[str, threading.Lock] = {}
_seq = 0


def record(business_id: str, ping: Dict[str, Any], headers: Dict[str, str],
           seq: Optional[int] = None) -> bool:
    """Hand this business's ping to the worker: write it to chief_keep_warm,
    the call just now as its last use, the window running from it. True when
    the row is written (or a newer call's write is on its way); False when
    the table isn't there or the write failed, and the caller pings in this
    process as before."""
    if table_state() is not True:
        return False
    import sb_clients
    b = str(business_id)
    lock = _locks.setdefault(b, threading.Lock())
    with lock:
        if seq is not None and _latest.get(b, seq) != seq:
            return True
        now = datetime.now(timezone.utc)
        times = {"last_call_at": _iso(now), "touched_at": _iso(now),
                 "window_ends_at": _iso(now + timedelta(seconds=window_for(b))),
                 "pings": 0, "stopped_at": None, "stopped_reason": None}
        text = ping_text(ping)
        h = prefix_hash(text, headers)
        try:
            if _stored.get(b) == h:
                rows = sb_clients.sb_patch_as_service(
                    f"/{TABLE}?business_id=eq.{_q(b)}&prefix_hash=eq.{h}&select=business_id", times)
                if rows:
                    return True
            rows = sb_clients.sb_post_as_service(
                f"/{TABLE}?on_conflict=business_id&select=business_id",
                {"business_id": b, **times, "payload": text, "headers": dict(headers or {}),
                 "prefix_hash": h},
                prefer="resolution=merge-duplicates,return=representation", redact=True)
        except Exception as e:
            logger.info("keep-warm biz=%s: record failed (%s)", b[:8], type(e).__name__)
            return False
        if rows:
            _stored[b] = h
            return True
        logger.info("keep-warm biz=%s: record not written, pinging in this process", b[:8])
        return False


def remember(business_id: Optional[str], payload: Dict[str, Any],
             headers: Optional[Dict[str, str]] = None) -> bool:
    """Called after each main Chief call: (re)start this business's pings."""
    global _seq
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
    _seq += 1
    _latest[b] = _seq
    _tasks[b] = loop.create_task(_keep_warm(b, ping, dict(headers or {}), _seq))
    return True


async def _keep_warm(business_id: str, ping: Dict[str, Any], headers: Dict[str, str],
                     seq: Optional[int] = None) -> None:
    """The worker pings from the table; this process pings only when the
    table can't take it (not applied yet, or the write failed)."""
    started = time.monotonic()
    try:
        if await asyncio.to_thread(record, business_id, ping, headers, seq):
            return
        window = await asyncio.to_thread(window_for, business_id)
        last_used = datetime.now(timezone.utc)
        while True:
            await asyncio.sleep(every_s())
            if time.monotonic() - started > window:
                logger.info("keep-warm biz=%s: idle past the window, stopping", business_id[:8])
                return
            if crosses_midnight(last_used, datetime.now(timezone.utc)):
                logger.info("keep-warm biz=%s: past 00:00 UTC, the copy is gone, stopping", business_id[:8])
                return
            if not await _ping(business_id, ping, headers):
                return
            last_used = datetime.now(timezone.utc)
    except asyncio.CancelledError:
        pass
    finally:
        if _tasks.get(business_id) is asyncio.current_task():
            _tasks.pop(business_id, None)


async def send_ping(business_id: str, ping: Dict[str, Any], headers: Dict[str, str]) -> str:
    """One no-reply read of the cached brief. 'read', or why not: 'wrote'
    (the copy was gone and this paid for one), 'refused' (the API said no),
    'busy' (429, 5xx or the network: worth one more try while the copy
    lasts), 'budget' (the spend guard), 'off' (no key)."""
    try:
        import httpx
        import llm_call
        import spend_guard
        if not llm_call.api_key():
            return "off"
        if await asyncio.to_thread(spend_guard.over_budget, business_id):
            return "budget"
        async with httpx.AsyncClient() as client:
            resp = await llm_call.apost(client, ping, timeout=httpx.Timeout(30.0, connect=5.0),
                                        extra_headers=headers or None, task="chief_keep_warm",
                                        business_id=business_id, units=0)
        if resp.status_code >= 400:
            logger.warning("keep-warm biz=%s: ping refused (%s)", business_id[:8], resp.status_code)
            return "busy" if resp.status_code == 429 or resp.status_code >= 500 else "refused"
        usage = (resp.json() or {}).get("usage") or {}
        read = int(usage.get("cache_read_input_tokens") or 0)
        wrote = int(usage.get("cache_creation_input_tokens") or 0)
        logger.info("keep-warm biz=%s: read %d, wrote %d", business_id[:8], read, wrote)
        if wrote > WRITE_STOP_TOKENS:
            logger.info("keep-warm biz=%s: the copy was gone (wrote %d), stopping", business_id[:8], wrote)
            return "wrote"
        return "read"
    except Exception as e:  # never let a ping touch anything else
        logger.warning("keep-warm biz=%s: ping failed (%s)", business_id[:8], type(e).__name__)
        return "busy"


async def _ping(business_id: str, ping: Dict[str, Any], headers: Dict[str, str]) -> bool:
    """The in-process chain's ping. False = stop pinging."""
    return await send_ping(business_id, ping, headers) == "read"


# ─── The worker's job ────────────────────────────────────────────────

def verdict(row: Dict[str, Any], now: datetime) -> str:
    """For a live row whose copy is due: 'ping', or why its chain is over:
    'lapsed' (the copy may be gone already), 'midnight' (00:00 UTC came
    since its last use), 'window' (the business has gone quiet)."""
    touched = _parse(row.get("touched_at"))
    ends = _parse(row.get("window_ends_at"))
    if touched is None or ends is None or (now - touched).total_seconds() >= LATE_S:
        return "lapsed"
    if crosses_midnight(touched, now):
        return "midnight"
    if now > ends:
        return "window"
    return "ping"


def _due(now: datetime) -> List[Dict[str, Any]]:
    """Live chains whose copy was last used every_s() or more ago."""
    import sb_clients
    cutoff = _q(_iso(now - timedelta(seconds=every_s())))
    rows = sb_clients.sb_get_as_service(
        f"/{TABLE}?stopped_at=is.null&touched_at=lt.{cutoff}"
        "&select=business_id,touched_at,window_ends_at,pings&order=touched_at.asc&limit=500")
    return [r for r in rows if isinstance(r, dict) and r.get("business_id")] if isinstance(rows, list) else []


def _set(business_id: str, touched_at: Any, body: Dict[str, Any],
         select: str = "business_id") -> Optional[Dict[str, Any]]:
    """Change a live row only if its copy was last used at `touched_at`: a
    message since then (or another worker's ping) moved it, and that chain
    is left alone. The row as changed, or None when nothing matched."""
    import sb_clients
    rows = sb_clients.sb_patch_as_service(
        f"/{TABLE}?business_id=eq.{_q(business_id)}&stopped_at=is.null"
        f"&touched_at=eq.{_q(touched_at)}&select={select}", body)
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None


async def _one(row: Dict[str, Any], now: datetime) -> str:
    b = str(row["business_id"])
    why = verdict(row, now)
    if why != "ping":
        await asyncio.to_thread(_set, b, row["touched_at"], {"stopped_at": _iso(now), "stopped_reason": why})
        logger.info("keep-warm biz=%s: chain over (%s)", b[:8], why)
        return why
    claimed_at = _iso(now)
    pings = int(row.get("pings") or 0)
    got = await asyncio.to_thread(_set, b, row["touched_at"],
                                  {"touched_at": claimed_at, "pings": pings + 1}, "payload,headers")
    if not got:
        return "taken"
    try:
        ping = json.loads(got.get("payload") or "")
    except (TypeError, ValueError):
        ping = None
    if not isinstance(ping, dict):
        await asyncio.to_thread(_set, b, claimed_at, {"stopped_at": _iso(now), "stopped_reason": "refused"})
        return "refused"
    outcome = await send_ping(b, ping, got.get("headers") or {})
    if outcome == "read":
        return "read"
    if outcome == "busy":
        # Put the last use back, so the next look tries once more while the
        # copy lasts (LATE_S ends the chain if the API stays busy).
        await asyncio.to_thread(_set, b, claimed_at, {"touched_at": row["touched_at"], "pings": pings})
        return "busy"
    await asyncio.to_thread(_set, b, claimed_at, {"stopped_at": _iso(datetime.now(timezone.utc)),
                                                  "stopped_reason": outcome})
    return outcome


async def tick() -> Dict[str, int]:
    """The worker's job, every TICK_MIN minutes on the scheduler leader:
    ping each business whose cached copy is due, end the chains that are
    over. Nothing while the table isn't there or CHIEF_KEEP_WARM=off."""
    counts: Dict[str, int] = {}
    if not enabled() or await asyncio.to_thread(table_state) is not True:
        return counts
    now = datetime.now(timezone.utc)
    try:
        rows = await asyncio.to_thread(_due, now)
    except Exception as e:
        logger.warning("keep-warm tick: read failed (%s)", type(e).__name__)
        return counts
    gate = asyncio.Semaphore(_PARALLEL)

    async def one(row: Dict[str, Any]) -> str:
        async with gate:
            try:
                return await _one(row, now)
            except Exception as e:  # one business never stops the others
                logger.warning("keep-warm biz=%s: tick failed (%s)", str(row.get("business_id"))[:8],
                               type(e).__name__)
                return "error"
    for outcome in await asyncio.gather(*(one(r) for r in rows)):
        counts[outcome] = counts.get(outcome, 0) + 1
    if counts:
        logger.info("keep-warm tick: %s", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return counts
