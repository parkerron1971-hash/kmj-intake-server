"""
member_portal_safety.py — the Safety room on a pastoral leader's Lead tab.

Kevin, 2026-10-20: a church's safety officers can be picked "from the
Pastors and Elders you've already named" — no team login needed (part 2 of
the approved canvas "Church Groups, Together"). The owner names them on the
Messaging page (messaging_router: msg_member_officers); this is where they
work, in the member app they already sign in to:

    GET  /my/lead/safety                 messages the check held, and open reports
    GET  /my/lead/safety/chat/<thread>   a whole chat, after a look was logged
    POST /my/lead/safety/act             {message_id, action: release|remove}
    POST /my/lead/safety/close           {report_id, outcome}
    POST /my/lead/safety/open            {thread_id, reason} — logged; its people are told
    POST /my/lead/safety/pause           {contact_id} — turn their messaging off

The same rules as the team's Safety room (messaging_router, whose functions
do the work): an officer sees only what the check held or someone reported;
opening a whole chat needs a reason, is logged with their name, and the
people in that chat see that a safety officer reviewed it. Someone stays an
officer only while the owner keeps them named AND they hold an active
pastoral role (senior or pastoral job in Leaders & roles). The owner's
preview never sees this.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_portal_safety")
router = APIRouter(tags=["member-portal"])

UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
LOOK_MINUTES = 30
FLAGS = {"harm": "Held: it may be harmful", "self_harm": "Held: someone may be hurting"}

DONE = {
    "released": "Released. Everyone in that chat can see it now.",
    "removed": "Removed. Nobody sees it any more.",
    "closed": "Report closed.",
    "paused": "Their messaging is paused. The church office can turn it back on.",
}
ERRORS = {
    "not_officer": "Only the church's safety officers can open the Safety room.",
    "reason": "Say why you're opening the whole chat first. It's logged and its people are told.",
    "error": "That didn't save. Please try again in a moment.",
    "preview": "This is a preview, so nothing is saved.",
    "slow": "That's a lot at once. Wait a few minutes, then try again.",
    "gone": "That isn't here any more.",
}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def is_officer(business_id: str, contact_id: str) -> Optional[bool]:
    """Named by the owner AND holding an active pastoral role. None when a
    read failed (the page says try again; it never opens on a failed read)."""
    import messaging_router as mr
    import church_roles as cr
    named = sb_clients.sb_get_as_service(
        f"/msg_member_officers?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&select=contact_id&limit=1")
    if named is None:
        return None
    if not named:
        return False
    roles = sb_clients.sb_get_as_service(
        f"/church_leader_roles?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        f"&status=eq.active&select=role&limit=50")
    defs = cr.defs(str(business_id))
    if roles is None or defs is None:
        return None
    by = cr.by_key(defs)
    return any((by.get(r["role"]) or cr.LEGACY.get(r["role"]) or {}).get("job") in mr.PASTORAL_JOBS for r in roles)


def waiting(business_id: str, contact_id: str) -> Optional[int]:
    """How many things wait for the officers, when this person is one; None
    when they aren't (or it can't be told)."""
    if not is_officer(business_id, contact_id):
        return None
    import messaging_router as mr
    try:
        items = mr.safety_items(str(business_id))
    except HTTPException:
        return None
    return len(items["held"]) + len(items["reports"])


def card(n: Optional[int]) -> str:
    """The Safety room's door on the Lead page (officers only)."""
    if n is None:
        return ""
    import member_app_ui as ui
    line = (f"{n} waiting for a safety officer" if n else "Nothing waiting. Every message is checked before it's delivered.")
    return (f'<a class="sf-door{" has-n" if n else ""}" href="/my/lead/safety">{ui.icon("shield", 20)}'
            f'<span><b>Safety room</b><small>{line}</small></span>{ui.icon("chevron", 18)}</a>')


