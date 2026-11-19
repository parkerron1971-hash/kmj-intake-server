"""
member_portal_threads.py — the church's conversation and its groups' notes
inside Messages, drawn like a phone's Messages app (church_threads.py keeps
the records and the switch; Kevin, 2026-11-17).

ONE MESSAGING PLACE (Kevin, 2026-11-17: "make sure that the section where
the messages are in group chat are not two messaging chats in the system").
While church threads are open for a church, /my/messages is the one inbox
(member_portal_messaging.serve hands it to messages_page):

  (a) the church's conversation, pinned first
  (b) chat requests
  (c) one row per group the member is in, newest first: its chat and its
      notes together, one unread count
  (d) private chats

It works with the church's chats off too: then only (a) and (c). A group's
row opens its chat when the chat is open to the member, and the group's
notes (Board posts, prayer-wall requests) sit inside the chat as small
cards (member_portal_groups); otherwise it opens the notes view.

  /my/inbox                    302 to /my/messages (old links, lock screens)
  /my/inbox/church             the church's notes as bubbles, the office's
                               replies, what the member wrote, and a box to
                               write to the church office
  /my/inbox/group/<gid>        302 to the group's chat when it's open to the
                               member, else the group's notes, for its members
                               only (else 404)
  POST /my/inbox/church/send   the member writes to the church office

The header's chat icon carries one unread count (church, groups and chats)
and Home's "Messages" card shows while anything is unread; both only while
threads are open here (counts()).

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
import contextvars
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

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


# ─── Unread: the header's count and Home's card ──────────────────────

BADGE: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("messages_badge", default=None)
_COUNTS: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
COUNTS_SECONDS = 15
CHAT_WINDOW_DAYS = 60


def forget(business_id: Any, contact_id: Any) -> None:
    """Something was just read here: the next count is fresh."""
    _COUNTS.pop((str(business_id), str(contact_id)), None)


def may_chat(full: Optional[Dict[str, Any]]) -> bool:
    """Messaging's own rules let this member into chats (a birthdate, their
    switch on, the guidelines agreed)."""
    import member_messaging_rules as rules
    return bool(full) and not rules.why_not(full) and bool(full.get("guidelines_at"))


def chat_unread(business_id: str, me_id: str, group_ids: List[str]) -> Optional[int]:
    """Unread chat messages: another person's delivered messages since the
    member last read each chat (theirs, and their groups'), at most 30 a
    chat, as Messages counts them. None when a read failed."""
    b, c = ct._q(business_id), ct._q(me_id)
    mine = sb_clients.sb_get_as_service(
        f"/msg_participants?business_id=eq.{b}&contact_id=eq.{c}&select=thread_id,state,last_read_at")
    if not isinstance(mine, list):
        return None
    gthreads: List[Dict[str, Any]] = []
    if group_ids:
        got = sb_clients.sb_get_as_service(
            f"/msg_threads?business_id=eq.{b}&kind=eq.group&group_id=in.({','.join(ct._q(g) for g in group_ids)})"
            "&select=id")
        if not isinstance(got, list):
            return None
        gthreads = got
    declined = {str(p["thread_id"]) for p in mine if p.get("state") == "declined"}
    read = {str(p["thread_id"]): str(p.get("last_read_at") or "") for p in mine}
    tids = (set(read) | {str(t["id"]) for t in gthreads}) - declined
    if not tids:
        return 0
    since = (datetime.now(timezone.utc) - timedelta(days=CHAT_WINDOW_DAYS)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/msg_messages?business_id=eq.{b}&thread_id=in.({','.join(ct._q(t) for t in sorted(tids))})"
        f"&status=eq.delivered&sender_contact_id=neq.{c}&created_at=gte.{ct._q(since)}"
        "&select=thread_id,created_at&order=created_at.desc&limit=2000")
    if not isinstance(rows, list):
        return None
    per: Dict[str, int] = {}
    for m in rows:
        t = str(m.get("thread_id"))
        if str(m.get("created_at") or "") > read.get(t, "") and per.get(t, 0) < 30:
            per[t] = per.get(t, 0) + 1
    return sum(per.values())


async def counts(biz: Dict[str, Any], me: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What's unread in Messages, while church threads are open here:
    {"notes": church_threads.summary, "chat": n, "total": n}. Kept
    COUNTS_SECONDS per member per replica (reading something here forgets
    it). None when threads aren't open or a read failed. Never raises."""
    try:
        if not await asyncio.to_thread(entry_open, biz):
            return None
        key = (str(biz["id"]), str(me["id"]))
        hit = _COUNTS.get(key)
        if hit and time.monotonic() - hit[0] < COUNTS_SECONDS:
            return hit[1]
        gids = await asyncio.to_thread(my_group_ids, key[0], key[1])
        if gids is None:
            return None

        async def chats() -> Optional[int]:
            import member_portal_messaging as mpm
            if not mpm.turned_on(biz):
                return 0
            full = await asyncio.to_thread(mpm._me_profile, key[0], me)
            if not may_chat(full):
                return 0
            return await asyncio.to_thread(chat_unread, key[0], key[1], gids)
        notes, chat = await asyncio.gather(asyncio.to_thread(ct.summary, key[0], key[1], gids), chats())
        if notes is None:
            return None
        out = {"notes": notes, "chat": chat or 0,
               "total": sum(t["unread"] for t in notes.values()) + (chat or 0)}
        _COUNTS[key] = (time.monotonic(), out)
        return out
    except Exception:
        logger.warning("church threads: unread counts were skipped", exc_info=True)
        return None


def home_card(biz: Dict[str, Any], got: Optional[Dict[str, Any]]) -> str:
    """Home's "Messages" card while anything is unread: how many are new,
    and the newest note as "<conversation>: <its line>", so a group's note
    reads as the group's (chats alone: "New messages in your chats").
    '' otherwise. Never raises."""
    try:
        if not got or not got.get("total"):
            return ""
        notes = got.get("notes") or {}
        newest = max((t["last"] for t in notes.values() if t["unread"] and t.get("last")),
                     key=lambda r: str(r.get("created_at") or ""), default=None)
        import member_app_ui as ui
        line = ""
        if newest:
            name = thread_name(biz, str(newest.get("thread") or ct.CHURCH))
            said = preview(newest, name)
            line = f"{name}: {said}" if said else name
        elif got.get("chat"):
            line = "New messages in your chats"
        n = int(got["total"])
        return (f'<a class="mb-row h-teal ct-home" href="/my/messages"><span class="mb-row-ic ct-home-ic">{ui.icon("chat", 20)}</span>'
                f'<span class="mb-row-t"><strong>Messages</strong><span>{n} new{" · " + _e(line) if line else ""}</span></span>'
                f'{ui.icon("chevron", 18)}</a>'
                '<style>.ct-home-ic{background:var(--h-deep);color:var(--h-ink);}'
                '.ct-home .mb-row-t span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}</style>')
    except Exception:
        logger.warning("church threads: Home's card was skipped", exc_info=True)
        return ""

# ─── Pages ────────────────────────────────────────────────────────────


def _logo(biz: Dict[str, Any], site) -> str:
    try:
        from public_form_theme import resolve_theme
        return resolve_theme(biz, site).get("logo_url") or ""
    except Exception:
        return ""


def _church_av(biz: Dict[str, Any], site) -> str:
    import member_app_ui as ui
    logo = _logo(biz, site)
    name = (biz.get("name") or "").strip() or "Your church"
    inner = f'<img src="{_e(logo)}" alt="">' if logo else _e(ui.initials(name))
    return f'<span class="ct-av is-church" aria-hidden="true">{inner}</span>'


def _row(href: str, av: str, title: str, line: str, when: str, unread: int) -> str:
    badge = f'<span class="mb-unread" aria-label="{unread} new">{unread}</span>' if unread else ""
    return (f'<li class="{"ct-new" if unread else ""}"><a href="{_e(href)}">{av}'
            f'<span class="mb-list-text"><strong>{_e(title)}</strong><span>{_e(line)}</span></span>'
            f'<span class="ct-side"><span class="ct-when">{_e(when)}</span>{badge}</span></a></li>')


def _newest_first(items: List[Tuple[Optional[datetime], str, str]]) -> List[str]:
    """Rows newest first; those with nothing in them yet after, by name."""
    dated = sorted((i for i in items if i[0] is not None), key=lambda i: i[0], reverse=True)
    rest = sorted((i for i in items if i[0] is None), key=lambda i: i[1].casefold())
    return [i[2] for i in dated + rest]


GATE_WORDS = {
    "guidelines": "Agree to the chat guidelines to message your groups and other members.",
    "no_birthdate": "Chats need your birthdate on your record. Ask the church office to add it.",
    "not_enabled": "Ask the church office to turn on chats for you.",
}


def render_messages(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], *,
                    got: Dict[str, Dict[str, Any]], groups: List[Dict[str, Any]], zone, gate: Optional[str] = None,
                    chats: Optional[List[Dict[str, Any]]] = None, requests: Optional[List[Dict[str, Any]]] = None,
                    start: Optional[List[Dict[str, Any]]] = None, family: Optional[List[Dict[str, Any]]] = None) -> str:
    """Messages, the one inbox: the church's conversation pinned first,
    chat requests, a row per group (its chat and its notes together, one
    count), then private chats. `gate`: why the member's chats aren't open
    ('off' when the church's chats are off); then only the church and the
    groups, each group opening its notes."""
    import member_lumen
    if member_lumen.page():
        return _lumen_messages(biz, site, request, me, got=got, groups=groups, zone=zone, gate=gate, chats=chats,
                               requests=requests, start=start, family=family)
    import member_app_ui as ui
    import member_portal_church as mpc
    import member_portal_messaging as mpm
    import member_spaces as msp
    from member_portal import _shell
    name = (biz.get("name") or "").strip() or "Your church"
    church = got.get(ct.CHURCH) or {"last": None, "unread": 0}
    last = church.get("last")
    pinned = _row(CHURCH_PAGE, _church_av(biz, site), name, preview(last, name) or "Write to the church office",
                  when_short((last or {}).get("created_at"), zone) if last else "", church["unread"])
    open_chats = gate is None
    chat_rows = (chats or []) if open_chats else []
    by_group = {str(r.get("group_id") or "").lower(): r for r in chat_rows if r.get("kind") == "group"}
    users = f'<span class="ct-av" aria-hidden="true">{ui.icon("users", 20)}</span>'

    def when(at: Optional[datetime]) -> str:
        return when_short(at.isoformat(), zone) if at else ""
    items: List[Tuple[Optional[datetime], str, str]] = []
    for g in groups:
        gid = str(g["id"]).lower()
        gname = str(g.get("name") or "Your group")
        chat = by_group.get(gid) or {}
        note = got.get(f"group:{gid}") or {}
        nl = note.get("last")
        chat_at = _at(chat.get("at"), zone) if chat.get("at") else None
        note_at = _at(nl.get("created_at"), zone) if nl else None
        if chat_at and (not note_at or chat_at >= note_at):
            line, at = str(chat.get("preview") or ""), chat_at
        elif note_at:
            line, at = preview(nl, gname), note_at
        else:
            line, at = "No messages yet", None
        href = (f"/my/groups/{gid}/chat" if open_chats and g.get("chat_on") is not False
                else f"/my/inbox/group/{gid}")
        unread = int(chat.get("unread") or 0) + int(note.get("unread") or 0)
        items.append((at, gname, _row(href, users, gname, line, when(at), unread)))
    for r in chat_rows:
        if r.get("kind") == "leaders":
            at = _at(r.get("at"), zone) if r.get("at") else None
            items.append((at, r["title"], _row("/my/groups/leaders", users, r["title"], str(r.get("preview") or ""),
                                               when(at), int(r.get("unread") or 0))))

    def person(r: Dict[str, Any]) -> str:
        face = (f'<img src="{_e(r["photo"])}" alt="" loading="lazy">' if r.get("photo") else _e(ui.initials(r["title"])))
        at = _at(r.get("at"), zone) if r.get("at") else None
        return _row(f"/my/messages/{r['id']}", f'<span class="ct-av" aria-hidden="true">{face}</span>', r["title"],
                    str(r.get("preview") or ""), when(at), int(r.get("unread") or 0))
    direct = [person(r) for r in chat_rows if r.get("kind") == "direct"]
    asked = [person(r) for r in (requests or [])] if open_chats else []
    youth = (msp.CURRENT.get() or {}).get("youth")
    head = ('<div class="mb-lt"><h1>Chats</h1></div>' + msp.safety_banner() if youth else
            mpc.connect_head(biz, "messages"))
    lists = '<ul class="mb-list mb-cards ct-list" style="--inset:76px">{}</ul>'
    body = [f"<style>{THREAD_CSS}</style>{head}{mpc._flash(request)}", lists.format(pinned)]
    if gate and gate != "off":
        words = GATE_WORDS.get(gate, "Chats aren't open to you right now.")
        go = ('<a class="mp-go" style="margin-top:12px" href="/my/messages?join=1">Read the guidelines</a>'
              if gate == "guidelines" else "")
        body.append(f'<div class="mp-card ct-gate" style="margin-top:14px"><p class="mp-muted" style="margin:0">{_e(words)}</p>{go}</div>')
    if asked:
        body.append(ui.section("Requests") + lists.format("".join(asked)))
    if items:
        body.append(ui.section("Groups") + lists.format("".join(_newest_first(items))))
    if direct:
        body.append(ui.section("Chats") + lists.format("".join(direct)))
    if open_chats and start:
        body.append(ui.section("Start a chat") + '<ul class="mb-list mb-cards">' + "".join(
            f'<li><a href="/my/messages/to/{_e(p["id"])}"><span class="mb-thumb mb-chat-av">{_e(ui.initials(p["name"]))}</span>'
            f'<span class="mb-list-text"><strong>{_e(mpm.first_and_initial(p["name"]))}</strong><span>{_e(p["why"])}</span></span>'
            f'{ui.icon("chevron", 16)}</a></li>' for p in start) + '</ul>')
    if open_chats and family:
        body.append(ui.section("Your teens") + '<ul class="mb-list mb-cards">' + "".join(
            f'<li><a href="/my/messages/family/{_e(t["id"])}"><span class="mb-thumb mb-chat-av">{mpm._teen_face(t)}</span>'
            f'<span class="mb-list-text"><strong>{_e(t["name"])}</strong><span>Read their chats</span></span>{ui.icon("chevron", 16)}</a></li>'
            for t in family) + '</ul>')
    return _shell(biz, site, "Messages", "".join(body), tab="messages", who=me)


