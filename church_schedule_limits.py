"""church_schedule_limits.py — the leaders schedule, step 2: how many can be
away at once (docs/CHURCH_SCHEDULE.md, PRs S2-2 and S2-3; church_schedule.py
holds the asks, and step 2's tables are supabase/APPLY-2026-11-20-church-
schedule-limits.sql).

The platform owner, 2026-11-18: "making sure that everyone is not gone at the
same time on our services. allowing only so many people off at the same time."

    GET    /church/schedule/limits?business_id=      the numbers, the usual
                                                     service days
    PUT    /church/schedule/limits                   set one number, or the
                                                     usual service days
    GET    /church/schedule/days?business_id=&from=&to=
                                                     each service day: who is
                                                     away, how many may be,
                                                     what is full
    GET    /church/schedule/protected-days?business_id=&from=&to=
    POST   /church/schedule/protected-days           a day nobody takes off
    DELETE /church/schedule/protected-days/{id}?business_id=
    GET    /church/schedule/volunteers?business_id=&from=&to=
                                                     by department: who of its
                                                     people is away (read only;
                                                     the volunteers' own rules
                                                     come with their own PR)
    GET    /church/schedule/pairs?business_id=       two people who can't be
    POST   /church/schedule/pairs                    away together (S2-4): the
    DELETE /church/schedule/pairs/{id}?business_id=  owner and whoever oversees
                                                     the office only, reads too

WHICH DAYS COUNT (a "service day"), on the church's own clock:

  1. every day the church has planned a service (a live worship_services
     row that is not an event date)
  2. on a day with no such row, its usual service weekdays: the ones it set
     (church_schedule_settings.service_weekdays), else any weekday its own
     plans put a service on, on two days or more, from eight weeks back to
     eight weeks ahead, else Sunday
  3. every protected day
  4. an event date counts for a department's number only (only the
     volunteers' teams serve one)

THE NUMBERS. The leaders group and the office group each have one: the
church's own (1 to 99), else worked out as one in four, one at least. A
department has one only when a row says so: no row, no limit. Who is away is
counted from the facts (serve_away), never from an ask's state, each person
once: an ask still waiting is not counted and not shown, so a count never
tells anyone that someone has asked.

WHAT IT DOES TO AN ASK (church_schedule.ask and .answer call flags_for):
nothing here ever refuses one. An ask that would put a service day past the
number for the asker's group (or for their department, when they are one of
the people it counts), or that touches a protected day, is flagged
(`over_limit`, `protected_day`) and goes up (church_schedule.goes_up). "Can't
make it" and the owner's own time away are never looked at here.

PAIRS (S2-4): two people who can't be away together, set by the owner or
whoever oversees the office, and private: read by those two alone, never
named to the one asking, to anyone else who decides, or on the calendar. An
ask whose days overlap, on any day, an away date of the other of a pair (the
facts, whatever made them: "can't make it" and the owner's own count) or an
ask of theirs still waiting that was made before it, is flagged `pair` and
goes up like the rest. A pair is in force only while both of them are on the
leaders schedule; while either is off it, it is kept and does nothing.
Reading an asker's pairs is one read an ask; their other's waiting asks are
read only when there is a pair.

WHO SETS WHAT (decision 7): the leaders number, the office number, the usual
service days and the protected days are the owner's and whoever oversees the
office's. Not an Admin's. A department's number: its leader, its overseer,
the owner, whoever oversees the office, or whoever holds the serve_schedule
duty.

Step 2 has its own "are its tables there" (ready()): church_schedule.ready()
is true with step 1's tables alone. Until this says yes, nothing here is read
and every route answers 404; church_schedule behaves exactly as step 1.

Server-only tables, read and written through the service role, always by
business_id. A failed read is a 503; a failed write is a 503 with nothing
saved; every answer a write gives is worked out before the write. Every read
is paged, or bounded by a list of ids a hundred at a time.
"""
from __future__ import annotations

import re
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

import business_access
import church_over as co
import church_schedule as cs
import sb_clients
from auth_supabase import UserSession

router = APIRouter(prefix="/church", tags=["church"])

FLAGS = ("over_limit", "protected_day", "pair")     # what this module flags, in church_schedule.UP_FLAGS's order
LIMIT_MAX = 99
NAME_MAX = 80
PAIR_NOTE_MAX = 140         # church_away_pairs.note
NEAR_DAYS = 56              # eight weeks: how far the usual weekdays are worked out, and an open day looked for
PICTURE_DAYS = cs.MAX_DAYS + 2 * NEAR_DAYS + 2      # the widest window anything here reads
SERVE_DUTY = "serve_schedule"
WEEKDAY_DEFAULT = (7,)      # Sunday (sunday_planning's own rule)
READY_SECONDS = 600.0       # the tables, once there, are asked about again in ten minutes
MISSING_SECONDS = 60.0      # not there (or couldn't tell): asked again a minute later
_STATE: Dict[str, Any] = {"yes": None, "at": 0.0}
# Tests pin the answer (conftest: False, so every other suite reads as a
# database with step 1 alone); production leaves it None and asks.
_FORCE: Optional[bool] = None

NOT_SETTER = cs.NOT_SETTER
NOT_DEPT_SETTER = ("Only the department's leader, whoever is over it, the owner, whoever oversees the office, or "
                   "whoever keeps Who serves when sets this number.")
NOT_READER = "That's for the people on the leaders schedule and whoever keeps Who serves when."
NO_DEPT = "That department isn't one of this church's."
BAD_NUMBER = f"A number from 1 to {LIMIT_MAX}, or nothing to go back to what's worked out."
BAD_WEEKDAYS = "The usual service days are a list of days, 1 for Monday to 7 for Sunday."
BAD_WINDOW = "Pick up to three months"
BAD_DAY = "A day is like 2026-11-20"
PAST_DAY = "Pick today or a day still to come."
BAD_NAME = f"Give the day a name, {NAME_MAX} letters at most."
ONE_THING = "Say one thing to set: a group's number, a department's number, or the usual service days."
NO_DAY = "That isn't one of this church's protected days."
NOT_PAIRS = "Only the owner, or whoever oversees the office, sees or changes who can't be away together."
PAIR_SELF = "Pick two different people."
PAIR_OFF = "Both of them need to be on the leaders schedule first."
PAIR_TWICE = "Those two are already a pair."
PAIR_NOTE = f"Keep the note to {PAIR_NOTE_MAX} letters."
NO_PAIR = "That isn't one of this church's pairs."


# ─── Are step 2's tables there ────────────────────────────────────────

def ready() -> bool:
    """True once church_protected_days answers (step 2's file is one
    transaction, so one table says all of it). church_schedule.ready's rule:
    only "no such table" says it isn't there; a blip keeps the last answer,
    and with none yet reads as not there (everything behaves as step 1 for a
    minute). Asked only where step 1 is already there and the switch open."""
    if _FORCE is not None:
        return _FORCE
    if not sb_clients.sb_url():
        return False    # no database to ask (a script)
    now = clock.monotonic()
    yes, at = _STATE["yes"], _STATE["at"]
    if yes is not None and now - at < (READY_SECONDS if yes else MISSING_SECONDS):
        return yes
    try:
        rows = sb_clients.sb_get_as_service("/church_protected_days?select=id&limit=1")
        err = sb_clients.last_error() if rows is None else None
    except Exception:  # noqa: BLE001 — a fake or a broken client is "couldn't tell"
        rows, err = None, None
    if isinstance(rows, list):
        got = True
    elif err and cs._no_table(err):
        got = False
    else:
        got = bool(yes)
    _STATE["yes"], _STATE["at"] = got, now
    return got


