"""church_monthly_report.py — the monthly report, gathered from the admin lanes, with nothing about money.

Kevin, 2026-11-01: "gathering the reports from admin should be Jessica", and
the monthly report has "nothing about money". The Executive Pastor holds the
monthly_report duty by default (church_duties: "The monthly report from the
lanes, without the money", due the first Monday). This is the report: a draft
for one month, a section a lane, from numbers the app already keeps, with her
notes, sent to the pastor.

    OFFICE & LEADERSHIP  tasks from meetings done and late (church_board_items
                         linked to tasks); rooms booked (church_space_bookings,
                         booked); new leaders (church_leader_roles: a person
                         whose first role began that month)
    PEOPLE & CARE        first-time guests and how many were reached since
                         (church_reports' rule for a first visit, church_reads'
                         for reaching out); Prayer & care requests received and
                         closed; people drifting from their groups
                         (church_reads.group_drift, today, so only for this
                         month and the one before). Counts only: never a name,
                         never what was asked, never a pastors-only note. The
                         care counts are People & care's (church_reports' rule):
                         a login whose areas leave it out doesn't get them
    SUNDAY & SERVING     attendance at each service (church_reports: the
                         headcount, or the people checked in by name if that's
                         more); serving places filled and open (sunday_planning:
                         a yes is filled; no one, offered, a no or an ask with no
                         answer is open); people new to a Sunday team
    MEDIA & COMMS        sermons posted (worship_sermons, published); clips
                         posted and posts sent (social_publications, the one
                         posting door, posted or partly posted)

A number that isn't kept for this church (no rooms, no Sunday teams, no
connected accounts, no meeting tasks) leaves its line out. A read that fails
leaves its line out too and says so in the section's `missing`: nothing is
invented. Nothing about money is read, not even a total: no gifts, no fees,
no bills, no help amounts.

  GET  /church/monthly-report?business_id=&month=YYYY-MM   the draft and her notes
  PUT  /church/monthly-report                              {business_id, month, notes: {lane: text}}
  POST /church/monthly-report/send                         {business_id, month, force}

Who: the owner, an admin, or a Manager that does monthly_report (a Manager
without it is told whose job it is). The send emails the finished page (the
numbers and the notes) to the owner, from the church, through the leaders
note's email path, once a month: the last send is kept on the month's row, and
a resend needs `force`. Every write after the email is checked: one that went
but wasn't noted says so (`recorded` false) and leaves the month "sending", and
a send still "sending" past its ten-minute hold goes again only with `force`,
so the pastor never gets it twice unasked. My week shows it as due on the first Monday to the
Manager who does it (church_my_week), until it's sent.

Notes and sends live in church_monthly_reports (supabase/APPLY-2026-11-02-
church-monthly-report.sql: server-only, RLS on, no policies). Before it's
applied, the page and the send are a 503 and My week leaves the line out.
Switched by CHURCH_MONTHLY_REPORT: off | owner | on (owner, the default, is the
platform owner's own church, member_asks.platform_church).
"""
from __future__ import annotations

import html as _html
import logging
import os
import re
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import business_access
import church_duties as cd
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/monthly-report", tags=["church"])

DUTY = "monthly_report"
TABLE = "church_monthly_reports"
KEEPS_ALL = ("owner", "admin")
LANES = ("office_leadership", "people_care", "sunday_serving", "media_comms")
NOTE_MAX = 1200
MONTHS_BACK = 12
SENDING_HOLD = timedelta(minutes=10)   # a send still "sending" after this was cut off; it can go again
CARE_AREA = "people_care"
CHUNK = 100
REACH_OUT_EVENTS = ("activity_logged", "email_sent", "sms_sent", "agent_message_sent", "journey_sent")
SENT = ("posted", "partly_posted")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")
NOT_CHURCH = "The monthly report is for churches"
ROW_FIELDS = "month,notes,notes_by_name,notes_at,send_id,send_state,sent_at,sent_by,sent_by_name,sends"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_MONTHLY_REPORT") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def church_open(business_id: Any) -> bool:
    """On, or (owner) the platform owner's own church: the Executive Pastor
    isn't the platform owner, so an owner switch is her church's."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── Small things ─────────────────────────────────────────────────────

class Unread(Exception):
    """A source that couldn't be read: its line is left out, and said."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def _chunks(ids: Iterable[Any]) -> List[List[str]]:
    out = sorted({str(i) for i in ids if i})
    return [out[i:i + CHUNK] for i in range(0, len(out), CHUNK)]


