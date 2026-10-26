# worship_ministries.py — ministries send their own announcements (ChurchSavvy
# round 5, canvas UZu4VsoY9KemkUGorz234j boards 18 and 20; idea A5: "Each
# ministry leader gets a link, like the volunteers' links, to send an
# announcement by Thursday. The office approves it and it lands on the board
# with its dates. A Wednesday reminder email goes out.").
#
# Signed in, the plan's part (planner, worship leader, admin), behind the
# screens switch (worship_router.mode()):
#   GET    /worship/ministries                 each ministry, with its link
#   POST   /worship/ministries                 a new one
#   PUT    /worship/ministries/{id}            change one
#   POST   /worship/ministries/{id}/new-link   a new link; the old one stops working
#   DELETE /worship/ministries/{id}            take it out; its link stops working
# Its link, with no sign-in (signed; names one church and one ministry):
#   GET    /worship/send/{link}                the church, the ministry, when it's due
#   POST   /worship/send/{link}                send one: it waits on the board for the office
#   POST   /worship/send/{link}/picture        a slot for one picture, into the church's library
#   POST   /worship/send/{link}/picture/{id}   the picture is in: checked, and its address
#   POST   /worship/send/{link}/reminders      {on}: Wednesday's reminder stopped, or started again
#   POST   /worship/send/{link}/stop           the email client's one-click "stop these reminders"
#
# The link picks the church and the ministry; nothing the caller sends can
# name another. What a ministry sends waits for the office (status
# "waiting", source "ministry") and shows only where a ministry may ask for:
# Sunday's slides and the lobby. The office's answer reaches the leader by
# email (tell_leader, from the board's decide), and on Wednesday from 9 AM on
# the church's clock each leader who wants one hears "anything for Sunday?"
# (sweep_tick), once a week.
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import worship_announce as wa
from auth_supabase import AuthedUser, require_user
from worship_router import mode
from worship_show_router import _q, _read, _staff, _uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

PURPOSE = "ministry-link"
VERSION = 1
MAX_MINISTRIES = 40
MAX_WAITING = 10                  # one ministry's requests waiting for the office at once
DUE = "Thursday"                  # in by Thursday for Sunday (board 20)
REMIND_WEEKDAY = 2                # Wednesday (Monday is 0)
REMIND_HOURS = (9, 20)            # on the church's clock
NOTE_LIMIT = 300
MAX_PICTURE_BYTES = 10 * 1024 * 1024
PICTURE_TYPES = ("image/png", "image/jpeg", "image/webp")
MINISTRY_SHOWS = ("room", "lobby")  # phones and the stream are the office's to add
MAX_UPLOADING = 30                # pictures on their way into one church's library from links, a day
_FIELDS = "id,business_id,name,leader_name,leader_email,remind,link_n,reminded_on,archived_at,created_at,updated_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── the link ────────────────────────────────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key(business_id: str) -> bytes:
    from customer_token import derive_key
    return derive_key(PURPOSE, str(business_id))


def sign(business_id: str, ministry_id: str, n: int) -> str:
    claims = {"v": VERSION, "biz": str(business_id), "m": str(ministry_id), "n": int(n)}
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_key(business_id), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify(token: str) -> Optional[Dict[str, Any]]:
    """The link's claims when it is genuine, else None. The church named inside
    picks the key, so a link edited to name another church fails its own
    signature. It doesn't expire: a new link, or taking the ministry out,
    retires it. Never raises."""
    try:
        payload, sig = (token or "").strip().split(".", 1)
        claims = json.loads(_unb64(payload))
        biz = str(claims.get("biz") or "")
        if claims.get("v") != VERSION or not biz or not str(claims.get("m") or "") or type(claims.get("n")) is not int:
            return None
        want = _b64(hmac.new(_key(biz), payload.encode("ascii"), hashlib.sha256).digest())
        return claims if hmac.compare_digest(want, sig) else None
    except Exception:  # noqa: BLE001 — a bad link is just a bad link
        return None