# ─── What the church set, and what is worked out ──────────────────────

def _number(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= LIMIT_MAX else None


def _weekdays(v: Any) -> Optional[List[int]]:
    if not isinstance(v, list):
        return None
    days = sorted({x for x in v if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 7})
    return days or None


def _said(ch: co.Church) -> Dict[str, Any]:
    """What the church itself set: {leaders, office, weekdays}, each None
    until it says otherwise. Read once a request; a failed read is a 503,
    never the worked-out number taken for the church's own."""
    def load() -> Dict[str, Any]:
        rows = cs._need(f"/church_schedule_settings?business_id=eq.{cs._q(ch.b)}"
                        f"&select=leaders_limit,office_limit,service_weekdays&limit=1")
        r = rows[0] if rows else {}
        return {"leaders": _number(r.get("leaders_limit")), "office": _number(r.get("office_limit")),
                "weekdays": _weekdays(r.get("service_weekdays"))}
    return ch._got("schedule_said", load)


def default_limit(people: int) -> int:
    """One in four, one at least."""
    return max(1, int(people) // 4)


def _span(ch: co.Church, lo: date, hi: date) -> Tuple[str, str]:
    """`lo` to `hi`, whole days on the church's clock, as two moments."""
    tz = ch.tz
    try:
        a = datetime.combine(lo, time(0), tzinfo=tz)
        z = datetime.combine(hi + timedelta(days=1), time(0), tzinfo=tz)
        return cs._iso(a), cs._iso(z)
    except OverflowError:
        raise HTTPException(400, BAD_DAY)


def _services(ch: co.Church, lo: date, hi: date) -> List[Tuple[date, str, str]]:
    """The church's own planned services and event dates from `lo` to `hi`:
    (the day on the church's clock, service | event, its title). Live rows
    only (not a template, not archived), read a page at a time."""
    import serve_dates as sd
    a, z = _span(ch, lo, hi)
    kind = ",kind" if sd.ready() else ""        # before the event-dates columns, every row is a service
    rows = cs._every(f"/worship_services?business_id=eq.{cs._q(ch.b)}&archived_at=is.null&is_template=eq.false"
                     f"&starts_at=gte.{cs._q(a)}&starts_at=lt.{cs._q(z)}&select=id,title,starts_at{kind}")
    out: List[Tuple[date, str, str]] = []
    tz = ch.tz
    for r in rows:
        try:
            at = datetime.fromisoformat(str(r.get("starts_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        day = at.astimezone(tz).date()
        if lo <= day <= hi:
            out.append((day, sd.EVENT if kind and sd.is_event(r) else sd.SERVICE, cs._plain(r.get("title"))))
    return sorted(out, key=lambda x: x[0])


def _worked_out(services: Iterable[Tuple[date, str, str]], today: date) -> List[int]:
    """The usual service weekdays from the church's own plans: any weekday
    with a planned service on two days or more, from eight weeks back to
    eight weeks ahead; else Sunday."""
    import serve_dates as sd
    seen: Dict[int, Set[date]] = {}
    for day, kind, _title in services:
        if kind == sd.SERVICE and abs((day - today).days) <= NEAR_DAYS:
            seen.setdefault(day.isoweekday(), set()).add(day)
    return sorted(w for w, days in seen.items() if len(days) >= 2) or list(WEEKDAY_DEFAULT)


def usual_weekdays(ch: co.Church, now: Optional[datetime] = None) -> List[int]:
    """The church's usual service days, 1 Monday to 7 Sunday: what it set,
    else worked out from its own plans, else Sunday."""
    said = _said(ch)["weekdays"]
    if said:
        return said
    today = cs._today(ch, now)
    return _worked_out(_services(ch, today - timedelta(days=NEAR_DAYS), today + timedelta(days=NEAR_DAYS)), today)


# ─── A department's people ────────────────────────────────────────────

def _departments(ch: co.Church) -> List[Dict[str, Any]]:
    """The church's active departments (none with its map closed)."""
    m = ch.map
    return list(m.active()) if m else []


def _department(ch: co.Church, department_id: Any) -> Optional[Dict[str, Any]]:
    did = str(department_id or "")
    return next((d for d in _departments(ch) if str(d.get("id")) == did), None) if did else None


def _teams(ch: co.Church) -> Dict[str, str]:
    """The church's Sunday teams: group id -> name. A team is a group with a
    serve_teams row; only an active group counts."""
    def load() -> Dict[str, str]:
        ids = [str(r["group_id"]) for r in cs._every(
            f"/serve_teams?business_id=eq.{cs._q(ch.b)}&select=group_id", key="group_id") if r.get("group_id")]
        out: Dict[str, str] = {}
        for part in co._chunks(ids, co.IDS_PER_READ):
            for g in cs._need(f"/groups?business_id=eq.{cs._q(ch.b)}&id=in.({cs._in(part)})&active=eq.true"
                              f"&select=id,name&limit={co.IDS_PER_READ}"):
                out[str(g["id"])] = cs._plain(g.get("name"))
        return out
    return ch._got("schedule_teams", load)


def _department_teams(ch: co.Church, d: Dict[str, Any]) -> List[str]:
    """The Sunday teams that hang from a department: as one of its groups,
    or by name as one of its Serve options."""
    teams = _teams(ch)
    by_name = {name.casefold(): gid for gid, name in teams.items() if name}
    out: List[str] = []
    for u in d.get("units") or []:
        gid = None
        if u.get("kind") == "group":
            gid = str(u.get("ref") or "")
        elif u.get("kind") == "serve_option":
            gid = by_name.get(cs._plain(u.get("label")).casefold())
        if gid and gid in teams and gid not in out:
            out.append(gid)
    return out


def _team_people(ch: co.Church, gid: str) -> Set[str]:
    """Everyone on one Sunday team (its leaders too), a page at a time."""
    kept: Dict[str, Set[str]] = ch._memo.setdefault("schedule_team_people", {})
    if gid not in kept:
        kept[gid] = {str(r["contact_id"]) for r in cs._every(
            f"/group_members?business_id=eq.{cs._q(ch.b)}&group_id=eq.{cs._q(gid)}&select=contact_id",
            key="contact_id") if r.get("contact_id")}
    return kept[gid]


def department_people(ch: co.Church, department_id: Any) -> Set[str]:
    """Who a department's number counts: everyone on its Sunday teams, each
    once. Empty for a department with no team, or one that isn't this
    church's."""
    d = _department(ch, department_id)
    out: Set[str] = set()
    for gid in (_department_teams(ch, d) if d else []):
        out |= _team_people(ch, gid)
    return out


def _department_limits(ch: co.Church) -> Dict[str, int]:
    """Each active department's own number. No row, no limit (decision 9)."""
    def load() -> Dict[str, int]:
        live = {str(d["id"]) for d in _departments(ch)}
        if not live:
            return {}
        rows = cs._every(f"/church_schedule_department_limits?business_id=eq.{cs._q(ch.b)}"
                         f"&select=department_id,at_most", key="department_id")
        return {str(r["department_id"]): r["at_most"] for r in rows
                if str(r.get("department_id")) in live and _number(r.get("at_most"))}
    return ch._got("schedule_department_limits", load)


# ─── The picture: one window, read once ───────────────────────────────

class Picture:
    """Everything the limit needs for one window of days, read once:

      days ........ {day: {"day", "kind": service | event | protected,
                    "name"}}: the days that count. An `event` day counts for
                    a department's number only
      people ...... {"leaders": set, "office": set}: the roster as it stands
      limits ...... {"leaders": n, "office": n}: the church's number, else
                    worked out
      departments . {id: {"id", "name", "at_most", "people": set}}: only the
                    departments that have a number
      away ........ {person: [(first day, last day)]}: THE FACTS (serve_away)
                    and nothing else. An ask still waiting is not in here
      pairs ....... {person: {the other of each pair in force}}: only for the
                    people the picture was asked to read pairs for (`who`),
                    else empty. PRIVATE: never handed to a page whole
      held ........ {the other of a pair: [(first, last, created_at)]}: their
                    asks still waiting in the window, and nobody else's. Read
                    only when there is a pair, and never counted as away
    """
    __slots__ = ("lo", "hi", "today", "roster", "people", "limits", "weekdays", "worked_out", "days", "departments",
                 "away", "pairs", "held")

    def group_of(self, cid: Any) -> Optional[str]:
        return self.roster.group_of(cid)

    def away_on(self, day: date, people: Iterable[str], but: Any = "") -> Set[str]:
        """Which of `people` have an away date on `day`, each once; never
        `but` (the one asking: their own days don't count against them)."""
        but = str(but or "")
        return {c for c in people if c != but and any(a <= day <= z for a, z in self.away.get(c, ()))}

    def pair_hits(self, cid: Any, first: date, last: date, before: Any = None) -> Set[str]:
        """The other of each of this person's pairs whose time away overlaps
        `first` to `last` on any day: an away date (the facts, whatever made
        them), or an ask still waiting that was made before `before` (the
        recheck at a yes: an ask is never sent up by one made after it; with
        no `before`, every one waiting). PRIVATE: who it is goes only to
        whoever may give the exception (member_portal_dates._limits)."""
        out: Set[str] = set()
        for o in self.pairs.get(str(cid or ""), ()):
            if any(a <= last and first <= z for a, z in self.away.get(o, ())):
                out.add(o)
            elif any(a <= last and first <= z and _made_before(at, before) for a, z, at in self.held.get(o, ())):
                out.add(o)
        return out

    def counted(self, lo: Optional[date] = None, hi: Optional[date] = None) -> List[Dict[str, Any]]:
        lo, hi = lo or self.lo, hi or self.hi
        return [self.days[d] for d in sorted(self.days) if lo <= d <= hi]


def picture(ch: co.Church, lo: date, hi: date, *, now: Optional[datetime] = None,
            who: Optional[Iterable[Any]] = None) -> Picture:
    """The window `lo` to `hi` (PICTURE_DAYS at most). Every read here is
    paged or bounded; a read that fails is a 503. `who`: the people whose
    pairs it reads too (an ask's asker); none named, no pair is read."""
    if hi < lo or (hi - lo).days > PICTURE_DAYS:
        raise HTTPException(400, cs.BAD_DAYS)
    import church_map
    import serve_dates as sd
    with church_map.once():
        p = Picture()
        p.lo, p.hi, p.today = lo, hi, cs._today(ch, now)
        p.roster = cs.roster(ch)
        p.people = {"leaders": set(p.roster.leaders), "office": set(p.roster.office)}
        said = _said(ch)
        p.limits = {g: said[g] or default_limit(len(p.people[g])) for g in cs.ROSTER_GROUPS}
        # One read of the plans covers the window and, when the usual days
        # have to be worked out, the eight weeks either side of today.
        a, z = lo, hi
        if not said["weekdays"]:
            a, z = min(lo, p.today - timedelta(days=NEAR_DAYS)), max(hi, p.today + timedelta(days=NEAR_DAYS))
        services = _services(ch, a, z)
        p.worked_out = not said["weekdays"]
        p.weekdays = said["weekdays"] or _worked_out(services, p.today)
        protected = {cs._day(r.get("day")): cs._plain(r.get("name")) for r in cs._every(
            f"/church_protected_days?business_id=eq.{cs._q(ch.b)}&day=gte.{lo.isoformat()}&day=lte.{hi.isoformat()}"
            f"&select=id,day,name")}
        planned: Dict[date, str] = {}
        events: Dict[date, str] = {}
        for day, kind, title in services:
            (events if kind == sd.EVENT else planned).setdefault(day, title)
        p.days = {}
        day = lo
        while day <= hi:
            if day in protected:
                p.days[day] = {"day": day, "kind": "protected", "name": protected[day]}
            elif day in planned or day.isoweekday() in p.weekdays:
                p.days[day] = {"day": day, "kind": "service", "name": planned.get(day, "")}
            elif day in events:
                p.days[day] = {"day": day, "kind": "event", "name": events[day]}
            if day == date.max:
                break
            day += timedelta(days=1)
        numbers = _department_limits(ch)
        p.departments = {}
        for d in _departments(ch):
            did = str(d["id"])
            if did in numbers:
                p.departments[did] = {"id": did, "name": cs._plain(d.get("name")) or "A department",
                                      "at_most": numbers[did], "people": department_people(ch, did)}
        everyone = set(p.roster.people())
        for d in p.departments.values():
            everyone |= d["people"]
        p.away = _facts(ch, everyone, lo, hi)
        # Pairs (S2-4): one read for the people asked about, who must be on
        # the schedule; their other's waiting asks only when there is a pair.
        # The other's away dates are already in p.away (they are on it too).
        p.pairs, p.held = {}, {}
        asked = {str(c) for c in (who or ()) if c} & p.roster.people()
        if asked:
            p.pairs = _partners(ch, asked, p.roster.people())
            others: Set[str] = set().union(*p.pairs.values()) if p.pairs else set()
            if others:
                p.held = _waiting(ch, others, lo, hi)
        return p


def _made_before(at: Any, before: Any) -> bool:
    """Whether a waiting ask made at `at` was made before `before` (or at
    the same moment: both count). With no `before`, every one does; a moment
    that can't be read counts too: a pair is never missed for a clock."""
    if before in (None, ""):
        return True

    def moment(v: Any) -> Optional[datetime]:
        s = str(v or "").replace("Z", "+00:00")
        m = re.match(r"^(.*?T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(.*)$", s)
        if m:                                   # any number of digits after the second (Postgres trims them)
            s = m.group(1) + (f".{(m.group(2) + '000000')[:6]}" if m.group(2) else "") + m.group(3)
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    a, b = moment(at), moment(before)
    return a is None or b is None or a <= b


def _partners(ch: co.Church, who: Set[str], on: Set[str]) -> Dict[str, Set[str]]:
    """{person in `who`: the other of each of their pairs in force}. In
    force: both are on the leaders schedule today (`on`); a pair with
    someone since taken off it is kept and does nothing. A hundred people a
    read, each read a page at a time, both columns at once (the table keeps
    each pair once, the smaller id first)."""
    out: Dict[str, Set[str]] = {}
    for part in co._chunks(who, co.IDS_PER_READ):
        ids = cs._in(part)
        for r in cs._every(f"/church_away_pairs?business_id=eq.{cs._q(ch.b)}"
                           f"&or=(a_contact_id.in.({ids}),b_contact_id.in.({ids}))"
                           f"&select=id,business_id,a_contact_id,b_contact_id"):
            a, b = str(r.get("a_contact_id") or ""), str(r.get("b_contact_id") or "")
            if str(r.get("business_id")) != ch.b or not a or not b or a == b or a not in on or b not in on:
                continue
            for x, y in ((a, b), (b, a)):
                if x in who:
                    out.setdefault(x, set()).add(y)
    return out


def _waiting(ch: co.Church, people: Set[str], lo: date, hi: date) -> Dict[str, List[Tuple[date, date, str]]]:
    """These people's asks still waiting that touch `lo` to `hi`: {person:
    [(first, last, created_at)]}. Who, which days and when it was made:
    never a reason, a kind, or who it went to. A hundred people a read,
    each read a page at a time."""
    out: Dict[str, List[Tuple[date, date, str]]] = {}
    window = f"&ends_on=gte.{lo.isoformat()}&starts_on=lte.{hi.isoformat()}"
    for part in co._chunks(people, co.IDS_PER_READ):
        for r in cs._every(f"/church_away_asks?business_id=eq.{cs._q(ch.b)}&state=eq.asked"
                           f"&contact_id=in.({cs._in(part)}){window}"
                           f"&select=id,business_id,contact_id,state,starts_on,ends_on,created_at"):
            cid = str(r.get("contact_id") or "")
            first, last = cs._day(r.get("starts_on")), cs._day(r.get("ends_on"))
            if str(r.get("business_id")) == ch.b and r.get("state") == "asked" and cid in people and first and last:
                out.setdefault(cid, []).append((first, last, str(r.get("created_at") or "")))
    return out


def _facts(ch: co.Church, people: Iterable[str], lo: date, hi: date) -> Dict[str, List[Tuple[date, date]]]:
    """THE FACTS for these people from `lo` to `hi`: {person: [(first day,
    last day)]}, from serve_away and nothing else (never an ask). A hundred
    people a read, each read a page at a time."""
    people = set(people)
    out: Dict[str, List[Tuple[date, date]]] = {}
    window = f"&ends_on=gte.{lo.isoformat()}&starts_on=lte.{hi.isoformat()}"
    for part in co._chunks(sorted(people), co.IDS_PER_READ):
        for f in cs._every(f"/serve_away?business_id=eq.{cs._q(ch.b)}&contact_id=in.({cs._in(part)}){window}"
                           f"&select=id,contact_id,starts_on,ends_on"):
            first, last = cs._day(f.get("starts_on")), cs._day(f.get("ends_on"))
            cid = str(f.get("contact_id") or "")
            if first and last and cid in people:
                out.setdefault(cid, []).append((first, last))
    return out


def service_days(ch: co.Church, lo: date, hi: date) -> List[Dict[str, Any]]:
    """The days that count from `lo` to `hi`: [{day, kind, name}]."""
    return picture(ch, lo, hi).counted()


def limit_for(ch: co.Church, grp: str, department_id: Any = None) -> Optional[int]:
    """How many may be away at once: a department's own number (None: it has
    none, so no limit), else the group's (the church's, else one in four)."""
    if department_id:
        return _department_limits(ch).get(str(department_id))
    if grp not in cs.ROSTER_GROUPS:
        return None
    r = cs.roster(ch)
    return _said(ch)[grp] or default_limit(len(r.leaders if grp == "leaders" else r.office))


def away_on(ch: co.Church, day: date, grp: str, department_id: Any = None) -> Set[str]:
    """Who of a group (or, with `department_id`, of that department's
    people, whether or not it has a number) has an away date on `day`: the
    facts only, each person once. A department's people are read for
    themselves: a picture holds the away dates of a department only when
    it has a number."""
    if department_id:
        gone = _facts(ch, department_people(ch, department_id), day, day)
        return {c for c, spans in gone.items() if any(a <= day <= z for a, z in spans)}
    p = picture(ch, day, day)
    return p.away_on(day, p.people.get(grp, set()))


# ─── What an ask would do ─────────────────────────────────────────────

def flags_of(p: Picture, cid: Any, first: date, last: date, department_id: Any = None, *, before: Any = None,
             pairs: bool = True) -> Dict[str, Any]:
    """What asking for `first` to `last` would run into, for one person, from
    a picture already read: {"flags": [...], "why": [...]}.

    `why` has one entry a day and cause, soonest first: {"flag":
    "protected_day", "day", "name"} for a protected day, and {"flag":
    "over_limit", "day", "of": leaders | office | department, "name" (a
    department's), "away", "at_most"} where as many of that group are
    already away as may be. Counts only: who is away is on the calendar for
    those who may see it. The asker's own away dates never count against
    them, and they are held to a department's number only when they are one
    of the people it counts.

    Then, last, at most one {"flag": "pair"} (S2-4) when the other of one of
    their pairs has time away on any of the same days (Picture.pair_hits,
    with `before`). It carries no day and no name: which days are the
    other's, and who they are, never leave here in `why`. Only a picture
    asked to read this person's pairs (`who`) can find one; `pairs=False`
    never looks."""
    cid = str(cid or "")
    grp = p.group_of(cid)
    dept = p.departments.get(str(department_id or ""))
    if dept and cid not in dept["people"]:
        dept = None
    why: List[Dict[str, Any]] = []
    for d in p.counted(first, last):
        day = d["day"]
        if d["kind"] == "protected":
            why.append({"flag": "protected_day", "day": day.isoformat(), "name": d["name"]})
        if grp and d["kind"] != "event":
            n = len(p.away_on(day, p.people[grp], cid))
            if n >= p.limits[grp]:
                why.append({"flag": "over_limit", "day": day.isoformat(), "of": grp, "name": "", "away": n,
                            "at_most": p.limits[grp]})
        if dept:
            n = len(p.away_on(day, dept["people"], cid))
            if n >= dept["at_most"]:
                why.append({"flag": "over_limit", "day": day.isoformat(), "of": "department", "name": dept["name"],
                            "away": n, "at_most": dept["at_most"]})
    if pairs and p.pairs.get(cid) and p.pair_hits(cid, first, last, before):
        why.append({"flag": "pair"})
    return {"flags": [f for f in FLAGS if any(w["flag"] == f for w in why)], "why": why}


def flags_for(ch: co.Church, asker_cid: Any, starts_on: date, ends_on: date, *, department_id: Any = None,
              now: Optional[datetime] = None, before: Any = None) -> Dict[str, Any]:
    """flags_of, read fresh for exactly these days: what church_schedule.ask
    asks before it writes, and church_schedule.answer again at a yes (with
    `before`, the ask's own created_at: the other of a pair's waiting asks
    made after it never send it up)."""
    return flags_of(picture(ch, starts_on, ends_on, now=now, who=[asker_cid]), asker_cid, starts_on, ends_on,
                    department_id, before=before)


def nearest_open(p: Picture, cid: Any, first: date, last: date, department_id: Any = None) -> Dict[str, Optional[str]]:
    """The nearest service day before `first` (today or later) and after
    `last` that this person could ask for without a flag: {"before",
    "after"}, each a day or None when the picture holds none. A pair is
    never looked at here: skipping the days the other of a pair is away
    would say which days those are."""
    def is_open(d: Dict[str, Any]) -> bool:
        return d["kind"] == "service" and not flags_of(p, cid, d["day"], d["day"], department_id, pairs=False)["flags"]
    before = [d["day"] for d in p.counted() if p.today <= d["day"] < first and is_open(d)]
    after = [d["day"] for d in p.counted() if d["day"] > last and is_open(d)]
    return {"before": max(before).isoformat() if before else None, "after": min(after).isoformat() if after else None}


def look(ch: co.Church, cid: Any, first: date, last: date, *, department_id: Any = None,
         now: Optional[datetime] = None) -> Dict[str, Any]:
    """Before an ask is sent (the Dates page): what these days would run
    into, the nearest open service days either side, and who it would go up
    to. {"flags", "why", "open": {"before", "after"}, "up": {kind, id,
    name}}. Reads; never writes. A pair is in `why` as {"flag": "pair"}
    alone (flags_of), and with nothing else in the way no open days are
    offered: they would be guesses about someone else's time away."""
    today = cs._today(ch, now)
    try:
        lo = min(first, max(today, first - timedelta(days=NEAR_DAYS)))
        hi = last + timedelta(days=NEAR_DAYS)
    except OverflowError:
        raise HTTPException(400, cs.BAD_DAYS)
    p = picture(ch, lo, hi, now=now, who=[cid])
    got = flags_of(p, cid, first, last, department_id)
    days_in_the_way = [f for f in got["flags"] if f != "pair"]
    return {**got, "open": nearest_open(p, cid, first, last, department_id) if days_in_the_way
            else {"before": None, "after": None}, "up": cs.goes_up(ch, cid)}


# ─── Who reads and who sets ───────────────────────────────────────────

def _keeps_serving(ch: co.Church, me: Dict[str, Any]) -> bool:
    """An office login that holds the serve_schedule duty (Who serves when)."""
    return me["kind"] == co.LOGIN and SERVE_DUTY in ch.held(str(me["id"]))


def _runs(ch: co.Church, me: Dict[str, Any], d: Dict[str, Any]) -> bool:
    """An office login whose own person leads this department, or is over
    it. (From the member app, as a person, comes later.)"""
    if me["kind"] != co.LOGIN:
        return False
    mine = ch.persons_of(me)
    return bool(mine & {str(d.get("leader_contact_id") or ""), str(d.get("overseer_contact_id") or "")} - {""})


def may_set_limit(ch: co.Church, me: Dict[str, Any], department_id: Any = None) -> bool:
    """A group's number and the usual service days: the owner, or whoever
    oversees the office (not an Admin: decision 7). A department's number:
    its leader, its overseer, the owner, whoever oversees the office, or
    whoever holds the serve_schedule duty."""
    if cs.over_all(ch, me):
        return True
    if not department_id:
        return False
    d = _department(ch, department_id)
    return bool(d) and (_keeps_serving(ch, me) or _runs(ch, me, d))


def _reader(ch: co.Church, me: Dict[str, Any]) -> str:
    """What `me` may read here: `all` (on the leaders schedule, the owner,
    whoever oversees the office), `departments` (whoever keeps Who serves
    when, and no more), or a 403."""
    if cs.over_all(ch, me) or (ch.persons_of(me) & cs.roster(ch).people()):
        return "all"
    if _keeps_serving(ch, me):
        return "departments"
    raise HTTPException(403, NOT_READER)


def limits(ch: co.Church, me: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """GET limits: {leaders: {at_most, set, people}, office: {…},
    departments: [{id, name, at_most | null, people, can_set}],
    service_weekdays, worked_out, can_set}. `set` is the church's own number
    (null: `at_most` is worked out). Whoever keeps Who serves when, and is
    not on the leaders schedule, gets the departments only."""
    import church_map
    with church_map.once():
        what = _reader(ch, me)
        r = cs.roster(ch)
        said = _said(ch)
        numbers = _department_limits(ch)
        depts = [{"id": str(d["id"]), "name": cs._plain(d.get("name")) or "A department",
                  "at_most": numbers.get(str(d["id"])), "people": len(department_people(ch, d["id"])),
                  "can_set": may_set_limit(ch, me, d["id"])} for d in _departments(ch)]

        def group(g: str) -> Optional[Dict[str, Any]]:
            if what != "all":
                return None
            n = len(r.leaders if g == "leaders" else r.office)
            return {"at_most": said[g] or default_limit(n), "set": said[g], "people": n}
        return {"leaders": group("leaders"), "office": group("office"), "departments": depts,
                "service_weekdays": usual_weekdays(ch, now), "worked_out": not said["weekdays"],
                "can_set": may_set_limit(ch, me)}


def _at_most(v: Any) -> Optional[int]:
    if v is None:
        return None
    if _number(v) is None:
        raise HTTPException(400, BAD_NUMBER)
    return v


def set_limit(ch: co.Church, me: Dict[str, Any], body: Dict[str, Any], *,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """PUT limits. One of: {group: leaders | office, at_most | null},
    {department_id, at_most | null}, {service_weekdays | null}. Null puts
    it back (a group's number and the usual days to what is worked out; a
    department to no limit). Answers with the limits as they stand after,
    worked out BEFORE the write: a read that fails is a 503 with nothing
    saved, and nothing after the write can fail on a read."""
    body = body or {}
    named = [k for k in ("group", "department_id", "service_weekdays") if k in body]
    if len(named) != 1:
        raise HTTPException(400, ONE_THING)
    what = named[0]
    if what != "service_weekdays" and "at_most" not in body:
        raise HTTPException(400, BAD_NUMBER)        # nothing said is not "put it back": that is an explicit null
    uid = str(me["id"]) if me["kind"] == co.LOGIN else None
    stamp = cs._iso(cs._now())
    import church_map
    with church_map.once():
        if what == "department_id":
            did = cs._uuid(body.get("department_id"), "department")
            if not _department(ch, did):
                raise HTTPException(404, NO_DEPT)
            if not may_set_limit(ch, me, did):
                raise HTTPException(403, NOT_DEPT_SETTER)
            n = _at_most(body.get("at_most"))
            view = limits(ch, me, now=now) if _may_read(ch, me) else {"departments": [
                {"id": did, "at_most": None, "people": len(department_people(ch, did)), "can_set": True,
                 "name": cs._plain(_department(ch, did).get("name")) or "A department"}]}
            for d in view["departments"]:
                if d["id"] == did:
                    d["at_most"] = n
        else:
            if not may_set_limit(ch, me):
                raise HTTPException(403, NOT_SETTER)
            view = limits(ch, me, now=now)
            if what == "group":
                grp = body.get("group")
                if grp not in cs.ROSTER_GROUPS:
                    raise HTTPException(400, "Say which group: leaders, or office")
                n = _at_most(body.get("at_most"))
                view[grp] = {"at_most": n or default_limit(view[grp]["people"]), "set": n,
                             "people": view[grp]["people"]}
            else:
                raw = body.get("service_weekdays")
                days = None
                if raw is not None:
                    days = _weekdays(raw)
                    if not isinstance(raw, list) or not days or len(days) != len(raw):
                        raise HTTPException(400, BAD_WEEKDAYS)
                if days:
                    view["service_weekdays"], view["worked_out"] = days, False
                else:
                    today = cs._today(ch, now)
                    view["service_weekdays"] = _worked_out(
                        _services(ch, today - timedelta(days=NEAR_DAYS), today + timedelta(days=NEAR_DAYS)), today)
                    view["worked_out"] = True
    if what == "department_id":
        if n is None:
            ok = sb_clients.sb_delete_as_service(
                f"/church_schedule_department_limits?department_id=eq.{cs._q(did)}&business_id=eq.{cs._q(ch.b)}")
        else:
            saved = sb_clients.sb_post_as_service(
                "/church_schedule_department_limits?on_conflict=department_id",
                {"department_id": did, "business_id": ch.b, "at_most": n, "set_by_user_id": uid,
                 "set_by_contact_id": None, "updated_at": stamp},
                prefer="resolution=merge-duplicates,return=representation")
            ok = isinstance(saved, list) and bool(saved)
        ch._memo.pop("schedule_department_limits", None)
    else:
        row = {"business_id": ch.b, "updated_by": uid, "updated_at": stamp}
        row.update({f"{grp}_limit": n} if what == "group" else {"service_weekdays": days})
        saved = sb_clients.sb_post_as_service("/church_schedule_settings?on_conflict=business_id", row,
                                              prefer="resolution=merge-duplicates,return=representation")
        ok = isinstance(saved, list) and bool(saved)
        ch._memo.pop("schedule_said", None)
    if not ok:
        raise HTTPException(503, cs.UNSAVED)
    return view


def _may_read(ch: co.Church, me: Dict[str, Any]) -> bool:
    try:
        _reader(ch, me)
        return True
    except HTTPException as e:
        if e.status_code != 403:
            raise
        return False


def _who(ch: co.Church, ids: Iterable[str]) -> List[Dict[str, str]]:
    ids = list(ids)
    names = ch.names(ids)
    return sorted(({"contact_id": c, "name": names.get(c, "Someone")} for c in ids),
                  key=lambda x: (x["name"].casefold(), x["contact_id"]))


def days(ch: co.Church, me: Dict[str, Any], lo: date, hi: date, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """GET days: each day that counts from `lo` to `hi` (three months at
    most): {from, to, days: [{day, kind, name, leaders: {away, at_most,
    full, who}, office: {…}, departments: [{id, name, away, at_most,
    full}]}]}. Counts and names only, FROM THE FACTS: an ask still waiting
    is not counted and not named, so nothing here says that someone has
    asked. Whoever keeps Who serves when, and is not on the leaders
    schedule, gets the departments only (`leaders` and `office` null). An
    event date carries the departments only for everyone."""
    if hi < lo or (hi - lo).days > cs.WINDOW_DAYS:
        raise HTTPException(400, BAD_WINDOW)
    import church_map
    with church_map.once():
        what = _reader(ch, me)
        p = picture(ch, lo, hi, now=now)
        rows = []
        for d in p.counted():
            day = d["day"]

            def group(g: str) -> Optional[Dict[str, Any]]:
                if what != "all" or d["kind"] == "event":
                    return None
                gone = p.away_on(day, p.people[g])
                return {"away": len(gone), "at_most": p.limits[g], "full": len(gone) >= p.limits[g],
                        "who": _who(ch, gone)}
            depts = []
            for x in p.departments.values():
                n = len(p.away_on(day, x["people"]))
                depts.append({"id": x["id"], "name": x["name"], "away": n, "at_most": x["at_most"],
                              "full": n >= x["at_most"]})
            rows.append({"day": day.isoformat(), "kind": d["kind"], "name": d["name"], "leaders": group("leaders"),
                         "office": group("office"), "departments": depts})
        return {"from": lo.isoformat(), "to": hi.isoformat(), "days": rows}


# ─── Protected days ───────────────────────────────────────────────────

def _protected_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(r.get("id")), "day": str(r.get("day") or "")[:10], "name": cs._plain(r.get("name"))}


def protected_days(ch: co.Church, me: Dict[str, Any], lo: date, hi: date) -> Dict[str, Any]:
    """GET protected-days: {days: [{id, day, name}], can_change}, soonest
    first. For someone on the leaders schedule, the owner and whoever
    oversees the office; whoever keeps Who serves when reads them too."""
    if hi < lo or (hi - lo).days > PICTURE_DAYS:
        raise HTTPException(400, cs.BAD_DAYS)
    import church_map
    with church_map.once():
        _reader(ch, me)
        rows = cs._every(f"/church_protected_days?business_id=eq.{cs._q(ch.b)}&day=gte.{lo.isoformat()}"
                         f"&day=lte.{hi.isoformat()}&select=id,business_id,day,name")
        rows = [r for r in rows if str(r.get("business_id")) == ch.b]
        return {"days": sorted((_protected_row(r) for r in rows), key=lambda x: x["day"]),
                "can_change": cs.over_all(ch, me)}


def add_protected(ch: co.Church, me: Dict[str, Any], body: Dict[str, Any], *,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """A day nobody takes off: the owner, or whoever oversees the office
    (403 for anyone else, an Admin too). Today or later, with a short name.
    One row a date: naming a day again changes its name. An ask already
    waiting on that day is looked at again when someone says yes to it."""
    import church_map
    with church_map.once():
        if not cs.over_all(ch, me):
            raise HTTPException(403, NOT_SETTER)
        day = cs._day((body or {}).get("day"))
        if not day:
            raise HTTPException(400, BAD_DAY)
        if day < cs._today(ch, now):
            raise HTTPException(400, PAST_DAY)
        name = cs._plain((body or {}).get("name"))
        if not name or len(name) > NAME_MAX:
            raise HTTPException(400, BAD_NAME)
    saved = sb_clients.sb_post_as_service(
        "/church_protected_days?on_conflict=business_id,day",
        {"business_id": ch.b, "day": day.isoformat(), "name": name, "created_by": str(me["id"])},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        raise HTTPException(503, cs.UNSAVED)
    return {"id": str(saved[0]["id"]), "day": day.isoformat(), "name": name}


def drop_protected(ch: co.Church, me: Dict[str, Any], day_id: Any) -> Dict[str, Any]:
    """Take a protected day off: the owner, or whoever oversees the office.
    Read first, so one that isn't this church's is a 404 and the answer says
    what was removed. A yes already given over it keeps its exception."""
    import church_map
    with church_map.once():
        if not cs.over_all(ch, me):
            raise HTTPException(403, NOT_SETTER)
        did = cs._uuid(day_id, "day")
        rows = cs._need(f"/church_protected_days?id=eq.{cs._q(did)}&business_id=eq.{cs._q(ch.b)}"
                        f"&select=id,business_id,day,name&limit=1")
        if not rows or str(rows[0].get("business_id")) != ch.b:
            raise HTTPException(404, NO_DAY)
    if not sb_clients.sb_delete_as_service(
            f"/church_protected_days?id=eq.{cs._q(did)}&business_id=eq.{cs._q(ch.b)}"):
        raise HTTPException(503, cs.UNSAVED)
    return _protected_row(rows[0])


# ─── By department: who of its people is away ─────────────────────────

def volunteers(ch: co.Church, me: Dict[str, Any], lo: date, hi: date) -> Dict[str, Any]:
    """GET volunteers (read only): {from, to, departments: [{id, name,
    at_most | null, people, away: [{contact_id, name, starts_on, ends_on}],
    waiting: [{contact_id, name, starts_on, ends_on, flags}]}]}.

    For whoever keeps Who serves when, the owner, whoever oversees the
    office and an Admin: every department. For an office login whose person
    leads a department or is over it: that department. `away` is the
    department's own people's away dates (the facts: who and which days, as
    Who serves when already shows them). `waiting` holds only a VOLUNTEER'S
    ask (grp volunteers): never a leader's ask, and never anyone's reason,
    which this read does not even select. Volunteers ask nothing yet (their
    rules come with their own PR), so `waiting` is empty until then."""
    if hi < lo or (hi - lo).days > cs.WINDOW_DAYS:
        raise HTTPException(400, BAD_WINDOW)
    import church_map
    with church_map.once():
        every = cs.over_all(ch, me) or _keeps_serving(ch, me)
        depts = [d for d in _departments(ch) if every or _runs(ch, me, d)]
        if not depts and not every:
            raise HTTPException(403, NOT_READER)
        numbers = _department_limits(ch)
        people = {str(d["id"]): department_people(ch, d["id"]) for d in depts}
        everyone: Set[str] = set().union(*people.values()) if people else set()
        window = f"&ends_on=gte.{lo.isoformat()}&starts_on=lte.{hi.isoformat()}"
        facts: List[Dict[str, Any]] = []
        for part in co._chunks(sorted(everyone), co.IDS_PER_READ):
            facts += cs._every(f"/serve_away?business_id=eq.{cs._q(ch.b)}&contact_id=in.({cs._in(part)}){window}"
                               f"&select=id,contact_id,starts_on,ends_on")
        asked = [a for a in cs._every(
            f"/church_away_asks?business_id=eq.{cs._q(ch.b)}&state=eq.asked&grp=eq.volunteers{window}"
            f"&select=id,business_id,contact_id,grp,state,starts_on,ends_on,flags,department_id")
            if str(a.get("business_id")) == ch.b and a.get("state") == "asked" and a.get("grp") == "volunteers"]
        names = ch.names([f.get("contact_id") for f in facts] + [a.get("contact_id") for a in asked])
        shaped = cs._names(ch, asked)

        def soonest(x: Dict[str, Any]) -> Tuple[str, str, str]:
            return (x["starts_on"], x["name"].casefold(), x["contact_id"])
        out = []
        for d in depts:
            did = str(d["id"])
            away = [{"contact_id": str(f["contact_id"]), "name": names.get(str(f["contact_id"]), "Someone"),
                     "starts_on": str(f.get("starts_on") or "")[:10], "ends_on": str(f.get("ends_on") or "")[:10]}
                    for f in facts if str(f.get("contact_id")) in people[did]]
            waiting = []
            for a in asked:
                if str(a.get("department_id") or "") != did:
                    continue
                s = cs.shape(ch, me, a, shaped)      # the one door an ask leaves by; no reason was read to give
                waiting.append({k: s[k] for k in ("contact_id", "name", "starts_on", "ends_on", "flags")})
            out.append({"id": did, "name": cs._plain(d.get("name")) or "A department", "at_most": numbers.get(did),
                        "people": len(people[did]), "away": sorted(away, key=soonest),
                        "waiting": sorted(waiting, key=soonest)})
        return {"from": lo.isoformat(), "to": hi.isoformat(), "departments": out}


# ─── Pairs: two people who can't be away together (S2-4) ──────────────

PAIR_FIELDS = "id,business_id,a_contact_id,b_contact_id,note,created_at"


def pairs(ch: co.Church) -> List[Dict[str, Any]]:
    """Every pair at this church, as saved (the smaller id first), a page at
    a time. PRIVATE: this is for the owner and whoever oversees the office
    alone (view_pairs, add_pair, drop_pair ask who first). An ask reads only
    its asker's (picture's `who`)."""
    return [r for r in cs._every(f"/church_away_pairs?business_id=eq.{cs._q(ch.b)}&select={PAIR_FIELDS}")
            if str(r.get("business_id")) == ch.b and r.get("a_contact_id") and r.get("b_contact_id")]


def _pair_view(r: Dict[str, Any], on: Set[str], names: Dict[str, str]) -> Dict[str, Any]:
    """One pair as the owner and whoever oversees the office see it. `in_force`
    is false while either of them is off the leaders schedule: kept, and it
    does nothing."""
    def one(c: str) -> Dict[str, Any]:
        return {"contact_id": c, "name": names.get(c, "Someone"), "on_schedule": c in on}
    a, b = str(r["a_contact_id"]), str(r["b_contact_id"])
    return {"id": str(r.get("id")), "a": one(a), "b": one(b), "note": cs._plain(r.get("note")) or None,
            "in_force": a in on and b in on, "created_at": r.get("created_at")}


def view_pairs(ch: co.Church, me: Dict[str, Any]) -> Dict[str, Any]:
    """GET pairs: {pairs: [{id, a: {contact_id, name, on_schedule}, b: {…},
    note, in_force, created_at}], can_change}, by name. The owner and
    whoever oversees the office ONLY (403 for anyone else: an Admin, a
    Manager who doesn't oversee the office, a department's leader, a
    member-app session, whoever it is)."""
    import church_map
    with church_map.once():
        if not cs.over_all(ch, me):
            raise HTTPException(403, NOT_PAIRS)
        rows = pairs(ch)
        on = cs.roster(ch).people()
        names = ch.names([r[k] for r in rows for k in ("a_contact_id", "b_contact_id")])
        out = [_pair_view(r, on, names) for r in rows]
    return {"pairs": sorted(out, key=lambda x: (x["a"]["name"].casefold(), x["b"]["name"].casefold(), x["id"])),
            "can_change": True}


def add_pair(ch: co.Church, me: Dict[str, Any], a: Any, b: Any, note: Any = None) -> Dict[str, Any]:
    """Two people who can't be away together: the owner, or whoever oversees
    the office (403 for anyone else). Two different people (400), both this
    church's own (400 for anyone else's) and both on the leaders schedule
    (400), with a private note of 140 letters at most. Saved once, the
    smaller id first (Postgres orders two uuids as their lower-case text
    does, and _uuid writes them lower-case); the same two again are a 409.
    Everything the answer says is read before the write."""
    import church_map
    with church_map.once():
        if not cs.over_all(ch, me):
            raise HTTPException(403, NOT_PAIRS)
        x, y = cs._uuid(a, "person"), cs._uuid(b, "person")
        if x == y:
            raise HTTPException(400, PAIR_SELF)
        said = cs._plain(note) or None
        if said and len(said) > PAIR_NOTE_MAX:
            raise HTTPException(400, PAIR_NOTE)
        names = {x: cs._person(ch, x), y: cs._person(ch, y)}       # 400 for anyone not this church's own
        on = cs.roster(ch).people()
        if x not in on or y not in on:
            raise HTTPException(400, PAIR_OFF)
        first, second = sorted((x, y))
        if cs._need(f"/church_away_pairs?business_id=eq.{cs._q(ch.b)}&a_contact_id=eq.{cs._q(first)}"
                    f"&b_contact_id=eq.{cs._q(second)}&select=id&limit=1"):
            raise HTTPException(409, PAIR_TWICE)
    # redact: a refusal's body would echo the row, and the note is private.
    saved = sb_clients.sb_post_as_service("/church_away_pairs", {
        "business_id": ch.b, "a_contact_id": first, "b_contact_id": second, "note": said,
        "created_by": str(me["id"])}, redact=True)
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        if str((sb_clients.last_error() or {}).get("code") or "") == "23505":
            raise HTTPException(409, PAIR_TWICE)        # the same two, saved in the same moment
        raise HTTPException(503, cs.UNSAVED)
    return _pair_view({**saved[0], "a_contact_id": first, "b_contact_id": second, "note": said}, on, names)


def drop_pair(ch: co.Church, me: Dict[str, Any], pair_id: Any) -> Dict[str, Any]:
    """Take a pair off: the owner, or whoever oversees the office (403 for
    anyone else). Read first, so one that isn't this church's is a 404 and
    the answer says what was removed. An ask already flagged by it keeps
    its flag; at the yes it is looked at again, and with the pair gone it
    is a plain yes (unless something else is in the way)."""
    import church_map
    with church_map.once():
        if not cs.over_all(ch, me):
            raise HTTPException(403, NOT_PAIRS)
        pid = cs._uuid(pair_id, "pair")
        rows = cs._need(f"/church_away_pairs?id=eq.{cs._q(pid)}&business_id=eq.{cs._q(ch.b)}"
                        f"&select={PAIR_FIELDS}&limit=1")
        if not rows or str(rows[0].get("business_id")) != ch.b or not rows[0].get("a_contact_id"):
            raise HTTPException(404, NO_PAIR)
        on = cs.roster(ch).people()
        view = _pair_view(rows[0], on, ch.names([rows[0]["a_contact_id"], rows[0]["b_contact_id"]]))
    if not sb_clients.sb_delete_as_service(f"/church_away_pairs?id=eq.{cs._q(pid)}&business_id=eq.{cs._q(ch.b)}"):
        raise HTTPException(503, cs.UNSAVED)
    return view


# ─── The routes ───────────────────────────────────────────────────────

def _church(session: UserSession, biz: Dict[str, Any]) -> co.Church:
    """church_schedule's own gate (a church, the switch, step 1's tables),
    then step 2's: before its file, none of these routes is there (404)."""
    ch = cs._church(session, biz)
    if not ready():
        raise HTTPException(404, "Not Found")
    return ch


def _church_from_body(session: UserSession, body: Dict[str, Any]) -> co.Church:
    ch = cs._church_from_body(session, body)
    if not ready():
        raise HTTPException(404, "Not Found")
    return ch


def _window(ch: co.Church, start: Optional[str], end: Optional[str], ahead: int) -> Tuple[date, date]:
    lo = cs._day(start) if start else cs._today(ch)
    try:
        hi = cs._day(end) if end else (lo + timedelta(days=ahead) if lo else None)
    except OverflowError:                       # a first day at the very end of the calendar
        hi = None
    if not lo or not hi:
        raise HTTPException(400, BAD_DAY)
    return lo, hi


@router.get("/schedule/limits")
def schedule_limits(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                    biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """How many may be away at once, by group and by department, and the
    church's usual service days."""
    ch = _church(session, biz)
    return limits(ch, cs._me(session))


@router.put("/schedule/limits")
def schedule_limits_set(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Set one number, or the usual service days. Answers with the limits
    as they stand after."""
    ch = _church_from_body(session, body or {})
    return set_limit(ch, cs._me(session), body or {})


@router.get("/schedule/days")
def schedule_days(business_id: str, start: Optional[str] = Query(None, alias="from"),
                  end: Optional[str] = Query(None, alias="to"),
                  session: UserSession = Depends(sb_clients.authed_request),
                  biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """The service days: who is away, how many may be, what is full. Three
    months at most (from today for two months when no days are named)."""
    ch = _church(session, biz)
    lo, hi = _window(ch, start, end, cs.WINDOW_DEFAULT)
    return days(ch, cs._me(session), lo, hi)


@router.get("/schedule/protected-days")
def schedule_protected(business_id: str, start: Optional[str] = Query(None, alias="from"),
                       end: Optional[str] = Query(None, alias="to"),
                       session: UserSession = Depends(sb_clients.authed_request),
                       biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """The days nobody takes off, from today for a year when no days are
    named."""
    ch = _church(session, biz)
    lo, hi = _window(ch, start, end, cs.MAX_DAYS)
    return protected_days(ch, cs._me(session), lo, hi)


@router.post("/schedule/protected-days")
def schedule_protected_add(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Name a day nobody takes off."""
    ch = _church_from_body(session, body or {})
    return {"saved": add_protected(ch, cs._me(session), body or {})}


@router.delete("/schedule/protected-days/{day_id}")
def schedule_protected_drop(day_id: str, business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                            biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Take a protected day off."""
    ch = _church(session, biz)
    return {"removed": drop_protected(ch, cs._me(session), day_id)}


@router.get("/schedule/volunteers")
def schedule_volunteers(business_id: str, start: Optional[str] = Query(None, alias="from"),
                        end: Optional[str] = Query(None, alias="to"),
                        session: UserSession = Depends(sb_clients.authed_request),
                        biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """By department: who of its people is away. Read only."""
    ch = _church(session, biz)
    lo, hi = _window(ch, start, end, cs.WINDOW_DEFAULT)
    return volunteers(ch, cs._me(session), lo, hi)


@router.get("/schedule/pairs")
def schedule_pairs(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                   biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Who can't be away together: the owner and whoever oversees the office
    only."""
    ch = _church(session, biz)
    return view_pairs(ch, cs._me(session))


@router.post("/schedule/pairs")
def schedule_pairs_add(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Two people who can't be away together."""
    ch = _church_from_body(session, body or {})
    body = body or {}
    return {"saved": add_pair(ch, cs._me(session), body.get("a_contact_id"), body.get("b_contact_id"),
                              body.get("note"))}


@router.delete("/schedule/pairs/{pair_id}")
def schedule_pairs_drop(pair_id: str, business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                        biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Take a pair off."""
    ch = _church(session, biz)
    return {"removed": drop_pair(ch, cs._me(session), pair_id)}
