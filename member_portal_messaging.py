"""
member_portal_messaging.py — group chats and direct messages in the member app.

Kevin's settled rules live in member_messaging_rules.py; this module only
reads the records those rules need and applies them on every action:

  /my/messages                     inbox: requests, then chats (newest first)
  /my/messages/<thread>            one chat: messages, send, report, block, mute
  /my/messages/feed/<thread>?v=    JSON for the chat poll
  /my/messages/to/<contact>        start (or reopen) a private chat
  /my/messages/group/<group>       open a group's chat
  /my/messages/family/<teen>       a linked parent's read-only view of their teen's chats
  POST /my/messages/<thread>/send · /accept · /decline · /mute · /block
  POST /my/messages/report · /my/messages/guidelines

Every message is screened (msg_screen.py) before anyone sees it: harmful
ones are HELD for the church's safety officers, crisis words deliver with
988 resources and a private note to the pastor. If the check can't run,
nothing is sent. Members see only what the rules allow; a teen is told
their linked parents can read their chats; everyone in a chat is told
when a safety officer reviewed it. Messaging is off until the church
turns it on (settings.messaging.enabled, which needs two safety officers).
The owner's preview reads but never writes. No notifications yet: members
see unread counts when they open the app.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import member_messaging_rules as rules
import sb_clients

router = APIRouter(tags=["member-portal"])

UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
BODY_MAX = 2000
PAGE = 80
POLL_MS = 6000
CRISIS_LINE = "988"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _in(ids: Iterable[str]) -> str:
    return ",".join(sorted({str(i) for i in ids if i}))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def settings(biz: Dict[str, Any]) -> Dict[str, Any]:
    s = ((biz or {}).get("settings") or {}).get("messaging") or {}
    return s if isinstance(s, dict) else {}


def turned_on(biz: Dict[str, Any]) -> bool:
    return bool(settings(biz).get("enabled"))


# ─── reads ───────────────────────────────────────────────────────────


def people(business_id: str, ids: Iterable[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """{contact_id: {id, name, birthdate, enabled, guidelines_at}} or None."""
    want = _in(ids)
    if not want:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    chunks = want.split(",")
    for i in range(0, len(chunks), 150):
        part = ",".join(chunks[i:i + 150])
        c = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({part})&select=id,name,birthdate")
        m = sb_clients.sb_get_as_service(
            f"/msg_members?business_id=eq.{_q(business_id)}&contact_id=in.({part})&select=contact_id,enabled,guidelines_at")
        if not isinstance(c, list) or not isinstance(m, list):
            return None
        mm = {str(r["contact_id"]): r for r in m}
        for r in c:
            extra = mm.get(str(r["id"]), {})
            out[str(r["id"])] = {"id": str(r["id"]), "name": r.get("name") or "", "birthdate": r.get("birthdate"),
                                 "enabled": bool(extra.get("enabled")), "guidelines_at": extra.get("guidelines_at")}
    return out


def guardians(business_id: str, ids: Iterable[str]) -> Optional[Dict[str, Set[str]]]:
    """{teen_id: {parent ids}} for links touching these people, or None."""
    want = _in(ids)
    if not want:
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/msg_guardians?business_id=eq.{_q(business_id)}"
        f"&or=(teen_contact_id.in.({want}),guardian_contact_id.in.({want}))&select=teen_contact_id,guardian_contact_id")
    if not isinstance(rows, list):
        return None
    out: Dict[str, Set[str]] = {}
    for r in rows:
        out.setdefault(str(r["teen_contact_id"]), set()).add(str(r["guardian_contact_id"]))
    return out


def blocks(business_id: str, a: str, b: str) -> Optional[Set[Tuple[str, str]]]:
    rows = sb_clients.sb_get_as_service(
        f"/msg_blocks?business_id=eq.{_q(business_id)}"
        f"&or=(and(blocker_contact_id.eq.{_q(a)},blocked_contact_id.eq.{_q(b)}),"
        f"and(blocker_contact_id.eq.{_q(b)},blocked_contact_id.eq.{_q(a)}))&select=blocker_contact_id,blocked_contact_id")
    if not isinstance(rows, list):
        return None
    return {(str(r["blocker_contact_id"]), str(r["blocked_contact_id"])) for r in rows}


def my_groups(business_id: str, me_id: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}&select=group_id,role")
    return rows if isinstance(rows, list) else None


def group_people(business_id: str, group_id: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&select=contact_id,role&limit=2000")
    return rows if isinstance(rows, list) else None


def share_group(business_id: str, a: str, b: str) -> Optional[bool]:
    ga, gb = my_groups(business_id, a), my_groups(business_id, b)
    if ga is None or gb is None:
        return None
    return bool({str(r["group_id"]) for r in ga} & {str(r["group_id"]) for r in gb})


def thread(business_id: str, tid: str):
    rows = sb_clients.sb_get_as_service(
        f"/msg_threads?id=eq.{_q(tid)}&business_id=eq.{_q(business_id)}&select=id,kind,group_id,direct_key,last_message_at&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else False


def participants(business_id: str, tid: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/msg_participants?thread_id=eq.{_q(tid)}&business_id=eq.{_q(business_id)}&select=contact_id,state,last_read_at,muted")
    return rows if isinstance(rows, list) else None


# ─── who is in a chat, and what may this person do there ─────────────


def chat_access(business_id: str, t: Dict[str, Any], me_id: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """{'role': 'member'|'parent'|None, 'can_send', 'why', 'people', 'me_state',
    'other' (direct), 'teen_in_chat', 'title'} — or None on a failed read."""
    me_id = str(me_id)
    if t["kind"] == "direct":
        parts = participants(business_id, t["id"])
        if parts is None:
            return None
        ids = [str(p["contact_id"]) for p in parts]
    else:
        gp = group_people(business_id, t["group_id"])
        if gp is None:
            return None
        ids = [str(r["contact_id"]) for r in gp]
        roles = {str(r["contact_id"]): r.get("role") for r in gp}
    folks = people(business_id, ids + [me_id])
    links = guardians(business_id, ids + [me_id])
    if folks is None or links is None:
        return None
    me = folks.get(me_id) or {"id": me_id, "enabled": False, "birthdate": None}
    out: Dict[str, Any] = {"role": None, "can_send": False, "why": "", "people": folks, "links": links,
                           "teen_in_chat": any(rules.is_teen(folks[i], today) for i in ids if i in folks),
                           "me_state": None, "other": None}
    if t["kind"] == "direct":
        state = {str(p["contact_id"]): p.get("state") for p in parts}
        if me_id in ids:
            out["role"] = "member"
            out["me_state"] = state.get(me_id)
            other_id = next((i for i in ids if i != me_id), None)
            other = folks.get(other_id) if other_id else None
            out["other"] = other
            if other is None:
                out["why"] = "recipient_off"
            elif state.get(me_id) == "declined":
                out["why"] = "declined"
            else:
                blk = blocks(business_id, me_id, other_id)
                shared = share_group(business_id, me_id, other_id)
                if blk is None or shared is None:
                    return None
                ok, how = rules.direct(me, other, guardians_of=links, blocked=blk, share_group=shared, today=today)
                out["can_send"], out["why"] = ok, ("" if ok else how)
        else:
            teens = [i for i in ids if i in folks and rules.may_read_as_parent(me_id, folks[i], links, today)]
            if teens:
                out["role"] = "parent"
    else:
        if me_id in ids:
            out["role"] = "member"
            members = [{**folks[i], "role": roles.get(i)} for i in ids if i in folks]
            open_, why = rules.group_chat(members, today)
            if not rules.can_message(me, today):
                out["why"] = rules.why_not(me, today)
            elif not open_:
                out["why"] = why
            else:
                out["can_send"] = True
        else:
            teens = [i for i in ids if i in folks and rules.may_read_as_parent(me_id, folks[i], links, today)]
            if teens:
                out["role"] = "parent"
    return out


def messages(business_id: str, tid: str, me_id: str, *, parent: bool = False) -> Optional[List[Dict[str, Any]]]:
    """The chat's messages, oldest first: delivered ones, plus the
    viewer's own held ones (shown as held). Never anyone else's held or
    removed message."""
    rows = sb_clients.sb_get_as_service(
        f"/msg_messages?thread_id=eq.{_q(tid)}&business_id=eq.{_q(business_id)}"
        f"&select=id,sender_contact_id,body,status,flag,created_at&order=created_at.desc&limit={PAGE}")
    if not isinstance(rows, list):
        return None
    keep = [m for m in rows if m["status"] == "delivered"
            or (m["status"] == "held" and not parent and str(m.get("sender_contact_id")) == str(me_id))]
    return list(reversed(keep))


def staff_looks(business_id: str, tid: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/msg_staff_views?thread_id=eq.{_q(tid)}&business_id=eq.{_q(business_id)}&select=created_at&order=created_at.desc&limit=5")
    return rows if isinstance(rows, list) else None


# ─── writes ──────────────────────────────────────────────────────────


def ensure_group_thread(business_id: str, group_id: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(
        f"/msg_threads?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&kind=eq.group&select=id&limit=1")
    if not isinstance(rows, list):
        return None
    if rows:
        return str(rows[0]["id"])
    made = sb_clients.sb_post_as_service("/msg_threads", {"business_id": business_id, "kind": "group", "group_id": group_id})
    if isinstance(made, list) and made:
        return str(made[0]["id"])
    again = sb_clients.sb_get_as_service(
        f"/msg_threads?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&kind=eq.group&select=id&limit=1")
    return str(again[0]["id"]) if isinstance(again, list) and again else None


def direct_key(a: str, b: str) -> str:
    return ":".join(sorted([str(a), str(b)]))


def open_direct(business_id: str, me_id: str, other_id: str, how: str) -> Optional[str]:
    """The pair's chat (made if new). A request leaves the other person
    'requested' until they accept."""
    key = direct_key(me_id, other_id)
    rows = sb_clients.sb_get_as_service(
        f"/msg_threads?business_id=eq.{_q(business_id)}&direct_key=eq.{_q(key)}&select=id&limit=1")
    if not isinstance(rows, list):
        return None
    if rows:
        return str(rows[0]["id"])
    made = sb_clients.sb_post_as_service("/msg_threads", {"business_id": business_id, "kind": "direct", "direct_key": key})
    if not (isinstance(made, list) and made):
        again = sb_clients.sb_get_as_service(
            f"/msg_threads?business_id=eq.{_q(business_id)}&direct_key=eq.{_q(key)}&select=id&limit=1")
        return str(again[0]["id"]) if isinstance(again, list) and again else None
    tid = str(made[0]["id"])
    ok = sb_clients.sb_post_as_service("/msg_participants", [
        {"thread_id": tid, "contact_id": me_id, "business_id": business_id, "state": "active"},
        {"thread_id": tid, "contact_id": other_id, "business_id": business_id,
         "state": "active" if how == "direct" else "requested"}])
    return tid if isinstance(ok, list) else None


def mark_read(business_id: str, tid: str, me_id: str) -> None:
    sb_clients.sb_post_as_service(
        "/msg_participants?on_conflict=thread_id,contact_id",
        {"thread_id": tid, "contact_id": me_id, "business_id": business_id, "last_read_at": now_iso()},
        prefer="return=minimal,resolution=merge-duplicates")


def care_alert(business_id: str, me: Dict[str, Any]) -> None:
    """Crisis words in a message: a private note to the pastor in Prayer &
    care (never in the chat). The message text itself is not copied."""
    sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": str(business_id), "form_id": None, "contact_id": str(me["id"]), "status": "new",
        "submission": {"name": (me.get("name") or "").strip(), "confidential": "yes",
                       "source": "Messaging (automatic)",
                       "prayer_request": "A message this person sent in the member app suggested they may be "
                                         "thinking about hurting themselves. They were shown crisis resources (988). "
                                         "Please reach out to them personally."}})


# ─── the pages ───────────────────────────────────────────────────────


def first_and_initial(name: Any) -> str:
    import live_router as lr
    return lr.author_for(name)


def _days(stamps) -> str:
    """'Oct 2, Oct 4' — the days safety officers looked."""
    out = []
    for st in stamps:
        try:
            d = datetime.fromisoformat(str(st).replace("Z", "+00:00")).date()
        except ValueError:
            continue
        label = f"{d.strftime('%b')} {d.day}"
        if label not in out:
            out.append(label)
    return ", ".join(out)


def _gate(biz, site, me, why: str) -> str:
    """Messaging isn't open to this person (yet)."""
    from member_portal import _shell
    text = {
        "off": "Messaging isn't turned on at this church yet.",
        "no_birthdate": "Messaging needs your birthdate on your record. Ask the church office to add it.",
        "not_enabled": "Ask the church office to turn on messaging for you.",
    }.get(why, "Messaging isn't available to you right now.")
    return _shell(biz, site, "Messages", f"""<h1>Messages</h1>
<div class="mp-card"><p class="mp-muted" style="margin:0">{text}</p></div>""", tab="me", who=me)


