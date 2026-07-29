"""
test_contract_vertical_framing.py — the contract agent must frame the document
for the vertical the business ACTUALLY is.

THE BUG THIS PINS DOWN
  contract_agent's framing map was keyed on legacy aliases ('church',
  'coaching', 'agency') while intake stamps canonical vertical_registry keys
  ('ministry', 'coach', 'creative'). Every canonical value missed the map and
  fell through to the generic "professional engagement proposal", and
  'lawyer' / 'consultant' had no entry at all — the two verticals whose
  archetypes are built around engagement letters and scopes of work.

  It went unnoticed because the raw type was still interpolated into the
  prompt, so the model partially recovered. These tests assert on the framing
  the code CHOOSES, not on the prose the model returns, so a silent fallback
  fails here instead of quietly degrading a document.

THE DRIFT GUARD
  test_every_canonical_vertical_has_framing is the one that matters long term:
  add a vertical to vertical_registry.CANONICAL without deciding what kind of
  document it signs, and this fails.
"""
from __future__ import annotations

import pytest

import contract_agent
import vertical_registry


# ── the drift guard ──────────────────────────────────────────────────

def test_every_canonical_vertical_has_framing():
    """A new vertical cannot ship without a framing decision."""
    missing = [k for k in vertical_registry.canonical_keys()
               if k not in contract_agent.PROPOSAL_FRAMING]
    assert not missing, (
        f"canonical verticals with no proposal framing: {missing}. "
        "Add an entry to contract_agent.PROPOSAL_FRAMING — a vertical with no "
        "framing silently drafts the generic proposal.")


def test_every_canonical_vertical_has_guidance():
    missing = [k for k in vertical_registry.canonical_keys()
               if k not in contract_agent.PROPOSAL_GUIDANCE]
    assert not missing, (
        f"canonical verticals with no drafting guidance: {missing}")


# ── the regression: canonical keys must not fall through ─────────────

@pytest.mark.parametrize("canonical", [
    "coach", "consultant", "creative", "lawyer", "ministry", "nonprofit",
    "course_creator", "financial_educator", "fitness_wellness",
    "personal_services", "service_provider",
])
def test_canonical_type_gets_specific_framing(canonical):
    """The values intake actually stamps must each get their OWN framing,
    not the generic fallback."""
    framing = contract_agent._proposal_framing(canonical)
    assert framing != contract_agent._GENERIC_FRAMING, (
        f"{canonical} fell through to the generic framing — this is the "
        "legacy-alias drift bug returning.")


def test_lawyer_gets_an_engagement_letter():
    """The vertical whose whole archetype is the engagement letter."""
    framing = contract_agent._proposal_framing("lawyer")
    assert "engagement letter" in framing.lower()
    guidance = contract_agent._proposal_guidance("lawyer")
    # The two things a lawyer's contract must not do.
    assert "outcome" in guidance.lower()
    assert "trust" in guidance.lower()


def test_consultant_gets_a_scope_of_work():
    framing = contract_agent._proposal_framing("consultant")
    assert "scope of work" in framing.lower()


def test_ministry_is_a_partnership_not_a_sale():
    framing = contract_agent._proposal_framing("ministry")
    assert "partnership" in framing.lower()
    assert "ministry" in framing.lower()


# ── aliases and canonical values agree ───────────────────────────────

@pytest.mark.parametrize("alias,canonical", [
    ("church",     "ministry"),
    ("coaching",   "coach"),
    ("agency",     "creative"),
    ("attorney",   "lawyer"),
    ("law_firm",   "lawyer"),
    ("consulting", "consultant"),
    ("non_profit", "nonprofit"),
])
def test_legacy_alias_lands_on_same_framing_as_canonical(alias, canonical):
    """Businesses stamped before the registry existed must get the same
    document as ones stamped after it."""
    assert (contract_agent._proposal_framing(alias)
            == contract_agent._proposal_framing(canonical))


# ── the fallbacks stay safe ──────────────────────────────────────────

def test_unknown_type_falls_back_to_generic():
    assert contract_agent._proposal_framing("crypto_yacht_rental") == \
        contract_agent._GENERIC_FRAMING


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_missing_type_does_not_raise(empty):
    """A business with no type still gets a draftable contract."""
    assert contract_agent._proposal_framing(empty) == \
        contract_agent._GENERIC_FRAMING
    assert contract_agent._proposal_guidance(empty)


def test_canonical_type_normalizes_spacing_and_case():
    assert contract_agent._canonical_type("Law Firm") == "lawyer"
    assert contract_agent._canonical_type("LAWYER") == "lawyer"
    assert contract_agent._canonical_type("law-firm") == "lawyer"
