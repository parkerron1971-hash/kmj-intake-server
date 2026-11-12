"""church_work_checks.py — what the system can count about a church's work
(docs/CHURCH_ASSIGNMENTS.md, decision 4).

A check can tick an assignment off; it never invents one. Each answers

    CHECKS[key](ctx) -> {done: True | False | None, text}

`done` True: the work is there, and an open assignment that names this check
(tasks.check_key) is ticked off (tick: status done, completed_at and
checked_at set, done by no one). False: not yet, with how far ("3 of 8
weeks"). None: only evidence, for a person to confirm ("7 rooms listed"),
or nothing to count yet. A check whose read fails says so ("Couldn't count
just now") and changes nothing.

`ctx` (Ctx) is one church at one moment: each check runs once per Ctx, and
reads its own table once (a board of five logins asks each check once, not
five times; church_team_week took 9-14 s for five logins before #1799).

The checks, each a count the code already keeps or can keep plainly:

    rooms_listed ........ church_spaces (active rooms): evidence only
    calendar_8_weeks .... the next 8 weeks with a service or an event, read
                          where the leaders note reads the calendar (the
                          Sunday plans, worship_services; Services & Events,
                          the event_roster rooms): done at 8 of 8
    departments_led ..... active church_departments with a leader: done when
                          every one has one
    groups_led .......... active groups with a leader (church_areas' count):
                          done at none without
    kids_checked ........ the kids leaders approved with a background check
                          date (space_leaders, space kids): evidence only,
                          since that table holds a date for every row by its
                          own rule and is not the list of everyone who works
                          with the kids
    follow_up_no_one .... people in follow-up with no one (the leaders note's
                          and My week's count): done at 0
    churchsavvy_joined .. ChurchSavvy's team (worship_team): done when nobody
                          invited is still waiting and at least one has joined
    serve_teams_led ..... the volunteers' Serve teams (serve_teams, owner
                          volunteers) with a leader: done when each has one
    sermons_6 ........... the last six Sundays with a sermon posted (sermons,
                          published): done at 6 of 6
    weekly_text ......... the weekly text went out this week
                          (church_my_week._done's own read)

Where there is nothing to count yet (no groups, no departments), the check
says so and claims nothing: a person confirms.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

UNREAD_TEXT = "Couldn't count just now."
WEEKS = 8
SUNDAYS = 6


class Unread(Exception):
    """A check's read didn't answer."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


class Ctx:
    """One church, now. Each check's answer is kept, so a check runs once,
    and each table a reader reads is read once (`once`), whoever asks: a
    team page of five logins reads it once, not five times."""

    def __init__(self, business: Dict[str, Any], now: Optional[datetime] = None, tz=None):
        self.business = business
        self.b = str(business["id"])
        self.now = now or datetime.now(timezone.utc)
        self._answers: Dict[str, Dict[str, Any]] = {}
        self._memo: Dict[Any, Any] = {}
        self._tz = tz

    def once(self, key: Any, fn: Callable[[], Any]) -> Any:
        """`fn()` once per Ctx; a read that failed stays failed (Unread) for
        the Ctx, never read again in the same request."""
        if key not in self._memo:
            try:
                self._memo[key] = (True, fn())
            except (Unread, HTTPException):
                self._memo[key] = (False, None)
        ok, got = self._memo[key]
        if not ok:
            raise Unread(str(key))
        return got

    @property
    def monday(self) -> date:
        return self.today - timedelta(days=self.today.weekday())

    def bounds(self, first: date, last: date):
        """[the start of `first`, the start of the day after `last`), on the
        church's clock."""
        return (datetime.combine(first, time(0), tzinfo=self.tz),
                datetime.combine(last + timedelta(days=1), time(0), tzinfo=self.tz))

    @property
    def tz(self):
        if self._tz is None:
            import church_leader_tasks as clt
            tz = clt.zone(self.business)
            if tz is None:
                import chief_assignments
                tz = chief_assignments._tz_for(self.b)
            self._tz = tz
        return self._tz

    @property
    def today(self) -> date:
        return self.now.astimezone(self.tz).date()

    def rows(self, path: str) -> List[Dict[str, Any]]:
        got = sb_clients.sb_get_as_service(path)
        if not isinstance(got, list):
            raise Unread(path.split("?")[0])
        return got


