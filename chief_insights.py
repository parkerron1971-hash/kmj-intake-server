"""
chief_insights.py — Chief Layers arc (2026-07-09): the weekly
longitudinal insight engine.

WHY: chief_memories holds durable facts, but nothing in the system ever
looks BACKWARD across months of bookings/revenue/clients and says "your
Tuesdays have been dying since March." That longitudinal read is the
thing a generic assistant can never know — it compounds with every week
a business runs on the platform. This module is that layer.

WHAT IT DOES (per business, roughly weekly):
  1. Pulls 12 weeks of operating data — sessions by week + weekday,
     paid revenue by week, new contacts, repeat-client concentration.
  2. Hands the digest + existing memories to the "insight" model lane
     (Opus 4.8 by default — low volume, highest stakes) and asks for at
     most 3 insights, each a pattern + a recommended move, grounded in
     the digest's numbers. Empty array is a valid, expected answer.
  3. Stores each insight as a chief_memories row (category="insight",
     source="ai_inferred") — so it flows into Chief's prompt through
     the existing memory pipeline and renders under the LONGITUDINAL
     INSIGHTS section — plus a chief_activity row so the practitioner
     sees "Chief noticed something" in the recap rail.
  4. Retires insight memories older than 45 days (is_active=false) so
     the section stays a rolling window, and prunes stale never-
     referenced low-importance memories (deterministic, mark-inactive
     only — nothing is deleted).

COST GUARDS (this lane runs Opus — guard it):
  - Eligibility gate: businesses without enough history (fewer than
    5 sessions AND fewer than 3 paid invoices in the window) are marked
    as run and SKIPPED — no LLM call on empty tenants.
  - Cadence marker lives in businesses.settings.chief_insights
    (last_run_at), written even on skips, so a zero-insight business
    doesn't re-run every tick.
  - Tick cap: at most MAX_PER_TICK businesses per 6-hour tick.
  - Kill switch: CHIEF_INSIGHTS=off.

Sync module (service-role sb_clients), run off-thread by async callers —
same pattern as rules_engine / chief_bookkeeping.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

import sb_clients
import chief_models
from api_usage_logger import log_api_usage_sync

logger = logging.getLogger("chief_insights")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

WINDOW_DAYS = 84            # 12 weeks of history feeds each analysis
CADENCE_DAYS = 6.5          # re-run once this much time has passed
INSIGHT_RETIRE_DAYS = 45    # insights older than this leave the prompt
MAX_PER_TICK = 8            # Opus cost cap per 6h tick
MAX_INSIGHTS = 3
MIN_SESSIONS = 5            # eligibility: enough history to analyze...
MIN_PAID_INVOICES = 3       # ...on either the calendar or the money side
PRUNE_AFTER_DAYS = 120      # stale-memory pruning (never-referenced, low importance)
PRUNE_MAX_IMPORTANCE = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _enabled() -> bool:
    return (os.environ.get("CHIEF_INSIGHTS") or "on").lower() != "off"


def _week_key(iso_str: str) -> Optional[str]:
    """Monday-of-week date string for an ISO timestamp."""
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    monday = dt.date() - timedelta(days=dt.weekday())
    return monday.isoformat()


# ─── Data digest ─────────────────────────────────────────────────────

def _gather_digest(biz_id: str) -> Dict[str, Any]:
    """12 weeks of operating data, compacted for the model."""
    start = _iso(_now() - timedelta(days=WINDOW_DAYS))

    sessions = sb_clients.sb_get_as_service(
        f"/sessions?business_id=eq.{biz_id}&scheduled_for=gte.{start}"
        f"&select=scheduled_for,status,contact_id&limit=1000") or []
    invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz_id}&created_at=gte.{start}"
        f"&select=total,status,paid_at,created_at&limit=1000") or []
    contacts = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{biz_id}"
        f"&select=id,created_at,status,health_score&limit=1000") or []

    sessions_by_week: Dict[str, int] = defaultdict(int)
    sessions_by_weekday: Dict[str, int] = defaultdict(int)
    per_contact: Dict[str, int] = defaultdict(int)
    cancelled = 0
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for s in sessions:
        wk = _week_key(s.get("scheduled_for"))
        if wk:
            sessions_by_week[wk] += 1
        try:
            dt = datetime.fromisoformat(str(s.get("scheduled_for")).replace("Z", "+00:00"))
            sessions_by_weekday[weekdays[dt.weekday()]] += 1
        except (ValueError, TypeError):
            pass
        if s.get("contact_id"):
            per_contact[s["contact_id"]] += 1
        if (s.get("status") or "").lower() in ("cancelled", "canceled", "no_show"):
            cancelled += 1

    revenue_by_week: Dict[str, float] = defaultdict(float)
    paid_count = 0
    unpaid_total = 0.0
    for inv in invoices:
        try:
            total = float(inv.get("total") or 0)
        except (TypeError, ValueError):
            total = 0.0
        if inv.get("paid_at"):
            paid_count += 1
            wk = _week_key(inv.get("paid_at"))
            if wk:
                revenue_by_week[wk] += total
        elif (inv.get("status") or "").lower() in ("sent", "viewed", "overdue"):
            unpaid_total += total

    cutoff = _now() - timedelta(days=WINDOW_DAYS)
    new_contacts = 0
    for c in contacts:
        try:
            created = datetime.fromisoformat(str(c.get("created_at")).replace("Z", "+00:00"))
            if created >= cutoff:
                new_contacts += 1
        except (ValueError, TypeError):
            pass

    repeat_clients = sum(1 for n in per_contact.values() if n >= 2)
    booked_clients = len(per_contact)

    return {
        "sessions_total": len(sessions),
        "sessions_by_week": dict(sorted(sessions_by_week.items())),
        "sessions_by_weekday": {d: sessions_by_weekday[d] for d in weekdays if sessions_by_weekday[d]},
        "cancelled_or_noshow": cancelled,
        "booked_clients": booked_clients,
        "repeat_clients": repeat_clients,
        "revenue_by_week": {k: round(v, 2) for k, v in sorted(revenue_by_week.items())},
        "paid_invoices": paid_count,
        "unpaid_outstanding": round(unpaid_total, 2),
        "contacts_total": len(contacts),
        "new_contacts_in_window": new_contacts,
    }


# ─── LLM synthesis ───────────────────────────────────────────────────

_SYSTEM = """You are the analytical layer of Chief, the operating intelligence of a small-business platform. You look across twelve weeks of one business's real operating data and surface longitudinal patterns the owner is too close to see.

