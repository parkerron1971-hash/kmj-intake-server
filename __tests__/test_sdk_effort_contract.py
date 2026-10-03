"""Effort through the REAL pinned SDK (2026-10-03).

requirements.txt pins anthropic==0.34.2, which predates `output_config`.
Passed as a keyword it is a TypeError before any request leaves, so the
Director's first blueprint on Opus 5.5 died in seven seconds, and the
builder's own effort (default high) would have killed every builder run
on Railway the same way. The fakes the other tests use accept any
keyword, and a newer local SDK accepts this one, which is how it hid.

These tests drive the INSTALLED SDK (CI installs the pinned one) against
an in-process transport and read the JSON body that would have been sent:
the effort must arrive as `output_config.effort`, and constructing the
call must not raise.
"""
import json

import httpx
import pytest

import model_ladder

_MESSAGE = {"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
            "content": [{"type": "text", "text": "SPEC DOCUMENT"}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1}}

_SSE = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in (
    ("message_start", {"type": "message_start", "message": {
        **_MESSAGE, "content": [], "stop_reason": None}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "SPEC DOCUMENT"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta",
                       "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                       "usage": {"output_tokens": 1}}),
    ("message_stop", {"type": "message_stop"}),
))


def _real_sdk_client(sent):
    """The installed anthropic SDK, wired to a transport that records the
    request body and answers like the API (JSON or a stream)."""
    import anthropic

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body)
        if body.get("stream"):
            return httpx.Response(200, text=_SSE,
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=_MESSAGE)

    return anthropic.Anthropic(api_key="sk-test-not-real", max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_sdk_helper_never_puts_output_config_at_the_top():
    kw = model_ladder.sdk_effort_kwargs("claude-opus-5-5", "high")
    assert "output_config" not in kw
    assert kw == {"extra_body": {"output_config": {"effort": "high"}}}
    assert model_ladder.sdk_effort_kwargs("claude-sonnet-4-5-20250929", "high") == {}
    # raw-HTTP payloads (Chief) keep the plain field
    assert model_ladder.effort_kwargs("claude-opus-5-5", "low") == {"output_config": {"effort": "low"}}


def test_the_builder_kwargs_survive_a_real_stream():
    import builder_v2
    sent = []
    client = _real_sdk_client(sent)
    with client.messages.stream(model="claude-opus-5-5", max_tokens=100, system="s",
                                messages=[{"role": "user", "content": "u"}],
                                **builder_v2._gen_kwargs("claude-opus-5-5", 0.2)) as s:
        for _ in s.text_stream:
            pass
        s.get_final_message()
    assert sent[0]["output_config"] == {"effort": builder_v2.BUILDER_EFFORT}
    assert "temperature" not in sent[0]          # Opus 5.5 400s on it


def test_the_director_reaches_the_api_through_the_real_sdk(monkeypatch):
    import llm_call
    import spec_author
    sent = []
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: _real_sdk_client(sent))
    monkeypatch.setattr(model_ladder, "call_with_ladder",
                        lambda fn, model, task, business_id, max_tokens:
                        (fn(model, max_tokens, 60.0), model))
    monkeypatch.setattr(spec_author, "_model", lambda: "claude-opus-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.delenv("SPEC_EFFORT", raising=False)
    assert spec_author._call_llm("sys", "user", "biz") == "SPEC DOCUMENT"
    assert sent[0]["stream"] is True
    assert sent[0]["output_config"] == {"effort": "medium"}
    assert sent[0]["max_tokens"] == spec_author.SPEC_MAX_TOKENS


@pytest.mark.parametrize("model,expect", [
    ("claude-sonnet-5-5", {"effort": "medium"}),
    ("claude-sonnet-4-5-20250929", None),
])
def test_the_grader_reaches_the_api_through_the_real_sdk(monkeypatch, model, expect):
    import llm_call
    import vision_grader as vg
    sent = []
    monkeypatch.setattr(llm_call, "sdk_client", lambda key=None, **kw: _real_sdk_client(sent))
    monkeypatch.setattr(vg, "_meter", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("VISION_JUDGE_MODEL", model)
    monkeypatch.delenv("VISION_JUDGE_EFFORT", raising=False)
    assert vg._grade_anthropic([b"a", b"b", b"c"], "biz-1", None, []) == "SPEC DOCUMENT"
    assert sent[0].get("output_config") == expect