# ─── The checks ───────────────────────────────────────────────────────

def rooms_listed(ctx: Ctx) -> Dict[str, Any]:
    n = len(ctx.rows(f"/church_spaces?business_id=eq.{_q(ctx.b)}&active=eq.true&kind=eq.room&select=id&limit=500"))
    return {"done": None, "text": f"{_n(n, 'room', 'rooms')} listed" if n else "No rooms listed yet"}


# ─── Readers: each table once per Ctx ─────────────────────────────────

def plans(ctx: Ctx) -> List[Dict[str, Any]]:
    """The Sunday plans (worship_services, not a template, not archived) from
    this week's Monday for eight weeks, read where the leaders note reads
    them: each {id, day} on the church's clock."""
    def read() -> List[Dict[str, Any]]:
        import church_leaders_note as cln
        lo, hi = ctx.bounds(ctx.monday, ctx.monday + timedelta(days=7 * WEEKS - 1))
        try:
            return [{"id": str(p["id"]), "day": p["day"]} for p in cln._plans(ctx.b, lo, hi, ctx.tz)]
        except HTTPException:
            raise Unread("worship_services")
    return ctx.once("plans", read)


def calendar_items(ctx: Ctx) -> List[Dict[str, Any]]:
    """The calendar from this week's Monday for eight weeks, read where the
    leaders note reads it: the Sunday plans (plans) and Services & Events
    (the event_roster rooms; an invite-only one stays out). Each {day,
    source: plan | occasion, where}."""
    def read() -> List[Dict[str, Any]]:
        import church_leaders_note as cln
        monday = ctx.monday
        try:
            occasions = cln._occasions(ctx.b, monday, monday + timedelta(days=7 * WEEKS - 1), ctx.tz)
        except HTTPException:
            raise Unread("Services & Events")
        return ([{"day": p["day"], "source": "plan", "where": ""} for p in plans(ctx)] +
                [{"day": o["day"], "source": "occasion", "where": o.get("where") or ""} for o in occasions])
    return ctx.once("calendar", read)


def waiting(ctx: Ctx) -> List[Dict[str, Any]]:
    """The people in follow-up with no one (handed back, or never handed):
    the leaders note's and My week's count, with when each came in."""
    def read() -> List[Dict[str, Any]]:
        rows = ctx.rows(f"/church_follow_ups?business_id=eq.{_q(ctx.b)}&status=in.(open,handed_back)"
                        "&select=status,leader_contact_id,created_at&limit=1000")
        return [r for r in rows if r.get("status") == "handed_back" or not r.get("leader_contact_id")]
    return ctx.once("waiting", read)


def sermon_days(ctx: Ctx) -> set:
    """The days a published sermon was preached, back to six Sundays ago."""
    def read() -> set:
        today = ctx.today
        last = today - timedelta(days=(today.weekday() + 1) % 7)
        since = min(last - timedelta(weeks=SUNDAYS - 1), ctx.monday - timedelta(days=1))
        rows = ctx.rows(f"/sermons?business_id=eq.{_q(ctx.b)}&published=eq.true&preached_on=gte.{since.isoformat()}"
                        "&select=preached_on&limit=200")
        return {str(r.get("preached_on") or "")[:10] for r in rows}
    return ctx.once("sermons", read)


def _local_day(v: Any, tz) -> Optional[date]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(tz).date()


