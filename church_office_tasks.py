"""church_office_tasks.py — a task handed to an office login reaches them.

Love City's office checkup (Kevin, 2026-11-01): a task handed to an office
login (tasks.assigned_to, "Who sees what", 2026-10-26) landed in their My
week and nowhere else. No email, no push, and a late one went to no one.
The church's leaders already hear (church_leader_tasks); the office logins
now do too, from the same hourly sweep:

  Told ......... a new hand-off to a login (seat_told_at null) is claimed,
                 then told once: a push to their phone (operate:tasks) and an
                 email to their sign-in address, from the church, naming who
                 handed it. Handed to yourself, or a login that has left:
                 marked told, nothing sent. The email failing lets the claim
                 go, so the next sweep tries again; the push alone never
                 holds a claim (most phones have no subscription yet).
                 Where church assignments are open for the church
                 (church_over.church_open), several new hand-offs to one
                 login in one sweep (a first assignment is 5 to 9 at once)
                 are one email and one push, naming who handed them out
                 ("Jessica gave you 7 things for your first four weeks").
  Taken back ... there too, before anyone is told (Kevin, 2026-11-12:
                 "admins can not give work to elders and pastors"): the
                 Tasks screen writes tasks straight to the database, so a
                 request made by hand can hand a pastor's or an elder's
                 login a task. The sweep asks church_over.may_hand for the
                 login in handed_by; one it may not make is un-handed as the
                 board leaves one (church_leader_tasks.take_back: handed to
                 no one, the name in its title, why in its notes), nobody is
                 told it is theirs, and the login that handed it gets one
                 email and one push saying why (tell_taken_back). Who is a
                 pastor unread: left as it is for the next sweep.
  Late ......... in the church's morning (church_leader_tasks.LATE_FROM to
                 LATE_UNTIL, its own clock): an open task past its due date,
                 told before today, goes up once (seat_late_told_at) to whoever
                 handed it out (tasks.handed_by, unless it's the login itself)
                 and to the church's Executive Pastor: a login whose member
                 record holds the executive_pastor role (Kevin, 2026-11-01:
                 "Jessica will be over the admin team"). A church with no
                 Executive Pastor: its owner. One email for each person told
                 and each login's newly late tasks, and a push.

Switched with My tasks for leaders (CHURCH_LEADER_TASKS, church_leader_tasks
.mode / church_open), on the worker as well. Before
supabase/APPLY-2026-11-01-office-task-told.sql every read fails quietly and
the sweep does nothing. Never a 500 anywhere: this only sends.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger(__name__)

FIELDS = ("id,business_id,title,description,status,due_date,assigned_to,handed_by,created_at,"
          "seat_told_at,seat_late_told_at")
SWEEP_MAX = 500
OVERSEER_KEYS = ("executive_pastor",)
NAV = "operate:tasks"


def _clt():
    import church_leader_tasks
    return church_leader_tasks


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ─── Who ─────────────────────────────────────────────────────────────

def person(biz: Dict[str, Any], user_id: str, names: Dict[str, str]) -> Dict[str, str]:
    """A login (or the owner) as {user_id, email, name}: their sign-in
    email ("" when they've left) and their name on the church's list."""
    clt = _clt()
    return {"user_id": str(user_id), "email": clt.hander_email(biz, str(user_id)),
            "name": names.get(str(user_id), "")}


def overseers(biz: Dict[str, Any]) -> List[str]:
    """Who a late office task goes up to: the logins whose member record
    holds the Executive Pastor role (by its key or the catalog's; where the
    church's leaders map is open and names the roles that oversee the
    office, office_overseer_roles, one of those), else the owner. Read
    every time: [] only when the church has neither. A failed read, the
    map's too, leaves the owner, as it always has."""
    import church_map
    b = str(biz["id"])
    m = church_map.opened(biz)
    keys: Optional[List[str]] = None
    if m is None:
        keys = []           # a failed map read names nobody, as any failed read here
    elif m:
        keys = church_map.picked(m, "office_overseer_roles")
    if keys is None:
        defs = _rows(f"/church_role_defs?business_id=eq.{_q(b)}&status=eq.active&select=key,catalog_key"
                     "&limit=500") or []
        keys = sorted({str(d.get("key")) for d in defs
                       if d.get("key") in OVERSEER_KEYS or d.get("catalog_key") in OVERSEER_KEYS})
    out: List[str] = []
    if keys:
        holders = _rows(f"/church_leader_roles?business_id=eq.{_q(b)}&status=eq.active"
                        f"&role=in.({','.join(_q(k) for k in keys)})&select=contact_id&limit=50") or []
        ids = sorted({str(h["contact_id"]) for h in holders if h.get("contact_id")})
        if ids:
            contacts = _rows(f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in ids)})"
                             "&select=id,email&limit=50") or []
            emails = {str(c.get("email") or "").strip().lower() for c in contacts if c.get("email")}
            seats = _rows(f"/business_users?business_id=eq.{_q(b)}&status=eq.active"
                          "&select=user_id,contact_id,invited_email&limit=200") or []
            for s in seats:
                if not s.get("user_id"):
                    continue
                if (s.get("contact_id") and str(s["contact_id"]) in ids) or \
                        str(s.get("invited_email") or "").strip().lower() in emails:
                    out.append(str(s["user_id"]))
    if not out and biz.get("owner_id"):
        out = [str(biz["owner_id"])]
    return sorted(set(out))


