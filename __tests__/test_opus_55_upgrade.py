"""Opus migration contracts: real SDK wire payloads and typed responses."""
import json

import httpx
import pytest

import chief_models
import llm_call
import model_ladder


def _message(text='{"ok": true}'):
    return {"id": "msg_test", "type": "message", "role": "assistant",
            "model": "claude-opus-5-5", "stop_reason": "end_turn",
            "stop_sequence": None,
            "content": [{"type": "thinking", "thinking": "private", "signature": "sig"},
                        {"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": 20}}


@pytest.fixture
def sdk_wire(monkeypatch):
    import anthropic
    import api_usage_logger
    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=_message())

    client = anthropic.Anthropic(
        api_key="sk-test", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("SITE_LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: client)
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", lambda **kw: None)
    yield sent
    client.close()


@pytest.mark.parametrize("stage,base", [("spec", 4000), ("atelier", 8000)])
def test_composer_stages_send_effort_with_the_pinned_sdk(monkeypatch, sdk_wire, stage, base):
    import atelier
    import site_composer
    monkeypatch.delenv("SITE_SPEC_MODEL", raising=False)
    monkeypatch.delenv("SITE_SPEC_EFFORT", raising=False)
    monkeypatch.setenv("ATELIER_MODEL", "claude-opus-5-5")
    monkeypatch.delenv("ATELIER_EFFORT", raising=False)
    if stage == "spec":
        text = site_composer._call_spec_stage(system="sys", user="user", business_id="test")
    else:
        text = atelier._call_llm("sys", "user", "test")
    assert text == '{"ok": true}'  # skip the thinking block
    assert len(sdk_wire) == 1       # primary model worked; no fallback
    payload = sdk_wire[0]
    assert payload["model"] == "claude-opus-5-5"
    assert payload["output_config"] == {"effort": "medium"}
    assert payload["max_tokens"] == base + 4096
    assert "thinking" not in payload and "temperature" not in payload


def test_moonshot_failure_preserves_effort_in_anthropic_fallback(monkeypatch, sdk_wire):
    import site_llm
    monkeypatch.setattr(site_llm, "provider", lambda: "moonshot")
    monkeypatch.setenv("CHIEF_SUBPROCESSOR_HOSTS", "api.moonshot.ai")
    monkeypatch.delenv("SITE_STAGE_PROVIDERS", raising=False)
    attempted = []

    def fail(**kw):
        attempted.append(True)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(site_llm, "_call_moonshot", fail)
    site_llm.create_message(model="claude-opus-5-5", max_tokens=8096,
                            system="s", user_content="u", effort="medium")
    assert attempted == [True]
    assert sdk_wire[0]["output_config"] == {"effort": "medium"}
    assert "temperature" not in sdk_wire[0]


@pytest.mark.parametrize("module,entry", [
    ("studio_designer_agent", "_call_claude"),
    ("studio_decoration_generator", "call_claude"),
])
def test_studio_calls_allow_thinking_and_preserve_unicode(monkeypatch, module, entry):
    import importlib
    mod = importlib.import_module(module)
    sent = []

    def post(**kw):
        sent.append(json.loads(kw["content"]))
        return httpx.Response(200, json=_message("caf\u00e9"),
                              request=httpx.Request("POST", "https://example.test"))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(llm_call, "post", post)
    assert getattr(mod, entry)("caf\u00e9") == "caf\u00e9"
    assert sent[0]["model"] == "claude-opus-5-5"
    assert sent[0]["output_config"] == {"effort": "medium"}
    assert sent[0]["max_tokens"] == 6596
    assert sent[0]["messages"][0]["content"] == "caf\u00e9"


def test_insights_send_high_effort_and_parse_text_after_thinking(monkeypatch):
    import chief_insights
    import feature_gates
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CHIEF_MODEL_INSIGHT", raising=False)
    monkeypatch.delenv("CHIEF_EFFORT_INSIGHT", raising=False)
    monkeypatch.setattr(feature_gates, "plan_of", lambda biz: "professional")
    monkeypatch.setattr(chief_insights, "log_api_usage_sync", lambda **kw: None)
    sent = []
    expected = [{"pattern": "Sales rose 10%", "move": "Review capacity"}]

    def post(body, **kw):
        sent.append(body)
        return httpx.Response(200, json=_message(json.dumps(expected)))

    monkeypatch.setattr(llm_call, "post", post)
    assert chief_insights._synthesize({"id": "test"}, {}, [], []) == expected
    assert sent[0]["model"] == "claude-opus-5-5"
    assert sent[0]["output_config"] == {"effort": "high"}
    assert sent[0]["max_tokens"] == 9192


def test_heavy_lanes_and_explicit_rollback(monkeypatch):
    for lane in ("deep", "insight"):
        monkeypatch.delenv(f"CHIEF_MODEL_{lane.upper()}", raising=False)
        monkeypatch.delenv(f"CHIEF_EFFORT_{lane.upper()}", raising=False)
        assert chief_models.model_for(lane) == "claude-opus-5-5"
        assert chief_models.model_for(lane, "professional") == "claude-opus-5-5"
        assert chief_models.effort_for(lane) == "high"
    old_budget = chief_models.max_tokens_for("deep")
    assert chief_models.max_tokens_for("deep", model="claude-opus-5-5") == old_budget + 8192
    monkeypatch.setenv("CHIEF_MODEL_DEEP", "claude-opus-4-8")
    assert chief_models.model_for("deep", "professional") == "claude-opus-4-8"
    assert chief_models.max_tokens_for("deep", model="claude-opus-4-8") == old_budget


@pytest.mark.parametrize("plan", ["starter", "practice", "professional"])
@pytest.mark.parametrize("lane", ["deep", "insight"])
def test_effort_and_budget_follow_the_resolved_tier(monkeypatch, plan, lane):
    monkeypatch.delenv(f"CHIEF_MODEL_{lane.upper()}", raising=False)
    monkeypatch.delenv(f"CHIEF_EFFORT_{lane.upper()}", raising=False)
    model = chief_models.model_for(lane, plan)
    base = chief_models.max_tokens_for(lane)
    assert chief_models.effort_for(lane, model=model) == ("high" if plan == "professional" else None)
    assert chief_models.max_tokens_for(lane, model=model) == base + (8192 if plan == "professional" else 0)
    monkeypatch.setenv(f"CHIEF_EFFORT_{lane.upper()}", "low")
    assert chief_models.effort_for(lane, model=model) == "low"
