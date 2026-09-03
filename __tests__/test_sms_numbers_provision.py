# __tests__/test_sms_numbers_provision.py
#
# Dedicated SMS numbers, phase C (2026-09-02): provisioning.
#
# The order of operations IS the safety property: row first (the partial
# unique index makes a race a 409, not two purchases), then buy, then
# attach — and each failure unwinds what came before it. These tests run
# the real handlers against an in-memory sms_numbers and a fake Twilio,
# and pin every branch of that unwind.

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import business_access
import billing_limits
import feature_gates
import sms_numbers_router as nr
import twilio_sms

BIZ = "aaaaaaaa-0000-0000-0000-000000000001"
OTHER = "bbbbbbbb-0000-0000-0000-000000000002"
USER = SimpleNamespace(user_id="u1", email="kevin@example.com")


def _run(coro):
    return asyncio.run(coro)


def _raises(coro, status):
    with pytest.raises(HTTPException) as ei:
        _run(coro)
    assert ei.value.status_code == status, ei.value.detail
    return ei.value.detail


@pytest.fixture
def world(monkeypatch):
    """In-memory sms_numbers + a fake Twilio. Every side effect recorded."""
    rows: list = []
    twilio_calls: list = []
    events: list = []
    live_count = {"n": 0}

    async def _sb_get(client, path):
        if path.startswith("/sms_numbers?status=in."):
            return [{"id": f"x{i}"} for i in range(live_count["n"])]
        if path.startswith("/sms_numbers?business_id=eq."):
            biz = path.split("business_id=eq.")[1].split("&")[0]
            live = [r for r in rows if r["business_id"] == biz and r["status"] in nr.LIVE_STATUSES]
            return live[:1]
        if path.startswith("/sms_numbers?id=eq."):
            rid = path.split("id=eq.")[1].split("&")[0]
            biz = path.split("business_id=eq.")[1].split("&")[0]
            return [r for r in rows if r["id"] == rid and r["business_id"] == biz][:1]
        if path.startswith("/sms_numbers?status=eq.releasing"):
            return [r for r in rows if r["status"] == "releasing"
                    and r.get("release_after") and r["release_after"] < datetime.now(timezone.utc).isoformat()]
        if path.startswith("/businesses?"):
            return [{"settings": {"phone": "(415) 555-0100"}}]
        return []

    async def _sb_post(client, path, body):
        if path == "/sms_numbers":
            if any(r["business_id"] == body["business_id"] and r["status"] in nr.LIVE_STATUSES for r in rows):
                return None   # the partial unique index
            row = {"id": f"row{len(rows) + 1}", **body}
            rows.append(row)
            return [row]
        if path == "/events":
            events.append(body)
            return [body]
        return [body]

    async def _sb_patch(client, path, body):
        rid = path.split("id=eq.")[1].split("&")[0]
        for r in rows:
            if r["id"] == rid:
                r.update(body)

    async def _sb_delete(client, path):
        rid = path.split("id=eq.")[1]
        rows[:] = [r for r in rows if r["id"] != rid]

    def search_numbers(area_code, limit=10):
        twilio_calls.append(("search", area_code))
        return [{"phone_number": f"+1{area_code}5550199", "friendly_name": "x", "locality": "SF", "region": "CA"}]

    def buy_number(phone):
        twilio_calls.append(("buy", phone))
        return {"sid": "PN_new", "phone_number": phone}

    def attach_to_service(sid):
        twilio_calls.append(("attach", sid))
        return "MG_test"

    def detach_from_service(sid):
        twilio_calls.append(("detach", sid))

    def release_number(sid):
        twilio_calls.append(("release", sid))

    async def _log_event(client, business_id, contact_id, event_type, data):
        events.append({"business_id": business_id, "event_type": event_type, "data": data})

    for name, fn in {"_sb_get": _sb_get, "_sb_post": _sb_post, "_sb_patch": _sb_patch,
                     "_sb_delete": _sb_delete, "_log_event": _log_event}.items():
        monkeypatch.setattr(nr, name, fn)
    for name, fn in {"search_numbers": search_numbers, "buy_number": buy_number,
                     "attach_to_service": attach_to_service,
                     "detach_from_service": detach_from_service,
                     "release_number": release_number}.items():
        monkeypatch.setattr(twilio_sms, name, fn)

    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r="member": "owner")
    monkeypatch.setattr(billing_limits, "require_feature", lambda b, f: None)
    monkeypatch.setattr(nr, "_twilio_configured", lambda: True)
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", "+15550000000")
    monkeypatch.delenv("SMS_NUMBERS_CAMPAIGN_CAP", raising=False)
    monkeypatch.delenv("SMS_NUMBER_RELEASE_GRACE_DAYS", raising=False)

    return SimpleNamespace(rows=rows, twilio=twilio_calls, events=events, live_count=live_count)


