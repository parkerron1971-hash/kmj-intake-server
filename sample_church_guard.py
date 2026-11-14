"""
sample_church_guard.py — nothing a sample church does is saved (BE-3, 2026-11-15).

A sample church (sample_church.py) is a made-up church its visitor really
owns, so every owner check lets them through. This pure-ASGI layer is the
one wall in front of every route: a write request (anything but GET, HEAD
and OPTIONS) that names a sample church is answered

    409 {"detail": {"error": "sample_church", "what": "write", "message": …}}

before any route runs, unless it is one of:
  · sample_church.READ_POSTS (POSTs that only read: a search, a preview);
  · Chief's chat (/agents/chief/chat, …/stream) and its prewarm, which do
    nothing for a sample until the sample's own Chief lane (BE-4);
  · /sample-church/* (the sample's own routes, BE-4).

"Names a sample" means: a UUID anywhere in the path; a `business_id`,
`biz` or `businessId` query parameter; or, for a JSON body up to
BODY_MAX bytes, the same keys at its top level (or in each item of a
top-level list). The body is read once and handed on byte for byte.

Cheap: one batched read for the ids this process has never seen
(sample_church.prime remembers every answer, both ways, for good), then
memory. Fails OPEN like every sample read: if the ids can't be read the
request goes on, and the provider seams (texts, mail, push, AI) still
refuse a sample on their own.

Also on GET: an owner's token preview of a site (`?pv=…` on /public/site/*
or /sites/*/preview*) carries X-Robots-Tag: noindex. A sample's site is
"coming soon" to everyone else (no_card_trial.site_hidden), and a preview
link that leaks must never be indexed.

Written in the style of sse_middleware.NoGzipForStreams: never wraps the
response body of a request it lets through, so streaming is untouched.
Registered INSIDE CORSMiddleware (added before it), so the 409 carries the
CORS headers the app needs to read it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Iterable, List, Optional, Set
from urllib.parse import parse_qs

logger = logging.getLogger("sample_church_guard")

BODY_MAX = 256 * 1024
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_KEYS = ("business_id", "biz", "businessId")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Chief's chat lane (BE-4 diverts it for a sample) and its prewarm, which
# answers "warmed nothing" for a sample by itself (chief_of_staff).
EXEMPT_PATHS = frozenset({
    "/agents/chief/chat",
    "/agents/chief/chat/stream",
    "/agents/chief/prewarm",
})
EXEMPT_PREFIXES = ("/sample-church/",)

_PREVIEW = re.compile(r"^/(public/site/|sites/[^/]+/preview)")


def _template_re(t: str) -> "re.Pattern[str]":
    t = t.rstrip("/") or "/"
    star = t.endswith("/*")
    if star:
        t = t[:-2]
    parts = [("[^/]+" if re.fullmatch(r"\{[^/{}]+\}", seg) else re.escape(seg))
             for seg in t.split("/")]
    return re.compile("^" + "/".join(parts) + ("(?:/.*)?" if star else "") + "/?$")


_READ_RES: List["re.Pattern[str]"] = []
_READ_SRC: tuple = ()


def _read_posts() -> List["re.Pattern[str]"]:
    global _READ_RES, _READ_SRC
    import sample_church
    src = tuple(sample_church.READ_POSTS)
    if src != _READ_SRC:
        _READ_RES = [_template_re(t) for t in src]
        _READ_SRC = src
    return _READ_RES


def allowed(method: str, path: str) -> bool:
    """A write this guard lets through for a sample."""
    p = path.rstrip("/") or "/"
    if p in EXEMPT_PATHS or any(path.startswith(x) for x in EXEMPT_PREFIXES):
        return True
    return method == "POST" and any(r.match(p) for r in _read_posts())


def _ids_in_json(raw: bytes) -> Set[str]:
    try:
        data = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:  # noqa: BLE001 - not JSON after all: nothing to read
        return set()
    items: Iterable[Any] = data if isinstance(data, list) else [data]
    out: Set[str] = set()
    for item in items:
        if isinstance(item, dict):
            for k in _KEYS:
                v = item.get(k)
                if isinstance(v, str) and _UUID.fullmatch(v.strip()):
                    out.add(v.strip().lower())
    return out


def ids_named(path: str, query: str, body: Optional[bytes]) -> Set[str]:
    """Every business id this request could name (path UUIDs, the query's
    and the JSON body's business keys)."""
    out = {m.group(0).lower() for m in _UUID.finditer(path or "")}
    if query:
        try:
            q = parse_qs(query, keep_blank_values=False)
        except Exception:  # noqa: BLE001
            q = {}
        for k in _KEYS:
            for v in q.get(k, []):
                if _UUID.fullmatch(v.strip()):
                    out.add(v.strip().lower())
    if body:
        out |= _ids_in_json(body)
    return out


def first_sample(ids: Iterable[str]) -> Optional[str]:
    """The first of these ids that is a sample church, or None. One batched
    read for ids never seen, then memory. Fails open (None)."""
    try:
        import sample_church
        ids = sorted(set(ids))
        if not ids:
            return None
        sample_church.prime(ids)
        for i in ids:
            if sample_church.is_sample(i):
                return i
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample-guard] failed open: {type(e).__name__}")
    return None


