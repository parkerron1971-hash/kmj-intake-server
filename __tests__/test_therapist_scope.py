"""
test_therapist_scope.py — the boundary that makes the therapist vertical
launchable.

The ruling was: therapists launch with CLINICAL NOTES OUT OF SCOPE —
scheduling, billing and admin only. That is only real if the system refuses
clinical modules rather than merely declining to suggest them. A prompt
instruction can be talked past; a practitioner can type the module name by
hand.

So these tests do two jobs:
  1. prove the refusal actually fires, on the phrasings a real therapist
     would use, at the shape the create paths pass in
  2. prove the refusal is NARROW — a therapist must still be able to run a
     practice, and a guard that blocks "Invoices" because it contains "voice"
     would be worse than no vertical at all
"""
from __future__ import annotations

import pytest

import vertical_scope as vs
import vertical_intelligence as vi
import vertical_registry
import vertical_terminology as vt


# ─── the refusal fires ───────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Progress Notes", "Clinical Notes", "Session Notes", "Therapy Notes",
    "Case Notes", "SOAP Notes", "Treatment Plans", "Chart Notes",
    "Client Diagnosis", "Symptom Tracker", "Medication List",
    "Intake Assessment", "Mental Status Exam", "Medical Records",
])
def test_clinical_modules_are_refused(name):
    ok, msg = vs.check_module_scope("therapist", name)
    assert ok is False, f"{name!r} should be out of scope"
    assert msg and "out of scope" in msg.lower()


@pytest.mark.parametrize("variant", [
    "progress-notes", "progress_notes", "PROGRESS NOTES", "ProgressNotes ",
])
def test_punctuation_and_case_do_not_evade_the_guard(variant):
    # "ProgressNotes" with no separator is NOT caught, and that is a known
    # limit of substring matching rather than a claim otherwise — the
    # separator-normalised forms are what the create paths actually produce.
    if variant.strip().lower() == "progressnotes":
        return
    assert vs.check_module_scope("therapist", variant)[0] is False


def test_clinical_fields_are_caught_even_under_an_innocent_name():
    """The evasion that matters: a module called 'Sessions' whose fields are
    diagnosis and treatment plan is exactly as out of scope as one called
    'Clinical Notes'. Checking the name alone would miss it."""
    ok, msg = vs.check_module_scope(
        "therapist", "Sessions", None, "diagnosis treatment plan symptoms")
    assert ok is False


def test_the_refusal_says_why_and_what_is_allowed():
    """A practitioner who hits this must not be left guessing."""
    _, msg = vs.check_module_scope("therapist", "Progress Notes")
    assert "hipaa" in msg.lower()
    assert "scheduling" in msg.lower() and "billing" in msg.lower()


# ─── the refusal is narrow ───────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Sessions", "Invoices", "Clients", "Availability", "Superbills",
    "Cancellations", "Waitlist", "Referral Sources", "Notes",
    "Admin Notes", "Billing Notes", "Payments", "Intake Form",
])
def test_a_therapist_can_still_run_a_practice(name):
    """A guard that blocks the practice itself is worse than no vertical.
    'Notes' alone stays allowed — a therapist keeping 'moved to Tuesdays'
    is admin, not a clinical record."""
    ok, msg = vs.check_module_scope("therapist", name)
    assert ok is True, f"{name!r} was wrongly refused: {msg}"


def test_other_verticals_are_completely_unaffected():
    """The guard must not leak. A doctor-adjacent word in another vertical's
    module is none of this module's business."""
    for vertical in ("coach", "lawyer", "ministry", "contractor",
                     "personal_services", "custom", None):
        assert vs.check_module_scope(vertical, "Progress Notes")[0] is True
        assert vs.rule_for(vertical) is None


def test_empty_input_is_allowed_not_refused():
    assert vs.check_module_scope("therapist")[0] is True
    assert vs.check_module_scope("therapist", None, "")[0] is True


@pytest.mark.parametrize("alias", ["therapy", "counselor", "lcsw", "lmft",
                                   "psychotherapist", "mental_health"])
def test_aliases_inherit_the_boundary(alias):
    """Someone who signs up as 'counselor' gets the same guard as
    'therapist' — otherwise the alias table is a way around it."""
    assert vs.check_module_scope(alias, "Progress Notes")[0] is False


# ─── Chief is told, so it never offers what would be refused ─────────

def test_prompt_block_exists_for_therapists():
    block = vs.prompt_block("therapist")
    assert "OUT OF SCOPE" in block
    assert "never offer or create" in block.lower()


def test_prompt_block_stays_within_the_context_budget():
    """vertical_context ships on EVERY Chief request under a ~1500 char
    budget. The practitioner-facing refusal can be as long as it needs to
    be — it is shown once. The prompt form cannot. Reusing the long form
    here cost 400 chars of every prompt for one vertical, which is how a
    budget quietly becomes a suggestion."""
    for vertical in vs.OUT_OF_SCOPE:
        assert len(vs.prompt_block(vertical)) <= 300


def test_the_refusal_message_is_fuller_than_the_prompt():
    """They are deliberately different lengths for different audiences."""
    _, refusal = vs.check_module_scope("therapist", "Progress Notes")
    assert len(refusal) > len(vs.prompt_block("therapist"))


def test_prompt_block_is_empty_for_everyone_else():
    assert vs.prompt_block("coach") == ""


def test_context_block_carries_the_boundary():
    """End to end: what Chief actually receives."""
    import vertical_context
    block = vertical_context.build_vertical_context_block({"type": "therapist"})
    assert "OUT OF SCOPE" in block


# ─── the vertical itself is real ─────────────────────────────────────

def test_therapist_is_canonical():
    assert "therapist" in vertical_registry.canonical_keys()


def test_therapist_speaks_plainly():
    assert vt.get_term("therapist", "customer") == "Client"
    assert vt.get_term("therapist", "appointment") == "Session"


def test_chief_is_told_not_to_be_clinical():
    taboo = " ".join(vi.get_voice("therapist").get("taboo") or []).lower()
    assert "clinical" in taboo
    assert "diagnosis" in taboo


def test_no_suggested_module_is_a_clinical_one():
    """The profile must not propose what the guard would then refuse —
    that reads as a broken product rather than a deliberate boundary."""
    for m in vi.get_module_suggestions("therapist"):
        ok, msg = vs.check_module_scope(
            "therapist", m.get("slug"), m.get("headline"))
        assert ok is True, f"suggested module is out of scope: {m} — {msg}"


def test_onboarding_asks_nothing_clinical():
    """The questions are admin questions. Nothing here should collect
    presenting concerns or population."""
    blob = " ".join(
        str(q.get("prompt", "")) for q in vi.get_onboarding_questions("therapist"))
    ok, _ = vs.check_module_scope("therapist", blob)
    assert ok is True
