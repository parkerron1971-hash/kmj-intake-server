"""church_schedule_volunteers.py — the leaders schedule, step 2: the volunteers'
rules (docs/CHURCH_SCHEDULE.md, PR S2-5; church_schedule.py is the engine,
church_schedule_limits.py holds the numbers).

The platform owner's call 3, approved 2026-11-18: "Volunteers need no yes to be
away, unless the date is full or they already agreed to serve it; then it goes
to their team leader."

A volunteer is anyone not on the leaders schedule. Their Away on the Serve page
(sunday_serving.add_away) is looked at here first:

  free ............ no department of theirs is at its number on any of those
                    days, and they said yes to no place inside them: SAVED AT
                    ONCE, exactly as it always was. Nothing here writes; the
                    Serve page's own write and its own words follow
  full ............ one of their departments (a department one of their Sunday
                    teams hangs from) is at its number on one of those days,
                    counting only away dates that were agreed, as S2-3 counts
                    (church_schedule_limits.flags_of): an ask, `over_limit`
  already serving . they said yes to a place inside those days (sunday_serving.
                    yes_places, what S1-6 opens on a yes): an ask, `serving`

Such an ask (grp volunteers, team_group_id set, department_id set where the
team hangs from one) goes to the leader of the Sunday team concerned
(leader_of; the doc's `team_leader`, named so because that word is a role key
the title-words rule keeps out of rule code). The team concerned is the one of
the soonest place they said yes to, else their first team in the department
that is full. Who that is, nearest first (team_step: everyone at the first step
that has anyone):

  1. the team's own leaders (group_members, role leader), by name
  2. the department it hangs from (as one of its groups, or by name as one of
     its Serve options): its leader while they hold a role that leads, else its
     overseer while they hold one that oversees (church_map.team_head's rule,
     #1719)
  3. that department's leader, else its overseer, whatever role they hold
  4. whoever keeps Who serves when: the Manager logins that hold the
     serve_schedule duty (an Admin holds every duty by its seat and is not
     picked for it)
  5. the owner

Never the volunteer themself, at any step. A volunteer's ask is NEVER INSTANT
and NEVER GOES UP: it is not "flagged" in church_schedule's sense
(church_schedule.flagged is false for it), so the one it went to answers it
over the department's number for their own team, with a plain yes (no
exception, no recheck: decided in S2-5, docs/CHURCH_SCHEDULE.md 7.11). A yes
writes the away date (church_away_settle) and opens the places they had agreed
to serve (church_schedule._open_places, as for every yes).

A VOLUNTEER'S AWAY NEVER FAILS BECAUSE OF THIS. away() answers None, "saved at
once, as always", for a free date and for anything that goes wrong while
looking: a read of the numbers, the teams or the places that fails, the ask's
own write failing, anything at all. One line is logged then, with the church's
id cut short and nothing else. A second press of the same days answers with
the ask already waiting, never a second one.

ORDER OF ASKING: the switch (no read), the tables (kept), the church (kept),
step 2's tables (kept), then whether they are on the leaders schedule (the
roster kept a minute: a replica that can't tell saves at once, as S1-6 does).
Closed anywhere along that line, nothing here reads at all.

Every read is paged or bounded by a list of ids a hundred at a time, and every
value in an address is quoted.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

import church_over as co
import church_schedule as cs
import sb_clients

GRP = "volunteers"
MINE_MAX = 50              # a volunteer's own asks on My serving: what still waits, and a "not this one" still to come


def _q(v: Any) -> str:
    return cs._q(v)


def _log(biz: Any, what: str, e: BaseException) -> None:
    """One line, the church's id cut short and nothing else: no name, no day."""
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    print(f"[church_schedule] {b[:8]}: {what} ({type(e).__name__})", flush=True)


def here(biz: Any) -> bool:
    """Whether the volunteers' rules reach this church: the leaders schedule
    reaches it (church_schedule._here: the switch, the tables, the church,
    each kept) and step 2's tables are there (church_schedule.step2, kept).
    NEVER RAISES. False: nothing here reads."""
    try:
        return bool(cs._here(biz)) and cs.step2()
    except Exception:  # noqa: BLE001 — closed, as far as can be told
        return False


# ─── Teams and departments ────────────────────────────────────────────

