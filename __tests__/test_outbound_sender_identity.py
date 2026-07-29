"""
test_outbound_sender_identity.py — the recipient must know who is texting.

THE ARCHITECTURE THIS PROTECTS (rather than replaces)
  The platform runs ONE registered A2P 10DLC brand and one number for every
  business. sms_routing solves the hard direction — a customer texts a
  keyword once, gets bound, and every later message routes to the right
  practitioner. That is the correct and only zero-per-operator-cost way to
  do compliant multi-tenant SMS.

  The hole was the other direction. sms_routing's own auto-replies brand
  themselves ("Solutionist System: You're now connected with X"), but
  Chief-initiated sends and broadcasts went out as the bare message body. A
  rebooking nudge arrived from an unfamiliar number with nothing saying
  which business it came from.

  On a SHARED campaign that is not merely confusing. Unrecognised outbound
  earns STOP replies and spam reports, and those land on the number every
  operator shares. Sender recognition matters MORE on one number, not less.

  Under Direct the registered sender stays the platform — a practitioner's
  name may appear in the BODY only. These tests pin it to exactly there.
"""
from __future__ import annotations

import pytest

from sms_service import compose_outbound_body, OPTOUT_TAIL, MAX_BRAND_PREFIX


# ── the core behaviour ───────────────────────────────────────────────

def test_business_name_leads_the_message():
    out = compose_outbound_body("Craft & Co", "You're due for a trim.")
    assert out == "Craft & Co: You're due for a trim."


def test_recipient_can_tell_who_it_is_from():
    """The whole point, stated as the user-visible property."""
    out = compose_outbound_body("Bethel Church", "Service moved to 10am.")
    assert out.startswith("Bethel Church")


# ── idempotence: no double-branding ──────────────────────────────────

def test_message_that_already_names_the_business_is_left_alone():
    """Chief often writes 'Craft & Co here —' on its own. That must not
    become 'Craft & Co: Craft & Co here —'."""
    body = "Craft & Co here — you're due for a trim."
    assert compose_outbound_body("Craft & Co", body) == body


def test_self_identification_match_is_case_insensitive():
    body = "CRAFT & CO: your appointment is confirmed."
    assert compose_outbound_body("Craft & Co", body) == body


def test_composing_twice_is_stable():
    once = compose_outbound_body("Craft & Co", "Trim time.")
    twice = compose_outbound_body("Craft & Co", once)
    assert once == twice


# ── the opt-out tail ─────────────────────────────────────────────────

def test_first_message_carries_the_way_out():
    out = compose_outbound_body("Craft & Co", "Welcome!", include_optout=True)
    assert out.endswith(OPTOUT_TAIL)


def test_later_messages_do_not_repeat_it():
    """Stapling opt-out language to every text burns characters and reads
    like spam. It belongs on the first one."""
    out = compose_outbound_body("Craft & Co", "See you Thursday.")
    assert OPTOUT_TAIL not in out


def test_optout_not_duplicated_when_the_author_already_wrote_it():
    body = "Welcome! Reply STOP to opt out."
    out = compose_outbound_body("Craft & Co", body, include_optout=True)
    assert out.upper().count("STOP") == 1


# ── edges ────────────────────────────────────────────────────────────

def test_missing_business_name_still_returns_a_sendable_message():
    """A name lookup that fails must never swallow the practitioner's
    message — degraded branding beats an unsent text."""
    assert compose_outbound_body("", "Hello there.") == "Hello there."
    assert compose_outbound_body(None, "Hello there.") == "Hello there."


def test_missing_name_still_honours_the_optout_flag():
    out = compose_outbound_body(None, "Hello.", include_optout=True)
    assert out.endswith(OPTOUT_TAIL)


def test_empty_message_stays_empty():
    """send_sms_core rejects blank bodies upstream; this must not invent
    one out of the brand prefix."""
    assert compose_outbound_body("Craft & Co", "") == ""
    assert compose_outbound_body("Craft & Co", "   ") == ""


def test_absurdly_long_name_is_truncated_not_dropped():
    name = "The Extremely Long Neighbourhood Barbershop And Grooming Emporium"
    out = compose_outbound_body(name, "Trim time.")
    prefix = out.split(":")[0]
    assert len(prefix) <= MAX_BRAND_PREFIX
    assert out.endswith("Trim time.")
    assert prefix.startswith("The Extremely Long")


def test_whitespace_is_normalised():
    assert compose_outbound_body("  Craft & Co  ", "  Trim.  ") == "Craft & Co: Trim."


# ── the seam is actually wired ───────────────────────────────────────

def test_send_sms_core_composes_before_sending():
    """Guards against the branding being added to the helper but never
    called — the failure mode where every test above passes and no real
    message is ever branded."""
    import inspect
    import sms_service
    src = inspect.getsource(sms_service.send_sms_core)
    assert "compose_outbound_body" in src, (
        "send_sms_core no longer composes the outbound body — Chief's texts "
        "would go out unbranded again")


def test_broadcast_composes_before_sending():
    import inspect
    import sms_routing
    src = inspect.getsource(sms_routing.broadcast)
    assert "compose_outbound_body" in src, (
        "broadcast no longer brands its body — the single most spam-prone "
        "outbound on a shared campaign")


def test_the_stored_body_is_the_sent_body():
    """The practitioner's thread must show what the customer RECEIVED, not
    the draft it was written from. send_sms_core rebinds `message` before
    both the provider call and _store_sms, so one variable serves both."""
    import inspect
    import sms_service
    src = inspect.getsource(sms_service.send_sms_core)
    compose_at = src.index("compose_outbound_body")
    # Every later use of the body must come after composition.
    for marker in ("twilio_sms.send_sms", "_store_sms"):
        if marker in src:
            assert src.index(marker) > compose_at, (
                f"{marker} runs BEFORE the body is branded")
