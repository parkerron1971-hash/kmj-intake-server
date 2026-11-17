"""
member_portal_threads.py — "From your church": the member's inbox, drawn
like a phone's Messages (church_threads.py keeps the records and the
switch; Kevin, 2026-11-17).

  /my/inbox                    the conversations: the church first, then each
                               group the member is in that has notes
  /my/inbox/church             the church's notes as bubbles, the office's
                               replies, what the member wrote, and a box to
                               write to the church office
  /my/inbox/group/<gid>        a group's notes, for its members only (else
                               404); no box: the group's chat is its own place
  POST /my/inbox/church/send   the member writes to the church office

Who and which church come from the session, never the form. The owner's
preview reads, never writes (no read marks, no messages). Kids, and an
adult who switched into Youth, go back to /my (member_asks' rule: this lives
in Church); a teen may write, as a teen may ask the church for help.

A message is 1 to BODY_MAX characters, at most DAY_MAX a day, never two
within GAP_SECONDS. Each is screened (msg_screen) exactly as a group chat's:
harm is kept held (only the writer sees it) and the people who may review it
are told; crisis words deliver, show the 988 resources and send the pastor's
private note; a screen that can't run saves nothing and asks them to try
again. Once saved, the office hears by a staff alert that names the writer
by first name, never their words.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import church_threads as ct
import sb_clients

logger = logging.getLogger("member_portal_threads")
router = APIRouter(tags=["member-portal"])

PAGES = ("/my", "/my/inbox", "/my/inbox/church")
CHURCH_PAGE = "/my/inbox/church"

# The small button under a note that opens what it's about, by where it
# goes (a note's kind says little: an announcement can point anywhere).
# First match wins; anything else is "Open".
_GID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
LINK_WORDS = (
    (re.compile(r"^/my/(live|sermons|watch)(/|$)"), "Watch"),
    (re.compile(r"^/my/events(/|$)"), "See the event"),
    (re.compile(rf"^/my/groups/{_GID}/board(/|$)"), "Open the Board"),
    (re.compile(rf"^/my/groups/{_GID}/prayer(/|$)"), "Open the prayer wall"),
    (re.compile(rf"^/my/groups/{_GID}/meet(/|$)"), "See the gathering"),
    (re.compile(rf"^/my/groups/{_GID}/?$"), "Open the group"),
    (re.compile(r"^/my/serving(/|$)"), "See my serving"),
    (re.compile(r"^/my/news(/|$)"), "Read it"),
    (re.compile(r"^/my/classes(/|$)"), "Open the class"),
)


def link_word(url: Any) -> str:
    """The button's word for a note that opens `url`."""
    path = re.split(r"[?#]", str(url or ""), maxsplit=1)[0]
    return next((word for pattern, word in LINK_WORDS if pattern.match(path)), "Open")

DONE = {"ct_sent": "Sent. The church office will see it."}
ERRORS = {"ct_empty": "Write a message first.",
          "ct_long": f"Keep a message under {ct.BODY_MAX:,} characters.",
          "ct_day": f"That's {ct.DAY_MAX} messages today. You can write again tomorrow.",
          "ct_gap": "One moment, then send it again."}