Rules:
- Every insight must be grounded in the numbers you were given — cite the actual figures or weeks in the pattern sentence. Never invent data.
- An insight is a TREND or PATTERN across weeks (drift, concentration, decay, momentum) — not a restatement of a single number.
- Do not repeat or lightly rephrase an existing insight you were shown.
- Fewer, sharper insights beat filler. If nothing meaningful stands out, return [].
- Each "move" is one concrete, doable next step for a busy owner — not generic advice.

Respond with ONLY a JSON array (no prose, no markdown fence), at most {max_n} items:
[{"pattern": "<one sentence, cites the data>", "move": "<one sentence, concrete next step>"}]"""


def _synthesize(biz: Dict[str, Any], digest: Dict[str, Any],
                memories: List[Dict], existing_insights: List[str]) -> List[Dict[str, str]]:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return []
    # Pricing v2 model ladder: insight quality scales with the tier.
    try:
        import feature_gates as _fg
        _plan = _fg.plan_of(biz) if isinstance(biz, dict) else None
    except Exception:
        _plan = None
    model = chief_models.model_for("insight", _plan)

    mem_lines = "\n".join(
        f"- [{m.get('category')}] {m.get('content')}" for m in memories[:30]
    ) or "(none)"
    existing_lines = "\n".join(f"- {t}" for t in existing_insights) or "(none)"
    user_msg = (
        f"BUSINESS: {biz.get('name')} (type: {biz.get('type') or 'general'})\n\n"
        f"TWELVE-WEEK OPERATING DIGEST (weeks keyed by their Monday):\n"
        f"{json.dumps(digest, indent=1)}\n\n"
        f"WHAT CHIEF ALREADY KNOWS ABOUT THIS PRACTITIONER:\n{mem_lines}\n\n"
        f"INSIGHTS ALREADY SURFACED (do not repeat these):\n{existing_lines}\n\n"
        f"Return the JSON array now."
    )

    try:
        resp = httpx.post(ANTHROPIC_API_URL, headers={
            "x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }, json={
            "model": model, "max_tokens": 1000,
            "system": _SYSTEM.replace("{max_n}", str(MAX_INSIGHTS)),
            "messages": [{"role": "user", "content": user_msg}],
        }, timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0))
    except httpx.HTTPError as e:
        logger.warning(f"[insights] LLM call failed: {e}")
        log_api_usage_sync(endpoint="/chief/insights", model=model,
                           input_tokens=0, output_tokens=0,
                           business_id=biz.get("id"), ok=False)
        return []
    if resp.status_code >= 400:
        logger.warning(f"[insights] LLM error {resp.status_code}: {resp.text[:200]}")
        log_api_usage_sync(endpoint="/chief/insights", model=model,
                           input_tokens=0, output_tokens=0,
                           business_id=biz.get("id"), ok=False)
        return []

    data = resp.json()
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    log_api_usage_sync(endpoint="/chief/insights", model=data.get("model") or model,
                       input_tokens=int(usage.get("input_tokens") or 0),
                       output_tokens=int(usage.get("output_tokens") or 0),
                       business_id=biz.get("id"))
    text = "".join(
        b.get("text", "") for b in data.get("content", [])
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()

    # Defensive parse — take the outermost JSON array in the reply.
    try:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return []
        items = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        logger.warning(f"[insights] unparseable reply: {text[:200]}")
        return []

    out: List[Dict[str, str]] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        pattern = str(it.get("pattern") or "").strip()
        move = str(it.get("move") or "").strip()
        if pattern and move:
            out.append({"pattern": pattern[:400], "move": move[:400]})
        if len(out) >= MAX_INSIGHTS:
            break
    return out


# ─── Persistence ─────────────────────────────────────────────────────

def _retire_and_prune(biz_id: str) -> None:
    """Rolling-window hygiene. Mark-inactive only — nothing is deleted."""
    retire_before = _iso(_now() - timedelta(days=INSIGHT_RETIRE_DAYS))
    try:
        sb_clients.sb_patch_as_service(
            f"/chief_memories?business_id=eq.{biz_id}&category=eq.insight"
            f"&is_active=eq.true&created_at=lt.{retire_before}",
            {"is_active": False})
    except Exception as e:
        logger.warning(f"[insights] retire failed for {biz_id}: {e}")
    # Deterministic stale-memory pruning: old, low-importance,
    # never referenced since creation → leaves the prompt.
    prune_before = _iso(_now() - timedelta(days=PRUNE_AFTER_DAYS))
    try:
        sb_clients.sb_patch_as_service(
            f"/chief_memories?business_id=eq.{biz_id}&is_active=eq.true"
            f"&category=not.in.(insight,standing_instruction,boundary)"
            f"&importance=lte.{PRUNE_MAX_IMPORTANCE}"
            f"&created_at=lt.{prune_before}&last_referenced_at=is.null",
            {"is_active": False})
    except Exception as e:
        logger.warning(f"[insights] prune failed for {biz_id}: {e}")


def _store(biz: Dict[str, Any], insights: List[Dict[str, str]]) -> int:
    biz_id = biz.get("id")
    stamp = _now().date().isoformat()
    stored = 0
    for ins in insights:
        content = f"[Weekly insight {stamp}] {ins['pattern']} → Move: {ins['move']}"
        row = {
            "business_id": biz_id,
            "category": "insight",
            "content": content[:2000],
            "source": "ai_inferred",
            "importance": 8,
        }
        try:
            res = sb_clients.sb_post_as_service("/chief_memories", row)
        except Exception as e:
            logger.warning(f"[insights] memory insert failed: {e}")
            res = None
        if not res:
            # Fail-soft if a legacy CHECK constraint rejects the new
            # category — the insight still reaches the prompt as a pattern.
            try:
                row["category"] = "pattern"
                res = sb_clients.sb_post_as_service("/chief_memories", row)
            except Exception as e:
                logger.warning(f"[insights] fallback insert failed: {e}")
                res = None
        if res:
            stored += 1
            # Semantic memory: embed the insight at write time. Best-effort.
            try:
                import chief_memory_semantic
                _mid = res[0].get("id") if isinstance(res, list) and res else None
                if _mid:
                    chief_memory_semantic.store_embedding(_mid, row["content"])
            except Exception:
                pass

    if stored and biz.get("owner_id"):
        try:
            sb_clients.sb_post_as_service("/chief_activity", {
                "user_id": biz["owner_id"],
                "business_id": biz_id,
                "source": "system",
                "action_type": "weekly_insight",
                "label": f"Weekly analysis: {insights[0]['pattern'][:100]}",
                "summary": (f"{stored} new insight(s) from twelve weeks of your data — "
                            "ask Chief about them anytime."),
            })
        except Exception as e:
            logger.warning(f"[insights] activity log failed: {e}")
    return stored


def _mark_run(biz: Dict[str, Any], produced: int, skipped: Optional[str] = None) -> None:
    settings = dict(biz.get("settings") or {})
    settings["chief_insights"] = {
        "last_run_at": _iso(_now()),
        "last_count": produced,
        **({"last_skip": skipped} if skipped else {}),
    }
    try:
        sb_clients.sb_patch_as_service(
            f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    except Exception as e:
        logger.warning(f"[insights] mark_run failed for {biz.get('id')}: {e}")


def _due(biz: Dict[str, Any]) -> bool:
    marker = ((biz.get("settings") or {}).get("chief_insights") or {})
    last = marker.get("last_run_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    return (_now() - last_dt) >= timedelta(days=CADENCE_DAYS)


# ─── Entry points ────────────────────────────────────────────────────

def run_for_business(business_id: str, force: bool = False) -> Dict[str, Any]:
    """Analyze one business now. `force` bypasses cadence (not eligibility)."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,type,settings,owner_id&limit=1") or []
    if not rows:
        return {"ok": False, "error": "business not found"}
    biz = rows[0]
    if not force and not _due(biz):
        return {"ok": True, "skipped": "not_due"}

    digest = _gather_digest(business_id)
    if digest["sessions_total"] < MIN_SESSIONS and digest["paid_invoices"] < MIN_PAID_INVOICES:
        _mark_run(biz, 0, skipped="not_enough_history")
        return {"ok": True, "skipped": "not_enough_history", "digest": digest}

    _retire_and_prune(business_id)

    memories = sb_clients.sb_get_as_service(
        f"/chief_memories?business_id=eq.{business_id}&is_active=eq.true"
        f"&category=neq.insight&order=importance.desc&limit=30"
        f"&select=category,content") or []
    existing = sb_clients.sb_get_as_service(
        f"/chief_memories?business_id=eq.{business_id}&is_active=eq.true"
        f"&category=eq.insight&order=created_at.desc&limit=10"
        f"&select=content") or []
    existing_texts = [r.get("content") or "" for r in existing]

    insights = _synthesize(biz, digest, memories, existing_texts)
    stored = _store(biz, insights) if insights else 0
    _mark_run(biz, stored)
    return {"ok": True, "produced": stored,
            "insights": insights, "digest": digest}


