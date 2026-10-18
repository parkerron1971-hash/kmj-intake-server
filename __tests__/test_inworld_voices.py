"""
test_inworld_voices.py — the featured voices (Kevin's pick, 2026-10-17).

Grace, Elijah, Jessica and Reed are Inworld voices offered to every
practitioner, included like Nova. What has to hold, none of which a
browser shows until the audio is wrong or silent:

1. "iw:<slug>" reaches Inworld with the right voice, model, speed and
   wire encoding — and PCM arrives headerless and sample-aligned.
2. Every miss speaks as Nova: an unknown slug, no key, Inworld refusing,
   timing out, or erroring before the first audio. Never silence.
3. The picker gets slugs and words, never Inworld's voice ids.
4. The usage row is the included endpoint at the Flash price.

The endpoint runs end to end against a fake httpx client that answers
like Inworld (one JSON object per line) or like OpenAI (raw bytes).
"""
from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import httpx  # noqa: E402
import pytest  # noqa: E402

import api_usage_logger  # noqa: E402
import whisper_proxy as wp  # noqa: E402


def _line(audio: bytes) -> str:
    return json.dumps({"result": {"audioContent": base64.b64encode(audio).decode()}})


class _Upstream:
    def __init__(self, status=200, lines=(), chunks=()):
        self.status_code = status
        self._lines = list(lines)
        self._chunks = list(chunks)
        self.closed = False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aiter_bytes(self, chunk_size=4096):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b'{"code": 5, "message": "Unknown voice"}'

    async def aclose(self):
        self.closed = True


