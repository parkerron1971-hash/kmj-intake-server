"""member_portal_dates.py — Dates on the member app's Lead tab: a leader's time
away (docs/CHURCH_SCHEDULE.md, PR S1-5; church_schedule.py is the engine).

Kevin, 2026-11-18: "I want to be able to build Leaders schedule. this is for
when leaders are planning time off and have certain obiligations so that we
as a church can plan around meeting". Leaders don't get office logins; they
use the member app. So this is where one of the church's people asks to be
away, says "I can't make it", sees who else is away, and says yes or not this
one to what went to them.

    Waiting for your yes ... the asks that went to this person (only when
                             there are any): who, the days, what kind, their
                             reason, who covers; Yes, or Not this one with a
                             short note
    Ask for time off ....... first day, last day, time off or another
                             commitment, a private reason, who covers (one of
                             the people on the schedule, or a typed name)
    I can't make it ........ the day or days and a private note: for the days
                             just ahead, on the calendar at once, no yes
    My dates ............... their own asks and where each stands; Take it back
    Who else is away ....... name, days, who covers. Never a reason, never a
                             note, never what kind

    GET  /my/lead/dates                      the page (member_portal_lead.serve
                                             hands it over while
                                             church_schedule.section says this
                                             person has one)
    POST /my/lead/dates/ask                  {start, end, kind, reason, cover,
                                             cover_name}
    POST /my/lead/dates/cant                 {start, end, reason}
    POST /my/lead/dates/<id>/answer          {ans: yes | no, note}
    POST /my/lead/dates/<id>/withdraw        take it back

A MEMBER-APP SESSION IS A PERSON, NEVER A LOGIN. Every call into the engine
is made as church_over.who(PERSON, this person), whoever they are: the
owner's own person and the person of whoever oversees the office get no
across-the-board view here (docs/CHURCH_SCHEDULE.md section 7, item 6). They
read a reason, and answer, only for an ask that went to them (or to the
office login tied to exactly them), and their own. `_ch_me` is the one place
that says who `me` is.

THE LIMIT (step 2, PR S2-3; only while church_schedule.step2() says its
tables are there, and otherwise this page is exactly step 1's):

    before sending ...... "Ask for these days" on days that are full, or on
                          a protected day, SENDS NOTHING the first time. The
                          page comes back with what they typed still in the
                          form and says plainly which day is full or
                          protected, the nearest open service days either
                          side, and that asking anyway goes to the one who
                          can make an exception (by the church's own name for
                          them). "Ask anyway" sends it
    after sending ....... their card says the same, and who it is waiting on
    whoever it went up to  their card says why it came to them: how many are
                          already away that day, or that the day is
                          protected. A count, never a name: who is away is
                          under Who else is away for those who may see it

PAIRS (S2-4): two people who can't be away together. The one asking is told,
before sending and on their card, only that "this overlaps with someone you
can't be away with at the same time": never who, never which days are the
other's, and their card says it from the ask's own flag, so it never changes
as the other's asks do. No nearest open days are offered for a pair alone.
Whoever it went up to reads, in "Why it came to you", who it overlaps with
only when they are the one who may give the exception (the owner's person,
or that of whoever oversees the office, on an ask that went up to them);
anyone else who has the card reads the same words without a name.

VOLUNTEERS (S2-5): a volunteer's Away on My serving that went to their team's
leader (church_schedule_volunteers) waits here, under Waiting for your yes,
for whoever it went to, whether or not they are on the leaders schedule
themself (church_schedule.section gives them the entry while it waits). Its
card says why it came to them: the volunteer is on the schedule to serve on
one of those days, or a day is full for their department (a count and the
day, never who). Their yes is a plain yes, over the department's number too.

A reason, and the note that came with an answer, appear only where
church_schedule.shape() gave them. "Who else is away" is built from name,
days and who covers alone (view's `away`), so nothing else can be printed
there. No id is on the screen: ids ride in form addresses and option values.

Every write is church_schedule's own (it checks the church, the person and
who may); here: a live session at this church (member_portal_church.
_signed_in, which refuses a cross-site POST and reads Origin: null by the
browser's Sec-Fetch-Site), never the owner's preview, the church's switch and
its tables (church_schedule.on: a 404 without them), the per-person rate
limit, and a redirect back with a short code. A refusal comes back as plain
words on the page, never as a raw error.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter()

HERE = "/my/lead/dates"
_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
WINDOW_DAYS = 62            # who else is away: the next two months (church_schedule.WINDOW_DEFAULT)
PICK_MAX = 200              # who covers: at most this many names in the list; anyone else is typed
PLANNED = ("time_off", "commitment")
KIND_WORDS = {"time_off": "Time off", "commitment": "Another commitment", "cant": "Can’t make it"}
NOT_OFFERED = "That isn’t one of the names on the list"

# {to}: who this person's asks go to, by the name the church knows them by.
DONE = {
    "dt_asked": "Asked. It’s waiting for {to}’s yes.",
    "dt_asked_short": "Asked. It’s short notice, so {to} may need a little time with it.",
    "dt_set": "It’s on the calendar.",
    "dt_cant": "Got it. It’s on the calendar.",
    "dt_yes": "You said yes. It’s on the calendar now.",
    "dt_no": "You said not this one.",
    "dt_back": "Taken back.",
}
DONE_ALONE = {"dt_asked": "Asked. It’s waiting for a yes.",
              "dt_asked_short": "Asked. It’s short notice, so the answer may take a little time.",
              "dt_asked_up": "Asked. It went to the one who can make an exception."}
# {up}: who can make an exception for this person, by the name the church knows them by.
DONE_UP = {"dt_asked_up": "Asked. It went to {up}, who can make an exception.",
           "dt_yes_x": "You said yes, as an exception. It’s on the calendar now."}
NOT_SENT = "Not sent yet. A day you picked is full or protected. Have a look under Ask for time off."
NOT_SENT_PAIR = ("Not sent yet. These days overlap with someone you can’t be away with at the same time. Have a look "
                 "under Ask for time off.")
# A pair, said three ways (S2-4). Never which days are the other's.
PAIR_YOU = "This overlaps with someone you can’t be away with at the same time."
PAIR_THEY = "It overlaps with someone they can’t be away with at the same time."
WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
WHY_MAX = 3                 # how many full or protected days a card spells out; the rest are counted
# {n}: the days "can't make it" reaches (the church's notice days, two at least).
ERRORS = {
    "error": "That didn’t save. Please try again.",
    "slow": "That was a lot at once. Wait a moment, then try again.",
    "preview": "This is a preview. Nothing is saved.",
    "dt_days": "Pick the days: a year at most, and not in the past.",
    "dt_far": "Can’t make it is for the next {n} days. For days farther out, ask for time off instead, so everyone can "
              "plan for it.",
    "dt_many": "That’s a lot of asks still waiting. Take one back first.",
    "dt_waiting": "Those days are already waiting for an answer.",
    "dt_cover": "Someone else covers, not the one who is away.",
    "dt_cover_who": "Pick who covers from the list, or type their name.",
    "dt_long": "That was a little long. Keep a reason to 500 letters, a note to 300 and a name to 80.",
    "dt_said": "That didn’t come through. Check it and try again.",
    "dt_not_on": "You aren’t on the leaders schedule here, so there’s nothing to ask for. The church office can add you.",
    "dt_not_yours": "That one isn’t yours to answer.",
    "dt_not_asker": "Only the one who asked takes it back here.",
    "dt_gone": "That isn’t one of yours.",
    "dt_already": "That one was already answered.",
    "dt_no_yes": "That one needs no yes.",
    "dt_closed": "That one can’t be taken back anymore.",
    "dt_changed": "That changed just now. Here it is as it stands.",
    "dt_up": "Those days have changed since this was asked: one of them is full now, or is a protected day. Your yes "
             "didn’t go through, and it has gone on to the one who can make an exception.",
    "dt_yours": "Those days have changed since this was asked: one of them is full now, or is a protected day. Your "
                "yes didn’t go through yet. It’s marked below. Say yes again to make an exception.",
    "dt_up_now": "Those days have changed since this was asked, and they need an exception now. Your yes didn’t go "
                 "through, and it has gone on to the one who can make an exception.",
    "dt_yours_now": "Those days have changed since this was asked, and they need an exception now. Your yes didn’t go "
                    "through yet. It’s marked below. Say yes again to make an exception.",
}

DATES_CSS = """
.ld-tks.dt-page{max-width:none;}
.dt-sec{display:flex;flex-direction:column;gap:12px;min-width:0;}
.dt-sec + .dt-sec{margin-top:22px;}
.dt-card{gap:10px;min-width:0;}
.dt-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;}
.dt-top b{font-size:17px;font-weight:650;line-height:1.3;min-width:0;overflow-wrap:anywhere;}
.dt-state{flex:none;display:inline-flex;align-items:center;min-height:26px;padding:0 10px;border-radius:999px;
  background:var(--s3);color:var(--fg);font-size:12px;font-weight:700;white-space:nowrap;}
