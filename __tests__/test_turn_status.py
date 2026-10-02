"""
test_turn_status.py — the turn says what it is doing.

While the server reads the business, waits on the model, runs the
actions and writes the second pass, the stream now carries a status
event; the plain endpoint never sees one. Tested as arithmetic: the
prefix, the phrases, and what one sink piece becomes on the wire.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos


def test_status_rides_the_sink_only_when_streaming():
    got = []
    tok = cos._STREAM_SINK.set(got.append)
    try:
        cos._turn_status("thinking")
        cos._turn_status("")
    finally:
        cos._STREAM_SINK.reset(tok)
    assert got == [cos.STATUS_PREFIX + "thinking"]
    cos._turn_status("thinking")            # no sink: nothing happens, nothing raised


def test_actions_read_as_plain_phrases():
    acts = [{"type": "create_client_form"}, {"type": "navigate"}, {"type": "remember"}]
    assert cos._humanize_actions(acts) == "creating the form and opening the room"
    assert cos._humanize_actions([{"type": "frobnicate_widget"}]) == "frobnicate widget"
    assert cos._humanize_actions([]) == "working on it"
    assert cos._humanize_actions([{"type": "show_view"}, {"type": "show_view"}]) == "pulling up the numbers"


def test_a_status_piece_becomes_a_status_event_never_text():
    filt = cos._ActionTagFilter()
    assert cos._stream_piece_events(cos.STATUS_PREFIX + "reading your business", filt) == [
        {"type": "status", "text": "reading your business"}]
    # ordinary text still flows through the tag filter as a delta
    evs = cos._stream_piece_events("Hello there. ", filt)
    assert evs and evs[0]["type"] == "delta" and "Hello" in evs[0]["text"]
    # a status never leaks into the text the filter is holding
    evs = cos._stream_piece_events(cos.STATUS_PREFIX + "thinking", filt)
    assert all(e["type"] == "status" for e in evs)


# ─── steps: the turn shows its work (2026-09-13) ─────────────────────

import asyncio
import json


def test_a_step_starts_and_ends_on_the_sink_only_when_streaming():
    got = []
    tok = cos._STREAM_SINK.set(got.append)
    try:
        step = cos._turn_step_start("create_invoice", 3)
        assert step and step["n0"] == 3
        cos._turn_step_end(step, {"type": "create_invoice", "result": "ok", "label": "Invoice 1042 created"})
    finally:
        cos._STREAM_SINK.reset(tok)
    assert len(got) == 2
    start = json.loads(got[0][len(cos.STEP_PREFIX):])
    end = json.loads(got[1][len(cos.STEP_PREFIX):])
    assert start == {"id": step["id"], "action": "create_invoice", "label": "Writing the invoice", "state": "running"}
    assert end["id"] == step["id"] and end["state"] == "done"
    assert end["label"] == "Invoice 1042 created"
    assert isinstance(end["ms"], int) and end["ms"] >= 0
    # no sink: nothing, nothing raised, nothing to finish
    assert cos._turn_step_start("create_invoice") is None
    cos._turn_step_end(None, {"result": "x"})


def test_a_failed_or_held_result_ends_the_step_that_way():
    got = []
    tok = cos._STREAM_SINK.set(got.append)
    try:
        s1 = cos._turn_step_start("send_invoice")
        cos._turn_step_end(s1, {"type": "send_invoice", "failed": True, "result": "no address"})
        s2 = cos._turn_step_start("send_invoice")
        cos._turn_step_end(s2, {"type": "send_invoice", "failed": True, "result": "held", "label": "Held: send invoice"})
        s3 = cos._turn_step_start("frobnicate_widget")
        cos._turn_step_end(s3, None)
    finally:
        cos._STREAM_SINK.reset(tok)
    ends = [json.loads(p[len(cos.STEP_PREFIX):]) for p in got if json.loads(p[len(cos.STEP_PREFIX):])["state"] != "running"]
    assert [e["state"] for e in ends] == ["failed", "held", "failed"]
    # an unknown verb still reads as words
    assert json.loads(got[4][len(cos.STEP_PREFIX):])["label"] == "Frobnicate widget"


def test_a_step_piece_becomes_a_step_event_and_junk_is_dropped():
    filt = cos._ActionTagFilter()
    piece = cos.STEP_PREFIX + json.dumps({"id": "ab12", "action": "check_goals", "label": "Checking goals", "state": "running"})
    assert cos._stream_piece_events(piece, filt) == [
        {"type": "step", "id": "ab12", "action": "check_goals", "label": "Checking goals", "state": "running"}]
    assert cos._stream_piece_events(cos.STEP_PREFIX + "not json", filt) == []
    assert cos._stream_piece_events(cos.STEP_PREFIX + json.dumps({"label": "no id"}), filt) == []


def test_the_door_emits_one_step_per_action(monkeypatch):
    async def ok_handler(client, biz, action):
        return {"type": "remember", "result": "saved", "label": "Remembered"}

    async def bad_handler(client, biz, action):
        raise RuntimeError("boom")

    monkeypatch.setitem(cos.ACTION_HANDLERS, "remember", ok_handler)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", bad_handler)

    got = []
    tok = cos._STREAM_SINK.set(got.append)
    try:
        results = asyncio.run(cos._execute_actions(
            None, {"id": "biz-1", "owner_id": "u1"},
            [{"type": "remember", "note": "x"}, {"type": "check_goals"}], user_id="u1"))
    finally:
        cos._STREAM_SINK.reset(tok)
    assert len(results) == 2
    steps = [json.loads(p[len(cos.STEP_PREFIX):]) for p in got if p.startswith(cos.STEP_PREFIX)]
    running = [s for s in steps if s["state"] == "running"]
    finished = [s for s in steps if s["state"] != "running"]
    assert [s["action"] for s in running] == ["remember", "check_goals"]
    assert [s["state"] for s in finished] == ["done", "failed"]
    assert finished[0]["label"] == "Remembered"
    # every start has its end, matched by id
    assert {s["id"] for s in running} == {s["id"] for s in finished}


def test_steps_left_in_the_queue_when_the_turn_ends_are_flushed_not_dropped(monkeypatch):
    async def run():
        async def fake_chat(req, session):
            sink = cos._STREAM_SINK.get()
            step = cos._turn_step_start("create_invoice")
            sink("prose that must not leak")
            cos._turn_step_end(step, {"type": "create_invoice", "result": "ok", "label": "Invoice 1042 created"})
            return {"response": "Done.", "actions_taken": []}
        monkeypatch.setattr(cos, "chief_chat", fake_chat)
        response = await cos.chief_chat_stream(
            cos.ChatRequest(business_id="fixture", message="invoice"), None)
        frames = [f async for f in response.body_iterator]
        events = [json.loads(f.removeprefix("data: ").strip()) for f in frames if f.startswith("data:")]
        types = [e["type"] for e in events]
        assert "prose that must not leak" not in str(events)
        steps = [e for e in events if e["type"] == "step"]
        assert [s["state"] for s in steps] == ["running", "done"]
        assert types.index("step") < types.index("delta") < types.index("final")
        assert types[-1] == "final"
    asyncio.run(run())
