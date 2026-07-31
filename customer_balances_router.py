"""
customer_balances_router.py — the drawdown ledger's HTTP surface.

THE GAP THIS CLOSES
  BE#307 shipped the primitive: customer_ledger (append-only signed rows),
  the customer_balances view, customer_balances.py, and three Chief verbs.
  But the ONLY way in was the chatbot — a coach had to literally type
  "Sarah used a session". No screen could show a balance, no button could
  grant one. This router is the product surface: reads for the contact
  page's BalanceCard, writes for its Grant/Consume actions.

AUTH LADDER (seat-access arc, 7/31 matrix)
  Reads  — member+. A team member checking "how many sessions does Marcus
           have left" before a call is exactly what member seats are for.
           Viewers stay out: balances are money, not directory data.
  Writes — manager+. Granting and consuming move prepaid value; that is
           manager work, same rank as outward sends.
  Owner passes everything (rank 5 in business_users_router._ROLE_RANK).

THIN BY DESIGN
  Every read and write goes through customer_balances.py — the balance
  math, validation, and the lost-race self-reversal on consume live
  THERE. This file only authenticates, authorizes, shapes JSON, and
  resolves vertical defaults so a coach's grant lands as package/session
  without the UI interrogating them about ledger taxonomy.

INSUFFICIENT BALANCE IS NOT AN ERROR
  consume returning ok=False with `available` is a normal business
  outcome ("Marcus is out of sessions"), so it comes back as HTTP 200
  with the shortfall attached — the UI says so in words. Malformed
  input (bad kind, non-positive amount) is a real 400.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
import customer_balances as cb

logger = logging.getLogger("customer_balances_router")

router = APIRouter(prefix="/balances", tags=["balances"])


# ─── auth ────────────────────────────────────────────────────────────

def _gate(biz: str, user: AuthedUser, min_role: str) -> Dict[str, Any]:
    """404 unknown business, then the shared role ladder (owner = rank 5,
    so the owner fallback every router carries is already inside
    require_role). Returns the business row — callers need its type for
    vertical defaults."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz, str(user.id), min_role)
    return rows[0]


def _contact_in_business(biz: str, contact_id: str) -> Dict[str, Any]:
    """A grant aimed at another business's contact must die here, not
    land as a cross-tenant ledger row."""
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{contact_id}&business_id=eq.{biz}"
        f"&select=id,name&limit=1") or []
    if not rows:
        raise HTTPException(404, "contact not found in this business")
    return rows[0]


# ─── reads (member+) ─────────────────────────────────────────────────

@router.get("/{business_id}/contact/{contact_id}")
def contact_balances(business_id: str, contact_id: str,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Everything the contact page needs in one call: balances by
    (kind, unit) — including zeroed-out ones, "0 of 10 left" is
    information — plus the recent ledger history that explains them,
    and this vertical's grant defaults for the UI's dialog."""
    biz_row = _gate(business_id, user, "member")
    _contact_in_business(business_id, contact_id)

    rows = sb_clients.sb_get_as_service(
        f"/customer_balances?business_id=eq.{business_id}"
        f"&contact_id=eq.{contact_id}&select=*") or []
    history = cb.history(business_id, contact_id, limit=50)
    return {
        "ok": True,
        "balances": rows,
        "history": history,
        "defaults": cb.defaults_for_vertical(biz_row.get("type")),
    }


@router.get("/{business_id}")
def business_balances(business_id: str,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Every non-zero balance across the business, with contact names —
    "who is holding prepaid value" at a glance."""
    _gate(business_id, user, "member")
    rows = [r for r in (sb_clients.sb_get_as_service(
        f"/customer_balances?business_id=eq.{business_id}&select=*") or [])
        if _num(r.get("balance")) != 0]

    contact_ids = sorted({str(r["contact_id"]) for r in rows if r.get("contact_id")})
    names: Dict[str, str] = {}
    if contact_ids:
        contacts = sb_clients.sb_get_as_service(
            f"/contacts?id=in.({','.join(contact_ids)})"
            f"&business_id=eq.{business_id}&select=id,name&limit=500") or []
        names = {str(c["id"]): c.get("name") or "—" for c in contacts}
    for r in rows:
        r["contact_name"] = names.get(str(r.get("contact_id")), "—")
    return {"ok": True, "balances": rows}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ─── writes (manager+) ───────────────────────────────────────────────

class GrantBody(BaseModel):
    contact_id: str
    amount: float
    kind: Optional[str] = None
    unit: Optional[str] = None
    reason: Optional[str] = None
    expires_at: Optional[str] = None   # ISO Z-form; grants only
    offering_id: Optional[str] = None
    invoice_id: Optional[str] = None


class ConsumeBody(BaseModel):
    contact_id: str
    amount: float = 1
    kind: Optional[str] = None
    unit: Optional[str] = None
    reason: Optional[str] = None
    allow_overdraw: bool = False


def _kind_unit(biz_row: Dict[str, Any], kind: Optional[str],
               unit: Optional[str]) -> Dict[str, str]:
    d = cb.defaults_for_vertical(biz_row.get("type"))
    return {"kind": (kind or d["kind"]).strip().lower(),
            "unit": (unit or d["unit"]).strip().lower()}


@router.post("/{business_id}/grant")
def grant(business_id: str, body: GrantBody,
          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _gate(business_id, user, "manager")
    _contact_in_business(business_id, body.contact_id)
    ku = _kind_unit(biz_row, body.kind, body.unit)
    reason = (body.reason or "").strip() or \
        f"{ku['kind'].replace('_', ' ').title()} purchased"
    res = cb.grant(
        business_id, body.contact_id, body.amount, ku["kind"], ku["unit"],
        reason, offering_id=body.offering_id, invoice_id=body.invoice_id,
        expires_at=body.expires_at, created_by=str(user.id))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error") or "grant failed")
    return res


@router.post("/{business_id}/consume")
def consume(business_id: str, body: ConsumeBody,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _gate(business_id, user, "manager")
    _contact_in_business(business_id, body.contact_id)
    ku = _kind_unit(biz_row, body.kind, body.unit)
    reason = (body.reason or "").strip() or "Delivered"
    res = cb.consume(
        business_id, body.contact_id, body.amount, ku["kind"], ku["unit"],
        reason, allow_overdraw=body.allow_overdraw, created_by=str(user.id))
    if not res.get("ok"):
        # Insufficient balance (including the lost-race reversal) is a
        # normal outcome the UI must narrate — 200 with the numbers.
        if res.get("available") is not None:
            return res
        raise HTTPException(400, res.get("error") or "consume failed")
    return res
