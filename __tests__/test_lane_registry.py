"""Lane registry + llm_call.post_lane (Layer Two workstream D). No network."""
import json

import httpx
import pytest

import lane_registry
import llm_call

PORTABLE = {"model": "claude-haiku-5-5", "max_tokens": 50, "thinking": {"type": "disabled"},
            "system": "Be brief.", "messages": [{"role": "user", "content": "Classify: cozy, warm"}]}


def configure(monkeypatch, lane="BACKGROUND", key_value="sk-test"):
    monkeypatch.setenv(f"CHIEF_PROVIDER_{lane}", "openai_compatible")
    monkeypatch.setenv(f"CHIEF_PROVIDER_MODEL_{lane}", "small-open-model")
    monkeypatch.setenv(f"CHIEF_PROVIDER_URL_{lane}", "https://models.example.test/v1/")
    monkeypatch.setenv(f"CHIEF_PROVIDER_KEY_ENV_{lane}", "SMALL_MODEL_KEY")
    if key_value is not None:
        monkeypatch.setenv("SMALL_MODEL_KEY", key_value)


@pytest.fixture
def wire(monkeypatch):
    """Record every outbound POST; answer like each provider would."""
    calls, metered = [], []

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        calls.append({"url": url, "json": json, "headers": headers})
        req = httpx.Request("POST", url)
        if url.endswith("/chat/completions"):
            if getattr(fake_post, "fail_provider", False):
                return httpx.Response(503, json={"error": "down"}, request=req)
            return httpx.Response(200, request=req, json={
                "id": "chatcmpl-1", "model": "small-open-model",
                "choices": [{"message": {"content": '{"intent":"warm"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 8}})
        return httpx.Response(200, request=req, json={
            "id": "msg_1", "model": json["model"], "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 30, "output_tokens": 5}})

    monkeypatch.setattr(llm_call.httpx, "post", fake_post)
    import api_usage_logger
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", lambda **row: metered.append(row))
    fake_post.calls, fake_post.metered = calls, metered
    return fake_post


def test_default_route_is_the_claude_lane(monkeypatch):
    for k in ("CHIEF_PROVIDER_BACKGROUND",):
        monkeypatch.delenv(k, raising=False)
    r = lane_registry.route_for("background")
    assert r.is_anthropic and r.model == "claude-haiku-5-5"


def test_a_half_configured_lane_stays_on_claude_and_says_so(monkeypatch, capsys):
    configure(monkeypatch, key_value=None)
    monkeypatch.delenv("SMALL_MODEL_KEY", raising=False)
    r = lane_registry.route_for("background")
    assert r.is_anthropic
    assert "staying on claude-haiku-5-5" in capsys.readouterr().out


def test_unknown_provider_stays_on_claude(monkeypatch, capsys):
    monkeypatch.setenv("CHIEF_PROVIDER_BACKGROUND", "grok-direct")
    assert lane_registry.route_for("background").is_anthropic
    assert "not a known provider" in capsys.readouterr().out


def test_anthropic_lane_posts_exactly_as_before(monkeypatch, wire):
    monkeypatch.delenv("CHIEF_PROVIDER_BACKGROUND", raising=False)
    resp = llm_call.post_lane("background", dict(PORTABLE), task="t")
    assert wire.calls[0]["url"] == llm_call.messages_url()
    assert wire.calls[0]["json"]["model"] == "claude-haiku-5-5"
    assert resp.json()["content"][0]["text"] == "ok"


def test_provider_lane_answers_in_the_anthropic_shape_and_is_metered(monkeypatch, wire):
    configure(monkeypatch)
    resp = llm_call.post_lane("background", dict(PORTABLE), business_id="biz-1")
    call = wire.calls[0]
    assert call["url"] == "https://models.example.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"]["model"] == "small-open-model"
    assert call["json"]["messages"][0] == {"role": "system", "content": "Be brief."}
    assert "thinking" not in call["json"] and "temperature" not in call["json"]
    data = resp.json()
    assert data["content"] == [{"type": "text", "text": '{"intent":"warm"}'}]
    assert data["usage"] == {"input_tokens": 40, "output_tokens": 8}
    assert wire.metered and wire.metered[0]["model"] == "small-open-model"
    assert wire.metered[0]["business_id"] == "biz-1"


def test_provider_failure_falls_back_to_the_claude_model(monkeypatch, wire, capsys):
    configure(monkeypatch)
    wire.fail_provider = True
    resp = llm_call.post_lane("background", dict(PORTABLE))
    assert [c["url"].rsplit("/", 1)[-1] for c in wire.calls] == ["completions", "messages"]
    assert wire.calls[1]["json"]["model"] == "claude-haiku-5-5"
    assert resp.json()["content"][0]["text"] == "ok"
    assert "falling back to claude-haiku-5-5" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [
    {"tools": [{"name": "x"}]},
    {"thinking": {"type": "enabled", "budget_tokens": 1024}},
    {"system": [{"type": "text", "text": "big brief", "cache_control": {"type": "ephemeral"}}]},
    {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
])
def test_anthropic_only_features_never_leave_claude(monkeypatch, wire, extra):
    configure(monkeypatch)
    llm_call.post_lane("background", {**PORTABLE, **extra})
    assert len(wire.calls) == 1 and wire.calls[0]["url"] == llm_call.messages_url()
    assert wire.calls[0]["json"]["model"] == "claude-haiku-5-5"


def test_describe_lists_every_lane(monkeypatch):
    configure(monkeypatch)
    lanes = lane_registry.describe()
    assert lanes["background"]["provider"] == "openai_compatible"
    assert lanes["background"]["fallback"] == "claude-haiku-5-5"
    assert lanes["chat"]["provider"] == "anthropic"


def test_design_intent_goes_through_the_lane(monkeypatch, wire):
    import design_intent
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    configure(monkeypatch)
    wire.calls.clear()
    design_intent.interpret(["cozy", "warm"], "personal_services")
    assert wire.calls[0]["url"].endswith("/chat/completions")
