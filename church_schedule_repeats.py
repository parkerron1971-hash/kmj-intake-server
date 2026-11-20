"""church_schedule_repeats.py — the leaders schedule: things that repeat
(docs/CHURCH_SCHEDULE.md, PR S1-7; church_schedule.py is the engine).

Kevin, 2026-11-18: "this is for when leaders are planning time off and have
certain obiligations so that we as a church can plan around meeting". A
leader says once "I work every second Saturday", and the schedule remembers
it: it is on the calendar, and Who serves when doesn't ask them to serve on
those days.

    GET    /church/schedule/commitments?business_id=&box=mine|all
                                                  my own (mine), or every one
                                                  (all: the owner and whoever
                                                  oversees the office)
    POST   /church/schedule/commitments           add one (for yourself; the
                                                  owner and the office
                                                  overseer for anyone on the
                                                  schedule, by `for`)
    DELETE /church/schedule/commitments/{id}?business_id=
                                                  take one off (your own; the
                                                  owner and the office
                                                  overseer anyone's)

One row of church_away_commitments (supabase/APPLY-2026-11-19-church-
schedule.sql; applied 2026-11-18): a label, a weekday (1 Monday to 7
Sunday), how often (`weekly`, `every_other` counted from starts_on, or
`month_nth` with nth 1 to 5, 5 being the last such day of the month), from
when and, if it ends, until when.

The rules (docs/CHURCH_SCHEDULE.md section 5, "Standing commitments"; 7.1
item 11; 7.12 for what the build decided):

  no yes ............ nobody answers it: it is on the calendar once saved
  never blocked ..... never counted toward a limit or a pair
                      (church_schedule_limits reads the facts in serve_away,
                      which a commitment never writes), never refused for a
                      full day
  ten a person ...... ten in force at once; past that, plain words
  who adds .......... someone on the leaders schedule, for their own person;
                      the owner and whoever oversees the office for anyone
                      on it (`for`, as an ask's), an office login only
  who takes off ..... their own person; the owner and whoever oversees the
                      office anyone's
  who is told ....... the one an ask of theirs would go to (church_schedule.
                      goes_to), once (told_at), outside quiet hours, never
                      the label (church_schedule_tell.tell_repeat)
  the scheduler ..... church_schedule.holds adds one row a day it falls on
                      (held_days): who and which days, never the label

THE LABEL IS AS PRIVATE AS AN ASK'S REASON. It is read by the person, the
one an ask of theirs would go to, the owner and whoever oversees the office
(sees_label: church_schedule.sees_reason's own rule, on the row an ask of
theirs would be), and by nobody else. Everyone else on the calendar reads a
name and a day, and the key isn't there. held_days, the sweep and every
notice never select it.

Every read is by business_id, bounded and paged; a failed read is a 503 (a
list that couldn't be read is never empty), except the scheduler's, which
fails open. A failed write is a 503 with nothing saved.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import business_access
import church_over as co
import church_schedule as cs
import sb_clients
from auth_supabase import UserSession

router = APIRouter(prefix="/church", tags=["church"])

PATTERNS = ("weekly", "every_other", "month_nth")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")   # 1 … 7
NTH = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "last"}
LAST = 5                    # nth 5 is the last such day of the month, whether it has four or five
MAX_EACH = 10               # in force at once, a person
LABEL_MAX = 80              # the table's own check
SPAN_DAYS = 366             # commitment_days works out this many days at most
START_BACK = cs.MAX_DAYS    # a first day may be up to a year back (every other week counts from it) or ahead
TELL_DAYS = 7               # one nobody could be told of in a week is left untold (church_schedule_tell.ANSWER_DAYS)
# What a reader of the label selects, and what everything else selects: never the label.
FIELDS = "id,business_id,contact_id,label,weekday,pattern,nth,starts_on,until_on,told_at,created_at"
DAYS_FIELDS = "id,business_id,contact_id,weekday,pattern,nth,starts_on,until_on"

LABEL = f"Say what it is, in {LABEL_MAX} letters or fewer."
BAD_WEEKDAY = "Pick the day it falls on."
BAD_PATTERN = "Say how often: every week, every other week, or once a month."
BAD_NTH = "Say which one of the month: the first to the fourth, or the last."
BAD_START = "Pick when it starts: within a year of today."
BAD_UNTIL = "Pick when it ends: today or later, and after it starts."
NONE_BETWEEN = "It doesn't fall on that day between the start and the end you picked."
TOO_MANY = f"That's {MAX_EACH} things that repeat already. Take one off first."
NOT_YOURS = "That isn't one of yours to take off."
GONE = "That one isn't there anymore."
# The member app's codes for the engine's refusals (member_portal_dates._code).
CODES = {LABEL: "dt_repeat_label", BAD_WEEKDAY: "dt_said", BAD_PATTERN: "dt_said", BAD_NTH: "dt_said",
         BAD_START: "dt_repeat_days", BAD_UNTIL: "dt_repeat_days", NONE_BETWEEN: "dt_repeat_none",
         TOO_MANY: "dt_repeat_many", NOT_YOURS: "dt_gone", GONE: "dt_gone"}


# ─── The days it falls on (pure) ──────────────────────────────────────

def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    s = str(v if v is not None else "").strip()
    return int(s) if s.isdigit() else None


def _nth_day(year: int, month: int, weekday: int, nth: int) -> date:
    """The nth such weekday of the month; nth 5 (LAST) is the last one,
    the fourth in a month that has only four."""
    if nth >= LAST:
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        d = nxt - timedelta(days=1)
        return d - timedelta(days=(d.isoweekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.isoweekday()) % 7 + 7 * (nth - 1))


def _months(a: date, z: date) -> Iterable[tuple]:
    y, m = a.year, a.month
    while (y, m) <= (z.year, z.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def days_of(row: Dict[str, Any], lo: date, hi: date) -> List[date]:
    """The days one commitment falls on inside lo..hi, soonest first. A row
    that can't be read falls on no day (never an error)."""
    wd, pattern, nth = _int(row.get("weekday")), row.get("pattern"), _int(row.get("nth"))
    start, until = cs._day(row.get("starts_on")), cs._day(row.get("until_on")) if row.get("until_on") else None
    if not wd or not 1 <= wd <= 7 or pattern not in PATTERNS or not start or (row.get("until_on") and not until):
        return []
    a, z = max(lo, start), min(hi, until) if until else hi
    if z < a:
        return []
    if pattern == "month_nth":
        if not nth or not 1 <= nth <= LAST:
            return []
        return [d for d in (_nth_day(y, m, wd, nth) for y, m in _months(a, z)) if a <= d <= z]
    d = a + timedelta(days=(wd - a.isoweekday()) % 7)
    step = 7
    if pattern == "every_other":
        # Counted from starts_on, which the table keeps on that weekday; a row
        # that somehow isn't counts from the first such day after it.
        anchor = start + timedelta(days=(wd - start.isoweekday()) % 7)
        if (d - anchor).days % 14:
            d += timedelta(days=7)
        step = 14
    out = []
    while d <= z:
        out.append(d)
        if (date.max - d).days < step:
            break                                   # the very end of the calendar: nothing after it
        d += timedelta(days=step)
    return out


