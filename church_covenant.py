"""church_covenant.py — the covenant an office login signs, in a popup.

Kevin, 2026-11-06: "can you align the covenant so when they open the app it
would pop up? i want to use e-signature."

    WHO ............ every office login with a lane (church_duties: the lanes,
                     not the treasurer, whose money promises differ) signs as
                     Admin; then the Executive Pastor; then the Senior Pastor,
                     the church's owner. In that order: DocuSeal holds each
                     signer until the one before has signed
    THE FORM ....... church_covenant_text: the shared covenant and that
                     admin's own page, with their duties from church_duties
    THE RECORD ..... an esign_documents row per admin, source_ref
                     "covenant:<version>:<user id>", so the signature takes
                     the road every other one does: the webhook, the ledger
                     hash of the signed PDF, and a copy emailed to both sides
    THE POPUP ...... GET /church/covenant says what THIS login owes right now.
                     The owner sends it (POST /church/covenant/send): nobody is
                     asked to sign until the owner says so, and until then
                     there is nothing to pop up
    SIGNING ........ on DocuSeal's own page, opened from the popup. Its page
                     refuses to sit in a frame (X-Frame-Options: SAMEORIGIN),
                     and the legal record is theirs either way

Switched by CHURCH_COVENANT: off | owner | on, owner when unset (the platform
owner's church, until a Thursday flip). A read that fails shows nothing: this
never stands between someone and their app.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import church_covenant_text as text
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("church_covenant")

router = APIRouter(prefix="/church/covenant", tags=["church"])

APP_URL = "https://system.mysolutionist.app/"
SIGN_BASE = "https://docuseal.com/s/"
# The office's four lanes. The treasurer approves money, and the covenant
# promises they won't, so their page is its own document.
LANES = ("office_leadership", "people_care", "sunday_serving", "media_comms")
_DAYS = {"Mon": "Mondays", "Tue": "Tuesdays", "Wed": "Wednesdays", "Thu": "Thursdays", "Fri": "Fridays",
         "Sat": "Saturdays", "Sun": "Sundays", "weekly": "Weekly", "monthly": "Monthly",
         "as needed": "As needed", "first Monday": "The first Monday"}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def mode() -> str:
    m = (os.environ.get("CHURCH_COVENANT") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


def source_ref(user_id: Any) -> str:
    return f"covenant:{text.VERSION}:{user_id}"


def _user_of(ref: Any) -> str:
    parts = str(ref or "").split(":")
    return parts[2] if len(parts) == 3 else ""


def when_of(day: Any) -> str:
    """"Tue, monthly" → "Tuesdays and monthly"."""
    parts = [p.strip() for p in str(day or "").split(",") if p.strip()]
    words = [_DAYS.get(p, p) for p in parts]
    if len(words) < 2:
        return words[0] if words else ""
    return " and ".join([words[0], *[w[0].lower() + w[1:] if w in ("Monthly", "Weekly") else w for w in words[1:]]])


def duties_of(lane: str) -> List[Tuple[str, str]]:
    import church_duties as cd
    return [(str(cd.CATALOG[k].get("label") or k), when_of(cd.CATALOG[k].get("day"))) for k in cd.STARTER.get(lane, [])]


def _name_of(biz: str, seat: Dict[str, Any]) -> str:
    """The person a login is: the church's record of them, else the name they gave."""
    import business_users_router as bur
    contact = (bur._contact(biz, seat.get("contact_id"))
               or bur.match_contact(biz, seat.get("invited_email"), seat.get("name")))
    return bur._clean_name((contact or {}).get("name") or seat.get("name")) or "Admin"


def people(biz: str) -> Dict[str, Any]:
    """Who signs at this church: its admins, and its Executive Pastor."""
    import church_duties as cd
    seats = cd._seats(biz)
    execs = cd._exec_users(biz, seats)
    admins: List[Dict[str, Any]] = []
    exec_seat: Optional[Dict[str, Any]] = None
    for s in seats:
        uid = str(s.get("user_id") or "")
        email = str(s.get("invited_email") or "").strip().lower()
        if uid in execs:
            exec_seat = exec_seat or s
            continue
        lane = cd._seat_lane(s)
        if lane in LANES and "@" in email:
            admins.append({"user_id": uid, "email": email, "name": _name_of(biz, s), "lane": lane,
                           "lane_label": cd.lane_label(lane)})
    pastor = None
    if exec_seat is not None:
        pastor = {"user_id": str(exec_seat["user_id"]), "email": str(exec_seat.get("invited_email") or "").strip().lower(),
                  "name": _name_of(biz, exec_seat)}
    return {"admins": sorted(admins, key=lambda a: a["name"].casefold()), "exec": pastor}


