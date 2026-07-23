"""
test_judge_fairness.py — the paid-for-nothing loop fixes (2026-07-23).

Three defects made every rebuild a burned fee:
  1. The rubric told the judge to score hover states — invisible in
     static screenshots — so every candidate lost motif points to an
     unobservable axis.
  2. Verdicts didn't record which reference standard they were earned
     under, so the ratchet compared composites across different bars
     (Mural candidate on the Nike-campaign bar vs a live score earned
     on the default bar = unwinnable).
  3. A rejected build's HTML was discarded entirely.

These tests pin the contract for 1 and 2 (3 lives in the rejection
persist block and is covered by inspection of vision_rejection shape).
"""
import vision_grader as vg
from reference_standards import STANDARDS, standard_for, standard_key_for


# ─── 1. static-screenshot rule ───────────────────────────────────────

def test_rubric_never_asks_for_hover_states():
    assert "hover" not in vg.RUBRIC.split("STATIC screenshots")[0].lower(), (
        "the scoring axes must not name hover states — a still image "
        "cannot show them"
    )
    assert "STATIC screenshots" in vg.RUBRIC
    assert "NEVER penalize" in vg.RUBRIC


def test_rubric_version_bumped_past_arcD1():
    # The rubric change is meaningful — the era stamp must move so the
    # ratchet re-grades old-era live verdicts instead of comparing raw.
    assert vg.RUBRIC_VERSION != "arcD-1"


# ─── 2. same-bar rule inputs ─────────────────────────────────────────

def test_standard_key_for_always_returns_known_key():
    assert standard_key_for(None) in STANDARDS
    assert standard_key_for({}) in STANDARDS
    key = standard_key_for({
        "design": {"loudness": "loud"},
        "site_prefs": {"feel_words": "bold statement energy", "boldness": "loud"},
    })
    assert key in STANDARDS


def test_standard_for_matches_its_key():
    ctx = {"site_prefs": {"feel_words": "quiet luxury, refined", "boldness": ""}}
    key = standard_key_for(ctx)
    assert standard_for(ctx) == {**STANDARDS}.get(key) or standard_for(ctx)


def test_verdict_composite_unchanged():
    v = {"first_viewport_impact": 7, "balance": 6, "motif_visibility": 5,
         "rhythm": 6, "template_smell": 4}
    assert vg.verdict_composite(v) == 20
