"""church_leader_tasks.py — My tasks, for the church's leaders who have no
office login.

Kevin, 2026-10-27: "yes build my tasks for leaders". A church's office
logins are few and cost money, and each one reads every member record, so
its leaders (elders, overseers, the worship pastor, the youth pastor, the
intercessor leader, team leaders) work from the member app's Lead tab on
their phone. Until now a task could only be handed to an office login
(tasks.assigned_to), so a Board decision like "the youth pastor plans the
fall retreat by Nov 15" couldn't be handed to the youth pastor. Now it can
(tasks.assigned_contact_id, supabase/APPLY-2026-10-27-leader-tasks.sql):

  Who .......... everyone in the All group leaders room
                 (member_portal_messaging.leaders_room_people): every group
                 leader and every role that leads. The office's Hand to list
                 gets them by name and role title, never an email
                 (GET /church/my-week/people, `leaders`).
  The leader ... the Lead tab's Tasks (/my/lead/tasks, member_portal_lead):
                 their open tasks, late first, then by due date, each with
                 its notes and when it's due in the church's words, and Done
                 (POST /my/lead/tasks/<id>/done), which marks it done and
                 records who. Every read and write is checked against the
                 church and their own contact id: anyone else's is a 404.
  Told ......... the office writes tasks straight to the database, so the
                 hourly sweep (sweep_tick) finds a new hand-off
                 (leader_told_at null) and emails the leader once, through
                 the leaders note's path (email_layout + Resend, the
                 church's identity, a key per task). leader_told_at is
                 claimed before the send, so two replicas never both send,
                 and let go when the send fails. No email on file: told
                 anyway; the Lead tab still shows it. No member push: no
                 member_push kind fits a task.
  Late ......... the same sweep, in the church's morning (8 to noon on its
                 own clock): an open task whose due date has passed, and
                 whose leader was told before today, goes up once to whoever
                 the leader answers to (church_roles.chain_above from the
                 roles they hold, an empty role passed over; one email per
                 leader for all their newly late tasks). late_told_at is
                 claimed the same way. A leader who holds no role with anyone
                 above them (a group leader only) has no one to go up to: it
                 goes back to whoever handed it out (tasks.handed_by, stamped
                 by the database, APPLY-2026-10-27-task-handed-by.sql). With
                 no one to tell, late_told_at is set so it's never asked
                 again. A done task is never told about.
  Who handed it  handed_by names the login on the leader's page and in their
                 email ("From Sarah"), by the Hand to list's own names
                 (church_my_week.people); else "the church office".
  The Board .... church_board.make_tasks hands a follow-up whose member has
                 no login but is one of the church's people by their contact.

Switched by CHURCH_LEADER_TASKS: off | owner | on. Owner (the default): the
platform owner's office alone, and on the member side and in the sweep, the
platform owner's own church (member_asks.platform_church). The sweep runs on
the worker, so switching on means setting it on both Railway services.

Before the migration every read here fails quietly: no leaders in the list,
no Tasks section, no sweep. Never a 500 on a page that already worked.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients
from auth_supabase import AuthedUser

logger = logging.getLogger(__name__)

OPEN_MAX = 100                  # a leader's open tasks, read at once
DONE_DAYS = 30                  # done ones, folded under the list
DONE_SHOWN = 10
NOTES_MAX = 1500                # a task's notes, as the page and the email show them
LATE_FROM, LATE_UNTIL = 8, 12   # the church's morning: when "past due" goes up
SWEEP_MAX = 500                 # tasks one sweep takes on
NOT_YOURS = "That task isn’t handed to you."
TASK_FIELDS = ("id,business_id,title,description,status,due_date,assigned_contact_id,leader_told_at,"
               "late_told_at,done_by_contact_id,completed_at,created_at,handed_by")
# Both migrations' columns: APPLY-2026-10-27-leader-tasks.sql, then
# APPLY-2026-10-27-task-handed-by.sql (who handed it).
NEW_COLUMNS = "assigned_contact_id,leader_told_at,late_told_at,done_by_contact_id,handed_by"
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_LEADER_TASKS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    """The office side (Hand to's Leaders, the Board's tasks), for this login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


