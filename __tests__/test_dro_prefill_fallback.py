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



# ─── THE CUT SENTENCE (2026-08-28, MaCnificent Hair Co) ──────────────
# Both full-DRO calls came back at exactly the 9000-token cap with the
# JSON cut mid-"because"; the parse retry re-rolled into the same cap
# and the build ran on the minimal brain.

def test_looks_truncated_knows_a_cut_object_from_prose_or_a_fence():
    assert passes._looks_truncated('{"dro_version": 1, "decisions": {"palette": {"because": "warm')
    assert not passes._looks_truncated('{"dro_version": 1}')
    assert not passes._looks_truncated("I cannot produce that.")
    assert not passes._looks_truncated('```json\n{"a": 1}\n```')
    assert not passes._looks_truncated("")


def test_a_cut_response_is_continued_with_the_partial_as_prefill():
    calls = []

    def _fake_call(client, system, user, *, max_tokens, temperature,
                   business_id, task, prefill=""):
        calls.append(prefill)
        return prefill + ' and unhurried"}}}'

    with mock.patch.object(passes, "_call", _fake_call):
        out = passes._continue_cut_response(
            None, "sys", "user", '{"decisions": {"palette": {"because": "warm  ',
            business_id="biz")
    # the prefill is the partial with trailing whitespace stripped (the API
    # rejects a prefill ending in whitespace), and the result is whole
    assert calls == ['{"decisions": {"palette": {"because": "warm']
    assert passes._parse_json(out) == {"decisions": {"palette": {"because": "warm and unhurried"}}}


def test_author_dro_continues_a_cut_response_instead_of_rerolling():
    """The attempt sees a cut object → ONE continuation call carrying the
    partial as prefill — not a bare re-roll with the 'not parseable' nag."""
    seen = []
    cut = '{"dro_version": 1, "decisions": {"palette": {"because": "warm'

    def _fake_call(client, system, user, *, max_tokens, temperature,
                   business_id, task, prefill=""):
        seen.append({"prefill": prefill, "user": user, "max_tokens": max_tokens})
        if prefill == cut:
            return cut + '"}}}'      # continued, still not a valid DRO — fine
        return cut                   # every fresh attempt is cut at the cap

    with mock.patch.object(passes, "_call", _fake_call), \
         mock.patch.object(passes, "_author_dro_minimal",
                           lambda *a, **k: None), \
         mock.patch.object(passes, "_select_exemplars", lambda s: []), \
         mock.patch.dict(passes.os.environ, {"ANTHROPIC_API_KEY": "k"}), \
         mock.patch.object(passes, "Anthropic", lambda *a, **k: object(),
                           create=True):
        passes.author_dro("biz", signals=[], recent=[])
    prefills = [c["prefill"] for c in seen]
    assert cut in prefills, "the cut response was never continued"
    # the continuation rides the taller cap, and the very next fresh call
    # (if any) is the parse retry, not a blind second roll at the old cap
    assert all(c["max_tokens"] == passes.DRO_MAX_TOKENS for c in seen)
    assert passes.DRO_MAX_TOKENS >= 14000