async def insights_tick() -> None:
    """Scheduler tick (leader-gated, every 6h). Kill switch CHIEF_INSIGHTS=off."""
    if not _enabled():
        return
    import asyncio

    def _tick_sync() -> None:
        rows = sb_clients.sb_get_as_service(
            "/businesses?select=id,name,type,settings,owner_id&limit=500") or []
        due = [b for b in rows if _due(b)]
        for biz in due[:MAX_PER_TICK]:
            try:
                res = run_for_business(biz["id"])
                produced = res.get("produced")
                if produced:
                    print(f"[Insights tick] {biz.get('name') or biz['id']}: "
                          f"{produced} insight(s)", flush=True)
            except Exception as e:  # pragma: no cover
                logger.warning(f"[insights] tick failed for {biz.get('id')}: {e}")
        if len(due) > MAX_PER_TICK:
            print(f"[Insights tick] {len(due) - MAX_PER_TICK} business(es) "
                  f"deferred to the next tick (cap {MAX_PER_TICK})", flush=True)
        # Semantic memory: embed any memories still missing an embedding
        # (frontend-created rows + the pre-upgrade backlog). Cheap + capped.
        try:
            import chief_memory_semantic
            chief_memory_semantic.backfill_tick(limit=100)
        except Exception:
            pass
        # Standing playbook: re-distill the per-business brief for any
        # business whose facts changed since last time. Cadence + fingerprint
        # gated, capped, fail-open — same 6h tick.
        try:
            import chief_playbook
            chief_playbook.tick(limit=chief_playbook.MAX_PER_TICK)
        except Exception:
            pass

    await asyncio.to_thread(_tick_sync)