THREAD_CSS = """
.ct-list{margin-top:16px;}
.ct-list a{align-items:flex-start;}
.ct-av{width:50px;height:50px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--s2);color:var(--fg);
  font-weight:650;font-size:16px;overflow:hidden;}
.ct-av img{width:100%;height:100%;object-fit:cover;}
.ct-av.is-church{background:var(--acc-soft);color:var(--acc);}
.ct-list .mb-list-text{padding-top:3px;}
.ct-list .mb-list-text span{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.ct-side{display:flex;flex-direction:column;align-items:flex-end;gap:6px;flex:none;padding-top:4px;}
.ct-when{font-size:12.5px;color:var(--fg3);font-variant-numeric:tabular-nums;}
.ct-new strong{font-weight:700;}
.ct-chat .ct-day{align-self:center;max-width:none;background:none;padding:0;margin:12px 0 2px;font-size:12px;font-weight:600;
  letter-spacing:.02em;color:var(--fg3);}
.ct-chat .mb-msg strong{font-size:15px;font-weight:650;letter-spacing:-.01em;}
.ct-chat .mb-msg-body{white-space:pre-line;}
.ct-at{font-size:11px;opacity:.7;margin-top:2px;font-variant-numeric:tabular-nums;}
.ct-open{display:inline-flex;align-items:center;gap:4px;align-self:flex-start;margin-top:6px;padding:6px 12px;border-radius:14px;
  background:var(--bg);color:var(--acc);font-size:13.5px;font-weight:620;text-decoration:none;}
.ct-open .mb-ic{width:14px;height:14px;}
.ct-compose textarea.mp-input{resize:none;padding:11px 18px;line-height:1.35;font:inherit;font-size:16px;max-height:160px;}
.ct-fine{margin:8px 2px 0;font-size:12.5px;color:var(--fg3);text-align:center;}
.ct-chatlink{display:flex;justify-content:center;margin:16px 0 4px;}
.mb-thread .ct-chat.ct-group{min-height:0;}
.ct-chatlink .mp-go{width:auto;padding:0 20px;}
"""


def _e(s: Any) -> str:
    from member_portal import _e as esc
    return esc(s)


# ─── Times, like Messages ─────────────────────────────────────────────


def _zone(biz: Dict[str, Any]):
    try:
        import group_gatherings
        z = group_gatherings.zone(biz)
        if z is not None:
            return z
    except Exception:
        pass
    return timezone.utc


def _at(iso: Any, zone) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(zone)


def _clock(d: datetime) -> str:
    return d.strftime("%I:%M %p").lstrip("0")


def when_short(iso: Any, zone, now: Optional[datetime] = None) -> str:
    """The inbox's time: 3:45 PM today, Yesterday, a weekday this week,
    else Nov 3."""
    d = _at(iso, zone)
    if d is None:
        return ""
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    days = (today - d.date()).days
    if days <= 0:
        return _clock(d)
    if days == 1:
        return "Yesterday"
    if days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%b')} {d.day}"


def day_label(d: datetime, now: Optional[datetime] = None) -> str:
    today = (now or datetime.now(timezone.utc)).astimezone(d.tzinfo or timezone.utc).date()
    days = (today - d.date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}" + (f", {d.year}" if d.year != today.year else "")


# ─── Reading ──────────────────────────────────────────────────────────


def preview(r: Optional[Dict[str, Any]], said_by: str = "") -> str:
    """One line for a row: what the church said, the office's reply by its
    writer, or "You: ...". A title that only repeats the conversation's
    name (`said_by`: a group's notes carry the group's name) is left out."""
    if not r:
        return ""
    body = " ".join(str(r.get("body") or "").split())
    if r.get("direction") == "member":
        return f"You: {body}"
    if r.get("kind") == "reply":
        return f"{r.get('author_name') or 'The office'}: {body}"
    title = " ".join(str(r.get("title") or "").split())
    if title and said_by and title.casefold() == said_by.casefold() and body:
        title = ""
    return f"{title} — {body}" if title and body else (title or body)


def my_group_ids(business_id: str, contact_id: str) -> Optional[List[str]]:
    import member_portal_messaging as mpm
    rows = mpm.my_groups(business_id, contact_id)
    return None if rows is None else sorted({str(r["group_id"]) for r in rows if r.get("group_id")})


def entry_open(biz: Dict[str, Any]) -> bool:
    """Whether to point at the inbox at all (Home and Me)."""
    return ct.open_for(biz) and ct.tables_ready()


def thread_name(biz: Dict[str, Any], thread: str) -> str:
    """The conversation's name: the church's, or its group's (read)."""
    gid = ct.group_of(thread)
    if not gid:
        return (biz.get("name") or "").strip() or "Your church"
    rows = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{ct._q(biz['id'])}&id=eq.{ct._q(gid)}&select=name&limit=1")
    return str((rows[0] if isinstance(rows, list) and rows else {}).get("name") or "").strip() or "Your group"


