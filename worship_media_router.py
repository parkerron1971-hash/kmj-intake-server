# worship_media_router.py — the church's pictures and videos for Sunday's
# screens (ChurchSavvy, step 2; Kevin 2026-10-19: "a place for library
# stuff ... Videos can get uploaded for video announcements").
#
#   GET     /worship/media                  the library (any seat)
#   POST    /worship/media/start            a slot to upload one file into
#   POST    /worship/media/{id}/finish      check the stored file; it's ready
#   DELETE  /worship/media/{id}             take it out (the file goes too)
#
# The file goes from the browser straight to Supabase Storage (the public
# business-assets bucket, 100 MB a file; resumable, 6 MB chunks), never
# through this server. It lives at a public link because a screen plays it
# with no sign-in and must still have it at the end of a long Sunday.
# Nothing is ready until the server has read the stored file back and it
# is what it says: a picture opens as one (Pillow), a video starts the way
# MP4, MOV or WebM files start. Anything else is deleted.
#
# Behind the same switch as the song library (worship_router.mode()).
from __future__ import annotations

import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import storage_links
from auth_supabase import AuthedUser, require_user
from business_access import assert_access
from worship_router import open_to

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

STAFF_ROLES = ("owner", "admin", "manager")
BUCKET = "business-assets"
CHUNK_BYTES = 6 * 1024 * 1024     # what Supabase's resumable uploads require
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024  # the bucket's own limit
LIBRARY_BYTES = 3 * 1024 * 1024 * 1024
TYPES: Dict[str, tuple] = {
    "image/png": ("image", "png"), "image/jpeg": ("image", "jpg"), "image/webp": ("image", "webp"),
    "video/mp4": ("video", "mp4"), "video/webm": ("video", "webm"), "video/quicktime": ("video", "mov"),
}
_OBJECT = re.compile(r"^[0-9a-f-]{36}/worship-[0-9a-f-]{36}\.(png|jpg|webp|mp4|webm|mov)$")
_FIELDS = "id,kind,name,object_name,mime,bytes,url,status,created_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _supabase() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/")


def _seat(biz: str, user: AuthedUser) -> str:
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    return assert_access(biz, user)


def _staff(biz: str, user: AuthedUser) -> str:
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    role = assert_access(biz, user)
    if role not in STAFF_ROLES:
        raise HTTPException(403, "Only the owner, an admin or a manager changes the library")
    return role


def public_url(object_name: str) -> str:
    return f"{_supabase()}/storage/v1/object/public/{BUCKET}/{object_name}"


def resumable_endpoint() -> str:
    """Large files go straight to the storage host (see clip_finder.resumable_endpoint)."""
    host = urlsplit(_supabase()).hostname or ""
    if host.endswith(".supabase.co"):
        return f"https://{host.split('.')[0]}.storage.supabase.co/storage/v1/upload/resumable/sign"
    return _supabase() + "/storage/v1/upload/resumable/sign"


def upload_token(object_name: str) -> str:
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        r = client.post(f"{_supabase()}/storage/v1/object/upload/sign/{BUCKET}/{object_name}",
                        headers=storage_links.service_headers(), json={})
    if r.status_code != 200:
        raise HTTPException(503, "The upload couldn't be prepared. Try again.")
    data = r.json()
    token = data.get("token") or (parse_qs(urlsplit(data.get("url") or "").query).get("token") or [None])[0]
    if not token:
        raise HTTPException(503, "The upload couldn't be prepared. Try again.")
    return token


def stored_size(object_name: str) -> Optional[int]:
    folder, _, name = object_name.rpartition("/")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        r = client.post(f"{_supabase()}/storage/v1/object/list/{BUCKET}", headers=storage_links.service_headers(),
                        json={"prefix": folder + "/", "search": name, "limit": 5})
    if r.status_code != 200:
        return None
    for item in r.json() or []:
        if item.get("name") == name:
            return int(((item.get("metadata") or {}).get("size")) or 0)
    return None


def read_start(object_name: str, limit: Optional[int]) -> Optional[bytes]:
    """The stored file's first `limit` bytes (all of it when None), read with the service key."""
    headers = dict(storage_links.service_headers())
    if limit:
        headers["Range"] = f"bytes=0-{limit - 1}"
    with httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=False) as client:
        r = client.get(f"{_supabase()}/storage/v1/object/{BUCKET}/{object_name}", headers=headers)
    return r.content if r.status_code in (200, 206) else None


def remove_object(object_name: str) -> None:
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            client.request("DELETE", f"{_supabase()}/storage/v1/object/{BUCKET}", headers=storage_links.service_headers(),
                           json={"prefixes": [object_name]})
    except httpx.HTTPError:
        logger.warning("[worship-media] couldn't remove %s", object_name)


