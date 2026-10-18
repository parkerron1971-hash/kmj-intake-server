"""Tone notes: Chief marks how a spoken reply should sound.

Kevin, 2026-10-18, after the tone test (artifact TnbYNV74wuE7HytcFmEUkZ):
the featured voices can change tone on Inworld's bigger model (TTS-2), and
he wants Chief to JUDGE when a reply needs it — most replies stay plain on
the cheaper model (Flash), the ones that carry news get a note. His recipe:
one note at the START, and when good news turns to bad, a breath and
"steady" right before the turn, carried to the end.

Chief writes one of five notes in square brackets: [pleased] [proud]
[gentle] [steady] [breathe]. A note is speech direction, never words. It
is stripped from the reply before anything reads it — the answer check,
the stitched reply, the chat bubble, the conversation on file — and rides
the stream beside the words instead (`speech` on a delta event). The app
carries the note across the pieces a reply is spoken in, and the speech
proxy turns each note into Inworld's own steering and picks the model:
a piece with a note speaks on TTS-2, a piece without one on Flash.

Only a voice turn whose practitioner chose a featured voice asks for
notes (`tone_notes` on the request): every other voice ignores them, so
writing them there would be tokens for nothing. CHIEF_TONE_NOTES is the
switch — off (default), owner (the platform owner's businesses only, to
hear it on real calls first) or on.
"""
from __future__ import annotations

import contextvars
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

TONES = ("pleased", "proud", "gentle", "steady")
NONVERBALS = ("breathe",)
_NAMES = "|".join(TONES + NONVERBALS)
_TAG = re.compile(rf"\[({_NAMES})\]", re.I)
# A run of notes with the space around it: "[breathe] [steady] " is one run.
_RUN = re.compile(rf"\s*(?:\[(?:{_NAMES})\]\s*)+", re.I)

PROMPT_BLOCK = """
TONE NOTES — this practitioner's voice can change its tone. You may mark how a reply should SOUND with a note in square brackets. Only these five exist: [pleased] [proud] [gentle] [steady] [breathe]. They are never shown or read aloud; the voice performs them.
- Judge by what the reply LEADS with: the news they asked about, or what they just shared. Most replies get NO notes: schedules, task lists, figures, how-tos, advice, opinions and ideas, and greetings, thanks and small talk; these stay plain even when you add good news to them. When in doubt, leave them out.
- [pleased] when the reply leads with everyday good news: a payment in, a booking, a good review, a kind word from a client.
- [proud] when it leads with a big win: a best week or month, a milestone, a goal reached.
- [gentle] for hardship: a loss, illness, someone struggling or in a hard season, or the practitioner sharing that they are tired, down, stressed or hurt.
- [steady] when it leads with something serious: money owed, a cancellation, a problem, a deadline at risk.
- The note is the very first thing in the reply, before any greeting or name, and holds to the end. At most ONE change, only when good news turns to bad, and always as [breathe] [steady] right before the sentence where it turns, never any other note. Example: "[pleased] Monica paid her invoice this morning. [breathe] [steady] But two others are still out, about eleven hundred dollars between them."
- No other bracketed notes, and never a note inside an action tag.
"""


