"""
test_cases_in_work_report.py — "what are you handling?" includes the
problems Chief is keeping an eye on (2026-10-07).

Chief's work report (Codex's chief_responsibilities.py) read assignments,
plans, builds, errands, approvals and event reviews. The problems Chief
diagnosed and is checking (chief_cases.py) were missing, so "what are you
handling?" never mentioned them. They are now a seventh source, in the
owner's words, and a checked result counts as needing the owner.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_responsibilities as responsibilities

BID = "11111111-1111-1111-1111-111111111111"

OPEN = {"id": "c-1", "status": "open", "symptom": "Tuesdays are dead",
        "cause": "no hours set", "fix": "set hours, text regulars",
        "measure": {"kind": "sessions_scheduled", "weekdays": [1, 2], "unit": "appointments"},
        "baseline": {"value": 4, "from": "2026-09-14", "to": "2026-10-04",
                     "window_from": "2026-10-05", "window_to": "2026-10-25"},
        "expected": 9, "check_on": "2026-10-26", "updated_at": "2026-10-05T20:00:00Z"}
CHECKED = {**OPEN, "id": "c-2", "status": "checked", "verdict": "partly",
           "result": {"value": 6}, "checked_at": "2026-10-26T06:00:00Z"}


def _read_with(cases):
    seen = []

    def read(query):
        seen.append(query)
        if query.startswith("/chief_cases"):
            return cases
        return []
    return read, seen


def test_the_report_reads_the_cases_for_this_business_only(monkeypatch):
    read, seen = _read_with([OPEN, CHECKED])
    monkeypatch.setattr(responsibilities.sb_clients, "sb_get_as_service", read)
    monkeypatch.setenv("CHIEF_DURABLE_EVENTS", "off")
    report = asyncio.run(responsibilities.snapshot(BID))
    q = [x for x in seen if x.startswith("/chief_cases")][0]
    assert f"business_id=eq.{BID}" in q and "status.eq.open" in q
    assert report["sources"]["cases"]["available"]
    items = {i["source_id"]: i for i in report["items"] if i["source"] == "cases"}
    assert items["c-1"]["title"] == "Tuesdays are dead"
    assert items["c-1"]["status"] == "keeping_an_eye_on" and not items["c-1"]["needs_you"]
    assert items["c-1"]["next_check_at"] == "2026-10-26"
    assert items["c-1"]["summary"].startswith("Keeping an eye on it. Before: 4 appointments")
    assert items["c-2"]["needs_you"] and items["c-2"]["summary"].startswith("It helped.")
    assert "Now: 6 appointments" in items["c-2"]["summary"]
    for item in items.values():
        assert "not proof" in item["attribution"]
        assert "case" not in item["summary"].lower() and "forecast" not in item["summary"].lower()


def test_an_unreadable_cases_table_is_named_not_hidden(monkeypatch):
    read, _ = _read_with(None)
    monkeypatch.setattr(responsibilities.sb_clients, "sb_get_as_service", read)
    monkeypatch.setenv("CHIEF_DURABLE_EVENTS", "off")
    report = asyncio.run(responsibilities.snapshot(BID))
    assert not report["sources"]["cases"]["available"] and report["partial"]


def test_chief_can_ask_for_just_the_cases(monkeypatch):
    read, _ = _read_with([OPEN, CHECKED])
    monkeypatch.setattr(responsibilities.sb_clients, "sb_get_as_service", read)
    monkeypatch.setenv("CHIEF_DURABLE_EVENTS", "off")
    out = asyncio.run(responsibilities.handle_responsibility_status(None, {"id": BID}, {"source": "cases"}))
    report = out["responsibilities"]
    assert report["scope"] == "cases" and report["total_found"] == 2
    assert report["source_counts"] == {"cases": {"found": 2, "needs_you": 1}}
    import mcp_server
    enum = mcp_server.TOOL_SCHEMAS["responsibility_status"][1]["properties"]["source"]["enum"]
    assert "cases" in enum
    with pytest.raises(ValueError):
        asyncio.run(responsibilities.handle_responsibility_status(None, {"id": BID}, {"source": "nope"}))
