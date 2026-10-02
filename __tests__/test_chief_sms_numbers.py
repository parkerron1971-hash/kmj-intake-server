# __tests__/test_chief_sms_numbers.py
#
# Chief owns the number (dedicated numbers, phase F).
#
# Three verbs over sms_numbers_router's cores, plus sms_status learning
# to report the line. The cores are faked here — their own contract is
# pinned in test_sms_numbers_provision — so these tests are about what
# Chief SAYS: the number in the practitioner's words, never a Twilio
# code, and {result, label} on every branch (a missing key blanks the
# app).

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from fastapi import HTTPException

import chief_sms_actions as csa
import sms_numbers_router as numbers

BIZ = {"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "Glow Studio", "settings": {}}
E164 = "+14155550199"
PRETTY = "(415) 555-0199"


def _run(coro):
    return asyncio.run(coro)


def _shape(res: Dict[str, Any], verb: str):
    assert res["type"] == verb
    assert isinstance(res.get("result"), str) and res["result"]
    assert isinstance(res.get("label"), str) and res["label"]
    assert "Twilio" not in res["result"] and "PN" not in res["label"]
    return res


# ─── provision ────────────────────────────────────────────────────────

def test_provision_reports_the_number_in_plain_words(monkeypatch):
    seen = {}

    async def provision_core(client, business_id, *, phone_number=None, area_code=None, friendly_label=None):
        seen.update(business_id=business_id, phone_number=phone_number, area_code=area_code)
        return {"phone_number": E164, "status": "active", "area_code": "415"}

    monkeypatch.setattr(numbers, "provision_core", provision_core)
    res = _shape(_run(csa.handle_provision_sms_number(None, BIZ, {"type": "provision_sms_number", "area_code": "415"})), "provision_sms_number")
    assert seen == {"business_id": BIZ["id"], "phone_number": None, "area_code": "415"}
    assert PRETTY in res["result"] and "no keyword" in res["result"]
    assert res["label"] == f"Your number: {PRETTY}"
    assert res["number"] == E164 and not res.get("failed")


def test_provision_passes_a_chosen_number_through(monkeypatch):
    seen = {}

    async def provision_core(client, business_id, **kw):
        seen.update(kw)
        return {"phone_number": E164, "status": "active", "area_code": "415"}

    monkeypatch.setattr(numbers, "provision_core", provision_core)
    _run(csa.handle_provision_sms_number(None, BIZ, {"phone_number": E164}))
    assert seen["phone_number"] == E164


@pytest.mark.parametrize("detail, expect", [
    ({"error": "feature_locked", "required_plan": "practice"}, "Practice plan"),
    ({"error": "area_code_required"}, "Which area code"),
    ({"error": "no_numbers", "message": "No local numbers in 415 right now — try a nearby area code."}, "another area code"),
    ({"error": "platform_number_unpinned", "message": "Texting isn't ready for private numbers yet."}, "isn't ready"),
    ({"error": "purchase_failed", "message": "That number couldn't be reserved — pick another or try again."}, "couldn't be reserved"),
])
def test_provision_failures_speak_the_practitioners_language(monkeypatch, detail, expect):
    async def provision_core(client, business_id, **kw):
        raise HTTPException(402 if detail["error"] == "feature_locked" else 400, detail)

    monkeypatch.setattr(numbers, "provision_core", provision_core)
    res = _shape(_run(csa.handle_provision_sms_number(None, BIZ, {})), "provision_sms_number")
    assert res["failed"] is True
    assert expect in res["result"]


def test_provision_when_they_already_have_one_is_not_a_failure(monkeypatch):
    async def provision_core(client, business_id, **kw):
        raise HTTPException(409, {"error": "already_has_number",
                                  "number": {"phone_number": E164, "status": "active"}})

    monkeypatch.setattr(numbers, "provision_core", provision_core)
    res = _shape(_run(csa.handle_provision_sms_number(None, BIZ, {})), "provision_sms_number")
    assert not res.get("failed")
    assert "already have" in res["result"] and PRETTY in res["result"]


def test_provision_unexpected_error_is_a_calm_failure(monkeypatch):
    async def provision_core(client, business_id, **kw):
        raise RuntimeError("socket hung up")

    monkeypatch.setattr(numbers, "provision_core", provision_core)
    res = _shape(_run(csa.handle_provision_sms_number(None, BIZ, {})), "provision_sms_number")
    assert res["failed"] is True and "socket" not in res["result"]


# ─── release / restore ────────────────────────────────────────────────

def test_release_says_what_stops_and_the_way_back(monkeypatch):
    async def release_core(client, business_id, number_id=None):
        assert number_id is None            # Chief doesn't know row ids
        return {"ok": True, "status": "releasing", "release_after": "2026-09-16T12:00:00+00:00",
                "grace_days": 14, "number": {"phone_number": E164, "status": "releasing"}}

    monkeypatch.setattr(numbers, "release_core", release_core)
    res = _shape(_run(csa.handle_release_sms_number(None, BIZ, {})), "release_sms_number")
    assert PRETTY in res["result"]
    assert "stop reaching you now" in res["result"]
    assert "September 16" in res["result"]
    assert "bring it back" in res["result"]
    assert res["label"] == f"Releasing {PRETTY}"


def test_release_with_no_number(monkeypatch):
    async def release_core(client, business_id, number_id=None):
        raise HTTPException(404, {"error": "not_found"})

    monkeypatch.setattr(numbers, "release_core", release_core)
    res = _shape(_run(csa.handle_release_sms_number(None, BIZ, {})), "release_sms_number")
    assert res["failed"] is True and "don't have a private number" in res["result"]


def test_release_twice_is_informative_not_a_failure(monkeypatch):
    async def release_core(client, business_id, number_id=None):
        raise HTTPException(409, {"error": "not_releasable", "status": "releasing",
                                  "number": {"phone_number": E164, "release_after": "2026-09-16T12:00:00+00:00"}})

    monkeypatch.setattr(numbers, "release_core", release_core)
    res = _shape(_run(csa.handle_release_sms_number(None, BIZ, {})), "release_sms_number")
    assert not res.get("failed") and "already being released" in res["result"]


def test_restore_inside_the_window(monkeypatch):
    async def restore_core(client, business_id, number_id=None):
        return {"ok": True, "status": "active", "number": {"phone_number": E164, "status": "active"}}

    monkeypatch.setattr(numbers, "restore_core", restore_core)
    res = _shape(_run(csa.handle_restore_sms_number(None, BIZ, {})), "restore_sms_number")
    assert "yours again" in res["result"] and res["label"] == f"Your number: {PRETTY}"


@pytest.mark.parametrize("status, expect", [
    ("active", "already active"),
    ("released", "no longer held"),
])
def test_restore_when_there_is_nothing_to_restore(monkeypatch, status, expect):
    async def restore_core(client, business_id, number_id=None):
        raise HTTPException(409, {"error": "not_restorable", "status": status})

    monkeypatch.setattr(numbers, "restore_core", restore_core)
    res = _shape(_run(csa.handle_restore_sms_number(None, BIZ, {})), "restore_sms_number")
    assert res["failed"] is True and expect in res["result"]


# ─── sms_status knows about the number ────────────────────────────────

@pytest.fixture
def status_world(monkeypatch):
    state = {"keyword": None, "number": None}
    monkeypatch.setattr(csa, "_current_keyword", lambda b: state["keyword"])
    monkeypatch.setattr(csa, "_live_number", lambda b: state["number"])
    monkeypatch.setattr(csa, "_opted_out_count", lambda b: 0)
    import sms_service, sms_alerts
    monkeypatch.setattr(sms_service, "_twilio_configured", lambda: True)
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)
    return state