def commitment_days(rows: Iterable[Dict[str, Any]], lo: Any, hi: Any) -> Dict[str, List[date]]:
    """{commitment id: [the days it falls on]} inside lo..hi, PURE. SPAN_DAYS
    (366) days at most are worked out: a wider window counts from lo for a
    year and no further. Days that aren't days fall on nothing."""
    a = lo if isinstance(lo, date) else cs._day(lo)
    z = hi if isinstance(hi, date) else cs._day(hi)
    if not a or not z or z < a:
        return {}
    if (z - a).days >= SPAN_DAYS:
        z = a + timedelta(days=SPAN_DAYS - 1)
    out: Dict[str, List[date]] = {}
    for r in rows or []:
        try:
            got = days_of(r, a, z)
        except (OverflowError, ValueError):     # the very end of the calendar: no day there to fall on
            got = []
        if got:
            out.setdefault(str(r.get("id") or ""), []).extend(got)
    return out


def first_day(weekday: int, pattern: str, nth: Optional[int], start: date) -> date:
    """The first day it falls on, on or after `start`: what is saved as
    starts_on, so every other week counts from a day it falls on and the
    page's "from" is a day it happens."""
    if pattern == "month_nth":
        d = _nth_day(start.year, start.month, weekday, nth or 1)
        if d < start:
            y, m = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
            d = _nth_day(y, m, weekday, nth or 1)
        return d
    return start + timedelta(days=(weekday - start.isoweekday()) % 7)


# ─── In plain words ───────────────────────────────────────────────────

