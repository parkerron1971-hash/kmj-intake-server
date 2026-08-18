"""
test_personal_services_terminology.py — barbers and salons say Client.

WHY THIS EXISTS
  personal_services carried an EMPTY override block for a year ("closest to
  generic"), so a barbershop's whole UI called the person in the chair a
  "Customer". The first fix chose "Guest" on a hospitality argument; Kevin
  overruled it (8/18) — barbers and stylists say "my clients" out loud,
  "Guest" is hotel language. Both the empty block and the Guest pass were
  deliberate decisions, so a test rather than a comment is what keeps the
  current ruling from being quietly undone.

THE LOCKSTEP THIS GUARDS
  vertical_context.build_vertical_context_block puts the VOCABULARY (from
  VERTICAL_TERMS) and the VOICE HALLMARKS (from VERTICAL_INTELLIGENCE) into
  the SAME Chief system prompt. If only the dictionary moves, Chief is
  handed a prompt that contradicts itself about what to call the person.
  test_hallmarks_do_not_contradict_vocabulary is the guard for that class
  of bug, not just this instance of it.
"""
from __future__ import annotations

import pytest

import vertical_terminology as vt
import vertical_intelligence as vi
import vertical_context


PS = "personal_services"


# ── the vocabulary ───────────────────────────────────────────────────

@pytest.mark.parametrize("key,expected", [
    ("customer",  "Client"),
    ("customers", "Clients"),
    ("contact",   "Client"),
    ("contacts",  "Clients"),
    ("offering",  "Service"),
    ("offerings", "Services"),
])
def test_barber_says_client(key, expected):
    assert vt.get_term(PS, key) == expected


@pytest.mark.parametrize("key", [
    "appointment", "appointments", "booking", "bookings",
])
def test_appointment_language_stays_generic(key):
    """A barber genuinely says 'appointment' and 'booking'. Overriding these
    would be change for its own sake — this pins the decision NOT to."""
    assert vt.get_term(PS, key) == vt.BASE_TERMS[key]


def test_the_override_block_is_not_empty():
    """The regression itself: an empty block is how this vertical spent a
    year calling clients customers."""
    assert vt.VERTICAL_TERMS.get(PS), (
        "personal_services override block is empty again — barbers will "
        "render 'Customer' throughout the UI.")


# ── the lockstep guard ───────────────────────────────────────────────

def test_hallmarks_do_not_contradict_vocabulary():
    """Voice hallmarks and terminology land in the same Chief prompt. They
    must not disagree about what to call the person."""
    profile = vi.get_profile(PS)
    hallmarks = " ".join((profile.get("voice") or {}).get("hallmarks") or [])
    person = vt.get_term(PS, "customer")

    assert person.lower() in hallmarks.lower(), (
        f"hallmarks never mention '{person}', the term the dictionary "
        f"resolves for this vertical: {hallmarks!r}")


def test_context_block_carries_client_not_customer():
    """End to end: what Chief actually receives in its system prompt."""
    block = vertical_context.build_vertical_context_block({"type": PS})
    assert "Client" in block
    # The prompt should not be telling Chief to say Customer for this
    # vertical anywhere — vocabulary line or hallmark line.
    assert "customer=Customer" not in block


# ── the other verticals are untouched ────────────────────────────────

@pytest.mark.parametrize("vertical,expected", [
    ("lawyer",     "Client"),
    ("ministry",   "Member"),
    ("coach",      "Client"),
    ("consultant", "Client"),
    ("nonprofit",  "Donor"),
])
def test_other_verticals_unchanged(vertical, expected):
    assert vt.get_term(vertical, "customer") == expected


def test_service_provider_stays_generic():
    """service_provider is the deliberate generic baseline — it must NOT
    inherit Guest just because it sits next to personal_services."""
    assert vt.get_term("service_provider", "customer") == "Customer"
