"""church_leaders_note.py — the Monday leaders note.

Kevin, 2026-10-27 (the leadership plan, artifact D68g78Hu7ULPXpwgkg1v5Y, and
its meeting playbook Evd8431XHqafeFpSXSgCFr): "let's build". Every Monday
the church office sends one short note to all the church's leaders: this
week's calendar, what's needed, and one win. The app puts the draft
together from the church's own data; the Church Administrator reads it,
changes what they like, writes the win and sends it. No model is called:
the draft is assembled from rows, so it costs nothing.

    THIS WEEK ...... the church's next seven days, read where the church
                     calendar reads them: the Sunday plans
                     (worship_services), Services & Events (the
                     event_roster rooms; an invite-only occasion stays
                     out), rooms booked (church_space_bookings, booked
                     only; a rental is said without its renter) and the
                     groups that meet (groups.meet_day, group_gatherings)
    WHAT'S NEEDED .. the places still open on the Sunday teams for each
                     service in those days (sunday_planning: a place with
                     no one, offered to the team, or a no), the roles an
                     event still needs (events_rsvp_router.role_fill), and
                     how many people in follow-up have no one yet (a
                     count, never a name). Nothing else: never invented
    ONE WIN ........ left blank for the office to write

Who gets it: everyone in the church's "All group leaders" room
(member_portal_messaging.leaders_room_people), at their own email as one
of the church's people. The note says who has no email. It goes by email,
through the path the Board's "Send minutes" uses (email_layout +
email_sender.send_via_resend, the church's identity, a key per send). The
leaders' chat can't carry it: a chat message needs a member sender.

Text it too (Kevin, 2026-11-17, approving it for the Office & Leadership
admin: "make this happen please"): with also_text, the same leaders whose
numbers said yes to the church's texts also get a short text of it
(text_version: the subject and the note's first lines, at most TEXT_SHORT
letters, only the note's own words), sent the way an announcement goes
(sms_routing.text_people: one text a number, STOP always wins, the church's
name first and the way out last, counted on the church's texts). A leader
who hasn't said yes is never texted. The card and the church's quiet hours
are checked before the week is taken: in quiet hours the send is refused,
saying when texts can go, rather than held. The gate is the note's own: the
same note to the same people, so it needs no weekly_text duty.

Text them again (Kevin, 2026-11-17, "build that"): a text that failed to
go through can be sent again, the same week, to the leaders it missed and
nobody else. The send keeps who it missed (`failed_ids`: contact ids, never
numbers) and the exact words it sent (`short`) in the week's record;
POST /text-again sends those same words to those same leaders, through the
same send (yes and STOP checked again, so a leader who has since said STOP
or never said yes is never texted), under the note's own gate, the card and
quiet hours (refused, as the send is). When the email went without the text
(or the text couldn't go at all: who said yes couldn't be read), the same
button sends the week's text for the first time, to every leader who said
yes. At most AGAIN_MOST times a week, and only in the week the note went.
Each one takes the record under a new id first, so two presses text once.

Who sends it: the owner, admins, and a Manager seat that does the leaders
note (church_duties "leaders_note": the Office & Leadership lane's by
default, or whoever it was given to; a Manager no lane names, by the areas
it works, as the Office area decided before duties). Once a week: one send
per church per Monday-start week on the church's clock. The last send (when,
who, how many, the words)
is kept in businesses.settings.church_leaders_note, merged into the live
settings and swapped only when nobody else changed it in between, so two
people pressing Send at once send once. No table, no migration.

  GET  /church/leaders-note/status?business_id=   {enabled}
  GET  /church/leaders-note?business_id=          the draft, who it goes to (`texts`: how many
                                                  of the leaders get the church's texts), the last send
  POST /church/leaders-note/send                  {business_id, subject, text, also_text?}
  POST /church/leaders-note/text-again            {business_id}: this week's text, to whoever it missed

The record is a server key (business_settings.SERVER_KEYS): the app can't
write it, so who gets a text again is only ever what a send recorded.

Switched by CHURCH_LEADERS_NOTE: off | owner | on (on by default since 2026-11-17).
A read that fails is a 503, never an empty note.
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import business_access
import sb_clients
from auth_supabase import AuthedUser, require_user
from church_duties import holds, refusal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/leaders-note", tags=["church"])

KEY = "church_leaders_note"          # businesses.settings[KEY]: the last send
DAYS = 7                             # "this week": today and the six days after
SUBJECT_MAX, TEXT_MAX = 150, 8000
GROUPS_NAMED = 8                     # the groups line names this many, then "and N more"
SAME_GATHERING = timedelta(hours=2)  # a plan and its occasion, as the calendar says
HEADINGS = ("This week", "What’s needed", "One win")
KEEPS_ALL = ("owner", "admin")
LEADERS_NOTE = "leaders_note"        # the church duty that sends it (church_duties)
NOT_CHURCH = "The leaders note is for churches"
DAY_RE = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), [A-Z][a-z]+ \d{1,2}$")
TEXT_SHORT = 300                     # the text version's letters at most, before the church's name and the way out
CUT = "..."                          # plain dots: an ellipsis would bill the whole text at the UCS-2 rate
TEXT_EVENT = "leaders_note_text"     # its events row: never an announcement (the weekly text's check reads those)
AGAIN_MOST = 2                       # "Text them again" at most this many times a week
IDS_MOST = 200                       # who a text missed, kept at most (a leaders room is far smaller)


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_LEADERS_NOTE") or "on").strip().lower()
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
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
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
    """A read that must answer: a failed one is a 503, never an empty note."""
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The leaders note couldn't be put together just now. Try again.")
    return rows


def _chunks(ids: Iterable[Any], n: int = 100) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _zone(biz: Dict[str, Any]):
    """The church's clock, as Sunday Planning and the groups read it
    (business_marketing.business_tz: the availability zone, else the
    owner's profile, else the platform's). A clock that can't be read is
    a 503: a week is never cut on a guessed clock."""
    import group_gatherings
    tz = group_gatherings.zone(biz)
    if tz is None:
        raise HTTPException(503, "The church's clock couldn't be read just now. Try again.")
    return tz


def clock(d: datetime) -> str:
    """'7:00 PM'."""
    return f"{d.strftime('%I').lstrip('0') or '12'}:{d:%M} {d:%p}"


def day_words(d: date) -> str:
    """'Sunday, November 1'."""
    return f"{d:%A}, {d:%B} {d.day}"


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


# ─── Who's asking ─────────────────────────────────────────────────────

def _business(biz_id: str) -> Dict[str, Any]:
    rows = _need(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and the login sending its note: the owner, an admin, or a
    Manager that does the leaders note (church_duties "leaders_note": the
    Office & Leadership lane's by default, or whoever it was given to; a
    Manager no lane names, by the areas it works, as before). 404 when the
    switch is closed to them, they have no such seat here, or it isn't a
    church; 403 for a Manager that doesn't do it, naming whose job it is; a
    failed read of the duty is a 503, never a yes."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "manager")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    if role not in KEEPS_ALL and not holds(biz_id, user, LEADERS_NOTE):
        raise HTTPException(403, refusal(biz_id, LEADERS_NOTE))
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user}


# ─── This week: the calendar ──────────────────────────────────────────

def _item(day: date, at: Optional[datetime], title: str, where: str = "", kind: str = "event") -> Dict[str, Any]:
    return {"day": day, "at": at, "title": _plain(title) or "Untitled", "where": _plain(where), "kind": kind}


def _plans(biz_id: str, lo: datetime, hi: datetime, tz) -> List[Dict[str, Any]]:
    """The Sunday plans in the days (worship_services: ChurchSavvy's and
    Sunday Planning's one table). An event date (serve_dates) is the
    volunteers' schedule for an event, not a plan: it stays out."""
    import serve_dates
    rows = _need(f"/worship_services?business_id=eq.{_q(biz_id)}&archived_at=is.null&is_template=eq.false"
                 f"{serve_dates.plans_only()}"
                 f"&starts_at=gte.{_q(_iso(lo))}&starts_at=lt.{_q(_iso(hi))}"
                 f"&select=id,title,starts_at{serve_dates.fields()}&order=starts_at.asc&limit=100")
    out = []
    for r in rows:
        d = _at(r.get("starts_at"))
        if not d:
            continue
        local = d.astimezone(tz)
        # needs: an event date's own numbers (never one here: plans_only), read by serve_dates.needed.
        out.append({**_item(local.date(), local, r.get("title") or "Sunday service", kind="service"),
                    "id": str(r["id"]), "needs": r.get("needs")})
    return out


def _roster_kind(data: Dict[str, Any], day: date, noun: Optional[str]) -> str:
    """A Services & Events occasion is a service or an event (the
    calendar's rosterKind): its own type, else its room's noun, else a
    Sunday one is the service."""
    t = str(data.get("type") or "").strip().lower()
    if t:
        return "service" if t == "service" else "event"
    if noun:
        return "service" if re.search(r"\bservices?\b", noun, re.I) else "event"
    return "service" if day.weekday() == 6 else "event"


def _when_of(raw: Any, tz) -> Tuple[Optional[date], Optional[datetime]]:
    """An occasion's day, and its time when it carries one. A time with no
    zone is the church's own wall clock (how the app saves it)."""
    s = str(raw or "").strip()
    if not s:
        return None, None
    if re.search(r"T\d{2}:\d{2}", s):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            d = None
        if d is not None:
            local = d.astimezone(tz) if d.tzinfo else d.replace(tzinfo=tz)
            return local.date(), local
    try:
        return date.fromisoformat(s[:10]), None
    except ValueError:
        return None, None


def _occasions(biz_id: str, first: date, last: date, tz) -> List[Dict[str, Any]]:
    """Services & Events in the days, with the roles each still needs. An
    invite-only occasion is for the people it was shared with, so it
    stays out of a note to every leader."""
    import events_rsvp_router as ev
    mods = _need(f"/custom_modules?business_id=eq.{_q(biz_id)}&archetype=eq.event_roster&is_active=eq.true"
                 "&select=id,name,archetype_params&limit=50")
    if not mods:
        return []
    fields = {str(m["id"]): ev.resolve_fields(m.get("archetype_params")) for m in mods}
    out: List[Dict[str, Any]] = []
    for chunk in _chunks(fields):
        for e in _need(f"/module_entries?business_id=eq.{_q(biz_id)}&module_id=in.({','.join(chunk)})"
                       "&status=eq.active&select=id,module_id,data&order=created_at.desc&limit=1000"):
            f = fields.get(str(e.get("module_id")))
            data = e.get("data") if isinstance(e.get("data"), dict) else {}
            if not f or ev.occasion_visibility(data) == "invite":
                continue
            day, at = _when_of(data.get(f["date_field"]), tz)
            if not day or not first <= day <= last:
                continue
            signups = ev.read_signups(data, f["signups_field"])
            short = []
            for role in ev.occasion_roles(data, f["roles"]):
                fill = ev.role_fill(role, signups)
                if not fill["full"]:
                    short.append(f"{_plain(fill['label'])} needs {fill['needed'] - fill['filled']} more")
            out.append({**_item(day, at, data.get(f["title_field"]) or "", data.get(f["location_field"]) or "",
                                kind=_roster_kind(data, day, f["occasion_noun"])),
                        "short": short})
    return out


def _rooms(biz_id: str, lo: datetime, hi: datetime, tz) -> List[Dict[str, Any]]:
    """Rooms booked in the days (a request isn't on the calendar until it's
    approved). A rental is said without its renter."""
    rows = _need(f"/church_space_bookings?business_id=eq.{_q(biz_id)}&status=eq.booked"
                 f"&start_at=lt.{_q(_iso(hi))}&end_at=gt.{_q(_iso(lo))}"
                 "&select=id,space_id,title,start_at,kind&order=start_at.asc&limit=300")
    if not rows:
        return []
    names: Dict[str, str] = {}
    for chunk in _chunks(r.get("space_id") for r in rows):
        for s in _need(f"/church_spaces?business_id=eq.{_q(biz_id)}&id=in.({','.join(chunk)})&select=id,name&limit=200"):
            names[str(s["id"])] = _plain(s.get("name")) or "A room"
    out = []
    for r in rows:
        d = _at(r.get("start_at"))
        if not d or d < lo:
            continue    # one that began before the days is already under way
        local = d.astimezone(tz)
        rental = r.get("kind") == "rental"
        out.append({**_item(local.date(), local, "booked for a rental" if rental else (r.get("title") or "Booked"),
                            kind="room"),
                    "room": names.get(str(r.get("space_id"))) or "A room", "rental": rental,
                    "match": "" if rental else _plain(r.get("title")).lower()})
    return out


def _groups(biz_id: str, first: date, last: date) -> List[Tuple[date, str]]:
    """The groups that meet in the days: each group's regular day (and its
    every-other-week or monthly turn), skipped dates left out."""
    import group_gatherings as gg
    rows = _need(f"/groups?business_id=eq.{_q(biz_id)}&active=eq.true"
                 "&select=id,name,meet_day,meet_time,meet_every,meet_from,meet_nth,meet_skips&order=name.asc&limit=500")
    out = []
    for g in rows:
        if not gg.scheduled(g):
            continue
        skips = {str(s)[:10] for s in (g.get("meet_skips") or [])}
        d = first
        while d <= last:
            if d.weekday() == int(g["meet_day"]) and gg.on_cycle(g, d) and d.isoformat() not in skips:
                out.append((d, _plain(g.get("name")) or "A group"))
            d += timedelta(days=1)
    out.sort(key=lambda x: (x[0], x[1].lower()))
    return out


def calendar(plans: List[Dict[str, Any]], occasions: List[Dict[str, Any]], rooms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One list for the days: the plans; each occasion unless it is the
    same service as a plan (one day, within two hours, or no time on one
    side); and each room, folded into the gathering it was booked for
    (same day, same name, within two hours) as its place."""
    items = list(plans)
    for o in occasions:
        if o["kind"] == "service" and any(
                p["day"] == o["day"] and (not p["at"] or not o["at"] or abs(p["at"] - o["at"]) <= SAME_GATHERING)
                for p in plans):
            continue
        items.append(o)
    for r in rooms:
        host = next((i for i in items if r["match"] and i["day"] == r["day"] and i["title"].lower() == r["match"]
                     and (not i["at"] or abs(i["at"] - r["at"]) <= SAME_GATHERING)), None)
        if host is not None:
            if not host["where"]:
                host["where"] = r["room"]
            continue
        items.append({**r, "title": f"{r['room']}: {r['title']}"})
    items.sort(key=lambda i: (i["day"], i["at"] is not None, i["at"].timetz().isoformat() if i["at"] else "", i["title"].lower()))
    return items


def week_text(items: List[Dict[str, Any]], groups: List[Tuple[date, str]]) -> str:
    """The days as the note says them: each day, then its gatherings, one
    a line; then the groups meeting, on one line."""
    blocks: List[str] = []
    day: Optional[date] = None
    lines: List[str] = []
    for i in items:
        if i["day"] != day:
            if lines:
                blocks.append("\n".join(lines))
            day, lines = i["day"], [day_words(i["day"])]
        lines.append(" · ".join(x for x in (clock(i["at"]) if i["at"] else "All day", i["title"], i["where"]) if x))
    if lines:
        blocks.append("\n".join(lines))
    if groups:
        said = [f"{name} ({d:%A})" for d, name in groups[:GROUPS_NAMED]]
        more = len(groups) - len(said)
        blocks.append(("Groups meeting: " if len(groups) > 1 else "A group meeting: ") + ", ".join(said)
                      + (f", and {more} more" if more else "") + ".")
    return "\n\n".join(blocks)


# ─── What's needed ────────────────────────────────────────────────────

def _sunday_places(biz_id: str, plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each plan in the days, the places still open on the Sunday
    teams (the schedule page's rule: no one, offered to the team, or a
    no) and how many asked haven't answered. The teams are
    sunday_planning's: a serving team with turns, its group active."""
    if not plans:
        return []
    import serve_dates
    serve = _need(f"/serve_teams?business_id=eq.{_q(biz_id)}&select=group_id,sort&limit=100")
    if not serve:
        return []
    groups = {str(g["id"]): _plain(g.get("name")) for g in _need(
        f"/groups?business_id=eq.{_q(biz_id)}&kind=eq.team&active=eq.true&select=id,name&limit=200")}
    team_ids = [str(s["group_id"]) for s in sorted(serve, key=lambda s: int(s.get("sort") or 0)) if str(s["group_id"]) in groups]
    if not team_ids:
        return []
    places = _need(f"/serve_positions?business_id=eq.{_q(biz_id)}&group_id=in.({','.join(_q(t) for t in team_ids)})"
                   "&active=eq.true&select=id,group_id,name,needed,sort&order=sort.asc&limit=500")
    if not places:
        return []
    rows = _need(f"/serve_assignments?business_id=eq.{_q(biz_id)}&service_id=in.({','.join(_q(p['id']) for p in plans)})"
                 "&select=service_id,position_id,slot,status&limit=5000")
    held = {(str(r["service_id"]), str(r["position_id"]), int(r.get("slot") or 1)): r.get("status") for r in rows}
    order = {t: n for n, t in enumerate(team_ids)}
    out = []
    for p in plans:
        open_by: Dict[str, Dict[str, int]] = {}
        waiting = total = 0
        for place in sorted(places, key=lambda x: (order.get(str(x["group_id"]), 99), int(x.get("sort") or 0))):
            for slot in range(1, serve_dates.needed(p, {**place, "id": str(place["id"])}) + 1):
                status = held.get((p["id"], str(place["id"]), slot))
                if status is None or status in ("offered", "no"):
                    team = open_by.setdefault(str(place["group_id"]), {})
                    name = _plain(place.get("name")) or "A place"
                    team[name] = team.get(name, 0) + 1
                    total += 1
                elif status == "asked":
                    waiting += 1
        if total or waiting:
            out.append({"plan": p, "open": total, "waiting": waiting,
                        "teams": [(groups[t], open_by[t]) for t in team_ids if t in open_by]})
    return out


def needed_text(sunday: List[Dict[str, Any]], occasions: List[Dict[str, Any]], no_one: int) -> str:
    """Each need on its own line: what's open, by name, and nothing more."""
    lines: List[str] = []
    for s in sunday:
        p = s["plan"]
        head = f"{p['title']}, {day_words(p['day'])}"
        bits = []
        if s["open"]:
            teams = ". ".join(f"{team}: " + ", ".join(f"{name} ({k})" if k > 1 else name for name, k in names.items())
                              for team, names in s["teams"])
            bits.append(f"{_n(s['open'], 'place is', 'places are')} still open. {teams}.")
        if s["waiting"]:
            bits.append(f"{_n(s['waiting'], 'person was', 'people were')} asked and {'hasn’t' if s['waiting'] == 1 else 'haven’t'} answered yet.")
        lines.append(f"{head}: " + " ".join(bits))
    for o in occasions:
        if o.get("short"):
            lines.append(f"{o['title']}, {day_words(o['day'])}: " + "; ".join(o["short"]) + ".")
    if no_one:
        lines.append(f"{_n(no_one, 'person', 'people')} in follow-up {'has' if no_one == 1 else 'have'} no one to reach "
                     "out to them yet. If you can take one, let the office know.")
    return "\n\n".join(lines)


def _no_one(biz_id: str) -> int:
    """People in follow-up with no one (handed back, or never handed): a
    count, never a name."""
    rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz_id)}&status=in.(open,handed_back)"
                 "&select=status,leader_contact_id&limit=1000")
    return sum(1 for r in rows if r.get("status") == "handed_back" or not r.get("leader_contact_id"))


