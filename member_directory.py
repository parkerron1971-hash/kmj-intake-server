"""
member_directory.py — the church's member directory, in the member app.

Kevin, 2026-10-27: "member directory is a go sense we have safety room". He
had said no for v1; the member-messaging safety room (messaging_router.py:
the safety officers, held messages, reports) is why it's a yes now. Lane:
Build, under "Love City leaves Subsplash (M-1)" (Subsplash has one).

THE RULES
  · Off until the church turns it on (Settings → Member page → Member
    directory; owner only). While off, /my/directory isn't served.
  · Nobody is listed until they say yes themselves, from My details or the
    directory page's "Show me in the directory".
  · A listed member shows their name and photo (the photo by member_photos'
    rule: an adult by their birthdate). Their phone, their email and their
    household each show only if they turned that one on; all start off.
  · Minors are never listed and never see it: anyone under 18 by birthdate,
    a child on a family (children.contact_id), a teen linked to a parent
    for messaging (msg_guardians), or anyone the office tagged youth/kids.
  · Members only: signed in at this church, and on the records as a member
    (contacts.status active or vip). Never public, never a visitor or lead,
    never another church's people.
  · Reaching someone goes through member messages (/my/messages/to/<id>),
    where the safety officers watch, when the church has messaging on and
    that person can message. Otherwise only what the person chose shows.
  · The office sees who is listed and can take someone out with a reason
    the member sees; that person stays out until the office lets them
    back. Anyone can always take themselves out.

STORAGE (no migration)
  businesses.settings.member_portal.directory = {"on": true}
  contacts.metadata.directory = {"listed", "phone", "email", "household",
                                 "at", "removed": {"reason", "at", "by"}}

ROUTES
  GET  /my/directory (member_portal.serve)   the list, search by name, households together
  POST /my/directory/me                       the member's own choices
  GET  /member-portal/{biz}/directory         the office's view (owner or an admin seat)
  PUT  /member-portal/{biz}/directory         {on}: the church's switch (owner only)
  POST /member-portal/{biz}/directory/remove  {contact_id, reason} (owner or an admin seat)
  POST /member-portal/{biz}/directory/restore {contact_id}
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("member_directory")
router = APIRouter(tags=["member-portal"])

KEY = "directory"
FIELDS = ("phone", "email", "household")
MEMBER_STATUSES = ("active", "vip")
ADULT_AGE = 18
LIST_MAX = 2000
CHUNK = 150
REASON_MAX = 300
QUERY_MAX = 60
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Tags the office uses for a young person. Whole tags only: "Youth leader"
# is an adult.
MINOR_TAGS = {"youth", "kids", "kid", "teen", "teens", "child", "children", "minor", "minors", "under 18",
              "youth member", "kids ministry"}
_PERSON = "id,name,email,phone,birthdate,status,tags,metadata,updated_at"
_LISTED = ("id,name,email,phone,birthdate,status,tags,last_name:metadata->>last_name,"
           "photo:metadata->member_photo,directory:metadata->directory")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── the rules (pure) ────────────────────────────────────────────────


def church_on(biz: Optional[Dict[str, Any]]) -> bool:
    """The church turned its directory on (and its member page is a thing it
    can have)."""
    cfg = ((biz or {}).get("settings") or {}).get("member_portal") or {}
    d = cfg.get(KEY) if isinstance(cfg, dict) else None
    return isinstance(d, dict) and d.get("on") is True


def prefs(person: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A person's own choices, from the `directory` alias the list selects
    or from their metadata. Anything missing or odd is off."""
    person = person or {}
    raw = person.get("directory")
    if raw is None and isinstance(person.get("metadata"), dict):
        raw = person["metadata"].get(KEY)
    raw = raw if isinstance(raw, dict) else {}
    removed = raw.get("removed")
    removed = ({"reason": str(removed.get("reason") or "")[:REASON_MAX], "at": str(removed.get("at") or "")}
               if isinstance(removed, dict) else None)
    out = {"listed": raw.get("listed") is True and removed is None, "removed": removed}
    for f in FIELDS:
        out[f] = raw.get(f) is True
    return out


def is_member(person: Optional[Dict[str, Any]]) -> bool:
    """On the records as a member, not a visitor (lead) or a guest."""
    return str((person or {}).get("status") or "").strip().lower() in MEMBER_STATUSES


