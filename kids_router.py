"""
kids_router.py — families and children, the one door to them.

Kevin, 2026-09-29: attendance first, then families and children's
check-in, then check-in stations. This is the families half: a household
(the adults are contacts the church already knows), its children, who
else may pick them up, and each child's care notes.

The tables (supabase/APPLY-2026-09-29-kids-families.sql) are server-only:
no browser role can read them, so every read and write comes through
here and is checked against the caller's seat on THIS business:

  member and above   families, children, rooms, pickups, allergies —
                     the welcome desk registers a new family on a Sunday
  manager and above  medical and custody notes, and deleting a family or
                     a child (a member can mark a child inactive instead)
  viewer / none      nothing: a child's name is not for every seat

A child is never a contact, so no child reaches an email audience, a
follow-up or Chief's CRM reads.

Every write answers with the saved rows, so the app shows success only
after the database confirmed it. A child's edit carries the updated_at
it was read at; a stale one is refused (409) instead of overwriting
someone else's change.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("kids")

router = APIRouter(prefix="/kids", tags=["kids"])

_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}
DEFAULT_ROOMS = ["Nursery", "Preschool", "Elementary"]
Relationship = Literal["parent", "guardian", "grandparent", "other"]


# ─── Access ──────────────────────────────────────────────────────────

def _uuid(value: str, what: str = "id") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _unavailable() -> HTTPException:
    return HTTPException(503, "Families are temporarily unavailable. Nothing was changed — try again.")


def role_for(business_id: str, user: AuthedUser) -> Optional[str]:
    """The caller's role here. A failed read is an outage (503), never
    'no access' and never 'access' — business_users_router.role_of can't
    tell those apart, so this reads for itself."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id&limit=1")
    if rows is None:
        raise _unavailable()
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) == str(user.id):
        return "owner"
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{business_id}&user_id=eq.{_uuid(user.id, 'user')}"
        f"&status=eq.active&select=role&limit=1")
    if seats is None:
        raise _unavailable()
    return seats[0].get("role") if seats else None


def require(business_id: str, user: AuthedUser, minimum: str) -> str:
    role = role_for(business_id, user)
    if _RANK.get(role or "", 0) < _RANK[minimum]:
        if minimum == "member":
            raise HTTPException(403, "Your seat can't see children's records. Ask the church owner for edit access.")
        raise HTTPException(403, "Only a manager or the owner can do that.")
    return role or ""