# ─── Who gets it ──────────────────────────────────────────────────────

def recipients(biz_id: str) -> Dict[str, Any]:
    """Everyone in the All group leaders room, as one of the church's
    people: who has an email (one email to an address, however many share
    it) and who doesn't, and each leader with a number (`phones`, for the
    text: which of them said yes is the text's own check)."""
    import member_portal_messaging as mpm
    room = mpm.leaders_room_people(biz_id)
    if room is None:
        raise HTTPException(503, "The leaders couldn't be read just now. Try again.")
    ids = [str(p.get("contact_id")) for p in room if p.get("contact_id")]
    people: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunks(ids):
        for c in _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(chunk)})&select=id,name,email,phone&limit=200"):
            people[str(c["id"])] = c
    to: List[Dict[str, str]] = []
    no_email: List[str] = []
    phones: List[Dict[str, str]] = []
    seen = set()
    for cid in sorted(people, key=lambda i: (_plain(people[i].get("name")) or "~").lower()):
        c = people[cid]
        name = _plain(c.get("name")) or "Someone"
        if str(c.get("phone") or "").strip():
            phones.append({"id": cid, "name": name, "phone": str(c["phone"]).strip()})
        email = str(c.get("email") or "").strip()
        if "@" not in email or " " in email:
            no_email.append(name)
            continue
        if email.lower() in seen:
            continue
        seen.add(email.lower())
        to.append({"contact_id": cid, "name": name, "email": email})
    return {"to": to, "no_email": no_email, "leaders": len(people), "phones": phones}