def _age(person: Dict[str, Any], today: Optional[date]) -> Optional[int]:
    import member_messaging_rules as rules
    return rules.age(person.get("birthdate"), today)


def is_minor(person: Optional[Dict[str, Any]], flagged: Iterable[str] = (), today: Optional[date] = None) -> bool:
    """Under 18 by a known birthdate, flagged as a child or teen elsewhere
    (`flagged`: on a family as a child, or linked to a parent for
    messaging), or tagged youth/kids by the office."""
    person = person or {}
    if str(person.get("id") or "") in {str(f) for f in flagged}:
        return True
    a = _age(person, today)
    if a is not None and a < ADULT_AGE:
        return True
    tags = person.get("tags")
    if isinstance(tags, list):
        for t in tags:
            if re.sub(r"\s+", " ", str(t or "")).strip().lower() in MINOR_TAGS:
                return True
    return False


def shown(person: Dict[str, Any], flagged: Iterable[str] = (), today: Optional[date] = None) -> bool:
    """Whether this person appears in the directory."""
    return prefs(person)["listed"] and is_member(person) and not is_minor(person, flagged, today)


def viewer_state(me: Optional[Dict[str, Any]], flagged: Iterable[str] = (), today: Optional[date] = None) -> str:
    """'ok' when this signed-in person may see the directory, else why not:
    'minor', 'removed' (the office took them out) or 'not_member'."""
    if not me:
        return "error"
    if is_minor(me, flagged, today):
        return "minor"
    if prefs(me)["removed"]:
        return "removed"
    if not is_member(me):
        return "not_member"
    return "ok"


def entry(person: Dict[str, Any], *, me_id: str, can_message: Set[str]) -> Dict[str, Any]:
    """One person as other members see them. Only what they chose: a field
    they didn't turn on is not in the dict at all."""
    import member_photos as ph
    pid = str(person["id"])
    mine = pid == str(me_id)
    p = prefs(person)
    out: Dict[str, Any] = {
        "id": pid,
        "name": re.sub(r"\s+", " ", str(person.get("name") or "")).strip() or "A member",
        # A photo by member_photos' rule (GET /my/photo re-checks it too).
        "photo": ph.src(person) if (mine or ph.shown_to_members(person)) else "",
        "me": mine,
        "message": (not mine) and pid in can_message,
    }
    if p["phone"] and str(person.get("phone") or "").strip():
        out["phone"] = str(person["phone"]).strip()
    if p["email"] and str(person.get("email") or "").strip():
        out["email"] = str(person["email"]).strip()
    return out


def _surname(person: Dict[str, Any]) -> str:
    import church_families as cf
    return cf.surname({"name": person.get("name") or "", "metadata": {"last_name": person.get("last_name") or ""}})