def church_open(business_id: Any) -> bool:
    """The member side and the sweep, for this church: on, or (owner) the
    platform owner's own church. Nobody signs in there as a login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _chunks(ids: Iterable[Any], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _email_ok(v: Any) -> str:
    e = str(v or "").strip()
    return e if "@" in e and " " not in e else ""


def first_name(name: str) -> str:
    return (_plain(name).split(" ") or [""])[0] or "friend"


def day_words(d: date) -> str:
    """'Friday, November 13' (an email is read on another day)."""
    return f"{d:%A}, {d:%B} {d.day}"


def due_words(due: Any, today: date) -> Dict[str, str]:
    """When a task is due, said the way the church would say it on the
    leader's page: '2 days late', 'Due today', 'Due tomorrow', 'Due
    Friday, Nov 13'. `state` is late, soon or ''."""
    d = _day(due)
    if not d:
        return {"text": "No due date", "state": ""}
    gap = (d - today).days
    if gap < 0:
        return {"text": f"{-gap} day{'s' if gap != -1 else ''} late", "state": "late"}
    if gap == 0:
        return {"text": "Due today", "state": "soon"}
    if gap == 1:
        return {"text": "Due tomorrow", "state": "soon"}
    return {"text": f"Due {d:%A}, {d:%b} {d.day}", "state": ""}


def ready(business_id: Any) -> bool:
    """The migration's columns answer (one probe, the task table's own)."""
    return _rows(f"/tasks?business_id=eq.{_q(business_id)}&select={NEW_COLUMNS}&limit=1") is not None


def zone(business: Dict[str, Any]):
    """The church's clock, as the leaders note and Sunday Planning read it.
    None when it can't be read: nothing goes up on a guessed clock."""
    import group_gatherings
    return group_gatherings.zone(business)


def _contacts(biz_id: str, ids: Iterable[Any]) -> Optional[Dict[str, Dict[str, str]]]:
    out: Dict[str, Dict[str, str]] = {}
    for chunk in _chunks(ids):
        rows = _rows(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(i) for i in chunk)})"
                     "&select=id,name,email&limit=200")
        if rows is None:
            return None
        for r in rows:
            out[str(r["id"])] = {"name": _plain(r.get("name")) or "Someone", "email": _email_ok(r.get("email"))}
    return out


# ─── Who handed it ────────────────────────────────────────────────────

# The Hand to list's stand-ins when a login has no name: "the church office"
# reads better to a leader.
_NO_NAME = {"The owner", "An office login"}


def handers(business: Dict[str, Any], ids: Iterable[Any]) -> Dict[str, str]:
    """Who handed these tasks out, by the Hand to list's own names
    (church_my_week.people: their name on the church's list, never an
    email). {} when no login handed them, or the names can't be read: the
    leader then sees "the church office"."""
    want = {str(i) for i in ids if i}
    if not want:
        return {}
    biz = business
    if not business.get("owner_id") or not isinstance(business.get("settings"), dict):
        rows = _rows(f"/businesses?id=eq.{_q(business['id'])}&select=id,name,type,settings,owner_id&limit=1")
        if not rows:
            return {}
        biz = rows[0]
    import church_my_week
    try:
        people = church_my_week.people(biz, "")
    except HTTPException:
        return {}
    return {str(p["user_id"]): _plain(p.get("name")) for p in people
            if str(p.get("user_id")) in want and _plain(p.get("name")) and p.get("name") not in _NO_NAME}


def hander_email(biz: Dict[str, Any], user_id: str) -> str:
    """The sign-in email of whoever handed a task out: the owner's from
    Auth, a login's from its seat. "" when they've left or it can't be read."""
    if str(user_id) == str(biz.get("owner_id") or ""):
        try:
            import messaging_router
            return _email_ok(messaging_router._owner_email(str(user_id)))
        except Exception:
            return ""
    rows = _rows(f"/business_users?business_id=eq.{_q(biz['id'])}&user_id=eq.{_q(user_id)}"
                 "&status=eq.active&select=invited_email&limit=1")
    return _email_ok(rows[0].get("invited_email")) if rows else ""


# ─── The office: who a task can be handed to ──────────────────────────

