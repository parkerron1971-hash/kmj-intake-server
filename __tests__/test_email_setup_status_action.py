"""Chief's `email_setup_status` read — "is my email set up?", answered.

Covers: nothing connected; verified + inbox + test (fully live); verified
with no test yet (one step left); waiting on DNS; drift flagged with a
next step; provider unreachable reports the stored state and says so;
an inbox that has stopped syncing is called out; the handler is
registered and classified as a read.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import chief_email_setup_actions as cea  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


VERIFIED = {
    "domain": "studiok.com", "from_local_part": "hello", "from_name": "Sarah from Studio K",
    "resend_domain_id": "dom_1", "status": "verified", "records": [],
    "verified_at": _iso(72),
}


def _biz(cfg=None, name="Studio K"):
    settings = {"email_domain": cfg} if cfg is not None else {}
    return {"id": "b1", "name": name, "settings": settings}


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    return fb


def _live(monkeypatch, status):
    async def _s(domain_id):
        return status
    monkeypatch.setattr(cea, "_live_status", _s)


def run(biz):
    return asyncio.run(cea.handle_email_setup_status(None, biz, {"type": "email_setup_status"}))


def test_registered_as_a_read():
    import action_registry as reg
    import chief_of_staff as cos
    assert cos.ACTION_HANDLERS["email_setup_status"] is cea.handle_email_setup_status
    assert reg.REGISTRY["email_setup_status"]["effect"] == reg.READ


def test_nothing_connected(fake):
    out = run(_biz())
    assert out["type"] == "email_setup_status" and out["result"] and out["label"]
    assert "no domain connected" in out["result"]
    assert "step 1" in out["result"]
    assert out["signal"]["ready"] is False
    assert out["nav"] == {"tab": "build", "sub": "email-setup"}


def test_fully_live(fake, monkeypatch):
    _live(monkeypatch, "verified")
    fake.rows("google_mailboxes").append(
        {"business_id": "b1", "google_email": "sarah@studiok.com", "last_synced_at": _iso(0.1)})
    cfg = {**VERIFIED, "last_test": {"id": "m1", "identity": "custom", "sent_at": _iso(1)}}
    out = run(_biz(cfg))
    assert "sending as Sarah from Studio K <hello@studiok.com>, verified" in out["result"]
    assert "sarah@studiok.com connected and syncing" in out["result"]
    assert "test email landed" in out["result"]
    assert "Next:" not in out["result"]
    assert out["label"].endswith("Email: live")
    assert out["signal"] == {"ready": True, "verified": True, "domain": "studiok.com",
                             "mailboxes": 1, "next_step": None}


def test_verified_but_no_test_yet_names_step_four(fake, monkeypatch):
    _live(monkeypatch, "verified")
    fake.rows("google_mailboxes").append(
        {"business_id": "b1", "google_email": "sarah@studiok.com", "last_synced_at": _iso(1)})
    out = run(_biz(VERIFIED))
    assert "no test sent" in out["result"]
    assert "step 4" in out["result"]
    assert "one step left" in out["label"]


def test_verified_without_inbox_names_step_three(fake, monkeypatch):
    _live(monkeypatch, "verified")
    out = run(_biz(VERIFIED))
    assert "no inbox connected" in out["result"]
    assert "step 3" in out["result"]
    assert out["signal"]["ready"] is False and out["signal"]["verified"] is True


def test_waiting_on_dns(fake, monkeypatch):
    _live(monkeypatch, "pending")
    out = run(_biz({**VERIFIED, "status": "pending", "verified_at": None}))
    assert "waiting on DNS" in out["result"]
    assert "step 2" in out["result"] and "every 30s" in out["result"]
    assert "waiting on DNS" in out["label"]


def test_drift_is_called_out_with_when(fake, monkeypatch):
    _live(monkeypatch, "failed")
    out = run(_biz({**VERIFIED, "status": "failed", "drift_detected_at": _iso(3)}))
    assert "STOPPED verifying 3h ago" in out["result"]
    assert "which record" in out["result"]


def test_missing_at_provider(fake, monkeypatch):
    _live(monkeypatch, "missing")
    out = run(_biz(VERIFIED))
    assert "no longer exists at the email provider" in out["result"]
    assert "disconnect and reconnect" in out["result"]


def test_provider_unreachable_reports_stored_state(fake, monkeypatch):
    _live(monkeypatch, None)
    out = run(_biz(VERIFIED))
    assert "verified" in out["result"]
    assert "provider unreachable" in out["result"]
    assert out["signal"]["verified"] is True


def test_stale_inbox_is_not_reported_as_syncing(fake, monkeypatch):
    _live(monkeypatch, "verified")
    fake.rows("google_mailboxes").append(
        {"business_id": "b1", "google_email": "sarah@studiok.com", "last_synced_at": _iso(40)})
    out = run(_biz({**VERIFIED, "last_test": {"id": "m1", "identity": "custom", "sent_at": _iso(1)}}))
    assert "NOT syncing" in out["result"]
    assert "reconnect the mailbox" in out["result"]


def test_mailbox_read_failure_is_non_fatal(fake, monkeypatch):
    _live(monkeypatch, "verified")

    def _boom(path):
        raise RuntimeError("db down")
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    out = run(_biz(VERIFIED))
    assert out["type"] == "email_setup_status" and out["result"]
    assert "no inbox connected" in out["result"]
