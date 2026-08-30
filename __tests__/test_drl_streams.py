"""
test_drl_streams.py — THE RATIONALE STREAMS (2026-08-29).

Run 3 of the judge rehearsal: a DRO came back at EXACTLY 14,000 output
tokens with 5,390 visible characters — on the 5-family, hidden
reasoning counts against max_tokens and the cap cut the JSON before
halfway. The DRL call now streams (the SDK refuses non-streaming
requests that could run past ten minutes) so the cap can be what a
whole rationale needs.
"""
from unittest import mock

import pytest

import model_ladder
import agents.composer.drl.passes as passes
from __tests__.test_dro_prefill_fallback import _Msg, _FakeStream


@pytest.fixture(autouse=True)
def _fresh_prefill_memory(monkeypatch):
    monkeypatch.setattr(passes, "_PREFILL_REJECTED", set())


def _passthrough(fn, model, task, business_id, max_tokens):
    return fn(model, max_tokens, 60.0), model


class _StreamOnlyClient:
    """create() is a trap: the DRL must generate by streaming."""

    def __init__(self, text):
        self.streams = []
        outer = self

        class _M:
            def create(_s, **kw):
                raise AssertionError("non-streaming create() called on the DRL path")

            def stream(_s, **kw):
                fs = _FakeStream(_Msg(text))
                outer.streams.append((kw, fs))
                return fs
        self.messages = _M()


def test_the_drl_call_streams_and_drains_the_stream_before_reading_the_final():
    client = _StreamOnlyClient('{"ok": 1}')
    with mock.patch.object(passes.model_ladder, "call_with_ladder", _passthrough):
        out = passes._call(client, "sys", "user", max_tokens=100, temperature=0.5,
                           business_id="biz", task="dro")
    assert out == '{"ok": 1}'
    assert len(client.streams) == 1
    kw, fs = client.streams[0]
    assert kw["max_tokens"] == 100 and kw["timeout"] == 60.0
    with pytest.raises(StopIteration):          # text_stream was drained
        next(fs.text_stream)


def test_the_cap_is_a_whole_rationale_and_the_ceiling_follows_it():
    # a 5-family DRO: ~12.5k hidden tokens before ~1.5k visible ones (run 3)
    assert passes.DRO_MAX_TOKENS >= 28000
    assert passes.SIGNAL_MAX_TOKENS >= 6000
    # non-streaming would have been refused by the SDK past ten minutes of
    # expected output (60*60*max_tokens/128000 s); streaming has no such wall
    assert 60 * 60 * passes.DRO_MAX_TOKENS / 128000 > 600
    assert model_ladder.timeout_for("dro", "claude-sonnet-5", passes.DRO_MAX_TOKENS) \
        >= passes.DRO_MAX_TOKENS / 30.0
    # the same cap reaches the continuation and the minimal rung
    assert passes.DRO_MAX_TOKENS == 32000


def test_prefill_rejection_on_the_stream_path_retries_bare_once_and_remembers():
    class _Rejecting:
        def __init__(self):
            self.kws = []
            outer = self

            class _M:
                def stream(_s, **kw):
                    outer.kws.append(kw)
                    if any(m.get("role") == "assistant" for m in kw["messages"]):
                        raise RuntimeError("400 - This model does not support assistant message prefill")
                    return _FakeStream(_Msg('{"ok":true}'))
            self.messages = _M()
    client = _Rejecting()
    with mock.patch.object(passes.model_ladder, "call_with_ladder", _passthrough), \
            mock.patch.object(passes, "_drl_model", lambda: "claude-sonnet-5"):
        out = passes._call(client, "sys", "u", max_tokens=10, temperature=0.5,
                           business_id="biz", task="dro", prefill='{"dro_version"')
        assert out == '{"ok":true}' and len(client.kws) == 2
        passes._call(client, "sys", "u", max_tokens=10, temperature=0.5,
                     business_id="biz", task="dro", prefill='{"dro_version"')
        assert len(client.kws) == 3                                  # bare straight away