def _group_line(g: Dict[str, Any], chat: Dict[str, Any], note: Dict[str, Any], zone) -> Tuple[str, Optional[datetime]]:
    """A group's row: its chat's last line or its notes' newest, whichever
    came last, and when."""
    gname = str(g.get("name") or "Your group")
    nl = note.get("last")
    chat_at = _at(chat.get("at"), zone) if chat.get("at") else None
    note_at = _at(nl.get("created_at"), zone) if nl else None
    if chat_at and (not note_at or chat_at >= note_at):
        return str(chat.get("preview") or ""), chat_at
    if note_at:
        return preview(nl, gname), note_at
    return "No messages yet", None


def _lumen_messages(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], *,
                    got: Dict[str, Dict[str, Any]], groups: List[Dict[str, Any]], zone, gate: Optional[str],
                    chats: Optional[List[Dict[str, Any]]], requests: Optional[List[Dict[str, Any]]],
                    start: Optional[List[Dict[str, Any]]], family: Optional[List[Dict[str, Any]]]) -> str:
    """Messages in the new look (member_lumen_people): the church's
    conversation pinned first, then every chat newest first (the groups,
    the leaders' room, private chats), each with its unread count; the same
    rows and the same doors as render_messages, read the same way."""
    import member_lumen_people as lp
    name = (biz.get("name") or "").strip() or "Your church"
    church = got.get(ct.CHURCH) or {"last": None, "unread": 0}
    last = church.get("last")
    pinned = lp.inbox_row(CHURCH_PAGE, lp.church_mark(name, _logo(biz, site)), name,
                          preview(last, name) or "Write to the church office",
                          when_short((last or {}).get("created_at"), zone) if last else "", church["unread"],
                          pin="From your church")
    open_chats = gate is None
    chat_rows = (chats or []) if open_chats else []
    by_group = {str(r.get("group_id") or "").lower(): r for r in chat_rows if r.get("kind") == "group"}

    def when(at: Optional[datetime]) -> str:
        return when_short(at.isoformat(), zone) if at else ""
    items: List[Tuple[Optional[datetime], str, str]] = []
    for g in groups:
        gid = str(g["id"]).lower()
        gname = str(g.get("name") or "Your group")
        chat = by_group.get(gid) or {}
        note = got.get(f"group:{gid}") or {}
        line, at = _group_line(g, chat, note, zone)
        href = (f"/my/groups/{gid}/chat" if open_chats and g.get("chat_on") is not False
                else f"/my/inbox/group/{gid}")
        unread = int(chat.get("unread") or 0) + int(note.get("unread") or 0)
        items.append((at, gname, lp.inbox_row(href, lp.group_mark(gname), gname, line, when(at), unread)))
    for r in chat_rows:
        at = _at(r.get("at"), zone) if r.get("at") else None
        if r.get("kind") == "leaders":
            items.append((at, r["title"], lp.inbox_row("/my/groups/leaders", lp.group_mark(r["title"]), r["title"],
                                                       str(r.get("preview") or ""), when(at), int(r.get("unread") or 0))))
        elif r.get("kind") == "direct":
            items.append((at, r["title"], lp.inbox_row(f"/my/messages/{r['id']}", lp.face(r.get("photo") or "", r["title"]),
                                                       r["title"], str(r.get("preview") or ""), when(at),
                                                       int(r.get("unread") or 0))))
    asked = (requests or []) if open_chats else []
    return lumen_inbox_page(biz, site, request, me, rows=[pinned] + _newest_first(items), requests=asked,
                            gate=gate, start=start if open_chats else None, family=family if open_chats else None)


