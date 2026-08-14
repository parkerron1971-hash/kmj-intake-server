"""
test_lead_door_defects.py — THE LEAD ARC PR 3.

Two defects on the anonymous lead doors:

  1. /intake/submit trusted a caller-supplied business_id and never
     compared it to the form it had just loaded by id. form_id is
     PUBLIC — it sits in the embed snippet on the practitioner's own
     website — so a submission could be written into any other tenant.

  2. Three anonymous endpoints keyed their per-IP limiter on
     request.client.host, which behind Railway is the PROXY. Every
     visitor to every published site shared one bucket. rate_limit
     already documents this and exists to solve it; intake_endpoint
     already used it. The concierge went further and hashed the same
     value into its per-VISITOR identity.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import intake_endpoint
import rate_limit


# ═══════════════════════════════════════════════════════════════════════
# 1. The cross-tenant write
# ═══════════════════════════════════════════════════════════════════════

class _Req:
    """Minimal stand-in for a Starlette Request."""
    def __init__(self, xff=None, peer="10.0.0.1"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": peer})()


def _submit(form_business_id, claimed_business_id):
    """Drive /intake/submit far enough to reach the ownership check."""
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        if path.startswith("/intake_forms"):
            return [{"id": "form-1", "business_id": form_business_id,
                     "fields": [], "settings": {}, "form_type": "general",
                     "name": "Contact"}]
        if path.startswith("/businesses"):
            return [{"id": claimed_business_id, "name": "Victim Co",
                     "type": "general", "voice_profile": {}}]
        if method == "POST":
            return [{"id": "c-1"}]
        return []

    body = intake_endpoint.IntakeSubmission(
        form_id="form-1", business_id=claimed_business_id,
        data={"name": "Attacker", "email": "a@example.com"})

    import lead_identity
    # The contact write goes through lead_identity now — one dedupe
    # rule shared by all five doors — which uses sb_clients, not
    # this module's supabase_request helper. Patched so the
    # ownership check below is what the test is measuring.
    with mock.patch("lead_identity.resolve",
                    return_value=lead_identity.Resolution(
                        contact_id="c-1", created=True)), \
         mock.patch.object(intake_endpoint, "supabase_request", side_effect=fake_sb), \
         mock.patch.object(intake_endpoint, "get_supabase_url", return_value="https://x"), \
         mock.patch.object(intake_endpoint, "get_supabase_anon", return_value="k"), \
         mock.patch.object(intake_endpoint, "get_anthropic_key", return_value=""), \
         mock.patch.object(intake_endpoint, "_intake_rate_ok", return_value=True), \
         mock.patch("lead_scoring.score_and_store",
                    return_value=__import__("lead_scoring").LeadScore(score=50)):
        try:
            result = asyncio.run(intake_endpoint.submit_intake(body, _Req()))
            return result, calls, None
        except Exception as e:
            return None, calls, e


def test_a_submission_cannot_be_written_into_another_business():
    """The whole defect: form-1 belongs to biz-owner, the caller says
    biz-victim, and it used to land in biz-victim's contacts."""
    result, calls, err = _submit(form_business_id="biz-owner",
                                 claimed_business_id="biz-victim")
    assert result is None, "the mismatched submission was accepted"
    assert getattr(err, "status_code", None) == 404
    writes = [c for c in calls if c[0] == "POST"]
    assert not writes, f"rows were written before the check: {writes}"


def test_the_mismatch_does_not_confirm_that_either_id_exists():
    """404 and the same detail as a missing form. A 403, or a different
    message, would turn this endpoint into an oracle for which form ids
    and business ids are real."""
    _, _, mismatch = _submit("biz-owner", "biz-victim")
    assert mismatch.status_code == 404
    assert mismatch.detail == "Form not found"


def test_the_honest_submission_still_goes_through():
    """The negative control. Without it, a check that rejects
    EVERYTHING would pass the test above."""
    result, calls, err = _submit(form_business_id="biz-1",
                                 claimed_business_id="biz-1")
    assert err is None, err
    assert result["success"] is True
    # lead_identity performs the insert; the point here is that the
    # honest submission was not rejected by the ownership check.
    assert result["contact_id"] == "c-1"


# ═══════════════════════════════════════════════════════════════════════
# 2. The limiter that was keyed on the proxy
# ═══════════════════════════════════════════════════════════════════════

def test_trusted_client_ip_separates_two_visitors_behind_one_proxy():
    """The property the fix depends on, stated directly."""
    a = rate_limit.trusted_client_ip(_Req(xff="203.0.113.7", peer="10.0.0.1"))
    b = rate_limit.trusted_client_ip(_Req(xff="198.51.100.4", peer="10.0.0.1"))
    assert a != b
    # request.client.host cannot tell them apart — that WAS the bug.
    assert _Req(xff="203.0.113.7").client.host == _Req(xff="198.51.100.4").client.host


ANON_DOORS = [
    ("public_site.py", ["contact_submit_endpoint"]),
    ("site_concierge.py", ["_visitor_key", "public_chat", "public_lead"]),
]


def test_no_anonymous_lead_door_keys_on_the_socket_peer():
    """A sweep, so the next endpoint added to these files cannot quietly
    reintroduce it. `request.client.host` is the Railway proxy: one
    bucket for the whole platform, and the sixth real contact-form
    submission in a minute refused."""
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for filename, _ in ANON_DOORS:
        for n, line in enumerate(
                (root / filename).read_text(encoding="utf-8").splitlines(), 1):
            if "request.client.host" in line and not line.strip().startswith("#"):
                offenders.append(f"{filename}:{n}: {line.strip()}")
    assert not offenders, offenders


def test_the_concierge_visitor_identity_is_per_person():
    """_visitor_key feeds the per-visitor DAILY message cap. Keyed on
    the proxy, two strangers on the same browser shared one identity and
    one person's conversation ate another's allowance."""
    import site_concierge
    same_ua = {"user-agent": "Mozilla/5.0"}

    def req(xff):
        r = _Req(xff=xff)
        r.headers = dict(same_ua, **{"x-forwarded-for": xff})
        return r

    assert site_concierge._visitor_key(req("203.0.113.7")) \
        != site_concierge._visitor_key(req("198.51.100.4"))


def test_the_same_visitor_keeps_one_identity():
    import site_concierge
    r1, r2 = _Req(xff="203.0.113.7"), _Req(xff="203.0.113.7")
    r1.headers = {"x-forwarded-for": "203.0.113.7", "user-agent": "UA"}
    r2.headers = {"x-forwarded-for": "203.0.113.7", "user-agent": "UA"}
    assert site_concierge._visitor_key(r1) == site_concierge._visitor_key(r2)


# ═══════════════════════════════════════════════════════════════════════
# 3. The brief model is a dial, not a constant
# ═══════════════════════════════════════════════════════════════════════

def test_notif_model_can_be_changed_without_a_deploy():
    import importlib
    import os
    with mock.patch.dict(os.environ, {"NOTIF_MODEL": "claude-haiku-4-5-20251001"}):
        ne = importlib.reload(importlib.import_module("notification_engine"))
        assert ne.NOTIF_MODEL == "claude-haiku-4-5-20251001"
    ne = importlib.reload(importlib.import_module("notification_engine"))
    assert ne.NOTIF_MODEL.startswith("claude-sonnet"), "default must stay Sonnet"
