"""
test_chief_turn_latency.py — the enrichment a Chief turn does before it
calls the model runs concurrently, not one source after another.

Kevin's report: "it seems like it's taking a while for it to think
before a response comes." Most of that wait is not the model. It is the
prelude — ten independent sources of context (voice samples, session
context, mentor cooldown, revenue forecast, relationship insights, time
context, habits, live bookkeeping, cross-vertical learning, plus the
proactive-suggestion emit), which used to be awaited one at a time.
Twelve PostgREST round-trips and two off-thread modules, each waiting on
the last, with the model call queued behind all of it. Paid on EVERY
turn, including "how's the business doing?".

None of them consumes another's result, so the wait was the sum of ten
things that should cost the slowest one. _gather_context, two calls up,
already fans its eighteen queries out with asyncio.gather; this block
simply never got the same treatment.

MEASURING IT: the turn is driven twice, once with every enrichment
source instant and once with each costing DELAY, and the test asserts
on the DIFFERENCE. That way nothing depends on a guess about what the
rest of the turn costs — the baseline measures itself. Serial code adds
10*DELAY; concurrent adds about one.

Also held here: the failure isolation the old per-call try/except blocks
gave, and proof the sources still actually run. Concurrency that turned
one broken source into a broken turn, or speed that came from quietly
dropping context, would both be bad trades.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos


DELAY = 0.10          # what each enrichment source costs when slowed
N_SOURCES = 10        # how many the prelude gathers

# Serial adds N_SOURCES * DELAY = 1.0s over baseline. Concurrent adds
# about DELAY. The budget sits far below serial and comfortably above
# concurrent, so neither a loaded CI box nor a fast one decides it.
BUDGET = DELAY * 4

_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}, "created_at": "2026-01-01T00:00:00Z"}


class _Session:
    class _User:
        id = "user-1"
    user = _User()
    token = "test-jwt"


def _req(**over):
    fields = {"business_id": "biz-1", "message": "how's the business doing?"}
    fields.update(over)
    return cos.ChatRequest(**fields)


@pytest.fixture
def turn(monkeypatch):
    """Drive a real chief_chat with the ten enrichment sources stubbed.

    Returns run(delay, **request_overrides) -> (elapsed, response). Only
    the enrichment sources honour `delay`; every other stub is instant,
    so the difference between two runs is enrichment and nothing else.
    """
    cost = {"delay": 0.0}
    called: set[str] = set()

    def _async_source(name, value):
        async def inner(*a, **k):
            called.add(name)
            if cost["delay"]:
                await asyncio.sleep(cost["delay"])
            return value
        return inner

    def _sync_source(name, value=""):
        def inner(*a, **k):
            called.add(name)
            if cost["delay"]:
                time.sleep(cost["delay"])
            return value
        return inner

    async def _instant(value=None):
        return value

    # ── Everything that is NOT the enrichment block: always instant ──
    async def _fake_sb(client, method, path, body=None):
        return [_BIZ]
    monkeypatch.setattr(cos, "_sb", _fake_sb)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances",
                        lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_autopilot_sweep", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_evaluate_escalations", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_gather_context",
                        lambda *a, **k: _instant({"business": _BIZ, "contacts": []}))
    monkeypatch.setattr(cos, "_fetch_view_detail", lambda *a, **k: _instant(""))
    monkeypatch.setattr(cos, "_build_system_prompt", lambda *a, **k: "SYSTEM")
    monkeypatch.setattr(cos, "_call_claude", lambda *a, **k: _instant("All good."))
    monkeypatch.setattr(cos, "_log_chief_activity", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_learn_patterns_async", lambda *a, **k: _instant(None))

    # ── The ten enrichment sources ──────────────────────────────────
    for name, value in [
        ("_get_voice_examples", ""), ("_get_session_context", ""),
        ("_should_show_mentor_tip", False), ("_forecast_revenue", None),
        ("_analyze_relationships", []), ("_get_time_context", ""),
        ("_get_habit_insights", ""),
    ]:
        monkeypatch.setattr(cos, name, _async_source(name, value))

    import chief_bookkeeping
    import chief_proactive_suggestions
    import vertical_context
    for mod, attr in [
        (chief_bookkeeping, "gather_and_format"),
        (vertical_context, "build_vertical_learned_block"),
        (chief_proactive_suggestions, "maybe_emit_proactive_suggestions"),
    ]:
        monkeypatch.setattr(mod, attr, _sync_source(attr))

    def run(delay=0.0, **over):
        cost["delay"] = delay
        started = time.monotonic()
        out = asyncio.run(cos.chief_chat(_req(**over), _Session()))
        return time.monotonic() - started, out

    run.called = called
    return run


# ─────────────────────────────────────────────────────────────────────
# The measurement
# ─────────────────────────────────────────────────────────────────────

def test_the_enrichment_sources_do_not_wait_on_each_other(turn):
    baseline, out = turn(delay=0.0)
    assert out["response"] == "All good."
    slowed, _ = turn(delay=DELAY)
    added = slowed - baseline
    assert added < BUDGET, (
        f"slowing {N_SOURCES} independent context sources by {DELAY}s each "
        f"added {added:.2f}s to the turn ({baseline:.2f}s -> {slowed:.2f}s). "
        f"Concurrent costs about {DELAY}s; {N_SOURCES * DELAY:.2f}s means "
        f"they are running one after another again."
    )


def test_a_greeting_turn_is_no_slower(turn):
    # Greetings build daily priorities on top of the same enrichment.
    msg = cos.OPENING_SENTINEL_PREFIX + " morning"
    baseline, _ = turn(delay=0.0, message=msg)
    slowed, _ = turn(delay=DELAY, message=msg)
    assert (slowed - baseline) < BUDGET


def test_every_source_still_actually_runs(turn):
    """Guarding the guard: a 'fix' that made the prelude fast by
    skipping the work would pass the timing tests above."""
    turn(delay=0.0)
    assert len(turn.called) == N_SOURCES, (
        f"only {sorted(turn.called)} ran — speed that comes from dropping "
        f"context is not the fix"
    )


# ─────────────────────────────────────────────────────────────────────
# Failure isolation — what the old per-call try/except blocks gave
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("broken", [
    "_get_voice_examples", "_get_session_context", "_should_show_mentor_tip",
    "_forecast_revenue", "_analyze_relationships", "_get_time_context",
    "_get_habit_insights",
])
def test_one_broken_source_never_takes_the_turn_down(turn, monkeypatch, broken):
    async def _boom(*a, **k):
        raise RuntimeError(f"{broken} is down")
    monkeypatch.setattr(cos, broken, _boom)
    _, out = turn()
    assert out["response"] == "All good.", (
        f"{broken} raising must degrade its own block, not the turn — "
        "gathering context is not worth losing the conversation over"
    )


@pytest.mark.parametrize("module_name,attr", [
    ("chief_bookkeeping", "gather_and_format"),
    ("vertical_context", "build_vertical_learned_block"),
    ("chief_proactive_suggestions", "maybe_emit_proactive_suggestions"),
])
def test_a_broken_off_thread_module_never_takes_the_turn_down(
        turn, monkeypatch, module_name, attr):
    import importlib
    mod = importlib.import_module(module_name)

    def _boom(*a, **k):
        raise RuntimeError(f"{module_name} is down")
    monkeypatch.setattr(mod, attr, _boom)
    _, out = turn()
    assert out["response"] == "All good."


def test_every_source_failing_at_once_still_answers(turn, monkeypatch):
    """The worst case: Supabase is unreachable and every block is empty.
    Chief should still talk."""
    async def _boom(*a, **k):
        raise RuntimeError("down")
    for name in ["_get_voice_examples", "_get_session_context",
                 "_should_show_mentor_tip", "_forecast_revenue",
                 "_analyze_relationships", "_get_time_context",
                 "_get_habit_insights"]:
        monkeypatch.setattr(cos, name, _boom)
    _, out = turn()
    assert out["response"] == "All good."
