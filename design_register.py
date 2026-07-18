# design_register.py
# ─────────────────────────────────────────────────────────────────────
# Phase 2, §3-J item 3 (Kevin's spec): THE EXCEPTION REGISTER.
# Every "I wanted X but the spec can't express it" from any creative
# stage is persisted, and the aggregate — ranked by frequency — IS the
# vocabulary roadmap ("where is the decision-space too narrow",
# automated). Phase 3 surface priority reads this.
#
# Storage: rows in the existing `events` table (event_type
# 'design_exception') — no migration needed. Also an in-memory
# per-build audit stash (invention counts) the build loop reads for
# invention verification.
# ─────────────────────────────────────────────────────────────────────

import logging
import time
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger("design_register")

# In-memory per-build audit stash: {business_id: {"inventions": int,
# "texts": list, "ts": float}} — texts ride along (A4, 2026-07-18) so the
# verification pass can check RESTATEMENT, not just count.
_AUDIT: Dict[str, Dict[str, Any]] = {}


def record_exception(business_id: str, stage: str, wanted: str,
                     blocked_by: str = "") -> None:
    """Persist one exception-register entry. Fire-and-forget."""
    wanted = " ".join(str(wanted).split())[:300]
    if not wanted or wanted.lower() in ("none", "none.", '"none"'):
        return
    try:
        import sb_clients
        sb_clients.sb_post_as_service("/events", {
            "business_id": business_id,
            "event_type": "design_exception",
            "data": {"stage": stage, "wanted": wanted,
                     "blocked_by": blocked_by[:200],
                     "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "source": "design_register",
        })
    except Exception as e:
        logger.info(f"[register] persist skipped ({type(e).__name__}): {e}")


def note_inventions(business_id: str, count: int,
                    texts: Optional[List[Any]] = None) -> None:
    """Stash the DRO invention count (+ the invention records themselves,
    when the authoring stage hands them over) for the build loop's
    verification."""
    _AUDIT[str(business_id)] = {
        "inventions": int(count),
        "texts": [t for t in (texts or []) if t][:6],
        "ts": time.time(),
    }


def get_invention_count(business_id: str) -> Optional[int]:
    entry = _AUDIT.get(str(business_id))
    if not entry or time.time() - entry.get("ts", 0) > 3600:
        return None
    return entry.get("inventions")


def get_invention_texts(business_id: str) -> Optional[List[Any]]:
    """The invention records (dicts with addition/builds_on/where, or raw
    strings) stashed by the DRO pass. None when unknown/expired — callers
    treat that as 'unverifiable', never as failure."""
    entry = _AUDIT.get(str(business_id))
    if not entry or time.time() - entry.get("ts", 0) > 3600:
        return None
    return entry.get("texts") or []


def aggregate(limit_rows: int = 500) -> List[Dict[str, Any]]:
    """The vocabulary roadmap: recent exceptions ranked by frequency."""
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            "/events?event_type=eq.design_exception"
            f"&order=created_at.desc&limit={int(limit_rows)}"
            "&select=business_id,data,created_at") or []
    except Exception as e:
        logger.warning(f"[register] aggregate read failed: {e}")
        return []
    counts: Counter = Counter()
    latest: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = r.get("data") or {}
        wanted = str(d.get("wanted") or "").strip()
        if not wanted:
            continue
        key = wanted.lower()
        counts[key] += 1
        if key not in latest:
            latest[key] = {"wanted": wanted, "stage": d.get("stage") or "",
                           "last_seen": r.get("created_at") or ""}
    out = []
    for key, n in counts.most_common(50):
        item = dict(latest[key])
        item["count"] = n
        out.append(item)
    return out
