"""
test_failed_read_holds_still.py — a failed read's id carries no clock (2026-09-24).

The cache watch's first live lines named the one part of Chief's cached
prompt that moved between messages, 11 s apart: the DATA QUALITY line,
digits only, and the same in the answer check's context_quality record.
A read that fails as the owner is listed there as 'lookup:' + its path,
and a path like "/insights?...&created_at=gte.<now>" differs on every
message, so both caches were re-written (~48k tokens) on every reply.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_truth
import sb_clients


def _failed_reads(monkeypatch, paths):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(sb_clients, "sb_as_current_context", none)
    token = chief_truth.begin("owner", "q")
    try:
        for p in paths:
            assert asyncio.run(cos._sb(None, "GET", p)) is None
        return sorted(chief_truth.unavailable_sources())
    finally:
        chief_truth.end(token)


def test_the_same_failed_read_has_one_id_whatever_the_time(monkeypatch):
    ids = _failed_reads(monkeypatch, [
        "/insights?business_id=eq.b1&created_at=gte.2026-09-24T13:43:30.688123+00:00&limit=5",
        "/insights?business_id=eq.b1&created_at=gte.2026-09-24T13:43:41.958456+00:00&limit=5",
        "/image_artworks?business_id=eq.b1&created_at=gte.2026-09-24T11:43:41Z&limit=5",
    ])
    assert ids == ["lookup:/image_artworks?business_id=eq.b1&created_at=gte.<time>&limit=5",
                   "lookup:/insights?business_id=eq.b1&created_at=gte.<time>&limit=5"]


def test_the_log_names_the_table_only(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="chief_of_staff")
    _failed_reads(monkeypatch, ["/contacts?business_id=eq.secret-biz&name=eq.Monica"])
    lines = [r.getMessage() for r in caplog.records if "read unavailable" in r.getMessage()]
    assert lines == ["chief read unavailable: /contacts"]
