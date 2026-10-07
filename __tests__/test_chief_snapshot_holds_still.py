"""
test_chief_snapshot_holds_still.py — what moves between messages stays out of the cached segments (2026-10-07).

The cache watch on 6 and 7 October named the parts of Chief's cached
prompt that changed between two messages of one conversation. Inside the
~20k-token state snapshot: DATA QUALITY, UNREAD INSIGHTS, RECENT UNREAD
NOTIFICATIONS, RECENT EVENTS, RECENT AGENT ACTIVITY, the screen they were
on, the habit and relationship notes. Inside the ~80k-token operating
manual: the mentor switch and the voice examples. Any one of them
changing re-wrote its whole cached segment. They now ride the per-message
tail after [[CHIEF_TURN_SPLIT]], word for word.
"""
from __future__ import annotations

import collections
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos


def _ctx(**over):
    base = collections.defaultdict(lambda: [], {
        "business": {"id": "b1", "name": "Biz", "settings": {"practitioner_name": "K"},
                     "voice_profile": {}}})
    base.update(over)
    return base


def _segments(prompt):
    universal, _, rest = prompt.partition("[[CHIEF_GLOBAL_SPLIT]]")
    manual, _, rest = rest.partition("[[CHIEF_CACHE_SPLIT]]")
    state, _, turn = rest.partition("[[CHIEF_TURN_SPLIT]]")
    return universal, manual, state, turn


def _now():
    return datetime.now(timezone.utc).isoformat()


def test_the_mentor_switch_and_voice_examples_leave_the_manual_alone():
    a = _segments(cos._build_system_prompt(_ctx(), False, mentor_active=True, voice_examples="VOICE_A"))
    b = _segments(cos._build_system_prompt(_ctx(), False, mentor_active=False, voice_examples="VOICE_B"))
    assert a[1] == b[1], "a per-message switch re-wrote the operating manual"
    assert a[2] == b[2]
    assert "MENTOR MODE: OFF" in b[3] and "VOICE_B" in b[3]
    assert "MENTOR MODE: active" in a[3] and "VOICE_A" in a[3]


def test_unread_items_and_recent_activity_leave_the_snapshot_alone():
    stamp = _now()
    quiet = _segments(cos._build_system_prompt(
        _ctx(context_quality={"retrieved_at": stamp, "unavailable": []}), False))
    busy_ctx = _ctx(
        notifications=[{"type": "alert", "title": "NOTE_X", "created_at": stamp}],
        insights=[{"priority": "high", "category": "cash", "title": "INSIGHT_X"}],
        events=[{"event_type": "EVENT_X", "created_at": stamp}],
        context_quality={"retrieved_at": stamp, "unavailable": ["lookup:/contacts"]},
    )
    busy = _segments(cos._build_system_prompt(busy_ctx, False))
    assert quiet[1] == busy[1] and quiet[2] == busy[2], "a moving section re-wrote a cached segment"
    for text in ("NOTE_X", "INSIGHT_X", "EVENT_X", "DATA QUALITY:", "lookup:/contacts",
                 "UNREAD INSIGHTS:", "RECENT UNREAD NOTIFICATIONS:", "RECENT AGENT ACTIVITY"):
        assert text in busy[3], text
        assert text not in busy[2], text


def test_the_screen_they_are_on_rides_the_turn():
    view = cos.CurrentContext(tab="operate", sub_tab="contacts")
    a = _segments(cos._build_system_prompt(_ctx(), False))
    b = _segments(cos._build_system_prompt(_ctx(), False, view=view, view_detail={}))
    assert a[2] == b[2]
    assert "CURRENTLY VIEWING: OPERATE" in b[3]


def test_habit_relationship_and_situational_notes_ride_the_turn():
    paid = [{"event_type": "invoice_paid", "created_at": _now()} for _ in range(3)]
    a = _segments(cos._build_system_prompt(_ctx(), False))
    b = _segments(cos._build_system_prompt(_ctx(recent_events=paid), False,
                                           habit_block="HABIT_X", relationships_block="REL_X"))
    assert a[1] == b[1] and a[2] == b[2]
    assert "HABIT_X" in b[3] and "REL_X" in b[3] and "SITUATIONAL: Multiple payments" in b[3]


def test_the_session_recap_stays_in_the_cached_snapshot():
    # Unchanged on purpose: no watch line has named it yet.
    s = _segments(cos._build_system_prompt(_ctx(), False, session_context="RECAP_X"))
    assert "RECAP_X" in s[2] and "RECAP_X" not in s[3]


def test_the_whole_snapshot_text_is_still_available_in_one_block():
    ctx = _ctx(insights=[{"priority": "high", "category": "cash", "title": "INSIGHT_X"}])
    whole = cos._format_context_for_prompt(ctx)
    stable, live = cos._format_context_parts(ctx)
    assert whole == stable + "\n" + live
    assert "BUSINESS: Biz" in stable and "INSIGHT_X" in live and "INSIGHT_X" not in stable
    assert "The lists in the business snapshot above are samples" in live


def test_no_business_data_is_still_one_line():
    assert cos._format_context_for_prompt({}) == "NO BUSINESS DATA AVAILABLE."


def test_the_kill_switch_restores_the_old_layout(monkeypatch):
    monkeypatch.setenv("CHIEF_SNAPSHOT_SPLIT", "off")
    ctx = _ctx(insights=[{"priority": "high", "category": "cash", "title": "INSIGHT_X"}],
               recent_events=[{"event_type": "invoice_paid", "created_at": _now()} for _ in range(3)])
    view = cos.CurrentContext(tab="operate", sub_tab="contacts")
    s = _segments(cos._build_system_prompt(ctx, False, view=view, view_detail={},
                                           mentor_active=True, voice_examples="VOICE_A",
                                           habit_block="HABIT_X", relationships_block="REL_X"))
    assert "MENTOR MODE: active" in s[1] and "VOICE_A" in s[1] and "SITUATIONAL: Multiple payments" in s[1]
    for text in ("INSIGHT_X", "CURRENTLY VIEWING: OPERATE", "HABIT_X", "REL_X"):
        assert text in s[2], text
    for text in ("MENTOR MODE", "VOICE_A", "INSIGHT_X", "CURRENTLY VIEWING", "HABIT_X", "REL_X", "SITUATIONAL"):
        assert text not in s[3], text
