"""Which paper belongs in which room — and the hides that are safety, not taste.

/doctemplates/list returned all sixteen templates to every business.
suggested_for only SORTED, so a nonprofit was shown a demand letter and
a coaching agreement, a barber an engagement letter, and six of the
fourteen verticals got a completely flat list.

HIDDEN, NEVER GATED. An irrelevant template sits behind "Show all", so
an over-hide costs one click while an under-hide can cost a
professional-ethics violation. That asymmetry is what lets the table be
opinionated, and it is why nothing here asserts a template is
unreachable.

Three of these hides are safety findings rather than tidiness, and they
get their own tests below.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import doc_templates as dt
import vertical_registry as vr


# ── The three that are safety, not taste ─────────────────────────────

@pytest.mark.parametrize("tid", ["service_agreement", "consulting_agreement"])
def test_a_lawyer_is_not_offered_a_capped_agreement(tid):
    """The sharpest defect the audit found.

    doc_templates.py states, in a comment, that engagement_letter and
    retainer_agreement omit a liability cap ON PURPOSE because
    prospectively limiting professional liability is ethically prohibited
    for lawyers in most states. Both of these carry _LIABILITY_CAP and
    both were shown to every lawyer.
    """
    assert dt.is_irrelevant(tid, "lawyer")
    why = dt.irrelevance_reason(tid, "lawyer") or ""
    assert "cap" in why.lower() or "liability" in why.lower(), why


def test_a_therapist_is_not_offered_the_coaching_agreement():
    """Its 'COACHING, NOT THERAPY' clause asserts the opposite of what a
    therapist does, and its confidentiality section is a generic
    exceptions list rather than a HIPAA-accurate privacy disclosure."""
    assert dt.is_irrelevant("coaching_agreement", "therapist")


def test_a_therapist_is_not_offered_the_closing_letter():
    """The therapist analogue of closing a matter is TERMINATION OF
    TREATMENT — a clinical event with abandonment exposure — and the
    letter's file-retention language invites treating this platform as
    custodian of the clinical record."""
    assert dt.is_irrelevant("disengagement_letter", "therapist")


def test_a_gym_is_not_offered_the_retainer_agreement():
    """A membership is an auto-renewing consumer contract under state
    health-club statutes; 'earned and non-refundable' would produce a
    non-compliant agreement."""
    assert dt.is_irrelevant("retainer_agreement", "fitness_wellness")


def test_a_congregation_is_not_offered_the_nondiscrimination_statement():
    """Correcting yesterday's own work.

    As written it commits the organisation to non-discrimination on
    religion, sex, gender identity and sexual orientation IN EMPLOYMENT,
    which many churches contradict via the ministerial exception and
    Title VII's religious-organisation exemption."""
    assert dt.is_irrelevant("nondiscrimination_statement", "ministry")
    assert "ministry" not in dt.TEMPLATE_INDEX[
        "nondiscrimination_statement"].get("suggested_for", []), (
        "suggested to the very vertical it is wrong for")


# ── The universal three stay universal ───────────────────────────────

@pytest.mark.parametrize("tid", ["mutual_nda", "independent_contractor", "demand_letter"])
def test_the_universal_templates_are_hidden_from_nobody(tid):
    """Every business signs an NDA eventually, hires 1099 help
    eventually, and eventually invoices someone who does not pay.
    Gating these would be the guess this table is careful not to make."""
    assert tid not in dt.IRRELEVANT_FOR, (
        f"{tid} is universal; hiding it from any vertical is the wrong call")


# ── Shape ────────────────────────────────────────────────────────────

def test_every_hide_names_a_real_template_and_a_real_vertical():
    """A typo on either side is invisible — it simply never matches."""
    ids = {t["id"] for t in dt.TEMPLATES}
    canonical = set(vr.CANONICAL)
    for tid, hides in dt.IRRELEVANT_FOR.items():
        assert tid in ids, f"IRRELEVANT_FOR names unknown template {tid!r}"
        for v in hides:
            assert v in canonical, f"{tid} hides for unknown vertical {v!r}"


def test_every_hide_carries_a_reason():
    """A hide with no reason is somebody's taste, and taste drifts."""
    for tid, hides in dt.IRRELEVANT_FOR.items():
        for v, why in hides.items():
            assert why and len(why) > 20, f"{tid}/{v} hidden with no real reason"


def test_a_template_is_never_hidden_from_its_own_suggested_vertical():
    """Suggesting and hiding the same paper to the same vertical is a
    contradiction the picker would render as both first and buried."""
    for t in dt.TEMPLATES:
        for v in t.get("suggested_for", []):
            canon = vr.resolve(v)
            assert not dt.is_irrelevant(t["id"], canon), (
                f"{t['id']} is both suggested for and hidden from {canon}")


def test_the_generic_vertical_hides_nothing():
    """custom is the deliberate 'we do not know this business' bucket.
    Filtering it would be guessing with no information at all."""
    for t in dt.TEMPLATES:
        assert not dt.is_irrelevant(t["id"], "custom"), t["id"]


def test_no_vertical_is_left_with_an_empty_library():
    """A vertical whose every template is hidden has a dead screen."""
    for v in vr.CANONICAL:
        left = [t["id"] for t in dt.TEMPLATES if not dt.is_irrelevant(t["id"], v)]
        assert len(left) >= 4, f"{v} has only {len(left)} relevant templates"


def test_the_nonprofit_governance_set_stays_out_of_trade_verticals():
    for tid in ("board_list", "conflict_of_interest_policy", "whistleblower_policy",
                "document_retention_policy", "mission_history"):
        for v in ("contractor", "personal_services", "lawyer", "creative"):
            assert dt.is_irrelevant(tid, v), f"{tid} shown to {v}"
        # ...and stays IN for the two that file one
        assert not dt.is_irrelevant(tid, "nonprofit")


def test_the_list_endpoint_marks_relevance():
    import inspect
    import doc_templates_router as r
    src = inspect.getsource(r.doctemplates_list)
    assert '"relevant"' in src
    assert "is_irrelevant" in src
    # and it must still RETURN everything — hidden, not gated
    assert "continue" not in src.split('"relevant"')[0].split("for t in")[-1], (
        "the endpoint must not filter templates out of the response")
