"""Connecting a Gmail inbox is retired (Kevin, 2026-11-14: "yes retire the
gmail for now"). Reading a Gmail inbox needs Google's yearly security review
to lose its unverified-app warning; church email brings mail in instead.

Pins: with GMAIL_CONNECT unset, starting a connection answers 410 with the
plain reason, the consent hop and the callback refuse too, and the worker's
sync does nothing. GMAIL_CONNECT=on brings it back as it was."""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gmail_sync  # noqa: E402
import google_oauth  # noqa: E402


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GMAIL_CONNECT", raising=False)


def test_starting_a_gmail_connection_is_retired(monkeypatch):
    called = []
    monkeypatch.setattr(google_oauth, "_require_owner", lambda *a: called.append(a))
    with pytest.raises(HTTPException) as e:
        asyncio.run(google_oauth.google_connect_start("biz", user=SimpleNamespace(id="u1")))
    assert e.value.status_code == 410 and "retired" in e.value.detail
    assert called == [], "refused before anything else is looked up"


def test_the_consent_hop_and_the_callback_refuse_too(monkeypatch):
    monkeypatch.setattr(google_oauth.oauth_connect_ticket, "verify", lambda *a, **k: ("biz", "u1"))
    with pytest.raises(HTTPException) as e:
        asyncio.run(google_oauth.google_connect(ticket="t"))
    assert e.value.status_code == 410
    page = asyncio.run(google_oauth.google_callback(code="c", state="t"))
    assert "retired" in page.body.decode()


def test_the_worker_syncs_nothing(monkeypatch):
    monkeypatch.setattr(google_oauth.sb_clients if hasattr(google_oauth, "sb_clients") else gmail_sync.sb_clients,
                        "sb_get_as_service", lambda *a, **k: pytest.fail("no mailbox read while retired"))
    assert asyncio.run(gmail_sync.sync_tick()) == {"skipped": "gmail_connect_retired"}


def test_gmail_connect_on_brings_it_back(monkeypatch):
    monkeypatch.setenv("GMAIL_CONNECT", "on")
    monkeypatch.setattr(google_oauth, "_require_owner", lambda *a: None)
    monkeypatch.setattr(google_oauth.oauth_connect_ticket, "mint", lambda *a: "tick")
    out = asyncio.run(google_oauth.google_connect_start("biz", user=SimpleNamespace(id="u1")))
    assert out == {"authorize_url": "/connect/google?ticket=tick"}
