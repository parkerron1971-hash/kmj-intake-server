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
  GET  /my/live/feed?v=   JSON for the chat poll (also through serve);
                          &n=1 adds how many are here
  POST /my/live/chat      {body}; JSON when asked, else a redirect
  POST /my/live/here      "I'm here": presence + online attendance;
                          JSON when asked, else a redirect
  POST /my/live/heart     {n}: hearts from the live room (JSON)

Members can't post links, a paused member can't post, a closed chat takes
nothing, and the owner's preview reads but never writes.

The live room (render_room, Kevin 2026-10-30) is the page's new design,
on for everyone (Kevin: "turn it on for everyone now, don't wait").
LIVE_ROOM (off | owner | on, default on) is the way back: owner shows it
only in the owner's preview; off is render_live, the page before it.
"""
from __future__ import annotations

import json
import os
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


def here_count(business_id: str, sid: str) -> Optional[int]:
    """How many said "I'm here" for this service; None when the read failed."""
    import live_router as lr
    rows = lr.here(business_id, sid)
    return len(rows) if rows is not None else None


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
        body = ('<div class="mb-lt"><h1>Live</h1></div><p class="mp-err" role="alert">Live couldn\'t load just now. '
                'Please try again in a moment.</p>')
        return _shell(biz, site, "Live", body, tab="live", who=me, back=("/my/sermons", "Watch"))
    if not cur:
        # Between services: a designed screen (the church's photo or its
        # art), then what's next, the latest message, the verse, prayer.
        import member_app_photos as photos
        import member_portal as mp
        import member_portal_bible as mpb
        nxt = ""
        first = (occasions or [None])[0]
        d = mpc._day((first or {}).get("date") or "")
        if first and d:
            from datetime import date
            soon = mpc._in_days(d, date.today())
            when = soon if soon in ("Today", "Tomorrow") else f"{d.strftime('%A')} · {soon}"
            nxt = (f'<a class="mb-row" href="/my/events"><span class="mb-row-ic">{ui.icon("calendar", 21)}</span>'
                   f'<span class="mb-row-t"><strong>{_e(first.get("title"))}</strong><span>{_e(when)}</span></span>'
                   f'{ui.icon("chevron", 18)}</a>')
        pool = photos.photos(biz, site)
        pic, look = photos.choose(biz, "live", pool, words=("live", "stream", "stage", "worship"))
        art = ui.picture(pic, look, "worship", night=True)
        church = _e(biz.get("name") or "the church")
        body = f"""<section class="mb-offair">{art}<div><span class="mb-kick">Live</span><h1>Between services</h1>
<p style="margin:0"><strong>No service is live right now.</strong> When {church} goes live, it plays right here, with a chat for the church.</p></div></section>
{flash}
{(ui.section("Next service") + nxt) if nxt else ''}
{mps.latest_card(library, palette_for(biz, site), pool=pool, used={pic}, site=site)}
{mpb.verse_card(mpb.prefs(request)[0])}
{mp.prayer_card()}"""
        return _shell(biz, site, "Live", body, tab="live", who=me, back=("/my/sermons", "Watch"))
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
                   f'<button class="mp-go" type="submit" aria-label="Send">{ui.icon("send", 18)}</button></form>'
                   '<p class="mb-chat-err mp-err" id="mb-chat-err" role="alert" hidden></p>')
    empty = '' if rows else '<li class="mb-chat-empty mp-muted">No messages yet. Say hello.</li>'
    body = f"""<div class="mb-player">{player}</div>
<div class="mb-live-head"><span class="mb-live-badge"><span class="mb-live-dot" aria-hidden="true"></span>Live</span>
  <h1 style="margin:6px 0 0">{_e(cur.get('title'))}</h1></div>
{flash}
<div class="mb-live-actions">{here_html}
  <a class="mp-go mp-go-2" href="/my/prayer">{ui.icon('pray', 16)}Ask for prayer</a></div>
{ui.section("Chat")}
<ul class="mb-chat" id="mb-chat" aria-live="polite" aria-label="Chat">{''.join(_bubble(m) for m in rows)}{empty}</ul>
{compose}"""
    script = _poll_script(int(cur.get("chat_version") or 0))
    return _shell(biz, site, "Live", body, tab="live", who=me, script=script, back=("/my/sermons", "Watch"))


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


# ─── The live room (Kevin 2026-10-30) ────────────────────────────────
# "the chat and buttons are not the best… make it top tier"; the design
# (canvas M9RXLgi9PZr6khRWMtVUhX) approved: "the design is great! build
# it". On a phone the service is a room you stay in: the video pinned at
# the top, the chat filling the rest with no tab bar over it, three
# one-line buttons, Prayer and Give opening over the chat while the
# service keeps playing, one-tap replies and hearts. Turned sideways the
# video fills the screen with the chat over it; on a computer the video
# and the buttons sit beside the chat, with what's coming up under them.
# The message the team pinned sits at the top of the chat (a host's new
# message pins itself; live_router.pin).

QUICK = ("Amen", "Good morning!", "Hallelujah", "Thank you, Jesus", "Watching from home")
HEARTS_MAX = 30
FAMILIES = ("gold", "teal", "violet", "coral")
PRAYER_VERSE = ("The effectual fervent prayer of a righteous man availeth much.", "James 5:16")
_HEART = ('<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">'
          '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 '
          '2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>')


def room_mode() -> str:
    m = (os.environ.get("LIVE_ROOM") or "on").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def room_for(preview: bool) -> bool:
    """The live room for this visit: everyone's while LIVE_ROOM is on (the
    default), only the owner's preview of the member app when it's owner."""
    m = room_mode()
    return m == "on" or (m == "owner" and bool(preview))


def family_of(author: Any) -> str:
    """A name's colour in the chat, the same on every phone. Summed over
    UTF-16 units, so the page's script (charCodeAt) picks the same one."""
    b = str(author or "").encode("utf-16-le")
    return FAMILIES[sum(int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)) % len(FAMILIES)]


def initials_of(author: Any) -> str:
    """'Ana R.' → AR, 'Cher' → C (the page's script draws new rows the same way)."""
    words = str(author or "").replace(".", " ").split()
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def give_choices(biz: Dict[str, Any]) -> Dict[str, Any]:
    """The Give sheet's funds and amounts: the church's own (giving_router)."""
    import giving_router as gr
    cfg = gr.giving_settings(biz.get("settings"))
    return {"funds": gr.configured_funds(cfg), "presets": gr.preset_amounts(cfg)[:4]}


def _row(m: Dict[str, Any], church: str) -> str:
    """One chat line, name first (the host's with a heart and a Host tag)."""
    from member_portal import _e
    if m["host"]:
        who = m["author"] if m["author"] not in ("", "Host") else church
        return (f'<li class="lv-msg is-host" data-id="{_e(m["id"])}"><span class="lv-av" aria-hidden="true">'
                f'{_HEART.format(s=12)}</span><p><b class="lv-who">{_e(who)}</b><span class="lv-tag">Host</span> '
                f'{_e(m["body"])}</p></li>')
    return (f'<li class="lv-msg h-{family_of(m["author"])}{" is-mine" if m["mine"] else ""}" data-id="{_e(m["id"])}">'
            f'<span class="lv-av" aria-hidden="true">{_e(initials_of(m["author"]))}</span>'
            f'<p><b class="lv-who">{"You" if m["mine"] else _e(m["author"])}</b> {_e(m["body"])}</p></li>')


