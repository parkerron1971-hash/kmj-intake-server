"""
group_chat_notify.py — how each person hears about a group's chat.

From the approved canvas "Church Groups, Together" (board Notify: "Group
chat: Every message · Evening summary · Off"). Per person, per chat (a
group's chat, or the All group leaders room), kept on msg_participants:

  every     a note for each message (what was live before; the default)
  evening   one quiet note at 7 PM on the church's clock: how many new
            messages and who wrote them (first names), and how many replied
            to you. Only what's new since you last read the chat or the last
            evening note, and only when there is something
  replies   only when someone replies to one of your messages

An after-hours alert still rings for anyone who lets them ring, whatever
they chose here: it's the one note that can't wait. Direct messages are
always "every". Notes never say what a message says.

The control sits under the chat's composer (member_portal_groups) and in
Notifications (member_push); the 7 PM sweep runs in member_push.sweep_tick.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

LEVELS = ("every", "evening", "replies")
LABELS = {"every": "Every message", "evening": "Evening summary", "replies": "Off"}
HINTS = {"every": "A note for each message.",
         "evening": "One quiet note at 7 PM: who talked, and any replies to you.",
         "replies": "Only when someone replies to you."}
EVENING_AT = 19                 # 7 PM
LOOK_BACK = timedelta(hours=24)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def level_of(part: Optional[Dict[str, Any]]) -> str:
    lv = str((part or {}).get("notify") or "every")
    return lv if lv in LEVELS else "every"


def hears_each(t: Dict[str, Any], part: Optional[Dict[str, Any]], ring: bool = False) -> bool:
    """Does this person get a note for every message in `t`?"""
    return t.get("kind") == "direct" or ring or level_of(part) == "every"


# ─── the member's choice ─────────────────────────────────────────────


def mine(business_id: str, tid: str, me_id: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(
        f"/msg_participants?thread_id=eq.{_q(tid)}&business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}"
        f"&select=notify&limit=1")
    if not isinstance(rows, list):
        return None
    return level_of(rows[0] if rows else None)


def choose(business: Dict[str, Any], me: Dict[str, Any], tid: str, level: str) -> Tuple[bool, str]:
    """Save this person's choice for a group chat or the leaders room they
    belong to."""
    import member_portal_messaging as mpm
    if level not in LEVELS:
        return False, "error"
    biz_id = str(business["id"])
    t = mpm.thread(biz_id, tid)
    if t is None:
        return False, "error"
    if not t or t.get("kind") not in ("group", "leaders"):
        return False, "gone_chat"
    acc = mpm.chat_access(biz_id, t, str(me["id"]))
    if acc is None:
        return False, "error"
    if acc.get("role") != "member":
        return False, "gone_chat"
    rows = sb_clients.sb_post_as_service(
        "/msg_participants?on_conflict=thread_id,contact_id",
        {"thread_id": str(tid), "contact_id": str(me["id"]), "business_id": biz_id, "notify": level},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(rows, list):
        return False, "error"
    # Saved only when it reads back that way.
    return (True, f"chat_{level}") if mine(biz_id, tid, str(me["id"])) == level else (False, "error")


def my_chats(business: Dict[str, Any], me_id: str) -> Optional[List[Dict[str, Any]]]:
    """The group chats (and the leaders room) this person is in, each with
    their choice: [{'tid', 'title', 'level'}], or None on a failed read.
    Only chats that have been opened (they have a thread)."""
    import member_portal_messaging as mpm
    biz_id = str(business["id"])
    if not mpm.turned_on(business):
        return []
    mine_ = mpm.my_groups(biz_id, me_id)
    if mine_ is None:
        return None
    gids = sorted({str(g["group_id"]) for g in mine_})
    out: List[Dict[str, Any]] = []
    if gids:
        gs = sb_clients.sb_get_as_service(
            f"/groups?business_id=eq.{_q(biz_id)}&id=in.({','.join(gids)})&active=eq.true&select=id,name,chat_on&limit=500")
        ts = sb_clients.sb_get_as_service(
            f"/msg_threads?business_id=eq.{_q(biz_id)}&kind=eq.group&group_id=in.({','.join(gids)})&select=id,group_id&limit=500")
        if not isinstance(gs, list) or not isinstance(ts, list):
            return None
        names = {str(g["id"]): g.get("name") or "Your group" for g in gs if g.get("chat_on") is not False}
        out += [{"tid": str(t["id"]), "title": names[str(t["group_id"])]} for t in ts if str(t.get("group_id")) in names]
    room = sb_clients.sb_get_as_service(f"/msg_threads?business_id=eq.{_q(biz_id)}&kind=eq.leaders&select=id&limit=1")
    if not isinstance(room, list):
        return None
    if room:
        folks = mpm.leaders_room_people(biz_id)
        if folks is None:
            return None
        if str(me_id) in {str(r["contact_id"]) for r in folks}:
            out.append({"tid": str(room[0]["id"]), "title": mpm.LEADERS_ROOM})
    if not out:
        return []
    parts = sb_clients.sb_get_as_service(
        f"/msg_participants?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(me_id)}"
        f"&thread_id=in.({','.join(c['tid'] for c in out)})&select=thread_id,notify")
    if not isinstance(parts, list):
        return None
    by = {str(p["thread_id"]): p for p in parts}
    for c in out:
        c["level"] = level_of(by.get(c["tid"]))
    return sorted(out, key=lambda c: (c["title"] == mpm.LEADERS_ROOM, c["title"].lower()))


def segments(tid: str, level: str, back: str, esc, label: str = "Notes about this chat") -> str:
    opts = "".join(
        f'<button type="submit" name="level" value="{lv}" aria-pressed="{"true" if lv == level else "false"}">{LABELS[lv]}</button>'
        for lv in LEVELS)
    return (f'<form class="gn-f" method="post" action="/my/groups/chat/notify"><input type="hidden" name="thread" value="{esc(tid)}">'
            f'<input type="hidden" name="back" value="{esc(back)}"><div class="gn-seg" role="group" aria-label="{esc(label)}">{opts}</div></form>')


def notifications_section(chats: Optional[List[Dict[str, Any]]], esc) -> str:
    """Notifications, under "New messages": each group chat's choice."""
    if not chats:
        return ""
    rows = "".join(
        f'<div class="gn-row"><b>{esc(c["title"])}</b>{segments(c["tid"], c["level"], "/my/notifications", esc, c["title"])}'
        f'<p class="gn-h">{HINTS[c["level"]]}</p></div>' for c in chats)
    return (f'<style>{CONTROL_CSS}</style><section class="mp-card" aria-labelledby="np-chats">'
            f'<h2 id="np-chats" class="mp-sect" style="margin-top:0">Group chats</h2>{rows}'
            f'<p class="mp-muted" style="margin:14px 0 0">An after-hours alert still rings if you let them. '
            f'Your leaders never see what you read in a chat, or when.</p></section>')