.dt-state.wait{background:var(--mb-soft);box-shadow:inset 0 0 0 .5px var(--mb-soft-line);}
.dt-state.yes{background:rgba(95,208,138,.24);}
.dt-state.no,.dt-state.short{background:rgba(255,138,92,.22);}
.dt-state.back{color:var(--fg2);}
.dt-state.short{align-self:flex-start;}
.dt-when{margin:0;font-size:15px;line-height:1.4;overflow-wrap:anywhere;}
.dt-meta{margin:0;font-size:13.5px;color:var(--fg2);line-height:1.45;overflow-wrap:anywhere;}
.dt-meta b{color:var(--fg);font-weight:600;}
.dt-it{background:var(--s2);border-radius:var(--r-sm);padding:10px 12px;display:flex;flex-direction:column;gap:4px;
  font-size:14.5px;line-height:1.4;}
.dt-it b{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--fg2);}
.dt-it p{margin:0;overflow-wrap:anywhere;white-space:pre-line;}
.dt-acts{display:flex;flex-direction:column;gap:8px;}
.dt-acts form,.dt-card > form{margin:0;}
.dt-more summary{list-style:none;cursor:pointer;}
.dt-more summary::-webkit-details-marker{display:none;}
.dt-more[open] summary{margin-bottom:10px;}
.dt-form{display:flex;flex-direction:column;gap:12px;margin:0;min-width:0;}
.dt-f{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:600;color:var(--fg2);min-width:0;}
.dt-f input,.dt-f select{min-height:48px;border-radius:12px;border:.5px solid var(--line);background:var(--s2);
  color:var(--fg);padding:0 12px;font:inherit;font-size:16px;font-weight:400;box-sizing:border-box;
  width:100%;min-width:0;}
.dt-f .ld-ta{min-height:84px;font-weight:400;}
.dt-f input:focus-visible,.dt-f select:focus-visible,.dt-f .ld-ta:focus-visible,.dt-page .ld-btn:focus-visible,
.dt-page .ld-ghost:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.dt-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-items:end;}
.dt-hint{margin:0;font-size:13px;line-height:1.45;color:var(--fg2);overflow-wrap:anywhere;}
.dt-lede{margin:0;font-size:14.5px;line-height:1.45;color:var(--fg2);}
.dt-list{display:flex;flex-direction:column;gap:8px;}
.dt-row{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:var(--r-md);background:var(--s1);
  min-height:56px;box-sizing:border-box;}
.dt-row .t{display:flex;flex-direction:column;min-width:0;flex:1;}
.dt-row .t b{font-size:15.5px;font-weight:650;overflow-wrap:anywhere;}
.dt-row .t small{font-size:13px;color:var(--fg2);}
.dt-cov{font-size:12.5px;color:var(--fg2);text-align:right;max-width:46%;overflow-wrap:anywhere;}
.dt-old summary{list-style:none;cursor:pointer;}
.dt-old summary::-webkit-details-marker{display:none;}
.dt-old[open] summary{margin-bottom:12px;}
.dt-old .dt-list{gap:12px;}
.dt-it.dt-full{background:rgba(255,138,92,.16);box-shadow:inset 0 0 0 .5px rgba(255,138,92,.5);gap:8px;}
.dt-it.dt-full p{white-space:normal;}
"""


def _e(s: Any) -> str:
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


def _first(name: Any) -> str:
    return (str(name or "").strip().split(" ") or [""])[0] or "someone"


# ─── Days, in plain words ─────────────────────────────────────────────

def _day(v: Any, today: date) -> str:
    """'Sun, Dec 20'; the year only when it isn't this one."""
    import church_schedule as cs
    d = cs._day(v)
    if not d:
        return "a day"
    said = f"{d:%a}, {d:%b} {d.day}"
    return said if d.year == today.year else f"{said}, {d.year}"


def _days(a: Any, b: Any, today: date) -> str:
    return _day(a, today) if str(a)[:10] == str(b)[:10] else f"{_day(a, today)} to {_day(b, today)}"


def _on_day(ts: Any, tz, today: date) -> str:
    """The church's own day a moment fell on: '' when it can't be read."""
    try:
        at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if at.tzinfo is None:
        return _day(at.date().isoformat(), today)
    return _day(at.astimezone(tz).date().isoformat(), today)


def _span(n: int) -> str:
    """How far "can't make it" reaches, said the way people say it."""
    return {7: "week", 14: "two weeks", 21: "three weeks", 28: "four weeks"}.get(n, f"{n} days")


# ─── What the page shows ──────────────────────────────────────────────

def _ch_me(biz: Dict[str, Any], me: Dict[str, Any]):
    """The church, and `me` as the engine takes it. ALWAYS A PERSON: this is
    the member app, and nobody here carries a login's standing, whoever
    they are (the owner's own person, the person of whoever oversees the
    office). Everything on this page and every write goes through here."""
    import church_over as co
    return co.Church(biz), co.who(co.PERSON, str(me["id"]))


def _pick(ch, roster, cid: str) -> List[Dict[str, str]]:
    """Who can be picked to cover: the people on the leaders schedule, by
    name, never the one asking. Only this church's (Church.names reads by
    business and by id, a hundred at a time), and PICK_MAX at most: anyone
    else, a volunteer say, is typed as a name."""
    ids = sorted(roster.people() - {cid})
    names = ch.names(ids)
    rows = [{"id": i, "name": names[i]} for i in ids if names.get(i) and names[i] != "Someone"]
    return sorted(rows, key=lambda r: (r["name"].casefold(), r["id"]))[:PICK_MAX]


def _on_calendar(ch, cid: str, ask_ids: Iterable[str]) -> Set[str]:
    """Which of these asks still have their away date. A yes is only on the
    calendar while its fact is in serve_away. Taking the date off under
    Serving, Away takes the ask back with it (church_schedule.withdraw_fact,
    S1-6); one taken off while the switch was closed for the church leaves
    the ask a yes with nothing behind it, and this page never calls that
    away (docs/CHURCH_SCHEDULE.md section 2.1)."""
    import church_over as co
    import church_schedule as cs
    out: Set[str] = set()
    for part in co._chunks(ask_ids, co.IDS_PER_READ):
        for f in cs._need(f"/serve_away?business_id=eq.{cs._q(ch.b)}&contact_id=eq.{cs._q(cid)}"
                          f"&ask_id=in.({cs._in(part)})&select=ask_id&limit={co.IDS_PER_READ}"):
            out.add(str(f.get("ask_id")))
    return out


