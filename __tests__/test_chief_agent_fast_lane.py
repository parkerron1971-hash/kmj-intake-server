"""The standing agent's fast lane (2026-09-04).

A lead is worth most in its first minutes, so a lead or a booking wakes
the agent within a minute (event_spine.emit → chief_agent.nudge); the
sweep behind it runs every two minutes instead of ten. Pinned here:

  * the fast-lane types are the ones a person is waiting on — leads and
    bookings — and never the bookkeeping ones;
  * a nudge outside a running loop is a quiet no-op (the sweep catches
    it); inside one it schedules exactly one run per business, debounced,
    and that run handles only that business's events;
  * emit nudges only after the row is written, and not when the write
    failed;
  * stamping returns only what this process stamped, and a run acts only
    on that — two replicas cannot both act on one event;
  * the sweep is scheduled every two minutes.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_agent as ca
import event_spine
import sb_clients

BIZ = "b-fast"


def test_the_fast_lane_is_leads_and_bookings_not_bookkeeping():
    assert ca.FAST_EVENT_TYPES <= set(ca.AGENT_EVENT_TYPES)
    assert {"booking_created", "contact_form_submitted", "concierge_lead_captured"} == set(ca.FAST_EVENT_TYPES)
    for slow in ("payment_received", "invoice_paid_auto", "contract_signed", "order_paid"):
        assert slow not in ca.FAST_EVENT_TYPES


def test_a_nudge_outside_a_running_loop_is_a_quiet_no_op(monkeypatch):
    monkeypatch.setattr(ca, "_pending_nudges", {})
    assert ca.nudge(BIZ, "booking_created") is False
    assert ca._pending_nudges == {}


def test_a_nudge_schedules_one_run_per_business_and_debounces(monkeypatch):
    monkeypatch.setattr(ca, "_pending_nudges", {})
    monkeypatch.setattr(ca, "NUDGE_DELAY_S", 0)
    monkeypatch.setattr(ca, "unhandled_events", lambda: [
        {"id": "e1", "business_id": BIZ, "event_type": "booking_created"},
        {"id": "e2", "business_id": "someone-else", "event_type": "booking_created"},
    ])
    handled = []

    async def handle_business(bid, events):
        handled.append((bid, [e["id"] for e in events]))
    monkeypatch.setattr(ca, "handle_business", handle_business)

    async def scenario():
        first = ca.nudge(BIZ, "booking_created")
        second = ca.nudge(BIZ, "contact_form_submitted")
        slow = ca.nudge(BIZ, "payment_received")
        task = ca._pending_nudges[BIZ]
        await task
        return first, second, slow
    first, second, slow = asyncio.run(scenario())
    assert first is True and second is False, "one run on its way covers both events"
    assert slow is False, "bookkeeping waits for the sweep"
    assert handled == [(BIZ, ["e1"])], "only this business's events, only once"
    assert BIZ not in ca._pending_nudges, "the slot is freed for the next lead"


def test_a_nudge_is_off_when_the_platform_switch_is_off(monkeypatch):
    monkeypatch.setenv("CHIEF_AGENT", "off")
    monkeypatch.setattr(ca, "_pending_nudges", {})

    async def scenario():
        return ca.nudge(BIZ, "booking_created")
    assert asyncio.run(scenario()) is False


def test_emit_nudges_after_the_row_is_written_and_not_when_it_failed(monkeypatch):
    order = []
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: order.append(("post", b["event_type"])) or [])
    monkeypatch.setattr(ca, "nudge", lambda biz, et: order.append(("nudge", et)) or True)
    assert event_spine.emit("booking_created", BIZ, {"booking_id": "x"}) is True
    assert order == [("post", "booking_created"), ("nudge", "booking_created")]

    order.clear()

    def boom(p, b, prefer=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(sb_clients, "sb_post_as_service", boom)
    assert event_spine.emit("booking_created", BIZ) is False
    assert order == [], "no row, no nudge"


def test_stamping_returns_only_what_this_process_stamped(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [{"id": "e1"}])
    assert ca.stamp_handled(["e1", "e2"]) == ["e1"]
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    assert ca.stamp_handled(["e1", "e2"]) == ["e1", "e2"], "a silent helper keeps the old behaviour"
    assert ca.stamp_handled([]) == []


def test_a_run_acts_only_on_the_events_it_won(monkeypatch):
    """Two replicas read the same unhandled row; the PATCH hands it to one.
    The other must act on nothing."""
    biz = {"id": BIZ, "name": "Biz", "settings": {"autonomy": {"agent_enabled": True}}}
    monkeypatch.setattr(ca, "_business", lambda bid: biz)
    import policy_engine
    import spend_guard
    monkeypatch.setattr(policy_engine, "is_paused", lambda b: False)
    monkeypatch.setattr(spend_guard, "over_budget", lambda b: False)
    monkeypatch.setattr(ca, "stamp_handled", lambda ids: ["e1"])
    ran = []

    async def run(b, events):
        ran.append([e["id"] for e in events])
        return {"ok": True}
    monkeypatch.setattr(ca, "run", run)
    events = [{"id": "e1", "business_id": BIZ}, {"id": "e2", "business_id": BIZ}]
    assert asyncio.run(ca.handle_business(BIZ, events)) == {"ok": True}
    assert ran == [["e1"]]

    ran.clear()
    monkeypatch.setattr(ca, "stamp_handled", lambda ids: [])
    assert asyncio.run(ca.handle_business(BIZ, events)) is None
    assert ran == [], "the other replica got there first"


def test_the_sweep_runs_every_two_minutes():
    import kmj_intake_automation as app
    src = inspect.getsource(app)
    i = src.index('id="chief_agent"')
    assert 'minutes=2' in src[i - 200:i]
