"""
test_vertical_flavor_gaps.py — terminology + email flavor gaps closed 7/31.

THE GAPS THESE PIN
  1. contractor's people register read "Contacts". The override block
     deliberately keeps 'customer' at BASE ("a contractor says Customer"),
     but never set the contact/contacts keys — so ContactsList and
     ContactDetail (which call term('contact')) leaked the generic noun.
  2. Only course_creator overrode session/sessions, so a lawyer's schedule
     surface read "Schedule Session" instead of Consultation. Lawyer,
     personal_services, contractor, and ministry now map the session noun
     to the word each trade actually uses.
  3. _vertical_intro_for_email had branches for 9 verticals; therapist and
     contractor silently fell through to "" — their confirmation emails
     shipped with no vertical voice at all.

  Assertions hit the override dicts and branch outputs DIRECTLY — get_term
  and the ""-fallback can never fail, so testing only through them would
  prove nothing (see feedback: tests that check nothing).
"""
from __future__ import annotations

import sys, pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import vertical_terminology as vt
from booking_confirmation_emails import _vertical_intro_for_email


# ── gap 1: contractor contact noun ───────────────────────────────────

def test_contractor_contact_override_exists():
    """Assert on the dict itself — get_term's BASE fallback also returns
    'Customer'-adjacent text, which is how this gap hid."""
    block = vt.VERTICAL_TERMS["contractor"]
    assert block.get("contact") == "Customer"
    assert block.get("contacts") == "Customers"


def test_contractor_customer_stays_base():
    """The deliberate decision the comment records: 'customer' is NOT
    overridden — BASE already says Customer for this vertical."""
    assert "customer" not in vt.VERTICAL_TERMS["contractor"]
    assert vt.get_term("contractor", "customer") == "Customer"


def test_contractor_people_register_resolves_customer():
    assert vt.get_term("contractor", "contact") == "Customer"
    assert vt.get_term("contractor", "contacts") == "Customers"


# ── gap 2: per-vertical session noun ─────────────────────────────────

SESSION_OVERRIDES = [
    ("lawyer",            "Consultation", "Consultations"),
    ("personal_services", "Appointment",  "Appointments"),
    ("contractor",        "Visit",        "Visits"),
    ("ministry",          "Meeting",      "Meetings"),
]


@pytest.mark.parametrize("vertical,singular,plural", SESSION_OVERRIDES)
def test_session_override_present_in_dict(vertical, singular, plural):
    block = vt.VERTICAL_TERMS[vertical]
    assert block.get("session") == singular, (
        f"{vertical}: session override missing — schedule surfaces will "
        f"read 'Session' instead of {singular}")
    assert block.get("sessions") == plural


@pytest.mark.parametrize("vertical,singular,plural", SESSION_OVERRIDES)
def test_session_matches_appointment_family(vertical, singular, plural):
    """Each vertical's session noun agrees with its appointment noun where
    one exists — the two keys land on the same scheduling surfaces.
    (personal_services keeps appointment at BASE, which IS 'Appointment',
    so the rule holds there too.)"""
    assert vt.get_term(vertical, "session") == vt.get_term(vertical, "appointment")
    assert vt.get_term(vertical, "sessions") == vt.get_term(vertical, "appointments")


def test_session_stays_base_where_it_fits():
    """Coach / fitness / therapist genuinely say Session — pin the decision
    NOT to override, so nobody 'completes the pattern' later."""
    for vertical in ("coach", "coaching", "fitness_wellness", "therapist"):
        assert "session" not in vt.VERTICAL_TERMS[vertical]
        assert vt.get_term(vertical, "session") == "Session"


def test_course_creator_session_unchanged():
    assert vt.VERTICAL_TERMS["course_creator"]["session"] == "Class"
    assert vt.VERTICAL_TERMS["course_creator"]["sessions"] == "Classes"


# ── gap 3: booking-confirmation intros ───────────────────────────────

def test_contractor_email_intro_is_dispatch_style():
    intro = _vertical_intro_for_email("contractor")
    assert intro, "contractor fell through to the empty generic intro"
    low = intro.lower()
    # The vertical_intelligence tone note: date + arrival window, access
    # cleared, vehicles moved, someone 18+ on site.
    assert "window" in low
    assert "vehicles" in low
    assert "18" in intro


def test_therapist_email_intro_is_sparse_and_non_clinical():
    intro = _vertical_intro_for_email("therapist")
    assert intro, "therapist fell through to the empty generic intro"
    low = intro.lower()
    assert "reschedul" in low or "cancellation" in low
    # HIPAA posture: scheduling/billing/admin only. A confirmation email is
    # often read by someone other than the client — nothing clinical, and
    # nothing about the content or purpose of the session.
    for banned in ("therapy", "treatment", "clinical", "diagnos",
                   "symptom", "session content", "goals"):
        assert banned not in low, f"therapist intro contains {banned!r}"
    # Sparse: one or two sentences, in line with the other branches.
    assert intro.count(".") <= 2


def test_unmapped_vertical_still_silent():
    """The generic fallback stays "" — don't bloat unmapped emails."""
    assert _vertical_intro_for_email("service_provider") == ""
    assert _vertical_intro_for_email(None) == ""
