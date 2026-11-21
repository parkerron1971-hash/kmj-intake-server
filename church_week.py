"""church_week.py — The week: every department's volunteers for one week, with
hours, for the church office (Volunteers -> The week, first in that group).

The pastor approved the mock on 2026-11-19 ("go"). One week, Sunday to
Saturday, with a way to the week before and the week after. READ ONLY:
nothing here writes. Changes stay where they are today, door by door, in Who
serves when (sunday_planning.py).

    GET /church/week/status?business_id=          {enabled, hours, checks}
    GET /church/week?business_id=&start=YYYY-MM-DD
                                                  the week that day is in
                                                  (docs/CHURCH_SCHEDULE.md,
                                                  "Step 4: The week", has the
                                                  shape field by field)

What it shows, top to bottom:

  counts ............ on the schedule (places with someone on them who said
                      yes or hasn't answered yet), open places (nobody on
                      them, a no, an offer nobody took, or someone on them
                      who is away that day), away (people on the teams with
                      an away date that week), and the hours this year of
                      the week's people
  look .............. short plain lines, most urgent first: a department
                      short on a day (and, for someone away, how many of the
                      team are free then), someone who hasn't answered, and
                      someone who can't serve with kids yet; or one line
                      saying nothing needs a look
  departments ....... one card a department, the church's own order (the
                      leaders map's departments, church_schedule_limits.
                      _department_teams: one of its groups, or a Serve option
                      by name), then a card for each Sunday team that hangs
                      from none, so nothing is lost. A team two departments
                      name sits on the first one's card only

WHO READS IT: the owner, an Admin, and a Manager who keeps either door of
Who serves when: one that changes some team there (sunday_planning.
_owners_for), or holds a duty the office menu opens Who serves when for
(READS: the Volunteers door's serve_schedule, serve_teams, new_volunteers,
background_checks, serving_thanks; ChurchSavvy's production_schedule and
churchsavvy_team). They read EVERY department, both doors, read only.
Anyone else with a seat here is refused (403); a stranger reads no church
(404). The church's own gate: a church, not one on ChurchSavvy alone (404).

MY DEPARTMENT (docs/CHURCH_SCHEDULE.md section 8.8; the pastor's mock and four
calls, 2026-11-20): department_week() is the same read for one person in the
member app, a department's leader or overseer on the leaders map, kept to
their departments' Sunday teams, this week or next, with no hours and no check
state (an uncleared kids place reads "The office is handling this place").
department_team() is what sunday_leading asks before letting them fill a
Volunteers' team of their department; worship and production stay read only.
A member-app session is a person: it never reaches _reader or a login's power.

WHAT ELSE IS PRIVATE: the hours and who can't serve with kids yet follow
church_serving's own rule (church_serving._access): a login it would turn
away gets no hours (null), and one it doesn't let read who's cleared never
sees "Can't serve with kids yet": that person reads as On (or No answer
yet), and nothing on the page counts it or says it. Hours and checks are
read for the week's people only (church_serving.minutes_of, checks_of), and
the checks only for those who may read them.

Away is the FACT (serve_away): who and which days, never its note. Nothing
here reads church_away_asks, so a waiting ask is never counted, shown or
given away (someone waiting reads as free). No phone, no email, no note of
any kind; names only of the church's own people on its teams and of the
departments' and teams' leaders.

Every read is the church's own (business_id) with every value quoted, and
paged or chunked by ids (never the first 1,000 taken for all of them). One
week a call: no start, or one that isn't a date, is this week, the week of
the coming Sunday (today when it is Sunday; the approved mock, made on a
Wednesday, opened on the Sunday to come); a start is the week it falls in;
a week more than WEEKS_BACK weeks back or WEEKS_AHEAD weeks ahead of this
week is refused (400).

Switched by CHURCH_WEEK: off | owner | on, owner when unset (the platform
owner's own church, and the platform owner's own login). Off, or closed for
this church: both routes answer as a closed feature does, 404 (status: all
false).
"""
from __future__ import annotations

import os
import re
import time as clock
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
import serve_dates as sd
import sunday_planning as sp
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix="/church/week", tags=["church"])

SWITCH = "CHURCH_WEEK"
CHURCHSAVVY, VOLUNTEERS = sp.CHURCHSAVVY, sp.VOLUNTEERS
DOORS = (VOLUNTEERS, CHURCHSAVVY)
# The duties the office opens each door's Who serves when for (the office
# menu's own rule, solutionist-studio worklog 2026-11-02-volunteers-door-ui:
# the Volunteers pages show to holders of the first five), besides the ones
# that change its teams (sunday_planning.OWNER_DUTIES).
READS: Dict[str, Tuple[str, ...]] = {
    VOLUNTEERS: ("serve_schedule", "serve_teams", "new_volunteers", "background_checks", "serving_thanks"),
    CHURCHSAVVY: ("production_schedule", "churchsavvy_team"),
}
KEEPS_ALL = ("owner", "admin")
WEEKS_BACK = 52             # a year of weeks behind this one
WEEKS_AHEAD = 26            # six months ahead (event dates are added up to 180 days out)
IDS_PER_READ = 100
STATES = ("on", "no_answer", "open", "away", "cant_serve_kids")
STATE_WORDS = {"on": "On", "no_answer": "No answer yet", "open": "Open", "away": "Away",
               "cant_serve_kids": "Can't serve with kids yet"}
OPEN_PLACE = "Open place"
IN_CHURCHSAVVY = "The worship team fills this in ChurchSavvy."
UNREAD = "The week couldn't be read just now. Try again."
NOT_CHURCH = "The week is for churches"
NOT_READER = "The week is for whoever keeps the volunteer teams or Who serves when."
BAD_WEEK = "Pick a week from a year back to six months ahead."
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _platform_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def open_to(user: AuthedUser) -> bool:
    """For this login: on, or (owner) the platform owner's own login."""
    m = mode()
    if m == "on":
        return True
    return m == "owner" and (getattr(user, "email", None) or "").strip().lower() == _platform_email()


