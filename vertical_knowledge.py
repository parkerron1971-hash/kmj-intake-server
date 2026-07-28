"""
vertical_knowledge.py — the store behind Feed 1 and Feed 2.

LAYER_TWO_ARCHITECTURE.md §6 names three feeds of vertical intelligence.
This module owns the two that need storage:

  Feed 1  seeded per-vertical knowledge. It already existed, as Python
          literals in vertical_intelligence.py — which meant it could only
          grow by editing a file and shipping a deploy. `seed_tick()`
          copies it into rows so it can grow without one.
  Feed 2  what real usage teaches, pooled across every business in a
          vertical. Written by vertical_distill.py, read from here.

The Python profiles stay the source of truth for seeds. This is a
projection of them, not a replacement — nothing regresses if the table is
empty, because callers fall back to the profiles they already used.

WHAT MAY LIVE HERE
  Patterns. Never a business name, a customer, an amount, a date, or a
  quoted message. The k-anonymity floor lives in the distiller (a learned
  row needs several distinct businesses behind it), and the table has no
  business_id column at all, so a row cannot be traced back to a tenant.

FAILS OPEN, EVERYWHERE
  No embedding key, no table yet, RPC missing, Supabase down — every
  function here returns empty or False and the caller behaves exactly as
  it did before this module existed. Vertical context has worked without
  it for a year; it must keep working the moment anything breaks.

Depends on: supabase/APPLY-2026-07-27-vertical-knowledge.sql
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

import sb_clients
import chief_memory_semantic  # reuses the embedding client + vector literal

logger = logging.getLogger("vertical_knowledge")

# Kinds carried today. Free-form by design — the CHECK is on `source`, not
# here, because a new kind should not need a migration.
KIND_VOICE = "voice"
KIND_REMINDER = "reminder"
KIND_OFFERING = "offering"
KIND_PATTERN = "pattern"      # what Feed 2 writes

SOURCE_SEED = "seed"
SOURCE_LEARNED = "learned"
SOURCE_CURATED = "curated"


def _enabled() -> bool:
    """Kill switch. `VERTICAL_KNOWLEDGE=off` makes every read return empty
    and every write a no-op, without a deploy."""
    return (os.environ.get("VERTICAL_KNOWLEDGE") or "on").strip().lower() != "off"


# ─── writes ──────────────────────────────────────────────────────────

def upsert(vertical: str, kind: str, content: str, *,
           source: str = SOURCE_SEED,
           confidence: float = 0.5,
           evidence_count: int = 0,
           curated_by: Optional[str] = None) -> bool:
    """Write one row, embedding it as we go. Idempotent on
    (vertical, kind, content) — the unique index means re-running the seed
    loader or the distiller reinforces instead of duplicating.

    Returns True only on a confirmed write, so callers can count honestly."""
    if not _enabled():
        return False
    vertical = (vertical or "").strip().lower()
    content = (content or "").strip()
    if not vertical or not content:
        return False

    row: Dict[str, Any] = {
        "vertical": vertical,
        "kind": kind,
        "content": content,
        "source": source,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "evidence_count": int(evidence_count),
    }
    if curated_by:
        row["curated_by"] = curated_by

    emb = chief_memory_semantic.embed(content)
    if emb:
        row["embedding"] = chief_memory_semantic._vec_literal(emb)

    try:
        sb_clients.sb_post_as_service(
            "/vertical_knowledge", row,
            prefer="resolution=merge-duplicates,return=minimal")
        return True
    except Exception as e:
        logger.warning(f"[vk] upsert failed ({vertical}/{kind}): {e}")
        return False


def deactivate(row_id: str) -> bool:
    """Retire a row without deleting it — a bad learned pattern should stop
    being retrieved but stay visible to whoever audits how it got there."""
    if not _enabled():
        return False
    try:
        sb_clients.sb_patch_as_service(
            f"/vertical_knowledge?id=eq.{row_id}", {"is_active": False})
        return True
    except Exception as e:
        logger.warning(f"[vk] deactivate failed: {e}")
        return False


# ─── reads ───────────────────────────────────────────────────────────

def match(vertical: str, query_text: str, *,
          threshold: float = 0.30, limit: int = 6) -> List[Dict[str, Any]]:
    """The knowledge most relevant to what is happening right now, for this
    vertical. Empty list on any failure."""
    if not _enabled():
        return []
    vertical = (vertical or "").strip().lower()
    if not vertical or not (query_text or "").strip():
        return []
    emb = chief_memory_semantic.embed(query_text)
    if not emb:
        return []
    try:
        r = httpx.post(
            f"{sb_clients.sb_url()}/rest/v1/rpc/match_vertical_knowledge",
            headers=sb_clients.sb_headers_service(),
            json={
                "p_vertical": vertical,
                "p_embedding": chief_memory_semantic._vec_literal(emb),
                "p_threshold": threshold,
                "p_limit": limit,
            }, timeout=8.0)
        if r.status_code >= 400:
            # Migration not applied yet, or transient — fail open, exactly
            # as semantic memory does.
            logger.info(f"[vk] match rpc {r.status_code}: {r.text[:120]}")
            return []
        return r.json() or []
    except Exception as e:
        logger.warning(f"[vk] match failed ({vertical}): {e}")
        return []


def list_for_vertical(vertical: str, *, source: Optional[str] = None,
                      limit: int = 200) -> List[Dict[str, Any]]:
    """Everything known about a vertical. For the seed loader's dedupe, and
    for anyone auditing what Feed 2 has decided."""
    if not _enabled():
        return []
    q = (f"/vertical_knowledge?vertical=eq.{(vertical or '').strip().lower()}"
         f"&is_active=eq.true&limit={limit}"
         f"&select=id,kind,content,source,confidence,evidence_count,created_at")
    if source:
        q += f"&source=eq.{source}"
    try:
        return sb_clients.sb_get_as_service(q) or []
    except Exception as e:
        logger.warning(f"[vk] list failed: {e}")
        return []


# ─── Feed 1: project the Python profiles into rows ───────────────────

def _seed_rows_for(vertical: str) -> List[Dict[str, str]]:
    """The seedable knowledge already sitting in vertical_intelligence, as
    rows. Deliberately a projection: the Python profile stays the source of
    truth, so a bad seed run can be fixed by re-running rather than by
    reconstructing anything."""
    import vertical_intelligence as vi
    import vertical_context

    out: List[Dict[str, str]] = []
    voice = vi.get_voice(vertical) or {}
    for hallmark in (voice.get("hallmarks") or [])[:8]:
        out.append({"kind": KIND_VOICE,
                    "content": f"Voice hallmark: {hallmark}"})
    for taboo in (voice.get("taboo") or [])[:6]:
        out.append({"kind": KIND_VOICE,
                    "content": f"Avoid in this vertical: {taboo}"})

    for reminder in (vertical_context._vertical_specific_reminders(
            vertical, vi.get_profile(vertical)) or []):
        out.append({"kind": KIND_REMINDER, "content": reminder})

    for off in (vi.get_offering_suggestions(vertical) or [])[:8]:
        name = off.get("name")
        if name:
            out.append({"kind": KIND_OFFERING,
                        "content": f"Typical offering: {name}"})
    return out


def seed_tick(verticals: Optional[List[str]] = None) -> Dict[str, int]:
    """Project Feed 1 into the table. Safe to run repeatedly — the unique
    index makes it converge rather than accumulate.

    Not scheduled: seeds change only when someone edits the Python, so this
    runs on demand (a deploy hook, or by hand after editing a profile)."""
    if not _enabled():
        return {"written": 0, "verticals": 0}
    import vertical_registry as reg

    keys = verticals or list(reg.canonical_keys())
    written = 0
    for vertical in keys:
        for row in _seed_rows_for(vertical):
            if upsert(vertical, row["kind"], row["content"],
                      source=SOURCE_SEED, confidence=0.9):
                written += 1
    logger.info(f"[vk] seed_tick wrote/refreshed {written} rows "
                f"across {len(keys)} verticals")
    return {"written": written, "verticals": len(keys)}
