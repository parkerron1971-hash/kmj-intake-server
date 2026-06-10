"""
period_overrides_router.py — Phase I.3 PR2.

Owner-gated. Powers the frontend soft-lock for client-edited surfaces
(invoices, business_expenses): check whether a date is locked, record an
override before the edit, and list the audit trail.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
import period_lock

logger = logging.getLogger("period_overrides_router")

router = APIRouter(prefix="/period-overrides", tags=["period_overrides"])

_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _period_label(p: Dict[str, Any]) -> str:
    try:
        y, m, _ = (int(x) for x in (p.get("period_start") or "").split("-"))
    except Exception:
        return p.get("period_type", "period")
    if p.get("period_type") == "month":
        return f"{_MONTHS[m]} {y}"
    if p.get("period_type") == "quarter":
        return f"Q{(m - 1) // 3 + 1} {y}"
    return f"{y}"


@router.get("/check")
def check(biz: str, date: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Is `date` (yyyy-mm-dd) in a closed period? Frontend calls this before a
    client-side edit."""
    _owner(biz, user)
    p = period_lock.locked_period(biz, date)
    if not p:
        return {"ok": True, "locked": False}
    return {"ok": True, "locked": True, "period_id": p.get("id"),
            "period_label": _period_label(p)}


class RecordBody(BaseModel):
    business_id: str
    source_type: str
    source_id: str
    date: str
    reason: str
    pre_snapshot: Optional[Any] = None
    post_snapshot: Optional[Any] = None


@router.post("")
def record(body: RecordBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Record an override before a client-side edit to a closed-period row."""
    _owner(body.business_id, user)
    if not (body.reason or "").strip():
        raise HTTPException(400, "a reason is required")
    p = period_lock.locked_period(body.business_id, body.date)
    period_lock.record_override(
        body.business_id, p, source_type=body.source_type, source_id=body.source_id,
        reason=body.reason.strip(), override_by=str(user.id), role="owner",
        pre=body.pre_snapshot, post=body.post_snapshot)
    return {"ok": True}


@router.get("")
def list_overrides(biz: str, period_id: Optional[str] = None,
                   source_type: Optional[str] = None,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Audit trail (read-only), filterable by period / source type."""
    _owner(biz, user)
    parts = [f"business_id=eq.{biz}"]
    if period_id:
        parts.append(f"accounting_period_id=eq.{period_id}")
    if source_type:
        parts.append(f"source_type=eq.{source_type}")
    parts.append("order=override_at.desc&limit=200&select=*")
    rows = sb_clients.sb_get_as_service(f"/period_edit_overrides?{'&'.join(parts)}") or []
    return {"ok": True, "overrides": rows}