def lumen_inbox_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], *, rows: List[str],
                     requests: List[Dict[str, Any]], gate: Optional[str] = None,
                     start: Optional[List[Dict[str, Any]]] = None,
                     family: Optional[List[Dict[str, Any]]] = None, empty: str = "") -> str:
    """The inbox page in the new look, from its rows (member_lumen_people
    .inbox_row): the heading, chat requests, the rows (or `empty`), then
    Start a chat and Your teens. member_portal_messaging.render_inbox uses
    it too."""
    import member_lumen_people as lp
    import member_lumen_ui as lm
    import member_photos as ph
    import member_portal_church as mpc
    import member_portal_messaging as mpm
    from member_portal import _shell
    body = [mpc.connect_head(biz, "messages"), mpc._flash(request)]
    if gate and gate != "off":
        words = GATE_WORDS.get(gate, "Chats aren't open to you right now.")
        go = ('<a class="lm-btn sm" href="/my/messages?join=1">Read the guidelines</a>' if gate == "guidelines" else "")
        body.append(f'<div class="lm-req lm-gate"><p class="lm-reqt">{_e(words)}</p>{go}</div>')
    body.extend(lp.request_row(r["id"], lp.face(r.get("photo") or "", r["title"]), r["title"]) for r in requests)
    body.append(lp.inbox(rows) if rows else lp.note(empty))
    if start:
        body.append(lm.section("Start a chat") + '<div class="lm-list">' + "".join(
            lm.row(f"/my/messages/to/{p['id']}", lp.face("", p["name"]), mpm.first_and_initial(p["name"]), p["why"])
            for p in start) + '</div>')
    if family:
        body.append(lm.section("Your teens") + '<div class="lm-list">' + "".join(
            lm.row(f"/my/messages/family/{t['id']}", lp.face(ph.src(t), t["name"]), t["name"], "Read their chats")
            for t in family) + '</div>')
    return _shell(biz, site, "Messages", "".join(body), tab="messages", who=me)