def page_url(token: str, **params: str) -> str:
    """The send page: ChurchSavvy's own (CHURCHSAVVY_APP_URL once it has its
    domain), else the app's /churchsavvy, as the volunteers' links."""
    import app_base
    base = ((os.environ.get("CHURCHSAVVY_APP_URL") or "").strip().rstrip("/")
            or f"{app_base.app_base_url()}/churchsavvy")
    extra = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items() if v)
    return f"{base}/send/{token}" + (f"?{extra}" if extra else "")


def one_click_url(token: str) -> str:
    """The List-Unsubscribe address: this server, which mysolutionist.app also serves."""
    domain = os.environ.get("APP_DOMAIN", "https://mysolutionist.app").rstrip("/")
    return f"{domain}/worship/send/{quote(token, safe='')}/stop"


def link_of(row: Dict[str, Any]) -> str:
    return sign(row["business_id"], row["id"], int(row.get("link_n") or 1))


def ministry_from_link(token: str) -> Dict[str, Any]:
    """The ministry a link opens: genuine, its church's, not taken out, and the newest link."""
    if mode() == "off":
        raise HTTPException(404, "Not Found")
    claims = verify(token)
    if not claims:
        raise HTTPException(410, "This link isn't right. Ask your church office for it again.")
    rows = _read(f"/worship_ministries?id=eq.{_q(claims['m'])}&business_id=eq.{_q(claims['biz'])}&select={_FIELDS}&limit=1",
                 "The ministry")
    if not rows or rows[0].get("archived_at") or int(rows[0].get("link_n") or 0) != claims["n"]:
        raise HTTPException(410, "This link was changed or taken out. Ask your church office for the new one.")
    return rows[0]


def _church(biz_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,settings&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn't be opened just now. Try again.")
    if not rows:
        raise HTTPException(410, "This church isn't on ChurchSavvy anymore.")
    return rows[0]


# ─── the church's ministries (signed in) ─────────────────────────────


def clean(body: Dict[str, Any], partial: bool = False) -> Dict[str, Any]:
    import academy_join
    out: Dict[str, Any] = {}
    if not partial or "name" in body:
        name = " ".join(str(body.get("name") or "").split())
        if not 1 <= len(name) <= 60:
            raise ValueError("Give the ministry a name, up to 60 letters")
        out["name"] = name
    if not partial or "leader_name" in body:
        out["leader_name"] = " ".join(str(body.get("leader_name") or "").split())[:80]
    if not partial or "leader_email" in body:
        email = str(body.get("leader_email") or "").strip()
        if email and (len(email) > 254 or not academy_join.valid_email(email)):
            raise ValueError("That email doesn't look right")
        out["leader_email"] = email
    if "remind" in body:
        out["remind"] = bool(body.get("remind"))
    return out


def _out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "name": row.get("name") or "", "leader_name": row.get("leader_name") or "",
            "leader_email": row.get("leader_email") or "", "remind": row.get("remind") is not False,
            "link": page_url(link_of(row))}


def _mine(biz: str, mid: str) -> Dict[str, Any]:
    rows = _read(f"/worship_ministries?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}&archived_at=is.null&select={_FIELDS}&limit=1",
                 "The ministry")
    if not rows:
        raise HTTPException(404, "ministry not found")
    return rows[0]


def _list(biz: str) -> List[Dict[str, Any]]:
    return _read(f"/worship_ministries?business_id=eq.{_q(biz)}&archived_at=is.null&select={_FIELDS}"
                 f"&order=name.asc&limit={MAX_MINISTRIES}", "Your ministries")


@router.get("/ministries")
def list_ministries(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user, "plan")
    return {"ministries": [_out(r) for r in _list(biz)], "due": DUE}


