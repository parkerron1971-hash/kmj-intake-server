"""
entity_groups_router.py — Category E — multi-entity consolidation v2.

An owner groups several of their businesses (Love City Church + KMJ
Creative + KMJ Ministries + The Solutionist System LLC → one roll-up).
Consolidated P&L / Balance Sheet = per-business GL reports summed with a
per-business column breakdown.

ELIMINATIONS HONESTY: inter-company transfers carry no tagging anywhere,
so v1 performs NO eliminations — the response says so in-band. A transfer
between two grouped businesses shows in both columns (and inflates the
consolidated line) until an inter-company tagging feature is ruled.

FX scaffold rides along here: fx_rates is a manual-entry table (v1.5 —
API integration is a future ruling). All ledgers are USD-only today
(GL-8 blocks non-USD backfill), so no conversion math runs yet.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
import gl_reports
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("entity_groups")

router = APIRouter(prefix="/entities", tags=["entities"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owned_businesses(user_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/businesses?owner_id=eq.{user_id}&is_active=eq.true"
        f"&select=id,name,type,entity_group_id&limit=100") or []


def _own_group(group_id: str, user_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/entity_groups?id=eq.{group_id}&owner_id=eq.{user_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "entity group not found")
    return rows[0]


class GroupBody(BaseModel):
    name: str


@router.get("")
def list_groups(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    groups = sb_clients.sb_get_as_service(
        f"/entity_groups?owner_id=eq.{user.id}&order=created_at.asc&select=*") or []
    businesses = _owned_businesses(str(user.id))
    for g in groups:
        g["businesses"] = [b for b in businesses if b.get("entity_group_id") == g["id"]]
    return {"ok": True, "groups": groups,
            "unassigned": [b for b in businesses if not b.get("entity_group_id")]}


@router.post("")
def create_group(body: GroupBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    res = sb_clients.sb_post_as_service("/entity_groups", {
        "owner_id": str(user.id), "name": name, "created_at": _now_iso()})
    row = (res or [None])[0] if isinstance(res, list) else res
    return {"ok": True, "group": row}


class AssignBody(BaseModel):
    business_id: str


@router.post("/{group_id}/assign")
def assign(group_id: str, body: AssignBody,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _own_group(group_id, user.id if isinstance(user.id, str) else str(user.id))
    owned = {b["id"] for b in _owned_businesses(str(user.id))}
    if body.business_id not in owned:
        raise HTTPException(403, "not your business")
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{body.business_id}", {"entity_group_id": group_id})
    return {"ok": True}


@router.post("/{group_id}/unassign")
def unassign(group_id: str, body: AssignBody,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _own_group(group_id, str(user.id))
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{body.business_id}&entity_group_id=eq.{group_id}",
        {"entity_group_id": None})
    return {"ok": True}


@router.delete("/{group_id}")
def delete_group(group_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _own_group(group_id, str(user.id))
    sb_clients.sb_patch_as_service(
        f"/businesses?entity_group_id=eq.{group_id}", {"entity_group_id": None})
    sb_clients.sb_delete_as_service(f"/entity_groups?id=eq.{group_id}&owner_id=eq.{user.id}")
    return {"ok": True}


# ─── Consolidated reports ────────────────────────────────────────────

@router.get("/{group_id}/consolidated-pl")
def consolidated_pl(group_id: str, period: str = "this_year",
                    basis: str = "accrual",
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    group = _own_group(group_id, str(user.id))
    members = [b for b in _owned_businesses(str(user.id))
               if b.get("entity_group_id") == group_id]
    columns = []
    total = {"gross_revenue": 0.0, "total_expenses": 0.0, "net_income": 0.0}
    for b in members:
        if not gl_reports.gl_active(b["id"]):
            columns.append({"business_id": b["id"], "name": b.get("name"),
                            "needs_gl": True, "gross_revenue": 0.0,
                            "total_expenses": 0.0, "net_income": 0.0})
            continue
        pl = gl_reports.gl_profit_and_loss(b["id"], period, basis=basis)
        cur = pl.get("current") or {}
        rev = (cur.get("revenue") or {}).get("gross_revenue") or 0.0
        exp = (cur.get("expenses") or {}).get("total") or 0.0
        net = cur.get("net_income") or 0.0
        columns.append({"business_id": b["id"], "name": b.get("name"),
                        "gross_revenue": rev, "total_expenses": exp, "net_income": net})
        total["gross_revenue"] = round(total["gross_revenue"] + rev, 2)
        total["total_expenses"] = round(total["total_expenses"] + exp, 2)
        total["net_income"] = round(total["net_income"] + net, 2)
    return {"ok": True, "report": "consolidated_pl", "group": group.get("name"),
            "period": period, "basis": basis, "currency": "USD",
            "columns": columns, "consolidated": total,
            "eliminations": "none",
            "note": ("No inter-company eliminations yet — transfers between "
                     "grouped businesses appear in both columns until "
                     "inter-company tagging is ruled. Read the consolidated "
                     "line with that in mind.")}


@router.get("/{group_id}/consolidated-balance-sheet")
def consolidated_balance_sheet(group_id: str, as_of: Optional[str] = None,
                               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    group = _own_group(group_id, str(user.id))
    members = [b for b in _owned_businesses(str(user.id))
               if b.get("entity_group_id") == group_id]
    columns = []
    total = {"assets": 0.0, "liabilities": 0.0, "equity": 0.0}
    for b in members:
        if not gl_reports.gl_active(b["id"]):
            columns.append({"business_id": b["id"], "name": b.get("name"),
                            "needs_gl": True, "assets": 0.0, "liabilities": 0.0,
                            "equity": 0.0})
            continue
        bs = gl_reports.gl_balance_sheet(b["id"], as_of)
        a = float(((bs.get("assets") or {}).get("total")) or 0)
        li = float(((bs.get("liabilities") or {}).get("total")) or 0)
        eq = float(((bs.get("equity") or {}).get("total")) or 0)
        columns.append({"business_id": b["id"], "name": b.get("name"),
                        "assets": a, "liabilities": li, "equity": eq})
        total["assets"] = round(total["assets"] + a, 2)
        total["liabilities"] = round(total["liabilities"] + li, 2)
        total["equity"] = round(total["equity"] + eq, 2)
    return {"ok": True, "report": "consolidated_balance_sheet",
            "group": group.get("name"), "as_of": as_of, "currency": "USD",
            "columns": columns, "consolidated": total, "eliminations": "none"}


# ─── FX rates (manual scaffold) ──────────────────────────────────────

class FxBody(BaseModel):
    base_currency: str
    quote_currency: str = "USD"
    rate: float
    as_of_date: str


@router.get("/fx/rates")
def list_fx(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/fx_rates?owner_id=eq.{user.id}&order=as_of_date.desc&limit=200&select=*") or []
    return {"ok": True, "rates": rows,
            "note": ("Manual rates (v1.5). The ledger is USD-only today — "
                     "non-USD source rows are blocked at backfill (GL-8) and "
                     "flagged for manual review; conversion math activates "
                     "with multi-currency ingestion (future ruling).")}


@router.put("/fx/rates")
def put_fx(body: FxBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    base = (body.base_currency or "").upper().strip()
    quote = (body.quote_currency or "USD").upper().strip()
    if len(base) != 3 or len(quote) != 3:
        raise HTTPException(400, "currencies must be 3-letter ISO codes")
    if body.rate <= 0:
        raise HTTPException(400, "rate must be positive")
    existing = sb_clients.sb_get_as_service(
        f"/fx_rates?owner_id=eq.{user.id}&base_currency=eq.{base}"
        f"&quote_currency=eq.{quote}&as_of_date=eq.{body.as_of_date}&select=id&limit=1") or []
    if existing:
        sb_clients.sb_patch_as_service(
            f"/fx_rates?id=eq.{existing[0]['id']}", {"rate": body.rate, "source": "manual"})
    else:
        sb_clients.sb_post_as_service("/fx_rates", {
            "owner_id": str(user.id), "base_currency": base, "quote_currency": quote,
            "rate": body.rate, "as_of_date": body.as_of_date, "source": "manual"}, prefer=None)
    return {"ok": True}
