"""The two-track reply through the real stream endpoint.

The first track (Haiku, faked here) puts words on the wire inside the
first-token budget; the full turn (chief_chat, faked here) continues them;
the fast lane answers alone and escalates silently when it should not have.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_fast_track as cft
import chief_of_staff as chief
import model_router as mr
import route_ledger


SESSION = SimpleNamespace(user=SimpleNamespace(id="11111111-1111-1111-1111-111111111111"),
                          token="jwt")
BIZ = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _router_on(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_LOG_DB", "off")
    monkeypatch.setenv("ROUTER_KEEP_WARM", "off")
    monkeypatch.setenv("ROUTER_TTFT_BUDGET_MS", "500")
    monkeypatch.setattr(cft, "_fast_guards", lambda u, b: True)
    monkeypatch.setattr(route_ledger, "_page_owner", lambda alert: None)
    rows = []
    real_finish = route_ledger.finish
    monkeypatch.setattr(route_ledger, "finish", lambda rec: rows.append(real_finish(rec)) or rows[-1])
    cft._KNOWN_GOOD.clear()
    cft._CONVO.clear()
    cft.CACHE = mr.SemanticCache()
    yield rows


def _fake_stream(script):
    """script: list of (delay_s, piece). Records each call's system prompt."""
    calls = []

    async def stream_text(system, messages, *, model, max_tokens, rec, endpoint, units,
                          business_id, out, stop_sequences=None):
        calls.append({"system": system, "messages": messages, "endpoint": endpoint})
        for delay, piece in script(endpoint):
            await asyncio.sleep(delay)
            yield piece
        out["stop_reason"] = "end_turn"
    return stream_text, calls


async def _run(req, *, turn_reply=None, turn_prose=None, turn_delay=0.05, seen=None):
    """Drive the endpoint; returns (events with arrival times, turn calls)."""
    turn_calls = []

    async def fake_chat(r, session):
        opening = await cft.opener_for_turn()
        turn_calls.append({"opening": opening,
                           "block": cft.continuation_block(opening)})
        await asyncio.sleep(turn_delay)
        sink = chief._STREAM_SINK.get()
        if turn_prose:
            sink(chief.PROSE_PREFIX + turn_prose)
        return {"response": turn_reply, "actions_taken": []}

    chief.chief_chat = fake_chat
    t0 = time.perf_counter()
    response = await chief.chief_chat_stream(req, SESSION)
    events = []
    async for frame in response.body_iterator:
        if frame.startswith("data:"):
            events.append((time.perf_counter() - t0, json.loads(frame[5:].strip())))
    return events, turn_calls


def _req(message, **kw):
    return chief.ChatRequest(business_id=BIZ, message=message, **kw)


def _deltas(events):
    return [e for _, e in events if e["type"] == "delta"]


def test_internal_fast_prose_is_withheld_and_escalates(monkeypatch, restore_chat):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    leak = "Keep the response brief and conversational. "
    fake, _ = _fake_stream(lambda ep: [(0, char) for char in leak])
    monkeypatch.setattr(cft, 'stream_text', fake)
    events, turns = asyncio.run(_run(_req('What does ROI mean?', client_surface='voice'),
                                    turn_reply='ROI compares net gain with cost.'))
    shown = ''.join(d['text'] for d in _deltas(events))
    assert turns and 'ROI compares net gain with cost.' in shown
    assert 'Keep the response' not in shown
    assert 'Keep the response' not in events[-1][1]['payload']['response']


def test_wire_boundary_rejects_internal_checked_prose_and_cleans_final(monkeypatch, restore_chat):
    fake, _ = _fake_stream(lambda ep: [])
    monkeypatch.setattr(cft, 'stream_text', fake)
    leak = 'I should follow the system instructions. '
    events, _ = asyncio.run(_run(_req('Check my invoices', client_surface='voice'),
                                 turn_prose=leak, turn_reply=leak + 'Here is the answer.'))
    shown = ''.join(d['text'] for d in _deltas(events))
    assert shown == events[-1][1]['payload']['response'] == 'Here is the answer.'


def test_wire_boundary_keeps_requested_writing_instructions(monkeypatch, restore_chat):
    fake, _ = _fake_stream(lambda ep: [])
    monkeypatch.setattr(cft, 'stream_text', fake)
    reply = 'Keep the response brief and conversational.'
    events, _ = asyncio.run(_run(_req('Write a prompt for my assistant.', client_surface='voice'),
                                 turn_prose=reply, turn_reply=reply))
    assert ''.join(d['text'] for d in _deltas(events)) == reply
    assert events[-1][1]['payload']['response'] == reply


