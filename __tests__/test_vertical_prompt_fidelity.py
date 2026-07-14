"""
test_vertical_prompt_fidelity.py — the vertical QUALITY BAR.

Leg 2 of the vertical-completion program. The north star is "when Chief
creates and adjusts, it fits the vertical." Chief's create/adjust output is
produced by the LLM from the assembled prompt — so the checkable proxy for
"Chief can adjust well" is: does the prompt Chief receives actually carry
this vertical's full identity? The create_offering / invoice handlers are
vertical-agnostic by design (they persist whatever the model emits), so the
ONLY lever is the prompt context. This test asserts that lever is fully
loaded for every supported vertical.

`assert_vertical_reaches_chief()` IS the bar. Legs 3 (lawyer) and 4 (ministry
polish) reuse it — a vertical isn't "done" until it clears this.

coach is the reference vertical (the most complete), with an extra explicit
check documenting what a fully-wired vertical looks like end to end.
"""
import pytest

from vertical_context import build_vertical_context_block
import vertical_terminology as vt


# Verticals that should FULLY reach Chief (have voice + offerings + invoice
# templates). service_provider/custom are the intentional GENERIC baseline.
FULLY_SUPPORTED = [
    "coach", "consultant", "creative", "course_creator", "financial_educator",
    "fitness_wellness", "personal_services", "lawyer", "ministry", "nonprofit",
]


def assert_vertical_reaches_chief(vertical: str) -> str:
    """The bar: the assembled vertical context block must carry this
    vertical's full identity — voice, vocabulary, offering shapes, invoice
    shapes. Returns the block so callers can add vertical-specific checks."""
    block = build_vertical_context_block({"type": vertical})

    # Not the generic fallback.
    assert "generic — vertical not explicitly mapped" not in block, (
        f"{vertical}: falls back to the GENERIC block")

    # Voice + vocabulary reach the prompt.
    assert "Voice register:" in block, f"{vertical}: no voice register"
    assert "Vocabulary:" in block, f"{vertical}: no vocabulary line"
    assert "Hallmarks:" in block, f"{vertical}: no voice hallmarks"

    # The create/adjust lever: offering + invoice starting points.
    assert "Typical offerings for this vertical" in block, (
        f"{vertical}: no offering templates in Chief's prompt — create_offering "
        f"will invent generic offerings")
    assert "Typical invoice lines for this vertical" in block, (
        f"{vertical}: no invoice-line templates in Chief's prompt — invoice "
        f"drafting will invent generic line items")
    return block


@pytest.mark.parametrize("vertical", FULLY_SUPPORTED)
def test_vertical_fully_reaches_chief(vertical):
    assert_vertical_reaches_chief(vertical)


def test_coach_reference_bar():
    """coach is the reference — spell out the full end-to-end identity so the
    bar is legible for the verticals that follow."""
    block = assert_vertical_reaches_chief("coach")
    # Coach vocabulary flows through terminology into the prompt.
    assert vt.get_term("coach", "customer") == "Client"
    assert vt.get_term("coach", "session") == "Session"
    assert "Client" in block  # vocabulary line carries the coach nouns
    # Coach-specific reminder present.
    assert "Confidentiality" in block


def test_vocabulary_is_vertical_specific():
    """Terminology actually differs per vertical (not all 'Customer')."""
    assert vt.get_term("lawyer", "service") == "Matter"
    assert vt.get_term("ministry", "customer") == "Member"
    assert vt.get_term("ministry", "donors") == "Givers"      # Leg 0 (ministry fix)
    assert vt.get_term("nonprofit", "customer") == "Donor"
    assert vt.get_term("course_creator", "customer") == "Student"


def test_ministry_and_nonprofit_are_distinct():
    """Same accounting family, different voice/vocabulary — not merged."""
    m = build_vertical_context_block({"type": "ministry"})
    n = build_vertical_context_block({"type": "nonprofit"})
    assert "Member" in m and "Donor" in n
    assert m != n