def calendar_8_weeks(ctx: Ctx) -> Dict[str, Any]:
    """Each of the next eight weeks (Monday to Sunday, this one first) with
    at least one service or event on the calendar."""
    monday = ctx.monday
    last = monday + timedelta(days=7 * WEEKS - 1)
    weeks = {(i["day"] - monday).days // 7 for i in calendar_items(ctx) if monday <= i["day"] <= last}
    n = len(weeks)
    return {"done": n >= WEEKS, "text": f"{n} of the next {WEEKS} weeks have something on the calendar"}


def departments_led(ctx: Ctx) -> Dict[str, Any]:
    rows = ctx.rows(f"/church_departments?business_id=eq.{_q(ctx.b)}&status=eq.active"
                    "&select=id,leader_contact_id&limit=200")
    if not rows:
        return {"done": None, "text": "No departments on the leaders map yet"}
    led = sum(1 for r in rows if r.get("leader_contact_id"))
    return {"done": led == len(rows), "text": f"{led} of {_n(len(rows), 'department', 'departments')} have a leader"}


def groups_led(ctx: Ctx) -> Dict[str, Any]:
    groups = ctx.rows(f"/groups?business_id=eq.{_q(ctx.b)}&active=eq.true&select=id&limit=2000")
    if not groups:
        return {"done": None, "text": "No groups yet"}
    leads = ctx.rows(f"/group_members?business_id=eq.{_q(ctx.b)}&role=eq.leader&select=group_id&limit=5000")
    have = {str(x.get("group_id")) for x in leads}
    without = sum(1 for g in groups if str(g["id"]) not in have)
    if not without:
        return {"done": True, "text": "Every group has a leader"}
    return {"done": False, "text": f"{_n(without, 'group has', 'groups have')} no leader"}


def kids_checked(ctx: Ctx) -> Dict[str, Any]:
    """Evidence only. The kids leaders the office approved (space_leaders,
    space kids) each carry a check date by the table's own rule
    (background_check_on is not null), so "every one has a date" would
    always pass; and who else works with the kids isn't a list the system
    keeps. A person confirms."""
    rows = ctx.rows(f"/space_leaders?business_id=eq.{_q(ctx.b)}&space=eq.kids&select=contact_id&limit=500")
    n = len({str(r.get("contact_id")) for r in rows})
    return {"done": None, "text": f"{_n(n, 'kids leader', 'kids leaders')} approved with a background check date"
            if n else "No kids leaders approved yet"}


def follow_up_no_one(ctx: Ctx) -> Dict[str, Any]:
    n = len(waiting(ctx))
    if not n:
        return {"done": True, "text": "Everyone in follow-up has someone"}
    return {"done": False, "text": f"{_n(n, 'person', 'people')} in follow-up {'has' if n == 1 else 'have'} no one"}


def churchsavvy_joined(ctx: Ctx) -> Dict[str, Any]:
    rows = ctx.rows(f"/worship_team?business_id=eq.{_q(ctx.b)}&status=in.(invited,active)&select=status&limit=200")
    joined = sum(1 for r in rows if r.get("status") == "active")
    waiting = sum(1 for r in rows if r.get("status") == "invited")
    if not rows:
        return {"done": False, "text": "Nobody is on ChurchSavvy's team yet"}
    text = f"{joined} joined" + (f", {waiting} still invited" if waiting else "")
    return {"done": joined > 0 and not waiting, "text": text}


def serve_teams_led(ctx: Ctx) -> Dict[str, Any]:
    teams = ctx.rows(f"/serve_teams?business_id=eq.{_q(ctx.b)}&owner=eq.volunteers&select=group_id&limit=500")
    if not teams:
        return {"done": None, "text": "No volunteer teams yet"}
    ids = [str(t["group_id"]) for t in teams if t.get("group_id")]
    have = set()
    for i in range(0, len(ids), 100):
        part = ",".join(_q(x) for x in ids[i:i + 100])
        have |= {str(x.get("group_id")) for x in ctx.rows(
            f"/group_members?business_id=eq.{_q(ctx.b)}&group_id=in.({part})&role=eq.leader&select=group_id&limit=2000")}
    led = sum(1 for g in ids if g in have)
    return {"done": led == len(ids), "text": f"{led} of {_n(len(ids), 'volunteer team', 'volunteer teams')} have a leader"}


def sermons_6(ctx: Ctx) -> Dict[str, Any]:
    """The last six Sundays (today, when it's Sunday), each with a sermon
    preached that day and posted."""
    today = ctx.today
    last = today - timedelta(days=(today.weekday() + 1) % 7)
    sundays = [last - timedelta(weeks=i) for i in range(SUNDAYS)]
    have = sermon_days(ctx)
    n = sum(1 for s in sundays if s.isoformat() in have)
    return {"done": n >= SUNDAYS, "text": f"{n} of the last {SUNDAYS} Sundays have their sermon posted"}


def weekly_text(ctx: Ctx) -> Dict[str, Any]:
    import church_my_week
    got = church_my_week._done(ctx.business, frozenset({"weekly_text"}), ctx.today, ctx.now, ctx.tz)
    if "weekly_text" not in got:
        raise Unread("events")
    if got["weekly_text"]:
        return {"done": True, "text": "This week's text went out"}
    return {"done": False, "text": "This week's text hasn't gone out yet"}


CHECKS: Dict[str, Callable[[Ctx], Dict[str, Any]]] = {
    "rooms_listed": rooms_listed,
    "calendar_8_weeks": calendar_8_weeks,
    "departments_led": departments_led,
    "groups_led": groups_led,
    "kids_checked": kids_checked,
    "follow_up_no_one": follow_up_no_one,
    "churchsavvy_joined": churchsavvy_joined,
    "serve_teams_led": serve_teams_led,
    "sermons_6": sermons_6,
    "weekly_text": weekly_text,
}
# The checks that only ever give evidence never tick anything off, so the
# hourly sweep never reads the items that name them (they'd fill its reads).
EVIDENCE = frozenset({"rooms_listed", "kids_checked"})
PASSABLE = frozenset(k for k in CHECKS if k not in EVIDENCE)


def run(ctx: Ctx, key: str) -> Optional[Dict[str, Any]]:
    """One check's answer, once per Ctx. None for a key that isn't a check.
    A read that fails is {done: None, text: "Couldn't count just now",
    unread: True}: nothing is ticked off on it."""
    fn = CHECKS.get(str(key or ""))
    if fn is None:
        return None
    if key not in ctx._answers:
        try:
            got = fn(ctx)
            ctx._answers[key] = {"key": key, "done": got.get("done"), "text": got.get("text") or ""}
        except Exception:
            print(f"[church_work_checks] {ctx.b[:8]}: {key} couldn't be counted", flush=True)
            ctx._answers[key] = {"key": key, "done": None, "text": UNREAD_TEXT, "unread": True}
    return ctx._answers[key]


def tick(ctx: Ctx, tasks: Iterable[Dict[str, Any]]) -> List[str]:
    """Tick off each open task whose check passes: status done, completed_at
    and checked_at now, done by no one, filtered on its church, still open
    and still naming the check (so two replicas, or a person marking it at the
    same moment, tick it once). Returns the ids ticked. A failed write leaves
    the task as it was; the next read or sweep tries again."""
    out: List[str] = []
    stamp = ctx.now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    for t in tasks:
        k = t.get("check_key")
        if not k or t.get("status") == "done":
            continue
        ans = run(ctx, k)
        if not ans or ans.get("done") is not True:
            continue
        got = sb_clients.sb_patch_as_service(
            f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(ctx.b)}&status=neq.done&check_key=eq.{_q(k)}",
            {"status": "done", "completed_at": stamp, "checked_at": stamp})
        if isinstance(got, list) and got:
            t.update(status="done", completed_at=stamp, checked_at=stamp)
            out.append(str(t["id"]))
    return out