def cards(people: List[Dict[str, Any]], *, house_of: Dict[str, str], house_names: Dict[str, str],
          me_id: str, can_message: Set[str], q: str = "") -> List[Dict[str, Any]]:
    """The directory's cards, A to Z by last name. People who each turned
    on their household and share one are one card under its name; everyone
    else is their own card. `people` are the ones shown already."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for person in people:
        hid = house_of.get(str(person["id"])) if prefs(person)["household"] else None
        groups.setdefault(f"h:{hid}" if hid else f"p:{person['id']}", []).append(person)
    out = []
    for key, members in groups.items():
        members = sorted(members, key=lambda r: str(r.get("name") or "").casefold())
        together = key.startswith("h:") and len(members) > 1
        title = (house_names.get(key[2:]) or "") if together else ""
        entries = [entry(m, me_id=me_id, can_message=can_message) for m in members]
        out.append({"key": key if together else f"p:{members[0]['id']}",
                    "title": title or (f"The {_surname(members[0])} household" if together else entries[0]["name"]),
                    "household": together, "people": entries,
                    "sort": (_surname(members[0]).casefold() or entries[0]["name"].casefold(),
                             entries[0]["name"].casefold())})
    q = re.sub(r"\s+", " ", str(q or "")).strip().casefold()[:QUERY_MAX]
    if q:
        out = [c for c in out if q in c["title"].casefold() or any(q in p["name"].casefold() for p in c["people"])]
    out.sort(key=lambda c: c["sort"])
    for c in out:
        c.pop("sort", None)
    return out


def clean_reason(raw: Any) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()[:REASON_MAX]


# ─── reads ───────────────────────────────────────────────────────────


def _chunks(ids: Iterable[str]) -> List[str]:
    ids = sorted({str(i) for i in ids if i and UUID.match(str(i))})
    return [",".join(_q(i) for i in ids[i:i + CHUNK]) for i in range(0, len(ids), CHUNK)]


def person(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """One person at this church, {} when they aren't one, None when the
    read failed."""
    if not UUID.match(str(contact_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}&select={_PERSON}&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def _contains(obj: Dict[str, Any]) -> str:
    return _q(json.dumps(obj, separators=(",", ":")))


def listed(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """Everyone at this church who said yes (before the minor and member
    checks), or None."""
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{_q(business_id)}&metadata=cs.{_contains({KEY: {'listed': True}})}"
        f"&select={_LISTED}&order=name.asc&limit={LIST_MAX}")
    return rows if isinstance(rows, list) else None


def flagged(business_id: str, ids: Iterable[str]) -> Optional[Set[str]]:
    """Which of these people are a child on a family or a teen linked to a
    parent; None when a read failed (the directory then doesn't show)."""
    out: Set[str] = set()
    for part in _chunks(ids):
        kids = sb_clients.sb_get_as_service(
            f"/children?business_id=eq.{_q(business_id)}&contact_id=in.({part})&select=contact_id")
        teens = sb_clients.sb_get_as_service(
            f"/msg_guardians?business_id=eq.{_q(business_id)}&teen_contact_id=in.({part})&select=teen_contact_id")
        if not isinstance(kids, list) or not isinstance(teens, list):
            return None
        out |= {str(r["contact_id"]) for r in kids if r.get("contact_id")}
        out |= {str(r["teen_contact_id"]) for r in teens if r.get("teen_contact_id")}
    return out


def households(business_id: str, ids: Iterable[str]) -> Optional[Tuple[Dict[str, str], Dict[str, str]]]:
    """({contact: household}, {household: name}) for these people, or None."""
    house_of: Dict[str, str] = {}
    for part in _chunks(ids):
        rows = sb_clients.sb_get_as_service(
            f"/household_adults?business_id=eq.{_q(business_id)}&contact_id=in.({part})"
            f"&select=household_id,contact_id&order=household_id.asc")
        if not isinstance(rows, list):
            return None
        for r in rows:
            house_of.setdefault(str(r["contact_id"]), str(r["household_id"]))
    names: Dict[str, str] = {}
    for part in _chunks(house_of.values()):
        rows = sb_clients.sb_get_as_service(
            f"/households?business_id=eq.{_q(business_id)}&id=in.({part})&select=id,name")
        if not isinstance(rows, list):
            return None
        names.update({str(r["id"]): re.sub(r"\s+", " ", str(r.get("name") or "")).strip() for r in rows})
    return house_of, names


def messageable(biz: Dict[str, Any], people: List[Dict[str, Any]]) -> Optional[Set[str]]:
    """Who can be reached by member messages: the church has messaging on,
    and the person can message (their switch and a birthdate)."""
    import member_messaging_rules as rules
    import member_portal_messaging as mpm
    if not mpm.turned_on(biz) or not people:
        return set()
    by_id = {str(p["id"]): p for p in people}
    out: Set[str] = set()
    for part in _chunks(by_id):
        rows = sb_clients.sb_get_as_service(
            f"/msg_members?business_id=eq.{_q(biz['id'])}&contact_id=in.({part})&select=contact_id,enabled")
        if not isinstance(rows, list):
            return None
        for r in rows:
            p = by_id.get(str(r["contact_id"]))
            if p and rules.can_message({"enabled": r.get("enabled"), "birthdate": p.get("birthdate")}):
                out.add(str(r["contact_id"]))
    return out


def view(biz: Dict[str, Any], me_id: str, q: str = "", today: Optional[date] = None) -> Dict[str, Any]:
    """What /my/directory shows this member: {state, me, cards, count,
    messaging}. state is 'ok', 'minor', 'removed', 'not_member' or
    'error' (a read failed: nothing shows rather than too much)."""
    b = str(biz["id"])
    me = person(b, me_id)
    rows = listed(b) if me else None
    if not me or rows is None:
        return {"state": "error", "me": prefs(me), "cards": [], "count": 0}
    flags = flagged(b, [r["id"] for r in rows] + [me_id])
    if flags is None:
        return {"state": "error", "me": prefs(me), "cards": [], "count": 0}
    state = viewer_state(me, flags, today)
    if state != "ok":
        return {"state": state, "me": prefs(me), "cards": [], "count": 0}
    people = [r for r in rows if shown(r, flags, today)]
    houses = households(b, [r["id"] for r in people if prefs(r)["household"]])
    reach = messageable(biz, people)
    if houses is None or reach is None:
        return {"state": "error", "me": prefs(me), "cards": [], "count": 0}
    import member_portal_messaging as mpm
    found = cards(people, house_of=houses[0], house_names=houses[1], me_id=str(me_id), can_message=reach, q=q)
    return {"state": "ok", "me": prefs(me), "cards": found, "count": len(people),
            "found": sum(len(c["people"]) for c in found), "messaging": mpm.turned_on(biz),
            "listed_me": any(str(r["id"]) == str(me_id) for r in people)}


# ─── writes ──────────────────────────────────────────────────────────


def _write(business_id: str, contact_id: str, change) -> Optional[str]:
    """Read the person, let `change(row, rec)` return their new directory
    record (or an error code), write it guarded by updated_at (an office
    edit at the same moment isn't lost). The code, or None when it failed."""
    for _ in range(3):
        row = person(business_id, contact_id)
        if row is None:
            return None
        if not row:
            return "gone"
        meta = dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {}
        current = meta.get(KEY) if isinstance(meta.get(KEY), dict) else {}
        made = change(row, dict(current))
        if isinstance(made, str):
            return made
        rec, code = made
        meta[KEY] = rec
        saved = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}"
            f"&updated_at=eq.{_q(row.get('updated_at') or '')}", {"metadata": meta})
        if isinstance(saved, list) and saved:
            return code
    return None