def teams_of(ch: co.Church, cid: Any) -> List[str]:
    """The Sunday teams this person is on (a group with a serve_teams row,
    still active), by the team's name. Their groups are read a page at a
    time."""
    import church_schedule_limits as csl
    teams = csl._teams(ch)
    if not teams:
        return []
    mine = {str(r["group_id"]) for r in cs._every(
        f"/group_members?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}&select=group_id,contact_id",
        key="group_id") if r.get("group_id") and str(r.get("contact_id") or "") == str(cid)}
    return sorted((g for g in mine if g in teams), key=lambda g: (teams[g].casefold(), g))


def _department_of_team(ch: co.Church, gid: Any) -> Optional[Dict[str, Any]]:
    """The active department a Sunday team hangs from (as one of its groups,
    or by name as one of its Serve options): the first in the church's own
    order. None with the map closed, or for a team that hangs from none."""
    import church_schedule_limits as csl
    gid = str(gid or "")
    if not gid:
        return None
    return next((d for d in csl._departments(ch) if gid in csl._department_teams(ch, d)), None)


def departments_of(ch: co.Church, cid: Any) -> List[Dict[str, Any]]:
    """The active departments this person's Sunday teams hang from, in the
    church's own order: [{"id", "name", "teams": [their teams in it]}]."""
    import church_schedule_limits as csl
    mine = teams_of(ch, cid)
    if not mine:
        return []
    out = []
    for d in csl._departments(ch):
        hits = [g for g in csl._department_teams(ch, d) if g in mine]
        if hits:
            out.append({"id": str(d["id"]), "name": cs._plain(d.get("name")) or "A department",
                        "teams": sorted(hits, key=lambda g: mine.index(g))})
    return out


def _people(ch: co.Church, ids: Iterable[Any], but: str) -> List[Dict[str, str]]:
    """These people as a step, by name: never `but` (the volunteer)."""
    ids = [str(c) for c in dict.fromkeys(str(i) for i in ids if i) if str(c) != but]
    names = ch.names(ids)
    return sorted(({"kind": co.PERSON, "id": c, "name": names.get(c, "Someone")} for c in ids),
                  key=lambda r: (r["name"].casefold(), r["id"]))


def _keepers(ch: co.Church, but: str) -> List[str]:
    """Whoever keeps Who serves when: the Manager logins that hold the
    serve_schedule duty, in a steady order. An Admin holds every duty by its
    seat and is not picked for it; nor is a login whose person is `but`."""
    import church_schedule_limits as csl
    return sorted(u for u in ch.office if ch.role(u) == "manager" and csl.SERVE_DUTY in ch.held(u)
                  and ch.login_person.get(u) != but)


def team_step(ch: co.Church, gid: Any, department_id: Any = None, *, but: Any = "") -> List[Dict[str, str]]:
    """Everyone at the first step that has anyone, over a volunteer on this
    Sunday team: [{kind, id, name}], nearest first (the module's docstring
    has the steps). `department_id`: the department the ask was filed under,
    used when the team hangs from none (or is gone). Never `but`. [] only
    for a church with no owner."""
    import church_schedule_limits as csl
    but, gid = str(but or ""), str(gid or "")
    if gid and gid in csl._teams(ch):
        leaders = [str(r["contact_id"]) for r in cs._every(
            f"/group_members?business_id=eq.{_q(ch.b)}&group_id=eq.{_q(gid)}&role=eq.leader"
            f"&select=group_id,contact_id,role", key="contact_id")
            if r.get("contact_id") and str(r.get("group_id") or "") == gid and r.get("role") == "leader"]
        step = _people(ch, leaders, but)
        if step:
            return step
    d = _department_of_team(ch, gid) or csl._department(ch, department_id)
    if d:
        lead, over = str(d.get("leader_contact_id") or ""), str(d.get("overseer_contact_id") or "")
        # church_map.team_head's rule (#1719): the leader while they hold a role that leads, else the overseer
        # while they hold one that oversees.
        for c, switch in ((lead, "lead"), (over, "oversee")):
            if c and c != but and ch.qualifies(c, switch):
                return _people(ch, [c], but)
        for c in (lead, over):
            if c and c != but:
                return _people(ch, [c], but)
    keep = _keepers(ch, but)
    if keep:
        return [{"kind": co.LOGIN, "id": u, "name": ch.login_name(u)} for u in keep]
    return [{"kind": co.LOGIN, "id": ch.owner, "name": ch.login_name(ch.owner)}] if ch.owner else []


def leader_of(ch: co.Church, gid: Any, department_id: Any = None, *, but: Any = "") -> Optional[Dict[str, str]]:
    """Who a volunteer's ask goes to: the first at team_step's first step
    (the doc's team_leader). None only for a church with no owner."""
    step = team_step(ch, gid, department_id, but=but)
    return step[0] if step else None


