"""
chief_playbook.py — the per-business STANDING PLAYBOOK
(compounding intelligence, part 3).

WHY: semantic memory ([[chief_memory_semantic]]) and the weekly insights
([[chief_insights]]) both grow a LIST — over months a business accumulates
dozens of memory rows and a rolling window of insights. A list is retrieval
material, not a point of view. Nothing in the system ever steps back and
says, in a few sentences, "here is who this business IS, what works for
them, what to avoid, and what matters right now." That distilled read is
the thing a generic assistant can never hold, and it gets sharper every
week the business runs on the platform.

WHAT IT DOES (per business, ~weekly):
  1. Pulls the durable memories (the owner's standing facts + preferences)
     and the recent longitudinal insights.
  2. Hands them to the cheap `background` summarization lane and asks for a
     tight standing brief — WHO THIS IS / WHAT WORKS / WHAT TO AVOID /
     RIGHT NOW — written TO the chief of staff, grounded only in the given
     material.
  3. Upserts one row per business into chief_playbooks. `context_block()`
     then prepends it to every Chief conversation as background truth the
     live data can override.

COST GUARDS (this runs an LLM — guard it like the insight lane):
  - Cadence marker in businesses.settings.chief_playbook (last_run_at +
    a source fingerprint), so a business is not re-summarized until enough
    time has passed AND its underlying facts actually changed.
  - Min-source gate: a business with almost nothing learned yet is marked
    and skipped — no LLM call, no thin one-line playbook.
  - Tick cap: at most MAX_PER_TICK businesses per 6-hour tick.
  - Kill switch: CHIEF_PLAYBOOK=off.

Everything FAILS OPEN: no OpenAI/Anthropic key, no table yet, a bad LLM
reply → no row / no block, and Chief behaves exactly as before. Strictly
additive.

Depends on: supabase/APPLY-2026-07-13-chief-playbooks.sql (chief_playbooks
table, service-role only). Sync module (service-role sb_clients), run off
the event loop by async callers — same shape as chief_insights.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

import llm_call

import sb_clients
import chief_models
from api_usage_logger import log_api_usage_sync

logger = logging.getLogger("chief_playbook")


CADENCE_DAYS = 6.5          # re-distill at most this often per business
MAX_PER_TICK = 8            # businesses distilled per 6h tick
MIN_SOURCES = 4             # need at least this much learned material
MAX_MEMORIES = 40           # cap what we feed the summarizer
MAX_INSIGHTS = 12
MAX_WORDS = 220             # target length of the brief


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _enabled() -> bool:
    if (os.environ.get("CHIEF_PLAYBOOK") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ─── Cadence marker (businesses.settings.chief_playbook) ──────────────

def _marker(biz: Dict[str, Any]) -> Dict[str, Any]:
    return dict(((biz.get("settings") or {}).get("chief_playbook") or {}))


def _due(biz: Dict[str, Any]) -> bool:
    last = _marker(biz).get("last_run_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    return (_now() - last_dt) >= timedelta(days=CADENCE_DAYS)


def _mark_run(biz: Dict[str, Any], sources: int, fingerprint: str,
              skipped: Optional[str] = None) -> None:
    settings = dict(biz.get("settings") or {})
    settings["chief_playbook"] = {
        "last_run_at": _iso(_now()),
        "sources": sources,
        "fingerprint": fingerprint,
        **({"last_skip": skipped} if skipped else {}),
    }
    try:
        sb_clients.sb_patch_as_service(
            f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    except Exception as e:
        logger.warning(f"[playbook] mark_run failed for {biz.get('id')}: {e}")


def _fingerprint(memories: List[Dict], insights: List[Dict]) -> str:
    """Cheap signature of the source material. If it hasn't changed since
    the last distillation, there's nothing new to say — skip the LLM even
    when the cadence clock is due."""
    def _latest(rows: List[Dict]) -> str:
        stamps = [str(r.get("created_at") or "") for r in rows]
        return max(stamps) if stamps else ""
    return f"m{len(memories)}:{_latest(memories)}|i{len(insights)}:{_latest(insights)}"


# ─── Source gather ───────────────────────────────────────────────────

def _gather_sources(biz_id: str) -> Dict[str, List[Dict]]:
    memories = sb_clients.sb_get_as_service(
        f"/chief_memories?business_id=eq.{biz_id}&is_active=eq.true"
        f"&category=neq.insight&order=importance.desc,created_at.desc"
        f"&limit={MAX_MEMORIES}&select=category,content,importance,created_at") or []
    insights = sb_clients.sb_get_as_service(
        f"/chief_memories?business_id=eq.{biz_id}&is_active=eq.true"
        f"&category=eq.insight&order=created_at.desc"
        f"&limit={MAX_INSIGHTS}&select=content,created_at") or []
    return {"memories": memories, "insights": insights}


# ─── LLM synthesis ───────────────────────────────────────────────────

_SYSTEM = """You distill everything a small-business platform has learned about ONE business into a tight standing brief. This brief sits at the top of every conversation the business's AI chief of staff has — so write it TO the chief of staff, as background truth, not as a report to the owner.