def render_guidelines(biz, site, me) -> str:
    from member_portal import _e, _shell
    teen = rules.is_teen(me)
    return _shell(biz, site, "Messages", f"""<h1>Before you start</h1>
<div class="mp-card mb-guide">
<p><strong>{_e(biz.get('name') or 'Our church')}'s messaging is for encouraging one another.</strong></p>
<ul class="mb-guide-list">
  <li>Be kind. No harassment, threats, or sexual content.</li>
  <li>Never ask anyone for money, photos, or to move to another app.</li>
  <li>Every message is checked before it's delivered. Harmful ones are held for the church's safety officers.</li>
  <li>You can report any message and block anyone. They aren't told who reported them.</li>
  <li>Staff don't read your messages, except a safety officer reviewing a reported or held one. If that happens, everyone in the chat is told.</li>
  {"<li><strong>Your linked parents can read all of your chats.</strong> You can message your parents and other teens privately; adults talk with you in group chats.</li>" if teen else ""}
  <li>Messages are kept for {int(settings(biz).get('retention_days') or 365) // 30} months, then deleted.</li>
  <li>If you or someone else is in danger, call 911. For a mental health crisis, call or text {CRISIS_LINE}.</li>
</ul>
<form method="post" action="/my/messages/guidelines"><button class="mp-go" type="submit">I agree</button></form>
</div>""", tab="me", who=me)


