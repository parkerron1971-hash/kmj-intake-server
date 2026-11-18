"""Private care intake never enters marketing/AI pipelines.

The inbox can act as well as read: a request moves new -> reviewed ->
closed, can be marked prayed, carries private notes (ministry_care_notes),
and the owner can hand one to a teammate, who then sees that request and
no other (care_access). Everything here is written as the service, after
that check, because the browser has no grant on either table.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from urllib.parse import quote
import sb_clients

STATUSES = ("new", "reviewed", "closed")
NOTE_MAX = 4000
_FIELDS = ("id,created_at,status,submission,contact_id,prayed_at,status_changed_at,"
           "assigned_to,assigned_at")
# How a request went through the prayer team (church_prayer,
# APPLY-2026-10-17-church-role-library.sql): read with the rest when the
# columns are there, and left out (the list still loads) when they aren't.
_PRAYER_FIELDS = (",prayer_team,wants_call,needs_pastor,leader_contact_id,leader_role,leader_prayed_at,leader_noted_at,"
                  "leader_assigned_at,leader_due_at,leader_late_level")
_LEGACY_FIELDS = "id,created_at,status,submission"
# A hand-off to an office login: its heads-up and due time (care_handoff,
# APPLY-2026-11-18-care-login-due.sql). Read first when they're there; the
# reads fall back to the ones above when they aren't.
_LOGIN_FIELDS = ",assigned_due_at,assigned_told_at,assigned_acted_at,assigned_late_level"

def needs_private_care(form, data):
    settings = form.get("settings") or {}
    answer = str(data.get("confidential", "")).strip().lower()
    # Prayer is sensitive by default, even when someone leaves the question blank.
    return (answer in ("yes", "true", "1", "on")
            or settings.get("private_care") is True
            or "prayer" in str(form.get("name", "")).lower()
            or any(str(k).lower() in ("prayer_request", "pastoral_care") and v for k, v in data.items()))

def save_submission(business_id, form_id, data):
    """A private care form. A form that asks "may our prayer team pray with
    you?" (a field named prayer_team) shares the request when the person
    said yes; everything else stays with the owner, as always."""
    import church_prayer
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": business_id, "form_id": form_id, "submission": data,
        "status": "new", **church_prayer.consent_columns(data or {}),
    })
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "Your private request could not be saved. Please retry.")
    church_prayer.on_new(str(business_id), rows[0])
    return {"success": True, "contact_id": None, "queued": False,
            "private": True, "message": "Your request was saved privately for the ministry owner."}

def require_owner(business_id, user):
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}&select=id,owner_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Private care is temporarily unavailable")
    if not rows or str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "Private care requests are available only to the business owner")


def _uuid(value: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── who may see what ────────────────────────────────────────────────
#
# Kevin, 2026-10-14: others should be able to see prayer requests. The
# owner still sees every request and decides who else sees each one: a
# request handed to a teammate (assigned_to = their user id) is visible to
# that teammate, and only that one. A seat with nothing handed to it sees
# an empty inbox, never a count of what it can't see.

#
# Kevin, 2026-11-01 (Love City's office checkup): the People & Care login
# works the care board, so it also sees what people agreed to share with
# the prayer team. A request kept private, or one that needs a pastor
# (church_prayer.consent_columns never shares those), stays with the
# owner or the People & care keeper, who can still hand it over.

class CareCaller:
    def __init__(self, user_id: str, owner: bool, shared: bool = False):
        self.user_id = str(user_id)
        self.owner = owner
        self.shared = bool(shared) and not owner

    @property
    def scope(self) -> str:
        if self.owner:
            return "all"
        return "shared" if self.shared else "assigned"


# What a People & care login sees beyond what was handed to it: requests
# the person agreed to share with the prayer team, never one that needs a
# pastor. A PostgREST `or=` body, beside `assigned_to.eq.<them>`.
SHARED = "and(prayer_team.is.true,needs_pastor.is.false)"


def _works_care(biz: str, user_id: str, role: Optional[str]) -> bool:
    """Whether this church login's own areas name People & care (picked by
    the church, or Chief's guess from their roles). The owner and Admins
    see the whole church in the menu, but a care request is the pastor's
    unless it was shared, so "the whole church" doesn't count here; only
    an area that names People & care does. Not a church, the switch off,
    or a failed read: no."""
    if not role or role == "owner":
        return False
    try:
        import church_areas
        view = church_areas.my_areas(biz, str(user_id), role)
    except Exception:
        return False
    areas = (view or {}).get("areas")
    return isinstance(areas, list) and "people_care" in areas


def care_access(business_id: str, user) -> CareCaller:
    """The owner, or an active seat on this business. Anyone else: 403.

    Who sees every request (Church Areas step 2, church_keys): the owner,
    until the church names a keeper for People & care; from then on that
    keeper, and anyone holding their key, the owner included. A church
    login that works People & care also sees the requests shared with the
    prayer team. Everyone else sees what was handed to them."""
    biz = _uuid(business_id, "business")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Private care is temporarily unavailable")
    if not rows:
        raise HTTPException(404, "business not found")
    owner = str(rows[0].get("owner_id")) == str(user.id)
    role: Optional[str] = "owner" if owner else None
    if not owner:
        seats = sb_clients.sb_get_as_service(
            f"/business_users?business_id=eq.{biz}&user_id=eq.{_uuid(user.id, 'user')}"
            "&status=eq.active&select=role&limit=1")
        if not isinstance(seats, list):
            raise HTTPException(503, "Private care is temporarily unavailable")
        if not seats:
            raise HTTPException(403, "Prayer & care requests are for this church's team")
        role = seats[0].get("role")
    import church_keys
    kept = church_keys.opened(biz, user, "people_care")
    sees_all = owner if kept is None else kept
    return CareCaller(user.id, sees_all, shared=not sees_all and _works_care(biz, str(user.id), role))


def _team(biz: str) -> List[Dict[str, Any]]:
    """Who the owner can hand a request to: the active seats, each with the
    person behind it and what they do (Kevin, 2026-11-18, the care desk:
    hand-offs by name and role, never an email address and a login level).

    `pastor`: the login's person holds a senior or pastoral role in the
    church's role library (church_roles); only they take a request that
    needs a pastor. `care`: works People & care (the lane) or holds a care
    role. `office`: the Office & Leadership lane or an office role.
    `treasurer`: the Treasurer lane or a role titled treasurer; the
    treasurer pays approved help (church_help) and isn't handed the ask.
    Anything that can't be read leaves the flags false and the name to the
    email: the list still loads."""
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&status=eq.active"
        "&select=user_id,invited_email,role,name,contact_id,lane&limit=200")
    if not isinstance(rows, list):
        # Before the seat-person columns (APPLY 2026-10-28): the old read.
        rows = sb_clients.sb_get_as_service(
            f"/business_users?business_id=eq.{biz}&status=eq.active"
            "&select=user_id,invited_email,role&limit=200")
    seats = [r for r in (rows if isinstance(rows, list) else []) if r.get("user_id")]
    cids = sorted({str(r["contact_id"]) for r in seats if r.get("contact_id")})
    people: Dict[str, Dict[str, Any]] = {}
    held: Dict[str, List[str]] = {}
    defs: List[Dict[str, Any]] = []
    if cids:
        try:
            import church_follow_up as cfu
            people = cfu._contacts(biz, cids) or {}
            got = sb_clients.sb_get_as_service(
                f"/church_leader_roles?business_id=eq.{biz}&status=eq.active"
                f"&contact_id=in.({','.join(cids)})&select=contact_id,role&limit=1000")
            for h in got if isinstance(got, list) else []:
                held.setdefault(str(h.get("contact_id")), []).append(str(h.get("role") or ""))
            if held:
                import church_roles
                defs = church_roles.defs(biz) or []
        except Exception:
            defs = []
    by = {d["key"]: d for d in defs if d.get("key")}
    try:
        import church_areas
        lane_label = {k: v["label"] for k, v in church_areas.LANES.items()}
    except Exception:
        lane_label = {}
    out = []
    for r in seats:
        cid = str(r.get("contact_id") or "")
        keys = [k for k in held.get(cid, []) if k]
        mine = [by[k] for k in keys if k in by]
        jobs = {d.get("job") for d in mine}
        handles = {h for d in mine for h in (d.get("handles") or [])}
        titles = [str(d.get("title") or "") for d in mine if d.get("title")]
        lane = str(r.get("lane") or "")
        treasurer = (lane == "treasurer" or "treasurer" in keys
                     or any("treasurer" in t.lower() for t in titles))
        name = " ".join(str(r.get("name") or "").split()) or str((people.get(cid) or {}).get("name") or "")
        out.append({
            "user_id": str(r["user_id"]), "email": r.get("invited_email") or "", "role": r.get("role") or "",
            "name": "" if name == "Someone" else name, "titles": titles[:3], "lane": lane,
            "lane_label": lane_label.get(lane, ""),
            "pastor": bool(jobs & {"senior", "pastoral"}),
            "care": lane == "people_care" or "care" in jobs or "care_need" in handles,
            "office": lane == "office_leadership" or ("office" in jobs and not treasurer),
            "treasurer": treasurer,
        })
    return out


def _owner_name(biz: str) -> str:
    """The name the church's settings give its owner, or ''."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=owner_name:settings->>practitioner_name&limit=1")
    if isinstance(rows, list) and rows:
        return " ".join(str(rows[0].get("owner_name") or "").split())
    return ""


