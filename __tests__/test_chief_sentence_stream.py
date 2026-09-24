"""
test_chief_sentence_stream.py — Chief speaks as it writes (2026-09-23).

Kevin: "chief responding as it's receiving information … instead of
waiting until it gets all the information." A reply used to be held whole
until actions and the answer check finished. Now each finished sentence of
the first model call goes out the moment the records prove it; the first
sentence they cannot prove closes the stream, and the rest arrives after
the full check as the continuation — never the whole reply a second time.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
import chief_truth as truth

SESSIONS = {"context:sessions": {"kind": "context", "complete": False, "text": json.dumps([
    {"title": "Knotless Braids", "scheduled_for": "2026-09-24T15:00:00+00:00", "contacts": {"name": "Tasha Brown"}},
    {"title": "Boho Bob", "scheduled_for": "2026-09-25T13:00:00+00:00", "contacts": {"name": "Maria Lopez"}},
])}}
DETROIT = ZoneInfo("America/Detroit")


def _stream(pieces, sources=SESSIONS):
    out = []
    s = chief._SentenceStreamer(out.append, truth.stream_prover(sources, DETROIT))
    for p in pieces:
        s(p)
    s.close()
    return [x[len(chief.PROSE_PREFIX):] for x in out], s


def test_a_proved_sentence_goes_out_the_moment_it_ends():
    said, s = _stream(["Your next appointment is Septem", "ber 24 at 11am with Tasha Brown. ",
                       "Want me to send her a reminder?"])
    # The question has no sentence end yet when the stream closes: it waits.
    assert said == ["Your next appointment is September 24 at 11am with Tasha Brown. "]
    assert s.text == said[0]


def test_the_first_unproved_sentence_closes_the_stream():
    said, _ = _stream(["Your next appointment is September 24 at 11am with Tasha Brown. ",
                       "She paid in full last week. ", "Anything else? "])
    assert said == ["Your next appointment is September 24 at 11am with Tasha Brown. "]


@pytest.mark.parametrize("sentence", [
    "Your next appointment is September 24 at 3pm with Tasha Brown. ",   # the UTC hour
    "I've booked Maria for Friday. ",                                     # a completion
    "Cash on hand is about eleven dollars. ",                             # spelled amount
    "Similar intensives run $800 a seat. ",                               # figure in no record
    "Nothing is booked tomorrow. ",                                       # state of a record
    "Tasha prefers mornings. ",                                           # a name proves nothing
])
def test_what_the_records_do_not_prove_never_streams(sentence):
    said, _ = _stream([sentence, "Okay. "])
    assert said == []


def test_plain_advice_streams_until_it_touches_the_business():
    said, _ = _stream(["Here's the whole arc. ",
                       "Pick one date this week since everything else counts backward from it. ",
                       "Your four cold leads come first. ", "Then the curriculum. "])
    assert said == ["Here's the whole arc. ",
                    "Pick one date this week since everything else counts backward from it. "]


def test_an_action_tag_stops_the_stream_before_the_narration():
    said, _ = _stream(["Here's where things stand. ", '[ACTION:{"type":"show_view"', '}] ',
                       "Here it is. "])
    assert said == ["Here's where things stand. "]


def test_a_promise_to_open_waits_for_the_action():
    # "Let me pull that up." is a promise until the navigation exists
    # (2026-09-23: "Let me open it." with nothing opened).
    said, _ = _stream(["Let me pull that up. ", "Here it is. "])
    assert said == []


def test_the_lane_has_kill_switches(monkeypatch):
    monkeypatch.setenv("CHIEF_STREAM_SENTENCES", "off")
    assert truth.stream_prover(SESSIONS) is None
    monkeypatch.delenv("CHIEF_STREAM_SENTENCES")
    monkeypatch.setenv("CHIEF_REVIEW_FAST_LANE", "off")
    assert truth.stream_prover(SESSIONS) is None


@pytest.mark.parametrize("final,expected_rest", [
    ("Here's the arc. Step two is pricing.", " Step two is pricing."),
    ("Here's  the arc.\nStep two is pricing.", "\nStep two is pricing."),
])
def test_the_reply_continues_what_streamed(final, expected_rest):
    stitched = chief._stitch_after_stream("Here's the arc. ", final)
    assert stitched.startswith("Here's the arc. ")
    assert stitched[len("Here's the arc. "):].strip() == expected_rest.strip()


def test_a_withheld_rest_is_one_honest_line_not_the_canned_retry():
    stitched = chief._stitch_after_stream("Here's the arc. ", truth.NO_ACTION_REPLY)
    assert stitched.startswith("Here's the arc.")
    assert "try again" not in stitched and "couldn't confirm the rest" in stitched


def test_the_endpoint_sends_each_sentence_once():
    async def run():
        async def fake_chat(req, session):
            s = chief._SentenceStreamer(chief._STREAM_SINK.get(), truth.stream_prover(SESSIONS, DETROIT))
            s("Your next appointment is September 24 at 11am with Tasha Brown. ")
            s("She paid last week. ")   # closes the stream
            s.close()
            final = chief._stitch_after_stream(
                s.text, "Your next appointment is September 24 at 11am with Tasha Brown. "
                        "Want me to send her a reminder?")
            return {"response": final, "actions_taken": []}
        chief_chat, chief.chief_chat = chief.chief_chat, fake_chat
        try:
            response = await chief.chief_chat_stream(
                chief.ChatRequest(business_id="fixture", message="next appointment?"), None)
            frames = [f async for f in response.body_iterator]
        finally:
            chief.chief_chat = chief_chat
        events = [json.loads(f.removeprefix("data: ").strip()) for f in frames if f.startswith("data:")]
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        assert deltas == ["Your next appointment is September 24 at 11am with Tasha Brown. ",
                          "Want me to send her a reminder?"]
        assert "".join(deltas) == events[-1]["payload"]["response"]
    asyncio.run(run())