def _active_groups(business_id: str, group_ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    if not group_ids:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{ct._q(business_id)}&id=in.({','.join(ct._q(g) for g in group_ids)})"
        "&select=id,name,chat_on,active")
    return None if not isinstance(rows, list) else [r for r in rows if r.get("active") is not False]


async def messages_page(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], *, gate: Optional[str] = None,
                        chats: Optional[List[Dict[str, Any]]] = None, requests: Optional[List[Dict[str, Any]]] = None,
                        start: Optional[List[Dict[str, Any]]] = None, family: Optional[List[Dict[str, Any]]] = None):
    """Messages while threads are open here (member_portal_messaging.serve
    calls it): (html, status)."""
    biz_id, me_id = str(biz["id"]), str(me["id"])
    gids = await asyncio.to_thread(my_group_ids, biz_id, me_id)
    if gids is None:
        return render_error(biz, site, me), 503
    got, groups, zone = await asyncio.gather(asyncio.to_thread(ct.summary, biz_id, me_id, gids),
                                             asyncio.to_thread(_active_groups, biz_id, gids),
                                             asyncio.to_thread(_zone, biz))
    if got is None or groups is None:
        return render_error(biz, site, me), 503
    return render_messages(biz, site, request, me, got=got, groups=groups, zone=zone, gate=gate, chats=chats,
                           requests=requests, start=start, family=family), 200


