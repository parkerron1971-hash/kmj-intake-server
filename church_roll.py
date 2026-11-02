"""church_roll.py — the roll: a church's People page, read in one go.

Kevin, 2026-11-01, on the Members Roll Redesign canvas
(BF38H75nNDSaxEC1ZJFFoe): "the design works ... the design is good", then
"build this". Lane: Build, under the Build item "Love City leaves Subsplash
(M-1)" (the members roll is the Subsplash People screen's job).

The page reads like a church, not a contact list, and everything it shows
already lives somewhere; this module only gathers it, read-only:

    PEOPLE ...... contacts. active = Member, lead = Guest, vip = Leader,
                  inactive / churned = Inactive. Anyone holding an active
                  leader role (church_leader_roles) or leading a group reads
                  as a Leader too
    SUNDAYS ..... the last 8 RECORDED Sundays, counted the way the Monday
                  shepherding sweep counts them (church_shepherd_signals: a
                  day on the church's check-in weekday with any attendance at
                  all, on the church's clock; a class night never is one).
                  Each person gets one letter per Sunday: P in person, O
                  online (online counts), M missed, N before their first
                  visit (an attendance row marked first_time, else the day
                  their record was made, unless it came over in an import)
    FAMILIES .... households (+ household_adults, + children with their own
                  record), named as the office named them, with the family's
                  shepherd (church_shepherds)
    DRIFTING .... church_shepherd_signals.drift on the FAMILY's Sundays (a
                  family attends when any of them does), or a person's own
                  when they have no family on file: missed the 3 newest
                  recorded Sundays after coming to 2 of the 6 before
    GROUPS ...... group_members of active groups; a team (kind team) and the
                  positions someone is trained for in Who serves when
                  (serve_positions + serve_trained) are their SERVING
    NEW GUESTS .. church_reads.first_time_guests: a first visit in the last
                  30 days that nobody has reached since (a check-in is not
                  reaching out)
    BIRTHDAYS ... contacts.birthdate, this week on the church's clock
    BAPTISMS .... planned baptisms in the church register, today or later

Care and giving stay with the logins that hold them: the roll says only
that someone has an open care card (never its words), and giving shows on a
person's page only for the owner, admins and accountants, and only when
Giving & money is open to them (church_keys).

Who: the owner and the church's staff seats (manager, admin), the people
the shepherding and families pages are for; while Who sees what is on, a
staff login whose areas are neither People & care nor the Office is refused.
Switch: CHURCH_ROLL off | owner (the default: the platform owner only) | on.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(prefix="/church/roll", tags=["church"])

MIN_ROLE = "manager"            # the shepherding and families pages' gate
SUNDAYS = 8                     # the dots
NEW_GUEST_DAYS = 30
PAGE = 1000                     # the most rows one read returns (PostgREST's cap)
MAX_ROWS = 100_000              # past this a read is refused, never cut short
LATELY = 6
CACHE_SECONDS = 90              # a person's page reuses the roll just read

STATUS = {"active": "member", "lead": "guest", "vip": "leader", "inactive": "inactive", "churned": "inactive"}
STATUS_WORD = {"member": "Member", "guest": "Guest", "leader": "Leader", "inactive": "Inactive"}
MINOR_TAGS = {"youth", "kids", "kid", "teen", "teens", "child", "children", "minor", "minors", "under 18",
              "youth member", "kids ministry"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_ROLL") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", "") or "").strip().lower() == owner
    return False


# ─── Small things ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(v: Any) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(404, "Not Found")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso_z(dt: datetime) -> str:
    # No "+00:00": a raw "+" in a PostgREST query string reads as a space.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short(d: Optional[date]) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}" if d else ""


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The roll couldn't be read just now. Try again.")
    return rows


def _all(path: str, order: str = "id.asc") -> List[Dict[str, Any]]:
    """Every row, a page at a time in a stable order: a read the server caps
    is never taken for the whole church."""
    out: List[Dict[str, Any]] = []
    while True:
        rows = _need(f"{path}&order={order}&limit={PAGE}&offset={len(out)}")
        out += rows
        if len(rows) < PAGE:
            return out
        if len(out) >= MAX_ROWS:
            raise HTTPException(503, "The roll has more rows than one read can hold. Try again later.")


def _soft_all(path: str, order: str = "id.asc") -> Optional[List[Dict[str, Any]]]:
    """_all for an optional source (Who serves when, which has no ledger
    row): None when it can't be read, and the roll goes on without it."""
    try:
        return _all(path, order)
    except HTTPException:
        return None


def _chunks(values: Iterable[Any], n: int = 120) -> List[List[str]]:
    vals = sorted({str(v) for v in values if v})
    return [vals[i:i + n] for i in range(0, len(vals), n)]


