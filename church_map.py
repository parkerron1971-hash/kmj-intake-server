"""church_map.py — the church leaders map, read core (docs/CHURCH_LEADERS_MAP.md §3).

Kevin, 2026-11-03: show how elders, pastors and ministry leaders connect to
the admins, the lead pastor and the people, for every church that subscribes;
"what i don't want is what i build works for love city but is broken and
messed up for other churches." Every church runs on one engine, and each
church's structure is data (supabase/APPLY-2026-11-04-church-map.sql).

    the switch ...... CHURCH_MAP = off | owner | on (default owner):
                      open_to(user) opens the office's routes to a login,
                      church_open(biz) the engine (sweeps, the member side)
                      to a church
    ready() ......... the migration's columns answer
    load(biz) ....... a church's map: its roles' switches, who a holder
                      answers to, its settings, its departments and what
                      hangs from each. None on a failed read, never empty
    opened(biz) ..... what a reader takes: False (closed, or not ready),
                      else load(biz)
    can(m, role) .... a role's seven switches; made_for(m, role) its streams
    picked(m, k) .... the roles a setting names (PR 7: who gives the pastor's
                      yes, who oversees the office); None = today's rule
    chain_for(...) .. who hears, step by step up from a person (PR 6): their
                      department's overseer, the item's department's leader
                      then overseer, the person they answer to, then
                      church_roles.chain_above, today's chain
    team_head(...) .. who a Serve sign-up for a team with no leader goes to:
                      its department's leader, else its overseer
    propose(biz) .... a read-only draft of departments, step 2's hook
    the writes ...... save_department, archive_department, set_answers_to,
                      save_settings (PR 5; church_map_router's routes): each
                      checks what it names against the church's own rows
                      and answers with what it saved, never with success on
                      a failed write (503)
    view(biz) ....... the office's map, with its gaps

Every reader takes it in this order (§3): closed, or not ready, runs today's
code; open and ready, the map decides wherever it knows, then the role's
switches, then today's rule; open and ready but load() failed, the caller
does what it does today on a failed read. The switches decide who shepherds
(church_shepherding.role_rows), choose's tie-break (church_follow_up) and
the leaders room (member_portal_messaging); church_roles writes them once
ready(). chain_for is who a late item, a drifting family or a waiting
prayer goes up to (Shepherding, the follow-up and prayer sweeps, the
shepherd signals, leader tasks).

Server-only tables, read through the service role, always by business_id.
"""
from __future__ import annotations

import contextvars
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

import church_roles as cr
import sb_clients
from auth_supabase import AuthedUser

ROLE_COLS = "id,key,job,status,handles," + ",".join(cr.SWITCHES) + ",made_for"
LINK_COLS = "id,contact_id,role,status,answers_to_contact_id"
SETTINGS_COLS = "pastor_from_cents,board_over_cents,pastor_yes_roles,office_overseer_roles,map_by,map_at"
DEPT_COLS = ("id,name,leader_contact_id,overseer_contact_id,support_duty,area,status,source,sort,updated_by,"
             "updated_at")
UNIT_COLS = "id,department_id,kind,group_id,role_id,board_id,worship_ministry_id,label"
# A unit's thing, by kind; the other kinds (a serve option, a space, a check line) are its label.
UNIT_REF = {"group": "group_id", "role": "role_id", "board": "board_id", "worship_ministry": "worship_ministry_id"}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_MAP") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    """The office's map routes (PR 5), for this login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


def church_open(biz: Any) -> bool:
    """The engine and the member side, for this church: on, or (owner) the
    platform owner's own church. Nobody signs in there as a login."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(biz.get("id") if isinstance(biz, dict) else biz)
    return False


# ─── Ready ────────────────────────────────────────────────────────────

_READY: Dict[str, bool] = {}


def ready() -> bool:
    """Whether the migration's columns answer: one probe, remembered for the
    process once they do (the file is one transaction, so one table's columns
    say all of it). False on any error, and asked again next time."""
    if _READY.get("ok"):
        return True
    try:
        rows = sb_clients.sb_get_as_service(f"/church_role_defs?select={','.join(cr.SWITCHES)},made_for&limit=1")
    except Exception:
        return False
    if isinstance(rows, list):
        _READY["ok"] = True
        return True
    return False


# ─── The map ──────────────────────────────────────────────────────────

@dataclass
class Map:
    """One church's map. `roles`: role id -> its key, job, handles, switches
    and made_for. `links`: active holder rows that name who they answer to.
    `settings`: the church's levels and role picks (None = today's platform
    rule). `departments`: draft and active, each with its `units`."""
    business_id: str
    roles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    links: List[Dict[str, Any]] = field(default_factory=list)
    settings: Dict[str, Any] = field(default_factory=dict)
    departments: List[Dict[str, Any]] = field(default_factory=list)

    def active(self) -> List[Dict[str, Any]]:
        return [d for d in self.departments if d["status"] == "active"]

    def answers_to(self, contact_id: str, role: str = "") -> Optional[str]:
        """The person this holder answers to, for `role` (or any role they hold)."""
        return next((x["answers_to_contact_id"] for x in self.links
                     if x["contact_id"] == str(contact_id) and (not role or x["role"] == role)), None)

    def led_by(self, contact_id: str) -> List[Dict[str, Any]]:
        return [d for d in self.active() if d["leader_contact_id"] == str(contact_id)]

    def overseen_by(self, contact_id: str) -> List[Dict[str, Any]]:
        return [d for d in self.active() if d["overseer_contact_id"] == str(contact_id)]

    def department_of(self, kind: str, ref: Any) -> Optional[Dict[str, Any]]:
        """The active department a group, role, board, worship ministry, serve
        option, space or check line hangs from (a thing hangs from one)."""
        want = str(ref or "") if kind in UNIT_REF else str(ref or "").strip().casefold()
        for d in self.active():
            for u in d["units"]:
                if u["kind"] == kind and (u["ref"] if kind in UNIT_REF else u["label"].strip().casefold()) == want:
                    return d
        return None


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _bid(biz: Any) -> str:
    return str(biz.get("id") if isinstance(biz, dict) else biz)


def role_switches(biz: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    """Each active or draft role's switches, by role id; None when the read
    failed. Its own read: church_roles.defs's select never names the new
    columns, so it can't fail before the migration."""
    rows = _rows(f"/church_role_defs?business_id=eq.{_q(_bid(biz))}&status=in.(active,draft)"
                 f"&select={ROLE_COLS}&limit=300")
    if rows is None:
        return None
    return {str(r["id"]): {"key": r.get("key"), "job": r.get("job"), "status": r.get("status"),
                           "handles": list(r.get("handles") or []),
                           **{k: r.get(k) for k in cr.SWITCHES}, "made_for": list(r.get("made_for") or [])}
            for r in rows}