# ─── Where they serve ─────────────────────────────────────────────────

def _places(ch: co.Church, cid: str, a: date, b: date, now: datetime) -> List[Dict[str, Any]]:
    """The places they said yes to on a day inside these days that is still
    to come (sunday_serving.yes_places: the very places a yes opens), each
    with its team and its moment: [{id, service_id, group_id, at}], soonest
    first. Read by a hundred ids at a time."""
    import sunday_serving as ss
    got = ss.yes_places(ch.b, cid, a, b, now=now)
    if not got:
        return []
    ids = [p["id"] for p in got]
    pos: Dict[str, str] = {}
    for part in co._chunks(ids, co.IDS_PER_READ):
        for r in cs._need(f"/serve_assignments?business_id=eq.{_q(ch.b)}&id=in.({cs._in(part)})"
                          f"&contact_id=eq.{_q(cid)}&select=id,position_id&limit={co.IDS_PER_READ}"):
            pos[str(r["id"])] = str(r.get("position_id") or "")
    team: Dict[str, str] = {}
    for part in co._chunks(pos.values(), co.IDS_PER_READ):
        for r in cs._need(f"/serve_positions?business_id=eq.{_q(ch.b)}&id=in.({cs._in(part)})"
                          f"&select=id,group_id&limit={co.IDS_PER_READ}"):
            team[str(r["id"])] = str(r.get("group_id") or "")
    at: Dict[str, str] = {}
    for part in co._chunks((p["service_id"] for p in got), co.IDS_PER_READ):
        for r in cs._need(f"/worship_services?business_id=eq.{_q(ch.b)}&id=in.({cs._in(part)})"
                          f"&select=id,starts_at&limit={co.IDS_PER_READ}"):
            at[str(r["id"])] = str(r.get("starts_at") or "")
    out = [{"id": p["id"], "service_id": p["service_id"], "group_id": team.get(pos.get(p["id"], ""), ""),
            "at": at.get(p["service_id"], "")} for p in got]
    return sorted((p for p in out if p["group_id"]), key=lambda p: (p["at"], p["id"]))


# ─── The plan ─────────────────────────────────────────────────────────

