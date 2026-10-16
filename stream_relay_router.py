"""
stream_relay_router.py — our own stream relay, the system's side (2026-10-16).

The church's streaming software (OBS, ProPresenter...) sends ONE stream to
our relay server instead of to YouTube. The relay (stream_relay/ in this
repo, on a DigitalOcean droplet) passes copies on to YouTube and Facebook
unchanged and writes the service to Cloudflare R2 as it streams. So:

  * members watch live in the member app, from R2, at no cost per viewer;
  * the recording becomes a sermon draft when the service ends;
  * YouTube and Facebook still get the stream, exactly as today.

The team's side (a manager or the owner — the live_router check):

  GET   /stream-relay?business_id=      the address, the key's last 4, where copies go, live now, recent
  POST  /stream-relay/key               {business_id}  — make (or replace) the stream key; shown ONCE
  PATCH /stream-relay/settings          {business_id, youtube_key?, youtube_on?, facebook_key?,
                                         facebook_on?, sermon_drafts?}

The relay's side (the shared secret in X-Relay-Secret; fails closed):

  POST  /stream-relay/relay/verify      {key}  — may this key stream? No side effects.
  POST  /stream-relay/relay/started     {key}  — the stream is up: open a session, return where copies go
  POST  /stream-relay/relay/ended       {session_id, duration_s, bytes}  — close it, make the sermon draft

Stream keys are stored hashed (sha256); the church sees the full key once.
YouTube / Facebook keys are Fernet ciphertext (STREAM_DEST_ENCRYPTION_KEY)
and are decrypted only for the relay. The tables are server-only
(APPLY-2026-10-16-stream-relay.sql).

Env (all four make the feature "ready"; without them it stays quiet):
  STREAM_RELAY_SECRET          shared with the relay server
  STREAM_DEST_ENCRYPTION_KEY   Fernet key for the YouTube/Facebook keys
  STREAM_INGEST_URL            what the church types as the server, rtmp://stream.<domain>/live
  MEDIA_PUBLIC_BASE            the R2 bucket's public address, https://media.<domain>
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import _uuid, require

router = APIRouter(tags=["stream-relay"])

# A sermon draft is made only from a recording at least this long: a
# sound check or a dropped test stream is not a service.
DRAFT_MIN_SECONDS = 5 * 60
DEST_KEY_MAX = 300
_DEST_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.?=&]+$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Where each platform takes a stream, over TLS. The church pastes only its
# stream key; the address is ours to know.
DESTINATIONS = {
    "youtube": ("YouTube", "rtmps://a.rtmps.youtube.com/live2/"),
    "facebook": ("Facebook", "rtmps://live-api-s.facebook.com:443/rtmp/"),
}
# A pasted full address is cut back to its key.
_PASTED_PREFIXES = (
    "rtmps://a.rtmps.youtube.com/live2/", "rtmp://a.rtmp.youtube.com/live2/",
    "rtmps://b.rtmps.youtube.com/live2/", "rtmp://b.rtmp.youtube.com/live2/",
    "rtmps://live-api-s.facebook.com:443/rtmp/", "rtmps://live-api-s.facebook.com/rtmp/",
)


# ─── config ──────────────────────────────────────────────────────────


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def ingest_url() -> str:
    return _env("STREAM_INGEST_URL").rstrip("/")


def media_base() -> str:
    return _env("MEDIA_PUBLIC_BASE").rstrip("/")


def is_ready() -> bool:
    return all(_env(n) for n in ("STREAM_RELAY_SECRET", "STREAM_DEST_ENCRYPTION_KEY",
                                 "STREAM_INGEST_URL", "MEDIA_PUBLIC_BASE"))


def _not_ready() -> HTTPException:
    return HTTPException(503, "Streaming from your church isn't switched on yet.")


def _unavailable() -> HTTPException:
    return HTTPException(503, "Streaming settings couldn't load just now. Please try again.")


# ─── pure helpers ────────────────────────────────────────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def key_hash(key: str) -> str:
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def new_key() -> str:
    """32 URL-safe characters: it rides in the stream's path (live/<key>)."""
    return secrets.token_urlsafe(24)