def save_choice(business_id: str, contact_id: str, want: Dict[str, bool]) -> Optional[str]:
    """A member's own yes or no, and what shows. Saying no always works and
    turns every field off; saying yes needs an adult member the office
    hasn't taken out. Returns a flash code (member_portal_church.DONE or
    ERRORS) or None when it didn't save."""
    def change(row, current):
        was = prefs({"directory": current})
        if want.get("listed"):
            fl = flagged(business_id, [contact_id])
            if fl is None:
                return "error"
            if is_minor(row, fl):
                return "dir_adults"
            if was["removed"]:
                return "dir_removed"
            if not is_member(row):
                return "dir_members"
            rec = {"listed": True, **{f: bool(want.get(f)) for f in FIELDS}, "at": _now()}
            return rec, ("dir_saved" if was["listed"] else "dir_on")
        rec = {"listed": False, **{f: False for f in FIELDS}, "at": _now()}
        if isinstance(current.get("removed"), dict):
            rec["removed"] = current["removed"]
        return rec, ("dir_off" if was["listed"] else "dir_saved")
    return _write(business_id, contact_id, change)


def office_remove(business_id: str, contact_id: str, reason: str, by: str) -> Optional[str]:
    def change(row, current):
        return ({"listed": False, **{f: False for f in FIELDS}, "at": _now(),
                 "removed": {"reason": reason, "at": _now(), "by": str(by)}}, "removed")
    return _write(business_id, contact_id, change)


def office_restore(business_id: str, contact_id: str) -> Optional[str]:
    """Let someone back: they aren't listed again until they say yes."""
    def change(row, current):
        return ({"listed": False, **{f: False for f in FIELDS}, "at": _now()}, "restored")
    return _write(business_id, contact_id, change)


# ─── the office ──────────────────────────────────────────────────────


def office_view(biz: Dict[str, Any], *, can_switch: bool) -> Optional[Dict[str, Any]]:
    """Who's listed (and, for anyone listed who doesn't show, why not) and
    who the office took out. None when a read failed."""
    import member_portal_messaging as mpm
    b = str(biz["id"])
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{_q(b)}&metadata=cs.{_contains({KEY: {}})}"
        f"&select=id,name,status,birthdate,tags,directory:metadata->directory&order=name.asc&limit={LIST_MAX}")
    if not isinstance(rows, list):
        return None
    flags = flagged(b, [r["id"] for r in rows])
    if flags is None:
        return None
    on_list, out = [], []
    for r in rows:
        p = prefs(r)
        name = re.sub(r"\s+", " ", str(r.get("name") or "")).strip() or "Someone"
        if p["removed"]:
            out.append({"id": str(r["id"]), "name": name, "reason": p["removed"]["reason"], "at": p["removed"]["at"]})
        elif p["listed"]:
            hidden = "under_18" if is_minor(r, flags) else "" if is_member(r) else "not_member"
            on_list.append({"id": str(r["id"]), "name": name, "shows": [f for f in FIELDS if p[f]],
                            "hidden": hidden})
    return {"ok": True, "on": church_on(biz), "can_switch": can_switch, "messaging": mpm.turned_on(biz),
            "listed": on_list, "removed": out, "shown": sum(1 for x in on_list if not x["hidden"])}


