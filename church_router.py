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
    GET|POST /church/leaders, DELETE …/{role_id}  the role library and who
                                                 holds which role (church_roles,
                                                 church_follow_up; owner and
                                                 staff)
    POST /church/roles, PATCH|DELETE …/{id}      make, change, archive a role
    POST /church/type                            the church type, and its titles
    GET /church/families/suggestions, POST …/accept | accept-sure | dismiss
                                                 Chief's guess at who lives
                                                 together (church_families)
    GET /church/shepherding, PUT …/settings, POST …/propose | approve | move,
        GET|PATCH|DELETE …/proposal, GET …/family/{id}
                                                 every member family's
                                                 shepherd (church_shepherding)

First-time guests: any active seat may read (the same rule as the
attendance table itself). Care counts: the owner and staff only, see
CARE_MIN_ROLE. The answers come from church_reads, which Chief reads too,
so the Home desk, the room overviews and Chief never disagree about who is
waiting for a call or how many prayer requests are new.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import church_cards
import church_checkin
import church_families
import church_follow_up
import church_reads
import church_roles
import church_shepherding
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
    """Ask someone to take a role: `role_id` (the church's role), or the
    first version's `role` key."""
    contact_id: str
    role_id: str = ""
    role: str = ""
    scope: str = Field("", max_length=120)


class _RoleDef(BaseModel):
    """A role in the library: the church's title on a job (church_roles)."""
    title: Optional[str] = Field(None, max_length=80)
    job: Optional[str] = Field(None, max_length=20)
    definition: Optional[str] = Field(None, max_length=1200)
    covers: Optional[str] = Field(None, max_length=10)
    reports_to: Optional[str] = None
    oversees_teams: Optional[List[str]] = Field(None, max_length=40)
    handles: Optional[List[str]] = Field(None, max_length=12)
    sees: Optional[List[str]] = Field(None, max_length=8)
    term_months: Optional[int] = Field(None, ge=0, le=120)
    needs_class: Optional[str] = None
    status: Optional[str] = Field(None, max_length=10)


class _Type(BaseModel):
    type: str = Field(..., max_length=20)
    add: List[str] = Field(default_factory=list, max_length=40)


def _who(session: UserSession) -> Tuple[str, str]:
    user = session.user
    meta = getattr(user, "user_metadata", None) or {}
    name = (meta.get("full_name") or meta.get("name") or getattr(user, "email", "") or "The office")
    return str(user.id), str(name)[:120]


@router.get("/follow-ups")
def follow_ups(business_id: str = Query(...),
               biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
               session: UserSession = Depends(sb_clients.authed_request)):
    """The Follow-up board: everyone a card handed to someone, where they
    are on their path, and every note (church_follow_up.board).

    Pastors-only notes are People & care's guarded part (church_keys): where
    the church named a keeper, everyone else's board says how many there
    are on a card, never what they say. Writing one stays open."""
    out = church_follow_up.board(_uuid(business_id))
    if out is None:
        raise HTTPException(503, "Follow-up couldn't be loaded. Try again in a moment.")
    import church_keys
    if not church_keys.is_open(_uuid(business_id), session.user, "people_care"):
        for card in out["follow_ups"]:
            notes = card.get("notes") or []
            card["notes"] = [n for n in notes if not n.get("pastors_only")]
            card["pastors_notes_locked"] = len(notes) - len(card["notes"])
        out["pastors_only_locked"] = True
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
    """Leaders & roles: the church's role library (each role its title on a
    job, with who holds it and who it answers to), its church type and the
    titles each type uses, its teams, groups, Kids leaders and office
    logins, and each card's path as the engine runs it. The first read
    fills a church's library (church_roles.ensure_library)."""
    out = church_roles.library(biz)
    if out is None:
        raise HTTPException(503, "Your leaders couldn't be loaded. Try again in a moment.")
    return out


def _role_out(biz: Dict[str, Any], role_id: str) -> Dict[str, Any]:
    lib = church_roles.library(biz)
    found = next((r for r in (lib or {}).get("roles") or [] if r["id"] == str(role_id)), None)
    return found or {"id": str(role_id)}


