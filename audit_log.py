"""
audit_log.py — Rails Arc 4 — the unified audit log.

One append-only table answering "who did what, when — and did it
work". Unlike chief_activity (a recap feed that skips failures by
design), the audit log records EVERYTHING executed: successes,
failures, even navigation — because "Chief tried X and it failed" is
exactly what a practitioner reviewing their business needs to see, and
exactly what protects the platform when a number is disputed.

Writers call record() (best-effort, never raises). v1 wires the Chief
chat loop; scheduler/rules/agent writers adopt the same helper
opportunistically — one function, one table, no bespoke shapes.

Reads go through GET /audit (member+ via the seat ladder — history is
a trust surface for the whole team, not an owner secret). The table is
service-role insert only with no update/delete policies: an audit row
that can be edited is a diary, not an audit.

ACTOR NAMES: the table's actor_type CHECK allows only
('user','chief','agent','system'). Non-chat writers (the scheduler,
the trusted-autonomy sweep) therefore write actor_type='system' and
carry their real identity in actor_id ('scheduler', 'trust-track') —
the frontend renders actor_id as the display name when present.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("audit_log")

router = APIRouter(prefix="/audit", tags=["audit"])

_RESULT_CAP = 2000  # jsonb result snippet cap (chars of serialized form)


def _cap_json(value: Any) -> Dict[str, Any]:
    """Coerce any handler result into a small jsonb-safe dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        try:
            s = json.dumps(value, default=str)
            if len(s) <= _RESULT_CAP:
                return value
            return {"truncated": s[:_RESULT_CAP]}
        except Exception:
            return {"repr": repr(value)[:_RESULT_CAP]}
    return {"text": str(value)[:_RESULT_CAP]}


def record(business_id: Optional[str], *, actor_type: str, verb: str,
           actor_id: Optional[str] = None, ok: bool = True,
           error: Optional[str] = None, summary: Optional[str] = None,
           payload: Optional[Dict[str, Any]] = None,
           result: Any = None,
           target_type: Optional[str] = None, target_id: Optional[str] = None,
           source: Optional[str] = None) -> bool:
    """Append one audit row. Best-effort: never raises into the caller."""
    if not business_id or not verb:
        return False
    row = {
        "business_id": business_id,
        "actor_type": actor_type if actor_type in ("user", "chief", "agent", "system") else "system",
        "actor_id": str(actor_id) if actor_id else None,
        "verb": str(verb)[:80],
        "target_type": target_type,
        "target_id": str(target_id)[:80] if target_id else None,
        "ok": bool(ok),
        "error": (str(error)[:500] if error else None),
        "summary": (str(summary)[:240] if summary else None),
        "payload": _cap_json(payload),
        "result": _cap_json(result),
        "source": source,
    }
    try:
        sb_clients.sb_post_as_service("/audit_log", row, prefer=None)
        return True
    except Exception as e:
        logger.warning(f"[audit] record({verb}) failed: {e}")
        return False


def record_chief_turn(*, user_id: Optional[str], business_id: Optional[str],
                      source: Optional[str], taken: List[Dict[str, Any]],
                      action_failed) -> int:
    """Audit every action a Chief chat turn executed — including
    failures and navigation (the two things chief_activity skips).
    `action_failed` is chief_of_staff's own failure predicate, passed
    in to keep one source of truth for what 'failed' means."""
    if not business_id or not taken:
        return 0
    n = 0
    for t in taken:
        if not isinstance(t, dict):
            continue
        verb = t.get("type") or "unknown"
        failed = bool(action_failed(t))
        wrote = record(
            business_id,
            actor_type="chief",
            actor_id=user_id,
            verb=verb,
            ok=not failed,
            error=(str(t.get("error") or t.get("result"))[:500] if failed else None),
            summary=t.get("label") or verb,
            payload={k: t.get(k) for k in ("label", "nav") if t.get(k)},
            result=t.get("result"),
            source=source if source in ("mobile", "desktop", "voice", "system") else "desktop",
        )
        n += 1 if wrote else 0
    return n


@router.get("")
def read_audit(biz: str, limit: int = 100, failed_only: bool = False,
               verb: Optional[str] = None,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The team's view of the business audit trail.

    Seat visibility (S11): owner-only reads left invited seats staring
    at an empty History panel. Same require_role ladder as the other
    routers — any working seat (member+) can read; roles are enforced
    server-side here regardless of what the client renders."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz, str(user.id), "member")

    limit = min(max(limit, 1), 500)
    q = (f"/audit_log?business_id=eq.{biz}"
         f"&select=id,actor_type,actor_id,verb,ok,error,summary,source,created_at,target_type,target_id"
         f"&order=created_at.desc&limit={limit}")
    if failed_only:
        q += "&ok=eq.false"
    if verb:
        safe = "".join(ch for ch in verb if ch.isalnum() or ch == "_")[:80]
        q += f"&verb=eq.{safe}"
    entries = sb_clients.sb_get_as_service(q) or []
    return {"ok": True, "entries": entries, "count": len(entries)}