def control(tid: str, level: str, back: str, ic, esc) -> str:
    """Under a chat: how you hear about it."""
    return (f'<details class="gn"><summary class="gn-s">{ic("bell", 15)}<span>Notes: <b>{LABELS[level]}</b></span></summary>'
            f'{segments(tid, level, back, esc)}<p class="gn-h">{HINTS[level]} An after-hours alert still rings if you let them.</p></details>')


CONTROL_CSS = """
.gn{margin:10px 0 0;}
.gn-s{display:inline-flex;align-items:center;gap:8px;min-height:40px;list-style:none;cursor:pointer;font-size:13.5px;color:var(--fg2);}
.gn-s::-webkit-details-marker{display:none;}
.gn-s b{color:var(--fg);font-weight:620;}
.gn-f{margin:4px 0 0;}
.gn-seg{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;padding:4px;border-radius:999px;background:var(--s2);}
.gn-seg button{min-height:40px;border:0;border-radius:999px;background:none;color:var(--fg2);font:inherit;font-size:13.5px;font-weight:620;cursor:pointer;}
.gn-seg button[aria-pressed=true]{background:var(--s1);color:var(--fg);box-shadow:0 1px 2px rgba(0,0,0,.25);}
.gn-h{margin:8px 2px 0;font-size:12.5px;color:var(--fg3);line-height:1.4;}
.gn-row{display:flex;flex-direction:column;gap:8px;padding:12px 0;border-bottom:.5px solid var(--line);}
.gn-row b{font-size:15px;font-weight:650;}
.gn-row .gn-h{margin:0 2px;}
"""


# ─── a reply, for those who chose "Off" ──────────────────────────────


def reply_note(business: Dict[str, Any], t: Dict[str, Any], acc: Dict[str, Any], sender_id: str,
               replied_to: Optional[str], parts: Optional[List[Dict[str, Any]]], title: str, url: str) -> None:
    """The person whose message was answered, when they hear only replies.
    (Everyone on "every" already heard; "evening" counts it at 7 PM.)"""
    import member_push
    if not replied_to or t.get("kind") == "direct":
        return
    rows = sb_clients.sb_get_as_service(
        f"/msg_messages?id=eq.{_q(replied_to)}&thread_id=eq.{_q(t['id'])}&business_id=eq.{_q(business['id'])}"
        f"&select=sender_contact_id&limit=1")
    if not isinstance(rows, list) or not rows:
        return
    who = str(rows[0].get("sender_contact_id") or "")
    if not who or who == str(sender_id):
        return
    if who not in member_push.chat_recipients(t, acc, sender_id, parts, everyone=True):
        return
    part = next((p for p in (parts or []) if str(p.get("contact_id")) == who), None)
    if level_of(part) != "replies":
        return
    member_push.send(business, "messages", title=title.replace("New message", "New reply to you", 1),
                     body="Open the app to read it.", url=url, contact_ids=[who], tag=f"chat-{t['id']}")


# ─── the 7 PM note (member_push.sweep_tick) ──────────────────────────


def _names(names: List[str]) -> str:
    firsts = [n.split()[0] for n in names if n.strip()]
    if not firsts:
        return ""
    if len(firsts) == 1:
        return firsts[0]
    if len(firsts) == 2:
        return f"{firsts[0]} and {firsts[1]}"
    rest = len(firsts) - 2
    return f"{firsts[0]}, {firsts[1]} and {rest} other{'s' if rest != 1 else ''}"


