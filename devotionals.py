"""
devotionals.py — a church's own devotionals, written in Solutionist and
read in the member app.

Kevin, 2026-10-19 (round three of the member app, approved on the "Member
App, Round Three" canvas, boards 10 and 11): the Bible needs "reading plans
plus church-made personal devotionals". His own "Consecrate Your Focus"
(seven days for Focus Week) is the shape this follows: a welcome, the daily
practices every day shares (First Look, One Thing, ...), then each day's
title, scripture, words, a line to hold on to, a prayer, something to do
today and something to do together.

A devotional is one row (devotionals; APPLY-2026-10-19-devotionals.sql):

    title, kind ("Focus Week"), author ("Pastor Kevin McCloud Jr."), about
    practices   [{key, title, sub}]  the daily checklist, at most 8
    days        [{title, scripture, body, pull, pray, act, together, journal}]
    starts_on   the church reads it together from this date (one day a
                day, everyone on the same page); empty = each member
                starts it on their own day
    voice       who reads it aloud when a member taps Listen
                (devotional_voice.py; one of Kevin's featured voices)
    status      draft | published (members see published ones only)

Staff (owner, admin, manager) write them; any seat reads the list:

    GET    /church/devotionals?business_id=          the church's devotionals
    GET    /church/devotionals/{id}?business_id=     one, with its days
    POST   /church/devotionals                       a new draft
    PUT    /church/devotionals/{id}                  save
    POST   /church/devotionals/{id}/publish          {publish: true|false}
    DELETE /church/devotionals/{id}?business_id=
    POST   /church/devotionals/read-paste            a whole devotional pasted
                                                     in, read into fields
                                                     (nothing is saved)

What members do with them is member_portal_devotionals.py.
"""
from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user
from business_access import assert_access

logger = logging.getLogger("devotionals")
router = APIRouter(prefix="/church", tags=["church"])

STAFF_ROLES = ("owner", "admin", "manager")
DAYS_MAX = 90
PRACTICES_MAX = 8
TOTAL_MAX = 600_000          # the days, as stored (the table says the same)
VOICES = ("grace", "elijah", "jessica", "reed")
DEFAULT_VOICE = "grace"
# Each field of a day and its longest.
DAY_FIELDS: Dict[str, int] = {"title": 120, "scripture": 120, "body": 12000, "pull": 400,
                              "pray": 2000, "act": 2000, "together": 1000, "journal": 300}
LIMITS = {"title": 120, "kind": 60, "author": 120, "about": 6000}
_META = "id,business_id,title,kind,author,about,practices,day_count,starts_on,voice,status,published_at,updated_at"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


# ─── reading one ─────────────────────────────────────────────────────


def catalog(business_id: str, *, published: bool = True) -> Optional[List[Dict[str, Any]]]:
    """The church's devotionals without their days (newest first), or None
    when the read failed."""
    status = "&status=eq.published" if published else ""
    rows = sb_clients.sb_get_as_service(
        f"/devotionals?business_id=eq.{_q(business_id)}{status}&select={_META}"
        f"&order=starts_on.desc.nullslast,published_at.desc.nullslast,updated_at.desc&limit=100")
    if not isinstance(rows, list):
        return None
    return [_dated(r) for r in rows]


