"""Mission Control → Agents → What they found: findings narrow by agent."""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import platform_console as pc


class _Resp:
    status_code = 200

    def json(self):
        return []


class Fake:
    def __init__(self):
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        if "platform_changelog" in url:
            self.params.append(params)
        return _Resp()


def findings_params(monkeypatch, **kw):
    f = Fake()
    monkeypatch.setattr(pc, "_service_headers", lambda: {})
    monkeypatch.setattr(pc.httpx, "AsyncClient", lambda **k: f)
    asyncio.run(pc.get_agents(_owner=None, **kw))
    return f.params[0]


def test_findings_default_to_every_agent(monkeypatch):
    p = findings_params(monkeypatch)
    assert p["agent"] == "not.is.null" and p["limit"] == "20"


def test_findings_narrow_to_one_agent_and_cap_the_limit(monkeypatch):
    p = findings_params(monkeypatch, agent="money_auditor", limit=500)
    assert p["agent"] == "eq.money_auditor" and p["limit"] == "100"


def test_a_filter_that_is_not_an_agent_name_is_ignored(monkeypatch):
    p = findings_params(monkeypatch, agent="hermes,title.eq.x")
    assert p["agent"] == "not.is.null"
