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
_PRAYER_FIELDS = ",prayer_team,wants_call,needs_pastor,leader_contact_id,leader_role,leader_prayed_at,leader_noted_at"
_LEGACY_FIELDS = "id,created_at,status,submission"

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

class CareCaller:
    def __init__(self, user_id: str, owner: bool):
        self.user_id = str(user_id)
        self.owner = owner

    @property
    def scope(self) -> str:
        return "all" if self.owner else "assigned"


def care_access(business_id: str, user) -> CareCaller:
    """The owner, or an active seat on this business. Anyone else: 403."""
    biz = _uuid(business_id, "business")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Private care is temporarily unavailable")
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) == str(user.id):
        return CareCaller(user.id, True)
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&user_id=eq.{_uuid(user.id, 'user')}"
        "&status=eq.active&select=role&limit=1")
    if not isinstance(seats, list):
        raise HTTPException(503, "Private care is temporarily unavailable")
    if not seats:
        raise HTTPException(403, "Prayer & care requests are for this church's team")
    return CareCaller(user.id, False)


def _team(biz: str) -> List[Dict[str, Any]]:
    """Who the owner can hand a request to: the active seats."""
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&status=eq.active"
        "&select=user_id,invited_email,role&limit=200")
    return [{"user_id": str(r["user_id"]), "email": r.get("invited_email") or "",
             "role": r.get("role") or ""}
            for r in (rows if isinstance(rows, list) else []) if r.get("user_id")]


def list_requests(business_id: str, caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    """The newest 100 requests this caller may see, each with its notes.

    `caller=None` is the owner (every request), kept for older callers."""
    biz = _uuid(business_id, "business")
    mine = caller is not None and not caller.owner
    base = f"/ministry_care_requests?business_id=eq.{biz}&order=created_at.desc&limit=100"
    if mine:
        base += f"&assigned_to=eq.{_uuid(caller.user_id, 'user')}"
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
    return {"requests": [dict(r, notes=notes.get(str(r.get("id")), [])) for r in rows],
            "actions": True, "scope": "assigned" if mine else "all",
            "team": [] if mine else _team(biz)}


def _request(biz: str, request_id: str, caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/ministry_care_requests?id=eq.{request_id}&business_id=eq.{biz}"
        "&select=id,status,prayed_at,status_changed_at,assigned_to,contact_id&limit=1")
    if rows is None:
        raise HTTPException(503, "That request couldn't be reached. Nothing was changed — try again.")
    # A request not handed to this teammate reads exactly like one that
    # doesn't exist: they learn nothing about what they can't see.
    if not rows or (caller is not None and not caller.owner
                    and str(rows[0].get("assigned_to") or "") != caller.user_id):
        raise HTTPException(404, "That request isn't here any more")
    return rows[0]


_UNSET = object()


def update_request(business_id: str, request_id: str, *, status: Optional[str] = None,
                   prayed: Optional[bool] = None, assigned_to: Any = _UNSET,
                   caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    """Move a request along, mark it prayed (prayed=False clears it), or,
    for the owner only, hand it to a teammate (assigned_to=None takes it
    back)."""
    biz, rid = _uuid(business_id, "business"), _uuid(request_id, "request")
    if status is not None and status not in STATUSES:
        raise HTTPException(400, "A request is new, reviewed or closed")
    current = _request(biz, rid, caller)
    patch: Dict[str, Any] = {}
    if status is not None and status != current.get("status"):
        patch["status"] = status
        patch["status_changed_at"] = _now()
    if prayed is not None:
        patch["prayed_at"] = _now() if prayed else None
    if assigned_to is not _UNSET:
        if caller is not None and not caller.owner:
            raise HTTPException(403, "Only the church's owner hands a request to someone")
        if assigned_to is None:
            if current.get("assigned_to"):
                patch.update(assigned_to=None, assigned_at=None,
                             assigned_by=caller.user_id if caller else None)
        else:
            who = _uuid(assigned_to, "teammate")
            if who not in {t["user_id"] for t in _team(biz)}:
                raise HTTPException(400, "That person isn't on this church's team")
            if who != str(current.get("assigned_to") or ""):
                patch.update(assigned_to=who, assigned_at=_now(),
                             assigned_by=caller.user_id if caller else None)
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
    return {"ok": True, "request": {k: row.get(k) for k in
                                    ("id", "status", "prayed_at", "status_changed_at",
                                     "assigned_to")}}


def add_note(business_id: str, request_id: str, body: str, author_id: str,
             caller: Optional[CareCaller] = None) -> Dict[str, Any]:
    biz, rid = _uuid(business_id, "business"), _uuid(request_id, "request")
    text = (body or "").strip()
    if not text:
        raise HTTPException(400, "Write the note first")
    if len(text) > NOTE_MAX:
        raise HTTPException(400, f"A note can be up to {NOTE_MAX} characters")
    _request(biz, rid, caller)
    rows = sb_clients.sb_post_as_service("/ministry_care_notes", {
        "business_id": biz, "request_id": rid, "author_id": str(author_id), "body": text})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That note didn't save. Nothing was changed — try again.")
    n = rows[0]
    return {"ok": True, "note": {k: n.get(k) for k in ("id", "body", "created_at", "author_id")}}


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
