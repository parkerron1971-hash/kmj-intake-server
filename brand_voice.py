"""The Solutionist voice, as rules a test can hold the public pages to.

Kevin, 2026-10-22, after the brand page ("Solutionist Brand and Markets",
https://claude.ai/artifact/Y6DSyYpqVP7FJ9KhTXD2HU): "build the voice system
to function properly as suggested". The voice is four things:

  * plain: the words a pastor or a client would use;
  * specific: names and numbers, not adjectives;
  * warm: calm, no hype, no exclamation points;
  * done: say what got handled, in the past tense.

Only the word list can be checked by a machine, so that is what lives here.
AVOID is the list; offenses() finds them in what a visitor actually reads
(text, the labels a screen reader speaks, and the prose inside the page's
scripts, never class names, ids or URL parameters). The test in
__tests__/test_brand_voice.py runs it over every front page.

"Trade" is out because the business is sold to churches and practices, not
trades. "Software" is out because it is a system. Chief is Chief, never an
"AI agent" or "AI assistant": the brief that set the position (Duet tells you
what needs attention; Solutionist gets it handled) moved the assistant
framing out of the hero on purpose.
"""
from __future__ import annotations

import html as _html
import re
from typing import List, Tuple

# (pattern, what to say instead). Patterns are case-insensitive and whole-word.
AVOID: Tuple[Tuple[str, str], ...] = (
    (r"\btrades?\b", "the work you do, or the kind of business"),
    (r"\bsoftware\b", "system"),
    (r"\bAI (?:agents?|assistants?|chief of staff)\b", "Chief"),
    (r"\bco-?pilots?\b", "Chief"),
    (r"\bseamless(?:ly)?\b", "say what happens"),
    (r"\brevolutionar(?:y|ize|izes)\b", "say what it does"),
    (r"\bgame[- ]chang(?:er|ers|ing)\b", "say what it does"),
)

_AVOID_RE = [(re.compile(p, re.I), say) for p, say in AVOID]

# Attributes a visitor reads or hears: alt text, hover titles, input hints and
# the labels a screen reader speaks. Meta descriptions show in search results.
_READ_ATTRS = re.compile(r'\b(?:alt|title|placeholder|aria-label|content)="([^"]*)"', re.I)
_TAG = re.compile(r"<[^>]+>")


def _js_strings(src: str) -> List[str]:
    """String literals in a script, skipping comments and regex literals.

    A small scanner rather than a regex, so an apostrophe in a comment or a
    quote inside /[’']/ never pairs with the wrong quote."""
    out: List[str] = []
    i, n, prev = 0, len(src), ""
    while i < n:
        c = src[i]
        if c in "'\"`":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append("".join(buf))
            i, prev = j + 1, c
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "/" and (not prev or prev in "(,=:[!&|?{};+-*%<>~^"):
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            i, prev = j + 1, "/"
            continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def _prose(s: str) -> bool:
    """A literal a visitor might read: a phrase, or a capitalized label.
    'trade' as a URL parameter or 'cycling' as a class name is neither."""
    return " " in s.strip() or s[:1].isupper()


def visible_text(page: str) -> List[str]:
    """The pieces of a page a visitor reads or hears, as plain text."""
    pieces: List[str] = []
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", page, flags=re.S | re.I)
    body = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<!--.*?-->", " ",
                  page, flags=re.S | re.I)
    pieces.extend(_READ_ATTRS.findall(body))
    pieces.append(_TAG.sub(" ", body))
    for src in scripts:
        if src.lstrip().startswith("{") and '"@context"' in src:
            pieces.append(src)          # structured data: search engines read it
            continue
        pieces.extend(_TAG.sub(" ", s) for s in _js_strings(src) if _prose(s))
    return [_html.unescape(p) for p in pieces if p.strip()]


def offenses(page: str) -> List[Tuple[str, str, str]]:
    """Every avoided word a visitor would read: (word, say instead, context)."""
    found: List[Tuple[str, str, str]] = []
    for text in visible_text(page):
        for rx, say in _AVOID_RE:
            for m in rx.finditer(text):
                ctx = " ".join(text[max(0, m.start() - 50):m.end() + 50].split())
                found.append((m.group(0), say, ctx))
    return found
