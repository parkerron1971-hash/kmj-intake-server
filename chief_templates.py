"""
chief_templates.py — draft→template residue.

When a Chief-drafted message is good enough to actually SEND, keep it as
a reusable template keyed to the SITUATION (embedded). The next similar
situation reuses that message's voice + shape as an exemplar instead of
generating from scratch — cheaper, and the practitioner's proven voice
stays consistent.

Everything FAILS OPEN: no OpenAI key, no table/RPC yet → None / no-op,
and the draft path behaves exactly as before. Strictly additive.

Depends on: supabase/APPLY-2026-07-13-chief-templates.sql
(chief_templates table + match_chief_templates RPC). Reuses the
semantic-memory embedding client.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

import sb_clients

logger = logging.getLogger("chief_templates")

# A near-identical situation reinforces the existing template instead of
# creating a duplicate.
_DEDUP_SIMILARITY = 0.92


def _enabled() -> bool:
    if (os.environ.get("CHIEF_TEMPLATES") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("OPENAI_API_KEY"))


def _embed(text: str):
    try:
        import chief_memory_semantic
        return chief_memory_semantic.embed(text)
    except Exception:
        return None


def best_template(business_id: str, kind: str, situation: str,
                  threshold: float = 0.35) -> Optional[dict]:
    """The most situation-similar past template for (business, kind), or
    None. Returns {id, body, situation, uses, similarity}."""
    if not _enabled() or not business_id or not (situation or "").strip():
        return None
    emb = _embed(situation)
    if not emb:
        return None
    try:
        from chief_memory_semantic import _vec_literal
        r = httpx.post(
            f"{sb_clients.sb_url()}/rest/v1/rpc/match_chief_templates",
            headers=sb_clients.sb_headers_service(),
            json={"p_business_id": business_id, "p_kind": kind,
                  "p_embedding": _vec_literal(emb),
                  "p_threshold": threshold, "p_limit": 1},
            timeout=8.0)
        if r.status_code >= 400:
            logger.info(f"[templates] match rpc {r.status_code}: {r.text[:120]}")
            return None
        rows = r.json() or []
        return rows[0] if rows else None
    except Exception as e:
        logger.warning(f"[templates] best_template failed: {e}")
        return None


def exemplar_block(business_id: str, kind: str, situation: str) -> str:
    """A ready-to-prepend system-prompt block carrying the best past
    message for this situation, or '' when there isn't a good one. Adding
    this to a draft prompt keeps the practitioner's proven voice."""
    t = best_template(business_id, kind, situation)
    if not t:
        return ""
    return (
        "\n\nA past message YOU wrote for a similar situation landed well "
        "with this practitioner's clients — match its voice, warmth, and "
        "length (do NOT copy it verbatim; adapt to the specific person "
        "and reason):\n\"\"\"\n" + (t.get("body") or "").strip()[:800] + "\n\"\"\"\n")


def save_from_sent(business_id: str, kind: str, situation: str, body: str) -> None:
    """Record a SENT message as a template. If a near-identical situation
    already has one, reinforce it (uses += 1) instead of duplicating.
    Best-effort; never raises."""
    if not _enabled() or not business_id or not (body or "").strip() or not (situation or "").strip():
        return
    try:
        existing = best_template(business_id, kind, situation, threshold=_DEDUP_SIMILARITY)
        if existing:
            sb_clients.sb_patch_as_service(
                f"/chief_templates?id=eq.{existing['id']}",
                {"uses": int(existing.get("uses") or 1) + 1,
                 "last_used_at": datetime.now(timezone.utc).isoformat()})
            return
        emb = _embed(situation)
        if not emb:
            return
        from chief_memory_semantic import _vec_literal
        sb_clients.sb_post_as_service("/chief_templates", {
            "business_id": business_id,
            "kind": kind,
            "situation": (situation or "")[:500],
            "situation_embedding": _vec_literal(emb),
            "body": (body or "")[:2000],
        })
        logger.info(f"[templates] saved {kind} template for {business_id}")
    except Exception as e:
        logger.warning(f"[templates] save_from_sent failed: {e}")