def clean_dest_key(raw: Any) -> str:
    """The platform's stream key from what the church pasted: a bare key or
    the whole address. '' clears it. Raises 400 on anything that could
    not be a stream key."""
    k = "".join(str(raw or "").split())
    for prefix in _PASTED_PREFIXES:
        if k.lower().startswith(prefix):
            k = k[len(prefix):]
            break
    if not k:
        return ""
    if len(k) > DEST_KEY_MAX or not _DEST_KEY_RE.match(k):
        raise HTTPException(400, "That doesn't look like a stream key. Copy it again from YouTube or Facebook.")
    return k


def playlist_path(business_id: str, session_id: str) -> str:
    return f"live/{business_id}/{session_id}/index.m3u8"


def playlist_url(path: str) -> str:
    return f"{media_base()}/{path}" if media_base() and path else ""


def is_media_playlist(url: str) -> Optional[str]:
    """The playlist path when `url` is one of our own recordings on the
    media host, else None. Used by sermons_public.video_embed_src."""
    base = media_base()
    if not base:
        return None
    try:
        p, b = urlparse((url or "").strip()), urlparse(base)
    except ValueError:
        return None
    if p.scheme != "https" or not p.hostname or (p.hostname or "").lower() != (b.hostname or "").lower():
        return None
    m = re.match(r"^/(live/[0-9a-f-]{36}/[0-9a-f-]{36}/index\.m3u8)$", p.path or "")
    return m.group(1) if m else None


def player_src(path: str) -> str:
    """Our own player page on the media host (stream_relay/player.html)."""
    return f"{media_base()}/player.html?v={quote('/' + path, safe='/')}"


def _fernet():
    from cryptography.fernet import Fernet
    k = _env("STREAM_DEST_ENCRYPTION_KEY")
    if not k:
        raise _not_ready()
    return Fernet(k.encode("ascii"))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii") if value else ""


def decrypt(value: str) -> str:
    if not value:
        return ""
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def destinations_for(row: Dict[str, Any]) -> List[Dict[str, str]]:
    """Where the relay sends copies, keys decrypted. Only the relay sees this."""
    out = []
    for name, (label, prefix) in DESTINATIONS.items():
        if row.get(f"{name}_on"):
            k = decrypt(row.get(f"{name}_key_enc") or "")
            if k:
                out.append({"name": name, "label": label, "url": prefix + k})
    return out


def service_title(when: datetime) -> str:
    return f"Service, {when.strftime('%B')} {when.day}, {when.year}"


