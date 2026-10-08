"""
test_s45_business_agents.py — the business agents and document tools leave Sonnet 4.5 (retires 2026-11-30).

Sonnet 5.5 differs in ways that fail quietly: it thinks by default (a
300-800 token draft budget is spent before any text), counts the same text
as ~30% more tokens, can decline with stop_reason "refusal", and the
pinned SDK (0.34.2) predates the `thinking` keyword. Every call here turns
thinking off, gets more room, reads text by block type, and fails soft on a
refusal. Each model keeps an env override for rollback.
"""
from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

S55 = "claude-sonnet-5-5"


def _resp(text="Hello there.", stop="end_turn"):
    r = Mock(status_code=200, text="")
    r.json.return_value = {"stop_reason": stop, "model": S55, "usage": {},
                           "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                       {"type": "text", "text": text}]}
    return r


AGENTS = [("session_agent", "DRAFT_MODEL", "SESSION_AGENT_DRAFT_MODEL"),
          ("session_agent", "PLAN_MODEL", "SESSION_AGENT_PLAN_MODEL"),
          ("payment_agent", "DRAFT_MODEL", "PAYMENT_AGENT_MODEL"),
          ("contract_agent", "DRAFT_MODEL", "CONTRACT_AGENT_MODEL"),
          ("module_agent", "DRAFT_MODEL", "MODULE_AGENT_MODEL"),
          ("foundation_agent", "ANTHROPIC_MODEL", "FOUNDATION_MODEL")]


@pytest.mark.parametrize("mod,attr,env", AGENTS)
def test_default_is_sonnet_5_5_and_env_rolls_back(monkeypatch, mod, attr, env):
    monkeypatch.delenv(env, raising=False)
    m = importlib.reload(importlib.import_module(mod))
    assert getattr(m, attr) == S55
    monkeypatch.setenv(env, "claude-sonnet-4-5-20250929")
    m = importlib.reload(m)
    assert getattr(m, attr) == "claude-sonnet-4-5-20250929"
    monkeypatch.delenv(env)
    importlib.reload(m)


@pytest.mark.parametrize("mod", ["session_agent", "payment_agent", "contract_agent", "module_agent"])
def test_agent_call_turns_thinking_off_and_reads_text_blocks(monkeypatch, mod):
    m = importlib.import_module(mod)
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _resp("Draft body.")
    monkeypatch.setattr(m.llm_call, "apost", apost)
    monkeypatch.setattr(m, "_anthropic_key", lambda: "k")
    out = asyncio.run(m._call_claude(None, "sys", "user", max_tokens=400))
    assert out == "Draft body."
    assert sent["thinking"] == {"type": "between_tools"}
    assert "temperature" not in sent and "tool_choice" not in sent
    assert sent["max_tokens"] == 520


@pytest.mark.parametrize("mod", ["session_agent", "payment_agent", "contract_agent", "module_agent"])
def test_agent_refusal_falls_back_to_the_plain_draft(monkeypatch, mod):
    m = importlib.import_module(mod)

    async def apost(client, payload, **kw):
        return _resp("", stop="refusal")
    monkeypatch.setattr(m.llm_call, "apost", apost)
    monkeypatch.setattr(m, "_anthropic_key", lambda: "k")
    assert asyncio.run(m._call_claude(None, "sys", "user")) == ""


class _Msg:
    def __init__(self, text, stop="end_turn"):
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.stop_reason = stop


def _fake_sdk(monkeypatch, fa, msg):
    calls = []

    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return msg
    monkeypatch.setattr(fa.llm_call, "sdk_client", lambda key=None: Client())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    return calls


def test_foundation_sdk_call_sends_thinking_off_through_extra_body(monkeypatch):
    import foundation_agent as fa
    calls = _fake_sdk(monkeypatch, fa, _Msg('{"recommended": "LLC"}'))

    async def nothing(*a, **k):
        return [{"id": "d1"}]
    monkeypatch.setattr(fa, "_sb_post", nothing)
    monkeypatch.setattr(fa, "update_phase", nothing)
    asyncio.run(fa.recommend_entity("biz", {"state": "OH"}))
    kw = calls[0]
    assert kw["model"] == S55 and "thinking" not in kw and "temperature" not in kw
    assert kw["extra_body"] == {"thinking": {"type": "between_tools"}}


def test_foundation_refusal_is_not_saved_as_an_empty_document(monkeypatch):
    import foundation_agent as fa
    _fake_sdk(monkeypatch, fa, _Msg("", stop="refusal"))
    saved = []

    async def post(*a, **k):
        saved.append(a)
        return [{"id": "d1"}]
    monkeypatch.setattr(fa, "_sb_post", post)
    out = asyncio.run(fa.recommend_entity("biz", {"state": "OH"}))
    assert out["ok"] is False and saved == []


def test_doc_intelligence_default_payload_and_refusal(monkeypatch):
    import doc_intelligence_router as di
    from fastapi import HTTPException
    monkeypatch.delenv("DOCINTEL_MODEL", raising=False)
    monkeypatch.setattr(di.llm_call, "api_key", lambda: "k")
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _resp("", stop="refusal")
    monkeypatch.setattr(di.llm_call, "apost", apost)
    with pytest.raises(HTTPException) as e:
        asyncio.run(di._call_claude("sys", [{"type": "text", "text": "doc"}], business_id="b",
                                    user_id="u", task_type="summary"))
    assert e.value.status_code == 422
    assert sent["model"] == S55 and sent["thinking"] == {"type": "between_tools"}
    assert sent["max_tokens"] == 2600 and di.MODE_MAX_TOKENS["grant_requirements"] == 10400


def test_doc_templates_learn_model_and_budgets(monkeypatch):
    import doc_templates_router as dt
    monkeypatch.delenv("DOCTEMPLATES_LEARN_MODEL", raising=False)
    assert dt._learn_model() == S55
    assert dt._draft_budget(1) == 1600 and dt._draft_budget(99) == 5200
    src = pathlib.Path(dt.__file__).read_text(encoding="utf-8")
    # Every payload in the module turns thinking off for its model.
    assert src.count("**model_ladder.thinking_off_kwargs(") == 4
    assert "claude-sonnet-4-5" not in src