def church_open(biz_id: Any) -> bool:
    """For this church: on, or (owner) the platform owner's own church
    (member_asks.platform_church: kept ten minutes a replica; a read that
    fails is a no)."""
    m = mode()
    if m == "on":
        return True
    if m != "owner":
        return False
    try:
        import member_asks
        return member_asks.platform_church(biz_id)
    except Exception:  # noqa: BLE001 — a lookup that fails is a no, never a 500
        return False


def office_open(user: AuthedUser, biz_id: Any) -> bool:
    """The routes: the login (open_to) or the church (church_open), as
    church_schedule.office_open."""
    return open_to(user) or church_open(biz_id)


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _in(ids: Iterable[Any]) -> str:
    return ",".join(_q(i) for i in ids)


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _first(name: str) -> str:
    return _plain(name).split(" ")[0] or "They"


def _uuid(v: Any) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "That church isn't one we know.")


def _chunks(ids: Iterable[Any], n: int = IDS_PER_READ) -> List[List[str]]:
    out = sorted({str(i) for i in ids if i})
    return [out[i:i + n] for i in range(0, len(out), n)]


def _need(path: str) -> List[Dict[str, Any]]:
    """A bounded read (one row, or one chunk of ids) that must answer."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _every(path: str, key: str = "id") -> List[Dict[str, Any]]:
    """Every row, page by page in `key` order (never the first 1,000 taken
    for all of them). A page that fails is a 503, never a shorter list."""
    try:
        rows = sb_clients.sb_get_all_as_service(path, key=key, strict=True)
    except sb_clients.PartialRead:
        raise HTTPException(503, UNREAD)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _every_in(path: str, column: str, values: Iterable[Any], key: str = "id") -> List[Dict[str, Any]]:
    """`path` with `column=in.(…)`, a hundred ids a read, each read paged."""
    out: List[Dict[str, Any]] = []
    for part in _chunks(values):
        out += _every(f"{path}&{column}=in.({_in(part)})", key=key)
    return out


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _count(n: int) -> str:
    return NUMBERS[n] if 0 <= n < len(NUMBERS) else str(n)


def _clock(at: datetime) -> str:
    """"10:30 AM", "7 PM"."""
    h = at.hour % 12 or 12
    return f"{h}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}" if at.minute else f"{h} {'AM' if at.hour < 12 else 'PM'}"


def _part_of_day(at: datetime) -> str:
    return "morning" if at.hour < 12 else "afternoon" if at.hour < 17 else "evening"


def _short(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _hours_words(minutes: int) -> str:
    if minutes <= 0:
        return "No hours yet"
    if minutes < 60:
        return f"{minutes} minutes"
    h = round(minutes / 60, 1)
    return "1 hour" if h == 1 else f"{h:g} hours"


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _team_phrase(name: str) -> str:
    """"the Parking Team", "the Kids Check-in team"."""
    return f"the {name}" if name.casefold().endswith("team") else f"the {name} team"


# ─── The gate ─────────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _doors(biz_id: str, user: AuthedUser) -> Tuple[Optional[str], FrozenSet[str], FrozenSet[str]]:
    """(this login's role here, the doors of Who serves when it keeps, the
    doors whose teams it changes). The owner and an Admin: both. A Manager:
    the doors its duties open (READS) or whose teams it changes
    (sunday_planning._owners_for). Anyone else: none. A duties read that
    fails is a 503."""
    import church_duties
    standing = church_duties.standing(biz_id, str(user.id))
    role = standing.get("role")
    if role in KEEPS_ALL:
        return role, frozenset(DOORS), frozenset(DOORS)
    if role != "manager":
        return role, frozenset(), frozenset()
    change, _role = sp._owners_for(biz_id, user)
    held = standing.get("duties") or frozenset()
    keeps = set(change) | {door for door, duties in READS.items() if any(d in held for d in duties)}
    return role, frozenset(keeps), frozenset(change)


def _serving(biz_id: str, user: AuthedUser) -> Dict[str, bool]:
    """Whether this login reads hours here, and who's cleared: church_
    serving's own rule (its switch, its areas, the background checks duty),
    asked of church_serving._access itself. A login it turns away (403, or
    its switch closed: 404) gets neither; a read that fails is a 503."""
    import church_serving
    try:
        me = church_serving._access(biz_id, user)
    except HTTPException as e:
        if e.status_code in (403, 404):
            return {"hours": False, "checks": False}
        if e.status_code == 503:
            raise HTTPException(503, UNREAD)
        raise
    return {"hours": True, "checks": bool(me.get("checks"))}


def _reader(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """Who is reading, and what they may see. 404: no seat here (as every
    church route), the switch closed for this church, Who serves when
    (SUNDAY_PLANNING) closed to them, or not a church (or a church on
    ChurchSavvy alone, which has no office). 403: a seat here that keeps
    neither door of Who serves when."""
    biz_id = _uuid(business_id)
    business_access.assert_access(biz_id, user, "viewer")
    if not office_open(user, biz_id) or not sp.open_to(user):
        raise HTTPException(404, "Not Found")
    biz = _business(biz_id)
    import church_follow_up
    import churchsavvy_billing
    if not church_follow_up.is_church(biz) or churchsavvy_billing.standalone(biz):
        raise HTTPException(404, NOT_CHURCH)
    role, keeps, change = _doors(biz_id, user)
    if not keeps:
        raise HTTPException(403, NOT_READER)
    return {"biz": biz, "role": role, "change": change, **_serving(biz_id, user)}


# ─── The week's reads ─────────────────────────────────────────────────

def _sunday_of(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _coming_sunday(today: date) -> date:
    """The coming Sunday: today when it is Sunday. "This week" is that
    Sunday's week (Sunday to Saturday), as the pastor's approved mock opened
    on a weekday (Wednesday Nov 18 shows Nov 22 to 28): on a weekday the
    Sunday before has passed and the one to come is what needs a look."""
    return today + timedelta(days=(6 - today.weekday()) % 7)


def _week(start: Any, today: date) -> date:
    """The Sunday of the week asked for: the one `start` is in; this week
    (the coming Sunday's, _coming_sunday) when there is no start or it isn't
    a date. 400 past the bounds."""
    this = _coming_sunday(today)
    first = this
    raw = start.strip() if isinstance(start, str) else ""
    if _DAY.match(raw):
        try:
            first = _sunday_of(date.fromisoformat(raw))
        except ValueError:
            first = this
        except OverflowError:               # the calendar's first days: far past the bounds
            raise HTTPException(400, BAD_WEEK)
    if not -WEEKS_BACK <= (first - this).days // 7 <= WEEKS_AHEAD:
        raise HTTPException(400, BAD_WEEK)
    return first


def _services(b: str, zone, first: date) -> List[Dict[str, Any]]:
    """The week's live services and event dates, soonest first, on the
    church's clock (sunday_planning._services' shape, read a page at a time)."""
    lo = datetime.combine(first, time(0), tzinfo=zone)
    hi = datetime.combine(first + timedelta(days=7), time(0), tzinfo=zone)
    rows = _every(f"/worship_services?business_id=eq.{b}&archived_at=is.null&is_template=eq.false"
                  f"&starts_at=gte.{_q(lo.astimezone(timezone.utc).isoformat())}"
                  f"&starts_at=lt.{_q(hi.astimezone(timezone.utc).isoformat())}"
                  f"&select=id,title,starts_at{sd.fields()}")
    out = []
    for r in rows:
        at = _at(r.get("starts_at"))
        if not at:
            continue
        at = at.astimezone(zone)
        event = sd.is_event(r)
        out.append({"id": str(r["id"]), "at": at, "day": at.date().isoformat(), "weekday": sd.weekday(at),
                    "time": at.strftime("%H:%M"), "kind": sd.EVENT if event else sd.SERVICE,
                    "title": _plain(r.get("title")) or ("An event" if event else "Sunday service"),
                    # An event date's own numbers for the Volunteers' places (serve_dates.needed).
                    "needs": r["needs"] if event and isinstance(r.get("needs"), dict) else None,
                    "event_entry_id": str(r["event_entry_id"]) if event and r.get("event_entry_id") else None})
    out.sort(key=lambda s: (s["at"], s["id"]))
    return out


def _serve_rows(b: str) -> List[Dict[str, Any]]:
    """serve_teams with each one's door, a page at a time. Before the door's
    column was there every team reads as the Volunteers', as sunday_planning.
    _serve_rows reads it."""
    path = f"/serve_teams?business_id=eq.{b}"
    if not sp._owner_missing():
        try:
            rows = _every(f"{path}&select=group_id,sort,owner", key="group_id")
            return [{**r, "owner": r.get("owner") if r.get("owner") in sp.OWNERS else VOLUNTEERS} for r in rows]
        except HTTPException:
            if sp._column_missing() is not True:
                raise
            sp._no_column["at"] = clock.monotonic()
    return [{**r, "owner": VOLUNTEERS} for r in _every(f"{path}&select=group_id,sort", key="group_id")]


def _teams(b: str) -> List[Dict[str, Any]]:
    """The Sunday teams (a serve_teams row and a live team group, as Who
    serves when lists them), in its order: {group_id, name, owner, sort}."""
    serve = _serve_rows(b)
    names: Dict[str, str] = {}
    for part in _chunks(s.get("group_id") for s in serve):
        for g in _need(f"/groups?business_id=eq.{b}&id=in.({_in(part)})&kind=eq.team&active=eq.true"
                       f"&select=id,name&limit={IDS_PER_READ}"):
            names[str(g["id"])] = _plain(g.get("name")) or "A team"
    teams = [{"group_id": str(s["group_id"]), "name": names[str(s["group_id"])], "owner": s["owner"],
              "sort": s.get("sort") or 0} for s in serve if str(s.get("group_id")) in names]
    teams.sort(key=lambda t: (t["sort"], t["name"].lower(), t["group_id"]))
    return teams


def _places(b: str, team_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Each team's live places, in its order."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for p in _every_in(f"/serve_positions?business_id=eq.{b}&active=eq.true"
                       f"&select=id,group_id,name,needed,sort,created_at", "group_id", team_ids):
        needed = p.get("needed") if isinstance(p.get("needed"), int) and not isinstance(p.get("needed"), bool) else 1
        out.setdefault(str(p["group_id"]), []).append(
            {"id": str(p["id"]), "name": _plain(p.get("name")) or "A place", "needed": max(1, min(needed, 10)),
             "sort": p.get("sort") or 0, "made": str(p.get("created_at") or "")})
    for rows in out.values():
        rows.sort(key=lambda p: (p["sort"], p["made"], p["id"]))
    return out


def _members(b: str, team_ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Each team's people: group -> {contact_id: role}, one team a read,
    a page at a time (a team's people are one key each: its contact)."""
    out: Dict[str, Dict[str, str]] = {}
    for gid in team_ids:
        out[gid] = {str(m["contact_id"]): str(m.get("role") or "member") for m in _every(
            f"/group_members?business_id=eq.{b}&group_id=eq.{_q(gid)}&select=contact_id,role", key="contact_id")
            if m.get("contact_id")}
    return out


