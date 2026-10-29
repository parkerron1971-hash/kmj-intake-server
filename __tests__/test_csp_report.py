"""Report-Only CSP violations: anonymous intake that only ever logs.

The frontend's Content-Security-Policy-Report-Only header points browsers
at POST /telemetry/csp-report. What matters: a report is cut to safe
fields before it is logged (a page path can carry a classroom or preview
token), repeats do not flood the log, nothing lands in the error ring
buffer the watchdog counts, and no input can make the route answer
anything but 204.
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import platform_watchdog as wd
import rate_limit


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(wd, "_CSP_SEEN", {})
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: True)
    lines = _Lines()
    wd.csp_logger.addHandler(lines)
    app = FastAPI()
    app.include_router(wd.telemetry_router)
    try:
        yield TestClient(app), lines.lines
    finally:
        wd.csp_logger.removeHandler(lines)


def _report(directive="script-src-elem", blocked="https://cdn.tailwindcss.com/3.4?x=1",
            page="https://system.mysolutionist.app/classroom/abc123.sig456?t=1"):
    return json.dumps({"csp-report": {
        "document-uri": page, "effective-directive": directive,
        "violated-directive": directive, "blocked-uri": blocked,
    }})


def _post(c, body, ctype="application/csp-report"):
    return c.post("/telemetry/csp-report", content=body, headers={"Content-Type": ctype})


def test_one_safe_line_per_report_and_no_token(client):
    c, lines = client
    r = _post(c, _report())
    assert r.status_code == 204
    assert lines == ["[csp] script-src-elem blocked=https://cdn.tailwindcss.com page=/classroom seen=1"]
    assert "abc123" not in lines[0] and "?" not in lines[0]


def test_repeats_log_at_one_ten_hundred(client):
    c, lines = client
    for _ in range(100):
        _post(c, _report())
    assert [l.rsplit("seen=", 1)[1] for l in lines] == ["1", "10", "100"]


def test_reporting_api_shape(client):
    c, lines = client
    body = json.dumps([{"type": "csp-violation", "body": {
        "effectiveDirective": "connect-src", "blockedURL": "wss://example.test/socket",
        "documentURL": "https://system.mysolutionist.app/"}}])
    assert _post(c, body, "application/reports+json").status_code == 204
    assert lines == ["[csp] connect-src blocked=wss://example.test page=/ seen=1"]


def test_srcdoc_and_keywords(client):
    c, lines = client
    _post(c, _report("script-src-elem", "inline", "about:srcdoc"))
    _post(c, _report("img-src", "data:image/png;base64,AAAA", "https://system.mysolutionist.app/station"))
    assert lines == [
        "[csp] script-src-elem blocked=inline page=about:srcdoc seen=1",
        "[csp] img-src blocked=data page=/station seen=1",
    ]


def test_hostile_fields_are_cut_to_other(client):
    c, lines = client
    _post(c, _report("script-src\n[csp] forged", "javascript:alert(1)",
                     "https://x.test/%0a[csp]forged/rest"))
    _post(c, _report("img-src", "https://evil.test\n[csp] forged/x", "https://x.test/"))
    assert lines == [
        "[csp] other blocked=other page=/other seen=1",
        "[csp] img-src blocked=other page=/ seen=1",
    ]


@pytest.mark.parametrize("body", [b"", b"not json", b"[1, 2]", b'{"csp-report": "x"}',
                                  b"{" + b" " * 20_000 + b"}"])
def test_garbage_is_204_and_silent(client, body):
    c, lines = client
    assert _post(c, body).status_code == 204
    assert lines == []


def test_over_budget_is_204_and_silent(client, monkeypatch):
    c, lines = client
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: False)
    assert _post(c, _report()).status_code == 204
    assert lines == []


def test_reports_never_enter_the_error_ring_buffer(client):
    c, _ = client
    before = len(wd._ERRORS)
    _post(c, _report())
    assert len(wd._ERRORS) == before


def test_bucket_is_registered():
    assert "csp_report" in rate_limit._LIMITS
