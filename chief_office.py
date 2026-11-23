"""chief_office.py — Chief knows the whole office, and whoever is over its lanes
runs the team through Chief.

Kevin, 2026-11-17: "make sure the chief is aware of everyones duties and job
description responsibility and also make sure Jessica has ability to request
things from chief in regards to admins etc like I would as well".

    THE OFFICE ............ one line for each office login (the owner, every
                            Admin, every Manager seat): name, title, seat and
                            lane, who they answer to, whom they are over, the
                            duties they do of their own by label (a money duty
                            by its label only, never a figure), and the first
                            line of their written job description, or that none
                            is written yet. Read with church_over's and
                            church_job_descriptions' own readers, the ones
                            job_of and whose_job use, so the three agree. The
                            same text for everyone on the church's team, so it
                            sits in the per-business cached segment, after the
                            church's menu (chief_prompt). Kept ROSTER_SECONDS a
                            replica, dropped when a duty moves here
                            (church_duties._forget). Shown to the owner, the
                            Admins and the Managers (shown()), never a Member or
                            a Viewer. A church whose duties are off has none.
                            Beside each duty, where it is done (place()). It
                            ends with the one rule for "whose job is this?"
    place() ............... a duty's place on the church's menu, in the menu's
                            words ("Office › Building › Rooms & spaces → Ask
                            for a room"): its page is the one My week opens
                            for it (church_my_week.DOOR), named by the map
                            the frontend exports (church_findway), never typed
                            here. INSIDE names the button a duty's work starts
                            from, ALSO a second page; each is a page key, and
                            each button is one a Help Center answer on that
                            page names (test_chief_office_howto checks both).
                            THROUGH_CHIEF: work no page has
    team_week ............. mid-turn read: the office team's week, as the Office
                            team page shows it (church_team_week.team), for
                            whoever is over the lanes, the owner and the admins,
                            behind the page's own gates
    monthly_report_draft .. mid-turn read: the monthly report's draft by lane
                            (church_monthly_report.build), for whoever gathers
                            it, the owner and the admins, behind the page's own
                            gate (_access). Sending stays on its page

Whose words go in THE OFFICE: a written title and the first line of a written
job description only when the owner wrote them in the owner's own words
(church_job_descriptions.mine for the owner: not pasted in, not from a
document) and nothing in them is shaped like an instruction, fenced either way.
The owner's words already bind every login (their standing instructions ride
in every login's prompt). Anyone else's written words are only job_of's to
read, and that read marks the turn (chief_church_jobs). So the roster never
brings another login's words into the prompt, and never needs to raise the
taint by being there. The monthly report's notes are someone's words: the read
fences them and raises the turn's taint, as job_of does.

CHIEF_BRIEF=lean shortens the manual, not the church's data: the roster is the
same either way.

THE CHURCH'S OWN JOB (2026-11-22). Kevin: "any person that we add in, it seems
like Chief doesn't get the information about the church, the role,
responsibilities". A church that makes its own jobs (church_job_defs: every
church but the one whose office the five starting jobs were written from)
gives a login a job by its sheet: "Treasurer", with a line of what it does.
None of that reached Chief: a job of the church's own is not a lane, so the
roster called its holder "Admin" or "Office" and said nothing of the job.

    the job in the roster . a login on one of the church's own jobs is titled
                            by that job (own_job), and, where the owner wrote
                            the job, what the church says it does
    WHO YOU ARE TALKING     card_for(): one block in the turn's tail for every
    WITH                    church login that isn't the owner's, an Admin's and
                            a Member's too: their level, their job and what it
                            does, their written description's first line, who
                            they answer to and are over, where they work, an
                            Admin's own duties, whether Giving & money is open
                            to them, and what to answer "what's my job" from.
                            Read from the same engines as the roster and the
                            sheet, kept CARD_SECONDS a replica

Whose words, the same rule: a job's title is a name, fenced and in quotes (one
instruction-shaped word anywhere in the job and none of its words are shown).
What a job DOES reaches the prompt only when the owner made the job and nobody
else has ever saved it (own_job: the owner re-saving a job someone else wrote,
or removing it, never makes its words the owner's). A written description, as
before, only in the owner's own words. Everyone else's stay behind
list_church_jobs and job_of, which mark the turn. The card is built off the
turn's task (a thread), so it can never raise the turn's taint: nothing on it
may need to.

The card reads nothing the roster didn't: build() keeps each office login's
facts (who they answer to, their own duties, their job, their description's
first line) beside the roster's text, and the card is those facts plus this
turn's scope. A Member or a Viewer, who is shown no roster, gets a short card
from their own seat alone.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

ROSTER_SECONDS = 120        # a replica keeps a church's roster this long (a duty moved here drops it at once)
FAILED_SECONDS = 30         # an empty or failed roster is asked again this soon
OFFICE_MAX = 12             # office logins named; the rest are counted
LABELS_MAX = 16             # duty labels a person; the rest are counted
LINE_MAX = 150              # characters of a written job description's first line
ROSTER_MAX_CHARS = 6000     # past this the descriptions go, then the labels shorten
CARD_SECONDS = 60           # a replica keeps one login's card this long (a duty moved here drops it at once)
CARD_DUTIES_MAX = 10        # an Admin's own duties named on their card; the rest are counted
# A job whose words say it handles the church's money. Only for one sentence on the card: a login on
# such a job with Giving & money shut is told the owner opens it, never to "ask the treasurer".
_MONEY_JOB = re.compile(r"\b(treasur|financ|bookkeep|book-keep|accountant|the books|count(?:er|ing)\b|"
                        r"giving|tith|offering|deposit|stewardship|payroll)", re.I)
SHOWN_TO = ("owner", "admin", "manager")
TEAM_NAV = {"tab": "operate", "sub": "team"}
REPORT_NAV = {"tab": "operate", "sub": "monthly-report"}
RESULT_MAX = 11_000         # the tool loop's cap for these two is 12,000

_CACHE: Dict[str, Tuple[float, str]] = {}
# Each office login's facts, kept with its church's roster (build() writes both): the card's source.
_FACTS: Dict[str, Dict[str, Dict[str, Any]]] = {}
_CARDS: Dict[Tuple[str, str, str], Tuple[float, str]] = {}
# One roster is built at a time a process: a turn's roster and its card ask together, and the second
# waits for the first instead of reading the whole office again.
_BUILDING = threading.Lock()

# ─── Where each duty is done ──────────────────────────────────────────
# Kevin, 2026-11-18: "make sure that chief is aware of how to do each thing
# with each person … I just asked and chief said yes but then said no to
# certain parts". Chief had the menu's pages but not which page each duty is
# done on, nor the button inside it, so it said it had no confirmed path.
#
# The button a duty's work starts from inside its page (church_my_week.DOOR),
# when the page holds more than that duty: each is named, as written, by one
# of the Help Center's answers on that page (church_findway.json).
INSIDE: Dict[str, str] = {
    "weekly_text": "Announcement",
    "leaders_note": "Text it too",
    "rooms": "Waiting for a yes",
    "first_guests": "Hand to",
    "events": "Roles",
    "serve_schedule": "Ask",
    "announcements": "Waiting for you",
    "oversee_lanes": "One-on-one",
    "monthly_report": "Send to the pastor",
}
# A second page a duty's work is on, by page key, with its button (or "").
ALSO: Dict[str, List[Tuple[str, str]]] = {
    "first_guests": [("operate:sms", "New here")],
    "events": [("operate:spaces", "Ask for a room")],
    "outreach_nights": [("operate:spaces", "Ask for a room")],
}
# Work a duty holds that no page has: done by asking Chief.
THROUGH_CHIEF: Dict[str, str] = {
    "church_email": "addresses are given out through Chief",
}


def _plain(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _cut(text: str, most: int) -> str:
    return text if len(text) <= most else text[:most - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _fail(atype: str, msg: str, nav: Dict[str, str]) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": nav}


def _at(key: str, button: str = "") -> Optional[str]:
    import church_findway
    page = church_findway.page(key)
    if not page:
        return None
    return page["where"] + (f" → {button}" if button else "")


def place(duty: str, business: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Where a duty is done, in the menu's words: its page, the button its
    work starts from, and any second page ("Sunday › Plan and look back ›
    Services & Events → Roles; also Office › Building › Rooms & spaces → Ask
    for a room"); work through Chief is said so. None when its page isn't on
    the map (test_chief_office_howto fails then). With `business`, First-time
    guests at a church whose Welcome Path is on is Visitor flow (My week's
    own door, church_my_week.door_of), where every guest's call is worked."""
    import church_my_week as mw
    door = mw.door_of(duty, business) if business else mw.DOOR.get(duty)
    inside = INSIDE.get(duty, "") if door == mw.DOOR.get(duty) else ""
    first = _at(f"{door['area']}:{door['id']}", inside) if door else None
    if not first:
        return None
    rest = ["also " + r for r in (_at(k, b) for k, b in ALSO.get(duty, [])) if r]
    if THROUGH_CHIEF.get(duty):
        rest.append(THROUGH_CHIEF[duty])
    return "; ".join([first, *rest])