def _unit(u: Dict[str, Any]) -> Dict[str, Any]:
    ref = u.get(UNIT_REF[u["kind"]]) if u.get("kind") in UNIT_REF else None
    return {"id": str(u["id"]), "kind": u.get("kind"), "ref": str(ref) if ref else "", "label": u.get("label") or ""}


def _dept(d: Dict[str, Any], units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {**{k: d.get(k) for k in DEPT_COLS.split(",")}, "id": str(d["id"]),
            "leader_contact_id": str(d["leader_contact_id"]) if d.get("leader_contact_id") else None,
            "overseer_contact_id": str(d["overseer_contact_id"]) if d.get("overseer_contact_id") else None,
            "status": d.get("status") or "active", "units": units}


def load(biz: Any) -> Optional[Map]:
    """The church's map, from five reads of its own. None when any failed:
    a caller stops as it does today on a failed read, and never takes an
    empty map for one that says nothing. Call it once ready()."""
    bid = _bid(biz)
    q = _q(bid)
    roles = role_switches(bid)
    links = _rows(f"/church_leader_roles?business_id=eq.{q}&answers_to_contact_id=not.is.null"
                  f"&select={LINK_COLS}&limit=1000")
    st = _rows(f"/church_role_settings?business_id=eq.{q}&select={SETTINGS_COLS}&limit=1")
    depts = _rows(f"/church_departments?business_id=eq.{q}&status=neq.archived&select={DEPT_COLS}"
                  "&order=sort.asc,name.asc&limit=200")
    units = _rows(f"/church_department_units?business_id=eq.{q}&select={UNIT_COLS}&limit=1000")
    if roles is None or links is None or st is None or depts is None or units is None:
        return None
    under: Dict[str, List[Dict[str, Any]]] = {}
    for u in units:
        under.setdefault(str(u.get("department_id")), []).append(_unit(u))
    return Map(
        business_id=bid, roles=roles,
        links=[{"id": str(x["id"]), "contact_id": str(x["contact_id"]), "role": str(x.get("role") or ""),
                "answers_to_contact_id": str(x["answers_to_contact_id"])}
               for x in links if x.get("status") == "active" and x.get("answers_to_contact_id")],
        settings={k: (st[0] if st else {}).get(k) for k in SETTINGS_COLS.split(",")},
        departments=[_dept(d, under.get(str(d["id"]), [])) for d in depts])


def state() -> Optional[bool]:
    """ready(), told apart from a blip: True when the map's columns answer;
    False when the table answers but its new columns don't (the migration
    isn't applied, so today's code is right); None when the probe itself
    failed, and nothing can be said either way."""
    if ready():
        return True
    try:
        base = sb_clients.sb_get_as_service("/church_role_defs?select=id&limit=1")
    except Exception:
        return None
    return False if isinstance(base, list) else None


_ONCE: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar("church_map_once", default=None)


@contextmanager
def once():
    """Inside this block opened(biz) reads each church's map once, and every
    reader gets that answer: a caller that asks about many logins
    (church_duties.holders_of, whose standing() reads overseer_keys for each
    Manager seat) loads it once, not once a login (#1717 review). A block
    inside another shares the outer one."""
    if _ONCE.get() is not None:
        yield
        return
    token = _ONCE.set({})
    try:
        yield
    finally:
        _ONCE.reset(token)


def opened(biz: Any) -> "Map | None | bool":
    """What a reader takes, in §3's order: False where the map is closed for
    this church or its columns aren't there (today's code runs as it is);
    else load(biz): the Map, or None when a read failed (a failed probe
    included), and the caller then does what it does today on a failed
    read, never today's people. A blip after a restart must not send an
    open church back to the title rules for a moment (#1714 review). Inside
    once(), each church's answer is read once."""
    memo, bid = _ONCE.get(), _bid(biz)
    if memo is not None and bid in memo:
        return memo[bid]
    got = _open(biz)
    if memo is not None:
        memo[bid] = got
    return got


def _open(biz: Any) -> "Map | None | bool":
    if not church_open(biz):
        return False
    s = state()
    if s is None:
        return None
    if s is False:
        return False
    return load(biz)


# ─── A role's switches ────────────────────────────────────────────────

def _row(m: Optional[Map], d: Dict[str, Any]) -> Dict[str, Any]:
    """Where a role's switches are read: the map's row for it; else a legacy
    role's catalog row (church_follow_up._effective_defs), or a row that
    carries its own; else its job's."""
    rid = str(d.get("id") or "")
    row = m.roles.get(rid) if m else None
    if row is None and rid.startswith("legacy:"):
        row = cr.LEGACY.get(str(d.get("key") or ""))
    if row is None and "can_lead" in d:
        row = d
    if row is None:
        row = cr.JOBS.get(str(d.get("job") or ""), cr.JOBS["office"])["switches"]
    return row


def _handles(row: Dict[str, Any], d: Dict[str, Any]) -> List[str]:
    return d.get("handles") if d.get("handles") is not None else (row.get("handles") or [])


def made_for(m: Optional[Map], d: Dict[str, Any]) -> List[str]:
    """The streams a role is the one made for (choose's tie-break where the
    map is open), always among its handles."""
    row = _row(m, d)
    return [s for s in _handles(row, d) if s in (row.get("made_for") or [])]


def can(m: Optional[Map], d: Dict[str, Any], *, ministers: Optional[bool] = None) -> Dict[str, Any]:
    """A role's seven switches: shepherd (None = it follows the church's
    Ministers setting; given `ministers`, that setting), oversee, lead,
    board_yes, see_all, and prayer and care, which are its handles (it takes
    shared prayer requests, care needs), bounded by its job. Read as _row
    says."""
    row = _row(m, d)
    handles = _handles(row, d)
    shepherd = row.get("can_shepherd")
    if shepherd is None and ministers is not None:
        shepherd = bool(ministers)
    return {"shepherd": shepherd, "oversee": bool(row.get("can_oversee")), "lead": bool(row.get("can_lead")),
            "board_yes": bool(row.get("can_board_yes")), "see_all": bool(row.get("can_see_all")),
            "prayer": "prayer_shared" in handles, "care": "care_need" in handles}


def picked(m: Map, setting: str) -> Optional[List[str]]:
    """The keys of the church's active roles a role pick names
    (pastor_yes_roles, office_overseer_roles: PR 7), sorted; [] when it
    names none still active, which each reader takes as "none named"; None
    when the church never set it, so today's rule stands (§2)."""
    ids = m.settings.get(setting)
    if ids is None:
        return None
    rows = (m.roles.get(str(i)) for i in ids)
    return sorted({str(r["key"]) for r in rows if r and r.get("status") == "active" and r.get("key")})


_SAYS = (("oversee", "can oversee a department"), ("lead", "leads (the leaders room)"),
         ("board_yes", "gives the board’s yes on money"), ("see_all", "sees everything"))


def says(m: Optional[Map], d: Dict[str, Any]) -> str:
    """A role's switches as Chief reads them, in a sentence."""
    c = can(m, d)
    words = ({True: ["shepherds families"], None: ["shepherds families when the church’s Ministers setting is on"]}
             .get(c["shepherd"], []) + [w for k, w in _SAYS if c[k]])
    made = (m.roles.get(str(d.get("id") or "")) or {}).get("made_for") if m else []
    if made:
        words.append("first in line for: " + "; ".join(cr.STREAMS[s] for s in made if s in cr.STREAMS))
    return "Switches: " + (", ".join(words) if words else "none")


# ─── The person chain (PR 6) ──────────────────────────────────────────

CHAIN_MAX = 12      # map steps; naming each person once already ends every walk


def _step(depts: List[Dict[str, Any]], who: str, people: int, seat_role: Dict[str, Any]) -> Dict[str, Any]:
    """A department step, shaped like a role so a caller reads its title and
    job as it reads chain_above's: "Youth overseer"."""
    names = list(dict.fromkeys(d["name"] for d in depts))
    return {"id": f"department:{depts[0]['id']}:{who}", "key": "", "job": seat_role.get("job") or "",
            "title": f"{' and '.join(names)} {who}{'s' if people > 1 else ''}", "department_id": depts[0]["id"]}


def _ranked(defs: List[Dict[str, Any]], holders: Dict[str, List[Dict[str, Any]]]) -> tuple:
    """(role key -> role, every holder row in the library's order)."""
    rank = {d["key"]: n for n, d in enumerate(defs)}
    return ({d["key"]: d for d in defs},
            sorted((h for hs in holders.values() for h in hs), key=lambda h: rank.get(str(h.get("role") or ""), 999)))


def _seat(m: Map, by: Dict[str, Dict[str, Any]], rows: List[Dict[str, Any]], cid: str,
          switch: str = "") -> Optional[tuple]:
    """(their role, their holder row): the first active role, in the
    library's order, this person holds with `switch` on; None when none."""
    for h in rows:
        d = by.get(str(h.get("role") or ""))
        if cid and str(h["contact_id"]) == cid and d and d.get("status", "active") == "active" \
                and (not switch or can(m, d)[switch]):
            return d, h
    return None


def team_head(m: Map, defs: List[Dict[str, Any]], holders: Dict[str, List[Dict[str, Any]]],
              team: str) -> Optional[tuple]:
    """Who a Serve sign-up goes to when its team has no leader of its own and
    its Serve option hangs from an active department: that department's
    leader while they hold an active role that leads, else its overseer while
    they hold one that oversees (decision 1). (step, holder row), the step
    shaped as chain_for's ("Youth leader"). None when the team hangs from no
    active department or neither person qualifies: today's rule goes on."""
    d = m.department_of("serve_option", team) if team else None
    if not d:
        return None
    by, rows = _ranked(defs, holders)
    for who, switch in (("leader", "lead"), ("overseer", "oversee")):
        s = _seat(m, by, rows, str(d[f"{who}_contact_id"] or ""), switch)
        if s:
            return _step([d], who, 1, s[0]), s[1]
    return None


def chain_for(m: Map, defs: List[Dict[str, Any]], holders: Dict[str, List[Dict[str, Any]]], person: Any,
              role: Optional[Dict[str, Any]], *, team: str = "", group_id: Any = None,
              skip: Iterable[Any] = ()) -> List[tuple]:
    """Who hears, nearest first, up from `person` holding `role` for an item
    (its team, its group), in chain_above's shape: (step, [holder rows]),
    where a step is a role, or a department step (_step), or the role the
    answers-to person holds. Each step up from a person P (§3):

      1. P leads active departments: their overseer (the one whose units
         hold the item's group, team or role; else every one, once each);
      2. from the item's own person only: the item's department, which P
         neither leads nor oversees: its leader, then its overseer
         (decision 1);
      3. P's holder row for the role names who they answer to: that person;
      4. else church_roles.chain_above from P's role, past anyone named.

    A person counts while they hold an active role here with the switch
    the step asks (an overseer can_oversee, a leader can_lead, an answers-to
    person any role); else they are passed over, like an empty role. Each
    person is named once and each department climbed once, so a loop ends;
    the support duty is never a step: support helps and never directs."""
    by, rows = _ranked(defs, holders)
    named = {str(x) for x in skip if x}
    out: List[tuple] = []
    done: set = set()

    def seat(cid: Any, switch: str = "") -> Optional[tuple]:
        """_seat, or None when they were named already."""
        cid = str(cid or "")
        return None if not cid or cid in named else _seat(m, by, rows, cid, switch)

    def up(depts: List[Dict[str, Any]], who: str) -> Optional[tuple]:
        """One step to these departments' leader or overseers, each person
        once; the one who doesn't qualify is passed over. Its first person's
        seat, or None when nobody qualified."""
        said, people = [], {}
        for d in depts:
            done.add(d["id"])
            s = seat(d[f"{who}_contact_id"], "lead" if who == "leader" else "oversee")
            if s:
                said.append(d)
                people.setdefault(str(s[1]["contact_id"]), s)
        if not people:
            return None
        head = next(iter(people.values()))
        out.append((_step(said, who, len(people), head[0]), [s[1] for s in people.values()]))
        named.update(people)
        return head

    item = [d for d in (m.department_of("group", group_id) if group_id else None,
                        m.department_of("serve_option", team) if team else None,
                        m.department_of("role", role["id"]) if role and role.get("id") else None) if d]
    ids = {d["id"] for d in item}
    cur, cur_role, cur_team, first = str(person or ""), role, team, True
    if cur:
        named.add(cur)
    while cur:
        if len(out) >= CHAIN_MAX:
            return out
        led = [d for d in m.led_by(cur) if d["id"] not in done]
        nxt = up([d for d in led if d["id"] in ids] or led, "overseer") if led else None
        mine = item[0] if item and first else None
        if not nxt and mine and mine["id"] not in done and cur != mine["overseer_contact_id"]:
            lead = up([mine], "leader")
            nxt = up([mine], "overseer") or lead
        if not nxt:
            s = seat(m.answers_to(cur, cur_role["key"]) if cur_role else m.answers_to(cur))
            if s:
                out.append(({**s[0], "answers_to": str(s[1]["contact_id"])}, [s[1]]))
                named.add(str(s[1]["contact_id"]))
                nxt = s
        if not nxt:
            break
        cur_role, row = nxt
        cur, cur_team, first = str(row["contact_id"]), row.get("scope") or "", False
    return out + cr.chain_above(cur_role, defs, holders, team=cur_team, skip=named)


# ─── A draft ──────────────────────────────────────────────────────────

def propose(biz: Any) -> Dict[str, Any]:
    """A read-only draft of the church's departments, the hook for step 2.

    TODO (step 2): draft from groups of kind 'ministry' and from each role's
    oversees_teams, a leader only where one person holds the source, never an
    overseer (an overseer changes who hears about a late item, so a person
    names one: docs/CHURCH_LEADERS_MAP.md §2). Until then it drafts nothing,
    and it never writes."""
    return {}


# ─── The office's writes (PR 5) ───────────────────────────────────────
#
# The triggers and unique indexes check what these check; a write they refuse
# comes back from sb_clients as None, which is a 503 unless a re-read shows a
# conflict someone made meanwhile (then the same plain 400 as before the write).

STATUSES = ("draft", "active", "archived")
SOURCES = ("office", "chief", "template")
KINDS = (*UNIT_REF, "serve_option", "space", "check_line")
LEVELS = ("pastor_from_cents", "board_over_cents")
PICKS = ("pastor_yes_roles", "office_overseer_roles")
LEVEL_MAX_CENTS = 10_000_000          # $100,000, the migration's check
UNITS_MAX, PICKS_MAX = 60, 20
IDS_PER_READ = 50                     # ids in one id=in.(...) read
LEFT_FOR = timedelta(minutes=10)      # how long a half-made department waits for its retry
# A unit's thing: its table, its name, and what still counts as there.
_THINGS = {"group": ("groups", "name", "&active=eq.true"),
           "role": ("church_role_defs", "title", "&status=in.(active,draft)"),
           "board": ("church_boards", "name", "&archived=eq.false"),
           "worship_ministry": ("worship_ministries", "name", "&archived_at=is.null")}
_WORD = {"group": "group", "role": "role", "board": "board", "worship_ministry": "worship ministry",
         "serve_option": "serve team", "space": "space", "check_line": "budget line"}
UNREAD = "Your leaders map couldn’t be read just now. Try again in a moment."
UNSAVED = "That didn’t save. Try again."
UNFINISHED = "That couldn’t finish saving. Try again in a moment."
LEFT_EMPTY = ("That didn’t finish saving. {name} was made with nothing in it: archive it on your leaders map, then "
              "try again.")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _bad(msg: str) -> None:
    raise HTTPException(400, msg)


def _id(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn’t valid")


def _need(path: str) -> List[Dict[str, Any]]:
    rows = _rows(path)
    if rows is None:
        raise HTTPException(503, UNREAD)
    return rows


def _tables_open() -> None:
    """The map's tables answer: a 503 before the migration, and when the
    probe itself failed (state() None), a blip is a failed read, never a yes."""
    s = state()
    if s is not True:
        raise HTTPException(503, UNREAD if s is None else "The leaders map isn’t set up yet. Try again later.")


def _map(bid: str) -> Map:
    _tables_open()
    m = load(bid)
    if m is None:
        raise HTTPException(503, UNREAD)
    return m


def _in(ids: Iterable[str]) -> str:
    return ",".join(_q(i) for i in ids)


def _by_ids(path: Any, ids: Iterable[Any]) -> List[Dict[str, Any]]:
    """`path(ids)` read IDS_PER_READ ids at a time and merged, so a big
    church's map stays under the proxy's URL limit; a 503 when any read fails."""
    ids = sorted({str(i) for i in ids if i})
    out: List[Dict[str, Any]] = []
    for n in range(0, len(ids), IDS_PER_READ):
        out += _need(path(_in(ids[n:n + IDS_PER_READ])))
    return out


def _people(bid: str, ids: Iterable[Any]) -> Dict[str, str]:
    """contact id -> name, for this church's people only."""
    rows = _by_ids(lambda part: f"/contacts?business_id=eq.{_q(bid)}&id=in.({part})&select=id,name&limit=1000", ids)
    return {str(r["id"]): _plain(r.get("name")) for r in rows}


def _holders(bid: str) -> List[Dict[str, Any]]:
    return _need(f"/church_leader_roles?business_id=eq.{_q(bid)}&status=eq.active&select={LINK_COLS}&limit=2000")


def qualifies(m: Map, holders: List[Dict[str, Any]], contact_id: Any, switch: str = "") -> bool:
    """Whether this person holds an active role here, with `switch` ("lead",
    "oversee") on when one is named: who may lead or oversee a department,
    and who the chain passes over once they no longer may (§3)."""
    by_key = {r["key"]: r for r in m.roles.values() if r.get("status") == "active"}
    for h in holders:
        if str(h["contact_id"]) == str(contact_id):
            d = by_key.get(h.get("role")) or cr.LEGACY.get(str(h.get("role") or ""))
            if d and (not switch or can(m, d)[switch]):
                return True
    return False


def _things(bid: str, kind: str, ids: Iterable[str]) -> Dict[str, str]:
    """id -> name of each one still here; a deleted or archived one isn't."""
    table, col, live = _THINGS[kind]
    rows = _by_ids(lambda part: f"/{table}?business_id=eq.{_q(bid)}&id=in.({part}){live}&select=id,{col}&limit=500",
                   ids)
    return {str(r["id"]): _plain(r.get(col)) for r in rows}


def _labels(bid: str, kind: str) -> Dict[str, str]:
    """The labels a unit of this kind may carry, folded -> the church's own
    spelling: the Serve card's teams, the budget lines (church_checks), or
    youth and kids."""
    if kind == "serve_option":
        import church_follow_up as cfu
        got = cfu.teams(bid)
        if got is None:
            raise HTTPException(503, UNREAD)
    elif kind == "check_line":
        import church_checks
        got = [x["name"] for x in church_checks.settings(bid)["lines"]]
    else:
        got = ["youth", "kids"]
    return {_plain(x).casefold(): _plain(x) for x in got}


def _ukey(u: Dict[str, Any]) -> tuple:
    return (u["kind"], u["ref"] or u["label"].casefold())


def _hung(m: Map, u: Dict[str, Any], did: Optional[str]) -> Optional[Dict[str, Any]]:
    """The other department (draft or active) this thing already hangs from."""
    return next((d for d in m.departments if d["id"] != did for x in d["units"] if _ukey(x) == _ukey(u)), None)


def _clash(m: Map, did: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    return next((d for d in m.departments if d["id"] != did and d["name"].strip().casefold() == name.casefold()),
                None)


def _left_behind(d: Optional[Dict[str, Any]], by: Any) -> bool:
    """A department this login's own save made in the last ten minutes and
    couldn't finish: its units failed, and so did taking it back out, so it
    was marked a draft from the office (save_department). A retry of that
    save takes it as its own instead of hitting its name. A department made
    on purpose with nothing hung from it is active, so it isn't one
    (#1716 review)."""
    if not d or d["units"] or d.get("status") != "draft" or d.get("source") != "office":
        return False
    if not by or str(d.get("updated_by") or "") != str(by):
        return False
    try:
        at = datetime.fromisoformat(str(d.get("updated_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) <= LEFT_FOR


def _units_in(bid: str, m: Map, did: Optional[str], raw: Any) -> List[Dict[str, Any]]:
    """A department's units as asked, each checked: the church's own thing,
    still here; a serve option on the Serve card, a budget line in the
    church's settings, a space youth or kids; not hanging from another
    department already."""
    if not isinstance(raw, list) or len(raw) > UNITS_MAX:
        _bad(f"A department holds up to {UNITS_MAX} things")
    want: Dict[tuple, Dict[str, Any]] = {}
    for u in raw:
        kind = u.get("kind") if isinstance(u, dict) else None
        if kind not in KINDS:
            _bad("That isn’t something a department can hold")
        ref = _id(u.get("ref"), _WORD[kind]) if kind in UNIT_REF else ""
        x = {"kind": kind, "ref": ref, "label": "" if ref else _plain(u.get("label"))[:120]}
        want.setdefault(_ukey(x), x)
    out = list(want.values())
    kinds = {u["kind"] for u in out}
    names = {k: _things(bid, k, [u["ref"] for u in out if u["kind"] == k]) if k in UNIT_REF else _labels(bid, k)
             for k in kinds}
    for u in out:
        k = u["kind"]
        u["name"] = names[k].get(u["ref"] or u["label"].casefold())
        if not u["name"]:
            _bad({"serve_option": f"“{u['label']}” isn’t a team on your Serve card",
                  "check_line": f"“{u['label']}” isn’t one of your budget lines",
                  "space": "A space is youth or kids"}.get(k, f"That {_WORD[k]} isn’t one of this church’s"))
        if k not in UNIT_REF:
            u["label"] = u["name"]
        other = _hung(m, u, did)
        if other:
            _bad(f"{u['name']} already hangs from {other['name']}. Take it off there first: a thing hangs from "
                 "one department.")
    return out


def _refused(bid: str, did: Optional[str], name: str = "", units: Iterable[Dict[str, Any]] = ()) -> HTTPException:
    """A write the database refused: the plain 400 when a re-read shows a
    department of that name, or one of these things taken, meanwhile (the
    unique indexes); else a 503."""
    m = load(bid)
    why = None
    if m is not None:
        clash = _clash(m, did, name) if name else None
        taken = next(((u, d) for u in units for d in [_hung(m, u, did)] if d), None)
        why = (f"There’s already a department called {clash['name']}" if clash else
               f"{taken[0]['name']} already hangs from {taken[1]['name']}" if taken else None)
    return HTTPException(400, why) if why else HTTPException(503, UNSAVED)


def save_department(biz: Any, body: Dict[str, Any], by: Any) -> Dict[str, Any]:
    """Make (no `id`) or change a department, and replace what hangs from it
    when `units` is given ([{kind, ref | label}]). Only what the request
    names is checked and changed; the rest is the gaps list's to flag. The
    leader must hold an active role that leads, the overseer one that can
    oversee, and they are two people; the duty is one of church_duties'; the
    area one of the eight. Archived, a department lets go of what hung from
    it. Returns the saved row with its units."""
    import church_areas as ca
    import church_duties as cd
    bid, body = _bid(biz), dict(body or {})
    q = _q(bid)
    m = _map(bid)
    did = _id(body["id"], "department") if body.get("id") else None
    cur = next((d for d in m.departments if d["id"] == did), None) if did else None
    if did and cur is None:          # archived ones aren't on the map
        got = _need(f"/church_departments?id=eq.{_q(did)}&business_id=eq.{q}&select={DEPT_COLS}&limit=1")
        if not got:
            raise HTTPException(404, "That department isn’t here")
        cur = _dept(got[0], [])
    row: Dict[str, Any] = {}
    if "name" in body or cur is None:
        row["name"] = _plain(body.get("name"))
        if not 1 <= len(row["name"]) <= 80:
            _bad("Name the department (up to 80 letters)")
    finish = None                           # a retry's status, set once its units are in
    if cur is None and isinstance(body.get("units"), list) and body["units"]:
        left = _clash(m, None, row["name"])
        if _left_behind(left, by):          # the retry of a save that couldn't finish
            did, cur, finish = left["id"], left, "active"     # what the first try made it, unless this one says
    for k, allowed, say in (("status", STATUSES, "A department is a draft, active or archived"),
                            ("source", SOURCES, "A department comes from the office, Chief or a template"),
                            ("area", (None, *ca.AREA_ORDER), "Pick one of the eight areas"),
                            ("support_duty", (None, *cd.CATALOG), "Pick one of the office’s duties to help it")):
        if k in body:
            row[k] = (body[k] or None) if k in ("area", "support_duty") else body[k]
            if row[k] not in allowed:
                _bad(say)
    if "sort" in body:
        if not isinstance(body["sort"], int) or isinstance(body["sort"], bool) or not 0 <= body["sort"] <= 999:
            _bad("The order is a number from 0 to 999")
        row["sort"] = body["sort"]
    if finish:      # it stays a draft, which routes nothing, until its units are in (#1717 review)
        finish = row.pop("status", finish)
        if finish == "archived":
            row["status"], finish = finish, None
    named = {k: _id(body[k], "person") if body[k] else None
             for k in ("leader_contact_id", "overseer_contact_id") if k in body}
    if any(named.values()):
        people, holders = _people(bid, named.values()), _holders(bid)
        for k, cid in named.items():
            who, switch, does = (("leader", "lead", "leads") if k == "leader_contact_id" else
                                 ("overseer", "oversee", "can oversee a department"))
            if cid and cid not in people:
                _bad(f"That {who} isn’t one of this church’s people")
            if cid and not qualifies(m, holders, cid, switch):
                _bad(f"{people[cid]} doesn’t hold a role that {does}. Turn that on for their role in Leaders & "
                     f"roles, or pick another {who}.")
    row.update(named)
    after = {**(cur or {}), **row}
    if after.get("leader_contact_id") and after["leader_contact_id"] == after.get("overseer_contact_id"):
        _bad("A department’s leader and its overseer are two people")
    status = after.get("status") or "active"
    clash = _clash(m, did, after["name"]) if status != "archived" else None
    if clash:
        _bad(f"There’s already a department called {clash['name']}")
    units = _units_in(bid, m, did, body["units"]) if body.get("units") is not None and status != "archived" else None
    stamp = {"updated_by": str(by) if by else None, "updated_at": datetime.now(timezone.utc).isoformat()}
    if cur is None:
        saved = sb_clients.sb_post_as_service("/church_departments", {
            "business_id": bid, "status": "active", "source": "office", "sort": 0, **row, **stamp})
    else:
        saved = sb_clients.sb_patch_as_service(f"/church_departments?id=eq.{_q(did)}&business_id=eq.{q}",
                                               {**row, **stamp})
    if not isinstance(saved, list) or not saved:
        raise _refused(bid, did, after["name"] if status != "archived" else "")
    did, have = str(saved[0]["id"]), (cur or {}).get("units") or []
    if status == "archived":        # what hung from it is free to hang elsewhere
        if not sb_clients.sb_delete_as_service(f"/church_department_units?business_id=eq.{q}&department_id=eq.{did}"):
            raise HTTPException(503, UNSAVED)
        return _dept(saved[0], [])
    if units is None:
        return _dept(saved[0], have)
    keep, old = {_ukey(u) for u in units}, {_ukey(u) for u in have}
    new = [u for u in units if _ukey(u) not in old]
    made: List[Dict[str, Any]] = []
    if new:
        made = sb_clients.sb_post_as_service("/church_department_units", [{
            "business_id": bid, "department_id": did, "kind": u["kind"], "label": "" if u["ref"] else u["label"],
            **{c: (u["ref"] if UNIT_REF.get(u["kind"]) == c else None) for c in UNIT_REF.values()}} for u in new])
        if not isinstance(made, list) or len(made) != len(new):
            # A new department doesn't stay half made. When it can't be taken
            # back out it is marked a draft, which routes nothing, and a retry
            # of this save finishes it (_left_behind).
            if cur is None and not sb_clients.sb_delete_as_service(
                    f"/church_departments?id=eq.{_q(did)}&business_id=eq.{q}"):
                marked = sb_clients.sb_patch_as_service(f"/church_departments?id=eq.{_q(did)}&business_id=eq.{q}",
                                                        {"status": "draft", **stamp})
                if not isinstance(marked, list) or not marked:     # it is left active, with nothing in it
                    print(f"[church_map] department {did} at {bid} left active and empty: its units, taking it "
                          "out and marking it a draft all failed", flush=True)
                    raise HTTPException(503, LEFT_EMPTY.format(name=after["name"]))
                raise HTTPException(503, UNFINISHED)
            raise _refused(bid, did, units=new)
    gone = [u["id"] for u in have if _ukey(u) not in keep]
    if gone and not sb_clients.sb_delete_as_service(
            f"/church_department_units?business_id=eq.{q}&department_id=eq.{did}&id=in.({_in(gone)})"):
        raise HTTPException(503, UNSAVED)
    if finish and finish != "draft":
        done = sb_clients.sb_patch_as_service(f"/church_departments?id=eq.{_q(did)}&business_id=eq.{q}",
                                              {"status": finish, **stamp})
        if not isinstance(done, list) or not done:
            raise HTTPException(503, UNFINISHED)
        saved = done
    return _dept(saved[0], [u for u in have if _ukey(u) in keep] + [_unit(u) for u in made])


def archive_department(biz: Any, department_id: Any, by: Any) -> Dict[str, Any]:
    """Archive a department. What hung from it can hang elsewhere; its name
    is free for a new one. Again on an archived one lets go of anything left."""
    return save_department(biz, {"id": department_id, "status": "archived"}, by)


def set_answers_to(biz: Any, holder_id: Any, answers_to: Any) -> Dict[str, Any]:
    """Who one holder row (a person in a role) answers to, or nobody (None):
    a person here who holds an active role, never the holder themselves.
    Returns the saved row."""
    _tables_open()
    bid = _bid(biz)
    hid = _id(holder_id, "role holder")
    rows = _need(f"/church_leader_roles?id=eq.{_q(hid)}&business_id=eq.{_q(bid)}&select={LINK_COLS}&limit=1")
    if not rows or rows[0].get("status") != "active":
        raise HTTPException(404, "That person doesn’t hold that role here")
    to = _id(answers_to, "person") if answers_to else None
    if to and to == str(rows[0]["contact_id"]):
        _bad("A leader can’t answer to themselves")
    if to and not any(str(h["contact_id"]) == to for h in _holders(bid)):
        _bad("They don’t hold a role here yet, so nobody can answer to them. Give them a role first.")
    if (str(rows[0].get("answers_to_contact_id") or "") or None) == to:
        return rows[0]
    saved = sb_clients.sb_patch_as_service(f"/church_leader_roles?id=eq.{_q(hid)}&business_id=eq.{_q(bid)}",
                                           {"answers_to_contact_id": to})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, UNSAVED)
    return saved[0]


def save_settings(biz: Any, body: Dict[str, Any], by: Any, role: str) -> Dict[str, Any]:
    """The church's money levels (cents; None is the platform's) and its
    role picks: who gives the pastor's yes, who oversees the office (lists of
    the church's active roles; [] is "none named"). Only the owner changes a
    money level (decision 3). A change stamps map_by/map_at and logs a line
    with what it was and is; the same values again change nothing."""
    bid, body = _bid(biz), dict(body or {})
    m = _map(bid)
    cur, out = m.settings, {}
    for k in LEVELS:
        if k in body:
            v = body[k]
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= LEVEL_MAX_CENTS):
                _bad("A money level is from $0 to $100,000")
            if v != cur.get(k):
                out[k] = v
    if any(k in out for k in LEVELS) and role != "owner":
        raise HTTPException(403, "Only the owner changes the church’s money levels.")
    if any(k in out for k in LEVELS):
        # A level left unset is the platform's (church_money_levels), so a
        # pastor's above $2,500 with the board's unset would ask for a board
        # member's yes before the pastor's (#1717 notes).
        import church_money_levels as cml
        pastor, board = (out.get(k, cur.get(k)) for k in LEVELS)
        if (cml.BOARD_OVER_CENTS if board is None else board) < (cml.PASTOR_FROM_CENTS if pastor is None else pastor):
            _bad("The board’s level starts at or above the pastor’s")
    active = {rid for rid, r in m.roles.items() if r.get("status") == "active"}
    for k in PICKS:
        if k in body:
            raw = body[k] or []
            if not isinstance(raw, list) or len(raw) > PICKS_MAX:
                _bad(f"Pick up to {PICKS_MAX} roles")
            ids = list(dict.fromkeys(_id(x, "role") for x in raw))
            if any(i not in active for i in ids):
                _bad("Pick from this church’s own roles")
            if ids != cur.get(k):
                out[k] = ids
    if not out:
        return {"settings": cur, "changed": False}
    saved = sb_clients.sb_post_as_service("/church_role_settings?on_conflict=business_id", {
        "business_id": bid, **out, "map_by": str(by), "map_at": datetime.now(timezone.utc).isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, UNSAVED)
    print(f"[church_map] settings {bid} by {by}: " + "; ".join(f"{k} {cur.get(k)!r} -> {v!r}" for k, v in out.items()),
          flush=True)
    return {"settings": {k: saved[0].get(k) for k in SETTINGS_COLS.split(",")}, "changed": True}


# ─── The office's map ─────────────────────────────────────────────────

def view(biz: Dict[str, Any]) -> Dict[str, Any]:
    """GET /church/map: each department with its people's names, its duty
    (label and who does it today, church_duties.holders_of) and its units by
    name; each role's switches; who answers to whom; the settings; and the
    gaps: a department missing a leader, an overseer or a duty, a leader or
    overseer who no longer qualifies, a serve option no longer on the Serve
    card, a budget line gone, a unit whose thing is gone."""
    import church_duties as cd
    import church_money_levels as cml
    bid = _bid(biz)
    m, roles, holders = _map(bid), cr.defs(bid, with_drafts=True), _holders(bid)
    if roles is None:
        raise HTTPException(503, UNREAD)
    units = [u for d in m.departments for u in d["units"]]
    names = {k: _things(bid, k, [u["ref"] for u in units if u["kind"] == k]) if k in UNIT_REF else _labels(bid, k)
             for k in {u["kind"] for u in units}}
    people = _people(bid, [d[k] for d in m.departments for k in ("leader_contact_id", "overseer_contact_id")] +
                     [x[k] for x in m.links for k in ("contact_id", "answers_to_contact_id")])
    duties = sorted({d["support_duty"] for d in m.departments if d["support_duty"] in cd.CATALOG})
    logins = cd._names(bid, biz, cd._seats(bid)) if duties else {}
    with once():
        helpers = {k: [{"user_id": u, "name": logins.get(u, "")} for u in cd.holders_of(bid, k)] for k in duties}
    gaps: List[Dict[str, Any]] = []
    out = []
    for d in m.departments:
        said = []
        for k, who, switch, does in (("leader_contact_id", "leader", "lead", "leads"),
                                     ("overseer_contact_id", "overseer", "oversee", "can oversee")):
            if not d[k]:
                said.append((f"no_{who}", f"{d['name']} has no {who}."))
            elif not qualifies(m, holders, d[k], switch):
                said.append((f"{who}_off", f"{people.get(d[k]) or 'Its ' + who} no longer holds a role that {does}."))
        if d["support_duty"] not in cd.CATALOG:
            said.append(("no_duty", f"No office duty is named to help {d['name']}."))
        shown = []
        for u in d["units"]:
            name = names[u["kind"]].get(u["ref"] or u["label"].casefold())
            if not name:
                said.append(("unit_gone", {"serve_option": f"“{u['label']}” is no longer on the Serve card.",
                                           "check_line": f"“{u['label']}” is no longer one of the budget lines."}
                             .get(u["kind"], f"A {_WORD[u['kind']]} that hung from {d['name']} is gone.")))
            shown.append({**u, "name": name or u["label"]})
        gaps += [{"department_id": d["id"], "kind": k, "text": t} for k, t in said]
        duty = d["support_duty"] if d["support_duty"] in cd.CATALOG else None
        out.append({**{k: d[k] for k in ("id", "name", "status", "source", "sort", "area", "updated_at")},
                    **{w: {"contact_id": d[k], "name": people.get(d[k], "")} if d[k] else None
                       for w, k in (("leader", "leader_contact_id"), ("overseer", "overseer_contact_id"))},
                    "support_duty": {"key": duty, "label": cd.CATALOG[duty]["label"], "holders": helpers[duty]}
                    if duty else None, "units": shown})
    return {"departments": out, "gaps": gaps,
            "roles": [{**{k: r[k] for k in ("id", "key", "title", "job", "status")}, "switches": can(m, r)}
                      for r in roles],
            "answers_to": [{"holder_id": x["id"], "role": x["role"], "contact_id": x["contact_id"],
                            "name": people.get(x["contact_id"], ""),
                            "answers_to": {"contact_id": x["answers_to_contact_id"],
                                           "name": people.get(x["answers_to_contact_id"], "")}} for x in m.links],
            "settings": {**m.settings, "platform": {"pastor_from_cents": cml.PASTOR_FROM_CENTS,
                                                    "board_over_cents": cml.BOARD_OVER_CENTS}}}
