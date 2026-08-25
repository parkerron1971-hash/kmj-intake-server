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
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from api_usage_logger import log_api_usage
from auth_supabase import AuthedUser, optional_user, require_user
import pricing_config
import rate_limit
import sb_clients
from speech_text import normalize_for_speech


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

# Per-business monthly ElevenLabs character allowance. Premium voice is
# metered per business (rows land in api_usage with endpoint /ai/tts-el,
# which also bills 1 unit/chunk on the plan-allowance rails); this cap is
# the hard per-tenant backstop so one chatty business can't drain the
# shared ElevenLabs account pool. Over the cap → graceful fallback to
# OpenAI voices (never silence). 0 disables the cap.
ELEVENLABS_MONTHLY_CHARS_PER_BIZ = int(os.environ.get("ELEVENLABS_MONTHLY_CHARS_PER_BIZ", "200000") or 0)
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


# ── Per-business voice metering helpers ──────────────────────────────
# Small in-process caches: TTS fires once per spoken sentence-group, so
# these checks must not add a DB round-trip to every chunk. Fail-open —
# a metering hiccup must never silence the Chief.

_OWNER_CACHE: dict = {}          # business_id -> (checked_at, owner_id)
_OWNER_CACHE_TTL_S = 300
_EL_CHARS_CACHE: dict = {}       # business_id -> (checked_at, month_key, chars)
_EL_CHARS_TTL_S = 120


def _month_bounds() -> tuple:
    now = time.gmtime()
    month_key = f"{now.tm_year:04d}-{now.tm_mon:02d}"
    month_start = f"{now.tm_year:04d}-{now.tm_mon:02d}-01T00:00:00+00:00"
    return month_key, month_start


def _owns_business(user_id: str, business_id: str) -> bool:
    """True when the business exists and belongs to user_id. Cached."""
    try:
        now = time.time()
        hit = _OWNER_CACHE.get(business_id)
        if hit and now - hit[0] < _OWNER_CACHE_TTL_S:
            return hit[1] == user_id
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
        owner_id = rows[0].get("owner_id") if rows else None
        _OWNER_CACHE[business_id] = (now, owner_id)
        return owner_id == user_id
    except Exception as e:
        logger.warning(f"voice metering owner check failed: {e}")
        return False


def _el_chars_this_month(business_id: str) -> int:
    """ElevenLabs characters this business has spoken this month, from
    the /ai/tts-el rows in api_usage. Cached; incremented locally by
    _note_el_chars so the cap doesn't lag behind by a cache window."""
    month_key, month_start = _month_bounds()
    now = time.time()
    hit = _EL_CHARS_CACHE.get(business_id)
    if hit and now - hit[0] < _EL_CHARS_TTL_S and hit[1] == month_key:
        return hit[2]
    try:
        rows = sb_clients.sb_get_as_service(
            f"/api_usage?business_id=eq.{business_id}&endpoint=eq./ai/tts-el"
            f"&created_at=gte.{month_start}&select=input_tokens&limit=10000") or []
        chars = sum(int(r.get("input_tokens") or 0) for r in rows)
    except Exception as e:
        logger.warning(f"voice metering usage read failed (fail-open): {e}")
        chars = hit[2] if hit and hit[1] == month_key else 0
    _EL_CHARS_CACHE[business_id] = (now, month_key, chars)
    return chars


def _note_el_chars(business_id: str, chars: int) -> None:
    """Bump the local cache after a successful ElevenLabs call so the
    cap tracks in real time between refreshes."""
    month_key, _ = _month_bounds()
    hit = _EL_CHARS_CACHE.get(business_id)
    if hit and hit[1] == month_key:
        _EL_CHARS_CACHE[business_id] = (hit[0], month_key, hit[2] + chars)


def _el_allowance_ok(business_id: str) -> bool:
    if ELEVENLABS_MONTHLY_CHARS_PER_BIZ <= 0:
        return True
    return _el_chars_this_month(business_id) < ELEVENLABS_MONTHLY_CHARS_PER_BIZ


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["whisper_proxy"])


