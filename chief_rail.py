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

Switch: only CHIEF_RAIL=practice turns it on; unset, empty or anything else
is off. Rows are kept RETENTION_DAYS (prune_tick, daily) and go with their
business (a cascading foreign key).
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
RETENTION_DAYS = 90
CONTACT_PAGE = 1000          # PostgREST's usual row cap
CONTACT_PAGES = 5            # at 5,000 contacts or more a name search is Chief's


def mode() -> str:
    """'practice' only when CHIEF_RAIL says exactly that; anything else,
    unset included, is 'off'. A deploy without the variable reads nothing."""
    return "practice" if (os.environ.get("CHIEF_RAIL") or "").strip().lower() == "practice" else "off"


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

def _money(v: Decimal) -> str:
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


def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _cents(v: Any) -> str:
    return str(_dec(v))


@dataclass
class Answer:
    text: str
    sources: Dict[str, Dict[str, Any]]
    facts: Dict[str, Any]           # claims (what each figure belongs to), headline sets, counts
    empty: bool = False             # nothing to report: the read itself is the proof


@dataclass
class Records:
    """What the rail read for one question. `complete` = the read returned
    every matching row (it came back under its limit)."""
    ok: bool = True
    why: str = ""
    complete: bool = True
    today: Optional[date] = None    # the business's date when it read
    open_invoices: List[Dict[str, Any]] = field(default_factory=list)   # Chief's row shape
    paid_invoices: List[Dict[str, Any]] = field(default_factory=list)
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    contact: Optional[Dict[str, Any]] = None
    contact_names: Optional[List[str]] = None    # every contact's name, when read
    window: str = ""                # what the session read covered, in words
    label: str = ""                 # "tomorrow" / "on Friday, Oct 17"
    day_iso: str = ""


def _open_sources(rows: List[Dict[str, Any]], complete: bool) -> Dict[str, Dict[str, Any]]:
    """The open invoices exactly as Chief's answer check sees them
    (evidence_for_review): the rows, and the totals Chief computes from
    them. The rail's own sums must agree with Chief's for a sentence to
    prove, so the proof checks two computations against each other."""
    import chief_of_staff as chief
    if not rows:
        return {}
    return {
        "context:open_invoices": {"kind": "context", "complete": complete,
                                  "text": json.dumps(rows, default=str, ensure_ascii=False)},
        "context:invoice_summary": {"kind": "context", "complete": complete,
                                    "text": json.dumps(chief._invoice_summary_lines(rows),
                                                       ensure_ascii=False)},
    }


def _sent(rows):
    return [r for r in rows if (r.get("status") or "draft") != "draft"]


def _total(rows) -> Decimal:
    return sum((_dec(r.get("total")) for r in rows), Decimal("0.00"))


def _by_client(rows):
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        c = out.setdefault(r.get("client") or "", {"owed": Decimal("0.00"), "n": 0,
                                                   "over": Decimal("0.00"), "n_over": 0})
        c["owed"] += _dec(r.get("total"))
        c["n"] += 1
        if (r.get("days_overdue") or 0) > 0:
            c["over"] += _dec(r.get("total"))
            c["n_over"] += 1
    return sorted(out.items(), key=lambda kv: (-kv[1]["owed"], kv[0]))


def _claim(amount, what, client=None, count=None, noun="invoice"):
    return {"amount": _cents(amount), "what": what, "client": client or None,
            "count": count, "noun": noun}