def view(biz: Dict[str, Any], contact_id: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Everything the page shows, for one of the church's people. Every ask
    comes through church_schedule.shape() as that person. A read that fails
    raises a 503 for the whole page: a list that couldn't be read is never
    shown as empty.

    `away` (who else is away) holds a name, the days, who covers and whether
    it still waits for this person's yes, and nothing else, so the page has
    no reason, note or kind to show there even for an ask this person may
    read. It is read from the facts (church_schedule.calendar), and a
    waiting ask is in it only when this person may read it."""
    import church_map
    import church_schedule as cs
    ch, me = _ch_me(biz, {"id": contact_id})
    cid = me["id"]
    now = now or cs._now()
    with church_map.once():
        today = cs._today(ch, now)
        roster = cs.roster(ch)
        on_it = cid in roster.people()
        notice = cs.settings(ch)["notice_days"]
        mine = cs.mine(ch, me, now)
        waiting = cs.waiting(ch, me)
        top = bool(ch.owner_person) and cid == ch.owner_person      # nobody is over them: needs no yes
        to = cs.goes_to(ch, cid) if on_it and not top else None
        away: List[Dict[str, Any]] = []
        if on_it:
            cal = cs.calendar(ch, me, today, today + timedelta(days=WINDOW_DAYS))
            for g in cal["groups"]:
                for a, held in [(a, False) for a in g["away"]] + [(a, True) for a in g["waiting"]]:
                    if a["contact_id"] == cid:
                        continue                                    # their own are under My dates
                    away.append({"name": a["name"], "starts_on": a["starts_on"], "ends_on": a["ends_on"],
                                 "cover": (a.get("cover") or {}).get("name") or "", "waiting": held})
            away.sort(key=lambda a: (a["starts_on"], a["name"].casefold(), a["ends_on"]))
        people = _pick(ch, roster, cid) if on_it else []
        kept = _on_calendar(ch, cid, [a["id"] for a in mine if a["state"] == "yes" and a.get("id")])
        tz = ch.tz
        up = _limits(ch, cid, mine, waiting, now, on_it and not top) if cs.step2() else ""
    for a in mine:
        a["on_calendar"] = a["id"] in kept
    return {"mine": mine, "waiting": waiting, "away": away, "people": people, "on_it": on_it, "top": top,
            "to": to["name"] if to else "", "notice_days": notice, "near": max(notice, cs.CANT_FLOOR),
            "today": today, "tz": tz, "up": up}


def _limits(ch, cid: str, mine: List[Dict[str, Any]], waiting: List[Dict[str, Any]], now: datetime,
            asks: bool) -> str:
    """Step 2, for the page: who could make an exception for this person
    (by the church's own name for them; '' for someone who asks for nothing
    here, or needs no yes), and on each waiting ask that went up, `why`:
    what its days run into as things stand now (church_schedule_limits.
    flags_of: counts and day names, never who). One picture for them all;
    an ask it can't hold gets None, and the card says only that it went up.
    Nothing more is read when no ask is flagged.

    A pair (S2-4). On their own card it is said from the ask's flag, never
    looked at again (nothing about the other's time away reaches them as it
    changes), and their pairs are never read here. On a card waiting for
    this person's yes it is looked at as things stand (the asker's pairs,
    read once for all such cards), and it names the other only on a card
    this person may answer, which makes them the owner's person or that of
    whoever oversees the office, on an ask that went up to them."""
    import church_schedule as cs
    import church_schedule_limits as csl
    up = cs.goes_up(ch, cid)["name"] if asks else ""
    # A volunteer's ask on a day full for their department (S2-5) is looked
    # at the same way for its card, for that department alone.
    flagged = [a for a in mine + waiting if a.get("state") == "asked"
               and (cs.flagged(a) or (cs.volunteer(a) and "over_limit" in (a.get("flags") or [])))]
    spans = [(cs._day(a["starts_on"]), cs._day(a["ends_on"])) for a in flagged]
    spans = [(lo, hi) for lo, hi in spans if lo and hi]
    if not spans:
        return up
    lo = min(lo for lo, _hi in spans)
    hi = min(max(hi for _lo, hi in spans), lo + timedelta(days=csl.PICTURE_DAYS))
    theirs = {id(a) for a in mine}
    pic = csl.picture(ch, lo, hi, now=now, who={a["contact_id"] for a in flagged if id(a) not in theirs})
    for a in flagged:
        first, last = cs._day(a["starts_on"]), cs._day(a["ends_on"])
        if not (first and last and lo <= first and last <= hi):
            a["why"] = None
            continue
        own = id(a) in theirs
        why = csl.flags_of(pic, a["contact_id"], first, last, (a.get("department") or {}).get("id"),
                           before=a.get("created_at"), pairs=not own)["why"]
        if cs.volunteer(a):
            # Their department's number, and nothing of the leaders' rules.
            a["why"] = [w for w in why if w.get("flag") == "over_limit" and w.get("of") == "department"]
            continue
        if own and "pair" in (a.get("flags") or []):
            why.append({"flag": "pair"})                # as it was when they asked: never looked at again
        elif not own and a.get("can_answer"):
            for w in why:
                if w["flag"] == "pair":                 # the one who may give the exception reads who
                    hits = pic.pair_hits(a["contact_id"], first, last, a.get("created_at"))
                    names = ch.names(sorted(hits))
                    w["with"] = sorted((names.get(c, "") for c in hits if names.get(c) not in (None, "", "Someone")),
                                       key=str.casefold)
        a["why"] = why
    return up


def chief_line(v: Dict[str, Any]) -> str:
    """Chief's one line at the top: what waits for their yes first, then
    their own ask that waits, then what the page is for."""
    today = v["today"]
    if v["waiting"]:
        a, n = v["waiting"][0], len(v["waiting"])
        more = f" {n - 1} more below." if n > 1 else ""
        return (f"{_first(a['name'])} asked to be away {_days(a['starts_on'], a['ends_on'], today)}. "
                f"It’s waiting for your yes, or not this one.{more}")
    asked = [a for a in v["mine"] if a["state"] == "asked"]
    if asked:
        a = asked[0]
        who = f" for {(a.get('to') or {}).get('name')}" if (a.get("to") or {}).get("name") else ""
        return f"Your ask for {_days(a['starts_on'], a['ends_on'], today)} is waiting{who}. You can take it back below."
    if not v["on_it"]:
        return "Nothing is waiting for your yes right now."
    return "Nothing is waiting. Planning to be away? Ask early, so everyone can plan around it."


def _cover_line(a: Dict[str, Any]) -> str:
    name = (a.get("cover") or {}).get("name") or ""
    return f'<p class="dt-meta"><b>Covering</b> {_e(name)}</p>' if name else ""


def _short(a: Dict[str, Any]) -> str:
    """Short notice, said on a planned ask only: "can't make it" is always
    short, and saying so would only sound like a complaint."""
    short = "short_notice" in (a.get("flags") or []) and a.get("kind") != "cant"
    return '<span class="dt-state short">Short notice</span>' if short else ""


def _serving_line(a: Dict[str, Any], theirs: bool) -> str:
    """Said while an ask waits, when they had already said yes to serve on
    one of its days: a yes opens that place again (church_schedule.
    _open_places), and whoever says yes, and the one who asked, should know
    it before it happens."""
    if a.get("state") != "asked" or a.get("kind") == "cant" or "serving" not in (a.get("flags") or []):
        return ""
    if theirs:
        return ('<p class="dt-meta">You said yes to serve on one of these days. With a yes here, that place opens '
                'again for your team.</p>')
    return (f'<p class="dt-meta">{_e(_first(a.get("name")))} said yes to serve on one of these days. With your yes, '
            f'that place opens again for their team.</p>')


def _why_said(w: Dict[str, Any], today: date, theirs: bool = False) -> str:
    """One full or protected day, in plain words. A count and the day:
    never who is away. A pair: to the one asking (`theirs`) and to whoever
    else has the card, that it overlaps with someone they can't be away
    with; by name only where _limits put one (`with`)."""
    if w.get("flag") == "pair":
        who = [n for n in (w.get("with") or []) if n]
        if who:
            names = who[0] if len(who) == 1 else f"{', '.join(who[:-1])} and {who[-1]}"
            return (f"It overlaps with time away for {names}, "
                    f"{'someone' if len(who) == 1 else 'people'} they can’t be away with at the same time.")
        return PAIR_YOU if theirs else PAIR_THEY
    day = _day(w.get("day"), today)
    if w.get("flag") == "protected_day":
        return f"{day} is a protected day{' (' + w['name'] + ')' if w.get('name') else ''}."
    n = int(w.get("away") or 0)
    count = WORDS[n] if 0 < n < len(WORDS) else str(n)
    who = {"leaders": "of the leaders", "office": "from the office"}.get(w.get("of")) or f"from {w.get('name') or 'the team'}"
    return (f"{day} is full: {count} {who} {'is' if n == 1 else 'are'} already away, and that’s as many as can be "
            f"away at once.")


def _why_lines(why: List[Dict[str, Any]], today: date, theirs: bool = False) -> List[str]:
    """The first few days, soonest first, then how many more; then a pair,
    once (it has no day)."""
    pair = [w for w in why if w.get("flag") == "pair"]
    why = [w for w in why if w.get("flag") != "pair"]
    said = [_why_said(w, today) for w in why[:WHY_MAX]]
    more = len({w.get("day") for w in why[WHY_MAX:]} - {w.get("day") for w in why[:WHY_MAX]})
    if len(why) > WHY_MAX:
        said.append(f"And {more} more day{'s' if more != 1 else ''} like these." if more else "And more on those days.")
    return said + ([_why_said(pair[0], today, theirs)] if pair else [])


def _open_said(open_: Dict[str, Any], today: date) -> str:
    """The nearest open service days either side, when there are any."""
    days = [_day(d, today) for d in ((open_ or {}).get("before"), (open_ or {}).get("after")) if d]
    if len(days) == 2:
        return f"The nearest open days are {days[0]} and {days[1]}."
    return f"The nearest open day is {days[0]}." if days else ""


def _look_block(draft: Dict[str, Any], today: date) -> str:
    """Before sending: the days they picked are full or protected. Nothing
    has been sent. What is in the way, the nearest open days, and where it
    goes if they ask anyway."""
    lines = "".join(f"<p>{_e(x)}</p>" for x in _why_lines(draft.get("why") or [], today, theirs=True))
    near = _open_said(draft.get("open") or {}, today)
    up = draft.get("up") or ""
    still = (f"You can still ask for these days. It goes to {up}, who can make an exception." if up
             else "You can still ask for these days. It goes to the one who can make an exception.")
    return (f'<div class="dt-it dt-full" role="alert"><b>Not sent yet</b>{lines}'
            + (f"<p>{_e(near)}</p>" if near else "") + f"<p>{_e(still)}</p></div>")


def _up_line(a: Dict[str, Any], theirs: bool, today: date) -> str:
    """Said while an ask that went up waits (step 2). To the one who asked:
    what is in the way, and who can make the exception. To the one it came
    to: why it came to them, and that their yes makes an exception. Counts
    and days only. '' for an ask that didn't go up, and on a database with
    step 1 alone."""
    import church_schedule as cs
    if a.get("state") != "asked" or not cs.flagged(a) or "why" not in a:
        return ""
    why = a.get("why")
    to = (a.get("to") or {}).get("name") or ""
    to = "" if to == cs.LEFT else to
    if theirs:
        who = f"{to} can make an exception" if to else "It’s with the one who can make an exception"
        if why:
            body = "".join(f"<p>{_e(x)}</p>" for x in _why_lines(why, today, theirs=True)) + f"<p>{_e(who)}.</p>"
        elif why is None:
            body = f"<p>{_e(who)}.</p>"
        else:
            body = (f"<p>These days were full or protected when you asked, so it went up. There’s room now.</p>"
                    f"<p>{_e(who)}.</p>")
        return f'<div class="dt-it dt-full"><b>Needs an exception</b>{body}</div>'
    if why:
        body = ("".join(f"<p>{_e(x)}</p>" for x in _why_lines(why, today))
                + "<p>Your yes makes an exception.</p>")
    elif why is None:
        body = "<p>It needs an exception. Your yes makes one.</p>"
    elif "pair" in (a.get("flags") or []):
        body = ("<p>Something was in the way of these days when it was asked. Nothing is now, so your yes is a "
                "plain yes.</p>")
    else:
        body = ("<p>These days were full or protected when it was asked. There’s room now, so your yes is a plain "
                "yes.</p>")
    return f'<div class="dt-it dt-full"><b>Why it came to you</b>{body}</div>'


def _vol_line(a: Dict[str, Any], theirs: bool, today: date) -> str:
    """Said while a volunteer's ask waits (S2-5): why it went to their
    team's leader. They are on the schedule to serve on one of these days,
    and/or one of them is full for their department, as a count and the day
    (never who is away). To the one it came to, that their yes is all it
    needs; to the volunteer, who it is waiting on. '' for any other ask."""
    import church_schedule as cs
    if a.get("state") != "asked" or not cs.volunteer(a):
        return ""
    flags = a.get("flags") or []
    lines: List[str] = []
    if "serving" in flags:
        lines.append("You’re on the schedule to serve on one of these days." if theirs
                     else f"{_first(a.get('name'))} is on the schedule to serve on one of these days.")
    if "over_limit" in flags:
        why = a.get("why")
        dept = (a.get("department") or {}).get("name") or "their team"
        if why:
            lines += _why_lines(why, today)
        elif why is None:
            lines.append(f"One of these days was full for {dept} when {'you' if theirs else 'they'} asked.")
        else:
            lines.append(f"One of these days was full for {dept} when {'you' if theirs else 'they'} asked. "
                         "There’s room now.")
    if not lines:
        return ""
    if theirs:
        to = (a.get("to") or {}).get("name") or ""
        to = "" if to == cs.LEFT else to
        head = f"Why it went to {to}" if to else "Why it went to your team’s leader"
        end = "With a yes these days go on your away days."
    else:
        head, end = "Why it came to you", "Your yes is all it needs."
    return (f'<div class="dt-it dt-full"><b>{_e(head)}</b>' + "".join(f"<p>{_e(x)}</p>" for x in lines)
            + f"<p>{_e(end)}</p></div>")


def _shown(a: Dict[str, Any]) -> str:
    """What this card shows as being in the way, for its Yes to carry: the
    flags the "Why it came to you" box spells out (the days as they stand,
    `why`), or, when the box could only say that it needs an exception, the
    ask's own. '' for an ask that didn't go up, or whose days have cleared:
    that Yes is shown as a plain yes. The engine gives an exception only
    over what was shown (church_schedule.answer)."""
    import church_schedule as cs
    if a.get("state") != "asked" or not cs.flagged(a) or "why" not in a:
        return ""
    why = a.get("why")
    said = {w.get("flag") for w in why} if why is not None else set(a.get("flags") or [])
    return ",".join(f for f in cs.UP_FLAGS if f in said)


def _wait_card(a: Dict[str, Any], today: date, tz) -> str:
    """One ask waiting for this person's yes. shape() gave them its reason
    (it went to them): it shows here, to them, and nowhere else."""
    act = f"/my/lead/dates/{_e(a['id'])}/answer"
    reason = (f'<div class="dt-it"><b>Their reason · private</b><p>{_e(a["reason"])}</p></div>'
              if a.get("reason") else "")
    asked = _on_day(a.get("created_at"), tz, today)
    return (f'<section class="ld-pr dt-card" aria-label="{_e(a["name"])}">'
            f'<div class="dt-top"><b>{_e(a["name"])}</b>'
            f'<span class="dt-state wait">{_e(KIND_WORDS.get(a.get("kind"), "Time away"))}</span></div>'
            f'<p class="dt-when">{_e(_days(a["starts_on"], a["ends_on"], today))}</p>{_short(a)}'
            f'{_up_line(a, False, today)}{_vol_line(a, False, today)}{reason}'
            f'{_cover_line(a) or "<p class=dt-meta>Nobody is covering yet.</p>"}{_serving_line(a, False)}'
            + (f'<p class="dt-meta">Asked {_e(asked)}</p>' if asked else "")
            + f'<div class="dt-acts"><form method="post" action="{act}"><input type="hidden" name="ans" value="yes">'
            + (f'<input type="hidden" name="shown" value="{_e(_shown(a))}">' if _shown(a) else "") +
            f'<button class="ld-btn" type="submit">Yes</button></form>'
            f'<details class="dt-more"><summary class="ld-ghost">Not this one</summary>'
            f'<form class="dt-form" method="post" action="{act}"><input type="hidden" name="ans" value="no">'
            f'<label class="dt-f">A short note, if you like (private)'
            f'<textarea class="ld-ta" name="note" maxlength="300"></textarea></label>'
            f'<button class="ld-btn" type="submit">Say not this one</button></form></details></div></section>')


def _state(a: Dict[str, Any], today: date, tz) -> Dict[str, str]:
    """Where one of their own asks stands: the chip, and one plain line."""
    decided = a.get("decided") or {}
    by, when = decided.get("by") or "", _on_day(decided.get("at"), tz, today)
    on = f" on {when}" if when else ""
    state = a.get("state")
    if state == "asked":
        import church_schedule as cs
        to = a.get("to") or {}
        if a.get("kind") == "cant" or not to:
            return {"chip": "Not finished", "cls": "no",
                    "line": "This one didn’t finish saving. Send it again for the same days, or take it back."}
        if not to.get("name") or to["name"] == cs.LEFT:
            return {"chip": "Waiting", "cls": "wait", "line": "Waiting for a yes."}
        return {"chip": "Waiting", "cls": "wait", "line": f"Waiting for {to['name']}’s yes."}
    if state == "yes":
        if not a.get("on_calendar"):
            return {"chip": "Off the calendar", "cls": "back",
                    "line": (f"{by} said yes{on}" if by else "It was on the calendar")
                    + ", but these days were taken off your away dates since."}
        if by and a.get("excepted"):
            return {"chip": "Yes", "cls": "yes", "line": f"{by} said yes{on}, as an exception. It’s on the calendar."}
        if by:
            return {"chip": "Yes", "cls": "yes", "line": f"{by} said yes{on}. It’s on the calendar."}
        return {"chip": "On the calendar", "cls": "yes", "line": "On the calendar. It needed no yes."}
    if state == "no":
        return {"chip": "Not this one", "cls": "no", "line": f"{by or 'They'} said not this one{on}."}
    return {"chip": "Taken back", "cls": "back", "line": "Taken back. It’s off the calendar."}


def _mine_card(a: Dict[str, Any], today: date, tz) -> str:
    """One of their own asks. Their reason is their own; the note that came
    with the answer is there only when shape() gave it."""
    st = _state(a, today, tz)
    note = (a.get("decided") or {}).get("note")
    by = (a.get("decided") or {}).get("by") or ""
    note_html = (f'<div class="dt-it"><b>{_e(_first(by) + "’s note" if by else "Their note")} · private</b>'
                 f'<p>{_e(note)}</p></div>' if note else "")
    reason = (f'<div class="dt-it"><b>Your reason · private</b><p>{_e(a["reason"])}</p></div>'
              if a.get("reason") else "")
    back = ""
    if a.get("can_withdraw") and (a.get("state") == "asked" or a.get("on_calendar")):
        back = (f'<form method="post" action="/my/lead/dates/{_e(a["id"])}/withdraw">'
                f'<button class="ld-ghost" type="submit">Take it back</button></form>')
    days = _days(a["starts_on"], a["ends_on"], today)
    return (f'<section class="ld-pr dt-card" aria-label="{_e(days)}">'
            f'<div class="dt-top"><b>{_e(days)}</b><span class="dt-state {st["cls"]}">{_e(st["chip"])}</span></div>'
            f'<p class="dt-meta">{_e(KIND_WORDS.get(a.get("kind"), "Time away"))}</p>{_short(a)}'
            f'<p class="dt-when">{_e(st["line"])}</p>{_up_line(a, True, today)}{_vol_line(a, True, today)}'
            f'{_serving_line(a, True)}{note_html}'
            f'{reason}{_cover_line(a)}{back}'
            f'</section>')


def _away_row(a: Dict[str, Any], today: date) -> str:
    """Someone else who is away: a name, the days, who covers. `a` has
    nothing else in it (view)."""
    held = " · waiting for your yes" if a.get("waiting") else ""
    cover = f'<span class="dt-cov">Covering: {_e(a["cover"])}</span>' if a.get("cover") else ""
    return (f'<div class="dt-row"><span class="t"><b>{_e(a["name"])}</b>'
            f'<small>{_e(_days(a["starts_on"], a["ends_on"], today))}{held}</small></span>{cover}</div>')


def _ask_form(v: Dict[str, Any], draft: Optional[Dict[str, Any]] = None) -> str:
    """The form. `draft` (step 2): what they just typed, on days that are
    full or protected. Nothing was sent: the form comes back as they left
    it, with what is in the way above the buttons, and Ask anyway."""
    from member_app_ui import icon
    today, to, n = v["today"].isoformat(), v.get("to") or "", int(v["notice_days"])
    if draft:
        return _ask_again(v, draft)
    if v["top"]:
        lede = "Nobody is over you here, so your time away goes straight on the calendar."
        send = "Put it on the calendar"
        reads = ("Private. Only those who look after the whole church with you can read this. Nobody else who sees "
                 "your dates can.")
    else:
        lede = (f"It goes to {to}, who says yes or not this one." if to
                else "It goes to whoever is over you, who says yes or not this one.")
        send = "Ask for these days"
        reads = (f"Private. {to or 'Whoever it goes to'} can read this, and so can those who look after the whole "
                 f"church. Nobody else who sees your dates can.")
    notice = (f'<p class="dt-hint">Planned time away works best with {n} days’ notice. Sooner is fine: it just says '
              f'short notice.</p>' if n > 0 and not v["top"] else "")
    opts = "".join(f'<option value="{_e(p["id"])}">{_e(p["name"])}</option>' for p in v["people"])
    return (f'<section class="ld-pr dt-card" aria-label="Ask for time off"><p class="dt-lede">{_e(lede)}</p>'
            f'<form class="dt-form" method="post" action="/my/lead/dates/ask"><div class="dt-two">'
            f'<label class="dt-f">First day<input type="date" name="start" required></label>'
            f'<label class="dt-f">Last day<input type="date" name="end" min="{today}"></label></div>'
            f'<fieldset class="ld-chips"><legend>What kind</legend>'
            f'<label><input type="radio" name="kind" value="time_off" checked><span>Time off</span></label>'
            f'<label><input type="radio" name="kind" value="commitment"><span>Another commitment</span></label>'
            f'</fieldset>'
            f'<label class="dt-f">Why, if you’d like to say<textarea class="ld-ta" name="reason" maxlength="500">'
            f'</textarea></label><p class="dt-hint">{icon("lock", 13)} {_e(reads)}</p>'
            f'<label class="dt-f">Who covers for you<select name="cover"><option value="">Nobody yet</option>{opts}'
            f'</select></label>'
            f'<label class="dt-f">Or type their name<input name="cover_name" maxlength="80" autocomplete="off"></label>'
            f'{notice}<button class="ld-btn" type="submit">{send}</button></form></section>')


def _ask_again(v: Dict[str, Any], d: Dict[str, Any]) -> str:
    """The ask form with what they typed still in it, and the look."""
    from member_app_ui import icon
    today, to = v["today"], v.get("to") or ""
    reads = (f"Private. {d.get('up') or to or 'Whoever it goes to'} can read this, and so can those who look after "
             f"the whole church. Nobody else who sees your dates can.")
    kind = d.get("kind") if d.get("kind") in PLANNED else "time_off"

    def on(k: str) -> str:
        return " checked" if kind == k else ""
    opts = "".join(f'<option value="{_e(p["id"])}"{" selected" if p["id"] == d.get("cover") else ""}>'
                   f'{_e(p["name"])}</option>' for p in v["people"])
    return (f'<section class="ld-pr dt-card" aria-label="Ask for time off">'
            f'<form class="dt-form" method="post" action="/my/lead/dates/ask"><div class="dt-two">'
            f'<label class="dt-f">First day<input type="date" name="start" value="{_e(d.get("start") or "")}" required>'
            f'</label><label class="dt-f">Last day<input type="date" name="end" value="{_e(d.get("end") or "")}" '
            f'min="{today.isoformat()}"></label></div>'
            f'{_look_block(d, today)}'
            f'<fieldset class="ld-chips"><legend>What kind</legend>'
            f'<label><input type="radio" name="kind" value="time_off"{on("time_off")}><span>Time off</span></label>'
            f'<label><input type="radio" name="kind" value="commitment"{on("commitment")}><span>Another commitment'
            f'</span></label></fieldset>'
            f'<label class="dt-f">Why, if you’d like to say<textarea class="ld-ta" name="reason" maxlength="500">'
            f'{_e(d.get("reason") or "")}</textarea></label><p class="dt-hint">{icon("lock", 13)} {_e(reads)}</p>'
            f'<label class="dt-f">Who covers for you<select name="cover"><option value="">Nobody yet</option>{opts}'
            f'</select></label>'
            f'<label class="dt-f">Or type their name<input name="cover_name" maxlength="80" autocomplete="off" '
            f'value="{_e(d.get("cover_name") or "")}"></label>'
            f'<div class="dt-acts"><button class="ld-btn" type="submit" name="sure" value="yes">Ask anyway</button>'
            f'<button class="ld-ghost" type="submit">I changed the days. Ask for those</button></div></form></section>')


def _cant_form(v: Dict[str, Any]) -> str:
    today, near = v["today"], int(v["near"])
    last = (today + timedelta(days=near - 1)).isoformat()
    told = f" {v['to']} is let know." if v.get("to") else ""
    return (f'<section class="ld-pr dt-card" aria-label="I can’t make it">'
            f'<p class="dt-lede">For the next {_e(_span(near))}: sick, or something came up. It goes straight on the '
            f'calendar and needs no yes.{_e(told)}</p>'
            f'<form class="dt-form" method="post" action="/my/lead/dates/cant"><div class="dt-two">'
            f'<label class="dt-f">The day<input type="date" name="start" value="{today.isoformat()}" '
            f'min="{today.isoformat()}" max="{last}" required></label>'
            f'<label class="dt-f">Last day, if more<input type="date" name="end" min="{today.isoformat()}">'
            f'</label></div>'
            f'<label class="dt-f">A private note, if you like<input name="reason" maxlength="500" autocomplete="off">'
            f'</label><button class="ld-ghost" type="submit">I can’t make it</button></form></section>')


def body(v: Optional[Dict[str, Any]], draft: Optional[Dict[str, Any]] = None) -> str:
    """The page's own part (inside the header and the switcher), in the
    order a phone reads it: Waiting for your yes, Ask for time off, I can't
    make it, My dates, Who else is away. `draft`: an ask not sent yet
    (_ask_form)."""
    from member_app_ui import icon
    from member_portal import band
    if v is None:
        return '<p class="mp-err" role="alert">Your dates couldn’t load just now. Please try again in a moment.</p>'
    today, tz = v["today"], v["tz"]
    chief = f'<div class="ld-chief"><small>{icon("star", 12)}From Chief</small><p>{_e(chief_line(v))}</p></div>'
    left = right = ""
    if v["waiting"]:
        left += ('<div class="dt-sec"><div class="mb-sh"><h2>Waiting for your yes</h2>'
                 f'<span>{len(v["waiting"])} waiting</span></div>'
                 + "".join(_wait_card(a, today, tz) for a in v["waiting"]) + '</div>')
    if v["on_it"]:
        left += ('<div class="dt-sec"><div class="mb-sh"><h2>Ask for time off</h2></div>' + _ask_form(v, draft)
                 + '</div>'
                 '<div class="dt-sec"><div class="mb-sh"><h2>I can’t make it</h2></div>' + _cant_form(v) + '</div>')
    mine = v["mine"]
    if v["on_it"] or mine:
        # Up top: what still waits, and every answer whose days haven't passed (a "not this one" too: they
        # were told to look here). Soonest first. The rest folds away under Earlier.
        now_ = sorted((a for a in mine if a["state"] == "asked"
                       or (a["state"] in ("yes", "no") and a["ends_on"] >= today.isoformat())),
                      key=lambda a: (a["state"] != "asked", a["starts_on"]))
        old = [a for a in mine if a not in now_]
        html_ = ('<div class="dt-sec"><div class="mb-sh"><h2>My dates</h2>'
                 f'<span>{sum(1 for a in mine if a["state"] == "asked")} waiting</span></div>')
        html_ += "".join(_mine_card(a, today, tz) for a in now_) if now_ else (
            '<p class="ld-quiet">Nothing coming up. When you ask to be away, it shows here.</p>')
        if old:
            html_ += (f'<details class="dt-old"><summary class="ld-ghost">Earlier · {len(old)}</summary>'
                      f'<div class="dt-list">{"".join(_mine_card(a, today, tz) for a in old)}</div></details>')
        right += html_ + '</div>'
    if v["on_it"]:
        rows = "".join(_away_row(a, today) for a in v["away"])
        right += ('<div class="dt-sec"><div class="mb-sh"><h2>Who else is away</h2><span>Next two months</span></div>'
                  + (f'<div class="dt-list">{rows}</div>' if rows else
                     '<p class="ld-quiet">Nobody else is away in the next two months.</p>') + '</div>')
        quiet = ("Everyone on the leaders schedule sees your days and who covers. Why you’re away stays between you, "
                 "whoever your ask goes to and those who look after the whole church.")
    elif not v["waiting"] and any(a.get("group") == "volunteers" for a in mine):
        # A volunteer who followed a link to their own (S2-5): theirs are on My serving too.
        quiet = "These are the away days you asked your team’s leader for. They’re on My serving too."
    else:
        quiet = ("You see only the asks that came to you. You aren’t on the leaders schedule yourself, so there’s "
                 "nothing to ask for here.")
    return (f'<div class="ld-tks dt-page">{chief}{band(left, right)}'
            f'<p class="ld-quiet">{icon("lock", 14)}<span>{_e(quiet)}</span></p></div>')


def _head(me: Dict[str, Any]) -> str:
    """The Lead tab's hello. No role names here: this page says nothing by
    title."""
    import member_portal_lead as mpl
    first = (me.get("name") or "").strip().split(" ")[0] or "friend"
    return f'<header class="ld-head"><h1 class="ld-hello">{mpl._word()}, <em>{_e(first)}</em></h1></header>'


def _flash(request: Request, v: Optional[Dict[str, Any]], err: str = "") -> str:
    """What the last press did, in plain words, from its short code. The
    name and the number are worked out here: nothing but the code rides in
    the address."""
    import member_portal_lead as mpl
    code = err or request.query_params.get("err") or ""
    bad = ERRORS.get(code) or mpl.ERRORS.get(code)
    if bad:
        bad = bad.replace("{n}", str(int((v or {}).get("near") or 14)))
        return f'<p class="mp-err mp-flash" role="alert">{_e(bad)}</p>'
    code = request.query_params.get("done") or ""
    if code in DONE_UP:
        up = (v or {}).get("up") or ""
        done = DONE_UP[code].replace("{up}", up) if up or "{up}" not in DONE_UP[code] else DONE_ALONE.get(code, "Done.")
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    done = DONE.get(code)
    if not done:
        return ""
    to = (v or {}).get("to") or ""
    done = done.replace("{to}", to) if to or "{to}" not in done else DONE_ALONE.get(code, "Done.")
    return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], v: Optional[Dict[str, Any]], seg: str,
           *, err: str = "", draft: Optional[Dict[str, Any]] = None) -> str:
    """/my/lead/dates. `draft`: an ask not sent yet, shown back in its form.
    The top of the page says so (nothing happened, so no other flash): the
    form may be below what waits for their yes."""
    import member_portal_lead as mpl
    from member_portal import _shell
    days_in_the_way = any(w.get("flag") != "pair" for w in (draft or {}).get("why") or [])
    flash = (f'<p class="mp-err mp-flash" role="alert">{_e(NOT_SENT if days_in_the_way else NOT_SENT_PAIR)}</p>'
             if draft else _flash(request, v, err))
    return _shell(biz, site, "Dates",
                  f'<style>{mpl.LEAD_CSS}{mpl.TASK_CSS}{DATES_CSS}</style><div class="ld-wide">'
                  f'{flash}{_head(me)}{seg}{body(v, draft)}</div>', tab="lead", who=me, wide=True)


def render_not_here(biz: Dict[str, Any], site, me: Dict[str, Any]) -> str:
    """For someone who followed a link here and has no Dates page: they are
    not on the leaders schedule and nothing waits for their yes."""
    import member_portal_lead as mpl
    from member_portal import _shell
    return _shell(biz, site, "Dates",
                  f'<style>{mpl.LEAD_CSS}</style><div class="ld-wide">{_head(me)}<section class="ld-card">'
                  f'<p>Dates is for the people on the leaders schedule, and nothing is waiting for your yes right '
                  f'now.</p><p><a href="/my">Back to Home</a></p></section></div>', tab="lead", who=me)


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], *, err: str = "",
                draft: Optional[Dict[str, Any]] = None):
    """GET /my/lead/dates: (html, status), or None when it is not a page at
    all (the switch is closed for the church, or its tables aren't there:
    the Lead tab answers as it does for any address it doesn't know).
    member_portal_lead.serve has already read church_schedule.section into
    DATES for this request. That answer is kept a minute, so it decides the
    switcher and never the page: the page reads fresh, and someone with
    nothing of theirs here (not on the schedule, nothing waiting for their
    yes, no asks of their own) gets a few plain words and a 404."""
    import church_follow_up as cfu
    import church_schedule as cs
    import church_shepherding as shep
    import group_lead
    import member_portal_lead as mpl
    entry = mpl.DATES.get() is not None
    if not entry and (not cfu.is_church(biz) or not await asyncio.to_thread(cs.on, biz)):
        return None
    cid = str(me["id"])
    my_roles = await asyncio.to_thread(cfu.roles_for, biz["id"], cid) or []
    active = [r for r in my_roles if r.get("status") == "active"]
    led = await asyncio.to_thread(group_lead.led_groups, biz["id"], cid) or []
    fams = 0
    if active:
        fv = await asyncio.to_thread(shep.my_families, biz["id"], cid)
        fams = len((fv or {}).get("families") or [])
    try:
        v: Optional[Dict[str, Any]] = await asyncio.to_thread(view, biz, cid)
    except HTTPException as e:
        logger.warning("lead dates read failed: %s", e.status_code)
        v = None
    if v is not None and not (v["on_it"] or v["waiting"] or v["mine"]):
        # Read fresh, there is nothing of theirs here: they followed a link (a notice, say).
        return render_not_here(biz, site, me), 404
    if v is not None:
        mpl.DATES.set({"waiting": len(v["waiting"])})       # on the page itself the count is what it just read
    seg = mpl._seg("dates", any(not mpl._is_prayer(r) for r in active), any(mpl._is_prayer(r) for r in active),
                   0, fams, len(led))
    if v is not None and not v["on_it"]:
        draft = None                                        # the form isn't theirs to see
    return render(biz, site, request, me, v, seg, err=err, draft=draft), 200 if v is not None else 503


# ─── POST ─────────────────────────────────────────────────────────────

def _go(**q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse(f"{HERE}?{qs}" if qs else HERE, status_code=303, headers=_SECURE_HEADERS)


def _code(e: HTTPException) -> str:
    """A refusal as a short code for the page (never its words in the
    address): the engine's 400, 403, 404, 409 and 503 each come back as
    plain words (ERRORS), never as a raw error."""
    import church_schedule as cs
    said, status = str(e.detail or ""), e.status_code
    if status == 400:
        if said == cs.BAD_DAYS:
            return "dt_days"
        if said.startswith(cs.CANT_FAR.split("{")[0]):
            return "dt_far"
        if said == cs.TOO_MANY:
            return "dt_many"
        if said.startswith("Someone else covers"):
            return "dt_cover"
        if said in (cs.NOT_PERSON, NOT_OFFERED):
            return "dt_cover_who"
        if said.startswith("Keep "):
            return "dt_long"
        return "dt_said"
    if status == 403:
        return {cs.NOT_ON: "dt_not_on", cs.NOT_TO_YOU: "dt_not_yours",
                cs.NOT_ASKER: "dt_not_asker"}.get(said, "dt_gone")
    if status == 404:
        return "dt_gone"
    if status == 409:
        if said.startswith(cs.FULL_NOW):                    # a yes that didn't land: the days ran into something new
            return "dt_yours" if said == cs.YOURS_NOW else "dt_up"
        if said.startswith(cs.NEEDS_NOW):                   # the same, a pair alone (never said to be one)
            return "dt_yours_now" if said == cs.YOURS_NEEDS else "dt_up_now"
        return {cs.WAITING: "dt_waiting", cs.ALREADY: "dt_already", cs.NO_YES: "dt_no_yes",
                cs.NOT_OPEN: "dt_closed"}.get(said, "dt_changed")
    return "error"


class _Look(Exception):
    """An ask on days that are full or protected, before it is sent: nothing
    was written, and the page is shown again with `draft` in its form."""

    def __init__(self, draft: Dict[str, Any]):
        super().__init__("look")
        self.draft = draft


async def _show(request: Request, church: Dict[str, Any], me: Dict[str, Any], draft: Dict[str, Any]):
    """The Dates page itself, as the answer to a press that sent nothing:
    what they typed is still in the form (it never rides in an address: a
    reason is private), with what is in the way. Never kept by a browser
    (member_portal's own headers)."""
    import member_portal_lead as mpl
    from member_portal import _SECURE_HEADERS
    biz = church["business"]
    await mpl._context(request, biz, me)
    out = await serve(request, biz, church.get("site"), me, draft=draft)
    if out is None:
        raise HTTPException(404, "Not found")
    return HTMLResponse(content=out[0], status_code=out[1], headers=_SECURE_HEADERS)


async def _act(request: Request, fn, ok: str):
    """A live session at this church, never the preview, the switch open
    and its tables there (a 404 otherwise), not too fast; then fn(biz, me,
    form) in a thread (it may answer with its own code); back to the page.
    fn may raise _Look instead: nothing was sent, and the page is shown."""
    import church_follow_up as cfu
    import church_schedule as cs
    import rate_limit
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _go(err="preview" if unavailable == "preview" else "error")
    if not me:
        return RedirectResponse("/my", status_code=303)
    biz = church["business"]
    if not cfu.is_church(biz) or not await asyncio.to_thread(cs.on, biz):
        raise HTTPException(404, "Not found")
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return _go(err="slow")
    form = await request.form()
    try:
        code = await asyncio.to_thread(fn, biz, me, form)
    except _Look as look:
        return await _show(request, church, me, look.draft)
    except HTTPException as e:
        if e.status_code >= 500:
            logger.warning("lead dates write failed: %s", e.status_code)
        return _go(err=_code(e))
    return _go(done=code or ok)


def _ask_id(ask_id: str) -> str:
    if not _ID.match(ask_id or ""):
        raise HTTPException(404, "Not found")
    return ask_id.lower()


def _cover(ch, me: Dict[str, str], form) -> Optional[str]:
    """Who covers, from the list: one of the people the page offered (on
    the leaders schedule at this church), never the one asking. Anyone else
    is typed as a name."""
    import church_schedule as cs
    raw = str(form.get("cover") or "").strip().lower()
    if not raw:
        return None
    if not _ID.match(raw):
        raise HTTPException(400, NOT_OFFERED)
    if raw == me["id"]:
        raise HTTPException(400, "Someone else covers, not the one who is away")
    if raw not in cs.roster(ch).people():
        raise HTTPException(400, NOT_OFFERED)
    return raw


def _send(biz: Dict[str, Any], me: Dict[str, Any], form, kind: str) -> Dict[str, Any]:
    import church_schedule as cs
    ch, who = _ch_me(biz, me)
    if who["id"] not in cs.roster(ch).people():
        raise HTTPException(403, cs.NOT_ON)
    planned = kind in PLANNED
    # "Can't make it" with no day named is today, on the church's own clock.
    start = form.get("start") or (None if planned else cs._today(ch).isoformat())
    return cs.ask(ch, who, {
        "starts_on": start, "ends_on": form.get("end") or start, "kind": kind,
        "reason": form.get("reason"), "cover_contact_id": _cover(ch, who, form) if planned else None,
        "cover_name": form.get("cover_name") if planned else None})


def _look(biz: Dict[str, Any], me: Dict[str, Any], form, kind: str) -> Optional[Dict[str, Any]]:
    """Before a planned ask is sent (step 2): would these days run into a
    full day or a protected one? READS ONLY. None when they wouldn't, or
    when the engine is going to answer with words of its own anyway (not on
    the schedule, days it can't take) or never looks (the one person the
    church's owner is). Otherwise what the page shows before anything is
    sent: what they typed, what is in the way, the nearest open days, and
    who can make an exception."""
    import church_schedule as cs
    import church_schedule_limits as csl
    ch, who = _ch_me(biz, me)
    cid = who["id"]
    first, last = cs._day(form.get("start")), cs._day(form.get("end") or form.get("start"))
    if not first or not last or last < first or (last - first).days > cs.MAX_DAYS or last < cs._today(ch):
        return None
    if cid not in cs.roster(ch).people() or (ch.owner_person and cid == ch.owner_person):
        return None
    dept = cs.department_of(ch, cid)
    got = csl.look(ch, cid, first, last, department_id=dept["id"] if dept else None)
    if not got["flags"]:
        return None
    return {"start": first.isoformat(), "end": last.isoformat(), "kind": kind,
            "reason": str(form.get("reason") or "")[:500], "cover": str(form.get("cover") or "").strip().lower(),
            "cover_name": str(form.get("cover_name") or "")[:80], "why": got["why"], "open": got["open"],
            "up": got["up"]["name"]}


@router.post("/my/lead/dates/ask", include_in_schema=False)
async def ask(request: Request):
    def go(biz, me, form):
        import church_schedule as cs
        kind = str(form.get("kind") or "time_off")
        if kind not in PLANNED:
            raise HTTPException(400, "Say what it is: time off, or another commitment")
        if cs.step2() and str(form.get("sure") or "") != "yes":
            draft = _look(biz, me, form, kind)
            if draft:
                raise _Look(draft)              # full or protected: shown first, nothing sent
        got = _send(biz, me, form, kind)
        if got["state"] == "yes":
            return "dt_set"                     # nobody is over them: it needed no yes
        if cs.flagged(got):
            return "dt_asked_up"                # it went up for an exception
        return "dt_asked_short" if "short_notice" in (got.get("flags") or []) else "dt_asked"
    return await _act(request, go, "dt_asked")


@router.post("/my/lead/dates/cant", include_in_schema=False)
async def cant(request: Request):
    def go(biz, me, form):
        _send(biz, me, form, "cant")
    return await _act(request, go, "dt_cant")


@router.post("/my/lead/dates/{ask_id}/answer", include_in_schema=False)
async def answer(ask_id: str, request: Request):
    def go(biz, me, form):
        import church_schedule as cs
        ch, who = _ch_me(biz, me)
        ans = str(form.get("ans") or "")
        if ans not in ("yes", "no"):
            raise HTTPException(400, "Say yes, or not this one")
        # The Yes carries what its card showed as being in the way: no exception is given unseen.
        shown = [f for f in str(form.get("shown") or "").split(",") if f]
        got = cs.answer(ch, who, _ask_id(ask_id), ans == "yes", form.get("note") if ans == "no" else None,
                        shown=shown)
        if ans == "yes" and got.get("excepted"):
            return "dt_yes_x"                   # a yes over a flag: an exception
        return "dt_yes" if ans == "yes" else "dt_no"
    return await _act(request, go, "dt_yes")


@router.post("/my/lead/dates/{ask_id}/withdraw", include_in_schema=False)
async def withdraw(ask_id: str, request: Request):
    def go(biz, me, form):
        import church_schedule as cs
        ch, who = _ch_me(biz, me)
        cs.withdraw(ch, who, _ask_id(ask_id))
    return await _act(request, go, "dt_back")
