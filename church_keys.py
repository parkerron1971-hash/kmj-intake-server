"""church_keys.py — Church Areas, step 2: keepers and keys.

Kevin, 2026-10-23: "if Pastor look at money another leader is notified and
have to recieve a code from that person to get into money". The artifact
"Church Areas and Keys" (7YRKpKa9g2DdFU9mm3WD8L), step 2; his picks on
2026-10-26: the lock binds the owner too, the keeper taps yes with a code
as the backup, and a yes opens the area for one hour.

    a KEEPER ...... someone the church names to keep a guarded area: the
                    treasurer keeps Giving, a pastor keeps Care, the kids
                    director keeps Kids. An area with no keeper has no lock,
                    so naming the first keeper is what turns it on
    a KEY ......... one person's ask to get into an area they don't keep.
                    Every keeper hears it (a phone alert and an email). A
                    keeper taps yes, or reads out the 6-digit code that came
                    with the alert. The asker never counts as their own yes.
                    Open for KEY_MINUTES; an ask with no answer lapses after
                    ASK_HOURS, and silence never opens anything. The
                    church's outside accountant, who has no seat, asks for
                    Giving's key the same way
    the WALL ...... wall() / is_open(): what each guarded door calls. Only
                    the guarded part of an area is behind it (who gave what,
                    the bank, payouts; medical and custody notes;
                    pastors-only notes and prayer). Totals stay open
    a CHANGE ...... naming or removing a keeper. A keeper's change, or the
                    first keeper of an area, counts at once. Anyone else's
                    waits CHANGE_DAYS, told to the keepers, unless a keeper
                    says yes first (or no, which cancels it): otherwise an
                    owner could name themselves, or take the keepers away,
                    to get in

  GET  /church/keys?business_id=             the guarded areas, their keepers,
                                             my keys, and what waits on me
  POST /church/keys/ask                      {business_id, area, reason}
  POST /church/keys/{id}/answer              {business_id, yes}       a keeper
  POST /church/keys/{id}/code                {business_id, code}      the asker
  PUT  /church/keepers                       {business_id, area, user_id, keep}  an admin
  POST /church/keepers/answer                {business_id, area, user_id, yes}   a keeper

Every read that fails is a 503, never "no keeper" (which would open the
lock) and never "locked" for someone who keeps the area. Switched by
CHURCH_KEYS: off | owner | on (owner until a Thursday). Off takes every
lock away; owner shows the routes to the platform owner, and to the logins
and accountants of the platform owner's own churches, while a church that
has keepers stays locked either way. (2026-11-01: owner used to show them
to the platform owner's email alone, so a treasurer the Giving keeper had
locked out at Love City couldn't even ask for a key.)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

GUARDED = ("people_care", "giving_money", "kids_youth")
KEY_MINUTES = 60
ASK_HOURS = 24
CHANGE_DAYS = 7
CODE_TRIES = 5
REASON_MAX = 300


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_KEYS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


def platform_church(business_id: str) -> bool:
    """Whether the platform owner owns this business (chief_of_staff.
    PLATFORM_OWNER_ID, the same "owner" as giving_deposits'): where an owner
    switch opens the key routes to everyone with a login there, since its
    locks are already live. A read that fails is a 503, never a yes."""
    rows = _need(f"/businesses?id=eq.{_q(business_id)}&select=owner_id&limit=1")
    if not rows or not rows[0].get("owner_id"):
        return False
    from chief_of_staff import PLATFORM_OWNER_ID
    return str(rows[0]["owner_id"]) == str(PLATFORM_OWNER_ID)


def _gate(user: AuthedUser, business_id: Optional[str] = None) -> None:
    if open_to(user):
        return
    if mode() == "owner" and business_id and platform_church(business_id):
        return
    raise HTTPException(404, "Not Found")


# ─── Reads ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _at(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The keys couldn't be read just now. Try again.")
    return rows


def _area(area: Any) -> str:
    if area not in GUARDED:
        raise HTTPException(400, "That area has nothing locked in it.")
    return str(area)


def _label(area: str) -> str:
    import church_areas
    return church_areas.AREAS[area]["label"]


def _keeper_rows(biz: str, area: Optional[str] = None) -> List[Dict[str, Any]]:
    one = f"&area=eq.{_q(area)}" if area else ""
    return _need(f"/church_keepers?business_id=eq.{_q(biz)}{one}"
                 "&select=area,user_id,added_by,added_at,starts_at,ends_at&limit=200")


def _active(row: Dict[str, Any], now: datetime) -> bool:
    starts, ends = _at(row.get("starts_at")), _at(row.get("ends_at"))
    return bool(starts and starts <= now and (ends is None or ends > now))


def active_keepers(biz: str, area: str, rows: Optional[List[Dict[str, Any]]] = None) -> Set[str]:
    now = _now()
    return {str(r["user_id"]) for r in (rows if rows is not None else _keeper_rows(biz, area))
            if r.get("area") == area and _active(r, now)}


def _open_key(biz: str, user_id: str, area: str) -> Optional[Dict[str, Any]]:
    rows = _need(f"/church_area_keys?business_id=eq.{_q(biz)}&user_id=eq.{_q(user_id)}&area=eq.{_q(area)}"
                 f"&status=eq.open&opens_until=gt.{_q(_iso(_now()))}&select=id,opens_until"
                 "&order=opens_until.desc&limit=1")
    return rows[0] if rows else None


# ─── The wall ─────────────────────────────────────────────────────────

def opened(business_id: str, user: AuthedUser, area: str) -> Optional[bool]:
    """None where the area has no lock (no keeper, or the switch is off);
    else whether this person keeps it or holds an open key. For a door
    whose rule changes once an area is kept (Care's inbox: the owner sees
    every request until the church names a keeper, then the keepers do)."""
    if mode() == "off" or area not in GUARDED:
        return None
    biz = str(business_id)
    keepers = active_keepers(biz, area)
    if not keepers:
        return None
    return str(user.id) in keepers or _open_key(biz, str(user.id), area) is not None


def is_open(business_id: str, user: AuthedUser, area: str) -> bool:
    """Whether this person may see the guarded part of an area now: always
    where the area has no keeper (or the switch is off), else for its
    keepers and for anyone holding an open key. The owner too."""
    return opened(business_id, user, area) is not False


def wall(business_id: str, user: AuthedUser, area: str) -> None:
    """403 {code: area_locked} unless the area is open to this person."""
    if not is_open(business_id, user, area):
        raise HTTPException(403, {
            "code": "area_locked", "area": area,
            "message": f"{_label(area)} is locked. Ask its keeper for a key: it opens for an hour once they say yes."})


# ─── People ───────────────────────────────────────────────────────────

def _business(biz: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _seats(biz: str) -> Dict[str, Dict[str, Any]]:
    return {str(r["user_id"]): r for r in _need(
        f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&select=user_id,role,invited_email&limit=500")
        if r.get("user_id")}


def _people(biz: str) -> Dict[str, Dict[str, Any]]:
    """The seats, and the church's outside accountants (business_collaborators):
    an accountant sees who gave what (giving_records.require_finance), so the
    Giving keeper's lock holds them too, and they ask for a key like anyone.
    Only for naming and telling: an accountant is never a keeper. A failed
    read of the accountants only costs a name."""
    seats = _seats(biz)
    rows = sb_clients.sb_get_as_service(
        f"/business_collaborators?business_id=eq.{_q(biz)}&status=eq.active&role=eq.accountant"
        "&select=user_id,invited_email&limit=50")
    outside = {str(r["user_id"]): {**r, "role": "accountant"}
               for r in (rows if isinstance(rows, list) else []) if r.get("user_id")}
    return {**outside, **seats}


def _outside(uid: str, owner_id: Any, people: Dict[str, Dict[str, Any]]) -> bool:
    """Neither the owner nor a seat: the routes only let an outside
    accountant this far, even when their row couldn't be read for a name."""
    return str(uid) != str(owner_id) and (people.get(str(uid)) or {}).get("role") in (None, "accountant")


def _who(uid: str, owner_id: Any, seats: Dict[str, Dict[str, Any]]) -> str:
    if str(uid) == str(owner_id):
        return "The owner"
    return (seats.get(str(uid)) or {}).get("invited_email") or "Someone who left"


def _email_of(uid: str, owner_id: Any, seats: Dict[str, Dict[str, Any]]) -> str:
    if str(uid) != str(owner_id):
        return str((seats.get(str(uid)) or {}).get("invited_email") or "").strip()
    try:
        import messaging_router
        return messaging_router._owner_email(str(uid))
    except Exception:
        return ""


def _later(fn: Callable[[], None]) -> None:
    """Alerts go off the request: a slow email never holds up an answer."""
    threading.Thread(target=fn, daemon=True).start()


def _tell(biz: Dict[str, Any], to: Set[str], title: str, body: str,
          seats: Dict[str, Dict[str, Any]], tag: str) -> None:
    """A phone alert and an email to each person; one that fails never stops
    the rest."""
    def run() -> None:
        import asyncio
        import push_notifications
        for uid in sorted(to):
            try:
                push_notifications.send_to_user(uid, title=title, body=body[:160], nav="operate:areas",
                                                tag=tag, business_id=str(biz["id"]))
            except Exception:
                logger.warning("church keys: a phone alert failed", exc_info=True)
            email = _email_of(uid, biz.get("owner_id"), seats)
            if "@" not in email:
                continue
            try:
                import app_base
                import email_sender
                asyncio.run(email_sender.send_via_resend(
                    to_email=email, to_name=None,
                    from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                    from_name=biz.get("name") or "Your church", subject=title[:150], reply_to=None,
                    business_id=str(biz["id"]), idempotency_key=f"{tag}-{uid}",
                    body=f"{title}\n\n{body}\n\nAnswer it here:\n{app_base.app_base_url()}/?nav=operate:areas\n"))
            except Exception:
                logger.warning("church keys: an email failed", exc_info=True)
    _later(run)


# ─── Keys ─────────────────────────────────────────────────────────────

def _hash(key_id: str, code: str) -> str:
    return hashlib.sha256(f"{key_id}:{code}".encode()).hexdigest()


def _lapsed(row: Dict[str, Any]) -> bool:
    asked = _at(row.get("asked_at"))
    return not asked or asked <= _now() - timedelta(hours=ASK_HOURS)


def _key(biz: str, key_id: str) -> Dict[str, Any]:
    rows = _need(f"/church_area_keys?id=eq.{_q(_uuid(key_id, 'key'))}&business_id=eq.{_q(biz)}"
                 "&select=id,area,user_id,reason,status,asked_at,opens_until,code_hash,code_tries&limit=1")
    if not rows:
        raise HTTPException(404, "That ask isn't here.")
    return rows[0]


def _set(row: Dict[str, Any], fields: Dict[str, Any], *, was: str = "asked") -> Dict[str, Any]:
    """Change an ask only from the state it was read in: two keepers
    answering at once, or a code and a tap together, settle once."""
    got = sb_clients.sb_patch_as_service(
        f"/church_area_keys?id=eq.{_q(row['id'])}&status=eq.{was}", fields)
    if not isinstance(got, list):
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone answered this one already.")
    return got[0]


def _shown(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: row.get(k) for k in ("id", "area", "status", "reason", "asked_at", "opens_until")}


def ask(business_id: str, user: AuthedUser, area: str, reason: str) -> Dict[str, Any]:
    biz = _business(business_id)
    keepers = active_keepers(biz["id"], area)
    me = str(user.id)
    if not keepers:
        raise HTTPException(409, f"{_label(area)} has no keeper, so nothing in it is locked.")
    if me in keepers:
        raise HTTPException(409, f"You keep {_label(area)}, so it's open to you.")
    already = _open_key(biz["id"], me, area)
    if already:
        return {"key": {**already, "area": area, "status": "open"}, "told": 0}
    seats = _people(biz["id"])
    if _outside(me, biz.get("owner_id"), seats) and area != "giving_money":
        raise HTTPException(400, "An accountant's key is for Giving & money.")
    waiting = [r for r in _need(
        f"/church_area_keys?business_id=eq.{_q(biz['id'])}&user_id=eq.{_q(me)}&area=eq.{_q(area)}"
        "&status=eq.asked&select=id,area,status,reason,asked_at,opens_until&order=asked_at.desc&limit=5")
        if not _lapsed(r)]
    if waiting:
        # One ask at a time: asking again doesn't ring the keepers twice.
        return {"key": _shown(waiting[0]), "told": 0}
    key_id, code = str(uuid.uuid4()), f"{secrets.randbelow(10 ** 6):06d}"
    saved = sb_clients.sb_post_as_service("/church_area_keys", {
        "id": key_id, "business_id": biz["id"], "area": area, "user_id": me,
        "reason": " ".join(str(reason or "").split())[:REASON_MAX], "code_hash": _hash(key_id, code)})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "Your ask didn't save. Try again.")
    who, why = _who(me, biz.get("owner_id"), seats), saved[0].get("reason")
    _tell(biz, keepers, f"{who} asks for a key to {_label(area)}",
          (f"“{why}” " if why else "") + f"Open the app to say yes or no, or read them this code: {code}. "
          f"A yes opens it for an hour.", seats, tag=f"key-{key_id}")
    return {"key": _shown(saved[0]), "told": len(keepers)}


