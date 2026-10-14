"""Private care intake is owner-only and never enters marketing/AI pipelines.

The inbox can act as well as read: a request moves new -> reviewed ->
closed, can be marked prayed, and carries private notes
(ministry_care_notes). Everything here is written as the service, after
require_owner, because the browser has no grant on either table.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from urllib.parse import quote
import sb_clients

STATUSES = ("new", "reviewed", "closed")
NOTE_MAX = 4000
_FIELDS = "id,created_at,status,submission,contact_id,prayed_at,status_changed_at"
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
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": business_id, "form_id": form_id, "submission": data,
        "status": "new",
    })
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "Your private request could not be saved. Please retry.")
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


def list_requests(business_id: str) -> Dict[str, Any]:
    """The newest 100 requests, each with its notes (oldest first)."""
    biz = _uuid(business_id, "business")
    base = f"/ministry_care_requests?business_id=eq.{biz}&order=created_at.desc&limit=100"
    rows = sb_clients.sb_get_as_service(f"{base}&select={_FIELDS}")
    if not isinstance(rows, list):
        # The columns this inbox acts on arrive with
        # APPLY-2026-10-14-care-inbox-actions.sql. Until then it still reads.
        rows = sb_clients.sb_get_as_service(f"{base}&select={_LEGACY_FIELDS}")
        if not isinstance(rows, list):
            raise HTTPException(503, "Private requests could not be loaded")
        return {"requests": [dict(r, notes=[]) for r in rows], "actions": False}
    notes: Dict[str, List[Dict[str, Any]]] = {}
    ids = ",".join(str(r["id"]) for r in rows if r.get("id"))
    if ids:
        found = sb_clients.sb_get_as_service(
            f"/ministry_care_notes?business_id=eq.{biz}&request_id=in.({ids})"
            "&select=id,request_id,body,created_at&order=created_at.asc&limit=2000")
        for n in found if isinstance(found, list) else []:
            notes.setdefault(str(n.get("request_id")), []).append(
                {k: n.get(k) for k in ("id", "body", "created_at")})
    return {"requests": [dict(r, notes=notes.get(str(r.get("id")), [])) for r in rows],
            "actions": True}


def _request(biz: str, request_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/ministry_care_requests?id=eq.{request_id}&business_id=eq.{biz}"
        "&select=id,status,prayed_at,status_changed_at&limit=1")
    if rows is None:
        raise HTTPException(503, "That request couldn't be reached. Nothing was changed — try again.")
    if not rows:
        raise HTTPException(404, "That request isn't here any more")
    return rows[0]


def update_request(business_id: str, request_id: str, *, status: Optional[str] = None,
                   prayed: Optional[bool] = None) -> Dict[str, Any]:
    """Move a request along, or mark it prayed (prayed=False clears it)."""
    biz, rid = _uuid(business_id, "business"), _uuid(request_id, "request")
    if status is not None and status not in STATUSES:
        raise HTTPException(400, "A request is new, reviewed or closed")
    current = _request(biz, rid)
    patch: Dict[str, Any] = {}
    if status is not None and status != current.get("status"):
        patch["status"] = status
        patch["status_changed_at"] = _now()
    if prayed is not None:
        patch["prayed_at"] = _now() if prayed else None
    if not patch:
        return {"ok": True, "request": current}
    patch["updated_at"] = _now()
    rows = sb_clients.sb_patch_as_service(
        f"/ministry_care_requests?id=eq.{rid}&business_id=eq.{biz}", patch)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing was changed — try again.")
    row = rows[0]
    return {"ok": True, "request": {k: row.get(k) for k in
                                    ("id", "status", "prayed_at", "status_changed_at")}}


def add_note(business_id: str, request_id: str, body: str, author_id: str) -> Dict[str, Any]:
    biz, rid = _uuid(business_id, "business"), _uuid(request_id, "request")
    text = (body or "").strip()
    if not text:
        raise HTTPException(400, "Write the note first")
    if len(text) > NOTE_MAX:
        raise HTTPException(400, f"A note can be up to {NOTE_MAX} characters")
    _request(biz, rid)
    rows = sb_clients.sb_post_as_service("/ministry_care_notes", {
        "business_id": biz, "request_id": rid, "author_id": str(author_id), "body": text})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That note didn't save. Nothing was changed — try again.")
    n = rows[0]
    return {"ok": True, "note": {k: n.get(k) for k in ("id", "body", "created_at")}}


def delete_note(business_id: str, note_id: str) -> Dict[str, Any]:
    biz, nid = _uuid(business_id, "business"), _uuid(note_id, "note")
    if not sb_clients.sb_delete_as_service(
            f"/ministry_care_notes?id=eq.{nid}&business_id=eq.{biz}"):
        raise HTTPException(503, "That note wasn't removed. Try again.")
    return {"ok": True}
