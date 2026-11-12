"""church_team_week.py — the Executive Pastor's view of her team.

Kevin, 2026-11-01: "Jessica will be over the admin team". The Executive
Pastor holds the oversee_lanes duty by default (church_duties: "See as each
lane", "The Monday team roll-up"); this is docs/CHURCH_DUTIES.md step 6, her
view, without the monthly report (its own PR).

    SEE AS ......... GET /church/my-week?as_user= opens to whoever is over the
                     lanes, for another Manager login on the same church only,
                     never an Admin or the owner (church_my_week). The page
                     says whose week it is (`seeing_as`). A duty never widens
                     what a login sees: the week is cut to the overseer's own
                     areas (within), so a follow-up's name reaches her only if
                     she works People & care herself.
    THE TEAM ....... GET /church/my-week/team?business_id= (whoever is over the
                     lanes, the owner, an admin): each office Manager login,
                     with its name and lane; its open tasks and how many are
                     late (the church's day); the follow-ups and the prayer and
                     care requests handed to it that are still open, as counts;
                     and what's due this week from its duties (each duty's day
                     in the catalog: "Wed: The weekly text", or the day the
                     login picked, church_assignments), each a check judges
                     done / not yet / late where church assignments are open
                     (judge_week: one read a table for the church). No money, and
                     nothing behind a keeper wall: no names of the people in
                     follow-up, nothing of what a care request asked, and the
                     follow-up and care counts only for an overseer who works
                     People & care herself. A failed read of one login's data
                     is a 503 for that row, never a row that looks empty.
    MONDAY ......... rollup_tick, hourly on the worker: on Monday in each
                     church's morning (its own clock, church_leader_tasks'
                     LATE_FROM to LATE_UNTIL), one email to each Manager over
                     the lanes, from the church, with the team in plain words
                     (who's late on what, what's due this week and, where a
                     check judges it, done / not yet / late), and a push to
                     My week. The owner and the admins don't get it (the owner
                     has chief_week). Claimed once per church per ISO week in
                     businesses.settings.church_team_rollup, swapped only when
                     nobody else changed it (church_leaders_note's way), so two
                     replicas send once. A week that reached some holders and not
                     others is `partial`: the next hour tries only the rest. A
                     record that doesn't save is logged and counted. Quiet when
                     no Manager is over the lanes.

Switched by CHURCH_TEAM_ROLLUP: off | owner | on. Owner (the default) means
the platform owner's own church (member_asks.platform_church), for the
overseer's See as, the team page and the roll-up alike; the owner's and the
admins' See as is unchanged whatever it says. The roll-up runs on the worker:
set it on both Railway services. No migration.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import church_areas
import church_duties as cd
import sb_clients
from auth_supabase import AuthedUser, UserSession
from business_access import business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

OVERSEE = "oversee_lanes"            # the church duty (church_duties.CATALOG)
KEY = "church_team_rollup"           # businesses.settings[KEY]: the last roll-up
NAV = "operate:my-week"
KEEPS_ALL = ("owner", "admin")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TASKS_READ = 500                     # a login's open tasks, read at once
TASKS_SHOWN = 5                      # on its row, late first
LATE_NAMED = 5                       # the email names this many late tasks a login, then "and N more"
TEAM_WORKERS = 6                     # logins read side by side on the team page
NOT_CHURCH = "The team page is for churches"


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_TEAM_ROLLUP") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def church_open(business_id: Any) -> bool:
    """On, or (owner) the platform owner's own church. The Executive Pastor
    isn't the platform owner, so an owner switch is her church's, as the
    member side's switches are."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        import member_asks
        return member_asks.platform_church(business_id)
    return False


# ─── Who is over the lanes ───────────────────────────────────────────

def overseer(business_id: Any, user: AuthedUser, role: Optional[str]) -> bool:
    """Whether this login is over the office's lanes here: the owner and the
    admins always; a Manager that does oversee_lanes (church_duties: the
    Executive Pastor by default, or whoever it was moved to). A failed read
    of the duty is a 503, never a yes."""
    if role in KEEPS_ALL:
        return True
    if role != "manager":
        return False
    return cd.holds(str(business_id), user, OVERSEE)


