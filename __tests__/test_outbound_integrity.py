# __tests__/test_outbound_integrity.py
#
# Outbound integrity (2026-07-31). Two holes, one branch:
#
#   1. Campaign SMS shipped UNBRANDED: campaigns_router._send_touch called
#      _send_platform_sms with the bare personalized body — no business
#      name, no opt-out — on the Twilio number every tenant shares. That
#      reopens exactly what PR #308 closed for broadcasts. These tests pin
#      the call site to compose_outbound_body(include_optout=True).
#
#   2. The composed site's contact form dead-ended: it validated, maybe
#      recorded sms_consents, sent a Resend email — and wrote NOTHING to
#      /contacts or /events. A visitor who filled the form never became a
#      lead. These tests pin find-or-create + the timeline event + dedup.

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from datetime import timezone
from unittest import mock

import pytest
from fastapi import HTTPException

import campaigns_router
import event_spine
import public_site
from sms_service import OPTOUT_TAIL


# ─── helpers ─────────────────────────────────────────────────────────

def _open_quiet_window():
    """A fake sms_alerts namespace whose quiet-hours window is always
    open (0-24 in UTC), with alerts on and consent granted."""
    async def has_sms_consent(client, business_id, phone):
        return True
    return SimpleNamespace(
        alerts_enabled=lambda: True,
        QUIET_TZ=timezone.utc,
        QUIET_SEND_START_HOUR=0,
        QUIET_SEND_END_HOUR=24,
        has_sms_consent=has_sms_consent,
    )


def _run_send_touch(touch_body: str, biz_name: str = "Craft & Co",
                    quiet: bool = False):
    """Drive _send_touch's SMS branch with everything external mocked.
    Returns (result, sent_bodies, stored_bodies, claims)."""
    from sms_service import normalize_phone

    biz = {"id": "biz-1", "name": biz_name}
    camp = {"id": "camp-1", "business_id": "biz-1", "name": "Win-back"}
    touch = {"channel": "sms", "body": touch_body}
    contact = {"id": "c-1", "name": "Sam", "phone": "+15551234567"}

    sms_alerts = _open_quiet_window()
    if quiet:
        sms_alerts.QUIET_SEND_START_HOUR = 0
        sms_alerts.QUIET_SEND_END_HOUR = 0   # window never open

    sent, stored, claims = [], [], []

    async def send_platform_sms(phone, body, *, business_id, client=None):
        # business_id is keyword-only and REQUIRED on the real seam —
        # the fake mirrors that so a call site that drops it fails here.
        sent.append((phone, body))
        return "SM123"

    async def store_sms(client, business_id, contact_id, phone_number,
                        message, direction, telnyx_id="", sent_by=None):
        stored.append((phone_number, message, direction))

    def fake_post(path, payload, prefer="return=representation"):
        claims.append((path, payload))
        return [{"id": "row-1"}]

    email_sender = SimpleNamespace()   # unused on the sms branch

    with mock.patch.object(campaigns_router.sb_clients,
                           "sb_post_as_service", side_effect=fake_post):
        result = asyncio.run(campaigns_router._send_touch(
            biz, camp, 0, touch, contact,
            email_sender, sms_alerts, send_platform_sms,
            store_sms, normalize_phone))
    return result, sent, stored, claims


# ─── 1. campaign SMS branding ────────────────────────────────────────

def test_campaign_sms_leads_with_business_name():
    result, sent, stored, _ = _run_send_touch("Hi {{first_name}}, we miss you!")
    assert result == "sms"
    assert len(sent) == 1
    _, body = sent[0]
    assert body.startswith("Craft & Co: ")
    assert "Hi Sam, we miss you!" in body          # personalization intact


def test_campaign_sms_carries_the_opt_out():
    _, sent, _, _ = _run_send_touch("Hi {{first_name}}, we miss you!")
    assert sent[0][1].endswith(OPTOUT_TAIL)
    assert "STOP" in sent[0][1].upper()


