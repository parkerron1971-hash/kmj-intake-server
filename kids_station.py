"""
kids_station.py — check-in stations: a PIN-locked tablet and a family
self check-in kiosk.

Kevin, 2026-09-29: "build it all so they can have option as to how they
want to do it." Team seats check children in from the app
(kids_checkin.py). This adds two devices a church can stand in a hallway:

  STAFF STATION  A tablet at the welcome desk. No team login: a volunteer
                 unlocks it with the station's PIN (it locks again after
                 30 minutes) and can then find families, check children in,
                 print tags, and release children at pickup — to someone on
                 the family's list only. A family with a custody note, or a
                 pickup by someone not on the list, needs a manager in the
                 app. The station never sees medical or custody notes.
  SELF KIOSK     Families check themselves in: a parent types their mobile
                 number, taps their children, and the tags print with the
                 code texted to that number. The kiosk cannot search by
                 name, list families, see rooms or release anyone. The PIN
                 only lets a volunteer leave the kiosk.

Pairing: a manager creates a station in the app and gets a one-time,
15-minute code; the tablet opens /station and types it once. The tablet
then holds a random token (only its SHA-256 is stored here). Revoking a
station, or pairing it again, retires that token immediately.

Limits (rate_limit.allow_strict — fail closed, shared across replicas):
pairing attempts per network, PIN attempts per station, and mobile-number
lookups per kiosk, so neither a code nor a family can be guessed.

Every check-in goes through kids_checkin.do_checkin, the same rules a
team seat follows, stamped with the station and method 'station'/'self'.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

import rate_limit
import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_checkin import (
    CODE_ALPHABET, _get, _in, _occasion, _shape, do_checkin, do_lookup, do_release, do_undo, mobile,
)
from kids_router import _clean, _now, _one, _unavailable, _uuid, require

logger = logging.getLogger("kids_station")

router = APIRouter(prefix="/kids", tags=["kids"])

Mode = Literal["staff", "self"]
PAIR_MINUTES = 15
UNLOCK_SECONDS = 30 * 60
PIN_RE = re.compile(r"^\d{4,8}$")
_STATION_COLS = "id,business_id,name,mode,paired_at,last_seen_at,revoked_at,pair_expires_at,created_at"


# ─── Secrets ─────────────────────────────────────────────────────────

def _key(purpose: str, business_id: str) -> bytes:
    from customer_token import derive_key
    return derive_key(purpose, str(business_id))


def pin_hash(business_id: str, station_id: str, pin: str) -> str:
    return hmac.new(_key("station-pin", business_id), f"{station_id}:{pin}".encode(), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pair_hash(code: str) -> str:
    # One platform-wide key: a tablet types the code before anyone knows
    # which church it belongs to.
    return hmac.new(_key("station-pair", "platform"), code.encode(), hashlib.sha256).hexdigest()


def new_pair_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def norm_pair(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:8]


def unlock_token(station: Dict[str, Any], exp: int) -> str:
    # Bound to the device's current token: pairing again or revoking
    # retires every unlock already handed out.
    msg = f"{station['id']}.{exp}.{station.get('token_hash') or ''}"
    sig = hmac.new(_key("station-unlock", station["business_id"]), msg.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def unlock_valid(station: Dict[str, Any], value: Optional[str]) -> bool:
    try:
        exp_s, sig = str(value or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < time.time():
        return False
    return hmac.compare_digest(unlock_token(station, exp), f"{exp}.{sig}")


# ─── The manager's side (in the app) ─────────────────────────────────

class StationIn(BaseModel):
    business_id: str
    name: str = Field(..., min_length=1, max_length=60)
    mode: Mode = "staff"
    pin: str = Field(..., min_length=4, max_length=8)


class StationPatch(BaseModel):
    business_id: str
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    mode: Optional[Mode] = None
    pin: Optional[str] = Field(None, min_length=4, max_length=8)


class BizOnly(BaseModel):
    business_id: str


def _pin_ok(pin: str) -> str:
    if not PIN_RE.match(pin or ""):
        raise HTTPException(400, "The PIN is 4 to 8 digits.")
    return pin


def _issue_pair_code(station_id: str, biz: str) -> Dict[str, Any]:
    for _ in range(5):
        code = new_pair_code()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=PAIR_MINUTES)).isoformat()
        rows = sb_clients.sb_patch_as_service(
            f"/checkin_stations?id=eq.{station_id}&business_id=eq.{biz}",
            {"pair_code_hash": pair_hash(code), "pair_expires_at": expires})
        if rows:
            return {"pair_code": f"{code[:4]}-{code[4:]}", "pair_expires_at": expires}
    raise HTTPException(503, "Couldn't make a pairing code. Try again.")


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {**{k: row.get(k) for k in ("id", "name", "mode", "paired_at", "last_seen_at", "revoked_at", "created_at")},
            "pairing": bool(row.get("pair_expires_at") and str(row["pair_expires_at"]) > now and not row.get("revoked_at"))}


@router.get("/stations")
def list_stations(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "manager")
    rows = _get(f"/checkin_stations?business_id=eq.{biz}&select={_STATION_COLS}&order=created_at.asc&limit=100")
    return {"stations": [_public(r) for r in rows]}


@router.post("/stations")
def create_station(body: StationIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "manager")
    name = _clean(body.name)
    if not name:
        raise HTTPException(400, "Give the station a name, like \"Welcome desk\".")
    pin = _pin_ok(body.pin)
    sid = str(uuid.uuid4())
    rows = sb_clients.sb_post_as_service("/checkin_stations", {
        "id": sid, "business_id": biz, "name": name, "mode": body.mode,
        "pin_hash": pin_hash(biz, sid, pin), "created_by": str(user.id)})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The station didn't save. Try again.")
    return {"station": _public(rows[0]), **_issue_pair_code(sid, biz)}


def _station_for(biz: str, station_id: str) -> Dict[str, Any]:
    return _one(f"/checkin_stations?id=eq.{_uuid(station_id, 'station')}&business_id=eq.{biz}&select=*&limit=1",
                "That station isn't here any more")


@router.post("/stations/{station_id}/pair")
def pair_code_again(station_id: str, body: BizOnly, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "manager")
    st = _station_for(biz, station_id)
    if st.get("revoked_at"):
        raise HTTPException(409, "That station was removed. Add a new one instead.")
    return {"station": _public(st), **_issue_pair_code(st["id"], biz)}


@router.patch("/stations/{station_id}")
def edit_station(station_id: str, body: StationPatch, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business")
    require(biz, user, "manager")
    st = _station_for(biz, station_id)
    patch: Dict[str, Any] = {}
    if body.name is not None:
        if not _clean(body.name):
            raise HTTPException(400, "Give the station a name.")
        patch["name"] = _clean(body.name)
    if body.mode is not None:
        patch["mode"] = body.mode
    if body.pin is not None:
        patch["pin_hash"] = pin_hash(biz, st["id"], _pin_ok(body.pin))
    if not patch:
        return {"station": _public(st)}
    rows = sb_clients.sb_patch_as_service(f"/checkin_stations?id=eq.{st['id']}&business_id=eq.{biz}", patch)
    if not rows:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"station": _public(rows[0])}


@router.delete("/stations/{station_id}")
def revoke_station(station_id: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business")
    require(biz, user, "manager")
    st = _station_for(biz, station_id)
    rows = sb_clients.sb_patch_as_service(
        f"/checkin_stations?id=eq.{st['id']}&business_id=eq.{biz}",
        {"revoked_at": _now(), "token_hash": None, "pair_code_hash": None, "pair_expires_at": None})
    if not rows:
        raise HTTPException(503, "That didn't save. The station still works — try again.")
    return {"station": _public(rows[0])}


# ─── The device's side ───────────────────────────────────────────────

def station_from_token(x_station_token: Optional[str]) -> Dict[str, Any]:
    """The one door for a paired device: the token names exactly one
    station, and the business comes from that row — never from the
    caller. Every station route calls this first (ownership_sweep
    counts it as the ownership check it is)."""
    token = str(x_station_token or "")
    if len(token) < 30:
        raise HTTPException(401, "This station isn't paired. Ask a manager for a pairing code.")
    rows = sb_clients.sb_get_as_service(
        f"/checkin_stations?token_hash=eq.{token_hash(token)}&revoked_at=is.null&select=*&limit=1")
    if rows is None:
        raise _unavailable()
    if not rows:
        raise HTTPException(401, "This station was removed or paired again. Ask a manager for a new pairing code.")
    st = rows[0]
    seen = str(st.get("last_seen_at") or "")
    if not seen or seen < (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat():
        sb_clients.sb_patch_as_service(f"/checkin_stations?id=eq.{st['id']}", {"last_seen_at": _now()})
    return st


def _unlocked(st: Dict[str, Any], x_station_unlock: Optional[str]) -> None:
    if st["mode"] != "staff":
        raise HTTPException(403, "A self check-in kiosk can't do that.")
    if not unlock_valid(st, x_station_unlock):
        raise HTTPException(423, "The station is locked. Enter the PIN to unlock it.")


def _church(biz: str) -> Dict[str, Any]:
    return _one(f"/businesses?id=eq.{biz}&select=id,name&limit=1", "business not found")


def todays_occasions(biz: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """The church's occasions from yesterday to tomorrow — the only ones a
    station may check anyone in to. The device picks today's by its own
    clock; the window covers every timezone's Sunday."""
    from events_rsvp_router import _parse_day, resolve_fields, roster_modules_for
    today = today or datetime.now(timezone.utc).date()
    mods = roster_modules_for(biz)
    if not mods:
        return []
    fields = {str(m["id"]): resolve_fields(m.get("archetype_params")) for m in mods}
    entries = _get(f"/module_entries?business_id=eq.{biz}&module_id=in.({_in(list(fields))})"
                   f"&status=eq.active&select=id,module_id,data&order=created_at.desc&limit=400")
    out = []
    for e in entries:
        f = fields.get(str(e["module_id"]))
        data = e.get("data") or {}
        raw = data.get(f["date_field"]) if f else None
        d = _parse_day(raw)
        if d and abs((d - today).days) <= 1:
            out.append({"id": e["id"], "title": _clean(data.get(f["title_field"])) or "Service",
                        "date": d.isoformat(), "when": raw if isinstance(raw, str) else d.isoformat()})
    return sorted(out, key=lambda o: o["when"])


