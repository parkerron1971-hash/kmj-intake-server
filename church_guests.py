"""church_guests.py — the Guests room: one room under People for everything
about first-time guests (the Welcome Path, step 6 of the build order).

Kevin, 2026-11-20: "capture visitors, place them in a flow where they
receive automated texts from the church, chief should be sending a follow
up call to the admin of people and care or a church should be able to
assign who should be over this ... top tier." On the mock (canvas
WmRiSK8seJky8pJUK5nztE, boards Guests room and Numbers): "build".

Read-only. Nothing here writes, sends or hands anything on; it reads what
New here (new_here.py), the follow-ups (church_follow_up.py), check-in
(attendance, child_checkins) and Groups wrote, and puts it in one place.

  GET /church/guests/{business_id}
      This week. Guests met in the last 7 days (New this week), guests met
      in the last 4 weeks who came again in the last 7 days (Came back),
      and Plan your visit cards from the last 2 weeks whose guest hasn't
      come yet (Planning a visit). For each guest: the door, a family line
      from the card, where New here's texts stand, their welcome call (who
      has it, when it's due, the last thing the caller logged), whether
      they came back. The facts row, a next move, the texts going out this
      week, and what Chief did (its History lines about these guests'
      follow-ups, in their own words).
  GET /church/guests/{business_id}/scorecard?period=month|season|year
      From first visit to connected, by door and by caller.
  GET /church/guests/{business_id}/status
      {open: true} when this login has the room (the menu asks once); the
      same gate, without a guest read.

Who: the GUEST_PATH switch (guest_path.switched_on); off is a 404, so the
app hides the room. A church login at Manager or above (the Follow-up
board's floor, church_router.CARE_MIN_ROLE) whose areas include People &
care: the owner and admins always, every login while Who sees what is off
(church_areas.mode()), otherwise church_areas.my_areas (the whole church,
or people_care among its areas). A view that can't be read is a 503.

Who a guest is (both reads): a contact of the church with any of
  - contacts.metadata.new_here.texted_at (New here: the text door, and
    since the Welcome Path every door; guest_path's contract),
  - contacts.metadata.new_here.app.at (the member app's "I'm new here"),
  - a welcome follow-up (guest_path.is_guest_follow_up: New here's card,
    the member app's, a first check-in, the website card, a connect or
    Plan your visit form),
counted once, from the earliest of those (their path's start). Someone who
texted the word a second time (new_here.visits >= 2) started when their
record was made. The door: metadata.new_here.door, else the door of the
earliest of those (a follow-up's card_key: text:new_here text,
app:new_here app, checkin:first kids, web:connect_card web, form:* form).

Visits (came back, a third time): the day the path started is the first
visit, then each later day on the church's clock with an attendance row
for the guest, or a child_checkins row for a family they're an adult in.
A Plan your visit card is a plan, not a visit: that guest's first visit is
their first check-in, and until then they are Planning a visit (not in the
scorecard's first-time guests).

The scorecard's steps, for guests whose path started in the period:
  first-time guests   as above (a planned visit counts once they came)
  called within N     the first note logged on their welcome follow-up as
                      reached (church_follow_up.REACHED: Talked, Left a
                      message) is within N days of the hand-off (assigned_at),
                      N the church's call window (settings.guest_calls.due_days,
                      2 unless the church picked 1 or 3)
  came back           a visit on a later day than their first
  came a third time   visits on 3 different days
  connected           joined a group, a class or a team: a group_members row
                      in an active group of any kind (small group, team, class,
                      ministry; Serve teams are groups) whose joined_on is on
                      or after their first visit, or an Academy class
                      (academy_enrollments, active or completed) enrolled on
                      or after their first visit
By door: guests, called within N days, came back. By caller: the person who
logged each guest's first reached note (calls) and how many of those were
within the call window (on time).

Reads go through the service role, pinned to the church; every list is read
a page at a time (never more than 1,000 rows in one read). A read the room
can't do without (the guests, their follow-ups, their notes, their visits)
is a 503, never "nobody": a side part that fails (the texts, what Chief did,
connected) comes back null and the room says it couldn't be read.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

import church_follow_up as cfu
import guest_path
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(tags=["church-guests"])

MIN_ROLE = "manager"                 # the Follow-up board's floor
CARE_AREA = "people_care"
WEEK_DAYS = 7                        # New this week
RECENT_DAYS = 28                     # Came back: met in the last four weeks
PLANNED_DAYS = 14                    # Planning a visit: a card from the last two weeks
PAGE = 1000                          # never more than this in one read
MAX_ROWS = 20000                     # a list longer than this is a 503, never a cut
CHUNK = 100                          # ids in one in.(...)
FEED_MAX = 5                         # What Chief did
REPLY_GRACE = timedelta(minutes=2)   # the word itself is not a reply
SENT_WINDOW = timedelta(minutes=10)  # a scheduled text's message, beside its run
INVITE_SKIP_AFTER = timedelta(hours=20)   # new_here._came_back's rule
DEFAULT_DUE_DAYS = 2

STEPS = ("welcome", "thanks", "call", "monday", "invite")
STEP_WORDS = {"welcome": "Welcome", "thanks": "Thank you", "call": "Call",
              "monday": "Monday note", "invite": "Invite back"}
TEXT_STEPS = ("thanks", "monday", "invite")
CARD_DOOR = {"text:new_here": "text", "app:new_here": "app", "checkin:first": "kids",
             "web:connect_card": "web"}
# The doors in the office's words (guest_path.DOORS), "a card" said as a
# heading can carry.
DOOR_WORDS = {**guest_path.DOORS, "form": "Cards and forms"}
OUTCOME_KINDS = ("talked", "message", "noanswer", "notnow", "handed_back")
OUTCOME_WORDS = {**cfu.OUTCOMES, "handed_back": "Handed back"}
PERIODS = ("month", "season", "year")
SEASONS = (("winter", (12, 1, 2)), ("spring", (3, 4, 5)), ("summer", (6, 7, 8)), ("fall", (9, 10, 11)))
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
FALLBACK_TZ = "America/New_York"

GUEST_SELECT = "id,name,phone,metadata,created_at"
FU_SELECT = ("id,contact_id,card_key,card_name,path_kind,answers,steps,step,status,leader_contact_id,"
             "due_at,assigned_at,created_at,done_at")
NOTE_SELECT = "id,follow_up_id,kind,author_kind,author_contact_id,author_name,created_at"


class Unread(Exception):
    """A read the room can't do without didn't answer."""


# ─── Small helpers ────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _iso(dt: datetime) -> str:
    # No "+00:00": a raw "+" in a PostgREST query string reads as a space.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _tz(business: Dict[str, Any]):
    """The church's clock (New here's: business_marketing), else Eastern."""
    try:
        import new_here
        return new_here.tz_of(business)
    except Exception:  # noqa: BLE001
        from zoneinfo import ZoneInfo
        return ZoneInfo(FALLBACK_TZ)


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _nameless(name: Any) -> bool:
    try:
        import text_room
        return text_room.nameless(name)
    except Exception:  # noqa: BLE001
        return not _plain(name)


def _first(name: str) -> str:
    return name.split(" ")[0] if name else ""


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _need(path: str) -> List[Dict[str, Any]]:
    rows = _rows(path)
    if rows is None:
        raise Unread(path.split("?")[0])
    return rows


def _all(path: str, order: str = "id.asc") -> List[Dict[str, Any]]:
    """Every row, a page at a time in a stable order: one read is never more
    than PAGE rows, and a list longer than MAX_ROWS is a 503, never a cut."""
    out: List[Dict[str, Any]] = []
    while True:
        rows = _need(f"{path}&order={order}&limit={PAGE}&offset={len(out)}")
        out += rows
        if len(rows) < PAGE:
            return out
        if len(out) >= MAX_ROWS:
            raise Unread(path.split("?")[0] + " (too many rows)")


def _chunks(values: Iterable[Any]) -> List[List[str]]:
    vals = sorted({str(v) for v in values if v})
    return [vals[i:i + CHUNK] for i in range(0, len(vals), CHUNK)]


def _all_in(path: str, column: str, values: Iterable[Any], order: str = "id.asc") -> List[Dict[str, Any]]:
    """`path` with `column=in.(…)`, a chunk of ids at a time, each read whole."""
    out: List[Dict[str, Any]] = []
    for part in _chunks(values):
        out += _all(f"{path}&{column}=in.({','.join(_q(v) for v in part)})", order)
    return out


def _soft(fn: Callable[[], Any]) -> Any:
    """A side part: None when it couldn't be read, and the room goes on."""
    try:
        return fn()
    except Unread as e:
        print(f"[church_guests] side read failed: {e}", flush=True)
        return None


