"""
test_cost_counts_1h_writes.py — a 1-hour cache write is priced at 2×, not 1.25× (2026-09-24).

Chief's universal and per-business prompt segments are cached with the
1-hour TTL, which the API bills at 2× base input for the write. The logger
priced every write at 1.25×, so a 1-hour write was logged at 62% of what it
cost, and the per-reply cost the credit price is set against read low.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from api_usage_logger import _compute_cost_cents, cache_write_1h


def test_the_1h_part_of_a_write_is_priced_at_2x():
    # Sonnet 5 at $2/MTok: 10k 5-minute writes = 2.5c, 10k 1-hour writes = 4c.
    assert _compute_cost_cents('claude-sonnet-5', 0, 0, cache_creation_tokens=20_000,
                               cache_creation_1h_tokens=10_000) == pytest.approx(6.5)


def test_without_the_breakdown_a_write_keeps_the_5_minute_rate():
    assert _compute_cost_cents('claude-sonnet-5', 0, 0, cache_creation_tokens=20_000) == pytest.approx(5.0)


def test_a_1h_count_never_exceeds_the_whole_write():
    assert _compute_cost_cents('claude-sonnet-5', 0, 0, cache_creation_tokens=10_000,
                               cache_creation_1h_tokens=99_000) == pytest.approx(4.0)


def test_the_breakdown_is_read_from_the_api_usage():
    usage = {"cache_creation_input_tokens": 57_000,
             "cache_creation": {"ephemeral_5m_input_tokens": 12_000, "ephemeral_1h_input_tokens": 45_000}}
    assert cache_write_1h(usage) == 45_000
    for missing in ({}, None, {"cache_creation": None}, {"cache_creation": "x"}):
        assert cache_write_1h(missing) == 0


def test_chiefs_main_call_logs_the_1h_part_on_both_paths():
    import chief_of_staff as cos
    src = inspect.getsource(cos._call_claude)
    assert src.count("cache_creation_1h_tokens=") == 2
