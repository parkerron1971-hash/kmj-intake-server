"""Mission Control → Systems → Database: the weekly database health check.

Kevin, 2026-11-18, the day production moved from Nano to Small after a
"Disk IO Budget" warning: a check every week that says when the database
should move up a size, before Sunday morning slows down.

THE READINGS. One every 15 minutes on Sunday from 7:45 AM to 1 PM US
Eastern (Sunday morning is when churches use the app most; the 7:45 reading
is the start line the 8:00 one is measured from), and two on Wednesday at
10:45 and 11 AM, a weekday to compare with. Each reading has two parts:

  Supabase's metrics feed (Prometheus text). Verified 2026-11-18 against
  https://supabase.com/docs/guides/telemetry/metrics and the metric list in
  https://github.com/supabase/supabase-grafana (metrics.md):
  GET https://<project ref>.supabase.co/customer/v1/privileged/metrics,
  HTTP Basic auth, user `service_role`, password a secret key
  (SUPABASE_METRICS_KEY, an sb_secret_ key) or the legacy service-role key.
  Read here: node_memory_{MemTotal,MemAvailable,SwapTotal,SwapFree,
  Committed_AS}_bytes, node_cpu_seconds_total by mode, node_disk_
  {read,written}_bytes_total and {reads,writes}_completed_total,
  pg_stat_database_num_backends, max_connections_connection_count and
  pg_database_size_bytes. The feed has NO Disk IO budget or balance series,
  so disk is judged from throughput and operations against the size's
  baseline (https://supabase.com/docs/guides/platform/compute-and-disk);
  the balance itself is only on Supabase's own pages.

  Postgres itself, through db_health_pg() (service role only): connections
  against max_connections, the database's size, and at the last reading of
  each window the five statements that wrote the most WAL and the most temp
  files (pg_stat_statements: normalized text, literals masked, 160
  characters, never a parameter).

A counter (CPU seconds, disk bytes) says something only between two
readings, so rates are worked out from consecutive readings 4 to 25 minutes
apart when the week is summed up (summarize()), never from one.

ONCE A SLOT. The job runs on the scheduler's leader every 5 minutes; a
15-minute slot's reading is claimed by inserting its row first (`slot` is
unique), so a leader hand-over or a second process never reads it twice.

THE VERDICT. judge() is pure: the compute size, the week's peaks and the
number of active churches give "Fine at Small", "Watch: ..." or "Time to
move up to Medium (+$45/month)", with the one or two reasons in plain words.
The size is read from the memory Supabase reports (a Small has 2 GB), then
SUPABASE_COMPUTE_SIZE, then Small.

MONDAY. From 8 AM Eastern on Monday the week's verdict is written once
(db_health_weeks, one row a Sunday). When it turns to "Time to move up",
the owner hears once, through the owner alert inbox (dev_alerts, source
"database"): a push that opens Mission Control → Systems → Database.

MEMBER APP. Each reading also keeps how long member pages took on the
server copy that took it (member_stopwatch.py), as metrics.member_app; the
card adds last Sunday's up into one line ("Tabs open in 0.9 s typical ...").

Owner-only (require_owner on the router). DB_HEALTH_CHECK=off stops the
readings, the report and the card. Until supabase/APPLY-2026-11-18-db-
health.sql is applied nothing is read or written and the card says it
isn't set up; nothing here ever answers 500 for a missing table.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from lead_admin import require_owner

logger = logging.getLogger("db_health")
router = APIRouter(prefix="/platform/db-health", tags=["platform-db-health"],
                   dependencies=[Depends(require_owner)])

MIGRATION = "supabase/APPLY-2026-11-18-db-health.sql"
SAMPLES = "/db_health_samples"
WEEKS = "/db_health_weeks"
ET = ZoneInfo("America/New_York")
NAV = "studio:platform-database"

HOURS_A_MONTH = 730
MB = 1_000_000            # Supabase's disk table is in MB/s
GIB = 1024 ** 3           # a Small's "2 GB" of memory is 2 GiB
MIB = 1024 ** 2
HTTP_TIMEOUT = 20.0
KEEP_WEEKS = 8            # readings older than this are removed by the Monday report
CHURCH_CACHE_SECONDS = 600.0
CHECK_GAP_SECONDS = 60.0  # between two "Check now" presses

# ─── The sizes (the compute picker and the compute-and-disk page, 2026-11-18) ──
# churches: the planning guide Kevin was given on 2026-11-18 (rough: churches
# of 75-600 people, Sunday morning the peak). (low, high); None = no top.
# Nano and Micro aren't in the guide: a handful of churches was enough to
# swap Nano hard, so their tops are kept tiny.
SIZES: List[Dict[str, Any]] = [
    {"key": "nano",   "label": "Nano",   "memory_gb": 0.5, "hourly": 0.01344, "disk_mbs": 5,   "iops": 250,   "churches": (0, 2)},
    {"key": "micro",  "label": "Micro",  "memory_gb": 1,   "hourly": 0.01344, "disk_mbs": 11,  "iops": 500,   "churches": (0, 8)},
    {"key": "small",  "label": "Small",  "memory_gb": 2,   "hourly": 0.0206,  "disk_mbs": 22,  "iops": 1000,  "churches": (0, 25)},
    {"key": "medium", "label": "Medium", "memory_gb": 4,   "hourly": 0.0822,  "disk_mbs": 39,  "iops": 2000,  "churches": (25, 100)},
    {"key": "large",  "label": "Large",  "memory_gb": 8,   "hourly": 0.1517,  "disk_mbs": 79,  "iops": 3600,  "churches": (100, 250)},
    {"key": "xl",     "label": "XL",     "memory_gb": 16,  "hourly": 0.2877,  "disk_mbs": 149, "iops": 6000,  "churches": (250, 500)},
    {"key": "2xl",    "label": "2XL",    "memory_gb": 32,  "hourly": 0.562,   "disk_mbs": 297, "iops": 12000, "churches": (500, None)},
    {"key": "4xl",    "label": "4XL",    "memory_gb": 64,  "hourly": 1.32,    "disk_mbs": 594, "iops": 20000, "churches": (500, None)},
]
SIZE_KEYS = [s["key"] for s in SIZES]
DEFAULT_SIZE = "small"

# ─── The lines (the planning guide's "move up when any of these shows") ─────
SWAP_WATCH = 64 * MIB          # some swap: memory is getting tight
SWAP_MOVE = 256 * MIB          # real swap: the database is using disk as memory
FREE_WATCH = 0.20              # memory available under 20% of the total
FREE_MOVE = 0.10
COMMIT_WATCH = 1.0             # memory promised out (Committed_AS) >= the memory there is
CPU_WATCH = 0.55
CPU_MOVE = 0.70                # the guide: CPU over ~70% during Sunday services
DISK_WATCH = 0.70              # of the size's baseline throughput or operations
DISK_MOVE = 1.0                # at or over the baseline: the Disk IO budget is being spent
SUSTAINED = 2                  # two 15-minute readings: half an hour
CONN_WATCH = 0.80
CHURCHES_NEAR = 0.80           # of the size's planned top

# The windows, US Eastern.
SUNDAY = 6
SUNDAY_FIRST = dtime(7, 45)
SUNDAY_LAST = dtime(13, 0)
WEEKDAY = 2                    # Wednesday
WEEKDAY_SLOTS = (dtime(10, 45), dtime(11, 0))
REPORT_DAY = 0                 # Monday
REPORT_AT = dtime(8, 0)
PAIR_MIN_SECONDS = 240
PAIR_MAX_SECONDS = 1500

SCHEDULE_WORDS = ("Every 15 minutes on Sunday from 8 AM to 1 PM Eastern, and Wednesday at 11 AM "
                  "for a weekday to compare. The verdict lands Monday at 8 AM.")
DISK_BALANCE_WORDS = ("Supabase's feed doesn't include the Disk IO balance, so this judges disk by how "
                      "fast it read and wrote against the size's baseline. If Supabase warns about "
                      "the Disk IO budget again, that alone is reason to move up.")


def enabled() -> bool:
    return (os.environ.get("DB_HEALTH_CHECK") or "on").strip().lower() not in ("0", "off", "false", "no")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Sizes ──────────────────────────────────────────────────────────────

def size_of(key: Any) -> Optional[Dict[str, Any]]:
    k = str(key or "").strip().lower().replace(" ", "")
    return next((s for s in SIZES if s["key"] == k), None)


def monthly(size: Dict[str, Any]) -> int:
    """The size's monthly price in whole dollars (730 hours)."""
    return int(round(size["hourly"] * HOURS_A_MONTH))