def _titles(biz_id: str, wanted: set) -> Optional[Dict[str, str]]:
    """Each leader's role title, the one ranked first in the church's
    library (a team's leader by their team: "Hospitality Team leader").
    None when the roles couldn't be read."""
    import church_follow_up as cfu
    import church_roles as cr
    rows = _rows(f"/church_leader_roles?business_id=eq.{_q(biz_id)}&status=eq.active"
                 "&select=contact_id,role,scope&limit=1000")
    defs = cr.defs(biz_id)
    if rows is None or defs is None:
        return None
    eff = cfu._effective_defs(defs, rows)
    rank = {d["key"]: n for n, d in enumerate(eff)}
    by = cr.by_key(eff)
    out: Dict[str, str] = {}
    for r in sorted(rows, key=lambda r: rank.get(str(r.get("role") or ""), 999)):
        cid = str(r.get("contact_id") or "")
        if cid not in wanted or cid in out:
            continue
        d = by.get(str(r.get("role") or "")) or {}
        scope = _plain(r.get("scope"))
        out[cid] = (f"{scope} leader" if d.get("covers") == "team" and scope
                    else d.get("title") or cr.title_of(str(r.get("role") or ""), eff))
    return out


def leaders(business_id: Any) -> Optional[List[Dict[str, Any]]]:
    """Everyone in the All group leaders room, by their own name and the
    title of a role they hold ("Group leader" when they lead a group and
    hold no role); never an email. None when the room couldn't be read."""
    import member_portal_messaging as mpm
    b = str(business_id)
    room = mpm.leaders_room_people(b)
    if room is None:
        return None
    # The office logins are in the room too (2026-11-01), but the Hand to
    # list already has them as logins: a task for one lands in their office
    # My week, not a Lead tab they don't use.
    office = mpm.office_contacts(b) or set()
    ids = sorted({str(p.get("contact_id")) for p in room if p.get("contact_id")} - office)
    if not ids:
        return []
    names: Dict[str, str] = {}
    for chunk in _chunks(ids):
        rows = _rows(f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in chunk)})"
                     "&select=id,name&limit=200")
        if rows is None:
            return None
        for r in rows:
            if _plain(r.get("name")):
                names[str(r["id"])] = _plain(r.get("name"))
    titles = _titles(b, set(ids))
    out = [{"contact_id": cid, "name": names[cid],
            "title": (titles or {}).get(cid) or ("Group leader" if titles is not None else "")}
           for cid in ids if cid in names]
    out.sort(key=lambda p: p["name"].casefold())
    return out


def hand_list(business: Dict[str, Any], user: AuthedUser) -> Optional[List[Dict[str, Any]]]:
    """The Hand to list's leaders, or None (no Leaders group): the switch is
    closed to this login, the migration isn't applied, or the room couldn't
    be read just now (the logins still stand)."""
    if not open_to(user):
        return None
    b = str(business["id"])
    if not ready(b):
        return None
    got = leaders(b)
    if got is None:
        logger.warning("leader tasks: the leaders couldn't be read for business %s", b[:8])
    return got


# ─── The leader: their own tasks ──────────────────────────────────────

def section(business: Dict[str, Any], contact_id: Any, now: Optional[datetime] = None) -> Optional[Dict[str, int]]:
    """Whether this member's Lead tab has Tasks, and how many are open:
    something handed to them that's open or done in the last month. None
    when it has none (the switch closed for the church, nothing handed, the
    migration not applied, or a read that failed)."""
    if not church_open((business or {}).get("id")):
        return None
    since = ((now or _now()) - timedelta(days=DONE_DAYS)).date().isoformat()
    rows = _rows(f"/tasks?business_id=eq.{_q(business['id'])}&assigned_contact_id=eq.{_q(contact_id)}"
                 f"&or=(status.neq.done,completed_at.gte.{since})&select=id,status&limit=200")
    if not rows:
        return None
    return {"open": sum(1 for r in rows if r.get("status") != "done")}