def how(row: Dict[str, Any]) -> str:
    """'Every Saturday', 'Every other Saturday', 'The last Sunday of each
    month'. Never the label."""
    wd = _int(row.get("weekday"))
    name = WEEKDAYS[wd - 1] if wd and 1 <= wd <= 7 else "day"
    if row.get("pattern") == "every_other":
        return f"Every other {name}"
    if row.get("pattern") == "month_nth":
        return f"The {NTH.get(_int(row.get('nth')) or 0, 'same')} {name} of each month"
    return f"Every {name}"


def _when(d: date, today: date, long: bool) -> str:
    said = f"{d:%A}, {d:%B} {d.day}" if long else f"{d:%b} {d.day}"
    return said if d.year == today.year else f"{said}, {d.year}"


def said(row: Dict[str, Any], today: date, *, long: bool = False) -> str:
    """How often, then from when (only while it hasn't started) and until
    when (only when it ends): 'Every other Saturday, from Dec 5', 'The last
    Sunday of each month', 'Every Wednesday until Mar 31'. Never the label."""
    out = how(row)
    first, until = cs._day(row.get("starts_on")), cs._day(row.get("until_on")) if row.get("until_on") else None
    if first and first > today:
        out += f", from {_when(first, today, long)}"
    if until:
        out += f" until {_when(until, today, long)}"
    return out


# ─── Who reads the label ──────────────────────────────────────────────

def _to_row(ch: co.Church, cid: str) -> Dict[str, Any]:
    """The row an ask of theirs would be, for the rules that read one: who
    they are, and who it would go to (church_schedule.goes_to)."""
    to = cs.goes_to(ch, cid)
    return {"contact_id": cid, "to_user_id": to["id"] if to and to["kind"] == co.LOGIN else None,
            "to_contact_id": to["id"] if to and to["kind"] == co.PERSON else None}


def sees_label(ch: co.Church, me: Dict[str, Any], cid: Any) -> bool:
    """Who reads what a commitment is: exactly who reads an ask's reason
    (church_schedule.sees_reason), on the row an ask of theirs would be. The
    person, the one it would go to, and (an office login) the owner and
    whoever oversees the office. Nobody else: not another leader, not an
    Admin, not the one who keeps Who serves when."""
    cid = str(cid or "")
    if cs._is_asker(ch, me, {"contact_id": cid}) or cs.over_all(ch, me):
        return True                                 # never worth working out who it would go to
    memo = ch._memo.setdefault("repeat_to", {})
    if cid not in memo:
        memo[cid] = _to_row(ch, cid)
    return cs.sees_reason(ch, me, memo[cid])


def shape(ch: co.Church, me: Dict[str, Any], row: Dict[str, Any], names: Dict[str, str],
          today: date) -> Dict[str, Any]:
    """One commitment as `me` may see it. THE ONE PLACE A LABEL LEAVES THE
    SERVER on a list: `label` is there only for those sees_label lets read
    it, and absent (not empty) for anyone else."""
    cid = str(row.get("contact_id") or "")
    mine = cs._is_asker(ch, me, {"contact_id": cid})
    out = {"id": str(row.get("id")), "contact_id": cid, "name": names.get(cid, "Someone"),
           "weekday": _int(row.get("weekday")), "pattern": row.get("pattern"), "nth": _int(row.get("nth")),
           "starts_on": str(row.get("starts_on") or "")[:10],
           "until_on": str(row.get("until_on"))[:10] if row.get("until_on") else None,
           "said": said(row, today), "mine": mine, "can_remove": mine or cs.over_all(ch, me),
           "created_at": row.get("created_at")}
    if sees_label(ch, me, cid):
        out["label"] = cs._plain(row.get("label"))
    return out


def standing(ch: co.Church, me: Dict[str, Any], rows: List[Dict[str, Any]], names: Dict[str, str], lo: date,
             hi: date) -> List[Dict[str, Any]]:
    """The calendar's `standing` for these commitments: one entry a day each
    falls on inside lo..hi, {contact_id, name, day}, and `label` only for
    those sees_label lets read it (absent for anyone else). Soonest first."""
    by_id = {str(r.get("id")): r for r in rows}
    out = []
    for rid, got in commitment_days(rows, lo, hi).items():
        r = by_id[rid]
        cid = str(r.get("contact_id") or "")
        sees = sees_label(ch, me, cid)
        for d in got:
            one = {"contact_id": cid, "name": names.get(cid, "Someone"), "day": d.isoformat()}
            if sees:
                one["label"] = cs._plain(r.get("label"))
            out.append(one)
    return sorted(out, key=lambda x: (x["day"], x["name"].casefold(), x["contact_id"], x.get("label") or ""))


