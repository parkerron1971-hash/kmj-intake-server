"""The voice output brief, server side (Dev Desk 2026-09-25): a warm
connection to the speech provider, short phrases served as audio at once,
leads a call can speak, and time to first audio logged per turn against a
1-second p95 SLO, apart from time to first token."""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import model_router as mr
import route_ledger
import voice_metrics as vm
import whisper_proxy as wp


# ── the speech provider connection ───────────────────────────────────

class _Upstream:
    status_code = 200

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    async def aiter_bytes(self, chunk_size=4096):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b""

    async def aclose(self):
        self.closed = True


class _Client:
    made = 0
    sends = 0

    def __init__(self, *a, **k):
        _Client.made += 1
        self.is_closed = False

    def build_request(self, method, url, headers=None, json=None):
        return {"url": url, "json": json}

    async def send(self, req, stream=False):
        _Client.sends += 1
        return _Upstream([b"\x01\x02" * 256, b"\x03\x04" * 128])

    async def get(self, *a, **k):
        return None

    async def aclose(self):
        self.is_closed = True


@pytest.fixture
def tts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TTS_KEEP_WARM", "off")
    monkeypatch.setattr(wp.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(wp.rate_limit, "allow", lambda *a, **k: True)
    monkeypatch.setattr(wp.rate_limit, "client_ip", lambda r: "203.0.113.1")
    logged = []

    async def _log(**k):
        logged.append(k)
    monkeypatch.setattr(wp, "log_api_usage", _log)
    monkeypatch.setattr(wp, "_TTS_HTTP", None)
    wp._PHRASE_AUDIO.clear()
    wp._PHRASE_AUDIO_BYTES["n"] = 0
    _Client.made = _Client.sends = 0
    return logged


async def _drain(resp):
    out = b""
    if hasattr(resp, "body_iterator"):
        async for c in resp.body_iterator:
            out += c
    else:
        out = resp.body
    return out


def _speak_many(bodies):
    async def go():
        outs = []
        for b in bodies:
            resp = await wp.text_to_speech(wp.TTSRequest(**b), request=object(), user=None)
            outs.append((resp, await _drain(resp)))
        return outs
    return asyncio.run(go())


def test_one_connection_serves_every_sentence_of_a_call(tts):
    outs = _speak_many([{"text": f"Sentence number {i} of a longer reply that is not a phrase at all.",
                         "format": "pcm"} for i in range(4)])
    assert _Client.made == 1 and _Client.sends == 4       # no handshake per sentence
    assert all(len(body) > 0 for _, body in outs)


def test_a_short_phrase_is_audio_at_once_the_second_time(tts):
    # Case and spacing do not change the audio; punctuation does (prosody),
    # so "On it." and "on it" are different phrases.
    outs = _speak_many([{"text": "On it.", "format": "pcm"}, {"text": "On it.", "format": "pcm"},
                        {"text": "on  it.", "format": "pcm"}])
    assert _Client.sends == 1                              # the provider spoke it once
    first, second, third = outs
    assert first[1] == second[1] == third[1]
    assert second[0].headers.get("x-tts-cache") == "hit"
    assert second[0].media_type == "audio/pcm"
    assert second[0].headers.get("x-audio-sample-rate") == "24000"
    assert len(tts) == 1                                    # a cache hit costs nothing


def test_the_cache_keys_on_voice_and_format_and_keeps_only_phrases(tts):
    _speak_many([{"text": "On it.", "format": "pcm"}, {"text": "On it.", "format": "mp3"},
                 {"text": "On it.", "voice": "alloy", "format": "pcm"}])
    assert _Client.sends == 3
    long = "This is a whole reply sentence, far too long to be treated as a phrase to keep around."
    _speak_many([{"text": long}, {"text": long}])
    assert _Client.sends == 5


def test_the_phrase_cache_is_bounded(monkeypatch):
    wp._PHRASE_AUDIO.clear()
    wp._PHRASE_AUDIO_BYTES["n"] = 0
    monkeypatch.setattr(wp, "PHRASE_AUDIO_MAX_ENTRIES", 3)
    for i in range(5):
        wp._phrase_put(("openai", "nova", "m", "pcm", f"p{i}"), b"x" * 10)
    assert len(wp._PHRASE_AUDIO) == 3 and wp._PHRASE_AUDIO_BYTES["n"] == 30
    assert ("openai", "nova", "m", "pcm", "p0") not in wp._PHRASE_AUDIO


def test_a_broken_stream_is_not_kept(tts, monkeypatch):
    class _Broken(_Upstream):
        async def aiter_bytes(self, chunk_size=4096):
            yield b"\x01\x02"
            raise RuntimeError("provider hung up")

    async def send(self, req, stream=False):
        return _Broken([])
    monkeypatch.setattr(_Client, "send", send)

    async def go():
        resp = await wp.text_to_speech(wp.TTSRequest(text="On it.", format="pcm"),
                                       request=object(), user=None)
        with pytest.raises(RuntimeError):
            await _drain(resp)
    asyncio.run(go())
    assert not wp._PHRASE_AUDIO


# ── leads a call can speak ───────────────────────────────────────────

def test_a_call_gets_a_whole_sentence_lead_or_none():
    assert mr.local_lead("action", voice=True) == "On it."
    assert mr.local_lead("confirm", voice=True) == "Okay."
    assert mr.local_lead("lookup", voice=True) == "One second."
    assert mr.local_lead("social", voice=True) == ""     # thanks is answered, not filled
    assert mr.local_lead("farewell", voice=True) == ""
    assert mr.local_lead("action") == "On it —"          # the screen keeps the dash


def test_after_a_sentence_lead_the_opening_keeps_its_capital():
    g = mr.OpenerGate("Did Maria pay?", after_lead=True)
    g.lower_after_lead = False
    out = g.feed("Sure, let me check Maria's invoices.") + g.finish()
    assert out == "Let me check Maria's invoices."


def test_a_call_turn_speaks_its_lead_and_the_opening_follows(monkeypatch):
    import chief_fast_track as cft
    import chief_of_staff as chief
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ROUTER_LOG_DB", "off")
    monkeypatch.setenv("ROUTER_KEEP_WARM", "off")
    monkeypatch.setattr(route_ledger, "_page_owner", lambda a: None)

    async def stream_text(system, messages, **k):
        await asyncio.sleep(0.7)
        yield "Sure, let me"
        yield " check Maria's invoices."
    monkeypatch.setattr(cft, "stream_text", stream_text)
    original = chief.chief_chat

    async def fake_chat(r, s):
        await cft.opener_for_turn()
        await asyncio.sleep(0.9)
        return {"response": "She paid on the 14th.", "actions_taken": []}
    chief.chief_chat = fake_chat
    try:
        async def go():
            session = SimpleNamespace(user=SimpleNamespace(id="11111111-1111-1111-1111-111111111111"))
            req = chief.ChatRequest(business_id="22222222-2222-2222-2222-222222222222",
                                    message="Did Maria pay?", client_surface="voice")
            resp = await chief.chief_chat_stream(req, session)
            evs = []
            async for f in resp.body_iterator:
                if f.startswith("data:"):
                    evs.append(json.loads(f[5:]))
            return evs
        evs = asyncio.run(go())
    finally:
        chief.chief_chat = original
    shown = "".join(e["text"] for e in evs if e["type"] == "delta")
    assert shown == "One second. Let me check Maria's invoices. She paid on the 14th."


# ── time to first audio ──────────────────────────────────────────────

USER = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
BIZ = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setenv("VOICE_LOG_DB", "off")
    import business_access
    from fastapi import HTTPException

    def assert_access(business_id, user, min_role="viewer"):
        if business_id != BIZ:
            raise HTTPException(status_code=404, detail="business not found")
        return "owner"
    monkeypatch.setattr(business_access, "assert_access", assert_access)
    vm._ACCESS_OK.clear()
    monkeypatch.setattr(vm, "WINDOW", route_ledger.SloWindow(
        metric="ttfa_ms", budget=vm.budget_ms, env="VOICE_SLO"))
    rows = []
    real = vm.record
    monkeypatch.setattr(vm, "record", lambda row: (rows.append(row), real(row)))
    return rows


def _post(**body):
    return asyncio.run(vm.report_voice_turn(vm.VoiceTurn(**body), user=USER))


def test_a_spoken_turn_is_logged_against_the_one_second_budget(report):
    out = _post(request_id="r1", business_id=BIZ, ttfa_ms=640, reply_audio_ms=1900,
                transcript_ms=180, first_text_ms=520, vad_silence_ms=900,
                first_audio="opener", engine="openai", tts_requests=3, tts_cache_hits=1)
    assert out == {"ok": True, "slo_met": True, "budget_ms": 1000}
    row = report[-1]
    assert row["business_id"] == BIZ and row["first_audio"] == "opener"
    assert row["reply_audio_ms"] == 1900                # the answer's own audio, beside it
    assert _post(ttfa_ms=1400)["slo_met"] is False


def test_the_business_must_be_the_callers(report):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _post(business_id="33333333-3333-3333-3333-333333333333", ttfa_ms=500)
    assert e.value.status_code == 404          # business_access's one answer for "no"
    with pytest.raises(HTTPException):
        _post(business_id="not-an-id", ttfa_ms=500)


def test_junk_from_the_client_is_clamped_not_stored(report):
    _post(ttfa_ms=-5, first_audio="<script>", outcome="exploded", underruns=10**9)
    row = report[-1]
    assert row["ttfa_ms"] is None and row["first_audio"] == "none"
    assert row["outcome"] == "spoken" and row["underruns"] is None
    assert row["slo_applies"] is False


def test_a_superseded_turn_is_kept_but_not_judged(report):
    _post(ttfa_ms=3000, outcome="superseded")
    assert report[-1]["slo_applies"] is False and report[-1]["slo_met"] is None


def test_the_voice_slo_pages_separately_from_the_token_slo(report, monkeypatch):
    monkeypatch.setenv("VOICE_SLO_MIN_SAMPLES", "5")
    paged = []
    monkeypatch.setattr(vm, "_page", lambda alert: paged.append(alert))
    for _ in range(4):
        _post(ttfa_ms=600)
    for _ in range(6):
        _post(ttfa_ms=1800)
    assert len(paged) == 1 and paged[0]["budget_ms"] == 1000
    assert route_ledger.WINDOW is not vm.WINDOW
    snap = vm.WINDOW.snapshot()
    assert "ttfa_p95_ms" in snap and snap["budget_ms"] == 1000


def test_voice_stats_aggregate_the_logged_turns():
    rows = [{"ttfa_ms": 300, "reply_audio_ms": 1500, "first_audio": "opener", "barge_in": False,
             "underruns": 0, "tts_requests": 3, "tts_cache_hits": 1, "slo_applies": True},
            {"ttfa_ms": 1200, "reply_audio_ms": 1200, "first_audio": "reply", "barge_in": True,
             "underruns": 2, "tts_requests": 2, "tts_cache_hits": 0, "slo_applies": True}]
    s = vm.stats_from_rows(rows)
    assert s["ttfa_p95_ms"] == 1200 and s["slo_met_pct"] == 50.0
    assert s["first_audio"] == {"opener": 1, "reply": 1}
    assert s["barge_in_rate"] == 0.5 and s["underruns"] == 2
    assert s["tts_cache_hit_rate"] == 0.2
