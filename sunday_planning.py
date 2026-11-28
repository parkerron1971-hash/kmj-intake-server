# sunday_planning.py — ChurchSavvy Planning: a church's Sunday teams and who
# serves when (design canvas Ct88v7pxpq5a4PGYX3MuQQ, boards 4 and 5; Kevin
# 2026-10-23: "This is a good build. i agree with your plan").
#
#   GET    /planning/status?business_id=            on for this person, and may they schedule?
#   GET    /planning/teams?business_id=             the Sunday teams, their places, who's trained
#   POST   /planning/teams                          make a serving team a Sunday team (or a new one)
#   PATCH  /planning/teams/{group_id}               its turns: arrive by, Sundays a month, swaps, families
#   DELETE /planning/teams/{group_id}               stop scheduling it (only while nobody was asked)
#   POST   /planning/positions                      a new place on a team
#   PATCH  /planning/positions/{id}                 rename it, how many people, a note
#   DELETE /planning/positions/{id}                 retire it; who served there stays
#   PUT    /planning/positions/{id}/people          who's trained on it, or learning
#   GET    /planning/people?business_id=&q=         find a member to add (names only)
#   POST   /planning/people                         someone new, by name and email (ChurchSavvy alone)
#   PUT    /planning/email                          ChurchSavvy's "Email asks and reminders", an admin's switch
#   GET    /planning/schedule?business_id=&start=&weeks=  the coming services, each place, who
#   POST   /planning/sundays                        add the coming Sundays to plan
#   GET    /planning/events?business_id=            upcoming Services & Events entries that could be an event date
#   POST   /planning/dates                          an event date that isn't a Sunday, for the volunteer teams
#   DELETE /planning/dates/{service_id}             take an event date off (only while nobody was asked)
#   PUT    /planning/dates/{service_id}/needs       an event date's own numbers for the Volunteers' places
#   GET    /planning/requests?business_id=          events' asks for the serving teams, waiting and lately answered
#   POST   /planning/requests/{id}/answer           yes (the event date is made) or no, with a note back
#   GET    /planning/candidates?business_id=&service_id=&position_id=
#                                                   who could take a place, the most rested first
#   POST   /planning/ask                            ask someone; it goes out on the next sweep
#   POST   /planning/offer                          offer a place to everyone on the team
#   POST   /planning/assignments/{id}/answer        their answer, when they told you in person
#   DELETE /planning/assignments/{id}               take it back; the place is open again
#   POST   /planning/fill                           ask people fairly for every open place
#   POST   /planning/unfill                         take back asks that haven't gone out yet
#
# A Sunday team is a church group of kind 'team' (groups.py): its people,
# leaders and thread are the group's own, and serve_teams holds only its
# turns. A volunteer is a contact (they answer in the member app), never a
# business_users seat. Who may schedule comes from worship_team: the owner,
# an admin or a manager, and a ChurchSavvy admin, planner or scheduler
# ("serve"). In a church a manager schedules only when its duties give it
# one of those parts (sunday_plan, production_schedule, serve_schedule or
# churchsavvy_team; worship_team.PARTS_FROM_DUTIES).
# Every other part, and a viewer seat, reads only.
#
# In a church, each Sunday team belongs to ChurchSavvy or to Volunteers
# (serve_teams.owner; "whose team it is" below), and each person changes
# only their own teams. GET /teams and /schedule take owner=churchsavvy or
# owner=volunteers for one door's teams; without it, the whole Sunday.
#
# Event dates (serve_dates.py; Kevin 2026-11-17: "build that"): a dated
# occasion that isn't a Sunday (an outreach night, a Saturday event, a
# Wednesday Bible study) is a service of kind 'event'. Whoever changes the
# Volunteers' teams (serve_schedule, the owner, an Admin) adds one, from an
# upcoming Services & Events entry or typed, and only the Volunteers' teams
# serve it: ChurchSavvy's teams are never asked, filled or shown a place on
# it, and ChurchSavvy's door doesn't list it. It doesn't count toward a
# team's Sundays a month. CHURCH_EVENT_VOLUNTEERS decides who may add one.
#
# An event's volunteers (event_volunteers.py, docs/EVENT_VOLUNTEERS.md; Kevin
# 2026-11-20, "go"): an event in Services & Events asks the serving teams for
# its own number of each Volunteers place, and whoever changes the
# Volunteers' teams says yes with one tap. The yes makes the event date with
# those numbers (worship_services.needs) through make_date, the one way an
# event date is made, here and from an ask. Every slot loop counts a place
# with serve_dates.needed(service, place): an event date with numbers needs
# exactly those (0 for a place it doesn't name), anything else the place's
# Sunday number. EVENT_VOLUNTEERS also lets an event date fall on a Sunday
# afternoon (never within two hours of a Sunday service) and makes a typed
# date a Services & Events entry too.
from __future__ import annotations

import logging
import os
import re
import time as clock
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import serve_dates as sd
from auth_supabase import AuthedUser, require_user
from worship_team import REFUSED, can, parts_of, require, roles_of

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/planning", tags=["planning"])

MAX_TEAMS = 20
MAX_PLACES = 30
MAX_TRAINED = 100
MAX_WEEKS = 8
MAX_EVENT_DATES = 30        # event dates still to come at one church
EVENT_AHEAD_DAYS = 180      # an event date this far ahead at most
SUNDAY_HOURS = 2            # a Sunday event date starts at least this long from a Sunday service
SUNDAY_TIME = "10:30"       # Add the next five Sundays' time when none is given
USUAL_WEEKS = 8             # a church's usual Sunday times: its Sunday services this many weeks either side of today
SUNDAY_CLASH = "That's during Sunday's service. Sunday services are already on Who serves when."
TEEN_UNDER = 18
FILLED_BY = "Chief, filling the month"
# The places a new team can start with: shapes, never anyone's names.
STARTERS = {
    "worship": ["Worship leader", "Vocals", "Keys", "Guitar", "Bass", "Drums"],
    "production": ["Slides", "Sound", "Livestream", "Lights"],
    "welcome": ["Greeter", "Usher", "Parking", "Coffee"],
    "kids": ["Nursery", "Kids class", "Check-in"],
    "prayer": ["Prayer team"],
}
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ─── the switch ──────────────────────────────────────────────────────
# SUNDAY_PLANNING = off | owner | on (default owner): dark-launched to the
# platform owner, like ChurchSavvy's WORSHIP_SONGS, until Kevin turns it on.


def mode() -> str:
    m = (os.environ.get("SUNDAY_PLANNING") or "on").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", None) or "").strip().lower() == owner
    return False


def _gate(user: AuthedUser) -> None:
    if not open_to(user):
        raise HTTPException(404, "Not Found")


# ─── whose team it is ────────────────────────────────────────────────
# One schedule, two doors (Kevin, 2026-11-02: "churchsavvy is shapretta
# because that has to do with the service projection and order of service
# for production team and partnering with worship team. volunteers and roles
# laquesha is doing is her assignment", then "yes churchsavvy for worship
# team, announcements to shapretta. go"; supabase/APPLY-2026-11-02-serve-
# team-owner.sql). In a church each Sunday team has an owner:
#   churchsavvy   the worship and production teams: changed by a login that
#                 does production_schedule or churchsavvy_team (the Media &
#                 Communications lane), and by ChurchSavvy's own team (a
#                 planner or an admin it invited: the worship pastor)
#   volunteers    every other team (greeters, ushers, kids, parking,
#                 hospitality, outreach): changed by a login that does
#                 serve_schedule (the Sunday & Serving lane)
# The owner and every Admin login change any team; anyone else is refused
# with whose job it is (church_duties.refusal). Changing a team is its turns,
# its places, who's trained, an ask, an offer, an answer, taking an ask back
# and filling its Sundays. Reading is as before: everyone who opens Planning
# sees every team, so the whole Sunday shows and nobody is double-booked.
# A business that isn't a church, and a church on ChurchSavvy alone, are
# unchanged: whoever schedules changes every team.
CHURCHSAVVY, VOLUNTEERS = "churchsavvy", "volunteers"
OWNERS = (CHURCHSAVVY, VOLUNTEERS)
# A team nobody gave an owner, by its name: the migration's backfill too.
CHURCHSAVVY_WORDS = ("worship", "praise", "band", "choir", "music", "singers", "production", "sound", "audio",
                     "camera", "stream", "media", "tech", "booth", "lights", "slides", "projection")
# The duties (church_duties.CATALOG) that change each owner's teams, the
# first named in a refusal. A key the catalog doesn't have is held by
# nobody, and the next one is named.
OWNER_DUTIES: Dict[str, Tuple[str, ...]] = {
    CHURCHSAVVY: ("production_schedule", "churchsavvy_team"),
    VOLUNTEERS: ("serve_schedule",),
}


def owner_by_name(name: Any) -> str:
    """ChurchSavvy's when the team's name says worship or production, else
    Volunteers'."""
    low = str(name or "").lower()
    return CHURCHSAVVY if any(w in low for w in CHURCHSAVVY_WORDS) else VOLUNTEERS


# Before the migration serve_teams.owner isn't there, and asking for it
# makes PostgREST refuse the whole read: then every team reads as
# Volunteers' and a new team is saved without it. Only PostgREST's own "no
# such column" (42703) says so, and it's asked again a minute later, so the
# owners show soon after the migration runs.
NO_COLUMN_SECONDS = 60.0
_no_column: Dict[str, float] = {"at": 0.0}


def _column_missing() -> Optional[bool]:
    """True: serve_teams.owner doesn't exist (42703). False: it answers.
    None: couldn't tell (a blip), which is never read as missing."""
    import httpx
    try:
        resp = httpx.get(f"{sb_clients.sb_url()}/rest/v1/serve_teams?select=owner&limit=1",
                         headers=sb_clients.sb_headers_service(), timeout=10.0)
    except Exception:
        return None
    if resp.status_code < 300:
        return False
    if resp.status_code == 400 and "42703" in resp.text:
        return True
    return None


def _owner_missing() -> bool:
    at = _no_column["at"]
    return bool(at) and clock.monotonic() - at < NO_COLUMN_SECONDS


def _serve_rows(path: str, fields: str) -> List[Dict[str, Any]]:
    """serve_teams rows (`path` has no select) with each one's `owner`.
    Before the migration they're read without it, each Volunteers'. Any
    other failed read is a 503."""
    if not _owner_missing():
        rows = sb_clients.sb_get_as_service(f"{path}&select={fields},owner")
        if rows is not None:
            return [{**r, "owner": r.get("owner") if r.get("owner") in OWNERS else VOLUNTEERS} for r in rows]
        if _column_missing() is not True:
            raise HTTPException(503, "The schedule couldn't be read just now. Try again.")
        _no_column["at"] = clock.monotonic()
    return [{**r, "owner": VOLUNTEERS} for r in _read(f"{path}&select={fields}")]


def _office(biz: str) -> bool:
    """Whether this church's Sunday teams have owners: a church
    (church_follow_up.is_church), and not one on ChurchSavvy alone."""
    import church_follow_up
    import churchsavvy_billing
    rows = _read(f"/businesses?id=eq.{_q(biz)}&select=id,type,settings&limit=1")
    return bool(rows) and church_follow_up.is_church(rows[0]) and not churchsavvy_billing.standalone(rows[0])