def _known_sample(ids: Iterable[str]) -> Any:
    """first_sample() from memory alone: the sample id, None when every id
    is known not to be one, or False when some id hasn't been read yet."""
    try:
        import sample_church
        kind = sample_church._KIND
        for i in ids:
            hit = kind.get(i)
            if hit is None:
                return False
            if hit:
                return i
        return None
    except Exception:  # noqa: BLE001
        return False


def _header(scope, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return ""


async def _refuse(send) -> None:
    import sample_church
    body = json.dumps({"detail": sample_church.detail("write")}).encode("utf-8")
    await send({"type": "http.response.start", "status": 409,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


class SampleChurchGuard:
    """See the module docstring. Add it BEFORE CORSMiddleware, so it sits
    inside it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        query = (scope.get("query_string") or b"").decode("latin-1")
        if method in _SAFE_METHODS:
            if method == "GET" and "pv=" in query and _PREVIEW.match(path):
                return await self.app(scope, receive, _noindex(send))
            return await self.app(scope, receive, send)
        if allowed(method, path):
            return await self.app(scope, receive, send)

        # Read a small JSON body once, to look for its business, and hand
        # the same bytes on. Anything else (a file, a form, a big body)
        # streams through untouched; its path and query are still read.
        buffered: List[dict] = []
        body: Optional[bytes] = None
        ctype = _header(scope, b"content-type").lower()
        if "json" in ctype:
            try:
                declared = int(_header(scope, b"content-length") or -1)
            except ValueError:
                declared = -1
            if declared <= BODY_MAX:
                chunks: List[bytes] = []
                size = 0
                while True:
                    msg = await receive()
                    buffered.append(msg)
                    if msg.get("type") != "http.request":
                        break
                    chunk = msg.get("body") or b""
                    size += len(chunk)
                    chunks.append(chunk)
                    if size > BODY_MAX or not msg.get("more_body"):
                        break
                if size <= BODY_MAX and buffered and buffered[-1].get("type") == "http.request" \
                        and not buffered[-1].get("more_body"):
                    body = b"".join(chunks)

        ids = ids_named(path, query, body)
        if ids:
            sample = _known_sample(ids)
            if sample is False:
                sample = await asyncio.to_thread(first_sample, ids)
            if sample:
                logger.info(f"[sample-guard] {method} {path[:80]} refused for a sample")
                return await _refuse(send)

        if not buffered:
            return await self.app(scope, receive, send)

        async def replay():
            if buffered:
                return buffered.pop(0)
            return await receive()

        return await self.app(scope, replay, send)


def _noindex(send):
    async def wrapped(message):
        if message.get("type") == "http.response.start":
            headers = [h for h in message.get("headers") or [] if h[0].lower() != b"x-robots-tag"]
            headers.append((b"x-robots-tag", b"noindex"))
            message = {**message, "headers": headers}
        await send(message)
    return wrapped
