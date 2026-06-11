"""ai_proxy endpoint regression tests (Arc 20B diagnostic fix arc PR1).

The bug class these exist for: PR3 inserted a gate block referencing
business_id before its assignment — UnboundLocalError outside any
try/except → every /ai/proxy request 500'd, and no test executed the
endpoint function end-to-end to catch it. These do.
"""
from __future__ import annotations

import asyncio
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import ai_proxy  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _FakeResp:
    status_code = 200
    text = ""

    def json(self):
        return {
            "model": "claude-sonnet-4-5-20250929",
            "content": [{"type": "text", "text": "hello from fake claude"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


class _FakeClient:
    def __init__(self, *a, **k): ...
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, *a, **k): return _FakeResp()


@pytest.fixture
def proxy_env(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)   # gate disabled
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)
    monkeypatch.setattr(ai_proxy.httpx, "AsyncClient", _FakeClient)
    # api_usage logging is fire-and-best-effort; neutralize network.
    import api_usage_logger
    async def _noop(**k): ...
    monkeypatch.setattr(api_usage_logger, "log_api_usage", _noop)
    monkeypatch.setattr(ai_proxy, "log_api_usage", _noop)
    return fb


def _req(**over):
    base = {"task_type": "draft",
            "messages": [{"role": "user", "content": "hi"}],
            "system": "you are test",
            "metadata": {"business_id": "b1"}}
    base.update(over)
    return ai_proxy.ProxyRequest(**base)


def test_endpoint_runs_end_to_end_with_metadata(proxy_env):
    """THE regression: task_type + metadata present must not raise
    (UnboundLocalError class) and must return a normal response."""
    out = asyncio.run(ai_proxy.ai_proxy(_req()))
    assert out["content"] == "hello from fake claude"
    assert out["usage"]["output_tokens"] == 5


def test_endpoint_runs_without_metadata_and_without_task_type(proxy_env):
    out1 = asyncio.run(ai_proxy.ai_proxy(_req(metadata=None)))
    assert out1["content"] == "hello from fake claude"
    out2 = asyncio.run(ai_proxy.ai_proxy(_req(task_type=None)))
    assert out2["content"] == "hello from fake claude"


def test_gate_exception_fails_open(proxy_env, monkeypatch):
    """A blowing-up gate must never take the endpoint down — Claude path
    proceeds (the fail-open contract)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")        # gate active
    import inference_gate
    def boom(*a, **k):
        raise RuntimeError("gate exploded")
    monkeypatch.setattr(inference_gate, "surface_cacheable", boom)
    out = asyncio.run(ai_proxy.ai_proxy(_req(task_type="score")))
    assert out["content"] == "hello from fake claude"


def test_cache_hit_short_circuits(proxy_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    import inference_gate
    monkeypatch.setattr(inference_gate, "_embed", lambda t: [0.1] * 4)
    # Pre-store, then the same request must come back cached with zero
    # Anthropic involvement signaled via stop_reason.
    first = asyncio.run(ai_proxy.ai_proxy(_req(task_type="score")))
    assert first["stop_reason"] != "cached"
    second = asyncio.run(ai_proxy.ai_proxy(_req(task_type="score")))
    assert second["stop_reason"] == "cached"
    assert second["content"] == "hello from fake claude"
    assert second["usage"]["cache_layer2_hit"] is True