def home_card(biz: Dict[str, Any], me: Dict[str, Any]) -> str:
    """Home's card while anything is unread: "From your church", how many
    are new, and the newest one as "<conversation>: <its line>", so a
    group's note reads as the group's. '' otherwise. Never raises."""
    try:
        if not entry_open(biz):
            return ""
        gids = my_group_ids(str(biz["id"]), str(me["id"]))
        if gids is None:
            return ""
        got = ct.summary(str(biz["id"]), str(me["id"]), gids)
        if not got:
            return ""
        n = sum(t["unread"] for t in got.values())
        if not n:
            return ""
        newest = max((t["last"] for t in got.values() if t["unread"] and t.get("last")),
                     key=lambda r: str(r.get("created_at") or ""), default=None)
        import member_app_ui as ui
        line = ""
        if newest:
            name = thread_name(biz, str(newest.get("thread") or ct.CHURCH))
            said = preview(newest, name)
            line = f"{name}: {said}" if said else name
        return (f'<a class="mb-row h-teal ct-home" href="/my/inbox"><span class="mb-row-ic ct-home-ic">{ui.icon("chat", 20)}</span>'
                f'<span class="mb-row-t"><strong>From your church</strong><span>{n} new{" · " + _e(line) if line else ""}</span></span>'
                f'{ui.icon("chevron", 18)}</a>'
                '<style>.ct-home-ic{background:var(--h-deep);color:var(--h-ink);}'
                '.ct-home .mb-row-t span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}</style>')
    except Exception:
        logger.warning("church threads: Home's card was skipped", exc_info=True)
        return ""


# ─── Pages ────────────────────────────────────────────────────────────


def _church_av(biz: Dict[str, Any], site) -> str:
    import member_app_ui as ui
    try:
        from public_form_theme import resolve_theme
        logo = resolve_theme(biz, site).get("logo_url") or ""
    except Exception:
        logo = ""
    name = (biz.get("name") or "").strip() or "Your church"
    inner = f'<img src="{_e(logo)}" alt="">' if logo else _e(ui.initials(name))
    return f'<span class="ct-av is-church" aria-hidden="true">{inner}</span>'


def _row(href: str, av: str, title: str, line: str, when: str, unread: int) -> str:
    badge = f'<span class="mb-unread" aria-label="{unread} new">{unread}</span>' if unread else ""
    return (f'<li class="{"ct-new" if unread else ""}"><a href="{_e(href)}">{av}'
            f'<span class="mb-list-text"><strong>{_e(title)}</strong><span>{_e(line)}</span></span>'
            f'<span class="ct-side"><span class="ct-when">{_e(when)}</span>{badge}</span></a></li>')


def render_inbox(biz: Dict[str, Any], site, me: Dict[str, Any], got: Dict[str, Dict[str, Any]],
                 groups: Dict[str, Dict[str, Any]], zone) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    name = (biz.get("name") or "").strip() or "Your church"
    church = got.get(ct.CHURCH) or {"last": None, "unread": 0}
    last = church.get("last")
    rows = [_row(CHURCH_PAGE, _church_av(biz, site), name, preview(last, name) or "Write to the church office",
                 when_short((last or {}).get("created_at"), zone) if last else "", church["unread"])]
    others = sorted(((t, v) for t, v in got.items() if t != ct.CHURCH and v.get("last")),
                    key=lambda tv: str(tv[1]["last"].get("created_at") or ""), reverse=True)
    for t, v in others:
        gid = ct.group_of(t)
        g = groups.get(gid)
        if not g:
            continue
        av = f'<span class="ct-av" aria-hidden="true">{ui.icon("users", 20)}</span>'
        rows.append(_row(ct.inbox_url(t), av, g.get("name") or "Your group", preview(v["last"], g.get("name") or ""),
                         when_short(v["last"].get("created_at"), zone), v["unread"]))
    body = (f'<style>{THREAD_CSS}</style><div class="mb-lt"><h1>From your church</h1></div>'
            f'<p class="mb-sub">Notes from {_e(name)} and your groups, in one place. Write back to the church office any time.</p>'
            f'<ul class="mb-list mb-cards ct-list" style="--inset:76px">{"".join(rows)}</ul>')
    return _shell(biz, site, "From your church", body, tab="me", who=me, back=("/my", "Home"))