def one(business_id: str, devotional_id: str, *, published: bool = True) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the devotional with its days, read ok). (None, True) = there is no
    such devotional (or it isn't published); (None, False) = the read
    failed."""
    if not _UUID.fullmatch(str(devotional_id or "")):
        return None, True
    status = "&status=eq.published" if published else ""
    rows = sb_clients.sb_get_as_service(
        f"/devotionals?id=eq.{_q(devotional_id)}&business_id=eq.{_q(business_id)}{status}"
        f"&select={_META},days,audio&limit=1")
    if not isinstance(rows, list):
        return None, False
    return (_dated(rows[0]) if rows else None), True


def _dated(row: Dict[str, Any]) -> Dict[str, Any]:
    """starts_on as a date (or None)."""
    out = dict(row)
    try:
        out["starts_on"] = date.fromisoformat(str(row.get("starts_on"))) if row.get("starts_on") else None
    except ValueError:
        out["starts_on"] = None
    return out


# ─── a day at a time ─────────────────────────────────────────────────


def run_start(dev: Dict[str, Any], started_on: Optional[date]) -> Optional[date]:
    """Day 1's date: the church's start date, or the member's own."""
    return dev.get("starts_on") or started_on


def day_number(start: Optional[date], count: int, today: Optional[date] = None) -> Optional[int]:
    """Today's day of the devotional, or None before it starts or after it
    ends."""
    if not start:
        return None
    n = ((today or date.today()) - start).days + 1
    return n if 1 <= n <= count else None


def open_upto(start: Optional[date], count: int, today: Optional[date] = None) -> int:
    """The days that are open: one a day from day 1, every day once it's
    over; 0 before it starts (or before a member starts their own)."""
    if not start:
        return 0
    return max(0, min(count, ((today or date.today()) - start).days + 1))


def day_on(start: date, n: int) -> date:
    return start + timedelta(days=n - 1)


def minutes(day: Dict[str, Any]) -> int:
    """About how long a day takes to read: its words at ~170 a minute."""
    words = sum(len(str(day.get(k) or "").split()) for k in ("body", "pull", "pray", "act", "together", "journal"))
    return max(2, round(words / 170 + 1))


def streak(done: set, upto: int) -> int:
    """Days done in a row, back from the last open day (or the one before,
    if today's isn't done yet)."""
    n = upto if upto in done else upto - 1
    out = 0
    while n >= 1 and n in done:
        out += 1
        n -= 1
    return out


def paragraphs(text: str) -> List[str]:
    """A day's words as paragraphs: split at blank lines; single line
    breaks inside a paragraph are kept as spaces."""
    parts = re.split(r"\n\s*\n", str(text or "").replace("\r\n", "\n").strip())
    return [re.sub(r"\s*\n\s*", " ", p).strip() for p in parts if p.strip()]


# ─── what staff save, checked ────────────────────────────────────────


def _text(raw: Any, cap: int, what: str) -> str:
    t = str(raw if raw is not None else "").replace("\r\n", "\n").strip()
    if len(t) > cap:
        raise ValueError(f"{what} can be at most {cap:,} characters.")
    return t


def clean_practices(raw: Any) -> List[Dict[str, str]]:
    """The daily checklist: [{key, title, sub}], at most 8, each with a
    title. A practice keeps its key (so a member's ticks stay put when its
    words change); a new one gets one."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("The daily practices didn't come through. Try again.")
    out: List[Dict[str, str]] = []
    keys = set()
    for p in raw:
        if not isinstance(p, dict):
            continue
        title = _text(p.get("title"), 60, "A practice's name")
        if not title:
            continue
        sub = _text(p.get("sub"), 120, "A practice's note")
        key = str(p.get("key") or "")
        if not re.fullmatch(r"[a-z0-9]{6,16}", key) or key in keys:
            key = secrets.token_hex(4)
        keys.add(key)
        out.append({"key": key, "title": title, "sub": sub})
    if len(out) > PRACTICES_MAX:
        raise ValueError(f"A devotional can have at most {PRACTICES_MAX} daily practices.")
    return out


def clean_days(raw: Any) -> List[Dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("The days didn't come through. Try again.")
    if len(raw) > DAYS_MAX:
        raise ValueError(f"A devotional can have at most {DAYS_MAX} days.")
    out = []
    for i, d in enumerate(raw, 1):
        d = d if isinstance(d, dict) else {}
        out.append({k: _text(d.get(k), cap, f"Day {i}'s {LABELS[k].lower()}") for k, cap in DAY_FIELDS.items()})
    import json
    if len(json.dumps(out, ensure_ascii=False).encode("utf-8")) > TOTAL_MAX:
        raise ValueError("This devotional is too long to save. Shorten some of its days.")
    return out


LABELS = {"title": "Title", "scripture": "Scripture", "body": "Words", "pull": "Line to hold on to",
          "pray": "Prayer", "act": "Do today", "together": "Together", "journal": "Journal question"}


def clean(body: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """A devotional's fields from Solutionist, checked. ValueError carries
    the words to show. `partial`: only the fields sent."""
    out: Dict[str, Any] = {}
    for k, cap in LIMITS.items():
        if k in body or (not partial and k == "title"):
            out[k] = _text(body.get(k), cap, {"title": "The title", "kind": "The kind", "author": "The author",
                                              "about": "The welcome"}[k])
    if "title" in out and not out["title"]:
        raise ValueError("Give the devotional a title.")
    if "practices" in body:
        out["practices"] = clean_practices(body.get("practices"))
    if "days" in body:
        out["days"] = clean_days(body.get("days"))
    if "starts_on" in body:
        raw = body.get("starts_on")
        if raw in (None, ""):
            out["starts_on"] = None
        else:
            try:
                start = date.fromisoformat(str(raw))
            except ValueError:
                raise ValueError("Choose a start date, or leave it empty so each member starts on their own day.")
            if abs((start - date.today()).days) > 400:
                raise ValueError("Choose a start date within a year of today.")
            out["starts_on"] = start.isoformat()
    if "voice" in body:
        v = str(body.get("voice") or DEFAULT_VOICE)
        if v not in VOICES:
            raise ValueError("Choose one of the voices.")
        out["voice"] = v
    return out


def ready(dev: Dict[str, Any]) -> Optional[str]:
    """Why a devotional can't go out yet, or None when it can."""
    days = dev.get("days") or []
    if not days:
        return "Add at least one day before it goes out."
    for i, d in enumerate(days, 1):
        if not str(d.get("title") or "").strip():
            return f"Day {i} needs a title before it goes out."
        if not (str(d.get("body") or "").strip() or str(d.get("scripture") or "").strip()):
            return f"Day {i} needs its words or a scripture before it goes out."
    return None


# ─── a whole devotional, pasted in ───────────────────────────────────
# A church usually has its devotional written already, in a document. Pasted
# in, it is read into fields the way Kevin's "Consecrate Your Focus" is set
# out: a title, a welcome, the practices as "First Look (morning, before your
# phone)." lines, then "Day 1, Monday: Not Here Before", the day's scripture
# in quotes ending with its reference, the words, and "Pray:", "Do today:",
# "Together:", "Journal:" lines. Nothing is saved; the team checks every
# field before saving.
# A real document, copied, is looser than that: a "date · name" byline,
# section headings, tables (tab-separated), the practices as numbered
# anchors that run on ("1. First Look (morning, before your phone). Your
# first look…"), and after the last day a "Your Daily Checklist" and a closing
# word. So the welcome is the first section's own words; the practices are a
# checklist section's lines when there is one, else the anchors; and a day
# ends at a heading once its Pray/Do today/Together/Journal lines have begun,
# or where one of those labels comes round again.

_DAY_HEAD = re.compile(r"^\s*(?:#+\s*)?day\s+(\d{1,2})\b\s*(?:[,(][^:–—\-]*?)?\s*(?:[:.–—\-]\s*(.*?))?\s*$", re.I)
_LABELLED = (("pray", re.compile(r"^\s*(?:\*\*)?(?:pray|prayer)(?:\*\*)?\s*[:\-–—]\s*(?:\*\*)?\s*(.*)$", re.I)),
             ("act", re.compile(r"^\s*(?:\*\*)?(?:do today|do this today|do|today|action|apply)(?:\*\*)?\s*[:\-–—]\s*(?:\*\*)?\s*(.*)$", re.I)),
             ("together", re.compile(r"^\s*(?:\*\*)?together(?:\*\*)?\s*[:\-–—]\s*(?:\*\*)?\s*(.*)$", re.I)),
             ("journal", re.compile(r"^\s*(?:\*\*)?(?:journal|reflect|reflection|write)(?:\*\*)?\s*[:\-–—]\s*(?:\*\*)?\s*(.*)$", re.I)),
             ("scripture", re.compile(r"^\s*(?:\*\*)?(?:scripture|read|verse)(?:\*\*)?\s*[:\-–—]\s*(?:\*\*)?\s*(.*)$", re.I)))
_QUOTED = re.compile(r'^\s*>?\s*["“](.+)["”]\s*[(\-–—]?\s*([1-3]?\s?[A-Za-z][A-Za-z .]+?\s\d{1,3}(?::\d{1,3}(?:\s?[-–]\s?\d{1,3})?)?)\)?\s*\.?\s*$')
_MARK = r"(?:[-*•◦▪]\s*|\[[ xX]?\]\s*|[☐☑✓✔]\s*|\d{1,2}[.)]\s+)"
_NAME = r"(?:\*\*)?([A-Z][\w’']*(?:\s[A-Za-z][\w’']*){0,3})"
_PRACTICE = re.compile(rf"^\s*{_MARK}?{_NAME}\s*\(([^)]{{2,80}})\)\s*\.?\s*(?:\*\*)?\s*$")
# "1. First Look (morning, before your phone). Your first look goes to God…"
_ANCHOR = re.compile(rf"^\s*{_MARK}?{_NAME}\s*\(([^)]{{2,80}})\)\.(?:\*\*)?\s+\S")
# a checklist line: "First Look: verse, prayer, and one ask", "- [ ] One Thing – 25 minutes"
_ITEM = re.compile(rf"^\s*{_MARK}?(?:\*\*)?([A-Z][^:–—]{{0,58}}?)(?:\*\*)?\s*(?::|\s[–—-]\s)\s*(.+)$")
_LISTS = re.compile(r"\b(?:check\s?list|practices|daily rhythm|every day|each day)\b", re.I)
_LABEL_ONLY = re.compile(r"^(?:pray|prayer|do today|together|journal|reflect|reflection|scripture|read|verse)$", re.I)
_DAY_LABELS = ("pray", "act", "together", "journal")


def _ref(text: str) -> str:
    """'Proverbs 4:25' when the words name a passage the Bible here can
    find, else ''."""
    import bible_text as bt
    found = bt.find_refs(text or "")
    return found[0][2].label() if found else ""


def _heading(line: str) -> bool:
    """A line that reads as a section's heading: "## Notes", or a short line
    with no closing punctuation and no colon ("Your Daily Checklist", "A
    closing charge", a "date · name" byline)."""
    s = line.strip()
    if s.startswith("#"):
        return bool(s.lstrip("#").strip())
    s = s.strip("*").strip()
    if (not s or "\t" in s or ":" in s or len(s) > 70 or len(s.split()) > 10
            or s[-1] in ".!?,;\"”’')" or not (s[0].isupper() or s[0].isdigit())):
        return False
    return not (_LABEL_ONLY.match(s) or re.match(_MARK, s) or _QUOTED.match(s))


def _sections(lines: List[str]) -> List[Tuple[str, List[str]]]:
    """[(heading, its lines)]; the lines before the first heading come under ''."""
    out: List[Tuple[str, List[str]]] = [("", [])]
    for ln in lines:
        if _heading(ln):
            out.append((ln.strip().lstrip("#").strip().strip("*").strip(), []))
        else:
            out[-1][1].append(ln)
    return out


def _practice(title: str, sub: str) -> Dict[str, str]:
    sub = sub.strip().strip("*").strip()
    return {"title": title.strip().strip("*").strip()[:60], "sub": (sub[:1].upper() + sub[1:])[:120]}


def _anchor(line: str) -> Optional[Dict[str, str]]:
    """'First Look (morning, before your phone).', on its own or running on."""
    s = line.strip()
    m = (_PRACTICE.match(s) if len(s) <= 90 else None) or _ANCHOR.match(s)
    return _practice(m.group(1), m.group(2)) if m else None


def _checklist(lines: List[str]) -> List[Dict[str, str]]:
    """A checklist section's practices: "Title: what it is", "Title (when)",
    or a listed "- Title"; its other words (an intro line) are left."""
    out: List[Dict[str, str]] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        got = _anchor(s)
        if not got:
            m = _ITEM.match(s)
            if m and len(m.group(1).split()) <= 5:
                got = _practice(m.group(1), m.group(2))
            elif re.match(_MARK, s) and len(s) <= 64 and s[-1] not in ".!?":
                got = _practice(re.sub(rf"^{_MARK}", "", s), "")
        if got and got["title"]:
            out.append(got)
        if len(out) >= PRACTICES_MAX:
            break
    return out


def _day_over(day: Dict[str, str], rest: List[str]) -> bool:
    """At a heading inside a day: the day is over once its Pray/Do today/
    Together/Journal lines have begun and none still to come is new (so an
    "Amen" on its own line doesn't end it before its "Do today")."""
    if not any(day[k] for k in _DAY_LABELS):
        return False
    for ln in rest:
        k = next((k for k, rx in _LABELLED if rx.match(ln.strip())), None)
        if k in _DAY_LABELS and not day[k]:
            return False
    return True


def _kind(raw: str) -> str:
    """The title's "Focus Week" after a colon. A "7-Day Devotional" says
    nothing the page doesn't (it reads "7-day devotional · <kind>")."""
    k = raw.strip()
    if not k or len(k) > 60:
        return ""
    k = re.sub(r"^(?:an?\s+)?\d{1,3}[\s-]?days?\b\s*", "", k, flags=re.I).strip()
    return "" if k.lower() in ("devotional", "devotion", "devotional plan") else k


def parse(text: str) -> Dict[str, Any]:
    """{title, kind, about, practices, days} read from pasted text; days is
    [] when no "Day 1" heading was found."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    heads = [i for i, ln in enumerate(lines) if _DAY_HEAD.match(ln)]
    pre = lines[:heads[0]] if heads else lines
    out: Dict[str, Any] = {"title": "", "kind": "", "about": "", "practices": [], "days": []}
    for i, ln in enumerate(pre):
        s = ln.strip().lstrip("#").strip().strip("*").strip()
        if s:
            title, _, kind = s.partition(":")
            out["title"] = title.strip()[:120]
            out["kind"] = _kind(kind)
            pre = pre[i + 1:]
            break
    intro = _sections(pre)
    # the welcome: the first section with words of its own (a byline or a heading alone has none)
    for head, ls in intro:
        if head and _LISTS.search(head):
            continue
        paras = paragraphs("\n".join(ln for ln in ls if "\t" not in ln and not _anchor(ln)))
        if paras:
            out["about"] = "\n\n".join(paras)[:LIMITS["about"]]
            break
    anchors = [p for p in (_anchor(ln) for ln in pre) if p][:PRACTICES_MAX]
    after: List[str] = []    # what follows a day's own lines: a checklist, a closing word
    for at, start in enumerate(heads):
        end = heads[at + 1] if at + 1 < len(heads) else len(lines)
        m = _DAY_HEAD.match(lines[start])
        day = {k: "" for k in DAY_FIELDS}
        day["title"] = (m.group(2) or "").strip().strip("*").strip()[:120]
        words: List[str] = []
        last = None
        for i in range(start + 1, end):
            s = lines[i].strip()
            if not s:
                words.append("")
                last = None
                continue
            hit = next(((k, rx.match(s)) for k, rx in _LABELLED if rx.match(s)), None)
            if ((last is None and _heading(s) and _day_over(day, lines[i + 1:end]))
                    or (hit and hit[0] in _DAY_LABELS and day[hit[0]])):
                after.extend(lines[i:end])
                break
            if hit:
                k, mm = hit
                value = mm.group(1).strip()
                day[k] = (_ref(value) or value[:120]) if k == "scripture" else value
                last = k
                continue
            if not day["scripture"]:
                q = _QUOTED.match(s)
                ref = _ref(q.group(2)) if q else ""
                if ref:
                    day["scripture"] = ref
                    continue
            if last and last != "scripture":
                day[last] = (day[last] + " " + s).strip()
                continue
            words.append(s)
        body = paragraphs("\n".join(words))
        if len(body) >= 2 and len(body[-1]) <= 160:
            day["pull"] = body.pop()
        day["body"] = "\n\n".join(body)
        for k, cap in DAY_FIELDS.items():
            day[k] = day[k][:cap]
        out["days"].append(day)
        if len(out["days"]) >= DAYS_MAX:
            break
    listed = next((got for head, ls in intro + _sections(after)
                   if head and _LISTS.search(head) for got in [_checklist(ls)] if got), [])
    out["practices"] = listed or anchors
    return out


# ─── staff ───────────────────────────────────────────────────────────


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _seat(biz: str, user: AuthedUser) -> str:
    """The caller's role on the church, through the one access check
    (business_access.assert_access: 404 for no seat, 503 when it can't
    run)."""
    return assert_access(biz, user)


def _staff(biz: str, user: AuthedUser) -> None:
    if _seat(biz, user) not in STAFF_ROLES:
        raise HTTPException(403, "Only the owner, an admin or a manager writes devotionals")


def _voices() -> List[Dict[str, str]]:
    import whisper_proxy as wp
    return [{"id": k, "label": wp.INWORLD_VOICES[k].label, "about": wp.INWORLD_VOICES[k].desc} for k in VOICES]


def _out(row: Dict[str, Any], *, days: bool = False) -> Dict[str, Any]:
    o = {k: row.get(k) for k in ("id", "title", "kind", "author", "about", "practices", "day_count", "voice",
                                 "status", "published_at", "updated_at")}
    o["starts_on"] = row["starts_on"].isoformat() if isinstance(row.get("starts_on"), date) else row.get("starts_on")
    if days:
        o["days"] = row.get("days") or []
    return o


def _get_or_404(biz: str, dev_id: str) -> Dict[str, Any]:
    row, ok = one(biz, dev_id, published=False)
    if not ok:
        raise HTTPException(503, "The devotional couldn't be read. Try again.")
    if not row:
        raise HTTPException(404, "devotional not found")
    return row


@router.get("/devotionals")
def list_devotionals(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    role = assert_access(biz, user)
    rows = catalog(biz, published=False)
    if rows is None:
        raise HTTPException(503, "The devotionals couldn't be read. Try again.")
    import devotional_voice as dv
    return {"devotionals": [_out(r) for r in rows], "voices": _voices(), "listen": dv.can_speak(),
            "can_write": role in STAFF_ROLES}


@router.get("/devotionals/{devotional_id}")
def get_devotional(devotional_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    assert_access(biz, user)
    return {"devotional": _out(_get_or_404(biz, _uuid(devotional_id, "devotional")), days=True)}


@router.post("/devotionals")
def create_devotional(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    try:
        fields = clean(body or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    now = datetime.now(timezone.utc).isoformat()
    rows = sb_clients.sb_post_as_service("/devotionals", {**fields, "business_id": biz, "status": "draft",
                                                          "created_at": now, "updated_at": now},
                                         prefer="return=representation")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"ok": True, "devotional": _out(_dated(rows[0]), days=True)}


@router.put("/devotionals/{devotional_id}")
def save_devotional(devotional_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    dev_id = _uuid(devotional_id, "devotional")
    current = _get_or_404(biz, dev_id)
    try:
        fields = clean(body or {}, partial=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if current.get("status") == "published":
        # It's out: it can't be saved into something that couldn't go out.
        why = ready({**current, **fields})
        if why:
            raise HTTPException(400, why + " It's published, so take it down first to save it unfinished.")
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    rows = sb_clients.sb_patch_as_service(
        f"/devotionals?id=eq.{_q(dev_id)}&business_id=eq.{_q(biz)}&select={_META},days", fields)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "devotional": _out(_dated(rows[0]), days=True)}


@router.post("/devotionals/{devotional_id}/publish")
def publish_devotional(devotional_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    dev_id = _uuid(devotional_id, "devotional")
    current = _get_or_404(biz, dev_id)
    publish = bool((body or {}).get("publish"))
    if publish:
        why = ready(current)
        if why:
            raise HTTPException(400, why)
    now = datetime.now(timezone.utc).isoformat()
    change: Dict[str, Any] = {"status": "published" if publish else "draft", "updated_at": now}
    if publish and current.get("status") != "published":
        change["published_at"] = now
    rows = sb_clients.sb_patch_as_service(
        f"/devotionals?id=eq.{_q(dev_id)}&business_id=eq.{_q(biz)}&select={_META}", change)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "devotional": _out(_dated(rows[0]))}


@router.delete("/devotionals/{devotional_id}")
def delete_devotional(devotional_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user)
    dev_id = _uuid(devotional_id, "devotional")
    current = _get_or_404(biz, dev_id)
    if not sb_clients.sb_delete_as_service(f"/devotionals?id=eq.{_q(dev_id)}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "That didn't delete. Try again.")
    # Members' days and journals went with it (the table cascades); the
    # plans they started on their own, and its Listen files, go now.
    sb_clients.sb_delete_as_service(
        f"/member_plan_starts?business_id=eq.{_q(biz)}&plan=eq.{_q('devotional:' + dev_id)}")
    import devotional_voice as dv
    dv.forget(current)
    return {"ok": True}


@router.post("/devotionals/read-paste")
def read_paste(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    text = str((body or {}).get("text") or "")
    if not text.strip():
        raise HTTPException(400, "Paste the devotional in first.")
    if len(text) > 200_000:
        raise HTTPException(400, "That's too much to read at once. Paste up to about 30 days at a time.")
    got = parse(text)
    if not got["days"]:
        raise HTTPException(400, 'No days were found. Start each day on its own line with "Day 1", "Day 2" and so on.')
    return {"ok": True, "found": got}