def _upcoming(occasions: Optional[List[Dict[str, Any]]]) -> str:
    """Coming up, on a computer only: the next two after today."""
    from datetime import date
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e
    today, cards = date.today(), []
    for o in occasions or []:
        d = mpc._day(o.get("date") or "")
        if not d or d <= today:
            continue
        cards.append(f'<a class="lv-oc" href="/my/events"><time datetime="{d.isoformat()}"><small>{d.strftime("%a")}</small>'
                     f'<b>{d.day}</b></time><span><strong>{_e(o.get("title"))}</strong>'
                     f'<span>{_e(o.get("date_label") or "")}</span></span>{ui.icon("chevron", 18)}</a>')
        if len(cards) == 2:
            break
    return (f'<aside class="lv-next" aria-labelledby="lv-next-h"><h2 id="lv-next-h">Coming up</h2>'
            f'<div class="lv-next-row">{"".join(cards)}</div></aside>') if cards else ""


def _prayer_sheet(church: str) -> str:
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e
    words, ref = PRAYER_VERSE
    return f"""<dialog class="lv-sheet" id="lv-prayer" aria-labelledby="lv-prayer-h"><div class="lv-sheet-in">
<div class="lv-grab" aria-hidden="true"></div>
<div class="lv-sheet-h"><h2 id="lv-prayer-h">How can we pray for you?</h2>
<button class="lv-x" type="button" data-close aria-label="Close">{ui.icon("plus", 18)}</button></div>
<form id="lv-prayer-f" method="post" action="/my/prayer">
<p class="lv-lock">{ui.icon("lock", 15)}Private. It goes to the pastors at {_e(church)}, never into the chat.</p>
<label class="mp-sr" for="lv-prayer-t">Your prayer request</label>
<textarea id="lv-prayer-t" name="request" rows="4" maxlength="{mpc.PRAYER_MAX}" placeholder="Your prayer request" required></textarea>
<fieldset><legend>Who prays with you?</legend>
<label class="lv-opt"><input type="radio" name="share" value="team" required> Our prayer team may pray over this with you</label>
<label class="lv-opt"><input type="radio" name="share" value="pastors"> Keep this with the pastors only</label></fieldset>
<label class="lv-opt lv-opt-call"><input type="checkbox" name="wants_call" value="yes"> I&#x27;d like someone to call me</label>
<p class="mp-err lv-err" id="lv-prayer-err" role="alert" hidden></p>
<button class="lv-go" type="submit">Send privately</button></form>
<div class="lv-done" id="lv-prayer-done" hidden><span class="lv-done-ic">{ui.icon("check", 26)}</span>
<h3>Sent to the pastors</h3><p class="lv-done-p">They&#x27;ll be praying with you.</p>
<blockquote>{_e(words)}</blockquote><cite>{_e(ref)}</cite>
<button class="lv-go" type="button" data-close>Back to the service</button></div>
</div></dialog>"""


def _give_sheet(church: str, give: Dict[str, Any]) -> str:
    import member_app_ui as ui
    from member_portal import _e
    funds = [f for f in give.get("funds") or [] if f] or ["General"]
    presets = list(give.get("presets") or [])[:4]
    if len(funds) == 1:
        fund = f'<input type="hidden" name="fund" value="{_e(funds[0])}">'
    elif len(funds) <= 3:
        fund = ('<fieldset class="lv-seg"><legend class="mp-sr">Fund</legend>' + "".join(
            f'<label><input type="radio" name="fund" value="{_e(f)}"{" checked" if i == 0 else ""}><span>{_e(f)}</span></label>'
            for i, f in enumerate(funds)) + '</fieldset>')
    else:
        fund = ('<label class="mp-sr" for="lv-fund">Fund</label><select class="lv-other" id="lv-fund" name="fund">' + "".join(
            f'<option value="{_e(f)}">{_e(f)}</option>' for f in funds) + '</select>')
    pick = 1 if len(presets) > 1 else 0
    amounts = "".join(f'<label><input type="radio" name="amount" value="{n}"{" checked" if i == pick else ""}>'
                      f'<span>${n:,}</span></label>' for i, n in enumerate(presets))
    return f"""<dialog class="lv-sheet" id="lv-give" aria-labelledby="lv-give-h"><div class="lv-sheet-in">
<div class="lv-grab" aria-hidden="true"></div>
<div class="lv-sheet-h"><h2 id="lv-give-h">Give to {_e(church)}</h2>
<button class="lv-x" type="button" data-close aria-label="Close">{ui.icon("plus", 18)}</button></div>
<form id="lv-give-f" method="get" action="/my/give">
{fund}
<fieldset class="lv-amts"><legend class="mp-sr">Amount</legend>{amounts}</fieldset>
<label class="mp-sr" for="lv-other">Other amount</label>
<input class="lv-other" id="lv-other" name="other" inputmode="decimal" autocomplete="off" placeholder="Other amount">
<button class="lv-go" id="lv-give-go" type="submit">Continue</button>
<p class="lv-lock lv-lock-foot">{ui.icon("lock", 15)}Next: your card, on the secure Give page.</p></form>
</div></dialog>"""