def mode() -> str:
    m = (os.environ.get("CHIEF_TONE_NOTES") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def has_notes(text: Optional[str]) -> bool:
    return bool(text) and "[" in text and _TAG.search(text) is not None


def strip(text: Optional[str]) -> str:
    """The words without the notes. Stripping sentence by sentence gives
    the same text as stripping the whole reply, so a stitched reply still
    continues exactly what streamed."""
    if not text or "[" not in text:
        return text or ""
    out: List[str] = []
    last = 0
    for m in _RUN.finditer(text):
        run = m.group(0)
        lead = run[:len(run) - len(run.lstrip())]
        trail = run[len(run.rstrip()):]
        out.append(text[last:m.start()])
        if not "".join(out).strip():
            out.append(lead)                  # the reply's start
        elif text[m.end():].strip():
            out.append(lead or trail or " ")  # between words: the space it had
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def notes_in(text: Optional[str]) -> List[str]:
    return [m.group(1).lower() for m in _TAG.finditer(text or "")]


def steers(text: Optional[str]) -> bool:
    """A note that changes the tone, not just a breath: only the bigger
    model performs one."""
    return any(n in TONES for n in notes_in(text))


def pieces(text: Optional[str]):
    """("words", str) and ("note", name) in order, for the speech proxy."""
    pos = 0
    for m in _TAG.finditer(text or ""):
        yield "words", (text or "")[pos:m.start()]
        yield "note", m.group(1).lower()
        pos = m.end()
    yield "words", (text or "")[pos:]


def speech(text: Optional[str]) -> Optional[str]:
    """The same words with the notes where Chief put them, each spelled the
    one way the speech proxy reads — or None when there are none."""
    if not has_notes(text):
        return None
    return _TAG.sub(lambda m: f"[{m.group(1).lower()}]", text or "")


def split_sentence(sentence: str):
    """(clean, speech) for one sentence of a toned reply."""
    return strip(sentence), speech(sentence)


# ── A turn's notes, for the part of a reply that did not stream ──────────
@dataclass
class ToneTurn:
    """Set by the streaming endpoint before the turn starts. `enabled`
    flips on only when the turn's prompt asked for notes; `records` keeps
    every model answer that carried notes, as written."""
    enabled: bool = False
    records: List[str] = field(default_factory=list)


TURN: "contextvars.ContextVar[Optional[ToneTurn]]" = contextvars.ContextVar(
    "chief_tone_turn", default=None)


def turn_enabled() -> bool:
    t = TURN.get()
    return bool(t and t.enabled)


def take(text: Optional[str]) -> Optional[str]:
    """A model answer as the rest of the turn should read it: the notes
    recorded for the stream's tail, the text without them. Untouched when
    this turn never asked for notes."""
    t = TURN.get()
    if not (t and t.enabled) or not has_notes(text):
        return text
    t.records.append(text or "")
    return strip(text)


_ANCHOR_CHARS = 40
_ALIGN_CHARS = 30


def _marks(tagged: str):
    """(anchor, notes) for each run of notes: the words that follow it."""
    out = []
    for m in _RUN.finditer(tagged):
        notes = notes_in(m.group(0))
        if not notes:
            continue
        anchor = strip(tagged[m.end():]).lstrip()[:_ANCHOR_CHARS]
        if anchor:
            out.append((anchor, " ".join(f"[{n}]" for n in notes)))
    return out


def tail_speech(final: str, start: int, turn: Optional[ToneTurn] = None) -> Optional[str]:
    """How to say final[start:] — the part of the reply that did not stream.

    Notes go back where Chief put them, found by the words that follow
    each one. A tail the model did not write that way (the answer check
    rewrote it) is said [steady]: the reply stays on one model, and a
    correction never sounds pleased. None means "no notes here; the app
    carries whatever tone came before"."""
    turn = turn if turn is not None else TURN.get()
    span = final[start:]
    if not (turn and turn.enabled and turn.records) or not span.strip():
        return None
    head = span.strip()[:_ALIGN_CHARS]
    for tagged in reversed(turn.records):
        if head not in strip(tagged):
            continue
        # Walk the whole reply in order, so a note in the part that
        # already streamed is never matched again further on.
        pieces, pos, search = [], start, 0
        for anchor, notes in _marks(tagged):
            at = final.find(anchor, search)
            if at < 0:
                continue
            search = at + 1
            if at >= start:
                pieces += [final[pos:at], notes + " "]
                pos = at
        if not pieces:
            return None
        pieces.append(final[pos:])
        return "".join(pieces)
    return "[steady] " + span.lstrip()