SAFETY_CSS = """
.sf-photo{display:block;max-width:min(320px,100%);height:auto;border-radius:14px;margin:0 0 8px;}
.sf-door{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:var(--r-md);background:var(--s1);color:var(--fg);
  text-decoration:none;margin:0 0 14px;}
.sf-door.has-n{background:var(--coral-deep,var(--s1));}
.sf-door span{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.sf-door b{font-size:16px;font-weight:650;}
.sf-door small{font-size:13.5px;color:var(--fg2);}
.sf-wrap{max-width:760px;display:flex;flex-direction:column;gap:12px;}
.sf-item{background:var(--s1);border-radius:var(--r-lg);padding:16px;display:flex;flex-direction:column;gap:10px;}
.sf-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;font-size:13px;color:var(--fg2);}
.sf-meta b{color:var(--fg);font-size:14.5px;}
.sf-flag{display:inline-flex;align-items:center;height:24px;padding:0 10px;border-radius:999px;background:var(--coral-deep,var(--s2));
  color:var(--coral-ink,var(--fg));font-size:12px;font-weight:700;}
.sf-body{margin:0;padding:12px 14px;border-radius:14px;background:var(--bg);font-size:15px;line-height:1.45;white-space:pre-line;
  overflow-wrap:anywhere;}
.sf-acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center;}
.sf-acts form{margin:0;}
.sf-btn{display:inline-flex;align-items:center;gap:6px;min-height:42px;padding:0 16px;border-radius:999px;border:0;font:inherit;
  font-size:14.5px;font-weight:620;cursor:pointer;background:var(--s2);color:var(--fg);}
.sf-btn.go{background:var(--acc-fill);color:var(--on-acc);}
.sf-btn.warn{background:transparent;color:var(--error);padding:0 6px;}
.sf-open{display:flex;flex-wrap:wrap;gap:8px;width:100%;}
.sf-open input,.sf-close input{flex:1;min-width:180px;min-height:42px;border:0;border-radius:12px;background:var(--bg);color:var(--fg);
  padding:0 14px;font:inherit;font-size:15px;}
.sf-close{display:flex;flex-wrap:wrap;gap:8px;width:100%;}
.sf-note{display:flex;gap:10px;font-size:13px;color:var(--fg3);line-height:1.45;margin:6px 0 0;}
.sf-msg{display:flex;flex-direction:column;gap:2px;padding:10px 0;border-top:.5px solid var(--line);}
.sf-msg:first-child{border-top:0;}
.sf-msg b{font-size:13.5px;}
.sf-msg span{font-size:15px;white-space:pre-line;overflow-wrap:anywhere;}
.sf-msg small{font-size:12px;color:var(--fg3);}
.sf-msg.held span{color:var(--coral-ink,var(--fg));}
.sf-msg.removed span{color:var(--fg3);text-decoration:line-through;}
"""


