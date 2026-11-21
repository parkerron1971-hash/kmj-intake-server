"""event_volunteers.py — an event's volunteers: the engine (docs/EVENT_VOLUNTEERS.md,
step S2). Kevin, 2026-11-20: "when a event is made there should be questions
asked normal service volunteers or special volunteers. this is needed so people
can request for an amount of volunteers for their event", then "go" on the
proposal with all five calls as recommended.

The event (a Services & Events entry) stays the one home. Its regular
volunteers come from the Volunteers' serving teams through Who serves when, in
an ASK (event_volunteer_requests) with the event's own number for each place.
Whoever schedules the teams (sunday_planning._scheduler, then _team_gate for
the Volunteers' teams: the owner, an Admin, the serve_schedule holder) says yes
with one tap, and the yes makes the event date with those numbers
(worship_services.needs; sunday_planning.make_date, the one way an event date
is made). When the organizer can schedule the teams, it goes straight on.

    GET    /church/event-volunteers/status?business_id=      enabled, ready, can_ask, can_schedule,
                                                             the Volunteers' places, holder first names
    GET    /church/event-volunteers/{entry_id}?business_id=  the event's volunteer picture (spec 6.11)
    POST   /church/event-volunteers/{entry_id}/request       ask: {business_id, needs, note?}
    PATCH  /church/event-volunteers/{entry_id}/request       change a waiting ask's numbers or note
    DELETE /church/event-volunteers/{entry_id}/request?business_id=   take a waiting ask back
    POST   /church/event-volunteers/{entry_id}/changed       the event was saved: its date and ask follow (sync)
    PUT    /church/event-volunteers/{entry_id}/flyer         the flyer: an upload, or {business_id, artwork_id}
    DELETE /church/event-volunteers/{entry_id}/flyer?business_id=     take the flyer off

The scheduler's side lives on Who serves when (sunday_planning: GET
/planning/requests, POST /planning/requests/{id}/answer, PUT
/planning/dates/{id}/needs) and calls answer()/requests_list() here.

WHO (spec section 5): any office login reads (the owner, an Admin, a Manager,
and a Member or Viewer login that works the office by church_spaces._office's
rule). A Viewer reads only: asking is the part's refusal (403). Every route
checks the church itself (business_access.assert_access), independent of RLS.

THE SWITCH. EVENT_VOLUNTEERS = off | owner | on, owner when unset (the platform
owner's own church, member_asks.platform_church), and only where event dates
are open too (serve_dates.open_for: an ask's yes makes one). It gates asking,
changing an ask, answering, changing a date's numbers, Sunday-afternoon event
dates and typed dates becoming Services & Events entries. It never hides what
is already there: the picture, a date's numbers (serve_dates.needed applies
them everywhere) and taking a waiting ask back answer whatever it says.

BEFORE THE MIGRATION (supabase/APPLY-2026-11-21-event-volunteers.sql) ready()
is False: nothing selects worship_services.needs (serve_dates.fields), the
routes here and on Who serves when answer 404, and nothing is a 500.

NOTICES (spec 7.1, 7.2). Office logins are told through church_schedule_tell.
to_login (a push to the office app and an email to the sign-in address), each
notice claimed once in the request's own ledger (told_at for whoever schedules
the teams, answer_told_at for the organizer): the claim lands only while the
mark is empty, and is let go when nothing could be sent, so sweep_tick tries
again and nobody hears twice. Quiet hours hold a notice; they never drop it. A
take-back is told straight after the write and never again (no column claims
it). Only print(..., flush=True) reaches the logs, prefixed [event-volunteers].

S3 (around the event): following the event (sync, on save and in the sweep),
the flyer (upload, attach, take off; flyer_of() is the one validator every
reader goes through), a kids role's check (church_serving.cleared) and the
special helpers' hours (church_serving.event_credits).

S5 (Chief, chief_event_volunteers): Chief calls these routes' own functions as
the signed-in login, never a copy: enabled() and status() (the gate and the
places), ask_blocks() (the ask's checks before anything is written, shared
with ask()), gallery_reader()/_artwork(), attach_flyer() (the flyer route's
body, shared with put_flyer()), ask(), changed() and picture().
"""
from __future__ import annotations

import os
import re
import time as clock
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

import sb_clients
import serve_dates as sd
import sunday_planning as sp
from auth_supabase import AuthedUser, require_user

router = APIRouter(prefix="/church/event-volunteers", tags=["church"])

SWITCH = "EVENT_VOLUNTEERS"
TABLE = "event_volunteer_requests"
WAITING, ON, DECLINED, WITHDRAWN, CANCELLED = "waiting", "on", "declined", "withdrawn", "cancelled"
LIVE = (WAITING, ON)
MAX_PLACES = 60             # places one ask names at most (the database's event_needs_ok)
MAX_EACH = 50               # people one place asks for at most
NOTE_MAX = 300
DECIDED_DAYS = 7            # Who serves when lists the asks answered this long ago
SERVE_MINUTES, MINUTES_LO, MINUTES_HI = 120, 15, 720
SETTLE_SECONDS = 120        # the sweep leaves a notice this new to the write's own send
TELL_DAYS = 7               # a notice nobody could be sent in a week is left
READY_SECONDS = 600.0       # the column and table, once there, are asked about again in ten minutes
MISSING_SECONDS = 60.0      # not there (or couldn't tell): asked again a minute later
_STATE: Dict[str, Any] = {"yes": None, "at": 0.0}
# Tests pin the answer (conftest: False, so every other suite reads as before
# the migration); production leaves it None and asks the database.
_FORCE: Optional[bool] = None
FIELDS = ("id,business_id,entry_id,title,starts_at,place,needs,note,asked_by,asked_by_name,status,service_id,"
          "decided_by,decided_by_name,decided_at,decided_note,told_at,answer_told_at,created_at")
WHOEVER = "whoever schedules the teams"
OFFICE = "The office"
NOT_OFFICE = "Volunteers for events belong to the office. An admin can add the Office to your areas."
NO_EVENT = "That event isn't in Services & Events. Open it from Services & Events and try again."
ASKED = "This event already asked for volunteers. Change the numbers on it instead."
NO_ASK = "This event hasn't asked for volunteers yet. Ask for them first."
SUNDAY_CLASH = "That's during Sunday's service. Sunday services are already on Who serves when."
UNREAD = "The event's volunteers couldn't be read just now. Try again."
UNSAVED = "That didn't save. Try again."


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _ids(values: Iterable[Any]) -> str:
    return ",".join(_q(v) for v in sorted({str(v) for v in values if v}))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat()


