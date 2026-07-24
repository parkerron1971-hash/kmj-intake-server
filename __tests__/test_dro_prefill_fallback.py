"""
test_dro_prefill_fallback.py — the silent-brain killer (2026-07-24).

After the #235 JSON prefill shipped, the default DRL model rejected
assistant prefill with a 400 — the DRO died in 0 seconds on EVERY
build, dro=None skipped the canvas and atelier silently, and the
module path shipped the old template while the owner's approved spec
never reached an author. The call now retries bare on that specific
error, on any model, without losing the prefill benefit elsewhere.
"""
from unittest import mock

import agents.composer.drl.passes as passes


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text, model="m"):
        self.content = [_Block(text)]
        self.model = model
        self.usage = None


class _PrefillRejectingClient:
    """First call with an assistant turn raises the live 400; a bare
    user-only conversation succeeds."""

    def __init__(self):
        self.calls = []

        class _Messages:
            def __init__(_s, outer):
                _s.outer = outer

            def create(_s, **kw):
                _s.outer.calls.append(kw)
                msgs = kw.get("messages") or []
                if any(m.get("role") == "assistant" for m in msgs):
                    raise RuntimeError(
                        "Error code: 400 - This model does not support "
                        "assistant message prefill. The conversation must "
                        "end with a user message.")
                return _Msg('{"ok":true}')

        self.messages = _Messages(self)


def _ladder_passthrough(fn, model, task, business_id, max_tokens):
    return fn(model, max_tokens, 60.0), model


def test_prefill_rejection_retries_bare_and_text_not_double_prefixed():
    client = _PrefillRejectingClient()
    with mock.patch.object(passes.model_ladder, "call_with_ladder",
                           _ladder_passthrough):
        out = passes._call(client, "sys", "user text", max_tokens=100,
                           temperature=0.5, business_id="biz",
                           task="dro", prefill='{"dro_version"')
    # two attempts: prefilled (rejected) then bare (succeeded)
    assert len(client.calls) == 2
    assert any(m.get("role") == "assistant" for m in client.calls[0]["messages"])
    assert all(m.get("role") == "user" for m in client.calls[1]["messages"])
    # prefill was NOT applied on the successful bare call, so the text
    # must come back without the prefill glued on
    assert out == '{"ok":true}'


def test_prefill_still_applied_when_model_accepts_it():
    class _AcceptingClient:
        def __init__(self):
            class _Messages:
                def create(_s, **kw):
                    return _Msg(',"rest":1}')
            self.messages = _Messages()

    with mock.patch.object(passes.model_ladder, "call_with_ladder",
                           _ladder_passthrough):
        out = passes._call(_AcceptingClient(), "sys", "user", max_tokens=100,
                           temperature=0.5, business_id="biz",
                           task="dro", prefill='{"dro_version"')
    assert out.startswith('{"dro_version"')