def render_inbox(biz, site, request, me, rows, requests, family, groups_open) -> str:
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    def row(r):
        badge = f'<span class="mb-unread" aria-label="{r["unread"]} unread">{r["unread"]}</span>' if r["unread"] else ""
        icon = ui.icon("users", 18) if r["kind"] == "group" else _e(ui.initials(r["title"]))
        return (f'<li><a href="/my/messages/{_e(r["id"])}"><span class="mb-thumb mb-chat-av">{icon}</span>'
                f'<span class="mb-list-text"><strong>{_e(r["title"])}</strong><span>{_e(r["preview"])}</span></span>{badge}</a></li>')
    req = "".join(row(r) for r in requests)
    body = [f"<h1>Messages</h1>{mpc._flash(request)}"]
    if req:
        body.append(f'<h2 class="mp-sect">Requests</h2><ul class="mb-list">{req}</ul>')
    body.append('<h2 class="mp-sect">Chats</h2>')
    body.append(f'<ul class="mb-list">{"".join(row(r) for r in rows)}</ul>' if rows else
                '<div class="mp-card"><p class="mp-muted" style="margin:0">No chats yet. Open one from a group, '
                'or start one with someone below.</p></div>')
    if groups_open:
        body.append('<h2 class="mp-sect">Start a chat</h2><ul class="mb-list">' + "".join(
            f'<li><a href="/my/messages/to/{_e(p["id"])}"><span class="mb-thumb mb-chat-av">{_e(ui.initials(p["name"]))}</span>'
            f'<span class="mb-list-text"><strong>{_e(first_and_initial(p["name"]))}</strong><span>{_e(p["why"])}</span></span>'
            f'{ui.icon("chevron", 16)}</a></li>' for p in groups_open) + '</ul>')
    if family:
        body.append('<h2 class="mp-sect">Your teens</h2><ul class="mb-list">' + "".join(
            f'<li><a href="/my/messages/family/{_e(t["id"])}"><span class="mb-thumb mb-chat-av">{_e(ui.initials(t["name"]))}</span>'
            f'<span class="mb-list-text"><strong>{_e(t["name"])}</strong><span>Read their chats</span></span>{ui.icon("chevron", 16)}</a></li>'
            for t in family) + '</ul>')
    return _shell(biz, site, "Messages", "".join(body), tab="me", who=me)