# ─── the happy path, in order ─────────────────────────────────────────

def test_provision_writes_row_then_buys_then_attaches(world):
    res = _run(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER))
    assert res["ok"] and res["number"]["phone_number"] == "+14155550199"
    assert res["number"]["status"] == "active"
    assert world.twilio == [("buy", "+14155550199"), ("attach", "PN_new")]
    row = world.rows[0]
    assert row["provider_sid"] == "PN_new" and row["messaging_service_sid"] == "MG_test"
    assert row["area_code"] == "415"
    assert [e["event_type"] for e in world.events] == ["sms_number_provisioned"]
    # Provider ids never reach the desk.
    assert "provider_sid" not in res["number"] and "messaging_service_sid" not in res["number"]


def test_provision_without_a_choice_takes_the_first_local_number(world):
    """'Just give me one' — area code from the business's own phone."""
    res = _run(nr.provision_number(nr.ProvisionBody(business_id=BIZ), USER))
    assert res["number"]["phone_number"] == "+14155550199"
    assert world.twilio[0] == ("search", "415")


def test_explicit_area_code_wins_over_the_default(world):
    _run(nr.provision_number(nr.ProvisionBody(business_id=BIZ, area_code="212"), USER))
    assert world.twilio[0] == ("search", "212")


# ─── every failure unwinds ────────────────────────────────────────────

def test_buy_failure_deletes_the_row(world, monkeypatch):
    def buy_number(phone):
        raise RuntimeError("21422 unavailable")
    monkeypatch.setattr(twilio_sms, "buy_number", buy_number)
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER), 502)
    assert detail["error"] == "purchase_failed"
    assert world.rows == []                       # nothing left behind
    assert not any(c[0] == "attach" for c in world.twilio)


def test_attach_failure_releases_the_number_and_marks_the_row(world, monkeypatch):
    def attach_to_service(sid):
        raise RuntimeError("service full")
    monkeypatch.setattr(twilio_sms, "attach_to_service", attach_to_service)
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER), 502)
    assert detail["error"] == "attach_failed"
    assert ("release", "PN_new") in world.twilio  # no paid, unattached line
    assert world.rows[0]["status"] == "released"
    assert world.rows[0]["provider_sid"] == "PN_new"   # the audit trail keeps the sid


# ─── the gates, before any purchase ───────────────────────────────────

def test_second_number_for_the_same_business_is_refused(world):
    _run(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER))
    world.twilio.clear()
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550100"), USER), 409)
    assert detail["error"] == "already_has_number"
    assert world.twilio == []


def test_campaign_cap_stops_provisioning(world, monkeypatch):
    monkeypatch.setenv("SMS_NUMBERS_CAMPAIGN_CAP", "3")
    world.live_count["n"] = 3
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER), 409)
    assert detail["error"] == "campaign_full"
    assert world.twilio == [] and world.rows == []


def test_unpinned_platform_number_refuses(world, monkeypatch):
    """Phase A's guarantee: no second number enters the pool until the
    shared lane is pinned."""
    monkeypatch.delenv("TWILIO_PLATFORM_NUMBER")
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER), 503)
    assert detail["error"] == "platform_number_unpinned"
    assert world.twilio == [] and world.rows == []


def test_plan_gate_is_a_402_with_the_frontend_contract(world, monkeypatch):
    def require_feature(b, f):
        raise HTTPException(402, {"error": "feature_locked", "feature": f, "required_plan": "practice"})
    monkeypatch.setattr(billing_limits, "require_feature", require_feature)
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER), 402)
    assert detail["error"] == "feature_locked" and detail["required_plan"] == "practice"
    assert "Twilio" not in detail["message"]
    assert world.twilio == []


def test_no_area_code_anywhere_asks_for_one(world, monkeypatch):
    async def _no_settings(client, path):
        return [{"settings": {}}] if path.startswith("/businesses?") else []
    monkeypatch.setattr(nr, "_sb_get", _no_settings)
    detail = _raises(nr.provision_number(nr.ProvisionBody(business_id=BIZ), USER), 400)
    assert detail["error"] == "area_code_required"


# ─── release, restore, sweep ──────────────────────────────────────────

