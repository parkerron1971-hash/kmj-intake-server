"""Phase I.3 PR4 — Chief proposes period close."""
from __future__ import annotations

import sys
import pathlib
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_bookkeeping as cb


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def test_candidate_requires_open_nearend_reconciled(monkeypatch):
    import gl_engine
    # Open MONTH period ending today, fully reconciled → candidate.
    monkeypatch.setattr(gl_engine, "period_covering", lambda biz, day, ptype: (
        {"id": "m6", "period_type": "month", "period_start": "2026-06-01",
         "period_end": _today(), "status": "open"} if ptype == "month" else None))
    monkeypatch.setattr(gl_engine, "period_counts",
                        lambda biz, s, e: {"transactions": 12, "reconciled": 12, "unmatched": 0})
    cand = cb.period_close_candidate("biz1")
    assert cand and cand["id"] == "m6"


def test_no_candidate_when_unmatched(monkeypatch):
    import gl_engine
    monkeypatch.setattr(gl_engine, "period_covering", lambda biz, day, ptype: (
        {"id": "m6", "period_type": "month", "period_start": "2026-06-01",
         "period_end": _today(), "status": "open"} if ptype == "month" else None))
    monkeypatch.setattr(gl_engine, "period_counts",
                        lambda biz, s, e: {"transactions": 12, "reconciled": 8, "unmatched": 4})
    assert cb.period_close_candidate("biz1") is None


def test_analyze_creates_proposal_then_skips_when_pending(monkeypatch):
    import gl_engine, sb_clients
    monkeypatch.setattr(gl_engine, "period_covering", lambda biz, day, ptype: (
        {"id": "m6", "period_type": "month", "period_start": "2026-06-01",
         "period_end": _today(), "status": "open"} if ptype == "month" else None))
    monkeypatch.setattr(gl_engine, "period_counts",
                        lambda biz, s, e: {"transactions": 5, "reconciled": 5, "unmatched": 0})

    state = {"pending": False}

    def _get(path):
        if "chief_bookkeeping_proposals" in path and "proposal_type=eq.propose_period_close" in path:
            return [{"status": "pending", "proposed": {"period_id": "m6"}, "resolved_at": None}] if state["pending"] else []
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: [{"id": "prop1", **b}])

    created = cb.analyze_period_close("biz1")
    assert len(created) == 1 and created[0]["proposal_type"] == "propose_period_close"
    assert created[0]["proposed"]["period_id"] == "m6"

    state["pending"] = True   # now a pending proposal exists → don't re-propose
    assert cb.analyze_period_close("biz1") == []


def test_approve_period_close_calls_close_period(monkeypatch):
    import gl_engine, sb_clients
    calls = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "prop1", "business_id": "biz1", "status": "pending",
         "proposal_type": "propose_period_close", "proposed": {"period_id": "m6"}}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    monkeypatch.setattr(gl_engine, "close_period",
                        lambda biz, pid, **kw: calls.append((biz, pid, kw)) or {"ok": True, "closed": True})
    out = cb.approve_proposal("biz1", "prop1", approved_by="owner-user")
    assert out["executed"] == "propose_period_close"
    biz, pid, kw = calls[0]
    assert pid == "m6" and kw["closed_via"] == "chief_auto_close" and kw["closed_by"] == "owner-user"