def _meta(row: Dict[str, Any], key: str) -> str:
    """A metadata field, read either as its own column (the select's alias)
    or from inside metadata."""
    v = row.get(key)
    if v is None and isinstance(row.get("metadata"), dict):
        v = row["metadata"].get(key)
    return _plain(v) if isinstance(v, (str, int, float)) else ""


def last_name(name: str, given: str = "") -> str:
    """The family name a roll sorts by: metadata's last_name, else the last
    word past a suffix (Jr, Sr, II…)."""
    if given:
        return given
    words = [w for w in _plain(name).split(" ") if w]
    while len(words) > 1 and words[-1].lower().rstrip(",.") in ("jr", "sr", "ii", "iii", "iv", "v"):
        words.pop()
    return words[-1] if len(words) > 1 else (words[0] if words else "")


def _age(born: Optional[date], today: date) -> Optional[int]:
    if not born:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _band(age: Optional[int]) -> str:
    if age is None:
        return ""
    return "kid" if age < 13 else "youth" if age < 18 else "adult"


def _birthday_on(born: date, year: int) -> date:
    """Their birthday in a given year (Feb 29 falls on Feb 28 off a leap year)."""
    try:
        return born.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def _status(row: Dict[str, Any]) -> str:
    return STATUS.get(str(row.get("status") or "").lower(), "member")


# ─── Who may read it ──────────────────────────────────────────────────

def _areas_ok(biz_id: str, uid: str, role: str) -> bool:
    """The owner and admins always; while Who sees what is off, every staff
    login; else a login whose areas are the whole church or include People &
    care or the Office. A view that couldn't be read is a 503, never a yes."""
    if role in ("owner", "admin"):
        return True
    import church_areas
    if church_areas.mode() != "on":
        return True
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    return areas is None or "people_care" in areas or "office" in areas


def _may_give(biz_id: str, user: Any, role: str) -> bool:
    """Giving shows for the owner, admins and accountants, while Giving &
    money is open to them (church_keys). Any failure is a no."""
    try:
        ok = role in ("owner", "admin")
        if not ok:
            from business_collaborators_router import is_active_accountant
            ok = bool(is_active_accountant(biz_id, str(user.id)))
        if not ok:
            return False
        import church_keys
        return church_keys.is_open(biz_id, user, "giving_money")
    except HTTPException:
        return False
    except Exception:
        return False


def _may_care(biz_id: str, user: Any) -> bool:
    try:
        import church_keys
        return church_keys.is_open(biz_id, user, "people_care")
    except Exception:
        return False


def _gate(biz: Dict[str, Any], session: UserSession) -> Tuple[str, Any, str]:
    user = session.user
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = str(biz["id"])
    import church_follow_up
    if not church_follow_up.is_church(biz):
        raise HTTPException(404, "Not Found")
    role = str(biz.get("_caller_role") or "")
    if not _areas_ok(biz_id, str(user.id), role):
        raise HTTPException(403, "The roll is for People & care and the Office.")
    return biz_id, user, role


# ─── Reading the church ───────────────────────────────────────────────

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _sundays(biz: Dict[str, Any], b: str, now: datetime) -> Dict[str, Any]:
    """The recorded Sundays (newest first, up to SUNDAYS), each person's
    mark on each, the first-visit days attendance knows, and today's count."""
    import church_shepherd_signals as sig
    rule = sig.sunday_rule(biz)
    if rule is None:
        raise HTTPException(503, "Sundays couldn't be read just now. Try again.")
    tz, weekday = rule
    today = now.astimezone(tz).date()
    cutoff = _iso_z(now - timedelta(weeks=sig.WINDOW_WEEKS, days=1))
    rows = _all(f"/attendance?business_id=eq.{_q(b)}&checked_in_at=gte.{_q(cutoff)}"
                "&select=id,entry_id,contact_id,name,method,first_time,checked_in_at")
    days_of = sig._entry_days(b, rows, tz)
    if days_of is None:
        raise HTTPException(503, "Sundays couldn't be read just now. Try again.")
    days: Set[date] = set()
    marks: Dict[str, Dict[date, str]] = {}
    firsts: Dict[str, date] = {}
    on_day: Dict[date, Set[str]] = {}
    for r in rows:
        eid = str(r.get("entry_id") or "")
        at = _parse(r.get("checked_in_at"))
        d = days_of.get(eid) if eid else (at.astimezone(tz).date() if at else None)
        if not d or d.weekday() != weekday or d > today:
            continue
        days.add(d)
        cid = str(r.get("contact_id") or "")
        who = f"c:{cid}" if cid else "n:" + _plain(r.get("name")).lower()
        if who != "n:":
            on_day.setdefault(d, set()).add(who)
        if not cid:
            continue
        k = "O" if str(r.get("method") or "") == "online" else "P"
        mine = marks.setdefault(cid, {})
        if mine.get(d) != "P":          # in person wins over online
            mine[d] = k
        if r.get("first_time") and (cid not in firsts or d < firsts[cid]):
            firsts[cid] = d
    newest = sorted(days, reverse=True)
    return {
        "tz": tz, "today": today, "all_days": newest, "days": newest[:SUNDAYS],
        "marks": marks, "firsts": firsts,
        "here_today": len(on_day.get(today, ())) if newest and newest[0] == today else None,
    }


