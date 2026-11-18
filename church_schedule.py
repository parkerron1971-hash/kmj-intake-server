"""church_schedule.py — the leaders schedule: who is on it, and asking to be
away (docs/CHURCH_SCHEDULE.md, PRs S1-2 and S1-3).

Kevin, 2026-11-18: "I want to be able to build Leaders schedule. this is for
when leaders are planning time off and have certain obiligations so that we
as a church can plan around meeting ... making sure that everyone is not gone
at the same time on our services." And, shown the five calls the plan rests
on: "Yes build to all five".

A leader asks to be away: planned time off, another commitment, or "I can't
make it". The ask goes to the person over them on the church's own leaders
map (church_over.above), who says yes or not this one. A yes becomes one away
date in serve_away, the table Who serves when already reads, written with the
ask in one transaction (church_away_settle). The reason they gave is private.

    GET  /church/schedule/status?business_id=     who I am here: my person, my
                                                  group, who my asks go to
    GET  /church/schedule/people?business_id=     who is on the schedule
    PUT  /church/schedule/people                  add or take off a name (the
                                                  owner, whoever oversees the
                                                  office)
    GET  /church/schedule/leaders?business_id=&from=&to=
                                                  the calendar, 93 days at most
    GET  /church/schedule/asks?business_id=&box=  mine | to_me | all
    POST /church/schedule/asks                    ask (for yourself; the owner
                                                  and the office overseer for
                                                  anyone on the schedule)
    POST /church/schedule/asks/{id}/answer        yes, or not this one
    POST /church/schedule/asks/{id}/withdraw      take it back
    GET  /church/schedule/settings?business_id=   the notice days
    PUT  /church/schedule/settings                (the owner, whoever oversees
                                                  the office)

Who is on the schedule is read from the church's own data, never a title
word or a role key: everyone who leads something (member_portal_messaging.
leading_people: the leaders of its groups, the holders of a role that leads,
its departments' leaders and overseers) is in `leaders`; an office login's
person who leads nothing is in `office`; then the church's own add list and
remove list (church_schedule_people).

The rules (docs/CHURCH_SCHEDULE.md section 5, step 1):

  who it goes to .... the first person church_over.above gives (decision 1);
                      a person with an office login is routed as that login
  short notice ...... inside the church's notice days (14 unless it says
                      otherwise): flagged, never blocked, the same person
  can't make it ..... nobody decides: settled yes at once, with nobody in
                      decided_by. For the days just ahead only (inside the
                      church's notice days, two days at least): farther out
                      is planned, so it is asked for as time off
  the owner's own ... the one person the owner is (church_over's
                      owner_person): nobody is over them, settled yes at
                      once. Anyone else who shares the owner's sign-in email
                      asks as anyone does, and it goes to the owner
  who answers ....... whoever it went to; in the office app also the owner
                      and whoever oversees the office. Never your own ask,
                      and (the owner aside) never one you entered
  who takes it back . the one who asked; in the office app also the owner
                      and whoever oversees the office
  who changes the ... the owner and whoever oversees the office. Not an
  roster, the days    Admin (decision 7)

Privacy: shape() is the ONE place a reason can leave the server. The asker,
whoever it went to, the owner and whoever oversees the office read it; an
Admin, another leader and the holder of the serve_schedule duty never do.
serve_away.note stays '' (only church_away_settle writes that row). Anything
that shows someone as away reads the fact in serve_away, not an ask's state.

Server-only tables (supabase/APPLY-2026-11-19-church-schedule.sql), read and
written through the service role, always by business_id. A failed read is a
503 (a list that couldn't be read is never empty); a failed write is a 503
with nothing saved. Everything an answer says is read before the write.

Switched by CHURCH_SCHEDULE: off | owner | on, owner when unset (the platform
owner's own church, and the platform owner's own login). Closed, not a
church, or before the migration (ready()): every route answers 404.

Who is told is church_schedule_tell's (S1-4): ask, answer and withdraw hand
it the row once the write is back (_after), never inside the write, and its
hourly sweep tells whatever was missed.

The member app's side is member_portal_dates (S1-5): Dates on the Lead tab,
where `me` is always a person. section() is what its switcher and
member_portal._leads ask: the kept roster and a kept count, never a fresh
read on every page.

Where it meets Who serves when (S1-6; the volunteer schedule is never made to
wait on any of it):

  holds() ........... the scheduler's hook (sunday_planning._Board): the days
                      someone has asked for and still waits on, so nobody
                      asks them to serve then. Who and which days, nothing
                      else. It fails open, on purpose
  takes() ........... whether the Serving Away form asks instead of saving:
                      the church's switch is open and they are on the kept
                      roster. Everyone else's Away is as it always was
  withdraw_fact() ... taking off an away date that came from an ask takes
                      the ask back too (church_away_settle), so no ask is
                      left a yes with nothing behind it
  a yes opens ....... the places they had already agreed to serve inside
                      those days (sunday_serving.open_places), after the
                      write, never inside it, never able to fail it

Not here yet (its own PR): things that repeat.
"""
from __future__ import annotations

import os
import re
import time as clock
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

import business_access
import church_over as co
import sb_clients
from auth_supabase import AuthedUser, UserSession

router = APIRouter(prefix="/church", tags=["church"])

SWITCH = "CHURCH_SCHEDULE"
KINDS = ("time_off", "commitment", "cant")
GROUPS = ("leaders", "office", "volunteers")
ROSTER_GROUPS = ("leaders", "office")          # volunteers come with step 2
GROUP_NAMES = {"leaders": "Leaders", "office": "The office"}
NOTICE_DAYS = 14
NOTICE_MAX = 90
MAX_OPEN = 20              # asks one person can have waiting at once
MAX_DAYS = 366
CANT_FLOOR = 2             # "can't make it" always covers today and tomorrow, whatever the notice days
ROSTER_SECONDS = 60        # the member side's roster, a replica (church_duties.CACHE_SECONDS)
REASON_MAX, NOTE_MAX, COVER_MAX = 500, 300, 80
MINE_DAYS = 90             # my asks: every one still waiting, and the last three months
WINDOW_DAYS = 93           # the calendar shows three months at most
WINDOW_DEFAULT = 62
HOLD_PAGE = 1000           # the scheduler's hold is read a page at a time (never above the project's max-rows)
HOLD_PAGES = 5             # and five pages at most: what the scheduler waits on is bounded, whatever is waiting
READY_SECONDS = 600.0      # the tables, once there, are asked about again in ten minutes
MISSING_SECONDS = 60.0     # not there (or couldn't tell): asked again a minute later
_STATE: Dict[str, Any] = {"yes": None, "at": 0.0}
# Tests pin the answer (conftest: False, so every other suite reads as before
# the migration); production leaves it None and asks the database.
_FORCE: Optional[bool] = None
_KEPT: Dict[str, Tuple[float, "Roster"]] = {}
_WAITING: Dict[str, Tuple[float, Dict[str, int]]] = {}      # church -> (when, {person: asks waiting for their yes})
_OPEN: Dict[str, Tuple[float, bool]] = {}                   # church -> (when, open for it?): _here, under `owner`
_LAST: Dict[str, "Roster"] = {}                             # church -> the last roster this replica read (on_schedule)

FIELDS = ("id,business_id,contact_id,made_by,grp,department_id,kind,starts_on,ends_on,reason,cover_contact_id,"
          "cover_name,to_user_id,to_contact_id,state,flags,decided_by_user_id,decided_by_contact_id,decided_at,"
          "decided_note,withdrawn_at,created_at")
FACT_FIELDS = "id,contact_id,starts_on,ends_on,ask_id,kind,created_at"
NOT_CHURCH = "The leaders schedule is for churches"
UNREAD = "The leaders schedule couldn't be read just now. Try again."
UNSAVED = "That didn't save. Try again."
NO_PERSON = ("This login isn't matched to a person here yet. Ask the owner to match it to your name on the "
             "church's list.")
NOT_ON = "You aren't on the leaders schedule here. The owner, or whoever oversees the office, can add you."
THEY_NOT_ON = "They aren't on the leaders schedule here yet. Add them to it first."
NOT_SETTER = "Only the owner, or whoever oversees the office, changes this."
NOT_FOR = "Only the owner, or whoever oversees the office, asks for someone else."
NOT_ALL = "Only the owner, or whoever oversees the office, sees every ask."
NOT_YOURS = "That isn't one of the asks you can see."
NOT_TO_YOU = "That one isn't yours to answer."
NOT_ASKER = "Only the one who asked, the owner, or whoever oversees the office takes it back."
ALREADY = "That one was already answered."
NO_YES = "That one needs no yes. It settles by itself when they ask for those days again."
MOVED = "That one changed just now. Open it again."
CANT_FAR = ("Can't make it is for the next {n} days. For days farther out, ask for time off instead, so everyone "
            "can plan for it.")