def _all(path: str, what: str, order: str = "id") -> List[Dict[str, Any]]:
    """Every row, a page at a time (church_reports._all: PostgREST caps a
    read, and a count cut short would be a wrong number)."""
    import church_reports as cr
    try:
        return cr._all(path, order, what)
    except cr.Unread as e:
        raise Unread(str(e))


def _all_in(path: str, column: str, ids: Iterable[Any], what: str, order: str = "id") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for part in _chunks(ids):
        out += _all(f"{path}&{column}=in.({','.join(_q(i) for i in part)})", what, order)
    return out


def _any(path: str, what: str) -> bool:
    """Whether the church keeps this at all (one row is enough)."""
    rows = sb_clients.sb_get_as_service(f"{path}&limit=1")
    if not isinstance(rows, list):
        raise Unread(what)
    return bool(rows)


def month_words(first: date) -> str:
    return f"{MONTH_NAMES[first.month - 1]} {first.year}"


def next_month(first: date) -> date:
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def prev_month(first: date) -> date:
    return date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def first_monday(first: date) -> date:
    """The first Monday of the month that starts on `first`."""
    return first + timedelta(days=(7 - first.weekday()) % 7)


def day_words(d: date) -> str:
    return f"{d:%A}, {MONTH_NAMES[d.month - 1]} {d.day}"


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and the login gathering its report: the owner, an admin,
    or a Manager that does monthly_report (church_duties). 404 for a closed
    switch, no seat of a manager or above, or not a church; 403 for a Manager
    that doesn't do it, naming whose job it is; a failed read is a 503."""
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "manager")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    if not church_open(biz_id):
        raise HTTPException(404, "Not Found")
    if role not in KEEPS_ALL and not cd.holds(biz_id, user, DUTY):
        raise HTTPException(403, cd.refusal(biz_id, DUTY))
    # Prayer & care's counts are People & care's (church_reports' rule).
    import church_reports as cr
    areas = cr._areas(biz_id, str(user.id), role)
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user,
            "care": areas is None or CARE_AREA in areas}


def _zone(biz: Dict[str, Any]):
    import church_leader_tasks
    tz = church_leader_tasks.zone(biz)
    if tz is None:
        raise HTTPException(503, "The church's clock couldn't be read just now. Try again.")
    return tz