def here_open(biz: Dict[str, Any]) -> bool:
    """Threads are open for this church and this member is in Church (or
    is a teen): Messages brings in the church's conversation and the
    groups' notes."""
    import member_spaces as msp
    return _in_church(msp.CURRENT.get() or {}) and entry_open(biz)


# ─── A group's notes inside its chat (member_portal_groups) ──────────

CHAT_NOTES_MAX = 30
NOTE_KINDS = ((re.compile(rf"^/my/groups/{_GID}/board(/|$)"), "Board"),
              (re.compile(rf"^/my/groups/{_GID}/prayer(/|$)"), "Prayer wall"),
              (re.compile(rf"^/my/groups/{_GID}/meet(/|$)"), "Gathering"))


def chat_notes(biz: Dict[str, Any], me_id: str, group_id: str, msgs: Optional[List[Dict[str, Any]]],
               *, mark: bool = False) -> List[Dict[str, Any]]:
    """The group's notes for this member, to sit in its chat: the newest
    CHAT_NOTES_MAX and, when the chat shows a long run of messages, none
    older than its oldest. The page and the chat's poll count them the same
    way. `mark` marks them read. [] while threads are closed. Never raises."""
    try:
        if not entry_open(biz):
            return []
        biz_id, gid = str(biz["id"]), str(group_id).lower()
        rows = ct.group_notes(biz_id, str(me_id), gid, limit=CHAT_NOTES_MAX) or []
        msgs = msgs or []
        import member_portal_messaging as mpm
        if len(msgs) >= mpm.PAGE * 3 // 4:
            oldest = str(msgs[0].get("created_at") or "")
            rows = [r for r in rows if str(r.get("created_at") or "") >= oldest]
        if mark:
            ct.mark_read(biz_id, str(me_id), f"group:{gid}")
            forget(biz_id, me_id)
        return rows
    except Exception:
        logger.warning("church threads: a group's notes were left out of its chat", exc_info=True)
        return []


def note_card(r: Dict[str, Any], zone, group_name: str = "", *, lumen: bool = False) -> str:
    """One of the group's notes as a small card in its chat, at its time,
    with the button to what it's about. `lumen` (the new look) gives it its
    time for the chat's day lines (member_lumen_people.days_script)."""
    import member_app_ui as ui
    url = str(r.get("url") or "")
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    kind = next((w for p, w in NOTE_KINDS if p.match(path)), "From the group")
    t = str(r.get("title") or "")
    if group_name and t.casefold() == group_name.casefold() and r.get("body"):
        t = ""
    when = when_short(r.get("created_at"), zone)
    at = f'<span class="gc-nc-at">{_e(when)}</span>' if when else ""
    link = (f'<a class="gc-nc-go" href="{_e(url)}">{_e(link_word(url))}{ui.icon("chevron", 14)}</a>'
            if url.startswith("/my/") and not ct.is_inbox_url(url) else "")
    title = f'<strong>{_e(t)}</strong>' if t else ""
    body = f'<p>{_e(r.get("body") or "")}</p>' if r.get("body") else ""
    stamp = f' data-at="{_e(r.get("created_at"))}"' if lumen and r.get("created_at") else ""
    return (f'<li class="gc-nc" id="n-{_e(r.get("id"))}"{stamp}><div class="gc-nc-in"><span class="gc-nc-k"><span>{_e(kind)}</span>{at}</span>'
            f'{title}{body}{link}</div></li>')


NOTE_CSS = """
.gc-nc{list-style:none;display:flex;justify-content:center;}
.gc-nc-in{width:100%;max-width:420px;display:flex;flex-direction:column;gap:4px;padding:10px 14px 12px;border-radius:16px;
  background:var(--s1);box-shadow:inset 0 0 0 1px var(--line);}
.gc-nc-k{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--teal-ink,var(--acc));}
.gc-nc-at{font-weight:600;letter-spacing:0;text-transform:none;color:var(--fg3);font-variant-numeric:tabular-nums;}
.gc-nc-in strong{font-size:15px;font-weight:650;letter-spacing:-.01em;}
.gc-nc-in p{margin:0;font-size:15px;line-height:1.38;color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;}
.gc-nc-go{display:inline-flex;align-items:center;gap:4px;align-self:flex-start;margin-top:4px;padding:6px 12px;border-radius:14px;
  background:var(--s2);color:var(--acc);font-size:13.5px;font-weight:620;text-decoration:none;}
.gc-nc-go .mb-ic{width:14px;height:14px;}
"""


def notes_section(rows: List[Dict[str, Any]], zone, group_name: str) -> str:
    """The group's notes under a chat that isn't open to the member yet
    (the guidelines to agree, or chats not turned on for them)."""
    if not rows:
        return ""
    cards = "".join(note_card(r, zone, group_name) for r in rows)
    return (f'<style>{NOTE_CSS}</style><section aria-label="Group news" style="margin-top:16px">'
            f'<ul class="gc-list">{cards}</ul></section>')

