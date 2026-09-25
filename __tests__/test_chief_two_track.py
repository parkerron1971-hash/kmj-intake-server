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
                          business_id, out):
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
    assert first["lead"] == "model" and first["text"] == "Let"     # word by word
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
    events, turns = asyncio.run(_run(_req("hey chief, what does ROI mean please")))
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
    events, turns = asyncio.run(_run(_req("give me a pep talk")))
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


def test_the_stream_endpoint_still_registers_the_turn_for_replay():
    src = pathlib.Path(chief.__file__).read_text(encoding="utf-8")
    tail = src[src.index('@router.post("/agents/chief/chat/stream")'):]
    tail = tail[:tail.index("return StreamingResponse")]
    assert "chief_stream_replay.register(req, _uid, turn)" in tail
    assert "turn.cancel()" not in tail