def _month(raw: Any, today: date) -> date:
    """The month asked for, as its first day: YYYY-MM, begun, and at most a
    year back. None or "" is the month before this one (the report is
    gathered at the start of the next)."""
    this = date(today.year, today.month, 1)
    if raw in (None, ""):
        return prev_month(this)
    m = MONTH_RE.match(str(raw).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise HTTPException(400, "Pick a month as YYYY-MM.")
    first = date(int(m.group(1)), int(m.group(2)), 1)
    if first > this:
        raise HTTPException(400, "That month hasn't begun yet.")
    if (this.year - first.year) * 12 + this.month - first.month > MONTHS_BACK:
        raise HTTPException(400, f"Pick a month from the last {MONTHS_BACK} months.")
    return first


def _context(me: Dict[str, Any], month: Any) -> Dict[str, Any]:
    biz = me["biz"]
    tz = _zone(biz)
    now = _now()
    today = now.astimezone(tz).date()
    first = _month(month, today)
    nxt = next_month(first)
    current = first == date(today.year, today.month, 1)
    return {"me": me, "biz": biz, "b": _q(biz["id"]), "tz": tz, "now": now, "today": today,
            "first": first, "next": nxt, "current": current,
            "lo": datetime.combine(first, time(0), tzinfo=tz), "hi": datetime.combine(nxt, time(0), tzinfo=tz),
            # The day "late" is judged on: today in this month, else the month's end.
            "cutoff": today if current else nxt}


# ─── A section's lines ────────────────────────────────────────────────

class Lines:
    def __init__(self, key: str):
        self.key = key
        self.lines: List[Dict[str, Any]] = []
        self.missing: List[str] = []

    def add(self, key: str, label: str, value: Any, text: str) -> None:
        if value is not None:
            self.lines.append({"key": key, "label": label, "value": value, "text": text})

    def unread(self, what: str) -> None:
        self.missing.append(f"{what} couldn't be read just now, so it's left out.")

    def view(self, notes: Dict[str, str]) -> Dict[str, Any]:
        return {"key": self.key, "label": cd.lane_label(self.key), "lines": self.lines, "missing": self.missing,
                "note": notes.get(self.key, "")}


# ─── Office & Leadership ──────────────────────────────────────────────

def office(ctx: Dict[str, Any]) -> Lines:
    out = Lines("office_leadership")
    b, tz = ctx["b"], ctx["tz"]
    try:
        items = _all(f"/church_board_items?business_id=eq.{b}&task_id=not.is.null&select=id,task_id", "Tasks from meetings")
        ids = {str(i["task_id"]) for i in items if i.get("task_id")}
        if ids:
            tasks = _all_in(f"/tasks?business_id=eq.{b}&select=id,status,due_date,completed_at,created_at", "id", ids,
                            "Tasks from meetings")
            done = late = 0
            for t in tasks:
                at = _at(t.get("completed_at"))
                finished = at.astimezone(tz).date() if t.get("status") == "done" and at else None
                if finished and ctx["first"] <= finished < ctx["next"]:
                    done += 1
                due, made = _day(t.get("due_date")), _at(t.get("created_at"))
                made_on = made.astimezone(tz).date() if made else None
                if (due and due < ctx["cutoff"] and (made_on is None or made_on < ctx["cutoff"])
                        and not (finished and finished < ctx["cutoff"])):
                    late += 1
            out.add("meeting_tasks_done", "Tasks from meetings done", done, f"Tasks from meetings done: {done}")
            out.add("meeting_tasks_late", "Tasks from meetings late", late, f"Tasks from meetings still late: {late}")
    except Unread:
        out.unread("Tasks from meetings")
    try:
        if _any(f"/church_spaces?business_id=eq.{b}&select=id", "Rooms"):
            n = len(_all(f"/church_space_bookings?business_id=eq.{b}&status=eq.booked"
                         f"&start_at=gte.{_q(_iso(ctx['lo']))}&start_at=lt.{_q(_iso(ctx['hi']))}&select=id", "Rooms"))
            out.add("rooms_booked", "Rooms booked", n, f"Rooms booked: {n}")
    except Unread:
        out.unread("Rooms")
    try:
        started: Dict[str, datetime] = {}
        for r in _all(f"/church_leader_roles?business_id=eq.{b}&status=eq.active&select=id,contact_id,answered_at,created_at",
                      "Leaders & roles"):
            at = _at(r.get("answered_at")) or _at(r.get("created_at"))
            cid = str(r.get("contact_id") or "")
            if cid and at and (cid not in started or at < started[cid]):
                started[cid] = at
        n = sum(1 for at in started.values() if ctx["lo"] <= at < ctx["hi"])
        out.add("new_leaders", "New leaders", n, f"New leaders: {n}")
    except Unread:
        out.unread("Leaders & roles")
    return out


# ─── People & Care ────────────────────────────────────────────────────

def first_visits(ctx: Dict[str, Any]) -> Dict[str, datetime]:
    """Each first-time guest whose first visit ever fell in the month, as
    key → when: a first-time check-in, or a family the kids desk welcomed,
    each person once (church_reports._guests' rule, keys kept so the reach
    can be counted). Names are read to match a name-only visit to its
    record, never shown."""
    b, hi = ctx["b"], _q(_iso(ctx["hi"]))
    first: Dict[str, datetime] = {}

    def seen(key: str, at: Optional[datetime]) -> None:
        if key and at and (key not in first or at < first[key]):
            first[key] = at
    for r in _all(f"/attendance?business_id=eq.{b}&first_time=is.true&checked_in_at=lt.{hi}"
                  "&select=id,contact_id,name,checked_in_at", "Attendance"):
        key = f"c:{r['contact_id']}" if r.get("contact_id") else "n:" + " ".join(str(r.get("name") or "").lower().split())
        seen("" if key == "n:" else key, _at(r.get("checked_in_at")))
    for r in _all(f"/church_follow_ups?business_id=eq.{b}&source_event=like.{_q('first-visit:*')}"
                  f"&created_at=lt.{hi}&select=id,contact_id,created_at", "Follow-up"):
        if r.get("contact_id"):
            seen(f"c:{r['contact_id']}", _at(r.get("created_at")))
    named = {k[2:]: k for k in first if k.startswith("n:")}
    if named:
        ids = [k[2:] for k in first if k.startswith("c:")]
        for c in _all_in(f"/contacts?business_id=eq.{b}&select=id,name", "id", ids, "Attendance"):
            nk = named.get(" ".join(str(c.get("name") or "").lower().split()))
            if nk and nk in first:
                seen(f"c:{c['id']}", first.pop(nk))
    return {k: at for k, at in first.items() if ctx["lo"] <= at < ctx["hi"]}


def reached(ctx: Dict[str, Any], firsts: Dict[str, datetime]) -> int:
    """How many of these guests someone reached after their first visit: a
    text that went (not a failed one), or a call, visit, email or message
    logged (church_reads.REACH_OUT_EVENTS). A check-in isn't reaching out,
    and a name-only guest can't be counted as reached."""
    b = ctx["b"]
    ids = [k[2:] for k in firsts if k.startswith("c:")]
    if not ids:
        return 0
    last: Dict[str, datetime] = {}
    rows = _all_in(f"/sms_messages?business_id=eq.{b}&direction=eq.outbound&status=neq.failed&select=id,contact_id,created_at",
                   "contact_id", ids, "Texts")
    rows += _all_in(f"/events?business_id=eq.{b}&event_type=in.({','.join(REACH_OUT_EVENTS)})"
                    "&select=id,contact_id,created_at", "contact_id", ids, "Calls and visits")
    for r in rows:
        at, cid = _at(r.get("created_at")), str(r.get("contact_id") or "")
        if at and cid and (cid not in last or at > last[cid]):
            last[cid] = at
    return sum(1 for cid in ids if cid in last and last[cid] >= firsts[f"c:{cid}"])


def people(ctx: Dict[str, Any]) -> Lines:
    out = Lines("people_care")
    b = ctx["b"]
    lo, hi = _q(_iso(ctx["lo"])), _q(_iso(ctx["hi"]))
    try:
        firsts = first_visits(ctx)
        # The church welcomes guests here: a check-in, or the kids desk, that month.
        used = firsts or _any(f"/attendance?business_id=eq.{b}&checked_in_at=gte.{lo}&checked_in_at=lt.{hi}&select=id",
                              "Attendance")
        if used:
            n = len(firsts)
            out.add("guests", "First-time guests", n, f"First-time guests: {n}")
            if n:
                k = reached(ctx, firsts)
                out.add("guests_reached", "Guests reached since their first visit", k,
                        f"Reached since their first visit: {k} of {n}")
    except Unread:
        out.unread("First-time guests")
    if ctx["me"]["care"]:
        try:
            opened = len(_all(f"/ministry_care_requests?business_id=eq.{b}&legacy_source=is.null"
                              f"&created_at=gte.{lo}&created_at=lt.{hi}&select=id", "Prayer & care"))
            closed = len(_all(f"/ministry_care_requests?business_id=eq.{b}&status=eq.closed"
                              f"&status_changed_at=gte.{lo}&status_changed_at=lt.{hi}&select=id", "Prayer & care"))
            out.add("care_opened", "Prayer & care requests received", opened, f"Prayer & care requests received: {opened}")
            out.add("care_closed", "Prayer & care requests closed", closed, f"Prayer & care requests closed: {closed}")
        except Unread:
            out.unread("Prayer & care")
    # Drifting is today's (who has missed their group's last meetings), so
    # it belongs only to this month's report and the one just ended.
    if ctx["first"] >= prev_month(date(ctx["today"].year, ctx["today"].month, 1)):
        import church_reads
        drift = church_reads.group_drift(str(ctx["biz"]["id"]), now=ctx["now"])
        if drift is None:
            out.unread("Groups")
        elif drift["groups"]:
            n = len({d["contact_id"] for d in drift["drifting"]})
            out.add("drifting", "People drifting from their groups, today", n,
                    f"People drifting from their groups today: {n}")
    return out


# ─── Sunday & Serving ─────────────────────────────────────────────────

def sunday(ctx: Dict[str, Any]) -> Lines:
    out = Lines("sunday_serving")
    b, tz = ctx["b"], ctx["tz"]
    import church_reports as cr
    try:
        occ = cr._occasions({"b": b, "shared": cr._Shared()})
        svc = sorted((o for o in occ if o["kind"] == "service" and ctx["first"] <= o["day"] < ctx["next"]),
                     key=lambda o: o["day"])
        ids = [o["id"] for o in svc]
        named = Counter(str(r["entry_id"]) for r in _all_in(f"/attendance?business_id=eq.{b}&select=id,entry_id",
                                                              "entry_id", ids, "Attendance"))
        heads: Counter = Counter()
        for r in _all_in(f"/attendance_headcounts?business_id=eq.{b}&select=id,entry_id,count", "entry_id", ids,
                         "Attendance"):
            heads[str(r["entry_id"])] += max(0, int(r.get("count") or 0))
        counts = [{"day": o["day"].isoformat(), "title": o["title"], "total": max(named[o["id"]], heads[o["id"]])}
                  for o in svc]
        counts = [c for c in counts if c["total"] > 0]
        if counts:
            said = " · ".join(f"{date.fromisoformat(c['day']):%a} {MONTH_NAMES[int(c['day'][5:7]) - 1][:3]} "
                              f"{int(c['day'][8:10])}: {c['total']}" for c in counts)
            out.add("attendance", "Attendance at each service", counts, f"Attendance: {said}")
    except (Unread, cr.Unread):
        out.unread("Attendance")
    try:
        serve = _all(f"/serve_teams?business_id=eq.{b}&select=group_id", "Sunday teams", order="group_id")
        teams = {str(g["id"]) for g in _all(f"/groups?business_id=eq.{b}&kind=eq.team&active=eq.true&select=id",
                                             "Sunday teams")} & {str(s["group_id"]) for s in serve}
        if teams:
            plans = _all(f"/worship_services?business_id=eq.{b}&archived_at=is.null&is_template=eq.false"
                         f"&starts_at=gte.{_q(_iso(ctx['lo']))}&starts_at=lt.{_q(_iso(ctx['hi']))}&select=id",
                         "Sunday teams")
            places = _all_in(f"/serve_positions?business_id=eq.{b}&active=eq.true&select=id,group_id,needed",
                             "group_id", teams, "Sunday teams")
            if plans and places:
                rows = _all_in(f"/serve_assignments?business_id=eq.{b}&select=id,service_id,position_id,slot,status",
                               "service_id", [p["id"] for p in plans], "Sunday teams")
                held = {(str(r["service_id"]), str(r["position_id"]), int(r.get("slot") or 1)): r.get("status")
                        for r in rows}
                filled = empty = 0
                for p in plans:
                    for place in places:
                        for slot in range(1, int(place.get("needed") or 1) + 1):
                            if held.get((str(p["id"]), str(place["id"]), slot)) == "yes":
                                filled += 1
                            else:
                                empty += 1
                out.add("serving_filled", "Serving places filled", filled, f"Serving places filled: {filled}")
                out.add("serving_open", "Serving places open", empty, f"Serving places open: {empty}")
            joined: Dict[str, date] = {}
            for m in _all_in(f"/group_members?business_id=eq.{b}&select=id,contact_id,joined_on", "group_id", teams,
                             "Sunday teams"):
                d, cid = _day(m.get("joined_on")), str(m.get("contact_id") or "")
                if cid and d and (cid not in joined or d < joined[cid]):
                    joined[cid] = d
            n = sum(1 for d in joined.values() if ctx["first"] <= d < ctx["next"])
            out.add("new_volunteers", "People new to a Sunday team", n, f"People new to a Sunday team: {n}")
    except Unread:
        out.unread("Sunday teams")
    return out


# ─── Media & Communications ───────────────────────────────────────────

def media(ctx: Dict[str, Any]) -> Lines:
    out = Lines("media_comms")
    b = ctx["b"]
    try:
        if _any(f"/sermons?business_id=eq.{b}&select=id", "Sermons"):
            n = len(_all(f"/sermons?business_id=eq.{b}&published=eq.true&preached_on=gte.{ctx['first'].isoformat()}"
                         f"&preached_on=lt.{ctx['next'].isoformat()}&select=id", "Sermons"))
            out.add("sermons", "Sermons posted", n, f"Sermons posted: {n}")
    except Unread:
        out.unread("Sermons")
    try:
        if _any(f"/social_connections?business_id=eq.{b}&select=id", "Posts"):
            # A post scheduled weeks ahead went out on its day: read back far
            # enough to find it, then count it in the month it went out.
            since = _q(_iso(ctx["lo"] - timedelta(days=92)))
            posts = clips = 0
            for r in _all(f"/social_publications?business_id=eq.{b}&status=in.({','.join(SENT)})"
                          f"&created_at=gte.{since}&created_at=lt.{_q(_iso(ctx['hi']))}"
                          "&select=id,media,scheduled_at,created_at", "Posts"):
                went = _at(r.get("scheduled_at")) or _at(r.get("created_at"))
                if not went or not ctx["lo"] <= went < ctx["hi"]:
                    continue
                posts += 1
                media_items = r.get("media") if isinstance(r.get("media"), list) else []
                if any(isinstance(m, dict) and m.get("clip_id") for m in media_items):
                    clips += 1
            out.add("clips", "Clips posted", clips, f"Clips posted: {clips}")
            out.add("posts", "Posts sent, clips among them", posts, f"Posts sent: {posts}"
                    + (f", {clips} of them clips" if clips else ""))
    except Unread:
        out.unread("Posts")
    return out


BUILDERS = (office, people, sunday, media)


# ─── The month's row: her notes, and the last send ────────────────────

def _row(biz_id: str, month: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(f"/{TABLE}?business_id=eq.{_q(biz_id)}&month=eq.{_q(month)}"
                                        f"&select={ROW_FIELDS}&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The report's notes couldn't be read just now. Try again.")
    return rows[0] if rows else None


def _notes_of(row: Optional[Dict[str, Any]]) -> Dict[str, str]:
    notes = (row or {}).get("notes")
    if not isinstance(notes, dict):
        return {}
    return {k: str(v) for k, v in notes.items() if k in LANES and isinstance(v, str) and v.strip()}


def _clock(d: datetime) -> str:
    return f"{d.strftime('%I').lstrip('0') or '12'}:{d:%M} {d:%p}"


def last_send(row: Optional[Dict[str, Any]], tz) -> Optional[Dict[str, Any]]:
    if not row or not row.get("send_id") or row.get("send_state") != "sent":
        return None
    at = _at(row.get("sent_at"))
    local = at.astimezone(tz) if at else None
    return {"sent_at": row.get("sent_at"), "by_name": row.get("sent_by_name") or "",
            "sends": int(row.get("sends") or 1),
            "sent_words": f"{day_words(local.date())} at {_clock(local)}" if local else ""}


def owner_name(biz: Dict[str, Any]) -> str:
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    return _plain(settings.get("practitioner_name")) or "the pastor"


# ─── The report ───────────────────────────────────────────────────────

def build(me: Dict[str, Any], month: Any = None) -> Dict[str, Any]:
    ctx = _context(me, month)
    biz = ctx["biz"]
    key = ctx["first"].strftime("%Y-%m")
    row = _row(str(biz["id"]), key)
    notes = _notes_of(row)
    sections = [fn(ctx).view(notes) for fn in BUILDERS]
    this = date(ctx["today"].year, ctx["today"].month, 1)
    months, m = [], this
    for _ in range(MONTHS_BACK + 1):
        months.append({"month": m.strftime("%Y-%m"), "words": month_words(m)})
        m = prev_month(m)
    due = first_monday(ctx["next"])
    sent = last_send(row, ctx["tz"])
    return {
        "church": _plain(biz.get("name")) or "Your church",
        "month": key, "month_words": month_words(ctx["first"]), "current": ctx["current"],
        "through": (ctx["today"] if ctx["current"] else ctx["next"] - timedelta(days=1)).isoformat(),
        "months": months,
        "sections": sections,
        "notes": notes,
        "notes_saved": ({"at": row.get("notes_at"), "by_name": row.get("notes_by_name") or ""}
                        if row and row.get("notes_at") else None),
        "care": bool(me["care"]),
        "sent": sent is not None, "last_send": sent,
        "sending": bool(row and row.get("send_state") == "sending"),
        "due": {"day": due.isoformat(), "words": day_words(due)},
        "to": {"name": owner_name(biz)},
    }


# ─── Her notes ────────────────────────────────────────────────────────

def save_notes(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    raw = body.get("notes")
    if not isinstance(raw, dict):
        raise HTTPException(400, "Send the notes as one line or a short paragraph for each lane.")
    unknown = [k for k in raw if k not in LANES]
    if unknown:
        raise HTTPException(400, "Notes go under the office's four lanes.")
    notes: Dict[str, str] = {}
    for k in LANES:
        v = raw.get(k)
        if v is None:
            continue
        if not isinstance(v, str):
            raise HTTPException(400, "Each note is words: one line or a short paragraph.")
        v = v.replace("\r\n", "\n").strip()
        if len(v) > NOTE_MAX:
            raise HTTPException(400, f"Keep each lane's note under {NOTE_MAX:,} letters: a line or a short paragraph.")
        if v:
            notes[k] = v
    tz = _zone(me["biz"])
    first = _month(body.get("month"), _now().astimezone(tz).date())
    import church_leaders_note as cln
    saved = sb_clients.sb_post_as_service(
        f"/{TABLE}?on_conflict=business_id,month",
        {"business_id": str(me["biz"]["id"]), "month": first.strftime("%Y-%m"), "notes": notes,
         "notes_by": me["uid"], "notes_by_name": cln.sender_name(me["biz"], me["user"]), "notes_at": _iso(_now())},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The notes didn't save. Try again.")
    return {"ok": True, "month": first.strftime("%Y-%m"), "notes": notes}


# ─── Sending it to the pastor ─────────────────────────────────────────

def report_text(report: Dict[str, Any], by: str) -> str:
    """The finished page in plain words: each lane's numbers and her note."""
    lines = [f"Hi {owner_name_first(report['to']['name'])},",
             f"Here is {report['month_words']} from the office's lanes" + (f", gathered by {by}" if by else "")
             + ". Nothing about money is in it."]
    for s in report["sections"]:
        block = [s["label"]] + [ln["text"] for ln in s["lines"]]
        if s.get("note"):
            block.append(f"Note: {s['note']}")
        if len(block) == 1:
            block.append("Nothing to report from the numbers the app keeps.")
        lines.append("\n".join(block))
    return "\n\n".join(lines)


def owner_name_first(name: str) -> str:
    parts = _plain(name).split(" ")
    if len(parts) > 1 and parts[0].lower().rstrip(".") in ("pastor", "rev", "reverend", "dr", "bishop", "elder"):
        return " ".join(parts[:2])
    return parts[0] if parts and parts[0] else "Pastor"


def report_html(text: str, headings: List[str], primary: str) -> str:
    import email_layout
    e = _html.escape
    p = '<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#1f2937;">'
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = [ln.rstrip() for ln in block.split("\n")]
        if rows and rows[0].strip() in headings:
            out.append(f'<p style="margin:{"8" if not out else "28"}px 0 10px;padding-left:10px;border-left:3px solid {e(primary)};'
                       'font-size:12px;line-height:1.4;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#111827;">'
                       f"{e(rows[0].strip())}</p>")
            rows = rows[1:]
        if any(r.strip() for r in rows):
            out.append(p + "<br />".join(email_layout._linkify(e(r)) for r in rows) + "</p>")
    return "".join(out)


def render(biz: Dict[str, Any], subject: str, text: str, headings: List[str]) -> str:
    import email_layout
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    brand = email_layout.brand_of(settings)
    church = _plain(biz.get("name")) or "Your church"
    return email_layout.render_html(
        "", business_name=church, brand=brand, sig=None, preheader=subject[:90],
        after_cta=report_html(text, headings, brand.get("primary") or email_layout.DEFAULT_ACCENT),
        disclaimer=f"You’re getting this because you lead {church}.",
        footer_note="Sent by your church office")


def _claim(biz_id: str, month: str, last: Optional[Dict[str, Any]], rec: Dict[str, Any]) -> bool:
    """Take the month's send: only while nobody has (send_id empty), or, for
    a resend, only while the last send is still the one read. Two presses,
    or two people, send once."""
    where = f"send_id=eq.{_q(last['send_id'])}" if last and last.get("send_id") else "send_id=is.null"
    got = sb_clients.sb_patch_as_service(f"/{TABLE}?business_id=eq.{_q(biz_id)}&month=eq.{_q(month)}&{where}", rec)
    return isinstance(got, list) and bool(got)


def send(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    biz = me["biz"]
    biz_id = str(biz["id"])
    import rate_limit
    if not rate_limit.allow("church_monthly_report_send", biz_id):
        raise HTTPException(429, "The report was tried several times this hour. Try again later.")
    report = build(me, body.get("month"))
    month = report["month"]
    tz = _zone(biz)
    row = _row(biz_id, month)
    was = last_send(row, tz)
    started = _at((row or {}).get("sent_at"))
    if (row or {}).get("send_state") == "sending":
        if started and _now() - started < SENDING_HOLD:
            raise HTTPException(409, "Someone else is sending this report right now. Open it again in a moment.")
        # Older than the hold: it was cut off, or it went and wasn't noted.
        # Either way, only a send asked for by name goes again.
        if not body.get("force"):
            raise HTTPException(409, "The last send of this report may have gone without being noted. Send it again "
                                     "only if the pastor didn't get it.")
    if was and not body.get("force"):
        raise HTTPException(409, f"{report['month_words']}'s report already went to {report['to']['name']} "
                                 f"({was['sent_words']}{', by ' + was['by_name'] if was['by_name'] else ''}). "
                                 "Send it again to send the newer one.")
    import messaging_router
    to = (messaging_router._owner_email(str(biz.get("owner_id") or "")) or "").strip()
    if "@" not in to or " " in to:
        raise HTTPException(409, "The pastor's sign-in email couldn't be found, so there's no one to send it to.")
    if row is None:
        made = sb_clients.sb_post_as_service(f"/{TABLE}?on_conflict=business_id,month",
                                             {"business_id": biz_id, "month": month, "notes": {}},
                                             prefer="resolution=ignore-duplicates,return=representation")
        if not isinstance(made, list):
            raise HTTPException(503, "The report couldn't be sent just now. Try again.")
        row = _row(biz_id, month)
    import church_leaders_note as cln
    by = cln.sender_name(biz, me["user"])
    claim = {"send_id": uuid.uuid4().hex, "send_state": "sending", "sent_at": _iso(_now()), "sent_by": me["uid"],
             "sent_by_name": by, "sends": int((row or {}).get("sends") or 0) + 1}
    if not _claim(biz_id, month, row, claim):
        raise HTTPException(409, "Someone else is sending this report right now. Open it again in a moment.")
    subject = f"The {report['month_words']} report"
    headings = [s["label"] for s in report["sections"]]
    text = report_text(report, by)
    reply = str(me["user"].email or "").strip()
    try:
        cln.deliver(biz, to, report["to"]["name"], subject, render(biz, subject, text, headings),
                    f"monthly-report-{biz_id}-{month}-{claim['send_id'][:12]}",
                    reply_to=reply if "@" in reply and " " not in reply else None)
    except Exception:
        logger.warning("monthly report: the email failed (business %s)", biz_id[:8], exc_info=True)
        back = {k: (row or {}).get(k) for k in ("send_id", "send_state", "sent_at", "sent_by", "sent_by_name", "sends")}
        back["sends"] = int(back.get("sends") or 0)
        if not _mark(biz_id, month, claim["send_id"], back):
            print(f"[church_monthly_report] {biz_id[:8]} {month}: a failed send's claim wasn't let go; "
                  f"it is held for {int(SENDING_HOLD.total_seconds() // 60)} minutes")
            raise HTTPException(503, "The report didn't reach the pastor just now, so nothing was sent. It can be "
                                     f"tried again in {int(SENDING_HOLD.total_seconds() // 60)} minutes.")
        raise HTTPException(503, "The report didn't reach the pastor just now, so nothing was sent. Try again in a moment.")
    done = {**claim, "send_state": "sent"}
    recorded = _mark(biz_id, month, claim["send_id"], {"send_state": "sent"})
    out = {"ok": True, "month": month, "to": report["to"]["name"], "last_send": last_send(done, tz), "sent": True,
           "recorded": recorded}
    if not recorded:
        # The pastor has it; the month still says "sending". A send after the
        # hold asks for force (send() above), so this never goes twice unasked.
        print(f"[church_monthly_report] {biz_id[:8]} {month}: SENT, but the send wasn't recorded "
              f"(send {claim['send_id'][:12]})")
        out["warning"] = "It went to the pastor, but the app couldn't note that it went. There's no need to send it again."
    return out


def _mark(biz_id: str, month: str, send_id: str, fields: Dict[str, Any]) -> bool:
    """Write what became of this send, only while the month is still this
    send's. Tried twice; False when neither write landed."""
    where = f"/{TABLE}?business_id=eq.{_q(biz_id)}&month=eq.{_q(month)}&send_id=eq.{_q(send_id)}"
    for _ in range(2):
        got = sb_clients.sb_patch_as_service(where, fields)
        if isinstance(got, list) and got:
            return True
    return False


# ─── My week: due on the first Monday ─────────────────────────────────

def week_item(business: Dict[str, Any], user_id: str, role: Optional[str], today: date) -> Optional[Dict[str, Any]]:
    """For My week: last month's report, due on this month's first Monday,
    for a Manager that does monthly_report, until it's sent. None for anyone
    else, once it's sent, and whenever a read fails (My week never fails for
    this line; the report page says what's wrong)."""
    if role != "manager":
        return None
    biz_id = str(business["id"])
    try:
        if not church_open(biz_id) or DUTY not in cd.standing(biz_id, str(user_id))["duties"]:
            return None
        this = date(today.year, today.month, 1)
        first = prev_month(this)
        row = _row(biz_id, first.strftime("%Y-%m"))
    except HTTPException:
        print(f"[church_monthly_report] {biz_id[:8]}: the report's line wasn't read for My week")
        return None
    except Exception:
        logger.info("monthly report: My week's line failed (business %s)", biz_id[:8], exc_info=True)
        return None
    if (row or {}).get("send_id"):
        return None      # sent, or sending (one that went but wasn't noted never nags)
    due = first_monday(this)
    words = MONTH_NAMES[first.month - 1]
    if today < due:
        return None
    if today == due:
        title, late = f"{words}'s monthly report is due today.", False
    else:
        title, late = f"{words}'s monthly report was due {day_words(due)}.", True
    return {"kind": "report", "late": late, "area": "office", "title": title,
            "detail": "Gather it from the lanes, add a line for each, and send it to the pastor. No money in it.",
            "door": {"area": "operate", "id": "monthly-report", "label": "Open the monthly report"}}


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("")
def monthly_report_read(business_id: str, month: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    return build(_access(business_id, user), month)


@router.put("")
def monthly_report_notes(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    return save_notes(_access(body.get("business_id"), user), body)


@router.post("/send")
def monthly_report_send(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    return send(_access(body.get("business_id"), user), body)