def volunteer_plan(ch: co.Church, cid: Any, starts_on: date, ends_on: date, *,
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    """What a volunteer's Away for these days is: {"instant", "flags", "to",
    "team_group_id", "department_id", "full", "places"}. READS ONLY.

    `instant`: free (nothing below), saved at once as it always was.
    Otherwise `flags` is `serving` (they said yes to a place inside the
    days: `places`, soonest first) and/or `over_limit` (one of their
    departments is at its number on one of the days: `full`, [{"department",
    "why"}], the why in church_schedule_limits' words, counts only). A
    protected day and a pair are the leaders' rules, never looked at here.

    The team concerned is the soonest place's, else their first team in the
    first full department; `department_id` is the full department when
    there is one (the serving team's own when that one is full), else the
    serving team's own. `to` is that team's leader (leader_of). The one
    person the church's owner is needs nobody's yes (S1-2): instant."""
    import church_schedule_limits as csl
    cid = str(cid or "")
    out: Dict[str, Any] = {"instant": True, "flags": [], "to": None, "team_group_id": None, "department_id": None,
                           "full": [], "places": []}
    if not cid or (ch.owner_person and cid == ch.owner_person):
        return out
    now = now or cs._now()
    places = _places(ch, cid, starts_on, ends_on, now)
    depts = departments_of(ch, cid)
    numbers = csl._department_limits(ch) if depts else {}
    counted = [d for d in depts if d["id"] in numbers]
    full: List[Dict[str, Any]] = []
    if counted:
        p = csl.picture(ch, starts_on, ends_on, now=now)
        for d in counted:
            why = [w for w in csl.flags_of(p, cid, starts_on, ends_on, d["id"], pairs=False)["why"]
                   if w.get("flag") == "over_limit" and w.get("of") == "department"]
            if why:
                full.append({"department": d, "why": why})
    if not places and not full:
        return out
    if places:
        gid = places[0]["group_id"]
        own = _department_of_team(ch, gid)
        own_id = str(own["id"]) if own else None
        hit = next((f["department"]["id"] for f in full if f["department"]["id"] == own_id), None)
        did = hit or (full[0]["department"]["id"] if full else own_id)
    else:
        gid, did = full[0]["department"]["teams"][0], full[0]["department"]["id"]
    to = leader_of(ch, gid, did, but=cid)
    if not to:
        return out
    flags = (["serving"] if places else []) + (["over_limit"] if full else [])
    return {"instant": False, "flags": flags, "to": to, "team_group_id": gid, "department_id": did, "full": full,
            "places": places}


# ─── The ask ──────────────────────────────────────────────────────────

def ask(ch: co.Church, cid: Any, starts_on: date, ends_on: date, plan: Dict[str, Any]) -> Dict[str, Any]:
    """The one write of a volunteer's ask: time off for these days, no
    reason (the Serve page asks for none), to whoever the plan names. A
    press of the same days again answers with the ask already waiting
    (whatever made it), never a second. Twenty waiting is a 400 in the
    engine's own words. A failed read or write raises (away() saves at once
    then). Whoever it went to hears once the write is back."""
    cid = str(cid)
    a, b = starts_on.isoformat(), ends_on.isoformat()
    path = (f"/church_away_asks?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}&state=eq.asked"
            f"&select={cs._fields()}&limit={cs.MAX_OPEN + 30}")

    def same(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return next((r for r in rows if str(r.get("business_id")) == ch.b and str(r.get("contact_id")) == cid
                     and str(r.get("starts_on"))[:10] == a and str(r.get("ends_on"))[:10] == b), None)
    open_ = cs._need(path)
    twin = same(open_)
    if twin:
        return twin
    if len(open_) >= cs.MAX_OPEN:
        raise HTTPException(400, cs.TOO_MANY)
    to = plan["to"]
    row = {"business_id": ch.b, "contact_id": cid, "made_by": None, "grp": GRP,
           "department_id": plan.get("department_id"), "team_group_id": plan.get("team_group_id"), "kind": "time_off",
           "starts_on": a, "ends_on": b, "reason": None, "cover_contact_id": None, "cover_name": None,
           "to_user_id": to["id"] if to["kind"] == co.LOGIN else None,
           "to_contact_id": to["id"] if to["kind"] == co.PERSON else None, "flags": list(plan["flags"])}
    saved = sb_clients.sb_post_as_service("/church_away_asks", row, redact=True)
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        if str((sb_clients.last_error() or {}).get("code") or "") == "23505":
            twin = same(cs._need(path))         # two presses at once: the other one stands
            if twin:
                return twin
        raise HTTPException(503, cs.UNSAVED)
    cs._after("tell_new", ch, saved[0])         # whoever it went to hears, once the write is back
    return saved[0]


def away(biz: Dict[str, Any], cid: Any, start: Any, end: Any) -> Optional[Dict[str, Any]]:
    """The Serve page's Away, for a volunteer (sunday_serving.add_away asks
    this after church_schedule.takes said no). None: SAVED AT ONCE, AS
    ALWAYS: a free date; closed anywhere (no read); someone on the leaders
    schedule, or a replica that can't tell (their own rule, S1-6); days the
    Away's own words refuse; or anything at all going wrong while looking or
    writing (one line logged). Otherwise {"asked": True, "volunteer": True,
    "state", "to", "short": False}: it went to their team's leader.

    NEVER RAISES, but for one refusal in plain words: twenty asks already
    waiting (church_schedule.TOO_MANY), as twenty away dates is today."""
    if not here(biz):
        return None
    cid = str(cid or "")
    try:
        if not cid or cs.on_schedule(biz, cid) is not False:
            return None                         # on it, or can't be told: not a volunteer's Away here
        a, z = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end or start)[:10])
    except (ValueError, TypeError):
        return None                             # the Away's own words say what is wrong with the days
    try:
        row = cs._own_row(biz)
        if row is None:
            return None
        ch = co.Church(row)
        if z < a or z < cs._today(ch) or (z - a).days > cs.MAX_DAYS:
            return None
        import church_map
        with church_map.once():
            plan = volunteer_plan(ch, cid, a, z)
            if plan["instant"]:
                return None
            saved = ask(ch, cid, a, z, plan)
    except HTTPException as e:
        if e.status_code == 400 and e.detail == cs.TOO_MANY:
            raise
        _log(biz, "a volunteer's Away couldn't be looked at, so it is saved at once, as always", e)
        return None
    except Exception as e:  # noqa: BLE001 — a volunteer's Away is never worth failing for this
        _log(biz, "a volunteer's Away couldn't be looked at, so it is saved at once, as always", e)
        return None
    return {"asked": True, "volunteer": True, "state": saved.get("state") or "asked",
            "to": (plan.get("to") or {}).get("name") or "", "short": False}