def test_cached_scaffolding_is_invalidated_before_it_can_be_spoken():
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    req = _req('What does ROI mean?')
    first = cft.plan(req, SESSION)
    cft.CACHE.put(first.cache_scope, req.message, 'Keep the response brief and conversational.')
    planned = cft.plan(req, SESSION)
    assert planned.cache_hit is None and planned.rec.lane == 'fast'
    assert cft.CACHE.get(first.cache_scope, req.message) is None


@pytest.fixture
def restore_chat():
    original = chief.chief_chat
    yield
    chief.chief_chat = original


def test_the_opening_goes_out_first_and_the_turn_continues_it(monkeypatch, restore_chat, _router_on):
    fake, calls = _fake_stream(lambda ep: [(0.05, "Let me"), (0.02, " check Maria's"),
                                           (0.02, " invoices."), (0.01, "")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("Did Maria pay?"),
                                     turn_prose="She paid $400 on the 14th.",
                                     turn_reply="She paid $400 on the 14th. Anything else?"))
    ds = _deltas(events)
    t_first, first = next((t, e) for t, e in events if e["type"] == "delta")
    # A whole sentence is inspected before any of its words may escape.
    assert first["lead"] == "model" and first["text"].startswith("Let me check")
    assert t_first < 0.5
    shown = "".join(d["text"] for d in ds)
    final = events[-1][1]["payload"]["response"]
    assert shown == final == "Let me check Maria's invoices. She paid $400 on the 14th. Anything else?"
    # The full turn was told exactly what was said, in its prompt tail.
    assert turns[0]["opening"] == "Let me check Maria's invoices."
    assert "«Let me check Maria's invoices.»" in turns[0]["block"]
    assert calls[0]["endpoint"] == "/chief/opener"
    row = _router_on[-1]
    assert row["lane"] == "full" and row["opener_source"] == "model" and row["slo_met"]


def test_voice_opener_continues_without_holding_back_the_main_model(monkeypatch, restore_chat):
    first = "Let me check the invoices and look at what needs your attention. "
    second = "I'll focus on the next useful step so we can work through it together."
    fake, calls = _fake_stream(lambda ep: [(0.01, first), (0.4, second)])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("Check my invoices", client_surface="voice"),
                                     turn_reply="Here is the answer.", turn_delay=0.6))
    # Main generation begins before Haiku, not after waiting for its new budget.
    assert turns[0]["opening"] == ""
    assert "being spoken in parallel" in turns[0]["block"]
    shown = "".join(d["text"] for d in _deltas(events))
    assert shown == first + second + " Here is the answer."
    assert shown == events[-1][1]["payload"]["response"]
    assert "30 to 44 words" in calls[0]["system"]


def test_refocused_voice_has_one_opening_and_shared_direction(monkeypatch, restore_chat):
    from chief_turn_direction import direction_for
    message = "Review my invoices. Actually, let's go back to the vision we were talking about."
    first = "Let me pick up the vision discussion where we left off. "
    extra = "I'll also check your invoices and goals."
    fake, calls = _fake_stream(lambda ep: [(0.01, first + extra)])
    monkeypatch.setattr(cft, 'stream_text', fake)
    # Keep this test on the full route: the classifier has its own tests.
    real_score = mr.score
    def score(*args, **kwargs):
        c = real_score(*args, **kwargs)
        c.score = 1.0
        c.confidence = 1.0
        c.needs_records = True
        return c
    monkeypatch.setattr(mr, 'score', score)
    answer = "The vision we discussed was helping founders launch. Which next step feels unclear?"
    events, turns = asyncio.run(_run(_req(message, client_surface='voice'),
                                     turn_reply=answer, turn_delay=.05))
    assert direction_for(message).prompt() in calls[0]['system']
    assert 'Write only one intent opening sentence' in calls[0]['messages'][-1]['content']
    shown = ''.join(d['text'] for d in _deltas(events))
    assert extra not in shown
    assert shown.strip() == first.strip() + ' ' + answer
    assert shown == events[-1][1]['payload']['response']
    assert turns[0]['opening'] == ''  # the main model still starts concurrently