def _labelled(key: str, paths: bool, business: Optional[Dict[str, Any]] = None) -> str:
    import church_duties as cd
    label = cd.CATALOG[key]["label"]
    where = place(key, business) if paths else None
    return f"{label} ({where})" if where else label


# ─── THE OFFICE ───────────────────────────────────────────────────────

def forget(business_id: Any = None) -> None:
    """Drop the kept rosters, facts and cards (one church's, or every one)."""
    for k in [k for k in _CACHE if business_id is None or k == str(business_id)]:
        _CACHE.pop(k, None)
        _FACTS.pop(k, None)
    for k in [k for k in _CARDS if business_id is None or k[0] == str(business_id)]:
        _CARDS.pop(k, None)


def text_for(business: Optional[Dict[str, Any]]) -> str:
    """THE OFFICE for this church; '' for any other business, a church whose
    duties are off, and when it can't be read (said in the log). Never
    raises: a roster that fails leaves it out, never the turn."""
    try:
        import church_follow_up as cfu
        if not isinstance(business, dict) or not business.get("id") or not cfu.is_church(business):
            return ""
        bid = str(business["id"])

        def kept() -> Optional[str]:
            hit = _CACHE.get(bid)
            if hit and time.monotonic() - hit[0] < (ROSTER_SECONDS if hit[1] else FAILED_SECONDS):
                return hit[1]
            return None

        text = kept()
        if text is not None:
            return text
        with _BUILDING:
            text = kept()                   # built while this one waited
            if text is not None:
                return text
            try:
                text = build(business)
            except Exception as e:  # noqa: BLE001 — a read that fails leaves the roster out
                print(f"[chief_office] the office roster wasn't read ({bid[:8]}): {type(e).__name__}", flush=True)
                text = ""
                _FACTS.pop(bid, None)
            _CACHE[bid] = (time.monotonic(), text)
            return text
    except Exception as e:  # noqa: BLE001
        print(f"[chief_office] the office roster failed: {type(e).__name__}", flush=True)
        return ""


