"""
test_chief_turn_timing.py — every Chief turn says where its time went.

Kevin asked for this after the enrichment fix (#584), and the reason is
in how that fix was reported: the 1.05s -> 0.11s number came from a test
harness, not from production. Nobody could say what a REAL turn costs or
which stage owns it. "It feels slow" is not something you can aim at.

So one line per turn:

  [Chief timing] total=1420ms recurrence=8 sweeps=210 context=340
                 enrich=15 prompt=4 model=843 warm=8 lane=chat streamed=1

What has to hold:

  1. IT FIRES. On every turn, not just slow ones or voice ones. A
     monitor that ships green and silent is what a broken monitor looks
     like — so the test asserts the line exists and carries real
     numbers, not that the code merely contains a logger call.
  2. THE STAGES ARE ATTRIBUTED, NOT AVERAGED. A slow stage must show up
     as ITS OWN number. If the whole point is aiming the next fix, a
     total is exactly the number that cannot aim it.
  3. IT NEVER BREAKS A TURN. An instrument that can take down the thing
     it measures is worse than no instrument.
  4. IT LOGS NOTHING SENSITIVE. Durations and counts only. A timing log
     that needed redacting would be the wrong shape for one that stays
     on in production.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos
import chief_prewarm


_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}, "created_at": "2026-01-01T00:00:00Z"}

SECRET = "Monica Walton's engagement letter is in Approvals"


class _Session:
    class _User:
        id = "user-1"
    user = _User()
    token = "test-jwt"


@pytest.fixture
def run_turn(monkeypatch):
    """Drive a real chief_chat. `slow` names a stage to make expensive so
    the test can prove that stage is attributed to itself."""
    delays = {}

    # The per-user rate limiter is real and in-process. A file that
    # drives dozens of turns as the same practitioner trips it — the
    # turns then 429 and the test fails for a reason that has nothing to
    # do with what it is testing. Neutralised here, and only here.
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: True)


    async def _instant(value=None):
        return value

    def _staged(name, value):
        async def inner(*a, **k):
            if delays.get(name):
                await asyncio.sleep(delays[name])
            return value
        return inner

    async def _fake_sb(client, method, path, body=None):
        return [_BIZ]
    monkeypatch.setattr(cos, "_sb", _fake_sb)
    monkeypatch.setattr(cos, "_generate_missing_recurring_instances",
                        _staged("recurrence", 0))
    monkeypatch.setattr(cos, "_autopilot_sweep", _staged("sweeps", 0))
    monkeypatch.setattr(cos, "_evaluate_escalations", lambda *a, **k: _instant(0))
    monkeypatch.setattr(cos, "_gather_context",
                        _staged("context", {"business": _BIZ, "contacts": []}))
    monkeypatch.setattr(cos, "_fetch_view_detail", lambda *a, **k: _instant(""))
    for name in ["_get_voice_examples", "_get_session_context",
                 "_get_time_context", "_get_habit_insights"]:
        monkeypatch.setattr(cos, name, _staged("enrich", ""))
    monkeypatch.setattr(cos, "_should_show_mentor_tip", lambda *a, **k: _instant(False))
    monkeypatch.setattr(cos, "_forecast_revenue", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_analyze_relationships", lambda *a, **k: _instant([]))
    monkeypatch.setattr(cos, "_build_system_prompt", lambda *a, **k: "SYSTEM")
    monkeypatch.setattr(cos, "_call_claude", _staged("model", "All good."))
    monkeypatch.setattr(cos, "_log_chief_activity", lambda *a, **k: _instant(None))
    monkeypatch.setattr(cos, "_learn_patterns_async", lambda *a, **k: _instant(None))

    import chief_bookkeeping
    import chief_proactive_suggestions
    import vertical_context
    monkeypatch.setattr(chief_bookkeeping, "gather_and_format", lambda *a, **k: "")
    monkeypatch.setattr(vertical_context, "build_vertical_learned_block",
                        lambda *a, **k: "")
    monkeypatch.setattr(chief_proactive_suggestions,
                        "maybe_emit_proactive_suggestions", lambda *a, **k: None)

    def _run(caplog, slow=None, seconds=0.25, message="how's the business doing?"):
        delays.clear()
        if slow:
            delays[slow] = seconds
        chief_prewarm.clear()
        with caplog.at_level(logging.INFO, logger="chief"):
            out = asyncio.run(cos.chief_chat(
                cos.ChatRequest(business_id="biz-1", message=message), _Session()))
        lines = [r.getMessage() for r in caplog.records
                 if "[Chief timing]" in r.getMessage()]
        return out, lines

    return _run


def _fields(line):
    return {k: v for k, v in re.findall(r"(\w+)=(\d+)", line)}


# ─────────────────────────────────────────────────────────────────────
# 1. It fires
# ─────────────────────────────────────────────────────────────────────

def test_every_turn_logs_its_timing(run_turn, caplog):
    out, lines = run_turn(caplog)
    assert out["response"] == "All good."
    assert len(lines) == 1, (
        "exactly one timing line per turn — none means the instrument is "
        "silent, more than one means it is double-counting"
    )


def test_the_line_carries_every_stage(run_turn, caplog):
    _, lines = run_turn(caplog)
    f = _fields(lines[0])
    for stage in ("total", "recurrence", "sweeps", "context", "enrich",
                  "prompt", "model", "warm"):
        assert stage in f, f"{stage} missing from: {lines[0]}"
    assert "lane=chat" in lines[0]


def test_the_numbers_are_real_not_zeroes(run_turn, caplog):
    _, lines = run_turn(caplog, slow="model", seconds=0.25)
    f = _fields(lines[0])
    assert int(f["model"]) >= 200, (
        f"a 250ms model call must show as ~250ms, got {f['model']} — "
        f"a timing log full of zeroes is a broken one"
    )
    assert int(f["total"]) >= int(f["model"])


# ─────────────────────────────────────────────────────────────────────
# 2. The stages are attributed, not averaged
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage", ["recurrence", "sweeps", "context", "model"])
def test_slowing_a_stage_moves_only_that_stage(run_turn, caplog, stage):
    """The whole point is aiming the next fix, so a slow stage has to show
    up as ITS OWN number. A total is exactly the number that cannot aim it.

    Compared as a DELTA against a baseline turn rather than against a
    fixed budget. Stages carry real background cost that this harness
    cannot mock away — `prompt` does a lazy import and two sync profile
    reads, `recurrence` pays the httpx client construction — so an
    absolute "every other stage is under 150ms" assertion fails for
    reasons that have nothing to do with attribution. What attribution
    actually means is: add 250ms to one stage, and only that stage's
    number moves.
    """
    _, base_lines = run_turn(caplog)
    base = _fields(base_lines[0])
    caplog.clear()
    _, slow_lines = run_turn(caplog, slow=stage, seconds=0.25)
    slow = _fields(slow_lines[0])

    moved = int(slow[stage]) - int(base[stage])
    assert moved >= 200, (
        f"slowed {stage} by 250ms but its number moved {moved}ms | "
        f"baseline: {base_lines[0]} | slowed: {slow_lines[0]}"
    )
    for other in ("recurrence", "sweeps", "context", "model"):
        if other == stage:
            continue
        drift = abs(int(slow[other]) - int(base[other]))
        assert drift < 150, (
            f"slowing {stage} moved {other} by {drift}ms — the stages are "
            f"not separated | baseline: {base_lines[0]} | "
            f"slowed: {slow_lines[0]}"
        )


def test_the_prewarm_hit_count_is_reported(run_turn, caplog):
    """warm=8 with a low enrich is the prewarm working; warm=0 on a voice
    turn is the thing to chase."""
    _, lines = run_turn(caplog)
    assert "warm=0" in lines[0], "nothing was prewarmed in this turn"

    chief_prewarm.store("user-1", "biz-1", {
        "voice_examples": "", "session_context": "", "mentor_active": False,
        "forecast": None, "relationship_insights": [], "time_block": "",
        "habit_block": "", "bookkeeping_block": "",
    })
    try:
        # run_turn clears the cache, so drive the turn directly here.
        with caplog.at_level(logging.INFO, logger="chief"):
            caplog.clear()
            asyncio.run(cos.chief_chat(
                cos.ChatRequest(business_id="biz-1", message="hi"), _Session()))
        line = [r.getMessage() for r in caplog.records
                if "[Chief timing]" in r.getMessage()][0]
        assert "warm=8" in line, line
    finally:
        chief_prewarm.clear()


# ─────────────────────────────────────────────────────────────────────
# 3. It never breaks a turn
# ─────────────────────────────────────────────────────────────────────

def test_logging_never_raises_on_junk_fields(caplog):
    """log() is the part that formats, so log() is the part that is
    guarded. An instrument that can take down the thing it measures is
    worse than no instrument."""
    clock = cos._TurnClock()
    clock.mark("stage")
    with caplog.at_level(logging.INFO, logger="chief"):
        clock.log(lane=object(), streamed=None)   # not formattable as ints
    # Not raising IS the assertion.


def test_a_broken_logging_backend_does_not_raise(monkeypatch):
    """The guard lives in _TurnClock.log, so that is what is tested. An
    instrument that can take down the thing it measures is worse than no
    instrument."""
    def _boom(*a, **k):
        raise RuntimeError("logging backend is down")
    monkeypatch.setattr(cos.logger, "info", _boom)
    clock = cos._TurnClock()
    clock.mark("stage")
    clock.log(lane="chat", streamed=False)   # must not raise


# ─────────────────────────────────────────────────────────────────────
# 4. It logs nothing sensitive
# ─────────────────────────────────────────────────────────────────────

def test_the_timing_line_carries_no_content_or_identity(run_turn, caplog):
    _, lines = run_turn(caplog, message=SECRET)
    line = lines[0]
    for leak in ("Monica", "Walton", "Approvals", "biz-1", "user-1",
                 "test-jwt", "KMJ"):
        assert leak not in line, f"timing log leaked {leak!r}: {line}"
    # Everything after the tag should be key=value pairs only.
    body = line.split("[Chief timing] ", 1)[1]
    for token in body.split():
        assert re.fullmatch(r"\w+=[\w.]+", token), f"unexpected token {token!r}"