def render_room(biz, site, request: Request, me: Dict[str, Any], cur: Dict[str, Any], *,
                msgs=None, here_me=None, muted_me=None, here_n: Optional[int] = None,
                occasions=None, give: Optional[Dict[str, Any]] = None,
                pinned: Optional[Dict[str, Any]] = None) -> str:
    """The live room. `here_n` is how many said "I'm here" (None hides the
    count: a failed read never says nobody's here); `give` is
    give_choices() while the church takes gifts in the app, else None
    (Give is then the link to /my/give, which says how to give);
    `pinned` is pinned_row(): the message the team pinned, or None."""
    import live_router as lr
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    church = (biz.get("name") or "").strip() or "Your church"
    src = lr.stream_embed(cur.get("stream_url") or "")
    if src:
        video = (f'<div class="mb-video"><iframe src="{_e(src)}" title="{_e(cur.get("title"))}" allowfullscreen '
                 f'referrerpolicy="strict-origin-when-cross-origin" '
                 f'allow="autoplay; fullscreen; picture-in-picture; encrypted-media"></iframe></div>')
    elif cur.get("stream_url"):
        video = (f'<div class="mb-video mb-linkout"><a class="mp-go" href="{_e(cur["stream_url"])}" target="_blank" '
                 f'rel="noopener">{ui.icon("play", 16)}Watch the stream</a></div>')
    else:
        video = ('<div class="mb-video mb-linkout"><p class="mp-muted" style="margin:0">The video is starting. '
                 'The chat is open below.</p></div>')
    started = str(cur.get("started_at") or "")
    rows = feed_rows(msgs or [], me["id"])
    # Faces beside the count: you once you're here, then who spoke last.
    faces: List[str] = [lr.author_for(me.get("name"))] if here_me else []
    for m in reversed(rows):
        if len(faces) >= 3:
            break
        if not m["host"] and not m["mine"] and m["author"] not in faces:
            faces.append(m["author"])
    stack = "".join(f'<i class="h-{family_of(a)}">{_e(initials_of(a))}</i>' for a in faces)
    if stack:
        stack = f'<span class="lv-stack" aria-hidden="true">{stack}</span>'
    here = (f'<p class="lv-here" id="lv-herewrap"{" hidden" if here_n is None else ""}>'
            f'{stack}<span><b data-here-n>{here_n or 0}</b> here</span></p>')
    you_are_here = f'<span class="lv-pill is-here" id="lv-here">{ui.icon("check", 17)}You&#x27;re here</span>'
    im_here = (you_are_here if here_me else
               f'<form method="post" action="/my/live/here" id="lv-here"><button class="lv-pill is-go" type="submit">'
               f'{ui.icon("user", 17)}I&#x27;m here</button></form>')
    opens = ' data-sheet="lv-give" aria-haspopup="dialog"' if give else ""
    give_pill = f'<a class="lv-pill" href="/my/give"{opens}>{ui.icon("give", 17)}Give</a>'
    p = pinned or {}
    if p.get("host"):
        p_cls, p_av, p_who = "lv-pin is-host", _HEART.format(s=12), (p["author"] if p["author"] not in ("", "Host") else church)
    elif p:
        p_cls, p_av = f"lv-pin h-{family_of(p['author'])}", _e(initials_of(p["author"]))
        p_who = "You" if p.get("mine") else p["author"]
    else:
        p_cls, p_av, p_who = "lv-pin", "", ""
    pin = (f'<div class="{p_cls}" id="lv-pin"{"" if p else " hidden"}><span class="lv-av" id="lv-pin-av" aria-hidden="true">'
           f'{p_av}</span><p><b class="lv-who" id="lv-pin-who">{_e(p_who)}</b><span class="lv-tag">Pinned</span>'
           f'<span class="lv-pin-b" id="lv-pin-b">{_e(p.get("body") or "")}</span></p></div>')
    if not cur.get("chat_open"):
        foot = '<p class="lv-note">The chat is closed right now.</p>'
    elif muted_me:
        foot = '<p class="lv-note">The host has paused your chat for this service.</p>'
    else:
        chips = "".join(f'<button type="submit" name="body" value="{_e(q)}"{" data-greet" if q == "Good morning!" else ""}>'
                        f'{_e(q)}</button>' for q in QUICK)
        foot = (f'<div class="lv-foot"><form class="lv-quick" id="lv-quick" method="post" action="/my/live/chat" '
                f'aria-label="Quick replies">{chips}</form>'
                f'<form class="lv-compose" method="post" action="/my/live/chat" id="mb-compose">'
                f'<label class="mp-sr" for="mb-say">Message the church</label>'
                f'<input class="lv-input" id="mb-say" name="body" maxlength="500" autocomplete="off" enterkeyhint="send" '
                f'placeholder="Say something kind…" required>'
                f'<button class="lv-send" id="lv-send" type="submit" aria-label="Send a heart">'
                f'<span class="lv-i-heart">{_HEART.format(s=19)}</span><span class="lv-i-send">{ui.icon("send", 19)}</span></button>'
                f'<div class="lv-hearts" id="lv-hearts" aria-hidden="true"></div></form>'
                f'<p class="mp-err lv-err" id="mb-chat-err" role="alert" hidden></p></div>')
    empty = '' if rows else '<li class="lv-empty">No messages yet. Say hello.</li>'
    flash = mpc._flash(request)
    body = f"""<style>{ROOM_CSS}</style>
<div class="lv-room" id="lv-room">
<div class="lv-stage">{video}<div class="lv-over" aria-hidden="true"><span class="lv-live"><i></i>LIVE</span>
<span class="lv-clock" id="lv-clock" hidden></span></div></div>
<div class="lv-info"><div class="lv-t"><h1>{_e(cur.get('title'))}</h1>
<p>{_e(church)} · <span id="lv-started">Live now</span></p></div>{here}</div>
<div class="lv-acts">{im_here}
<a class="lv-pill" href="/my/prayer" data-sheet="lv-prayer" aria-haspopup="dialog">{ui.icon("pray", 17)}Prayer</a>
{give_pill}</div>
{_upcoming(occasions)}
<section class="lv-chat" aria-labelledby="lv-chat-h">
<h2 class="lv-chat-h" id="lv-chat-h">Live chat<span{" hidden" if here_n is None else ""}>· <b data-here-n>{here_n or 0}</b> here</span></h2>
{pin}
<div class="lv-scroll"><ul class="lv-list" id="mb-chat" aria-live="polite" aria-label="Messages">{''.join(_row(m, church) for m in rows)}{empty}</ul>
<button class="lv-newer" id="lv-newer" type="button" hidden>New messages{ui.icon("down", 15)}</button></div>
{foot}
</section>
</div>
{_prayer_sheet(church)}
{_give_sheet(church, give) if give else ''}
<template id="lv-heart-tpl">{_HEART.format(s=15)}</template>
<template id="lv-here-tpl">{you_are_here}</template>
<div class="lv-toast" id="lv-toast" role="status" aria-live="polite"{'' if flash else ' hidden'}>{flash}</div>"""
    first = (str(me.get("name") or "").split() or [""])[0][:40]
    cfg = {"v": int(cur.get("chat_version") or 0), "hearts": int(cur.get("hearts") or 0), "started": started,
           "church": church, "first": first, "poll": POLL_MS}
    script = "<script>" + ROOM_JS.replace("__CFG__", json.dumps(cfg).replace("</", "<\\/")) + "</script>"
    return _shell(biz, site, "Live", body, tab="live", who=me, script=script, back=("/my/sermons", "Watch"), wide=True)