def _bubble(r: Dict[str, Any], zone, said_by: str = "") -> str:
    import member_app_ui as ui
    d = _at(r.get("created_at"), zone)
    at = f'<span class="ct-at">{_e(_clock(d))}</span>' if d else ""
    body = _e(r.get("body") or "")
    if r.get("direction") == "member":
        held = ('<span class="mb-msg-held">Held for review. Only you can see it.</span>' if r.get("held") else "")
        return f'<li class="mb-msg mb-mine"><span class="mb-msg-body">{body}</span>{held}{at}</li>'
    if r.get("kind") == "reply":
        who = _e(r.get("author_name") or "The office")
        return (f'<li class="mb-msg"><span class="mb-msg-who">{who}</span>'
                f'<span class="mb-msg-body">{body}</span>{at}</li>')
    t = str(r.get("title") or "")
    if said_by and t.casefold() == said_by.casefold() and r.get("body"):
        t = ""                                      # a group's note carries the group's name: the header says it
    title = f'<strong>{_e(t)}</strong>' if t else ""
    url = str(r.get("url") or "")
    link = ""
    if url.startswith("/my/") and not ct.is_inbox_url(url):
        link = f'<a class="ct-open" href="{_e(url)}">{_e(link_word(url))}{ui.icon("chevron", 14)}</a>'
    text = f'<span class="mb-msg-body">{body}</span>' if body else ""
    return f'<li class="mb-msg ct-note">{title}{text}{link}{at}</li>'


def _bubbles(rows: List[Dict[str, Any]], zone, empty: str, said_by: str = "") -> str:
    out, day = [], None
    for r in rows:
        d = _at(r.get("created_at"), zone)
        if d is not None and d.date() != day:
            day = d.date()
            out.append(f'<li class="mb-msg ct-day" role="separator">{_e(day_label(d))}</li>')
        out.append(_bubble(r, zone, said_by))
    return "".join(out) or f'<li class="mb-chat-empty mp-muted">{_e(empty)}</li>'