def answer(business_id: str, user: AuthedUser, key_id: str, yes: bool) -> Dict[str, Any]:
    biz = _business(business_id)
    row = _key(biz["id"], key_id)
    me = str(user.id)
    if me not in active_keepers(biz["id"], row["area"]):
        raise HTTPException(403, f"Only a keeper of {_label(row['area'])} answers this.")
    if str(row["user_id"]) == me:
        raise HTTPException(403, "Nobody answers their own ask.")
    if row["status"] != "asked":
        raise HTTPException(409, "Someone answered this one already.")
    if _lapsed(row):
        _set(row, {"status": "expired"})
        raise HTTPException(410, "This ask ran out. They can ask again.")
    now = _now()
    fields: Dict[str, Any] = {"status": "open" if yes else "declined", "answered_by": me,
                              "answered_at": _iso(now), "how": "tap"}
    if yes:
        fields["opens_until"] = _iso(now + timedelta(minutes=KEY_MINUTES))
    saved = _set(row, fields)
    seats = _people(biz["id"])
    _tell(biz, {str(row["user_id"])},
          f"Your key to {_label(row['area'])} is {'open for an hour' if yes else 'not given this time'}",
          f"{_who(me, biz.get('owner_id'), seats)} {'said yes' if yes else 'said no'}.", seats,
          tag=f"key-{row['id']}-answer")
    return {"key": _shown(saved)}