def _at(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _read(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


PAGE = 1000          # the most rows one read returns (PostgREST's cap), whatever its limit says
MAX_ROWS = 100_000   # past this a read is refused, never cut short


def _read_all(path: str, order: str) -> List[Dict[str, Any]]:
    """Every row, a page at a time in a stable order (church_serving's own
    rule): a read the server caps is never taken for the whole, so a short
    read never reads as "nobody's on this date". A page that fails is a 503."""
    out: List[Dict[str, Any]] = []
    while True:
        rows = _read(f"{path}&order={order}&limit={PAGE}&offset={len(out)}")
        out += rows
        if len(rows) < PAGE:
            return out
        if len(out) >= MAX_ROWS:
            raise HTTPException(503, UNREAD)


def _first(name: Any) -> str:
    return _plain(name).split(" ")[0] if _plain(name) else ""


def the(title: Any) -> str:
    """"the Youth Lock-in"; a title that starts with "The" keeps its own."""
    t = _plain(title) or "event"
    return t if t.lower().startswith("the ") else f"the {t}"


def The(title: Any) -> str:
    """"The Youth Lock-in", to begin a sentence."""
    t = the(title)
    return t[:1].upper() + t[1:]


def clock_words(at: datetime) -> str:
    """"7:00 PM"."""
    return f"{at.hour % 12 or 12}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


# ─── the switch ──────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _platform_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def _church_switch(business_id: Any, user: Any = None) -> bool:
    m = mode()
    if m == "on":
        return True
    if m != "owner":
        return False
    if user is not None and (getattr(user, "email", None) or "").strip().lower() == _platform_email():
        return True
    try:
        import member_asks
        return member_asks.platform_church(business_id)
    except Exception:  # noqa: BLE001 — a lookup that fails is a no, never a 500
        return False


def open_for(business_id: Any, user: Any = None) -> bool:
    """Whether this church may ask for volunteers now: EVENT_VOLUNTEERS open
    for it (on, or owner and the platform owner's own church or login), and
    event dates open there too (an ask's yes makes one)."""
    return _church_switch(business_id, user) and sd.open_for(business_id, user)


def enabled(business_id: Any, user: Any = None) -> bool:
    """The status route's `enabled`, and Chief's (chief_event_volunteers):
    the migration in, Who serves when on, the switch open here for this
    login, and a church whose teams have owners. Who may ask is still each
    route's own gate (_login, the Viewer's refusal)."""
    return ready() and sp.mode() != "off" and open_for(business_id, user) and sp._office(business_id)


# ─── the column and the table ────────────────────────────────────────

def _missing(err: Optional[Dict[str, Any]]) -> bool:
    """PostgREST saying the column (42703) or the table (42P01, PGRST205, a
    404 of its own) isn't there."""
    if not err:
        return False
    code, msg = str(err.get("code") or ""), str(err.get("message") or "")
    return (code in ("42703", "42P01", "PGRST205") or "42703" in msg or "42P01" in msg
            or (err.get("status") == 404 and code.startswith("PGRST")))


def ready() -> bool:
    """True once worship_services.needs and event_volunteer_requests answer
    (one migration makes both). serve_dates.ready's rule: only "no such
    column" or "no such table" says they aren't; a blip keeps the last
    answer, and with none yet reads as not there."""
    if _FORCE is not None:
        return _FORCE
    if not sb_clients.sb_url():
        return False    # no database to ask (a script)
    now = clock.monotonic()
    yes, at = _STATE["yes"], _STATE["at"]
    if yes is not None and now - at < (READY_SECONDS if yes else MISSING_SECONDS):
        return yes
    got: Optional[bool] = None
    try:
        for path in ("/worship_services?select=needs&limit=1", f"/{TABLE}?select=id&limit=1"):
            rows = sb_clients.sb_get_as_service(path)
            if isinstance(rows, list):
                continue
            got = False if _missing(sb_clients.last_error()) else bool(yes)
            break
        else:
            got = True
    except Exception:  # noqa: BLE001 — a fake or a broken client is "couldn't tell"
        got = bool(yes)
    _STATE["yes"], _STATE["at"] = got, now
    return bool(got)


# ─── the flyer: the one reader (spec 6.12) ───────────────────────────

_COPY = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(-thumb)?\.jpg")


def flyer_of(data: Any, business_id: Any, entry_id: Any) -> Optional[Dict[str, Any]]:
    """The event's flyer, {url, thumb, w, h}, or None. `_flyer` sits in JSON
    the browser writes, so it is checked on every read: the full copy exactly
    {base}/storage/v1/object/public/business-assets/{business}/event-flyers/
    {entry}/{artwork}.jpg and the thumb the same with -thumb.jpg (one
    artwork, this church, this event; nothing before, between or after), and
    the size whole numbers from 1 to 8000. Anything else is no flyer, never
    an error. The office app reading data._flyer itself holds it to the same
    rule (spec 6.12)."""
    f = data.get("_flyer") if isinstance(data, dict) else None
    base = sb_clients.sb_url()
    if not isinstance(f, dict) or not base:
        return None
    try:
        b, e = str(uuid.UUID(str(business_id))), str(uuid.UUID(str(entry_id)))
    except (ValueError, TypeError):
        return None
    folder = f"{base}/storage/v1/object/public/business-assets/{b}/event-flyers/{e}/"
    out: Dict[str, Any] = {}
    art = None
    for key, thumb in (("url", False), ("thumb", True)):
        v = f.get(key)
        if not isinstance(v, str) or not v.startswith(folder):
            return None
        m = _COPY.fullmatch(v[len(folder):])
        if not m or bool(m.group(2)) != thumb or (art is not None and m.group(1) != art):
            return None
        art = m.group(1)
        out[key] = v
    for key in ("w", "h"):
        v = f.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 8000:
            return None
        out[key] = v
    return out


# ─── who is asking ───────────────────────────────────────────────────

def _login(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """An office login of a church whose teams have owners, with the
    migration in. 404: before the migration, Who serves when off, no seat
    here (business_access's own 404), not such a church. 403: a Member or
    Viewer login that doesn't work the office."""
    biz = sp._uuid(business_id)
    if not ready() or sp.mode() == "off":
        raise HTTPException(404, "Not Found")
    import business_access
    role = business_access.assert_access(biz, user, "viewer")
    if not sp._office(biz):
        raise HTTPException(404, "Not Found")
    if role not in ("owner", "admin", "manager"):
        import church_spaces
        if not church_spaces._office(biz, str(user.id), role):
            raise HTTPException(403, NOT_OFFICE)
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user}


def schedules(me: Dict[str, Any]) -> bool:
    """Whether this login schedules the Volunteers' teams: exactly the rule
    that changes them on Who serves when (sunday_planning._scheduler, then
    _team_gate for the Volunteers' teams)."""
    if me["role"] == "viewer":
        return False
    try:
        who = sp._scheduler(me["biz"], me["user"])
        sp._team_gate(me["biz"], who, sp.VOLUNTEERS)
        return True
    except HTTPException as e:
        if e.status_code in (402, 403):
            return False
        raise


def _ask_gate(me: Dict[str, Any]) -> None:
    """A Viewer reads and never asks: the part's refusal, as on Who serves when."""
    if me["role"] == "viewer":
        from worship_team import REFUSED
        raise HTTPException(403, REFUSED["serve"])


def _switch_gate(me: Dict[str, Any]) -> None:
    if not open_for(me["biz"], me["user"]):
        raise HTTPException(404, "Not Found")


def _business(biz: str) -> Dict[str, Any]:
    rows = _read(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def login_name(church: Dict[str, Any], uid: Any) -> str:
    """A login by the name a notice and a card can say: the owner by the
    church's own name for them; anyone else by their first name. Never an
    email address and never a stand-in: "The office" when there is no name."""
    import church_duties as cd
    biz, uid = str(church["id"]), str(uid or "")
    try:
        names = cd._names(biz, church, cd._seats(biz))
    except HTTPException:
        return OFFICE
    name = _plain(names.get(uid))
    if not name or "@" in name or name in ("An office login", "The account owner"):
        return OFFICE
    return name[:80] if uid == str(church.get("owner_id") or "") else cd._first(name)[:80]


def holders(church: Dict[str, Any]) -> List[str]:
    """Who is told of an ask: the logins holding the serve_schedule duty;
    the owner when nobody does. A read that fails tells the owner."""
    import church_duties as cd
    try:
        got = cd.manager_holders(str(church["id"]), "serve_schedule")
    except HTTPException:
        got = []
    if got:
        return got
    return [str(church["owner_id"])] if church.get("owner_id") else []


def holder_names(church: Dict[str, Any]) -> List[str]:
    """The first names of whoever holds the serve_schedule duty (the owner's
    and the admins' are never said: they aren't who the duty names)."""
    import church_duties as cd
    try:
        uids = cd.manager_holders(str(church["id"]), "serve_schedule")
    except HTTPException:
        return []
    return [n for n in (login_name(church, u) for u in uids) if n != OFFICE]


def _who_schedules(church: Dict[str, Any]) -> str:
    """"Laquesha", "Laquesha and Dee", or "whoever schedules the teams"."""
    return _join(holder_names(church)) or WHOEVER


# ─── the Volunteers' places, and an ask's numbers ────────────────────

def volunteer_places(biz: str) -> List[Dict[str, Any]]:
    """Every active place on this church's Volunteers' teams, in the teams'
    order: {id, name, needed (its Sunday number), group_id, team}.
    ChurchSavvy's worship and production places are never here."""
    serve = [s for s in sp._serve_rows(f"/serve_teams?business_id=eq.{_q(biz)}", "group_id,sort")
             if s["owner"] == sp.VOLUNTEERS]
    if not serve:
        return []
    names = {str(g["id"]): _plain(g.get("name")) or "A team" for g in _read(
        f"/groups?business_id=eq.{_q(biz)}&id=in.({_ids(s['group_id'] for s in serve)})&kind=eq.team"
        f"&active=eq.true&select=id,name")}
    sort = {str(s["group_id"]): int(s.get("sort") or 0) for s in serve}
    if not names:
        return []
    out = []
    for p in _read(f"/serve_positions?business_id=eq.{_q(biz)}&group_id=in.({_ids(names)})&active=eq.true"
                   f"&select=id,group_id,name,needed,sort,created_at&order=sort.asc,created_at.asc"):
        gid = str(p["group_id"])
        n = p.get("needed")
        out.append({"id": str(p["id"]), "name": _plain(p.get("name")) or "A place",
                    "needed": n if isinstance(n, int) and not isinstance(n, bool) and n >= 1 else 1,
                    "group_id": gid, "team": names[gid],
                    "_order": (sort.get(gid, 0), names[gid].lower(), int(p.get("sort") or 0),
                               str(p.get("created_at") or ""), str(p["id"]))})
    out.sort(key=lambda p: p["_order"])
    return [{k: v for k, v in p.items() if k != "_order"} for p in out]


def sunday_numbers(places: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """Every Volunteers place at its Sunday number (what needs: null means),
    in an ask's shape; None when there's nothing to say or more than an ask
    can hold."""
    out = {p["id"]: min(p["needed"], MAX_EACH) for p in places}
    return out if 0 < len(out) <= MAX_PLACES else None


def clean_needs(biz: str, raw: Any, places: List[Dict[str, Any]]) -> Dict[str, int]:
    """An ask's numbers: 1 to 60 places, each an active place on one of this
    church's Volunteers' teams, each a whole number from 1 to 50. A place
    that isn't one (ChurchSavvy's, another church's, retired) is a 400 that
    names it."""
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(400, "Tick at least one place, or untick Our regular serving teams.")
    if len(raw) > MAX_PLACES:
        raise HTTPException(400, f"Ask for {MAX_PLACES} places at most.")
    by_id = {p["id"]: p for p in places}
    out: Dict[str, int] = {}
    for key, n in raw.items():
        try:
            pid = str(uuid.UUID(str(key)))
        except (ValueError, TypeError):
            raise HTTPException(400, "That place isn't one of the Volunteers' places. Pick from the serving teams.")
        place = by_id.get(pid)
        if not place:
            got = sb_clients.sb_get_as_service(
                f"/serve_positions?id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&select=name&limit=1")
            name = _plain(got[0].get("name")) if isinstance(got, list) and got else ""
            raise HTTPException(400, f"{name} isn't one of the Volunteers' places. Pick from the serving teams."
                                if name else "That place isn't one of the Volunteers' places. Pick from the serving teams.")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_EACH:
            raise HTTPException(400, f"Give {place['name']} a number from 1 to {MAX_EACH}.")
        out[pid] = n
    return out


def _note(raw: Any) -> str:
    note = _plain(raw)
    if len(note) > NOTE_MAX:
        raise HTTPException(400, f"Keep the note to {NOTE_MAX} letters.")
    return note


def needs_words(needs: Dict[str, Any], places: List[Dict[str, Any]], before: Optional[Dict[str, Any]] = None) -> str:
    """"2 on Greeters, 1 on Parking and 4 on Kids rooms", in the teams'
    order. With `before` (what was asked), only what changed: "3 on Kids
    rooms instead of 4", "nobody on Parking instead of 1"."""
    by_id = {p["id"]: p for p in places}
    order = {p["id"]: n for n, p in enumerate(places)}
    now_, was_ = needs or {}, before or {}
    keys = sorted(set(now_) | (set(was_) if before is not None else set()), key=lambda k: (order.get(k, len(order)), k))
    out = []
    for pid in keys:
        name = by_id[pid]["name"] if pid in by_id else "a place that's gone"
        n, was = int(now_.get(pid, 0) or 0), int(was_.get(pid, 0) or 0)
        if before is None:
            out.append(f"{n} on {name}")
        elif n != was:
            out.append(f"{n} on {name} instead of {was}" if n else f"nobody on {name} instead of {was}")
    return _join(out)


# ─── the event ───────────────────────────────────────────────────────

def event_entry(biz: str, entry_id: str, zone, read=None) -> Dict[str, Any]:
    """One of this church's Services & Events entries (an event_roster
    room's): its title, day and time on the church's clock (`at` is None for
    a bare date), place, data and roles. 404 for anything else. `read` is
    who reads it: the server (_read) unless Chief hands it the login's own
    reader (chief_event_volunteers, where this picture's gate can't apply)."""
    read = read or _read
    rows = read(f"/module_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(biz)}"
                f"&select=id,module_id,status,data&limit=1")
    if not rows:
        raise HTTPException(404, NO_EVENT)
    e = rows[0]
    mods = read(f"/custom_modules?id=eq.{_q(e.get('module_id'))}&business_id=eq.{_q(biz)}"
                f"&archetype=eq.event_roster&select=id,archetype_params,is_active&limit=1")
    if not mods:
        raise HTTPException(404, NO_EVENT)
    return entry_view(e, mods[0], zone)


def entry_view(e: Dict[str, Any], mod: Dict[str, Any], zone) -> Dict[str, Any]:
    """One entry of an events room, as event_entry() gives it."""
    import church_leaders_note as cln
    import events_rsvp_router as ev
    f = ev.resolve_fields(mod.get("archetype_params"))
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    day, at = cln._when_of(data.get(f["date_field"]), zone)
    return {"entry_id": str(e["id"]), "module_id": str(mod["id"]),
            "active": e.get("status") == "active" and mod.get("is_active") is not False,
            "title": _plain(data.get(f["title_field"]))[:120] or "An event", "day": day, "at": at,
            "place": _plain(data.get(f["location_field"]))[:120], "data": data,
            "roles": ev.occasion_roles(data, f["roles"]), "signups_field": f["signups_field"]}


def upcoming_gate(ent: Dict[str, Any], now: datetime) -> None:
    """An event one may ask for: active, with a start time, still to come,
    and within EVENT_AHEAD_DAYS."""
    if not ent["active"]:
        raise HTTPException(404, NO_EVENT)
    if ent["at"] is None:
        raise HTTPException(400, "Give the event a start time first.")
    if ent["at"] <= now:
        raise HTTPException(400, f"{The(ent['title'])} has already happened.")
    if ent["day"] > now.date() + timedelta(days=sp.EVENT_AHEAD_DAYS):
        raise HTTPException(400, f"{The(ent['title'])} is more than {sp.EVENT_AHEAD_DAYS // 30} months "
                                 "away. Ask for volunteers when it's closer.")


def ask_blocks(biz: str, ent: Dict[str, Any], now: datetime, zone) -> None:
    """What stops an ask before anything is written (spec 6.1), in the ask's
    own words: the event upcoming (a start time, not past, within
    EVENT_AHEAD_DAYS), not during a Sunday service, and, for an event that
    is saved, no live ask and not on Who serves when another way. The ask
    route asks it, and so does Chief's look before saving
    (chief_event_volunteers), on the event as it is about to be saved."""
    upcoming_gate(ent, now)
    if sd.is_sunday(ent["at"]) and sp.during_sunday_service(biz, ent["at"], zone):
        raise HTTPException(400, SUNDAY_CLASH)
    eid = ent.get("entry_id")
    if not eid:
        return
    if live_request(biz, eid):
        raise HTTPException(409, ASKED)
    if live_date(biz, eid):
        # Made the November 17 way, with no ask: its numbers are changed there.
        who = _who_schedules(_business(biz))
        raise HTTPException(409, f"This event is already on Who serves when. {who[:1].upper()}{who[1:]} can change "
                                 "its numbers there.")


def _requests_of(biz: str, entry_id: str, live: bool = True) -> List[Dict[str, Any]]:
    status = f"&status=in.({','.join(LIVE)})" if live else ""
    return _read(f"/{TABLE}?business_id=eq.{_q(biz)}&entry_id=eq.{_q(entry_id)}{status}"
                 f"&select={FIELDS}&order=created_at.desc&limit=20")


def live_request(biz: str, entry_id: str) -> Optional[Dict[str, Any]]:
    rows = _requests_of(biz, entry_id)
    return rows[0] if rows else None


def live_date(biz: str, entry_id: str) -> Optional[Dict[str, Any]]:
    """The event date made for this event and still on Who serves when."""
    rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&event_entry_id=eq.{_q(entry_id)}&kind=eq.{sd.EVENT}"
                 f"&archived_at=is.null&is_template=eq.false&select=id,title,starts_at{sd.fields()}&limit=1")
    return rows[0] if rows else None


def _request_row(biz: str, rid: str) -> Dict[str, Any]:
    rows = _read(f"/{TABLE}?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&select={FIELDS}&limit=1")
    if not rows:
        raise HTTPException(404, "That ask isn't here anymore.")
    return rows[0]


def _request_out(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(r["id"]), "status": r.get("status"), "needs": r.get("needs") or {}, "note": r.get("note") or "",
            "asked_by_name": r.get("asked_by_name") or "", "decided_by_name": r.get("decided_by_name") or "",
            "decided_note": r.get("decided_note") or "", "decided_at": r.get("decided_at"),
            "service_id": str(r["service_id"]) if r.get("service_id") else None,
            "entry_id": str(r["entry_id"]) if r.get("entry_id") else None, "title": r.get("title") or "",
            "starts_at": r.get("starts_at"), "place": r.get("place") or ""}


def _saved(got: Any) -> Dict[str, Any]:
    if not isinstance(got, list) or not got:
        raise HTTPException(503, UNSAVED)
    return got[0]


def _after(what: str, church: Dict[str, Any], row: Dict[str, Any], **kw: Any) -> None:
    """Hand a notice on once the write has landed: off this request
    (member_push._later), never able to fail the write it follows. The sweep
    tells an ask or an answer that was missed; a take-back is not tried
    again."""
    try:
        import member_push
        church, row = dict(church), dict(row)
        fn = globals()[what]
        member_push._later(lambda: fn(church, row, **kw))
    except Exception:  # noqa: BLE001 — a notice is never worth failing the write it is about
        print(f"[event-volunteers] {str(church.get('id'))[:8]}: a notice wasn't handed on ({what})", flush=True)


# ─── the routes: status, the picture, asking ─────────────────────────

@router.get("/status")
def status(business_id: str, user: AuthedUser = Depends(require_user)):
    """What the New event questions need: whether asking is open here, what
    this login may do, the Volunteers' places at their Sunday numbers, and
    who schedules the teams. Before the migration, or with the switch closed
    for this church, only {enabled: false, ready}."""
    biz = sp._uuid(business_id)
    import business_access
    business_access.assert_access(biz, user, "viewer")
    if not enabled(biz, user):
        return {"enabled": False, "ready": ready(), "can_ask": False, "can_schedule": False, "teams": [],
                "holders": []}
    me = _login(biz, user)
    church = _business(biz)
    teams: Dict[str, Dict[str, Any]] = {}
    for p in volunteer_places(biz):
        t = teams.setdefault(p["group_id"], {"group_id": p["group_id"], "name": p["team"], "places": []})
        t["places"].append({"id": p["id"], "name": p["name"], "needed": p["needed"]})
    return {"enabled": True, "ready": True, "can_ask": me["role"] != "viewer", "can_schedule": schedules(me),
            "teams": list(teams.values()), "holders": holder_names(church)}


def _may_read_names(me: Dict[str, Any]) -> bool:
    """Who serves when's own reading rule: its switch open to this login and
    a part there (worship_team.roles_of, Planning's part)."""
    if not sp.open_to(me["user"]):
        return False
    try:
        from worship_team import roles_of
        roles_of(me["biz"], me["user"], part="planning")
        return True
    except HTTPException as e:
        if e.status_code in (402, 403, 404):
            return False
        raise


def _minutes(data: Dict[str, Any]) -> int:
    v = data.get("_serve_minutes") if isinstance(data, dict) else None
    if not isinstance(v, int) or isinstance(v, bool):
        return SERVE_MINUTES
    return max(MINUTES_LO, min(MINUTES_HI, v))


def serve_minutes(data: Any) -> int:
    """A special helper's minutes for one event: _serve_minutes, 120 by
    default, held to 15 to 720."""
    return _minutes(data if isinstance(data, dict) else {})


# What the event page says of someone on a kids role without a current
# check, by their check's own state (church_serving.checks_of).
CHECK_WORDS = {"overdue": "Check overdue", "none": "No check on file", "blocked": "No check on file",
               "teen": "Under 18"}


def _kids_checks(biz: str, user: AuthedUser, roles: List[Dict[str, Any]],
                 signups: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Each person on this event's kids roles and their check's state
    (church_serving.checks_of: ok, due, overdue, none, blocked, teen), or
    None when this login may not read who's cleared (church_serving._access's
    `checks`) or there is no kids role with a person on it."""
    kids = {str(r.get("id")) for r in roles if r.get("kids") is True}
    cids = {str(s["contact_id"]) for s in signups if s.get("contact_id") and s.get("role") in kids}
    if not cids:
        return None
    import church_serving as cs
    try:
        access = cs._access(biz, user)
    except HTTPException:
        return None
    if not access.get("checks"):
        return None
    try:
        today = _now().astimezone(cs._zone(biz)).date()
        got = cs.checks_of(access["biz"], cids, today)
    except HTTPException:
        return None
    return {cid: (got.get(cid) or {}).get("status") or "none" for cid in cids}


def _check_marks(status: Optional[str]) -> Dict[str, Any]:
    """{checked, check}: whether the check is current (church_serving.CLEARED)
    and, when it isn't, why ("Check overdue", "No check on file", "Under 18")."""
    import church_serving as cs
    ok = status in cs.CLEARED
    return {"checked": ok, "check": None if ok else CHECK_WORDS.get(status or "none", "No check on file")}


@router.get("/{entry_id}")
def picture(entry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """The event's volunteers, both kinds, in one picture (spec 6.11). The
    switch never hides it: people were asked and need to know."""
    me = _login(business_id, user)
    biz = me["biz"]
    eid = sp._uuid(entry_id, "event")
    zone = sp._zone(biz)
    ent = event_entry(biz, eid, zone)
    reqs = sorted(_requests_of(biz, eid, live=False), key=lambda r: str(r.get("created_at") or ""), reverse=True)
    # The live ask; else the latest, so a no and its note still read.
    req = next((r for r in reqs if r.get("status") in LIVE), reqs[0] if reqs else None)
    svc = live_date(biz, eid)
    places = volunteer_places(biz)
    names_ok = _may_read_names(me)
    teams: List[Dict[str, Any]] = []
    if svc:
        rows = _read(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(svc['id'])}"
                     f"&select=position_id,slot,contact_id,status")
        held = {(str(r["position_id"]), int(r.get("slot") or 1)): r for r in rows}
        who: Dict[str, Dict[str, Any]] = {}
        if names_ok:
            who = sp._people(biz, [r.get("contact_id") for r in rows if r.get("status") in ("asked", "yes")])
        for p in places:
            n = sd.needed(svc, p)
            if n < 1:
                continue
            slots = []
            for k in range(1, n + 1):
                r = held.get((p["id"], k))
                state = r["status"] if r and r.get("status") in ("asked", "yes") and r.get("contact_id") else "open"
                slot: Dict[str, Any] = {"slot": k, "state": state}
                if state != "open" and names_ok:
                    slot["name"] = (who.get(str(r["contact_id"])) or {}).get("name") or "Someone"
                slots.append(slot)
            teams.append({"place_id": p["id"], "name": p["name"], "team": p["team"], "needed": n, "slots": slots})
    elif req and req.get("status") == WAITING:
        asked = req.get("needs") or {}
        for p in places:
            n = int(asked.get(p["id"], 0) or 0)
            if n > 0:
                teams.append({"place_id": p["id"], "name": p["name"], "team": p["team"], "needed": n, "pending": True,
                              "slots": [{"slot": k, "state": "open"} for k in range(1, n + 1)]})
    import events_rsvp_router as ev
    signups = ev.read_signups(ent["data"], ent["signups_field"])
    # A kids role's people carry `checked` and, when it isn't current, `check`
    # ("Check overdue", "No check on file", "Under 18"; spec 6.10) for a login
    # that may read who's cleared, by church_serving's own rule, and nobody else.
    checks = _kids_checks(biz, me["user"], ent["roles"], signups)
    special = []
    for role in ent["roles"]:
        fill = ev.role_fill(role, signups)
        kids = role.get("kids") is True
        people = [{"name": _plain(s.get("name")) or "Someone",
                   **({"contact_id": str(s["contact_id"])} if s.get("contact_id") else {}),
                   **(_check_marks(checks.get(str(s["contact_id"]))) if kids and checks is not None
                      and s.get("contact_id") else {})}
                  for s in signups if s.get("role") == role.get("id") and (s.get("status") or "yes") == "yes"]
        special.append({"role_id": str(role.get("id")), "label": fill["label"], "needed": fill["needed"],
                        "kids": kids, "open": role.get("open") is True, "people": people})
    t_need = sum(t["needed"] for t in teams)
    t_yes = sum(1 for t in teams for s in t["slots"] if s["state"] == "yes")
    s_need = sum(s["needed"] for s in special)
    s_yes = sum(min(len(s["people"]), s["needed"]) for s in special)
    return {
        "request": None if not req else {
            "id": str(req["id"]), "status": req.get("status"), "needs": req.get("needs") or {},
            "note": req.get("note") or "", "asked_by_name": req.get("asked_by_name") or "",
            "decided_by_name": req.get("decided_by_name") or "", "decided_note": req.get("decided_note") or "",
            # Whether this login may change or take back the ask (the PATCH and
            # DELETE rule: the one who asked, or whoever schedules the teams;
            # never a Viewer), so the page offers only what the server allows.
            "can_change": me["role"] != "viewer" and _mine_or_scheduler(me, req)},
        "date": None if not svc else {"service_id": str(svc["id"]), "starts_at": svc.get("starts_at"),
                                      "needs": svc.get("needs") if isinstance(svc.get("needs"), dict) else None},
        "teams": teams,
        "special": special,
        "counts": {"all": t_need + s_need, "yes": t_yes + s_yes, "teams_needed": t_need, "teams_yes": t_yes,
                   "special_needed": s_need, "special_yes": s_yes},
        "flyer": flyer_of(ent["data"], biz, eid),
        "serve_minutes": _minutes(ent["data"]),
    }


@router.post("/{entry_id}/request")
def ask(entry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Ask the serving teams for the event's numbers (spec 6.1). From
    whoever schedules the teams it goes straight on: the event date is made
    with these numbers (sunday_planning.make_date) and the ask is on. From
    anyone else it waits for their one tap."""
    body = body or {}
    me = _login(body.get("business_id"), user)
    _ask_gate(me)
    _switch_gate(me)
    biz = me["biz"]
    eid = sp._uuid(entry_id, "event")
    zone = sp._zone(biz)
    now = sp._now().astimezone(zone)
    ent = event_entry(biz, eid, zone)
    ask_blocks(biz, ent, now, zone)
    church = _business(biz)
    places = volunteer_places(biz)
    needs = clean_needs(biz, body.get("needs"), places)
    note = _note(body.get("note"))
    straight = schedules(me)
    name = login_name(church, me["uid"])
    stamp = _iso(sp._now())
    row = {"business_id": biz, "entry_id": eid, "title": ent["title"], "starts_at": _iso(ent["at"]),
           "place": ent["place"], "needs": needs, "note": note, "asked_by": me["uid"], "asked_by_name": name,
           "status": WAITING, "service_id": None, "decided_by": None, "decided_by_name": "", "decided_at": None,
           "decided_note": "", "told_at": None, "answer_told_at": None}
    if straight:
        # Straight on: the row claims the event's one live ask first (the
        # partial unique index), so two asks at once never make two dates.
        row.update({"status": ON, "decided_by": me["uid"], "decided_by_name": name, "decided_at": stamp,
                    "answer_told_at": stamp})
    got = sb_clients.sb_post_as_service(f"/{TABLE}?select={FIELDS}", row)
    if not isinstance(got, list) or not got:
        err = sb_clients.last_error() or {}
        if str(err.get("code")) == "23505":
            raise HTTPException(409, ASKED)
        raise HTTPException(503, UNSAVED)
    req = got[0]
    date_out = None
    if straight:
        try:
            date_out = sp.make_date(biz, user, entry_id=eid, needs=needs, gone=_gone(ent["title"]))["date"]
        except HTTPException:
            # The date wasn't made: the ask comes back out, so there is never
            # half of one. If even that can't be written, the sweep closes it
            # (repair), and no notice goes for an ask that is on with no date.
            if not sb_clients.sb_delete_as_service(f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}"
                                                   f"&status=eq.{ON}&service_id=is.null"):
                print(f"[event-volunteers] {biz[:8]}: an ask whose date wasn't made didn't come back out", flush=True)
            raise
        req = _link(biz, req, date_out["id"])
    _after("tell_ask", church, req)
    return {"request": _request_out(req), "date": date_out}


def _gone(title: Any) -> str:
    return f"{The(title)} isn't coming up in Services & Events anymore."


def _link(biz: str, req: Dict[str, Any], sid: str) -> Dict[str, Any]:
    """The ask names the date it made. The date is made either way, so a
    write that fails here is never a 503: it is said in the logs, and the
    sweep links them (repair)."""
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&select={FIELDS}", {"service_id": sid})
    if isinstance(got, list) and got:
        return got[0]
    print(f"[event-volunteers] {biz[:8]}: an ask wasn't linked to the date it made; the sweep will", flush=True)
    return {**req, "service_id": sid}


def _mine_or_scheduler(me: Dict[str, Any], req: Dict[str, Any]) -> bool:
    return str(req.get("asked_by")) == me["uid"] or schedules(me)


@router.patch("/{entry_id}/request")
def change_ask(entry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """While it waits, the one who asked (or whoever schedules the teams)
    changes the numbers or the note. Once it's on, the numbers are changed
    on Who serves when."""
    body = body or {}
    me = _login(body.get("business_id"), user)
    _ask_gate(me)
    _switch_gate(me)
    biz = me["biz"]
    eid = sp._uuid(entry_id, "event")
    req = live_request(biz, eid)
    if not req:
        raise HTTPException(404, NO_ASK)
    if not _mine_or_scheduler(me, req):
        raise HTTPException(403, f"Only {req.get('asked_by_name') or 'whoever asked'} or {WHOEVER} can change this ask.")
    if req.get("status") == ON:
        raise HTTPException(409, _on_words(me, _business(biz)))
    fields: Dict[str, Any] = {}
    if "needs" in body:
        fields["needs"] = clean_needs(biz, body.get("needs"), volunteer_places(biz))
    if "note" in body:
        fields["note"] = _note(body.get("note"))
    if not fields:
        raise HTTPException(400, "Change the numbers or the note.")
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&status=eq.{WAITING}&select={FIELDS}", fields)
    if not isinstance(got, list):
        raise HTTPException(503, UNSAVED)
    if not got:
        now_row = _request_row(biz, str(req["id"]))
        if now_row.get("status") == ON:
            raise HTTPException(409, _on_words(me, _business(biz)))
        raise HTTPException(409, "That ask was just answered. Look again.")
    return {"request": _request_out(got[0])}


def _on_words(me: Dict[str, Any], church: Dict[str, Any]) -> str:
    if schedules(me):
        return "It's on the schedule now. Change its numbers on Who serves when."
    return f"It's on the schedule now. Ask {_who_schedules(church)} to change the numbers."


@router.delete("/{entry_id}/request")
def take_back(entry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """Take a waiting ask back: the one who asked, or whoever schedules the
    teams. The switch doesn't stop it: an ask made while it was open can
    always be taken back. An ask that's on comes off Who serves when."""
    me = _login(business_id, user)
    _ask_gate(me)
    biz = me["biz"]
    eid = sp._uuid(entry_id, "event")
    req = live_request(biz, eid)
    if not req:
        raise HTTPException(404, NO_ASK)
    if not _mine_or_scheduler(me, req):
        raise HTTPException(403, f"Only {req.get('asked_by_name') or 'whoever asked'} or {WHOEVER} can take this ask back.")
    if req.get("status") == ON:
        raise HTTPException(409, "Take it off Who serves when instead.")
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&status=eq.{WAITING}&select={FIELDS}",
        {"status": WITHDRAWN})
    if not isinstance(got, list):
        raise HTTPException(503, UNSAVED)
    if not got:
        raise HTTPException(409, "That ask was just answered. Look again.")
    _after("tell_withdrawn", _business(biz), got[0], by=me["uid"])
    return {"request": _request_out(got[0])}


# ─── whoever schedules the teams: the asks and the answer ────────────

def waiting_count(biz: str, user: Any = None) -> int:
    """How many asks wait at this church, for the band on Who serves when
    and The week. 0 before the migration, with the switch closed, and when
    the count couldn't be read (the page never fails over it)."""
    if not ready() or not open_for(biz, user):
        return 0
    rows = sb_clients.sb_get_as_service(f"/{TABLE}?business_id=eq.{_q(biz)}&status=eq.{WAITING}&select=id&limit=500")
    if not isinstance(rows, list):
        print(f"[event-volunteers] {biz[:8]}: the waiting asks weren't counted", flush=True)
        return 0
    return len(rows)


def requests_list(biz: str) -> List[Dict[str, Any]]:
    """GET /planning/requests: the waiting asks, soonest event first, then
    those answered in the last week, newest first. Each with its day and
    time on the church's clock, who asked, the note, each place's number
    beside its Sunday number, the flyer's thumb and the special roles'
    numbers (labels and numbers, never names)."""
    import events_rsvp_router as ev
    zone = sp._zone(biz)
    since = _iso(sp._now() - timedelta(days=DECIDED_DAYS))
    waiting = _read(f"/{TABLE}?business_id=eq.{_q(biz)}&status=eq.{WAITING}&select={FIELDS}&order=starts_at.asc&limit=200")
    decided = _read(f"/{TABLE}?business_id=eq.{_q(biz)}&status=in.({ON},{DECLINED})&decided_at=gte.{_q(since)}"
                    f"&select={FIELDS}&order=decided_at.desc&limit=200")
    waiting.sort(key=lambda r: (str(r.get("starts_at") or ""), str(r["id"])))
    decided.sort(key=lambda r: str(r.get("decided_at") or ""), reverse=True)
    rows = waiting + decided
    places = volunteer_places(biz)
    by_id = {p["id"]: p for p in places}
    order = {p["id"]: n for n, p in enumerate(places)}
    eids = [str(r["entry_id"]) for r in rows if r.get("entry_id")]
    entries: Dict[str, Dict[str, Any]] = {}
    mods: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(eids), 100):
        for e in _read(f"/module_entries?business_id=eq.{_q(biz)}&id=in.({_ids(eids[i:i + 100])})"
                       f"&select=id,module_id,data"):
            entries[str(e["id"])] = e
    mids = {str(e.get("module_id")) for e in entries.values() if e.get("module_id")}
    if mids:
        for m in _read(f"/custom_modules?business_id=eq.{_q(biz)}&id=in.({_ids(mids)})&select=id,archetype_params"):
            mods[str(m["id"])] = ev.resolve_fields(m.get("archetype_params"))
    out = []
    for r in rows:
        at = _at(r.get("starts_at"))
        local = at.astimezone(zone) if at else None
        e = entries.get(str(r.get("entry_id") or ""))
        data = e.get("data") if e and isinstance(e.get("data"), dict) else {}
        f = mods.get(str((e or {}).get("module_id") or ""))
        roles = []
        if e and f:
            signups = ev.read_signups(data, f["signups_field"])
            roles = [{"label": x["label"], "needed": x["needed"], "filled": x["filled"]}
                     for x in (ev.role_fill(role, signups) for role in ev.occasion_roles(data, f["roles"]))]
        flyer = flyer_of(data, biz, r.get("entry_id"))
        needs = r.get("needs") or {}
        out.append({
            "id": str(r["id"]), "status": r.get("status"), "entry_id": str(r["entry_id"]) if r.get("entry_id") else None,
            "title": r.get("title") or "An event", "day": sd.day_label(local) if local else "",
            "time": clock_words(local) if local else "", "starts_at": r.get("starts_at"), "place": r.get("place") or "",
            "asked_by_name": r.get("asked_by_name") or "", "note": r.get("note") or "",
            "decided_by_name": r.get("decided_by_name") or "", "decided_note": r.get("decided_note") or "",
            "decided_at": r.get("decided_at"), "service_id": str(r["service_id"]) if r.get("service_id") else None,
            "places": [{"place_id": pid, "name": by_id[pid]["name"] if pid in by_id else "A place that's gone",
                        "team": by_id[pid]["team"] if pid in by_id else "", "n": int(n),
                        "sunday": by_id[pid]["needed"] if pid in by_id else None}
                       for pid, n in sorted(needs.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))],
            "flyer_thumb": flyer["thumb"] if flyer else None,
            "flyer": {"thumb": flyer["thumb"], "url": flyer["url"]} if flyer else None,
            "special": roles,
        })
    return out


def _cancel(biz: str, req: Dict[str, Any]) -> None:
    sb_clients.sb_patch_as_service(f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&status=eq.{WAITING}"
                                   "&select=id", {"status": CANCELLED})


def answer(biz: str, user: AuthedUser, rid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST /planning/requests/{id}/answer (spec 6.3), behind Who serves
    when's scheduler gate. A yes claims the ask (it lands only while it
    still waits, so two yeses at once make one event date), then makes the
    date through sunday_planning.make_date, the same code as Add an event
    date, with these numbers. A no needs a note back to the organizer."""
    church = _business(biz)
    req = _request_row(biz, rid)
    if req.get("status") != WAITING:
        raise HTTPException(409, _already(req))
    said = body.get("answer")
    if said not in ("yes", "no"):
        raise HTTPException(400, "The answer is yes or no.")
    note = _note(body.get("note"))
    name = login_name(church, str(user.id))
    stamp = _iso(sp._now())
    claim = f"/{TABLE}?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&status=eq.{WAITING}&select={FIELDS}"
    decided = {"decided_by": str(user.id), "decided_by_name": name, "decided_at": stamp, "decided_note": note,
               "answer_told_at": None}
    if said == "no":
        if not note:
            raise HTTPException(400, f"Say why, so {_first(req.get('asked_by_name')) or 'whoever asked'} knows what "
                                     "to do next.")
        got = sb_clients.sb_patch_as_service(claim, {"status": DECLINED, **decided})
        if not isinstance(got, list):
            raise HTTPException(503, UNSAVED)
        if not got:
            raise HTTPException(409, _already(_request_row(biz, rid)))
        _after("tell_answer", church, got[0])
        return {"request": _request_out(got[0]), "date": None}
    zone = sp._zone(biz)
    now = sp._now().astimezone(zone)
    places = volunteer_places(biz)
    asked = req.get("needs") or {}
    needs = clean_needs(biz, body["needs"], places) if body.get("needs") is not None else \
        clean_needs(biz, {k: v for k, v in asked.items() if k in {p["id"] for p in places}} or asked, places)
    if not req.get("entry_id"):
        _cancel(biz, req)
        raise HTTPException(409, f"{The(req.get('title'))} isn't in Services & Events anymore.")
    ent = event_entry(biz, str(req["entry_id"]), zone)
    if not ent["active"]:
        _cancel(biz, req)
        raise HTTPException(409, f"{The(ent['title'])} isn't in Services & Events anymore.")
    if ent["at"] is not None and ent["at"] <= now:
        _cancel(biz, req)
        raise HTTPException(409, f"{The(ent['title'])} has already happened.")
    if ent["at"] is not None and sd.is_sunday(ent["at"]) and sp.during_sunday_service(biz, ent["at"], zone):
        raise HTTPException(409, SUNDAY_CLASH)
    got = sb_clients.sb_patch_as_service(claim, {"status": ON, "needs": needs, **decided})
    if not isinstance(got, list):
        raise HTTPException(503, UNSAVED)
    if not got:
        raise HTTPException(409, _already(_request_row(biz, rid)))
    try:
        date_out = sp.make_date(biz, user, entry_id=str(req["entry_id"]), needs=needs, gone=_gone(ent["title"]))["date"]
    except HTTPException:
        # No date: the ask waits again, as it was. If even that can't be
        # written, the sweep puts it back (repair); no notice goes meanwhile.
        back = sb_clients.sb_patch_as_service(
            f"/{TABLE}?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&status=eq.{ON}&service_id=is.null"
            f"&decided_at=eq.{_q(stamp)}&select=id", _waiting_again(asked))
        if not isinstance(back, list) or not back:
            print(f"[event-volunteers] {biz[:8]}: an ask whose date wasn't made didn't go back to waiting", flush=True)
        raise
    row = _link(biz, got[0], date_out["id"])
    _after("tell_answer", church, row, before=asked)
    return {"request": _request_out(row), "date": date_out}


def _waiting_again(needs: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": WAITING, "needs": needs, "decided_by": None, "decided_by_name": "", "decided_at": None,
            "decided_note": "", "answer_told_at": None}


def _already(req: Dict[str, Any]) -> str:
    st = req.get("status")
    if st in (ON, DECLINED):
        return f"Already answered by {req.get('decided_by_name') or 'someone else'}."
    if st == WITHDRAWN:
        return "That ask was taken back. There's nothing to answer."
    return "That ask is closed: the event went away or moved. There's nothing to answer."


def close_for_date(biz: str, sid: str) -> bool:
    """An event date comes off Who serves when (sunday_planning.drop_date):
    the ask that made it is cancelled, so the event may ask again. Nobody is
    told (they did it). False when that couldn't be written; True before the
    migration (there is no ask)."""
    if not ready():
        return True
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&status=eq.{ON}&select=id", {"status": CANCELLED})
    return isinstance(got, list)


def follow_needs(biz: str, sid: str, needs: Optional[Dict[str, int]], places: List[Dict[str, Any]]) -> None:
    """A date's numbers changed on Who serves when (spec 6.4): the live ask
    that made it says the same, so the organizer reads the truth. Back to the
    Sunday numbers, it reads every Volunteers place at its Sunday number."""
    if not ready():
        return
    want = needs if needs else sunday_numbers(places)
    if not want:
        return
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&status=eq.{ON}&select=id", {"needs": want})
    if not isinstance(got, list):
        print(f"[event-volunteers] {biz[:8]}: an ask's numbers didn't follow its date", flush=True)


# ─── notices (spec 7.1, 7.2) ─────────────────────────────────────────

def _open_church(church: Dict[str, Any]) -> bool:
    """Notices go where the switch is open for the church, never for a
    sample church (its people are made up)."""
    try:
        import sample_church
        if sample_church.skip(church):
            return False
    except Exception:  # noqa: BLE001
        pass
    return _church_switch(church.get("id"))


def _church_name(church: Dict[str, Any]) -> str:
    return _plain(church.get("name")) or "Your church"


def _hi(name: str) -> str:
    return f"Hi {_first(name)}," if _first(name) and name != OFFICE else "Hello,"


def _when(req: Dict[str, Any], church: Dict[str, Any]) -> Tuple[str, str]:
    """(day words, time) of the ask's event on the church's clock."""
    at = _at(req.get("starts_at"))
    if not at:
        return "", ""
    try:
        import business_marketing
        at = at.astimezone(business_marketing.business_tz(church))
    except Exception:  # noqa: BLE001 — a clock that can't be read: UTC
        pass
    return sd.day_label(at), clock_words(at)


def ask_words(church: Dict[str, Any], req: Dict[str, Any], places: List[Dict[str, Any]]) -> Dict[str, str]:
    """7.1, to whoever schedules the teams: an ask that waits, or one put
    straight on by someone else."""
    asker = req.get("asked_by_name") or OFFICE
    day, at = _when(req, church)
    what = needs_words(req.get("needs") or {}, places)
    ev_ = the(req.get("title"))
    if req.get("status") == ON:
        title = f"{asker} put {ev_} on Who serves when"
        line = f"{asker} put {ev_} on Who serves when, {day}: {what}."
        return {"title": title[:80], "body": f"{day}: {what}."[:160], "subject": f"{_church_name(church)}: {title}",
                "text": "\n\n".join([line, "Asks go out to the teams as you make them."])}
    title = f"{asker} asked for volunteers"
    line = f"{asker} asked for volunteers for {ev_}, {day}, {at}: {what}."
    return {"title": title[:80], "body": f"{line} Open Who serves when to answer."[:160],
            "subject": f"{_church_name(church)}: {asker} asked for volunteers for {ev_}",
            "text": "\n\n".join([line, "Open Who serves when to answer."])}


def withdrawn_words(church: Dict[str, Any], req: Dict[str, Any], by: str, to_asker: bool) -> Dict[str, str]:
    ev_ = the(req.get("title"))
    if to_asker:
        title = f"{by} took back your ask for {ev_}"
        return {"title": title[:80], "body": "You can ask again from the event.", "subject": f"{_church_name(church)}: {title}",
                "text": "\n\n".join([f"{by} took back your ask for volunteers for {ev_}.",
                                     "You can ask again from the event in Services & Events."])}
    title = f"{req.get('asked_by_name') or OFFICE} took back the ask for {ev_}"
    return {"title": title[:80], "body": "Nothing for you to do.", "subject": f"{_church_name(church)}: {title}",
            "text": f"{title}. There's nothing for you to do."}


def answer_words(church: Dict[str, Any], req: Dict[str, Any], places: List[Dict[str, Any]],
                 before: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """7.2, to the organizer. A yes says what changed when the one who said
    it changed the numbers (`before`: what was asked); told later by the
    sweep, which can't know, it says the numbers it went on with."""
    by = req.get("decided_by_name") or OFFICE
    ev_ = the(req.get("title"))
    if req.get("status") == DECLINED:
        note = req.get("decided_note") or ""
        line = f"{by} can't staff {ev_} with the teams: “{note}”"
        return {"title": f"{by} can't staff {ev_} with the teams"[:80], "body": f"“{note}”"[:160],
                "subject": f"{_church_name(church)}: about the volunteers for {ev_}",
                "text": "\n\n".join([line, "You can see it on the event, and ask again there."])}
    needs = req.get("needs") or {}
    line = f"{by} put {ev_} on the schedule. Asks go out to the teams."
    if before is not None:
        changed = needs_words(needs, places, before)
        if changed:
            line = f"{by} put {ev_} on the schedule, with {changed}. Asks go out to the teams."
    else:
        line = f"{by} put {ev_} on the schedule with {needs_words(needs, places)}. Asks go out to the teams."
    return {"title": f"{by} put {ev_} on the schedule"[:80], "body": line[:160],
            "subject": f"{_church_name(church)}: {ev_} is on the schedule", "text": line}


def _tell(church: Dict[str, Any], uids: Iterable[str], words: Dict[str, str], ref: str) -> int:
    """One notice to each office login: church_schedule_tell.to_login (a push
    to the office app and an email). How many it reached."""
    import church_over as co
    import church_schedule_tell as cst
    ch = co.Church(church)
    reached = 0
    for uid in uids:
        try:
            got = cst.to_login(ch, str(uid), title=words["title"], body=words["body"], ref=f"{ref}-{uid}"[:200],
                               subject=words["subject"], text=words["text"])
        except Exception:  # noqa: BLE001 — one login that fails never stops the next
            print(f"[event-volunteers] {str(church.get('id'))[:8]}: a notice didn't go", flush=True)
            continue
        reached += 1 if (got.get("rang") or got.get("mailed")) else 0
    return reached


def _claim(biz: str, rid: str, column: str, guard: str, stamp: str) -> bool:
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&{column}=is.null{guard}&select=id", {column: stamp})
    return isinstance(got, list) and bool(got)


def _release(biz: str, rid: str, column: str, stamp: str) -> None:
    try:
        sb_clients.sb_patch_as_service(
            f"/{TABLE}?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&{column}=eq.{_q(stamp)}&select=id", {column: None})
    except Exception:  # noqa: BLE001
        print(f"[event-volunteers] {biz[:8]}: a claim wasn't let go ({column})", flush=True)


def _claimed(church: Dict[str, Any], req: Dict[str, Any], column: str, uids: List[str], words: Dict[str, str],
             ref: str, now: datetime) -> str:
    biz, rid = str(church["id"]), str(req["id"])
    stamp = _iso(now)
    if not _claim(biz, rid, column, f"&status=eq.{_q(req.get('status'))}", stamp):
        return "taken"
    try:
        sent = _tell(church, uids, words, ref) if uids else 1
    except Exception:  # noqa: BLE001 — a claim is never left taken for a notice that didn't go
        sent = 0
    if not sent:
        _release(biz, rid, column, stamp)
        return "unsent"
    return "told" if uids else "none"


def _quiet(church: Dict[str, Any], now: datetime) -> bool:
    try:
        import member_push
        return member_push.quiet_hour(church, now)
    except Exception:  # noqa: BLE001 — a clock nobody could read never holds a notice back
        return False


def tell_ask(church: Dict[str, Any], req: Dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """7.1: whoever schedules the teams hears of an ask, once (told_at): one
    that waits, or one put straight on by someone (they, as a scheduler,
    aren't told of their own). Answers told | held (quiet hours) | taken
    (another replica told it) | unsent (nothing went: let go for the sweep)
    | none (nobody to tell; marked) | closed."""
    try:
        if not _open_church(church):
            return "closed"
        if req.get("told_at") or req.get("status") not in LIVE:
            return "none"
        if req.get("status") == ON and not req.get("service_id"):
            return "none"       # on with no date yet: a write still under way, or one the sweep mends first
        now = now or _now()
        at = _at(req.get("starts_at"))
        if at and at <= now:
            return "none"
        biz = str(church["id"])
        asker = str(req.get("asked_by") or "")
        straight = req.get("status") == ON and str(req.get("decided_by") or "") == asker
        if req.get("status") == ON and not straight:
            # Answered before anyone was told of it: there is nothing left to tell them.
            return _claimed(church, req, "told_at", [], {}, "", now)
        uids = [u for u in holders(church) if u != asker]
        if not uids:
            return _claimed(church, req, "told_at", [], {}, "", now)
        if _quiet(church, now):
            return "held"
        words = ask_words(church, req, volunteer_places(biz))
        return _claimed(church, req, "told_at", uids, words, f"event-ask-{req['id']}", now)
    except HTTPException:
        return "unsent"


def tell_answer(church: Dict[str, Any], req: Dict[str, Any], *, now: Optional[datetime] = None,
                before: Optional[Dict[str, Any]] = None) -> str:
    """7.2: the organizer hears the answer, once (answer_told_at). Never for
    their own yes (straight on). Answers as tell_ask does."""
    try:
        if not _open_church(church):
            return "closed"
        if req.get("answer_told_at") or req.get("status") not in (ON, DECLINED):
            return "none"
        if req.get("status") == ON and not req.get("service_id"):
            return "none"       # on with no date yet: nothing is on the schedule to say
        asker = str(req.get("asked_by") or "")
        if not asker or str(req.get("decided_by") or "") == asker:
            return _claimed(church, req, "answer_told_at", [], {}, "", now or _now())
        now = now or _now()
        if _quiet(church, now):
            return "held"
        words = answer_words(church, req, volunteer_places(str(church["id"])), before)
        return _claimed(church, req, "answer_told_at", [asker], words, f"event-answer-{req['id']}", now)
    except HTTPException:
        return "unsent"


def tell_withdrawn(church: Dict[str, Any], req: Dict[str, Any], *, by: str) -> str:
    """Taken back, straight after the write, and never tried again (no
    column claims it). By the one who asked: whoever schedules the teams
    hears, when they had been told of the ask. By a scheduler: the one who
    asked hears."""
    try:
        if not _open_church(church) or req.get("status") != WITHDRAWN:
            return "none"
        asker = str(req.get("asked_by") or "")
        if str(by) == asker:
            if not req.get("told_at"):
                return "none"
            uids = [u for u in holders(church) if u != asker]
            words = withdrawn_words(church, req, req.get("asked_by_name") or OFFICE, False)
        else:
            uids = [asker] if asker else []
            words = withdrawn_words(church, req, login_name(church, by), True)
        if not uids:
            return "none"
        return "told" if _tell(church, uids, words, f"event-back-{req['id']}") else "unsent"
    except HTTPException:
        return "unsent"


def repair(church: Dict[str, Any], req: Dict[str, Any]) -> str:
    """An ask left on with no date (a write lost on the way, or a date that
    couldn't be made and a write that couldn't undo it): linked to the
    event's live date when it has one; else an ask put straight on is
    cancelled (its asker was told it failed) and an answered one waits again.
    Nobody is told. linked | cancelled | waiting | none | unsent."""
    biz = str(church["id"])
    if req.get("status") != ON or req.get("service_id"):
        return "none"
    guard = f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&status=eq.{ON}&service_id=is.null&select=id"
    try:
        live = live_date(biz, str(req["entry_id"])) if req.get("entry_id") else None
    except HTTPException:
        return "unsent"
    if live:
        what, body = "linked", {"service_id": str(live["id"])}
    elif str(req.get("decided_by") or "") == str(req.get("asked_by") or ""):
        what, body = "cancelled", {"status": CANCELLED}
    else:
        what, body = "waiting", _waiting_again(req.get("needs") or {})
    got = sb_clients.sb_patch_as_service(guard, body)
    return what if isinstance(got, list) and got else "unsent"


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes on the worker: an ask left on with no date is mended
    (repair), the notices a write couldn't send (quiet hours, a failed send,
    a replica that died) are told, once, from the ledger, and every event
    with a date or an ask follows its Services & Events entry (follow_tick,
    spec 6.7). Quiet (not one read) with the switch off and before the
    migration. A church that fails never stops the others."""
    stats = {"churches": 0, "told": 0, "answers": 0, "held": 0, "unsent": 0, "mended": 0}
    if mode() == "off" or not ready():
        return stats
    now = now or _now()
    churches: Dict[str, Dict[str, Any]] = {}
    _tell_tick(now, stats, churches)
    stats.update({"followed": 0, "moved": 0, "cancelled": 0, "people_told": 0})
    try:
        follow_tick(now, stats, churches)
    except Exception:  # noqa: BLE001 — the notices above stand; following runs again next time
        print("[event-volunteers] the sweep couldn't follow the events; next time", flush=True)
    return stats


def _read_churches(ids: Iterable[str], cache: Dict[str, Dict[str, Any]]) -> None:
    missing = sorted({str(i) for i in ids if i} - set(cache))
    for i in range(0, len(missing), 100):
        for b in sb_clients.sb_get_as_service(f"/businesses?id=in.({_ids(missing[i:i + 100])})"
                                              f"&select=id,name,type,owner_id,settings&limit=100") or []:
            cache[str(b["id"])] = b


def _tell_tick(now: datetime, stats: Dict[str, int], churches: Dict[str, Dict[str, Any]]) -> None:
    since = _q(_iso(now - timedelta(days=TELL_DAYS)))
    settle = now - timedelta(seconds=SETTLE_SECONDS)
    asks = sb_clients.sb_get_as_service(f"/{TABLE}?status=in.({WAITING},{ON})&told_at=is.null&created_at=gte.{since}"
                                        f"&select={FIELDS}&order=created_at.asc&limit=500")
    answers = sb_clients.sb_get_as_service(f"/{TABLE}?status=in.({ON},{DECLINED})&answer_told_at=is.null"
                                           f"&decided_at=gte.{since}&select={FIELDS}&order=decided_at.asc&limit=500")
    stranded = sb_clients.sb_get_as_service(f"/{TABLE}?status=eq.{ON}&service_id=is.null&decided_at=lt.{_q(_iso(settle))}"
                                            f"&select={FIELDS}&order=decided_at.asc&limit=200")
    if not isinstance(asks, list) or not isinstance(answers, list) or not isinstance(stranded, list):
        print("[event-volunteers] the sweep couldn't read the untold asks; next time", flush=True)
        return
    work: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for kind, rows in (("stranded", stranded), ("asks", asks), ("answers", answers)):
        for r in rows:
            work.setdefault(str(r.get("business_id")), {}).setdefault(kind, []).append(r)
    if not work:
        return
    _read_churches(work, churches)
    for b, todo in work.items():
        church = churches.get(b)
        if not church or not _open_church(church):
            continue
        stats["churches"] += 1
        try:
            mended = set()
            for r in todo.get("stranded", []):
                if repair(church, r) in ("linked", "cancelled", "waiting"):
                    stats["mended"] += 1
                    mended.add(str(r["id"]))
            for kind, fn, at_key, told in (("asks", tell_ask, "created_at", "told"),
                                           ("answers", tell_answer, "decided_at", "answers")):
                for r in todo.get(kind, []):
                    made = _at(r.get(at_key))
                    if (made and made > settle) or str(r["id"]) in mended:
                        continue        # the write's own notice goes first; a mended ask, next time
                    got = fn(church, r, now=now)
                    key = told if got == "told" else got
                    if key in stats:
                        stats[key] += 1
        except Exception:  # noqa: BLE001 — one church never stops the others
            print(f"[event-volunteers] the sweep failed for business {b[:8]}", flush=True)


def follow_tick(now: datetime, stats: Dict[str, int], churches: Dict[str, Dict[str, Any]]) -> None:
    """The safety net for edits made anywhere but the office's event form
    (Chief, another tab). Two reads find the churches with something to
    follow: event dates from an entry still to come or started in the last
    RAIN_HOURS, and live asks (waiting, or on for a date not long past).
    Each church is then followed with its own handful of reads (follow),
    however many events it has. Only churches the follow is open for
    (_follows), never a sample church."""
    recent = _q(_iso(now - timedelta(hours=RAIN_HOURS)))
    try:
        # Paged in a stable order: past the server's cap a church is never left out.
        dates = _read_all(
            f"/worship_services?kind=eq.{sd.EVENT}&archived_at=is.null&is_template=eq.false&event_entry_id=not.is.null"
            f"&starts_at=gt.{recent}&select=id,business_id", "business_id.asc,id.asc")
        asks = _read_all(
            f"/{TABLE}?status=in.({WAITING},{ON})&or=(status.eq.{WAITING},starts_at.gt.{recent})"
            "&select=id,business_id", "business_id.asc,id.asc")
    except HTTPException:
        print("[event-volunteers] the sweep couldn't read the events to follow; next time", flush=True)
        return
    ids = {str(r["business_id"]) for r in dates + asks if r.get("business_id")}
    if not ids:
        return
    _read_churches(ids, churches)
    for b in sorted(ids):
        church = churches.get(b)
        if not church or not _follows(church):
            continue
        try:
            got = follow(church, now)
        except Exception:  # noqa: BLE001 — one church never stops the next
            print(f"[event-volunteers] {b[:8]}: its events couldn't be followed; next time", flush=True)
            continue
        stats["followed"] += got["events"]
        stats["moved"] += got["moved"]
        stats["cancelled"] += got["cancelled"]
        stats["people_told"] += got["told"]


# ─── following the event (spec 6.7) ──────────────────────────────────
# An event's date on Who serves when follows the event in Services &
# Events. follow() runs after the office saves an event (POST
# /{entry_id}/changed, sync) and in the 15-minute sweep, for edits made
# anywhere else. It is idempotent: a second call finds nothing to do.
#
#   day or time changed ..... the date follows; whoever was asked (and told)
#                             or said yes hears
#   title or place changed .. the date follows; nobody is told
#   moved past, more than 180 days out, into a Sunday service, or no time
#                             ........ the date stays; Who serves when flags it
#                             (event_moved); a waiting ask is cancelled if past
#   archived, not active, deleted ... every ask on the date is taken back
#                             (Take back's own path), the date comes off, each
#                             person hears once, and the ask is cancelled
#   a rain date ............. a date whose start passed less than RAIN_HOURS
#                             ago follows a new time still ahead; one further
#                             back stays, flagged
#
# A PERSON'S LATEST MOVE NOTICE ALWAYS NAMES THE DATE'S TIME. Each notice is
# claimed first in member_push_sends, the ledger every member note uses
# (unique on business, kind and ref_id; every replica and the worker share
# it), as "event-moved-{assignment}-{time}-{n}": n counts that person's move
# notices for the date, so two replicas reach for the same key and one wins,
# and an event that goes back to a time it had before is told again. The
# ledger is read once a church: a person whose latest notice names another
# time than the date's (a sync that told and then lost the move, and the
# office put it back) hears it is back. A cancel is "event-cancelled-
# {assignment}". People are told first, then the date changes. A claim that
# can't be read (a database blip) stops the change for now; the next sync
# does it, and nobody hears twice. Quiet hours hold the whole change while
# anyone would hear of it, and the serving sweep says nothing for such a date
# meanwhile (unsettled), so no reminder goes out for what isn't true.

LEDGER = "/member_push_sends?on_conflict=business_id,kind,ref_id"
SERVING = "serving"
FOLLOW_DAYS = 200           # an ask is made at most 180 days ahead: older ones are long past
RAIN_HOURS = 48             # a date whose start passed this recently still follows its event to a new time
FOLLOW_ROWS = "id,service_id,position_id,slot,contact_id,status,notified_at"
MOVE_REF = re.compile(r"event-moved-([0-9a-f-]{36})-(\d{8}T\d{4}Z)-(\d{1,6})")


def short_day(at: datetime) -> str:
    """"Fri, Dec 11"."""
    return f"{at.strftime('%a')}, {sd.short_day(at)}"


def short_when(at: datetime) -> str:
    """"Sat, Dec 12, 6:00 PM"."""
    return f"{short_day(at)}, {clock_words(at)}"


def _same_time(a: Optional[datetime], b: Optional[datetime]) -> bool:
    return a is not None and b is not None and abs((a - b).total_seconds()) < 60


def _wont_follow(biz: str, ent: Dict[str, Any], now: datetime, zone) -> Optional[str]:
    """Why a moved event's date stays where it is, or None when it follows:
    no_time (a bare date), past, far (more than EVENT_AHEAD_DAYS out),
    sunday (into a Sunday service)."""
    at = ent.get("at")
    if at is None or ent.get("day") is None:
        return "no_time"
    if at <= now:
        return "past"
    if ent["day"] > now.astimezone(zone).date() + timedelta(days=sp.EVENT_AHEAD_DAYS):
        return "far"
    if sd.is_sunday(at) and sp.during_sunday_service(biz, at, zone):
        return "sunday"
    return None


def moved_flag(ent: Dict[str, Any], why: str) -> Dict[str, Any]:
    """What Who serves when says of a date that didn't follow its event."""
    at, day = ent.get("at"), ent.get("day")
    if at is not None:
        when = short_when(at)
    elif day is not None:
        when = f"{short_day(day)}, with no start time"
    else:
        when = "no day yet"
    return {"to": _iso(at) if at is not None else None, "why": why,
            "words": f"The event moved to {when}; this date didn't follow. Take it off or keep it."}


def moved_words(title: Any, at: datetime, place: str, status: str) -> Dict[str, str]:
    head = f"{The(title)} moved to {short_when(at)}"
    body = (f"You're still on {place}. If you can't make it, tap Change my answer." if status == "yes"
            else f"You were asked for {place}. Tap Yes or Can't that day.")
    return {"title": head, "body": body}


def cancelled_words(title: Any, at: datetime, place: str) -> Dict[str, str]:
    return {"title": f"{The(title)} on {short_day(at)} was cancelled", "body": f"You're off {place}."}


def _hears(r: Dict[str, Any]) -> bool:
    """Who hears of a move or a cancel: whoever said yes, and whoever was
    asked once the ask went out (an ask still waiting to go out goes with
    the new time, or not at all)."""
    return bool(r.get("contact_id")) and (r.get("status") == "yes"
                                          or (r.get("status") == "asked" and bool(r.get("notified_at"))))


class _Tell:
    """The people of one date, read once: names, addresses, their serving
    email choices and the places' names."""

    def __init__(self, church: Dict[str, Any], rows: List[Dict[str, Any]]):
        self.church = church
        self.biz = str(church["id"])
        self.on = _open_church(church)
        cids = sorted({str(r["contact_id"]) for r in rows if _hears(r)})
        pids = sorted({str(r["position_id"]) for r in rows if r.get("position_id")})
        self.places = {str(p["id"]): _plain(p.get("name")) or "your place" for p in (_read(
            f"/serve_positions?business_id=eq.{_q(self.biz)}&id=in.({_ids(pids)})&select=id,name") if pids else [])}
        self.people: Dict[str, Dict[str, Any]] = {}
        self.prefs: Dict[str, Dict[str, Any]] = {}
        if self.on and cids:
            import group_email
            self.people = {str(p["id"]): p for p in (group_email._people(self.biz, cids) or [])}
            self.prefs = {str(x["contact_id"]): x for x in _read(
                f"/serve_prefs?business_id=eq.{_q(self.biz)}&contact_id=in.({_ids(cids)})"
                "&select=contact_id,email,email_stopped_at")}

    def place(self, r: Dict[str, Any]) -> str:
        return self.places.get(str(r.get("position_id")), "your place")

    def send(self, r: Dict[str, Any], words: Dict[str, str], ref: str, url: str) -> str:
        """One person, once: told | taken (told before) | unsent (the
        ledger couldn't be read: try again) | quiet (a church nothing is
        sent for: a sample, or one the switch is closed for)."""
        if not self.on:
            return "quiet"
        cid = str(r["contact_id"])
        claim = sb_clients.sb_post_as_service(
            LEDGER, {"business_id": self.biz, "kind": SERVING, "ref_id": ref[:200], "title": words["title"][:200],
                     "body": words["body"], "url": url, "sent_by": None},
            prefer="resolution=ignore-duplicates,return=representation")
        if claim is None:
            return "unsent"
        if not claim:
            return "taken"
        import member_push
        rang = member_push.send(self.church, SERVING, title=words["title"], body=words["body"], url=url,
                                contact_ids=[cid], tag=f"serving-{r['id']}")
        try:
            self._email(cid, words, ref, url, rang)
        except Exception:  # noqa: BLE001 — one address never stops the rest; the push went or it didn't
            print(f"[event-volunteers] {self.biz[:8]}: an email to a volunteer didn't go", flush=True)
        try:
            member_push._logged(claim[0].get("id"), rang)
        except Exception:  # noqa: BLE001
            pass
        return "told"

    def _email(self, cid: str, words: Dict[str, str], ref: str, url: str, rang: int) -> None:
        """sunday_serving_alerts' email rules: an adult who keeps their
        serving emails, or anyone the phone didn't reach; never once they
        pressed Stop these emails."""
        import academy_join
        import group_email
        import sunday_serving_alerts as ssa
        person, pref = self.people.get(cid), self.prefs.get(cid) or {}
        if not person or pref.get("email_stopped_at"):
            return
        if not (ssa.email_church(self.church) or pref.get("email") is not False or not rang):
            return
        email = str(person.get("email") or "").strip()
        if not group_email._adult(person) or not academy_join.valid_email(email):
            return
        import asyncio
        import email_layout
        import email_sender
        import serve_links
        church = _church_name(self.church)
        settings = self.church.get("settings") if isinstance(self.church.get("settings"), dict) else {}
        stop = serve_links.stop_token(self.biz, cid)
        app = group_email.app_url(self.biz)
        cta = ("Open my serving", f"{app}{url}") if app else None
        html = email_layout.render_html(
            "\n\n".join([f"{words['title']}.", words["body"]]), business_name=church, brand=email_layout.brand_of(settings),
            sig=None, unsubscribe_url=serve_links.page_url(stop, stop="1"), unsubscribe_label="Stop these emails",
            preheader=words["body"][:90], cta=cta, disclaimer=f"You serve at {church}.",
            footer_note="Sent with ChurchSavvy")
        asyncio.run(email_sender.send_via_resend(
            to_email=email, to_name=person.get("name") or None,
            from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app", from_name=church,
            subject=words["title"][:150], body=html, reply_to=None, business_id=self.biz,
            idempotency_key=ref[:120], unsubscribe_url=serve_links.one_click_url(stop)))


def back_words(title: Any, at: datetime, place: str, status: str) -> Dict[str, str]:
    """A correction: the person was told another time than the date's."""
    head = f"{The(title)} is back to {short_when(at)}"
    return {"title": head, "body": moved_words(title, at, place, status)["body"]}


def stamp(at: datetime) -> str:
    """A time as a notice's key says it: "20261101T0000Z"."""
    return at.astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ")


def move_ref(aid: Any, at: datetime, n: int) -> str:
    return f"event-moved-{aid}-{stamp(at)}-{n}"


LEDGER_IDS = 40             # people a ledger read names at once (keeps its address short)


def _told(biz: str, now: datetime, aids: Iterable[Any]) -> Dict[str, Tuple[int, str]]:
    """Each of these assignments' latest move notice, from the ledger:
    {assignment: (n, the time it named)}. Only these people's notices, newest
    first, read whole however many there are. The latest is the highest n,
    and between two of the same n (two replicas that raced to two new times)
    the later written: so the next notice is always n + 1, and the time
    compared is the one the person heard last."""
    since = _q(_iso(now - timedelta(days=FOLLOW_DAYS)))
    ids = sorted({str(a) for a in aids if a})
    best: Dict[str, Tuple[int, str, str]] = {}
    for i in range(0, len(ids), LEDGER_IDS):
        names = ",".join(f"ref_id.like.{_q(f'event-moved-{a}-*')}" for a in ids[i:i + LEDGER_IDS])
        rows = _read_all(f"/member_push_sends?business_id=eq.{_q(biz)}&kind=eq.{SERVING}&or=({names})"
                         f"&created_at=gte.{since}&select=id,ref_id,created_at", "created_at.desc,id.desc")
        for r in rows:
            m = MOVE_REF.fullmatch(str(r.get("ref_id") or ""))
            if not m or m.group(1) not in ids:
                continue
            aid, at, n, made = m.group(1), m.group(2), int(m.group(3)), str(r.get("created_at") or "")
            if aid not in best or (n, made) > (best[aid][0], best[aid][2]):
                best[aid] = (n, at, made)
    return {aid: (n, at) for aid, (n, at, _made) in best.items()}


def _church_zone(church: Dict[str, Any]):
    try:
        import business_marketing
        return business_marketing.business_tz(church)
    except Exception:  # noqa: BLE001 — the church's own clock, read the long way
        return sp._zone(str(church["id"]))


def _entries(biz: str, eids: Iterable[Any], zone) -> Dict[str, Dict[str, Any]]:
    """These events of this church as entry_view gives them, two reads for
    them all. One that isn't there, or isn't in an events room, is left
    out: for following, it went away."""
    ids = sorted({str(e) for e in eids if e})
    rows: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 100):
        rows += _read(f"/module_entries?business_id=eq.{_q(biz)}&id=in.({_ids(ids[i:i + 100])})"
                      "&select=id,module_id,status,updated_at,data")
    mids = sorted({str(r.get("module_id")) for r in rows if r.get("module_id")})
    mods = {str(m["id"]): m for m in (_read(f"/custom_modules?business_id=eq.{_q(biz)}&id=in.({_ids(mids)})"
                                            "&archetype=eq.event_roster&select=id,archetype_params,is_active")
                                      if mids else [])}
    return {str(r["id"]): {**entry_view(r, mods[str(r["module_id"])], zone), "updated_at": r.get("updated_at")}
            for r in rows if str(r.get("module_id")) in mods}


