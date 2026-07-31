"""
accounting_periods_router.py — Phase I.3 (PR1) — period closing.

Owner-gated. Monthly/quarterly close = status flip + audit; annual close also
posts a closing journal entry (gl_engine). Reopen reverses it. Soft-lock
overrides + accountant collaborators land in the next I.3 PRs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date as _date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
import billing_limits
import gl_engine

logger = logging.getLogger("accounting_periods_router")

router = APIRouter(prefix="/accounting-periods", tags=["accounting_periods"])

_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _access(biz: str, user: AuthedUser, min_role: str = "viewer") -> Dict[str, Any]:
    """Seat-access arc (7/31): periods are readable by any active seat or
    accountant collaborator; generate/close/reopen escalate to manager."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    if min_role == "viewer":
        from business_collaborators_router import is_active_accountant
        if is_active_accountant(biz, str(user.id)):
            return row
    from business_users_router import require_role
    require_role(biz, str(user.id), min_role)
    return row


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    return _access(biz, user, "viewer")


def _owner_for_period(period_id: str, user: AuthedUser,
                      min_role: str = "viewer") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/accounting_periods?id=eq.{period_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "period not found")
    biz = _access(str(rows[0]["business_id"]), user, min_role)
    return {"period": rows[0], "biz": biz}


def _label(p: Dict[str, Any]) -> str:
    start = (p.get("period_start") or "")
    try:
        y, m, _ = (int(x) for x in start.split("-"))
    except Exception:
        return p.get("period_type", "Period")
    if p["period_type"] == "month":
        return f"{_MONTHS[m]} {y}"
    if p["period_type"] == "quarter":
        return f"Q{(m - 1) // 3 + 1} {y}"
    return f"{y}"


def _closed_by_label(p: Dict[str, Any], biz: Dict[str, Any]) -> str:
    if p.get("closed_via") == "owner":
        return (biz.get("settings") or {}).get("practitioner_name") or "Owner"
    if p.get("closed_via") == "chief_auto_close":
        return "Chief (auto)"
    return p.get("closed_via") or "—"


def _enrich(p: Dict[str, Any], biz: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(p)
    out["label"] = _label(p)
    out["closed_by_label"] = _closed_by_label(p, biz)
    return out


@router.get("")
def list_periods(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner(biz, user)
    # Auto-generate the current calendar year's periods on first view.
    year = datetime.now(timezone.utc).year
    existing = sb_clients.sb_get_as_service(
        f"/accounting_periods?business_id=eq.{biz}&period_start=gte.{year}-01-01"
        f"&select=id&limit=1") or []
    if not existing:
        gl_engine.generate_periods(biz, year)
    rows = sb_clients.sb_get_as_service(
        f"/accounting_periods?business_id=eq.{biz}"
        f"&order=period_start.desc,period_type.asc&select=*&limit=500") or []
    return {"ok": True, "periods": [_enrich(r, biz_row) for r in rows]}


@router.get("/{period_id}")
def get_period(period_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    ctx = _owner_for_period(period_id, user)
    p = ctx["period"]
    counts = gl_engine.period_counts(str(p["business_id"]), p["period_start"], p["period_end"])
    return {"ok": True, "period": _enrich(p, ctx["biz"]), "counts": counts}


class GenerateBody(BaseModel):
    business_id: str
    year: Optional[int] = None


@router.post("/generate")
def generate(biz: str, year: Optional[int] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _access(biz, user, "manager")
    billing_limits.require_feature(biz, "period_close")
    y = year or datetime.now(timezone.utc).year
    return gl_engine.generate_periods(biz, y)


@router.post("/{period_id}/close")
def close(period_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    ctx = _owner_for_period(period_id, user, min_role="manager")
    biz_id = str(ctx["period"]["business_id"])
    billing_limits.require_feature(biz_id, "period_close")
    try:
        # Category D — two-signature close: when enabled, the initiator's
        # close becomes a pending proposal the OTHER party (accountant ↔
        # owner) must approve. Sequential signoffs; both ids end up on the
        # proposal row (audit).
        settings = (ctx.get("biz") or {}).get("settings") or {}
        if settings.get("period_close_two_signature"):
            import chief_bookkeeping
            pend = [p for p in chief_bookkeeping.list_proposals(biz_id, "pending")
                    if p.get("proposal_type") == "propose_period_close"
                    and (p.get("proposed") or {}).get("period_id") == period_id]
            if pend:
                return {"ok": True, "pending_second_signature": True,
                        "proposal": pend[0],
                        "note": "Awaiting the second signature on the existing request."}
            row = chief_bookkeeping._insert_proposal(
                biz_id, "propose_period_close",
                proposed={"period_id": period_id,
                          "initiated_by": str(user.id), "initiated_role": "owner",
                          "requires_second_signature": True},
                confidence=1.0,
                reasoning=("Two-signature close: the owner requested this period "
                           "be closed — your approval is the second signature."))
            return {"ok": True, "pending_second_signature": True, "proposal": row,
                    "note": "Close requested — your accountant's approval is the "
                            "second signature."}
        return gl_engine.close_period(biz_id, period_id,
                                      closed_by=str(user.id), closed_via="owner")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[periods] close failed: {e}")
        raise HTTPException(500, f"close failed: {e}")


class ReopenBody(BaseModel):
    reason: str


@router.post("/{period_id}/reopen")
def reopen(period_id: str, body: ReopenBody,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    if not (body.reason or "").strip():
        raise HTTPException(400, "a reason is required to reopen a closed period")
    ctx = _owner_for_period(period_id, user, min_role="manager")
    billing_limits.require_feature(str(ctx["period"]["business_id"]), "period_close")
    try:
        return gl_engine.reopen_period(str(ctx["period"]["business_id"]), period_id,
                                       reopened_by=str(user.id), reason=body.reason.strip())
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[periods] reopen failed: {e}")
        raise HTTPException(500, f"reopen failed: {e}")