def _bubble(r: Dict[str, Any], zone, said_by: str = "", av: str = "") -> str:
    """One message in the conversation. `av` (the new look) is the face
    the church's notes and the office's replies sit beside; a member's own
    message is drawn the same either way (instant send draws it too)."""
    import member_app_ui as ui
    d = _at(r.get("created_at"), zone)
    at = f'<span class="ct-at">{_e(_clock(d))}</span>' if d else ""
    body = _e(r.get("body") or "")
    if r.get("direction") == "member":
        held = ('<span class="mb-msg-held">Held for review. Only you can see it.</span>' if r.get("held") else "")
        return f'<li class="mb-msg mb-mine"><span class="mb-msg-body">{body}</span>{held}{at}</li>'
    if r.get("kind") == "reply":
        who = _e(r.get("author_name") or "The office")
        if av:
            return (f'<li class="mb-msg lm-them">{av}<div class="lm-note"><span class="lm-who">{who}</span>'
                    f'<span class="mb-msg-body">{body}</span>{at}</div></li>')
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
    if av:
        return f'<li class="mb-msg ct-note lm-them">{av}<div class="lm-note">{title}{text}{link}{at}</div></li>'
    return f'<li class="mb-msg ct-note">{title}{text}{link}{at}</li>'


def _bubbles(rows: List[Dict[str, Any]], zone, empty: str, said_by: str = "", av: str = "") -> str:
    out, day = [], None
    for r in rows:
        d = _at(r.get("created_at"), zone)
        if d is not None and d.date() != day:
            day = d.date()
            out.append(f'<li class="mb-msg ct-day" role="separator">{_e(day_label(d))}</li>')
        out.append(_bubble(r, zone, said_by, av))
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

# With instant send on (member_instant_send) the box is its script's: this
# only scrolls to the newest and grows the box as they write.
SCROLL_ONLY_JS = """<script>(function(){var b=document.getElementById('ct-chat');if(b){window.scrollTo(0,document.documentElement.scrollHeight);}
var t=document.getElementById('ct-say');if(!t)return;function fit(){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,160)+'px';}
t.addEventListener('input',fit);fit();
})();</script>"""


def church_script() -> str:
    """The church conversation's scripts: instant send while it's on, else
    the plain post that reloads (MEMBER_INSTANT_SEND=off)."""
    import member_instant_send as mis
    instant = mis.script("ct-compose", "ct-chat", "ct-say", "ct-err", "ct")
    return SCROLL_ONLY_JS + instant if instant else SCROLL_JS


def render_church(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                  rows: List[Dict[str, Any]], zone) -> str:
    import member_lumen
    if member_lumen.page():
        return _lumen_church(biz, site, request, me, rows, zone)
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
    return _shell(biz, site, name, body, tab="messages", who=me, bar=False, back=("/my/messages", "Messages"),
                  script=church_script())


def _lumen_church(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                  rows: List[Dict[str, Any]], zone) -> str:
    """The church's conversation in the new look (member_lumen_people): the
    church's mark and name in the bar ("The church office"), its notes and
    the office's replies as cards beside its mark, yours on the right, a
    line for each day, and the box at the foot. The form, list, box and
    error ids are instant send's (church_script)."""
    import member_lumen_people as lp
    from member_portal import _shell
    name = (biz.get("name") or "").strip() or "Your church"
    logo = _logo(biz, site)
    chat = _bubbles(rows, zone, f"Notes from {name} show up here. You can write to the church office below.", name,
                    av=lp.church_mark(name, logo))
    compose = (f'<form class="ct-compose lm-cmp" method="post" action="{CHURCH_PAGE}/send" id="ct-compose">'
               '<label class="mp-sr" for="ct-say">Message the church office</label>'
               f'<span class="lm-cbox"><span class="lm-cfield"><textarea id="ct-say" name="body" rows="1" '
               f'maxlength="{ct.BODY_MAX}" required placeholder="Message the church office"></textarea>'
               f'{lp.send_button()}</span></span>'
               '<p class="lm-cfine">Goes to the church office. It isn&#x27;t posted anywhere.</p></form>')
    body = (f'<div class="mb-thread">{_flash(request)}<ul class="mb-chat ct-chat" id="ct-chat" aria-label="Messages">'
            f'{chat}</ul>{compose}</div>')
    return _shell(biz, site, name, body, tab="messages", who=me, bar=False, back=("/my/messages", "Messages"),
                  script=church_script() + lp.BOTTOM_JS,
                  lumen_head=lp.thead(lp.church_mark(name, logo), name, "The church office"))


def _lumen_group_notes(biz: Dict[str, Any], site, me: Dict[str, Any], g: Dict[str, Any], rows: List[Dict[str, Any]],
                       zone, chat_open: bool) -> str:
    """A group's notes in the new look (while its chat isn't open to the
    member): the group's mark and name in the bar, its notes as cards
    beside the mark, and the door to its chat when it opens to them."""
    import member_lumen_people as lp
    from member_portal import _shell
    name = g.get("name") or "Your group"
    chat = _bubbles(rows, zone, "Your group's news shows up here: a leader's posts and prayer requests.", name,
                    av=lp.group_mark(name))
    link = (f'<div class="lm-cmp lm-cdoor"><a class="lm-btn" href="/my/groups/{_e(g["id"])}/chat">Open the group chat</a></div>'
            if chat_open else "")
    body = (f'<div class="mb-thread"><ul class="mb-chat ct-chat ct-group" id="ct-chat" aria-label="Notes">{chat}</ul>'
            f'{link}</div>')
    return _shell(biz, site, name, body, tab="messages", who=me, bar=False, back=("/my/messages", "Messages"),
                  script=SCROLL_JS, lumen_head=lp.thead(lp.group_mark(name), name, "Group news"))


