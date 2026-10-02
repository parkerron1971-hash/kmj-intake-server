"""
test_drl_ceiling.py — THE CEILING FOLLOWS THE OUTPUT (2026-08-29).

The api_usage ledger showed every DRO at exactly 9,100 output tokens
(14000 x 0.65): the 120s sonnet ceiling timed out each 14k-token
rationale, the -35% retry hit its own cap mid-JSON, and the build fell
to minimal mode having paid for nothing. The per-call timeout now rises
with the tokens asked for, on every rung; and a model's prefill
rejection is remembered so no call pays a doomed round trip twice.
"""
from unittest import mock

import pytest

import model_ladder
import agents.composer.drl.passes as passes
from __tests__.test_dro_prefill_fallback import _PrefillRejectingClient, _Msg, _FakeStream


@pytest.fixture(autouse=True)
def _fresh_prefill_memory(monkeypatch):
    monkeypatch.setattr(passes, "_PREFILL_REJECTED", set())


def test_ceiling_rises_with_the_output_budget_and_keeps_the_family_floor():
    # the trap: a 14k-token DRO on sonnet under a 120s ceiling
    assert model_ladder.timeout_for("dro", "claude-sonnet-5") == 120.0
    dro = model_ladder.timeout_for("dro", "claude-sonnet-5", passes.DRO_MAX_TOKENS)
    assert dro >= passes.DRO_MAX_TOKENS / 30.0                # 14k tokens at 30 tok/s ≈ 467s+
    assert dro > 350.0                                         # the observed sonnet-5 need
    # small budgets keep the floor; slow families keep their higher floor
    assert model_ladder.timeout_for("signals", "claude-sonnet-5", 3200) == max(75.0, 3200 / 30.0 + 30.0)
    assert model_ladder.timeout_for("dro", "claude-opus-5") == 240.0
    assert model_ladder.timeout_for("dro", "claude-opus-5", 600) == 240.0
    assert model_ladder.timeout_for("dro", "claude-opus-5", passes.DRO_MAX_TOKENS) == dro
    # garbage budgets fall back to the floor, never raise
    assert model_ladder.timeout_for("dro", "claude-sonnet-5", None) == 120.0
    assert model_ladder.timeout_for("dro", "claude-sonnet-5", "x") == 120.0


def test_every_rung_gets_a_timeout_sized_to_its_own_tokens(monkeypatch):
    monkeypatch.setattr(model_ladder, "record_model_fallback", lambda *a, **k: None)
    seen = []

    class _Timeout(Exception):
        pass
    monkeypatch.setattr(model_ladder, "is_timeout_error", lambda e: isinstance(e, _Timeout))
    monkeypatch.setattr(model_ladder, "is_model_unavailable_error", lambda e: False)

    def do_call(model, max_tokens, timeout):
        seen.append((model, max_tokens, timeout))
        if len(seen) < 3:
            raise _Timeout("slow")
        return "ok"

    out, used = model_ladder.call_with_ladder(do_call, model="claude-sonnet-5",
                                              task="dro", max_tokens=14000)
    assert out == "ok" and used == model_ladder.FALLBACK_MODEL
    primary, reduced, fallback = seen
    assert primary == ("claude-sonnet-5", 14000, model_ladder.timeout_for("dro", "claude-sonnet-5", 14000))
    assert reduced[1] == 9100 and reduced[2] == model_ladder.timeout_for("dro", "claude-sonnet-5", 9100)
    assert fallback[1] == 9100 and fallback[2] == model_ladder.timeout_for("dro", model_ladder.FALLBACK_MODEL, 9100)
    assert primary[2] > reduced[2] > 120.0                     # sized, not the flat floor


def _passthrough(fn, model, task, business_id, max_tokens):
    return fn(model, max_tokens, 60.0), model


def test_prefill_rejection_is_remembered_per_model():
    client = _PrefillRejectingClient()
    with mock.patch.object(passes.model_ladder, "call_with_ladder", _passthrough), \
            mock.patch.object(passes, "_drl_model", lambda: "claude-sonnet-5"):
        passes._call(client, "sys", "u", max_tokens=100, temperature=0.5,
                     business_id="biz", task="dro", prefill='{"dro_version"')
        assert len(client.calls) == 2                          # rejected, then bare
        assert "claude-sonnet-5" in passes._PREFILL_REJECTED
        passes._call(client, "sys", "u", max_tokens=100, temperature=0.5,
                     business_id="biz", task="dro", prefill='{"dro_version"')
        assert len(client.calls) == 3                          # bare straight away
        assert all(m.get("role") == "user" for m in client.calls[2]["messages"])
    # a different model id still gets the prefill attempt

    class _Accepting:
        def __init__(self):
            self.calls = []

            class _M:
                def __init__(_s, o):
                    _s.o = o

                def create(_s, **kw):
                    _s.o.calls.append(kw)
                    return _Msg('"x": 1}')

                def stream(_s, **kw):
                    return _FakeStream(_s.create(**kw))
            self.messages = _M(self)
    acc = _Accepting()
    with mock.patch.object(passes.model_ladder, "call_with_ladder", _passthrough), \
            mock.patch.object(passes, "_drl_model", lambda: "claude-opus-5"):
        out = passes._call(acc, "sys", "u", max_tokens=100, temperature=0.5,
                           business_id="biz", task="dro", prefill='{')
    assert len(acc.calls) == 1
    assert any(m.get("role") == "assistant" for m in acc.calls[0]["messages"])
    assert out == '{"x": 1}'
