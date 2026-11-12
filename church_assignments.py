"""church_assignments.py — whoever is over people starts them, hands them work
and sees it move (docs/CHURCH_ASSIGNMENTS.md, PR A).

Kevin, 2026-11-11: "lets build what is missing", "we also need to allow for
the admin to pick days for work load that works for them", "we also need to
allow for Jessica to be able to hand out assignments to each of them as
well", and "this needs to be a way for churches to set this up in a general
sense when they establish leaders over people."

An assignment IS a task (public.tasks), handed to one login (assigned_to) or
one of the church's people (assigned_contact_id). Everything that tells,
escalates and shows a handed task already works on it: the hand-off email
and push (church_office_tasks, church_leader_tasks: grouped here into one
email a person a sweep when several arrive together), late going up, My week,
the team page, the Monday roll-up, the Lead tab. The new columns
(supabase/APPLY-2026-11-12-church-assignments.sql) only add what an
assignment has that a task didn't: its duty, what done means, the check that
can tick it off, the start-up item it came from, stuck, and sent up.

Who is over whom is church_over's; every route checks it for anything about
someone else, and reads each task with its church and its person first.

  GET    /church/assignments/people?business_id=     the board: each person under
                                                     me, with open, late, stuck,
                                                     done in the last 7 days, and
                                                     their first assignment n of m
  GET    /church/assignments?business_id=&for=       their assignments (them, or
                                                     anyone over them)
  POST   /church/assignments                         hand one out (anyone over
                                                     them, or yourself)
  PATCH  /church/assignments/{task_id}               done, stuck (them, or anyone
                                                     over them); the date, title
                                                     and done_when (the one over
                                                     them, or whoever handed it)
  DELETE /church/assignments/{task_id}?business_id=  take it back (whoever handed
                                                     it, or anyone over them)
  POST   /church/assignments/{task_id}/raise         send a stuck one up to whoever
                                                     is over me (anyone over them)
  POST   /church/assignments/start                   make their first assignment
                                                     (anyone over them)
  GET    /church/assignments/one-on-one?business_id=&for=
                                                     a one-on-one (anyone over
                                                     them): finished, stuck, late,
                                                     next, this week's jobs; plain
                                                     lines; nothing recorded
  GET    /church/duty-days?business_id=&user_id=     each duty a login holds, its
                                                     catalog day, its picked day
  PUT    /church/duty-days                           pick one (the login, or anyone
                                                     over it); null puts it back

`for` is login:<user id> or person:<contact id>. Every write answers with what
it saved; a failed write is a 503, never a 200. Money never travels through
this: no start-up item is a money duty, a Manager or a person is never handed
one, and nothing here shows an amount.

Picked days (church_duty_days, server-only) are read wherever a duty's day is
read: church_my_week.rhythm, church_team_week.due_this_week (the team page and
the Monday roll-up). A duty whose catalog day names Saturday or Sunday (the
Sunday jobs) doesn't move, nor the first-Monday report (its date is the
monthly report's own); a weekly, as-needed or monthly one can take a day.

The hourly sweep (sweep_tick, on the worker) tells whoever a stuck item was
sent up to, once, and ticks off open items whose check now passes.

Switched by CHURCH_ASSIGNMENTS (church_over.mode): off | owner | on, default
owner (the platform owner's own church). Closed, the routes answer 404 and
nothing reads the new columns. Set it on both Railway services.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query

import business_access
import church_over as co
import church_startup as cs
import church_work_checks as cw
import sb_clients
from auth_supabase import UserSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

FIELDS = ("id,business_id,title,description,status,due_date,assigned_to,assigned_contact_id,handed_by,created_at,"
          "completed_at,duty,done_when,check_key,startup_key,stuck_note,stuck_at,raised_at,raised_to,"
          "raised_to_contact_id,raised_by,raised_told_at,checked_at")
DONE_DAYS = 14             # a person's list shows what was done in the last two weeks
BOARD_DONE_DAYS = 7        # the board counts the last week's
READ_MAX = 1000
STUCK_SHOWN, NEXT_SHOWN = 5, 3
TITLE_MAX, DONE_WHEN_MAX, STUCK_MAX, NOTES_MAX = 200, 300, 500, 1500
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
NOT_CHURCH = "Assignments are for churches"
NOT_OVER = "They aren't someone you're over here."
NOT_YOURS = "That isn't one of the assignments you can see."
UNREAD = "The assignments couldn't be read just now. Try again."
UNSAVED = "That didn't save. Try again."
NAV = "operate:my-week"


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


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _day(v: Any) -> Optional[str]:
    """A due date as the routes take it: YYYY-MM-DD, or none."""
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, "A due date is a day, like 2026-11-20")


def _first(name: str) -> str:
    return _plain(name).split(" ")[0] or "Someone"


def _join(names: List[str]) -> str:
    names = [n for n in dict.fromkeys(names) if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _clt():
    import church_leader_tasks
    return church_leader_tasks


def _target_of(t: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if t.get("assigned_to"):
        return co.who(co.LOGIN, t["assigned_to"])
    if t.get("assigned_contact_id"):
        return co.who(co.PERSON, t["assigned_contact_id"])
    return None


# ─── Picked days ──────────────────────────────────────────────────────

def movable(duty: str) -> bool:
    """Whether a duty's day can be picked: not a Sunday job (its catalog day
    names Saturday or Sunday), not the first-Monday report; a weekly, as
    needed or monthly one can take a day."""
    import church_duties as cd
    d = cd.CATALOG.get(duty)
    if not d:
        return False
    toks = {t.strip().lower() for t in str(d.get("day") or "").split(",")}
    return not ({"sat", "sun"} & toks) and "first monday" not in toks


def day_with(catalog_day: str, picked: Optional[str]) -> str:
    """A duty's catalog day with its picked day in it: "Thu" for a weekly
    one, "Thu, monthly" for a monthly one (still once a month)."""
    if picked not in WEEKDAYS:
        return catalog_day
    toks = [t.strip().lower() for t in str(catalog_day or "").split(",")]
    return f"{picked}, monthly" if "monthly" in toks else str(picked)


def picked_days(business_id: Any, user_ids: Iterable[Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """user id -> {duty: picked day}, one read. None when it failed."""
    ids = sorted({str(u) for u in user_ids if u})
    if not ids:
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/church_duty_days?business_id=eq.{_q(business_id)}&user_id=in.({','.join(_q(u) for u in ids)})"
        "&select=user_id,duty,day&limit=2000")
    if not isinstance(rows, list):
        return None
    out: Dict[str, Dict[str, str]] = {}
    for r in rows:
        if r.get("day") in WEEKDAYS and movable(str(r.get("duty") or "")):
            out.setdefault(str(r["user_id"]), {})[str(r["duty"])] = str(r["day"])
    return out


def days_for(business: Any, user_ids: Iterable[Any]) -> Dict[str, Dict[str, str]]:
    """What the readers (My week's rhythm, the team page, the roll-up) use:
    the picked days where the switch is open for the church, else none. A
    read that fails is the catalog's days, said in the log."""
    bid = str(business.get("id") if isinstance(business, dict) else business)
    if not co.church_open(bid):
        return {}
    got = picked_days(bid, user_ids)
    if got is None:
        print(f"[church_assignments] {bid[:8]}: picked days unread; the catalog's days stand", flush=True)
        return {}
    return got


# ─── One assignment, as the app shows it ──────────────────────────────

def _names_by_login(ch: co.Church, ids: Iterable[Any]) -> Dict[str, str]:
    out = {}
    for u in {str(i) for i in ids if i}:
        if u == ch.owner or u in ch.seats:
            out[u] = ch.login_name(u)
    return out


def item(t: Dict[str, Any], today: date, logins: Dict[str, str], people: Dict[str, str],
         check: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    clt = _clt()
    due = str(t.get("due_date") or "")[:10]
    words = clt.due_words(due, today)
    done = t.get("status") == "done"
    stuck = bool(t.get("stuck_at")) and not done
    tpl = cs.BY_KEY.get(str(t.get("startup_key") or ""))
    raised_to = (logins.get(str(t.get("raised_to") or "")) or people.get(str(t.get("raised_to_contact_id") or ""))
                 or "")
    return {
        "id": str(t["id"]), "title": _plain(t.get("title"))[:TITLE_MAX] or "An assignment",
        "notes": str(t.get("description") or "").replace("\r\n", "\n").strip()[:NOTES_MAX],
        "status": "done" if done else ("stuck" if stuck else "open"),
        "due": due or None, "due_text": words["text"], "late": not done and words["state"] == "late",
        "duty": t.get("duty") or None, "duty_label": cs.duty_label(t.get("duty")),
        "done_when": _plain(t.get("done_when")) or None,
        "startup": bool(t.get("startup_key")), "week": tpl["week"] if tpl else None,
        "check": {"done": check.get("done"), "text": check.get("text")} if check else None,
        "stuck": {"note": _plain(t.get("stuck_note")), "since": t.get("stuck_at")} if stuck else None,
        "raised": {"at": t.get("raised_at"), "to": raised_to} if stuck and t.get("raised_at") else None,
        "from": logins.get(str(t.get("handed_by") or "")) or "the church office",
        "completed_at": t.get("completed_at") if done else None, "checked": bool(done and t.get("checked_at")),
    }


def _checks(ctx: cw.Ctx, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Each open row's check, run once a kind, and the passed ones ticked off."""
    cw.tick(ctx, rows)
    return {str(t["id"]): cw.run(ctx, t["check_key"]) for t in rows if t.get("check_key") in cw.CHECKS}


def _first_counts(rows: List[Dict[str, Any]], templates: List[Dict[str, Any]]) -> Dict[str, int]:
    """Their first assignment as n of m, and how many more a start would make."""
    first = [t for t in rows if t.get("startup_key")]
    made = {str(t["startup_key"]) for t in first}
    return {"done": sum(1 for t in first if t.get("status") == "done"), "of": len(first),
            "to_make": sum(1 for t in templates if t["key"] not in made)}


# ─── The gate ─────────────────────────────────────────────────────────

def _church(session: UserSession, biz: Dict[str, Any]) -> co.Church:
    """The church, open to this login: a church (404), the switch (404)."""
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    if not co.office_open(session.user, biz):
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


def _allowed(ch: co.Church, me: Dict[str, Any], target: Dict[str, Any], *, self_ok: bool) -> bool:
    """True when `me` is over `target` (or is them, where that's allowed);
    a 403 otherwise. Returns whether `me` is over them."""
    if co.same(me, target):
        if self_ok:
            return False
        raise HTTPException(403, NOT_OVER)
    if not co.is_over(ch, me, target):
        raise HTTPException(403, NOT_OVER)
    return True


def _task(ch: co.Church, task_id: Any) -> Dict[str, Any]:
    """One of this church's tasks, handed to someone; a 404 for anything
    else, whoever's it is."""
    tid = _uuid(task_id, "assignment")
    rows = _need(f"/tasks?id=eq.{_q(tid)}&business_id=eq.{_q(ch.b)}&select={FIELDS}&limit=1")
    if not rows or str(rows[0].get("business_id")) != ch.b or not _target_of(rows[0]):
        raise HTTPException(404, NOT_YOURS)
    return rows[0]


def _theirs(t: Dict[str, Any], target: Dict[str, Any]) -> str:
    """The filter that keeps a write on the task while it's still theirs."""
    return (f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(t['business_id'])}"
            f"&{cs.column(target)}=eq.{_q(target['id'])}")


def _saved(got: Any) -> Dict[str, Any]:
    if not isinstance(got, list):
        raise HTTPException(503, UNSAVED)
    if not got:
        raise HTTPException(409, "That assignment changed hands just now. Open it again.")
    return got[0]


def _ready(ch: co.Church) -> None:
    """Before a write: read everything answering with what it saved will
    need (the seats, who each login is, the owner's sign-in email, the top
    and the seniors). A read that fails then is a 503 with nothing saved, and
    nothing after the write can fail on it (#1801 review: a self-handed task
    saved, answered 503 on a cold Auth read, and a retry made a second copy)."""
    _ = (ch.seats, ch.login_person, ch.top, ch.seniors, ch.tz)


def _after(fn, default):
    """A name read after a write that already saved: one that fails falls
    back to `default` and is said in the log, never a 503 for a saved write."""
    try:
        return fn()
    except HTTPException:
        print("[church_assignments] a name after a saved write wasn't read; answered without it", flush=True)
        return default


def _one(ch: co.Church, t: Dict[str, Any], ctx: Optional[cw.Ctx] = None) -> Dict[str, Any]:
    """A saved row as the app shows it. Never fails on a read: it answers
    writes that already saved (`check` runs catch their own failures)."""
    ctx = ctx or cw.Ctx(ch.business, _now(), ch.tz)
    check = cw.run(ctx, t["check_key"]) if t.get("check_key") and t.get("status") != "done" else None
    logins = _after(lambda: _names_by_login(ch, [t.get("handed_by"), t.get("raised_to")]), {})
    people = _after(lambda: ch.names([t.get("raised_to_contact_id")]), {}) if t.get("raised_to_contact_id") else {}
    return item(t, ctx.today, logins, people, check)


def _name_of(ch: co.Church, target: Dict[str, Any]) -> str:
    return ch.login_name(target["id"]) if target["kind"] == co.LOGIN else ch.names([target["id"]]).get(
        target["id"], "Someone")


# ─── The board ────────────────────────────────────────────────────────

def _since_day(now: datetime, days: int) -> str:
    """A day a day before the window opens: a value inside or=() carries no
    colon, and the exact cut is made in Python."""
    return (now.astimezone(timezone.utc) - timedelta(days=days + 1)).date().isoformat()


def _handed(ch: co.Church, now: datetime) -> List[Dict[str, Any]]:
    """Every task handed to someone at this church that's open, done in the
    last week, or a start-up item: two reads for the whole church."""
    who = "or=(assigned_to.not.is.null,assigned_contact_id.not.is.null)"
    rows = _need(f"/tasks?business_id=eq.{_q(ch.b)}&status=neq.done&{who}&select={FIELDS}"
                 f"&order=due_date.asc.nullslast&limit={READ_MAX}")
    rows += _need(f"/tasks?business_id=eq.{_q(ch.b)}&status=eq.done"
                  f"&or=(completed_at.gte.{_since_day(now, BOARD_DONE_DAYS)},startup_key.not.is.null)&select={FIELDS}"
                  f"&order=completed_at.desc&limit={READ_MAX}")
    return [r for r in rows if str(r.get("business_id")) == ch.b and _target_of(r)]


def board(ch: co.Church, me: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    ctx = cw.Ctx(ch.business, now, ch.tz)
    today = ctx.today
    people = co.under(ch, me)
    out_people: List[Dict[str, Any]] = []
    if people:
        rows = _handed(ch, now)
        _checks(ctx, [r for r in rows if r.get("status") != "done"])
        by: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            by.setdefault(co.key(_target_of(r)), []).append(r)
        logins = _names_by_login(ch, [r.get("raised_to") for r in rows])
        cut = _iso(now - timedelta(days=BOARD_DONE_DAYS))
        for p in people:
            target = co.who(p["kind"], p["id"])
            mine = by.get(co.key(target), [])
            open_ = [r for r in mine if r.get("status") != "done"]
            items = [item(r, today, logins, {}) for r in open_]
            stuck = [i for i in items if i["stuck"]]
            nxt = sorted((i for i in items if not i["stuck"]), key=lambda i: (not i["late"], i["due"] or "9999-12-31"))
            out_people.append({
                "for": co.key(target), "kind": p["kind"], "id": p["id"], "name": p["name"], "why": p["why"],
                "open": len(open_), "late": sum(1 for i in items if i["late"]), "stuck": len(stuck),
                "done_7d": sum(1 for r in mine if r.get("status") == "done" and str(r.get("completed_at") or "") >= cut),
                "first": _first_counts(mine, cs.for_who(ch, target)),
                "stuck_items": [{"id": i["id"], "title": i["title"], "note": i["stuck"]["note"],
                                 "since": i["stuck"]["since"], "raised": i["raised"] is not None} for i in stuck][:STUCK_SHOWN],
                "next": [{"id": i["id"], "title": i["title"], "due": i["due"], "due_text": i["due_text"],
                          "late": i["late"]} for i in nxt][:NEXT_SHOWN],
            })
    return {"church": _plain(ch.business.get("name")) or "Your church", "today": today.isoformat(),
            "me": {"for": co.key(me), "name": ch.login_name(me["id"]) if me["kind"] == co.LOGIN else ""},
            "people": out_people,
            "counts": {"people": len(out_people), "late": sum(p["late"] for p in out_people),
                       "stuck": sum(p["stuck"] for p in out_people)}}


@router.get("/assignments/people")
def assignments_people(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                       biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """The board: each person under me, with their assignments in counts.
    Nobody under me is an empty list, never a refusal; a read that fails is
    a 503."""
    ch = _church(session, biz)
    return board(ch, _me(session))


# ─── One person's assignments ─────────────────────────────────────────

def theirs(ch: co.Church, me: Dict[str, Any], target: Dict[str, Any], over: bool,
           now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or _now()
    ctx = cw.Ctx(ch.business, now, ch.tz)
    q = f"/tasks?business_id=eq.{_q(ch.b)}&{cs.column(target)}=eq.{_q(target['id'])}"
    open_rows = _need(f"{q}&status=neq.done&select={FIELDS}&order=due_date.asc.nullslast&limit={READ_MAX}")
    since = _iso(now - timedelta(days=DONE_DAYS))
    done_rows = _need(f"{q}&status=eq.done&or=(completed_at.gte.{_since_day(now, DONE_DAYS)},startup_key.not.is.null)"
                      f"&select={FIELDS}&order=completed_at.desc&limit={READ_MAX}")
    mine = [r for r in open_rows + done_rows if str(r.get("business_id")) == ch.b
            and co.same(_target_of(r) or {}, target)]
    open_ = [r for r in mine if r.get("status") != "done"]
    checks = _checks(ctx, open_)
    raised: List[Dict[str, Any]] = []
    if co.same(me, target) and target["kind"] == co.LOGIN:
        # What was sent up to me: still stuck, or done in the last two weeks
        # (resolved: it never vanishes without a word).
        raised = [r for r in _need(
            f"/tasks?business_id=eq.{_q(ch.b)}&raised_to=eq.{_q(target['id'])}&raised_at=not.is.null"
            f"&or=(status.neq.done,completed_at.gte.{_since_day(now, DONE_DAYS)})&select={FIELDS}"
            "&order=raised_at.desc&limit=50")
            if str(r.get("business_id")) == ch.b and str(r.get("raised_to") or "") == target["id"]
            and (r.get("stuck_at") if r.get("status") != "done" else str(r.get("completed_at") or "") >= since)]
    logins = _names_by_login(ch, [r.get(k) for r in mine + raised for k in ("handed_by", "raised_to")])
    people = ch.names([r.get("raised_to_contact_id") for r in mine if r.get("raised_to_contact_id")])
    items = [item(r, ctx.today, logins, people, checks.get(str(r["id"]))) for r in mine]
    whose = {**_names_by_login(ch, [r.get("assigned_to") for r in raised]),
             **ch.names([r.get("assigned_contact_id") for r in raised if r.get("assigned_contact_id")])}
    open_items = sorted((i for i in items if i["status"] == "open"), key=lambda i: (not i["late"], i["due"] or "9999-12-31"))
    done_items = sorted((i for i in items if i["status"] == "done" and str(i["completed_at"] or "") >= since),
                        key=lambda i: str(i["completed_at"] or ""), reverse=True)
    return {
        "for": co.key(target), "kind": target["kind"], "id": target["id"], "name": _name_of(ch, target),
        "mine": co.same(me, target), "can_change": over, "today": ctx.today.isoformat(),
        "first": _first_counts(mine, cs.for_who(ch, target)),
        "open": open_items,
        "stuck": [i for i in items if i["status"] == "stuck"],
        "done": done_items,
        "raised_to_you": [{**item(r, ctx.today, logins, {}),
                           "whose": whose.get(str(r.get("assigned_to") or r.get("assigned_contact_id") or ""), ""),
                           "sent_up_at": r.get("raised_at"), "resolved": r.get("status") == "done"}
                          for r in raised],
    }


@router.get("/assignments")
def assignments_list(business_id: str, for_: str = Query("", alias="for"),
                     session: UserSession = Depends(sb_clients.authed_request),
                     biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Someone's assignments: open (late first), stuck, done in the last two
    weeks (start-up items always, for n of m), each with its check's words.
    Yours, or anyone's you're over; `can_change` says you may change the
    date, the title and what done means. Your own list carries what was sent
    up to you."""
    ch = _church(session, biz)
    me = _me(session)
    target = co.parse_for(for_) if for_ else me
    over = _allowed(ch, me, target, self_ok=True)
    return theirs(ch, me, target, over)


# ─── The one-on-one ───────────────────────────────────────────────────

ONE_ON_ONE_DAYS = 7
NEXT_SHOWN_1on1 = 5


def _quoted(titles: List[str]) -> str:
    return _join([f"“{t}”" for t in titles])


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def one_on_one(ch: co.Church, target: Dict[str, Any], now: Optional[datetime] = None,
               areas: Optional[List[str]] = None) -> Dict[str, Any]:
    """What a one-on-one with them goes over, read and never recorded: what
    they finished in the last 7 days; what's stuck, how long, and whether it
    was sent up; what's late; the next five due; and (a login) this week's
    jobs, done, not yet or late. Plain lines too, to read out as they are.
    Nothing is written: no check ticks anything off here. `areas` (the
    asker's own view, church_team_week.view_of; None is the whole church):
    only their jobs in those areas, as See as cuts a rhythm (rhythm_within),
    so a job's words never cross a wall the asker doesn't work behind.
    Their assignments are their own, whatever area they're filed under."""
    import church_my_week as mw
    import church_team_week as ctw
    now = now or _now()
    ctx = cw.Ctx(ch.business, now, ch.tz)
    today = ctx.today
    q = f"/tasks?business_id=eq.{_q(ch.b)}&{cs.column(target)}=eq.{_q(target['id'])}"
    open_rows = _need(f"{q}&status=neq.done&select={FIELDS}&order=due_date.asc.nullslast&limit={READ_MAX}")
    done_rows = _need(f"{q}&status=eq.done&completed_at=gte.{_since_day(now, ONE_ON_ONE_DAYS)}&select={FIELDS}"
                      f"&order=completed_at.desc&limit={READ_MAX}")
    theirs_ = lambda r: str(r.get("business_id")) == ch.b and co.same(_target_of(r) or {}, target)  # noqa: E731
    open_rows = [r for r in open_rows if theirs_(r) and r.get("status") != "done"]
    cut = _iso(now - timedelta(days=ONE_ON_ONE_DAYS))
    done_rows = [r for r in done_rows if theirs_(r) and r.get("status") == "done" and str(r.get("completed_at") or "") >= cut]
    logins = _names_by_login(ch, [r.get("raised_to") for r in open_rows])
    people = ch.names([r.get("raised_to_contact_id") for r in open_rows if r.get("raised_to_contact_id")])
    clt = _clt()
    tz = ctx.tz

    def local(v: Any) -> Optional[date]:
        return cw._local_day(v, tz) if v else None

    finished = [{"id": str(r["id"]), "title": _plain(r.get("title")) or "An assignment",
                 "on": f"{local(r.get('completed_at')):%A}" if local(r.get("completed_at")) else "",
                 "checked": bool(r.get("checked_at"))} for r in done_rows]
    stuck, late, nxt = [], [], []
    for r in open_rows:
        title = _plain(r.get("title")) or "An assignment"
        due = str(r.get("due_date") or "")[:10]
        words = clt.due_words(due, today)
        if r.get("stuck_at"):
            since = local(r.get("stuck_at"))
            to = (logins.get(str(r.get("raised_to") or "")) or people.get(str(r.get("raised_to_contact_id") or ""))
                  or "") if r.get("raised_at") else ""
            stuck.append({"id": str(r["id"]), "title": title, "note": _plain(r.get("stuck_note")),
                          "since": r.get("stuck_at"), "days": max(0, (today - since).days) if since else 0,
                          "sent_up": bool(r.get("raised_at")), "sent_up_to": to})
        elif words["state"] == "late":
            late.append({"id": str(r["id"]), "title": title, "due": due, "due_text": words["text"]})
        else:
            nxt.append({"id": str(r["id"]), "title": title, "due": due or None, "due_text": words["text"]})
    stuck.sort(key=lambda s: -s["days"])
    nxt.sort(key=lambda i: i["due"] or "9999-12-31")
    nxt = nxt[:NEXT_SHOWN_1on1]
    jobs: List[Dict[str, Any]] = []
    if target["kind"] == co.LOGIN:
        held = ch.held(target["id"])
        picks = days_for(ch.business, [target["id"]]).get(target["id"], {})
        monday = today - timedelta(days=today.weekday())
        jobs = ctw.due_this_week(held, monday, picks)
        if areas is not None:
            import church_duties as cd
            jobs = [w for w in jobs if cd.CATALOG[w["duty"]]["area"] in set(areas)]
        judged = mw._done_full(ch.business, frozenset(w["duty"] for w in jobs), today, now, tz, picks=picks, ctx=ctx) \
            if co.church_open(ch.b) else {}
        for w in jobs:
            got = judged.get(w["duty"])
            due = mw.due_day(w["duty"], monday, picks.get(w["duty"]), today)
            state = mw.job_state(got["done"], due, today) if got else None
            if state:
                w.update(state=state, state_text=mw.STATE_TEXT[state], detail=got["text"], due=due.isoformat())
    lines = [f"Finished in the last week: {_quoted([f['title'] for f in finished])}." if finished
             else "Nothing finished in the last week."]
    if stuck:
        said = []
        for s in stuck:
            how = f"for {s['days']} day{'s' if s['days'] != 1 else ''}" if s["days"] else "since today"
            said.append(f"“{s['title']}” {how}" + (f", sent up to {s['sent_up_to']}" if s["sent_up_to"] else
                                                   ", sent up" if s["sent_up"] else ""))
        lines.append("Stuck: " + "; ".join(said) + ".")
    else:
        lines.append("Nothing stuck.")
    if late:
        lines.append("Late: " + "; ".join(f"“{i['title']}”, {i['due_text']}" for i in late) + ".")
    lines.append("Next: " + "; ".join(f"“{i['title']}”, {_lower_first(i['due_text'])}" for i in nxt) + "."
                 if nxt else "Nothing else is due.")
    if jobs:
        lines.append("This week's jobs: " + "; ".join(
            f"{w['label']}, {w['state_text'].lower()}" if w.get("state") else f"{w['label']}, {', '.join(w['days'])}"
            for w in jobs) + ".")
    return {"for": co.key(target), "kind": target["kind"], "id": target["id"], "name": _name_of(ch, target),
            "today": today.isoformat(), "finished": finished, "stuck": stuck, "late": late, "next": nxt,
            "jobs": jobs, "lines": lines}


@router.get("/assignments/one-on-one")
def assignments_one_on_one(business_id: str, for_: str = Query(..., alias="for"),
                           session: UserSession = Depends(sb_clients.authed_request),
                           biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """A one-on-one with someone you're over: finished in the last 7 days,
    stuck (how long, and whether sent up), late, the next five due, and this
    week's jobs done or not yet; plain lines too. Nothing is recorded."""
    ch = _church(session, biz)
    me = _me(session)
    target = co.parse_for(for_)
    _allowed(ch, me, target, self_ok=False)
    import church_team_week as ctw
    return one_on_one(ch, target, areas=ctw.view_of(ch.b, me["id"], ch.role(me["id"])))


# ─── Handing one out ──────────────────────────────────────────────────

def _duty_ok(target: Dict[str, Any], ch: co.Church, duty: Any) -> Optional[str]:
    import church_duties as cd
    if duty in (None, ""):
        return None
    duty = str(duty)
    if duty not in cd.CATALOG and duty not in cs.SWITCH_LABEL:
        raise HTTPException(400, "That isn't one of the church's jobs")
    if duty in cd.CATALOG and cd.CATALOG[duty]["money"] and not (
            target["kind"] == co.LOGIN and ch.role(target["id"]) in co.KEEPS_ALL):
        raise HTTPException(400, f"“{cd.CATALOG[duty]['label']}” is a money job: it stays with the owner and the "
                                 "admins.")
    return duty


def _text(v: Any, most: int, what: str, *, need: bool = False) -> Optional[str]:
    s = _plain(v) if what != "notes" else str(v or "").replace("\r\n", "\n").strip()
    if need and not s:
        raise HTTPException(400, f"Say what the {what} is")
    if len(s) > most:
        raise HTTPException(400, f"Keep the {what} to {most} letters")
    return s or None


def give(ch: co.Church, me: Dict[str, Any], target: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    row = {"business_id": ch.b, "title": _text(body.get("title"), TITLE_MAX, "title", need=True),
           "description": _text(body.get("notes"), NOTES_MAX, "notes"), "status": "todo", "priority": "medium",
           "due_date": _day(body.get("due_date")),
           "assigned_to": target["id"] if target["kind"] == co.LOGIN else None,
           "assigned_contact_id": target["id"] if target["kind"] == co.PERSON else None,
           "handed_by": str(me["id"]), "duty": _duty_ok(target, ch, body.get("duty")),
           "done_when": _text(body.get("done_when"), DONE_WHEN_MAX, "done when"), "check_key": None,
           "startup_key": None}
    saved = sb_clients.sb_post_as_service("/tasks", row)
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        raise HTTPException(503, UNSAVED)
    return saved[0]


@router.post("/assignments")
def assignments_give(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Hand one out: {business_id, for, title, due_date?, done_when?, duty?,
    notes?}. To someone you're over, or to yourself. Answers with what it
    saved."""
    body = body or {}
    ch = _church_from_body(session, body)
    me = _me(session)
    target = co.parse_for(body.get("for"))
    _allowed(ch, me, target, self_ok=True)
    _ready(ch)
    saved = give(ch, me, target, body)
    return {"saved": _one(ch, saved)}


# ─── Changing one ─────────────────────────────────────────────────────

SENT_UP = ("It was sent up, so whoever sent it up, whoever it went to, or whoever is over you says when it's no "
           "longer stuck. Marking it done still works.")
JUST_SENT_UP = ("It was just sent up, so whoever sent it up, whoever it went to, or whoever is over you says when "
                "it's no longer stuck. Open it again.")
SENT_UP_STAYS = ("It was sent up, so it stays until whoever sent it up, whoever it went to, or whoever is over "
                 "them takes it back.")


def _now_sent_up(t: Dict[str, Any]) -> bool:
    """Whether this task has been sent up since it was read (a guarded write
    that changed nothing): read again."""
    rows = sb_clients.sb_get_as_service(f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(t['business_id'])}"
                                        "&select=id,raised_at&limit=1")
    return isinstance(rows, list) and bool(rows) and bool(rows[0].get("raised_at"))


def change(ch: co.Church, me: Dict[str, Any], t: Dict[str, Any], body: Dict[str, Any],
           now: Optional[datetime] = None) -> Dict[str, Any]:
    """Who changes what (Claude's rule from the #1801 review, after Kevin's
    wish that the one over them be in control): done, by
    them or anyone over them; stuck, by them too until it's been sent up, and
    from then on only by whoever sent it up, whoever it went to, or anyone
    over them (the assignee can still mark it done, which closes it, and
    whoever it went to sees it resolved); the date, the title and what done
    means, by anyone over them or whoever handed it."""
    now = now or _now()
    target = _target_of(t)
    mine = co.same(me, target)
    over = False if mine else co.is_over(ch, me, target)
    sent = bool(t.get("raised_at"))
    up_side = sent and str(me["id"]) in {str(t.get("raised_by") or ""), str(t.get("raised_to") or "")}
    if not (mine or over or up_side):
        raise HTTPException(403, NOT_OVER)
    patch: Dict[str, Any] = {}
    if any(k in body for k in ("due_date", "title", "done_when")):
        if not (over or str(t.get("handed_by") or "") == str(me["id"])):
            raise HTTPException(403, "Only whoever is over them changes the date, the title or what done means.")
        if "title" in body:
            patch["title"] = _text(body.get("title"), TITLE_MAX, "title", need=True)
        if "due_date" in body:
            patch["due_date"] = _day(body.get("due_date"))
        if "done_when" in body:
            patch["done_when"] = _text(body.get("done_when"), DONE_WHEN_MAX, "done when")
    if "stuck" in body and sent and not (over or up_side):
        raise HTTPException(403, SENT_UP)
    if "done" in body and not (mine or over):
        raise HTTPException(403, "Only they, or whoever is over them, mark it done.")
    if "stuck" in body:
        if body["stuck"] is None:
            patch.update(stuck_note=None, stuck_at=None, raised_at=None, raised_to=None, raised_to_contact_id=None,
                         raised_by=None, raised_told_at=None)
        else:
            if not isinstance(body["stuck"], str):
                raise HTTPException(400, "Say why it's stuck, or null when it isn't")
            patch["stuck_note"] = _text(body["stuck"], STUCK_MAX, "note") or ""
            if not t.get("stuck_at"):
                patch["stuck_at"] = _iso(now)
    if "done" in body:
        if not isinstance(body["done"], bool):
            raise HTTPException(400, "done is true or false")
        if body["done"]:
            if t.get("status") != "done":
                patch.update(status="done", completed_at=_iso(now))
        elif t.get("status") == "done":
            patch.update(status="todo", completed_at=None, checked_at=None)
    if not patch:
        return t
    # The assignee's own say on stuck holds only while it hasn't been sent up:
    # the database holds that too, so a send-up in between wins (409).
    guard = "&raised_at=is.null" if "stuck" in body and not (over or up_side) else ""
    got = sb_clients.sb_patch_as_service(_theirs(t, target) + guard, patch)
    if guard and isinstance(got, list) and not got and _now_sent_up(t):
        raise HTTPException(409, JUST_SENT_UP)
    return _saved(got)


@router.patch("/assignments/{task_id}")
def assignments_change(task_id: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """{business_id, done?, stuck?: note | null, due_date?, title?, done_when?}:
    done by them or anyone over them; stuck by them until it's sent up, then
    by whoever sent it up, whoever it went to, or anyone over them; the date,
    the title and what done means by whoever is over them (or handed it).
    Answers with what it saved."""
    body = body or {}
    ch = _church_from_body(session, body)
    t = _task(ch, task_id)
    _ready(ch)
    saved = change(ch, _me(session), t, body)
    return {"saved": _one(ch, saved)}


@router.delete("/assignments/{task_id}")
def assignments_take_back(task_id: str, business_id: str, session: UserSession = Depends(sb_clients.authed_request),
                          biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Take one back: whoever handed it, or anyone over them. Once it's been
    sent up, only whoever sent it up, whoever it went to, or anyone over them
    (never the assignee, even one who handed it to herself), so it never
    vanishes from the list of whoever it went to. Answers with what was taken
    back."""
    ch = _church(session, biz)
    me = _me(session)
    t = _task(ch, task_id)
    target = _target_of(t)
    guard = ""
    if t.get("raised_at"):
        up_side = str(me["id"]) in {str(t.get("raised_by") or ""), str(t.get("raised_to") or "")}
        if not up_side and (co.same(me, target) or not co.is_over(ch, me, target)):
            raise HTTPException(403, SENT_UP_STAYS)
    elif str(t.get("handed_by") or "") == str(me["id"]):
        guard = "&raised_at=is.null"      # whoever handed it, only while it hasn't been sent up
    else:
        _allowed(ch, me, target, self_ok=False)
    if not sb_clients.sb_delete_as_service(_theirs(t, target) + guard):
        raise HTTPException(503, UNSAVED)
    left = _need(f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(ch.b)}&select=id,raised_at&limit=1")
    if left:
        raise HTTPException(409, SENT_UP_STAYS) if guard and left[0].get("raised_at") else HTTPException(503, UNSAVED)
    print(f"[church_assignments] {ch.b[:8]}: {me['id'][:8]} took back {t['id']} ({_plain(t.get('title'))[:60]!r})",
          flush=True)
    return {"taken_back": {"id": str(t["id"]), "title": _plain(t.get("title")), "for": co.key(target)}}


# ─── Sending one up ───────────────────────────────────────────────────

def raise_up(ch: co.Church, me: Dict[str, Any], t: Dict[str, Any], note: Any,
             now: Optional[datetime] = None) -> Tuple[Dict[str, Any], Dict[str, str]]:
    now = now or _now()
    target = _target_of(t)
    _allowed(ch, me, target, self_ok=False)
    if t.get("status") == "done":
        raise HTTPException(409, "That one is done: there's nothing to send up.")
    up = co.above(ch, me)
    if not up:
        raise HTTPException(409, "Nobody is over you here, so there's no one to send it up to.")
    to = up[0]
    stamp = _iso(now)
    patch = {"raised_at": stamp, "raised_by": str(me["id"]), "raised_told_at": None,
             "raised_to": to["id"] if to["kind"] == co.LOGIN else None,
             "raised_to_contact_id": to["id"] if to["kind"] == co.PERSON else None}
    said = _text(note, STUCK_MAX, "note") if note is not None else None
    if said is not None:
        patch["stuck_note"] = said
    elif not t.get("stuck_at"):
        patch["stuck_note"] = ""
    if not t.get("stuck_at"):
        patch["stuck_at"] = stamp
    return _saved(sb_clients.sb_patch_as_service(f"{_theirs(t, target)}&status=neq.done", patch)), to


@router.post("/assignments/{task_id}/raise")
def assignments_raise(task_id: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """{business_id, note?}: send a stuck one up to whoever is over me (the
    nearest; the owner at the top). Anyone over them. It's marked stuck if it
    wasn't; the hourly sweep tells them once."""
    body = body or {}
    ch = _church_from_body(session, body)
    t = _task(ch, task_id)
    _ready(ch)
    saved, to = raise_up(ch, _me(session), t, body.get("note"))
    return {"saved": _one(ch, saved), "to": to}


# ─── A first assignment ───────────────────────────────────────────────

@router.post("/assignments/start")
def assignments_start(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """{business_id, for}: make their first assignment, from the jobs they
    hold (a login) or the switches they hold (one of the church's people).
    Anyone over them. Made once per item: again makes only what's new, and
    says how many it skipped."""
    body = body or {}
    ch = _church_from_body(session, body)
    me = _me(session)
    target = co.parse_for(body.get("for"))
    _allowed(ch, me, target, self_ok=False)
    _ready(ch)
    ctx = cw.Ctx(ch.business, _now(), ch.tz)
    got = cs.start(ch, str(me["id"]), target, ctx.today)
    logins = _after(lambda: _names_by_login(ch, [me["id"]]), {})
    return {"for": co.key(target), "name": _after(lambda: _name_of(ch, target), ""), "of": got["of"],
            "skipped": got["skipped"],
            "made": [item(r, ctx.today, logins, {}) for r in got["made"]]}


# ─── Days ─────────────────────────────────────────────────────────────

def _login_target(ch: co.Church, me: Dict[str, Any], user_id: Optional[str]) -> Tuple[Dict[str, str], bool]:
    target = co.who(co.LOGIN, _uuid(user_id, "login")) if user_id else me
    if not co.same(me, target):
        _allowed(ch, me, target, self_ok=False)
        return target, True
    return target, False


def _held(ch: co.Church, uid: str) -> List[str]:
    import church_duties as cd
    held = ch.held(uid)
    return [k for k in cd.CATALOG if k in held]


def days_page(ch: co.Church, target: Dict[str, str], over: bool) -> Dict[str, Any]:
    import church_duties as cd
    import church_my_week as mw
    picks = picked_days(ch.b, [target["id"]])
    if picks is None:
        raise HTTPException(503, UNREAD)
    mine = picks.get(target["id"], {})
    out = []
    for k in _held(ch, target["id"]):
        d = cd.CATALOG[k]
        pick = mine.get(k)
        out.append({"duty": k, "label": d["label"], "catalog_day": d["day"], "usual": mw.placed(d["day"])[2],
                    "picked": pick, "when": mw.placed(day_with(d["day"], pick))[2], "movable": movable(k)})
    return {"user_id": target["id"], "name": ch.login_name(target["id"]), "can_change": True,
            "over": over, "duties": out}


@router.get("/duty-days")
def duty_days(business_id: str, user_id: Optional[str] = None, session: UserSession = Depends(sb_clients.authed_request),
              biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Each duty a login holds (yours, or one you're over): its catalog day,
    its picked day, and whether it can move."""
    ch = _church(session, biz)
    target, over = _login_target(ch, _me(session), user_id)
    return days_page(ch, target, over)


def pick_day(ch: co.Church, me: Dict[str, Any], target: Dict[str, str], duty: Any, day: Any) -> Dict[str, Any]:
    import church_duties as cd
    import church_my_week as mw
    duty = str(duty or "")
    if duty not in cd.CATALOG:
        raise HTTPException(400, "That isn't one of the church's jobs")
    if cd.CATALOG[duty]["money"] and ch.role(me["id"]) not in co.KEEPS_ALL:
        # A money job's day is the owner's or an Admin's to pick, whoever else is over the login.
        raise HTTPException(403, f"“{cd.CATALOG[duty]['label']}” is a money job: only the owner or an admin picks "
                                 "its day.")
    if duty not in _held(ch, target["id"]):
        raise HTTPException(400, f"“{cd.CATALOG[duty]['label']}” isn't one of their jobs here.")
    if not movable(duty):
        raise HTTPException(400, f"“{cd.CATALOG[duty]['label']}” stays on its day: {mw.placed(cd.CATALOG[duty]['day'])[2]}.")
    where = (f"/church_duty_days?business_id=eq.{_q(ch.b)}&user_id=eq.{_q(target['id'])}&duty=eq.{_q(duty)}")
    if day is None:
        if not sb_clients.sb_delete_as_service(where):
            raise HTTPException(503, UNSAVED)
        picked = None
    else:
        if day not in WEEKDAYS:
            raise HTTPException(400, "A day is Mon, Tue, Wed, Thu, Fri, Sat or Sun")
        saved = sb_clients.sb_post_as_service(
            "/church_duty_days?on_conflict=business_id,user_id,duty",
            {"business_id": ch.b, "user_id": target["id"], "duty": duty, "day": day, "set_by": str(me["id"]),
             "updated_at": _iso(_now())}, prefer="resolution=merge-duplicates,return=representation")
        if not isinstance(saved, list) or not saved or saved[0].get("day") != day:
            raise HTTPException(503, UNSAVED)
        picked = day
    d = cd.CATALOG[duty]
    return {"saved": {"user_id": target["id"], "duty": duty, "label": d["label"], "catalog_day": d["day"],
                      "picked": picked, "when": mw.placed(day_with(d["day"], picked))[2], "movable": True}}


@router.put("/duty-days")
def duty_days_pick(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """{business_id, user_id?, duty, day | null}: the day a weekly job falls
    on, by the login itself or anyone over it. null puts it back to the
    catalog's. Answers with what it saved."""
    body = body or {}
    ch = _church_from_body(session, body)
    me = _me(session)
    target, _over = _login_target(ch, me, body.get("user_id"))
    if "day" not in body:
        raise HTTPException(400, "Say the day, or null to put it back")
    return pick_day(ch, me, target, body.get("duty"), body["day"])


# ─── Telling people: a first assignment in one email ──────────────────

NUMBER = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def startup_of(business_id: str, ids: Iterable[Any]) -> Dict[str, str]:
    """task id -> its start-up key, for the sweeps' grouped tell. Read only
    where the switch is open; {} when it isn't, or the read fails (the
    columns before their migration): the email then says "tasks"."""
    ids = sorted({str(i) for i in ids if i})
    if not ids or not co.church_open(business_id):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/tasks?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(i) for i in ids)})"
        "&select=id,startup_key&limit=500")
    if not isinstance(rows, list):
        return {}
    return {str(r["id"]): str(r["startup_key"]) for r in rows if r.get("startup_key")}


def grouped_text(name: str, by: List[str], tasks: List[Dict[str, Any]], today: Optional[date],
                 first: bool, where: str) -> Tuple[str, str, str]:
    """(subject end, the email's words, the push's words) for several
    hand-offs at once: "Jessica gave you 7 things for your first four weeks"."""
    clt = _clt()
    who = _join(by) or "The church office"
    n = len(tasks)
    days = [d for d in (clt._day(t.get("due_date")) for t in tasks) if d]
    if first:
        span = max(1, -(-((max(days) - today).days) // 7)) if days and today else 0
        what = (f"{n} things for your first {NUMBER.get(span, str(span))} weeks" if span > 1
                else f"{n} things for your first week" if span == 1 else f"{n} things for your first assignment")
    else:
        what = f"{n} tasks"
    lines = [f"Hi {clt.first_name(name) or 'there'},", f"{who} gave you {what}:"]
    said = []
    for t in sorted(tasks, key=lambda t: (str(t.get("due_date") or "9999"), _plain(t.get("title")))):
        d = clt._day(t.get("due_date"))
        said.append(f"“{_plain(t.get('title')) or 'A task'}”" + (f", due {clt.day_words(d)}" if d else ""))
    lines[-1] += "\n" + "\n".join(said)
    lines.append(where)
    return what, "\n\n".join(lines), f"{who}: {what}"


# ─── The hourly sweep: sent up, and checks that tick ──────────────────

RAISED_FIELDS = ("id,business_id,title,stuck_note,stuck_at,status,assigned_to,assigned_contact_id,raised_at,"
                 "raised_to,raised_to_contact_id,raised_by,raised_told_at")


def _claim_raised(t: Dict[str, Any], stamp: str) -> bool:
    got = sb_clients.sb_patch_as_service(
        f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(t['business_id'])}&raised_at=eq.{_q(t['raised_at'])}"
        "&raised_told_at=is.null&status=neq.done", {"raised_told_at": stamp})
    return isinstance(got, list) and bool(got)


def _release_raised(t: Dict[str, Any], stamp: str) -> None:
    try:
        sb_clients.sb_patch_as_service(
            f"/tasks?id=eq.{_q(t['id'])}&business_id=eq.{_q(t['business_id'])}&raised_told_at=eq.{_q(stamp)}",
            {"raised_told_at": None})
    except Exception:
        logger.warning("assignments: a raised claim wasn't let go (task %s)", str(t["id"])[:8], exc_info=True)


def raised_text(name: str, by: str, whose: str, t: Dict[str, Any], where: str) -> str:
    clt = _clt()
    title = _plain(t.get("title")) or "An assignment"
    lines = [f"Hi {clt.first_name(name) or 'there'},",
             f"{by or 'Someone in the office'} sent up something that's stuck: “{title}”"
             + (f", {whose}’s." if whose else ".")]
    note = _plain(t.get("stuck_note"))
    if note:
        lines.append(f"What’s stuck: {note}")
    lines.append(where)
    return "\n\n".join(lines)


def _login_email(ch: co.Church, uid: str) -> Optional[str]:
    """A login's sign-in email: the owner's from Auth, a seat's from the
    church's seats; '' when it has none (or has left the office), None when
    it couldn't be read."""
    clt = _clt()
    try:
        if uid == ch.owner:
            return clt._email_ok(ch.owner_email)
        seat = ch.seats.get(uid)
    except HTTPException:
        return None
    return clt._email_ok((seat or {}).get("invited_email")) if seat else ""


def tell_raised(biz: Dict[str, Any], rows: List[Dict[str, Any]], now: datetime, stats: Dict[str, int]) -> None:
    """Each item newly sent up: claimed, then one email (and a push to a
    login) to whoever it was sent up to, from the church, with the item, its
    stuck note and who sent it up. No email on file: told anyway (it's on
    their page). An address that couldn't be read is never "no email": that
    item isn't claimed, and the next sweep tries again."""
    import church_office_tasks as cot
    clt = _clt()
    ch = co.Church(biz)
    b = ch.b
    church = _plain(biz.get("name")) or "Your church"
    reply_to = clt._office_email(biz)
    people = clt._contacts(b, [r.get("raised_to_contact_id") for r in rows] +
                           [r.get("assigned_contact_id") for r in rows])
    if people is None:
        stats["raised_unread"] += len(rows)
        print(f"[church_assignments] {b[:8]}: the people for what was sent up weren't read; next sweep", flush=True)
        return

    def login(uid: Any) -> str:
        uid = str(uid or "")
        try:
            return ch.login_name(uid) if uid and (uid == ch.owner or uid in ch.seats) else ""
        except HTTPException:
            return ""

    for t in rows:
        if t.get("status") == "done" or not t.get("stuck_at"):
            continue
        # Everything the email says is read before the claim: a claim taken
        # and never sent would leave them untold for good.
        by = login(t.get("raised_by"))
        whose = (login(t["assigned_to"]) if t.get("assigned_to")
                 else (people.get(str(t.get("assigned_contact_id") or "")) or {}).get("name", ""))
        subject = f"{church}: something stuck was sent up to you"
        if t.get("raised_to"):
            uid = str(t["raised_to"])
            email = _login_email(ch, uid)
            if email is None:
                stats["raised_unread"] += 1        # not claimed: the next sweep tries again
                continue
            name = login(uid)
            where = "It’s on your My week until it’s done or no longer stuck."
            link, label = cot._link(b), "Open My week"
            render = cot.render
        else:
            p = people.get(str(t.get("raised_to_contact_id") or "")) or {}
            uid, email, name = "", p.get("email", ""), p.get("name", "")
            where = f"It’s on your {clt._tab_word()} tab in the church’s app until it’s done or no longer stuck."
            link, label = clt._tasks_link(b), "Open your tasks"
            render = clt.render_email
        stamp = _iso(now)
        if not _claim_raised(t, stamp):
            continue
        if not email:
            stats["raised_no_email"] += 1
            continue
        try:
            html = render(biz, raised_text(name, by, whose, t, where), _plain(t.get("title"))[:80], link, label)
            clt.deliver(biz, email, name, subject, html, f"assignment-raised-{t['id']}-{t['raised_at']}",
                        reply_to=reply_to)
        except Exception:
            logger.warning("assignments: a raised email failed (task %s)", str(t["id"])[:8], exc_info=True)
            _release_raised(t, stamp)
            stats["raised_unsent"] += 1
            continue
        if uid:
            try:
                import push_notifications
                push_notifications.send_to_user(uid, title="Sent up to you"[:80],
                                                body=f"{by + ': ' if by else ''}{_plain(t.get('title'))}"[:160],
                                                nav=NAV, tag=f"raised-{t['id']}"[:60], business_id=b)
            except Exception:
                logger.info("assignments: a push didn't go (business %s)", b[:8], exc_info=True)
        stats["raised_told"] += 1


BIZ_FIELDS = "id,name,type,settings,owner_id"


def _platform_owner_id() -> str:
    """The platform owner's user id (chief_of_staff.PLATFORM_OWNER_ID, as
    church_keys.platform_church reads it)."""
    from chief_of_staff import PLATFORM_OWNER_ID
    return str(PLATFORM_OWNER_ID)


def _open_churches() -> Optional[List[Dict[str, Any]]]:
    """The churches the sweep works for: None for every one (on); with
    `owner`, the platform owner's own churches, each one church_open also
    says yes to; [] when they can't be read (the next hour tries again)."""
    import church_follow_up as cfu
    if co.mode() == "on":
        return None
    rows = sb_clients.sb_get_as_service(f"/businesses?owner_id=eq.{_q(_platform_owner_id())}"
                                        f"&select={BIZ_FIELDS}&limit=50")
    if not isinstance(rows, list):
        print("[church_assignments] the platform's churches weren't read; next sweep", flush=True)
        return []
    return [b for b in rows if cfu.is_church(b) and co.church_open(b["id"])]


def _all(path: str, what: str) -> Optional[List[Dict[str, Any]]]:
    """Every row, page by page in id order (sb_get_all_as_service), so rows a
    sweep can't use never crowd out the ones it can. None when it can't be
    read whole (the migration not applied, a page that failed): nothing of it
    is acted on, and the next hour tries again."""
    try:
        return sb_clients.sb_get_all_as_service(path, key="id")
    except sb_clients.PartialRead:
        print(f"[church_assignments] {what} was read in part; next sweep", flush=True)
        return None


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, on the worker (kmj_intake_automation): what was sent up is told
    once; open items whose check can pass, and now does, are ticked off.
    Only the churches the switch is open for (with `owner`, the platform
    owner's own), every row of theirs page by page, so nothing waits behind
    rows it can't use (an evidence-only check is never read: it never
    ticks). A church that fails never stops the others. Quiet with the switch
    off, and before the migration (its reads fail and nothing happens)."""
    stats = {"churches": 0, "raised_told": 0, "raised_no_email": 0, "raised_unsent": 0, "raised_unread": 0,
             "ticked": 0}
    if co.mode() == "off":
        return stats
    now = now or _now()
    churches = _open_churches()
    if churches == []:
        return stats
    scope = "" if churches is None else f"&business_id=in.({','.join(_q(b['id']) for b in churches)})"
    raised = _all(f"/tasks?raised_at=not.is.null&raised_told_at=is.null&status=neq.done&stuck_at=not.is.null"
                  f"{scope}&select={RAISED_FIELDS}", "what was sent up")
    if raised is None:
        return stats            # the migration isn't applied (or the read failed): next hour
    checked = _all(f"/tasks?check_key=in.({','.join(sorted(cw.PASSABLE))})&status=neq.done{scope}"
                   "&select=id,business_id,check_key,status", "the items a check can tick") or []
    work: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for kind, rows in (("raised", raised), ("checked", checked)):
        for r in rows:
            work.setdefault(str(r.get("business_id")), {"raised": [], "checked": []})[kind].append(r)
    if not work:
        return stats
    clt = _clt()
    bizs: Dict[str, Dict[str, Any]] = {str(b["id"]): b for b in churches or []}
    for chunk in clt._chunks(b for b in work if b not in bizs):
        for x in sb_clients.sb_get_as_service(f"/businesses?id=in.({','.join(_q(i) for i in chunk)})"
                                              f"&select={BIZ_FIELDS}&limit=100") or []:
            bizs[str(x["id"])] = x
    import church_follow_up as cfu
    for b, todo in work.items():
        biz = bizs.get(b)
        if not biz or not cfu.is_church(biz) or not co.church_open(b):
            continue
        stats["churches"] += 1
        try:
            if todo["raised"]:
                tell_raised(biz, todo["raised"], now, stats)
            if todo["checked"]:
                stats["ticked"] += len(cw.tick(cw.Ctx(biz, now), todo["checked"]))
        except Exception:
            logger.warning("assignments sweep failed for business %s", b[:8], exc_info=True)
    return stats


def digest(ids: Iterable[Any]) -> str:
    return hashlib.sha1(",".join(sorted(str(i) for i in ids)).encode()).hexdigest()[:16]