def render_group(biz: Dict[str, Any], site, me: Dict[str, Any], g: Dict[str, Any], rows: List[Dict[str, Any]],
                 zone, chat_open: bool) -> str:
    import member_lumen
    if member_lumen.page():
        return _lumen_group_notes(biz, site, me, g, rows, zone, chat_open)
    import member_app_ui as ui
    from member_portal import _shell
    name = g.get("name") or "Your group"
    chat = _bubbles(rows, zone, "Your group's news shows up here: a leader's posts and prayer requests.", name)
    link = (f'<div class="ct-chatlink"><a class="mp-go" href="/my/groups/{_e(g["id"])}/chat">{ui.icon("chat", 17)}'
            'Open the group chat</a></div>' if chat_open else "")
    body = (f'<style>{THREAD_CSS}</style><div class="mb-thread"><div class="mb-lt"><h1 style="font-size:28px">{_e(name)}</h1></div>'
            f'<ul class="mb-chat ct-chat ct-group" id="ct-chat" aria-label="Notes">{chat}</ul>{link}</div>')
    return _shell(biz, site, name, body, tab="messages", who=me, bar=False, back=("/my/messages", "Messages"),
                  script=SCROLL_JS)


def render_missing(biz: Dict[str, Any], site, me: Dict[str, Any]) -> str:
    from member_portal import _shell
    body = ('<div class="mb-lt"><h1>Not here</h1></div>'
            '<p class="mp-muted">This conversation is for the people in that group. Yours are in '
            '<a href="/my/messages">Messages</a>.</p>')
    return _shell(biz, site, "Not here", body, tab="messages", who=me, back=("/my/messages", "Messages"))


def render_error(biz: Dict[str, Any], site, me: Dict[str, Any]) -> str:
    from member_portal import _shell
    body = ('<p class="mp-err" role="alert">Your messages couldn&#x27;t load just now. Please try again in a moment.</p>'
            '<p><a href="/my/messages">Try again</a></p>')
    return _shell(biz, site, "Messages", body, tab="messages", who=me, back=("/my", "Home"))


def _in_church(space_ctx: Dict[str, Any]) -> bool:
    """Kids, and an adult who switched into Youth, go back to /my."""
    space = space_ctx.get("space", "church")
    return not (space == "kids" or (space == "youth" and not space_ctx.get("youth")))


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str, *, preview: bool = False):
    """GET /my/inbox/* (member_portal.serve): the church's conversation and
    a group's notes; the old inbox goes to Messages. (html, status), or a
    redirect."""
    import member_spaces as msp
    from member_portal import _SECURE_HEADERS
    if sub == "/my/inbox":
        return RedirectResponse("/my/messages", status_code=302, headers=_SECURE_HEADERS)
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if not _in_church(msp.CURRENT.get() or {}):
        return home
    if not await asyncio.to_thread(entry_open, biz):
        return home
    biz_id, me_id = str(biz["id"]), str(me["id"])
    if sub == CHURCH_PAGE:
        rows, zone = await asyncio.gather(asyncio.to_thread(ct.church_notes, biz_id, me_id),
                                          asyncio.to_thread(_zone, biz))
        if rows is None:
            return render_error(biz, site, me), 503
        if not preview:
            await asyncio.to_thread(ct.mark_read, biz_id, me_id, ct.CHURCH)
            forget(biz_id, me_id)
        return render_church(biz, site, request, me, rows, zone), 200
    if sub.startswith("/my/inbox/group/"):
        import member_messaging_rules as rules
        import member_portal_groups as mpg
        import member_portal_messaging as mpm
        gid = sub[len("/my/inbox/group/"):].strip("/").lower()
        if not ct.UUID_RE.match(gid):
            return render_missing(biz, site, me), 404
        member, g = await asyncio.gather(asyncio.to_thread(mpg._is_member, biz_id, gid, me_id),
                                         asyncio.to_thread(mpg.group_row, biz_id, gid))
        if member is None or g is None:
            return render_error(biz, site, me), 503
        if not member or not g:
            return render_missing(biz, site, me), 404
        chat_on = mpm.turned_on(biz) and g.get("chat_on") is not False
        full = await asyncio.to_thread(mpm._me_profile, biz_id, me) if chat_on else None
        if chat_on and may_chat(full):
            # One conversation per group: its notes are inside its chat.
            return RedirectResponse(f"/my/groups/{gid}/chat", status_code=302, headers=_SECURE_HEADERS)
        rows, zone = await asyncio.gather(asyncio.to_thread(ct.group_notes, biz_id, me_id, gid),
                                          asyncio.to_thread(_zone, biz))
        if rows is None:
            return render_error(biz, site, me), 503
        if not preview:
            await asyncio.to_thread(ct.mark_read, biz_id, me_id, f"group:{gid}")
            forget(biz_id, me_id)
        # The chat's door, where it opens to them once they agree to the guidelines.
        link = bool(chat_on and full is not None and not rules.why_not(full))
        return render_group(biz, site, me, g, rows, zone, link), 200
    return RedirectResponse("/my/messages", status_code=302, headers=_SECURE_HEADERS)