def _bubble(m: Dict[str, Any], me_id: str, names: Dict[str, str], *, reportable: bool) -> str:
    from member_portal import _e
    mine = str(m.get("sender_contact_id")) == str(me_id)
    who = "" if mine else f'<span class="mb-msg-who">{_e(names.get(str(m.get("sender_contact_id")), "Someone"))}</span>'
    held = '<span class="mb-msg-held">Held for review. Only you can see it.</span>' if m["status"] == "held" else ""
    report = (f'<form method="post" action="/my/messages/report" class="mb-report"><input type="hidden" name="message_id" '
              f'value="{_e(m["id"])}"><button type="submit" class="mb-report-btn">Report</button></form>'
              if reportable and not mine and m["status"] == "delivered" else "")
    return (f'<li class="mb-msg{" mb-mine" if mine else ""}" data-id="{_e(m["id"])}">{who}'
            f'<span class="mb-msg-body">{_e(m["body"])}</span>{held}{report}</li>')


def render_chat(biz, site, request, me, t, acc, msgs, looks, *, title: str, viewing_as: str = "") -> str:
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    folks = acc["people"]
    names = {i: first_and_initial(p.get("name")) for i, p in folks.items()}
    parent = acc["role"] == "parent"
    notices = []
    if parent:
        notices.append(f"You're reading {_e(viewing_as)}'s chat as their parent. You can't post here.")
    elif rules.is_teen(folks.get(str(me["id"]), {})):
        notices.append("Your linked parents can read this chat.")
    elif acc.get("teen_in_chat"):
        notices.append("A teen is in this chat; their linked parents can read it.")
    if looks:
        notices.append("A church safety officer reviewed this chat on " + _days(x["created_at"] for x in looks) + ".")
    note = "".join(f'<p class="mb-chat-note mp-muted">{n}</p>' for n in notices)
    body_msgs = "".join(_bubble(m, me["id"], names, reportable=not parent) for m in msgs) or \
        '<li class="mb-chat-empty mp-muted">No messages yet.</li>'
    actions = ""
    compose = ""
    if not parent:
        if acc.get("me_state") == "requested":
            actions = (f'<div class="mb-request"><p class="mp-muted">{_e(title)} wants to message you.</p>'
                       f'<form method="post" action="/my/messages/{_e(t["id"])}/accept"><button class="mp-go" type="submit">Accept</button></form>'
                       f'<form method="post" action="/my/messages/{_e(t["id"])}/decline"><button class="mp-go mp-go-2" type="submit">Ignore</button></form></div>')
        elif acc["can_send"]:
            compose = (f'<form class="mb-compose" method="post" action="/my/messages/{_e(t["id"])}/send" id="mb-compose">'
                       '<label class="mp-sr" for="mb-say">Message</label>'
                       f'<input class="mp-input" id="mb-say" name="body" maxlength="{BODY_MAX}" autocomplete="off" placeholder="Write a message…" required>'
                       f'<button class="mp-go" type="submit" aria-label="Send">{ui.icon("chevron", 18)}</button></form>'
                       '<p class="mb-chat-err mp-err" id="mb-chat-err" role="alert" hidden></p>')
        else:
            reason = {"two_adults": "This chat opens once two adult leaders of the group can message.",
                      "teen_adult": "Private messages between a teen and an adult who isn't their parent aren't allowed. Talk in your group chat instead.",
                      "recipient_off": "You can't message this person right now.",
                      "declined": "You ignored this request.",
                      "no_birthdate": "Messaging needs your birthdate on your record.",
                      "not_enabled": "Ask the church office to turn on messaging for you."}.get(acc["why"], "You can't post here right now.")
            compose = f'<p class="mb-chat-note mp-muted">{_e(reason)}</p>'
        if t["kind"] == "direct" and acc.get("other"):
            actions += (f'<div class="mb-chat-tools"><form method="post" action="/my/messages/{_e(t["id"])}/block">'
                        f'<button class="mp-link" type="submit">Block {_e(first_and_initial(acc["other"]["name"]))}</button></form></div>')
    script = _poll_script(t["id"], len(msgs)) if not parent else ""
    return _shell(biz, site, title, f"""<a class="mb-back" href="/my/messages">{ui.icon('back', 16)}Messages</a>
<h1 style="margin-top:6px">{_e(title)}</h1>{mpc._flash(request)}{note}
<ul class="mb-chat" id="mb-chat" aria-live="polite" aria-label="Messages">{body_msgs}</ul>
{actions}{compose}""", tab="me", who=me, script=script)


def _poll_script(tid: str, count: int) -> str:
    """Send without leaving the page; reload when something new arrives."""
    return f"""<script>(function(){{var box=document.getElementById('mb-chat'),f=document.getElementById('mb-compose'),
err=document.getElementById('mb-chat-err'),n={json.dumps(count)};if(box)box.scrollTop=box.scrollHeight;
function poll(){{fetch('/my/messages/feed/{tid}',{{credentials:'same-origin',headers:{{'Accept':'application/json'}}}})
.then(function(r){{return r.json();}}).then(function(d){{if(d&&typeof d.count==='number'&&d.count!==n)location.reload();}}).catch(function(){{}});}}
setInterval(poll,{POLL_MS});
if(f){{f.addEventListener('submit',function(e){{e.preventDefault();var i=f.querySelector('input'),t=i.value.trim();if(!t)return;
var b=f.querySelector('button');b.disabled=true;err.hidden=true;
fetch(f.getAttribute('action'),{{method:'POST',credentials:'same-origin',headers:{{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'}},body:'body='+encodeURIComponent(t)}})
.then(function(r){{return r.json().then(function(d){{return {{ok:r.ok,d:d}};}});}}).then(function(x){{b.disabled=false;
if(x.ok){{i.value='';if(x.d.care){{location.href=location.pathname+'?done=care';return;}}location.reload();}}else{{err.textContent=x.d.error||'That didn\\'t send. Please try again.';err.hidden=false;}}}})
.catch(function(){{b.disabled=false;err.textContent='That didn\\'t send. Please try again.';err.hidden=false;}});}});}}
}})();</script>"""


