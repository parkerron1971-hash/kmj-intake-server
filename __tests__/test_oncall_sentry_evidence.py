"""On-call's Sentry evidence: readable without a token, useful with one.

The 2026-10-01 incident #1137 was diagnosed as an expired login. Sentry
had the real cause in the breadcrumbs (a 400 for a missing column), so
the evidence file now carries the latest event's message, exception and
breadcrumbs.
"""
from __future__ import annotations

import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "oncall_sentry_evidence",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "oncall_sentry_evidence.py")
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)


def test_without_a_token_it_says_so_and_exits_cleanly(monkeypatch, capsys):
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    assert ev.main() == 0
    assert "SENTRY_AUTH_TOKEN secret is not set" in capsys.readouterr().out


def test_issues_and_the_latest_event_are_printed(monkeypatch, capsys):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "t")
    issue = {"id": "77", "shortId": "PYTHON-FASTAPI-2", "count": "43",
             "lastSeen": "2026-10-01T08:00:00Z", "title": "sb_clients async GET /agent_queue",
             "culprit": "", "permalink": "https://example/77", "project": {"slug": "python-fastapi"}}
    event = {"message": "sb_clients async GET /agent_queue: 400",
             "entries": [{"type": "breadcrumbs", "data": {"values": [
                 {"level": "warning", "category": "httplib",
                  "data": {"http.response.status_code": 400, "url": "https://x/rest/v1/agent_queue"}},
                 {"level": "error", "category": "sb_clients",
                  "message": '400 {"code":"42703","message":"column agent_queue.data does not exist"}'},
             ]}}]}

    def fake_get(token, path):
        return [issue] if path.startswith("/issues/?") else event

    monkeypatch.setattr(ev, "_get", fake_get)
    assert ev.main() == 0
    out = capsys.readouterr().out
    assert "PYTHON-FASTAPI-2" in out and "×43" in out
    assert "HTTP 400" in out
    assert "column agent_queue.data does not exist" in out


def test_no_unresolved_errors(monkeypatch, capsys):
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "t")
    monkeypatch.setattr(ev, "_get", lambda token, path: [])
    assert ev.main() == 0
    assert "No unresolved errors" in capsys.readouterr().out
