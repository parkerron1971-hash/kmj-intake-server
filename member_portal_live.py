"""
member_portal_live.py — Live in the member app (/my/live).

When the church is live (the team started it in the app, live_router.py)
a member sees the stream edge to edge, "I'm here", and the chat: other
signed-in members by first name and last initial, the host's messages
marked, newest at the bottom. Their phone asks for anything new every few
seconds with one cheap read (the session's chat_version). Prayer never
goes in the chat — "Ask for prayer" sends it privately to the pastor.

Between services the tab never shows a dead stream (the walk-through of
Kevin's church's current app found its Live tile on a months-old ended
stream): it says when the next service is and offers last Sunday's
message.

  GET  /my/live           the page (served through member_portal.serve)
  GET  /my/live/feed?v=   JSON for the chat poll (also through serve)
  POST /my/live/chat      {body}; JSON when asked, else a redirect
  POST /my/live/here      "I'm here": presence + online attendance

Members can't post links, a paused member can't post, a closed chat takes
nothing, and the owner's preview reads but never writes.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import sb_clients

router = APIRouter(tags=["member-portal"])

FEED_LIMIT = 60
POLL_MS = 5000


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def i_am_here(business_id: str, sid: str, contact_id: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f"/live_presence?session_id=eq.{_q(sid)}&contact_id=eq.{_q(contact_id)}"
        f"&business_id=eq.{_q(business_id)}&select=contact_id&limit=1")
    return bool(rows) if isinstance(rows, list) else None


def is_muted(business_id: str, sid: str, contact_id: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f"/live_mutes?session_id=eq.{_q(sid)}&contact_id=eq.{_q(contact_id)}"
        f"&business_id=eq.{_q(business_id)}&select=contact_id&limit=1")
    return bool(rows) if isinstance(rows, list) else None


def feed_rows(msgs: List[Dict[str, Any]], me_id: str) -> List[Dict[str, Any]]:
    """What a member's phone gets: never another member's record id."""
    return [{"id": m["id"], "author": m.get("author") or "", "body": m.get("body") or "",
             "host": bool(m.get("host")), "mine": str(m.get("contact_id") or "") == str(me_id),
             "at": m.get("created_at")} for m in msgs if not m.get("hidden")]


def _bubble(m: Dict[str, Any]) -> str:
    from member_portal import _e
    cls = "mb-msg" + (" mb-mine" if m["mine"] else "") + (" mb-host" if m["host"] else "")
    who = "" if m["mine"] else f'<span class="mb-msg-who">{_e(m["author"])}{" · Host" if m["host"] and m["author"] != "Host" else ""}</span>'
    return f'<li class="{cls}">{who}<span class="mb-msg-body">{_e(m["body"])}</span></li>'


def render_live(biz, site, request: Request, me: Dict[str, Any], cur: Optional[Dict[str, Any]], *,
                msgs=None, here_me=None, muted_me=None, occasions=None, library=None) -> str:
    import live_router as lr
    import member_app_ui as ui
    import member_portal_church as mpc
    import member_portal_sermons as mps
    from member_portal import _e, _shell, palette_for
    flash = mpc._flash(request)
    if cur is None:
        body = '<h1>Live</h1><p class="mp-err" role="alert">Live couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "Live", body, tab="live", who=me)
    if not cur:
        nxt = mpc.next_card(occasions)
        body = f"""<h1>Live</h1>{flash}
<div class="mp-card mb-offair"><span class="mb-live-dot mb-off" aria-hidden="true"></span>
  <span><strong>No service is live right now.</strong><br><span class="mp-muted">When the church goes live, it plays right here, with the chat.</span></span></div>
{('<h2 class="mp-sect">Next service</h2>' + nxt) if nxt else ''}
{mps.latest_card(library, palette_for(biz, site))}
<a class="mb-prayer-link" href="/my/prayer">{ui.icon('lock', 18)}<span>Need prayer? Send it privately to the pastor.</span>{ui.icon('chevron', 16)}</a>"""
        return _shell(biz, site, "Live", body, tab="live", who=me)
    src = lr.stream_embed(cur.get("stream_url") or "")
    if src:
        player = (f'<div class="mb-video"><iframe src="{_e(src)}" title="{_e(cur.get("title"))}" allowfullscreen '
                  f'referrerpolicy="strict-origin-when-cross-origin" '
                  f'allow="autoplay; fullscreen; picture-in-picture; encrypted-media"></iframe></div>')
    elif cur.get("stream_url"):
        player = (f'<div class="mb-video mb-linkout"><a class="mp-go" href="{_e(cur["stream_url"])}" target="_blank" '
                  f'rel="noopener">{ui.icon("play", 16)}Watch the stream</a></div>')
    else:
        player = ('<div class="mb-video mb-linkout"><p class="mp-muted" style="margin:0">The video is starting. '
                  'The chat is open below.</p></div>')
    here_html = (f'<span class="mb-chip">{ui.icon("check", 12)}You\'re here</span>' if here_me else
                 '<form method="post" action="/my/live/here"><button class="mp-go" type="submit">I\'m here</button></form>')
    rows = feed_rows(msgs or [], me["id"])
    if not cur.get("chat_open"):
        compose = '<p class="mp-muted mb-chat-note">The chat is closed right now.</p>'
    elif muted_me:
        compose = '<p class="mp-muted mb-chat-note">The host has paused your chat for this service.</p>'
    else:
        compose = ('<form class="mb-compose" method="post" action="/my/live/chat" id="mb-compose">'
                   '<label class="mp-sr" for="mb-say">Message</label>'
                   '<input class="mp-input" id="mb-say" name="body" maxlength="500" autocomplete="off" '
                   'placeholder="Say something kind…" required>'
                   f'<button class="mp-go" type="submit" aria-label="Send">{ui.icon("chevron", 18)}</button></form>'
                   '<p class="mb-chat-err mp-err" id="mb-chat-err" role="alert" hidden></p>')
    empty = '' if rows else '<li class="mb-chat-empty mp-muted">No messages yet. Say hello.</li>'
    body = f"""<div class="mb-player">{player}</div>
