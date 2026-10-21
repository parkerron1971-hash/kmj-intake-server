"""
member_portal_groups.py — a group's own place in the member app.

Kevin, 2026-10-20: "We need to upgrade the groups for churches. there is no
area where people can communicate like a chat. recieve announcements from
group leader. etc... there is a entire area missing." The approved canvas
("Church Groups, Together", HZfUhGgL6phQUVfFLz3Uwb) gives every group a
page of its own; this is part 1 of building it:

  /my/groups/<id>          Home: what the leader pinned, the newest posts,
                           when it meets, the chat and video doors, who's in
  /my/groups/<id>/board    the Board: announcements from the group's leaders
                           (and from the pastors to every group), each with
                           "Got it"; a leader sees who has seen it
  /my/groups/<id>/people   who's in the group
  /my/groups/<id>/chat     the group's chat, inside the group (part 2): the
                           messaging thread, every message checked first;
                           Love / Praying / Amen, replies, report, and a
                           leader can take a message down (the safety
                           officers are told). The office can make a group
                           Board-only or leaders-only.

  /my/groups/<id>/prayer   the group's prayer wall (part 3, group_prayer):
                           ask the group, or only the pastors; danger words
                           go to a pastor first; "I'm praying", answered
  /my/groups/<id>/meet     gatherings (part 3, group_gatherings): the next
                           one, Going / Maybe / Can't, "I'm here", a
                           leader's roll and schedule, the last few
  /my/groups/leaders       All group leaders (part 2c): one chat for
                           everyone who leads a group and the church's
                           pastors (member_portal_messaging.leaders_room_people)

Someone who isn't in the group sees what it is, who leads it, and how to
get in — never who else belongs.

Kevin's calls (2026-10-20):
  * People in a group see each other's FULL names; each group's leader may
    switch the group to first names (groups.name_display). A teen always
    shows by first name, and photos follow member_photos (adults only).
  * How people join depends on the group's type and on whoever creates it
    (groups.join_mode): open = join right away; ask = a leader says yes
    (JOIN_DEFAULT per type); invite = not listed, leaders bring people in.

POST, each acting as the signed-in member (same-origin form, a live
session, the per-person limit, a redirect back with a short code):
  /my/groups/ask            join an open group, or ask to join
  /my/groups/withdraw       take back a request
  /my/groups/answer         a leader: say yes, or not now
  /my/groups/post           a leader posts to the Board (checked first, like
                            every message: msg_screen)
  /my/groups/post/ack       "Got it"
  /my/groups/post/remove    the author or a leader of the group
  /my/groups/post/pin       a leader pins or unpins (one pin per group)
  /my/groups/names          a leader: full names or first names

Records: group_join_requests, group_posts, group_post_seen
(supabase/APPLY-2026-10-20-group-space.sql). Only this file writes them.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_portal_groups")

router = APIRouter(tags=["member-portal"])

JOIN_MODES = ("open", "ask", "invite")
# A new group's way in, by its type (Kevin: "optional based on who created
# the group and what type of group this is"); whoever creates it can change it.
JOIN_DEFAULT = {"small_group": "ask", "team": "ask", "ministry": "ask", "class": "open"}
NAME_MODES = ("full", "first")
TITLE_MAX = 120
POST_MAX = 2000
POSTS_SHOWN = 40
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TABS = ("", "board", "people", "chat", "prayer", "meet")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── reading ─────────────────────────────────────────────────────────


def group_row(business_id: str, group_id: str) -> Optional[Dict[str, Any]]:
    """The group, {} when it isn't this church's or isn't running, None
    when the read failed."""
    if not UUID.match(str(group_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/groups?id=eq.{_q(group_id)}&business_id=eq.{_q(business_id)}"
        f"&select=id,name,kind,description,meets,location,capacity,open_to_join,join_mode,name_display,youth,active,"
        f"chat_on,chat_writers,meet_day,meet_time,meet_address,meet_note,meet_skips,meet_every,meet_from,study_on,updated_at&limit=1")
    if rows is None:
        return None
    if not rows or not rows[0].get("active"):
        return {}
    g = rows[0]
    import member_portal_church as mpc
    g["join_mode"] = mpc.join_mode(g)
    if g.get("name_display") not in NAME_MODES:
        g["name_display"] = "full"
    return g


def _contacts(business_id: str, ids: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    out: Dict[str, Dict[str, Any]] = {}
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(x) for x in ids[i:i + 150])})"
            f"&select=id,name,birthdate,metadata")
        if rows is None:
            return None
        out.update({str(r["id"]): r for r in rows})
    return out


def roster(business_id: str, group_id: str) -> Optional[List[Dict[str, Any]]]:
    """Everyone in the group, leaders first, then by name."""
    members = sb_clients.sb_get_as_service(
        f"/group_members?group_id=eq.{_q(group_id)}&business_id=eq.{_q(business_id)}"
        f"&select=contact_id,role,joined_on,can_host_live&limit=5000")
    if members is None:
        return None
    people = _contacts(business_id, [m["contact_id"] for m in members])
    if people is None:
        return None
    out = []
    for m in members:
        c = people.get(str(m["contact_id"]))
        if not c:
            continue
        out.append({**c, "id": str(c["id"]), "role": m.get("role") or "member", "joined_on": m.get("joined_on"),
                    "host": bool(m.get("can_host_live")) and m.get("role") == "leader"})
    out.sort(key=lambda p: (p["role"] != "leader", str(p.get("name") or "").lower()))
    return out


def _age(person: Dict[str, Any]) -> Optional[int]:
    import member_messaging_rules as rules
    return rules.age(person.get("birthdate"))


def display_name(person: Dict[str, Any], mode: str) -> str:
    """Full or first name, by the group's setting. A teen always shows by
    first name (their profile is for parents and staff)."""
    name = " ".join(str(person.get("name") or "").split())
    first = name.split(" ")[0] if name else ""
    a = _age(person)
    if mode == "first" or (a is not None and a < 18):
        return first or "Someone"
    return name or "Someone"


def my_request(business_id: str, group_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """This person's waiting request to join, {} when none, None on a failed read."""
    rows = sb_clients.sb_get_as_service(
        f"/group_join_requests?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}"
        f"&contact_id=eq.{_q(contact_id)}&status=eq.waiting&select=id,asked_at&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def my_requests(business_id: str, contact_id: str) -> Optional[set]:
    """The groups this person is waiting to hear from."""
    rows = sb_clients.sb_get_as_service(
        f"/group_join_requests?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        f"&status=eq.waiting&select=group_id&limit=200")
    if rows is None:
        return None
    return {str(r["group_id"]) for r in rows}


def requests_for(business_id: str, group_id: str) -> Optional[List[Dict[str, Any]]]:
    """Who is waiting to join, oldest first, with what a leader needs to say
    yes: their name and how long they've been around."""
    rows = sb_clients.sb_get_as_service(
        f"/group_join_requests?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}"
        f"&status=eq.waiting&select=id,contact_id,asked_at&order=asked_at.asc&limit=100")
    if rows is None:
        return None
    if not rows:
        return []
    ids = [str(r["contact_id"]) for r in rows]
    people: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 150):
        got = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(x) for x in ids[i:i + 150])})"
            f"&select=id,name,birthdate,metadata,status,created_at")
        if got is None:
            return None
        people.update({str(p["id"]): p for p in got})
    out = []
    for r in rows:
        p = people.get(str(r["contact_id"]))
        if p:
            out.append({**r, "person": p})
    return out


def posts_for(business_id: str, group_id: str, me_id: str, leader: bool,
              group_size: int) -> Optional[List[Dict[str, Any]]]:
    """The Board, pinned first, then newest: the group's own posts and the
    pastors' posts to every group. Each carries its author, whether I
    pressed "Got it", and (for a leader) how many have seen it."""
    rows = sb_clients.sb_get_as_service(
        f"/group_posts?business_id=eq.{_q(business_id)}&or=(group_id.eq.{_q(group_id)},group_id.is.null)"
        f"&removed_at=is.null&select=id,group_id,title,body,pinned,ask_ack,posted_by,after_hours,emailed,audience,publish_at,created_at"
        f"&order=created_at.desc&limit={POSTS_SHOWN}")
    if rows is None:
        return None
    # A word the office sent to the group leaders only shows to leaders; a
    # post scheduled for later only to the group's leaders until its time.
    import group_post_later as gpl
    rows = [r for r in rows if (leader or r.get("audience") != "leaders") and (leader or not gpl.is_waiting(r))]
    for r in rows:
        r["later"] = gpl.is_waiting(r)
        if r["later"]:
            r["later_label"] = gpl.label({"id": business_id}, r["publish_at"])
    if not rows:
        return []
    ids = [str(r["id"]) for r in rows]
    seen = sb_clients.sb_get_as_service(
        f"/group_post_seen?business_id=eq.{_q(business_id)}&post_id=in.({','.join(ids)})"
        f"&select=post_id,contact_id,acked_at&limit=20000")
    if seen is None:
        return None
    authors = _contacts(business_id, [str(r["posted_by"]) for r in rows if r.get("posted_by")])
    if authors is None:
        return None
    for r in rows:
        mine = [s for s in seen if str(s["post_id"]) == str(r["id"])]
        r["seen_n"] = min(len({str(s["contact_id"]) for s in mine}), group_size) if leader else 0
        r["acked_n"] = min(len({str(s["contact_id"]) for s in mine if s.get("acked_at")}), group_size) if leader else 0
        # Whoever posted it has nothing to say "Got it" to.
        r["i_acked"] = str(r.get("posted_by") or "") == str(me_id) or any(
            str(s["contact_id"]) == str(me_id) and s.get("acked_at") for s in mine)
        r["author"] = authors.get(str(r.get("posted_by") or "")) or {}
        r["church"] = not r.get("group_id")
    pinned =[r for r in rows if r.get("pinned") and not r["church"]]
    rest = sorted([r for r in rows if not (r.get("pinned") and not r["church"])],
                  key=lambda r: str(r.get("publish_at") or r.get("created_at") or ""), reverse=True)
    return pinned + rest


def mark_seen(business_id: str, contact_id: str, post_ids: List[str]) -> None:
    """Opening the group counts as seeing what's on it. Best effort."""
    if not post_ids:
        return
    try:
        sb_clients.sb_post_as_service(
            "/group_post_seen?on_conflict=post_id,contact_id",
            [{"post_id": p, "contact_id": str(contact_id), "business_id": str(business_id)} for p in post_ids],
            prefer="resolution=ignore-duplicates,return=minimal")
    except Exception:
        logger.warning("group post seen write failed", exc_info=True)


def space(business_id: str, group_id: str, me: Dict[str, Any], *, tab: str = "") -> Optional[Dict[str, Any]]:
    """Everything a group's page shows this person. None when a read failed
    (the page says "try again", never "no group"), {} when there's no such
    group here, or it's invite-only and they aren't in it."""
    g = group_row(business_id, group_id)
    if g is None:
        return None
    if not g:
        return {}
    people = roster(business_id, group_id)
    if people is None:
        return None
    me_id = str(me["id"])
    mine = next((p for p in people if p["id"] == me_id), None)
    role = (mine or {}).get("role")
    data: Dict[str, Any] = {"group": g, "role": role, "people": people,
                            "leaders": [p for p in people if p["role"] == "leader"]}
    if not role:
        if g["join_mode"] == "invite":
            return {}
        req = my_request(business_id, group_id, me_id)
        if req is None:
            return None
        data["asked"] = bool(req)
        data["full"] = bool(g.get("capacity")) and len(people) >= int(g["capacity"])
        return data
    posts = posts_for(business_id, group_id, me_id, role == "leader", len(people))
    if posts is None:
        return None
    data["posts"] = posts
    if role == "leader":
        reqs = requests_for(business_id, group_id)
        if reqs is None:
            return None
        data["requests"] = reqs
    import member_portal_group_live as mgl
    live = mgl.open_sessions(business_id, [group_id]) or {}
    data["live"] = live.get(str(group_id))
    data["host"] = bool((mine or {}).get("host"))
    return data


