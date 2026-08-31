"""Composer slot/override writes require a seat on the named business.

The previous pattern was:

    _: UserSession = Depends(sb_clients.authed_request)

That proves somebody is signed in, then discards the session. The
handler still takes `business_id` from the path or body and writes
through service-role storage, so RLS never applies. Business ids are
public (embed snippets). Any practitioner could upload, clear, reroll,
or override another practice's live site, and the DALL-E diag routes
would bill that tenant's cap.

These tests EXECUTE the endpoints (architecture R3) with FastAPI's
dependency chain intact — not just inspect source. The owner of a
brand-new business (owner_id set, no business_users row — the #464
shape) still gets in; a stranger gets the indistinguishable 404
business_access uses on purpose.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sb_clients
from agents.override_system import router as override_router
from agents.slot_system import router as slot_router
from auth_supabase import AuthedUser, UserSession


OWNER_ID = "11111111-1111-1111-1111-111111111111"
STRANGER_ID = "99999999-9999-9999-9999-999999999999"
BIZ = "22222222-2222-2222-2222-222222222222"
SLOT = "hero_main"


def _session(uid: str) -> UserSession:
    return UserSession(
        user=AuthedUser(id=uid, email="test@example.com", role="authenticated"),
        token="test-jwt",
    )


def _sb_get(owner_id: str, member_role=None):
    """Stand-in for the two reads business_access + role_of make."""
    def _get(path, *a, **kw):
        if path.startswith("/businesses?"):
            return [{"id": BIZ, "owner_id": owner_id}]
        if path.startswith("/business_users?"):
            return [{"role": member_role}] if member_role else []
        return []
    return _get


def _app(uid: str) -> FastAPI:
    app = FastAPI()
    app.include_router(slot_router.router)
    app.include_router(override_router.router)
    app.dependency_overrides[sb_clients.authed_request] = lambda: _session(uid)
    return app


@pytest.fixture
def owner_client(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb_get(OWNER_ID))
    return TestClient(_app(OWNER_ID), raise_server_exceptions=False)


@pytest.fixture
def stranger_client(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _sb_get(OWNER_ID))
    return TestClient(_app(STRANGER_ID), raise_server_exceptions=False)


@pytest.fixture
def member_client(monkeypatch):
    monkeypatch.setattr(
        sb_clients, "sb_get_as_service", _sb_get(OWNER_ID, member_role="member"))
    return TestClient(_app(STRANGER_ID), raise_server_exceptions=False)


# ── Source: the discarded-session pattern is gone ──────────────────


def test_slot_writes_use_business_access_admin():
    for fn in (slot_router.upload_slot, slot_router.clear_slot,
               slot_router.remove_slot, slot_router.restore_slot,
               slot_router.reroll_slot):
        src = inspect.getsource(fn)
        assert 'business_access("admin")' in src, fn.__name__
        assert "_: UserSession" not in src, fn.__name__


def test_slot_manifest_is_a_read():
    src = inspect.getsource(slot_router.get_slot_manifest)
    assert 'business_access("viewer")' in src


def test_dalle_body_routes_assert_access_before_spend():
    for fn in (slot_router.diag_dalle_generate, slot_router.diag_simulate_spend):
        src = inspect.getsource(fn)
        assert "assert_access" in src
        # The gate must run before the work that costs money / mutates.
        gate = src.index("assert_access")
        for marker in ("generate_dalle_image", "add_synthetic_spend",
                       "can_dalle_generate", "set_slot_default"):
            at = src.find(marker)
            if at != -1:
                assert gate < at, f"{fn.__name__}: assert_access after {marker}"


def test_override_upsert_asserts_access_before_the_write():
    src = inspect.getsource(override_router.upsert_override)
    assert "assert_access" in src
    gate = src.index("assert_access")
    write = src.index("persisted = override_storage.upsert_override")
    assert gate < write, "gate must run before the write"


def test_override_path_writes_use_admin():
    for fn in (override_router.delete_one_override,
               override_router.delete_override_by_path):
        src = inspect.getsource(fn)
        assert 'business_access("admin")' in src


def test_override_reads_are_viewer():
    for fn in (override_router.list_overrides_for_business,
               override_router.get_one_override,
               override_router.diag_list_targets_in_preview):
        src = inspect.getsource(fn)
        assert 'business_access("viewer")' in src


# ── Execution: stranger cannot mutate another practice ─────────────


def test_stranger_cannot_clear_another_business_slot(stranger_client, monkeypatch):
    called = []
    monkeypatch.setattr(
        slot_router.slot_storage, "clear_slot_custom",
        lambda *a, **k: called.append(True) or True)
    res = stranger_client.post(f"/slots/{BIZ}/{SLOT}/clear")
    assert res.status_code == 404, res.text
    assert called == []


def test_stranger_cannot_upsert_an_override(stranger_client, monkeypatch):
    called = []
    monkeypatch.setattr(
        override_router.override_storage, "upsert_override",
        lambda **k: called.append(k) or {"id": "x"})
    res = stranger_client.post("/chief/override", json={
        "business_id": BIZ,
        "override_type": "text",
        "target_path": "hero/headline",
        "override_value": "hijacked",
    })
    assert res.status_code == 404, res.text
    assert called == []


def test_stranger_cannot_read_the_slot_manifest(stranger_client):
    res = stranger_client.get(f"/slots/{BIZ}")
    assert res.status_code == 404, res.text


def test_stranger_cannot_spend_dalle_on_another_business(stranger_client, monkeypatch):
    called = []
    monkeypatch.setattr(
        slot_router, "add_synthetic_spend_for_testing",
        lambda **k: called.append(k) or True)
    res = stranger_client.post("/slots/_diag/dalle_spend_simulate", json={
        "business_id": BIZ,
        "cost_usd": 0.45,
    })
    assert res.status_code == 404, res.text
    assert called == []


# ── Execution: the owner of a new business (no seat row) still works ─


def test_owner_can_clear_their_own_slot(owner_client, monkeypatch):
    monkeypatch.setattr(
        slot_router.slot_storage, "clear_slot_custom", lambda *a, **k: True)
    monkeypatch.setattr(
        slot_router.slot_storage, "get_slot", lambda *a, **k: {})
    monkeypatch.setattr(
        slot_router.slot_storage, "can_reroll", lambda *a, **k: (True, 0))
    monkeypatch.setattr(slot_router, "_refresh_composed", lambda *a, **k: None)
    res = owner_client.post(f"/slots/{BIZ}/{SLOT}/clear")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("success") is True
    assert "slot" in body


def test_owner_can_upsert_an_override(owner_client, monkeypatch):
    monkeypatch.setattr(
        override_router.override_storage, "get_override", lambda *a, **k: None)
    monkeypatch.setattr(
        override_router.override_storage, "upsert_override",
        lambda **k: {"id": "ov-1", "status": "active", **k})
    monkeypatch.setattr(
        override_router.override_storage, "mark_overrides_status",
        lambda *a, **k: True)
    res = owner_client.post("/chief/override", json={
        "business_id": BIZ,
        "override_type": "text",
        "target_path": "hero/headline",
        "override_value": "Hello",
    })
    assert res.status_code == 200, res.text
    assert res.json().get("id") == "ov-1"


def test_owner_can_read_the_slot_manifest(owner_client, monkeypatch):
    monkeypatch.setattr(
        slot_router.slot_storage, "get_slot", lambda *a, **k: {})
    monkeypatch.setattr(
        slot_router.slot_storage, "can_reroll", lambda *a, **k: (True, 0))
    res = owner_client.get(f"/slots/{BIZ}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["business_id"] == BIZ
    assert isinstance(body.get("slots"), list)
    assert any(s.get("slot_name") == SLOT for s in body["slots"])


# ── Seats: a member can look, cannot rewrite the live site ─────────


def test_member_can_read_slots_but_cannot_clear(member_client, monkeypatch):
    monkeypatch.setattr(
        slot_router.slot_storage, "get_slot", lambda *a, **k: {})
    monkeypatch.setattr(
        slot_router.slot_storage, "can_reroll", lambda *a, **k: (True, 0))
    read = member_client.get(f"/slots/{BIZ}")
    assert read.status_code == 200, read.text

    called = []
    monkeypatch.setattr(
        slot_router.slot_storage, "clear_slot_custom",
        lambda *a, **k: called.append(True) or True)
    write = member_client.post(f"/slots/{BIZ}/{SLOT}/clear")
    assert write.status_code == 404, write.text
    assert called == []
