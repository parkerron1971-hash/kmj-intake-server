"""
whisper_proxy.py — Solutionist System Whisper STT proxy

Cross-platform voice transcription. The Tauri client captures audio via
MediaRecorder, uploads the blob to this endpoint, and gets back the
transcription. The OpenAI API key never leaves Railway.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.
2. In main.py:
       from whisper_proxy import router as whisper_router
       app.include_router(whisper_router)
3. Set the env var:
       OPENAI_API_KEY=sk-...
4. requirements.txt already has httpx; FastAPI's UploadFile requires
   python-multipart which is a standard transitive dep.

═══════════════════════════════════════════════════════════════════════
ENDPOINT
═══════════════════════════════════════════════════════════════════════

POST /ai/whisper/transcribe
  Content-Type: multipart/form-data
  Fields:
    audio:     <file>  (webm/mp4/ogg/wav/mp3 — Whisper accepts all)
    language:  <str>   (optional ISO-639-1 code)

Response:
    { "text": "...", "language": "en", ... }
"""

import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from api_usage_logger import log_api_usage
import rate_limit


def _voice_rate_guard(request: Request) -> None:
    """Per-IP throttle on the voice endpoints (beta-readiness audit).
    Fail-open inside rate_limit.allow."""
    if not rate_limit.allow("voice", rate_limit.client_ip(request)):
        raise HTTPException(status_code=429,
            detail="Too many voice requests — give it a moment.",
            headers={"Retry-After": str(rate_limit.retry_after("voice"))})

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
# Latency arc 2026-07-15: gpt-4o-mini-transcribe is faster AND more
# accurate than whisper-1 on the same /audio/transcriptions endpoint
# (default json response = same {"text": ...} shape the client reads).
WHISPER_MODEL = "gpt-4o-mini-transcribe"
TTS_MODEL_DEFAULT = "tts-1"           # faster, good quality
TTS_MODEL_HD = "tts-1-hd"             # slower, best quality
TTS_VOICES = {"nova", "alloy", "echo", "fable", "onyx", "shimmer"}
TTS_MAX_CHARS = 4096                  # OpenAI's hard limit

# ── ElevenLabs (optional second TTS provider) ────────────────────────
# Voice ids arrive from the client prefixed "el:<voice_id>" — the speak
# endpoint routes on the prefix; everything else stays OpenAI. Enabled
# by setting ELEVENLABS_API_KEY on Railway; without it the voices list
# is empty and el: requests fall back to OpenAI nova (never a dead end).
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
ELEVENLABS_MODEL = "eleven_turbo_v2_5"   # low-latency tier — right for conversation
ELEVENLABS_MAX_CHARS = 4096              # match the OpenAI clamp
MAX_BYTES = 25 * 1024 * 1024          # Whisper server-side limit
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
TTS_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)

logger = logging.getLogger("whisper_proxy")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] whisper: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


def _openai_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "")


def _elevenlabs_key() -> str:
    return os.environ.get("ELEVENLABS_API_KEY", "")


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["whisper_proxy"])


