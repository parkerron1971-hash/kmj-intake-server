"""
chief_quality.py — Chief quality & cost, every night (agent operations
plan, Wave 3).

A SENSE, like Hermes and the Money auditor: plain arithmetic over what
Chief already records, no AI, no writes beyond its own report. Before
this, Chief's cost and speed were measured when someone asked.

WHAT IT READS
  model_route_log — one row per Chief turn: cost, time to first word,
                    whether the speed target applied and was met,
                    escalation, error, cache hit.
  api_usage       — every paid call: what the platform spent and where.
  spend_guard     — today's spend against the daily cap.

WHAT IT REPORTS (last 24 hours against the 7 days before)
  turns, cost per turn, first word p50/p90, speed target met, escalation,
  errors, cache hits; total spend, the costliest endpoints and businesses;
  today's spend against the cap.

WHAT IT FLAGS (only with enough turns to mean something)
  cost per turn up 40%+ · speed target met below 80% or down 10+ points ·
  errors at 5%+ · cache hits down 15+ points · today's spend at 70%+ of
  the cap.

The weekly quality half is .github/workflows/chief-eval-weekly.yml: the
turn, factual and advice evals against the real model.

Every run → platform_agent_runs; flags → platform_changelog, where
Business Chief reads them. Daily 07:00 UTC; manual run at
POST /platform/agents/chief-quality/run. Kill switch: CHIEF_QUALITY=off.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from lead_admin import _service_headers, SUPABASE_URL

logger = logging.getLogger("chief_quality")

AGENT = "chief_quality"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0)
MIN_TURNS_DAY = 20
MIN_TURNS_BASE = 50


def enabled() -> bool:
    return (os.environ.get("CHIEF_QUALITY") or "on").strip().lower() not in (
        "0", "off", "false", "no")


def _when(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _pct(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def turn_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure: the numbers for one window of model_route_log rows."""
    n = len(rows)
    if not n:
        return {"turns": 0}
    ttft = sorted(float(r["ttft_ms"]) for r in rows if r.get("ttft_ms") is not None)
    slo = [r for r in rows if r.get("slo_applies")]
    return {
        "turns": n,
        "cost_per_turn_cents": round(sum(float(r.get("cost_cents") or 0) for r in rows) / n, 3),
        "ttft_p50_ms": _pct(ttft, 0.5),
        "ttft_p90_ms": _pct(ttft, 0.9),
        "slo_met_rate": round(sum(1 for r in slo if r.get("slo_met")) / len(slo), 3) if slo else None,
        "escalation_rate": round(sum(1 for r in rows if r.get("escalated")) / n, 3),
        "error_rate": round(sum(1 for r in rows if r.get("error")) / n, 3),
        "cache_hit_rate": round(sum(1 for r in rows if r.get("cache_hit")) / n, 3),
    }


