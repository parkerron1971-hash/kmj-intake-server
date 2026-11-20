"""guest_path_weeks.py — the Welcome Path after week one: two roads, the
Saturday heads-up, the pastor's signature, and the rules that keep it kind.

Kevin, 2026-11-20, on the Welcome Path mock (canvas WmRiSK8seJky8pJUK5nztE,
boards Main "Weeks two to six: two roads" and "The rules that keep it kind",
and PathEditor): "capture visitors, place them in a flow where they receive
automated texts from the church ... top tier", then "build"; "the Monday
note is signed by the senior pastor"; "each church picks its own newcomers'
next-step event". Week one (welcome, thank you, Monday note, invite) is New
here's (new_here.py). This is what comes after, on the same path
(contacts.metadata.new_here, guest_path.py's contract; no migration).

WHO IT IS FOR. Only where guest_path.switched_on (GUEST_PATH) AND New here's
own switches (NEW_HERE, settings.new_here.on) say yes; off, everything here
is quiet and week one is exactly what it was. Texts go only to a guest whose
path's texts started (new_here._texting: a yes at their door, or the text
door's word), never after STOP, only inside the church's automatic-text
hours (texting_hours), and only from a church that isn't a sample.

THE TWO ROADS. A guest's first visit is the day their path started (New
here's texted_at), or for a Plan your visit card their first check-in;
church_guests' rule decides the visits (that day, then each later church-day
with an attendance row, or a kids check-in for a family they're an adult
in). Week two's Wednesday (W2) is the first Wednesday at least 8 days after
the first visit, so week one's last text (an invite can land on day 8) is
never beside it. On the church's clock, each moved inside its hours:
  came back   "So good to see you" (`back`): on the day of their first visit
              after the first, BACK_HOURS after that day's first check-in
              (10 AM when no check-in time is known), never past the day's
              last slot (texting_hours' end less 15 minutes) and never within
              half an hour of the check-in. Gone when that day ends.
  not yet     "Thinking of you" (`thinking`): W2, 11 AM, while they haven't
              been back. A day to go.
  both roads  The newcomers' next step (`next_step`): W2 + 7, 11 AM: the
              church's own event from Services & Events (settings.new_here.
              next_step.event_id), its name and when filled in ({event},
              {when}). Skipped while none is picked, when it isn't coming up
              any more, and from EVENT_SOON before it starts.
  not yet     "Our door is always open" (`door_open`): W2 + 14, 11 AM, still
              not back. Then the automatic texts rest.
  connected   church_guests' definition (a group, a class or a team joined on
              or after the first visit): the path ends, no more road texts
              (path.ended).
Each road text goes once a path (path.sent), from the sweep below.

THE RULES (for every automatic text of the path, week one's too; the
welcome itself is never held back by a count):
  HOLD        metadata.new_here.hold (set when a guest's reply waits on a
              person; another piece sets and clears it, this one honors it):
              nothing automatic goes. A week-one text found held is kept
              (path.waiting) and sent once the hold clears; a road text stays
              due. Either one whose moment passed by more than a day (a
              thank-you, past its own day) is skipped, and why is noted
              (path.skipped).
  A WEEK      no more than WEEK_MAX texts in any 7 days: the welcome and the
              Text me box say "up to 4 msgs a week".
  AFTER WEEK ONE   from 7 days after the path started, no more than one
              automatic text in any 7 days (counting texts sent after week
              one). A road text held back by it waits within its window.
  path.log keeps when each automatic text went (two weeks of them).

THE MONDAY NOTE'S SIGNATURE (settings.new_here.signature, on unless the
church turns it off): the church's own words for it (name), else whoever
holds the senior role (member_pastor.find: the senior role's holders, the
first by name): "Pastor James" where the role's title says Pastor, else
their name. No one found: no signature. new_here.run_scheduled adds it.

THE SATURDAY HEADS-UP (settings.new_here.heads_up: greeters, kids): Saturday
from 9 AM (until 1 PM, so a slow tick still makes it), once per church per
Saturday (claimed first in church_shepherd_notices, the church's server-only
sent-once ledger: key "guest-heads-up-<saturday>-sat"). Who may come
tomorrow: guests whose first visit was in the last 14 days and who haven't
been back (and aren't connected), and Plan your visit guests who haven't
come yet (a card from the last 14 days; when it answered with a date, only
for tomorrow), with their kids' first names when the kids desk knows them.
  greeters    whoever holds a role whose job is "welcome" (church_roles:
              Welcome Team lead, Connections, Guest Services ...); none, the
              first-time guests' login (church_duties first_guests: its
              Manager, else the owner)
  kids desk   whoever holds a role whose job is "kids" (Kids ministry lead,
              Nursery ...), only about families with kids; none, nobody (the
              greeters' note names the kids anyway). Logins by area aren't
              read: a role is who the church named for the kids desk.
A holder who is also an office login (the same person, church_over) gets a
push and an email to their sign-in address (care_handoff.tell's way); anyone
else an email. Never a phone number, a prayer or what the card said.

THE SWEEP (sweep_tick, every 15 minutes on the worker beside the follow-up
sweep, leader-gated): the churches with a guest whose path started in the
last WINDOW_DAYS; each one's guests read once (church_guests' reads, a page
at a time); a read that fails decides nothing (that church waits for the
next tick). Every send re-reads the church (switches, words, hours) and the
guest, and is claimed first (path.claim, a compare-and-set on the guest's
row that also holds hold and the path's start as they were read), so two
copies never both send. At most MAX_TEXTS_PER_TICK texts and
MAX_HEADS_UP_PER_TICK heads-ups a tick.

THE ROOM: room_view() is new_here's GET /new-here "path" block: the
signature as it would read, the church's upcoming events for the picker, the
picked one, when each text goes in words, who the heads-up goes to, and the
limits.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("guest_path_weeks")

STEPS = ("back", "thinking", "next_step", "door_open")        # new_here.PATH_TEXTS
STEP_WORDS = {"back": "So good to see you", "thinking": "Thinking of you", "next_step": "Their next step",
              "door_open": "Our door is always open"}
WINDOW_DAYS = 50                    # a path that started longer ago than this is resting
WED = 2
ROAD_HOUR = 11
BACK_HOURS = 3
BACK_DEFAULT = time(10, 0)          # a return day with no check-in time known
BACK_GAP = timedelta(minutes=30)
STALE = timedelta(days=1)           # a text held past its moment by more than this is skipped
NEXT_STEP_WINDOW = timedelta(days=7)
EVENT_SOON = timedelta(hours=3)     # the next step's text never goes this close to the event
EVENT_LOOKAHEAD = 60                # days: the events a church can pick from
WEEK = timedelta(days=7)
WEEK_MAX = 4                        # "up to 4 msgs a week" (the welcome, the Text me box)
AFTER_MAX = 1                       # after week one: one a week
LOG_KEEP = timedelta(days=14)
CLAIM_STALE = timedelta(minutes=15)
MAX_TEXTS_PER_TICK = 30
MAX_HEADS_UP_PER_TICK = 20
HEADS_UP_DAY = 5                    # Saturday
HEADS_UP_FROM, HEADS_UP_UNTIL = 9, 13
HEADS_UP_DAYS = 14
PLANNED_DAYS = 14
NAV = "operate:guests"
LEDGER = "church_shepherd_notices"
TITLE_WORDS = {"pastor", "rev", "reverend", "dr", "bishop", "elder", "apostle", "prophet", "father", "minister",
               "pr", "ps"}

LIMIT_WORDS = {
    "week": "Four texts already went to this guest in the last 7 days (the most they said yes to); not sent.",
    "one_a_week": "After week one, one automatic text a week, and one already went; not sent.",
}
WHY_WORDS = {"held": "a reply was waiting on a person", "week": "four texts had gone that week",
             "one_a_week": "one text a week after week one", "hours": "outside the church's texting hours",
             "stopped": "they said STOP", "unsure": "a send that may have gone"}
CONNECTED_MEANS = ("When a guest joins a group, a class or a team, the path ends: no more automatic texts.")


# ─── small helpers ────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _nh():
    import new_here
    return new_here


def _meta(contact: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    import guest_path
    return guest_path.guest_meta(contact)


# ─── the path's own record (metadata.new_here.path) ───────────────────

def path_of(mine: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """This path's record: {for (its start), sent, skipped, waits, waiting,
    log, claim, ended}. A record from an earlier visit is left behind, all
    but the last two weeks' log (the limits count across visits)."""
    start = str(mine.get("texted_at") or "")
    p = mine.get("path") if isinstance(mine.get("path"), dict) else {}
    if str(p.get("for") or "") == start:
        out = copy.deepcopy(p)
    else:
        out = {"for": start, "log": list(p.get("log") or [])}
        if isinstance(p.get("claim"), dict):
            out["claim"] = dict(p["claim"])      # a send in flight stays claimed
    out["log"] = [t for t in (out.get("log") or []) if (_parse(t) and now - _parse(t) < LOG_KEEP)]
    for key in ("sent", "skipped", "waits", "waiting"):
        if not isinstance(out.get(key), dict):
            out[key] = {}
    return out


