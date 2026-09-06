"""
test_turn_status.py — the turn says what it is doing.

While the server reads the business, waits on the model, runs the
actions and writes the second pass, the stream now carries a status
event; the plain endpoint never sees one. Tested as arithmetic: the
prefix, the phrases, and what one sink piece becomes on the wire.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos


def test_status_rides_the_sink_only_when_streaming():
    got = []
    tok = cos._STREAM_SINK.set(got.append)
    try:
        cos._turn_status("thinking")
        cos._turn_status("")
    finally:
        cos._STREAM_SINK.reset(tok)
    assert got == [cos.STATUS_PREFIX + "thinking"]
    cos._turn_status("thinking")            # no sink: nothing happens, nothing raised


def test_actions_read_as_plain_phrases():
    acts = [{"type": "create_client_form"}, {"type": "navigate"}, {"type": "remember"}]
    assert cos._humanize_actions(acts) == "creating the form and opening the room"
    assert cos._humanize_actions([{"type": "frobnicate_widget"}]) == "frobnicate widget"
    assert cos._humanize_actions([]) == "working on it"
    assert cos._humanize_actions([{"type": "show_view"}, {"type": "show_view"}]) == "pulling up the numbers"


def test_a_status_piece_becomes_a_status_event_never_text():
    filt = cos._ActionTagFilter()
    assert cos._stream_piece_events(cos.STATUS_PREFIX + "reading your business", filt) == [
        {"type": "status", "text": "reading your business"}]
    # ordinary text still flows through the tag filter as a delta
    evs = cos._stream_piece_events("Hello there. ", filt)
    assert evs and evs[0]["type"] == "delta" and "Hello" in evs[0]["text"]
    # a status never leaks into the text the filter is holding
    evs = cos._stream_piece_events(cos.STATUS_PREFIX + "thinking", filt)
    assert all(e["type"] == "status" for e in evs)
