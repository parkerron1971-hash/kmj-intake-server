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

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-1"
MAX_BYTES = 25 * 1024 * 1024  # Whisper server-side limit
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)

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


@router.get("/ai/whisper/health")
async def health():
    """Liveness probe — confirms the router is mounted and the key is set."""
    return {
        "status": "ok",
        "key_present": bool(_openai_key()),
        "model": WHISPER_MODEL,
        "max_bytes": MAX_BYTES,
    }