ROOM_CSS = """
.lv-room{--live:#e2231a;}
.lv-stage{position:relative;background:#000;}
.lv-stage .mb-video{border-radius:0;}
.lv-over{position:absolute;z-index:2;top:10px;left:12px;display:flex;gap:6px;pointer-events:none;}
.lv-live,.lv-clock{height:24px;padding:0 9px;border-radius:6px;display:inline-flex;align-items:center;gap:6px;color:#fff;font-size:12px;font-weight:700;}
.lv-live{background:var(--live);letter-spacing:.06em;}
.lv-live i{width:7px;height:7px;border-radius:50%;background:#fff;}
.lv-clock{background:rgba(0,0,0,.62);font-size:12.5px;font-weight:600;font-variant-numeric:tabular-nums;}
.lv-clock[hidden]{display:none;}
@media (prefers-reduced-motion:no-preference){.lv-live i{animation:mbpulse 1.6s ease-in-out infinite;}}
.lv-info{display:flex;align-items:center;gap:12px;padding:14px var(--g) 0;}
.lv-t{flex:1;min-width:0;}
.lv-t h1{margin:0;font-size:20px;font-weight:680;letter-spacing:-.02em;line-height:1.22;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-t p{margin:2px 0 0;font-size:13px;color:var(--fg3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-here{flex:none;display:flex;align-items:center;gap:8px;margin:0;font-size:13px;font-weight:600;color:var(--fg2);}
.lv-here[hidden]{display:none;}
.lv-here b,.lv-chat-h b{color:var(--fg);font-variant-numeric:tabular-nums;}
.lv-stack{display:flex;}
.lv-stack i{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-style:normal;font-size:9px;font-weight:700;
  letter-spacing:-.02em;background:var(--h-deep);color:var(--h-ink);box-shadow:0 0 0 2px var(--bg);}
.lv-stack i+i{margin-left:-3px;}
.lv-acts{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:8px;padding:12px var(--g) 0;}
.lv-acts form{display:contents;}
.lv-pill{width:100%;height:42px;padding:0 12px;border:0;border-radius:999px;display:flex;align-items:center;justify-content:center;gap:7px;
  font:inherit;font-size:14.5px;font-weight:620;letter-spacing:-.01em;white-space:nowrap;text-decoration:none;cursor:pointer;
  background:var(--s1);color:var(--fg);box-shadow:inset 0 0 0 1px var(--line);}
.lv-pill.is-go{background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
.lv-pill.is-here{background:var(--teal-deep);color:var(--teal-ink);box-shadow:none;cursor:default;}
.lv-pill:disabled{opacity:.6;}
.lv-chat{position:relative;display:flex;flex-direction:column;margin-top:12px;box-shadow:0 -.5px 0 var(--hair);}
.lv-chat-h{display:none;}
.lv-chat-h span[hidden]{display:none;}
.lv-pin{display:flex;gap:10px;align-items:flex-start;margin:10px var(--g) 0;padding:10px 12px;border-radius:14px;background:var(--acc-soft);}
.lv-pin[hidden]{display:none;}
.lv-pin p{margin:0;font-size:14px;line-height:1.38;min-width:0;}
.lv-pin-b{display:block;margin-top:1px;color:var(--fg);overflow-wrap:anywhere;}
.lv-scroll{position:relative;display:flex;flex-direction:column;}
.lv-list{list-style:none;margin:0;padding:10px var(--g) 8px;display:flex;flex-direction:column;gap:10px;overflow-y:auto;overscroll-behavior:contain;}
.lv-msg{display:flex;gap:9px;align-items:flex-start;}
.lv-msg p{margin:0;padding-top:2px;min-width:0;font-size:15px;line-height:1.38;overflow-wrap:anywhere;}
.lv-msg.is-mine{margin:0 -8px;padding:6px 8px;border-radius:12px;background:var(--s1);}
.lv-av{width:26px;height:26px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:10px;font-weight:700;letter-spacing:.02em;
  background:var(--h-deep,var(--s2));color:var(--h-ink,var(--fg2));}
.lv-who{font-weight:650;color:var(--h-ink,var(--fg));}
.is-host .lv-av{background:var(--acc-fill);color:var(--on-acc);}
.is-host .lv-who{color:var(--acc);}
.lv-tag{display:inline-block;margin:0 2px 0 6px;padding:1px 6px;border-radius:5px;background:var(--acc-soft);color:var(--acc);
  font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;vertical-align:1px;}
.lv-empty{margin:auto;padding:24px 0;color:var(--fg3);font-size:14px;}
.lv-newer{position:absolute;left:50%;bottom:10px;transform:translateX(-50%);height:32px;padding:0 12px 0 14px;border:0;border-radius:999px;
  display:flex;align-items:center;gap:4px;background:var(--fg);color:var(--bg);font:inherit;font-size:13px;font-weight:650;cursor:pointer;
  box-shadow:0 6px 18px rgba(0,0,0,.35);}
.lv-newer[hidden]{display:none;}
.lv-foot{padding:6px var(--g) calc(10px + env(safe-area-inset-bottom,0px));background:var(--bg);}
.lv-quick{display:flex;gap:7px;margin:0 calc(var(--g) * -1) 8px;padding:0 var(--g);overflow-x:auto;scrollbar-width:none;}
.lv-quick::-webkit-scrollbar{display:none;}
.lv-quick button{flex:none;height:32px;padding:0 13px;border:0;border-radius:999px;background:var(--s1);color:var(--fg);font:inherit;
  font-size:13.5px;font-weight:600;white-space:nowrap;cursor:pointer;box-shadow:inset 0 0 0 1px var(--line);}
.lv-compose{position:relative;display:flex;gap:8px;align-items:center;margin:0;}
.lv-input{flex:1;min-width:0;height:44px;padding:0 16px;border:0;border-radius:22px;background:var(--s1);color:var(--fg);font:inherit;font-size:16px;
  box-shadow:inset 0 0 0 1px var(--line);}
.lv-input::placeholder{color:var(--fg3);}
.lv-input:focus{outline:none;box-shadow:inset 0 0 0 1.5px var(--acc);}
.lv-send{width:44px;height:44px;flex:none;border:0;border-radius:50%;display:grid;place-items:center;background:var(--acc-fill);color:var(--on-acc);cursor:pointer;}
.lv-send>span{display:grid;}
.lv-i-send,.has-text .lv-i-heart{display:none!important;}
.has-text .lv-i-send{display:grid!important;}
.lv-err{margin:8px 0 0;font-size:13px;}
.lv-err[hidden]{display:none;}
.lv-note{margin:0;padding:14px var(--g) calc(14px + env(safe-area-inset-bottom,0px));color:var(--fg3);font-size:13.5px;}
.lv-hearts{position:absolute;right:0;bottom:calc(100% + 6px);width:44px;height:230px;pointer-events:none;}
.lv-heart{position:absolute;bottom:0;left:50%;width:30px;height:30px;margin-left:-15px;border-radius:50%;display:grid;place-items:center;
  background:var(--s3);color:var(--acc);opacity:0;}
.lv-heart.is-mine{background:var(--acc-fill);color:var(--on-acc);}
@media (prefers-reduced-motion:no-preference){
  .lv-heart.r1{animation:lvRiseA 2.4s ease-out forwards;}
  .lv-heart.r2{animation:lvRiseB 2.4s ease-out forwards;}
  .lv-heart.r3{animation:lvRiseC 2.4s ease-out forwards;}}
@media (prefers-reduced-motion:reduce){.lv-heart{animation:lvFade .9s ease-out forwards;}}
@keyframes lvRiseA{0%{opacity:0;transform:translate(0,0) scale(.5);}12%{opacity:1;transform:translate(var(--x),-26px) scale(1);}
  100%{opacity:0;transform:translate(calc(var(--x) * -1),-220px) scale(.9);}}
@keyframes lvRiseB{0%{opacity:0;transform:translate(0,0) scale(.5);}15%{opacity:1;transform:translate(calc(var(--x) * -1),-30px) scale(1.05);}
  100%{opacity:0;transform:translate(var(--x),-210px) scale(.85);}}
@keyframes lvRiseC{0%{opacity:0;transform:translate(0,0) scale(.5);}10%{opacity:1;transform:translate(0,-20px) scale(1);}
  60%{transform:translate(var(--x),-140px) scale(.95);}100%{opacity:0;transform:translate(0,-230px) scale(.9);}}
@keyframes lvFade{0%{opacity:0;}30%{opacity:1;}100%{opacity:0;}}
.lv-toast{position:fixed;z-index:40;left:50%;bottom:calc(132px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);
  max-width:calc(100% - 32px);padding:10px 16px;border-radius:999px;background:var(--teal-deep);color:var(--teal-ink);font-size:14px;
  font-weight:620;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.4);}
.lv-toast[hidden]{display:none;}
.lv-toast .mp-flash{margin:0;padding:0;border:0;background:none;color:inherit;font:inherit;}
.lv-next{display:none;}
.lv-next h2{margin:0 0 10px;font-size:17px;}
.lv-next-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
.lv-oc{display:flex;align-items:center;gap:14px;padding:12px 14px;border-radius:16px;background:var(--s1);color:var(--fg);text-decoration:none;}
.lv-oc time{width:44px;flex:none;text-align:center;line-height:1.05;}
.lv-oc small{display:block;color:var(--acc);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;}
.lv-oc b{display:block;font-size:22px;font-weight:700;letter-spacing:-.02em;}
.lv-oc>span{flex:1;min-width:0;}
.lv-oc strong{display:block;font-weight:620;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-oc span span{display:block;color:var(--fg3);font-size:13px;}
.lv-oc .mb-ic{color:var(--fg3);}
.lv-pill:focus-visible,.lv-quick button:focus-visible,.lv-send:focus-visible,.lv-newer:focus-visible,.lv-oc:focus-visible,.lv-x:focus-visible,
.lv-go:focus-visible,.lv-opt input:focus-visible{outline:2px solid var(--focus);outline-offset:2px;}
dialog.lv-sheet{position:fixed;inset:auto 0 0 0;width:100%;max-width:600px;max-height:min(80dvh,660px);margin:0 auto;padding:0;border:0;
  border-radius:22px 22px 0 0;background:var(--s1);color:var(--fg);overflow:auto;overscroll-behavior:contain;box-shadow:0 -12px 40px rgba(0,0,0,.45);}
dialog.lv-sheet::backdrop{background:rgba(0,0,0,.5);}
@media (prefers-reduced-motion:no-preference){dialog.lv-sheet[open]{animation:lvUp .26s cubic-bezier(.2,.8,.2,1);}}
@keyframes lvUp{from{transform:translateY(40px);opacity:.4;}to{transform:none;opacity:1;}}
.lv-sheet-in{padding:10px var(--g) calc(20px + env(safe-area-inset-bottom,0px));}
.lv-grab{width:38px;height:5px;margin:0 auto 12px;border-radius:3px;background:var(--s3);}
.lv-sheet-h{display:flex;align-items:center;gap:10px;}
.lv-sheet-h h2{flex:1;margin:0;font-size:20px;}
.lv-x{width:34px;height:34px;flex:none;border:0;border-radius:50%;display:grid;place-items:center;background:var(--s2);color:var(--fg2);cursor:pointer;}
.lv-x .mb-ic{transform:rotate(45deg);}
.lv-lock{display:flex;gap:8px;align-items:center;margin:8px 0 14px;color:var(--fg3);font-size:13px;line-height:1.35;}
.lv-lock-foot{justify-content:center;margin:12px 0 0;}
.lv-sheet textarea{display:block;width:100%;min-height:112px;padding:12px 14px;border:0;border-radius:14px;background:var(--bg);color:var(--fg);
  font:inherit;font-size:16px;line-height:1.4;resize:vertical;box-shadow:inset 0 0 0 1px var(--line);}
.lv-sheet textarea:focus,.lv-other:focus{outline:none;box-shadow:inset 0 0 0 1.5px var(--acc);}
.lv-sheet fieldset{margin:14px 0 0;padding:0;border:0;}
.lv-sheet legend{margin-bottom:6px;font-size:14px;font-weight:620;}
.lv-opt{display:flex;gap:10px;align-items:flex-start;margin:7px 0;font-size:14.5px;line-height:1.35;cursor:pointer;}
.lv-opt input{width:20px;height:20px;flex:none;margin:0;accent-color:var(--acc-fill);}
.lv-opt-call{margin-top:12px;}
.lv-go{width:100%;height:50px;margin-top:16px;border:0;border-radius:14px;background:var(--acc-fill);color:var(--on-acc);font:inherit;
  font-size:16px;font-weight:650;letter-spacing:-.01em;cursor:pointer;}
.lv-go:disabled{opacity:.6;}
.lv-done{padding:14px 4px 0;text-align:center;}
.lv-done[hidden],#lv-prayer-f[hidden]{display:none;}
.lv-done-ic{width:56px;height:56px;margin:0 auto 12px;border-radius:50%;display:grid;place-items:center;background:var(--teal-deep);color:var(--teal-ink);}
.lv-done h3{margin:0;font-size:20px;}
.lv-done-p{margin:4px 0 0;color:var(--fg2);}
.lv-done blockquote{margin:18px 8px 4px;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:19px;line-height:1.35;}
.lv-done cite{color:var(--fg3);font-size:13px;font-style:normal;}
.lv-seg{display:flex;gap:4px;margin:6px 0 14px!important;padding:3px!important;border-radius:12px;background:var(--bg);}
.lv-seg label,.lv-amts label{position:relative;flex:1;}
.lv-seg input,.lv-amts input{position:absolute;opacity:0;pointer-events:none;}
.lv-seg span{min-height:38px;padding:0 8px;border-radius:9px;display:flex;align-items:center;justify-content:center;text-align:center;
  color:var(--fg2);font-size:13.5px;font-weight:600;cursor:pointer;}
.lv-seg input:checked+span{background:var(--s3);color:var(--fg);}
.lv-amts{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:6px!important;}
.lv-amts span{height:54px;border-radius:14px;display:grid;place-items:center;background:var(--bg);font-size:19px;font-weight:700;
  letter-spacing:-.02em;font-variant-numeric:tabular-nums;cursor:pointer;box-shadow:inset 0 0 0 1px var(--line);}
.lv-amts input:checked+span{background:var(--fg);color:var(--bg);box-shadow:none;}
.lv-seg input:focus-visible+span,.lv-amts input:focus-visible+span{outline:2px solid var(--focus);outline-offset:2px;}
.lv-other{display:block;width:100%;height:48px;margin-top:8px;padding:0 14px;border:0;border-radius:14px;background:var(--bg);color:var(--fg);
  font:inherit;font-size:16px;box-shadow:inset 0 0 0 1px var(--line);}
/* A phone: the room fills the screen, no tab bar, the chat scrolls on its own */
@media (max-width:1099px){body:has(.lv-room) .mb-nav{display:none;}}
@media (max-width:999px){
  body:has(.lv-room){height:100vh;height:100dvh;min-height:0;overflow:hidden;display:flex;flex-direction:column;}
  body:has(.lv-room) .mb-top{flex:none;width:100%;background:var(--bg);box-shadow:0 .5px 0 var(--hair);}
  body:has(.lv-room) .mp-foot{display:none;}
  body:has(.lv-room) .mp-shell{flex:1;min-height:0;width:100%;padding:0;display:flex;flex-direction:column;}
  .lv-room{flex:1;min-height:0;display:flex;flex-direction:column;}
  .lv-chat,.lv-scroll,.lv-list{flex:1;min-height:0;}
}
/* Turned sideways: the video fills the screen, the chat sits over it */
@media (max-width:999px) and (orientation:landscape) and (max-height:520px){
  body:has(.lv-room) .mb-top{display:none;}
  .lv-stage{position:fixed;inset:0;z-index:30;}
  .lv-stage .mb-video{position:absolute;inset:0;height:100%;aspect-ratio:auto;}
  .lv-over{top:14px;left:max(16px,env(safe-area-inset-left,0px));}
  .lv-info{position:fixed;z-index:31;top:46px;left:max(16px,env(safe-area-inset-left,0px));max-width:42%;padding:0;pointer-events:none;}
  .lv-t h1{color:#fff;font-size:18px;text-shadow:0 1px 8px rgba(0,0,0,.7);}
  .lv-t p{color:rgba(255,255,255,.86);text-shadow:0 1px 6px rgba(0,0,0,.7);}
  .lv-here{display:none;}
  .lv-acts{position:fixed;z-index:31;left:max(16px,env(safe-area-inset-left,0px));bottom:64px;display:flex;padding:0;}
  .lv-pill{width:auto;height:36px;font-size:13.5px;background:rgba(0,0,0,.55);color:#fff;box-shadow:inset 0 0 0 1px rgba(255,255,255,.22);}
  .lv-pill.is-go{background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
  .lv-pill.is-here{background:var(--teal-deep);color:var(--teal-ink);box-shadow:none;}
  .lv-chat{position:fixed;z-index:31;top:14px;bottom:60px;right:max(16px,env(safe-area-inset-right,0px));width:300px;margin:0;
    border-radius:14px;background:linear-gradient(90deg,rgba(0,0,0,0),rgba(0,0,0,.55) 35%);box-shadow:none;}
  .lv-pin,.lv-quick{display:none;}
  .lv-list{padding:8px 10px;}
  .lv-msg p{color:#fff;font-size:14px;text-shadow:0 1px 6px rgba(0,0,0,.7);}
  .lv-msg.is-mine{margin:0;padding:6px 8px;background:rgba(0,0,0,.35);}
  .lv-empty{color:rgba(255,255,255,.8);}
  .lv-foot{padding:6px 10px 0;background:transparent;}
  .lv-input{height:40px;background:rgba(0,0,0,.5);color:#fff;box-shadow:inset 0 0 0 1px rgba(255,255,255,.28);}
  .lv-input::placeholder{color:rgba(255,255,255,.75);}
  .lv-send{width:40px;height:40px;}
  .lv-note{color:rgba(255,255,255,.85);}
}
/* A computer: the video and the buttons beside the chat */
@media (min-width:1000px){
  .lv-room{display:grid;grid-template-columns:minmax(0,1fr) minmax(340px,380px);
    grid-template-areas:"stage chat" "info chat" "acts chat" "next chat" ". chat";grid-template-rows:auto auto auto auto 1fr;
    gap:0 28px;align-items:start;margin-top:8px;}
  .lv-stage{grid-area:stage;border-radius:18px;overflow:hidden;}
  .lv-info{grid-area:info;padding:18px 0 0;}
  .lv-t h1{font-size:28px;letter-spacing:-.03em;white-space:normal;}
  .lv-t p{margin-top:4px;font-size:14px;}
  .lv-here{font-size:14px;}
  .lv-acts{grid-area:acts;display:flex;gap:10px;padding:16px 0 0;}
  .lv-pill{width:auto;height:44px;padding:0 18px;}
  .lv-next{grid-area:next;display:block;margin-top:34px;}
  .lv-chat{grid-area:chat;position:sticky;top:72px;height:min(760px,calc(100vh - 96px));margin:0;border-radius:18px;
    background:var(--s1);overflow:hidden;box-shadow:none;}
  .lv-chat-h{display:flex;align-items:baseline;gap:6px;margin:0;padding:14px 16px 12px;font-size:15px;font-weight:650;box-shadow:0 .5px 0 var(--hair);}
  .lv-chat-h span{color:var(--fg3);font-weight:500;}
  .lv-chat,.lv-scroll,.lv-list{min-height:0;}
  .lv-scroll,.lv-list{flex:1;}
  .lv-pin{margin:10px 12px 0;}
  .lv-list{padding:12px 16px;}
  .lv-msg.is-mine{background:var(--s2);}
  .lv-foot{padding:8px 12px 12px;background:var(--s1);}
  .lv-quick{margin:0 -12px 8px;padding:0 12px;}
  .lv-quick button,.lv-input{background:var(--s2);}
  .lv-toast{bottom:40px;}
  dialog.lv-sheet{inset:0;max-width:460px;max-height:min(86vh,720px);margin:auto;border-radius:22px;}
  .lv-grab{display:none;}
}
@media (min-width:1000px) and (hover:hover) and (pointer:fine){
  .lv-pill:not(.is-here):hover,.lv-quick button:hover{filter:brightness(1.12);}
  .lv-oc:hover{background:var(--s2);}
}
"""


