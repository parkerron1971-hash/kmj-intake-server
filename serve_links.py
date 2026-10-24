# serve_links.py — ChurchSavvy Planning by email: a volunteer answers an
# ask, sees their Sunday and says "I'm here" from a link in the email, with
# no sign-in and no app (design canvas UZu4VsoY9KemkUGorz234j, boards 12
# "The ask, by email", 13 "One tap to answer" and 14 "Their Sunday, on the
# web"; Kevin 2026-10-24: "develop small planning that would work and allow
# for at least emails to go out").
#
#   GET  /serve-link/view?t=           the ask or their Sunday, as the page shows it
#   GET  /serve-link/who?t=            the church and their first name (the stop page)
#   POST /serve-link/answer            {t, ans: yes|no|other, why?, offer?}
#   POST /serve-link/why               {t, why}: why they can't, if they want to say
#   POST /serve-link/here              {t}: "I'm here", on the day
#   POST /serve-link/email             {t, on}: stop these emails, or start them again
#   POST /serve-link/stop?t=           the email client's one-click unsubscribe
#
# A link is signed (customer_token.derive_key, its own purpose) and names
# one church, one person and, for an ask, one place on one Sunday. The church
# comes from the link, never from the caller, and every change goes through
# sunday_serving with that person: a link can only answer its own ask, read
# its own Sunday and stop its own emails at that one church. An answer link
# lapses a few days after its Sunday; a stop link lasts a year.
#
# Opening a link changes nothing. The page asks for the answer it was opened
# with (?ans=yes), so a mail scanner that fetches every link in an email
# can't say yes for anyone.
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

import sb_clients
import sunday_planning as sp
import sunday_serving as ss

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/serve-link", tags=["planning"])

PURPOSE = "serve-link"
VERSION = 1
ANSWER_GRACE_DAYS = 3        # an ask's link still opens this long after its Sunday
STOP_DAYS = 400              # "Stop these emails" keeps working for a year and more


# ─── the link ────────────────────────────────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key(business_id: str) -> bytes:
    from customer_token import derive_key
    return derive_key(PURPOSE, str(business_id))


def sign(business_id: str, contact_id: str, assignment_id: Optional[str], expires: int) -> str:
    claims = {"v": VERSION, "biz": str(business_id), "cid": str(contact_id), "exp": int(expires)}
    if assignment_id:
        claims["a"] = str(assignment_id)
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_key(business_id), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify(token: str, now: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The link's claims when it is genuine and unexpired, else None. The
    church named inside picks the key, so a link edited to name another
    church fails its own signature. Never raises."""
    try:
        payload, sig = (token or "").strip().split(".", 1)
        claims = json.loads(_unb64(payload))
        biz = str(claims.get("biz") or "")
        if claims.get("v") != VERSION or not biz or not str(claims.get("cid") or ""):
            return None
        want = _b64(hmac.new(_key(biz), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        if int(claims.get("exp") or 0) <= int(now if now is not None else time.time()):
            return None
        return claims
    except Exception:  # noqa: BLE001 — a bad link is just a bad link
        return None


def answer_token(business_id: str, contact_id: str, assignment_id: str, sunday: datetime) -> str:
    return sign(business_id, contact_id, assignment_id,
                int((sunday + timedelta(days=ANSWER_GRACE_DAYS)).timestamp()))


def stop_token(business_id: str, contact_id: str, now: Optional[int] = None) -> str:
    return sign(business_id, contact_id, None, int(now if now is not None else time.time()) + STOP_DAYS * 86400)


def page_url(token: str, **params: str) -> str:
    """The page a link opens: ChurchSavvy's own (CHURCHSAVVY_APP_URL once it
    has its domain), else the app's /churchsavvy."""
    import app_base
    base = ((os.environ.get("CHURCHSAVVY_APP_URL") or "").strip().rstrip("/")
            or f"{app_base.app_base_url()}/churchsavvy")
    extra = "".join(f"&{k}={quote(v, safe='')}" for k, v in params.items() if v)
    return f"{base}/a/{token}" + (f"?{extra[1:]}" if extra else "")