Given the owner's durable facts + standing preferences (memories) and the platform's weekly longitudinal insights, write a compact playbook using ONLY these sections, and omit any section you have nothing real to say for:

WHO THIS IS — one or two sentences: what the business does, who it serves, the practitioner's working style.
WHAT WORKS — the proven plays, preferences, and voice worth repeating.
WHAT TO AVOID — boundaries, hard preferences, past misfires.
RIGHT NOW — the current priorities or live trends to act on.

Rules:
- Ground every line ONLY in the material you were given. Never invent facts, numbers, names, or preferences.
- Terse and specific — this is a briefing, not prose. No preamble, no sign-off, no markdown fences.
- Under {max_words} words total. If there is very little material, write only WHO THIS IS.
- Write plain text with the section labels in CAPS as shown."""


def _synthesize(biz: Dict[str, Any], sources: Dict[str, List[Dict]]) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return ""
    try:
        import feature_gates as _fg
        _plan = _fg.plan_of(biz) if isinstance(biz, dict) else None
    except Exception:
        _plan = None
    # Distillation is summarization → the cheap/fast `background` lane.
    model = chief_models.model_for("background", _plan)

    mem_lines = "\n".join(
        f"- [{m.get('category')}] {m.get('content')}"
        for m in sources["memories"]
    ) or "(none yet)"
    ins_lines = "\n".join(
        f"- {i.get('content')}" for i in sources["insights"]
    ) or "(none yet)"
    user_msg = (
        f"BUSINESS: {biz.get('name')} (type: {biz.get('type') or 'general'})\n\n"
        f"DURABLE FACTS + STANDING PREFERENCES:\n{mem_lines}\n\n"
        f"WEEKLY LONGITUDINAL INSIGHTS:\n{ins_lines}\n\n"
        f"Write the playbook now."
    )

    try:
        resp = llm_call.post({
            "model": model, "max_tokens": 700,
            "system": _SYSTEM.replace("{max_words}", str(MAX_WORDS)),
            "messages": [{"role": "user", "content": user_msg}],
        }, timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0), key=key)
    except httpx.HTTPError as e:
        logger.warning(f"[playbook] LLM call failed: {e}")
        log_api_usage_sync(endpoint="/chief/playbook", model=model,
                           input_tokens=0, output_tokens=0,
                           business_id=biz.get("id"), ok=False)
        return ""
    if resp.status_code >= 400:
        logger.warning(f"[playbook] LLM error {resp.status_code}: {resp.text[:200]}")
        log_api_usage_sync(endpoint="/chief/playbook", model=model,
                           input_tokens=0, output_tokens=0,
                           business_id=biz.get("id"), ok=False)
        return ""

    data = resp.json()
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    log_api_usage_sync(endpoint="/chief/playbook", model=data.get("model") or model,
                       input_tokens=int(usage.get("input_tokens") or 0),
                       output_tokens=int(usage.get("output_tokens") or 0),
                       business_id=biz.get("id"))
    text = "".join(
        b.get("text", "") for b in data.get("content", [])
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()
    return text[:2500]


# ─── Persistence ─────────────────────────────────────────────────────

def _upsert(biz_id: str, body: str, sources_count: int,
            fingerprint: str, model: str) -> bool:
    """One row per business (business_id is the PK) — upsert via
    merge-duplicates so a re-distillation replaces the prior brief."""
    row = {
        "business_id": biz_id,
        "body": body[:2500],
        "sources_count": sources_count,
        "fingerprint": fingerprint,
        "model": model,
        "generated_at": _iso(_now()),
    }
    try:
        res = sb_clients.sb_post_as_service(
            "/chief_playbooks", row,
            prefer="resolution=merge-duplicates,return=representation")
        return bool(res)
    except Exception as e:
        logger.warning(f"[playbook] upsert failed for {biz_id}: {e}")
        return False


# ─── Entry points ────────────────────────────────────────────────────

def regenerate(business_id: str, force: bool = False) -> Dict[str, Any]:
    """Re-distill one business's playbook. `force` bypasses the cadence
    clock (not the min-source gate). Cheap paths short-circuit before any
    LLM call. Best-effort — never raises."""
    if not _enabled():
        return {"ok": False, "skipped": "disabled"}
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,type,settings&limit=1") or []
    if not rows:
        return {"ok": False, "error": "business not found"}
    biz = rows[0]

    if not force and not _due(biz):
        return {"ok": True, "skipped": "not_due"}

    sources = _gather_sources(business_id)
    n_sources = len(sources["memories"]) + len(sources["insights"])
    fp = _fingerprint(sources["memories"], sources["insights"])

    if n_sources < MIN_SOURCES:
        _mark_run(biz, n_sources, fp, skipped="not_enough_material")
        return {"ok": True, "skipped": "not_enough_material", "sources": n_sources}

    # Nothing new since the last distillation → bump the clock, skip the LLM.
    if not force and _marker(biz).get("fingerprint") == fp:
        _mark_run(biz, n_sources, fp, skipped="unchanged")
        return {"ok": True, "skipped": "unchanged", "sources": n_sources}

    body = _synthesize(biz, sources)
    if not body:
        # LLM failure — do NOT mark, so the next tick retries.
        return {"ok": False, "error": "synthesis_failed"}

    model = chief_models.model_for("background")
    saved = _upsert(business_id, body, n_sources, fp, model)
    if saved:
        _mark_run(biz, n_sources, fp)
    return {"ok": saved, "sources": n_sources, "chars": len(body)}


def context_block(business_id: str) -> str:
    """A ready-to-prepend prompt block carrying this business's standing
    playbook, or '' when there isn't one yet. Fail-open."""
    if (os.environ.get("CHIEF_PLAYBOOK") or "on").strip().lower() == "off":
        return ""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/chief_playbooks?business_id=eq.{business_id}"
            f"&select=body&limit=1") or []
    except Exception:
        return ""
    body = (rows[0].get("body") if rows else "") or ""
    body = body.strip()
    if not body:
        return ""
    return (
        "STANDING PLAYBOOK (your distilled read on this business — the "
        "compounding picture across everything you've learned; treat it as "
        "background truth, but let the live data above override it if they "
        "ever conflict):\n" + body + "\n")


def tick(limit: int = MAX_PER_TICK) -> int:
    """Scheduler tick — distill playbooks for businesses whose cadence is
    due, capped at `limit`. Returns how many were (re)written. Kill switch
    CHIEF_PLAYBOOK=off. Best-effort."""
    if not _enabled():
        return 0
    rows = sb_clients.sb_get_as_service(
        "/businesses?select=id,name,type,settings&limit=500") or []
    due = [b for b in rows if _due(b)]
    written = 0
    for biz in due[:limit]:
        try:
            res = regenerate(biz["id"])
            if res.get("ok") and not res.get("skipped"):
                written += 1
                print(f"[Playbook tick] {biz.get('name') or biz['id']}: "
                      f"distilled ({res.get('sources')} sources)", flush=True)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[playbook] tick failed for {biz.get('id')}: {e}")
    if len(due) > limit:
        print(f"[Playbook tick] {len(due) - limit} business(es) deferred "
              f"to the next tick (cap {limit})", flush=True)
    return written
