"""
kids_checkin.py — children's check-in and pickup.

Kevin, 2026-09-29: pickup security is BOTH — a code on screen that is
texted to the parent, AND printed name tags. This is the server half:

  CHECK IN   A family's children go into their rooms for one occasion.
             The server makes one pickup code for the family at that
             occasion (four characters, no look-alikes), texts it to the
             adult who brought them if asked, and answers with everything
             the app needs to print the tags. Checking a sibling in later
             reuses the family's code.
  PICK UP    The team types the code from the parent's tag or text. The
             answer lists the children still in, and who may take them:
             the family's adults and its pickup list. Releasing records who
             they went home with.

Seats (kids_router.require): member+ checks in and out. A child whose
family has a custody note is released by a manager or the owner only,
and only managers read the note itself — everyone else is told to fetch
one. A team member releases only to someone on the family's list; a
manager may release to someone else by name.

The code text goes straight to the carrier from the church's line (as the
member page's sign-in code does), never through send_sms_core, so no code
sits in the church's text history. A STOP is honoured. The reply says
plainly whether the text went, and nothing is claimed that didn't happen.
"""
from __future__ import annotations

import logging
import re
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import (
    _RANK, _clean, _now, _one, _unavailable, _uuid, require,
)

logger = logging.getLogger("kids_checkin")

router = APIRouter(prefix="/kids", tags=["kids"])

# No 0/O, 1/I/L, 2/Z, 5/S, 8/B: a code read aloud across a noisy hallway
# or squinted at on a tag is never ambiguous.
CODE_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
CODE_RE = re.compile(r"^[A-Z0-9]{4}$")


def new_code(taken: set) -> str:
    for _ in range(50):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        if code not in taken:
            return code
    raise HTTPException(503, "Couldn't make a pickup code. Try again.")


def norm_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:4]


def mobile(phone: Any) -> str:
    """E.164 for texting, or "". An extension the office typed ("x2")
    would otherwise ride along as extra digits and break the number."""
    import sms_service
    raw = re.split(r"(?i)\s*(?:x|ext\.?|extension)\s*\d", str(phone or ""))[0]
    return sms_service.normalize_phone(re.sub(r"[^\d+]", "", raw))