# ─── reads ───────────────────────────────────────────────────────────


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def stream_row(business_id: str) -> Optional[Dict[str, Any]]:
    """The church's row, {} when it has none, None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/church_streams?business_id=eq.{_q(business_id)}&select=*&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def _sessions(business_id: str, *, live: bool, limit: int) -> Optional[List[Dict[str, Any]]]:
    status = "live" if live else "ended"
    rows = sb_clients.sb_get_as_service(
        f"/stream_sessions?business_id=eq.{_q(business_id)}&status=eq.{status}"
        f"&select=id,status,live_session_id,sermon_id,playlist_path,duration_s,started_at,ended_at"
        f"&order=started_at.desc&limit={int(limit)}")
    return rows if isinstance(rows, list) else None


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "has_key": bool(row.get("key_hash")),
        "key_last4": row.get("key_last4") or "",
        "youtube": {"on": bool(row.get("youtube_on")), "saved": bool(row.get("youtube_key_enc"))},
        "facebook": {"on": bool(row.get("facebook_on")), "saved": bool(row.get("facebook_key_enc"))},
        "sermon_drafts": bool(row.get("sermon_drafts", True)),
    }


def _with_urls(s: Dict[str, Any]) -> Dict[str, Any]:
    return {**s, "playlist_url": playlist_url(s.get("playlist_path") or "")}


# ─── team routes ─────────────────────────────────────────────────────


class BizIn(BaseModel):
    business_id: str


class SettingsIn(BaseModel):
    business_id: str
    youtube_key: Optional[str] = Field(default=None, max_length=1000)
    youtube_on: Optional[bool] = None
    facebook_key: Optional[str] = Field(default=None, max_length=1000)
    facebook_on: Optional[bool] = None
    sermon_drafts: Optional[bool] = None


@router.get("/stream-relay")
def stream_overview(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "manager")
    row = stream_row(biz)
    if row is None:
        raise _unavailable()
    live = _sessions(biz, live=True, limit=1)
    recent = _sessions(biz, live=False, limit=10)
    if live is None or recent is None:
        raise _unavailable()
    return {
        "ready": is_ready(),
        "server": ingest_url(),
        **_public(row),
        "live": _with_urls(live[0]) if live else None,
        "recent": [_with_urls(r) for r in recent],
    }


@router.post("/stream-relay/key")
def stream_new_key(body: BizIn, user: AuthedUser = Depends(require_user)):
    """Make the church's stream key, or replace it (the old one stops
    working at once). The full key is in this response and nowhere else."""
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    if not is_ready():
        raise _not_ready()
    row = stream_row(biz)
    if row is None:
        raise _unavailable()
    key = new_key()
    fields = {"key_hash": key_hash(key), "key_last4": key[-4:], "updated_at": now_iso()}
    if row:
        saved = sb_clients.sb_patch_as_service(f"/church_streams?business_id=eq.{_q(biz)}", fields)
    else:
        saved = sb_clients.sb_post_as_service("/church_streams", {"business_id": biz, **fields})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The stream key didn't save. Please try again.")
    return {"ok": True, "key": key, "server": ingest_url(), **_public(saved[0])}


@router.patch("/stream-relay/settings")
def stream_settings(body: SettingsIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    if not is_ready():
        raise _not_ready()
    row = stream_row(biz)
    if row is None:
        raise _unavailable()
    if not row:
        raise HTTPException(409, "Make your stream key first.")
    patch: Dict[str, Any] = {"updated_at": now_iso()}
    for name in DESTINATIONS:
        raw = getattr(body, f"{name}_key")
        if raw is not None:
            k = clean_dest_key(raw)
            patch[f"{name}_key_enc"] = encrypt(k)
            if not k:
                patch[f"{name}_on"] = False
        on = getattr(body, f"{name}_on")
        if on is not None:
            has_key = bool(patch.get(f"{name}_key_enc", row.get(f"{name}_key_enc")))
            if on and not has_key:
                raise HTTPException(400, f"Paste your {DESTINATIONS[name][0]} stream key first.")
            patch[f"{name}_on"] = on
    if body.sermon_drafts is not None:
        patch["sermon_drafts"] = body.sermon_drafts
    saved = sb_clients.sb_patch_as_service(f"/church_streams?business_id=eq.{_q(biz)}", patch)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Please try again.")
    return {"ok": True, **_public(saved[0])}


# ─── the relay's routes ──────────────────────────────────────────────


def require_relay(secret: Optional[str]) -> None:
    """Fails closed: no secret configured means no relay can talk to us."""
    expected = _env("STREAM_RELAY_SECRET")
    if not expected:
        raise HTTPException(503, "relay not configured")
    if not secret or not hmac.compare_digest(secret.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(401, "bad relay secret")


class KeyIn(BaseModel):
    key: str = Field(min_length=8, max_length=200)


class EndedIn(BaseModel):
    session_id: str
    duration_s: int = Field(default=0, ge=0, le=7 * 24 * 3600)
    bytes: int = Field(default=0, ge=0)


def church_from_stream_key(key: str) -> Dict[str, Any]:
    """The church a stream key belongs to. The relay never names a
    business: it comes from the key's own row, and an unknown or replaced
    key is refused (ownership_sweep counts this as the check)."""
    rows = sb_clients.sb_get_as_service(
        f"/church_streams?key_hash=eq.{key_hash(key)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "read failed")
    if not rows:
        raise HTTPException(403, "unknown stream key")
    return rows[0]


@router.post("/stream-relay/relay/verify")
def relay_verify(body: KeyIn, x_relay_secret: Optional[str] = Header(default=None)):
    require_relay(x_relay_secret)
    church_from_stream_key(body.key)
    return {"ok": True}


@router.post("/stream-relay/relay/started")
def relay_started(body: KeyIn, x_relay_secret: Optional[str] = Header(default=None)):
    """The church's stream is up. Idempotent: a relay that restarts mid-
    service, or asks twice, gets the same live session back."""
    require_relay(x_relay_secret)
    row = church_from_stream_key(body.key)
    biz = str(row["business_id"])
    live = _sessions(biz, live=True, limit=1)
    if live is None:
        raise HTTPException(503, "read failed")
    if live:
        s = live[0]
    else:
        made = sb_clients.sb_post_as_service("/stream_sessions", {"business_id": biz, "status": "live"})
        if not isinstance(made, list) or not made:
            again = _sessions(biz, live=True, limit=1)   # two relays raced; the database kept one
            if not again:
                raise HTTPException(503, "session didn't save")
            s = again[0]
        else:
            s = made[0]
            path = playlist_path(biz, str(s["id"]))
            patch = {"playlist_path": path}
            live_id = _open_live_service(biz, playlist_url(path))
            if live_id:
                patch["live_session_id"] = live_id
            sb_clients.sb_patch_as_service(f"/stream_sessions?id=eq.{_q(s['id'])}", patch)
            s = {**s, **patch}
    return {
        "ok": True,
        "session_id": str(s["id"]),
        "business_id": biz,
        "playlist_path": s.get("playlist_path") or playlist_path(biz, str(s["id"])),
        "destinations": destinations_for(row),
    }


def _open_live_service(biz: str, url: str) -> Optional[str]:
    """Go live in the member app with our own player, unless the team
    already went live with another link (theirs is left alone)."""
    import live_router
    cur = live_router.current(biz)
    if cur is None or cur:
        return None
    rows = sb_clients.sb_post_as_service("/live_sessions", {
        "business_id": biz, "title": "Live now", "stream_url": url,
        "status": "live", "chat_open": True})
    if not isinstance(rows, list) or not rows:
        return None
    live_router._tell_members_live(biz, rows[0])
    return str(rows[0]["id"])


@router.post("/stream-relay/relay/ended")
def relay_ended(body: EndedIn, x_relay_secret: Optional[str] = Header(default=None)):
    """The stream stopped and did not come back. Close the session, end
    the live service we opened, and make the sermon draft."""
    require_relay(x_relay_secret)
    sid = (body.session_id or "").lower()
    if not UUID_RE.match(sid):
        raise HTTPException(400, "bad session id")
    rows = sb_clients.sb_get_as_service(f"/stream_sessions?id=eq.{sid}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "read failed")
    if not rows:
        raise HTTPException(404, "no such session")
    s = rows[0]
    if s.get("status") == "ended":
        return {"ok": True, "sermon_id": s.get("sermon_id")}
    biz = str(s["business_id"])
    ended = now_iso()
    sb_clients.sb_patch_as_service(f"/stream_sessions?id=eq.{sid}", {
        "status": "ended", "ended_at": ended, "duration_s": body.duration_s, "bytes": body.bytes})
    if s.get("live_session_id"):
        sb_clients.sb_patch_as_service(
            f"/live_sessions?id=eq.{_q(s['live_session_id'])}&status=eq.live",
            {"status": "ended", "ended_at": ended, "updated_at": ended})
    sermon_id = None
    church = stream_row(biz) or {}
    if church.get("sermon_drafts", True) and body.duration_s >= DRAFT_MIN_SECONDS:
        sermon_id = _sermon_draft(biz, s)
        if sermon_id:
            sb_clients.sb_patch_as_service(f"/stream_sessions?id=eq.{sid}", {"sermon_id": sermon_id})
    return {"ok": True, "sermon_id": sermon_id}


def _local_now(biz: str) -> datetime:
    """The church's own clock (the marketing desk's one chain), UTC if unknown."""
    try:
        import business_marketing
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{_q(biz)}&select=id,owner_id,settings&limit=1") or []
        if rows:
            return datetime.now(business_marketing.business_tz(rows[0]))
    except Exception:
        pass
    return datetime.now(timezone.utc)


def _sermon_draft(biz: str, s: Dict[str, Any]) -> Optional[str]:
    """An unpublished sermon holding the whole recording. The team names
    it and publishes it from Sermons."""
    when = _local_now(biz)
    url = playlist_url(s.get("playlist_path") or "")
    if not url:
        return None
    made = sb_clients.sb_post_as_service("/sermons", {
        "business_id": biz, "title": service_title(when), "preached_on": when.date().isoformat(),
        "video_url": url, "published": False})
    if isinstance(made, list) and made:
        return str(made[0]["id"])
    return None