def _station_occasion(st: Dict[str, Any], entry_id: str) -> Dict[str, Any]:
    eid = _uuid(entry_id, "occasion")
    if not any(o["id"] == eid for o in todays_occasions(st["business_id"])):
        raise HTTPException(403, "A station can only check children in to today's services.")
    return _occasion(st["business_id"], eid)


class PairIn(BaseModel):
    code: str = Field(..., max_length=20)


@router.post("/station/pair")
def pair(body: PairIn, request: Request):
    if not rate_limit.allow_strict("station_pair", rate_limit.client_ip(request)):
        raise HTTPException(429, "Too many tries. Wait a few minutes and try again.")
    code = norm_pair(body.code)
    if len(code) != 8:
        raise HTTPException(400, "The pairing code is 8 letters and numbers, like ABCD-EFGH.")
    rows = sb_clients.sb_get_as_service(
        f"/checkin_stations?pair_code_hash=eq.{pair_hash(code)}&revoked_at=is.null&select=*&limit=1")
    if rows is None:
        raise _unavailable()
    now = datetime.now(timezone.utc).isoformat()
    if not rows or not rows[0].get("pair_expires_at") or str(rows[0]["pair_expires_at"]) < now:
        raise HTTPException(404, "That code didn't work. Codes last 15 minutes and work once — ask a manager for a new one.")
    st = rows[0]
    token = secrets.token_urlsafe(32)
    # Conditional on the code still being this one, so two tablets typing
    # the same code can't both walk away with a working token.
    saved = sb_clients.sb_patch_as_service(
        f"/checkin_stations?id=eq.{st['id']}&pair_code_hash=eq.{st['pair_code_hash']}",
        {"token_hash": token_hash(token), "pair_code_hash": None, "pair_expires_at": None,
         "paired_at": _now(), "last_seen_at": _now()})
    if not saved:
        raise HTTPException(409, "That code was just used. Ask a manager for a new one.")
    church = _church(st["business_id"])
    return {"token": token, "station": {"id": st["id"], "name": st["name"], "mode": st["mode"]},
            "church": church.get("name") or ""}