def _away(b: str, people: Iterable[str], first: date, last: date) -> Dict[str, List[Tuple[str, str]]]:
    """Who is away this week and which days: the facts (serve_away), never
    their note, and never an ask."""
    out: Dict[str, List[Tuple[str, str]]] = {}
    for a in _every_in(f"/serve_away?business_id=eq.{b}&starts_on=lte.{last.isoformat()}"
                       f"&ends_on=gte.{first.isoformat()}&select=id,contact_id,starts_on,ends_on", "contact_id", people):
        out.setdefault(str(a["contact_id"]), []).append((str(a.get("starts_on") or "")[:10],
                                                         str(a.get("ends_on") or "")[:10]))
    return out


def _names(b: str, ids: Iterable[str]) -> Dict[str, str]:
    return {str(c["id"]): _plain(c.get("name")) or "Someone"
            for c in _every_in(f"/contacts?business_id=eq.{b}&select=id,name", "id", ids)}


def _heads_it(d: Dict[str, Any], person: str) -> bool:
    """This person is the department's leader or its overseer on the
    leaders map (church_schedule_limits._runs reads the same two)."""
    return bool(person) and person in (str(d.get("leader_contact_id") or ""), str(d.get("overseer_contact_id") or ""))


def _cards(biz: Dict[str, Any], teams: List[Dict[str, Any]], person: Optional[str] = None,
           ch: Any = None) -> List[Dict[str, Any]]:
    """[{department, teams}] in the church's own order, then one card for
    each team that hangs from no department. A team two departments name is
    on the first one's card only, so nothing is counted twice.

    `person` (My department, in the member app): only the departments this
    person leads or oversees, and no team's own card. A team that one of
    theirs names is on their card even when a department before it names it
    too: theirs is the card they read."""
    import church_map
    import church_over as co
    import church_schedule_limits as csl
    known = {t["group_id"]: t for t in teams}
    out: List[Dict[str, Any]] = []
    taken: Set[str] = set()
    try:
        with church_map.once():
            ch = ch or co.Church(biz)
            for d in csl._departments(ch):
                if person is not None and not _heads_it(d, person):
                    continue
                mine = [g for g in csl._department_teams(ch, d) if g in known and g not in taken]
                if not mine:
                    continue
                taken |= set(mine)
                out.append({"department": d, "teams": [t for t in teams if t["group_id"] in mine]})
    except HTTPException as e:
        if e.status_code == 503:
            raise HTTPException(503, UNREAD)
        raise
    if person is None:
        out += [{"department": None, "teams": [t]} for t in teams if t["group_id"] not in taken]
    return out


