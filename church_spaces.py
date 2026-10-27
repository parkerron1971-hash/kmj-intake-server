"""church_spaces.py — Rooms & spaces, with Rentals: booking a church's building.

Kevin, 2026-10-27, on the Church Menu Gaps check ("Office, filled in", the
9:10 AM beat: a family calls for the fellowship hall for a funeral meal on
Saturday, and there's no list of rooms and no booking): "lets start building
this". Planning Center's Calendar books rooms and resources with approvals;
that's the bar. Filed under the Build item "Love City leaves Subsplash (M-1)".

    a SPACE ....... a room, a vehicle or a piece of equipment the church
                    lends: the sanctuary, the fellowship hall, the van, the
                    projector. Retired, not deleted (active false), so old
                    bookings keep their room
    a BOOKING ..... one space, a title, a start and an end; who it's for (one
                    of the church's people, optional) and who booked it;
                    requested, booked, declined or cancelled. A weekly repeat
                    is one row a week sharing a series id, up to an end date
    a CLASH ....... two BOOKED bookings of one space that overlap. The server
                    refuses the second and says what it clashes with; the
                    table's exclusion constraint backs that up when two people
                    press Book at once. A request over a booked time is
                    refused too. Requests may overlap each other: the first
                    approved wins, and approving the other is refused
    a RENTAL ...... a booking for someone outside the church (a wedding for a
                    non-member, a group renting the hall): a fee and a
                    deposit, and one bill made through the invoices the app
                    already sends (a church calls them Bills), linked to the
                    booking so its page shows whether it's paid

Who: the owner and admins, and the church's office logins whose areas include
the Office (church_areas, "Who sees what"). The owner, admins and managers
book straight away, approve and keep the list of spaces; any other office
login asks (a request). A viewer login only looks. Money (a rental's fee,
deposit and bill) is the owner's and admins', as gifts are
(ministry_finance_access); everyone else sees a rental without its amounts.
Members can't book from their app in this version.

  GET   /church/spaces/status?business_id=          {enabled, book, approve, rentals}
  GET   /church/spaces?business_id=                 the spaces and what this login may do
  POST  /church/spaces                              {business_id, name, kind, capacity, notes, active}
  PATCH /church/spaces/{id}                         {business_id, ...those}
  POST  /church/spaces/order                        {business_id, ids}
  GET   /church/spaces/bookings?business_id=&start=&end=   the range's bookings, and every waiting request
  POST  /church/spaces/check                        {business_id, space_id, start_at, end_at, repeat_until?, tz?, booking_id?}
  POST  /church/spaces/bookings                     {business_id, space_id, title, start_at, end_at, contact_id?,
                                                     notes?, status?, repeat_until?, tz?, kind?, renter_*?, fee?, deposit?}
  PATCH /church/spaces/bookings/{id}                {business_id, ...what changes}
  POST  /church/spaces/bookings/{id}/decide         {business_id, status: booked | declined | cancelled, series?}
  POST  /church/spaces/bookings/{id}/bill           {business_id}        make the rental's bill, once
  GET   /church/spaces/rentals?business_id=&when=   upcoming | past

Switched by CHURCH_SPACES: off | owner | on (owner until a Thursday). Until
supabase/APPLY-2026-10-27-church-spaces.sql is applied the status says
enabled: false and every other route answers 503, never 500.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/spaces", tags=["church"])

KINDS = ("room", "vehicle", "equipment")
STATUSES = ("requested", "booked", "declined", "cancelled")
# What each role may do here (business_users_router._ROLE_RANK names).
WRITERS = ("owner", "admin", "manager", "member")   # book, or ask
APPROVERS = ("owner", "admin", "manager")           # book straight away, approve, keep the spaces
FINANCE = ("owner", "admin")                        # a rental's money, as ministry_finance_access
KEEPS_ALL = ("owner", "admin")

MAX_REPEATS = 53            # a weekly repeat runs at most a year
MAX_DAYS = 14               # one booking runs at most two weeks
RANGE_DAYS = 62             # one read covers at most two months
NAME_MAX, TITLE_MAX, NOTES_MAX, SPACE_NOTES_MAX = 80, 120, 2000, 1000
MONEY_MAX_CENTS = 10_000_000

SPACE_FIELDS = "id,name,kind,capacity,notes,active,sort_order"
BOOKING_FIELDS = ("id,space_id,title,start_at,end_at,contact_id,booked_by,status,notes,series_id,repeat_until,"
                  "kind,renter_name,renter_email,renter_phone,fee_cents,deposit_cents,invoice_id,"
                  "decided_by,decided_at,created_at")
MONEY_FIELDS = ("fee_cents", "deposit_cents", "invoice_id")
BILL_NS = uuid.UUID("6d1c3c5e-6b8f-4c55-9a3e-2a0f6f1e7b21")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_SPACES") or "owner").strip().lower()
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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _at(v: Any) -> Optional[datetime]:
    s = str(v or "").strip().replace("Z", "+00:00")
    if re.search(r"T\d{2}:\d{2}(:\d{2}(\.\d+)?)? \d{2}:\d{2}$", s):
        s = s[:-6] + "+" + s[-5:]   # a "+" a query string turned into a space
    try:
        d = datetime.fromisoformat(s) if s else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, f"That {what} isn't one we know.")


def _need(path: str) -> List[Dict[str, Any]]:
    """A read that must answer: a failed one (or the tables before their
    migration) is a 503, never an empty building."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Rooms & spaces couldn't be read just now. Try again.")
    return rows