def _flash(request: Request) -> str:
    from member_portal import _e
    err = ERRORS.get(request.query_params.get("err") or "")
    done = DONE.get(request.query_params.get("done") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def _when(iso: Any) -> str:
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    mins = int((datetime.now(timezone.utc) - then).total_seconds() // 60)
    if mins < 60:
        return "just now" if mins < 2 else f"{mins} min ago"
    if mins < 60 * 24:
        return f"{mins // 60} h ago"
    return f"{then.strftime('%b')} {then.day}"


def _open_form(tid: str) -> str:
    from member_portal import _e
    return (f'<form class="sf-open" method="post" action="/my/lead/safety/open"><input type="hidden" name="thread_id" value="{_e(tid)}">'
            f'<label class="mp-sr" for="sf-why-{_e(tid)}">Why you\'re opening the whole chat</label>'
            f'<input id="sf-why-{_e(tid)}" name="reason" maxlength="300" required placeholder="Why open the whole chat? It\'s logged.">'
            f'<button class="sf-btn" type="submit">Open the whole chat</button></form>')


def _photo(m: Dict[str, Any], photos: Optional[Dict[str, Any]]) -> str:
    """A held or reported photo (chat_photos), for the officer to see."""
    import chat_photos
    from member_portal import _e
    mid, tid = str(m.get("id") or ""), str(m.get("thread_id") or "")
    if not photos or mid not in photos or not tid:
        return ""
    return f'<img class="sf-photo" src="{_e(chat_photos.src(tid, mid))}" alt="The photo" loading="lazy">'


def render_room(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                items: Optional[Dict[str, Any]], photos: Optional[Dict[str, Any]] = None) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    import member_portal_lead as mpl
    head = (f'<a class="mb-back" href="/my/lead">Lead</a><header class="ld-head"><h1 class="ld-hello">Safety <em>room</em></h1></header>'
            f'{_flash(request)}')
    if items is None:
        body = f'{head}<p class="mp-err" role="alert">The Safety room couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "Safety room", f'<style>{mpl.LEAD_CSS}{SAFETY_CSS}</style><div class="ld-wide">{body}</div>',
                      tab="lead", who=me)
    cards: List[str] = []
    for m in items["held"]:
        mid, tid = _e(m["id"]), _e(m.get("thread_id") or "")
        sender = _e(m.get("sender") or "Someone")
        cards.append(
            f'<article class="sf-item"><div class="sf-meta"><b>{sender}</b><span>{_e(_when(m.get("created_at")))}</span>'
            f'<span class="sf-flag">{_e(FLAGS.get(m.get("flag") or "", "Held by the check"))}</span></div>'
            f'{_photo(m, photos)}<p class="sf-body">{_e(m.get("body") or "")}</p>'
            f'<div class="sf-acts"><form method="post" action="/my/lead/safety/act"><input type="hidden" name="message_id" value="{mid}">'
            f'<input type="hidden" name="action" value="release"><button class="sf-btn go" type="submit">Release it</button></form>'
            f'<form method="post" action="/my/lead/safety/act"><input type="hidden" name="message_id" value="{mid}">'
            f'<input type="hidden" name="action" value="remove"><button class="sf-btn" type="submit">Remove it</button></form>'
            f'<form method="post" action="/my/lead/safety/pause"><input type="hidden" name="contact_id" value="{_e(m.get("sender_contact_id") or "")}">'
            f'<button class="sf-btn warn" type="submit">Pause {sender}\'s messaging</button></form></div>'
            f'{_open_form(tid) if tid else ""}</article>')
    for r in items["reports"]:
        msg = r.get("message") or {}
        rid = _e(r["id"])
        sender = _e(msg.get("sender") or "Someone")
        reason = f'<span>· “{_e(r["reason"])}”</span>' if r.get("reason") else ""
        # A message a group's leader took down comes here as a report: the
        # officer can put it back (release) if the leader was too quick.
        remove = (f'<form method="post" action="/my/lead/safety/act"><input type="hidden" name="message_id" value="{_e(msg.get("id") or "")}">'
                  + (f'<input type="hidden" name="action" value="release"><button class="sf-btn go" type="submit">Put it back</button></form>'
                     if msg.get("status") == "removed" else
                     f'<input type="hidden" name="action" value="remove"><button class="sf-btn" type="submit">Remove the message</button></form>')
                  if msg.get("id") else "")
        cards.append(
            f'<article class="sf-item"><div class="sf-meta"><b>{sender}</b><span>{_e(_when(msg.get("created_at")))}</span>'
            f'<span class="sf-flag">Reported by {_e(r.get("reporter") or "a member")}</span>{reason}</div>'
            f'{_photo(msg, photos)}<p class="sf-body">{_e(msg.get("body") or "")}</p>'
            f'<div class="sf-acts">{remove}'
            f'<form method="post" action="/my/lead/safety/pause"><input type="hidden" name="contact_id" value="{_e(msg.get("sender_contact_id") or "")}">'
            f'<button class="sf-btn warn" type="submit">Pause {sender}\'s messaging</button></form></div>'
            f'<form class="sf-close" method="post" action="/my/lead/safety/close"><input type="hidden" name="report_id" value="{rid}">'
            f'<label class="mp-sr" for="sf-out-{rid}">What you did</label>'
            f'<input id="sf-out-{rid}" name="outcome" maxlength="500" placeholder="What you did (only officers see this)">'
            f'<button class="sf-btn go" type="submit">Close the report</button></form>'
            f'{_open_form(msg.get("thread_id") or "") if msg.get("thread_id") else ""}</article>')
    if not cards:
        cards.append('<section class="ld-card"><p style="margin:0">Nothing is waiting. Every message is checked before it\'s '
                     'delivered; anything the check holds, or a member reports, shows up here.</p></section>')
    note = (f'<p class="sf-note">{ui.icon("lock", 15)}<span>You see only what the check held or someone reported. '
            f'Opening a whole chat is logged with your name and your reason, and the people in it see that a safety '
            f'officer reviewed it.</span></p>')
    body = f'{head}<div class="sf-wrap">{"".join(cards)}{note}</div>'
    return _shell(biz, site, "Safety room", f'<style>{mpl.LEAD_CSS}{SAFETY_CSS}</style><div class="ld-wide">{body}</div>',
                  tab="lead", who=me)


def recent_look(business_id: str, thread_id: str, contact_id: str) -> Optional[bool]:
    since = (datetime.now(timezone.utc) - timedelta(minutes=LOOK_MINUTES)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/msg_staff_views?business_id=eq.{_q(business_id)}&thread_id=eq.{_q(thread_id)}&contact_id=eq.{_q(contact_id)}"
        f"&created_at=gt.{_q(since)}&select=id&limit=1")
    if rows is None:
        return None
    return bool(rows)


def render_chat(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], data: Dict[str, Any]) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    import member_portal_lead as mpl
    rows = "".join(
        f'<div class="sf-msg {"held" if m.get("status") == "held" else "removed" if m.get("status") == "removed" else ""}">'
        f'<b>{_e(m.get("sender") or "Someone")}</b>{_photo({**m, "thread_id": data.get("tid")}, data.get("photos"))}<span>{_e(m.get("body") or "")}</span>'
        f'<small>{_e(_when(m.get("created_at")))}{" · held" if m.get("status") == "held" else " · removed" if m.get("status") == "removed" else ""}</small></div>'
        for m in data.get("messages") or [])
    body = (f'<a class="mb-back" href="/my/lead/safety">Safety room</a>'
            f'<header class="ld-head"><h1 class="ld-hello">The whole <em>chat</em></h1></header>'
            f'<p class="sf-note">{ui.icon("lock", 15)}<span>Your look is logged with your reason, and the people in this chat '
            f'see that a safety officer reviewed it.</span></p>'
            f'<section class="sf-item">{rows or "<p>No messages.</p>"}</section>')
    return _shell(biz, site, "The whole chat", f'<style>{mpl.LEAD_CSS}{SAFETY_CSS}</style><div class="ld-wide sf-wrap">{body}</div>',
                  tab="lead", who=me)


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str):
    """GET /my/lead/safety[/chat/<thread>]: (html, status)."""
    import messaging_router as mr
    from member_portal import _shell
    biz_id, me_id = str(biz["id"]), str(me["id"])
    officer = await asyncio.to_thread(is_officer, biz_id, me_id)
    if not officer:
        msg = ("Only the church's safety officers can open the Safety room." if officer is False
               else "The Safety room couldn't load just now. Please try again in a moment.")
        return (_shell(biz, site, "Safety room", f'<a class="mb-back" href="/my/lead">Lead</a><p class="mp-muted">{msg}</p>',
                       tab="lead", who=me), 403 if officer is False else 503)
    rest = sub[len("/my/lead/safety"):].strip("/")
    if rest.startswith("chat/"):
        tid = rest[len("chat/"):]
        if not UUID.match(tid):
            return render_room(biz, site, request, me, await _items(biz_id)), 404
        looked = await asyncio.to_thread(recent_look, biz_id, tid, me_id)
        if not looked:
            return render_room(biz, site, request, me, await _items(biz_id)), 403
        try:
            data = await asyncio.to_thread(_whole_chat, biz_id, tid)
        except HTTPException as e:
            return render_room(biz, site, request, me, None), e.status_code
        data = {**data, "tid": tid, "photos": await asyncio.to_thread(_photos, biz_id, data["messages"])}
        return render_chat(biz, site, request, me, data), 200
    items = await _items(biz_id)
    photos = None
    if items is not None:
        photos = await asyncio.to_thread(_photos, biz_id, items["held"] + [r.get("message") or {} for r in items["reports"]])
    return render_room(biz, site, request, me, items, photos), 200 if items is not None else 503


