"""Authenticated, bounded ElevenLabs text-input stream. One socket per reply.
The browser can prepare it while Chief thinks, then send speakable phrases.
Only PCM and small status events leave the relay; the provider key stays here.
"""
import asyncio
import base64
import json
import os
import re
import time
from urllib.parse import urlencode

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import rate_limit
import whisper_proxy as tts
from auth_supabase import _verify_token

router = APIRouter()
# Inherit the configured speech handler/level; root INFO can be disabled in production.
logger = tts.logger.getChild("stream")
MAX_CHARS = 16000
MAX_FRAME = 20000
SESSION_SECONDS = 180


def enabled():
    return os.getenv("CHIEF_ELEVEN_STREAM", "on").lower() not in {"off", "false", "0"}


def parse_hello(raw):
    if len(raw) > MAX_FRAME:
        raise ValueError("hello too large")
    msg = json.loads(raw)
    if not isinstance(msg, dict) or msg.get("type") != "hello":
        raise ValueError("hello required")
    token, biz, voice = (msg.get(k) for k in ("token", "business_id", "voice"))
    if not isinstance(token, str) or not token or len(token) > 12000:
        raise ValueError("token required")
    if not isinstance(biz, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", biz):
        raise ValueError("business required")
    if not isinstance(voice, str) or not re.fullmatch(r"el:[a-zA-Z0-9_-]{1,100}", voice):
        raise ValueError("ElevenLabs voice required")
    return token, biz, voice[3:]


def upstream_url(voice):
    return "wss://api.elevenlabs.io/v1/text-to-speech/" + voice + "/stream-input?" + urlencode({
        "model_id": tts.ELEVENLABS_MODEL, "output_format": "pcm_24000",
        "auto_mode": "true", "inactivity_timeout": 60,
    })


async def relay(ws, up, business_id, user_id):
    """Read text and audio concurrently; metering cannot hold the first byte."""
    chars = 0
    submitted_at = None
    first_audio = None
    finished_input = asyncio.Event()

    async def read_text():
        nonlocal chars, submitted_at
        while True:
            raw = await asyncio.wait_for(ws.receive_text(), 60)
            if len(raw) > MAX_FRAME:
                raise ValueError("frame too large")
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                raise ValueError("invalid frame")
            if msg.get("type") == "finish":
                finished_input.set()
                await up.send(json.dumps({"text": ""}))
                return
            if msg.get("type") != "text" or not isinstance(msg.get("text"), str):
                raise ValueError("text required")
            text = msg["text"].strip()
            if not text:
                continue
            if len(text) > 4096 or chars + len(text) > MAX_CHARS:
                raise ValueError("speech limit reached")
            # The allowance was loaded during hello, before any text. Reserve
            # locally without yielding so concurrent sockets cannot reuse it.
            cap = tts.ELEVENLABS_MONTHLY_CHARS_PER_BIZ
            hit = tts._EL_CHARS_CACHE.get(business_id)
            if cap > 0 and hit and hit[2] + len(text) > cap:
                raise ValueError("voice allowance reached")
            spoken = tts.normalize_for_speech(text)
            if submitted_at is None:
                submitted_at = time.perf_counter()
            chars += len(text)
            tts._note_el_chars(business_id, len(text))
            await up.send(json.dumps({"text": spoken + " ", "flush": True}))

    async def read_audio():
        nonlocal first_audio
        async for raw in up:
            msg = json.loads(raw)
            if msg.get("error") or msg.get("message") and not msg.get("audio"):
                raise RuntimeError("speech provider rejected stream")
            if msg.get("audio"):
                audio = base64.b64decode(msg["audio"], validate=True)
                if audio:
                    if first_audio is None:
                        first_audio = time.perf_counter()
                    await ws.send_bytes(audio)
            if msg.get("isFinal"):
                if not finished_input.is_set():
                    raise RuntimeError("speech provider ended before input")
                await ws.send_json({"type": "done"})
                return
        if not finished_input.is_set():
            raise RuntimeError("speech stream closed early")
        await ws.send_json({"type": "done"})

    tasks = [asyncio.create_task(read_text()), asyncio.create_task(read_audio())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if tasks[0] in done and finished_input.is_set():
            await asyncio.wait_for(tasks[1], 30)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await up.close()  # release the provider slot before database metering
        if chars:
            # Audio is already delivered (or the user disconnected). Keep
            # billing after the audio path, including interrupted replies.
            await tts.log_api_usage(endpoint="/ai/tts-el", model=tts.ELEVENLABS_MODEL,
                input_tokens=chars, output_tokens=0, business_id=business_id, user_id=user_id)
        logger.info("[speech flow] %s", json.dumps({"transport": "websocket", "chars": chars,
            "first_audio_ms": round((first_audio-submitted_at)*1000) if first_audio and submitted_at else None}))


@router.websocket("/ai/tts/stream")
async def speech_stream(ws: WebSocket):
    await ws.accept()
    try:
        if not enabled() or not tts._elevenlabs_key():
            raise ValueError("stream unavailable")
        if not rate_limit.allow("voice", rate_limit.client_ip(ws)):
            raise ValueError("voice rate limit")
        token, biz, voice = parse_hello(await asyncio.wait_for(ws.receive_text(), 8))
        user = await asyncio.to_thread(_verify_token, token)
        if not await asyncio.to_thread(tts._owns_business, user.id, biz):
            raise ValueError("business access denied")
        if not await asyncio.to_thread(tts._el_allowance_ok, biz):
            raise ValueError("voice allowance reached")
        async with websockets.connect(upstream_url(voice), open_timeout=5,
            additional_headers={"xi-api-key": tts._elevenlabs_key()}, max_size=2**20) as up:
            await up.send(json.dumps({"text": " "}))
            await ws.send_json({"type": "ready", "sample_rate": 24000})
            await asyncio.wait_for(relay(ws, up, biz, user.id), SESSION_SECONDS)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.info("speech stream ended: %s", type(exc).__name__)
        try:
            await ws.send_json({"type": "error", "message": "Voice stream unavailable"})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
