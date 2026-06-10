"""Phase I.3 PR2 — soft-lock: locked-period detection + the backend guard."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import period_lock as pl


def test_locked_period_picks_most_specific(monkeypatch):
    import sb_clients
    # A closed MONTH and closed YEAR both cover the date → month wins (tightest).
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "yr", "period_type": "year", "period_start": "2026-01-01", "period_end": "2026-12-31", "status": "closed"},
        {"id": "mo", "period_type": "month", "period_start": "2026-06-01", "period_end": "2026-06-30", "status": "closed"},
    ])
    assert pl.locked_period("biz1", "2026-06-15")["id"] == "mo"


def test_locked_period_none_when_open(monkeypatch):
    import sb_clients
    # status=eq.closed filter isn't applied by the naive mock, but an empty
    # result models "no closed period covers this date".
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    assert pl.locked_period("biz1", "2026-06-15") is None
    assert pl.locked_period("biz1", "") is None


def test_guard_409_when_locked_no_reason(monkeypatch):
    from fastapi import HTTPException
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "mo", "period_type": "month", "period_start": "2026-06-01", "period_end": "2026-06-30", "status": "closed"}])
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda *a, **k: pytest.fail("must not record without a reason"))
    with pytest.raises(HTTPException) as e:
        pl.guard("biz1", "2026-06-15", source_type="bill", source_id="b1",
                 reason=None, override_by="owner")
    assert e.value.status_code == 409
    assert e.value.detail["error"] == "period_closed"


def test_guard_records_and_allows_with_reason(monkeypatch):
    import sb_clients
    posts = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "mo", "period_type": "month", "period_start": "2026-06-01", "period_end": "2026-06-30", "status": "closed"}])
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: posts.append((p, b)))
    pl.guard("biz1", "2026-06-15", source_type="bill", source_id="b1",
             reason="fixing a miskeyed amount", override_by="owner",
             pre={"amount": 100}, post={"amount": 120})
    path, body = posts[0]
    assert "period_edit_overrides" in path
    assert body["override_reason"] == "fixing a miskeyed amount"
    assert body["accounting_period_id"] == "mo"
    assert body["pre_change_snapshot"] == {"amount": 100}


def test_guard_noop_when_not_locked(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])  # no closed period
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda *a, **k: pytest.fail("no override when not locked"))
    pl.guard("biz1", "2026-06-15", source_type="bill", source_id="b1",
             reason=None, override_by="owner")  # returns cleanly
