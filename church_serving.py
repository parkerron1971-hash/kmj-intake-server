"""church_serving.py — Serving hours and background checks (Sunday › Serving).

Kevin reviewed the Church Office Prototypes on 2026-10-27
(https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo, the "Serving hours" tab:
an office screen beside a member's phone) and picked this second: "lets go
with your list", then "make sure that the design is top tier". Filed under
the Build item "Love City leaves Subsplash (M-1)".

    HOURS ....... add up on their own from Who serves when (sunday_planning).
                  Every place someone said yes to, at a service this year
                  that has started, counts the time they served:
                    * the team's own length, when the office set one
                      ("Count each Sunday as 3 hours"), else
                    * the plan: from the team's arrive-by time (or the
                      plan's Before items, whichever is earlier) to the end
                      of the plan (its items' minutes, After included), else
                    * DEFAULT_SERVICE_MINUTES from the start, when the plan
                      has no times.
                  Two places one person held the same day count their time
                  once, never twice (the 9:00 and the 11:00 share a call
                  time). A sub who said yes gets the hours: the place became
                  theirs. A no, an ask nobody answered, an offered place and
                  a day the person marked away never count.
                  A logged group gathering counts the office's group length
                  (90 minutes until it's changed) for each leader of the
                  group who was marked there. Hours outside the schedule (a
                  work day) are added by the office, with a note.
    CHECKS ...... who works with kids or youth: the Youth and Kids leaders
                  (space_leaders) and everyone on a Sunday team whose area is
                  Kids & youth (church_areas: the church's pick, else its
                  name), or on its schedule. A check date is the latest of
                  the leader approval's and one recorded here; it is good
                  for the office's number of years (CHECK_YEARS by default).
                    ok ........ good past the next 30 days
                    due ....... runs out within DUE_DAYS
                    overdue ... ran out
                    none ...... no check on record
                    blocked ... no check on record and on the schedule with
                                kids or youth within SOON_DAYS: "Can't serve
                                with kids yet"
                    teen ...... under 18: checks are for adults
                  "Send check reminders" goes the ways serving already
                  reaches people: a phone alert (member_push "serving") and
                  an email with the office's own check link (a setting; no
                  vendor is wired in), once a week at most per person.

Storage: no migration. The office's lengths, check link and years live in
businesses.settings.church_serving; hours outside the schedule, a check date
recorded here and when a reminder last went live in contacts.metadata.serving.

  GET    /church/serving/status?business_id=          {enabled, checks, write}
  GET    /church/serving?business_id=&year=           the year's hours, the checks, what needs someone
  GET    /church/serving/people?business_id=&q=       find someone (names only), to add hours
  POST   /church/serving/hours                        {business_id, contact_id, on, hours, note}
  DELETE /church/serving/hours/{entry_id}?business_id=&contact_id=
  PUT    /church/serving/settings                     {business_id, team_minutes?, group_minutes?,
                                                       check_link?, check_years?}
  POST   /church/serving/checks                       {business_id, contact_id, on}   a check date
  POST   /church/serving/checks/remind                {business_id, contact_ids?}

Who: the owner and admins, and office logins whose areas (church_areas, Who
sees what) are the whole church or include Worship & media, Kids & youth or
People & care. The checks are Kids & youth's and People & care's (and the
owner's and admins'): anyone else gets the hours without them. Changing
anything is the owner's, an admin's or a manager's.

Switched by CHURCH_SERVING: off | owner | on (owner until a Thursday). The
member's own hours on My serving (member_portal_serving) follow the same
switch: on for everyone, and in owner mode only in the platform owner's own
preview of the member app.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/serving", tags=["church"])

HOURS_AREAS = ("worship_media", "kids_youth", "people_care")
CHECK_AREAS = ("kids_youth", "people_care")
KEEPS_ALL = ("owner", "admin")
WRITERS = ("owner", "admin", "manager")

DEFAULT_SERVICE_MINUTES = 90     # a service whose plan has no times
GROUP_MINUTES = 90               # a group gathering, until the office says otherwise
CALL_REACH = timedelta(hours=4)  # an arrive-by time further back than this isn't this service's
MAX_PLACE_MINUTES = 12 * 60
CHECK_YEARS = 2
YEARS_OK = (1, 2, 3, 4, 5)
DUE_DAYS = 30
SOON_DAYS = 28
REMIND_DAYS = 7
HOURS_KEPT = 300                 # entries outside the schedule, per person
NOTE_MAX = 200
LINK_MAX = 500
KEY = "serving"                  # contacts.metadata.serving / businesses.settings.church_serving
SETTINGS_KEY = "church_serving"
BEFORE = ("before", "before the service", "before service")
STATUSES = ("blocked", "overdue", "none", "due", "ok", "teen")
NEEDS = ("blocked", "overdue", "none", "due")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_SERVING") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _owner_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        return (user.email or "").strip().lower() == _owner_email()
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _ids(values: Iterable[Any]) -> str:
    return ",".join(_q(v) for v in sorted({str(v) for v in values if v}))


def _chunks(values: Iterable[Any], n: int = 120) -> List[List[str]]:
    out = sorted({str(v) for v in values if v})
    return [out[i:i + n] for i in range(0, len(out), n)]


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one is a 503, never zero hours."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Serving couldn't be read just now. Try again.")
    return rows


def _need_in(path: str, column: str, values: Iterable[Any], n: int = 120) -> List[Dict[str, Any]]:
    """`path` with `column=in.(…)` added, read in chunks so a URL stays short."""
    out: List[Dict[str, Any]] = []
    for part in _chunks(values, n):
        out += _need(f"{path}&{column}=in.({','.join(_q(v) for v in part)})")
    return out


def _zone(biz_id: str):
    import sunday_planning as sp
    return sp._zone(biz_id)


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hhmm(v: Any) -> Optional[time]:
    m = re.match(r"^(\d{1,2}):(\d{2})", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:      # Feb 29 in a year without one
        return d.replace(year=d.year + years, day=28)


def _age(born: Any, today: date) -> Optional[int]:
    b = _day(born)
    if not b:
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def _settings(biz: Dict[str, Any]) -> Dict[str, Any]:
    s = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    raw = s.get(SETTINGS_KEY) if isinstance(s.get(SETTINGS_KEY), dict) else {}
    team = raw.get("team_minutes") if isinstance(raw.get("team_minutes"), dict) else {}
    group = raw.get("group_minutes")
    years = raw.get("check_years")
    link = raw.get("check_link")
    return {
        "team_minutes": {str(k): int(v) for k, v in team.items()
                         if isinstance(v, int) and not isinstance(v, bool) and 15 <= v <= MAX_PLACE_MINUTES},
        "group_minutes": group if isinstance(group, int) and not isinstance(group, bool) and 15 <= group <= 480 else GROUP_MINUTES,
        "check_years": years if years in YEARS_OK else CHECK_YEARS,
        "check_link": link if isinstance(link, str) and _good_link(link) else "",
    }


def _good_link(v: str) -> bool:
    return bool(re.match(r"^https://[^\s<>\"']+$", v)) and len(v) <= LINK_MAX


def _mine(contact: Dict[str, Any]) -> Dict[str, Any]:
    meta = contact.get("metadata") if isinstance(contact.get("metadata"), dict) else {}
    rec = meta.get(KEY)
    return rec if isinstance(rec, dict) else {}


# ─── Hours: the arithmetic (pure) ─────────────────────────────────────

def plan_minutes(items: Any) -> Tuple[float, float]:
    """(minutes before the start, minutes from the start to the end) of a
    plan, read the way the order of service reads it (sunday_order): items
    under a section called Before count back from the start; everything
    else, After included, runs forward from it."""
    before = during = 0.0
    section = None
    for i in items if isinstance(items, list) else []:
        if not isinstance(i, dict):
            continue
        if i.get("kind") == "section":
            section = str(i.get("title") or "").strip().lower()
            continue
        try:
            m = min(max(float(i.get("minutes") or 0), 0.0), 240.0)
        except (TypeError, ValueError):
            m = 0.0
        if section in BEFORE:
            before += m
        else:
            during += m
    return before, during


def place_span(start: datetime, items: Any, call: Optional[time], set_minutes: Optional[int]) -> Tuple[datetime, datetime]:
    """When one place at one service was served: the team's set length from
    the start; else from the arrive-by time (or the plan's Before items,
    whichever is earlier) to the plan's end; else DEFAULT_SERVICE_MINUTES."""
    if set_minutes:
        return start, start + timedelta(minutes=set_minutes)
    before, during = plan_minutes(items)
    if during <= 0:
        during = DEFAULT_SERVICE_MINUTES
    begin = start - timedelta(minutes=before)
    if call:
        due = datetime.combine(start.date(), call, tzinfo=start.tzinfo)
        if due < begin and start - due <= CALL_REACH:
            begin = due
    end = start + timedelta(minutes=during)
    if end - begin > timedelta(minutes=MAX_PLACE_MINUTES):
        begin = end - timedelta(minutes=MAX_PLACE_MINUTES)
    return begin, end