def enter_code(business_id: str, user: AuthedUser, key_id: str, code: str) -> Dict[str, Any]:
    biz = _business(business_id)
    row = _key(biz["id"], key_id)
    if str(row["user_id"]) != str(user.id):
        raise HTTPException(403, "Only the person who asked enters the code.")
    if row["status"] != "asked":
        raise HTTPException(409, "This ask is already answered.")
    if _lapsed(row):
        _set(row, {"status": "expired"})
        raise HTTPException(410, "This ask ran out. Ask again for a new code.")
    tries = int(row.get("code_tries") or 0)
    given = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not row.get("code_hash") or not hmac.compare_digest(_hash(row["id"], given), str(row["code_hash"])):
        tries += 1
        _set(row, {"code_tries": tries, **({"status": "closed"} if tries >= CODE_TRIES else {})})
        if tries >= CODE_TRIES:
            raise HTTPException(403, "That code isn't right, and that was the last try. Ask again for a new one.")
        raise HTTPException(400, f"That code isn't right. {CODE_TRIES - tries} tries left.")
    now = _now()
    saved = _set(row, {"status": "open", "answered_at": _iso(now), "how": "code",
                       "opens_until": _iso(now + timedelta(minutes=KEY_MINUTES))})
    keepers = active_keepers(biz["id"], row["area"])
    seats = _people(biz["id"])
    _tell(biz, keepers, f"{_who(str(user.id), biz.get('owner_id'), seats)} opened {_label(row['area'])} with a code",
          "A keeper's code opened it for an hour. If nobody gave them that code, close it from the app.",
          seats, tag=f"key-{row['id']}-code")
    return {"key": _shown(saved)}


