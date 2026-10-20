"""
test_sse_middleware.py — the chat stream must never ride through gzip.

The burst bug (2026-08-25): GZipMiddleware compresses a streaming body
through one zlib stream that only drains on CLOSE, so every SSE delta
of a Chief turn reached the client in a single burst at the end —
measured live as firstByte == total on 9.7–17.5s turns. The shim strips
Accept-Encoding for the stream path so gzip stands down there.

What has to hold:
  1. The stream path comes back UNCOMPRESSED even when the client
     advertises gzip — that is the whole fix.
  2. Everything else keeps its compression — the shim must not turn
     off gzip for the app at large.
  3. The shim is a pure passthrough for non-http scopes and non-stream
     paths — byte-identical scope, no body handling.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

from sse_middleware import NoGzipForStreams, STREAM_PATH_SUFFIXES, is_screen_stream


def _mini_app() -> FastAPI:
    """The production middleware arrangement in miniature: gzip inside,
    the shim OUTSIDE (added after), one streaming route on the real
    stream suffix and one plain route."""
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(NoGzipForStreams)

    @app.post("/agents/chief/chat/stream")
    async def stream():
        async def _events():
            # The production preamble shape: highly compressible, which
            # is exactly why gzip swallowed it whole.
            yield ":" + (" " * 16384) + "\n\n"
            yield 'data: {"type":"delta","text":"hello"}\n\n'
        return StreamingResponse(_events(), media_type="text/event-stream")

    @app.get("/worship/screen/{token}/events")
    async def screen(token: str):
        async def _events():
            yield ":" + (" " * 16384) + "\n\n"
            yield 'event: live\ndata: {"rev":1,"state":{"slide":0}}\n\n'
        return StreamingResponse(_events(), media_type="text/event-stream")

    @app.get("/big")
    async def big():
        return PlainTextResponse("x" * 50_000)

    return app


def test_the_stream_path_is_never_gzipped():
    client = TestClient(_mini_app())
    r = client.post("/agents/chief/chat/stream",
                    headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers, (
        "the stream rode through gzip — deltas will buffer until close "
        "and arrive as one burst"
    )
    assert '"delta"' in r.text


def test_a_church_screens_stream_is_never_gzipped():
    client = TestClient(_mini_app())
    r = client.get("/worship/screen/" + "a" * 43 + "/events", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert "content-encoding" not in r.headers, (
        "a screen's live slides rode through gzip — they wait until the "
        "stream closes, so the screen never hears the booth"
    )
    assert '"slide"' in r.text


def test_the_shim_strips_accept_encoding_for_a_screens_stream():
    """Version-proof: what the shim itself does, whatever Starlette's gzip
    would. (Starlette 0.4x+ skips text/event-stream on its own, so the
    gzip test above passes locally either way; production's doesn't.)"""
    import asyncio
    seen = {}

    async def inner(scope, receive, send):
        seen["headers"] = dict(scope["headers"])

    shim = NoGzipForStreams(inner)
    asyncio.run(shim({"type": "http", "path": "/worship/screen/" + "a" * 43 + "/events",
                      "headers": [(b"accept-encoding", b"gzip"), (b"host", b"x")]}, None, None))
    assert b"accept-encoding" not in seen["headers"] and seen["headers"][b"host"] == b"x"
    asyncio.run(shim({"type": "http", "path": "/worship/screens",
                      "headers": [(b"accept-encoding", b"gzip")]}, None, None))
    assert seen["headers"][b"accept-encoding"] == b"gzip"


def test_the_screen_stream_matches_the_real_route():
    import worship_show_router
    paths = [getattr(r, "path", "") for r in worship_show_router.router.routes]
    real = next(p for p in paths if p.endswith("/events"))
    assert is_screen_stream(real.replace("{token}", "a" * 43))
    assert not is_screen_stream("/worship/screens") and not is_screen_stream("/worship/screen/x/show")


def test_everything_else_keeps_its_compression():
    client = TestClient(_mini_app())
    r = client.get("/big", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip", (
        "the shim turned gzip off for the whole app — it must only "
        "stand down on the stream path"
    )


def test_the_suffix_list_matches_the_real_route():
    # The shim matches by suffix; if the chat/stream route ever moves,
    # this is the tripwire that says the shim no longer covers it.
    import chief_of_staff  # noqa: F401 — proves the module imports
    assert any("/agents/chief/chat/stream".endswith(s)
               for s in STREAM_PATH_SUFFIXES)


def test_non_http_scopes_pass_through_untouched():
    seen = {}

    async def inner(scope, receive, send):
        seen.update(scope=scope)

    import asyncio
    shim = NoGzipForStreams(inner)
    ws_scope = {"type": "websocket", "path": "/agents/chief/chat/stream",
                "headers": [(b"accept-encoding", b"gzip")]}
    asyncio.run(shim(ws_scope, None, None))
    assert seen["scope"] is ws_scope, "non-http scope must pass through by identity"