def _sent_times(mine: Dict[str, Any]) -> List[datetime]:
    p = mine.get("path") if isinstance(mine.get("path"), dict) else {}
    times = [t for t in (_parse(x) for x in p.get("log") or []) if t]
    start = _parse(mine.get("texted_at"))
    # The text door's welcome is the reply to their word, never a scheduled
    # send: it went when they texted.
    if start and str(mine.get("door") or "text") == "text" and start not in times:
        times.append(start)
    return times


def limit_says(mine: Dict[str, Any], now: datetime) -> str:
    """"" when one more automatic text may go to this guest now, else why
    not: "week" (WEEK_MAX in the last 7 days) or "one_a_week" (after week
    one, one already went in the last 7 days)."""
    times = [t for t in _sent_times(mine) if now - WEEK < t <= now]
    if len(times) >= WEEK_MAX:
        return "week"
    start = _parse(mine.get("texted_at"))
    if start and now >= start + WEEK and sum(1 for t in times if t >= start + WEEK) >= AFTER_MAX:
        return "one_a_week"
    return ""


def _guards(read: Dict[str, Any]) -> str:
    """The keys a write must find as they were read: the hold (another piece
    sets it when a guest replies), the path's start (a new door starts a new
    path) and the claim (one send at a time)."""
    out = ("&metadata->new_here->>hold=eq.true" if read.get("hold") is True
           else "&or=(metadata->new_here->>hold.is.null,metadata->new_here->>hold.eq.false)")
    start = str(read.get("texted_at") or "")
    out += f"&metadata->new_here->>texted_at=eq.{_q(start)}" if start else "&metadata->new_here->>texted_at=is.null"
    claim = (read.get("path") or {}).get("claim") if isinstance(read.get("path"), dict) else None
    at = str((claim or {}).get("at") or "") if isinstance(claim, dict) else ""
    out += f"&metadata->new_here->path->claim->>at=eq.{_q(at)}" if at else "&metadata->new_here->path->>claim=is.null"
    # The guest's write count, shared with guest_replies (the hold's own
    # writes): a reply, an answer and a send landing in the same moment never
    # undo one another's keys (path.claim, path.waiting, the hold).
    v = read.get("hold_v")
    out += f"&metadata->new_here->>hold_v=eq.{_q(v)}" if v not in (None, "") else "&metadata->new_here->>hold_v=is.null"
    return out


def _next_v(read: Dict[str, Any]) -> int:
    try:
        return int(read.get("hold_v") or 0) + 1
    except (TypeError, ValueError):
        return 1


def update(biz_id: str, contact_id: str,
           change: Callable[[Dict[str, Any], Dict[str, Any]], Optional[Dict[str, Any]]],
           *, tries: int = 3) -> Optional[Dict[str, Any]]:
    """Read the guest fresh, change(mine, contact) -> the new metadata.
    new_here (None: nothing to write), and write it only while the hold, the
    path's start and the claim are as read (_guards); someone else got there
    first, read again and try again. The new metadata.new_here; {} when
    change() said nothing to write; None when it couldn't be read or
    written. Never raises."""
    try:
        for _ in range(max(1, tries)):
            rows = _rows(f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(biz_id)}"
                         "&select=id,name,phone,metadata&limit=1")
            if not rows:
                return None
            contact = rows[0]
            read = _meta(contact)
            new = change(copy.deepcopy(read), contact)
            if new is None:
                return {}
            new["hold_v"] = _next_v(read)
            meta = dict(contact.get("metadata") or {}) if isinstance(contact.get("metadata"), dict) else {}
            meta["new_here"] = new
            got = sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(biz_id)}{_guards(read)}", {"metadata": meta})
            if got is None:
                return None
            if got:
                return new
        return None
    except Exception as e:  # noqa: BLE001
        print(f"[guest_path_weeks] {str(biz_id)[:8]}: a guest's path wasn't written ({type(e).__name__})", flush=True)
        return None


def log_sent(biz_id: str, contact_id: str, now: datetime) -> bool:
    """Note that an automatic text went to this guest now (the limits read
    it). Never raises."""
    def change(mine: Dict[str, Any], _c: Dict[str, Any]) -> Dict[str, Any]:
        p = path_of(mine, now)
        p["log"] = (p["log"] + [_iso(now)])[-20:]
        mine["path"] = p
        return mine
    return bool(update(str(biz_id), str(contact_id), change))


