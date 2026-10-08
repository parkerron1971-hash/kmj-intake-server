"""
test_tools_haiku_5_5.py — the Haiku jobs outside Chief's lanes run on Haiku 5.5 (2026-10-07).

Receipt and product-photo reading, lead scoring, the action-log navigator,
the bookkeeping assist, the website look, terminology suggestions, the
interview probe, the AI proxy's volume tier and the message screen moved
from Haiku 4.5 after a side-by-side on each job. Haiku 5.5 400s on any
temperature but 1, thinks by default (its thinking counts against
max_tokens), and can decline a request on safety grounds; these tests pin
how every call handles that. Rolled back to Haiku 4.5 by env var, each
request is what it was.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace as S

import pytest

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import model_ladder  # noqa: E402

H55 = "claude-haiku-5-5"
H45 = "claude-haiku-4-5-20251001"
OFF = {"type": "disabled"}


def test_haiku_5_5_takes_no_temperature():
    assert not model_ladder.supports_sampling(H55)
    assert model_ladder.sampling_kwargs(H55, 0) == {}
    assert model_ladder.sampling_kwargs(H45, 0) == {"temperature": 0}


def test_every_default_is_haiku_5_5(monkeypatch):
    import ai_proxy
    import chief_llm
    import ledger_navigator
    import lead_scoring
    import msg_screen
    import site_composer
    monkeypatch.delenv("CHIEF_LLM_MODEL", raising=False)
    assert chief_llm._model() == H55
    assert ledger_navigator.NAV_MODEL == H55
    assert lead_scoring.REFINE_MODEL == H55
    assert msg_screen.MODEL == H55
    assert site_composer._PROBE_MODEL == H55
    assert ai_proxy.TASK_MODEL_MAP["volume"] == H55
    assert ai_proxy._select_model(None, H55) == H55   # an allowed override


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, text='{"verdict": "ok"}', stop="end_turn"):
        self._text, self._stop = text, stop

    def raise_for_status(self):
        pass

    def json(self):
        return {"model": "m", "stop_reason": self._stop, "usage": {},
                "content": [{"type": "text", "text": self._text}] if self._text else []}


def _capture_post(monkeypatch, text):
    import llm_call
    seen = {}

    def post(payload, *a, **k):
        seen.update(payload)
        return _Resp(text)
    monkeypatch.setattr(llm_call, "post", post)
    return seen


def _capture_apost(monkeypatch, text, stop="end_turn"):
    import llm_call
    seen = {}

    async def apost(client, payload, *a, **k):
        seen.update(payload)
        return _Resp(text, stop)
    monkeypatch.setattr(llm_call, "apost", apost)
    return seen


def _quick(payload, model=H55):
    assert payload["model"] == model
    assert "temperature" not in payload and "top_p" not in payload and "top_k" not in payload
    assert payload["thinking"] == OFF


def test_receipt_read_sends_haiku_5_5_with_thinking_off():
    # The read sits inside the upload endpoint, after storage; pin its request.
    import inspect
    import receipts_router
    src = inspect.getsource(receipts_router)
    assert 'os.environ.get("RECEIPT_MODEL", "claude-haiku-5-5")' in src
    block = src[src.index('model = os.environ.get("RECEIPT_MODEL"'):src.index('task="receipt-scan"')]
    assert "**chief_models.quick_call_kwargs(model)" in block and "temperature" not in block


def test_product_photo_read(monkeypatch):
    import inventory_scan
    monkeypatch.delenv("PRODUCT_SCAN_MODEL", raising=False)
    seen = _capture_post(monkeypatch, '{"name": "Pomade 4oz", "category": "product"}')
    out = asyncio.run(inventory_scan._read_label(b"\xff\xd8jpeg", "image/jpeg"))
    _quick(seen)
    assert out["name"] == "Pomade 4oz"


def test_lead_refinement(monkeypatch):
    import lead_scoring
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(lead_scoring, "REFINE_MODEL", H55)
    seen = _capture_post(monkeypatch, '{"delta": 5, "reasoning": "Specific.", "response_type": "book_time"}')
    sub = {"name": "Ann", "email": "a@x.com",
           "message": "Our pipe burst this morning and the kitchen is flooding, can you come today?"}
    out = lead_scoring.refine(lead_scoring.score_lead(sub), sub)
    _quick(seen)
    assert out.refined


def test_log_navigator(monkeypatch):
    import ledger_navigator
    monkeypatch.setattr(ledger_navigator, "NAV_MODEL", H55)
    seen = _capture_post(monkeypatch, '{"failed_only": true}')
    out = ledger_navigator.resolve("show me what failed")
    _quick(seen)
    assert out["filter"].get("failed_only") is True


def test_bookkeeping_assist(monkeypatch):
    import chief_llm
    import inference_gate
    monkeypatch.delenv("CHIEF_LLM_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(inference_gate, "lookup", lambda *a, **k: None)
    monkeypatch.setattr(inference_gate, "store", lambda *a, **k: None)
    seen = _capture_apost(monkeypatch, '{"answer": "Software."}')

    async def _noop(**k):
        pass
    import api_usage_logger
    monkeypatch.setattr(api_usage_logger, "log_api_usage", _noop)
    text = asyncio.run(chief_llm._call_claude("b1", "sys", "user", max_tokens=500, endpoint="/x"))
    _quick(seen)
    assert "Software" in text


def test_bookkeeping_batch_has_room_for_haiku_5_5_tokens():
    import inspect
    import chief_llm
    src = inspect.getsource(chief_llm.analyze_hard)
    assert 'max_tokens=1500, endpoint="/chief/analyze-hard"' in src


def test_website_look(monkeypatch):
    import chief_site_view
    import llm_call
    monkeypatch.delenv("CHIEF_VIEW_MODEL", raising=False)
    seen = {}

    class _Msgs:
        def create(self, **kw):
            seen.update(kw)
            return S(usage=S(input_tokens=1, output_tokens=1),
                     content=[S(type="text", text="A dark page.")])
    monkeypatch.setattr(llm_call, "sdk_client", lambda **k: S(messages=_Msgs()))
    assert chief_site_view.describe(b"\xff\xd8jpeg") == "A dark page."
    _quick(seen)


def test_terminology(monkeypatch):
    import sb_clients
    import terminology_overrides_router as tr
    monkeypatch.delenv("TERMINOLOGY_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(tr, "_require_owner", lambda *a, **k: {"type": "dog grooming"})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: [{"name": "Pawsh"}])
    seen = _capture_apost(monkeypatch, json.dumps({"customer": "Pet Parent"}))
    out = asyncio.run(tr.generate_overrides_via_chief(tr.GenerateBody(business_id="b1"), user=S(id="u")))
    _quick(seen)
    assert out["proposed_terminology"]["customer"] == "Pet Parent"


def test_interview_probe_passes_thinking_off(monkeypatch):
    import rate_limit
    import site_composer
    import site_llm
    seen = {}

    def create_message(**kw):
        seen.update(kw)
        return S(content=[S(type="text", text="Who do you most want to reach?")])
    monkeypatch.setattr(site_composer, "_require_owner", lambda *a, **k: None)
    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: True)
    monkeypatch.setattr(site_llm, "create_message", create_message)
    out = site_composer.interview_probe(
        site_composer.InterviewProbeBody(business_id="b1", answer="we do good work"), user=S(id="u"))
    assert out["followup"] == "Who do you most want to reach?"
    assert seen["model"] == H55 and seen["thinking"] == OFF


def test_site_llm_sends_thinking_only_when_asked(monkeypatch):
    import llm_call
    import site_llm
    monkeypatch.setattr(site_llm, "provider_for", lambda task="": "anthropic")
    calls = []

    class _Msgs:
        def create(self, **kw):
            calls.append(kw)
            return S()
    monkeypatch.setattr(llm_call, "sdk_client", lambda **k: S(messages=_Msgs()))
    site_llm.create_message(model=H55, max_tokens=10, system="s", user_content="u", thinking=OFF)
    site_llm.create_message(model="claude-opus-4-8", max_tokens=10, system="s", user_content="u")
    # Through extra_body: the pinned SDK (0.34.2) predates the `thinking`
    # keyword and would raise a TypeError on it.
    assert calls[0]["extra_body"] == {"thinking": OFF} and "thinking" not in calls[0]
    assert "thinking" not in calls[1] and "extra_body" not in calls[1]


def test_ai_proxy_volume_tier(monkeypatch):
    import ai_proxy
    from test_ai_proxy_endpoint import _FakeRequest, _user, proxy_env  # noqa: F401
    from test_i2_gl_sync import FakeSB
    import sb_clients
    fb = FakeSB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)
    sent = []

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, *a, **k):
            sent.append(k.get("json"))
            return S(status_code=200, text="", json=lambda: {
                "model": H55, "content": [{"type": "text", "text": "hi"}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}})
    monkeypatch.setattr(ai_proxy.httpx, "AsyncClient", _Client)

    async def _noop(**k): ...
    import api_usage_logger
    monkeypatch.setattr(api_usage_logger, "log_api_usage", _noop)
    monkeypatch.setattr(ai_proxy, "log_api_usage", _noop)
    req = ai_proxy.ProxyRequest(task_type="volume", messages=[{"role": "user", "content": "say hi"}],
                                max_tokens=10, temperature=0.7)
    out = asyncio.run(ai_proxy.ai_proxy(req, _FakeRequest(), _user()))
    assert out["content"] == "hi"
    _quick(sent[-1])
    # A model that takes a temperature still gets the caller's.
    req = ai_proxy.ProxyRequest(task_type="draft", messages=[{"role": "user", "content": "x"}], temperature=0.7)
    asyncio.run(ai_proxy.ai_proxy(req, _FakeRequest(), _user()))
    assert sent[-1]["temperature"] == 0.7 and "thinking" not in sent[-1]


def test_message_screen_on_haiku_5_5(monkeypatch):
    import msg_screen
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(msg_screen, "MODEL", H55)
    seen = _capture_apost(monkeypatch, '{"verdict": "harm"}')
    assert asyncio.run(msg_screen.screen("b1", "send me gift cards")) == "harm"
    _quick(seen)


def test_message_screen_rolled_back_keeps_temperature_zero(monkeypatch):
    import msg_screen
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(msg_screen, "MODEL", H45)
    seen = _capture_apost(monkeypatch, '{"verdict": "ok"}')
    asyncio.run(msg_screen.screen("b1", "see you Sunday"))
    assert seen["temperature"] == 0 and "thinking" not in seen


@pytest.mark.parametrize("text,verdict", [
    ("a message the model declined to read", "harm"),
    ("I keep thinking about killing myself", "self_harm"),
])
def test_a_safety_refusal_is_never_a_delivery(monkeypatch, text, verdict):
    # Haiku 5.5's own classifiers can decline. "Try again" would hide the
    # message from the safety officers, so it is held (or routed as a crisis).
    import msg_screen
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(msg_screen, "MODEL", H55)
    _capture_apost(monkeypatch, "", stop="refusal")
    assert asyncio.run(msg_screen.screen("b1", text)) == verdict
