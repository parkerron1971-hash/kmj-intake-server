"""
test_empty_calendar_is_an_answer.py — a complete, empty calendar read says "nothing booked" (2026-09-24).

The prompt said "(none in the loaded sample; check data availability)"
under the calendar whether the read had succeeded or failed. Live on KMJ,
"When is my next appointment?" then spent two lookups (17.9 s) before
saying nothing was booked. A read that succeeded and came back under its
limit of 10 is the whole calendar for the window; a failed read still
says to check.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
from __tests__.test_gather_context_wave2 import gather  # noqa: F401  (fixture)

NOTHING_BOOKED = "(nothing booked in this window: this list is the whole calendar for it)"
CHECK = "(none in the loaded sample; check data availability)"


def _with_sessions(monkeypatch, value):
    original = chief._sb

    async def rows(client, method, path, body=None):
        if path.startswith('/sessions?'):
            return value
        return await original(client, method, path, body)
    monkeypatch.setattr(chief, '_sb', rows)


def _calendar(prompt):
    return prompt.split(chief.SESSIONS_HEADING + ":", 1)[1].split("\n\n", 1)[0]


def test_an_empty_read_is_nothing_booked(gather, monkeypatch):
    _with_sessions(monkeypatch, [])
    _, ctx = gather(query_text=None)
    assert ctx['sessions_complete'] is True
    assert NOTHING_BOOKED in _calendar(chief._format_context_for_prompt(ctx))


def test_a_failed_read_still_says_to_check(gather, monkeypatch):
    _with_sessions(monkeypatch, None)
    _, ctx = gather(query_text=None)
    assert ctx['sessions'] == [] and ctx['sessions_complete'] is False
    calendar = _calendar(chief._format_context_for_prompt(ctx))
    assert CHECK in calendar and NOTHING_BOOKED not in calendar


def test_a_full_page_is_not_called_complete(gather, monkeypatch):
    rows = [{"id": f"s{i}", "title": "Call", "scheduled_for": "2026-09-25T15:00:00+00:00",
             "contacts": {"name": "Tasha"}} for i in range(10)]
    _with_sessions(monkeypatch, rows)
    _, ctx = gather(query_text=None)
    assert ctx['sessions_complete'] is False
