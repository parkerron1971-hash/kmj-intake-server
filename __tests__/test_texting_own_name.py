"""Texting under each business's own name, step 4b: the name and the mixed rule (2026-10-11).

Kevin, 2026-10-11: once a business texts under its own registered name, its
texts lead with its name, and (the mixed rule) confirmations and reminders
reach everyone they reach today, while texts it writes and offers go only to
people who agreed under its name since it registered, or have texted it.
Pinned here:
  1. Whether a business texts under its own name, and since when.
  2. Confirmations and reminders lead with the business's name then; the
     shared number's words are unchanged otherwise.
  3. A text the owner (or Chief) writes is refused, before anything is sent,
     to someone who agreed only before the switch; it goes to someone who
     agreed since, or texted since.
  4. Offers and automatic notes: on for a business texting under its own
     name, with the offers box ticked since; the shared switch stays off.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import outreach_journeys as oj  # noqa: E402
import sms_alerts  # noqa: E402
import sms_routing  # noqa: E402
import sms_service  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
SINCE = "2026-10-12T15:00:00+00:00"
OWN = {"number": "+12165550100", "since": SINCE}


def run(x):
    return asyncio.run(x)


@pytest.fixture
def db(monkeypatch):
    """sms_routing's reads, answered from a table of path → rows."""
    state = {"answers": {}, "reads": []}

    async def get(client, path):
        state["reads"].append(path)
        for key, rows in state["answers"].items():
            if key in path:
                return rows
        return []

    monkeypatch.setattr(sms_routing, "_sb_get", get)
    return state


# ── 1. texting under its own name, since when ─────────────────────────

def test_own_registration_needs_its_number_in_its_own_account(db):
    assert run(sms_routing.own_registration(None, BIZ)) is None
    db["answers"] = {"/sms_numbers?": [{"phone_number": "+12165550100"}],
                     "/texting_registrations?": [{"twilio": {"sent_at": SINCE}}]}
    assert run(sms_routing.own_registration(None, BIZ)) == OWN
    assert "account_sid=not.is.null" in db["reads"][-2] and "status=in.(active,suspended)" in db["reads"][-2]
    assert run(sms_routing.own_registration(None, None)) is None


def test_agreed_under_its_own_name_means_since_the_switch(db):
    assert run(sms_routing.agreed_under_own_name(None, BIZ, "+15559998888", SINCE)) is False
    consent, inbound = db["reads"][-2], db["reads"][-1]
    assert "consented_at=gte.2026-10-12T15%3A00%3A00%2B00%3A00" in consent and f"business_id=eq.{BIZ}" in consent
    assert "direction=eq.inbound" in inbound and "created_at=gte.2026-10-12T15" in inbound
    db["answers"] = {"/sms_messages?": [{"id": 1}]}
    assert run(sms_routing.agreed_under_own_name(None, BIZ, "+15559998888", SINCE)) is True      # texted since
    assert run(sms_routing.agreed_under_own_name(None, BIZ, "+15559998888", SINCE,
                                                 source="booking_marketing")) is False          # not for offers
    db["answers"] = {"source=eq.booking_marketing": [{"id": 2}]}
    assert run(sms_routing.agreed_under_own_name(None, BIZ, "+15559998888", SINCE, source="booking_marketing"))


# ── 2. the name on confirmations and reminders ────────────────────────

def test_confirmations_and_reminders_lead_with_the_business_once_its_own():
    own = sms_alerts.confirmation_text("Ann", "KMJ Creative Solutions", "Tuesday, October 14", "3:00 PM",
                                       own_name=True)
    assert own == ("KMJ Creative Solutions: Hi Ann, your booking is confirmed for Tuesday, October 14 at "
                   "3:00 PM. Reply to this message with any questions. Reply STOP to opt out.")
    rem = sms_alerts.reminder_text("KMJ Creative Solutions", "Tuesday", "3:00 PM", own_name=True)
    assert rem.startswith("Reminder from KMJ Creative Solutions: your appointment is Tuesday at 3:00 PM.")
    for text in (own, rem):
        assert "Solutionist" not in text and "STOP" in text
        assert sms_alerts.segments(text) <= 2 if hasattr(sms_alerts, "segments") else True
    shared = sms_alerts.confirmation_text("Ann", "KMJ Creative Solutions", "Tuesday, October 14", "3:00 PM")
    assert shared.startswith("Solutionist System: Hi Ann, your booking with KMJ Creative Solutions")   # unchanged


