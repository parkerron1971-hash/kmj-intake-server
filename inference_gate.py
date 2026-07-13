"""
inference_gate.py — Arc 20 Phase B Part 9 — the Layer-2 routing gate.

Sits between "Chief wants Claude" and the Anthropic call on the two
cacheable surfaces (chief_llm, ai_proxy allow-listed task_types).

Decision order (fail-open at EVERY step — the gate may only ever save
money, never block or degrade Chief):
  1. disabled / no embedding key / surface not cacheable  → claude
  2. exact prompt-hash hit (fresh)                        → cached
  3. cosine match >= threshold (fresh, business-scoped)   → cached
  4. otherwise                                            → claude, then store

The main Chief CONVERSATION is deliberately NOT cacheable in v1 — replies
are state-dependent and a stale answer about the practitioner's books is
the unforgivable failure mode. Composer/Director are excluded by design
(anti-convergence). See docs/inference_layer.md.

Metering note: cache hits still count as weighted Chief interactions —
the practitioner bought an answer, not an Anthropic invoice line. Savings
accrue to platform margin (the point of Layer 2).
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

import sb_clients

logger = logging.getLogger("inference_gate")

OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
EMBED_MODEL = "text-embedding-3-small"   # 1536 dims; ~$0.02/1M tokens

# ai_proxy task_types eligible for caching (classification-shaped work).
CACHEABLE_TASK_TYPES = set(
    (os.environ.get("INFERENCE_CACHEABLE_TASKS") or "score,briefing").split(","))


def _threshold() -> float:
    try:
        t = float(os.environ.get("INFERENCE_GATE_THRESHOLD") or 0.92)
        return max(0.85, min(0.99, t))   # 0.85 floor per the ruled scope
    except Exception:
        return 0.92


def _ttl_days() -> int:
    try:
        return max(1, int(os.environ.get("INFERENCE_CACHE_TTL_DAYS") or 30))
    except Exception:
        return 30


def gate_enabled() -> bool:
    if (os.environ.get("INFERENCE_GATE") or "on").lower() == "off":
        return False
    return bool(os.environ.get("OPENAI_API_KEY"))


def surface_cacheable(surface: str, task_type: Optional[str] = None) -> bool:
    if surface == "chief_llm":
        return True
    if surface == "ai_proxy":
        return bool(task_type and task_type in CACHEABLE_TASK_TYPES)
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").lower().split()).encode()).hexdigest()


def _embed(text: str) -> Optional[list]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        r = httpx.post(OPENAI_EMBED_URL, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        }, json={"model": EMBED_MODEL, "input": (text or "")[:8000]}, timeout=10.0)
        if r.status_code != 200:
            logger.warning(f"[gate] embed {r.status_code}: {r.text[:120]}")
            return None
        data = r.json()
        # Metering (beta-readiness audit): the gate's embedding call runs
        # on every cacheable Chief-bookkeeping lookup and was dark.
        try:
            from api_usage_logger import log_api_usage_sync
            toks = int((data.get("usage") or {}).get("prompt_tokens") or 0)
            log_api_usage_sync(endpoint="/gate/embed", model=EMBED_MODEL,
                               input_tokens=toks, output_tokens=0)
        except Exception:
            pass
        return data["data"][0]["embedding"]
    except Exception as e:
        logger.warning(f"[gate] embed failed: {e}")
        return None


def _log_decision(business_id: Optional[str], surface: str, task_type: Optional[str],
                  hit: bool, confidence: Optional[float], reason: Optional[str],
                  cents_saved: float = 0.0) -> None:
    try:
        sb_clients.sb_post_as_service("/inference_gate_decisions", {
            "business_id": business_id, "surface": surface, "task_type": task_type,
            "cache_hit": hit, "confidence": confidence,
            "fallback_reason": reason, "cents_saved": round(cents_saved, 4),
            "created_at": _now_iso(),
        }, prefer=None)
    except Exception:
        pass


def lookup(business_id: str, surface: str, request_text: str,
           task_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Try the cache. Returns {response, confidence, cached: True} or None
    (meaning: call Claude). NEVER raises."""
    try:
        if not gate_enabled() or not surface_cacheable(surface, task_type):
            _log_decision(business_id, surface, task_type, False, None, "disabled")
            return None
        h = _hash(request_text)
        exact = sb_clients.sb_get_as_service(
            f"/inference_cache?business_id=eq.{business_id}&surface=eq.{surface}"
            f"&prompt_hash=eq.{h}&select=id,response,model,input_tokens,output_tokens,"
            f"created_at&limit=1") or []
        if exact:
            row = exact[0]
            from datetime import timedelta as _td
            cutoff = (datetime.now(timezone.utc) - _td(days=_ttl_days())).isoformat()
            if (row.get("created_at") or "") >= cutoff:
                saved = _estimate_cents(row)
                _bump(row["id"], saved)
                _log_decision(business_id, surface, task_type, True, 1.0, None, saved)
                return {"response": row["response"], "confidence": 1.0, "cached": True}
            # stale exact entry: fall through to (and refresh via) the miss path
            _log_decision(business_id, surface, task_type, False, None, "stale")
        emb = _embed(request_text)
        if emb is None:
            _log_decision(business_id, surface, task_type, False, None, "embed_unavailable")
            return None
        rows = sb_clients.sb_post_as_service("/rpc/match_inference_cache", {
            "p_business_id": business_id, "p_surface": surface,
            "p_embedding": emb, "p_threshold": _threshold(),
            "p_max_age_days": _ttl_days(),
        }) or []
        if not isinstance(rows, list):
            rows = []
        # Guard against malformed RPC responses (and test fakes): a match
        # MUST carry a response + similarity.
        rows = [r for r in rows
                if isinstance(r, dict) and r.get("response")
                and r.get("similarity") is not None]
        if rows:
            row = rows[0]
            sim = float(row.get("similarity") or 0)
            saved = _estimate_cents(row)
            _bump(row["id"], saved)
            _log_decision(business_id, surface, task_type, True, sim, None, saved)
            return {"response": row["response"], "confidence": sim, "cached": True,
                    "_embedding": emb}
        _log_decision(business_id, surface, task_type, False, None, "miss")
        return {"_embedding": emb, "cached": False} if emb else None
    except Exception as e:
        logger.warning(f"[gate] lookup failed open: {e}")
        _log_decision(business_id, surface, task_type, False, None, "error")
        return None