def credit_day(spans: List[Tuple[datetime, datetime, str]]) -> List[Tuple[str, int]]:
    """One person's places on one day → (team, minutes) each, the time two
    places share counted once (for the earlier one)."""
    out: List[Tuple[str, int]] = []
    covered: Optional[datetime] = None
    for begin, end, team in sorted(spans, key=lambda s: (s[0], s[1])):
        start = max(begin, covered) if covered else begin
        mins = int(round((end - start).total_seconds() / 60)) if end > start else 0
        out.append((team, mins))
        covered = max(covered, end) if covered else end
    return out


def check_state(on: Optional[date], years: int, today: date, teen: bool, next_up: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """One person's check: status and when it runs out."""
    if teen:
        return {"status": "teen", "due": None}
    if on is None:
        return {"status": "blocked" if next_up else "none", "due": None}
    due = add_years(on, years)
    if due < today:
        return {"status": "overdue", "due": due.isoformat()}
    if (due - today).days <= DUE_DAYS:
        return {"status": "due", "due": due.isoformat()}
    return {"status": "ok", "due": due.isoformat()}


def _check_rank(c: Dict[str, Any]) -> Tuple[int, int, str]:
    order = {"blocked": 0, "overdue": 1, "none": 2, "due": 3, "ok": 4, "teen": 5}
    soon = 0 if c.get("next") else 1
    return (order[c["status"]], soon if c["status"] == "overdue" else 0, (c.get("name") or "").lower())


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _areas(biz_id: str, uid: str, role: str) -> Optional[List[str]]:
    """This login's areas, or None for the whole church (the owner and
    admins; anyone while Who sees what is off). A view that couldn't be read
    is a 503, never everything."""
    if role in KEEPS_ALL:
        return None
    import church_areas
    if church_areas.mode() != "on":
        return None
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    return None if areas is None else [str(a) for a in areas]


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and what this login may see and do here. 404 when the
    switch is closed to them, they have no login here, or it isn't a church;
    403 for a login whose areas leave Serving out."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Serving hours are for churches")
    areas = _areas(biz_id, str(user.id), role)
    if areas is not None and not set(areas) & set(HOURS_AREAS):
        raise HTTPException(403, "Serving belongs to Worship & media, Kids & youth and People & care. "
                                 "An admin can add one of them to your areas.")
    checks = areas is None or bool(set(areas) & set(CHECK_AREAS))
    return {"biz": biz, "role": role, "uid": str(user.id), "checks": checks, "write": role in WRITERS}


def _may_write(me: Dict[str, Any], checks: bool = False) -> None:
    if not me["write"]:
        raise HTTPException(403, "Only the owner, an admin or a manager changes this.")
    if checks and not me["checks"]:
        raise HTTPException(403, "Background checks belong to Kids & youth and People & care.")


