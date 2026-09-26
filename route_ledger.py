"""
route_ledger.py — every routed request, and the first-token SLO.

One row per Chief stream request in `model_route_log` (APPLY-2026-09-25-
model-route-log.sql): the complexity score and how it was reached, the lane,
the model that answered, whether it escalated and why, time to first token,
total time, and what the request cost across every model call it made. The
routing thresholds in model_router are dials; this is what they get tuned
against.

TIME TO FIRST TOKEN IS A HARD SLO
  Budget: ROUTER_TTFT_BUDGET_MS (500). Measured per request from the moment
  the request reached the app (sse_middleware stamps it, before auth) to the
  moment the first word of the reply left the stream generator. Every
  request is judged against it and the verdict is on its row. A rolling
  window (ROUTER_SLO_WINDOW_S, 15 min) keeps the recent measurements; when
  its p95 goes over budget with at least ROUTER_SLO_MIN_SAMPLES in it, the
  owner gets one Mission Control finding and one push, then nothing more
  until ROUTER_SLO_ALERT_COOLDOWN_S has passed AND the p95 has recovered —
  one page per incident, not one per request.

COST
  The turn's own model calls are tallied as they happen: a context-local
  Tally is set by the stream endpoint and inherited by the turn task, and
  the two places Chief's model spend passes through (chief_of_staff.
  _call_claude's streaming branch and the llm_call seam's _meter) add to it.
  api_usage stays the billing ledger; this is the per-request view of the
  same numbers.

Writes go through the service role (the table has RLS on and no policies:
server-owned rows, see docs/RLS_MODEL.md and the 2026-09-14 lesson that a
user-JWT write to such a table vanishes silently). Before the migration is
applied the write fails soft once and the `[route]` log line still carries
every field.
"""
from __future__ import annotations

import contextvars
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("route_ledger")
if not logger.handlers:
    # Its own handler at INFO, like chief.truth: under the root's default
    # level the per-request [route] line — the only record until
    # model_route_log is applied — never reached the Railway logs.
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] route: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


def budget_ms() -> int:
    try:
        return max(100, int(os.environ.get("ROUTER_TTFT_BUDGET_MS") or 500))
    except (TypeError, ValueError):
        return 500


def _int_env(name: str, default: int, lo: int) -> int:
    try:
        return max(lo, int(os.environ.get(name) or default))
    except (TypeError, ValueError):
        return default


# ─── Cost tally ──────────────────────────────────────────────────────