def _flash(request: Request) -> str:
    import member_portal_church as mpc
    q = request.query_params
    err = ERRORS.get(q.get("err") or "") or mpc.ERRORS.get(q.get("err") or "")
    done = DONE.get(q.get("done") or "") or mpc.DONE.get(q.get("done") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


SCROLL_JS = """<script>(function(){var b=document.getElementById('ct-chat');if(b){window.scrollTo(0,document.documentElement.scrollHeight);}
var t=document.getElementById('ct-say');if(!t)return;function fit(){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,160)+'px';}
t.addEventListener('input',fit);fit();
var f=document.getElementById('ct-compose');if(f){f.addEventListener('submit',function(){var s=f.querySelector('button');if(s)s.disabled=true;});}
})();</script>"""


def render_church(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                  rows: List[Dict[str, Any]], zone) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    name = (biz.get("name") or "").strip() or "Your church"
    chat = _bubbles(rows, zone, f"Notes from {name} show up here. You can write to the church office below.", name)
    compose = (f'<form class="mb-compose ct-compose" method="post" action="{CHURCH_PAGE}/send" id="ct-compose">'
               '<label class="mp-sr" for="ct-say">Message the church office</label>'
               f'<textarea class="mp-input" id="ct-say" name="body" rows="1" maxlength="{ct.BODY_MAX}" required '
               'placeholder="Message the church office"></textarea>'
               f'<button class="mp-go" type="submit" aria-label="Send">{ui.icon("send", 18)}</button></form>'
               '<p class="ct-fine">Goes to the church office. It isn&#x27;t posted anywhere.</p>')
    body = (f'<style>{THREAD_CSS}</style><div class="mb-thread"><div class="mb-lt"><h1 style="font-size:28px">{_e(name)}</h1></div>'
            f'{_flash(request)}<ul class="mb-chat ct-chat" id="ct-chat" aria-label="Messages">{chat}</ul>{compose}</div>')
    return _shell(biz, site, name, body, tab="me", who=me, bar=False, back=("/my/inbox", "Inbox"), script=SCROLL_JS)


def render_group(biz: Dict[str, Any], site, me: Dict[str, Any], g: Dict[str, Any], rows: List[Dict[str, Any]],
                 zone, chat_open: bool) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    name = g.get("name") or "Your group"
    chat = _bubbles(rows, zone, "Your group's news shows up here: a leader's posts and prayer requests.", name)
    link = (f'<div class="ct-chatlink"><a class="mp-go" href="/my/groups/{_e(g["id"])}/chat">{ui.icon("chat", 17)}'
            'Open the group chat</a></div>' if chat_open else "")
    body = (f'<style>{THREAD_CSS}</style><div class="mb-thread"><div class="mb-lt"><h1 style="font-size:28px">{_e(name)}</h1></div>'
            f'<ul class="mb-chat ct-chat ct-group" id="ct-chat" aria-label="Notes">{chat}</ul>{link}</div>')
    return _shell(biz, site, name, body, tab="me", who=me, bar=False, back=("/my/inbox", "Inbox"), script=SCROLL_JS)


def render_missing(biz: Dict[str, Any], site, me: Dict[str, Any]) -> str:
    from member_portal import _shell
    body = ('<div class="mb-lt"><h1>Not here</h1></div>'
            '<p class="mp-muted">This conversation is for the people in that group. Your conversations are in '
            '<a href="/my/inbox">From your church</a>.</p>')
    return _shell(biz, site, "Not here", body, tab="me", who=me, back=("/my/inbox", "Inbox"))


def render_error(biz: Dict[str, Any], site, me: Dict[str, Any]) -> str:
    from member_portal import _shell
    body = ('<p class="mp-err" role="alert">Your messages couldn&#x27;t load just now. Please try again in a moment.</p>'
            '<p><a href="/my/inbox">Try again</a></p>')
    return _shell(biz, site, "From your church", body, tab="me", who=me, back=("/my", "Home"))


def _in_church(space_ctx: Dict[str, Any]) -> bool:
    """Kids, and an adult who switched into Youth, go back to /my."""
    space = space_ctx.get("space", "church")
    return not (space == "kids" or (space == "youth" and not space_ctx.get("youth")))


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str, *, preview: bool = False):
    """GET /my/inbox and its conversations (member_portal.serve). (html,
    status), or a redirect."""
    import member_spaces as msp
    from member_portal import _SECURE_HEADERS
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if not _in_church(msp.CURRENT.get() or {}):
        return home
    if not await asyncio.to_thread(entry_open, biz):
        return home
    biz_id, me_id = str(biz["id"]), str(me["id"])
    zone = await asyncio.to_thread(_zone, biz)
    if sub == "/my/inbox":
        gids = await asyncio.to_thread(my_group_ids, biz_id, me_id)
        got = await asyncio.to_thread(ct.summary, biz_id, me_id, gids or []) if gids is not None else None
        if got is None:
            return render_error(biz, site, me), 503
        groups: Dict[str, Dict[str, Any]] = {}
        want = sorted(ct.group_of(t) for t in got if t != ct.CHURCH)
        if want:
            rows = await asyncio.to_thread(
                sb_clients.sb_get_as_service,
                f"/groups?business_id=eq.{ct._q(biz_id)}&id=in.({','.join(ct._q(g) for g in want)})&select=id,name")
            if not isinstance(rows, list):
                return render_error(biz, site, me), 503
            groups = {str(r["id"]).lower(): r for r in rows}
        return render_inbox(biz, site, me, got, groups, zone), 200
    if sub == CHURCH_PAGE:
        rows = await asyncio.to_thread(ct.church_notes, biz_id, me_id)
        if rows is None:
            return render_error(biz, site, me), 503
        if not preview:
            await asyncio.to_thread(ct.mark_read, biz_id, me_id, ct.CHURCH)
        return render_church(biz, site, request, me, rows, zone), 200
    if sub.startswith("/my/inbox/group/"):
        import member_portal_groups as mpg
        gid = sub[len("/my/inbox/group/"):].strip("/").lower()
        if not ct.UUID_RE.match(gid):
            return render_missing(biz, site, me), 404
        member, g = await asyncio.gather(asyncio.to_thread(mpg._is_member, biz_id, gid, me_id),
                                         asyncio.to_thread(mpg.group_row, biz_id, gid))
        if member is None or g is None:
            return render_error(biz, site, me), 503
        if not member or not g:
            return render_missing(biz, site, me), 404
        rows = await asyncio.to_thread(ct.group_notes, biz_id, me_id, gid)
        if rows is None:
            return render_error(biz, site, me), 503
        if not preview:
            await asyncio.to_thread(ct.mark_read, biz_id, me_id, f"group:{gid}")
        import member_portal_messaging as mpm
        chat_open = mpm.turned_on(biz) and g.get("chat_on") is not False
        return render_group(biz, site, me, g, rows, zone, chat_open), 200
    return RedirectResponse("/my/inbox", status_code=303, headers=_SECURE_HEADERS)