# ─── writing ─────────────────────────────────────────────────────────


def _is_leader(business_id: str, group_id: str, contact_id: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?group_id=eq.{_q(group_id)}&contact_id=eq.{_q(contact_id)}"
        f"&business_id=eq.{_q(business_id)}&select=role&limit=1")
    if rows is None:
        return None
    return bool(rows) and rows[0].get("role") == "leader"


def _is_member(business_id: str, group_id: str, contact_id: str) -> Optional[bool]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?group_id=eq.{_q(group_id)}&contact_id=eq.{_q(contact_id)}"
        f"&business_id=eq.{_q(business_id)}&select=role&limit=1")
    if rows is None:
        return None
    return bool(rows)


def ask(business: Dict[str, Any], me: Dict[str, Any], group_id: str) -> Tuple[bool, str]:
    """Join an open group, or ask to join one a leader says yes to."""
    business_id = str(business["id"])
    g = group_row(business_id, group_id)
    if g is None:
        return False, "error"
    if not g:
        return False, "group_gone"
    if g["join_mode"] == "invite":
        return False, "group_invite"
    if g["join_mode"] == "open":
        import member_portal_church as mpc
        return mpc.add_member(business_id, me, g)
    member = _is_member(business_id, g["id"], me["id"])
    if member is None:
        return False, "error"
    if member:
        return True, "joined"
    if g.get("capacity"):
        count = sb_clients.sb_get_as_service(f"/group_members?group_id=eq.{_q(g['id'])}&select=contact_id&limit=10001")
        if count is None:
            return False, "error"
        if len(count) >= int(g["capacity"]):
            return False, "group_full"
    waiting = my_request(business_id, g["id"], me["id"])
    if waiting is None:
        return False, "error"
    if waiting:
        return True, "asked"
    saved = sb_clients.sb_post_as_service("/group_join_requests", {
        "business_id": business_id, "group_id": g["id"], "contact_id": str(me["id"]), "status": "waiting"})
    if not saved:
        # A double press: the one-waiting index refused the second.
        again = my_request(business_id, g["id"], me["id"])
        return (True, "asked") if again else (False, "error")
    import member_push
    member_push.tell_join_request(business, g, me)
    return True, "asked"


def withdraw(business_id: str, me: Dict[str, Any], group_id: str) -> Tuple[bool, str]:
    if not UUID.match(str(group_id or "")):
        return False, "group_gone"
    ok = sb_clients.sb_patch_as_service(
        f"/group_join_requests?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}"
        f"&contact_id=eq.{_q(me['id'])}&status=eq.waiting",
        {"status": "withdrawn", "decided_at": _now()})
    return (True, "withdrawn") if ok is not None else (False, "error")


def answer(business: Dict[str, Any], me: Dict[str, Any], request_id: str, yes: bool) -> Tuple[bool, str, str]:
    """A leader of the group says yes, or not now. (ok, code, group_id)."""
    business_id = str(business["id"])
    if not UUID.match(str(request_id or "")):
        return False, "gone", ""
    rows = sb_clients.sb_get_as_service(
        f"/group_join_requests?id=eq.{_q(request_id)}&business_id=eq.{_q(business_id)}"
        f"&select=id,group_id,contact_id,status&limit=1")
    if rows is None:
        return False, "error", ""
    if not rows:
        return False, "gone", ""
    r = rows[0]
    gid = str(r["group_id"])
    leader = _is_leader(business_id, gid, me["id"])
    if leader is None:
        return False, "error", gid
    if not leader:
        return False, "not_group_leader", gid
    if r.get("status") != "waiting":
        return False, "answered", gid
    if yes:
        g = group_row(business_id, gid)
        if g is None:
            return False, "error", gid
        if not g:
            return False, "group_gone", gid
        import member_portal_church as mpc
        ok, code = mpc.add_member(business_id, {"id": str(r["contact_id"])}, g)
        if not ok:
            return False, code, gid
    done = sb_clients.sb_patch_as_service(
        f"/group_join_requests?id=eq.{_q(request_id)}&business_id=eq.{_q(business_id)}&status=eq.waiting",
        {"status": "yes" if yes else "no", "decided_at": _now(), "decided_by": str(me["id"])})
    if done is None:
        return False, "error", gid
    if yes:
        import member_push
        member_push.tell_join_yes(business, gid, str(r["contact_id"]))
    return True, "said_yes" if yes else "not_now", gid


async def create_post(business: Dict[str, Any], me: Dict[str, Any], group_id: str, title: str, body: str,
                      pinned: bool, ask_ack: bool, after_hours: bool = False, email_rest: bool = False,
                      send_at: str = "") -> Tuple[bool, str]:
    import asyncio
    import msg_screen
    business_id = str(business["id"])
    g = await asyncio.to_thread(group_row, business_id, group_id)
    if g is None:
        return False, "error"
    if not g:
        return False, "group_gone"
    leader = await asyncio.to_thread(_is_leader, business_id, g["id"], me["id"])
    if leader is None:
        return False, "error"
    if not leader:
        return False, "not_group_leader"
    title = " ".join(str(title or "").split())[:TITLE_MAX]
    body = re.sub(r"[ \t]+\n", "\n", str(body or "")).strip()[:POST_MAX]
    if not body:
        return False, "empty_post"
    # Send later (group_post_later): a time on the church's clock.
    import group_post_later as gpl
    when, why = await asyncio.to_thread(gpl.when_from, business, send_at)
    if why:
        return False, why
    try:
        verdict = await msg_screen.screen(business_id, f"{title}\n{body}".strip())
    except msg_screen.ScreenUnavailable:
        return False, "post_busy"
    if verdict != "ok":
        return False, "post_no"
    # An after-hours alert (member_push quiet hours): only in quiet hours,
    # one a night for each leader.
    import member_portal_messaging as mpm
    import member_push
    alert = bool(after_hours) and not when and await asyncio.to_thread(member_push.quiet_hour, business)
    if alert:
        used = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/group_posts?business_id=eq.{_q(business_id)}&posted_by=eq.{_q(me['id'])}&after_hours=is.true"
            f"&created_at=gte.{quote(mpm.alert_since(), safe='')}&select=id&limit=1")
        if not isinstance(used, list):
            return False, "error"
        if used:
            return False, "alert_used"
    if pinned and not when:
        # One pin per group: the new one takes the top (a scheduled one, when it goes out).
        await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/group_posts?business_id=eq.{_q(business_id)}&group_id=eq.{_q(g['id'])}&pinned=eq.true",
            {"pinned": False})
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/group_posts", {
        "business_id": business_id, "group_id": g["id"], "title": title, "body": body,
        "pinned": bool(pinned), "ask_ack": bool(ask_ack), "posted_by": str(me["id"]),
        **({"after_hours": True} if alert else {}), **({"email_rest": True} if email_rest else {}),
        **({"publish_at": when.astimezone(timezone.utc).isoformat()} if when else {})})
    if not (isinstance(rows, list) and rows):
        return False, "error"
    if when:
        return True, "post_later"
    member_push.tell_group_post(business, g, str(rows[0].get("id") or ""), me, title, ring=bool(alert))
    if email_rest:
        # "Email the rest" (group_email): the group's people with no phone
        # set up for the app, off the request.
        import group_email
        group_email.spawn(group_email.email_rest(business, g, {**rows[0], "title": title, "body": body}, me))
    return True, "post_up"


