"""
voice_stream.py — streaming speech-to-text for the call (voice latency arc, 2026-09-08)

The batch path (/ai/whisper/transcribe) hears nothing until the browser's
silence detector gives up, uploads a blob, and waits for a transcript. The
practitioner sits through the tail AND the round trip on every turn. This
endpoint keeps a WebSocket open for the whole call, forwards microphone
audio to OpenAI's Realtime transcription session as it is spoken, lets the
server's voice-activity detector decide when the sentence ended, and hands
the transcript back the moment it exists — typically well under a second
after the last word.

Why a relay and not the browser talking to OpenAI: the API key never
leaves Railway, the same rate guard and metering as the batch path apply,
and a browser cannot set headers on a WebSocket anyway.

WS /ai/voice/stream
  1. client → text  {"type":"hello","token":"<supabase jwt>",
                     "silence_ms":900,"language":"en","business_id":"…"}
  2. server → text  {"type":"ready"}
  3. client → binary frames: signed 16-bit little-endian mono PCM at 24 kHz,
              any size (100 ms per frame is a good rhythm)
     client → text  {"type":"commit"}   the practitioner stopped the mic by hand
  4. server → text  {"type":"speech_started"} · {"type":"speech_stopped"}
                    {"type":"delta","text":" word"}
                    {"type":"final","text":"the whole utterance"}
                    {"type":"error","message":"…"}
                    {"type":"closed","reason":"…"}   then the socket closes

The client keeps sending frames (silence included) until it has the final
it is waiting for — the server VAD needs to HEAR the pause to end the turn.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import rate_limit
from api_usage_logger import log_api_usage
from auth_supabase import _verify_token
from whisper_proxy import _owns_business

router = APIRouter()
logger = logging.getLogger("voice_stream")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] voice_stream: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

# Rehearsed 2026-09-08 with the live key: the GA session shape on the
# transcription intent, no beta header (the beta shape is disabled —
# `beta_api_shape_disabled`). Transcript landed 0.60 s after speech_stopped.
OPENAI_RT_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
RT_MODEL = "gpt-4o-mini-transcribe"
# $0.003 / minute of audio (same model as the batch path).
RT_CENTS_PER_MIN = 0.3
PCM_BYTES_PER_SEC = 24000 * 2
DEFAULT_SILENCE_MS = 900
MIN_SILENCE_MS, MAX_SILENCE_MS = 300, 2000
HELLO_TIMEOUT_S = 8.0
UPSTREAM_OPEN_TIMEOUT_S = 10.0
# A call can sit quiet while Chief talks; only a truly abandoned socket
# (no frames at all for this long) is reaped.
IDLE_TIMEOUT_S = 600.0


# ═══════════════════════════════════════════════════════════════════════
# Pure pieces — tested without a socket
# ═══════════════════════════════════════════════════════════════════════

def parse_hello(raw: str) -> Dict[str, Any]:
    """The client's opening message. Raises ValueError on anything
    that is not a well-formed hello with a token."""
    try:
        ev = json.loads(raw)
    except Exception as e:
        raise ValueError(f"not json: {e}")
    if not isinstance(ev, dict) or ev.get("type") != "hello":
        raise ValueError("first message must be a hello")
    token = ev.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("hello needs a token")
    silence = ev.get("silence_ms", DEFAULT_SILENCE_MS)
    try:
        silence = int(silence)
    except Exception:
        silence = DEFAULT_SILENCE_MS
    language = ev.get("language")
    if not (isinstance(language, str) and 2 <= len(language) <= 5):
        language = None
    biz = ev.get("business_id")
    if not (isinstance(biz, str) and biz.strip()):
        biz = None
    return {"token": token.strip(), "silence_ms": silence,
            "language": language, "business_id": biz}


def session_config(silence_ms: Optional[int], language: Optional[str] = None) -> Dict[str, Any]:
    """The session.update we send upstream. The silence tail is clamped so
    a client can neither cut mid-word nor stretch a turn past patience."""
    s = max(MIN_SILENCE_MS, min(int(silence_ms or DEFAULT_SILENCE_MS), MAX_SILENCE_MS))
    transcription: Dict[str, Any] = {"model": RT_MODEL}
    if language:
        transcription["language"] = language
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "noise_reduction": {"type": "near_field"},
                    "transcription": transcription,
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": s,
                    },
                }
            },
        },
    }


def map_event(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate an upstream event into the small vocabulary the browser
    speaks. None = nothing the client needs to hear."""
    t = ev.get("type") or ""
    if t == "session.updated":
        return {"type": "ready"}
    if t == "input_audio_buffer.speech_started":
        return {"type": "speech_started"}
    if t == "input_audio_buffer.speech_stopped":
        return {"type": "speech_stopped"}
    if t == "conversation.item.input_audio_transcription.delta":
        return {"type": "delta", "text": ev.get("delta") or ""}
    if t == "conversation.item.input_audio_transcription.completed":
        return {"type": "final", "text": (ev.get("transcript") or "").strip()}
    if t == "conversation.item.input_audio_transcription.failed":
        err = ev.get("error") or {}
        return {"type": "error", "message": err.get("message") or "transcription failed"}
    if t == "error":
        err = ev.get("error") or {}
        code = err.get("code") or ""
        # A hand-stop after the VAD already closed the turn commits an
        # empty buffer. Nothing is lost — the final is on its way.
        if code == "input_audio_buffer_commit_empty":
            return None
        return {"type": "error", "message": err.get("message") or "voice stream error", "code": code}
    return None


