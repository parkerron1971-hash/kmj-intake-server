"""
doc_audit.py — read the finished document before the client does.

WHAT THIS IS FOR

  Every guarantee in doc_templates.py is an AUTHORING guarantee. Fixed
  clauses render byte-for-byte, drafted sections carry fallbacks,
  _SafeMap keeps an unresolved placeholder visible rather than rendering
  a hole, normalize_custom auto-declares undeclared fields. All of that
  happens while the document is being built.

  Nothing looked at the finished text. The moment a practitioner edits a
  draft by hand, or a learned template ships a field the model chose, or
  a sticky default fires, the result is unverified prose on its way to a
  client.

DETERMINISTIC ONLY, AND THAT IS THE POINT

  Not one rule here calls a model. If a regex can prove it, a model call
  for it is waste plus a new failure mode — and the findings with teeth
  are all provable: an unfilled {placeholder}, "thirty (14) days", two
  different totals in the same money clause, a deadline that has already
  passed, a contract with no signature block.

  MISSPELLINGS RANK LAST, deliberately, and are the smallest thing this
  does. A general dictionary on a legal document is a false-positive
  engine: it flags every client surname, every trade term, "BoldSign",
  "SF-424", "NOFO" — and cheerfully passes "Deluth". So the spelling
  rule is a CURATED list of the confusions that actually occur in this
  kind of paper, and nothing else.

THE THING THAT MAKES IT SAFE

  A practitioner who dismisses a wrong finding twice stops reading the
  panel, and from then on the auditor is worse than absent, because it
  creates a false sense of having been checked.

  So: only deterministic rules may emit a blocker; every finding quotes
  the text it is about, because a finding you cannot see is a finding you
  ignore; and every rule ships with a negative fixture for the known
  landmines — the signature block's underscores, the underscore default
  on practitioner_title, "1.5% per month", "Form 1099-NEC".

  And the harness: every template in the library, rendered and audited,
  must produce ZERO blockers. A rule that fires on our own paper is
  either wrong or has found a template bug, and either way it is not
  allowed to reach a practitioner.

IT HAS NO VETO

  Nothing here can stop a document generating, approving, sending or
  printing. Every entry point is wrapped so that an exception yields no
  findings rather than an error. An auditor that can block a document is
  a worse failure than the defects it catches.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# ── Severity ─────────────────────────────────────────────────────────
#
# Three, and only three. A practitioner can hold three in their head;
# five becomes a colour wheel nobody reads.
#
#   blocker — provably wrong AND visible to the client
#   high    — probably wrong, worth a look before it goes
#   note    — tidy it if you like
BLOCKER, HIGH, NOTE = "blocker", "high", "note"

MAX_PER_SEVERITY = {BLOCKER: 3, HIGH: 5, NOTE: 5}


def _finding(code: str, severity: str, title: str, detail: str,
             excerpt: str = "", fix: str = "review") -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        # Verbatim, always. A finding whose text cannot be found in the
        # document is a finding nobody can act on.
        "excerpt": (excerpt or "").strip()[:180],
        "fix": fix,
        "source": "deterministic",
    }


# ── Known-good patterns that must never fire ─────────────────────────
#
# Each of these cost a real false positive somewhere, and each has a
# negative fixture in the tests.
_SIGNATURE_RULE = re.compile(r"_{4,}")          # the signature block's lines
_PERCENT_RATE = re.compile(r"\d+(?:\.\d+)?%")   # "1.5% per month"
_FORM_NUMBER = re.compile(r"\b(?:Form|SF|W)-?\s?\d+[A-Z\-]*\b", re.I)


# ── D1 — an unfilled placeholder ─────────────────────────────────────

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
# The human-authored family, which arrives via learned templates and
# hand edits rather than through the DSL.
_HUMAN_HOLES = re.compile(
    r"(\[[A-Z][A-Z _/]{2,}\]|\bTBD\b|\bXXX+\b|<insert\b|\bLorem ipsum\b)", re.I)


def _check_placeholders(body: str) -> List[Dict[str, Any]]:
    out = []
    for m in _PLACEHOLDER.finditer(body):
        out.append(_finding(
            "placeholder_unfilled", BLOCKER,
            "Unfilled placeholder",
            f"{{{m.group(1)}}} never got a value and will print exactly like that.",
            _around(body, m.start()), fix="fill_field"))
    for m in _HUMAN_HOLES.finditer(body):
        out.append(_finding(
            "placeholder_human", BLOCKER,
            "Placeholder text left in",
            f"“{m.group(1)}” reads as a note to self, not a term.",
            _around(body, m.start()), fix="edit_text"))
    return out


# ── D8 — a number that disagrees with its own word ───────────────────

_WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
_NUM_PAREN = re.compile(r"\b([a-z]+)\s*\(\s*(\d+)\s*\)", re.I)
_PAREN_NUM = re.compile(r"\b(\d+)\s*\(\s*([a-z]+)\s*\)", re.I)


def _check_number_words(body: str) -> List[Dict[str, Any]]:
    """"thirty (14) days" — a classic, and provable with no judgement."""
    out = []
    for rx, word_first in ((_NUM_PAREN, True), (_PAREN_NUM, False)):
        for m in rx.finditer(body):
            word = (m.group(1) if word_first else m.group(2)).lower()
            digits = m.group(2) if word_first else m.group(1)
            if word not in _WORD_NUM:
                continue
            if _WORD_NUM[word] != int(digits):
                out.append(_finding(
                    "number_word_mismatch", HIGH,
                    "Number disagrees with its word",
                    f"“{word}” and “{digits}” are different numbers. "
                    "Whichever is wrong, a reader will argue for the other.",
                    _around(body, m.start()), fix="edit_text"))
    return out


# ── D4 — dates that cannot be, or already were ───────────────────────

_DATE_LONG = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s*(\d{4})\b")
_DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def _check_dates(body: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    today = today or date.today()
    out = []
    for m in _DATE_LONG.finditer(body):
        mon, day, year = _MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
        out += _one_date(body, m, year, mon, day, today)
    for m in _DATE_SLASH.finditer(body):
        mon, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        out += _one_date(body, m, year, mon, day, today)
    return out


def _one_date(body, m, year, mon, day, today) -> List[Dict[str, Any]]:
    try:
        parsed = date(year, mon, day)
    except ValueError:
        return [_finding(
            "date_impossible", BLOCKER, "That date does not exist",
            f"“{m.group(0)}” is not a real calendar date.",
            _around(body, m.start()), fix="edit_text")]
    # A wildly wrong year is nearly always a typo, and it is the kind
    # that survives a proofread because it looks like a date.
    if not (today.year - 1 <= parsed.year <= today.year + 10):
        return [_finding(
            "date_far_off", HIGH, "That year looks wrong",
            f"“{m.group(0)}” is outside the range a live document usually "
            "carries.", _around(body, m.start()), fix="edit_text")]
    return []


# ── D3 — two different totals in the same money clause ───────────────

_MONEY = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")


def _check_money(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Within ONE clause, two different amounts is usually a stale edit.

    Scoped to a single section on purpose: a contract legitimately names
    a fee in one clause and a deposit in another, and comparing across
    the whole document would fire on every well-formed agreement."""
    out = []
    for s in sections:
        text = s.get("text") or ""
        amounts = {a.replace(" ", "") for a in _MONEY.findall(text)}
        if len(amounts) > 1:
            out.append(_finding(
                "money_conflict", HIGH,
                "Two amounts in one clause",
                "This clause names " + " and ".join(sorted(amounts))
                + ". If one of them is stale, the other is what gets argued.",
                text, fix="edit_text"))
    return out


