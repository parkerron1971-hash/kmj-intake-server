"""A custom domain's pages are never stored by Cloudflare (custom_domain_cache.py).

2026-10-25: the SaaS Worker fetches the Railway URL, so Cloudflare's cache
key had no hostname in it and churchsavvy.app's home page (public,
s-maxage=600) was served to lovecityc.com. Anything that arrives with
X-Original-Host must leave private, with Cloudflare-CDN-Cache-Control:
no-store; direct traffic keeps its headers.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

import churchsavvy_site
import public_site
from custom_domain_cache import NoSharedCacheForCustomDomains, _shared_free

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _mini_app() -> TestClient:
    app = FastAPI()

    @app.get("/page")
    def page():
        return PlainTextResponse("a page", headers={"Cache-Control": "public, max-age=300, s-maxage=600"})

    @app.get("/bare")
    def bare():
        return PlainTextResponse("no header")

    @app.get("/stream")
    def stream():
        return StreamingResponse(iter([b"one ", b"two"]), media_type="text/plain",
                                 headers={"Cache-Control": "public, s-maxage=60, stale-while-revalidate=600"})

    app.add_middleware(NoSharedCacheForCustomDomains)
    return TestClient(app)


def _shared_cacheable(cc: str) -> bool:
    d = [p.strip().split("=")[0].lower() for p in cc.split(",")]
    return "private" not in d and "no-store" not in d and ("public" in d or "s-maxage" in d)


def test_through_the_worker_nothing_is_stored_at_the_edge():
    c = _mini_app()
    r = c.get("/page", headers={"X-Original-Host": "churchsavvy.app"})
    assert r.text == "a page"
    assert r.headers["cloudflare-cdn-cache-control"] == "no-store"
    assert r.headers["cache-control"] == "private, max-age=300"
    assert not _shared_cacheable(r.headers["cache-control"])


def test_a_response_with_no_cache_header_still_leaves_private():
    r = _mini_app().get("/bare", headers={"X-Original-Host": "lovecityc.com"})
    assert r.headers["cache-control"] == "private, no-cache"
    assert r.headers["cloudflare-cdn-cache-control"] == "no-store"


def test_a_streamed_page_keeps_its_body():
    r = _mini_app().get("/stream", headers={"X-Original-Host": "lovecityc.com"})
    assert r.text == "one two"
    assert r.headers["cache-control"] == "private, stale-while-revalidate=600"


def test_direct_traffic_keeps_its_headers():
    c = _mini_app()
    r = c.get("/page", headers={"Host": "mysolutionist.app"})
    assert r.headers["cache-control"] == "public, max-age=300, s-maxage=600"
    assert "cloudflare-cdn-cache-control" not in r.headers
    assert "cache-control" not in c.get("/bare").headers


@pytest.mark.parametrize("given,want", [
    ("public, max-age=300, s-maxage=600", "private, max-age=300"),
    ("public, max-age=604800, immutable", "private, max-age=604800, immutable"),
    ("no-store", "private, no-store"),
    ("private, max-age=60", "private, max-age=60"),
    ("", "private, no-cache"),
])
def test_only_the_shared_directives_go(given, want):
    assert _shared_free(given) == want


def test_churchsavvys_real_pages_leave_private_through_the_worker(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://system.mysolutionist.app")
    app = FastAPI()
    app.include_router(churchsavvy_site.router)
    app.include_router(public_site.router)
    app.add_middleware(NoSharedCacheForCustomDomains)
    c = TestClient(app)
    for path in ("/", "/pricing", "/churchsavvy-assets/og-2.png"):
        r = c.get(path, headers={"X-Original-Host": "churchsavvy.app"})
        assert r.status_code == 200, path
        assert r.headers["cloudflare-cdn-cache-control"] == "no-store", path
        assert not _shared_cacheable(r.headers["cache-control"]), (path, r.headers["cache-control"])
    assert "ChurchSavvy" in c.get("/", headers={"X-Original-Host": "churchsavvy.app"}).text


def test_the_app_adds_it_outermost():
    """Registered after every other add_middleware, so it rewrites the
    final headers (an inner position would run before gzip/CORS add theirs,
    harmless today, but outermost is the rule for header shims here)."""
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    adds = re.findall(r"^app\.add_middleware\(\s*(\w+)", src, flags=re.M)
    assert adds and adds[-1] == "NoSharedCacheForCustomDomains", adds