def spend_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure: where the money went in one window of api_usage rows."""
    by_endpoint: Dict[str, float] = defaultdict(float)
    by_business: Dict[str, float] = defaultdict(float)
    total = 0.0
    for r in rows:
        cost = float(r.get("cost_cents") or 0)
        total += cost
        by_endpoint[r.get("endpoint") or "?"] += cost
        if r.get("business_id"):
            by_business[r["business_id"]] += cost
    top = lambda d: [(k, round(v, 1)) for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:5]]
    return {"total_cents": round(total, 1), "calls": len(rows),
            "top_endpoints": top(by_endpoint), "top_businesses": top(by_business)}


def flags(day: Dict[str, Any], base: Dict[str, Any],
          spent_cents: Optional[float], cap_cents: Optional[float]) -> List[Dict[str, Any]]:
    """Pure: what needs a person. Trends only with enough turns on both sides."""
    out: List[Dict[str, Any]] = []

    def flag(code: str, title: str, detail: str, pending: bool = True) -> None:
        out.append({"code": code, "title": f"Chief: {title}", "detail": detail,
                    "pending": pending})

    enough = day.get("turns", 0) >= MIN_TURNS_DAY and base.get("turns", 0) >= MIN_TURNS_BASE
    if enough:
        c1, c0 = day["cost_per_turn_cents"], base["cost_per_turn_cents"]
        if c0 and c1 >= c0 * 1.4:
            flag("cost:per_turn_up", f"cost per reply up {round((c1 / c0 - 1) * 100)}%",
                 f"{c1:.2f}¢ a turn over the last 24h against {c0:.2f}¢ over the week "
                 "before. Check for a model change, a longer prompt or lost caching.")
        s1, s0 = day.get("slo_met_rate"), base.get("slo_met_rate")
        if s1 is not None and (s1 < 0.8 or (s0 is not None and s0 - s1 >= 0.10)):
            flag("speed:slo", f"first word on time in only {round(s1 * 100)}% of turns",
                 f"Speed target met {round(s1 * 100)}% (week before "
                 f"{round(s0 * 100) if s0 is not None else '?'}%). First word p50 "
                 f"{day.get('ttft_p50_ms')} ms, p90 {day.get('ttft_p90_ms')} ms.")
        h1, h0 = day.get("cache_hit_rate"), base.get("cache_hit_rate")
        if h0 is not None and h1 is not None and h0 - h1 >= 0.15:
            flag("cost:cache_drop", f"cache hits down to {round(h1 * 100)}%",
                 f"From {round(h0 * 100)}% over the week before. A prompt change that "
                 "breaks the cache split makes every turn pay full price.")
    if day.get("turns", 0) >= MIN_TURNS_DAY and (day.get("error_rate") or 0) >= 0.05:
        flag("quality:errors", f"{round(day['error_rate'] * 100)}% of turns errored",
             f"{round(day['error_rate'] * day['turns'])} of {day['turns']} turns in the last "
             "24h recorded an error. Sentry has the details.")
    if spent_cents is not None and cap_cents:
        if spent_cents >= 0.7 * cap_cents:
            flag("cost:near_cap", f"today's spend at {round(spent_cents / cap_cents * 100)}% of the cap",
                 f"${spent_cents / 100:.2f} of the ${cap_cents / 100:.0f} daily cap. At the cap "
                 "the spend guard stops paid AI for everyone until midnight UTC.")
    return out


async def _rows(c: httpx.AsyncClient, headers: Dict[str, str], table: str,
                params: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
    try:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params=params)
        if r.status_code < 400 and isinstance(r.json(), list):
            return r.json()
        logger.warning(f"{table} read {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"{table} read failed: {e}")
    return None


async def report(c: httpx.AsyncClient, headers: Dict[str, str],
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    day_start, base_start = now - timedelta(hours=24), now - timedelta(days=8)
    unseen: List[str] = []
    turns = await _rows(c, headers, "model_route_log", {
        "select": "created_at,cost_cents,ttft_ms,slo_applies,slo_met,escalated,error,cache_hit",
        "created_at": f"gte.{base_start.isoformat()}", "limit": "20000"})
    if turns is None:
        unseen.append("Chief turns")
        turns = []
    day_rows = [r for r in turns if (_when(r.get("created_at")) or base_start) >= day_start]
    base_rows = [r for r in turns if (_when(r.get("created_at")) or now) < day_start]
    day, base = turn_metrics(day_rows), turn_metrics(base_rows)
    if base.get("turns"):
        base["turns_per_day"] = round(base["turns"] / 7, 1)

    usage = await _rows(c, headers, "api_usage", {
        "select": "endpoint,cost_cents,business_id",
        "created_at": f"gte.{day_start.isoformat()}", "limit": "20000"})
    if usage is None:
        unseen.append("spend")
    spend = spend_summary(usage or [])

    spent = cap = None
    try:
        import spend_guard
        spent, cap = spend_guard.today_spend_cents(), spend_guard._cap_cents()
    except Exception:
        unseen.append("spend cap")

    return {"day": day, "week_before": base, "spend_24h": spend,
            "today_spent_cents": spent, "cap_cents": cap, "unseen": unseen,
            "flags": flags(day, base, spent, cap)}


def _summary(r: Dict[str, Any]) -> str:
    d, s = r["day"], r["spend_24h"]
    if not d.get("turns"):
        head = "no Chief turns in the last 24h"
    else:
        slo = f", on time {round(d['slo_met_rate'] * 100)}%" if d.get("slo_met_rate") is not None else ""
        head = (f"{d['turns']} turns, {d['cost_per_turn_cents']:.2f}¢ each, first word "
                f"p50 {d.get('ttft_p50_ms')} ms{slo}")
    tail = f"; ${s['total_cents'] / 100:.2f} spent across {s['calls']} paid calls"
    if r["flags"]:
        tail += "; " + "; ".join(f["title"].removeprefix("Chief: ") for f in r["flags"])
    if r["unseen"]:
        tail += "; could not read: " + ", ".join(r["unseen"])
    return head + tail


async def quality_tick() -> Dict[str, Any]:
    """One nightly pass. Never raises (scheduler-safe)."""
    if not enabled():
        return {"skipped": True}
    headers = _service_headers()
    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await report(c, headers, now=started)
            for f in r["flags"]:
                try:
                    await c.post(f"{SUPABASE_URL}/rest/v1/platform_changelog",
                                 headers={**headers, "Prefer": "return=minimal"},
                                 json={"category": "pending" if f["pending"] else "note",
                                       "status": "pending" if f["pending"] else "done",
                                       "title": f["title"][:300], "detail": f["detail"][:2000],
                                       "agent": AGENT})
                except Exception as e:
                    logger.warning(f"finding write failed: {e}")
            summary = _summary(r)
            await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                         headers={**headers, "Prefer": "return=minimal"},
                         json={"agent": AGENT, "started_at": started.isoformat(),
                               "finished_at": datetime.now(timezone.utc).isoformat(),
                               "ok": True, "findings": len(r["flags"]),
                               "summary": summary[:500],
                               "details": {k: v for k, v in r.items() if k != "flags"}})
        return {"ok": True, "summary": summary, "flags": len(r["flags"])}
    except Exception as e:
        logger.error(f"quality tick failed: {e}")
        return {"ok": False, "error": str(e)[:300]}