# ─── Words ───────────────────────────────────────────────────────────

def _link(biz_id: str) -> str:
    import app_base
    try:
        import office_door
        path = office_door.path_for(biz_id) or ""
    except Exception:
        path = ""
    return app_base.app_base_url() + path


def handed_text(name: str, task: Dict[str, Any], today: Optional[date], by: str = "") -> str:
    clt = _clt()
    title = clt._plain(task.get("title")) or "A task"
    lines = [f"Hi {clt.first_name(name) or 'there'},", f"{by or 'The church office'} handed you a task: {title}."]
    d = clt._day(task.get("due_date"))
    if d:
        lines.append(f"It was due {clt.day_words(d)}, so it’s already late." if today and d < today
                     else f"It’s due {clt.day_words(d)}.")
    notes = str(task.get("description") or "").replace("\r\n", "\n").strip()[:clt.NOTES_MAX]
    if notes:
        lines.append(f"Notes:\n{notes}")
    lines.append("It’s on your My week and in Tasks. Mark it done there when it’s finished.")
    return "\n\n".join(lines)


def late_text(name: str, who: str, tasks: List[Dict[str, Any]], why: str) -> str:
    clt = _clt()

    def said(t: Dict[str, Any]) -> str:
        d = clt._day(t.get("due_date"))
        return f"“{clt._plain(t.get('title')) or 'A task'}”" + (f", due {clt.day_words(d)}" if d else "")
    lines = [f"Hi {clt.first_name(name) or 'there'},"]
    if len(tasks) == 1:
        lines.append(f"{who} has a task past due: {said(tasks[0])}.")
    else:
        lines.append(f"{who} has {len(tasks)} tasks past due:\n" + "\n".join(said(t) for t in tasks))
    lines.append(why + " A quick, kind word is usually all it takes.")
    return "\n\n".join(lines)


def render(biz: Dict[str, Any], text: str, preheader: str, link: str = "", label: str = "") -> str:
    import email_layout
    clt = _clt()
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    church = clt._plain(biz.get("name")) or "Your church"
    return email_layout.render_html(
        text, business_name=church, brand=email_layout.brand_of(settings), sig=None, preheader=preheader[:90],
        cta=(label, link) if link and label else None,
        disclaimer=f"You’re getting this because you work in {church}’s office.",
        footer_note="Sent by your church office")


def _push(user_id: str, biz_id: str, title: str, body: str, tag: str, nav: str = NAV) -> None:
    try:
        import push_notifications
        push_notifications.send_to_user(user_id, title=title[:80], body=body[:160], nav=nav, tag=tag[:60],
                                        business_id=biz_id)
    except Exception:
        logger.info("office tasks: a push didn't go (business %s)", biz_id[:8], exc_info=True)


# ─── The sweep ───────────────────────────────────────────────────────

def _claim(biz_id: str, t: Dict[str, Any], column: str, stamp: str) -> bool:
    """Take this task's telling: still open, still the same login's, and
    nobody has told it yet. Two replicas: one wins."""
    got = sb_clients.sb_patch_as_service(
        f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(biz_id)}&assigned_to=eq.{_q(t['assigned_to'])}"
        f"&{column}=is.null&status=neq.done", {column: stamp})
    return isinstance(got, list) and bool(got)


