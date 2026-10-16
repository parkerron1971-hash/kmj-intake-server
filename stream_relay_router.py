"""
stream_relay_router.py — our own stream relay, the system's side (2026-10-16).

The church's streaming software (OBS, ProPresenter...) sends ONE stream to
our relay server instead of to YouTube. The relay (stream_relay/ in this
repo, on a DigitalOcean droplet) passes copies on to YouTube and Facebook
unchanged and writes the service to a PRIVATE Cloudflare R2 bucket as it
streams. So:

  * members watch live in the member app through our player page here,
    which hands out short-lived signed links to the bucket (no cost per
    viewer, nothing in the bucket is public);
  * the recording becomes an unpublished sermon draft when the service
    ends, playable only by the church's managers until they publish it;
  * YouTube and Facebook still get the stream, exactly as today.

The team's side (a manager or the owner — the live_router check):

  GET   /stream-relay?business_id=      the address, the key's last 4, where copies go, live now, recent
  POST  /stream-relay/key               {business_id}  — make (or replace) the stream key; shown ONCE
  PATCH /stream-relay/settings          {business_id, youtube_key?, youtube_on?, facebook_key?,
                                         facebook_on?, sermon_drafts?}

Anyone, checked per request (the player and its playlist):

  GET   /stream-relay/watch/<session>           our player page
  GET   /stream-relay/media/<session>/index.m3u8
        Plays while the stream is live, or once a PUBLISHED sermon carries
        it, or with a manager's signed link (?t=, minted in the overview,
        hours long). Anything else is a 404. Every segment line is a
        presigned R2 link that expires; the bucket itself is never public.

The relay's side (the shared secret in X-Relay-Secret; fails closed, and
answers 403 while streaming is switched off):

  POST  /stream-relay/relay/verify      {stream_id, key}  — may this key stream? where copies go
  POST  /stream-relay/relay/started     {stream_id, key, run_id, recorded_s?, bytes?}
        The stream is up, AND the relay's heartbeat (every minute while it
        is): opens or repairs the session and its live service, records
        that the relay still holds it, and returns where copies go now (so
        a removed key or a rotated stream key takes effect within a minute).
        The session id is derived from the relay's run id, so a retry after
        a half-finished start repairs the same session.
  POST  /stream-relay/relay/ended       {session_id, duration_s, bytes}
        Close it: end the live service, save the draft, then mark it ended.
        200 only when all three are saved; a retry, or two at once, makes
        one draft (its id is derived from the session's). Works while
        switched off, so turning streaming off never strands a service.

A live session the relay stops reporting (a lost droplet, an end that never
got through) is closed by sweep_stale(), run every 10 minutes and before an
overview, so it is never reused next Sunday.

The church's stream key is `<stream_id>?key=<secret>`: the relay's path is
the stream id (not secret; logs show it), the secret rides in the query
(never logged). Only sha256(secret) is stored; the church sees it once.
YouTube / Facebook keys are Fernet ciphertext (STREAM_DEST_ENCRYPTION_KEY)
and are decrypted only for the relay. The tables are server-only
(APPLY-2026-10-16-stream-relay.sql, APPLY-2026-10-16-stream-relay-heartbeat.sql).

Env (all of them make the feature "ready"; without them it stays quiet):
  STREAM_RELAY_SECRET          shared with the relay server
  STREAM_DEST_ENCRYPTION_KEY   Fernet key for the YouTube/Facebook keys (also signs managers' links)
  STREAM_INGEST_URL            what the church types as the server, rtmps://stream.<domain>:443/live
  STREAM_R2_ENDPOINT           https://<account>.r2.cloudflarestorage.com
  STREAM_R2_BUCKET             the private media bucket
  STREAM_R2_ACCESS_KEY_ID      an R2 token with READ on that bucket only
  STREAM_R2_SECRET_ACCESS_KEY
"""
from __future__ import annotations

import hashlib
import hmac
import html as _html
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import _uuid, require

router = APIRouter(tags=["stream-relay"])

