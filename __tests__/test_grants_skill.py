"""A practitioner asking to track grants must reach a skill.

Before this file's subject existed, "track our grants" selected NOTHING.
No skill carried grant, funder, LOI, RFP or NOFO in its triggers, so the
module generator designed a grant pipeline with no guidance at all — for
a vertical whose onboarding card has promised "donors, programs, grants,
events" since the day it shipped.

These are behaviour checks, not a reading of the file's prose: what a
phrase selects, and what the guidance refuses to promise.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import build_skills as bs

SKILL = "grants-module"


def _names(text, biz_type=None):
    return [s["name"] for s in bs.select_skills(text, biz_type)]


def _body():
    hit = [s for s in bs.load_skills() if s["name"] == SKILL]
    assert hit, "grants-module did not load — check the frontmatter parses"
    return hit[0]["body"].lower()


@pytest.mark.parametrize("phrase", [
    "track our grants",
    "set up a grant pipeline",
    "I need to manage funders and deadlines",
    "where are we on that foundation proposal",
    "NOFO deadlines are killing me",
    "keep track of every LOI we send",
    "an RFP tracker",
])
def test_grant_language_selects_the_skill(phrase):
    assert SKILL in _names(phrase), f"{phrase!r} selected {_names(phrase)}"


@pytest.mark.parametrize("phrase", [
    "a pipeline for leads",
    "track my client sessions",
    "who owes me money",
    "book appointments",
])
def test_unrelated_asks_do_not_select_it(phrase):
    assert SKILL not in _names(phrase), f"{phrase!r} selected {_names(phrase)}"


def test_it_composes_with_the_generic_pipeline_skill():
    """Both is the right answer: generic stage discipline plus the
    grant-specific shape. MAX_SKILLS caps at 2, so this is the ceiling."""
    got = _names("set up a grant pipeline")
    assert SKILL in got and "pipeline-module" in got, got


def test_it_is_not_gated_to_one_vertical():
    """A ministry applies for grants; so does a fiscal sponsor. The
    triggers are specific enough that gating by business_type would only
    lock out real askers."""
    for biz in ("nonprofit", "ministry", "consultant", None):
        assert SKILL in _names("track our grants", biz), biz


def test_reporting_is_not_taught_as_terminal():
    """The one rule that separates a grant pipeline from a sales one.

    A prose assertion, deliberately: this file IS the guidance, so the
    thing worth pinning is that the rule cannot be quietly softened. The
    behavioural half of this skill is covered by the selection tests
    above.
    """
    body = _body()
    assert "reporting is not terminal" in body
    # Wrapped across a line in the source, so normalize before matching.
    flat = " ".join(body.split())
    assert "reporting must never go in closed_statuses" in flat


def test_it_refuses_to_promise_drafting():
    """No surface writes grant narratives. The skill must not design
    fields that imply otherwise, and must not invent outcome numbers —
    a reported figure is certified by whoever signs, so a fabricated one
    is a legal exposure rather than a formatting problem."""
    body = _body()
    assert "does not draft" in body
    assert "ai draft field or trigger" in body
    for phrase in ("do not invent outcome", "fabricated number"):
        assert phrase in body, phrase


def test_currency_not_text_for_the_amount():
    body = _body()
    assert "`currency`, never `text`" in body


def test_module_ref_for_the_program_link():
    """Free text here is the exact disease module_ref was added to cure."""
    body = _body()
    assert "module_ref" in body
    assert "never free text" in body


def test_every_trigger_word_is_word_bounded():
    """Short triggers are substrings of many words; `loi` and `rfp` and
    `rfa` are the risky ones here."""
    skill = [s for s in bs.load_skills() if s["name"] == SKILL][0]
    for t in skill.get("triggers") or []:
        assert not bs._trigger_re(t).search(f"x{t}x"), t
        assert bs._trigger_re(t).search(f"a {t} b"), t
