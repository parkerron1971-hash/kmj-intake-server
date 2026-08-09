"""A ledger row that did not land says so.

audit_log.record() returned True unconditionally. sb_clients returns
None on 4xx, on 5xx and on transport error WITHOUT raising, so the
try/except around the insert could only ever catch a JSON error — every
rejected write reported success.

That is not one bug, it is the reason every coverage number quoted about
this ledger is an upper bound rather than a measurement. rules_router
already checks the return value and logs on failure; that branch had
never once executed.

The second half was that prefer=None made failure undetectable even in
principle: a SUCCESSFUL insert also returns an empty body, so there was
nothing to compare.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import audit_log
import sb_clients


ROW_OK = [{"id": "11111111-1111-1111-1111-111111111111"}]


def _record(**over):
    kwargs = dict(actor_type="chief", verb="create_invoice", summary="x")
    kwargs.update(over)
    return audit_log.record("biz-1", **kwargs)


class TestRecordDetectsFailure:
    def test_a_rejected_write_returns_false(self, monkeypatch):
        """The regression this whole PR exists for: sb_clients returns
        None on a 4xx without raising."""
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: None)
        assert _record() is False

    def test_a_transport_error_returns_false(self, monkeypatch):
        """Also None, also silent — a different cause, same shape."""
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: None)
        assert _record() is False

    def test_an_empty_list_is_a_failure_not_a_success(self, monkeypatch):
        """PostgREST returns [] when nothing was inserted."""
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: [])
        assert _record() is False

    def test_a_raise_still_returns_false(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("connection reset")
        monkeypatch.setattr(sb_clients, "sb_post_as_service", _boom)
        assert _record() is False

    def test_a_real_write_returns_true(self, monkeypatch):
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: ROW_OK)
        assert _record() is True

    def test_failure_is_logged_at_error_not_warning(self, monkeypatch, caplog):
        """A gap in an append-only chain is not a warning."""
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: None)
        with caplog.at_level("ERROR"):
            _record()
        assert any(r.levelname == "ERROR" for r in caplog.records)

    def test_validation_failures_still_return_false_without_a_write(self, monkeypatch):
        """Missing business_id / verb short-circuits before the insert —
        unchanged behaviour, asserted so it stays that way."""
        called = {"n": 0}

        def _count(*a, **k):
            called["n"] += 1
            return ROW_OK
        monkeypatch.setattr(sb_clients, "sb_post_as_service", _count)
        assert audit_log.record("", actor_type="chief", verb="x") is False
        assert audit_log.record("biz-1", actor_type="chief", verb="") is False
        assert called["n"] == 0


class TestItAsksForSomethingBack:
    def test_the_insert_requests_the_id(self, monkeypatch):
        """prefer=None returns an empty body on SUCCESS too, so there was
        nothing to distinguish. Asking for the pk back is what makes the
        check possible at all."""
        seen = {}

        def _capture(path, body, prefer=None):
            seen["path"], seen["prefer"] = path, prefer
            return ROW_OK
        monkeypatch.setattr(sb_clients, "sb_post_as_service", _capture)
        _record()
        assert "select=id" in seen["path"], "must ask for the key back"
        assert "return=representation" in (seen["prefer"] or "")

    def test_it_does_not_ask_for_the_whole_row(self, monkeypatch):
        """We just wrote the payload; shipping it back doubles the cost
        of every ledger write."""
        seen = {}

        def _capture(path, body, prefer=None):
            seen["path"] = path
            return ROW_OK
        monkeypatch.setattr(sb_clients, "sb_post_as_service", _capture)
        _record(payload={"big": "x" * 500})
        assert "select=id" in seen["path"]


class TestVocabularySync:
    def test_a_lost_sync_reports_zero(self, monkeypatch):
        """The boot line printed 'synced: N verbs' whether or not a
        single row landed."""
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: None)
        assert audit_log.sync_action_types() == 0

    def test_a_real_sync_reports_the_count(self, monkeypatch):
        monkeypatch.setattr(sb_clients, "sb_post_as_service",
                            lambda *a, **k: [{"verb": "x"}])
        assert audit_log.sync_action_types() > 0

    def test_a_raise_reports_zero(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("nope")
        monkeypatch.setattr(sb_clients, "sb_post_as_service", _boom)
        assert audit_log.sync_action_types() == 0