def _post(business_id: str, post_id: str) -> Optional[Dict[str, Any]]:
    if not UUID.match(str(post_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/group_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&removed_at=is.null"
        f"&select=id,group_id,posted_by,pinned&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def ack(business_id: str, me: Dict[str, Any], post_id: str) -> Tuple[bool, str, str]:
    """"Got it" on a post this person can see. (ok, code, group_id)."""
    p = _post(business_id, post_id)
    if p is None:
        return False, "error", ""
    if not p:
        return False, "gone", ""
    gid = str(p.get("group_id") or "")
    if gid:
        member = _is_member(business_id, gid, me["id"])
        if member is None:
            return False, "error", gid
        if not member:
            return False, "not_in_group", gid
    else:
        rows = sb_clients.sb_get_as_service(
            f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me['id'])}&select=group_id&limit=1")
        if rows is None:
            return False, "error", ""
        if not rows:
            return False, "not_in_group", ""
    # return=representation: a minimal write hands back None even when it
    # worked, which would read as a failure.
    ok = sb_clients.sb_post_as_service(
        "/group_post_seen?on_conflict=post_id,contact_id",
        {"post_id": str(p["id"]), "contact_id": str(me["id"]), "business_id": str(business_id), "acked_at": _now()},
        prefer="resolution=merge-duplicates,return=representation")
    return (True, "got_it", gid) if ok else (False, "error", gid)


def remove_post(business_id: str, me: Dict[str, Any], post_id: str) -> Tuple[bool, str, str]:
    p = _post(business_id, post_id)
    if p is None:
        return False, "error", ""
    if not p or not p.get("group_id"):
        return False, "gone", str(p.get("group_id") or "") if p else ""
    gid = str(p["group_id"])
    if str(p.get("posted_by") or "") != str(me["id"]):
        leader = _is_leader(business_id, gid, me["id"])
        if leader is None:
            return False, "error", gid
        if not leader:
            return False, "not_group_leader", gid
    ok = sb_clients.sb_patch_as_service(
        f"/group_posts?id=eq.{_q(p['id'])}&business_id=eq.{_q(business_id)}", {"removed_at": _now(), "pinned": False})
    return (True, "post_down", gid) if ok is not None else (False, "error", gid)


def pin(business_id: str, me: Dict[str, Any], post_id: str, on: bool) -> Tuple[bool, str, str]:
    p = _post(business_id, post_id)
    if p is None:
        return False, "error", ""
    if not p or not p.get("group_id"):
        return False, "gone", ""
    gid = str(p["group_id"])
    leader = _is_leader(business_id, gid, me["id"])
    if leader is None:
        return False, "error", gid
    if not leader:
        return False, "not_group_leader", gid
    if on:
        sb_clients.sb_patch_as_service(
            f"/group_posts?business_id=eq.{_q(business_id)}&group_id=eq.{_q(gid)}&pinned=eq.true", {"pinned": False})
    ok = sb_clients.sb_patch_as_service(
        f"/group_posts?id=eq.{_q(p['id'])}&business_id=eq.{_q(business_id)}", {"pinned": bool(on)})
    return (True, "pinned" if on else "unpinned", gid) if ok is not None else (False, "error", gid)


def set_names(business_id: str, me: Dict[str, Any], group_id: str, mode: str) -> Tuple[bool, str]:
    if mode not in NAME_MODES:
        return False, "error"
    leader = _is_leader(business_id, group_id, me["id"])
    if leader is None:
        return False, "error"
    if not leader:
        return False, "not_group_leader"
    ok = sb_clients.sb_patch_as_service(
        f"/groups?id=eq.{_q(group_id)}&business_id=eq.{_q(business_id)}",
        {"name_display": mode, "updated_at": _now()})
    return (True, f"names_{mode}") if ok is not None else (False, "error")


# ─── the page ────────────────────────────────────────────────────────

# Group pages: the member app's tokens, groups in teal (the Connect colour),
# the church colour only on what you press. One sheet, gs-* names.
GROUP_CSS = """
.gs-hero{position:relative;display:grid;margin:0 calc(var(--g) * -1);min-height:268px;color:#fff;overflow:hidden;border-radius:0 0 var(--r-lg) var(--r-lg);}
.gs-hero>*{grid-area:1/1;}
.gs-hero .gs-art,.gs-hero .gs-art>*{width:100%;height:100%;min-height:268px;object-fit:cover;display:block;}
.gs-hero .gs-art{position:relative;}
.gs-scrim{position:relative;background:linear-gradient(180deg,rgba(0,0,0,.18) 0%,rgba(0,0,0,0) 30%,rgba(0,0,0,.55) 62%,rgba(0,0,0,.9) 100%);}
.gs-hero-in{position:relative;align-self:end;display:flex;flex-direction:column;gap:6px;padding:0 var(--g) 18px;}
.gs-kind{align-self:flex-start;display:inline-flex;align-items:center;height:26px;padding:0 10px;border-radius:999px;font-size:12.5px;font-weight:650;
  background:rgba(255,255,255,.2);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);}
.gs-hero h1{color:#fff;margin:0;font-size:33px;letter-spacing:-.04em;line-height:1.04;}
.gs-hero p{margin:0;font-size:14px;color:rgba(255,255,255,.86);}
.gs-who{display:flex;align-items:center;gap:10px;margin-top:4px!important;}
.gs-faces{display:flex;align-items:center;}
.gs-faces .gs-av{margin-left:-4px;box-shadow:0 0 0 2px rgba(0,0,0,.55);}
@media (min-width:640px){.gs-hero{margin:0;border-radius:var(--r-lg);}}
.gs-faces .gs-av:first-child{margin-left:0;}
.gs-av{width:28px;height:28px;border-radius:50%;flex:none;display:grid;place-items:center;overflow:hidden;font-size:11px;font-weight:700;
  background:var(--teal-deep);color:var(--teal-ink);}
.gs-av img{width:100%;height:100%;object-fit:cover;display:block;}
.gs-av.m{width:42px;height:42px;font-size:14px;}
.gs-av.l{width:56px;height:56px;font-size:18px;}
.gs-tabs{display:flex;gap:6px;overflow-x:auto;margin:16px calc(var(--g) * -1) 0;padding:0 var(--g) 2px;scrollbar-width:none;}
.gs-tabs::-webkit-scrollbar{display:none;}
.gs-tab{flex:none;display:inline-flex;align-items:center;gap:7px;min-height:42px;padding:0 15px;border-radius:999px;background:var(--s1);
  color:var(--fg2);font-size:14.5px;font-weight:600;text-decoration:none;letter-spacing:-.01em;}
.gs-tab[aria-current]{background:var(--teal-deep);color:var(--teal-ink);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--teal-ink) 30%,transparent);}
.gs-n{min-width:19px;height:19px;padding:0 5px;border-radius:10px;background:var(--acc-fill);color:var(--on-acc);font-size:11px;font-weight:700;display:grid;place-items:center;}
.gs-card{border-radius:var(--r-lg);background:var(--s1);padding:16px;display:flex;flex-direction:column;gap:12px;margin-bottom:12px;}
.gs-card.pin{background:var(--teal-deep);}
.gs-card.church{background:var(--acc-deep,var(--s1));}
.gs-ph{display:flex;align-items:center;gap:10px;}
.gs-ph .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;}
.gs-ph b{font-size:14.5px;font-weight:650;display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.gs-ph small{font-size:12.5px;color:var(--fg2);}
.gs-tag{display:inline-flex;align-items:center;height:19px;padding:0 7px;border-radius:6px;background:var(--teal-deep);color:var(--teal-ink);font-size:11px;font-weight:700;}
.gs-card.pin .gs-tag{background:var(--s1);}
.gs-tag.pastor{background:var(--acc-soft);color:var(--acc);}
.gs-pinned{display:inline-flex;align-items:center;gap:4px;color:var(--teal-ink);font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;}
.gs-card h3{margin:0;font-size:19px;font-weight:700;letter-spacing:-.022em;line-height:1.2;}
.gs-card p.gs-body{margin:0;font-size:15px;line-height:1.5;white-space:pre-line;overflow-wrap:anywhere;}
.gs-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;}
.gs-foot form{margin:0;}
.gs-ack{display:inline-flex;align-items:center;gap:6px;min-height:42px;padding:0 16px;border-radius:999px;border:0;background:var(--acc-fill);
  color:var(--on-acc);font:inherit;font-size:14.5px;font-weight:620;cursor:pointer;}
.gs-ack.done{background:var(--s2);color:var(--fg2);cursor:default;}
.gs-seen{font-size:13px;color:var(--fg2);}
.gs-mini{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 4px;border:0;background:none;font:inherit;font-size:14px;
  font-weight:600;color:var(--teal-ink);cursor:pointer;text-decoration:none;}
.gs-mini.warn{color:var(--error);}
.gs-row{display:flex;align-items:center;gap:14px;padding:14px 16px;text-decoration:none;color:inherit;position:relative;}
.gs-list{border-radius:var(--r-md);background:var(--s1);overflow:hidden;margin-bottom:12px;}
.gs-list>.gs-row+.gs-row::before{content:"";position:absolute;top:0;left:72px;right:0;height:.5px;background:var(--line);}
.gs-row .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.gs-row .gs-t b{font-size:16px;font-weight:620;letter-spacing:-.015em;}
.gs-row .gs-t span{font-size:13.5px;color:var(--fg2);}
.gs-disc{width:42px;height:42px;border-radius:50%;flex:none;display:grid;place-items:center;background:var(--teal-deep);color:var(--teal-ink);}
.gs-disc.gold{background:var(--gold-deep);color:var(--gold-ink);}
.gs-disc.violet{background:var(--violet-deep);color:var(--violet-ink);}
.gs-disc.coral{background:var(--coral-deep);color:var(--coral-ink);}
.gs-acts{display:flex;gap:8px;flex-wrap:wrap;}
.gs-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 18px;border-radius:999px;border:0;
  background:var(--acc-fill);color:var(--on-acc);font:inherit;font-size:15px;font-weight:600;text-decoration:none;cursor:pointer;}
.gs-btn.soft{background:var(--s2);color:var(--fg);}
.gs-btn.tint{background:var(--teal-deep);color:var(--teal-ink);}
.gs-btn.sm{min-height:38px;padding:0 14px;font-size:14px;}
.gs-req{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;padding:14px 16px;position:relative;}
.gs-req+.gs-req::before{content:"";position:absolute;top:0;left:16px;right:0;height:.5px;background:var(--line);}
.gs-req .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.gs-req .gs-t b{font-size:16px;font-weight:620;}
.gs-req .gs-t span{font-size:13.5px;color:var(--fg2);}
.gs-req .gs-acts{width:100%;padding-left:56px;}
.gs-req form{margin:0;}
.gs-head{display:flex;align-items:center;gap:10px;padding:14px 16px 4px;}
.gs-head b{font-size:15.5px;font-weight:660;}
.gs-compose{border-radius:var(--r-lg);background:var(--s1);padding:6px 16px 16px;display:flex;flex-direction:column;gap:6px;margin-bottom:16px;}
.gs-compose label.gs-l{font-size:12.5px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;color:var(--fg3);padding-top:10px;}
.gs-compose input[type=text],.gs-compose textarea{width:100%;border:0;outline:none;background:var(--bg);color:var(--fg);border-radius:12px;
  padding:12px 14px;font:inherit;font-size:16px;line-height:1.45;}
.gs-compose input[type=text]{font-weight:650;}
.gs-compose textarea{min-height:120px;resize:vertical;}
.gs-check{display:flex;align-items:center;gap:10px;min-height:40px;font-size:14.5px;}
.gs-check input{width:20px;height:20px;flex:none;margin:0;accent-color:var(--teal);}
.gs-fine{font-size:12.5px;color:var(--fg3);margin:0;}
.gs-meet{display:flex;align-items:center;gap:14px;}
.gs-meet .gs-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.gs-meet .gs-t b{font-size:17px;font-weight:660;letter-spacing:-.02em;}
.gs-meet .gs-t span{font-size:13.5px;color:var(--fg2);}
.gs-lead{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:12px;}
.gs-lc{border-radius:var(--r-md);background:var(--teal-deep);padding:16px 12px 14px;display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;}
.gs-lc b{font-size:15.5px;font-weight:660;}
.gs-lc small{font-size:12.5px;color:var(--fg2);}
.gs-note{display:flex;gap:10px;align-items:flex-start;font-size:13px;color:var(--fg3);line-height:1.45;margin:4px 0 12px;}
.gs-note .mb-ic{margin-top:2px;}
.gs-seg{display:inline-grid;grid-auto-flow:column;padding:3px;border-radius:12px;background:var(--s2);}
.gs-seg button{min-height:36px;padding:0 14px;border:0;border-radius:9px;background:none;color:var(--fg2);font:inherit;font-size:14px;font-weight:600;cursor:pointer;}
.gs-seg button[aria-pressed=true]{background:var(--s3);color:var(--fg);}
.gs-about{font-size:15px;color:var(--fg2);line-height:1.5;margin:14px 0 0;white-space:pre-line;}
.gs-empty{border-radius:var(--r-md);background:var(--s1);padding:18px 16px;color:var(--fg2);font-size:14.5px;margin-bottom:12px;}
.gs-wait{display:inline-flex;align-items:center;gap:6px;min-height:38px;padding:0 14px;border-radius:999px;background:var(--teal-deep);
  color:var(--teal-ink);font-size:14px;font-weight:620;}
"""


def _ic(name: str, size: int = 18) -> str:
    import member_app_ui as ui
    extra = {
        "megaphone": '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
        # Praying, on a message in the chat.
        "hand-heart": ('<path d="M11 14h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 16"/><path d="m7 20 1.6-1.4c.3-.4.8-.6 1.4-.6h4'
                       'c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/><path d="m2 15 6 6"/><path d="M19.5 8.5'
                       'c.7-.7 1.5-1.6 1.5-2.7A2.73 2.73 0 0 0 16 4a2.78 2.78 0 0 0-5 1.8c0 1.2.8 2 1.5 2.8L16 12Z"/>'),
        "pin": ('<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76'
                'a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>'),
        "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
        "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        # Chief, on this week's study (group_study).
        "sparkles": ('<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5'
                     'l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063'
                     'a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4M22 5h-4M4 17v2M5 18H3"/>'),
        # Bring something (group_bring).
        "utensils": ('<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/>'
                     '<path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>'),
    }
    if name in extra:
        return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{extra[name]}</svg>')
    return ui.icon(name, size)


def _when(iso: Any) -> str:
    try:
        then = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    mins = int((datetime.now(timezone.utc) - then).total_seconds() // 60)
    if mins < 2:
        return "Just now"
    if mins < 60:
        return f"{mins} min ago"
    if mins < 60 * 24:
        return f"{mins // 60} h ago"
    days = mins // (60 * 24)
    if days == 1:
        return "Yesterday"
    if days < 7:
        return then.strftime("%A")
    return f"{then.strftime('%b')} {then.day}"


def _since(d: Any) -> str:
    try:
        day = date.fromisoformat(str(d)[:10])
    except ValueError:
        return ""
    return f"Since {day.strftime('%b')} {day.year}" if day.year == date.today().year else f"Since {day.year}"


def _face(person: Dict[str, Any], cls: str = "gs-av", mode: str = "full") -> str:
    """Their photo when members may see it, else initials of the name the
    group shows (so first-name mode, and a teen, show one letter)."""
    import member_photos as ph
    shown = display_name(person, mode) if person.get("name") else ""
    return ph.avatar({**person, "name": shown}, show=ph.shown_to_members(person), cls=cls)


def _base(gid: str, tab: str = "") -> str:
    return f"/my/groups/{gid}" + (f"/{tab}" if tab else "")


def _flash(request: Request) -> str:
    import member_portal_church as mpc
    return mpc._flash(request)


def _hero(biz: Dict[str, Any], site, g: Dict[str, Any], people: List[Dict[str, Any]],
          leaders: List[Dict[str, Any]], in_group: bool) -> str:
    import member_app_ui as ui
    import member_app_photos as photos
    import member_portal_church as mpc
    from member_portal import _e
    pool = photos.photos(biz, site)
    pic, look = photos.choose(biz, f"group:{g['id']}", pool, title=g.get("name") or "")
    art = ui.picture(pic, look, "youth" if g.get("youth") else "groups", eager=True, night=True)
    facts = " · ".join(_e(x) for x in (g.get("meets"), g.get("location")) if x)
    kind = mpc.GROUP_KINDS.get(g.get("kind") or "", "Group")
    led = [display_name(p, "first") for p in leaders]
    led_line = f'led by {_e(_and(led))}' if led else ""
    n = len(people)
    count = f"{n} {'person' if n == 1 else 'people'}" if in_group else ""
    who = " · ".join(x for x in (count, led_line) if x)
    shown = (leaders + [p for p in people if p["role"] != "leader"])[:4] if in_group else leaders[:3]
    faces = "".join(_face(p, mode=g.get("name_display") or "full") for p in shown)
    facts_p = f'<p>{facts}</p>' if facts else ""
    who_p = (f'<p class="gs-who"><span class="gs-faces" aria-hidden="true">{faces}</span><span>{who}</span></p>'
             if who else "")
    return (f'<section class="gs-hero" aria-labelledby="gs-name"><span class="gs-art">{art}</span><span class="gs-scrim"></span>'
            f'<div class="gs-hero-in"><span class="gs-kind">{_e(kind)}</span><h1 id="gs-name">{_e(g.get("name") or "")}</h1>'
            f'{facts_p}{who_p}</div></section>')


def _and(names: List[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _tabs(gid: str, current: str, *, board_new: int, chat: bool, live: Optional[Dict[str, Any]]) -> str:
    from member_portal import _e
    items = [("", "Home", "home", 0)]
    if chat:
        items.append(("chat", "Chat", "chat", 0))
    items += [("board", "Board", "megaphone", board_new), ("prayer", "Prayer", "hand-heart", 0), ("meet", "Meet", "calendar", 0),
              ("people", "People", "users", 0)]
    out = []
    for key, label, icon, n in items:
        cur = ' aria-current="page"' if key == current else ""
        badge = f'<span class="gs-n" aria-label="{n} new">{n}</span>' if n else ""
        out.append(f'<a class="gs-tab" href="{_base(gid, key)}"{cur}>{_ic(icon, 17)}<span>{label}</span>{badge}</a>')
    if live:
        out.append(f'<a class="gs-tab" href="/my/groups/live/{_e(live["id"])}">{_ic("video", 17)}<span>Video</span></a>')
    return f'<nav class="gs-tabs" aria-label="In this group">{"".join(out)}</nav>'


def _post_card(p: Dict[str, Any], g: Dict[str, Any], *, leader: bool, me_id: str, size: int, back: str) -> str:
    from member_portal import _e
    author = p.get("author") or {}
    # The office's word has no author contact: it's from the pastors.
    name = (display_name(author, g.get("name_display") or "full") if author
            else "Your pastors" if p.get("church") else "A leader")
    tag = '<span class="gs-tag pastor">Pastor</span>' if p.get("church") else '<span class="gs-tag">Leader</span>'
    who = f'{_e(name)} {tag}'
    meta = _when(p.get("created_at"))
    later = bool(p.get("later"))
    if later:
        meta = f"Goes out {p.get('later_label') or 'later'}"
        tag += '<span class="gs-tag later">Scheduled</span>'
        who = f'{_e(name)} {tag}'
    if p.get("church"):
        meta += " · to every group leader" if p.get("audience") == "leaders" else " · to every group"
    pinned = bool(p.get("pinned")) and not p.get("church")
    pin_mark = f'<span class="gs-pinned">{_ic("pin", 14)}Pinned</span>' if pinned else ""
    if p.get("after_hours"):
        pin_mark += f'<span class="gs-pinned gc-ahs">{_ic("bell", 14)}After-hours alert</span>'
    title = f'<h3>{_e(p["title"])}</h3>' if p.get("title") else ""
    pid = _e(p["id"])
    ack = ""
    if p.get("ask_ack") and not later:
        if p.get("i_acked"):
            ack = f'<span class="gs-ack done">{_ic("check", 15)}You saw this</span>'
        else:
            ack = (f'<form method="post" action="/my/groups/post/ack"><input type="hidden" name="id" value="{pid}">'
                   f'<input type="hidden" name="back" value="{_e(back)}">'
                   f'<button class="gs-ack" type="submit">{_ic("check", 15)}Got it</button></form>')
    seen = ""
    if leader and not p.get("church") and not later:
        bits = [f"Seen by {int(p.get('seen_n') or 0)} of {size}"]
        if p.get("ask_ack"):
            bits.append(f"{int(p.get('acked_n') or 0)} said got it")
        if p.get("emailed"):
            bits.append(f"{int(p['emailed'])} by email")
        seen = f'<span class="gs-seen">{" · ".join(bits)}</span>'
    tools = ""
    if not p.get("church") and (leader or str(p.get("posted_by") or "") == str(me_id)):
        pin_form = ""
        if leader:
            pin_form = (f'<form method="post" action="/my/groups/post/pin"><input type="hidden" name="id" value="{pid}">'
                        f'<input type="hidden" name="on" value="{"0" if pinned else "1"}">'
                        f'<button class="gs-mini" type="submit">{_ic("pin", 15)}{"Unpin" if pinned else "Pin to the top"}</button></form>')
        if later:
            pin_form = (f'<form method="post" action="/my/groups/post/now"><input type="hidden" name="id" value="{pid}">'
                        f'<button class="gs-mini" type="submit">{_ic("send", 15)}Send now</button></form>')
        tools = (f'<div class="gs-acts">{pin_form}<form method="post" action="/my/groups/post/remove">'
                 f'<input type="hidden" name="id" value="{pid}"><button class="gs-mini warn" type="submit">Take it down</button>'
                 f'</form></div>')
    cls = "gs-card later" if later else "gs-card pin" if pinned else ("gs-card church" if p.get("church") else "gs-card")
    face = _face(author, "gs-av m", g.get("name_display") or "full") if author else '<span class="gs-av m" aria-hidden="true">?</span>'
    foot = f'<div class="gs-foot">{ack}{seen}</div>' if (ack or seen) else ""
    return (f'<article class="{cls}"><div class="gs-ph">{face}<span class="gs-t"><b>{who}</b><small>{_e(meta)}</small></span>'
            f'{pin_mark}</div>{title}<p class="gs-body">{_e(p.get("body") or "")}</p>{foot}{tools}</article>')


def _requests_block(reqs: List[Dict[str, Any]], g: Dict[str, Any], back: str = "") -> str:
    from member_portal import _e
    if not reqs:
        return ""
    back_in = f'<input type="hidden" name="back" value="{_e(back)}">' if back else ""
    rows = []
    for r in reqs:
        p = r["person"]
        status = "Member" if (p.get("status") or "") in ("active", "member") else "Visitor"
        bits = [f"{status} since {str(p.get('created_at') or '')[:4]}" if p.get("created_at") else status,
                f"asked {_when(r.get('asked_at')).lower()}"]
        name = display_name(p, "full")
        rid = _e(r["id"])
        rows.append(
            f'<div class="gs-req">{_face(p, "gs-av m")}<span class="gs-t"><b>{_e(name)}</b><span>{_e(" · ".join(b for b in bits if b))}</span></span>'
            f'<div class="gs-acts"><form method="post" action="/my/groups/answer"><input type="hidden" name="id" value="{rid}">{back_in}'
            f'<input type="hidden" name="yes" value="0"><button class="gs-btn soft sm" type="submit" aria-label="Not now for {_e(name)}">Not now</button></form>'
            f'<form method="post" action="/my/groups/answer"><input type="hidden" name="id" value="{rid}">{back_in}'
            f'<input type="hidden" name="yes" value="1"><button class="gs-btn sm" type="submit" aria-label="Say yes to {_e(name)}">Say yes</button></form></div></div>')
    return (f'<section class="gs-list" aria-labelledby="gs-req-h"><div class="gs-head"><b id="gs-req-h">Asking to join</b>'
            f'<span class="gs-n">{len(reqs)}</span></div>{"".join(rows)}</section>')


def _compose(g: Dict[str, Any], quiet: bool = False, later: str = "") -> str:
    from member_portal import _e
    alert = (f'<label class="gs-check"><input type="checkbox" name="after_hours" value="1">After-hours alert: '
             f'rings through quiet hours for people who allow it. One a night.</label>' if quiet else "")
    return (f'<form class="gs-compose" id="post" method="post" action="/my/groups/post">'
            f'<input type="hidden" name="group_id" value="{_e(g["id"])}">'
            f'<label class="gs-l" for="gs-pt">Post to the Board</label>'
            f'<input type="text" id="gs-pt" name="title" maxlength="{TITLE_MAX}" placeholder="What\'s it about?">'
            f'<label class="mp-sr" for="gs-pb">Your post</label>'
            f'<textarea id="gs-pb" name="body" maxlength="{POST_MAX}" required '
            f'placeholder="Write it like you\'d say it to the group."></textarea>'
            f'<label class="gs-check"><input type="checkbox" name="pin" value="1">Pin it to the top</label>'
            f'<label class="gs-check"><input type="checkbox" name="ack" value="1" checked>Ask everyone for a “Got it”</label>{alert}'
            f'<label class="gs-check"><input type="checkbox" name="email" value="1">Email the people who haven’t set the app up on a phone</label>'
            f'{later}'
            f'<button class="gs-btn" type="submit">{_ic("send", 16)}Post to {_e(g.get("name") or "the group")}</button>'
            f'<p class="gs-fine">Everyone in the group sees it on the group\'s Home and Board. It\'s checked before it goes up, like every message.</p>'
            f'</form>')


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], data: Optional[Dict[str, Any]],
           tab: str = "") -> Tuple[str, int]:
    """The group's page. (html, status)."""
    import member_portal_messaging as mpm
    from member_portal import _e, _shell
    if data is None:
        body = ('<a class="mb-back" href="/my/groups">Connect</a>'
                '<p class="mp-err" role="alert">This group couldn\'t load just now. Please try again in a moment.</p>')
        return _shell(biz, site, "Group", f"<style>{GROUP_CSS}</style>{body}", tab="connect", who=me), 503
    if not data:
        body = ('<a class="mb-back" href="/my/groups">Connect</a><div class="mb-lt"><h1>Not here</h1></div>'
                '<p class="mp-muted">This group isn\'t running any more, or it\'s by invitation. '
                'Find another on Connect, or ask the church office.</p>')
        return _shell(biz, site, "Group", f"<style>{GROUP_CSS}</style>{body}", tab="connect", who=me), 404
    g, people, leaders, role = data["group"], data["people"], data["leaders"], data.get("role")
    gid = _e(g["id"])
    hero = _hero(biz, site, g, people, leaders, bool(role))
    flash = _flash(request)
    about = f'<p class="gs-about">{_e(g["description"])}</p>' if g.get("description") else ""
    if not role:
        if data.get("asked"):
            act = (f'<span class="gs-wait">{_ic("clock", 15)}Asked · a leader will say yes</span>'
                   f'<form method="post" action="/my/groups/withdraw"><input type="hidden" name="group_id" value="{gid}">'
                   f'<button class="gs-mini" type="submit">Take back my request</button></form>')
        elif data.get("full"):
            act = '<p class="mp-muted">This group is full right now. Ask the church office about the next one.</p>'
        else:
            label = "Join" if g["join_mode"] == "open" else "Ask to join"
            note = ("You'll be in right away." if g["join_mode"] == "open"
                    else "A leader of the group says yes, usually within a day or two.")
            act = (f'<form method="post" action="/my/groups/ask"><input type="hidden" name="group_id" value="{gid}">'
                   f'<button class="gs-btn" type="submit">{label}</button></form><p class="gs-fine" style="width:100%">{note}</p>')
        led = "".join(f'<div class="gs-lc">{_face(p, "gs-av l", "first")}<b>{_e(display_name(p, "first"))}</b><small>Leader</small></div>'
                      for p in leaders)
        leads = f'<div class="mb-sh"><h2>Who leads</h2></div><div class="gs-lead">{led}</div>' if led else ""
        body = (f'<a class="mb-back" href="/my/groups">Connect</a>{hero}{flash}{about}'
                f'<div class="gs-acts" style="margin-top:18px">{act}</div>{leads}')
        return _shell(biz, site, g.get("name") or "Group", f"<style>{GROUP_CSS}</style>{body}", tab="connect", who=me), 200
    leader = role == "leader"
    posts = data.get("posts") or []
    me_id = str(me["id"])
    unread = sum(1 for p in posts if p.get("ask_ack") and not p.get("i_acked"))
    chat = mpm.turned_on(biz) and g.get("chat_on") is not False
    tabs = _tabs(g["id"], tab, board_new=unread if tab != "board" else 0, chat=chat, live=data.get("live"))
    back = _base(g["id"], tab)
    size = len(people)
    script = ""
    if tab == "chat":
        content, script = _chat_body(biz, request, me, g, data.get("chat") or {"state": "error"}, leader)
    elif tab == "meet":
        import group_gatherings
        import group_study
        st = data.get("study")
        study = group_study.render(g, st, leader=leader, people=people, next_day=(data.get("meet") or {}).get("next"),
                                   ic=_ic, esc=_e, name=lambda p: display_name(p, g.get("name_display") or "full"))
        draft = bool(st and st.get("study") and not st["study"].get("posted_at"))
        content = group_gatherings.render_tab(
            biz, g, data.get("meet"), me_id=me_id, leader=leader, people=people, live=data.get("live"), ic=_ic,
            face=lambda p: _face(p, "gs-av m", g.get("name_display") or "full"), esc=_e,
            name=lambda p: display_name(p, g.get("name_display") or "full"), study="" if draft else study)
        if draft:
            content = study + content
        if (data.get("meet") is not None) and st is None:
            content += '<p class="mp-err" role="alert">This week’s study couldn’t load just now. Please try again in a moment.</p>'
    elif tab == "prayer":
        import group_prayer
        content = group_prayer.render_tab(
            biz, g, data.get("prayer"), me_id=me_id, leader=leader, size=size,
            answered=request.query_params.get("view") == "answered", ic=_ic,
            face=lambda p: _face(p, "gs-av m", "first"), when=_when, esc=_e)
    elif tab == "board":
        cards = "".join(_post_card(p, g, leader=leader, me_id=me_id, size=size, back=back) for p in posts)
        empty = ('<p class="gs-empty">Nothing on the Board yet. When a leader posts, it shows here.</p>' if not cards else "")
        import member_push
        import group_post_later as gpl
        content = f'{_compose(g, member_push.quiet_hour(biz), gpl.compose_later(biz, _ic)) if leader else ""}{cards}{empty}'
        content += (f'<p class="gs-note">{_ic("lock", 15)}<span>Only the group\'s leaders post here, plus your pastors to every group.'
                    f'</span></p>')
    elif tab == "people":
        mode = g.get("name_display") or "full"
        lead_cards = "".join(
            f'<div class="gs-lc">{_face(p, "gs-av l", mode)}<b>{_e(display_name(p, mode))}</b><small>Leader</small></div>'
            for p in leaders)
        rows = "".join(
            f'<div class="gs-row">{_face(p, "gs-av m", mode)}<span class="gs-t"><b>{_e(display_name(p, mode))}'
            f'{" (you)" if p["id"] == me_id else ""}</b><span>{_e(_since(p.get("joined_on")))}</span></span></div>'
            for p in people if p["role"] != "leader")
        members = f'<div class="gs-list">{rows}</div>' if rows else '<p class="gs-empty">No one else has joined yet.</p>'
        names = ""
        if leader:
            names = (f'<div class="gs-card"><div class="gs-ph"><span class="gs-t"><b>Names in this group</b>'
                     f'<small>You choose. Phone numbers and emails always stay hidden.</small></span></div>'
                     f'<form method="post" action="/my/groups/names"><input type="hidden" name="group_id" value="{gid}">'
                     f'<span class="gs-seg" role="group" aria-label="Names in this group">'
                     f'<button type="submit" name="mode" value="full" aria-pressed="{"true" if mode == "full" else "false"}">Full names</button>'
                     f'<button type="submit" name="mode" value="first" aria-pressed="{"true" if mode == "first" else "false"}">First names</button>'
                     f'</span></form></div>')
        others = sum(1 for p in people if p["role"] != "leader")
        content = (f'<div class="gs-lead" style="margin-top:4px">{lead_cards}</div>'
                   f'<h2 style="margin:22px 0 12px">{others} {"person" if others == 1 else "people"} in the group</h2>{members}'
                   f'<p class="gs-note">{_ic("lock", 15)}<span>Only people in this group see this list. '
                   f'{"Full names" if mode == "full" else "First names"}, by the leader\'s choice; a teen always shows by first name. '
                   f'Phone numbers and emails stay hidden.</span></p>{names}')
        if not leader:
            content += (f'<form method="post" action="/my/groups" style="margin-top:8px"><input type="hidden" name="group_id" value="{gid}">'
                        f'<input type="hidden" name="action" value="leave"><button class="gs-mini warn" type="submit">Leave this group</button></form>')
    else:
        import group_study
        parts = []
        st = data.get("study")
        if leader:
            parts.append(_requests_block(data.get("requests") or [], g))
            if st and st.get("study") and not st["study"].get("posted_at"):
                parts.append(group_study.render(g, st, leader=True, people=people,
                                                next_day=(data.get("meet") or {}).get("next"), ic=_ic, esc=_e,
                                                name=lambda p: display_name(p, g.get("name_display") or "full")))
        pinned = [p for p in posts if p.get("pinned") and not p.get("church")]
        church_new = [p for p in posts if p.get("church") and not p.get("i_acked")][:1]
        for p in (pinned[:1] + church_new):
            parts.append(_post_card(p, g, leader=leader, me_id=me_id, size=size, back=back))
        when = " · ".join(_e(x) for x in (g.get("meets"), g.get("location")) if x)
        nxt = (data.get("meet") or {}).get("next")
        bring = ""
        if nxt:
            import group_bring
            import group_gatherings
            going = sum(1 for a in ((data.get("meet") or {}).get("rsvps") or {}).values() if a == "going")
            when = _e(group_gatherings.when_text(g, nxt)) + (f" · {going} going" if going else "")
            items = ((data.get("meet") or {}).get("bring") or {}).get(nxt.isoformat()) or []
            if items:
                left = group_bring.still_open(items, {p["id"] for p in people})
                bring = (f'<a class="gs-mini" href="{_base(g["id"], "meet")}">{_ic("utensils", 15)}'
                         f'Bring something · {group_bring.open_label(left)}</a>')
        live = data.get("live") or {}
        meet = ""
        if live:
            label = "Join the video meeting" if live.get("status") == "live" or data.get("host") else "Video starting: waiting for leaders"
            meet = f'<a class="gs-btn tint sm" href="/my/groups/live/{_e(live["id"])}">{_ic("video", 15)}{label}</a>'
        elif data.get("host"):
            meet = (f'<form method="post" action="/my/groups/live/start"><input type="hidden" name="group_id" value="{gid}">'
                    f'<input type="hidden" name="mode" value="meeting">'
                    f'<button class="gs-btn soft sm" type="submit">{_ic("video", 15)}Open a video room</button></form>')
        if when or meet:
            parts.append(f'<section class="gs-card" aria-label="When we meet"><div class="gs-meet">'
                         f'<span class="gs-disc coral">{_ic("calendar", 20)}</span><span class="gs-t"><b>When we meet</b>'
                         f'<span>{when or "Your leaders will share the next time"}</span></span>'
                         f'<a class="gs-mini" href="{_base(g["id"], "meet")}">{"Are you coming?" if nxt else "Open"}</a></div>'
                         f'{bring}{f"<div class=gs-acts>{meet}</div>" if meet else ""}</section>')
        latest = [p for p in posts if p not in pinned and p not in church_new][:2]
        if latest:
            parts.append(f'<div class="mb-sh"><h2>From the Board</h2><a href="{_base(g["id"], "board")}">See all</a></div>')
            parts.extend(_post_card(p, g, leader=leader, me_id=me_id, size=size, back=back) for p in latest)
        elif not pinned and not church_new:
            parts.append(f'<p class="gs-empty">Nothing on the Board yet.'
                         f'{" Post the first word to your group." if leader else " When a leader posts, it shows here."}</p>')
        doors = []
        if leader:
            doors.append(f'<a class="gs-row" href="{_base(g["id"], "board")}#post"><span class="gs-disc">{_ic("megaphone", 20)}</span>'
                         f'<span class="gs-t"><b>Post to the Board</b><span>Everyone in the group sees it</span></span>{_ic("chevron", 18)}</a>')
        if chat:
            doors.append(f'<a class="gs-row" href="{_base(g["id"], "chat")}"><span class="gs-disc violet">{_ic("chat", 20)}</span>'
                         f'<span class="gs-t"><b>Group chat</b><span>Talk with everyone in the group</span></span>{_ic("chevron", 18)}</a>')
        study_line = group_study.home_line(g, st, _ic, _e, _base(g["id"], "meet"))
        if study_line:
            doors.append(study_line)
        doors.append(f'<a class="gs-row" href="{_base(g["id"], "prayer")}"><span class="gs-disc coral">{_ic("hand-heart", 20)}</span>'
                     f'<span class="gs-t"><b>Prayer wall</b><span>Carry each other in prayer</span></span>{_ic("chevron", 18)}</a>')
        doors.append(f'<a class="gs-row" href="{_base(g["id"], "people")}"><span class="gs-disc gold">{_ic("users", 20)}</span>'
                     f'<span class="gs-t"><b>People</b><span>{size} in the group</span></span>{_ic("chevron", 18)}</a>')
        parts.append(f'<div class="mb-sh"><h2>In the group</h2></div><div class="gs-list">{"".join(doors)}</div>')
        if not chat and g.get("chat_on") is not False:
            parts.append(f'<p class="gs-note">{_ic("chat", 15)}<span>The group chat opens when '
                         f'{_e(biz.get("name") or "the church")} turns on messaging.</span></p>')
        content = "".join(parts)
    page = f'<a class="mb-back" href="/my/groups">Connect</a>{hero}{tabs}{flash}<div style="margin-top:16px">{content}</div>'
    import group_bring
    import group_gatherings
    import group_prayer
    import group_study
    import group_chat_notify
    import group_post_later
    return _shell(biz, site, g.get("name") or "Group",
                  f"<style>{GROUP_CSS}{CHAT_CSS}{group_prayer.PRAYER_CSS}{group_gatherings.MEET_CSS}{group_bring.BRING_CSS}{group_study.STUDY_CSS}{group_chat_notify.CONTROL_CSS}{group_post_later.LATER_CSS}</style>{page}",
                  tab="connect", who=me, script=script), 200


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str) -> Tuple[str, int]:
    """GET /my/groups/<id>[/board|/people]."""
    import asyncio
    rest = sub[len("/my/groups/"):].strip("/")
    if rest == "leaders":
        return render_room(biz, site, request, me, await asyncio.to_thread(room_view, biz, me))
    gid, _, tab = rest.partition("/")
    if not UUID.match(gid) or tab not in TABS:
        return render(biz, site, request, me, {}, "")
    data = await asyncio.to_thread(space, str(biz["id"]), gid, me, tab=tab)
    if data and data.get("role") and tab == "chat":
        data["chat"] = await asyncio.to_thread(chat_view, biz, data["group"], me)
    if data and data.get("role") and tab in ("", "meet"):
        import group_gatherings
        data["meet"] = await asyncio.to_thread(group_gatherings.view, biz, data["group"], str(me["id"]), data["people"])
        import group_study
        data["study"] = await asyncio.to_thread(group_study.view, biz, data["group"], leader=data.get("role") == "leader")
    if data and data.get("role") and tab == "prayer":
        import group_prayer
        data["prayer"] = await asyncio.to_thread(group_prayer.wall, str(biz["id"]), gid, str(me["id"]),
                                                 answered=request.query_params.get("view") == "answered")
    if data and data.get("role") and tab in ("", "board"):
        shown = data.get("posts") or []
        if tab == "":
            shown = [p for p in shown if (p.get("pinned") and not p.get("church"))][:1] + \
                    [p for p in shown if p.get("church") and not p.get("i_acked")][:1] + shown[:3]
        await asyncio.to_thread(mark_seen, str(biz["id"]), str(me["id"]), sorted({str(p["id"]) for p in shown}))
    return render(biz, site, request, me, data, tab)


# ─── the Chat tab ────────────────────────────────────────────────────


def chat_view(biz: Dict[str, Any], g: Optional[Dict[str, Any]], me: Dict[str, Any], *, room: bool = False) -> Dict[str, Any]:
    """What the Chat tab shows this member: {'state': off | board_only |
    gate (why) | guidelines | error | ok, ...}. Messaging's own rules decide
    who may write (birthdates, the per-person switch, teens' two adults).
    `room`: the church's All group leaders room instead of a group."""
    import member_portal_messaging as mpm
    import member_messaging_rules as rules
    biz_id = str(biz["id"])
    if not mpm.turned_on(biz):
        return {"state": "off"}
    if not room and g.get("chat_on") is False:
        return {"state": "board_only"}
    full = mpm._me_profile(biz_id, me)
    if full is None:
        return {"state": "error"}
    why = rules.why_not(full)
    if why:
        return {"state": "gate", "why": why}
    if not full.get("guidelines_at"):
        return {"state": "guidelines", "teen": rules.is_teen(full)}
    tid = mpm.ensure_leaders_thread(biz_id) if room else mpm.ensure_group_thread(biz_id, str(g["id"]))
    t = mpm.thread(biz_id, tid) if tid else None
    if not t:
        return {"state": "error"}
    acc = mpm.chat_access(biz_id, t, str(me["id"]))
    if acc is None or acc.get("role") != "member":
        return {"state": "error"}
    msgs = mpm.messages(biz_id, tid, str(me["id"]))
    looks = mpm.staff_looks(biz_id, tid)
    if msgs is None or looks is None:
        return {"state": "error"}
    rx = mpm.reactions_for(biz_id, [m["id"] for m in msgs], str(me["id"]))
    if rx is None:
        return {"state": "error"}
    mpm.mark_read(biz_id, tid, str(me["id"]))
    import group_chat_notify as gcn
    import member_push
    quiet = member_push.quiet_hour(biz)
    notify = gcn.mine(biz_id, tid, str(me["id"])) if "messages" in member_push.church_kinds(biz.get("settings")) else None
    writers = "all" if room else (g.get("chat_writers") if g.get("chat_writers") in ("all", "leaders") else "all")
    return {"state": "ok", "tid": tid, "acc": acc, "msgs": msgs, "looks": looks, "rx": rx, "writers": writers,
            "quiet": quiet, "notify": notify}


def room_view(biz: Dict[str, Any], me: Dict[str, Any]) -> Dict[str, Any]:
    """The All group leaders room for this member: {'state': not_in |
    error | ...chat_view's states, 'size'}."""
    import member_portal_messaging as mpm
    folks = mpm.leaders_room_people(str(biz["id"]))
    if folks is None:
        return {"state": "error"}
    if not any(p["contact_id"] == str(me["id"]) for p in folks):
        return {"state": "not_in"}
    return {**chat_view(biz, None, me, room=True), "size": len(folks)}


ROOM = {"id": "leaders", "name": "All group leaders", "name_display": "full"}


def render_room(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], cv: Dict[str, Any]) -> Tuple[str, int]:
    """/my/groups/leaders: (html, status)."""
    from member_portal import _e, _shell
    church = _e(biz.get("name") or "the church")
    back = '<a class="mb-back" href="/my/groups">Connect</a>'
    if cv.get("state") == "not_in":
        body = (f'{back}<div class="mb-lt"><h1>For leaders</h1></div><p class="mp-muted">This room is for the people who '
                f'lead a group at {church}, and its pastors. Find a group to join on Connect.</p>')
        return _shell(biz, site, "All group leaders", f"<style>{GROUP_CSS}</style>{body}", tab="connect", who=me), 404
    n = cv.get("size") or 0
    faces = ""
    if cv.get("state") == "ok":
        folks = cv["acc"]["people"]
        shown = sorted((p for p in folks.values() if p.get("name")), key=lambda p: str(p["name"]).lower())[:4]
        faces = f'<span class="gs-faces" aria-hidden="true">{"".join(_face(p) for p in shown)}</span>'
    hero = (f'<section class="gs-hero gs-room" aria-labelledby="gs-name"><span class="gs-scrim"></span><div class="gs-hero-in">'
            f'<span class="gs-kind">For leaders</span><h1 id="gs-name">All group leaders</h1>'
            f'<p>Everyone who leads a group at {church}, and its pastors</p>'
            f'<p class="gs-who">{faces}<span>{n} {"person" if n == 1 else "people"}</span></p></div></section>')
    content, script = _chat_body(biz, request, me, ROOM, cv, False, here="/my/groups/leaders")
    page = f'{back}{hero}{_flash(request)}<div style="margin-top:16px">{content}</div>'
    status = 503 if cv.get("state") == "error" else 200
    return _shell(biz, site, "All group leaders", f"<style>{GROUP_CSS}{CHAT_CSS}{ROOM_CSS}</style>{page}", tab="connect",
                  who=me, script=script), status