ROOM_JS = r"""(function(){
var C=__CFG__,d=document,room=d.getElementById('lv-room');if(!room)return;
var list=d.getElementById('mb-chat'),pin=d.getElementById('lv-pin'),pinB=d.getElementById('lv-pin-b'),
newer=d.getElementById('lv-newer'),toast=d.getElementById('lv-toast'),err=d.getElementById('mb-chat-err'),
f=d.getElementById('mb-compose'),say=d.getElementById('mb-say'),send=d.getElementById('lv-send'),
hearts=d.getElementById('lv-hearts'),HEART=d.getElementById('lv-heart-tpl'),
v=C.v,seen=C.hearts,credit=0,pending=0,flushT=0,ticks=0,FAM=['gold','teal','violet','coral'],
JSONH={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'};
function fam(a){var s=0;for(var i=0;i<a.length;i++)s+=a.charCodeAt(i);return FAM[s%FAM.length];}
function ini(a){var w=a.replace(/\./g,' ').split(/\s+/).filter(Boolean);if(!w.length)return '?';
  return (Array.from(w[0])[0]+(w.length>1?Array.from(w[w.length-1])[0]:'')).toUpperCase();}
function heartNode(){return HEART.content.cloneNode(true);}
function row(m){var li=d.createElement('li'),av=d.createElement('span'),p=d.createElement('p'),b=d.createElement('b');
  li.setAttribute('data-id',m.id);av.className='lv-av';av.setAttribute('aria-hidden','true');b.className='lv-who';
  if(m.host){li.className='lv-msg is-host';av.appendChild(heartNode());
    b.textContent=(m.author&&m.author!=='Host')?m.author:C.church;p.appendChild(b);
    var t=d.createElement('span');t.className='lv-tag';t.textContent='Host';p.appendChild(t);}
  else{li.className='lv-msg h-'+fam(m.author)+(m.mine?' is-mine':'');av.textContent=ini(m.author);
    b.textContent=m.mine?'You':m.author;p.appendChild(b);}
  p.appendChild(d.createTextNode(' '+m.body));li.appendChild(av);li.appendChild(p);return li;}
function near(){return list.scrollHeight-list.scrollTop-list.clientHeight<90;}
function down(){list.scrollTop=list.scrollHeight;if(newer)newer.hidden=true;}
function draw(ms){
  var have=[].map.call(list.querySelectorAll('li[data-id]'),function(li){return li.getAttribute('data-id');}),
      ids=ms.map(function(m){return m.id;}),stick=near(),added=0,k=ms.length?have.indexOf(ms[0].id):-1;
  // what scrolled out of the newest 60 leaves from the top; a hidden one redraws the list
  if(k>0){have.slice(0,k).forEach(function(id){var o=list.querySelector('li[data-id="'+id+'"]');if(o)o.remove();});have=have.slice(k);}
  var gone=have.some(function(id){return ids.indexOf(id)<0;});
  if(gone){list.textContent='';have=[];}
  ms.forEach(function(m){if(have.indexOf(m.id)<0){list.appendChild(row(m));added++;}});
  var empty=list.querySelector('.lv-empty');
  if(ms.length&&empty)empty.remove();
  if(!ms.length&&!empty){var e=d.createElement('li');e.className='lv-empty';e.textContent='No messages yet. Say hello.';list.appendChild(e);}
  if(stick||gone)down();else if(added&&newer)newer.hidden=false;}
// the message the team pinned (or none), drawn like a chat line
function setPin(m){if(!pin)return;pin.hidden=!m;if(!m)return;
  var av=d.getElementById('lv-pin-av'),who=d.getElementById('lv-pin-who');
  pin.className='lv-pin'+(m.host?' is-host':' h-'+fam(m.author));av.textContent='';
  if(m.host)av.appendChild(heartNode());else av.textContent=ini(m.author);
  who.textContent=m.host?((m.author&&m.author!=='Host')?m.author:C.church):(m.mine?'You':m.author);
  pinB.textContent=m.body;}
function setN(n){[].forEach.call(d.querySelectorAll('[data-here-n]'),function(e){e.textContent=n;});
  var w=d.getElementById('lv-herewrap');if(w)w.hidden=false;var h=d.querySelector('.lv-chat-h span');if(h)h.hidden=false;}
function tell(m){if(!toast)return;toast.textContent=m;toast.hidden=false;clearTimeout(tell.t);tell.t=setTimeout(function(){toast.hidden=true;},3800);}
if(toast&&!toast.hidden)tell.t=setTimeout(function(){toast.hidden=true;},4200);
function float(mine){if(!hearts||hearts.childElementCount>14)return;var s=d.createElement('span');
  s.className='lv-heart'+(mine?' is-mine':'')+' r'+(1+Math.floor(Math.random()*3));
  s.style.setProperty('--x',Math.round(Math.random()*26-13)+'px');s.appendChild(heartNode());hearts.appendChild(s);
  setTimeout(function(){s.remove();},2600);}
function others(total){var dl=total-seen;if(dl<=0)return;seen=total;var show=dl-credit;credit=Math.max(0,credit-dl);
  show=Math.min(show,8);for(var i=0;i<show;i++)setTimeout(function(){float(false);},i*260+Math.random()*200);}
function flush(){flushT=0;if(!pending)return;var k=pending;pending=0;
  fetch('/my/live/heart',{method:'POST',credentials:'same-origin',headers:JSONH,body:'n='+k})
  .then(function(r){return r.json();}).then(function(x){if(x&&x.ok)credit+=k;}).catch(function(){});}
function heart(){float(true);pending++;if(!flushT)flushT=setTimeout(flush,1200);}
function poll(){if(d.hidden)return;ticks++;
  fetch('/my/live/feed?v='+v+(ticks%6===1?'&n=1':''),{credentials:'same-origin',headers:{'Accept':'application/json'}})
  .then(function(r){return r.json();}).then(function(x){
    if(x.live===false){location.reload();return;}
    if(typeof x.hearts==='number')others(x.hearts);
    if(typeof x.here==='number')setN(x.here);
    if(x.same===false){v=x.v;draw(x.messages||[]);setPin(x.pin||null);}}).catch(function(){});}
function oops(m){if(!err)return;var s=near();err.textContent=m||'That didn’t send. Please try again.';err.hidden=false;
  if(s)down();clearTimeout(oops.t);oops.t=setTimeout(function(){err.hidden=true;},6000);}
function post(t,done){if(err)err.hidden=true;if(send)send.disabled=true;
  fetch('/my/live/chat',{method:'POST',credentials:'same-origin',headers:JSONH,body:'body='+encodeURIComponent(t)})
  .then(function(r){return r.json().then(function(x){return {ok:r.ok,x:x};});})
  .then(function(o){if(send)send.disabled=false;if(o.ok){if(done)done();down();poll();}else oops(o.x&&o.x.error);})
  .catch(function(){if(send)send.disabled=false;oops();});}
if(f&&say&&send){
  var mode=function(){var has=!!say.value.trim();f.classList.toggle('has-text',has);send.setAttribute('aria-label',has?'Send':'Send a heart');};
  say.addEventListener('input',mode);
  send.addEventListener('click',function(e){if(!say.value.trim()){e.preventDefault();heart();}});
  f.addEventListener('submit',function(e){e.preventDefault();var t=say.value.trim();if(t)post(t,function(){say.value='';mode();});});}
var quick=d.getElementById('lv-quick');
if(quick){var g=quick.querySelector('[data-greet]'),hr=new Date().getHours();
  if(g){var w=hr<12?'Good morning!':hr<17?'Good afternoon!':'Good evening!';g.value=w;g.textContent=w;}
  quick.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;e.preventDefault();post(b.value);});}
var here=d.getElementById('lv-here');
if(here&&here.tagName==='FORM')here.addEventListener('submit',function(e){e.preventDefault();var b=here.querySelector('button');b.disabled=true;
  fetch('/my/live/here',{method:'POST',credentials:'same-origin',headers:JSONH,body:''})
  .then(function(r){return r.json().then(function(x){return {ok:r.ok,x:x};});})
  .then(function(o){b.disabled=false;if(!o.ok){tell(o.x&&o.x.error||'That didn’t save. Please try again.');return;}
    var s=d.getElementById('lv-here-tpl').content.firstElementChild.cloneNode(true);here.replaceWith(s);
    if(typeof o.x.here==='number')setN(o.x.here);
    tell('You’re here. Welcome home'+(C.first?', '+C.first:'')+'!');})
  .catch(function(){b.disabled=false;tell('That didn’t save. Please try again.');});});
function sheet(dlg){var done=dlg.querySelector('.lv-done'),form=dlg.querySelector('form');
  if(done&&!done.hidden){done.hidden=true;form.hidden=false;}dlg.showModal();}
[].forEach.call(d.querySelectorAll('[data-sheet]'),function(a){var dlg=d.getElementById(a.getAttribute('data-sheet'));
  if(!dlg||typeof dlg.showModal!=='function')return;a.addEventListener('click',function(e){e.preventDefault();sheet(dlg);});});
[].forEach.call(d.querySelectorAll('dialog.lv-sheet'),function(dlg){
  dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close();});
  [].forEach.call(dlg.querySelectorAll('[data-close]'),function(b){b.addEventListener('click',function(){dlg.close();});});});
var pf=d.getElementById('lv-prayer-f');
if(pf)pf.addEventListener('submit',function(e){e.preventDefault();var b=pf.querySelector('[type=submit]'),pe=d.getElementById('lv-prayer-err');
  b.disabled=true;pe.hidden=true;
  fetch('/my/prayer',{method:'POST',credentials:'same-origin',headers:JSONH,body:new URLSearchParams(new FormData(pf)).toString()})
  .then(function(r){return r.json().then(function(x){return {ok:r.ok,x:x};});})
  .then(function(o){b.disabled=false;if(o.ok){pf.reset();pf.hidden=true;d.getElementById('lv-prayer-done').hidden=false;}
    else{pe.textContent=o.x&&o.x.error||'That didn’t send. Please try again.';pe.hidden=false;}})
  .catch(function(){b.disabled=false;pe.textContent='That didn’t send. Please try again.';pe.hidden=false;});});
var gf=d.getElementById('lv-give-f');
if(gf){var go=d.getElementById('lv-give-go'),other=d.getElementById('lv-other');
  var amt=function(){var o=parseFloat((other.value||'').replace(/[^0-9.]/g,''));if(o>=1)return o;
    var c=gf.querySelector('input[name=amount]:checked');return c?parseFloat(c.value):0;};
  var fund=function(){var c=gf.querySelector('[name=fund]:checked')||gf.querySelector('select[name=fund],input[type=hidden][name=fund]');return c?c.value:'';};
  var label=function(){var a=amt(),fd=fund();go.textContent=a?'Continue · $'+(a%1?a.toFixed(2):a.toLocaleString())+(fd?' to '+fd:''):'Continue';};
  gf.addEventListener('change',function(e){if(e.target.name==='amount')other.value='';label();});
  other.addEventListener('input',function(){if(other.value)[].forEach.call(gf.querySelectorAll('input[name=amount]'),function(r){r.checked=false;});label();});
  gf.addEventListener('submit',function(e){e.preventDefault();var a=amt();if(!a){other.focus();return;}
    location.href='/my/give?amount='+encodeURIComponent(a)+(fund()?'&fund='+encodeURIComponent(fund()):'');});
  label();}
var clock=d.getElementById('lv-clock'),t0=Date.parse(C.started||'');
if(t0){var st=d.getElementById('lv-started');
  if(st)st.textContent='Started '+new Date(t0).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
  var tick=function(){var s=Math.max(0,Math.floor((Date.now()-t0)/1000)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;
    clock.textContent=(h?h+':'+(m<10?'0':''):'')+m+':'+(x<10?'0':'')+x;};
  if(clock){clock.hidden=false;tick();setInterval(tick,1000);}}
if(newer)newer.addEventListener('click',down);
list.addEventListener('scroll',function(){if(newer&&near())newer.hidden=true;},{passive:true});
down();setInterval(poll,C.poll);
})();"""