# A sermon draft is made only from a recording at least this long: a
# sound check or a dropped test stream is not a service.
DRAFT_MIN_SECONDS = 5 * 60
# A live session the relay hasn't reported for this long is over. The
# relay reports every minute, and waits 10 minutes for a dropped stream,
# so this only fires for a lost relay or a finish that never got through.
STALE_S = 45 * 60
# Members hear "live now" at most once in this window per church: a
# sound check and the service an hour later are one alert, not two.
LIVE_ALERT_COOLDOWN_S = 3 * 3600
# A manager's link to a recording works this long.
STAFF_LINK_S = 6 * 3600
# Each segment link in a playlist works this long, and is re-signed
# after RESIGN_S so a link handed out is always good for hours.
SEGMENT_LINK_S = 4 * 3600
SEGMENT_RESIGN_S = 3600

DEST_KEY_MAX = 300
_DEST_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.?=&]+$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
STREAM_ID_RE = re.compile(r"^[0-9a-f]{20}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
SEGMENT_RE = re.compile(r"^seg_\d{6}\.ts$")
# Ids derived from other ids (a session from the relay's run, a draft and a
# live service from their session), so a retry lands on the same row.
_NS = uuid.UUID("5b0e3c1e-8f4a-4d7b-9a35-4e0f2c6d1a77")

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


def r2_config() -> Dict[str, str]:
    return {"endpoint": _env("STREAM_R2_ENDPOINT").rstrip("/"), "bucket": _env("STREAM_R2_BUCKET"),
            "key_id": _env("STREAM_R2_ACCESS_KEY_ID"), "secret": _env("STREAM_R2_SECRET_ACCESS_KEY")}


def _fernet_ok(k: str) -> bool:
    try:
        from cryptography.fernet import Fernet
        Fernet(k.encode("ascii"))
        return True
    except Exception:
        return False


def is_ready() -> bool:
    """Every setting present AND sane: ingest is encrypted (rtmps), the
    bucket is reached over https, the encryption key is a real key."""
    r2 = r2_config()
    return (bool(_env("STREAM_RELAY_SECRET")) and _fernet_ok(_env("STREAM_DEST_ENCRYPTION_KEY"))
            and ingest_url().startswith("rtmps://") and r2["endpoint"].startswith("https://")
            and all(r2.values()))


def player_base() -> str:
    from chief_host import FALLBACK_BASE
    return FALLBACK_BASE.rstrip("/")


def _not_ready() -> HTTPException:
    return HTTPException(503, "Streaming from your church isn't switched on yet.")


def _unavailable() -> HTTPException:
    return HTTPException(503, "Streaming settings couldn't load just now. Please try again.")


# ─── pure helpers ────────────────────────────────────────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def key_hash(secret: str) -> str:
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def stream_id_for(business_id: str) -> str:
    """The church's path on the relay (live/<stream_id>). Not a secret —
    the relay's logs show it — and it never changes, so a new key needs
    only the key pasted again."""
    return hashlib.sha256(f"stream-id:v1:{business_id}".encode("utf-8")).hexdigest()[:20]


def new_secret() -> str:
    """32 URL-safe characters: the part of the key that is the password."""
    return secrets.token_urlsafe(24)


def full_key(business_id: str, secret: str) -> str:
    """What the church pastes as its stream key: the path, then the secret
    as a query (`?key=`), which the relay reads and never logs."""
    return f"{stream_id_for(business_id)}?key={secret}"


def derived_id(kind: str, of: str) -> str:
    return str(uuid.uuid5(_NS, f"{kind}:{of}"))


def session_id_for(business_id: str, run_id: str) -> str:
    return derived_id("session", f"{business_id}:{run_id}")


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


def watch_url(session_id: str) -> str:
    """The recording's one link (a live service's stream_url, a draft's
    video_url). It is a page that checks, not a file anyone can fetch."""
    return f"{player_base()}/stream-relay/watch/{session_id}"


def watch_session(url: str) -> Optional[str]:
    """The session id when `url` is one of our own watch links, else None.
    Used by sermons_public.video_embed_src."""
    try:
        p, b = urlparse((url or "").strip()), urlparse(player_base())
    except ValueError:
        return None
    if p.scheme != "https" or not p.hostname or p.hostname.lower() != (b.hostname or "").lower():
        return None
    m = re.match(r"^/stream-relay/watch/([0-9a-f-]{36})$", p.path or "")
    return m.group(1) if m and UUID_RE.match(m.group(1)) else None


# A manager's link: <expiry>.<hmac>, bound to one session.

def _token_key() -> bytes:
    return hmac.new(_env("STREAM_DEST_ENCRYPTION_KEY").encode("utf-8"), b"stream-media-token-v1",
                    hashlib.sha256).digest()


def staff_token(session_id: str, now: Optional[float] = None) -> str:
    exp = int(now if now is not None else time.time()) + STAFF_LINK_S
    sig = hmac.new(_token_key(), f"{session_id}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def token_ok(session_id: str, token: str, now: Optional[float] = None) -> bool:
    exp, _, sig = (token or "").partition(".")
    if not exp.isdigit() or not sig or not _env("STREAM_DEST_ENCRYPTION_KEY"):
        return False
    if int(exp) < int(now if now is not None else time.time()):
        return False
    want = hmac.new(_token_key(), f"{session_id}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig)


def staff_watch_url(session_id: str) -> str:
    return f"{watch_url(session_id)}?t={staff_token(session_id)}"


# R2 is S3: a GET link signed with AWS Signature V4 in the query string.
# Hand-rolled (no boto3 on this server); checked against AWS's published
# example in the tests.

def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4_presign(scheme: str, host: str, path: str, *, key_id: str, secret: str, expires: int,
                  when: datetime, region: str = "auto") -> str:
    amz_date = when.strftime("%Y%m%dT%H%M%SZ")
    day = when.strftime("%Y%m%d")
    scope = f"{day}/{region}/s3/aws4_request"
    params = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{key_id}/{scope}",
              "X-Amz-Date": amz_date, "X-Amz-Expires": str(int(expires)), "X-Amz-SignedHeaders": "host"}
    query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items()))
    canonical = "\n".join(["GET", path, query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    k = _hmac(_hmac(_hmac(_hmac(f"AWS4{secret}".encode("utf-8"), day), region), "s3"), "aws4_request")
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{scheme}://{host}{path}?{query}&X-Amz-Signature={sig}"


def r2_link(object_key: str, expires: int = SEGMENT_LINK_S) -> str:
    """A link to one private object, good for `expires` seconds."""
    r2 = r2_config()
    ep = urlparse(r2["endpoint"])
    path = "/" + quote(r2["bucket"], safe="") + "/" + quote(object_key, safe="/-_.~")
    return sigv4_presign(ep.scheme, ep.netloc, path, key_id=r2["key_id"], secret=r2["secret"],
                         expires=expires, when=datetime.now(timezone.utc))


def r2_origin() -> str:
    ep = urlparse(r2_config()["endpoint"])
    return f"{ep.scheme}://{ep.netloc}" if ep.netloc else ""


def sign_playlist(text: str, prefix: str, link: Callable[[str], str]) -> str:
    """Our playlist with every segment line swapped for a signed link.
    Only our own segment names survive; anything else (and its #EXTINF)
    is dropped, so the bucket is never named or listed."""
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            out.append(line)
        elif SEGMENT_RE.match(line):
            out.append(link(f"{prefix}/{line}"))
        elif out and out[-1].startswith("#EXTINF"):
            out.pop()
    return "\n".join(out) + "\n"


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


def _parse_ts(v: Any) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


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


_SESSION_COLS = "id,business_id,status,live_session_id,sermon_id,playlist_path,duration_s,bytes,started_at,ended_at"


def _sessions(business_id: str, *, live: bool, limit: int) -> Optional[List[Dict[str, Any]]]:
    status = "live" if live else "ended"
    rows = sb_clients.sb_get_as_service(
        f"/stream_sessions?business_id=eq.{_q(business_id)}&status=eq.{status}"
        f"&select={_SESSION_COLS}&order=started_at.desc&limit={int(limit)}")
    return rows if isinstance(rows, list) else None


def _session(sid: str) -> Optional[Dict[str, Any]]:
    """One session, {} when there is none, None when the read failed."""
    rows = sb_clients.sb_get_as_service(f"/stream_sessions?id=eq.{_q(sid)}&select={_SESSION_COLS}&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "has_key": bool(row.get("key_hash")),
        "key_last4": row.get("key_last4") or "",
        "youtube": {"on": bool(row.get("youtube_on")), "saved": bool(row.get("youtube_key_enc"))},
        "facebook": {"on": bool(row.get("facebook_on")), "saved": bool(row.get("facebook_key_enc"))},
        "sermon_drafts": bool(row.get("sermon_drafts", True)),
    }


def _view(s: Dict[str, Any]) -> Dict[str, Any]:
    """A session as a manager sees it, with a link only they can play."""
    return {k: s.get(k) for k in ("id", "status", "sermon_id", "duration_s", "started_at", "ended_at")} | {
        "watch_url": staff_watch_url(str(s["id"]))}


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


_OFF = {"ready": False, "server": "", "has_key": False, "key_last4": "",
        "youtube": {"on": False, "saved": False}, "facebook": {"on": False, "saved": False},
        "sermon_drafts": True, "live": None, "recent": []}


@router.get("/stream-relay")
def stream_overview(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "manager")
    if not is_ready():
        return dict(_OFF)
    row = stream_row(biz)
    if row is None:
        raise _unavailable()
    sweep_stale(biz)
    live = _sessions(biz, live=True, limit=1)
    recent = _sessions(biz, live=False, limit=10)
    if live is None or recent is None:
        raise _unavailable()
    return {
        "ready": True,
        "server": ingest_url(),
        **_public(row),
        "live": _view(live[0]) if live else None,
        "recent": [_view(r) for r in recent],
    }


@router.post("/stream-relay/key")
def stream_new_key(body: BizIn, user: AuthedUser = Depends(require_user)):
    """Make the church's stream key, or replace it (the old one stops
    working at once, and a stream on it is cut within a minute). The full
    key is in this response and nowhere else."""
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    if not is_ready():
        raise _not_ready()
    row = stream_row(biz)
    if row is None:
        raise _unavailable()
    secret = new_secret()
    fields = {"key_hash": key_hash(secret), "key_last4": secret[-4:], "updated_at": now_iso()}
    if row:
        saved = sb_clients.sb_patch_as_service(f"/church_streams?business_id=eq.{_q(biz)}", fields)
    else:
        saved = sb_clients.sb_post_as_service("/church_streams", {"business_id": biz, **fields})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "The stream key didn't save. Please try again.")
    return {"ok": True, "key": full_key(biz, secret), "server": ingest_url(), **_public(saved[0])}


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


# ─── the player: who may watch what ─────────────────────────────────


class _Cache:
    """Small, per-process, thread-safe: the player polls its playlist every
    few seconds while live, and one database read and one bucket read per
    poll per viewer would be wasteful."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.access: Dict[str, Tuple[float, Optional[Dict[str, Any]], bool]] = {}
        self.lists: Dict[str, Tuple[float, str]] = {}
        self.links: Dict[str, Tuple[float, Dict[str, Tuple[str, float]]]] = {}

    def clear(self) -> None:
        with self.lock:
            self.access.clear()
            self.lists.clear()
            self.links.clear()


_cache = _Cache()
ACCESS_TTL_S = 10


def _published(biz: str, sid: str) -> Optional[bool]:
    """Does a PUBLISHED sermon of this church carry this recording?"""
    rows = sb_clients.sb_get_as_service(
        f"/sermons?business_id=eq.{_q(biz)}&published=eq.true"
        f"&video_url=like.{_q('*/stream-relay/watch/' + sid)}&select=id&limit=1")
    return bool(rows) if isinstance(rows, list) else None


def _access(sid: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(session, public?) — cached a few seconds. Raises 503 on a failed read."""
    now = time.time()
    with _cache.lock:
        hit = _cache.access.get(sid)
    if hit and now - hit[0] < ACCESS_TTL_S:
        return hit[1], hit[2]
    s = _session(sid)
    if s is None:
        raise HTTPException(503, "Couldn't load just now.")
    public = False
    if s:
        if s.get("status") == "live":
            public = True
        else:
            pub = _published(str(s["business_id"]), sid)
            if pub is None:
                raise HTTPException(503, "Couldn't load just now.")
            public = pub
    with _cache.lock:
        _cache.access[sid] = (now, s or None, public)
    return s or None, public


def media_access(sid: str, token: str) -> Dict[str, Any]:
    """The session when this request may play it; 404 otherwise. Live is
    public (it is on YouTube at the same moment); afterwards only a
    published sermon makes it public, and a manager's signed link plays a
    draft."""
    sid = (sid or "").lower()
    if not UUID_RE.match(sid) or not is_ready():
        raise HTTPException(404, "Not found")
    s, public = _access(sid)
    if not s:
        raise HTTPException(404, "Not found")
    if public or token_ok(sid, token):
        return s
    raise HTTPException(404, "Not found")


def _playlist_text(s: Dict[str, Any]) -> Optional[str]:
    """The playlist as the relay last wrote it. None when it isn't there yet."""
    sid = str(s["id"])
    ttl = 2 if s.get("status") == "live" else 60
    now = time.time()
    with _cache.lock:
        hit = _cache.lists.get(sid)
    if hit and now - hit[0] < ttl:
        return hit[1]
    import httpx
    try:
        r = httpx.get(r2_link(str(s.get("playlist_path") or playlist_path(str(s["business_id"]), sid)), 60),
                      timeout=5)
    except httpx.HTTPError:
        raise HTTPException(503, "Couldn't load just now.")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise HTTPException(503, "Couldn't load just now.")
    with _cache.lock:
        _cache.lists[sid] = (now, r.text)
    return r.text


def _segment_link(sid: str, object_key: str) -> str:
    now = time.time()
    with _cache.lock:
        seen, links = _cache.links.get(sid, (now, {}))
        hit = links.get(object_key)
        if hit and now - hit[1] < SEGMENT_RESIGN_S:
            _cache.links[sid] = (now, links)
            return hit[0]
    url = r2_link(object_key)
    with _cache.lock:
        seen, links = _cache.links.get(sid, (now, {}))
        links[object_key] = (url, now)
        _cache.links[sid] = (now, links)
        for other in [k for k, (t, _) in _cache.links.items() if now - t > 2 * 3600]:
            _cache.links.pop(other, None)
    return url


_HLS = ('<script nonce="{n}" src="https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js" '
        'integrity="sha384-9v3HcdYrO3D+OPDTjZ40RXocgE4GtXVCd3/mCS62JsM93JXgI1afJVuwjFvsu6ni" '
        'crossorigin="anonymous"></script>')
_PLAYER_JS = r"""(function () {
  var video = document.getElementById('v');
  var note = document.getElementById('note');
  function say(text) { note.textContent = text; note.hidden = false; video.hidden = true; }
  var src = video.getAttribute('data-src');
  if (window.Hls && Hls.isSupported()) {
    var hls = new Hls({ liveSyncDurationCount: 3, maxBufferLength: 30 });
    var tries = 0;
    hls.on(Hls.Events.ERROR, function (_e, data) {
      if (!data.fatal) return;
      if (data.type === Hls.ErrorTypes.MEDIA_ERROR && tries < 3) { tries++; hls.recoverMediaError(); return; }
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR && tries < 20) {
        tries++;   // a live service that dropped for a moment comes back
        setTimeout(function () { hls.loadSource(src); }, 3000);
        return;
      }
      say("The video stopped. Please refresh to try again.");
    });
    hls.on(Hls.Events.MANIFEST_PARSED, function () { tries = 0; });
    hls.loadSource(src);
    hls.attachMedia(video);
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = src;   // Safari and iPhones play this natively
  } else {
    say("This browser can't play the video. Try another browser.");
  }
})();"""


def _page(body: str, nonce: str, status: int) -> Response:
    css = ("html,body{margin:0;height:100%;background:#000;color:#f0efec;"
           "font:15px/1.4 system-ui,-apple-system,'Segoe UI',sans-serif}"
           "video{display:block;width:100%;height:100%;background:#000}"
           "#note{position:absolute;inset:0;display:grid;place-items:center;padding:16px;text-align:center}"
           "#note[hidden]{display:none}")
    doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta name="referrer" content="no-referrer"><title>Service video</title>'
           f'<style nonce="{nonce}">{css}</style></head><body>{body}</body></html>')
    r2 = r2_origin()
    csp = (f"default-src 'none'; script-src 'nonce-{nonce}' https://cdn.jsdelivr.net; "
           f"style-src 'nonce-{nonce}'; media-src 'self' blob: {r2}; connect-src 'self' {r2}; "
           "worker-src blob:; img-src data:; base-uri 'none'; form-action 'none'")
    return Response(doc, status_code=status, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": csp, "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.get("/stream-relay/watch/{session_id}")
def watch_page(session_id: str, t: str = Query(default="", max_length=200)):
    """Our player. Embedded by the member app and church sites (iframe)."""
    nonce = secrets.token_urlsafe(12)
    sid = (session_id or "").lower()
    try:
        media_access(sid, t)
    except HTTPException as e:
        text = "This video isn't available." if e.status_code == 404 else "This video couldn't load. Please try again."
        return _page(f'<p id="note">{text}</p>', nonce, e.status_code)
    src = f"/stream-relay/media/{sid}/index.m3u8" + (f"?t={quote(t, safe='.')}" if t else "")
    body = (f'<video id="v" controls playsinline preload="metadata" data-src="{_html.escape(src)}"></video>'
            f'<p id="note" hidden></p>{_HLS.format(n=nonce)}<script nonce="{nonce}">{_PLAYER_JS}</script>')
    return _page(body, nonce, 200)


@router.get("/stream-relay/media/{session_id}/index.m3u8")
def media_playlist(session_id: str, t: str = Query(default="", max_length=200)):
    s = media_access(session_id, t)
    sid = str(s["id"])
    text = _playlist_text(s)
    if text is None:
        raise HTTPException(404, "Not found")
    prefix = str(s.get("playlist_path") or playlist_path(str(s["business_id"]), sid)).rsplit("/", 1)[0]
    body = sign_playlist(text, prefix, lambda k: _segment_link(sid, k))
    live = s.get("status") == "live"
    return Response(body, media_type="application/vnd.apple.mpegurl", headers={
        "Cache-Control": "no-store" if live else "private, max-age=30",
        "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})


# ─── the relay's routes ──────────────────────────────────────────────


def require_relay(secret: Optional[str]) -> None:
    """Fails closed: no secret configured means no relay can talk to us."""
    expected = _env("STREAM_RELAY_SECRET")
    if not expected:
        raise HTTPException(503, "relay not configured")
    if not secret or not hmac.compare_digest(secret.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(401, "bad relay secret")


def require_switched_on() -> None:
    """Switched off (or half set up) means no church streams: 403, which
    the relay takes as a refusal (cut the stream, forget the key), never as
    "the backend is down" (keep going on what it remembers)."""
    if not is_ready():
        raise HTTPException(403, "streaming is switched off")


class VerifyIn(BaseModel):
    stream_id: str = Field(min_length=20, max_length=20)
    key: str = Field(min_length=16, max_length=200)


class StartIn(VerifyIn):
    run_id: str = Field(min_length=36, max_length=36)
    recorded_s: int = Field(default=0, ge=0, le=7 * 24 * 3600)
    bytes: int = Field(default=0, ge=0)


class EndedIn(BaseModel):
    session_id: str
    duration_s: int = Field(default=0, ge=0, le=7 * 24 * 3600)
    bytes: int = Field(default=0, ge=0)


def church_from_stream_key(stream_id: str, key: str) -> Dict[str, Any]:
    """The church a stream key belongs to. The relay never names a
    business: it comes from the key's own row, and an unknown or replaced
    key, or a key presented on another church's path, is refused
    (ownership_sweep counts this as the check)."""
    if not STREAM_ID_RE.match(stream_id or "") or not SECRET_RE.match(key or ""):
        raise HTTPException(403, "unknown stream key")
    rows = sb_clients.sb_get_as_service(
        f"/church_streams?key_hash=eq.{key_hash(key)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "read failed")
    if not rows or not hmac.compare_digest(stream_id_for(str(rows[0]["business_id"])), stream_id):
        raise HTTPException(403, "unknown stream key")
    return rows[0]


@router.post("/stream-relay/relay/verify")
def relay_verify(body: VerifyIn, x_relay_secret: Optional[str] = Header(default=None)):
    require_relay(x_relay_secret)
    require_switched_on()
    row = church_from_stream_key(body.stream_id, body.key)
    return {"ok": True, "destinations": destinations_for(row)}


@router.post("/stream-relay/relay/started")
def relay_started(body: StartIn, x_relay_secret: Optional[str] = Header(default=None)):
    """The stream is up — the first time, and every minute after (the
    relay's heartbeat). Every step is repeatable: a retry after a step
    failed finishes what is missing."""
    require_relay(x_relay_secret)
    require_switched_on()
    row = church_from_stream_key(body.stream_id, body.key)
    biz = str(row["business_id"])
    run = (body.run_id or "").lower()
    if not UUID_RE.match(run):
        raise HTTPException(400, "bad run id")
    sid = session_id_for(biz, run)
    live = _sessions(biz, live=True, limit=1)
    if live is None:
        raise HTTPException(503, "read failed")
    s = live[0] if live else None
    if s and str(s["id"]) != sid:
        # Another run's session: that relay run is over (its end may still
        # be on the way) or that relay is gone. Close it before this one.
        finalize(s, int(s.get("duration_s") or 0), int(s.get("bytes") or 0))
        s = None
    if s is None:
        s = _open_session(biz, sid)
    _ensure_live_service(biz, s)
    _beat(sid, body.recorded_s, body.bytes)
    return {
        "ok": True,
        "session_id": sid,
        "business_id": biz,
        "playlist_path": s.get("playlist_path") or playlist_path(biz, sid),
        "destinations": destinations_for(row),
    }


def _open_session(biz: str, sid: str) -> Dict[str, Any]:
    old = _session(sid)
    if old is None:
        raise HTTPException(503, "read failed")
    if old:
        # This run's session was already closed (by the sweep, after the
        # relay went quiet too long). The relay starts a new run.
        raise HTTPException(409, "session ended")
    made = sb_clients.sb_post_as_service("/stream_sessions", {
        "id": sid, "business_id": biz, "status": "live", "playlist_path": playlist_path(biz, sid),
        "last_seen_at": now_iso()})
    if not isinstance(made, list) or not made:
        raise HTTPException(503, "session didn't save")
    return made[0]


def _ensure_live_service(biz: str, s: Dict[str, Any]) -> None:
    """Go live in the member app with our own player, unless the team went
    live with another link (theirs is left alone). A failed read is not
    "the team went live" — it is a 503, and the relay asks again."""
    if s.get("live_session_id"):
        return
    sid = str(s["id"])
    import live_router
    cur = live_router.current(biz)
    if cur is None:
        raise HTTPException(503, "live read failed")
    ours = watch_url(sid)
    if cur and cur.get("stream_url") != ours:
        return
    if cur:
        live_row = cur                       # ours, opened before but never linked
    else:
        made = sb_clients.sb_post_as_service("/live_sessions", {
            "id": derived_id("live", sid), "business_id": biz, "title": "Live now",
            "stream_url": ours, "status": "live", "chat_open": True})
        if not isinstance(made, list) or not made:
            raise HTTPException(503, "live service didn't save")
        live_row = made[0]
    linked = sb_clients.sb_patch_as_service(f"/stream_sessions?id=eq.{_q(sid)}",
                                            {"live_session_id": live_row["id"]})
    if not isinstance(linked, list) or not linked:
        raise HTTPException(503, "link didn't save")
    s["live_session_id"] = live_row["id"]
    _alert_members(biz, live_row)


def _alert_members(biz: str, live_row: Dict[str, Any]) -> None:
    """"Live now" for members — at most once per LIVE_ALERT_COOLDOWN_S per
    church (a sound check and the service are one alert). The push itself
    is deduplicated per live service (member_push's ref)."""
    since = (datetime.now(timezone.utc) - timedelta(seconds=LIVE_ALERT_COOLDOWN_S)).isoformat()
    others = sb_clients.sb_get_as_service(
        f"/live_sessions?business_id=eq.{_q(biz)}&started_at=gte.{_q(since)}"
        f"&id=neq.{_q(live_row['id'])}&select=id&limit=1")
    if not isinstance(others, list) or others:
        return
    import live_router
    live_router._tell_members_live(biz, live_row)


def _beat(sid: str, recorded_s: int, size: int) -> None:
    """The relay still holds this stream. Best effort: a missed beat only
    matters after STALE_S of them."""
    patch: Dict[str, Any] = {"last_seen_at": now_iso()}
    if recorded_s:
        patch["duration_s"] = int(recorded_s)
    if size:
        patch["bytes"] = int(size)
    sb_clients.sb_patch_as_service(f"/stream_sessions?id=eq.{_q(sid)}&status=eq.live", patch)


@router.post("/stream-relay/relay/ended")
def relay_ended(body: EndedIn, x_relay_secret: Optional[str] = Header(default=None)):
    """The stream stopped and did not come back. 200 only once the live
    service is closed, the draft saved and the session marked ended."""
    require_relay(x_relay_secret)
    sid = (body.session_id or "").lower()
    if not UUID_RE.match(sid):
        raise HTTPException(400, "bad session id")
    s = _session(sid)
    if s is None:
        raise HTTPException(503, "read failed")
    if not s:
        raise HTTPException(404, "no such session")
    sermon_id = finalize(s, body.duration_s, body.bytes)
    return {"ok": True, "sermon_id": sermon_id}


def finalize(s: Dict[str, Any], duration_s: int, size: int) -> Optional[str]:
    """Close one session, every step repeatable, 'ended' written LAST so a
    failed step is retried rather than skipped. Raises 503 on any failed
    write. Two at once make one draft: its id is the session's own."""
    if s.get("status") == "ended":
        return s.get("sermon_id")
    sid, biz = str(s["id"]), str(s["business_id"])
    ended = now_iso()
    duration = max(int(duration_s or 0), int(s.get("duration_s") or 0))
    for live_id in {derived_id("live", sid), str(s.get("live_session_id") or "")} - {""}:
        closed = sb_clients.sb_patch_as_service(
            f"/live_sessions?id=eq.{_q(live_id)}&status=eq.live",
            {"status": "ended", "ended_at": ended, "updated_at": ended})
        if not isinstance(closed, list):
            raise HTTPException(503, "live service didn't close")
    sermon_id = None
    church = stream_row(biz)
    if church is None:
        raise HTTPException(503, "read failed")
    if church and church.get("sermon_drafts", True) and duration >= DRAFT_MIN_SECONDS:
        sermon_id = _sermon_draft(biz, s)
    done = sb_clients.sb_patch_as_service(f"/stream_sessions?id=eq.{_q(sid)}&status=eq.live", {
        "status": "ended", "ended_at": ended, "duration_s": duration,
        "bytes": max(int(size or 0), int(s.get("bytes") or 0)), "sermon_id": sermon_id})
    if not isinstance(done, list):
        raise HTTPException(503, "session didn't close")
    with _cache.lock:
        _cache.access.pop(sid, None)
    return sermon_id


def _church_tz(biz: str):
    """The church's own clock (the marketing desk's one chain), UTC if unknown."""
    try:
        import business_marketing
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{_q(biz)}&select=id,owner_id,settings&limit=1") or []
        if rows:
            return business_marketing.business_tz(rows[0])
    except Exception:
        pass
    return timezone.utc


def _sermon_draft(biz: str, s: Dict[str, Any]) -> str:
    """An unpublished sermon holding the whole recording, dated by when the
    service STARTED on the church's clock. The team names it and publishes
    it from Sermons. Raises 503 when it didn't save."""
    sid = str(s["id"])
    sermon_id = derived_id("sermon", sid)
    when = (_parse_ts(s.get("started_at")) or datetime.now(timezone.utc)).astimezone(_church_tz(biz))
    made = sb_clients.sb_post_as_service("/sermons?on_conflict=id", {
        "id": sermon_id, "business_id": biz, "title": service_title(when),
        "preached_on": when.date().isoformat(), "video_url": watch_url(sid), "published": False},
        prefer="return=representation,resolution=ignore-duplicates")
    if not isinstance(made, list):
        raise HTTPException(503, "draft didn't save")
    return sermon_id


def sweep_stale(business_id: Optional[str] = None) -> int:
    """Close live sessions the relay stopped reporting (STALE_S). Quiet on
    any failure; the next sweep tries again. Before the heartbeat column
    exists (APPLY-2026-10-16-stream-relay-heartbeat.sql) it does nothing."""
    if not is_ready():
        return 0
    only = f"&business_id=eq.{_q(business_id)}" if business_id else ""
    rows = sb_clients.sb_get_as_service(f"/stream_sessions?status=eq.live{only}&select=*&limit=200")
    if not isinstance(rows, list):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_S)
    closed = 0
    for s in rows:
        if "last_seen_at" not in s:
            return 0
        seen = _parse_ts(s.get("last_seen_at") or s.get("started_at"))
        if seen and seen < cutoff:
            try:
                finalize(s, int(s.get("duration_s") or 0), int(s.get("bytes") or 0))
                closed += 1
            except HTTPException:
                continue
    return closed