CARE = "people_care"


def view_of(business_id: Any, user_id: str, role: Optional[str]) -> Optional[List[str]]:
    """The areas this login sees itself, or None for the whole church (the
    owner and the admins always; anyone while Who sees what is off). A duty
    never widens what a login sees (docs/CHURCH_DUTIES.md, rule 5), so what
    the overseer reads of her team stays inside her own areas. A view that
    can't be read is a 503, never everything."""
    if role in KEEPS_ALL or church_areas.mode() != "on":
        return None
    view = church_areas.my_areas(str(business_id), str(user_id), role)
    if view is None:
        raise HTTPException(503, "Your areas couldn't be read just now. Try again.")
    areas = view.get("areas")
    return None if areas is None else [str(a) for a in areas]


def within(week: Dict[str, Any], areas: Optional[List[str]]) -> Dict[str, Any]:
    """Another Manager's week (church_my_week.build) as the overseer may
    read it: only what lies in the areas she sees herself. Her own view the
    whole church: the week as it is. A task handed to the login is its own,
    whatever area it's filed under, so it always shows; people in follow-up
    and care handed to them are People & care's; a first check-in is Kids &
    youth's too; each area's line and gaps are that area's. What the office
    sent the login's person (`from_office`) is theirs alone: never in
    another's view of their week, whatever areas (#1804 review)."""
    week = {k: v for k, v in week.items() if k != "from_office"}
    if isinstance(week.get("counts"), dict):
        week["counts"] = {k: v for k, v in week["counts"].items() if k != "from_office"}
    if areas is None:
        return week
    mine = set(areas)
    items = [n for n in ([week["next"]] if week.get("next") else []) + list(week.get("needs") or [])
             if n.get("kind") == "task" or n.get("area") in mine]
    handed = list(week.get("handed") or [])
    if CARE not in mine:
        handed = [h for h in handed if h.get("from") == "Kids check-in"] if "kids_youth" in mine else []
    shown = [a for a in week.get("areas") or [] if a.get("key") in mine]
    return {**week, "areas": shown, "next": items[0] if items else None, "needs": items[1:], "handed": handed,
            "counts": {"needs": len(items), "areas": len(shown), "handed": len(handed)}}


# ─── Small things ─────────────────────────────────────────────────────

def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


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


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "The team couldn't be read just now. Try again.")
    return rows


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def _clt():
    import church_leader_tasks
    return church_leader_tasks


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_key(d: date) -> str:
    """The ISO week a church day is in: '2026-W45'."""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _zone(biz: Dict[str, Any]):
    tz = _clt().zone(biz)
    if tz is None:
        raise HTTPException(503, "The church's clock couldn't be read just now. Try again.")
    return tz


# ─── What's due this week ─────────────────────────────────────────────

def due_this_week(duties: Iterable[str], monday: date, picked: Optional[Dict[str, str]] = None
                  ) -> List[Dict[str, Any]]:
    """Each duty's day in the catalog, for the week that starts `monday`:
    [{duty, label, days, text}], by the first day, catalog order within it.
    "first Monday" is this week's only when this Monday is the month's first;
    "weekly", "monthly" and "as needed" name no day. A day the login picked
    (`picked`, church_assignments: duty -> day) stands in for the catalog's,
    and a weekly or as-needed job with one has that day. Never a money duty."""
    import church_assignments as cas
    have = set(duties)
    out = []
    for key, d in cd.CATALOG.items():
        if key not in have or d["money"]:
            continue
        day = str(d.get("day") or "")
        toks = [t.strip() for t in day.split(",")]
        once_a_month = "monthly" in toks and not any(t in WEEKDAYS for t in toks)
        if (picked or {}).get(key) and cas.movable(key) and not once_a_month:
            day = cas.day_with(day, picked[key])      # a job once a month stays out of the week
        days: List[str] = []
        for tok in (t.strip() for t in str(day or "").split(",")):
            if tok in WEEKDAYS and tok not in days:
                days.append(tok)
            elif tok.lower() == "first monday" and monday.day <= 7 and "Mon" not in days:
                days.append("Mon")
        if days:
            out.append({"duty": key, "label": d["label"], "days": days, "text": f"{', '.join(days)}: {d['label']}"})
    out.sort(key=lambda w: WEEKDAYS.index(w["days"][0]))
    return out