def shown(text: str, who: Optional[Dict[str, Any]]) -> str:
    """The roster for this turn's speaker: the owner (no `who`), an Admin or a
    Manager seat. A Member or a Viewer doesn't read everyone's jobs
    (church_job_descriptions.READ_ALL)."""
    if not text:
        return ""
    role = "owner" if who is None else str(who.get("role") or "")
    return text if role in SHOWN_TO else ""


def _shaped(*texts: Any) -> bool:
    """Whether any of these is shaped like an instruction to Chief, or carries an action tag."""
    import untrusted_text as ut
    for t in texts:
        if t and (ut.detect_injection(t) or ut.strip_action_tags(t)[1]):
            return True
    return False


def _heading(line: str) -> bool:
    return line.endswith(":") or (len(line.split()) <= 6 and not re.search(r"[.!?…”\"]$", line))


def first_line(text: Any) -> str:
    """A written job description's first sentence: past its headings
    ("Summary", "What they own"), LINE_MAX at most."""
    for para in re.split(r"\n\s*\n", str(text or "").replace("\r\n", "\n")):
        lines = [_plain(ln) for ln in para.split("\n") if _plain(ln)]
        lines = [ln for ln in lines if not _heading(ln)]
        if lines:
            joined = " ".join(lines)
            m = re.match(r"(.+?[.!?])(?:\s|$)", joined)
            return _cut(m.group(1) if m else joined, LINE_MAX)
    return ""


_CHANGES_READ = 1000


def _job_changers(ch: Any) -> Optional[Dict[str, set]]:
    """Each of the church's own jobs → every login the record says changed
    it (church_sheet_changes). None when the record couldn't be read: then
    nobody's words are known to be the owner's."""
    def read() -> Optional[Dict[str, set]]:
        import church_job_defs as cj
        import sb_clients
        from urllib.parse import quote
        try:
            rows = sb_clients.sb_get_as_service(
                f"/{cj.LOG}?business_id=eq.{quote(str(ch.b), safe='')}&job_key=not.is.null"
                f"&select=job_key,changed_by&limit={_CHANGES_READ}")
        except Exception:  # noqa: BLE001
            return None
        # A full page may be a cut one (the database returns 1,000 rows at most): then it isn't the whole record.
        if not isinstance(rows, list) or len(rows) >= _CHANGES_READ:
            return None
        out: Dict[str, set] = {}
        for r in rows:
            if r.get("job_key"):
                out.setdefault(str(r["job_key"]), set()).add(str(r.get("changed_by") or ""))
        return out
    return ch._got("own_job_changers", read)


def _owners_words(ch: Any, job: Dict[str, Any]) -> bool:
    """Whether everything written on this job is the owner's own. The row
    keeps only who made it and who saved it last, and a save stamps the
    saver whatever they changed: the owner changing a job's areas, or
    removing it, must not turn the words someone else wrote into the
    owner's. So: the owner made it, the owner saved it last, it is still
    there, and the record of changes names nobody else for it. A record
    that can't be read is a no."""
    owner = str(ch.owner or "")
    if not owner or job.get("gone") or job.get("maker") != owner or job.get("writer") != owner:
        return False
    changers = _job_changers(ch)
    return changers is not None and changers.get(str(job.get("key")), set()) <= {owner}


def own_job(ch: Any, uid: str) -> Optional[Dict[str, Any]]:
    """The church's own job this login was given on its sheet (its stored job
    isn't one of the starting jobs), ready for the prompt:
      label ...... its title, fenced; '' when anything on the job is shaped
                   like an instruction (then none of its words are shown)
      does ....... what the church says it does, fenced, only in the owner's
                   own words (_owners_words)
      does_kept .. a line exists that isn't shown here
      gone ....... the job was removed from the list (the login keeps it)
      money ...... its words say it handles the church's money
      unread ..... the login has one, but the jobs couldn't be read just now
    None for a starting job or no job."""
    import church_duties as cd
    import church_job_defs as cj
    import church_map_asks as cma
    seat = ch.seats.get(uid) or {}
    if not cd.own_job_seat(seat):
        return None
    rows = ch._got("own_job_rows", lambda: cj._rows(ch.b))
    job = cj.own_with_writer(ch.b, seat.get("lane"), rows) if rows is not None else None
    if not job:
        return {"label": "", "does": "", "does_kept": False, "gone": False, "money": False, "unread": True}
    does = _plain(job.get("does"))
    # One instruction-shaped word anywhere in the job and none of its words are shown, the title too.
    odd = _shaped(job["label"], does)
    label = "" if odd else cma.fence(job["label"])
    shown = cma.fence(does).rstrip(".") if does and not odd and _owners_words(ch, job) else ""
    return {"label": label, "does": shown, "does_kept": bool(does) and not shown, "gone": job["gone"],
            "money": bool(not odd and _MONEY_JOB.search(f"{job['label']} {does}")), "unread": False}


def _name(v: Any) -> str:
    """A name for the prompt: fenced, and '' when it is shaped like an instruction."""
    import church_map_asks as cma
    v = _plain(v)
    return "" if not v or _shaped(v) else cma.fence(v)