class Tally:
    """Tokens and cents for one request, across every model it used."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_model: Dict[str, Dict[str, int]] = {}
        self.frozen = False

    def add(self, model: str, input_tokens: int = 0, output_tokens: int = 0,
            cache_read: int = 0, cache_write: int = 0) -> None:
        if self.frozen:
            return          # background work the turn spawned, after it ended
        m = str(model or "unknown")
        with self._lock:
            row = self.by_model.setdefault(m, {"calls": 0, "in": 0, "out": 0,
                                               "cache_read": 0, "cache_write": 0})
            row["calls"] += 1
            row["in"] += int(input_tokens or 0)
            row["out"] += int(output_tokens or 0)
            row["cache_read"] += int(cache_read or 0)
            row["cache_write"] += int(cache_write or 0)

    def totals(self) -> Dict[str, int]:
        t = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0}
        with self._lock:
            for row in self.by_model.values():
                for k in t:
                    t[k] += row.get(k, 0)
        return t

    def cost_cents(self) -> float:
        total = 0.0
        with self._lock:
            items = list(self.by_model.items())
        for model, row in items:
            pin, pout = _price(model)
            total += (row["in"] * pin + row["out"] * pout
                      + row["cache_read"] * pin * 0.1
                      + row["cache_write"] * pin * 1.25) / 1_000_000.0
        return round(total, 4)


def _price(model: str) -> Tuple[float, float]:
    """(input, output) cents per million tokens, from the billing ledger's
    own table so the two can never disagree."""
    try:
        import api_usage_logger
        pin, pout = api_usage_logger._price_for_model(model)
        return float(pin), float(pout)
    except Exception:
        return 0.0, 0.0


TALLY: "contextvars.ContextVar[Optional[Tally]]" = contextvars.ContextVar(
    "route_tally", default=None)


def tally(model: str, input_tokens: int = 0, output_tokens: int = 0,
          cache_read: int = 0, cache_write: int = 0) -> None:
    """Add one model call to the current request's tally, if one is open.
    Never raises; costs nothing when no request is being routed."""
    try:
        t = TALLY.get()
        if t is not None:
            t.add(model, input_tokens, output_tokens, cache_read, cache_write)
    except Exception:
        pass


def tally_usage(model: str, usage: Optional[Dict[str, Any]]) -> None:
    """tally() from a Messages API `usage` object."""
    if not isinstance(usage, dict):
        return
    tally(model, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0),
          int(usage.get("cache_read_input_tokens") or 0),
          int(usage.get("cache_creation_input_tokens") or 0))


# ─── One request ─────────────────────────────────────────────────────

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _uuid_or_none(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    return s if _UUID.match(s) else None


@dataclass
class RouteRecord:
    arrived: float                                 # perf_counter at arrival
    business_id: Optional[str] = None
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    surface: Optional[str] = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    lane: str = "full"
    reason: str = ""
    complexity: Dict[str, Any] = field(default_factory=dict)
    classifier_ms: Optional[int] = None
    opener_source: str = "none"   # model | local | client | answer | cache | none
    opener_cut: Optional[str] = None
    answer_model: Optional[str] = None
    escalated: bool = False
    escalation_reason: Optional[str] = None
    cache_hit: bool = False
    cache_similarity: Optional[float] = None
    first_token_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    slo_applies: bool = True       # False: the app talking to itself (sentinels)
    tally: Tally = field(default_factory=Tally)

    def mark_first_token(self, source: Optional[str] = None) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()
            if source:
                self.opener_source = source

    def escalate(self, reason: str) -> None:
        if not self.escalated:
            self.escalated = True
            self.escalation_reason = reason

    @property
    def ttft_ms(self) -> Optional[int]:
        if self.first_token_at is None:
            return None
        return int((self.first_token_at - self.arrived) * 1000)

    @property
    def total_ms(self) -> Optional[int]:
        end = self.finished_at or time.perf_counter()
        return int((end - self.arrived) * 1000)

    def row(self) -> Dict[str, Any]:
        t = self.tally.totals()
        ttft = self.ttft_ms
        budget = budget_ms()
        c = self.complexity or {}
        return {
            "request_id": self.request_id,
            "business_id": _uuid_or_none(self.business_id),
            "user_id": _uuid_or_none(self.user_id),
            "conversation_id": (str(self.conversation_id)[:80] if self.conversation_id else None),
            "surface": (self.surface or "desktop")[:20],
            "lane": self.lane,
            "reason": (self.reason or "")[:120],
            "complexity": c.get("score"),
            "confidence": c.get("confidence"),
            "kind": c.get("kind"),
            "classifier": c.get("source"),
            "classifier_ms": self.classifier_ms,
            "signals": c.get("signals") or [],
            "opener_source": self.opener_source,
            "opener_cut": self.opener_cut,
            "answer_model": self.answer_model,
            "models": self.tally.by_model,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
            "cache_hit": self.cache_hit,
            "cache_similarity": self.cache_similarity,
            "ttft_ms": ttft,
            "total_ms": self.total_ms,
            "budget_ms": budget,
            "slo_applies": self.slo_applies,
            "slo_met": (ttft is not None and ttft <= budget) if self.slo_applies else None,
            "input_tokens": t["in"],
            "output_tokens": t["out"],
            "cache_read_tokens": t["cache_read"],
            "cache_write_tokens": t["cache_write"],
            "cost_cents": self.tally.cost_cents(),
            "error": (self.error or None) and str(self.error)[:200],
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


# ─── The SLO window ──────────────────────────────────────────────────

class SloWindow:
    """Recent latencies, the p95 over them, and the page.

    One class for both hard latency SLOs: time to first TOKEN on every
    streamed turn (this module, `ttft_ms`, ROUTER_SLO_*) and time to first
    AUDIO on every spoken call turn (voice_metrics, `ttfa_ms`, VOICE_SLO_*).
    Each has its own window, budget and page, so one cannot mask the other."""

    def __init__(self, *, metric: str = "ttft_ms", budget=None, env: str = "ROUTER_SLO") -> None:
        self._lock = threading.Lock()
        self._samples: Deque[Tuple[float, int]] = deque(maxlen=5000)
        self._lanes: Deque[Tuple[float, str, bool, str, float]] = deque(maxlen=5000)
        self._alert_open = False
        self._alerted_at = 0.0
        self.metric = metric
        self._budget = budget or budget_ms
        self._env = env

    def budget(self) -> int:
        return int(self._budget())

    def window_s(self) -> int:
        return _int_env(f"{self._env}_WINDOW_S", 900, 60)

    def _trim(self, now: float) -> None:
        cut = now - self.window_s()
        while self._samples and self._samples[0][0] < cut:
            self._samples.popleft()
        while self._lanes and self._lanes[0][0] < cut:
            self._lanes.popleft()

    def add(self, row: Dict[str, Any], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Record one request; returns the alert to send, if this one
        tipped the window over budget."""
        now = time.time() if now is None else now
        with self._lock:
            ttft = row.get(self.metric)
            if row.get("slo_applies", True):
                # A request that never produced a word (it errored first) is
                # a miss, not a gap in the data: count it at its total time.
                if not isinstance(ttft, int) and isinstance(row.get("total_ms"), int):
                    ttft = row["total_ms"]
                if isinstance(ttft, int):
                    self._samples.append((now, ttft))
            self._lanes.append((now, str(row.get("lane")), bool(row.get("escalated")),
                                str(row.get("opener_source")), float(row.get("cost_cents") or 0)))
            self._trim(now)
            p95 = self._pct(95)
            n = len(self._samples)
            budget = self.budget()
            if p95 is None or n < _int_env(f"{self._env}_MIN_SAMPLES", 20, 1):
                return None
            if p95 <= budget:
                self._alert_open = False            # recovered: re-arm
                return None
            cooldown = _int_env(f"{self._env}_ALERT_COOLDOWN_S", 3600, 60)
            if self._alert_open and now - self._alerted_at < cooldown:
                return None
            self._alert_open = True
            self._alerted_at = now
            return {"p95_ms": p95, "p50_ms": self._pct(50), "samples": n,
                    "budget_ms": budget, "window_s": self.window_s()}

    def _pct(self, p: float) -> Optional[int]:
        vals = sorted(v for _, v in self._samples)
        return percentile(vals, p)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._trim(time.time())
            vals = sorted(v for _, v in self._samples)
            lanes = list(self._lanes)
        budget = self.budget()
        name = self.metric.replace("_ms", "")
        out: Dict[str, Any] = {
            "window_s": self.window_s(), "budget_ms": budget, "samples": len(vals),
            f"{name}_p50_ms": percentile(vals, 50), f"{name}_p95_ms": percentile(vals, 95),
            f"{name}_p99_ms": percentile(vals, 99),
            "slo_met_pct": (round(100.0 * sum(1 for v in vals if v <= budget) / len(vals), 1)
                            if vals else None),
            "alert_open": self._alert_open,
        }
        out.update(_mix(lanes))
        return out