def _item(r: Dict[str, Any], today: date, by: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    due = due_words(r.get("due_date"), today)
    return {"id": str(r["id"]), "title": _plain(r.get("title"))[:200] or "A task",
            "notes": str(r.get("description") or "").replace("\r\n", "\n").strip()[:NOTES_MAX],
            "due": str(r.get("due_date") or "")[:10], "due_text": due["text"], "state": due["state"],
            "late": due["state"] == "late",
            "from": (by or {}).get(str(r.get("handed_by") or "")) or "the church office",
            "created_at": str(r.get("created_at") or "")}


def mine(business: Dict[str, Any], contact_id: Any, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """This leader's tasks: the open ones, late first, then by due date
    (none last), and the ones done in the last month, newest first. Only
    tasks handed to them, at this church. None when a read failed."""
    b, cid = str(business["id"]), str(contact_id)
    now = now or _now()
    mine_q = f"/tasks?business_id=eq.{_q(b)}&assigned_contact_id=eq.{_q(cid)}"
    open_rows = _rows(f"{mine_q}&status=neq.done&select={TASK_FIELDS}"
                      f"&order=due_date.asc.nullslast,created_at.asc&limit={OPEN_MAX}")
    since = _iso(now - timedelta(days=DONE_DAYS))
    done_rows = _rows(f"{mine_q}&status=eq.done&completed_at=gte.{_q(since)}&select={TASK_FIELDS}"
                      f"&order=completed_at.desc&limit={DONE_SHOWN}")
    if open_rows is None or done_rows is None:
        return None
    tz = zone(business)
    if tz is None:
        import member_portal_lead as mpl
        tz = mpl._tz(business)
    today = now.astimezone(tz).date()
    ours = lambda r: str(r.get("business_id")) == b and str(r.get("assigned_contact_id")) == cid  # noqa: E731
    by = handers(business, (r.get("handed_by") for r in open_rows if ours(r)))
    items = [_item(r, today, by) for r in open_rows if ours(r) and r.get("status") != "done"]
    items.sort(key=lambda i: (not i["late"], i["due"] or "9999-12-31", i["created_at"]))
    done = []
    for r in done_rows:
        if not ours(r) or r.get("status") != "done":
            continue
        at = _at(r.get("completed_at"))
        local = at.astimezone(tz) if at else None
        done.append({"id": str(r["id"]), "title": _plain(r.get("title"))[:200] or "A task",
                     "done_on": f"{local:%a} {local:%b} {local.day}" if local else "",
                     "at": _iso(at) if at else "", "by_me": str(r.get("done_by_contact_id") or "") == cid})
    done.sort(key=lambda d: d["at"], reverse=True)
    return {"open": items, "done": done, "today": today.isoformat()}


def mark_done(business_id: Any, contact_id: Any, task_id: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The leader marks a task handed to them done: done, when, and who.
    404 for anything not handed to them at this church; done twice is
    done once."""
    b, cid, tid = str(business_id), str(contact_id), str(task_id or "")
    if not _UUID.match(tid):
        raise HTTPException(404, NOT_YOURS)
    where = f"/tasks?id=eq.{_q(tid)}&business_id=eq.{_q(b)}&assigned_contact_id=eq.{_q(cid)}"
    rows = _rows(f"{where}&select=id,status&limit=1")
    if rows is None:
        raise HTTPException(503, "That didn’t save. Please try again.")
    if not rows:
        raise HTTPException(404, NOT_YOURS)
    if rows[0].get("status") == "done":
        return rows[0]
    got = sb_clients.sb_patch_as_service(f"{where}&status=neq.done", {
        "status": "done", "completed_at": _iso(now or _now()), "done_by_contact_id": cid})
    if not isinstance(got, list):
        raise HTTPException(503, "That didn’t save. Please try again.")
    if got:
        return got[0]
    # It moved in between: done by someone else, or handed on.
    again = _rows(f"{where}&select=id,status&limit=1")
    if again and again[0].get("status") == "done":
        return again[0]
    raise HTTPException(404, NOT_YOURS)


# ─── Telling people: the hourly sweep ─────────────────────────────────

def _tasks_link(biz_id: str) -> str:
    import church_follow_up as cfu
    origin = cfu.site_origin(biz_id)
    return f"{origin}/my/lead/tasks" if origin else ""


def _office_email(biz: Dict[str, Any]) -> Optional[str]:
    """Where a reply goes: the church office's own address (its email
    signature, else its contact email). Tasks don't record which login made
    them, so never a login's."""
    import email_layout
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    sig = email_layout.signature_of(settings)
    return _email_ok(sig.get("email") or settings.get("contact_email")) or None


def _tab_word() -> str:
    import member_app_ui
    return "Serve" if member_app_ui.serve_mode() else "Lead"


def render_email(biz: Dict[str, Any], text: str, preheader: str, link: str = "", label: str = "") -> str:
    import email_layout
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    church = _plain(biz.get("name")) or "Your church"
    return email_layout.render_html(
        text, business_name=church, brand=email_layout.brand_of(settings), sig=None, preheader=preheader[:90],
        cta=(label, link) if link and label else None,
        disclaimer=f"You’re getting this because you lead at {church}.",
        footer_note="Sent by your church office")


def deliver(biz: Dict[str, Any], to_email: str, to_name: str, subject: str, html: str, key: str,
            reply_to: Optional[str] = None) -> None:
    """One email through the app's own path (Resend, the church's identity
    where it has one). Raises when it doesn't go."""
    import email_sender
    church = _plain(biz.get("name")) or "Your church"
    asyncio.run(email_sender.send_via_resend(
        to_email=to_email, to_name=to_name or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=church, subject=subject[:150], body=html, reply_to=reply_to,
        business_id=str(biz["id"]), idempotency_key=key[:120]))


def handed_text(name: str, task: Dict[str, Any], today: Optional[date], by: str = "") -> str:
    """The leader's email, in plain words. `by`: who handed it, by name."""
    title = _plain(task.get("title")) or "A task"
    lines = [f"Hi {first_name(name)},", f"{by or 'The church office'} handed you a task: {title}."]
    d = _day(task.get("due_date"))
    if d:
        lines.append(f"It was due {day_words(d)}, so it’s already late." if today and d < today
                     else f"It’s due {day_words(d)}.")
    notes = str(task.get("description") or "").replace("\r\n", "\n").strip()[:NOTES_MAX]
    if notes:
        lines.append(f"Notes from the office:\n{notes}")
    lines.append(f"It’s on your {_tab_word()} tab in the church’s app, under Tasks. When it’s done, tap Done "
                 "there and the office will see it.")
    return "\n\n".join(lines)


def late_text(name: str, leader: str, tasks: List[Dict[str, Any]], handed: bool = False) -> str:
    """The email to the person the leader answers to, or (`handed`) to
    whoever handed the tasks out when the leader answers to no one."""
    def said(t: Dict[str, Any]) -> str:
        d = _day(t.get("due_date"))
        return f"“{_plain(t.get('title')) or 'A task'}”" + (f", due {day_words(d)}" if d else "")
    lines = [f"Hi {first_name(name)},"]
    if len(tasks) == 1:
        lines.append(f"{leader} has a task past due: {said(tasks[0])}.")
    else:
        lines.append(f"{leader} has {len(tasks)} tasks past due:\n" + "\n".join(said(t) for t in tasks))
    why = (f"You’re hearing about it because you handed {'it' if len(tasks) == 1 else 'them'} to "
           f"{first_name(leader)}, and no one is named above them in Leaders & roles. " if handed
           else f"You’re hearing about it because {first_name(leader)} answers to you. ")
    lines.append(why + "A quick, kind word is usually all it takes.")
    return "\n\n".join(lines)


def _release(biz_id: str, task_id: str, column: str, stamp: str) -> None:
    """Let a claim go (the send failed), only if it's still ours."""
    try:
        sb_clients.sb_patch_as_service(
            f"/tasks?id=eq.{_q(task_id)}&business_id=eq.{_q(biz_id)}&{column}=eq.{_q(stamp)}", {column: None})
    except Exception:
        logger.warning("leader tasks: a claim wasn't let go (task %s)", task_id[:8], exc_info=True)


def _claim(biz_id: str, t: Dict[str, Any], column: str, stamp: str) -> bool:
    """Take the task's telling for this sweep: it's still open, still the
    same leader's, and nobody has told it yet. Two replicas: one wins."""
    got = sb_clients.sb_patch_as_service(
        f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(biz_id)}&assigned_contact_id=eq.{_q(t['assigned_contact_id'])}"
        f"&{column}=is.null&status=neq.done", {column: stamp})
    return isinstance(got, list) and bool(got)


def tell_new(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    """Each task newly handed to a leader: claimed, then one email to the
    leader. No email on file: it stays told (the Lead tab shows it)."""
    b = str(biz["id"])
    people = _contacts(b, (r.get("assigned_contact_id") for r in rows))
    if people is None:
        return
    church = _plain(biz.get("name")) or "Your church"
    link = _tasks_link(b)
    reply_to = _office_email(biz)
    tz = zone(biz)
    today = now.astimezone(tz).date() if tz else None
    by = handers(biz, (r.get("handed_by") for r in rows))
    for t in rows:
        tid, cid = str(t["id"]), str(t.get("assigned_contact_id") or "")
        stamp = _iso(now)
        if not cid or not _claim(b, t, "leader_told_at", stamp):
            continue
        who = people.get(cid)
        if not who or not who["email"]:
            stats["no_email"] += 1
            continue
        try:
            html = render_email(biz, handed_text(who["name"], t, today, by.get(str(t.get("handed_by") or ""), "")),
                                f"{_plain(t.get('title'))[:80]}", link, "Open your tasks")
            deliver(biz, who["email"], who["name"], f"{church}: a task for you", html,
                    f"leader-task-{tid}-{cid}", reply_to=reply_to)
            stats["told"] += 1
        except Exception:
            logger.warning("leader tasks: a hand-off email failed (task %s)", tid[:8], exc_info=True)
            _release(b, tid, "leader_told_at", stamp)
            stats["unsent"] += 1


def overseer(leader_id: str, all_roles: List[Dict[str, Any]], defs: List[Dict[str, Any]]
             ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Who this leader answers to: from the roles they hold (the church's
    library order), the nearest role above that someone holds (an empty one
    passed over; the senior role tops every chain). (None, []) when they
    hold no role with anyone above."""
    import church_roles as cr
    held = cr.active_holders(all_roles)
    by = cr.by_key(defs)
    rank = {d["key"]: n for n, d in enumerate(defs)}
    mine_roles = sorted((r for r in all_roles if str(r.get("contact_id")) == leader_id and r.get("status") == "active"),
                        key=lambda r: rank.get(str(r.get("role") or ""), 999))
    for r in mine_roles:
        role = by.get(str(r.get("role") or ""))
        if not role:
            continue
        chain = cr.chain_above(role, defs, held, team=r.get("scope") or "", skip={leader_id})
        if chain:
            return chain[0]
    return None, []


def tell_late(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    """In the church's morning: each leader's open tasks past their due
    date (the church's day), told before today, go up once to whoever the
    leader answers to, in one email per leader. No one above them: back to
    whoever handed each out (handed_by); with no one at all, set as told,
    with nobody told."""
    import church_follow_up as cfu
    tz = zone(biz)
    if tz is None:
        return
    local = now.astimezone(tz)
    if not LATE_FROM <= local.hour < LATE_UNTIL:
        return
    today = local.date()
    midnight = datetime.combine(today, time(0), tzinfo=tz)
    due = []
    for r in rows:
        d, told = _day(r.get("due_date")), _at(r.get("leader_told_at"))
        if r.get("status") != "done" and d and d < today and told and told < midnight and r.get("assigned_contact_id"):
            due.append(r)
    if not due:
        return
    b = str(biz["id"])
    import church_roles as cr
    all_roles = cfu.roles(b)
    defs = cr.defs(b)
    if all_roles is None or defs is None:
        return  # the chain can't be read now; the next sweep tries again
    eff = cfu._effective_defs(defs, all_roles)
    by_leader: Dict[str, List[Dict[str, Any]]] = {}
    for r in sorted(due, key=lambda r: (str(r.get("due_date")), str(r.get("created_at") or ""))):
        by_leader.setdefault(str(r["assigned_contact_id"]), []).append(r)
    names = _contacts(b, by_leader)
    if names is None:
        return
    reply_to = _office_email(biz)
    for lid, tasks in by_leader.items():
        role, above = overseer(lid, all_roles, eff)
        stamp = _iso(now)
        claimed = [t for t in tasks if _claim(b, t, "late_told_at", stamp)]
        if not claimed:
            continue
        leader = (names.get(lid) or {}).get("name") or "A leader"
        if above:
            to: Dict[str, Dict[str, Any]] = {}
            for h in above:
                e = _email_ok(h.get("email"))
                if e and e.lower() not in to:
                    to[e.lower()] = {**h, "email": e}
            if not to:
                stats["late_no_email"] += len(claimed)
                continue
            _send_late(biz, leader, claimed, to, stamp, reply_to, stats)
            continue
        # No one above them: each task goes back to whoever handed it out.
        back: Dict[str, List[Dict[str, Any]]] = {}
        for t in claimed:
            back.setdefault(str(t.get("handed_by") or ""), []).append(t)
        by = handers(biz, back)
        for uid, theirs in back.items():
            e = hander_email(biz, uid) if uid else ""
            if not e:
                logger.info("leader tasks: %d late task(s) with no one above the leader and no one who handed "
                            "them out (business %s)", len(theirs), b[:8])
                stats["late_no_one"] += len(theirs)
                continue
            _send_late(biz, leader, theirs, {e.lower(): {"email": e, "name": by.get(uid, ""), "contact_id": uid}},
                       stamp, reply_to, stats, handed=True)


def _send_late(biz: Dict[str, Any], leader: str, tasks: List[Dict[str, Any]], to: Dict[str, Dict[str, Any]],
               stamp: str, reply_to: Optional[str], stats: Dict[str, int], handed: bool = False) -> None:
    """One past-due email to each of `to` for these claimed tasks; when none
    goes, the claims are let go so the next sweep tries again."""
    b = str(biz["id"])
    subject = (f"{leader} has a task past due" if len(tasks) == 1
               else f"{leader} has {len(tasks)} tasks past due")
    digest = hashlib.sha1(",".join(sorted(str(t["id"]) for t in tasks)).encode()).hexdigest()[:16]
    sent = 0
    for h in to.values():
        try:
            html = render_email(biz, late_text(h.get("name") or "", leader, tasks, handed), subject)
            deliver(biz, h["email"], h.get("name") or "", subject, html,
                    f"leader-task-late-{digest}-{h.get('contact_id')}", reply_to=reply_to)
            sent += 1
        except Exception:
            logger.warning("leader tasks: a past-due email failed (business %s)", b[:8], exc_info=True)
    if sent:
        stats["late"] += len(tasks)
    else:
        for t in tasks:
            _release(b, str(t["id"]), "late_told_at", stamp)
        stats["late_unsent"] += len(tasks)


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, on the leader replica (kmj_intake_automation): new hand-offs
    are told to their leaders; in each church's morning, late ones go up. A
    church that fails never stops the others. Quiet with the switch off or
    before the migration."""
    stats = {"churches": 0, "told": 0, "no_email": 0, "unsent": 0,
             "late": 0, "late_no_one": 0, "late_no_email": 0, "late_unsent": 0}
    if mode() == "off":
        return stats
    now = now or _now()
    fresh = _rows(f"/tasks?assigned_contact_id=not.is.null&leader_told_at=is.null&status=neq.done"
                  f"&select={TASK_FIELDS}&order=created_at.asc&limit={SWEEP_MAX}")
    if fresh is None:
        return stats  # the migration isn't applied (or the read failed): next hour
    # Every church's today is at most a day past UTC's: each one's own date decides.
    cutoff = (now.astimezone(timezone.utc).date() + timedelta(days=1)).isoformat()
    late = _rows(f"/tasks?assigned_contact_id=not.is.null&status=neq.done&late_told_at=is.null"
                 f"&leader_told_at=not.is.null&due_date=lt.{cutoff}"
                 f"&select={TASK_FIELDS}&order=due_date.asc&limit={SWEEP_MAX}") or []
    work: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for kind, rows in (("fresh", fresh), ("late", late)):
        for r in rows:
            work.setdefault(str(r.get("business_id")), {"fresh": [], "late": []})[kind].append(r)
    if not work:
        return stats
    bizs: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunks(work):
        for x in _rows(f"/businesses?id=in.({','.join(_q(i) for i in chunk)})"
                       "&select=id,name,type,settings,owner_id&limit=100") or []:
            bizs[str(x["id"])] = x
    import church_follow_up as cfu
    for b, todo in work.items():
        biz = bizs.get(b)
        if not biz or not cfu.is_church(biz) or not church_open(b):
            continue
        stats["churches"] += 1
        try:
            if todo["fresh"]:
                tell_new(biz, todo["fresh"], now, stats)
            if todo["late"]:
                tell_late(biz, todo["late"], now, stats)
        except Exception:
            logger.warning("leader tasks sweep failed for business %s", b[:8], exc_info=True)
    return stats
