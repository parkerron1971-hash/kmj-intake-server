"""
member_asks.py — Ask the church: a member's path to ask the church for things.

Kevin, 2026-10-27, after the office's Rooms & spaces, Pledges & campaigns,
the member directory and the church calendar shipped: "we need to create a
path for members to be able to request these things from the church app as
well." Lane: Build, under the Build item "Love City leaves Subsplash (M-1)".

Every ask lands in the office queue that already handles it. Nothing new
for the office to learn:

    ASK                 LANDS IN                                 WHO HEARS
    room ............   church_space_bookings, status requested,  the office
                        kind use, for the member (Rooms & spaces'
                        requests waiting for a yes)
    help ............   ministry_care_requests, kind "help",      People & care
                        confidential (Prayer & care, marked Help)
    visit ...........   ministry_care_requests, kind "visit"      People & care
    life_event ......   ministry_care_requests, kind "life_event" People & care
                        with the event (a wedding, a funeral, a
                        dedication, a baptism). No register yet.
    pledge ..........   church_pledges (one per giver per         the owner, admins
                        campaign), recorded_by = the member's     and the accountant
                        own contact id (their sign-in is a person,
                        not a login)
    event ...........   a link to the member Events page (/my/events), which
                        already signs people up (events_rsvp_router's rules)

Prayer has its own page (/my/prayer); Ask links to it.

THE KINDS ARE A CONTRACT. Care rows carry submission.kind = "help" | "visit"
| "life_event" (KIND_HELP etc. below) and submission.source = SOURCE (or
SOURCE_YOUTH). Prayer & care and the help-requests work read them; keep
them stable.

THE RULES
  · Off until the church turns asks on, one by one (Settings > Member page >
    What members can ask for; the owner only). Members see only what's on,
    and only what the church's features support: a room only while Rooms &
    spaces is open for the church and it has an active room; a pledge only
    while Pledges & campaigns is open and a campaign hasn't ended.
  · Who and which church come from the member's session, never the form. A
    member can't book for someone else, can't say "booked", can't pick a
    contact, a church or a status.
  · A room shows free and busy only: never another booking's title or who.
    A time over a booked one is refused without saying what's there.
  · Help, visits and life events are private: confidential, never shared
    with the prayer team, and the alerts about them carry no name and no
    words.
  · Minors (MINORS): a teen (13 to 17 by birthdate) or anyone the office
    marks as a child (member_directory.is_minor: a child on a family, a teen
    linked to a parent, a youth/kids tag) gets Ask with only prayer and help,
    and help goes the youth way (pastors only, marked Youth). Under 13 there
    is no sign-in. The Kids space, and an adult leader who switched into
    Youth, are sent back to /my: Ask lives in Church.
  · Rate-limited per member (member_ask, member_ask_day), on top of the
    member app's own (member_action), so one member can't flood the office.

THE SWITCH. CHURCH_MEMBER_ASKS = off | owner | on, owner until a Thursday
(the church_keys pattern). With owner, only the platform owner sees the
office section and only a church whose owner is the platform owner may turn
asks on; members of any other church see nothing. Off hides it all. The
app's own switch is askRollout.ts (OPEN_TO_EVERYONE).

STORAGE (no migration)
  businesses.settings.member_portal.asks = {"on": [ask keys], "at", "by"}

ROUTES
  GET  /my/ask, /my/ask/{room,help,visit,life,pledge}   (member_portal.serve)
  POST /my/ask/room       {space, day, start, end, reason}
  POST /my/ask/care       {kind: help|visit|life_event, pick, text, date?, wants_call?}
  POST /my/ask/pledge     {campaign, how: total|weekly|biweekly|monthly, amount, times?, note?, request_id?}
  GET  /member-portal/{biz}/asks    the office's view (owner or an admin seat)
  PUT  /member-portal/{biz}/asks    {on: [ask keys]} (owner only)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("member_asks")
router = APIRouter(tags=["member-portal"])

KEY = "asks"
ASKS = ("room", "help", "visit", "life_event", "pledge", "event")
CARE = ("help", "visit", "life_event")
YOUTH_ASKS = ("help",)
KIND_HELP, KIND_VISIT, KIND_LIFE = "help", "visit", "life_event"
SOURCE = "Member app, Ask the church"
SOURCE_YOUTH = "Member app, Youth"

# What each care ask offers to pick (the word the office reads is the value).
PICKS: Dict[str, Dict[str, str]] = {
    "help": {"food": "Food", "bill": "A bill", "ride": "A ride", "other": "Something else"},
    "visit": {"talk": "Talk with a pastor", "home": "A home visit", "hospital": "A hospital visit"},
    "life_event": {"wedding": "A wedding", "funeral": "A funeral", "dedication": "A baby dedication",
                   "baptism": "A baptism"},
}
# The submission field each care ask's pick is kept in.
PICK_FIELD = {"help": "need", "visit": "visit", "life_event": "life_event"}
PAGE_OF = {"help": "help", "visit": "visit", "life_event": "life"}

TEXT_MAX = 2000
REASON_MAX = 300
NOTE_MAX = 500
DAYS_AHEAD = 365
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLOCK_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$")

# The office's words for each ask (the app's section reads them too).
CHOICES: Dict[str, Dict[str, str]] = {
    "room": {"label": "Book a room", "hint": "A member picks a room, a day and a time, and says what it's for.",
             "lands": "Rooms & spaces, in the requests waiting for a yes", "hears": "The office"},
    "help": {"label": "Ask for help", "hint": "Food, a bill, a ride or something else. Private.",
             "lands": "Prayer & care, marked Help and kept confidential", "hears": "People & care"},
    "visit": {"label": "Talk to a pastor", "hint": "A call, or a visit at home or in the hospital.",
              "lands": "Prayer & care, marked Visit", "hears": "People & care"},
    "life_event": {"label": "Plan a life event", "hint": "A wedding, a funeral, a baby dedication or a baptism.",
                   "lands": "Prayer & care, marked Life event, for the office to follow up",
                   "hears": "People & care"},
    "pledge": {"label": "Make a pledge", "hint": "To a campaign that's running, and see what they've given toward it.",
               "lands": "Pledges & campaigns, as their own pledge",
               "hears": "The owner, admins and the accountant"},
    "event": {"label": "Sign up for an event", "hint": "Opens the Events page, where they say they're coming.",
              "lands": "Your events, as a sign-up", "hears": "Whoever runs the event"},
}

# Where each landed ask sends the office (push_notifications nav).
NAV = {"room": "operate:spaces", "care": "operate:care", "pledge": "operate:pledges"}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _plain(v: Any, top: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:top]


def _words(v: Any, top: int) -> str:
    """A member's own words: line breaks kept, nothing past `top`."""
    s = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()[:top]


# ─── The switch ───────────────────────────────────────────────────────