def test_stored_body_matches_what_was_sent():
    """The sms_messages ledger must show the message the recipient saw —
    branded, tail and all — not the raw draft."""
    _, sent, stored, _ = _run_send_touch("Hi {{first_name}}, we miss you!")
    assert stored[0][1] == sent[0][1]
    assert stored[0][2] == "outbound"


def test_already_branded_touch_is_not_double_prefixed():
    """compose_outbound_body idempotence must hold at THIS call site:
    Chief drafting 'Craft & Co: ...' must not become
    'Craft & Co: Craft & Co: ...'."""
    _, sent, _, _ = _run_send_touch("Craft & Co: come back for a trim.")
    assert sent[0][1].count("Craft & Co:") == 1


def test_exactly_once_claim_still_precedes_the_send():
    """Branding must not have reordered the ledger claim: the
    campaign_sends row is written before the carrier call."""
    _, sent, _, claims = _run_send_touch("Hi there")
    send_claims = [p for p, _ in claims if p == "/campaign_sends"]
    assert send_claims, "campaign_sends claim disappeared"


def test_quiet_hours_deferral_survives():
    """Outside the send window _send_touch must still raise _Defer
    BEFORE claiming or sending anything."""
    with pytest.raises(campaigns_router._Defer):
        _run_send_touch("Hi there", quiet=True)


# ─── 2. contact form → contact + event ───────────────────────────────

def _capture(body_email="Visitor@Example.com", phone="", message="Hello!",
             get_results=None, post_result=None):
    """Run _capture_contact_from_form with sb_clients + event_spine
    mocked. get_results is a list popped per sb_get_as_service call."""
    import sb_clients

    gets, posts, patches, events = [], [], [], []
    get_results = list(get_results or [])

    def fake_get(path):
        gets.append(path)
        return get_results.pop(0) if get_results else []

    def fake_post(path, payload, prefer="return=representation"):
        posts.append((path, payload))
        if post_result is not None:
            return post_result
        return [{"id": "new-c-1"}]

    def fake_patch(path, payload):
        patches.append((path, payload))
        return [{"id": "c-1"}]

    def fake_emit(event_type, business_id, data=None, contact_id=None,
                  source="system"):
        events.append({"event_type": event_type, "business_id": business_id,
                       "data": data, "contact_id": contact_id,
                       "source": source})
        return True

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(sb_clients, "sb_post_as_service", side_effect=fake_post), \
         mock.patch.object(sb_clients, "sb_patch_as_service", side_effect=fake_patch), \
         mock.patch.object(event_spine, "emit", side_effect=fake_emit):
        contact_id = public_site._capture_contact_from_form(
            "biz-1", "Visitor V", body_email, phone, message)
    return contact_id, gets, posts, patches, events


def test_new_submission_creates_a_lead_contact():
    contact_id, gets, posts, patches, events = _capture()
    assert contact_id == "new-c-1"
    contact_posts = [p for p in posts if p[0] == "/contacts"]
    assert len(contact_posts) == 1
    payload = contact_posts[0][1]
    assert payload["business_id"] == "biz-1"
    assert payload["status"] == "lead"
    assert payload["source"] == "website_contact_form"
    assert payload["email"] == "visitor@example.com"   # lowercased
    assert payload["metadata"]["website_form_messages"][0]["message"] == "Hello!"
    assert not patches


def test_submission_writes_a_timeline_event():
    contact_id, _, _, _, events = _capture()
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "contact_form_submitted"
    assert ev["business_id"] == "biz-1"
    assert ev["contact_id"] == "new-c-1"
    assert ev["data"]["new_contact"] is True
    assert ev["data"]["message_preview"] == "Hello!"


