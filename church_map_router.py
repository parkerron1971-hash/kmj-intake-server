"""church_map_router.py — the office's leaders map (docs/CHURCH_LEADERS_MAP.md §3, PR 5).

    GET  /church/map?business_id=                   the map and its gaps (church_map.view);
                                                    a manager seat and up; &with=choices adds
                                                    what the editor's pickers offer (B3b)
    PUT  /church/map/departments?business_id=       make or change a department, and what
                                                    hangs from it; the owner or an admin
    POST /church/map/departments/{id}/archive?...   archive one; what hung from it is free
    PUT  /church/map/answers-to?business_id=        who a role holder answers to, or nobody
    PUT  /church/map/settings?business_id=          the pastor's-yes and office-overseer roles
                                                    (the owner or an admin); the money levels
                                                    (the owner only: decision 3)
    GET  /church/map/changes?business_id=           what waits for a yes, and the recent
                                                    changes in plain words; a manager seat up
    POST /church/map/changes/{id}/undo?...          put one change back (church_map_batch)
    POST /church/map/changes/{id}/apply?...         make a waiting change, or finish a failed one
    POST /church/map/changes/{id}/discard?...       let a waiting change go; these three the
                                                    owner or an admin, a money one the owner
    GET  /church/map/templates?business_id=&q=&kind=  the ready-made directory's search (B4a:
                                                    church_templates); a manager seat and up
    GET  /church/map/templates/{kind}/{key}?...     one ready-made, and what adopting it would
                                                    add here (read only); a manager seat and up
    POST /church/map/templates/adopt?business_id=   {kind, key, tradition?, name?}: the church's
                                                    own copy, as drafts (B4b: church_templates.
                                                    adopt); the owner or an admin
    GET  /church/map/asks?business_id=              Is this right? (B11, church_map_asks): what
                                                    the office suggested, waiting for a yes; the
                                                    owner or an admin
    GET  /church/map/asks/mine?business_id=         an office login's own asks, each answered one
                                                    with `happened` (what came of it, in words),
                                                    and its last check
    POST /church/map/asks/{id}/apply|done|discard?  answer one; the owner or an admin, money the
                                                    owner
    POST /church/map/asks/{id}/undo?business_id=    put back what saying yes to one made, both
                                                    parts or neither (undo_ask's rules); the owner
                                                    or an admin, money the owner

Once step 2's file is applied (church_map.step2_state()), each save above is
logged as one change (church_map_batch, origin 'office'), so the sheet's Undo
covers edits made on screen. Each logged save answers with `change` (its id,
for Undo, or None), `made` (whether anything changed: False with no change is
"nothing changed", True with no change is "saved, but its record didn't
save"), `can_undo` and, for those two, a `note` in words. Before it a save
runs as it always has, logs nothing and says `made` None; a failed probe is a
503. The changes and ready-made routes are a 503 until then.

Behind CHURCH_MAP: a 404 unless church_map.office_open(user, church): the
login (open_to) or the church (church_open), so with `owner` the platform
owner's login and the platform owner's church (Love City: its admins and
Managers too) reach these, the asks routes the same way. The seats still
decide: a Manager seat reads, the owner or an admin writes, money is the
owner's. Moving a duty from an ask follows the duties' own switch for the
login (church_duties.open_to), unwidened: an ask that would move one says why
it can't be applied (`cant_apply`). A 503 before the migration, when the probe
itself fails (church_map.state() None) or when the map can't be read:
church_map's writes and view refuse then. The business id is checked as
church_router checks it, and the seat by business_access.assert_access: no
seat, or too low a one, is the same 404 a stranger gets. Reads and writes go
through the service role, always by business_id.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import church_map as cm
import church_map_asks as asks
import church_map_batch as batch
import church_templates as ct
import sb_clients
from auth_supabase import AuthedUser, require_user
from business_access import assert_access

router = APIRouter(prefix="/church/map", tags=["church"])


def _church(business_id: str, user: AuthedUser, min_role: str) -> Tuple[Dict[str, Any], str]:
    """The business id, the switch (for this login or this church), the seat
    and a church (church_map checks its own tables). Returns the church's row
    and the caller's role."""
    try:
        bid = str(uuid.UUID(str(business_id)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")
    if not cm.office_open(user, bid):
        raise HTTPException(404, "Not Found")
    role = assert_access(bid, user, min_role)
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{bid}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, cm.UNREAD)
    import church_follow_up as cfu
    if not rows or not cfu.is_church(rows[0]):
        raise HTTPException(404, "The leaders map is for churches.")
    return rows[0], role


NOTHING = "Nothing changed: it already read that way."
UNLOGGED = "Saved, but its record didn’t save, so Undo can’t put it back from Recent changes."
# A save before step 2's file: nothing is logged, so whether it changed anything isn't told.
NOT_LOGGED = {"change": None, "made": None, "can_undo": False, "note": ""}


def _told(change: Optional[Dict[str, Any]], made: bool, role: str) -> Dict[str, Any]:
    """What a logged save tells the page: the change it was logged as (Undo posts its id), `made`, whether
    Undo can put it back, and a `note` when there's no change to undo, saying which of the two it is."""
    return {"change": change, "made": bool(made),
            "can_undo": bool(change) and change["status"] == "applied" and (not change["money"] or role == "owner"),
            "note": "" if change else UNLOGGED if made else NOTHING}


def _logged(biz: Dict[str, Any], role: str, user: AuthedUser,
            part: Dict[str, Any]) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """One office save as one change, once step 2's file is applied: (the
    write's own answer, what _told says). None before it: the caller saves as
    it always has, logging nothing. A failed probe is a 503, never "not yet"."""
    s = cm.step2_state()
    if s is None:
        raise HTTPException(503, cm.UNREAD)
    if not s:
        return None
    out = batch.apply(biz, [part], user.id, "office", role=role)
    return out["results"][0], _told(out["change"], out["made"], role)


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
def map_view(business_id: str = Query(...), with_: str = Query("", alias="with", max_length=20),
             user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "manager")
    return {**cm.view(biz, choices=with_ == "choices"),
            "you": {"role": role, "writes": role in ("owner", "admin"), "money": role == "owner"}}


@router.put("/departments")
def department_save(body: _Department, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    said = body.model_dump(exclude_unset=True)
    got = _logged(biz, role, user, {"kind": "department", **said})
    if got is None:
        return {"ok": True, "department": cm.save_department(biz, said, user.id), **NOT_LOGGED}
    return {"ok": True, "department": got[0], **got[1]}


@router.post("/departments/{department_id}/archive")
def department_archive(department_id: str, business_id: str = Query(...),
                       user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    got = _logged(biz, role, user, {"kind": "department", "id": department_id, "status": "archived"})
    if got is None:
        return {"ok": True, "department": cm.archive_department(biz, department_id, user.id), **NOT_LOGGED}
    return {"ok": True, "department": got[0], **got[1]}


@router.put("/answers-to")
def answers_to_save(body: _AnswersTo, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    got = _logged(biz, role, user, {"kind": "answers_to", "holder_id": body.holder_id,
                                    "answers_to_contact_id": body.answers_to_contact_id})
    if got is None:
        return {"ok": True, "holder": cm.set_answers_to(biz, body.holder_id, body.answers_to_contact_id),
                **NOT_LOGGED}
    return {"ok": True, "holder": got[0], **got[1]}


@router.put("/settings")
def settings_save(body: _Settings, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    said = body.model_dump(exclude_unset=True)
    got = _logged(biz, role, user, {"kind": "settings", **said})
    if got is None:
        return {"ok": True, **cm.save_settings(biz, said, user.id, role), **NOT_LOGGED}
    return {"ok": True, **got[0], **got[1]}


@router.get("/changes")
def changes_list(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "manager")
    return batch.recent(biz, role)


@router.post("/changes/{change_id}/undo")
def change_undo(change_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    return {"ok": True, **batch.undo(biz, change_id, user.id, role=role)}


@router.post("/changes/{change_id}/apply")
def change_apply(change_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    return {"ok": True, **batch.apply_pending(biz, change_id, user.id, role=role)}


@router.post("/changes/{change_id}/discard")
def change_discard(change_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    return {"ok": True, **batch.discard(biz, change_id, user.id, role=role)}


# ─── The ready-made directory (B4a) and adopting one (B4b) ────────────

def _directory(business_id: str, user: AuthedUser) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """The church, its role settings and its tradition, once step 2's file is
    there (§1.3). A read only: nothing is seeded."""
    biz, _role = _church(business_id, user, "manager")
    s = cm.step2_state()
    if s is not True:
        raise HTTPException(503, cm.UNREAD if s is None else "The ready-made list isn’t set up yet. Try again later.")
    import church_roles as cr
    st = cr.settings(biz["id"])
    if st is None:
        raise HTTPException(503, cm.UNREAD)
    return biz, st, ct.tradition_of(biz, st)


def _tradition(key: str) -> Dict[str, str]:
    import church_roles as cr
    return {"key": key, "label": cr.TYPES[key]["label"]}


@router.get("/templates")
def templates_search(business_id: str = Query(...), q: str = Query("", max_length=80),
                     kind: str = Query("", max_length=12), user: AuthedUser = Depends(require_user)):
    biz, _st, tradition = _directory(business_id, user)
    if kind not in ("", *ct.KINDS):
        raise HTTPException(400, "Look through whole churches, ministries or roles")
    return {"tradition": _tradition(tradition), "results": ct.search(q, kind, tradition, biz.get("name") or "")}


@router.get("/templates/{kind}/{key}")
def template_detail(kind: str, key: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, st, tradition = _directory(business_id, user)
    t = ct.get(kind, key)
    if t is None:
        raise HTTPException(404, "That ready-made isn’t here")
    return {"tradition": _tradition(tradition), "ready_made": ct.card(t, tradition, biz.get("name") or ""),
            "here": ct.here(biz, t, tradition, st)}


class _Adopt(BaseModel):
    kind: str = Field(..., max_length=12)
    key: str = Field(..., max_length=60)
    tradition: Optional[str] = Field(None, max_length=12)
    name: Optional[str] = Field(None, max_length=80)


@router.post("/templates/adopt")
def template_adopt(body: _Adopt, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz, role = _church(business_id, user, "admin")
    return {"ok": True, **ct.adopt(biz, body.kind, body.key, user.id, role=role, tradition=body.tradition or "",
                                   name=body.name or "")}


# ─── Is this right? (B11): what the office suggests, for a yes ────────

def _asks(business_id: str, user: AuthedUser, least: str) -> Tuple[Dict[str, Any], str]:
    """Opened by the church (church_map.church_open), not by the login, since its office logins are the
    point: a 404 where it's closed, as for a stranger or too low a seat. Then a church and the file
    (church_map_asks.church: a 503 before it)."""
    try:
        bid = str(uuid.UUID(str(business_id)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")
    if not cm.church_open(bid):
        raise HTTPException(404, "Not Found")
    role = assert_access(bid, user, least)
    return asks.church(bid), role


def _gates(user: AuthedUser, bid: str) -> Dict[str, bool]:
    """What this login may make from an ask, as the sheet's and the duties page's own routes decide it: the
    map's change routes (office_open: the login or the church) and the duties' (church_duties.open_to, the
    login's, not widened here). What it can't make or undo there, it can't make through an ask (#1731
    review)."""
    import church_duties as cd
    return {"map": cm.office_open(user, bid), "duty": cd.open_to(user)}


@router.get("/asks")
def asks_open(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    """What the team suggested, waiting for a yes: the owner or an admin."""
    biz, role = _asks(business_id, user, "admin")
    return asks.open_asks(biz, role, str(user.id), _gates(user, biz["id"]), answered=True)


@router.get("/asks/mine")
def asks_mine(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    """An office login's own asks, how each went, and its last check (`checked_at`, `due`)."""
    biz, role = _asks(business_id, user, "manager")
    if role not in asks.OFFICE:
        raise HTTPException(403, asks.OWNER_HERE)
    return asks.mine(biz, str(user.id), role)


@router.post("/asks/{ask_id}/undo")
def asks_undo(ask_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    """Put back what saying yes to one made: its change to the map and the duty it moved, both or neither,
    each through its own undo (church_map_asks.undo_answer, undo_ask's rules). The owner or an admin; a
    change with money in it, the owner. Registered before the answer route, whose {how} would take it."""
    biz, role = _asks(business_id, user, "admin")
    return {"ok": True, **asks.undo_answer(biz, ask_id, str(user.id), role, _gates(user, biz["id"]))}


@router.post("/asks/{ask_id}/{how}")
def asks_answer(ask_id: str, how: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    """apply | done | discard one: the owner or an admin; a change with money in it, the owner. `can_undo`:
    whether POST /church/map/asks/{id}/undo can put back what it made."""
    if how not in ("apply", "done", "discard"):
        raise HTTPException(404, "Not Found")
    biz, role = _asks(business_id, user, "admin")
    out = asks.answer(biz, ask_id, str(user.id), role, how, _gates(user, biz["id"]))
    out.pop("row", None)
    return {"ok": True, **out}
