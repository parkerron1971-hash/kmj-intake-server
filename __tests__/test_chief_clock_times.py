"""
test_chief_clock_times.py — the answer check reads clock times (2026-09-14).

A practitioner set her week's hours by voice. The receipts said
"📅 Thu → 09:00–17:30"; Chief's replies said "9am to 5:30pm". The figure
parser dropped "9am" and the "30pm" of "5:30pm" as letter-digit
identifiers, kept a lone 5, and found no 5 in 09:00–17:30 — six replies
in a row were withheld as "claim number 5 is not in the quote". A clock
time is a figure on the 24-hour clock however it is written, and an
hour a receipt writes as 13:00 is "1" on the practitioner's clock.
"""
from __future__ import annotations

import json
import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


def _review(text, quote, sid="result:0", kind="action"):
    return json.dumps({"verdict": "supported",
                       "claims": [{"text": text, "kind": kind, "source_id": sid, "quote": quote}]})


def _receipt(label):
    return {"result:0": {"kind": "receipt", "complete": True,
                         "text": json.dumps({"type": "set_availability_day", "result": "updated", "label": label}, ensure_ascii=False)}}


@pytest.mark.parametrize("text,expected", [
    ("9am", ["9", "0"]),
    ("9 a.m.", ["9", "0"]),
    ("5:30pm", ["17", "30"]),
    ("5:30 PM", ["17", "30"]),
    ("12pm", ["12", "0"]),
    ("12am", ["0", "0"]),
    ("11:30", ["11", "30"]),
    ("17:30", ["17", "30"]),
    ("09:00–17:30", ["9", "0", "17", "30"]),
    ("5 invoices", ["5"]),
    ("INV-2026-007 for $150", ["150"]),
])
def test_clock_times_are_figures_on_the_24_hour_clock(text, expected):
    assert truth._figures(text) == expected


def test_iso_timestamps_still_split_into_date_and_hour():
    assert truth._numbers("2026-09-14T10:00") >= {Decimal(2026), Decimal(9), Decimal(14), Decimal(10), Decimal(0)}


def test_a_bare_hour_needs_a_meridiem_to_be_a_time():
    assert "9" in truth._figures("9 to 11:30am")
    assert truth._numbers("3 things at 3pm") == {Decimal(3), Decimal(15), Decimal(0)}


# The six drafts the log recorded as withheld, against the receipts and
# context they were actually checked against.
@pytest.mark.parametrize("draft,claim,quote,label", [
    ("Thursdays are now 9am to 5:30pm, cut off before Bible study.",
     "Thursdays are now 9am to 5:30pm", "📅 Thu → 09:00–17:30", "📅 Thu → 09:00–17:30"),
    ("Thursday, 9am to 5:30pm",
     "Thursday, 9am to 5:30pm", "📅 Thu → 09:00–17:30", "📅 Thu → 09:00–17:30"),
    ("Wednesday, same split as Monday, 9 to 11:30, then 1 to 8",
     "9 to 11:30, then 1 to 8", "📅 Wed → 09:00–11:30, 13:00–20:00", "📅 Wed → 09:00–11:30, 13:00–20:00"),
    ("So far set: Monday 9–11:30am and 1–8pm, Tuesday 9am–8pm.",
     "Monday 9–11:30am and 1–8pm", "📅 Mon → 09:00–11:30, 13:00–20:00", "📅 Mon → 09:00–11:30, 13:00–20:00"),
    ("Monday and Wednesday: 9am to 11:30am, then 1pm to 8pm (gap for the school run).",
     "9am to 11:30am, then 1pm to 8pm", "📅 Mon → 09:00–11:30, 13:00–20:00", "📅 Mon → 09:00–11:30, 13:00–20:00"),
])
def test_hours_said_on_the_12_hour_clock_match_a_24_hour_receipt(draft, claim, quote, label):
    verdict, cited, reason = truth.assess_review(_review(claim, quote), draft, _receipt(label))
    assert verdict == "supported", reason
    assert cited == ["result:0"]


def test_a_wrong_hour_is_still_caught():
    draft = "Thursday, 9am to 6:30pm"
    verdict, _, reason = truth.assess_review(
        _review("Thursday, 9am to 6:30pm", "📅 Thu → 09:00–17:30"), draft, _receipt("📅 Thu → 09:00–17:30"))
    assert verdict == "unsupported"
    assert "claim number 18" in reason


def test_twelve_hour_twins_only_come_from_clock_times():
    # "1 to 8" against 13:00–20:00 passes because the quote holds clock
    # times; the same words against a quote with no times still fail.
    assert truth._clock_twins("13:00–20:00") >= {Decimal(1), Decimal(13), Decimal(8), Decimal(20)}
    assert truth._clock_twins("13 lessons, 20 clients") == set()
    verdict, _, reason = truth.assess_review(
        _review("1 to 8 lessons", "13 lessons, 20 clients", kind="fact"),
        "1 to 8 lessons", {"result:0": {"kind": "record", "complete": True, "text": "13 lessons, 20 clients"}})
    assert verdict == "unsupported"