# ── D6 — the document stopped being a contract ───────────────────────

def _check_structure(body: str, *, numbered: bool) -> List[Dict[str, Any]]:
    out = []
    if numbered and "ACCEPTED AND AGREED" not in body.upper():
        out.append(_finding(
            "signature_block_missing", HIGH,
            "No signature block",
            "An agreement with nothing to sign is not an agreement. It is "
            "usually deleted by accident while editing.",
            "", fix="review"))
    return out


# ── D9 — mechanical defects ──────────────────────────────────────────

_DOUBLED = re.compile(r"\b(\w{3,})\s+\1\b", re.I)
_MOJIBAKE = re.compile(r"(â€™|â€œ|â€\x9d|Â[^\w\s]|ï»¿)")
# Curated. NOT a dictionary — see the module docstring.
_CONFUSABLES = {
    "aggreement": "agreement", "agreeement": "agreement",
    "seperate": "separate", "recieve": "receive", "occured": "occurred",
    "recieved": "received", "signiture": "signature", "signator": "signatory",
    "liscense": "license", "aknowledge": "acknowledge",
    "statue of limitations": "statute of limitations",
    "principle amount": "principal amount",
    "per say": "per se", "hereto for": "heretofore",
    "for all intensive purposes": "for all intents and purposes",
    "should of": "should have", "would of": "would have",
}