# ─── The text version ─────────────────────────────────────────────────

def text_version(subject: Any, text: Any) -> str:
    """The note as one short text: the subject, then the note's own lines in
    order with the headings left out, cut at a word to TEXT_SHORT letters
    with plain dots. In plain letters, so no part of it bills as UCS-2: the
    calendar's dot between words is a dash, and curly quotes and long dashes
    are swapped as every text's are (twilio_sms.gsm_safe). Only the note's
    own words: never who has no email, an address or a number. The app's
    textVersion (leadersNoteCore) says it the same way, so the screen shows
    exactly what goes; the church's name leads it and the way out ends it
    when it's sent (sms_service.compose_outbound_body)."""
    import twilio_sms
    heads = {h.replace("’", "'").lower() for h in HEADINGS}
    body = [ln for ln in (_plain(x) for x in str(text or "").replace("\r\n", "\n").split("\n"))
            if ln and ln.replace("’", "'").lower() not in heads]
    out = twilio_sms.gsm_safe("\n".join(ln for ln in [_plain(subject)] + body if ln).replace("·", "-"))
    if len(out) <= TEXT_SHORT:
        return out
    room = TEXT_SHORT - len(CUT)
    cut = out[:room]
    if out[room] not in " \n":
        at = max(cut.rfind(" "), cut.rfind("\n"))
        if at >= room // 2:
            cut = cut[:at]
    return cut.rstrip(" \n-,;:.") + CUT


