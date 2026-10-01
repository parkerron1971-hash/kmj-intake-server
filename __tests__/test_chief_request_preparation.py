"""Main preparation preserves gates while independent streams/background work progress."""
import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

import billing_context
import chief_of_staff as chief
import chief_proactive_suggestions
import llm_call
import route_ledger
import sb_clients
import spend_guard


class Response:
    status_code = 200
    text = ""

    def json(self):
        return {"stop_reason": "end_turn", "usage": {},
                "content": [{"type": "text", "text": "Ready."}]}


@pytest.mark.parametrize("outcome", [True, False, "unavailable"])
def test_slow_budget_check_yields_but_still_governs_provider_request(monkeypatch, outcome):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    observed = []

    def check(business_id):
        observed.append((business_id, billing_context.current(), sb_clients.get_current_user_jwt()))
        entered.set()
        release.wait(1.0)
        finished.set()
        if outcome == "unavailable":
            raise RuntimeError("budget storage unavailable")
        return outcome

    provider = AsyncMock(return_value=Response())
    monkeypatch.setattr(spend_guard, "over_budget", check)
    monkeypatch.setattr(chief, "_anthropic_key", lambda: "fixture-key")
    monkeypatch.setattr(chief, "log_api_usage", AsyncMock())
    monkeypatch.setattr(llm_call, "apost", provider)

    async def run():
        token = sb_clients.set_user_jwt("fixture-jwt")
        try:
            with billing_context.bill_to("biz-1"):
                task = asyncio.create_task(chief._call_claude(None, "System", [],
                    business_id="biz-1", enable_web_search=False))
                # On the old synchronous path this callback cannot run until
                # the guard times out. No provider/model timing is involved.
                started = await asyncio.to_thread(entered.wait, 1.0)
                yielded = started and not finished.is_set()
                release.set()
                answer = await task
                return yielded, answer
        finally:
            release.set()
            sb_clients.reset_user_jwt(token)

    yielded, answer = asyncio.run(run())
    assert yielded, "a cold spend lookup froze the event loop carrying the opening"
    assert observed == [("biz-1", "biz-1", "fixture-jwt")]
    if outcome is True:
        provider.assert_not_awaited()
        assert answer == spend_guard.block_message()
    else:
        provider.assert_awaited_once()
        assert answer == "Ready."  # same allow/fail-open semantics as before


def test_proactive_task_survives_request_cancel_and_keeps_its_owner(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    observed = []
    monkeypatch.setattr(chief, "_TURN_SWEEP_TASKS", set())

    def emit(biz):
        entered.set()
        release.wait(2.0)
        observed.append((biz["id"], billing_context.current(),
                         sb_clients.get_current_user_jwt(), route_ledger.TALLY.get()))

    monkeypatch.setattr(chief_proactive_suggestions, "maybe_emit_proactive_suggestions", emit)

    async def run():
        tally = route_ledger.Tally()
        async def request():
            jwt = sb_clients.set_user_jwt("jwt-origin")
            tally_token = route_ledger.TALLY.set(tally)
            try:
                with billing_context.bill_to("biz-origin"):
                    chief._spawn_proactive_suggestions({"id": "biz-origin"})
                    await asyncio.Future()
            finally:
                sb_clients.reset_user_jwt(jwt)
                route_ledger.TALLY.reset(tally_token)

        request_task = asyncio.create_task(request())
        try:
            assert await asyncio.to_thread(entered.wait, 1.0)
            request_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request_task
            assert chief._TURN_SWEEP_TASKS
            assert all(not task.cancelled() for task in chief._TURN_SWEEP_TASKS)
        finally:
            release.set()
            await chief._drain_turn_sweeps()
        assert not chief._TURN_SWEEP_TASKS
        assert tally.totals()["calls"] == 0

    asyncio.run(run())
    assert observed == [("biz-origin", "biz-origin", "jwt-origin", None)]


def test_proactive_failure_is_observed_and_background_task_is_released(monkeypatch, caplog):
    monkeypatch.setattr(chief, "_TURN_SWEEP_TASKS", set())

    def broken(biz):
        raise RuntimeError("fixture offline")

    monkeypatch.setattr(chief_proactive_suggestions, "maybe_emit_proactive_suggestions", broken)

    async def run():
        chief._spawn_proactive_suggestions({"id": "biz-1"})
        await chief._drain_turn_sweeps()
        assert not chief._TURN_SWEEP_TASKS

    asyncio.run(run())
    assert "proactive suggestions failed" in caplog.text


@pytest.mark.parametrize("empty", [False, True])
def test_jit_uses_scoped_turn_snapshots_without_three_new_reads(monkeypatch, empty):
    business = {} if empty else {"brand_voice": "warm", "proactive_capture_enabled": True}
    practitioner = {} if empty else {"full_legal_name": "Fixture Owner",
        "proactive_capture_enabled": True, "voice_samples": {"casual_nurture": "Sample"}}
    ctx = {"business": {"id": "biz", "owner_id": "owner"}, "memories": []}
    monkeypatch.setattr(chief.business_profile_agent, "get_profile", lambda _: business)
    monkeypatch.setattr(chief.practitioner_profile_agent, "get_profile", lambda _: practitioner)
    monkeypatch.setattr(chief.voice_depth_agent, "get_voice_depth", lambda _: practitioner)
    message = "My business profile, accountant, and writing voice need attention."
    assert chief.business_profile_agent.get_missing_jit_fields("biz") == chief.business_profile_agent.missing_jit_fields_from_profile(business)
    assert chief.practitioner_profile_agent.get_missing_jit_fields("owner") == chief.practitioner_profile_agent.missing_jit_fields_from_profile(practitioner)
    assert chief.voice_depth_agent.get_missing_voice_jit_fields("owner") == chief.voice_depth_agent.missing_voice_jit_fields_from_profile(practitioner)
    ctx.update(business_profile_raw=business, practitioner_profile_raw=practitioner)
    expected = chief._build_jit_directive(ctx, message)
    def forbidden(*args, **kwargs):
        raise AssertionError("duplicate database read after context was gathered")
    monkeypatch.setattr(chief.business_profile_agent, "get_profile", forbidden)
    monkeypatch.setattr(chief.practitioner_profile_agent, "get_profile", forbidden)
    monkeypatch.setattr(chief.voice_depth_agent, "get_voice_depth", forbidden)
    actual = chief._build_jit_directive({**ctx, "business_profile_raw": business,
        "practitioner_profile_raw": practitioner}, message)
    assert actual == expected
    if not empty:
        assert "JIT-CAPTURE PRIORITY" in actual
