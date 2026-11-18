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
"""
from __future__ import annotations

import asyncio
import re
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
SHOWN_TO = ("owner", "admin", "manager")
TEAM_NAV = {"tab": "operate", "sub": "team"}
REPORT_NAV = {"tab": "operate", "sub": "monthly-report"}
RESULT_MAX = 11_000         # the tool loop's cap for these two is 12,000

_CACHE: Dict[str, Tuple[float, str]] = {}

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


def place(duty: str) -> Optional[str]:
    """Where a duty is done, in the menu's words: its page, the button its
    work starts from, and any second page ("Sunday › Plan and look back ›
    Services & Events → Roles; also Office › Building › Rooms & spaces → Ask
    for a room"); work through Chief is said so. None when its page isn't on
    the map (test_chief_office_howto fails then)."""
    import church_my_week as mw
    door = mw.DOOR.get(duty)
    first = _at(f"{door['area']}:{door['id']}", INSIDE.get(duty, "")) if door else None
    if not first:
        return None
    rest = ["also " + r for r in (_at(k, b) for k, b in ALSO.get(duty, [])) if r]
    if THROUGH_CHIEF.get(duty):
        rest.append(THROUGH_CHIEF[duty])
    return "; ".join([first, *rest])


def _labelled(key: str, paths: bool) -> str:
    import church_duties as cd
    label = cd.CATALOG[key]["label"]
    where = place(key) if paths else None
    return f"{label} ({where})" if where else label


# ─── THE OFFICE ───────────────────────────────────────────────────────

def forget(business_id: Any = None) -> None:
    """Drop the kept rosters (one church's, or every one)."""
    for k in [k for k in _CACHE if business_id is None or k == str(business_id)]:
        _CACHE.pop(k, None)


def text_for(business: Optional[Dict[str, Any]]) -> str:
    """THE OFFICE for this church; '' for any other business, a church whose
    duties are off, and when it can't be read (said in the log). Never
    raises: a roster that fails leaves it out, never the turn."""
    try:
        import church_follow_up as cfu
        if not isinstance(business, dict) or not business.get("id") or not cfu.is_church(business):
            return ""
        bid = str(business["id"])
        hit = _CACHE.get(bid)
        now = time.monotonic()
        if hit and now - hit[0] < (ROSTER_SECONDS if hit[1] else FAILED_SECONDS):
            return hit[1]
        try:
            text = build(business)
        except Exception as e:  # noqa: BLE001 — a read that fails leaves the roster out
            print(f"[chief_office] the office roster wasn't read ({bid[:8]}): {type(e).__name__}", flush=True)
            text = ""
        _CACHE[bid] = (now, text)
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


def _order(ch: Any, uid: str, overseers: set) -> Tuple[int, int, str]:
    import church_duties as cd
    role = ch.role(uid)
    lanes = ch.lanes(uid)
    rank = 0 if uid in overseers else (1 if role == "admin" else 2)
    lane = min((cd.LANE_KEYS.index(k) for k in lanes if k in cd.LANE_KEYS), default=99)
    return rank, lane, ch.login_name(uid).casefold()


def _person_line(ch: Any, J: Any, e: Dict[str, Any], *, overseers: set, jobs_on: bool, words: bool,
                 labels_max: int, paths: bool = True) -> str:
    import church_duties as cd
    import church_job_descriptions as cjd
    import church_map_asks as cma
    import church_over as co
    uid, seat = e["user_id"], e["seat"]
    row = e["row"] if jobs_on else None
    trusted = bool(row) and cjd.mine(row, ch.owner) and not _shaped(row.get("title"), row.get("description"))
    title = cma.fence(row["title"]) if trusted and _plain(row.get("title")) else cjd.system_title(ch, e)
    seat_word = {"owner": "the owner", "admin": "Admin", "manager": "Manager"}.get(seat or "", "")
    lanes = [cd.lane_label(k) for k in (ch.lanes(uid) if seat in ("admin", "manager") else [])]
    if seat == "owner":
        head = f"- {ch.login_name(uid)}: " + ("the owner" if title == "The owner" else f"{title} (the owner)")
    else:
        tags = [seat_word] + [ln for ln in lanes if ln.casefold() != title.casefold()]
        head = f"- {e['name']}: {title} ({', '.join(t for t in tags if t)})"
    bits: List[str] = []
    if seat == "owner":
        bits.append("over everyone; does every duty, money ones too")
    else:
        up = [o["name"] for o in co.above(ch, e["who"])]
        if up:
            bits.append("answers to " + _join(up))
        if uid in overseers:
            team = [r["name"] for r in co.under(ch, co.who(co.LOGIN, uid)) if r["kind"] == co.LOGIN]
            bits.append("over the lanes: " + (_join(team) if team else "no Manager is under them yet"))
        if seat == "admin":
            bits.append("does every duty, money ones too")
    labels = [_labelled(k, paths) for k in e["own"]]
    if labels:
        more = len(labels) - labels_max
        listed = "; ".join(labels[:labels_max]) + (f"; and {more} more" if more > 0 else "")
        bits.append(("their own: " if seat in ("owner", "admin") else "duties: ") + listed)
    elif seat == "manager" and not e["covers"]:
        bits.append("no office duties yet")
    if e["covers"]:
        bits.append("covers every lane's other duties, never money")
    if jobs_on:
        if row and trusted and words and first_line(row.get("description")):
            bits.append(f"job description: “{cma.fence(first_line(row.get('description'))).rstrip('.')}”")
        elif row:
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
                                  paths=paths)
                     for e in entries]
            text = "\n".join([head, *lines, *tail, _rule(jobs_on, movers, paths)])
            if len(text) <= ROSTER_MAX_CHARS:
                break
        return text + "\n"


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
