"""The /intelligence/vertical endpoint and alias-typed businesses.

The endpoint fed a UI branch that hid an entire section, so getting
`is_known` wrong here was not a cosmetic reporting bug.
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import vertical_intelligence_router as vir
import vertical_registry as reg
from vertical_terminology import BASE_TERMS


def _get(business_type):
    return vir.get_vertical(business_type=business_type)


def test_every_alias_is_reported_as_known():
    """`is_known` was computed on the RAW string against canonical-only
    profile keys, so every registry alias came back False.

    BusinessProfileReview does `if (!isKnown || questions.length === 0)
    return null;` — so the whole vertical onboarding-questions section
    silently did not render for a business stamped 'agency', 'church',
    'attorney' or 'plumber', while the questions it would have shown were
    sitting in the same response payload."""
    for alias, canonical in reg.alias_to_canonical().items():
        out = _get(alias)
        assert out["is_known"] is True, f"'{alias}' reported as unknown"
        assert out["canonical_vertical"] == canonical, (
            f"'{alias}' should canonicalise to '{canonical}'")


def test_an_unrecognised_type_is_still_reported_unknown():
    """The flag has to keep meaning something — a type in no alias list
    still reports False, so the section still hides for a business the
    system genuinely has no profile for."""
    out = _get("sasquatch_grooming")
    assert out["is_known"] is False
    assert out["canonical_vertical"] == "custom"
    assert _get(None)["is_known"] is False


def test_alias_gets_its_vertical_dictionary_not_the_base_one():
    """The router did its own raw VERTICAL_TERMS lookup as well, so an
    alias-typed business received its vertical's voice and offerings
    alongside the BASE dictionary — the two halves of one response
    disagreeing about what a customer is called."""
    church = _get("church")["effective_terms"]
    ministry = _get("ministry")["effective_terms"]
    assert church["customer"] == ministry["customer"] == "Member"
    assert church["customer"] != BASE_TERMS["customer"]

    store = _get("online_store")["effective_terms"]
    assert store["service"] == "Product"
    assert _get("micro_saas")["effective_terms"]["service"] == "Plan"


def test_resolved_business_type_still_answers_which_input_won():
    """`resolved_business_type` documents WHICH INPUT won the fallback
    chain, which is a different question from which vertical it is. It
    must keep reporting the raw winner — `canonical_vertical` is where the
    resolved key belongs."""
    out = _get("church")
    assert out["resolved_business_type"] == "church"
    assert out["canonical_vertical"] == "ministry"


def test_alias_and_canonical_return_the_same_intelligence():
    for alias, canonical in [("agency", "creative"), ("plumber", "contractor"),
                             ("online_store", "ecommerce"), ("micro_saas", "saas")]:
        a, c = _get(alias), _get(canonical)
        for field in ("voice", "onboarding_questions", "offering_suggestions",
                      "invoice_line_templates", "module_suggestions",
                      "empty_state_nudges", "effective_terms"):
            assert a[field] == c[field], f"'{alias}' differs from '{canonical}' on {field}"
