"""Site-builder audit (2026-08-13) — enqueue must not start a second
paid build.

Two failures met here to make one money bug:

  1. The stale sweep decided "orphaned" by AGE alone. A full Opus build
     genuinely approaches the 10-minute cutoff, so a slow-but-alive build
     was marked failed while its thread kept running — which freed the
     dedupe slot AND told the practitioner the build had died.

  2. The dedupe was a read followed by an insert with nothing between
     them, so two clicks inside one round-trip both inserted.

Either path ends with two concurrent builds racing to write the same
site row and two 600-credit markers. The database now holds the
invariant (partial unique index); these tests pin the process-side
behaviour around it.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Deliberately NO os.environ.setdefault for SUPABASE_URL /
# SUPABASE_SERVICE_ROLE_KEY here. chief_jobs reads both lazily inside
# _url() / _service_key(), and every test below replaces _sb outright,
# so neither is needed — while setting them at import time leaks into
# the whole pytest process and un-skips test_product_files_private's
# live bucket check, pointing a production assertion at a dummy URL.
import chief_jobs  # noqa: E402


BIZ = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
OLD_JOB = "99999999-9999-9999-9999-999999999999"


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


class _Recorder:
    """Captures every _sb call so a test can assert what the enqueue did
    (and, more importantly, what it did NOT do)."""

    def __init__(self, get_rows=None, post_rows=None):
        self.calls: list = []
        self._get_rows = get_rows if get_rows is not None else []
        self._post_rows = post_rows

    async def __call__(self, client, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return self._get_rows
        if method == "POST":
            return self._post_rows
        return None

    def patched_to_failed(self) -> list:
        return [p for (m, p, b) in self.calls
                if m == "PATCH" and isinstance(b, dict) and b.get("status") == "failed"]

    def inserted(self) -> list:
        return [p for (m, p, b) in self.calls if m == "POST"]


@pytest.fixture(autouse=True)
def _clear_inflight():
    chief_jobs._INFLIGHT.clear()
    yield
    chief_jobs._INFLIGHT.clear()


def _enqueue(monkeypatch, recorder, no_task=True):
    monkeypatch.setattr(chief_jobs, "_sb", recorder)
    if no_task:
        # Don't actually spawn a runner in a unit test.
        monkeypatch.setattr(chief_jobs.asyncio, "create_task", lambda coro: coro.close())
    return asyncio.run(
        chief_jobs.enqueue(None, user_id=USER, business_id=BIZ, kind="rebuild_site")
    )


# ─── the sweep must not kill a slow-but-alive build ──────────────────


def test_old_but_still_running_here_is_not_swept(monkeypatch):
    """A 14-minute build whose runner is alive in this process is slow,
    not orphaned. Sweeping it is what freed the slot for a second build."""
    chief_jobs._INFLIGHT.add(OLD_JOB)
    rec = _Recorder(get_rows=[{"id": OLD_JOB, "status": "running",
                               "started_at": _iso(14), "created_at": _iso(14)}])
    job = _enqueue(monkeypatch, rec)

    assert rec.patched_to_failed() == [], "a live job was marked failed"
    assert rec.inserted() == [], "a second build was enqueued over a live one"
    assert job is not None and job.get("deduped") is True
    assert job["id"] == OLD_JOB


def test_old_and_not_running_here_is_still_swept(monkeypatch):
    """The sweep's real job — a row orphaned by a restart belongs to a
    process that no longer exists, so its id is not in _INFLIGHT."""
    rec = _Recorder(get_rows=[{"id": OLD_JOB, "status": "running",
                               "started_at": _iso(14), "created_at": _iso(14)}],
                    post_rows=[{"id": "new-job", "kind": "rebuild_site"}])
    job = _enqueue(monkeypatch, rec)

    assert len(rec.patched_to_failed()) == 1
    assert len(rec.inserted()) == 1
    assert job is not None and job["id"] == "new-job"


def test_fresh_job_dedupes_without_inserting(monkeypatch):
    rec = _Recorder(get_rows=[{"id": "fresh-1", "status": "running",
                               "started_at": _iso(2), "created_at": _iso(2)}])
    job = _enqueue(monkeypatch, rec)

    assert rec.inserted() == []
    assert job is not None and job.get("deduped") is True


# ─── losing the insert race must return the winner, not None ─────────


class _RaceRecorder(_Recorder):
    """First GET finds nothing (so we try to insert), the INSERT loses to
    the unique index and returns None, the follow-up GET finds the
    winner."""

    def __init__(self):
        super().__init__()
        self._gets = 0

    async def __call__(self, client, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            self._gets += 1
            if self._gets == 1:
                return []
            return [{"id": "winner-job", "status": "running", "kind": "rebuild_site"}]
        if method == "POST":
            return None  # unique violation — _sb logs and returns None
        return None


def test_insert_race_returns_the_winning_job(monkeypatch):
    """Returning None here is what made the app say 'couldn't start your
    build' over a build that WAS running — and that message is what
    invites the retry that starts a second one."""
    rec = _RaceRecorder()
    job = _enqueue(monkeypatch, rec)

    assert job is not None, "race loser returned None instead of the live job"
    assert job["id"] == "winner-job"
    assert job.get("deduped") is True


def test_insert_failure_with_no_winner_still_returns_none(monkeypatch):
    """A genuine insert failure (not a race) must not invent a job."""

    class _Dead(_Recorder):
        async def __call__(self, client, method, path, body=None):
            self.calls.append((method, path, body))
            return [] if method == "GET" else None

    job = _enqueue(monkeypatch, _Dead())
    assert job is None
