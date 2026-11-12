"""church_over.py — who is over whom, at any church (docs/CHURCH_ASSIGNMENTS.md).

Kevin, 2026-11-11: "whatever we are building, this needs to be a way for
churches to set this up in a general sense when they establish leaders over
people." Whoever is over people starts them, hands them work and sees it
move (church_assignments). This module only says who that is, and it reads
it from the church's own data, never from names or title words:

  the office ....... the owner and every Admin are over every office login
                     (the Admin and Manager seats) but their own; a Manager
                     over the lanes (church_duties: oversee_lanes, by the
                     Executive Pastor role's key or the map's
                     office_overseer_roles, or moved to them) is over every
                     other Manager login, never an Admin or the owner
  the ministry ..... where the church's leaders map is open and ready
                     (church_map.opened): whoever a person's active holder
                     row answers to; an active department's overseer over its
                     leader; its leader over the people of what hangs from it
                     (its groups' leaders, its Serve teams' leaders, the
                     holders of its roles), and its overseer over them while
                     it has no leader who leads; walked down, each person
                     once, so a loop ends. The owner and the Admins are over
                     everyone who leads or holds a role. Closed or not ready:
                     the owner, the Admins and a login over the lanes are over
                     everyone, as tasks for leaders work today
  qualifying ....... as church_map.chain_for climbs: someone is over others
                     through a department while they hold an active role with
                     its switch (an overseer can oversee, a leader leads),
                     through answers-to while they hold any active role. The
                     one under them needs nothing
  a person with a login  is their login (an office seat: their work lands in
                     My week), as church_leader_tasks.leaders already keeps
                     them out of the leaders list; and the map never hands
                     anyone a login the office rule doesn't (an Admin's login
                     is only the owner's and the Admins'; a Manager's, also
                     whoever is over the lanes)
  the top .......... the owner's own identity (every one of the church's
                     people with the owner's sign-in email, the owner's
                     person however found): never under anyone, never walked
                     through. A failed read of the owner's email is a 503
  the seniors ...... every holder of a senior-job role (or, where the map
                     names them, of a role that gives the pastor's yes):
                     under the owner only, never walked through, so the owner
                     can hand an elder work and no Admin, Manager or Member
                     seat ever can
  the shepherds .... every holder of an active role that shepherds (its own
                     switch, church_map.can: the church's pastors and elders,
                     never a title word; a role that follows the Ministers
                     setting, by that setting). Kevin, 2026-11-12: "admins can
                     not give work to elders and pastors but they can give
                     them things that is related to their area that they need
                     for them to have" (church_handovers). No office standing
                     is over a shepherd or a senior (an Admin's, a Manager's,
                     the login over the lanes', the closed map's everyone),
                     nor over a login whose person is one: only the owner, or
                     the ministry chain the map says (answers-to, their
                     department's overseer), walked from a login's own
                     person, as anyone's. A leader who doesn't shepherd is
                     as before

    under(ch, me) ..... [{kind, id, name, why}], the office first
    is_over(ch, me, t)  every write checks it
    above(ch, who) .... who a stuck item goes up to: for a Manager login,
                        whoever is over the lanes, else the owner; for a login
                        over the lanes or an Admin, the owner; for a person,
                        the steps a late task already climbs (church_leader_
                        tasks.overseer: church_map.chain_for where the map is
                        open); at the top, the owner. Never yourself

`me` and `who` are {kind: 'login', id: user id} or {kind: 'person', id:
contact id} (a member signed in to the member app). A login's person is its
business_users.contact_id, else the one contact its sign-in email names
(business_users_router.match_contact's rule; the owner's by their Auth email).

A read that fails is a 503, never "nobody is under you". Each table is read
once per Church (one request); church_map.once() keeps the map to one read.

The switch, CHURCH_ASSIGNMENTS (off | owner | on; owner until a Thursday), is
here because every part of the feature asks it: church_open(biz) for the
church (the platform owner's own church with `owner`), office_open(user, biz)
for the office's routes (that, or the platform owner's own login).
"""
from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients
from auth_supabase import AuthedUser