# ─── page handlers (GET, through member_portal.serve) ────────────────


def _me_profile(business_id: str, me: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    folks = people(business_id, [me["id"]])
    if folks is None:
        return None
    return {**me, **folks.get(str(me["id"]), {"enabled": False, "birthdate": None, "guidelines_at": None})}


def inbox_rows(business_id: str, me_id: str) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """(chats, requests) for the inbox, newest first, with unread counts."""
    mine = sb_clients.sb_get_as_service(
        f"/msg_participants?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}&select=thread_id,state,last_read_at")
    groups = my_groups(business_id, me_id)
    if not isinstance(mine, list) or groups is None:
        return None
    gids = [str(g["group_id"]) for g in groups]
    gthreads = []
    if gids:
        gthreads = sb_clients.sb_get_as_service(
            f"/msg_threads?business_id=eq.{_q(business_id)}&kind=eq.group&group_id=in.({_in(gids)})&select=id,group_id,last_message_at")
        if not isinstance(gthreads, list):
            return None
    tids = {str(p["thread_id"]) for p in mine if p.get("state") != "declined"} | {str(t["id"]) for t in gthreads}
    if not tids:
        return [], []
    threads = sb_clients.sb_get_as_service(
        f"/msg_threads?business_id=eq.{_q(business_id)}&id=in.({_in(tids)})&select=id,kind,group_id,last_message_at")
    others = sb_clients.sb_get_as_service(
        f"/msg_participants?business_id=eq.{_q(business_id)}&thread_id=in.({_in(tids)})&contact_id=neq.{_q(me_id)}&select=thread_id,contact_id")
    gnames = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{_q(business_id)}&id=in.({_in(gids) or '00000000-0000-0000-0000-000000000000'})&select=id,name")
    if not isinstance(threads, list) or not isinstance(others, list) or not isinstance(gnames, list):
        return None
    folks = people(business_id, [o["contact_id"] for o in others])
    if folks is None:
        return None
    read = {str(p["thread_id"]): p for p in mine}
    other_of = {str(o["thread_id"]): str(o["contact_id"]) for o in others}
    gname = {str(g["id"]): g.get("name") or "Group" for g in gnames}
    chats, requests = [], []
    for t in sorted(threads, key=lambda x: str(x.get("last_message_at") or ""), reverse=True):
        tid = str(t["id"])
        last_read = (read.get(tid) or {}).get("last_read_at")
        q = (f"/msg_messages?thread_id=eq.{_q(tid)}&business_id=eq.{_q(business_id)}&status=eq.delivered"
             f"&select=body,sender_contact_id,created_at&order=created_at.desc&limit=30")
        recent = sb_clients.sb_get_as_service(q)
        if not isinstance(recent, list):
            return None
        unread = sum(1 for m in recent if str(m.get("sender_contact_id")) != str(me_id)
                     and (not last_read or str(m["created_at"]) > str(last_read)))
        preview = (recent[0]["body"][:80] if recent else "No messages yet")
        if t["kind"] == "group":
            title = gname.get(str(t["group_id"]), "Group")
        else:
            title = first_and_initial((folks.get(other_of.get(tid, "")) or {}).get("name"))
        row = {"id": tid, "kind": t["kind"], "title": title, "preview": preview, "unread": unread}
        (requests if (read.get(tid) or {}).get("state") == "requested" else chats).append(row)
    return chats, requests


def startable(business_id: str, me: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """People this member can message directly: group-mates (by the rules)
    and their own family links. There is no member directory."""
    groups = my_groups(business_id, me["id"])
    if groups is None:
        return None
    gids = [str(g["group_id"]) for g in groups]
    mates: Dict[str, str] = {}
    if gids:
        rows = sb_clients.sb_get_as_service(
            f"/group_members?business_id=eq.{_q(business_id)}&group_id=in.({_in(gids)})&select=contact_id,group_id&limit=5000")
        names = sb_clients.sb_get_as_service(f"/groups?business_id=eq.{_q(business_id)}&id=in.({_in(gids)})&select=id,name")
        if not isinstance(rows, list) or not isinstance(names, list):
            return None
        gn = {str(g["id"]): g.get("name") or "" for g in names}
        for r in rows:
            if str(r["contact_id"]) != str(me["id"]):
                mates.setdefault(str(r["contact_id"]), f"In {gn.get(str(r['group_id']), 'your group')}")
    links = guardians(business_id, [me["id"]])
    if links is None:
        return None
    family = {t for t, ps in links.items() if str(me["id"]) in ps} | links.get(str(me["id"]), set())
    for f in family:
        mates.setdefault(f, "Family")
    folks = people(business_id, list(mates) + [me["id"]])
    allp = guardians(business_id, list(mates) + [me["id"]])
    if folks is None or allp is None:
        return None
    me_full = folks.get(str(me["id"]), me)
    out = []
    for pid, why in mates.items():
        other = folks.get(pid)
        if not other:
            continue
        ok, how = rules.direct(me_full, other, guardians_of=allp, blocked=set(), share_group=True)
        if ok:
            out.append({"id": pid, "name": other["name"], "why": why})
    return sorted(out, key=lambda p: p["name"].lower())[:60]


async def serve(request: Request, biz, site, me, sub: str):
    """GET /my/messages* — returns (html, status) or a RedirectResponse."""
    import asyncio
    from fastapi.responses import RedirectResponse
    from member_portal import _SECURE_HEADERS
    if not turned_on(biz):
        return _gate(biz, site, me, "off"), 200
    full = await asyncio.to_thread(_me_profile, biz["id"], me)
    if full is None:
        return _gate(biz, site, me, "error"), 503
    rest = sub[len("/my/messages"):].strip("/")
    # A linked parent's read-only view works even if the parent hasn't
    # turned messaging on for themselves.
    if rest.startswith("family/"):
        teen_id = rest[len("family/"):]
        if not UUID.match(teen_id):
            return RedirectResponse("/my/messages", status_code=303, headers=_SECURE_HEADERS)
        return await asyncio.to_thread(_family_page, request, biz, site, full, teen_id)
    why = rules.why_not(full)
    if why:
        return _gate(biz, site, me, why), 200
    if not full.get("guidelines_at"):
        return render_guidelines(biz, site, full), 200
    if not rest:
        rows, start, family = await asyncio.gather(
            asyncio.to_thread(inbox_rows, biz["id"], str(me["id"])),
            asyncio.to_thread(startable, biz["id"], full),
            asyncio.to_thread(_my_teens, biz["id"], str(me["id"])))
        if rows is None or start is None or family is None:
            return _gate(biz, site, me, "error"), 503
        chats, requests = rows
        return render_inbox(biz, site, request, full, chats, requests, family, start), 200
    if rest.startswith("to/") or rest.startswith("group/"):
        kind, _, target = rest.partition("/")
        if not UUID.match(target):
            return RedirectResponse("/my/messages", status_code=303, headers=_SECURE_HEADERS)
        tid = await asyncio.to_thread(_open_target, biz["id"], full, kind, target)
        if tid is None:
            return RedirectResponse("/my/messages?err=error", status_code=303, headers=_SECURE_HEADERS)
        if isinstance(tid, str) and tid.startswith("err:"):
            return RedirectResponse(f"/my/messages?err={tid[4:]}", status_code=303, headers=_SECURE_HEADERS)
        return RedirectResponse(f"/my/messages/{tid}", status_code=303, headers=_SECURE_HEADERS)
    if rest.startswith("feed/"):
        tid = rest[len("feed/"):]
        data = await asyncio.to_thread(_feed, biz["id"], str(me["id"]), tid)
        return JSONResponse(data, status_code=200 if "count" in data else 404, headers=_SECURE_HEADERS)
    if not UUID.match(rest):
        return RedirectResponse("/my/messages", status_code=303, headers=_SECURE_HEADERS)
    return await asyncio.to_thread(_chat_page, request, biz, site, full, rest)


def _my_teens(business_id: str, me_id: str) -> Optional[List[Dict[str, Any]]]:
    links = guardians(business_id, [me_id])
    if links is None:
        return None
    teens = [t for t, ps in links.items() if me_id in ps]
    folks = people(business_id, teens)
    if folks is None:
        return None
    return [{"id": t, "name": folks[t]["name"]} for t in teens if t in folks and rules.is_teen(folks[t])]


def _open_target(business_id: str, me: Dict[str, Any], kind: str, target: str):
    """A chat id, 'err:<code>', or None on a failed read."""
    if kind == "group":
        groups = my_groups(business_id, me["id"])
        if groups is None:
            return None
        if target not in {str(g["group_id"]) for g in groups}:
            return "err:group_gone"
        return ensure_group_thread(business_id, target)
    folks = people(business_id, [target, me["id"]])
    links = guardians(business_id, [target, me["id"]])
    blk = blocks(business_id, str(me["id"]), target)
    shared = share_group(business_id, str(me["id"]), target)
    if folks is None or links is None or blk is None or shared is None:
        return None
    other = folks.get(target)
    if not other:
        return "err:recipient_off"
    ok, how = rules.direct(folks.get(str(me["id"]), me), other, guardians_of=links, blocked=blk, share_group=shared)
    if not ok:
        return f"err:{how if how in ('teen_adult',) else 'recipient_off'}"
    return open_direct(business_id, str(me["id"]), target, how)


def _title(business_id: str, t: Dict[str, Any], acc: Dict[str, Any], me_id: str) -> str:
    if t["kind"] == "group":
        g = sb_clients.sb_get_as_service(f"/groups?id=eq.{_q(t['group_id'])}&business_id=eq.{_q(business_id)}&select=name&limit=1")
        return (g[0].get("name") if isinstance(g, list) and g else "") or "Group chat"
    ids = [i for i in acc["people"] if i != str(me_id)]
    return first_and_initial(acc["people"][ids[0]]["name"]) if ids else "Chat"


def _chat_page(request, biz, site, me, tid: str, *, as_parent_of: str = ""):
    t = thread(biz["id"], tid)
    if t is None:
        return _gate(biz, site, me, "error"), 503
    if not t:
        return _gate(biz, site, me, "gone"), 404
    acc = chat_access(biz["id"], t, str(me["id"]))
    if acc is None:
        return _gate(biz, site, me, "error"), 503
    if not acc["role"]:
        return _gate(biz, site, me, "gone"), 404
    parent = acc["role"] == "parent"
    msgs = messages(biz["id"], tid, str(me["id"]), parent=parent)
    looks = staff_looks(biz["id"], tid)
    if msgs is None or looks is None:
        return _gate(biz, site, me, "error"), 503
    if not parent:
        mark_read(biz["id"], tid, str(me["id"]))
    teen_name = ""
    title = _title(biz["id"], t, acc, str(me["id"]))
    if parent:
        teen_name = next((p["name"] for i, p in acc["people"].items()
                          if rules.may_read_as_parent(str(me["id"]), p, acc["links"])), "your teen")
        if t["kind"] == "direct":
            # "Maya & Ava C." — whose chat it is, then who it's with.
            others = [p for i, p in acc["people"].items()
                      if not rules.may_read_as_parent(str(me["id"]), p, acc["links"])]
            if others:
                title = f"{str(teen_name).split(' ')[0]} & {first_and_initial(others[0].get('name'))}"
    return render_chat(biz, site, request, me, t, acc, msgs, looks, title=title, viewing_as=teen_name), 200


def _family_page(request, biz, site, me, teen_id: str):
    import member_app_ui as ui
    from member_portal import _e, _shell
    folks = people(biz["id"], [teen_id])
    links = guardians(biz["id"], [teen_id])
    if folks is None or links is None:
        return _gate(biz, site, me, "error"), 503
    teen = folks.get(teen_id)
    if not teen or not rules.may_read_as_parent(str(me["id"]), teen, links):
        return _gate(biz, site, me, "gone"), 404
    rows = inbox_rows(biz["id"], teen_id)
    if rows is None:
        return _gate(biz, site, me, "error"), 503
    chats = rows[0] + rows[1]
    items = "".join(
        f'<li><a href="/my/messages/{_e(r["id"])}"><span class="mb-thumb mb-chat-av">{ui.icon("users", 18) if r["kind"] == "group" else _e(ui.initials(r["title"]))}</span>'
        f'<span class="mb-list-text"><strong>{_e(r["title"])}</strong><span>{_e(r["preview"])}</span></span>{ui.icon("chevron", 16)}</a></li>'
        for r in chats) or '<li class="mp-muted" style="padding:12px 0">No chats yet.</li>'
    return _shell(biz, site, "Messages", f"""<a class="mb-back" href="/my/messages">{ui.icon('back', 16)}Messages</a>
<h1>{_e(teen['name'])}'s chats</h1>
<p class="mp-muted">As their linked parent you can read all of {_e(teen['name'].split(' ')[0])}'s chats. They're told you can.</p>
<ul class="mb-list">{items}</ul>""", tab="me", who=me), 200


def _feed(business_id: str, me_id: str, tid: str) -> Dict[str, Any]:
    if not UUID.match(tid):
        return {"error": "gone"}
    t = thread(business_id, tid)
    if not t:
        return {"error": "gone"}
    acc = chat_access(business_id, t, me_id)
    if not acc or not acc["role"]:
        return {"error": "gone"}
    msgs = messages(business_id, tid, me_id, parent=acc["role"] == "parent")
    return {"count": len(msgs or [])}


# ─── POST ─────────────────────────────────────────────────────────────


def _wants_json(request: Request) -> bool:
    return "application/json" in (request.headers.get("accept") or "")


def _answer(request: Request, ok: bool, code: str, back: str, status: int = 400, **extra):
    import member_portal_church as mpc
    if _wants_json(request):
        if ok:
            return JSONResponse({"ok": True, **extra})
        return JSONResponse({"ok": False, "error": mpc.ERRORS.get(code, "That didn't send. Please try again.")},
                            status_code=status)
    return mpc._back(back, **({"done": code} if ok else {"err": code}))


async def _who(request: Request):
    """(church, me with profile, error_code, status)."""
    import asyncio
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable == "preview":
        return church, None, "preview", 403
    if unavailable:
        return church, None, "error", 503
    if not me:
        return church, None, "signed_out", 401
    if not turned_on(church["business"]):
        return church, None, "msg_off", 409
    full = await asyncio.to_thread(_me_profile, church["business"]["id"], me)
    if full is None:
        return church, None, "error", 503
    return church, full, "", 200


@router.post("/my/messages/{tid}/send", include_in_schema=False)
async def send(tid: str, request: Request):
    import asyncio
    import msg_screen
    import rate_limit
    back = f"/my/messages/{tid}" if UUID.match(tid) else "/my/messages"
    church, me, err, status = await _who(request)
    if err:
        return _answer(request, False, err, back, status)
    biz = church["business"]
    if rules.why_not(me) or not me.get("guidelines_at"):
        return _answer(request, False, "not_enabled", back, 403)
    form = await request.form()
    text = str(form.get("body") or "").strip()[:BODY_MAX]
    if not text:
        return _answer(request, False, "empty_chat", back)
    if not UUID.match(tid):
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    t = await asyncio.to_thread(thread, biz["id"], tid)
    if t is None:
        return _answer(request, False, "error", back, 503)
    if not t:
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    acc = await asyncio.to_thread(chat_access, biz["id"], t, str(me["id"]))
    if acc is None:
        return _answer(request, False, "error", back, 503)
    if acc["role"] != "member" or not acc["can_send"] or acc.get("me_state") == "declined":
        return _answer(request, False, acc.get("why") or "cant_send", back, 403)
    if not rate_limit.allow_strict("live_chat", f"msg|{biz['id']}|{me['id']}"):
        return _answer(request, False, "slow_chat", back, 429)
    try:
        verdict = await msg_screen.screen(biz["id"], text)
    except msg_screen.ScreenUnavailable:
        return _answer(request, False, "screen_off", back, 503)
    status_ = "held" if verdict == "harm" else "delivered"
    row = await asyncio.to_thread(sb_clients.sb_post_as_service, "/msg_messages", {
        "business_id": biz["id"], "thread_id": tid, "sender_contact_id": str(me["id"]), "body": text,
        "status": status_, "flag": None if verdict == "ok" else verdict})
    if not isinstance(row, list) or not row:
        return _answer(request, False, "error", back, 503)
    if acc.get("me_state") == "requested":
        # Replying accepts the request.
        await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                f"/msg_participants?thread_id=eq.{_q(tid)}&contact_id=eq.{_q(me['id'])}&business_id=eq.{_q(biz['id'])}",
                                {"state": "active"})
    if verdict == "self_harm":
        await asyncio.to_thread(care_alert, biz["id"], me)
        return _answer(request, True, "care", back, care=True)
    return _answer(request, True, "held" if verdict == "harm" else "sent", back)


async def _set_state(request: Request, tid: str, state: str):
    import asyncio
    back = f"/my/messages/{tid}" if UUID.match(tid) else "/my/messages"
    church, me, err, status = await _who(request)
    if err:
        return _answer(request, False, err, back, status)
    if not UUID.match(tid):
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    biz = church["business"]
    saved = await asyncio.to_thread(
        sb_clients.sb_patch_as_service,
        f"/msg_participants?thread_id=eq.{_q(tid)}&contact_id=eq.{_q(me['id'])}&business_id=eq.{_q(biz['id'])}&state=eq.requested",
        {"state": state})
    if not isinstance(saved, list):
        return _answer(request, False, "error", back, 503)
    return _answer(request, True, "accepted" if state == "active" else "ignored",
                   back if state == "active" else "/my/messages")


@router.post("/my/messages/{tid}/accept", include_in_schema=False)
async def accept(tid: str, request: Request):
    return await _set_state(request, tid, "active")


@router.post("/my/messages/{tid}/decline", include_in_schema=False)
async def decline(tid: str, request: Request):
    return await _set_state(request, tid, "declined")


@router.post("/my/messages/{tid}/block", include_in_schema=False)
async def block(tid: str, request: Request):
    import asyncio
    church, me, err, status = await _who(request)
    if err:
        return _answer(request, False, err, "/my/messages", status)
    biz = church["business"]
    t = await asyncio.to_thread(thread, biz["id"], tid) if UUID.match(tid) else False
    if t is None:
        return _answer(request, False, "error", "/my/messages", 503)
    if not t or t["kind"] != "direct":
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    parts = await asyncio.to_thread(participants, biz["id"], tid)
    if parts is None:
        return _answer(request, False, "error", "/my/messages", 503)
    ids = [str(p["contact_id"]) for p in parts]
    if str(me["id"]) not in ids:
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    other = next((i for i in ids if i != str(me["id"])), None)
    if other:
        saved = await asyncio.to_thread(
            sb_clients.sb_post_as_service, "/msg_blocks?on_conflict=blocker_contact_id,blocked_contact_id",
            {"blocker_contact_id": str(me["id"]), "blocked_contact_id": other, "business_id": biz["id"]},
            prefer="return=representation,resolution=ignore-duplicates")
        if saved is None:
            return _answer(request, False, "error", "/my/messages", 503)
    return _answer(request, True, "blocked", "/my/messages")


@router.post("/my/messages/report", include_in_schema=False)
async def report(request: Request):
    import asyncio
    church, me, err, status = await _who(request)
    form = await request.form()
    mid = str(form.get("message_id") or "")
    if err:
        return _answer(request, False, err, "/my/messages", status)
    biz = church["business"]
    if not UUID.match(mid):
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
                                   f"/msg_messages?id=eq.{_q(mid)}&business_id=eq.{_q(biz['id'])}&select=id,thread_id,sender_contact_id&limit=1")
    if not isinstance(rows, list):
        return _answer(request, False, "error", "/my/messages", 503)
    if not rows:
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    m = rows[0]
    back = f"/my/messages/{m['thread_id']}"
    t = await asyncio.to_thread(thread, biz["id"], str(m["thread_id"]))
    acc = await asyncio.to_thread(chat_access, biz["id"], t, str(me["id"])) if t else None
    if not acc or acc["role"] != "member":
        return _answer(request, False, "gone_chat", "/my/messages", 404)
    saved = await asyncio.to_thread(sb_clients.sb_post_as_service, "/msg_reports", {
        "business_id": biz["id"], "message_id": mid, "reporter_contact_id": str(me["id"]),
        "reason": str(form.get("reason") or "")[:500]})
    if not isinstance(saved, list) or not saved:
        return _answer(request, False, "error", back, 503)
    return _answer(request, True, "reported", back)