# ─── Hours: the reads ─────────────────────────────────────────────────

def _year_window(zone, year: int, now: datetime) -> Tuple[datetime, datetime]:
    lo = datetime(year, 1, 1, tzinfo=zone)
    hi = min(datetime(year + 1, 1, 1, tzinfo=zone), now.astimezone(zone))
    return lo, hi


def _sunday_spans(biz_id: str, zone, lo: datetime, hi: datetime, settings: Dict[str, Any],
                  only: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Every yes this year, as credits {contact_id, team, minutes, day}; and
    the teams' names. Away days, and anything but a yes, never count."""
    b = _q(biz_id)
    window = (f"&starts_at=gte.{_q(lo.astimezone(timezone.utc).isoformat())}"
              f"&starts_at=lt.{_q(hi.astimezone(timezone.utc).isoformat())}")
    if only:
        said = _need(f"/serve_assignments?business_id=eq.{b}&contact_id=eq.{_q(only)}&status=eq.yes"
                     f"&select=service_id,position_id,contact_id&limit=5000")
        services = _need_in(f"/worship_services?business_id=eq.{b}&archived_at=is.null&is_template=eq.false{window}"
                            f"&select=id,starts_at,items", "id", [r["service_id"] for r in said]) if said else []
    else:
        services = _need(f"/worship_services?business_id=eq.{b}&archived_at=is.null&is_template=eq.false{window}"
                         f"&select=id,starts_at,items&order=starts_at.asc&limit=3000")
        said = _need_in(f"/serve_assignments?business_id=eq.{b}&status=eq.yes&select=service_id,position_id,contact_id",
                        "service_id", [s["id"] for s in services]) if services else []
    svc = {str(s["id"]): s for s in services}
    said = [r for r in said if str(r.get("service_id")) in svc and r.get("contact_id")]
    if not said:
        return [], {}
    places = {str(p["id"]): p for p in _need_in(f"/serve_positions?business_id=eq.{b}&select=id,group_id,name",
                                                 "id", [r["position_id"] for r in said])}
    turns = {str(t["group_id"]): t for t in _need(f"/serve_teams?business_id=eq.{b}&select=group_id,call_time&limit=200")}
    gids = {str(p.get("group_id")) for p in places.values() if p.get("group_id")}
    names = {str(g["id"]): _plain(g.get("name")) or "A team"
             for g in _need_in(f"/groups?business_id=eq.{b}&select=id,name", "id", gids)} if gids else {}
    who = f"&contact_id=eq.{_q(only)}" if only else ""
    away = _need(f"/serve_away?business_id=eq.{b}{who}&starts_on=lte.{hi.date().isoformat()}"
                 f"&ends_on=gte.{lo.date().isoformat()}&select=contact_id,starts_on,ends_on&limit=5000")
    gone: Dict[str, List[Tuple[str, str]]] = {}
    for a in away:
        gone.setdefault(str(a["contact_id"]), []).append((str(a["starts_on"])[:10], str(a["ends_on"])[:10]))
    by_day: Dict[Tuple[str, str], List[Tuple[datetime, datetime, str]]] = {}
    for r in said:
        s = svc[str(r["service_id"])]
        start = _at(s.get("starts_at"))
        place = places.get(str(r["position_id"]))
        if not start or not place:
            continue
        start = start.astimezone(zone)
        cid, day = str(r["contact_id"]), start.date().isoformat()
        if any(a <= day <= z for a, z in gone.get(cid, [])):
            continue
        gid = str(place.get("group_id") or "")
        span = place_span(start, s.get("items"), _hhmm((turns.get(gid) or {}).get("call_time")),
                          settings["team_minutes"].get(gid))
        by_day.setdefault((cid, day), []).append((span[0], span[1], gid))
    out = []
    for (cid, day), spans in by_day.items():
        for gid, mins in credit_day(spans):
            out.append({"contact_id": cid, "team": gid, "minutes": mins, "day": day})
    return out, names


def _group_credits(biz_id: str, lo: date, hi: date, settings: Dict[str, Any],
                   only: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """A logged gathering counts for each leader of the group who was marked
    there. A Sunday team's own group never counts here: its hours are its
    Sundays."""
    b = _q(biz_id)
    who = f"&contact_id=eq.{_q(only)}" if only else ""
    leads = _need(f"/group_members?business_id=eq.{b}&role=eq.leader{who}&select=group_id,contact_id&limit=5000")
    if not leads:
        return [], {}
    groups = {str(g["id"]): g for g in _need_in(f"/groups?business_id=eq.{b}&select=id,name,kind", "id",
                                               [x["group_id"] for x in leads])}
    led = {(str(x["group_id"]), str(x["contact_id"])) for x in leads
           if str(x["group_id"]) in groups and groups[str(x["group_id"])].get("kind") != "team"}
    if not led:
        return [], {}
    meetings = {str(m["id"]): m for m in _need_in(
        f"/group_meetings?business_id=eq.{b}&met_on=gte.{lo.isoformat()}&met_on=lte.{hi.isoformat()}"
        f"&select=id,group_id,met_on", "group_id", {g for g, _ in led})}
    if not meetings:
        return [], {}
    came = _need_in(f"/group_meeting_attendance?business_id=eq.{b}{who}&select=meeting_id,contact_id",
                    "meeting_id", meetings, n=100)
    out = []
    for c in came:
        m = meetings.get(str(c.get("meeting_id")))
        if m and (str(m["group_id"]), str(c["contact_id"])) in led:
            out.append({"contact_id": str(c["contact_id"]), "group": str(m["group_id"]),
                        "minutes": settings["group_minutes"], "day": str(m["met_on"])[:10]})
    return out, {g: _plain(groups[g].get("name")) or "A group" for g, _ in led}


def _extra_rows(biz_id: str, only: Optional[str] = None) -> List[Dict[str, Any]]:
    """Everyone with something recorded here: hours outside the schedule, a
    check date, a reminder."""
    b = _q(biz_id)
    one = f"&id=eq.{_q(only)}" if only else ""
    has = _q(json.dumps({KEY: {}}, separators=(",", ":")))
    return _need(f"/contacts?business_id=eq.{b}{one}&metadata=cs.{has}&select=id,name,birthdate,metadata&limit=2000")


def _extra_credits(rows: List[Dict[str, Any]], year: int) -> List[Dict[str, Any]]:
    out = []
    for c in rows:
        for e in _mine(c).get("hours") or []:
            if not isinstance(e, dict):
                continue
            on = _day(e.get("on"))
            mins = e.get("minutes")
            if on and on.year == year and isinstance(mins, int) and mins > 0:
                out.append({"contact_id": str(c["id"]), "minutes": mins, "day": on.isoformat(),
                            "id": str(e.get("id") or ""), "note": str(e.get("note") or ""), "by": str(e.get("by_name") or "")})
    return out


def _people(biz_id: str, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    rows = _need_in(f"/contacts?business_id=eq.{_q(biz_id)}&select=id,name,birthdate", "id", ids)
    return {str(r["id"]): {"name": _plain(r.get("name")) or "Someone", "birthdate": r.get("birthdate")} for r in rows}


# ─── Checks: the reads ────────────────────────────────────────────────

def _kids_teams(biz_id: str) -> Dict[str, str]:
    """The Sunday teams whose area is Kids & youth: the church's pick for
    the team, else what its name says."""
    import church_areas
    b = _q(biz_id)
    turns = _need(f"/serve_teams?business_id=eq.{b}&select=group_id&limit=200")
    if not turns:
        return {}
    groups = _need_in(f"/groups?business_id=eq.{b}&active=eq.true&select=id,name", "id", [t["group_id"] for t in turns])
    try:
        places = church_areas._places(biz_id)
    except HTTPException:
        places = {}   # a pick only narrows; the name still says
    return {str(g["id"]): _plain(g.get("name")) for g in groups
            if church_areas.place_team(_plain(g.get("name")), places).get("area") == "kids_youth"}


def checks(biz: Dict[str, Any], settings: Dict[str, Any], today: date, zone,
           only: Optional[str] = None, extra_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Everyone who works with kids or youth, with their check."""
    biz_id = str(biz["id"])
    b = _q(biz_id)
    who = f"&contact_id=eq.{_q(only)}" if only else ""
    leaders = _need(f"/space_leaders?business_id=eq.{b}{who}&select=contact_id,space,background_check_on&limit=2000")
    teams = _kids_teams(biz_id)
    where: Dict[str, List[str]] = {}
    dates: Dict[str, List[date]] = {}
    for x in leaders:
        cid = str(x["contact_id"])
        label = "Youth leader" if x.get("space") == "youth" else "Kids leader"
        if label not in where.setdefault(cid, []):
            where[cid].append(label)
        d = _day(x.get("background_check_on"))
        if d:
            dates.setdefault(cid, []).append(d)
    nexts: Dict[str, Dict[str, Any]] = {}
    if teams:
        members = _need_in(f"/group_members?business_id=eq.{b}{who}&select=group_id,contact_id", "group_id", teams)
        for m in members:
            cid = str(m["contact_id"])
            name = teams.get(str(m["group_id"]))
            if name and name not in where.setdefault(cid, []):
                where[cid].append(name)
        places = {str(p["id"]): p for p in _need_in(f"/serve_positions?business_id=eq.{b}&active=eq.true&select=id,group_id,name",
                                                     "group_id", teams)}
        now = _now().astimezone(zone)
        soon = _need(f"/worship_services?business_id=eq.{b}&archived_at=is.null&is_template=eq.false"
                     f"&starts_at=gte.{_q((now - timedelta(hours=3)).astimezone(timezone.utc).isoformat())}"
                     f"&starts_at=lt.{_q((now + timedelta(days=SOON_DAYS)).astimezone(timezone.utc).isoformat())}"
                     f"&select=id,starts_at&order=starts_at.asc&limit=200")
        if soon and places:
            when = {str(s["id"]): _at(s.get("starts_at")) for s in soon}
            rows = _need_in(f"/serve_assignments?business_id=eq.{b}{who}&status=in.(asked,yes)"
                            f"&service_id=in.({_ids(when)})&select=service_id,position_id,contact_id",
                            "position_id", places)
            for r in rows:
                at, p = when.get(str(r["service_id"])), places.get(str(r["position_id"]))
                if not at or not p or not r.get("contact_id"):
                    continue
                cid = str(r["contact_id"])
                team = teams.get(str(p.get("group_id")), "")
                if team and team not in where.setdefault(cid, []):
                    where[cid].append(team)
                local = at.astimezone(zone)
                if cid not in nexts or local.date().isoformat() < nexts[cid]["day"]:
                    nexts[cid] = {"day": local.date().isoformat(), "place": _plain(p.get("name")), "team": team}
    if not where:
        return []
    recorded = {str(c["id"]): c for c in (extra_rows if extra_rows is not None else _extra_rows(biz_id, only))}
    people = _people(biz_id, where)
    out = []
    for cid, labels in where.items():
        person = people.get(cid)
        if not person:
            continue
        mine = _mine(recorded.get(cid) or {})
        own = _day(mine.get("check_on"))
        on = max(dates.get(cid, []) + ([own] if own else []), default=None)
        age = _age(person.get("birthdate"), today)
        state = check_state(on, settings["check_years"], today, age is not None and age < 18, nexts.get(cid))
        out.append({"contact_id": cid, "name": person["name"], "where": labels, "on": on.isoformat() if on else None,
                    **state, "next": nexts.get(cid), "reminded_at": mine.get("reminded_at")})
    out.sort(key=_check_rank)
    return out


# ─── The page ─────────────────────────────────────────────────────────

def _leans(teams: List[Dict[str, Any]], person_names: Dict[str, str]) -> List[Dict[str, Any]]:
    """A team that leans on one person: three or more served this year, at
    least six hours between them, and one gave half or more."""
    out = []
    for t in teams:
        if t["people"] < 3 or t["minutes"] < 360 or not t.get("top"):
            continue
        top = t["top"]
        if top["minutes"] * 2 >= t["minutes"]:
            out.append({"kind": "team", "group_id": t["group_id"], "name": t["name"], "minutes": t["minutes"],
                        "top": {"contact_id": top["contact_id"], "name": person_names.get(top["contact_id"], "Someone"),
                                "minutes": top["minutes"]}})
    return out


def overview(me: Dict[str, Any], year: Optional[int] = None) -> Dict[str, Any]:
    biz = me["biz"]
    biz_id = str(biz["id"])
    zone = _zone(biz_id)
    now = _now()
    this_year = now.astimezone(zone).year
    year = this_year if year is None else year
    if not this_year - 3 <= year <= this_year:
        raise HTTPException(400, f"Pick a year from {this_year - 3} to {this_year}.")
    settings = _settings(biz)
    lo, hi = _year_window(zone, year, now)
    sundays, team_names = _sunday_spans(biz_id, zone, lo, hi, settings)
    groups, group_names = _group_credits(biz_id, lo.date(), hi.date(), settings)
    extra_rows = _extra_rows(biz_id)
    extra = _extra_credits(extra_rows, year)

    per: Dict[str, Dict[str, Any]] = {}

    def person(cid: str) -> Dict[str, Any]:
        return per.setdefault(cid, {"contact_id": cid, "minutes": 0, "sundays": 0, "sunday_minutes": 0, "gatherings": 0,
                                    "group_minutes": 0, "extra_minutes": 0, "teams": {}, "days": set()})
    team_tot: Dict[str, Dict[str, Any]] = {}
    for c in sundays:
        p = person(c["contact_id"])
        p["minutes"] += c["minutes"]
        p["sunday_minutes"] += c["minutes"]
        p["days"].add(c["day"])
        p["teams"][c["team"]] = p["teams"].get(c["team"], 0) + c["minutes"]
        t = team_tot.setdefault(c["team"], {"minutes": 0, "by": {}, "places": 0})
        t["minutes"] += c["minutes"]
        t["places"] += 1
        t["by"][c["contact_id"]] = t["by"].get(c["contact_id"], 0) + c["minutes"]
    for c in groups:
        p = person(c["contact_id"])
        p["minutes"] += c["minutes"]
        p["group_minutes"] += c["minutes"]
        p["gatherings"] += 1
    for c in extra:
        p = person(c["contact_id"])
        p["minutes"] += c["minutes"]
        p["extra_minutes"] += c["minutes"]

    for p in per.values():
        p["sundays"] = len(p.pop("days"))
    names = _people(biz_id, per)
    rows = []
    for cid, p in per.items():
        if p["minutes"] <= 0 or cid not in names:
            continue
        p["name"] = names[cid]["name"]
        p["teams"] = [team_names.get(g, "A team") for g, _ in sorted(p["teams"].items(), key=lambda kv: -kv[1])]
        rows.append(p)
    rows.sort(key=lambda p: (-p["minutes"], p["name"].lower()))

    teams = []
    for gid, t in team_tot.items():
        top_cid, top_min = max(t["by"].items(), key=lambda kv: kv[1]) if t["by"] else (None, 0)
        teams.append({"group_id": gid, "name": team_names.get(gid, "A team"), "minutes": t["minutes"],
                      "people": len(t["by"]), "places": t["places"],
                      "set_minutes": settings["team_minutes"].get(gid),
                      "top": {"contact_id": top_cid, "minutes": top_min} if top_cid else None})
    teams.sort(key=lambda t: (-t["minutes"], t["name"].lower()))
    # Teams the office can set a length for: every Sunday team, served yet or not.
    sunday_teams = _need(f"/serve_teams?business_id=eq.{_q(biz_id)}&select=group_id,call_time,sort&order=sort.asc&limit=200")
    st_names = {str(g["id"]): _plain(g.get("name")) for g in _need_in(
        f"/groups?business_id=eq.{_q(biz_id)}&active=eq.true&select=id,name", "id", [t["group_id"] for t in sunday_teams])}
    lengths = [{"group_id": str(t["group_id"]), "name": st_names[str(t["group_id"])],
                "call_time": str(t.get("call_time") or "")[:5] or None,
                "set_minutes": settings["team_minutes"].get(str(t["group_id"]))}
               for t in sunday_teams if str(t["group_id"]) in st_names]

    person_names = {cid: names[cid]["name"] for cid in names}
    check_rows: Optional[List[Dict[str, Any]]] = None
    if me["checks"]:
        check_rows = checks(biz, settings, now.astimezone(zone).date(), zone, extra_rows=extra_rows)
    needs: List[Dict[str, Any]] = []
    if check_rows:
        needs += [{"kind": "check", **c} for c in check_rows if c["status"] in NEEDS]
    needs += _leans(teams, person_names)

    group_minutes = sum(c["minutes"] for c in groups)
    recent_extra = sorted(extra, key=lambda e: e["day"], reverse=True)[:12]
    return {
        "year": year, "years": list(range(this_year, this_year - 4, -1)),
        "today": now.astimezone(zone).date().isoformat(),
        "totals": {"minutes": sum(p["minutes"] for p in rows), "people": len(rows),
                   "sunday_minutes": sum(c["minutes"] for c in sundays), "places": len(sundays),
                   "group_minutes": group_minutes, "gatherings": len(groups),
                   "extra_minutes": sum(e["minutes"] for e in extra)},
        "people": rows[:500],
        "teams": teams,
        "groups": {"minutes": group_minutes, "gatherings": len(groups),
                   "leaders": len({c["contact_id"] for c in groups}), "names": sorted(set(group_names.values()))},
        "extra": [{**e, "name": person_names.get(e["contact_id"], "Someone")} for e in recent_extra],
        "lengths": lengths,
        "needs": needs,
        "checks": check_rows,
        "check_counts": ({s: sum(1 for c in check_rows if c["status"] == s) for s in STATUSES}
                         if check_rows is not None else None),
        "settings": {"group_minutes": settings["group_minutes"],
                     "check_years": settings["check_years"] if me["checks"] else None,
                     "check_link": settings["check_link"] if me["checks"] else None,
                     "default_minutes": DEFAULT_SERVICE_MINUTES},
        "can": {"write": me["write"], "checks": me["checks"], "remind": me["write"] and me["checks"]},
    }


# ─── The member's own (My serving) ───────────────────────────────────

def member_on(platform_owner_preview: bool) -> bool:
    """The member's hours follow the office's switch: on for everyone, and
    in owner mode only in the platform owner's own preview."""
    m = mode()
    return m == "on" or (m == "owner" and platform_owner_preview)


def member_view(biz: Dict[str, Any], cid: str) -> Dict[str, Any]:
    """One member's own hours this year and, when they serve with kids or
    youth, their check. Nobody else's: every read is filtered to them."""
    biz_id = str(biz["id"])
    zone = _zone(biz_id)
    now = _now()
    year = now.astimezone(zone).year
    settings = _settings(biz)
    lo, hi = _year_window(zone, year, now)
    sundays, team_names = _sunday_spans(biz_id, zone, lo, hi, settings, only=cid)
    groups, _ = _group_credits(biz_id, lo.date(), hi.date(), settings, only=cid)
    mine = _extra_rows(biz_id, only=cid)
    extra = _extra_credits(mine, year)
    by_team: Dict[str, int] = {}
    for c in sundays:
        by_team[c["team"]] = by_team.get(c["team"], 0) + c["minutes"]
    check = checks(biz, settings, now.astimezone(zone).date(), zone, only=cid, extra_rows=mine)
    c = next((x for x in check if x["contact_id"] == cid), None)
    return {
        "year": year,
        "minutes": sum(x["minutes"] for x in sundays) + sum(x["minutes"] for x in groups) + sum(x["minutes"] for x in extra),
        "sundays": len({x["day"] for x in sundays}),
        "teams": [team_names.get(g, "your team") for g, _ in sorted(by_team.items(), key=lambda kv: -kv[1])],
        "gatherings": len(groups),
        "extra": len(extra),
        "check": ({"status": c["status"], "on": c["on"], "due": c["due"], "next": c["next"]} if c else None),
        "check_link": settings["check_link"] or None,
    }


# ─── Writes ───────────────────────────────────────────────────────────

def _contact(biz_id: str, contact_id: Any) -> Dict[str, Any]:
    cid = _uuid(contact_id, "person")
    rows = _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&select=id,name,birthdate,metadata,updated_at&limit=1")
    if not rows:
        raise HTTPException(404, "That person isn't one of this church's.")
    return rows[0]


def _write_mine(biz_id: str, contact_id: str, change) -> Dict[str, Any]:
    """Read the person, let change(rec) return their new serving record,
    write it guarded by updated_at (an edit at the same moment isn't lost)."""
    for _ in range(3):
        row = _contact(biz_id, contact_id)
        meta = dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {}
        rec = change(dict(_mine(row)))
        meta[KEY] = rec
        guard = f"&updated_at=eq.{_q(row['updated_at'])}" if row.get("updated_at") else ""
        saved = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz_id)}{guard}&select=id", {"metadata": meta})
        if saved is None:
            raise HTTPException(503, "That didn't save. Try again.")
        if saved:
            return rec
    raise HTTPException(409, "Someone changed that person at the same moment. Try again.")


def _by_name(me: Dict[str, Any], user: AuthedUser) -> str:
    """Who added hours, as the office's list says it: the owner by the
    church's name for its leader, anyone else by their login."""
    if me["role"] == "owner":
        s = me["biz"].get("settings") if isinstance(me["biz"].get("settings"), dict) else {}
        return (_plain(s.get("practitioner_name")) or "The office")[:80]
    email = (user.email or "").strip()
    return (email.split("@")[0] if email else "The office")[:80]


_OWNER_SEEN: Dict[str, bool] = {}


def is_platform_owner(owner_id: Any) -> bool:
    """Whether a member-app preview was opened by the platform owner (the
    owner-mode switch shows the member's hours there and nowhere else). A
    lookup that fails is a no."""
    key = str(owner_id or "")
    if not key:
        return False
    if key not in _OWNER_SEEN:
        try:
            import platform_suite
            _OWNER_SEEN[key] = (platform_suite._owner_email(key) or "") == _owner_email()
        except Exception:  # noqa: BLE001 — unread is a no, and is asked again next time
            return False
    return _OWNER_SEEN[key]


def add_hours(me: Dict[str, Any], user: AuthedUser, body: Dict[str, Any]) -> Dict[str, Any]:
    _may_write(me)
    biz_id = str(me["biz"]["id"])
    zone = _zone(biz_id)
    today = _now().astimezone(zone).date()
    on = _day(body.get("on"))
    if not on or on > today or on.year < today.year - 3:
        raise HTTPException(400, "Pick the day they served: not in the future, and within the last three years.")
    try:
        hours = float(body.get("hours"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Hours is a number, like 3 or 1.5.")
    if not 0.25 <= hours <= 24:
        raise HTTPException(400, "Hours is from a quarter of an hour to 24.")
    note = _plain(body.get("note"))[:NOTE_MAX]
    if not note:
        raise HTTPException(400, "Say what they did, like \"Fall work day\".")
    entry = {"id": str(uuid.uuid4()), "on": on.isoformat(), "minutes": int(round(hours * 60)), "note": note,
             "by": me["uid"], "by_name": _by_name(me, user), "at": _now().isoformat()}

    def change(rec):
        kept = [e for e in (rec.get("hours") or []) if isinstance(e, dict)]
        if len(kept) >= HOURS_KEPT:
            raise HTTPException(400, f"{HOURS_KEPT} entries is the most one person keeps. Take an old one off first.")
        rec["hours"] = kept + [entry]
        return rec
    _write_mine(biz_id, body.get("contact_id"), change)
    return {"entry": {k: v for k, v in entry.items() if k != "by"}}


def drop_hours(me: Dict[str, Any], contact_id: Any, entry_id: str) -> Dict[str, Any]:
    _may_write(me)
    biz_id = str(me["biz"]["id"])
    eid = _uuid(entry_id, "entry")
    found = {"hit": False}

    def change(rec):
        kept = [e for e in (rec.get("hours") or []) if isinstance(e, dict)]
        rest = [e for e in kept if str(e.get("id")) != eid]
        found["hit"] = len(rest) != len(kept)
        rec["hours"] = rest
        return rec
    _write_mine(biz_id, contact_id, change)
    if not found["hit"]:
        raise HTTPException(404, "Those hours aren't there anymore.")
    return {"ok": True}


def record_check(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    _may_write(me, checks=True)
    biz_id = str(me["biz"]["id"])
    today = _now().astimezone(_zone(biz_id)).date()
    on = _day(body.get("on"))
    if not on or on > today or on.year < 2000:
        raise HTTPException(400, "The check's date can't be in the future.")
    cid = _uuid(body.get("contact_id"), "person")

    def change(rec):
        rec["check_on"] = on.isoformat()
        rec["check_by"] = me["uid"]
        rec["check_at"] = _now().isoformat()
        return rec
    _write_mine(biz_id, cid, change)
    # The Youth and Kids leaders page shows the same date: keep it in step
    # where this one is newer.
    leaders = sb_clients.sb_get_as_service(
        f"/space_leaders?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&select=space,background_check_on")
    for x in leaders if isinstance(leaders, list) else []:
        had = _day(x.get("background_check_on"))
        if had is None or had < on:
            sb_clients.sb_patch_as_service(
                f"/space_leaders?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&space=eq.{_q(x['space'])}",
                {"background_check_on": on.isoformat()})
    return {"on": on.isoformat()}


def save_settings(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    _may_write(me, checks=("check_link" in body or "check_years" in body))
    biz_id = str(me["biz"]["id"])
    biz = _business(biz_id)
    settings = dict(biz.get("settings") or {}) if isinstance(biz.get("settings"), dict) else {}
    cur = dict(settings.get(SETTINGS_KEY) or {}) if isinstance(settings.get(SETTINGS_KEY), dict) else {}
    changed = False
    if "team_minutes" in body:
        want = body.get("team_minutes")
        if not isinstance(want, dict) or len(want) > 50:
            raise HTTPException(400, "team_minutes is {team: minutes}.")
        teams = {str(t["group_id"]) for t in _need(f"/serve_teams?business_id=eq.{_q(biz_id)}&select=group_id&limit=200")}
        team = dict(cur.get("team_minutes") or {}) if isinstance(cur.get("team_minutes"), dict) else {}
        for gid, mins in want.items():
            gid = _uuid(gid, "team")
            if gid not in teams:
                raise HTTPException(404, "That team isn't on Sundays here.")
            if mins in (None, ""):
                team.pop(gid, None)
            elif isinstance(mins, int) and not isinstance(mins, bool) and 15 <= mins <= MAX_PLACE_MINUTES:
                team[gid] = mins
            else:
                raise HTTPException(400, "A Sunday counts from a quarter of an hour to 12 hours.")
        cur["team_minutes"] = team
        changed = True
    if "group_minutes" in body:
        g = body.get("group_minutes")
        if not isinstance(g, int) or isinstance(g, bool) or not 15 <= g <= 480:
            raise HTTPException(400, "A group gathering counts from a quarter of an hour to 8 hours.")
        cur["group_minutes"] = g
        changed = True
    if "check_link" in body:
        link = str(body.get("check_link") or "").strip()
        if link and not _good_link(link):
            raise HTTPException(400, "The check link is a web address starting with https://.")
        cur["check_link"] = link
        changed = True
    if "check_years" in body:
        y = body.get("check_years")
        if y not in YEARS_OK or isinstance(y, bool):
            raise HTTPException(400, "A check is good for 1 to 5 years.")
        cur["check_years"] = y
        changed = True
    if not changed:
        raise HTTPException(400, "Nothing to change.")
    settings[SETTINGS_KEY] = cur
    saved = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id", {"settings": settings})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    s = _settings({"settings": settings})
    return {"settings": {"team_minutes": s["team_minutes"], "group_minutes": s["group_minutes"],
                         "check_link": s["check_link"], "check_years": s["check_years"]}}


# ─── Check reminders ──────────────────────────────────────────────────

def _month_day(iso: Optional[str]) -> str:
    d = _day(iso)
    return f"{d.strftime('%b')} {d.day}" if d else ""


def reminder_words(church: str, c: Dict[str, Any], link: bool) -> Dict[str, str]:
    """The words of one reminder, by where their check stands."""
    if c["status"] == "due":
        title = f"Your background check runs out {_month_day(c['due'])}"
        said = f"Yours runs out {_month_day(c['due'])}."
    elif c["status"] == "overdue":
        title = "Your background check needs renewing"
        said = f"Yours ran out {_month_day(c['due'])}."
    else:
        title = "A background check before you serve with kids"
        said = "We don't have one on record for you yet."
    how = "You can start it from the link below." if link else "The office will send you the link to start it."
    body = f"{church} asks everyone who serves with kids and youth to keep a current background check. {said} {how}"
    return {"title": title, "body": body}


async def _email_one(biz: Dict[str, Any], person: Dict[str, Any], w: Dict[str, str], cta: Optional[Tuple[str, str]],
                     app_link: Optional[str], week: str) -> bool:
    import academy_join
    import email_layout
    import email_sender
    import serve_links
    from html import escape
    email = str(person.get("email") or "").strip()
    if not academy_join.valid_email(email):
        return False
    church = _plain(biz.get("name")) or "Your church"
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    stop = serve_links.stop_token(str(biz["id"]), str(person["id"]))
    after = ""
    if app_link and cta and cta[1] != app_link:
        after = (f'<p style="margin:0 0 20px;font-family:Arial,Helvetica,sans-serif;font-size:14px;">'
                 f'<a href="{escape(app_link)}" style="color:#1d45f2;font-weight:600;text-decoration:none;">'
                 f'Or open My serving in {escape(church)}\'s app</a></p>')
    html = email_layout.render_html(
        "\n\n".join([w["title"], w["body"]]), business_name=church, brand=email_layout.brand_of(settings), sig=None,
        unsubscribe_url=serve_links.page_url(stop, stop="1"), unsubscribe_label="Stop these emails",
        preheader=w["body"][:90], cta=cta, after_cta=after,
        disclaimer=f"You serve with kids or youth at {church}.", footer_note="Sent by your church office")
    await email_sender.send_via_resend(
        to_email=email, to_name=person.get("name") or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=church, subject=w["title"][:150], body=html, reply_to=None,
        business_id=str(biz["id"]), idempotency_key=f"serving-check-{person['id']}-{week}",
        unsubscribe_url=serve_links.one_click_url(stop))
    return True


async def remind(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """Send check reminders to everyone whose check needs them (or to the
    ones picked): a phone alert and an email, never twice in a week."""
    _may_write(me, checks=True)
    biz = me["biz"]
    biz_id = str(biz["id"])
    zone = await asyncio.to_thread(_zone, biz_id)
    settings = _settings(biz)
    now = _now()
    rows = await asyncio.to_thread(checks, biz, settings, now.astimezone(zone).date(), zone)
    picked = body.get("contact_ids")
    if picked is not None:
        if not isinstance(picked, list) or len(picked) > 500:
            raise HTTPException(400, "contact_ids is a list of people.")
        picked = {_uuid(p, "person") for p in picked}
    out = {"sent": 0, "phones": 0, "emails": 0, "recent": 0, "unreachable": 0}
    targets = []
    for c in rows:
        if c["status"] not in NEEDS or (picked is not None and c["contact_id"] not in picked):
            continue
        last = _at(c.get("reminded_at"))
        if last and now - last < timedelta(days=REMIND_DAYS):
            out["recent"] += 1
            continue
        targets.append(c)
    if not targets:
        return out
    import group_email
    import member_push
    import sunday_serving as sv
    people = {str(p["id"]): p for p in (await asyncio.to_thread(group_email._people, biz_id, [c["contact_id"] for c in targets]) or [])}
    app = await asyncio.to_thread(group_email.app_url, biz_id)
    link = settings["check_link"]
    church = _plain(biz.get("name")) or "Your church"
    week = now.astimezone(zone).strftime("%G-W%V")
    for c in targets:
        person = people.get(c["contact_id"])
        if not person or not group_email._adult(person):
            continue
        w = reminder_words(church, c, bool(link))
        rang = await asyncio.to_thread(member_push.send, biz, "serving", title=w["title"], body=w["body"],
                                       url="/my/serving", contact_ids=[c["contact_id"]],
                                       ref_id=f"check-{c['contact_id']}-{week}", tag=f"serving-check-{c['contact_id']}")
        mailed = False
        try:
            stopped = not await asyncio.to_thread(sv.emails_on, biz_id, c["contact_id"])
        except HTTPException:
            stopped = True
        if not stopped:
            cta = ("Start my background check", link) if link else (
                ("Open My serving", f"{app}/my/serving") if app else None)
            try:
                mailed = await _email_one(biz, person, w, cta, f"{app}/my/serving" if app else None, week)
            except Exception:  # noqa: BLE001 — one address never stops the rest
                logger.warning("serving checks: one reminder email failed", exc_info=True)
        if not rang and not mailed:
            out["unreachable"] += 1
            continue
        out["sent"] += 1
        out["phones"] += 1 if rang else 0
        out["emails"] += 1 if mailed else 0
        stamp = now.isoformat()

        def change(rec, stamp=stamp):
            rec["reminded_at"] = stamp
            return rec
        try:
            await asyncio.to_thread(_write_mine, biz_id, c["contact_id"], change)
        except HTTPException:
            logger.warning("serving checks: reminded_at didn't save for one person")
    return out


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def serving_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's Sunday door shows Serving, and the checks on it:
    the app asks once, so its menu offers it only where it opens. Quietly
    false for a closed switch, a business that isn't a church, a login
    whose areas leave it out, or a read that failed."""
    off = {"enabled": False, "checks": False, "write": False}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == "Serving hours are for churches":
            return off
        raise
    return {"enabled": True, "checks": me["checks"], "write": me["write"]}


@router.get("")
def serving_read(business_id: str, year: Optional[int] = None, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    return overview(me, year)


@router.get("/people")
def serving_people(business_id: str, q: str = "", user: AuthedUser = Depends(require_user)):
    """Someone to add hours for, by name: names only."""
    me = _access(business_id, user)
    _may_write(me)
    term = re.sub(r"[^\w .'-]", "", " ".join(q.split())[:60])
    if len(term) < 2:
        return {"people": []}
    rows = _need(f"/contacts?business_id=eq.{_q(me['biz']['id'])}&name=ilike.*{_q(term)}*&select=id,name"
                 f"&order=name.asc&limit=12")
    return {"people": [{"contact_id": str(r["id"]), "name": _plain(r.get("name")) or "Someone"} for r in rows]}


@router.post("/hours")
def serving_add_hours(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return add_hours(me, user, body)


@router.delete("/hours/{entry_id}")
def serving_drop_hours(entry_id: str, business_id: str, contact_id: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    return drop_hours(me, contact_id, entry_id)


@router.put("/settings")
def serving_settings(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return save_settings(me, body)


@router.post("/checks")
def serving_record_check(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return record_check(me, body)


@router.post("/checks/remind")
async def serving_remind(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = await asyncio.to_thread(_access, body.get("business_id"), user)
    return await remind(me, body)
