"""
church_router.py — the church office's read-only questions about people.

    GET /church/first-time-guests?business_id=   came for the first time,
                                                 nobody has reached out since
    GET /church/care-counts?business_id=         the Prayer & care inbox as
                                                 numbers (owner and staff)
    GET /church/cards?business_id=               every card a guest can fill
                                                 in (the website's own and the
                                                 app's forms) and what came in
                                                 on each (owner and staff)
    GET /church/follow-ups?business_id=          Leaders & follow-up: everyone
        POST …/{id}/reassign | note | step | close   a card handed to a leader
    GET|POST /church/leaders, DELETE …/{role_id}  who holds which role
                                                 (church_follow_up; owner and
                                                 staff)

First-time guests: any active seat may read (the same rule as the
attendance table itself). Care counts: the owner and staff only, see
CARE_MIN_ROLE. The answers come from church_reads, which Chief reads too,
so the Home desk, the room overviews and Chief never disagree about who is
waiting for a call or how many prayer requests are new.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import church_cards
import church_follow_up
import church_reads
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(prefix="/church", tags=["church"])

# Who may read the care numbers: the church's owner and its staff, the same
# people Chief gives them to (chief_church_actions._CARE_ROLES: owner, admin,
# manager). business_access takes a MINIMUM rank on the seat ladder in
# business_users_router._ROLE_RANK,
#     viewer 1 < member 2 < manager 3 < admin 4 < owner 5,
# so "manager" lets in exactly manager, admin and owner and keeps member and
# viewer seats out. Accountants are not on that ladder at all: they are
# business_collaborators, not business_users, so role_of gives them no role
# and they are refused like anyone else with no seat (and a seat row naming
# a role the ladder doesn't know ranks 0, also refused). Nothing to order
# around, so no special case. A refusal is business_access's deliberate 404,
# the same answer a stranger gets.
CARE_MIN_ROLE = "manager"

# The only numbers the care route ever sends. Named, so a status or a field
# added to church_reads later cannot reach the app by accident.
CARE_COUNT_KEYS = ("new", "reviewed", "closed", "prayed")


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")


@router.get("/first-time-guests")
def first_time_guests(business_id: str = Query(...),
                      limit: int = Query(20, ge=1, le=100),
                      biz: Dict[str, Any] = Depends(business_access("viewer"))):
    rows = church_reads.first_time_guests(_uuid(business_id), limit=limit)
    if rows is None:
        raise HTTPException(503, "First-time guests couldn't be loaded. Try again in a moment.")
    return {"guests": rows, "window_days": church_reads.FIRST_VISIT_WINDOW_DAYS}


@router.get("/care-counts")
def care_counts(business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """How many prayer and care requests are new, reviewed, closed and
    marked prayed in the last CARE_WINDOW_DAYS, and how many days the
    oldest new one has waited (None when nothing is new). Numbers only:
    never a request's words, a name, an id or anything about children."""
    care = church_reads.care_request_counts(_uuid(business_id))
    if care is None:
        raise HTTPException(503, "Prayer and care numbers couldn't be loaded. Try again in a moment.")
    oldest = care.get("oldest_new_days")
    return {
        "care": {**{k: int(care.get(k) or 0) for k in CARE_COUNT_KEYS},
                 "oldest_new_days": int(oldest) if oldest is not None else None},
        "window_days": church_reads.CARE_WINDOW_DAYS,
    }


class _Reassign(BaseModel):
    leader_contact_id: Optional[str] = None


class _Note(BaseModel):
    text: str = Field(..., max_length=2000)
    pastors_only: bool = False


class _Role(BaseModel):
    contact_id: str
    role: str
    scope: str = Field("", max_length=120)


def _who(session: UserSession) -> Tuple[str, str]:
    user = session.user
    meta = getattr(user, "user_metadata", None) or {}
    name = (meta.get("full_name") or meta.get("name") or getattr(user, "email", "") or "The office")
    return str(user.id), str(name)[:120]


