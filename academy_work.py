"""Homework answered with a file (the last part of the Class Schedule design).

A teacher's homework can ask for an upload (a photo, a file, a voice note or
a short video) or for "tick it off and add a photo". The student hands it in
from their classroom, by their class link:

    POST /academy-work/<class link>/<item>   multipart "file"
    GET  /academy-work/<class link>/<item>   their own file: a short signed link

and the teacher, signed in, opens what came in:

    GET  /academy-work-file/<work id>        a short signed link

The files live in the PRIVATE academy-work bucket, which has no storage
policies: only this service role reads or writes it. So everything a
policy would have checked is checked here or in the database first:

  * the link, the item and its week, by academy_item_file_target and again
    by academy_item_attach (service-only; APPLY-2026-10-18-academy-uploads.sql),
    which also refuses a path outside this student's own name;
  * the bytes, never the browser's word: a photo must decode, and is saved
    again (turned upright, at most 2400 px, WITHOUT its EXIF, so a phone
    photo's location never reaches the teacher); a PDF, a voice note or a
    video must start the way that kind of file starts, and is stored under
    the type found there, from a short list a browser can only play or show;
  * the teacher's read, as the teacher: the work row is read with their own
    token, so academy_item_work's teacher-read policy decides, not this code.

Classmates never see a file, even on homework shared with the class.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
import secrets
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

import storage_links
from auth_supabase import UserSession, require_user_session

logger = logging.getLogger(__name__)
router = APIRouter()

BUCKET = "academy-work"
SIGNED_TTL = 900  # long enough to watch a short video; never a lasting link

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The one shape a stored file has (the database's constraint says the same).
_PATH = re.compile(r"[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}-[0-9a-f-]{36}-[0-9a-f]{8}\.(jpg|png|pdf|mp3|m4a|ogg|wav|webm|mp4|mov)")

MB = 1024 * 1024
LIMIT = {"photo": 20 * MB, "pdf": 20 * MB, "audio": 25 * MB, "video": 50 * MB}
READ_CAP = max(LIMIT.values())
PHOTO_EDGE = 2400
PHOTO_KINDS = ("jpeg", "png", "webp", "gif", "avif")  # what a photo may arrive as; it is kept as JPEG or PNG

# The student reads these. The database's own refusals are written for them too.
WORDS = {
    "too_big": "That file is too big. A photo or a PDF can be up to 20 MB, a voice note 25 MB, a video 50 MB.",
    "heic": "That photo is in the iPhone's HEIC format. Choose it again from Photos, or take a screenshot of it and send that.",
    "photo_only": "This one asks for a photo. Send a JPG or PNG.",
    "unknown": "We can take a photo (JPG or PNG), a PDF, a voice note or a short video. That file isn't one of those.",
    "unreadable": "We couldn't open that photo. Try taking it again, or send a screenshot of it.",
    "empty": "That file is empty. Choose it again.",
}
_DB_WORDS = {
    "Not open yet": "This week isn't open yet.",
    "This one doesn't take a file": "This homework doesn't take a file.",
    "That isn't part of this class": "That isn't part of this class.",
}


# ─── What a file is, from its bytes ──────────────────────────────────

def _photo(data: bytes) -> Optional[Tuple[bytes, str, str]]:
    """A photo that decodes, saved again upright, at most PHOTO_EDGE px,
    without EXIF (location, camera, time). PNG when it has see-through
    parts, else JPEG."""
    import upload_images
    if not upload_images.verified_image(data, PHOTO_KINDS):
        return None
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(data)) as src:
            src.seek(0)
            if src.format in ("JPEG", "MPO"):
                src.draft("RGB", (PHOTO_EDGE, PHOTO_EDGE))  # decode no bigger than it is kept
            img = ImageOps.exif_transpose(src)
            img.thumbnail((PHOTO_EDGE, PHOTO_EDGE))
            see_through = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
            out = io.BytesIO()
            if see_through:
                img.convert("RGBA").save(out, "PNG", optimize=True)
                return out.getvalue(), "image/png", "png"
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
            return out.getvalue(), "image/jpeg", "jpg"
    except Exception:  # noqa: BLE001 — a photo that won't save again isn't taken
        return None


def classify(data: bytes, declared: str = "", photo_only: bool = False) -> Tuple[Optional[Tuple[bytes, str, str]], str]:
    """((bytes to store, MIME, extension), "") or (None, the student's words).
    `declared` (the browser's type) only ever chooses between audio and video
    for a container that holds either; it never makes a file acceptable."""
    if not data:
        return None, WORDS["empty"]
    import upload_images
    head = data[:16]
    brand = data[8:12] if data[4:8] == b"ftyp" else b""
    if upload_images.sniff(data) in PHOTO_KINDS:
        if len(data) > LIMIT["photo"]:
            return None, WORDS["too_big"]
        found = _photo(data)
        return (found, "") if found else (None, WORDS["unreadable"])
    if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return None, WORDS["heic"]
    if photo_only:
        return None, WORDS["photo_only"]
    audio_said = (declared or "").lower().startswith("audio/")
    kind: Optional[Tuple[str, str, str]] = None  # (limit family, MIME, ext)
    if head.startswith(b"%PDF-"):
        kind = ("pdf", "application/pdf", "pdf")
    elif brand in (b"M4A ", b"M4B "):
        kind = ("audio", "audio/mp4", "m4a")
    elif brand == b"qt  ":
        kind = ("video", "video/quicktime", "mov")
    elif brand:
        kind = ("audio", "audio/mp4", "m4a") if audio_said else ("video", "video/mp4", "mp4")
    elif head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        kind = ("audio", "audio/mpeg", "mp3")
    elif head.startswith(b"OggS"):
        kind = ("audio", "audio/ogg", "ogg")
    elif head[:4] == b"RIFF" and data[8:12] == b"WAVE":
        kind = ("audio", "audio/wav", "wav")
    elif head.startswith(b"\x1a\x45\xdf\xa3"):
        kind = ("audio", "audio/webm", "webm") if audio_said else ("video", "video/webm", "webm")
    if not kind:
        return None, WORDS["unknown"]
    family, mime, ext = kind
    if len(data) > LIMIT[family]:
        return None, WORDS["too_big"]
    return (data, mime, ext), ""


def display_name(filename: str, ext: str) -> str:
    """The name the teacher sees: the student's own, made plain, ending in
    what the file now is (a .heic name can't sit on a JPEG)."""
    base = re.sub(r"[^\w .()'-]+", "_", (filename or "").replace("\\", "/").rsplit("/", 1)[-1]).strip(" ._") or "file"
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem[:140].strip() or 'file'}.{ext}"


def object_path(target: Dict[str, Any], ext: str) -> str:
    """<business>/<course>/<enrollment>-<item>-<random>.<ext>, or ValueError."""
    ids = [str(target.get(k) or "").lower() for k in ("business_id", "course_id", "enrollment_id", "item_id")]
    if not all(_UUID.fullmatch(i) for i in ids):
        raise ValueError("target ids aren't ids")
    path = f"{ids[0]}/{ids[1]}/{ids[2]}-{ids[3]}-{secrets.token_hex(4)}.{ext}"
    if not _PATH.fullmatch(path):
        raise ValueError("path out of shape")
    return path


# ─── The database and storage, as the service role ───────────────────

def _base() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


async def _rpc(client: httpx.AsyncClient, name: str, body: Dict[str, Any]) -> Tuple[Any, str]:
    """(result, "") or (None, the database's own sentence or "failed")."""
    import sb_clients
    try:
        r = await client.post(f"{_base()}/rest/v1/rpc/{name}", headers=sb_clients.sb_headers_service(), json=body,
                              timeout=httpx.Timeout(30.0))
    except Exception as e:  # noqa: BLE001
        logger.error("academy-work %s: %s", name, type(e).__name__)
        return None, "failed"
    if r.status_code >= 400:
        try:
            said = str((r.json() or {}).get("message") or "")
        except Exception:  # noqa: BLE001
            said = ""
        return None, said or "failed"
    return (r.json() if r.text else None), ""


def _refuse(said: str) -> HTTPException:
    if said == "Classroom unavailable":
        return HTTPException(404, "Classroom unavailable")
    for key, words in _DB_WORDS.items():
        if key in said:
            return HTTPException(400, words)
    return HTTPException(502, "That didn't save. Try again in a moment.")


async def _store(client: httpx.AsyncClient, path: str, blob: bytes, mime: str) -> str:
    """"" when stored, else plain words for the student."""
    if not storage_links.has_service_key() or not _base():
        return storage_links.UPLOAD_NOT_CONFIGURED
    try:
        r = await client.post(f"{_base()}/storage/v1/object/{BUCKET}/{path}",
                              headers={**storage_links.service_headers(), "Content-Type": mime, "x-upsert": "false",
                                       "Cache-Control": "private, max-age=0"},
                              content=blob, timeout=httpx.Timeout(connect=10.0, read=120.0, write=300.0, pool=10.0))
    except Exception as e:  # noqa: BLE001
        logger.error("academy-work store: %s", type(e).__name__)
        return storage_links.UPLOAD_UNREACHABLE
    if r.status_code >= 400:
        logger.error("academy-work store: %s %s", r.status_code, r.text[:200])
        return storage_links.upload_refusal(r.status_code, r.text)
    return ""


async def _remove(client: httpx.AsyncClient, path: Optional[str]) -> None:
    """Best effort: a replaced or unattached file is deleted."""
    if not path or not _PATH.fullmatch(path):
        return
    try:
        await client.request("DELETE", f"{_base()}/storage/v1/object/{BUCKET}",
                             headers={**storage_links.service_headers(), "Content-Type": "application/json"},
                             json={"prefixes": [path]}, timeout=httpx.Timeout(30.0))
    except Exception as e:  # noqa: BLE001
        logger.warning("academy-work remove: %s", type(e).__name__)


def _limit(bucket: str, key: str) -> None:
    import rate_limit
    if not rate_limit.allow_strict(bucket, key):
        raise HTTPException(429, "That's a lot of uploads at once. Wait a few minutes and try again.")


def _link_key(token: str) -> str:
    """A class link is a credential; the limiter's shared table gets a hash of it."""
    return hashlib.sha256(token.encode()).hexdigest()[:24]


def _ids(*values: str) -> None:
    if not all(_UUID.fullmatch(v or "") for v in values):
        raise HTTPException(404, "Not found")


# ─── Routes ──────────────────────────────────────────────────────────

@router.post("/academy-work/{token}/{item_id}")
async def upload_work(token: str, item_id: str, request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    _ids(token, item_id)
    import rate_limit
    _limit("academy_work_upload", _link_key(token))
    _limit("academy_work_upload_ip", rate_limit.trusted_client_ip(request))
    blob = b""
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        blob += chunk
        if len(blob) > READ_CAP:
            raise HTTPException(413, WORDS["too_big"])
    async with httpx.AsyncClient() as client:
        target, said = await _rpc(client, "academy_item_file_target", {"p_token": token, "p_item": item_id})
        if not target:
            raise _refuse(said)
        found, words = await asyncio.to_thread(classify, blob, file.content_type or "", bool(target.get("photo_only")))
        if not found:
            raise HTTPException(400, words)
        data, mime, ext = found
        try:
            path = object_path(target, ext)
        except ValueError:
            logger.error("academy-work: target ids out of shape")
            raise HTTPException(502, "That didn't save. Try again in a moment.")
        refused = await _store(client, path, data, mime)
        if refused:
            raise HTTPException(502, refused)
        name = display_name(file.filename or "", ext)
        attached, said = await _rpc(client, "academy_item_attach", {"p_token": token, "p_item": item_id, "p_path": path,
                                                                    "p_name": name, "p_type": mime, "p_size": len(data)})
        if not attached:
            await _remove(client, path)
            raise _refuse(said)
        await _remove(client, attached.get("old_path"))
    return {"file_name": attached.get("file_name"), "file_type": attached.get("file_type"),
            "file_size": attached.get("file_size")}


@router.get("/academy-work/{token}/{item_id}")
async def my_work_file(token: str, item_id: str) -> Dict[str, Any]:
    _ids(token, item_id)
    _limit("academy_work_file", _link_key(token))
    async with httpx.AsyncClient() as client:
        mine, said = await _rpc(client, "academy_item_my_file", {"p_token": token, "p_item": item_id})
        if said:
            raise _refuse(said)
        return await _signed(client, mine)


@router.get("/academy-work-file/{work_id}")
async def teacher_work_file(work_id: str, session: UserSession = Depends(require_user_session)) -> Dict[str, Any]:
    _ids(work_id)
    _limit("academy_work_file", session.user.id)
    import sb_clients
    # Read AS THE TEACHER: academy_item_work's teacher-read policy decides who sees it.
    rows = await asyncio.to_thread(sb_clients.sb_get_as_user,
                                   f"/academy_item_work?id=eq.{work_id}&select=file_path,file_name,file_type&limit=1",
                                   session.token)
    async with httpx.AsyncClient() as client:
        return await _signed(client, (rows or [None])[0])


async def _signed(client: httpx.AsyncClient, row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    path = (row or {}).get("file_path")
    if not path or not _PATH.fullmatch(path):
        raise HTTPException(404, "No file here")
    url = await storage_links.signed_url(client, BUCKET, path, ttl=SIGNED_TTL)
    if not url:
        raise HTTPException(502, "That file didn't open. Try again in a moment.")
    return {"url": url, "file_name": row.get("file_name"), "file_type": row.get("file_type")}
