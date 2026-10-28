"""
test_chief_tone_notes.py — Chief marks how a spoken reply should sound
(Kevin, 2026-10-18: "build the tone notes").

A featured voice changes tone on Inworld's bigger model when Chief writes
a note — [pleased] [proud] [gentle] [steady] [breathe] — and stays on the
cheaper Flash model when it does not. What has to hold:

1. A note is never a word: the answer check, the stitched reply, the chat
   bubble and the reply on file all read the text without it, and the
   voice gets it beside the words (`speech` on a delta event).
2. The part of a reply that did not stream is said with its notes in the
   same places; a tail the answer check rewrote is said steady.
3. The speech proxy turns a note into Inworld's steering on the tone
   model, keeps a breath on Flash, drops notes past the monthly cap, and
   gives every other voice the words alone.
4. Only a voice turn that asked (a featured voice) and a switch that is
   on gets the rules in its prompt.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import chief_of_staff as chief  # noqa: E402
import chief_tone  # noqa: E402
import chief_truth as truth  # noqa: E402
import whisper_proxy as wp  # noqa: E402
from chief_voice_bridge import VoiceBridge  # noqa: E402
from test_inworld_voices import (  # noqa: E402,F401 — the same fake Inworld
    _Client, _Upstream, _inworld_sent, _line, _openai_sent, _speak, env)

REPLY = ("[pleased] Monica paid her invoice this morning. [breathe] [steady] But two "
         "others are still out, about eleven hundred dollars between them.")
CLEAN = ("Monica paid her invoice this morning. But two others are still out, about "
         "eleven hundred dollars between them.")
P = chief.PROSE_PREFIX


@pytest.fixture
def toned():
    turn = chief_tone.ToneTurn(enabled=True)
    token = chief_tone.TURN.set(turn)
    yield turn
    chief_tone.TURN.reset(token)


# ── 1. a note is never a word ────────────────────────────────────────

def test_the_reply_reads_without_its_notes():
    assert chief_tone.strip(REPLY) == CLEAN
    assert chief_tone.strip("[gentle]Her surgery went well.") == "Her surgery went well."
    assert chief_tone.strip("Revenue is up.[breathe][steady]But two are late.") == (
        "Revenue is up. But two are late.")
    assert chief_tone.strip("That's all for today. [breathe]") == "That's all for today."
    assert chief_tone.strip("Plain words [ACTION:{}] stay.") == "Plain words [ACTION:{}] stay."


@pytest.mark.parametrize("parts", [
    ["[pleased] Monica paid. ", "[breathe] [steady] But two are out."],
    ["Done.\n\n", "[steady] But the bank form is still missing."],
    ["[proud] Best month yet. ", "[breathe]\n", "[steady] One invoice is late."],
])
def test_sentence_by_sentence_reads_the_same_as_the_whole(parts):
    # The streamed sentences and the reply on file must stitch exactly.
    assert "".join(chief_tone.strip(p) for p in parts) == chief_tone.strip("".join(parts))


def test_notes_are_spelled_one_way_for_the_voice():
    assert chief_tone.speech("[Pleased] Hi.") == "[pleased] Hi."
    assert chief_tone.speech("No notes here.") is None
    assert chief_tone.steers("[breathe] But two are out.") is False
    assert chief_tone.steers("[steady] Two are out.") is True


def test_a_model_answer_is_untouched_unless_the_turn_asked():
    assert chief_tone.take(REPLY) == REPLY
    token = chief_tone.TURN.set(chief_tone.ToneTurn(enabled=False))
    try:
        assert chief_tone.take(REPLY) == REPLY
    finally:
        chief_tone.TURN.reset(token)


def test_a_toned_turn_records_the_notes_and_reads_on_without_them(toned):
    assert chief_tone.take(REPLY) == CLEAN
    assert chief_tone.take("No notes.") == "No notes."
    assert toned.records == [REPLY]


def test_every_model_call_hands_back_the_words(toned):
    async def call(*a, **k):
        return REPLY
    assert asyncio.run(chief._without_tone_notes(call)(None, "", [])) == CLEAN
    assert toned.records == [REPLY]
    # The live call is wrapped the same way.
    assert chief._call_claude.__wrapped__.__name__ == "_call_claude"


SESSIONS = {"context:sessions": {"kind": "context", "complete": False, "text": json.dumps([
    {"title": "Knotless Braids", "scheduled_for": "2026-09-24T15:00:00+00:00",
     "contacts": {"name": "Tasha Brown"}},
])}}


def _stream(pieces):
    out = []
    s = chief._SentenceStreamer(out.append, truth.stream_prover(SESSIONS, ZoneInfo("America/Detroit")))
    for p in pieces:
        s(p)
    s.close()
    return [x[len(P):] for x in out], s


def test_a_toned_sentence_is_checked_without_its_note_and_spoken_with_it(toned):
    said, s = _stream(["[pleased] Your next appointment is Septem",
                       "ber 24 at 11am with Tasha Brown. ", "Anything else"])
    assert said == ["[pleased] Your next appointment is September 24 at 11am with Tasha Brown. "]
    # What streamed, for stitching against the reply on file: words only.
    assert s.text == "Your next appointment is September 24 at 11am with Tasha Brown. "
    events = chief._stream_piece_events(P + said[0], chief._ActionTagFilter())
    assert events == [{"type": "delta", "checked": True,
                       "text": "Your next appointment is September 24 at 11am with Tasha Brown. ",
                       "speech": said[0]}]


def test_a_note_on_its_own_line_goes_with_the_next_words(toned):
    said, s = _stream(["[pleased]\n", "Your next appointment is September 24 at 11am "
                       "with Tasha Brown. "])
    assert said == ["[pleased] Your next appointment is September 24 at 11am with Tasha Brown. "]
    assert s.text == "Your next appointment is September 24 at 11am with Tasha Brown. "


def test_a_plain_sentence_streams_as_before(toned):
    events = chief._stream_piece_events(P + "Hello. ", chief._ActionTagFilter())
    assert events == [{"type": "delta", "text": "Hello. ", "checked": True}]


def test_the_preview_compares_words_and_keeps_the_note(toned):
    out = []
    evidence = {"context:open_invoices": {"kind": "context", "complete": True, "text": json.dumps([
        {"invoice_number": "INV-2026-031", "client_name": "Maria Lopez", "amount": 400,
         "status": "sent", "due_date": "2026-09-20"}])}}
    fact = "Maria Lopez still owes $400 on INV-2026-031. "
    b = VoiceBridge(out.append, truth.stream_prover(evidence), chief._SentenceStreamer, prefix=P)
    b._preview(P + fact)
    b.main(P + "[steady] " + fact)       # the same fact: left out, its note kept
    b.main(P + "Want me to send a reminder? ")
    assert out == [P + fact, P + "[steady] Want me to send a reminder? "]
    assert b.stitch(fact + "Want me to send a reminder?") == fact + "Want me to send a reminder?"


# ── 2. the tail of the reply ─────────────────────────────────────────

def test_the_tail_is_said_with_its_notes_where_chief_put_them(toned):
    toned.records.append(REPLY)
    start = len("Monica paid her invoice this morning. ")
    assert chief_tone.tail_speech(CLEAN, start) == (
        "[breathe] [steady] But two others are still out, about eleven hundred dollars "
        "between them.")


def test_a_reply_that_never_streamed_starts_with_its_opening_note(toned):
    toned.records.append(REPLY)
    assert chief_tone.tail_speech(CLEAN, 0) == REPLY


def test_a_tail_with_no_note_of_its_own_carries_the_tone_before_it(toned):
    toned.records.append("[pleased] Monica paid. She also booked Friday.")
    assert chief_tone.tail_speech("Monica paid. She also booked Friday.", len("Monica paid. ")) is None


def test_a_rewritten_tail_is_said_steady(toned):
    toned.records.append(REPLY)
    final = ("Monica paid her invoice this morning.\n\nI couldn't confirm the rest of that "
             "from your records, so I stopped there.")
    start = len("Monica paid her invoice this morning.")
    assert chief_tone.tail_speech(final, start) == (
        "[steady] I couldn't confirm the rest of that from your records, so I stopped there.")


def test_no_notes_without_a_toned_turn():
    assert chief_tone.tail_speech(CLEAN, 0, chief_tone.ToneTurn()) is None
    assert chief_tone.tail_speech(CLEAN, 0, chief_tone.ToneTurn(enabled=True)) is None


def test_the_stream_sends_words_to_the_screen_and_notes_to_the_voice(monkeypatch):
    async def fake_chat(req, session):
        turn = chief_tone.TURN.get()
        turn.enabled = True                       # the prompt asked for notes
        sink = chief._STREAM_SINK.get()
        sink(P + "[pleased] Monica paid her invoice this morning. ")
        return {"response": chief_tone.take(REPLY), "actions_taken": []}

    async def run():
        monkeypatch.setattr(chief, "chief_chat", fake_chat)
        response = await chief.chief_chat_stream(
            chief.ChatRequest(business_id="fixture", message="Any news?", tone_notes=True), None)
        frames = [f async for f in response.body_iterator]
        return [json.loads(f.removeprefix("data: ").strip()) for f in frames if f.startswith("data:")]

    events = asyncio.run(run())
    deltas = [e for e in events if e["type"] == "delta"]
    assert "".join(d["text"] for d in deltas) == CLEAN
    assert deltas[0]["speech"] == "[pleased] Monica paid her invoice this morning. "
    assert deltas[1]["speech"].startswith("[breathe] [steady] But two others")
    assert events[-1]["payload"]["response"] == CLEAN


# ── 3. the speech proxy ──────────────────────────────────────────────

@pytest.fixture
def tone_env(env, monkeypatch):
    monkeypatch.setattr(wp, "INWORLD_TONE_MONTHLY_CHARS", 200000)
    monkeypatch.setattr(wp, "_tone_chars_this_month", lambda: 0)
    return env


def test_a_note_puts_the_piece_on_the_tone_model_in_inworlds_words(tone_env):
    _speak({"text": "[pleased] Monica paid her $1,200 invoice.", "voice": "iw:grace"})
    body = _inworld_sent()[0]["json"]
    assert body["modelId"] == "inworld-tts-2"
    assert body["text"].startswith("[say upbeat and pleased] Monica paid her")
    assert "$" not in body["text"]
    assert body["audioConfig"]["speakingRate"] == 1.1
    assert [row["model"] for row in tone_env] == ["inworld-tts-2"]
    assert tone_env[0]["input_tokens"] == len(body["text"])


def test_the_turn_reads_as_kevin_heard_it(tone_env):
    _speak({"text": "[breathe] [steady] But two clients haven't paid.", "voice": "iw:elijah"})
    body = _inworld_sent()[0]["json"]
    assert body["modelId"] == "inworld-tts-2"
    assert body["text"] == "[breathe] [steady] But two clients haven't paid."


def test_a_breath_alone_stays_on_flash(tone_env):
    _speak({"text": "[breathe] One more thing.", "voice": "iw:grace"})
    body = _inworld_sent()[0]["json"]
    assert body["modelId"] == "inworld-tts-2-flash"
    assert body["text"] == "[breathe] One more thing."


def test_past_the_monthly_cap_notes_drop_and_flash_speaks(tone_env, monkeypatch):
    monkeypatch.setattr(wp, "_tone_chars_this_month", lambda: 200000)
    _speak({"text": "[pleased] Monica paid. [breathe] [steady] Two are out.", "voice": "iw:grace"})
    body = _inworld_sent()[0]["json"]
    assert body["modelId"] == "inworld-tts-2-flash"
    assert body["text"] == "Monica paid. [breathe] Two are out."


def test_the_cap_reads_the_month_it_is_counting(monkeypatch):
    # The real counter, not a stand-in: a "+00:00" month start reads as a
    # space in the query string and PostgREST answers 400 (measured
    # 2026-10-18), which would leave the cap at zero forever.
    paths = []

    def get(path, **k):
        paths.append(path)
        return [{"input_tokens": 1500}, {"input_tokens": 500}]
    monkeypatch.setattr(wp.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(wp, "_TONE_CHARS_CACHE", {"at": 0.0, "month": "", "chars": 0})
    assert wp._tone_chars_this_month() == 2000
    assert "+" not in paths[0] and "T00:00:00Z" in paths[0]
    assert "model=eq.inworld-tts-2&" in paths[0]


def test_a_failed_read_keeps_the_last_count_instead_of_zero(monkeypatch):
    month_key, _ = wp._month_bounds()
    monkeypatch.setattr(wp, "_TONE_CHARS_CACHE", {"at": 0.0, "month": month_key, "chars": 250000})
    monkeypatch.setattr(wp.sb_clients, "sb_get_as_service", lambda path, **k: None)
    monkeypatch.setattr(wp, "INWORLD_TONE_MONTHLY_CHARS", 200000)
    assert wp._tone_chars_this_month() == 250000
    assert wp._tone_allowed() is False


def test_every_other_voice_reads_the_words_alone(tone_env):
    _speak({"text": "[pleased] Monica paid. [breathe] [steady] Two are out.", "voice": "nova"})
    assert _openai_sent()[0]["json"]["input"] == "Monica paid. Two are out."
    assert not _inworld_sent()


def test_a_tone_model_miss_tries_the_same_voice_on_flash_before_nova(tone_env, monkeypatch):
    answers = iter([_Upstream(status=400), _Upstream(lines=[_line(b"\x01\x02" * 4)])])

    class _C(_Client):
        async def send(self, req, stream=False):
            if req["url"] == wp.INWORLD_TTS_URL:
                return next(answers)
            return await super().send(req, stream)
    monkeypatch.setattr(wp.httpx, "AsyncClient", _C)
    monkeypatch.setattr(wp, "_TTS_HTTP", None)
    resp = _speak({"text": "[pleased] Monica paid.", "voice": "iw:grace"})
    sent = _inworld_sent()
    assert [r["json"]["modelId"] for r in sent] == ["inworld-tts-2", "inworld-tts-2-flash"]
    assert sent[1]["json"]["text"] == "Monica paid."
    assert b"".join(resp.chunks) == b"\x01\x02" * 4
    assert not _openai_sent()


def test_notes_alone_are_not_something_to_say(tone_env):
    with pytest.raises(wp.HTTPException):
        _speak({"text": "[pleased] [breathe]", "voice": "iw:grace"})


# ── 4. who gets the rules ────────────────────────────────────────────

def _block(monkeypatch, *, mode="on", asked=True, owner=False, turn=True):
    monkeypatch.setenv("CHIEF_TONE_NOTES", mode)

    async def is_owner(client, biz):
        return owner
    monkeypatch.setattr(chief, "_is_platform_owner_biz", is_owner)
    t = chief_tone.ToneTurn() if turn else None
    token = chief_tone.TURN.set(t)
    try:
        block = asyncio.run(chief._tone_notes_block(
            SimpleNamespace(tone_notes=asked), None, {"owner_id": "x"}))
    finally:
        chief_tone.TURN.reset(token)
    return block, t


def test_the_rules_go_to_a_featured_voice_turn_when_the_switch_is_on(monkeypatch):
    block, t = _block(monkeypatch)
    assert block == chief_tone.PROMPT_BLOCK and t.enabled
    assert "[pleased]" in block and "[breathe] [steady]" in block


@pytest.mark.parametrize("kw", [
    {"mode": "off"},                 # the default
    {"asked": False},                # Nova, ElevenLabs: notes would be wasted
    {"turn": False},                 # the plain endpoint cannot carry them
    {"mode": "owner", "owner": False},
])
def test_no_rules_otherwise(monkeypatch, kw):
    block, t = _block(monkeypatch, **kw)
    assert block == ""
    assert t is None or not t.enabled


def test_owner_mode_is_the_platform_owner_only(monkeypatch):
    block, _ = _block(monkeypatch, mode="owner", owner=True)
    assert block == chief_tone.PROMPT_BLOCK


def test_the_switch_defaults_off(monkeypatch):
    monkeypatch.delenv("CHIEF_TONE_NOTES", raising=False)
    assert chief_tone.mode() == "off"
    monkeypatch.setenv("CHIEF_TONE_NOTES", "loud")
    assert chief_tone.mode() == "off"
