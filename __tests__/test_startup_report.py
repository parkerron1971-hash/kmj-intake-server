"""The startup screen's own report: anonymous intake that only ever logs.

The frontend's startup screen (public/startup.js) runs before the app's
code and before any sign-in. When the app does not open it retries once
and posts what happened to POST /telemetry/startup with sendBeacon. What
matters: every field is cut to an allowlist before it is logged (a page
path can carry a classroom token, an error message can carry a URL with a
query string), nothing lands in the error ring buffer the watchdog counts,
and no input can make the route answer anything but 204.
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

IOS_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/27.0.1 Mobile/15E148 Safari/604.1")


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: True)
    lines = _Lines()
    wd.startup_logger.addHandler(lines)
    app = FastAPI()
    app.include_router(wd.telemetry_router)
    try:
        yield TestClient(app), lines.lines
    finally:
        wd.startup_logger.removeHandler(lines)


def _post(c, body):
    # sendBeacon with a string body goes out as text/plain (no preflight).
    raw = body if isinstance(body, (str, bytes)) else json.dumps(body)
    return c.post("/telemetry/startup", content=raw, headers={"Content-Type": "text/plain;charset=UTF-8"})


def _report(**over):
    body = {"stage": "retry", "boot": "none", "secs": 12.4, "standalone": True,
            "page": "/", "ua": IOS_SAFARI, "errors": []}
    body.update(over)
    return body


def test_one_line_with_the_phone_named(client):
    c, lines = client
    r = _post(c, _report())
    assert r.status_code == 204
    assert lines == ["[startup] retry boot=none secs=12 app=1 page=/ ua=iOS 18.7 Safari 27.0"]


def test_failed_with_errors_cuts_urls_and_tokens(client):
    c, lines = client
    _post(c, _report(
        stage="failed", boot="entry", secs=21, page="/classroom/abc123.sig456?t=secret",
        errors=[
            "script: https://system.mysolutionist.app/assets/main-B1gLPbNx.js?token=secret",
            "TypeError: Importing a module script failed.\nat line 2",
        ],
    ))
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("[startup] failed boot=entry secs=21 app=1 page=/classroom ")
    assert "system.mysolutionist.app/main-B1gLPbNx.js" in line
    assert "TypeError: Importing a module script failed. at line 2" in line
    for leaked in ("abc123", "secret", "?", "\n"):
        assert leaked not in line


def test_recovered_and_other_browsers(client):
    c, lines = client
    _post(c, _report(stage="recovered", boot="main", standalone=False,
                     ua="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"))
    _post(c, _report(ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1"))
    assert lines[0] == "[startup] recovered boot=main secs=12 app=0 page=/ ua=Android 14 Chrome 131"
    assert lines[1].endswith("ua=iOS 17.5 Chrome 131")


def test_unknown_fields_are_cut_to_the_allowlist(client):
    c, lines = client
    _post(c, _report(boot="<script>", secs="lots", standalone="yes", page="/Évil path",
                     errors=["x" * 900, {"nested": 1}, "ok", "fourth is dropped"]))
    line = lines[0]
    assert " boot=other secs=0 app=0 page=/other " in line
    assert "fourth" not in line and "<" not in line and "nested" not in line
    assert max(len(e) for e in line.split("errors=", 1)[1].split(" | ")) <= 140


def test_a_report_never_reaches_the_ring_buffer(client):
    c, _ = client
    before = len(wd.recent_errors(400))
    _post(c, _report(stage="failed", errors=["boom"]))
    assert len(wd.recent_errors(400)) == before


@pytest.mark.parametrize("body", [
    "", "not json", "null", "[]", json.dumps({"stage": "launch"}), json.dumps({"stage": None}),
    "x" * 5000,
])
def test_junk_is_always_204_and_silent(client, body):
    c, lines = client
    assert _post(c, body).status_code == 204
    assert lines == []


def test_over_the_budget_is_not_logged(client, monkeypatch):
    c, lines = client
    seen = []
    monkeypatch.setattr(rate_limit, "allow", lambda bucket, key: seen.append(bucket) or False)
    assert _post(c, _report()).status_code == 204
    assert lines == [] and seen == ["startup_report"]


def test_the_bucket_exists():
    assert rate_limit._LIMITS["startup_report"][1] == 3600
