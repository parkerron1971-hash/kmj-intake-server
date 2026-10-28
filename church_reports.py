"""church_reports.py — the Reports pack: the year's numbers a church is asked for.

Kevin, 2026-10-27, on the Church Office Prototypes ("Reports pack" tab,
artifact 2vGqaUZUynRuiFVKuQEZWo): "lets go with your list", the sixth and
last; "make sure that the design is top tier". Members ask for these numbers
at the annual business meeting and denominations ask for them every year.
The data is already in the app; this page only gathers it. Lane: Build,
under the Build item "Love City leaves Subsplash (M-1)".

One year at a time (this year and the four before it), every number
computed here from tables the app already keeps, each with the place it
came from. A number that can't be known is None with the reason, never a
guess and never a zero standing in for "we don't know". Long reads go a
page of 1000 at a time in a stable order (PostgREST caps a read), so a
count is never cut short.

    SUNDAY ...... Attendance (attendance, attendance_headcounts): each
                  service's headcount, or the people checked in by name if
                  that's more (Attendance's own rule). A service is a
                  Services & Events occasion the app calls one (its type,
                  else its room's noun, else a Sunday; churchCalendar's
                  rosterKind). Services nobody counted are left out of the
                  average. Kids checked in (child_checkins) beside it.
    PEOPLE ...... Members are records marked active or VIP (the member
                  directory's rule). Today's count is exact. A past day's
                  is today's list rewound through the status changes the
                  app logged (events, contact_status_changed), and is "—"
                  when the church started in the app after that day, or
                  its people were imported after it (a record imported
                  later can't say who was a member before). New members,
                  transfers, baptisms, dedications, weddings and funerals
                  come from the church register (church_register_entries,
                  done, not removed). First-time guests: a first-time
                  check-in (attendance.first_time) or a family the kids
                  desk welcomed (church_follow_ups, first-visit:), each
                  person once, in the year of their first visit.
    GROUPS ...... Active groups that aren't Sunday teams, and the share of
                  members in at least one. Groups are kept as they are
                  today, so a past year's are "—".
    SERVING ..... Serving hours (church_serving's own arithmetic: every yes
                  at a service that has started, leaders at their group's
                  gatherings, hours the office added) and how many served.
    GIVING ...... Paid gifts less refunds (invoices.is_gift, the year-end
                  statements' read and UTC year), givers, designated funds,
                  the year's giving budget (business_budgets, revenue), and
                  this year's ministry budgets (church_check_settings lines
                  against expenses by ministry). Only for finance logins:
                  the owner, admins and the church's accountant.
    CARE ........ Help given (church_help_given: amount, families helped,
                  by need) and requests received in Prayer & care
                  (ministry_care_requests, not the backfill). Counts and
                  sums only: no name, no story is read past a count.
                  People & care's, like the pages they come from.
    EVENTS ...... Events held (Services & Events occasions that aren't
                  services, dated in the year up to today), their RSVPs
                  (a yes) and paid sign-ups (church_event_registrations,
                  paid or confirmed places).

Who: the owner, admins and office logins (church_areas, Who sees what; while
that is off, every login sees the whole church, as before). Giving is the
owner's, the admins' and the accountant's: anyone else gets "kept with the
treasurer" and no giving number at all. Funerals follow the register's rule,
and Care the Help and Prayer & care pages' (church_help, private_care): the
pastors' and the care team's (People & care), never an Office login's, not
even as a total. A login without them gets "kept with the pastors and the
care team" and nothing is read for it.

  GET /church/reports/status?business_id=            {enabled, giving, deaths, care}
  GET /church/reports?business_id=&year=             the year's numbers, by section
  GET /church/reports/export?business_id=&year=      the same numbers as a CSV

The handlers are plain def: FastAPI runs them on its worker threads, never
on the event loop, and the sections read side by side on a small pool.
Switched by CHURCH_REPORTS: off | owner | on (owner until a Thursday). No
migration: every number comes from a table that already exists.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/reports", tags=["church"])

YEARS_BACK = 4                       # this year and the four before it
PAGE = 1000                          # the most rows one read returns (PostgREST's cap)
MAX_ROWS = 200_000                   # past this a read is refused, never cut short
CHUNK = 100                          # ids per `in.(…)` read, so a URL stays short
MEMBER_STATUSES = ("active", "vip")  # member_directory.MEMBER_STATUSES
KEEPS_ALL = ("owner", "admin")
OFFICE_AREA = "office"
CARE_AREA = "people_care"
CACHE_SECONDS = 120                  # the page, then its print and its CSV, read once
SECTIONS = ("people", "sunday", "groups", "serving", "giving", "care", "events")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")

# Where each number comes from, in the app's own words. The page shows these
# beside each number and the CSV carries them for a denomination's form.
SRC = {
    "attendance": "Sunday › Attendance & check-in: each service's headcount, or the people checked in by name "
                  "if that's more. Services nobody counted are left out.",
    "peak": "Sunday › Attendance & check-in: the largest single service in the year.",
    "kids": "Sunday › Kids check-in: children checked in at each service, averaged over the services that used it.",
    "members_now": "People › Members: records marked Member (active or VIP) today.",
    "members_then": "People › Members: today's list, rewound through the status changes the app logged.",
    "register": "Office › Church records: entries that happened in the year, not removed.",
    "new_members": "Office › Church records: membership entries marked joined or transferred in.",
    "guests": "Sunday › Attendance (first-time check-ins) and families the kids desk welcomed for the first "
              "time. Each person once, in the year of their first visit.",
    "groups": "People › Groups: active groups that aren't Sunday teams, as they are today.",
    "groups_share": "People › Groups and Members: members (active or VIP) in at least one active group, today.",
    "serving_hours": "Sunday › Serving: every yes at a service that has started, leaders at their group's "
                     "gatherings, and hours the office added.",
    "serving_people": "Sunday › Serving: people with serving hours in the year.",
    "giving": "Giving › Gifts: paid gifts less refunds, the same year the year-end statements use (UTC).",
    "givers": "Giving › Gifts: people with at least one paid gift in the year. Gifts with no giver on file "
              "are counted in the total, not here.",
    "budget": "Giving › Gifts › Budgets: the year's revenue budget, month by month.",
    "funds": "Giving › Gifts: paid gifts to a fund other than the general fund (tithes and offerings count as "
             "general).",
    "ministries": "Office › Check requests › Budgets by ministry: this year's lines against expenses with that "
                  "ministry's name.",
    "help": "People › Help requests: help recorded as given in the year (amounts only).",
    "families": "People › Help requests: each person helped once; help for someone not on the list counts once "
                "per request.",
    "care": "People › Prayer & care: requests received in the year, from forms and the member app.",
    "events": "Sunday › Services & Events: occasions that aren't services, dated in the year up to today.",
    "rsvps": "Sunday › Services & Events: yes answers on those events (free RSVPs).",
    "paid_signups": "Event sign-ups: places taken on those events, paid or confirmed.",
}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_REPORTS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _at(v: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _tz(biz_id: str) -> ZoneInfo:
    try:
        import outside_calendar
        return ZoneInfo(outside_calendar.business_timezone(biz_id) or "UTC")
    except (ZoneInfoNotFoundError, ValueError, Exception):
        return ZoneInfo("UTC")


def _chunks(ids: Iterable[Any], n: int = CHUNK) -> List[List[str]]:
    out = sorted({str(i) for i in ids if i})
    return [out[i:i + n] for i in range(0, len(out), n)]


def _cents(v: Any) -> int:
    try:
        return int(round(float(v or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _r(x: float) -> int:
    """Half up, the way people round (Python's round() would make 2.5 hours 2)."""
    return int(math.floor(x + 0.5))


def _dollars(cents: int) -> float:
    return round(cents / 100.0, 2)


def _short(d: date) -> str:
    return f"{MONTHS[d.month - 1][:3]} {d.day}"


def _long(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


# ─── Reads ────────────────────────────────────────────────────────────

class Unread(Exception):
    """A source that couldn't be read. Its numbers show "—" with this reason,
    and the rest of the report stands."""


# The report being put together on this thread: a read that fails marks it,
# so a report with a "—" from a blip is never kept for the next reader.
_TL = threading.local()


def _shaky(why: str) -> None:
    marks = getattr(_TL, "shaky", None)
    if marks is not None:
        marks.append(why)


def _rows(path: str, what: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        _shaky(what)
        raise Unread(what)
    return rows


def _all(path: str, order: str, what: str) -> List[Dict[str, Any]]:
    """Every row, a page at a time in a stable order: a read the server caps
    is never taken for the whole."""
    out: List[Dict[str, Any]] = []
    while True:
        rows = _rows(f"{path}&order={order}&limit={PAGE}&offset={len(out)}", what)
        out += rows
        if len(rows) < PAGE:
            return out
        if len(out) >= MAX_ROWS:
            raise Unread(f"{what} has more rows than one report can add up")


def _all_in(path: str, column: str, values: Iterable[Any], order: str, what: str) -> List[Dict[str, Any]]:
    """`path` with `column=in.(…)`, read in chunks, each chunk read whole."""
    out: List[Dict[str, Any]] = []
    for part in _chunks(values):
        out += _all(f"{path}&{column}=in.({','.join(_q(v) for v in part)})", order, what)
    return out


class _Shared:
    """Reads two sections need (the church's people, its occasions, the
    register), made once per report even when the sections run side by
    side. A failed read fails every section that asks for it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}
        self._vals: Dict[str, Tuple[bool, Any]] = {}

    def get(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            lk = self._locks.setdefault(key, threading.Lock())
        with lk:
            if key not in self._vals:
                try:
                    self._vals[key] = (True, fn())
                except Unread as e:
                    self._vals[key] = (False, e)
            ok, v = self._vals[key]
        if not ok:
            raise v
        return v


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings,created_at&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
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


def _finance(biz_id: str, uid: str, role: str) -> bool:
    """Giving: the owner, admins, or the church's active accountant
    (giving_records.require_finance's rule)."""
    if role in KEEPS_ALL:
        return True
    try:
        import business_collaborators_router as bcr
        return bool(bcr.is_active_accountant(biz_id, uid))
    except Exception:
        return False


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and what this login may see in its reports. 404 when the
    switch is closed to them, they have no login here, or it isn't a church;
    403 for a login whose areas leave the Office out."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Reports are for churches")
    uid = str(user.id)
    areas = _areas(biz_id, uid, role)
    if areas is not None and OFFICE_AREA not in areas:
        raise HTTPException(403, "Reports are kept by the office. An admin can add Office to your areas.")
    carer = areas is None or CARE_AREA in areas
    return {"biz": biz, "role": role, "uid": uid,
            "giving": _finance(biz_id, uid, role),
            # Funerals are the pastors' and the care team's (the register's
            # rule), and so are help given and Prayer & care, even as totals
            # (church_help and private_care keep them to People & care).
            "deaths": carer, "care": carer}


# ─── One number ───────────────────────────────────────────────────────

def stat(key: str, label: str, value: Any, unit: str, source: str, reason: Optional[str] = None,
         note: Optional[str] = None) -> Dict[str, Any]:
    """One number with where it came from. A number that can't be known is
    None with its reason; a reason always means None."""
    if value is None and not reason:
        reason = "This couldn't be worked out."
    return {"key": key, "label": label, "value": None if reason else value, "unit": unit,
            "source": source, "reason": reason, "note": note}


def _unknown(keys: Iterable[Tuple[str, str, str, str]], reason: str) -> List[Dict[str, Any]]:
    return [stat(k, label, None, unit, SRC[src], reason) for k, label, unit, src in keys]


# ─── The year ─────────────────────────────────────────────────────────

def _context(me: Dict[str, Any], year: Optional[Any]) -> Dict[str, Any]:
    biz = me["biz"]
    biz_id = str(biz["id"])
    tz = _tz(biz_id)
    now = _now()
    today = now.astimezone(tz).date()
    if year in (None, ""):
        y = today.year
    else:
        try:
            y = int(str(year))
        except ValueError:
            raise HTTPException(400, f"Pick a year from {today.year - YEARS_BACK} to {today.year}.")
    if not today.year - YEARS_BACK <= y <= today.year:
        raise HTTPException(400, f"Pick a year from {today.year - YEARS_BACK} to {today.year}.")
    current = y == today.year
    start = datetime(y, 1, 1, tzinfo=tz)
    end = datetime(y + 1, 1, 1, tzinfo=tz)
    return {
        "me": me, "biz": biz, "biz_id": biz_id, "b": _q(biz_id), "tz": tz, "now": now, "today": today,
        "year": y, "current": current, "through": today if current else date(y, 12, 31),
        "start": start, "end": end, "until": min(end, now), "shared": _Shared(),
    }


def _month_slots(ctx: Dict[str, Any]) -> List[int]:
    """The months that have begun (all twelve for a past year)."""
    return list(range(1, (ctx["today"].month if ctx["current"] else 12) + 1))


def _series(ctx: Dict[str, Any], by_month: Dict[int, Any], empty: Any = 0) -> List[Optional[Any]]:
    """Twelve values; a month that hasn't come yet is None."""
    begun = set(_month_slots(ctx))
    return [by_month.get(m, empty) if m in begun else None for m in range(1, 13)]


# ─── Shared reads ─────────────────────────────────────────────────────

def _contacts(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ctx["shared"].get("contacts", lambda: _all(
        f"/contacts?business_id=eq.{ctx['b']}&select=id,status,created_at", "id", "Members"))


def occasion_kind(data: Dict[str, Any], day: date, noun: Optional[str]) -> str:
    """A service or an event, the app's rule (churchCalendar.rosterKind): its
    own type when it has one; else its room's noun ("services"); else a
    Sunday occasion is the service and the rest are events."""
    t = str((data or {}).get("type") or "").strip().lower()
    if t:
        return "service" if t == "service" else "event"
    n = _plain(noun)
    if n:
        return "service" if re.search(r"\bservices?\b", n, re.IGNORECASE) else "event"
    return "service" if day.weekday() == 6 else "event"


def _occasions(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every dated occasion in the church's Services & Events rooms, as
    {id, day, kind, title, rsvps}."""
    def read() -> List[Dict[str, Any]]:
        from events_rsvp_router import _parse_day, attending_count, read_signups, resolve_fields
        mods = _rows(f"/custom_modules?business_id=eq.{ctx['b']}&archetype=eq.event_roster&is_active=eq.true"
                     "&select=id,name,archetype_params&order=created_at.asc&limit=50", "Services & Events")
        out: List[Dict[str, Any]] = []
        for m in mods:
            f = resolve_fields(m.get("archetype_params"))
            for e in _all(f"/module_entries?business_id=eq.{ctx['b']}&module_id=eq.{_q(m['id'])}&status=eq.active"
                          "&select=id,data", "id", "Services & Events"):
                data = e.get("data") if isinstance(e.get("data"), dict) else {}
                day = _parse_day(data.get(f["date_field"]))
                if not day:
                    continue
                kind = occasion_kind(data, day, f.get("occasion_noun"))
                out.append({"id": str(e["id"]), "day": day, "kind": kind,
                            "title": _plain(data.get(f["title_field"]))[:120] or ("A service" if kind == "service" else "An event"),
                            "rsvps": attending_count(read_signups(data, f["signups_field"]))})
        return out
    return ctx["shared"].get("occasions", read)


def _in_year(ctx: Dict[str, Any], occ: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    lo = date(ctx["year"], 1, 1)
    return [o for o in occ if o["kind"] == kind and lo <= o["day"] <= ctx["through"]]


def _register(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    y = ctx["year"]
    return ctx["shared"].get("register", lambda: _all(
        f"/church_register_entries?business_id=eq.{ctx['b']}&removed_at=is.null&status=eq.done"
        f"&event_on=gte.{y}-01-01&event_on=lte.{y}-12-31&select=kind,membership", "id",
        "The church register isn't set up yet, or"))


def _why(e: Unread) -> str:
    """A failed read, said plainly."""
    s = str(e)
    if s.endswith(", or"):
        return f"{s} couldn't be read just now."
    if "more rows" in s:
        return f"{s}."
    return f"{s} couldn't be read just now."


# ─── Sunday ───────────────────────────────────────────────────────────

def sunday(ctx: Dict[str, Any]) -> Dict[str, Any]:
    keys = (("attendance_avg", "Average attendance at services", "people", "attendance"),
            ("services_counted", "Services counted", "count", "attendance"),
            ("attendance_peak", "Largest service", "people", "peak"))
    kid = ("kids_avg", "Kids checked in, average per service", "people", "kids")
    try:
        svc = _in_year(ctx, _occasions(ctx), "service")
        ids = [o["id"] for o in svc]
        named = Counter(str(r["entry_id"]) for r in _all_in(
            f"/attendance?business_id=eq.{ctx['b']}&select=entry_id", "entry_id", ids, "id", "Attendance"))
        heads: Counter = Counter()
        for r in _all_in(f"/attendance_headcounts?business_id=eq.{ctx['b']}&select=entry_id,count",
                         "entry_id", ids, "id", "Attendance"):
            heads[str(r["entry_id"])] += max(0, int(r.get("count") or 0))
    except Unread as e:
        why = _why(e)
        return {"stats": _unknown(keys + (kid,), why), "months": _series(ctx, {}, None), "counts": [], "reason": why}

    total = {o["id"]: max(named[o["id"]], heads[o["id"]]) for o in svc}
    counted = [o for o in svc if total[o["id"]] > 0]
    by_month: Dict[int, List[int]] = {}
    for o in counted:
        by_month.setdefault(o["day"].month, []).append(total[o["id"]])
    months = _series(ctx, {m: {"avg": _r(sum(v) / len(v)), "services": len(v)} for m, v in by_month.items()},
                     {"avg": None, "services": 0})
    y = ctx["year"]
    none = "No service has a count yet this year." if ctx["current"] else f"No service has a count in {y}."
    if counted:
        avg = _r(sum(total[o["id"]] for o in counted) / len(counted))
        peak = max(counted, key=lambda o: (total[o["id"]], -o["day"].toordinal()))
        stats = [stat("attendance_avg", "Average attendance at services", avg, "people", SRC["attendance"]),
                 stat("services_counted", "Services counted", len(counted), "count", SRC["attendance"]),
                 stat("attendance_peak", "Largest service", total[peak["id"]], "people", SRC["peak"],
                      note=f"{peak['title']}, {_short(peak['day'])}")]
    else:
        stats = [stat("attendance_avg", "Average attendance at services", None, "people", SRC["attendance"], none),
                 stat("services_counted", "Services counted", 0, "count", SRC["attendance"]),
                 stat("attendance_peak", "Largest service", None, "people", SRC["peak"], none)]

    try:
        kids = Counter(str(r["entry_id"]) for r in _all_in(
            f"/child_checkins?business_id=eq.{ctx['b']}&select=entry_id", "entry_id", ids, "id", "Kids check-in"))
        used = [kids[o["id"]] for o in svc if kids[o["id"]] > 0]
        stats.append(stat(*kid[:2], _r(sum(used) / len(used)), "people", SRC["kids"]) if used else
                     stat(*kid[:2], None, "people", SRC["kids"],
                          "Kids check-in wasn't used at a service " + ("yet this year." if ctx["current"] else f"in {y}.")))
    except Unread as e:
        stats.append(stat(*kid[:2], None, "people", SRC["kids"], _why(e)))
    # Each service's count, oldest first: what the averages are made of.
    counts = [{"day": o["day"].isoformat(), "title": o["title"], "total": total[o["id"]]}
              for o in sorted(counted, key=lambda o: o["day"])]
    return {"stats": stats, "months": months, "counts": counts, "reason": None if counted else none}


# ─── People ───────────────────────────────────────────────────────────

def _members_on(ctx: Dict[str, Any], when: datetime) -> Tuple[Optional[int], Optional[str]]:
    """How many were members at the instant `when`: today's list rewound
    through the status changes the app logged. None, and why, when the
    records can't reach back that far."""
    biz = ctx["biz"]
    began = _at(biz.get("created_at"))
    if began and began > when:
        return None, (f"{_plain(biz.get('name')) or 'The church'} started in the app on "
                      f"{_long(began.astimezone(ctx['tz']).date())}, so who was a member before then isn't on record.")
    late = _rows(f"/contacts?business_id=eq.{ctx['b']}&metadata->>imported_at=gt.{_q(_iso(when))}"
                 "&select=imported_at:metadata->>imported_at,imported_from:metadata->>imported_from"
                 "&order=metadata->>imported_at.asc&limit=1", "Members")
    if late:
        frm = _plain(late[0].get("imported_from")) or "an import"
        at = _at(late[0].get("imported_at"))
        day = f" on {_long(at.astimezone(ctx['tz']).date())}" if at else ""
        return None, f"Your people came over from {frm}{day}, so who was a member before then isn't on record."
    first: Dict[str, Any] = {}
    for ev in _all(f"/events?business_id=eq.{ctx['b']}&event_type=eq.contact_status_changed"
                   f"&created_at=gte.{_q(_iso(when))}&select=contact_id,data,created_at", "created_at.asc,id.asc",
                   "Members"):
        cid = str(ev.get("contact_id") or "")
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if cid and cid not in first and "from" in data:
            first[cid] = data.get("from")
    n = 0
    for c in _contacts(ctx):
        made = _at(c.get("created_at"))
        if made is None or made >= when:
            continue
        was = first.get(str(c["id"]), c.get("status"))
        if str(was or "").strip().lower() in MEMBER_STATUSES:
            n += 1
    return n, None


def _guests(ctx: Dict[str, Any]) -> Dict[int, int]:
    """First-time guests by month: each person once, in the month of their
    first visit, if that falls in the year."""
    end = _q(_iso(ctx["end"]))
    first: Dict[str, datetime] = {}

    def seen(key: str, at: Optional[datetime]) -> None:
        if key and at and (key not in first or at < first[key]):
            first[key] = at
    for r in _all(f"/attendance?business_id=eq.{ctx['b']}&first_time=is.true&checked_in_at=lt.{end}"
                  "&select=contact_id,name,checked_in_at", "id", "Attendance"):
        key = f"c:{r['contact_id']}" if r.get("contact_id") else "n:" + " ".join(str(r.get("name") or "").lower().split())
        seen("" if key == "n:" else key, _at(r.get("checked_in_at")))
    for r in _all(f"/church_follow_ups?business_id=eq.{ctx['b']}&source_event=like.{_q('first-visit:*')}"
                  f"&created_at=lt.{end}&select=contact_id,created_at", "id", "Follow-up"):
        if r.get("contact_id"):
            seen(f"c:{r['contact_id']}", _at(r.get("created_at")))
    # Someone checked in by name alone and, another time, from their record
    # is one guest: a name-only visit joins the record with that name (the
    # earlier visit counts). Names are read to match, never shown.
    named = {k[2:]: k for k in first if k.startswith("n:")}
    if named:
        ids = [k[2:] for k in first if k.startswith("c:")]
        for c in _all_in(f"/contacts?business_id=eq.{ctx['b']}&select=id,name", "id", ids, "id", "Attendance"):
            nk = named.get(" ".join(str(c.get("name") or "").lower().split()))
            if nk and nk in first:
                seen(f"c:{c['id']}", first.pop(nk))
    out: Dict[int, int] = {}
    for at in first.values():
        if ctx["start"] <= at < ctx["end"]:
            m = at.astimezone(ctx["tz"]).month
            out[m] = out.get(m, 0) + 1
    return out


def people(ctx: Dict[str, Any]) -> Dict[str, Any]:
    y = ctx["year"]
    stats: List[Dict[str, Any]] = []
    # Members at the start of the year, and at its end (today, this year).
    start_label = f"Members on January 1, {y}"
    end_label = "Members today" if ctx["current"] else f"Members on December 31, {y}"
    try:
        n, why = _members_on(ctx, ctx["start"])
        stats.append(stat("members_start", start_label, n, "people", SRC["members_then"], why))
    except Unread as e:
        stats.append(stat("members_start", start_label, None, "people", SRC["members_then"], _why(e)))
    try:
        if ctx["current"]:
            n = sum(1 for c in _contacts(ctx) if str(c.get("status") or "").strip().lower() in MEMBER_STATUSES)
            stats.append(stat("members_end", end_label, n, "people", SRC["members_now"]))
        else:
            n, why = _members_on(ctx, ctx["end"])
            stats.append(stat("members_end", end_label, n, "people", SRC["members_then"], why))
    except Unread as e:
        stats.append(stat("members_end", end_label, None, "people", SRC["members_now"], _why(e)))

    # The register: what happened in the year.
    reg = (("new_members", "New members", "people", "new_members"),
           ("transfers_in", "Transferred in", "people", "register"),
           ("transfers_out", "Transferred out", "people", "register"),
           ("baptisms", "Baptisms", "people", "register"),
           ("dedications", "Baby dedications", "people", "register"),
           ("weddings", "Weddings", "count", "register"),
           ("deaths", "Funerals", "count", "register"))
    try:
        rows = _register(ctx)
        kinds = Counter(r.get("kind") for r in rows)
        moves = Counter(r.get("membership") for r in rows if r.get("kind") == "membership")
        vals = {"new_members": moves["joined"] + moves["transferred_in"], "transfers_in": moves["transferred_in"],
                "transfers_out": moves["transferred_out"], "baptisms": kinds["baptism"],
                "dedications": kinds["dedication"], "weddings": kinds["wedding"], "deaths": kinds["funeral"]}
        for key, label, unit, src in reg:
            if key == "deaths" and not ctx["me"]["deaths"]:
                stats.append(stat(key, label, None, unit, SRC[src], "Kept with the pastors and the care team."))
            else:
                stats.append(stat(key, label, vals[key], unit, SRC[src]))
    except Unread as e:
        why = _why(e)
        stats += [stat(k, label, None, unit, SRC[src],
                       why if k != "deaths" or ctx["me"]["deaths"] else "Kept with the pastors and the care team.")
                  for k, label, unit, src in reg]

    guests: List[Optional[int]] = _series(ctx, {}, None)
    try:
        g = _guests(ctx)
        stats.append(stat("guests", "First-time guests", sum(g.values()), "people", SRC["guests"]))
        guests = _series(ctx, g)
    except Unread as e:
        stats.append(stat("guests", "First-time guests", None, "people", SRC["guests"], _why(e)))
    return {"stats": stats, "guests_by_month": guests}


# ─── Groups ───────────────────────────────────────────────────────────

GROUP_KINDS = {"small_group": "Small groups", "class": "Classes", "ministry": "Ministries"}


def groups(ctx: Dict[str, Any]) -> Dict[str, Any]:
    keys = (("groups", "Groups meeting", "count", "groups"),
            ("in_groups", "People in a group", "people", "groups_share"),
            ("groups_share", "Members in a group", "pct", "groups_share"))
    if not ctx["current"]:
        return {"stats": _unknown(keys, "Groups are kept as they are today, so a past year's can't be read back. "
                                        "Pick this year to see them."), "by_kind": []}
    try:
        gs = _all(f"/groups?business_id=eq.{ctx['b']}&active=eq.true&kind=neq.team&select=id,kind", "id", "Groups")
        inside = _all_in(f"/group_members?business_id=eq.{ctx['b']}&select=contact_id,group_id", "group_id",
                         [g["id"] for g in gs], "group_id,contact_id", "Groups")
        members = {str(c["id"]) for c in _contacts(ctx) if str(c.get("status") or "").strip().lower() in MEMBER_STATUSES}
    except Unread as e:
        return {"stats": _unknown(keys, _why(e)), "by_kind": []}
    people_in = {str(r["contact_id"]) for r in inside if r.get("contact_id")}
    kinds = Counter(str(g.get("kind") or "small_group") for g in gs)
    stats = [stat("groups", "Groups meeting", len(gs), "count", SRC["groups"], note="today"),
             stat("in_groups", "People in a group", len(people_in), "people", SRC["groups_share"], note="today")]
    if members:
        stats.append(stat("groups_share", "Members in a group", _r(100 * len(members & people_in) / len(members)),
                          "pct", SRC["groups_share"], note=f"{len(members & people_in)} of {len(members)} members, today"))
    else:
        stats.append(stat("groups_share", "Members in a group", None, "pct", SRC["groups_share"],
                          "No one is marked a member yet, so there's no share to give."))
    by_kind = [{"kind": k, "label": GROUP_KINDS.get(k, "Groups"), "count": kinds[k]}
               for k in ("small_group", "class", "ministry") if kinds[k]]
    return {"stats": stats, "by_kind": by_kind}


# ─── Serving ──────────────────────────────────────────────────────────

def serving(ctx: Dict[str, Any]) -> Dict[str, Any]:
    keys = (("serving_hours", "Hours served", "hours", "serving_hours"),
            ("serving_people", "People serving", "people", "serving_people"))
    import church_serving as cs
    biz_id, y = ctx["biz_id"], ctx["year"]
    try:
        zone = cs._zone(biz_id)
        settings = cs._settings(ctx["biz"])
        lo, hi = cs._year_window(zone, y, ctx["now"])
        sundays, _ = cs._sunday_spans(biz_id, zone, lo, hi, settings)
        gathered, _ = cs._group_credits(biz_id, lo.date(), hi.date(), settings)
        extra = cs._extra_credits(cs._extra_rows(biz_id), y)
        credits = [c for c in sundays + gathered + extra if c.get("minutes", 0) > 0]
        per: Dict[str, int] = {}
        for c in credits:
            per[str(c["contact_id"])] = per.get(str(c["contact_id"]), 0) + int(c["minutes"])
        # Serving's own totals: people still on the list (a record that's gone
        # takes its hours with it, as on the Serving page).
        names = cs._people(biz_id, per) if per else {}
    except HTTPException:
        _shaky("Serving")
        return {"stats": _unknown(keys, "Serving couldn't be read just now."), "months": _series(ctx, {}, None)}
    kept = {cid for cid, mins in per.items() if mins > 0 and cid in names}
    minutes = sum(per[c] for c in kept)
    by_month: Dict[int, int] = {}
    for c in credits:
        d = _day(c.get("day"))
        if d and str(c["contact_id"]) in kept:
            by_month[d.month] = by_month.get(d.month, 0) + int(c["minutes"])
    hours = _r(minutes / 60)
    return {"stats": [stat("serving_hours", "Hours served", hours, "hours", SRC["serving_hours"]),
                      stat("serving_people", "People serving", len(kept), "people", SRC["serving_people"])],
            "months": _series(ctx, {m: _r(v / 60) for m, v in by_month.items()})}


# ─── Giving ───────────────────────────────────────────────────────────

def giving(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not ctx["me"]["giving"]:
        return {"kept": True, "reason": "Kept with the treasurer."}
    y = ctx["year"]
    keys = (("giving_total", "Total given", "usd", "giving"), ("givers", "Givers", "people", "givers"),
            ("gifts", "Gifts", "count", "giving"))
    try:
        gifts = _all(f"/invoices?business_id=eq.{ctx['b']}&is_gift=eq.true&status=eq.paid"
                     f"&paid_at=gte.{y}-01-01T00:00:00Z&paid_at=lt.{y + 1}-01-01T00:00:00Z"
                     "&select=id,total,refund_amount_cents,gift_fund,category,contact_id,paid_at", "id", "Giving")
    except Unread as e:
        why = _why(e)
        return {"kept": False, "stats": _unknown(keys, why), "months": _series(ctx, {}, None), "funds": [],
                "ministries": None, "ministries_reason": why}
    from giving_router import fund_label, is_designated
    total = 0
    givers: Set[str] = set()
    count = 0
    unattributed = 0
    by_month: Dict[int, int] = {}
    funds: Dict[str, Dict[str, Any]] = {}
    for g in gifts:
        net = _cents(g.get("total")) - max(0, int(round(float(g.get("refund_amount_cents") or 0))))
        if net <= 0:
            continue
        count += 1
        total += net
        if g.get("contact_id"):
            givers.add(str(g["contact_id"]))
        else:
            unattributed += net
        at = _at(g.get("paid_at"))
        if at:
            m = at.astimezone(timezone.utc).month
            by_month[m] = by_month.get(m, 0) + net
        name = _plain(g.get("gift_fund") or g.get("category")) or "General"
        label = fund_label(name)
        # "Building" and "Building Fund" are one fund, as the receipts say it.
        f = funds.setdefault(label.lower(), {"name": label, "cents": 0, "designated": is_designated(name)})
        f["cents"] += net
    stats = [stat("giving_total", "Total given", _dollars(total), "usd", SRC["giving"]),
             stat("givers", "Givers", len(givers), "people", SRC["givers"],
                  note=f"plus ${_dollars(unattributed):,.2f} given with no giver on file" if unattributed else None),
             stat("gifts", "Gifts", count, "count", SRC["giving"])]
    designated = sorted((f for f in funds.values() if f["designated"]), key=lambda f: (-f["cents"], f["name"].lower()))
    stats.append(stat("designated_total", "Given to designated funds", _dollars(sum(f["cents"] for f in designated)),
                      "usd", SRC["funds"]))
    for f in designated:
        stats.append(stat(f"fund:{f['name']}", f"Designated · {f['name']}", _dollars(f["cents"]), "usd", SRC["funds"]))

    # The giving budget: the books' revenue budget for the year's months.
    budget_by: Dict[int, int] = {}
    budget_reason: Optional[str] = None
    try:
        for r in _rows(f"/business_budgets?business_id=eq.{ctx['b']}&year=eq.{y}&category=eq.revenue"
                       "&select=month,amount&limit=100", "The giving budget"):
            m = int(r.get("month") or 0)
            if 1 <= m <= 12:
                budget_by[m] = budget_by.get(m, 0) + _cents(r.get("amount"))
    except Unread as e:
        budget_reason = _why(e)
    upto = ctx["today"].month if ctx["current"] else 12
    budget_year = sum(budget_by.values())
    budget_to_date = sum(v for m, v in budget_by.items() if m <= upto)
    if budget_reason is None and budget_year <= 0:
        budget_reason = f"No giving budget is set for {y} (Giving › Gifts › Budgets)."
    month_word = MONTHS[upto - 1]
    if budget_reason:
        stats += [stat("giving_budget", f"Giving budget for {y}", None, "usd", SRC["budget"], budget_reason),
                  stat("giving_vs_budget", "Of the giving budget", None, "pct", SRC["budget"], budget_reason)]
    else:
        stats.append(stat("giving_budget", f"Giving budget for {y}", _dollars(budget_year), "usd", SRC["budget"]))
        if budget_to_date > 0:
            stats.append(stat("giving_vs_budget", "Of the giving budget", _r(100 * total / budget_to_date), "pct",
                              SRC["budget"], note=(f"through {month_word}" if ctx["current"] and upto < 12 else None)))
        else:
            stats.append(stat("giving_vs_budget", "Of the giving budget", None, "pct", SRC["budget"],
                              f"The budget has nothing set through {month_word} yet."))
    months = _series(ctx, {m: {"cents": by_month.get(m, 0), "budget_cents": budget_by.get(m)} for m in range(1, 13)},
                     {"cents": 0, "budget_cents": None})

    ministries, why = _ministries(ctx)
    return {"kept": False, "stats": stats, "months": months,
            "funds": [{"name": f["name"], "usd": _dollars(f["cents"]), "designated": f["designated"]}
                      for f in sorted(funds.values(), key=lambda f: (-f["cents"], f["name"].lower()))],
            "ministries": ministries, "ministries_reason": why}


def _ministries(ctx: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """This year's ministry budgets (Check requests) against what each has
    spent. Kept for this year only: a past year's lines aren't on file."""
    if not ctx["current"]:
        return None, "Ministry budgets are kept for this year only."
    try:
        rows = _rows(f"/church_check_settings?business_id=eq.{ctx['b']}&select=lines&limit=1",
                     "Budgets by ministry aren't set up yet, or")
    except Unread as e:
        return None, _why(e)
    import church_checks
    lines = [x for x in church_checks._clean_lines((rows[0] if rows else {}).get("lines")) if x["budget_cents"] > 0]
    if not lines:
        return None, "No ministry has a budget yet (Office › Check requests › Budgets by ministry)."
    y = ctx["year"]
    spent: Dict[str, int] = {}
    try:
        for e in _all(f"/business_expenses?business_id=eq.{ctx['b']}&date=gte.{y}-01-01&date=lte.{y}-12-31"
                      "&select=amount,subcategory", "id", "Expenses"):
            key = _plain(e.get("subcategory")).lower()
            if key:
                spent[key] = spent.get(key, 0) + _cents(e.get("amount"))
    except Unread as e:
        return None, _why(e)
    return [{"name": x["name"], "budget_usd": _dollars(x["budget_cents"]),
             "spent_usd": _dollars(spent.get(x["name"].lower(), 0))} for x in lines], None


# ─── Care ─────────────────────────────────────────────────────────────

NEED_WORDS = {"food": "Food", "bill": "Bills", "ride": "Rides", "other": "Other help"}


def care(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Counts and sums only: amounts, needs and days are read, never a name
    or a story, and who was helped is only ever counted. People & care's
    alone (the pastors and the care team, the owner and admins): an Office
    login gets "kept", and nothing is read for it."""
    if not ctx["me"].get("care"):
        return {"kept": True, "reason": "Kept with the pastors and the care team."}
    y = ctx["year"]
    stats: List[Dict[str, Any]] = []
    by_need: List[Dict[str, Any]] = []
    help_keys = (("help_given", "Help given", "usd", "help"), ("help_times", "Times help was given", "count", "help"),
                 ("families_helped", "Families helped", "people", "families"))
    try:
        given = _all(f"/church_help_given?business_id=eq.{ctx['b']}&given_on=gte.{y}-01-01&given_on=lte.{y}-12-31"
                     "&select=request_id,amount_cents", "id", "Help requests aren't set up yet, or")
        asked = {str(r["id"]): r for r in _all_in(
            f"/church_help_requests?business_id=eq.{ctx['b']}&select=id,contact_id,need", "id",
            {g["request_id"] for g in given}, "id", "Help requests aren't set up yet, or")}
        cents = sum(max(0, int(g.get("amount_cents") or 0)) for g in given)
        families = {f"c:{asked[k]['contact_id']}" if asked.get(k, {}).get("contact_id") else f"r:{k}"
                    for k in {str(g["request_id"]) for g in given}}
        needs: Dict[str, Dict[str, int]] = {}
        for g in given:
            need = str((asked.get(str(g["request_id"])) or {}).get("need") or "other")
            n = needs.setdefault(need if need in NEED_WORDS else "other", {"cents": 0, "times": 0})
            n["cents"] += max(0, int(g.get("amount_cents") or 0))
            n["times"] += 1
        stats += [stat("help_given", "Help given", _dollars(cents), "usd", SRC["help"]),
                  stat("help_times", "Times help was given", len(given), "count", SRC["help"]),
                  stat("families_helped", "Families helped", len(families), "people", SRC["families"])]
        by_need = [{"need": k, "label": NEED_WORDS[k], "usd": _dollars(v["cents"]), "times": v["times"]}
                   for k, v in sorted(needs.items(), key=lambda kv: (-kv[1]["cents"], -kv[1]["times"], kv[0]))]
    except Unread as e:
        stats += _unknown(help_keys, _why(e))

    months: List[Optional[int]] = _series(ctx, {}, None)
    care_keys = (("care_requests", "Prayer & care requests received", "count", "care"),)
    try:
        rows = _all(f"/ministry_care_requests?business_id=eq.{ctx['b']}&legacy_source=is.null"
                    f"&created_at=gte.{_q(_iso(ctx['start']))}&created_at=lt.{_q(_iso(ctx['end']))}"
                    "&select=created_at", "id", "Prayer & care")
        per: Dict[int, int] = {}
        for r in rows:
            at = _at(r.get("created_at"))
            if at:
                m = at.astimezone(ctx["tz"]).month
                per[m] = per.get(m, 0) + 1
        stats.append(stat("care_requests", "Prayer & care requests received", len(rows), "count", SRC["care"]))
        months = _series(ctx, per)
    except Unread as e:
        stats += _unknown(care_keys, _why(e))
    return {"stats": stats, "by_need": by_need, "months": months}


# ─── Events ───────────────────────────────────────────────────────────

def events(ctx: Dict[str, Any]) -> Dict[str, Any]:
    keys = (("events_held", "Events held", "count", "events"), ("rsvps", "RSVPs", "people", "rsvps"),
            ("paid_signups", "Paid sign-ups", "people", "paid_signups"),
            ("signups", "Sign-ups in all", "people", "rsvps"))
    try:
        ev = _in_year(ctx, _occasions(ctx), "event")
    except Unread as e:
        return {"stats": _unknown(keys, _why(e)), "months": _series(ctx, {}, None)}
    rsvps = sum(o["rsvps"] for o in ev)
    per: Dict[int, int] = {}
    for o in ev:
        per[o["day"].month] = per.get(o["day"].month, 0) + 1
    stats = [stat("events_held", "Events held", len(ev), "count", SRC["events"]),
             stat("rsvps", "RSVPs", rsvps, "people", SRC["rsvps"])]
    try:
        paid = sum(max(0, int(r.get("seats") or 0)) for r in _all_in(
            f"/church_event_registrations?business_id=eq.{ctx['b']}&status=in.(paid,confirmed)&select=entry_id,seats",
            "entry_id", [o["id"] for o in ev], "id", "Event sign-ups aren't set up yet, or"))
        stats += [stat("paid_signups", "Paid sign-ups", paid, "people", SRC["paid_signups"]),
                  stat("signups", "Sign-ups in all", rsvps + paid, "people",
                       "Free RSVPs and paid sign-ups on the year's events, together.")]
    except Unread as e:
        why = _why(e)
        stats += [stat("paid_signups", "Paid sign-ups", None, "people", SRC["paid_signups"], why),
                  stat("signups", "Sign-ups in all", None, "people",
                       "Free RSVPs and paid sign-ups on the year's events, together.",
                       "Paid sign-ups couldn't be counted, so the whole isn't known. The RSVPs are above.")]
    return {"stats": stats, "months": _series(ctx, per)}


# ─── The report ───────────────────────────────────────────────────────

BUILDERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "people": people, "sunday": sunday, "groups": groups, "serving": serving, "giving": giving,
    "care": care, "events": events,
}
TITLES = {"people": "People", "sunday": "Sunday", "groups": "Groups", "serving": "Serving",
          "giving": "Giving", "care": "Care", "events": "Events"}

_CACHE: Dict[Tuple[str, int, bool, bool, bool], Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def _section(name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """One section; anything unexpected is that section's "—", never the
    whole report's 500. A read that fails on its thread marks the report."""
    _TL.shaky = ctx["shaky"]
    try:
        return BUILDERS[name](ctx)
    except Exception as e:   # noqa: BLE001: a report stands without one section
        print(f"[church_reports] {name} failed for {ctx['biz_id']}: {type(e).__name__}: {e}")
        logger.warning("church_reports %s failed: %s", name, e)
        _shaky(name)
        return {"stats": [], "failed": True, "reason": f"{TITLES[name]} couldn't be put together just now."}
    finally:
        _TL.shaky = None


def build(me: Dict[str, Any], year: Optional[Any] = None) -> Dict[str, Any]:
    """The year's report. Kept CACHE_SECONDS for the same church, year and
    view, but only when every read answered: a "—" from a blip is never
    handed to the next reader (a source not set up yet is read each time)."""
    ctx = _context(me, year)
    ctx["shaky"] = []
    key = (ctx["biz_id"], ctx["year"], bool(me["giving"]), bool(me["deaths"]), bool(me.get("care")))
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    with ThreadPoolExecutor(max_workers=len(SECTIONS), thread_name_prefix="church-reports") as pool:
        futures = {name: pool.submit(_section, name, ctx) for name in SECTIONS}
        sections = {name: f.result() for name, f in futures.items()}
    import church_register
    y = ctx["year"]
    out = {
        "year": y, "years": list(range(ctx["today"].year, ctx["today"].year - YEARS_BACK - 1, -1)),
        "today": ctx["today"].isoformat(), "through": ctx["through"].isoformat(), "current": ctx["current"],
        "church": church_register.church_look(ctx["biz"]),
        "me": {"giving": bool(me["giving"]), "deaths": bool(me["deaths"]), "care": bool(me.get("care"))},
        "sections": sections,
    }
    if not ctx["shaky"]:
        with _CACHE_LOCK:
            if len(_CACHE) > 64:
                _CACHE.clear()
            _CACHE[key] = (time.monotonic(), out)
    return out


# ─── The CSV ──────────────────────────────────────────────────────────

UNIT_WORDS = {"people": "people", "count": "count", "usd": "US dollars", "pct": "percent", "hours": "hours"}


def _cell(v: Any) -> str:
    """Text a spreadsheet won't run: a cell that starts like a formula is
    set as text."""
    s = str(v if v is not None else "")
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _value(s: Dict[str, Any]) -> str:
    v = s.get("value")
    if v is None:
        return "—"
    if s.get("unit") == "usd":
        return f"{float(v):.2f}"
    return str(v)


def csv_of(report: Dict[str, Any]) -> str:
    """Every number with its source, one row each, for a denomination's
    form. A number that isn't known is "—" with the reason in Note."""
    church = report["church"]["name"]
    y = report["year"]
    through = report["through"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Church", "Year", "Through", "Section", "Number", "Value", "Unit", "Note", "Source"])

    def row(section: str, s: Dict[str, Any]) -> None:
        note = s.get("reason") or s.get("note") or ""
        w.writerow([_cell(church), y, through, section, _cell(s["label"]), _value(s),
                    UNIT_WORDS.get(s["unit"], s["unit"]), _cell(note), _cell(s["source"])])
    for name in SECTIONS:
        sec = report["sections"].get(name) or {}
        title = TITLES[name]
        if sec.get("kept"):
            w.writerow([_cell(church), y, through, title, title, "—", "", _cell(sec.get("reason") or ""), ""])
            continue
        if sec.get("failed"):
            w.writerow([_cell(church), y, through, title, title, "—", "", _cell(sec.get("reason") or ""), ""])
            continue
        for s in sec.get("stats") or []:
            row(title, s)
        if name == "sunday":
            for i, m in enumerate(sec.get("months") or []):
                if m is None:
                    continue
                row(title, stat(f"attendance_{i + 1}", f"Average attendance, {MONTHS[i]}", m.get("avg"), "people",
                                SRC["attendance"], None if m.get("avg") is not None else "No service was counted."))
    return buf.getvalue()


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def reports_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows Reports: the app asks once, so its
    menu offers the page only where it opens. Quietly false for a closed
    switch, a business that isn't a church, or a login outside the Office."""
    off = {"enabled": False, "giving": False, "deaths": False, "care": False}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == "Reports are for churches":
            return off
        raise
    return {"enabled": True, "giving": me["giving"], "deaths": me["deaths"], "care": me["care"]}


@router.get("")
def reports_read(business_id: str, year: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    return build(_access(business_id, user), year)


@router.get("/export")
def reports_export(business_id: str, year: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    report = build(_access(business_id, user), year)
    slug = re.sub(r"[^a-z0-9]+", "-", report["church"]["name"].lower()).strip("-") or "church"
    return Response(content="﻿" + csv_of(report), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{slug}-{report["year"]}-numbers.csv"',
                             "Cache-Control": "no-store"})
