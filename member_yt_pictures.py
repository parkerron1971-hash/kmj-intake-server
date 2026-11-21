"""member_yt_pictures.py — a message's own video picture, in the new look.

Love City posts its Sunday services as YouTube links with no series and no
art (its last eight, added 2026-11-21), so in the new look (Look 5.1) every
one of them showed the generated colour wash where the mock shows a real
picture. Now a message with no art of its own shows its video's picture.
The order (member_portal_sermons._art): the series' own art, then the
church's photo named for it (both as before), then this, then the colour
wash. Only in the new look (member_lumen): today's look is unchanged.

THE ADDRESS (picture_url: pure, no read, no write). From the message's own
video link (sermons_public.youtube_id):

  /my/yt/<id>.jpg?k=<signature>      the small picture (rails, rows, the
                                     share sheet's card)
  /my/yt/<id>-w.jpg?k=<signature>    the wide one (a picture drawn across
                                     the phone: Watch's latest, a message's
                                     page, a series, Home's message card,
                                     the story picture)

'' for a link that isn't YouTube. The signature is over the name, so the
route serves only a picture a page of ours drew: the church's address never
serves just any video's picture.

THE PICTURE (GET /my/yt/<name>). Fetched by the server from YouTube's
picture host (i.ytimg.com, nothing else), never by the member's phone: a
page that shows these pictures tells Google nothing about who is looking.
The phone first talks to YouTube when the member opens a message and its
player (youtube-nocookie) loads, as before. The page's own pictures stay on
the church's address, the way the story picture's are read on the server
(member_lumen_share.picture_bytes).
  The small one is YouTube's hqdefault (480 x 360, there for every video,
  with black bars baked in top and bottom); the wide one is maxresdefault
  (1280 x 720) when the video has one, else sddefault, else hqdefault.
  Either is cut to 16:9 at its centre, which takes the bars off exactly, and
  saved as a JPEG of at most 480 or 1280 across. Kept per server copy
  (KEEP_S, within BUDGET bytes; only MISS_S when a sharper picture failed to
  answer on the way; a video with no picture is remembered as that for
  MISS_S; a failed fetch is never kept) and a day by the phone
  (Cache-Control, ETag). The story picture that draws one is never kept
  without it (member_lumen_share.picture). 404 for a name or signature that isn't ours or a
  video with no picture, 503 when YouTube didn't answer. No database read.

Where the picture draws (art()): over the message's own colour wash, so a
picture that can't load leaves the wash, never an empty grey box.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import io
import logging
import re
import threading
import time
from collections import OrderedDict
from html import escape
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger("member_yt_pictures")
router = APIRouter(tags=["member-portal"])

PREFIX = "/my/yt/"
NAME_RE = re.compile(r"^([A-Za-z0-9_-]{11})(-w)?\.jpg$")
UPSTREAM = "https://i.ytimg.com/vi/{vid}/{name}.jpg"
SMALL = ("hqdefault",)
WIDE = ("maxresdefault", "sddefault", "hqdefault")
SMALL_W, WIDE_W = 480, 1280
FETCH_TIMEOUT_S = 5.0
BYTES_MAX = 3 * 1024 * 1024          # one picture from YouTube
PIXELS_MAX = 4_000_000
KEEP_S = 6 * 3600                    # a church may change a video's picture
MISS_S = 600
BUDGET = 24 * 1024 * 1024            # kept pictures, per server copy
PHONE_S = 86400


def _e(v: Any) -> str:
    return escape(str(v if v is not None else ""), quote=True)


# ─── the address ─────────────────────────────────────────────────────


def _key() -> bytes:
    from customer_token import derive_key
    return derive_key("member-yt-picture", "all")


def sign(name: str) -> str:
    raw = hmac.new(_key(), str(name).encode("utf-8"), hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def picture_url(video_url: Any, wide: bool = False) -> str:
    """The message's video picture on our own address, or '' (not a YouTube
    link, or nothing to sign with)."""
    from sermons_public import youtube_id
    vid = youtube_id(str(video_url or ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
        return ""
    name = f"{vid}{'-w' if wide else ''}.jpg"
    try:
        return f"{PREFIX}{name}?k={sign(name)}"
    except Exception:  # noqa: BLE001 — no secret: the colour wash stays
        return ""


def art(url: str, wash: str = "") -> str:
    """The picture as a message's art: a colour photo (member_app_ui.photo's
    markup, so every place that lays out a photo lays this out) over `wash`,
    the message's poster colours (member_app_ui.poster_style)."""
    style = f' style="{_e(wash)}"' if wash else ""
    return (f'<span class="mb-ph is-colour lm-yt"{style} aria-hidden="true"><img src="{_e(url)}" alt="" '
            f'loading="lazy" decoding="async"></span>')


