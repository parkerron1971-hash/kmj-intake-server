"""The clauses the paper was missing, and the two that fought each other.

An audit of all sixteen templates found the gaps below. Each one is
pinned here so the fix cannot quietly regress.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import doc_templates as dt


def _headings(tid):
    return [s.get("heading") for s in dt.TEMPLATE_INDEX[tid]["sections"]]


def _body(tid):
    return " ".join(s.get("text") or "" for s in dt.TEMPLATE_INDEX[tid]["sections"])


# ── Confidentiality, which three agreements simply did not have ──────

@pytest.mark.parametrize("tid", [
    "retainer_agreement", "service_agreement", "independent_contractor",
])
def test_agreements_that_hand_over_the_business_protect_it(tid):
    """A monthly retainer, a project contract and a 1099 engagement all
    hand over the business's clients, pricing and work product, and said
    nothing about confidentiality at all."""
    assert "CONFIDENTIALITY" in _headings(tid)


def test_the_nda_does_not_get_a_second_confidentiality_clause():
    """It IS the confidentiality agreement — splicing the shared clause
    in would have it say the same thing twice in different words."""
    assert _headings("mutual_nda").count("CONFIDENTIALITY") <= 1


# ── Termination, and the one that disappeared ────────────────────────

@pytest.mark.parametrize("tid", [
    "engagement_letter", "retainer_agreement", "service_agreement",
    "consulting_agreement", "coaching_agreement", "independent_contractor",
])
def test_every_agreement_can_be_ended(tid):
    assert "ENDING THIS AGREEMENT" in _headings(tid)


def test_the_consulting_termination_no_longer_hangs_off_an_optional_field():
    """It was fixed(..., requires="term"), so a consulting agreement with
    the optional Term field left blank shipped with NO termination clause
    — the exit vanished along with the start date."""
    t = dt.TEMPLATE_INDEX["consulting_agreement"]
    ending = [s for s in t["sections"] if s.get("heading") == "ENDING THIS AGREEMENT"]
    assert ending and not ending[0].get("requires"), (
        "the termination clause is conditional again")


def test_termination_carries_a_cure_period_and_survival():
    body = _body("service_agreement").lower()
    assert "materially breaches" in body
    assert "10 days" in body
    assert "continue to apply" in body, "nothing is stated to survive termination"


# ── The NDA's missing forum ──────────────────────────────────────────

def test_the_nda_can_actually_be_enforced_somewhere():
    """An NDA whose whole value is enforceability shipped with no dispute
    clause and no prevailing-party fees."""
    assert "DISPUTE RESOLUTION" in _headings("mutual_nda")


# ── The contradiction ────────────────────────────────────────────────

def test_the_coaching_agreement_no_longer_argues_with_itself():
    """INVESTMENT said payment was due "regardless of session usage".
    ENDING THE PROGRAM said undelivered sessions are refunded. Read
    together they said a client both does and does not get money back."""
    body = _body("coaching_agreement")
    assert "regardless of" in body, "the during-program rule should still stand"
    assert "undelivered sessions are refunded" not in body
    assert "beyond the notice period is refunded" in body


# ── The letter that asserted a fact it could not know ────────────────

def test_the_demand_letter_no_longer_asserts_prior_requests():
    """"Despite prior requests" printed unconditionally, in FIXED text.
    With no prior request, the letter opened by asserting something
    untrue — in the document most likely to be read by a lawyer."""
    body = _body("demand_letter")
    assert "Despite prior" not in body


def test_the_prior_request_line_is_conditional_and_has_a_field():
    t = dt.TEMPLATE_INDEX["demand_letter"]
    assert any(f["key"] == "prior_requests" for f in t["fields"])
    gated = [s for s in t["sections"] if s.get("requires") == "prior_requests"]
    assert len(gated) == 1
    assert "not the first request" in gated[0]["text"]


# ── The armour, made structural ──────────────────────────────────────

def test_every_drafted_section_forbids_invention():
    """Six nonprofit templates each carried their own version of this
    sentence and the seven original agreements carried none — so the
    newest paper was armoured and the oldest, most-used paper was not.

    It lives in drafted() now, so a section cannot ship without it."""
    for t in dt.TEMPLATES:
        for s in t["sections"]:
            if s["kind"] == "drafted":
                assert "nvent" in s["brief"], f"{t['id']}: unarmoured brief"


def test_the_armour_is_not_applied_twice():
    """A brief that already says it keeps its own wording."""
    for t in dt.TEMPLATES:
        for s in t["sections"]:
            if s["kind"] == "drafted":
                assert s["brief"].count("Invent nothing.") <= 1, t["id"]


def test_a_new_drafted_section_is_armoured_automatically():
    s = dt.drafted("X", "Say something nice.", "Fallback text here.")
    assert "nvent" in s["brief"]
    assert s["brief"].startswith("Say something nice.")


def test_every_drafted_section_still_has_its_fallback():
    """The armour must not have disturbed the other half of the contract:
    generation succeeds with the model down."""
    for t in dt.TEMPLATES:
        for s in t["sections"]:
            if s["kind"] == "drafted":
                assert s.get("fallback"), f"{t['id']}: drafted with no fallback"