@router.post("/ai/whisper/transcribe")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: Optional[str] = Form(None),
    business_id: Optional[str] = Form(None),
    user: AuthedUser = Depends(require_user),
):
    """Transcribe an uploaded audio blob via OpenAI Whisper.

    `business_id` is OPTIONAL and only ever used to attribute the usage
    row — same ownership rail as /ai/tts (never trust a bare body field).
    A caller that omits it still transcribes; the row just lands with a
    user_id and no tenant, which is what every row looked like before."""
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
    #
    # ATTRIBUTION (2026-08-24). The row was written with neither a
    # business_id nor a user_id, so every one of them was unattributable.
    # That is not a rounding error: measured over 2026-08-10..24, /ai/whisper
    # was 370 calls and $9.12 — 19.8% of the platform's entire AI bill, and
    # the single largest line no per-tenant control could see. spend_guard's
    # per-business ceiling cannot count what carries no business, and the
    # Costs view cannot show whose voice it was.
    #
    # Roughly 94% of Chief turns now arrive by voice (370 whisper calls
    # against 394 /chief/backend turns in the same window), so this is the
    # normal path, not an edge one.
    try:
        est_minutes = max(len(audio_bytes) / 2500.0 / 60.0, 1 / 60.0)
        biz = (business_id or "").strip() or None
        metered_biz = biz if (biz and _owns_business(user.id, biz)) else None
        await log_api_usage(
            endpoint="/ai/whisper", model=WHISPER_MODEL,
            input_tokens=0, output_tokens=0,
            business_id=metered_biz, user_id=user.id,
            units=pricing_config.voice_input_price(),
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
    # Active business — attributes the spoken characters to a tenant for
    # metering. Optional: anonymous/unattributed requests still speak
    # (OpenAI voices only).
    business_id: Optional[str] = None


@router.post("/ai/tts/speak")
async def text_to_speech(req: TTSRequest, request: Request,
                         user: Optional[AuthedUser] = Depends(optional_user)):
    """Proxy TTS (OpenAI, or ElevenLabs for 'el:' voice ids). Streams raw
    mp3 audio back to the client for faster time-to-first-byte playback.

    Auth is OPTIONAL: OpenAI voices work for any caller (rate-guarded,
    included with every plan). ElevenLabs voices are premium — they
    require a signed-in owner of business_id, bill 1 unit per chunk on
    the plan-allowance rails, and are capped per business per month
    (ELEVENLABS_MONTHLY_CHARS_PER_BIZ). Every deny falls back to OpenAI
    — voice never goes silent."""
    _voice_rate_guard(request)
    key = _openai_key()
    if not key:
        raise HTTPException(500, "OPENAI_API_KEY not configured on server")

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > TTS_MAX_CHARS:
        text = text[:TTS_MAX_CHARS]

    # Metering identity — attribute characters to the business only when
    # the signed-in caller actually owns it (these rows feed the billing
    # rails; never trust a bare body field).
    biz_id = (req.business_id or "").strip() or None
    metered_biz = biz_id if (user and biz_id and _owns_business(user.id, biz_id)) else None

    # ElevenLabs routing — "el:<voice_id>" ids go to the ElevenLabs
    # streamer when the caller qualifies. EVERY deny falls back to the
    # OpenAI path below so a stale saved voice choice, a signed-out
    # session, or an exhausted allowance never silences the Chief.
    raw_voice = (req.voice or "nova").strip()
    if raw_voice.startswith("el:"):
        el_key = _elevenlabs_key()
        el_voice_id = raw_voice[3:].strip()
        if not el_key or not el_voice_id:
            logger.warning("ElevenLabs voice requested but key or voice id missing — falling back to OpenAI nova")
        elif not metered_biz:
            logger.warning("ElevenLabs voice requires a signed-in owner + business_id — falling back to OpenAI nova")
        elif not _el_allowance_ok(metered_biz):
            logger.info(f"ElevenLabs monthly char cap reached for business {metered_biz} — falling back to OpenAI nova")
        else:
            return await _elevenlabs_speak(text, el_voice_id, el_key,
                                           business_id=metered_biz,
                                           user_id=user.id if user else None)

    voice = raw_voice.lower()
    if voice not in TTS_VOICES:
        voice = "nova"

    model = req.model or TTS_MODEL_DEFAULT
    if model not in (TTS_MODEL_DEFAULT, TTS_MODEL_HD):
        model = TTS_MODEL_DEFAULT

    # Symbols become words at the wire, so "$1,234.56" is spoken the same
    # way no matter which client called us — the web app normalizes for
    # its own local browser-speech path, but the KAI agent and the mobile
    # app do not, and they reach this endpoint too.
    spoken = normalize_for_speech(text)[:TTS_MAX_CHARS]

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
                    "input": spoken,
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

    logger.info(
        f"TTS streaming: chars={len(text)} spoken={len(spoken)} "
        f"voice={voice} model={model}")
    # Metering (beta-readiness audit): every spoken reply was dark. TTS is
    # priced per character — pass the char count as input_tokens; the
    # tts-1 / tts-1-hd table entries are per-1M-char so the cost is exact.
    # business_id/user_id attribute the row for analytics; /ai/tts carries
    # UNIT weight 0 (included with every plan — see usage_metering).
    #
    # Counts the SPOKEN length, not the raw: OpenAI bills what we send, and
    # this row feeds the spend guard, so anything shorter would understate
    # real money. (The ElevenLabs row is the other way round — it also
    # drives a per-business quota. See _elevenlabs_speak.)
    try:
        await log_api_usage(
            endpoint="/ai/tts", model=model,
            input_tokens=len(spoken), output_tokens=0,
            business_id=metered_biz, user_id=user.id if user else None)
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


async def _elevenlabs_speak(text: str, voice_id: str, key: str,
                            business_id: Optional[str] = None,
                            user_id: Optional[str] = None) -> StreamingResponse:
    """Stream ElevenLabs TTS back to the client — same mp3-over-HTTP
    contract as the OpenAI path, so the frontend audio pipeline doesn't
    know or care which provider spoke."""
    if len(text) > ELEVENLABS_MAX_CHARS:
        text = text[:ELEVENLABS_MAX_CHARS]

    # Symbols become words at the wire. turbo_v2_5 does NOT normalize on
    # its own — apply_text_normalization is Enterprise-only on the v2.5
    # models — so without this a premium voice reads money worse than the
    # free one. `text` stays the raw form on purpose; see the metering
    # note below.
    spoken = normalize_for_speech(text)[:ELEVENLABS_MAX_CHARS]

    client = httpx.AsyncClient(timeout=TTS_TIMEOUT)
    try:
        upstream = await client.send(
            client.build_request(
                "POST",
                f"{ELEVENLABS_TTS_URL}/{voice_id}/stream?output_format=mp3_44100_128",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={"text": spoken, "model_id": ELEVENLABS_MODEL},
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

    logger.info(
        f"ElevenLabs TTS streaming: chars={len(text)} spoken={len(spoken)} "
        f"voice={voice_id} biz={business_id}")
    # Metering — per character (input_tokens), attributed to the business.
    # Endpoint /ai/tts-el is DISTINCT from /ai/tts on purpose: it bills
    # 1 unit per chunk on the plan-allowance rails (usage_metering
    # UNIT_WEIGHTS) and is what the monthly char cap sums.
    #
    # Counts the RAW length, not the spoken one. This row drives
    # ELEVENLABS_MONTHLY_CHARS_PER_BIZ, and spelling "$" out is OUR
    # formatting decision — a practitioner should not lose voice
    # allowance because we made the number pronounceable. The tradeoff is
    # deliberate and small: the cost side of this row now understates the
    # true billed characters by the width of the expansion (money-bearing
    # text only, single digits of percent). If that ever needs to be
    # exact, the fix is a second field, not a bigger number here.
    try:
        await log_api_usage(
            endpoint="/ai/tts-el", model=ELEVENLABS_MODEL,
            input_tokens=len(text), output_tokens=0,
            business_id=business_id, user_id=user_id)
    except Exception:
        pass
    if business_id:
        _note_el_chars(business_id, len(text))

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
        "elevenlabs_monthly_chars_per_biz": ELEVENLABS_MONTHLY_CHARS_PER_BIZ,
        "whisper_model": WHISPER_MODEL,
        "tts_model": TTS_MODEL_DEFAULT,
        "tts_voices": sorted(TTS_VOICES),
        "max_bytes": MAX_BYTES,
        "tts_max_chars": TTS_MAX_CHARS,
    }