NOT_OPEN = "That one can't be taken back anymore."
WAITING = "Those days are already waiting for an answer."
TOO_MANY = "That's a lot of asks still waiting. Take one back first."
BAD_DAYS = "Pick the days: a year at most, and not in the past."
NOT_PERSON = "That person isn't one of this church's people."
LEFT = "Someone who has left the office"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get(SWITCH) or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    """For this login: on, or (owner) the platform owner's own login, as
    church_over.open_to."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", None) or "").strip().lower() == owner
    return False


def church_open(biz: Any) -> bool:
    """For this church: on, or (owner) the platform owner's own church
    (member_asks.platform_church: kept ten minutes a replica, and a read that
    fails is a no)."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


def office_open(user: AuthedUser, biz: Any) -> bool:
    """The office's routes: the login (open_to) or the church (church_open)."""
    return open_to(user) or church_open(biz)


def _no_table(err: Dict[str, Any]) -> bool:
    """PostgREST saying the table isn't there: Postgres's 42P01, or its own
    "not in the schema cache" (PGRST205, a 404)."""
    code = str(err.get("code") or "")
    return code in ("42P01", "PGRST205") or "42P01" in str(err.get("message") or "") \
        or (err.get("status") == 404 and code.startswith("PGRST"))


def ready() -> bool:
    """True once church_away_asks answers (the migration is one transaction,
    so one table says all of it). serve_dates.ready's rule: only "no such
    table" says it isn't there; a blip keeps the last answer, and with none
    yet reads as not there (the routes answer 404 for a minute, never a 500)."""
    if _FORCE is not None:
        return _FORCE
    if not sb_clients.sb_url():
        return False    # no database to ask (a script)
    now = clock.monotonic()
    yes, at = _STATE["yes"], _STATE["at"]
    if yes is not None and now - at < (READY_SECONDS if yes else MISSING_SECONDS):
        return yes
    try:
        rows = sb_clients.sb_get_as_service("/church_away_asks?select=id&limit=1")
        err = sb_clients.last_error() if rows is None else None
    except Exception:  # noqa: BLE001 — a fake or a broken client is "couldn't tell"
        rows, err = None, None
    if isinstance(rows, list):
        got = True
    elif err and _no_table(err):
        got = False
    else:
        got = bool(yes)
    _STATE["yes"], _STATE["at"] = got, now
    return got


def on(biz: Any) -> bool:
    """What every reader outside the routes asks: open for this church, and
    its tables are there."""
    return church_open(biz) and ready()


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _every(path: str, key: str = "id") -> List[Dict[str, Any]]:
    """Every row, page by page (never the first 1,000 taken for all of
    them). A page that fails is a 503, never a shorter list."""
    try:
        rows = sb_clients.sb_get_all_as_service(path, key=key, strict=True)
    except sb_clients.PartialRead:
        raise HTTPException(503, UNREAD)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _today(ch: co.Church, now: Optional[datetime] = None) -> date:
    """Today on the church's own clock (decision 18)."""
    return (now or _now()).astimezone(ch.tz).date()


def _in(ids: Iterable[Any]) -> str:
    return ",".join(_q(i) for i in ids)


# ─── The gate ─────────────────────────────────────────────────────────

def _church(session: UserSession, biz: Dict[str, Any]) -> co.Church:
    """The church, open to this login: a church (404), the switch (404), the
    tables (404: before the migration nothing here exists)."""
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    if not office_open(session.user, biz) or not ready():
        raise HTTPException(404, "Not Found")
    return co.Church(biz)