# ─── One login's row ──────────────────────────────────────────────────

def _name(raw: str) -> str:
    """A login's name for the team: never a whole email address."""
    raw = _plain(raw)
    return (raw.split("@")[0] or "An office login") if "@" in raw else (raw or "An office login")


def seat_name(biz: str, seat: Dict[str, Any]) -> str:
    """Who a login is, as the app greets them (business_users_router.seat_person:
    its person, by its tied record or its one email; else the name it gave),
    else the part of its email before the @."""
    try:
        import business_users_router
        who = business_users_router.seat_person(biz, str(seat["user_id"])) or {}
    except Exception:
        who = {}
    return _name(str(who.get("name") or "") or str(seat.get("name") or "") or str(seat.get("invited_email") or ""))


def _lane_words(lanes: Iterable[str]) -> Optional[str]:
    keys = sorted(lanes, key=lambda k: (k != cd.EXEC, cd.LANE_KEYS.index(k) if k in cd.LANE_KEYS else 99))
    return " · ".join(cd.lane_label(k) for k in keys) or None


def _person_ids(biz: str, seat: Dict[str, Any]) -> List[str]:
    """The church's people this login is: its tied record, and any record
    its sign-in email names (as My week matches a follow-up's leader)."""
    ids = {str(seat["contact_id"])} if seat.get("contact_id") else set()
    email = (seat.get("invited_email") or "").strip().lower()
    if "@" in email:
        for c in _need(f"/contacts?business_id=eq.{_q(biz)}&email=ilike.{_q(church_areas._escape_ilike(email))}"
                       "&select=id&limit=10"):
            if c.get("id"):
                ids.add(str(c["id"]))
    return sorted(ids)


def row(biz: Dict[str, Any], seat: Dict[str, Any], name: str, now: datetime, today: date,
        monday: date, care: bool = True, picked: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One Manager login's week, in counts. Raises a 503 when a read fails.
    `care` False (an overseer whose areas leave People & care out): no
    follow-up or care counts, and nothing is read for them. `picked`: the
    days this login picked for its duties (read once for the team)."""
    b, uid = str(biz["id"]), str(seat["user_id"])
    s = cd.standing(b, uid)
    clt = _clt()
    items = []
    for t in _need(f"/tasks?business_id=eq.{_q(b)}&assigned_to=eq.{_q(uid)}&status=neq.done"
                   f"&select=id,title,due_date&order=due_date.asc.nullslast&limit={TASKS_READ}"):
        due = str(t.get("due_date") or "")[:10]
        items.append({"title": _plain(t.get("title"))[:200] or "A task", "due": due or None,
                      "due_text": clt.due_words(due, today)["text"], "late": bool(due and due < today.isoformat())})
    items.sort(key=lambda i: (not i["late"], i["due"] or "9999-12-31"))
    week = due_this_week(s["duties"], monday, picked)
    late = sum(1 for i in items if i["late"])
    out = {"user_id": uid, "name": name, "lane": _lane_words(s["lanes"]), "lanes": list(s["lanes"]),
           "_duties": frozenset(s["duties"]),
           "ok": True, "status": 200,
           "tasks": {"open": len(items), "late": late, "items": items[:TASKS_SHOWN],
                     "late_items": [i for i in items if i["late"]][:LATE_NAMED]},
           "this_week": week, "this_week_text": " · ".join(w["text"] for w in week)}
    if care:
        ids = _person_ids(b, seat)
        fu_open = fu_late = 0
        if ids:
            fus = _need(f"/church_follow_ups?business_id=eq.{_q(b)}&leader_contact_id=in.({','.join(_q(i) for i in ids)})"
                        "&status=eq.open&select=id,due_at&limit=1000")
            fu_open = len(fus)
            fu_late = sum(1 for f in fus if (_at(f.get("due_at")) or now) < now)
        asked = _need(f"/ministry_care_requests?business_id=eq.{_q(b)}&assigned_to=eq.{_q(uid)}"
                      "&status=in.(new,reviewed)&select=id&limit=500")
        out["follow_ups"] = {"open": fu_open, "late": fu_late}
        out["care"] = {"open": len(asked)}
    return out


# The areas behind the keeper wall for an overseer who doesn't work People &
# care: a judged job in one keeps its done / not yet / late, never its words
# (a count of people in follow-up, of drifting families).
WALLED = ("people_care", "kids_youth", "groups_classes")


def walled(w: Dict[str, Any]) -> Dict[str, Any]:
    """One job due this week without its check's words when it's in a walled area."""
    if w.get("detail") is not None and (cd.CATALOG.get(w.get("duty")) or {}).get("area") in WALLED:
        return {k: v for k, v in w.items() if k != "detail"}
    return w


def without_care(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The rows without their follow-up and care counts (People & care's),
    and without the words of any judged job in a walled area."""
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k not in ("follow_ups", "care")}
        if r.get("this_week"):
            r["this_week"] = [walled(w) for w in r["this_week"]]
        out.append(r)
    return out