def test_repeat_submission_dedups_by_email():
    """Same visitor twice = ONE contact: the second submission updates
    (last_interaction + appended message), never creates."""
    existing = [{"id": "c-1", "phone": None,
                 "metadata": {"website_form_messages": [
                     {"at": "2026-07-30T00:00:00Z", "message": "First!"}]}}]
    contact_id, gets, posts, patches, events = _capture(
        get_results=[existing])
    assert contact_id == "c-1"
    assert not [p for p in posts if p[0] == "/contacts"]   # no second row
    assert len(patches) == 1
    path, payload = patches[0]
    assert "id=eq.c-1" in path and "business_id=eq.biz-1" in path
    assert "last_interaction" in payload
    msgs = payload["metadata"]["website_form_messages"]
    assert [m["message"] for m in msgs] == ["First!", "Hello!"]
    assert events[0]["data"]["new_contact"] is False


def test_email_match_is_scoped_to_the_business_and_case_insensitive():
    _capture()
    _, gets, _, _, _ = _capture()
    lookup = gets[0]
    assert "business_id=eq.biz-1" in lookup
    assert "email=ilike." in lookup


def test_email_lookup_escapes_like_wildcards():
    """jo_n@x.com must not match joan@x.com — '_' is a LIKE wildcard."""
    _, gets, _, _, _ = _capture(body_email="jo_n@x.com")
    assert "%5C_" in gets[0]        # url-encoded backslash-underscore


def test_falls_back_to_phone_match_when_email_unknown():
    existing = [{"id": "c-9", "phone": "+15551234567", "metadata": {}}]
    contact_id, gets, posts, patches, _ = _capture(
        phone="(555) 123-4567",
        get_results=[[], existing])     # email miss, phone hit
    assert contact_id == "c-9"
    assert any("phone=eq." in g for g in gets)
    assert not [p for p in posts if p[0] == "/contacts"]
    assert len(patches) == 1


def test_capture_never_raises():
    import sb_clients
    with mock.patch.object(sb_clients, "sb_get_as_service",
                           side_effect=RuntimeError("db down")):
        assert public_site._capture_contact_from_form(
            "biz-1", "V", "v@x.com", "", "hi") is None


# ─── endpoint wiring: capture ordering + rate-limit gate ─────────────

def _fake_request(host="1.2.3.4"):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_endpoint_captures_contact_even_when_email_is_unconfigured():
    """Lead capture must not depend on the Resend leg: with no
    RESEND_API_KEY the endpoint still writes the contact first."""
    import brand_engine
    captured = []
    with mock.patch.object(public_site, "_check_contact_rate", return_value=True), \
         mock.patch.object(public_site, "_capture_contact_from_form",
                           side_effect=lambda *a, **k: captured.append((a, k)) or "c-1"), \
         mock.patch.object(brand_engine, "get_bundle",
                           return_value={"footer": {"contact_email": "op@x.com"}}), \
         mock.patch.object(brand_engine, "_sb_get", return_value=[]), \
         mock.patch.dict("os.environ", {"RESEND_API_KEY": ""}, clear=False):
        res = asyncio.run(public_site.contact_submit_endpoint(
            "biz-1", {"name": "V", "email": "v@x.com", "message": "hi"},
            _fake_request()))
    assert captured and captured[0][0][0] == "biz-1"
    # THE LEAD ARC PR 6: the endpoint also hands over where they came
    # from. Positional args unchanged; attribution rides as a keyword.
    assert "attribution" in captured[0][1]
    assert res["ok"] is False       # email leg unconfigured, capture done


def test_rate_limit_blocks_before_any_db_write():
    """The 429 must fire before contact capture — the spam gate guards
    the write path, not just the email."""
    with mock.patch.object(public_site, "_check_contact_rate",
                           return_value=False), \
         mock.patch.object(public_site, "_capture_contact_from_form") as cap:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(public_site.contact_submit_endpoint(
                "biz-1", {"name": "V", "email": "v@x.com", "message": "hi"},
                _fake_request()))
    assert exc.value.status_code == 429
    cap.assert_not_called()


# ─── catalog ─────────────────────────────────────────────────────────

def test_contact_form_submitted_is_cataloged():
    assert "contact_form_submitted" in event_spine.EVENT_CATALOG
