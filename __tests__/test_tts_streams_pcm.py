"""
test_tts_streams_pcm.py — the voice latency arc (2026-09-08).

Two things changed in /ai/tts/speak and both are invisible in a browser
until the audio is wrong:

1. The standard voice is gpt-4o-mini-tts. Every client that ever saved
   "tts-1" in localStorage keeps sending that name; the alias must land
   on the new model, and HD must stay a distinct choice.
2. A client may ask for `format: "pcm"` and get raw s16le/24 kHz bytes
   with an `audio/pcm` Content-Type, so it can schedule audio as the
   bytes arrive. A client that says nothing must still get mp3 — KAI,
   the mobile app and the voice preview never learned the new word.

The endpoint is exercised end to end with a fake httpx client so the
JSON we send OpenAI (model, response_format) and the response headers
are asserted, not assumed.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402

import whisper_proxy as wp  # noqa: E402


# ── pure resolvers ───────────────────────────────────────────────────

@pytest.mark.parametrize("requested,expected", [
    (None, "gpt-4o-mini-tts"),
    ("", "gpt-4o-mini-tts"),
    ("tts-1", "gpt-4o-mini-tts"),          # the saved legacy name
    ("gpt-4o-mini-tts", "gpt-4o-mini-tts"),
    ("tts-1-hd", "tts-1-hd"),              # HD stays its own choice
    ("gpt-4o-mini-transcribe", "gpt-4o-mini-tts"),  # wrong family → default
    ("eleven_turbo_v2_5", "gpt-4o-mini-tts"),
])
def test_resolve_tts_model(requested, expected):
    assert wp.resolve_tts_model(requested) == expected


@pytest.mark.parametrize("requested,expected", [
    (None, "mp3"),
    ("", "mp3"),
    ("mp3", "mp3"),
    ("pcm", "pcm"),
    ("PCM", "pcm"),
    ("wav", "mp3"),        # not offered → the safe historical contract
    ("opus", "mp3"),
])
def test_resolve_tts_format(requested, expected):
    assert wp.resolve_tts_format(requested) == expected


def test_pcm_headers_carry_decoder_parameters():
    h = wp.tts_response_headers("pcm")
    assert h["X-Audio-Sample-Rate"] == "24000"
    assert h["X-Audio-Channels"] == "1"
    assert h["X-Audio-Encoding"] == "s16le"
    assert h["Cache-Control"] == "no-store"
    assert "X-Audio-Sample-Rate" not in wp.tts_response_headers("mp3")


# ── the endpoint, end to end against a fake OpenAI ───────────────────

class _FakeUpstream:
    status_code = 200

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    async def aiter_bytes(self, chunk_size=4096):
        for c in self._chunks:
            yield c

    async def aclose(self):
        self.closed = True


class _FakeClient:
    """Records the request OpenAI would have received."""
    sent: dict = {}

    def __init__(self, *a, **k):
        self.closed = False

    def build_request(self, method, url, headers=None, json=None):
        _FakeClient.sent = {"method": method, "url": url, "headers": headers, "json": json}
        return _FakeClient.sent

    async def send(self, req, stream=False):
        return _FakeUpstream([b"\x00\x01" * 1024, b"\x02\x03" * 512])

    async def aclose(self):
        self.closed = True


@pytest.fixture
def tts_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(wp.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(wp.rate_limit, "allow", lambda *a, **k: True)
    monkeypatch.setattr(wp.rate_limit, "client_ip", lambda r: "203.0.113.1")

    async def _noop(**k): ...
    monkeypatch.setattr(wp, "log_api_usage", _noop)
    _FakeClient.sent = {}
    return _FakeClient


async def _drain(resp) -> bytes:
    out = b""
    async for chunk in resp.body_iterator:
        out += chunk
    return out


def _speak(body: dict):
    req = wp.TTSRequest(**body)
    resp = asyncio.run(wp.text_to_speech(req, request=object(), user=None))
    return resp


def test_default_request_is_mp3_on_the_new_model(tts_env):
    resp = _speak({"text": "Hello there.", "voice": "nova"})
    sent = tts_env.sent["json"]
    assert sent["model"] == "gpt-4o-mini-tts"
    assert sent["response_format"] == "mp3"
    assert resp.media_type == "audio/mpeg"
    assert "x-audio-sample-rate" not in {k.lower() for k in resp.headers.keys()}


def test_legacy_tts1_name_lands_on_mini_tts(tts_env):
    _speak({"text": "Hello there.", "voice": "nova", "model": "tts-1"})
    assert tts_env.sent["json"]["model"] == "gpt-4o-mini-tts"


def test_hd_is_still_hd(tts_env):
    _speak({"text": "Hello there.", "voice": "nova", "model": "tts-1-hd"})
    assert tts_env.sent["json"]["model"] == "tts-1-hd"


def test_pcm_request_streams_raw_pcm_with_decoder_headers(tts_env):
    resp = _speak({"text": "You are owed $2,345.", "voice": "nova", "format": "pcm"})
    sent = tts_env.sent["json"]
    assert sent["response_format"] == "pcm"
    # Money is still spelled out at the wire, whatever the format.
    assert "$" not in sent["input"]
    assert resp.media_type == "audio/pcm"
    assert resp.headers["x-audio-sample-rate"] == "24000"
    assert resp.headers["x-audio-encoding"] == "s16le"
    # The bytes pass through untouched, in order.
    body = asyncio.run(_drain(resp))
    assert body == b"\x00\x01" * 1024 + b"\x02\x03" * 512


def test_unknown_format_falls_back_to_mp3(tts_env):
    resp = _speak({"text": "Hello.", "voice": "nova", "format": "flac"})
    assert tts_env.sent["json"]["response_format"] == "mp3"
    assert resp.media_type == "audio/mpeg"


def test_elevenlabs_output_format_matches_the_wire_format():
    assert wp._EL_OUTPUT_FORMATS["pcm"] == "pcm_24000"
    assert wp._EL_OUTPUT_FORMATS["mp3"] == "mp3_44100_128"