# ─── What My serving shows them ───────────────────────────────────────

def mine(biz: Dict[str, Any], cid: Any, now: Optional[datetime] = None) -> Optional[List[Dict[str, Any]]]:
    """A volunteer's own asks for My serving: each still waiting, and each
    "not this one" whose days haven't passed, soonest first, every one
    through church_schedule.shape() as that person (the asker reads their
    own, and the note that came with the answer). [] for none. None: closed
    (no read is made) or a read that failed. NEVER RAISES: the page stands
    without them."""
    if not here(biz):
        return None
    try:
        ch, me = co.Church(biz), co.who(co.PERSON, str(cid))
        today = cs._today(ch, now)
        rows = cs._need(f"/church_away_asks?business_id=eq.{_q(ch.b)}&contact_id=eq.{_q(cid)}&grp=eq.{GRP}"
                        f"&state=in.(asked,no)&ends_on=gte.{today.isoformat()}&select={cs._fields()}"
                        f"&order=starts_on.asc&limit={MINE_MAX}")
        rows = [r for r in rows if str(r.get("business_id")) == ch.b and str(r.get("contact_id")) == str(cid)
                and r.get("grp") == GRP and r.get("state") in ("asked", "no")]
        if not rows:
            return []
        # The member app's church row carries no owner (member_portal's site
        # row): the whole row, so an ask that went to the owner says their name.
        whole = cs._own_row(biz)
        if whole is None:
            return None
        ch = co.Church(whole)
        rows.sort(key=lambda r: (str(r.get("starts_on") or ""), str(r.get("id"))))
        import church_map
        with church_map.once():
            names = cs._names(ch, rows)
            return [cs.shape(ch, me, r, names) for r in rows]
    except Exception as e:  # noqa: BLE001 — never worth the page
        _log(biz, "a volunteer's own asks couldn't be read for My serving", e)
        return None


# ─── Taking one back, and the sweep ───────────────────────────────────

def take_back(biz: Any, cid: Any, ask_id: Any) -> bool:
    """Under Away on My serving, the x on a waiting ask (it rides in the same
    form as an away date's: /my/serving/away/remove). True: it was their
    waiting ask, taken back through church_schedule.withdraw as that person
    (so whoever it went to is told, as for any take-back). False: not one,
    and the caller goes on as it always did. Asked only when no away date
    had that id, and only where step 2's tables are there: nothing more is
    read anywhere else. A read that fails is a 503 with nothing taken back."""
    if not cs.step2():
        return False
    try:
        aid = cs._uuid(ask_id, "ask")
    except HTTPException:
        return False
    b = str(biz.get("id") if isinstance(biz, dict) else biz)
    cid = str(cid or "")
    rows = cs._need(f"/church_away_asks?id=eq.{_q(aid)}&business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}"
                    f"&grp=eq.{GRP}&state=eq.asked&select=id,business_id,contact_id,grp,state&limit=1")
    if not rows or str(rows[0].get("contact_id")) != cid or str(rows[0].get("business_id")) != b:
        return False
    row = cs._own_row(biz)
    if row is None:
        raise HTTPException(503, cs.UNREAD)
    try:
        cs.withdraw(co.Church(row), co.who(co.PERSON, cid), aid)
    except HTTPException as e:
        if e.status_code in (404, 409):
            return False
        raise
    return True


def stale(ch: co.Church, ask_row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The hourly sweep (church_schedule_tell): who a volunteer's waiting ask
    should sit with now, or None to leave it where it is. It stays while its
    `to` is still one of those at the first step of its team's chain
    (team_step), whoever is listed first; it is sent on, to the first of
    them, when `to` is empty, a login that has left the office, or no longer
    one of them. Never round the same step, never to the asker, and never to
    the nearest step over the asker on the leaders map: a volunteer's ask is
    their team's."""
    cid = str(ask_row.get("contact_id") or "")
    step = team_step(ch, ask_row.get("team_group_id"), ask_row.get("department_id"), but=cid)
    if not step:
        return None
    if ask_row.get("to_user_id"):
        to: Optional[Dict[str, str]] = co.who(co.LOGIN, ask_row["to_user_id"])
    elif ask_row.get("to_contact_id"):
        to = co.who(co.PERSON, ask_row["to_contact_id"])
    else:
        to = None
    if to and not (to["kind"] == co.LOGIN and not cs._in_office(ch, to["id"])) and any(co.same(to, s) for s in step):
        return None
    return step[0]