def _sent(biz: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/esign_documents?business_id=eq.{_q(biz)}&source_ref=like.covenant:{text.VERSION}:*"
        "&select=id,document_id,title,signer_name,signer_email,status,source_ref&limit=200")
    return rows if isinstance(rows, list) else None


def payload_for(church: str, admin: Dict[str, Any], pastor: Optional[Dict[str, Any]],
                senior: Dict[str, Any]) -> Dict[str, Any]:
    """The DocuSeal submission for one admin. Nobody is emailed: they sign
    from the popup, each in turn."""
    first = str((pastor or {}).get("name") or "").split(" ")[0]
    html = text.document_html(
        church=church, name=admin["name"], lane=admin["lane"], lane_label=admin["lane_label"],
        duties=admin.get("duties") or duties_of(admin["lane"]),
        pastor=f"Pastor {first}" if first else "the Senior Pastor",
        exec_name=(pastor or {}).get("name"), senior_name=senior.get("name"))
    submitters = [{"role": text.ADMIN, "name": admin["name"], "email": admin["email"]}]
    if pastor and pastor.get("email"):
        submitters.append({"role": text.EXEC, "name": pastor["name"], "email": pastor["email"]})
    submitters.append({"role": text.SENIOR, "name": senior.get("name") or "Senior Pastor", "email": senior["email"]})
    for s in submitters:
        s.update(send_email=False, completed_redirect_url=APP_URL)
    title = f"{church} Admin Covenant: {admin['name']}"
    return {"name": title, "send_email": False, "order": "preserved",
            "documents": [{"name": title[:100], "html": html}], "submitters": submitters}


async def _create(church: str, biz: str, admin: Dict[str, Any], pastor: Optional[Dict[str, Any]],
                  senior: Dict[str, Any]) -> Dict[str, Any]:
    """One admin's covenant at DocuSeal, and its row here."""
    import docuseal_router as dr
    body = payload_for(church, admin, pastor, senior)
    async with httpx.AsyncClient(timeout=dr.HTTP_TIMEOUT) as c:
        r = await c.post(f"{dr.DOCUSEAL_BASE}/submissions/html", headers=dr._auth_headers(), json=body)
    if r.status_code >= 400:
        logger.error(f"[covenant] send failed {r.status_code}: {r.text[:300]}")
        return {"name": admin["name"], "ok": False}
    doc_id = dr.submission_id_from_send(r.json())
    if not doc_id:
        return {"name": admin["name"], "ok": False}
    saved = sb_clients.sb_post_as_service("/esign_documents", {
        "business_id": biz, "provider": dr.PROVIDER, "document_id": doc_id, "title": body["name"][:120],
        "signer_name": admin["name"][:100], "signer_email": admin["email"], "status": "sent",
        "source_ref": source_ref(admin["user_id"])})
    if not saved:
        logger.error(f"[covenant] submission {doc_id} made but its row didn't save")
        return {"name": admin["name"], "ok": False}
    return {"name": admin["name"], "ok": True, "document_id": doc_id,
            "hash": hashlib.sha256(body["documents"][0]["html"].encode("utf-8")).hexdigest()}


async def _submission(document_id: str) -> Optional[Dict[str, Any]]:
    import docuseal_router as dr
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as c:
            r = await c.get(f"{dr.DOCUSEAL_BASE}/submissions/{_q(document_id)}", headers=dr._auth_headers())
    except (httpx.HTTPError, HTTPException):
        return None
    if r.status_code >= 400:
        return None
    data = r.json()
    return data if isinstance(data, dict) else None


