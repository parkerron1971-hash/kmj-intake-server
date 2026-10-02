"""
test_chief_ratios_are_not_figures.py — "1:1" is a format, not a quantity (2026-09-24).

Live: pricing answer mentioning "1:1" coaching → `claim number 1 is not in
the quote :: no product/pricing records show a 1:1 or group-cohort price`,
and the trim could not save the answer (every 1:1 sentence "had" a 1).
"""
from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


@pytest.mark.parametrize("text,expected", [
    ("$3,000 for the 1:1 intensive", ["3,000"]),
    ("1-on-1 coaching", []),
    ("a 2x2 grid", []),
    ("9:30am", ["9", "30"]),
    ("3 x 5 = 15", ["3", "5", "15"]),
    ("1:1 at 3pm", ["15", "0"]),
])
def test_ratios_drop_out_and_clock_times_stay(text, expected):
    assert truth._figures(text) == expected


def test_trim_logs_why_it_gave_up(caplog):
    import json
    caplog.set_level("INFO")
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "Revenue was $900,000", "kind": "fact", "source_id": "", "quote": "", "gap": "x"}]})
    assert truth._trim_unsupported(raw, "Revenue was $900,000.", {},
                                   "claim number has no evidence :: Revenue was $900,000") is None
    assert "reply trim not possible" in caplog.text