def next_size(size: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    i = SIZE_KEYS.index(size["key"])
    return SIZES[i + 1] if i + 1 < len(SIZES) else None


def churches_words(size: Dict[str, Any]) -> str:
    lo, hi = size["churches"]
    if hi is None:
        return f"{lo}+"
    return f"up to ~{hi}" if not lo else f"~{lo}–{hi}"


def size_from_memory(total_bytes: Any) -> Optional[str]:
    """The size whose memory this is. The kernel keeps a little for itself,
    so the reported total sits just under the size's memory: the smallest
    size with at least that much (5% slack for rounding) is the one."""
    try:
        total = float(total_bytes)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(total) or total <= 0:
        return None
    for s in SIZES:
        if s["memory_gb"] * GIB * 1.05 >= total:
            return s["key"]
    return None


def current_size(memory_total: Any = None) -> Tuple[Dict[str, Any], str]:
    """(size, where it came from): "measured" (the memory Supabase reports),
    "setting" (SUPABASE_COMPUTE_SIZE) or "default" (Small)."""
    measured = size_from_memory(memory_total)
    if measured:
        return size_of(measured), "measured"
    env = size_of(os.environ.get("SUPABASE_COMPUTE_SIZE"))
    if env:
        return env, "setting"
    return size_of(DEFAULT_SIZE), "default"


def sizes_table(current: Dict[str, Any]) -> List[Dict[str, Any]]:
    nxt = next_size(current)
    return [{"key": s["key"], "label": s["label"], "memory_gb": s["memory_gb"], "monthly": monthly(s),
             "churches": churches_words(s), "disk_mbs": s["disk_mbs"],
             "current": s["key"] == current["key"], "next": bool(nxt and s["key"] == nxt["key"])}
            for s in SIZES if s["key"] not in ("nano", "micro") or s["key"] == current["key"]]


# ─── The metrics feed (Prometheus text format) ──────────────────────────

_LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)(?:\s+-?\d+)?\s*$')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"((?:[^"\\]|\\.)*)"')
_ESCAPE = re.compile(r'\\(.)')
_SKIP_DEVICE = re.compile(r'^(ram|loop|fd|sr|dm-|md)\d*|^nvme\d+n\d+p\d+$|^[shv]d[a-z]+\d+$|^xvd[a-z]+\d+$')
_OTHER_SERVICES = {"postgrest", "gotrue", "auth", "storage", "realtime", "kong", "edge", "supavisor", "pgbouncer"}


