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

S3 adds the flyer (upload, attach, every reader), following the event (sync),
the special-role rules and hours; flyer_of() here is the validator they read.
"""
from __future__ import annotations

import os
import re
import time as clock
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

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
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._\-/]+$")


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

def flyer_of(data: Any, business_id: Any) -> Optional[Dict[str, Any]]:
    """The event's flyer, {url, thumb, w, h}, or None. `_flyer` sits in JSON
    the browser writes, so it is checked on every read: both addresses in
    this church's own event-flyers folder of the public business-assets
    bucket, nothing in them but a path's plain characters, and the size whole
    numbers from 1 to 8000. Anything else is no flyer, never an error."""
    f = data.get("_flyer") if isinstance(data, dict) else None
    base = sb_clients.sb_url()
    if not isinstance(f, dict) or not base:
        return None
    try:
        b = str(uuid.UUID(str(business_id)))
    except (ValueError, TypeError):
        return None
    folder = f"{base}/storage/v1/object/public/business-assets/{b}/event-flyers/"
    out: Dict[str, Any] = {}
    for key in ("url", "thumb"):
        v = f.get(key)
        if not isinstance(v, str) or not v.startswith(folder):
            return None
        rest = v[len(folder):]
        if (not rest or ".." in rest or rest.startswith("/") or rest.endswith("/") or "//" in rest
                or not _SAFE_PATH.match(rest)):
            return None
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

def event_entry(biz: str, entry_id: str, zone) -> Dict[str, Any]:
    """One of this church's Services & Events entries (an event_roster
    room's): its title, day and time on the church's clock (`at` is None for
    a bare date), place, data and roles. 404 for anything else."""
    import church_leaders_note as cln
    import events_rsvp_router as ev
    rows = _read(f"/module_entries?id=eq.{_q(entry_id)}&business_id=eq.{_q(biz)}"
                 f"&select=id,module_id,status,data&limit=1")
    if not rows:
        raise HTTPException(404, NO_EVENT)
    e = rows[0]
    mods = _read(f"/custom_modules?id=eq.{_q(e.get('module_id'))}&business_id=eq.{_q(biz)}"
                 f"&archetype=eq.event_roster&select=id,archetype_params,is_active&limit=1")
    if not mods:
        raise HTTPException(404, NO_EVENT)
    f = ev.resolve_fields(mods[0].get("archetype_params"))
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    day, at = cln._when_of(data.get(f["date_field"]), zone)
    return {"entry_id": str(e["id"]), "module_id": str(mods[0]["id"]),
            "active": e.get("status") == "active" and mods[0].get("is_active") is not False,
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
    if not ready() or sp.mode() == "off" or not open_for(biz, user) or not sp._office(biz):
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
    v = data.get("_serve_minutes")
    if not isinstance(v, int) or isinstance(v, bool):
        return SERVE_MINUTES
    return max(MINUTES_LO, min(MINUTES_HI, v))


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
    special = []
    for role in ent["roles"]:
        fill = ev.role_fill(role, signups)
        people = [{"name": _plain(s.get("name")) or "Someone",
                   **({"contact_id": str(s["contact_id"])} if s.get("contact_id") else {})}
                  for s in signups if s.get("role") == role.get("id") and (s.get("status") or "yes") == "yes"]
        special.append({"role_id": str(role.get("id")), "label": fill["label"], "needed": fill["needed"],
                        "kids": role.get("kids") is True, "open": role.get("open") is True, "people": people})
    t_need = sum(t["needed"] for t in teams)
    t_yes = sum(1 for t in teams for s in t["slots"] if s["state"] == "yes")
    s_need = sum(s["needed"] for s in special)
    s_yes = sum(min(len(s["people"]), s["needed"]) for s in special)
    return {
        "request": None if not req else {
            "id": str(req["id"]), "status": req.get("status"), "needs": req.get("needs") or {},
            "note": req.get("note") or "", "asked_by_name": req.get("asked_by_name") or "",
            "decided_by_name": req.get("decided_by_name") or "", "decided_note": req.get("decided_note") or ""},
        "date": None if not svc else {"service_id": str(svc["id"]), "starts_at": svc.get("starts_at"),
                                      "needs": svc.get("needs") if isinstance(svc.get("needs"), dict) else None},
        "teams": teams,
        "special": special,
        "counts": {"all": t_need + s_need, "yes": t_yes + s_yes, "teams_needed": t_need, "teams_yes": t_yes,
                   "special_needed": s_need, "special_yes": s_yes},
        "flyer": flyer_of(ent["data"], biz),
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
    upcoming_gate(ent, now)
    if sd.is_sunday(ent["at"]) and sp.during_sunday_service(biz, ent["at"], zone):
        raise HTTPException(400, SUNDAY_CLASH)
    church = _business(biz)
    if live_request(biz, eid):
        raise HTTPException(409, ASKED)
    if live_date(biz, eid):
        # Made the November 17 way, with no ask: its numbers are changed there.
        who = _who_schedules(church)
        raise HTTPException(409, f"This event is already on Who serves when. {who[:1].upper()}{who[1:]} can change "
                                 "its numbers there.")
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
        flyer = flyer_of(data, biz)
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
    (repair), and the notices a write couldn't send (quiet hours, a failed
    send, a replica that died) are told, once, from the ledger. Quiet (not one read) with the switch off and before the
    migration. A church that fails never stops the others. S3 adds following
    the event (spec 6.7) here."""
    stats = {"churches": 0, "told": 0, "answers": 0, "held": 0, "unsent": 0, "mended": 0}
    if mode() == "off" or not ready():
        return stats
    now = now or _now()
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
        return stats
    work: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for kind, rows in (("stranded", stranded), ("asks", asks), ("answers", answers)):
        for r in rows:
            work.setdefault(str(r.get("business_id")), {}).setdefault(kind, []).append(r)
    if not work:
        return stats
    churches: Dict[str, Dict[str, Any]] = {}
    ids = sorted(work)
    for i in range(0, len(ids), 100):
        for b in sb_clients.sb_get_as_service(f"/businesses?id=in.({_ids(ids[i:i + 100])})"
                                              f"&select=id,name,type,owner_id,settings&limit=100") or []:
            churches[str(b["id"])] = b
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
    return stats