def wait_for_hold(business: Dict[str, Any], contact: Dict[str, Any], action: Dict[str, Any],
                  now: datetime) -> Optional[Tuple[bool, str]]:
    """new_here.run_scheduled's answer for a week-one text that comes due
    while the guest's reply waits on a person: kept in path.waiting with its
    moment, and the sweep sends it once the hold clears (or skips it, a day
    on). (ok, what happened); None when the hold was cleared a moment ago
    (the text goes on now)."""
    step = str(action.get("step") or "")
    moment = str(action.get("moment") or "") or _iso(now)
    keep = {k: v for k, v in action.items() if k != "resumed"}
    keep["moment"] = moment

    def change(mine: Dict[str, Any], _c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not mine.get("hold"):
            return None
        p = path_of(mine, now)
        p["waiting"][step] = {"moment": moment, "action": keep}
        mine["path"] = p
        return mine
    got = update(str(business["id"]), str(contact["id"]), change)
    if got is None:
        return False, "A reply is waiting on a person, and this text couldn't be kept waiting."
    if not got:
        return None
    return True, "A reply is waiting on a person: this text waits until someone answers them."


# ─── the Monday note's signature ──────────────────────────────────────

def pastor_signature(name: str, title: str) -> str:
    """"Pastor James" for a senior role whose title says Pastor, else the
    name as it is (a name that already starts with a title stays as it is)."""
    name = _plain(name)
    if not name:
        return ""
    words = name.split(" ")
    if words[0].lower().strip(".") in TITLE_WORDS:
        return name[:40]
    if "pastor" in (title or "").lower():
        return f"Pastor {words[0]}"[:40]
    return name[:40]


def signer(business: Dict[str, Any], settings: Dict[str, Any], *, even_off: bool = False) -> str:
    """Who signs the Monday note: the church's own words for it, else the
    senior role's holder; "" when it's off (unless `even_off`, for the room's
    label) or no one is found. Never raises: a read that fails is no
    signature, and the note still goes."""
    sig = settings.get("signature") if isinstance(settings.get("signature"), dict) else {}
    if not sig.get("on", True) and not even_off:
        return ""
    if _plain(sig.get("name")):
        return _plain(sig.get("name"))[:40]
    try:
        import member_pastor
        p = member_pastor.who(business)
    except Exception:  # noqa: BLE001
        p = None
    if not p:
        return ""
    return pastor_signature(p.get("name") or "", p.get("title") or "")


def sign(words: str, name: str) -> str:
    if not name or words.rstrip().endswith(name):
        return words
    return f"{words.rstrip()} {name}"


# ─── the church's own events (Services & Events) ──────────────────────

def _when_words(when: datetime, timed: bool) -> str:
    """'Sunday, December 13 at 12:30 PM', or 'Sunday, December 13'."""
    day = f"{when.strftime('%A, %B')} {when.day}"
    if not timed:
        return day
    hour = when.hour % 12 or 12
    minutes = f":{when.minute:02d}" if when.minute else ""
    return f"{day} at {hour}{minutes} {'AM' if when.hour < 12 else 'PM'}"


def events_coming(business: Dict[str, Any], now: Optional[datetime] = None) -> Optional[List[Dict[str, Any]]]:
    """The church's own upcoming occasions in Services & Events (an
    event_roster room's entries), soonest first, the next EVENT_LOOKAHEAD
    days: never a weekly service, never a private one, never one that has
    started. Each {entry_id, title, date, time, when, where, starts}. None
    when they couldn't be read."""
    import studio_light_table as slt
    from church_checkin import _entries, _roster
    from events_rsvp_router import resolve_fields
    biz_id = str(business["id"])
    mods = _roster(biz_id)
    if mods is None:
        return None
    if not mods:
        return []
    fields = {str(m["id"]): resolve_fields(m.get("archetype_params")) for m in mods}
    entries = _entries(biz_id, list(fields))
    if entries is None:
        return None
    tz = _nh().tz_of(business)
    local = (now or _now()).astimezone(tz).replace(tzinfo=None)
    out: List[Dict[str, Any]] = []
    for e in entries:
        f = fields.get(str(e.get("module_id")))
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        if not f or str(data.get("type") or "") == "service" or data.get("private") is True:
            continue
        raw = data.get(f["date_field"])
        when = slt._parse(raw)
        title = _plain(data.get(f["title_field"]))[:120]
        if not title or when is None or when > local + timedelta(days=EVENT_LOOKAHEAD):
            continue
        timed = len(str(raw).strip()) > 10
        starts = when if timed else datetime.combine(when.date(), time(0, 0))
        if starts <= local:
            continue
        out.append({"entry_id": str(e["id"]), "title": title, "date": when.date().isoformat(),
                    "time": when.strftime("%H:%M") if timed else None, "when": _when_words(when, timed),
                    "where": _plain(data.get(f["location_field"]))[:120],
                    "starts": _iso(starts.replace(tzinfo=tz))})
    out.sort(key=lambda x: (x["date"], x["time"] or "", x["title"].lower()))
    return out


def event_name(title: str) -> str:
    """The title as it reads after "our": "The Newcomers Lunch" -> "Newcomers Lunch"."""
    return re.sub(r"^(the|our|a|an)\s+", "", _plain(title), flags=re.I) or _plain(title)


def road_words(step: str, settings: Dict[str, Any], guest_name: str,
               event: Optional[Dict[str, Any]] = None) -> str:
    text = settings[step]["text"]
    if step == "next_step":
        if not event:
            return ""
        text = text.replace(_nh().EVENT, event_name(event["title"])).replace(_nh().WHEN, event["when"])
    return _nh().fill(text, name=guest_name)


# ─── when each road text goes ─────────────────────────────────────────

def week_two(first: date) -> date:
    """W2: the first Wednesday at least 8 days after the first visit."""
    d = first + timedelta(days=8)
    return d + timedelta(days=(WED - d.weekday()) % 7)


def _slot(day: date, at: time, tz: Any, hours: Dict[str, Any]) -> datetime:
    """`at` on `day`, moved inside the church's automatic-text hours."""
    t = max(at, time(hours["auto_from"], 0))
    t = min(t, time(hours["auto_until"] - 1, 45))
    return datetime.combine(day, t, tzinfo=tz)


def road(g: Dict[str, Any], settings: Dict[str, Any], hours: Dict[str, Any], tz: Any,
         times: List[datetime], event: Optional[Dict[str, Any]], now: datetime) -> List[Tuple[str, datetime, datetime]]:
    """[(step, moment, until)] for this guest's road texts that are on, in
    the order they come (see the module docstring). `g`: church_guests'
    guest with first_day and visit_days placed; `times`: their check-in
    times; `event`: the picked next step as it reads now, or None."""
    first = g.get("first_day")
    if not first:
        return []                       # a Plan your visit guest who hasn't come yet
    later = sorted(d for d in g.get("visit_days") or [] if d > first)
    out: List[Tuple[str, datetime, datetime]] = []
    if later and settings["back"]["on"]:
        v = later[0]
        that_day = sorted(t for t in times if t.astimezone(tz).date() == v)
        if that_day:
            came = that_day[0].astimezone(tz)
        elif g.get("texted") and g["texted"].astimezone(tz).date() == v:
            came = g["texted"].astimezone(tz)
        else:
            came = datetime.combine(v, BACK_DEFAULT, tzinfo=tz)
        moment = max(came + timedelta(hours=BACK_HOURS), datetime.combine(v, time(hours["auto_from"], 0), tzinfo=tz))
        latest = datetime.combine(v, time(hours["auto_until"] - 1, 45), tzinfo=tz)
        if moment > latest:
            moment = latest if latest >= came + BACK_GAP else None
        if moment:
            out.append(("back", moment, datetime.combine(v, time(hours["auto_until"], 0), tzinfo=tz)))
    w2 = week_two(first)
    road_at = time(ROAD_HOUR, 0)
    if not later and settings["thinking"]["on"]:
        m = _slot(w2, road_at, tz, hours)
        out.append(("thinking", m, m + STALE))
    if settings["next_step"]["on"] and event:
        m = _slot(w2 + timedelta(days=7), road_at, tz, hours)
        starts = _parse(event.get("starts")) or m
        until = min(m + NEXT_STEP_WINDOW, starts - EVENT_SOON)
        if until > m:
            out.append(("next_step", m, until))
    if not later and settings["door_open"]["on"]:
        m = _slot(w2 + timedelta(days=14), road_at, tz, hours)
        out.append(("door_open", m, m + STALE))
    out.sort(key=lambda s: s[1])
    return out


def due(items: List[Tuple[str, datetime, datetime]], p: Dict[str, Any], now: datetime
        ) -> Tuple[Optional[Tuple[str, datetime, datetime]], List[str]]:
    """(the road text due now or None, the steps whose window closed while
    they waited: skipped, with why)."""
    closed: List[str] = []
    for step, moment, until in items:
        if step in p["sent"] or step in p["skipped"]:
            continue
        if now < moment:
            continue
        if now > until:
            if step in p["waits"]:
                closed.append(step)
            continue
        return (step, moment, until), closed
    return None, closed


# ─── reading a church's guests ────────────────────────────────────────

def _planned(meta: Dict[str, Any], fus: List[Dict[str, Any]], start: datetime) -> bool:
    """The path started from a Plan your visit card (a plan, not a visit)."""
    if str(meta.get("door") or "") != "form":
        return False
    for f in fus:
        made = _parse(f.get("created_at"))
        if (str(f.get("path_kind") or "") == "visit" and str(f.get("card_key") or "").startswith("form:")
                and made and abs((made - start).total_seconds()) <= 86400):
            return True
    return False


def _visit_times(biz_id: str, ids: List[str], since: datetime
                 ) -> Tuple[Dict[str, List[datetime]], Dict[str, Set[str]]]:
    """Each guest's check-in times since `since` (church_guests._visits'
    reads and rule: their own attendance, and the kids desk for a family
    they're an adult in), and the families they're an adult in. Raises
    church_guests.Unread."""
    import church_guests as cg
    b = _q(biz_id)
    times: Dict[str, List[datetime]] = {i: [] for i in ids}
    homes: Dict[str, Set[str]] = {i: set() for i in ids}
    if not ids:
        return times, homes
    for r in cg._all_in(f"/attendance?business_id=eq.{b}&{cg._between('checked_in_at', since)}"
                        "&select=id,contact_id,checked_in_at", "contact_id", ids):
        t, cid = _parse(r.get("checked_in_at")), str(r.get("contact_id"))
        if t and cid in times:
            times[cid].append(t)
    adults_of: Dict[str, Set[str]] = {}
    for h in cg._all_in(f"/household_adults?business_id=eq.{b}&select=household_id,contact_id", "contact_id", ids,
                        order="household_id.asc,contact_id.asc"):
        cid = str(h["contact_id"])
        adults_of.setdefault(str(h["household_id"]), set()).add(cid)
        if cid in homes:
            homes[cid].add(str(h["household_id"]))
    if adults_of:
        for r in cg._all_in(f"/child_checkins?business_id=eq.{b}&{cg._between('checked_in_at', since)}"
                            "&select=id,household_id,checked_in_at", "household_id", adults_of):
            t = _parse(r.get("checked_in_at"))
            for cid in adults_of.get(str(r.get("household_id")), ()) if t else ():
                if cid in times:
                    times[cid].append(t)
    return times, homes


def gather(business: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    """The church's guests on the path whose path started in the last
    WINDOW_DAYS, each as church_guests reads them (door, follow-ups, visits
    placed), with their check-in times, families, and who is connected.
    None when a read it can't do without failed (nothing is decided)."""
    import church_guests as cg
    biz_id = str(business["id"])
    tz = _nh().tz_of(business)
    since = now - timedelta(days=WINDOW_DAYS)
    try:
        contacts, fus_by = cg._gather(biz_id, since)
        guests: Dict[str, Dict[str, Any]] = {}
        for cid, c in contacts.items():
            meta = _meta(c)
            start = _parse(meta.get("texted_at"))
            if not start or start < since:
                continue
            g = cg._core(c, fus_by.get(cid, []), tz)
            if not g:
                continue
            # The path's own start (New here's texted_at), never an older
            # follow-up's: the roads count from this visit.
            g["start"], g["start_day"] = start, start.astimezone(tz).date()
            g["planned"] = _planned(meta, fus_by.get(cid, []), start)
            g["contact"] = c
            guests[cid] = g
        ids = sorted(guests)
        times, homes = _visit_times(biz_id, ids, since - timedelta(days=1))
        for cid, g in guests.items():
            cg._place_visits(g, {t.astimezone(tz).date() for t in times.get(cid, [])}, tz)
    except cg.Unread as e:
        print(f"[guest_path_weeks] {biz_id[:8]}: guests unread ({e})", flush=True)
        return None
    connected = cg._soft(lambda: cg._connected(
        biz_id, {cid: g["first_day"] for cid, g in guests.items() if g.get("first_day")}, tz))
    return {"tz": tz, "guests": guests, "times": times, "homes": homes, "connected": connected}


def _phones(biz_id: str, ids: List[str]) -> Optional[Dict[str, str]]:
    """The number each guest's path texts go to: the one their week-one texts
    went to (their door's yes may be for another number than the record's).
    None when it couldn't be read."""
    import church_guests as cg
    try:
        rows = cg._scheduled(biz_id, ids)
    except cg.Unread:
        return None
    out: Dict[str, str] = {}
    for cid, rs in rows.items():
        rs = sorted(rs, key=lambda r: str(r.get("run_at") or ""))
        phone = str(((rs[-1] if rs else {}).get("action") or {}).get("phone") or "")
        if phone:
            out[cid] = phone
    return out


# ─── sending ──────────────────────────────────────────────────────────

def send_text(biz_id: str, contact_id: str, phone: str, body: str) -> Tuple[str, str]:
    """One automatic text from the church's number, kept in its texts.
    ("sent" | "stopped" | "failed", detail). Sync: runs its own loop (the
    sweep is on a worker thread)."""
    async def go() -> Tuple[str, str]:
        import httpx
        import sms_routing
        import sms_service
        async with httpx.AsyncClient(timeout=15) as client:
            if await sms_service.is_opted_out(client, phone, biz_id):
                return "stopped", ""
            try:
                sid = await sms_routing._send_platform_sms(phone, body, business_id=biz_id, client=client)
                await sms_service._store_sms(client, biz_id, contact_id, phone, body, "outbound",
                                             telnyx_id=sid or "", sent_by="system")
            except Exception as e:  # noqa: BLE001
                return "failed", str(e)[:200]
        return "sent", ""
    return asyncio.run(go())


def _church_ok(biz_id: str) -> Optional[Dict[str, Any]]:
    """The church read fresh, while every switch still says yes; else None."""
    nh = _nh()
    import guest_path
    import sample_church
    biz = nh._business(biz_id)
    if not biz or not nh.is_church(biz) or sample_church.skip(biz):
        return None
    if not guest_path.switched_on(biz_id) or not nh.switched_on(biz_id) or not nh.settings_of(biz)["on"]:
        return None
    return biz


def _in_hours(business: Dict[str, Any], now: datetime) -> bool:
    import texting_hours
    return texting_hours.in_auto_window(business, now.astimezone(_nh().tz_of(business)))


def _note_wait(biz_id: str, cid: str, step: str, why: str, now: datetime) -> None:
    def change(mine: Dict[str, Any], _c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = path_of(mine, now)
        if p["waits"].get(step) == why or step in p["sent"] or step in p["skipped"]:
            return None
        p["waits"][step] = why
        mine["path"] = p
        return mine
    update(biz_id, cid, change)


def _skip(biz_id: str, cid: str, steps: List[str], now: datetime, why: Optional[str] = None,
          waiting: bool = False) -> None:
    """Close these steps with why (their wait's reason unless `why`)."""
    def change(mine: Dict[str, Any], _c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = path_of(mine, now)
        for step in steps:
            if waiting:
                if step not in p["waiting"]:
                    continue
                p["waiting"].pop(step, None)
                key = f"week_one:{step}"
            else:
                if step in p["sent"] or step in p["skipped"]:
                    continue
                key = step
            p["skipped"][key] = {"why": why or p["waits"].get(step) or "held", "at": _iso(now)}
            p["waits"].pop(step, None)
        mine["path"] = p
        return mine
    update(biz_id, cid, change)


def _release(biz_id: str, cid: str, stamp: str) -> None:
    def change(mine: Dict[str, Any], _c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = mine.get("path") if isinstance(mine.get("path"), dict) else {}
        if str((p.get("claim") or {}).get("at") or "") != stamp:
            return None
        p.pop("claim", None)
        mine["path"] = p
        return mine
    update(biz_id, cid, change)


def _send_road(biz_id: str, g: Dict[str, Any], step: str, phone: str, now: datetime,
               events: Optional[List[Dict[str, Any]]], stats: Dict[str, int]) -> bool:
    """Claim, re-read, send and record one road text. True when it went."""
    nh = _nh()
    cid = str(g["id"])
    start = str(g["meta"].get("texted_at") or "")
    biz = _church_ok(biz_id)
    if not biz:
        return False
    settings = nh.settings_of(biz)
    if not settings[step]["on"] or not _in_hours(biz, now):
        return False
    event = None
    if step == "next_step":
        event = next((e for e in events or [] if e["entry_id"] == settings["next_step"]["event_id"]), None)
        if not event:
            return False
    stamp = _iso(now) + f"#{random.randint(1000, 9999)}"
    ctx: Dict[str, Any] = {}

    def claim(mine: Dict[str, Any], contact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = path_of(mine, now)
        if (str(mine.get("texted_at") or "") != start or not nh._texting(mine) or mine.get("hold")
                or p.get("claim") or step in p["sent"] or step in p["skipped"] or p.get("ended")
                or limit_says(mine, now)):
            return None
        p["claim"] = {"step": step, "at": stamp}
        mine["path"] = p
        ctx["contact"] = contact
        return mine
    got = update(biz_id, cid, claim)
    if not got:
        return False
    contact = ctx["contact"]
    words = road_words(step, settings, nh.first_name(contact.get("name")), event)
    import sms_service
    body = sms_service.compose_outbound_body(_plain(biz.get("name")), words)
    outcome, detail = send_text(biz_id, cid, phone, body)
    if outcome != "sent":
        _release(biz_id, cid, stamp)
        if outcome == "stopped":
            _skip(biz_id, cid, [step], now, why="stopped")
        else:
            stats["failed"] += 1
            print(f"[guest_path_weeks] {biz_id[:8]}: a {step} text didn't go ({detail[:80]})", flush=True)
        return False

    def record(mine: Dict[str, Any], _c: Dict[str, Any]) -> Dict[str, Any]:
        p = path_of(mine, now)
        p["sent"][step] = _iso(now)
        p["log"] = (p["log"] + [_iso(now)])[-20:]
        p["waits"].pop(step, None)
        if str((p.get("claim") or {}).get("at") or "") == stamp:
            p.pop("claim", None)
        mine["path"] = p
        return mine
    if not update(biz_id, cid, record, tries=5):
        print(f"[guest_path_weeks] {biz_id[:8]}: a {step} text went but wasn't recorded", flush=True)
    stats["sent"] += 1
    return True


def _resume(biz_id: str, g: Dict[str, Any], step: str, wait: Dict[str, Any], now: datetime,
            stats: Dict[str, int]) -> bool:
    """A week-one text kept while the guest's reply waited, sent now that it
    doesn't (new_here.run_scheduled reads everything again)."""
    nh = _nh()
    cid = str(g["id"])
    biz = _church_ok(biz_id)
    if not biz or not _in_hours(biz, now):
        return False
    stamp = _iso(now) + f"#{random.randint(1000, 9999)}"

    def claim(mine: Dict[str, Any], _c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = path_of(mine, now)
        if mine.get("hold") or p.get("claim") or step not in p["waiting"]:
            return None
        p["waiting"].pop(step, None)
        p["claim"] = {"step": f"week_one:{step}", "at": stamp}
        mine["path"] = p
        return mine
    if not update(biz_id, cid, claim):
        return False
    action = dict(wait.get("action") or {})
    action["resumed"] = True
    try:
        ok, what = asyncio.run(nh.run_scheduled(biz, action))
    except Exception as e:  # noqa: BLE001
        ok, what = False, f"raised: {type(e).__name__}"
    _release(biz_id, cid, stamp)
    if ok and what.startswith("Sent"):
        stats["resumed"] += 1
        return True
    if not ok:
        stats["failed"] += 1
    print(f"[guest_path_weeks] {biz_id[:8]}: a held {step} text: {what[:100]}", flush=True)
    return False


def _end(biz_id: str, cid: str, why: str, now: datetime) -> None:
    def change(mine: Dict[str, Any], _c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = path_of(mine, now)
        if p.get("ended"):
            return None
        p["ended"] = {"why": why, "at": _iso(now)}
        mine["path"] = p
        return mine
    update(biz_id, cid, change)


def _texts_for_church(biz: Dict[str, Any], data: Dict[str, Any], now: datetime, stats: Dict[str, int],
                      budget: Dict[str, int]) -> None:
    nh = _nh()
    import sms_alerts
    biz_id = str(biz["id"])
    if not sms_alerts.alerts_enabled():
        return
    settings = nh.settings_of(biz)
    tz = data["tz"]
    import texting_hours
    hours = texting_hours.of(biz)
    connected = data["connected"]
    texting = {cid: g for cid, g in data["guests"].items() if nh._texting(g["meta"])}
    if not texting:
        return
    phones = _phones(biz_id, sorted(texting))
    events = None
    if settings["next_step"]["on"] and settings["next_step"]["event_id"]:
        events = events_coming(biz, now)          # None: unread, the next step waits
    for cid, g in sorted(texting.items(), key=lambda kv: kv[1]["start"]):
        if budget["texts"] <= 0:
            return
        mine = g["meta"]
        p = path_of(mine, now)
        claim = p.get("claim") if isinstance(p.get("claim"), dict) else None
        if claim:
            at = _parse(str(claim.get("at") or "").split("#")[0])
            if at and now - at > CLAIM_STALE:
                # A send that started and never finished: it may have gone,
                # so it's never sent again.
                stamp = str(claim.get("at"))
                step = str(claim.get("step") or "")
                _release(biz_id, cid, stamp)
                if step in STEPS:
                    _skip(biz_id, cid, [step], now, why="unsure")
            continue
        if p.get("ended"):
            continue
        # Week one's held texts, now that the reply was answered.
        for step, wait in sorted(p["waiting"].items()):
            moment = _parse((wait or {}).get("moment"))
            if not moment:
                continue
            stale = now > moment + STALE or (
                step == "thanks" and now.astimezone(tz).date() != moment.astimezone(tz).date())
            if stale:
                _skip(biz_id, cid, [step], now, why="held", waiting=True)
                continue
            if mine.get("hold") or connected is None:
                continue
            if budget["texts"] > 0 and _resume(biz_id, g, step, wait, now, stats):
                budget["texts"] -= 1
        if connected is None:
            continue                               # who is connected couldn't be read: nothing is decided
        if cid in connected:
            _end(biz_id, cid, "connected", now)
            stats["connected"] += 1
            continue
        event = None
        if events:
            event = next((e for e in events if e["entry_id"] == settings["next_step"]["event_id"]), None)
        items = road(g, settings, hours, tz, data["times"].get(cid, []), event, now)
        hit, closed = due(items, p, now)
        if closed:
            _skip(biz_id, cid, closed, now)
            stats["skipped"] += len(closed)
        if not hit:
            continue
        step = hit[0]
        why = ("held" if mine.get("hold") else limit_says(mine, now)
               or ("" if texting_hours.in_auto_window(biz, now.astimezone(tz)) else "hours"))
        if why:
            _note_wait(biz_id, cid, step, why, now)
            stats["waiting"] += 1
            continue
        if phones is None:
            continue
        phone = nh.mobile(phones.get(cid) or (g.get("contact") or {}).get("phone"))
        if not phone:
            continue
        if _send_road(biz_id, g, step, phone, now, events, stats):
            budget["texts"] -= 1


# ─── the Saturday heads-up ────────────────────────────────────────────

def _planned_for(fus: List[Dict[str, Any]]) -> Optional[date]:
    """The day a Plan your visit card said they'd come, when it answered
    with a date (an <input type=date> answer); else None."""
    for f in fus:
        if str(f.get("path_kind") or "") != "visit":
            continue
        for a in f.get("answers") or []:
            m = re.fullmatch(r"\s*(\d{4}-\d{2}-\d{2})\s*", str((a or {}).get("a") or ""))
            if m:
                try:
                    return date.fromisoformat(m.group(1))
                except ValueError:
                    continue
    return None


def _kids_names(biz_id: str, homes: Dict[str, Set[str]], ids: List[str]) -> Dict[str, List[str]]:
    """Each guest's kids' first names, from the families they're an adult in
    (the kids desk's records). A read that fails leaves the names out."""
    want = sorted({h for cid in ids for h in homes.get(cid, set())})
    if not want:
        return {}
    import church_guests as cg
    try:
        kids = cg._all_in(f"/children?business_id=eq.{_q(biz_id)}&active=eq.true"
                          "&select=id,household_id,first_name,birthdate", "household_id", want)
    except cg.Unread:
        return {}
    by_home: Dict[str, List[str]] = {}
    # The oldest first, as a family says them.
    for k in sorted(kids, key=lambda k: (str(k.get("birthdate") or "9999"), _plain(k.get("first_name")).lower())):
        name = _plain(k.get("first_name")).split(" ")[0][:30]
        if name:
            by_home.setdefault(str(k.get("household_id")), []).append(name)
    out: Dict[str, List[str]] = {}
    for cid in ids:
        names: List[str] = []
        for h in sorted(homes.get(cid, set())):
            for n in by_home.get(h, []):
                if n not in names:
                    names.append(n)
        if names:
            out[cid] = names
    return out


def _and(names: List[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def may_come(business: Dict[str, Any], data: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    """Who may come tomorrow (see the module docstring): [{id, name, kids
    (first names), has_kids, planned, first_day}], named guests only, the
    planned visits last."""
    import church_guests as cg
    tz = data["tz"]
    today = now.astimezone(tz).date()
    tomorrow = today + timedelta(days=1)
    connected = data["connected"] or set()
    out: List[Dict[str, Any]] = []
    for cid, g in data["guests"].items():
        if not g.get("name") or cid in connected:
            continue
        if g.get("expected"):
            if g["start"] < now - timedelta(days=PLANNED_DAYS):
                continue
            said = _planned_for(g.get("fus") or [])
            if said and said != tomorrow:
                continue
            planned = True
        else:
            first = g.get("first_day")
            if not first or g.get("came_back") or not (today - timedelta(days=HEADS_UP_DAYS) <= first <= today):
                continue
            planned = False
        meta = g["meta"]
        app = meta.get("app") if isinstance(meta.get("app"), dict) else {}
        out.append({"id": cid, "name": g["name"], "planned": planned,
                    "first_day": g.get("first_day"),
                    "family": cg._family(meta, app, g.get("fus") or [])})
    names = _kids_names(str(business["id"]), data.get("homes") or {}, [o["id"] for o in out])
    for o in out:
        o["kids"] = names.get(o["id"], [])
        o["has_kids"] = bool(o["kids"]) or bool(o.pop("family"))
    out.sort(key=lambda o: (o["planned"], o["name"].lower()))
    return out


def _line(o: Dict[str, Any], *, kids_desk: bool = False) -> str:
    if kids_desk:
        kids = f"{o['name']}’s kids, {_and(o['kids'])}" if o["kids"] else f"{o['name']} and their kids"
        return kids + (" (planning a first visit)" if o["planned"] else "")
    out = o["name"] + (f", with {_and(o['kids'])}" if o["kids"] else (", with kids" if o["has_kids"] else ""))
    if o["planned"]:
        return out + " · planning a first visit"
    first = o.get("first_day")
    return out + (f" · first came {first.strftime('%A, %B')} {first.day}" if first else "")


def heads_up_words(church: str, people: List[Dict[str, Any]], *, kids_desk: bool = False) -> Dict[str, str]:
    """{subject, title, body (the push), text (the email)}."""
    n = len(people)
    names = [p["name"] for p in people]
    if kids_desk:
        subject = "Guest families who may come tomorrow"
        lead = ("These guests may bring their kids tomorrow, so someone at the kids desk can welcome them by "
                "name:")
        body = (f"{_and(names[:2])}" + (f" and {n - 2} more" if n > 2 else "")
                + (" may bring their kids tomorrow."))
    else:
        subject = "Guests who may come tomorrow"
        lead = "These guests may come tomorrow, so someone can meet them at the door by name:"
        body = (f"{_and(names[:2])}" + (f" and {n - 2} more" if n > 2 else "")
                + (" may come tomorrow." if n > 1 else " may come tomorrow."))
    lines = "\n".join(f"• {_line(p, kids_desk=kids_desk)}" for p in people)
    text = (f"{lead}\n\n{lines}\n\nNo need to reply. From {church}’s Welcome Path.")
    return {"subject": subject, "title": subject, "body": body, "text": text}


def _role_holders(biz_id: str, job: str) -> Optional[List[Dict[str, Any]]]:
    """The people who hold a role whose job is `job` (church_roles):
    [{id, name, email}]. None when it couldn't be read."""
    import church_roles as cr
    defs = cr.defs(biz_id)
    if defs is None:
        return None
    have = {d["key"] for d in defs}
    # A church still on the first version's keys keeps them
    # (church_follow_up._effective_defs): "welcome_lead", the Welcome Team lead.
    keys = sorted({d["key"] for d in defs if d.get("job") == job}
                  | {k for k, leg in cr.LEGACY.items() if leg.get("job") == job and k not in have})
    if not keys:
        return []
    held = _rows(f"/church_leader_roles?business_id=eq.{_q(biz_id)}&role=in.({','.join(_q(k) for k in keys)})"
                 "&status=eq.active&select=contact_id,role&limit=200")
    if held is None:
        return None
    ids = sorted({str(h["contact_id"]) for h in held if h.get("contact_id")})
    if not ids:
        return []
    people = _rows(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(i) for i in ids)})"
                   "&select=id,name,email&limit=200")
    if people is None:
        return None
    return sorted(({"id": str(p["id"]), "name": _plain(p.get("name")), "email": _plain(p.get("email")).lower()}
                   for p in people), key=lambda p: (p["name"].lower(), p["id"]))


def _first_guests_logins(biz_id: str) -> Optional[List[str]]:
    """The first-time guests' login (church_duties first_guests): its
    Manager logins, else the owner. None when it couldn't be read."""
    import church_duties
    from fastapi import HTTPException
    try:
        managers = church_duties.manager_holders(biz_id, "first_guests")
        if managers:
            return managers
        return church_duties.holders_of(biz_id, "first_guests")[:1]
    except HTTPException:
        return None


def heads_up_people(business: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Who the heads-up goes to now: {greeters: [{id, name, email}] (role
    holders), greeter_logins: [user ids] (only when no one holds a welcome
    role), kids: [{id, name, email}]}. None when it couldn't be read."""
    biz_id = str(business["id"])
    greeters = _role_holders(biz_id, "welcome")
    kids = _role_holders(biz_id, "kids")
    if greeters is None or kids is None:
        return None
    logins: List[str] = []
    if not greeters:
        got = _first_guests_logins(biz_id)
        if got is None:
            return None
        logins = got
    return {"greeters": greeters, "greeter_logins": logins, "kids": kids}


def _tell_login(ch: Any, uid: str, words: Dict[str, str], ref: str) -> bool:
    """A push to the office app and an email to the login's sign-in address
    (care_handoff.tell's way). True when either went. Never raises."""
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    try:
        email = cas._login_email(ch, uid)
    except Exception:  # noqa: BLE001
        email = None
    if email is None:
        return False
    rang = 0
    try:
        import push_notifications
        rang = push_notifications.send_to_user(uid, title=words["title"][:80], body=words["body"][:160], nav=NAV,
                                               tag=ref[:60], business_id=ch.b)
    except Exception:  # noqa: BLE001
        logger.info("guest heads-up: a push didn't go", exc_info=True)
    mailed = False
    if email:
        try:
            import app_base
            html = cot.render(ch.business, words["text"], words["title"], f"{app_base.app_base_url()}/?nav={NAV}",
                              "Open Guests")
            clt.deliver(ch.business, email, "", words["subject"], html, ref, reply_to=clt._office_email(ch.business))
            mailed = True
        except Exception:  # noqa: BLE001
            logger.warning("guest heads-up: an email didn't go (business %s)", ch.b[:8], exc_info=True)
    return bool(rang) or mailed


def _email_person(business: Dict[str, Any], person: Dict[str, Any], words: Dict[str, str], ref: str) -> bool:
    import church_leader_tasks as clt
    import church_office_tasks as cot
    email = clt._email_ok(person.get("email"))
    if not email:
        return False
    try:
        html = cot.render(business, words["text"], words["title"])
        clt.deliver(business, email, person.get("name") or "", words["subject"], html, ref,
                    reply_to=clt._office_email(business))
        return True
    except Exception:  # noqa: BLE001
        logger.warning("guest heads-up: an email didn't go (business %s)", str(business.get("id"))[:8],
                       exc_info=True)
        return False


def _claim_heads_up(biz_id: str, key: str) -> Optional[bool]:
    got = sb_clients.sb_post_as_service(f"/{LEDGER}?on_conflict=business_id,key",
                                        {"business_id": biz_id, "key": key, "sent_at": _iso(_now())},
                                        prefer="resolution=ignore-duplicates,return=representation")
    if not isinstance(got, list):
        return None
    return bool(got)


def _unclaim_heads_up(biz_id: str, key: str) -> None:
    try:
        sb_clients.sb_delete_as_service(f"/{LEDGER}?business_id=eq.{_q(biz_id)}&key=eq.{_q(key)}")
    except Exception:  # noqa: BLE001
        logger.warning("guest heads-up: a claim wasn't let go (business %s)", biz_id[:8], exc_info=True)


def heads_up_key(saturday: date) -> str:
    return f"guest-heads-up-{saturday.isoformat()}-sat"


def heads_up(business: Dict[str, Any], data: Dict[str, Any], now: datetime, stats: Dict[str, int]) -> bool:
    """Saturday's heads-up for one church (see the module docstring). True
    when it went to someone."""
    nh = _nh()
    biz_id = str(business["id"])
    tz = data["tz"]
    local = now.astimezone(tz)
    if local.weekday() != HEADS_UP_DAY or not HEADS_UP_FROM <= local.hour < HEADS_UP_UNTIL:
        return False
    which = nh.settings_of(business)["heads_up"]
    if not which["greeters"] and not which["kids"]:
        return False
    people = may_come(business, data, now)
    if not people:
        return False
    key = heads_up_key(local.date())
    sent = _rows(f"/{LEDGER}?business_id=eq.{_q(biz_id)}&key=eq.{_q(key)}&select=key&limit=1")
    if sent is None or sent:
        return False
    who = heads_up_people(business)
    if who is None:
        return False
    with_kids = [p for p in people if p["has_kids"]]
    plan: List[Tuple[str, Any, Dict[str, str]]] = []      # (kind, person or uid, words)
    church = _plain(business.get("name")) or "your church"
    if which["greeters"]:
        words = heads_up_words(church, people)
        plan += [("person", p, words) for p in who["greeters"]]
        plan += [("login", uid, words) for uid in who["greeter_logins"]]
    if which["kids"] and with_kids and who["kids"]:
        words = heads_up_words(church, with_kids, kids_desk=True)
        mine = {p["id"] for p in who["greeters"]} if which["greeters"] else set()
        plan += [("person", p, words) for p in who["kids"] if p["id"] not in mine]
    if not plan:
        return False
    claimed = _claim_heads_up(biz_id, key)
    if not claimed:
        return False
    import church_over as co
    ch = co.Church(business)
    try:
        by_person = {c: u for u, c in ch.login_person.items()}
    except Exception:  # noqa: BLE001 — the person still gets the email
        by_person = {}
    told = 0
    seen: Set[str] = set()
    for kind, who_, words in plan:
        ref = f"guest-heads-up-{biz_id}-{local.date().isoformat()}-{kind}-{who_ if kind == 'login' else who_['id']}"
        if kind == "login":
            if who_ in seen:
                continue
            seen.add(who_)
            told += _tell_login(ch, who_, words, ref)
            continue
        uid = by_person.get(who_["id"])
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
            told += _tell_login(ch, uid, words, ref)
        else:
            told += _email_person(business, who_, words, ref)
    if not told:
        _unclaim_heads_up(biz_id, key)        # nobody heard: the next tick tries again
        return False
    stats["heads_up"] += 1
    print(f"[guest_path_weeks] {biz_id[:8]}: Saturday heads-up to {told} about {len(people)} guests", flush=True)
    return True


# ─── the sweep ────────────────────────────────────────────────────────

def _empty_stats() -> Dict[str, int]:
    return {"churches": 0, "sent": 0, "resumed": 0, "waiting": 0, "skipped": 0, "connected": 0, "failed": 0,
            "heads_up": 0}


def _maybe_busy(guests: List[Dict[str, Any]], now: datetime) -> bool:
    """Whether a church's guests might have a text due: one whose texts
    started and whose path hasn't ended or finished."""
    nh = _nh()
    for c in guests:
        mine = _meta(c)
        if not nh._texting(mine):
            continue
        p = path_of(mine, now)
        if p.get("ended"):
            continue
        if p["waiting"] or p.get("claim") or len(set(p["sent"]) | set(p["skipped"])) < len(STEPS):
            return True
    return False


def sweep_church(biz_id: str, guests: List[Dict[str, Any]], now: datetime, stats: Dict[str, int],
                 budget: Dict[str, int]) -> None:
    biz = _church_ok(biz_id)
    if not biz:
        return
    tz = _nh().tz_of(biz)
    local = now.astimezone(tz)
    saturday = local.weekday() == HEADS_UP_DAY and HEADS_UP_FROM <= local.hour < HEADS_UP_UNTIL
    busy = budget["texts"] > 0 and _maybe_busy(guests, now)
    if not busy and not (saturday and budget["heads_up"] > 0):
        return
    data = gather(biz, now)
    if data is None:
        return
    stats["churches"] += 1
    if saturday and budget["heads_up"] > 0:
        try:
            if heads_up(biz, data, now, stats):
                budget["heads_up"] -= 1
        except Exception:  # noqa: BLE001
            logger.warning("guest heads-up failed for business %s", biz_id[:8], exc_info=True)
    if busy:
        _texts_for_church(biz, data, now, stats, budget)


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes (kmj_intake_automation, beside the follow-up sweep):
    each church with a guest whose path started in the last WINDOW_DAYS.
    Sync: the scheduler runs it on a worker thread."""
    stats = _empty_stats()
    import guest_path
    if guest_path.mode() == "off":
        return stats
    now = now or _now()
    import sample_church
    since = _iso(now - timedelta(days=WINDOW_DAYS))
    rows = _rows(f"/contacts?metadata->new_here->>texted_at=gte.{_q(since)}&select=id,business_id,metadata"
                 f"&order=business_id.asc&limit=5000{sample_church.exclude()}")
    if rows is None:
        print("[guest_path_weeks] the guests couldn't be read; nothing decided this tick", flush=True)
        return stats
    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in sample_church.drop_samples(rows):
        by_biz.setdefault(str(r["business_id"]), []).append(r)
    order = sorted(by_biz)
    random.shuffle(order)                    # a busy church never crowds the same ones out every tick
    budget = {"texts": MAX_TEXTS_PER_TICK, "heads_up": MAX_HEADS_UP_PER_TICK}
    for biz_id in order:
        if budget["texts"] <= 0 and budget["heads_up"] <= 0:
            break
        try:
            sweep_church(biz_id, by_biz[biz_id], now, stats, budget)
        except Exception:  # noqa: BLE001
            logger.warning("guest path sweep failed for business %s", biz_id[:8], exc_info=True)
    if any(stats[k] for k in ("sent", "resumed", "heads_up", "skipped", "connected", "failed")):
        print(f"[guest_path_weeks] tick: {stats}", flush=True)
    return stats


# ─── the room (GET /new-here's "path") ────────────────────────────────

def _hour_words(hour: int) -> str:
    import texting_hours as th
    return th.hour_words(hour)


def room_view(business: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    """What the Guests room's path editor shows beside the church's words:
    who signs the Monday note, the events it can pick from, when each road
    text goes, who hears on Saturday, and the limits. Parts that couldn't
    be read are None (the room says so)."""
    import texting_hours as th
    hours = th.of(business)
    road_hour = _hour_words(min(max(ROAD_HOUR, hours["auto_from"]), hours["auto_until"] - 1))
    sig = settings["signature"]
    by_role = signer(business, {"signature": {"on": True, "name": ""}})
    events = events_coming(business)
    picked = settings["next_step"]["event_id"]
    event = next((e for e in events or [] if e["entry_id"] == picked), None) if picked else None
    people = None
    try:
        who = heads_up_people(business)
    except Exception:  # noqa: BLE001
        who = None
    if who is not None:
        names: List[str] = [p["name"] for p in who["greeters"] if p["name"]]
        if who["greeter_logins"]:
            import care_handoff
            import church_over as co
            ch = co.Church(business)
            for uid in who["greeter_logins"]:
                try:
                    names.append(care_handoff._called(ch, uid))
                except Exception:  # noqa: BLE001
                    names.append(care_handoff.OFFICE)
        people = {"greeters": names, "greeters_from": "welcome" if who["greeters"] else "first_guests",
                  "kids": [p["name"] for p in who["kids"] if p["name"]]}
    return {
        "signer": signer(business, settings, even_off=True),
        "signer_from": "church" if sig["name"] else ("role" if by_role else ""),
        "signer_role": by_role,
        "events": events,
        "event": event,
        "event_gone": bool(picked and events is not None and not event),
        "when": {
            "back": f"The day they come back, about {BACK_HOURS} hours after they arrive",
            "thinking": f"Week two, Wednesday at {road_hour} · only if they haven’t been back",
            "next_step": f"Week three, Wednesday at {road_hour} · both roads",
            "door_open": f"Week four, Wednesday at {road_hour} · only if they haven’t been back · then the texts rest",
            "heads_up": f"Saturday at {_hour_words(HEADS_UP_FROM)} · to your team, not the guest",
        },
        "heads_up_to": people,
        "limits": {"week": WEEK_MAX, "after_week_one": AFTER_MAX},
        "connected_means": CONNECTED_MEANS,
        "steps": list(STEPS),
    }