# ─── Keepers ──────────────────────────────────────────────────────────

def put_keeper(business_id: str, user: AuthedUser, area: str, target: str, keep: bool) -> Dict[str, Any]:
    biz = _business(business_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Keys are for churches")
    rows = _keeper_rows(biz["id"], area)
    keepers = active_keepers(biz["id"], area, rows)
    me = str(user.id)
    seats = _seats(biz["id"])
    if keep and target != str(biz.get("owner_id")) and target not in seats:
        raise HTTPException(400, "A keeper has to be the owner or someone with an office login.")
    # The first keeper, or a keeper's own change, counts at once.
    now = _now()
    when = now if (me in keepers or not keepers) else now + timedelta(days=CHANGE_DAYS)
    mine = next((r for r in rows if str(r["user_id"]) == target), None)
    if keep:
        keeping = bool(mine and _active(mine, now))
        if keeping and not mine.get("ends_at"):
            return {"keeper": mine, "waits_until": None}
        if keeping:
            # Calling off their removal keeps a keeper; it opens nothing.
            when = now
        saved = sb_clients.sb_post_as_service(
            "/church_keepers?on_conflict=business_id,area,user_id",
            {"business_id": biz["id"], "area": area, "user_id": target, "added_by": me, "added_at": _iso(now),
             "starts_at": mine["starts_at"] if keeping else _iso(when), "ends_at": None},
            prefer="resolution=merge-duplicates,return=representation")
    else:
        if not mine:
            raise HTTPException(404, "They don't keep this area.")
        if not _active(mine, now):
            # Taking back an addition that hasn't started opens nothing.
            gone = sb_clients.sb_delete_as_service(
                f"/church_keepers?business_id=eq.{_q(biz['id'])}&area=eq.{_q(area)}&user_id=eq.{_q(target)}")
            if gone is None or gone is False:
                raise HTTPException(503, "That didn't save. Try again.")
            return {"keeper": None, "waits_until": None}
        saved = sb_clients.sb_patch_as_service(
            f"/church_keepers?business_id=eq.{_q(biz['id'])}&area=eq.{_q(area)}&user_id=eq.{_q(target)}",
            {"ends_at": _iso(when)})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    waits = when > now
    if waits:
        name = _who(target, biz.get("owner_id"), seats)
        _tell(biz, keepers, f"{_who(me, biz.get('owner_id'), seats)} wants to "
              f"{'add' if keep else 'remove'} a keeper of {_label(area)}",
              f"{name} {'becomes' if keep else 'stops being'} a keeper on {when:%b} {when.day} "
              "unless a keeper says no in the app. A keeper's yes makes it happen now.",
              seats, tag=f"keeper-{area}-{target}-{int(now.timestamp())}")
    return {"keeper": saved[0], "waits_until": _iso(when) if waits else None}


def answer_change(business_id: str, user: AuthedUser, area: str, target: str, yes: bool) -> Dict[str, Any]:
    biz = _business(business_id)
    rows = _keeper_rows(biz["id"], area)
    me = str(user.id)
    if me not in active_keepers(biz["id"], area, rows):
        raise HTTPException(403, f"Only a keeper of {_label(area)} answers this.")
    now = _now()
    mine = next((r for r in rows if str(r["user_id"]) == target), None)
    adding = bool(mine and not _active(mine, now))
    removing = bool(mine and _active(mine, now) and _at(mine.get("ends_at")) and _at(mine["ends_at"]) > now)
    if not (adding or removing):
        raise HTTPException(404, "Nothing is waiting on that keeper.")
    where = f"/church_keepers?business_id=eq.{_q(biz['id'])}&area=eq.{_q(area)}&user_id=eq.{_q(target)}"
    if adding:
        saved = (sb_clients.sb_patch_as_service(where, {"starts_at": _iso(now)}) if yes
                 else sb_clients.sb_delete_as_service(where))
    else:
        saved = sb_clients.sb_patch_as_service(where, {"ends_at": _iso(now) if yes else None})
    if saved is None or saved is False or saved == []:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True, "change": "adding" if adding else "removing", "yes": yes}