@router.post("/roles")
def role_create(body: _RoleDef, business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    """Make a role: the church's own title on one of the jobs."""
    uid, _name = _who(session)
    if church_roles.ensure_library(biz) is None:
        raise HTTPException(503, "Your roles couldn't be loaded. Try again in a moment.")
    row = church_roles.create_role(biz, body.model_dump(exclude_none=True), by_user=uid)
    return {"ok": True, "role": _role_out(biz, row["id"])}


@router.patch("/roles/{role_id}")
def role_update(role_id: str, body: _RoleDef, business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    changes = body.model_dump(exclude_unset=True)
    row = church_roles.update_role(_uuid(business_id), role_id, changes)
    return {"ok": True, "role": _role_out(biz, row["id"])}


@router.delete("/roles/{role_id}")
def role_archive(role_id: str, business_id: str = Query(...),
                 biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """Archive a role (a draft is deleted). Refused while people hold it."""
    return {"ok": True, **church_roles.archive_role(_uuid(business_id), role_id)}


@router.post("/type")
def church_type(body: _Type, business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    """The church's type (its tradition), and the type's titles to add."""
    uid, _name = _who(session)
    out = church_roles.set_type(biz, body.type, body.add, by_user=uid)
    st = out["settings"]
    tkey = st.get("church_type") or body.type
    return {"ok": True, "added": out["added"],
            "church_type": {"key": tkey, "label": church_roles.TYPES[tkey]["label"],
                            "guessed": st.get("guessed_type") or tkey, "reason": st.get("guess_reason") or "",
                            "set_by": st.get("set_by") or "owner"}}


@router.post("/leaders")
async def leader_add(body: _Role, business_id: str = Query(...),
                     biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                     session: UserSession = Depends(sb_clients.authed_request)):
    """Ask a member to take a role. They get an email with what the role is
    and a link to their member page, where they say yes; the Lead tab
    appears then."""
    import asyncio
    uid, _name = _who(session)
    which = body.role_id or body.role
    if not which:
        raise HTTPException(400, "Pick the role")
    row = await asyncio.to_thread(church_follow_up.add_role, _uuid(business_id), body.contact_id,
                                  which, body.scope, by_user=uid)
    emailed = False
    if not row.get("already"):
        emailed = await church_follow_up.send_invite(biz, row)
    return {"ok": True, "id": str(row.get("id") or ""), "status": row.get("status"),
            "already": bool(row.get("already")), "emailed": emailed}


@router.delete("/leaders/{role_id}")
def leader_remove(role_id: str, business_id: str = Query(...),
                  biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    out = church_follow_up.remove_role(_uuid(business_id), role_id)
    return {"ok": True, "returned_to_office": int(out.get("returned") or 0)}


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


# ─── Sunday check-in (church_checkin) ──────────────────────────────────

class _Checkin(BaseModel):
    enabled: Optional[bool] = None
    weekday: Optional[int] = Field(None, ge=0, le=6)
    start_time: Optional[str] = Field(None, max_length=5)
    timezone: Optional[str] = Field(None, max_length=64)
    opens_before_min: Optional[int] = Field(None, ge=0, le=240)
    closes_after_min: Optional[int] = Field(None, ge=30, le=720)
    title: Optional[str] = Field(None, max_length=80)


@router.get("/checkin")
def checkin_get(business_id: str = Query(...), biz: Dict[str, Any] = Depends(business_access())):
    """Attendance's Sunday check-in panel: the church's service, the member
    link for the welcome-slide code, and this week's count by how people
    were counted. Any seat that reads attendance reads this."""
    return church_checkin.overview(biz)


@router.put("/checkin")
def checkin_put(body: _Checkin, business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    """Turn Sunday check-in on or off, and set the service it opens for."""
    uid, _name = _who(session)
    church_checkin.save_settings(biz, body.model_dump(exclude_unset=True), uid)
    return church_checkin.overview(biz)


# ─── Families and shepherding (church_families, church_shepherding) ───
#
# Kevin, 2026-10-17: every member family has a shepherd, a pastor or an
# elder; visitors stay with Welcome (canvas 31su6kdYmYecH5b2NxjBJN). Chief
# suggests families and proposes who shepherds whom; nothing is saved or
# sent until the office approves. The office's seats only (owner and staff,
# the same as Leaders & roles).

class _FamilyAccept(BaseModel):
    key: Optional[str] = Field(None, max_length=20)
    name: str = Field(..., max_length=120)
    adults: List[str] = Field(default_factory=list, max_length=20)
    children: List[str] = Field(default_factory=list, max_length=20)


class _FamilyKey(BaseModel):
    key: str = Field(..., max_length=20)


class _ShepSettings(BaseModel):
    ministers: Optional[bool] = None
    cap: Optional[int] = Field(None, ge=1, le=40)
    lead_cap: Optional[int] = Field(None, ge=1, le=40)


class _DraftMove(BaseModel):
    unit: str = Field(..., max_length=40)
    shepherd_contact_id: Optional[str] = None


class _FamilyMove(BaseModel):
    household_id: str
    shepherd_contact_id: Optional[str] = None


@router.get("/families/suggestions")
def family_suggestions(business_id: str = Query(...),
                       biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """Families: who Chief thinks lives together, from members not yet in a
    family. Nothing is saved until the office accepts one."""
    out = church_families.suggestions(_uuid(business_id))
    if out is None:
        raise HTTPException(503, "Your members couldn't be loaded. Try again in a moment.")
    return out


@router.post("/families/accept")
def family_accept(body: _FamilyAccept, business_id: str = Query(...),
                  biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    made = church_families.accept(_uuid(business_id), body.model_dump())
    return {"ok": True, "household_id": made["household_id"]}


@router.post("/families/accept-sure")
def family_accept_sure(business_id: str = Query(...),
                       biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    return {"ok": True, "made": church_families.accept_sure(_uuid(business_id))}


@router.post("/families/dismiss")
def family_dismiss(body: _FamilyKey, business_id: str = Query(...),
                   biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    church_families.dismiss(_uuid(business_id), body.key)
    return {"ok": True}


@router.get("/shepherding")
def shepherding(business_id: str = Query(...), biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """Operate → Follow-up → Shepherding: who shepherds, the families each
    has, who is waiting, and the visitors who stay with Welcome."""
    out = church_shepherding.overview(biz)
    if out is None:
        raise HTTPException(503, "Shepherding couldn't be loaded. Try again in a moment.")
    return out


@router.put("/shepherding/settings")
def shepherding_settings(body: _ShepSettings, business_id: str = Query(...),
                         biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                         session: UserSession = Depends(sb_clients.authed_request)):
    uid, _name = _who(session)
    return {"ok": True, "settings": church_shepherding.save_settings(
        _uuid(business_id), body.model_dump(exclude_unset=True), uid)}


@router.post("/shepherding/propose")
def shepherding_propose(business_id: str = Query(...),
                        biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                        session: UserSession = Depends(sb_clients.authed_request)):
    """Chief's proposal for every family waiting for a shepherd, keeping the
    office's own moves. Saved as a draft; nothing is sent."""
    uid, _name = _who(session)
    return church_shepherding.propose(biz, uid)


@router.get("/shepherding/proposal")
def shepherding_proposal(business_id: str = Query(...),
                         biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    return church_shepherding.proposal(biz)


@router.patch("/shepherding/proposal")
def shepherding_proposal_move(body: _DraftMove, business_id: str = Query(...),
                              biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                              session: UserSession = Depends(sb_clients.authed_request)):
    uid, _name = _who(session)
    return church_shepherding.move_in_draft(biz, body.unit, body.shepherd_contact_id, uid)


@router.delete("/shepherding/proposal")
def shepherding_proposal_discard(business_id: str = Query(...),
                                 biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    church_shepherding.discard(biz)
    return {"ok": True}


@router.post("/shepherding/approve")
async def shepherding_approve(business_id: str = Query(...),
                              biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                              session: UserSession = Depends(sb_clients.authed_request)):
    """Write the proposal and email each shepherd their families, once."""
    uid, _name = _who(session)
    out = await asyncio.to_thread(church_shepherding.approve, biz, uid)
    told = 0
    if out["gained"]:
        told = await church_shepherding.tell_shepherds(biz, out["gained"], out["ctx"],
                                                       church_shepherding._iso(church_shepherding._now()))
    return {"ok": True, "placed": out["placed"], "told": told, "failed": out["failed"]}


@router.post("/shepherding/move")
async def shepherding_move(body: _FamilyMove, business_id: str = Query(...),
                           biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE)),
                           session: UserSession = Depends(sb_clients.authed_request)):
    """Give one family to another shepherd (they get an email), or back to
    waiting."""
    uid, _name = _who(session)
    out = await asyncio.to_thread(church_shepherding.move, biz, body.household_id, body.shepherd_contact_id, uid)
    if out["changed"] and out["shepherd"]:
        await church_shepherding.tell_new_shepherd(biz, out["shepherd"], out["name"], out["ctx"])
    return {"ok": True}


@router.get("/shepherding/family/{household_id}")
def shepherding_family(household_id: str, business_id: str = Query(...),
                       biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """A family's shepherd and touches with their notes, for the office.
    The family never reads these."""
    return church_shepherding.office_family(biz, household_id)
