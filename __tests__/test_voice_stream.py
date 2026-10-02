"""
test_voice_stream.py — the streaming speech-to-text relay (voice latency arc 9/08).

The relay is thin on purpose; what can go wrong is the vocabulary at each
end. So: the hello is parsed strictly (a token is required — the batch
path requires a signed-in user and so does this one), the upstream session
config carries a CLAMPED silence tail, upstream events map onto the six
words the browser knows (and the one harmless error is swallowed), the
meter prices audio by the minute, and the whole thing relays end to end
against a fake OpenAI socket through Starlette's WebSocket test client.
"""
from __future__ import annotations

import asyncio
import base64
import json
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import voice_stream as vs  # noqa: E402


# ── hello ────────────────────────────────────────────────────────────

def test_hello_requires_type_and_token():
    with pytest.raises(ValueError):
        vs.parse_hello("not json")
    with pytest.raises(ValueError):
        vs.parse_hello(json.dumps({"type": "commit"}))
    with pytest.raises(ValueError):
        vs.parse_hello(json.dumps({"type": "hello"}))
    with pytest.raises(ValueError):
        vs.parse_hello(json.dumps({"type": "hello", "token": "   "}))


def test_hello_fields_are_normalised():
    h = vs.parse_hello(json.dumps({
        "type": "hello", "token": " jwt ", "silence_ms": "750",
        "language": "en", "business_id": "biz-1"}))
    assert h == {"token": "jwt", "silence_ms": 750, "language": "en", "business_id": "biz-1"}
    h = vs.parse_hello(json.dumps({"type": "hello", "token": "jwt", "silence_ms": "x",
                                   "language": 7, "business_id": ""}))
    assert h["silence_ms"] == vs.DEFAULT_SILENCE_MS
    assert h["language"] is None and h["business_id"] is None


# ── session config ───────────────────────────────────────────────────

@pytest.mark.parametrize("asked,expected", [
    (None, vs.DEFAULT_SILENCE_MS), (0, vs.DEFAULT_SILENCE_MS),
    (100, 300), (900, 900), (5000, 2000),
])
def test_session_config_clamps_the_silence_tail(asked, expected):
    cfg = vs.session_config(asked)
    inp = cfg["session"]["audio"]["input"]
    assert cfg["type"] == "session.update"
    assert cfg["session"]["type"] == "transcription"
    assert inp["format"] == {"type": "audio/pcm", "rate": 24000}
    assert inp["turn_detection"]["type"] == "server_vad"
    assert inp["turn_detection"]["silence_duration_ms"] == expected
    assert inp["transcription"]["model"] == vs.RT_MODEL
    assert "language" not in inp["transcription"]
    assert vs.session_config(900, "en")["session"]["audio"]["input"]["transcription"]["language"] == "en"


# ── event mapping ────────────────────────────────────────────────────

@pytest.mark.parametrize("ev,expected", [
    ({"type": "session.updated"}, {"type": "ready"}),
    ({"type": "session.created"}, None),
    ({"type": "input_audio_buffer.speech_started", "audio_start_ms": 10}, {"type": "speech_started"}),
    ({"type": "input_audio_buffer.speech_stopped"}, {"type": "speech_stopped"}),
    ({"type": "input_audio_buffer.committed"}, None),
    ({"type": "conversation.item.input_audio_transcription.delta", "delta": " word"},
     {"type": "delta", "text": " word"}),
    ({"type": "conversation.item.input_audio_transcription.completed", "transcript": " Hey Chief. "},
     {"type": "final", "text": "Hey Chief."}),
    ({"type": "conversation.item.input_audio_transcription.failed", "error": {"message": "boom"}},
     {"type": "error", "message": "boom"}),
    # a hand-stop after the VAD already closed the turn — harmless
    ({"type": "error", "error": {"code": "input_audio_buffer_commit_empty", "message": "x"}}, None),
    ({"type": "error", "error": {"code": "rate_limit", "message": "slow down"}},
     {"type": "error", "message": "slow down", "code": "rate_limit"}),
    ({"type": "something.new"}, None),
    ({}, None),
])
def test_map_event(ev, expected):
    assert vs.map_event(ev) == expected


def test_cost_is_per_minute_of_audio():
    one_minute = vs.PCM_BYTES_PER_SEC * 60
    assert vs.cost_cents_for(one_minute) == pytest.approx(vs.RT_CENTS_PER_MIN)
    assert vs.cost_cents_for(0) == 0