ROOM_CSS = """
.gs-room{min-height:200px;background:radial-gradient(120% 140% at 90% 0%,color-mix(in srgb,var(--teal) 45%,transparent),transparent 60%),
  linear-gradient(160deg,var(--teal-deep),var(--s1));}
"""


CHAT_CSS = """
.gc-notes{display:flex;flex-direction:column;gap:6px;margin:0 0 10px;}
.gc-note{display:flex;gap:8px;align-items:flex-start;font-size:13px;color:var(--fg3);margin:0;}
.gc-list{list-style:none;margin:0;padding:0 0 12px;display:flex;flex-direction:column;gap:12px;}
.gc-m{display:flex;align-items:flex-start;gap:8px;max-width:100%;}
.gc-m.mine{flex-direction:row-reverse;}
.gc-col{display:flex;flex-direction:column;gap:4px;min-width:0;max-width:82%;}
.gc-m.mine .gc-col{align-items:flex-end;}
.gc-who{display:flex;align-items:center;gap:6px;font-size:12.5px;font-weight:650;color:var(--fg2);padding:0 4px;}
.gc-b{margin:0;padding:9px 13px 10px;border-radius:20px;background:var(--s1);font-size:15.5px;line-height:1.38;
  white-space:pre-line;overflow-wrap:anywhere;color:var(--fg);}
.gc-m.mine .gc-b{background:var(--teal);color:var(--on-teal);}
.gc-q{display:flex;flex-direction:column;gap:1px;padding:6px 10px;border-radius:12px;background:var(--s2);font-size:13px;
  line-height:1.3;color:var(--fg2);max-width:100%;}
.gc-q b{font-size:12px;color:var(--fg);}
.gc-held{font-size:12.5px;color:var(--coral-ink,var(--fg3));padding:0 4px;}
.gc-rx{display:flex;gap:4px;flex-wrap:wrap;padding:0 2px;}
.gc-rx form,.gc-acts form{margin:0;}
.gc-chip{display:inline-flex;align-items:center;gap:4px;min-height:32px;padding:0 10px;border-radius:999px;border:0;background:var(--s2);
  color:var(--fg2);font:inherit;font-size:12.5px;font-weight:650;cursor:pointer;}
.gc-chip.on{background:var(--teal-deep);color:var(--teal-ink);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--teal-ink) 40%,transparent);}
.gc-chip .mb-ic{width:14px;height:14px;}
.gc-d{display:flex;flex-direction:column;align-items:flex-start;gap:6px;min-width:0;max-width:100%;}
.gc-m.mine .gc-d{align-items:flex-end;}
.gc-d>summary{list-style:none;cursor:pointer;}
.gc-d>summary::-webkit-details-marker{display:none;}
.gc-d>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.gc-d[open]>summary{box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 55%,transparent);}
.gc-acts{display:flex;align-items:center;gap:4px;flex-wrap:wrap;padding:6px;border-radius:999px;background:var(--s2);}
.gc-pk{min-width:38px;height:38px;padding:0 10px;border-radius:999px;border:0;display:inline-grid;place-items:center;background:none;
  color:var(--fg);font:inherit;font-size:13px;font-weight:700;cursor:pointer;box-sizing:border-box;}
.gc-pk:has(.mb-ic){padding:0;}
.gc-pk.on{background:var(--teal-deep);color:var(--teal-ink);}
.gc-pk .mb-ic{width:18px;height:18px;}
.gc-act{display:inline-flex;align-items:center;gap:4px;min-height:32px;padding:0 8px;border:0;background:none;color:var(--fg3);
  font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:none;border-radius:999px;}
.gc-act:hover{background:var(--s1);color:var(--fg2);}
.gc-act.warn{color:var(--error);}
.gc-act .mb-ic{width:15px;height:15px;}
.gc-compose{position:sticky;bottom:calc(84px + env(safe-area-inset-bottom,0px));z-index:6;margin:6px calc(var(--g) * -1) 0;
  padding:10px var(--g) 12px;background:var(--bar,var(--bg));-webkit-backdrop-filter:blur(20px);backdrop-filter:blur(20px);
  display:flex;flex-direction:column;gap:8px;}
.gc-reply{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--fg2);}
.gc-reply span{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.gc-reply a{color:var(--fg3);font-weight:600;text-decoration:none;}
.gc-row{display:flex;gap:8px;align-items:center;}
.gc-row input{flex:1;min-width:0;min-height:46px;border:0;outline:none;border-radius:23px;background:var(--s1);color:var(--fg);
  padding:0 16px;font:inherit;font-size:16px;box-shadow:inset 0 0 0 1px var(--line);}
.gc-send{width:46px;height:46px;border-radius:50%;border:0;display:grid;place-items:center;background:var(--acc-fill);color:var(--on-acc);
  cursor:pointer;flex:none;}
.gc-ah{display:flex;align-items:flex-start;gap:8px;font-size:12.5px;color:var(--fg2);line-height:1.35;cursor:pointer;}
.gc-ah input{width:20px;height:20px;margin:0;flex:none;accent-color:var(--coral,var(--acc));}
.gc-ah .mb-ic{flex:none;margin-top:2px;color:var(--coral,var(--acc));}
.gc-ah b{color:var(--fg);font-weight:650;}
.gc-ahs{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:650;color:var(--coral,var(--acc));padding:0 4px;}
.gc-safe{display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;color:var(--fg3);margin:0;}
.gc-guide{background:var(--s1);border-radius:var(--r-lg);padding:16px 18px;}
.gc-guide ul{margin:8px 0 14px;padding-left:18px;display:flex;flex-direction:column;gap:6px;font-size:14.5px;color:var(--fg2);}
"""


