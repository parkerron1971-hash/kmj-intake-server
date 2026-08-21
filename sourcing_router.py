"""
sourcing_router.py — THE SOURCING DESK, stage 1 endpoints (2026-08-21).

POST /sourcing/{business_id}/search   run one search (owner, metered, capped)
GET  /sourcing/{business_id}/searches the runs already paid for
GET  /sourcing/{business_id}/limits   what's left today, for the UI

TWO GATES, AND THEY ARE NOT THE SAME GATE
  billing_limits.require_units is the METER — this is an AI action and it
  costs the business a unit, on every tier (Kevin's ruling: sourcing is
  not tier-gated; the vendor list is plain CRUD and the search is the
  part that costs).

  The daily cap is the CIRCUIT BREAKER. Metering answers "may they spend
  this?"; it does not answer "should this fire two hundred times?" A
  retry loop in a client, a double-tap on a slow button, or an
  enthusiastic afternoon can each run up a bill against a business that
  meant to search twice. The cap is counted from the rows themselves, so
  it cannot drift from what was actually run.

  Order matters: the cap is checked FIRST. It is free to evaluate and
  refusing early means a capped business is never metered for a search
  it is not going to get.

WHY SEARCHES ARE OWNER-ONLY TO RUN AND MEMBER-READABLE
  Running one spends the business's money. Reading one does not, and the
  people who manage stock should be able to see who was already looked
  at before asking for it to be run again.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import billing_limits
import sb_clients
import sourcing_engine
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("sourcing_router")

router = APIRouter(prefix="/sourcing", tags=["sourcing"])

# A day's worth of genuine use is a handful. This is a runaway guard, not
# a rationing device — a practitioner who hits it has either found a bug
# or is doing something the meter should be having an opinion about.
DAILY_SEARCH_CAP = 12

_NEED_MAX = 400
_LIST_CAP = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id,name,industry&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _reader(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(biz, str(user.id)):
        return row
    from business_users_router import require_role
    require_role(biz, str(user.id), "viewer")
    return row


def searches_today(business_id: str) -> int:
    since = (_now() - timedelta(hours=24)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/sourcing_searches?business_id=eq.{business_id}"
        f"&created_at=gte.{since}&select=id&limit={DAILY_SEARCH_CAP + 1}") or []
    return len(rows)


def _business_context(biz_row: Dict[str, Any], business_id: str) -> str:
    """A couple of lines about who is asking, so the search is for THEIR
    business rather than a generic one. Deliberately thin: the name and
    trade sharpen a supplier search; the customer list would not, and
    every extra field is another thing leaving the building."""
    bits: List[str] = []
    name = (biz_row.get("name") or "").strip()
    industry = (biz_row.get("industry") or "").strip()
    if name:
        bits.append(name)
    if industry:
        bits.append(f"a {industry} business")
    try:
        offs = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=is.true"
            f"&select=name&limit=6") or []
        names = [str(o.get("name") or "").strip() for o in offs]
        names = [n for n in names if n]
        if names:
            bits.append("sells " + ", ".join(names[:6]))
    except Exception:
        pass
    return "; ".join(bits)


class SearchBody(BaseModel):
    need: str
    region: Optional[str] = None
    qty: Optional[int] = None
    budget_per_unit: Optional[float] = None


@router.get("/{business_id}/limits")
def limits(business_id: str,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    used = searches_today(business_id)
    return {"ok": True, "used_today": used, "cap": DAILY_SEARCH_CAP,
            "remaining": max(0, DAILY_SEARCH_CAP - used)}


@router.get("/{business_id}/searches")
def list_searches(business_id: str,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _reader(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/sourcing_searches?business_id=eq.{business_id}"
        f"&order=created_at.desc&select=*&limit={_LIST_CAP}") or []
    return {"ok": True, "searches": rows}


@router.post("/{business_id}/search")
def run_search(business_id: str, body: SearchBody,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner(business_id, user)

    need = (body.need or "").strip()
    if len(need) < 3:
        raise HTTPException(400, "say what you're trying to source")
    if len(need) > _NEED_MAX:
        raise HTTPException(400, "that's a long one — trim it to the essentials")
    if body.qty is not None and (body.qty < 0 or body.qty > 10_000_000):
        raise HTTPException(400, "that quantity doesn't look right")
    if body.budget_per_unit is not None and body.budget_per_unit < 0:
        raise HTTPException(400, "that budget doesn't look right")

    # The circuit breaker first — free to check, and a capped business
    # should never be metered for a search it will not receive.
    used = searches_today(business_id)
    if used >= DAILY_SEARCH_CAP:
        raise HTTPException(429, {
            "error": "daily_search_cap",
            "cap": DAILY_SEARCH_CAP,
            "message": (f"That's {DAILY_SEARCH_CAP} vendor searches today. "
                        f"The limit resets on a rolling 24 hours — the ones "
                        f"you've already run are saved below."),
        })

    # Then the meter. This is an AI action like any other.
    billing_limits.require_units(business_id)

    result = sourcing_engine.search_vendors(
        need=need,
        region=(body.region or "").strip() or None,
        qty=body.qty,
        budget_per_unit=body.budget_per_unit,
        business_context=_business_context(biz_row, business_id),
    )

    row = {
        "business_id": business_id,
        "need": need,
        "region": (body.region or "").strip() or None,
        "qty": body.qty,
        "budget_per_unit": body.budget_per_unit,
        "candidates": result["candidates"],
        "sources": result["sources"],
        "coverage_note": result["coverage_note"],
        "proposed_count": result["proposed_count"],
        "dropped_count": result["dropped_count"],
        "model": result["model"],
        "created_by": str(user.id),
    }
    saved = None
    try:
        created = sb_clients.sb_post_as_service("/sourcing_searches", row) or []
        saved = created[0] if isinstance(created, list) and created else created
    except Exception as e:
        # The search already ran and the practitioner already paid for it.
        # Failing the response because the receipt would not save would
        # charge them and show them nothing.
        logger.warning("[sourcing] could not record search: %s", e)

    return {"ok": True, "search": saved or row,
            "used_today": used + 1, "cap": DAILY_SEARCH_CAP}