def _fact(ch: Any, e: Dict[str, Any], overseers: set, jobs_on: bool) -> Dict[str, Any]:
    """What the roster knows of one office login, read once: the roster's
    line and that login's card are both written from it."""
    import church_duties as cd
    import church_job_descriptions as cjd
    import church_map_asks as cma
    import church_over as co
    uid, seat = e["user_id"], e["seat"]
    row = e["row"] if jobs_on else None
    trusted = bool(row) and cjd.mine(row, ch.owner) and not _shaped(row.get("title"), row.get("description"))
    office = seat in ("admin", "manager")
    up, team = [], None
    if seat != "owner":
        up = [o["name"] for o in co.above(ch, e["who"])]
        if uid in overseers:
            team = [r["name"] for r in co.under(ch, co.who(co.LOGIN, uid)) if r["kind"] == co.LOGIN]
    return {
        "seat": seat, "name": e.get("name") or ch.login_name(uid),
        # One of the church's own jobs is not a lane: without this its holder read as "Admin" or "Office".
        "job": own_job(ch, uid) if office else None,
        "lanes": [cd.lane_label(k) for k in (ch.lanes(uid) if office else [])],
        "roles": [r["title"] for r in e["roles"] if not r.get("asked")],
        "up": up, "team": team, "own": list(e["own"]), "covers": bool(e["covers"]),
        "written": bool(row),
        "title": cma.fence(row["title"]) if trusted and _plain(row.get("title")) else "",
        "first": cma.fence(first_line(row.get("description"))).rstrip(".") if trusted else "",
        "jobs_on": jobs_on,
    }


def _order(ch: Any, uid: str, overseers: set) -> Tuple[int, int, str]:
    import church_duties as cd
    role = ch.role(uid)
    lanes = ch.lanes(uid)
    rank = 0 if uid in overseers else (1 if role == "admin" else 2)
    lane = min((cd.LANE_KEYS.index(k) for k in lanes if k in cd.LANE_KEYS), default=99)
    return rank, lane, ch.login_name(uid).casefold()


def _person_line(ch: Any, J: Any, e: Dict[str, Any], *, overseers: set, jobs_on: bool, words: bool,
                 labels_max: int, paths: bool = True, fact: Optional[Dict[str, Any]] = None) -> str:
    import church_job_descriptions as cjd
    f = fact if fact is not None else _fact(ch, e, overseers, jobs_on)
    uid, seat = e["user_id"], e["seat"]
    job = f["job"] if f["job"] and f["job"]["label"] else None
    # A title the church's own office typed is someone's words: in quotes, so it never reads as a seat or a lane.
    title = f["title"] or (f"“{job['label']}”" if job else cjd.system_title(ch, e))
    seat_word = {"owner": "the owner", "admin": "Admin", "manager": "Manager"}.get(seat or "", "")
    if seat == "owner":
        head = f"- {ch.login_name(uid)}: " + ("the owner" if title == "The owner" else f"{title} (the owner)")
    else:
        tags = [seat_word] + [ln for ln in f["lanes"] if ln.casefold() != title.casefold()]
        head = f"- {e['name']}: {title} ({', '.join(t for t in tags if t)})"
    bits: List[str] = []
    if seat == "owner":
        bits.append("over everyone; does every duty, money ones too")
    else:
        if f["up"]:
            bits.append("answers to " + _join(f["up"]))
        if f["team"] is not None:
            bits.append("over the lanes: " + (_join(f["team"]) if f["team"] else "no Manager is under them yet"))
        if seat == "admin":
            bits.append("does every duty, money ones too")
    labels = [_labelled(k, paths, getattr(ch, "business", None)) for k in e["own"]]
    if labels:
        more = len(labels) - labels_max
        listed = "; ".join(labels[:labels_max]) + (f"; and {more} more" if more > 0 else "")
        bits.append(("their own: " if seat in ("owner", "admin") else "duties: ") + listed)
    elif seat == "manager" and not e["covers"]:
        bits.append("no office duties yet")
    if e["covers"]:
        bits.append("covers every lane's other duties, never money")
    if job:
        bits.append("a job this church made" + (f", which it says does: “{job['does']}”"
                                                 if words and job["does"] else ""))
    if jobs_on:
        if f["first"] and words:
            bits.append(f"job description: “{f['first']}”")
        elif f["written"]:
            bits.append("job description written (job_of reads it)")
        else:
            bits.append("no written job description yet")
    return head + ": " + "; ".join(bits) + "."


def _rule(jobs_on: bool, movers: List[str], paths: bool = True) -> str:
    where = ("Beside each duty is where it is done, the place in the menu's words and → the button its work starts "
             "from: confirmed, so give it as written when someone asks how or where, then the Help Center's steps. "
             if paths else
             # Past the cap: job_of says them a person at a time (list_duties too, while the office is small).
             "Where a duty is done: " + ("job_of says it beside each of a person's duties, and list_duties beside "
                                         "each duty (Done in:) while the office is small" if jobs_on else
                                         "list_duties says it beside each duty (Done in:)")
             + ", confirmed; then the Help Center's steps. ")
    if jobs_on:
        rule = ("Whose job is it, one rule: an office duty (the weekly text, the books…) → THE OFFICE, by name "
                "(list_duties for the lane-by-lane detail, and before move_duty); other work (the van, the fire "
                "extinguishers) or someone outside the office → whose_job; someone's whole job → job_of.")
    else:
        rule = ("Whose job is it: an office duty → THE OFFICE, by name (list_duties for the lane-by-lane detail); "
                "anything else, say you don't know and that the owner or an admin can say.")
    rule = where + rule
    who = "the owner or an admin" + (f", and {_join(movers)} for the Managers under them" if movers else "")
    rule += f" Who moves a duty: {who}."
    if jobs_on:
        rule += (" A one-on-one or the weekly huddle to get ready for (whoever is over the lanes, or the owner): "
                 "one_on_one for each person, then a tight fifteen-minute agenda from it alone: wins, stuck and how "
                 "long, late, next, this week's jobs not done. Nothing is recorded.")
    return rule