def test_the_confirmation_asks_which_name_to_lead_with(monkeypatch):
    sent = []

    async def consent(client, biz, phone):
        return True

    async def own(client, biz):
        return OWN

    async def send(phone, body, *, business_id, client=None):
        sent.append(body)
        return "SM1"

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(sms_alerts, "has_sms_consent", consent)
    monkeypatch.setattr(sms_alerts, "own_registration", own)
    monkeypatch.setattr(sms_alerts, "_send_platform_sms", send)
    monkeypatch.setattr(sms_alerts, "_find_contact_by_phone", nothing)
    monkeypatch.setattr(sms_alerts, "_store_sms", nothing)
    monkeypatch.setattr(sms_alerts, "_log_event", nothing)
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)
    out = run(sms_alerts.send_booking_confirmation(
        business={"id": BIZ, "name": "KMJ Creative Solutions", "settings": {}},
        entry_data={"phone": "(555) 999-8888"}, customer_name="Ann Lee", appointment_iso="2026-10-14T19:00:00Z"))
    assert out["status"] == "sent" and sent[0].startswith("KMJ Creative Solutions: Hi Ann, your booking is confirmed")


# ── 3. a text the owner writes ────────────────────────────────────────

class _Stop(Exception):
    pass


@pytest.fixture
def core(monkeypatch):
    import no_card_trial
    sent = []

    async def ok(*a, **k):
        return None

    async def not_out(client, phone, biz):
        return False

    async def reached(client, biz):
        raise _Stop()                                   # past the gate: the send would go ahead

    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    monkeypatch.setattr(no_card_trial, "check_async", ok)
    monkeypatch.setattr(sms_service, "is_opted_out", not_out)
    monkeypatch.setattr(sms_service, "_find_contact_by_phone", ok)
    monkeypatch.setattr(sms_service, "_business_name", reached)
    import twilio_sms
    monkeypatch.setattr(twilio_sms, "send_sms", lambda *a, **k: sent.append(a) or "SM1")
    return sent


@pytest.mark.parametrize("agreed", [False, True])
def test_a_text_the_owner_writes_follows_the_mixed_rule(core, monkeypatch, agreed):
    seen = {}

    async def own(client, biz):
        return OWN

    async def agree(client, biz, phone, since, **kw):
        seen.update(phone=phone, since=since)
        return agreed

    monkeypatch.setattr(sms_routing, "own_registration", own)
    monkeypatch.setattr(sms_routing, "agreed_under_own_name", agree)
    if agreed:
        with pytest.raises(_Stop):
            run(sms_service.send_sms_core(None, business_id=BIZ, to="(555) 999-8888", message="See you Tuesday"))
    else:
        with pytest.raises(sms_service.SmsSendError) as e:
            run(sms_service.send_sms_core(None, business_id=BIZ, to="(555) 999-8888", message="See you Tuesday"))
        assert e.value.status == 422 and "before your business registered its own number" in str(e.value)
        assert "confirmations and reminders still reach them" in str(e.value)
    assert seen == {"phone": "+15559998888", "since": SINCE} and core == []    # nothing sent either way here


def test_a_business_not_registered_texts_as_today(core, monkeypatch):
    async def none(client, biz):
        return None

    async def never(*a, **k):
        raise AssertionError("no rule to check")

    monkeypatch.setattr(sms_routing, "own_registration", none)
    monkeypatch.setattr(sms_routing, "agreed_under_own_name", never)
    with pytest.raises(_Stop):
        run(sms_service.send_sms_core(None, business_id=BIZ, to="(555) 999-8888", message="hi"))


# ── 4. offers and automatic notes ─────────────────────────────────────

@pytest.mark.parametrize("own,ticked_since,expect", [
    (OWN, True, "sms"), (OWN, False, "email"), (None, True, "email"),       # the shared switch stays off
])
def test_offers_text_only_a_business_under_its_own_name(monkeypatch, own, ticked_since, expect):
    import contact_fields
    import email_sender
    seen = {}

    async def own_reg(client, biz):
        return own

    async def agree(client, biz, phone, since, *, source=None):
        seen.update(since=since, source=source)
        return ticked_since

    async def not_out(client, phone, biz):
        return False

    monkeypatch.delenv("JOURNEY_TEXTS", raising=False)
    monkeypatch.setattr(sms_routing, "own_registration", own_reg)
    monkeypatch.setattr(sms_routing, "agreed_under_own_name", agree)
    monkeypatch.setattr(sms_alerts, "is_opted_out", not_out)
    monkeypatch.setattr(contact_fields, "sms_opted_out", lambda c: False)
    for name in ("email_opted_out", "can_email", "email_ok"):
        if hasattr(email_sender, name):
            monkeypatch.setattr(email_sender, name, lambda *a, **k: True if name != "email_opted_out" else False)
    contact = {"phone": "+15559998888", "email": "ann@example.com"}
    got = run(oj._channel(None, {"id": BIZ, "name": "KMJ"}, contact))
    assert (got == "sms") == (expect == "sms")
    if own:
        assert seen == {"since": SINCE, "source": oj.MARKETING_CONSENT}
