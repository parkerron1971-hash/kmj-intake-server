"""Hermes logs a standing finding once a day, not every hourly tick."""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import hermes_agent as ha


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeLog:
    def __init__(self, existing=(), read_status=200):
        self.existing, self.read_status, self.posts, self.reads = list(existing), read_status, [], []

    async def get(self, url, headers=None, params=None):
        self.reads.append(params)
        return _Resp([{"id": 1}] if params["title"][3:] in self.existing else [], self.read_status)

    async def post(self, url, headers=None, json=None):
        self.posts.append(json)
        return _Resp(None, 201)


T = "Hermes: 1 customer text unanswered for 4+ hours"


def test_a_finding_already_logged_today_is_not_logged_again():
    c = FakeLog(existing=[T])
    asyncio.run(ha._log_finding(c, {}, T, "detail"))
    assert c.posts == []
    assert c.reads[0]["agent"] == "eq.hermes" and c.reads[0]["created_at"].endswith("Z")


def test_a_new_or_changed_finding_is_logged():
    c = FakeLog(existing=[T])
    asyncio.run(ha._log_finding(c, {}, "Hermes: 2 customer texts unanswered for 4+ hours", "detail"))
    assert len(c.posts) == 1


def test_a_failed_repeat_check_still_logs():
    c = FakeLog(existing=[T], read_status=500)
    asyncio.run(ha._log_finding(c, {}, T, "detail"))
    assert len(c.posts) == 1