def percentile(sorted_vals: List[int], p: float) -> Optional[int]:
    """Nearest-rank percentile of an ascending list."""
    if not sorted_vals:
        return None
    k = max(1, int(math.ceil(p / 100.0 * len(sorted_vals))))
    return int(sorted_vals[min(k, len(sorted_vals)) - 1])


def _mix(lanes: List[Tuple[float, str, bool, str, float]]) -> Dict[str, Any]:
    n = len(lanes)
    by_lane: Dict[str, int] = {}
    by_opener: Dict[str, int] = {}
    esc = 0
    cost = 0.0
    for _, lane, escalated, opener, cents in lanes:
        by_lane[lane] = by_lane.get(lane, 0) + 1
        by_opener[opener] = by_opener.get(opener, 0) + 1
        esc += 1 if escalated else 0
        cost += cents
    return {"requests": n, "by_lane": by_lane, "by_opener": by_opener,
            "escalation_rate": round(esc / n, 3) if n else None,
            "cost_cents": round(cost, 2)}


WINDOW = SloWindow()
_table_missing_logged = False


def finish(rec: RouteRecord) -> Dict[str, Any]:
    """Close a request: freeze its tally, log it, write its row, feed the
    SLO window, page the owner if that tipped it. Never raises."""
    try:
        rec.tally.frozen = True
        if rec.finished_at is None:
            rec.finished_at = time.perf_counter()
        row = rec.row()
    except Exception as e:  # pragma: no cover — a log must never cost a reply
        logger.warning("[route] record failed: %s", e)
        return {}
    logger.info(
        "[route] lane=%s reason=%s kind=%s score=%s conf=%s src=%s opener=%s%s ttft=%sms "
        "budget=%sms slo=%s total=%sms escalated=%s%s cache=%s cost=%sc models=%s",
        row["lane"], row["reason"], row["kind"], row["complexity"], row["confidence"],
        row["classifier"], row["opener_source"],
        f"(cut:{row['opener_cut']})" if row.get("opener_cut") else "",
        row["ttft_ms"], row["budget_ms"], "met" if row["slo_met"] else "MISSED",
        row["total_ms"], row["escalated"],
        f"({row['escalation_reason']})" if row.get("escalation_reason") else "",
        row["cache_hit"], row["cost_cents"], ",".join(sorted(row["models"] or {})))
    try:
        alert = WINDOW.add(row)
        if alert:
            _page_owner(alert)
    except Exception as e:  # pragma: no cover
        logger.warning("[route] slo window failed: %s", e)
    _write_row(row)
    return row


_skip_db_until = 0.0