def _business(business_id: str) -> Dict[str, Any]:
    if not UUID.match(str(business_id or "")):
        raise HTTPException(404, "business not found")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Couldn't check that just now. Please try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _office(business_id: str, user: AuthedUser) -> Tuple[Dict[str, Any], bool]:
    """The church and whether the caller owns it. The owner, or an admin
    seat (the office: member_spaces' leaders follow the same rule); anyone
    else is refused with the same 404 business_access gives."""
    biz = _business(business_id)
    if str(biz.get("owner_id")) == str(user.id):
        return biz, True
    import business_access
    business_access.assert_access(business_id, user, "admin")
    return biz, False


def _payload(biz: Dict[str, Any], owner: bool) -> Dict[str, Any]:
    out = office_view(biz, can_switch=owner)
    if out is None:
        raise HTTPException(503, "The directory didn't load. Please try again in a moment.")
    return out


@router.get("/member-portal/{business_id}/directory")
def get_directory(business_id: str, user: AuthedUser = Depends(require_user)):
    biz, owner = _office(business_id, user)
    import member_portal as mp
    if not mp.portal_eligible(biz):
        raise HTTPException(404, "Not Found")
    return _payload(biz, owner)


@router.put("/member-portal/{business_id}/directory")
def switch_directory(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The owner only. {on: bool}. Turning it off takes it out of the
    member app's bar too, so no tab leads nowhere."""
    import member_portal as mp
    on = (body or {}).get("on")
    if not isinstance(on, bool):
        raise HTTPException(400, "on must be true or false")
    biz = mp._require_owner(business_id, user)
    if not mp.portal_eligible(biz):
        raise HTTPException(400, "The member directory is for churches.")
    fresh = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=settings&limit=1")
    if not isinstance(fresh, list) or not fresh:
        raise HTTPException(503, "That change didn't save. Please try again.")
    settings = dict(fresh[0].get("settings") or {})
    cfg = dict(mp.portal_settings(settings))
    cfg[KEY] = {"on": on, "at": _now()}
    if not on and isinstance(cfg.get("tabs"), list) and KEY in cfg["tabs"]:
        import member_app_ui as ui
        keys = ui.clean_tab_keys([k for k in cfg["tabs"] if k != KEY])
        if keys is None or tuple(keys) == ui.DEFAULT_TAB_KEYS:
            cfg.pop("tabs", None)
        else:
            cfg["tabs"] = keys
    settings["member_portal"] = cfg
    saved = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(business_id)}", {"settings": settings})
    if not saved:
        raise HTTPException(503, "That change didn't save. Please try again.")
    return _payload({**biz, "settings": settings}, True)


def _contact_arg(body: Dict[str, Any]) -> str:
    cid = str((body or {}).get("contact_id") or "")
    if not UUID.match(cid):
        raise HTTPException(400, "Choose who.")
    return cid