def store(business_id: str, surface: str, request_text: str, response: str,
          model: str, input_tokens: int, output_tokens: int,
          task_type: Optional[str] = None,
          embedding: Optional[list] = None) -> None:
    """After Claude answers a miss, remember it. NEVER raises."""
    try:
        if not gate_enabled() or not surface_cacheable(surface, task_type) \
                or not (response or "").strip():
            return
        emb = embedding if embedding is not None else _embed(request_text)
        # UPSERT (Finding 3): a post-TTL miss must OVERWRITE the stale row —
        # plain insert hit the (business_id,surface,prompt_hash) unique index
        # and the stale entry never refreshed. Resolution: fresh content +
        # fresh created_at + hit_count reset to 0 (the stale answer's hits
        # don't vouch for the new one). Concurrent same-prompt misses both
        # upsert; last write wins — both wrote the same fresh answer, so the
        # race is benign.
        sb_clients.sb_post_as_service(
            "/inference_cache?on_conflict=business_id,surface,prompt_hash", {
                "business_id": business_id, "surface": surface, "task_type": task_type,
                "prompt_hash": _hash(request_text),
                "embedding": emb,
                "request_preview": (request_text or "")[:300],
                "response": response, "model": model,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "hit_count": 0,
                "cost_cents_saved": 0,
                "last_hit_at": None,
                "created_at": _now_iso(),
            }, prefer="resolution=merge-duplicates")
    except Exception as e:
        logger.warning(f"[gate] store failed soft: {e}")


def _estimate_cents(row: Dict[str, Any]) -> float:
    try:
        from api_usage_logger import _compute_cost_cents
        return _compute_cost_cents(row.get("model") or "claude-sonnet-4",
                                   int(row.get("input_tokens") or 0),
                                   int(row.get("output_tokens") or 0))
    except Exception:
        return 0.0


def _bump(cache_id: str, saved: float) -> None:
    try:
        rows = sb_clients.sb_get_as_service(
            f"/inference_cache?id=eq.{cache_id}&select=hit_count,cost_cents_saved&limit=1") or []
        cur = rows[0] if rows else {}
        sb_clients.sb_patch_as_service(f"/inference_cache?id=eq.{cache_id}", {
            "hit_count": int(cur.get("hit_count") or 0) + 1,
            "cost_cents_saved": round(float(cur.get("cost_cents_saved") or 0) + saved, 4),
            "last_hit_at": _now_iso(),
        })
    except Exception:
        pass


def stats() -> Dict[str, Any]:
    """Platform-owner telemetry aggregate."""
    decisions = sb_clients.sb_get_as_service(
        "/inference_gate_decisions?order=created_at.desc"
        "&select=surface,task_type,cache_hit,cents_saved&limit=5000") or []
    total = len(decisions)
    hits = sum(1 for d in decisions if d.get("cache_hit"))
    saved = round(sum(float(d.get("cents_saved") or 0) for d in decisions), 2)
    by_surface: Dict[str, Dict[str, int]] = {}
    for d in decisions:
        s = by_surface.setdefault(d.get("surface") or "?", {"calls": 0, "hits": 0})
        s["calls"] += 1
        s["hits"] += 1 if d.get("cache_hit") else 0
    top = sb_clients.sb_get_as_service(
        "/inference_cache?order=hit_count.desc&limit=10"
        "&select=surface,request_preview,hit_count,cost_cents_saved") or []
    size = sb_clients.sb_get_as_service(
        "/inference_cache?select=id&limit=10000") or []
    return {
        "ok": True,
        "gate_enabled": gate_enabled(),
        "threshold": _threshold(),
        "decisions_sampled": total,
        "cache_hit_rate": round(hits / total, 3) if total else None,
        "estimated_cents_saved": saved,
        "cache_entries": len(size),
        "by_surface": by_surface,
        "top_cached": top,
    }
