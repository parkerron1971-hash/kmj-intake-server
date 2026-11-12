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
    kids_checked ........ kids workers with a background check date
                          (space_leaders, church_areas' count): done at none
                          without
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
    """One church, now. Each check's answer is kept, so a check runs once."""

    def __init__(self, business: Dict[str, Any], now: Optional[datetime] = None):
        self.business = business
        self.b = str(business["id"])
        self.now = now or datetime.now(timezone.utc)
        self._answers: Dict[str, Dict[str, Any]] = {}
        self._tz = None

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


def calendar_8_weeks(ctx: Ctx) -> Dict[str, Any]:
    """Each of the next eight weeks (Monday to Sunday, this one first) with
    at least one service or event on the calendar."""
    import church_leaders_note as cln
    tz = ctx.tz
    monday = ctx.today - timedelta(days=ctx.today.weekday())
    last = monday + timedelta(days=7 * WEEKS - 1)
    lo = datetime.combine(monday, time(0), tzinfo=tz)
    hi = datetime.combine(last + timedelta(days=1), time(0), tzinfo=tz)
    try:
        days = [p["day"] for p in cln._plans(ctx.b, lo, hi, tz)] + [o["day"] for o in cln._occasions(ctx.b, monday, last, tz)]
    except HTTPException:
        raise Unread("calendar")
    weeks = {(d - monday).days // 7 for d in days if monday <= d <= last}
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
    rows = ctx.rows(f"/space_leaders?business_id=eq.{_q(ctx.b)}&select=contact_id,background_check_on&limit=500")
    if not rows:
        return {"done": None, "text": "No kids workers listed yet"}
    without = sum(1 for r in rows if not r.get("background_check_on"))
    if not without:
        return {"done": True, "text": "Every kids worker has a background check date"}
    return {"done": False, "text": f"{_n(without, 'kids worker has', 'kids workers have')} no background check date"}


def follow_up_no_one(ctx: Ctx) -> Dict[str, Any]:
    import church_leaders_note as cln
    try:
        n = cln._no_one(ctx.b)
    except HTTPException:
        raise Unread("church_follow_ups")
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
    rows = ctx.rows(f"/sermons?business_id=eq.{_q(ctx.b)}&published=eq.true&preached_on=gte.{sundays[-1].isoformat()}"
                    "&select=preached_on&limit=200")
    have = {str(r.get("preached_on") or "")[:10] for r in rows}
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
