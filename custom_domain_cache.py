"""
custom_domain_cache.py — Cloudflare never stores a custom domain's pages.

Found 2026-10-25 (Kevin: "churchsavvy site is pulling up under
lovecityc.com"). Custom domains reach us through the Cloudflare-for-SaaS
Worker (infra/cloudflare_saas_worker.js), which fetches the RAILWAY origin
URL and passes the visitor's hostname in X-Original-Host. Cloudflare caches
that fetch under the Railway URL — the hostname the visitor typed is not in
the cache key. So every custom domain shares one cache entry per path:
churchsavvy.app's home page (public, s-maxage=600) was stored as
kmj-intake-server-production.up.railway.app/ and served to lovecityc.com
and www.lovecityc.com as a HIT, the same x-railway-request-id on both. A
church's own pages (s-maxage=60) would have leaked the same way into
another church's domain.

So for any request that came through the Worker (it carries
X-Original-Host), the response tells Cloudflare not to store it:
Cloudflare-CDN-Cache-Control: no-store, and Cache-Control loses its shared
directives (public, s-maxage) and becomes private. The browser may still
keep its own copy. Direct traffic (mysolutionist.app, platform
subdomains, the API host) never carries the header and is untouched.

Pure ASGI, header-only (never touches a body), like sse_middleware.py:
BaseHTTPMiddleware buffers streaming responses.
"""
from __future__ import annotations

from typing import List, Tuple


def _shared_free(cache_control: str) -> str:
    """The same directives minus what lets a shared cache store it, plus
    private. An empty or missing header becomes "private, no-cache"."""
    kept = []
    for part in cache_control.split(","):
        d = part.strip()
        name = d.split("=")[0].strip().lower()
        if not d or name in ("public", "s-maxage", "private", "proxy-revalidate"):
            continue
        kept.append(d)
    if not kept:
        kept = ["no-cache"]
    return ", ".join(["private"] + kept)


def headers_for_custom_domain(headers: List[Tuple[bytes, bytes]]) -> List[Tuple[bytes, bytes]]:
    out = []
    cache_control = ""
    for k, v in headers:
        name = k.lower()
        if name == b"cache-control":
            cache_control = v.decode("latin-1")
            continue
        if name in (b"cloudflare-cdn-cache-control", b"cdn-cache-control"):
            continue
        out.append((k, v))
    out.append((b"cache-control", _shared_free(cache_control).encode("latin-1")))
    out.append((b"cloudflare-cdn-cache-control", b"no-store"))
    return out


def via_custom_domain(scope) -> bool:
    return any(k.lower() == b"x-original-host" and v.strip() for k, v in scope.get("headers") or [])


class NoSharedCacheForCustomDomains:
    """Add OUTERMOST (add_middleware last) so it sees the final headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not via_custom_domain(scope):
            await self.app(scope, receive, send)
            return

        async def send_private(message):
            if message.get("type") == "http.response.start":
                message = {**message, "headers": headers_for_custom_domain(list(message.get("headers") or []))}
            await send(message)

        await self.app(scope, receive, send_private)
