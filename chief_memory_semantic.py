"""
chief_memory_semantic.py — semantic retrieval for Chief's memory.

Compounding API-free intelligence (2026-07-13). Memories get an
embedding computed ONCE at write time; retrieval is then pure DB math
via the business-scoped `match_chief_memories` RPC — free, instant, and
resilient to an AI-provider outage.

Everything here FAILS OPEN: no OpenAI key, no embedding column yet, RPC
missing → return None / skip, and the caller falls back to the existing
importance/recency blend. This is strictly additive to memory recall.

Depends on: supabase/APPLY-2026-07-13-chief-memory-embeddings.sql
(embedding column + ivfflat index + match_chief_memories RPC).
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

import sb_clients

logger = logging.getLogger("chief_memory_semantic")


def _enabled() -> bool:
    # Reuses the inference gate's embedding client; off without an OpenAI
    # key or when explicitly disabled.
    if (os.environ.get("CHIEF_SEMANTIC_MEMORY") or "on").strip().lower() == "off":
        return False
    return bool(os.environ.get("OPENAI_API_KEY"))


def embed(text: str) -> Optional[List[float]]:
    """Embed one string (OpenAI text-embedding-3-small, 1536 dims).
    Reuses inference_gate's client. None on any failure."""
    if not _enabled() or not (text or "").strip():
        return None
    try:
        from inference_gate import _embed
        return _embed(text)
    except Exception as e:
        logger.warning(f"[semantic] embed failed: {e}")
        return None


def _vec_literal(embedding: List[float]) -> str:
    """pgvector wants a '[0.1,0.2,...]' string literal via PostgREST."""
    return "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"


def store_embedding(memory_id: str, text: str) -> bool:
    """Compute + persist the embedding for a memory row. Best-effort."""
    emb = embed(text)
    if not emb or not memory_id:
        return False
    try:
        sb_clients.sb_patch_as_service(
            f"/chief_memories?id=eq.{memory_id}",
            {"embedding": _vec_literal(emb)})
        return True
    except Exception as e:
        logger.warning(f"[semantic] store_embedding failed: {e}")
        return False


def match(business_id: str, query_text: str,
          threshold: float = 0.30, limit: int = 12) -> List[Dict[str, Any]]:
    """Top semantically-similar active memories for this business.
    Returns [] on any failure (caller keeps its importance/recency blend).
    Rows: {id, content, category, importance, similarity}."""
    if not business_id:
        return []
    emb = embed(query_text)
    if not emb:
        return []
    try:
        url = f"{sb_clients.sb_url()}/rest/v1/rpc/match_chief_memories"
        headers = sb_clients.sb_headers_service()
        r = httpx.post(url, headers=headers, json={
            "p_business_id": business_id,
            "p_embedding": _vec_literal(emb),
            "p_threshold": threshold,
            "p_limit": limit,
        }, timeout=8.0)
        if r.status_code >= 400:
            # RPC/migration not applied yet, or transient — fail open.
            logger.info(f"[semantic] match rpc {r.status_code}: {r.text[:120]}")
            return []
        return r.json() or []
    except Exception as e:
        logger.warning(f"[semantic] match failed: {e}")
        return []


def backfill_tick(limit: int = 100) -> int:
    """Embed a batch of memories that have no embedding yet (frontend
    writers + rows created before this shipped). Returns count embedded.
    Meant to be called from the existing scheduler; safe to run often."""
    if not _enabled():
        return 0
    try:
        rows = sb_clients.sb_get_as_service(
            f"/chief_memories?embedding=is.null&is_active=eq.true"
            f"&select=id,content&limit={limit}") or []
    except Exception as e:
        logger.warning(f"[semantic] backfill fetch failed: {e}")
        return 0
    done = 0
    for row in rows:
        if store_embedding(row.get("id"), row.get("content") or ""):
            done += 1
    if done:
        logger.info(f"[semantic] backfilled {done} memory embeddings")
    return done
