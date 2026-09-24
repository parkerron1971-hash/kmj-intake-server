"""Chat answers arrive fast and whole — the 2026-09-19 audit's backend fixes.

From the audit of 24 turns after the 9/18 fixes (8 still walled):
- "Give me an update on the business" → withheld for "claim number 24 is
  not in the quote :: twenty users by November 24" (a DATE's day judged
  as a quantity), then the 15 s repair timed out → "No action ran in this
  request" after 58 seconds, 42 of them in the check.
- "the booking site" / the 90-day plan → opened the page, then replied
  "I could not verify the explanation. Please check the results shown."
  because a navigation is not a write receipt.
- A dropped stream cancelled the server turn, so the client's re-POST ran
  every action again; the voice lane had no request id at all.
- ElevenLabs' concurrent cap switched Chief's voice to Nova mid-call.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
import chief_stream_replay as replay
import chief_truth as truth


# ── 1. spoken dates are the same figures as the record's ISO date ─────

@pytest.mark.parametrize("spoken", [
    "twenty users by November 24, still at zero",
    "by Nov. 24th",
    "the 24th of November",
    "November 24, 2026",
])
def test_a_spoken_date_reads_as_month_and_day(spoken):
    nums = truth._numbers(spoken)
    assert {Decimal(11), Decimal(24)} <= nums, (spoken, nums)


def test_the_goal_claim_that_walled_the_update_now_checks_against_its_record():
    sources = {"context:goals": {"kind": "context",
        "text": '[{"title": "20 Solutionist System users", "target": 20, "current": 0, "due": "2026-11-24"}]'}}
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": "twenty users by November 24, still at zero", "kind": "fact",
         "source_id": "context:goals", "quote": '"target": 20, "current": 0, "due": "2026-11-24"'}]})
    verdict, _, reason = truth.assess_review(raw, "You have twenty users by November 24, still at zero.", sources)
    assert verdict == "supported", reason


def test_iso_dates_money_and_identifiers_are_unchanged():
    nums = {int(n) for n in truth._numbers("INV-2026-007 for $150, order A1B2, due 2026-09-14T10:00")}
    assert {150, 2026, 9, 14, 10, 0} <= nums and 7 not in nums and 1 not in nums
    assert truth._numbers("3 things at 3pm") == {Decimal(3), Decimal(15), Decimal(0)}
    assert Decimal(5) in truth._numbers("5 invoices in May")


# ── 2. a navigation is the receipt for "I've opened it" ────────────────

def _nav_receipt():
    return {"type": "navigate", "result": "opened", "label": "Opened BUILD → booking",
            "nav": {"tab": "build", "sub": "booking"}}


def test_a_navigation_receipt_supports_an_opened_claim():
    sources = truth.evidence_for_review({}, "", [_nav_receipt()])
    assert sources["result:0"]["kind"] == "receipt" and sources["result:0"]["effect"] == "ui"
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": "opened your booking page", "kind": "action", "source_id": "result:0",
         "quote": '"result": "opened"'}]})
    verdict, cited, reason = truth.assess_review(raw, "I've opened your booking page.", sources)
    assert verdict == "supported" and cited == ["result:0"], reason
    # ...but it is not a write: "nothing was sent" still clears.
    assert truth.wrote_anything(sources) is False


def test_a_withheld_reply_beside_a_navigation_shows_where_it_went_not_a_wall():
    result, meta = asyncio.run(truth.finalize_reply(None, "Here is your booking page, and I sent Ada a text.",
        ctx={}, view_detail="", taken=[_nav_receipt()], message="the booking site", business_id="biz",
        reviewer=AsyncMock(return_value=json.dumps({"verdict": "unsupported", "claims": [
            {"text": "I sent Ada a text", "kind": "action", "source_id": "", "quote": "", "gap": "no send receipt"}]}))))
    # Where it went, then one honest line for what was left out (2026-09-23).
    assert result.startswith("Opened BUILD → booking")
    assert "left the rest of my answer out" in result and "sent Ada" not in result
    assert "could not verify the explanation" not in result
    assert meta["status"] == "receipts"


# ── 3. the check has a budget ─────────────────────────────────────────

def test_the_repair_is_skipped_when_the_budget_is_spent():
    calls = {"repair": 0}

    async def slow_reviewer(client, system, messages, **kw):
        await asyncio.sleep(0.3)
        return json.dumps({"verdict": "unsupported", "claims": [
            {"text": "You earned $900.", "kind": "fact", "source_id": "", "quote": "", "gap": "no ledger"}]})

    async def repairer(client, system, messages, **kw):
        calls["repair"] += 1
        return "You earned money."

    t0 = time.monotonic()
    result, meta = asyncio.run(truth.finalize_reply(None, "You earned $900.", ctx={}, view_detail="",
        taken=[], message="how much did I earn", business_id="biz",
        reviewer=slow_reviewer, repairer=repairer, budget_s=0.5))
    assert calls["repair"] == 0
    assert meta["status"] == "withheld"
    assert time.monotonic() - t0 < 5


def test_the_repair_runs_inside_a_generous_budget():
    calls = {"repair": 0, "review": 0}

    async def reviewer(client, system, messages, **kw):
        calls["review"] += 1
        if calls["review"] == 1:
            return json.dumps({"verdict": "unsupported", "claims": [
                {"text": "I texted your invoice.", "kind": "action", "source_id": "", "quote": "", "gap": "no receipt"}]})
        return json.dumps({"verdict": "supported", "claims": []})

    async def repairer(client, system, messages, **kw):
        calls["repair"] += 1
        return "Which invoice should I text?"

    result, meta = asyncio.run(truth.finalize_reply(None, "I texted your invoice.", ctx={}, view_detail="",
        taken=[], message="text the invoice", business_id="biz",
        reviewer=reviewer, repairer=repairer, budget_s=45.0))
    assert result == "Which invoice should I text?" and meta.get("recovered")
    assert calls["repair"] == 1


# ── 4. a dropped stream waits for the running turn instead of re-running ─

@pytest.fixture(autouse=True)
def _clean():
    replay._receipts.clear()
    replay._inflight.clear()
    yield
    replay._receipts.clear()
    replay._inflight.clear()


def _request(**kw):
    return chief.ChatRequest(**{"business_id": "biz", "message": "send the invoice",
                                "request_id": "turn-1", **kw})


def test_the_re_post_waits_for_the_in_flight_turn():
    async def scenario():
        started = asyncio.Event()

        async def turn():
            started.set()
            await asyncio.sleep(0.2)
            return {"response": "Sent.", "actions_taken": [{"type": "send_invoice", "result": "sent"}]}

        task = asyncio.create_task(turn())
        replay.register(_request(), "owner", task)
        await started.wait()
        got = await replay.recover_async(_request(), "owner")
        assert got == {"response": "Sent.", "actions_taken": [{"type": "send_invoice", "result": "sent"}]}
        await asyncio.sleep(0)
        assert not replay._inflight
    asyncio.run(scenario())


def test_recover_async_is_none_for_another_turn_or_a_missing_request_id():
    async def scenario():
        task = asyncio.create_task(asyncio.sleep(0.05, result={"response": "x"}))
        replay.register(_request(), "owner", task)
        assert await replay.recover_async(_request(request_id="turn-2"), "owner") is None
        assert await replay.recover_async(_request(), "someone-else") is None
        assert await replay.recover_async(_request(request_id=None), "owner") is None
        await task
    asyncio.run(scenario())


def test_the_stream_endpoint_no_longer_cancels_the_turn():
    src = pathlib.Path(chief.__file__).read_text(encoding="utf-8")
    tail = src[src.index('@router.post("/agents/chief/chat/stream")'):]
    tail = tail[:tail.index("return StreamingResponse")]
    assert "turn.cancel()" not in tail
    assert "chief_stream_replay.register(req, _uid, turn)" in tail


# ── 5. the voice budget is passed ─────────────────────────────────────

def test_the_voice_lane_gets_the_short_budget():
    src = pathlib.Path(chief.__file__).read_text(encoding="utf-8")
    assert 'budget_s=20.0 if lane == "voice" else 45.0' in src


# ── 6. one retry before the voice changes ─────────────────────────────

def test_elevenlabs_busy_is_retried_once_before_falling_back(monkeypatch):
    import whisper_proxy
    calls = {"n": 0}

    async def speak(*a, **k):
        calls["n"] += 1
        return None if calls["n"] == 1 else "audio"

    monkeypatch.setattr(whisper_proxy, "_elevenlabs_speak", speak)
    monkeypatch.setattr(whisper_proxy, "ELEVENLABS_BUSY_RETRY_S", 0)
    src = pathlib.Path(whisper_proxy.__file__).read_text(encoding="utf-8")
    assert src.count("await _elevenlabs_speak(") >= 2
    assert "ELEVENLABS_BUSY_RETRY_S" in src
