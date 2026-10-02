"""Delivery reports that beat their row are retried, never dropped; Hermes
asks Twilio about anything still `sent` (2026-10-02: 12 of 14 outbound
texts read `sent` forever while Twilio had delivered them)."""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient

import twilio_sms as ts

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeDB:
    """sms_messages with one row that appears only after `appears_after` reads."""
    def __init__(self, status="sent", appears_after=0, twilio=None):
        self.row = {"telnyx_id": "SM1", "status": status}
        self.appears_after, self.calls = appears_after, 0
        self.patches, self.twilio = [], twilio or {}

    def __call__(self, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _exists(self):
        return self.calls > self.appears_after

    async def patch(self, url, headers=None, params=None, json=None):
        self.calls += 1
        self.patches.append((params, json))
        guard = (params or {}).get("status", "")
        if not self._exists() or (guard and self.row["status"] in ("delivered", "failed")):
            return _Resp([])
        self.row["status"] = json["status"]
        return _Resp([dict(self.row)])

    async def get(self, url, headers=None, params=None, auth=None):
        if "api.twilio.com" in url:
            sid = url.rsplit("/", 1)[-1].replace(".json", "")
            return _Resp({"status": self.twilio.get(sid, "delivered")})
        if (params or {}).get("select") == "telnyx_id":
            return _Resp([{"telnyx_id": "SM1"}, {"telnyx_id": "legacy-telnyx"}])
        return _Resp([dict(self.row)] if self._exists() else [])


def client(monkeypatch, db):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(ts.httpx, "AsyncClient", db)
    monkeypatch.setattr(ts, "_RETRY_DELAYS", (0, 0, 0))
    app = FastAPI()
    app.include_router(ts.router)
    return TestClient(app)


def test_a_report_that_beats_its_row_is_retried_until_the_row_exists(monkeypatch):
    db = FakeDB(appears_after=2)
    r = client(monkeypatch, db).post("/webhooks/twilio/status",
                                     data={"MessageSid": "SM1", "MessageStatus": "delivered"})
    assert r.status_code == 204
    assert db.row["status"] == "delivered", "the background retry wrote it once the row existed"


def test_a_late_sent_report_never_undoes_delivered(monkeypatch):
    db = FakeDB(status="delivered")
    client(monkeypatch, db).post("/webhooks/twilio/status",
                                 data={"MessageSid": "SM1", "MessageStatus": "sent"})
    assert db.row["status"] == "delivered"
    assert db.patches[0][0]["status"] == "not.in.(delivered,failed)"
    assert len(db.patches) == 1, "the row exists, so no retry"


def test_undelivered_is_written_as_failed(monkeypatch):
    db = FakeDB()
    client(monkeypatch, db).post("/webhooks/twilio/status",
                                 data={"MessageSid": "SM1", "MessageStatus": "undelivered"})
    assert db.row["status"] == "failed"


def test_reconcile_asks_twilio_and_writes_the_real_outcome(monkeypatch):
    for k, v in (("TWILIO_ACCOUNT_SID", "AC1"), ("TWILIO_API_KEY_SID", "SK1"),
                 ("TWILIO_API_KEY_SECRET", "s")):
        monkeypatch.setenv(k, v)
    db = FakeDB(twilio={"SM1": "undelivered"})
    monkeypatch.setattr(ts.httpx, "AsyncClient", db)
    out = asyncio.run(ts.reconcile_sent(now=NOW))
    assert out == {"checked": 1, "delivered": 0, "failed": 1}, "non-Twilio ids are skipped"
    assert db.row["status"] == "failed"


def test_reconcile_without_twilio_does_nothing(monkeypatch):
    monkeypatch.delenv("TWILIO_API_KEY_SID", raising=False)
    assert asyncio.run(ts.reconcile_sent(now=NOW)) == {"skipped": "twilio not configured"}
