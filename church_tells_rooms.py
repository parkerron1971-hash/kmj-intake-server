"""church_tells_rooms.py — the rooms tells and a leader's yes, for church_tells.

Love City's connection map (2026-11-21) found three hand-offs that told
nobody:

  room_asked ....... an office login asked for a room and the rooms holder
                     wasn't told; the request sat until someone opened
                     Rooms & spaces. Now whoever does the rooms hears it.
  room_answered .... the rooms holder said yes or no and the login who asked
                     never heard back. Now they do.
  leader_said_yes .. a person said yes to a leader role and whoever runs
                     background checks didn't know a check was next. Now
                     they do.

Each finder is finder(church, now) -> [church_tells.Item]; the sweep picks
who hears, groups, keeps quiet hours and tells each item once.

Why a member's room ask is left out of room_asked: the member app's ask
(member_asks.ask_room) already phones the rooms holders the moment it's
made. Its rows are booked with no login (booked_by is null, contact_id is
the member), so this finder reads only rows an office login booked
(booked_by=not.is.null) and nobody hears twice. For the same reason
room_answered tells only a login: a member has no login to tell.

A weekly repeat is one request (one series_id), so it is one tell, keyed by
the series, not one tell a week.

The words never carry a booking's notes, a decider's reason, or anything
private: who, the room, the day and time. A read that fails returns [] and
the next sweep tries again; a read the words depend on (who asked, the
room, a background check) that fails stops the finder rather than send a
wrong or empty line, because a tell is sent once for good.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import church_tells as ct
import sb_clients

ASK_DAYS = 3            # a request made this recently, still waiting
ANSWER_DAYS = 3         # a request answered this recently
YES_DAYS = 7            # a leader's yes this recently
LIMIT = 200
ADULT = 18              # background checks are for adults (church_serving.check_state's `teen`)


# ─── Reads ────────────────────────────────────────────────────────────

def _read(path: str) -> Optional[List[Dict[str, Any]]]:
    """A service read that says when it failed (None), for the reads the
    words or the decision depend on."""
    try:
        got = sb_clients.sb_get_as_service(path)
    except Exception:  # noqa: BLE001
        return None
    return got if isinstance(got, list) else None


def _in(ids: Iterable[Any]) -> str:
    return "in.(" + ",".join(ct.q(i) for i in sorted({str(i) for i in ids if i})) + ")"


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _zone(church: Dict[str, Any]):
    """The church's clock, as Rooms & spaces reads it."""
    import church_spaces
    return church_spaces._tz({"biz": {"id": str(church["id"])}})


def _when(row: Dict[str, Any], tz) -> str:
    import church_spaces
    s, e = _at(row.get("start_at")), _at(row.get("end_at"))
    return church_spaces.when_text(s, e, tz) if s and e else "a day to be set"


def _seats(biz: str) -> Optional[Dict[str, Dict[str, Any]]]:
    rows = _read(f"/business_users?business_id=eq.{ct.q(biz)}&status=eq.active"
                 f"&select=user_id,contact_id,name,invited_email&limit={LIMIT}")
    return None if rows is None else {str(s["user_id"]): s for s in rows if s.get("user_id")}


