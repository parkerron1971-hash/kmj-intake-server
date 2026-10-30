"""text_room.py — the Text room's people pieces (Kevin, 2026-10-30: "let's
work on the list"; the design is the artifact "Texting Room Upgrade").

    POST /sms/guest      save a number that texted in: their name on a
                         contact (the keyword already made one named with
                         the number, so it is named, not duplicated), their
                         earlier texts tied to it, and at a church a welcome
                         follow-up (church_follow_up.start, routed like a
                         first check-in: the welcome role, else the senior
                         one)
    GET  /sms/prayer     which of these texts are on the prayer list
    POST /sms/prayer     put a text on the prayer list (ministry_care_requests).
                         Pastors only unless the office shares it with the
                         prayer team; words about danger, abuse or a death
                         stay with the pastors whatever is chosen
                         (church_prayer.consent_columns), and a shared one
                         is handed to the Intercessor leader (on_new)
    GET  /sms/replies    the business's saved replies
    PUT  /sms/replies    replace them (settings.sms_replies)

Every handler resolves the caller's relationship to the business before it
reads or writes (business_access): reading at viewer, writing at member,
the people who answer texts.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sms"])

MAX_REPLIES = 12
MAX_LABEL = 30
MAX_REPLY = 480
MAX_PRAYER = 2000


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _unavailable() -> HTTPException:
    return HTTPException(503, "Text is busy right now. Try again in a minute.")


def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,settings&limit=1")
    if not isinstance(rows, list):
        raise _unavailable()
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _is_church(business: Dict[str, Any]) -> bool:
    import church_follow_up
    return church_follow_up.is_church(business)


def nameless(name: Any) -> bool:
    """A contact the keyword made is named with the number until someone
    names them: no letters at all."""
    return not re.search(r"[^\W\d_]", str(name or ""))


def _contact_by_phone(biz: str, phone: str) -> Optional[Dict[str, Any]]:
    """The same match inbound texts use (sms_service._find_contact_by_phone):
    exact E.164, then the last ten digits."""
    sel = "select=id,name,phone,status,tags&limit=1"
    rows = sb_clients.sb_get_as_service(f"/contacts?business_id=eq.{_q(biz)}&phone=eq.{_q(phone)}&{sel}")
    if rows is None:
        raise _unavailable()
    if rows:
        return rows[0]
    last10 = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if not last10:
        return None
    rows = sb_clients.sb_get_as_service(f"/contacts?business_id=eq.{_q(biz)}&phone=like.%25{last10}&{sel}")
    if rows is None:
        raise _unavailable()
    return rows[0] if rows else None


# ─── A number that texted in becomes someone ─────────────────────────

class GuestIn(BaseModel):
    business_id: str
    name: str = Field(..., max_length=200)
    phone: str = Field(..., max_length=40)


@router.post("/sms/guest")
def save_guest(body: GuestIn, user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(body.business_id)
    business_access.assert_access(biz, user, "member")
    from sms_service import normalize_phone, _pq
    name = " ".join(str(body.name or "").split())[:120]
    phone = normalize_phone(body.phone)
    if nameless(name):
        raise HTTPException(400, "Type their name.")
    if not phone:
        raise HTTPException(400, "That isn't a number we can text.")
    business = _business(biz)
    church = _is_church(business)

    found = _contact_by_phone(biz, phone)
    created = False
    if found and not nameless(found.get("name")):
        # Someone saved them meanwhile: keep their name, don't make a second one.
        cid = str(found["id"])
    elif found:
        tags = [t for t in (found.get("tags") or []) if isinstance(t, str)]
        patch: Dict[str, Any] = {"name": name}
        if church:
            # The keyword made them "active" as a placeholder; at a church a
            # first-time texter is a guest, as one saved from scratch is.
            patch["status"] = "lead"
            if "first-time guest" not in tags:
                patch["tags"] = tags + ["first-time guest"]
        if sb_clients.sb_patch_as_service(f"/contacts?id=eq.{_q(found['id'])}&business_id=eq.{_q(biz)}", patch) is None:
            raise _unavailable()
        cid = str(found["id"])
    else:
        row: Dict[str, Any] = {"business_id": biz, "name": name, "phone": phone, "status": "lead", "source": "sms"}
        if church:
            row["tags"] = ["first-time guest"]
        made = sb_clients.sb_post_as_service("/contacts", row)
        if not isinstance(made, list) or not made:
            raise _unavailable()
        cid, created = str(made[0]["id"]), True

    # Their earlier texts are tied to them, so it stays one conversation.
    sb_clients.sb_patch_as_service(
        f"/sms_messages?business_id=eq.{_q(biz)}&phone_number=eq.{_pq(phone)}&contact_id=is.null",
        {"contact_id": cid})

    leader = None
    if church:
        import church_follow_up
        # The leader reads that they texted, never what: a first text can be
        # a prayer request, and prayer is never a follow-up's (the module's
        # rule). Routed like a first check-in, so the words decide nothing.
        row = church_follow_up.start(
            biz, cid, card_key="text:first", card_name="First text", kind="connect",
            answers=[{"q": "First text", "a": "Texted the church for the first time. The conversation is in Text."}],
            source_event=f"text-guest:{phone}"[:80], what="First texts", route_answers=[])
        if row and row.get("leader_contact_id"):
            people = sb_clients.sb_get_as_service(
                f"/contacts?id=eq.{_q(row['leader_contact_id'])}&business_id=eq.{_q(biz)}&select=name&limit=1")
            leader = (people[0].get("name") if isinstance(people, list) and people else None) or ""
        elif row:
            leader = ""
    return {"ok": True, "contact_id": cid, "created": created,
            "follow_up": leader is not None, "leader": (leader or "").split(" ")[0] or None}


# ─── The prayer list ─────────────────────────────────────────────────

class PrayerIn(BaseModel):
    business_id: str
    message_id: str
    # With the prayer team; otherwise the pastors only.
    share: bool = False


@router.get("/sms/prayer")
def prayer_marks(business_id: str = Query(...), ids: str = Query(""), user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(business_id)
    business_access.assert_access(biz, user, "viewer")
    want = [_uuid(x, "text") for x in ids.split(",") if x.strip()][:200]
    if not want:
        return {"on_list": {}}
    rows = sb_clients.sb_get_as_service(
        f"/ministry_care_requests?business_id=eq.{_q(biz)}"
        f"&submission->>sms_message_id=in.({','.join(want)})&select=submission,prayer_team&limit=200")
    if rows is None:
        raise _unavailable()
    out = {}
    for r in rows:
        mid = (r.get("submission") or {}).get("sms_message_id")
        if mid:
            out[str(mid)] = {"shared": bool(r.get("prayer_team"))}
    return {"on_list": out}


@router.post("/sms/prayer")
def add_prayer(body: PrayerIn, user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(body.business_id)
    business_access.assert_access(biz, user, "member")
    mid = _uuid(body.message_id, "text")
    business = _business(biz)
    if not _is_church(business):
        raise HTTPException(400, "The prayer list is a church's.")
    msgs = sb_clients.sb_get_as_service(
        f"/sms_messages?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}&direction=eq.inbound"
        "&select=id,contact_id,phone_number,message&limit=1")
    if msgs is None:
        raise _unavailable()
    if not msgs:
        raise HTTPException(404, "That text isn't here.")
    msg = msgs[0]
    have = sb_clients.sb_get_as_service(
        f"/ministry_care_requests?business_id=eq.{_q(biz)}&submission->>sms_message_id=eq.{_q(mid)}"
        "&select=id,prayer_team,needs_pastor&limit=1")
    if have is None:
        raise _unavailable()
    if have:
        return {"ok": True, "already": True, "shared": bool(have[0].get("prayer_team")),
                "needs_pastor": bool(have[0].get("needs_pastor"))}

    name, email = "", ""
    if msg.get("contact_id"):
        people = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{_q(msg['contact_id'])}&business_id=eq.{_q(biz)}&select=name,email&limit=1")
        if isinstance(people, list) and people:
            name = "" if nameless(people[0].get("name")) else str(people[0].get("name") or "")
            email = str(people[0].get("email") or "")
    import church_prayer
    submission = {
        "name": name, "email": email, "phone": msg.get("phone_number") or "",
        "prayer_request": str(msg.get("message") or "")[:MAX_PRAYER],
        "confidential": "no" if body.share else "yes",
        "source": "Text", "sms_message_id": mid,
    }
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": biz, "form_id": None, "contact_id": msg.get("contact_id"), "status": "new",
        "submission": submission, **church_prayer.consent_columns(submission, share=body.share),
    })
    if not isinstance(rows, list) or not rows:
        raise _unavailable()
    church_prayer.on_new(biz, rows[0])
    return {"ok": True, "already": False, "shared": bool(rows[0].get("prayer_team")),
            "needs_pastor": bool(rows[0].get("needs_pastor"))}


# ─── Saved replies ───────────────────────────────────────────────────

class Reply(BaseModel):
    label: str = Field(..., max_length=200)
    text: str = Field(..., max_length=2000)


class RepliesIn(BaseModel):
    business_id: str
    replies: List[Reply] = Field(default_factory=list, max_length=50)


def clean_replies(raw: Any) -> List[Dict[str, str]]:
    """Trimmed, non-empty, one per label, at most MAX_REPLIES."""
    out: List[Dict[str, str]] = []
    seen = set()
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        label = " ".join(str(r.get("label") or "").split())[:MAX_LABEL]
        text = str(r.get("text") or "").strip()[:MAX_REPLY]
        if not label or not text or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        out.append({"label": label, "text": text})
        if len(out) >= MAX_REPLIES:
            break
    return out


@router.get("/sms/replies")
def get_replies(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(business_id)
    business_access.assert_access(biz, user, "viewer")
    s = _business(biz).get("settings")
    return {"replies": clean_replies((s if isinstance(s, dict) else {}).get("sms_replies"))}


@router.put("/sms/replies")
def put_replies(body: RepliesIn, user: AuthedUser = Depends(require_user)):
    import business_access
    biz = _uuid(body.business_id)
    business_access.assert_access(biz, user, "member")
    replies = clean_replies([r.model_dump() for r in body.replies])
    s = _business(biz).get("settings")
    s = s if isinstance(s, dict) else {}
    if sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz)}", {"settings": {**s, "sms_replies": replies}}) is None:
        raise _unavailable()
    return {"ok": True, "replies": replies}