def tell_new(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    """Each new hand-off to a login, told once. Where church assignments are
    open for the church (church_over.church_open), a login handed several in
    one sweep (a first assignment is 5 to 9 at once) gets one email and one
    push for all of them, naming who handed them out; one alone is told as
    before. There too, a hand-off to a pastor or an elder that its login may
    not make is taken back before anyone is told
    (church_leader_tasks.take_back)."""
    clt = _clt()
    b = str(biz["id"])
    # First, a hand-off its login may not make (a pastor's or an elder's,
    # from an office seat) is taken back, and nobody is told it is theirs.
    rows = clt.take_back(biz, rows, "assigned_to", "seat_told_at", stats, "office_")
    if not rows:
        return
    tz = clt.zone(biz)
    w = {"church": clt._plain(biz.get("name")) or "Your church", "today": now.astimezone(tz).date() if tz else None,
         "names": clt.handers(biz, {str(r.get("assigned_to")) for r in rows} | {str(r.get("handed_by") or "") for r in rows}),
         "link": _link(b), "reply_to": clt._office_email(biz)}
    import church_over
    grouped = church_over.church_open(b)
    by_login: Dict[str, List[Dict[str, Any]]] = {}
    for t in rows:
        by_login.setdefault(str(t.get("assigned_to") or ""), []).append(t)
    for uid, tasks in by_login.items():
        if not uid:
            continue
        if grouped and len(tasks) > 1:
            _tell_group(biz, uid, tasks, now, stats, w)
            continue
        for t in tasks:
            stamp = _iso(now)
            if not _claim(b, t, "seat_told_at", stamp):
                continue
            if str(t.get("handed_by") or "") == uid:
                stats["office_self"] += 1
                continue
            _tell_one(biz, uid, t, stamp, stats, w)


def _tell_one(biz: Dict[str, Any], uid: str, t: Dict[str, Any], stamp: str, stats: Dict[str, int],
              w: Dict[str, Any]) -> None:
    """One claimed hand-off: its email and push, as the sweep always sent it."""
    clt = _clt()
    b, tid = str(biz["id"]), str(t["id"])
    names = w["names"]
    who = person(biz, uid, names)
    if not who["email"]:
        stats["office_no_email"] += 1
        return
    by = names.get(str(t.get("handed_by") or ""), "")
    title = clt._plain(t.get("title")) or "A task"
    try:
        html = render(biz, handed_text(who["name"], t, w["today"], by), title[:80], w["link"], "Open your tasks")
        clt.deliver(biz, who["email"], who["name"], f"{w['church']}: a task for you", html,
                    f"office-task-{tid}-{uid}", reply_to=w["reply_to"])
    except Exception:
        logger.warning("office tasks: a hand-off email failed (task %s)", tid[:8], exc_info=True)
        clt._release(b, tid, "seat_told_at", stamp)
        stats["office_unsent"] += 1
        return
    _push(uid, b, "A task for you", f"{by + ': ' if by else ''}{title}", f"task-{tid}")
    stats["office_told"] += 1


def _tell_group(biz: Dict[str, Any], uid: str, tasks: List[Dict[str, Any]], now: datetime, stats: Dict[str, int],
                w: Dict[str, Any]) -> None:
    """Several new hand-offs to one login in one sweep: each claimed, then
    one email and one push for all of them ("Jessica gave you 7 things for
    your first four weeks"). Handed to yourself: told, nothing sent. The
    email failing lets every claim it carried go, so the next sweep tries
    again."""
    import church_assignments as cas
    clt = _clt()
    b = str(biz["id"])
    stamp = _iso(now)
    claimed = [t for t in tasks if _claim(b, t, "seat_told_at", stamp)]
    send = [t for t in claimed if str(t.get("handed_by") or "") != uid]
    stats["office_self"] += len(claimed) - len(send)
    if len(send) <= 1:
        for t in send:
            _tell_one(biz, uid, t, stamp, stats, w)
        return
    who = person(biz, uid, w["names"])
    if not who["email"]:
        stats["office_no_email"] += len(send)
        return
    startup = cas.startup_of(b, [t["id"] for t in send])
    first = all(str(t["id"]) in startup for t in send)
    by = [w["names"].get(h, "") for h in dict.fromkeys(str(t.get("handed_by") or "") for t in send)]
    what, text, push = cas.grouped_text(who["name"], by, send, w["today"], first,
                                        "They’re on your My week. Mark each one done there when it’s finished.")
    key = cas.digest(t["id"] for t in send)
    try:
        html = render(biz, text, what[:80], w["link"], "Open My week")
        clt.deliver(biz, who["email"], who["name"], f"{w['church']}: {what}", html, f"office-tasks-{key}-{uid}",
                    reply_to=w["reply_to"])
    except Exception:
        logger.warning("office tasks: a grouped hand-off email failed (business %s)", b[:8], exc_info=True)
        for t in send:
            clt._release(b, str(t["id"]), "seat_told_at", stamp)
        stats["office_unsent"] += len(send)
        return
    _push(uid, b, "Your first assignment" if first else "Tasks for you", push, f"tasks-{key}", nav="operate:my-week")
    stats["office_told"] += len(send)


def taken_back_text(name: str, items: List[Dict[str, str]]) -> str:
    """The email to a login whose hand-off was taken back, in plain words:
    what it was, who it was for, why, and where the task is now."""
    import church_over
    clt = _clt()
    lines = [f"Hi {clt.first_name(name) or 'there'},"]
    if len(items) == 1:
        x = items[0]
        lines.append(f"You handed {x['name']} a task: {x['title']}.")
        lines.append(f"It was taken back, so it isn’t handed to them now. {church_over.WHO_HANDS}")
        lines.append(f"The task is still in Tasks, with {x['name']}’s name on it, for the owner to hand out.")
    else:
        lines.append(f"You handed out {len(items)} tasks that were taken back:\n"
                     + "\n".join(f"“{x['title']}” ({x['name']})" for x in items))
        lines.append(f"They aren’t handed to anyone now. {church_over.WHO_HANDS}")
        lines.append("They are still in Tasks, with a name on each, for the owner to hand out.")
    return "\n\n".join(lines)


def tell_taken_back(biz: Dict[str, Any], back: Dict[str, List[Dict[str, str]]]) -> int:
    """Each login whose hand-off a sweep just took back
    (church_leader_tasks.take_back), told once: one email to their sign-in
    address and one push for everything this sweep took back from them.
    `back` is {user id: [{id, title, name}]}. The take-back is done already
    and is the claim, so this is sent once and never tried again: an email
    that fails, or a login with no address, leaves the note on the task to
    say why. Returns how many logins were told."""
    clt = _clt()
    b = str(biz["id"])
    church = clt._plain(biz.get("name")) or "Your church"
    names = clt.handers(biz, back)
    link, reply_to = _link(b), clt._office_email(biz)
    told = 0
    for uid, items in back.items():
        who = person(biz, uid, names)
        if not who["email"] or not items:
            continue
        one = len(items) == 1
        what = "a task was taken back" if one else f"{len(items)} tasks were taken back"
        key = hashlib.sha1(",".join(sorted(x["id"] for x in items)).encode()).hexdigest()[:16]
        try:
            html = render(biz, taken_back_text(who["name"], items), what[:1].upper() + what[1:], link, "Open Tasks")
            clt.deliver(biz, who["email"], who["name"], f"{church}: {what}", html, f"office-task-back-{key}-{uid}",
                        reply_to=reply_to)
        except Exception:
            logger.warning("office tasks: a taken-back email failed (business %s)", b[:8], exc_info=True)
            continue
        _push(uid, b, "A task was taken back" if one else "Tasks were taken back",
              f"{items[0]['title']} ({items[0]['name']})" if one else "They aren’t handed to anyone now. Open Tasks.",
              f"task-back-{key}")
        told += 1
    return told


def tell_late(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    clt = _clt()
    tz = clt.zone(biz)
    if tz is None:
        return
    local = now.astimezone(tz)
    if not clt.LATE_FROM <= local.hour < clt.LATE_UNTIL:
        return
    today = local.date()
    midnight = datetime.combine(today, time(0), tzinfo=tz)
    due = []
    for r in rows:
        d, told = clt._day(r.get("due_date")), clt._at(r.get("seat_told_at"))
        if r.get("status") != "done" and d and d < today and told and told < midnight and r.get("assigned_to"):
            due.append(r)
    if not due:
        return
    b = str(biz["id"])
    over = overseers(biz)
    by_login: Dict[str, List[Dict[str, Any]]] = {}
    for r in sorted(due, key=lambda r: (str(r.get("due_date")), str(r.get("created_at") or ""))):
        by_login.setdefault(str(r["assigned_to"]), []).append(r)
    ids = set(by_login) | set(over) | {str(r.get("handed_by") or "") for r in due}
    names = clt.handers(biz, ids)
    reply_to = clt._office_email(biz)
    for uid, tasks in by_login.items():
        stamp = _iso(now)
        claimed = [t for t in tasks if _claim(b, t, "seat_late_told_at", stamp)]
        if not claimed:
            continue
        who = names.get(uid) or "Someone in the office"
        # Each person to tell, with why: whoever handed a task out, and the
        # Executive Pastor (or the owner). Never the login itself.
        tell: Dict[str, Dict[str, Any]] = {}
        for t in claimed:
            h = str(t.get("handed_by") or "")
            if h and h != uid:
                tell.setdefault(h, {"why": f"You’re hearing about it because you handed it to "
                                           f"{clt.first_name(who)}.", "tasks": []})["tasks"].append(t)
        # The Executive Pastor's own late task goes to the owner.
        above = [o for o in over if o != uid] or [o for o in (str(biz.get("owner_id") or ""),) if o and o != uid]
        for o in above:
            if o:
                entry = tell.setdefault(o, {"why": "", "tasks": []})
                entry["why"] = entry["why"] or (f"You’re hearing about it because {clt.first_name(who)} "
                                                "is on the office team you oversee.")
                entry["tasks"] = claimed
        sent = 0
        digest = hashlib.sha1(",".join(sorted(str(t["id"]) for t in claimed)).encode()).hexdigest()[:16]
        for to_uid, x in tell.items():
            p = person(biz, to_uid, names)
            if not p["email"]:
                continue
            subject = (f"{who} has a task past due" if len(x["tasks"]) == 1
                       else f"{who} has {len(x['tasks'])} tasks past due")
            try:
                html = render(biz, late_text(p["name"], who, x["tasks"], x["why"]), subject)
                clt.deliver(biz, p["email"], p["name"], subject, html,
                            f"office-task-late-{digest}-{to_uid}", reply_to=reply_to)
                sent += 1
                _push(to_uid, b, subject, clt._plain(x["tasks"][0].get("title")) or "A task", f"late-{digest}")
            except Exception:
                logger.warning("office tasks: a past-due email failed (business %s)", b[:8], exc_info=True)
        if sent:
            stats["office_late"] += len(claimed)
        elif tell:
            for t in claimed:
                clt._release(b, str(t["id"]), "seat_late_told_at", stamp)
            stats["office_late_unsent"] += len(claimed)
        else:
            stats["office_late_no_one"] += len(claimed)


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, on the worker (kmj_intake_automation): new hand-offs to a
    login are told; in each church's morning, late ones go up. A church that
    fails never stops the others. Quiet with the switch off or before the
    migration. `office_taken_back`: hand-offs to a pastor's or an elder's
    login that weren't the login's to make, un-handed before anyone was told;
    `office_rule_unread`: ones left for the next sweep because who is a
    pastor couldn't be read (church_leader_tasks.take_back)."""
    clt = _clt()
    stats = {"churches": 0, "office_told": 0, "office_self": 0, "office_no_email": 0, "office_unsent": 0,
             "office_late": 0, "office_late_no_one": 0, "office_late_unsent": 0,
             "office_taken_back": 0, "office_rule_unread": 0}
    if clt.mode() == "off":
        return stats
    now = now or datetime.now(timezone.utc)
    fresh = _rows(f"/tasks?assigned_to=not.is.null&seat_told_at=is.null&status=neq.done"
                  f"&select={FIELDS}&order=created_at.asc&limit={SWEEP_MAX}")
    if fresh is None:
        return stats  # the migration isn't applied (or the read failed): next hour
    cutoff = (now.astimezone(timezone.utc).date() + timedelta(days=1)).isoformat()
    late = _rows(f"/tasks?assigned_to=not.is.null&status=neq.done&seat_late_told_at=is.null"
                 f"&seat_told_at=not.is.null&due_date=lt.{cutoff}"
                 f"&select={FIELDS}&order=due_date.asc&limit={SWEEP_MAX}") or []
    work: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for kind, rows in (("fresh", fresh), ("late", late)):
        for r in rows:
            work.setdefault(str(r.get("business_id")), {"fresh": [], "late": []})[kind].append(r)
    if not work:
        return stats
    bizs: Dict[str, Dict[str, Any]] = {}
    for chunk in clt._chunks(work):
        for x in _rows(f"/businesses?id=in.({','.join(_q(i) for i in chunk)})"
                       "&select=id,name,type,settings,owner_id&limit=100") or []:
            bizs[str(x["id"])] = x
    import church_follow_up as cfu
    for b, todo in work.items():
        biz = bizs.get(b)
        if not biz or not cfu.is_church(biz) or not clt.church_open(b):
            continue
        stats["churches"] += 1
        try:
            if todo["fresh"]:
                tell_new(biz, todo["fresh"], now, stats)
            if todo["late"]:
                tell_late(biz, todo["late"], now, stats)
        except Exception:
            logger.warning("office tasks sweep failed for business %s", b[:8], exc_info=True)
    return stats
