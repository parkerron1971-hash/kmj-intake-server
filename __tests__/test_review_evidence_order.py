"""
test_review_evidence_order.py — a tool read outranks standing context (2026-09-14).

Chief read the availability config, answered "Thursday's 9am to 5pm", and
the reviewer marked it a gap: it was never shown the record. Reads made
in the turn live only in the turn's source store, and the evidence
budget (30,000 chars) kept results, then context, then the store — so a
business with a full blueprint, brand and playbook (10,000 chars each)
evicted the one record the reply was about. Now: results, then this
turn's reads, then context.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


FAT = {"blueprint_block": "b" * 10000, "brand_block": "r" * 10000,
       "playbook_block": "p" * 10000, "voice_block": "v" * 10000}


def test_a_tool_read_survives_a_full_context():
    token = truth.begin("owner-1", "What are my hours on Thursday?")
    try:
        truth.record("tool:list_availability", {"summary": "thu: 09:00–17:00"})
        sources = truth.evidence_for_review(FAT, {}, [])
    finally:
        truth.end(token)
    assert "tool:list_availability" in sources
    assert "thu: 09:00–17:00" in sources["tool:list_availability"]["text"]
    assert sum(len(s["text"]) for s in sources.values()) <= truth.MAX_EVIDENCE_CHARS


def test_rank_is_results_then_reads_then_context():
    token = truth.begin("owner-1", "q")
    try:
        truth.record("tool:check_goals", {"goals": 2})
        sources = truth.evidence_for_review({"contacts_total": 725}, {}, [{"type": "create_task", "task_id": "t1"}])
    finally:
        truth.end(token)
    assert list(sources) == ["result:0", "tool:check_goals", "context:contacts_total"]


def test_a_read_that_is_also_a_context_field_is_the_read():
    # The store's value for an id wins over the context copy and keeps
    # the higher rank; nothing is listed twice.
    token = truth.begin("owner-1", "q")
    try:
        truth.record("context:queue", {"pending": 3})
        sources = truth.evidence_for_review({"queue": {"pending": 1}}, {}, [])
    finally:
        truth.end(token)
    assert list(sources) == ["context:queue"]
    assert '"pending": 3' in sources["context:queue"]["text"]


def test_the_calendar_survives_a_full_context():
    # 2026-09-23: "when is my next appointment?" was answered right
    # ("nothing on your calendar") and marked unverified, because the
    # budget dropped context:sessions to keep the blueprint.
    ctx = {**FAT, "foundation_block": "f" * 10000, "business_profile_block": "q" * 10000,
           "sessions": [], "open_invoices": [{"number": "INV-2026-013", "total": 55}],
           "contacts_total": 725, "context_quality": {"sessions": "ok"}}
    sources = truth.evidence_for_review(ctx, {}, [])
    for sid in ("context:sessions", "context:open_invoices", "context:contacts_total",
                "context:context_quality"):
        assert sid in sources, sid
    assert "context:blueprint_block" not in sources
    assert sum(len(s["text"]) for s in sources.values()) <= truth.MAX_EVIDENCE_CHARS