def pinned_row(business_id: str, cur: Dict[str, Any], rows: List[Dict[str, Any]],
               me_id: str) -> Optional[Dict[str, Any]]:
    """The message the team pinned, as a phone shows a chat line (feed_rows),
    or None: nothing pinned, the pinned message is hidden, or reading it
    failed (the pin card hides; the chat is untouched). It's read on its
    own only when it has scrolled out of the newest FEED_LIMIT."""
    pid = str(cur.get("pinned_message_id") or "")
    if not pid:
        return None
    for m in rows:
        if str(m["id"]) == pid:
            return m
    got = sb_clients.sb_get_as_service(
        f"/live_chat?id=eq.{_q(pid)}&session_id=eq.{_q(cur['id'])}&business_id=eq.{_q(business_id)}"
        f"&hidden=eq.false&select=id,contact_id,author,host,body,hidden,created_at&limit=1")
    found = feed_rows(got, me_id) if isinstance(got, list) else []
    return found[0] if found else None


def feed(business_id: str, me: Dict[str, Any], v: int, with_here: bool = False) -> Dict[str, Any]:
    """The chat poll: {"live": False} once it ends; {"same": True} when
    nothing changed; else the newest visible messages and the pinned one
    (`pin`; pinning bumps chat_version). Every answer while live carries
    the service's hearts (the same read); `with_here` (the live room asks
    every sixth poll) adds how many are here, left out when that read
    fails."""
    import live_router as lr
    cur = lr.current(business_id)
    if cur is None:
        return {"error": "unavailable"}
    if not cur:
        return {"live": False}
    ver = int(cur.get("chat_version") or 0)
    out: Dict[str, Any] = {"live": True, "open": bool(cur.get("chat_open")), "v": ver,
                           "hearts": int(cur.get("hearts") or 0)}
    if with_here:
        n = here_count(business_id, cur["id"])
        if n is not None:
            out["here"] = n
    if ver == v:
        return {**out, "same": True}
    msgs = lr.messages(business_id, cur["id"], False, FEED_LIMIT)
    if msgs is None:
        return {"error": "unavailable"}
    rows = feed_rows(msgs, me["id"])
    return {**out, "same": False, "messages": rows, "pin": pinned_row(business_id, cur, rows, me["id"])}


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
    """The live room asks for JSON (the video keeps playing) and gets how
    many are here now, when that read works."""
    import asyncio
    import live_router as lr
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return _answer(request, False, "preview" if unavailable == "preview" else "error",
                       403 if unavailable == "preview" else 503)
    if not me:
        return _answer(request, False, "signed_out", 401) if _wants_json(request) else mpc._back("/my")
    if not mpc._allowed(church, me):
        return _answer(request, False, "slow", 429)
    biz_id = church["business"]["id"]
    cur = await asyncio.to_thread(lr.current, biz_id)
    if cur is None:
        return _answer(request, False, "error", 503)
    if not cur:
        return _answer(request, False, "not_live", 409)
    ok = await asyncio.to_thread(mark_here, biz_id, cur, me)
    if not ok:
        return _answer(request, False, "error", 503)
    if _wants_json(request):
        n = await asyncio.to_thread(here_count, biz_id, cur["id"])
        return JSONResponse({"ok": True, **({"here": n} if n is not None else {})})
    return _answer(request, True, "here")


