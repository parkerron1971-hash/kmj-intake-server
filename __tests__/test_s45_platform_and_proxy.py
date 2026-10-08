"""
test_s45_platform_and_proxy.py — the platform Chief, the AI proxy and the intent classifier leave Sonnet 4.5.

Sonnet 4.5 retires 2026-11-30. The platform Chief sent every forced
creation turn (and every turn Sonnet 5.5 declined) to it, because Sonnet
5.5 rejects a forced tool_choice; that fallback is now Sonnet 5, which takes
one. The proxy's Sonnet tiers move to Sonnet 5.5, a client that names a
retiring model gets its current equivalent, thinking is off for every model
that can turn it off, and the app's budgets grow with the token count.
"""
from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import model_ladder


def test_platform_fallback_takes_a_forced_tool_and_is_not_retiring(monkeypatch):
    monkeypatch.delenv("PLATFORM_CHIEF_FALLBACK_MODEL", raising=False)
    import platform_console
    pc = importlib.reload(platform_console)
    assert pc.PLATFORM_CHIEF_FALLBACK_MODEL == "claude-sonnet-5"
    assert model_ladder.supports_forced_tool_choice(pc.PLATFORM_CHIEF_FALLBACK_MODEL)
    payload = pc._platform_chief_payload(pc.PLATFORM_CHIEF_FALLBACK_MODEL, "sys", [], [], True)
    assert payload["tool_choice"]["type"] == "any"
    assert "temperature" not in payload and payload["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("task", ["plan", "score", "draft", "briefing"])
def test_proxy_sonnet_tiers_are_sonnet_5_5(monkeypatch, task):
    import ai_proxy
    for k in ("AI_PROXY_PLAN_MODEL", "AI_PROXY_SCORE_MODEL", "AI_PROXY_DRAFT_MODEL",
              "AI_PROXY_BRIEFING_MODEL", "AI_PROXY_DEFAULT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    p = importlib.reload(ai_proxy)
    assert p.TASK_MODEL_MAP[task] == "claude-sonnet-5-5"
    assert p.DEFAULT_MODEL == "claude-sonnet-5-5"
    assert "sonnet-4" not in " ".join(p._ALLOWED_OVERRIDE_MODELS)
    assert "haiku-4" not in " ".join(p._ALLOWED_OVERRIDE_MODELS)


def test_proxy_tier_rolls_back_by_env(monkeypatch):
    import ai_proxy
    monkeypatch.setenv("AI_PROXY_DRAFT_MODEL", "claude-sonnet-5")
    p = importlib.reload(ai_proxy)
    assert p.TASK_MODEL_MAP["draft"] == "claude-sonnet-5"
    monkeypatch.delenv("AI_PROXY_DRAFT_MODEL")
    importlib.reload(ai_proxy)


@pytest.mark.parametrize("asked,got", [
    ("claude-sonnet-4-5-20250929", "claude-sonnet-5-5"),
    ("claude-sonnet-4-5", "claude-sonnet-5-5"),
    ("claude-sonnet-4-20250514", "claude-sonnet-5-5"),
    ("claude-haiku-4-5-20251001", "claude-haiku-5-5"),
    ("claude-haiku-4-5", "claude-haiku-5-5"),
    ("claude-haiku-5-5", "claude-haiku-5-5"),
])
def test_a_retiring_model_named_by_the_app_maps_to_its_current_equivalent(asked, got):
    import ai_proxy
    assert ai_proxy._select_model("draft", asked) == got


def test_an_unknown_override_still_falls_back_to_the_tier():
    import ai_proxy
    assert ai_proxy._select_model("draft", "claude-fable-5") == ai_proxy.TASK_MODEL_MAP["draft"]


def test_proxy_payload_turns_thinking_off_and_drops_temperature(monkeypatch):
    """The payload builder is inline in the route; its pieces are checked
    through the same helpers it calls."""
    src = pathlib.Path(importlib.import_module("ai_proxy").__file__).read_text(encoding="utf-8")
    assert "anthropic_payload.update(model_ladder.thinking_off_kwargs(model))" in src
    assert "int((req.max_tokens or DEFAULT_MAX_TOKENS) * 1.3), MAX_PROXY_TOKENS)" in src
    assert model_ladder.thinking_off_kwargs("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}}
    assert model_ladder.thinking_off_kwargs("claude-haiku-5-5") == {"thinking": {"type": "disabled"}}
    assert model_ladder.thinking_off_kwargs("claude-opus-4-8") == {}
    assert model_ladder.sampling_kwargs("claude-sonnet-5-5", 1.0) == {}


class _Msg:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.stop_reason = "end_turn"


def test_intent_classifier_is_haiku_5_5_with_thinking_off_and_no_temperature(monkeypatch):
    monkeypatch.delenv("INTENT_CLASSIFIER_MODEL", raising=False)
    import agents.chief_executive.intent_classifier as ic
    ic = importlib.reload(ic)
    calls = []

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return _Msg('{"intent": "scheduling", "confidence": 0.9, "parameters": {}}')
    monkeypatch.setattr(ic.llm_call, "sdk_client", lambda key=None: Client())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    out = ic.classify_intent("move my 3pm to Friday")
    kw = calls[0]
    assert kw["model"] == "claude-haiku-5-5" and "temperature" not in kw and "thinking" not in kw
    assert kw["extra_body"] == {"thinking": {"type": "disabled"}}
    assert out.get("intent") == "scheduling"


def test_intent_classifier_rolls_back_to_sonnet_with_its_own_thinking_setting(monkeypatch):
    monkeypatch.setenv("INTENT_CLASSIFIER_MODEL", "claude-sonnet-5-5")
    import agents.chief_executive.intent_classifier as ic
    ic = importlib.reload(ic)
    assert ic.CLASSIFIER_MODEL == "claude-sonnet-5-5"
    monkeypatch.delenv("INTENT_CLASSIFIER_MODEL")
    importlib.reload(ic)