def _one(path: str, missing: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise _unavailable()
    if not rows:
        raise HTTPException(404, missing)
    return rows[0]


def _family(business_id: str, household_id: str) -> Dict[str, Any]:
    return _one(f"/households?id=eq.{_uuid(household_id, 'family')}&business_id=eq.{business_id}"
                f"&select=*&limit=1", "That family isn't here any more")


def _child(business_id: str, child_id: str) -> Dict[str, Any]:
    return _one(f"/children?id=eq.{_uuid(child_id, 'child')}&business_id=eq.{business_id}"
                f"&select=*&limit=1", "That child isn't here any more")


def _saved(rows: Any) -> Dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    return rows[0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(s: Optional[str]) -> str:
    return " ".join(str(s or "").split())


# ─── Read ────────────────────────────────────────────────────────────

def _in(ids: List[str]) -> str:
    return ",".join(ids)


@router.get("/families")
def list_families(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    role = require(biz, user, "member")
    private = _RANK[role] >= _RANK["manager"]

    families = sb_clients.sb_get_as_service(
        f"/households?business_id=eq.{biz}&select=id,name,created_at,updated_at&order=name.asc&limit=2000")
    adults = sb_clients.sb_get_as_service(
        f"/household_adults?business_id=eq.{biz}&select=household_id,contact_id,relationship&limit=8000")
    kids = sb_clients.sb_get_as_service(
        f"/children?business_id=eq.{biz}&select=*&order=first_name.asc&limit=8000")
    pickups = sb_clients.sb_get_as_service(
        f"/household_pickups?business_id=eq.{biz}&select=id,household_id,name,phone,relationship"
        f"&order=created_at.asc&limit=8000")
    notes = sb_clients.sb_get_as_service(
        f"/child_care_notes?business_id=eq.{biz}&select=child_id,allergies,medical,custody,updated_at&limit=8000")
    if any(x is None for x in (families, adults, kids, pickups, notes)):
        raise _unavailable()

    people: Dict[str, Dict[str, Any]] = {}
    ids = sorted({str(a["contact_id"]) for a in adults})
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{biz}&id=in.({_in(ids[i:i + 150])})&select=id,name,email,phone")
        if rows is None:
            raise _unavailable()
        people.update({str(r["id"]): r for r in rows})

    by_note = {str(n["child_id"]): n for n in notes}
    out: Dict[str, Dict[str, Any]] = {
        str(f["id"]): {**f, "adults": [], "children": [], "pickups": []} for f in families}
    for a in adults:
        f = out.get(str(a["household_id"]))
        p = people.get(str(a["contact_id"]))
        if f is not None and p is not None:
            f["adults"].append({"contact_id": p["id"], "name": p.get("name") or "",
                                "email": p.get("email") or "", "phone": p.get("phone") or "",
                                "relationship": a.get("relationship") or "parent"})
    for k in kids:
        f = out.get(str(k["household_id"]))
        if f is None:
            continue
        n = by_note.get(str(k["id"]), {})
        child = {key: k.get(key) for key in (
            "id", "first_name", "last_name", "birthdate", "grade", "room", "active", "updated_at")}
        child["allergies"] = n.get("allergies") or ""
        if private:
            child["medical"] = n.get("medical") or ""
            child["custody"] = n.get("custody") or ""
        else:
            # Say THAT there is something to know, never what it is.
            child["has_private_notes"] = bool((n.get("medical") or "").strip() or (n.get("custody") or "").strip())
        f["children"].append(child)
    for p in pickups:
        f = out.get(str(p["household_id"]))
        if f is not None:
            f["pickups"].append({key: p.get(key) for key in ("id", "name", "phone", "relationship")})

    rooms = list(DEFAULT_ROOMS)
    for k in kids:
        r = _clean(k.get("room"))
        if r and r.lower() not in {x.lower() for x in rooms}:
            rooms.append(r)
    return {"role": role, "can_see_private": private, "rooms": rooms, "families": list(out.values())}


# ─── Families ────────────────────────────────────────────────────────

class AdultIn(BaseModel):
    contact_id: str
    relationship: Relationship = "parent"


class FamilyIn(BaseModel):
    business_id: str
    name: str = Field(..., min_length=1, max_length=120)
    adults: List[AdultIn] = Field(default_factory=list, max_length=6)


class FamilyPatch(BaseModel):
    business_id: str
    name: str = Field(..., min_length=1, max_length=120)


def _link_adult(biz: str, household_id: str, contact_id: str, relationship: str) -> Dict[str, Any]:
    cid = _uuid(contact_id, "person")
    _one(f"/contacts?id=eq.{cid}&business_id=eq.{biz}&select=id&limit=1", "That person isn't in Members")
    return _saved(sb_clients.sb_post_as_service(
        "/household_adults?on_conflict=household_id,contact_id",
        {"household_id": household_id, "contact_id": cid, "business_id": biz, "relationship": relationship},
        prefer="return=representation,resolution=merge-duplicates"))


@router.post("/families")
def create_family(body: FamilyIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "member")
    name = _clean(body.name)
    if not name:
        raise HTTPException(400, "Give the family a name")
    for a in body.adults:
        _uuid(a.contact_id, "person")
    fam = _saved(sb_clients.sb_post_as_service("/households", {"business_id": biz, "name": name}))
    try:
        for a in body.adults:
            _link_adult(biz, fam["id"], a.contact_id, a.relationship)
    except HTTPException:
        # All or nothing: a family missing a parent it was created with
        # is worse than no family.
        sb_clients.sb_delete_as_service(f"/households?id=eq.{fam['id']}&business_id=eq.{biz}")
        raise
    return {"family": fam}


@router.patch("/families/{household_id}")
def rename_family(household_id: str, body: FamilyPatch, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "member")
    fam = _family(biz, household_id)
    name = _clean(body.name)
    if not name:
        raise HTTPException(400, "Give the family a name")
    return {"family": _saved(sb_clients.sb_patch_as_service(
        f"/households?id=eq.{fam['id']}&business_id=eq.{biz}", {"name": name, "updated_at": _now()}))}


@router.delete("/families/{household_id}")
def delete_family(household_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "manager")
    fam = _family(biz, household_id)
    if not sb_clients.sb_delete_as_service(f"/households?id=eq.{fam['id']}&business_id=eq.{biz}"):
        raise HTTPException(503, "That didn't delete. Nothing was changed — try again.")
    return {"deleted": fam["id"]}


class AdultPut(BaseModel):
    business_id: str
    relationship: Relationship = "parent"


@router.put("/families/{household_id}/adults/{contact_id}")
def put_adult(household_id: str, contact_id: str, body: AdultPut, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "member")
    fam = _family(biz, household_id)
    return {"adult": _link_adult(biz, fam["id"], contact_id, body.relationship)}


@router.delete("/families/{household_id}/adults/{contact_id}")
def remove_adult(household_id: str, contact_id: str, business_id: str = Query(...),
                 user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "member")
    fam = _family(biz, household_id)
    cid = _uuid(contact_id, "person")
    if not sb_clients.sb_delete_as_service(
            f"/household_adults?household_id=eq.{fam['id']}&contact_id=eq.{cid}&business_id=eq.{biz}"):
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    return {"removed": cid}


# ─── Pickups ─────────────────────────────────────────────────────────

class PickupIn(BaseModel):
    business_id: str
    name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field("", max_length=40)
    relationship: str = Field("", max_length=60)


@router.post("/families/{household_id}/pickups")
def add_pickup(household_id: str, body: PickupIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "member")
    fam = _family(biz, household_id)
    name = _clean(body.name)
    if not name:
        raise HTTPException(400, "Add their name")
    return {"pickup": _saved(sb_clients.sb_post_as_service("/household_pickups", {
        "business_id": biz, "household_id": fam["id"], "name": name,
        "phone": _clean(body.phone), "relationship": _clean(body.relationship)}))}


@router.delete("/pickups/{pickup_id}")
def remove_pickup(pickup_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "member")
    row = _one(f"/household_pickups?id=eq.{_uuid(pickup_id, 'pickup')}&business_id=eq.{biz}&select=id&limit=1",
               "That person isn't on the list any more")
    if not sb_clients.sb_delete_as_service(f"/household_pickups?id=eq.{row['id']}&business_id=eq.{biz}"):
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    return {"removed": row["id"]}


# ─── Children ────────────────────────────────────────────────────────

class ChildFields(BaseModel):
    first_name: Optional[str] = Field(None, max_length=80)
    last_name: Optional[str] = Field(None, max_length=80)
    birthdate: Optional[date] = None
    grade: Optional[str] = Field(None, max_length=20)
    room: Optional[str] = Field(None, max_length=60)
    active: Optional[bool] = None
    allergies: Optional[str] = Field(None, max_length=200)
    medical: Optional[str] = Field(None, max_length=1000)
    custody: Optional[str] = Field(None, max_length=1000)


class ChildIn(ChildFields):
    business_id: str
    household_id: str
    first_name: str = Field(..., min_length=1, max_length=80)


class ChildPatch(ChildFields):
    business_id: str
    # The updated_at the app read; a newer one means someone else saved first.
    expected_updated_at: Optional[str] = None


_CHILD_COLS = ("first_name", "last_name", "grade", "room", "active")


def _child_row(fields: ChildFields) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for key in _CHILD_COLS:
        v = getattr(fields, key)
        if v is not None:
            row[key] = v if isinstance(v, bool) else _clean(v)
    if "birthdate" in fields.model_fields_set:
        b = fields.birthdate
        if b is not None and not (date(1990, 1, 1) <= b <= date.today()):
            raise HTTPException(400, "That birthday isn't a date we can use")
        row["birthdate"] = b.isoformat() if b else None
    if row.get("first_name", "x") == "":
        raise HTTPException(400, "Add the child's first name")
    return row


def _notes_row(fields: ChildFields, role: str) -> Dict[str, Any]:
    notes: Dict[str, Any] = {}
    if fields.allergies is not None:
        notes["allergies"] = _clean(fields.allergies)
    for key in ("medical", "custody"):
        v = getattr(fields, key)
        if v is not None:
            if _RANK[role] < _RANK["manager"]:
                raise HTTPException(403, "Only a manager or the owner can change medical or custody notes.")
            notes[key] = str(v).strip()
    return notes


def _save_notes(biz: str, child_id: str, notes: Dict[str, Any], user: AuthedUser) -> Dict[str, Any]:
    return _saved(sb_clients.sb_post_as_service(
        "/child_care_notes?on_conflict=child_id",
        {"child_id": child_id, "business_id": biz, **notes, "updated_at": _now(), "updated_by": str(user.id)},
        prefer="return=representation,resolution=merge-duplicates"))


@router.post("/children")
def add_child(body: ChildIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    role = require(biz, user, "member")
    fam = _family(biz, body.household_id)
    row = _child_row(body)
    notes = _notes_row(body, role)
    child = _saved(sb_clients.sb_post_as_service(
        "/children", {"business_id": biz, "household_id": fam["id"], **row}))
    if notes:
        try:
            _save_notes(biz, child["id"], notes, user)
        except HTTPException:
            # A child saved without the allergy someone typed is the one
            # outcome worse than not saving: undo and say so.
            sb_clients.sb_delete_as_service(f"/children?id=eq.{child['id']}&business_id=eq.{biz}")
            raise
    return {"child": child}


@router.patch("/children/{child_id}")
def edit_child(child_id: str, body: ChildPatch, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    role = require(biz, user, "member")
    current = _child(biz, child_id)
    row = _child_row(body)
    notes = _notes_row(body, role)
    if not row and not notes:
        return {"child": current}
    # Claim the child first, conditional on the stamp the app read — one
    # atomic write, even when only the notes change (they live in their
    # own table), so two people editing never silently overwrite.
    path = f"/children?id=eq.{current['id']}&business_id=eq.{biz}"
    if body.expected_updated_at:
        path += f"&updated_at=eq.{quote(body.expected_updated_at, safe='')}"
    rows = sb_clients.sb_patch_as_service(path, {**row, "updated_at": _now()})
    if rows is None:
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    if not rows:
        raise HTTPException(409, "Someone else just changed this child's details. Reopen them to see the latest.")
    if notes:
        _save_notes(biz, current["id"], notes, user)
    return {"child": rows[0]}


@router.delete("/children/{child_id}")
def delete_child(child_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "manager")
    current = _child(biz, child_id)
    if not sb_clients.sb_delete_as_service(f"/children?id=eq.{current['id']}&business_id=eq.{biz}"):
        raise HTTPException(503, "That didn't delete. Nothing was changed — try again.")
    return {"deleted": current["id"]}