def parse_prometheus(text: Optional[str]) -> List[Tuple[str, Dict[str, str], float]]:
    """Every sample in a Prometheus text exposition: (name, labels, value).
    Comments, blank lines and lines it can't read are skipped; a timestamp
    after the value is ignored; NaN and ±Inf come back as floats."""
    out: List[Tuple[str, Dict[str, str], float]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, labels_raw, value_raw = m.groups()
        try:
            value = float(value_raw)
        except ValueError:
            continue
        labels: Dict[str, str] = {}
        for lm in _LABEL.finditer(labels_raw or ""):
            labels[lm.group(1)] = _ESCAPE.sub(lambda e: "\n" if e.group(1) == "n" else e.group(1), lm.group(2))
        out.append((name, labels, value))
    return out


def _ours(labels: Dict[str, str], ref: Optional[str]) -> bool:
    """The primary database's own series: not another service's (PostgREST,
    Auth ...), and not a read replica's (its supabase_identifier differs)."""
    if (labels.get("service_type") or "").lower() in _OTHER_SERVICES:
        return False
    ident = labels.get("supabase_identifier")
    if ref and ident and ident != ref:
        return False
    return True


def reading_from(samples: Iterable[Tuple[str, Dict[str, str], float]],
                 ref: Optional[str] = None) -> Dict[str, float]:
    """The numbers this check keeps from one scrape. Gauges as they are;
    counters (CPU seconds, disk bytes and operations) as running totals,
    turned into rates between two readings by summarize()."""
    first: Dict[str, float] = {}
    sums: Dict[str, float] = {}
    cpus: set = set()
    for name, labels, value in samples:
        if not math.isfinite(value) or not _ours(labels, ref):
            continue
        if name.startswith("node_memory_") and name.endswith("_bytes"):
            field = {"node_memory_MemTotal_bytes": "mem_total", "node_memory_MemAvailable_bytes": "mem_available",
                     "node_memory_SwapTotal_bytes": "swap_total", "node_memory_SwapFree_bytes": "swap_free",
                     "node_memory_Committed_AS_bytes": "committed"}.get(name)
            if field and field not in first:
                first[field] = value
        elif name == "node_cpu_seconds_total":
            sums["cpu_total"] = sums.get("cpu_total", 0.0) + value
            if labels.get("mode") == "idle":
                sums["cpu_idle"] = sums.get("cpu_idle", 0.0) + value
            if labels.get("cpu") is not None:
                cpus.add(labels["cpu"])
        elif name in ("node_disk_read_bytes_total", "node_disk_written_bytes_total",
                      "node_disk_reads_completed_total", "node_disk_writes_completed_total"):
            if _SKIP_DEVICE.search(labels.get("device") or ""):
                continue
            field = {"node_disk_read_bytes_total": "disk_read", "node_disk_written_bytes_total": "disk_written",
                     "node_disk_reads_completed_total": "disk_reads",
                     "node_disk_writes_completed_total": "disk_writes"}[name]
            sums[field] = sums.get(field, 0.0) + value
        elif name == "pg_stat_database_num_backends":
            sums["backends"] = sums.get("backends", 0.0) + value
        elif name == "max_connections_connection_count":
            first.setdefault("max_conn", value)
        elif name == "pg_database_size_bytes":
            if labels.get("datname") in (None, "postgres"):
                first.setdefault("db_bytes", value)
        elif name == "pg_database_size_mb":
            first.setdefault("db_mb", value)
    out = {**first, **sums}
    if "cpu_idle" in out and "cpu_total" not in out:
        out.pop("cpu_idle")
    if "cpu_total" in out:
        out.setdefault("cpu_idle", 0.0)
        if cpus:
            out["cpus"] = float(len(cpus))
    if "db_bytes" not in out and "db_mb" in out:
        out["db_bytes"] = out["db_mb"] * MIB
    out.pop("db_mb", None)
    return out


def project_ref() -> Optional[str]:
    host = (urlparse(os.environ.get("SUPABASE_URL") or "").hostname or "").lower()
    m = re.fullmatch(r"([a-z0-9]+)\.supabase\.co", host)
    if m:
        return m.group(1)
    ref = (os.environ.get("SUPABASE_PROJECT_REF") or "").strip().lower()
    return ref if re.fullmatch(r"[a-z0-9]+", ref or "") else None


def metrics_url() -> Optional[str]:
    ref = project_ref()
    return f"https://{ref}.supabase.co/customer/v1/privileged/metrics" if ref else None


def _metrics_key() -> str:
    # Read at call time, never logged or returned.
    return (os.environ.get("SUPABASE_METRICS_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


async def read_metrics(client: httpx.AsyncClient) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    """(the reading, None) or (None, why not, in words)."""
    url, key = metrics_url(), _metrics_key()
    if not url:
        return None, "The database's address isn't a Supabase project address, so its metrics can't be found."
    if not key:
        return None, "There's no key to read Supabase's metrics with."
    try:
        resp = await client.get(url, auth=("service_role", key), timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        return None, f"Supabase's metrics didn't answer ({type(e).__name__})."
    if resp.status_code in (401, 403):
        return None, f"Supabase refused the key for its metrics ({resp.status_code})."
    if resp.status_code >= 400:
        return None, f"Supabase's metrics answered {resp.status_code}."
    reading = reading_from(parse_prometheus(resp.text), project_ref())
    if not reading:
        return None, "Supabase's metrics answered with nothing this check reads."
    return reading, None


# ─── The database's own numbers (db_health_pg, the migration) ───────────

def _missing(err: Optional[Dict[str, Any]]) -> bool:
    """A table or function the migration makes isn't there yet."""
    if not err:
        return False
    return err.get("code") in ("42P01", "42883", "PGRST205", "PGRST202") or err.get("status") == 404


def read_pg(top: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    got = sb_clients.sb_post_as_service("/rpc/db_health_pg", {"p_top": int(top)}, redact=True)
    if isinstance(got, dict):
        return got, None
    if _missing(sb_clients.last_error()):
        return None, "The database's own numbers aren't set up yet."
    return None, "The database's own numbers couldn't be read."


# ─── Active churches (what the size plan counts) ────────────────────────

_church_cache: Dict[str, Any] = {"at": None, "value": None}


def count_churches() -> Optional[int]:
    """Churches using the system: active, past due, on a trial or comped,
    never a sample church. The platform owner's own church counts: it uses
    the database like any other. None when it can't be read."""
    import church_billing
    try:
        rows = sb_clients.sb_get_all_as_service(
            "/businesses?or=(subscription_status.in.(active,trialing,past_due),comp_tier.not.is.null)"
            "&is_sample=not.is.true&select=id,type", key="id", strict=True, redact=True) or []
    except Exception as e:  # noqa: BLE001 — an unread count is said so, never a 500
        logger.warning("db health: churches unread: %s", type(e).__name__)
        return None
    return sum(1 for r in rows if church_billing.is_church(r))


def churches_cached() -> Optional[int]:
    at = _church_cache["at"]
    if at is not None and time.monotonic() - at < CHURCH_CACHE_SECONDS and _church_cache["value"] is not None:
        return _church_cache["value"]
    value = count_churches()
    _church_cache.update(at=time.monotonic(), value=value)
    return value


# ─── When to read ──────────────────────────────────────────────────────

def slot_for(now: datetime) -> Optional[Tuple[datetime, str]]:
    """The 15-minute slot `now` falls in, and its kind ("sunday" or
    "weekday"), or None outside the windows."""
    local = now.astimezone(ET)
    floored = local.replace(minute=local.minute - local.minute % 15, second=0, microsecond=0)
    t = floored.timetz().replace(tzinfo=None)
    if floored.weekday() == SUNDAY and SUNDAY_FIRST <= t <= SUNDAY_LAST:
        kind = "sunday"
    elif floored.weekday() == WEEKDAY and t in WEEKDAY_SLOTS:
        kind = "weekday"
    else:
        return None
    return floored.astimezone(timezone.utc), kind


def last_of_window(slot: datetime, kind: str) -> bool:
    t = slot.astimezone(ET).timetz().replace(tzinfo=None)
    return t == (SUNDAY_LAST if kind == "sunday" else WEEKDAY_SLOTS[-1])


def due_week(now: datetime) -> date:
    """The Sunday whose report is due: from Monday 8 AM Eastern it is the
    day before; until then, the Sunday a week earlier."""
    local = now.astimezone(ET)
    monday = local.date() - timedelta(days=local.weekday())
    if local.weekday() == REPORT_DAY and local.timetz().replace(tzinfo=None) < REPORT_AT:
        monday -= timedelta(days=7)
    return monday - timedelta(days=1)


def last_sunday(now: datetime) -> date:
    """The Sunday on or before today, Eastern."""
    local = now.astimezone(ET).date()
    return local - timedelta(days=(local.weekday() + 1) % 7)


def week_bounds(sunday: date) -> Tuple[datetime, datetime]:
    """Monday 00:00 to the next Monday 00:00 Eastern, as UTC."""
    start = datetime.combine(sunday - timedelta(days=6), dtime(0, 0), ET)
    end = datetime.combine(sunday + timedelta(days=1), dtime(0, 0), ET)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _z(dt: datetime) -> str:
    # The Z form: '+00:00' reads as a space in a PostgREST query string.
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(raw: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def when_words(dt: datetime) -> str:
    local = dt.astimezone(ET)
    hour = local.hour % 12 or 12
    clock = f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    return f"{local:%A} at {clock}"


# ─── The week, summed up (pure) ─────────────────────────────────────────

def _num(d: Dict[str, Any], key: str) -> Optional[float]:
    v = d.get(key)
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _counter(prev: Dict[str, Any], cur: Dict[str, Any], key: str) -> Optional[float]:
    a, b = _num(prev, key), _num(cur, key)
    if a is None or b is None or b < a:     # a reset (restart, resize) is no rate
        return None
    return b - a


def summarize(rows: List[Dict[str, Any]], size: Dict[str, Any]) -> Dict[str, Any]:
    """The peaks in a set of readings, judged against `size`. Each section
    is None when no reading had it. Rates (CPU, disk) come from pairs of
    consecutive readings 4-25 minutes apart, attributed to the later one."""
    pts = []
    for r in rows or []:
        at = _parse(r.get("taken_at"))
        if at is None:
            continue
        pts.append((at, r.get("kind") or "", r.get("metrics") if isinstance(r.get("metrics"), dict) else {},
                    r.get("pg") if isinstance(r.get("pg"), dict) else {}))
    pts.sort(key=lambda p: p[0])
    out: Dict[str, Any] = {"readings": len(pts),
                           "sunday_readings": sum(1 for p in pts if p[1] == "sunday"),
                           "weekday_readings": sum(1 for p in pts if p[1] == "weekday"),
                           "memory": None, "swap": None, "committed": None, "cpu": None, "disk": None,
                           "connections": None, "db_bytes": None, "memory_total": None}
    for at, kind, m, pg in pts:
        total, avail = _num(m, "mem_total"), _num(m, "mem_available")
        if total:
            out["memory_total"] = total
        if total and avail is not None:
            used = max(total - avail, 0.0)
            if out["memory"] is None or used > out["memory"]["used"]:
                out["memory"] = {"used": used, "total": total, "free_share": avail / total, "at": when_words(at)}
        st, sf = _num(m, "swap_total"), _num(m, "swap_free")
        if st is not None and sf is not None:
            used = max(st - sf, 0.0)
            if out["swap"] is None or used > out["swap"]["used"]:
                out["swap"] = {"used": used, "total": st, "at": when_words(at)}
        com = _num(m, "committed")
        if total and com is not None:
            ratio = com / total
            if out["committed"] is None or ratio > out["committed"]["ratio"]:
                out["committed"] = {"ratio": ratio, "bytes": com, "total": total, "at": when_words(at)}
        conns = _num(pg, "connections") if _num(pg, "connections") is not None else _num(m, "backends")
        cap = _num(pg, "max_connections") if _num(pg, "max_connections") is not None else _num(m, "max_conn")
        if conns is not None and (out["connections"] is None or conns > out["connections"]["peak"]):
            out["connections"] = {"peak": int(conns), "max": int(cap) if cap else None, "at": when_words(at)}
        size_b = _num(pg, "db_bytes") if _num(pg, "db_bytes") is not None else _num(m, "db_bytes")
        if size_b is not None:
            out["db_bytes"] = size_b

    cpu_pts: List[Dict[str, Any]] = []
    disk_pts: List[Dict[str, Any]] = []
    for (a_at, a_kind, a, _), (b_at, b_kind, b, _) in zip(pts, pts[1:]):
        dt = (b_at - a_at).total_seconds()
        if not (PAIR_MIN_SECONDS <= dt <= PAIR_MAX_SECONDS):
            continue
        d_total, d_idle = _counter(a, b, "cpu_total"), _counter(a, b, "cpu_idle")
        if d_total and d_idle is not None and d_idle <= d_total:
            cpu_pts.append({"busy": 1 - d_idle / d_total, "at": b_at, "kind": b_kind})
        d_r, d_w = _counter(a, b, "disk_read"), _counter(a, b, "disk_written")
        if d_r is not None and d_w is not None:
            ops_r, ops_w = _counter(a, b, "disk_reads"), _counter(a, b, "disk_writes")
            iops = (ops_r + ops_w) / dt if ops_r is not None and ops_w is not None else None
            mbs = (d_r + d_w) / dt / MB
            share = max(mbs / size["disk_mbs"], (iops or 0.0) / size["iops"])
            disk_pts.append({"mbs": mbs, "read_mbs": d_r / dt / MB, "write_mbs": d_w / dt / MB,
                             "iops": iops, "share": share, "at": b_at, "kind": b_kind})
    if cpu_pts:
        top = max(cpu_pts, key=lambda p: p["busy"])
        weekday = [p["busy"] for p in cpu_pts if p["kind"] == "weekday"]
        out["cpu"] = {"peak": top["busy"], "at": when_words(top["at"]),
                      "over_move": sum(1 for p in cpu_pts if p["busy"] >= CPU_MOVE),
                      "weekday": max(weekday) if weekday else None, "readings": len(cpu_pts)}
    if disk_pts:
        top = max(disk_pts, key=lambda p: p["share"])
        weekday = [p["mbs"] for p in disk_pts if p["kind"] == "weekday"]
        by_ops = top["iops"] is not None and top["iops"] / size["iops"] > top["mbs"] / size["disk_mbs"]
        out["disk"] = {"peak_mbs": top["mbs"], "read_mbs": top["read_mbs"], "write_mbs": top["write_mbs"],
                       "iops": top["iops"], "share": top["share"], "by": "ops" if by_ops else "throughput",
                       "at": when_words(top["at"]), "baseline_mbs": size["disk_mbs"], "baseline_iops": size["iops"],
                       "over_baseline": sum(1 for p in disk_pts if p["share"] >= DISK_MOVE),
                       "weekday_mbs": max(weekday) if weekday else None, "readings": len(disk_pts)}
    return out


# ─── The verdict (pure) ─────────────────────────────────────────────────

_RANK = {"move": 2, "watch": 1, "info": 0}


def _pct(x: float) -> str:
    return f"{int(round(x * 100))}%"


def _bytes_words(n: float) -> str:
    if n >= GIB:
        return f"{n / GIB:.1f} GB"
    return f"{int(round(n / MIB))} MB"


def _minutes(readings: int) -> str:
    m = readings * 15
    return f"{m} minutes" if m < 60 else (f"{m // 60} hour" + ("s" if m >= 120 else "")
                                          + (f" {m % 60} minutes" if m % 60 else ""))


def judge(size: Dict[str, Any], peak: Optional[Dict[str, Any]], churches: Optional[int]) -> Dict[str, Any]:
    """The verdict: {level fine|watch|move, headline, reasons (the one or two
    that matter most), measured, next}. Any one "move" line is enough
    whatever the church count; the church count alone moves only when there
    were no readings to say otherwise."""
    peak = peak or {}
    label = size["label"]
    reasons: List[Dict[str, Any]] = []

    def add(level: str, code: str, short: str, text: str) -> None:
        reasons.append({"level": level, "code": code, "short": short, "text": text})

    swap = peak.get("swap")
    if swap and swap["used"] >= SWAP_WATCH:
        lvl = "move" if swap["used"] >= SWAP_MOVE else "watch"
        add(lvl, "swap", f"swap reached {_bytes_words(swap['used'])}",
            f"The database ran short of memory and used {_bytes_words(swap['used'])} of disk as memory "
            f"(swap) on {swap['at']}." + (" That slows every page." if lvl == "move" else ""))
    mem = peak.get("memory")
    if mem and mem["free_share"] < FREE_WATCH:
        lvl = "move" if mem["free_share"] < FREE_MOVE else "watch"
        add(lvl, "memory", f"only {_pct(mem['free_share'])} of memory was free",
            f"Only {_pct(mem['free_share'])} of the {_bytes_words(mem['total'])} of memory was free on "
            f"{mem['at']}.")
    com = peak.get("committed")
    if com and com["ratio"] >= COMMIT_WATCH:
        add("watch", "committed", "memory promised out passed what there is",
            f"Memory promised out reached {_bytes_words(com['bytes'])}, more than the "
            f"{_bytes_words(com['total'])} there is, on {com['at']}.")
    cpu = peak.get("cpu")
    if cpu:
        if cpu["over_move"] >= SUSTAINED:
            add("move", "cpu", f"CPU stayed over {_pct(CPU_MOVE)}",
                f"CPU ran at {_pct(CPU_MOVE)} or more for {_minutes(cpu['over_move'])} "
                f"(the top was {_pct(cpu['peak'])}, on {cpu['at']}).")
        elif cpu["peak"] >= CPU_MOVE:
            add("watch", "cpu", f"CPU reached {_pct(cpu['peak'])}",
                f"CPU reached {_pct(cpu['peak'])} on {cpu['at']}. Half an hour over "
                f"{_pct(CPU_MOVE)} means it's time to move up.")
        elif cpu["peak"] >= CPU_WATCH:
            add("watch", "cpu", f"CPU reached {_pct(cpu['peak'])}",
                f"CPU reached {_pct(cpu['peak'])} on {cpu['at']}. The line is {_pct(CPU_MOVE)}.")
    disk = peak.get("disk")
    if disk:
        if disk["by"] == "ops" and disk["iops"] is not None:
            what = f"{int(round(disk['iops'])):,} disk operations a second"
            line = f"{label}'s baseline of {disk['baseline_iops']:,} a second"
        else:
            what = f"{disk['peak_mbs']:.1f} MB/s of disk reads and writes"
            line = f"{label}'s {disk['baseline_mbs']} MB/s baseline"
        if disk["over_baseline"] >= SUSTAINED:
            add("move", "disk", "disk ran over its baseline",
                f"Disk ran over {line} for {_minutes(disk['over_baseline'])} (the top was {what}, "
                f"on {disk['at']}). That spends the Disk IO budget, and when it runs out the database is "
                f"held to {disk['baseline_mbs']} MB/s.")
        elif disk["share"] >= DISK_WATCH:
            add("watch", "disk", f"disk reached {_pct(disk['share'])} of its baseline",
                f"Disk reached {what} on {disk['at']}, {_pct(disk['share'])} of {line}.")
    conns = peak.get("connections")
    if conns and conns.get("max") and conns["peak"] / conns["max"] >= CONN_WATCH:
        add("watch", "connections", f"{conns['peak']} of {conns['max']} connections in use",
            f"{conns['peak']} of the {conns['max']} database connections were in use on {conns['at']}.")

    measured = bool(peak.get("readings"))
    lo, hi = size["churches"]
    if churches is not None and hi is not None:
        many = f"{churches} active {'church' if churches == 1 else 'churches'}"
        if churches > hi:
            if measured:
                add("watch", "churches", f"{many}, past {label}'s ~{hi}",
                    f"{many}; {label} is planned for about {hi}. The readings are still fine, so move "
                    "when one of them turns.")
            else:
                add("move", "churches", f"{many}, past {label}'s ~{hi}",
                    f"{many}; {label} is planned for about {hi}, and there were no readings this week "
                    "to say otherwise.")
        elif churches >= max(1, math.ceil(hi * CHURCHES_NEAR)):
            add("watch", "churches", f"{many}, close to {label}'s ~{hi}",
                f"{many}; {label} is planned for about {hi}.")
    if not measured:
        add("info", "unmeasured", "no readings this week",
            "No readings came in this week, so this is by the church count alone.")

    reasons.sort(key=lambda r: -_RANK[r["level"]])
    level = "move" if any(r["level"] == "move" for r in reasons) else (
        "watch" if any(r["level"] == "watch" for r in reasons) else "fine")
    nxt = next_size(size)
    if level == "move":
        if nxt:
            more = monthly(nxt) - monthly(size)
            headline = f"Time to move up to {nxt['label']} (+${more}/month)"
        else:
            headline = f"Time to grow past {label}: ask Supabase about a read replica"
    elif level == "watch":
        first = next(r for r in reasons if r["level"] == "watch")
        headline = f"Watch: {first['short']}"
    else:
        headline = f"Fine at {label}"
    shown = [r for r in reasons if r["level"] != "info"][:2] or reasons[:1]
    return {"level": level, "headline": headline, "reasons": shown, "measured": measured,
            "size": size["key"],
            "next": ({"key": nxt["key"], "label": nxt["label"], "monthly": monthly(nxt),
                      "more": monthly(nxt) - monthly(size)} if nxt else None)}


def should_tell(verdict: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> bool:
    """Tell the owner once, when the verdict turns to "Time to move up": not
    again while last week already said the same move."""
    if verdict.get("level") != "move":
        return False
    if not previous or previous.get("level") != "move":
        return True
    return (previous.get("headline") or "") != (verdict.get("headline") or "")


def alert_words(verdict: Dict[str, Any]) -> Tuple[str, str]:
    head = verdict["headline"]
    title = f"Database: {head[:1].lower()}{head[1:]}"[:90]
    body = " ".join(r["text"] for r in verdict.get("reasons") or [])[:220]
    return title, body or "Open Mission Control for the numbers."


def tops_from(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The top writers from the latest reading that has them."""
    best = None
    for r in rows or []:
        pg = r.get("pg") if isinstance(r.get("pg"), dict) else {}
        if not isinstance(pg.get("top_wal"), list) and not isinstance(pg.get("top_temp"), list):
            continue
        at = _parse(r.get("taken_at"))
        if at and (best is None or at > best[0]):
            best = (at, pg)
    if not best:
        return None
    pg = best[1]

    def clean(items: Any, field: str) -> List[Dict[str, Any]]:
        out = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            out.append({"query": str(it.get("query") or "")[:160], "calls": int(_num(it, "calls") or 0),
                        "bytes": int(_num(it, field) or 0)})
        return out[:5]
    return {"wal": clean(pg.get("top_wal"), "wal_bytes"), "temp": clean(pg.get("top_temp"), "temp_bytes"),
            "since": pg.get("since"), "at": _z(best[0]), "problem": pg.get("top_problem")}


# ─── The store ──────────────────────────────────────────────────────────

_state: Dict[str, Any] = {"reported": None, "unset_until": 0.0, "last_check": 0.0}


def forget() -> None:
    _state.update(reported=None, unset_until=0.0, last_check=0.0)
    _church_cache.update(at=None, value=None)


def _unset() -> None:
    """The tables aren't there yet: stay quiet for an hour."""
    _state["unset_until"] = time.monotonic() + 3600


def claim_slot(slot: datetime, kind: str) -> Optional[bool]:
    """True when this process claimed the slot, False when it was already
    claimed, None when the store isn't there or can't be written."""
    got = sb_clients.sb_post_as_service(
        f"{SAMPLES}?on_conflict=slot", {"slot": _z(slot), "kind": kind},
        prefer="resolution=ignore-duplicates,return=representation", redact=True)
    if isinstance(got, list):
        return bool(got)
    if _missing(sb_clients.last_error()):
        _unset()
    return None


async def take_reading(slot: datetime, kind: str, *, top: bool) -> Dict[str, Any]:
    """Claim the slot, read both parts, keep what came back. Never raises."""
    claimed = await asyncio.to_thread(claim_slot, slot, kind)
    if not claimed:
        return {"slot": _z(slot), "taken": False, "claimed": claimed}
    async with httpx.AsyncClient() as c:
        metrics, why = await read_metrics(c)
    pg, pg_why = await asyncio.to_thread(read_pg, 5 if top else 0)
    # How long member pages took on this server copy (member_stopwatch.py),
    # kept in the same jsonb: no table of its own, no migration.
    import member_stopwatch
    member = member_stopwatch.for_reading(kind)
    if member:
        metrics = {**(metrics or {}), "member_app": member}
    taken_at = _now()
    problem = " ".join(w for w in (why, pg_why) if w)[:300] or None
    if why:
        print(f"[db_health] metrics unread at {_z(slot)}: {why}", flush=True)
    row = {"taken_at": _z(taken_at), "metrics": metrics, "pg": pg, "problem": problem}
    kept = await asyncio.to_thread(sb_clients.sb_patch_as_service, f"{SAMPLES}?slot=eq.{_z(slot)}", row)
    if kept:
        # Only now does the next reading start after these member numbers.
        member_stopwatch.saved(member, kind)
    else:
        print(f"[db_health] reading at {_z(slot)} wasn't saved", flush=True)
    return {"slot": _z(slot), "taken": True, "kind": kind, "taken_at": _z(taken_at), "metrics": metrics,
            "pg": pg, "problem": problem}


def read_rows(start: datetime, end: datetime) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"{SAMPLES}?taken_at=gte.{_z(start)}&taken_at=lt.{_z(end)}"
        "&select=slot,kind,taken_at,metrics,pg,problem&order=taken_at.asc&limit=500", redact=True)
    if isinstance(rows, list):
        return rows
    if _missing(sb_clients.last_error()):
        _unset()
    return None


def read_weeks(limit: int = 8) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"{WEEKS}?select=week,size,churches,level,headline,reasons,told_at,created_at"
        f"&order=week.desc&limit={int(limit)}", redact=True)
    if isinstance(rows, list):
        return rows
    if _missing(sb_clients.last_error()):
        _unset()
    return None


def week_verdict(rows: List[Dict[str, Any]], churches: Optional[int]) -> Dict[str, Any]:
    """The week's summary and verdict from its readings (Sunday and weekday;
    a "Check now" reading never counts toward the week)."""
    week_rows = [r for r in rows if r.get("kind") in ("sunday", "weekday")]
    peak_mem = None
    for r in reversed(week_rows):
        m = r.get("metrics") if isinstance(r.get("metrics"), dict) else {}
        if _num(m, "mem_total"):
            peak_mem = _num(m, "mem_total")
            break
    size, source = current_size(peak_mem)
    peak = summarize(week_rows, size)
    return {"size": size, "size_source": source, "peak": peak, "verdict": judge(size, peak, churches),
            "tops": tops_from(week_rows)}


async def report_week(sunday: date) -> Dict[str, Any]:
    """Write the week's verdict once and tell the owner if it turned to
    "Time to move up". Never raises out."""
    start, end = week_bounds(sunday)
    rows = await asyncio.to_thread(read_rows, start, end)
    if rows is None:
        return {"week": sunday.isoformat(), "written": False, "why": "readings unread"}
    churches = await asyncio.to_thread(count_churches)
    got = week_verdict(rows, churches)
    v = got["verdict"]
    record = {"week": sunday.isoformat(), "size": got["size"]["key"], "churches": churches,
              "level": v["level"], "headline": v["headline"][:200], "reasons": v["reasons"],
              "peak": got["peak"], "tops": got["tops"]}
    inserted = await asyncio.to_thread(
        sb_clients.sb_post_as_service, f"{WEEKS}?on_conflict=week", record,
        "resolution=ignore-duplicates,return=representation", redact=True)
    if not isinstance(inserted, list):
        return {"week": sunday.isoformat(), "written": False, "why": "not written"}
    _state["reported"] = sunday
    out: Dict[str, Any] = {"week": sunday.isoformat(), "written": bool(inserted), "level": v["level"],
                           "headline": v["headline"], "told": None}
    if not inserted:
        return out
    prev_rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"{WEEKS}?week=eq.{(sunday - timedelta(days=7)).isoformat()}&select=level,headline&limit=1")
    previous = prev_rows[0] if isinstance(prev_rows, list) and prev_rows else None
    if should_tell(v, previous):
        out["told"] = await _tell(sunday, v)
    cutoff = _now() - timedelta(weeks=KEEP_WEEKS)
    await asyncio.to_thread(sb_clients.sb_delete_as_service, f"{SAMPLES}?created_at=lt.{_z(cutoff)}")
    return out


async def _tell(sunday: date, verdict: Dict[str, Any]) -> Optional[str]:
    """The owner alert, claimed on the week's row so it goes once."""
    claim = await asyncio.to_thread(
        sb_clients.sb_patch_as_service, f"{WEEKS}?week=eq.{sunday.isoformat()}&told_at=is.null",
        {"told_at": _z(_now())})
    if not claim:
        return None
    import dev_alerts
    title, body = alert_words(verdict)
    nxt = (verdict.get("next") or {}).get("key") or "more"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            return await dev_alerts.raise_alert(
                c, source="database", kind="move_up", key=f"db-health:{sunday.isoformat()}:{nxt}",
                level="warn", title=title, body=body, nav=NAV)
    except Exception as e:  # noqa: BLE001 — the card still says it; the alert is best effort
        print(f"[db_health] owner alert failed: {type(e).__name__}", flush=True)
        return "failed"


async def tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every 5 minutes on the scheduler's leader: the slot's reading when
    one is due, and the Monday report when it is due and not written."""
    if not enabled():
        return {"skipped": "off"}
    if time.monotonic() < _state["unset_until"]:
        return {"skipped": "not set up"}
    now = now or _now()
    out: Dict[str, Any] = {}
    try:
        due = slot_for(now)
        if due:
            slot, kind = due
            out["reading"] = await take_reading(slot, kind, top=last_of_window(slot, kind))
        week = due_week(now)
        if _state["reported"] != week and time.monotonic() >= _state["unset_until"]:
            rows = await asyncio.to_thread(
                sb_clients.sb_get_as_service, f"{WEEKS}?week=eq.{week.isoformat()}&select=week&limit=1")
            if isinstance(rows, list) and rows:
                _state["reported"] = week
            elif isinstance(rows, list):
                out["report"] = await report_week(week)
            elif _missing(sb_clients.last_error()):
                _unset()
    except Exception as e:  # noqa: BLE001 — a scheduled job never takes the process down
        print(f"[db_health] tick failed: {type(e).__name__}: {e}", flush=True)
        out["error"] = type(e).__name__
    return out


# ─── The card ───────────────────────────────────────────────────────────

def _latest(rows: List[Dict[str, Any]], size: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The last reading of any kind (a "Check now" too), with rates when the
    one before it is close enough to measure from."""
    taken = [r for r in rows if _parse(r.get("taken_at"))]
    if not taken:
        return None
    taken.sort(key=lambda r: _parse(r["taken_at"]))
    last = taken[-1]
    s = summarize(taken[-2:], size)
    s.pop("readings", None)
    return {"at": last.get("taken_at"), "kind": last.get("kind"), "problem": last.get("problem"), **s}


def build_summary(now: datetime, rows: Optional[List[Dict[str, Any]]],
                  weeks: Optional[List[Dict[str, Any]]], churches: Optional[int]) -> Dict[str, Any]:
    """What the card shows (pure but for the env)."""
    if rows is None or weeks is None:
        size, source = current_size(None)
        return {"enabled": True, "set_up": False, "migration": MIGRATION,
                "size": {"key": size["key"], "label": size["label"], "source": source},
                "sizes": sizes_table(size), "churches": {"count": churches, "range": churches_words(size)},
                "schedule": SCHEDULE_WORDS, "disk_note": DISK_BALANCE_WORDS}
    sunday = last_sunday(now)
    start, end = week_bounds(sunday)
    in_week = [r for r in rows if (at := _parse(r.get("taken_at"))) and start <= at < end]
    got = week_verdict(in_week, churches)
    size = got["size"]
    latest = _latest(rows, size)
    if got["size_source"] != "measured" and latest and latest.get("memory_total"):
        size, source = current_size(latest["memory_total"])
        got = {**got, "size": size, "size_source": source, "peak": summarize(
            [r for r in in_week if r.get("kind") in ("sunday", "weekday")], size)}
        got["verdict"] = judge(size, got["peak"], churches)
    local = now.astimezone(ET)
    so_far = local.date() == sunday and local.timetz().replace(tzinfo=None) <= SUNDAY_LAST
    import member_stopwatch
    return {
        "enabled": True, "set_up": True,
        "size": {"key": size["key"], "label": size["label"], "memory_gb": size["memory_gb"],
                 "monthly": monthly(size), "disk_mbs": size["disk_mbs"], "iops": size["iops"],
                 "source": got["size_source"]},
        "sizes": sizes_table(size),
        "churches": {"count": churches, "range": churches_words(size), "top": size["churches"][1]},
        "week": {"sunday": sunday.isoformat(), "so_far": so_far, "readings": got["peak"]["readings"],
                 "sunday_readings": got["peak"]["sunday_readings"],
                 "weekday_readings": got["peak"]["weekday_readings"]},
        "peak": got["peak"], "verdict": got["verdict"], "tops": got["tops"] or tops_from(rows),
        "latest": latest,
        "history": [{"week": w.get("week"), "level": w.get("level"), "headline": w.get("headline"),
                     "told": bool(w.get("told_at"))} for w in weeks],
        "schedule": SCHEDULE_WORDS, "disk_note": DISK_BALANCE_WORDS,
        "member_app": member_stopwatch.card(in_week, rows, so_far=so_far, when_words=when_words),
    }


async def _summary(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    rows, weeks, churches = await asyncio.gather(
        asyncio.to_thread(read_rows, now - timedelta(days=8), now + timedelta(minutes=1)),
        asyncio.to_thread(read_weeks, 8),
        asyncio.to_thread(churches_cached))
    return build_summary(now, rows, weeks, churches)


@router.get("/summary")
async def summary():
    if not enabled():
        return {"enabled": False}
    try:
        return await _summary()
    except Exception as e:  # noqa: BLE001 — the card says it couldn't read, never a 500
        logger.warning("db health summary failed: %s", type(e).__name__)
        raise HTTPException(503, "The database check couldn't be read just now. Try again in a minute.")


@router.post("/check")
async def check_now():
    """A reading now, outside the schedule ("Check now" on the card): never
    counted toward the week, and it shows whether Supabase's feed answers."""
    if not enabled():
        raise HTTPException(409, "The weekly database check is off.")
    if time.monotonic() - _state["last_check"] < CHECK_GAP_SECONDS:
        raise HTTPException(429, "That was just checked. Give it a minute.")
    _state["last_check"] = time.monotonic()
    now = _now().replace(microsecond=0)
    got = await take_reading(now, "manual", top=True)
    if not got.get("taken"):
        if got.get("claimed") is None:
            raise HTTPException(503, f"The database check isn't set up yet: apply {MIGRATION}.")
        raise HTTPException(429, "That was just checked. Give it a minute.")
    return await _summary(now + timedelta(seconds=1))