def build(biz: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything the roll shows, for the whole church. Raises 503 when any
    read failed: a short read never shows as fewer people or a missed Sunday."""
    import church_shepherd_signals as sig
    now = now or _now()
    b = str(biz["id"])
    sun = _sundays(biz, b, now)
    today: date = sun["today"]

    contacts = _all(f"/contacts?business_id=eq.{_q(b)}"
                    "&select=id,name,email,phone,status,tags,birthdate,created_at,source,"
                    "first_name:metadata->>first_name,last_name:metadata->>last_name,"
                    "imported_at:metadata->>imported_at,imported_from:metadata->>imported_from")
    people: Dict[str, Dict[str, Any]] = {}
    for c in contacts:
        cid = str(c.get("id") or "")
        name = _plain(c.get("name"))
        if not cid or not name:
            continue
        people[cid] = c

    # Families
    homes = {str(h["id"]): h for h in _all(f"/households?business_id=eq.{_q(b)}&select=id,name") if h.get("id")}
    adults = _all(f"/household_adults?business_id=eq.{_q(b)}&select=household_id,contact_id,relationship",
                  order="household_id.asc,contact_id.asc")
    kids = _all(f"/children?business_id=eq.{_q(b)}&select=id,household_id,birthdate,active,contact_id") if homes else []
    shepherds = _all(f"/church_shepherds?business_id=eq.{_q(b)}&select=household_id,shepherd_contact_id",
                     order="household_id.asc")
    home_of: Dict[str, str] = {}
    members_of: Dict[str, List[str]] = {}
    child_of: Dict[str, Dict[str, Any]] = {}
    for a in adults:
        hid, cid = str(a.get("household_id") or ""), str(a.get("contact_id") or "")
        if hid in homes and cid in people:
            members_of.setdefault(hid, []).append(cid)
            home_of.setdefault(cid, hid)
    for k in kids:
        hid, cid = str(k.get("household_id") or ""), str(k.get("contact_id") or "")
        if k.get("active") is False or hid not in homes:
            continue
        if cid and cid in people:
            members_of.setdefault(hid, []).append(cid)
            home_of.setdefault(cid, hid)
            child_of[cid] = k
    shepherd_of = {str(s["household_id"]): str(s.get("shepherd_contact_id") or "") for s in shepherds}

    # Groups and serving
    groups = {str(g["id"]): g for g in _all(f"/groups?business_id=eq.{_q(b)}&active=eq.true&select=id,name,kind") if g.get("id")}
    gm = _all(f"/group_members?business_id=eq.{_q(b)}&select=group_id,contact_id,role", order="group_id.asc,contact_id.asc")
    in_groups: Dict[str, List[Tuple[str, bool]]] = {}
    on_teams: Dict[str, Set[str]] = {}
    leads: Set[str] = set()
    for m in gm:
        g = groups.get(str(m.get("group_id") or ""))
        cid = str(m.get("contact_id") or "")
        if not g or cid not in people:
            continue
        name = _plain(g.get("name")) or "A group"
        lead = str(m.get("role") or "") == "leader"
        if lead:
            leads.add(cid)
        if str(g.get("kind") or "") == "team":
            on_teams.setdefault(cid, set()).add(name)
        else:
            in_groups.setdefault(cid, []).append((name, lead))
    team_groups = {gid for gid, g in groups.items() if str(g.get("kind") or "") == "team"}
    if team_groups:
        pos_rows = _soft_all(f"/serve_positions?business_id=eq.{_q(b)}&active=eq.true&select=id,group_id") or []
        positions = {str(p["id"]): str(p.get("group_id") or "") for p in pos_rows if p.get("id")}
        trained = _soft_all(f"/serve_trained?business_id=eq.{_q(b)}&select=position_id,contact_id",
                            order="position_id.asc,contact_id.asc") if positions else []
        for t in trained or []:
            gid = positions.get(str(t.get("position_id") or ""))
            cid = str(t.get("contact_id") or "")
            if gid in groups and cid in people:
                on_teams.setdefault(cid, set()).add(_plain(groups[gid].get("name")) or "A team")

    # Leaders by role
    role_rows = _all(f"/church_leader_roles?business_id=eq.{_q(b)}&status=eq.active&select=contact_id,role",
                     order="contact_id.asc")
    roles_of: Dict[str, List[str]] = {}
    for r in role_rows:
        cid = str(r.get("contact_id") or "")
        if cid in people:
            roles_of.setdefault(cid, []).append(str(r.get("role") or ""))

    # Planned baptisms (today or later on the church's clock)
    planned = _all(f"/church_register_entries?business_id=eq.{_q(b)}&kind=eq.baptism&status=eq.planned"
                   f"&removed_at=is.null&event_on=gte.{today.isoformat()}&select=id,event_on,people,contact_ids",
                   order="event_on.asc,id.asc")
    baptism_on: Dict[str, date] = {}
    for e in planned:
        d = _day(e.get("event_on"))
        ids = [str(x) for x in (e.get("contact_ids") or [])]
        for p in e.get("people") or []:
            if isinstance(p, dict) and p.get("contact_id"):
                ids.append(str(p["contact_id"]))
        for cid in ids:
            if d and cid in people and (cid not in baptism_on or d < baptism_on[cid]):
                baptism_on[cid] = d

    # New guests nobody has reached
    import church_reads
    guests = church_reads.first_time_guests(b, days=NEW_GUEST_DAYS, limit=500, now=now)
    if guests is None:
        raise HTTPException(503, "New guests couldn't be read just now. Try again.")
    unreached = {str(g["contact_id"]): g for g in guests if g.get("contact_id")}

    # Each person's Sundays
    days: List[date] = sun["days"]
    oldest_first = list(reversed(days))
    marks: Dict[str, Dict[date, str]] = sun["marks"]
    tz = sun["tz"]

    def first_known(cid: str, c: Dict[str, Any]) -> Optional[date]:
        """Their first visit: a check-in marked first_time says so; else the
        day their record was made, unless it came over in an import (an
        import stamps the day it ran, not the day they first came)."""
        f = sun["firsts"].get(cid)
        if f:
            return f
        made = _parse(c.get("created_at"))
        imported = (_meta(c, "imported_at") or _meta(c, "imported_from")
                    or str(c.get("source") or "").lower().startswith("import"))
        return made.astimezone(tz).date() if made and not imported else None

    def letters(cid: str, c: Dict[str, Any]) -> str:
        mine = marks.get(cid, {})
        first = first_known(cid, c)
        out = ""
        for d in oldest_first:
            if d in mine:
                out += mine[d]
            elif first and d < first:
                out += "N"
            else:
                out += "M"
        return out

    # Drifting: by family when they have one, else on their own
    all_days: List[date] = sun["all_days"]
    family_drift: Dict[str, bool] = {}
    for hid, ids in members_of.items():
        came: Set[date] = set()
        for cid in ids:
            came |= set(marks.get(cid, {}))
        family_drift[hid] = bool(sig.drift(all_days, came))

    week_days = {(today + timedelta(days=i)) for i in range(7)}
    rows: List[Dict[str, Any]] = []
    for cid, c in people.items():
        status = _status(c)
        if status == "member" and (cid in roles_of or cid in leads):
            status = "leader"
        hid = home_of.get(cid, "")
        born = _day(c.get("birthdate"))
        if not born and cid in child_of:
            born = _day(child_of[cid].get("birthdate"))
        age = _age(born, today)
        band = _band(age)
        if not band and (cid in child_of or {str(t).lower() for t in (c.get("tags") or [])} & MINOR_TAGS):
            band = "youth"
        bday = ""
        if born:
            this_year = _birthday_on(born, today.year)
            if this_year < today:
                this_year = _birthday_on(born, today.year + 1)
            bday = f"{this_year.month:02d}-{this_year.day:02d}"
        drifting = status != "inactive" and (family_drift.get(hid, False) if hid
                                             else bool(sig.drift(all_days, set(marks.get(cid, {})))))
        fv = sun["firsts"].get(cid)
        if not fv and cid in unreached:
            at = _parse(unreached[cid].get("first_visit_at"))
            fv = at.astimezone(tz).date() if at else None
        in_week = bool(born) and (_birthday_on(born, today.year) in week_days
                                  or _birthday_on(born, today.year + 1) in week_days)
        name = _plain(c.get("name"))
        rows.append({
            "id": cid, "name": name,
            "first": _meta(c, "first_name") or name.split(" ")[0],
            "last": last_name(name, _meta(c, "last_name")),
            "status": status,
            "family": {"id": hid, "name": _plain(homes[hid].get("name")) if hid else ""},
            "groups": [g for g, _ in sorted(in_groups.get(cid, []), key=lambda x: (not x[1], x[0].lower()))],
            "serving": sorted(on_teams.get(cid, set()), key=str.lower),
            "sundays": letters(cid, c),
            "first_visit": fv.isoformat() if fv else "",
            "birthday": bday,
            "age_band": band,
            "drifting": drifting,
            "new_unreached": cid in unreached and status != "inactive",
            "baptism_on": baptism_on[cid].isoformat() if cid in baptism_on else "",
            "phone": _plain(c.get("phone")),
            "email": _plain(c.get("email")),
            "_born": born, "_bday_this_week": in_week, "_age": age,
        })

    # The family list (named, with a shepherd)
    names = {cid: _plain(c.get("name")) for cid, c in people.items()}
    families = [{"id": hid, "name": _plain(h.get("name")) or "A family",
                 "shepherd": names.get(shepherd_of.get(hid, ""), ""),
                 "drifting": family_drift.get(hid, False)}
                for hid, h in homes.items() if members_of.get(hid)]

    return {
        "biz_id": b, "today": today, "tz": tz, "days": days, "all_days": all_days,
        "here_today": sun["here_today"], "people": rows, "by_id": {r["id"]: r for r in rows},
        "families": families, "homes": homes, "members_of": members_of, "child_of": child_of,
        "shepherd_of": shepherd_of, "names": names, "in_groups": in_groups, "roles_of": roles_of,
        "marks": marks, "unreached": unreached, "planned": planned, "family_drift": family_drift,
    }


def _cached(biz: Dict[str, Any], *, fresh: bool) -> Dict[str, Any]:
    b = str(biz["id"])
    hit = _cache.get(b)
    if hit and not fresh and hit[0] > time.monotonic():
        return hit[1]
    ctx = build(biz)
    _cache[b] = (time.monotonic() + CACHE_SECONDS, ctx)
    if len(_cache) > 200:                       # a busy replica never grows without end
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    return ctx


# ─── The roll ─────────────────────────────────────────────────────────

def _names(list_: List[str], most: int = 3) -> List[str]:
    return list_[:most]


def week(ctx: Dict[str, Any]) -> Dict[str, Any]:
    today: date = ctx["today"]
    live = [p for p in ctx["people"] if p["status"] != "inactive"]
    new = sorted((p for p in live if p["new_unreached"]), key=lambda p: p["first_visit"] or "", reverse=True)
    newest = ""
    if new:
        n0 = new[0]
        when = _day(n0["first_visit"])
        newest = f"Newest: {n0['name']}{', first here ' + short(when) if when else ''}."
    drift_people = [p for p in live if p["drifting"]]
    drift_fams = {p["family"]["id"] or f"p:{p['id']}" for p in drift_people}
    order = [(today + timedelta(days=i)) for i in range(7)]
    md = {f"{d.month:02d}-{d.day:02d}": d for d in order}
    bdays = sorted((p for p in live if p["_bday_this_week"]),
                   key=lambda p: (md.get(p["birthday"]) or today, p["last"].lower()))
    first = []
    for p in bdays[:3]:
        d = md.get(p["birthday"])
        first.append({"name": p["name"], "day": "today" if d == today else (DAYS[d.weekday()] if d else short(_day(f"{today.year}-{p['birthday']}")))})
    bap = None
    upcoming = sorted({p["baptism_on"] for p in live if p["baptism_on"]})
    if upcoming:
        nxt = upcoming[0]
        on = [p["name"] for p in live if p["baptism_on"] == nxt]
        bap = {"n": len(on), "date": nxt, "names": on[:6]}
    return {
        "new_guests": {"n": len(new), "names": _names([p["name"] for p in new], 6), "newest": newest},
        "drifting": {"families": len(drift_fams), "people": len(drift_people)},
        "birthdays": {"n": len(bdays), "from": today.isoformat(), "to": (today + timedelta(days=6)).isoformat(), "first": first},
        "baptism": bap,
    }


def roll_view(ctx: Dict[str, Any], *, can_care: bool, can_give: bool) -> Dict[str, Any]:
    public = [{k: v for k, v in p.items() if not k.startswith("_")} for p in ctx["people"]]
    return {
        "today": ctx["today"].isoformat(),
        "sundays": [d.isoformat() for d in reversed(ctx["days"])],
        "here_today": ctx["here_today"],
        "people": public,
        "families": ctx["families"],
        "week": week(ctx),
        "can_care": can_care,
        "can_give": can_give,
    }


# ─── One person ───────────────────────────────────────────────────────

def _care_open(b: str, cid: str) -> bool:
    """Someone has an open care card for them (never what it says)."""
    try:
        import church_follow_up as cfu
        rows = sb_clients.sb_get_as_service(
            f"/church_follow_ups?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&status=in.(open,handed_back)"
            "&select=id,path_kind,answers&limit=50")
        if not isinstance(rows, list):
            return False
        return any(cfu.stream_for(r.get("path_kind") or "", r.get("answers") or [])[0] == "care_need" for r in rows)
    except Exception:
        return False


def _member_since(b: str, cid: str) -> Optional[date]:
    rows = sb_clients.sb_get_as_service(
        f"/church_register_entries?business_id=eq.{_q(b)}&kind=eq.membership&status=eq.done&removed_at=is.null"
        f"&membership=in.(joined,transferred_in)&contact_ids=cs.{{{cid}}}&select=event_on&order=event_on.asc&limit=1")
    if isinstance(rows, list) and rows:
        return _day(rows[0].get("event_on"))
    return None


def _address(meta: Any) -> str:
    a = meta.get("address") if isinstance(meta, dict) else None
    if isinstance(a, str):
        return _plain(a)
    if isinstance(a, dict):
        line = ", ".join(x for x in (_plain(a.get("line1") or a.get("street")), _plain(a.get("line2"))) if x)
        town = " ".join(x for x in (_plain(a.get("city")) + ("," if a.get("city") and (a.get("state") or a.get("zip")) else ""),
                                    _plain(a.get("state")), _plain(a.get("zip") or a.get("postal_code"))) if x)
        return ", ".join(x for x in (line, town) if x)
    return ""


EVENT_WORDS = {
    "contact_note": "Note",
    "activity_logged": "Logged",
    "email_sent": "Emailed",
    "sms_sent": "Texted",
    "agent_message_sent": "Messaged",
    "journey_sent": "Follow-up step sent",
    "contact_status_changed": "Status changed",
}


def _lately(ctx: Dict[str, Any], b: str, cid: str) -> List[Dict[str, str]]:
    """The newest few things that happened with them: notes and contact
    from the office, and their Sundays. A failed read leaves its part out."""
    tz = ctx["tz"]
    items: List[Tuple[datetime, str]] = []
    ev = sb_clients.sb_get_as_service(
        f"/events?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&event_type=in.({','.join(EVENT_WORDS)})"
        "&select=event_type,data,created_at&order=created_at.desc&limit=20")
    for e in ev if isinstance(ev, list) else []:
        at = _parse(e.get("created_at"))
        if not at:
            continue
        kind = str(e.get("event_type") or "")
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        if kind == "contact_note":
            words = _plain(data.get("note"))
            text = f"Note: {words[:110]}{'…' if len(words) > 110 else ''}" if words else "A note"
        elif kind == "contact_status_changed":
            to = STATUS_WORD.get(STATUS.get(str(data.get("to") or "").lower(), ""), "")
            text = f"Marked {to}" if to else "Status changed"
        elif kind == "activity_logged":
            what = _plain(data.get("activity_type") or data.get("type") or "")
            text = f"{what.capitalize()} logged" if what else "Contact logged"
        else:
            text = EVENT_WORDS[kind]
        items.append((at, text))
    sms = sb_clients.sb_get_as_service(
        f"/sms_messages?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&status=neq.failed"
        "&select=direction,created_at&order=created_at.desc&limit=10")
    for s in sms if isinstance(sms, list) else []:
        at = _parse(s.get("created_at"))
        if at:
            items.append((at, "Texted by the church" if s.get("direction") == "outbound" else "Texted the church"))
    for d, k in ctx["marks"].get(cid, {}).items():
        items.append((datetime(d.year, d.month, d.day, 12, tzinfo=tz), "Here in person" if k == "P" else "Watched online"))
    items.sort(key=lambda x: x[0], reverse=True)
    out, seen = [], set()
    for at, text in items:
        d = at.astimezone(tz).date()
        if (d, text) in seen:
            continue
        seen.add((d, text))
        out.append({"d": short(d), "t": text})
        if len(out) >= LATELY:
            break
    return out


def _giving(b: str, cid: str, today: date) -> List[Dict[str, str]]:
    try:
        import giving_records
        gifts = giving_records.read_gifts(b, f"{today.year}-01-01", f"{today.year + 1}-01-01", contact_id=cid)
    except Exception:
        return [{"k": "Giving", "v": "Couldn’t be read just now"}]
    total = 0.0
    last: Optional[date] = None
    for g in gifts:
        try:
            total += float(g.get("total") or 0) - float(g.get("refund_amount_cents") or 0) / 100
        except (TypeError, ValueError):
            pass
        d = _day(g.get("paid_at"))
        if d and (last is None or d > last):
            last = d
    if not gifts:
        return [{"k": f"In {today.year}", "v": "No gifts yet"}]
    n = len(gifts)
    return [{"k": f"In {today.year}", "v": f"${total:,.0f} in {n} gift{'s' if n != 1 else ''}"},
            {"k": "Last gift", "v": short(last)}]


def _chief(ctx: Dict[str, Any], p: Dict[str, Any], shepherd: str) -> Dict[str, Any]:
    """What Chief sees, in plain words, with the next step as a button. A
    rule over what's on file, not a model call: it costs nothing and never
    says something the record can't back."""
    first, name = p["first"] or p["name"], p["name"]
    s = p["sundays"]
    here = sum(1 for k in s if k in "PO")
    of = sum(1 for k in s if k != "N")
    today: date = ctx["today"]
    if p["drifting"]:
        before = s[:-3]
        came = sum(1 for k in before if k in "PO")
        size = sum(1 for k in before if k != "N")
        who = f"Their family’s shepherd is {shepherd}." if shepherd else "Their family has no shepherd yet."
        return {"text": f"{first} came {came} of the {size} Sundays before, then missed the last 3. {who}",
                "actions": [{"label": f"Draft a text to {first}", "ask": f"Draft a short, warm text to {name}, who has missed the last 3 Sundays. No guilt, just that we miss them. Show me before it sends."},
                            {"label": "Who should call?", "ask": f"Who should call {name} this week? They have missed the last 3 Sundays."}]}
    if p["new_unreached"]:
        fv = _day(p["first_visit"])
        return {"text": f"{first} first visited{' on ' + short(fv) if fv else ''} and nobody has reached out yet.",
                "actions": [{"label": "Draft a welcome text", "ask": f"Draft a welcome text to {name}, who visited for the first time{' on ' + short(fv) if fv else ''}. Show me before it sends."},
                            {"label": "Hand to the welcome team", "ask": f"Hand {name}, a first-time guest, to our welcome team to follow up this week."}]}
    if p["baptism_on"]:
        d = _day(p["baptism_on"])
        return {"text": f"{first} is planned for baptism on {short(d)}.",
                "actions": [{"label": "Send the details", "ask": f"Draft a note to {name} about their baptism on {short(d)}: what to bring and when to arrive. Show me before it sends."}]}
    if p["_bday_this_week"]:
        bd = _day(f"{today.year}-{p['birthday']}") if p["birthday"] else None
        return {"text": f"{first}’s birthday is {'today' if bd == today else short(bd)}.",
                "actions": [{"label": "Draft a birthday note", "ask": f"Draft a short birthday text to {name}. Show me before it sends."}]}
    if p["status"] == "guest" and here >= 2:
        return {"text": f"{first} has come {here} of the last {of} Sundays as a guest. They may be ready to hear about membership.",
                "actions": [{"label": "Invite them to membership", "ask": f"Draft an invitation to {name} for our next membership class. Show me before it sends."}]}
    adult = p["age_band"] not in ("kid", "youth")
    if p["status"] in ("member", "leader") and adult and not p["groups"]:
        return {"text": f"{first} is here {here} of {of} Sundays and isn’t in a group yet.",
                "actions": [{"label": "Suggest a group", "ask": f"Which of our groups would suit {name}? They aren’t in one yet."}]}
    if p["status"] == "member" and adult and not p["serving"] and of and here * 2 >= of:
        return {"text": f"{first} is here most Sundays and isn’t serving yet.",
                "actions": [{"label": "Ask about serving", "ask": f"Draft a note asking {name} if they would like to serve on one of our teams. Show me before it sends."}]}
    if p["status"] == "inactive":
        return {"text": f"{first} is kept on the roll as inactive.",
                "actions": [{"label": f"Ask Chief about {first}", "ask": f"Tell me about {name}."}]}
    line = f"{first} is here {here} of {of} Sundays." if of else f"No Sundays recorded for {first} yet."
    return {"text": line, "actions": [{"label": f"Ask Chief about {first}", "ask": f"Tell me about {name}."}]}


def person_view(ctx: Dict[str, Any], cid: str, *, can_care: bool, can_give: bool) -> Dict[str, Any]:
    b = ctx["biz_id"]
    p = ctx["by_id"].get(cid)
    if not p:
        raise HTTPException(404, "They aren’t on this church’s roll.")
    rows = _need(f"/contacts?business_id=eq.{_q(b)}&id=eq.{_q(cid)}&select=id,name,email,phone,birthdate,status,metadata&limit=1")
    if not rows:
        raise HTTPException(404, "They aren’t on this church’s roll.")
    c = rows[0]
    today: date = ctx["today"]
    hid = p["family"]["id"]
    shepherd = ctx["names"].get(ctx["shepherd_of"].get(hid, ""), "") if hid else ""
    family = None
    if hid:
        people = []
        for mid in ctx["members_of"].get(hid, []):
            m = ctx["by_id"].get(mid)
            if not m or any(x["id"] == mid for x in people):
                continue
            age = m.get("_age")
            role = "child" if mid in ctx["child_of"] or m["age_band"] in ("kid", "youth") else ""
            people.append({"id": mid, "name": m["name"], "role": f"{role}, {age}" if role and age is not None else role})
        people.sort(key=lambda x: (x["role"] != "", x["name"].lower()))
        family = {"id": hid, "name": p["family"]["name"] or "Their family", "shepherd": shepherd, "people": people}

    church: List[Dict[str, str]] = []
    grp = ctx["in_groups"].get(cid, [])
    if grp:
        church.append({"k": "Groups", "v": ", ".join(f"{g} (leads)" if lead else g for g, lead in grp)})
    if p["serving"]:
        church.append({"k": "Serving", "v": ", ".join(p["serving"])})
    if ctx["roles_of"].get(cid):
        try:
            import church_roles
            defs = church_roles.defs(b) or []
            titles = [church_roles.title_of(k, defs) for k in ctx["roles_of"][cid] if k]
        except Exception:
            titles = []
        if titles:
            church.append({"k": "Leads as", "v": ", ".join(t for t in titles if t)})
    if shepherd:
        church.append({"k": "Shepherd", "v": shepherd})
    since = _member_since(b, cid) if p["status"] in ("member", "leader") else None
    if since:
        church.append({"k": "Member since", "v": f"{MONTHS[since.month - 1]} {since.year}"})
    fv = _day(p["first_visit"])
    if fv:
        church.append({"k": "First visit", "v": f"{short(fv)}, {fv.year}" if fv.year != today.year else short(fv)})

    reach: List[Dict[str, str]] = []
    phone, email = _plain(c.get("phone")), _plain(c.get("email"))
    if phone:
        reach.append({"k": "Mobile", "v": phone, "href": "tel:" + "".join(ch for ch in phone if ch.isdigit() or ch == "+")})
    if email:
        reach.append({"k": "Email", "v": email, "href": f"mailto:{email}"})
    born = p.get("_born")
    if born:
        age = p.get("_age")
        reach.append({"k": "Birthday", "v": f"{MONTHS[born.month - 1]} {born.day}" + (f" · {age}" if age is not None and age < 18 else ""), "href": ""})
    addr = _address(c.get("metadata"))
    if addr:
        reach.append({"k": "Address", "v": addr, "href": ""})

    status = p["status"]
    line = " · ".join(x for x in (STATUS_WORD[status], p["family"]["name"],
                                  f"first here {short(fv)}" if status == "guest" and fv else "") if x)
    marks = {d: k for d, k in zip(reversed(ctx["days"]), p["sundays"])}
    return {
        "id": cid, "name": p["name"], "status": status, "line": line,
        "phone": phone, "email": email,
        "family": family,
        "sundays": [{"date": d.isoformat(), "k": marks.get(d, "M")} for d in reversed(ctx["days"])],
        "church": church,
        "reach": reach,
        "lately": _lately(ctx, b, cid),
        "chief": _chief(ctx, p, shepherd),
        "care_open": _care_open(b, cid),
        "giving": _giving(b, cid, today) if can_give else [],
        "can_care": can_care,
        "can_give": can_give,
    }


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("")
def roll(business_id: str = Query(...),
         biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
         session: UserSession = Depends(sb_clients.authed_request)):
    """The roll: everyone, their Sundays, families, and This week."""
    b, user, role = _gate(biz, session)
    ctx = _cached(biz, fresh=True)
    return roll_view(ctx, can_care=_may_care(b, user), can_give=_may_give(b, user, role))


@router.get("/person/{contact_id}")
def person(contact_id: str, business_id: str = Query(...),
           biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
           session: UserSession = Depends(sb_clients.authed_request)):
    """One person's page on the roll."""
    b, user, role = _gate(biz, session)
    cid = _uuid(contact_id)
    ctx = _cached(biz, fresh=False)
    if cid not in ctx["by_id"]:
        ctx = _cached(biz, fresh=True)       # someone just added
    return person_view(ctx, cid, can_care=_may_care(b, user), can_give=_may_give(b, user, role))