def unread_row(seat: Dict[str, Any], name: str, err: HTTPException) -> Dict[str, Any]:
    lane = cd._seat_lane(seat)
    first = name.split(" ")[0] or "This login"
    return {"user_id": str(seat["user_id"]), "name": name, "lane": cd.lane_label(lane) if lane else None,
            "lanes": [lane] if lane else [], "ok": False, "status": err.status_code,
            "error": f"{first}'s week couldn't be read just now. Try again."}


# ─── The team ─────────────────────────────────────────────────────────

def team(biz: Dict[str, Any], now: Optional[datetime] = None, exclude: Optional[str] = None,
         care: bool = True) -> Dict[str, Any]:
    """Every active Manager login on the church but `exclude` (the overseer
    asking: her own week is My week), each a row. The seats and the church's
    clock must answer (a 503 for the page); one login's own reads failing is
    a 503 for its row alone. A name that can't be read is the part of the
    login's email before the @. `care` False leaves out the follow-up and
    care counts (an overseer whose own areas leave People & care out).
    The logins are read side by side (TEAM_WORKERS at a time): each is a
    dozen reads of its own, and one after another a team of five took the
    page ten seconds and more."""
    now = now or _now()
    b = str(biz["id"])
    tz = _zone(biz)
    today = now.astimezone(tz).date()
    monday = monday_of(today)
    seats = [s for s in cd._seats(b) if s.get("role") == "manager" and str(s["user_id"]) != str(exclude or "")]
    # The days each login picked (church_assignments), one read for the team.
    import church_assignments as cas
    picks = cas.days_for(biz, [s["user_id"] for s in seats])

    def one(s: Dict[str, Any]) -> Dict[str, Any]:
        name = seat_name(b, s)
        try:
            return row(biz, s, name, now, today, monday, care, picks.get(str(s["user_id"])))
        except HTTPException as e:
            if e.status_code != 503:
                raise
            print(f"[church_team_week] {b[:8]}: a login's week couldn't be read")
            return unread_row(s, name, e)

    if len(seats) > 1:
        with ThreadPoolExecutor(max_workers=min(TEAM_WORKERS, len(seats)), thread_name_prefix="church-team") as pool:
            rows = list(pool.map(one, seats))      # in the seats' order; a refusal that isn't a 503 still raises
    else:
        rows = [one(s) for s in seats]
    rows.sort(key=lambda r: (cd.EXEC not in r["lanes"], r["name"].lower()))
    page = {
        "church": _plain(biz.get("name")) or "Your church",
        "today": today.isoformat(),
        "week": {"monday": monday.isoformat(), "words": f"the week of {monday:%B} {monday.day}"},
        "team": rows,
        "care": care,
        "counts": {"logins": len(rows), "late_tasks": sum(r["tasks"]["late"] for r in rows if r["ok"]),
                   "unread": sum(1 for r in rows if not r["ok"])},
    }
    import church_over
    if church_over.church_open(b):
        judge_week(biz, rows, now, today, tz, picks, care)
        page["counts"]["late_jobs"] = sum(r.get("this_week_counts", {}).get("late", 0) for r in rows if r["ok"])
    for r in rows:
        r.pop("_duties", None)
    return page


