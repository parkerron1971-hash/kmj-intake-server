"""
sse_middleware.py — the shim that lets the chat stream actually stream.

Latency arc round 2 (2026-08-25, Kevin: "why it feels so slow"). The
app runs Starlette's GZipMiddleware (minimum_size=1024), and Starlette
compresses a STREAMING body through one zlib stream that only reliably
drains on stream CLOSE. Tiny SSE events — and even a 16KB whitespace
preamble, which deflates to ~50 bytes — sit inside the compressor's
window until the turn ends. Measured live on production:
firstByte == firstDelta == total on /agents/chief/chat/stream, three
turns in a row, 9.7–17.5s each. The "stream" was a burst.

The buffer was in-house: X-Accel-Buffering and Cache-Control:
no-transform were aimed at the edge proxy and could not help, because
gzip decides on the REQUEST's Accept-Encoding before any response
header exists.

So: an outermost pure-ASGI shim strips Accept-Encoding for the stream
path only. GZipMiddleware sees a client that does not accept gzip and
stands down; every delta reaches the wire the moment the generator
yields it. Everything else on the app keeps its compression.

Pure passthrough by construction — this middleware never touches
receive/send bodies, so it cannot introduce the very buffering it
exists to remove (BaseHTTPMiddleware, the decorator form, buffers
streaming responses through a memory channel and is avoided on
purpose).
"""
from __future__ import annotations

# Paths that must stream event-by-event. endswith-matched, so a router
# prefix cannot silently strand one.
STREAM_PATH_SUFFIXES = ("/agents/chief/chat/stream",)


class NoGzipForStreams:
    """Strip Accept-Encoding for streaming paths so GZipMiddleware
    stands down there. Add OUTERMOST (i.e., add_middleware LAST) — an
    inner position would run after gzip has already decided."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = str(scope.get("path", ""))
            if path.endswith(STREAM_PATH_SUFFIXES):
                scope = dict(scope)
                scope["headers"] = [
                    (k, v) for (k, v) in scope.get("headers", [])
                    if k.lower() != b"accept-encoding"
                ]
        await self.app(scope, receive, send)