def _church_from_body(session: UserSession, body: Dict[str, Any]) -> co.Church:
    """The church a write names in its body: a member seat or above
    (business_access.assert_access), then as _church."""
    bid = _uuid((body or {}).get("business_id"), "church")
    business_access.assert_access(bid, session.user, "member")
    rows = _need(f"/businesses?id=eq.{_q(bid)}&select=id,name,type,owner_id,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return _church(session, rows[0])


def _me(session: UserSession) -> Dict[str, str]:
    return co.who(co.LOGIN, session.user.id)


# ─── Who is who ───────────────────────────────────────────────────────

def office_overseers(ch: co.Church) -> List[str]:
    """The Manager logins that oversee the office today, without the owner
    and the Admins (the answer church_duties.manager_holders gives for
    oversee_lanes), worked out from this church's own rows, read for this
    request: who reads a private reason never lags a duty that moved by the
    minute church_duties keeps its answers."""
    return ch._got("schedule_overseers", lambda: sorted(
        u for u in ch.office if ch.role(u) == "manager" and ch.over_lanes(u)))


def person_of(ch: co.Church, me: Dict[str, Any]) -> Optional[str]:
    """Which of the church's people `me` is: a person is themself; a login,
    the one church_over matched it to (never business_users_router.
    seat_person, which writes). None: a login matched to no one."""
    if me["kind"] == co.PERSON:
        return str(me["id"])
    return ch.login_person.get(str(me["id"]))


def over_all(ch: co.Church, me: Dict[str, Any]) -> bool:
    """The owner's and the office overseer's standing over every ask: an
    office login's only. A member-app session (a person) never carries it,
    whoever that person is (decision 6); nor does an Admin (decision 7)."""
    if me["kind"] != co.LOGIN:
        return False
    uid = str(me["id"])
    return bool(uid) and (uid == ch.owner or uid in office_overseers(ch))


def nearest(ch: co.Church, asker_cid: Any) -> List[Dict[str, str]]:
    """Everyone at the nearest step over this person, in the library's order
    (church_over.above): [{kind, id, name}]. [] only for the one person the
    owner is (Church.owner_person). church_over puts everyone who carries the
    owner's sign-in email at the top (a husband or wife on a family address
    too); here only the owner needs no yes, so anyone else there has the
    owner's login over them, as anyone with nobody else over them does."""
    cid = str(asker_cid or "")
    if ch.owner_person and cid == ch.owner_person:
        return []
    rows = co.above(ch, co.who(co.PERSON, cid))
    if rows:
        return rows
    return [{"kind": co.LOGIN, "id": ch.owner, "name": ch.login_name(ch.owner)}] if ch.owner else []


def goes_to(ch: co.Church, asker_cid: Any) -> Optional[Dict[str, str]]:
    """Who an ask of this person's goes to: the first one at the nearest
    step over them (decision 1: naming every one at that step would widen
    who reads the reason). {kind, id, name}; None only for the one person
    the owner is."""
    rows = nearest(ch, asker_cid)
    return rows[0] if rows else None


def _is_asker(ch: co.Church, me: Dict[str, Any], ask: Dict[str, Any]) -> bool:
    return str(ask.get("contact_id") or "") in ch.persons_of(me)


def _in_office(ch: co.Church, uid: str) -> bool:
    """The owner, or a login on an office seat today (Admin or Manager). An
    ask only ever names a login because it was the office's; one that has
    since moved to another seat, or left, has left the office, and what went
    to it is no longer its own."""
    return bool(uid) and (uid == ch.owner or uid in ch.office)


def _went_to(ch: co.Church, me: Dict[str, Any], ask: Dict[str, Any]) -> bool:
    """Whether this ask went to `me`. A login: it names the login while that
    login is still in the office, or the person the login is; and the owner
    holds one nobody else can answer (both empty, or a login that has left
    the office). A person (the member app): it names them, or the office
    login tied to exactly them."""
    to_user, to_person = str(ask.get("to_user_id") or ""), str(ask.get("to_contact_id") or "")
    live = _in_office(ch, to_user)              # the login it names still holds an office seat
    if me["kind"] == co.PERSON:
        cid = str(me["id"])
        return bool(cid) and (to_person == cid or (live and ch.login_person.get(to_user) == cid))
    uid = str(me["id"])
    if (live and to_user == uid) or (to_person and to_person in ch.persons_of(me)):
        return True
    return not to_person and not live and uid == ch.owner


def needs_no_yes(ch: co.Church, ask: Dict[str, Any]) -> bool:
    """"Can't make it", and the owner's own person's ask: nobody decides
    either. One still waiting is one whose settle failed; nobody answers it,
    and it settles when they ask for those days again."""
    return ask.get("kind") == "cant" or (
        bool(ch.owner_person) and str(ask.get("contact_id") or "") == ch.owner_person)


def may_decide(ch: co.Church, me: Dict[str, Any], ask: Dict[str, Any]) -> bool:
    """Whether `me` may say yes or not this one: it went to them, or (an
    office login) they are the owner or oversee the office. Never your own
    ask, whatever your standing; and never one you entered, the owner aside
    (a login matched to no person could otherwise enter one for its own
    record and say yes to it): whoever oversees the office and enters an ask
    for someone leaves the yes to the one it went to, or the owner."""
    if _is_asker(ch, me, ask):
        return False
    if me["kind"] == co.LOGIN and str(me["id"]) != ch.owner and str(ask.get("made_by") or "") == str(me["id"]):
        return False
    return _went_to(ch, me, ask) or over_all(ch, me)


def sees_reason(ch: co.Church, me: Dict[str, Any], ask: Dict[str, Any]) -> bool:
    """Who reads an ask's reason: the one who asked, whoever it went to, and
    (an office login) the owner and whoever oversees the office. Nobody
    else: not an Admin, not another leader, not the one who keeps Who serves
    when."""
    return _is_asker(ch, me, ask) or _went_to(ch, me, ask) or over_all(ch, me)


def may_withdraw(ch: co.Church, me: Dict[str, Any], ask: Dict[str, Any]) -> bool:
    """The one who asked, or (an office login) the owner or whoever oversees
    the office. Having entered it is not enough: a login that entered one
    and has since lost that standing can't take it back."""
    return _is_asker(ch, me, ask) or over_all(ch, me)


# ─── The church's settings ────────────────────────────────────────────

def settings(ch: co.Church) -> Dict[str, int]:
    """{notice_days}: 14 until the church says otherwise. A failed read is a
    503, never the default taken for the church's own number."""
    rows = _need(f"/church_schedule_settings?business_id=eq.{_q(ch.b)}&select=notice_days&limit=1")
    n = rows[0].get("notice_days") if rows else None
    return {"notice_days": n if isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= NOTICE_MAX
            else NOTICE_DAYS}


def save_settings(ch: co.Church, me: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, int]:
    """The notice days: the owner, or whoever oversees the office (403 for
    anyone else, an Admin too). One row a church, merged."""
    if not over_all(ch, me):
        raise HTTPException(403, NOT_SETTER)
    n = (body or {}).get("notice_days")
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= NOTICE_MAX:
        raise HTTPException(400, f"Notice is a number of days, from 0 to {NOTICE_MAX}")
    saved = sb_clients.sb_post_as_service(
        "/church_schedule_settings?on_conflict=business_id",
        {"business_id": ch.b, "notice_days": n, "updated_by": str(me["id"]), "updated_at": _iso(_now())},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, UNSAVED)
    return {"notice_days": n}


def is_short(ch: co.Church, starts_on: date, today: date, notice_days: Optional[int] = None) -> bool:
    """Short notice: the first day is inside the church's notice days.
    Flagged, never blocked."""
    days = settings(ch)["notice_days"] if notice_days is None else notice_days
    return starts_on < today + timedelta(days=days)


# ─── Who is on the schedule ───────────────────────────────────────────

class Roster:
    """Who is on the leaders schedule at one church. `leaders` and `office`
    are the two groups as they stand (the church's add list in, its remove
    list out); `added` (person -> the group they were added to) and
    `removed` are the church's own lists."""
    __slots__ = ("leaders", "office", "added", "removed")

    def __init__(self, leaders: Set[str], office: Set[str], added: Dict[str, str], removed: Set[str]):
        self.leaders, self.office, self.added, self.removed = leaders, office, added, removed

    def group_of(self, cid: Any) -> Optional[str]:
        cid = str(cid or "")
        return "leaders" if cid in self.leaders else ("office" if cid in self.office else None)

    def people(self) -> Set[str]:
        return self.leaders | self.office


def _roster_of(leads: Set[str], office: Set[str], rows: List[Dict[str, Any]]) -> Roster:
    """The two groups from the church's data, then its own lists. Someone
    who leads something and also has an office login counts in `leaders`
    (decision 2); an add says which group, whatever the data says."""
    added = {str(r["contact_id"]): str(r["grp"]) for r in rows
             if r.get("listed") == "add" and r.get("grp") in ROSTER_GROUPS and r.get("contact_id")}
    removed = {str(r["contact_id"]) for r in rows if r.get("listed") == "remove" and r.get("contact_id")}
    groups = {"leaders": set(leads), "office": set(office) - set(leads)}
    for cid, grp in added.items():
        for g in groups.values():
            g.discard(cid)
        groups[grp].add(cid)
    return Roster(groups["leaders"] - removed, groups["office"] - removed, added, removed)


def _base(ch: co.Church) -> Tuple[Set[str], Set[str], List[Dict[str, Any]]]:
    """What a roster is made from, read for this request: who leads
    something, the office logins' people, and the church's own lists."""
    import church_map
    import member_portal_messaging as mpm
    with church_map.once():
        leads = mpm.leading_people(ch.b)
        if leads is None:
            raise HTTPException(503, UNREAD)
        office = set(ch.person_login)
    rows = _every(f"/church_schedule_people?business_id=eq.{_q(ch.b)}&select=contact_id,listed,grp",
                  key="contact_id")
    return leads, office, [r for r in rows if r.get("contact_id")]


def roster(ch: co.Church) -> Roster:
    """Who is on the leaders schedule, read fresh (the office routes always
    do). A read that fails is a 503, never an empty schedule."""
    return ch._got("schedule_roster", lambda: _roster_of(*_base(ch)))


def _own_row(biz: Any) -> Optional[Dict[str, Any]]:
    """The church's own row (its owner and settings): the one handed in when
    it is whole, else read. None for no such church; a failed read raises."""
    if isinstance(biz, dict) and biz.get("owner_id"):
        return biz
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    rows = _need(f"/businesses?id=eq.{_q(b)}&select=id,name,type,owner_id,settings&limit=1")
    return rows[0] if rows else None


def roster_kept(biz: Any) -> Optional[Roster]:
    """roster(), kept a minute a replica, for the member side (a page view
    is about eleven reads otherwise): an add or a remove on one replica can
    show up to a minute late on another (decision 17). None when it couldn't
    be read, and that is never kept."""
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    now = clock.monotonic()
    # list(): page views ask from many threads at once, and one of them may be adding a church right now.
    for k in [k for k, (at, _r) in list(_KEPT.items()) if now - at >= ROSTER_SECONDS]:
        _KEPT.pop(k, None)
    hit = _KEPT.get(b)
    if hit:
        return hit[1]
    try:
        row = _own_row(biz)
        if row is None:
            return None
        got = _roster_of(*_base(co.Church(row)))
    except HTTPException:
        return None
    _KEPT[b] = (now, got)
    _LAST[b] = got
    return got


def forget(biz: Any) -> None:
    """A roster that changed is read again at once on this replica."""
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    _KEPT.pop(b, None)
    _LAST.pop(b, None)


def waiting_kept(biz: Any) -> Optional[Dict[str, int]]:
    """How many asks wait for each person's yes, as the member app counts
    them: {contact id: n}, kept a minute a replica beside the roster, so the
    Lead tab's switcher (and member_portal._leads, which every page of the
    app asks) costs no read of its own. Exactly waiting()'s rule for a
    person: the ask names them, or the office login tied to exactly them;
    never their own ask, never one that needs no yes. Only who and how many
    is read: never a reason, never a note. None when it couldn't be read,
    and that is never kept. A write on this replica forgets it (_after), so
    the count is right again at once here and within the minute elsewhere."""
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    now = clock.monotonic()
    for k in [k for k, (at, _n) in list(_WAITING.items()) if now - at >= ROSTER_SECONDS]:
        _WAITING.pop(k, None)
    hit = _WAITING.get(b)
    if hit:
        return hit[1]
    try:
        row = _own_row(biz)
        if row is None:
            return None
        ch = co.Church(row)
        rows = _every(f"/church_away_asks?business_id=eq.{_q(b)}&state=eq.asked"
                      "&select=id,business_id,contact_id,kind,state,to_user_id,to_contact_id")
        got: Dict[str, int] = {}
        for r in rows:
            if str(r.get("business_id")) != b or r.get("state") != "asked":
                continue
            to = str(r.get("to_contact_id") or "") or (ch.login_person.get(str(r.get("to_user_id") or "")) or "")
            if not to:
                continue
            me = co.who(co.PERSON, to)
            if _went_to(ch, me, r) and not _is_asker(ch, me, r) and not needs_no_yes(ch, r):
                got[to] = got.get(to, 0) + 1
    except HTTPException:
        return None
    _WAITING[b] = (now, got)
    return got


def forget_waiting(biz: Any) -> None:
    """The kept counts are read again at once on this replica."""
    _WAITING.pop(str(biz.get("id") if isinstance(biz, dict) else biz), None)


def section(biz: Any, cid: Any) -> Optional[Dict[str, int]]:
    """The Lead tab's Dates entry for one of the church's people, in the
    member app: {"waiting": n}, n being the asks waiting for their yes.
    None means no entry at all: the tables aren't there, the switch is
    closed for the church, or they are not on the schedule and nothing
    waits on them (so the app is unchanged for everyone else). Both answers
    come from what is kept a minute a replica (roster_kept, waiting_kept):
    member_portal._leads asks this on every page of the app.

    The tables are asked about first (kept too), so before the migration
    nothing else is read. A roster that couldn't be read is no entry, unless
    something waits on them; a count that couldn't be read is 0. NEVER
    RAISES: every page of the member app waits on this, so whatever goes
    wrong here is one logged line and no entry, never a broken page."""
    try:
        if not ready() or not church_open(biz):
            return None
        cid = str(cid or "")
        if not cid:
            return None
        n = int((waiting_kept(biz) or {}).get(cid, 0))
        if not n:
            r = roster_kept(biz)
            if r is None or cid not in r.people():
                return None
        return {"waiting": n}
    except Exception as e:  # noqa: BLE001 — the tab bar is never worth a 500
        b = str(biz.get("id") if isinstance(biz, dict) else biz)
        print(f"[church_schedule] {b[:8]}: the Dates entry couldn't be worked out ({type(e).__name__})", flush=True)
        return None


# ─── Where it meets Who serves when ───────────────────────────────────

def _here(biz: Any) -> bool:
    """Whether the leaders schedule reaches Who serves when and the Serve
    page at this church, asked the cheap way and in this order: the switch
    (no read), then the tables (kept ten minutes), then the church. Off, or
    before the migration, nothing is read at all, not even whose church it
    is.

    Under `owner` the church's answer is kept a minute a replica WHATEVER IT
    WAS, a lookup that failed included. member_asks.platform_church keeps
    only an answer it could read, and each time it couldn't it asks the
    sign-in service again (which can take ten seconds to say no): the
    volunteer schedule waits on that once a minute a church at most, never
    on every board. A lookup that failed reads as closed, as it always
    has. NEVER RAISES."""
    m = mode()
    if m == "off" or not ready():
        return False
    if m == "on":
        return True
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    now = clock.monotonic()
    # list(): boards are built on many threads at once.
    for k in [k for k, (at, _yes) in list(_OPEN.items()) if now - at >= ROSTER_SECONDS]:
        _OPEN.pop(k, None)
    hit = _OPEN.get(b)
    if hit:
        return hit[1]
    try:
        yes = bool(church_open(b))
    except Exception:  # noqa: BLE001 - closed, as far as can be told; never an error for whoever asked
        yes = False
    _OPEN[b] = (now, yes)
    return yes


def holds(biz_id: Any, lo: Any, hi: Any) -> List[Dict[str, str]]:
    """The scheduler's hook (sunday_planning._Board): the days someone has
    asked to be away and is still waiting on, so Who serves when doesn't ask
    them to serve on a day they have asked for. [{contact_id, starts_on,
    ends_on}] for every ask still `asked` that touches `lo`..`hi` (days).

    Only who and which days. The read never selects the reason, the kind,
    who it went to or anything else of the ask's, so the board has nothing
    to say but "away", in the words it already uses.

    FAILS OPEN, ON PURPOSE (decision 12), AND NEVER RAISES: [] when the
    switch is off, the tables aren't there, the switch is closed for this
    church, or the read failed for any reason at all. The other choice is
    Who serves when failing, for every church and every volunteer, whenever
    this one table blips. The worst that failing open does is that someone
    whose ask still waits is asked to serve that day, which is what happens
    today; they say no, and their ask is still answered.

    It costs nothing where there is nothing to hold: the switch (no read),
    then the tables (kept ten minutes), then the church (kept) are asked
    first (_here), so off, before the migration, or closed for the church no
    read is made here. Open, it is one read, a page at a time (HOLD_PAGE
    rows, HOLD_PAGES pages at most: what the scheduler waits on is bounded,
    and past that it holds the ones it read)."""
    try:
        if not _here(biz_id):
            return []
        b = str(biz_id.get("id") if isinstance(biz_id, dict) else biz_id)
        a, z = _day(lo), _day(hi)
        if not b or not a or not z or z < a:
            return []
        path = (f"/church_away_asks?business_id=eq.{_q(b)}&state=eq.asked&starts_on=lte.{z.isoformat()}"
                f"&ends_on=gte.{a.isoformat()}&select=id,business_id,contact_id,starts_on,ends_on,state"
                f"&order=id.asc&limit={HOLD_PAGE}")
        rows: List[Dict[str, Any]] = []
        after: Optional[str] = None
        for _page in range(HOLD_PAGES):
            page = sb_clients.sb_get_as_service(path + (f"&id=gt.{_q(after)}" if after else ""))
            if not isinstance(page, list):
                return []                       # a page that failed: nobody is held, and nothing is half-read
            rows += page
            if len(page) < HOLD_PAGE:
                break
            after = str(page[-1].get("id") or "")
            if not after:
                break
        out = []
        for r in rows:
            s, e = str(r.get("starts_on") or "")[:10], str(r.get("ends_on") or "")[:10]
            if (str(r.get("business_id")) == b and r.get("state") == "asked" and r.get("contact_id")
                    and s <= z.isoformat() and e >= a.isoformat()):
                out.append({"contact_id": str(r["contact_id"]), "starts_on": s, "ends_on": e})
        return out
    except Exception as e:  # noqa: BLE001 — the volunteer schedule is never worth failing for this
        print(f"[church_schedule] the scheduler's hold couldn't be read ({type(e).__name__}); nobody is held",
              flush=True)
        return []


def on_schedule(biz: Any, cid: Any) -> Optional[bool]:
    """Whether one of the church's people is on its leaders schedule, as the
    member app asks it: from the roster kept a minute a replica (decision
    17), never a fresh read on a page. False: the switch is off or closed
    for the church, its tables aren't there (asked first, so nothing else is
    read before the migration), or they aren't on it. None: the switch is
    open and the roster couldn't be read, so it can't be told. NEVER RAISES.
    A page shows its leaders' part only on True; a write asks takes().

    When the minute is up and the roster can't be read again, the last one
    this replica read answers (_LAST), however old: a blip never stands
    between a volunteer and their Away. "Couldn't tell" is left for a
    replica that has never once read this church's roster."""
    try:
        if not _here(biz):
            return False
    except Exception:  # noqa: BLE001 — closed, as far as can be told
        return False
    cid = str(cid or "")
    if not cid:
        return False
    try:
        r = roster_kept(biz)
    except Exception:  # noqa: BLE001
        r = None
    if r is None:
        r = _LAST.get(str(biz.get("id") if isinstance(biz, dict) else biz))
    return None if r is None else cid in r.people()


def takes(biz: Any, cid: Any) -> bool:
    """Whether this person's Away on the Serve page is asked for (through
    ask(), with all its rules) instead of saved at once: the church's switch
    is open and they are on its leaders schedule (on_schedule). False for
    everyone else, with no read where the switch is closed or before the
    migration: a volunteer's Away is exactly what it always was.

    Where the switch is open and the roster couldn't be read, it can't be
    told who is asking, and guessing "a volunteer" would hand a leader an
    away date nobody said yes to: a 503 ("try again"), nothing saved."""
    got = on_schedule(biz, cid)
    if got is None:
        raise HTTPException(503, UNREAD)
    return got


def department_of(ch: co.Church, cid: Any) -> Optional[Dict[str, Any]]:
    """The active department this person is in on the church's map: one
    they lead, else one they oversee, else the one something of theirs hangs
    from (a group they lead, a team they lead, a role they hold). None with
    the map closed, or for someone in none."""
    cid = str(cid or "")
    m = ch.map
    if not m or not cid:
        return None
    depts = m.active()
    for column in ("leader_contact_id", "overseer_contact_id"):
        for d in depts:
            if d.get(column) == cid:
                return d
    for d in depts:
        if any(c == cid for c, _why in co._unit_people(ch, d)):
            return d
    return None


def _dept(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    return {"id": str(d["id"]), "name": _plain(d.get("name")) or "A department"} if d else None


def _person(ch: co.Church, cid: str) -> str:
    """One of this church's own people, by name; a 400 for anyone else's."""
    rows = _need(f"/contacts?business_id=eq.{_q(ch.b)}&id=eq.{_q(cid)}&select=id,name&limit=1")
    if not rows:
        raise HTTPException(400, NOT_PERSON)
    name = _plain(rows[0].get("name")) or "Someone"
    ch._memo.setdefault("names", {})[cid] = name
    return name


def _people_view(ch: co.Church, r: Roster, can_change: bool) -> Dict[str, Any]:
    names = ch.names(sorted(r.people() | set(r.added) | r.removed))
    logins = ch.person_login

    def one(cid: str, grp: str) -> Dict[str, Any]:
        uid = logins.get(cid)
        return {"contact_id": cid, "name": names.get(cid, "Someone"),
                "what": co._login_why(ch, uid) if grp == "office" and uid else co._what(ch, cid),
                "department": _dept(department_of(ch, cid))}

    def by_name(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(rows, key=lambda x: (x["name"].casefold(), x["contact_id"]))

    return {"leaders": by_name([one(c, "leaders") for c in r.leaders]),
            "office": by_name([one(c, "office") for c in r.office]),
            "added": by_name([{"contact_id": c, "name": names.get(c, "Someone"), "group": g}
                              for c, g in r.added.items()]),
            "removed": by_name([{"contact_id": c, "name": names.get(c, "Someone")} for c in r.removed]),
            "can_change": can_change}


def people(ch: co.Church, me: Dict[str, Any]) -> Dict[str, Any]:
    """Who is on the schedule, by name, with what they do here. For a login
    whose own person is on it, and for the owner, an Admin and whoever
    oversees the office (403 for anyone else). `can_change`: the owner and
    the office overseer only."""
    import church_map
    with church_map.once():
        r = roster(ch)
        over = over_all(ch, me)
        admin = me["kind"] == co.LOGIN and ch.role(str(me["id"])) in co.KEEPS_ALL
        if not (over or admin or (ch.persons_of(me) & r.people())):
            raise HTTPException(403, NOT_ON)
        return _people_view(ch, r, over)


def set_listed(ch: co.Church, me: Dict[str, Any], contact_id: Any, listed: Any, grp: Any = None) -> Dict[str, Any]:
    """Add a name (to `leaders`, or to `office`), take one off, or (None)
    put them back to what the church's data says. The owner, or whoever
    oversees the office: an Admin gets a 403 (decision 7). The answer (the
    schedule as it stands after) is worked out before the write, so a read
    that fails is a 503 with nothing saved; a failed write is a 503 too."""
    if not over_all(ch, me):
        raise HTTPException(403, NOT_SETTER)
    cid = _uuid(contact_id, "person")
    if listed not in ("add", "remove", None):
        raise HTTPException(400, "Say add, remove, or nothing to put them back")
    grp = None if listed != "add" else (grp or "leaders")
    if listed == "add" and grp not in ROSTER_GROUPS:
        raise HTTPException(400, "Add them to the leaders or to the office")
    import church_map
    with church_map.once():
        _person(ch, cid)
        leads, office, rows = _base(ch)
        rows = [r for r in rows if str(r["contact_id"]) != cid]
        if listed:
            rows.append({"contact_id": cid, "listed": listed, "grp": grp})
        after = _roster_of(leads, office, rows)
        view = _people_view(ch, after, True)
    if listed:
        saved = sb_clients.sb_post_as_service(
            "/church_schedule_people?on_conflict=business_id,contact_id",
            {"business_id": ch.b, "contact_id": cid, "listed": listed, "grp": grp, "set_by": str(me["id"]),
             "updated_at": _iso(_now())},
            prefer="resolution=merge-duplicates,return=representation")
        if not isinstance(saved, list) or not saved:
            raise HTTPException(503, UNSAVED)
    elif not sb_clients.sb_delete_as_service(
            f"/church_schedule_people?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}"):
        raise HTTPException(503, UNSAVED)
    ch._memo["schedule_roster"] = after
    forget(ch.b)
    return view


# ─── One ask, as the app shows it ─────────────────────────────────────

def _names(ch: co.Church, rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Every name these asks say, read together: the people (who asked, who
    covers, who it went to, who answered), the logins, the departments."""
    rows = list(rows)
    logins = {str(r[k]) for r in rows for k in ("to_user_id", "decided_by_user_id") if r.get(k)}
    logins = {u for u in logins if u == ch.owner or u in ch.seats}
    people = ch.names([r.get(k) for r in rows for k in ("contact_id", "cover_contact_id", "to_contact_id",
                                                         "decided_by_contact_id")]
                      + [ch.login_person.get(u) for u in logins])
    depts: Dict[str, str] = {}
    if any(r.get("department_id") for r in rows):
        m = ch.map
        depts = {str(d["id"]): _plain(d.get("name")) or "A department" for d in (m.departments if m else [])}
    return {"people": people, "logins": {u: ch.login_name(u) for u in logins}, "depts": depts}


def _prime(ch: co.Church, me: Dict[str, Any]) -> None:
    """Before a write: read what shape() asks of the church (who `me` is,
    who oversees the office), so nothing after the write can fail on a read
    and answer 503 for something that saved (church_assignments._ready)."""
    _ = (ch.persons_of(me), over_all(ch, me), ch.seats, ch.owner_person)


def shape(ch: co.Church, me: Dict[str, Any], row: Dict[str, Any], names: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """One ask as `me` may see it. THE ONE PLACE A REASON LEAVES THE SERVER:
    `reason` is None unless sees_reason, and `reason_hidden` then says one
    was given. The note that came with the answer is kept to the same
    people (it can say why). Never fails on a read once `names` and _prime
    are done: it answers writes that already saved."""
    people, logins = names.get("people") or {}, names.get("logins") or {}
    sees = sees_reason(ch, me, row)
    reason = str(row.get("reason") or "").strip() or None
    state = str(row.get("state") or "")
    to: Optional[Dict[str, str]] = None
    if row.get("to_user_id"):
        u = str(row["to_user_id"])
        to = {"kind": co.LOGIN, "id": u, "name": logins.get(u) or LEFT}
    elif row.get("to_contact_id"):
        c = str(row["to_contact_id"])
        to = {"kind": co.PERSON, "id": c, "name": people.get(c, "Someone")}
    cover: Optional[Dict[str, Any]] = None
    if row.get("cover_contact_id"):
        c = str(row["cover_contact_id"])
        cover = {"contact_id": c, "name": people.get(c, "Someone")}
    elif _plain(row.get("cover_name")):
        cover = {"contact_id": None, "name": _plain(row.get("cover_name"))}
    decided: Optional[Dict[str, Any]] = None
    if row.get("decided_at"):
        by = (logins.get(str(row.get("decided_by_user_id") or ""))
              or people.get(str(row.get("decided_by_contact_id") or "")) or None)
        decided = {"by": by, "at": row.get("decided_at"), "note": (row.get("decided_note") or None) if sees else None}
    did = str(row.get("department_id") or "")
    return {
        "id": str(row["id"]) if row.get("id") else None, "contact_id": str(row.get("contact_id")),
        "name": people.get(str(row.get("contact_id")), "Someone"), "group": row.get("grp"),
        "department": {"id": did, "name": (names.get("depts") or {}).get(did, "A department")} if did else None,
        "kind": row.get("kind"), "starts_on": str(row.get("starts_on") or "")[:10],
        "ends_on": str(row.get("ends_on") or "")[:10], "state": state, "flags": list(row.get("flags") or []),
        "to": to, "cover": cover, "decided": decided,
        "reason": reason if sees else None, "reason_hidden": bool(reason) and not sees,
        "mine": _is_asker(ch, me, row),
        "can_answer": state == "asked" and not needs_no_yes(ch, row) and may_decide(ch, me, row),
        "can_withdraw": state in ("asked", "yes") and may_withdraw(ch, me, row),
        "created_at": row.get("created_at"),
    }


def _fact(ch: co.Church, me: Dict[str, Any], f: Dict[str, Any], grp: Optional[str],
          names: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """An away date with no ask behind it (added the way it always was): the
    ask's own keys, with `id` and `kind` empty. It never had a reason."""
    out = shape(ch, me, {"contact_id": f.get("contact_id"), "grp": grp, "starts_on": f.get("starts_on"),
                         "ends_on": f.get("ends_on"), "state": "yes", "created_at": f.get("created_at")}, names)
    # Nothing here to take back: it comes off where it was added (Serving, Away).
    return dict(out, can_withdraw=False)


# ─── Asking ───────────────────────────────────────────────────────────

def _reason(v: Any) -> Optional[str]:
    s = str(v or "").replace("\r\n", "\n").strip()
    if len(s) > REASON_MAX:
        raise HTTPException(400, f"Keep the reason to {REASON_MAX} letters")
    return s or None


def _note(v: Any) -> Optional[str]:
    s = str(v or "").replace("\r\n", "\n").strip()
    if len(s) > NOTE_MAX:
        raise HTTPException(400, f"Keep the note to {NOTE_MAX} letters")
    return s or None


def _settle(ch: co.Church, ask_id: Any, state: str, *, by_user: Optional[str] = None,
            by_contact: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
    """One decision in one transaction (church_away_settle): the ask's
    state, and its away date made (yes) or taken off (withdrawn). {changed,
    ask}. A call that fails, or that finds no such ask, is a 503."""
    got = sb_clients.sb_post_as_service("/rpc/church_away_settle", {
        "p_business_id": ch.b, "p_ask_id": str(ask_id), "p_state": state, "p_by_user": by_user,
        "p_by_contact": by_contact, "p_note": note}, redact=True)     # a refusal's body can echo the row: never logged
    if not isinstance(got, dict) or not isinstance(got.get("ask"), dict):
        raise HTTPException(503, UNSAVED)
    return got


def _has_fact(ch: co.Church, ask_id: Any) -> bool:
    return bool(_need(f"/serve_away?business_id=eq.{_q(ch.b)}&ask_id=eq.{_q(ask_id)}&select=id&limit=1"))


def _settled(ch: co.Church, cid: str, kind: str, a: date, b: date) -> Optional[Dict[str, Any]]:
    """This person's ask for exactly these days and this kind that already
    settled with nobody deciding, its away date still there: the same press
    landing twice."""
    for r in _need(f"/church_away_asks?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}&state=eq.yes"
                   f"&kind=eq.{kind}&starts_on=eq.{a.isoformat()}&ends_on=eq.{b.isoformat()}"
                   f"&decided_by_user_id=is.null&decided_by_contact_id=is.null&select={FIELDS}&limit=5"):
        if _has_fact(ch, r["id"]):
            return r
    return None


def _take_back(ch: co.Church, ask_id: str) -> None:
    """Remove an ask that is still waiting for a yes it doesn't need. If
    this fails too, asking again finds it and finishes it."""
    if not sb_clients.sb_delete_as_service(
            f"/church_away_asks?id=eq.{_q(ask_id)}&business_id=eq.{_q(ch.b)}&state=eq.asked"):
        print(f"[church_schedule] {ch.b[:8]}: an ask that didn't settle wasn't taken back", flush=True)


def _after(what: str, ch: co.Church, row: Dict[str, Any], **kw: Any) -> None:
    """Hand a notice to church_schedule_tell once the write has landed: off
    this request (member_push._later, a thread of its own), on a Church of
    its own (this request's is still answering), and never able to fail the
    write it follows: anything that goes wrong here is logged and dropped
    (the hourly sweep tells an ask or an answer that was missed; a take-back
    is not tried again). `what` is one of church_schedule_tell's tell_new,
    tell_answer, tell_withdrawn. The row is handed over whole;
    church_schedule_tell keeps only what a notice may say (never the reason,
    never the note). The kept counts for the member app's switcher are
    forgotten here too: every write that changes what waits passes through."""
    forget_waiting(ch.b)
    try:
        import member_push
        biz, row = dict(ch.business), dict(row)

        def run() -> None:
            import church_schedule_tell as tell
            getattr(tell, what)(co.Church(biz), row, **kw)

        member_push._later(run)
    except Exception:  # noqa: BLE001 — a notice is never worth failing the write it is about
        print(f"[church_schedule] {ch.b[:8]}: a notice wasn't handed on ({what})", flush=True)


def _serving(ch: co.Church, cid: str, a: date, b: date, now: Optional[datetime]) -> bool:
    """Whether they have already said yes to serve on a day inside these
    (the ask's `serving` flag): a yes will open those places. A flag and
    nothing more, so a read that fails here says no and is logged, and
    never costs anyone their ask (sickness is never blocked by a blip in
    Who serves when). _open_places reads for itself when the yes comes."""
    try:
        import sunday_serving
        return bool(sunday_serving.yes_places(ch.b, cid, a, b, now=now or _now()))
    except Exception as e:  # noqa: BLE001
        print(f"[church_schedule] {ch.b[:8]}: couldn't tell whether they serve on those days ({type(e).__name__})",
              flush=True)
        return False


def _open_places(ch: co.Church, row: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """A yes to someone who had already said yes to serve inside those days
    (decision 10): each of those places is opened again, the way
    sunday_serving.cant_make_it opens one, so whoever schedules that team
    sees the gap instead of a yes from someone who is away. What the team
    sees is the board's own words for it ("Can't make it · Away"): never
    that there was an ask, its kind, its reason or who said yes.

    AFTER THE WRITE, NEVER INSIDE IT, and never able to fail it: the yes and
    its away date are already saved (church_away_settle), so whatever goes
    wrong here is one logged line and the yes stands. Only a place still a
    yes, on a day still to come, is touched, so doing it twice changes
    nothing. Answers with how many were opened."""
    try:
        import sunday_serving
        return sunday_serving.open_places(ch.b, str(row.get("contact_id") or ""), row.get("starts_on"),
                                          row.get("ends_on"), now=now or _now())
    except Exception as e:  # noqa: BLE001 — the yes is saved; this never takes it back
        print(f"[church_schedule] {ch.b[:8]}: a yes was saved, but the places they had agreed to serve "
              f"weren't opened ({type(e).__name__})", flush=True)
        return 0


def ask(ch: co.Church, me: Dict[str, Any], body: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The one write of an ask. Everything is read before it: who it is for
    and their group, the days against the church's clock and its notice
    days, what is already waiting, who it goes to, and every name the answer
    says (church_assignments._ready's rule: a read that fails is a 503 with
    nothing saved).

    For yourself; `for` (person:<id>) only by the owner or whoever oversees
    the office. "Can't make it" (for the days just ahead: inside the church's
    notice days, two days at least), and the owner's own person, need no
    yes: the ask is saved and settled yes at once, with nobody in
    decided_by. If that second step fails the ask is taken back and the
    answer is a 503; asking again finds whatever was left and finishes it,
    and two presses at once end as one ask and one away date, never a second
    copy."""
    body = body or {}
    kind = str(body.get("kind") or "")
    if kind not in KINDS:
        raise HTTPException(400, "Say what it is: time off, another commitment, or can't make it")
    a, b = _day(body.get("starts_on")), _day(body.get("ends_on") or body.get("starts_on"))
    if not a or not b:
        raise HTTPException(400, BAD_DAYS)
    reason = _reason(body.get("reason"))
    cover_id = _uuid(body["cover_contact_id"], "person") if body.get("cover_contact_id") else None
    cover_name = None if cover_id else (_plain(body.get("cover_name")) or None)
    if cover_name and len(cover_name) > COVER_MAX:
        raise HTTPException(400, f"Keep who covers to {COVER_MAX} letters")
    import church_map
    with church_map.once():
        if body.get("for") not in (None, ""):
            if not over_all(ch, me):
                raise HTTPException(403, NOT_FOR)
            target = co.parse_for(body["for"])
            if target["kind"] != co.PERSON:
                raise HTTPException(400, "Say who it's for by their name on the church's list")
            cid = target["id"]
            _person(ch, cid)
            not_on = HTTPException(400, THEY_NOT_ON)
        else:
            cid = person_of(ch, me) or ""
            if not cid:
                raise HTTPException(409, NO_PERSON)
            not_on = HTTPException(403, NOT_ON)
        grp = roster(ch).group_of(cid)
        if not grp:
            raise not_on
        today = _today(ch, now)
        if b < a or b < today or (b - a).days > MAX_DAYS:
            raise HTTPException(400, BAD_DAYS)
        if cover_id:
            if cover_id == cid:
                raise HTTPException(400, "Someone else covers, not the one who is away")
            _person(ch, cover_id)
        notice = settings(ch)["notice_days"]
        near = max(notice, CANT_FLOOR)
        if kind == "cant" and a >= today + timedelta(days=near):
            raise HTTPException(400, CANT_FAR.format(n=near))    # farther out is planned: it is asked for
        top = bool(ch.owner_person) and cid == ch.owner_person    # the one person the owner is: nobody is over them
        instant = kind == "cant" or top
        open_ = _need(f"/church_away_asks?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}&state=eq.asked"
                      f"&select=id,kind,starts_on,ends_on&limit={MAX_OPEN + 30}")
        same = next((r for r in open_ if str(r.get("starts_on"))[:10] == a.isoformat()
                     and str(r.get("ends_on"))[:10] == b.isoformat()), None)
        left: Optional[str] = None             # one a failed settle left behind: finish it
        if same and instant and same.get("kind") == kind:
            left = str(same["id"])
        elif same:
            raise HTTPException(409, WAITING)
        elif not instant and len(open_) >= MAX_OPEN:    # one that needs no yes never waits, so it is never one too many
            raise HTTPException(400, TOO_MANY)
        # One that did settle, though its answer was lost on the way back.
        done = _settled(ch, cid, kind, a, b) if instant else None
        to = None if top else goes_to(ch, cid)
        flags = ["short_notice"] if not top and is_short(ch, a, today, notice) else []
        if _serving(ch, cid, a, b, now):
            flags.append("serving")             # they already said yes to serve one of the days: a yes opens it
        dept = department_of(ch, cid)
        row = {"business_id": ch.b, "contact_id": cid, "made_by": str(me["id"]) if me["kind"] == co.LOGIN else None,
               "grp": grp, "department_id": str(dept["id"]) if dept else None, "kind": kind,
               "starts_on": a.isoformat(), "ends_on": b.isoformat(), "reason": reason,
               "cover_contact_id": cover_id, "cover_name": cover_name,
               "to_user_id": to["id"] if to and to["kind"] == co.LOGIN else None,
               "to_contact_id": to["id"] if to and to["kind"] == co.PERSON else None, "flags": flags}
        names = _names(ch, [row] + ([done] if done else []))
        _prime(ch, me)
    if done:
        if left:
            _take_back(ch, left)                # a leftover beside the one that settled
        _open_places(ch, done, now)             # and so may this have been (a place already opened is left alone)
        _after("tell_new", ch, done)            # its own answer was lost, so its notice may have been too (told once)
        return shape(ch, me, done, names)
    if left:
        saved_id = left
    else:
        # redact: a refusal's body ("Failing row contains ...") would put the reason in the log.
        saved = sb_clients.sb_post_as_service("/church_away_asks", row, redact=True)
        if not isinstance(saved, list) or not saved or not saved[0].get("id"):
            # Two presses at once: the table keeps one waiting ask for the same days.
            if str((sb_clients.last_error() or {}).get("code") or "") == "23505":
                raise HTTPException(409, WAITING)
            raise HTTPException(503, UNSAVED)
        if not instant:
            _after("tell_new", ch, saved[0])    # whoever it went to hears, once the write is back
            return shape(ch, me, saved[0], names)
        saved_id = str(saved[0]["id"])
    twin: Optional[Dict[str, Any]] = None
    try:
        if not left:
            # Two presses at once: the table keeps one WAITING ask for the same
            # days, so once the other press has settled this insert goes in
            # too. Look again before settling: the other one stands, and this
            # one goes.
            twin = _settled(ch, cid, kind, a, b)
            if twin:
                names = _names(ch, [twin])
        got = None if twin else _settle(ch, saved_id, "yes")
    except HTTPException:
        _take_back(ch, saved_id)                # nothing is left waiting for a yes it doesn't need
        raise
    if twin:
        _take_back(ch, saved_id)
        return shape(ch, me, twin, names)
    if not got.get("changed"):
        raise HTTPException(409, MOVED)         # it moved under us (taken back, say): never "saved" as it stands
    _open_places(ch, got["ask"], now)           # it is a yes now: the places they had agreed to serve are open again
    _after("tell_new", ch, got["ask"])          # "can't make it": whoever is over them hears at once
    return shape(ch, me, got["ask"], names)


def _ask(ch: co.Church, ask_id: Any) -> Dict[str, Any]:
    """One of this church's asks; a 404 for anything else."""
    aid = _uuid(ask_id, "ask")
    rows = _need(f"/church_away_asks?id=eq.{_q(aid)}&business_id=eq.{_q(ch.b)}&select={FIELDS}&limit=1")
    if not rows or str(rows[0].get("business_id")) != ch.b:
        raise HTTPException(404, NOT_YOURS)
    return rows[0]


def answer(ch: co.Church, me: Dict[str, Any], ask_id: Any, yes: Any, note: Any = None) -> Dict[str, Any]:
    """Yes, or not this one (with a note, 300 letters at most): whoever it
    went to; in the office app also the owner and whoever oversees the
    office (403 for anyone else, for your own ask, and for one you entered
    unless you are the owner). The database decides it in one transaction,
    so two answers at once land one after the other and the second is a 409,
    as is an answer after a withdraw. One that needs no yes (a "can't make
    it" left waiting by a failed settle) is never answered: a 409."""
    if not isinstance(yes, bool):
        raise HTTPException(400, "Say yes, or not this one")
    note = _note(note)
    row = _ask(ch, ask_id)
    import church_map
    with church_map.once():
        if not may_decide(ch, me, row):
            raise HTTPException(403, NOT_TO_YOU)
        if row.get("state") != "asked":
            raise HTTPException(409, ALREADY)
        if needs_no_yes(ch, row):
            raise HTTPException(409, NO_YES)
        by = {"by_user": str(me["id"])} if me["kind"] == co.LOGIN else {"by_contact": str(me["id"])}
        names = _names(ch, [dict(row, decided_by_user_id=by.get("by_user"),
                                 decided_by_contact_id=by.get("by_contact"))])
        _prime(ch, me)
    got = _settle(ch, row["id"], "yes" if yes else "no", note=note, **by)
    if not got.get("changed"):
        raise HTTPException(409, ALREADY)
    if yes:
        _open_places(ch, got["ask"])            # after the write, never inside it, never able to fail it
    _after("tell_answer", ch, got["ask"])       # the one who asked hears the answer
    return shape(ch, me, got["ask"], names)


def withdraw(ch: co.Church, me: Dict[str, Any], ask_id: Any) -> Dict[str, Any]:
    """Take an ask back: the one who asked, or (an office login) the owner
    or whoever oversees the office (403 for anyone else). One still waiting,
    or one already said yes to (its away date goes with it); anything else
    is a 409."""
    row = _ask(ch, ask_id)
    import church_map
    with church_map.once():
        if not may_withdraw(ch, me, row):
            raise HTTPException(403, NOT_ASKER)
        if row.get("state") not in ("asked", "yes"):
            raise HTTPException(409, NOT_OPEN)
        names = _names(ch, [row])
        _prime(ch, me)
    got = _settle(ch, row["id"], "withdrawn")
    if not got.get("changed"):
        raise HTTPException(409, NOT_OPEN)
    _after("tell_withdrawn", ch, got["ask"], by=dict(me))
    return shape(ch, me, got["ask"], names)


def withdraw_fact(biz: Any, cid: Any, away_id: Any) -> bool:
    """Taking an away date off on the Serve page (sunday_serving.drop_away),
    when that date came from an ask: the ask is taken back through
    church_away_settle, which removes the date in the same transaction, so
    no ask is left a yes with nothing behind it and no date is left without
    its ask being settled. It goes through withdraw() as the person
    themself, so its rules hold (only the one who asked) and whoever it went
    to is told as for any take-back (church_schedule_tell).

    True: it was one of ours and it is done; the caller deletes nothing.
    False: not ours to do, and the caller removes the date exactly as it
    always did: the switch is off or closed for the church or its tables
    aren't there (no read is made then), there is no such date of theirs, it
    is a plain away date (no ask), or its ask is gone or already settled (a
    date left behind by one is a plain date now). A read or a write that
    fails is a 503 with nothing removed: never the date without its ask."""
    if not _here(biz):
        return False
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    cid = str(cid or "")
    rows = _need(f"/serve_away?id=eq.{_q(away_id)}&business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}"
                 f"&select=id,ask_id&limit=1")
    ask_id = rows[0].get("ask_id") if rows else None
    if not ask_id:
        return False
    row = _own_row(biz)
    if row is None:
        raise HTTPException(503, UNREAD)
    try:
        withdraw(co.Church(row), co.who(co.PERSON, cid), ask_id)
    except HTTPException as e:
        if e.status_code in (404, 409):
            return False                        # no such ask anymore, or it was already settled: a plain date now
        raise
    return True


# ─── Lists ────────────────────────────────────────────────────────────

def _shaped(ch: co.Church, me: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [r for r in rows if str(r.get("business_id")) == ch.b]
    names = _names(ch, rows)
    return [shape(ch, me, r, names) for r in rows]


def _open_first(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = sorted(rows, key=lambda r: str(r.get("starts_on") or ""), reverse=True)
    return sorted(rows, key=lambda r: r.get("state") != "asked")


def mine(ch: co.Church, me: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """My asks: every one still waiting, then the last three months', newest
    first. A login matched to no person has none."""
    cid = person_of(ch, me)
    if not cid:
        return []
    since = (_today(ch, now) - timedelta(days=MINE_DAYS)).isoformat()
    rows = _need(f"/church_away_asks?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}"
                 f"&or=(state.eq.asked,ends_on.gte.{since})&select={FIELDS}&order=starts_on.desc&limit=200")
    return _shaped(ch, me, _open_first([r for r in rows if str(r.get("contact_id")) == cid]))


def waiting(ch: co.Church, me: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The asks waiting for my yes: the ones that went to me, soonest first.
    (The owner and the office overseer may answer any; `everything` lists
    those.)"""
    rows = _every(f"/church_away_asks?business_id=eq.{_q(ch.b)}&state=eq.asked&select={FIELDS}")
    import church_map
    with church_map.once():
        rows = [r for r in rows if r.get("state") == "asked" and _went_to(ch, me, r) and not _is_asker(ch, me, r)
                and not needs_no_yes(ch, r)]
        return _shaped(ch, me, sorted(rows, key=lambda r: (str(r.get("starts_on") or ""), str(r.get("id")))))


def everything(ch: co.Church, me: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every ask at this church, waiting first, then the last three months':
    the owner and whoever oversees the office only (403 for anyone else)."""
    import church_map
    with church_map.once():
        if not over_all(ch, me):
            raise HTTPException(403, NOT_ALL)
        since = (_today(ch, now) - timedelta(days=MINE_DAYS)).isoformat()
        rows = _every(f"/church_away_asks?business_id=eq.{_q(ch.b)}&or=(state.eq.asked,ends_on.gte.{since})"
                      f"&select={FIELDS}")
        return _shaped(ch, me, _open_first(rows))


def _by_day(x: Dict[str, Any]) -> Tuple[str, str, str]:
    return (x["starts_on"], x["name"].casefold(), x["contact_id"])


def calendar(ch: co.Church, me: Dict[str, Any], lo: date, hi: date) -> Dict[str, Any]:
    """Who is away from `lo` to `hi`, by group: {from, to, groups: [{key,
    name, people, away, waiting, standing}]}.

    For someone on the schedule, and for the owner and whoever oversees the
    office (403 for anyone else: the one who keeps Who serves when sees this
    only when they are on the schedule themselves). `away` is read from the
    facts (serve_away), never from an ask's state: each with its ask through
    shape() (name, days, who covers; a reason only for those who may read
    it), or as a plain away date. `waiting` holds only the asks `me` may
    read (their own, the ones that went to them, and for the owner and the
    office overseer every one): a waiting ask is nobody else's to see.
    `standing` (things that repeat) comes with its own PR."""
    if hi < lo or (hi - lo).days > WINDOW_DAYS:
        raise HTTPException(400, "Pick up to three months")
    import church_map
    with church_map.once():
        r = roster(ch)
        on_it = r.people()
        if not (over_all(ch, me) or (ch.persons_of(me) & on_it)):
            raise HTTPException(403, NOT_ON)
        window = f"&ends_on=gte.{lo.isoformat()}&starts_on=lte.{hi.isoformat()}"
        facts: List[Dict[str, Any]] = []
        for part in co._chunks(on_it, co.IDS_PER_READ):
            facts += _every(f"/serve_away?business_id=eq.{_q(ch.b)}&contact_id=in.({_in(part)}){window}"
                            f"&select={FACT_FIELDS}")
        facts = [f for f in facts if str(f.get("contact_id")) in on_it]
        asks: Dict[str, Dict[str, Any]] = {}
        for part in co._chunks((f.get("ask_id") for f in facts), co.IDS_PER_READ):
            for a in _need(f"/church_away_asks?business_id=eq.{_q(ch.b)}&id=in.({_in(part)})&select={FIELDS}"
                           f"&limit={co.IDS_PER_READ}"):
                if str(a.get("business_id")) == ch.b:
                    asks[str(a["id"])] = a
        held = [a for a in _every(f"/church_away_asks?business_id=eq.{_q(ch.b)}&state=eq.asked{window}"
                                  f"&select={FIELDS}")
                if str(a.get("business_id")) == ch.b and a.get("state") == "asked"
                and str(a.get("contact_id")) in on_it and sees_reason(ch, me, a)]
        names = _names(ch, list(asks.values()) + held + [{"contact_id": f.get("contact_id")} for f in facts])
        groups = []
        for key in ROSTER_GROUPS:
            away = []
            for f in facts:
                cid = str(f.get("contact_id"))
                if r.group_of(cid) != key:
                    continue
                a = asks.get(str(f.get("ask_id") or ""))
                # The days are the fact's own: it is what the scheduler reads.
                away.append(shape(ch, me, dict(a, starts_on=f.get("starts_on"), ends_on=f.get("ends_on")), names)
                            if a and str(a.get("contact_id")) == cid else _fact(ch, me, f, key, names))
            asked = [shape(ch, me, a, names) for a in held if r.group_of(a.get("contact_id")) == key]
            groups.append({"key": key, "name": GROUP_NAMES[key],
                           "people": len(r.leaders if key == "leaders" else r.office),
                           "away": sorted(away, key=_by_day), "waiting": sorted(asked, key=_by_day), "standing": []})
    return {"from": lo.isoformat(), "to": hi.isoformat(), "groups": groups}


def status(ch: co.Church, me: Dict[str, Any]) -> Dict[str, Any]:
    """Who I am on the schedule: my person (None: this login is matched to
    no one, and the screen asks them to pick their record), my group, who my
    asks go to, and whether I see every ask and set the church's numbers."""
    import church_map
    with church_map.once():
        cid = person_of(ch, me)
        grp = roster(ch).group_of(cid) if cid else None
        over = over_all(ch, me)
        return {"open": True,
                "me": {"person": cid, "group": grp,
                       "goes_to": goes_to(ch, cid) if cid and grp else None,
                       "sees_all": over, "can_set": over},
                "owner_how": ch.owner_how, "notice_days": settings(ch)["notice_days"]}


# ─── The routes ───────────────────────────────────────────────────────

@router.get("/schedule/status")
def schedule_status(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                    biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Who I am on the leaders schedule here. Any seat."""
    ch = _church(session, biz)
    return status(ch, _me(session))


@router.get("/schedule/people")
def schedule_people(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                    biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Who is on the schedule: the two groups, and the church's own add and
    remove lists."""
    ch = _church(session, biz)
    return people(ch, _me(session))


@router.put("/schedule/people")
def schedule_people_set(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Add a name, take one off, or put them back. Answers with the schedule
    as it stands after."""
    ch = _church_from_body(session, body or {})
    body = body or {}
    return set_listed(ch, _me(session), body.get("contact_id"), body.get("listed"), body.get("group"))


@router.get("/schedule/leaders")
def schedule_leaders(business_id: str, start: Optional[str] = Query(None, alias="from"),
                     end: Optional[str] = Query(None, alias="to"),
                     session: UserSession = Depends(sb_clients.authed_request),
                     biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """The leaders calendar: who is away, by group, three months at most
    (from today for two months when no days are named)."""
    ch = _church(session, biz)
    lo = _day(start) if start else _today(ch)
    try:
        hi = _day(end) if end else (lo + timedelta(days=WINDOW_DEFAULT) if lo else None)
    except OverflowError:                       # a first day at the very end of the calendar
        hi = None
    if not lo or not hi:
        raise HTTPException(400, "A day is like 2026-11-20")
    return calendar(ch, _me(session), lo, hi)


@router.get("/schedule/asks")
def schedule_asks(business_id: str, box: str = "mine", session: UserSession = Depends(sb_clients.authed_request),
                  biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """`mine`: my asks. `to_me`: the ones waiting for my yes. `all`: every
    ask, for the owner and whoever oversees the office."""
    ch = _church(session, biz)
    if box not in ("mine", "to_me", "all"):
        raise HTTPException(400, "Pick mine, to_me or all")
    me = _me(session)
    return {"asks": mine(ch, me) if box == "mine" else (waiting(ch, me) if box == "to_me" else everything(ch, me))}


@router.post("/schedule/asks")
def schedule_ask(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Ask to be away. Answers with what it saved."""
    ch = _church_from_body(session, body or {})
    return {"saved": ask(ch, _me(session), body or {})}


@router.post("/schedule/asks/{ask_id}/answer")
def schedule_answer(ask_id: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Yes, or not this one. A 409 when it had already moved."""
    ch = _church_from_body(session, body or {})
    body = body or {}
    return {"saved": answer(ch, _me(session), ask_id, body.get("yes"), body.get("note"))}


@router.post("/schedule/asks/{ask_id}/withdraw")
def schedule_withdraw(ask_id: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Take an ask back."""
    ch = _church_from_body(session, body or {})
    return {"saved": withdraw(ch, _me(session), ask_id)}


@router.get("/schedule/settings")
def schedule_settings(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                      biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """The notice days: for someone on the schedule, the owner and whoever
    oversees the office."""
    ch = _church(session, biz)
    me = _me(session)
    import church_map
    with church_map.once():
        if not (over_all(ch, me) or (ch.persons_of(me) & roster(ch).people())):
            raise HTTPException(403, NOT_ON)
    return settings(ch)


@router.put("/schedule/settings")
def schedule_settings_set(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Set the notice days."""
    ch = _church_from_body(session, body or {})
    return save_settings(ch, _me(session), body or {})
