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
of the church's people. The note says who has no email. It goes by email
only, through the path the Board's "Send minutes" uses (email_layout +
email_sender.send_via_resend, the church's identity, a key per send). The
leaders' chat can't carry it: a chat message needs a member sender.

Who sends it: the owner, admins and Manager seats, at churches, and (while
Who sees what is on) only a login whose areas include the Office, the same
rule as Rooms & spaces. Once a week: one send per church per Monday-start
week on the church's clock. The last send (when, who, how many, the words)
is kept in businesses.settings.church_leaders_note, merged into the live
settings and swapped only when nobody else changed it in between, so two
people pressing Send at once send once. No table, no migration.

  GET  /church/leaders-note/status?business_id=   {enabled}
  GET  /church/leaders-note?business_id=          the draft, who it goes to, the last send
  POST /church/leaders-note/send                  {business_id, subject, text}

Switched by CHURCH_LEADERS_NOTE: off | owner | on (owner until a Thursday).
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church/leaders-note", tags=["church"])

KEY = "church_leaders_note"          # businesses.settings[KEY]: the last send
DAYS = 7                             # "this week": today and the six days after
SUBJECT_MAX, TEXT_MAX = 150, 8000
GROUPS_NAMED = 8                     # the groups line names this many, then "and N more"
SAME_GATHERING = timedelta(hours=2)  # a plan and its occasion, as the calendar says
HEADINGS = ("This week", "What’s needed", "One win")
KEEPS_ALL = ("owner", "admin")
NOT_CHURCH = "The leaders note is for churches"
DAY_RE = re.compile(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), [A-Z][a-z]+ \d{1,2}$")


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_LEADERS_NOTE") or "owner").strip().lower()
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


def _office(biz_id: str, uid: str, role: str) -> bool:
    """Whether this login works the office (church_spaces' rule): the owner
    and admins always; any login while Who sees what is off; else a login
    whose areas are the whole church or include the Office. A view that
    couldn't be read is a 503, never a yes."""
    if role in KEEPS_ALL:
        return True
    import church_areas
    if church_areas.mode() != "on":
        return True
    view = church_areas.my_areas(biz_id, uid, role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    return view.get("areas") is None or "office" in (view.get("areas") or [])


def _access(business_id: Any, user: AuthedUser) -> Dict[str, Any]:
    """The church, and the login sending its note: the owner, an admin or a
    manager. 404 when the switch is closed to them, they have no such seat
    here, or it isn't a church; 403 for a manager who doesn't work the
    office."""
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    biz_id = _uuid(business_id, "church")
    role = business_access.assert_access(biz_id, user, "manager")
    biz = _business(biz_id)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    if not _office(biz_id, str(user.id), role):
        raise HTTPException(403, "The leaders note belongs to the office. An admin can add the Office to your areas.")
    return {"biz": biz, "role": role, "uid": str(user.id), "user": user}


# ─── This week: the calendar ──────────────────────────────────────────

def _item(day: date, at: Optional[datetime], title: str, where: str = "", kind: str = "event") -> Dict[str, Any]:
    return {"day": day, "at": at, "title": _plain(title) or "Untitled", "where": _plain(where), "kind": kind}


def _plans(biz_id: str, lo: datetime, hi: datetime, tz) -> List[Dict[str, Any]]:
    """The Sunday plans in the days (worship_services: ChurchSavvy's and
    Sunday Planning's one table)."""
    rows = _need(f"/worship_services?business_id=eq.{_q(biz_id)}&archived_at=is.null&is_template=eq.false"
                 f"&starts_at=gte.{_q(_iso(lo))}&starts_at=lt.{_q(_iso(hi))}"
                 "&select=id,title,starts_at&order=starts_at.asc&limit=100")
    out = []
    for r in rows:
        d = _at(r.get("starts_at"))
        if not d:
            continue
        local = d.astimezone(tz)
        out.append({**_item(local.date(), local, r.get("title") or "Sunday service", kind="service"),
                    "id": str(r["id"])})
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
            for slot in range(1, int(place.get("needed") or 1) + 1):
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
    it) and who doesn't."""
    import member_portal_messaging as mpm
    room = mpm.leaders_room_people(biz_id)
    if room is None:
        raise HTTPException(503, "The leaders couldn't be read just now. Try again.")
    ids = [str(p.get("contact_id")) for p in room if p.get("contact_id")]
    people: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunks(ids):
        for c in _need(f"/contacts?business_id=eq.{_q(biz_id)}&id=in.({','.join(chunk)})&select=id,name,email&limit=200"):
            people[str(c["id"])] = c
    to: List[Dict[str, str]] = []
    no_email: List[str] = []
    seen = set()
    for cid in sorted(people, key=lambda i: (_plain(people[i].get("name")) or "~").lower()):
        c = people[cid]
        name = _plain(c.get("name")) or "Someone"
        email = str(c.get("email") or "").strip()
        if "@" not in email or " " in email:
            no_email.append(name)
            continue
        if email.lower() in seen:
            continue
        seen.add(email.lower())
        to.append({"contact_id": cid, "name": name, "email": email})
    return {"to": to, "no_email": no_email, "leaders": len(people)}


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
            "sending": rec.get("state") == "sending"}


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
    church = _plain(biz.get("name")) or "Your church"
    monday = monday_of(today)
    parts = {"week": week_text(items, groups), "needed": needed_text(sunday, occasions, no_one), "win": ""}
    subject = f"Leaders, the week of {monday:%B} {monday.day}"
    last = last_view(last_of(biz), tz)
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
        "counts": {"calendar": len(items), "groups": len(groups),
                   "open_places": sum(s["open"] for s in sunday),
                   "roles": sum(1 for o in occasions if o.get("short")), "no_one": no_one},
        "last": last,
        "sent_this_week": sent_this_week,
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
    each leader gets their own email; if none went, the claim is let go."""
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
    done = {**claim, "state": "sent", "sent": len(sent), "failed": failed[:200]}
    recorded = swap(biz_id, claim["id"], done)
    return {"sent": len(sent), "failed": failed, "no_email": people["no_email"], "recorded": recorded,
            "last": last_view(done, tz), "sent_this_week": True,
            "next_send": {"day": (monday + timedelta(days=7)).isoformat(), "words": day_words(monday + timedelta(days=7))}}


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
