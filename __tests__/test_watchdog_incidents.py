"""The watchdog files real failures for on-call, and only real failures.

An `incident` issue starts .github/workflows/oncall.yml, which spends a
Claude run investigating. So what gets filed matters as much as whether
filing works: configuration gaps must not page, a recurring failure must
comment on the open incident rather than open a new one, and no token
means nothing happens.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import platform_watchdog as wd


class _Resp:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class _FakeGitHub:
    def __init__(self, open_issues=None):
        self.open_issues = open_issues or []
        self.posts = []

    async def get(self, url, headers=None, params=None):
        assert params["labels"] == "incident"
        return _Resp(200, self.open_issues)

    async def post(self, url, headers=None, json=None):
        self.posts.append((url, json))
        return _Resp(201, {"html_url": "https://github.com/x/y/issues/9"})


DB_DOWN = {"severity": "critical", "code": "db:reach", "message": "database unreachable: timeout"}
KEY_MISSING = {"severity": "critical", "code": "svc:meta_ads", "message": "Meta Ads is missing env keys"}


def test_config_gaps_do_not_page_on_call():
    assert wd._incident_findings([KEY_MISSING, DB_DOWN]) == [DB_DOWN]
    assert wd._incident_findings([KEY_MISSING]) == []


def test_new_failure_opens_a_labelled_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    gh = _FakeGitHub()
    url = asyncio.run(wd._file_incident(gh, [DB_DOWN]))
    assert url.endswith("/issues/9")
    [(target, payload)] = gh.posts
    assert target.endswith("/kmj-intake-server/issues")
    assert payload["labels"] == ["incident"]
    assert payload["title"].startswith("Watchdog:")
    assert "db:reach" in payload["body"]


def test_recurring_failure_comments_instead_of_reopening(monkeypatch):
    """Only `opened` starts on-call, so a comment does not re-investigate."""
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    gh = _FakeGitHub(open_issues=[
        {"number": 3, "title": "Uptime: production is not answering", "html_url": "u3"},
        {"number": 7, "title": "Watchdog: database unreachable", "html_url": "u7"},
    ])
    url = asyncio.run(wd._file_incident(gh, [DB_DOWN]))
    assert url == "u7"
    [(target, payload)] = gh.posts
    assert target.endswith("/issues/7/comments")
    assert "Still failing" in payload["body"]


def test_no_token_files_nothing(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    gh = _FakeGitHub()
    assert asyncio.run(wd._file_incident(gh, [DB_DOWN])) is None
    assert gh.posts == []