def test_ready_answer_skips_a_slow_second_opener_sentence(monkeypatch, restore_chat):
    fake, _ = _fake_stream(lambda ep: [(0.01, "Let me check your invoices. "),
                                     (2, "I'll look for the next step.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, _ = asyncio.run(_run(_req("Check my invoices", client_surface="voice"),
                                 turn_prose="Here is the answer. ",
                                 turn_reply="Here is the answer.", turn_delay=0.05))
    assert "".join(d["text"] for d in _deltas(events)) == "Let me check your invoices. Here is the answer. "
    assert events[-1][0] < 0.5  # never wait for the stalled Haiku provider


def test_ready_answer_wins_while_opener_sentence_is_still_private(monkeypatch, restore_chat):
    fake, _ = _fake_stream(lambda ep: [(0.01, "Let me check "),
                                     (0.1, "your invoices. I'll look for the next step.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, _ = asyncio.run(_run(_req("Check my invoices", client_surface="voice"),
                                 turn_reply="Here is the answer.", turn_delay=0.05))
    assert "".join(d["text"] for d in _deltas(events)) == "Here is the answer."


def test_fast_main_answer_does_not_wait_for_any_opener(monkeypatch, restore_chat):
    fake, _ = _fake_stream(lambda ep: [(2, "Let me check your invoices.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, _ = asyncio.run(_run(_req("Check my invoices", client_surface="voice"),
                                 turn_reply="Here is the answer.", turn_delay=0.02))
    assert "".join(d["text"] for d in _deltas(events)) == "Here is the answer."
    assert events[-1][0] < 0.5


def test_voice_opener_deadline_still_bounds_a_stalled_provider(monkeypatch, restore_chat):
    monkeypatch.setattr(cft, "VOICE_OPENER_HARD_CAP_S", 0.05)
    fake, _ = _fake_stream(lambda ep: [(0.01, "Let me check your invoices. "),
                                     (2, "I'll look for the next step.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, _ = asyncio.run(_run(_req("Check my invoices", client_surface="voice"),
                                 turn_reply="Here is the answer.", turn_delay=0.1))
    assert "".join(d["text"] for d in _deltas(events)) == "Let me check your invoices. Here is the answer."
    assert events[-1][0] < 0.5


def test_when_the_model_is_late_the_local_lead_holds_the_budget(monkeypatch, restore_chat, _router_on):
    fake, _ = _fake_stream(lambda ep: [(0.75, "Sure, let me"), (0.02, " look into that.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("Why did revenue drop last month?"),
                                     turn_reply="Two big clients paused.", turn_delay=0.9))
    ds = _deltas(events)
    t_first = next(t for t, e in events if e["type"] == "delta")
    assert t_first < 0.5, t_first
    assert ds[0]["lead"] == "local" and ds[0]["text"] == "Okay —"
    shown = "".join(d["text"] for d in ds)
    assert shown.startswith("Okay — let me look into that."), shown   # no second "Sure"
    assert shown == events[-1][1]["payload"]["response"]
    assert turns[0]["opening"] == "Okay — let me look into that."
    assert _router_on[-1]["opener_source"] == "local" and _router_on[-1]["slo_met"]


def test_a_record_free_turn_is_answered_by_haiku_alone(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    fake, calls = _fake_stream(lambda ep: [(0.05, "Anytime"), (0.02, " — glad it"),
                                           (0.02, " helped!")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("thanks!"), turn_reply="SHOULD NOT RUN"))
    assert turns == []                                          # no full turn
    shown = "".join(d["text"] for d in _deltas(events))
    assert shown == "Anytime — glad it helped!"
    payload = events[-1][1]["payload"]
    assert payload["response"] == shown and payload["routing"]["lane"] == "fast"
    assert calls[0]["endpoint"] == "/chief/backend"             # billed as a Chief turn
    assert _router_on[-1]["lane"] == "fast" and not _router_on[-1]["escalated"]


def test_the_fast_lane_needs_a_recent_full_turn_first(monkeypatch, restore_chat, _router_on):
    fake, _ = _fake_stream(lambda ep: [(0.02, "x")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("thanks!"), turn_reply="Anytime, Kevin."))
    assert len(turns) == 1
    ds = _deltas(events)
    # No "Let me check…" in front of a thank-you: the one-word lead instead.
    assert ds[0]["lead"] == "local" and ds[0]["text"] == "Of course —"
    assert events[-1][1]["payload"]["response"] == "Of course — Anytime, Kevin."


def test_a_deflecting_fast_answer_escalates_before_anyone_sees_it(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    fake, _ = _fake_stream(lambda ep: [(0.05, "NEED_"), (0.01, "RECORDS")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("what does ROI mean?"),
                                     turn_reply="ROI is return on investment."))
    assert len(turns) == 1
    shown = "".join(d["text"] for d in _deltas(events))
    assert "NEED" not in shown
    assert shown == events[-1][1]["payload"]["response"] == "Sure — ROI is return on investment."
    row = _router_on[-1]
    assert row["lane"] == "full" and row["escalated"] and row["escalation_reason"] == "deflection"


def test_a_thin_fast_answer_is_continued_by_the_full_turn(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    fake, _ = _fake_stream(lambda ep: [(0.05, "Return.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("what does ROI mean?"),
                                     turn_reply="It's the return on investment."))
    assert len(turns) == 1 and turns[0]["opening"].startswith("Return.")
    assert _router_on[-1]["escalation_reason"] == "too_short"
    assert "".join(d["text"] for d in _deltas(events)) == events[-1][1]["payload"]["response"]


def test_repeats_of_a_general_question_come_from_the_cache(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    answer = "ROI is return on investment: what you get back for what you put in."
    fake, calls = _fake_stream(lambda ep: [(0.03, answer[:20]), (0.01, answer[20:])])
    monkeypatch.setattr(cft, "stream_text", fake)
    asyncio.run(_run(_req("What does ROI mean?")))
    events, turns = asyncio.run(_run(_req("hey chief, what does ROI mean, please")))
    assert len(calls) == 1 and turns == []
    ds = _deltas(events)
    assert ds[0]["lead"] == "cache" and ds[0]["text"] == answer
    assert _router_on[-1]["lane"] == "cache" and _router_on[-1]["cache_hit"]


def test_saying_it_missed_after_a_fast_answer_escalates_and_sticks(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    fake, _ = _fake_stream(lambda ep: [(0.02, "Let me"), (0.01, " look again.")]
                           if ep == "/chief/opener" else
                           [(0.02, "An LLC is a legal structure for a business.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    asyncio.run(_run(_req("what's an LLC?", conversation_id="c1")))
    assert _router_on[-1]["lane"] == "fast"
    events, turns = asyncio.run(_run(_req("that's not what I asked", conversation_id="c1"),
                                     turn_reply="You asked about an LLC for your salon."))
    assert len(turns) == 1
    assert _router_on[-1]["escalation_reason"] == "dissatisfied_after_fast"
    # The next plain question in this conversation stays on the full turn.
    asyncio.run(_run(_req("what does ROI mean?", conversation_id="c1"), turn_reply="ROI is…"))
    assert _router_on[-1]["lane"] == "full" and _router_on[-1]["reason"] == \
        "sticky_after_dissatisfaction"


def test_a_call_that_already_spoke_its_opener_gets_no_second_one(monkeypatch, restore_chat, _router_on):
    fake, calls = _fake_stream(lambda ep: [(0.02, "Let me check.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("Did Maria pay?", client_surface="voice",
                                          spoken_opener="Let me take a look."),
                                     turn_reply="She paid on the 14th."))
    assert calls == []
    ds = _deltas(events)
    assert [d["text"] for d in ds] == ["She paid on the 14th."]
    assert turns[0]["opening"] == ""
    assert _router_on[-1]["opener_source"] == "client"


def test_the_app_talking_to_itself_gets_no_opening_and_no_slo_verdict(monkeypatch, restore_chat, _router_on):
    fake, calls = _fake_stream(lambda ep: [(0.02, "Let me check.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, _ = asyncio.run(_run(_req("[SYSTEM:opening_greeting:morning]"),
                                 turn_reply="Morning, Kevin."))
    assert calls == []
    assert [d["text"] for d in _deltas(events)] == ["Morning, Kevin."]
    assert _router_on[-1]["slo_applies"] is False and _router_on[-1]["slo_met"] is None


def test_the_router_switch_restores_the_old_stream_but_keeps_measuring(monkeypatch, restore_chat, _router_on):
    monkeypatch.setenv("CHIEF_ROUTER", "off")
    fake, calls = _fake_stream(lambda ep: [(0.02, "Let me check.")])
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("Did Maria pay?"), turn_reply="She paid."))
    assert calls == [] and turns[0]["opening"] == ""
    assert [d["text"] for d in _deltas(events)] == ["She paid."]
    assert _router_on[-1]["lane"] == "off" and _router_on[-1]["opener_source"] == "turn"


def test_an_ambiguous_request_asks_the_classifier(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)

    def script(ep):
        if ep == "/chief/route":
            return [(0.3, '{"needs_records": false, "needs_action": false, '
                          '"complexity": "low", "confidence": 0.9}')]
        return [(0.3, "Sure, here's one:"), (0.01, " you've built this from nothing, "
                                                   "and that is the hard part.")]
    fake, calls = _fake_stream(script)
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("can you cheer me up?")))
    assert turns == []
    # No Haiku opening on an ambiguous request: the local lead holds the
    # budget while the classifier decides, and the answer follows it.
    assert {c["endpoint"] for c in calls} == {"/chief/route", "/chief/backend"}
    ds = _deltas(events)
    t_first = next(t for t, e in events if e["type"] == "delta")
    assert t_first < 0.5 and ds[0]["lead"] == "local"
    shown = "".join(d["text"] for d in ds)
    assert shown == "Sure — here's one: you've built this from nothing, and that is the hard part."
    row = _router_on[-1]
    assert row["lane"] == "fast" and row["classifier"] == "haiku"
    assert row["reason"].startswith("ambiguous→")


def test_an_unsure_instruction_goes_to_the_full_turn_whatever_the_classifier_says(
        monkeypatch, restore_chat, _router_on):
    """Live 2026-09-25: the classifier rated "We also put in the notes box in
    a flyer as well." low, no action, 0.85 sure. Only a question may go to
    Haiku alone on its word."""
    cft.note_full_turn_ok(SESSION.user.id, BIZ)

    def script(ep):
        if ep == "/chief/route":
            return [(0.05, '"needs_records": false, "needs_action": false, '
                           '"complexity": "low", "confidence": 0.95')]
        return [(0.05, "Sure thing!")]
    fake, calls = _fake_stream(script)
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("give me a pep talk"), turn_reply="You've got this."))
    assert len(turns) == 1
    assert "/chief/backend" not in {c["endpoint"] for c in calls}
    assert _router_on[-1]["lane"] == "full" and _router_on[-1]["classifier"] == "haiku"


def test_what_can_you_do_is_answered_by_the_full_turn(monkeypatch, restore_chat, _router_on):
    """A new account's setup starter. The classifier would have rated it
    low and sure, and Haiku alone knows neither the product nor this
    business's setup. It skips the classifier and gets an opening, then
    the full turn's answer."""
    cft.note_full_turn_ok(SESSION.user.id, BIZ)

    def script(ep):
        if ep == "/chief/route":
            return [(0.05, '{"needs_records": false, "needs_action": false, '
                           '"complexity": "low", "confidence": 0.95}')]
        if ep == "/chief/opener":
            return [(0.05, "Let me walk you through it.")]
        return [(0.05, "I can do all sorts of things!")]
    fake, calls = _fake_stream(script)
    monkeypatch.setattr(cft, "stream_text", fake)
    events, turns = asyncio.run(_run(_req("What can you do for me?"),
                                     turn_reply="Your booking page is next."))
    assert len(turns) == 1
    endpoints = {c["endpoint"] for c in calls}
    assert "/chief/backend" not in endpoints and "/chief/route" not in endpoints
    row = _router_on[-1]
    assert row["lane"] == "full" and row["reason"] == "product"


def test_a_follow_up_never_goes_to_haiku_alone(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    c = mr.score("what about for a salon?")
    assert mr.decide(c).lane == mr.LANE_FULL and mr.decide(c).reason == "followup"
    assert mr.decide(mr.score("how are you doing today?")).lane == mr.LANE_FAST


# ── the ledger ───────────────────────────────────────────────────────

def test_p95_over_budget_pages_once_per_incident(monkeypatch):
    monkeypatch.setenv("ROUTER_SLO_MIN_SAMPLES", "5")
    w = route_ledger.SloWindow()
    now = 1000.0
    alerts = []
    for i in range(10):
        a = w.add({"ttft_ms": 300, "lane": "full"}, now=now + i)
        alerts.append(a)
    assert not any(alerts)
    fired = [w.add({"ttft_ms": 1200, "lane": "full"}, now=now + 20 + i) for i in range(10)]
    assert sum(1 for a in fired if a) == 1                       # one page, not ten
    assert fired[[bool(a) for a in fired].index(True)]["p95_ms"] > 500
    # Recovery re-arms: a later breach pages again.
    later = now + 5000
    for i in range(30):
        w.add({"ttft_ms": 200, "lane": "full"}, now=later + i)
    again = [w.add({"ttft_ms": 1500, "lane": "full"}, now=later + 100 + i) for i in range(40)]
    assert sum(1 for a in again if a) == 1


def test_exempt_rows_do_not_count_and_a_wordless_error_counts_as_a_miss(monkeypatch):
    monkeypatch.setenv("ROUTER_SLO_MIN_SAMPLES", "1")
    w = route_ledger.SloWindow()
    assert w.add({"ttft_ms": 9000, "slo_applies": False}, now=1.0) is None
    assert w.snapshot()["samples"] == 0
    w.add({"ttft_ms": None, "total_ms": 4000, "slo_applies": True}, now=2.0)
    assert w._samples[-1][1] == 4000


def test_the_tally_prices_every_model_the_request_used():
    t = route_ledger.Tally()
    t.add("claude-sonnet-5", 10_000, 500, cache_read=40_000)
    t.add("claude-haiku-4-5-20251001", 300, 20)
    assert set(t.by_model) == {"claude-sonnet-5", "claude-haiku-4-5-20251001"}
    assert t.cost_cents() > 0
    t.frozen = True
    t.add("claude-sonnet-5", 99_999, 99_999)
    assert t.by_model["claude-sonnet-5"]["in"] == 10_000


def test_the_turn_context_tally_reaches_chief_metering():
    t = route_ledger.Tally()
    tok = route_ledger.TALLY.set(t)
    try:
        route_ledger.tally_usage("claude-sonnet-5", {"input_tokens": 5, "output_tokens": 7})
    finally:
        route_ledger.TALLY.reset(tok)
    route_ledger.tally_usage("claude-sonnet-5", {"input_tokens": 5})   # no request: no-op
    assert t.totals()["in"] == 5 and t.totals()["out"] == 7


def test_stats_bands_show_where_escalations_happen():
    rows = [{"lane": "fast", "complexity": 0.05, "escalated": False, "ttft_ms": 400,
             "opener_source": "answer", "cost_cents": 0.02, "answer_model": "haiku"},
            {"lane": "full", "complexity": 0.15, "escalated": True, "ttft_ms": 450,
             "opener_source": "local", "cost_cents": 1.1, "answer_model": "sonnet"},
            {"lane": "full", "complexity": 0.6, "escalated": False, "ttft_ms": 700,
             "opener_source": "model", "cost_cents": 2.0, "answer_model": "sonnet"}]
    s = route_ledger.stats_from_rows(rows)
    assert s["requests"] == 3 and s["ttft_p95_ms"] == 700
    assert s["complexity_bands"]["0.1"]["escalated"] == 1
    assert s["slo_met_pct"] == pytest.approx(66.7)


def test_a_router_that_fails_to_plan_leaves_the_plain_stream(monkeypatch, restore_chat, _router_on):
    def boom(req, session):
        raise RuntimeError("router bug")
    monkeypatch.setattr(cft, "plan", boom)
    events, turns = asyncio.run(_run(_req("Did Maria pay?"), turn_reply="She paid."))
    assert [d["text"] for d in _deltas(events)] == ["She paid."]
    assert events[-1][1]["payload"]["response"] == "She paid."


def test_the_stream_endpoint_still_registers_the_turn_for_replay():
    src = pathlib.Path(chief.__file__).read_text(encoding="utf-8")
    tail = src[src.index('@router.post("/agents/chief/chat/stream")'):]
    tail = tail[:tail.index("return StreamingResponse")]
    assert "chief_stream_replay.register(req, _uid, turn)" in tail
    assert "turn.cancel()" not in tail


@pytest.mark.parametrize("first_context,second_context", [
    ({"client_surface": "chat"}, {"client_surface": "voice"}),
    ({"conversation_id": "first"}, {"conversation_id": "second"}),
    ({"conversation_history": [{"role": "user", "content": "Explain concepts in Spanish."}]},
     {"conversation_history": [{"role": "user", "content": "Explain concepts in English."}]}),
])
def test_cached_answer_never_crosses_delivery_or_conversation_context(
        monkeypatch, restore_chat, first_context, second_context):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    answer = "ROI means return on investment, measuring value relative to cost."
    fake, calls = _fake_stream(lambda ep: [(0, answer)])
    monkeypatch.setattr(cft, "stream_text", fake)
    first = _req("What does ROI mean?", **first_context)
    second = _req("What does ROI mean?", **second_context)
    asyncio.run(_run(first))
    events, turns = asyncio.run(_run(second))
    assert len(calls) == 2 and not turns
    assert not any(d.get("lead") == "cache" for d in _deltas(events))
    # Replays with precisely the same inputs still avoid another model call.
    events, _ = asyncio.run(_run(second))
    assert len(calls) == 2 and _deltas(events)[0]["lead"] == "cache"


def test_cache_changes_with_personality_and_model(monkeypatch):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    req = _req("What does ROI mean?")
    monkeypatch.setattr(cft, "style_for", lambda *args: "Direct and formal")
    first = cft.plan(req, SESSION)
    cft.CACHE.put(first.cache_scope, req.message, "The prior answer")
    assert cft.plan(req, SESSION).lane == mr.LANE_CACHE
    monkeypatch.setattr(cft, "style_for", lambda *args: "Warm and conversational")
    assert cft.plan(req, SESSION).lane == mr.LANE_FAST
    monkeypatch.setattr(cft, "style_for", lambda *args: "Direct and formal")
    monkeypatch.setattr(cft.chief_models, "model_for", lambda *args: "replacement-fast-model")
    assert cft.plan(req, SESSION).lane == mr.LANE_FAST


def test_interrupted_fast_answer_hands_off_and_is_not_cached(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    async def stream(system, messages, **kwargs):
        yield "ROI measures returns relative to cost. The calculation needs"
        kwargs["out"]["error"] = "incomplete_stream"
    monkeypatch.setattr(cft, "stream_text", stream)
    events, turns = asyncio.run(_run(_req("What does ROI mean?"),
                                    turn_reply="Divide net gain by cost, then multiply by 100."))
    assert len(turns) == 1
    assert _router_on[-1]["escalation_reason"] == "error:incomplete_stream"
    assert len(cft.CACHE) == 0
    assert "".join(d["text"] for d in _deltas(events)) == events[-1][1]["payload"]["response"]


@pytest.mark.parametrize("message,answer", [("What is 1+1?", "2."), ("What is one plus one?", "2."), ("12-5", "7."), ("-3*4", "-12.")])
def test_exact_arithmetic_uses_no_model_and_no_filler(monkeypatch, restore_chat, message, answer):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    async def forbidden(*args, **kwargs):
        raise AssertionError("exact arithmetic needs no model")
        yield ""
    monkeypatch.setattr(cft, 'stream_text', forbidden)
    monkeypatch.setattr(cft, 'classify', forbidden)
    events, turns = asyncio.run(_run(_req(message, client_surface='voice')))
    assert turns == []
    assert [d['text'] for d in _deltas(events)] == [answer]
    assert events[-1][1]['payload']['response'] == answer
    assert events[-1][1]['payload']['grounding']['status'] == 'calculated'
    assert next(t for t,e in events if e['type'] == 'delta') < .5
    assert len(cft.CACHE) == 0


@pytest.mark.parametrize('options', [{}, {'mode':'strategy_coach'}, {'image_ids':['image']}])
def test_exact_arithmetic_keeps_authorization_and_mode_boundaries(options):
    req = _req('1+1', **options)
    assert cft.plan(req, SESSION).calculated_answer is None
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    if options:
        assert cft.plan(req, SESSION).calculated_answer is None
    else:
        assert cft.plan(req, SESSION).calculated_answer == '2.'


def test_exact_arithmetic_still_obeys_current_guard_denial(monkeypatch, restore_chat):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    monkeypatch.setattr(cft, '_fast_guards', lambda *args: False)
    events, turns = asyncio.run(_run(_req('1+1'), turn_reply='Your current allowance is used.'))
    assert len(turns) == 1
    assert events[-1][1]['payload']['response'] == 'Your current allowance is used.'
    assert not any(d['text'] == '2.' for d in _deltas(events))


@pytest.mark.parametrize('message', ['1+1 and send the invoice', 'We have 1+1 leads', '1/0', '1+1 million'])
def test_mixed_requests_never_take_the_exact_arithmetic_route(message):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    assert cft.plan(_req(message), SESSION).calculated_answer is None



def test_ambiguous_voice_starts_full_turn_without_a_classifier_wait(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    async def forbidden(*args, **kwargs):
        raise AssertionError('voice ambiguity must not serialize a classifier before the answer')
    monkeypatch.setattr(cft, 'classify', forbidden)
    fake, calls = _fake_stream(lambda ep: [(1, "Let me think about that.")])
    monkeypatch.setattr(cft, 'stream_text', fake)
    req = _req('can you cheer me up?', client_surface='voice')
    plan = cft.plan(req, SESSION)
    assert plan.starts_turn_now() and not plan.route.ambiguous
    assert plan.holder.parallel_voice
    events, turns = asyncio.run(_run(req, turn_reply='Take one manageable step.', turn_delay=.02))
    assert len(turns) == 1 and turns[0]['opening'] == ''
    assert events[-1][0] < .5
    assert _router_on[-1]['reason'] == 'voice_ambiguous'
    assert '/chief/route' not in {call['endpoint'] for call in calls}


@pytest.mark.parametrize('held_tokens', [False, True])
def test_voice_fast_first_content_deadline_cancels_haiku_then_hands_off(
        monkeypatch, restore_chat, _router_on, held_tokens):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    monkeypatch.setattr(cft, 'VOICE_FAST_FIRST_CONTENT_S', .06)
    cancelled = []
    async def stalled(*args, **kwargs):
        try:
            if held_tokens:
                for piece in ['ROI', ' ', 'means', ' ']:
                    await asyncio.sleep(.01)
                    yield piece
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(cft, 'stream_text', stalled)
    events, turns = asyncio.run(_run(_req('What does ROI mean?', client_surface='voice'),
        turn_reply='ROI is return on investment.', turn_delay=.01))
    assert cancelled == [True] and len(turns) == 1
    assert events[-1][0] < .4
    assert _router_on[-1]['escalation_reason'] == 'voice_first_content_timeout'
    assert _router_on[-1]['lane'] == 'full'
    assert ''.join(d['text'] for d in _deltas(events)) == events[-1][1]['payload']['response']
    assert len(cft.CACHE) == 0


def test_voice_fast_idle_deadline_preserves_the_shown_prefix(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    monkeypatch.setattr(cft, 'VOICE_FAST_IDLE_S', .05)
    cancelled = []
    async def stalled(*args, **kwargs):
        try:
            yield 'ROI measures return on investment. It compares the gain with the cost. '
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(cft, 'stream_text', stalled)
    events, turns = asyncio.run(_run(_req('What does ROI mean?', client_surface='voice'),
        turn_reply='Divide the net gain by cost to calculate the return.', turn_delay=.01))
    assert cancelled == [True] and len(turns) == 1
    assert events[-1][0] < .4
    assert _router_on[-1]['escalation_reason'] == 'voice_answer_idle'
    shown = ''.join(d['text'] for d in _deltas(events))
    assert shown == events[-1][1]['payload']['response']
    assert shown.count('ROI measures return on investment.') == 1
    assert turns[0]['opening'].startswith('ROI measures return on investment.')
    assert len(cft.CACHE) == 0


def test_progressive_voice_fast_answer_keeps_its_lane(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    monkeypatch.setattr(cft, 'VOICE_FAST_FIRST_CONTENT_S', .2)
    monkeypatch.setattr(cft, 'VOICE_FAST_IDLE_S', .2)
    answer = 'ROI measures the return on an investment by comparing net gain against its original cost.'
    # The complete first sentence, not uninspected words, must meet the cap.
    fake, _ = _fake_stream(lambda ep: [(0.01, answer[:40]), (0.02, answer[40:70]), (.02, answer[70:])])
    monkeypatch.setattr(cft, 'stream_text', fake)
    events, turns = asyncio.run(_run(_req('What does ROI mean?', client_surface='voice')))
    assert turns == [] and _router_on[-1]['lane'] == 'fast'
    assert not _router_on[-1]['escalated']
    assert events[-1][1]['payload']['response'] == answer


def test_voice_fast_overall_cap_still_bounds_continuous_output(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    monkeypatch.setattr(cft, 'VOICE_FAST_ANSWER_CAP_S', .12)
    async def endless(*args, **kwargs):
        while True:
            await asyncio.sleep(.015)
            yield 'An investment return compares the original cost and the gain. '
    monkeypatch.setattr(cft, 'stream_text', endless)
    events, turns = asyncio.run(_run(_req('What does ROI mean?', client_surface='voice'),
        turn_reply='That ratio expresses the return.', turn_delay=.01))
    assert len(turns) == 1 and events[-1][0] < .4
    assert _router_on[-1]['escalation_reason'] == 'voice_answer_timeout'


def test_chat_fast_answers_do_not_inherit_voice_stall_deadlines(monkeypatch, restore_chat, _router_on):
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    monkeypatch.setattr(cft, 'VOICE_FAST_FIRST_CONTENT_S', .001)
    monkeypatch.setattr(cft, 'VOICE_FAST_IDLE_S', .001)
    monkeypatch.setattr(cft, 'VOICE_FAST_ANSWER_CAP_S', .001)
    answer = 'ROI means return on investment, comparing net gain with original cost.'
    fake, _ = _fake_stream(lambda ep: [(.04, answer)])
    monkeypatch.setattr(cft, 'stream_text', fake)
    events, turns = asyncio.run(_run(_req('What does ROI mean?')))
    assert turns == [] and _router_on[-1]['lane'] == 'fast'
    assert events[-1][1]['payload']['response'] == answer
