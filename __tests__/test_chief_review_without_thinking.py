"""
test_chief_review_without_thinking.py — the answer check runs without thinking (2026-09-24).

Benchmarked on three real answers against KMJ's records (twice each):
Sonnet 5 with thinking off averaged 8.4 s vs 10.3 s at low effort, with
the same verdict on all six; the live factual eval passed 12/12. Haiku 4.5
was not faster and returned unusable reviews. CHIEF_REVIEW_THINKING=low
restores the old setting; models that reject disabled thinking keep it.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


class _Resp:
    status_code = 200

    def json(self):
        return {"content": [{"type": "text", "text": '{"verdict":"supported","claims":[]}'}]}


def _capture(monkeypatch, model):
    import chief_models
    import llm_call
    import spend_guard
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None: model)
    asyncio.run(truth.review_reply(None, "sys", [{"role": "user", "content": "x"}], max_tokens=100))
    return sent


def test_sonnet_reviews_with_thinking_disabled(monkeypatch):
    monkeypatch.delenv("CHIEF_REVIEW_THINKING", raising=False)
    sent = _capture(monkeypatch, "claude-sonnet-5")
    # No effort with thinking disabled. (output_config also carries the
    # review's enforced JSON shape since 2026-09-24.)
    assert sent["thinking"] == {"type": "disabled"} and "effort" not in sent.get("output_config", {})


def test_the_switch_restores_low_effort(monkeypatch):
    monkeypatch.setenv("CHIEF_REVIEW_THINKING", "low")
    sent = _capture(monkeypatch, "claude-sonnet-5")
    assert "thinking" not in sent and sent["output_config"]["effort"] == "low"


def test_a_model_that_rejects_disabled_thinking_keeps_low_effort(monkeypatch):
    monkeypatch.delenv("CHIEF_REVIEW_THINKING", raising=False)
    sent = _capture(monkeypatch, "claude-opus-5-5")
    assert "thinking" not in sent