def _finished(r: Dict[str, Any]) -> bool:
    return bool(r.get("prayed_at")) or r.get("status") == "closed"


def lane_of(r: Dict[str, Any], caller: Optional[CareCaller]) -> str:
    """Where a request sits on the care desk, the same rule the app draws:
    the owner's needs_pastor / waiting / with / done; a teammate's mine /
    team / done."""
    if _finished(r):
        return "done"
    if caller is None or caller.owner:
        if r.get("assigned_to") or r.get("leader_contact_id"):
            return "with"
        return "needs_pastor" if r.get("needs_pastor") else "waiting"
    return "mine" if str(r.get("assigned_to") or "") == caller.user_id else "team"


def list_requests(business_id: str, caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    """The newest 100 requests this caller may see, each with its notes.

    `caller=None` is the owner (every request), kept for older callers."""
    biz = _uuid(business_id, "business")
    mine = caller is not None and not caller.owner
    scope = caller.scope if caller is not None else "all"
    root = f"/ministry_care_requests?business_id=eq.{biz}&order=created_at.desc&limit=100"
    base = root + (f"&assigned_to=eq.{_uuid(caller.user_id, 'user')}" if mine else "")
    rows = None
    if scope == "shared":
        # The prayer-team columns say what was shared. If they can't be
        # read, nothing counts as shared: the login sees what was handed
        # to it, as before, never more.
        shared = f"{root}&or=(assigned_to.eq.{_uuid(caller.user_id, 'user')},{SHARED})"
        rows = sb_clients.sb_get_as_service(f"{shared}&select={_FIELDS}{_PRAYER_FIELDS}{_LOGIN_FIELDS}")
        if not isinstance(rows, list):
            rows = sb_clients.sb_get_as_service(f"{shared}&select={_FIELDS}{_PRAYER_FIELDS}")
        if not isinstance(rows, list):
            scope = "assigned"
    if scope != "shared":
        rows = sb_clients.sb_get_as_service(f"{base}&select={_FIELDS}{_PRAYER_FIELDS}{_LOGIN_FIELDS}")
        if not isinstance(rows, list):
            rows = sb_clients.sb_get_as_service(f"{base}&select={_FIELDS}{_PRAYER_FIELDS}")
    prayer = isinstance(rows, list)
    if not prayer:
        rows = sb_clients.sb_get_as_service(f"{base}&select={_FIELDS}")
    if not isinstance(rows, list):
        if mine:
            # Without the assignment column nothing can have been handed
            # to anyone, and the owner-only read must not stand in for it.
            raise HTTPException(503, "Private requests could not be loaded")
        # The columns this inbox acts on arrive with
        # APPLY-2026-10-14-care-inbox-actions.sql and -care-assign.sql.
        # Until then the owner still reads.
        rows = sb_clients.sb_get_as_service(f"{base}&select={_LEGACY_FIELDS}")
        if not isinstance(rows, list):
            raise HTTPException(503, "Private requests could not be loaded")
        return {"requests": [dict(r, notes=[]) for r in rows], "actions": False,
                "scope": "all", "team": []}
    notes: Dict[str, List[Dict[str, Any]]] = {}
    ids = ",".join(str(r["id"]) for r in rows if r.get("id"))
    if ids:
        found = sb_clients.sb_get_as_service(
            f"/ministry_care_notes?business_id=eq.{biz}&request_id=in.({ids})"
            "&select=id,request_id,body,created_at,author_id&order=created_at.asc&limit=2000")
        for n in found if isinstance(found, list) else []:
            notes.setdefault(str(n.get("request_id")), []).append(
                {k: n.get(k) for k in ("id", "body", "created_at", "author_id")})
    if prayer:
        # Who on the prayer team has it, and whether they prayed and wrote.
        try:
            import church_prayer
            rows = church_prayer.office_fields(rows, biz)
        except Exception:
            pass
    # The team by name and role (the owner's hand-off list), and the names
    # on the notes: a note says who wrote it, never "a teammate".
    team = _team(biz)
    # The owner already sees the team's addresses; anyone else sees a name
    # or a role title, never a teammate's email address.
    names = {t["user_id"]: (t["name"] or ((t["titles"] or [""])[0]) or t["lane_label"]
                            or (t["email"] if not mine else "")) for t in team}
    got = sb_clients.sb_get_as_service(f"/businesses?id=eq.{biz}&select=owner_id&limit=1")
    owner_id = str(got[0].get("owner_id") or "") if isinstance(got, list) and got else ""
    if owner_id:
        names[owner_id] = _owner_name(biz) or "The pastor"
    for ns in notes.values():
        for n in ns:
            n["author_name"] = names.get(str(n.get("author_id") or ""), "")
    out: Dict[str, Any] = {
        "requests": [dict(r, notes=notes.get(str(r.get("id")), [])) for r in rows],
        "actions": True, "scope": scope, "team": [],
    }
    if not mine:
        waiting: Dict[str, int] = {}
        for r in rows:
            if r.get("assigned_to") and not _finished(r):
                waiting[str(r["assigned_to"])] = waiting.get(str(r["assigned_to"]), 0) + 1
        out["team"] = [dict(t, waiting=waiting.get(t["user_id"], 0)) for t in team]
        # Who prays with the prayer team (members, in the member app), so
        # the office can hand a shared prayer to a different one.
        try:
            import church_prayer
            out["prayer_team"] = church_prayer.office_people(biz) or []
        except Exception:
            out["prayer_team"] = []
    return out


def _may_touch(row: Dict[str, Any], caller: Optional[CareCaller]) -> bool:
    """Whether this caller may see and act on one request: the owner (or
    keeper) always; a teammate when it was handed to them; a People & care
    login also when the person shared it with the prayer team and it
    doesn't need a pastor."""
    if caller is None or caller.owner:
        return True
    if str(row.get("assigned_to") or "") == caller.user_id:
        return True
    return caller.shared and row.get("prayer_team") is True and row.get("needs_pastor") is not True


def _request(biz: str, request_id: str, caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    one = (f"/ministry_care_requests?id=eq.{request_id}&business_id=eq.{biz}"
           "&select=id,status,prayed_at,status_changed_at,assigned_to,contact_id")
    # The prayer columns for every caller: a hand-off reads needs_pastor
    # (the pastors' alone) and leader_prayed_at. Without them, the old read.
    prayer = ",prayer_team,needs_pastor,leader_contact_id,leader_prayed_at"
    rows = sb_clients.sb_get_as_service(one + prayer + _LOGIN_FIELDS + "&limit=1")
    if rows is None:
        rows = sb_clients.sb_get_as_service(one + prayer + "&limit=1")
    if rows is None:
        rows = sb_clients.sb_get_as_service(one + "&limit=1")
    if rows is None:
        raise HTTPException(503, "That request couldn't be reached. Nothing was changed — try again.")
    # A request this caller may not see reads exactly like one that
    # doesn't exist: they learn nothing about what they can't see.
    if not rows or not _may_touch(rows[0], caller):
        raise HTTPException(404, "That request isn't here any more")
    return rows[0]


_UNSET = object()
# A hand-off's timing, cleared: taken back, given back, or handed afresh.
_UNTIMED = {"assigned_due_at": None, "assigned_told_at": None, "assigned_acted_at": None,
            "assigned_late_level": 0}


def update_request(business_id: str, request_id: str, *, status: Optional[str] = None,
                   prayed: Optional[bool] = None, assigned_to: Any = _UNSET,
                   leader_contact_id: Any = _UNSET,
                   caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    """Move a request along, mark it prayed (prayed=False clears it), or,
    for the owner only, hand it to a teammate (assigned_to=None takes it
    back). The teammate it was handed to may give it back (assigned_to=None
    on their own request). A request that needs a pastor goes only to a
    login whose person holds a pastor role. `leader_contact_id`: the owner
    hands a shared prayer to a different member of the prayer team."""
    biz, rid = _uuid(business_id, "business"), _uuid(request_id, "request")
    if status is not None and status not in STATUSES:
        raise HTTPException(400, "A request is new, reviewed or closed")
    current = _request(biz, rid, caller)
    patch: Dict[str, Any] = {}
    timed = "assigned_late_level" in current      # APPLY-2026-11-18-care-login-due.sql is in
    holds = caller is not None and str(current.get("assigned_to") or "") == caller.user_id
    if (timed and holds and not current.get("assigned_acted_at") and assigned_to is _UNSET
            and (status in ("reviewed", "closed") or prayed is True)):
        # The login it was handed to took a first step ("I'm on it",
        # prayed, done): nothing is late after it (care_handoff).
        patch["assigned_acted_at"] = _now()
    if status is not None and status != current.get("status"):
        patch["status"] = status
        patch["status_changed_at"] = _now()
    if prayed is not None:
        patch["prayed_at"] = _now() if prayed else None
    if assigned_to is not _UNSET:
        giving_back = (caller is not None and not caller.owner and assigned_to is None
                       and str(current.get("assigned_to") or "") == caller.user_id)
        if caller is not None and not caller.owner and not giving_back:
            raise HTTPException(403, "Only the church's owner hands a request to someone")
        if assigned_to is None:
            if current.get("assigned_to"):
                patch.update(assigned_to=None, assigned_at=None,
                             assigned_by=caller.user_id if caller else None)
                if timed:
                    patch.update(_UNTIMED)
        else:
            who = _uuid(assigned_to, "teammate")
            if "needs_pastor" not in current:
                # The read that carries the crisis flag failed (or the
                # column isn't there): never hand on what might be a
                # pastor's alone without knowing.
                raise HTTPException(503, "That couldn't be checked just now. Nothing was changed. Try again.")
            mate = next((t for t in _team(biz) if t["user_id"] == who), None)
            if mate is None:
                raise HTTPException(400, "That person isn't on this church's team")
            if current.get("needs_pastor") and not mate.get("pastor"):
                # Words about a death, abuse or someone in danger: the
                # pastors' alone (church_prayer.needs_pastor). Kevin,
                # 2026-11-18: never offered to the treasurer or the office.
                raise HTTPException(400, "This request needs a pastor. Hand it to a login whose person holds "
                                         "a pastor role (Follow-up, Leaders), or keep it.")
            if who != str(current.get("assigned_to") or ""):
                now = _now()
                patch.update(assigned_to=who, assigned_at=now,
                             assigned_by=caller.user_id if caller else None)
                if timed:
                    # A first step is due in a day; the login hears once,
                    # two minutes from now (care_handoff.sweep_tick). Handed
                    # to yourself: nobody to tell.
                    import care_handoff
                    patch.update(_UNTIMED, assigned_due_at=care_handoff.due_from(datetime.fromisoformat(now)))
                    if caller is not None and who == caller.user_id:
                        patch["assigned_told_at"] = now
    if leader_contact_id is not _UNSET:
        if caller is not None and not caller.owner:
            raise HTTPException(403, "Only the church's owner hands a request to someone")
        import church_prayer
        patch.update(church_prayer.office_hand(biz, current, leader_contact_id))
    if not patch:
        return {"ok": True, "request": current}
    patch["updated_at"] = _now()
    rows = sb_clients.sb_patch_as_service(
        f"/ministry_care_requests?id=eq.{rid}&business_id=eq.{biz}", patch)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    row = rows[0]
    if prayed and not current.get("prayed_at"):
        # The person who asked can hear that the church prayed (their
        # "Prayer" notification, if the church and they have it on).
        import member_push
        member_push.tell_prayed(biz, current.get("contact_id"), rid)
    out = {k: row.get(k) for k in ("id", "status", "prayed_at", "status_changed_at", "assigned_to",
                                    "assigned_at")}
    if timed:
        out.update({k: row.get(k) for k in _LOGIN_FIELDS.strip(",").split(",")})
    if "leader_contact_id" in patch:
        out.update({k: row.get(k) for k in ("leader_contact_id", "leader_role", "leader_assigned_at",
                                            "leader_due_at", "leader_late_level")})
        try:
            import church_prayer
            out["leader"] = (church_prayer.office_fields([row], biz)[0] or {}).get("leader")
        except Exception:
            pass
    return {"ok": True, "request": out}


def add_note(business_id: str, request_id: str, body: str, author_id: str,
             caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    biz, rid = _uuid(business_id, "business"), _uuid(request_id, "request")
    text = (body or "").strip()
    if not text:
        raise HTTPException(400, "Write the note first")
    if len(text) > NOTE_MAX:
        raise HTTPException(400, f"A note can be up to {NOTE_MAX} characters")
    current = _request(biz, rid, caller)
    rows = sb_clients.sb_post_as_service("/ministry_care_notes", {
        "business_id": biz, "request_id": rid, "author_id": str(author_id), "body": text})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That note didn't save. Nothing was changed — try again.")
    n = rows[0]
    out: Dict[str, Any] = {"ok": True, "note": {k: n.get(k) for k in ("id", "body", "created_at", "author_id")}}
    if ("assigned_late_level" in current and not current.get("assigned_acted_at")
            and current.get("assigned_to") and str(current["assigned_to"]) == str(author_id)):
        # A note from the login it was handed to is their first step
        # (care_handoff): nothing is late after it. The note stands
        # whether or not this lands.
        now = _now()
        got = sb_clients.sb_patch_as_service(
            f"/ministry_care_requests?id=eq.{rid}&business_id=eq.{biz}&assigned_to=eq.{_uuid(author_id, 'user')}"
            "&assigned_acted_at=is.null&select=assigned_acted_at", {"assigned_acted_at": now})
        if isinstance(got, list) and got:
            out["assigned_acted_at"] = got[0].get("assigned_acted_at") or now
    return out


def delete_note(business_id: str, note_id: str,
                caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    """The owner removes any note; a teammate only their own, and only on
    a request still handed to them."""
    biz, nid = _uuid(business_id, "business"), _uuid(note_id, "note")
    where = f"/ministry_care_notes?id=eq.{nid}&business_id=eq.{biz}"
    if caller is not None and not caller.owner:
        rows = sb_clients.sb_get_as_service(f"{where}&select=request_id,author_id&limit=1")
        if rows is None:
            raise HTTPException(503, "That note wasn't removed. Try again.")
        if not rows or str(rows[0].get("author_id")) != caller.user_id:
            raise HTTPException(404, "That note isn't here any more")
        _request(biz, _uuid(rows[0].get("request_id"), "request"), caller)
        where += f"&author_id=eq.{caller.user_id}"
    if not sb_clients.sb_delete_as_service(where):
        raise HTTPException(503, "That note wasn't removed. Try again.")
    return {"ok": True}


# ─── The desk's numbers (2026-11-18) ──────────────────────────────────
#
# The locked page shows how many requests sit in each lane and nothing
# else: no name, no word of a request, no id. It needs no password (that
# is the point of a locked page), only a login that may open the inbox.

COUNT_KEYS = {"all": ("needs_pastor", "waiting", "with", "done"),
              "shared": ("mine", "team", "done"), "assigned": ("mine", "team", "done")}


def counts(business_id: str, caller: CareCaller) -> Dict[str, Any]:
    biz = _uuid(business_id, "business")
    scope = caller.scope
    root = f"/ministry_care_requests?business_id=eq.{biz}&order=created_at.desc&limit=100"
    lean = "id,status,prayed_at,assigned_to"
    extra = ",needs_pastor,prayer_team,leader_contact_id"
    me = _uuid(caller.user_id, "user")
    rows = None
    if scope == "shared":
        rows = sb_clients.sb_get_as_service(f"{root}&or=(assigned_to.eq.{me},{SHARED})&select={lean}{extra}")
        if not isinstance(rows, list):
            scope = "assigned"
    if scope != "shared":
        base = root + ("" if caller.owner else f"&assigned_to=eq.{me}")
        rows = sb_clients.sb_get_as_service(f"{base}&select={lean}{extra}")
        if not isinstance(rows, list):
            rows = sb_clients.sb_get_as_service(f"{base}&select={lean}")
    if not isinstance(rows, list):
        raise HTTPException(503, "The numbers couldn't be read just now. Try again.")
    out = {k: 0 for k in COUNT_KEYS[caller.scope]}
    for r in rows:
        k = lane_of(r, caller)
        if k in out:
            out[k] += 1
    return {"scope": caller.scope, "counts": out}


# ─── The lock (Kevin, 2026-11-18) ─────────────────────────────────────
#
# The page should lock when no work has been done and ask for a password
# to open again, "but that should be custom to settings because others
# might like something else". One row a church (ministry_care_settings,
# APPLY-2026-11-18-care-lock.sql). No row, no table yet, or a read that
# failed: the default, which is the careful one.
#
# When the church asks for the password, the inbox's own routes refuse a
# request that doesn't carry a care proof for this church and this login
# (ledger_unlock.require_unlock, scope "care"). A proof lasts the church's
# quiet minutes and the app renews it while someone is working (POST
# .../unlock/renew), so a page left alone locks on the server too. A
# church that never locks by itself gets an hour at a time, renewed the
# same way.

LOCK_MINUTES = (0, 5, 10, 15, 30, 60)
DEFAULT_LOCK = {"lock_minutes": 10, "require_password": True}


def lock_mode() -> str:
    """CHURCH_CARE_LOCK: on (the default) or off. Off is the rollback: no
    church is asked for the password, whatever it saved; the page still
    locks after its quiet minutes and when it's left."""
    import os
    return "off" if (os.environ.get("CHURCH_CARE_LOCK") or "on").strip().lower() == "off" else "on"


def _is_sample(biz: str) -> bool:
    """The made-up sample church (sample_church.py): nothing in it is
    private, and the app never sends its password anywhere (the sample's
    guard refuses /auth/step-up), so it opens without one. A read that
    fails, or no such column yet, is not a sample."""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{biz}&select=is_sample&limit=1")
    return isinstance(rows, list) and bool(rows) and rows[0].get("is_sample") is True


def lock_settings(business_id: str) -> Dict[str, Any]:
    s = _lock_settings(business_id)
    if lock_mode() == "off":
        s = {**s, "require_password": False}
    return s


def _lock_settings(business_id: str) -> Dict[str, Any]:
    biz = _uuid(business_id, "business")
    if _is_sample(biz):
        return {"lock_minutes": DEFAULT_LOCK["lock_minutes"], "require_password": False,
                "saved": False, "ready": False, "sample": True}
    rows = sb_clients.sb_get_as_service(
        f"/ministry_care_settings?business_id=eq.{biz}&select=lock_minutes,require_password&limit=1")
    if not isinstance(rows, list):
        return {**DEFAULT_LOCK, "saved": False, "ready": False}
    if not rows:
        return {**DEFAULT_LOCK, "saved": False, "ready": True}
    r = rows[0]
    try:
        minutes = int(r.get("lock_minutes"))
    except (TypeError, ValueError):
        minutes = DEFAULT_LOCK["lock_minutes"]
    if minutes not in LOCK_MINUTES:
        minutes = DEFAULT_LOCK["lock_minutes"]
    return {"lock_minutes": minutes, "require_password": r.get("require_password") is not False,
            "saved": True, "ready": True}


def unlock_ttl(business_id: str) -> int:
    """How long one care proof lasts, in seconds: the church's quiet
    minutes, an hour for a church that never locks by itself."""
    return (lock_settings(business_id)["lock_minutes"] or 60) * 60


def require_open(request: Any, business_id: str, user: Any) -> Dict[str, Any]:
    """The gate in front of the inbox's routes: when the church asks for
    the password, a care proof for this church and this login, or a 403
    `ledger_locked` (scope care) for the app to show its lock."""
    s = lock_settings(business_id)
    if s["require_password"]:
        import ledger_unlock
        ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_CARE,
                                     _uuid(business_id, "business"))
    return s


def save_lock_settings(business_id: str, caller: CareCaller, *, lock_minutes: Any = None,
                       require_password: Any = None) -> Dict[str, Any]:
    """The owner (or the People & care keeper) changes how the page locks."""
    if not caller.owner:
        raise HTTPException(403, "Only the church's owner changes how Prayer & care locks")
    biz = _uuid(business_id, "business")
    now = _lock_settings(biz)
    if not now["ready"]:
        raise HTTPException(503, "Lock settings are being switched on. Try again later.")
    minutes = now["lock_minutes"] if lock_minutes is None else lock_minutes
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = -1
    if minutes not in LOCK_MINUTES:
        raise HTTPException(400, "Pick how long it waits: never, 5, 10, 15, 30 or 60 minutes")
    password = now["require_password"] if require_password is None else bool(require_password)
    rows = sb_clients.sb_post_as_service(
        "/ministry_care_settings?on_conflict=business_id",
        {"business_id": biz, "lock_minutes": minutes, "require_password": password,
         "updated_by": caller.user_id, "updated_at": _now()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing was changed. Try again.")
    return {"lock_minutes": minutes, "require_password": password, "saved": True, "ready": True}