def _login_names(church: Dict[str, Any], uids: Iterable[str],
                 seats: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """user id -> the name the church knows the login by (church_over's
    rule): the owner by the church's own name for them; a login by its
    person's first name, else the name it gave, else its email before the @."""
    biz = str(church["id"])
    owner = str(church.get("owner_id") or "")
    want = [u for u in {str(u) for u in uids if u}]
    cids = {str(seats[u]["contact_id"]) for u in want if u in seats and seats[u].get("contact_id")}
    people: Dict[str, str] = {}
    if cids:
        got = _read(f"/contacts?business_id=eq.{ct.q(biz)}&id={_in(cids)}&select=id,name&limit={LIMIT}")
        if got is None:
            return None
        people = {str(c["id"]): _plain(c.get("name")) for c in got}
    settings = church.get("settings") if isinstance(church.get("settings"), dict) else {}
    out: Dict[str, str] = {}
    for u in want:
        if u == owner:
            out[u] = _plain(settings.get("practitioner_name")) or "The owner"
            continue
        s = seats.get(u) or {}
        raw = people.get(str(s.get("contact_id") or "")) or _plain(s.get("name")) or _plain(s.get("invited_email"))
        out[u] = (raw.split("@")[0] if "@" in raw else raw.split(" ")[0]) if raw else "Someone in the office"
    return out


def _rooms(biz: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    ids = {r.get("space_id") for r in rows if r.get("space_id")}
    if not ids:
        return {}
    got = _read(f"/church_spaces?business_id=eq.{ct.q(biz)}&id={_in(ids)}&select=id,name&limit={LIMIT}")
    return None if got is None else {str(s["id"]): _plain(s.get("name")) for s in got}


def _groups(rows: List[Dict[str, Any]], extra: Tuple[str, ...] = ()) -> List[List[Dict[str, Any]]]:
    """A weekly repeat's rows together (by series, and `extra` fields), the
    first by start first; a one-off booking alone."""
    out: Dict[Tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        k = (("series", str(r["series_id"]), *(str(r.get(f) or "") for f in extra))
             if r.get("series_id") else ("one", str(r["id"])))
        out.setdefault(k, []).append(r)
    return [sorted(g, key=lambda r: str(r.get("start_at") or "")) for g in out.values()]


def _more(group: List[Dict[str, Any]]) -> str:
    n = len(group) - 1
    return f", and {n} more week{'s' if n != 1 else ''}" if n > 0 else ""


BOOKING = "id,space_id,start_at,end_at,booked_by,status,series_id,decided_by,decided_at,created_at"


# ─── A room request -> the rooms holder ───────────────────────────────

def room_asked(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    """An office login's room request from the last ASK_DAYS, still waiting
    and still to come. The member app's own asks (no login) are left out:
    member_asks already phoned the rooms holders."""
    biz = str(church["id"])
    rows = ct.rows(f"/church_space_bookings?business_id=eq.{ct.q(biz)}&status=eq.requested"
                   f"&booked_by=not.is.null&created_at=gte.{ct.since(now, ASK_DAYS)}"
                   f"&end_at=gt.{ct.since(now, 0)}&select={BOOKING}&order=start_at.asc&limit={LIMIT}")
    rows = [r for r in rows if r.get("id") and r.get("booked_by")]
    if not rows:
        return []
    seats = _seats(biz)
    rooms = _rooms(biz, rows)
    if seats is None or rooms is None:
        return []
    names = _login_names(church, (r["booked_by"] for r in rows), seats)
    if names is None:
        return []
    try:
        tz = _zone(church)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for g in _groups(rows):
        first = g[0]
        who = names.get(str(first["booked_by"])) or "Someone in the office"
        room = rooms.get(str(first.get("space_id"))) or "a room"
        key = f"room-ask:{first['series_id']}" if first.get("series_id") else f"room-ask:{first['id']}"
        out.append(ct.Item(key=key, title="A room request",
                           line=f"{who} asked for {room}, {_when(first, tz)}{_more(g)}. Say yes or no in Rooms & spaces.",
                           duty="rooms", actor=str(first["booked_by"])))
    return out


# ─── The answer -> whoever asked ──────────────────────────────────────

def room_answered(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    """A request booked or declined in the last ANSWER_DAYS, asked by an
    office login (the owner or an active business_users seat) and decided by
    someone else. A booking an approver made straight away has decided_by =
    booked_by, so it never shows here."""
    biz = str(church["id"])
    rows = ct.rows(f"/church_space_bookings?business_id=eq.{ct.q(biz)}&status=in.(booked,declined)"
                   f"&booked_by=not.is.null&decided_at=gte.{ct.since(now, ANSWER_DAYS)}"
                   f"&select={BOOKING}&order=start_at.asc&limit={LIMIT}")
    rows = [r for r in rows if r.get("id") and r.get("booked_by") and r.get("decided_by")
            and str(r["decided_by"]) != str(r["booked_by"])]
    if not rows:
        return []
    seats = _seats(biz)
    if seats is None:
        return []
    owner = str(church.get("owner_id") or "")
    rows = [r for r in rows if str(r["booked_by"]) in seats or str(r["booked_by"]) == owner]
    if not rows:
        return []
    rooms = _rooms(biz, rows)
    if rooms is None:
        return []
    try:
        tz = _zone(church)
    except Exception:  # noqa: BLE001
        return []
    out = []
    # One decision on a weekly repeat is one answer: its rows share the
    # series, the status and the moment it was decided.
    for g in _groups(rows, extra=("status", "decided_at", "booked_by")):
        first = g[0]
        yes = first.get("status") == "booked"
        room = rooms.get(str(first.get("space_id"))) or "A room"
        key = (f"room-answer:{first['series_id']}:{first['status']}:{first.get('decided_at')}"
               if first.get("series_id") else f"room-answer:{first['id']}")
        out.append(ct.Item(key=key,
                           title="Your room request was booked" if yes else "Your room request wasn't approved",
                           line=f"{room}, {_when(first, tz)}{_more(g)}.",
                           to=[str(first["booked_by"])], actor=str(first["decided_by"])))
    return out


# ─── A leader's yes -> background checks ──────────────────────────────

def leader_said_yes(church: Dict[str, Any], now: datetime) -> List[ct.Item]:
    """A person who said yes to a leader role in the last YES_DAYS and has
    no background check on file (church_serving.check_on: the latest of a
    kids/youth leader approval's date and one recorded in Serving). Someone
    under 18 is left out: checks are for adults (church_serving's `teen`).
    An expired check is on file, so it isn't told here; Serving's own
    reminders cover it."""
    import church_serving
    biz = str(church["id"])
    rows = ct.rows(f"/church_leader_roles?business_id=eq.{ct.q(biz)}&status=eq.active"
                   f"&answered_at=gte.{ct.since(now, YES_DAYS)}"
                   f"&select=id,contact_id,role,scope,answered_at&order=answered_at.asc&limit={LIMIT}")
    rows = [r for r in rows if r.get("id") and r.get("contact_id")]
    if not rows:
        return []
    cids = {str(r["contact_id"]) for r in rows}
    people = _read(f"/contacts?business_id=eq.{ct.q(biz)}&id={_in(cids)}"
                   f"&select=id,name,birthdate,metadata&limit={LIMIT}")
    leaders = _read(f"/space_leaders?business_id=eq.{ct.q(biz)}&contact_id={_in(cids)}"
                    f"&select=contact_id,background_check_on&limit={LIMIT}")
    if people is None or leaders is None:
        return []
    import church_roles
    defs = church_roles.defs(biz)
    if defs is None:
        return []
    by_id = {str(p["id"]): p for p in people}
    dates: Dict[str, List[date]] = {}
    for x in leaders:
        d = church_serving._day(x.get("background_check_on"))
        if d:
            dates.setdefault(str(x["contact_id"]), []).append(d)
    today = now.date()
    out = []
    for r in rows:
        cid = str(r["contact_id"])
        person = by_id.get(cid)
        if not person:
            continue                     # the person is gone; nobody to check
        age = church_serving._age(person.get("birthdate"), today)
        if age is not None and age < ADULT:
            continue
        if church_serving.check_on(dates.get(cid, []), person) is not None:
            continue
        first = _plain(person.get("name")).split(" ")[0] or "Someone"
        title = church_roles.title_of(str(r.get("role") or ""), defs)
        scope = _plain(r.get("scope"))
        what = f"{title} ({scope})" if scope else title
        out.append(ct.Item(key=f"leader-yes:{r['id']}", title="A new leader said yes",
                           line=f"{first} said yes to {what}. Their background check is next.",
                           duty="background_checks"))
    return out