@router.post("/my/messages/guidelines", include_in_schema=False)
async def guidelines(request: Request):
    import asyncio
    church, me, err, status = await _who(request)
    if err:
        return _answer(request, False, err, "/my/messages", status)
    if rules.why_not(me):
        return _answer(request, False, "not_enabled", "/my/messages", 403)
    biz = church["business"]
    saved = await asyncio.to_thread(sb_clients.sb_patch_as_service,
                                    f"/msg_members?contact_id=eq.{_q(me['id'])}&business_id=eq.{_q(biz['id'])}",
                                    {"guidelines_at": now_iso(), "updated_at": now_iso()})
    if not isinstance(saved, list) or not saved:
        return _answer(request, False, "error", "/my/messages", 503)
    return _answer(request, True, "welcome_msgs", "/my/messages")


# ─── keeping messages a year ─────────────────────────────────────────


def retention_tick() -> int:
    """Delete messages older than each church's keep-for days (default a
    year), except held ones and those under an open report. Returns the
    number of churches swept."""
    rows = sb_clients.sb_get_as_service("/businesses?settings->messaging->>enabled=eq.true&select=id,settings&limit=1000")
    if not isinstance(rows, list):
        return 0
    for b in rows:
        days = int(settings(b).get("retention_days") or 365)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(30, days))).isoformat()
        open_ = sb_clients.sb_get_as_service(
            f"/msg_reports?business_id=eq.{_q(b['id'])}&status=eq.open&select=message_id&limit=5000")
        if not isinstance(open_, list):
            continue
        keep = _in(r["message_id"] for r in open_)
        keep_q = f"&id=not.in.({keep})" if keep else ""
        sb_clients.sb_delete_as_service(
            f"/msg_messages?business_id=eq.{_q(b['id'])}&created_at=lt.{_q(cutoff)}&status=neq.held{keep_q}")
    return len(rows)