def cost_cents_for(pcm_bytes: int) -> float:
    minutes = pcm_bytes / PCM_BYTES_PER_SEC / 60.0
    return round(minutes * RT_CENTS_PER_MIN, 4)


# ═══════════════════════════════════════════════════════════════════════
# The relay
# ═══════════════════════════════════════════════════════════════════════

async def _say_closed(ws: WebSocket, reason: str) -> None:
    try:
        await ws.send_text(json.dumps({"type": "closed", "reason": reason}))
    except Exception:
        pass


async def _close(ws: WebSocket, code: int, reason: str) -> None:
    await _say_closed(ws, reason)
    try:
        await ws.close(code=code, reason=reason[:120])
    except Exception:
        pass


@router.websocket("/ai/voice/stream")
async def voice_stream(ws: WebSocket) -> None:
    await ws.accept()
    ip = rate_limit.client_ip(ws)
    if not rate_limit.allow("voice", ip):
        await _close(ws, 4429, "Too many voice requests — give it a moment.")
        return
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        await _close(ws, 4500, "voice is not configured on the server")
        return

    try:
        hello = parse_hello(await asyncio.wait_for(ws.receive_text(), HELLO_TIMEOUT_S))
    except WebSocketDisconnect:
        return
    except Exception as e:
        await _close(ws, 4400, f"expected hello: {e}")
        return
    try:
        user = _verify_token(hello["token"])
    except Exception:
        await _close(ws, 4401, "sign in to use voice")
        return
    biz = hello["business_id"]
    metered_biz = biz if (biz and _owns_business(user.id, biz)) else None

    sent_bytes = 0
    finals = 0
    t0 = time.time()
    reason = "done"
    try:
        async with websockets.connect(
            OPENAI_RT_URL,
            additional_headers={"Authorization": f"Bearer {key}"},
            max_size=None,
            open_timeout=UPSTREAM_OPEN_TIMEOUT_S,
        ) as up:
            await up.send(json.dumps(session_config(hello["silence_ms"], hello["language"])))

            async def pump_client() -> str:
                nonlocal sent_bytes
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), IDLE_TIMEOUT_S)
                    except asyncio.TimeoutError:
                        return "idle"
                    if msg.get("type") == "websocket.disconnect":
                        return "client-left"
                    b = msg.get("bytes")
                    if b:
                        sent_bytes += len(b)
                        await up.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(b).decode("ascii"),
                        }))
                        continue
                    text = msg.get("text")
                    if not text:
                        continue
                    try:
                        ev = json.loads(text)
                    except Exception:
                        continue
                    if isinstance(ev, dict) and ev.get("type") == "commit":
                        await up.send(json.dumps({"type": "input_audio_buffer.commit"}))

            async def pump_upstream() -> str:
                nonlocal finals
                async for raw in up:
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    out = map_event(ev if isinstance(ev, dict) else {})
                    if out is None:
                        continue
                    if out["type"] == "final":
                        finals += 1
                    await ws.send_text(json.dumps(out))
                return "upstream-closed"

            client_task = asyncio.create_task(pump_client())
            upstream_task = asyncio.create_task(pump_upstream())
            done, pending = await asyncio.wait(
                {client_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            for d in done:
                exc = d.exception()
                if exc is not None:
                    raise exc
                reason = d.result()
    except WebSocketDisconnect:
        reason = "client-left"
    except Exception as e:
        reason = f"error: {type(e).__name__}"
        logger.warning(f"voice stream ended with {type(e).__name__}: {e}")
        await _say_closed(ws, "voice stream error")
    finally:
        duration_ms = int((time.time() - t0) * 1000)
        logger.info(
            f"voice stream {reason}: audio={sent_bytes / PCM_BYTES_PER_SEC:.1f}s "
            f"finals={finals} wall={duration_ms}ms user={user.id} biz={metered_biz}")
        if sent_bytes:
            try:
                await log_api_usage(
                    endpoint="/ai/voice/stream", model=RT_MODEL,
                    input_tokens=0, output_tokens=0,
                    business_id=metered_biz, user_id=user.id,
                    duration_ms=duration_ms,
                    cost_cents_override=cost_cents_for(sent_bytes))
            except Exception:
                pass
        if reason != "client-left":
            await _close(ws, 1000, reason)