def _chat_body(biz: Dict[str, Any], request: Request, me: Dict[str, Any], g: Dict[str, Any], cv: Dict[str, Any],
               leader: bool, *, here: str = ""):
    """(html, script) for the Chat tab (and the leaders' room, `here`)."""
    import member_portal_messaging as mpm
    import member_messaging_rules as rules
    from member_portal import _e
    church = _e(biz.get("name") or "the church")
    gid = str(g["id"])
    here = here or _base(gid, "chat")
    state = cv.get("state")
    if state == "off":
        return f'<p class="gs-empty">This chat opens when {church} turns on messaging.</p>', ""
    if state == "board_only":
        return (f'<p class="gs-empty">{_e(g.get("name") or "This group")} uses its Board only. '
                f'<a href="{_base(gid, "board")}">Open the Board</a></p>'), ""
    if state == "gate":
        why = {"no_birthdate": f"The group chat needs your birthdate on your record. Ask {church}'s office to add it.",
               "not_enabled": f"Ask {church}'s office to turn on messaging for you, then you can join the group chat."}
        return f'<p class="gs-empty">{_e(why.get(cv.get("why"), "Messaging isn’t available to you right now."))}</p>', ""
    if state == "guidelines":
        teen = ('<li><strong>Your linked parents can read all of your chats.</strong></li>' if cv.get("teen") else "")
        return (f'<section class="gc-guide"><p style="margin:0"><strong>Before you join the chat</strong></p><ul>'
                f'<li>Be kind. No harassment, threats, or sexual content.</li>'
                f'<li>Never ask anyone for money, photos, or to move to another app.</li>'
                f'<li>Every message is checked before it’s delivered. Harmful ones are held for the church’s safety officers.</li>'
                f'<li>You can report any message. They aren’t told who reported them.</li>'
                f'<li>Staff don’t read your messages, except a safety officer reviewing a reported or held one; if that happens, '
                f'everyone in the chat is told.</li>{teen}'
                f'<li>If you or someone else is in danger, call 911. For a mental health crisis, call or text 988.</li></ul>'
                f'<form method="post" action="/my/messages/guidelines"><input type="hidden" name="back" value="{_e(here)}">'
                f'<button class="gs-btn" type="submit">I agree</button></form></section>'), ""
    if state != "ok":
        return '<p class="mp-err" role="alert">The group chat couldn’t load just now. Please try again in a moment.</p>', ""
    acc, msgs, rx, tid = cv["acc"], cv["msgs"], cv["rx"], cv["tid"]
    folks = acc["people"]
    mode = g.get("name_display") or "full"
    me_id = str(me["id"])
    notes = []
    if rules.is_teen(folks.get(me_id, {})):
        notes.append(("lock", "Your linked parents can read this chat."))
    elif acc.get("teen_in_chat"):
        notes.append(("lock", "A teen is in this chat; their linked parents can read it."))
    if cv.get("looks"):
        notes.append(("shield", "A church safety officer reviewed this chat on " + mpm._days(x["created_at"] for x in cv["looks"]) + "."))
    if msgs:
        notes.append(("chat", "Tap a message to react, reply or report it."))
    by_id = {str(m["id"]): m for m in msgs}
    reply_id = str(request.query_params.get("reply") or "")
    replying = by_id.get(reply_id) if UUID.match(reply_id) and by_id.get(reply_id, {}).get("status") == "delivered" else None
    rx_names = (("love", "heart", "Love"), ("pray", "hand-heart", "Praying"), ("amen", "", "Amen"))
    items = []
    for m in msgs:
        sid = str(m.get("sender_contact_id") or "")
        mine = sid == me_id
        person = folks.get(sid) or {}
        name = display_name(person, mode) if person else "Someone"
        face = "" if mine else _face(person, "gs-av m", mode)
        who = "" if mine else f'<span class="gc-who">{_e(name)}</span>'
        quote = ""
        if m.get("reply_to"):
            q = by_id.get(str(m["reply_to"]))
            if q and q.get("status") == "delivered":
                qn = display_name(folks.get(str(q.get("sender_contact_id") or "")) or {}, mode) or "Someone"
                quote = f'<span class="gc-q"><b>{_e(qn)}</b><span>{_e(str(q.get("body") or "")[:120])}</span></span>'
        held = ('<span class="gc-held">Held for review. Only you can see it.</span>' if m.get("status") == "held" else "")
        r = rx.get(str(m["id"])) or {}
        chips, acts = [], []
        if m.get("status") == "delivered":
            for kind, icon, label in rx_names:
                n = int(r.get(kind) or 0)
                on = kind in (r.get("mine") or set())

                def toggle(cls: str, inner: str, said: str) -> str:
                    return (f'<form method="post" action="/my/messages/{_e(tid)}/react"><input type="hidden" name="message_id" value="{_e(m["id"])}">'
                            f'<input type="hidden" name="kind" value="{kind}"><input type="hidden" name="back" value="{_e(here)}">'
                            f'<button class="{cls}{" on" if on else ""}" type="submit" aria-pressed="{"true" if on else "false"}" '
                            f'aria-label="{said}">{inner}</button></form>')
                # Under the message: the reactions it has, with counts.
                if n or on:
                    chips.append(toggle("gc-chip", (_ic(icon, 14) if icon else f"<span>{label}</span>") + f"<span>{n}</span>",
                                        f"{label}, {n}"))
                # In the picker: all three.
                acts.append(toggle("gc-pk", _ic(icon, 18) if icon else f"<span>{label}</span>", label))
            acts.append(f'<a class="gc-act" href="{_e(here)}?reply={_e(m["id"])}#gc-compose">Reply</a>')
            if not mine:
                acts.append(f'<form method="post" action="/my/messages/report"><input type="hidden" name="message_id" value="{_e(m["id"])}">'
                            f'<input type="hidden" name="back" value="{_e(here)}"><button class="gc-act" type="submit">Report</button></form>')
            if leader and not mine:
                acts.append(f'<form method="post" action="/my/messages/{_e(tid)}/hide"><input type="hidden" name="message_id" value="{_e(m["id"])}">'
                            f'<input type="hidden" name="back" value="{_e(here)}"><button class="gc-act warn" type="submit">Take down</button></form>')
        chips_html = f'<div class="gc-rx">{"".join(chips)}</div>' if chips else ""
        body = _e(m.get("body") or "")
        # Tap a message for Love / Praying / Amen, Reply, Report (and a
        # leader's Take down): the chat stays calm, like the canvas.
        bubble = (f'<details class="gc-d"><summary class="gc-b">{body}</summary><div class="gc-acts">{"".join(acts)}</div></details>'
                  if acts else f'<p class="gc-b">{body}</p>')
        rang = f'<span class="gc-ahs">{_ic("bell", 13)}After-hours alert</span>' if m.get("after_hours") else ""
        items.append(f'<li class="gc-m{" mine" if mine else ""}" id="m-{_e(m["id"])}">{face}<div class="gc-col">{who}{quote}'
                     f'{bubble}{rang}{held}{chips_html}</div></li>')
    listing = "".join(items) or '<li class="gs-empty">No messages yet. Say hello to your group.</li>'
    notes_html = "".join(f'<p class="gc-note">{_ic(i, 14)}<span>{_e(n)}</span></p>' for i, n in notes)
    can_write = bool(acc.get("can_send")) and (cv.get("writers") != "leaders" or leader)
    if can_write:
        reply_bar = ""
        reply_input = ""
        if replying:
            rn = display_name(folks.get(str(replying.get("sender_contact_id") or "")) or {}, mode) or "Someone"
            reply_bar = (f'<div class="gc-reply">{_ic("chat", 14)}<span>Replying to <b>{_e(rn)}</b>: {_e(str(replying.get("body") or "")[:80])}</span>'
                         f'<a href="{_e(here)}#gc-compose" aria-label="Cancel reply">Cancel</a></div>')
            reply_input = f'<input type="hidden" name="reply_to" value="{_e(replying["id"])}">'
        compose = (f'<form class="gc-compose" id="gc-compose" method="post" action="/my/messages/{_e(tid)}/send">'
                   f'{reply_bar}<input type="hidden" name="back" value="{_e(here)}">{reply_input}{_alert_toggle(cv)}'
                   f'<div class="gc-row"><label class="mp-sr" for="gc-say">Message the group</label>'
                   f'<input id="gc-say" name="body" maxlength="{mpm.BODY_MAX}" autocomplete="off" required '
                   f'placeholder="Message {_e(g.get("name") or "the group")}">'
                   f'<button class="gc-send" type="submit" aria-label="Send">{_ic("send", 18)}</button></div>'
                   f'<p class="gc-safe">{_ic("shield", 13)}<span>Kind words only. Every message is checked before it’s delivered.</span></p>'
                   f'<p class="mp-err" id="gc-err" role="alert" hidden></p></form>')
    elif cv.get("writers") == "leaders":
        compose = '<p class="gs-note">Only the group’s leaders write in this chat. You can react to what they say.</p>'
    else:
        reason = {"two_adults": "This chat opens once two adult leaders of the group can message.",
                  "no_birthdate": "Messaging needs your birthdate on your record.",
                  "not_enabled": "Ask the church office to turn on messaging for you."}.get(acc.get("why"), "You can’t post here right now.")
        compose = f'<p class="gs-note">{_e(reason)}</p>'
    # New messages show up for everyone, readers of a leaders-only chat too.
    script = _chat_script(tid, len(msgs))
    # How you hear about it (group_chat_notify), when the church sends notes about messages.
    import group_chat_notify as gcn
    hear = gcn.control(tid, cv["notify"], here, _ic, _e) if cv.get("notify") else ""
    return (f'<section class="gc" aria-label="Group chat"><div class="gc-notes">{notes_html}</div>'
            f'<ul class="gc-list" id="gc-list" aria-live="polite" aria-label="Messages">{listing}</ul>{compose}{hear}</section>'), script