def turn_of(submission: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Who signs next, by the covenant's order: the one before must be done.
    DocuSeal lists its submitters in no order worth trusting."""
    by_role = {str(s.get("role")): s for s in submission.get("submitters") or [] if isinstance(s, dict)}
    for role in text.ORDER:
        s = by_role.get(role)
        if s is not None and str(s.get("status")) != "completed":
            return s
    return None


def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "That couldn't be read just now. Try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _is_church(b: Dict[str, Any]) -> bool:
    import vertical_registry
    return vertical_registry.resolve(str(b.get("type") or "")) == "ministry"


def _viewer_role(row: Dict[str, Any], uid: str, owner_id: str, exec_id: str) -> Optional[str]:
    if uid == owner_id:
        return text.SENIOR
    if exec_id and uid == exec_id:
        return text.EXEC
    if _user_of(row.get("source_ref")) == uid:
        return text.ADMIN
    return None


@router.get("")
async def mine(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What this login owes now: {on, sign: [...], send: [...]}. `send` is
    the owner's: the admins who haven't been asked yet."""
    import business_users_router as bur
    off: Dict[str, Any] = {"on": False, "sign": [], "send": []}
    b = _business(business_id)
    if not _is_church(b) or not switched_on(b["id"]):
        return off
    uid, owner_id = str(user.id), str(b.get("owner_id") or "")
    if uid != owner_id and not bur.role_of(str(b["id"]), uid):
        return off
    rows = _sent(str(b["id"]))
    if rows is None:
        return off
    who = people(str(b["id"]))
    exec_id = str((who.get("exec") or {}).get("user_id") or "")
    waiting = [r for r in rows if r.get("status") == "sent" and _viewer_role(r, uid, owner_id, exec_id)]
    subs = await asyncio.gather(*[_submission(str(r["document_id"])) for r in waiting])
    sign: List[Dict[str, Any]] = []
    for row, sub in zip(waiting, subs):
        turn = turn_of(sub) if sub else None
        if not turn or str(turn.get("role")) != _viewer_role(row, uid, owner_id, exec_id) or not turn.get("slug"):
            continue
        sign.append({"title": row.get("title"), "name": row.get("signer_name"), "url": SIGN_BASE + str(turn["slug"]),
                     "yours": _user_of(row.get("source_ref")) == uid})
    asked = {_user_of(r.get("source_ref")) for r in rows}
    send = ([{"name": a["name"], "lane": a["lane_label"]} for a in who["admins"] if a["user_id"] not in asked]
            if uid == owner_id else [])
    return {"on": True, "sign": sign, "send": send, "title": f"{b.get('name') or 'Your church'} Admin Covenant"}


class SendBody(BaseModel):
    business_id: str


@router.post("/send")
async def send(body: SendBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The owner asks the admins to sign. Only those not yet asked, so
    pressing it twice asks nobody twice."""
    import docuseal_router as dr
    b = _business(body.business_id)
    biz = str(b["id"])
    if str(b.get("owner_id") or "") != str(user.id):
        raise HTTPException(403, "Only the church's owner can send the covenant.")
    if not _is_church(b) or not switched_on(biz):
        raise HTTPException(404, "not found")
    rows = _sent(biz)
    if rows is None:
        raise HTTPException(503, "The covenant couldn't be read just now. Nothing was sent. Try again.")
    who = people(biz)
    asked = {_user_of(r.get("source_ref")) for r in rows}
    todo = [a for a in who["admins"] if a["user_id"] not in asked]
    if not todo:
        return {"ok": True, "sent": [], "failed": []}
    email = await dr._owner_email(str(b.get("owner_id")))
    if not email:
        raise HTTPException(503, "Your own email couldn't be read just now. Nothing was sent. Try again.")
    church = str(b.get("name") or "Your church")
    settings = b.get("settings") if isinstance(b.get("settings"), dict) else {}
    senior = {"email": email, "name": str(settings.get("practitioner_name") or "").strip()}
    done = await asyncio.gather(*[_create(church, biz, a, who.get("exec"), senior) for a in todo])
    import audit_log
    audit_log.record(biz, actor_type="user", actor_id=str(user.id), verb="covenant_send", source="desktop",
                     summary=f"Sent the admin covenant to {sum(1 for d in done if d['ok'])} admins",
                     payload={"version": text.VERSION, "sent": [d["name"] for d in done if d["ok"]],
                              "hashes": {d["name"]: d.get("hash") for d in done if d["ok"]}})
    return {"ok": all(d["ok"] for d in done), "sent": [d["name"] for d in done if d["ok"]],
            "failed": [d["name"] for d in done if not d["ok"]]}