@router.get("/follow-ups")
def follow_ups(business_id: str = Query(...),
               biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """The Follow-up board: everyone a card handed to someone, where they
    are on their path, and every note (church_follow_up.board)."""
    out = church_follow_up.board(_uuid(business_id))
    if out is None:
        raise HTTPException(503, "Follow-up couldn't be loaded. Try again in a moment.")
    return out


@router.post("/follow-ups/{follow_up_id}/reassign")
def follow_up_reassign(follow_up_id: str, body: _Reassign, business_id: str = Query(...),
                       biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                       session: UserSession = Depends(sb_clients.authed_request)):
    uid, name = _who(session)
    church_follow_up.reassign(_uuid(business_id), follow_up_id, body.leader_contact_id, by_user=uid, by_name=name)
    return {"ok": True}


@router.post("/follow-ups/{follow_up_id}/note")
def follow_up_note(follow_up_id: str, body: _Note, business_id: str = Query(...),
                   biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                   session: UserSession = Depends(sb_clients.authed_request)):
    uid, name = _who(session)
    note = church_follow_up.office_note(_uuid(business_id), follow_up_id, body.text,
                                        pastors_only=body.pastors_only, by_user=uid, by_name=name)
    return {"ok": True, "note_id": str(note.get("id") or "")}


@router.post("/follow-ups/{follow_up_id}/step")
def follow_up_step(follow_up_id: str, business_id: str = Query(...),
                   biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                   session: UserSession = Depends(sb_clients.authed_request)):
    uid, name = _who(session)
    row = church_follow_up.advance(_uuid(business_id), follow_up_id, author_kind="office",
                                   author_user_id=uid, author_name=name)
    return {"ok": True, "step": row.get("step"), "status": row.get("status")}


@router.post("/follow-ups/{follow_up_id}/close")
def follow_up_close(follow_up_id: str, business_id: str = Query(...),
                    biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                    session: UserSession = Depends(sb_clients.authed_request)):
    uid, name = _who(session)
    church_follow_up.close(_uuid(business_id), follow_up_id, by_user=uid, by_name=name)
    return {"ok": True}


@router.get("/leaders")
def leaders(business_id: str = Query(...),
            biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """Leaders & roles: who holds which role (invited or active), the
    roles a member can hold, and the teams a team leader can lead (the
    choices on the church's Serve card)."""
    bid = _uuid(business_id)
    rows, team_names = church_follow_up.roles(bid), church_follow_up.teams(bid)
    if rows is None or team_names is None:
        raise HTTPException(503, "Your leaders couldn't be loaded. Try again in a moment.")
    return {
        "roles": [{k: r.get(k) for k in ("id", "contact_id", "name", "email", "phone", "role", "scope",
                                          "status", "invited_at", "answered_at")} for r in rows],
        "role_labels": church_follow_up.ROLE_LABELS,
        "teams": team_names,
        # Each card's path as the engine runs it, so the page shows exactly
        # what happens (steps and their days, and the late ladder).
        "paths": church_follow_up.PATHS,
        "late_ladder": [{"days": d, "level": lvl, "kind": k} for d, lvl, k in church_follow_up.LATE_LADDER],
    }


@router.post("/leaders")
async def leader_add(body: _Role, business_id: str = Query(...),
                     biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                     session: UserSession = Depends(sb_clients.authed_request)):
    """Ask a member to take a role. They get an email with a link to their
    member page, where they say yes; the Lead tab appears then."""
    import asyncio
    uid, _name = _who(session)
    row = await asyncio.to_thread(church_follow_up.add_role, _uuid(business_id), body.contact_id,
                                  body.role, body.scope, by_user=uid)
    emailed = False
    if not row.get("already"):
        emailed = await church_follow_up.send_invite(biz, row)
    return {"ok": True, "id": str(row.get("id") or ""), "status": row.get("status"),
            "already": bool(row.get("already")), "emailed": emailed}


@router.delete("/leaders/{role_id}")
def leader_remove(role_id: str, business_id: str = Query(...),
                  biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    church_follow_up.remove_role(_uuid(business_id), role_id)
    return {"ok": True}


@router.get("/cards")
def cards(business_id: str = Query(...),
          biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """The Forms page's cards: the ones written into the church's website,
    with their questions, and how many came in on each card and intake form
    in the last 90 days. Who filled in a card is the office's to see (owner
    and staff, the same seats as the care numbers); a private card is
    numbers only. See church_cards."""
    out = church_cards.cards(_uuid(business_id))
    if out is None:
        raise HTTPException(503, "Your cards couldn't be loaded. Try again in a moment.")
    return out