def _alert_toggle(cv: Dict[str, Any]) -> str:
    """Quiet hours (member_push): this message can ring through for the
    people who let after-hours alerts ring, like a late prayer call."""
    if not cv.get("quiet"):
        return ""
    return (f'<label class="gc-ah"><input type="checkbox" name="after_hours" value="1">{_ic("bell", 15)}'
            f'<span><b>After-hours alert</b> Rings through quiet hours for people who allow it, like a late prayer call. '
            f'One a night.</span></label>')


def _chat_script(tid: str, count: int) -> str:
    """Send without leaving the page; reload when something new arrives
    (messaging's own feed counts the messages this person can see), never
    while they're typing or choosing; one message's picker open at a time."""
    import json
    return f"""<script>(function(){{var f=document.getElementById('gc-compose'),err=document.getElementById('gc-err'),n={json.dumps(count)};
var l=document.getElementById('gc-list');if(l&&!location.hash){{window.scrollTo(0,document.documentElement.scrollHeight);}}
document.addEventListener('toggle',function(e){{var d=e.target;if(!d.classList||!d.classList.contains('gc-d')||!d.open)return;
document.querySelectorAll('details.gc-d[open]').forEach(function(o){{if(o!==d)o.open=false;}});}},true);
function poll(){{if(document.activeElement&&document.activeElement.id==='gc-say'&&document.activeElement.value)return;
if(document.querySelector('details.gc-d[open]'))return;
fetch('/my/messages/feed/{tid}',{{credentials:'same-origin',headers:{{'Accept':'application/json'}}}})
.then(function(r){{return r.json();}}).then(function(d){{if(d&&typeof d.count==='number'&&d.count!==n)location.replace(location.pathname);}}).catch(function(){{}});}}
setInterval(poll,6000);
if(f){{f.addEventListener('submit',function(e){{e.preventDefault();var i=document.getElementById('gc-say'),t=i.value.trim();if(!t)return;
var b=f.querySelector('.gc-send');b.disabled=true;err.hidden=true;var body=new URLSearchParams(new FormData(f));
fetch(f.getAttribute('action'),{{method:'POST',credentials:'same-origin',headers:{{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'}},body:body.toString()}})
.then(function(r){{return r.json().then(function(d){{return {{ok:r.ok,d:d}};}});}}).then(function(x){{b.disabled=false;
if(x.ok){{i.value='';var ah=f.querySelector('input[name=after_hours]');if(ah)ah.checked=false;if(x.d.care){{location.href=location.pathname+'?done=care';return;}}location.replace(location.pathname);}}else{{err.textContent=x.d.error||'That didn\'t send. Please try again.';err.hidden=false;}}}})
.catch(function(){{b.disabled=false;err.textContent='That didn\'t send. Please try again.';err.hidden=false;}});}});}}
}})();</script>"""