def judge_week(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, today: date, tz,
               picks: Dict[str, Dict[str, str]], care: bool = True) -> None:
    """Each row's jobs due this week, judged (church_my_week._done_full):
    `state` done / not_yet / late, `state_text`, `detail` (what the check
    counted) and `due` on each one a check judges, `this_week_counts`, and
    `last_week` (church_my_week.last_week: last week's result, judged at the
    end of each job's day). One church_work_checks.Ctx for the whole team,
    after the rows are read, so each table is read once for the church,
    never once a login. A job no check judges, or one whose read failed,
    keeps only its day. `care` False (an overseer who doesn't work People &
    care): a job in a walled area keeps its state and never its words."""
    import church_my_week as mw
    import church_work_checks as cw
    ctx = cw.Ctx(biz, now, tz)
    monday = monday_of(today)
    for r in rows:
        if not r.get("ok"):
            continue
        mine = picks.get(str(r["user_id"])) or {}
        judged = mw._done_full(biz, frozenset(w["duty"] for w in r["this_week"]), today, now, tz,
                               picks=mine, ctx=ctx)
        counts = {"done": 0, "not_yet": 0, "late": 0}
        for w in r["this_week"]:
            due = mw.due_day(w["duty"], monday, mine.get(w["duty"]), today)
            got = judged.get(w["duty"])
            state = mw.job_state(got["done"], due, today) if got else None
            if state:
                w.update(state=state, state_text=mw.STATE_TEXT[state], detail=got["text"], due=due.isoformat())
                counts[state] += 1
        if not care:
            r["this_week"] = [walled(w) for w in r["this_week"]]
        r["this_week_counts"] = counts
        last = mw.last_week(biz, r.get("_duties") or frozenset(), today, now, tz, picks=mine, ctx=ctx)
        if last:
            r["last_week"] = last


@router.get("/my-week/team")
def my_team(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
            biz: Dict[str, Any] = Depends(business_access("manager"))):
    """The office's Manager logins' weeks, for whoever is over the lanes
    (oversee_lanes), the owner or an admin. A Manager that isn't over them
    is told whose job it is."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    import church_my_week
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    bid = str(biz["id"])
    if not church_open(bid):
        raise HTTPException(404, "Not Found")
    uid = str(session.user.id)
    role = church_my_week._role(biz, uid)
    if not overseer(bid, session.user, role):
        raise HTTPException(403, cd.refusal(bid, OVERSEE))
    areas = view_of(bid, uid, role)
    return team(biz, exclude=uid if role == "manager" else None, care=areas is None or CARE in areas)


# ─── Monday: the roll-up ──────────────────────────────────────────────

def _line(r: Dict[str, Any]) -> str:
    """One login, in plain words."""
    head = r["name"] + (f", {r['lane']}" if r.get("lane") else "")
    if not r["ok"]:
        return f"{head}\nTheir week couldn't be read this morning. It's on the Team page in the app."
    clt = _clt()
    lines = [head]
    t = r["tasks"]
    late = t.get("late_items") or []
    if late:
        named = [f"“{i['title']}” (due {clt.day_words(date.fromisoformat(i['due']))})" for i in late]
        more = t["late"] - len(named)
        if more > 0:
            said = ", ".join(named) + f" and {more} more"
        else:
            said = ", ".join(named[:-1]) + (" and " if len(named) > 1 else "") + named[-1]
        lines.append(f"Late: {said}.")
    counts = []
    if t["open"]:
        counts.append(_n(t["open"], "open task", "open tasks") + (f", {t['late']} late" if t["late"] else ""))
    fu = r.get("follow_ups") or {}
    if fu.get("open"):
        counts.append(_n(fu["open"], "follow-up", "follow-ups") + " open" + (f", {fu['late']} late" if fu["late"] else ""))
    if (r.get("care") or {}).get("open"):
        counts.append(_n(r["care"]["open"], "prayer or care request", "prayer or care requests") + " open")
    if counts:
        lines.append(("" if late else "Nothing late. ") + "; ".join(counts) + ".")
    else:
        lines.append("Nothing handed to them is open.")
    if r["this_week"]:
        late_jobs = [w["label"] for w in r["this_week"] if w.get("state") == "late"]
        if late_jobs:
            lines.append("Late on the week: " + ", ".join(late_jobs) + ".")
        lines.append("This week: " + week_said(r))
    if r.get("last_week"):
        lines.append(r["last_week"]["text"] + ".")
    return "\n".join(lines)


def week_said(r: Dict[str, Any]) -> str:
    """A row's jobs due this week, each with its day and, where a check
    judged it, done / not yet / late: "Mon: First-time guests and welcome
    calls (late) · Wed: The weekly text and email (not yet)"."""
    return " · ".join(w["text"] + (f" ({w['state_text'].lower()})" if w.get("state") else "")
                      for w in r.get("this_week") or [])