def is_what_it_says(mime: str, head: bytes) -> bool:
    """Does the file start the way its type's files start?"""
    if mime == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if mime in ("video/mp4", "video/quicktime"):
        return len(head) >= 8 and head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip")
    if mime == "video/webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    return False


def picture_opens(data: bytes) -> bool:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001 — anything Pillow can't open isn't a picture
        return False


def _out(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: row.get(k) for k in ("id", "kind", "name", "mime", "bytes", "url", "status", "created_at")}


def _own(biz: str, mid: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/worship_media?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}&archived_at=is.null&select={_FIELDS}")
    if rows is None:
        raise HTTPException(503, "The library couldn't be read. Try again.")
    if not rows:
        raise HTTPException(404, "That picture or video isn't here")
    return rows[0]


@router.get("/media")
def list_media(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    role = _seat(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/worship_media?business_id=eq.{_q(biz)}&archived_at=is.null&status=eq.ready&select={_FIELDS}"
        f"&order=created_at.desc&limit=500")
    if rows is None:
        raise HTTPException(503, "The library couldn't be read. Try again.")
    return {"media": [_out(r) for r in rows], "can_write": role in STAFF_ROLES,
            "used_bytes": sum(int(r.get("bytes") or 0) for r in rows), "limit_bytes": LIBRARY_BYTES}


@router.post("/media/start")
def start_upload(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    mime = str(body.get("mime") or "")
    if mime not in TYPES:
        raise HTTPException(400, "Use a PNG, JPG or WebP picture, or an MP4, MOV or WebM video")
    kind, ext = TYPES[mime]
    size = body.get("bytes")
    cap = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    if not isinstance(size, int) or not 0 < size <= cap:
        raise HTTPException(400, f"A {'picture' if kind == 'image' else 'video'} is at most {cap // (1024 * 1024)} MB")
    name = str(body.get("name") or "").strip()[:120] or ("Picture" if kind == "image" else "Video")
    have = sb_clients.sb_get_as_service(
        f"/worship_media?business_id=eq.{_q(biz)}&archived_at=is.null&status=eq.ready&select=bytes")
    if have is None:
        raise HTTPException(503, "The library couldn't be read. Try again.")
    if sum(int(r.get("bytes") or 0) for r in have) + size > LIBRARY_BYTES:
        raise HTTPException(409, "The library is full (3 GB). Take out pictures or videos you no longer use first.")
    mid = str(uuid.uuid4())
    object_name = f"{biz}/worship-{mid}.{ext}"
    rows = sb_clients.sb_post_as_service(f"/worship_media?select={_FIELDS}", {
        "id": mid, "business_id": biz, "kind": kind, "name": name, "object_name": object_name, "mime": mime,
        "bytes": size, "status": "uploading", "created_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The upload couldn't be prepared. Try again.")
    return {"media": _out(rows[0]), "upload": {
        "endpoint": resumable_endpoint(), "token": upload_token(object_name), "bucket": BUCKET,
        "object_name": object_name, "content_type": mime, "chunk_size": CHUNK_BYTES}}


@router.post("/media/{media_id}/finish")
def finish_upload(media_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    row = _own(biz, _uuid(media_id, "picture or video"))
    if row["status"] == "ready":
        return {"ok": True, "media": _out(row)}
    name = row["object_name"]
    if not _OBJECT.match(name) or not name.startswith(biz + "/"):
        raise HTTPException(409, "That upload isn't this church's")
    if stored_size(name) != int(row["bytes"]):
        raise HTTPException(409, "The upload isn't complete yet. Keep this page open until it finishes.")
    whole = row["kind"] == "image"
    data = read_start(name, None if whole else 64)
    ok = bool(data) and is_what_it_says(row["mime"], data) and (not whole or picture_opens(data))
    if not ok:
        remove_object(name)
        sb_clients.sb_patch_as_service(f"/worship_media?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&select=id",
                                       {"archived_at": _now(), "updated_at": _now()})
        raise HTTPException(400, "That file isn't the picture or video it says it is, so it was removed.")
    rows = sb_clients.sb_patch_as_service(
        f"/worship_media?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&select={_FIELDS}",
        {"status": "ready", "url": public_url(name), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The upload is stored but couldn't be marked ready. Press Finish again.")
    return {"ok": True, "media": _out(rows[0])}


@router.delete("/media/{media_id}")
def remove_media(media_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user)
    row = _own(biz, _uuid(media_id, "picture or video"))
    rows = sb_clients.sb_patch_as_service(f"/worship_media?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}&select=id",
                                          {"archived_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't take it out. Try again.")
    if _OBJECT.match(row["object_name"]) and row["object_name"].startswith(biz + "/"):
        remove_object(row["object_name"])
    return {"ok": True}
