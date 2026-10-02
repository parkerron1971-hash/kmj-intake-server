"""
test_chief_review_shape_enforced.py — the answer check's reply is always well-formed JSON (2026-09-24).

Told in prose to "Return ONLY JSON", the reviewer (thinking off) wrote
`{"verdict":"supported","claims":[[]][0] || null,"claims":[...` on 3 of 8
reviews of one real answer. Each read as "review is not JSON" and the draft
went out unchecked, or was withheld when it claimed an action. The API now
enforces the shape; with it the same answer came back well-formed 6 of 6.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff  # noqa: F401  (chief_truth imports it lazily)
import chief_truth as truth


class _Resp:
    status_code = 200

    def json(self):
        return {"content": [{"type": "text", "text": '{"verdict":"supported","claims":[]}'}]}


def _send(monkeypatch, fn, model="claude-sonnet-5", system=None):
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
    asyncio.run(fn(None, system or truth.REVIEW_SYSTEM, [{"role": "user", "content": "{}"}], max_tokens=100))
    return sent


def test_the_review_asks_for_its_shape(monkeypatch):
    monkeypatch.delenv("CHIEF_REVIEW_SCHEMA", raising=False)
    sent = _send(monkeypatch, truth.review_reply)
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": truth.REVIEW_SCHEMA}


def test_the_prose_repair_does_not(monkeypatch):
    monkeypatch.delenv("CHIEF_REVIEW_SCHEMA", raising=False)
    sent = _send(monkeypatch, truth.repair_reply, system=truth.REPAIR_SYSTEM)
    assert "format" not in (sent.get("output_config") or {})


def test_the_switch_drops_it(monkeypatch):
    monkeypatch.setenv("CHIEF_REVIEW_SCHEMA", "off")
    assert "output_config" not in _send(monkeypatch, truth.review_reply)


def test_low_effort_and_the_shape_ride_together(monkeypatch):
    # Opus 5.5 rejects disabled thinking and keeps low effort instead.
    monkeypatch.delenv("CHIEF_REVIEW_SCHEMA", raising=False)
    monkeypatch.delenv("CHIEF_REVIEW_THINKING", raising=False)
    sent = _send(monkeypatch, truth.review_reply, model="claude-opus-5-5")
    assert sent["output_config"]["effort"] == "low" and "format" in sent["output_config"]


def _walk(node):
    yield node
    for v in (node.get("properties") or {}).values():
        yield from _walk(v)
    if isinstance(node.get("items"), dict):
        yield from _walk(node["items"])


def test_the_schema_matches_what_assess_review_accepts():
    # Every object closed (the API requires it), and every well-formed
    # reply the schema allows is one assess_review can read.
    for node in _walk(truth.REVIEW_SCHEMA):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
    claim = truth.REVIEW_SCHEMA["properties"]["claims"]["items"]
    assert set(claim["properties"]) == {"text", "kind", "source_id", "quote", "gap"}
    assert set(claim["required"]) == {"text", "kind", "source_id", "quote"}
    draft = "You have 2 open invoices."
    sources = {"context:invoice_summary": {"kind": "context", "text": "2 open invoices", "complete": True}}
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": "2 open invoices", "kind": "fact", "source_id": "context:invoice_summary",
         "quote": "2 open invoices"}]})
    assert truth.assess_review(raw, draft, sources)[0] == "supported"


@pytest.mark.parametrize("bad", [
    '{"verdict":"supported","claims":[[]][0] || null,"claims":[]}',
])
def test_the_malformed_reply_it_prevents_still_reads_as_invalid(bad):
    # Kept as the record of why: without the schema this is what came back.
    assert truth.assess_review(bad, "Five invoices.", {})[0] == "invalid"