def build(business: Dict[str, Any]) -> str:
    """THE OFFICE, read now. '' for a church whose duties are off. A read
    that fails raises (text_for leaves the roster out)."""
    import church_duties as cd
    if not cd.church_open(business):
        return ""
    import church_job_descriptions as cjd
    import church_map
    import church_over as co
    ch = co.Church(business)
    with church_map.once():
        jobs_on = co.church_open(business) and cjd.ready() is True
        J = cjd.Jobs(ch)
        if not jobs_on:
            J._memo["rows"] = []          # descriptions are switched with assignments: closed, none is read
        overseers = {u for u in ch.office if ch.role(u) == "manager" and co.OVERSEE in ch.held(u)}
        office = sorted(ch.office, key=lambda u: _order(ch, u, overseers))
        people = ([ch.owner] if ch.owner else []) + office
        entries = [J.entry(None, u) for u in people[:OFFICE_MAX + (1 if ch.owner else 0)]]
        J.name(entries)
        facts = {e["user_id"]: _fact(ch, e, overseers, jobs_on) for e in entries}
        church = _plain(business.get("name")) or "this church"
        head = (f"THE OFFICE at {church}, from its own duties" + (" and job descriptions" if jobs_on else "")
                + " (the same for everyone on its team). The owner and every Admin do every duty, money ones too; "
                "money duties by label only.")
        movers = [ch.login_name(u) for u in office if u in overseers]
        tail = []
        if not office:
            # A church with nobody in its office yet (church_structure, the standard start).
            tail.append("Nobody but the owner has an office login yet. When the talk turns to who does what "
                        "at the church, offer once to set up the team (SETTING UP THE TEAM).")
        if len(people) > len(entries):
            tail.append(f"…and {len(people) - len(entries)} more office logins: list_duties names them all.")
        # Past the cap: the descriptions go, then the places, then the labels shorten.
        for words, labels_max, paths in ((True, LABELS_MAX, True), (False, LABELS_MAX, True),
                                         (False, LABELS_MAX, False), (False, 6, False)):
            lines = [_person_line(ch, J, e, overseers=overseers, jobs_on=jobs_on, words=words, labels_max=labels_max,
                                  paths=paths, fact=facts[e["user_id"]])
                     for e in entries]
            text = "\n".join([head, *lines, *tail, _rule(jobs_on, movers, paths)])
            if len(text) <= ROSTER_MAX_CHARS:
                break
        _FACTS[ch.b] = facts                # the cards are written from these (card_for)
        return text + "\n"


# ─── WHO YOU ARE TALKING WITH ─────────────────────────────────────────

LEVELS = {"admin": "an Admin", "manager": "a Manager", "member": "a Member", "viewer": "a Viewer"}
CARD_ASK = ("When they ask what their job is, what they are responsible for or what they can do here, answer from "
            "this record first, in the church's own words for their job, and never say you don't know their role. ")
CARD_MORE = {
    "office": "For more, look it up: my_work (their own work and how it is going), sheet_of who \"me\" (everything "
              "their login opens), job_of who \"me\" (their whole job description).",
    "other": "For more, look it up: sheet_of who \"me\" (everything their login opens).",
}


def _scope_mark(scope: Optional[Dict[str, Any]]) -> str:
    """What of this turn's scope the card says, as a key: a card kept for one
    scope is never read back for another (a giving tick just given, areas
    just changed)."""
    if scope is None:
        return "-"
    money = scope.get("money") or {}
    return "|".join([",".join(scope.get("areas") or []),
                     ",".join(f"{k}={money[k]}" for k in sorted(money)) if money else ""])


def card_for(business: Optional[Dict[str, Any]], user_id: Any, scope: Optional[Dict[str, Any]] = None) -> str:
    """WHO YOU ARE TALKING WITH for this login's turn; '' for the owner, any
    business that isn't a church, a login with no seat here, and when it
    can't be read (said in the log). Never raises: a card that fails leaves
    itself out, never the turn. `scope`: chief_areas' scope for this turn
    (its areas, and the giving tick when one is held)."""
    try:
        import church_follow_up as cfu
        uid = str(user_id or "")
        if (not isinstance(business, dict) or not business.get("id") or not uid
                or uid == str(business.get("owner_id") or "") or not cfu.is_church(business)):
            return ""
        key = (str(business["id"]), uid, _scope_mark(scope))
        hit = _CARDS.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < (CARD_SECONDS if hit[1] else FAILED_SECONDS):
            return hit[1]
        try:
            text = build_card(business, uid, scope)
        except Exception as e:  # noqa: BLE001 — a read that fails leaves the card out
            print(f"[chief_office] the talking-with card wasn't read ({key[0][:8]}): {type(e).__name__}", flush=True)
            text = ""
        if len(_CARDS) > 2000:
            _CARDS.clear()
        _CARDS[key] = (time.monotonic(), text)
        return text
    except Exception as e:  # noqa: BLE001
        print(f"[chief_office] the talking-with card failed: {type(e).__name__}", flush=True)
        return ""