@router.post("/member-portal/{business_id}/directory/remove")
def remove_from_directory(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """{contact_id, reason}. The reason is shown to the member."""
    cid = _contact_arg(body)
    reason = clean_reason((body or {}).get("reason"))
    if len(reason) < 3:
        raise HTTPException(400, "Say why, in a few words. The member sees it.")
    biz, owner = _office(business_id, user)
    code = office_remove(str(biz["id"]), cid, reason, str(user.id))
    if code == "gone":
        raise HTTPException(404, "That person isn't in this church's records.")
    if code is None:
        raise HTTPException(503, "That didn't save. Please try again.")
    return _payload(biz, owner)


@router.post("/member-portal/{business_id}/directory/restore")
def restore_to_directory(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """{contact_id}. They can list themselves again; nothing is listed for them."""
    cid = _contact_arg(body)
    biz, owner = _office(business_id, user)
    code = office_restore(str(biz["id"]), cid)
    if code == "gone":
        raise HTTPException(404, "That person isn't in this church's records.")
    if code is None:
        raise HTTPException(503, "That didn't save. Please try again.")
    return _payload(biz, owner)


# ─── the member's side ───────────────────────────────────────────────


@router.post("/my/directory/me", include_in_schema=False)
async def save_mine(request: Request):
    """listed=yes|no, phone/email/household=yes, back=/my/details|/my/directory."""
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    back = "/my/details" if str(form.get("back") or "") == "/my/details" else "/my/directory"
    if unavailable:
        return mpc._back(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    if not church_on(church["business"]):
        return mpc._back("/my", err="dir_closed")
    if not mpc._allowed(church, me):
        return mpc._back(back, err="slow")
    want = {"listed": str(form.get("listed") or "") == "yes",
            **{f: str(form.get(f) or "") == "yes" for f in FIELDS}}
    code = await asyncio.to_thread(save_choice, str(church["business"]["id"]), str(me["id"]), want)
    if code in ("dir_on", "dir_saved", "dir_off"):
        return mpc._back(back, done=code)
    return mpc._back(back, err=code if code in ("dir_adults", "dir_removed", "dir_members") else "error")


# ─── pages ───────────────────────────────────────────────────────────

CSS = """
.dir-find{position:relative;margin:16px 0 6px;}
.dir-find .mb-ic{position:absolute;left:15px;top:50%;transform:translateY(-50%);color:var(--fg3);pointer-events:none;}
.dir-find .mp-input{padding-left:44px;}
.dir-count{font-size:13.5px;color:var(--fg2);margin:10px 2px 4px;}
.dir-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;}
.dir-card{background:var(--s1);border-radius:var(--r-md);padding:6px 14px;}
.dir-card h2{font-size:13px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--fg3);margin:10px 0 2px;}
.dir-p{display:flex;align-items:center;gap:12px;padding:10px 0;}
.dir-p + .dir-p{border-top:1px solid var(--s2);}
.dir-p .mb-avatar{width:48px;height:48px;font-size:16px;}
.dir-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.dir-t strong{font-size:16px;font-weight:620;letter-spacing:-.015em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dir-t a{display:inline-flex;align-items:center;gap:6px;min-height:28px;font-size:14px;color:var(--acc);text-decoration:none;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%;}
.dir-t a .mb-ic{flex:none;width:15px;height:15px;}
.dir-t a span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dir-you{font-size:12px;font-weight:650;color:var(--fg3);margin-left:6px;}
.dir-msg{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--acc-soft);color:var(--acc);}
.dir-note{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;color:var(--fg2);margin:22px 2px 0;line-height:1.45;}
.dir-note .mb-ic{flex:none;margin-top:2px;}
.dir-join h2{margin:0 0 6px;font-size:19px;}
.dir-join form{margin-top:12px;}
.dir-me{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14.5px;color:var(--fg2);
  margin:12px 2px 0;}
.dir-me a{color:var(--acc);text-decoration:none;font-weight:600;min-height:44px;display:inline-flex;align-items:center;}
.dir-fields{border:0;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:12px;}
.dir-fields legend{font-size:14px;font-weight:600;color:var(--fg2);margin-bottom:10px;padding:0;}
.dir-fields .mp-check input{flex:none;}
.dir-fields .mp-check small{display:block;color:var(--fg2);font-size:13px;font-weight:400;}
@media (min-width:700px){.dir-list{display:grid;grid-template-columns:1fr 1fr;align-items:start;}}
"""

# Search as you type: the list is already here, so it filters in place; the
# form still works (?q=) without it.
FILTER_JS = """<script>(function(){var f=document.getElementById('dir-q');if(!f)return;
var cards=[].slice.call(document.querySelectorAll('.dir-card')),n=document.getElementById('dir-count'),none=document.getElementById('dir-none');
function run(){var q=f.value.trim().toLowerCase(),seen=0;cards.forEach(function(c){var on=!q||(c.getAttribute('data-names')||'').indexOf(q)>-1;
c.hidden=!on;if(on)seen+=+c.getAttribute('data-n');});if(n)n.textContent=q?(seen+(seen==1?' person':' people')+' found'):n.getAttribute('data-all');
if(none)none.hidden=seen>0||!q;}
f.addEventListener('input',run);f.form.addEventListener('submit',function(e){e.preventDefault();run();f.blur();});})();</script>"""


def _phone_href(phone: str) -> str:
    digits = re.sub(r"(?i)\s*(x|ext\.?)\s*\d+$", "", phone)
    digits = re.sub(r"[^\d+]", "", digits)
    return f"tel:{digits}" if len(re.sub(r'\D', '', digits)) >= 7 else ""


def render_person(p: Dict[str, Any]) -> str:
    import member_app_ui as ui
    from member_portal import _e
    face = (f'<span class="mb-avatar has-photo" aria-hidden="true"><img src="{_e(p["photo"])}" alt="" loading="lazy" '
            f'decoding="async"></span>' if p.get("photo") else
            f'<span class="mb-avatar" aria-hidden="true">{_e(ui.initials(p["name"]))}</span>')
    lines = ""
    if p.get("phone"):
        href = _phone_href(p["phone"])
        lines += (f'<a href="{_e(href)}">{ui.icon("phone", 15)}<span>{_e(p["phone"])}</span></a>' if href
                  else f'<span>{_e(p["phone"])}</span>')
    if p.get("email"):
        lines += f'<a href="mailto:{_e(p["email"])}">{ui.icon("mail", 15)}<span>{_e(p["email"])}</span></a>'
    you = '<span class="dir-you">You</span>' if p.get("me") else ""
    msg = (f'<a class="dir-msg" href="/my/messages/to/{_e(p["id"])}" aria-label="Message {_e(p["name"])}">'
           f'{ui.icon("chat", 20)}</a>' if p.get("message") else "")
    return (f'<div class="dir-p">{face}<span class="dir-t"><strong>{_e(p["name"])}{you}</strong>{lines}</span>'
            f'{msg}</div>')


def render_card(c: Dict[str, Any]) -> str:
    from member_portal import _e
    names = " | ".join([c["title"]] + [p["name"] for p in c["people"]]).lower()
    head = f'<h2>{_e(c["title"])}</h2>' if c.get("household") else ""
    return (f'<li class="dir-card" data-names="{_e(names)}" data-n="{len(c["people"])}">{head}'
            f'{"".join(render_person(p) for p in c["people"])}</li>')


def _join_card(church: str) -> str:
    from member_portal import _e
    return (f'<div class="mp-card dir-join"><h2>Show me in the directory</h2>'
            f'<p class="mp-muted">Members of {_e(church)} will see your name and photo. Your phone, your email and '
            f'your household stay hidden unless you turn each one on.</p>'
            f'<form method="post" action="/my/directory/me"><input type="hidden" name="listed" value="yes">'
            f'<input type="hidden" name="back" value="/my/directory">'
            f'<button class="mp-go" type="submit">Show me in the directory</button></form></div>')


def render_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], v: Dict[str, Any],
                q: str = "") -> Tuple[str, int]:
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    church = (biz.get("name") or "").strip() or "your church"
    top = f'<div class="mb-lt"><h1>Directory</h1></div>{mpc.connect_tabs(biz, "directory")}{mpc._flash(request)}'
    state = v.get("state")
    if state != "ok":
        if state == "minor":
            body = (f'<div class="mp-card"><h2>The directory is for adults</h2><p class="mp-muted">It lists adult members '
                    f'of {_e(church)}. Your groups and your friends there are on Connect.</p>'
                    f'<a class="mp-go mp-go-2" href="/my/groups">Go to Connect</a></div>')
        elif state == "not_member":
            body = (f'<div class="mp-card"><h2>The directory is for members</h2><p class="mp-muted">It lists members of '
                    f'{_e(church)} who chose to be in it. If you\'re a member, ask the church office to mark you '
                    f'as one.</p></div>')
        elif state == "removed":
            reason = (v.get("me") or {}).get("removed", {}).get("reason") or ""
            said = f' They said: “{_e(reason)}”' if reason else ""
            body = (f'<div class="mp-card"><h2>You\'re not in the directory</h2><p class="mp-muted">The church office '
                    f'took you out of the directory.{said}</p><p class="mp-muted">Ask the office if you\'d like to be '
                    f'back in.</p></div>')
        else:
            body = ('<p class="mp-err" role="alert">The directory couldn\'t load just now. Please try again in a '
                    'moment.</p>')
        return (_shell(biz, site, "Directory", f"<style>{CSS}</style>{top}{body}", tab="directory", who=me),
                503 if state == "error" else 200)
    if v.get("listed_me"):
        me_row = (f'<p class="dir-me"><span>You\'re in the directory.</span>'
                  f'<a href="/my/details#directory">Change what shows</a></p>')
    else:
        me_row = _join_card(church)
    count = v.get("count") or 0
    everyone = f'{count} {"person" if count == 1 else "people"}'
    cards_html = "".join(render_card(c) for c in v.get("cards") or [])
    if count == 0:
        listing = (f'<p class="mp-muted" style="margin-top:18px">No one is in the directory yet. '
                   f'{"Be the first: " if not v.get("listed_me") else ""}members show here once they say yes.</p>')
        search = ""
    else:
        found = v.get("found", count)
        shown_now = everyone if not q else f'{found} {"person" if found == 1 else "people"} found'
        search = (f'<form class="dir-find" role="search" method="get" action="/my/directory">'
                  f'{ui.icon("search", 18)}<label class="mp-sr" for="dir-q">Search by name</label>'
                  f'<input class="mp-input" id="dir-q" type="search" name="q" value="{_e(q)}" maxlength="{QUERY_MAX}" '
                  f'placeholder="Search by name" autocomplete="off" enterkeyhint="search"></form>'
                  f'<p class="dir-count" id="dir-count" aria-live="polite" data-all="{_e(everyone)}">{_e(shown_now)}</p>')
        listing = (f'<ul class="dir-list">{cards_html}</ul>'
                   f'<p class="mp-muted" id="dir-none"{"" if q and not cards_html else " hidden"}>No one by that name.</p>')
    reach = ("" if not v.get("messaging") else
             " To reach someone, tap the message button: it goes through member messages, where the church's safety "
             "officers keep watch.")
    note = (f'<p class="dir-note">{ui.icon("lock", 16)}<span>Only signed-in members of {_e(church)} see this. '
            f'Each person here chose to be listed, and chose what shows. Children and teens are never '
            f'listed.{reach}</span></p>')
    body = f'{top}{me_row}{search}{listing}{note}'
    return _shell(biz, site, "Directory", f"<style>{CSS}</style>{body}", tab="directory", who=me,
                  script=FILTER_JS if count else ""), 200


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any]) -> Tuple[str, int]:
    """GET /my/directory, once the church has it on (member_portal checks)."""
    q = re.sub(r"\s+", " ", str(request.query_params.get("q") or "")).strip()[:QUERY_MAX]
    v = await asyncio.to_thread(view, biz, str(me["id"]), q)
    return render_page(biz, site, request, me, v, q)