# ─── This week's jobs (docs/CHURCH_ASSIGNMENTS.md, PR B) ──────────────
#
# A weekly job of church_duties.CATALOG that the system can judge, about the
# week the church's clock is in (Monday to Sunday): {done, text}. `due` is
# the day the job falls on for the login being judged (the day it picked,
# else the catalog's); church_my_week turns done and due into done / not
# yet / late. `done` None claims nothing (nothing to count this week); a
# read that fails claims nothing either (unread). Each reader reads its
# table once per Ctx, so a team page judges five logins on the same reads.

def _volunteer_places(ctx: Ctx) -> List[Dict[str, Any]]:
    """The places on the volunteers' Serve teams (serve_teams owner
    volunteers, the team's group active): each {id, needed}."""
    def read() -> List[Dict[str, Any]]:
        ids = [str(t["group_id"]) for t in ctx.rows(
            f"/serve_teams?business_id=eq.{_q(ctx.b)}&owner=eq.volunteers&select=group_id&limit=500") if t.get("group_id")]
        if not ids:
            return []
        live = [str(g["id"]) for g in ctx.rows(
            f"/groups?business_id=eq.{_q(ctx.b)}&kind=eq.team&active=eq.true&id=in.({','.join(_q(i) for i in ids)})"
            "&select=id&limit=500")]
        if not live:
            return []
        return ctx.rows(f"/serve_positions?business_id=eq.{_q(ctx.b)}&group_id=in.({','.join(_q(i) for i in live)})"
                        "&active=eq.true&select=id,group_id,needed&limit=500")
    return ctx.once("volunteer_places", read)