def _between(col: str, since: datetime, until: Optional[datetime] = None) -> str:
    out = f"{col}=gte.{_q(_iso(since))}"
    return out + (f"&{col}=lt.{_q(_iso(until))}" if until else "")


def _clock(local: datetime) -> str:
    hour = local.strftime("%I").lstrip("0") or "12"
    ampm = local.strftime("%p")
    return f"{hour}:{local.minute:02d} {ampm}" if local.minute else f"{hour} {ampm}"


def when_words(t: datetime, tz: Any, now: datetime) -> str:
    """'6 PM today', '10 AM tomorrow', 'Tue 6 PM' on the church's clock."""
    local, today = t.astimezone(tz), now.astimezone(tz).date()
    if local.date() == today:
        return f"{_clock(local)} today"
    if local.date() == today + timedelta(days=1):
        return f"{_clock(local)} tomorrow"
    return f"{local.strftime('%a')} {_clock(local)}"


def late_words(due: datetime, now: datetime) -> str:
    days = int((now - due).total_seconds() // 86400)
    if days < 1:
        return "past due"
    return "a day late" if days == 1 else f"{days} days late"


# ─── Who may read it ──────────────────────────────────────────────────

def _areas_ok(biz_id: str, uid: str, role: str) -> bool:
    """The owner and admins always; while Who sees what is off, every staff
    login; else a login whose areas are the whole church or include People &
    care. A view that couldn't be read is a 503, never a yes."""
    if role in ("owner", "admin"):
        return True
    import church_areas
    if church_areas.mode() != "on":
        return True
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    return areas is None or CARE_AREA in areas


def _gate(biz: Dict[str, Any], session: UserSession) -> str:
    if not cfu.is_church(biz):
        raise HTTPException(404, "Not Found")
    biz_id = str(biz["id"])
    if not guest_path.switched_on(biz_id):
        raise HTTPException(404, "Not Found")
    if not _areas_ok(biz_id, str(session.user.id), str(biz.get("_caller_role") or "")):
        raise HTTPException(403, "The Guests room is for People & care.")
    return biz_id


# ─── Who the guests are ───────────────────────────────────────────────

def _gather(biz_id: str, since: datetime, until: Optional[datetime] = None
            ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """The church's contacts with a guest signal in [since, until), and every
    welcome follow-up each of them has (whenever it was made)."""
    b = _q(biz_id)
    texted = _all(f"/contacts?business_id=eq.{b}&{_between('metadata->new_here->>texted_at', since, until)}"
                  f"&select={GUEST_SELECT}")
    told = _all(f"/contacts?business_id=eq.{b}&{_between('metadata->new_here->app->>at', since, until)}"
                f"&select={GUEST_SELECT}")
    made = [f for f in _all(f"/church_follow_ups?business_id=eq.{b}&{_between('created_at', since, until)}"
                            f"&select={FU_SELECT}") if guest_path.is_guest_follow_up(f)]
    contacts: Dict[str, Dict[str, Any]] = {str(c["id"]): c for c in texted + told}
    missing = {str(f["contact_id"]) for f in made if f.get("contact_id")} - set(contacts)
    for c in _all_in(f"/contacts?business_id=eq.{b}&select={GUEST_SELECT}", "id", missing):
        contacts[str(c["id"])] = c
    theirs = _all_in(f"/church_follow_ups?business_id=eq.{b}&select={FU_SELECT}", "contact_id", contacts)
    by_contact: Dict[str, List[Dict[str, Any]]] = {}
    seen: Set[str] = set()
    for f in theirs + made:
        fid = str(f.get("id"))
        if fid in seen or not guest_path.is_guest_follow_up(f) or str(f.get("contact_id")) not in contacts:
            continue
        seen.add(fid)
        by_contact.setdefault(str(f["contact_id"]), []).append(f)
    for fs in by_contact.values():
        fs.sort(key=lambda f: str(f.get("created_at") or ""))
    return contacts, by_contact


def _door_of_follow_up(f: Dict[str, Any]) -> str:
    key = str(f.get("card_key") or "")
    return CARD_DOOR.get(key) or ("form" if key.startswith("form:") else "")


def _family(meta: Dict[str, Any], app: Dict[str, Any], fus: List[Dict[str, Any]]) -> str:
    """A family line from what they told the church: the card's kids, the
    member app's, or the kids desk's first check-in line."""
    card = meta.get("card") if isinstance(meta.get("card"), dict) else {}
    kids = str(card.get("kids") or "")
    if kids == "1":
        return "with 1 kid"
    if kids in ("2", "3 or more"):
        return f"with {kids} kids"
    if app.get("kids") == "yes":
        ages = _plain(app.get("ages"))[:40]
        return f"with kids ({ages})" if ages else "with kids"
    for f in fus:
        if str(f.get("card_key")) != cfu.FIRST_CHECK_IN_KEY:
            continue
        for a in f.get("answers") or []:
            for part in str((a or {}).get("a") or "").split(" · "):
                if "checked in" in part:
                    return _plain(part)[:60]
    return ""


def _core(c: Dict[str, Any], fus: List[Dict[str, Any]], tz: Any) -> Optional[Dict[str, Any]]:
    """One guest's start, door, family line and welcome follow-up."""
    meta = guest_path.guest_meta(c)
    app = meta.get("app") if isinstance(meta.get("app"), dict) else {}
    texted = _parse(meta.get("texted_at"))
    app_at = _parse(app.get("at"))
    try:
        visits = int(meta.get("visits") or 0)
    except (TypeError, ValueError):
        visits = 0
    signals: List[Tuple[datetime, str]] = []
    if texted:
        signals.append((texted, "text"))
    if app_at:
        signals.append((app_at, "app"))
    for f in fus:
        t = _parse(f.get("created_at"))
        if t:
            signals.append((t, _door_of_follow_up(f)))
    if visits >= 2:
        made = _parse(c.get("created_at"))
        if made:
            signals.append((made, "text"))
    if not signals:
        return None
    start, first_door = min(signals, key=lambda s: s[0])
    door = str(meta.get("door") or "")
    door = door if door in guest_path.DOORS else first_door
    # A card or form: the church's own card's name says more than "a card".
    door_words = DOOR_WORDS.get(door, "")
    if door == "form":
        form = next((f for f in fus if str(f.get("card_key") or "").startswith("form:")), None)
        door_words = _plain((form or {}).get("card_name"))[:40] or door_words
    # The follow-up the room shows: an open one first, else the newest.
    live = [f for f in fus if f.get("status") in ("open", "handed_back")]
    fu = (live or fus)[-1] if fus else None
    earliest = fus[0] if fus else None
    planned = bool(earliest and str(earliest.get("path_kind")) == "visit"
                   and str(earliest.get("card_key") or "").startswith("form:")
                   and (_parse(earliest.get("created_at")) or start) <= start)
    name = "" if _nameless(c.get("name")) else _plain(c.get("name"))
    return {
        "id": str(c["id"]), "name": name, "initials": cfu.initials(name) if name else "",
        "family": _family(meta, app, fus), "door": door, "door_words": door_words,
        "start": start, "start_day": start.astimezone(tz).date(), "texted": texted,
        "text_again": visits >= 2 and texted, "meta": meta, "fu_row": fu, "fus": fus, "planned": planned,
        "hold": bool(meta.get("hold")),
    }


# ─── Visits ───────────────────────────────────────────────────────────

def _visits(biz_id: str, ids: Iterable[str], since: datetime, tz: Any
            ) -> Tuple[Dict[str, Set[date]], Dict[str, List[datetime]]]:
    """Each guest's check-in days since `since` on the church's clock (their
    own attendance, and the kids desk for a family they're an adult in),
    and their own attendance times (New here's invite rule reads those)."""
    b = _q(biz_id)
    ids = sorted({str(i) for i in ids})
    days: Dict[str, Set[date]] = {i: set() for i in ids}
    times: Dict[str, List[datetime]] = {i: [] for i in ids}
    if not ids:
        return days, times
    for r in _all_in(f"/attendance?business_id=eq.{b}&{_between('checked_in_at', since)}"
                     "&select=id,contact_id,checked_in_at", "contact_id", ids):
        t, cid = _parse(r.get("checked_in_at")), str(r.get("contact_id"))
        if t and cid in days:
            days[cid].add(t.astimezone(tz).date())
            times[cid].append(t)
    homes = _all_in(f"/household_adults?business_id=eq.{b}&select=household_id,contact_id", "contact_id", ids,
                    order="household_id.asc,contact_id.asc")
    adults_of: Dict[str, Set[str]] = {}
    for h in homes:
        adults_of.setdefault(str(h["household_id"]), set()).add(str(h["contact_id"]))
    if adults_of:
        for r in _all_in(f"/child_checkins?business_id=eq.{b}&{_between('checked_in_at', since)}"
                         "&select=id,household_id,checked_in_at", "household_id", adults_of):
            t = _parse(r.get("checked_in_at"))
            if not t:
                continue
            for cid in adults_of.get(str(r.get("household_id")), ()):
                if cid in days:
                    days[cid].add(t.astimezone(tz).date())
    return days, times


def _place_visits(g: Dict[str, Any], days: Set[date], tz: Any) -> None:
    """first_day, visit days, came_back and third for one guest."""
    seen = set(days)
    if g["text_again"]:
        seen.add(g["texted"].astimezone(tz).date())     # texting the word again is a visit
    if g["planned"]:
        mine = sorted(d for d in seen if d >= g["start_day"])
        g["first_day"] = mine[0] if mine else None
        g["expected"] = not mine
    else:
        mine = sorted({g["start_day"]} | {d for d in seen if d >= g["start_day"]})
        g["first_day"] = g["start_day"]
        g["expected"] = False
    g["visit_days"] = mine
    g["came_back"] = len(mine) >= 2
    g["third"] = len(mine) >= 3


# ─── Notes and follow-ups ─────────────────────────────────────────────

def _notes(biz_id: str, fids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for n in _all_in(f"/church_follow_up_notes?business_id=eq.{_q(biz_id)}"
                     f"&kind=in.({','.join(OUTCOME_KINDS)})&select={NOTE_SELECT}", "follow_up_id", fids,
                     order="created_at.asc,id.asc"):
        out.setdefault(str(n["follow_up_id"]), []).append(n)
    for ns in out.values():
        ns.sort(key=lambda n: str(n.get("created_at") or ""))
    return out


def _names(biz_id: str, ids: Iterable[str]) -> Dict[str, str]:
    return {str(r["id"]): _plain(r.get("name"))
            for r in _all_in(f"/contacts?business_id=eq.{_q(biz_id)}&select=id,name", "id", ids)}


def _handed_at(f: Dict[str, Any]) -> Optional[datetime]:
    return _parse(f.get("assigned_at")) or _parse(f.get("created_at"))


def _first_reached(notes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((n for n in notes if n.get("kind") in cfu.REACHED), None)


def _fu_view(f: Dict[str, Any], notes: List[Dict[str, Any]], names: Dict[str, str], now: datetime
             ) -> Dict[str, Any]:
    steps = f.get("steps") or []
    step = int(f.get("step") or 0)
    due = _parse(f.get("due_at"))
    status = str(f.get("status") or "")
    late = bool(status == "open" and due and due < now)
    lid = str(f.get("leader_contact_id") or "")
    caller = names.get(lid, "") if lid else ""
    reached = _first_reached(notes)
    last = notes[-1] if notes else None
    last_reached = next((n for n in reversed(notes) if n.get("kind") in cfu.REACHED), None)
    return {
        "id": str(f["id"]), "status": status, "step": step,
        "step_title": str(steps[step].get("title") or "") if step < len(steps) else "",
        "due_at": f.get("due_at"), "late": late, "late_days": int((now - due).total_seconds() // 86400) if late else 0,
        "caller": {"id": lid, "name": caller, "initials": cfu.initials(caller) if caller else ""} if lid else None,
        "last_outcome": ({"kind": last.get("kind"), "words": OUTCOME_WORDS.get(str(last.get("kind")), ""),
                          "at": last.get("created_at")} if last else None),
        "reached": bool(reached), "reached_at": reached.get("created_at") if reached else None,
        "reached_words": OUTCOME_WORDS.get(str(last_reached.get("kind")), "") if last_reached else "",
        "card_name": str(f.get("card_name") or ""), "card_key": str(f.get("card_key") or ""),
    }


# ─── New here's texts ─────────────────────────────────────────────────

def _scheduled(biz_id: str, ids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in _all_in(f"/chief_scheduled_actions?business_id=eq.{_q(biz_id)}&action->>type=eq.new_here_text"
                     "&select=id,action,run_at,status,last_run_at", "action->>contact_id", ids):
        out.setdefault(str((r.get("action") or {}).get("contact_id")), []).append(r)
    return out


def _messages(biz_id: str, ids: Iterable[str], since: datetime) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for m in _all_in(f"/sms_messages?business_id=eq.{_q(biz_id)}&{_between('created_at', since)}"
                     "&select=id,contact_id,direction,read,created_at", "contact_id", ids):
        out.setdefault(str(m.get("contact_id")), []).append(m)
    return out


def texts_ok(meta: Dict[str, Any]) -> bool:
    """New here's texts go to this guest: they said yes (texts_ok), or they
    texted the word (the text door, which New here's texts were made for)."""
    if meta.get("texts_ok") is True:
        return True
    return bool(meta.get("texted_at")) and str(meta.get("door") or "text") == "text"


def _text_state(row: Optional[Dict[str, Any]], outbound: Optional[List[datetime]]) -> Tuple[str, Any]:
    if not row:
        return "off", None
    status = str(row.get("status") or "")
    if status == "queued":
        return "waiting", row.get("run_at")
    if status == "done":
        ran = _parse(row.get("last_run_at"))
        if outbound is None or not ran:
            return "done", row.get("last_run_at")
        sent = any(abs((t - ran).total_seconds()) <= SENT_WINDOW.total_seconds() for t in outbound)
        return ("done" if sent else "skipped"), row.get("last_run_at")
    if status == "failed":
        return "missed", row.get("last_run_at")
    return "skipped", row.get("last_run_at")


def _texts(g: Dict[str, Any], rows: Optional[List[Dict[str, Any]]], msgs: Optional[List[Dict[str, Any]]],
           fu: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = g["meta"]
    ok = texts_ok(meta)
    texted = str(meta.get("texted_at") or "")
    outbound = None if msgs is None else [t for t in (_parse(m.get("created_at")) for m in msgs
                                                       if m.get("direction") == "outbound") if t]
    steps = []
    for key in STEPS:
        if key == "welcome":
            state, at = ("done", meta.get("texted_at")) if ok else ("off", None)
        elif key == "call":
            if not fu:
                state, at = "off", None
            elif fu["reached"]:
                state, at = "done", fu["reached_at"]
            elif fu["status"] in ("open", "handed_back"):
                state, at = ("waiting", fu["due_at"]) if fu["step"] == 0 else ("done", None)
            else:
                state, at = "skipped", None
        elif rows is None:
            state, at = "unknown", None
        else:
            mine = [r for r in rows if str((r.get("action") or {}).get("step")) == key]
            this_visit = [r for r in mine if str((r.get("action") or {}).get("texted_at") or "") == texted]
            pick = sorted(this_visit or mine, key=lambda r: str(r.get("run_at") or ""))
            state, at = _text_state(pick[-1] if pick else None, outbound)
        steps.append({"key": key, "label": STEP_WORDS[key], "state": state, "at": at})
    return {"ok": ok, "steps": steps}


def _reply_waiting(g: Dict[str, Any], msgs: Optional[List[Dict[str, Any]]]) -> Optional[datetime]:
    """When the guest's oldest unread reply came in (after the word itself),
    or None."""
    if g["hold"]:
        return _parse(g["meta"].get("hold_since")) or g["start"]
    if not msgs:
        return None
    after = g["start"] + REPLY_GRACE
    waiting = sorted(t for t in (_parse(m.get("created_at")) for m in msgs
                                 if m.get("direction") == "inbound" and m.get("read") is False) if t and t > after)
    return waiting[0] if waiting else None


# ─── The status line ──────────────────────────────────────────────────

def status_of(g: Dict[str, Any], tz: Any, now: datetime) -> Dict[str, str]:
    """{tone, line, sub}: need (someone has something to do), ok, calm."""
    fu = g.get("follow_up")
    if g.get("reply_at"):
        return {"tone": "need", "line": "Texted back: waiting on you", "sub": "Their reply is in Text"}
    if g.get("expected"):
        caller = ((fu or {}).get("caller") or {}).get("name") or ""
        return {"tone": "calm", "line": "Planning a visit",
                "sub": f"{caller} has them" if caller else ("No one has them yet" if fu else "")}
    if not fu:
        if g["door"] == "text":
            return {"tone": "calm", "line": "Waiting on their card", "sub": "Their call starts when they send it"}
        return {"tone": "calm", "line": "No follow-up yet", "sub": ""}
    caller = (fu.get("caller") or {}).get("name") or ""
    last = fu.get("last_outcome") or {}
    if fu["status"] == "handed_back":
        return {"tone": "need", "line": "Handed back", "sub": f"{caller} handed them back" if caller else ""}
    if fu["status"] == "open" and not fu.get("caller"):
        return {"tone": "need", "line": "No one has them yet", "sub": "Hand them to someone on the Follow-up board"}
    if fu["reached"]:
        sub = f"Next: {fu['step_title']}" if fu["status"] == "open" and fu["step_title"] else (
            "Done" if fu["status"] == "done" else "")
        return {"tone": "ok", "line": fu["reached_words"] or "Talked", "sub": sub}
    if fu["status"] == "open" and fu["step"] == 0:
        due = _parse(fu.get("due_at"))
        tried = last.get("words") if last.get("kind") in ("noanswer", "notnow") else ""
        if fu["late"] and due:
            return {"tone": "need", "line": f"Call is {late_words(due, now)}",
                    "sub": tried or (f"{caller} has them" if caller else "")}
        return {"tone": "need", "line": f"Call by {when_words(due, tz, now)}" if due else "To call",
                "sub": tried or (f"{caller} has them" if caller else "")}
    if fu["status"] == "open":
        return {"tone": "ok", "line": "Reached", "sub": f"Next: {fu['step_title']}" if fu["step_title"] else ""}
    return {"tone": "calm", "line": "Done" if fu["status"] == "done" else "Closed", "sub": ""}


def _shown(g: Dict[str, Any], tz: Any, now: datetime) -> Dict[str, Any]:
    """A guest as the room reads it."""
    out = {k: g[k] for k in ("id", "name", "initials", "family", "door", "door_words", "planned", "hold",
                             "came_back", "third", "expected")}
    out.update({
        "start_at": _iso(g["start"]), "first_day": g["first_day"].isoformat() if g.get("first_day") else None,
        "visits": len(g.get("visit_days") or []),
        "follow_up": g.get("follow_up"), "texts": g.get("texts"),
        "reply_waiting": bool(g.get("reply_at")),
        "status": status_of(g, tz, now),
    })
    return out


# ─── This week ────────────────────────────────────────────────────────

def _empty_counts() -> Dict[str, Any]:
    return {"new": 0, "called": 0, "to_call": 0, "late": 0, "to_call_by": None, "came_back": 0, "planned": 0}


def _texts_this_week(biz_id: str, tz: Any, now: datetime, guests: Dict[str, Dict[str, Any]],
                     att_times: Dict[str, List[datetime]]) -> List[Dict[str, Any]]:
    """New here's texts set to go in the next 7 days, by step and day. An
    invite to a guest who came back since (new_here's own rule: a check-in
    20 hours or more after their text) is said to be skipped, by name."""
    rows = _all(f"/chief_scheduled_actions?business_id=eq.{_q(biz_id)}&action->>type=eq.new_here_text"
                f"&status=eq.queued&{_between('run_at', now, now + timedelta(days=WEEK_DAYS))}"
                "&select=id,action,run_at", order="run_at.asc,id.asc")
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in rows:
        act = r.get("action") or {}
        step, at = str(act.get("step") or ""), _parse(r.get("run_at"))
        if step not in TEXT_STEPS or not at:
            continue
        local = at.astimezone(tz)
        e = out.setdefault((local.date().isoformat(), step), {
            "step": step, "words": STEP_WORDS[step], "day": local.date().isoformat(), "at": _iso(at),
            "when": f"{local.strftime('%a')} {_clock(local)}", "count": 0, "skip": 0, "skip_names": []})
        e["count"] += 1
        cid = str(act.get("contact_id") or "")
        texted = _parse(act.get("texted_at"))
        if step == "invite" and texted and cid in att_times and any(
                t >= texted + INVITE_SKIP_AFTER for t in att_times[cid]):
            e["skip"] += 1
            g = guests.get(cid)
            if g and g["name"] and len(e["skip_names"]) < 3:
                e["skip_names"].append(g["name"])
    return sorted(out.values(), key=lambda e: e["at"])


def _chief_did(biz_id: str, fids: Iterable[str]) -> List[Dict[str, Any]]:
    """Chief's History lines (church_history) about these guests' follow-ups,
    newest first, at most FEED_MAX, in their own words (a History line never
    names whom a card is about)."""
    got: List[Dict[str, Any]] = []
    for part in _chunks(fids):
        got += _need(f"/audit_log?business_id=eq.{_q(biz_id)}&actor_id=eq.church&target_type=eq.church_follow_up"
                     f"&target_id=in.({','.join(_q(v) for v in part)})&select=id,verb,summary,created_at"
                     f"&order=created_at.desc&limit={FEED_MAX}")
    got.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return [{"verb": r.get("verb"), "line": _plain(r.get("summary")), "at": r.get("created_at")}
            for r in got[:FEED_MAX] if _plain(r.get("summary"))]


def next_move(listed: List[Dict[str, Any]], unlisted_waiting: int, now: datetime) -> Dict[str, Any]:
    """The one thing to do first, the same every time for the same week: a
    guest's reply waiting, then the longest-late call, then anyone with no
    one, else calm."""
    def who(g: Dict[str, Any]) -> str:
        return g["name"] or "A guest"

    replies = sorted((g for g in listed if g.get("reply_at")), key=lambda g: g["reply_at"])
    if replies:
        g = replies[0]
        return {"kind": "answer", "guest_id": g["id"], "follow_up_id": (g.get("follow_up") or {}).get("id"),
                "line": f"{who(g)} texted back, and the reply is waiting.",
                "detail": "Read it in Text and answer them.",
                "action": f"Answer {_first(g['name'])}" if g["name"] else "Answer them"}
    late = [g for g in listed if (g.get("follow_up") or {}).get("late") and (g["follow_up"] or {}).get("step") == 0
            and g["follow_up"].get("status") == "open" and g["follow_up"].get("caller")]
    if late:
        g = min(late, key=lambda g: str(g["follow_up"].get("due_at") or ""))
        fu = g["follow_up"]
        due = _parse(fu.get("due_at")) or now
        last = (fu.get("last_outcome") or {}).get("kind")
        detail = f"{fu['caller']['name'] or 'Their caller'} has them."
        if last in ("noanswer", "notnow"):
            detail += f" Last try: {OUTCOME_WORDS[last]}."
        return {"kind": "call", "guest_id": g["id"], "follow_up_id": fu["id"],
                "line": f"{who(g)}'s welcome call is {late_words(due, now)}.", "detail": detail,
                "action": "Open Follow-up"}
    nobody = [g for g in listed if (g.get("follow_up") or {}).get("status") == "handed_back"
              or ((g.get("follow_up") or {}).get("status") == "open" and not g["follow_up"].get("caller"))]
    if nobody:
        g = min(nobody, key=lambda g: g["start"])
        fu = g["follow_up"]
        detail = (f"{fu['caller']['name']} handed them back." if fu.get("status") == "handed_back" and fu.get("caller")
                  and fu["caller"].get("name") else "Hand them to someone on the Follow-up board.")
        return {"kind": "hand_on", "guest_id": g["id"], "follow_up_id": fu["id"],
                "line": f"{who(g)} has no one to call them yet.", "detail": detail,
                "action": f"Hand {_first(g['name'])} on" if g["name"] else "Hand them on"}
    if not listed:
        return {"kind": "calm", "line": "No new guests this week yet.",
                "detail": "When a guest comes through any door, they show here.", "action": ""}
    if unlisted_waiting:
        n = unlisted_waiting
        return {"kind": "calm", "line": "Nothing is late.",
                "detail": f"{n} {'guest hasn’t' if n == 1 else 'guests haven’t'} sent their card yet, "
                          "so no one has them to call.", "action": ""}
    return {"kind": "calm", "line": "Every guest this week has someone to call them.",
            "detail": "Nothing is late.", "action": ""}


def this_week(biz: Dict[str, Any], *, user: Any = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    tz = _tz(biz)
    now = now or _now()
    since = now - timedelta(days=RECENT_DAYS)
    week = now - timedelta(days=WEEK_DAYS)
    contacts, fus_by = _gather(biz_id, since)
    cores = {cid: g for cid, g in ((cid, _core(c, fus_by.get(cid, []), tz)) for cid, c in contacts.items()) if g}
    # Started before the window (a record from long ago with a new signal):
    # not new, and not this room's to count.
    cores = {cid: g for cid, g in cores.items() if g["start"] >= since}
    ids = sorted(cores)
    days, att_times = _visits(biz_id, ids, since - timedelta(days=1), tz)
    for cid, g in cores.items():
        _place_visits(g, days.get(cid, set()), tz)
    fus = {g["fu_row"]["id"]: g["fu_row"] for g in cores.values() if g["fu_row"]}
    all_fids = [str(f["id"]) for g in cores.values() for f in g["fus"]]
    notes = _notes(biz_id, fus)
    names = _names(biz_id, {str(f.get("leader_contact_id")) for f in fus.values() if f.get("leader_contact_id")})
    sched = _soft(lambda: _scheduled(biz_id, ids))
    msgs = _soft(lambda: _messages(biz_id, ids, since))
    for cid, g in cores.items():
        g["follow_up"] = _fu_view(g["fu_row"], notes.get(str(g["fu_row"]["id"]), []), names, now) \
            if g["fu_row"] else None
        mine = None if msgs is None else msgs.get(cid, [])
        g["texts"] = _texts(g, None if sched is None else sched.get(cid, []), mine, g["follow_up"])
        g["reply_at"] = _reply_waiting(g, mine)

    def latest_later(g: Dict[str, Any]) -> Optional[date]:
        later = [d for d in g["visit_days"] if g.get("first_day") and d > g["first_day"]]
        return later[-1] if later else None

    week_day = week.astimezone(tz).date()
    came_back, new, planned = [], [], []
    for g in cores.values():
        back = latest_later(g)
        if g["came_back"] and back and back >= week_day:
            came_back.append(g)
        elif g["expected"]:
            if g["start"] >= now - timedelta(days=PLANNED_DAYS):
                planned.append(g)
        elif g["start"] >= week:
            new.append(g)
    for group in (came_back, new, planned):
        group.sort(key=lambda g: g["start"], reverse=True)
    listed = came_back + new
    shown = listed + planned
    this_weeks = [g for g in listed if g["start"] >= week and not g["expected"]]
    to_call = [g for g in shown if (g.get("follow_up") or {}).get("status") == "open"
               and g["follow_up"]["step"] == 0 and not g["follow_up"]["reached"]]
    upcoming = sorted(str(g["follow_up"]["due_at"]) for g in to_call
                      if g["follow_up"].get("due_at") and not g["follow_up"]["late"])
    counts = {
        "new": len(this_weeks),
        "called": sum(1 for g in this_weeks if (g.get("follow_up") or {}).get("reached")),
        "to_call": len(to_call),
        "late": sum(1 for g in to_call if g["follow_up"]["late"]),
        "to_call_by": upcoming[-1] if upcoming else None,
        "to_call_by_words": (_parse(upcoming[-1]).astimezone(tz).strftime("%a") if upcoming else ""),
        "came_back": len(came_back),
        "planned": len(planned),
    }
    waiting_cards = sum(1 for g in shown if not g.get("follow_up") and g["door"] == "text")
    you_do: Optional[bool] = None
    if user is not None:
        try:
            import church_duties
            you_do = bool(church_duties.holds(biz_id, user, guest_path.FIRST_GUESTS))
        except Exception:  # noqa: BLE001 — a duty that can't be read decides nothing
            you_do = None
    return {
        "on": True,
        "church": {"name": _plain(biz.get("name")), "tz": str(getattr(tz, "key", "") or "")},
        "today": now.astimezone(tz).date().isoformat(),
        "you_do_first_guests": you_do,
        "counts": counts,
        "groups": [
            {"key": "new", "title": "New this week", "legend": " · ".join(STEP_WORDS[s] for s in STEPS),
             "guests": [_shown(g, tz, now) for g in new]},
            {"key": "came_back", "title": "Came back", "legend": "Second visit and after",
             "guests": [_shown(g, tz, now) for g in came_back]},
            {"key": "planned", "title": "Planning a visit", "legend": "Sent a Plan your visit card",
             "guests": [_shown(g, tz, now) for g in planned]},
        ],
        "next_move": next_move(shown, waiting_cards, now),
        "texts_this_week": _soft(lambda: _texts_this_week(biz_id, tz, now, cores, att_times)),
        "texts_read": sched is not None and msgs is not None,
        "chief_did": _soft(lambda: _chief_did(biz_id, all_fids)),
        "doors": dict(guest_path.DOORS),
        "steps": [{"key": s, "label": STEP_WORDS[s]} for s in STEPS],
    }


# ─── The scorecard ────────────────────────────────────────────────────

def period_of(period: str, now: datetime, tz: Any) -> Dict[str, Any]:
    """[from, to) on the church's clock, with its words."""
    today = now.astimezone(tz).date()
    if period == "month":
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        return {"from": start, "to": end, "label": "This month", "span": MONTHS[start.month - 1]}
    if period == "year":
        start = date(today.year, 1, 1)
        return {"from": start, "to": date(today.year + 1, 1, 1), "label": "This year", "span": str(today.year)}
    name, months = next((n, m) for n, m in SEASONS if today.month in m)
    year = today.year - 1 if today.month in (1, 2) else today.year
    start = date(year, months[0], 1)
    end_month = months[-1] + 1
    end = date(year + (1 if name == "winter" else 0), end_month, 1) if end_month <= 12 else date(year + 1, 1, 1)
    return {"from": start, "to": end, "label": f"This {name}",
            "span": f"{MONTHS[months[0] - 1]} to {MONTHS[months[-1] - 1]}"}


def due_days_of(biz: Dict[str, Any]) -> int:
    """The church's call window (guest_calls.py's settings key): 1, 2 or 3
    days, 2 unless it picked another."""
    saved = ((biz.get("settings") or {}).get("guest_calls") or {}) if isinstance(biz.get("settings"), dict) else {}
    try:
        n = int((saved if isinstance(saved, dict) else {}).get("due_days") or DEFAULT_DUE_DAYS)
    except (TypeError, ValueError):
        n = DEFAULT_DUE_DAYS
    return n if n in (1, 2, 3) else DEFAULT_DUE_DAYS


def _backup_id(biz: Dict[str, Any]) -> str:
    saved = (biz.get("settings") or {}).get("guest_calls") if isinstance(biz.get("settings"), dict) else None
    backup = (saved or {}).get("backup") if isinstance(saved, dict) else None
    return str((backup or {}).get("contact_id") or "") if isinstance(backup, dict) else ""


def _connected(biz_id: str, first_day: Dict[str, date], tz: Any) -> Set[str]:
    """Guests who joined a group, a class or a team on or after their first
    visit (see the module's definition)."""
    b = _q(biz_id)
    ids = sorted(first_day)
    out: Set[str] = set()
    if not ids:
        return out
    members = _all_in(f"/group_members?business_id=eq.{b}&select=group_id,contact_id,joined_on,created_at",
                      "contact_id", ids, order="group_id.asc,contact_id.asc")
    group_ids = {str(m["group_id"]) for m in members}
    active = {str(g["id"]) for g in _all_in(f"/groups?business_id=eq.{b}&active=is.true&select=id,kind",
                                            "id", group_ids)} if group_ids else set()
    for m in members:
        cid = str(m.get("contact_id"))
        joined = _day(m.get("joined_on")) or ((_parse(m.get("created_at")) or _now()).astimezone(tz).date())
        if str(m.get("group_id")) in active and cid in first_day and joined >= first_day[cid]:
            out.add(cid)
    for e in _all_in(f"/academy_enrollments?business_id=eq.{b}&status=in.(active,completed)"
                     "&select=id,contact_id,enrolled_at", "contact_id", ids):
        cid, at = str(e.get("contact_id")), _parse(e.get("enrolled_at"))
        if cid in first_day and at and at.astimezone(tz).date() >= first_day[cid]:
            out.add(cid)
    return out


def _guests_word(n: int) -> str:
    return "guest" if n == 1 else "guests"


def read_line(n: int, connected: Optional[int], came_back: int, doors: List[Dict[str, Any]], label: str) -> str:
    """One plain sentence that is true of the numbers it sits above."""
    when = label[0].lower() + label[1:]
    if not n:
        return f"No first-time guests {when} yet."
    if connected is None:
        out = f"Of {n} first-time {_guests_word(n)} {when}, {came_back} came back."
    else:
        out = (f"Of {n} first-time {_guests_word(n)} {when}, {connected} "
               f"{'is' if connected == 1 else 'are'} now in a group, a class or a team.")
    big = [d for d in doors if d["guests"] >= 3]
    if len(big) >= 2:
        low = min(big, key=lambda d: (d["came_back"] / d["guests"], -d["guests"]))
        best = max(d["came_back"] / d["guests"] for d in big)
        if low["came_back"] / low["guests"] < best:
            out += f" {low['words']}: {low['came_back']} of {low['guests']} came back, the fewest of any door."
    return out


def scorecard(biz: Dict[str, Any], period: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    tz = _tz(biz)
    now = now or _now()
    span = period_of(period, now, tz)
    since = datetime.combine(span["from"], time(0, 0), tzinfo=tz)
    until = datetime.combine(span["to"], time(0, 0), tzinfo=tz)
    contacts, fus_by = _gather(biz_id, since, until)
    cores = {cid: g for cid, g in ((cid, _core(c, fus_by.get(cid, []), tz)) for cid, c in contacts.items()) if g}
    cores = {cid: g for cid, g in cores.items() if since <= g["start"] < until}
    days, _times = _visits(biz_id, sorted(cores), since - timedelta(days=1), tz)
    for cid, g in cores.items():
        _place_visits(g, days.get(cid, set()), tz)
    guests = [g for g in cores.values() if not g["expected"]]
    fus = [f for g in guests for f in g["fus"]]
    notes = _notes(biz_id, [str(f["id"]) for f in fus])
    due_days = due_days_of(biz)
    window = timedelta(days=due_days)

    def first_call(g: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """(the follow-up, its first reached note) for a guest's welcome call:
        the earliest reached note across their welcome follow-ups."""
        best = None
        for f in g["fus"]:
            n = _first_reached(notes.get(str(f["id"]), []))
            if n and (best is None or str(n.get("created_at")) < str(best[1].get("created_at"))):
                best = (f, n)
        return best

    def on_time(pair: Optional[Tuple[Dict[str, Any], Dict[str, Any]]]) -> bool:
        if not pair:
            return False
        handed, said = _handed_at(pair[0]), _parse(pair[1].get("created_at"))
        return bool(handed and said and said - handed <= window)

    calls = {g["id"]: first_call(g) for g in guests}
    called = {gid for gid, pair in calls.items() if on_time(pair)}
    connected = _soft(lambda: _connected(biz_id, {g["id"]: g["first_day"] for g in guests if g.get("first_day")}, tz))
    n = len(guests)
    came_back = sum(1 for g in guests if g["came_back"])
    funnel = [
        {"key": "guests", "label": "First-time guests", "n": n},
        {"key": "called", "label": f"Called within {due_days} {'day' if due_days == 1 else 'days'}", "n": len(called)},
        {"key": "came_back", "label": "Came back", "n": came_back},
        {"key": "third", "label": "Came a third time", "n": sum(1 for g in guests if g["third"])},
        {"key": "connected", "label": "Connected", "n": None if connected is None else len(connected)},
    ]
    doors: List[Dict[str, Any]] = []
    for key in list(guest_path.DOORS) + [""]:
        mine = [g for g in guests if (g["door"] if g["door"] in guest_path.DOORS else "") == key]
        if mine:
            doors.append({"door": key, "words": DOOR_WORDS.get(key) or "Other", "guests": len(mine),
                          "called": sum(1 for g in mine if g["id"] in called),
                          "came_back": sum(1 for g in mine if g["came_back"])})
    backup = _backup_id(biz)
    by_caller: Dict[str, Dict[str, Any]] = {}
    for gid, pair in calls.items():
        if not pair:
            continue
        note = pair[1]
        key = str(note.get("author_contact_id") or "") or f"name:{_plain(note.get('author_name'))}"
        e = by_caller.setdefault(key, {"id": str(note.get("author_contact_id") or ""),
                                       "name": _plain(note.get("author_name")), "calls": 0, "on_time": 0})
        e["calls"] += 1
        e["on_time"] += int(gid in called)
    missing = [e["id"] for e in by_caller.values() if e["id"] and not e["name"]]
    if missing:
        names = _names(biz_id, missing)
        for e in by_caller.values():
            e["name"] = e["name"] or names.get(e["id"], "")
    callers = sorted(({**e, "name": e["name"] or "Someone", "backup": bool(backup and e["id"] == backup)}
                      for e in by_caller.values()), key=lambda e: (-e["calls"], e["name"]))

    def unreached(g: Dict[str, Any]) -> bool:
        if not g["fus"] or calls.get(g["id"]):
            return False
        f = g["fus"][-1]
        due = _parse(f.get("due_at"))
        return f.get("status") not in ("open", "handed_back") or bool(due and due < now)

    not_reached = sum(1 for g in guests if unreached(g))
    no_call_yet = sum(1 for g in guests if not g["fus"])
    return {
        "on": True,
        "period": period, "label": span["label"], "span": span["span"],
        "from": span["from"].isoformat(), "to": span["to"].isoformat(),
        "due_days": due_days,
        "funnel": funnel,
        "doors": doors,
        "callers": callers,
        "not_reached": not_reached,
        "no_follow_up": no_call_yet,
        "read": read_line(n, None if connected is None else len(connected), came_back, doors, span["label"]),
        "connected_means": ("Joined a group, a class or a team in Groups, or a class in the Academy, "
                            "on or after their first visit."),
    }


# ─── The routes ───────────────────────────────────────────────────────

def _unread() -> HTTPException:
    return HTTPException(503, "The guests couldn't be read just now. Try again in a minute.")


@router.get("/church/guests/{business_id}/status")
def get_status(business_id: str, biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
               session: UserSession = Depends(sb_clients.authed_request)):
    """Whether this login has the Guests room: the menu asks this once (the
    same gate as the room, without reading a single guest). A no is the
    room's own 404 or 403."""
    _gate(biz, session)
    return {"open": True}


@router.get("/church/guests/{business_id}")
def get_guests(business_id: str, biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
               session: UserSession = Depends(sb_clients.authed_request)):
    """The Guests room's This week (see the module docstring)."""
    _gate(biz, session)
    try:
        return this_week(biz, user=session.user)
    except Unread as e:
        print(f"[church_guests] this week unread ({e}) business={str(biz.get('id'))[:8]}", flush=True)
        raise _unread()


@router.get("/church/guests/{business_id}/scorecard")
def get_scorecard(business_id: str, period: str = Query("season", max_length=10),
                  biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
                  session: UserSession = Depends(sb_clients.authed_request)):
    """The Guests room's Scorecard (see the module docstring)."""
    _gate(biz, session)
    if period not in PERIODS:
        raise HTTPException(400, "The period is month, season or year.")
    try:
        return scorecard(biz, period)
    except Unread as e:
        print(f"[church_guests] scorecard unread ({e}) business={str(biz.get('id'))[:8]}", flush=True)
        raise _unread()
