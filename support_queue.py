"""
support_queue.py — the ranking that turns a pile of tickets into a fix queue.

Pure functions, no I/O: everything here answers "what should be fixed next,
and why" from a ticket row plus its triage row. The router does the reading
and writing; this module holds the judgement so it can be tested and, more
importantly, so it can be READ — an operator who disagrees with the order
should be able to see the arithmetic that produced it.

Three ideas:

  - Severity dominates, but age eventually wins. A blocker outranks
    everything. A month-old 'normal' ticket climbs past a fresh one but
    still sits under a real 'high' — nothing rots forever, and nothing
    important gets buried by noise.
  - Repeats count. Three businesses reporting the same problem is a
    different fact from one business reporting it three times, and the
    problem key is what tells them apart.
  - Silence is a defect. A ticket nobody has answered carries its own
    weight, because the failure practitioners actually feel is not a slow
    fix — it is never hearing back.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# --- vocabulary (mirrors the CHECK constraints in
#     supabase/APPLY-2026-09-02-support-fix-queue.sql) -----------------

SEVERITIES = ("blocker", "high", "normal", "low")
FIX_STATES = ("new", "triaged", "queued", "fixing", "shipped",
              "answered", "wont_fix", "duplicate")

# Which lane of the fix queue a state belongs to. The lanes are the whole
# operating procedure in four words: decide, dispatch, watch, tell them.
LANES: Dict[str, str] = {
    "new": "triage",       # nobody has decided anything yet
    "triaged": "ready",    # decided, waiting for a session
    "queued": "fixing",    # a dev task exists
    "fixing": "fixing",    # that dev task is running
    "shipped": "confirm",  # fixed, and the practitioner still does not know
    "answered": "closed",
    "wont_fix": "closed",
    "duplicate": "closed",
}
OPEN_LANES = ("triage", "ready", "fixing", "confirm")

# dev_tasks.status -> the fix_state it implies. The walk-back that stops a
# shipped fix from sitting in "in progress" forever.
DEV_STATUS_TO_FIX_STATE: Dict[str, str] = {
    "queued": "queued",
    "dispatched": "queued",
    "picked_up": "fixing",
    "opened": "fixing",
    "working": "fixing",
    "done": "shipped",
}

# --- severity, guessed ----------------------------------------------
# Deliberately keyword-based and not a model call: triage runs on every
# queue read, must cost nothing, and must give the same answer twice. The
# guess is a starting position — an operator's explicit severity always
# wins, and triaged_by records which one you are looking at.

_BLOCKER_PHRASES = (
    "can't log in", "cant log in", "cannot log in", "can't sign in",
    "cant sign in", "cannot sign in", "locked out", "locked me out",
    "won't load", "wont load", "will not load", "nothing loads",
    "site is down", "app is down", "white screen", "blank screen",
    "lost all", "lost everything", "deleted everything", "data is gone",
    "everything is gone", "charged twice", "double charged",
    "charged me twice", "can't get in", "cant get in",
)
_HIGH_WORDS = (
    "error", "broken", "not working", "not work", "doesn't work",
    "doesnt work", "won't save", "wont save", "doesn't save", "doesnt save",
    "crash",
    "crashed", "failed", "failing", "wrong amount", "missing",
    "stuck", "hangs", "froze", "frozen", "refund", "overcharged",
    "not sending", "didn't send", "didnt send",
)
_LOW_WORDS = (
    "typo", "spelling", "colour", "font", "spacing", "alignment",
    "would be nice", "nice to have", "someday", "suggestion", "idea",
    "cosmetic", "minor",
)


def guess_severity(category: str, subject: str, message: str) -> Tuple[str, str]:
    """(severity, the reason it was chosen). Never raises."""
    text = f"{subject or ''} {message or ''}".lower()
    cat = (category or "general").lower()

    for phrase in _BLOCKER_PHRASES:
        if phrase in text:
            return "blocker", f'said "{phrase}"'

    if cat == "billing":
        return "high", "billing — money is involved"

    if cat == "bug":
        for w in _HIGH_WORDS:
            if w in text:
                return "high", f'a bug report saying "{w}"'
        return "normal", "a bug report"

    if cat == "feature":
        return "low", "a feature idea"

    for w in _LOW_WORDS:
        if w in text:
            return "low", f'cosmetic — "{w}"'

    for w in _HIGH_WORDS:
        if w in text:
            return "high", f'said "{w}"'

    return "normal", f"a {cat} ticket"


# --- the problem key -------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "it", "its", "this", "that", "these", "those", "i", "we", "you",
    "my", "our", "your", "me", "us", "to", "of", "in", "on", "at", "for",
    "with", "from", "by", "as", "so", "if", "when", "then", "there", "here",
    "not", "no", "cant", "cannot", "wont", "doesnt", "didnt", "isnt",
    "have", "has", "had", "do", "does", "did", "get", "got", "just", "now",
    "please", "help", "hi", "hey", "hello", "thanks", "thank", "problem",
    "issue", "something", "anything", "everything", "wrong", "still",
}


def _keywords(text: str, take: int = 3) -> List[str]:
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    kept: List[str] = []
    for w in words:
        if w in _STOPWORDS or w in kept:
            continue
        kept.append(w)
        if len(kept) >= take:
            break
    return sorted(kept)


def problem_key(category: str, subject: str, message: str,
                context: Optional[Dict[str, Any]] = None) -> str:
    """A key two reports of the SAME problem are likely to share.

    Screen plus the three most distinctive words of the subject, sorted so
    word order stops mattering ("booking cancel broken" and "cancel on
    booking is broken" land together). It under-clusters rather than over-
    clusters on purpose: a wrong merge hides a second, different problem,
    while a missed merge only costs one extra row in the list.
    """
    screen = ""
    if isinstance(context, dict):
        screen = re.sub(r"[^a-z0-9]+", "-",
                        str(context.get("screen") or "").lower()).strip("-")
    words = _keywords(subject or "", 3) or _keywords(message or "", 3)
    return ":".join([(category or "general").lower(), screen or "app",
                     "-".join(words) or "unspecified"])


# --- the rank --------------------------------------------------------

SEVERITY_POINTS = {"blocker": 1000, "high": 400, "normal": 120, "low": 30}
AGE_POINTS_PER_DAY = 8
AGE_POINTS_CAP = 240          # 30 days of waiting
REPEAT_POINTS = 60
REPEAT_POINTS_CAP = 300
UNANSWERED_POINTS = 50


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def age_days(created_at: Optional[str], now: Optional[datetime] = None) -> float:
    started = parse_ts(created_at)
    if not started:
        return 0.0
    now = now or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (now - started).total_seconds() / 86400.0)


def rank(ticket: Dict[str, Any], triage: Dict[str, Any], repeats: int = 1,
         now: Optional[datetime] = None) -> Tuple[int, List[str]]:
    """(score, the reasons for it).

    The reasons are for the operator's eyes: a queue that cannot explain
    its own order does not get trusted, and an untrusted queue gets ignored
    in favour of scrolling the raw list — which is the process this is
    replacing.
    """
    severity = (triage.get("severity") or "normal").lower()
    if severity not in SEVERITY_POINTS:
        severity = "normal"
    why: List[str] = [severity]
    score = SEVERITY_POINTS[severity]

    days = age_days(ticket.get("created_at"), now)
    score += min(int(days * AGE_POINTS_PER_DAY), AGE_POINTS_CAP)
    if days >= 1:
        why.append(f"{int(days)}d old")

    extra = max(0, int(repeats) - 1)
    if extra:
        score += min(extra * REPEAT_POINTS, REPEAT_POINTS_CAP)
        why.append(f"{repeats} reports of this")

    if not (triage.get("first_response_at") or ticket.get("replied_at")):
        score += UNANSWERED_POINTS
        why.append("never answered")

    return score, why


def lane_of(fix_state: Optional[str]) -> str:
    return LANES.get((fix_state or "new").lower(), "triage")