def _zone(name: Any) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(str(name)) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _tz(me: Dict[str, Any], given: Any = None) -> ZoneInfo:
    """The clock a booking's words and weekly repeats are read in: the one
    the app sent (the person's own), else the church's."""
    z = _zone(given)
    if z:
        return z
    try:
        import outside_calendar
        return _zone(outside_calendar.business_timezone(me["biz"]["id"])) or ZoneInfo("UTC")
    except Exception:
        return ZoneInfo("UTC")


def _clock(d: datetime) -> str:
    return f"{d.strftime('%I:%M').lstrip('0')} {d.strftime('%p')}"


def when_text(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    """'Sat Oct 31, 5:00 PM–8:00 PM', or across days with both dates."""
    a, b = start.astimezone(tz), end.astimezone(tz)
    day = f"{a.strftime('%a %b')} {a.day}"
    if a.date() == b.date():
        return f"{day}, {_clock(a)}–{_clock(b)}"
    return f"{day}, {_clock(a)} – {b.strftime('%a %b')} {b.day}, {_clock(b)}"


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open, as the table's tstzrange: one ending at 5 and the next
    starting at 5 don't clash."""
    return a_start < b_end and b_start < a_end


def expand_weekly(start: datetime, end: datetime, until: Optional[date], tz: ZoneInfo) -> List[Tuple[datetime, datetime]]:
    """The times of a booking and its weekly repeats through `until` (in the
    church's clock, so 9 AM stays 9 AM across a clock change). No `until`
    is the one booking. More than MAX_REPEATS is refused, never cut short."""
    if until is None:
        return [(start, end)]
    first = start.astimezone(tz)
    length = end - start
    wall = first.replace(tzinfo=None)
    out: List[Tuple[datetime, datetime]] = []
    for i in range(MAX_REPEATS + 1):
        s_local = (wall + timedelta(weeks=i)).replace(tzinfo=tz)
        if s_local.date() > until:
            break
        if len(out) == MAX_REPEATS:
            raise HTTPException(400, "A weekly repeat runs a year at most. Pick an earlier end date.")
        s = s_local.astimezone(timezone.utc)
        out.append((s, s + length))
    return out


# ─── Who's asking ─────────────────────────────────────────────────────

def _office(biz_id: str, uid: str, role: str) -> bool:
    """Whether this login works the office: the owner and admins always;
    any login while Who sees what is off (everyone sees the whole church,
    as before); else a login whose areas are the whole church or include
    the Office. A view that couldn't be read is a 503, never a yes."""
    if role in KEEPS_ALL:
        return True
    import church_areas
    if church_areas.mode() != "on":
        return True
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    return view.get("areas") is None or "office" in (view.get("areas") or [])


def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and this login's standing in its building. 404 when the
    switch is closed to them, they have no login here, or it isn't a
    church; 403 for a login that doesn't work the office."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "viewer")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, "Rooms & spaces are for churches")
    if not _office(biz_id, str(user.id), role):
        raise HTTPException(403, "Rooms & spaces belong to the office. An admin can add the Office to your areas.")
    return {"biz": biz, "role": role, "uid": str(user.id)}


def _may(me: Dict[str, Any], roles: Sequence[str], why: str) -> None:
    if me["role"] not in roles:
        raise HTTPException(403, why)


def _can(me: Dict[str, Any]) -> Dict[str, bool]:
    return {"book": me["role"] in WRITERS, "approve": me["role"] in APPROVERS, "rentals": me["role"] in FINANCE}


def _ready(biz_id: str) -> bool:
    """Both tables answer (one migration makes both)."""
    return isinstance(sb_clients.sb_get_as_service(
        f"/church_space_bookings?business_id=eq.{_q(biz_id)}&select=id&limit=1"), list)


# ─── Spaces ───────────────────────────────────────────────────────────

def _spaces(biz_id: str) -> List[Dict[str, Any]]:
    rows = _need(f"/church_spaces?business_id=eq.{_q(biz_id)}&select={SPACE_FIELDS}&order=sort_order.asc,name.asc&limit=500")
    return sorted(rows, key=lambda s: (int(s.get("sort_order") or 0), str(s.get("name") or "").lower()))


def _space(biz_id: str, space_id: Any) -> Dict[str, Any]:
    rows = _need(f"/church_spaces?id=eq.{_q(_uuid(space_id, 'room'))}&business_id=eq.{_q(biz_id)}"
                 f"&select={SPACE_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That room isn't one of this church's.")
    return rows[0]


def space_fields(body: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not partial or "name" in body:
        name = _plain(body.get("name"))[:NAME_MAX]
        if not name:
            raise HTTPException(400, "Name the room, vehicle or equipment.")
        out["name"] = name
    if not partial or "kind" in body:
        kind = body.get("kind") or "room"
        if kind not in KINDS:
            raise HTTPException(400, "A space is a room, a vehicle or equipment.")
        out["kind"] = kind
    if "capacity" in body:
        cap = body.get("capacity")
        if cap in (None, ""):
            out["capacity"] = None
        else:
            try:
                n = int(cap)
            except (TypeError, ValueError):
                raise HTTPException(400, "Capacity is how many people it holds.")
            if not 0 <= n <= 100_000:
                raise HTTPException(400, "Capacity is how many people it holds.")
            out["capacity"] = n
    if "notes" in body:
        out["notes"] = str(body.get("notes") or "").strip()[:SPACE_NOTES_MAX]
    if "active" in body:
        out["active"] = body.get("active") is not False
    return out


# ─── Bookings: reading ────────────────────────────────────────────────

def _names(biz_id: str, rows: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Who each booking is for (a contact's name) and who booked it."""
    cids = sorted({str(r["contact_id"]) for r in rows if r.get("contact_id")})
    people: Dict[str, str] = {}
    if cids:
        got = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(c) for c in cids)})&select=id,name&limit=500")
        people = {str(c["id"]): _plain(c.get("name")) for c in got or [] if isinstance(c, dict)}
    by: Dict[str, str] = {}
    if any(r.get("booked_by") for r in rows):
        seats = sb_clients.sb_get_as_service(
            f"/business_users?business_id=eq.{_q(biz_id)}&status=eq.active&select=user_id,invited_email&limit=500")
        by = {str(s["user_id"]): str(s.get("invited_email") or "") for s in seats or [] if isinstance(s, dict)}
    return people, by


def _bills(biz_id: str, ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    want = sorted({str(i) for i in ids if i})
    if not want:
        return {}
    rows = _need(f"/invoices?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(i) for i in want)})"
                 "&select=id,invoice_number,status,total,paid_at,due_date,sent_at&limit=500")
    return {str(r["id"]): r for r in rows}


def bill_state(inv: Optional[Dict[str, Any]], today: date) -> str:
    """none | draft | sent | overdue | paid | void, for the Rentals page."""
    if not inv:
        return "none"
    st = str(inv.get("status") or "draft")
    if st == "paid":
        return "paid"
    if st in ("void", "cancelled"):
        return "void"
    if st == "draft":
        return "draft"
    due = str(inv.get("due_date") or "")[:10]
    return "overdue" if st == "overdue" or (due and due < today.isoformat()) else "sent"


def shown(me: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bookings as this login sees them: names filled in; a rental's money
    (and its bill) only for the owner and admins."""
    if not rows:
        return []
    biz = str(me["biz"]["id"])
    owner = str(me["biz"].get("owner_id") or "")
    people, by = _names(biz, rows)
    money = me["role"] in FINANCE
    try:
        bills: Optional[Dict[str, Dict[str, Any]]] = _bills(biz, (r.get("invoice_id") for r in rows)) if money else {}
    except HTTPException:
        bills = None   # the bookings still show; a bill that couldn't be read says so
    today = _now().date()
    out = []
    for r in rows:
        row = dict(r)
        uid = str(r.get("booked_by") or "")
        row["for_name"] = people.get(str(r.get("contact_id") or "")) or None
        row["by_name"] = ("The owner" if uid and uid == owner else by.get(uid) or ("Someone who left" if uid else None))
        row["mine"] = bool(uid) and uid == me["uid"]
        if money:
            inv = (bills or {}).get(str(r.get("invoice_id") or ""))
            row["bill"] = ({"id": inv["id"], "number": inv.get("invoice_number"), "status": bill_state(inv, today),
                            "total": inv.get("total"), "paid_at": inv.get("paid_at"), "due_date": inv.get("due_date")}
                           if inv else {"id": r["invoice_id"], "status": "unread"} if bills is None and r.get("invoice_id")
                           else None)
        else:
            for k in MONEY_FIELDS:
                row.pop(k, None)
        out.append(row)
    return out


def _booking(biz_id: str, booking_id: Any) -> Dict[str, Any]:
    rows = _need(f"/church_space_bookings?id=eq.{_q(_uuid(booking_id, 'booking'))}&business_id=eq.{_q(biz_id)}"
                 f"&select={BOOKING_FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That booking isn't here.")
    return rows[0]


# ─── Clashes ──────────────────────────────────────────────────────────

def clashes(biz_id: str, space_id: str, times: List[Tuple[datetime, datetime]],
            skip: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """The BOOKED bookings of this space that overlap any of `times`, each
    once, with the time of ours it meets."""
    if not times:
        return []
    lo = min(s for s, _ in times)
    hi = max(e for _, e in times)
    rows = _need(f"/church_space_bookings?business_id=eq.{_q(biz_id)}&space_id=eq.{_q(space_id)}&status=eq.booked"
                 f"&start_at=lt.{_q(_iso(hi))}&end_at=gt.{_q(_iso(lo))}"
                 "&select=id,title,start_at,end_at,series_id&order=start_at.asc&limit=1000")
    skip = {str(s) for s in skip}
    out = []
    for r in rows:
        if str(r.get("id")) in skip:
            continue
        rs, re_ = _at(r.get("start_at")), _at(r.get("end_at"))
        if not rs or not re_:
            continue
        hit = next((s for s, e in times if overlaps(s, e, rs, re_)), None)
        if hit is not None:
            out.append({"id": r["id"], "title": r.get("title"), "start_at": r.get("start_at"),
                        "end_at": r.get("end_at"), "on": _iso(hit)})
    return out


def clash_message(space_name: str, found: List[Dict[str, Any]], tz: ZoneInfo) -> str:
    first = found[0]
    s, e = _at(first["start_at"]), _at(first["end_at"])
    said = f"{space_name} is already booked then: {first.get('title') or 'a booking'}, {when_text(s, e, tz)}."
    if len(found) > 1:
        said += f" And {len(found) - 1} more {'time' if len(found) == 2 else 'times'} in this repeat."
    return said


def _refuse_clash(space: Dict[str, Any], found: List[Dict[str, Any]], tz: ZoneInfo) -> None:
    raise HTTPException(409, {"code": "clash", "message": clash_message(space["name"], found, tz), "clashes": found})


# ─── Bookings: writing ────────────────────────────────────────────────

def _when(v: Any, what: str) -> datetime:
    d = _at(v)
    if not d:
        raise HTTPException(400, f"Pick a {what} time.")
    return d


def _until(v: Any, start: datetime, tz: ZoneInfo) -> Optional[date]:
    if v in (None, ""):
        return None
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, "Pick the date the repeat ends.")
    if d < start.astimezone(tz).date():
        raise HTTPException(400, "The repeat ends before it starts.")
    return d


def _cents(v: Any, what: str) -> int:
    if v in (None, ""):
        return 0
    try:
        n = round(float(v) * 100)
    except (TypeError, ValueError):
        raise HTTPException(400, f"The {what} is an amount in dollars.")
    if not 0 <= n <= MONEY_MAX_CENTS:
        raise HTTPException(400, f"The {what} is an amount in dollars.")
    return int(n)


def _email(v: Any) -> Optional[str]:
    e = str(v or "").strip().lower()
    if not e:
        return None
    if len(e) > 200 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
        raise HTTPException(400, "That email doesn't look right.")
    return e


def _contact(biz_id: str, v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    cid = _uuid(v, "person")
    if not _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&select=id&limit=1"):
        raise HTTPException(400, "That person isn't one of this church's people.")
    return cid


def booking_fields(me: Dict[str, Any], body: Dict[str, Any], *, partial: bool,
                   was: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The checked fields of a new booking (or the ones an edit changes)."""
    biz = str(me["biz"]["id"])
    out: Dict[str, Any] = {}
    if not partial or "space_id" in body:
        space = _space(biz, body.get("space_id"))
        if not space.get("active") and (not was or str(was.get("space_id")) != str(space["id"])):
            raise HTTPException(400, f"{space['name']} isn't in use any more.")
        out["space_id"] = space["id"]
    if not partial or "title" in body:
        title = _plain(body.get("title"))[:TITLE_MAX]
        if not title:
            raise HTTPException(400, "Say what it's for: a title, like “Johnson family meal”.")
        out["title"] = title
    if not partial or "start_at" in body or "end_at" in body:
        start = _when(body.get("start_at", (was or {}).get("start_at")), "start")
        end = _when(body.get("end_at", (was or {}).get("end_at")), "end")
        if end <= start:
            raise HTTPException(400, "The end comes after the start.")
        if end - start > timedelta(days=MAX_DAYS):
            raise HTTPException(400, "One booking runs two weeks at most. Use a weekly repeat for longer.")
        if end <= _now():
            raise HTTPException(400, "That time has already passed.")
        out["start_at"], out["end_at"] = _iso(start), _iso(end)
    if "contact_id" in body:
        out["contact_id"] = _contact(biz, body.get("contact_id"))
    if "notes" in body:
        out["notes"] = str(body.get("notes") or "").strip()[:NOTES_MAX]
    if not partial or "kind" in body:
        kind = body.get("kind") or "use"
        if kind not in ("use", "rental"):
            raise HTTPException(400, "A booking is the church's own, or a rental.")
        out["kind"] = kind
    for k in ("renter_name", "renter_phone"):
        if k in body:
            out[k] = _plain(body.get(k))[:120] or None
    if "renter_email" in body:
        out["renter_email"] = _email(body.get("renter_email"))
    for k, what in (("fee", "fee"), ("deposit", "deposit")):
        if k in body:
            cents = _cents(body.get(k), what)
            if me["role"] not in FINANCE:
                if cents:
                    raise HTTPException(403, "Only the owner or an admin sets a rental's fee and deposit.")
                continue
            out[f"{k}_cents"] = cents
    return out


def _times(me: Dict[str, Any], fields: Dict[str, Any], body: Dict[str, Any]) -> Tuple[List[Tuple[datetime, datetime]], Optional[date], ZoneInfo]:
    tz = _tz(me, body.get("tz"))
    start, end = _at(fields["start_at"]), _at(fields["end_at"])
    until = _until(body.get("repeat_until"), start, tz)
    return expand_weekly(start, end, until, tz), until, tz


def book(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """A new booking, and its weekly repeats: all of them or none."""
    _may(me, WRITERS, "Your login can look at the rooms but not book them.")
    biz = str(me["biz"]["id"])
    fields = booking_fields(me, body, partial=False)
    times, until, tz = _times(me, fields, body)
    wanted = body.get("status") or "booked"
    if wanted not in ("booked", "requested"):
        raise HTTPException(400, "A new booking is booked, or asked for.")
    status = wanted if me["role"] in APPROVERS else "requested"
    space = _space(biz, fields["space_id"])
    found = clashes(biz, space["id"], times)
    if found:
        _refuse_clash(space, found, tz)
    series = str(uuid.uuid4()) if len(times) > 1 else None
    now = _iso(_now())
    rows = [{**fields, "id": str(uuid.uuid4()), "business_id": biz, "start_at": _iso(s), "end_at": _iso(e),
             "booked_by": me["uid"], "status": status, "series_id": series,
             "repeat_until": until.isoformat() if until and series else None,
             "decided_by": me["uid"] if status == "booked" else None,
             "decided_at": now if status == "booked" else None, "created_at": now, "updated_at": now}
            for s, e in times]
    saved = sb_clients.sb_post_as_service("/church_space_bookings", rows)
    if not isinstance(saved, list) or not saved:
        # Someone may have booked it in the moment between: the table's
        # exclusion constraint refused the insert. Say so plainly.
        found = clashes(biz, space["id"], times)
        if found:
            _refuse_clash(space, found, tz)
        raise HTTPException(503, "That booking didn't save. Try again.")
    return {"status": status, "bookings": shown(me, saved)}


def edit(me: Dict[str, Any], booking_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Change one booking. An approver changes any; anyone else only their
    own request. A rental that has its bill keeps its amounts."""
    biz = str(me["biz"]["id"])
    was = _booking(biz, booking_id)
    if me["role"] not in APPROVERS and not (str(was.get("booked_by")) == me["uid"] and was.get("status") == "requested"):
        raise HTTPException(403, "Only an admin changes a booking someone else made, or one that's booked.")
    if was.get("status") not in ("requested", "booked"):
        raise HTTPException(409, "That booking was declined or cancelled. Book it again instead.")
    fields = booking_fields(me, body, partial=True, was=was)
    if was.get("invoice_id") and any(k in fields and fields[k] != was.get(k) for k in ("fee_cents", "deposit_cents")):
        raise HTTPException(409, "This rental's bill is already made. Change the amount on the bill, in Bills.")
    if not fields:
        return {"bookings": shown(me, [was])}
    if any(k in fields for k in ("space_id", "start_at", "end_at")):
        space = _space(biz, fields.get("space_id", was["space_id"]))
        s, e = _at(fields.get("start_at", was["start_at"])), _at(fields.get("end_at", was["end_at"]))
        found = clashes(biz, space["id"], [(s, e)], skip=[was["id"]])
        if found:
            _refuse_clash(space, found, _tz(me, body.get("tz")))
    fields["updated_at"] = _iso(_now())
    got = sb_clients.sb_patch_as_service(
        f"/church_space_bookings?id=eq.{_q(was['id'])}&business_id=eq.{_q(biz)}&status=eq.{_q(was['status'])}", fields)
    if not isinstance(got, list):
        space = _space(biz, fields.get("space_id", was["space_id"]))
        found = clashes(biz, space["id"], [(_at(fields.get("start_at", was["start_at"])),
                                            _at(fields.get("end_at", was["end_at"])))], skip=[was["id"]])
        if found:
            _refuse_clash(space, found, _tz(me, body.get("tz")))
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "Someone changed this booking just now. Open it again.")
    return {"bookings": shown(me, got)}


def decide(me: Dict[str, Any], booking_id: str, status: Any, series: bool, tz_name: Any = None) -> Dict[str, Any]:
    """Approve (booked) or decline a request, or cancel a booking. With
    `series`, this one and the later ones in its weekly repeat."""
    biz = str(me["biz"]["id"])
    was = _booking(biz, booking_id)
    if status not in ("booked", "declined", "cancelled"):
        raise HTTPException(400, "A booking is approved, declined or cancelled.")
    if status in ("booked", "declined"):
        _may(me, APPROVERS, "Only the owner, an admin or a manager approves a booking.")
        frm = ("requested",)
    else:
        if me["role"] not in APPROVERS and str(was.get("booked_by")) != me["uid"]:
            raise HTTPException(403, "Only an admin cancels a booking someone else made.")
        frm = ("requested", "booked")
    if was.get("status") not in frm:
        raise HTTPException(409, "That booking was settled already.")
    rows = [was]
    if series and was.get("series_id"):
        rows = _need(f"/church_space_bookings?business_id=eq.{_q(biz)}&series_id=eq.{_q(was['series_id'])}"
                     f"&start_at=gte.{_q(_iso(_at(was['start_at'])))}&status=in.({','.join(frm)})"
                     f"&select={BOOKING_FIELDS}&order=start_at.asc&limit={MAX_REPEATS + 1}")
        if me["role"] not in APPROVERS:
            rows = [r for r in rows if str(r.get("booked_by")) == me["uid"]]
    ids = [str(r["id"]) for r in rows]
    if not ids:
        raise HTTPException(409, "That booking was settled already.")
    if status == "booked":
        space = _space(biz, was["space_id"])
        times = [(_at(r["start_at"]), _at(r["end_at"])) for r in rows]
        found = clashes(biz, space["id"], times, skip=ids)
        if found:
            _refuse_clash(space, found, _tz(me, tz_name))
    now = _iso(_now())
    patch = {"status": status, "decided_by": me["uid"], "decided_at": now, "updated_at": now}
    got = sb_clients.sb_patch_as_service(
        f"/church_space_bookings?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})"
        f"&status=in.({','.join(frm)})", patch)
    if not isinstance(got, list):
        if status == "booked":
            space = _space(biz, was["space_id"])
            found = clashes(biz, space["id"], [(_at(r["start_at"]), _at(r["end_at"])) for r in rows], skip=ids)
            if found:
                _refuse_clash(space, found, _tz(me, tz_name))
        raise HTTPException(503, "That didn't save. Try again.")
    if not got:
        raise HTTPException(409, "That booking was settled already.")
    rows = shown(me, sorted(got, key=lambda r: str(r.get("start_at"))))
    # A cancelled rental's bill stays a bill until someone voids it in Bills:
    # the app names it, so it isn't sent or chased by mistake.
    left = [r["bill"] for r in rows if status == "cancelled" and isinstance(r.get("bill"), dict)
            and r["bill"].get("status") in ("draft", "sent", "overdue")]
    return {"bookings": rows, "bills_left": left}


# ─── Rentals: the bill ────────────────────────────────────────────────

def _next_number(biz_id: str) -> str:
    """The invoices' own numbering (InvoiceComposer, Chief): INV-YYYY-NNN,
    one past the year's highest, read as numbers (as text, INV-2026-1000
    sorts below INV-2026-999). Two bills made in the same moment can still
    share a number, as they can from the composer: the table doesn't
    forbid it, and the bill's id is what links it."""
    prefix = f"INV-{_now().year}-"
    rows = _need(f"/invoices?business_id=eq.{_q(biz_id)}&invoice_number=like.{_q(prefix)}%25"
                 "&select=invoice_number&limit=5000")
    seen = [int(m.group(1)) for r in rows
            if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", str(r.get("invoice_number") or "")))]
    return f"{prefix}{(max(seen) + 1 if seen else 1):03d}"


def _renter(biz_id: str, booking: Dict[str, Any]) -> Optional[str]:
    """The person the bill goes to: the booking's own, else the renter by
    email among the church's people, else a new person (a guest)."""
    if booking.get("contact_id"):
        return str(booking["contact_id"])
    email = (booking.get("renter_email") or "").strip().lower()
    if not email:
        return None
    import church_areas
    found = _need(f"/contacts?business_id=eq.{_q(biz_id)}&email=ilike.{_q(church_areas._escape_ilike(email))}"
                  "&select=id&limit=1")
    if found:
        return str(found[0]["id"])
    made = sb_clients.sb_post_as_service("/contacts", {
        "business_id": biz_id, "name": _plain(booking.get("renter_name")) or email.split("@")[0], "email": email,
        **({"phone": booking["renter_phone"]} if booking.get("renter_phone") else {}),
        "status": "lead", "source": "room_rental", "last_interaction": _iso(_now()),
    })
    if not isinstance(made, list) or not made:
        raise HTTPException(503, "The renter couldn't be added to your people just now. Try again.")
    return str(made[0]["id"])


def _category(settings: Dict[str, Any]) -> str:
    fin = settings.get("financial") if isinstance(settings.get("financial"), dict) else {}
    cats = fin.get("categories") if isinstance(fin.get("categories"), list) else None
    if not cats:
        return "Other"
    for c in cats:
        if isinstance(c, str) and "rent" in c.lower():
            return c
    return "Other" if "Other" in cats else str(cats[0])


def bill(me: Dict[str, Any], booking_id: str, tz_name: Any = None) -> Dict[str, Any]:
    """Make a rental's bill once, as a draft invoice linked to the booking.
    Its id is fixed by the booking (and the bill it replaces, if that one was
    voided), so two presses, or a press after a failed link, make one bill.
    The app sends it the way it sends every bill."""
    _may(me, FINANCE, "Only the owner or an admin bills a rental.")
    biz_row = me["biz"]
    biz = str(biz_row["id"])
    b = _booking(biz, booking_id)
    if b.get("kind") != "rental":
        raise HTTPException(400, "Only a rental is billed. Mark it as a rental first.")
    if b.get("status") != "booked":
        raise HTTPException(409, "Book it first: a request isn't billed.")
    have = _bills(biz, [b.get("invoice_id")]).get(str(b.get("invoice_id") or ""))
    if have and bill_state(have, _now().date()) != "void":
        return {"created": False, "invoice_id": have["id"], "bookings": shown(me, [b])}
    fee, deposit = int(b.get("fee_cents") or 0), int(b.get("deposit_cents") or 0)
    if fee + deposit <= 0:
        raise HTTPException(400, "Set the fee or the deposit first.")
    inv_id = str(uuid.uuid5(BILL_NS, f"{b['id']}:{b.get('invoice_id') or ''}"))
    exists = _need(f"/invoices?id=eq.{_q(inv_id)}&business_id=eq.{_q(biz)}&select=id&limit=1")
    created = False
    contact_id = _renter(biz, b)
    if not exists:
        if not contact_id:
            raise HTTPException(400, "Add the renter's email, or pick them from your people, so the bill has somewhere to go.")
        space = _space(biz, b["space_id"])
        tz = _tz(me, tz_name)
        start, end = _at(b["start_at"]), _at(b["end_at"])
        when = when_text(start, end, tz)
        items = [{"description": f"{space['name']} rental: {b.get('title')} ({when})", "quantity": 1,
                  "unit_price": fee / 100, "total": fee / 100}] if fee else []
        if deposit:
            items.append({"description": "Deposit", "quantity": 1, "unit_price": deposit / 100, "total": deposit / 100})
        total = round((fee + deposit) / 100, 2)
        settings = biz_row.get("settings") if isinstance(biz_row.get("settings"), dict) else {}
        fin = settings.get("financial") if isinstance(settings.get("financial"), dict) else {}
        today = _now().date()
        due = max(today, min(start.astimezone(tz).date(), today + timedelta(days=14)))
        saved = sb_clients.sb_post_as_service("/invoices", {
            "id": inv_id, "business_id": biz, "contact_id": contact_id,
            "invoice_number": _next_number(biz), "status": "draft",
            "items": items, "subtotal": total, "tax_rate": 0, "tax_amount": 0, "total": total,
            "currency": fin.get("currency") or "USD", "category": _category(settings),
            "summary": f"{space['name']} rental", "due_date": due.isoformat(),
            "notes": f"Rental of {space['name']}, {when}.",
            "stripe_payment_url": ((settings.get("payments") or {}).get("stripe_link") or None)
            if isinstance(settings.get("payments"), dict) else None,
            "is_recurring": False,
        })
        if isinstance(saved, list) and saved:
            created = True
        elif not _need(f"/invoices?id=eq.{_q(inv_id)}&business_id=eq.{_q(biz)}&select=id&limit=1"):
            raise HTTPException(503, "The bill didn't save. Try again.")
    link = {"invoice_id": inv_id, "updated_at": _iso(_now())}
    if contact_id and not b.get("contact_id"):
        link["contact_id"] = contact_id
    got = sb_clients.sb_patch_as_service(
        f"/church_space_bookings?id=eq.{_q(b['id'])}&business_id=eq.{_q(biz)}", link)
    if not isinstance(got, list) or not got:
        raise HTTPException(503, "The bill was made but didn't link to the booking. Press Send the bill again.")
    return {"created": created, "invoice_id": inv_id, "bookings": shown(me, got)}


# ─── Routes ───────────────────────────────────────────────────────────

def _range(start: Any, end: Any) -> Tuple[datetime, datetime]:
    s, e = _when(start, "start"), _when(end, "end")
    if e <= s or e - s > timedelta(days=RANGE_DAYS):
        raise HTTPException(400, "Read up to two months at a time.")
    return s, e


@router.get("/status")
def spaces_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's office shows Rooms & spaces (and Rentals): the
    app asks once, so its menu offers them only where they open. Quietly
    false for a closed switch, a business that isn't a church, a login
    that doesn't work the office, or tables not made yet."""
    off = {"enabled": False, "book": False, "approve": False, "rentals": False}
    if not open_to(user):
        return off
    try:
        me = _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 503) or e.detail == "Rooms & spaces are for churches":
            return off
        raise
    if not _ready(str(me["biz"]["id"])):
        return off
    return {"enabled": True, **_can(me)}


@router.get("")
def spaces_list(business_id: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    return {"spaces": _spaces(str(me["biz"]["id"])), "me": _can(me)}


@router.post("")
def spaces_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    _may(me, APPROVERS, "Only the owner, an admin or a manager changes the list of spaces.")
    biz = str(me["biz"]["id"])
    fields = space_fields(body or {}, partial=False)
    have = [int(s.get("sort_order") or 0) for s in _spaces(biz)]
    now = _iso(_now())
    saved = sb_clients.sb_post_as_service("/church_spaces", {
        "notes": "", "active": True, **fields, "business_id": biz,
        "sort_order": max(have) + 1 if have else 0, "created_at": now, "updated_at": now})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"space": saved[0]}


@router.post("/order")
def spaces_order(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    _may(me, APPROVERS, "Only the owner, an admin or a manager changes the list of spaces.")
    biz = str(me["biz"]["id"])
    ids = [_uuid(i, "room") for i in ((body or {}).get("ids") or [])][:500]
    have = {str(s["id"]) for s in _spaces(biz)}
    if not ids or any(i not in have for i in ids):
        raise HTTPException(400, "Put this church's own spaces in order.")
    for n, sid in enumerate(ids):
        got = sb_clients.sb_patch_as_service(f"/church_spaces?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}",
                                             {"sort_order": n, "updated_at": _iso(_now())})
        if not isinstance(got, list):
            raise HTTPException(503, "The order didn't all save. Try again.")
    return {"spaces": _spaces(biz)}


@router.patch("/{space_id}")
def spaces_edit(space_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    _may(me, APPROVERS, "Only the owner, an admin or a manager changes the list of spaces.")
    biz = str(me["biz"]["id"])
    space = _space(biz, space_id)
    fields = space_fields(body or {}, partial=True)
    if not fields:
        return {"space": space}
    fields["updated_at"] = _iso(_now())
    got = sb_clients.sb_patch_as_service(f"/church_spaces?id=eq.{_q(space['id'])}&business_id=eq.{_q(biz)}", fields)
    if not isinstance(got, list) or not got:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"space": got[0]}


@router.get("/bookings")
def bookings_read(business_id: str, start: str, end: str, user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    biz = str(me["biz"]["id"])
    s, e = _range(start, end)
    rows = _need(f"/church_space_bookings?business_id=eq.{_q(biz)}&status=in.(requested,booked)"
                 f"&start_at=lt.{_q(_iso(e))}&end_at=gt.{_q(_iso(s))}&select={BOOKING_FIELDS}"
                 "&order=start_at.asc&limit=2000")
    waiting = _need(f"/church_space_bookings?business_id=eq.{_q(biz)}&status=eq.requested"
                    f"&end_at=gt.{_q(_iso(_now()))}&select={BOOKING_FIELDS}&order=start_at.asc&limit=300")
    return {"bookings": shown(me, rows), "requests": shown(me, waiting), "me": _can(me)}


@router.post("/check")
def bookings_check(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """What a booking would clash with, before it's saved."""
    body = body or {}
    me = _access(body.get("business_id"), user)
    biz = str(me["biz"]["id"])
    space = _space(biz, body.get("space_id"))
    start, end = _when(body.get("start_at"), "start"), _when(body.get("end_at"), "end")
    if end <= start:
        return {"clashes": [], "message": None}
    tz = _tz(me, body.get("tz"))
    times = expand_weekly(start, end, _until(body.get("repeat_until"), start, tz), tz)
    skip = [_uuid(body["booking_id"], "booking")] if body.get("booking_id") else []
    found = clashes(biz, space["id"], times, skip=skip)
    return {"clashes": found, "message": clash_message(space["name"], found, tz) if found else None,
            "times": len(times)}


@router.post("/bookings")
def bookings_add(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return book(me, body or {})


@router.patch("/bookings/{booking_id}")
def bookings_edit(booking_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    me = _access((body or {}).get("business_id"), user)
    return edit(me, booking_id, body or {})


@router.post("/bookings/{booking_id}/decide")
def bookings_decide(booking_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return decide(me, booking_id, body.get("status"), body.get("series") is True, body.get("tz"))


@router.post("/bookings/{booking_id}/bill")
def bookings_bill(booking_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    me = _access(body.get("business_id"), user)
    return bill(me, booking_id, body.get("tz"))


@router.get("/rentals")
def rentals_read(business_id: str, when: str = "upcoming", user: AuthedUser = Depends(require_user)):
    me = _access(business_id, user)
    _may(me, FINANCE, "Rentals carry money: the owner and admins keep them.")
    biz = str(me["biz"]["id"])
    now = _q(_iso(_now()))
    if when == "past":
        rows = _need(f"/church_space_bookings?business_id=eq.{_q(biz)}&kind=eq.rental&end_at=lte.{now}"
                     f"&select={BOOKING_FIELDS}&order=start_at.desc&limit=200")
    else:
        rows = _need(f"/church_space_bookings?business_id=eq.{_q(biz)}&kind=eq.rental&end_at=gt.{now}"
                     f"&select={BOOKING_FIELDS}&order=start_at.asc&limit=500")
    return {"rentals": shown(me, rows), "me": _can(me)}