@router.post("/ai/whisper/transcribe")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: Optional[str] = Form(None),
):
    """Transcribe an uploaded audio blob via OpenAI Whisper."""
    _voice_rate_guard(request)
    key = _openai_key()
    if not key:
        logger.error("OPENAI_API_KEY not configured")
        raise HTTPException(500, "OPENAI_API_KEY not configured on server")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "no audio received")
    if len(audio_bytes) > MAX_BYTES:
        raise HTTPException(413, f"audio too large ({len(audio_bytes)} bytes, max {MAX_BYTES})")

    filename = audio.filename or "recording.webm"
    content_type = audio.content_type or "audio/webm"

    files = {"file": (filename, audio_bytes, content_type)}
    data: dict = {"model": WHISPER_MODEL}
    if language:
        data["language"] = language

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                OPENAI_API_URL,
                headers={"Authorization": f"Bearer {key}"},
                files=files,
                data=data,
            )
    except httpx.TimeoutException:
        logger.warning("Whisper request timed out")
        raise HTTPException(504, "Whisper API timed out")
    except httpx.HTTPError as e:
        logger.error(f"Whisper request failed: {e}")
        raise HTTPException(502, f"Whisper request failed: {e}")

    if resp.status_code >= 400:
        body = resp.text[:300]
        logger.warning(f"Whisper {resp.status_code}: {body}")
        raise HTTPException(resp.status_code, f"Whisper error: {body}")

    try:
        result = resp.json()
    except ValueError:
        raise HTTPException(502, "Whisper returned non-JSON response")

    logger.info(
        f"Whisper ok: bytes={len(audio_bytes)} "
        f"text_len={len(result.get('text', ''))} content_type={content_type}"
    )
    # Metering (beta-readiness audit): voice input was completely dark.
    # Whisper is $0.006/min; estimate minutes from the byte size of the
    # (opus/webm voice) blob — ~2.5 KB/sec is a reasonable voice rate.
    try:
        est_minutes = max(len(audio_bytes) / 2500.0 / 60.0, 1 / 60.0)
        await log_api_usage(
            endpoint="/ai/whisper", model=WHISPER_MODEL,
            input_tokens=0, output_tokens=0,
            cost_cents_override=round(est_minutes * 0.6, 4))  # $0.006/min = 0.6c/min
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════════════════
# TTS (Text-to-Speech) proxy
# ═══════════════════════════════════════════════════════════════════════

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "nova"
    model: Optional[str] = TTS_MODEL_DEFAULT


@router.post("/ai/tts/speak")
async def text_to_speech(req: TTSRequest, request: Request):
    """Proxy OpenAI TTS. Streams raw mp3 audio back to the client for
    faster time-to-first-byte playback."""
    _voice_rate_guard(request)
    key = _openai_key()
    if not key:
        raise HTTPException(500, "OPENAI_API_KEY not configured on server")

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS]

    # ElevenLabs routing — "el:<voice_id>" ids go to the ElevenLabs
    # streamer; missing key/id falls back to OpenAI nova so a stale
    # saved voice choice never silences the Chief.
    raw_voice = (req.voice or "nova").strip()
    if raw_voice.startswith("el:"):
        el_key = _elevenlabs_key()
        el_voice_id = raw_voice[3:].strip()
        if el_key and el_voice_id:
            return await _elevenlabs_speak(text, el_voice_id, el_key)
        logger.warning("ElevenLabs voice requested but key or voice id missing — falling back to OpenAI nova")

    voice = raw_voice.lower()
    if voice not in TTS_VOICES:
        voice = "nova"

    model = req.model or TTS_MODEL_DEFAULT
    if model not in (TTS_MODEL_DEFAULT, TTS_MODEL_HD):
        model = TTS_MODEL_DEFAULT

    # Use httpx streaming so we forward chunks as OpenAI produces them,
    # instead of buffering the entire mp3 in memory first.
    client = httpx.AsyncClient(timeout=TTS_TIMEOUT)

    try:
        upstream = await client.send(
            client.build_request(
                "POST",
                OPENAI_TTS_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": text,
                    "voice": voice,
                    "response_format": "mp3",
                },
            ),
            stream=True,
        )
    except httpx.TimeoutException:
        await client.aclose()
        logger.warning("TTS request timed out")
        raise HTTPException(504, "TTS API timed out")
    except httpx.HTTPError as e:
        await client.aclose()
        logger.error(f"TTS request failed: {e}")
        raise HTTPException(502, f"TTS request failed: {e}")

    if upstream.status_code >= 400:
        body = (await upstream.aread()).decode("utf-8", errors="replace")[:300]
        await upstream.aclose()
        await client.aclose()
        logger.warning(f"TTS {upstream.status_code}: {body}")
        raise HTTPException(upstream.status_code, f"TTS error: {body}")

    logger.info(f"TTS streaming: chars={len(text)} voice={voice} model={model}")
    # Metering (beta-readiness audit): every spoken reply was dark. TTS is
    # priced per character — pass the char count as input_tokens; the
    # tts-1 / tts-1-hd table entries are per-1M-char so the cost is exact.
    try:
        await log_api_usage(
            endpoint="/ai/tts", model=model,
            input_tokens=len(text), output_tokens=0)
    except Exception:
        pass

    async def _stream():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=4096):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        _stream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