@router.get("/station/me")
def me(x_station_token: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    church = _church(st["business_id"])
    return {"station": {"id": st["id"], "name": st["name"], "mode": st["mode"]},
            "church": church.get("name") or "", "occasions": todays_occasions(st["business_id"])}


class PinIn(BaseModel):
    pin: str = Field(..., max_length=12)


@router.post("/station/unlock")
def unlock(body: PinIn, x_station_token: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    if not rate_limit.allow_strict("station_pin", st["id"]):
        raise HTTPException(429, "Too many wrong PINs. The station is locked for 15 minutes — or a manager can reset the PIN.")
    if not hmac.compare_digest(pin_hash(st["business_id"], st["id"], str(body.pin or "")), st["pin_hash"]):
        raise HTTPException(403, "That PIN isn't right.")
    exp = int(time.time()) + UNLOCK_SECONDS
    return {"unlock": unlock_token(st, exp), "expires_at": datetime.fromtimestamp(exp, timezone.utc).isoformat()}


# ─── Staff station (unlocked) ────────────────────────────────────────

@router.get("/station/families")
def station_families(q: str = Query(..., max_length=60), x_station_token: Optional[str] = Header(None),
                     x_station_unlock: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _unlocked(st, x_station_unlock)
    biz = st["business_id"]
    t = _clean(q).lower()
    digits = re.sub(r"\D", "", q)
    if len(t) < 2:
        return {"families": []}
    fams = _get(f"/households?business_id=eq.{biz}&select=id,name&limit=2000")
    kids = _get(f"/children?business_id=eq.{biz}&active=eq.true&select=id,household_id,first_name,last_name,birthdate,grade,room&limit=8000")
    links = _get(f"/household_adults?business_id=eq.{biz}&select=household_id,contact_id,relationship&limit=8000")
    ids = sorted({str(l["contact_id"]) for l in links})
    people: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 150):
        people.update({str(c["id"]): c for c in _get(
            f"/contacts?business_id=eq.{biz}&id=in.({_in(ids[i:i + 150])})&select=id,name,phone")})
    notes = {str(n["child_id"]): n.get("allergies") or "" for n in _get(
        f"/child_care_notes?business_id=eq.{biz}&select=child_id,allergies&limit=8000")}
    out = []
    for f in fams:
        fk = [k for k in kids if str(k["household_id"]) == str(f["id"])]
        if not fk:
            continue
        fa = [(l, people.get(str(l["contact_id"]))) for l in links if str(l["household_id"]) == str(f["id"])]
        fa = [(l, p) for l, p in fa if p]
        names = [f["name"], *[p.get("name") or "" for _, p in fa], *[f"{k.get('first_name') or ''} {k.get('last_name') or ''}" for k in fk]]
        hit = any(t in n.lower() for n in names) or (
            len(digits) >= 4 and any(re.sub(r"\D", "", mobile(p.get("phone")) or "").endswith(digits) for _, p in fa))
        if not hit:
            continue
        out.append({
            "id": f["id"], "name": f["name"],
            # A station shows the last four digits only, to confirm the text goes to the right phone.
            "adults": [{"contact_id": p["id"], "name": p.get("name") or "", "relationship": l.get("relationship") or "parent",
                        "phone_last4": (re.sub(r"\D", "", mobile(p.get("phone")))[-4:] if mobile(p.get("phone")) else "")}
                       for l, p in fa],
            "children": [{**{k2: k.get(k2) for k2 in ("id", "first_name", "last_name", "birthdate", "grade", "room")},
                          "allergies": notes.get(str(k["id"]), "")} for k in fk],
        })
        if len(out) >= 8:
            break
    return {"families": out}


@router.get("/station/checkins")
def station_checkins(entry_id: str = Query(...), x_station_token: Optional[str] = Header(None),
                     x_station_unlock: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _unlocked(st, x_station_unlock)
    entry = _station_occasion(st, entry_id)
    rows = _get(f"/child_checkins?business_id=eq.{st['business_id']}&entry_id=eq.{entry['id']}"
                f"&select=*&order=checked_in_at.asc&limit=2000")
    return {"checkins": _shape(rows, st["business_id"], False)}


class StationKid(BaseModel):
    child_id: str
    room: str = Field("", max_length=60)


class StationCheckinIn(BaseModel):
    entry_id: str
    household_id: str
    children: List[StationKid] = Field(..., min_length=1, max_length=20)
    dropped_off_by: Optional[str] = None
    text_code: bool = False


@router.post("/station/checkin")
async def station_checkin(body: StationCheckinIn, x_station_token: Optional[str] = Header(None),
                          x_station_unlock: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _unlocked(st, x_station_unlock)
    entry = _station_occasion(st, body.entry_id)
    return await do_checkin(st["business_id"], entry, body.household_id,
                            [(k.child_id, k.room) for k in body.children], body.dropped_off_by,
                            body.text_code, "station", None, False, station_id=st["id"])


@router.delete("/station/checkins/{checkin_id}")
def station_undo(checkin_id: str, x_station_token: Optional[str] = Header(None),
                 x_station_unlock: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _unlocked(st, x_station_unlock)
    return do_undo(st["business_id"], checkin_id)


class StationLookupIn(BaseModel):
    entry_id: str
    code: str = Field(..., max_length=12)


@router.post("/station/checkout/lookup")
def station_lookup(body: StationLookupIn, x_station_token: Optional[str] = Header(None),
                   x_station_unlock: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _unlocked(st, x_station_unlock)
    return do_lookup(st["business_id"], _station_occasion(st, body.entry_id), body.code, False)


class StationReleaseIn(BaseModel):
    entry_id: str
    code: str = Field(..., max_length=12)
    checkin_ids: List[str] = Field(..., min_length=1, max_length=20)
    released_to: str = Field(..., min_length=1, max_length=120)


@router.post("/station/checkout")
def station_release(body: StationReleaseIn, x_station_token: Optional[str] = Header(None),
                    x_station_unlock: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _unlocked(st, x_station_unlock)
    # A station is never a manager: custody families and anyone not on
    # the list go to a manager in the app.
    return do_release(st["business_id"], _station_occasion(st, body.entry_id), body.code,
                      body.checkin_ids, body.released_to, False, None)


# ─── Self check-in kiosk ─────────────────────────────────────────────

class SelfFindIn(BaseModel):
    phone: str = Field(..., max_length=40)


NOT_FOUND = "We couldn't find your family with that number. Please check in at the welcome desk."


def _family_by_phone(biz: str, phone: str) -> Optional[Dict[str, Any]]:
    """The one household whose adult has this mobile. None when there is
    no match or more than one (a shared number goes to the desk)."""
    digits = re.sub(r"\D", "", mobile(phone))[-10:]
    if len(digits) != 10:
        return None
    candidates = _get(f"/contacts?business_id=eq.{biz}&phone=like.*{digits[-4:]}*&select=id,name,phone&limit=200")
    matched = [c for c in candidates if re.sub(r"\D", "", mobile(c.get("phone")))[-10:] == digits]
    if not matched:
        return None
    links = _get(f"/household_adults?business_id=eq.{biz}&contact_id=in.({_in([c['id'] for c in matched])})"
                 f"&select=household_id,contact_id")
    homes = {str(l["household_id"]) for l in links}
    if len(homes) != 1:
        return None
    link = next(l for l in links if str(l["household_id"]) in homes)
    adult = next(c for c in matched if str(c["id"]) == str(link["contact_id"]))
    fam = _one(f"/households?id=eq.{link['household_id']}&business_id=eq.{biz}&select=id,name&limit=1", NOT_FOUND)
    return {"family": fam, "adult": adult}


def _self_only(st: Dict[str, Any]) -> None:
    if st["mode"] != "self":
        raise HTTPException(403, "This station is set up for the welcome team, not self check-in.")


@router.post("/station/self/find")
def self_find(body: SelfFindIn, x_station_token: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _self_only(st)
    if not rate_limit.allow_strict("station_self_find", st["id"]):
        raise HTTPException(429, "Please check in at the welcome desk.")
    biz = st["business_id"]
    found = _family_by_phone(biz, body.phone)
    if not found:
        raise HTTPException(404, NOT_FOUND)
    fam = found["family"]
    kids = _get(f"/children?business_id=eq.{biz}&household_id=eq.{fam['id']}&active=eq.true"
                f"&select=id,first_name,room&order=first_name.asc")
    if not kids:
        raise HTTPException(404, NOT_FOUND)
    # First names and rooms only: whoever types a number sees no more
    # than a name tag would show.
    return {"family": fam["name"], "household_id": fam["id"],
            "adult_first_name": (found["adult"].get("name") or "").split(" ")[0],
            "children": [{"id": k["id"], "first_name": k["first_name"], "room": k.get("room") or ""} for k in kids]}


class SelfCheckinIn(BaseModel):
    entry_id: str
    phone: str = Field(..., max_length=40)
    child_ids: List[str] = Field(..., min_length=1, max_length=20)


@router.post("/station/self/checkin")
async def self_checkin(body: SelfCheckinIn, x_station_token: Optional[str] = Header(None)):
    st = station_from_token(x_station_token)
    _self_only(st)
    if not rate_limit.allow_strict("station_self_find", st["id"]):
        raise HTTPException(429, "Please check in at the welcome desk.")
    biz = st["business_id"]
    found = _family_by_phone(biz, body.phone)
    if not found:
        raise HTTPException(404, NOT_FOUND)
    entry = _station_occasion(st, body.entry_id)
    result = await do_checkin(biz, entry, found["family"]["id"], [(c, "") for c in body.child_ids],
                              found["adult"]["id"], True, "self", None, False, station_id=st["id"])
    # The kiosk prints the tags, so it needs names, rooms and allergies —
    # never who dropped them off or any flag beyond the allergy.
    for c in result["checkins"]:
        c.pop("dropped_off_by", None)
        c.pop("custody_alert", None)
    return result