def _money_claims(rows: List[Dict[str, Any]], paid: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every amount the records hold and what it belongs to: each invoice
    (its client), each client's sums (with how many invoices), the totals
    (with their counts). A figure Chief says that is none of these came
    from nowhere; one said next to the wrong client is the wrong fact."""
    sent = _sent(rows)
    over = [r for r in sent if (r.get("days_overdue") or 0) > 0]
    drafts = [r for r in rows if (r.get("status") or "draft") == "draft"]
    out = [_claim(r.get("total"), "invoice", r.get("client"), 1) for r in rows]
    out += [_claim(r.get("total"), "paid", r.get("client"), 1) for r in paid]
    for name, c in _by_client(sent):
        out.append(_claim(c["owed"], "client_owed", name, c["n"]))
        if c["n_over"]:
            out.append(_claim(c["over"], "client_over", name, c["n_over"]))
    out.append(_claim(_total(sent), "owed_total", None, len(sent)))
    out.append(_claim(_total(over), "over_total", None, len(over)))
    if drafts:
        out.append(_claim(_total(drafts), "draft_total", None, len(drafts)))
    return out


def _owe_line(name: str, r: Dict[str, Any]) -> str:
    num = r.get("number")
    on = f"on invoice {num}" if num and num != "(no number)" else "on an invoice"
    line = f"{name} owes {_money(_dec(r.get('total')))} {on}"
    due = _day(r.get("due_date"))
    if due:
        line += f", due {_md(due)}"
    if (r.get("days_overdue") or 0) > 0:
        line += f", {_plural(int(r['days_overdue']), 'day')} overdue"
    return line + "."


class _Leave(Exception):
    """This one is Chief's: the reason is the decline reason."""


def compose(q: Question, rec: Records, tz) -> Tuple[Optional[Answer], str]:
    """(the rail's answer from what it read, '') or (None, why the shelf
    would leave this one to Chief: too long, an unnamed client). Pure."""
    try:
        if q.shelf == MONEY:
            return _compose_money(q, rec, tz), ""
        return _compose_schedule(q, rec, tz), ""
    except _Leave as e:
        return None, str(e)


def _compose_money(q: Question, rec: Records, tz) -> Answer:
    rows = rec.open_invoices
    sent = _sent(rows)
    over = [r for r in sent if (r.get("days_overdue") or 0) > 0]
    drafts = [r for r in rows if (r.get("status") or "draft") == "draft"]
    owed, over_sum = _total(sent), _total(over)
    facts: Dict[str, Any] = {"claims": _money_claims(rows, rec.paid_invoices)}
    lines: List[str] = []
    sources = _open_sources(rows, rec.complete)

    if q.form in ("who_owes", "owed_total", "overdue"):
        if any(not r.get("client") or r.get("client") == "(no client)" for r in sent):
            raise _Leave("unnamed_client")
        if q.form == "who_owes":
            clients = _by_client(sent)
            if len(clients) > MAX_CLIENT_LINES:
                raise _Leave("too_long")
            if not sent:
                return Answer("Nobody owes you right now: there are no sent, unpaid invoices.",
                              sources, {**facts, "headline": []}, empty=True)
            lines.append(f"You're owed {_money(owed)} across {_plural(len(sent), 'sent invoice')}.")
            for name, c in clients:
                line = f"{name} owes {_money(c['owed'])} across {_plural(c['n'], 'invoice')}"
                if c["n_over"]:
                    line += f", {_money(c['over'])} of it overdue"
                lines.append(line + ".")
            facts.update(headline=[[_cents(owed)] + [_cents(c["owed"]) for _, c in clients]],
                         clients=len(clients))
        elif q.form == "owed_total":
            if not sent:
                return Answer("You're owed nothing right now: there are no sent, unpaid invoices.",
                              sources, {**facts, "headline": []}, empty=True)
            lines.append(f"You're owed {_money(owed)} across {_plural(len(sent), 'sent invoice')}.")
            if over:
                verb = "is" if len(over) == 1 else "are"
                lines.append(f"{len(over)} of those {'invoice' if len(over) == 1 else 'invoices'} "
                             f"{verb} overdue, {_money(over_sum)} in total.")
            if drafts:
                lines.append(f"You also have {_plural(len(drafts), 'draft')}, "
                             f"{_money(_total(drafts))}, not yet sent.")
            facts.update(headline=[[_cents(owed)]], clients=len(_by_client(sent)))
        else:
            if not over:
                return Answer("Nothing is overdue right now.", sources, {**facts, "headline": []},
                              empty=True)
            clients = _by_client(over)
            if len(clients) > MAX_CLIENT_LINES:
                raise _Leave("too_long")
            verb = "is" if len(over) == 1 else "are"
            lines.append(f"{_plural(len(over), 'invoice')} {verb} overdue, {_money(over_sum)} in total.")
            for name, c in clients:
                lines.append(f"{name} has {_money(c['over'])} overdue.")
            facts.update(headline=[[_cents(over_sum)] + [_cents(c["over"]) for _, c in clients]],
                         clients=len(clients))
        return Answer(" ".join(lines), sources, facts)

    # did_pay / client_balance: one client's open invoices, and their last payment.
    name = (rec.contact or {}).get("name") or ""
    mine = sorted(sent, key=lambda r: str(r.get("due_date") or "9999"))
    paid = rec.paid_invoices[:1]
    for r in mine:
        lines.append(_owe_line(name, r))
    if q.form == "did_pay" and paid:
        p = paid[0]
        num = p.get("number")
        line = (f"{name} paid invoice {num}, {_money(_dec(p.get('total')))}" if num
                else f"{name} paid an invoice of {_money(_dec(p.get('total')))}")
        at = _instant(p.get("paid_at"))
        if at:
            line += f", on {_md(at.astimezone(tz).date())}"
        lines.append(line + ".")
    if paid:
        sources["rail:paid_invoices"] = {
            "kind": "record", "complete": True,
            "text": json.dumps([{"record": "invoice", **r} for r in paid], default=str, ensure_ascii=False)}
    if mine:
        # Every open invoice said, or the client's total for them.
        headline = [[_cents(r.get("total")) for r in mine], [_cents(_total(mine))]]
    elif q.form == "did_pay" and paid:
        headline = [[_cents(paid[0].get("total"))]]
    else:
        headline = []
    facts.update(polarity="owes" if mine else ("paid" if paid else "none"), headline=headline,
                 client=name or None)
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


def _compose_schedule(q: Question, rec: Records, tz) -> Answer:
    sources = _session_sources(rec)
    claims = []
    for s in rec.sessions:
        title, who, local = _session_parts(s, tz)
        if local is None:
            raise _Leave("bad_time")
        claims.append({"time": f"{local.hour:02d}:{local.minute:02d}", "client": who or None,
                       "date": local.date().isoformat(), "title": title})
    today = rec.today.isoformat() if rec.today else None
    facts: Dict[str, Any] = {"claims": claims, "count": len(rec.sessions), "today": today}
    if q.form == "day":
        if len(rec.sessions) > MAX_DAY_SESSIONS:
            raise _Leave("too_long")
        facts["day"] = rec.day_iso
        if not rec.sessions:
            return Answer(f"Nothing is booked {rec.label}.", sources, facts, empty=True)
        lines = [f"You have {_plural(len(rec.sessions), 'session')} {rec.label}."]
        for c in claims:
            what = (f"{c['title']} with {c['client']}" if c["title"] and c["client"]
                    else (c["title"] or c["client"] or "A session"))
            h, m = map(int, c["time"].split(":"))
            lines.append(f"{_clock(datetime(2000, 1, 1, h, m))}: {what}.")
        return Answer(" ".join(lines), sources, facts)
    if not rec.sessions:
        name = (rec.contact or {}).get("name")
        text = (f"{name} has nothing booked ahead." if q.form == "client_next"
                else "Nothing is booked ahead on your calendar.")
        return Answer(text, sources, facts, empty=True)
    title, who, local = _session_parts(rec.sessions[0], tz)
    facts["claims"] = claims[:1]
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
    and the read was the whole list), or 'failed'. A read that did not
    return every row proves nothing."""
    if not rec.complete:
        return "failed", []
    if answer.empty:
        return "empty_read", []
    import chief_truth
    cited = chief_truth.fast_lane(answer.text, answer.sources, tz)
    return ("prover", list(cited)) if cited is not None else ("failed", [])


# ─── What Chief said ─────────────────────────────────────────────────

_WALL = re.compile(r"couldn['’]t (?:verify|confirm)|could not (?:verify|confirm)|"
                   r"^No action ran in this request|^Your request came through\. I couldn", re.I)
# "$100, then…": a comma after the figure ends it; only ",000" continues it.
_DOLLARS = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?!\d|,\d)")
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
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
_COUNT_SAID = re.compile(
    r"\b(\d+|%s)\s+(?:[a-z]+\s+)?(invoices?|bills?|sessions?|appointments?|bookings?|clients?|"
    r"customers?|people)\b" % "|".join(_NUMBER_WORDS), re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
_DATE_SAID = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)
_WEEKDAY_SAID = re.compile(r"\b(%s|today|tomorrow|tonight)\b" % "|".join(_DAY_NAMES), re.I)
_TOTAL_CUE = re.compile(r"\b(?:total|in all|altogether|all together|overall|combined|of your|"
                        r"everyone|everybody|all (?:of )?(?:your )?clients)\b", re.I)
# The business as the subject: "you're owed", "you have", "in total".
_BUSINESS_SUBJECT = re.compile(r"\b(?:you(?:'re|’re| are)? (?:still )?owed|you have|you've|you’ve|"
                               r"your (?:total|clients|customers|books|balance)|in total|altogether|"
                               r"overall|combined|across (?:all|everyone)|everyone|everybody)\b", re.I)
_PRONOUN = re.compile(r"\b(?:she|he|they|her|him|them|his|hers|their)\b", re.I)
# Each "paid" is read with whatever negates it, and only that: "the
# previously unpaid $300 has now been paid" says paid AND owed.
_PAID_WORD = re.compile(r"(?<![-\w])(?:paid|received|collected|came in|cleared|settled)\b", re.I)
# "n't" sits inside its word ("doesn't", "hasn't"), so it has no boundary
# before it.
_NEGATION_BEFORE = re.compile(r"(?:\b(?:not|never|neither|nobody|no one|none|nothing|no longer|yet to be|"
                              r"still to be)\b|n['’]t\b)[\w\s'’]{0,14}$", re.I)
_OWED_WORD = re.compile(r"(?<![-\w])(?:owes?|owed|owing|unpaid|outstanding|overdue|due|open|pending|"
                        r"unsettled|balance)\b", re.I)
_OWED_KINDS = ("invoice", "client_owed", "client_over", "owed_total", "over_total", "draft_total")
_TOTAL_KINDS = ("owed_total", "over_total", "draft_total")
_SEGMENT = re.compile(r",\s+|;\s*|\s+(?:and|but|while|plus)\s+|\s+[–—-]\s+", re.I)
# Money also splits at a colon ("You're owed $300 in total: Maria owes
# $100"). A calendar line keeps its colon: "10:00 AM: Haircut with Maria"
# is one claim about Maria.
_SEGMENT_MONEY = re.compile(r",\s+|;\s*|:\s+|\s+(?:and|but|while|plus)\s+|\s+[–—-]\s+", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# Capitalised words in a reply that are not a person: the business's own
# nouns, the calendar, and how sentences start (chief_truth's list covers
# the most common words).
_NOT_PEOPLE = frozenset("""
invoice invoices inv total totals balance balances overdue payment payments paid unpaid session
sessions appointment appointments booking bookings calendar schedule client clients customer
customers draft drafts am pm noon your you you're yes no not nothing nobody none next upcoming
neither both all every each most some any also just still only great good right sure okay ok
here there it its they we our us heads note looks so then quick reminder dollars usd
chief solutionist stripe square paypal venmo zelle cashapp quickbooks plaid
you've you'll you'd i'm i've i'll i'd we're we've we'll that's there's here's it's let's what's
thanks thank unfortunately currently altogether together overall combined between across of
including plus meanwhile however otherwise besides separately earlier later recently outstanding
open pending owed due sent nope yep already remaining remember will shall do does did is are was
were has have had everyone everybody someone anyone either second finally lastly update summary
breakdown bottom line money cash revenue income deposit deposits check card biggest largest
smallest oldest newest highest lowest least more less again since while once until because
alright absolutely definitely honestly basically actually apparently hopefully luckily sadly
mostly roughly about around almost nearly exactly great good happy sounds looks right last first
from after before when if and but or with for at by in on to as up out over under also both
""".split())

# Outcome order, worst first: what one reply is, when its parts disagree.
_SEVERITY = ("differs", "unverified")


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


def _counts_said(text: str) -> List[Tuple[int, str]]:
    out = []
    for n, noun in _COUNT_SAID.findall(text or ""):
        num = int(n) if n.isdigit() else _NUMBER_WORDS[n.lower()]
        noun = noun.lower()
        kind = ("invoice" if noun.startswith(("invoice", "bill")) else
                "client" if noun.startswith(("client", "customer", "people")) else "session")
        out.append((num, kind))
    return out


def _base(w: str) -> str:
    low = w.lower().replace("’", "'")
    return low[:-2] if low.endswith("'s") else low


def _people_said(text: str, known: Dict[str, set]) -> Tuple[set, bool]:
    """(the known clients this text names, whether it names anyone else).

    `known` maps each lowercased name word to the clients it belongs to.
    A client's name counts in any case ("MARIA", "maria").

    Someone else is any capitalised word (or one in capitals, four letters
    or more) that is no client and no common word, wherever it stands:
    "Jordan at 10am" is a person the records don't hold. The words
    sentences start with ("Overall,", "Currently", "You've") are common
    words (_NOT_PEOPLE), so an ordinary reply is not held up; an unusual
    one is unresolved, which keeps it out of agreement, never in."""
    import chief_truth
    named, stranger = set(), False
    words = list(re.finditer(r"[A-Za-z][A-Za-z'’]*", text or ""))
    for k, m in enumerate(words):
        w = m.group(0)
        low = _base(w)
        if low in known and len(low) > 2 and low not in chief_truth._NOT_NAMES and low not in _NOT_PEOPLE:
            named |= known[low]
            continue
        if not w[0].isupper() or (w.isupper() and len(low) <= 3):
            continue        # lower case, or INV / USD / AM
        if low in known or low in _NOT_PEOPLE or low in chief_truth._NOT_NAMES or len(low) < 2:
            continue
        stranger = True
    return named, stranger


def _status_of(text: str) -> Optional[str]:
    """What a part says of its amounts: 'paid', 'owed', 'both' (it says
    each, so which is unresolved), 'negated' ("doesn't owe": not a status
    the records can confirm), or None."""
    paid = owed = negated = False
    for m in _PAID_WORD.finditer(text or ""):
        if _NEGATION_BEFORE.search(text[:m.start()]):
            owed = True             # "hasn't paid", "neither has paid"
        else:
            paid = True
    for m in _OWED_WORD.finditer(text or ""):
        word = m.group(0).lower()
        if word != "unpaid" and _NEGATION_BEFORE.search(text[:m.start()]) \
                and not re.search(r"\b(?:still|yet)\b[\w\s'’]{0,6}$", text[:m.start()], re.I):
            negated = True          # "doesn't owe", "no longer outstanding"
        else:
            owed = True
    if negated:
        return "negated"
    if paid and owed:
        return "both"
    return "paid" if paid else "owed" if owed else None


def _days_said(text: str, today: Optional[date]) -> set:
    """The dates a text names: a month and day, a weekday (the next one),
    today, tomorrow."""
    out = set()
    for mon, d in _DATE_SAID.findall(text or ""):
        if today:
            try:
                out.add(date(today.year, _MONTHS[mon.lower()[:3]], int(d)).isoformat())
            except ValueError:
                pass
    for w in _WEEKDAY_SAID.findall(text or ""):
        w = w.lower()
        if not today:
            continue
        if w in ("today", "tonight"):
            out.add(today.isoformat())
        elif w == "tomorrow":
            out.add((today + timedelta(days=1)).isoformat())
        else:
            ahead = (_DAY_NAMES.index(w) - today.weekday()) % 7
            out.add((today + timedelta(days=ahead)).isoformat())
            out.add((today + timedelta(days=ahead or 7)).isoformat())
    return out


def compare(q: Question, answer: Answer, reply: str) -> Tuple[str, Dict[str, Any]]:
    """Did Chief say what the records say? (outcome, detail). Pure.

    Each sentence is resolved WHOLE before any figure in it is checked:
    who each part is about and what it says of its amounts (paid, owed).
    Then every amount, time and count is held to the record it belongs to.
    Anything the sentence leaves unresolved is kept out of agreement.

    agrees     the rail's headline, and every claim resolved and true
    partial    every claim resolved and true, but not all of the headline
    differs    a figure, time, count, client, day or yes/no the records contradict
    unverified a claim that can't be resolved: someone the records don't
               hold, a total that could be one client's or everyone's, paid
               and owed at once, a table. Never agreement.
    withheld   Chief's reply was walled
    silent     Chief said no figure at all (a question back, a hedge)"""
    reply = reply or ""
    if _WALL.search(reply):
        return "withheld", {}
    if q.shelf == MONEY:
        return _compare_money(answer, reply)
    return _compare_schedule(q, answer, reply)


def _known_people(names) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for full in names:
        for w in re.findall(r"[A-Za-z][A-Za-z'’-]*", full or ""):
            out.setdefault(w.lower(), set()).add(full)
    return out


def _worst(problems: List[str]) -> Optional[str]:
    for o in _SEVERITY:
        if o in problems:
            return o
    return None


def _sentences(reply: str, splitter, people: Dict[str, set], *, default_client: Optional[str] = None,
               today: Optional[date] = None):
    """Each sentence of a reply, resolved whole. Yields one dict per part:
    its text; `subject` (a set of clients, or 'business', or None when it
    can't be told); `status`; `days`; and `stranger` (the SENTENCE names
    someone the records don't hold).

    A part's own subject is, in order: the client it names; the client a
    pronoun stands for (the one last named in the reply, or the one client
    asked about; unresolved otherwise); the business, when it says so
    ("you're owed", "in total"). A part with none takes the nearest part's
    that has one, before it first, then after. With none in the sentence
    the subject is the business, unstated ('business?'), which any of the
    records' figures can be. A stated business ('business') must be held
    to a business total. A part with no status of its own takes the
    sentence's, when the sentence has exactly one."""
    last_client: set = {default_client} if default_client else set()
    for sentence in _SENTENCE.split(reply or ""):
        parts = [p for p in splitter.split(sentence) if p.strip()]
        info = []
        for p in parts:
            named, stranger = _people_said(p, people)
            if named:
                own = named
            elif _PRONOUN.search(p):
                own = set(last_client) if len(last_client) == 1 else "unresolved"
            elif _BUSINESS_SUBJECT.search(p):
                own = "business"
            else:
                own = None
            info.append({"text": p, "named": named, "stranger": stranger, "own_status": _status_of(p),
                         "own_subject": own, "own_days": _days_said(p, today)})
        stranger = any(i["stranger"] for i in info)
        statuses = {i["own_status"] for i in info if i["own_status"]}
        whole = (None if not statuses else next(iter(statuses)) if len(statuses) == 1 else "both")
        order = lambda k: list(range(k - 1, -1, -1)) + list(range(k + 1, len(info)))
        for k, i in enumerate(info):
            subject = i["own_subject"] or next(
                (info[j]["own_subject"] for j in order(k) if info[j]["own_subject"]), "business?")
            if subject == "unresolved":
                subject = None
            days = i["own_days"] or next(
                (info[j]["own_days"] for j in list(range(k - 1, -1, -1)) + list(range(k + 1, len(info)))
                 if info[j]["own_days"]), set())
            yield {"text": i["text"], "subject": subject, "status": i["own_status"] or whole,
                   "days": days, "stranger": stranger}
        named_here = set().union(*(i["named"] for i in info)) if info else set()
        if named_here:
            last_client = named_here


def _compare_money(answer: Answer, reply: str) -> Tuple[str, Dict[str, Any]]:
    facts = answer.facts
    claims = facts.get("claims") or []
    known = {c["amount"] for c in claims}
    people = _known_people({c["client"] for c in claims if c["client"]} | {facts.get("client") or ""}
                           | set(facts.get("contacts") or []))
    counts = {"invoice": {c["count"] for c in claims if c["count"] is not None},
              "client": {facts.get("clients")} if facts.get("clients") is not None else set()}
    said = amounts_said(reply)
    detail: Dict[str, Any] = {"said": said, "problems": []}
    problems: List[str] = []

    def flag(outcome, why):
        problems.append(outcome)
        detail["problems"].append(why)

    if said and "|" in reply:
        flag("unverified", "table")
    for part in _sentences(reply, _SEGMENT_MONEY, people, default_client=facts.get("client")):
        amts = amounts_said(part["text"])
        stated = _counts_said(part["text"])
        for a in amts:
            if a not in known:
                flag("differs", f"unknown amount {a}")
                continue
            cands = [c for c in claims if c["amount"] == a]
            # Whoever it is about, an amount the records only have owed,
            # said as paid (or the other way round), is wrong.
            if part["status"] == "paid" and not any(c["what"] == "paid" for c in cands):
                flag("differs", f"{a} said as paid, the records have it owed")
                continue
            if part["status"] == "owed" and not any(c["what"] in _OWED_KINDS for c in cands):
                flag("differs", f"{a} said as owed, the records have it paid")
                continue
            if part["stranger"]:
                flag("unverified", f"{a} said in a sentence about someone the records don't hold")
                continue
            subject = part["subject"]
            if subject is None:
                flag("unverified", f"{a}: who it belongs to is unclear")
                continue
            if subject == "business":
                # Said of the business ("you're owed", "in total"): one of
                # its totals, or, asked about one client, that client's own.
                totals = [c for c in cands if c["what"] in _TOTAL_KINDS
                          or (facts.get("client") and c["client"] == facts["client"])]
                if not totals:
                    flag("unverified", f"{a}: one client's figure said as the business's")
                    continue
                cands = totals
            elif subject == "business?":
                pass            # no subject stated: any of the records' figures
            else:
                mine = [c for c in cands if c["client"] in subject]
                if not mine:
                    if _TOTAL_CUE.search(part["text"]) and any(c["what"] in _TOTAL_KINDS for c in cands):
                        flag("unverified", f"{a}: a total said next to a client")
                    else:
                        flag("differs", f"{a} said for the wrong client")
                    continue
                cands = mine
            status = part["status"]
            if status in ("both", "negated"):
                flag("unverified", f"{a}: paid or owed is unresolved ({status})")
                continue
            if status == "paid" and not any(c["what"] == "paid" for c in cands):
                flag("differs", f"{a} said as paid, the records have it owed")
                continue
            if status == "owed" and not any(c["what"] in _OWED_KINDS for c in cands):
                flag("differs", f"{a} said as owed, the records have it paid")
                continue
            inv = [n for n, kind in stated if kind == "invoice"]
            if inv and len(amts) == 1 and not any(c["count"] in inv for c in cands
                                                  if c["count"] is not None):
                flag("differs", f"{a} said with the wrong invoice count")
        for n, kind in stated:
            if kind in counts and counts[kind] and n not in counts[kind]:
                flag("differs", f"count {n} {kind}")
    if answer.empty:
        worst = _worst(problems) or ("differs" if said else None)
        if worst:
            return worst, detail
        return ("agrees" if _NONE_SAID.search(reply) else "silent"), detail
    pol = facts.get("polarity")
    if pol in ("owes", "paid"):
        owes, paid = bool(_OWES_SAID.search(reply)), bool(_PAID_SAID.search(reply))
        detail["polarity_said"] = "both" if owes and paid else "owes" if owes else "paid" if paid else None
        if (pol == "owes" and paid and not owes) or (pol == "paid" and owes and not paid):
            flag("differs", "yes/no")
    worst = _worst(problems)
    if worst:
        return worst, detail
    if not said:
        return "silent", detail
    covered = any(set(h) <= set(said) for h in facts.get("headline") or [])
    return ("agrees" if covered else "partial"), detail


def _compare_schedule(q: Question, answer: Answer, reply: str) -> Tuple[str, Dict[str, Any]]:
    facts = answer.facts
    claims = facts.get("claims") or []
    today = _day(facts.get("today"))
    people = _known_people({c["client"] for c in claims if c["client"]}
                           | {w for c in claims for w in [c["title"]] if w}
                           | set(facts.get("contacts") or []))
    said = times_said(reply)
    detail: Dict[str, Any] = {"said": said, "problems": []}
    problems: List[str] = []

    def flag(outcome, why):
        problems.append(outcome)
        detail["problems"].append(why)

    if said and "|" in reply:
        flag("unverified", "table")
    one = claims[0]["client"] if len(claims) == 1 else None
    for part in _sentences(reply, _SEGMENT, people, default_client=one, today=today):
        days = part["days"]
        for t in times_said(part["text"]):
            cands = [c for c in claims if c["time"] == t]
            if not cands:
                flag("differs", f"time {t} not on the calendar")
                continue
            # Whoever it is about, a time on a day the calendar doesn't have
            # it is wrong.
            if days and not any(c["date"] in days for c in cands):
                flag("differs", f"{t} said on the wrong day")
                continue
            if part["stranger"]:
                flag("unverified", f"{t} said in a sentence about someone the records don't hold")
                continue
            subject = part["subject"]
            if subject is None:
                flag("unverified", f"{t}: who it is with is unclear")
                continue
            if subject not in ("business", "business?"):
                cands = [c for c in cands if c["client"] in subject or c["title"] in subject
                         or c["client"] is None]
                if not cands:
                    flag("differs", f"{t} said for the wrong client")
                    continue
            if days and not any(c["date"] in days for c in cands):
                flag("differs", f"{t} said on the wrong day")
        for n, kind in _counts_said(part["text"]):
            if kind == "session" and q.form == "day" and n != facts.get("count"):
                flag("differs", f"count {n}")
        if q.form == "day" and facts.get("day") and days and facts["day"] not in days \
                and (times_said(part["text"]) or _counts_said(part["text"])):
            flag("differs", "wrong day")
    worst = _worst(problems)
    if answer.empty:
        if worst or said:
            return (worst or "differs"), detail
        return ("agrees" if _NONE_SAID.search(reply) else "silent"), detail
    if worst:
        return worst, detail
    if not said:
        return "silent", detail
    want = {c["time"] for c in claims}
    return ("agrees" if want <= set(said) else "partial"), detail


# ─── Reading ─────────────────────────────────────────────────────────

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _get(path: str) -> Optional[List[Dict[str, Any]]]:
    """A service-role read whose failure log hides the filter values (a
    typed client name rides in the contact search) and the error body."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(path, redact=True)
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


def _contacts(bid: str) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Every contact of the business (id, name), read by its id alone, or
    (None, why): a failed page, or 5,000 contacts or more."""
    rows: List[Dict[str, Any]] = []
    for page in range(CONTACT_PAGES):
        got = _get(f"/contacts?business_id=eq.{bid}&select=id,name&order=id.asc"
                   f"&limit={CONTACT_PAGE}&offset={page * CONTACT_PAGE}")
        if got is None:
            return None, "read_failed"
        rows += got
        if len(got) < CONTACT_PAGE:
            return rows, ""
    return None, "too_many_contacts"


def _contact(bid: str, typed: str, rows: Optional[List[Dict[str, Any]]] = None
             ) -> Tuple[Optional[Dict[str, Any]], str]:
    """The one contact a typed name means, or (None, why). One word matches
    a first or last name; more words must be the name's start.

    The name is matched HERE, never sent: the business's contact list is
    read by its id alone. A name in a query string reaches every logger on
    the way (HTTPX logs each request URL at INFO), and a log is the wrong
    place for a client's name."""
    words = typed.split()
    if rows is None:
        rows, why = _contacts(bid)
        if rows is None:
            return None, why

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
    if len(hits) > 1:
        return None, "name_ambiguous"
    return hits[0], ""


def _usd(rows: List[Dict[str, Any]]) -> bool:
    """Every amount here is in dollars. The rail says "$" and adds amounts
    up; another currency, or a mix, is left to Chief."""
    return all(str(r.get("currency") or "usd").strip().lower() == "usd" for r in rows)


def _chief_rows(rows: List[Dict[str, Any]], today: date, client: Optional[str] = None) -> List[Dict[str, Any]]:
    """Invoice rows in the shape Chief's answer check reads them, aged on
    the BUSINESS's date: at 02:00 UTC it is still yesterday in Detroit, and
    an invoice due yesterday there is not overdue yet."""
    out = []
    for r in rows:
        status = r.get("status") or "draft"
        days = 0
        due = _day(r.get("due_date"))
        if due and status != "draft":
            days = max(0, (today - due).days)
        out.append({
            "id": r.get("id"),
            "number": r.get("invoice_number") or "(no number)",
            "client": client or (((r.get("contacts") or {}).get("name")
                                  if isinstance(r.get("contacts"), dict) else None) or "(no client)"),
            "total": float(_dec(r.get("total"))),
            "status": status,
            "due_date": r.get("due_date") or "",
            "days_overdue": days,
        })
    return out


def _iso(at: datetime) -> str:
    return quote(at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), safe="")