def rollup_text(name: str, page: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    clt = _clt()
    lines = [f"Hi {clt.first_name(name) or 'there'},",
             f"Here is the office team, {page['week']['words']}: who's late on what, and what's due this week."]
    lines += [_line(r) for r in rows]
    lines.append("It's all on the Team page in the app, and you can open any of their weeks from there.")
    return "\n\n".join(lines)


def rollup_subject(rows: List[Dict[str, Any]]) -> str:
    late = sum(r["tasks"]["late"] for r in rows if r["ok"])
    return f"Your team this week: {_n(late, 'task', 'tasks')} late" if late else "Your team this week: nothing late"


def _settings(biz: Dict[str, Any]) -> Dict[str, Any]:
    s = biz.get("settings")
    return s if isinstance(s, dict) else {}


def last_of(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rec = _settings(biz).get(KEY)
    return rec if isinstance(rec, dict) and rec.get("id") else None


def swap(biz_id: str, expect: Optional[str], rec: Optional[Dict[str, Any]]) -> bool:
    """Put `rec` where the last roll-up is kept (None takes it away), only if
    what's there is still `expect` (a roll-up's id, or nothing): the live
    settings are read fresh and merged, and the write is filtered on the
    roll-up's id, so two replicas claim a week once (church_leaders_note.swap)."""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,settings&limit=1")
    if not isinstance(rows, list) or not rows:
        return False
    settings = dict(_settings(rows[0]))
    have = settings.get(KEY) if isinstance(settings.get(KEY), dict) else None
    if (have or {}).get("id") != expect:
        return False
    if rec is None:
        settings.pop(KEY, None)
    else:
        settings[KEY] = rec
    where = f"settings->{KEY}->>id=eq.{_q(expect)}" if expect else f"settings->{KEY}=is.null"
    got = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz_id)}&{where}", {"settings": settings})
    return isinstance(got, list) and bool(got)


def _push(user_id: str, biz_id: str, title: str, body: str, tag: str) -> None:
    try:
        import push_notifications
        push_notifications.send_to_user(user_id, title=title[:80], body=body[:160], nav=NAV, tag=tag[:60],
                                        business_id=biz_id)
    except Exception:
        logger.info("team roll-up: a push didn't go (business %s)", biz_id[:8], exc_info=True)


