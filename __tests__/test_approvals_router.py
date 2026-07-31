"""S11 close-out — /approvals endpoints (approvals_router.py).

Pins:
  * role matrix: viewer/member/stranger 403, manager/owner 200
  * every approve writes an audit_log row (actor_type='user') — and a
    FAILED approve writes one too (ok=false), the reason this router exists
  * idempotency: re-approving a non-draft is 409, never a double-send
  * cross-tenant queue ids are 404 (business filter in the lookup)
  * dismiss flips status + audits, same ladder
  * the endpoint executes through chief_of_staff._do_approve_one — the
    SAME core the approve_draft verb uses (no forked send path)
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import approvals_router as ar  # noqa: E402
import chief_of_staff  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


def _u(uid):
    return type("U", (), {"id": uid})()


def _member(fb, uid, role, biz="b1", status="active"):
    fb.rows("business_users").append({
        "id": f"m_{uid}", "business_id": biz, "user_id": uid,
        "invited_email": f"{uid}@x.com", "role": role, "status": status})


def _draft(fb, qid, biz="b1", status="draft", contact_id="c1", subject="Follow up"):
    row = {
        "id": qid, "business_id": biz, "contact_id": contact_id,
        "agent": "nurture", "action_type": "email", "channel": "email",
        "subject": subject, "body": "Hi there", "status": status,
        "priority": "medium", "ai_reasoning": "quiet contact",
        "created_at": "2026-07-31T00:00:00Z",
    }
    fb.rows("agent_queue").append(row)
    return row


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)

    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1",
                                  "name": "Biz One", "settings": {}})
    fb.rows("businesses").append({"id": "b2", "owner_id": "owner2",
                                  "name": "Biz Two", "settings": {}})
    _member(fb, "v1", "viewer")
    _member(fb, "mem1", "member")
    _member(fb, "mg1", "manager")
    fb.rows("contacts").append({"id": "c1", "business_id": "b1",
                                "name": "Jane", "email": "jane@x.com",
                                "health_score": 50})

    # chief_of_staff._do_approve_one runs for real against the fake:
    # route its _sb through FakeSB and stub only the Resend hop.
    fb.sent = []

    async def fake_sb(client, method, path, body=None):
        if method == "GET":
            return fb.get(path)
        if method == "PATCH":
            return fb.patch(path, body)
        if method == "POST":
            return fb.post(path, body)
        raise AssertionError(f"unexpected {method}")

    async def fake_send(client, biz, item):
        fb.sent.append(dict(item))
        return {"sent": True, "reason": None, "to_email": "jane@x.com",
                "to_name": "Jane", "provider_id": "re_1"}

    monkeypatch.setattr(chief_of_staff, "_sb", fake_sb)
    monkeypatch.setattr(chief_of_staff, "_send_queued_email", fake_send)
    return fb


def _approve(biz, qid, uid, payload=None):
    return asyncio.run(ar.approve_draft_endpoint(biz, qid, payload, _u(uid)))


def _dismiss(biz, qid, uid, payload=None):
    return asyncio.run(ar.dismiss_draft_endpoint(biz, qid, payload, _u(uid)))


def _audit_rows(fb, verb=None):
    rows = fb.rows("audit_log")
    return [r for r in rows if verb is None or r.get("verb") == verb]


# ─── Role matrix ─────────────────────────────────────────────────────

def test_role_matrix(fake):
    fb = fake
    for qid in ("q_mg", "q_own"):
        _draft(fb, qid)

    for uid in ("v1", "mem1", "stranger"):
        with pytest.raises(HTTPException) as e:
            _approve("b1", "q_mg", uid)
        assert e.value.status_code == 403, uid

    out = _approve("b1", "q_mg", "mg1")
    assert out["ok"] is True and out["sent"] is True and out["status"] == "sent"

    out2 = _approve("b1", "q_own", "owner1")
    assert out2["ok"] is True

    # dismiss walks the same ladder
    _draft(fb, "q_d1")
    with pytest.raises(HTTPException) as e:
        _dismiss("b1", "q_d1", "mem1")
    assert e.value.status_code == 403
    assert _dismiss("b1", "q_d1", "mg1")["status"] == "dismissed"


# ─── Audit rows ──────────────────────────────────────────────────────

def test_approve_writes_user_audit_row(fake):
    fb = fake
    _draft(fb, "q1")
    _approve("b1", "q1", "mg1")
    rows = _audit_rows(fb, "approve_draft")
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "user"
    assert row["actor_id"] == "mg1"
    assert row["ok"] is True
    assert row["business_id"] == "b1"
    assert row["target_type"] == "agent_queue" and row["target_id"] == "q1"
    assert row["result"].get("sent") is True


def test_failed_approve_is_audited_too(fake, monkeypatch):
    fb = fake
    _draft(fb, "q1")

    async def boom(client, biz, item):
        raise RuntimeError("resend exploded")

    monkeypatch.setattr(chief_of_staff, "_do_approve_one", boom)
    with pytest.raises(HTTPException) as e:
        _approve("b1", "q1", "mg1")
    assert e.value.status_code == 500
    rows = _audit_rows(fb, "approve_draft")
    assert len(rows) == 1
    assert rows[0]["ok"] is False
    assert "resend exploded" in (rows[0]["error"] or "")
    assert rows[0]["actor_type"] == "user" and rows[0]["actor_id"] == "mg1"


def test_dismiss_writes_audit_row(fake):
    fb = fake
    _draft(fb, "q1")
    _dismiss("b1", "q1", "mg1")
    rows = _audit_rows(fb, "dismiss_draft")
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "user" and rows[0]["ok"] is True
    item = [r for r in fb.rows("agent_queue") if r["id"] == "q1"][0]
    assert item["status"] == "dismissed" and item.get("reviewed_at")


# ─── Idempotency / 409s / 404s ───────────────────────────────────────

def test_reapprove_is_409_never_double_send(fake):
    fb = fake
    _draft(fb, "q1")
    _approve("b1", "q1", "mg1")
    assert len(fb.sent) == 1
    with pytest.raises(HTTPException) as e:
        _approve("b1", "q1", "owner1")
    assert e.value.status_code == 409
    assert "sent" in e.value.detail
    assert len(fb.sent) == 1          # the seam: no second delivery

    for status in ("approved", "dismissed"):
        _draft(fb, f"q_{status}", status=status)
        with pytest.raises(HTTPException) as e2:
            _approve("b1", f"q_{status}", "owner1")
        assert e2.value.status_code == 409
        with pytest.raises(HTTPException) as e3:
            _dismiss("b1", f"q_{status}", "owner1")
        assert e3.value.status_code == 409


def test_unknown_and_cross_tenant_are_404(fake):
    fb = fake
    _draft(fb, "q_other", biz="b2")
    # b1's manager pointing at b2's draft through b1 — not found, not 403
    with pytest.raises(HTTPException) as e:
        _approve("b1", "q_other", "mg1")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e2:
        _approve("b1", "nope", "owner1")
    assert e2.value.status_code == 404
    with pytest.raises(HTTPException) as e3:
        _approve("no-such-biz", "q_other", "owner1")
    assert e3.value.status_code == 404
    assert fb.sent == []
    assert _audit_rows(fb) == []      # nothing executed, nothing audited


# ─── Shared core (no forked send path) ───────────────────────────────

def test_endpoint_runs_through_the_verbs_core(fake, monkeypatch):
    """The endpoint must execute chief_of_staff._do_approve_one — the
    exact function the approve_draft verb uses — not a re-implementation."""
    fb = fake
    _draft(fb, "q1")
    calls = []
    real = chief_of_staff._do_approve_one

    async def spy(client, biz, item):
        calls.append(item["id"])
        return await real(client, biz, item)

    monkeypatch.setattr(chief_of_staff, "_do_approve_one", spy)
    _approve("b1", "q1", "mg1")
    assert calls == ["q1"]


def test_endpoint_and_verb_leave_identical_state(fake):
    """Behavior parity: the HTTP approve and the Chief verb produce the
    same row status, sent_at, and event — proof there is one machinery."""
    fb = fake
    _draft(fb, "q_http")
    _draft(fb, "q_verb")

    _approve("b1", "q_http", "owner1")
    biz = fb.get("/businesses?id=eq.b1&limit=1")[0]
    asyncio.run(chief_of_staff.handle_approve_draft(
        None, biz, {"queue_id": "q_verb"}))

    rows = {r["id"]: r for r in fb.rows("agent_queue")}
    for qid in ("q_http", "q_verb"):
        assert rows[qid]["status"] == "sent"
        assert rows[qid].get("sent_at") and rows[qid].get("reviewed_at")
    events = [e for e in fb.rows("events")
              if e.get("event_type") == "agent_message_sent"]
    assert len(events) == 2
    assert len(fb.sent) == 2


def test_approve_with_edits_sends_the_edited_text(fake):
    fb = fake
    _draft(fb, "q1")
    out = _approve("b1", "q1", "mg1",
                   ar.ApproveBody(subject="New subject", body="New body"))
    assert out["ok"] is True
    item = [r for r in fb.rows("agent_queue") if r["id"] == "q1"][0]
    assert item["subject"] == "New subject" and item["body"] == "New body"
    assert fb.sent[0]["body"] == "New body"
    assert _audit_rows(fb, "approve_draft")[0]["payload"].get("edited") is True


# ─── Route registration ──────────────────────────────────────────────

def test_routes_exist_and_require_auth():
    from auth_supabase import require_user
    paths = {r.path for r in ar.router.routes}
    assert "/approvals/{business_id}/{queue_id}/approve" in paths
    assert "/approvals/{business_id}/{queue_id}/dismiss" in paths
    for r in ar.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_router_is_registered_in_the_app():
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "from approvals_router import router as approvals_router" in src
    assert "app.include_router(approvals_router)" in src