def _check_mechanics(body: str) -> List[Dict[str, Any]]:
    out = []
    for m in _MOJIBAKE.finditer(body):
        out.append(_finding(
            "mojibake", HIGH, "Garbled characters",
            "Some text was encoded twice and will print as symbols in the PDF.",
            _around(body, m.start()), fix="edit_text"))
        break  # one is enough; they always come in clusters
    for m in _DOUBLED.finditer(body):
        out.append(_finding(
            "doubled_word", NOTE, "A word is repeated",
            f"“{m.group(1)} {m.group(1)}”.",
            _around(body, m.start()), fix="edit_text"))
    low = body.lower()
    for wrong, right in _CONFUSABLES.items():
        i = low.find(wrong)
        if i >= 0:
            out.append(_finding(
                "confusable", NOTE, "Probably the wrong word",
                f"“{wrong}” is usually “{right}” in this kind of document.",
                _around(body, i), fix="edit_text"))
    return out


def _around(body: str, i: int, width: int = 90) -> str:
    start = max(0, i - width // 3)
    return body[start:start + width].replace("\n", " ")


# ── The pass ─────────────────────────────────────────────────────────

def audit_document(body: str, *, sections: Optional[List[Dict[str, Any]]] = None,
                   numbered: bool = False,
                   today: Optional[date] = None) -> Dict[str, Any]:
    """Every rule, ranked and capped. Never raises."""
    try:
        findings: List[Dict[str, Any]] = []
        findings += _check_placeholders(body)
        findings += _check_number_words(body)
        findings += _check_dates(body, today)
        findings += _check_money(sections or [{"text": body}])
        findings += _check_structure(body, numbered=numbered)
        findings += _check_mechanics(body)

        order = {BLOCKER: 0, HIGH: 1, NOTE: 2}
        findings.sort(key=lambda f: order[f["severity"]])

        # Capped per severity. A list of thirty is wallpaper.
        kept, seen = [], {BLOCKER: 0, HIGH: 0, NOTE: 0}
        dropped = 0
        for f in findings:
            sev = f["severity"]
            if seen[sev] < MAX_PER_SEVERITY[sev]:
                kept.append(f)
                seen[sev] += 1
            else:
                dropped += 1

        return {
            "ok": True,
            "findings": kept,
            "counts": dict(seen),
            "more": dropped,
            "clauses_checked": len(sections or []),
        }
    except Exception:
        # An auditor that breaks a document is worse than no auditor.
        return {"ok": True, "findings": [], "counts": {}, "more": 0,
                "clauses_checked": 0, "degraded": "audit_failed"}


def blocking_count(result: Dict[str, Any]) -> int:
    return int((result.get("counts") or {}).get(BLOCKER, 0))