def _money_line(ch: Any, uid: str, role: str, scope: Optional[Dict[str, Any]], money_job: bool) -> str:
    """Whether Giving & money is open to this login, and what to say when it isn't."""
    import church_keys
    if role == "admin":
        try:
            open_ = church_keys.is_open(ch.b, SimpleNamespace(id=uid), "giving_money")
        except Exception:  # noqa: BLE001 — couldn't tell: said as that
            open_ = None
        if open_ is None:
            return ("Giving & money: theirs as an Admin. Whether this church's Giving keeper has it locked for them "
                    "couldn't be checked just now: answer their money questions from the lookups, and pass on "
                    "what a lookup says if it is locked.")
        if open_ is False:
            return ("Giving & money: theirs as an Admin, but this church has a Giving keeper and it is locked for "
                    "them until the keeper gives a key (asked for in Areas; a yes opens it for an hour). What came "
                    "in, by fund and by day, still answers without the key (giving_summary).")
        return ("Giving & money: open to them as an Admin (giving, the service counts, bills, the books). Answer "
                "their money questions from the lookups, giving_summary first for what came in; never send them to "
                "someone else for it.")
    tick = (scope or {}).get("money")
    if tick:
        return (f"Giving & money: the owner gave this login giving at {str(tick.get('level') or 'see').title()}"
                + (", with who gave" if tick.get("who_gave") else ", without who gave")
                + (" and the bank" if tick.get("bank") else "")
                + ". Read what that opens with the giving lookups; their own gates decide the rest.")
    base = "Giving & money: not open to this login. Only the owner opens it, on a person's sheet in Logins & areas."
    if money_job:
        return (base + " Their job here is about the church's money, so when they ask about giving or money, say "
                "exactly that: it isn't switched on for their login yet, and the owner switches it on. Offer to "
                "write the owner a note asking for it. Never tell them to ask the treasurer or an admin: they may "
                "be the one who is meant to have it.")
    return base


def build_card(business: Dict[str, Any], uid: str, scope: Optional[Dict[str, Any]] = None) -> str:
    """The card, read now. '' for a login with no seat or the owner. A read
    that fails raises (card_for leaves the card out).

    An office login (an Admin or a Manager seat) is written from the facts
    the roster keeps (text_for builds them, or waits for the build in flight),
    so the card reads the office once, with the roster. A Member or a Viewer,
    and an office login at a church with no roster (its duties off), get the
    short card: their seat and their job alone, nobody else's name."""
    import church_areas
    import church_duties as cd
    import church_over as co
    ch = co.Church(business)
    role = ch.role(uid)
    if not role or role == "owner":
        return ""
    office = role in ("admin", "manager")
    fact = None
    if office and text_for(business):
        fact = (_FACTS.get(ch.b) or {}).get(uid)        # None past the roster's first twelve logins
    church = _plain(business.get("name")) or "this church"
    lines = [f"WHO YOU ARE TALKING WITH, from {church}'s own record of this login (their sheet in Logins & areas):"]

    # Their level and their job.
    job = fact["job"] if fact else own_job(ch, uid)
    if fact:
        lanes, roles = fact["lanes"], fact["roles"]
    else:
        try:
            lanes = [cd.lane_label(k) for k in ch.lanes(uid)] if office else []
        except HTTPException:
            lanes = []
        roles = []
    roles = [r for r in (_name(x) for x in roles[:3]) if r]
    name = _name(fact["name"] if fact else ch.login_name(uid))
    who = (name or "Someone whose name isn't on file") + f": {LEVELS.get(role, 'an office')} login."
    if job and job["label"]:
        who += (f" Their job here is “{job['label']}”, a job this church made"
                + (" (since removed from the list; they keep the title)." if job["gone"] else "."))
    elif job and job["unread"]:
        who += " Their job here is one this church made; it couldn't be read just now (sheet_of who \"me\" names it)."
    elif job:
        who += (" Their job here is one this church made; its words aren't read out here (sheet_of who \"me\" "
                "names it).")
    elif lanes:
        who += f" Their job here is {_join(lanes)}."
    elif roles:
        who += f" They hold the church's role of {_join(roles)}."
    elif office:
        who += (" No job is set on their sheet yet: say so if they ask what their job is, and that the owner or "
                "an Admin sets it there.")
    lines.append("- " + who)
    if job and job["does"]:
        lines.append(f"- What the church says that job does: “{job['does']}”.")
    elif job and job["does_kept"]:
        lines.append("- What that job does is written on the job itself: list_church_jobs reads it.")

    if fact:
        # Their written job description: the owner's words only, as THE OFFICE shows them.
        if fact["jobs_on"]:
            if fact["first"]:
                lines.append("- Their written job description" + (f", titled “{fact['title']}”," if fact["title"] else "")
                             + f" starts: “{fact['first']}”. job_of who \"me\" reads all of it.")
            elif fact["written"]:
                lines.append("- A job description is written for them: job_of who \"me\" reads it.")
            else:
                lines.append("- No job description is written for them yet.")
        # Who they answer to, and (whoever is over the lanes) the Managers under them: the roster's own.
        up = [n for n in (_name(x) for x in fact["up"][:3]) if n]
        team = [n for n in (_name(x) for x in (fact["team"] or [])[:8]) if n]
        if up or team:
            lines.append("- " + "; ".join(x for x in (("Answers to " + _join(up)) if up else "",
                                                      ("over the lanes: " + _join(team)) if team else "") if x) + ".")

    # Where they work: said only when it is known (an unread scope is never "nothing is closed").
    if role in church_areas.KEEPS_ALL:
        lines.append("- Works across the whole church: an Admin login is kept to no area.")
    elif scope is not None:
        areas = [(church_areas.AREAS.get(a) or {}).get("label") or a for a in scope.get("areas") or []]
        lines.append("- Works in: " + (_join(areas) if areas else "no area switched on yet (their own tasks, "
                                                               "notes and meetings only)") + ".")

    # An Admin's own duties (a Manager's, a Member's and a Viewer's ride in "Their jobs here").
    if role == "admin" and fact:
        own = [_labelled(k, True, business) for k in fact["own"]]
        if own:
            more = len(own) - CARD_DUTIES_MAX
            lines.append("- Theirs by name: " + "; ".join(own[:CARD_DUTIES_MAX])
                         + (f"; and {more} more" if more > 0 else "")
                         + ". As an Admin every other duty is open to them too.")
        else:
            lines.append("- No duty is theirs by name. As an Admin every duty is open to them: for whose job "
                         "something is, read THE OFFICE.")

    money_job = bool((job or {}).get("money")) or bool(_MONEY_JOB.search(" ".join(lanes + roles)))
    lines.append("- " + _money_line(ch, uid, role, scope, money_job))
    lines.append(CARD_ASK + CARD_MORE["office" if fact else "other"])
    return "\n".join(lines) + "\n"