def _said_yes(biz_id: str, phones: List[str]) -> Optional[set]:
    """Which of these numbers get the church's texts: the announcement's own
    rule (sms_alerts.said_yes_to_texts). None when it can't be told."""
    import httpx
    import sms_alerts

    async def ask():
        async with httpx.AsyncClient() as client:
            return await sms_alerts.said_yes_to_texts(client, biz_id, phones)
    try:
        return asyncio.run(ask())
    except Exception:
        logger.warning("leaders note: who gets texts wasn't read", exc_info=True)
        return None


def quiet_now(biz: Dict[str, Any]) -> bool:
    """Quiet hours at the church right now (member_push.quiet_hour: its own
    hours, Text → Texting hours). False when it can't be told, as there."""
    import member_push
    try:
        return bool(member_push.quiet_hour(biz, _now()))
    except Exception:
        return False


def quiet_words(biz: Dict[str, Any], again: bool = False) -> str:
    """Why no text can go now, and when one can. `again`: for Text them
    again, where the email has already gone."""
    import texting_hours as th
    h = th.of(biz)
    church = _plain(biz.get("name")) or "the church"
    head = (f"It's quiet hours at {church} ({th.hour_words(h['quiet_from'])} to {th.hour_words(h['quiet_until'])}), "
            "so texts can't go now.")
    if again:
        return f"{head} Send the text after {th.hour_words(h['quiet_until'])}."
    return f"{head} Send it with the text after {th.hour_words(h['quiet_until'])}, or send the email alone now."


