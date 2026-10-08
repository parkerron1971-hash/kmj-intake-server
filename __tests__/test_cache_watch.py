"""
test_cache_watch.py — name the cached prompt part that moved between turns (2026-09-24).

After the cache fixes the usage log still showed Chief's state segment and
the answer check's records re-written on every message, while an offline
rebuild of the same inputs was byte-identical. The watch logs which part
changed since the business's last call, by static heading, without logging
the business's data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import cache_watch


def _fresh():
    cache_watch._seen.clear()


def _capture(caplog):
    # The watch logger does not propagate to root (root stays at WARNING).
    cache_watch.logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="chief.cache_watch")


def test_the_first_call_has_nothing_to_compare():
    _fresh()
    assert cache_watch.note("k", "biz", {"a": "1"}) == []


def test_it_names_the_part_that_moved_and_how(caplog):
    _fresh()
    state = "DATA QUALITY: {\"retrieved_on\": \"2026-09-24\"}\n\nUPCOMING SESSIONS (next 7 days):\n  (none)"
    cache_watch.note("chief_prompt", "biz-1", cache_watch.paragraphs(state))
    later = state.replace("2026-09-24", "2026-09-25")
    _capture(caplog)
    changed = cache_watch.note("chief_prompt", "biz-1", cache_watch.paragraphs(later))
    assert len(changed) == 1 and changed[0].startswith("00 DATA QUALITY")
    line = caplog.records[-1].getMessage()
    assert "digits only" in line and "1 of 3 parts changed" in line


def test_the_log_carries_headings_not_data(caplog):
    _fresh()
    cache_watch.note("review_records", "biz-2", {"context:open_invoices": '[{"client": "Monica Walton", "total": 150}]'})
    _capture(caplog)
    cache_watch.note("review_records", "biz-2", {"context:open_invoices": '[{"client": "Monica Walton", "total": 175}]'})
    line = caplog.records[-1].getMessage()
    assert "context:open_invoices" in line
    assert "Monica" not in line and "175" not in line


def test_businesses_are_kept_apart_and_bounded():
    _fresh()
    cache_watch.note("k", "a", {"x": "1"})
    assert cache_watch.note("k", "b", {"x": "2"}) == []
    for i in range(cache_watch._MAX_BUSINESSES + 20):
        cache_watch.note("k", f"biz{i}", {"x": "1"})
    assert len(cache_watch._seen) == cache_watch._MAX_BUSINESSES


class _Resp:
    status_code = 200

    def __init__(self):
        self.text = ""

    def json(self):
        return {"stop_reason": "end_turn", "usage": {}, "content": [{"type": "text", "text": "ok"}]}


def test_chiefs_main_turn_is_watched(monkeypatch):
    import chief_of_staff as cos
    import llm_call
    _fresh()
    seen = []
    monkeypatch.setattr(cache_watch, "note", lambda kind, biz, parts: seen.append((kind, biz, sorted(parts)[:2])) or [])

    async def apost(client, payload, **kw):
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    system = ("U " * 600 + "[[CHIEF_GLOBAL_SPLIT]]" + "M " * 900 + "[[CHIEF_CACHE_SPLIT]]"
              + "STATE A\n\nSTATE B " * 300 + "[[CHIEF_TURN_SPLIT]]" + "TURN")
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                 business_id="biz-9", stable_tools=True))
    assert seen and seen[0][0] == "chief_prompt" and seen[0][1] == "biz-9"


def test_the_review_is_watched_and_the_repair_is_not(monkeypatch):
    import chief_models
    import chief_truth as truth
    import llm_call
    import spend_guard
    seen = []
    monkeypatch.setattr(cache_watch, "note", lambda kind, biz, parts: seen.append((kind, sorted(parts))) or [])

    class R:
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": '{"verdict":"supported","claims":[]}'}]}

    async def apost(client, payload, **kw):
        return R()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None: "claude-sonnet-5")
    doc = {"owner_message": "q", "draft": "d", "unavailable": [],
           "sources": {"context:offerings": {"text": "x"}, "context:current_view": {"text": "home"},
                       "conversation:current": {"text": "q"}}}
    msgs = [{"role": "user", "content": json.dumps(doc)}]
    asyncio.run(truth.review_reply(None, truth.REVIEW_SYSTEM, msgs, max_tokens=100, business_id="biz"))
    assert seen == [("review_records", ["context:offerings"])]
    asyncio.run(truth.repair_reply(None, truth.REPAIR_SYSTEM, msgs, max_tokens=100, business_id="biz"))
    assert len(seen) == 1


def test_the_same_records_in_another_order_count_as_a_change():
    _fresh()
    cache_watch.note("review_records", "b", {"context:a": "1", "context:b": "2"})
    assert cache_watch.note("review_records", "b", {"context:b": "2", "context:a": "1"}) == ["(order)"]


def test_nothing_changed_is_said_too(caplog):
    _fresh()
    cache_watch.note("k", "b", {"x": "1"})
    _capture(caplog)
    assert cache_watch.note("k", "b", {"x": "1"}) == []
    assert "nothing changed" in caplog.records[-1].getMessage()


def test_the_watch_logs_at_info_on_its_own_handler():
    import logging as _l
    assert cache_watch.logger.handlers and cache_watch.logger.getEffectiveLevel() == _l.INFO


def test_the_main_turn_falls_back_to_the_business_it_serves(monkeypatch):
    # The main Chief call passes tool_biz, not business_id.
    import chief_of_staff as cos
    import llm_call
    seen = []
    monkeypatch.setattr(cache_watch, "note", lambda kind, biz, parts: seen.append(biz) or [])

    async def apost(client, payload, **kw):
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    system = ("U " * 600 + "[[CHIEF_GLOBAL_SPLIT]]" + "M " * 900 + "[[CHIEF_CACHE_SPLIT]]"
              + "STATE A\n\nSTATE B " * 300 + "[[CHIEF_TURN_SPLIT]]" + "TURN")
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                 stable_tools=True, tool_biz={"id": "biz-from-tools"}))
    assert seen == ["biz-from-tools"]


# ─── The whole request (2026-10-07) ──────────────────────────────────────
# 48 calls in 30 days re-wrote Chief's whole brief within the hour and read
# nothing back: the start of the prefix moved. The API renders tools first
# and keys the cache to the model and effort, none of which the system-part
# watch could see.

def _fresh_requests():
    _fresh()
    cache_watch._last_call.clear()


def _payload(tools=("get_contacts", "show_view"), effort="low", model="claude-sonnet-5-5"):
    return {
        "model": model,
        "output_config": {"effort": effort},
        "tools": [{"name": n, "description": f"{n} tool", "input_schema": {}} for n in tools],
        "system": [
            {"type": "text", "text": "UNIVERSAL", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "MANUAL", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "STATE", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "THIS TURN at 09:02"},
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_request_parts_cover_what_the_cache_is_keyed_on_and_not_the_tail():
    parts = cache_watch.request_parts(_payload(), ttl="1h")
    assert list(parts)[:3] == ["model", "effort", "ttl"]
    assert "tool get_contacts" in parts and "tool show_view" in parts
    assert [k for k in parts if k.startswith("system")] == ["system 0", "system 1", "system 2"]
    assert not any("THIS TURN" in v for v in parts.values())


def test_a_tool_that_comes_and_goes_is_named(caplog):
    _fresh_requests()
    cache_watch.note_request("biz-t", _payload(), ttl="1h", role="chief_main")
    _capture(caplog)
    s = cache_watch.note_request("biz-t", _payload(tools=("get_contacts", "show_view", "generate_image")),
                                 ttl="1h", role="chief_main")
    assert "tool generate_image" in s["changed"] and "(order)" in s["changed"]
    assert not s["first"] and s["prev_role"] == "chief_main"


def test_effort_and_model_changes_are_named():
    _fresh_requests()
    cache_watch.note_request("biz-e", _payload(), role="chief_main")
    s = cache_watch.note_request("biz-e", _payload(effort=None), role="retry")
    assert s["changed"] == ["effort"]
    s = cache_watch.note_request("biz-e", _payload(effort=None, model="claude-sonnet-5"), role="retry")
    assert s["changed"] == ["model"]


def test_an_unchanged_request_logs_nothing(caplog):
    _fresh_requests()
    cache_watch.note_request("biz-q", _payload())
    _capture(caplog)
    before = len(caplog.records)
    assert cache_watch.note_request("biz-q", _payload())["changed"] == []
    assert len(caplog.records) == before


def test_a_rewrite_says_why(caplog):
    _fresh_requests()
    _capture(caplog)
    first = cache_watch.note_request("biz-w", _payload(), role="chief_main")
    cache_watch.report_write("biz-w", first, 0, 106000)
    assert "first call for this business" in caplog.records[-1].getMessage()
    moved = cache_watch.note_request("biz-w", _payload(tools=("get_contacts",)), role="chief_main")
    cache_watch.report_write("biz-w", moved, 0, 106000)
    line = caplog.records[-1].getMessage()
    assert "wrote 106000, read 0" in line and "'(order)'" in line and "min after a chief_main call" in line
    same = cache_watch.note_request("biz-w", _payload(tools=("get_contacts",)), role="chief_main")
    cache_watch.report_write("biz-w", same, 0, 106000)
    assert "nothing in the request changed" in caplog.records[-1].getMessage()


def test_small_writes_are_not_reported(caplog):
    _fresh_requests()
    _capture(caplog)
    s = cache_watch.note_request("biz-s", _payload())
    before = len(caplog.records)
    cache_watch.report_write("biz-s", s, 90000, 3000)
    cache_watch.report_write("biz-s", None, 0, 90000)
    cache_watch.report_write(None, s, 0, 90000)
    assert len(caplog.records) == before


class _RespWithUsage:
    status_code = 200
    text = ""

    def __init__(self, write):
        self._write = write

    def json(self):
        return {"stop_reason": "end_turn", "model": "claude-sonnet-5-5",
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": self._write},
                "content": [{"type": "text", "text": "ok"}]}


def test_chiefs_call_explains_a_big_rewrite(monkeypatch, caplog):
    import chief_of_staff as cos
    import llm_call
    import spend_guard
    _fresh_requests()

    async def apost(client, payload, **kw):
        return _RespWithUsage(106000)
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    system = ("U " * 600 + "[[CHIEF_GLOBAL_SPLIT]]" + "M " * 900 + "[[CHIEF_CACHE_SPLIT]]"
              + "STATE A\n\nSTATE B " * 300 + "[[CHIEF_TURN_SPLIT]]" + "TURN")
    _capture(caplog)
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                 business_id="biz-c", stable_tools=True, timing_role="chief_main"))
    lines = [r.getMessage() for r in caplog.records if "cache rewrite" in r.getMessage()]
    assert lines and "biz=biz-c" in lines[-1] and "role=chief_main" in lines[-1] and "wrote 106000" in lines[-1]