async def _elevenlabs_speak(text: str, voice_id: str, key: str) -> StreamingResponse:
    """Stream ElevenLabs TTS back to the client — same mp3-over-HTTP
    contract as the OpenAI path, so the frontend audio pipeline doesn't
    know or care which provider spoke."""
    if len(text) > ELEVENLABS_MAX_CHARS:
        text = text[:ELEVENLABS_MAX_CHARS]

    client = httpx.AsyncClient(timeout=TTS_TIMEOUT)
    try:
        upstream = await client.send(
            client.build_request(
                "POST",
                f"{ELEVENLABS_TTS_URL}/{voice_id}/stream?output_format=mp3_44100_128",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={"text": text, "model_id": ELEVENLABS_MODEL},
            ),
            stream=True,
        )
    except httpx.TimeoutException:
        await client.aclose()
        logger.warning("ElevenLabs TTS timed out")
        raise HTTPException(504, "TTS API timed out")
    except httpx.HTTPError as e:
        await client.aclose()
        logger.error(f"ElevenLabs TTS failed: {e}")
        raise HTTPException(502, f"TTS request failed: {e}")

    if upstream.status_code >= 400:
        body = (await upstream.aread()).decode("utf-8", errors="replace")[:300]
        await upstream.aclose()
        await client.aclose()
        logger.warning(f"ElevenLabs TTS {upstream.status_code}: {body}")
        raise HTTPException(upstream.status_code, f"TTS error: {body}")

    logger.info(f"ElevenLabs TTS streaming: chars={len(text)} voice={voice_id}")
    # Metering — ElevenLabs is priced per character, same convention as
    # the OpenAI entries: char count as input_tokens.
    try:
        await log_api_usage(
            endpoint="/ai/tts", model=ELEVENLABS_MODEL,
            input_tokens=len(text), output_tokens=0)
    except Exception:
        pass

    async def _stream():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=4096):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        _stream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


# In-process cache — the voice list changes rarely; don't hit the
# ElevenLabs API on every picker open.
_EL_VOICES_CACHE: dict = {"at": 0.0, "voices": []}
_EL_VOICES_TTL_S = 300


@router.get("/ai/tts/voices")
async def list_tts_voices(request: Request):
    """ElevenLabs voices connected to this deployment's account, shaped
    for the frontend voice picker: [{id: "el:<voice_id>", label, desc}].
    Empty list when ELEVENLABS_API_KEY isn't configured — the picker
    simply doesn't render the section (no dead-end)."""
    _voice_rate_guard(request)
    key = _elevenlabs_key()
    if not key:
        return {"voices": []}

    now = time.time()
    if _EL_VOICES_CACHE["voices"] and now - _EL_VOICES_CACHE["at"] < _EL_VOICES_TTL_S:
        return {"voices": _EL_VOICES_CACHE["voices"]}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(ELEVENLABS_VOICES_URL, headers={"xi-api-key": key})
        if resp.status_code >= 400:
            logger.warning(f"ElevenLabs voices list {resp.status_code}")
            return {"voices": _EL_VOICES_CACHE["voices"]}
        data = resp.json()
        voices = []
        for v in (data.get("voices") or []):
            vid = v.get("voice_id")
            if not vid:
                continue
            labels = v.get("labels") or {}
            desc_bits = [labels.get(k) for k in ("gender", "accent", "description") if labels.get(k)]
            voices.append({
                "id": f"el:{vid}",
                "label": v.get("name") or "Voice",
                "desc": ", ".join(desc_bits) or "ElevenLabs voice",
            })
        _EL_VOICES_CACHE.update(at=now, voices=voices)
        return {"voices": voices}
    except Exception as e:
        logger.warning(f"ElevenLabs voices list failed: {e}")
        return {"voices": _EL_VOICES_CACHE["voices"]}


# ═══════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════

@router.get("/ai/whisper/health")
async def health():
    """Liveness probe — confirms the router is mounted and the key is set."""
    return {
        "status": "ok",
        "key_present": bool(_openai_key()),
        "elevenlabs_key_present": bool(_elevenlabs_key()),
        "whisper_model": WHISPER_MODEL,
        "tts_model": TTS_MODEL_DEFAULT,
        "tts_voices": sorted(TTS_VOICES),
        "max_bytes": MAX_BYTES,
        "tts_max_chars": TTS_MAX_CHARS,
    }