LOGIN, PERSON = "login", "person"
OFFICE_ROLES = ("admin", "manager")
KEEPS_ALL = ("owner", "admin")
OVERSEE = "oversee_lanes"
UNREAD = "Who is over whom couldn't be read just now. Try again."
SEAT_FIELDS = "user_id,role,lane,areas,contact_id,invited_email,name"
EMAILS_PER_READ = 20
IDS_PER_READ = 100
# The owner's sign-in email, kept ten minutes per replica once read (as
# member_asks keeps whether a church is the platform's); a failed read is
# never kept, so the next request asks again.
OWNER_EMAIL_SECONDS = 600
_OWNER_EMAIL: Dict[str, Tuple[float, str]] = {}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_ASSIGNMENTS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    """For this login: on, or (owner) the platform owner's own login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", None) or "").strip().lower() == owner
    return False


def church_open(biz: Any) -> bool:
    """For this church: on, or (owner) the platform owner's own church
    (member_asks.platform_church, as church_team_week.church_open). What the
    sweeps and the readers (My week's days, the team page) follow."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


def office_open(user: AuthedUser, biz: Any) -> bool:
    """The office's routes: the login (open_to) or the church (church_open),
    as church_duties.office_open."""
    return open_to(user) or church_open(biz)


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _first(name: str) -> str:
    return _plain(name).split(" ")[0] or "someone"


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _chunks(ids: Iterable[Any], n: int) -> Iterable[List[str]]:
    ids = sorted({str(i) for i in ids if i})
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def who(kind: str, id_: Any) -> Dict[str, str]:
    return {"kind": kind, "id": str(id_)}


def key(w: Dict[str, Any]) -> str:
    return f"{w['kind']}:{w['id']}"


def parse_for(raw: Any) -> Dict[str, str]:
    """`login:<user id>` or `person:<contact id>`, as the routes take it."""
    kind, _, rest = str(raw or "").partition(":")
    if kind not in (LOGIN, PERSON):
        raise HTTPException(400, "Say who it's for: login:<id> or person:<id>")
    try:
        return who(kind, uuid.UUID(rest.strip()))
    except (ValueError, TypeError):
        raise HTTPException(400, "That person isn't valid")


def same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return a.get("kind") == b.get("kind") and str(a.get("id")) == str(b.get("id"))


# ─── One church, each table read once ─────────────────────────────────

class Church:
    """One church's logins, people and map, each read once and kept for the
    request. Every read that fails is a 503."""

    def __init__(self, business: Dict[str, Any]):
        self.business = business
        self.b = str(business["id"])
        self.owner = str(business.get("owner_id") or "")
        self._memo: Dict[str, Any] = {}

    def _got(self, name: str, fn):
        if name not in self._memo:
            self._memo[name] = fn()
        return self._memo[name]

    # The logins.
    @property
    def seats(self) -> Dict[str, Dict[str, Any]]:
        return self._got("seats", lambda: {
            str(s["user_id"]): s for s in _need(f"/business_users?business_id=eq.{_q(self.b)}&status=eq.active"
                                                f"&select={SEAT_FIELDS}&limit=200") if s.get("user_id")})

    def role(self, uid: Any) -> Optional[str]:
        uid = str(uid or "")
        if uid and uid == self.owner:
            return "owner"
        seat = self.seats.get(uid)
        return seat.get("role") if seat else None

    @property
    def office(self) -> List[str]:
        """The office logins (Admin and Manager seats), never the owner."""
        return [u for u, s in self.seats.items() if s.get("role") in OFFICE_ROLES and u != self.owner]

    def held(self, uid: str) -> FrozenSet[str]:
        """The duties this login holds: church_duties.standing's answer,
        worked out from this church's rows read once (its seats, its moves,
        who is the Executive Pastor) instead of a dozen reads a login. The
        owner and the Admins hold every duty; a Manager its lanes' (or, with
        no lane, its areas'), until a duty moves; never money."""
        import church_duties as cd
        role = self.role(uid)
        if role in KEEPS_ALL:
            return cd.ALL
        if role != "manager":
            return frozenset()
        lanes = set(self.lanes(uid))
        by_area = None if lanes else cd._area_duties(self.b, uid, role)
        return cd._manager_duties(lanes, uid, self.moved, by_area)

    def over_lanes(self, uid: str) -> bool:
        """The owner and the Admins always; a Manager while it does
        oversee_lanes (the same answer church_duties.holds gives)."""
        return OVERSEE in self.held(uid)

    @property
    def exec_users(self) -> Set[str]:
        """The Manager logins whose person holds a role that oversees the
        office (church_duties.overseer_keys: the map's office_overseer_roles,
        else the Executive Pastor role) and said yes: church_duties._exec_users'
        rule, with the logins' people matched in one read."""
        def load() -> Set[str]:
            import church_duties as cd
            keys = set(cd.overseer_keys(self.b))
            ids = {str(h["contact_id"]) for h in self.holders if h.get("role") in keys}
            return {u for u, s in self.seats.items()
                    if s.get("role") == "manager" and self.login_person.get(u) in ids}
        return self._got("exec", load)

    def lanes(self, uid: str) -> List[str]:
        import church_duties as cd
        seat = self.seats.get(uid) or {}
        out: Set[str] = set()
        ln = cd._seat_lane(seat) if seat.get("role") in OFFICE_ROLES else None
        if ln:
            out.add(ln)
        if seat.get("role") == "manager" and uid in self.exec_users:
            out.add(cd.EXEC)
        return sorted(out, key=lambda k: (k != cd.EXEC, cd.LANE_KEYS.index(k) if k in cd.LANE_KEYS else 99))

    @property
    def tz(self):
        """The church's clock: the one every page that judges its week reads
        (church_work_checks.church_zone); a 503 when it can't be read."""
        def load():
            import church_work_checks as cw
            return cw.church_zone(self.business)
        return self._got("tz", load)

    @property
    def moved(self) -> Dict[str, List[str]]:
        import church_duties as cd
        return self._got("moved", lambda: cd._moved(self.b))

    # Who each login is, as one of the church's people.
    @property
    def owner_email(self) -> str:
        """The owner's sign-in email ('' when the account has none). A read
        that fails is a 503, never "the owner is nobody": who the owner is
        decides who is never under anyone."""
        def load() -> str:
            if not self.owner:
                return ""
            hit = _OWNER_EMAIL.get(self.owner)
            if hit and time.monotonic() - hit[0] < OWNER_EMAIL_SECONDS:
                return hit[1]
            import messaging_router
            got = messaging_router.owner_email_read(self.owner)
            if got is None:
                raise HTTPException(503, UNREAD)
            email = got.strip().lower()
            _OWNER_EMAIL[self.owner] = (time.monotonic(), email)
            return email
        return self._got("owner_email", load)

    @property
    def _by_email(self) -> Dict[str, List[Dict[str, Any]]]:
        """The church's people by email, for the owner's and each untied
        seat's sign-in email: one read for them all."""
        def load() -> Dict[str, List[Dict[str, Any]]]:
            emails = {(s.get("invited_email") or "").strip().lower() for s in self.seats.values()
                      if not s.get("contact_id")}
            emails.add(self.owner_email)
            found: Dict[str, List[Dict[str, Any]]] = {}
            for part in _chunks((e for e in emails if "@" in e), EMAILS_PER_READ):
                ors = ",".join(f"email.ilike.{_q(_escape_ilike(e))}" for e in part)
                for c in _need(f"/contacts?business_id=eq.{_q(self.b)}&or=({ors})&select=id,name,email&limit=200"):
                    found.setdefault((c.get("email") or "").strip().lower(), []).append(c)
            return found
        return self._got("by_email", load)

    @property
    def login_person(self) -> Dict[str, str]:
        """user id -> contact id, for the owner and every seat: its tied
        record, else the one person its email names (with several, the one
        whose first name the login gave)."""
        def load() -> Dict[str, str]:
            out = {u: str(s["contact_id"]) for u, s in self.seats.items() if s.get("contact_id")}
            want: Dict[str, Tuple[str, str]] = {}
            for u, s in self.seats.items():
                email = (s.get("invited_email") or "").strip().lower()
                if u not in out and "@" in email:
                    want[u] = (email, _plain(s.get("name")))
            if self.owner and self.owner not in out and "@" in self.owner_email:
                want[self.owner] = (self.owner_email, "")
            found = self._by_email
            for u, (email, name) in want.items():
                rows = found.get(email) or []
                if len(rows) > 1:
                    first = name.split(" ")[0].lower() if name else ""
                    rows = [c for c in rows if first and _plain(c.get("name")).split(" ")[0].lower() == first]
                if len(rows) == 1 and rows[0].get("id"):
                    out[u] = str(rows[0]["id"])
            return out
        return self._got("login_person", load)

    @property
    def person_login(self) -> Dict[str, str]:
        """contact id -> the office login (Admin or Manager seat) that person is."""
        return {c: u for u, c in self.login_person.items() if u in self.office}

    @property
    def owner_person(self) -> Optional[str]:
        return self.login_person.get(self.owner) if self.owner else None

    @property
    def top(self) -> Set[str]:
        """The owner's own identity, never under anyone and never walked
        through: every one of the church's people whose email is the owner's
        sign-in email (a family address too), and the owner's person however
        it was found."""
        def load() -> Set[str]:
            out = {str(c["id"]) for c in self._by_email.get(self.owner_email, []) if c.get("id")} \
                if "@" in self.owner_email else set()
            if self.owner_person:
                out.add(self.owner_person)
            return out
        return self._got("top", load)

    @property
    def seniors(self) -> Set[str]:
        """Under the owner only. This is Claude's decision (2026-11-12, made in
        the #1801 review, round 2), not Kevin's: he hasn't been asked yet.
        Every holder of a role whose job is the senior one (church_roles: the top of
        every chain, a job and never a title) or, where the map names them, of
        a role that gives the pastor's yes (pastor_yes_roles), who isn't the
        owner's own identity. The owner can hand them work and start them; no
        Admin, Manager or Member seat is ever over them, and no walk goes
        through them. At a church whose elders share the top ("Elders
        (Shepherds)"), every elder is one."""
        def load() -> Set[str]:
            import church_roles as cr
            have = {str(d.get("key")) for d in self.defs}
            keys = {str(d.get("key")) for d in self.defs if d.get("job") == "senior" and d.get("key")}
            keys |= {k for k, d in cr.LEGACY.items() if d.get("job") == "senior" and k not in have}
            m = self.map
            if m:
                import church_map
                keys |= set(church_map.picked(m, "pastor_yes_roles") or [])
            return {str(h["contact_id"]) for h in self.holders if h.get("role") in keys} - self.top
        return self._got("seniors", load)

    @property
    def shepherds(self) -> Set[str]:
        """Every holder of an active role that shepherds, who isn't the
        owner's own identity: the role's own switch (church_map.can, the
        map's row, else the role's own or its job's), and a role that
        follows the church's Ministers setting by that setting (read only
        then; a failed read is a 503). Never a title word."""
        def load() -> Set[str]:
            import church_map
            m = self.map or None
            said: Dict[str, Any] = {}
            for h in self.holders:
                k = str(h.get("role") or "")
                if k not in said:
                    d = self.def_of(key_=k)
                    said[k] = church_map.can(m, d)["shepherd"] if d else False
            ministers = False
            if any(v is None for v in said.values()):
                import church_shepherding
                st = church_shepherding.settings(self.b)
                if st is None:
                    raise HTTPException(503, UNREAD)
                ministers = bool(st.get("ministers"))
            keys = {k for k, v in said.items() if v is True or (v is None and ministers)}
            return {str(h["contact_id"]) for h in self.holders if h.get("role") in keys} - self.top
        return self._got("shepherds", load)

    @property
    def guarded(self) -> Set[str]:
        """The people no office standing is over (the shepherds and the
        seniors): only the owner, or the map's own chain."""
        return self.shepherds | self.seniors

    def persons_of(self, me: Dict[str, Any]) -> Set[str]:
        if me["kind"] == PERSON:
            return {str(me["id"])}
        cid = self.login_person.get(str(me["id"]))
        return {cid} if cid else set()

    # The ministry.
    @property
    def map(self):
        """The church's map, or False (closed, or its columns not there)."""
        def load():
            import church_map
            m = church_map.opened(self.business)
            if m is None:
                raise HTTPException(503, UNREAD)
            return m
        return self._got("map", load)

    @property
    def holders(self) -> List[Dict[str, Any]]:
        """Active holder rows, in the library's order."""
        def load():
            rows = _need(f"/church_leader_roles?business_id=eq.{_q(self.b)}&status=eq.active"
                         "&select=contact_id,role,scope,status&limit=2000")
            rank = {d["key"]: n for n, d in enumerate(self.defs)}
            return sorted((r for r in rows if r.get("contact_id")),
                          key=lambda r: rank.get(str(r.get("role") or ""), 999))
        return self._got("holders", load)

    @property
    def defs(self) -> List[Dict[str, Any]]:
        def load():
            import church_roles as cr
            got = cr.defs(self.b)
            if got is None:
                raise HTTPException(503, UNREAD)
            return got
        return self._got("defs", load)

    def def_of(self, *, key_: str = "", id_: str = "") -> Optional[Dict[str, Any]]:
        import church_roles as cr
        if id_:
            return next((d for d in self.defs if str(d.get("id")) == str(id_)), None)
        return next((d for d in self.defs if d.get("key") == key_), None) or cr.LEGACY.get(key_)

    @property
    def groups(self) -> Dict[str, str]:
        return self._got("groups", lambda: {
            str(g["id"]): _plain(g.get("name")) or "A group"
            for g in _need(f"/groups?business_id=eq.{_q(self.b)}&active=eq.true&select=id,name&limit=2000")})

    @property
    def group_leaders(self) -> Dict[str, List[str]]:
        """group id -> who leads it (active groups only)."""
        def load():
            out: Dict[str, List[str]] = {}
            for r in _need(f"/group_members?business_id=eq.{_q(self.b)}&role=eq.leader"
                           "&select=group_id,contact_id&limit=5000"):
                g, c = str(r.get("group_id") or ""), str(r.get("contact_id") or "")
                if g in self.groups and c and c not in out.setdefault(g, []):
                    out[g].append(c)
            return out
        return self._got("group_leaders", load)

    def leads_groups(self, cid: str) -> List[str]:
        return [g for g, people in self.group_leaders.items() if cid in people]

    def qualifies(self, cid: Any, switch: str = "") -> bool:
        import church_map
        m = self.map
        return bool(m) and bool(cid) and church_map.qualifies(m, self.holders, cid, switch)

    # Names.
    def names(self, cids: Iterable[Any]) -> Dict[str, str]:
        have: Dict[str, str] = self._memo.setdefault("names", {})
        want = [c for c in {str(c) for c in cids if c} if c not in have]
        for part in _chunks(want, IDS_PER_READ):
            for r in _need(f"/contacts?business_id=eq.{_q(self.b)}&id=in.({','.join(_q(i) for i in part)})"
                           "&select=id,name&limit=200"):
                have[str(r["id"])] = _plain(r.get("name")) or "Someone"
        return {str(c): have.get(str(c), "Someone") for c in cids if c}

    def login_name(self, uid: str) -> str:
        """A login by its person's name, else the name it gave, else the part
        of its email before the @; never a whole address. The owner by the
        church's own name for them."""
        if uid == self.owner:
            settings = self.business.get("settings") if isinstance(self.business.get("settings"), dict) else {}
            return _plain(settings.get("practitioner_name")) or "The owner"
        seat = self.seats.get(uid) or {}
        cid = self.login_person.get(uid)
        name = self.names([cid]).get(cid, "") if cid else ""
        raw = name if name and name != "Someone" else (_plain(seat.get("name")) or (seat.get("invited_email") or ""))
        raw = _plain(raw)
        return (raw.split("@")[0] or "An office login") if "@" in raw else (raw or "An office login")


# ─── What someone does, in plain words ────────────────────────────────

def _login_why(ch: Church, uid: str) -> str:
    import church_duties as cd
    words = " · ".join(cd.lane_label(k) for k in ch.lanes(uid))
    if words:
        return f"Office · {words}"
    return "Office · Admin" if ch.role(uid) == "admin" else "Office"


def _what(ch: Church, cid: str) -> str:
    """A person by what they do here: their first role in the library's
    order (a team's leader by their team), else the group they lead."""
    for h in ch.holders:
        if str(h.get("contact_id")) == cid:
            d = ch.def_of(key_=str(h.get("role") or "")) or {}
            scope = _plain(h.get("scope"))
            if d.get("covers") == "team" and scope:
                return f"{scope} leader"
            import church_roles as cr
            return d.get("title") or cr.title_of(str(h.get("role") or ""), ch.defs)
    gids = ch.leads_groups(cid)
    if gids:
        return f"Leads {ch.groups[gids[0]]}"
    return "One of the church's people"


# ─── The ministry's steps down ────────────────────────────────────────

def _unit_people(ch: Church, d: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The people of what hangs from a department: its groups' leaders, its
    Serve teams' leaders (a role that covers a team, scoped to it) and the
    holders of its roles."""
    out: List[Tuple[str, str]] = []
    for u in d.get("units") or []:
        kind = u.get("kind")
        if kind == "group":
            for c in ch.group_leaders.get(str(u.get("ref") or ""), []):
                out.append((c, f"Leads {ch.groups.get(str(u['ref']), 'a group')}"))
        elif kind == "serve_option":
            label = _plain(u.get("label"))
            for h in ch.holders:
                hd = ch.def_of(key_=str(h.get("role") or "")) or {}
                if hd.get("covers") == "team" and label and _plain(h.get("scope")).casefold() == label.casefold():
                    out.append((str(h["contact_id"]), f"{label} leader"))
        elif kind == "role":
            rd = ch.def_of(id_=str(u.get("ref") or ""))
            if rd:
                for h in ch.holders:
                    if h.get("role") == rd.get("key"):
                        out.append((str(h["contact_id"]), f"{rd.get('title') or 'A role'} · {d['name']}"))
    return out


def _direct(ch: Church, p: str) -> List[Tuple[str, str]]:
    """Who is directly under person `p` on the map, with why."""
    m = ch.map
    out: List[Tuple[str, str]] = []
    if ch.qualifies(p):
        for x in m.links:
            if x["answers_to_contact_id"] == p and x["contact_id"] != p:
                out.append((x["contact_id"], "answers"))
    for d in m.active():
        lead = d.get("leader_contact_id")
        if d.get("overseer_contact_id") == p and ch.qualifies(p, "oversee"):
            if lead and lead != p:
                out.append((lead, f"Leads {d['name']}"))
            if not (lead and ch.qualifies(lead, "lead")):       # no leader who leads: the overseer is over its people
                out += [(c, w) for c, w in _unit_people(ch, d) if c not in (p, lead)]
        if lead == p and ch.qualifies(p, "lead"):
            out += [(c, w) for c, w in _unit_people(ch, d) if c not in (p, d.get("overseer_contact_id"))]
    return out


def _walk(ch: Church, start: Set[str], stop: Set[str] = frozenset()) -> List[Tuple[str, str, str]]:
    """Every person below `start` on the map, nearest first, each once:
    (person, why, the person they are directly under). Nobody in `stop` (the
    top of every chain) is ever reached, nor anyone only through them."""
    seen = set(start) | set(stop)
    queue = sorted(start)
    out: List[Tuple[str, str, str]] = []
    while queue:
        p = queue.pop(0)
        for t, why in _direct(ch, p):
            if t in seen:
                continue
            seen.add(t)
            out.append((t, why, p))
            queue.append(t)
    return out


def _everyone(ch: Church) -> List[str]:
    """Everyone who leads or holds a role here: holders of an active role,
    the leaders of active groups, and (open map) each active department's
    leader and overseer."""
    ids = [str(h["contact_id"]) for h in ch.holders]
    ids += [c for g in ch.group_leaders.values() for c in g]
    m = ch.map
    if m:
        ids += [p for d in m.active() for p in (d.get("leader_contact_id"), d.get("overseer_contact_id")) if p]
    return list(dict.fromkeys(ids))


# ─── under / is_over / above ──────────────────────────────────────────

def _under(ch: Church, me: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """[(kind, id, why)], the office first, each once, never me."""
    out: Dict[str, Tuple[str, str, str]] = {}
    mine = ch.persons_of(me)

    def add(kind: str, id_: str, why: str) -> None:
        k = f"{kind}:{id_}"
        if k not in out and not (kind == LOGIN and me["kind"] == LOGIN and id_ == str(me["id"])):
            out[k] = (kind, id_, why)

    role = ch.role(me["id"]) if me["kind"] == LOGIN else None
    lanes = me["kind"] == LOGIN and role in ("owner", "admin", "manager") and ch.over_lanes(str(me["id"]))
    # No office standing but the owner's is over a shepherd or a senior, nor
    # over a login whose person is one (Kevin, 2026-11-12: "admins can not
    # give work to elders and pastors"); the map's own chain, walked from my
    # person below, still is.
    guard: Set[str] = ch.guarded if role in OFFICE_ROLES else set()
    lp = ch.login_person if guard else {}
    if role in KEEPS_ALL:
        for uid in ch.office:
            if lp.get(uid) not in guard:
                add(LOGIN, uid, _login_why(ch, uid))
    elif role == "manager" and lanes:
        for uid in ch.office:
            if ch.role(uid) == "manager" and lp.get(uid) not in guard:
                add(LOGIN, uid, _login_why(ch, uid))
    off = ch.person_login
    # The owner's own identity is never under anyone; the senior and the
    # pastor's-yes holders are under the owner only, and no walk goes through
    # either.
    stop = ch.top | ch.seniors
    skip = mine | (ch.top if role == "owner" else stop)
    m = ch.map
    if role in KEEPS_ALL or (not m and lanes):
        for cid in _everyone(ch):
            if cid not in skip and cid not in off and cid not in guard:
                add(PERSON, cid, _what(ch, cid))
        if role == "owner" or not guard:
            return list(out.values())
    if not m or not mine:
        return list(out.values())
    for t, why, via in _walk(ch, mine, stop):
        if t in skip:
            continue
        name = ch.names([via]).get(via, "") if via not in mine else ""
        if why == "answers":
            said = "Answers to you" if via in mine else f"Answers to {_first(name)}"
        else:
            said = why if via in mine else f"{why} · under {_first(name)}"
        if t in off:
            # A person with an office login is their login, and the map never
            # hands anyone a login the office rule doesn't: only the owner or
            # an Admin (who have every login already), or someone over the
            # lanes for a Manager seat. Never an Admin's, never the owner's.
            uid = off[t]
            if uid != ch.owner and (role in KEEPS_ALL or (lanes and ch.role(uid) == "manager")):
                add(LOGIN, uid, said)
        else:
            add(PERSON, t, said)
    return list(out.values())


def under(ch: Church, me: Dict[str, Any]) -> List[Dict[str, str]]:
    """Each one under `me`, by name, with why in plain words."""
    import church_map
    with church_map.once():
        rows = _under(ch, me)
        # Every name in one read: the people, and the logins' own people.
        names = ch.names([i for k, i, _w in rows if k == PERSON] +
                         [ch.login_person.get(i) for k, i, _w in rows if k == LOGIN] + [ch.login_person.get(me["id"])])
        return [{"kind": k, "id": i, "name": ch.login_name(i) if k == LOGIN else names.get(i, "Someone"), "why": w}
                for k, i, w in rows]


def is_over(ch: Church, me: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Whether `me` is over `target` at this church. A read that fails is a
    503, never a yes or a no."""
    if same(me, target):
        return False
    import church_map
    with church_map.once():
        return any(k == target["kind"] and i == str(target["id"]) for k, i, _w in _under(ch, me))


def above(ch: Church, who_: Dict[str, Any]) -> List[Dict[str, str]]:
    """Who a stuck item of `who_`'s goes up to, nearest first, by name; []
    only at the top (the owner)."""
    import church_map
    with church_map.once():
        rows = _above(ch, who_)
        names = ch.names([i for k, i in rows if k == PERSON])
        return [{"kind": k, "id": i, "name": ch.login_name(i) if k == LOGIN else names.get(i, "Someone")}
                for k, i in rows]


def _top(ch: Church, me: Dict[str, Any]) -> List[Tuple[str, str]]:
    if not ch.owner or (me["kind"] == LOGIN and str(me["id"]) == ch.owner):
        return []
    if me["kind"] == PERSON and str(me["id"]) in ch.top:
        return []
    return [(LOGIN, ch.owner)]


def _above(ch: Church, me: Dict[str, Any]) -> List[Tuple[str, str]]:
    if me["kind"] == LOGIN:
        uid = str(me["id"])
        role = ch.role(uid)
        if role == "owner":
            return []
        if role == "manager" and not ch.over_lanes(uid):
            import church_duties as cd
            over = [u for u in cd.manager_holders(ch.b, OVERSEE) if u != uid]
            if over:
                return [(LOGIN, u) for u in over]
        return _top(ch, me)
    cid = str(me["id"])
    if cid in ch.top:
        return []
    if cid in ch.seniors:
        return _top(ch, me)             # under the owner only
    if cid in ch.person_login:
        return _above(ch, who(LOGIN, ch.person_login[cid]))
    import church_follow_up as cfu
    import church_leader_tasks as clt
    import church_roles as cr
    all_roles = cfu.roles(ch.b)
    defs = cr.defs(ch.b)
    if all_roles is None or defs is None:
        raise HTTPException(503, UNREAD)
    eff = cfu._effective_defs(defs, all_roles)
    m = ch.map
    _role, holders = clt.overseer(cid, all_roles, eff, m or None)
    if m and not holders:
        got = clt.group_department(m, ch.b, cid, all_roles, eff)
        if got is None:
            raise HTTPException(503, UNREAD)
        _role, holders = got
    out: List[Tuple[str, str]] = []
    for h in holders or []:
        c = str(h.get("contact_id") or "")
        if not c or c == cid:
            continue
        # The owner's own identity is the owner's login; an office person is
        # their login; anyone else (a senior holder too), their person.
        hit = (LOGIN, ch.owner) if c in ch.top and ch.owner else (
            (LOGIN, ch.person_login[c]) if c in ch.person_login else (PERSON, c))
        if hit not in out:
            out.append(hit)
    return out or _top(ch, me)