def _photos(biz_id: str, msgs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    import chat_photos
    return chat_photos.for_messages(biz_id, [m.get("id") for m in msgs if m.get("id")])


async def _items(biz_id: str) -> Optional[Dict[str, Any]]:
    import messaging_router as mr
    try:
        return await asyncio.to_thread(mr.safety_items, biz_id)
    except HTTPException:
        return None


def _whole_chat(biz_id: str, tid: str) -> Dict[str, Any]:
    """The chat as the team's Safety room shows it, without logging again
    (the look that let this page open is already logged)."""
    import messaging_router as mr
    msgs = sb_clients.sb_get_as_service(
        f"/msg_messages?thread_id=eq.{_q(tid)}&business_id=eq.{_q(biz_id)}"
        f"&select=id,sender_contact_id,body,status,flag,created_at&order=created_at.asc&limit=500")
    if not isinstance(msgs, list):
        raise HTTPException(503, "unavailable")
    names = mr._names(biz_id, [m.get("sender_contact_id") for m in msgs])
    return {"messages": [{**m, "sender": names.get(str(m.get("sender_contact_id")), "Someone")} for m in msgs]}


# ─── routes ──────────────────────────────────────────────────────────


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target != "/my/lead/safety" and not re.fullmatch(r"/my/lead/safety/chat/[0-9a-fA-F-]{36}", target):
        target = "/my/lead/safety"
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


async def _officer(request: Request):
    """(biz_id, me, form) for an officer's POST, or a redirect."""
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return None, None, None, _go("/my/lead/safety", err="preview" if unavailable == "preview" else "error")
    if not me:
        return None, None, None, mpc._back("/my")
    biz_id = str(church["business"]["id"])
    officer = await asyncio.to_thread(is_officer, biz_id, str(me["id"]))
    if not officer:
        return None, None, None, _go("/my/lead/safety", err="not_officer" if officer is False else "error")
    if not mpc._allowed(church, me):
        return None, None, None, _go("/my/lead/safety", err="slow")
    return biz_id, me, await request.form(), None


async def _run(fn, *args) -> Optional[str]:
    """Run one of messaging_router's officer actions; the error code or None."""
    try:
        await asyncio.to_thread(fn, *args)
        return None
    except HTTPException as e:
        return "gone" if e.status_code == 404 else ("reason" if e.status_code == 422 else "error")


@router.post("/my/lead/safety/act", include_in_schema=False)
async def act_route(request: Request):
    import messaging_router as mr
    biz_id, me, form, stop = await _officer(request)
    if stop:
        return stop
    action = str(form.get("action") or "")
    if action not in ("release", "remove"):
        return _go("/my/lead/safety", err="error")
    err = await _run(mr.act, biz_id, str(form.get("message_id") or ""), action, str(me["id"]))
    return _go("/my/lead/safety", **({"err": err} if err else {"done": "released" if action == "release" else "removed"}))


@router.post("/my/lead/safety/close", include_in_schema=False)
async def close_route(request: Request):
    import messaging_router as mr
    biz_id, me, form, stop = await _officer(request)
    if stop:
        return stop
    err = await _run(mr.close, biz_id, str(form.get("report_id") or ""), str(form.get("outcome") or ""), str(me["id"]))
    return _go("/my/lead/safety", **({"err": err} if err else {"done": "closed"}))


@router.post("/my/lead/safety/pause", include_in_schema=False)
async def pause_route(request: Request):
    import messaging_router as mr
    biz_id, me, form, stop = await _officer(request)
    if stop:
        return stop
    err = await _run(mr.pause, biz_id, str(form.get("contact_id") or ""))
    return _go("/my/lead/safety", **({"err": err} if err else {"done": "paused"}))


@router.post("/my/lead/safety/open", include_in_schema=False)
async def open_route(request: Request):
    import messaging_router as mr
    biz_id, me, form, stop = await _officer(request)
    if stop:
        return stop
    tid = str(form.get("thread_id") or "")
    reason = " ".join(str(form.get("reason") or "").split())
    if len(reason) < 3:
        return _go("/my/lead/safety", err="reason")
    if not UUID.match(tid):
        return _go("/my/lead/safety", err="gone")
    err = await _run(lambda: mr.open_logged(biz_id, tid, reason, contact_id=str(me["id"])))
    if err:
        return _go("/my/lead/safety", err=err)
    return _go(f"/my/lead/safety/chat/{tid}")