# ── end to end against a fake OpenAI socket ──────────────────────────

class _FakeUpstream:
    """Speaks just enough Realtime: acknowledges the session, counts the
    audio it is sent, and on commit returns speech_stopped + a completed
    transcript that names how many bytes it heard."""
    instances: list = []

    def __init__(self, url, **kw):
        self.url = url
        self.kw = kw
        self.sent: list = []
        self.audio_bytes = 0
        self.q: asyncio.Queue = asyncio.Queue()
        _FakeUpstream.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, raw: str):
        ev = json.loads(raw)
        self.sent.append(ev)
        t = ev.get("type")
        if t == "session.update":
            await self.q.put(json.dumps({"type": "session.created"}))
            await self.q.put(json.dumps({"type": "session.updated"}))
        elif t == "input_audio_buffer.append":
            self.audio_bytes += len(base64.b64decode(ev["audio"]))
            if self.audio_bytes == 4800:
                await self.q.put(json.dumps({"type": "input_audio_buffer.speech_started"}))
        elif t == "input_audio_buffer.commit":
            await self.q.put(json.dumps({"type": "input_audio_buffer.speech_stopped"}))
            await self.q.put(json.dumps({
                "type": "conversation.item.input_audio_transcription.delta", "delta": "heard"}))
            await self.q.put(json.dumps({
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": f"heard {self.audio_bytes} bytes"}))

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.q.get()
        if item is None:
            raise StopAsyncIteration
        return item


class _User:
    id = "user-1"
    email = "u@example.com"
    role = "authenticated"


@pytest.fixture
def relay(monkeypatch):
    _FakeUpstream.instances = []
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(vs.websockets, "connect", _FakeUpstream)
    monkeypatch.setattr(vs.rate_limit, "allow", lambda *a, **k: True)
    monkeypatch.setattr(vs, "_verify_token", lambda tok: _User() if tok == "good" else (_ for _ in ()).throw(ValueError("bad")))
    monkeypatch.setattr(vs, "_owns_business", lambda uid, biz: biz == "biz-1")
    logged: list = []

    async def _log(**k):
        logged.append(k)
    monkeypatch.setattr(vs, "log_api_usage", _log)
    app = FastAPI()
    app.include_router(vs.router)
    return TestClient(app), logged


def test_relay_end_to_end(relay):
    client, logged = relay
    with client.websocket_connect("/ai/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "hello", "token": "good", "silence_ms": 900, "business_id": "biz-1"}))
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        ws.send_bytes(b"\x00\x01" * 2400)        # 100 ms
        assert json.loads(ws.receive_text()) == {"type": "speech_started"}
        ws.send_bytes(b"\x00\x01" * 2400)
        ws.send_text(json.dumps({"type": "commit"}))
        assert json.loads(ws.receive_text()) == {"type": "speech_stopped"}
        assert json.loads(ws.receive_text()) == {"type": "delta", "text": "heard"}
        assert json.loads(ws.receive_text()) == {"type": "final", "text": "heard 9600 bytes"}
    up = _FakeUpstream.instances[0]
    assert up.url == vs.OPENAI_RT_URL
    assert up.kw["additional_headers"]["Authorization"] == "Bearer sk-test"
    assert "OpenAI-Beta" not in up.kw["additional_headers"]
    assert up.sent[0]["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 900
    # metered: 9600 bytes = 0.2 s of audio, attributed to the owned business
    assert len(logged) == 1
    row = logged[0]
    assert row["endpoint"] == "/ai/voice/stream" and row["model"] == vs.RT_MODEL
    assert row["user_id"] == "user-1" and row["business_id"] == "biz-1"
    assert row["cost_cents_override"] == pytest.approx(vs.cost_cents_for(9600))


def test_relay_rejects_a_bad_token(relay):
    client, logged = relay
    with client.websocket_connect("/ai/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "hello", "token": "bad"}))
        assert json.loads(ws.receive_text()) == {"type": "closed", "reason": "sign in to use voice"}
    assert not _FakeUpstream.instances
    assert logged == []


def test_relay_rejects_a_missing_hello(relay):
    client, _ = relay
    with client.websocket_connect("/ai/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "commit"}))
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "closed" and msg["reason"].startswith("expected hello")
    assert not _FakeUpstream.instances