def _provisioned(world):
    _run(nr.provision_number(nr.ProvisionBody(business_id=BIZ, phone_number="+14155550199"), USER))
    world.twilio.clear()
    return world.rows[0]


def test_release_holds_the_line_for_the_grace_window(world):
    row = _provisioned(world)
    res = _run(nr.release_number(row["id"], BIZ, USER))
    assert res["status"] == "releasing" and res["grace_days"] == 14
    after = datetime.fromisoformat(res["release_after"])
    assert timedelta(days=13, hours=23) < after - datetime.now(timezone.utc) <= timedelta(days=14)
    assert world.twilio == []                     # nothing handed back yet
    assert row["status"] == "releasing"


def test_release_is_scoped_to_the_business(world):
    row = _provisioned(world)
    _raises(nr.release_number(row["id"], OTHER, USER), 404)
    assert row["status"] == "active"


def test_restore_inside_the_window(world):
    row = _provisioned(world)
    _run(nr.release_number(row["id"], BIZ, USER))
    res = _run(nr.restore_number(row["id"], nr.RestoreBody(business_id=BIZ), USER))
    assert res["status"] == "active" and row["status"] == "active" and row["release_after"] is None


def test_restore_after_release_is_refused(world):
    row = _provisioned(world)
    row["status"] = "released"
    _raises(nr.restore_number(row["id"], nr.RestoreBody(business_id=BIZ), USER), 409)


def test_sweep_hands_back_only_what_is_due(world):
    due = _provisioned(world)
    due["status"] = "releasing"
    due["release_after"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    not_yet = {"id": "row9", "business_id": OTHER, "phone_number": "+12125550100",
               "status": "releasing", "provider_sid": "PN_other",
               "release_after": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()}
    world.rows.append(not_yet)
    stats = _run(nr.release_sweep())
    assert stats == {"checked": 1, "released": 1, "failed": 0}
    assert world.twilio == [("detach", "PN_new"), ("release", "PN_new")]
    assert due["status"] == "released" and due["released_at"]
    assert not_yet["status"] == "releasing"
    assert [e["event_type"] for e in world.events][-1] == "sms_number_released"


def test_sweep_one_failure_does_not_stop_the_rest(world, monkeypatch):
    a = _provisioned(world)
    a.update(status="releasing", release_after=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    b = {"id": "rowB", "business_id": OTHER, "phone_number": "+12125550100", "status": "releasing",
         "provider_sid": "PN_bad", "release_after": a["release_after"]}
    world.rows.append(b)

    def release_number(sid):
        if sid == "PN_bad":
            raise RuntimeError("20404")
        world.twilio.append(("release", sid))
    monkeypatch.setattr(twilio_sms, "release_number", release_number)
    stats = _run(nr.release_sweep())
    assert stats == {"checked": 2, "released": 1, "failed": 1}
    assert a["status"] == "released" and b["status"] == "releasing"


# ─── GET /sms/numbers: what the desk asks first ───────────────────────

def test_get_number_reports_eligibility(world):
    res = _run(nr.get_number(BIZ, USER))
    assert res == {"number": None, "eligible": True, "reason": None,
                   "required_plan": None, "grace_days": 14}


def test_get_number_after_provision_shows_the_line(world):
    _provisioned(world)
    res = _run(nr.get_number(BIZ, USER))
    assert res["number"]["phone_number"] == "+14155550199" and res["eligible"] is False
    assert res["reason"] is None            # not ineligible — they have one


def test_get_number_names_the_plan_when_locked(world, monkeypatch):
    def require_feature(b, f):
        raise HTTPException(402, {"error": "feature_locked", "required_plan": "practice"})
    monkeypatch.setattr(billing_limits, "require_feature", require_feature)
    res = _run(nr.get_number(BIZ, USER))
    assert res["eligible"] is False and res["reason"] == "plan" and res["required_plan"] == "practice"


# ─── wiring ───────────────────────────────────────────────────────────

def test_feature_is_gated_at_practice():
    assert feature_gates.FEATURE_MIN_PLAN[nr.FEATURE] == "practice"


def test_router_and_sweep_are_mounted():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "from sms_numbers_router import router as sms_numbers_router" in src
    assert "app.include_router(sms_numbers_router)" in src
    assert "_sms_numbers.release_sweep" in src


def test_twilio_helpers_exist_and_block():
    import inspect
    for name in ("search_numbers", "buy_number", "attach_to_service",
                 "detach_from_service", "release_number"):
        fn = getattr(twilio_sms, name)
        assert not inspect.iscoroutinefunction(fn), f"{name} must be blocking (run_in_threadpool)"