def _owners_for(biz: str, user: AuthedUser) -> Tuple[FrozenSet[str], Optional[str]]:
    """(whose teams this person changes in a church, their office role).
    The owner and an Admin login: every team. Otherwise the owners whose
    duties they hold (OWNER_DUTIES), and ChurchSavvy's teams for ChurchSavvy's
    own team when its parts schedule. A duties read that fails is a 503."""
    import church_duties
    standing = church_duties.standing(biz, str(user.id))
    role = standing.get("role")
    if role in ("owner", "admin"):
        return frozenset(OWNERS), role
    held = standing.get("duties") or frozenset()
    mine = {owner for owner, duties in OWNER_DUTIES.items() if any(d in held for d in duties)}
    if can(parts_of(biz, user.id), "serve"):
        mine.add(CHURCHSAVVY)
    # Ministry operations (the one Sunday hub, M-7): the Volunteers' teams, as
    # serve_schedule; ChurchSavvy's only team by team, once opened (_team_gate).
    if "ministry_ops" in held and _hub_on(user):
        mine.add(VOLUNTEERS)
    return frozenset(mine), role


def _scheduler(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """Who is changing the schedule, before any team is read: {roles,
    office, owners, role}. Outside a church's teams with owners: whoever
    schedules (CAN["serve"]) changes every team, as before. In one: whoever
    may change some team (_owners_for). A Manager who may change none hears
    whose job it is from the team it tried (_team_gate); anyone else with
    none (a viewer seat, a booth volunteer) hears the part's refusal now."""
    roles = roles_of(biz, user, part="planning")
    if not _office(biz):
        if not can(roles, "serve"):
            raise HTTPException(403, REFUSED["serve"])
        return {"roles": roles, "office": False, "owners": frozenset(OWNERS), "role": None, "leads": frozenset(),
                "ops": False, "cid": None}
    owners, role = _owners_for(biz, user)
    who = _with_hub(biz, user, {"roles": roles, "office": True, "owners": owners, "role": role})
    if not owners and role != "manager" and not who["leads"] and not who["ops"]:
        raise HTTPException(403, REFUSED["serve"])
    return who


def _refusal(biz: str, owner: str) -> str:
    """Whose job this owner's teams are, in church_duties' words."""
    import church_duties
    duty = next((d for d in OWNER_DUTIES[owner] if d in church_duties.CATALOG), None)
    return church_duties.refusal(biz, duty) if duty else REFUSED["serve"]


def _team_gate(biz: str, who: Dict[str, Any], owner: str, gid: Optional[str] = None, schedule: bool = False) -> None:
    """403 unless `who` (_scheduler) changes this owner's teams. With the
    one Sunday hub on, scheduling one team (`schedule`, `gid`: an ask, an
    offer, taking an ask back, a fill) is also open to that team's own leader,
    and a ChurchSavvy team to ministry operations once it's opened to them."""
    if not who["office"] or owner in who["owners"]:
        return
    if schedule and gid:
        if gid in who.get("leads", ()):
            return
        if who.get("ops") and owner == CHURCHSAVVY:
            if gid in _opened(biz):
                return
            raise HTTPException(403, f"{_team_name(biz, gid)}'s leader hasn't opened its spots to ministry operations.")
    raise HTTPException(403, _refusal(biz, owner))


def _place_gate(biz: str, who: Dict[str, Any], group_id: Any, schedule: bool = False) -> None:
    """_team_gate for the team a place is on."""
    if who["office"]:
        _team_gate(biz, who, _team_row(biz, str(group_id))["owner"], str(group_id), schedule)


# ─── the one Sunday hub (sunday_hub.py, M-7) ─────────────────────────
# With SUNDAY_HUB on, a team's own leader schedules their team from the
# office too (as from the member app's Lead tab, sunday_leading), and
# ministry operations (the ministry_ops duty) the Volunteers' teams, and
# ChurchSavvy's one by one once their leader or the pastor opens them
# (serve_teams.open_to_ops); that team's leaders are told what they did.
# Off, none of this is asked.


def _hub_on(user: AuthedUser) -> bool:
    import sunday_hub
    return sunday_hub.open_to(user)


def _with_hub(biz: str, user: AuthedUser, who: Dict[str, Any]) -> Dict[str, Any]:
    """`who` with the teams this login leads, whether it holds ministry
    operations, and its person (sunday_hub.standing), with the hub on."""
    who.update(leads=frozenset(), ops=False, cid=None)
    if who["office"] and _hub_on(user):
        import sunday_hub
        st = sunday_hub.standing(biz, user)
        who.update(leads=frozenset(t["group_id"] for t in st["leads"]), ops="ministry_ops" in st["duties"],
                   cid=st["contact_id"])
    return who


def _opened(biz: str) -> Set[str]:
    import sunday_hub
    return sunday_hub.open_to_ops(biz)


def _team_name(biz: str, gid: str) -> str:
    rows = _read(f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&select=name&limit=1")
    return (rows[0].get("name") if rows else None) or "This team"


def _borrowed(who: Dict[str, Any], owner: str, gid: str) -> bool:
    """Ministry operations scheduling a ChurchSavvy team it doesn't change by
    its own duties: the team's leaders are told."""
    return bool(who["office"] and who.get("ops") and owner not in who["owners"] and gid not in who.get("leads", ()))


def _tell_team(biz: str, user: AuthedUser, who: Dict[str, Any], gid: str, what: str, ctx: Dict[str, Any]) -> None:
    """Tell a team's own leaders what ministry operations did on it
    (sunday_leading's note). Never able to fail the write it follows: a read
    that fails here only means no note."""
    try:
        import sunday_leading as sl
        church = _read(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,settings,owner_id&limit=1")
        if not church:
            return
        me = {"id": who.get("cid") or "", "name": _asker(biz, user)}
        sl._tell_its_leaders(church[0], me, {"group_id": gid, "name": _team_name(biz, gid)}, what, ctx)
    except Exception:  # noqa: BLE001 — a note is never worth failing the write it is about
        logger.warning("planning: a note to %s's leaders wasn't handed on (%s)", gid, what, exc_info=True)


def _borrowed_unsent(biz: str, who: Dict[str, Any], ids: List[str]) -> Dict[str, int]:
    """Of these asks, the ones not yet sent on ChurchSavvy teams ministry
    operations schedules only because they're opened to it: team -> how many."""
    if not (who["office"] and who.get("ops")) or CHURCHSAVVY in who["owners"] or not ids:
        return {}
    opened = _opened(biz) - set(who.get("leads") or ())
    if not opened:
        return {}
    out: Dict[str, int] = {}
    for i in range(0, len(ids), 100):
        rows = _read(f"/serve_assignments?business_id=eq.{_q(biz)}&id=in.({_ids(ids[i:i + 100])})&status=eq.asked"
                     "&notified_at=is.null&select=id,position_id")
        pids = sorted({str(r["position_id"]) for r in rows})
        places = {str(p["id"]): str(p["group_id"]) for p in (_read(
            f"/serve_positions?business_id=eq.{_q(biz)}&id=in.({_ids(pids)})&select=id,group_id") if pids else [])}
        for r in rows:
            gid = places.get(str(r["position_id"]))
            if gid in opened:
                out[gid] = out.get(gid, 0) + 1
    return out


def _hub_marks(biz: str, user: AuthedUser, teams: List[Dict[str, Any]]) -> None:
    """With the hub on, each team says whether it's open to ministry
    operations and whether this login leads it (in place)."""
    if not _hub_on(user) or not teams:
        return
    import sunday_hub
    opened = sunday_hub.open_to_ops(biz)
    try:
        leads = {t["group_id"] for t in sunday_hub.standing(biz, user)["leads"]}
    except HTTPException:
        leads = set()
    for t in teams:
        t["open_to_ops"] = t["group_id"] in opened
        t["mine"] = t["group_id"] in leads


def _new_owner(who: Dict[str, Any], given: Any, name: str) -> str:
    """A new team's owner: the one asked for; else, in a church, the one
    door its maker schedules for; else by its name."""
    if given is not None:
        if given not in OWNERS:
            raise HTTPException(400, "A Sunday team is ChurchSavvy's or Volunteers'")
        return given
    if who["office"] and len(who["owners"]) == 1:
        return next(iter(who["owners"]))
    return owner_by_name(name)


def _doors(biz: str, user: AuthedUser, roles: Set[str]) -> Dict[str, Any]:
    """For the pages: whether this church's teams have owners (two_doors),
    whose this person changes, and whose a team they make is by default
    (None: they choose, by its name unless they say). A read that fails
    shows nothing as theirs to change; every write still asks for itself."""
    try:
        office = _office(biz)
    except HTTPException:
        return {"two_doors": False, "change": [], "new_team_owner": None}
    if not office:
        return {"two_doors": False, "change": list(OWNERS) if can(roles, "serve") else [], "new_team_owner": None}
    try:
        mine, _role = _owners_for(biz, user)
    except HTTPException:
        mine = frozenset()
    return {"two_doors": True, "change": [o for o in OWNERS if o in mine],
            "new_team_owner": next(iter(mine)) if len(mine) == 1 else None}


def _may_add_dates(biz: str, user: AuthedUser, doors: Dict[str, Any]) -> bool:
    """For the pages: may this login add an event date here? A church whose
    teams have owners, a login that changes the Volunteers' teams, the
    switch open for this church and the columns there (serve_dates)."""
    if not doors.get("two_doors") or VOLUNTEERS not in (doors.get("change") or []):
        return False
    return sd.open_for(biz, user) and sd.ready()


def _which(owner: Optional[str]) -> Optional[str]:
    if owner in (None, ""):
        return None
    if owner not in OWNERS:
        raise HTTPException(400, "owner is churchsavvy or volunteers")
    return owner


# ─── helpers ─────────────────────────────────────────────────────────


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise HTTPException(503, "The schedule couldn't be read just now. Try again.")
    return rows


def _ids(values) -> str:
    return ",".join(_q(v) for v in sorted({str(v) for v in values if v}))


def _staff(biz: str, user: AuthedUser, write: bool, part: Optional[str] = "planning") -> Set[str]:
    """Every part of the team and every seat reads; scheduling is the
    owner's, an admin's, a manager's, or a ChurchSavvy admin's or planner's.
    Both are Planning's part of a ChurchSavvy plan (worship_team.roles_of)."""
    if write:
        return require(biz, user, "serve")
    return roles_of(biz, user, part=part)


def _church(biz: str) -> Dict[str, Any]:
    rows = _read(f"/businesses?id=eq.{_q(biz)}&select=id,settings,owner_id&limit=1")
    return rows[0] if rows else {"id": biz, "settings": {}}


def _zone(biz: str):
    import business_marketing
    return business_marketing.business_tz(_church(biz))


def _asker(biz: str, user: AuthedUser) -> str:
    """The name an ask goes out under: their name on the Sunday team, else
    the church's own name for its leader, else the office."""
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?business_id=eq.{_q(biz)}&user_id=eq.{_q(user.id)}&status=eq.active&select=name&limit=1") or []
    if rows and (rows[0].get("name") or "").strip():
        return rows[0]["name"].strip()[:80]
    name = ((_church(biz).get("settings") or {}).get("practitioner_name") or "").strip()
    return name[:80] or "The office"


def _people(biz: str, ids) -> Dict[str, Dict[str, Any]]:
    """id → {name, teen, has_email} for these members of this church: whether
    an email can reach them, never the address itself."""
    import academy_join
    out: Dict[str, Dict[str, Any]] = {}
    ids = sorted({str(i) for i in ids if i})
    today = _now().date()
    for i in range(0, len(ids), 150):
        rows = _read(f"/contacts?business_id=eq.{_q(biz)}&id=in.({_ids(ids[i:i + 150])})&select=id,name,birthdate,email")
        for r in rows:
            out[str(r["id"])] = {"name": (r.get("name") or "Someone").strip() or "Someone",
                                 "teen": _is_teen(r.get("birthdate"), today),
                                 "has_email": academy_join.valid_email(str(r.get("email") or "").strip())}
    return out


def _is_teen(born: Any, today: date) -> bool:
    try:
        b = date.fromisoformat(str(born)[:10])
    except (TypeError, ValueError):
        return False
    age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return age < TEEN_UNDER


def _hhmm(t: Any) -> Optional[str]:
    return str(t)[:5] if t else None


# ─── teams and places ────────────────────────────────────────────────


def _teams(biz: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(the Sunday teams with their places, people and who's trained, and
    whose each is; the church's other serving teams that could become one,
    each with whose it would be by its name)."""
    serve = _serve_rows(f"/serve_teams?business_id=eq.{_q(biz)}", "group_id,call_time,max_month,swap_needs_ok,families,sort")
    groups = _read(f"/groups?business_id=eq.{_q(biz)}&kind=eq.team&active=eq.true&select=id,name&order=name.asc")
    by_group = {str(s["group_id"]): s for s in serve}
    names = {str(g["id"]): g["name"] for g in groups}
    team_ids = [g for g in by_group if g in names]
    places: List[Dict[str, Any]] = []
    trained: List[Dict[str, Any]] = []
    members: List[Dict[str, Any]] = []
    if team_ids:
        places = _read(f"/serve_positions?business_id=eq.{_q(biz)}&group_id=in.({_ids(team_ids)})&active=eq.true"
                       f"&select=id,group_id,name,needed,note,sort&order=sort.asc,created_at.asc")
        members = _read(f"/group_members?business_id=eq.{_q(biz)}&group_id=in.({_ids(team_ids)})&select=group_id,contact_id,role")
    if places:
        trained = _read(f"/serve_trained?business_id=eq.{_q(biz)}&position_id=in.({_ids(p['id'] for p in places)})"
                        f"&select=position_id,contact_id,level")
    who = _people(biz, [m["contact_id"] for m in members] + [t["contact_id"] for t in trained])
    # How often each would like to serve (member_portal_serving): a wish, not a rule.
    often = {str(p["contact_id"]): p.get("often") for p in (_read(
        f"/serve_prefs?business_id=eq.{_q(biz)}&contact_id=in.({_ids(who)})&select=contact_id,often") if who else [])}
    out = []
    for gid in team_ids:
        s = by_group[gid]
        mine = [m for m in members if str(m["group_id"]) == gid and str(m["contact_id"]) in who]
        people = sorted(({"contact_id": str(m["contact_id"]), **who[str(m["contact_id"])], "leader": m.get("role") == "leader",
                          "often": often.get(str(m["contact_id"]))}
                         for m in mine), key=lambda p: (not p["leader"], p["name"].lower()))
        out.append({
            "group_id": gid, "name": names[gid], "owner": s["owner"], "call_time": _hhmm(s.get("call_time")),
            "max_month": s.get("max_month", 2), "swap_needs_ok": bool(s.get("swap_needs_ok")),
            "families": bool(s.get("families", True)), "sort": s.get("sort") or 0,
            "people": people,
            "places": [{
                "id": str(p["id"]), "name": p["name"], "needed": p.get("needed") or 1, "note": p.get("note") or "",
                "sort": p.get("sort") or 0,
                "people": sorted(({"contact_id": str(t["contact_id"]), "level": t.get("level") or "trained",
                                   **who[str(t["contact_id"])]}
                                  for t in trained if str(t["position_id"]) == str(p["id"]) and str(t["contact_id"]) in who),
                                 key=lambda x: (x["level"] != "trained", x["name"].lower())),
            } for p in places if str(p["group_id"]) == gid],
        })
    out.sort(key=lambda t: (t["sort"], t["name"].lower()))
    others = [{"group_id": str(g["id"]), "name": g["name"], "owner": owner_by_name(g["name"])}
              for g in groups if str(g["id"]) not in by_group]
    return out, others


def _team_row(biz: str, gid: str) -> Dict[str, Any]:
    rows = _serve_rows(f"/serve_teams?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&limit=1", "group_id,max_month")
    if not rows:
        raise HTTPException(404, "That Sunday team isn't here")
    return rows[0]


def _place_row(biz: str, pid: str) -> Dict[str, Any]:
    rows = _read(f"/serve_positions?id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&active=eq.true"
                 f"&select=id,group_id,name,needed&limit=1")
    if not rows:
        raise HTTPException(404, "That place isn't on the team anymore")
    return rows[0]


def _clean_name(raw: Any, what: str, longest: int) -> str:
    name = " ".join(str(raw or "").split())
    if not name or len(name) > longest:
        raise HTTPException(400, f"Give the {what} a name, {longest} letters at most")
    return name


@router.get("/status")
def status(business_id: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    """Is Planning on for this person; with a church, what may they do."""
    _gate(user)
    if not business_id:
        return {"enabled": True}
    biz = _uuid(business_id)
    # Never walled (sunday_hub): the app reads it to know what to show.
    roles = roles_of(biz, user, part=None, wall=False)
    settings = _church(biz).get("settings") or {}
    cs = settings.get("churchsavvy") if isinstance(settings.get("churchsavvy"), dict) else {}
    portal = settings.get("member_portal") if isinstance(settings.get("member_portal"), dict) else {}
    doors = _doors(biz, user, roles)
    return {"enabled": True, "can_write": can(roles, "serve"), "roles": sorted(roles),
            "can_setup": can(roles, "setup"), "email_asks": cs.get("planning_email") is True,
            "member_app": portal.get("enabled") is True, **doors,
            # This login may add an event date (one that isn't a Sunday) for the volunteer teams.
            "event_dates": _may_add_dates(biz, user, doors)}


@router.put("/email")
def set_email_asks(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """ChurchSavvy's "Email asks and reminders" (Setup → Planning): on, every
    ask and reminder goes by email with one-tap answers; off, Planning
    emails only what the member app's own switch sends. An admin's choice."""
    _gate(user)
    biz = _uuid(body.get("business_id"))
    require(biz, user, "setup")
    on = body.get("on") is True
    rows = _read(f"/businesses?id=eq.{_q(biz)}&select=settings&limit=1")
    if not rows:
        raise HTTPException(404, "That church isn't here")
    settings = rows[0].get("settings") if isinstance(rows[0].get("settings"), dict) else {}
    cs = dict(settings["churchsavvy"]) if isinstance(settings.get("churchsavvy"), dict) else {}
    cs["planning_email"] = on
    saved = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz)}&select=id",
                                           {"settings": {**settings, "churchsavvy": cs}})
    if not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"email_asks": on}


@router.get("/teams")
def list_teams(business_id: str, owner: Optional[str] = None, user: AuthedUser = Depends(require_user)):
    """The Sunday teams; with owner=, only ChurchSavvy's or only Volunteers'.
    `change` is whose teams this person may change (every team's still read)."""
    _gate(user)
    biz = _uuid(business_id)
    which = _which(owner)
    roles = _staff(biz, user, write=False)
    teams, others = _teams(biz)
    if which:
        teams = [t for t in teams if t["owner"] == which]
    _hub_marks(biz, user, teams)
    return {"teams": teams, "other_teams": others, "starters": STARTERS, "can_write": can(roles, "serve"),
            "owner": which, "owner_words": list(CHURCHSAVVY_WORDS), **_doors(biz, user, roles)}


@router.post("/teams")
def add_team(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Schedule a serving team on Sundays: one the church has (group_id), or
    a new one by name, with the places it starts with. In a church it's
    ChurchSavvy's or Volunteers' (`owner`): the one asked for, else the one
    door its maker schedules for, else by its name."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    have = _serve_rows(f"/serve_teams?business_id=eq.{_q(biz)}", "group_id")
    if len(have) >= MAX_TEAMS:
        raise HTTPException(400, f"A church schedules at most {MAX_TEAMS} Sunday teams")
    places = body.get("places") or []
    if not isinstance(places, list) or len(places) > 12:
        raise HTTPException(400, "A team starts with at most 12 places")
    places = [_clean_name(p, "place", 40) for p in places]
    gid: Optional[str] = None
    if body.get("group_id"):
        gid = _uuid(body["group_id"], "team")
        rows = _read(f"/groups?id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&kind=eq.team&active=eq.true&select=id,name&limit=1")
        if not rows:
            raise HTTPException(404, "That serving team isn't here")
        if any(str(h["group_id"]) == gid for h in have):
            raise HTTPException(409, "That team is already on Sundays")
        name = str(rows[0].get("name") or "")
    else:
        name = _clean_name(body.get("name"), "team", 80)
    owner = _new_owner(who, body.get("owner"), name)
    _team_gate(biz, who, owner)
    if gid is None:
        made = sb_clients.sb_post_as_service("/groups?select=id",
                                             {"business_id": biz, "name": name, "kind": "team", "join_mode": "ask"})
        if not isinstance(made, list) or not made:
            raise HTTPException(503, "The team didn't save. Try again.")
        gid = str(made[0]["id"])
    row: Dict[str, Any] = {"group_id": gid, "business_id": biz, "sort": len(have)}
    if not _owner_missing():
        row["owner"] = owner
    saved = sb_clients.sb_post_as_service("/serve_teams?select=group_id", row)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The team didn't save. Try again.")
    if places:
        seen: Set[str] = set()
        rows = []
        for i, p in enumerate(places):
            if p.lower() not in seen:
                seen.add(p.lower())
                rows.append({"business_id": biz, "group_id": gid, "name": p, "sort": i})
        if sb_clients.sb_post_as_service("/serve_positions?select=id", rows) is None:
            raise HTTPException(503, "The team saved, but its places didn't. Add them again.")
    teams, _ = _teams(biz)
    return {"team": next((t for t in teams if t["group_id"] == gid), None)}


@router.patch("/teams/{group_id}")
def change_team(group_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """A team's turns. In a church, `owner` moves it to the other door: only
    for someone who changes both doors' teams (the owner, an Admin)."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    gid = _uuid(group_id, "team")
    if "open_to_ops" in body:
        return _open_to_ops(biz, user, gid, body)
    who = _scheduler(biz, user)
    team = _team_row(biz, gid)
    _team_gate(biz, who, team["owner"])
    fields: Dict[str, Any] = {}
    if "owner" in body:
        to = body["owner"]
        if to not in OWNERS:
            raise HTTPException(400, "A Sunday team is ChurchSavvy's or Volunteers'")
        if to != team["owner"]:
            _team_gate(biz, who, to)
            if _owner_missing():
                raise HTTPException(409, "A team can't move between ChurchSavvy and Volunteers just yet. Try again soon.")
            fields["owner"] = to
    if "call_time" in body:
        ct = body["call_time"]
        if ct in (None, ""):
            fields["call_time"] = None
        elif isinstance(ct, str) and _HHMM.match(ct):
            fields["call_time"] = ct
        else:
            raise HTTPException(400, "Arrive by is a time like 10:15")
    if "max_month" in body:
        m = body["max_month"]
        if not isinstance(m, int) or isinstance(m, bool) or not 0 <= m <= 5:
            raise HTTPException(400, "Sundays a month is 1 to 5, or 0 for no limit")
        fields["max_month"] = m
    for k in ("swap_needs_ok", "families"):
        if k in body:
            if not isinstance(body[k], bool):
                raise HTTPException(400, f"{k} is yes or no")
            fields[k] = body[k]
    if "sort" in body:
        s = body["sort"]
        if not isinstance(s, int) or isinstance(s, bool) or not 0 <= s <= 999:
            raise HTTPException(400, "That order isn't valid")
        fields["sort"] = s
    if not fields:
        raise HTTPException(400, "Nothing to change")
    fields["updated_at"] = _now().isoformat()
    saved = sb_clients.sb_patch_as_service(
        f"/serve_teams?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&select=group_id", fields)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    teams, _ = _teams(biz)
    return {"team": next((t for t in teams if t["group_id"] == gid), None)}


def _open_to_ops(biz: str, user: AuthedUser, gid: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Open (or close) one Sunday team's spots to ministry operations: the
    owner, an Admin, or that team's own leader, and sent on its own. With
    the hub off it isn't there."""
    if not _hub_on(user):
        raise HTTPException(404, "Not Found")
    if set(body) - {"business_id", "open_to_ops"}:
        raise HTTPException(400, "Open a team to ministry operations on its own")
    if not isinstance(body.get("open_to_ops"), bool):
        raise HTTPException(400, "open_to_ops is yes or no")
    import sunday_hub
    roles_of(biz, user, part="planning")
    _team_row(biz, gid)
    st = sunday_hub.standing(biz, user)
    if not st["approve"] and gid not in {t["group_id"] for t in st["leads"]}:
        raise HTTPException(403, "Only the pastor or this team's leader opens its spots to ministry operations.")
    saved = sb_clients.sb_patch_as_service(f"/serve_teams?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&select=group_id",
                                           {"open_to_ops": body["open_to_ops"], "updated_at": _now().isoformat()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"group_id": gid, "open_to_ops": body["open_to_ops"]}


@router.delete("/teams/{group_id}")
def drop_team(group_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """Stop scheduling a team on Sundays. Its group, people and thread stay.
    Refused once anyone was asked: their Sundays would vanish with it."""
    _gate(user)
    biz = _uuid(business_id)
    who = _scheduler(biz, user)
    gid = _uuid(group_id, "team")
    _team_gate(biz, who, _team_row(biz, gid)["owner"])
    places = _read(f"/serve_positions?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&select=id")
    if places and _read(f"/serve_assignments?business_id=eq.{_q(biz)}&position_id=in.({_ids(p['id'] for p in places)})"
                        f"&select=id&limit=1"):
        raise HTTPException(409, "People were already asked to serve on this team. Take them off the schedule first.")
    if not sb_clients.sb_delete_as_service(f"/serve_teams?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True}


@router.post("/positions")
def add_place(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    gid = _uuid(body.get("group_id"), "team")
    _team_gate(biz, who, _team_row(biz, gid)["owner"])
    name = _clean_name(body.get("name"), "place", 40)
    needed = body.get("needed", 1)
    if not isinstance(needed, int) or isinstance(needed, bool) or not 1 <= needed <= 10:
        raise HTTPException(400, "A place needs 1 to 10 people")
    note = str(body.get("note") or "").strip()[:200]
    have = _read(f"/serve_positions?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&active=eq.true&select=name,sort")
    if len(have) >= MAX_PLACES:
        raise HTTPException(400, f"A team has at most {MAX_PLACES} places")
    if any((h.get("name") or "").strip().lower() == name.lower() for h in have):
        raise HTTPException(409, "The team already has that place")
    sort = max([h.get("sort") or 0 for h in have] + [-1]) + 1
    saved = sb_clients.sb_post_as_service("/serve_positions?select=id,group_id,name,needed,note,sort",
                                          {"business_id": biz, "group_id": gid, "name": name, "needed": needed,
                                           "note": note, "sort": min(sort, 999)})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The place didn't save. Try again.")
    p = saved[0]
    return {"place": {"id": str(p["id"]), "name": p["name"], "needed": p["needed"], "note": p.get("note") or "",
                      "sort": p.get("sort") or 0, "people": []}}


@router.patch("/positions/{position_id}")
def change_place(position_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    pid = _uuid(position_id, "place")
    place = _place_row(biz, pid)
    _place_gate(biz, who, place["group_id"])
    fields: Dict[str, Any] = {}
    if "name" in body:
        name = _clean_name(body["name"], "place", 40)
        others = _read(f"/serve_positions?group_id=eq.{_q(place['group_id'])}&active=eq.true&id=neq.{_q(pid)}&select=name")
        if any((o.get("name") or "").strip().lower() == name.lower() for o in others):
            raise HTTPException(409, "The team already has that place")
        fields["name"] = name
    if "needed" in body:
        n = body["needed"]
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 10:
            raise HTTPException(400, "A place needs 1 to 10 people")
        fields["needed"] = n
    if "note" in body:
        fields["note"] = str(body["note"] or "").strip()[:200]
    if "sort" in body:
        s = body["sort"]
        if not isinstance(s, int) or isinstance(s, bool) or not 0 <= s <= 999:
            raise HTTPException(400, "That order isn't valid")
        fields["sort"] = s
    if not fields:
        raise HTTPException(400, "Nothing to change")
    saved = sb_clients.sb_patch_as_service(
        f"/serve_positions?id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&select=id,name,needed,note,sort", fields)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    p = saved[0]
    return {"place": {"id": str(p["id"]), "name": p["name"], "needed": p["needed"], "note": p.get("note") or "",
                      "sort": p.get("sort") or 0}}


@router.delete("/positions/{position_id}")
def retire_place(position_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """Retire a place: it leaves the schedule; who served there stays."""
    _gate(user)
    biz = _uuid(business_id)
    who = _scheduler(biz, user)
    pid = _uuid(position_id, "place")
    _place_gate(biz, who, _place_row(biz, pid)["group_id"])
    saved = sb_clients.sb_patch_as_service(
        f"/serve_positions?id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&select=id", {"active": False})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True}


@router.put("/positions/{position_id}/people")
def set_trained(position_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Who's trained on a place, or learning it. Each of them is on the
    team (the group) too, so they hear its news and its thread."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    pid = _uuid(position_id, "place")
    place = _place_row(biz, pid)
    _place_gate(biz, who, place["group_id"])
    raw = body.get("people")
    if not isinstance(raw, list) or len(raw) > MAX_TRAINED:
        raise HTTPException(400, f"A place lists at most {MAX_TRAINED} people")
    want: Dict[str, str] = {}
    for p in raw:
        if not isinstance(p, dict):
            raise HTTPException(400, "Each person is {contact_id, level}")
        cid = _uuid(p.get("contact_id"), "person")
        level = p.get("level") or "trained"
        if level not in ("trained", "learning"):
            raise HTTPException(400, "Each person is trained or learning")
        want[cid] = level
    if want and len(_people(biz, want)) != len(want):
        raise HTTPException(404, "Someone there isn't in this church")
    gid = str(place["group_id"])
    have = {str(r["contact_id"]): r.get("level") for r in
            _read(f"/serve_trained?position_id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&select=contact_id,level")}
    gone = [c for c in have if c not in want]
    if gone and not sb_clients.sb_delete_as_service(
            f"/serve_trained?position_id=eq.{_q(pid)}&business_id=eq.{_q(biz)}&contact_id=in.({_ids(gone)})"):
        raise HTTPException(503, "That didn't save. Try again.")
    changed = [{"position_id": pid, "contact_id": c, "business_id": biz, "level": lv}
               for c, lv in want.items() if have.get(c) != lv]
    if changed and sb_clients.sb_post_as_service(
            "/serve_trained?on_conflict=position_id,contact_id&select=contact_id", changed,
            prefer="resolution=merge-duplicates,return=representation") is None:
        raise HTTPException(503, "That didn't save. Try again.")
    on_team = {str(m["contact_id"]) for m in
               _read(f"/group_members?group_id=eq.{_q(gid)}&business_id=eq.{_q(biz)}&select=contact_id")}
    joining = [{"group_id": gid, "contact_id": c, "business_id": biz, "role": "member"} for c in want if c not in on_team]
    if joining and sb_clients.sb_post_as_service(
            "/group_members?on_conflict=group_id,contact_id&select=contact_id", joining,
            prefer="resolution=ignore-duplicates,return=representation") is None:
        # They're trained either way; the team's news reaches them once they join.
        logger.warning("[planning] adding %d people to team %s didn't save", len(joining), gid)
    teams, _ = _teams(biz)
    team = next((t for t in teams if t["group_id"] == gid), None)
    return {"place": next((p for p in (team or {}).get("places", []) if p["id"] == pid), None)}


@router.get("/people")
def find_people(business_id: str, q: str = "", user: AuthedUser = Depends(require_user)):
    """Members to add to a team, by name: names only, and only for whoever
    schedules (never a church's records)."""
    _gate(user)
    biz = _uuid(business_id)
    _staff(biz, user, write=True)
    term = " ".join(q.split())[:60]
    if len(term) < 2:
        return {"people": []}
    safe = re.sub(r"[^\w .'-]", "", term)
    rows = _read(f"/contacts?business_id=eq.{_q(biz)}&name=ilike.*{_q(safe)}*&select=id,name,birthdate"
                 f"&order=name.asc&limit=20")
    today = _now().date()
    return {"people": [{"contact_id": str(r["id"]), "name": (r.get("name") or "").strip() or "Someone",
                        "teen": _is_teen(r.get("birthdate"), today)} for r in rows]}


@router.post("/people")
def add_person(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Someone new to schedule, by name and email (canvas UZu4VsoY9KemkUGorz234j
    board 10 "Add a person"): a church on ChurchSavvy alone has no member
    list to pick from. The same email at this church is the same person, so
    nobody is made twice, and their name stays as the church has it."""
    import academy_join
    _gate(user)
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, write=True)
    name = _clean_name(body.get("name"), "person", 80)
    email = str(body.get("email") or "").strip().lower()
    if not academy_join.valid_email(email):
        raise HTTPException(400, "That email doesn't look right.")
    like = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    found = _read(f"/contacts?business_id=eq.{_q(biz)}&email=ilike.{_q(like)}&select=id,name,birthdate&limit=1")
    if found:
        r = found[0]
        return {"person": {"contact_id": str(r["id"]), "name": (r.get("name") or "").strip() or name,
                           "teen": _is_teen(r.get("birthdate"), _now().date()), "has_email": True}, "existing": True}
    made = sb_clients.sb_post_as_service("/contacts", {"business_id": biz, "name": name, "email": email,
                                                      "source": "churchsavvy_planning"})
    if not isinstance(made, list) or not made:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"person": {"contact_id": str(made[0]["id"]), "name": name, "teen": False, "has_email": True},
            "existing": False}


# ─── the schedule ────────────────────────────────────────────────────


def _sunday_on_or_after(d: date) -> date:
    return d + timedelta(days=(6 - d.weekday()) % 7)


def _window(biz: str, start: Optional[str], weeks: int) -> Tuple[Any, date, datetime, datetime]:
    zone = _zone(biz)
    if start:
        if not isinstance(start, str) or not _DAY.match(start):
            raise HTTPException(400, "from is a date like 2026-10-25")
        try:
            first = date.fromisoformat(start)
        except ValueError:
            raise HTTPException(400, "from is a date like 2026-10-25")
    else:
        today = _now().astimezone(zone).date()
        first = _sunday_on_or_after(today)
        # From today, not from that Sunday: an event date this week (a
        # Thursday outreach night) shows before its Sunday comes. The
        # Sundays shown are still `weeks` of them.
        lo = datetime.combine(today, time(0), tzinfo=zone)
        hi = datetime.combine(first, time(0), tzinfo=zone) + timedelta(days=7 * weeks)
        return zone, first, lo, hi
    lo = datetime.combine(first, time(0), tzinfo=zone)
    hi = lo + timedelta(days=7 * weeks)
    return zone, first, lo, hi


def _services(biz: str, lo: datetime, hi: datetime, zone, plans: bool = False) -> List[Dict[str, Any]]:
    """The services in the window, soonest first, each on the church's
    clock. An event date (serve_dates) says so: kind 'event', its place, the
    Services & Events entry it came from, and that only the Volunteers'
    teams serve it. plans: the Sunday plans alone, no event dates."""
    rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
                 f"{sd.plans_only() if plans else ''}"
                 f"&starts_at=gte.{_q(lo.astimezone(timezone.utc).isoformat())}"
                 f"&starts_at=lt.{_q(hi.astimezone(timezone.utc).isoformat())}"
                 f"&select=id,title,starts_at{sd.fields()}&order=starts_at.asc")
    out = []
    for r in rows:
        try:
            at = datetime.fromisoformat(str(r["starts_at"]).replace("Z", "+00:00")).astimezone(zone)
        except (TypeError, ValueError):
            continue
        event = sd.is_event(r)
        svc = {"id": str(r["id"]), "title": r.get("title") or ("An event" if event else "Sunday service"),
               "starts_at": r["starts_at"], "day": at.date().isoformat(), "time": at.strftime("%H:%M"),
               "month": at.strftime("%Y-%m"), "kind": sd.EVENT if event else sd.SERVICE, "weekday": sd.weekday(at)}
        if event:
            # Its own numbers for the Volunteers' places (null: their Sunday numbers).
            svc.update({"place": r.get("place") or "", "only": VOLUNTEERS,
                        "event_entry_id": str(r["event_entry_id"]) if r.get("event_entry_id") else None,
                        "needs": r["needs"] if isinstance(r.get("needs"), dict) else None})
        out.append(svc)
    out.sort(key=lambda x: x["starts_at"] and datetime.fromisoformat(str(x["starts_at"]).replace("Z", "+00:00")))
    return out


def serves(service: Dict[str, Any], team: Dict[str, Any]) -> bool:
    """Whether this team serves at this service: every team on a Sunday,
    only the Volunteers' teams on an event date."""
    return service.get("kind") != sd.EVENT or team.get("owner") == VOLUNTEERS


class _Board:
    """Everything a schedule decision needs, read once: the services in a
    window, the teams and places, every ask and answer, who's away (and who
    has asked to be and still waits: `held`), and how many Sundays each
    person is on in each month."""

    def __init__(self, biz: str, start: Optional[str], weeks: int, month_reach: bool = True):
        self.biz = biz
        self.zone, self.first, lo, hi = _window(biz, start, weeks)
        self.lo_day = lo.date()
        self.services = _services(biz, lo, hi, self.zone)
        self.teams, _ = _teams(biz)
        # A person's load counts their whole months, so read from the first
        # of the first month to the end of the last one.
        if month_reach:
            mlo = lo.replace(day=1)
            mhi = (hi.replace(day=1) + timedelta(days=32)).replace(day=1)
            self.month_services = _services(biz, mlo, mhi, self.zone)
        else:
            self.month_services = list(self.services)
        sids = [s["id"] for s in self.month_services]
        self.rows = (_read(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=in.({_ids(sids)})"
                           f"&select=id,service_id,position_id,slot,contact_id,status,note,asked_by,asked_at,answered_at,notified_at,swap_to")
                     if sids else [])
        last = (hi - timedelta(days=1)).date()
        self.away = _read(f"/serve_away?business_id=eq.{_q(biz)}&starts_on=lte.{last.isoformat()}"
                          f"&ends_on=gte.{self.lo_day.isoformat()}&select=contact_id,starts_on,ends_on,note")
        # Days someone has asked to be away and still waits on (the leaders
        # schedule): they read as away for those days, in the same words, so
        # nobody asks them then. Who and which days only; never in `away`,
        # which is what was agreed. It fails open and costs no read where the
        # leaders schedule isn't open (church_schedule.holds).
        import church_schedule
        self.held = church_schedule.holds(biz, self.lo_day, last)
        self.place_name = {p["id"]: p["name"] for t in self.teams for p in t["places"]}
        self.place_team = {p["id"]: t for t in self.teams for p in t["places"]}
        self.service = {s["id"]: s for s in self.month_services}

    def busy(self, cid: str, sid: str, but_place: Optional[str] = None) -> Optional[str]:
        """The place this person already holds at this service, if any."""
        for r in self.rows:
            if (str(r.get("contact_id")) == cid and str(r["service_id"]) == sid and r["status"] in ("asked", "yes")
                    and str(r["position_id"]) != (but_place or "")):
                return self.place_name.get(str(r["position_id"]), "another place")
        return None

    def is_away(self, cid: str, sid: str) -> bool:
        """Away that day: an away date of theirs, or days they have asked
        for and still wait on (`held`). The board says "away" for both and
        never which."""
        day = self.service[sid]["day"]
        return any(str(a["contact_id"]) == cid and str(a["starts_on"]) <= day <= str(a["ends_on"])
                   for a in (*self.away, *self.held))

    def load(self, cid: str, month: str) -> int:
        """The Sundays (services) this person is on that month: an event
        date isn't one of a team's Sundays a month."""
        return sum(1 for r in self.rows if str(r.get("contact_id")) == cid and r["status"] in ("asked", "yes")
                   and self.service.get(str(r["service_id"]), {}).get("month") == month
                   and self.service.get(str(r["service_id"]), {}).get("kind") != sd.EVENT)

    def holder(self, sid: str, pid: str, slot: int) -> Optional[Dict[str, Any]]:
        return next((r for r in self.rows if str(r["service_id"]) == sid and str(r["position_id"]) == pid
                     and int(r.get("slot") or 1) == slot), None)

    def candidates(self, sid: str, pid: str) -> List[Dict[str, Any]]:
        team = self.place_team.get(pid)
        if not team or not serves(self.service[sid], team):
            return []
        place = next(p for p in team["places"] if p["id"] == pid)
        if sd.needed(self.service[sid], place) < 1:
            return []           # an event date that doesn't need this place
        level = {p["contact_id"]: p["level"] for p in place["people"]}
        month = self.service[sid]["month"]
        # An event date isn't one of the team's Sundays a month: no cap.
        cap = 0 if self.service[sid].get("kind") == sd.EVENT else (team.get("max_month") or 0)
        out = []
        for person in team["people"]:
            cid = person["contact_id"]
            clash = self.busy(cid, sid, but_place=pid)
            away = self.is_away(cid, sid)
            n = self.load(cid, month)
            full = bool(cap) and n >= cap
            out.append({"contact_id": cid, "name": person["name"], "teen": person["teen"], "leader": person["leader"],
                        "trained": level.get(cid), "away": away, "clash": clash, "load": n, "at_most": cap,
                        "ok": not away and not clash and not full})
        rank = {"trained": 0, "learning": 1, None: 2}
        out.sort(key=lambda c: (not c["ok"], rank[c["trained"]], c["load"], c["name"].lower()))
        return out


def _assignment_out(r: Dict[str, Any], who: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    cid = str(r["contact_id"]) if r.get("contact_id") else None
    swap = str(r["swap_to"]) if r.get("swap_to") else None
    return {"id": str(r["id"]), "service_id": str(r["service_id"]), "position_id": str(r["position_id"]),
            "slot": int(r.get("slot") or 1), "contact_id": cid, "name": (who.get(cid) or {}).get("name") if cid else None,
            "status": r["status"], "note": r.get("note") or "", "asked_by": r.get("asked_by") or "",
            "asked_at": r.get("asked_at"), "answered_at": r.get("answered_at"),
            "sent": bool(r.get("notified_at")),
            # They asked someone to cover; they stay on until that person says yes.
            "swap_to": swap, "swap_name": (who.get(swap) or {}).get("name") if swap else None}


@router.get("/schedule")
def schedule(business_id: str, user: AuthedUser = Depends(require_user), weeks: int = 5,
             start: Optional[str] = None, owner: Optional[str] = None):
    """The coming services, each team's places and who's on them; with
    owner=, only ChurchSavvy's or only Volunteers' teams and their asks."""
    _gate(user)
    biz = _uuid(business_id)
    which = _which(owner)
    roles = _staff(biz, user, write=False)
    if not 1 <= weeks <= MAX_WEEKS:
        raise HTTPException(400, f"Show 1 to {MAX_WEEKS} weeks")
    board = _Board(biz, start, weeks)
    teams = [t for t in board.teams if not which or t["owner"] == which]
    _hub_marks(biz, user, teams)
    # ChurchSavvy's door doesn't list an event date: none of its teams serve one.
    services = [s for s in board.services if not (which == CHURCHSAVVY and s.get("kind") == sd.EVENT)]
    places = {p["id"] for t in teams for p in t["places"]}
    shown = {s["id"]: s for s in services}
    rows = [r for r in board.rows if str(r["service_id"]) in shown and (not which or str(r["position_id"]) in places)
            and (str(r["position_id"]) not in board.place_team
                 or serves(shown[str(r["service_id"])], board.place_team[str(r["position_id"])]))]
    who = _people(biz, [r.get("contact_id") for r in rows] + [r.get("swap_to") for r in rows]
                  + [a["contact_id"] for a in board.away])
    doors = _doors(biz, user, roles)
    # How many each shown place needs at each service (serve_dates.needed): its
    # Sunday number, or an event date's own (0: not needed that night).
    services = [{**s, "needed": {p["id"]: sd.needed(s, p) for t in teams if serves(s, t) for p in t["places"]}}
                for s in services]
    # An event date's flyer {thumb, url}, and `event_moved` when its event
    # moved and the date didn't follow (event_volunteers, spec 6.7, 6.12).
    import event_volunteers
    event_volunteers.date_extras(biz, services, user)
    return {
        "from": board.first.isoformat(), "weeks": weeks,
        "services": services,
        "teams": teams,
        "assignments": [_assignment_out(r, who) for r in rows],
        "away": [{"contact_id": str(a["contact_id"]), "name": (who.get(str(a["contact_id"])) or {}).get("name"),
                  "starts_on": a["starts_on"], "ends_on": a["ends_on"]} for a in board.away],
        "can_write": can(roles, "serve"),
        "owner": which, **doors, "event_dates": _may_add_dates(biz, user, doors),
        # Events' asks for the serving teams still waiting (the band; event_volunteers).
        "requests_waiting": _requests_waiting(biz, user, doors),
    }


def _requests_waiting(biz: str, user: AuthedUser, doors: Dict[str, Any]) -> int:
    """How many events' asks wait at this church: 0 outside a church whose
    teams have owners, before the migration and with EVENT_VOLUNTEERS closed."""
    if not doors.get("two_doors"):
        return 0
    import event_volunteers
    return event_volunteers.waiting_count(biz, user)


@router.post("/sundays")
def add_sundays(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Add the coming Sundays to plan, at the church's usual time. A Sunday
    that already has a service is left as it is."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, write=True)
    count = body.get("count", 5)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_WEEKS:
        raise HTTPException(400, f"Add 1 to {MAX_WEEKS} Sundays")
    at = body.get("time") or SUNDAY_TIME
    if not isinstance(at, str) or not _HHMM.match(at):
        raise HTTPException(400, "The time is like 10:30")
    zone, first, lo, hi = _window(biz, body.get("start"), count)
    # An event date that day (a Sunday afternoon's) is not that Sunday's service.
    have = {s["day"] for s in _services(biz, lo, hi, zone, plans=True)}
    hh, mm = (int(x) for x in at.split(":"))
    rows = []
    for i in range(count):
        day = first + timedelta(days=7 * i)
        if day.isoformat() in have:
            continue
        starts = datetime.combine(day, time(hh, mm), tzinfo=zone).astimezone(timezone.utc).isoformat()
        rows.append({"business_id": biz, "title": "Sunday service", "starts_at": starts, "items": []})
    if rows and sb_clients.sb_post_as_service("/worship_services?select=id", rows) is None:
        raise HTTPException(503, "The Sundays didn't save. Try again.")
    return {"added": len(rows)}


# ─── event dates (serve_dates) ───────────────────────────────────────


def _dates_gate(biz: str, user: AuthedUser, switch: bool = True) -> Dict[str, Any]:
    """Event dates are a church's whose teams have owners, with the columns
    there and (to add one) the switch open for it: otherwise 404, as if
    there were nothing here. Then whoever changes the Volunteers' teams:
    the owner, an Admin, a serve_schedule holder; anyone else hears whose
    job it is (or a viewer, the part's refusal)."""
    if not sd.ready() or (switch and not sd.open_for(biz, user)) or not _office(biz):
        raise HTTPException(404, "Not Found")
    who = _scheduler(biz, user)
    _team_gate(biz, who, VOLUNTEERS)
    return who


def _sunday_services(biz: str, lo: datetime, hi: datetime) -> List[datetime]:
    """When each Sunday service (kind service, not a template) starts in the
    window: the plans alone, never an event date."""
    out = []
    for r in _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
                   f"{sd.plans_only()}&starts_at=gte.{_q(lo.astimezone(timezone.utc).isoformat())}"
                   f"&starts_at=lt.{_q(hi.astimezone(timezone.utc).isoformat())}&select=id,starts_at&limit=500"):
        try:
            out.append(datetime.fromisoformat(str(r["starts_at"]).replace("Z", "+00:00")))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _clashes(starts: datetime, services: Iterable[datetime]) -> bool:
    """Starts within SUNDAY_HOURS of one of these services (either side)."""
    return any(abs(starts - at) < timedelta(hours=SUNDAY_HOURS) for at in services)


def usual_sunday_times(biz: str, zone) -> List[time]:
    """When this church's Sunday services usually start, for a Sunday that
    isn't planned yet (Sundays are added a few at a time; event dates go
    180 days out): the times of its Sunday services from USUAL_WEEKS before
    today to USUAL_WEEKS after; with none, SUNDAY_TIME, the time Add the next
    five Sundays gives them."""
    today = _now().astimezone(zone).date()
    lo = datetime.combine(today - timedelta(days=7 * USUAL_WEEKS), time(0), tzinfo=zone)
    hi = datetime.combine(today + timedelta(days=7 * USUAL_WEEKS + 1), time(0), tzinfo=zone)
    got = {at.astimezone(zone).time().replace(second=0, microsecond=0) for at in _sunday_services(biz, lo, hi)
           if at.astimezone(zone).weekday() == 6}
    hh, mm = (int(x) for x in SUNDAY_TIME.split(":"))
    return sorted(got) or [time(hh, mm)]


def _that_sunday(day: date, planned: List[datetime], zone, usual) -> List[datetime]:
    """The Sunday services on this day: those planned, else the church's
    usual times on it (`usual`: called once, only when needed)."""
    mine = [at for at in planned if at.astimezone(zone).date() == day]
    return mine or [datetime.combine(day, t, tzinfo=zone) for t in usual()]


def during_sunday_service(biz: str, starts: datetime, zone) -> bool:
    """Whether a Sunday event date starting then would be during a Sunday
    service that day (docs/EVENT_VOLUNTEERS.md 6.9): one planned, or, with
    that Sunday not planned yet, one at the church's usual time."""
    day = starts.astimezone(zone).date()
    lo = datetime.combine(day, time(0), tzinfo=zone)
    return _clashes(starts, _that_sunday(day, _sunday_services(biz, lo, lo + timedelta(days=1)), zone,
                                         lambda: usual_sunday_times(biz, zone)))


def _upcoming_events(biz: str, zone, now: datetime, sundays: bool = False) -> List[Dict[str, Any]]:
    """The church's Services & Events entries from today to EVENT_AHEAD_DAYS
    out that aren't on a Sunday (a Sunday is Add the next five Sundays'),
    soonest first: {entry_id, title, day, weekday, time (or None), place,
    taken (already an event date)}. `sundays` (EVENT_VOLUNTEERS open): a
    Sunday afternoon's is one too, unless it starts within SUNDAY_HOURS of a
    Sunday service that day or carries no time to tell."""
    import church_leaders_note as cln
    import events_rsvp_router as ev
    mods = _read(f"/custom_modules?business_id=eq.{_q(biz)}&archetype=eq.event_roster&is_active=eq.true"
                 "&select=id,archetype_params&limit=50")
    if not mods:
        return []
    fields = {str(m["id"]): ev.resolve_fields(m.get("archetype_params")) for m in mods}
    taken = {str(r["event_entry_id"]) for r in _read(
        f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&kind=eq.{sd.EVENT}"
        "&event_entry_id=not.is.null&select=event_entry_id&limit=500") if r.get("event_entry_id")}
    today = now.date()
    last = today + timedelta(days=EVENT_AHEAD_DAYS)
    plans: Optional[List[datetime]] = None
    usual: List[List[time]] = []

    def usual_times() -> List[time]:
        if not usual:
            usual.append(usual_sunday_times(biz, zone))
        return usual[0]
    ids = sorted(fields)
    out: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 50):
        for e in _read(f"/module_entries?business_id=eq.{_q(biz)}&module_id=in.({_ids(ids[i:i + 50])})"
                       "&status=eq.active&select=id,module_id,data&order=created_at.desc&limit=1000"):
            f = fields.get(str(e.get("module_id")))
            data = e.get("data") if isinstance(e.get("data"), dict) else {}
            if not f:
                continue
            day, at = cln._when_of(data.get(f["date_field"]), zone)
            if not day or not today <= day <= last or (at is not None and at <= now):
                continue
            if day.weekday() == 6:
                if not sundays or at is None:
                    continue
                if plans is None:
                    lo = datetime.combine(today, time(0), tzinfo=zone)
                    plans = _sunday_services(biz, lo, lo + timedelta(days=EVENT_AHEAD_DAYS + 1))
                if _clashes(at, _that_sunday(day, plans, zone, usual_times)):
                    continue
            out.append({"entry_id": str(e["id"]), "title": " ".join(str(data.get(f["title_field"]) or "").split())[:120]
                        or "An event", "day": day.isoformat(), "weekday": sd.weekday(day),
                        "time": at.strftime("%H:%M") if at else None,
                        "place": " ".join(str(data.get(f["location_field"]) or "").split())[:120],
                        "taken": str(e["id"]) in taken})
    out.sort(key=lambda x: (x["day"], x["time"] or "", x["title"].lower()))
    return out


def _asks_open(biz: str, user: AuthedUser) -> bool:
    """EVENT_VOLUNTEERS open here, with its migration in: Sunday afternoons
    and typed dates becoming Services & Events entries."""
    import event_volunteers
    return event_volunteers.ready() and event_volunteers.open_for(biz, user)


@router.get("/events")
def upcoming_events(business_id: str, user: AuthedUser = Depends(require_user)):
    """What "Add an event date" offers first: the upcoming Services & Events
    entries that aren't on a Sunday and aren't on Who serves when yet."""
    _gate(user)
    biz = _uuid(business_id)
    _dates_gate(biz, user)
    zone = _zone(biz)
    return {"events": [e for e in _upcoming_events(biz, zone, _now().astimezone(zone), sundays=_asks_open(biz, user))
                       if not e["taken"]][:60]}


@router.post("/dates")
def add_date(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """An event date that isn't a Sunday, for the volunteer teams: one of
    the church's upcoming Services & Events entries (entry_id: its title,
    day, place and time when it has one; a time given here wins), or typed
    (title, day, time, place). Never past, at most EVENT_AHEAD_DAYS ahead;
    an entry once while it's on the schedule, and one title once a day. It
    has no order of service, so ChurchSavvy's plan and screens never see it.
    With EVENT_VOLUNTEERS open it may be a Sunday afternoon, and a typed one
    goes into Services & Events too (make_date)."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _dates_gate(biz, user)
    entry_id = _uuid(body.get("entry_id"), "event") if body.get("entry_id") else None
    if entry_id:
        import event_volunteers
        if event_volunteers.ready() and event_volunteers.live_request(biz, entry_id):
            raise HTTPException(409, "This event already asked for volunteers. Answer its ask on Who serves when "
                                     "instead.")
    return make_date(biz, user, entry_id=entry_id, title=body.get("title"), day=body.get("day"),
                     at_time=body.get("time"), place=body.get("place"))


def _typed_entry(biz: str, title: str, starts: datetime, place: str) -> Optional[Dict[str, Any]]:
    """A typed event date's Services & Events entry (docs/EVENT_VOLUNTEERS.md
    6.8), in the church's first events room (the oldest active event_roster
    module), private, with no sign-ups and no roles of its own. None when the
    church has no events room. A write that fails is a 503: the date isn't
    made either."""
    import events_rsvp_router as ev
    mods = _read(f"/custom_modules?business_id=eq.{_q(biz)}&archetype=eq.event_roster&is_active=eq.true"
                 "&select=id,archetype_params,created_at&order=created_at.asc&limit=50")
    if not mods:
        return None
    mod = min(mods, key=lambda m: (str(m.get("created_at") or ""), str(m["id"])))
    f = ev.resolve_fields(mod.get("archetype_params"))
    data = {f["title_field"]: title, f["date_field"]: starts.strftime("%Y-%m-%dT%H:%M"), f["location_field"]: place,
            "_visibility": "private", f["signups_field"]: [], "_roles": []}
    got = sb_clients.sb_post_as_service("/module_entries", {
        "business_id": biz, "module_id": str(mod["id"]), "status": "active", "created_by": "who_serves_when",
        "data": data})
    if not isinstance(got, list) or not got:
        raise HTTPException(503, "The event date didn't save. Try again.")
    return {"entry_id": str(got[0]["id"]), "module_id": str(mod["id"]), "title": title}


def make_date(biz: str, user: AuthedUser, *, entry_id: Optional[str] = None, title: Any = None, day: Any = None,
              at_time: Any = None, place: Any = None, needs: Optional[Dict[str, int]] = None,
              gone: Optional[str] = None) -> Dict[str, Any]:
    """The one way an event date is made (docs/EVENT_VOLUNTEERS.md 6.3): Add
    an event date (POST /dates) and an event's ask for the serving teams
    (event_volunteers: a yes, or an ask put straight on), which passes its
    numbers (`needs`). Every rule holds whichever way it comes: never past,
    EVENT_AHEAD_DAYS ahead at most, MAX_EVENT_DATES still to come at most,
    one live event date an entry, one title once a day. A Sunday only with
    EVENT_VOLUNTEERS open, and never within SUNDAY_HOURS of a Sunday
    service. The caller gates who; this gates what. {date, event}: the
    event is the Services & Events entry a typed date made (6.8), else
    None. `gone`: the words when the entry isn't coming up (an ask's own)."""
    zone = _zone(biz)
    now = _now().astimezone(zone)
    asks = _asks_open(biz, user)
    if entry_id:
        ev = next((e for e in _upcoming_events(biz, zone, now, sundays=asks) if e["entry_id"] == entry_id), None)
        if not ev:
            raise HTTPException(404, gone or "That event isn't coming up in Services & Events. Pick another, or "
                                             "type it in.")
        if ev["taken"]:
            raise HTTPException(409, "That event is already on Who serves when.")
        title, raw_day, at_time, place = ev["title"], ev["day"], at_time or ev["time"], ev["place"]
    else:
        title = _clean_name(title, "event", 120)
        raw_day = day
        place = " ".join(str(place or "").split())
        if len(place) > 120:
            raise HTTPException(400, "Keep the place to 120 letters")
    if not isinstance(raw_day, str) or not _DAY.match(raw_day):
        raise HTTPException(400, "Pick the day it's on")
    try:
        day = date.fromisoformat(raw_day)
    except ValueError:
        raise HTTPException(400, "Pick the day it's on")
    if not isinstance(at_time, str) or not _HHMM.match(at_time):
        raise HTTPException(400, "Give it a start time, like 19:00")
    if day.weekday() == 6 and not asks:
        raise HTTPException(400, "Sundays are already on Who serves when: add them with Add the next five Sundays.")
    if day > now.date() + timedelta(days=EVENT_AHEAD_DAYS):
        raise HTTPException(400, f"Pick a day in the next {EVENT_AHEAD_DAYS // 30} months")
    hh, mm = (int(x) for x in at_time.split(":"))
    starts = datetime.combine(day, time(hh, mm), tzinfo=zone)
    if starts <= now:
        raise HTTPException(400, "That day and time have passed")
    if day.weekday() == 6 and during_sunday_service(biz, starts, zone):
        raise HTTPException(400, SUNDAY_CLASH)
    ahead = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&kind=eq.{sd.EVENT}"
                  f"&starts_at=gte.{_q(now.astimezone(timezone.utc).isoformat())}&select=id,title,starts_at&limit=500")
    if len(ahead) >= MAX_EVENT_DATES:
        raise HTTPException(400, f"That's {MAX_EVENT_DATES} event dates still to come. Take one off first.")
    for r in ahead:
        try:
            same_day = datetime.fromisoformat(str(r["starts_at"]).replace("Z", "+00:00")).astimezone(zone).date() == day
        except (TypeError, ValueError):
            continue
        if same_day and str(r.get("title") or "").strip().lower() == title.lower():
            raise HTTPException(409, f"{title} is already on Who serves when for {sd.day_label(day)}.")
    # A typed date is a Services & Events entry too (the switch open), written
    # first: if it can't be, the date isn't made; if the date can't be, the
    # entry comes back out. Never half of one.
    made = _typed_entry(biz, title, starts, place) if asks and not entry_id else None
    row = {"business_id": biz, "title": title, "starts_at": starts.astimezone(timezone.utc).isoformat(), "items": [],
           "kind": sd.EVENT, "place": place, "event_entry_id": made["entry_id"] if made else entry_id}
    if needs:
        row["needs"] = needs
    saved = sb_clients.sb_post_as_service("/worship_services?select=id,title,starts_at,kind,place,event_entry_id", row)
    if not isinstance(saved, list) or not saved:
        err = sb_clients.last_error() or {}
        if made and not sb_clients.sb_delete_as_service(
                f"/module_entries?id=eq.{_q(made['entry_id'])}&business_id=eq.{_q(biz)}"):
            print(f"[sunday_planning] {biz[:8]}: a typed date's entry wasn't taken back", flush=True)
        if str(err.get("code")) == "23505":
            raise HTTPException(409, "That event is already on Who serves when.")
        raise HTTPException(503, "The event date didn't save. Try again.")
    out = _services(biz, starts - timedelta(minutes=1), starts + timedelta(minutes=1), zone)
    return {"date": next((s for s in out if s["id"] == str(saved[0]["id"])), None), "event": made}


@router.delete("/dates/{service_id}")
def drop_date(service_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """Take an event date off Who serves when, only while nobody was asked
    for it (take its asks back first). Only an event date: never a Sunday
    or anything of ChurchSavvy's. The switch doesn't stop it: a date made
    while it was on can always come off."""
    _gate(user)
    biz = _uuid(business_id)
    _dates_gate(biz, user, switch=False)
    sid = _uuid(service_id, "event date")
    if not _read(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&archived_at=is.null"
                 f"&kind=eq.{sd.EVENT}&select=id&limit=1"):
        raise HTTPException(404, "That event date isn't on Who serves when")
    if _read(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&select=id&limit=1"):
        raise HTTPException(409, "Someone was asked for this date. Take back its asks first, then take the date off.")
    import event_volunteers
    # The ask that made it is closed first: a date gone with its ask still on
    # would leave the event unable to ask again or take it back.
    if not event_volunteers.close_for_date(biz, sid):
        raise HTTPException(503, "That didn't take the date off. Try again.")
    saved = sb_clients.sb_patch_as_service(
        f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&kind=eq.{sd.EVENT}&archived_at=is.null&select=id",
        {"archived_at": _now().isoformat()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't take the date off. Try again.")
    return {"ok": True}


# ─── events' asks for the serving teams (event_volunteers) ───────────


def _requests_gate(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """Events' asks are answered by whoever changes the Volunteers' teams
    (_dates_gate), with EVENT_VOLUNTEERS open here and its migration in:
    otherwise 404, as if there were nothing here."""
    import event_volunteers
    if not event_volunteers.ready() or not event_volunteers.open_for(biz, user):
        raise HTTPException(404, "Not Found")
    return _dates_gate(biz, user, switch=False)


@router.get("/requests")
def event_requests(business_id: str, user: AuthedUser = Depends(require_user)):
    """The events' asks for the serving teams: those waiting, soonest event
    first, and those answered in the last week (event_volunteers.requests_list)."""
    _gate(user)
    biz = _uuid(business_id)
    _requests_gate(biz, user)
    import event_volunteers
    return {"requests": event_volunteers.requests_list(biz)}


@router.post("/requests/{request_id}/answer")
def answer_request(request_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Yes (the event date is made with the ask's numbers, or the ones given
    here) or no (with a note back). event_volunteers.answer."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _requests_gate(biz, user)
    import event_volunteers
    return event_volunteers.answer(biz, user, _uuid(request_id, "ask"), body)


@router.put("/dates/{service_id}/needs")
def set_needs(service_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """An event date's own numbers for the Volunteers' places
    (docs/EVENT_VOLUNTEERS.md 6.4): {needs: {place_id: n}}, or null for the
    places' Sunday numbers. Lowering a place below a spot someone was asked
    for, or taking that place off, is refused until that ask is taken back;
    an open spot left past the new number (offered to the team, or a no)
    goes with it. The ask that made the date follows."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _requests_gate(biz, user)
    sid = _uuid(service_id, "event date")
    if "needs" not in body:
        raise HTTPException(400, "Give the numbers for each place, or null for the Sunday numbers.")
    import event_volunteers
    rows = _read(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&archived_at=is.null"
                 f"&kind=eq.{sd.EVENT}&select=id,title,starts_at{sd.fields()}&limit=1")
    if not rows:
        raise HTTPException(404, "That event date isn't on Who serves when")
    svc = rows[0]
    places = event_volunteers.volunteer_places(biz)
    needs = None if body["needs"] is None else event_volunteers.clean_needs(biz, body["needs"], places)
    after = {"kind": sd.EVENT, "needs": needs}
    by_id = {p["id"]: p for p in places}
    order = {p["id"]: n for n, p in enumerate(places)}

    def beyond() -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """(the refusal for the first asked spot past the new numbers, the
        open spots past them)."""
        held = _read(f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}"
                     f"&select=id,position_id,slot,status,contact_id")
        open_: List[Dict[str, Any]] = []
        for r in sorted(held, key=lambda r: (order.get(str(r["position_id"]), len(order)), int(r.get("slot") or 1))):
            place = by_id.get(str(r["position_id"]))
            if not place or int(r.get("slot") or 1) <= sd.needed(after, place):
                continue
            if r.get("status") in ("asked", "yes") and r.get("contact_id"):
                return (f"Someone was asked for {place['name']} {int(r.get('slot') or 1)}. Take that ask back "
                        "first."), open_
            open_.append(r)
        return None, open_
    refused, past = beyond()
    if refused:
        raise HTTPException(409, refused)
    if past and not sb_clients.sb_delete_as_service(
            f"/serve_assignments?business_id=eq.{_q(biz)}&service_id=eq.{_q(sid)}&id=in.({_ids(r['id'] for r in past)})"
            "&status=in.(offered,no)"):
        raise HTTPException(503, "That didn't save. Try again.")
    saved = sb_clients.sb_patch_as_service(
        f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&kind=eq.{sd.EVENT}&archived_at=is.null&select=id",
        {"needs": needs})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    # An ask for a spot past the new numbers that landed meanwhile: the
    # numbers go back, and it is said as before.
    refused, _ = beyond()
    if refused:
        back = sb_clients.sb_patch_as_service(
            f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&kind=eq.{sd.EVENT}&select=id",
            {"needs": svc.get("needs") if isinstance(svc.get("needs"), dict) else None})
        if not isinstance(back, list) or not back:
            print(f"[sunday_planning] {biz[:8]}: an event date's numbers weren't put back", flush=True)
        raise HTTPException(409, refused)
    event_volunteers.follow_needs(biz, sid, needs, places)
    return {"service_id": sid, "needs": needs,
            "needed": {p["id"]: sd.needed(after, p) for p in places}}


@router.get("/candidates")
def candidates(business_id: str, service_id: str, position_id: str, user: AuthedUser = Depends(require_user)):
    """Who on the team could take a place: free and not away first, then
    trained before learning, then whoever has served least that month."""
    _gate(user)
    biz = _uuid(business_id)
    _staff(biz, user, write=True)
    sid, pid = _uuid(service_id, "service"), _uuid(position_id, "place")
    board = _service_board(biz, sid)
    if pid not in board.place_team:
        raise HTTPException(404, "That place isn't on a Sunday team")
    return {"candidates": board.candidates(sid, pid)}


def _service_board(biz: str, sid: str) -> _Board:
    rows = _read(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&archived_at=is.null&select=starts_at&limit=1")
    if not rows:
        raise HTTPException(404, "That service isn't here")
    zone = _zone(biz)
    try:
        day = datetime.fromisoformat(str(rows[0]["starts_at"]).replace("Z", "+00:00")).astimezone(zone).date()
    except (TypeError, ValueError):
        raise HTTPException(409, "That service has no date yet")
    board = _Board(biz, day.isoformat(), 1)
    if sid not in board.service:
        raise HTTPException(404, "That service isn't here")
    return board


def _serves_gate(board: _Board, sid: str, pid: str) -> None:
    """409 for a place on a team that doesn't serve at this service: a
    ChurchSavvy team on an event date."""
    team, svc = board.place_team.get(pid), board.service.get(sid)
    if team and svc and not serves(svc, team):
        raise HTTPException(409, f"Only the volunteer teams serve at {svc['title']}. {team['name']} isn't scheduled for it.")


def _slot(body: Dict[str, Any], place: Dict[str, Any], svc: Optional[Dict[str, Any]] = None) -> int:
    """The spot asked for, within how many this place needs at this service
    (serve_dates.needed). A place an event date doesn't need is a 409."""
    n = sd.needed(svc, place) if svc is not None else (place.get("needed") or 1)
    if n < 1:
        import event_volunteers
        raise HTTPException(409, f"{place.get('name') or 'That place'} isn't needed for "
                                 f"{event_volunteers.the((svc or {}).get('title'))}.")
    slot = body.get("slot", 1)
    if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= n:
        raise HTTPException(400, "That place doesn't have that many spots")
    return slot


def _put(biz: str, board: _Board, sid: str, pid: str, slot: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Write one place on one service: replace whatever was there, unless
    someone already said yes (taking them off is its own step)."""
    held = board.holder(sid, pid, slot)
    if held and held["status"] == "yes" and str(held.get("contact_id")) != str(fields.get("contact_id")):
        who = _people(biz, [held["contact_id"]]).get(str(held["contact_id"]), {}).get("name", "Someone")
        raise HTTPException(409, f"{who} already said yes for this place. Take them off first.")
    row = {"contact_id": None, "status": "asked", "note": "", "asked_by": "", "asked_at": _now().isoformat(),
           "answered_at": None, "notified_at": None, "nudged_at": None, "swap_to": None, "swap_asked_at": None,
           # What sunday_serving_alerts already said was said to whoever held it.
           "leader_told_at": None, "week_sent_at": None, "day_sent_at": None, "morning_sent_at": None,
           "swap_told_at": None, "here_at": None, **fields}
    if held:
        saved = sb_clients.sb_patch_as_service(
            f"/serve_assignments?id=eq.{_q(held['id'])}&business_id=eq.{_q(biz)}&select=*", row)
    else:
        saved = sb_clients.sb_post_as_service(
            "/serve_assignments?select=*", {"business_id": biz, "service_id": sid, "position_id": pid, "slot": slot, **row})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return saved[0]


@router.post("/ask")
def ask(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Ask someone on the team to take a place. The ask goes out on the
    next sweep, with the church's quiet hours kept."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    sid, pid = _uuid(body.get("service_id"), "service"), _uuid(body.get("position_id"), "place")
    cid = _uuid(body.get("contact_id"), "person")
    place = _place_row(biz, pid)
    gid = str(place["group_id"])
    _place_gate(biz, who, gid, schedule=True)
    out = do_ask(biz, sid, pid, body.get("slot", 1), cid, _asker(biz, user))
    if _borrowed(who, _team_row(biz, gid)["owner"], gid):
        a = out["assignment"]
        _tell_team(biz, user, who, gid, "ask", {"service_id": sid, "place": place.get("name"), "id": a["id"],
                                                "person_name": a.get("name"), "at": a.get("asked_at")})
    return out


def do_ask(biz: str, sid: str, pid: str, slot: Any, cid: str, asker: str) -> Dict[str, Any]:
    """The ask itself, for the office or a team's own leader (sunday_leading)."""
    place = _place_row(biz, pid)
    board = _service_board(biz, sid)
    _serves_gate(board, sid, pid)
    slot = _slot({"slot": slot}, place, board.service.get(sid))
    pick = next((c for c in board.candidates(sid, pid) if c["contact_id"] == cid), None)
    if not pick:
        raise HTTPException(409, "They aren't on this team yet. Add them to the team first.")
    if pick["away"]:
        raise HTTPException(409, f"{pick['name']} is away that Sunday")
    if pick["clash"]:
        raise HTTPException(409, f"{pick['name']} is already on {pick['clash']} at that service")
    row = _put(biz, board, sid, pid, slot, {"contact_id": cid, "status": "asked", "asked_by": asker})
    out = _assignment_out(row, {cid: {"name": pick["name"]}})
    if pick["at_most"] and pick["load"] >= pick["at_most"]:
        out["warning"] = f"That's more than {pick['at_most']} Sundays this month for {pick['name']}"
    return {"assignment": out}


@router.post("/offer")
def offer(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Offer a place to everyone on the team who's trained and free; the
    first yes takes it."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    sid, pid = _uuid(body.get("service_id"), "service"), _uuid(body.get("position_id"), "place")
    place = _place_row(biz, pid)
    gid = str(place["group_id"])
    _place_gate(biz, who, gid, schedule=True)
    out = do_offer(biz, sid, pid, body.get("slot", 1), _asker(biz, user))
    if _borrowed(who, _team_row(biz, gid)["owner"], gid):
        _tell_team(biz, user, who, gid, "offer", {"service_id": sid, "place": place.get("name"),
                                                  "id": out["assignment"]["id"]})
    return out


def do_offer(biz: str, sid: str, pid: str, slot: Any, asker: str) -> Dict[str, Any]:
    place = _place_row(biz, pid)
    board = _service_board(biz, sid)
    _serves_gate(board, sid, pid)
    slot = _slot({"slot": slot}, place, board.service.get(sid))
    row = _put(biz, board, sid, pid, slot, {"contact_id": None, "status": "offered", "asked_by": asker})
    return {"assignment": _assignment_out(row, {})}


def _assignment(biz: str, aid: str) -> Dict[str, Any]:
    rows = _read(f"/serve_assignments?id=eq.{_q(aid)}&business_id=eq.{_q(biz)}&select=*&limit=1")
    if not rows:
        raise HTTPException(404, "That isn't on the schedule anymore")
    return rows[0]


def _asked_gate(biz: str, who: Dict[str, Any], row: Dict[str, Any], schedule: bool = False) -> None:
    """_team_gate for the team an ask is on (its place retired or not)."""
    if not who["office"]:
        return
    places = _read(f"/serve_positions?id=eq.{_q(row['position_id'])}&business_id=eq.{_q(biz)}&select=group_id&limit=1")
    if not places:
        raise HTTPException(404, "That isn't on the schedule anymore")
    _place_gate(biz, who, places[0]["group_id"], schedule)


@router.post("/assignments/{assignment_id}/answer")
def mark_answer(assignment_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Their answer, when they gave it in person or by phone."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    aid = _uuid(assignment_id, "schedule")
    row = _assignment(biz, aid)
    _asked_gate(biz, who, row)
    status_ = body.get("status")
    if status_ not in ("yes", "no"):
        raise HTTPException(400, "The answer is yes or no")
    if row["status"] == "offered":
        raise HTTPException(409, "Nobody has this place yet. Ask someone first.")
    saved = sb_clients.sb_patch_as_service(
        f"/serve_assignments?id=eq.{_q(aid)}&business_id=eq.{_q(biz)}&select=*",
        {"status": status_, "answered_at": _now().isoformat(), "note": str(body.get("note") or "").strip()[:300]})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    cid = str(saved[0]["contact_id"])
    return {"assignment": _assignment_out(saved[0], _people(biz, [cid]))}


@router.delete("/assignments/{assignment_id}")
def take_back(assignment_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    who = _scheduler(biz, user)
    aid = _uuid(assignment_id, "schedule")
    row = _assignment(biz, aid)
    _asked_gate(biz, who, row, schedule=True)
    out = do_take_back(biz, aid)
    if who["office"] and who.get("ops"):
        places = _read(f"/serve_positions?id=eq.{_q(row['position_id'])}&business_id=eq.{_q(biz)}"
                       "&select=group_id,name&limit=1")
        gid = str(places[0]["group_id"]) if places else ""
        if gid and _borrowed(who, _team_row(biz, gid)["owner"], gid):
            _tell_team(biz, user, who, gid, "take_back", {"service_id": str(row["service_id"]),
                                                          "place": places[0].get("name"), "id": aid})
    return out


def do_take_back(biz: str, aid: str) -> Dict[str, Any]:
    _assignment(biz, aid)
    if not sb_clients.sb_delete_as_service(f"/serve_assignments?id=eq.{_q(aid)}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True}


@router.post("/fill")
def fill(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Ask people for every open place in the coming weeks, fairly: only
    someone trained, free that hour and not away, never past their team's
    Sundays a month, and the most rested first. New people learning a place
    are left for a leader to pair with someone. Nothing goes out until the
    next sweep, so the whole fill can be taken back. In a church, only the
    teams this person changes: one asked for (group_id), else every one of
    theirs."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    weeks = body.get("weeks", 4)
    if not isinstance(weeks, int) or isinstance(weeks, bool) or not 1 <= weeks <= MAX_WEEKS:
        raise HTTPException(400, f"Fill 1 to {MAX_WEEKS} weeks")
    only = _uuid(body["group_id"], "team") if body.get("group_id") else None
    owners: Optional[FrozenSet[str]] = None
    if who["office"]:
        if only:
            _place_gate(biz, who, only, schedule=True)
        elif not who["owners"]:
            raise HTTPException(403, _refusal(biz, VOLUNTEERS))
        elif set(who["owners"]) != set(OWNERS):
            owners = who["owners"]
    out = do_fill(biz, weeks, body.get("start"), only, owners=owners)
    if only and out.get("asked") and _borrowed(who, _team_row(biz, only)["owner"], only):
        _tell_team(biz, user, who, only, "fill", {"n": out["asked"], "id": out["ids"][0]})
    return out


def do_fill(biz: str, weeks: int, start: Optional[str], only: Optional[str], asker: str = FILLED_BY,
            owners: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Fill the open places; `owners` keeps it to those owners' teams. The
    board is every team either way, so nobody is asked twice the same hour."""
    board = _Board(biz, start, weeks)
    keep = set(owners) if owners is not None else None
    fresh: List[Dict[str, Any]] = []
    left = 0
    for svc in board.services:
        for team in board.teams:
            if only and team["group_id"] != only:
                continue
            if keep is not None and team["owner"] not in keep:
                continue
            if not serves(svc, team):
                continue
            for place in team["places"]:
                for slot in range(1, sd.needed(svc, place) + 1):
                    if board.holder(svc["id"], place["id"], slot):
                        continue
                    # Never one person on two spots of one place (busy() leaves
                    # the place's own spots out, so it can re-ask for a spot).
                    holding = {str(r.get("contact_id")) for r in board.rows
                               if str(r["service_id"]) == svc["id"] and str(r["position_id"]) == place["id"]
                               and r["status"] in ("asked", "yes")}
                    pick = next((c for c in board.candidates(svc["id"], place["id"])
                                 if c["ok"] and c["trained"] == "trained" and c["contact_id"] not in holding), None)
                    if not pick:
                        left += 1
                        continue
                    row = {"business_id": biz, "service_id": svc["id"], "position_id": place["id"], "slot": slot,
                           "contact_id": pick["contact_id"], "status": "asked", "asked_by": asker,
                           "asked_at": _now().isoformat()}
                    fresh.append(row)
                    # The board learns each ask at once, so the next place
                    # sees this person as busy and their month as fuller.
                    board.rows.append({**row, "id": "pending"})
    ids: List[str] = []
    if fresh:
        saved = sb_clients.sb_post_as_service("/serve_assignments?select=id", fresh)
        if not isinstance(saved, list):
            raise HTTPException(503, "The asks didn't save. Try again.")
        ids = [str(r["id"]) for r in saved]
    return {"asked": len(ids), "still_open": left, "ids": ids}


@router.post("/unfill")
def unfill(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Take back asks that haven't gone out yet (and nobody answered). In a
    church, only asks on the teams this person changes."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    who = _scheduler(biz, user)
    raw = body.get("ids")
    if not isinstance(raw, list) or not raw or len(raw) > 400:
        raise HTTPException(400, "Which asks to take back?")
    ids = [_uuid(i, "schedule") for i in raw]
    if who["office"] and set(who["owners"]) != set(OWNERS):
        extra = set(who.get("leads") or ()) | (_opened(biz) if who.get("ops") else set())
        if not who["owners"] and not extra:
            raise HTTPException(403, _refusal(biz, VOLUNTEERS))
        ids = _asks_on(biz, ids, who["owners"], extra)
    told = _borrowed_unsent(biz, who, ids)
    out = do_unfill(biz, ids)
    for gid, n in told.items():
        _tell_team(biz, user, who, gid, "unfill", {"n": n, "id": ids[0]})
    return out


def _asks_on(biz: str, ids: List[str], owners: Iterable[str], extra: Iterable[str] = ()) -> List[str]:
    """Which of these asks are on the teams of these owners (or these teams)."""
    keep = set(owners)
    teams = {str(t["group_id"]) for t in _serve_rows(f"/serve_teams?business_id=eq.{_q(biz)}", "group_id")
             if t["owner"] in keep} | {str(g) for g in extra}
    out: List[str] = []
    for i in range(0, len(ids), 100):
        rows = _read(f"/serve_assignments?business_id=eq.{_q(biz)}&id=in.({_ids(ids[i:i + 100])})&select=id,position_id")
        pids = sorted({str(r["position_id"]) for r in rows})
        places = {str(p["id"]): str(p["group_id"]) for p in (_read(
            f"/serve_positions?business_id=eq.{_q(biz)}&id=in.({_ids(pids)})&select=id,group_id") if pids else [])}
        out += [str(r["id"]) for r in rows if places.get(str(r["position_id"])) in teams]
    return out


def do_unfill(biz: str, ids: List[str]) -> Dict[str, Any]:
    back = 0
    for i in range(0, len(ids), 100):
        part = _ids(ids[i:i + 100])
        rows = _read(f"/serve_assignments?business_id=eq.{_q(biz)}&id=in.({part})&status=eq.asked"
                     f"&notified_at=is.null&select=id")
        if rows:
            if not sb_clients.sb_delete_as_service(
                    f"/serve_assignments?business_id=eq.{_q(biz)}&id=in.({_ids(r['id'] for r in rows)})"
                    f"&status=eq.asked&notified_at=is.null"):
                raise HTTPException(503, "That didn't save. Try again.")
            back += len(rows)
    return {"taken_back": back}