def _write_row(row: Dict[str, Any]) -> None:
    def _go() -> None:
        global _table_missing_logged, _skip_db_until
        try:
            import sb_clients
            # return=representation: an empty body is how success reads
            # otherwise, and it would look exactly like a failure here.
            res = sb_clients.sb_post_as_service("/model_route_log", row)
            ok = bool(res)
        except Exception as e:
            ok = False
            logger.debug("[route] model_route_log write raised: %s", e)
        if not ok:
            # Most likely the migration is not applied yet. Back off for ten
            # minutes rather than logging a PostgREST 404 on every turn.
            _skip_db_until = time.time() + 600
            if not _table_missing_logged:
                _table_missing_logged = True
                logger.warning("[route] model_route_log write failed — is "
                               "supabase/APPLY-2026-09-25-model-route-log.sql applied? "
                               "The [route] log lines carry every field meanwhile.")
    if (os.environ.get("ROUTER_LOG_DB") or "on").strip().lower() == "off":
        return
    if time.time() < _skip_db_until:
        return
    try:
        threading.Thread(target=_go, name="route-log", daemon=True).start()
    except Exception:  # pragma: no cover
        pass


def _page_owner(alert: Dict[str, Any]) -> None:
    """One Mission Control finding + one push — the spend guard's channel."""
    note = (f"Chief's time to first word is over its budget: p95 {alert['p95_ms']}ms "
            f"against {alert['budget_ms']}ms (p50 {alert['p50_ms']}ms) over the last "
            f"{alert['samples']} requests in {alert['window_s'] // 60} minutes. The local "
            f"lead should hold the budget whatever the models do, so a breach means requests "
            f"are slow before the stream starts (auth, the event loop, the host) — read the "
            f"[route] log lines. Budget: ROUTER_TTFT_BUDGET_MS.")
    logger.warning("[route] SLO BREACH %s", alert)
    page_owner("Chief first-word time over budget (p95)", note,
               push_title="Chief is slow to start replying",
               push_body=f"p95 first word {alert['p95_ms']}ms (budget {alert['budget_ms']}ms).")


def page_owner(finding_title: str, note: str, *, push_title: str, push_body: str) -> None:
    """One Mission Control finding + one push to the platform owner — the
    spend guard's channel. Fire-and-forget; never raises."""
    try:
        import asyncio
        import httpx
        import platform_watchdog as wd
        import push_notifications
        from lead_admin import _service_headers

        async def _go():
            headers = _service_headers()
            async with httpx.AsyncClient(timeout=15) as c:
                await wd._log_finding(c, headers, finding_title, note, pending=True)
                owner = await wd._owner_user_id(c, headers)
            if owner:
                push_notifications.send_to_user(owner, title=push_title, body=push_body,
                                                nav="studio")

        try:
            asyncio.get_running_loop().create_task(_go())
        except RuntimeError:
            asyncio.run(_go())
    except Exception as e:
        logger.warning("[route] owner page failed (non-fatal): %s", e)


# ─── Stats for the owner ─────────────────────────────────────────────

def stats_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate model_route_log rows into what threshold tuning needs:
    first-token percentiles, lane mix, and — per complexity band — how
    often a request was escalated, which is the signal that a threshold
    is too low (fast answers that did not hold) or too high."""
    rows = [r for r in rows if isinstance(r, dict)]
    ttft = sorted(int(r["ttft_ms"]) for r in rows if isinstance(r.get("ttft_ms"), int))
    budget = budget_ms()
    bands: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            s = float(r.get("complexity"))
        except (TypeError, ValueError):
            continue
        b = f"{min(0.9, math.floor(s * 10) / 10):.1f}"
        band = bands.setdefault(b, {"requests": 0, "fast": 0, "escalated": 0, "cost_cents": 0.0})
        band["requests"] += 1
        band["fast"] += 1 if r.get("lane") == "fast" else 0
        band["escalated"] += 1 if r.get("escalated") else 0
        band["cost_cents"] = round(band["cost_cents"] + float(r.get("cost_cents") or 0), 4)
    lanes = [(0.0, str(r.get("lane")), bool(r.get("escalated")), str(r.get("opener_source")),
              float(r.get("cost_cents") or 0)) for r in rows]
    by_model: Dict[str, int] = {}
    for r in rows:
        m = r.get("answer_model")
        if m:
            by_model[m] = by_model.get(m, 0) + 1
    out = {
        "requests": len(rows), "budget_ms": budget,
        "ttft_p50_ms": percentile(ttft, 50), "ttft_p95_ms": percentile(ttft, 95),
        "ttft_p99_ms": percentile(ttft, 99),
        "slo_met_pct": (round(100.0 * sum(1 for v in ttft if v <= budget) / len(ttft), 1)
                        if ttft else None),
        "complexity_bands": dict(sorted(bands.items())),
        "answer_models": by_model,
    }
    out.update({k: v for k, v in _mix(lanes).items() if k != "requests"})
    return out