def parse(url: str) -> Optional[Tuple[str, bool]]:
    """(video id, wide) for an address picture_url made, signature checked;
    None for anything else."""
    u = str(url or "")
    if not u.startswith(PREFIX):
        return None
    name, _, query = u[len(PREFIX):].partition("?")
    m = NAME_RE.match(name)
    k = query[2:] if query.startswith("k=") and "&" not in query else ""
    if not m or not k:
        return None
    try:
        good = hmac.compare_digest(k, sign(name))
    except Exception:  # noqa: BLE001
        return None
    return (m.group(1), bool(m.group(2))) if good else None


# ─── the picture ─────────────────────────────────────────────────────

# (video id, wide) -> (kept until, on the server's monotonic clock; the JPEG or b"")
_KEPT: "OrderedDict[Tuple[str, bool], Tuple[float, bytes]]" = OrderedDict()
_LOCK = threading.Lock()


def _fetch(url: str) -> Optional[bytes]:
    """YouTube's picture: its bytes, b"" when it has none (404), None when
    the fetch failed (tests replace this)."""
    import httpx
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False, trust_env=False) as c:
            with c.stream("GET", url, headers={"Accept": "image/jpeg"}) as r:
                if r.status_code == 404:
                    return b""
                if r.status_code != 200:
                    return None
                out = bytearray()
                for chunk in r.iter_bytes():
                    out.extend(chunk)
                    if len(out) > BYTES_MAX:
                        return None
                return bytes(out)
    except Exception:  # noqa: BLE001
        logger.info("video picture: YouTube didn't answer", exc_info=True)
        return None


def cut(raw: bytes, width: int) -> Optional[bytes]:
    """The picture cut to 16:9 at its centre (hqdefault's bars off), at most
    `width` across, as a JPEG; None for anything that isn't a JPEG we take."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format != "JPEG" or im.width * im.height > PIXELS_MAX:
            return None
        im = im.convert("RGB")
        w, h = im.size
        tall = round(w * 9 / 16)
        if tall < h:
            top = (h - tall) // 2
            im = im.crop((0, top, w, top + tall))
        elif tall > h:
            across = round(h * 16 / 9)
            left = (w - across) // 2
            im = im.crop((left, 0, left + across, h))
        if im.width > width:
            im = im.resize((width, round(width * 9 / 16)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=84, optimize=True, progressive=True)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def get(vid: str, wide: bool) -> Optional[bytes]:
    """The picture's JPEG; b"" when the video has none; None when YouTube
    didn't answer. Kept (module docstring): a found picture KEEP_S, but only
    MISS_S when a sharper one failed to answer on the way (so a passing blip
    on maxresdefault doesn't pin the smaller picture for hours), a miss
    MISS_S, a failure never."""
    key = (vid, wide)
    now = time.monotonic()
    with _LOCK:
        hit = _KEPT.get(key)
        if hit and now < hit[0]:
            _KEPT.move_to_end(key)
            return hit[1]
    failed = False
    got = b""
    for name in WIDE if wide else SMALL:
        raw = _fetch(UPSTREAM.format(vid=vid, name=name))
        if raw is None:
            failed = True
            continue
        if raw:
            got = cut(raw, WIDE_W if wide else SMALL_W) or b""
            if got:
                break
    if not got and failed:
        return None
    with _LOCK:
        _KEPT[key] = (now + (KEEP_S if got and not failed else MISS_S), got)
        _KEPT.move_to_end(key)
        while sum(len(v[1]) for v in _KEPT.values()) > BUDGET and len(_KEPT) > 1:
            _KEPT.popitem(last=False)
    return got


def bytes_for(url: str) -> Optional[bytes]:
    """The picture behind an address picture_url made (the story picture
    reads it here, member_lumen_share.picture_bytes); None for anything else
    or when there's no picture."""
    got = parse(url)
    if not got:
        return None
    return get(*got) or None


# ─── the route ───────────────────────────────────────────────────────

_NO = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@router.get("/my/yt/{name}", include_in_schema=False)
async def video_picture(request: Request, name: str):
    """A message's video picture (module docstring)."""
    m = NAME_RE.match(name or "")
    k = str(request.query_params.get("k") or "")
    try:
        good = bool(m) and bool(k) and hmac.compare_digest(k, sign(name))
    except Exception:  # noqa: BLE001
        good = False
    if not good:
        return Response(status_code=404, headers=_NO)
    got = await asyncio.to_thread(get, m.group(1), bool(m.group(2)))
    if got is None:
        return Response(status_code=503, headers={**_NO, "Retry-After": "60"})
    if not got:
        return Response(status_code=404, headers=_NO)
    tag = '"' + hashlib.sha256(got).hexdigest()[:20] + '"'
    keep = {"Cache-Control": f"public, max-age={PHONE_S}", "ETag": tag, "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=keep)
    return Response(content=got, media_type="image/jpeg", headers=keep)
