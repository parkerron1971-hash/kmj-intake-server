"""Action Ledger Stage 0 — the two dispatchers that ran with no gate.

notification_engine had NO auth dependency anywhere in the module and
/act executes any of Chief's 151 handler verbs; it was fail-closed only
by accident (its _sb used the anon key, so RLS returned nothing and the
practitioner's "Yes, do that" button silently 404'd). chief_scheduler
ran any verb unprompted on a recurrence with no registry consultation.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402


def _user(uid="owner1"):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "owner1", "is_active": True, "name": "b1",
        "type": "coach", "settings": {}})
    fb.rows("business_users").append({
        "id": "s_v", "business_id": "b1", "user_id": "v1",
        "role": "viewer", "status": "active"})
    fb.rows("business_users").append({
        "id": "s_m", "business_id": "b1", "user_id": "m1",
        "role": "member", "status": "active"})
    return fb


# ─── notification_engine ─────────────────────────────────────────────

def test_every_notification_route_requires_auth():
    """The regression that matters: a route in this module with no auth
    dependency is how the hole existed in the first place."""
    import notification_engine as ne
    from auth_supabase import require_user
    unprotected = []
    for route in ne.router.routes:
        path = getattr(route, "path", "")
        if path.endswith("/health"):
            continue                      # health is deliberately open
        params = inspect.signature(route.endpoint).parameters
        has_user = any(
            getattr(p.default, "dependency", None) is require_user
            for p in params.values())
        if not has_user:
            unprotected.append(path)
    assert not unprotected, f"unauthenticated notification routes: {unprotected}"


def test_act_authorizes_caller_against_the_notifications_business(fake, monkeypatch):
    import notification_engine as ne

    async def _fake_sb(client, method, path, body=None):
        if path.startswith("/chief_notifications?id=eq.n1"):
            return [{"id": "n1", "business_id": "b1", "title": "t",
                     "action_payload": {"type": "create_task", "title": "x"}}]
        return []
    monkeypatch.setattr(ne, "_sb", _fake_sb)

    # A stranger with a valid JWT but no seat is refused.
    with pytest.raises(HTTPException) as e:
        asyncio.run(ne.execute_notification_action("n1", _user("stranger")))
    assert e.value.status_code == 403


def test_act_refuses_bulk_verbs(fake, monkeypatch):
    """One click must not fire an unattended bulk send — the registry's
    standing rule, which this path never consulted."""
    import notification_engine as ne

    async def _fake_sb(client, method, path, body=None):
        if path.startswith("/chief_notifications?id=eq.n2"):
            return [{"id": "n2", "business_id": "b1", "title": "t",
                     "action_payload": {"type": "batch_email"}}]
        return []
    monkeypatch.setattr(ne, "_sb", _fake_sb)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ne.execute_notification_action("n2", _user("owner1")))
    assert e.value.status_code == 400
    assert "bulk" in str(e.value.detail).lower()


def test_act_refuses_unclassified_verbs(fake, monkeypatch):
    import notification_engine as ne

    async def _fake_sb(client, method, path, body=None):
        if path.startswith("/chief_notifications?id=eq.n3"):
            return [{"id": "n3", "business_id": "b1", "title": "t",
                     "action_payload": {"type": "not_a_real_verb"}}]
        return []
    monkeypatch.setattr(ne, "_sb", _fake_sb)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ne.execute_notification_action("n3", _user("owner1")))
    assert e.value.status_code == 400


def test_sb_uses_service_role_not_anon():
    """The anon key made every read return [] under RLS — the engine
    could not read its own rows. Service role + the auth gate above."""
    src = pathlib.Path(
        _here.parent / "notification_engine.py").read_text(encoding="utf-8")
    body = src.split("async def _sb(")[1].split("async def ")[0]
    assert "sb_service_role()" in body
    assert "_supabase_anon()" not in body


# ─── chief_scheduler ─────────────────────────────────────────────────

def test_scheduler_refuses_bulk_and_stamps_the_class(fake, monkeypatch):
    import chief_scheduler as cs
    patched = {}
    monkeypatch.setattr(cs.sb_clients, "sb_patch_as_service",
                        lambda p, b: patched.update(b) or [])
    audited = {}
    import audit_log
    monkeypatch.setattr(audit_log, "record",
                        lambda biz, **kw: audited.update(kw) or True)

    asyncio.run(cs._execute_row({
        "id": "r1", "business_id": "b1", "recurrence": "weekly",
        "action": {"type": "batch_email"}, "label": "blast"}))
    assert patched.get("status") == "failed"
    # Stage 3 routed this through policy_engine; the refusal now carries
    # the engine's plainer sentence ("affects many records at once")
    # rather than the word "bulk". Assert the OUTCOME, not the wording.
    assert "unattended" in (patched.get("last_error") or "").lower()
    assert audited.get("ok") is False


def test_scheduler_records_reversibility_and_cadence(fake, monkeypatch):
    """A class-C verb on a recurrence still runs (recurring invoices are
    a real feature) — but the ledger now says so in authorized_by."""
    import chief_scheduler as cs
    monkeypatch.setattr(cs.sb_clients, "sb_patch_as_service", lambda p, b: [])
    audited = {}
    import audit_log
    monkeypatch.setattr(audit_log, "record",
                        lambda biz, **kw: audited.update(kw) or True)

    async def _handler(client, biz, action):
        return {"result": "sent", "label": "Invoice sent"}
    from chief_of_staff import ACTION_HANDLERS
    monkeypatch.setitem(ACTION_HANDLERS, "send_invoice", _handler)

    asyncio.run(cs._execute_row({
        "id": "r2", "business_id": "b1", "recurrence": "monthly",
        "action": {"type": "send_invoice"}, "label": "monthly invoice"}))
    # Stage 3: the shared evaluator produces the rule; cadence lives in
    # payload.recurrence rather than being duplicated into the string.
    assert audited["payload"]["authorized_by"] == "scheduled:C:unattended"
    assert audited["payload"]["recurrence"] == "monthly"
    assert audited["ok"] is True