# ─── Reads ────────────────────────────────────────────────────────────

def _in_force(today: date) -> str:
    """Only one still in force: no end, or an end today or later."""
    return f"or=(until_on.is.null,until_on.gte.{today.isoformat()})"


def of_people(ch: co.Church, people: Iterable[Any], lo: date, hi: date) -> List[Dict[str, Any]]:
    """These people's commitments that can fall inside lo..hi, label and all
    (for the calendar, which shapes them), a hundred people a read, each read
    paged. A failed read is a 503."""
    out: List[Dict[str, Any]] = []
    for part in co._chunks(people, co.IDS_PER_READ):
        out += cs._every(f"/church_away_commitments?business_id=eq.{cs._q(ch.b)}&contact_id=in.({cs._in(part)})"
                         f"&starts_on=lte.{hi.isoformat()}&{_in_force(lo)}&select={FIELDS}")
    keep = {str(p) for p in people}
    return [r for r in out if str(r.get("business_id")) == ch.b and str(r.get("contact_id")) in keep]


def held_days(biz_id: Any, lo: date, hi: date) -> List[Dict[str, str]]:
    """The scheduler's part (church_schedule.holds): one row a day a
    commitment falls on inside lo..hi, [{contact_id, starts_on, ends_on}]
    with both days the same. Selects who and which days only: NEVER THE
    LABEL. One read, a page at a time (church_schedule.HOLD_PAGE rows,
    HOLD_PAGES pages at most). A page that fails holds nobody here (and
    nothing is half read): [] and one logged line. NEVER RAISES. holds()
    has already asked the cheap checks (the switch, the tables, the church)."""
    try:
        b = str(biz_id.get("id") if isinstance(biz_id, dict) else biz_id)
        path = (f"/church_away_commitments?business_id=eq.{cs._q(b)}&starts_on=lte.{hi.isoformat()}"
                f"&{_in_force(lo)}&select={DAYS_FIELDS}&order=id.asc&limit={cs.HOLD_PAGE}")
        rows: List[Dict[str, Any]] = []
        after: Optional[str] = None
        for _page in range(cs.HOLD_PAGES):
            page = sb_clients.sb_get_as_service(path + (f"&id=gt.{cs._q(after)}" if after else ""))
            if not isinstance(page, list):
                print("[church_schedule] the things that repeat couldn't be read for the scheduler; only asks are "
                      "held", flush=True)
                return []
            rows += page
            if len(page) < cs.HOLD_PAGE:
                break
            after = str(page[-1].get("id") or "")
            if not after:
                break
        rows = [r for r in rows if str(r.get("business_id")) == b and r.get("contact_id")]
        who = {str(r.get("id")): str(r["contact_id"]) for r in rows}
        out = []
        for rid, got in commitment_days(rows, lo, hi).items():
            out += [{"contact_id": who[rid], "starts_on": d.isoformat(), "ends_on": d.isoformat()} for d in got]
        return out
    except Exception as e:  # noqa: BLE001 — the volunteer schedule is never worth failing for this
        print(f"[church_schedule] the things that repeat couldn't be held ({type(e).__name__}); only asks are held",
              flush=True)
        return []


def _theirs(ch: co.Church, cid: str, today: date) -> List[Dict[str, Any]]:
    """Their commitments still in force, label and all. A failed read is a
    503."""
    rows = cs._need(f"/church_away_commitments?business_id=eq.{cs._q(ch.b)}&contact_id=eq.{cs._q(cid)}"
                    f"&{_in_force(today)}&select={FIELDS}&order=created_at.asc&limit={MAX_EACH + 40}")
    return [r for r in rows if str(r.get("business_id")) == ch.b and str(r.get("contact_id")) == cid]


def _order(rows: List[Dict[str, Any]], names: Dict[str, str]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: (names.get(str(r.get("contact_id")), "").casefold(),
                                       _int(r.get("weekday")) or 0, str(r.get("starts_on") or ""), str(r.get("id"))))