# ─── The team's week and the monthly report, read for the office ──────

def _turn_user() -> str:
    from chief_duties import _turn_user as tu
    return tu()


def _email(uid: str) -> Optional[str]:
    """The signed-in person's email, for a switch in owner mode (chief_duties'
    per-process cache). None when it can't be read: unread is not a yes."""
    from chief_duties import _EMAILS
    if uid not in _EMAILS:
        try:
            import platform_suite
            _EMAILS[uid] = platform_suite._owner_email(uid) or ""
        except Exception:  # noqa: BLE001
            return None
    return _EMAILS[uid]


def _areas_open(uid: str) -> Optional[bool]:
    """Who sees what (CHURCH_AREAS) for this login, as the Office team page's
    gate (church_areas._gate). None when owner mode can't read who they are."""
    import church_areas
    m = church_areas.mode()
    if m == "on":
        return True
    if m != "owner":
        return False
    email = _email(uid)
    return None if email is None else church_areas.open_to(SimpleNamespace(email=email))


def _counts_words(page: Dict[str, Any]) -> str:
    c = page.get("counts") or {}
    bits = [f"{c.get('logins', 0)} Manager logins", f"{c.get('late_tasks', 0)} late tasks"]
    if "late_jobs" in c:
        bits.append(f"{c['late_jobs']} of this week's jobs late")
    if c.get("unread"):
        bits.append(f"{c['unread']} couldn't be read just now")
    return "; ".join(bits)


def _row_words(r: Dict[str, Any]) -> str:
    import church_team_week as ctw
    if not r.get("ok"):
        return (r["name"] + (f", {r['lane']}" if r.get("lane") else "") + "\n"
                + (r.get("error") or "Their week couldn't be read just now."))
    return ctw._line(r)


def team_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "team_week"
    if action.get("_unattended"):
        return _fail(atype, "the team's week is read only when someone at the church asks.", TEAM_NAV)
    uid = _turn_user()
    if not uid:
        return _fail(atype, "the team's week is for someone signed in to the church's office.", TEAM_NAV)
    import church_duties as cd
    import church_my_week as mw
    import church_team_week as ctw
    try:
        business = cd._business(business_id)
        if not cd._is_church(business):
            return _fail(atype, ctw.NOT_CHURCH + ".", TEAM_NAV)
        bid = str(business["id"])
        if not ctw.church_open(bid):
            return _fail(atype, "the Office team page isn't switched on at this church yet.", TEAM_NAV)
        on = _areas_open(uid)
        if on is None:
            return _fail(atype, "whether the Office team page is on couldn't be checked just now. Try again.",
                         TEAM_NAV)
        if not on:
            return _fail(atype, "the Office team page isn't switched on here yet.", TEAM_NAV)
        try:
            role = mw._role(business, uid)
        except HTTPException as e:
            if e.status_code == 404:
                return _fail(atype, "the team's week is for the church's office logins.", TEAM_NAV)
            raise
        if role not in SHOWN_TO:
            return _fail(atype, "the team's week is for whoever is over the office's lanes, the owner and the "
                                "admins.", TEAM_NAV)
        if not ctw.overseer(bid, SimpleNamespace(id=uid), role):
            return _fail(atype, cd.refusal(bid, ctw.OVERSEE), TEAM_NAV)
        areas = ctw.view_of(bid, uid, role)
        page = ctw.team(business, exclude=uid if role == "manager" else None, care=areas is None or ctw.CARE in areas)
    except HTTPException as e:
        return _fail(atype, _plain(e.detail), TEAM_NAV)
    lines = [f"The office team at {page['church']}, {page['week']['words']}: who's late on what and what's due this "
             f"week, as the Office team page shows it. No money. {_counts_words(page)}."]
    if not page.get("care"):
        lines.append("Follow-ups and prayer and care requests aren't counted here: they're People & care's, outside "
                     "this login's areas.")
    rows = page.get("team") or []
    if not rows:
        lines.append("No other Manager login is on the office yet.")
    shown_rows = 0
    for r in rows:
        said = _row_words(r)
        if sum(len(x) + 1 for x in lines) + len(said) > RESULT_MAX:
            break
        lines.append(said)
        shown_rows += 1
    if shown_rows < len(rows):
        lines.append(f"…and {len(rows) - shown_rows} more on the Office team page.")
    late = (page.get("counts") or {}).get("late_tasks", 0)
    return {"type": atype, "result": "\n\n".join(lines),
            "label": "The office team" + (f" · {late} late" if late else " · nothing late"),
            "nav": TEAM_NAV, "logins": len(rows),
            "note_for_chief": ("Say it by name, late first, from these lines only; offer what helps (open their "
                               "week, give_assignment, move_duty) and wait for a yes.")}