def mode() -> str:
    m = (os.environ.get("CHURCH_MEMBER_ASKS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def _platform_email() -> str:
    return (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()


def open_to(user: AuthedUser) -> bool:
    """The office section, for this signed-in login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        return (user.email or "").strip().lower() == _platform_email()
    return False


_OWNER_CACHE: Dict[str, Tuple[float, bool]] = {}
OWNER_CACHE_SECONDS = 600


def platform_church(business_id: Any) -> bool:
    """Whether this church's owner is the platform owner: what an `owner`
    switch means on the member side, where nobody signs in as a login. Kept
    ten minutes per replica; a read that fails is a no (members see
    nothing rather than something not yet switched on)."""
    bid = str(business_id or "")
    hit = _OWNER_CACHE.get(bid)
    if hit and time.monotonic() - hit[0] < OWNER_CACHE_SECONDS:
        return hit[1]
    if not UUID_RE.match(bid):
        return False
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(bid)}&select=owner_id&limit=1")
    if not isinstance(rows, list) or not rows or not rows[0].get("owner_id"):
        return False
    import messaging_router
    email = messaging_router._owner_email(str(rows[0]["owner_id"]))
    if not email:
        return False
    yes = email == _platform_email()
    _OWNER_CACHE[bid] = (time.monotonic(), yes)
    return yes


def _switch_open(m: str, business_id: Any) -> bool:
    if m == "on":
        return True
    if m == "owner":
        return platform_church(business_id)
    return False


def church_open(biz: Dict[str, Any]) -> bool:
    """Asks may be served at this church at all."""
    return _switch_open(mode(), (biz or {}).get("id"))


def spaces_open(biz: Dict[str, Any]) -> bool:
    import church_spaces
    return _switch_open(church_spaces.mode(), biz.get("id"))


def pledges_open(biz: Dict[str, Any]) -> bool:
    import church_pledges
    return _switch_open(church_pledges.mode(), biz.get("id"))


# ─── The church's choices ─────────────────────────────────────────────


def turned_on(biz: Optional[Dict[str, Any]]) -> List[str]:
    """The asks this church turned on, in ASKS order. Anything odd is off."""
    cfg = ((biz or {}).get("settings") or {}).get("member_portal") or {}
    raw = cfg.get(KEY) if isinstance(cfg, dict) else None
    on = raw.get("on") if isinstance(raw, dict) else None
    if not isinstance(on, list):
        return []
    return [k for k in ASKS if k in on]


def clean_choice(raw: Any) -> Optional[List[str]]:
    """The office's list: known asks only, once each, in ASKS order. None
    for anything that isn't a list."""
    if not isinstance(raw, list):
        return None
    return [k for k in ASKS if k in {str(x) for x in raw}]


# ─── What the church's features support ───────────────────────────────

_READY: Dict[Tuple[str, str], Tuple[float, bool]] = {}
READY_SECONDS = 60


def open_rooms(biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The church's active rooms, while Rooms & spaces is open for it. A
    read that fails (or the tables before their migration) is none."""
    if not spaces_open(biz):
        return []
    rows = sb_clients.sb_get_as_service(
        f"/church_spaces?business_id=eq.{_q(biz['id'])}&active=eq.true&kind=eq.room"
        "&select=id,name,capacity,notes,sort_order&order=sort_order.asc,name.asc&limit=200")
    return [r for r in rows if isinstance(r, dict) and r.get("id")] if isinstance(rows, list) else []


def church_today(biz: Dict[str, Any]) -> date:
    import church_pledges
    return _now().astimezone(church_pledges._tz(biz)).date()


def open_campaigns(biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Campaigns that haven't ended (a pledge Sunday often comes before the
    start), while Pledges & campaigns is open for the church."""
    if not pledges_open(biz):
        return []
    import church_pledges
    rows = sb_clients.sb_get_as_service(
        f"/church_campaigns?business_id=eq.{_q(biz['id'])}&ends_on=gte.{_q(church_today(biz).isoformat())}"
        f"&select={church_pledges.CAMPAIGN_FIELDS}&order=starts_on.asc&limit=50")
    return [r for r in rows if isinstance(r, dict) and r.get("id")] if isinstance(rows, list) else []


def _ready(biz: Dict[str, Any], ask: str, *, fresh: bool = False) -> bool:
    """Whether the church's features support this ask now. Rooms and
    pledges are read (kept a minute per replica for Home and Me)."""
    if ask == "room":
        read: Callable[[Dict[str, Any]], List[Any]] = open_rooms
    elif ask == "pledge":
        read = open_campaigns
    else:
        return ask in ASKS
    key = (str(biz.get("id")), ask)
    hit = _READY.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < READY_SECONDS:
        return hit[1]
    yes = bool(read(biz))
    _READY[key] = (time.monotonic(), yes)
    return yes


def offered(biz: Dict[str, Any], *, minor: bool, fresh: bool = False) -> List[str]:
    """The asks this person sees: on at the church, supported now, and for
    a minor only YOUTH_ASKS. The church's own choices are read first: a
    church with nothing on costs no read at all."""
    on = turned_on(biz)
    if not on or not church_open(biz):
        return []
    if minor:
        on = [k for k in on if k in YOUTH_ASKS]
    return [k for k in on if _ready(biz, k, fresh=fresh)]


# ─── Who's asking (MINORS) ────────────────────────────────────────────


def minor(business_id: str, me: Dict[str, Any]) -> Optional[bool]:
    """Whether this member is a minor by the member app's rules
    (member_directory.is_minor: under 18 by birthdate, a child on a family,
    a teen linked to a parent, a youth/kids tag). None when a read failed."""
    import member_directory as mdir
    import member_spaces as msp
    if msp.is_youth(me) or msp.is_child(me):
        return True
    row = mdir.person(business_id, str(me["id"]))
    if row is None:
        return None
    if not row:
        return None
    flags = mdir.flagged(business_id, [str(me["id"])])
    if flags is None:
        return None
    return mdir.is_minor(row, flags)


_MINOR: Dict[Tuple[str, str], Tuple[float, bool]] = {}
MINOR_SECONDS = 300


def entry(biz: Dict[str, Any], me: Dict[str, Any]) -> List[str]:
    """For Home and Me: the asks to point at, by the same minor rule as the
    page, so the line never promises a teen (or anyone marked a child) more
    than the page gives. Kept five minutes per member per replica; a read
    that fails counts as a minor (the fewest asks)."""
    if not turned_on(biz) or not church_open(biz):
        return []
    key = (str(biz.get("id")), str(me.get("id")))
    hit = _MINOR.get(key)
    if hit and time.monotonic() - hit[0] < MINOR_SECONDS:
        young = hit[1]
    else:
        found = minor(key[0], me)
        young = found is not False
        if found is not None:
            _MINOR[key] = (time.monotonic(), young)
    return offered(biz, minor=young)


# ─── Telling the people who handle it ─────────────────────────────────


def _later(fn: Callable[[], None]) -> None:
    """Alerts go off the request: a slow phone alert never holds up a member."""
    threading.Thread(target=fn, daemon=True).start()


def recipients(business_id: str, area: str) -> Set[str]:
    """The logins told about an ask: the owner, and

      giving ....... admins and the church's accountant (giving_records'
                     rule: money is theirs, whatever a login's areas say)
      people_care,
      office ....... admins, and, with Who sees what on (CHURCH_AREAS), the
                     logins whose areas are the whole church or include it.

    Before Who sees what is on, nothing says who covers what, so only the
    owner and admins are told. A read that fails tells the owner alone."""
    bid = _q(business_id)
    biz = sb_clients.sb_get_as_service(f"/businesses?id=eq.{bid}&select=id,owner_id&limit=1")
    if not isinstance(biz, list) or not biz:
        return set()
    out = {str(biz[0]["owner_id"])} if biz[0].get("owner_id") else set()
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{bid}&status=eq.active&select=user_id,role&limit=500")
    if not isinstance(seats, list):
        return out
    import church_areas
    for s in seats:
        uid, role = str(s.get("user_id") or ""), s.get("role")
        if not uid:
            continue
        if role in church_areas.KEEPS_ALL:
            out.add(uid)
        elif area != "giving" and church_areas.mode() == "on":
            view = church_areas.my_areas(str(business_id), uid, role)
            if view is not None and (view.get("areas") is None or area in (view.get("areas") or [])):
                out.add(uid)
    if area == "giving":
        acc = sb_clients.sb_get_as_service(
            f"/business_collaborators?business_id=eq.{bid}&status=eq.active&role=eq.accountant&select=user_id&limit=50")
        out |= {str(r["user_id"]) for r in acc or [] if isinstance(r, dict) and r.get("user_id")}
    return out


def notify(business_id: str, area: str, title: str, body: str, nav: str, key: str,
           priority: str = "normal") -> None:
    """The bell (the office's alerts, one per ask) and a phone alert to each
    login that handles it. Never the member's words; for care and giving,
    never their name either (both are guarded areas, and the bell is the
    whole church's). Off the request; never raises."""
    def run() -> None:
        try:
            import httpx
            import notification_engine

            async def bell() -> None:
                async with httpx.AsyncClient(timeout=20) as client:
                    await notification_engine.create_urgent_alert(
                        client, str(business_id), title, body, dedup_key=key, dedup_hours=24 * 7,
                        priority=priority, suggested_action=f"Open {_DOOR.get(nav, 'the app')}")
            asyncio.run(bell())
        except Exception:
            logger.warning("member asks: the bell failed", exc_info=True)
        try:
            import push_notifications
            for uid in sorted(recipients(str(business_id), area)):
                try:
                    push_notifications.send_to_user(uid, title=title, body=body[:160], nav=nav, tag=key,
                                                    business_id=str(business_id))
                except Exception:
                    logger.warning("member asks: a phone alert failed", exc_info=True)
        except Exception:
            logger.warning("member asks: phone alerts failed", exc_info=True)
    _later(run)


_DOOR = {"operate:spaces": "Rooms & spaces", "operate:care": "Prayer & care", "operate:pledges": "Pledges & campaigns"}


# ─── Rooms ────────────────────────────────────────────────────────────


def _spaces_tz(biz: Dict[str, Any]):
    import church_spaces
    return church_spaces._tz({"biz": {"id": str(biz["id"])}})


def _day(v: Any) -> Optional[date]:
    s = str(v or "")
    if not DAY_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _clock(v: Any) -> Optional[Tuple[int, int]]:
    m = CLOCK_RE.match(str(v or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _at(day: date, hm: Tuple[int, int], tz) -> datetime:
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=tz)


def busy(biz: Dict[str, Any], space_id: str, day: date, tz) -> Optional[List[Tuple[datetime, datetime]]]:
    """The booked stretches of one room on one day, in the church's clock:
    times only, never what or who. None when the read failed."""
    import church_spaces
    lo = datetime(day.year, day.month, day.day, tzinfo=tz)
    hi = lo + timedelta(days=1)
    rows = sb_clients.sb_get_as_service(
        f"/church_space_bookings?business_id=eq.{_q(biz['id'])}&space_id=eq.{_q(space_id)}&status=eq.booked"
        f"&start_at=lt.{_q(church_spaces._iso(hi))}&end_at=gt.{_q(church_spaces._iso(lo))}"
        "&select=start_at,end_at&order=start_at.asc&limit=100")
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        s, e = church_spaces._at(r.get("start_at")), church_spaces._at(r.get("end_at"))
        if s and e:
            out.append((max(s.astimezone(tz), lo), min(e.astimezone(tz), hi)))
    return out


def my_rooms(biz: Dict[str, Any], me_id: str) -> Optional[List[Dict[str, Any]]]:
    """This member's own room asks still to come: theirs to see in full."""
    import church_spaces
    rows = sb_clients.sb_get_as_service(
        f"/church_space_bookings?business_id=eq.{_q(biz['id'])}&contact_id=eq.{_q(me_id)}"
        f"&status=in.(requested,booked,declined)&end_at=gt.{_q(church_spaces._iso(_now()))}"
        "&select=id,space_id,title,start_at,end_at,status&order=start_at.asc&limit=20")
    return rows if isinstance(rows, list) else None


def ask_room(biz: Dict[str, Any], me: Dict[str, Any], form: Dict[str, Any]) -> Tuple[bool, str, Dict[str, str]]:
    """A member's room request: (ok, code, where to land them back). The
    booking is the member's own, requested, for the church's own use;
    church_spaces checks the room, the times and the clash, as it does for
    the office."""
    import church_spaces
    rooms = {str(r["id"]): r for r in open_rooms(biz)}
    sid = str(form.get("space") or "")
    day = _day(form.get("day"))
    keep = {"space": sid if sid in rooms else "", "day": day.isoformat() if day else ""}
    if sid not in rooms:
        return False, "ask_off", keep
    tz = _spaces_tz(biz)
    today = _now().astimezone(tz).date()
    if not day or day < today:
        return False, "ask_room_time", keep
    if day > today + timedelta(days=DAYS_AHEAD):
        return False, "ask_room_far", keep
    a, b = _clock(form.get("start")), _clock(form.get("end"))
    if not a or not b:
        return False, "ask_room_time", keep
    start, end = _at(day, a, tz), _at(day, b, tz)
    if end <= start or start <= _now():
        return False, "ask_room_time", keep
    reason = _plain(form.get("reason"), REASON_MAX)
    if len(reason) < 3:
        return False, "ask_room_reason", keep
    s_utc, e_utc = church_spaces._iso(start), church_spaces._iso(end)
    try:
        if church_spaces.clashes(str(biz["id"]), sid, [(start, end)]):
            return False, "ask_room_taken", keep
        # The same ask sent twice (a double tap) lands once.
        again = sb_clients.sb_get_as_service(
            f"/church_space_bookings?business_id=eq.{_q(biz['id'])}&space_id=eq.{_q(sid)}"
            f"&contact_id=eq.{_q(me['id'])}&status=eq.requested&start_at=eq.{_q(s_utc)}&end_at=eq.{_q(e_utc)}"
            "&select=id&limit=1")
        if not isinstance(again, list):
            return False, "error", keep
        if again:
            return True, "ask_room", keep
        title = reason if len(reason) <= church_spaces.TITLE_MAX else reason[:church_spaces.TITLE_MAX - 1] + "…"
        church_spaces.book({"biz": {"id": str(biz["id"]), "owner_id": None}, "role": "member", "uid": None}, {
            "space_id": sid, "title": title, "start_at": s_utc, "end_at": e_utc,
            "contact_id": str(me["id"]), "kind": "use", "status": "requested",
            "notes": f"Asked from the member app: {reason}"})
    except HTTPException as e:
        if e.status_code == 409:
            return False, "ask_room_taken", keep
        if e.status_code == 400:
            return False, "ask_room_time", keep
        return False, "error", keep
    who = _first(me.get("name"))
    room = _plain(rooms[sid].get("name"), 80) or "A room"
    notify(str(biz["id"]), "office", "A room request",
           f"{who} asked for {room}, {church_spaces.when_text(start, end, tz)}. Say yes or no in Rooms & spaces.",
           NAV["room"], f"ask-room-{me['id']}-{s_utc}")
    return True, "ask_room", keep


def _first(name: Any) -> str:
    s = _plain(name, 80)
    return (s.split(" ")[0] if s else "") or "A member"


# ─── Care: help, a visit, a life event ────────────────────────────────


def ask_care(biz: Dict[str, Any], me: Dict[str, Any], kind: str, form: Dict[str, Any], *,
             youth: bool) -> Tuple[bool, str]:
    """A private request to Prayer & care, in the shape the office's inbox
    already reads. Kept with the pastors (never the prayer team); a youth's
    help goes the youth way."""
    import church_prayer
    picks = PICKS[kind]
    pick = str(form.get("pick") or "")
    if pick not in picks:
        return False, "ask_pick"
    text = _words(form.get("text"), TEXT_MAX)
    if kind == KIND_HELP and len(text) < 2:
        return False, "ask_empty"
    when = None
    if kind == KIND_LIFE and str(form.get("date") or "").strip():
        when = _day(form.get("date"))
        if not when or when < church_today(biz) - timedelta(days=1):
            return False, "ask_date"
    full = _contact(str(biz["id"]), str(me["id"])) or me
    sub: Dict[str, Any] = {
        "name": _plain(full.get("name"), 120), "email": full.get("email") or "", "phone": full.get("phone") or "",
        "request": text or picks[pick], "kind": kind, PICK_FIELD[kind]: picks[pick],
        "confidential": "yes", "source": SOURCE_YOUTH if youth else SOURCE,
    }
    if when:
        sub["date"] = when.isoformat()
    if youth:
        sub["youth"] = "yes"
    wants_call = str(form.get("wants_call") or "") == "yes"
    if wants_call:
        sub["wants_call"] = "yes"
    # The same ask sent twice (a double tap, a back-and-resend) lands once.
    have = sb_clients.sb_get_as_service(
        f"/ministry_care_requests?business_id=eq.{_q(biz['id'])}&contact_id=eq.{_q(me['id'])}&status=eq.new"
        f"&submission->>kind=eq.{_q(kind)}&select=submission&order=created_at.desc&limit=20")
    if not isinstance(have, list):
        return False, "error"
    if any(isinstance(r.get("submission"), dict) and r["submission"].get("request") == sub["request"]
           and r["submission"].get(PICK_FIELD[kind]) == sub[PICK_FIELD[kind]] for r in have):
        return True, _done_code(kind, sub)
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": str(biz["id"]), "form_id": None, "contact_id": str(me["id"]), "status": "new",
        "submission": sub, **church_prayer.consent_columns(sub, share=False, wants_call=wants_call),
    })
    if not (isinstance(rows, list) and rows):
        return False, "error"
    said = {KIND_HELP: "Someone asked for help", KIND_VISIT: "Someone asked to talk with a pastor",
            KIND_LIFE: "Someone asked about a life event"}[kind]
    notify(str(biz["id"]), "people_care", "A new request in Prayer & care",
           f"{said} from the member app. It's private: open Prayer & care to read it.",
           NAV["care"], f"ask-care-{rows[0].get('id') or uuid.uuid4()}", priority="high")
    return True, _done_code(kind, sub)


def _done_code(kind: str, sub: Dict[str, Any]) -> str:
    try:
        from msg_screen import CRISIS_RE
        if CRISIS_RE.search(str(sub.get("request") or "")):
            return "care"
    except Exception:
        pass
    return {KIND_HELP: "ask_help", KIND_VISIT: "ask_visit", KIND_LIFE: "ask_life"}[kind]


def _contact(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}&select=id,name,email,phone&limit=1")
    return rows[0] if isinstance(rows, list) and rows else None


# ─── Pledges ──────────────────────────────────────────────────────────


def _cents(v: Any) -> Optional[int]:
    s = re.sub(r"[\s,$]", "", str(v or ""))
    if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", s):
        return None
    try:
        n = int((Decimal(s) * 100).to_integral_value())
    except InvalidOperation:
        return None
    return n if n >= 100 else None


def my_pledges(biz: Dict[str, Any], me_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """campaign id → this member's pledge, or None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/church_pledges?business_id=eq.{_q(biz['id'])}&contact_id=eq.{_q(me_id)}"
        "&select=id,campaign_id,contact_id,total_cents,per_period_cents,period,periods,note,recorded_at&limit=100")
    if not isinstance(rows, list):
        return None
    return {str(r["campaign_id"]): r for r in rows if r.get("campaign_id")}


def progress_for(biz: Dict[str, Any], me_id: str, campaigns: List[Dict[str, Any]],
                 mine: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Dict[str, Any]]]:
    """campaign id → {given_cents, left_cents, percent} for this member's
    own pledges: their own paid gifts to the campaign's fund in its dates
    (church_pledges.progress). None when the gifts couldn't be read."""
    import church_pledges
    from giving_records import read_gifts
    pledged = [c for c in campaigns if str(c["id"]) in mine]
    if not pledged:
        return {}
    tz = church_pledges._tz(biz)
    today = church_today(biz)
    try:
        gifts: List[Dict[str, Any]] = []
        for a, b in church_pledges.windows(pledged, today):
            gifts.extend(read_gifts(str(biz["id"]), f"{a.isoformat()}T00:00:00Z", f"{b.isoformat()}T00:00:00Z",
                                    contact_id=me_id))
    except HTTPException:
        return None
    out = {}
    for c in pledged:
        if date.fromisoformat(str(c["starts_on"])[:10]) > today:
            out[str(c["id"])] = {"given_cents": 0, "left_cents": int(mine[str(c["id"])].get("total_cents") or 0),
                                 "percent": 0}
            continue
        row = church_pledges.progress(c, [mine[str(c["id"])]], gifts, tz)["rows"][0]
        out[str(c["id"])] = {k: row[k] for k in ("given_cents", "left_cents", "percent")}
    return out


def ask_pledge(biz: Dict[str, Any], me: Dict[str, Any], form: Dict[str, Any]) -> Tuple[bool, str]:
    """A member's own pledge to a campaign that hasn't ended, or a change to
    the amount of the one they have (one per giver per campaign)."""
    import church_pledges
    cid = str(form.get("campaign") or "")
    campaign = next((c for c in open_campaigns(biz) if str(c["id"]) == cid), None)
    if not campaign:
        return False, "ask_campaign"
    how = str(form.get("how") or "total")
    cents = _cents(form.get("amount"))
    if cents is None:
        return False, "ask_amount"
    if how == "total":
        body: Dict[str, Any] = {"total_cents": cents}
    elif how in church_pledges.PERIODS:
        t = str(form.get("times") or "").strip()
        if not t.isdigit() or not 1 <= int(t) <= church_pledges.PERIODS_MAX:
            return False, "ask_times"
        body = {"per_period_cents": cents, "period": how, "periods": int(t)}
    else:
        return False, "ask_amount"
    try:
        amount = church_pledges._pledge_amount(body)
    except HTTPException:
        return False, "ask_amount"
    note = _plain(form.get("note"), NOTE_MAX)
    bid, me_id = str(biz["id"]), str(me["id"])
    have = sb_clients.sb_get_as_service(
        f"/church_pledges?business_id=eq.{_q(bid)}&campaign_id=eq.{_q(cid)}&contact_id=eq.{_q(me_id)}&select=id&limit=1")
    if not isinstance(have, list):
        return False, "error"
    name = _plain(campaign.get("name"), 80) or "a campaign"
    if have:
        saved = sb_clients.sb_patch_as_service(
            f"/church_pledges?id=eq.{_q(have[0]['id'])}&business_id=eq.{_q(bid)}&contact_id=eq.{_q(me_id)}",
            {**amount, "note": note})
        if not (isinstance(saved, list) and saved):
            return False, "error"
        notify(bid, "giving", "A pledge changed",
               f"A pledge to {name} changed in the member app. Open Pledges & campaigns.",
               NAV["pledge"], f"ask-pledge-{have[0]['id']}-{amount['total_cents']}")
        return True, "ask_pledge_changed"
    rid = str(form.get("request_id") or "")
    row = {"business_id": bid, "campaign_id": cid, "contact_id": me_id, **amount, "note": note,
           "recorded_by": me_id}
    if UUID_RE.match(rid):
        again = sb_clients.sb_get_as_service(
            f"/church_pledges?business_id=eq.{_q(bid)}&request_id=eq.{_q(rid)}&select=id&limit=1")
        if isinstance(again, list) and again:
            return True, "ask_pledge"
        row["request_id"] = rid
    saved = sb_clients.sb_post_as_service("/church_pledges", row)
    if not (isinstance(saved, list) and saved):
        # Two taps at once: the table keeps one per giver; the other finds it.
        again = sb_clients.sb_get_as_service(
            f"/church_pledges?business_id=eq.{_q(bid)}&campaign_id=eq.{_q(cid)}&contact_id=eq.{_q(me_id)}"
            "&select=id&limit=1")
        return (True, "ask_pledge") if isinstance(again, list) and again else (False, "error")
    notify(bid, "giving", "A new pledge",
           f"Someone pledged to {name} from the member app. Open Pledges & campaigns.",
           NAV["pledge"], f"ask-pledge-{saved[0].get('id') or rid}")
    return True, "ask_pledge"


# ─── The member's POSTs ───────────────────────────────────────────────

PAGES = ("/my/ask", "/my/ask/room", "/my/ask/help", "/my/ask/visit", "/my/ask/life", "/my/ask/pledge")


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target not in PAGES:
        target = "/my/ask"
    q = {k: v for k, v in q.items() if v}
    return RedirectResponse(f"{target}?{urlencode(q)}" if q else target, status_code=303, headers=_SECURE_HEADERS)


def _allowed(church: Dict[str, Any], me: Dict[str, Any]) -> bool:
    """Asks have their own budget per member (an hour's and a day's), on top
    of the member app's own."""
    import rate_limit
    key = f"{church['business']['id']}|{me['id']}"
    return (rate_limit.allow_strict("member_ask", key) and rate_limit.allow_strict("member_ask_day", key)
            and rate_limit.allow_strict("member_action", key))


async def _start(request: Request, ask: str, back: str):
    """Who's asking, and whether they may ask this. (church, me, form,
    youth, redirect): a redirect means stop there."""
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    form = dict(await request.form())
    if unavailable:
        return church, None, form, False, _go(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return church, None, form, False, mpc._back("/my")
    biz = church["business"]
    if ask not in turned_on(biz) or not await asyncio.to_thread(church_open, biz):
        return church, me, form, False, _go("/my/ask", err="ask_off")
    young = await asyncio.to_thread(minor, str(biz["id"]), me)
    if young is None:
        return church, me, form, False, _go(back, err="error")
    if ask not in await asyncio.to_thread(offered, biz, minor=bool(young), fresh=True):
        return church, me, form, bool(young), _go("/my/ask", err="ask_youth" if young else "ask_off")
    return church, me, form, bool(young), None


@router.post("/my/ask/room", include_in_schema=False)
async def post_room(request: Request):
    church, me, form, _, stop = await _start(request, "room", "/my/ask/room")
    if stop:
        return stop
    if not _allowed(church, me):
        return _go("/my/ask/room", err="slow", space=str(form.get("space") or "")[:36])
    ok, code, keep = await asyncio.to_thread(ask_room, church["business"], me, form)
    if ok:
        return _go("/my/ask", done=code)
    return _go("/my/ask/room", err=code, **keep)


@router.post("/my/ask/care", include_in_schema=False)
async def post_care(request: Request):
    form0 = await request.form()
    kind = str(form0.get("kind") or "")
    if kind not in CARE:
        return _go("/my/ask", err="ask_off")
    page = f"/my/ask/{PAGE_OF[kind]}"
    church, me, form, young, stop = await _start(request, kind, page)
    if stop:
        return stop
    if not _allowed(church, me):
        return _go(page, err="slow")
    ok, code = await asyncio.to_thread(ask_care, church["business"], me, kind, form, youth=young)
    return _go("/my/ask", done=code) if ok else _go(page, err=code)


@router.post("/my/ask/pledge", include_in_schema=False)
async def post_pledge(request: Request):
    church, me, form, _, stop = await _start(request, "pledge", "/my/ask/pledge")
    if stop:
        return stop
    if not _allowed(church, me):
        return _go("/my/ask/pledge", err="slow")
    ok, code = await asyncio.to_thread(ask_pledge, church["business"], me, form)
    return _go("/my/ask/pledge", done=code) if ok else _go("/my/ask/pledge", err=code)


# ─── The office ───────────────────────────────────────────────────────


def office_view(biz: Dict[str, Any], *, owner: bool) -> Dict[str, Any]:
    """The church's choices, what each needs before it shows, and where each
    lands."""
    on = turned_on(biz)
    out = []
    for k in ASKS:
        why = ""
        if k == "room":
            if not spaces_open(biz):
                why = "Rooms & spaces isn't open at your church yet."
            elif not _ready(biz, "room", fresh=True):
                why = "Add a room in Rooms & spaces first."
        elif k == "pledge":
            if not pledges_open(biz):
                why = "Pledges & campaigns isn't open at your church yet."
            elif not _ready(biz, "pledge", fresh=True):
                why = "Start a campaign in Pledges & campaigns first."
        out.append({"key": k, **CHOICES[k], "on": k in on, "ready": not why, "why": why,
                    "youth": k in YOUTH_ASKS})
    return {"ok": True, "on": on, "can_switch": owner, "choices": out}


def _office(business_id: str, user: AuthedUser) -> Tuple[Dict[str, Any], bool]:
    """The church and whether the caller owns it: the owner, or an admin seat
    (member_directory's rule for the Member page's office sections)."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    import member_directory
    import member_portal as mp
    import church_follow_up as cfu
    biz, owner = member_directory._office(business_id, user)
    if not mp.portal_eligible(biz) or not cfu.is_church(biz):
        raise HTTPException(404, "Not Found")
    return biz, owner


@router.get("/member-portal/{business_id}/asks")
def get_asks(business_id: str, user: AuthedUser = Depends(require_user)):
    biz, owner = _office(business_id, user)
    return office_view(biz, owner=owner)


@router.put("/member-portal/{business_id}/asks")
def save_asks(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The owner only. {on: [ask keys]}: every ask not named is off."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    on = clean_choice((body or {}).get("on"))
    if on is None:
        raise HTTPException(400, "on must be a list of asks")
    import member_portal as mp
    import church_follow_up as cfu
    biz = mp._require_owner(business_id, user)
    if not mp.portal_eligible(biz) or not cfu.is_church(biz):
        raise HTTPException(400, "Asks are for churches.")
    fresh = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=settings&limit=1")
    if not isinstance(fresh, list) or not fresh:
        raise HTTPException(503, "That change didn't save. Please try again.")
    settings = dict(fresh[0].get("settings") or {})
    cfg = dict(mp.portal_settings(settings))
    cfg[KEY] = {"on": on, "at": _now().isoformat(), "by": str(user.id)}
    settings["member_portal"] = cfg
    saved = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(business_id)}", {"settings": settings})
    if not saved:
        raise HTTPException(503, "That change didn't save. Please try again.")
    return office_view({**biz, "settings": settings}, owner=True)


# ─── Pages ────────────────────────────────────────────────────────────

# Each ask wears one of the app's family colours (member_app_ui: gold, teal,
# violet, coral; the church's own on prayer, as on Home).
HUE = {"room": "teal", "help": "coral", "visit": "violet", "life_event": "gold", "pledge": "gold",
       "event": "coral", "prayer": "brand"}
ICON = {"room": "home", "help": "heart", "visit": "chat", "life_event": "star", "pledge": "give",
        "event": "calendar", "prayer": "pray"}

CSS = """
.ask-list{list-style:none;margin:18px 0 0;padding:0;display:flex;flex-direction:column;gap:10px;}
.ask-list li{display:flex;}
.ask-list li>.ask-card{flex:1;min-width:0;}
.ask-card{display:flex;align-items:center;gap:14px;min-height:76px;padding:14px 16px;border-radius:var(--r-md);background:var(--s1);
  color:var(--fg);text-decoration:none;}
.ask-dot{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--h-deep);color:var(--h-ink);}
.ask-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.ask-t strong{font-size:16.5px;font-weight:640;letter-spacing:-.015em;}
.ask-t span{font-size:13.5px;color:var(--fg2);line-height:1.35;}
.ask-card>.mb-ic:last-child{color:var(--fg3);flex:none;}
.ask-card:focus-visible,.ask-pick label:has(input:focus-visible),.ask-day a:focus-visible{outline:2px solid var(--focus);outline-offset:3px;}
.ask-note{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;color:var(--fg2);margin:22px 2px 0;line-height:1.45;}
.ask-note .mb-ic{flex:none;margin-top:2px;}
.ask-head{display:flex;align-items:center;gap:12px;margin:4px 0 2px;}
.ask-head .ask-dot{width:40px;height:40px;}
.ask-form{display:flex;flex-direction:column;gap:12px;margin-top:18px;}
.ask-form>label{margin-top:4px;}
.ask-pick{border:0;margin:0;padding:0;min-width:0;}
.ask-pick legend{font-size:14px;font-weight:600;color:var(--fg2);padding:0;margin:0 0 10px;}
.ask-pick-g{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.ask-pick label{display:flex;align-items:center;gap:10px;min-height:52px;padding:10px 14px;border-radius:14px;background:var(--s1);
  font-size:15px;font-weight:560;color:var(--fg);cursor:pointer;line-height:1.25;}
.ask-pick input{width:20px;height:20px;margin:0;flex:none;accent-color:var(--acc-fill);}
.ask-pick label:has(input:checked){box-shadow:inset 0 0 0 2px var(--acc);}
.ask-form .mp-check{align-items:center;min-height:48px;padding:0 2px;cursor:pointer;}
.ask-form .mp-check input{margin:0;}
.ask-two{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.ask-two>div{display:flex;flex-direction:column;gap:8px;min-width:0;}
.ask-sec{font-size:13px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--fg3);margin:26px 2px 10px;}
.ask-busy{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;}
.ask-busy li{display:flex;align-items:center;gap:10px;min-height:48px;padding:10px 14px;border-radius:12px;background:var(--s1);font-size:15px;
  font-variant-numeric:tabular-nums;}
.ask-busy li .mb-ic{color:var(--fg3);flex:none;}
.ask-busy li span{color:var(--fg2);margin-left:auto;font-size:13px;}
.ask-free{display:flex;align-items:center;gap:10px;min-height:48px;padding:10px 14px;border-radius:12px;background:var(--teal-deep);
  color:var(--fg);font-size:15px;}
.ask-free .mb-ic{color:var(--teal-ink);flex:none;}
.ask-mine{display:flex;flex-direction:column;gap:8px;}
.ask-mine .mp-card{margin:0;display:flex;flex-direction:column;gap:4px;}
.ask-mine strong{font-size:15.5px;}
.ask-chip{display:inline-flex;align-items:center;height:26px;padding:0 10px;border-radius:999px;font-size:12.5px;font-weight:650;
  align-self:flex-start;background:var(--s3);color:var(--fg2);margin-top:4px;}
.ask-chip.is-booked{background:var(--teal-deep);color:var(--teal-ink);}
.ask-chip.is-declined{background:var(--coral-deep);color:var(--coral-ink);}
.ask-camp{margin-top:14px;}
.ask-camp h2{font-size:20px;font-weight:700;letter-spacing:-.025em;margin:6px 0 4px;}
.ask-camp .mb-kick{color:var(--gold-ink);}
.ask-bar{height:10px;border-radius:999px;background:var(--s3);overflow:hidden;margin:14px 0 8px;}
.ask-bar i{display:block;height:100%;border-radius:999px;background:var(--gold);}
.ask-sum{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:14.5px;color:var(--fg2);font-variant-numeric:tabular-nums;}
.ask-sum b{color:var(--fg);font-weight:650;}
.ask-camp details{margin-top:12px;}
.ask-camp summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-size:15px;font-weight:600;color:var(--acc);list-style:none;}
.ask-camp summary::-webkit-details-marker{display:none;}
.ask-amt{position:relative;}
.ask-amt>b{position:absolute;left:16px;top:50%;transform:translateY(-50%);color:var(--fg2);font-weight:600;pointer-events:none;}
.ask-amt .mp-input{padding-left:32px;font-variant-numeric:tabular-nums;}
.ask-done{display:flex;gap:14px;align-items:flex-start;padding:16px;border-radius:var(--r-md);background:var(--teal-deep);margin:16px 0 4px;}
.ask-done .ask-dot{background:var(--teal);color:var(--on-teal);width:40px;height:40px;}
.ask-done strong{display:block;font-size:16px;margin-bottom:2px;}
.ask-done p{margin:0;color:var(--fg2);font-size:14.5px;line-height:1.45;}
.ask-cta{margin-top:6px;}
@media (min-width:700px){.ask-list{display:grid;grid-template-columns:1fr 1fr;}}
@media (max-width:520px){.ask-see{grid-template-columns:1fr;}}
@media (max-width:360px){.ask-pick-g,.ask-two{grid-template-columns:1fr;}}
@media (prefers-reduced-motion:no-preference){.ask-card{transition:transform .15s ease;}.ask-card:active{transform:scale(.98);}}
"""

# What happens next, said plainly, in the church's own name.
DONE = {
    "ask_room": ("Asked", "The church office will say yes, or suggest another time. You'll see it under Book a room."),
    "ask_help": ("Sent privately", "Someone from {church} will reach out to you. Only the pastors and the people who "
                                   "care for members see it."),
    "ask_visit": ("Sent", "A pastor from {church} will reach out to you."),
    "ask_life": ("Sent", "The {church} office will reach out to plan it with you."),
    "ask_pledge": ("Thank you", "Your pledge is recorded. Gifts to the campaign's fund count toward it."),
    "ask_pledge_changed": ("Changed", "Your pledge is changed. What you've already given still counts."),
}
ERRORS = {
    "ask_off": "That isn't something you can ask for here right now.",
    "ask_youth": "That's for adults. You can ask for help or prayer here.",
    "ask_room_taken": "That room is taken then. Pick another time; the busy times are listed.",
    "ask_room_time": "Pick a start and an end on that day, later than now.",
    "ask_room_far": "Pick a day within the next year.",
    "ask_room_reason": "Say what it's for, in a few words.",
    "ask_pick": "Choose one first.",
    "ask_empty": "Tell us a little about what you need.",
    "ask_date": "That date doesn't look right.",
    "ask_amount": "Enter an amount of at least $1, like 25 or 1200.",
    "ask_times": "Enter how many times, from 1 to 520.",
    "ask_campaign": "That campaign isn't taking pledges any more.",
}


def _flash(request: Request, church: str) -> str:
    from member_portal import _e
    import member_app_ui as ui
    import member_portal_church as mpc
    done = DONE.get(request.query_params.get("done") or "")
    if done:
        return (f'<div class="ask-done" role="status"><span class="ask-dot">{ui.icon("check", 20)}</span>'
                f'<div><strong>{_e(done[0])}.</strong><p>{_e(done[1].format(church=church))}</p></div></div>')
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    return mpc._flash(request)


def _card(href: str, ask: str, title: str, sub: str) -> str:
    import member_app_ui as ui
    from member_portal import _e
    return (f'<li><a class="ask-card h-{HUE[ask]}" href="{_e(href)}"><span class="ask-dot">{ui.icon(ICON[ask], 22)}</span>'
            f'<span class="ask-t"><strong>{_e(title)}</strong><span>{_e(sub)}</span></span>{ui.icon("chevron", 18)}</a></li>')


def _top(ask: str, title: str, sub: str) -> str:
    import member_app_ui as ui
    from member_portal import _e
    return (f'<div class="ask-head h-{HUE[ask]}"><span class="ask-dot">{ui.icon(ICON[ask], 20)}</span>'
            f'<div class="mb-lt" style="margin:0"><h1>{_e(title)}</h1></div></div><p class="mb-sub">{_e(sub)}</p>')


def _page(biz, site, me, title: str, body: str, back: Tuple[str, str] = ("/my/ask", "Ask"), script: str = "") -> str:
    from member_portal import _shell
    return _shell(biz, site, title, f"<style>{CSS}</style>{body}", tab="ask", who=me, back=back, script=script)


def render_menu(biz, site, request: Request, me, asks: List[str], youth: bool) -> str:
    from member_portal import _e
    import member_app_ui as ui
    church = (biz.get("name") or "").strip() or "the church"
    cards = []
    words = {
        "room": ("/my/ask/room", "Book a room", "Ask for a room at the church for a day and a time"),
        "help": ("/my/ask/help", "Ask for help", "Food, a bill, a ride or something else. Private."),
        "visit": ("/my/ask/visit", "Talk to a pastor", "A call, or a visit at home or in the hospital"),
        "life_event": ("/my/ask/life", "Plan a life event", "A wedding, a funeral, a baby dedication, a baptism"),
        "pledge": ("/my/ask/pledge", "Make a pledge", "Pledge to a campaign and see what you've given"),
        "event": ("/my/events", "Sign up for an event", "Say you're coming, or sign up to serve"),
    }
    if youth:
        words["help"] = ("/my/ask/help", "Ask for help", "It goes privately to the pastors")
    for k in asks:
        href, t, s = words[k]
        cards.append(_card(href, k, t, s))
    cards.append(_card("/my/prayer?for=youth" if youth else "/my/prayer", "prayer", "Ask for prayer",
                       "Privately, to the pastors"))
    sub = (f"Ask {church} for help or prayer. It goes privately to the pastors." if youth else
           f"Ask {church} for what you need. Each ask goes straight to the people who look after it.")
    note = ("Nothing you send here is posted or shown to other members." if youth else
            "Help, visits and life events go privately to the pastors and the people who care for members. "
            "Nothing you send here is posted or shown to other members.")
    body = (f'<div class="mb-lt"><h1>Ask the <em>church</em></h1></div><p class="mb-sub">{_e(sub)}</p>'
            f'{_flash(request, church)}<ul class="ask-list">{"".join(cards)}</ul>'
            f'<p class="ask-note">{ui.icon("lock", 16)}<span>{_e(note)}</span></p>')
    return _page(biz, site, me, "Ask the church", body, back=("/my", "Home"))


def render_care(biz, site, request: Request, me, kind: str, youth: bool) -> str:
    from member_portal import _e
    church = (biz.get("name") or "").strip() or "the church"
    picks = PICKS[kind]
    if kind == KIND_HELP:
        top = _top("help", "Ask for help",
                   f"Tell {church} what you need. It goes privately to the pastors"
                   + ("." if youth else " and the people who care for members. It isn't posted or shared."))
        legend, label, ph, need = "What do you need help with?", "Tell us a little more", \
            "What's going on, and how we can help", True
    elif kind == KIND_VISIT:
        top = _top("visit", "Talk to a pastor", f"Ask a pastor from {church} to call you or come and see you.")
        legend, label, ph, need = "What would help?", "Anything we should know? (optional)", \
            "Where you are, and when is a good time", False
    else:
        top = _top("life_event", "Plan a life event",
                   f"Tell the {church} office what you're planning. They'll reach out to plan it with you.")
        legend, label, ph, need = "What are you planning?", "Anything we should know? (optional)", \
            "Names, the place, anything you'd like", False
    radios = "".join(f'<label><input type="radio" name="pick" value="{_e(k)}" required> {_e(v)}</label>'
                     for k, v in picks.items())
    date_row = ""
    if kind == KIND_LIFE:
        today = church_today(biz)
        date_row = (f'<label for="ask-date">When, if you know (optional)</label>'
                    f'<input class="mp-input" id="ask-date" type="date" name="date" min="{today.isoformat()}">')
    call = ('<label class="mp-check"><input type="checkbox" name="wants_call" value="yes"> '
            "I'd like someone to call me</label>")
    body = (f'{top}{_flash(request, church)}'
            f'<form class="ask-form" method="post" action="/my/ask/care"><input type="hidden" name="kind" value="{kind}">'
            f'<fieldset class="ask-pick"><legend>{_e(legend)}</legend><div class="ask-pick-g">{radios}</div></fieldset>'
            f'{date_row}<label for="ask-text">{_e(label)}</label>'
            f'<textarea class="mp-input mp-text" id="ask-text" name="text" rows="5" maxlength="{TEXT_MAX}" '
            f'placeholder="{_e(ph)}"{" required" if need else ""}></textarea>{call}'
            f'<button class="mp-go ask-cta" type="submit">Send</button></form>')
    title = {KIND_HELP: "Ask for help", KIND_VISIT: "Talk to a pastor", KIND_LIFE: "Plan a life event"}[kind]
    return _page(biz, site, me, title, body)


def _hm(d: datetime) -> str:
    import church_spaces
    return church_spaces._clock(d)


def render_room(biz, site, request: Request, me, rooms: List[Dict[str, Any]], space: Dict[str, Any], day: date,
                busy_times: Optional[List[Tuple[datetime, datetime]]], mine: Optional[List[Dict[str, Any]]],
                today: date) -> str:
    from member_portal import _e
    import member_app_ui as ui
    church = (biz.get("name") or "").strip() or "the church"
    names = {str(r["id"]): _plain(r.get("name"), 80) for r in rooms}
    opts = "".join(f'<option value="{_e(r["id"])}"{" selected" if str(r["id"]) == str(space["id"]) else ""}>'
                   f'{_e(names[str(r["id"])])}{f" · holds {int(r["capacity"])}" if r.get("capacity") else ""}</option>'
                   for r in rooms)
    pick = (f'<form class="ask-form" method="get" action="/my/ask/room" id="ask-see">'
            f'<div class="ask-two ask-see"><div><label for="ask-space">Room</label>'
            f'<select class="mp-input" id="ask-space" name="space">{opts}</select></div>'
            f'<div><label for="ask-day">Day</label><input class="mp-input" id="ask-day" type="date" name="day" '
            f'value="{day.isoformat()}" min="{today.isoformat()}" max="{(today + timedelta(days=DAYS_AHEAD)).isoformat()}" '
            f'required></div></div><noscript><button class="mp-go mp-go-2" type="submit">See that day</button></noscript></form>')
    when = f"{day.strftime('%A, %B')} {day.day}"
    if busy_times is None:
        day_html = '<p class="mp-err" role="alert">That day\'s times couldn\'t load just now. Please try again in a moment.</p>'
    elif not busy_times:
        day_html = f'<p class="ask-free">{ui.icon("check", 18)}<span>{_e(names[str(space["id"])])} is free all day.</span></p>'
    else:
        day_html = ('<ul class="ask-busy" aria-label="Busy times">'
                    + "".join(f'<li>{ui.icon("clock", 17)}{_e(_hm(s))} – {_e(_hm(e))}<span>Busy</span></li>'
                              for s, e in busy_times) + '</ul>')
    notes = _plain(space.get("notes"), 300)
    ask = (f'<form class="ask-form" method="post" action="/my/ask/room">'
           f'<input type="hidden" name="space" value="{_e(space["id"])}"><input type="hidden" name="day" value="{day.isoformat()}">'
           f'<div class="ask-two"><div><label for="ask-start">From</label>'
           f'<input class="mp-input" id="ask-start" type="time" name="start" step="900" required></div>'
           f'<div><label for="ask-end">To</label><input class="mp-input" id="ask-end" type="time" name="end" step="900" '
           f'required></div></div>'
           f'<label for="ask-reason">What it\'s for</label>'
           f'<input class="mp-input" id="ask-reason" name="reason" maxlength="{REASON_MAX}" required '
           f'placeholder="For example: a baby shower for the Rivers family">'
           f'<button class="mp-go ask-cta" type="submit">Ask for {_e(names[str(space["id"])])}</button></form>')
    mine_html = ""
    if mine:
        tz = _spaces_tz(biz)
        import church_spaces
        rows = []
        for b in mine:
            s, e = church_spaces._at(b.get("start_at")), church_spaces._at(b.get("end_at"))
            if not s or not e:
                continue
            st = str(b.get("status") or "")
            chip = {"booked": ("is-booked", "Booked"), "declined": ("is-declined", "Not this time"),
                    "requested": ("", "Waiting for the office")}.get(st, ("", st))
            rows.append(f'<div class="mp-card"><strong>{_e(names.get(str(b.get("space_id")), "A room"))}</strong>'
                        f'<span class="mp-muted">{_e(church_spaces.when_text(s, e, tz))} · {_e(b.get("title") or "")}</span>'
                        f'<span class="ask-chip {chip[0]}">{_e(chip[1])}</span></div>')
        if rows:
            mine_html = f'<h2 class="ask-sec">Your asks</h2><div class="ask-mine">{"".join(rows)}</div>'
    script = ("<script>(function(){var f=document.getElementById('ask-see');if(!f)return;"
              "[].forEach.call(f.querySelectorAll('select,input'),function(x){x.addEventListener('change',function(){"
              "if(x.value)f.submit();});});})();</script>")
    about = f'<p class="ask-note">{ui.icon("doc", 16)}<span>{_e(notes)}</span></p>' if notes else ""
    lead = f"Ask {church} for a room. The office says yes, or suggests another time."
    body = (f'{_top("room", "Book a room", lead)}{_flash(request, church)}{pick}'
            f'<h2 class="ask-sec">{_e(when)}</h2>{day_html}{about}'
            f'<h2 class="ask-sec">Ask for a time</h2>{ask}{mine_html}'
            f'<p class="ask-note">{ui.icon("lock", 16)}<span>You see when a room is busy, never who has it or why.</span></p>')
    return _page(biz, site, me, "Book a room", body, script=script)


def _money(cents: int) -> str:
    d = cents / 100
    return f"${d:,.0f}" if cents % 100 == 0 else f"${d:,.2f}"


PERIOD_WORDS = {"weekly": ("a week", "weeks"), "biweekly": ("every two weeks", "times"), "monthly": ("a month", "months")}


def _pledge_words(p: Dict[str, Any]) -> str:
    total = int(p.get("total_cents") or 0)
    if p.get("period") in PERIOD_WORDS and p.get("per_period_cents") and p.get("periods"):
        each, many = PERIOD_WORDS[p["period"]]
        return f"{_money(int(p['per_period_cents']))} {each} for {int(p['periods'])} {many}, {_money(total)} in all"
    return _money(total)


def _span(c: Dict[str, Any]) -> str:
    try:
        a, b = date.fromisoformat(str(c["starts_on"])[:10]), date.fromisoformat(str(c["ends_on"])[:10])
    except (KeyError, ValueError):
        return ""
    return f"{a.strftime('%b')} {a.day}, {a.year} to {b.strftime('%b')} {b.day}, {b.year}"


def _pledge_form(c: Dict[str, Any], p: Optional[Dict[str, Any]]) -> str:
    from member_portal import _e
    cid = _e(c["id"])
    how = (p or {}).get("period") or "total"
    amt = int((p or {}).get("per_period_cents") or (p or {}).get("total_cents") or 0)
    amount = (f"{amt / 100:.2f}".rstrip("0").rstrip(".") if amt else "")
    times = str((p or {}).get("periods") or "")
    hows = (("total", "One amount"), ("weekly", "Each week"), ("biweekly", "Every two weeks"), ("monthly", "Each month"))
    radios = "".join(f'<label><input type="radio" name="how" value="{k}"{" checked" if k == how else ""}> {v}</label>'
                     for k, v in hows)
    return (f'<form class="ask-form" method="post" action="/my/ask/pledge">'
            f'<input type="hidden" name="campaign" value="{cid}"><input type="hidden" name="request_id" value="{uuid.uuid4()}">'
            f'<fieldset class="ask-pick"><legend>How you\'ll give</legend><div class="ask-pick-g">{radios}</div></fieldset>'
            f'<div class="ask-two"><div><label for="ask-amt-{cid}">Amount</label><div class="ask-amt"><b aria-hidden="true">$</b>'
            f'<input class="mp-input" id="ask-amt-{cid}" name="amount" inputmode="decimal" autocomplete="off" '
            f'value="{_e(amount)}" placeholder="0" required></div></div>'
            f'<div><label for="ask-times-{cid}">How many times</label><input class="mp-input" id="ask-times-{cid}" '
            f'name="times" inputmode="numeric" pattern="[0-9]*" value="{_e(times)}" placeholder="For a weekly pledge"></div></div>'
            f'<label for="ask-note-{cid}">A note (optional)</label><input class="mp-input" id="ask-note-{cid}" name="note" '
            f'maxlength="{NOTE_MAX}" value="{_e((p or {}).get("note") or "")}">'
            f'<button class="mp-go ask-cta" type="submit">{"Change my pledge" if p else "Pledge"}</button></form>')


def render_pledge(biz, site, request: Request, me, campaigns: List[Dict[str, Any]],
                  mine: Optional[Dict[str, Dict[str, Any]]], prog: Optional[Dict[str, Dict[str, Any]]],
                  give_url: str) -> Tuple[str, int]:
    from member_portal import _e
    import member_app_ui as ui
    church = (biz.get("name") or "").strip() or "the church"
    top = _top("pledge", "Make a pledge", f"Pledge toward what {church} is raising for. Only you and the people "
                                          "who keep the church's giving see your pledge.")
    if mine is None:
        body = (f'{top}<p class="mp-err" role="alert">Your pledges couldn\'t load just now. Please try again in a '
                f'moment.</p>')
        return _page(biz, site, me, "Make a pledge", body), 503
    cards = []
    for c in campaigns:
        p = mine.get(str(c["id"]))
        goal = int(c.get("goal_cents") or 0)
        fund = _plain(c.get("fund"), 40) or "General"
        head = (f'<span class="mb-kick">{_e(_span(c))}</span><h2>{_e(c.get("name") or "A campaign")}</h2>'
                f'<p class="mp-muted" style="margin:0">Goal {_e(_money(goal))} · gifts to the {_e(fund)} fund count'
                f'{". " + _e(c.get("note")) if c.get("note") else ""}</p>')
        if p:
            pr = (prog or {}).get(str(c["id"])) if prog is not None else None
            total = int(p.get("total_cents") or 0)
            if pr is None:
                done = '<p class="mp-muted" role="status">What you\'ve given couldn\'t load just now.</p>'
            else:
                pct = int(pr.get("percent") or 0)
                done = (f'<div class="ask-bar" role="progressbar" aria-label="Given toward your pledge" aria-valuemin="0" '
                        f'aria-valuemax="100" aria-valuenow="{pct}"><i style="width:{max(pct, 2) if pr["given_cents"] else 0}%"></i></div>'
                        f'<p class="ask-sum"><span>Given <b>{_e(_money(int(pr["given_cents"])))}</b> of '
                        f'{_e(_money(total))}</span><span>{pct}%</span></p>')
            give = (f'<a class="mp-go mp-go-2 ask-cta" href="{_e(give_url)}">{ui.icon("give", 17)}Give to the {_e(fund)} fund</a>'
                    if give_url else "")
            cards.append(f'<article class="mp-card ask-camp" aria-label="{_e(c.get("name") or "")}">{head}'
                         f'<p style="margin:14px 0 0"><span class="mb-kick">Your pledge</span><b>{_e(_pledge_words(p))}</b></p>'
                         f'{done}{give}<details><summary>Change the amount</summary>{_pledge_form(c, p)}</details></article>')
        else:
            cards.append(f'<article class="mp-card ask-camp" aria-label="{_e(c.get("name") or "")}">{head}'
                         f'{_pledge_form(c, None)}</article>')
    if not cards:
        cards.append('<p class="mp-muted">No campaign is taking pledges right now.</p>')
    note = (f'<p class="ask-note">{ui.icon("lock", 16)}<span>A pledge is a promise, not a payment. You give the way you '
            f'always do; your gifts to the fund in the campaign\'s dates count toward it.</span></p>')
    return _page(biz, site, me, "Make a pledge", f'{top}{_flash(request, church)}{"".join(cards)}{note}'), 200


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str):
    """GET /my/ask and its pages (member_portal.serve). (html, status), or a
    redirect. Ask lives in Church: Kids, and an adult who switched into
    Youth, go back to /my; a teen gets only prayer and help."""
    import member_spaces as msp
    from member_portal import _SECURE_HEADERS
    home = RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    ctx = msp.CURRENT.get() or {}
    space = ctx.get("space", "church")
    if space == "kids" or (space == "youth" and not ctx.get("youth")):
        return home
    if not turned_on(biz) or not await asyncio.to_thread(church_open, biz):
        return home
    young = await asyncio.to_thread(minor, str(biz["id"]), me)
    if young is None:
        from member_portal import render_try_again
        return render_try_again(biz, site), 503
    young = bool(young or ctx.get("youth"))
    asks = await asyncio.to_thread(offered, biz, minor=young)
    if not asks:
        return home
    back = RedirectResponse("/my/ask", status_code=303, headers=_SECURE_HEADERS)
    if sub == "/my/ask":
        return render_menu(biz, site, request, me, asks, young), 200
    page = sub[len("/my/ask/"):]
    if page in ("help", "visit", "life"):
        kind = {"help": KIND_HELP, "visit": KIND_VISIT, "life": KIND_LIFE}[page]
        if kind not in asks:
            return back
        return render_care(biz, site, request, me, kind, young), 200
    if page == "room" and "room" in asks:
        rooms = await asyncio.to_thread(open_rooms, biz)
        if not rooms:
            return back
        want = str(request.query_params.get("space") or "")
        space_row = next((r for r in rooms if str(r["id"]) == want), rooms[0])
        tz = await asyncio.to_thread(_spaces_tz, biz)
        today = _now().astimezone(tz).date()
        day = _day(request.query_params.get("day")) or today
        if day < today or day > today + timedelta(days=DAYS_AHEAD):
            day = today
        busy_times, mine = await asyncio.gather(asyncio.to_thread(busy, biz, str(space_row["id"]), day, tz),
                                                asyncio.to_thread(my_rooms, biz, str(me["id"])))
        return render_room(biz, site, request, me, rooms, space_row, day, busy_times, mine, today), 200
    if page == "pledge" and "pledge" in asks:
        campaigns, mine = await asyncio.gather(asyncio.to_thread(open_campaigns, biz),
                                               asyncio.to_thread(my_pledges, biz, str(me["id"])))
        if not campaigns:
            return back
        prog = await asyncio.to_thread(progress_for, biz, str(me["id"]), campaigns, mine) if mine else {}
        from giving_router import giving_is_active
        return render_pledge(biz, site, request, me, campaigns, mine, prog,
                             "/my/give" if giving_is_active(biz) else "")
    return back


# ─── Home and Me ──────────────────────────────────────────────────────


def home_row(asks: List[str]) -> str:
    """Home's way in, beside prayer: '' when there's nothing to ask."""
    if not asks:
        return ""
    import member_app_ui as ui
    said = ", ".join(ENTRY_WORDS[k] for k in asks[:3])
    more = " and more" if len(asks) > 3 else ""
    return (f'<a class="mb-row h-teal" href="/my/ask"><span class="mb-row-ic ask-row-ic">{ui.icon("send", 20)}</span>'
            f'<span class="mb-row-t"><strong>Ask the church</strong><span>{said[0].upper() + said[1:]}{more}</span></span>'
            f'{ui.icon("chevron", 18)}</a><style>.ask-row-ic{{background:var(--h-deep);color:var(--h-ink);}}</style>')


ENTRY_WORDS = {"room": "a room", "help": "help", "visit": "a visit", "life_event": "a life event",
               "pledge": "a pledge", "event": "an event"}


def me_sub(asks: List[str]) -> str:
    """Me's line under Ask the church."""
    said = ", ".join(ENTRY_WORDS[k] for k in asks[:3])
    return said[0].upper() + said[1:] + (", prayer" if len(asks) < 3 else " and more")