def sunday_spots(ctx: Ctx, day: date) -> Optional[tuple]:
    """(places with a yes, places) on the volunteers' teams for the services
    planned that day (plans: the calendar's own read). None when nothing is
    planned that day or the teams have no places."""
    def read() -> Optional[tuple]:
        services = [p["id"] for p in plans(ctx) if p["day"] == day]
        if not services:
            return None
        places = {str(p["id"]): max(1, int(p.get("needed") or 1)) for p in _volunteer_places(ctx)}
        if not places:
            return None
        rows = ctx.rows(f"/serve_assignments?business_id=eq.{_q(ctx.b)}"
                        f"&service_id=in.({','.join(_q(s) for s in services)})&status=eq.yes"
                        "&select=service_id,position_id,slot&limit=5000")
        yes = {(str(r.get("service_id")), str(r.get("position_id")), int(r.get("slot") or 1)) for r in rows
               if str(r.get("position_id")) in places and int(r.get("slot") or 1) <= places[str(r.get("position_id"))]}
        return len(yes), len(services) * sum(places.values())
    return ctx.once(("spots", day), read)


def sunday_counted(ctx: Ctx, day: date) -> bool:
    """Whether that day has a count: a named check-in (attendance) or a
    headcount above zero (attendance_headcounts) recorded that day, on the
    church's clock."""
    def read() -> bool:
        lo, hi = ctx.bounds(day, day)
        span = lambda col: f"{col}=gte.{_q(lo.isoformat())}&{col}=lt.{_q(hi.isoformat())}"  # noqa: E731
        if ctx.rows(f"/attendance?business_id=eq.{_q(ctx.b)}&{span('checked_in_at')}&select=id&limit=1"):
            return True
        return bool(ctx.rows(f"/attendance_headcounts?business_id=eq.{_q(ctx.b)}&{span('updated_at')}&count=gt.0"
                             "&select=id&limit=1"))
    return ctx.once(("counted", day), read)


def drifting(ctx: Ctx) -> set:
    """The families drifting right now (church_shepherd_signals: an open
    drift signal, church_shepherd_signals' own rule)."""
    return ctx.once("drifting", lambda: {str(r["household_id"]) for r in ctx.rows(
        f"/church_shepherd_signals?business_id=eq.{_q(ctx.b)}&kind=eq.drift&resolved_at=is.null"
        "&select=household_id&limit=10000") if r.get("household_id")})


def touched_since(ctx: Ctx, since: date) -> set:
    """The families with a touch logged (a call, a visit, a text, seen at
    church: church_shepherd_touches) since that day began, on the church's
    clock."""
    lo, _hi = ctx.bounds(since, since)
    return ctx.once(("touched", since), lambda: {str(r["household_id"]) for r in ctx.rows(
        f"/church_shepherd_touches?business_id=eq.{_q(ctx.b)}&created_at=gte.{_q(lo.isoformat())}"
        "&select=household_id&limit=10000") if r.get("household_id")})


def _day_name(d: date) -> str:
    return f"{d:%A}"