def text_reach(biz: Dict[str, Any], people: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """For "Text it too (12 of 18 leaders get texts)": how many of the
    leaders have a number that said yes (`reach`; two sharing a number are
    both reached), how many texts that is (`numbers`), whether it's quiet
    hours now and what that means, and the name the text leads with. None
    when who said yes can't be read: the screen then offers no text."""
    from sms_service import normalize_phone
    phones = [normalize_phone(p.get("phone")) for p in people.get("phones") or []]
    yes = _said_yes(str(biz["id"]), sorted({p for p in phones if p}))
    if yes is None:
        return None
    quiet = quiet_now(biz)
    return {"leaders": people["leaders"], "reach": sum(1 for p in phones if p and p in yes),
            "numbers": len({p for p in phones if p} & yes), "quiet": quiet,
            "quiet_words": quiet_words(biz) if quiet else "",
            "name": biz.get("name") or "the business", "most": TEXT_SHORT}


def _text(biz_id: str, to: List[Dict[str, str]], short: str) -> Dict[str, Any]:
    """The short text to these leaders (each {id, name, phone}) through
    sms_routing.text_people, the announcement's own send: only a number that
    said yes, STOP checked right before each. With `went` and `missed`, the
    leaders (contact ids) it reached and the ones a failed text missed. When
    none went, `error`; `unsure` when the send broke partway, so who got it
    can't be told (never sent again then)."""
    import sms_routing
    from sms_service import normalize_phone
    try:
        out = asyncio.run(sms_routing.text_people(biz_id, to, short, event=TEXT_EVENT))
    except Exception:
        logger.warning("leaders note: the text didn't go", exc_info=True)
        return {"error": "The text didn't go just now.", "unsure": True}
    if out.get("error"):
        return {"error": str(out["error"])}
    went = set(out.get("sent_to") or ())
    missed = set(out.get("failed_to") or ())
    return {**out,
            "went": [p["id"] for p in to if normalize_phone(p.get("phone")) in went],
            "missed": sorted({str(p["id"]) for p in to if p.get("id") and normalize_phone(p.get("phone")) in missed})}


def text_leaders(biz_id: str, people: Dict[str, Any], short: str) -> Dict[str, Any]:
    """The short text to the leaders whose numbers said yes: how many leaders
    it reached (`sent`; a shared number reaches each who shares it), how many
    texts went (`texts`), how many leaders it skipped (no number, no yes, or
    STOP), how many a failed text missed, and the text as it went. Kept for
    Text them again: who a failed text missed (`failed_ids`, contact ids) and
    the words it sent (`short`). When none could go it says why (`error`;
    `none_went` when the send stopped before any text, so the week's text can
    still go); the email has gone either way."""
    out = _text(biz_id, people.get("phones") or [], short)
    if out.get("error"):
        rec = {"sent": 0, "texts": 0, "skipped": 0, "failed": 0, "body": "", "error": out["error"], "short": short,
               "failed_ids": []}
        if not out.get("unsure"):
            rec["none_went"] = True
        return rec
    reached, missed = len(out["went"]), out["missed"]
    failed = len(missed)
    return {"sent": reached, "texts": int(out.get("sent") or 0), "skipped": max(0, people["leaders"] - reached - failed),
            "failed": failed, "body": str(out.get("body") or ""), "short": short, "failed_ids": missed[:IDS_MOST]}


# ─── The last send, kept in the church's settings ─────────────────────

def _settings(biz: Dict[str, Any]) -> Dict[str, Any]:
    s = biz.get("settings")
    return s if isinstance(s, dict) else {}


def last_of(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rec = _settings(biz).get(KEY)
    return rec if isinstance(rec, dict) and rec.get("id") else None


def swap(biz_id: str, expect: Optional[str], rec: Optional[Dict[str, Any]]) -> bool:
    """Put `rec` where the last send is kept (None takes it away), only if
    what's there is still `expect` (a send's id, or nothing). The live
    settings are read fresh and merged, so no other key is touched; the
    write is filtered on the note's id, so a send someone else made in
    between is never overwritten. False when it moved or didn't save."""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,settings&limit=1")
    if not isinstance(rows, list) or not rows:
        return False
    settings = dict(_settings(rows[0]))
    now = settings.get(KEY) if isinstance(settings.get(KEY), dict) else None
    if (now or {}).get("id") != expect:
        return False
    if rec is None:
        settings.pop(KEY, None)
    else:
        settings[KEY] = rec
    where = f"settings->{KEY}->>id=eq.{_q(expect)}" if expect else f"settings->{KEY}=is.null"
    got = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz_id)}&{where}", {"settings": settings})
    return isinstance(got, list) and bool(got)


def last_view(rec: Optional[Dict[str, Any]], tz) -> Optional[Dict[str, Any]]:
    if not rec:
        return None
    at = _at(rec.get("sent_at"))
    return {"week": rec.get("week"), "sent_at": rec.get("sent_at"),
            "sent_words": f"{day_words(at.astimezone(tz).date())} at {clock(at.astimezone(tz))}" if at else "",
            "by_name": rec.get("by_name") or "", "sent": int(rec.get("sent") or 0),
            "no_email": list(rec.get("no_email") or []), "failed": list(rec.get("failed") or []),
            "subject": rec.get("subject") or "", "text": rec.get("text") or "",
            "sending": rec.get("state") == "sending", "texts": _texts_view(rec.get("texts"))}


