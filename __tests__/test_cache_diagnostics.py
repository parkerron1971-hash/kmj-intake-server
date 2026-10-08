"""
test_cache_diagnostics.py — Chief's main call carries Anthropic's cache diagnostics (2026-10-08).

Sending the previous reply's id as diagnostics.previous_message_id makes the
API name the first divergence when the cache misses (model, system, tools or
messages). Free; hashes only. Only the main call's first round carries it.
"""
from __future__ import annotations

import inspect
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import cache_watch
import chief_of_staff as cos


def setup_function(_):
    cache_watch._last_message.clear()


def test_the_first_main_call_opts_in_with_no_previous_id(monkeypatch):
    monkeypatch.delenv("CACHE_DIAGNOSTICS", raising=False)
    assert cache_watch.diagnostics_field("biz-1", "chief_main") == {"previous_message_id": None}


def test_the_next_call_names_the_previous_reply(monkeypatch):
    monkeypatch.delenv("CACHE_DIAGNOSTICS", raising=False)
    cache_watch.diagnostics_seen("biz-1", "chief_main", "msg_A", None)
    assert cache_watch.diagnostics_field("biz-1", "chief_main") == {"previous_message_id": "msg_A"}
    assert cache_watch.diagnostics_field("biz-2", "chief_main") == {"previous_message_id": None}


def test_only_the_main_call_and_never_when_off(monkeypatch):
    assert cache_watch.diagnostics_field("biz-1", "chief_review") is None
    assert cache_watch.diagnostics_field(None, "chief_main") is None
    monkeypatch.setenv("CACHE_DIAGNOSTICS", "off")
    assert cache_watch.diagnostics_field("biz-1", "chief_main") is None


def test_a_named_miss_is_logged(caplog, monkeypatch):
    monkeypatch.delenv("CACHE_DIAGNOSTICS", raising=False)
    cache_watch.logger.propagate = True
    try:
        with caplog.at_level(logging.INFO, logger="chief.cache_watch"):
            cache_watch.diagnostics_seen("biz-1", "chief_main", "msg_B", {"cache_miss_reason": {
                "type": "tools_changed", "cache_missed_input_tokens": 106000}}, 0, 106000)
    finally:
        cache_watch.logger.propagate = False
    assert "tools_changed" in caplog.text and "106000" in caplog.text
    assert cache_watch._last_message["biz-1"] == "msg_B"


def test_no_divergence_and_pending_log_nothing(caplog, monkeypatch):
    monkeypatch.delenv("CACHE_DIAGNOSTICS", raising=False)
    cache_watch.logger.propagate = True
    try:
        with caplog.at_level(logging.INFO, logger="chief.cache_watch"):
            cache_watch.diagnostics_seen("biz-1", "chief_main", "msg_C", None)
            cache_watch.diagnostics_seen("biz-1", "chief_main", "msg_D", {"cache_miss_reason": None})
    finally:
        cache_watch.logger.propagate = False
    assert "cache diagnostics" not in caplog.text


def test_the_main_call_wires_it_in_on_the_first_round_only():
    src = inspect.getsource(cos._call_claude)
    assert 'payload["diagnostics"] = _diag' in src
    assert src.count('payload.pop("diagnostics", None)') == 2      # stream and non-stream
    assert "diagnostics_seen(" in src