def job_first_guests(ctx: Ctx, due: date) -> Dict[str, Any]:
    """Nobody who came into follow-up by the end of the job's day is waiting
    with no one (handed back, or never handed). It counts everyone in
    follow-up, as the leaders note does: the board doesn't mark who is a
    first-time guest beyond a first check-in."""
    n = sum(1 for r in waiting(ctx) if (_local_day(r.get("created_at"), ctx.tz) or ctx.today) <= due)
    if not n:
        return {"done": True, "text": f"Everyone in follow-up by {_day_name(due)} has someone"}
    return {"done": False, "text": f"{_n(n, 'person', 'people')} in follow-up by {_day_name(due)} "
                                   f"{'has' if n == 1 else 'have'} no one"}


def job_serve_schedule(ctx: Ctx, due: date) -> Dict[str, Any]:
    """Every place on the volunteers' teams has a yes for the services
    planned this week's Sunday."""
    got = sunday_spots(ctx, ctx.monday + timedelta(days=6))
    if got is None:
        return {"done": None, "text": "Nothing planned to fill this Sunday"}
    yes, total = got
    return {"done": yes >= total, "text": f"{yes} of {total} places on Sunday's volunteer teams have a yes"}


def job_calendar(ctx: Ctx, due: date) -> Dict[str, Any]:
    """Next week (Monday to Sunday) has at least one service or event on the
    calendar, and every Services & Events occasion in it names its place."""
    first = ctx.monday + timedelta(days=7)
    items = [i for i in calendar_items(ctx) if first <= i["day"] <= first + timedelta(days=6)]
    if not items:
        return {"done": False, "text": "Nothing on next week's calendar yet"}
    no_place = sum(1 for i in items if i["source"] == "occasion" and not str(i.get("where") or "").strip())
    return {"done": not no_place,
            "text": f"{_n(len(items), 'thing', 'things')} on next week's calendar"
                    + (f", {no_place} without a place" if no_place else "")}


def job_sermons(ctx: Ctx, due: date) -> Dict[str, Any]:
    """Last Sunday (the day before this week's Monday) has a published
    sermon preached that day."""
    sunday = ctx.monday - timedelta(days=1)
    if sunday.isoformat() in sermon_days(ctx):
        return {"done": True, "text": "Sunday's sermon is posted"}
    return {"done": False, "text": "Sunday's sermon isn't posted yet"}


def job_attendance(ctx: Ctx, due: date) -> Dict[str, Any]:
    """This week's Sunday has a count recorded that day (sunday_counted).
    Before that Sunday there's nothing to count, and nothing is read."""
    sunday = ctx.monday + timedelta(days=6)
    if ctx.today < sunday or not sunday_counted(ctx, sunday):
        return {"done": False, "text": "Sunday's count isn't in yet"}
    return {"done": True, "text": "Sunday's count is in"}


def job_shepherding(ctx: Ctx, due: date) -> Dict[str, Any]:
    """Every family drifting now has a touch logged since this week's
    Monday. No family drifting: done."""
    drift = drifting(ctx)
    if not drift:
        return {"done": True, "text": "No family is drifting"}
    reached = len(drift & touched_since(ctx, ctx.monday))
    return {"done": reached == len(drift),
            "text": f"{reached} of {_n(len(drift), 'drifting family', 'drifting families')} reached this week"}


WEEKLY: Dict[str, Callable[[Ctx, date], Dict[str, Any]]] = {
    "first_guests": job_first_guests,
    "serve_schedule": job_serve_schedule,
    "calendar": job_calendar,
    "sermons": job_sermons,
    "attendance": job_attendance,
    "shepherding": job_shepherding,
}


def week_job(ctx: Ctx, duty: str, due: date) -> Optional[Dict[str, Any]]:
    """One weekly job's answer for the login whose day is `due`: {done,
    text}, once per Ctx. None for a duty no check judges. A read that fails
    is {done: None, text: "Couldn't count just now", unread: True}."""
    fn = WEEKLY.get(duty)
    if fn is None:
        return None
    key = ("job", duty, due)
    if key not in ctx._answers:
        try:
            got = fn(ctx, due)
            ctx._answers[key] = {"done": got.get("done"), "text": got.get("text") or ""}
        except Exception:
            print(f"[church_work_checks] {ctx.b[:8]}: this week's {duty} couldn't be judged", flush=True)
            ctx._answers[key] = {"done": None, "text": UNREAD_TEXT, "unread": True}
    return ctx._answers[key]
