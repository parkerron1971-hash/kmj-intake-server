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
from typing import Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
WHISPER_MODEL = "whisper-1"
TTS_MODEL_DEFAULT = "tts-1"           # faster, good quality
TTS_MODEL_HD = "tts-1-hd"             # slower, best quality
TTS_VOICES = {"nova", "alloy", "echo", "fable", "onyx", "shimmer"}
TTS_MAX_CHARS = 4096                  # OpenAI's hard limit
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


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["whisper_proxy"])


@router.post("/ai/whisper/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: Optional[str] = Form(None),
):
    """Transcribe an uploaded audio blob via OpenAI Whisper."""
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
    return result


# ═══════════════════════════════════════════════════════════════════════
# TTS (Text-to-Speech) proxy
# ═══════════════════════════════════════════════════════════════════════

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "nova"
    model: Optional[str] = TTS_MODEL_DEFAULT


@router.post("/ai/tts/speak")
async def text_to_speech(req: TTSRequest):
    """Proxy OpenAI TTS. Returns raw mp3 audio (binary)."""
    key = _openai_key()
    if not key:
        raise HTTPException(500, "OPENAI_API_KEY not configured on server")

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS]

    voice = (req.voice or "nova").lower()
    if voice not in TTS_VOICES:
        voice = "nova"

    model = req.model or TTS_MODEL_DEFAULT
    if model not in (TTS_MODEL_DEFAULT, TTS_MODEL_HD):
        model = TTS_MODEL_DEFAULT

    try:
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
            resp = await client.post(
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
            )
    except httpx.TimeoutException:
        logger.warning("TTS request timed out")
        raise HTTPException(504, "TTS API timed out")
    except httpx.HTTPError as e:
        logger.error(f"TTS request failed: {e}")
        raise HTTPException(502, f"TTS request failed: {e}")

    if resp.status_code >= 400:
        body = resp.text[:300]
        logger.warning(f"TTS {resp.status_code}: {body}")
        raise HTTPException(resp.status_code, f"TTS error: {body}")

    logger.info(f"TTS ok: chars={len(text)} voice={voice} model={model} bytes={len(resp.content)}")
    return Response(
        content=resp.content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )


# ═══════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════

@router.get("/ai/whisper/health")
async def health():
    """Liveness probe — confirms the router is mounted and the key is set."""
    return {
        "status": "ok",
        "key_present": bool(_openai_key()),
        "whisper_model": WHISPER_MODEL,
        "tts_model": TTS_MODEL_DEFAULT,
        "tts_voices": sorted(TTS_VOICES),
        "max_bytes": MAX_BYTES,
        "tts_max_chars": TTS_MAX_CHARS,
    }
