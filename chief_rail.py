"""
chief_rail.py — the rail: a records question answered from the records.

Kevin, 2026-10-16: the AI is a library and Claude is the librarian. "Instead
of the librarian going to get the book, a layer two goes and helps layer one
get the book." Most of what Chief is asked about money and the calendar is a
lookup: "Did Maria pay?", "What do I have tomorrow?". Today every one of them
pays for a full Sonnet turn and often the paid answer check, and about a
third of the short ones came back walled ("I couldn't verify…") even though
the answer was sitting in one table.

The rail is a shelf of question shapes, each with one exact read and a fixed
way of saying the result. An answer is composed only of what the read
returned, and each sentence must pass the same free prover that lets Chief's
own sentences skip the paid check (chief_truth.fast_lane). An empty read
proves "nothing booked" by itself: the read is the whole list.

THIS IS PRACTICE MODE ONLY. The rail never answers anyone here. After Chief's
reply has gone out, it reads the same records fresh, writes the answer it
would have given, proves it, and compares it with what Chief said. One row
per question goes to chief_rail_practice; GET /platform/rail/stats (owner)
and scripts/rail_practice_report.py read them. A shelf earns live use only
by a long run of agreement (docs/CHIEF_RAIL.md). It never acts, never calls
a model, never caches an answer, and reads only a business the asking user
owns.

Shelves today: money (who owes, how much is owed, what is overdue, did a
client pay) and schedule (a day's sessions, the next session, a client's
next session). Anything else is declined, and the reason is counted.

Switch: CHIEF_RAIL=off stops it. Unset (the default) is practice.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends

logger = logging.getLogger(__name__)
router = APIRouter()

TABLE = "chief_rail_practice"
MONEY = "money"
SCHEDULE = "schedule"

# What the rail would leave to Chief rather than read out: past these it is
# a report, not a lookup. Chief's own snapshot stops at 40 open invoices.
MAX_OPEN_INVOICES = 39
MAX_CLIENT_LINES = 6
MAX_DAY_SESSIONS = 8
MAX_CLIENT_OPEN = 4


def mode() -> str:
    """practice (the default) or off."""
    v = (os.environ.get("CHIEF_RAIL") or "practice").strip().lower()
    return "off" if v in ("off", "0", "false", "no") else "practice"


# ─── The question ────────────────────────────────────────────────────

@dataclass
class Question:
    shelf: str                      # money | schedule
    form: str                       # who_owes | owed_total | overdue | did_pay |
                                    # client_balance | day | next | client_next
    name: Optional[str] = None      # as typed, lowercased
    day: Optional[str] = None       # today | tomorrow | monday … sunday


_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY = r"(?P<day>today|tomorrow|(?:on |this )?(?:%s))" % "|".join(_DAY_NAMES)
_NAME = r"(?P<name>[a-z][a-z'.-]*(?: [a-z][a-z'.-]*){0,2}?)"
_NOW = r"(?: right now| currently| at the moment| so far| still| today)?"
_WHATS = r"what(?:'s|s| is)"
_SESSION = r"(?:appointments?|sessions?|bookings?|clients?)"


def _rx(*parts: str) -> Tuple["re.Pattern[str]", ...]:
    """One whole-message pattern per phrasing (a group name can appear only
    once in a pattern, and most phrasings name the client or the day)."""
    return tuple(re.compile("^(?:" + p + ")$") for p in parts)


_FORMS: List[Tuple[str, str, Tuple["re.Pattern[str]", ...]]] = [
    (MONEY, "who_owes", _rx(
        r"(?:who|which (?:clients?|customers?|people))(?: still)? (?:owes?|has(?:n't| not) paid|"
        r"have(?:n't| not) paid|(?:is|are) behind on (?:payments?|paying)|"
        r"has (?:an? )?(?:open|unpaid|outstanding) (?:invoices?|balance))"
        r"(?: me| us)?(?: money| anything)?(?: yet)?" + _NOW)),
    (MONEY, "owed_total", _rx(
        r"how much (?:money )?(?:am i|are we) (?:still )?(?:owed|waiting on|waiting for)" + _NOW,
        r"how much (?:money )?(?:do|does) (?:my |our )?(?:clients?|customers?|people|everyone|everybody)"
        r" (?:still )?owe (?:me|us)" + _NOW,
        r"how much (?:money )?(?:is|do i have) (?:still )?(?:outstanding|unpaid|owed(?: to me)?|"
        r"in (?:unpaid|open|outstanding) invoices)" + _NOW,
        _WHATS + r" (?:my |our |the )?(?:total )?(?:outstanding|unpaid|owed)"
        r"(?: balance| amount| total| to me)?" + _NOW)),
    (MONEY, "overdue", _rx(
        r"(?:do i have |are there |is there |have i got )?(?:any )?overdue (?:invoices?|payments?|bills?)" + _NOW,
        r"(?:what|which)(?: invoices?)? (?:is|are) overdue" + _NOW,
        r"how many invoices (?:are|do i have) overdue" + _NOW,
        _WHATS + r" overdue" + _NOW,
        r"(?:is|are) (?:anything|anyone|anybody|any invoices?) overdue" + _NOW,
        r"(?:anything|anyone|anybody) overdue" + _NOW,
        r"who(?:'s|s| is| are) overdue" + _NOW)),
    (MONEY, "did_pay", _rx(
        r"(?:did|has|have) " + _NAME + r" (?:paid|pay)(?: (?:me|us))?"
        r"(?: (?:her|his|their|the|that|my) (?:invoice|bill|balance))?(?: yet| already| in full| up)?",
        r"is " + _NAME + r" (?:paid up|all paid|paid)",
        r"(?:did|has) " + _NAME + r" (?:make|made|send|sent) (?:a |her |his |their |the )?payment")),
    (MONEY, "client_balance", _rx(
        r"how much (?:does|do) " + _NAME + r" (?:still )?owe(?: me| us)?",
        r"does " + _NAME + r" (?:still )?owe (?:me|us)(?: anything| money)?",
        r"what does " + _NAME + r" (?:still )?owe(?: me| us)?")),
    (SCHEDULE, "day", _rx(
        _WHATS + r" (?:on )?(?:my |the )?(?:calendar|schedule|agenda|books)(?: look(?:ing)? like)?(?: for)? " + _DAY,
        r"what does (?:my |the )?(?:calendar|schedule|day) look like " + _DAY,
        r"what do i have(?: on (?:my|the) calendar| booked| scheduled| going on)? " + _DAY,
        r"(?:who|what) (?:am i seeing|is booked|is coming in|have i got)(?: on (?:my|the) calendar)? " + _DAY,
        r"(?:do i have|have i got|are there|is there|any)(?: any)? " + _SESSION +
        r"(?: booked| scheduled| on (?:my|the) calendar| coming in)?(?: for)? " + _DAY,
        r"how many " + _SESSION + r"(?: do i have| have i got| are there| are booked| am i seeing|"
        r" are on (?:my|the) calendar)?(?: for)? " + _DAY,
        r"what are (?:my |the )" + _SESSION + r"(?: for)? " + _DAY,
        r"(?:am i|are we) (?:busy|booked) " + _DAY)),
    (SCHEDULE, "next", _rx(
        r"(?:when|what|who)(?:'s|s| is) (?:my |the )?next (?:appointment|session|booking|client)",
        _WHATS + r" next on (?:my|the) (?:calendar|schedule)",
        r"when do i (?:see|have) (?:my )?next (?:appointment|session|booking|client)")),
    (SCHEDULE, "client_next", _rx(
        r"when(?:'s|s| is) " + _NAME + r" (?:next )?(?:appointment|session|booking)",
        r"when (?:am i|will i be|do i) (?:seeing|see) " + _NAME + r"(?: next| again)?",
        r"when (?:is|does) " + _NAME + r" (?:coming in|come in|booked|scheduled|"
        r"have (?:an? )?(?:appointment|session|booking))(?: next)?",
        r"(?:does|is) " + _NAME + r" (?:have an? (?:appointment|session|booking)|booked|scheduled)"
        r"(?: coming up| soon)?")),
]

# Words that are not a client's name. "Did she pay?" leans on the
# conversation; "did the smiths pay" names a household the rail can't pick.
_NOT_A_NAME = frozenset("""
she he they them her him it that this those these anyone anybody everyone everybody someone
somebody nobody no one client clients customer customers people i you we my me our the a an
invoice invoices everything anything all next last first my
""".split())

# The two shelves' subjects, for counting near misses: a money or calendar
# question asked in a shape the rail does not take yet.
_TOPIC = [
    (MONEY, re.compile(r"\b(?:paid|pay|pays|owe[sd]?|owing|unpaid|overdue|outstanding|invoices?|"
                       r"balance|deposits?)\b")),
    (SCHEDULE, re.compile(r"\b(?:appointments?|bookings?|booked|calendar|schedule|sessions?|"
                          r"today|tomorrow|tonight|this week|next week|(?:%s))\b" % "|".join(_DAY_NAMES))),
]


def read_question(message: str) -> Tuple[Optional[Question], str, Optional[str]]:
    """(question, '', shelf) when a shelf takes it whole; otherwise
    (None, why not, the shelf it was about or None). Pure."""
    import model_router
    raw = str(message or "").strip()
    if not raw or len(raw) > 160 or "\n" in raw:
        return None, "not_a_lookup", None
    t = model_router.normalize(raw).rstrip(" .")
    t = re.sub(r"^(?:and|so|also|ok|okay) ", "", t)
    for shelf, form, phrasings in _FORMS:
        m = next((m for m in (rx.match(t) for rx in phrasings) if m), None)
        if not m:
            continue
        g = m.groupdict()
        name = (g.get("name") or "").strip() or None
        if name:
            name = re.sub(r"'s$", "", name)
            if set(name.split()) & _NOT_A_NAME:
                return None, "not_a_name", shelf
        day = (g.get("day") or "").replace("on ", "").replace("this ", "").strip() or None
        return Question(shelf, form, name=name, day=day), "", shelf
    for shelf, rx in _TOPIC:
        if rx.search(t):
            return None, "phrasing", shelf
    return None, "no_shelf", None


# ─── Saying it ───────────────────────────────────────────────────────

def _money(v: float) -> str:
    return f"${v:,.2f}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _md(d: date) -> str:
    return f"{d:%b} {d.day}"


def _clock(at: datetime) -> str:
    h = at.hour % 12 or 12
    return f"{h}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"


def _when(at: datetime) -> str:
    return f"{at:%A}, {_md(at.date())} at {_clock(at)}"


def _instant(v: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


@dataclass
class Answer:
    text: str
    sources: Dict[str, Dict[str, Any]]
    facts: Dict[str, Any]
    empty: bool = False             # nothing to report: the read itself is the proof


@dataclass
class Records:
    """What the rail read for one question. `complete` = the read returned
    every matching row (it came back under its limit)."""
    ok: bool = True
    why: str = ""
    complete: bool = True
    open_invoices: List[Dict[str, Any]] = field(default_factory=list)   # Chief's row shape
    paid_invoices: List[Dict[str, Any]] = field(default_factory=list)
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    contact: Optional[Dict[str, Any]] = None
    window: str = ""                # what the session read covered, in words
    label: str = ""                 # "tomorrow" / "on Friday, Oct 17"
    day_iso: str = ""


def _open_sources(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The open invoices exactly as Chief's answer check sees them
    (evidence_for_review): the rows, and the totals Chief computes from
    them. The rail's own sums must agree with Chief's for a sentence to
    prove, so the proof checks two computations against each other."""
    import chief_of_staff as chief
    if not rows:
        return {}
    return {
        "context:open_invoices": {"kind": "context", "complete": True,
                                  "text": json.dumps(rows, default=str, ensure_ascii=False)},
        "context:invoice_summary": {"kind": "context", "complete": True,
                                    "text": json.dumps(chief._invoice_summary_lines(rows),
                                                       ensure_ascii=False)},
    }


