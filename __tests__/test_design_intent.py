"""
test_design_intent.py — proves the "reason, don't match a table" property.

Two layers:
  1. MECHANISM (always runs, no key): validation, normalization, fail-open,
     and that the rubric actually enumerates the safe output primitives.
  2. GENERALIZATION (runs only with ANTHROPIC_API_KEY): feed descriptors that
     appear in NO keyword table — "trustworthy", "serene", "electric",
     "quiet confidence", "modern law firm" — and assert each maps to a
     sensible look. This is the actual proof that the system handles intent
     it was never coded for. Run it with a key to watch it generalize.
"""
import os
import pytest

import design_intent as di


# ─── Mechanism (deterministic) ───────────────────────────────────────

def test_rubric_enumerates_the_safe_primitives():
    """The model can only ever be asked to choose looks the renderer builds."""
    for fam in di.VIBE_FAMILIES:
        assert fam in di._SYSTEM
    for intn in di.INTENSITIES:
        assert intn in di._SYSTEM


def test_validate_accepts_good_and_defaults_intensity():
    ok = di._validate({"vibe": "formal", "intensity": "restrained",
                       "rationale": "x", "confidence": 0.8})
    assert ok and ok["vibe"] == "formal" and ok["intensity"] == "restrained"
    # bad intensity → safe default, still accepted
    d = di._validate({"vibe": "warm", "intensity": "screaming", "confidence": 0.7})
    assert d and d["intensity"] == "confident"


def test_validate_rejects_unbuildable_vibe():
    # A look the renderer can't build must be refused, not coerced.
    assert di._validate({"vibe": "cyberpunk", "intensity": "bold", "confidence": 0.9}) is None
    assert di._validate({"vibe": "", "confidence": 0.9}) is None
    assert di._validate("formal") is None


def test_normalization_dedups_and_caps():
    got = di._norm_descriptors(["Warm", "warm", "  bold  ", "", None])
    assert got == ["Warm", "bold"]
    assert di._norm_descriptors("professional") == ["professional"]
    assert di._norm_descriptors(None) == []


def test_fail_open_when_disabled_or_no_input(monkeypatch):
    monkeypatch.setenv("SITE_DESIGN_REASONING", "off")
    assert di.interpret(["trustworthy"]) is None          # kill switch
    monkeypatch.setenv("SITE_DESIGN_REASONING", "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert di.interpret(["trustworthy"]) is None           # no key → fallback
    assert di.interpret([]) is None                        # nothing to reason about


# ─── Generalization (live — needs a key) ─────────────────────────────

_LIVE = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="needs ANTHROPIC_API_KEY — this is the live generalization proof")

# Descriptors that are NOT in _infer_vibe / VIBE_FAMILY_MAP / the fuzzy font
# tables. A keyword system defaults these to formal; reasoning should place
# them correctly.
_NOVEL = [
    ("trustworthy",        {"formal"}),
    ("serene",             {"warm"}),
    ("electric",           {"bold"}),
    ("quiet confidence",   {"formal", "warm"}),
    ("approachable expert",{"warm", "formal"}),
    ("high-octane",        {"bold"}),
    ("old-world craft",    {"warm", "formal"}),
]


@_LIVE
@pytest.mark.parametrize("word,acceptable", _NOVEL)
def test_novel_descriptor_maps_sensibly(word, acceptable):
    read = di.interpret([word])
    assert read is not None, f"{word!r} produced no read"
    assert read["vibe"] in acceptable, (
        f"{word!r} → {read['vibe']} (expected one of {acceptable}); "
        f"rationale: {read.get('rationale')}")


@_LIVE
def test_business_type_breaks_ties():
    # Bare "professional" leans formal; the type shouldn't fight it.
    law = di.interpret(["professional"], business_type="lawyer")
    assert law and law["vibe"] == "formal"
    # A coach with no strong words leans warm.
    coach = di.interpret(["friendly"], business_type="coach")
    assert coach and coach["vibe"] == "warm"


@_LIVE
def test_conflicting_words_resolve_by_dominant_intent():
    # "professional but approachable" → formal look, softened by intensity.
    read = di.interpret(["professional but approachable"])
    assert read and read["vibe"] in {"formal", "warm"}
