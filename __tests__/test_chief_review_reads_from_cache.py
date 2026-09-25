"""
test_chief_review_reads_from_cache.py — the answer check stops paying full price for the same records (2026-09-24).

api_usage over 4 days: every answer review sent ~20k input tokens with
nothing cached (~4.6c of a ~5c check), though the business's records are
the same from one message to the next and between a review and its
recheck. The review document is unchanged but for key order; it goes out
as text blocks whose concatenation is that document, steadiest records
first, each group behind a cache breakpoint.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff  # noqa: F401  (chief_truth imports it lazily)
import chief_truth as truth


def _doc(sources, draft="Five invoices."):
    return {"owner_message": "what's overdue?", "draft": draft, "sources": sources, "unavailable": []}


SOURCES = {
    "result:0": {"kind": "record", "text": "list_scheduled: []"},
    "context:email_replies": {"kind": "context", "text": "no replies"},
    "context:current_view": {"kind": "context", "text": "home"},
    "context:open_invoices": {"kind": "context", "text": "[{\"total\": 40}]"},
    "context:events": {"kind": "context", "text": "[]"},
    "context:offerings": {"kind": "context", "text": "[...]"},
    "context:blueprint_block": {"kind": "context", "text": "The plan..."},
    "conversation:current": {"kind": "conversation", "text": "what's overdue?"},
    "turn:execution": {"kind": "record", "text": "No action ran."},
}


def _split(doc):
    return truth._cacheable_review_messages([{"role": "user", "content": json.dumps(doc)}])[0]["content"]


def test_the_blocks_are_the_same_document():
    doc = _doc(SOURCES)
    blocks = _split(doc)
    assert json.loads("".join(b["text"] for b in blocks)) == doc


def test_steady_records_then_prose_then_activity_each_cached():
    blocks = _split(_doc(SOURCES))
    assert len(blocks) == 4
    assert all(b.get("cache_control") == {"type": "ephemeral"} for b in blocks[:3])
    assert "cache_control" not in blocks[3]
    steady, prose, activity, tail = (b["text"] for b in blocks)
    assert "context:open_invoices" in steady and "context:offerings" in steady
    assert "context:blueprint_block" in prose
    assert "context:events" in activity and "context:email_replies" in activity
    # The turn's own reads, the page, the conversation and the draft are never cached.
    for turn_only in ("result:0", "context:current_view", "conversation:current", "Five invoices."):
        assert turn_only in tail


def test_a_new_draft_and_new_activity_leave_the_steady_records_cached():
    first = _split(_doc(SOURCES))
    later = _split(_doc({**SOURCES, "context:events": {"kind": "context", "text": "[1]"}}, draft="Two invoices."))
    assert first[0]["text"] == later[0]["text"] and first[1]["text"] == later[1]["text"]
    assert first[2]["text"] != later[2]["text"]


def test_the_evidence_clock_does_not_change_the_records():
    def steady(stamp):
        ctx = {"open_invoices": [{"n": 1}], "context_quality": {"retrieved_at": stamp}}
        return _split(_doc(truth.evidence_for_review(ctx, "", [])))[0]["text"]
    assert steady("2026-09-24T11:34:52.076830+00:00") == steady("2026-09-24T11:36:15.210134+00:00")


def test_only_the_turn_parts_and_no_records_goes_out_unchanged():
    msgs = [{"role": "user", "content": json.dumps(_doc({"conversation:current": {"text": "hi"}}))}]
    assert truth._cacheable_review_messages(msgs) is msgs
    for odd in ([{"role": "user", "content": "not json"}], [], [{"role": "user", "content": [{"type": "text"}]}]):
        assert truth._cacheable_review_messages(odd) is odd


class _Resp:
    status_code = 200

    def json(self):
        return {"content": [{"type": "text", "text": '{"verdict":"supported","claims":[]}'}]}


def test_the_review_request_caches_its_instructions_and_records(monkeypatch):
    import chief_models
    import llm_call
    import spend_guard
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None: "claude-sonnet-5")
    doc = _doc(SOURCES)
    asyncio.run(truth.review_reply(None, truth.REVIEW_SYSTEM,
                [{"role": "user", "content": json.dumps(doc)}], max_tokens=100))
    assert sent["system"] == [{"type": "text", "text": truth.REVIEW_SYSTEM,
                               "cache_control": {"type": "ephemeral"}}]
    breakpoints = sum(1 for b in sent["system"] + sent["messages"][0]["content"] if "cache_control" in b)
    assert breakpoints <= 4  # the API's limit per request
    assert json.loads("".join(b["text"] for b in sent["messages"][0]["content"])) == doc


def test_the_prose_repair_is_sent_as_given(monkeypatch):
    # The repair runs at most once a turn under its own instructions: a
    # cache it wrote was never read back, only paid for at 1.25x.
    import chief_models
    import llm_call
    import spend_guard
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None: "claude-sonnet-5")
    content = json.dumps(_doc(SOURCES))
    asyncio.run(truth.repair_reply(None, truth.REPAIR_SYSTEM,
                [{"role": "user", "content": content}], max_tokens=100))
    assert sent["system"] == truth.REPAIR_SYSTEM
    assert sent["messages"] == [{"role": "user", "content": content}]