# ─── The week ─────────────────────────────────────────────────────────

def week(me: Dict[str, Any], start: Any = None, *, person: Optional[str] = None, ch: Any = None) -> Dict[str, Any]:
    """GET /church/week: the shape is docs/CHURCH_SCHEDULE.md's "Step 4:
    The week".

    `person` is My department's (department_week, docs section 8.8): the
    same read, kept to the Sunday teams of the departments this person leads
    or oversees (only their places, their people and their away dates are
    read), no "can't serve with kids yet" line in Look at first (the row
    says it, and department_week turns it into "The office is handling this
    place"), no "hasn't answered" line for a place the office has either,
    and each card carries who on its teams is away this week. `ch`: the
    church_over.Church the caller already holds (its map and teams are read
    once)."""
    import business_marketing
    biz = me["biz"]
    biz_id = str(biz["id"])
    b = _q(biz_id)
    zone = business_marketing.business_tz(biz)
    now = _now().astimezone(zone)
    today = now.date()
    first = _week(start, today)
    last = first + timedelta(days=6)
    services = _services(b, zone, first)
    import event_volunteers
    event_volunteers.date_extras(biz_id, services, flags=False)
    teams = _teams(b)
    cards = _cards(biz, teams, person, ch)
    if person is not None:
        theirs = {t["group_id"] for c in cards for t in c["teams"]}
        teams = [t for t in teams if t["group_id"] in theirs]
    gids = [t["group_id"] for t in teams]
    places = _places(b, gids) if gids else {}
    members = _members(b, gids)
    # Every ask at the week's services, whatever the team: who is busy at a
    # service (on any team) is never counted free.
    rows = _every_in(f"/serve_assignments?business_id=eq.{b}&select=id,service_id,position_id,slot,contact_id,status,"
                     f"asked_at", "service_id", [s["id"] for s in services]) if services and gids else []
    holder: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: str(r.get("id"))):
        try:
            slot = int(r.get("slot") or 1)
        except (TypeError, ValueError):
            continue
        holder.setdefault((str(r.get("service_id")), str(r.get("position_id")), slot), r)
    on_rows = [r for r in rows if r.get("status") in ("asked", "yes") and r.get("contact_id")]
    shown_places = {p["id"] for gid in gids for p in places.get(gid, [])}
    # Whose away dates are read: the teams' people, and whoever is on one of
    # the shown places (My department: its own places only, so no other
    # department's people's away dates are read).
    everyone = {c for m in members.values() for c in m} | {
        str(r["contact_id"]) for r in on_rows if person is None or str(r.get("position_id")) in shown_places}
    away = _away(b, everyone, first, last) if everyone else {}

    def is_away(cid: str, day: str) -> bool:
        return any(a <= day <= z for a, z in away.get(cid, []))

    # The places, slot by slot, each service a team serves.
    slots: List[Dict[str, Any]] = []
    for svc in services:
        for t in teams:
            if not sp.serves(svc, t):
                continue
            for p in places.get(t["group_id"], []):
                for slot in range(1, sd.needed(svc, p) + 1):
                    r = holder.get((svc["id"], p["id"], slot))
                    cid = str(r["contact_id"]) if r and r.get("status") in ("asked", "yes") and r.get("contact_id") else None
                    state = "open" if not cid else "away" if is_away(cid, svc["day"]) else \
                        "on" if r["status"] == "yes" else "no_answer"
                    slots.append({"svc": svc, "team": t, "place": p, "slot": slot, "cid": cid, "state": state,
                                  "asked": r.get("asked_at") if cid else None, "status": r["status"] if cid else None})

    # Who can't serve with kids yet: only for those who read who's cleared,
    # only the week's people on a Kids & youth team's place at a service
    # still to come (a past day is what happened), by church_serving's own
    # rule: no check on record and on the schedule with kids or youth.
    if me["checks"]:
        import church_serving
        try:
            kids = church_serving._kids_teams(biz_id)
            with_kids = [s for s in slots if s["cid"] and s["state"] != "away" and s["svc"]["at"] > now
                         and s["team"]["group_id"] in kids]
            nexts: Dict[str, Dict[str, Any]] = {}
            for s in with_kids:
                nexts.setdefault(s["cid"], {"day": s["svc"]["day"], "place": s["place"]["name"],
                                            "team": s["team"]["name"]})
            status = church_serving.checks_of(biz, nexts, today, nexts) if nexts else {}
        except HTTPException as e:
            if e.status_code == 503:
                raise HTTPException(503, UNREAD)
            raise
        for s in with_kids:
            if (status.get(s["cid"]) or {}).get("status") == "blocked":
                s["state"] = "cant_serve_kids"

    shown_people = {s["cid"] for s in slots if s["cid"]}
    minutes: Optional[Dict[str, int]] = None
    if me["hours"]:
        import church_serving
        try:
            minutes = church_serving.minutes_of(biz, shown_people, zone) if shown_people else {}
        except HTTPException as e:
            if e.status_code == 503:
                raise HTTPException(503, UNREAD)
            raise
    leaders = {gid: sorted(c for c, role in m.items() if role == "leader") for gid, m in members.items()}
    named = set(shown_people)
    if person is not None:
        named |= {c for m in members.values() for c in m if c in away}
    for c in cards:
        d = c["department"]
        if d and d.get("leader_contact_id"):
            named.add(str(d["leader_contact_id"]))
        elif not d:
            named |= set(leaders.get(c["teams"][0]["group_id"], []))
    names = _names(b, named) if named else {}

    # Two services on one weekday say their time too.
    per_day: Dict[str, int] = {}
    for s in services:
        per_day[s["weekday"]] = per_day.get(s["weekday"], 0) + 1

    def when(svc: Dict[str, Any]) -> str:
        return f"{svc['weekday']} at {_clock(svc['at'])}" if per_day[svc["weekday"]] > 1 else svc["weekday"]

    def svc_words(svc: Dict[str, Any]) -> str:
        words = f"{svc['weekday']} {_clock(svc['at'])}"
        return f"{words} · {svc['title']}" if svc["kind"] == sd.EVENT else words

    busy: Dict[str, Set[str]] = {}
    for r in on_rows:
        busy.setdefault(str(r["service_id"]), set()).add(str(r["contact_id"]))

    def free(t: Dict[str, Any], svc: Dict[str, Any], but: str) -> int:
        return sum(1 for c in members.get(t["group_id"], {})
                   if c != but and c not in busy.get(svc["id"], set()) and not is_away(c, svc["day"]))

    def row_out(s: Dict[str, Any]) -> Dict[str, Any]:
        t, svc, cid = s["team"], s["svc"], s["cid"]
        short = s["state"] in ("open", "away")
        upcoming = svc["at"] > now
        mins = (minutes or {}).get(cid, 0) if cid and minutes is not None else None
        return {"group_id": t["group_id"], "team": t["name"], "door": t["owner"], "place_id": s["place"]["id"],
                "place": s["place"]["name"], "slot": s["slot"],
                "person": {"contact_id": cid, "name": names.get(cid, "Someone")} if cid else None,
                "who": names.get(cid, "Someone") if cid else OPEN_PLACE,
                "state": s["state"], "state_words": STATE_WORDS[s["state"]],
                "minutes": mins, "hours_words": _hours_words(mins) if mins is not None else None,
                "find": ({"group_id": t["group_id"], "service_id": svc["id"], "day": svc["day"]}
                         if short and upcoming and t["owner"] == VOLUNTEERS else None),
                "note": IN_CHURCHSAVVY if short and t["owner"] == CHURCHSAVVY else None}

    out_cards: List[Dict[str, Any]] = []
    look: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    rank = {"short": 0, "no_answer": 1, "cant_serve_kids": 2}
    for n, c in enumerate(cards):
        d = c["department"]
        mine = {t["group_id"] for t in c["teams"]}
        name = (_plain(d.get("name")) or "A department") if d else c["teams"][0]["name"]
        if d:
            lead = str(d.get("leader_contact_id") or "")
            led_by = names.get(lead) if lead else None
        else:
            lead_ids = leaders.get(c["teams"][0]["group_id"], [])
            led_by = sorted((names.get(x, "") for x in lead_ids if names.get(x)), key=str.casefold)
            led_by = led_by[0] if led_by else None
        card_services, open_n, any_rows = [], 0, False
        for svc in services:
            if not any(sp.serves(svc, t) for t in c["teams"]):
                continue
            here = [s for s in slots if s["svc"] is svc and s["team"]["group_id"] in mine]
            any_rows = any_rows or bool(here)
            open_n += sum(1 for s in here if s["state"] in ("open", "away"))
            card_services.append({"service_id": svc["id"], "day": svc["day"], "weekday": svc["weekday"],
                                  "time": svc["time"], "words": svc_words(svc), "kind": svc["kind"],
                                  "title": svc["title"], "past": svc["at"] <= now,
                                  "rows": [row_out(s) for s in here],
                                  # An event date's flyer {thumb, url} (event_volunteers.date_extras).
                                  **({"flyer": svc.get("flyer")} if svc["kind"] == sd.EVENT else {})})
            if svc["at"] <= now:
                continue
            # Look at first: short, by door; who hasn't answered; who can't serve with kids yet.
            for door in DOORS:
                gaps = [s for s in here if s["team"]["owner"] == door and s["state"] in ("open", "away")]
                if not gaps:
                    continue
                count: Dict[str, int] = {}
                for s in gaps:
                    count[s["place"]["name"]] = count.get(s["place"]["name"], 0) + 1
                where = ", ".join(f"{p} ({k})" if k > 1 else p for p, k in count.items())
                details = []
                for s in gaps:
                    if s["state"] == "away":
                        k = free(s["team"], svc, s["cid"])
                        tp = _team_phrase(s["team"]["name"])
                        who = (f"Nobody else on {tp} is free" if k == 0 else f"One person on {tp} is free" if k == 1
                               else f"{_count(k).capitalize()} people on {tp} are free")
                        details.append(f"{names.get(s['cid'], 'Someone')} is away. {who} that {_part_of_day(svc['at'])}.")
                if door == CHURCHSAVVY:
                    details.append(IN_CHURCHSAVVY)
                look.append(((svc["at"], rank["short"], DOORS.index(door), n, 0), {
                    "kind": "short", "title": f"{name} is short {_count(len(gaps))} on {when(svc)}: {where}.",
                    "details": details, "service_id": svc["id"], "day": svc["day"],
                    "find": ({"group_id": gaps[0]["team"]["group_id"], "service_id": svc["id"], "day": svc["day"]}
                             if door == VOLUNTEERS else None)}))
            for i, s in enumerate(here):
                # My department: a place the office is handling makes no line at all (it would point at it).
                if s["cid"] and s["status"] == "asked" and s["state"] != "away" and not (
                        person is not None and s["state"] == "cant_serve_kids"):
                    who = names.get(s["cid"], "Someone")
                    asked = _asked_words(s["asked"], zone, today)
                    look.append(((svc["at"], rank["no_answer"], DOORS.index(s["team"]["owner"]), n, i), {
                        "kind": "no_answer", "title": f"{name}: {who} hasn't answered for {when(svc)}.",
                        "details": [f"{_first(who)} was asked {asked}."] if asked else [],
                        "service_id": svc["id"], "day": svc["day"], "find": None}))
                if s["state"] == "cant_serve_kids" and person is None:
                    who = names.get(s["cid"], "Someone")
                    first_name = _first(who)
                    on_for = f"is on for {when(svc)}" if s["status"] == "yes" else f"was asked for {when(svc)}"
                    look.append(((svc["at"], rank["cant_serve_kids"], DOORS.index(s["team"]["owner"]), n, i), {
                        "kind": "cant_serve_kids", "title": f"{name}: {who} can't serve with kids yet.",
                        "details": [f"{first_name}'s background check isn't on record. {first_name} {on_for}."],
                        "service_id": svc["id"], "day": svc["day"], "find": None}))
        doors = {t["owner"] for t in c["teams"]}
        out_cards.append({
            "department_id": str(d["id"]) if d else None,
            "group_id": None if d else c["teams"][0]["group_id"],
            "name": name, "led_by": led_by,
            "churchsavvy": doors == {CHURCHSAVVY},
            "open": open_n,
            "label": (f"{open_n} open" if open_n else "Filled") if any_rows else "Nothing this week",
            "teams": [{"group_id": t["group_id"], "name": t["name"], "door": t["owner"],
                       "churchsavvy": t["owner"] == CHURCHSAVVY} for t in c["teams"]],
            "services": card_services})
        if person is not None:
            # Who on its teams is away this week (the facts, each person once): My department's Away list.
            on_card = {p for gid in mine for p in members.get(gid, {})}
            out_cards[-1]["away"] = sorted(
                ({"contact_id": p, "name": names.get(p, "Someone"), "days": sorted(set(away[p]))}
                 for p in on_card if p in away),
                key=lambda x: (x["days"][0], x["name"].casefold(), x["contact_id"]))

    items = [item for _key, item in sorted(look, key=lambda x: x[0])]
    if not items:
        with_places = {s["svc"]["id"] for s in slots}
        items = [{"kind": "clear", "title": _all_clear([s for s in services if s["id"] in with_places], teams, now,
                                                       mine=person is not None),
                  "details": [], "service_id": None, "day": None, "find": None}]
    this = _coming_sunday(today)
    prev, nxt = first - timedelta(days=7), first + timedelta(days=7)
    total = sum((minutes or {}).get(c, 0) for c in shown_people) if minutes is not None else None
    on_teams = {c for m in members.values() for c in m}
    return {
        "week": {"from": first.isoformat(), "to": last.isoformat(), "words": _week_words(first, last),
                 "this_week": first == this,
                 "prev": prev.isoformat() if (prev - this).days // 7 >= -WEEKS_BACK else None,
                 "next": nxt.isoformat() if (nxt - this).days // 7 <= WEEKS_AHEAD else None},
        "counts": {"on": sum(1 for s in slots if s["state"] in ("on", "no_answer", "cant_serve_kids")),
                   "open": sum(1 for s in slots if s["state"] in ("open", "away")),
                   "away": len({c for c in away if c in on_teams}),
                   "hours": round(total / 60, 1) if total is not None else None},
        "look": items,
        "departments": out_cards,
        "can": {"hours": bool(me["hours"]), "checks": bool(me["checks"]),
                "change": [d for d in DOORS if d in me["change"]]},
    }


def _asked_words(asked_at: Any, zone, today: date) -> Optional[str]:
    """"today", "yesterday", "on Monday", "on Nov 9"."""
    at = _at(asked_at)
    if not at:
        return None
    day = at.astimezone(zone).date()
    gap = (today - day).days
    if gap <= 0:
        return "today"
    if gap == 1:
        return "yesterday"
    if gap < 7:
        return f"on {day.strftime('%A')}"
    return f"on {_short(day)}"


def _all_clear(services: List[Dict[str, Any]], teams: List[Dict[str, Any]], now: datetime, mine: bool = False) -> str:
    """The one line when nothing needs a look. `services` are only those at
    which some team has a place this week: a service nothing serves (an
    event date with only ChurchSavvy's teams, a team with no places) is
    never said to be filled. `mine`: My department's words (never the
    office page's name)."""
    if not teams:
        return "None of your department's teams is on the schedule yet." if mine else "No teams are on Who serves when yet."
    if not services:
        return "Nothing is on the schedule this week."
    ahead = [s for s in services if s["at"] > now]
    if not ahead:
        return "This week's services have passed."
    days: List[str] = []
    for s in ahead:
        if s["weekday"] not in days:
            days.append(s["weekday"])
    return f"Everything is filled for {_join(days)}."


def _week_words(first: date, last: date) -> str:
    """"Nov 22 to 28", "Nov 29 to Dec 5"."""
    if first.month == last.month:
        return f"{_short(first)} to {last.day}"
    return f"{_short(first)} to {_short(last)}"


# ─── My department: the same week, in the member app ──────────────────
#
# docs/CHURCH_SCHEDULE.md section 8.8. The pastor approved the mock and four
# calls on 2026-11-20. For whoever the leaders map names over a department
# (its leader, its overseer), on the Sundays page of the member app's Lead
# tab (member_portal_leading). A MEMBER-APP SESSION IS A PERSON, never a
# login (member_portal_dates._ch_me): nothing here carries an office
# standing, reads hours or says a check state. Someone on a kids place who
# isn't cleared reads "The office is handling this place", never why.

PHONE_WORDS = {"on": "On", "no_answer": "Asked, no answer yet", "open": "Open", "away": "Away",
               "office": "The office is handling this place"}
WHICH = ("this", "next")    # this week and next week: the phone's two
HEADS_SECONDS = 60          # who leads or oversees a department, kept this long a replica
_HEADS: Dict[str, Tuple[float, FrozenSet[str]]] = {}


def _bid(biz: Any) -> str:
    return str(biz.get("id") if isinstance(biz, dict) else biz)


def member_open(biz: Any) -> bool:
    """My department at this church: Who serves when isn't off
    (SUNDAY_PLANNING) and CHURCH_WEEK is open for the church (church_open:
    on, or the platform owner's own church under owner). A person has no
    login, so the platform owner's own login (open_to) opens nothing here."""
    return sp.mode() != "off" and church_open(_bid(biz))


def heads(biz: Any) -> Optional[FrozenSet[str]]:
    """Who leads or oversees an active department at this church, kept a
    minute a replica: the Lead tab's Sundays entry and who gets the tab
    read this, so neither costs a read on a page view (the page itself
    reads fresh). Empty while the leaders map is closed for the church or
    its columns aren't there; None when a read failed (never kept: the next
    page asks again). One read: the church's active departments, two
    columns."""
    b = _bid(biz)
    hit = _HEADS.get(b)
    if hit and clock.monotonic() - hit[0] < HEADS_SECONDS:
        return hit[1]
    import church_map
    got: FrozenSet[str] = frozenset()
    if church_map.church_open(biz):
        state = church_map.state()
        if state is None:
            return None
        if state:
            rows = sb_clients.sb_get_as_service(
                f"/church_departments?business_id=eq.{_q(b)}&status=eq.active"
                f"&select=leader_contact_id,overseer_contact_id&limit=200")
            if not isinstance(rows, list):
                return None
            got = frozenset(str(r[k]) for r in rows for k in ("leader_contact_id", "overseer_contact_id") if r.get(k))
    _HEADS[b] = (clock.monotonic(), got)
    return got


def standing(biz: Any, contact_id: Any) -> Optional[bool]:
    """Whether My department is this person's, from what heads() keeps:
    None when it couldn't be told (a read failed). NEVER RAISES: every page
    of the member app waits on it."""
    try:
        cid = str(contact_id or "")
        if not cid or not member_open(biz):
            return False
        got = heads(biz)
        return None if got is None else cid in got
    except Exception as e:  # noqa: BLE001 — the tab bar is never worth a 500
        print(f"[church_week] {_bid(biz)[:8]}: My department's entry couldn't be worked out ({type(e).__name__})",
              flush=True)
        return None


def entry(biz: Any, contact_id: Any) -> bool:
    """standing(), with "couldn't be told" as no: the Lead tab's Sundays
    entry and the tab itself."""
    return bool(standing(biz, contact_id))


def _church_row(biz: Any) -> Optional[Dict[str, Any]]:
    """The church's whole row (the member app's own has no owner, which the
    leaders map's reads need), or None for a business that isn't a church
    or is a church on ChurchSavvy alone."""
    import church_follow_up
    import churchsavvy_billing
    row = _business(_uuid(_bid(biz)))
    if not church_follow_up.is_church(row) or churchsavvy_billing.standalone(row):
        return None
    return row


def department_team(biz: Any, contact_id: Any, group_id: Any) -> Optional[Dict[str, Any]]:
    """{group_id, name}: one of the Volunteers' Sunday teams that hangs from
    a department this person leads or oversees (call 2): sunday_leading lets
    them do for it what its own leader does, every write checked here. None
    for anything else: ChurchSavvy's worship and production teams (read
    only here, call 4), a team on no department of theirs, the switch
    closed. Read fresh; a read that fails is a 503."""
    gid, cid = str(group_id or ""), str(contact_id or "")
    if not gid or not cid or not member_open(biz):
        return None
    row = _church_row(biz)
    if not row:
        return None
    team = next((t for t in _teams(_q(row["id"])) if t["group_id"] == gid), None)
    if not team or team["owner"] != VOLUNTEERS or not _cards(row, [team], cid):
        return None
    return {"group_id": gid, "name": team["name"]}


def _days_words(spans: Iterable[Tuple[str, str]]) -> str:
    """"Sunday, Nov 22"; "Nov 21 to 23"; two of them joined with "and"."""
    out: List[str] = []
    for a, z in spans:
        try:
            first, last = date.fromisoformat(a), date.fromisoformat(z)
        except ValueError:
            continue
        out.append(f"{first.strftime('%A')}, {_short(first)}" if last <= first else _week_words(first, last))
    return _join(out)


def _phone_row(r: Dict[str, Any], numbered: bool) -> Dict[str, Any]:
    """One place on the phone: no hours, and "can't serve with kids yet" is
    "The office is handling this place" (call 3). Find someone is on an open
    place only (the mock's): someone away keeps their place until they are
    taken off it, which a leader can't do to a yes (sunday_leading), so the
    button would only be refused."""
    state = "office" if r["state"] == "cant_serve_kids" else r["state"]
    f = r["find"] if state == "open" else None
    return {"place": r["place"] + (f" {r['slot']}" if numbered else ""), "who": r["who"], "state": state,
            "words": PHONE_WORDS[state], "note": r["note"],
            "find": {"team": f["group_id"], "day": f["service_id"], "spot": f"{r['place_id']}:{r['slot']}"}
            if f else None}


def _phone_teams(card: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The department's card, one card a team: when it serves this week and
    each place's rows."""
    out = []
    for t in card["teams"]:
        services = []
        for s in card["services"]:
            rows = [r for r in s["rows"] if r["group_id"] == t["group_id"]]
            if not rows:
                continue
            spots: Dict[str, int] = {}
            for r in rows:
                spots[r["place_id"]] = spots.get(r["place_id"], 0) + 1
            services.append({"words": s["words"], "past": s["past"],
                             "rows": [_phone_row(r, spots[r["place_id"]] > 1) for r in rows]})
        out.append({"name": t["name"], "churchsavvy": t["churchsavvy"], "services": services})
    return out


def department_week(biz: Any, contact_id: Any, which: str = "this") -> Optional[Dict[str, Any]]:
    """My department (section 8.8): the office's week (week(), the same
    read) for the departments this person leads or oversees, this week or
    next, in the phone's shape: {week, counts (on, open, away), look,
    departments: [{name, led_by, teams: [{name, churchsavvy, services:
    [{words, past, rows: [{place, who, state, words, note, find}]}]}],
    elsewhere: [{team, under}], away: [{name, days}]}]}. No hours and no
    check state anywhere in it. "This week" is the coming Sunday's
    (_coming_sunday), "next" the one after.
    None when it isn't theirs: the switch closed for the church, not a
    church, the leaders map closed, or no department of theirs. Fresh
    reads; one that fails is a 503 (the page says so in plain words)."""
    cid = str(contact_id or "")
    if not cid or not member_open(biz):
        return None
    row = _church_row(biz)
    if not row:
        return None
    import business_marketing
    import church_map
    import church_over as co
    import church_schedule_limits as csl
    import church_serving
    with church_map.once():
        try:
            ch = co.Church(row)
            depts = [d for d in csl._departments(ch) if _heads_it(d, cid)]
        except HTTPException as e:
            if e.status_code == 503:
                raise HTTPException(503, UNREAD)
            raise
        if not depts:
            return None
        which = which if which in WHICH else "this"
        this = _coming_sunday(_now().astimezone(business_marketing.business_tz(row)).date())
        start = this + timedelta(days=7) if which == "next" else this
        # Hours: never. Who isn't cleared for a kids place: worked out while
        # Serving is on for every church, only to say the office has it.
        body = week({"biz": row, "role": None, "change": frozenset(), "hours": False,
                     "checks": church_serving.mode() == "on"}, start.isoformat(), person=cid, ch=ch)
        cards = {c["department_id"]: c for c in body["departments"]}
        # A team two of their departments name is on the first one's card:
        # the other says where it is, never that it has no team.
        under = {t["group_id"]: (t["name"], c["name"]) for c in body["departments"] for t in c["teams"]}
        try:
            elsewhere = {str(d["id"]): [{"team": under[g][0], "under": under[g][1]}
                                        for g in csl._department_teams(ch, d) if g in under]
                         for d in depts if str(d["id"]) not in cards}
        except HTTPException as e:
            if e.status_code == 503:
                raise HTTPException(503, UNREAD)
            raise
    missing = {str(d["leader_contact_id"]) for d in depts if str(d["id"]) not in cards and d.get("leader_contact_id")}
    called = _names(_q(row["id"]), missing - {cid}) if missing - {cid} else {}
    out = []
    for d in depts:
        c = cards.get(str(d["id"]))
        lead = str(d.get("leader_contact_id") or "")
        out.append({"name": _plain(d.get("name")) or "A department",
                    "led_by": None if not lead or lead == cid else (c["led_by"] if c else called.get(lead)),
                    "teams": _phone_teams(c) if c else [],
                    "elsewhere": elsewhere.get(str(d["id"]), []),
                    "away": [{"name": a["name"], "days": _days_words(a["days"])} for a in (c or {}).get("away", [])]})
    w = body["week"]
    return {"week": {"from": w["from"], "to": w["to"], "words": w["words"], "which": which},
            "counts": {k: body["counts"][k] for k in ("on", "open", "away")},
            "look": [{"title": x["title"], "details": list(x["details"]),
                      "find": {"team": x["find"]["group_id"], "day": x["find"]["service_id"]} if x["find"] else None}
                     for x in body["look"]],
            "departments": out}


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def week_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's menu shows The week: the app asks once. Quietly
    false for a closed switch, a business that isn't a church, a login that
    keeps neither door of Who serves when, or a read that failed."""
    off = {"enabled": False, "hours": False, "checks": False}
    try:
        me = _reader(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail in ("Not Found", NOT_CHURCH):
            return off
        raise
    return {"enabled": True, "hours": me["hours"], "checks": me["checks"]}


@router.get("")
def week_read(business_id: str, start: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    """One week of every department's volunteers, read only."""
    me = _reader(business_id, user)
    import event_volunteers
    # Events' asks for the serving teams still waiting: The week's band.
    return {**week(me, start), "requests_waiting": event_volunteers.waiting_count(str(me["biz"]["id"]), user)}
