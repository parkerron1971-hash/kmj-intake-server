# __tests__/test_texts_bill_as_plain_text.py
#
# Texts are billed per segment, and one character outside the GSM-7
# alphabet switches the WHOLE message to UCS-2: 70 characters a segment
# instead of 160. The appointment reminder carried an em dash, so every
# reminder billed as 3 segments where 2 would do. Chief-written texts
# pick up curly quotes and dashes the same way, and a long business name
# was cut with "…".
#
#   1. twilio_sms.gsm_safe swaps typography that has an exact plain
#      stand-in; emoji and other deliberate characters are left alone.
#   2. Both ways a text leaves (send_sms and the TwiML auto-reply) apply it.
#   3. The automated templates are GSM-7 at the source, and the reminder
#      for a realistic booking is 2 segments, not 3.

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import sms_alerts
import sms_routing
import sms_service
import twilio_sms
from twilio_sms import gsm_safe, is_gsm7, segments


# ─── 1. the normaliser ────────────────────────────────────────────────

@pytest.mark.parametrize("fancy, plain", [
    ("Fresh Cutz — see you", "Fresh Cutz - see you"),
    ("2–3 pm", "2-3 pm"),
    ("Kevin’s chair", "Kevin's chair"),
    ("“Booked”", '"Booked"'),
    ("one more thing…", "one more thing..."),
    ("10 AM", "10 AM"),
])
def test_typography_becomes_plain(fancy, plain):
    assert gsm_safe(fancy) == plain
    assert is_gsm7(gsm_safe(fancy))


def test_plain_text_is_untouched_and_idempotent():
    s = "Fresh Cutz: see you tomorrow 2:30 PM. Need to change it? Reply here."
    assert gsm_safe(s) == s
    assert gsm_safe(gsm_safe("a — b")) == gsm_safe("a — b")


def test_emoji_is_a_choice_and_stays():
    assert gsm_safe("See you soon 💈") == "See you soon 💈"
    assert not is_gsm7("See you soon 💈")


def test_segment_counting():
    assert segments("x" * 160) == 1
    assert segments("x" * 161) == 2
    assert segments("x" * 306) == 2
    assert segments("x" * 307) == 3
    assert segments("—" + "x" * 69) == 1
    assert segments("—" + "x" * 70) == 2
    assert segments("[" * 80) == 1   # extended chars count double: 160
    assert segments("[" * 81) == 2


# ─── 2. every text leaves through it ──────────────────────────────────

class _FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(sid="SM_plain")


def test_send_sms_sends_the_plain_version(monkeypatch):
    fake = _FakeMessages()
    monkeypatch.setattr(twilio_sms, "_twilio_client", lambda: SimpleNamespace(messages=fake))
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG_test")
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550000000")
    twilio_sms.send_sms("+15551112222", "Fresh Cutz — you’re booked…")
    assert fake.calls[0]["body"] == "Fresh Cutz - you're booked..."


def test_auto_replies_go_through_it_too():
    # The inbound webhook answers HELP / keyword binds as TwiML; that body
    # never reaches send_sms, so it must be normalised where it is built.
    src = inspect.getsource(twilio_sms.twilio_inbound_sms)
    assert "escape(gsm_safe(reply))" in src


# ─── 3. the templates themselves ──────────────────────────────────────

def test_reminder_is_two_segments_not_three():
    text = sms_alerts.reminder_text("Fresh Cutz Barber Studio", "tomorrow", "2:30 PM")
    assert is_gsm7(text), text
    assert segments(text) == 2


def test_confirmation_is_plain():
    text = sms_alerts.confirmation_text("Marcus", "Fresh Cutz Barber Studio", "Thu Oct 9", "2:30 PM")
    assert is_gsm7(text), text
    assert segments(text) == 2


def test_routing_replies_are_plain_at_the_source():
    src = inspect.getsource(sms_routing)
    for phrase in ("We're here - email", "- send your message."):
        assert phrase in src


def test_long_brand_is_cut_with_plain_dots():
    name = "The Extremely Long Neighbourhood Barbershop And Grooming Emporium"
    out = sms_service.compose_outbound_body(name, "Trim time.")
    prefix = out.split(":")[0]
    assert prefix.endswith("...")
    assert len(prefix) <= sms_service.MAX_BRAND_PREFIX
    assert is_gsm7(out)
