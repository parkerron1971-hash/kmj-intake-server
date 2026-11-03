"""church_map_router.py — the office's leaders map (docs/CHURCH_LEADERS_MAP.md §3, PR 5).

    GET  /church/map?business_id=                   the map and its gaps (church_map.view);
                                                    a manager seat and up
    PUT  /church/map/departments?business_id=       make or change a department, and what
                                                    hangs from it; the owner or an admin
    POST /church/map/departments/{id}/archive?...   archive one; what hung from it is free
    PUT  /church/map/answers-to?business_id=        who a role holder answers to, or nobody
    PUT  /church/map/settings?business_id=          the pastor's-yes and office-overseer roles
                                                    (the owner or an admin); the money levels
                                                    (the owner only: decision 3)

Behind CHURCH_MAP: a 404 unless church_map.open_to(user), so with `owner`
only the platform owner's login reaches these; a 503 before the migration,
when the probe itself fails (church_map.state() None) or when the map can't
be read: church_map's writes and view refuse then. The business id is checked
as church_router checks it, and the seat by business_access.assert_access: no
seat, or too low a one, is the same 404 a stranger gets. Reads and writes go
through the service role, always by business_id.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import church_map as cm
import sb_clients
from auth_supabase import AuthedUser, require_user
from business_access import assert_access

router = APIRouter(prefix="/church/map", tags=["church"])


def _church(business_id: str, user: AuthedUser, min_role: str) -> Tuple[Dict[str, Any], str]:
    """The switch, then the business id, the seat and a church (church_map
    checks its own tables). Returns the church's row and the caller's role."""
    if not cm.open_to(user):
        raise HTTPException(404, "Not Found")
    try:
        bid = str(uuid.UUID(str(business_id)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")
    role = assert_access(bid, user, min_role)
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{bid}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, cm.UNREAD)
    import church_follow_up as cfu
    if not rows or not cfu.is_church(rows[0]):
        raise HTTPException(404, "The leaders map is for churches.")
    return rows[0], role


class _Unit(BaseModel):
    kind: str = Field(..., max_length=20)
    ref: Optional[str] = Field(None, max_length=40)
    label: Optional[str] = Field(None, max_length=120)


class _Department(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = Field(None, max_length=80)
    leader_contact_id: Optional[str] = None
    overseer_contact_id: Optional[str] = None
    support_duty: Optional[str] = Field(None, max_length=40)
    area: Optional[str] = Field(None, max_length=40)
    status: Optional[str] = Field(None, max_length=10)
    source: Optional[str] = Field(None, max_length=10)
    sort: Optional[int] = None
    units: Optional[List[_Unit]] = Field(None, max_length=cm.UNITS_MAX)


class _AnswersTo(BaseModel):
    holder_id: str
    answers_to_contact_id: Optional[str] = None


class _Settings(BaseModel):
    pastor_from_cents: Optional[int] = None
    board_over_cents: Optional[int] = None
    pastor_yes_roles: Optional[List[str]] = Field(None, max_length=cm.PICKS_MAX)
    office_overseer_roles: Optional[List[str]] = Field(None, max_length=cm.PICKS_MAX)


@router.get("")
def map_view(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "manager")
    return {**cm.view(biz), "you": {"role": role, "writes": role in ("owner", "admin"), "money": role == "owner"}}


@router.put("/departments")
def department_save(body: _Department, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, _role = _church(business_id, user, "admin")
    return {"ok": True, "department": cm.save_department(biz, body.model_dump(exclude_unset=True), user.id)}


@router.post("/departments/{department_id}/archive")
def department_archive(department_id: str, business_id: str = Query(...),
                       user: AuthedUser = Depends(require_user)):
    biz, _role = _church(business_id, user, "admin")
    return {"ok": True, "department": cm.archive_department(biz, department_id, user.id)}


@router.put("/answers-to")
def answers_to_save(body: _AnswersTo, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, _role = _church(business_id, user, "admin")
    return {"ok": True, "holder": cm.set_answers_to(biz, body.holder_id, body.answers_to_contact_id)}


@router.put("/settings")
def settings_save(body: _Settings, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    return {"ok": True, **cm.save_settings(biz, body.model_dump(exclude_unset=True), user.id, role)}
