"""
support_thread.py — what the person who reported it is allowed to see, and
the words the ticket uses to tell its own story.

Pure functions, no I/O. Two jobs:

  1. STAGE. The operator's fix_state has eight values and includes things
     like "wont_fix"; the practitioner's stage has five and is written in
     the language of somebody waiting on an answer. One mapping, so the
     badge they see can never drift from where the work actually is.

  2. THE GUARD. Everything in support_ticket_messages is tenant-readable —
     that is the point of it. So nothing internal may ever be written
     there. Chief already carries this rule ("practitioners must NEVER see
     builder/GitHub/Claude Code language"); here it stops being a
     convention and becomes a check that runs before every write, because
     the sentence that closes a ticket now comes from a fixing session,
     and a session that has spent an hour in a repo talks like it.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# --- stage: fix_state as the practitioner sees it --------------------

STAGES = ("received", "looking", "working", "fixed", "answered")

STAGE_OF_FIX_STATE: Dict[str, str] = {
    "new": "received",
    "triaged": "looking",
    "queued": "working",
    "fixing": "working",
    "shipped": "fixed",
    "answered": "answered",
    "wont_fix": "answered",
    "duplicate": "answered",
}

STAGE_LABEL: Dict[str, str] = {
    "received": "Received",
    "looking": "Someone's looking",
    "working": "Being worked on",
    "fixed": "Fixed — try it",
    "answered": "Answered",
}


def stage_of(fix_state: Optional[str]) -> str:
    """Unknown values fall back to 'received' rather than raising: a stage
    the app has not heard of must degrade to a working badge, not a blank
    ticket. Same reason the column carries no CHECK."""
    return STAGE_OF_FIX_STATE.get((fix_state or "new").lower(), "received")


# --- the words the ticket says for itself ----------------------------
# Fixed sentences, not generated ones. A system message is written by a
# state change, and a state change has nothing to add beyond the fact —
# so the wording is reviewable here, once, in plain English.

SYSTEM_MESSAGE: Dict[str, str] = {
    "looking": "Someone is looking at this now.",
    "working": "We're working on a fix for this.",
    "fixed": ("This should be fixed now. Give it a try when you get a "
              "moment — and tell us here if it still isn't right."),
    "stalled": ("We hit a snag on the fix, so this is back with the team. "
                "It hasn't been forgotten."),
}

# Which stage transitions are worth an email rather than only a badge.
# 'working' earns one because silence after reporting something is the
# part people actually feel; 'fixed' earns one because it asks them to do
# something. Each fires at most once, since a state only transitions once.
EMAIL_ON = ("working", "fixed")


# --- the guard -------------------------------------------------------
# Tight on purpose. Every entry is a word that only appears in a sentence
# written from inside the workshop, and none of them is something a
# practitioner-facing sentence about their own business would need.

_BANNED = (
    "claude", "anthropic", "github", "pull request", "pr #", "repo",
    "repository", "branch", "commit", "merge", "codebase", "dev task",
    "builder", "railway", "supabase", "migration", "endpoint", "api key",
    "stack trace", "traceback", "deploy", "rollback", "refactor",
    "regression test", "unit test", "typescript", "python", "sql",
    "localhost", "http://", "https://",
)


def practitioner_safe(text: str) -> Tuple[bool, List[str]]:
    """(is it safe to show them, which words made it unsafe).

    Substring matching, deliberately: 'PR #785' and 'the PR' both matter,
    and a word-boundary regex over a list this small buys nothing but a
    way to miss one.
    """
    low = (text or "").lower()
    hits = [w for w in _BANNED if w in low]
    return (not hits), hits


def clean_for_practitioner(text: str, fallback: str) -> str:
    """The sentence a fixing session wrote, if it can be shown as-is;
    otherwise the generic one.

    Fail-SAFE, not fail-open: a sentence that trips the guard is replaced
    entirely rather than edited, because a redacted sentence reads like a
    redacted sentence and the point of the message is that it sounds like
    a person. The raw text is not lost — the caller keeps it on the
    operator-only note.
    """
    text = (text or "").strip()
    if not text:
        return fallback
    ok, _hits = practitioner_safe(text)
    if not ok:
        return fallback
    # One sentence, not a session log: keep it to something a person reads
    # in a glance.
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= 400 else fallback