# ─── routes ──────────────────────────────────────────────────────────

_BACK_RE = re.compile(r"^(/my/groups(/[0-9a-fA-F-]{36}(/(board|people|prayer|meet))?)?|/my/lead/groups(/[0-9a-fA-F-]{36})?)$")


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if not _BACK_RE.match(target or ""):
        target = "/my/groups"
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


async def _who(request: Request, back: str):
    """(church, me, form) for a POST, or a redirect when it can't go ahead."""
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return None, None, None, _go(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return None, None, None, mpc._back("/my")
    if not mpc._allowed(church, me):
        return None, None, None, _go(back, err="slow")
    form = await request.form()
    return church, me, form, None


def _gid(form) -> str:
    v = str(form.get("group_id") or "")
    return v if UUID.match(v) else ""


@router.post("/my/groups/ask", include_in_schema=False)
async def ask_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    ok, code = await asyncio.to_thread(ask, church["business"], me, gid)
    if code == "joined":
        return _go(_base(gid), done="joined")
    return _go(_base(gid) if ok or code in ("group_full",) else "/my/groups", **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/withdraw", include_in_schema=False)
async def withdraw_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    ok, code = await asyncio.to_thread(withdraw, church["business"]["id"], me, gid)
    return _go(_base(gid) if gid else "/my/groups", **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/answer", include_in_schema=False)
async def answer_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    yes = str(form.get("yes") or "") == "1"
    ok, code, gid = await asyncio.to_thread(answer, church["business"], me, str(form.get("id") or ""), yes)
    back = str(form.get("back") or "")
    target = back if back.startswith("/my/lead/") and _BACK_RE.match(back) else (_base(gid) if gid else "/my/groups")
    return _go(target, **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/post", include_in_schema=False)
async def post_route(request: Request):
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    ok, code = await create_post(church["business"], me, gid, str(form.get("title") or ""), str(form.get("body") or ""),
                                 str(form.get("pin") or "") == "1", str(form.get("ack") or "") == "1",
                                 str(form.get("after_hours") or "") == "1", str(form.get("email") or "") == "1",
                                 str(form.get("send_at") or ""))
    return _go(_base(gid, "board"), **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/post/now", include_in_schema=False)
async def post_now_route(request: Request):
    """A scheduled post, out now (group_post_later)."""
    import asyncio
    import group_post_later as gpl
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    pid = str(form.get("id") or "")
    if not UUID.match(pid):
        return _go("/my/groups", err="post_gone")
    ok, code, gid = await asyncio.to_thread(gpl.send_now, church["business"], me, pid)
    return _go(_base(gid, "board") if gid else "/my/groups", **({"done": code} if ok else {"err": code}))


def _back_of(form, gid: str) -> str:
    b = str(form.get("back") or "")
    return b if _BACK_RE.match(b) else (_base(gid, "board") if gid else "/my/groups")


@router.post("/my/groups/post/ack", include_in_schema=False)
async def ack_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    ok, code, gid = await asyncio.to_thread(ack, church["business"]["id"], me, str(form.get("id") or ""))
    return _go(_back_of(form, gid), **({} if ok else {"err": code}))


@router.post("/my/groups/post/remove", include_in_schema=False)
async def remove_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    ok, code, gid = await asyncio.to_thread(remove_post, church["business"]["id"], me, str(form.get("id") or ""))
    return _go(_base(gid, "board") if gid else "/my/groups", **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/post/pin", include_in_schema=False)
async def pin_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    ok, code, gid = await asyncio.to_thread(pin, church["business"]["id"], me, str(form.get("id") or ""),
                                            str(form.get("on") or "") == "1")
    return _go(_base(gid, "board") if gid else "/my/groups", **({"done": code} if ok else {"err": code}))


# ─── gatherings (group_gatherings) ───────────────────────────────────


async def _meet_action(request: Request, act):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    ok, code = await asyncio.to_thread(act, church["business"], me, gid, form)
    return _go(_base(gid, "meet"), **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/meet/rsvp", include_in_schema=False)
async def meet_rsvp_route(request: Request):
    import group_gatherings as gg
    return await _meet_action(request, lambda biz, me, gid, form: gg.rsvp(biz, me, gid, str(form.get("answer") or "")))


@router.post("/my/groups/meet/here", include_in_schema=False)
async def meet_here_route(request: Request):
    import group_gatherings as gg
    return await _meet_action(request, lambda biz, me, gid, form: gg.here(biz, me, gid))


@router.post("/my/groups/meet/roll", include_in_schema=False)
async def meet_roll_route(request: Request):
    import group_gatherings as gg

    def act(biz, me, gid, form):
        try:
            visitors = int(str(form.get("visitors") or "0") or 0)
        except ValueError:
            visitors = 0
        present = [str(x) for x in form.getlist("here") if UUID.match(str(x))]
        return gg.roll(biz, me, gid, present, visitors, str(form.get("note") or ""))
    return await _meet_action(request, act)


@router.post("/my/groups/meet/schedule", include_in_schema=False)
async def meet_schedule_route(request: Request):
    import group_gatherings as gg
    return await _meet_action(request, lambda biz, me, gid, form: gg.set_schedule(
        biz, me, gid, str(form.get("day") or ""), str(form.get("time") or ""), str(form.get("address") or ""),
        str(form.get("note") or ""), str(form.get("every") or "1"), str(form.get("first") or "")))


@router.post("/my/groups/meet/skip", include_in_schema=False)
async def meet_skip_route(request: Request):
    import group_gatherings as gg
    return await _meet_action(request, lambda biz, me, gid, form: gg.skip(
        biz, me, gid, str(form.get("day") or ""), str(form.get("on") or "") == "1"))


# Bring something (group_bring).

@router.post("/my/groups/meet/bring/add", include_in_schema=False)
async def meet_bring_add_route(request: Request):
    import group_bring
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    ok, code = await group_bring.add(church["business"], me, gid, str(form.get("day") or ""), str(form.get("what") or ""))
    return _go(_base(gid, "meet"), **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/chat/notify", include_in_schema=False)
async def chat_notify_route(request: Request):
    """Every message / Evening summary / Off, for one group chat or the
    leaders room (group_chat_notify)."""
    import asyncio
    import group_chat_notify as gcn
    import member_portal_church as mpc
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    back = str(form.get("back") or "/my/groups")
    tid = str(form.get("thread") or "")
    if not UUID.match(tid):
        return mpc._back(back, err="gone_chat")
    ok, code = await asyncio.to_thread(gcn.choose, church["business"], me, tid, str(form.get("level") or ""))
    return mpc._back(back, **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/meet/study", include_in_schema=False)
async def meet_study_route(request: Request):
    import group_study
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    sid = str(form.get("study") or "")
    if not UUID.match(sid):
        return _go(_base(gid, "meet"), err="study_gone")
    edited = [str(q) for q in form.getlist("q")] if str(form.get("edited") or "") == "1" else None
    ok, code = await group_study.post(church["business"], me, gid, sid, edited)
    return _go(_base(gid, "meet"), **({"done": code} if ok else {"err": code}))


def _bring_item(form) -> str:
    item = str(form.get("item") or "")
    return item if UUID.match(item) else ""


@router.post("/my/groups/meet/bring/claim", include_in_schema=False)
async def meet_bring_claim_route(request: Request):
    import group_bring
    return await _meet_action(request, lambda biz, me, gid, form: group_bring.claim(biz, me, gid, _bring_item(form))
                              if _bring_item(form) else (False, "bring_gone"))


@router.post("/my/groups/meet/bring/undo", include_in_schema=False)
async def meet_bring_undo_route(request: Request):
    import group_bring
    return await _meet_action(request, lambda biz, me, gid, form: group_bring.unclaim(biz, me, gid, _bring_item(form))
                              if _bring_item(form) else (False, "bring_gone"))


@router.post("/my/groups/meet/bring/remove", include_in_schema=False)
async def meet_bring_remove_route(request: Request):
    import group_bring
    return await _meet_action(request, lambda biz, me, gid, form: group_bring.remove(biz, me, gid, _bring_item(form))
                              if _bring_item(form) else (False, "bring_gone"))


# ─── the prayer wall (group_prayer) ──────────────────────────────────


@router.post("/my/groups/prayer", include_in_schema=False)
async def prayer_route(request: Request):
    import asyncio
    import group_prayer
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    biz = church["business"]
    g = await asyncio.to_thread(group_row, str(biz["id"]), gid)
    inside = await asyncio.to_thread(_is_member, str(biz["id"]), gid, me["id"]) if g else False
    if g is None or inside is None:
        return _go(_base(gid, "prayer"), err="error")
    if not g or not inside:
        return _go(_base(gid), err="not_in_group")
    ok, code = await group_prayer.ask(biz, me, g, str(form.get("body") or ""), str(form.get("to") or "") == "pastors")
    return _go(_base(gid, "prayer"), **({"done": code} if ok else {"err": code}))


async def _prayer_action(request: Request, act):
    """The shared shape of mark / answer / remove: back to the wall."""
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    biz_id = str(church["business"]["id"])
    ok, code, gid = await asyncio.to_thread(act, church["business"], biz_id, me, form)
    back = _base(gid, "prayer") if UUID.match(gid or "") else "/my/groups"
    if ok and str(form.get("view") or "") == "answered" and UUID.match(gid or ""):
        back = _base(gid, "prayer")
    return _go(back, **({"done": code} if ok else {"err": code}))


@router.post("/my/groups/prayer/mark", include_in_schema=False)
async def prayer_mark_route(request: Request):
    import group_prayer
    return await _prayer_action(request, lambda biz, biz_id, me, form: group_prayer.mark(
        biz, me, str(form.get("id") or ""), str(form.get("kind") or ""),
        lambda gid: _is_member(biz_id, gid, me["id"])))


@router.post("/my/groups/prayer/answer", include_in_schema=False)
async def prayer_answer_route(request: Request):
    import group_prayer
    return await _prayer_action(request, lambda biz, biz_id, me, form: group_prayer.answer(
        biz_id, me, str(form.get("id") or ""), str(form.get("praise") or "")))


@router.post("/my/groups/prayer/remove", include_in_schema=False)
async def prayer_remove_route(request: Request):
    import group_prayer
    return await _prayer_action(request, lambda biz, biz_id, me, form: group_prayer.remove(
        biz_id, me, str(form.get("id") or ""), lambda gid: _is_leader(biz_id, gid, me["id"])))


@router.post("/my/groups/names", include_in_schema=False)
async def names_route(request: Request):
    import asyncio
    church, me, form, stop = await _who(request, "/my/groups")
    if stop:
        return stop
    gid = _gid(form)
    if not gid:
        return _go("/my/groups", err="group_gone")
    ok, code = await asyncio.to_thread(set_names, church["business"]["id"], me, gid, str(form.get("mode") or ""))
    return _go(_base(gid, "people"), **({"done": code} if ok else {"err": code}))
