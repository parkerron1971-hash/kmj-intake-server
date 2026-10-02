# __tests__/test_outbound_sender_pinned.py
#
# Every send names its sender (2026-09-02, dedicated numbers phase A).
#
# A Messaging Service send with no from_ lets Twilio pick ANY number in
# the service's pool. Harmless with one number in the pool; the moment
# a practitioner's own number joins it, an unpinned booking alert for
# Business A can go out from Business B's line. These tests pin the
# seam BEFORE any dedicated number exists:
#
#   1. twilio_sms.send_sms passes from_ (explicit, else the platform
#      number) alongside messaging_service_sid.
#   2. sender_for is the one resolver, and both send seams
#      (send_sms_core, _send_platform_sms) go through it.
#   3. _send_platform_sms cannot be called without a business_id —
#      the fake in test_outbound_integrity mirrors that.
#   4. Every production call site of _send_platform_sms names its
#      business (source-pinned, the way test_sms_tenant_isolation
#      pins the auth guards).

from __future__ import annotations

import asyncio
import inspect
import re
from types import SimpleNamespace

import pytest

import campaigns_router
import sms_alerts
import sms_routing
import sms_service
import twilio_sms


def _run(coro):
    return asyncio.run(coro)


class _FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(sid="SM_pinned")


@pytest.fixture
def twilio(monkeypatch):
    fake = _FakeMessages()
    monkeypatch.setattr(twilio_sms, "_twilio_client",
                        lambda: SimpleNamespace(messages=fake))
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MG_test")
    monkeypatch.setattr(twilio_sms, "_warned_unpinned", False)
    return fake


# ─── 1. the Twilio call itself ────────────────────────────────────────

def test_send_pins_platform_number_by_default(twilio, monkeypatch):
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550001111")
    sid = twilio_sms.send_sms("+15559998888", "hi")
    assert sid == "SM_pinned"
    call = twilio.calls[0]
    assert call["from_"] == "+15550001111"
    assert call["messaging_service_sid"] == "MG_test"   # service still applies


def test_explicit_from_number_wins_over_platform(twilio, monkeypatch):
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550001111")
    twilio_sms.send_sms("+15559998888", "hi", from_number="+15557772222")
    assert twilio.calls[0]["from_"] == "+15557772222"


def test_unset_platform_number_degrades_to_pool_with_warning(twilio, monkeypatch, caplog):
    """Missing env must not stop texts — it falls back to today's pool
    pick, loudly. (Provisioning a dedicated number is what refuses to
    run in this state; that lives in phase C.)"""
    monkeypatch.delenv("TWILIO_PLATFORM_NUMBER", raising=False)
    with caplog.at_level("WARNING", logger="twilio_sms"):
        twilio_sms.send_sms("+15559998888", "hi")
    assert "from_" not in twilio.calls[0]
    assert any("UNPINNED" in r.message for r in caplog.records)


# ─── 2. one resolver, both seams ──────────────────────────────────────

def test_sender_for_resolves_platform_number(monkeypatch):
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550001111")
    assert _run(sms_service.sender_for(None, "biz-1")) == "+15550001111"


def test_send_sms_core_passes_sender_for(monkeypatch):
    src = inspect.getsource(sms_service.send_sms_core)
    assert "sender_for(" in src and "from_number=from_number" in src, (
        "send_sms_core must resolve its sender through sender_for and "
        "hand it to twilio_sms.send_sms — otherwise Chief's and the "
        "scheduler's texts go out unpinned.")


def test_send_platform_sms_passes_sender_for(monkeypatch):
    seen = {}

    async def fake_sender_for(client, business_id):
        seen["business_id"] = business_id
        return "+15550001111"

    def fake_send(to, body, *, from_number=None):
        seen["from_number"] = from_number
        return "SM1"

    monkeypatch.setattr(sms_routing, "sender_for", fake_sender_for)
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    monkeypatch.setattr(sms_routing, "_twilio_configured", lambda: True)
    monkeypatch.setattr(twilio_sms, "send_sms", fake_send)

    sid = _run(sms_routing._send_platform_sms("+15559998888", "hi", business_id="biz-7"))
    assert sid == "SM1"
    assert seen == {"business_id": "biz-7", "from_number": "+15550001111"}


# ─── 3. business_id is not optional ───────────────────────────────────

def test_send_platform_sms_requires_business_id():
    sig = inspect.signature(sms_routing._send_platform_sms)
    param = sig.parameters["business_id"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        _run(sms_routing._send_platform_sms("+15559998888", "hi"))


# ─── 4. every call site names its business ────────────────────────────

_CALL = re.compile(r"send_platform_sms\(\s*([^)]*?)\)", re.S)


@pytest.mark.parametrize("module", [sms_routing, sms_alerts, campaigns_router])
def test_every_call_site_names_its_business(module):
    src = inspect.getsource(module)
    calls = [m.group(1) for m in _CALL.finditer(src)
             if not m.group(0).startswith("send_platform_sms(to_number")   # the def
             and "def " not in src[max(0, m.start() - 12):m.start()]]
    # Only real call expressions: skip the import line and the
    # parameter pass-through in campaigns_tick's _send_touch(...) call.
    calls = [c for c in calls if "," in c]
    assert calls, f"{module.__name__}: no call sites found — regex drift?"
    for args in calls:
        assert "business_id=" in args, (
            f"{module.__name__}: _send_platform_sms called without "
            f"business_id= — that send cannot name its sender:\n  ({args})")