@router.post("/my/live/heart", include_in_schema=False)
async def live_heart(request: Request):
    """Hearts from the live room, in a batch of 1 to HEARTS_MAX taps.
    Counted on the service only (live_add_hearts), never kept per person;
    the others' phones float them from their next poll. Always JSON."""
    import asyncio
    import live_router as lr
    import member_portal_church as mpc
    import rate_limit

    def no(code: str, status: int):
        return JSONResponse({"ok": False, "error": mpc.ERRORS.get(code, "That didn't send. Please try again.")},
                            status_code=status)

    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return no("preview" if unavailable == "preview" else "error", 403 if unavailable == "preview" else 503)
    if not me:
        return no("signed_out", 401)
    form = await request.form()
    try:
        n = max(1, min(HEARTS_MAX, int(str(form.get("n") or "1"))))
    except ValueError:
        n = 1
    biz_id = church["business"]["id"]
    cur = await asyncio.to_thread(lr.current, biz_id)
    if cur is None:
        return no("error", 503)
    if not cur:
        return no("not_live", 409)
    if not cur.get("chat_open"):
        return no("chat_closed", 409)
    if not rate_limit.allow_strict("live_heart", f"{biz_id}|{me['id']}"):
        return no("slow_chat", 429)
    total = await asyncio.to_thread(sb_clients.sb_post_as_service, "/rpc/live_add_hearts",
                                    {"p_session": cur["id"], "p_business": biz_id, "p_n": n})
    if isinstance(total, list):
        total = total[0] if total else None
    if isinstance(total, dict):
        total = next(iter(total.values()), None)
    if not isinstance(total, int):
        return no("error", 503)
    return JSONResponse({"ok": True, "hearts": total})
