"""Phase I.3 PR3 — accountant collaborators: accept + active-accountant check."""
from __future__ import annotations

import sys
import pathlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import business_collaborators_router as bc


class _U:
    id = "acct-user"


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def test_accept_activates_and_links_user(monkeypatch):
    import sb_clients
    patches = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "c1", "business_id": "biz1", "status": "pending", "role": "accountant",
         "expiration_at": _future(), "token": "tok"}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: patches.append((p, b)))
    out = bc.accept(bc.AcceptBody(token="tok"), user=_U())
    assert out["business_id"] == "biz1" and out["role"] == "accountant"
    _, body = patches[0]
    assert body["status"] == "active" and body["user_id"] == "acct-user" and body["accepted_at"]


def test_accept_rejects_revoked(monkeypatch):
    from fastapi import HTTPException
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "c1", "business_id": "biz1", "status": "revoked", "expiration_at": _future(), "token": "tok"}])
    with pytest.raises(HTTPException) as e:
        bc.accept(bc.AcceptBody(token="tok"), user=_U())
    assert e.value.status_code == 409


def test_accept_rejects_expired(monkeypatch):
    from fastapi import HTTPException
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "c1", "business_id": "biz1", "status": "pending", "expiration_at": _past(), "token": "tok"}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    with pytest.raises(HTTPException) as e:
        bc.accept(bc.AcceptBody(token="tok"), user=_U())
    assert e.value.status_code == 409


def test_is_active_accountant(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [{"id": "c1"}] if "status=eq.active" in path else [])
    assert bc.is_active_accountant("biz1", "acct-user") is True