def _follows(church: Dict[str, Any]) -> bool:
    """Where an event's date follows it: the switch open for the church
    itself (not only for the platform owner's login), event dates open
    there, never a sample church. The notices go exactly where the changes
    do, so a date never moves or comes off in silence."""
    return _open_church(church) and sd.open_for(str(church["id"]))


def _ledger(cx: Dict[str, Any]) -> Dict[str, Tuple[int, str]]:
    """The latest move notice of everyone who hears on the dates followed
    (one ledger read for them all, made only when someone would hear)."""
    if cx["told"] is None:
        cx["told"] = _told(cx["biz"], cx["now"], [r["id"] for rs in cx["rows"].values() for r in rs if _hears(r)])
    return cx["told"]


def _teller(cx: Dict[str, Any]) -> "_Tell":
    if cx["tell"] is None:
        cx["tell"] = _Tell(cx["church"], [r for rs in cx["rows"].values() for r in rs])
    return cx["tell"]


def _rearm(biz: str, sid: str, to: datetime, zone, now: datetime) -> None:
    """A moved date's reminders follow the new time: a yes's mark is
    cleared only for a reminder whose moment for the new time is still to
    come (sunday_serving_alerts.moments, its own rule). One whose window
    already opened keeps its mark, so it never goes twice or late."""
    import sunday_serving_alerts as ssa
    clear = {col: None for col, at in ssa.moments(to, zone).items() if at > now}
    if clear and not isinstance(sb_clients.sb_patch_as_service(
            f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&status=eq.yes&select=id", clear), list):
        print(f"[event-volunteers] {biz[:8]}: a moved date's reminders weren't reset", flush=True)


def _cancel_one(cx: Dict[str, Any], s: Dict[str, Any], title: Any, at: datetime) -> Tuple[str, int]:
    """The event went away: tell each person on the date once, take every
    row back by Take back's own path (sunday_planning.do_take_back, so
    reminders stop and swaps close) and take the date off. The ask that made
    it is closed after (_follow_ask): until then it points the next sync at
    a deleted event's date. cancelled | held | unsent."""
    church, biz, now = cx["church"], cx["biz"], cx["now"]
    sid = str(s["id"])
    rows = cx["rows"].get(sid, [])
    hear = [r for r in rows if _hears(r)]
    if hear and cx["on"] and _quiet(church, now):
        return "held", 0
    local = at.astimezone(cx["zone"])
    told = 0
    for r in hear:
        tell = _teller(cx)
        got = tell.send(r, cancelled_words(title, local, tell.place(r)), f"event-cancelled-{r['id']}", "/my/serving")
        if got == "unsent":
            return "unsent", told
        told += got == "told"
    for r in rows:
        try:
            sp.do_take_back(biz, str(r["id"]))
        except HTTPException as e:
            if e.status_code != 404:
                return "unsent", told
    off = sb_clients.sb_patch_as_service(
        f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&kind=eq.{sd.EVENT}&archived_at=is.null&select=id",
        {"archived_at": _iso(now)})
    return ("cancelled" if isinstance(off, list) else "unsent"), told


def _follow_one(cx: Dict[str, Any], s: Dict[str, Any], ent: Optional[Dict[str, Any]], title: Any) -> Tuple[str, int]:
    """One live date and its event. moved | renamed | same | corrected |
    flagged | held | cancelled | past | unsent, and how many heard."""
    church, biz, zone, now = cx["church"], cx["biz"], cx["zone"], cx["now"]
    sid = str(s["id"])
    at = _at(s.get("starts_at"))
    if at is None:
        return "same", 0
    if ent is None or not ent["active"]:
        if at <= now:
            return "past", 0        # it happened (or is under way): leave it
        return _cancel_one(cx, s, title, at)
    fields: Dict[str, Any] = {}
    if ent["title"] != _plain(s.get("title")):
        fields["title"] = ent["title"]
    if ent["place"] != _plain(s.get("place")):
        fields["place"] = ent["place"]
    moved = not _same_time(ent.get("at"), at)
    # A rain date: a date that started a little while ago follows a new time still ahead.
    ahead = at > now or (ent.get("at") is not None and ent["at"] > now)
    follow = moved and ahead and not _wont_follow(biz, ent, now, zone)
    state = "moved" if follow else ("flagged" if moved else "same")
    to = ent["at"] if follow else at.astimezone(zone)
    need: List[Tuple[Dict[str, Any], Optional[Tuple[int, str]]]] = []
    hear = [r for r in cx["rows"].get(sid, []) if _hears(r)]
    if hear and (follow or at > now):
        told = _ledger(cx)
        for r in hear:
            last = told.get(str(r["id"]))
            if follow and (last is None or last[1] != stamp(to)):
                need.append((r, last))
            elif not follow and last is not None and last[1] != stamp(at):
                need.append((r, last))      # told a time the date doesn't have: it's back
    n_told = 0
    if need and cx["on"] and _quiet(church, now):
        state, follow = "held", False       # the date waits for its notices
    else:
        for r, last in need:
            tell = _teller(cx)
            n = last[0] + 1 if last else 0
            words = (moved_words if follow else back_words)(ent["title"], to, tell.place(r), r["status"])
            got = tell.send(r, words, move_ref(r["id"], to, n), f"/my/serving/{r['id']}")
            if got == "unsent":
                return "unsent", n_told
            if got in ("told", "taken"):
                cx["told"][str(r["id"])] = (n, stamp(to))
            n_told += got == "told"
        if need and not follow:
            state = "corrected"
        if follow:
            fields["starts_at"] = _iso(to)
    if not fields:
        return state, n_told
    got = sb_clients.sb_patch_as_service(
        f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&kind=eq.{sd.EVENT}&archived_at=is.null&select=id",
        fields)
    if not isinstance(got, list):
        return "unsent", n_told
    if "starts_at" in fields:
        _rearm(biz, sid, to, zone, now)
    # The ask that made the date says what it says (its card, and the sweep's reach).
    copy = {k: v for k, v in fields.items() if k in ("title", "place", "starts_at")}
    if not isinstance(sb_clients.sb_patch_as_service(
            f"/{TABLE}?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&status=eq.{ON}&select=id", copy), list):
        print(f"[event-volunteers] {biz[:8]}: an ask's copy of its date didn't follow; next time", flush=True)
    return (state if state != "same" else "renamed"), n_told


def _refresh(biz: str, req: Dict[str, Any], ent: Dict[str, Any], now: datetime) -> Optional[str]:
    """A waiting ask keeps its copies of the event (title, starts_at, place)
    up to date, and is cancelled when the event went into the past.
    refreshed | cancelled | None."""
    fields: Dict[str, Any] = {}
    if ent["title"] != (req.get("title") or ""):
        fields["title"] = ent["title"]
    if ent["place"] != (req.get("place") or ""):
        fields["place"] = ent["place"]
    if ent.get("at") is not None and not _same_time(ent["at"], _at(req.get("starts_at"))):
        fields["starts_at"] = _iso(ent["at"])
    past = ent.get("at") is not None and ent["at"] <= now
    if past:
        fields["status"] = CANCELLED
    if not fields:
        return None
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&status=eq.{WAITING}&select=id", fields)
    if not isinstance(got, list) or not got:
        return None
    return "cancelled" if past else "refreshed"


def _close(biz: str, req: Dict[str, Any], status: str) -> bool:
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?id=eq.{_q(req['id'])}&business_id=eq.{_q(biz)}&status=eq.{_q(status)}&select=id",
        {"status": CANCELLED})
    return isinstance(got, list) and bool(got)


def _follow_ask(cx: Dict[str, Any], r: Dict[str, Any], ents: Dict[str, Dict[str, Any]],
                live: Dict[str, Dict[str, Any]], states: Dict[str, str]) -> int:
    """One live ask: a waiting one keeps its copies (or closes with its
    event); one that is on closes when its event went away and its date came
    off, now or before. A date that already happened keeps its ask: it was
    served. 1 when it was written."""
    biz, now = cx["biz"], cx["now"]
    eid = str(r.get("entry_id") or "")
    ent = ents.get(eid) if eid else None
    alive = ent is not None and ent["active"]
    if r.get("status") == WAITING:
        if not alive:
            return int(_close(biz, r, WAITING))
        return int(bool(_refresh(biz, r, ent, now)))
    sid = str(r.get("service_id") or "")
    if alive or not sid:
        return 0                    # on and well, or on with no date (repair's)
    if states.get(sid) == "cancelled" or sid not in live:
        return int(_close(biz, r, ON))
    return 0


def follow(church: Dict[str, Any], now: Optional[datetime] = None, *, only: Optional[str] = None) -> Dict[str, Any]:
    """Follow one church's events (spec 6.7): every live date from an entry,
    still to come or started in the last RAIN_HOURS, and every live ask; or,
    with `only` (the office's /changed), that event's and the asks whose
    event was deleted. A handful of reads for the church however many events
    it has: its dates, its asks, their events (two), the rows on those dates
    and, when anyone would hear, the move ledger. Safe to call any number of
    times. {date: `only`'s date's state or None, told, requests, events,
    moved, cancelled}."""
    now = now or _now()
    biz = str(church["id"])
    recent = _q(_iso(now - timedelta(hours=RAIN_HOURS)))
    out: Dict[str, Any] = {"date": None, "told": 0, "requests": 0, "events": 0, "moved": 0, "cancelled": 0}
    dates = _read(f"/worship_services?business_id=eq.{_q(biz)}&kind=eq.{sd.EVENT}&archived_at=is.null"
                  f"&is_template=eq.false&starts_at=gt.{recent}&select=id,title,starts_at{sd.fields()}"
                  "&order=starts_at.asc&limit=200")
    asks = _read(f"/{TABLE}?business_id=eq.{_q(biz)}&status=in.({WAITING},{ON})"
                 f"&or=(status.eq.{WAITING},starts_at.gt.{recent})&select={FIELDS}&order=created_at.asc&limit=500")
    if only:
        asks = [r for r in asks if str(r.get("entry_id") or "") in (str(only), "")]
    live = {str(s["id"]): s for s in dates}
    orphans = {str(r["service_id"]) for r in asks
               if not r.get("entry_id") and r.get("status") == ON and r.get("service_id")}
    work = [s for s in dates if s.get("event_entry_id") and (not only or str(s["event_entry_id"]) == str(only))]
    work += [live[sid] for sid in sorted(orphans) if sid in live and not live[sid].get("event_entry_id")]
    if not work and not asks:
        return out
    zone = _church_zone(church)
    ents = _entries(biz, {s.get("event_entry_id") for s in work} | {r.get("entry_id") for r in asks}, zone)
    rows: Dict[str, List[Dict[str, Any]]] = {}
    sids = sorted({str(s["id"]) for s in work})
    for i in range(0, len(sids), 100):
        # Paged: a short read must never read as "nobody's on this date".
        for row in _read_all(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=in.({_ids(sids[i:i + 100])})"
                             f"&select={FOLLOW_ROWS}", "id.asc"):
            rows.setdefault(str(row["service_id"]), []).append(row)
    cx = {"church": church, "biz": biz, "zone": zone, "now": now, "rows": rows, "told": None, "tell": None,
          "on": _open_church(church)}
    states: Dict[str, str] = {}
    for s in work:
        eid = str(s.get("event_entry_id") or "")
        ent = ents.get(eid) if eid else None
        title = ((ent or {}).get("title") or next((r.get("title") for r in asks if str(r.get("service_id") or "")
                                                   == str(s["id"]) and r.get("title")), None) or s.get("title"))
        state, told = _follow_one(cx, s, ent, title)
        states[str(s["id"])] = state
        out["told"] += told
        out["events"] += 1
        out["moved"] += state == "moved"
        out["cancelled"] += state == "cancelled"
        if only and eid == str(only):
            out["date"] = state
    for r in asks:
        out["requests"] += _follow_ask(cx, r, ents, live, states)
    return out


def sync(biz: str, entry_id: str, *, now: Optional[datetime] = None,
         church: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Follow one event (spec 6.7): follow(), kept to it and to the asks
    whose event was deleted."""
    return follow(church or _business(biz), now, only=str(entry_id))


def unsettled(church: Dict[str, Any], services: Iterable[Dict[str, Any]],
              now: Optional[datetime] = None) -> set:
    """The event dates (sunday_serving's shape: id, at, event, entry_id)
    whose event went away, or moved to a time the date will follow, and the
    date hasn't yet: the serving sweep says nothing for them meanwhile, so a
    cancel or a move held through quiet hours never has a reminder or an ask
    go out for what isn't true. Empty where the follow isn't open, before
    the migration, and when a read fails (the reminders go as before)."""
    evs = [s for s in services if s.get("event")]
    if not evs or not ready() or not _follows(church):
        return set()
    now = now or _now()
    biz = str(church["id"])
    try:
        zone = _church_zone(church)
        ents = _entries(biz, {s.get("entry_id") for s in evs}, zone)
        out = set()
        stale = now - timedelta(days=1)
        for s in evs:
            eid = str(s.get("entry_id") or "")
            if not eid:
                continue
            ent = ents.get(eid)
            if ent is None or not ent["active"]:
                out.add(str(s["id"]))
            elif not _same_time(ent.get("at"), s.get("at")) and not _wont_follow(biz, ent, now, zone):
                out.add(str(s["id"]))
            else:
                continue
            changed = _at((ent or {}).get("updated_at"))
            if changed is not None and changed < stale:
                # A change this old should have been followed long ago: a follow stuck
                # (unsent, a read that keeps failing) shows here, as the reminders wait.
                print(f"[event-volunteers] {biz[:8]}: the reminders for an event date are held for a change "
                      f"made {(now - changed).days} day(s) ago that hasn't been followed", flush=True)
        loose = [str(s["id"]) for s in evs if not s.get("entry_id")]
        if loose:
            out |= {str(r["service_id"]) for r in _read(
                f"/{TABLE}?business_id=eq.{_q(biz)}&status=eq.{ON}&entry_id=is.null&service_id=in.({_ids(loose)})"
                "&select=service_id")}
        return out
    except Exception:  # noqa: BLE001 — a read that fails keeps the reminders as they were
        print(f"[event-volunteers] {biz[:8]}: the serving sweep couldn't check its event dates", flush=True)
        return set()


@router.post("/{entry_id}/changed")
def changed(entry_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The office saved an event (the app calls this after every save): its
    date on Who serves when and its ask follow it now (follow), with the
    same gate as asking. Where the follow isn't open for the church itself
    (the platform owner's login at another church, a sample church) it is a
    404: nothing changes without its notices. Cheap, and safe to call
    twice."""
    body = body or {}
    me = _login(body.get("business_id"), user)
    _ask_gate(me)
    _switch_gate(me)
    eid = sp._uuid(entry_id, "event")
    church = _business(me["biz"])
    if not _follows(church):
        raise HTTPException(404, "Not Found")
    got = follow(church, only=eid)
    return {"date": got["date"], "told": got["told"], "requests": got["requests"]}


# ─── the flyer (spec 6.12) ───────────────────────────────────────────
# PUT /{entry_id}/flyer takes an upload (multipart: business_id, file) or a
# picture already in the church's gallery (JSON {business_id, artwork_id}).
# An upload goes through image_studio as every picture does
# (normalize_image, its own store, an image_artworks row in the owner's
# name), so it is in the church's gallery and on the Light Table too. Then
# two copies are made from the original with Pillow, plain RGB JPEGs with no
# EXIF: the full one at most 1600 px on its long side (quality 88) and the
# thumb 480 px wide (quality 82), in the public business-assets bucket at
# {business_id}/event-flyers/{entry_id}/{artwork_id}.jpg and -thumb.jpg. The
# same picture always lands at the same address, so attaching it again
# replaces its copies. _flyer is written by a read-modify-write of the
# event's data as the server, and the whole new data comes back so the
# office's form saves on top of it.

FLYER_BYTES = 10 * 1024 * 1024
FLYER_SIDE = 8000
FULL_SIDE, FULL_QUALITY = 1600, 88
THUMB_WIDE, THUMB_QUALITY = 480, 82
FLYER_KINDS = ("JPEG", "PNG", "WEBP")
FLYER_PIXELS = 25_000_000   # image_studio.normalize_image's own cap, checked here before anything is decoded
NOT_A_FLYER = "Choose a JPG, PNG or WebP picture under 10 MB."
TOO_HEAVY = "That picture is over 10 MB. Choose a smaller one, or save it smaller first."
NOT_A_KIND = "That isn't a JPG, PNG or WebP picture. Choose one of those."
TOO_BIG = "That picture is too big: at most 8000 pixels a side and 25 megapixels in all. Choose a smaller one."
UNREADABLE = "That picture couldn't be read. Choose another JPG, PNG or WebP."
NOT_YOURS = ("Pictures from the gallery are for the owner, an admin, and whoever does the posts or the clips. "
             "Upload the flyer instead.")
NO_PICTURE = "That picture isn't in this church's gallery. Pick another, or upload one."


def _flyer_gate(business_id: Any, entry_id: str, user: AuthedUser,
                switch: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Any office login that could edit the event, with the switch open: a
    Viewer is the part's refusal (403), another church's event a 404.
    Taking a flyer off (`switch` False) doesn't need the switch: after a
    rollback the office can still take one down."""
    me = _login(business_id, user)
    _ask_gate(me)
    if switch:
        _switch_gate(me)
    eid = sp._uuid(entry_id, "event")
    ent = event_entry(me["biz"], eid, sp._zone(me["biz"]))
    return me, ent


def check_upload(raw: Any) -> bytes:
    """An upload the flyer takes: a JPG, PNG or WebP of at most 10 MB and
    8000 px a side, turned upright (a phone's photo carries its turn in its
    EXIF, which the copies drop), then image_studio.normalize_image's PNG.
    Anything else is a plain 400."""
    import io
    from PIL import Image, ImageOps, UnidentifiedImageError
    import image_studio
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise HTTPException(400, "Choose a picture to upload.")
    if len(raw) > FLYER_BYTES:
        raise HTTPException(400, TOO_HEAVY)
    try:
        # Image.open reads the header only: the kind and the size are checked
        # before anything is decoded on purpose. Reading the EXIF turn after
        # that may decode a PNG (its EXIF can sit after the pixels), but only
        # a picture already inside the caps.
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in FLYER_KINDS:
                raise HTTPException(400, NOT_A_KIND)
            if im.width > FLYER_SIDE or im.height > FLYER_SIDE or im.width * im.height > FLYER_PIXELS:
                raise HTTPException(400, TOO_BIG)
            turn = im.getexif().get(0x0112) if hasattr(im, "getexif") else None
            if turn and turn != 1:
                im.load()
                up = ImageOps.exif_transpose(im)
                buf = io.BytesIO()
                up.save(buf, "PNG")
                raw = buf.getvalue()
    except HTTPException:
        raise
    except Image.DecompressionBombError:
        raise HTTPException(400, TOO_BIG)
    except UnidentifiedImageError:
        raise HTTPException(400, NOT_A_KIND)
    except (OSError, ValueError):
        raise HTTPException(400, UNREADABLE)
    try:
        return image_studio.normalize_image(bytes(raw))
    except HTTPException:
        raise HTTPException(400, UNREADABLE)


def flyer_copies(png: bytes) -> Dict[str, Any]:
    """The two delivery copies of one picture: {full, thumb} JPEG bytes and
    the full one's size. RGB on white (a see-through flyer reads on any
    card), never any EXIF."""
    import io
    from PIL import Image
    with Image.open(io.BytesIO(png)) as im:
        im.load()
        rgb = Image.new("RGB", im.size, "white")
        if im.mode in ("RGBA", "LA") or "transparency" in im.info:
            rgba = im.convert("RGBA")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        else:
            rgb.paste(im.convert("RGB"))
    full = rgb.copy()
    full.thumbnail((FULL_SIDE, FULL_SIDE), Image.LANCZOS)
    wide = min(THUMB_WIDE, rgb.width)
    thumb = rgb.resize((wide, max(1, round(rgb.height * wide / rgb.width))), Image.LANCZOS)
    out: Dict[str, Any] = {"w": full.width, "h": full.height}
    for key, im, q in (("full", full, FULL_QUALITY), ("thumb", thumb, THUMB_QUALITY)):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        out[key] = buf.getvalue()
    out["thumb_w"], out["thumb_h"] = thumb.width, thumb.height
    return out


def flyer_paths(biz: str, eid: str, artwork_id: str) -> Tuple[str, str]:
    base = f"{biz}/event-flyers/{eid}/{artwork_id}"
    return f"{base}.jpg", f"{base}-thumb.jpg"


def gallery_reader(church: Dict[str, Any], user: AuthedUser) -> None:
    """Whether this login may take a picture from the church's gallery and
    put it on the public page: the owner, or a login image_studio's own
    church_reader lets read the gallery (an Admin, whoever does the posts or
    the clips). Anyone else is a 403: the picture is read as the owner and
    published, so the gallery's own rule decides."""
    if str(user.id) == str(church.get("owner_id") or ""):
        return
    import image_studio
    if not image_studio.church_reader(str(church["id"]), user):
        raise HTTPException(403, NOT_YOURS)


def _artwork(biz: str, artwork_id: Any) -> Dict[str, Any]:
    """A picture of this church's gallery, ready. Another church's is a 404."""
    try:
        aid = str(uuid.UUID(str(artwork_id)))
    except (ValueError, TypeError):
        raise HTTPException(404, NO_PICTURE)
    rows = _read(f"/image_artworks?id=eq.{_q(aid)}&business_id=eq.{_q(biz)}"
                 "&select=id,business_id,status,storage_path&limit=1")
    if not rows or str(rows[0].get("business_id")) != biz:
        raise HTTPException(404, NO_PICTURE)
    if rows[0].get("status") != "ready" or not str(rows[0].get("storage_path") or "").startswith(biz + "/"):
        raise HTTPException(409, "That picture isn't ready yet. Try again in a minute.")
    return rows[0]


def write_flyer(biz: str, eid: str, flyer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """_flyer on the event (None takes it off), by a read-modify-write of its
    data as the server, the event's own revision as the guard. The whole new
    data."""
    for _ in range(4):
        rows = _read(f"/module_entries?id=eq.{_q(eid)}&business_id=eq.{_q(biz)}&select=id,data,updated_at&limit=1")
        if not rows:
            raise HTTPException(404, NO_EVENT)
        data = dict(rows[0].get("data") or {}) if isinstance(rows[0].get("data"), dict) else {}
        if flyer is None:
            data.pop("_flyer", None)
        else:
            data["_flyer"] = flyer
        rev = rows[0].get("updated_at")
        guard = f"&updated_at=eq.{_q(rev)}" if rev else ""
        got = sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{_q(eid)}&business_id=eq.{_q(biz)}{guard}&select=id,data", {"data": data})
        if not isinstance(got, list):
            raise HTTPException(503, UNSAVED)
        if got:
            return got[0].get("data") if isinstance(got[0].get("data"), dict) else data
    raise HTTPException(409, "Someone else was saving this event at the same moment. Try again.")


async def _flyer_body(request: Any) -> Tuple[Any, Optional[bytes], Any]:
    """(business_id, the upload's bytes or None, artwork_id or None)."""
    kind = (request.headers.get("content-type") or "").lower()
    if kind.startswith("multipart/form-data"):
        try:
            form = await request.form()
        except Exception:  # noqa: BLE001 — a broken form is a plain 400
            raise HTTPException(400, "Choose a picture to upload.")
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            raise HTTPException(400, "Choose a picture to upload.")
        raw = await up.read(FLYER_BYTES + 1)
        return form.get("business_id"), raw, None
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Upload a picture, or pick one from the gallery.")
    if not isinstance(body, dict) or not body.get("artwork_id"):
        raise HTTPException(400, "Upload a picture, or pick one from the gallery.")
    return body.get("business_id"), None, body.get("artwork_id")


@router.put("/{entry_id}/flyer")
async def put_flyer(entry_id: str, request: Request, user: AuthedUser = Depends(require_user)):
    """The event's flyer (spec 6.12): an upload, or a picture from the
    church's gallery. {data: the event's whole data now, flyer}."""
    business_id, raw, artwork_id = await _flyer_body(request)
    return await attach_flyer(business_id, entry_id, user, raw=raw, artwork_id=artwork_id)


async def attach_flyer(business_id: Any, entry_id: str, user: AuthedUser, *, raw: Optional[bytes] = None,
                       artwork_id: Any = None) -> Dict[str, Any]:
    """The flyer route's work once its body is read: the gate, an upload's
    checks or a gallery picture's (gallery_reader, _artwork), the copies and
    the write. Chief puts a gallery picture on an event through here too
    (chief_event_volunteers), as the signed-in login, so there is one way a
    flyer goes on."""
    import asyncio
    import httpx
    import image_studio
    if raw is None and not artwork_id:
        raise HTTPException(400, "Upload a picture, or pick one from the gallery.")
    me, ent = await asyncio.to_thread(_flyer_gate, business_id, entry_id, user)
    biz, eid = me["biz"], ent["entry_id"]
    church = await asyncio.to_thread(_business, biz)
    owner = str(church.get("owner_id") or "")
    png = await asyncio.to_thread(check_upload, raw) if raw is not None else None
    if artwork_id:
        await asyncio.to_thread(gallery_reader, church, user)
    row = await asyncio.to_thread(_artwork, biz, artwork_id) if artwork_id else None
    async with httpx.AsyncClient(timeout=60) as client:
        # As the church's owner, like every server-made picture
        # (clip_covers, the marketing desk): the gallery and its originals
        # are the owner's. Set only here, after the gate; reset below.
        token = image_studio.build_actor.set({"business_id": biz, "user_id": owner})
        try:
            if png is not None:
                art_id = str(uuid.uuid4())
                path = f"{biz}/{art_id}.png"
                await image_studio.store(client, path, png, "image/png")
                rows = await image_studio.db(client, "POST", "/image_artworks", {
                    "id": art_id, "business_id": biz, "owner_id": owner, "prompt": f"Flyer: {ent['title']}"[:180],
                    "status": "ready", "storage_path": path, "cost_usd": 0}, server_write=True)
                row = rows[0] if isinstance(rows, list) and rows else {"id": art_id, "storage_path": path,
                                                                        "status": "ready"}
            else:
                png = await image_studio.original(client, row)
            art_id = str(row["id"])
            copies = await asyncio.to_thread(flyer_copies, png)
            full_path, thumb_path = flyer_paths(biz, eid, art_id)
            await image_studio.store(client, full_path, copies["full"], "image/jpeg", "business-assets")
            await image_studio.store(client, thumb_path, copies["thumb"], "image/jpeg", "business-assets")
        finally:
            image_studio.build_actor.reset(token)
    flyer = {"artwork_id": art_id, "url": image_studio.storage_url(f"object/public/business-assets/{full_path}"),
             "thumb": image_studio.storage_url(f"object/public/business-assets/{thumb_path}"),
             "w": copies["w"], "h": copies["h"], "at": _iso(_now())}
    data = await asyncio.to_thread(write_flyer, biz, eid, flyer)
    return {"data": data, "flyer": flyer_of(data, biz, eid)}


@router.delete("/{entry_id}/flyer")
def drop_flyer(entry_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """Take the flyer off the event (the picture stays in the gallery). The
    switch doesn't stop it: a flyer put up while it was open can always come
    down."""
    me, ent = _flyer_gate(business_id, entry_id, user, switch=False)
    data = write_flyer(me["biz"], ent["entry_id"], None)
    return {"data": data, "flyer": None}


def flyer_card(data: Any, business_id: Any, entry_id: Any) -> Optional[Dict[str, str]]:
    """{thumb, url} for an office list (Who serves when, The week)."""
    f = flyer_of(data, business_id, entry_id)
    return {"thumb": f["thumb"], "url": f["url"]} if f else None


def flyers_for(biz: str, entry_ids: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """The flyers {url, thumb, w, h} of these events of this church, by
    entry id (only the ones that have a valid one). A read that fails is
    no flyers, never an error: a picture is never worth a page."""
    ids = sorted({str(e) for e in entry_ids if e})
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 100):
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?business_id=eq.{_q(biz)}&id=in.({_ids(ids[i:i + 100])})&select=id,data")
        if not isinstance(rows, list):
            return out
        for r in rows:
            f = flyer_of(r.get("data"), biz, r.get("id"))
            if f:
                out[str(r["id"])] = f
    return out


def date_extras(biz: str, services: List[Dict[str, Any]], user: Any = None, *, flags: bool = True,
                now: Optional[datetime] = None) -> None:
    """Event dates on Who serves when and The week (each a service dict with
    kind 'event' and its event_entry_id): `flyer` {thumb, url} or None, and,
    with `flags` and the switch open, `event_moved` (moved_flag) when its
    event moved and the date won't follow: the new time can't be followed
    (past, far, a Sunday service, no time), or the date started more than
    RAIN_HOURS ago. In place; one read of the events. A read that fails,
    here or in the Sunday check, leaves no flyer or no flag: the page never
    fails over a picture or a flag."""
    evs = [s for s in services if s.get("kind") == sd.EVENT]
    for s in evs:
        s["flyer"] = None
    linked = [s for s in evs if s.get("event_entry_id")]
    if not linked:
        return
    rows: Dict[str, Dict[str, Any]] = {}
    ids = sorted({str(s["event_entry_id"]) for s in linked})
    for i in range(0, len(ids), 100):
        got = sb_clients.sb_get_as_service(f"/module_entries?business_id=eq.{_q(biz)}&id=in.({_ids(ids[i:i + 100])})"
                                           "&select=id,module_id,status,data")
        if not isinstance(got, list):
            return
        rows.update({str(r["id"]): r for r in got})
    try:
        flag = flags and ready() and open_for(biz, user)
    except Exception:  # noqa: BLE001
        flag = False
    mods: Dict[str, Dict[str, Any]] = {}
    if flag:
        mids = sorted({str(r.get("module_id")) for r in rows.values() if r.get("module_id")})
        got = sb_clients.sb_get_as_service(f"/custom_modules?business_id=eq.{_q(biz)}&id=in.({_ids(mids)})"
                                           "&archetype=eq.event_roster&select=id,archetype_params,is_active") if mids else []
        mods = {str(m["id"]): m for m in got} if isinstance(got, list) else {}
    now = now or _now()
    zone = None
    for s in linked:
        e = rows.get(str(s["event_entry_id"]))
        if not e:
            continue
        s["flyer"] = flyer_card(e.get("data"), biz, e.get("id"))
        if not flag:
            continue
        s["event_moved"] = None
        mod = mods.get(str(e.get("module_id")))
        at = _at(s.get("starts_at"))
        if not mod or at is None:
            continue
        try:
            zone = zone or sp._zone(biz)
            ent = entry_view(e, mod, zone)
            if not ent["active"] or _same_time(ent.get("at"), at):
                continue
            if at <= now - timedelta(hours=RAIN_HOURS):
                why: Optional[str] = "started"
            elif at <= now and (ent.get("at") is None or ent["at"] <= now):
                why = "past"
            else:
                why = _wont_follow(biz, ent, now, zone)
        except Exception:  # noqa: BLE001 — no flag rather than no page
            print(f"[event-volunteers] {biz[:8]}: an event date's flag couldn't be worked out", flush=True)
            continue
        if why:
            s["event_moved"] = moved_flag(ent, why)