class _Client:
    """Answers Inworld from `inworld`, OpenAI with fixed bytes, and keeps
    every request it was handed."""
    inworld: object = None
    sent: list = []

    def __init__(self, *a, **k):
        self.is_closed = False

    def build_request(self, method, url, headers=None, json=None):
        req = {"method": method, "url": url, "headers": headers, "json": json}
        _Client.sent.append(req)
        return req

    async def send(self, req, stream=False):
        if req["url"] == wp.INWORLD_TTS_URL:
            if isinstance(_Client.inworld, Exception):
                raise _Client.inworld
            return _Client.inworld
        return _Upstream(chunks=[b"NOVA"])

    async def aclose(self):
        self.is_closed = True


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("INWORLD_API_KEY", "Basic aXctdGVzdA==")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("TTS_KEEP_WARM", "off")
    monkeypatch.setattr(wp.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(wp, "_TTS_HTTP", None)
    wp._PHRASE_AUDIO.clear()
    wp._PHRASE_AUDIO_BYTES["n"] = 0
    monkeypatch.setattr(wp.rate_limit, "allow", lambda *a, **k: True)
    monkeypatch.setattr(wp.rate_limit, "client_ip", lambda r: "203.0.113.1")
    logged = []

    async def _log(**k):
        logged.append(k)
    monkeypatch.setattr(wp, "log_api_usage", _log)
    _Client.sent = []
    _Client.inworld = _Upstream(lines=[_line(b"\x01\x02" * 8), "", _line(b"\x03\x04" * 8)])
    return logged


def _speak(body: dict):
    """Answer and read the audio in ONE event loop, as the server does.
    The Inworld path reads its first slice before answering; a second
    asyncio.run would find that stream already closed by the first
    loop's shutdown."""
    async def go():
        resp = await wp.text_to_speech(wp.TTSRequest(**body), request=object(), user=None)
        chunks = []
        if hasattr(resp, "body_iterator"):
            async for c in resp.body_iterator:
                chunks.append(c)
        else:
            chunks.append(resp.body)
        return resp, chunks
    resp, chunks = asyncio.run(go())
    resp.chunks = chunks
    return resp


def _drain(resp) -> bytes:
    return b"".join(resp.chunks)


def _inworld_sent():
    return [r for r in _Client.sent if r["url"] == wp.INWORLD_TTS_URL]


def _openai_sent():
    return [r for r in _Client.sent if r["url"] == wp.OPENAI_TTS_URL]


# ── routing ──────────────────────────────────────────────────────────

def test_grace_reaches_inworld_with_her_voice_speed_and_flash(env):
    resp = _speak({"text": "You are owed $2,345.", "voice": "iw:grace"})
    sent = _inworld_sent()[0]
    body = sent["json"]
    assert body["voiceId"] == wp.INWORLD_VOICES["grace"].voice_id
    assert body["modelId"] == "inworld-tts-2-flash"
    assert body["audioConfig"]["speakingRate"] == 1.1
    assert body["audioConfig"]["audioEncoding"] == "MP3"
    # The key goes out as Inworld's Basic credential, prefix not doubled.
    assert sent["headers"]["Authorization"] == "Basic aXctdGVzdA=="
    # Money is spelled out at the wire, the same as every other voice.
    assert "$" not in body["text"]
    assert resp.media_type == "audio/mpeg"
    assert _drain(resp) == b"\x01\x02" * 8 + b"\x03\x04" * 8
    assert not _openai_sent()


def test_grace_at_normal_speed_is_the_same_voice_slower(env):
    _speak({"text": "Hello there.", "voice": "iw:grace-normal"})
    body = _inworld_sent()[0]["json"]
    assert body["voiceId"] == wp.INWORLD_VOICES["grace"].voice_id
    assert body["audioConfig"]["speakingRate"] == 1.0


def test_two_speeds_of_one_voice_never_share_a_kept_phrase(env):
    _speak({"text": "On it.", "voice": "iw:grace"})
    _Client.sent = []
    _speak({"text": "On it.", "voice": "iw:grace-normal"})
    assert _inworld_sent(), "1.0x must not be served the 1.1x audio from memory"


def test_stock_voices_speak_at_normal_speed(env):
    _speak({"text": "Hello there.", "voice": "iw:jessica"})
    body = _inworld_sent()[0]["json"]
    assert body["voiceId"] == "Jessica"
    assert body["audioConfig"]["speakingRate"] == 1.0


def test_slug_is_case_and_space_tolerant(env):
    _speak({"text": "Hello there.", "voice": "iw: Elijah "})
    assert _inworld_sent()[0]["json"]["voiceId"] == wp.INWORLD_VOICES["elijah"].voice_id


def test_pcm_is_headerless_and_sample_aligned(env):
    # Slices of 3 and 5 bytes: the odd byte must wait for the next slice,
    # or every sample after it is shifted into noise.
    _Client.inworld = _Upstream(lines=[_line(b"\x0a\x0b\x0c"), _line(b"\x0d\x0e\x0f\x10\x11")])
    resp = _speak({"text": "Hello there.", "voice": "iw:reed", "format": "pcm"})
    assert _inworld_sent()[0]["json"]["audioConfig"]["audioEncoding"] == "PCM"
    assert _inworld_sent()[0]["json"]["audioConfig"]["sampleRateHertz"] == 24000
    assert resp.media_type == "audio/pcm"
    assert resp.headers["x-audio-sample-rate"] == "24000"
    assert _drain(resp) == b"\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11"
    assert all(len(c) % 2 == 0 for c in resp.chunks)


# ── every miss speaks as Nova ────────────────────────────────────────

def test_unknown_slug_speaks_as_nova(env):
    resp = _speak({"text": "Hello there.", "voice": "iw:nobody"})
    assert not _inworld_sent()
    assert _openai_sent()[0]["json"]["voice"] == "nova"
    assert _drain(resp) == b"NOVA"


def test_no_key_speaks_as_nova(env, monkeypatch):
    monkeypatch.delenv("INWORLD_API_KEY")
    resp = _speak({"text": "Hello there.", "voice": "iw:grace"})
    assert not _inworld_sent()
    assert _drain(resp) == b"NOVA"


def test_inworld_refusing_speaks_as_nova(env):
    _Client.inworld = _Upstream(status=404)
    resp = _speak({"text": "Hello there.", "voice": "iw:grace"})
    assert _Client.inworld.closed
    assert _openai_sent()[0]["json"]["voice"] == "nova"
    assert _drain(resp) == b"NOVA"


def test_inworld_timing_out_speaks_as_nova(env):
    _Client.inworld = httpx.ConnectTimeout("slow")
    resp = _speak({"text": "Hello there.", "voice": "iw:grace"})
    assert _drain(resp) == b"NOVA"


def test_error_before_the_first_audio_speaks_as_nova(env):
    _Client.inworld = _Upstream(lines=[json.dumps({"error": {"code": 13, "message": "boom"}})])
    resp = _speak({"text": "Hello there.", "voice": "iw:grace"})
    assert _Client.inworld.closed
    assert _drain(resp) == b"NOVA"


def test_text_longer_than_inworld_takes_speaks_whole_as_nova(env):
    long = "word " * (wp.INWORLD_MAX_CHARS // 5 + 10)
    _speak({"text": long, "voice": "iw:grace"})
    assert not _inworld_sent()
    assert _openai_sent()


# ── picker + metering ────────────────────────────────────────────────

def test_picker_lists_featured_voices_by_slug_only(env):
    out = asyncio.run(wp.list_tts_voices(request=object()))["voices"]
    assert [v["id"] for v in out] == ["iw:grace", "iw:grace-normal", "iw:elijah", "iw:jessica", "iw:reed"]
    assert [v["label"] for v in out] == ["Grace", "Grace (normal speed)", "Elijah", "Jessica", "Reed"]
    flat = json.dumps(out)
    assert "design-voice" not in flat and "misty-lemon" not in flat


def test_picker_hides_featured_voices_without_a_key(env, monkeypatch):
    monkeypatch.delenv("INWORLD_API_KEY")
    assert asyncio.run(wp.list_tts_voices(request=object()))["voices"] == []


def test_usage_row_is_included_and_priced_as_flash(env):
    resp = _speak({"text": "Hello there.", "voice": "iw:grace"})
    _drain(resp)
    row = env[-1]
    assert row["endpoint"] == "/ai/tts"          # UNIT weight 0: included
    assert row["model"] == "inworld-tts-2-flash"
    assert row["input_tokens"] == len("Hello there.")
    assert api_usage_logger.MODEL_PRICING_CENTS["inworld-tts-2-flash"] == (1500.0, 0.0)
    assert api_usage_logger.provider_for("inworld-tts-2-flash") == "inworld"


def test_short_phrase_is_kept_and_served_without_inworld(env):
    first = _speak({"text": "On it.", "voice": "iw:grace"})
    _Client.sent = []
    resp = _speak({"text": "On it.", "voice": "iw:grace"})
    assert not _inworld_sent()
    assert resp.headers["x-tts-cache"] == "hit"
    # The whole phrase was kept, not just its first slice.
    assert _drain(resp) == _drain(first) == b"\x01\x02" * 8 + b"\x03\x04" * 8


def test_stream_cut_short_is_not_kept_as_the_phrase(env):
    _Client.inworld = _Upstream(lines=[_line(b"\x01\x02"), json.dumps({"error": {"code": 14}})])
    _speak({"text": "On it.", "voice": "iw:grace"})
    _Client.sent = []
    _Client.inworld = _Upstream(lines=[_line(b"\x01\x02"), _line(b"\x03\x04")])
    _speak({"text": "On it.", "voice": "iw:grace"})
    assert _inworld_sent(), "a partial phrase must not be served from memory"