def _sent(rows):
    return [r for r in rows if (r.get("status") or "draft") != "draft"]


def _by_client(rows):
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        c = out.setdefault(r.get("client") or "", {"owed": 0.0, "n": 0, "over": 0.0, "n_over": 0})
        c["owed"] += float(r.get("total") or 0)
        c["n"] += 1
        if (r.get("days_overdue") or 0) > 0:
            c["over"] += float(r.get("total") or 0)
            c["n_over"] += 1
    return sorted(out.items(), key=lambda kv: (-kv[1]["owed"], kv[0]))


def _known_amounts(rows: List[Dict[str, Any]], paid: List[Dict[str, Any]]) -> List[str]:
    """Every amount the records hold: each invoice, each client's sums, the
    totals. A figure Chief says that is not one of these came from nowhere."""
    vals = set()
    sent = _sent(rows)
    for r in list(rows) + list(paid):
        vals.add(float(r.get("total") or 0))
    for _, c in _by_client(sent):
        vals.update((c["owed"], c["over"]))
    over = [r for r in sent if (r.get("days_overdue") or 0) > 0]
    drafts = [r for r in rows if (r.get("status") or "draft") == "draft"]
    for group in (sent, over, drafts, rows):
        vals.add(sum(float(r.get("total") or 0) for r in group))
    return sorted(_cents(v) for v in vals)


