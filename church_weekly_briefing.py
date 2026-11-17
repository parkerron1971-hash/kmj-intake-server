"""church_weekly_briefing.py — a church's weekly briefing, about a church's week.

The weekly briefing (growth_engine.run_growth_briefing) was written for a
business: new contacts, sessions, payments, at-risk clients by health
score. A church got the same letter, in the same words, over numbers that
mostly sat at zero (Kevin, 2026-11-17, the first church loaded: the pages
on a church's menu that still speak in business words).

For a church the letter is about the church's week, from the church's own
records, read here before the model writes a word:

    SUNDAY ......... each service in the last days that has a count (the
                     same count Reports shows: people checked in by name,
                     or the headcount, whichever is larger), and the
                     counted service before it
    FIRST TIME ..... people marked first time at check-in or on a New
                     here card in those days: a count, never a name
    NEW PEOPLE ..... people added to the church's records this week and
                     the week before
    FOLLOW-UP ...... how many people are in follow-up, how many have no
                     one yet, how many are late, how many were finished
                     this week: counts, never a name
    PLACES OPEN .... the places still open on the Sunday teams and the
                     roles an event still needs, for the next seven days
                     (the leaders note's own reads)
    COMING ......... the next seven days on the church calendar (the
                     leaders note's own reads; a rental is said without
                     its renter, an invite-only occasion stays out)

WHAT IS LEFT OUT, ON PURPOSE
  * Giving. The briefing page opens to office logins that never see
    giving (church_money_gate, church_areas), and one letter is kept for
    the whole church. So no gift, total or payment is read or said here,
    and the business letter's payment line is not passed on for a church.
  * Names. The office does not see the roll or prayer and care. Every
    line about people is a count. (The drafts the briefing queues do name
    who they are for: those sit in Approvals, which the same logins open.)
  * Health scores. A grade nobody at a church asked for.

EVERY NUMBER IS A QUERY RESULT
  `week` returns precomputed parts; `facts` says them to the model as
  lines it may repeat and never derive from; `numbers_markdown` prints
  them under the letter, so a count can't be paraphrased into another
  count. A part that couldn't be read is None, is named under "not read
  this time", and is never said as zero.

No model call here and no write: service-role reads only, on the path
the endpoint already guards (growth_engine: require_user and
require_business_access). The one model call is the letter's, the one a
business's briefing makes, on the same model.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("church_weekly_briefing")

BACK_DAYS = 7          # the week behind: today and the seven days before it
AHEAD_DAYS = 7         # the week ahead: today and the six days after
MAX_COMING = 14        # gatherings said under "Coming this week"
MAX_NEEDED = 8         # lines said under "Places still open"
LOOK_BACK = 8          # services looked through for "the counted service before"
PAGE = 1000

HEADLINE = "The headline"
WENT_WELL = "What went well"
ATTENTION = "Needs attention"
FOCUS = "This week's focus"
NUMBERS = "The week in numbers"
OPEN_PLACES = "Places still open"
COMING = "Coming this week"
DRAFTS = "Drafts waiting for you"

# Every table a church's week is read from: Sunday (the occasions and
# their counts), people (counts), follow-up (counts) and the week ahead
# (the leaders note's reads). A table that holds giving, a gift or a
# payment is never one of them; the test records every read and holds
# this list to it, so adding a read is a reviewed change to this line.
TABLES_READ = frozenset({
    "custom_modules", "module_entries", "attendance", "attendance_headcounts",
    "contacts", "church_follow_ups",
    "worship_services", "church_space_bookings", "church_spaces", "groups",
    "serve_teams", "serve_positions", "serve_assignments",
    "profiles", "booking_availability", "businesses",
})

# What a part is called when it couldn't be read.
PART_WORDS = {
    "services": "the Sunday counts",
    "first_time": "first-time guests",
    "new_people": "new people",
    "follow_up": "follow-up",
    "needed": "the places still open",
    "coming": "the calendar",
}


class _Unread(Exception):
    """A read that didn't answer. Its part is left out, never said as 0."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _n(k: int, one: str, many: str) -> str:
    return f"{k} {one if k == 1 else many}"


def _day_words(d: date) -> str:
    """'Sunday, November 15'."""
    return f"{d:%A}, {d:%B} {d.day}"