def commitments(ch: co.Church, me: Dict[str, Any], box: str = "mine", *,
                now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """`mine`: my own still in force (a login matched to no person has none).
    `all`: every one still in force at this church, the owner and whoever
    oversees the office only (403), as an ask's `all` box. Each through
    shape()."""
    today = cs._today(ch, now)
    import church_map
    with church_map.once():
        if box == "all":
            if not cs.over_all(ch, me):
                raise HTTPException(403, cs.NOT_ALL)
            rows = cs._every(f"/church_away_commitments?business_id=eq.{cs._q(ch.b)}&{_in_force(today)}"
                             f"&select={FIELDS}")
            rows = [r for r in rows if str(r.get("business_id")) == ch.b]
        else:
            cid = cs.person_of(ch, me)
            rows = _theirs(ch, cid, today) if cid else []
        names = ch.names([r.get("contact_id") for r in rows])
        return [shape(ch, me, r, names, today) for r in _order(rows, names)]


# ─── Adding one, taking one off ───────────────────────────────────────

def _read_body(body: Dict[str, Any], today: date) -> Dict[str, Any]:
    """What a commitment is, from a body, checked before anything is read:
    the row's own fields, its first day worked out (first_day)."""
    label = cs._plain(body.get("label"))
    if not label or len(label) > LABEL_MAX:
        raise HTTPException(400, LABEL)
    wd = _int(body.get("weekday"))
    if not wd or not 1 <= wd <= 7:
        raise HTTPException(400, BAD_WEEKDAY)
    pattern = str(body.get("pattern") or "")
    if pattern not in PATTERNS:
        raise HTTPException(400, BAD_PATTERN)
    nth = _int(body.get("nth")) if pattern == "month_nth" else None
    if pattern == "month_nth" and (not nth or not 1 <= nth <= LAST):
        raise HTTPException(400, BAD_NTH)
    start = cs._day(body.get("starts_on")) if body.get("starts_on") else today
    if not start or abs((start - today).days) > START_BACK:
        raise HTTPException(400, BAD_START)
    until = None
    if body.get("until_on"):
        until = cs._day(body.get("until_on"))
        if not until or until < today or until < start:
            raise HTTPException(400, BAD_UNTIL)
    first = first_day(wd, pattern, nth, start)
    if until and first > until:
        raise HTTPException(400, NONE_BETWEEN)
    return {"label": label, "weekday": wd, "pattern": pattern, "nth": nth, "starts_on": first.isoformat(),
            "until_on": until.isoformat() if until else None}


def _same(r: Dict[str, Any], want: Dict[str, Any]) -> bool:
    """The same one again (a second press): what it is, the day, how often,
    from and until."""
    return (cs._plain(r.get("label")).casefold() == want["label"].casefold()
            and _int(r.get("weekday")) == want["weekday"] and r.get("pattern") == want["pattern"]
            and _int(r.get("nth")) == want["nth"] and str(r.get("starts_on") or "")[:10] == want["starts_on"]
            and (str(r.get("until_on"))[:10] if r.get("until_on") else None) == want["until_on"])


def add_commitment(ch: co.Church, me: Dict[str, Any], body: Dict[str, Any], *,
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    """Add one. Everything is read before the write: who it is for and that
    they are on the schedule, how many they have in force, who it would go
    to, every name the answer says; a read that fails is a 503 with nothing
    saved.

    For yourself (a person, or a login's own person: 409 for a login matched
    to no one, 403 for someone not on the schedule); `for` (person:<id>) only
    by the owner or whoever oversees the office (403), and only for someone
    on the schedule (400), as an ask's. No yes is needed and nothing blocks
    it: never a full day, never a pair. Ten in force at most (400). The same
    one again answers with the one already there, never a second.

    The one an ask of theirs would go to is told once, after the write
    (church_schedule_tell.tell_repeat, through member_push._later), never the
    label. When there is nobody to tell (the one person the owner is), or it
    would go to the very login that added it, it is saved as told."""
    body = body or {}
    now = now or cs._now()
    today = cs._today(ch, now)
    want = _read_body(body, today)
    import church_map
    with church_map.once():
        if body.get("for") not in (None, ""):
            if not cs.over_all(ch, me):
                raise HTTPException(403, cs.NOT_FOR)
            target = co.parse_for(body["for"])
            if target["kind"] != co.PERSON:
                raise HTTPException(400, "Say who it's for by their name on the church's list")
            cid = target["id"]
            cs._person(ch, cid)
            not_on = HTTPException(400, cs.THEY_NOT_ON)
        else:
            cid = cs.person_of(ch, me) or ""
            if not cid:
                raise HTTPException(409, cs.NO_PERSON)
            not_on = HTTPException(403, cs.NOT_ON)
        if not cs.roster(ch).group_of(cid):
            raise not_on
        have = _theirs(ch, cid, today)
        same = next((r for r in have if _same(r, want)), None)
        if not same and len(have) >= MAX_EACH:
            raise HTTPException(400, TOO_MANY)
        to = cs.goes_to(ch, cid)
        names = ch.names([cid])
        _ = (cs.over_all(ch, me), ch.persons_of(me))        # what shape() asks, read before the write
        if same:
            return shape(ch, me, same, names, today)
    nobody = to is None or (me["kind"] == co.LOGIN and to["kind"] == co.LOGIN and str(to["id"]) == str(me["id"]))
    row = {"business_id": ch.b, "contact_id": cid, **want, "told_at": cs._iso(now) if nobody else None}
    # redact: a refusal's body ("Failing row contains ...") would put the label in the log.
    saved = sb_clients.sb_post_as_service("/church_away_commitments", row, redact=True)
    if not isinstance(saved, list) or not saved or not saved[0].get("id"):
        raise HTTPException(503, cs.UNSAVED)
    if not nobody:
        _after(ch, saved[0])
    return shape(ch, me, saved[0], names, today)


def drop_commitment(ch: co.Church, me: Dict[str, Any], commitment_id: Any, *,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """Take one off: their own person's, or (an office login) the owner's
    and the office overseer's anyone's (403 for anyone else). Read first, so
    one that isn't this church's is a 404 and the answer says what was taken
    off. Nobody is told."""
    rid = cs._uuid(commitment_id, "one")
    today = cs._today(ch, now)
    import church_map
    with church_map.once():
        rows = cs._need(f"/church_away_commitments?id=eq.{cs._q(rid)}&business_id=eq.{cs._q(ch.b)}"
                        f"&select={FIELDS}&limit=1")
        if not rows or str(rows[0].get("business_id")) != ch.b:
            raise HTTPException(404, GONE)
        r = rows[0]
        if not (cs._is_asker(ch, me, r) or cs.over_all(ch, me)):
            raise HTTPException(403, NOT_YOURS)
        names = ch.names([r.get("contact_id")])
        out = shape(ch, me, r, names, today)
    if not sb_clients.sb_delete_as_service(
            f"/church_away_commitments?id=eq.{cs._q(rid)}&business_id=eq.{cs._q(ch.b)}"):
        raise HTTPException(503, cs.UNSAVED)
    return dict(out, can_remove=False)


def _after(ch: co.Church, row: Dict[str, Any]) -> None:
    """Hand the notice to church_schedule_tell once the write is back: off
    this request (member_push._later), on a Church of its own, never able
    to fail the write (the hourly sweep tells one that was missed). The row
    goes whole; tell_repeat keeps only what a notice may say (never the
    label)."""
    try:
        import member_push
        biz, row = dict(ch.business), dict(row)

        def run() -> None:
            import church_schedule_tell as tell
            tell.tell_repeat(co.Church(biz), row)

        member_push._later(run)
    except Exception:  # noqa: BLE001 — a notice is never worth failing the write it is about
        print(f"[church_schedule] {ch.b[:8]}: a notice wasn't handed on (tell_repeat)", flush=True)


# ─── The routes ───────────────────────────────────────────────────────

@router.get("/schedule/commitments")
def schedule_commitments(business_id: str, box: str = "mine", session: UserSession = Depends(sb_clients.authed_request),
                         biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """`mine`: my own things that repeat. `all`: everyone's, for the owner
    and whoever oversees the office."""
    ch = cs._church(session, biz)
    if box not in ("mine", "all"):
        raise HTTPException(400, "Pick mine or all")
    return {"commitments": commitments(ch, cs._me(session), box)}


@router.post("/schedule/commitments")
def schedule_commitment_add(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Something that repeats. Answers with what it saved."""
    ch = cs._church_from_body(session, body or {})
    return {"saved": add_commitment(ch, cs._me(session), body or {})}


@router.delete("/schedule/commitments/{commitment_id}")
def schedule_commitment_drop(commitment_id: str, business_id: str,
                             session: UserSession = Depends(sb_clients.authed_request),
                             biz: Dict[str, Any] = Depends(business_access.business_access("member"))):
    """Take one off."""
    ch = cs._church(session, biz)
    return {"removed": drop_commitment(ch, cs._me(session), commitment_id)}
