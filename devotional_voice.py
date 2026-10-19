"""
devotional_voice.py — Listen, on a devotional's day in the member app.

Kevin said yes to Listen on 2026-10-19, knowing it costs voice minutes.
So a day is read aloud ONCE for each version of its words: the first member
who taps Listen waits while it's made (about half a minute), the file is
kept in the church's storage, and every later tap, by anyone, plays that
same file. The cost is one reading per day each time the church edits it,
never one per listen. A changed day has new words, so a new hash, so it is
read again; the old file is left until the devotional is deleted.

The voice is the one the church picked for the devotional, from Kevin's
featured voices (Inworld; whisper_proxy.INWORLD_VOICES), at an unhurried
pace. A piece Inworld can't read is read by OpenAI's Nova instead, so the
member never gets silence; with neither key, or no ffmpeg to make the MP3,
Listen isn't offered at all.

    POST /my/bible/plans/listen   JSON {devotional, day} → {ok, url, seconds}

What is read: the devotional's name and the day, the scripture (its words
from the app's Bible, KJV, at most six verses), the day's words, the line
to hold on to, the prayer, what to do today, together, and the journal
question.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import sb_clients

logger = logging.getLogger("devotional_voice")
router = APIRouter(tags=["member-portal"])

BUCKET = "business-assets"            # public: the church's members' app reads it
PIECE_MAX = 3000                      # characters per request (both providers take ~4,000)
RATE = 24000                          # PCM from both providers: s16le mono at this rate
GAP = b"\x00\x00" * int(RATE * 0.7)   # a breath between pieces
VERSES_READ = 6
MODEL_TAG = "v1"                      # bump to read every day again (a better voice, say)
_LOCKS: Dict[str, asyncio.Lock] = {}
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
OPENAI_SPEECH = "https://api.openai.com/v1/audio/speech"
OPENAI_MODEL = "gpt-4o-mini-tts"
_NOVA_FOR = {"grace": "nova", "jessica": "shimmer", "elijah": "onyx", "reed": "echo"}


def can_speak() -> bool:
    """Listen is offered only when it can work."""
    import whisper_proxy as wp
    return bool(wp._inworld_key() or wp._openai_key()) and bool(shutil.which("ffmpeg"))


# ─── what is read ────────────────────────────────────────────────────


def spoken_ref(label: str) -> str:
    """'Proverbs 4:25' → 'Proverbs 4, verse 25'; '4:16-18' → 'verses 16 to 18'."""
    m = re.fullmatch(r"(.+?) (\d+):(\d+)(?:[-–](\d+))?", label or "")
    if not m:
        return label
    book, ch, a, b = m.groups()
    return f"{book} {ch}, verse {a}" if not b else f"{book} {ch}, verses {a} to {b}"


def scripture_words(ref_text: str) -> str:
    """The scripture as it's read: its reference, then its words."""
    import bible_text as bt
    found = bt.find_refs(ref_text or "")
    if not found:
        return str(ref_text or "").strip()
    ref = found[0][2]
    verses = bt.verses(ref, bt.DEFAULT) or []
    words = " ".join(re.sub(r"[\[\]¶]", "", t).strip() for _, _, t in verses[:VERSES_READ])
    return f"{spoken_ref(ref.label())}. {words}".strip()


def script(dev: Dict[str, Any], n: int) -> List[str]:
    """The day as paragraphs to read, in order."""
    import devotionals as dv
    day = (dev.get("days") or [])[n - 1]
    out = [f"{dev.get('title') or ''}. Day {n}. {day.get('title') or ''}."]
    if str(day.get("scripture") or "").strip():
        out.append(scripture_words(day["scripture"]))
    out += dv.paragraphs(day.get("body") or "")
    if str(day.get("pull") or "").strip():
        out.append(day["pull"].strip())
    for key, said in (("pray", "Pray."), ("act", "Do today."), ("together", "Together.")):
        if str(day.get(key) or "").strip():
            out.append(f"{said} {day[key].strip()}")
    if str(day.get("journal") or "").strip():
        out.append(f"Something to write down. {day['journal'].strip()}")
    return [p for p in out if p.strip()]


def pieces(paras: List[str], cap: int = PIECE_MAX) -> List[str]:
    """Paragraphs joined into pieces of at most `cap` characters; a
    paragraph longer than that is cut at its sentences."""
    out: List[str] = []
    for p in paras:
        parts = [p] if len(p) <= cap else re.split(r"(?<=[.!?])\s+", p)
        for part in parts:
            while len(part) > cap:            # one sentence longer than a piece: cut at a space
                cut = part.rfind(" ", 0, cap)
                cut = cut if cut > 0 else cap
                out.append(part[:cut])
                part = part[cut:].strip()
            if out and len(out[-1]) + 2 + len(part) <= cap:
                out[-1] = out[-1] + "\n\n" + part
            elif part:
                out.append(part)
    return out