def _cents(v: Any) -> str:
    try:
        return str(Decimal(str(v)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return ""


def _owe_line(name: str, r: Dict[str, Any]) -> str:
    num = r.get("number")
    on = f"on invoice {num}" if num and num != "(no number)" else "on an invoice"
    line = f"{name} owes {_money(float(r.get('total') or 0))} {on}"
    due = _day(r.get("due_date"))
    if due:
        line += f", due {_md(due)}"
    if (r.get("days_overdue") or 0) > 0:
        line += f", {_plural(int(r['days_overdue']), 'day')} overdue"
    return line + "."


def compose(q: Question, rec: Records, tz) -> Tuple[Optional[Answer], str]:
    """(the rail's answer from what it read, '') or (None, why the shelf
    would leave this one to Chief: too long, an unnamed client). Pure."""
    try:
        if q.shelf == MONEY:
            return _compose_money(q, rec, tz), ""
        return _compose_schedule(q, rec, tz), ""
    except _Leave as e:
        return None, str(e)


class _Leave(Exception):
    """This one is Chief's: the reason is the decline reason."""


def _compose_money(q: Question, rec: Records, tz) -> Optional[Answer]:
    rows = rec.open_invoices
    sent = _sent(rows)
    over = [r for r in sent if (r.get("days_overdue") or 0) > 0]
    drafts = [r for r in rows if (r.get("status") or "draft") == "draft"]
    owed = sum(float(r.get("total") or 0) for r in sent)
    over_sum = sum(float(r.get("total") or 0) for r in over)
    facts: Dict[str, Any] = {"known": _known_amounts(rows, rec.paid_invoices)}
    lines: List[str] = []
    sources = _open_sources(rows)

    if q.form in ("who_owes", "owed_total", "overdue"):
        if any(not r.get("client") or r.get("client") == "(no client)" for r in sent):
            raise _Leave("unnamed_client")
        if q.form == "who_owes":
            clients = _by_client(sent)
            if len(clients) > MAX_CLIENT_LINES:
                raise _Leave("too_long")
            if not sent:
                return Answer("Nobody owes you right now: there are no sent, unpaid invoices.",
                              sources, {**facts, "headline": [], "count": 0}, empty=True)
            lines.append(f"You're owed {_money(owed)} across {_plural(len(sent), 'sent invoice')}.")
            for name, c in clients:
                line = f"{name} owes {_money(c['owed'])} across {_plural(c['n'], 'invoice')}"
                if c["n_over"]:
                    line += f", {_money(c['over'])} of it overdue"
                lines.append(line + ".")
            facts.update(headline=[_cents(owed)] + [_cents(c["owed"]) for _, c in clients],
                         count=len(clients))
        elif q.form == "owed_total":
            if not sent:
                return Answer("You're owed nothing right now: there are no sent, unpaid invoices.",
                              sources, {**facts, "headline": [], "count": 0}, empty=True)
            lines.append(f"You're owed {_money(owed)} across {_plural(len(sent), 'sent invoice')}.")
            if over:
                verb = "is" if len(over) == 1 else "are"
                lines.append(f"{len(over)} of those {'invoice' if len(over) == 1 else 'invoices'} "
                             f"{verb} overdue, {_money(over_sum)} in total.")
            if drafts:
                lines.append(f"You also have {_plural(len(drafts), 'draft')}, "
                             f"{_money(sum(float(r.get('total') or 0) for r in drafts))}, not yet sent.")
            facts.update(headline=[_cents(owed)], count=len(sent))
        else:
            if not over:
                return Answer("Nothing is overdue right now.", sources,
                              {**facts, "headline": [], "count": 0}, empty=True)
            clients = _by_client(over)
            if len(clients) > MAX_CLIENT_LINES:
                raise _Leave("too_long")
            verb = "is" if len(over) == 1 else "are"
            lines.append(f"{_plural(len(over), 'invoice')} {verb} overdue, {_money(over_sum)} in total.")
            for name, c in clients:
                lines.append(f"{name} has {_money(c['over'])} overdue.")
            facts.update(headline=[_cents(over_sum)] + [_cents(c["over"]) for _, c in clients],
                         count=len(over))
        return Answer(" ".join(lines), sources, facts)

    # did_pay / client_balance: one client's invoices.
    name = (rec.contact or {}).get("name") or ""
    mine = sent
    if len(mine) > MAX_CLIENT_OPEN:
        raise _Leave("too_long")
    paid = sorted(rec.paid_invoices, key=lambda r: str(r.get("paid_at") or ""), reverse=True)
    for r in sorted(mine, key=lambda r: str(r.get("due_date") or "9999")):
        lines.append(_owe_line(name, r))
    if q.form == "did_pay" and paid:
        p = paid[0]
        num = p.get("number")
        line = f"{name} paid invoice {num}, {_money(float(p.get('total') or 0))}" if num \
            else f"{name} paid an invoice of {_money(float(p.get('total') or 0))}"
        at = _instant(p.get("paid_at"))
        if at:
            line += f", on {_md(at.astimezone(tz).date())}"
        lines.append(line + ".")
    if paid:
        sources["rail:paid_invoices"] = {
            "kind": "record", "complete": True,
            "text": json.dumps([{"record": "invoice", **r} for r in paid[:3]], default=str,
                               ensure_ascii=False)}
    polarity = "owes" if mine else ("paid" if paid else "none")
    facts.update(polarity=polarity, count=len(mine),
                 headline=[_cents(r.get("total")) for r in mine]
                 + ([_cents(paid[0].get("total"))] if q.form == "did_pay" and paid and not mine else []))
    if not lines:
        text = (f"{name} owes you nothing right now: there are no sent, unpaid invoices for them."
                if q.form == "client_balance" or paid else f"{name} has no sent invoices on file.")
        return Answer(text, sources, facts, empty=True)
    return Answer(" ".join(lines), sources, facts)


def _session_parts(s: Dict[str, Any], tz) -> Tuple[str, str, Optional[datetime]]:
    """(title, client name, local start) of one session row."""
    at = _instant(s.get("scheduled_for"))
    title = str(s.get("title") or "").strip()
    who = ((s.get("contacts") or {}).get("name") if isinstance(s.get("contacts"), dict) else None) or ""
    return title, str(who).strip(), (at.astimezone(tz) if at else None)


def _session_sources(rec: Records) -> Dict[str, Dict[str, Any]]:
    out = {"context:sessions": {"kind": "context", "complete": rec.complete, "text": json.dumps(
        {"heading": f"SESSIONS ({rec.window})", "rows": rec.sessions}, default=str, ensure_ascii=False)}}
    if rec.day_iso:
        out["rail:session_count"] = {"kind": "record", "complete": rec.complete, "text": json.dumps(
            [{"day": rec.day_iso, "sessions_booked": len(rec.sessions)}])}
    return out


def _compose_schedule(q: Question, rec: Records, tz) -> Optional[Answer]:
    sources = _session_sources(rec)
    times = []
    for s in rec.sessions:
        at = _instant(s.get("scheduled_for"))
        if at:
            local = at.astimezone(tz)
            times.append(f"{local.hour:02d}:{local.minute:02d}")
    facts: Dict[str, Any] = {"times": times, "count": len(rec.sessions)}
    if q.form == "day":
        if len(rec.sessions) > MAX_DAY_SESSIONS:
            raise _Leave("too_long")
        if not rec.sessions:
            return Answer(f"Nothing is booked {rec.label}.", sources, facts, empty=True)
        lines = [f"You have {_plural(len(rec.sessions), 'session')} {rec.label}."]
        for s in rec.sessions:
            title, who, local = _session_parts(s, tz)
            if local is None:
                raise _Leave("bad_time")
            what = f"{title} with {who}" if title and who else (title or who or "A session")
            lines.append(f"{_clock(local)}: {what}.")
        return Answer(" ".join(lines), sources, facts)
    if not rec.sessions:
        name = (rec.contact or {}).get("name")
        text = (f"{name} has nothing booked ahead." if q.form == "client_next"
                else "Nothing is booked ahead on your calendar.")
        return Answer(text, sources, facts, empty=True)
    title, who, local = _session_parts(rec.sessions[0], tz)
    if local is None:
        raise _Leave("bad_time")
    facts["times"] = times[:1]
    if q.form == "client_next":
        name = (rec.contact or {}).get("name") or ""
        text = (f"{name} is booked for {title} on {_when(local)}." if title
                else f"{name} is booked on {_when(local)}.")
        return Answer(text, sources, facts)
    what = (f"{title} with {who}" if title and who else title or (f"with {who}" if who else "booked"))
    return Answer(f"Your next session is {what} on {_when(local)}.", sources, facts)


def prove(answer: Answer, rec: Records, tz) -> Tuple[str, List[str]]:
    """How the answer is proved: 'prover' (chief_truth's free check passed
    every sentence against the records), 'empty_read' (nothing to report,
    and the read was the whole list), or 'failed'."""
    if answer.empty:
        return ("empty_read", []) if rec.complete else ("failed", [])
    import chief_truth
    cited = chief_truth.fast_lane(answer.text, answer.sources, tz)
    return ("prover", list(cited)) if cited is not None else ("failed", [])


# ─── What Chief said ─────────────────────────────────────────────────

_WALL = re.compile(r"couldn['’]t (?:verify|confirm)|could not (?:verify|confirm)|"
                   r"^No action ran in this request|^Your request came through\. I couldn", re.I)
_DOLLARS = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?![\d,])")
_CLOCK_SAID = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\b\.?|\b(noon|midday)\b", re.I)
_NONE_SAID = re.compile(
    r"\b(?:no one|nobody|nothing|none|zero|no (?:open|unpaid|outstanding|overdue|sent|invoices?|"
    r"sessions?|appointments?|bookings?)|(?:don'?t|do not) (?:have|see) any|(?:aren'?t|are not) any|"
    r"(?:isn'?t|is not) anything|(?:all|fully) (?:paid|caught up|clear)|clear calendar|"
    r"calendar is (?:clear|empty|open))\b", re.I)
_OWES_SAID = re.compile(r"\b(?:still owes?|owes?|owed|owing|has(?:n'?t| not) paid|not (?:yet )?paid|"
                        r"unpaid|outstanding|overdue|balance of|is due)\b", re.I)
_PAID_SAID = re.compile(r"\b(?:has paid|already paid|paid (?:in full|invoice|on|you|it|that|her|his|their|"
                        r"the)|(?:she|he|they) paid|payment (?:came|went) (?:in|through)|marked (?:as )?paid|"
                        r"is paid)\b", re.I)


def amounts_said(text: str) -> List[str]:
    out = []
    for whole, frac in _DOLLARS.findall(text or ""):
        out.append(_cents(whole.replace(",", "") + "." + (frac or "0")))
    return sorted(set(x for x in out if x))


def times_said(text: str) -> List[str]:
    out = set()
    for h, m, ap, noon in _CLOCK_SAID.findall(text or ""):
        if noon:
            out.add("12:00")
            continue
        hour = int(h) % 12 + (12 if ap.lower() == "p" else 0)
        if 0 <= hour < 24:
            out.add(f"{hour:02d}:{int(m or 0):02d}")
    return sorted(out)


def compare(q: Question, answer: Answer, reply: str) -> Tuple[str, Dict[str, Any]]:
    """Did Chief say what the records say? (outcome, detail). Pure.

    agrees   Chief said the rail's headline and nothing the records lack
    partial  everything Chief said is in the records, but not the headline
    differs  Chief said a figure, time or yes/no the records contradict
    withheld Chief's reply was walled ("I couldn't verify…")
    silent   Chief said no figure at all (a question back, a hedge)"""
    reply = reply or ""
    if _WALL.search(reply):
        return "withheld", {}
    facts = answer.facts
    if q.shelf == MONEY:
        said = amounts_said(reply)
        known = set(facts.get("known") or [])
        unknown = [a for a in said if a not in known]
        detail = {"said": said, "unknown": unknown}
        if answer.empty:
            if said:
                return "differs", detail
            return ("agrees" if _NONE_SAID.search(reply) else "silent"), detail
        if unknown:
            return "differs", detail
        pol = facts.get("polarity")
        if pol in ("owes", "paid"):
            owes, paid = bool(_OWES_SAID.search(reply)), bool(_PAID_SAID.search(reply))
            detail["polarity_said"] = ("both" if owes and paid else "owes" if owes
                                       else "paid" if paid else None)
            if (pol == "owes" and paid and not owes) or (pol == "paid" and owes and not paid):
                return "differs", detail
        if not said:
            return "silent", detail
        head = facts.get("headline") or []
        return ("agrees" if head and head[0] in said else "partial"), detail
    said = times_said(reply)
    want = list(facts.get("times") or [])
    detail = {"said": said}
    if answer.empty:
        if said:
            return "differs", detail
        return ("agrees" if _NONE_SAID.search(reply) else "silent"), detail
    if q.form != "day":
        if not said:
            return "silent", detail
        return ("agrees" if want and want[0] in said else "differs"), detail
    extra = [t for t in said if t not in want]
    if extra:
        return "differs", {**detail, "unknown": extra}
    if said and set(want) <= set(said):
        return "agrees", detail
    return ("partial" if said else "silent"), detail


# ─── Reading ─────────────────────────────────────────────────────────

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _get(path: str) -> Optional[List[Dict[str, Any]]]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        return None
    return rows


def _business(bid: str, user_id: str) -> Optional[Dict[str, Any]]:
    """The business row, only when the asking user owns it. Service-role
    read, compared in code (the _require_owner pattern): the rail reads
    nothing a collaborator, or anyone else, could not already open."""
    rows = _get(f"/businesses?id=eq.{bid}&select=id,owner_id,availability:settings->availability&limit=1")
    if not rows or str(rows[0].get("id")) != bid or str(rows[0].get("owner_id") or "") != user_id:
        return None
    return rows[0]


def _tz(biz: Dict[str, Any]):
    """The business's clock, by mailbox_policy.email_clock's precedence:
    the availability settings, then the owner's profile, then the platform
    default, then UTC."""
    name = (biz.get("availability") or {}).get("timezone") if isinstance(biz.get("availability"), dict) else None
    if not name and biz.get("owner_id"):
        prof = _get(f"/practitioner_profiles?owner_id=eq.{biz['owner_id']}&select=timezone&limit=1")
        name = (prof or [{}])[0].get("timezone") if prof else None
    name = name or os.environ.get("PLATFORM_DEFAULT_TZ", "").strip() or "UTC"
    try:
        return ZoneInfo(str(name).strip())
    except (ValueError, ZoneInfoNotFoundError):
        return timezone.utc


def _contact(bid: str, typed: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """The one contact a typed name means, or (None, why). One word matches
    a first or last name; more words must be the name's start."""
    words = typed.split()
    pattern = quote("*" + typed.replace(" ", "*") + "*", safe="*")
    rows = _get(f"/contacts?business_id=eq.{bid}&name=ilike.{pattern}&select=id,name&limit=25")
    if rows is None:
        return None, "read_failed"

    def fits(name: str) -> bool:
        parts = re.sub(r"[^a-z' -]", "", name.lower()).split()
        if not parts:
            return False
        if len(words) == 1:
            return words[0] in (parts[0], parts[-1])
        return parts[:len(words)] == words or parts == words

    hits = [r for r in rows if fits(str(r.get("name") or ""))]
    exact = [r for r in hits if str(r.get("name") or "").lower().split() == words]
    hits = exact or hits
    if not hits:
        return None, "name_not_found"
    if len(hits) > 1 or len(rows) >= 25:
        return None, "name_ambiguous"
    return hits[0], ""


def _chief_rows(rows: List[Dict[str, Any]], client: Optional[str] = None) -> List[Dict[str, Any]]:
    import chief_of_staff as chief
    return chief._with_days_overdue([{
        "id": r.get("id"),
        "number": r.get("invoice_number") or "(no number)",
        "client": client or (((r.get("contacts") or {}).get("name")
                              if isinstance(r.get("contacts"), dict) else None) or "(no client)"),
        "total": float(r.get("total") or 0),
        "status": r.get("status") or "draft",
        "due_date": r.get("due_date") or "",
    } for r in rows])


def _iso(at: datetime) -> str:
    return quote(at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), safe="")


def read(q: Question, bid: str, tz, *, now: Optional[datetime] = None) -> Records:
    """The one read each question shape needs. Fresh every time."""
    now = now or datetime.now(timezone.utc)
    rec = Records()
    if q.name:
        rec.contact, why = _contact(bid, q.name)
        if rec.contact is None:
            return Records(ok=False, why=why)
    cid = (rec.contact or {}).get("id")
    if q.shelf == MONEY:
        if cid:
            rows = _get(f"/invoices?business_id=eq.{bid}&contact_id=eq.{cid}&status=neq.cancelled"
                        f"&select=id,invoice_number,total,status,due_date,paid_at"
                        f"&order=created_at.desc&limit=50")
            if rows is None:
                return Records(ok=False, why="read_failed")
            rec.complete = len(rows) < 50
            name = rec.contact.get("name")
            rec.open_invoices = _chief_rows(
                [r for r in rows if r.get("status") in ("sent", "viewed", "overdue")], name)
            rec.paid_invoices = [{"number": r.get("invoice_number"), "client": name,
                                  "total": float(r.get("total") or 0), "status": "paid",
                                  "paid_at": r.get("paid_at"), "due_date": r.get("due_date") or ""}
                                 for r in rows if r.get("status") == "paid"]
        else:
            rows = _get(f"/invoices?business_id=eq.{bid}&status=in.(draft,sent,viewed,overdue)"
                        f"&select=id,invoice_number,total,status,due_date,contact_id,contacts(name)"
                        f"&order=due_date.asc.nullslast&limit={MAX_OPEN_INVOICES + 1}")
            if rows is None:
                return Records(ok=False, why="read_failed")
            if len(rows) > MAX_OPEN_INVOICES:
                return Records(ok=False, why="too_many_rows")
            rec.open_invoices = _chief_rows(rows)
        return rec
    select = "&select=id,title,scheduled_for,contact_id,contacts(name)&order=scheduled_for.asc"
    base = f"/sessions?business_id=eq.{bid}&status=eq.scheduled"
    if q.form == "day":
        today = now.astimezone(tz).date()
        if q.day == "today":
            day, rec.label = today, "today"
        elif q.day == "tomorrow":
            day, rec.label = today + timedelta(days=1), "tomorrow"
        else:
            ahead = (_DAY_NAMES.index(q.day) - today.weekday()) % 7
            if ahead == 0:
                return Records(ok=False, why="ambiguous_day")   # today, or a week from today?
            day = today + timedelta(days=ahead)
            rec.label = f"on {day:%A}, {_md(day)}"
        lo = datetime.combine(day, dtime.min, tzinfo=tz)
        hi = datetime.combine(day + timedelta(days=1), dtime.min, tzinfo=tz)
        limit = MAX_DAY_SESSIONS + 1
        rows = _get(f"{base}&scheduled_for=gte.{_iso(lo)}&scheduled_for=lt.{_iso(hi)}{select}&limit={limit}")
        rec.window, rec.day_iso = f"{day.isoformat()}, {day:%A}", day.isoformat()
    else:
        limit = 1
        who = f"&contact_id=eq.{cid}" if cid else ""
        rows = _get(f"{base}{who}&scheduled_for=gte.{_iso(now)}{select}&limit={limit}")
        rec.window = "next booked" + (f" for {rec.contact.get('name')}" if cid else "")
    if rows is None:
        return Records(ok=False, why="read_failed")
    rec.sessions = rows
    rec.complete = len(rows) < limit or q.form != "day"
    return rec


# ─── Practice ────────────────────────────────────────────────────────

_RUNNING = threading.BoundedSemaphore(3)
_skip_db_until = 0.0
_table_missing_logged = False


def after_turn(req: Any, user_id: str, complexity: Any, payload: Any, *, rec: Any = None) -> None:
    """Called once a full Chief turn has answered (chief_fast_track.TwoTrack.finish).
    Returns at once; the practice runs on its own thread. Never raises."""
    try:
        if mode() == "off" or not isinstance(payload, dict):
            return
        message = str(getattr(req, "message", "") or "")
        if (getattr(req, "image_ids", None) or (getattr(req, "mode", None) or "") not in ("", "chief")
                or message.lstrip().startswith("[SYSTEM:")):
            return
        if rec is not None and getattr(rec, "reason", "") == "checked_availability":
            return          # already answered from the records by chief_availability
        bid = str(getattr(req, "business_id", "") or "")
        if not (_UUID.match(bid) and _UUID.match(str(user_id or ""))):
            return
        q, why, shelf = read_question(message)
        kind = getattr(complexity, "kind", None)
        if q is None and kind != "lookup":
            return          # not a records question: nothing to learn here
        if not _RUNNING.acquire(blocking=False):
            print("[rail] practice skipped: busy", flush=True)
            return
        tally = getattr(rec, "tally", None)
        job = {
            "q": q, "why": why, "shelf": shelf, "kind": kind, "bid": bid, "user_id": str(user_id),
            "reply": str(payload.get("response") or ""),
            "grounding": str(((payload.get("grounding") or {}).get("status")) or "") or None,
            "verbs": [str(a.get("type")) for a in (payload.get("actions_taken") or [])
                      if isinstance(a, dict) and a.get("type")][:12],
            "request_id": str(getattr(rec, "request_id", "") or getattr(req, "request_id", "") or "")[:80] or None,
            "surface": (str(getattr(req, "client_surface", "") or "") or "desktop")[:20],
            "chief_cost_cents": tally.cost_cents() if tally is not None else None,
            "chief_ms": getattr(rec, "total_ms", None),
        }
        try:
            threading.Thread(target=_practice, args=(job,), name="rail-practice", daemon=True).start()
        except Exception:
            _RUNNING.release()
            raise
    except Exception as e:  # pragma: no cover — practice must never cost a reply
        print(f"[rail] practice not started: {type(e).__name__}", flush=True)


def _practice(job: Dict[str, Any]) -> None:
    try:
        row = practice(job)
        if row:
            _write(row)
            print(f"[rail] practice shelf={row['shelf']} form={row['form']} took={row['took']} "
                  f"decline={row['decline_reason']} proof={row['proof']} outcome={row['outcome']} "
                  f"rail_ms={row['rail_ms']} chief_ms={row['chief_ms']}", flush=True)
    except Exception as e:  # pragma: no cover
        print(f"[rail] practice failed: {type(e).__name__}", flush=True)
    finally:
        _RUNNING.release()


def practice(job: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """One practice run: read, compose, prove, compare. The row to keep,
    or None when there is nothing to record (the user is not the owner)."""
    import action_registry
    started = time.perf_counter()
    q: Optional[Question] = job.get("q")
    verbs = job.get("verbs") or []
    row: Dict[str, Any] = {
        "request_id": job.get("request_id"), "business_id": job["bid"], "surface": job.get("surface"),
        "kind": job.get("kind"), "shelf": q.shelf if q else job.get("shelf"),
        "form": q.form if q else None, "took": False, "decline_reason": None if q else job.get("why"),
        "proof": None, "proof_sources": [], "rail_answer": None, "rail_facts": {},
        "outcome": None, "outcome_detail": {}, "chief_grounding": job.get("grounding"),
        "chief_wrote": any(action_registry.effect(v) == action_registry.WRITE for v in verbs),
        "chief_verbs": verbs, "chief_cost_cents": job.get("chief_cost_cents"),
        "chief_ms": job.get("chief_ms"), "rail_ms": None,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    biz = _business(job["bid"], job["user_id"])
    if biz is None:
        return None
    if q is None:
        return row
    tz = _tz(biz)
    rec = read(q, job["bid"], tz, now=now)
    if not rec.ok:
        row.update(decline_reason=rec.why, rail_ms=int((time.perf_counter() - started) * 1000))
        return row
    answer, why = compose(q, rec, tz)
    if answer is None:
        row.update(decline_reason=why, rail_ms=int((time.perf_counter() - started) * 1000))
        return row
    proof, cited = prove(answer, rec, tz)
    outcome, detail = compare(q, answer, job.get("reply") or "")
    if row["chief_wrote"]:
        detail = {**detail, "note": "chief also changed something"}
    row.update(took=True, proof=proof, proof_sources=cited, rail_answer=answer.text[:600],
               rail_facts={k: v for k, v in answer.facts.items() if k != "known"},
               outcome=outcome, outcome_detail=detail,
               rail_ms=int((time.perf_counter() - started) * 1000))
    return row


def _write(row: Dict[str, Any]) -> None:
    global _skip_db_until, _table_missing_logged
    if time.time() < _skip_db_until:
        return
    try:
        import sb_clients
        ok = bool(sb_clients.sb_post_as_service(f"/{TABLE}", row))
    except Exception:
        ok = False
    if not ok:
        _skip_db_until = time.time() + 600
        if not _table_missing_logged:
            _table_missing_logged = True
            print("[rail] chief_rail_practice write failed: is "
                  "supabase/APPLY-2026-10-16-chief-rail-practice.sql applied?", flush=True)


# ─── The owner's view ────────────────────────────────────────────────

def _pct(vals: List[int], p: float) -> Optional[int]:
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    k = max(1, math.ceil(p / 100.0 * len(vals)))
    return int(vals[min(k, len(vals)) - 1])


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Practice rows → what a graduation decision needs, per shelf."""
    out: Dict[str, Any] = {}
    for r in rows:
        s = out.setdefault(r.get("shelf") or "none", {
            "asked": 0, "took": 0, "proved": 0, "declined": {}, "outcomes": {}, "forms": {},
            "chief_cost_cents_on_took": 0.0, "rail_ms": [], "chief_ms": [], "walls_the_rail_answered": 0})
        s["asked"] += 1
        if not r.get("took"):
            why = r.get("decline_reason") or "?"
            s["declined"][why] = s["declined"].get(why, 0) + 1
            continue
        s["took"] += 1
        s["forms"][r.get("form") or "?"] = s["forms"].get(r.get("form") or "?", 0) + 1
        proved = r.get("proof") in ("prover", "empty_read")
        s["proved"] += 1 if proved else 0
        o = r.get("outcome") or "?"
        s["outcomes"][o] = s["outcomes"].get(o, 0) + 1
        s["chief_cost_cents_on_took"] += float(r.get("chief_cost_cents") or 0)
        if proved and o == "withheld":
            s["walls_the_rail_answered"] += 1
        for k in ("rail_ms", "chief_ms"):
            if isinstance(r.get(k), (int, float)):
                s[k].append(r[k])
    for s in out.values():
        compared = sum(s["outcomes"].get(k, 0) for k in ("agrees", "partial", "differs"))
        s["agreement_pct"] = round(100.0 * s["outcomes"].get("agrees", 0) / compared, 1) if compared else None
        s["chief_cost_cents_on_took"] = round(s["chief_cost_cents_on_took"], 2)
        for k in ("rail_ms", "chief_ms"):
            vals = s.pop(k)
            s[f"{k}_p50"], s[f"{k}_p95"] = _pct(vals, 50), _pct(vals, 95)
    return out


def _require_owner_dep():
    from lead_admin import require_owner
    return require_owner


@router.get("/platform/rail/stats")
async def rail_stats(days: int = 7, _owner: Any = Depends(_require_owner_dep())):
    """The rail's practice record, per shelf. Owner only. Counts, shares and
    timings; no answers, names or ids."""
    import asyncio
    import sb_clients
    days = max(1, min(int(days or 7), 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    rows: List[Dict[str, Any]] = []
    try:
        got = await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/{TABLE}?created_at=gte.{quote(since, safe='')}&order=created_at.desc&limit=5000"
            "&select=shelf,form,took,decline_reason,proof,outcome,chief_cost_cents,rail_ms,chief_ms")
        rows = got if isinstance(got, list) else []
    except Exception as e:  # pragma: no cover
        print(f"[rail] stats read failed: {type(e).__name__}", flush=True)
    return {"ok": True, "mode": mode(), "days": days, "rows": len(rows), "shelves": summarize(rows)}