<div class="mb-live-head"><span class="mb-live-badge"><span class="mb-live-dot" aria-hidden="true"></span>Live</span>
  <h1 style="margin:6px 0 0">{_e(cur.get('title'))}</h1></div>
{flash}
<div class="mb-live-actions">{here_html}
  <a class="mp-go mp-go-2" href="/my/prayer">{ui.icon('lock', 16)}Ask for prayer</a></div>
<h2 class="mp-sect">Chat</h2>
<ul class="mb-chat" id="mb-chat" aria-live="polite" aria-label="Chat">{''.join(_bubble(m) for m in rows)}{empty}</ul>
{compose}"""
    script = _poll_script(int(cur.get("chat_version") or 0))
    return _shell(biz, site, "Live", body, tab="live", who=me, script=script)


def _poll_script(v: int) -> str:
    """Ask for anything new every few seconds; send without leaving the
    page. Messages are built with textContent, never as HTML."""
    return f"""<script>(function(){{var v={json.dumps(v)},box=document.getElementById('mb-chat'),f=document.getElementById('mb-compose'),
err=document.getElementById('mb-chat-err');if(!box)return;
function down(){{box.scrollTop=box.scrollHeight;}}
function draw(ms){{box.textContent='';if(!ms.length){{var e=document.createElement('li');e.className='mb-chat-empty mp-muted';e.textContent='No messages yet. Say hello.';box.appendChild(e);return;}}
ms.forEach(function(m){{var li=document.createElement('li');li.className='mb-msg'+(m.mine?' mb-mine':'')+(m.host?' mb-host':'');
if(!m.mine){{var w=document.createElement('span');w.className='mb-msg-who';w.textContent=m.author+(m.host&&m.author!=='Host'?' · Host':'');li.appendChild(w);}}
var b=document.createElement('span');b.className='mb-msg-body';b.textContent=m.body;li.appendChild(b);box.appendChild(li);}});down();}}
function poll(){{fetch('/my/live/feed?v='+v,{{credentials:'same-origin',headers:{{'Accept':'application/json'}}}}).then(function(r){{return r.json();}}).then(function(d){{
if(!d.live){{location.reload();return;}}if(!d.same){{v=d.v;draw(d.messages||[]);}}}}).catch(function(){{}});}}
down();setInterval(poll,{POLL_MS});
if(f){{f.addEventListener('submit',function(e){{e.preventDefault();var i=f.querySelector('input'),t=i.value.trim();if(!t)return;
var btn=f.querySelector('button');btn.disabled=true;err.hidden=true;
fetch('/my/live/chat',{{method:'POST',credentials:'same-origin',headers:{{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'}},body:'body='+encodeURIComponent(t)}})
.then(function(r){{return r.json().then(function(d){{return {{ok:r.ok,d:d}};}});}}).then(function(x){{btn.disabled=false;
if(x.ok){{i.value='';poll();}}else{{err.textContent=x.d.error||'That didn\\'t send. Please try again.';err.hidden=false;}}}})
.catch(function(){{btn.disabled=false;err.textContent='That didn\\'t send. Please try again.';err.hidden=false;}});}});}}
}})();</script>"""


def feed(business_id: str, me: Dict[str, Any], v: int) -> Dict[str, Any]:
    """The chat poll: {"live": False} once it ends; {"same": True} when
    nothing changed; else the newest visible messages."""
    import live_router as lr
    cur = lr.current(business_id)
    if cur is None:
        return {"error": "unavailable"}
    if not cur:
        return {"live": False}
    ver = int(cur.get("chat_version") or 0)
    if ver == v:
        return {"live": True, "open": bool(cur.get("chat_open")), "v": ver, "same": True}
    msgs = lr.messages(business_id, cur["id"], False, FEED_LIMIT)
    if msgs is None:
        return {"error": "unavailable"}
    return {"live": True, "open": bool(cur.get("chat_open")), "v": ver, "same": False,
            "messages": feed_rows(msgs, me["id"])}


# ─── POST ─────────────────────────────────────────────────────────────


def _wants_json(request: Request) -> bool:
    return "application/json" in (request.headers.get("accept") or "")


def _answer(request: Request, ok: bool, code: str, status: int = 400):
    import member_portal_church as mpc
    if _wants_json(request):
        if ok:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": mpc.ERRORS.get(code, "That didn't send. Please try again.")},
                            status_code=status)
    return mpc._back("/my/live", **({"done": code} if ok else {"err": code}))


@router.post("/my/live/chat", include_in_schema=False)
async def live_chat_post(request: Request):
    import asyncio
    import live_router as lr
    import member_portal_church as mpc
    import rate_limit
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return _answer(request, False, "preview" if unavailable == "preview" else "error",
                       403 if unavailable == "preview" else 503)
    if not me:
        return _answer(request, False, "signed_out", 401)
    form = await request.form()
    text = lr.clean_body(form.get("body"))
    if not text:
        return _answer(request, False, "empty_chat")
    if lr.has_link(text):
        return _answer(request, False, "link")
    biz_id = church["business"]["id"]
    cur = await asyncio.to_thread(lr.current, biz_id)
    if cur is None:
        return _answer(request, False, "error", 503)
    if not cur:
        return _answer(request, False, "not_live", 409)
    if not cur.get("chat_open"):
        return _answer(request, False, "chat_closed", 409)
    paused = await asyncio.to_thread(is_muted, biz_id, cur["id"], me["id"])
    if paused is None:
        return _answer(request, False, "error", 503)
    if paused:
        return _answer(request, False, "muted", 403)
    if not rate_limit.allow_strict("live_chat", f"{biz_id}|{me['id']}"):
        return _answer(request, False, "slow_chat", 429)
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/live_chat", {
        "business_id": biz_id, "session_id": cur["id"], "contact_id": str(me["id"]),
        "author": lr.author_for(me.get("name")), "host": False, "body": text})
    if not isinstance(rows, list) or not rows:
        return _answer(request, False, "error", 503)
    return _answer(request, True, "chat")


def mark_here(business_id: str, cur: Dict[str, Any], me: Dict[str, Any]) -> bool:
    """Presence for this service, and — when it is tied to one — the
    member checked in to it as online attendance. Someone already checked
    in at the door is not counted twice (one check-in per person)."""
    sid = cur["id"]
    rows = sb_clients.sb_post_as_service(
        "/live_presence?on_conflict=session_id,contact_id",
        {"session_id": sid, "contact_id": str(me["id"]), "business_id": business_id},
        prefer="return=representation,resolution=ignore-duplicates")
    if rows is None:
        return False
    entry = cur.get("entry_id")
    if not entry:
        return True
    have = sb_clients.sb_get_as_service(
        f"/attendance?entry_id=eq.{_q(entry)}&contact_id=eq.{_q(me['id'])}&business_id=eq.{_q(business_id)}"
        f"&select=id&limit=1")
    if not isinstance(have, list):
        return False
    if have:
        return True
    made = sb_clients.sb_post_as_service("/attendance", {
        "business_id": business_id, "entry_id": entry, "contact_id": str(me["id"]),
        "name": (me.get("name") or "A member").strip()[:160] or "A member", "method": "online"})
    if isinstance(made, list) and made:
        return True
    # Lost a race with a check-in at the door: that still counts.
    again = sb_clients.sb_get_as_service(
        f"/attendance?entry_id=eq.{_q(entry)}&contact_id=eq.{_q(me['id'])}&business_id=eq.{_q(business_id)}"
        f"&select=id&limit=1")
    return bool(again) if isinstance(again, list) else False


@router.post("/my/live/here", include_in_schema=False)
async def live_here(request: Request):
    import asyncio
    import live_router as lr
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my/live", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    if not mpc._allowed(church, me):
        return mpc._back("/my/live", err="slow")
    biz_id = church["business"]["id"]
    cur = await asyncio.to_thread(lr.current, biz_id)
    if cur is None:
        return mpc._back("/my/live", err="error")
    if not cur:
        return mpc._back("/my/live", err="not_live")
    ok = await asyncio.to_thread(mark_here, biz_id, cur, me)
    return mpc._back("/my/live", **({"done": "here"} if ok else {"err": "error"}))
