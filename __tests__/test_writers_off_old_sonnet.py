"""
test_writers_off_old_sonnet.py — the writing jobs leave Sonnet 4 and Sonnet 4.5 (2026-10-07).

Sonnet 4 (claude-sonnet-4-20250514) was retired on 2026-06-15: the KMJ
lead qualifier, follow-up emails and Pulse briefing have returned a 404
since. Sonnet 4.5 retires on 2026-11-30. Each job was run on its current
model, Haiku 5.5 and Sonnet 5.5, and graded blind and pairwise by Opus 5.5:

- Haiku 5.5: the briefs (preferred 4/5 over Sonnet 4.5), the nurture
  drafts (3/4), the KMJ lead and follow-up drafts (3/4 over Sonnet 5.5).
  Each had fewer invented details than the model it replaces.
- Sonnet 5.5: growth briefing, drafts and insights, brand kits and
  directions, the intake reply, and Pulse. Haiku won only half of these
  or fewer, or got figures wrong.

Every job keeps an env var that rolls it back without a deploy.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import pathlib
import sys
from types import SimpleNamespace as S
from unittest import mock
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

H55 = "claude-haiku-5-5"
S55 = "claude-sonnet-5-5"
H45 = "claude-haiku-4-5-20251001"

JOBS = {  # module: (attribute, env var, default)
    "notification_engine": ("NOTIF_MODEL", "NOTIF_MODEL", H55),
    "nurture_agent": ("DRAFT_MODEL", "NURTURE_DRAFT_MODEL", H55),
    "growth_engine": ("BRIEFING_MODEL", "GROWTH_BRIEFING_MODEL", S55),
    "brand_engine": ("ANTHROPIC_MODEL", "BRAND_MODEL", S55),
    "intake_endpoint": ("DRAFT_MODEL", "INTAKE_DRAFT_MODEL", S55),
}


def _reload(name, env=None):
    with mock.patch.dict(os.environ, env or {}):
        for _, var, _ in JOBS.values():
            if not env or var not in env:
                os.environ.pop(var, None)
        os.environ.pop("GROWTH_INSIGHTS_MODEL", None)
        return importlib.reload(importlib.import_module(name))


@pytest.mark.parametrize("name", sorted(JOBS))
def test_each_job_defaults_to_its_measured_model(name):
    attr, _, default = JOBS[name]
    assert getattr(_reload(name), attr) == default


def test_growth_insights_default_and_kmj_defaults():
    assert _reload("growth_engine").INSIGHTS_MODEL == S55
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'KMJ_LEAD_MODEL = os.getenv("KMJ_LEAD_MODEL") or "claude-haiku-5-5"' in src
    assert 'PULSE_MODEL = os.getenv("PULSE_MODEL") or "claude-sonnet-5-5"' in src


@pytest.mark.parametrize("name", sorted(JOBS))
def test_each_job_rolls_back_by_env(name):
    attr, var, _ = JOBS[name]
    assert getattr(_reload(name, {var: H45}), attr) == H45
    _reload(name)


def test_no_retired_or_retiring_sonnet_left_in_these_jobs():
    for f in ("notification_engine.py", "nurture_agent.py", "growth_engine.py", "brand_engine.py",
              "intake_endpoint.py", "kmj_intake_automation.py"):
        code = "\n".join(l for l in (ROOT / f).read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        assert "claude-sonnet-4-5" not in code and "claude-sonnet-4-2025" not in code, f
        assert "content[0].text" not in code, f


# ── the request each job sends ─────────────────────────────────────────
def _response(text="Hello", stop="end_turn"):
    r = Mock(status_code=200, text="")
    r.json.return_value = {"stop_reason": stop, "content": [
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": text}]}
    return r


def _expected_thinking(model):
    return {"type": "between_tools"} if "sonnet-5-5" in model else {"type": "disabled"}


def _async_job(monkeypatch, name, model, stop="end_turn"):
    mod = importlib.import_module(name)
    attr, _, _ = JOBS[name]
    monkeypatch.setattr(mod, attr, model)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    api = AsyncMock(return_value=_response(stop=stop))
    monkeypatch.setattr(mod.llm_call, "apost", api)
    if name == "notification_engine":
        out = asyncio.run(mod._call_claude(None, "sys", "user"))
    elif name == "nurture_agent":
        out = asyncio.run(mod._call_claude(None, "sys", "user"))
    elif name == "growth_engine":
        out = asyncio.run(mod._call_claude(None, "sys", "user", model=model))
    else:
        out = asyncio.run(mod.call_claude(None, "sys", "user", model, 100))
    return api.await_args.args[1], out


ASYNC = ["notification_engine", "nurture_agent", "growth_engine", "intake_endpoint"]


@pytest.mark.parametrize("name", ASYNC)
@pytest.mark.parametrize("model", [H55, S55])
def test_payload_on_each_new_model(monkeypatch, name, model):
    payload, out = _async_job(monkeypatch, name, model)
    assert payload["model"] == model
    assert payload["thinking"] == _expected_thinking(model)
    assert "temperature" not in payload
    assert out == "Hello"            # read by block type, never the thinking block


@pytest.mark.parametrize("name", ASYNC)
def test_a_refusal_fails_soft(monkeypatch, name):
    _, out = _async_job(monkeypatch, name, H55, stop="refusal")
    assert out == ""


@pytest.mark.parametrize("name", ASYNC)
def test_haiku_4_5_rollback_gets_no_thinking_field(monkeypatch, name):
    payload, _ = _async_job(monkeypatch, name, H45)
    assert "thinking" not in payload


def test_brand_kit_and_directions_payloads(monkeypatch):
    import brand_engine as be
    monkeypatch.setattr(be, "ANTHROPIC_MODEL", S55)
    monkeypatch.setattr(be, "_anthropic_key", lambda: "fixture")
    sent = []

    def post_with(client, payload=None, **kw):
        sent.append(payload)
        return _response(json.dumps({"tagline": "t", "colors": {}, "font_pair": {}}))
    monkeypatch.setattr(be.llm_call, "post_with", post_with)
    assert be._call_claude_for_kit("sys", "user")["ok"] is True
    monkeypatch.setattr(be, "_brand_context_lines", lambda bid: ["Business name: X"])
    be.generate_directions("b1", {})
    assert [p["model"] for p in sent] == [S55, S55]
    assert all(p["thinking"] == {"type": "between_tools"} and "temperature" not in p for p in sent)


def test_brand_refusal_fails_soft(monkeypatch):
    import brand_engine as be
    monkeypatch.setattr(be, "_anthropic_key", lambda: "fixture")
    monkeypatch.setattr(be.llm_call, "post_with", lambda *a, **k: _response("{}", stop="refusal"))
    assert be._call_claude_for_kit("sys", "user")["ok"] is False
    monkeypatch.setattr(be, "_brand_context_lines", lambda bid: ["Business name: X"])
    assert be.generate_directions("b1", {})["ok"] is False


# ── kmj_intake_automation: the three calls that 404'd since 2026-06-15 ─
def _sdk_response(text, stop="end_turn"):
    return S(stop_reason=stop, content=[S(type="thinking", thinking="", signature="x"),
                                        S(type="text", text=text)])


@pytest.fixture
def kia():
    return importlib.import_module("kmj_intake_automation")


def test_lead_qualifier_and_followups_run_on_haiku_5_5(kia, monkeypatch):
    calls = []

    def create(**kw):
        calls.append(kw)
        return _sdk_response('{"subject": "Hi", "body": "Thanks"}')
    monkeypatch.setattr(kia, "client_messages_create", create)
    assert asyncio.run(kia.auto_qualify_lead({"name": "Ray"}))["subject"] == "Hi"
    assert asyncio.run(kia.generate_followup_email(
        {"clientName": "New Hope", "packageDelivered": "THE CONNECT"}, "Check-in"))["body"] == "Thanks"
    assert [c["model"] for c in calls] == [kia.KMJ_LEAD_MODEL] * 2 == [H55] * 2
    assert all(c["thinking"] == {"type": "disabled"} and "temperature" not in c for c in calls)
    assert calls[0]["max_tokens"] == 2000


def test_a_declined_lead_raises_for_the_callers_existing_catch(kia, monkeypatch):
    monkeypatch.setattr(kia, "client_messages_create", lambda **kw: _sdk_response("", stop="refusal"))
    with pytest.raises(ValueError):
        asyncio.run(kia.auto_qualify_lead({"name": "Ray"}))


def test_pulse_runs_on_sonnet_5_5_with_room_to_finish(kia, monkeypatch):
    import rate_limit
    calls = []

    def create(**kw):
        calls.append(kw)
        return _sdk_response('{"greeting": "Morning"}')
    monkeypatch.setattr(kia, "client_messages_create", create)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    monkeypatch.setattr(rate_limit, "trusted_client_ip", lambda r: "203.0.113.9")

    class Req:
        headers = {}
        client = None
        async def json(self):
            return {"incomeGoal": 7000}
    assert asyncio.run(kia.run_pulse(Req()))["greeting"] == "Morning"
    (kw,) = calls
    assert kw["model"] == kia.PULSE_MODEL == S55
    assert kw["max_tokens"] == 8000
    assert kw["thinking"] == {"type": "between_tools"}
    assert kw["tools"][0]["name"] == "web_search"