def details_block(biz: Dict[str, Any], me_id: str) -> str:
    """The directory's part of My details: '' while the church has it off,
    or for someone who can't be in it (a minor, a visitor)."""
    if not church_on(biz):
        return ""
    from member_portal import _e
    me = person(str(biz["id"]), me_id)
    if not me:
        return ""
    fl = flagged(str(biz["id"]), [me_id])
    if fl is None or is_minor(me, fl):
        return ""
    p = prefs(me)
    head = ('<h2 id="directory" style="margin:32px 0 4px">Member directory</h2>'
            '<p class="mb-sub" style="margin-bottom:12px">Signed-in members of the church see who\'s listed. '
            'Nobody else does, and children and teens are never listed.</p>')
    if p["removed"]:
        reason = p["removed"]["reason"]
        said = f' They said: “{_e(reason)}”' if reason else ""
        return (f'{head}<p class="mp-flash" style="margin:0">The church office took you out of the directory.{said} '
                f'Ask the office if you\'d like to be back in.</p>')
    if not is_member(me):
        return ""
    chk = lambda on: " checked" if on else ""
    return (f'{head}<form class="mp-form" method="post" action="/my/directory/me">'
            f'<input type="hidden" name="back" value="/my/details">'
            f'<label class="mp-check"><input type="checkbox" name="listed" value="yes"{chk(p["listed"])}> '
            f'Show me in the directory</label>'
            f'<fieldset class="dir-fields"><legend>Besides your name and photo, show:</legend>'
            f'<label class="mp-check"><input type="checkbox" name="phone" value="yes"{chk(p["phone"])}> '
            f'<span>My phone</span></label>'
            f'<label class="mp-check"><input type="checkbox" name="email" value="yes"{chk(p["email"])}> '
            f'<span>My email</span></label>'
            f'<label class="mp-check"><input type="checkbox" name="household" value="yes"{chk(p["household"])}> '
            f'<span>My household<small>Shows you together with the adults you live with, when they\'re listed '
            f'and chose this too.</small></span></label></fieldset>'
            f'<button class="mp-go mp-go-2" type="submit" style="margin-top:8px">Save directory choices</button>'
            f'</form><style>{CSS}</style>')