def one_click_url(token: str) -> str:
    """The List-Unsubscribe address: this server, which mysolutionist.app
    also serves (the same host as the platform's own unsubscribe)."""
    domain = os.environ.get("APP_DOMAIN", "https://mysolutionist.app").rstrip("/")
    return f"{domain}/serve-link/stop?t={quote(token, safe='')}"


# ─── who the link is ─────────────────────────────────────────────────


def _claims(token: str, ask: bool = True) -> Dict[str, Any]:
    claims = verify(token)
    if not claims:
        raise HTTPException(410, "This link has run out. Your church can send you a new one.")
    if ask and not claims.get("a"):
        raise HTTPException(404, "This link doesn't open a Sunday.")
    return claims


def _church(biz_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{quote(biz_id, safe='')}&select=id,name,settings&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't be opened just now. Try again.")
    if not rows:
        raise HTTPException(410, "This church isn't on ChurchSavvy anymore.")
    return rows[0]


def _person(biz_id: str, cid: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{quote(cid, safe='')}&business_id=eq.{quote(biz_id, safe='')}&select=id,name&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't be opened just now. Try again.")
    if not rows:
        raise HTTPException(410, "This link isn't for anyone at this church anymore.")
    return rows[0]


def _open(biz: Dict[str, Any]) -> None:
    """Planning's own switch decides, as it does for the member app."""
    if not ss.on():
        raise HTTPException(404, "Not Found")


def church_card(biz: Dict[str, Any]) -> Dict[str, Any]:
    """The church's name and look for the page's header: its name leads,
    ChurchSavvy signs off small at the bottom (board 12)."""
    import email_layout
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    brand = email_layout.brand_of(settings)
    name = (biz.get("name") or "").strip() or "Your church"
    letters = "".join(w[0] for w in name.split()[:2]).upper() or "C"
    return {"name": name, "initials": letters, "logo": brand.get("logo_url") or None,
            "color": brand.get("primary") or None}


# ─── saying when ─────────────────────────────────────────────────────


def _clock(hhmm: Optional[str]) -> str:
    if not hhmm:
        return ""
    h, m = int(hhmm[:2]), hhmm[3:5]
    return f"{(h % 12) or 12}:{m} {'PM' if h >= 12 else 'AM'}"


def _when(at: datetime) -> Dict[str, str]:
    return {"day": f"{at.strftime('%A')}, {at.strftime('%b')} {at.day}",
            "short": f"{at.strftime('%b')} {at.day}", "time": _clock(at.strftime("%H:%M"))}


def _arrive(at: datetime, call: Optional[str]) -> str:
    return _clock(call) if call else _clock(at.strftime("%H:%M"))


# ─── the page ────────────────────────────────────────────────────────


def view(token: str) -> Dict[str, Any]:
    claims = _claims(token)
    biz_id, cid, aid = claims["biz"], claims["cid"], claims["a"]
    biz = _church(biz_id)
    _open(biz)
    person = _person(biz_id, cid)
    out: Dict[str, Any] = {"church": church_card(biz), "first": ((person.get("name") or "").strip().split(" ") or [""])[0],
                           "email_on": ss.emails_on(biz_id, cid), "whys": list(ss.WHY)}
    try:
        a = ss.ask_view(biz, cid, aid)
    except HTTPException as e:
        if e.status_code in (404, 409):
            return {**out, "gone": True, "message": e.detail}
        raise
    at: datetime = a["at"]
    free = [{"id": f["id"], **_when(f["at"])} for f in ss.free_sundays(biz_id, cid, at.tzinfo, at)] \
        if a["status"] in ("asked", "no") and not a["cover"] else []
    out["ask"] = {
        "id": a["id"], "status": a["status"], "cover": a["cover"], "cover_from": a["cover_from"],
        "place": a["place"], "team": a["team"], "title": a["title"], "asked_by": a["asked_by"] or None,
        "leader": a["leader"], "arrive": _arrive(at, a.get("call_time")), "past": a["past"], **_when(at),
        "with": [{"name": w["name"], "place": w["place"], "status": w["status"]} for w in a["with"]],
        "free": free,
    }
    if a["status"] == "yes" and not a["cover"] and not a["past"]:
        try:
            p = ss.pack(biz, cid, aid)
            out["pack"] = {"role": p["role"], "roles": p["roles"], "songs": p["songs"], "moments": p["moments"],
                           "order": p["order"], "here_open": p["here_open"], "past": p["past"]}
        except HTTPException:
            out["pack"] = None
    return out


@router.get("/view")
def open_link(t: str):
    return view(t)


@router.get("/who")
def who(t: str):
    """The church and the first name a link is for, and whether this
    church's serving emails still reach them: the Stop these emails page
    names the church before anything changes. Any genuine link reads it."""
    claims = _claims(t, ask=False)
    biz = _church(claims["biz"])
    person = _person(claims["biz"], claims["cid"])
    return {"church": church_card(biz), "first": ((person.get("name") or "").strip().split(" ") or [""])[0],
            "email_on": ss.emails_on(claims["biz"], claims["cid"])}


def _body_token(body: Dict[str, Any]) -> str:
    t = body.get("t") if isinstance(body, dict) else None
    if not isinstance(t, str) or not t:
        raise HTTPException(400, "This link is missing its code.")
    return t


@router.post("/answer")
def answer(body: Dict[str, Any]):
    t = _body_token(body)
    claims = _claims(t)
    biz = _church(claims["biz"])
    _open(biz)
    ans = str(body.get("ans") or "")
    why = str(body.get("why") or "")
    offer = body.get("offer")
    ss.answer(biz, claims["cid"], claims["a"], ans, why, offer=str(offer) if offer else None)
    return view(t)


@router.post("/why")
def why(body: Dict[str, Any]):
    t = _body_token(body)
    claims = _claims(t)
    biz = _church(claims["biz"])
    _open(biz)
    ss.set_why(biz, claims["cid"], claims["a"], str(body.get("why") or ""))
    return view(t)


@router.post("/here")
def here(body: Dict[str, Any]):
    t = _body_token(body)
    claims = _claims(t)
    biz = _church(claims["biz"])
    _open(biz)
    ss.here(biz, claims["cid"], claims["a"])
    return view(t)


@router.post("/email")
def email(body: Dict[str, Any]):
    """Stop these emails, or start them again: this church's serving emails
    for this one person, nothing else (never the platform-wide block, which
    would also stop their sign-in codes)."""
    t = _body_token(body)
    claims = _claims(t, ask=False)
    biz = _church(claims["biz"])
    _person(claims["biz"], claims["cid"])
    if body.get("on") is True:
        ss.set_hearing(biz, claims["cid"], "email", True)
    else:
        ss.stop_emails(biz, claims["cid"])
    return {"church": church_card(biz), "email_on": ss.emails_on(claims["biz"], claims["cid"])}


@router.post("/stop")
async def one_click(request: Request, t: str = ""):
    """RFC 8058 one-click unsubscribe: the mail client POSTs here with
    List-Unsubscribe=One-Click. Same effect as the page's button."""
    claims = verify(t)
    if not claims:
        return PlainTextResponse("This link has run out.", status_code=410)
    try:
        biz = _church(claims["biz"])
        _person(claims["biz"], claims["cid"])
        ss.stop_emails(biz, claims["cid"])
    except HTTPException as e:
        return PlainTextResponse(str(e.detail), status_code=e.status_code)
    return PlainTextResponse(f"You won't get serving emails from {church_card(biz)['name']} anymore.")