def read(q: Question, bid: str, tz, *, now: Optional[datetime] = None) -> Records:
    """The one read each question shape needs. Fresh every time."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(tz).date()
    rec = Records(today=today)
    if q.name:
        rows, why = _contacts(bid)
        if rows is None:
            return Records(ok=False, why=why)
        rec.contact_names = [str(r.get("name")) for r in rows if r.get("name")]
        rec.contact, why = _contact(bid, q.name, rows)
        if rec.contact is None:
            return Records(ok=False, why=why)
    cid = (rec.contact or {}).get("id")
    if q.shelf == MONEY:
        if cid:
            name = rec.contact.get("name")
            # Every open invoice of theirs (a short list, or it is Chief's),
            # and only their latest payment: no page of history can hide an
            # older unpaid one.
            rows = _get(f"/invoices?business_id=eq.{bid}&contact_id=eq.{cid}"
                        f"&status=in.(sent,viewed,overdue)"
                        f"&select=id,invoice_number,total,status,due_date,currency"
                        f"&order=due_date.asc.nullslast&limit={MAX_CLIENT_OPEN + 1}")
            paid = (_get(f"/invoices?business_id=eq.{bid}&contact_id=eq.{cid}&status=eq.paid"
                         f"&select=invoice_number,total,paid_at,due_date,currency"
                         f"&order=paid_at.desc.nullslast&limit=1") if q.form == "did_pay" else [])
            if rows is None or paid is None:
                return Records(ok=False, why="read_failed")
            if len(rows) > MAX_CLIENT_OPEN:
                return Records(ok=False, why="too_long")
            if not _usd(rows + paid):
                return Records(ok=False, why="currency")
            rec.open_invoices = _chief_rows(rows, today, name)
            rec.paid_invoices = [{"number": r.get("invoice_number"), "client": name,
                                  "total": float(_dec(r.get("total"))), "status": "paid",
                                  "paid_at": r.get("paid_at"), "due_date": r.get("due_date") or ""}
                                 for r in paid]
        else:
            rows = _get(f"/invoices?business_id=eq.{bid}&status=in.(draft,sent,viewed,overdue)"
                        f"&select=id,invoice_number,total,status,due_date,currency,contact_id,contacts(name)"
                        f"&order=due_date.asc.nullslast&limit={MAX_OPEN_INVOICES + 1}")
            if rows is None:
                return Records(ok=False, why="read_failed")
            if len(rows) > MAX_OPEN_INVOICES:
                return Records(ok=False, why="too_many_rows")
            if not _usd(rows):
                return Records(ok=False, why="currency")
            rec.open_invoices = _chief_rows(rows, today)
        return rec
    select = "&select=id,title,scheduled_for,contact_id,contacts(name)&order=scheduled_for.asc"
    base = f"/sessions?business_id=eq.{bid}&status=eq.scheduled"
    if q.form == "day":
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
    # The day's read is every session that day when it came back under its
    # limit; the next session is one row, ordered, so it is whole.
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
        if mode() != "practice" or not isinstance(payload, dict):
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
    # Who else the business deals with, so a reply that puts a figure next
    # to another client ("tasha at 10am", in any case) is held to her.
    names = rec.contact_names
    if names is None:
        rows, _ = _contacts(job["bid"])
        names = [str(r.get("name")) for r in rows or [] if r.get("name")]
    answer.facts["contacts"] = names
    outcome, detail = compare(q, answer, job.get("reply") or "")
    if row["chief_wrote"]:
        detail = {**detail, "note": "chief also changed something"}
    row.update(took=True, proof=proof, proof_sources=cited, rail_answer=answer.text[:600],
               rail_facts={"headline": answer.facts.get("headline"), "count": answer.facts.get("count"),
                           "polarity": answer.facts.get("polarity")},
               outcome=outcome, outcome_detail=detail,
               rail_ms=int((time.perf_counter() - started) * 1000))
    return row


def _write(row: Dict[str, Any]) -> None:
    global _skip_db_until, _table_missing_logged
    if time.time() < _skip_db_until:
        return
    try:
        import sb_clients
        # redact: a refused insert's error body echoes the failing row,
        # rail_answer and all.
        ok = bool(sb_clients.sb_post_as_service(f"/{TABLE}", row, redact=True))
    except Exception:
        ok = False
    if not ok:
        _skip_db_until = time.time() + 600
        if not _table_missing_logged:
            _table_missing_logged = True
            print("[rail] chief_rail_practice write failed: is "
                  "supabase/APPLY-2026-10-16-chief-rail-practice.sql applied?", flush=True)


def prune_tick() -> int:
    """Daily (scheduler_lock.gate): practice rows older than RETENTION_DAYS
    go. rail_answer names clients, so the record is kept only as long as
    a graduation decision needs it."""
    import sb_clients
    cut = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat().replace("+00:00", "Z")
    ok = sb_clients.sb_delete_as_service(f"/{TABLE}?created_at=lt.{quote(cut, safe='')}")
    print(f"[rail] practice rows older than {RETENTION_DAYS} days pruned: {'ok' if ok else 'failed'}",
          flush=True)
    return 1 if ok else 0


# ─── The owner's view ────────────────────────────────────────────────

def _pct(vals: List[int], p: float) -> Optional[int]:
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    k = max(1, math.ceil(p / 100.0 * len(vals)))
    return int(vals[min(k, len(vals)) - 1])


_COMPARED = ("agrees", "partial", "differs", "unverified")


def _agreement(outcomes: Dict[str, int]) -> Optional[float]:
    compared = sum(outcomes.get(k, 0) for k in _COMPARED)
    return round(100.0 * outcomes.get("agrees", 0) / compared, 1) if compared else None


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Practice rows → what a graduation decision needs, per shelf and per
    form. Agreement counts PROVED answers only: an answer the prover
    refused is no evidence, however well it matched Chief."""
    out: Dict[str, Any] = {}
    for r in rows:
        s = out.setdefault(r.get("shelf") or "none", {
            "asked": 0, "took": 0, "proved": 0, "proof_failed": 0, "declined": {}, "outcomes": {},
            "forms": {}, "chief_cost_cents_on_took": 0.0, "rail_ms": [], "chief_ms": [],
            "walls_the_rail_answered": 0})
        s["asked"] += 1
        if not r.get("took"):
            why = r.get("decline_reason") or "?"
            s["declined"][why] = s["declined"].get(why, 0) + 1
            continue
        s["took"] += 1
        f = s["forms"].setdefault(r.get("form") or "?", {"took": 0, "proved": 0, "proof_failed": 0,
                                                         "outcomes": {}})
        f["took"] += 1
        s["chief_cost_cents_on_took"] += float(r.get("chief_cost_cents") or 0)
        for k in ("rail_ms", "chief_ms"):
            if isinstance(r.get(k), (int, float)):
                s[k].append(r[k])
        if r.get("proof") not in ("prover", "empty_read"):
            s["proof_failed"] += 1
            f["proof_failed"] += 1
            continue
        s["proved"] += 1
        f["proved"] += 1
        o = r.get("outcome") or "?"
        s["outcomes"][o] = s["outcomes"].get(o, 0) + 1
        f["outcomes"][o] = f["outcomes"].get(o, 0) + 1
        if o == "withheld":
            s["walls_the_rail_answered"] += 1
    for s in out.values():
        s["agreement_pct"] = _agreement(s["outcomes"])
        for f in s["forms"].values():
            f["agreement_pct"] = _agreement(f["outcomes"])
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
    """The rail's practice record, per shelf and form. Owner only. Counts,
    shares and timings; no answers, names or ids."""
    import asyncio
    import sb_clients
    days = max(1, min(int(days or 7), RETENTION_DAYS))
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