def evening(business: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """At 7 PM on the church's clock: one note per person per chat for
    everyone who chose the evening summary, when there's something new."""
    import group_gatherings as gg
    import member_portal_messaging as mpm
    import member_push
    tz = gg.zone(business)
    if tz is None:
        return 0
    now = now or _now()
    local = now.astimezone(tz)
    if local.hour != EVENING_AT:
        return 0
    biz_id = str(business["id"])
    picked = sb_clients.sb_get_as_service(
        f"/msg_participants?business_id=eq.{_q(biz_id)}&notify=eq.evening"
        f"&select=thread_id,contact_id,state,muted,last_read_at,summed_at&limit=5000")
    if not isinstance(picked, list):
        return 0
    by_thread: Dict[str, List[Dict[str, Any]]] = {}
    for p in picked:
        by_thread.setdefault(str(p["thread_id"]), []).append(p)
    sent = 0
    floor = now - LOOK_BACK
    for tid, folks in by_thread.items():
        try:
            sent += _evening_thread(business, tid, folks, now, floor, local.date().isoformat(), mpm, member_push)
        except Exception:
            logger.warning("evening chat note failed for one chat", exc_info=True)
    return sent


def _since(p: Dict[str, Any], floor: datetime) -> datetime:
    marks = [floor]
    for k in ("last_read_at", "summed_at"):
        try:
            if p.get(k):
                marks.append(datetime.fromisoformat(str(p[k]).replace("Z", "+00:00")))
        except ValueError:
            pass
    return max(marks)


def _evening_thread(business, tid, folks, now, floor, day, mpm, member_push) -> int:
    biz_id = str(business["id"])
    t = mpm.thread(biz_id, tid)
    if not t or t.get("kind") not in ("group", "leaders"):
        return 0
    start = min(_since(p, floor) for p in folks)
    msgs = sb_clients.sb_get_as_service(
        f"/msg_messages?business_id=eq.{_q(biz_id)}&thread_id=eq.{_q(tid)}&status=eq.delivered"
        f"&created_at=gt.{_q(start.isoformat())}&select=id,sender_contact_id,reply_to,created_at&order=created_at.asc&limit=2000")
    if not isinstance(msgs, list) or not msgs:
        return 0
    gp = (mpm.leaders_room_people(biz_id) if t.get("kind") == "leaders" else mpm.group_people(biz_id, t["group_id"]))
    acc = mpm.chat_access(biz_id, t, str(folks[0]["contact_id"]))
    if acc is None or gp is None:
        return 0
    # Only people still in the chat, with messaging on, who didn't decline or mute it.
    members = {str(r["contact_id"]) for r in gp}
    allowed = set(member_push.chat_recipients(t, acc, "", folks, everyone=True)) & members
    answered = sorted({str(m["reply_to"]) for m in msgs if m.get("reply_to")})
    owners: Dict[str, str] = {}
    if answered:
        rows = sb_clients.sb_get_as_service(
            f"/msg_messages?business_id=eq.{_q(biz_id)}&id=in.({','.join(answered)})&select=id,sender_contact_id")
        owners = {str(r["id"]): str(r.get("sender_contact_id") or "") for r in (rows or [])}
    names = {i: (p.get("name") or "") for i, p in (acc.get("people") or {}).items()}
    if t.get("kind") == "leaders":
        title, url = mpm.LEADERS_ROOM, "/my/groups/leaders"
    else:
        g = sb_clients.sb_get_as_service(f"/groups?id=eq.{_q(t['group_id'])}&business_id=eq.{_q(biz_id)}&select=name&limit=1") or []
        title, url = (g[0].get("name") if g else "") or "Your group", f"/my/groups/{t['group_id']}/chat"
    sent = 0
    for p in folks:
        cid = str(p["contact_id"])
        if cid not in allowed:
            continue
        since = _since(p, floor)
        new = [m for m in msgs if str(m.get("sender_contact_id") or "") != cid
               and datetime.fromisoformat(str(m["created_at"]).replace("Z", "+00:00")) > since]
        if not new:
            continue
        writers: List[str] = []
        for m in new:
            w = str(m.get("sender_contact_id") or "")
            if w and w not in writers:
                writers.append(w)
        to_me = sum(1 for m in new if owners.get(str(m.get("reply_to") or "")) == cid)
        n = len(new)
        body = f"{n} new message{'s' if n != 1 else ''}"
        who = _names([names.get(w, "") for w in writers])
        if who:
            body += f" from {who}"
        if to_me:
            body += f" · {to_me} repl{'ies' if to_me != 1 else 'y'} to you"
        sent += member_push.send(business, "messages", title=title, body=body, url=url, contact_ids=[cid],
                                 ref_id=f"chat-evening:{tid}:{cid}:{day}", tag=f"chat-{tid}")
        sb_clients.sb_patch_as_service(
            f"/msg_participants?thread_id=eq.{_q(tid)}&contact_id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}",
            {"summed_at": now.isoformat()})
    return sent