# ─── Writing to the church office ─────────────────────────────────────


def recent_mine(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    """The member's messages from the last day, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/{ct.NOTES}?business_id=eq.{ct._q(business_id)}&contact_id=eq.{ct._q(contact_id)}&direction=eq.member"
        f"&created_at=gte.{ct._q(since)}&select=id,created_at&order=created_at.desc&limit={ct.DAY_MAX + 1}")
    return rows if isinstance(rows, list) else None


def too_soon(rows: List[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    if not rows:
        return False
    d = _at(rows[0].get("created_at"), timezone.utc)
    return d is not None and ((now or datetime.now(timezone.utc)) - d).total_seconds() < ct.GAP_SECONDS


async def send_message(biz: Dict[str, Any], me: Dict[str, Any], text: str) -> Tuple[bool, str]:
    """The member's message to the church office. (ok, code): the code is
    the page's flash."""
    import msg_screen
    import sample_church
    if sample_church.skip(biz):                     # a sample church records and sends nothing
        return False, "preview"
    if not text:
        return False, "ct_empty"
    if len(text) > ct.BODY_MAX:
        return False, "ct_long"
    biz_id, me_id = str(biz["id"]), str(me["id"])
    mine = await asyncio.to_thread(recent_mine, biz_id, me_id)
    if mine is None:
        return False, "error"
    if len(mine) >= ct.DAY_MAX:
        return False, "ct_day"
    if too_soon(mine):
        return False, "ct_gap"
    try:
        verdict = await msg_screen.screen(biz_id, text)
    except msg_screen.ScreenUnavailable:
        return False, "screen_off"
    held = verdict == "harm"
    first = (str(me.get("name") or "").strip().split() or [""])[0]
    row = await asyncio.to_thread(sb_clients.sb_post_as_service, f"/{ct.NOTES}", {
        "business_id": biz_id, "contact_id": me_id, "thread": ct.CHURCH, "direction": "member", "kind": "message",
        "title": None, "body": text, "url": None, "ref_id": None, "author_user_id": None,
        "author_name": first or None, "held": held}, redact=True)
    if not isinstance(row, list) or not row:
        return False, "error"
    if held:
        ct.tell_reviewers(biz_id, str(row[0].get("id") or ""))
        return True, "held"
    ct.tell_office(biz_id, me_id, first)
    if verdict == "self_harm":
        import member_portal_messaging as mpm
        await asyncio.to_thread(mpm.care_alert, biz_id, me)
        return True, "care"
    return True, "ct_sent"


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target not in PAGES:
        target = "/my"
    q = {k: v for k, v in q.items() if v}
    return RedirectResponse(f"{target}?{urlencode(q)}" if q else target, status_code=303, headers=_SECURE_HEADERS)


@router.post("/my/inbox/church/send", include_in_schema=False)
async def send_route(request: Request):
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    if unavailable:
        return _go(CHURCH_PAGE, err="preview" if unavailable == "preview" else "error")
    if not me:
        return _go("/my")
    biz = church["business"]
    if not await asyncio.to_thread(entry_open, biz):
        return _go("/my")
    if not mpc._allowed(church, me):
        return _go(CHURCH_PAGE, err="slow")
    ok, code = await send_message(biz, me, ct.words(form.get("body")))
    return _go(CHURCH_PAGE, **({"done": code} if ok else {"err": code}))
