"""scheduler_lock.gate runs async AND plain jobs, and only on the leader.

Five gated jobs are plain functions. `await fn()` ran them on the event
loop and then crashed on their dict return value ("object dict can't be
used in 'await' expression"), which Sentry recorded every 15 minutes for
lead_response_reconcile.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import scheduler_lock


def _lead(monkeypatch, leader: bool = True):
    monkeypatch.setattr(scheduler_lock, "is_leader", lambda: leader)


def test_async_job_is_awaited(monkeypatch):
    _lead(monkeypatch)

    async def job():
        return {"ok": True}

    assert asyncio.run(scheduler_lock.gate("a", job)()) == {"ok": True}


def test_plain_job_runs_off_the_event_loop_and_returns_its_dict(monkeypatch):
    _lead(monkeypatch)
    loop_thread = {}

    def job():
        loop_thread["job"] = threading.get_ident()
        return {"reconciled": 3}

    async def run():
        loop_thread["loop"] = threading.get_ident()
        return await scheduler_lock.gate("lead_response_reconcile", job)()

    assert asyncio.run(run()) == {"reconciled": 3}
    assert loop_thread["job"] != loop_thread["loop"], "a plain job must not block the loop"


def test_plain_callable_returning_a_coroutine_is_awaited(monkeypatch):
    _lead(monkeypatch)

    async def inner():
        return "done"

    assert asyncio.run(scheduler_lock.gate("b", lambda: inner())()) == "done"


def test_follower_skips_both_kinds(monkeypatch):
    _lead(monkeypatch, leader=False)
    calls = []

    async def a():
        calls.append("a")

    def b():
        calls.append("b")

    asyncio.run(scheduler_lock.gate("a", a)())
    asyncio.run(scheduler_lock.gate("b", b)())
    assert calls == []
