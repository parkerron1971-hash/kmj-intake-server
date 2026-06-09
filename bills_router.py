"""
bills_router.py — Phase H.1 v1 — Accounts Payable.

Owner-gated CRUD over the bills table + lazy recurring-bill generation
(mirrors the invoices recurrence model). Sync sb_clients service-role with
explicit business_id scoping (Chief/Phase-G pattern).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date as _date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("bills_router")

router = APIRouter(prefix="/bills", tags=["bills"])

_BUCKETS = ("tax", "owner_pay", "operating", "savings", "other")
_FREQS = ("weekly", "biweekly", "monthly", "quarterly", "annually")
# A bill is outstanding (counts toward AP) when not paid and not cancelled.
OUTSTANDING_EXCLUDED = ("paid", "cancelled")
_SAFETY_CAP = 36  # max recurring instances generated per template per call


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> _date:
    return datetime.now(timezone.utc).date()


def _d(s: Optional[str]) -> Optional[_date]:
    try:
        y, m, dd = (int(p) for p in (s or "").split("-"))
        return _date(y, m, dd)
    except Exception:
        return None


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _owner_for_bill(bill_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/bills?id=eq.{bill_id}&select=id,business_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "bill not found")
    _owner(str(rows[0].get("business_id")), user)
    return rows[0]


# ─── Recurrence (mirror invoices) ────────────────────────────────────

def _step(d: _date, freq: str, n: int) -> _date:
    """d advanced by n steps of freq."""
    if freq == "weekly":
        return d + timedelta(days=7 * n)
    if freq == "biweekly":
        return d + timedelta(days=14 * n)
    if freq == "monthly":
        return _add_months(d, n)
    if freq == "quarterly":
        return _add_months(d, 3 * n)
    if freq == "annually":
        return _add_months(d, 12 * n)
    return d


def _add_months(d: _date, months: int) -> _date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    # Clamp day to month length.
    import calendar
    day = min(d.day, calendar.monthrange(y, m)[1])
    return _date(y, m, day)


def _generate_due_recurring_bills(business_id: str) -> int:
    """Create missing recurring-bill instances up to today. Lazy + idempotent
    (children counted to derive the next index). Returns count created."""
    templates = sb_clients.sb_get_as_service(
        f"/bills?business_id=eq.{business_id}&is_recurring=eq.true"
        f"&recurrence_paused=eq.false&recurrence_index=eq.0&status=neq.cancelled"
        f"&select=*"
    ) or []
    today = _today()
    created = 0
    for t in templates:
        freq = t.get("recurrence_frequency")
        start = _d(t.get("recurrence_start")) or _d(t.get("due_date"))
        if freq not in _FREQS or not start:
            continue
        # Existing children for this template.
        kids = sb_clients.sb_get_as_service(
            f"/bills?business_id=eq.{business_id}"
            f"&recurrence_parent_id=eq.{t['id']}&select=recurrence_index"
        ) or []
        # index 0 = template itself (due on `start`). Next index = max+1.
        max_idx = max([0] + [int(k.get("recurrence_index") or 0) for k in kids])
        end_type = t.get("recurrence_end_type") or "never"
        end_val = t.get("recurrence_end_value")
        n = max_idx + 1
        guard = 0
        while guard < _SAFETY_CAP:
            guard += 1
            if end_type == "after_count":
                try:
                    if n >= int(end_val):
                        break
                except Exception:
                    pass
            next_due = _step(start, freq, n)
            if end_type == "on_date":
                ed = _d(end_val)
                if ed and next_due > ed:
                    break
            if next_due > today:
                break  # don't pre-generate future instances
            try:
                sb_clients.sb_post_as_service("/bills", {
                    "business_id": business_id,
                    "vendor_name": t.get("vendor_name"),
                    "description": t.get("description"),
                    "amount": t.get("amount"),
                    "category": t.get("category") or "operating",
                    "subcategory": t.get("subcategory"),
                    "due_date": next_due.isoformat(),
                    "status": "pending",
                    "is_recurring": False,
                    "recurrence_parent_id": t["id"],
                    "recurrence_index": n,
                    "is_1099_eligible": t.get("is_1099_eligible") or False,
                }, prefer=None)
                created += 1
            except Exception as e:
                logger.warning(f"[bills] recurring gen insert failed: {e}")
                break
            n += 1
    return created


def _mark_overdue(business_id: str) -> None:
    """Flip pending/scheduled bills past their due date to overdue."""
    today = _today().isoformat()
    try:
        sb_clients.sb_patch_as_service(
            f"/bills?business_id=eq.{business_id}"
            f"&status=in.(pending,scheduled)&due_date=lt.{today}",
            {"status": "overdue", "updated_at": _now_iso()})
    except Exception as e:
        logger.warning(f"[bills] mark overdue failed: {e}")


# ─── Endpoints ───────────────────────────────────────────────────────

@router.get("")
def list_bills(biz: str, status: Optional[str] = None,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    _generate_due_recurring_bills(biz)
    _mark_overdue(biz)
    parts = [f"business_id=eq.{biz}"]
    if status:
        parts.append(f"status=eq.{status}")
    parts.append("order=due_date.asc.nullslast,created_at.desc&select=*&limit=2000")
    rows = sb_clients.sb_get_as_service(f"/bills?{'&'.join(parts)}") or []
    return {"ok": True, "bills": rows}


class BillBody(BaseModel):
    business_id: str
    vendor_name: str
    amount: float
    description: Optional[str] = None
    category: str = "operating"
    subcategory: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "pending"
    is_recurring: bool = False
    recurrence_frequency: Optional[str] = None
    recurrence_start: Optional[str] = None
    recurrence_end_type: Optional[str] = "never"
    recurrence_end_value: Optional[str] = None
    is_1099_eligible: bool = False
    notes: Optional[str] = None


@router.post("")
def create_bill(body: BillBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(body.business_id, user)
    if body.category not in _BUCKETS:
        raise HTTPException(400, f"category must be one of {_BUCKETS}")
    if body.is_recurring and body.recurrence_frequency not in _FREQS:
        raise HTTPException(400, f"recurring bills need a frequency in {_FREQS}")
    payload = {
        "business_id": body.business_id,
        "vendor_name": body.vendor_name,
        "description": body.description,
        "amount": body.amount,
        "category": body.category,
        "subcategory": body.subcategory,
        "due_date": body.due_date,
        "status": body.status if body.status in
            ("draft", "pending", "scheduled", "paid", "overdue", "cancelled") else "pending",
        "is_recurring": body.is_recurring,
        "recurrence_frequency": body.recurrence_frequency if body.is_recurring else None,
        "recurrence_start": (body.recurrence_start or body.due_date) if body.is_recurring else None,
        "recurrence_end_type": body.recurrence_end_type if body.is_recurring else None,
        "recurrence_end_value": body.recurrence_end_value if body.is_recurring else None,
        "recurrence_index": 0,
        "is_1099_eligible": body.is_1099_eligible,
        "notes": body.notes,
    }
    res = sb_clients.sb_post_as_service("/bills", payload)
    row = (res or [None])[0] if isinstance(res, list) else res
    # Backfill any already-due instances for a new recurring template.
    if body.is_recurring:
        _generate_due_recurring_bills(body.business_id)
    return {"ok": True, "bill": row}


class BillPatchBody(BaseModel):
    business_id: str
    vendor_name: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None
    is_1099_eligible: Optional[bool] = None
    recurrence_paused: Optional[bool] = None
    notes: Optional[str] = None


@router.patch("/{bill_id}")
def update_bill(bill_id: str, body: BillPatchBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_for_bill(bill_id, user)
    patch: Dict[str, Any] = {"updated_at": _now_iso()}
    for f in ("vendor_name", "amount", "description", "subcategory", "due_date",
              "is_1099_eligible", "recurrence_paused", "notes"):
        v = getattr(body, f)
        if v is not None:
            patch[f] = v
    if body.category is not None:
        if body.category not in _BUCKETS:
            raise HTTPException(400, f"category must be one of {_BUCKETS}")
        patch["category"] = body.category
    if body.status is not None:
        if body.status not in ("draft", "pending", "scheduled", "paid", "overdue", "cancelled"):
            raise HTTPException(400, "invalid status")
        patch["status"] = body.status
    sb_clients.sb_patch_as_service(
        f"/bills?id=eq.{bill_id}&business_id=eq.{body.business_id}", patch)
    return {"ok": True}


class MarkPaidBody(BaseModel):
    business_id: str
    paid_amount: Optional[float] = None
    paid_via: Optional[str] = "manual"


@router.post("/{bill_id}/mark-paid")
def mark_paid(bill_id: str, body: MarkPaidBody,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _owner_for_bill(bill_id, user)
    cur = sb_clients.sb_get_as_service(
        f"/bills?id=eq.{bill_id}&select=amount&limit=1") or [{}]
    amt = body.paid_amount if body.paid_amount is not None else cur[0].get("amount")
    sb_clients.sb_patch_as_service(
        f"/bills?id=eq.{bill_id}&business_id=eq.{body.business_id}",
        {"status": "paid", "paid_at": _now_iso(),
         "paid_amount": amt, "paid_via": body.paid_via or "manual",
         "updated_at": _now_iso()})
    return {"ok": True}


@router.delete("/{bill_id}")
def delete_bill(bill_id: str, biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    sb_clients.sb_delete_as_service(f"/bills?id=eq.{bill_id}&business_id=eq.{biz}")
    return {"ok": True}