def _texts_view(t: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(t, dict):
        return None
    return {"sent": int(t.get("sent") or 0), "texts": int(t.get("texts") or 0), "skipped": int(t.get("skipped") or 0),
            "failed": int(t.get("failed") or 0), "body": str(t.get("body") or ""), "error": str(t.get("error") or "")}


# ─── Text them again ──────────────────────────────────────────────────

AGAIN_LIMIT = (f"The text was sent again {AGAIN_MOST} times this week, the most a week allows. "
               "The next note can go with its own text.")
UNSURE = "It isn't clear whether the text reached them, so it can't be sent again this week."
STUCK = timedelta(minutes=10)        # a try still "sending" after this never finished saving


def _int(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _ids(v: Any) -> Optional[List[str]]:
    """Who a text missed, as a send kept it: contact ids, at most IDS_MOST.
    None for anything else, so who to text is never a guess."""
    if not isinstance(v, list) or len(v) > IDS_MOST:
        return None
    out = set()
    for x in v:
        try:
            out.add(str(uuid.UUID(str(x))))
        except (ValueError, TypeError, AttributeError):
            return None
    return sorted(out)


def _short(v: Any) -> str:
    """The words a send kept: a text_version, so at most TEXT_SHORT letters."""
    return v if isinstance(v, str) and v.strip() and len(v) <= TEXT_SHORT else ""


def again_of(rec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What Text them again can do with a week's record (read strictly; a
    shape no send writes offers nothing): `mode` "again" (the same words to
    the leaders a failed text missed, `ids`), "first" (the week's text hasn't
    gone: the email went alone, or the text stopped before any went) or
    None; `short`, the words; `tries` so far; `why` it can't, when it can't."""
    out: Dict[str, Any] = {"mode": None, "ids": [], "short": "", "tries": 0, "why": ""}
    if not rec or rec.get("state") != "sent":
        return out
    t = rec.get("texts")
    if t is None:
        short = text_version(rec.get("subject"), rec.get("text"))
        return {**out, "mode": "first", "short": short} if short else out
    if not isinstance(t, dict):
        return out
    tries = t.get("tries", 0)
    if isinstance(tries, bool) or not isinstance(tries, int) or not 0 <= tries <= AGAIN_MOST:
        return out
    out["tries"] = tries
    short = _short(t.get("short"))
    if t.get("state") == "sending":
        # A try that never finished saving (a save that failed, a replica
        # gone mid-send) can't say who it reached: after STUCK it says so,
        # and it never goes again.
        at = _at(t.get("at"))
        if not at or _now() - at > STUCK:
            return {**out, "mode": "again", "why": UNSURE}
        return {**out, "mode": "again", "why": "The text is going out now. Open the page again in a moment."}
    if t.get("error"):
        if t.get("none_went") is True and not t.get("unsure") and short:
            return {**out, "mode": "first", "short": short}
        return out
    if not _int(t.get("failed")):
        return out
    ids = _ids(t.get("failed_ids"))
    if t.get("unsure"):
        return {**out, "mode": "again", "why": UNSURE}
    if not ids or not short:
        # A send from before who it missed was kept: it can't be told.
        return {**out, "mode": "again", "why": "This week's text went before the app kept who it missed, "
                                               "so it can't be sent again."}
    return {**out, "mode": "again", "ids": ids, "short": short}


def text_failed_of(rec: Optional[Dict[str, Any]]) -> int:
    """How many leaders the week's text didn't reach because it failed."""
    t = (rec or {}).get("texts")
    return _int(t.get("failed")) if isinstance(t, dict) and not t.get("error") else 0


def again_view(biz: Dict[str, Any], rec: Optional[Dict[str, Any]], reach: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """For "The text didn't reach 2 leaders. Text them again": how many it
    goes to, the text exactly as it goes (the church's name first, the way
    out last, as sms_routing.text_people makes it), tries left, and whether
    it can go now (`why` not: quiet hours, the week's limit). None when
    there's nothing to offer; "first" only when some leader gets texts
    (`reach`, text_reach)."""
    a = again_of(rec)
    if not a["mode"]:
        return None
    if a["mode"] == "first":
        n = _int((reach or {}).get("reach"))
        if not n:
            return None
    else:
        n = len(a["ids"]) or text_failed_of(rec)
    why = a["why"] or (AGAIN_LIMIT if a["tries"] >= AGAIN_MOST else "")
    if not why and quiet_now(biz):
        why = quiet_words(biz, again=True)
    from sms_service import compose_outbound_body
    body = compose_outbound_body(biz.get("name") or "the business", a["short"], include_optout=True) if a["short"] else ""
    return {"mode": a["mode"], "leaders": n, "body": body, "tries_left": max(0, AGAIN_MOST - a["tries"]),
            "allowed": not why, "why": why}


def sender_name(biz: Dict[str, Any], user: AuthedUser) -> str:
    """Who sent it, by their own name: the owner's from the church's
    settings, anyone else's as one of the church's people by their sign-in
    email, else the part of the email before the @."""
    if str(biz.get("owner_id")) == str(user.id):
        name = _plain(_settings(biz).get("practitioner_name"))
        if name:
            return name
    email = (user.email or "").strip().lower()
    if "@" in email:
        import church_areas
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(biz['id'])}&email=ilike.{_q(church_areas._escape_ilike(email))}&select=name&limit=5")
        name = next((_plain(r.get("name")) for r in rows or [] if _plain(r.get("name"))), "")
        if name:
            return name
        return email.split("@")[0]
    return "The office"


# ─── The draft ────────────────────────────────────────────────────────

def compose(parts: Dict[str, str]) -> str:
    """The note as one text: each part under its heading, an empty part
    left out (the app joins it the same way, lib/leadersNoteCore)."""
    keys = ("week", "needed", "win")
    return "\n\n".join(f"{h}\n{(parts.get(k) or '').strip()}" for h, k in zip(HEADINGS, keys)
                       if (parts.get(k) or "").strip())


def draft(me: Dict[str, Any]) -> Dict[str, Any]:
    biz = me["biz"]
    biz_id = str(biz["id"])
    tz = _zone(biz)
    today = _now().astimezone(tz).date()
    last_day = today + timedelta(days=DAYS - 1)
    lo = datetime.combine(today, time(0), tzinfo=tz)
    hi = datetime.combine(last_day + timedelta(days=1), time(0), tzinfo=tz)
    plans = _plans(biz_id, lo, hi, tz)
    occasions = _occasions(biz_id, today, last_day, tz)
    rooms = _rooms(biz_id, lo, hi, tz)
    groups = _groups(biz_id, today, last_day)
    items = calendar(plans, occasions, rooms)
    sunday = _sunday_places(biz_id, plans)
    no_one = _no_one(biz_id)
    people = recipients(biz_id)
    try:
        texts = text_reach(biz, people)
    except Exception:
        logger.warning("leaders note: the text's reach wasn't read", exc_info=True)
        texts = None
    church = _plain(biz.get("name")) or "Your church"
    monday = monday_of(today)
    parts = {"week": week_text(items, groups), "needed": needed_text(sunday, occasions, no_one), "win": ""}
    subject = f"Leaders, the week of {monday:%B} {monday.day}"
    rec = last_of(biz)
    last = last_view(rec, tz)
    sent_this_week = bool(last and last["week"] == monday.isoformat())
    nxt = monday + timedelta(days=7)
    return {
        "church": church,
        "week": {"monday": monday.isoformat(), "words": f"the week of {monday:%B} {monday.day}"},
        "days": {"from": today.isoformat(), "to": last_day.isoformat(),
                 "words": f"{day_words(today)} to {day_words(last_day)}"},
        "headings": {"week": HEADINGS[0], "needed": HEADINGS[1], "win": HEADINGS[2]},
        "draft": {"subject": subject, **parts},
        "text": compose(parts),
        "recipients": {"leaders": people["leaders"], "reach": len(people["to"]), "no_email": people["no_email"]},
        "texts": texts,
        "counts": {"calendar": len(items), "groups": len(groups),
                   "open_places": sum(s["open"] for s in sunday),
                   "roles": sum(1 for o in occasions if o.get("short")), "no_one": no_one},
        "last": last,
        "sent_this_week": sent_this_week,
        # Text them again: this week's only.
        "text_failed": text_failed_of(rec) if sent_this_week else 0,
        "text_again": again_view(biz, rec, texts) if sent_this_week else None,
        "next_send": {"day": nxt.isoformat(), "words": day_words(nxt)},
    }


# ─── Sending ──────────────────────────────────────────────────────────

def note_html(text: str, primary: str) -> str:
    """The note's body for the email: each heading set apart as a small
    rule-marked label, a day's first line in bold, the rest as written."""
    import email_layout
    e = _html.escape
    heads = {h.replace("’", "'").lower() for h in HEADINGS}
    p = '<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#1f2937;">'
    out = []
    for block in re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip()):
        lines = [ln.rstrip() for ln in block.split("\n")]
        if lines and lines[0].strip().replace("’", "'").lower() in heads:
            out.append(f'<p style="margin:{"8" if not out else "28"}px 0 10px;padding-left:10px;border-left:3px solid {e(primary)};'
                       'font-size:12px;line-height:1.4;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#111827;">'
                       f"{e(lines[0].strip())}</p>")
            lines = lines[1:]
        if not any(ln.strip() for ln in lines):
            continue
        said = [email_layout._linkify(e(ln)) for ln in lines]
        if DAY_RE.match(lines[0].strip()):
            said[0] = f"<b>{said[0]}</b>"
        out.append(p + "<br />".join(said) + "</p>")
    return "".join(out)


def deliver(biz: Dict[str, Any], to_email: str, to_name: str, subject: str, html: str, key: str,
            reply_to: Optional[str] = None) -> None:
    """One email through the app's own path (Resend, the church's identity
    where it has one). Raises when it doesn't go. A leader's reply goes to
    whoever sent the note (the Church Administrator), not a no-reply box:
    "What's needed" asks for answers."""
    import email_sender
    church = _plain(biz.get("name")) or "Your church"
    asyncio.run(email_sender.send_via_resend(
        to_email=to_email, to_name=to_name or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=church, subject=subject[:SUBJECT_MAX], body=html, reply_to=reply_to,
        business_id=str(biz["id"]), idempotency_key=key))


def render(biz: Dict[str, Any], subject: str, text: str) -> str:
    import email_layout
    church = _plain(biz.get("name")) or "Your church"
    brand = email_layout.brand_of(_settings(biz))
    first = next((ln.strip() for ln in text.split("\n") if ln.strip() and ln.strip() not in HEADINGS), subject)
    return email_layout.render_html(
        "", business_name=church, brand=brand, sig=None, preheader=first[:90],
        after_cta=note_html(text, brand.get("primary") or email_layout.DEFAULT_ACCENT),
        disclaimer=f"You’re getting this because you lead at {church}.",
        footer_note="Sent by your church office")


def send(me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """Send this week's note to the leaders, once a week. The week is
    claimed first (so a second press, or a second person, is refused), then
    each leader gets their own email; if none went, the claim is let go.
    With also_text, the leaders whose numbers said yes get the short text
    after the emails go (text_leaders); the card and the church's quiet
    hours are checked before anything is taken or sent."""
    also_text = body.get("also_text") is True
    subject = _plain(body.get("subject"))[:SUBJECT_MAX]
    text = str(body.get("text") or "").replace("\r\n", "\n").strip()
    if not subject:
        raise HTTPException(400, "Give the note a subject.")
    if not text:
        raise HTTPException(400, "The note is empty. Write a line or two first.")
    if len(text) > TEXT_MAX:
        raise HTTPException(400, f"The note is long for an email: keep it under {TEXT_MAX:,} letters.")
    biz = me["biz"]
    biz_id = str(biz["id"])
    short = text_version(subject, text) if also_text else ""
    if also_text:
        import billing_limits
        billing_limits.require_card(biz_id, "texts")
        if quiet_now(biz):
            raise HTTPException(409, quiet_words(biz))
    import rate_limit
    if not rate_limit.allow("church_leaders_note_send", biz_id):
        raise HTTPException(429, "The note was tried several times this hour. Try again later.")
    tz = _zone(biz)
    monday = monday_of(_now().astimezone(tz).date())
    fresh = _business(biz_id)
    last = last_of(fresh)
    if last and last.get("week") == monday.isoformat():
        seen = last_view(last, tz) or {}
        raise HTTPException(409, f"This week's note already went out ({seen.get('sent_words') or 'this week'}"
                                 f"{', by ' + seen['by_name'] if seen.get('by_name') else ''}). "
                                 f"The next one can go {day_words(monday + timedelta(days=7))}.")
    people = recipients(biz_id)
    if not people["to"]:
        raise HTTPException(409, "None of the leaders has an email yet, so there's no one to send it to.")
    claim = {"id": uuid.uuid4().hex, "week": monday.isoformat(), "state": "sending", "sent_at": _iso(_now()),
             "by": me["uid"], "by_name": sender_name(fresh, me["user"]), "sent": 0,
             "no_email": people["no_email"][:200], "failed": [], "subject": subject, "text": text}
    if also_text:
        claim["texts"] = {"sent": 0, "texts": 0, "skipped": 0, "failed": 0, "body": short, "short": short, "failed_ids": []}
    if not swap(biz_id, (last or {}).get("id"), claim):
        raise HTTPException(409, "Someone else is sending this week's note right now. Open the page again in a moment.")
    html = render(fresh, subject, text)
    reply = str(me["user"].email or "").strip()
    reply_to = reply if "@" in reply and " " not in reply else None
    sent: List[str] = []
    failed: List[str] = []
    for p in people["to"]:
        try:
            deliver(fresh, p["email"], p["name"], subject, html, f"leaders-note-{biz_id}-{claim['id'][:12]}-{p['contact_id']}",
                    reply_to=reply_to)
            sent.append(p["name"])
        except Exception:
            logger.warning("leaders note: an email failed", exc_info=True)
            failed.append(p["name"])
    if not sent:
        # Nothing went: the week is free again.
        swap(biz_id, claim["id"], last)
        raise HTTPException(503, "The note didn't reach anyone just now, so nothing was sent. Try again in a moment.")
    texts = text_leaders(biz_id, people, short) if also_text else None
    done = {**claim, "state": "sent", "sent": len(sent), "failed": failed[:200]}
    if texts is not None:
        done["texts"] = texts
    recorded = swap(biz_id, claim["id"], done)
    return {"sent": len(sent), "failed": failed, "no_email": people["no_email"], "recorded": recorded,
            "texts": _texts_view(texts), "last": last_view(done, tz), "sent_this_week": True,
            # Text them again, when a text failed (or couldn't go at all). Not
            # "first" after an email alone: that's offered when the page opens.
            "text_failed": text_failed_of(done), "text_again": again_view(fresh, done, None),
            "next_send": {"day": (monday + timedelta(days=7)).isoformat(), "words": day_words(monday + timedelta(days=7))}}


def text_again(me: Dict[str, Any]) -> Dict[str, Any]:
    """Text this week's note again to the leaders a failed text missed: the
    same words, to those leaders only, yes and STOP checked again as it goes
    (a leader who has said STOP, or never said yes, is never texted). When
    the week's text hasn't gone (the email went alone, or the text stopped
    before any went), it goes now to every leader who said yes. The record is
    read fresh (a failed read is a 503, never a send); the card, quiet hours
    and AGAIN_MOST are checked; then the record is taken under a new id, so
    two presses text once. Nothing went: the try is given back."""
    biz = me["biz"]
    biz_id = str(biz["id"])
    tz = _zone(biz)
    monday = monday_of(_now().astimezone(tz).date())
    fresh = _business(biz_id)
    last = last_of(fresh)
    if not last or last.get("week") != monday.isoformat():
        raise HTTPException(409, "This week's note hasn't gone yet. The text goes with the note: send it from this page.")
    if last.get("state") != "sent":
        raise HTTPException(409, "This week's note is still going out. Open the page again in a moment.")
    a = again_of(last)
    if not a["mode"]:
        raise HTTPException(409, "There's nothing to text again this week: the text reached every leader it could.")
    if a["why"]:
        raise HTTPException(409, a["why"])
    if a["tries"] >= AGAIN_MOST:
        raise HTTPException(409, AGAIN_LIMIT)
    import billing_limits
    billing_limits.require_card(biz_id, "texts")
    if quiet_now(fresh):
        raise HTTPException(409, quiet_words(fresh, again=True))
    import rate_limit
    if not rate_limit.allow("church_leaders_note_text_again", biz_id):
        raise HTTPException(429, "The text was tried several times this hour. Try again later.")
    again = a["mode"] == "again"
    people = recipients(biz_id)
    to = [p for p in people["phones"] if p["id"] in set(a["ids"])] if again else list(people["phones"])
    if not to:
        raise HTTPException(409, "None of the leaders it missed is in the leaders room with a number now, so there's no one to text."
                            if again else "None of the leaders has a number on their record, so there's no one to text.")
    old = last["texts"] if again else {"sent": 0, "texts": 0, "skipped": 0, "failed": 0, "body": ""}
    tries = a["tries"] + 1
    claim = {**last, "id": uuid.uuid4().hex,
             "texts": {**old, "short": a["short"], "state": "sending", "at": _iso(_now()), "tries": tries}}
    claim["texts"].pop("unsure", None)
    if not swap(biz_id, last["id"], claim):
        raise HTTPException(409, "Someone else is texting the leaders right now. Open the page again in a moment.")
    out = _text(biz_id, to, a["short"])
    if out.get("error") and not out.get("unsure"):
        # Nothing went: the try is given back (asked twice; the swap only
        # lands on our own claim). If it still won't save, the claim reads
        # as unsure after STUCK and never texts twice; say so now.
        if not (swap(biz_id, claim["id"], last) or swap(biz_id, claim["id"], last)):
            print(f"[leaders_note] {biz_id[:8]}: text-again sent nothing and its try couldn't be given back")
            raise HTTPException(503, f"{out['error']} The page couldn't be put back either, "
                                     "so the text may not be offered again this week.")
        raise HTTPException(503, out["error"])
    if out.get("error"):
        # It broke partway: who got it can't be told, so it never goes again.
        reached, still = [], []
        texts = {**old, "short": a["short"], "tries": tries, "unsure": True, "failed_ids": []}
        if not again:
            texts["error"] = out["error"]
    else:
        reached, still = out["went"], out["missed"]
        if again:
            total = _int(old.get("sent")) + _int(old.get("skipped")) + _int(old.get("failed"))
            sent = _int(old.get("sent")) + len(reached)
            texts = {**old, "sent": sent, "texts": _int(old.get("texts")) + _int(out.get("sent")),
                     "skipped": max(0, total - sent - len(still)), "failed": len(still)}
        else:
            texts = {"sent": len(reached), "texts": _int(out.get("sent")),
                     "skipped": max(0, people["leaders"] - len(reached) - len(still)), "failed": len(still)}
        texts.update({"body": str(out.get("body") or old.get("body") or ""), "short": a["short"],
                      "failed_ids": still[:IDS_MOST], "tries": tries})
    for k in ("state", "at", "none_went"):
        texts.pop(k, None)
    kept = old.get("again") if again else None
    earlier = [x for x in kept if isinstance(x, dict)] if isinstance(kept, list) else []
    texts["again"] = (earlier + [{"at": _iso(_now()), "by_name": sender_name(fresh, me["user"]),
                                  "sent": len(reached), "failed": len(still)}])[-AGAIN_MOST:]
    done = {**claim, "texts": texts}
    recorded = swap(biz_id, claim["id"], done) or swap(biz_id, claim["id"], done)
    warning = ""
    if not recorded:
        # The texts went but who they reached isn't saved: the claim stays
        # "sending", reads as unsure after STUCK, and is never pressed again.
        print(f"[leaders_note] {biz_id[:8]}: text-again went (reached={len(reached)}) but its record didn't save")
        warning = "The text went, but who it reached couldn't be saved, so it can't be sent again this week."
    return {"reached": len(reached), "failed": len(still), "recorded": recorded, "unsure": bool(out.get("error")),
            "warning": warning, "texts": _texts_view(texts), "last": last_view(done, tz),
            "text_failed": text_failed_of(done), "text_again": again_view(fresh, done, None) if recorded else None}


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/status")
def leaders_note_status(business_id: str, user: AuthedUser = Depends(require_user)):
    """Whether this login's Office shows the leaders note: the app asks
    once, so its menu offers the page only where it opens. Quietly false
    for a closed switch, a business that isn't a church, a login below a
    manager, or a manager who doesn't work the office."""
    if not open_to(user):
        return {"enabled": False}
    try:
        _access(business_id, user)
    except HTTPException as e:
        if e.status_code in (403, 404, 503):
            return {"enabled": False}
        raise
    return {"enabled": True}


@router.get("")
def leaders_note_draft(business_id: str, user: AuthedUser = Depends(require_user)):
    return draft(_access(business_id, user))


@router.post("/send")
def leaders_note_send(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    return send(_access(body.get("business_id"), user), body)


@router.post("/text-again")
def leaders_note_text_again(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    return text_again(_access(body.get("business_id"), user))