@router.post("/ministries")
def add_ministry(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    try:
        fields = clean(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    have = _list(biz)
    if len(have) >= MAX_MINISTRIES:
        raise HTTPException(400, f"A church has up to {MAX_MINISTRIES} ministry links")
    if any((r.get("name") or "").lower() == fields["name"].lower() for r in have):
        raise HTTPException(409, f"There's already a link for {fields['name']}")
    now = _now()
    rows = sb_clients.sb_post_as_service(f"/worship_ministries?select={_FIELDS}", {
        "business_id": biz, **fields, "remind": fields.get("remind", True), "link_n": 1, "created_at": now, "updated_at": now},
        prefer="return=representation")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The ministry wasn't saved. Try again.")
    return {"ministry": _out(rows[0])}


@router.put("/ministries/{ministry_id}")
def save_ministry(ministry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "plan")
    cur = _mine(biz, _uuid(ministry_id, "ministry"))
    try:
        change = clean({k: v for k, v in body.items() if k != "business_id"}, partial=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if "name" in change and any((r.get("name") or "").lower() == change["name"].lower() and r["id"] != cur["id"] for r in _list(biz)):
        raise HTTPException(409, f"There's already a link for {change['name']}")
    change["updated_at"] = _now()
    rows = sb_clients.sb_patch_as_service(f"/worship_ministries?id=eq.{_q(cur['id'])}&business_id=eq.{_q(biz)}&select={_FIELDS}", change)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The change wasn't saved. Try again.")
    return {"ministry": _out(rows[0])}


@router.post("/ministries/{ministry_id}/new-link")
def new_ministry_link(ministry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user, "plan")
    cur = _mine(biz, _uuid(ministry_id, "ministry"))
    rows = sb_clients.sb_patch_as_service(f"/worship_ministries?id=eq.{_q(cur['id'])}&business_id=eq.{_q(biz)}&select={_FIELDS}",
                                          {"link_n": int(cur.get("link_n") or 1) + 1, "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The new link wasn't made. The old one still works; try again.")
    return {"ministry": _out(rows[0])}


@router.delete("/ministries/{ministry_id}")
def remove_ministry(ministry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user, "plan")
    cur = _mine(biz, _uuid(ministry_id, "ministry"))
    rows = sb_clients.sb_patch_as_service(f"/worship_ministries?id=eq.{_q(cur['id'])}&business_id=eq.{_q(biz)}&select=id",
                                          {"archived_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "It wasn't taken out. Try again.")
    return {"ok": True}


# ─── the link's page (no sign-in) ────────────────────────────────────


@router.get("/send/{link}")
def open_send(link: str):
    import serve_links
    m = ministry_from_link(link)
    return {"church": serve_links.church_card(_church(m["business_id"])), "ministry": m["name"],
            "leader": (m.get("leader_name") or "").split(" ")[0], "due": DUE, "remind": m.get("remind") is not False,
            "can_remind": bool(m.get("leader_email")), "shows": list(MINISTRY_SHOWS)}


def picture_prefix(biz: str) -> str:
    """Where a picture sent from the link lives: the church's own library."""
    import worship_media_router as wm
    return wm.public_url(f"{biz}/worship-")


@router.post("/send/{link}")
def send_announcement(link: str, body: Dict[str, Any]):
    from worship_announce_router import church_today
    m = ministry_from_link(link)
    biz = m["business_id"]
    body = body or {}
    try:
        row = wa.clean({k: body.get(k) for k in ("title", "when", "where", "body", "image_url", "event_on", "show_from", "show_until", "shows")})
    except ValueError as e:
        raise HTTPException(400, str(e))
    row["shows"] = {k: bool(row["shows"].get(k)) and k in MINISTRY_SHOWS for k in wa.WHERE}
    if not any(row["shows"].values()):
        raise HTTPException(400, "Pick where it should show")
    if row.get("image_url") and not re.fullmatch(re.escape(picture_prefix(biz)) + r"[0-9a-f-]{36}\.(png|jpg|webp)", row["image_url"]):
        # Exactly a picture in this church's library: nothing after the prefix can walk elsewhere.
        raise HTTPException(400, "Add the picture here, from your phone or computer")
    if not row.get("show_until"):
        row["show_until"] = wa.until_default(row.get("event_on"))
        if row["show_until"] and row.get("show_from") and row["show_from"] > row["show_until"]:
            row["show_until"] = row["show_from"]
    waiting = _read(f"/worship_announcements?business_id=eq.{_q(biz)}&source=eq.ministry&source_ref=eq.{_q(m['id'])}"
                    f"&status=eq.waiting&archived_at=is.null&select=id&limit={MAX_WAITING}", "The announcements")
    if len(waiting) >= MAX_WAITING:
        raise HTTPException(429, f"{m['name']} has {MAX_WAITING} waiting for the office already. Once they've looked, send more.")
    have = _read(f"/worship_announcements?business_id=eq.{_q(biz)}&archived_at=is.null&select=id&limit={wa.MAX_PER_CHURCH}",
                 "The announcements")
    if len(have) >= wa.MAX_PER_CHURCH:
        raise HTTPException(409, "The church's board is full just now. Ask the office.")
    now = _now()
    saved = sb_clients.sb_post_as_service(f"/worship_announcements?select=id,title,event_on,when_text,where_text,shows", {
        "business_id": biz, **row, "status": "waiting", "source": "ministry", "source_ref": m["id"],
        "sent_by": {"ministry": m["name"], "name": m.get("leader_name") or "", "email": m.get("leader_email") or "", "at": now},
        "created_at": now, "updated_at": now,
    }, prefer="return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "It wasn't sent. Try again.")
    a = saved[0]
    return {"ok": True, "announcement": {"title": a.get("title"), "event_on": a.get("event_on"), "when": a.get("when_text") or "",
                                          "where": a.get("where_text") or "", "shows": a.get("shows") or {}},
            "today": church_today(biz).isoformat()}


@router.post("/send/{link}/picture")
def send_picture_start(link: str, body: Dict[str, Any]):
    import worship_media_router as wm
    m = ministry_from_link(link)
    biz = m["business_id"]
    body = body or {}
    mime = str(body.get("mime") or "")
    if mime not in PICTURE_TYPES:
        raise HTTPException(400, "Use a PNG, JPG or WebP picture")
    size = body.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_PICTURE_BYTES:
        raise HTTPException(400, f"A picture is at most {MAX_PICTURE_BYTES // (1024 * 1024)} MB")
    have = sb_clients.sb_get_as_service(f"/worship_media?business_id=eq.{_q(biz)}&archived_at=is.null&status=eq.ready&select=bytes")
    if have is None:
        raise HTTPException(503, "That couldn't be prepared. Try again.")
    if sum(int(r.get("bytes") or 0) for r in have) + size > wm.LIBRARY_BYTES:
        raise HTTPException(409, "The church's library is full. Send it without a picture, and the office can add one.")
    # A link someone passed around can't fill the library with half-sent pictures.
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    going = sb_clients.sb_get_as_service(f"/worship_media?business_id=eq.{_q(biz)}&status=eq.uploading&archived_at=is.null"
                                         f"&created_at=gte.{_q(since)}&select=id&limit={MAX_UPLOADING}")
    if going is None:
        raise HTTPException(503, "That couldn't be prepared. Try again.")
    if len(going) >= MAX_UPLOADING:
        raise HTTPException(429, "Too many pictures are on their way just now. Send it without one, or try again tomorrow.")
    mid = str(uuid.uuid4())
    object_name = f"{biz}/worship-{mid}.{wm.TYPES[mime][1]}"
    name = f"{m['name']}: {str(body.get('name') or 'Picture').strip()}"[:120]
    rows = sb_clients.sb_post_as_service(f"/worship_media?select={wm._FIELDS}", {
        "id": mid, "business_id": biz, "kind": "image", "name": name, "object_name": object_name, "mime": mime,
        "bytes": size, "status": "uploading", "created_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That couldn't be prepared. Try again.")
    return {"media_id": mid, "upload": {
        "endpoint": wm.resumable_endpoint(), "token": wm.upload_token(object_name), "bucket": wm.BUCKET,
        "object_name": object_name, "content_type": mime, "chunk_size": wm.CHUNK_BYTES}}


@router.post("/send/{link}/picture/{media_id}")
def send_picture_finish(link: str, media_id: str):
    import worship_media_router as wm
    m = ministry_from_link(link)
    row = wm._own(m["business_id"], _uuid(media_id, "picture"))
    if row.get("kind") != "image":
        raise HTTPException(400, "That isn't a picture")
    done = wm.finish(m["business_id"], row)
    return {"url": done.get("url")}


def _set_remind(m: Dict[str, Any], on: bool) -> None:
    rows = sb_clients.sb_patch_as_service(f"/worship_ministries?id=eq.{_q(m['id'])}&business_id=eq.{_q(m['business_id'])}&select=id",
                                          {"remind": bool(on), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That wasn't saved. Try again.")


@router.post("/send/{link}/reminders")
def send_reminders(link: str, body: Dict[str, Any]):
    m = ministry_from_link(link)
    on = (body or {}).get("on")
    if not isinstance(on, bool):
        raise HTTPException(400, "On or off")
    _set_remind(m, on)
    return {"ok": True, "remind": on}


@router.post("/send/{link}/stop")
def stop_reminders(link: str):
    """RFC 8058 one-click: the email client stops Wednesday's reminder, nothing else."""
    _set_remind(ministry_from_link(link), False)
    return {"ok": True}


# ─── the leader hears (the office's answer, Wednesday's reminder) ────


def _span(row: Dict[str, Any]) -> str:
    def day(v: Optional[str]) -> str:
        d = date.fromisoformat(v) if v else None
        return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}" if d else ""
    f, u = day(row.get("show_from")), day(row.get("show_until"))
    return f"from {f} until {u}" if f and u else f"until {u}" if u else f"from {f}" if f else ""


def _where_words(shows: Dict[str, Any]) -> str:
    parts = [w for k, w in (("room", "on Sunday's slides"), ("lobby", "in the lobby"), ("online", "on the stream"),
                            ("phones", "on phones")) if (shows or {}).get(k)]
    return " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 2 else parts)


def answer_words(church: str, row: Dict[str, Any], decision: str, note: str) -> Dict[str, str]:
    title = row.get("title") or "Your announcement"
    if decision == "on":
        when = " ".join(x for x in (_span(row), _where_words(row.get("shows") or {})) if x)
        body = f"{church}'s office put “{title}” on the board." + (f" It shows {when}." if when else "")
        if note:
            body += f"\n\nFrom the office: “{note}”"
        return {"subject": f"“{title}” is on the screens", "body": body}
    body = f"{church}'s office didn't put “{title}” on the screens this time."
    body += f"\n\nThey said: “{note}”" if note else " If you'd like to know why, ask the office."
    return {"subject": f"“{title}” isn't on the screens this time", "body": body}


async def _send(biz: Dict[str, Any], m: Dict[str, Any], subject: str, body: str, cta_label: str, key: str) -> None:
    import email_layout
    import email_sender
    import serve_links
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    church = serve_links.church_card(biz)["name"]
    token = link_of(m)
    html = email_layout.render_html(
        body, business_name=church, brand=email_layout.brand_of(settings), sig=None,
        unsubscribe_url=page_url(token, stop="1"), unsubscribe_label="Stop Wednesday's reminders", preheader=body[:90],
        cta=(cta_label, page_url(token)), disclaimer=f"You lead {m.get('name')} at {church}.", footer_note="Sent with ChurchSavvy")
    await email_sender.send_via_resend(
        to_email=m["leader_email"], to_name=m.get("leader_name") or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app", from_name=church,
        subject=subject[:150], body=html, reply_to=None, business_id=str(biz["id"]), idempotency_key=key,
        unsubscribe_url=one_click_url(token))


def tell_leader(biz_id: str, row: Dict[str, Any], decision: str, note: str = "") -> bool:
    """The office put a ministry's announcement on, or not: its leader hears by
    email. A failed email never undoes the answer. True when it went."""
    import academy_join
    if row.get("source") != "ministry" or not row.get("source_ref"):
        return False
    try:
        rows = sb_clients.sb_get_as_service(
            f"/worship_ministries?id=eq.{_q(row['source_ref'])}&business_id=eq.{_q(biz_id)}&select={_FIELDS}&limit=1") or []
        m = rows[0] if rows else None
        if not m or m.get("archived_at") or not academy_join.valid_email(str(m.get("leader_email") or "")):
            return False
        biz = _church(biz_id)
        w = answer_words(biz.get("name") or "Your church", row, decision, note)
        asyncio.run(_send(biz, m, w["subject"], w["body"], "Send another", f"ministry-answer-{row['id']}-{decision}"))
        return True
    except Exception:  # noqa: BLE001 — the answer stands either way
        logger.warning("ministries: the leader's email failed for %s", str(row.get("id"))[:8], exc_info=True)
        return False


def remind_words(church: str, m: Dict[str, Any]) -> Dict[str, str]:
    first = (m.get("leader_name") or "").split(" ")[0]
    hi = f"Hi {first}, anything" if first else "Anything"
    return {"subject": "Anything for Sunday?",
            "body": f"{hi} from {m.get('name')} for Sunday's screens at {church}? Send it by {DUE}, and the office can put it on."}


def due_now(local: datetime) -> bool:
    """Wednesday, between 9 AM and 8 PM on the church's clock."""
    return local.weekday() == REMIND_WEEKDAY and REMIND_HOURS[0] <= local.hour < REMIND_HOURS[1]


def _release(m: Dict[str, Any], today: date) -> None:
    """A reminder that didn't go: the claim goes back, so the next sweep tries again
    (Resend's idempotency key keeps a retry from sending twice)."""
    sb_clients.sb_patch_as_service(
        f"/worship_ministries?id=eq.{_q(m['id'])}&business_id=eq.{_q(m['business_id'])}&reminded_on=eq.{today.isoformat()}&select=id",
        {"reminded_on": m.get("reminded_on")})


def _claim(m: Dict[str, Any], today: date) -> bool:
    """This week's reminder, once: only the sweep that moves reminded_on to today sends it."""
    rows = sb_clients.sb_patch_as_service(
        f"/worship_ministries?id=eq.{_q(m['id'])}&business_id=eq.{_q(m['business_id'])}"
        f"&or=(reminded_on.is.null,reminded_on.lt.{today.isoformat()})&select=id", {"reminded_on": today.isoformat()})
    return isinstance(rows, list) and len(rows) == 1


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 30 minutes: on Wednesday, each leader who wants it hears once."""
    import academy_join
    import churchsavvy_billing as csb
    from worship_announce_router import church_zone
    out = {"reminded": 0, "failed": 0}
    if mode() == "off":
        return out
    rows = sb_clients.sb_get_as_service(f"/worship_ministries?archived_at=is.null&remind=is.true&select={_FIELDS}&limit=5000") or []
    by_church: Dict[str, List[Dict[str, Any]]] = {}
    for m in rows:
        if academy_join.valid_email(str(m.get("leader_email") or "")):
            by_church.setdefault(str(m["business_id"]), []).append(m)
    now = now or datetime.now(timezone.utc)
    for biz_id, ministries in by_church.items():
        try:
            local = now.astimezone(church_zone(biz_id))
            if not due_now(local):
                continue
            got = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,settings,{csb.BILLING_FIELDS}&limit=1") or []
            if not got or csb.lapsed(got[0], "screens"):
                continue
            biz = got[0]
            church = (biz.get("name") or "").strip() or "Your church"
            for m in ministries:
                if str(m.get("reminded_on") or "") == local.date().isoformat() or not _claim(m, local.date()):
                    continue
                w = remind_words(church, m)
                try:
                    asyncio.run(_send(biz, m, w["subject"], w["body"], "Send an announcement",
                                      f"ministry-remind-{m['id']}-{local.date().isoformat()}"))
                    out["reminded"] += 1
                except Exception:  # noqa: BLE001 — one address never stops the rest
                    out["failed"] += 1
                    logger.warning("ministries: one reminder failed", exc_info=True)
                    _release(m, local.date())
        except Exception:  # noqa: BLE001
            logger.warning("ministries: one church's reminders failed", exc_info=True)
    return out