def run_church(biz: Dict[str, Any], now: datetime, stats: Dict[str, int]) -> None:
    """Monday morning on this church's clock: the week's roll-up, once."""
    clt = _clt()
    b = str(biz["id"])
    tz = clt.zone(biz)
    if tz is None:
        return
    local = now.astimezone(tz)
    if local.weekday() != 0 or not clt.LATE_FROM <= local.hour < clt.LATE_UNTIL:
        return
    if not church_open(b):
        return
    week = week_key(local.date())
    last = last_of(biz)
    # This week's roll-up went to everyone it could, or is going now: done.
    # One that reached some and not others (`partial`) tries the rest again.
    told: List[str] = []
    if last and last.get("week") == week:
        if last.get("state") != "partial":
            stats["already"] += 1
            return
        told = [str(u) for u in last.get("to") or []]
    try:
        holders = cd.manager_holders(b, OVERSEE)
        if not holders:
            stats["no_one"] += 1
            return
        page = team(biz, now)
    except HTTPException:
        stats["unread"] += 1
        return  # the next hour of the morning tries again
    names = {r["user_id"]: r["name"] for r in page["team"]}
    letters = [(uid, [r for r in page["team"] if r["user_id"] != uid]) for uid in holders if uid not in told]
    letters = [(uid, rows) for uid, rows in letters if rows]
    if not letters:
        if told:
            _record(b, last, {**last, "state": "sent"}, stats)   # whoever was left has no team to hear about
        else:
            stats["no_team"] += 1
        return
    claim = {"id": uuid.uuid4().hex, "week": week, "state": "sending", "at": _iso(now), "sent": len(told), "to": told}
    if not swap(b, (last or {}).get("id"), claim):
        return
    import church_office_tasks as cot
    link = cot._link(b)
    reply_to = clt._office_email(biz)
    sent: List[str] = []
    unsent = 0
    for uid, rows in letters:
        email = clt.hander_email(biz, uid)
        if not email:
            stats["no_email"] += 1
            continue
        # Each holder reads only what her own areas hold: People & care's
        # counts stay out for one whose areas leave it out (or can't be read).
        try:
            areas = view_of(b, uid, "manager")
        except HTTPException:
            areas = []
        if areas is not None and CARE not in areas:
            rows = without_care(rows)
        name = names.get(uid, "")
        subject = rollup_subject(rows)
        try:
            html = cot.render(biz, rollup_text(name, page, rows), subject, link, "Open the team")
            clt.deliver(biz, email, name, subject, html, f"team-rollup-{b}-{week}-{uid}", reply_to=reply_to)
        except Exception:
            logger.warning("team roll-up: an email failed (business %s)", b[:8], exc_info=True)
            unsent += 1
            continue
        sent.append(uid)
        late = sum(r["tasks"]["late"] for r in rows if r["ok"])
        _push(uid, b, "Your team this week",
              f"{_n(late, 'task', 'tasks')} late on the team." if late else "Nothing late on the team.",
              f"team-{week}")
    stats["sent"] += len(sent)
    stats["unsent"] += unsent
    if not sent and unsent:
        _record(b, claim, last, stats)    # nothing went: the week is as it was, for the next hour
        return
    everyone = told + sent
    _record(b, claim, {**claim, "state": "partial" if unsent else "sent", "sent": len(everyone), "to": everyone}, stats)


def _record(biz_id: str, claim: Dict[str, Any], rec: Optional[Dict[str, Any]], stats: Dict[str, int]) -> None:
    """Swap the week's claim for what happened. A write that doesn't land is
    said in the log and the stats: the week would otherwise sit as sending,
    with nobody told, until next Monday."""
    if not swap(biz_id, claim["id"], rec):
        stats["unrecorded"] += 1
        print(f"[church_team_week] {biz_id[:8]}: the roll-up's record didn't save (week {claim.get('week')})")


def rollup_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, on the worker (kmj_intake_automation): every church with a
    Manager login, its roll-up in its Monday morning. A church that fails
    never stops the others. Quiet with the switch off."""
    stats = {"churches": 0, "sent": 0, "unsent": 0, "no_email": 0, "no_one": 0, "no_team": 0,
             "already": 0, "unread": 0, "unrecorded": 0}
    if mode() == "off":
        return stats
    now = now or _now()
    seats = _rows("/business_users?role=eq.manager&status=eq.active&select=business_id&limit=20000")
    if seats is None:
        return stats
    ids = sorted({str(s["business_id"]) for s in seats if s.get("business_id")})
    import church_follow_up as cfu
    for chunk in _clt()._chunks(ids):
        for biz in _rows(f"/businesses?id=in.({','.join(_q(i) for i in chunk)})"
                         "&select=id,name,type,settings,owner_id&limit=100") or []:
            if not cfu.is_church(biz):
                continue
            stats["churches"] += 1
            try:
                run_church(biz, now, stats)
            except Exception:
                logger.warning("team roll-up failed for business %s", str(biz.get("id"))[:8], exc_info=True)
    return stats