# ─── What one person sees ─────────────────────────────────────────────

def overview(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    biz = _business(business_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Keys are for churches")
    import church_areas
    me, now = str(user.id), _now()
    rows, seats = _keeper_rows(biz["id"]), _people(biz["id"])
    # An outside accountant only ever needs Giving's key.
    outside = _outside(me, biz.get("owner_id"), seats)
    # An ask answered at the end of its day is a key for an hour after.
    since = now - timedelta(hours=ASK_HOURS, minutes=KEY_MINUTES)
    asks = [a for a in _need(f"/church_area_keys?business_id=eq.{_q(biz['id'])}&status=in.(asked,open)"
                             f"&asked_at=gt.{_q(_iso(since))}"
                             "&select=id,area,user_id,reason,status,asked_at,opens_until&order=asked_at.desc&limit=200")
            if a["status"] == "open" or not _lapsed(a)]
    areas, waiting = [], []
    for area in (("giving_money",) if outside else GUARDED):
        keep = active_keepers(biz["id"], area, rows)
        people = []
        for r in rows:
            if r.get("area") != area:
                continue
            ends = _at(r.get("ends_at"))
            if ends and ends <= now:
                continue
            pending = "adding" if not _active(r, now) else ("removing" if ends else None)
            people.append({"user_id": str(r["user_id"]), "who": _who(str(r["user_id"]), biz.get("owner_id"), seats),
                           "pending": pending, "on": r["starts_at"] if pending == "adding" else r.get("ends_at")})
        mine = [a for a in asks if a["area"] == area and str(a["user_id"]) == me]
        key = next((a for a in mine if a["status"] == "open" and (_at(a.get("opens_until")) or now) > now), None)
        asked = next((a for a in mine if a["status"] == "asked"), None)
        areas.append({"area": area, "label": church_areas.AREAS[area]["label"],
                      "guarded": church_areas.AREAS[area]["guarded"], "locked": bool(keep), "keepers": people,
                      "me": {"keeper": me in keep, "open_until": key["opens_until"] if key else None,
                             "asked": _shown(asked) if asked else None}})
        if me in keep:
            waiting += [{**_shown(a), "who": _who(str(a["user_id"]), biz.get("owner_id"), seats)}
                        for a in asks if a["area"] == area and a["status"] == "asked" and str(a["user_id"]) != me]
    return {"enabled": True, "areas": areas, "waiting": waiting}


# ─── Routes ───────────────────────────────────────────────────────────

def _member(business_id: Any, user: AuthedUser, minimum: str = "member", accountant: bool = False) -> str:
    try:
        biz = _uuid(business_id, "business")
    except HTTPException:
        _gate(user)            # a switch closed to them is a 404 whatever they send
        raise
    # Who has a login here is asked next, so "owner" opens the platform
    # owner's churches to their own people and accountants, nobody else.
    _gate(user, biz)
    try:
        business_access.assert_access(biz, user, minimum)
    except HTTPException as e:
        # A seatless outside accountant still sees who gave what, so they
        # see their key and ask for it; they never answer one.
        import business_collaborators_router
        if not (accountant and e.status_code == 404
                and business_collaborators_router.is_active_accountant(biz, str(user.id))):
            raise
    return biz


@router.get("/keys")
def keys_overview(business_id: str, user: AuthedUser = Depends(require_user)):
    return overview(_member(business_id, user, accountant=True), user)


@router.post("/keys/ask")
def keys_ask(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _member(body.get("business_id"), user, accountant=True)
    return ask(biz, user, _area(body.get("area")), str(body.get("reason") or ""))


@router.post("/keys/{key_id}/answer")
def keys_answer(key_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _member(body.get("business_id"), user)
    return answer(biz, user, key_id, body.get("yes") is True)


@router.post("/keys/{key_id}/code")
def keys_code(key_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _member(body.get("business_id"), user, accountant=True)
    return enter_code(biz, user, key_id, str(body.get("code") or ""))


@router.put("/keepers")
def keepers_put(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _member(body.get("business_id"), user, "admin")
    return put_keeper(biz, user, _area(body.get("area")), _uuid(body.get("user_id"), "person"),
                      body.get("keep") is not False)


@router.post("/keepers/answer")
def keepers_answer(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _member(body.get("business_id"), user)
    return answer_change(biz, user, _area(body.get("area")), _uuid(body.get("user_id"), "person"),
                         body.get("yes") is True)