def masked(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else ""


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise _unavailable()
    return rows


def _occasion(biz: str, entry_id: str) -> Dict[str, Any]:
    return _one(f"/module_entries?id=eq.{_uuid(entry_id, 'occasion')}&business_id=eq.{biz}"
                f"&select=id,data&limit=1", "That service or event isn't here any more")


def _title(entry: Dict[str, Any]) -> str:
    data = entry.get("data") or {}
    return _clean(data.get("title") or data.get("name") or "") or "Service"


def _in(ids: List[str]) -> str:
    return ",".join(sorted({str(i) for i in ids}))


def _shape(rows: List[Dict[str, Any]], biz: str, private: bool) -> List[Dict[str, Any]]:
    """Check-in rows joined to the child, their allergies and whether
    their family has a custody note (the note itself for managers only)."""
    if not rows:
        return []
    kids = {str(k["id"]): k for k in _get(
        f"/children?business_id=eq.{biz}&id=in.({_in([r['child_id'] for r in rows])})"
        f"&select=id,first_name,last_name,birthdate,household_id")}
    family_kids = _get(f"/children?business_id=eq.{biz}&household_id=in.({_in([r['household_id'] for r in rows])})"
                       f"&select=id,household_id")
    notes = {str(n["child_id"]): n for n in _get(
        f"/child_care_notes?business_id=eq.{biz}&child_id=in.({_in([k['id'] for k in family_kids] or ['00000000-0000-0000-0000-000000000000'])})"
        f"&select=child_id,allergies,custody")}
    custody_by_family: Dict[str, List[str]] = {}
    for k in family_kids:
        c = (notes.get(str(k["id"]), {}).get("custody") or "").strip()
        if c:
            custody_by_family.setdefault(str(k["household_id"]), []).append(c)
    adults = [r["dropped_off_by"] for r in rows if r.get("dropped_off_by")]
    names = {str(c["id"]): c.get("name") or "" for c in _get(
        f"/contacts?business_id=eq.{biz}&id=in.({_in(adults)})&select=id,name")} if adults else {}
    out = []
    for r in rows:
        k = kids.get(str(r["child_id"]), {})
        custody = custody_by_family.get(str(r["household_id"]), [])
        item = {
            "id": r["id"], "child_id": r["child_id"], "household_id": r["household_id"],
            "first_name": k.get("first_name") or "", "last_name": k.get("last_name") or "",
            "birthdate": k.get("birthdate"), "room": r.get("room") or "", "code": r["code"],
            "allergies": (notes.get(str(r["child_id"]), {}).get("allergies") or ""),
            "custody_alert": bool(custody),
            "dropped_off_by": names.get(str(r.get("dropped_off_by") or ""), ""),
            "checked_in_at": r["checked_in_at"], "checked_out_at": r.get("checked_out_at"),
            "released_to": r.get("released_to"),
        }
        if private and custody:
            item["custody"] = "\n".join(custody)
        out.append(item)
    return out


# ─── Who's in ────────────────────────────────────────────────────────

@router.get("/checkins")
def list_checkins(business_id: str = Query(...), entry_id: str = Query(...),
                  user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    role = require(biz, user, "member")
    entry = _occasion(biz, entry_id)
    rows = _get(f"/child_checkins?business_id=eq.{biz}&entry_id=eq.{entry['id']}"
                f"&select=*&order=checked_in_at.asc&limit=2000")
    return {"role": role, "can_see_private": _RANK[role] >= _RANK["manager"],
            "occasion": {"id": entry["id"], "title": _title(entry)},
            "checkins": _shape(rows, biz, _RANK[role] >= _RANK["manager"])}


# ─── Check in ────────────────────────────────────────────────────────

class KidIn(BaseModel):
    child_id: str
    room: str = Field("", max_length=60)


class CheckinIn(BaseModel):
    business_id: str
    entry_id: str
    household_id: str
    children: List[KidIn] = Field(..., min_length=1, max_length=20)
    dropped_off_by: Optional[str] = None
    text_code: bool = False


async def text_code(biz: Dict[str, Any], phone: str, code: str, names: List[str]) -> str:
    """'sent' | 'opted_out' | 'unavailable' | 'failed'. Straight to the
    carrier: a live pickup code never sits in the church's text history."""
    church = _clean(biz.get("name")) or "Your church"
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
    body = (f"{church}: {who} {'is' if len(names) == 1 else 'are'} checked in. "
            f"Pickup code {code}. Show this code to pick up. Reply STOP to opt out.")
    try:
        import httpx
        import sms_service
        import twilio_sms
        from starlette.concurrency import run_in_threadpool
        if not sms_service._twilio_configured():
            return "unavailable"
        async with httpx.AsyncClient() as client:
            if await sms_service.is_opted_out(client, phone, str(biz["id"])):
                return "opted_out"
            sender = await sms_service.sender_for(client, str(biz["id"]))
        await run_in_threadpool(twilio_sms.send_sms, phone, body, from_number=sender)
        return "sent"
    except Exception as e:
        logger.warning("pickup code text failed (%s) for business %s", type(e).__name__, biz.get("id"))
        return "failed"


@router.post("/checkin")
async def check_in(body: CheckinIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    role = require(biz, user, "member")
    entry = _occasion(biz, body.entry_id)
    fam = _one(f"/households?id=eq.{_uuid(body.household_id, 'family')}&business_id=eq.{biz}"
               f"&select=id,name&limit=1", "That family isn't here any more")
    kids = {str(k["id"]): k for k in _get(
        f"/children?business_id=eq.{biz}&household_id=eq.{fam['id']}&active=eq.true&select=id,first_name,room")}
    wanted: Dict[str, str] = {}
    for k in body.children:
        cid = _uuid(k.child_id, "child")
        if cid not in kids:
            raise HTTPException(404, "One of those children isn't in this family any more. Reopen the family.")
        wanted[cid] = _clean(k.room) or _clean(kids[cid].get("room"))

    adult: Optional[Dict[str, Any]] = None
    if body.dropped_off_by:
        aid = _uuid(body.dropped_off_by, "person")
        link = _get(f"/household_adults?household_id=eq.{fam['id']}&contact_id=eq.{aid}&select=contact_id&limit=1")
        if not link:
            raise HTTPException(400, "That person isn't one of this family's adults.")
        adult = _one(f"/contacts?id=eq.{aid}&business_id=eq.{biz}&select=id,name,phone&limit=1",
                     "That person isn't in Members any more")

    existing = _get(f"/child_checkins?business_id=eq.{biz}&entry_id=eq.{entry['id']}&select=child_id,household_id,code,checked_out_at")
    # A sibling checked in later shares the family's code while any of
    # them is still in.
    code = next((r["code"] for r in existing if str(r["household_id"]) == str(fam["id"]) and not r.get("checked_out_at")), None)
    if not code:
        code = new_code({r["code"] for r in existing})
    already = {str(r["child_id"]): r for r in existing}
    gone_home = [kids[c]["first_name"] for c in wanted if c in already and already[c].get("checked_out_at")]
    if gone_home:
        raise HTTPException(409, f"{', '.join(gone_home)} already went home from this one.")
    new_rows = [{
        "business_id": biz, "entry_id": entry["id"], "child_id": c, "household_id": fam["id"],
        "room": room, "code": code, "dropped_off_by": adult["id"] if adult else None,
        "method": "staff", "checked_in_by": str(user.id),
    } for c, room in wanted.items() if c not in already]
    if new_rows:
        saved = sb_clients.sb_post_as_service("/child_checkins", new_rows)
        if not isinstance(saved, list) or len(saved) != len(new_rows):
            raise HTTPException(503, "The check-in didn't save. Nobody was checked in — try again.")

    rows = _get(f"/child_checkins?business_id=eq.{biz}&entry_id=eq.{entry['id']}"
                f"&child_id=in.({_in(list(wanted))})&select=*&order=checked_in_at.asc")
    checkins = _shape(rows, biz, _RANK[role] >= _RANK["manager"])
    code = checkins[0]["code"] if checkins else code

    texted, texted_to = "off", ""
    if body.text_code:
        phone = mobile(adult.get("phone")) if adult else ""
        if not adult:
            texted = "no_adult"
        elif not phone:
            texted = "no_mobile"
        else:
            church = _one(f"/businesses?id=eq.{biz}&select=id,name&limit=1", "business not found")
            texted = await text_code(church, phone, code, [kids[c]["first_name"] for c in wanted])
            texted_to = masked(phone)
    if adult:
        # The parent was here today; Home's care queue reads this.
        sb_clients.sb_patch_as_service(f"/contacts?id=eq.{adult['id']}&business_id=eq.{biz}",
                                       {"last_interaction": _now()})
    return {"code": code, "family": fam["name"], "occasion": _title(entry),
            "checkins": checkins, "texted": texted, "texted_to": texted_to}


@router.delete("/checkins/{checkin_id}")
def undo_checkin(checkin_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "member")
    row = _one(f"/child_checkins?id=eq.{_uuid(checkin_id, 'check-in')}&business_id=eq.{biz}"
               f"&select=id,checked_out_at&limit=1", "That check-in isn't here any more")
    if row.get("checked_out_at"):
        raise HTTPException(409, "They've already gone home, so the check-in stays on the record.")
    if not sb_clients.sb_delete_as_service(f"/child_checkins?id=eq.{row['id']}&business_id=eq.{biz}&checked_out_at=is.null"):
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    return {"removed": row["id"]}


# ─── Pick up ─────────────────────────────────────────────────────────

class LookupIn(BaseModel):
    business_id: str
    entry_id: str
    code: str = Field(..., max_length=12)


def _pickup_list(biz: str, household_id: str) -> List[Dict[str, Any]]:
    links = _get(f"/household_adults?household_id=eq.{household_id}&business_id=eq.{biz}&select=contact_id,relationship")
    people = {str(c["id"]): c for c in _get(
        f"/contacts?business_id=eq.{biz}&id=in.({_in([l['contact_id'] for l in links])})&select=id,name,phone")} if links else {}
    allowed = [{"name": people[str(l["contact_id"])].get("name") or "", "relationship": l.get("relationship") or "parent",
                "phone": people[str(l["contact_id"])].get("phone") or "", "kind": "adult"}
               for l in links if str(l["contact_id"]) in people]
    allowed += [{"name": p["name"], "relationship": p.get("relationship") or "", "phone": p.get("phone") or "", "kind": "pickup"}
                for p in _get(f"/household_pickups?household_id=eq.{household_id}&business_id=eq.{biz}&select=name,relationship,phone")]
    return allowed


def _waiting(biz: str, entry_id: str, code: str) -> List[Dict[str, Any]]:
    return _get(f"/child_checkins?business_id=eq.{biz}&entry_id=eq.{entry_id}&code=eq.{code}"
                f"&checked_out_at=is.null&select=*&order=checked_in_at.asc")


@router.post("/checkout/lookup")
def lookup(body: LookupIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    role = require(biz, user, "member")
    entry = _occasion(biz, body.entry_id)
    code = norm_code(body.code)
    if not CODE_RE.match(code):
        raise HTTPException(400, "A pickup code is four letters and numbers.")
    rows = _waiting(biz, entry["id"], code)
    if not rows:
        raise HTTPException(404, "No child is waiting with that code. Check the tag, or look them up in the room list.")
    household_id = str(rows[0]["household_id"])
    fam = _one(f"/households?id=eq.{household_id}&business_id=eq.{biz}&select=id,name&limit=1", "That family isn't here any more")
    private = _RANK[role] >= _RANK["manager"]
    children = _shape(rows, biz, private)
    custody = any(c["custody_alert"] for c in children)
    return {"code": code, "family": fam["name"], "children": children,
            "allowed": _pickup_list(biz, household_id), "custody_alert": custody,
            "can_release": private or not custody, "can_release_to_anyone": private}


class ReleaseIn(BaseModel):
    business_id: str
    entry_id: str
    code: str = Field(..., max_length=12)
    checkin_ids: List[str] = Field(..., min_length=1, max_length=20)
    released_to: str = Field(..., min_length=1, max_length=120)


@router.post("/checkout")
def release(body: ReleaseIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    role = require(biz, user, "member")
    manager = _RANK[role] >= _RANK["manager"]
    entry = _occasion(biz, body.entry_id)
    code = norm_code(body.code)
    if not CODE_RE.match(code):
        raise HTTPException(400, "A pickup code is four letters and numbers.")
    waiting = {str(r["id"]): r for r in _waiting(biz, entry["id"], code)}
    ids = [_uuid(i, "check-in") for i in body.checkin_ids]
    missing = [i for i in ids if i not in waiting]
    if missing:
        raise HTTPException(409, "Someone on that list has already gone home, or the code doesn't match. Look the code up again.")
    household_id = str(waiting[ids[0]]["household_id"])
    children = _shape([waiting[i] for i in ids], biz, manager)
    if any(c["custody_alert"] for c in children) and not manager:
        raise HTTPException(403, "This family has a custody note. A manager or the owner needs to release these children.")
    to = _clean(body.released_to)
    allowed = {a["name"].strip().lower() for a in _pickup_list(biz, household_id) if a["name"].strip()}
    if to.lower() not in allowed and not manager:
        raise HTTPException(403, f"{to} isn't on this family's pickup list. A manager or the owner can release to someone else.")
    rows = sb_clients.sb_patch_as_service(
        f"/child_checkins?business_id=eq.{biz}&entry_id=eq.{entry['id']}&code=eq.{code}"
        f"&id=in.({_in(ids)})&checked_out_at=is.null",
        {"checked_out_at": _now(), "checked_out_by": str(user.id), "released_to": to})
    if rows is None:
        raise HTTPException(503, "That didn't save. Nobody was released — try again.")
    if len(rows) != len(ids):
        # Someone else released one of them a moment ago.
        raise HTTPException(409, "Someone else just released one of these children. Look the code up again.")
    return {"released": [r["id"] for r in rows], "released_to": to}