def _service_words(h: Dict[str, Any]) -> str:
    """'Sunday service, November 15' (the day is left off when the title
    already says it), else 'Midweek service, Wednesday, November 11'."""
    try:
        d = date.fromisoformat(h["day"])
    except (KeyError, ValueError):
        return f"{h.get('title', 'A service')}, {h.get('words', '')}".rstrip(", ")
    if f"{d:%A}".lower() in str(h["title"]).lower():
        return f"{h['title']}, {d:%B} {d.day}"
    return f"{h['title']}, {h['words']}"


def _rows(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise _Unread(path.split("?", 1)[0])
    return rows


def _count(path: str) -> int:
    n = sb_clients.sb_count_as_service(path)
    if n is None:
        raise _Unread(path.split("?", 1)[0])
    return int(n)


def _chunks(ids: List[str], n: int = 100) -> List[List[str]]:
    return [ids[i:i + n] for i in range(0, len(ids), n)]


# ─── The parts ────────────────────────────────────────────────────────

def _services(biz_id: str, today: date) -> Dict[str, Any]:
    """Each service in the days that has a count, and the counted service
    before them. The count is Reports' own (church_reports.sunday): the
    people checked in by name or the headcount, whichever is larger. The
    people checked in are counted by the database, one service at a time,
    so a full room is never cut at a page of rows."""
    import church_reports as cr
    ctx = {"b": _q(biz_id), "shared": cr._Shared()}
    try:
        occ = [o for o in cr._occasions(ctx) if o["kind"] == "service" and o["day"] <= today]
    except cr.Unread as e:
        raise _Unread(str(e))
    first = today - timedelta(days=BACK_DAYS)
    occ.sort(key=lambda o: o["day"], reverse=True)
    inside = [o for o in occ if o["day"] >= first]
    earlier = [o for o in occ if o["day"] < first][:LOOK_BACK]
    b = _q(biz_id)
    heads: Dict[str, int] = {}
    for part in _chunks([o["id"] for o in inside + earlier]):
        for r in _rows(f"/attendance_headcounts?business_id=eq.{b}&entry_id=in.({','.join(_q(i) for i in part)})"
                       f"&select=entry_id,count&limit={PAGE}"):
            heads[str(r["entry_id"])] = heads.get(str(r["entry_id"]), 0) + max(0, int(r.get("count") or 0))

    def total(o: Dict[str, Any]) -> int:
        named = _count(f"/attendance?business_id=eq.{b}&entry_id=eq.{_q(o['id'])}&select=id")
        return max(named, heads.get(o["id"], 0))

    def said(o: Dict[str, Any], n: int) -> Dict[str, Any]:
        return {"title": o["title"], "day": o["day"].isoformat(), "words": _day_words(o["day"]), "count": n}

    held, uncounted = [], 0
    for o in sorted(inside, key=lambda o: o["day"]):
        n = total(o)
        if n > 0:
            held.append(said(o, n))
        else:
            uncounted += 1
    before = None
    for o in earlier:                     # newest first: the last one with a count
        n = total(o)
        if n > 0:
            before = said(o, n)
            break
    return {"held": held, "before": before, "uncounted": uncounted}


def _first_time(biz_id: str, since: datetime) -> int:
    """People marked first time in the days: at check-in, or on a New here
    card. One person once, however they were marked. Names are read to
    tell two check-ins apart, never kept."""
    b, at = _q(biz_id), _q(_iso(since))
    seen = set()
    for r in _rows(f"/attendance?business_id=eq.{b}&first_time=is.true&checked_in_at=gte.{at}"
                   f"&select=contact_id,name&limit={PAGE}"):
        key = f"c:{r['contact_id']}" if r.get("contact_id") else "n:" + _plain(r.get("name")).lower()
        if key != "n:":
            seen.add(key)
    for r in _rows(f"/church_follow_ups?business_id=eq.{b}&source_event=like.{_q('first-visit:*')}"
                   f"&created_at=gte.{at}&select=contact_id&limit={PAGE}"):
        if r.get("contact_id"):
            seen.add(f"c:{r['contact_id']}")
    return len(seen)


def _new_people(biz_id: str, now: datetime) -> Dict[str, int]:
    b = _q(biz_id)
    week, two = _q(_iso(now - timedelta(days=7))), _q(_iso(now - timedelta(days=14)))
    return {
        "this_week": _count(f"/contacts?business_id=eq.{b}&created_at=gte.{week}&select=id"),
        "week_before": _count(f"/contacts?business_id=eq.{b}&created_at=gte.{two}&created_at=lt.{week}&select=id"),
    }


def _follow_up(biz_id: str, now: datetime) -> Dict[str, int]:
    """Counts, never a name, each counted by the database: who is in
    follow-up, who has no one (handed back, or never handed: the leaders
    note's rule), who is late, and how many were finished this week."""
    b = _q(biz_id)
    live = f"/church_follow_ups?business_id=eq.{b}&status=in.(open,handed_back)"
    return {
        "open": _count(f"{live}&select=id"),
        "no_one": _count(f"{live}&or=(status.eq.handed_back,leader_contact_id.is.null)&select=id"),
        "late": _count(f"/church_follow_ups?business_id=eq.{b}&status=eq.open&due_at=lt.{_q(_iso(now))}&select=id"),
        "finished": _count(f"/church_follow_ups?business_id=eq.{b}&status=eq.done"
                           f"&done_at=gte.{_q(_iso(now - timedelta(days=7)))}&select=id"),
    }


def _ahead(biz: Dict[str, Any], tz, today: date) -> Dict[str, Any]:
    """The week ahead, read where the leaders note reads it."""
    import church_leaders_note as ln
    from fastapi import HTTPException
    biz_id = str(biz["id"])
    last = today + timedelta(days=AHEAD_DAYS - 1)
    lo = datetime.combine(today, time(0), tzinfo=tz)
    hi = datetime.combine(last + timedelta(days=1), time(0), tzinfo=tz)
    out: Dict[str, Any] = {"coming": None, "needed": None}
    try:
        plans = ln._plans(biz_id, lo, hi, tz)
        occasions = ln._occasions(biz_id, today, last, tz)
    except HTTPException:
        return out
    try:
        items = ln.calendar(plans, occasions, ln._rooms(biz_id, lo, hi, tz))
        out["coming"] = [{"day": i["day"].isoformat(), "words": _day_words(i["day"]),
                          "at": ln.clock(i["at"]) if i["at"] else "", "title": i["title"], "where": i["where"]}
                         for i in items]
    except HTTPException:
        pass
    try:
        sunday = ln._sunday_places(biz_id, plans)
        text = ln.needed_text(sunday, occasions, 0)
        out["needed"] = {"open_places": sum(s["open"] for s in sunday),
                         "waiting": sum(s["waiting"] for s in sunday),
                         "roles": sum(1 for o in occasions if o.get("short")),
                         "lines": [ln_ for ln_ in text.split("\n\n") if ln_.strip()]}
    except HTTPException:
        pass
    return out


def week(biz: Dict[str, Any]) -> Dict[str, Any]:
    """The church's week, part by part. Never raises: a part that couldn't
    be read is None and is named in `unread`."""
    biz_id = str(biz["id"])
    now = _now()
    try:
        import church_leaders_note as ln
        tz = ln._zone(biz)
    except Exception:  # noqa: BLE001 — a clock that can't be read: UTC days, said plainly below
        tz = timezone.utc
    today = now.astimezone(tz).date()
    since = datetime.combine(today - timedelta(days=BACK_DAYS), time(0), tzinfo=tz)
    out: Dict[str, Any] = {"today": today.isoformat(), "ending": _day_words(today)}

    def part(key: str, fn) -> None:
        try:
            out[key] = fn()
        except _Unread as e:
            logger.info("church briefing: %s not read (%s)", key, e)
            out[key] = None
        except Exception:  # noqa: BLE001 — one part never takes the letter down
            logger.warning("church briefing: %s failed", key, exc_info=True)
            out[key] = None

    part("services", lambda: _services(biz_id, today))
    part("first_time", lambda: _first_time(biz_id, since))
    part("new_people", lambda: _new_people(biz_id, now))
    part("follow_up", lambda: _follow_up(biz_id, now))
    try:
        out.update(_ahead(biz, tz, today))
    except Exception:  # noqa: BLE001
        logger.warning("church briefing: the week ahead failed", exc_info=True)
        out.update({"coming": None, "needed": None})
    out["unread"] = [k for k in PART_WORDS if out.get(k) is None]
    return out


# ─── Said to the model ────────────────────────────────────────────────

def reader_of(biz: Dict[str, Any]) -> str:
    """Who the letter is written to: the name the church gave, else the
    church's leaders. Never "the practitioner"."""
    name = _plain((biz.get("settings") or {}).get("practitioner_name"))
    return name if name and name.lower() not in ("the practitioner", "the team") else ""


def system_prompt(biz: Dict[str, Any]) -> str:
    name = _plain(biz.get("name")) or "this church"
    voice = biz.get("voice_profile") or {}
    tone = voice.get("tone", "warm and direct")
    reader = reader_of(biz)
    to = f"{reader} and the people who run the church with them" if reader else "the people who run the church"
    by_name = (f"- Address {reader} by name once, near the top. Name no one else." if reader
               else "- Name no one.")
    return f"""You are Chief, writing the weekly briefing for {name}, a church. Write it to {to}.

Voice: {tone}. Voice profile details: {json.dumps(voice)[:600]}

Write EXACTLY four markdown sections with these exact headers, in this order:

## {HEADLINE}
One sentence: the most important thing about the church's week.

## {WENT_WELL}
2-3 bullet points taken from the facts: a Sunday count, first-time guests, new people, follow-ups finished, meetings held.

## {ATTENTION}
2-3 bullet points on what is waiting on someone: people in follow-up with no one yet, follow-up that is late, places still open on a team, drafts waiting in Approvals. If nothing is waiting, say so in one line.

## {FOCUS}
One specific thing to do this week, grounded in the facts and in what is coming.

Rules:
- Under 300 words. Warm, plain and direct, like a trusted friend over coffee. Short sentences. No dashes used as punctuation.
- Church words only: people, members and guests (never clients, customers, contacts or leads); a meeting (never a session); the church (never the business or the practice); Approvals (never the Queue).
- Never mention giving, money, payments or scores of any kind.
{by_name}
- Do NOT invent anything. Every number in the facts was read from the church's records. Repeat a number exactly as given. You may say one given number is more or fewer than another given number; never add, subtract, average or estimate.
- A fact marked "not read this time" is unknown, not zero. Say nothing about it except, at most, that it could not be read.
- A low number is not a failing. Never scold.
- The numbers, the places still open and the calendar are printed under your letter exactly as given. Do not write a numbers section and do not list the calendar."""


def facts(stats: Dict[str, Any]) -> str:
    """The data block the model writes from: the church's week, and the two
    things the business briefing already read that a church has too
    (meetings booked on its Meetings page, drafts waiting in Approvals)."""
    w = stats.get("church_week") or {}
    lines: List[str] = [f"THE CHURCH'S WEEK: the seven days ending {w.get('ending') or stats.get('window_end', '')[:10]}", ""]

    s = w.get("services")
    if s is not None:
        lines.append("SERVICES WITH A COUNT:")
        if s["held"]:
            lines += [f"  - {_service_words(h)}: {h['count']} counted" for h in s["held"]]
        else:
            lines.append("  - No service in these days has a count yet.")
        if s.get("uncounted"):
            lines.append(f"  - {_n(s['uncounted'], 'service', 'services')} in these days {'has' if s['uncounted'] == 1 else 'have'} no count.")
        if s.get("before"):
            b = s["before"]
            lines.append(f"THE COUNTED SERVICE BEFORE THOSE: {_service_words(b)}: {b['count']} counted")
    if w.get("first_time") is not None:
        lines.append(f"FIRST-TIME GUESTS (marked at check-in or on a New here card): {w['first_time']}")
    p = w.get("new_people")
    if p is not None:
        lines.append(f"NEW PEOPLE ADDED TO THE CHURCH'S RECORDS: {p['this_week']} this week, {p['week_before']} the week before")
    f = w.get("follow_up")
    if f is not None:
        lines.append(f"FOLLOW-UP: {_n(f['open'], 'person is', 'people are')} in follow-up; {f['no_one']} "
                     f"{'has' if f['no_one'] == 1 else 'have'} no one to reach out to them yet; {f['late']} "
                     f"{'is' if f['late'] == 1 else 'are'} late; {_n(f['finished'], 'follow-up was', 'follow-ups were')} "
                     "finished this week")
    lines.append(f"MEETINGS (booked on the Meetings page): {stats.get('sessions_completed_count', 0)} held this week, "
                 f"{stats.get('sessions_upcoming_count', 0)} coming in the next seven days")
    pending = stats.get("pending_items") or []
    lines.append(f"DRAFTS WAITING IN APPROVALS: {len(pending)}{' or more' if len(pending) >= 5 else ''}")

    need = w.get("needed")
    if need is not None:
        lines += ["", "PLACES STILL OPEN IN THE NEXT SEVEN DAYS:"]
        lines += [f"  - {ln_}" for ln_ in need["lines"][:MAX_NEEDED]] or ["  - None. Every place on the Sunday teams and every event role is filled."]
    coming = w.get("coming")
    if coming is not None:
        lines += ["", "COMING IN THE NEXT SEVEN DAYS:"]
        lines += [f"  - {c['words']}: {' '.join(x for x in (c['at'], c['title']) if x)}" for c in coming[:MAX_COMING]] \
            or ["  - Nothing is on the church calendar."]
    unread = [PART_WORDS[k] for k in (w.get("unread") or []) if k in PART_WORDS]
    if unread:
        lines += ["", "NOT READ THIS TIME (unknown, not zero): " + ", ".join(unread)]

    vertical = stats.get("church_vertical_block") or ""
    if vertical:
        lines += ["", vertical]
    return "\n".join(lines) + "\n"


# ─── Printed under the letter ─────────────────────────────────────────

def numbers_markdown(stats: Dict[str, Any]) -> str:
    """The numbers, the places still open and the calendar, as markdown the
    model never touches. '' when there is nothing to print."""
    w = stats.get("church_week") or {}
    blocks: List[str] = []

    nums: List[str] = []
    s = w.get("services")
    if s is not None:
        before = s.get("before")
        for i, h in enumerate(s["held"]):
            tail = f" ({before['count']} at the service before)" if before and i == 0 else ""
            nums.append(f"- **{_service_words(h)}:** {h['count']} counted{tail}")
        if not s["held"]:
            nums.append("- **Sunday:** no service in these days has a count yet")
    if w.get("first_time") is not None:
        nums.append(f"- **First-time guests:** {w['first_time']}")
    p = w.get("new_people")
    if p is not None:
        nums.append(f"- **New people added:** {p['this_week']} ({p['week_before']} the week before)")
    f = w.get("follow_up")
    if f is not None:
        nums.append(f"- **In follow-up:** {f['open']}"
                    + (f", and {f['no_one']} {'has' if f['no_one'] == 1 else 'have'} no one yet" if f["no_one"] else "")
                    + (f"; {f['late']} late" if f["late"] else ""))
        nums.append(f"- **Follow-ups finished:** {f['finished']}")
    held, ahead = stats.get("sessions_completed_count", 0), stats.get("sessions_upcoming_count", 0)
    if held or ahead:
        nums.append(f"- **Meetings:** {held} held, {ahead} coming")
    pending = stats.get("pending_items") or []
    if pending:
        nums.append(f"- **Drafts waiting in Approvals:** {len(pending)}{' or more' if len(pending) >= 5 else ''}")
    unread = [PART_WORDS[k] for k in (w.get("unread") or []) if k in PART_WORDS]
    if unread:
        nums.append("- **Not read this time:** " + ", ".join(unread))
    if nums:
        blocks.append("\n".join([f"## {NUMBERS}"] + nums))

    need = w.get("needed")
    if need and need["lines"]:
        blocks.append("\n".join([f"## {OPEN_PLACES}"] + [f"- {ln_}" for ln_ in need["lines"][:MAX_NEEDED]]))

    coming = w.get("coming")
    if coming:
        by_day: Dict[str, List[str]] = {}
        for c in coming[:MAX_COMING]:
            said = c["title"] + (f" at {c['at']}" if c["at"] else "") + (f" ({c['where']})" if c["where"] else "")
            by_day.setdefault(c["words"], []).append(said)
        rows = [f"- **{day}:** " + "; ".join(said) for day, said in by_day.items()]
        more = len(coming) - MAX_COMING
        if more > 0:
            rows.append(f"- And {more} more on the church calendar")
        blocks.append("\n".join([f"## {COMING}"] + rows))
    return "\n\n".join(blocks)


def fallback_body() -> str:
    """The letter when the model didn't answer: one true line, with the
    numbers still printed under it."""
    return (f"## {HEADLINE}\n"
            "The letter couldn't be written this time. The week's numbers are below, straight from the church's records.\n")


# ─── The drafts the briefing queues ───────────────────────────────────

def recorded_words(days: Optional[int]) -> str:
    """Why a check-in was drafted, in a church's words."""
    if days is None or days <= 0:
        return ""
    return f"nothing recorded in {_n(days, 'day', 'days')}"


def check_in_prompts(biz: Dict[str, Any], contact: Dict[str, Any], days: Optional[int], sender: str, tone: str):
    """(system, user, reasoning) for a check-in to one of the church's
    people. No score, no attendance record, no money."""
    name = contact.get("name", "there")
    since = f"Nothing has been recorded for {name} in {_n(days, 'day', 'days')}." if days and days > 0 \
        else f"It has been a while since anything was recorded for {name}."
    system = (f"You are writing for {biz.get('name', 'the church')}, a church. Draft a short, warm check-in from "
              f"{sender} to {name}, one of the church's people.\n\n"
              "Be pastoral, never transactional. Do not mention money, giving, attendance records, scores or how "
              "long it has been. Do not guess at why they have been quiet.\n\n"
              f"Voice: \"{tone}\". Under 4 sentences. No pressure and no guilt. Sign off as {sender}.")
    user = (f"Person: {name}\n{since}\n\n"
            "Draft a gentle note that says they are thought of and leaves the door open.")
    why = recorded_words(days)
    reasoning = (f"{why[0].upper() + why[1:]} for {name}. " if why else "") + "Drafted with the weekly briefing."
    return system, user, reasoning


def meeting_followup_prompts(biz: Dict[str, Any], contact: Dict[str, Any], title: str, notes: str, sender: str, tone: str):
    """(system, user, subject, reasoning) for a note after a meeting."""
    name = contact.get("name", "there")
    title = title or "our meeting"
    system = (f"You are writing for {biz.get('name', 'the church')}, a church. Draft a follow-up note from {sender} to "
              f"{name} after the meeting they just had.\n\n"
              "Be pastoral, never transactional. Do not mention money or giving.\n\n"
              f"Voice: \"{tone}\". Under 5 sentences. Say something true about the meeting, and include one next "
              f"step or question. Sign off as {sender}.")
    user = (f"Person: {name}\nMeeting: {title}\nNotes from the meeting: {notes or '(none recorded)'}\n\n"
            "Draft the follow-up note.")
    return system, user, f"Following up on {title}", f"A follow-up after a meeting ({title}). Drafted with the weekly briefing."


def actions_markdown(actions: List[Dict[str, Any]], pending_proposals: int, days_since) -> str:
    """The drafts list as stored in the letter's body, in a church's words.
    '' when there is nothing to show."""
    if not actions and pending_proposals == 0:
        return ""
    lines = [f"## {DRAFTS}"]
    for a in actions:
        name = a.get("contact_name") or "someone"
        follow = a.get("action_type") == "follow_up"
        if a["kind"] == "created":
            if a.get("agent") == "session":
                lines.append(f"- A follow-up after your meeting with {name} is drafted and waiting in Approvals")
            elif a.get("agent") == "nurture":
                lines.append(f"- A check-in for {name} is drafted and waiting in Approvals")
            else:
                lines.append(f"- A note for {name} is drafted and waiting in Approvals")
        elif a["kind"] == "already_queued":
            d = days_since(a.get("existing_created_at"))
            when = f"for {_n(d, 'day', 'days')}" if d and d > 0 else "since earlier today"
            lines.append(f"- A {'follow-up' if follow else 'check-in'} for {name} has been waiting in Approvals {when}")
    if pending_proposals > 0:
        lines.append(f"- {_n(pending_proposals, 'proposal has', 'proposals have')} been waiting in Approvals since earlier this week")
    lines += ["", "Open Approvals to read them and send the ones you want."]
    return "\n".join(lines)