def test_status_with_own_number_is_ready_without_a_keyword(status_world):
    status_world["number"] = {"phone_number": E164, "status": "active"}
    res = _run(csa.handle_sms_status(None, BIZ, {}))
    assert res["label"] == "Texting — ready"
    assert f"your own number {PRETTY}" in res["result"]
    assert "optional" in res["result"]
    assert res["signal"]["has_number"] == 1 and res["signal"]["ready"] == 1
    assert res["own_number"] == E164


def test_status_without_either_still_needs_setup(status_world):
    res = _run(csa.handle_sms_status(None, BIZ, {}))
    assert res["label"] == "Texting — needs setup"
    assert "no keyword yet" in res["result"]
    assert res["signal"]["has_number"] == 0 and res["own_number"] is None


def test_status_names_a_number_on_its_way_out(status_world):
    status_world["keyword"] = "GLOW"
    status_world["number"] = {"phone_number": E164, "status": "releasing",
                              "release_after": "2026-09-16T12:00:00+00:00"}
    res = _run(csa.handle_sms_status(None, BIZ, {}))
    assert "being released" in res["result"] and "September 16" in res["result"]
    assert res["signal"]["has_number"] == 0          # not usable
    assert res["label"] == "Texting — ready"         # the keyword still carries it


# ─── the pretty-printer, since it's in every sentence ─────────────────

@pytest.mark.parametrize("raw, out", [
    ("+14155550199", "(415) 555-0199"),
    ("+442071234567", "+442071234567"),
    (None, ""),
])
def test_pretty_number(raw, out):
    assert csa._pretty_number(raw) == out
