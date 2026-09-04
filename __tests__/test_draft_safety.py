"""Editing a draft must not destroy it, and must not send it by accident.

TWO DEFECTS, both in the path a practitioner is told to use.

rewrite_draft ran the whole body through _draft_short, which hardcodes
max_tokens=500, and PATCHed whatever came back over the original. A
contract body runs several thousand tokens, so the rewrite returned cut
off mid-clause and silently replaced the entire agreement. There is no
version history, so the original was simply gone — and the result string
said "rewritten (not yet approved)" while draft_preview showed the first
600 characters, which looked perfect, because the truncation is at the
END.

edit_draft's registry entry read "still a draft, still unsent". The
handler calls _do_approve_one, which approves and sends. The prompt was
honest; the registry — the default-deny classification surface — was the
drifted artifact.

And there was no way at all to save an edit WITHOUT approving it.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import pytest

import action_registry as ar
import chief_of_staff as cos


# ── The truncation guard ─────────────────────────────────────────────

def test_the_short_draft_ceiling_is_named_not_buried():
    assert cos.DRAFT_MAX_TOKENS == 500
    src = inspect.getsource(cos._draft_short)
    assert "max_tokens or DRAFT_MAX_TOKENS" in src, (
        "the ceiling must be overridable, or a document goes through the "
        "email-sized cap")


def test_draft_short_accepts_a_ceiling():
    assert "max_tokens" in inspect.signature(cos._draft_short).parameters


def test_rewrite_sizes_the_ceiling_to_the_document():
    src = inspect.getsource(cos.handle_rewrite_draft)
    assert "max_tokens=budget" in src, "the rewrite still uses the default cap"
    assert "DRAFT_MAX_TOKENS" in src, "the floor should be the short default"


def test_rewrite_refuses_a_body_that_came_back_truncated():
    """The guard that makes the ceiling safe rather than merely likely."""
    src = inspect.getsource(cos.handle_rewrite_draft)
    assert "0.55" in src, "no length check before the PATCH"
    # the refusal must happen BEFORE the write
    guard = src.index("0.55")
    patch = src.index('"PATCH", f"/agent_queue')
    assert guard < patch, "the length check runs after the body is written"


@pytest.mark.parametrize("old_len,new_len,refused", [
    (5600, 900, True),    # the real bug: a contract truncated at 500 tokens
    (5600, 5200, False),  # a genuine edit
    (5600, 3200, False),  # a genuine "make it shorter"
    (5600, 2000, True),   # too much loss to be intentional
    (400, 80, False),     # a short email may legitimately collapse
])
def test_the_threshold_separates_an_edit_from_a_truncation(old_len, new_len, refused):
    """Documented as data rather than prose so the boundary is checkable."""
    triggered = old_len > 1200 and new_len < old_len * 0.55
    assert triggered is refused, (old_len, new_len)


# ── The registry told the truth ──────────────────────────────────────

def test_edit_draft_admits_that_it_approves():
    desc = ar.REGISTRY["edit_draft"]["why"].lower()
    assert "approve" in desc, desc
    assert "still a draft" not in desc, "the description understates the blast radius"


def test_edit_draft_really_does_approve():
    """Pinning the behaviour the description now admits to."""
    assert "_do_approve_one" in inspect.getsource(cos.handle_edit_draft)


# ── save_draft: the path that was missing ────────────────────────────

def test_save_draft_is_registered_all_three_places():
    """Handler, registry AND prompt. A verb missing the third ships
    nothing — the lesson giving_statement taught this codebase."""
    assert "save_draft" in cos.ACTION_HANDLERS
    assert "save_draft" in ar.REGISTRY
    source = chief_source()
    assert '"type":"save_draft"' in source, "not in the prompt catalogue"


def test_save_draft_does_not_approve_or_send():
    src = inspect.getsource(cos.handle_save_draft)
    assert "_do_approve_one" not in src, "save_draft must not approve"
    # It may SAY "not sent" in its result; it must not CALL anything that sends.
    assert "_do_approve_one" not in src
    assert "deliver" not in src.lower()


def test_save_draft_carries_the_same_truncation_guard():
    """A short body replacing a long one is the same loss either way."""
    src = inspect.getsource(cos.handle_save_draft)
    assert "0.55" in src


def test_save_draft_is_class_a_and_says_it_sends_nothing():
    entry = ar.REGISTRY["save_draft"]
    assert entry["reversibility"] == "A"
    assert "nothing leaves" in entry["why"].lower()
