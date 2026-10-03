"""The vision judge on a model that thinks (2026-10-03).

Kevin moved the judge to Sonnet 5.5. It thinks adaptively at HIGH unless
told otherwise, and the thinking counts against max_tokens, so every call
that reads VISION_JUDGE_MODEL (the grader, the site check, the canvas
self-review) now sends a bounded effort and has room for its answer. An
empty answer is the dangerous one: each caller reads it as "nothing
wrong".
"""
import json
from types import SimpleNamespace
from unittest import mock

import vision_grader as vg


def _fake_client(sent, text):
    class _Msgs:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(model=kw["model"],
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                                   content=[SimpleNamespace(type="text", text=text)])
    return SimpleNamespace(messages=_Msgs())


def test_the_judge_effort_reads_its_dial(monkeypatch):
    monkeypatch.delenv("VISION_JUDGE_EFFORT", raising=False)
    assert vg.judge_effort() == "medium"
    monkeypatch.setenv("VISION_JUDGE_EFFORT", " LOW ")
    assert vg.judge_effort() == "low"
    monkeypatch.setenv("VISION_JUDGE_EFFORT", "max")
    assert vg.judge_effort() == "medium"


def test_only_a_model_that_takes_effort_gets_it(monkeypatch):
    monkeypatch.delenv("VISION_JUDGE_EFFORT", raising=False)
    # an SDK call: the effort rides extra_body (see test_sdk_effort_contract)
    assert vg.judge_kwargs("claude-sonnet-5-5") == {"extra_body": {"output_config": {"effort": "medium"}}}
    # Sonnet 4.5 400s on the field, so the old default judge gets nothing
    assert vg.judge_kwargs("claude-sonnet-4-5-20250929") == {}


def test_the_grader_bounds_a_thinking_judge(monkeypatch):
    sent = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("VISION_JUDGE_MODEL", "claude-sonnet-5-5")
    monkeypatch.delenv("VISION_JUDGE_EFFORT", raising=False)
    monkeypatch.setattr(vg.llm_call, "sdk_client",
                        lambda key=None: _fake_client(sent, json.dumps({"balance": 9})))
    with mock.patch.object(vg, "_meter"):
        vg._grade_anthropic([b"a", b"b", b"c"], "biz-1", None, [])
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["extra_body"]["output_config"] == {"effort": "medium"}
    assert sent["max_tokens"] >= 2000


def test_the_grader_on_the_old_default_sends_no_effort(monkeypatch):
    sent = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("VISION_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(vg.llm_call, "sdk_client",
                        lambda key=None: _fake_client(sent, json.dumps({"balance": 9})))
    with mock.patch.object(vg, "_meter"):
        vg._grade_anthropic([b"a", b"b", b"c"], "biz-1", None, [])
    assert "output_config" not in sent and "extra_body" not in sent


def test_the_site_check_vision_pass_bounds_a_thinking_judge(monkeypatch):
    import site_check
    sent = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("VISION_JUDGE_MODEL", "claude-sonnet-5-5")
    monkeypatch.delenv("VISION_JUDGE_EFFORT", raising=False)
    monkeypatch.delenv("VISION_GRADER", raising=False)
    monkeypatch.setattr(vg.llm_call, "sdk_client",
                        lambda key=None: _fake_client(sent, '{"findings": []}'))
    with mock.patch.object(vg, "_meter"):
        site_check.vision_findings({"url": "https://x.example/", "shots": {390: b"a"}}, "biz-1")
    assert sent["extra_body"]["output_config"] == {"effort": "medium"}
    assert sent["max_tokens"] >= 2000


def test_the_canvas_self_review_bounds_a_thinking_judge(monkeypatch):
    import api_usage_logger
    import canvas
    sent = {}
    monkeypatch.setattr(api_usage_logger, "log_api_usage_sync", lambda **kw: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("CANVAS_REVIEW_MODEL", raising=False)
    monkeypatch.setenv("VISION_JUDGE_MODEL", "claude-sonnet-5-5")
    monkeypatch.delenv("VISION_JUDGE_EFFORT", raising=False)
    monkeypatch.setattr(vg, "_screenshot", lambda html: [b"a", b"b", b"c"])
    monkeypatch.setattr(vg.llm_call, "sdk_client",
                        lambda key=None: _fake_client(sent, "SHIP"))
    assert canvas._self_review("<html></html>", "brief", "biz-1") is None
    assert sent["extra_body"]["output_config"] == {"effort": "medium"}
    assert sent["max_tokens"] >= 1500