async def handle_team_week(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(team_sync, str((biz or {}).get("id") or ""), action or {})


_NOT_FOUND = {"Not Found": "the monthly report isn't switched on at this church yet.",
              "business not found": "the monthly report is for the church's owner, its admins and whoever gathers "
                                    "it."}


def report_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "monthly_report_draft"
    if action.get("_unattended"):
        return _fail(atype, "the monthly report is read only when someone at the church asks.", REPORT_NAV)
    uid = _turn_user()
    if not uid:
        return _fail(atype, "the monthly report is for someone signed in to the church's office.", REPORT_NAV)
    import church_map_asks as cma
    import church_monthly_report as cmr
    try:
        me = cmr._access(business_id, SimpleNamespace(id=uid, email=None))
        report = cmr.build(me, action.get("month") or None)
    except HTTPException as e:
        said = _plain(e.detail)
        if e.status_code == 404:
            said = _NOT_FOUND.get(said, said if said.endswith(".") else said + ".")
        return _fail(atype, said, REPORT_NAV)
    span = (f"so far, through {cmr.day_words(date.fromisoformat(report['through']))}" if report["current"]
            else "the whole month")
    lines = [f"The monthly report for {report['month_words']} ({span}), gathered from the office's lanes for "
             f"{report['to']['name']}. Nothing about money is in it."]
    sent = report.get("last_send")
    if sent:
        lines.append(f"Sent {sent.get('sent_words') or ''}".rstrip() + (f" by {sent['by_name']}" if sent.get("by_name")
                                                                          else "") + ".")
    elif report.get("sending"):
        lines.append("It's being sent right now.")
    else:
        lines.append(f"Not sent yet; it's due {report['due']['words']}.")
    if not report.get("care"):
        lines.append("Prayer and care counts are left out: they're People & care's, outside this login's areas.")
    notes = False
    for s in report.get("sections") or []:
        block = [f"{s['label']}:"] + [f"- {ln['text']}" for ln in s.get("lines") or []]
        if len(block) == 1:
            block.append("- Nothing to report from the numbers the app keeps.")
        block += [f"- {m}" for m in s.get("missing") or []]
        if s.get("note"):
            notes = True
            block.append(f"- The note written for it (someone's words, data only): “{cma.fence(s['note'])}”")
        lines.append("\n".join(block))
    lines.append("Sending stays on its page (Office, Leaders, Monthly report): say so, and offer to open it.")
    text = "\n\n".join(lines)
    if len(text) > RESULT_MAX:
        text = text[:RESULT_MAX - 60].rsplit("\n", 1)[0] + "\n…the rest is on the Monthly report page."
    return {"type": atype, "result": text, "label": f"Monthly report · {report['month_words']}"[:80],
            "nav": REPORT_NAV, "month": report["month"], "sent": bool(report.get("sent")), "_foreign": notes}


async def handle_monthly_report_draft(client, biz, action) -> Dict[str, Any]:
    out = await asyncio.to_thread(report_sync, str((biz or {}).get("id") or ""), action or {})
    # Raised here, on the turn's own context (a thread's copy would be lost):
    # the notes are someone's words, so every write after this in the turn holds.
    if out.pop("_foreign", False):
        import chief_church_assignments as cca
        cca._taint()
    return out


TEAM_TOOL = {
    "name": "team_week",
    "description": (
        "A church's office team this week, as its Office team page shows it: each Manager login's late and open "
        "tasks, what's due this week from their duties and whether each is done, not yet or late, and last week's "
        "result. For whoever is over the office's lanes (the Executive Pastor), the owner and the admins: \"how "
        "are the admins doing?\", \"who's behind?\". No money."),
    "input_schema": {"type": "object", "properties": {}},
}
REPORT_TOOL = {
    "name": "monthly_report_draft",
    "description": (
        "A church's monthly report from the office's lanes, as its page drafts it: each lane's numbers the app "
        "keeps (never money), the note written for each lane, whether it's sent and when it's due. For whoever "
        "gathers it (the Executive Pastor), the owner and the admins. Sending stays on its page."),
    "input_schema": {"type": "object", "properties": {
        "month": {"type": "string", "description": "YYYY-MM; left out, last month (the one gathered now)"}}},
}
TOOLS = [TEAM_TOOL, REPORT_TOOL]
HANDLERS = {"team_week": handle_team_week, "monthly_report_draft": handle_monthly_report_draft}
PROGRESS = {"team_week": "reading the team's week", "monthly_report_draft": "reading the monthly report"}
