"""Team personas must be reachable from a real businesses.type.

TEAM_PERSONAS was keyed on a taxonomy of its own — church, coaching,
consulting, freelance, real_estate, health_wellness — and looked up with
a raw `.get(bt)`. Only ONE of those keys ("nonprofit") is a value
businesses.type ever holds, so in practice every coach, consultant,
ministry, lawyer and therapist in the system got the "default" set:
"Outreach", "Proposals", "Billing", "Tracker", "Advisor".

The coach personas were not missing. They were written, shipped, and
unreachable, sitting under the key "coaching" while every coach row said
"coach".

These tests pin the two halves of the fix: the keys are canonical, and
the lookup resolves aliases so both spellings land on the same set.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos
import vertical_registry as vr

AGENT_KEYS = ("nurture", "session_prep", "contract", "payment", "module", "growth")

# Pre-registry business types kept on raw keys: they resolve to "custom",
# so they cannot be canonical, but their personas beat the default set.
LEGACY_RAW_KEYS = {"real_estate", "health_wellness"}


def test_every_canonical_vertical_has_personas():
    """Except the two generic buckets, which SHOULD get the default set."""
    generic = {"custom", "service_provider"}
    missing = set(vr.CANONICAL) - set(cos.TEAM_PERSONAS) - generic
    # service_provider does have its own set (the old "freelance" one);
    # that is a bonus, not a requirement, so only custom may be absent.
    assert not missing, f"canonical verticals falling to default personas: {sorted(missing)}"


def test_persona_keys_are_canonical_or_declared_legacy():
    keys = set(cos.TEAM_PERSONAS) - {"default"}
    stray = keys - set(vr.CANONICAL) - LEGACY_RAW_KEYS
    assert not stray, (
        f"persona keys that no businesses.type will ever equal: {sorted(stray)} — "
        "either canonicalize them or declare them legacy"
    )


@pytest.mark.parametrize("alias,canonical", [
    ("church", "ministry"),
    ("coaching", "coach"),
    ("consulting", "consultant"),
    ("CHURCH", "ministry"),
    ("  coach  ", "coach"),
])
def test_aliases_resolve_to_the_same_personas(alias, canonical):
    """The bug in one line: a stored alias must not fall to default."""
    assert cos._persona_set(alias) is cos.TEAM_PERSONAS[canonical]
    assert cos._persona_set(alias) is not cos.TEAM_PERSONAS["default"]


@pytest.mark.parametrize("vertical", ["ministry", "coach", "consultant", "nonprofit",
                                      "lawyer", "therapist", "contractor",
                                      "personal_services"])
def test_real_verticals_do_not_get_the_default_set(vertical):
    got = cos._persona_set(vertical)
    assert got is not cos.TEAM_PERSONAS["default"], (
        f"{vertical} still receives the generic personas"
    )
    assert cos.get_team_label(vertical, "nurture") != "Outreach"


def test_legacy_types_keep_their_own_personas():
    """real_estate resolves to 'custom' — the raw fallback must catch it."""
    for legacy in LEGACY_RAW_KEYS:
        assert vr.resolve(legacy) not in cos.TEAM_PERSONAS or vr.resolve(legacy) == legacy
        assert cos._persona_set(legacy) is cos.TEAM_PERSONAS[legacy]


def test_every_persona_set_covers_every_agent():
    """A half-filled set means one surface silently reads the title-cased key."""
    for vertical, personas in cos.TEAM_PERSONAS.items():
        for agent in AGENT_KEYS:
            assert agent in personas, f"{vertical} is missing the {agent} persona"
            assert personas[agent].get("label"), f"{vertical}.{agent} has no label"
            assert personas[agent].get("description"), f"{vertical}.{agent} has no description"


def test_unknown_and_empty_types_still_get_default():
    for value in ("", None, "   ", "sasquatch_grooming"):
        assert cos._persona_set(value) is cos.TEAM_PERSONAS["default"]


def test_nonprofit_contract_persona_claims_no_grant_capability():
    """No surface writes grants yet; the label must not say otherwise.

    Re-point this at the grant surface when one exists — until then a
    "Grant Writer" label is a promise the contract agent cannot keep.
    """
    label = cos.get_team_label("nonprofit", "contract")
    desc = cos.get_team_description("nonprofit", "contract")
    assert "grant" not in label.lower(), f"label re-claims grant writing: {label!r}"
    assert "grant" not in desc.lower(), f"description re-claims grant writing: {desc!r}"
    assert "funding application" not in desc.lower()