# ─── Writing to the church office ─────────────────────────────────────


def recent_mine(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    """The member's messages from the last day, newest first."""
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/{ct.NOTES}?business_id=eq.{ct._q(business_id)}&contact_id=eq.{ct._q(contact_id)}&direction=eq.member"
        f"&created_at=gte.{ct._q(since)}&select=id,created_at,body,held&order=created_at.desc&limit={ct.DAY_MAX + 1}")
    return rows if isinstance(rows, list) else None


def too_soon(rows: List[Dict[str, Any]], now: Optional[datetime] = None) -> bool:
    if not rows:
        return False
    d = _at(rows[0].get("created_at"), timezone.utc)
    return d is not None and ((now or datetime.now(timezone.utc)) - d).total_seconds() < ct.GAP_SECONDS


async def send_message(biz: Dict[str, Any], me: Dict[str, Any], text: str, *,
                       saved: Optional[Dict[str, Any]] = None, retry: bool = False) -> Tuple[bool, str]:
    """The member's message to the church office. (ok, code): the code is
    the page's flash. `saved` gets the saved row ("row"). `retry` (the app
    lost the answer to this very message) answers with the same words saved
    in the last few minutes instead of saving them twice."""
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
    if retry:
        import member_instant_send as mis
        hit = mis.same_recent(mine, text)
        if hit is not None:
            return await _already_sent(biz_id, hit, text, saved)
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
    if saved is not None:
        saved["row"] = row[0]
    if held:
        ct.tell_reviewers(biz_id, str(row[0].get("id") or ""))
        return True, "held"
    ct.tell_office(biz_id, me_id, first)
    if verdict == "self_harm":
        import member_portal_messaging as mpm
        await asyncio.to_thread(mpm.care_alert, biz_id, me)
        return True, "care"
    return True, "ct_sent"


async def _already_sent(biz_id: str, row: Dict[str, Any], text: str, saved: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """A retry whose message was saved the first time: nothing is saved or
    told again. A row keeps "held" but not a crisis verdict, so the words
    are checked again to show the crisis resources the first answer would
    have shown (the crisis floor when the check can't run)."""
    import msg_screen
    if saved is not None:
        saved["row"] = row
    if row.get("held"):
        return True, "held"
    try:
        verdict = await msg_screen.screen(biz_id, text)
    except msg_screen.ScreenUnavailable:
        verdict = msg_screen.floor(text) or "ok"
    return True, "care" if verdict == "self_harm" else "ct_sent"


# A refused send's HTTP status, for the app's JSON answer.
REFUSED_STATUS = {"ct_day": 429, "ct_gap": 429, "slow": 429, "screen_off": 503, "error": 503, "preview": 403,
                  "signed_out": 401, "gone_chat": 404}


def sent_json(biz: Dict[str, Any], row: Dict[str, Any], code: str) -> Dict[str, Any]:
    """The app's answer to a saved message: the bubble as this page draws it,
    the day it falls on (and its divider), and the page's own held or crisis
    notice. A failure here never makes a saved message look unsent."""
    import member_instant_send as mis
    out: Dict[str, Any] = {"ok": True, "code": code, "id": str(row.get("id") or "")}
    if code == "care":
        out["care"] = True
    note = mis.notice(code)
    if note:
        out["notice"] = note
    try:
        zone = _zone(biz)
        out["html"] = _bubble(row, zone)
        d = _at(row.get("created_at"), zone)
        if d is not None:
            out["day"] = day_label(d)
            out["day_html"] = f'<li class="mb-msg ct-day" role="separator">{_e(out["day"])}</li>'
    except Exception:
        logger.exception("church conversation: the sent bubble didn't draw")
    return out


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target not in PAGES:
        target = "/my"
    q = {k: v for k, v in q.items() if v}
    return RedirectResponse(f"{target}?{urlencode(q)}" if q else target, status_code=303, headers=_SECURE_HEADERS)


@router.post("/my/inbox/church/send", include_in_schema=False)
async def send_route(request: Request):
    """The plain form gets a 303 back to the conversation, as always; the
    app's instant send (Accept: application/json) gets JSON, through the
    same checks in the same order."""
    import member_instant_send as mis
    import member_portal_church as mpc
    app = mis.wants_json(request)

    def no(code: str, target: str = CHURCH_PAGE):
        if app:
            return mis.refused(code, REFUSED_STATUS.get(code, 400), ERRORS)
        return _go(target, err=code) if target == CHURCH_PAGE else _go(target)

    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    if unavailable:
        return no("preview" if unavailable == "preview" else "error")
    if not me:
        return no("signed_out", "/my")
    biz = church["business"]
    if not await asyncio.to_thread(entry_open, biz):
        return no("gone_chat", "/my")
    if not mpc._allowed(church, me):
        return no("slow")
    saved: Dict[str, Any] = {}
    ok, code = await send_message(biz, me, ct.words(form.get("body")), saved=saved,
                                  retry=app and mis.is_retry(form))
    if not app:
        return _go(CHURCH_PAGE, **({"done": code} if ok else {"err": code}))
    if not ok:
        return no(code)
    return JSONResponse(await asyncio.to_thread(sent_json, biz, saved.get("row") or {}, code))