def version(dev: Dict[str, Any], n: int) -> str:
    """Which reading of this day: its words and its voice."""
    raw = "\n".join([MODEL_TAG, str(dev.get("voice") or ""), *script(dev, n)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def kept(dev: Dict[str, Any], n: int) -> Optional[Dict[str, Any]]:
    """The day's file when it was made from these words, else None."""
    got = (dev.get("audio") or {}).get(str(n))
    if isinstance(got, dict) and got.get("hash") == version(dev, n) and str(got.get("url") or "").startswith("https://"):
        return got
    return None


# ─── making it ───────────────────────────────────────────────────────


async def _inworld(text: str, voice: str, business_id: str) -> Optional[bytes]:
    import whisper_proxy as wp
    from api_usage_logger import log_api_usage
    key = wp._inworld_key()
    v = wp.INWORLD_VOICES.get(voice)
    if not key or not v:
        return None
    said = wp._inworld_text(text, steer=False)
    if not said or len(said) > wp.INWORLD_MAX_CHARS:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async with client.stream(
                    "POST", wp.INWORLD_TTS_URL,
                    headers={"Authorization": f"Basic {key}", "Content-Type": "application/json"},
                    json={"text": said, "voiceId": v.voice_id, "modelId": wp.INWORLD_MODEL,
                          "audioConfig": {"audioEncoding": "PCM", "sampleRateHertz": RATE,
                                          "speakingRate": min(v.rate, 1.0)}}) as r:
                if r.status_code >= 400:
                    logger.warning("devotional Inworld %s: %s", r.status_code, (await r.aread())[:200])
                    return None
                audio = bytearray()
                async for chunk in wp._inworld_chunks(r):
                    audio += chunk
    except Exception as e:  # noqa: BLE001
        logger.warning("devotional Inworld failed: %r", e)
        return None
    try:
        await log_api_usage(endpoint="/ai/tts", model=wp.INWORLD_MODEL, input_tokens=len(said), output_tokens=0,
                            business_id=business_id, task_type="devotional_listen")
    except Exception:  # noqa: BLE001
        pass
    return bytes(audio) or None


async def _nova(text: str, voice: str, business_id: str) -> Optional[bytes]:
    import whisper_proxy as wp
    from api_usage_logger import log_api_usage
    from speech_text import normalize_for_speech
    key = wp._openai_key()
    if not key:
        return None
    said = normalize_for_speech(text)[:4000]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(OPENAI_SPEECH, headers={"Authorization": f"Bearer {key}"},
                                  json={"model": OPENAI_MODEL, "voice": _NOVA_FOR.get(voice, "nova"), "input": said,
                                        "response_format": "pcm",
                                        "instructions": "Read a church devotional aloud: warm, unhurried and sincere, "
                                                        "with a short pause between paragraphs. Not an announcer."})
        if r.status_code >= 400:
            logger.warning("devotional Nova %s: %s", r.status_code, r.text[:200])
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("devotional Nova failed: %r", e)
        return None
    try:
        await log_api_usage(endpoint="/ai/tts", model=OPENAI_MODEL, input_tokens=len(said), output_tokens=0,
                            business_id=business_id, task_type="devotional_listen")
    except Exception:  # noqa: BLE001
        pass
    return r.content or None


def encode(pcm: bytes) -> Optional[bytes]:
    """The reading as a small MP3 (mono, 48 kbps: about 360 KB a minute)."""
    try:
        done = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "1",
             "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", "pipe:1"],
            input=pcm, capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("devotional encode failed: %r", e)
        return None
    if done.returncode != 0 or not done.stdout:
        logger.error("devotional encode: ffmpeg %s %s", done.returncode, done.stderr[:200])
        return None
    return done.stdout


def _path(business_id: str, dev_id: str, n: int, h: str) -> str:
    return f"{business_id}/devotional-audio/{dev_id}-d{int(n)}-{h}.mp3"


_PATH = re.compile(r"[0-9a-f-]{36}/devotional-audio/[0-9a-f-]{36}-d\d{1,2}-[0-9a-f]{16}\.mp3")


def store(path: str, mp3: bytes) -> Optional[str]:
    """The file in the church's public storage; its URL, or None."""
    base = sb_clients.sb_url()
    if not _PATH.fullmatch(path) or not base:
        return None
    import storage_links
    try:
        r = httpx.post(f"{base}/storage/v1/object/{BUCKET}/{path}", content=mp3, timeout=60.0,
                       headers={**storage_links.service_headers(), "Content-Type": "audio/mpeg", "x-upsert": "true",
                                "cache-control": "max-age=31536000"})
    except httpx.HTTPError as e:
        logger.error("devotional store failed: %r", e)
        return None
    if r.status_code >= 400:
        logger.error("devotional store: %s %s", r.status_code, r.text[:200])
        return None
    return f"{base}/storage/v1/object/public/{BUCKET}/{path}"


def remember(business_id: str, dev_id: str, n: int, entry: Dict[str, Any]) -> bool:
    """Put the day's file on the devotional, read just before writing so a
    file another day just got isn't lost."""
    q = f"/devotionals?id=eq.{dev_id}&business_id=eq.{business_id}"
    rows = sb_clients.sb_get_as_service(f"{q}&select=audio&limit=1")
    if not isinstance(rows, list) or not rows:
        return False
    audio = dict(rows[0].get("audio") or {})
    audio[str(n)] = entry
    return bool(sb_clients.sb_patch_as_service(q, {"audio": audio}))


async def make(dev: Dict[str, Any], n: int) -> Optional[Dict[str, Any]]:
    """Read the day aloud and keep it: {hash, url, path, seconds}, or None."""
    biz, dev_id = str(dev["business_id"]), str(dev["id"])
    voice = str(dev.get("voice") or "grace")
    pcm = bytearray()
    for i, piece in enumerate(pieces(script(dev, n))):
        audio = await _inworld(piece, voice, biz) or await _nova(piece, voice, biz)
        if not audio:
            return None
        if i:
            pcm += GAP
        pcm += audio[:len(audio) - len(audio) % 2]
    mp3 = await asyncio.to_thread(encode, bytes(pcm))
    if not mp3:
        return None
    h = version(dev, n)
    path = _path(biz, dev_id, n, h)
    url = await asyncio.to_thread(store, path, mp3)
    if not url:
        return None
    entry = {"hash": h, "url": url, "path": path, "seconds": round(len(pcm) / (2 * RATE)),
             "made_at": datetime.now(timezone.utc).isoformat()}
    if not await asyncio.to_thread(remember, biz, dev_id, n, entry):
        logger.warning("devotional audio made but not remembered: %s day %s", dev_id, n)
    return entry


async def ready(dev: Dict[str, Any], n: int) -> Optional[Dict[str, Any]]:
    """The day's file: the kept one, or made now. Two members tapping
    Listen at once wait for one reading, not two."""
    got = kept(dev, n)
    if got:
        return got
    lock = _LOCKS.setdefault(f"{dev['id']}:{n}:{version(dev, n)}", asyncio.Lock())
    async with lock:
        import devotionals as dv
        fresh, _ok = await asyncio.to_thread(dv.one, str(dev["business_id"]), str(dev["id"]))
        got = kept(fresh or dev, n)
        if got:
            return got
        return await make(fresh or dev, n)


def forget(dev: Dict[str, Any]) -> None:
    """Best effort: a deleted devotional's files go too."""
    paths = [e.get("path") for e in (dev.get("audio") or {}).values()
             if isinstance(e, dict) and _PATH.fullmatch(str(e.get("path") or ""))]
    base = sb_clients.sb_url()
    if not paths or not base:
        return
    import storage_links
    try:
        httpx.request("DELETE", f"{base}/storage/v1/object/{BUCKET}", timeout=30.0,
                      headers={**storage_links.service_headers(), "Content-Type": "application/json"},
                      json={"prefixes": paths})
    except httpx.HTTPError as e:
        logger.warning("devotional audio delete failed: %r", e)


# ─── the route ───────────────────────────────────────────────────────


@router.post("/my/bible/plans/listen", include_in_schema=False)
async def listen(request: Request):
    """The day's reading for a member (or the owner's preview): JSON in,
    JSON out (the day page's Listen button)."""
    import member_portal as mp
    import member_portal_church as mpc
    import member_portal_devotionals as mpd
    import rate_limit
    h = mp._SECURE_HEADERS

    def no(error: str, status: int) -> JSONResponse:
        return JSONResponse({"ok": False, "error": error}, status_code=status, headers=h)
    if not mp._same_origin(request):
        return no("origin", 403)
    church, me, unavailable = await mpc._signed_in(request)
    preview = unavailable == "preview"
    if unavailable and not preview:
        return no("unavailable", 503)
    if not me and not preview:
        return no("signin", 401)
    biz = church["business"]
    if not rate_limit.allow("devotional_listen", f"{biz['id']}|{me['id'] if me else 'preview'}"):
        return no("slow", 429)
    if not can_speak():
        return no("off", 404)
    try:
        body = await request.json()
        n = int((body or {}).get("day"))
        dev_id = str((body or {}).get("devotional") or "")
    except Exception:  # noqa: BLE001
        return no("bad", 400)
    import devotionals as dv
    dev, ok = await asyncio.to_thread(dv.one, biz["id"], dev_id)
    if not ok:
        return no("unavailable", 503)
    if not dev or not 1 <= n <= int(dev.get("day_count") or 0):
        return no("bad", 400)
    if not preview:
        started = await asyncio.to_thread(mpd.started_on, biz["id"], str(me["id"]), dev)
        if started is False:
            return no("unavailable", 503)
        if n > dv.open_upto(dv.run_start(dev, started), int(dev["day_count"])):
            return no("closed", 403)
    got = await ready(dev, n)
    if not got:
        return no("error", 503)
    return JSONResponse({"ok": True, "url": got["url"], "seconds": got.get("seconds") or 0}, headers=h)
