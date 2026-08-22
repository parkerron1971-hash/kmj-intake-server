"""
public_site.py — Solutionist System public site data + widget endpoints

Unauthenticated read-only endpoints that serve practitioner site data
and embeddable widget HTML. Only exposes modules with
public_display.enabled = true and only the fields listed in visible_fields.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.
2. In main.py:
       from public_site import router as public_site_router
       app.include_router(public_site_router)
3. No env vars beyond the existing SUPABASE_URL + SUPABASE_ANON.

Brand Engine v1 helpers (_brand_footer_html, _in_the_clear_badge_html)
are available for any renderer to call. The brand-engine-migration.sql
also promotes nested keys into the legacy flat keys this file reads
at lines 741, 870, 1700 — so existing color reads now resolve to the
real practitioner brand color instead of defaults. Smart Sites (Pass 3)
will wire the helpers into every page footer.
"""

import asyncio
import html as _html
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _brand_footer_html(business_id: str) -> str:
    """Return a small footer block (copyright + legal disclaimers) sourced
    from the Brand Engine bundle. Returns "" if the bundle can't compose,
    so callers can safely append unconditionally."""
    if not business_id:
        return ""
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id) or {}
    except Exception:
        return ""
    footer = bundle.get("footer") or {}
    cr = footer.get("copyright_line") or ""
    legal = footer.get("legal_footer") or ""
    if not cr and not legal:
        return ""
    parts: List[str] = []
    if cr:
        parts.append(f'<div class="brand-copyright">{_html.escape(cr)}</div>')
    if legal:
        parts.append(f'<div class="brand-legal-footer">{_html.escape(legal)}</div>')
    return (
        '<footer class="brand-footer" style="margin-top:2rem;padding:1rem;'
        'font-size:.8rem;color:#666;text-align:center;line-height:1.6;">'
        + "".join(parts)
        + "</footer>"
    )


def _in_the_clear_badge_html(business_id: str) -> str:
    """Inline badge marking the business as foundation-complete. Smart
    Sites in Pass 3 will style this properly via the
    `.in-the-clear-badge` class. v1 ships unstyled markup."""
    if not business_id:
        return ""
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id) or {}
    except Exception:
        return ""
    if not (bundle.get("legal") or {}).get("in_the_clear"):
        return ""
    return (
        '<span class="in-the-clear-badge" '
        'title="Legal &amp; Tax Setup complete">'
        '✓ Business In The Clear</span>'
    )


def _brand_head_meta_tags(business_id: str) -> str:
    """Return favicon link + Open Graph + Twitter Card meta tags sourced
    from the Brand Engine bundle's assets section. Inject before
    </head> in any rendered public page. Returns "" when no relevant
    assets are configured, so callers can append unconditionally."""
    if not business_id:
        return ""
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id) or {}
    except Exception:
        return ""
    assets = bundle.get("assets") or {}
    favicon = assets.get("favicon")
    social_card = assets.get("social_card")
    business = bundle.get("business") or {}
    biz_name = (business.get("name") or "").replace('"', '&quot;')
    tagline = (business.get("tagline") or "").replace('"', '&quot;')

    parts: List[str] = []
    if favicon:
        parts.append(f'<link rel="icon" type="image/png" href="{favicon}">')
        parts.append(f'<link rel="shortcut icon" href="{favicon}">')
        parts.append(f'<link rel="apple-touch-icon" href="{favicon}">')
    if social_card:
        parts.append(f'<meta property="og:image" content="{social_card}">')
        if biz_name:
            parts.append(f'<meta property="og:title" content="{biz_name}">')
        if tagline:
            parts.append(f'<meta property="og:description" content="{tagline}">')
        parts.append('<meta property="og:type" content="website">')
        parts.append('<meta name="twitter:card" content="summary_large_image">')
        parts.append(f'<meta name="twitter:image" content="{social_card}">')
        if biz_name:
            parts.append(f'<meta name="twitter:title" content="{biz_name}">')
        if tagline:
            parts.append(f'<meta name="twitter:description" content="{tagline}">')
    return "\n    ".join(parts)

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from auth_supabase import require_user, AuthedUser
from business_access import business_access
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response, StreamingResponse)

from auth_supabase import AuthedUser, require_user


def _require_business_owner(business_id: str, user: AuthedUser) -> None:
    """Owner gate for destructive/expensive site endpoints (mirrors
    /composer/rationale's check): 404 for an unknown business, 403 when
    the verified caller isn't its owner. These endpoints trigger
    service-role writes / LLM composes — session auth alone isn't enough."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
RATE_LIMIT_PER_MIN = 100
RATE_WINDOW_SEC = 60

# Business-type → color palette for widgets
TYPE_PALETTES: Dict[str, Dict[str, str]] = {
    "church":     {"bg": "#faf7f2", "card": "#fff", "accent": "#8B6914", "text": "#2d2417", "muted": "#7a6e5e", "border": "#e8dfd2"},
    "coaching":   {"bg": "#f0f4f8", "card": "#fff", "accent": "#1a6b8a", "text": "#1a2a3a", "muted": "#5a6a7a", "border": "#dce4ec"},
    "consulting": {"bg": "#f3f4f6", "card": "#fff", "accent": "#3730a3", "text": "#111827", "muted": "#6b7280", "border": "#e5e7eb"},
    "nonprofit":  {"bg": "#f0fdf4", "card": "#fff", "accent": "#166534", "text": "#14532d", "muted": "#4d7c5e", "border": "#d1e7d8"},
    "freelance":  {"bg": "#fdf4ff", "card": "#fff", "accent": "#7c3aed", "text": "#1e1033", "muted": "#6b5b7b", "border": "#e8d5f5"},
}
DEFAULT_PALETTE = TYPE_PALETTES["consulting"]

# ═══════════════════════════════════════════════════════════════════════
# SUBDOMAIN DETECTION
# ═══════════════════════════════════════════════════════════════════════

BASE_DOMAINS = ["mysolutionist.app", "solutionistsystem.com", "getsolutionist.com", "mysolutionist.com"]

# Pass 4.0e cache-headers-fix — applied to every public subdomain +
# custom-domain HTML response. Matches the existing /sites/{id}/preview
# admin path (which has had no-store since Pass 3.8f.2). Without these
# headers, browsers heuristically cache HTML responses (RFC 7234 §4.2.2)
# and practitioner regenerates + inline edits don't show up on the live
# subdomain until hard refresh. With them, every subdomain request hits
# the FastAPI render pipeline fresh.
_PUBLIC_SITE_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

# ─── Edge caching for stable public pages (2026-08-02) ───────────────
#
# The no-store above is correct for anything that reflects live state,
# but it was applied to EVERY public response — including the composed
# home page, which changes only when the practitioner changes it. The
# cost, measured: Cloudflare could not cache the page, so it stopped
# being a CDN and became a 500ms tax. Time to first byte was 1153ms
# through Cloudflare versus 650ms hitting Railway directly, and every
# single visitor's page view ran the full render on the ONE uvicorn
# worker that Chief and site builds share.
#
# The split that keeps both properties:
#   max-age=0, must-revalidate  → the BROWSER always revalidates, so a
#       practitioner refreshing their own site sees an edit instantly.
#       This is the property the original no-store was protecting.
#   s-maxage=60                 → the shared cache (Cloudflare) may
#       serve for a minute. An edit is visible to the world within ~60s
#       without any purge plumbing.
#   stale-while-revalidate=600  → the edge serves the slightly-stale
#       copy instantly and refreshes behind the scenes, so nobody ever
#       waits on our origin for a page we already have.
#
# NOTE: Cloudflare does not cache HTML on ANY plan by default — this
# header is necessary but not sufficient. The zone also needs a Cache
# Rule marking these responses eligible for cache. Without it nothing
# breaks; the page simply keeps behaving as it does today.
#
# Applied ONLY to pages whose content is a stored artifact: the
# composed home page, generated secondary pages, robots.txt, and
# sitemap.xml. Everything that reflects live state — booking (slot
# availability), giving, events, academy, learner portals, the offline
# page, and 404s — deliberately keeps no-store.
_PUBLIC_SITE_EDGE_CACHE_HEADERS = {
    "Cache-Control": (
        "public, max-age=0, must-revalidate, "
        "s-maxage=60, stale-while-revalidate=600"
    ),
}

# Hosts where the Railway API is served directly. When the incoming
# Host matches one of these, the root + catch-all handlers MUST 404 so
# requests fall through to the real API routers (chief, email, etc.)
# without being intercepted by the subdomain site-server.
API_HOSTS = (
    "kmj-intake-server-production.up.railway.app",
    ".railway.app",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
)


def _is_api_host(host: str) -> bool:
    """True when the request arrived on the Railway API domain (or local dev)."""
    h = (host or "").split(":")[0].lower().strip()
    if not h:
        return True  # no host header → treat as API to be safe
    for needle in API_HOSTS:
        if needle.startswith("."):
            if h.endswith(needle):
                return True
        elif h == needle:
            return True
    return False


def public_host(request: Request) -> str:
    """The hostname the VISITOR actually used.

    Custom domains reach us through the Cloudflare-for-SaaS Worker, which
    rewrites the Host header to the Railway origin (so Railway's host-based
    router accepts the request) and forwards the real customer hostname in
    X-Original-Host. We deliberately do NOT use X-Forwarded-Host here:
    Railway's edge proxy manages the X-Forwarded-* family itself and
    overwrites it before it reaches the app, so the customer hostname would
    be lost. X-Original-Host is a custom header the edge passes through
    untouched. Fall back to Host for direct traffic (platform subdomains,
    local dev, the API host)."""
    orig = (request.headers.get("x-original-host") or "").split(",")[0]
    orig = orig.split(":")[0].strip().lower()
    if orig:
        return orig
    return (request.headers.get("host") or "").split(":")[0].lower().strip()


def extract_slug_from_host(request: Request) -> Optional[str]:
    """Extract the business slug from subdomain.
    embrace-the-shift.mysolutionist.app → 'embrace-the-shift'
    www.mysolutionist.app → None (root)
    mysolutionist.app → None (root)
    kmj-intake-server-production.up.railway.app → None (API domain)
    """
    host = public_host(request)
    if not host:
        return None

    for base in BASE_DOMAINS:
        if host == base or host == f"www.{base}":
            return None
        if host.endswith(f".{base}"):
            slug = host.replace(f".{base}", "")
            if slug and slug != "www":
                return slug

    return None


def _inject_canonical(html: str, slug: str, custom_domain: Optional[str] = None,
                      page_path: str = "") -> str:
    """Inject canonical URL + OG tags into the HTML head section. When the
    site has a custom domain configured, that is the canonical public
    address (not the platform subdomain).

    `page_path` ('/about') makes a secondary page canonical to ITSELF.
    Without it every page of a multi-page site claimed to be the home
    page, which tells Google the site has one page and three duplicates.
    """
    canonical = _public_origin(slug, custom_domain) + (page_path or "")

    # The composed HTML already carries a canonical baked in at BUILD
    # time (site_modules/_base.py hardcodes the platform subdomain — it
    # cannot know about a domain connected later, or which page it will
    # be served as). Appending a second canonical would leave two
    # competing tags and Google would pick one at random. Serve time
    # knows the truth, so serve time WINS: strip what the builder wrote,
    # then inject.
    html = re.sub(r'\s*<link[^>]+rel=["\']canonical["\'][^>]*>', "", html,
                  flags=re.IGNORECASE)
    html = re.sub(r'\s*<meta[^>]+property=["\']og:url["\'][^>]*>', "", html,
                  flags=re.IGNORECASE)

    tags = (
        f'\n<link rel="canonical" href="{canonical}" />'
        f'\n<meta property="og:url" content="{canonical}" />'
    )
    if "</head>" in html:
        return html.replace("</head>", tags + "\n</head>", 1)
    if "</HEAD>" in html:
        return html.replace("</HEAD>", tags + "\n</HEAD>", 1)
    return html


def _public_origin(slug: str, custom_domain: Optional[str] = None) -> str:
    """The address the public actually uses for this site. A connected
    custom domain IS the site's home — the platform subdomain is the
    fallback, never the canonical when a domain exists."""
    cd = str(custom_domain or "").strip().lower().lstrip("/")
    return f"https://{cd}" if cd else f"https://{slug}.mysolutionist.app"


# Findability bundle (2026-08-02). Secondary pages of a composed
# multi-page site are stored in site_config.generated_pages keyed by
# page_id; these are the clean public paths that map onto them.
_SITE_PAGE_PATHS = {"/about": "about", "/services": "services", "/contact": "contact"}


def _rewrite_nav_for_preview(html: str, slug: str) -> str:
    """Point the page nav at the preview base, for the preview base only.

    2026-08-13 site-builder audit: site_multipage.build_page_nav now
    emits root-relative hrefs (/about), because that is the only form
    that is correct on BOTH the subdomain and a custom domain added
    later, and because the clean routes are the ones that honour the
    offline switch and set a per-page canonical.

    The cost of root-relative is that /public/site/{slug} — the studio's
    preview iframe — is not the site root, so those links would leave
    the preview for the app root. Rewriting them here, at serve time and
    on this handler only, keeps the preview navigable without putting
    the internal URL back into the stored HTML that visitors get.
    """
    if not html:
        return html
    out = html
    # Cross-page nav (multi-page sites only).
    if "sxm-header-pagenav" in html:
        base = f"/public/site/{slug}"
        out = out.replace('href="/"', f'href="{base}"')
        for path, pid in _SITE_PAGE_PATHS.items():
            out = out.replace(f'href="{path}"', f'href="{base}/{pid}"')
    # Always-wins sub-paths (/book, /store, /give, /events). These are
    # root-relative in stored HTML so they stay correct on a custom
    # domain, but the preview base is not the site root — left alone
    # they would leave the studio for the app root. Absolute public URLs
    # keep them clickable without putting a host back into the stored
    # page a visitor receives.
    origin = f"https://{slug}.mysolutionist.app"
    for sub in _ALWAYS_WINS_PATHS:
        out = out.replace(f'href="{sub}"', f'href="{origin}{sub}"')
    return out
# Sub-paths served by their own handlers — never 404, never in the
# "unknown path" branch.
_ALWAYS_WINS_PATHS = ("/book", "/give", "/events", "/store")


def _site_robots_txt(slug: str, custom_domain: Optional[str] = None) -> str:
    """A real robots.txt per site. Without one, crawlers had to guess,
    and /robots.txt itself returned the home page with a 200 (soft-404)
    which is worse than nothing."""
    origin = _public_origin(slug, custom_domain)
    return (
        "User-agent: *\n"
        "Allow: /\n"
        # Nothing indexable lives behind these; they are transactional.
        "Disallow: /thank-you\n"
        f"\nSitemap: {origin}/sitemap.xml\n"
    )


def _site_sitemap_xml(slug: str, cfg: Dict[str, Any],
                      custom_domain: Optional[str] = None) -> str:
    """Sitemap listing every page this site actually serves — home, any
    generated secondary pages, and the live transactional doors. Only
    real URLs: a sitemap that lists a page which 404s is worse than no
    sitemap at all."""
    origin = _public_origin(slug, custom_domain)
    urls: List[str] = [origin + "/"]

    pages = cfg.get("generated_pages")
    if isinstance(pages, dict):
        for path, page_id in _SITE_PAGE_PATHS.items():
            if (pages.get(page_id) or "").strip():
                urls.append(origin + path)

    # Transactional doors, listed only when actually live.
    try:
        import offering_profiles
        state = offering_profiles.business_state(str(cfg.get("_business_id") or "")) if cfg.get("_business_id") else {}
    except Exception:
        state = {}
    if state.get("booking_enabled"):
        urls.append(origin + "/book")

    body = "".join(
        f"\n  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{body}\n</urlset>\n')


def _not_found_page(slug: str, business_name: str = "",
                    accent: str = "#D4AF37",
                    custom_domain: Optional[str] = None) -> HTMLResponse:
    """A real 404 — branded, honest, with a way home.

    Before the findability bundle every unknown path returned the HOME
    PAGE with a 200. Search engines read mass soft-404s as a quality
    signal against the whole site, and it made /robots.txt and
    /sitemap.xml unaddable (they were 'already taken' by the home page).
    """
    origin = _public_origin(slug, custom_domain)
    name = (business_name or "").strip()
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Page not found{(' — ' + name) if name else ''}</title>
<style>
 body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      background:#faf9f7;color:#1a1a1a;font-family:system-ui,-apple-system,sans-serif;
      text-align:center;padding:24px;line-height:1.6}}
 .n{{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:{accent};
     font-weight:700;margin-bottom:14px}}
 h1{{font-size:clamp(1.6rem,4vw,2.2rem);font-weight:400;margin:0 0 10px}}
 p{{color:#5a5a5a;margin:0 0 26px;max-width:30rem}}
 a{{display:inline-block;padding:12px 28px;border-radius:999px;background:{accent};
    color:#fff;text-decoration:none;font-weight:600;font-size:14px}}
</style></head>
<body><div>
 <div class="n">404</div>
 <h1>That page isn&rsquo;t here</h1>
 <p>The link may be out of date, or the page may have moved.</p>
 <a href="{origin}/">Go to the homepage</a>
</div></body></html>"""
    return HTMLResponse(content=html, status_code=404,
                        headers={**_PUBLIC_SITE_NO_STORE_HEADERS})


# ─── Image optimization (2026-08-02, performance pass) ───────────────
#
# Measured on a live composed page before this change: 13 images,
# 12.8 MB, zero srcset. Heroes were 2.4 MB PNGs straight off DALL-E,
# practitioner uploads up to 10 MB stored unmodified, and a phone on 4G
# downloaded the full desktop asset every time (the serve path is
# no-store, so nothing amortized it either).
#
# Supabase Storage can resize and re-encode on its own CDN — verified
# live on this project. The same hero at width=1200 with resize=contain
# comes back as WebP at 189 KB instead of 2.4 MB (93% smaller), and the
# whole page drops to 0.71 MB (95%). WebP is CONTENT-NEGOTIATED off the
# browser's Accept header, so one URL serves WebP to modern browsers
# and the original format to old ones — no <picture>, no fallbacks.
#
# This rewrites at SERVE time, not build time, so every site already
# published gets it immediately without a rebuild (and the stored HTML
# stays untouched, which keeps the change reversible).

_SB_OBJECT_RE = re.compile(
    r"(https://[a-z0-9]+\.supabase\.co/storage/v1)/object/public/([^\"'\s)>]+)",
    re.IGNORECASE)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
# Widths a real layout actually asks for. 1600 covers retina desktop;
# beyond that the source images aren't bigger anyway (the transform
# caps at the original dimensions).
_SRCSET_WIDTHS = (400, 800, 1200, 1600)
_DEFAULT_WIDTH = 1200
# Formats the transform can't help with — vectors are already tiny and
# animated GIFs lose their animation.
_NO_TRANSFORM_EXT = (".svg", ".gif", ".ico")


def _tx_url(base: str, path: str, width: int, quality: int = 78) -> str:
    """A Supabase render-endpoint URL at a given width. resize=contain
    preserves aspect ratio — without it the transform honours width and
    keeps the ORIGINAL height, which squishes the image."""
    return (f"{base}/render/image/public/{path}"
            f"{'&' if '?' in path else '?'}width={width}"
            f"&quality={quality}&resize=contain")


def _optimize_images(html: str) -> str:
    """Point <img> tags at resized WebP and give them a srcset.

    Conservative by construction: only Supabase storage URLs, only tags
    that don't already carry a srcset, never vectors/GIFs, and the
    first image stays eager (it is almost always the hero / LCP).
    Any failure returns the HTML untouched — a page that serves heavy
    images beats a page that doesn't serve.
    """
    if not html or "supabase.co/storage" not in html:
        return html

    state = {"n": 0}

    def rewrite(m: "re.Match") -> str:
        tag = m.group(0)
        state["n"] += 1
        first = state["n"] == 1

        if "srcset" in tag.lower():
            return tag
        src_m = _SRC_RE.search(tag)
        if not src_m:
            return tag
        src = src_m.group(1)
        if "/render/image/public/" in src:      # already transformed
            return tag
        sb = _SB_OBJECT_RE.match(src)
        if not sb:
            return tag                          # Unsplash, data:, external
        base, path = sb.group(1), sb.group(2)
        if path.lower().rsplit("?", 1)[0].endswith(_NO_TRANSFORM_EXT):
            return tag

        # `&` inside an HTML attribute must be escaped — an unescaped
        # one is only safe while no parameter name happens to spell an
        # entity (&copy, &reg, &times...). Ours don't today; escaping
        # means they never can. Browsers decode it back before fetching.
        def _attr(u: str) -> str:
            return u.replace("&", "&amp;")

        srcset = ", ".join(f"{_attr(_tx_url(base, path, w))} {w}w"
                           for w in _SRCSET_WIDTHS)
        out = tag.replace(src, _attr(_tx_url(base, path, _DEFAULT_WIDTH)), 1)
        inject = (f' srcset="{srcset}"'
                  f' sizes="(max-width: 768px) 100vw, {_DEFAULT_WIDTH}px"')
        # The hero is the LCP element — never lazy-load it. Everything
        # below the fold that hasn't already said otherwise gets lazy.
        if "loading=" not in out.lower() and not first:
            inject += ' loading="lazy"'
        if "decoding=" not in out.lower():
            inject += ' decoding="async"'
        return out[:-1].rstrip() + inject + ">" if out.endswith(">") else out

    try:
        return _IMG_TAG_RE.sub(rewrite, html)
    except Exception as e:      # pragma: no cover — never break a page
        logger.warning(f"[perf] image optimization skipped: {e}")
        return html


async def _render_not_found(client: httpx.AsyncClient, slug: str,
                            business_id: Optional[str],
                            custom_domain: Optional[str] = None) -> HTMLResponse:
    """Brand the 404 with the business's own name + accent. Best-effort:
    a lookup failure still returns a correct 404, just a plain one."""
    name, accent = "", "#D4AF37"
    if business_id:
        try:
            rows = await _sb(client,
                f"/businesses?id=eq.{business_id}&select=name,settings&limit=1")
            if rows:
                name = rows[0].get("name") or ""
                bk = ((rows[0].get("settings") or {}).get("brand_kit") or {})
                bc = str(bk.get("primary_color") or "").strip()
                if bc.startswith("#") and len(bc) in (4, 7):
                    accent = bc
        except Exception:
            pass
    return _not_found_page(slug, name, accent, custom_domain)


def _inject_concierge_widget(html: str, business_id: Optional[str]) -> str:
    """Site Concierge hook (2026-08-01): append the widget <script> tag to
    served site pages ONLY when the concierge is enabled for the business
    (site_concierge.widget_snippet returns "" otherwise — the enablement
    truth lives there, cached briefly). Rides the _inject_brand_meta seam
    so every composed-site serve path gets it in one place. Defensive:
    any failure returns the original HTML unchanged."""
    if not business_id:
        return html
    try:
        import site_concierge
        snippet = site_concierge.widget_snippet(business_id)
    except Exception:
        return html
    if not snippet:
        return html
    for tag in ("</body>", "</BODY>"):
        if tag in html:
            return html.replace(tag, snippet + "\n" + tag, 1)
    return html + snippet


TRAFFIC_API_BASE = os.environ.get(
    "TRAFFIC_API_BASE", "https://kmj-intake-server-production.up.railway.app")


def _traffic_beacon(business_id: str) -> str:
    """The first-party page-view beacon for a published customer site.

    WHY THIS EXISTS: every number on the practitioner's funnel — form
    submissions, bookings, link clicks, downloads — is a CONVERSION.
    There was no denominator anywhere, so "twelve leads" could not be
    told apart from twelve-out-of-thirty or twelve-out-of-a-thousand.

    WHY IT IS NOT navigator.sendBeacon. sendBeacon is the right tool for
    this and it does not work here. A beacon carrying an
    application/json body is not a CORS "simple request", so it needs a
    preflight — and sendBeacon cannot preflight, so cross-origin the
    browser drops it SILENTLY. A customer site on its own verified
    domain is always cross-origin to the API. fetch with keepalive
    survives page unload just as well and is allowed to preflight; the
    app's CORS is already "*" because the booking and intake embeds run
    on arbitrary practitioner origins.

    PRIVACY, unchanged from site_analytics' stated contract: no cookie
    (sessionStorage dies with the tab), no IP kept, no user-agent kept,
    referrer reduced to a host server-side. DNT is honoured here as well
    as on the server, so a visitor who has asked not to be tracked costs
    nothing at all.
    """
    return (
        "<script>(function(){try{"
        "if(navigator.doNotTrack==='1'||window.doNotTrack==='1')return;"
        "var B=" + json.dumps(TRAFFIC_API_BASE) + ";"
        "var ID=" + json.dumps(str(business_id)) + ";"
        "var K='sol_sid',sid;try{sid=sessionStorage.getItem(K);"
        "if(!sid){sid=(Math.random().toString(36).slice(2)+Date.now()"
        ".toString(36)).slice(0,24);sessionStorage.setItem(K,sid);}}"
        "catch(e){return;}"
        "var w=window.innerWidth||1024;"
        "var d=w<700?'mobile':(w<1024?'tablet':'desktop');"
        "function send(ev){try{fetch(B+'/api/track',{method:'POST',"
        "headers:{'Content-Type':'application/json'},keepalive:true,"
        "body:JSON.stringify({s:sid,p:location.pathname,"
        "r:document.referrer||null,d:d,e:ev,b:ID})}).catch(function(){});"
        "}catch(e){}}"
        "send('view');"
        "document.addEventListener('click',function(e){"
        "var a=e.target&&e.target.closest?e.target.closest('a,button'):null;"
        "if(!a)return;"
        "var t=((a.textContent||'')+' '+(a.getAttribute('href')||''))"
        ".toLowerCase();"
        "if(/book|schedule|appoint|contact|get started|call|quote|buy|"
        "enquir|inquir/.test(t))send('cta');},true);"
        "document.addEventListener('submit',function(){send('submit');},true);"
        "}catch(e){}})();</script>"
    )


def _inject_traffic_beacon(html: str, business_id: Optional[str]) -> str:
    """Drop the beacon in before </body>. Never raises, never blocks a
    page: a site that cannot be measured is a small problem, a site that
    will not render is a large one. Kill switch: SITE_TRAFFIC=off."""
    if not business_id or not html:
        return html
    if (os.environ.get("SITE_TRAFFIC") or "on").strip().lower() == "off":
        return html
    if "sol_sid" in html:                     # already stamped
        return html
    try:
        tag = _traffic_beacon(business_id)
    except Exception:
        return html
    for close in ("</body>", "</BODY>"):
        if close in html:
            return html.replace(close, tag + "\n" + close, 1)
    return html + tag


def _inject_brand_meta(html: str, business_id: Optional[str]) -> str:
    """Pass 3: wire `_brand_head_meta_tags` into legacy HTML before </head>.
    Activates the dormant Pass 2.5a helper for users who haven't opted into
    Smart Sites yet — favicons + OG tags + Twitter Cards finally render.
    Defensive: any failure returns the original HTML unchanged.

    Also the concierge widget's ride: every serve path that stamps brand
    meta is a served site page, so the widget hook runs here first."""
    html = _inject_concierge_widget(html, business_id)
    # The page-view beacon rides here too, for the same reason and on
    # the same evidence: every call site of this function is a page a
    # real visitor sees. Previews render through other handlers, so a
    # practitioner checking their own draft does not pollute their
    # numbers.
    html = _inject_traffic_beacon(html, business_id)
    if not business_id:
        return html
    try:
        tags = _brand_head_meta_tags(business_id)
    except Exception:
        return html
    if not tags:
        return html
    if "</head>" in html:
        return html.replace("</head>", tags + "\n</head>", 1)
    if "</HEAD>" in html:
        return html.replace("</HEAD>", tags + "\n</HEAD>", 1)
    return html


def _use_smart_sites(site_row: Dict[str, Any]) -> bool:
    """Whether to render via the Smart Sites engine.

    Canonical-engine rule (DRL arc, ruled 2026-06-13): the Module Composer
    is the canonical builder. Once a site has been composed by it
    (html_source == 'module-composer'), the composer's html_content is what
    renders — the Smart Sites engine never shadows it, even if a stale
    use_smart_sites flag lingers from an earlier opt-in. This prevents the
    two engines from fighting over the same business_sites row (the bug that
    made DRO-driven concept copy invisible)."""
    cfg = (site_row or {}).get("site_config") or {}
    if cfg.get("html_source") == "module-composer":
        return False
    return bool(cfg.get("use_smart_sites"))


def _esc(text: Any) -> str:
    """Cheap HTML escape."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_price_label(price: float, pricing_type: str, currency: str) -> str:
    """Produce a display-friendly price tag. Honors pricing_type semantics
    so 'free' / 'custom' / 'starting_at' render correctly on the site."""
    sym = "$" if (currency or "USD").upper() == "USD" else ""
    pt = (pricing_type or "fixed").lower()
    if pt == "free":
        return "Free"
    if pt == "custom" or price <= 0:
        return "Contact for pricing"
    base = f"{sym}{price:,.2f}".rstrip("0").rstrip(".") if price % 1 else f"{sym}{price:,.0f}"
    if pt == "hourly" or pt == "per_hour":
        return f"{base}/hr"
    if pt == "per_session":
        return f"{base}/session"
    if pt == "subscription" or pt == "monthly":
        return f"{base}/mo"
    if pt == "starting_at":
        return f"Starting at {base}"
    return base


def _get_product_cta(
    product: Dict[str, Any],
    slug: str,
    brand_color: str,
    settings: Dict[str, Any],
    price_label: str,
) -> str:
    """Return the CTA HTML for a single product card.

    Priority order for buy buttons:
      1. Shopify Buy Button embed (rendered as-is when from cdn.shopify.com)
      2. Stripe payment link (auto-generated for the platform owner; can
         be set manually for other practitioners)
      3. Shopify URL (cart link, paste-in)
      4. Square checkout URL
      5. PayPal URL
      6. External / catch-all URL
      7. Fallbacks: 'Contact for pricing' -> #contact, 'Free' -> #contact

    Services route to /{slug}/book even when a payment link exists, so
    the practitioner can collect time + intake before charging.
    """
    ptype = (product.get("type") or "service").lower()
    metadata = product.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    stripe_url = (product.get("stripe_payment_url") or "").strip()
    shopify_url = (metadata.get("shopify_buy_url") or "").strip()
    square_url = (metadata.get("square_buy_url") or "").strip()
    paypal_url = (metadata.get("paypal_buy_url") or "").strip()
    external_url = (metadata.get("external_buy_url") or "").strip()
    shopify_embed = (metadata.get("shopify_embed") or "").strip()

    btn_style = (
        f"display:inline-block;margin-top:10px;padding:10px 18px;"
        f"background:{brand_color};color:#fff;text-decoration:none;"
        f"border-radius:6px;font-weight:600;text-align:center;"
    )
    secondary_btn_style = (
        f"display:inline-block;margin-top:6px;padding:8px 14px;"
        f"background:transparent;color:{brand_color};border:1px solid {brand_color};"
        f"text-decoration:none;border-radius:6px;font-weight:500;font-size:13px;"
        f"text-align:center;"
    )

    # 1. Shopify Buy Button embed wins — sanitize: only allow embeds that
    # reference cdn.shopify.com so the renderer can't be tricked into
    # injecting arbitrary scripts.
    if shopify_embed and "cdn.shopify.com" in shopify_embed:
        return f'<div class="shopify-embed" style="margin-top:10px;">{shopify_embed}</div>'

    # 2. Services always use /book — booking captures slot + contact info
    # AND can collect payment via Stripe afterwards if the practitioner
    # wires it up. Override only if a specific service has a stripe_url
    # set on the product (rare).
    if ptype == "service":
        booking_slug = slug
        return (
            f'<a href="/{_esc(booking_slug)}/book" style="{btn_style}">'
            f'Book Now &mdash; {price_label}</a>'
        )

    # 3. Provider priority for non-services. Stripe first because it's
    # the only one we can auto-generate.
    primary = ""
    label_suffix = f" &mdash; {price_label}" if price_label and price_label != "Contact for pricing" else ""
    if stripe_url:
        primary = f'<a href="{_esc(stripe_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy Now{label_suffix}</a>'
    elif shopify_url:
        primary = f'<a href="{_esc(shopify_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy on Shopify{label_suffix}</a>'
    elif square_url:
        primary = f'<a href="{_esc(square_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy Now{label_suffix}</a>'
    elif paypal_url:
        primary = f'<a href="{_esc(paypal_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy with PayPal{label_suffix}</a>'
    elif external_url:
        primary = f'<a href="{_esc(external_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy Now{label_suffix}</a>'
    else:
        # No payment link at all -> contact CTA
        pricing_type = (product.get("pricing_type") or "fixed").lower()
        if pricing_type == "custom":
            return f'<a href="#contact" style="{btn_style}">Get a Quote</a>'
        if pricing_type == "free":
            return f'<a href="#contact" style="{btn_style}">Get It Free</a>'
        return f'<div style="margin-top:10px;font-weight:700;color:#222;">{price_label}</div>'

    # 4. Alternate-provider buttons under the primary, if multiple exist.
    alts: List[str] = []
    if stripe_url and shopify_url:
        alts.append(f'<a href="{_esc(shopify_url)}" target="_blank" rel="noopener" style="{secondary_btn_style}">Also on Shopify</a>')
    if stripe_url and paypal_url:
        alts.append(f'<a href="{_esc(paypal_url)}" target="_blank" rel="noopener" style="{secondary_btn_style}">Pay with PayPal</a>')
    return primary + "".join(alts)


def _render_products_section(
    products: List[Dict[str, Any]],
    slug: str,
    brand_color: str = "#D4AF37",
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a Products & Services section. Returns '' when nothing to show.

    `brand_color` flows in from settings.brand_kit.primary_color so the
    CTA buttons match the practitioner's brand instead of always gold.
    `settings` carries the rest of the business settings (subdomain,
    payment_providers, etc.) for CTA routing decisions.
    """
    settings = settings or {}
    visible = [
        p for p in (products or [])
        if (p.get("status") or "active") == "active"
        and p.get("display_on_website", True)
    ]
    if not visible:
        return ""

    visible.sort(key=lambda p: (
        0 if p.get("featured") else 1,
        p.get("sort_order") or 0,
        p.get("name") or "",
    ))

    cards: List[str] = []
    for p in visible:
        name = _esc(p.get("name") or "")
        desc = _esc((p.get("description") or "")[:240])
        ptype = (p.get("type") or "service").lower()
        try:
            price = float(p.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        currency = (p.get("currency") or "USD").upper()
        pricing_type = (p.get("pricing_type") or "fixed").lower()
        price_label = _format_price_label(price, pricing_type, currency)

        image_url = p.get("image_url")
        image_html = (
            f'<div style="width:100%;aspect-ratio:4/3;overflow:hidden;background:#f5f5f5;">'
            f'<img src="{_esc(image_url)}" alt="{name}" style="width:100%;height:100%;object-fit:cover;display:block;" loading="lazy" />'
            f'</div>'
        ) if image_url else ""

        # Featured badge
        featured_badge = ""
        if p.get("featured"):
            featured_badge = (
                f'<span style="display:inline-block;padding:2px 8px;border-radius:99px;'
                f'background:{brand_color};color:#fff;font-size:10px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-left:6px;">'
                f'Popular</span>'
            )

        # Duration badge for services
        duration_badge = ""
        duration = p.get("duration_minutes")
        if duration and ptype == "service":
            duration_badge = (
                f'<span style="display:inline-block;padding:2px 8px;border-radius:99px;'
                f'background:rgba(0,0,0,0.06);color:#666;font-size:11px;margin-left:6px;">'
                f'{int(duration)} min</span>'
            )

        cta = _get_product_cta(p, slug, brand_color, settings, price_label)

        includes = p.get("includes") or []
        includes_html = ""
        if ptype == "package" and isinstance(includes, list) and includes:
            items = "".join(
                f'<li style="font-size:13px;color:#555;padding:3px 0;">&#10003; {_esc((i.get("item") if isinstance(i, dict) else i) or "")}</li>'
                for i in includes[:6]
            )
            includes_html = f'<ul style="list-style:none;margin:8px 0 4px;padding-left:0;">{items}</ul>'

        # Featured card gets a tinted background + accent border
        card_style = (
            "background:#fff;border:1px solid rgba(0,0,0,0.08);border-radius:12px;"
            "overflow:hidden;display:flex;flex-direction:column;"
        )
        if p.get("featured"):
            card_style = (
                f"background:#fff;border:2px solid {brand_color};border-radius:12px;"
                f"overflow:hidden;display:flex;flex-direction:column;"
                f"box-shadow:0 4px 24px rgba(0,0,0,0.06);"
            )

        price_color = brand_color
        cards.append(
            f'<div style="{card_style}">'
            f'{image_html}'
            f'<div style="padding:16px;display:flex;flex-direction:column;gap:6px;flex:1;">'
            f'<h3 style="margin:0;font-size:18px;color:#222;">{name}{duration_badge}{featured_badge}</h3>'
            f'<div style="font-size:22px;font-weight:700;color:{price_color};margin:4px 0;">{price_label}</div>'
            + (f'<p style="margin:0;font-size:14px;color:#555;line-height:1.5;">{desc}</p>' if desc else '')
            + f'{includes_html}'
            f'{cta}'
            f'</div></div>'
        )

    return (
        '<section id="services" style="padding:60px 24px;background:#fafafa;">'
        '<div style="max-width:1100px;margin:0 auto;">'
        '<h2 style="text-align:center;font-size:32px;margin:0 0 32px;color:#222;">Services &amp; Products</h2>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px;">'
        + "".join(cards) +
        '</div></div></section>'
    )


def _render_gallery_section(gallery: List[Dict[str, Any]]) -> str:
    """Render the Gallery section from settings.media_library.gallery.
    Returns '' if nothing public to show."""
    visible = [
        g for g in (gallery or [])
        if g.get("show_on_website", True) and g.get("url")
    ]
    if not visible:
        return ""
    visible.sort(key=lambda g: g.get("sort_order") or 0)

    tiles = []
    for g in visible:
        url = _esc(g.get("url"))
        alt = _esc(g.get("alt") or "")
        caption = _esc(g.get("caption") or "")
        cap_html = (
            f'<p style="margin:6px 0 0;font-size:12px;color:#666;text-align:center;">{caption}</p>'
            if caption else ""
        )
        tiles.append(
            f'<div class="gallery-item" style="display:flex;flex-direction:column;">'
            f'<div style="aspect-ratio:1/1;overflow:hidden;border-radius:8px;background:#f5f5f5;">'
            f'<img src="{url}" alt="{alt}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block;" />'
            f'</div>{cap_html}</div>'
        )

    return (
        '<section id="gallery" style="padding:60px 24px;background:#fff;">'
        '<div style="max-width:1100px;margin:0 auto;">'
        '<h2 style="text-align:center;font-size:32px;margin:0 0 32px;color:#222;">Gallery</h2>'
        '<div class="gallery-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;">'
        + "".join(tiles) +
        '</div></div></section>'
    )


def _render_testimonials_section(testimonials: List[Dict[str, Any]]) -> str:
    """Render the Testimonials section from settings.website_content.testimonials.
    ONLY renders when there are real, opt-in testimonials — never produces a
    placeholder. Quotes are HTML-escaped but otherwise rendered verbatim;
    we never modify the practitioner's words."""
    visible = [
        t for t in (testimonials or [])
        if t.get("show_on_website", True) and (t.get("quote") or "").strip()
    ]
    if not visible:
        return ""

    cards: List[str] = []
    for t in visible:
        quote = _esc(t.get("quote") or "")
        name = _esc(t.get("name") or "")
        role = _esc(t.get("role") or "")
        role_html = (
            f'<div style="font-size:12px;color:#777;margin-top:2px;">{role}</div>'
            if role else ""
        )
        cards.append(
            '<figure style="margin:0;padding:24px;background:#fff;border:1px solid #ececec;'
            'border-radius:12px;display:flex;flex-direction:column;gap:14px;">'
            f'<blockquote style="margin:0;font-size:16px;line-height:1.6;color:#222;">'
            f'&ldquo;{quote}&rdquo;</blockquote>'
            '<figcaption style="display:flex;align-items:flex-start;justify-content:space-between;">'
            f'<div><div style="font-weight:600;color:#222;">— {name}</div>{role_html}</div>'
            '</figcaption></figure>'
        )

    return (
        '<section id="testimonials" style="padding:60px 24px;background:#fafafa;">'
        '<div style="max-width:1100px;margin:0 auto;">'
        '<h2 style="text-align:center;font-size:32px;margin:0 0 32px;color:#222;">What people are saying</h2>'
        '<div class="testimonial-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;">'
        + "".join(cards) +
        '</div></div></section>'
    )


def _inject_dynamic_sections(
    html: str,
    products_html: str,
    gallery_html: str,
    testimonials_html: str = "",
) -> str:
    """Inject the products + gallery + testimonials sections into the
    served HTML.

    Arc 26: module-composer pages render offerings/testimonials/gallery
    from live data at compose time — appending the legacy sections would
    double-render them, so marked pages pass through untouched.

    Placeholder-aware: if the template contains `{{PRODUCTS_SECTION}}`,
    `{{GALLERY_SECTION}}`, or `{{TESTIMONIALS_SECTION}}`, those tokens
    are replaced in place. This lets generated templates control where
    each section lives. Otherwise the sections fall back to being
    appended right before </body> (legacy templates).

    The site itself is regenerated rarely; this gives practitioners
    live updates without a regen cycle.
    """
    # Arc 26 — composed pages already contain these sections (live data
    # baked at compose/shuffle time); skip legacy injection entirely.
    if 'name="x-solutionist-composer"' in html:
        return html

    products_html = products_html or ""
    gallery_html = gallery_html or ""
    testimonials_html = testimonials_html or ""

    placeholder_replaced = False
    if "{{PRODUCTS_SECTION}}" in html:
        html = html.replace("{{PRODUCTS_SECTION}}", products_html)
        placeholder_replaced = True
    if "{{GALLERY_SECTION}}" in html:
        html = html.replace("{{GALLERY_SECTION}}", gallery_html)
        placeholder_replaced = True
    if "{{TESTIMONIALS_SECTION}}" in html:
        html = html.replace("{{TESTIMONIALS_SECTION}}", testimonials_html)
        placeholder_replaced = True
    if placeholder_replaced:
        # Old templates may have ONE placeholder but not all three; for
        # the missing ones, fall through and append before </body>.
        leftovers = []
        if "{{PRODUCTS_SECTION}}" not in (products_html + gallery_html + testimonials_html):
            # the placeholder we just replaced was already filled; nothing to add
            pass
        # Append remaining sections only if they weren't placed via placeholder
        # and haven't already been written into the document.
        # Since placeholder replacement was scoped above, the legacy append
        # path still runs for any section without a placeholder.
        if "{{PRODUCTS_SECTION}}" not in html and products_html and products_html not in html:
            leftovers.append(products_html)
        if "{{GALLERY_SECTION}}" not in html and gallery_html and gallery_html not in html:
            leftovers.append(gallery_html)
        if "{{TESTIMONIALS_SECTION}}" not in html and testimonials_html and testimonials_html not in html:
            leftovers.append(testimonials_html)
        extra = "".join(leftovers)
        if not extra:
            return html
        if "</body>" in html:
            return html.replace("</body>", extra + "\n</body>", 1)
        if "</BODY>" in html:
            return html.replace("</BODY>", extra + "\n</BODY>", 1)
        return html + extra

    # No placeholders at all -> legacy append-before-</body> behavior.
    extra = products_html + gallery_html + testimonials_html
    if not extra:
        return html
    if "</body>" in html:
        return html.replace("</body>", extra + "\n</body>", 1)
    if "</BODY>" in html:
        return html.replace("</BODY>", extra + "\n</BODY>", 1)
    return html + extra


logger = logging.getLogger("public_site")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] public: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")
def _supabase_service(): return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# In-memory rate limiter
_rate_buckets: Dict[str, Dict[str, Any]] = {}

def _check_rate(slug: str) -> bool:
    now = time.time()
    bucket = _rate_buckets.get(slug)
    if not bucket or now - bucket["start"] > RATE_WINDOW_SEC:
        _rate_buckets[slug] = {"start": now, "count": 1}
        return True
    if bucket["count"] >= RATE_LIMIT_PER_MIN:
        return False
    bucket["count"] += 1
    return True

# ═══════════════════════════════════════════════════════════════════════
# SUPABASE HELPER
# ═══════════════════════════════════════════════════════════════════════

async def _sb(client: httpx.AsyncClient, path: str):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
    }
    resp = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _sb_service(client: httpx.AsyncClient, path: str):
    """Phase D.2.1 — service-role GET for the hosted booking page render.

    Public booking-page serving needs to read businesses.name +
    settings.brand_kit + settings.booking_page to render the page, and
    these are restricted from anon by RLS. Service-role read here is
    bounded: callers MUST filter by the specific biz_id already resolved
    from the public slug, and the rendered output only exposes fields
    that are inherently public-by-intent (the practitioner is asking
    customers to visit this URL)."""
    key = _supabase_service()
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    resp = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        return None
    text = resp.text
    return json.loads(text) if text else None

async def _sb_service_patch(client: httpx.AsyncClient, path: str, body: dict):
    """Academy Phase 4B — service-role PATCH for learner-portal progress
    writes. Same bounded-use rule as _sb_service: callers must target a
    row already resolved from an unguessable portal token, and the only
    fields written are the student's own progress/homework/status."""
    key = _supabase_service()
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    resp = await client.patch(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase service PATCH {path}: {resp.status_code} {resp.text[:200]}")
        raise HTTPException(502, "update failed")
    return True


async def _sb_post(client: httpx.AsyncClient, path: str, body: dict):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.post(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase POST {path}: {resp.status_code} {resp.text[:200]}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: dict):
    """Pass 3: PATCH helper for the new Smart Sites endpoints."""
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.patch(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase PATCH {path}: {resp.status_code} {resp.text[:200]}")
        return None
    text = resp.text
    return json.loads(text) if text else None

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _filter_entry(entry_data: Dict, visible: List[str], hidden: List[str]) -> Dict:
    """Keep only the fields the practitioner chose to show.

    2026-08-13 site-builder audit: an empty `visible` used to mean SHOW
    EVERYTHING except three hardcoded names (assigned_to, internal_notes,
    contact_id). That is an allow-list that silently becomes a deny-list
    the moment it is empty — so a field called notes, phone, email, rate
    or client published itself, and any writer that set
    public_display.enabled WITHOUT also writing visible_fields (Chief's
    ensure_module, the Resources library) opted a module's entire schema
    onto the open web.

    An empty allow-list now means nothing is shown. A module with no
    chosen fields renders no entry data rather than all of it — the safe
    reading of "the practitioner never said". The field picker in
    ComposedSiteControls is where that choice gets made.
    """
    if visible:
        return {k: v for k, v in entry_data.items() if k in visible and k not in hidden}
    return {}


def _palette_for(biz_type: str) -> Dict[str, str]:
    return TYPE_PALETTES.get(biz_type, DEFAULT_PALETTE)


def _render_entries_html(entries: List[Dict], display_type: str, palette: Dict[str, str]) -> str:
    """Render module entries as HTML based on display_type."""
    if not entries:
        return '<p style="color:' + palette["muted"] + ';font-style:italic;">No items yet.</p>'

    if display_type == "grid":
        cards = []
        for e in entries:
            title = e.get("title") or e.get("deliverable_name") or e.get("name") or ""
            body_parts = [f'<strong>{title}</strong>'] if title else []
            for k, v in e.items():
                if k in ("title", "deliverable_name", "name") or v is None or v == "":
                    continue
                body_parts.append(f'<span style="color:{palette["muted"]};font-size:0.85em">{k}: {v}</span>')
            cards.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:6px;">'
                + "<br>".join(body_parts) + '</div>'
            )
        return (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;">'
            + "".join(cards) + '</div>'
        )

    if display_type == "wall":
        tiles = []
        for e in entries:
            title = e.get("title") or e.get("quote") or next((str(v) for v in e.values() if v), "")
            status = e.get("status") or ""
            tiles.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-left:3px solid {palette["accent"]};border-radius:0 8px 8px 0;'
                f'padding:14px;break-inside:avoid;margin-bottom:10px;">'
                f'<div style="font-size:0.95em;line-height:1.5;">{title}</div>'
                + (f'<div style="font-size:0.75em;color:{palette["muted"]};margin-top:6px;text-transform:uppercase;letter-spacing:1px;">{status}</div>' if status else '')
                + '</div>'
            )
        return (
            '<div style="column-count:2;column-gap:14px;">'
            + "".join(tiles) + '</div>'
        )

    if display_type == "catalog":
        items = []
        for e in entries:
            title = e.get("title") or e.get("name") or ""
            desc = e.get("description") or ""
            price = e.get("price")
            price_str = f'${price}' if price is not None else ""
            items.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:8px;">'
                f'<div style="font-size:1.1em;font-weight:600;">{title}</div>'
                + (f'<div style="font-size:0.85em;color:{palette["muted"]};line-height:1.5;">{desc[:200]}</div>' if desc else '')
                + (f'<div style="font-size:1.2em;font-weight:700;color:{palette["accent"]};">{price_str}</div>' if price_str else '')
                + '</div>'
            )
        return (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;">'
            + "".join(items) + '</div>'
        )

    # Default: list
    rows = []
    for e in entries:
        title = e.get("title") or e.get("deliverable_name") or e.get("name") or str(next(iter(e.values()), ""))
        sub = e.get("description") or e.get("status") or ""
        rows.append(
            f'<div style="padding:12px 0;border-bottom:1px solid {palette["border"]};display:flex;justify-content:space-between;align-items:center;">'
            f'<span>{title}</span>'
            + (f'<span style="font-size:0.8em;color:{palette["muted"]};">{sub}</span>' if sub else '')
            + '</div>'
        )
    return '<div>' + "".join(rows) + '</div>'


def _build_widget_html(module: Dict, entries: List[Dict], biz: Dict) -> str:
    pd = module.get("public_display") or {}
    display_type = pd.get("display_type", "list")
    title = pd.get("title_override") or module.get("name", "")
    description = pd.get("description") or ""
    palette = _palette_for(biz.get("type", "general"))

    entries_html = _render_entries_html(entries, display_type, palette)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Inter', system-ui, sans-serif;
  background: {palette['bg']};
  color: {palette['text']};
  padding: 24px;
  line-height: 1.6;
}}
h2 {{ font-size: 1.4em; font-weight: 700; margin-bottom: 6px; color: {palette['text']}; }}
.desc {{ font-size: 0.9em; color: {palette['muted']}; margin-bottom: 18px; }}
</style>
</head>
<body>
<h2>{title}</h2>
{f'<p class="desc">{description}</p>' if description else ''}
{entries_html}
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["public_site"])


@router.get("/public/site/{slug}")
async def get_site_html(slug: str):
    """Return the full generated site HTML for hosting/preview."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        # Accept both draft and published sites so practitioners can preview
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&order=updated_at.desc&limit=1"
            f"&select=html_content,business_id,status,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        site = sites[0]
        biz_id = site.get("business_id")

        # Pass 3: Smart Sites flag-gate. ANY failure falls through to legacy.
        if _use_smart_sites(site) and biz_id:
            products_for_smart = await _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100") or []
            smart_html = await _try_render_smart_site(
                biz_id, "home", products=products_for_smart)
            if smart_html:
                return HTMLResponse(
                    content=smart_html, status_code=200, media_type="text/html",
                    headers={"X-Solutionist-Source": "smart-sites"})

        html = site.get("html_content") or ""
        if not html:
            raise HTTPException(404, "Site has no content")

        # Pull live products + media library + verified testimonials so
        # they update without a regen.
        products: List[Dict[str, Any]] = []
        gallery: List[Dict[str, Any]] = []
        testimonials: List[Dict[str, Any]] = []
        brand_color = "#D4AF37"
        biz_settings: Dict[str, Any] = {}
        if biz_id:
            prod_rows, biz_rows = await asyncio.gather(
                _sb(client,
                    f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                    f"&order=sort_order.asc,created_at.desc&select=*&limit=100"),
                _sb(client, f"/businesses?id=eq.{biz_id}&select=settings&limit=1"),
            )
            products = prod_rows or []
            if biz_rows:
                biz_settings = biz_rows[0].get("settings") or {}
                lib = biz_settings.get("media_library") or {}
                gallery = lib.get("gallery") or []
                website_content = biz_settings.get("website_content") or {}
                testimonials = website_content.get("testimonials") or []
                bk = biz_settings.get("brand_kit") or {}
                bc = (bk.get("primary_color") or "").strip() if isinstance(bk, dict) else ""
                if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                    brand_color = bc

        html = _inject_canonical(html, slug, (site.get("site_config") or {}).get("custom_domain"))
        # Pass 3: activate the dormant Pass 2.5a meta-tag helper.
        html = _inject_brand_meta(html, biz_id)
        html = _inject_dynamic_sections(
            html,
            _render_products_section(products, slug, brand_color, biz_settings),
            _render_gallery_section(gallery),
            _render_testimonials_section(testimonials),
        )
        # Preview base only — keeps the studio iframe navigable now that
        # the stored nav is root-relative for the real site.
        html = _rewrite_nav_for_preview(html, slug)
        return HTMLResponse(
            content=html,
            status_code=200,
            media_type="text/html",
            headers={"X-Solutionist-Source": "public-site"},
        )


@router.get("/public/site/{slug}/data")
async def get_site_data(slug: str):
    """Return structured JSON for dynamic site sections + forms."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        biz_id = sites[0]["business_id"]

        biz_rows, modules, forms = await asyncio.gather(
            _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,voice_profile&limit=1"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true"
                        f"&select=id,name,schema,public_display&limit=50"),
            _sb(client, f"/intake_forms?business_id=eq.{biz_id}&is_active=eq.true"
                        f"&select=id,name,form_type,settings&limit=20"),
        )

        biz = biz_rows[0] if biz_rows else {}

        # Filter to public modules and fetch their entries
        public_modules = [
            m for m in (modules or [])
            if (m.get("public_display") or {}).get("enabled")
        ]

        entry_tasks = [
            _sb(client,
                f"/module_entries?module_id=eq.{m['id']}&status=eq.active"
                f"&order={(m.get('public_display') or {}).get('sort_by', 'created_at')}.desc"
                f"&limit={(m.get('public_display') or {}).get('max_display', 20)}"
                f"&select=id,data,created_at")
            for m in public_modules
        ]
        entry_results = await asyncio.gather(*entry_tasks) if entry_tasks else []

        sections = []
        for i, m in enumerate(public_modules):
            pd = m.get("public_display") or {}
            visible = pd.get("visible_fields") or []
            hidden = pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"]
            filter_status = pd.get("filter_status") or []

            raw_entries = entry_results[i] or []
            filtered = []
            for e in raw_entries:
                data = e.get("data") or {}
                if filter_status and data.get("status") not in filter_status:
                    continue
                filtered.append({
                    **_filter_entry(data, visible, hidden),
                    "created_at": e.get("created_at"),
                })

            sections.append({
                "module_id": m["id"],
                "title": pd.get("title_override") or m.get("name"),
                "display_type": pd.get("display_type", "list"),
                "description": pd.get("description") or "",
                "entries": filtered,
            })

        # Forms linked to public modules
        public_mod_ids = {m["id"] for m in public_modules}
        linked_forms = [
            {"form_id": f["id"], "name": f["name"],
             "embed_url": f"/public/widget/form/{f['id']}"}
            for f in (forms or [])
            if (f.get("settings") or {}).get("linked_module_id") in public_mod_ids
        ]

        return {
            "business": {
                "name": biz.get("name"),
                "type": biz.get("type"),
            },
            "sections": sections,
            "forms": linked_forms,
        }


@router.get("/public/site/{slug}/{page_path}")
async def get_site_page_html(slug: str, page_path: str):
    """Serve a secondary page of a multi-page site (About/Services/Contact)
    from site_config.generated_pages. Registered AFTER /data so it never
    shadows it. Unknown sub-paths or single-page sites fall back to home."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")
    import studio_page_types
    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&order=updated_at.desc&limit=1"
            f"&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        cfg = sites[0].get("site_config") or {}
        pages = cfg.get("generated_pages") if isinstance(cfg.get("generated_pages"), dict) else {}
        page_id = studio_page_types.slug_to_page_id(page_path)
        html = (pages or {}).get(page_id) or ""
        if not html:
            # Home, unknown page, or a single-page site → serve the main page.
            return await get_site_html(slug)
        # page_path makes this page canonical to ITSELF. Without it every
        # secondary page claimed to be the home page, telling Google the
        # site has one page and three duplicates. The clean-path handlers
        # always passed it; this one — the one the old nav actually sent
        # visitors to — never did.
        html = _inject_canonical(html, slug, cfg.get("custom_domain"),
                                 f"/{page_id}" if page_id != "home" else "")
        html = _inject_brand_meta(html, sites[0].get("business_id"))
        html = _rewrite_nav_for_preview(html, slug)
        return HTMLResponse(content=html, status_code=200, media_type="text/html",
                            headers={"X-Solutionist-Source": "module-composer-multipage"})


@router.get("/public/{slug}/thank-you")
async def thank_you_page(slug: str):
    """Branded thank-you page shown after a Stripe checkout completes.

    Reads the business name + brand_kit.primary_color from settings so
    the success state matches the rest of the practitioner's site.
    """
    if not _check_rate(f"thank-you-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    name = "Thank You"
    accent = "#D4AF37"
    home_link = f"/public/site/{slug}"
    biz_id: Optional[str] = None

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if sites:
            biz_id = sites[0].get("business_id")
            # Pass 3: Smart Sites flag-gate (try/except always falls through)
            if _use_smart_sites(sites[0]) and biz_id:
                smart_html = await _try_render_smart_site(biz_id, "thank_you")
                if smart_html:
                    return HTMLResponse(content=smart_html, media_type="text/html",
                                        headers={"X-Solutionist-Source": "smart-sites"})
            if biz_id:
                biz_rows = await _sb(client,
                    f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1")
                if biz_rows:
                    biz = biz_rows[0]
                    name = biz.get("name") or name
                    bk = (biz.get("settings") or {}).get("brand_kit") or {}
                    if isinstance(bk, dict):
                        bc = (bk.get("primary_color") or "").strip()
                        if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                            accent = bc

    safe_name = _esc(name)
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Thank You &mdash; {safe_name}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<style>
* {{ box-sizing: border-box; }}
body {{
  margin:0; min-height:100vh; padding:24px;
  display:flex; align-items:center; justify-content:center;
  background:#0a0a0f; color:#e8e6e3;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;
  text-align:center;
}}
.wrap {{ max-width: 480px; }}
.check {{
  width:72px; height:72px; border-radius:50%;
  background: color-mix(in srgb, {accent} 16%, transparent);
  border: 2px solid {accent};
  display:flex; align-items:center; justify-content:center;
  margin:0 auto 24px;
  font-size:34px; color:{accent}; font-weight:700;
}}
h1 {{ font-size:30px; font-weight:700; margin:0 0 12px; letter-spacing:-0.01em; }}
p {{ color:#aaa; font-size:16px; line-height:1.6; margin:0 0 28px; }}
a.btn {{
  display:inline-block; padding:12px 24px;
  background:{accent}; color:#0a0a0f; font-weight:600;
  text-decoration:none; border-radius:8px;
  transition: opacity 0.2s;
}}
a.btn:hover {{ opacity: 0.9; }}
.muted {{ color:#666; font-size:13px; margin-top:18px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="check">&#10003;</div>
  <h1>Thank you!</h1>
  <p>Your purchase is confirmed. A confirmation email is on its way &mdash; and if your purchase includes a download, you'll get a delivery email shortly.</p>
  <a class="btn" href="{home_link}">&larr; Back to {safe_name}</a>
  <div class="muted">Powered by The Solutionist System</div>
</div>
</body></html>"""

    # Pass 3: legacy thank-you also gets favicons + OG tags now.
    html = _inject_brand_meta(html, biz_id)
    return HTMLResponse(content=html, status_code=200, media_type="text/html")


@router.post("/sites/{business_id}/restore-previous")
def restore_previous(business_id: str,
                     user: AuthedUser = Depends(require_user)):
    """Compose safety net (2026-07-10): swap the live page back to the
    previous full compose. Symmetric — call again to switch back. No
    LLM, no cost; the slot fills automatically on every full recompose."""
    _require_business_owner(business_id, user)
    import site_composer
    return site_composer.restore_previous_compose(business_id)


@router.post("/sites/{business_id}/invalidate")
async def invalidate_site_cache(business_id: str, user: AuthedUser = Depends(require_user)):
    """Bump business_sites.updated_at so consumers see a fresh
    revision after products / brand_kit / testimonials change.

    The static template HTML is regenerated client-side via the BUILD
    > My Site flow; what changes here is only the dynamically-injected
    sections (products, gallery, testimonials) and the brand colors
    applied at request time. Calling this endpoint is a no-op if the
    business has no published site row yet.
    """
    async with httpx.AsyncClient() as client:
        sites = await _sb(client, f"/business_sites?business_id=eq.{business_id}&select=id&limit=1")
        if not sites:
            return {"status": "no_site"}
        site_id = sites[0]["id"]
        url = f"{_supabase_url()}/rest/v1/business_sites?id=eq.{site_id}"
        headers = {
            "apikey": _supabase_anon(),
            "Authorization": f"Bearer {_supabase_anon()}",
            "Content-Type": "application/json",
        }
        try:
            await client.patch(
                url,
                headers=headers,
                content=json.dumps({"updated_at": datetime.now(timezone.utc).isoformat()}),
                timeout=HTTP_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"site invalidate patch failed: {e}")
        return {"status": "invalidated", "site_id": site_id}


# ═══════════════════════════════════════════════════════════════════════
# SMART SITES v1 — config + preview + enable/disable endpoints (Pass 3)
# ═══════════════════════════════════════════════════════════════════════


@router.post("/sites/{business_id}/smart-config")
async def save_smart_config_endpoint(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Save (merge into) site_config without flipping the use_smart_sites
    flag. Body shape: any subset of SmartSiteConfig keys.

    Owner-gated (audit 2026-08-01): require_user alone let ANY signed-in
    user merge arbitrary keys into ANOTHER business's site_config —
    including custom_domain, offline, and use_smart_sites (which shadows
    a composed page with the retired Smart Sites renderer). Cross-tenant
    write, closed."""
    _require_business_owner(business_id, user)
    try:
        from smart_sites import save_smart_config
        result = save_smart_config(business_id, body or {})
        if not result.get("ok"):
            raise HTTPException(404, result.get("error", "save failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] save_smart_config failed: {e}")
        raise HTTPException(500, "save failed")


@router.post("/sites/{business_id}/smart-preview")
async def smart_preview_endpoint(business_id: str, body: Dict[str, Any],
                                 user: AuthedUser = Depends(require_user)):
    """Render Smart Sites preview from a draft config without persisting.
    Used by MySite.tsx live preview iframe.

    Owner-gated (audit 2026-08-01): this had NO auth at all, and it
    renders a business's real brand + content into HTML for anyone who
    knows a business_id. It is a private draft preview, not a public
    page — the public door is /public/site/{slug}."""
    _require_business_owner(business_id, user)
    try:
        from smart_sites import render_smart_site_preview
        html = render_smart_site_preview(business_id, body or {})
        return HTMLResponse(content=html, media_type="text/html")
    except Exception as e:
        logger.warning(f"[smart_sites] preview failed: {e}")
        raise HTTPException(500, f"preview failed: {e}")


@router.post("/sites/{business_id}/smart-enable")
async def smart_enable_endpoint(business_id: str,
                                user: AuthedUser = Depends(require_user)):
    """Flip use_smart_sites = true. Seeds defaults from bundle if empty.
    Owner-gated: the reroute below synchronously overwrites the live
    composed site (service-role write).

    ─── Smart Sites Arc 4 — RETIRED ENGINE, LIVE CALLER ────────────────
    Decision: LIVE frontend caller — MySite.tsx:185 handleEnableSmartSites
    → smartSites.ts enableSmartSites (smartSites.ts:128) — so NOT 410'd.
    When LEGACY_SITE_ENGINES is off (default) this reroutes to the
    canonical Module Composer: a DETERMINISTIC compose (use_llm=False —
    the caller awaits this synchronously, so no long LLM calls) that
    produces a real composed page from the business's live data; the
    practitioner can then run the full LLM compose from the composer
    panel. Compatibility contract with enableSmartSites():
      - it reads result.ok and result.site_config.generated_decoration;
        the latter, when absent, fires the legacy /generate-decoration
        LLM in the background — so the response (NOT the DB) carries a
        marker there to keep that retired engine dormant;
      - after the await, MySite refetches the site row; html_source ==
        'module-composer' routes it to the composed-site editor view.
    """
    _require_business_owner(business_id, user)
    import site_composer as _sc
    if not _sc.legacy_site_engines_enabled():
        logger.warning(f"[smart-enable] DEPRECATED path hit — rerouting to a "
                       f"deterministic Module Composer compose for {business_id[:8]}")
        result = _sc.compose_site(business_id, use_llm=False)
        try:
            from brand_engine import _sb_get as be_get
            rows = be_get(f"/business_sites?business_id=eq.{business_id}"
                          "&select=site_config&limit=1") or []
            cfg = dict((rows[0].get("site_config") or {}) if rows else {})
        except Exception:
            cfg = {}
        # Response-only trims + shims: the document itself is heavy and
        # the frontend doesn't read it here; the generated_decoration
        # marker only suppresses the legacy decoration auto-fire.
        cfg.pop("generated_html", None)
        cfg.setdefault("generated_decoration", {"engine": "module-composer"})
        return {
            "ok": True,
            "use_smart_sites": False,
            "engine": "module-composer",
            "deprecated": True,
            "note": ("Smart Sites was retired — this site was composed by the "
                     "Module Composer. POST /composer/compose for the full "
                     "LLM composition."),
            "site_config": cfg,
            "composer": {k: result.get(k) for k in ("slug", "url", "sections",
                                                    "composition_source")},
        }
    try:
        from smart_sites import enable_smart_sites
        result = enable_smart_sites(business_id)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error", "enable failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] enable failed: {e}")
        raise HTTPException(500, "enable failed")


@router.post("/sites/{business_id}/smart-disable")
async def smart_disable_endpoint(business_id: str, user: AuthedUser = Depends(require_user)):
    """Flip use_smart_sites = false. Falls back to legacy rendering.
    Owner-gated (audit 2026-08-01) — it rewrites another tenant's
    site_config otherwise."""
    _require_business_owner(business_id, user)
    try:
        from smart_sites import disable_smart_sites
        result = disable_smart_sites(business_id)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error", "disable failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] disable failed: {e}")
        raise HTTPException(500, "disable failed")


# ─── Pass 3.5 Session 3: layout-options + layout-override endpoints ───


@router.get("/sites/{business_id}/layout-options")
async def layout_options_endpoint(business_id: str):
    """Return detected vocabularies (top 3) + available layouts for the
    primary vocabulary. Drives the MySite Design System override UI."""
    try:
        from brand_engine import _sb_get as be_get
        from studio_data import LAYOUTS, VOCAB_LAYOUT_MAP
        from studio_vocab_detect import detect_vocabularies

        biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        business_data = biz_rows[0]
        voice_profile = business_data.get("voice_profile") or {}
        brand_kit = (business_data.get("settings") or {}).get("brand_kit") or {}

        profile_rows = be_get(
            f"/business_profiles?business_id=eq.{business_id}&select=*&limit=1"
        ) or []
        business_profile = profile_rows[0] if profile_rows else {}

        site_rows = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
        ) or []
        site_config = (site_rows[0].get("site_config") if site_rows else {}) or {}

        matches = detect_vocabularies(
            business_data, business_profile, voice_profile, brand_kit
        )

        vocab_options = [
            {
                "id": m["vocabulary"]["id"],
                "name": m["vocabulary"]["name"],
                "section": m["vocabulary"]["section"],
                "color_palette": m["vocabulary"]["color_palette"],
                "confidence": round(m["confidence"], 2),
                "reasons": m["reasons"][:3],
            }
            for m in matches
        ]

        active_vocab = (
            site_config.get("vocabulary_override")
            or (matches[0]["vocabulary"]["id"] if matches else None)
        )

        layout_ids = VOCAB_LAYOUT_MAP.get(active_vocab, []) if active_vocab else []
        layout_options = [
            {
                "id": lid,
                "name": LAYOUTS[lid]["name"],
                "description": LAYOUTS[lid]["description"],
            }
            for lid in layout_ids
            if lid in LAYOUTS
        ]

        active_layout = site_config.get("layout_id") or (
            layout_ids[0] if layout_ids else None
        )

        return {
            "ok": True,
            "vocab_options": vocab_options,
            "layout_options": layout_options,
            "active_vocab": active_vocab,
            "active_layout": active_layout,
            "is_using_override": bool(
                site_config.get("layout_id") or site_config.get("vocabulary_override")
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] layout-options failed for {business_id}: {e}")
        raise HTTPException(500, "layout-options failed")


@router.post("/sites/{business_id}/layout-override")
async def layout_override_endpoint(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Save vocabulary or layout override into site_config.

    Body: { vocabulary_override: <vocab-id> | null, layout_id: <layout-id> | null }
    Pass null (or omit either key) to reset to auto-detect.

    Owner-gated (audit 2026-08-01) — writes site_config.
    """
    _require_business_owner(business_id, user)
    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch
        from studio_data import LAYOUTS, VOCABULARIES

        body = body or {}

        # Validate against the known sets (None / null is always allowed = clear)
        vocab_value = body.get("vocabulary_override", "__unset__")
        layout_value = body.get("layout_id", "__unset__")
        if vocab_value not in ("__unset__", None) and vocab_value not in VOCABULARIES:
            raise HTTPException(400, f"Unknown vocabulary: {vocab_value}")
        if layout_value not in ("__unset__", None) and layout_value not in LAYOUTS:
            raise HTTPException(400, f"Unknown layout: {layout_value}")

        sites = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
        ) or []
        if not sites:
            raise HTTPException(404, "No business_sites row")
        site_id = sites[0]["id"]
        current = sites[0].get("site_config") or {}

        new_config = dict(current)
        if vocab_value != "__unset__":
            if vocab_value is None:
                new_config.pop("vocabulary_override", None)
            else:
                new_config["vocabulary_override"] = vocab_value
        if layout_value != "__unset__":
            if layout_value is None:
                new_config.pop("layout_id", None)
            else:
                new_config["layout_id"] = layout_value

        be_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
        return {"ok": True, "site_config": new_config}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] layout-override failed for {business_id}: {e}")
        raise HTTPException(500, "layout-override failed")


# ─── Pass 3.6: contact-form submission via Resend ──────────────────────

# In-memory rate limiter — 5 submissions per minute per IP. Acceptable
# for v1; restarts reset state.
_contact_rate: Dict[str, List[float]] = {}


def _check_contact_rate(ip: str) -> bool:
    now = time.time()
    cutoff = now - 60
    bucket = [t for t in _contact_rate.get(ip, []) if t > cutoff]
    if len(bucket) >= 5:
        _contact_rate[ip] = bucket
        return False
    bucket.append(now)
    _contact_rate[ip] = bucket
    return True


def _record_website_sms_consent(business_id: str, phone_raw: str,
                                name: str) -> None:
    """SMS consent audit row for a website contact-form opt-in (Arc 1,
    2026-07-04). Mirrors booking_widget_router._record_booking_sms_consent:
    best-effort, never blocks or fails the submission."""
    try:
        from sms_service import normalize_phone
        import sb_clients
        phone = normalize_phone(str(phone_raw or ""))
        if not phone:
            logger.info("[consent] sms_consent checked but no usable phone on contact form")
            return
        sb_clients.sb_post_as_service("/sms_consents", {
            "phone": phone,
            "name": (name or "").strip()[:120] or None,
            "source": "website_contact",
            "business_id": business_id,
        })
        logger.info(f"[consent] website contact SMS consent recorded {phone} biz={business_id[:8]}")
    except Exception as e:
        logger.warning(f"[consent] website contact consent record failed: {e}")


def _capture_contact_from_form(business_id: str, name: str, email: str,
                               phone_raw: str, message: str,
                               attribution: Optional[Dict[str, Any]] = None
                               ) -> Optional[str]:
    """Find-or-create the contact for a website contact-form submission
    (outbound-integrity, 2026-07-31). Before this, a visitor who filled
    the composed site's contact form ONLY produced a notification email —
    zero rows in /contacts or /events. The lead evaporated the moment the
    operator archived the email.

    Dedup: match by email (case-insensitive, LIKE wildcards escaped) or,
    failing that, by normalized phone — always WITHIN business_id. Found
    contacts get last_interaction bumped and the message appended to
    metadata; new ones are created as status='lead' mirroring
    intake_endpoint / booking_widget conventions.

    Anonymous public endpoint → service-role client only (same client
    this file already uses), and the caller's rate limiting runs BEFORE
    this so it cannot become a spam-amplification vector. Best-effort by
    contract: never raises, never blocks the notification email.
    """
    try:
        import urllib.parse

        import lead_attribution
        import sb_clients
        from sms_service import normalize_phone

        email_clean = (email or "").strip().lower()
        phone = normalize_phone(str(phone_raw or ""))
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # THE ONE DEDUPE RULE (lead_identity). This block used to be
        # the best of four different implementations; it is the only
        # one now, and every door shares it — including the name guard
        # that keeps two people at one household address out of a
        # single record.
        import lead_identity
        existing = lead_identity.find(
            business_id, email=email_clean, phone=phone, name=name,
            select="id,name,phone,metadata")

        msg_entry = {"at": now_iso, "message": (message or "")[:1000]}
        if existing:
            contact_id = existing["id"]
            meta = existing.get("metadata") or {}
            msgs = list(meta.get("website_form_messages") or [])
            msgs.append(msg_entry)
            meta["website_form_messages"] = msgs[-10:]
            patch: Dict[str, Any] = {"last_interaction": now_iso, "metadata": meta}
            if phone and not str(existing.get("phone") or "").strip():
                patch["phone"] = phone
            sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{contact_id}&business_id=eq.{business_id}", patch)
        else:
            created = sb_clients.sb_post_as_service("/contacts", {
                "business_id": business_id,
                "name": name,
                "email": email_clean or None,
                "phone": phone or None,
                "status": "lead",
                "source": "website_contact_form",
                "source_detail": lead_attribution.detail_for(attribution),
                "attribution": attribution or None,
                "metadata": {"website_form_messages": [msg_entry]},
                "last_interaction": now_iso,
            })
            if not isinstance(created, list) or not created:
                logger.warning(
                    f"[contact-submit] contact create failed biz={business_id[:8]} "
                    f"— see preceding sb_clients log line")
                return None
            contact_id = created[0]["id"]

        import event_spine
        event_spine.emit(
            "contact_form_submitted", business_id,
            dict({"name": name, "email": email_clean,
                  "message_preview": (message or "")[:160],
                  "new_contact": existing is None},
                 **lead_attribution.event_fields(attribution)),
            contact_id=contact_id, source="website_contact_form")

        # Score it, on a worker thread. Until this landed, a lead from
        # the composed site's own contact form carried a null lead_score
        # forever, which made it invisible to the hot-lead alert, the
        # Hot Leads list, Chief's briefing and the proposal agent — all
        # four gate on that column. Backgrounded because a visitor is
        # waiting on this request and nothing in it reads the score.
        import lead_scoring
        lead_scoring.score_in_background(
            business_id, contact_id,
            {"name": name, "email": email_clean, "phone": phone,
             "message": message},
            source="website_contact_form", email=email_clean, phone=phone)
        return contact_id
    except Exception as e:
        logger.warning(f"[contact-submit] contact capture failed: {e}")
        return None


@router.post("/sites/{business_id}/contact-submit")
async def contact_submit_endpoint(business_id: str, body: Dict[str, Any], request: Request):
    """Capture a contact-form submission as a lead + notify via Resend.

    Body: { name, email, message, phone?, sms_consent? }. Rate-limited
    per client IP at 5/min. Returns {ok: true} on success or {ok: false,
    error: str} on email service failure (so the front-end form shows a
    graceful message rather than crashing).

    Lead capture: every valid submission finds-or-creates the contact
    (dedup by email/phone within the business) and drops a
    contact_form_submitted event on the spine — see
    _capture_contact_from_form. The notification email is unchanged.

    sms_consent (Arc 1): the composed-site contact form shows an
    UNCHECKED opt-in checkbox + optional phone field when the platform
    is SMS-capable; a checked box with a usable phone is recorded in
    sms_consents (source='website_contact') — the A2P audit trail.
    """
    # trusted_client_ip, not request.client.host: behind Railway the
    # socket peer is the PROXY, so every visitor to every published site
    # shared ONE bucket and the sixth contact-form submission
    # platform-wide in a minute was refused. A limiter that drops real
    # leads is worse than no limiter. rate_limit exists for exactly this
    # and intake_endpoint already uses it.
    import rate_limit
    client_ip = rate_limit.trusted_client_ip(request)
    if not _check_contact_rate(client_ip):
        raise HTTPException(429, "Too many submissions. Please try again later.")

    body = body or {}
    name = (body.get("name") or "").strip()[:200]
    email = (body.get("email") or "").strip()[:200]
    message = (body.get("message") or "").strip()[:5000]

    if not name or not email or not message:
        raise HTTPException(400, "Missing required fields")
    if "@" not in email or "." not in email:
        raise HTTPException(400, "Invalid email")

    # SMS opt-in audit (best-effort; recorded once the submission is
    # valid, independent of email-delivery outcome).
    if body.get("sms_consent") is True and str(body.get("phone") or "").strip():
        _record_website_sms_consent(business_id, str(body.get("phone"))[:40], name)

    # Lead capture (outbound-integrity, 2026-07-31): the submission
    # becomes/updates a contact + a timeline event BEFORE the email leg,
    # so the visitor exists in /contacts even if Resend hiccups. The rate
    # limit above already gated this write; best-effort by contract.
    # Where they came from. Read SERVER-SIDE off the Referer header —
    # this form is emitted by four different renderers plus whatever the
    # builder's LLM writes, so anything requiring the client to
    # cooperate would be partially deployed forever.
    import lead_attribution
    attribution = lead_attribution.capture(request, body)
    _capture_contact_from_form(
        business_id, name, email, str(body.get("phone") or ""), message,
        attribution=attribution)

    try:
        from brand_engine import get_bundle, _sb_get as be_get
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[contact-submit] get_bundle failed for {business_id}: {e}")
        bundle = {}
        be_get = None

    # Per-site override email from site_config.sections.contact.email
    # is the displayed "Public email" the visitor sees on the form. Send
    # to that first; fall back to the canonical bundle footer email.
    site_contact_email = None
    if be_get is not None:
        try:
            site_rows = be_get(
                f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
            ) or []
            site_cfg = (site_rows[0].get("site_config") if site_rows else {}) or {}
            site_contact_email = (
                ((site_cfg.get("sections") or {}).get("contact") or {}).get("email")
            )
        except Exception:
            site_contact_email = None

    target_email = (
        site_contact_email
        or ((bundle.get("footer") or {}).get("contact_email"))
        or os.environ.get("DEFAULT_CONTACT_FALLBACK_EMAIL")
        or ""
    )
    business_name = (bundle.get("business") or {}).get("name") or "Your Site"

    if not target_email:
        return {"ok": False, "error": "No contact email configured for this site."}

    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        return {"ok": False, "error": "Email service not configured."}

    # Escape user-provided strings before injecting into HTML
    safe_name = _esc(name)
    safe_email = _esc(email)
    safe_message = _esc(message).replace("\n", "<br>")

    subject = f"[{business_name}] Contact form submission from {name}"[:200]
    html_body = (
        f"<h2>New contact form submission</h2>"
        f"<p><strong>From:</strong> {safe_name} (&lt;{safe_email}&gt;)</p>"
        f"<p><strong>Message:</strong></p>"
        f'<p style="white-space:pre-wrap;">{safe_message}</p>'
        f"<hr>"
        f'<p style="font-size:0.85em;color:#666;">Sent via your {_esc(business_name)} website.</p>'
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": "noreply@mysolutionist.app",
                    "to": [target_email],
                    "reply_to": email,
                    "subject": subject,
                    "html": html_body,
                },
            )
        if 200 <= r.status_code < 300:
            return {"ok": True}
        logger.warning(f"[contact-submit] Resend {r.status_code}: {r.text[:200]}")
        return {"ok": False, "error": "Email service error."}
    except httpx.HTTPError as e:
        logger.warning(f"[contact-submit] HTTPError sending to {target_email}: {e}")
        return {"ok": False, "error": "Network error."}
    except Exception as e:
        logger.warning(f"[contact-submit] unexpected: {e}")
        return {"ok": False, "error": "Unexpected error."}


# ─── Pass 3.7c: Studio-spirit decoration generation pipeline ───────────
#
# In-memory cooldown tracker: business_id -> last unix timestamp of a
# successful (or attempted) generation. 60-second cooldown prevents
# accidental rapid-fire regenerations during testing. Resets on Railway
# redeploy (acceptable for v1).
_decoration_cooldown: Dict[str, float] = {}
DECORATION_COOLDOWN_SECONDS = 60


def _check_decoration_cooldown(business_id: str):
    """Return (can_generate: bool, seconds_remaining: int)."""
    last = _decoration_cooldown.get(business_id, 0)
    elapsed = time.time() - last
    if elapsed >= DECORATION_COOLDOWN_SECONDS:
        return True, 0
    return False, int(DECORATION_COOLDOWN_SECONDS - elapsed)


@router.post("/sites/{business_id}/generate-decoration")
async def generate_decoration_endpoint(business_id: str, user: AuthedUser = Depends(require_user)):
    """Generate a unique decoration scheme via the Studio-spirit AI pipeline.

    Flow:
      1. Check cooldown (60s/business). 429 if still cooling down.
      2. Resolve current vocab + layout via smart_sites helper.
      3. Set cooldown BEFORE the slow API call so concurrent calls block.
      4. Call Claude (creative) + GPT (structural validator).
      5. Validate output against schema.
      6. Persist into business_sites.site_config.generated_decoration.

    Owner-gated (audit 2026-08-01) — spends LLM budget and writes
    another tenant's site_config otherwise.
    """
    _require_business_owner(business_id, user)
    can_generate, seconds_remaining = _check_decoration_cooldown(business_id)
    if not can_generate:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active. Try again in {seconds_remaining} seconds.",
        )

    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch, get_bundle
    except Exception as e:
        logger.warning(f"[decoration] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "Business not found")
    business_data = biz_rows[0]

    try:
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[decoration] get_bundle failed for {business_id}: {e}")
        bundle = {}

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not site_rows:
        raise HTTPException(
            404, "business_sites row missing — enable Smart Sites first"
        )
    site_id = site_rows[0]["id"]
    site_config = site_rows[0].get("site_config") or {}

    try:
        from smart_sites import resolve_layout_and_vocabulary
        # Actual signature: (business_id, site_config) -> 7-tuple
        # (layout_id, vocab_id, composite, design_system, business_data,
        #  business_profile, detected_matches)
        resolved = resolve_layout_and_vocabulary(business_id, site_config)
        layout_id = resolved[0]
        vocab_id = resolved[1]
        composite = resolved[2]
    except Exception as e:
        logger.warning(f"[decoration] resolve_layout_and_vocabulary failed: {e}")
        raise HTTPException(500, "Could not resolve layout/vocabulary")

    if not vocab_id or not layout_id:
        raise HTTPException(
            400, "Cannot resolve vocab/layout for this business yet"
        )

    # Fetch products so the Director prompt can reference real engagement
    # names instead of generic "services".
    try:
        product_rows = be_get(
            f"/products?business_id=eq.{business_id}&status=eq.active&select=name,description,price&limit=12"
        ) or []
    except Exception:
        product_rows = []

    # Stamp cooldown BEFORE the slow Claude+GPT calls so concurrent
    # requests block immediately.
    _decoration_cooldown[business_id] = time.time()

    try:
        from studio_decoration_generator import generate_decoration_scheme
    except Exception as e:
        logger.warning(f"[decoration] generator import failed: {e}")
        raise HTTPException(500, "Generator unavailable")

    scheme, error = generate_decoration_scheme(
        business_data, bundle, vocab_id, layout_id, composite,
        products=product_rows,
    )
    if not scheme:
        raise HTTPException(500, f"Generation failed: {error}")

    new_config = dict(site_config)
    new_config["generated_decoration"] = scheme
    try:
        be_patch(
            f"/business_sites?id=eq.{site_id}", {"site_config": new_config}
        )
    except Exception as e:
        logger.warning(f"[decoration] persist failed for {business_id}: {e}")
        raise HTTPException(500, "Generation succeeded but persist failed")

    return {
        "ok": True,
        "scheme": scheme,
        "vocab_id": vocab_id,
        "layout_id": layout_id,
    }


@router.get("/sites/{business_id}/decoration-status")
async def decoration_status_endpoint(business_id: str):
    """Return current decoration scheme + cooldown status.

    Also surfaces a `cold_start_predicted` field showing whether the
    next generation would fire the cold-start enforcement branch.
    """
    try:
        from brand_engine import _sb_get as be_get, get_bundle
    except Exception as e:
        logger.warning(f"[decoration] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
    ) or []
    site_config = (site_rows[0].get("site_config") if site_rows else {}) or {}
    scheme = site_config.get("generated_decoration")

    # Diagnostic: predict whether cold-start would fire next time.
    cold_start_predicted = None
    voice_signals = None
    try:
        from studio_decoration_generator import _voice_signal_breakdown, _has_meaningful_voice_signal
        bundle = get_bundle(business_id) or {}
        product_rows = be_get(
            f"/products?business_id=eq.{business_id}&status=eq.active&select=name&limit=12"
        ) or []
        voice_signals = _voice_signal_breakdown(bundle, product_rows)
        cold_start_predicted = not _has_meaningful_voice_signal(bundle, product_rows)
    except Exception as e:
        logger.warning(f"[decoration] cold-start prediction failed: {e}")

    can_generate, seconds_remaining = _check_decoration_cooldown(business_id)

    # Pass 3.8b — surface brief presence on the Pass 3.7c status endpoint
    # so existing UI consumers see brief state without a separate fetch.
    brief = site_config.get("design_brief")

    # Pass 3.8d — surface Builder Agent state alongside scheme + brief.
    generated_html = site_config.get("generated_html")

    # Pass 3.8f.2 — surface the full design_recommendation object so the
    # MySite Design DNA panel can show the current strand pair, archetype,
    # signature_moment, alternatives, etc. without a second roundtrip.
    recommendation = site_config.get("design_recommendation")

    # Pass 3.8f.2 — signal_count + threshold so the panel can display
    # "{n}/9 voice signals" without re-deriving the truthy count.
    signal_count = sum(1 for v in (voice_signals or {}).values() if v)
    threshold = 2

    # Pass 3.8f.2 — also surface the design-rec cooldown alongside the
    # decoration cooldown. The MySite "Regenerate Design" button drives
    # /generate-design-recommendation, so its cooldown is what gates the
    # button. Old `can_generate` / `cooldown_remaining_seconds` fields
    # remain (decoration cooldown) for backward compatibility.
    can_regen_rec, rec_cooldown_remaining = _check_design_rec_cooldown(business_id)

    return {
        "ok": True,
        "has_scheme": bool(scheme),
        "scheme": scheme,
        "generated_at": (scheme or {}).get("generated_at"),
        "can_generate": can_generate,
        "cooldown_remaining_seconds": seconds_remaining,
        "cold_start_predicted": cold_start_predicted,
        "voice_signals": voice_signals,
        # Pass 3.8b additions
        "has_brief": bool(brief),
        "brief_generated_at": (brief or {}).get("generatedAt"),
        "brief_warnings": (brief or {}).get("_validation_warnings") or [],
        # Pass 3.8d additions — Builder Agent state
        "has_generated_html": bool(generated_html),
        "html_generated_at": site_config.get("html_generated_at"),
        "html_build_error": site_config.get("html_build_error"),
        "html_validation_errors": site_config.get("html_validation_errors") or [],
        "html_build_failed_at": site_config.get("html_build_failed_at"),
        # Pass 3.8f — quality validator residual warnings (empty on clean pass)
        "quality_warnings": site_config.get("quality_warnings") or [],
        # Pass 3.8f.2 — full recommendation + signal counts for MySite panel
        "has_recommendation": bool(recommendation),
        "recommendation": recommendation,
        "signal_count": signal_count,
        "threshold": threshold,
        "can_regenerate_recommendation": can_regen_rec,
        "recommendation_cooldown_remaining_seconds": rec_cooldown_remaining,
        # Pass 3.8g — multi-page architecture state
        "site_type": site_config.get("site_type", "landing-page"),
        "site_pages": site_config.get("site_pages") or [],
        "generated_pages_count": len(site_config.get("generated_pages") or {}),
        "generated_page_ids": list((site_config.get("generated_pages") or {}).keys()),
        "pages_generated_at": site_config.get("pages_generated_at"),
        "pages_errors": site_config.get("pages_errors") or [],
    }


# _get_cost_cap_summary() lived here, publishing cost_cap_status to the
# design panel's "Daily Builder usage: N / 50" line. Removed 2026-08-13
# (site-builder audit) with the counter itself — see studio_config for
# why. Build spend is governed by credits (pricing_config +
# billing_limits), not by a daily Builder counter.


# ─── Pass 3.8f.2: MySite preview endpoint ─────────────────────────────
#
# Serves the home page through the same fallback chain the live URL uses
# (Builder HTML → archetype → Studio → legacy), so the MySite preview
# iframe stays in sync with the public site after every regeneration.
# Cache-busted via no-store headers; the React iframe also passes a
# ?v={timestamp} query string so the browser cannot serve a stale copy.

@router.get("/sites/{business_id}/preview")
async def preview_site_endpoint(business_id: str, v: Optional[int] = None):
    """Render the full site through the fallback chain.

    Same output as the live URL would serve. Accessible by business_id so
    the MySite editor doesn't need to know the slug. The optional `v`
    query parameter is the iframe cache-bust token; ignored server-side
    but used by the browser/CDN cache key.
    """
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[preview] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=id&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "Business not found")

    try:
        from smart_sites import render_full_site_html
        html = render_full_site_html(business_id)
    except Exception as e:
        logger.warning(f"[preview] render failed for {business_id}: {e}")
        raise HTTPException(500, "Render failed")

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Solutionist-Source": "preview",
            # Allow iframing from the Tauri / MySite shell. We deliberately
            # do NOT set X-Frame-Options at all so any origin can embed the
            # preview — this endpoint serves only Builder/archetype-derived
            # HTML the practitioner already controls.
        },
    )


# ─── Pass 3.8g: per-page preview (multi-page architecture) ────────────

@router.get("/sites/{business_id}/preview-page/{page_id}")
async def preview_page_endpoint(
    business_id: str, page_id: str, v: Optional[int] = None,
):
    """Preview a specific page (home, about, services, contact) from a
    multi-page site. Same cache-busting headers + iframe-friendly behavior
    as /preview. Returns 404 if the page hasn't been generated yet."""
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[preview-page] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=id&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "Business not found")

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
    ) or []
    site_config = (site_rows[0].get("site_config") if site_rows else {}) or {}

    pages = site_config.get("generated_pages") or {}
    html = pages.get(page_id)
    if not html:
        raise HTTPException(
            status_code=404,
            detail=f"Page '{page_id}' not generated. Run /generate-multi-page first.",
        )

    try:
        from studio_html_validator import inject_motion_modules
        scheme = site_config.get("generated_decoration")
        brief = site_config.get("design_brief")
        html = inject_motion_modules(html, scheme, brief)
    except Exception as e:
        logger.warning(f"[preview-page] inject_motion_modules failed: {e}")

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Solutionist-Source": f"preview-page/{page_id}",
        },
    )


# ─── Pass 3.8a: Designer Agent — strand pair recommendation ───────────
#
# In-memory cooldown tracker, per-business, 60s. Reuses Pass 3.7c pattern.
# Resets on Railway redeploy (acceptable for v1).
_design_rec_cooldown: Dict[str, float] = {}
DESIGN_REC_COOLDOWN_SECONDS = 60

# Pass 3.8b: Brief Expander — separate cooldown so manual /expand calls
# don't conflict with the auto-fire chain from /generate-design-recommendation.
_brief_expand_cooldown: Dict[str, float] = {}
BRIEF_EXPAND_COOLDOWN_SECONDS = 60

# Pass 3.8d: Builder Agent (LLM #3) — separate cooldown so manual
# /generate-html calls respect the 60-s window after auto-fire.
_html_build_cooldown: Dict[str, float] = {}
HTML_BUILD_COOLDOWN_SECONDS = 60

# Pass 3.8d: an in-flight set so we don't kick off two background Builder
# jobs for the same business inside one Railway worker (the cooldown
# already blocks new POSTs, but the auto-fire path can race the user).
_html_build_in_flight: set = set()


def _check_brief_expand_cooldown(business_id: str):
    """Returns (can_expand: bool, seconds_remaining: int)."""
    last = _brief_expand_cooldown.get(business_id, 0)
    elapsed = time.time() - last
    if elapsed >= BRIEF_EXPAND_COOLDOWN_SECONDS:
        return True, 0
    return False, int(BRIEF_EXPAND_COOLDOWN_SECONDS - elapsed)


def _check_html_build_cooldown(business_id: str):
    """Returns (can_build: bool, seconds_remaining: int)."""
    last = _html_build_cooldown.get(business_id, 0)
    elapsed = time.time() - last
    if elapsed >= HTML_BUILD_COOLDOWN_SECONDS:
        return True, 0
    return False, int(HTML_BUILD_COOLDOWN_SECONDS - elapsed)


def _check_design_rec_cooldown(business_id: str):
    """Returns (can_generate: bool, seconds_remaining: int)."""
    last = _design_rec_cooldown.get(business_id, 0)
    elapsed = time.time() - last
    if elapsed >= DESIGN_REC_COOLDOWN_SECONDS:
        return True, 0
    return False, int(DESIGN_REC_COOLDOWN_SECONDS - elapsed)


@router.post("/sites/{business_id}/generate-design-recommendation")
async def generate_design_rec_endpoint(business_id: str, user: AuthedUser = Depends(require_user)):
    """Run the Designer Agent (LLM #1). Picks strand pair + ratio +
    sub-strand + layout archetype + accent style + 2 alternatives.

    Cold-start path (deterministic, no LLM) fires when bundle voice
    signals are below the 2-of-9 threshold.

    Owner-gated (audit 2026-08-01) — spends LLM budget and writes
    another tenant's site_config otherwise.
    """
    _require_business_owner(business_id, user)
    can_generate, seconds_remaining = _check_design_rec_cooldown(business_id)
    if not can_generate:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active. Try again in {seconds_remaining} seconds.",
        )

    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch, get_bundle
    except Exception as e:
        logger.warning(f"[design-rec] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "Business not found")
    business_data = biz_rows[0]

    try:
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[design-rec] get_bundle failed for {business_id}: {e}")
        bundle = {}

    profile_rows = be_get(
        f"/business_profiles?business_id=eq.{business_id}&select=*&limit=1"
    ) or []
    business_profile = profile_rows[0] if profile_rows else {}
    voice_profile = business_data.get("voice_profile") or {}
    brand_kit = (business_data.get("settings") or {}).get("brand_kit") or {}

    try:
        product_rows = be_get(
            f"/products?business_id=eq.{business_id}&is_active=eq.true&select=*&limit=20"
        ) or []
    except Exception:
        product_rows = []

    try:
        from studio_vocab_detect import detect_vocabulary_triple, has_meaningful_voice_signal
    except Exception as e:
        logger.warning(f"[design-rec] studio_vocab_detect import failed: {e}")
        raise HTTPException(500, "Vocab detector unavailable")

    primary_vocab_id, _, _ = detect_vocabulary_triple(
        business_data, business_profile, voice_profile, brand_kit
    )
    if not primary_vocab_id:
        raise HTTPException(400, "Cannot resolve vocabulary for this business")

    has_signal = has_meaningful_voice_signal(bundle, product_rows)
    cold_start = not has_signal

    # Stamp cooldown BEFORE the slow Claude call
    _design_rec_cooldown[business_id] = time.time()

    try:
        from studio_designer_agent import generate_design_recommendation
    except Exception as e:
        logger.warning(f"[design-rec] designer agent import failed: {e}")
        raise HTTPException(500, "Designer Agent unavailable")

    # Pass 4.0b PART 3 — feed Sparse-Input Enrichment to Designer.
    # Soft-fail: enrichment failure must NOT block recommendation. The
    # Designer's prompt simply omits the ENRICHMENT BRIEF block when
    # enriched_brief is None. We still run enrichment for cold-start so
    # the rec carries `_enrichment_available: True` for observability.
    enriched_brief = None
    try:
        from agents.sparse_input_enrichment import enrich_intake
        biz_for_enrich = bundle.get("business") or {}
        voice_for_enrich = bundle.get("voice") or {}
        intel_for_enrich = bundle.get("practitioner_intelligence") or {}
        strategy_for_enrich = (intel_for_enrich.get("strategy_track") or {})

        colors_in: list = []
        bk = brand_kit or {}
        for k in ("primary_color", "accent_color", "secondary_color"):
            v = bk.get(k)
            if v:
                colors_in.append(v)

        enriched_brief = enrich_intake(
            business_name=biz_for_enrich.get("name") or business_data.get("name") or "",
            description=(
                biz_for_enrich.get("elevator_pitch")
                or biz_for_enrich.get("tagline")
                or intel_for_enrich.get("about_business")
                or None
            ),
            colors=colors_in or None,
            practitioner_voice=(
                voice_for_enrich.get("brand_voice")
                or voice_for_enrich.get("tone_original")
                or None
            ),
            strategy_track_summary=strategy_for_enrich.get("summary") or None,
        )
    except Exception as e:
        logger.warning(f"[design-rec] enrichment soft-failed for {business_id}: {e}")
        enriched_brief = None

    rec, error = generate_design_recommendation(
        bundle, primary_vocab_id, product_rows, cold_start,
        enriched_brief=enriched_brief,
    )
    if not rec:
        raise HTTPException(500, f"Generation failed: {error}")

    # Persist into business_sites.site_config.design_recommendation
    site_id = None
    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if site_rows:
        site_id = site_rows[0]["id"]
        site_config = site_rows[0].get("site_config") or {}
        new_config = dict(site_config)
        new_config["design_recommendation"] = rec
        try:
            be_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
        except Exception as e:
            logger.warning(f"[design-rec] persist failed for {business_id}: {e}")
            # Generation succeeded; persist failure is recoverable next time

    # Pass 3.8b — auto-fire Brief Expander after recommendation succeeds.
    # Wrap in try/except so a brief failure does NOT 500 the recommendation
    # request. The recommendation itself is still useful even if the brief
    # expansion fails (user can manually retry via /expand-design-brief).
    auto_brief = None
    auto_expanded = False
    try:
        from studio_brief_expander import expand_design_brief
        auto_brief, brief_err = expand_design_brief(bundle, rec, product_rows)
        if auto_brief and site_id:
            # Re-fetch site_config so we don't clobber any concurrent write
            fresh_rows = be_get(
                f"/business_sites?id=eq.{site_id}&select=site_config&limit=1"
            ) or []
            fresh_config = (fresh_rows[0].get("site_config") if fresh_rows else {}) or {}
            fresh_config["design_brief"] = auto_brief
            try:
                be_patch(
                    f"/business_sites?id=eq.{site_id}", {"site_config": fresh_config}
                )
                # Stamp brief cooldown so explicit /expand-design-brief calls
                # respect the 60s window after auto-fire.
                _brief_expand_cooldown[business_id] = time.time()
                auto_expanded = True
            except Exception as e:
                logger.warning(f"[design-rec] auto-brief persist failed: {e}")
    except Exception as e:
        logger.warning(f"[design-rec] auto-brief expansion failed: {e}")

    # Pass 3.8d — auto-fire Builder Agent (LLM #3) once the brief expansion
    # succeeded. The Builder takes 60-120 s, longer than Railway's edge
    # gateway timeout (~60 s), so we kick it off in a background daemon
    # thread and return the recommendation + brief immediately. The user
    # polls /decoration-status to see when the HTML lands.
    auto_built_html_kicked_off = False
    if auto_brief and site_id:
        try:
            # Verify Builder module loads before launching the thread.
            from studio_builder_agent import build_html  # noqa: F401
            can_build, _ = _check_html_build_cooldown(business_id)
            if can_build and business_id not in _html_build_in_flight:
                _html_build_cooldown[business_id] = time.time()
                import threading
                threading.Thread(
                    target=_run_builder_job,
                    args=(business_id, site_id),
                    name=f"builder-auto-{business_id[:8]}",
                    daemon=True,
                ).start()
                auto_built_html_kicked_off = True
            else:
                logger.info(
                    f"[design-rec] Builder auto-fire skipped — "
                    f"cooldown_active={not can_build}, "
                    f"in_flight={business_id in _html_build_in_flight}"
                )
        except Exception as e:
            logger.warning(f"[design-rec] Builder auto-fire setup failed: {e}")

    response = {
        "ok": True,
        "recommendation": rec,
        "vocab_id": primary_vocab_id,
        "cold_start": cold_start,
        "auto_expanded": auto_expanded,
        "auto_built_html_kicked_off": auto_built_html_kicked_off,
    }
    if auto_brief:
        response["brief"] = auto_brief
    return response


# ─── Pass 3.8f.2: promote alternative recommendation ──────────────────
#
# The Designer Agent returns a primary recommendation plus 2 alternatives
# representing genuinely different creative positions. Promote-alternative
# swaps an alternative into primary, then re-fires the Brief Expander +
# Builder Agent so the live URL + preview pick up the new direction.

@router.post("/sites/{business_id}/promote-alternative")
async def promote_alternative_endpoint(business_id: str, alternative_index: int,
                                       user: AuthedUser = Depends(require_user)):
    """Promote one of the Designer Agent's alternatives to primary.
    Owner-gated: the reroute below kicks a background LLM compose that
    overwrites the live site.

    Reuses the design-rec cooldown (60s window) so the user can't thrash
    LLM calls. Re-fires Brief Expander + Builder in a background thread
    using the same _run_builder_job helper as /generate-design-recommendation.
    Returns immediately; client polls /decoration-status to see when
    html_generated_at advances past the call timestamp.

    ─── Smart Sites Arc 4 — RETIRED ENGINE, LIVE CALLER ────────────────
    Decision: LIVE frontend caller — DesignDNAPanel.tsx:224 "Use This
    Direction" → decorationGen.ts promoteAlternative (decorationGen.ts:333)
    — so NOT 410'd. Strand alternatives don't exist in the Module
    Composer; the honest equivalent of "try a different direction" is a
    fresh composer run, so when LEGACY_SITE_ENGINES is off (default) this
    kicks compose_site in a background thread (compose can exceed the 60s
    edge timeout — same returns-immediately semantics as before).
    Compatibility contract with the caller: it reads only ok/detail, then
    polls /decoration-status until html_generated_at advances — which the
    composer's render_and_persist writes.
    """
    if alternative_index not in (0, 1):
        raise HTTPException(
            status_code=400, detail="alternative_index must be 0 or 1",
        )
    _require_business_owner(business_id, user)

    import site_composer as _sc
    if not _sc.legacy_site_engines_enabled():
        logger.warning(f"[promote-alt] DEPRECATED path hit — rerouting to a "
                       f"fresh Module Composer compose for {business_id[:8]}")

        def _compose_bg_promote():
            try:
                _sc.compose_site(business_id)
            except Exception as e:
                logger.warning(f"[promote-alt] composer reroute failed: {e}")

        import threading
        threading.Thread(target=_compose_bg_promote,
                         name=f"composer-promote-{business_id[:8]}",
                         daemon=True).start()
        return {
            "ok": True,
            "engine": "module-composer",
            "deprecated": True,
            "promoted_index": alternative_index,
            "builder_kicked_off": True,
            "html_status": "building",
            "note": ("Design alternatives were retired with the legacy engine — "
                     "a fresh Module Composer composition is building instead. "
                     "POST /composer/compose directly next time."),
        }

    try:
        from brand_engine import (
            _sb_get as be_get, _sb_patch as be_patch, get_bundle,
        )
    except Exception as e:
        logger.warning(f"[promote-alt] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not site_rows:
        raise HTTPException(404, "business_sites missing")
    site_id = site_rows[0]["id"]
    site_config = site_rows[0].get("site_config") or {}

    current_rec = site_config.get("design_recommendation")
    if not current_rec:
        raise HTTPException(
            status_code=400,
            detail=(
                "No current recommendation. "
                "Run /generate-design-recommendation first."
            ),
        )

    alternatives = current_rec.get("alternatives") or []
    if alternative_index >= len(alternatives):
        raise HTTPException(
            status_code=400,
            detail=f"Only {len(alternatives)} alternatives available",
        )

    alt = alternatives[alternative_index]

    # Reuse the design-rec cooldown — promotion costs an LLM call (the
    # Brief Expander) plus an Opus call (the Builder), so the same 60s
    # gate that governs /generate-design-recommendation applies here.
    can_generate, seconds_remaining = _check_design_rec_cooldown(business_id)
    if not can_generate:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active. Try again in {seconds_remaining} seconds.",
        )

    new_rec: Dict[str, Any] = {
        "strand_a_id": alt["strand_a_id"],
        "strand_a_name": alt.get("strand_a_name"),
        "ratio_a": alt["ratio_a"],
        "strand_b_id": alt["strand_b_id"],
        "strand_b_name": alt.get("strand_b_name"),
        "ratio_b": alt["ratio_b"],
        # Keep the rest of the current direction so we don't lose
        # signature_moment / pacing_rhythm / voice_proof_quote when
        # promoting. These were tuned against the practitioner; the
        # alternative is a strand-pair swap, not a full re-tuning.
        "sub_strand_id": current_rec.get("sub_strand_id"),
        "layout_archetype": current_rec.get("layout_archetype"),
        "accent_style": current_rec.get("accent_style"),
        "site_type": current_rec.get("site_type", "full-site"),
        "signature_moment": current_rec.get("signature_moment"),
        "pacing_rhythm": current_rec.get("pacing_rhythm"),
        "voice_proof_quote": current_rec.get("voice_proof_quote"),
        "rationale": (
            f"Promoted from alternative: {alt.get('rationale', '')}"
            + (f". Tradeoff: {alt['tradeoff']}" if alt.get('tradeoff') else "")
        ),
        "alternatives": [],  # alternatives reset on promotion
        "cold_start": False,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "promoted_from_alternative": alternative_index,
    }

    # Stamp cooldown BEFORE the Brief Expander call so concurrent clicks
    # don't double-fire while we're computing.
    _design_rec_cooldown[business_id] = time.time()

    # Persist new recommendation immediately so /decoration-status reflects
    # the promotion even before the brief and HTML rebuild.
    site_config["design_recommendation"] = new_rec
    try:
        be_patch(
            f"/business_sites?id=eq.{site_id}",
            {"site_config": site_config},
        )
    except Exception as e:
        logger.warning(f"[promote-alt] persist new_rec failed: {e}")

    # Fetch deps for Brief Expander
    try:
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[promote-alt] get_bundle failed: {e}")
        bundle = {}

    try:
        product_rows = be_get(
            f"/products?business_id=eq.{business_id}&is_active=eq.true&select=*&limit=20"
        ) or []
    except Exception:
        product_rows = []

    # Re-fire Brief Expander (synchronous — fast)
    auto_brief = None
    try:
        from studio_brief_expander import expand_design_brief
        auto_brief, brief_err = expand_design_brief(bundle, new_rec, product_rows)
        if auto_brief:
            fresh_rows = be_get(
                f"/business_sites?id=eq.{site_id}&select=site_config&limit=1"
            ) or []
            fresh_config = (
                fresh_rows[0].get("site_config") if fresh_rows else {}
            ) or {}
            fresh_config["design_brief"] = auto_brief
            try:
                be_patch(
                    f"/business_sites?id=eq.{site_id}",
                    {"site_config": fresh_config},
                )
                _brief_expand_cooldown[business_id] = time.time()
            except Exception as e:
                logger.warning(f"[promote-alt] brief persist failed: {e}")
        elif brief_err:
            logger.warning(f"[promote-alt] brief expansion failed: {brief_err}")
    except Exception as e:
        logger.warning(f"[promote-alt] brief expansion exception: {e}")

    # Kick Builder in background — same pattern as /generate-design-recommendation
    builder_kicked = False
    if auto_brief:
        try:
            from studio_builder_agent import build_html  # noqa: F401
            can_build, _ = _check_html_build_cooldown(business_id)
            if can_build and business_id not in _html_build_in_flight:
                _html_build_cooldown[business_id] = time.time()
                import threading
                threading.Thread(
                    target=_run_builder_job,
                    args=(business_id, site_id),
                    name=f"builder-promote-{business_id[:8]}",
                    daemon=True,
                ).start()
                builder_kicked = True
            else:
                logger.info(
                    f"[promote-alt] Builder auto-fire skipped — "
                    f"cooldown_active={not can_build}, "
                    f"in_flight={business_id in _html_build_in_flight}"
                )
        except Exception as e:
            logger.warning(f"[promote-alt] Builder auto-fire setup failed: {e}")

    return {
        "ok": True,
        "promoted": alt,
        "promoted_index": alternative_index,
        "recommendation": new_rec,
        "brief_ready": auto_brief is not None,
        "builder_kicked_off": builder_kicked,
        "html_status": "building" if builder_kicked else "idle",
    }


# ─── Pass 3.8g: site-type ─────────────────────────────────────────────
#
# _multi_page_in_flight lived here — a guard stopping two concurrent
# /generate-multi-page calls racing through the cost-cap counter. It went
# with the endpoint (2026-08-13, site-builder audit). The concurrency it
# protected is chief_jobs' problem now, and that holds the invariant in
# the database rather than in a process-local set that a redeploy forgets.


@router.post("/sites/{business_id}/set-site-type")
async def set_site_type_endpoint(business_id: str, site_type: str,
                                 _biz: dict = Depends(business_access("admin"))):
    """Switch a business between landing-page and multi-page rendering.

    Persists site_config.site_type. Routing reads this on every public
    page load. Switching to multi-page does NOT immediately generate
    pages — the user must call /generate-multi-page.
    """
    if site_type not in ("landing-page", "multi-page"):
        raise HTTPException(
            status_code=400,
            detail="site_type must be 'landing-page' or 'multi-page'",
        )

    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch
    except Exception as e:
        logger.warning(f"[set-site-type] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not site_rows:
        raise HTTPException(404, "business_sites missing")
    site_id = site_rows[0]["id"]
    site_config = site_rows[0].get("site_config") or {}
    site_config["site_type"] = site_type
    try:
        be_patch(
            f"/business_sites?id=eq.{site_id}",
            {"site_config": site_config},
        )
    except Exception as e:
        logger.warning(f"[set-site-type] persist failed: {e}")
        raise HTTPException(500, "Persist failed")
    return {"ok": True, "site_type": site_type}


@router.post("/sites/{business_id}/generate-multi-page")
async def generate_multi_page_endpoint(business_id: str,
                                       user: AuthedUser = Depends(require_user)):
    """Generate every page in a multi-page site.

    ─── Smart Sites Arc 4 — RETIRED ENGINE, NO LIVE CALLER ─────────────
    Decision: 410 (2026-08-13, site-builder audit). The frontend caller
    — DesignDNAPanel's "Generate All Pages" — is gone, verified by grep
    across solutionist-studio/src; only explanatory comments remain.

    It had answered 503 to every caller since 2026-05-08 anyway, behind
    a kill switch that is itself now deleted, so the button's whole
    observable history was "Multi-page generation failed".

    Flipping that switch would not have earned it back. The Builder
    pipeline this drove is retired behind LEGACY_SITE_ENGINES, so the
    body below had become a reroute to ONE compose_site call — and
    compose_site already renders About / Services / Contact as a tail
    step whenever site_type is multi-page (site_composer.py, the
    site_multipage block). Every ordinary rebuild produces the pages.
    This was a second, pricier door to that: one paid build per press,
    against a daily cap shared across every tenant.

    The reroute also stamped site_config.site_pages = ["home"] AFTER
    compose_site had written ["home", "about", "services", "contact"],
    so a successful multi-page build reported itself as a single page.
    That clobber goes with it.

    Pages are managed in the studio (ComposedSiteControls), which reads
    site_config.generated_pages, and refreshed by rebuilding the site.
    """
    return JSONResponse(status_code=410, content={
        "error": "This page-build engine was retired. Secondary pages are "
                 "rendered with the site — rebuild it to refresh them."})



@router.get("/sites/{business_id}/design-signals")
async def design_signals_endpoint(business_id: str):
    """Diagnostic — returns the 9-signal breakdown + cold-start prediction.

    Free probe: no LLM call, no DB writes. Used by frontend Design DNA UI
    (3.8e) to show "your next generation will be cold-start because [X]"
    before the user clicks Generate.
    """
    try:
        from brand_engine import _sb_get as be_get, get_bundle
    except Exception as e:
        logger.warning(f"[design-signals] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=id&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "Business not found")

    try:
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[design-signals] get_bundle failed: {e}")
        bundle = {}

    try:
        product_rows = be_get(
            f"/products?business_id=eq.{business_id}&is_active=eq.true&select=name&limit=20"
        ) or []
    except Exception:
        product_rows = []

    try:
        from studio_vocab_detect import voice_signal_breakdown
        signals = voice_signal_breakdown(bundle, product_rows)
    except Exception as e:
        logger.warning(f"[design-signals] breakdown failed: {e}")
        signals = {}

    truthy = sum(1 for v in signals.values() if v)
    cold_start_predicted = truthy < 2

    # Surface the existing persisted recommendation + brief if any (for
    # the UI to know whether a regenerate would be first-time vs replace)
    persisted_rec = None
    persisted_brief = None
    try:
        site_rows = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
        ) or []
        if site_rows:
            sc = site_rows[0].get("site_config") or {}
            persisted_rec = sc.get("design_recommendation")
            persisted_brief = sc.get("design_brief")
    except Exception:
        persisted_rec = None
        persisted_brief = None

    can_generate, seconds_remaining = _check_design_rec_cooldown(business_id)
    can_expand_brief, brief_cooldown_remaining = _check_brief_expand_cooldown(business_id)

    return {
        "ok": True,
        "signals": signals,
        "signal_count": truthy,
        "threshold": 2,
        "cold_start_predicted": cold_start_predicted,
        "has_recommendation": bool(persisted_rec),
        "recommendation_generated_at": (persisted_rec or {}).get("generated_at"),
        "recommendation_was_cold_start": (persisted_rec or {}).get("cold_start"),
        # Pass 3.8b — brief presence
        "has_brief": bool(persisted_brief),
        "brief_generated_at": (persisted_brief or {}).get("generatedAt"),
        "brief_warnings": (persisted_brief or {}).get("_validation_warnings") or [],
        "can_generate": can_generate,
        "cooldown_remaining_seconds": seconds_remaining,
        "can_expand_brief": can_expand_brief,
        "brief_cooldown_remaining_seconds": brief_cooldown_remaining,
    }


@router.post("/sites/{business_id}/expand-design-brief")
async def expand_brief_endpoint(business_id: str,
                                _biz: dict = Depends(business_access("admin"))):
    """Pass 3.8b — manual idempotent Brief Expander call.

    Reads the persisted design_recommendation, runs LLM #2 to expand it
    into a full DesignBrief, and persists at site_config.design_brief.
    Used when the auto-fire chain in /generate-design-recommendation
    failed, OR when the user wants to regenerate just the brief without
    regenerating the strand pick.
    """
    can_expand, seconds_remaining = _check_brief_expand_cooldown(business_id)
    if not can_expand:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active. Try again in {seconds_remaining} seconds.",
        )

    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch, get_bundle
    except Exception as e:
        logger.warning(f"[expand-brief] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not site_rows:
        raise HTTPException(
            404, "business_sites row missing — enable Smart Sites first"
        )
    site_id = site_rows[0]["id"]
    site_config = site_rows[0].get("site_config") or {}

    recommendation = site_config.get("design_recommendation")
    if not recommendation:
        raise HTTPException(
            400,
            "No design_recommendation found. Run /generate-design-recommendation first.",
        )

    try:
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[expand-brief] get_bundle failed: {e}")
        bundle = {}

    try:
        product_rows = be_get(
            f"/products?business_id=eq.{business_id}&is_active=eq.true&select=*&limit=20"
        ) or []
    except Exception:
        product_rows = []

    # Stamp cooldown BEFORE the slow Claude call
    _brief_expand_cooldown[business_id] = time.time()

    try:
        from studio_brief_expander import expand_design_brief
    except Exception as e:
        logger.warning(f"[expand-brief] expander import failed: {e}")
        raise HTTPException(500, "Brief Expander unavailable")

    brief, error = expand_design_brief(bundle, recommendation, product_rows)
    if not brief:
        raise HTTPException(500, f"Brief expansion failed: {error}")

    # Persist
    new_config = dict(site_config)
    new_config["design_brief"] = brief
    try:
        be_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
    except Exception as e:
        logger.warning(f"[expand-brief] persist failed for {business_id}: {e}")

    return {
        "ok": True,
        "brief": brief,
        "had_warnings": bool(brief.get("_validation_warnings")),
        "warnings": brief.get("_validation_warnings") or [],
    }


def _run_builder_job(business_id: str, site_id: str) -> None:
    """Run the Builder Agent + persist outcome. Designed to be called from
    a daemon thread so it does not block the request thread.

    Reads its own bundle / products / testimonials / brief / scheme inside
    the worker so the caller doesn't have to gather them. All persistence
    paths (success and failure) write to site_config so /decoration-status
    reflects the outcome.

    Cooldown is stamped by the CALLER before launching the thread. The
    in-flight set is owned by this function: entered at the top, removed
    in the finally block.
    """
    if business_id in _html_build_in_flight:
        logger.warning(f"[builder-job] {business_id} already in flight; skip")
        return
    _html_build_in_flight.add(business_id)

    try:
        try:
            from brand_engine import (
                _sb_get as be_get, _sb_patch as be_patch, get_bundle,
            )
            from studio_builder_agent import build_html
        except Exception as e:
            logger.warning(f"[builder-job] import failed: {e}")
            return

        # Fetch fresh state inside the worker — site_config may have been
        # updated by /expand-design-brief or /generate-design-recommendation
        # between cooldown stamp and now.
        site_rows = be_get(
            f"/business_sites?id=eq.{site_id}&select=site_config&limit=1"
        ) or []
        if not site_rows:
            logger.warning(f"[builder-job] business_sites row vanished for {site_id}")
            return
        site_config = site_rows[0].get("site_config") or {}

        brief = site_config.get("design_brief")
        if not brief:
            logger.warning(f"[builder-job] design_brief missing for {business_id}")
            return

        scheme = site_config.get("generated_decoration")

        try:
            bundle = get_bundle(business_id) or {}
        except Exception as e:
            logger.warning(f"[builder-job] get_bundle failed: {e}")
            bundle = {}

        try:
            products = be_get(
                f"/products?business_id=eq.{business_id}"
                f"&status=eq.active&display_on_website=eq.true&select=*&limit=20"
            ) or []
            if not products:
                products = be_get(
                    f"/products?business_id=eq.{business_id}"
                    f"&status=eq.active&select=*&limit=20"
                ) or []
        except Exception:
            products = []

        try:
            testimonials = be_get(
                f"/testimonials?business_id=eq.{business_id}&select=*&limit=10"
            ) or []
        except Exception:
            testimonials = []

        # Pass 3.8f — third element is now warnings (quality heuristics).
        # On hard failure html is None and the third element holds the
        # structural validator's errors. On success-with-warnings the
        # third element is the quality validator's residual warnings
        # after one retry; HTML still ships.
        html, error, warnings = build_html(
            brief, bundle, scheme, products, testimonials,
        )

        # Re-fetch site_config so we don't clobber any concurrent write
        # while the slow Claude call was running (e.g., a brief regen).
        fresh_rows = be_get(
            f"/business_sites?id=eq.{site_id}&select=site_config&limit=1"
        ) or []
        fresh_config = (
            fresh_rows[0].get("site_config") if fresh_rows else {}
        ) or {}

        if not html:
            fresh_config["html_build_failed_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            fresh_config["html_build_error"] = error or "Unknown failure"
            fresh_config["html_validation_errors"] = warnings or []
            try:
                be_patch(
                    f"/business_sites?id=eq.{site_id}",
                    {"site_config": fresh_config},
                )
            except Exception as e:
                logger.warning(f"[builder-job] failure persist failed: {e}")
            logger.warning(
                f"[builder-job] {business_id} build failed: {error}; "
                f"errors={warnings}"
            )
            return

        fresh_config["generated_html"] = html
        fresh_config["html_generated_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        fresh_config.pop("html_build_failed_at", None)
        fresh_config.pop("html_build_error", None)
        fresh_config.pop("html_validation_errors", None)

        # Pass 3.8f — persist quality warnings (or clear them on a clean
        # pass) so /decoration-status can surface the diagnostic.
        if warnings:
            fresh_config["quality_warnings"] = warnings
        else:
            fresh_config.pop("quality_warnings", None)

        try:
            be_patch(
                f"/business_sites?id=eq.{site_id}",
                {"site_config": fresh_config},
            )
            if warnings:
                logger.info(
                    f"[builder-job] {business_id} build OK with "
                    f"{len(warnings)} quality warnings; html_length={len(html)}"
                )
            else:
                logger.info(
                    f"[builder-job] {business_id} build OK; "
                    f"html_length={len(html)}"
                )
        except Exception as e:
            logger.warning(f"[builder-job] success persist failed: {e}")
    finally:
        _html_build_in_flight.discard(business_id)


@router.post("/sites/{business_id}/generate-html")
async def generate_html_endpoint(business_id: str, user: AuthedUser = Depends(require_user)):
    """Pass 3.8d — manual idempotent Builder Agent call (LLM #3).

    Returns 202 immediately; the build runs in a background daemon thread
    because Railway's edge gateway times out long-running requests at ~60 s
    and a complete Builder pass takes 60-120 s. Poll /decoration-status to
    observe completion: `has_generated_html: true` means success;
    `html_build_failed_at` set means the most recent build failed.

    ─── Smart Sites Arc 4 — RETIRED ENGINE, NO LIVE CALLER ─────────────
    Decision: 410 when LEGACY_SITE_ENGINES is off (default). Verified
    2026-07-04: zero callers in the frontend repo (grep for
    "generate-html" across solutionist-studio/src matches nothing live —
    only .bak snapshots of decorationGen mention neighboring endpoints).
    The Builder-Agent pipeline this drove is superseded by the Module
    Composer end to end.
    """
    import site_composer as _sc
    if not _sc.legacy_site_engines_enabled():
        return JSONResponse(status_code=410, content={
            "error": "This build engine was retired — sites are composed by "
                     "the Module Composer. POST /composer/compose instead."})

    can_build, seconds_remaining = _check_html_build_cooldown(business_id)
    if not can_build:
        raise HTTPException(
            status_code=429,
            detail=f"Cooldown active. Try again in {seconds_remaining} seconds.",
        )

    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[generate-html] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
    ) or []
    if not site_rows:
        raise HTTPException(
            404, "business_sites row missing — enable Smart Sites first"
        )
    site_id = site_rows[0]["id"]
    site_config = site_rows[0].get("site_config") or {}

    if not site_config.get("design_brief"):
        raise HTTPException(
            400,
            "No design_brief found. Run /generate-design-recommendation first.",
        )

    # Validate the Builder module loads before we kick off the thread, so
    # configuration errors surface to the user as a 500 here, not silently
    # vanish into a daemon thread that never persists anything.
    try:
        from studio_builder_agent import build_html  # noqa: F401
    except Exception as e:
        logger.warning(f"[generate-html] builder import failed: {e}")
        raise HTTPException(500, "Builder Agent unavailable")

    # Stamp cooldown BEFORE launching the thread.
    _html_build_cooldown[business_id] = time.time()

    import threading
    threading.Thread(
        target=_run_builder_job,
        args=(business_id, site_id),
        name=f"builder-{business_id[:8]}",
        daemon=True,
    ).start()

    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "accepted": True,
            "message": (
                "Build started in background. Poll /decoration-status to "
                "observe completion (has_generated_html, html_generated_at, "
                "html_build_error, html_validation_errors)."
            ),
        },
    )


@router.get("/sites/{business_id}/preview-archetype/{archetype_id}")
async def preview_archetype_endpoint(business_id: str, archetype_id: str):
    """Pass 3.8c — render an archetype for a business and return HTML directly.

    Uses the business's stored design_brief. If brief missing, returns 404.
    Does NOT change live URL behavior — preview only. NO writes.
    """
    try:
        from brand_engine import _sb_get as be_get, get_bundle
    except Exception as e:
        logger.warning(f"[preview-archetype] brand_engine import failed: {e}")
        raise HTTPException(500, "Server misconfigured")

    biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
    if not biz_rows:
        raise HTTPException(404, "Business not found")
    business_data = biz_rows[0]

    site_rows = be_get(
        f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
    ) or []
    if not site_rows:
        raise HTTPException(404, "business_sites missing — enable Smart Sites first")
    site_config = site_rows[0].get("site_config") or {}

    brief = site_config.get("design_brief")
    if not brief:
        raise HTTPException(
            404,
            "design_brief missing — run /generate-design-recommendation first",
        )

    scheme = site_config.get("generated_decoration")

    try:
        bundle = get_bundle(business_id) or {}
    except Exception as e:
        logger.warning(f"[preview-archetype] get_bundle failed: {e}")
        bundle = {}

    # Defensive content reads — these tables may or may not exist depending
    # on how the business is set up. Missing tables degrade silently to [].
    # The products table uses status/display_on_website (not is_active).
    try:
        products = be_get(
            f"/products?business_id=eq.{business_id}"
            f"&status=eq.active&display_on_website=eq.true"
            f"&select=*&limit=20"
        ) or []
        if not products:
            # Fallback: some legacy rows may not have display_on_website set.
            # Try just status=active so the preview surfaces real catalog items.
            products = be_get(
                f"/products?business_id=eq.{business_id}"
                f"&status=eq.active&select=*&limit=20"
            ) or []
    except Exception:
        products = []
    try:
        testimonials = be_get(
            f"/testimonials?business_id=eq.{business_id}&select=*&limit=10"
        ) or []
    except Exception:
        testimonials = []
    # gallery_images and resources may be in JSONB module_entries — leave empty
    # for v1; archetypes that need them already fall back to product-cards.
    gallery: list = []
    resources: list = []

    try:
        from studio_render_context import build_context
        from studio_archetypes.dispatch import render_archetype
    except Exception as e:
        logger.warning(f"[preview-archetype] archetype import failed: {e}")
        raise HTTPException(500, "Archetype renderer unavailable")

    context = build_context(
        business_id, business_data, bundle, brief, scheme,
        products, testimonials, gallery, resources,
    )

    html = render_archetype(archetype_id, context)
    if not html:
        raise HTTPException(400, f"Unknown or failed archetype: {archetype_id}")

    return HTMLResponse(
        content=html,
        status_code=200,
        media_type="text/html",
        headers={"X-Solutionist-Source": f"archetype-preview:{archetype_id}"},
    )


@router.get("/public/widget/{module_id}")
async def get_widget(module_id: str):
    """Return a self-contained styled HTML page for iframe embedding."""
    if not _check_rate(module_id):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        modules = await _sb(client,
            f"/custom_modules?id=eq.{module_id}&is_active=eq.true&limit=1&select=*")
        if not modules:
            raise HTTPException(404, "Module not found")
        module = modules[0]

        pd = module.get("public_display") or {}
        if not pd.get("enabled"):
            raise HTTPException(403, "Module not publicly visible")

        biz_id = module["business_id"]
        biz_rows = await _sb(client,
            f"/businesses?id=eq.{biz_id}&select=name,type,voice_profile&limit=1")
        biz = biz_rows[0] if biz_rows else {}

        sort_field = pd.get("sort_by", "created_at")
        max_display = pd.get("max_display", 20)
        filter_status = pd.get("filter_status") or []
        visible = pd.get("visible_fields") or []
        hidden = pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"]

        raw = await _sb(client,
            f"/module_entries?module_id=eq.{module_id}&status=eq.active"
            f"&order={sort_field}.desc&limit={max_display}&select=id,data,created_at") or []

        entries = []
        for e in raw:
            data = e.get("data") or {}
            if filter_status and data.get("status") not in filter_status:
                continue
            entries.append(_filter_entry(data, visible, hidden))

        html = _build_widget_html(module, entries, biz)
        return HTMLResponse(content=html)


# ═══════════════════════════════════════════════════════════════════════
# LINK PAGE ENDPOINT
# ═══════════════════════════════════════════════════════════════════════


@router.get("/public/link/{slug}")
async def link_page_html(slug: str):
    """Render a Linktree-style link page."""
    if not _check_rate(f"link-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        # Find business by link_page slug
        biz_rows = await _sb(client, "/businesses?select=id,name,type,settings&limit=200")
        biz = None
        for b in (biz_rows or []):
            lp = (b.get("settings") or {}).get("link_page") or {}
            if lp.get("slug") == slug and lp.get("enabled"):
                biz = b
                break
        if not biz:
            raise HTTPException(404, "Link page not found")

        # Pass 3: Smart Sites flag-gate. Pull site_config to check the flag.
        biz_id_for_smart = biz["id"]
        site_rows = await _sb(client,
            f"/business_sites?business_id=eq.{biz_id_for_smart}&limit=1&select=site_config")
        if site_rows and _use_smart_sites(site_rows[0]):
            lp_for_smart = (biz.get("settings") or {}).get("link_page") or {}
            smart_links = lp_for_smart.get("custom_links") or []
            smart_html = await _try_render_smart_site(
                biz_id_for_smart, "link", links=smart_links)
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        brand = (biz.get("settings") or {}).get("brand_kit") or {}
        lp = (biz.get("settings") or {}).get("link_page") or {}
        colors = brand.get("colors") or _palette_for(biz.get("type", "general"))
        biz_name = biz.get("name", "")
        tagline = brand.get("tagline", "")
        practitioner = (biz.get("settings") or {}).get("practitioner_name", biz_name)

        layout = lp.get("layout", "stack")
        bg_style = lp.get("background", "gradient")
        primary = colors.get("primary", "#333")
        secondary = colors.get("secondary", "#666")
        bg = colors.get("background", "#faf8f5")
        text_color = colors.get("text", "#1a1a2e")

        if bg_style == "gradient":
            bg_css = f"linear-gradient(135deg, {primary}22, {secondary}22)"
        elif bg_style == "dark":
            bg_css = "#0d0d12"
            text_color = "#E8E4DD"
        else:
            bg_css = bg

        # Gather links
        biz_id = biz["id"]
        sites, forms, modules = await asyncio.gather(
            # site_config carries custom_domain — the Book link below is
            # absolute, so without it a practitioner's own domain loses.
            _sb(client, f"/business_sites?business_id=eq.{biz_id}&limit=1"
                        "&select=slug,site_config"),
            _sb(client, f"/intake_forms?business_id=eq.{biz_id}&is_active=eq.true&select=id,name&limit=20"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true&select=id,name,icon,public_display&limit=20"),
        )

        links_html = ""
        auto_links = []
        site_slug = sites[0]["slug"] if sites else None
        if site_slug:
            auto_links.append(("🌐", "Website", f"/public/site/{site_slug}"))
        # 2026-08-13 (post-audit gap list): this read settings.booking
        # .enabled — the retired store nothing writes any more — and
        # pointed at /public/booking/{slug}, the LEGACY page that 404s
        # for module-based businesses. So a practitioner with a fully
        # published modern booking page got no Book link at all, and the
        # only way to get one was the flag that produced a broken link.
        # Same detector the composer uses, same URL the Embed tab shares.
        if site_slug:
            try:
                from booking_widget_router import booking_is_live
                from business_sites_helpers import booking_url_for_site
                _live = await asyncio.to_thread(
                    booking_is_live, biz_id, biz.get("settings") or {})
                if _live:
                    auto_links.append(
                        ("📅", "Book a Session", booking_url_for_site(sites[0])))
            except Exception as _bk_e:
                logger.info(f"[link-page] booking link skipped: {_bk_e}")
        for f in (forms or []):
            auto_links.append(("📥", f["name"], "#"))
        for m in (modules or []):
            if (m.get("public_display") or {}).get("enabled"):
                auto_links.append((m.get("icon", "🧩"), m["name"], f"/public/widget/{m['id']}"))
        for cl in (lp.get("custom_links") or []):
            auto_links.append((cl.get("icon", "🔗"), cl.get("label", "Link"), cl.get("url", "#")))

        btn_style = (
            f"display:block;width:100%;padding:14px 20px;margin-bottom:10px;background:#fff;"
            f"border:1.5px solid {primary}30;border-radius:10px;text-decoration:none;"
            f"color:{text_color};font-weight:600;font-size:0.95em;text-align:center;"
            f"transition:transform 0.15s,box-shadow 0.15s;"
        )
        for icon, label, url in auto_links:
            links_html += f'<a href="{url}" style="{btn_style}" onmouseover="this.style.transform=\'translateY(-2px)\';this.style.boxShadow=\'0 4px 12px rgba(0,0,0,0.1)\'" onmouseout="this.style.transform=\'\';this.style.boxShadow=\'\'">{icon} {label}</a>\n'

        # Social icons
        socials = lp.get("social_profiles") or {}
        social_html = ""
        social_map = {"instagram": "📸", "facebook": "📘", "youtube": "📺", "twitter": "🐦", "linkedin": "💼", "tiktok": "🎵"}
        for platform, handle in socials.items():
            if not handle:
                continue
            social_html += f'<span style="font-size:1.4em;cursor:pointer;" title="{platform}: {handle}">{social_map.get(platform, "🔗")}</span> '

        # Optional gallery — pulls from media_library when toggled on
        gallery_html = ""
        if lp.get("show_gallery"):
            lib = ((biz.get("settings") or {}).get("media_library") or {})
            gallery_items = [g for g in (lib.get("gallery") or []) if g.get("show_on_website", True) and g.get("url")]
            gallery_items.sort(key=lambda g: g.get("sort_order") or 0)
            if gallery_items:
                tiles = "".join(
                    f'<a href="{_esc(g.get("url"))}" target="_blank" rel="noreferrer" '
                    f'style="display:block;aspect-ratio:1/1;border-radius:8px;overflow:hidden;background:#0001;">'
                    f'<img src="{_esc(g.get("url"))}" alt="{_esc(g.get("alt") or "")}" loading="lazy" '
                    f'style="width:100%;height:100%;object-fit:cover;display:block;" /></a>'
                    for g in gallery_items[:9]
                )
                gallery_html = (
                    f'<div style="margin-top:24px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">{tiles}</div>'
                )

        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{practitioner} — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:{bg_css};color:{text_color};min-height:100vh;display:flex;justify-content:center;padding:40px 20px;}}
.container{{max-width:420px;width:100%;text-align:center;}}
.avatar{{width:80px;height:80px;border-radius:50%;background:{primary};color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:2em;font-weight:700;margin-bottom:12px;}}
h1{{font-size:1.4em;font-weight:700;margin-bottom:4px;}}
.tagline{{color:{primary};font-size:0.9em;margin-bottom:24px;font-style:italic;}}
.socials{{margin-top:20px;display:flex;gap:12px;justify-content:center;}}
.footer{{margin-top:30px;font-size:0.7em;color:{text_color}55;}}
</style></head>
<body><div class="container">
<div class="avatar">{biz_name[0] if biz_name else '?'}</div>
<h1>{practitioner}</h1>
{f'<p class="tagline">{tagline}</p>' if tagline else f'<p class="tagline">{biz_name}</p>'}
{links_html}
{f'<div class="socials">{social_html}</div>' if social_html else ''}
{gallery_html}
<div class="footer">Powered by The Solutionist System</div>
</div></body></html>"""
        # Pass 3: legacy link page also gets favicons + OG tags now.
        html = _inject_brand_meta(html, biz_id_for_smart)
        return HTMLResponse(content=html)


@router.post("/public/link/{slug}/track")
async def track_link_click(slug: str, link_id: str = "", referrer: str = ""):
    """Log a link page click event."""
    if not _check_rate(f"link-track-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")
    async with httpx.AsyncClient() as client:
        biz_rows = await _sb(client, "/businesses?select=id,settings&limit=200")
        biz_id = None
        for b in (biz_rows or []):
            if ((b.get("settings") or {}).get("link_page") or {}).get("slug") == slug:
                biz_id = b["id"]
                break
        if not biz_id:
            raise HTTPException(404, "Business not found")
        await _sb_post(client, "/events", {
            "business_id": biz_id,
            "event_type": "link_page_click",
            "data": {"link_id": link_id, "referrer": referrer, "slug": slug},
            "source": "link_page",
        })
        return {"tracked": True}


# ═══════════════════════════════════════════════════════════════════════
# RESOURCE LIBRARY ENDPOINT
# ═══════════════════════════════════════════════════════════════════════


@router.get("/public/resources/{slug}")
async def resource_library_html(slug: str):
    """Render a public resource library page."""
    if not _check_rate(f"resources-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows, modules = await asyncio.gather(
            _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,settings&limit=1"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&name=eq.Resources&is_active=eq.true&limit=1&select=id"),
        )
        biz = biz_rows[0] if biz_rows else {}
        brand = (biz.get("settings") or {}).get("brand_kit") or {}
        colors = brand.get("colors") or _palette_for(biz.get("type", "general"))
        module_id = modules[0]["id"] if modules else None

        if not module_id:
            raise HTTPException(404, "No resource library")

        entries = await _sb(client,
            f"/module_entries?module_id=eq.{module_id}&status=eq.active&order=created_at.desc&limit=50&select=id,data") or []

        # Pass 3: Smart Sites flag-gate (try/except always falls through).
        if _use_smart_sites(sites[0]):
            smart_resources = [
                {**(e.get("data") or {}), "url": (e.get("data") or {}).get("resource_url")}
                for e in entries
            ]
            smart_html = await _try_render_smart_site(
                biz_id, "resources", resources=smart_resources)
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        primary = colors.get("primary", "#333")
        bg = colors.get("background", "#faf8f5")
        biz_name = biz.get("name", "")

        cards_html = ""
        for e in entries:
            d = e.get("data") or {}
            title = d.get("title", "(untitled)")
            desc = d.get("description", "")
            cat = d.get("category", "")
            access_type = d.get("access", "free")
            url = d.get("resource_url", "")
            is_gated = access_type == "gated"

            icon = "🔒" if is_gated else "📄"
            btn = f'<a href="{url}" target="_blank" style="display:inline-block;margin-top:10px;padding:8px 16px;background:{primary};color:#fff;border-radius:6px;text-decoration:none;font-size:0.85em;font-weight:600;">View Resource</a>' if url and not is_gated else '<span style="display:inline-block;margin-top:10px;padding:8px 16px;background:#ddd;color:#888;border-radius:6px;font-size:0.85em;">Contact us to access</span>'

            cards_html += f'''<div style="background:#fff;border:1px solid #e8e4dd;border-radius:10px;padding:18px;">
<div style="font-size:0.75em;text-transform:uppercase;letter-spacing:1px;color:{primary};font-weight:600;margin-bottom:6px;">{icon} {cat}</div>
<div style="font-size:1.05em;font-weight:600;margin-bottom:4px;">{title}</div>
{f'<div style="font-size:0.85em;color:#666;line-height:1.5;margin-bottom:4px;">{desc}</div>' if desc else ''}
{btn}
</div>'''

        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Resources — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:{bg};color:#1a1a2e;padding:40px 20px;}}
.container{{max-width:800px;margin:0 auto;}}
h1{{font-size:1.8em;font-weight:700;margin-bottom:8px;}}
.sub{{color:#666;margin-bottom:24px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;}}
</style></head>
<body><div class="container">
<h1>Resources</h1>
<p class="sub">{biz_name}</p>
<div class="grid">{cards_html}</div>
</div></body></html>"""
        # Pass 3: legacy resources page also gets favicons + OG tags now.
        html = _inject_brand_meta(html, biz_id)
        return HTMLResponse(content=html)


@router.post("/public/resources/{slug}/track")
async def track_resource_download(slug: str, resource_id: str = ""):
    """Log a resource download event."""
    if not _check_rate(f"res-track-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")
    async with httpx.AsyncClient() as client:
        sites = await _sb(client, f"/business_sites?slug=eq.{slug}&limit=1&select=business_id")
        if not sites:
            raise HTTPException(404, "Business not found")
        await _sb_post(client, "/events", {
            "business_id": sites[0]["business_id"],
            "event_type": "resource_download",
            "data": {"resource_id": resource_id},
            "source": "resource_library",
        })
        return {"tracked": True}


# ═══════════════════════════════════════════════════════════════════════
# BOOKING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════


@router.get("/public/booking/{slug}/slots")
async def booking_slots(slug: str, days: int = 14):
    """Return available time slots for the next N days."""
    if not _check_rate(f"booking-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        # Look up business by slug from business_sites
        sites = await _sb(client, f"/business_sites?slug=eq.{slug}&limit=1&select=business_id")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows = await _sb(client, f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]
        booking = (biz.get("settings") or {}).get("booking") or {}
        if not booking.get("enabled"):
            raise HTTPException(404, "Booking not enabled")

        available_days = set(booking.get("available_days", [1, 2, 3, 4, 5]))
        hours_start = booking.get("hours", {}).get("start", "09:00")
        hours_end = booking.get("hours", {}).get("end", "17:00")
        buffer = booking.get("buffer_minutes", 15)
        window = min(days, booking.get("booking_window_days", 14))
        session_types = list(booking.get("session_types", []) or [])
        durations = dict(booking.get("durations", {}) or {})

        # Pull bookable services from the products catalog. Any product
        # with type=service, status=active, display_on_website=true is
        # offered as a session type — that way adding a product in
        # BUILD -> Products & Services automatically makes it bookable.
        product_services = []
        try:
            product_services = await _sb(
                client,
                f"/products?business_id=eq.{biz_id}&status=eq.active"
                f"&type=eq.service&display_on_website=eq.true"
                f"&order=sort_order.asc&limit=50"
                f"&select=id,name,description,price,currency,pricing_type,duration_minutes"
            ) or []
        except Exception:
            product_services = []

        # Merge product services into the legacy session_types/durations
        # shape so the existing booking UI keeps working. Each product
        # name becomes a session type and its duration_minutes seeds the
        # durations map. Practitioner-defined session_types still win
        # for any name conflict.
        existing_keys = {str(t).lower() for t in session_types}
        product_meta: List[Dict[str, Any]] = []
        for p in product_services:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in existing_keys:
                session_types.append(name)
                existing_keys.add(key)
            dur = p.get("duration_minutes") or 60
            try:
                dur = int(dur)
            except (TypeError, ValueError):
                dur = 60
            if name not in durations:
                durations[name] = dur
            product_meta.append({
                "id": p.get("id"),
                "name": name,
                "description": p.get("description") or "",
                "price": p.get("price"),
                "currency": p.get("currency") or "USD",
                "pricing_type": p.get("pricing_type") or "fixed",
                "duration_minutes": dur,
            })
        min_duration = min(durations.values()) if durations else 60

        # Parse hours
        try:
            start_h, start_m = int(hours_start.split(":")[0]), int(hours_start.split(":")[1])
            end_h, end_m = int(hours_end.split(":")[0]), int(hours_end.split(":")[1])
        except (ValueError, IndexError):
            start_h, start_m, end_h, end_m = 9, 0, 17, 0

        # Get existing sessions in the window
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=window)
        existing = await _sb(client,
            f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
            f"&scheduled_for=gte.{now.isoformat().replace('+00:00', 'Z')}&scheduled_for=lte.{window_end.isoformat().replace('+00:00', 'Z')}"
            f"&select=scheduled_for,duration_minutes&limit=200") or []

        booked_ranges = []
        for s in existing:
            try:
                sdt = datetime.fromisoformat(s["scheduled_for"].replace("Z", "+00:00"))
                dur = s.get("duration_minutes") or 60
                booked_ranges.append((sdt, sdt + timedelta(minutes=dur + buffer)))
            except (ValueError, TypeError):
                pass

        # Generate slots
        slots = []
        for d in range(window):
            day = now.date() + timedelta(days=d + 1)
            # isoweekday: Mon=1 .. Sun=7
            if day.isoweekday() not in available_days:
                continue

            day_slots = []
            t_h, t_m = start_h, start_m
            while t_h < end_h or (t_h == end_h and t_m < end_m):
                slot_start = datetime(day.year, day.month, day.day, t_h, t_m, tzinfo=timezone.utc)
                slot_end = slot_start + timedelta(minutes=min_duration)
                if slot_end.hour > end_h or (slot_end.hour == end_h and slot_end.minute > end_m):
                    break

                # Check conflicts
                conflict = any(bs <= slot_start < be or bs < slot_end <= be for bs, be in booked_ranges)
                if not conflict:
                    day_slots.append(f"{t_h:02d}:{t_m:02d}")

                t_m += min_duration + buffer
                while t_m >= 60:
                    t_h += 1
                    t_m -= 60

            if day_slots:
                slots.append({"date": day.isoformat(), "times": day_slots})

        return {
            "slots": slots,
            "session_types": session_types,
            "durations": durations,
            "products": product_meta,
        }


class BookingSubmission(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    session_type: str
    date: str        # YYYY-MM-DD
    time: str        # HH:MM
    message: Optional[str] = None


@router.post("/public/booking/{slug}/submit")
async def booking_submit(slug: str, req: BookingSubmission,
                         request: Request = None):
    """Process a booking: create contact + session."""
    if not _check_rate(f"booking-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client, f"/business_sites?slug=eq.{slug}&limit=1&select=business_id")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows = await _sb(client, f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]
        booking = (biz.get("settings") or {}).get("booking") or {}
        if not booking.get("enabled"):
            raise HTTPException(404, "Booking not enabled")

        durations = booking.get("durations") or {}
        duration = durations.get(req.session_type, 60)

        # Parse scheduled time
        try:
            scheduled = datetime.fromisoformat(f"{req.date}T{req.time}:00+00:00")
        except ValueError:
            raise HTTPException(400, "Invalid date/time")

        # Conflict check
        buffer = booking.get("buffer_minutes", 15)
        slot_end = scheduled + timedelta(minutes=duration + buffer)
        conflicts = await _sb(client,
            f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
            # Z form — '+00:00' reads as a space in query strings; the
            # broken filter made this conflict check ALWAYS pass (silent
            # double-booking risk, 2026-07-21 platform bug class).
            f"&scheduled_for=gte.{(scheduled - timedelta(minutes=duration + buffer)).isoformat().replace('+00:00', 'Z')}"
            f"&scheduled_for=lte.{slot_end.isoformat().replace('+00:00', 'Z')}"
            f"&select=id&limit=1")
        if conflicts:
            raise HTTPException(409, "Time slot no longer available")

        # ── Find or create the contact ────────────────────────────
        # THE FIFTH LEAD DOOR, and the one that was easiest to miss:
        # it lives here in public_site rather than with the rest of
        # the booking code, so PR #574 (scoring) and PR #580
        # (attribution) both went past it. Its lookup was
        # `email=eq.{req.email}` — case sensitive AND unnormalized,
        # so a booking from Dana@X.com created a second contact
        # beside the existing dana@x.com and the two halves of that
        # person's history never met.
        import lead_attribution
        import lead_identity
        attribution = lead_attribution.capture(request,
                                               source_detail="booking page")
        resolution = await asyncio.to_thread(
            lead_identity.resolve, biz_id,
            name=req.name, email=req.email, phone=req.phone,
            source="booking_page",
            source_detail=lead_attribution.detail_for(attribution,
                                                      "booking page"),
            attribution=attribution or None)
        contact_id = resolution.contact_id

        if resolution.created and contact_id:
            # Score it, like every other door. Backgrounded: the
            # visitor is waiting on this request and nothing in it
            # reads the score.
            import lead_scoring
            lead_scoring.score_in_background(
                biz_id, contact_id,
                {"name": req.name, "email": req.email or "",
                 "phone": req.phone or "",
                 "session_type": req.session_type,
                 "date": req.date, "time": req.time,
                 "message": req.message or ""},
                source="booking_widget",
                email=req.email or "", phone=req.phone or "")

        # Create session
        session_title = f"{req.session_type.replace('_', ' ').title()} with {req.name}"
        new_session = await _sb_post(client, "/sessions", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "title": session_title,
            "session_type": req.session_type,
            "status": "scheduled",
            "scheduled_for": scheduled.isoformat(),
            "duration_minutes": duration,
            "notes": req.message or None,
        })
        session_id = new_session[0]["id"] if (new_session and isinstance(new_session, list)) else None

        # Log event
        await _sb_post(client, "/events", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "event_type": "booking_created",
            "data": {"session_id": session_id, "session_type": req.session_type, "source": "public_booking_page"},
            "source": "booking_page",
        })

        practitioner = (biz.get("settings") or {}).get("practitioner_name", biz.get("name", ""))
        return {
            "success": True,
            "session_id": session_id,
            "contact_id": contact_id,
            "message": f"You're booked! {req.session_type.replace('_', ' ').title()} with {practitioner} on {req.date} at {req.time}.",
        }


@router.get("/public/booking/{slug}")
async def booking_page_html(slug: str):
    """Return the public booking page HTML."""
    if not _check_rate(f"booking-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows = await _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,settings&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]
        booking = (biz.get("settings") or {}).get("booking") or {}
        if not booking.get("enabled"):
            raise HTTPException(404, "Booking not enabled")

        # Pass 3: Smart Sites flag-gate. v1 booking page is intentionally
        # minimal — Smart Sites v2 will inline the slot picker.
        if _use_smart_sites(sites[0]):
            smart_html = await _try_render_smart_site(biz_id, "booking")
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        brand = (biz.get("settings") or {}).get("brand_kit") or {}
        colors = brand.get("colors") or _palette_for(biz.get("type", "general"))
        practitioner = (biz.get("settings") or {}).get("practitioner_name", biz.get("name", ""))
        message = booking.get("message", "Pick a time that works for you.")
        biz_name = biz.get("name", "")
        primary = colors.get("primary") or colors.get("accent", "#333")
        bg = colors.get("background", "#faf8f5")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Book with {practitioner} — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:{bg};color:#1a1a2e;min-height:100vh;display:flex;justify-content:center;padding:40px 20px;}}
.container{{max-width:480px;width:100%;}}
h1{{font-size:1.6em;font-weight:700;margin-bottom:4px;}}
.sub{{color:#666;font-size:0.9em;margin-bottom:24px;line-height:1.5;}}
.msg{{padding:16px;background:rgba(0,0,0,0.03);border-radius:10px;margin-bottom:24px;font-style:italic;color:#555;line-height:1.5;}}
#slots{{margin-bottom:24px;}}
.day-header{{font-weight:600;font-size:0.85em;color:#888;text-transform:uppercase;letter-spacing:1px;margin:16px 0 8px;}}
.time-grid{{display:flex;flex-wrap:wrap;gap:8px;}}
.time-btn{{padding:8px 16px;border:1.5px solid {primary}40;border-radius:8px;background:#fff;color:{primary};font-weight:600;cursor:pointer;font-size:0.85em;transition:all 0.15s;}}
.time-btn:hover,.time-btn.sel{{background:{primary};color:#fff;border-color:{primary};}}
#form{{display:none;padding:20px;background:#fff;border:1px solid #e8e4dd;border-radius:12px;}}
.field{{margin-bottom:14px;}}
.field label{{display:block;font-size:0.75em;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px;}}
.field input,.field select,.field textarea{{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:6px;font-size:0.9em;font-family:inherit;}}
.field textarea{{resize:vertical;min-height:60px;}}
.submit-btn{{width:100%;padding:12px;background:{primary};color:#fff;border:none;border-radius:8px;font-weight:700;font-size:1em;cursor:pointer;margin-top:8px;}}
.submit-btn:disabled{{opacity:0.5;cursor:default;}}
#confirm{{display:none;text-align:center;padding:40px 20px;}}
#confirm h2{{color:{primary};margin-bottom:8px;}}
.loading{{color:#888;font-style:italic;padding:20px;text-align:center;}}
</style>
</head>
<body>
<div class="container">
<h1>Book with {practitioner}</h1>
<p class="sub">{biz_name}</p>
<div class="msg">{message}</div>
<div id="slots"><div class="loading">Loading available times…</div></div>
<div id="form">
<div class="field"><label>Name</label><input id="f-name" required></div>
<div class="field"><label>Email</label><input id="f-email" type="email"></div>
<div class="field"><label>Session Type</label><select id="f-type"></select></div>
<div class="field"><label>Message (optional)</label><textarea id="f-msg"></textarea></div>
<button class="submit-btn" id="book-btn" onclick="submitBooking()">Book Now</button>
</div>
<div id="confirm"><h2>✓ You're booked!</h2><p id="confirm-msg"></p></div>
</div>
<script>
const BASE='';
let selectedDate='',selectedTime='';
async function load(){{
  try{{
    const r=await fetch(BASE+'/public/booking/{slug}/slots');
    const d=await r.json();
    const c=document.getElementById('slots');
    if(!d.slots||d.slots.length===0){{c.innerHTML='<p>No available times right now. Please check back later.</p>';return;}}
    let h='';
    d.slots.forEach(day=>{{
      const dt=new Date(day.date+'T00:00:00');
      h+='<div class="day-header">'+dt.toLocaleDateString(undefined,{{weekday:'long',month:'short',day:'numeric'}})+'</div>';
      h+='<div class="time-grid">';
      day.times.forEach(t=>{{h+='<button class="time-btn" onclick="pick(\\''+day.date+'\\',\\''+t+'\\',this)">'+t+'</button>';}});
      h+='</div>';
    }});
    c.innerHTML=h;
    const sel=document.getElementById('f-type');
    (d.session_types||[]).forEach(t=>{{const o=document.createElement('option');o.value=t;o.textContent=t.replace(/_/g,' ');sel.appendChild(o);}});
  }}catch(e){{document.getElementById('slots').innerHTML='<p>Could not load times.</p>';}}
}}
function pick(date,time,btn){{
  selectedDate=date;selectedTime=time;
  document.querySelectorAll('.time-btn').forEach(b=>b.classList.remove('sel'));
  btn.classList.add('sel');
  document.getElementById('form').style.display='block';
  document.getElementById('form').scrollIntoView({{behavior:'smooth'}});
}}
async function submitBooking(){{
  const btn=document.getElementById('book-btn');btn.disabled=true;btn.textContent='Booking…';
  try{{
    const r=await fetch(BASE+'/public/booking/{slug}/submit',{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{
        name:document.getElementById('f-name').value,
        email:document.getElementById('f-email').value,
        session_type:document.getElementById('f-type').value,
        date:selectedDate,time:selectedTime,
        message:document.getElementById('f-msg').value||null,
      }})
    }});
    const d=await r.json();
    if(d.success){{
      document.getElementById('slots').style.display='none';
      document.getElementById('form').style.display='none';
      document.getElementById('confirm').style.display='block';
      document.getElementById('confirm-msg').textContent=d.message;
    }}else{{btn.disabled=false;btn.textContent='Book Now';alert(d.detail||'Booking failed');}}
  }}catch(e){{btn.disabled=false;btn.textContent='Book Now';alert('Booking failed');}}
}}
load();
</script>
</body>
</html>"""
        # Pass 3: legacy booking page also gets favicons + OG tags now.
        html = _inject_brand_meta(html, biz_id)
        return HTMLResponse(content=html)


@router.get("/public/health")
async def public_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "rate_limit_per_min": RATE_LIMIT_PER_MIN,
        "palettes": list(TYPE_PALETTES.keys()),
        "base_domains": BASE_DOMAINS,
    }


# ─── Pass 3.8g: cost cap diagnostic ───────────────────────────────────
@router.get("/design/exception-register")
async def design_exception_register(user: AuthedUser = Depends(require_user)):
    """Phase 2 (spec 3-J): the vocabulary roadmap — every 'wanted X,
    spec cannot express it' from the creative stages, ranked by
    frequency. This answers 'where is the decision-space too narrow'
    with data instead of taste. Requires a signed-in user."""
    try:
        from design_register import aggregate
        return {"ok": True, "register": aggregate()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@router.get("/design/health")
async def design_health(user: AuthedUser = Depends(require_user)):
    """P3 (2026-07-18): platform design telemetry — 'are the generated
    sites actually good', answered with data instead of taste. Aggregates
    the last 200 composed site_configs: vision-grader pass rate + mean
    rubric scores, DRO failure rate, atelier planned-vs-generated
    fallback rate (planned seats land on composes from P3 forward; older
    rows count generated only), invention-verification restatements.
    Requires a signed-in user."""
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            "/business_sites?order=updated_at.desc&limit=200"
            "&select=business_id,site_config,updated_at") or []
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    composes = [r for r in rows
                if (r.get("site_config") or {}).get("html_source")
                == "module-composer"]
    v_n = v_pass = 0
    impact_sum = smell_sum = 0.0
    dro_fail = 0
    at_planned = at_generated = at_active = 0
    inv_checked = inv_restatements = 0
    for r in composes:
        cfg = r.get("site_config") or {}
        v = cfg.get("vision_verdict") or {}
        if v:
            v_n += 1
            v_pass += 1 if v.get("passes_gate") else 0
            try:
                impact_sum += float(v.get("first_viewport_impact") or 0)
            except (TypeError, ValueError):
                pass
            try:
                smell_sum += float(v.get("template_smell") or 0)
            except (TypeError, ValueError):
                pass
        if cfg.get("dro_failure"):
            dro_fail += 1
        atl = cfg.get("atelier") if isinstance(cfg.get("atelier"), dict) else {}
        frags = atl.get("fragments") or {}
        if frags:
            at_active += 1
            at_generated += len(frags)
            try:
                at_planned += int(atl.get("planned") or len(frags))
            except (TypeError, ValueError):
                at_planned += len(frags)
        iv = cfg.get("invention_verification") or {}
        if iv.get("ok") is not None:
            inv_checked += 1
            if iv.get("ok") is False:
                inv_restatements += 1
    n = len(composes)
    return {"ok": True,
            "window": {"composed_sites": n, "business_sites_scanned": len(rows)},
            "vision": {"graded": v_n,
                       "pass_rate": round(v_pass / v_n, 3) if v_n else None,
                       "mean_first_viewport_impact": round(impact_sum / v_n, 2) if v_n else None,
                       "mean_template_smell": round(smell_sum / v_n, 2) if v_n else None},
            "dro": {"failures": dro_fail,
                    "failure_rate": round(dro_fail / n, 3) if n else None},
            "atelier": {"active": at_active,
                        "planned_seats": at_planned,
                        "generated": at_generated,
                        "fallback_rate": (round(1 - at_generated / at_planned, 3)
                                          if at_planned else None)},
            "inventions": {"verified": inv_checked,
                           "restatements": inv_restatements}}


# GET /system/cost-cap-status lived here. Its docstring claimed "used by
# ops + frontend"; at removal (2026-08-13, site-builder audit) it had
# zero callers in either repo. It reported a counter nothing incremented.


# ═══════════════════════════════════════════════════════════════════════
# SUBDOMAIN ROUTING — Root domain + catch-all
# ═══════════════════════════════════════════════════════════════════════
# MUST be registered LAST so they don't shadow API routes.
# They only fire when the Host header is a mysolutionist.app subdomain.
# API calls from kmj-intake-server-production.up.railway.app pass through
# because extract_slug_from_host returns None → 404 → FastAPI continues.

MARKETING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>The Solutionist System — One workspace that runs your whole practice</title>
<meta name="description" content="The Solutionist System is one AI-powered workspace that replaces 8+ tools for solo practitioners. Contacts, invoices, sessions, content, goals, and a Chief of Staff that knows your business.">
<meta property="og:title" content="The Solutionist System">
<meta property="og:description" content="One AI-powered workspace that runs your whole practice. Built for pastors, coaches, consultants, and solo studios.">
<meta property="og:url" content="https://mysolutionist.app">
<meta property="og:type" content="website">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* ─── tokens (mirrors the app's Neon Command theme) ─── */
  :root {
    --bg: #0a0a0e;
    --bg-2: #11111a;
    --surface: rgba(255,255,255,0.04);
    --surface-2: rgba(255,255,255,0.06);
    --border: rgba(255,255,255,0.08);
    --border-strong: rgba(255,255,255,0.14);
    --text-primary: #fafafa;
    --text-secondary: #d4d4d4;
    --text-muted: #a1a1a1;
    --text-dim: #737373;
    --accent: #7c3aed;
    --accent-2: #6366f1;
    --info: #06b6d4;
    --success: #34d399;
    --warning: #fbbf24;
    --danger: #f87171;
    --glow: rgba(124, 58, 237, 0.35);
    --glow-cyan: rgba(6, 182, 212, 0.28);
    --font-heading: 'Space Grotesk', system-ui, sans-serif;
    --font-body: 'Inter', system-ui, sans-serif;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{background:var(--bg);color:var(--text-primary);font-family:var(--font-body);line-height:1.6;-webkit-font-smoothing:antialiased;}
  body{overflow-x:hidden;}
  a{color:inherit;text-decoration:none;}

  /* ─── shared atoms ─── */
  .container{max-width:1140px;margin:0 auto;padding:0 28px;}
  .eyebrow{display:inline-flex;align-items:center;gap:8px;padding:5px 14px;font-size:10px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);background:color-mix(in srgb, var(--accent) 12%, transparent);border:1px solid color-mix(in srgb, var(--accent) 28%, transparent);border-radius:99px;}
  .gradient-text{background:linear-gradient(135deg, var(--accent), var(--info));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
  h1,h2,h3{font-family:var(--font-heading);letter-spacing:-0.015em;line-height:1.1;}
  h1{font-size:clamp(38px, 6vw, 64px);font-weight:600;}
  h2{font-size:clamp(28px, 4vw, 40px);font-weight:600;margin-bottom:14px;}
  h3{font-size:18px;font-weight:600;color:var(--text-primary);margin-bottom:6px;}
  p{color:var(--text-secondary);font-size:16px;}
  .lead{font-size:18px;color:var(--text-muted);line-height:1.65;}

  /* ─── nav ─── */
  .nav{position:sticky;top:0;z-index:50;background:rgba(10,10,14,0.78);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--border);}
  .nav-inner{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;max-width:1140px;margin:0 auto;}
  .brand{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.01em;}
  .brand .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));margin-right:9px;box-shadow:0 0 10px var(--glow);}
  .nav-links{display:flex;align-items:center;gap:22px;font-size:13px;font-weight:500;}
  .nav-links a{color:var(--text-muted);transition:color 0.15s;}
  .nav-links a:hover{color:var(--text-primary);}
  .nav-cta{padding:8px 16px;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary);border-radius:8px;font-weight:600;font-size:13px;box-shadow:0 2px 14px color-mix(in srgb, var(--accent) 28%, transparent);transition:transform 0.15s, box-shadow 0.15s;}
  .nav-cta:hover{transform:translateY(-1px);box-shadow:0 4px 18px color-mix(in srgb, var(--accent) 42%, transparent);}
  @media (max-width: 720px){.nav-links{gap:12px;font-size:12px;} .nav-links a:not(.nav-cta){display:none;}}

  /* ─── hero ─── */
  .hero{position:relative;padding:88px 0 96px;text-align:center;overflow:hidden;}
  .hero::before{content:'';position:absolute;inset:-80px 0 auto;height:520px;background:radial-gradient(60% 80% at 50% 0%, var(--glow), transparent 70%);pointer-events:none;}
  .hero::after{content:'';position:absolute;left:50%;top:-40px;transform:translateX(-50%);width:560px;height:560px;border-radius:50%;background:radial-gradient(circle at center, var(--glow-cyan), transparent 65%);pointer-events:none;opacity:0.5;}
  .hero .container{position:relative;z-index:1;}
  .hero h1{margin:18px auto 22px;max-width:900px;}
  .hero h1 .accent{background:linear-gradient(135deg, var(--accent), var(--info));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
  .hero .lead{max-width:680px;margin:0 auto 36px;}
  .hero-ctas{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;}
  .btn-primary{display:inline-flex;align-items:center;gap:8px;padding:13px 26px;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary);font-weight:600;font-size:14px;border-radius:10px;border:none;cursor:pointer;box-shadow:0 4px 22px color-mix(in srgb, var(--accent) 35%, transparent);transition:transform 0.15s, box-shadow 0.15s;}
  .btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 30px color-mix(in srgb, var(--accent) 50%, transparent);}
  .btn-secondary{display:inline-flex;align-items:center;gap:8px;padding:13px 22px;background:var(--surface);color:var(--text-primary);font-weight:600;font-size:14px;border-radius:10px;border:1px solid var(--border-strong);cursor:pointer;transition:background 0.15s, border-color 0.15s;}
  .btn-secondary:hover{background:var(--surface-2);border-color:color-mix(in srgb, var(--accent) 50%, transparent);}
  .hero-note{margin-top:22px;font-size:12px;color:var(--text-dim);}

  /* ─── section base ─── */
  section{position:relative;padding:80px 0;}
  .section-head{text-align:center;max-width:680px;margin:0 auto 56px;}
  .section-head .eyebrow{margin-bottom:14px;}
  .section-head p{color:var(--text-muted);margin-top:8px;}

  /* ─── glass card ─── */
  .card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:26px;transition:transform 0.18s, border-color 0.18s, background 0.18s;}
  .card:hover{transform:translateY(-2px);border-color:color-mix(in srgb, var(--accent) 35%, transparent);background:color-mix(in srgb, var(--surface) 100%, transparent);}
  .card-icon{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:10px;background:color-mix(in srgb, var(--accent) 14%, transparent);color:var(--accent);font-size:20px;margin-bottom:14px;border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);}

  /* ─── features grid ─── */
  .features-grid{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;}
  @media (max-width: 920px){.features-grid{grid-template-columns:repeat(2, 1fr);}}
  @media (max-width: 600px){.features-grid{grid-template-columns:1fr;}}
  .feature-card p{font-size:14px;color:var(--text-muted);line-height:1.6;}

  /* ─── audience ─── */
  .audience{padding:64px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);background:linear-gradient(180deg, transparent, color-mix(in srgb, var(--accent) 4%, transparent), transparent);}
  .audience-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
  .audience-pill{display:inline-flex;align-items:center;gap:8px;padding:10px 18px;background:var(--surface);border:1px solid var(--border);border-radius:99px;font-size:14px;font-weight:500;color:var(--text-secondary);transition:border-color 0.18s, background 0.18s;}
  .audience-pill:hover{border-color:color-mix(in srgb, var(--accent) 40%, transparent);background:color-mix(in srgb, var(--accent) 8%, transparent);}
  .audience-pill .emoji{font-size:18px;}

  /* ─── how it works ─── */
  .how-grid{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;position:relative;}
  @media (max-width: 920px){.how-grid{grid-template-columns:1fr;}}
  .step-card{position:relative;}
  .step-num{position:absolute;top:-14px;left:24px;display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary);font-family:var(--font-heading);font-weight:700;font-size:13px;letter-spacing:0;box-shadow:0 0 16px var(--glow);}

  /* ─── why us ─── */
  .why-grid{display:grid;grid-template-columns:repeat(2, 1fr);gap:18px;}
  @media (max-width: 760px){.why-grid{grid-template-columns:1fr;}}
  .why-card{display:flex;gap:16px;}
  .why-card .check{flex-shrink:0;width:32px;height:32px;border-radius:8px;background:color-mix(in srgb, var(--success) 18%, transparent);color:var(--success);display:inline-flex;align-items:center;justify-content:center;font-weight:700;border:1px solid color-mix(in srgb, var(--success) 40%, transparent);}

  /* ─── meta callout ─── */
  .meta-callout{padding:36px;background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 10%, transparent), color-mix(in srgb, var(--info) 8%, transparent));border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);border-radius:18px;text-align:center;}
  .meta-callout .platforms{display:inline-flex;align-items:center;gap:10px;margin-bottom:18px;font-size:12px;font-weight:600;letter-spacing:1.6px;text-transform:uppercase;color:var(--text-muted);}
  .meta-callout .platforms .badge-pill{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:99px;background:var(--surface-2);border:1px solid var(--border);font-size:11px;color:var(--text-secondary);text-transform:none;letter-spacing:0;}

  /* ─── final CTA ─── */
  .final-cta{padding:96px 0;text-align:center;position:relative;overflow:hidden;}
  .final-cta::before{content:'';position:absolute;inset:0;background:radial-gradient(60% 100% at 50% 50%, var(--glow), transparent 65%);pointer-events:none;opacity:0.65;}
  .final-cta .container{position:relative;z-index:1;}
  .final-cta h2{margin-bottom:14px;}
  .final-cta p{max-width:520px;margin:0 auto 32px;color:var(--text-muted);}

  /* ─── footer ─── */
  footer{background:var(--bg-2);border-top:1px solid var(--border);padding:42px 0 32px;}
  .footer-inner{max-width:1140px;margin:0 auto;padding:0 28px;display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap;}
  .footer-brand{display:flex;flex-direction:column;gap:6px;}
  .footer-brand .small{font-size:12px;color:var(--text-dim);}
  .footer-links{display:flex;flex-wrap:wrap;gap:18px;font-size:13px;}
  .footer-links a{color:var(--text-muted);transition:color 0.15s;}
  .footer-links a:hover{color:var(--text-primary);}
  .footer-bottom{max-width:1140px;margin:32px auto 0;padding:16px 28px 0;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;}

  /* ═════ Animation pass: motion that mirrors the app heroes ═════ */
  /* Brand-dot heartbeat (persistent, sub-2s cycle) */
  @keyframes brandPulse {
    0%, 100% { box-shadow: 0 0 10px var(--glow); }
    50%      { box-shadow: 0 0 16px var(--glow), 0 0 4px color-mix(in srgb, var(--accent) 80%, transparent); }
  }
  .brand .dot, .footer-brand .brand .dot { animation: brandPulse 2.6s ease-in-out infinite; }

  /* Floating background orbs in the hero — drift slowly to give the
     page a "living" feeling without distracting the eye. */
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(50px);
    opacity: 0.55;
    pointer-events: none;
    z-index: 0;
  }
  .orb-1 { top: 10%;  left: 8%;   width: 280px; height: 280px;
           background: radial-gradient(circle, var(--glow), transparent 70%);
           animation: orbDrift1 18s ease-in-out infinite; }
  .orb-2 { top: 60%;  right: 6%;  width: 220px; height: 220px;
           background: radial-gradient(circle, var(--glow-cyan), transparent 70%);
           animation: orbDrift2 22s ease-in-out infinite; }
  .orb-3 { bottom:-40px; left: 40%; width: 200px; height: 200px;
           background: radial-gradient(circle, color-mix(in srgb, var(--accent-2) 35%, transparent), transparent 70%);
           animation: orbDrift3 26s ease-in-out infinite; opacity: 0.4; }
  @keyframes orbDrift1 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(40px, -30px); } }
  @keyframes orbDrift2 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-30px, 25px); } }
  @keyframes orbDrift3 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(20px, -20px); } }

  /* Scroll reveal — IntersectionObserver at the bottom of body adds
     .visible when an element enters view; CSS handles the transition. */
  .reveal { opacity: 0; transform: translateY(18px); transition: opacity 0.6s ease, transform 0.6s ease; }
  .reveal.visible { opacity: 1; transform: translateY(0); }
  .reveal-delay-1 { transition-delay: 0.08s; }
  .reveal-delay-2 { transition-delay: 0.16s; }
  .reveal-delay-3 { transition-delay: 0.24s; }

  /* Stat highlight in hero — count-up effect via animated stroke */
  .stat-block { display: inline-flex; align-items: baseline; gap: 8px; margin-top: 6px; padding: 8px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 99px; font-size: 13px; color: var(--text-muted); }
  .stat-block .big { font-family: var(--font-heading); font-size: 22px; font-weight: 700; color: transparent;
                     background: linear-gradient(135deg, var(--accent), var(--info));
                     -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; line-height: 1; }
  .stat-block .big::after { content: ''; display: inline-block; width: 4px; height: 4px; border-radius: 50%; background: var(--accent); margin-left: 6px; box-shadow: 0 0 6px var(--glow); animation: brandPulse 1.8s ease-in-out infinite; }

  /* ═════ Signature mini-visuals inside feature cards ═════ */
  .mini-visual { height: 64px; margin-bottom: 18px; position: relative;
                 background: linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 60%, transparent), transparent);
                 border-radius: 10px; overflow: hidden;
                 display: flex; align-items: center; justify-content: center; }

  /* Orbit (Command Center) */
  .mv-orbit { position: relative; width: 56px; height: 56px; }
  .mv-orbit::before, .mv-orbit::after { content: ''; position: absolute; border-radius: 50%; border: 1px dashed color-mix(in srgb, var(--accent) 35%, transparent); }
  .mv-orbit::before { inset: 0; }
  .mv-orbit::after  { inset: 12px; border-color: color-mix(in srgb, var(--info) 35%, transparent); }
  .mv-orbit .center { position: absolute; top: 50%; left: 50%; width: 10px; height: 10px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--info)); transform: translate(-50%, -50%); box-shadow: 0 0 10px var(--glow); }
  .mv-orbit .moon { position: absolute; top: 50%; left: 50%; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); margin: -3px 0 0 -3px;
                     animation: orbitSpin 6s linear infinite; transform-origin: 0 0; }
  .mv-orbit .moon-2 { background: var(--info); animation-duration: 9s; animation-delay: -3s; }
  @keyframes orbitSpin { from { transform: rotate(0deg) translateX(22px) rotate(0deg); }
                          to   { transform: rotate(360deg) translateX(22px) rotate(-360deg); } }

  /* Stacked cards (Build) */
  .mv-stack { position: relative; width: 64px; height: 48px; }
  .mv-stack span { position: absolute; width: 48px; height: 30px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); transition: transform 0.25s ease; }
  .mv-stack span:nth-child(1) { top: 0;  left: 0;  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, transparent), transparent); }
  .mv-stack span:nth-child(2) { top: 6px; left: 8px; background: linear-gradient(135deg, color-mix(in srgb, var(--info) 16%, transparent), transparent); animation: stackFloat 5s ease-in-out infinite; }
  .mv-stack span:nth-child(3) { top: 14px; left: 16px; background: linear-gradient(135deg, color-mix(in srgb, var(--success) 15%, transparent), transparent); animation: stackFloat 5s ease-in-out infinite; animation-delay: -2.5s; }
  @keyframes stackFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }

  /* Calendar grid pulse (Operate) */
  .mv-grid { display: grid; grid-template-columns: repeat(5, 8px); grid-template-rows: repeat(3, 8px); gap: 3px; }
  .mv-grid span { width: 8px; height: 8px; border-radius: 2px; background: color-mix(in srgb, var(--accent) 14%, transparent); border: 1px solid var(--border); }
  .mv-grid span.live { background: linear-gradient(135deg, var(--accent), var(--info)); border-color: transparent; box-shadow: 0 0 6px var(--glow); animation: gridPing 2.4s ease-in-out infinite; }
  @keyframes gridPing { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(1.2); } }

  /* Rising bars (Grow) */
  .mv-bars { display: flex; align-items: flex-end; gap: 4px; height: 36px; }
  .mv-bars span { width: 6px; border-radius: 2px 2px 0 0; background: linear-gradient(180deg, var(--accent), var(--info)); animation: barRise 3.2s ease-in-out infinite; }
  .mv-bars span:nth-child(1) { height: 40%; animation-delay: -0.0s; }
  .mv-bars span:nth-child(2) { height: 70%; animation-delay: -0.4s; }
  .mv-bars span:nth-child(3) { height: 55%; animation-delay: -0.8s; }
  .mv-bars span:nth-child(4) { height: 90%; animation-delay: -1.2s; }
  .mv-bars span:nth-child(5) { height: 65%; animation-delay: -1.6s; }
  @keyframes barRise { 0%,100% { transform: scaleY(0.85); opacity: 0.85; transform-origin: bottom; } 50% { transform: scaleY(1.05); opacity: 1; } }

  /* Pulsing sparkle (Chief) */
  .mv-spark { position: relative; width: 36px; height: 36px; }
  .mv-spark::before, .mv-spark::after { content: ''; position: absolute; inset: 0; border-radius: 50%; border: 1px solid var(--accent); opacity: 0.5; animation: sparkExpand 2.6s ease-out infinite; }
  .mv-spark::after { animation-delay: -1.3s; border-color: var(--info); }
  .mv-spark .core { position: absolute; top: 50%; left: 50%; width: 12px; height: 12px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--info)); transform: translate(-50%, -50%); box-shadow: 0 0 14px var(--glow); }
  @keyframes sparkExpand { 0% { transform: scale(0.4); opacity: 0.9; } 100% { transform: scale(1.6); opacity: 0; } }

  /* FB ↔ IG flow (Publish) */
  .mv-publish { display: flex; align-items: center; gap: 12px; }
  .mv-publish .platform { width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; color: #fff; }
  .mv-publish .fb { background: #1877F2; }
  .mv-publish .ig { background: linear-gradient(135deg, #833AB4, #FD1D1D, #FCB045); }
  .mv-publish .flow { flex: 1; min-width: 16px; max-width: 24px; height: 2px; background: linear-gradient(90deg, transparent, var(--accent), var(--info), transparent); background-size: 200% 100%; animation: flowSweep 2.4s linear infinite; border-radius: 2px; }
  @keyframes flowSweep { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

  /* ═════ Comparison table ═════ */
  .compare { width: 100%; border-collapse: separate; border-spacing: 0;
             background: var(--surface); border: 1px solid var(--border); border-radius: 16px; overflow: hidden;
             font-family: var(--font-body); }
  .compare th, .compare td { padding: 14px 18px; text-align: left; font-size: 14px; }
  .compare thead { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  .compare thead th { font-family: var(--font-heading); font-weight: 600; color: var(--text-primary); letter-spacing: -0.005em; font-size: 13px; border-bottom: 1px solid var(--border); }
  .compare thead th.sol-col { color: var(--accent); }
  .compare tbody td { border-top: 1px solid var(--border); color: var(--text-secondary); }
  .compare tbody td:first-child { font-weight: 600; color: var(--text-primary); }
  .compare td.sol { color: var(--success); }
  .compare td.alt { color: var(--text-muted); font-style: italic; }
  .compare-foot { margin-top: 12px; font-size: 12px; color: var(--text-dim); text-align: center; font-style: italic; }
  @media (max-width: 720px) {
    .compare th, .compare td { padding: 10px 12px; font-size: 12.5px; }
  }

  /* ═════ Everything-included list ═════ */
  .included-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
  @media (max-width: 760px) { .included-grid { grid-template-columns: 1fr; } }
  .included-cat { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 22px; }
  .included-cat h3 { font-family: var(--font-heading); font-size: 16px; color: var(--accent); margin-bottom: 12px; letter-spacing: -0.01em; }
  .included-cat ul { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px 10px; }
  .included-cat li { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-secondary); padding: 4px 10px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; }
  .included-cat li::before { content: ''; width: 4px; height: 4px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--info)); }

  /* ═════ FAQ ═════ */
  .faq-list { display: flex; flex-direction: column; gap: 10px; }
  .faq-item { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; transition: border-color 0.18s; }
  .faq-item[open] { border-color: color-mix(in srgb, var(--accent) 45%, transparent); }
  .faq-item summary { padding: 18px 22px; cursor: pointer; font-family: var(--font-heading); font-weight: 600; font-size: 15px; color: var(--text-primary); list-style: none; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .faq-item summary::-webkit-details-marker { display: none; }
  .faq-item summary::after { content: '+'; font-family: var(--font-body); font-weight: 400; font-size: 22px; color: var(--accent); transition: transform 0.18s; line-height: 1; }
  .faq-item[open] summary::after { transform: rotate(45deg); }
  .faq-body { padding: 0 22px 20px; font-size: 14.5px; color: var(--text-secondary); line-height: 1.65; }
  .faq-body p { margin-bottom: 10px; }
  .faq-body p:last-child { margin-bottom: 0; }

  /* ═════ Founder note ═════ */
  .founder { position: relative; padding: 36px; background: var(--surface); border: 1px solid var(--border); border-radius: 18px;
             display: grid; grid-template-columns: 64px 1fr; gap: 22px; align-items: flex-start; }
  @media (max-width: 640px) { .founder { grid-template-columns: 1fr; padding: 28px; } }
  .founder-avatar { width: 64px; height: 64px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
                    background: linear-gradient(135deg, var(--accent), var(--info)); color: var(--text-primary); font-family: var(--font-heading); font-weight: 600; font-size: 24px; box-shadow: 0 4px 22px var(--glow); }
  .founder-body p { font-size: 15.5px; line-height: 1.7; color: var(--text-secondary); margin-bottom: 14px; }
  .founder-body p:last-of-type { margin-bottom: 0; }
  .founder-sig { margin-top: 14px; font-family: var(--font-heading); font-weight: 600; color: var(--text-primary); font-size: 14px; }
  .founder-sig .small { display: block; font-family: var(--font-body); font-weight: 400; font-size: 12px; color: var(--text-dim); margin-top: 2px; }
</style>
</head>
<body>

<!-- ═══ NAV ═══ -->
<nav class="nav">
  <div class="nav-inner">
    <a class="brand" href="/"><span class="dot"></span>The Solutionist System</a>
    <div class="nav-links">
      <a href="#features">Features</a>
      <a href="#compare">Compare</a>
      <a href="#faq">FAQ</a>
      <a href="/help">Help</a>
      <a class="nav-cta" href="mailto:kmjcreativesolution@gmail.com?subject=Get%20Started%20with%20Solutionist">Get Started</a>
    </div>
  </div>
</nav>

<!-- ═══ HERO ═══ -->
<section class="hero">
  <span class="orb orb-1" aria-hidden></span>
  <span class="orb orb-2" aria-hidden></span>
  <span class="orb orb-3" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">For solo practitioners + small studios</span>
    <h1 class="reveal reveal-delay-1">One workspace that runs your <span class="accent">whole practice.</span></h1>
    <p class="lead reveal reveal-delay-2">Contacts, invoices, sessions, content, goals, and an AI Chief of Staff that knows your business — replacing eight tools and the friction between them.</p>
    <div class="hero-ctas reveal reveal-delay-3">
      <a class="btn-primary" href="mailto:kmjcreativesolution@gmail.com?subject=Get%20Started%20with%20Solutionist">Get Started →</a>
      <a class="btn-secondary" href="#features">See what it does</a>
    </div>
    <div class="reveal reveal-delay-3" style="margin-top:18px;">
      <span class="stat-block">
        <span class="big">8</span>
        <span>tools replaced by one workspace</span>
      </span>
    </div>
    <div class="hero-note reveal reveal-delay-3">Currently in private beta · Email us to request access</div>
  </div>
</section>

<!-- ═══ FEATURES ═══ -->
<section id="features">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">What it does</span>
      <h2>Six surfaces, one workspace.</h2>
      <p>Each tab is its own command center. They share contacts, content, brand, and your Chief — so nothing falls between the cracks.</p>
    </div>
    <div class="features-grid">
      <div class="card feature-card reveal">
        <div class="mini-visual" aria-hidden>
          <div class="mv-orbit">
            <span class="center"></span>
            <span class="moon"></span>
            <span class="moon moon-2"></span>
          </div>
        </div>
        <div class="card-icon">🏠</div>
        <h3>Command Center</h3>
        <p>Daily dashboard: today's schedule, what needs attention, recent activity. Voice-first option — wake your Chief by name.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-1">
        <div class="mini-visual" aria-hidden>
          <div class="mv-stack"><span></span><span></span><span></span></div>
        </div>
        <div class="card-icon">🧱</div>
        <h3>Build</h3>
        <p>Practitioner sites, brand kits, intake forms, integrations. Connect Stripe, Facebook Pages, and the tools you already use.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-2">
        <div class="mini-visual" aria-hidden>
          <div class="mv-grid">
            <span></span><span></span><span></span><span class="live"></span><span></span>
            <span></span><span class="live"></span><span></span><span></span><span></span>
            <span></span><span></span><span></span><span></span><span class="live"></span>
          </div>
        </div>
        <div class="card-icon">⚙️</div>
        <h3>Operate</h3>
        <p>Contacts, invoices, calendar, tasks, email + SMS hubs. The day-to-day plumbing that keeps clients moving forward.</p>
      </div>
      <div class="card feature-card reveal">
        <div class="mini-visual" aria-hidden>
          <div class="mv-bars"><span></span><span></span><span></span><span></span><span></span></div>
        </div>
        <div class="card-icon">📈</div>
        <h3>Grow</h3>
        <p>Revenue analytics, goals across five lenses (Business / Team Building / Personal / Custom), sales funnel, and a content calendar with pillars.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-1">
        <div class="mini-visual" aria-hidden>
          <div class="mv-spark"><span class="core"></span></div>
        </div>
        <div class="card-icon">🤖</div>
        <h3>Chief of Staff</h3>
        <p>An AI that reads your real data every turn. Drafts emails, plans posts, sets goals, sends reports, and gives tactical input on what to push.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-2">
        <div class="mini-visual" aria-hidden>
          <div class="mv-publish">
            <span class="platform fb">f</span>
            <span class="flow"></span>
            <span class="platform ig">📷</span>
          </div>
        </div>
        <div class="card-icon">📣</div>
        <h3>Publish anywhere</h3>
        <p>Connect your Facebook Page and linked Instagram Business account, then publish from the Content tab in one click. Posts and engagement live next to your goals.</p>
      </div>
    </div>
  </div>
</section>

<!-- ═══ AUDIENCE ═══ -->
<section id="audience" class="audience">
  <div class="container">
    <div class="section-head" style="margin-bottom:32px;">
      <span class="eyebrow">Who it's for</span>
      <h2 style="margin-top:14px;">Built for people who serve people.</h2>
    </div>
    <div class="audience-grid">
      <span class="audience-pill"><span class="emoji">⛪</span> Pastors</span>
      <span class="audience-pill"><span class="emoji">🎯</span> Coaches</span>
      <span class="audience-pill"><span class="emoji">💼</span> Consultants</span>
      <span class="audience-pill"><span class="emoji">🎨</span> Creatives</span>
      <span class="audience-pill"><span class="emoji">🧘</span> Practitioners</span>
      <span class="audience-pill"><span class="emoji">🏠</span> Solo Studios</span>
    </div>
  </div>
</section>

<!-- ═══ HOW IT WORKS ═══ -->
<section id="how">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">How it works</span>
      <h2>Three steps to a working practice.</h2>
    </div>
    <div class="how-grid">
      <div class="card step-card">
        <span class="step-num">1</span>
        <h3 style="margin-top:14px;">Sign up</h3>
        <p style="font-size:14px;color:var(--text-muted);">Create your account, set up your business profile, and tell Chief what you do. Onboarding takes about 10 minutes.</p>
      </div>
      <div class="card step-card">
        <span class="step-num">2</span>
        <h3 style="margin-top:14px;">Connect your tools</h3>
        <p style="font-size:14px;color:var(--text-muted);">Plug in Stripe, your Facebook Page, QuickBooks, your bank — whatever you already use. Tokens stay server-side; you control disconnection.</p>
      </div>
      <div class="card step-card">
        <span class="step-num">3</span>
        <h3 style="margin-top:14px;">Run your practice</h3>
        <p style="font-size:14px;color:var(--text-muted);">Use the workspace daily. Track contacts, invoice clients, plan posts, hit goals. Ask Chief for input anytime.</p>
      </div>
    </div>
  </div>
</section>

<!-- ═══ META CALLOUT ═══ -->
<section style="padding:48px 0;">
  <div class="container">
    <div class="meta-callout">
      <div class="platforms">
        <span class="badge-pill">f Facebook</span>
        <span class="badge-pill">📷 Instagram</span>
      </div>
      <h2 style="font-size:28px;">Publish to Facebook + Instagram from one place.</h2>
      <p style="max-width:560px;margin:14px auto 0;color:var(--text-muted);">Connect your Facebook Page once. Draft posts in the Content tab, publish to your Page (and linked Instagram Business account) in one click. Tokens are stored securely on our servers — your browser never sees them, and you can disconnect anytime.</p>
    </div>
  </div>
</section>

<!-- ═══ WHY US ═══ -->
<section>
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Why Solutionist</span>
      <h2>One workspace replacing the chaos of eight.</h2>
    </div>
    <div class="why-grid">
      <div class="card why-card">
        <div class="check">✓</div>
        <div>
          <h3>One brain, not eight</h3>
          <p style="font-size:14px;color:var(--text-muted);">Your CRM, invoicing, calendar, content, and analytics all talk to each other. Update a contact once; every tool sees it.</p>
        </div>
      </div>
      <div class="card why-card">
        <div class="check">✓</div>
        <div>
          <h3>AI that knows your business</h3>
          <p style="font-size:14px;color:var(--text-muted);">Chief reads your real data every turn — not a generic LLM. Asks for context once, then uses it forever.</p>
        </div>
      </div>
      <div class="card why-card">
        <div class="check">✓</div>
        <div>
          <h3>Real-time, not weekly reports</h3>
          <p style="font-size:14px;color:var(--text-muted);">Every metric — revenue, contacts at risk, goals on pace — updates as data changes. No CSV exports, no waiting for someone to refresh.</p>
        </div>
      </div>
      <div class="card why-card">
        <div class="check">✓</div>
        <div>
          <h3>Built for solo, not enterprise</h3>
          <p style="font-size:14px;color:var(--text-muted);">No teams, no seat math, no Slack-integration sprawl. Designed for one operator running their whole practice.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- ═══ COMPARISON ═══ -->
<section id="compare">
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">The alternative</span>
      <h2>One workspace vs. cobbling 8 tools together.</h2>
      <p>What you'd normally pay $200+/month for and lose to context-switching every day.</p>
    </div>
    <div class="reveal reveal-delay-1">
      <table class="compare">
        <thead>
          <tr>
            <th>What you need</th>
            <th class="sol-col">Solutionist</th>
            <th>The 8-tool stack</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>CRM &amp; contacts</td><td class="sol">✓ Built-in</td><td class="alt">HubSpot / Notion / spreadsheet</td></tr>
          <tr><td>Invoicing &amp; payments</td><td class="sol">✓ Built-in</td><td class="alt">Stripe + QuickBooks</td></tr>
          <tr><td>Calendar &amp; booking</td><td class="sol">✓ Built-in</td><td class="alt">Calendly + Google Calendar</td></tr>
          <tr><td>Content planning &amp; publishing</td><td class="sol">✓ Built-in</td><td class="alt">Buffer / Hootsuite + Notion</td></tr>
          <tr><td>Goals &amp; tracking</td><td class="sol">✓ Built-in</td><td class="alt">Spreadsheet + sticky notes</td></tr>
          <tr><td>Funnel &amp; pipeline analytics</td><td class="sol">✓ Built-in</td><td class="alt">Mixpanel / Looker / DIY</td></tr>
          <tr><td>Website &amp; brand</td><td class="sol">✓ Built-in</td><td class="alt">Squarespace / Webflow + Figma</td></tr>
          <tr><td>AI assistant that knows your business</td><td class="sol">✓ Chief of Staff</td><td class="alt">ChatGPT + manual context every time</td></tr>
        </tbody>
      </table>
      <div class="compare-foot">Every tool above also needs its own login, billing, sync setup, and prayers that it talks to the others.</div>
    </div>
  </div>
</section>

<!-- ═══ EVERYTHING INCLUDED ═══ -->
<section id="included">
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Everything in the workspace</span>
      <h2>Yes, all of this is built in.</h2>
      <p>No add-ons, no premium tier hiding the basics, no upsells. The whole product is the whole product.</p>
    </div>
    <div class="included-grid">
      <div class="included-cat reveal">
        <h3>🏠 Command Center</h3>
        <ul>
          <li>Daily dashboard</li><li>Voice-first Chief</li><li>Command palette</li>
          <li>Wake-word listening</li><li>Activity feed</li><li>Smart notifications</li>
        </ul>
      </div>
      <div class="included-cat reveal reveal-delay-1">
        <h3>🧱 Build</h3>
        <ul>
          <li>Practitioner sites</li><li>Brand kits</li><li>Intake forms</li><li>Custom modules</li>
          <li>Print materials</li><li>Booking page</li><li>Link page</li><li>Email templates</li>
          <li>Products &amp; services</li><li>Integrations hub</li>
        </ul>
      </div>
      <div class="included-cat reveal">
        <h3>⚙️ Operate</h3>
        <ul>
          <li>Contacts (CRM)</li><li>Invoices &amp; payments</li><li>Calendar</li><li>Tasks</li>
          <li>Email hub</li><li>SMS hub</li><li>Projects</li><li>Documents</li><li>Autopilot agents</li>
        </ul>
      </div>
      <div class="included-cat reveal reveal-delay-1">
        <h3>📈 Grow</h3>
        <ul>
          <li>Revenue analytics</li><li>Revenue Allocator</li><li>Expense tracking</li>
          <li>Goals (5 lenses)</li><li>Goal reminders</li><li>Funnel analytics</li>
          <li>Drop-off insights</li><li>Lost-reason logging</li><li>Content calendar</li>
          <li>Content pillars</li><li>Idea inbox</li><li>Engagement tracking</li>
          <li>Weekly briefing</li><li>Insights feed</li>
        </ul>
      </div>
      <div class="included-cat reveal">
        <h3>🤖 Chief of Staff (AI)</h3>
        <ul>
          <li>Voice mode</li><li>Memory + standing instructions</li>
          <li>Action delegation</li><li>Goal coaching</li><li>Content drafting</li>
          <li>Direct publishing</li><li>Report generation</li><li>Insight + tactical input</li>
        </ul>
      </div>
      <div class="included-cat reveal reveal-delay-1">
        <h3>🔌 Connections</h3>
        <ul>
          <li>Stripe</li><li>Square</li><li>PayPal</li><li>Facebook Pages</li>
          <li>Instagram Business</li><li>Resend (email)</li><li>Supabase Storage</li>
          <li>More coming</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<!-- ═══ FAQ ═══ -->
<section id="faq">
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Common questions</span>
      <h2>Answers to what people ask first.</h2>
    </div>
    <div class="faq-list reveal reveal-delay-1" style="max-width:780px;margin:0 auto;">
      <details class="faq-item">
        <summary>Who is this actually for?</summary>
        <div class="faq-body">
          <p>Solo practitioners and small studios. The people we built it for: pastors, coaches, consultants, creatives, agencies-of-one, and small service businesses. If you run your whole show — sales, delivery, marketing, finances — Solutionist is for you. If you have a 20-person team with a dedicated ops person, it's overkill.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>Do I need a team to use this?</summary>
        <div class="faq-body">
          <p>No. The whole product assumes one operator. No seat math, no "add a teammate" friction, no admin role management. If you grow to a team later, the data model supports it — but it's not the default.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>What about pricing?</summary>
        <div class="faq-body">
          <p>We're in private beta right now. Pricing is coming when we open public access. Email us — if you're a fit, we'll get you in early and grandfather you on whatever pricing launches.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>How is this different from Notion, HubSpot, or just using ChatGPT?</summary>
        <div class="faq-body">
          <p><strong>Notion</strong> is a blank canvas — you'd build all this yourself, and it doesn't have an AI that knows your actual business data.</p>
          <p><strong>HubSpot</strong> is enterprise CRM with a steep learning curve, sales-team assumptions, and pricing that doesn't fit a solo practice.</p>
          <p><strong>ChatGPT</strong> is generic — you have to re-explain your business every time. Chief reads your real contacts, invoices, goals, content, and brand on every turn.</p>
          <p>Solutionist is purpose-built for solo operators with AI woven through every surface.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>Does the AI replace my judgment?</summary>
        <div class="faq-body">
          <p>No. Chief drafts, suggests, and assists — it never sends without you approving (except for explicit actions you ask it to take, like "send this email" or "publish this post"). It's an instrument, not a replacement.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>What about my existing tools — do I have to move everything?</summary>
        <div class="faq-body">
          <p>No. Connect what you want (Stripe for payments, Facebook for publishing, Resend for email). The rest stays. Solutionist is opinionated about workflow but not greedy — you can keep Calendly or your existing email tool and Solutionist will work around it.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>How secure is my data?</summary>
        <div class="faq-body">
          <p>Connected social account tokens and other credentials are stored server-side only — your browser never sees them. We use Supabase for data storage and Railway for hosting. You can disconnect any integration immediately from the app, which deletes the stored token. Full details in the <a href="/privacy">Privacy Policy</a>.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>When can I sign up?</summary>
        <div class="faq-body">
          <p>Now — email us at <a href="mailto:kmjcreativesolution@gmail.com">kmjcreativesolution@gmail.com</a> with a few sentences about your practice. If we're a fit, we'll onboard you within a few days.</p>
        </div>
      </details>
    </div>
  </div>
</section>

<!-- ═══ FOUNDER NOTE ═══ -->
<section id="founder" style="padding:64px 0;">
  <div class="container" style="max-width:820px;">
    <div class="section-head reveal" style="margin-bottom:32px;">
      <span class="eyebrow">From the founder</span>
    </div>
    <div class="founder reveal reveal-delay-1">
      <div class="founder-avatar">KM</div>
      <div class="founder-body">
        <p>I built the Solutionist System because I was tired of running my own business across eight tools that didn't talk to each other.</p>
        <p>Every solo operator I know lives in the same chaos: Notion for notes, Stripe for invoices, Calendly for booking, Buffer for content, a spreadsheet for goals, a CRM nobody actually uses. The friction between tools eats more time than the actual work.</p>
        <p>So we built one workspace where everything lives together — with an AI Chief of Staff that actually knows your business, not generic prompts. We're growing it carefully in private beta. If you're a coach, pastor, consultant, or solo studio, I'd love to talk.</p>
        <div class="founder-sig">
          Kevin McCloud Jr.
          <span class="small">Founder &middot; The Solutionist System LLC</span>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- ═══ FINAL CTA ═══ -->
<section class="final-cta">
  <div class="container">
    <span class="eyebrow">Ready when you are</span>
    <h2 style="margin-top:14px;">Run your practice from one place.</h2>
    <p>Currently in private beta. Email us — we'll set you up with access and walk you through onboarding.</p>
    <a class="btn-primary" href="mailto:kmjcreativesolution@gmail.com?subject=Get%20Started%20with%20Solutionist">Email us to get started →</a>
  </div>
</section>

<!-- ═══ FOOTER ═══ -->
<footer>
  <div class="footer-inner">
    <div class="footer-brand">
      <span class="brand"><span class="dot"></span>The Solutionist System</span>
      <span class="small">Built by The Solutionist System LLC · Michigan, USA</span>
    </div>
    <div class="footer-links">
      <a href="/help">Help</a>
      <a href="/privacy">Privacy</a>
      <a href="/data-deletion">Data Deletion</a>
      <a href="/terms">Terms</a>
      <a href="mailto:kmjcreativesolution@gmail.com">Contact</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>&copy; 2026 The Solutionist System LLC</span>
    <span>mysolutionist.app</span>
  </div>
</footer>

<script>
  // Scroll-reveal: add .visible to .reveal elements as they enter view.
  // Pure vanilla JS, no dependencies. Respects prefers-reduced-motion —
  // when reduced motion is on, just reveal everything immediately.
  (function() {
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var els = document.querySelectorAll('.reveal');
    if (reduced || !('IntersectionObserver' in window)) {
      // Show everything without animation
      for (var i = 0; i < els.length; i++) els[i].classList.add('visible');
      return;
    }
    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    for (var j = 0; j < els.length; j++) io.observe(els[j]);

    // Smooth-scroll anchor links
    document.querySelectorAll('a[href^="#"]').forEach(function(a) {
      a.addEventListener('click', function(e) {
        var id = a.getAttribute('href').slice(1);
        if (!id) return;
        var target = document.getElementById(id);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
        }
      });
    });
  })();
</script>

</body>
</html>"""


async def _augment_html(client: httpx.AsyncClient, biz_id: Optional[str], slug: str, html: str,
                        custom_domain: Optional[str] = None,
                        page_path: str = "") -> str:
    """Inject canonical + live products + gallery into served HTML.

    `custom_domain` (2026-08-02): this function used to call
    _inject_canonical(html, slug) — dropping the argument the helper
    already accepted. Every custom-domain page therefore declared the
    platform subdomain as its canonical, handing the ranking value of
    the domain the practitioner PAID FOR to a subdomain they don't own.
    """
    products: List[Dict[str, Any]] = []
    gallery: List[Dict[str, Any]] = []
    brand_color = "#D4AF37"
    biz_settings: Dict[str, Any] = {}
    if biz_id:
        prod_rows, biz_rows = await asyncio.gather(
            _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100"),
            _sb(client, f"/businesses?id=eq.{biz_id}&select=settings&limit=1"),
        )
        products = prod_rows or []
        if biz_rows:
            biz_settings = (biz_rows[0].get("settings") or {})
            lib = biz_settings.get("media_library") or {}
            gallery = lib.get("gallery") or []
            bk = biz_settings.get("brand_kit") or {}
            bc = (bk.get("primary_color") or "").strip() if isinstance(bk, dict) else ""
            if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                brand_color = bc
    html = _inject_canonical(html, slug, custom_domain, page_path)
    # Pass 3: activate the Pass 2.5a `_brand_head_meta_tags` helper for
    # legacy sites too — favicons + OG + Twitter Cards now render for
    # everyone, not just Smart Sites users.
    html = _inject_brand_meta(html, biz_id)
    html = _inject_dynamic_sections(
        html,
        _render_products_section(products, slug, brand_color, biz_settings),
        _render_gallery_section(gallery),
    )
    # LAST — after every section that could add an <img> (products and
    # gallery are injected above), so nothing escapes the rewrite.
    html = _optimize_images(html)
    return html


async def _try_render_smart_site(business_id: str, page_type: str, **opts) -> Optional[str]:
    """Pass 3: attempt Smart Sites render. Returns HTML on success, None on
    any failure so the caller can fall through to legacy. NEVER raises."""
    try:
        from smart_sites import render_smart_site_page
        return render_smart_site_page(business_id, page_type, **opts)
    except Exception as e:
        logger.warning(f"[smart_sites] render failed for {business_id} {page_type}: {e}")
        return None


# Phase D.2.1 — embed origin used by the SSR booking page. Defaults to
# the production Railway URL; an env override lets local/dev environments
# point the rendered <script> at a different host.
_EMBED_ORIGIN = os.environ.get(
    "EMBED_ORIGIN",
    "https://kmj-intake-server-production.up.railway.app",
)


async def _serve_store_page(slug: str) -> HTMLResponse:
    """Serve the hosted store at /store on the site's OWN domain.

    2026-08-13 (post-audit gap list): the store CTA composed onto a site
    pointed at {RAILWAY_BASE}/public/store/{slug}/page — so a visitor on
    the custom domain the practitioner pays for was walked onto a
    railway.app URL at the exact moment they decided to buy. /book,
    /give and /events had all been given the always-wins treatment on
    the site's own domain; the store never was.

    The renderer is unchanged — this is a route in front of it, so both
    addresses serve the same page and old links keep working.
    """
    from store_router import hosted_store_page
    # hosted_store_page is sync (blocking PostgREST reads); keep it off
    # the event loop the way every other blocking render here does.
    return await asyncio.to_thread(hosted_store_page, slug)


async def _serve_booking_page(client, biz_id: Optional[str], slug: str) -> HTMLResponse:
    """Phase D.2.1 — render the hosted booking page at
    https://<slug>.mysolutionist.app/book.

    Reads business + settings.booking_page; if published=True renders
    the full SSR page (logo + name + tagline + widget + footer), if
    not returns a 404-status "not published yet" page (still
    brand-applied).

    The renderer is in booking_page_renderer.py — keeps this routing
    function tight + makes the HTML easy to unit-test."""
    if not biz_id:
        raise HTTPException(404, "business not found")
    # Service-role read: anon RLS on businesses blocks public reads,
    # but the booking-page render is an inherently public surface (the
    # practitioner is sharing this URL with customers). Scoped to one
    # id, returning only render-needed columns.
    biz_rows = await _sb_service(
        client,
        f"/businesses?id=eq.{biz_id}&select=id,name,settings&limit=1",
    )
    if not biz_rows:
        raise HTTPException(404, "business not found")
    business = biz_rows[0]
    settings = business.get("settings") or {}
    page = settings.get("booking_page") or {}

    canonical = f"https://{slug}.mysolutionist.app/book"

    # Late import — avoid circular at module load
    from booking_page_renderer import (
        render_booking_page,
        render_not_published_page,
    )

    if not page.get("published"):
        html = render_not_published_page(business, canonical)
        return HTMLResponse(
            content=html, status_code=404, media_type="text/html",
            headers={**_PUBLIC_SITE_NO_STORE_HEADERS},
        )

    html = render_booking_page(business, canonical, embed_origin=_EMBED_ORIGIN)
    return HTMLResponse(
        content=html, media_type="text/html",
        headers={**_PUBLIC_SITE_NO_STORE_HEADERS},
    )


async def _serve_give_page(client, biz_id: Optional[str], slug: str) -> HTMLResponse:
    """Online giving — render the public give page at
    https://<slug>.mysolutionist.app/give (mirrors _serve_booking_page).

    Gated hard: only a nonprofit-family business (vertical_family
    .is_nonprofit_like) with settings.giving.enabled AND a connected
    Stripe account gets the live page; everyone else gets a branded
    404-status "not available" page. The renderer lives in
    giving_router.py — pure + unit-tested, same split as
    booking_page_renderer."""
    if not biz_id:
        raise HTTPException(404, "business not found")
    biz_rows = await _sb_service(
        client,
        f"/businesses?id=eq.{biz_id}"
        f"&select=id,name,type,settings,stripe_account_id&limit=1",
    )
    if not biz_rows:
        raise HTTPException(404, "business not found")
    business = biz_rows[0]
    canonical = f"https://{slug}.mysolutionist.app/give"

    from giving_router import (
        giving_is_active,
        render_give_page,
        render_giving_unavailable_page,
    )

    if not giving_is_active(business):
        html = render_giving_unavailable_page(business, canonical)
        return HTMLResponse(
            content=html, status_code=404, media_type="text/html",
            headers={**_PUBLIC_SITE_NO_STORE_HEADERS},
        )

    html = render_give_page(business, canonical, slug, api_origin=_EMBED_ORIGIN)
    return HTMLResponse(
        content=html, media_type="text/html",
        headers={**_PUBLIC_SITE_NO_STORE_HEADERS},
    )


async def _serve_events_page(client, biz_id: Optional[str], slug: str) -> HTMLResponse:
    """Public event RSVP — render the events page at
    https://<slug>.mysolutionist.app/events (mirrors _serve_give_page).

    Gated: settings.events_public.enabled AND at least one active
    event_roster module (any vertical — see events_rsvp_router's gate
    ruling); everyone else gets a branded 404-status page. The renderer
    + occasion math live in events_rsvp_router.py — pure + unit-tested,
    same split as giving_router."""
    if not biz_id:
        raise HTTPException(404, "business not found")
    biz_rows = await _sb_service(
        client,
        f"/businesses?id=eq.{biz_id}"
        f"&select=id,name,type,settings&limit=1",
    )
    if not biz_rows:
        raise HTTPException(404, "business not found")
    business = biz_rows[0]
    canonical = f"https://{slug}.mysolutionist.app/events"

    from events_rsvp_router import (
        MAX_ENTRIES_PER_MODULE,
        build_occasions,
        events_public_is_active,
        render_events_page,
        render_events_unavailable_page,
    )

    modules = await _sb_service(
        client,
        f"/custom_modules?business_id=eq.{biz_id}"
        f"&archetype=eq.event_roster&is_active=eq.true"
        f"&select=id,name,archetype_params&limit=50",
    ) or []

    if not events_public_is_active(business, modules):
        html = render_events_unavailable_page(business, canonical)
        return HTMLResponse(
            content=html, status_code=404, media_type="text/html",
            headers={**_PUBLIC_SITE_NO_STORE_HEADERS},
        )

    entries_by_module = {}
    for mod in modules:
        rows = await _sb_service(
            client,
            f"/module_entries?module_id=eq.{mod['id']}&status=eq.active"
            f"&select=id,module_id,data&limit={MAX_ENTRIES_PER_MODULE}",
        ) or []
        entries_by_module[str(mod["id"])] = rows

    occasions = build_occasions(modules, entries_by_module)
    html = render_events_page(business, occasions, canonical, slug,
                              api_origin=_EMBED_ORIGIN)
    return HTMLResponse(
        content=html, media_type="text/html",
        headers={**_PUBLIC_SITE_NO_STORE_HEADERS},
    )


async def _render_offline_page(client: httpx.AsyncClient,
                               biz_id: Optional[str]) -> HTMLResponse:
    """A calm, branded 'temporarily offline' page shown while the practitioner
    has taken their public site down to work on it. Returns 503 so search
    engines treat it as temporary and don't de-index the site.

    Name + accent come from the business row (businesses.name +
    settings.brand_kit.primary_color) — site_config never carried those keys.
    Fail-open to neutral defaults; this page must never itself error."""
    import html as _html
    name, accent = "This site", "#D4AF37"
    try:
        if biz_id:
            rows = await _sb(client,
                f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1") or []
            if rows:
                name = (rows[0].get("name") or "").strip() or name
                bk = (rows[0].get("settings") or {}).get("brand_kit") or {}
                bc = (bk.get("primary_color") or "").strip() if isinstance(bk, dict) else ""
                if bc.startswith("#") and len(bc) in (4, 7):
                    # Expand #abc → #aabbcc so the 8-digit alpha suffix used in
                    # the pulse keyframes ({accent}66) stays a valid color.
                    accent = ("#" + "".join(c * 2 for c in bc[1:])) if len(bc) == 4 else bc
    except Exception:
        pass
    name = _html.escape(name)
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>{name} — back soon</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:#0f1115; color:#e9ecf1; padding:24px; text-align:center; }}
  @media (prefers-color-scheme: light) {{ body {{ background:#f7f7f5; color:#1a1c20; }} }}
  .wrap {{ max-width:460px; }}
  .dot {{ width:10px; height:10px; border-radius:50%; background:{accent};
    display:inline-block; margin-bottom:24px; box-shadow:0 0 0 0 {accent};
    animation:pulse 2.4s ease-out infinite; }}
  @keyframes pulse {{ 0%{{box-shadow:0 0 0 0 {accent}66;}} 70%{{box-shadow:0 0 0 16px {accent}00;}}
    100%{{box-shadow:0 0 0 0 {accent}00;}} }}
  h1 {{ font-size:1.6rem; font-weight:650; margin:0 0 12px; letter-spacing:-0.01em; }}
  p {{ font-size:1rem; line-height:1.6; opacity:0.72; margin:0; }}
  @media (prefers-reduced-motion: reduce) {{ .dot {{ animation:none; }} }}
</style></head>
<body><div class="wrap">
  <span class="dot"></span>
  <h1>We'll be right back</h1>
  <p>{name} is making a few updates. Please check back in a little while.</p>
</div></body></html>"""
    return HTMLResponse(content=html, status_code=503, media_type="text/html",
                        headers={**_PUBLIC_SITE_NO_STORE_HEADERS})


# ═══ Academy Phase 4 — public course pages ═══════════════════════════
# /academy (catalog) + /academy/<course_id> (landing page w/ buy link)
# on any business site — AND optionally standalone: site_config.
# academy_slug claims a dedicated subdomain, site_config.academy_domain
# a dedicated custom domain, where the academy IS the site root. One
# business, two storefronts (e.g. consulting + education).


def _academy_valid_id(cid: str) -> bool:
    return 32 <= len(cid) <= 40 and all(c in "0123456789abcdefABCDEF-" for c in cid)


def _academy_hrefs(standalone: bool):
    """URL scheme per mode: embedded rides /academy/*; standalone owns
    the root (catalog at /, courses at /course/<id>)."""
    if standalone:
        return "/", (lambda cid: f"/course/{cid}")
    return "/academy", (lambda cid: f"/academy/{cid}")


def _academy_parse(path: str, standalone: bool):
    """→ ('catalog', None) | ('course', id) | (None, None) for a 404."""
    p = (path or "/").rstrip("/") or "/"
    if standalone:
        if p == "/" or p == "/academy":
            return "catalog", None
        for prefix in ("/course/", "/academy/"):
            if p.startswith(prefix):
                cid = p[len(prefix):]
                if _academy_valid_id(cid):
                    return "course", cid
        return None, None
    if p == "/academy":
        return "catalog", None
    if p.startswith("/academy/"):
        cid = p[len("/academy/"):]
        if _academy_valid_id(cid):
            return "course", cid
    return None, None


def _academy_fmt_runtime(minutes: int) -> str:
    if minutes <= 0:
        return ""
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


_ACADEMY_CSS = """
  * { box-sizing: border-box; margin: 0; }
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #faf9f6; color: #1d1b16; line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }
  @media (prefers-color-scheme: dark) {
    body { background: #12121a; color: #eceaf2; }
    .card, .lesson { background: #1a1a26 !important; border-color: rgba(255,255,255,0.09) !important; }
    .muted { color: #9a97a8 !important; }
    .price-box { background: #1a1a26 !important; border-color: rgba(255,255,255,0.09) !important; }
  }
  .wrap { max-width: 780px; margin: 0 auto; padding: 40px 22px 80px; }
  .eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 10px; }
  h1 { font-size: clamp(26px, 5vw, 38px); line-height: 1.15; letter-spacing: -0.01em; margin-bottom: 12px; }
  .muted { color: #6d6a60; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; margin-top: 28px; }
  .card {
    display: block; text-decoration: none; color: inherit;
    background: #fff; border: 1px solid rgba(29,27,22,0.10); border-radius: 16px;
    padding: 20px; transition: transform .15s ease, box-shadow .15s ease;
  }
  .card:hover { transform: translateY(-3px); box-shadow: 0 14px 40px rgba(0,0,0,0.10); }
  .card h2 { font-size: 17px; margin-bottom: 6px; line-height: 1.3; }
  .card p { font-size: 13px; margin-bottom: 12px; }
  .meta { font-size: 11.5px; display: flex; gap: 10px; flex-wrap: wrap; }
  .pill { display: inline-block; font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px; }
  .lessons { margin-top: 26px; display: flex; flex-direction: column; gap: 8px; }
  .lesson {
    display: flex; align-items: center; gap: 12px;
    background: #fff; border: 1px solid rgba(29,27,22,0.10); border-radius: 12px;
    padding: 12px 16px; font-size: 14px;
  }
  .lesson .n { font-weight: 700; opacity: .45; width: 22px; text-align: center; flex-shrink: 0; }
  .lesson .t { flex: 1; min-width: 0; }
  .lesson .d { font-size: 11.5px; flex-shrink: 0; }
  .btn {
    display: inline-block; padding: 14px 30px; border-radius: 12px;
    font-weight: 700; font-size: 15px; text-decoration: none; color: #fff;
    text-align: center;
  }
  .price-box {
    margin-top: 30px; padding: 22px; border-radius: 16px;
    background: #fff; border: 1px solid rgba(29,27,22,0.10);
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
  }
  .price { font-size: 30px; font-weight: 800; letter-spacing: -0.01em; }
  .back { font-size: 13px; text-decoration: none; font-weight: 600; }
  .foot { margin-top: 54px; font-size: 11.5px; text-align: center; }
"""


async def _academy_brand(client, biz_id) -> tuple:
    """(business_name, accent, theme) — service-role reads. accent comes
    from the brand kit unless the practitioner overrode it in the
    academy appearance settings (site_config.academy_theme: {headline,
    intro, accent, mode:'auto'|'light'|'dark'})."""
    name, accent = "The Academy", "#B4762A"
    theme: Dict[str, Any] = {}
    try:
        rows = await _sb_service(
            client, f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1") or []
        if rows:
            name = (rows[0].get("name") or "").strip() or name
            bk = (rows[0].get("settings") or {}).get("brand_kit") or {}
            bc = (bk.get("primary_color") or "").strip() if isinstance(bk, dict) else ""
            if bc.startswith("#") and len(bc) in (4, 7):
                accent = bc
    except Exception:
        pass
    site_config: Dict[str, Any] = {}
    try:
        srows = await _sb_service(
            client,
            f"/business_sites?business_id=eq.{biz_id}"
            f"&order=updated_at.desc&limit=1&select=site_config") or []
        if srows:
            site_config = srows[0].get("site_config") or {}
            t = site_config.get("academy_theme") or {}
            if isinstance(t, dict):
                theme = t
                ta = (t.get("accent") or "").strip()
                if ta.startswith("#") and len(ta) in (4, 7):
                    accent = ta
    except Exception:
        pass
    return name, accent, theme, site_config


def _academy_skin(biz_id, site_config: Dict[str, Any], theme: Dict[str, Any],
                  fallback_accent: str) -> tuple:
    """'Same generator as the main site' (Kevin's ruling): reconstruct
    the composed site's DesignSystem from stored config — zero LLM
    (resolve_layout_and_vocabulary is deterministic DB reads + pure
    functions) — and bridge its tokens onto the academy stylesheet:
    real display/body fonts (with the Google Fonts link), the site's
    palette, surface treatment, and the AI decoration scheme when one
    exists. Fail-open: ANY hiccup returns the base look untouched.
    Returns (accent, head_extra_html)."""
    try:
        from smart_sites import resolve_layout_and_vocabulary
        from studio_layouts.shared import (
            apply_scheme_to_design_system, render_decoration_head)
        (_lid, _vocab, _comp, ds, _bd, _bp, _dm) = resolve_layout_and_vocabulary(
            str(biz_id), site_config or {})
        if not ds:
            return fallback_accent, ""
        scheme = (site_config or {}).get("generated_decoration")
        if scheme:
            try:
                ds = apply_scheme_to_design_system(ds, scheme)
            except Exception:
                pass
        accent = ((theme or {}).get("accent") or "").strip() \
            or (ds.get("palette_accent") or "").strip() or fallback_accent
        if not accent.startswith("#"):
            accent = fallback_accent
        fonts_link = ""
        if ds.get("google_fonts_url"):
            fonts_link = (f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                          f'<link rel="stylesheet" href="{_esc(ds["google_fonts_url"])}">')
        deco = ""
        if scheme:
            try:
                deco = render_decoration_head(ds, scheme) or ""
            except Exception:
                deco = ""
        css = f"""
  body {{ background: {ds['palette_bg']} !important; color: {ds['palette_text']} !important; font-family: {ds['font_body']}; }}
  h1, h2, .eyebrow, .price {{ font-family: {ds['font_display']}; }}
  .card, .lesson, .price-box, .hw {{ background: {ds['palette_surface']} !important; border-color: color-mix(in srgb, {ds['palette_text']} 14%, transparent) !important; }}
  .muted {{ color: {ds['palette_muted']} !important; }}
  .check {{ border-color: color-mix(in srgb, {ds['palette_text']} 35%, transparent); }}
"""
        return accent, fonts_link + "<style>" + css + "</style>" + deco
    except Exception as e:
        logger.warning(f"academy skin resolve failed (base look): {e}")
        return fallback_accent, ""


def _academy_mode_css(theme: Dict[str, Any]) -> str:
    """Forced light/dark override (mode 'auto' returns nothing — the
    prefers-color-scheme block in _ACADEMY_CSS handles it)."""
    mode = (theme or {}).get("mode")
    if mode == "dark":
        return """
  body { background: #12121a !important; color: #eceaf2 !important; }
  .card, .lesson, .price-box { background: #1a1a26 !important; border-color: rgba(255,255,255,0.09) !important; }
  .muted { color: #9a97a8 !important; }"""
    if mode == "light":
        return """
  body { background: #faf9f6 !important; color: #1d1b16 !important; }
  .card, .lesson, .price-box { background: #fff !important; border-color: rgba(29,27,22,0.10) !important; }
  .muted { color: #6d6a60 !important; }"""
    return ""


async def _serve_academy(client, biz_id, path: str, standalone: bool,
                         main_slug: str = "") -> HTMLResponse:
    """Render the academy catalog or a course landing page."""
    kind, course_id = _academy_parse(path, standalone)
    catalog_href, course_href = _academy_hrefs(standalone)
    biz_name, accent, theme, site_config = await _academy_brand(client, biz_id)
    accent, skin_head = _academy_skin(biz_id, site_config, theme, accent)
    mode_css = _academy_mode_css(theme)
    safe_biz = _esc(biz_name)
    main_href = "/" if not standalone else (
        f"https://{main_slug}.mysolutionist.app" if main_slug else "")

    if kind == "course" and course_id:
        crows = await _sb_service(
            client,
            f"/academy_courses?id=eq.{course_id}&business_id=eq.{biz_id}"
            f"&status=eq.published&limit=1"
            f"&select=id,title,description,drip_mode,product_id") or []
        if crows:
            course = crows[0]
            lessons = await _sb_service(
                client,
                f"/academy_lessons?course_id=eq.{course_id}"
                f"&order=sort_order.asc&limit=60"
                f"&select=title,duration_minutes,lesson_type") or []
            price_html = ""
            product_id = course.get("product_id")
            if product_id:
                prows = await _sb_service(
                    client,
                    f"/products?id=eq.{product_id}&limit=1"
                    f"&select=price,stripe_payment_url") or []
                if prows and (prows[0].get("stripe_payment_url") or "").strip():
                    price_val = prows[0].get("price")
                    price_str = f"${int(round(float(price_val))):,}" if price_val else ""
                    price_html = f"""
  <div class="price-box">
    <div>
      <div class="price">{_esc(price_str)}</div>
      <div class="muted" style="font-size:12px">one-time &middot; instant access</div>
    </div>
    <a class="btn" style="background:{accent}" href="{_esc(prows[0]['stripe_payment_url'])}"
       target="_blank" rel="noopener">Enroll now</a>
  </div>"""
            if not price_html:
                contact_href = main_href or catalog_href
                price_html = f"""
  <div class="price-box">
    <div class="muted" style="font-size:13.5px">Enrollment is personal &mdash; reach out and {safe_biz} will get you started.</div>
    <a class="btn" style="background:{accent}" href="{_esc(contact_href)}">Get in touch</a>
  </div>"""
            total_min = sum(int(l.get("duration_minutes") or 0) for l in lessons)
            runtime = _academy_fmt_runtime(total_min)
            drip = course.get("drip_mode") or "none"
            drip_note = (
                "New material unlocks each week after you join." if drip == "weekly"
                else "Material unlocks on a guided schedule after you join." if drip == "custom"
                else "Everything is available the moment you join.")
            lesson_rows = "".join(
                f'<div class="lesson"><span class="n">{i + 1}</span>'
                f'<span class="t">{_esc(l.get("title") or "Lesson")}</span>'
                f'<span class="d muted">{_esc(_academy_fmt_runtime(int(l.get("duration_minutes") or 0)))}</span></div>'
                for i, l in enumerate(lessons))
            html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(course.get("title") or "Course")} &mdash; {safe_biz}</title>
<style>{_ACADEMY_CSS}</style>{skin_head}<style>{mode_css}</style></head>
<body><div class="wrap">
  <a class="back" style="color:{accent}" href="{_esc(catalog_href)}">&larr; All courses</a>
  <div style="height:26px"></div>
  <div class="eyebrow" style="color:{accent}">{safe_biz} &middot; Academy</div>
  <h1>{_esc(course.get("title") or "Course")}</h1>
  <p class="muted" style="font-size:15.5px;max-width:600px">{_esc(course.get("description") or "")}</p>
  <div class="meta muted" style="margin-top:14px">
    <span>{len(lessons)} lesson{"s" if len(lessons) != 1 else ""}</span>
    {f'<span>&middot; {_esc(runtime)}</span>' if runtime else ''}
    <span>&middot; {_esc(drip_note)}</span>
  </div>
  {price_html}
  <div class="lessons">{lesson_rows}</div>
  <div class="foot muted">Powered by The Solutionist System</div>
</div></body></html>"""
            html = _inject_brand_meta(html, biz_id)
            return HTMLResponse(content=html, media_type="text/html",
                                headers={**_PUBLIC_SITE_NO_STORE_HEADERS})
        kind = None  # course missing/unpublished → styled 404 below

    if kind == "catalog":
        courses = await _sb_service(
            client,
            f"/academy_courses?business_id=eq.{biz_id}&status=eq.published"
            f"&order=created_at.desc&limit=50"
            f"&select=id,title,description,product_id") or []
        lesson_stats: Dict[str, Dict[str, int]] = {}
        price_by_product: Dict[str, str] = {}
        if courses:
            ids = ",".join(c["id"] for c in courses)
            lrows = await _sb_service(
                client,
                f"/academy_lessons?course_id=in.({ids})"
                f"&select=course_id,duration_minutes&limit=1000") or []
            for l in lrows:
                s = lesson_stats.setdefault(l["course_id"], {"n": 0, "min": 0})
                s["n"] += 1
                s["min"] += int(l.get("duration_minutes") or 0)
            pids = [c.get("product_id") for c in courses if c.get("product_id")]
            if pids:
                prows = await _sb_service(
                    client,
                    f"/products?id=in.({','.join(pids)})&select=id,price,stripe_payment_url") or []
                for p in prows:
                    if (p.get("stripe_payment_url") or "").strip() and p.get("price"):
                        price_by_product[p["id"]] = f"${int(round(float(p['price']))):,}"
        cards = ""
        for c in courses:
            s = lesson_stats.get(c["id"], {"n": 0, "min": 0})
            runtime = _academy_fmt_runtime(s["min"])
            price = price_by_product.get(c.get("product_id") or "")
            price_pill = (
                f'<span class="pill" style="background:{accent}1a;color:{accent}">{_esc(price)}</span>'
                if price else "")
            cards += f"""
  <a class="card" href="{_esc(course_href(c["id"]))}">
    <h2>{_esc(c.get("title") or "Course")}</h2>
    <p class="muted">{_esc((c.get("description") or "")[:160])}</p>
    <div class="meta muted">
      <span>{s["n"]} lesson{"s" if s["n"] != 1 else ""}</span>
      {f'<span>&middot; {_esc(runtime)}</span>' if runtime else ''}
      <span style="margin-left:auto">{price_pill}</span>
    </div>
  </a>"""
        empty = "" if courses else (
            '<p class="muted" style="margin-top:30px">New courses are on the way &mdash; check back soon.</p>')
        main_link = (
            f'<a class="back" style="color:{accent}" href="{_esc(main_href)}">&larr; {safe_biz}</a>'
            if main_href else "")
        catalog_h1 = _esc((theme.get("headline") or "").strip() or "The Academy")
        default_intro = ("Courses taught by " + biz_name
                         + " — learn at your own pace, with real accountability.")
        catalog_intro = _esc((theme.get("intro") or "").strip() or default_intro)
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Academy &mdash; {safe_biz}</title>
<style>{_ACADEMY_CSS}</style>{skin_head}<style>{mode_css}</style></head>
<body><div class="wrap">
  {main_link}
  <div style="height:26px"></div>
  <div class="eyebrow" style="color:{accent}">{safe_biz}</div>
  <h1>{catalog_h1}</h1>
  <p class="muted" style="font-size:15.5px;max-width:560px">{catalog_intro}</p>
  <div class="cards">{cards}</div>
  {empty}
  <div class="foot muted">Powered by The Solutionist System</div>
</div></body></html>"""
        html = _inject_brand_meta(html, biz_id)
        return HTMLResponse(content=html, media_type="text/html",
                            headers={**_PUBLIC_SITE_NO_STORE_HEADERS})

    # Unknown academy path — a small branded 404 that offers the catalog.
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Not found &mdash; {safe_biz}</title>
<style>{_ACADEMY_CSS}</style>{skin_head}<style>{mode_css}</style></head>
<body><div class="wrap" style="text-align:center;padding-top:90px">
  <div class="eyebrow" style="color:{accent}">{safe_biz} &middot; Academy</div>
  <h1>That page isn't here</h1>
  <p class="muted">The course may have been unpublished or the link mistyped.</p>
  <div style="height:22px"></div>
  <a class="btn" style="background:{accent}" href="{_esc(catalog_href)}">See all courses</a>
</div></body></html>"""
    return HTMLResponse(content=html, status_code=404, media_type="text/html",
                        headers={**_PUBLIC_SITE_NO_STORE_HEADERS})


# ═══ Academy Phase 4B — the learner portal ═══════════════════════════
# Students get a magic link: /learn/<portal_token> (globally-unique
# uuid on their enrollment — no passwords, no accounts). Course home
# shows their progress + lesson list with drip locks; lesson pages play
# the video, render the content + homework, and let them mark their own
# progress — feeding the SAME enrollments.progress/homework the
# practitioner's teaching view reads. Host-independent (token is the
# key), so links work on subdomains, custom domains, and standalone
# academy addresses alike.

_LEARN_CSS = _ACADEMY_CSS + """
  .prog { height: 8px; border-radius: 4px; background: rgba(127,127,127,0.18); overflow: hidden; margin: 18px 0 6px; }
  .prog > span { display: block; height: 100%; border-radius: 4px; transition: width .4s ease; }
  .lesson.locked { opacity: .55; }
  .lesson a { color: inherit; text-decoration: none; display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
  .check { width: 22px; height: 22px; border-radius: 7px; border: 1.5px solid rgba(127,127,127,0.4); flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 13px; }
  .video { position: relative; padding-top: 56.25%; border-radius: 14px; overflow: hidden; margin: 22px 0; background: #000; }
  .video iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
  .content { font-size: 15.5px; margin-top: 18px; }
  .content p { margin-bottom: 14px; }
  .hw { margin-top: 26px; padding: 18px; border-radius: 14px; border: 1px dashed rgba(127,127,127,0.4); }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 28px; }
  form.inline { display: inline; }
  button.btn { border: 0; cursor: pointer; font-family: inherit; }
  .btn.ghost { background: transparent !important; border: 1.5px solid rgba(127,127,127,0.35); color: inherit; }
"""


def _learn_video_embed(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    def _clean(v: str) -> str:
        return "".join(c for c in v if c.isalnum() or c in "_-")
    try:
        src = ""
        if "youtube.com/watch" in u and "v=" in u:
            src = f"https://www.youtube.com/embed/{_clean(u.split('v=')[1].split('&')[0])}"
        elif "youtu.be/" in u:
            src = f"https://www.youtube.com/embed/{_clean(u.split('youtu.be/')[1].split('?')[0])}"
        elif "loom.com/share/" in u:
            src = f"https://www.loom.com/embed/{_clean(u.split('loom.com/share/')[1].split('?')[0])}"
        elif "vimeo.com/" in u and "player.vimeo" not in u:
            src = f"https://player.vimeo.com/video/{_clean(u.split('vimeo.com/')[1].split('?')[0].strip('/'))}"
        if src:
            return (f'<div class="video"><iframe src="{_esc(src)}" allowfullscreen '
                    f'loading="lazy" allow="autoplay; fullscreen; picture-in-picture"></iframe></div>')
        return (f'<p style="margin-top:18px"><a class="back" href="{_esc(u)}" target="_blank" '
                f'rel="noopener">&#9654; Watch the lesson video</a></p>')
    except Exception:
        return ""


def _learn_content_html(text: str) -> str:
    """Escape + paragraphize lesson content (plain text / light markdown
    written in the studio — bold markers are stripped, not rendered)."""
    clean = _esc((text or "").replace("**", "").replace("__", ""))
    paras = [p.strip().replace("\n", "<br>") for p in clean.split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paras)


def _learn_unlock(drip_mode: str, idx: int, drip_offset_days: int, enrolled_at: str):
    """Datetime when lesson idx unlocks, or None if already available."""
    if drip_mode not in ("weekly", "custom"):
        return None
    days = idx * 7 if drip_mode == "weekly" else max(0, int(drip_offset_days or 0))
    if days <= 0:
        return None
    try:
        base = datetime.fromisoformat((enrolled_at or "").replace("Z", "+00:00"))
    except Exception:
        return None
    when = base + timedelta(days=days)
    return when if when > datetime.now(timezone.utc) else None


async def _learn_load(client, token: str):
    """enrollment + course + lessons + brand for a portal token, or None."""
    if not _academy_valid_id(token):
        return None
    erows = await _sb_service(
        client,
        f"/academy_enrollments?portal_token=eq.{token}&limit=1"
        f"&select=id,course_id,business_id,contact_id,status,progress,homework,enrolled_at,"
        f"contacts(name)") or []
    if not erows:
        return None
    enr = erows[0]
    crows = await _sb_service(
        client,
        f"/academy_courses?id=eq.{enr['course_id']}&limit=1"
        f"&select=id,title,description,drip_mode") or []
    if not crows:
        return None
    lessons = await _sb_service(
        client,
        f"/academy_lessons?course_id=eq.{enr['course_id']}&order=sort_order.asc&limit=60"
        f"&select=id,title,content,video_url,resource_url,homework,duration_minutes,"
        f"lesson_type,drip_offset_days") or []
    biz_name, accent, theme, site_config = await _academy_brand(client, enr["business_id"])
    accent, skin_head = _academy_skin(enr["business_id"], site_config, theme, accent)
    return enr, crows[0], lessons, biz_name, accent, theme, skin_head


async def _serve_learner(path: str) -> HTMLResponse:
    """GET /learn/<token>[/<lesson_id>] — course home or lesson page."""
    parts = [p for p in path.split("/") if p]  # ['learn', token, lesson?]
    token = parts[1] if len(parts) >= 2 else ""
    lesson_id = parts[2] if len(parts) >= 3 else ""
    async with httpx.AsyncClient() as client:
        loaded = await _learn_load(client, token)
        if not loaded:
            html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Link not found</title><style>{_LEARN_CSS}</style></head>
<body><div class="wrap" style="text-align:center;padding-top:90px">
  <h1>This link isn't active</h1>
  <p class="muted">Your access link may have changed &mdash; reach out to your teacher for a fresh one.</p>
</div></body></html>"""
            return HTMLResponse(content=html, status_code=404, media_type="text/html",
                                headers={**_PUBLIC_SITE_NO_STORE_HEADERS})
        enr, course, lessons, biz_name, accent, theme, skin_head = loaded
        mode_css = _academy_mode_css(theme)
        safe_biz = _esc(biz_name)
        student = _esc(((enr.get("contacts") or {}).get("name") or "").split(" ")[0] or "there")
        progress = enr.get("progress") or {}
        homework = enr.get("homework") or {}
        drip_mode = course.get("drip_mode") or "none"
        done_n = sum(1 for l in lessons if progress.get(l["id"]))
        pct = int(round(done_n / len(lessons) * 100)) if lessons else 0
        home_href = f"/learn/{token}"

        if lesson_id:
            idx = next((i for i, l in enumerate(lessons) if l["id"] == lesson_id), None)
            if idx is None:
                return RedirectResponse(url=home_href, status_code=303)
            lesson = lessons[idx]
            locked = _learn_unlock(drip_mode, idx, lesson.get("drip_offset_days") or 0,
                                   enr.get("enrolled_at") or "")
            if locked:
                return RedirectResponse(url=home_href, status_code=303)
            is_done = bool(progress.get(lesson_id))
            hw_done = bool(homework.get(lesson_id))
            nxt = lessons[idx + 1] if idx + 1 < len(lessons) else None
            video = _learn_video_embed(lesson.get("video_url") or "")
            content = _learn_content_html(lesson.get("content") or "")
            resource = ""
            if (lesson.get("resource_url") or "").strip():
                resource = (f'<p style="margin-top:14px"><a class="back" style="color:{accent}" '
                            f'href="{_esc(lesson["resource_url"])}" target="_blank" rel="noopener">'
                            f'&#128206; Lesson resource</a></p>')
            hw_html = ""
            if (lesson.get("homework") or "").strip():
                hw_btn = ("<span class=\"pill\" style=\"background:" + accent + ";color:#fff\">Homework done &#10003;</span>"
                          if hw_done else
                          f'<form class="inline" method="post" action="/learn/{token}/mark">'
                          f'<input type="hidden" name="lesson_id" value="{lesson_id}">'
                          f'<input type="hidden" name="kind" value="homework">'
                          f'<input type="hidden" name="back" value="{_esc(f"/learn/{token}/{lesson_id}")}">'
                          f'<button class="btn" style="background:{accent};padding:10px 20px;font-size:13px">I did the homework</button></form>')
                hw_html = (f'<div class="hw"><div class="eyebrow" style="color:{accent}">Homework</div>'
                           f'<div class="content" style="margin-top:6px">{_learn_content_html(lesson["homework"])}</div>'
                           f'<div style="margin-top:12px">{hw_btn}</div></div>')
            if is_done:
                mark_btn = (f'<a class="btn ghost" href="{_esc(home_href)}">Back to course</a>'
                            + (f'<a class="btn" style="background:{accent}" href="/learn/{token}/{nxt["id"]}">Next lesson &rarr;</a>' if nxt else ""))
            else:
                nxt_href = f"/learn/{token}/{nxt['id']}" if nxt else home_href
                mark_btn = (f'<form class="inline" method="post" action="/learn/{token}/mark">'
                            f'<input type="hidden" name="lesson_id" value="{lesson_id}">'
                            f'<input type="hidden" name="kind" value="lesson">'
                            f'<input type="hidden" name="back" value="{_esc(nxt_href)}">'
                            f'<button class="btn" style="background:{accent}">Mark complete'
                            + (" &amp; continue &rarr;" if nxt else "") + "</button></form>")
            html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>{_esc(lesson.get("title") or "Lesson")} &mdash; {safe_biz}</title>
<style>{_LEARN_CSS}</style>{skin_head}<style>{mode_css}</style></head>
<body><div class="wrap">
  <a class="back" style="color:{accent}" href="{_esc(home_href)}">&larr; {_esc(course.get("title") or "Course")}</a>
  <div style="height:22px"></div>
  <div class="eyebrow" style="color:{accent}">Lesson {idx + 1} of {len(lessons)}</div>
  <h1>{_esc(lesson.get("title") or "Lesson")}</h1>
  {video}
  <div class="content">{content}</div>
  {resource}
  {hw_html}
  <div class="actions">{mark_btn}</div>
  <div class="foot muted">Powered by The Solutionist System</div>
</div></body></html>"""
            return HTMLResponse(content=html, media_type="text/html",
                                headers={**_PUBLIC_SITE_NO_STORE_HEADERS})

        # Course home
        rows = ""
        for i, l in enumerate(lessons):
            locked = _learn_unlock(drip_mode, i, l.get("drip_offset_days") or 0,
                                   enr.get("enrolled_at") or "")
            is_done = bool(progress.get(l["id"]))
            check = (f'<span class="check" style="background:{accent};border-color:{accent}">&#10003;</span>'
                     if is_done else '<span class="check"></span>')
            dur = _academy_fmt_runtime(int(l.get("duration_minutes") or 0))
            if locked:
                when = locked.strftime("%b %-d") if os.name != "nt" else locked.strftime("%b %d")
                rows += (f'<div class="lesson locked">{check}'
                         f'<span class="t">{i + 1}. {_esc(l.get("title") or "Lesson")}</span>'
                         f'<span class="d muted">&#128274; unlocks {when}</span></div>')
            else:
                rows += (f'<div class="lesson"><a href="/learn/{token}/{l["id"]}">{check}'
                         f'<span class="t">{i + 1}. {_esc(l.get("title") or "Lesson")}</span>'
                         f'<span class="d muted">{_esc(dur)}</span></a></div>')
        complete = lessons and done_n == len(lessons)
        cheer = ("You finished the whole course. Incredible work."
                 if complete else
                 ("Pick up where you left off." if done_n else "Your journey starts with lesson one."))
        html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>{_esc(course.get("title") or "Course")} &mdash; {safe_biz}</title>
<style>{_LEARN_CSS}</style>{skin_head}<style>{mode_css}</style></head>
<body><div class="wrap">
  <div class="eyebrow" style="color:{accent}">{safe_biz} &middot; Academy</div>
  <h1>{_esc(course.get("title") or "Course")}</h1>
  <p class="muted" style="font-size:15px">Welcome back, {student} &mdash; {cheer}</p>
  <div class="prog"><span style="width:{pct}%;background:{accent}"></span></div>
  <div class="muted" style="font-size:12px">{done_n} of {len(lessons)} lessons complete &middot; {pct}%</div>
  <div class="lessons">{rows}</div>
  <div class="foot muted">Powered by The Solutionist System</div>
</div></body></html>"""
        return HTMLResponse(content=html, media_type="text/html",
                            headers={**_PUBLIC_SITE_NO_STORE_HEADERS})


async def _serve_site_by_slug(slug: str, path: str = "/") -> HTMLResponse:
    """Shared logic: look up site by slug and return HTML.
    Pass 3: when site_config.use_smart_sites is true, attempt Smart Sites
    render first. ANY failure falls through to legacy.
    Pass 3.8g: `path` is forwarded to render_smart_site_page so multi-page
    sites can route /about, /services, /contact correctly.
    Phase D.2.1: `/book` always serves the hosted booking page
    (regardless of MySite presence); `/` falls back to /book when the
    site has no html_content (booking_only row)."""
    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&order=updated_at.desc&limit=1"
            f"&select=html_content,business_id,site_config")
        if not sites:
            # Academy Phase 4 — a dedicated academy subdomain has no row
            # of its own; it lives in site_config.academy_slug on the
            # business's main site row.
            arow = await _sb(client,
                f"/business_sites?site_config->>academy_slug=eq.{slug}"
                f"&order=updated_at.desc&limit=1"
                f"&select=slug,business_id,site_config")
            if arow:
                a_cfg = arow[0].get("site_config") or {}
                a_biz = arow[0].get("business_id")
                if a_cfg.get("offline"):
                    return await _render_offline_page(client, a_biz)
                return await _serve_academy(
                    client, a_biz, path, standalone=True,
                    main_slug=arow[0].get("slug") or "")
            raise HTTPException(404, "Site not found")
        site = sites[0]
        biz_id = site.get("business_id")

        # Practitioner took the public site down to work on it. Editor
        # preview (/public/site/{slug}) is unaffected — only the public
        # address shows the maintenance page.
        _cfg = site.get("site_config") or {}
        if _cfg.get("offline"):
            return await _render_offline_page(client, biz_id)

        # ─── Phase D.2.1 — hosted booking page routing ─────────────
        # /book always serves the booking page (overrides MySite for
        # the booking sub-path). / redirects to /book when the site
        # has no MySite html_content (booking_only row).
        normalized_path = path.rstrip("/") or "/"
        if normalized_path == "/book":
            return await _serve_booking_page(client, biz_id, slug)
        # Online giving — /give serves the hosted give page (same
        # always-wins sub-path contract as /book).
        if normalized_path == "/give":
            return await _serve_give_page(client, biz_id, slug)
        # Public event RSVP — /events serves the hosted events page
        # (same always-wins sub-path contract as /book and /give).
        if normalized_path == "/events":
            return await _serve_events_page(client, biz_id, slug)
        # The shop, on the site's own domain rather than a railway.app
        # URL the visitor has never seen (2026-08-13 gap list).
        if normalized_path == "/store":
            return await _serve_store_page(slug)
        # ─── Academy Phase 4 — /academy catalog + course pages ─────
        if normalized_path == "/academy" or normalized_path.startswith("/academy/"):
            return await _serve_academy(client, biz_id, normalized_path, standalone=False)
        if path == "/" and not site.get("html_content"):
            return RedirectResponse(url="/book", status_code=307)

        # ─── Findability bundle (2026-08-02) ───────────────────────
        # robots.txt + sitemap.xml are real files now. They used to hit
        # the catch-all and return the HOME PAGE with a 200, which is
        # both a soft-404 and the reason neither could be added.
        _cd = _cfg.get("custom_domain")
        if normalized_path == "/robots.txt":
            return PlainTextResponse(_site_robots_txt(slug, _cd),
                                     headers={**_PUBLIC_SITE_EDGE_CACHE_HEADERS})
        if normalized_path == "/sitemap.xml":
            return Response(
                content=_site_sitemap_xml(slug, {**_cfg, "_business_id": biz_id}, _cd),
                media_type="application/xml",
                headers={**_PUBLIC_SITE_EDGE_CACHE_HEADERS})

        if _use_smart_sites(site) and biz_id:
            # Fetch products to pass into the home page renderer.
            products = await _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100") or []
            smart_html = await _try_render_smart_site(
                biz_id, "home", products=products, path=path,
            )
            if smart_html:
                return HTMLResponse(
                    content=smart_html, media_type="text/html",
                    headers={
                        "X-Solutionist-Source": "smart-sites",
                        **_PUBLIC_SITE_NO_STORE_HEADERS,
                    },
                )
            # else: fall through to legacy

        if not site.get("html_content"):
            raise HTTPException(404, "Site not found")

        # ─── Secondary pages at CLEAN paths ────────────────────────
        # A composed multi-page site stores About/Services/Contact in
        # site_config.generated_pages. They were only reachable at
        # /public/site/{slug}/about — so slug.mysolutionist.app/about
        # served the home page instead (soft-404), and the site's own
        # nav pointed visitors at the /public/... preview URL.
        _pages = _cfg.get("generated_pages")
        _page_id = _SITE_PAGE_PATHS.get(normalized_path)
        if _page_id and isinstance(_pages, dict):
            _page_html = (_pages.get(_page_id) or "").strip()
            if _page_html:
                _page_html = await _augment_html(
                    client, biz_id, slug, _page_html,
                    custom_domain=_cd, page_path=normalized_path)
                return HTMLResponse(
                    content=_page_html, media_type="text/html",
                    headers={"X-Solutionist-Source": "module-composer-multipage",
                             **_PUBLIC_SITE_EDGE_CACHE_HEADERS})

        # ─── Real 404 for anything else ────────────────────────────
        # Every unknown path used to return the home page with a 200.
        if normalized_path != "/":
            return await _render_not_found(client, slug, biz_id, _cd)

        html = await _augment_html(client, biz_id, slug, site["html_content"],
                                   custom_domain=_cd, page_path="")
        return HTMLResponse(
            content=html, media_type="text/html",
            headers={**_PUBLIC_SITE_EDGE_CACHE_HEADERS},
        )


async def _serve_site_by_custom_domain(domain: str, path: str = "/") -> HTMLResponse:
    """Look up a site by its custom domain.
    Pass 3: same flag check as _serve_site_by_slug.
    Pass 3.8g: forwards `path` for multi-page routing.
    www resolves to the same site: connect stores the APEX only (its
    normalizer strips www), so a www visitor's raw Host would match nothing
    and 404 — strip it here, covering both call sites."""
    domain = str(domain or "").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?site_config->>custom_domain=eq.{domain}"
            f"&order=updated_at.desc&limit=1"
            f"&select=html_content,slug,business_id,site_config")
        if not sites:
            # Academy Phase 4 — a domain can point at the ACADEMY as its
            # own standalone site (site_config.academy_domain).
            arow = await _sb(client,
                f"/business_sites?site_config->>academy_domain=eq.{domain}"
                f"&order=updated_at.desc&limit=1"
                f"&select=slug,business_id,site_config")
            if arow:
                a_cfg = arow[0].get("site_config") or {}
                a_biz = arow[0].get("business_id")
                if a_cfg.get("offline"):
                    return await _render_offline_page(client, a_biz)
                return await _serve_academy(
                    client, a_biz, path, standalone=True,
                    main_slug=arow[0].get("slug") or "")
            return None  # type: ignore
        site = sites[0]
        biz_id = site.get("business_id")
        slug = site.get("slug") or domain

        _cfg = site.get("site_config") or {}
        if _cfg.get("offline"):
            return await _render_offline_page(client, biz_id)

        # Academy subpaths work on custom domains too (parity with the
        # subdomain path).
        _norm = path.rstrip("/") or "/"
        if _norm == "/academy" or _norm.startswith("/academy/"):
            return await _serve_academy(client, biz_id, _norm, standalone=False)
        # Online giving works on custom domains too — a church that
        # bought its own domain must not lose /give.
        if _norm == "/give":
            return await _serve_give_page(client, biz_id, slug)
        # Public event RSVP works on custom domains too — same parity
        # reasoning as /give.
        if _norm == "/events":
            return await _serve_events_page(client, biz_id, slug)
        # Booking (2026-08-02): this was MISSING here while present on
        # the subdomain path, so /book on a practitioner's own domain
        # silently served the home page — a dead Book button on the
        # address they paid for.
        if _norm == "/book":
            return await _serve_booking_page(client, biz_id, slug)
        # Store (2026-08-13): same parity gap /book had — the shop CTA
        # sent custom-domain visitors to a railway.app address mid-purchase.
        if _norm == "/store":
            return await _serve_store_page(slug)

        # ─── Findability bundle (2026-08-02), custom-domain parity ──
        if _norm == "/robots.txt":
            return PlainTextResponse(_site_robots_txt(slug, domain),
                                     headers={**_PUBLIC_SITE_EDGE_CACHE_HEADERS})
        if _norm == "/sitemap.xml":
            return Response(
                content=_site_sitemap_xml(slug, {**_cfg, "_business_id": biz_id}, domain),
                media_type="application/xml",
                headers={**_PUBLIC_SITE_EDGE_CACHE_HEADERS})

        if _use_smart_sites(site) and biz_id:
            products = await _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100") or []
            smart_html = await _try_render_smart_site(
                biz_id, "home", products=products, path=path,
            )
            if smart_html:
                return HTMLResponse(
                    content=smart_html, media_type="text/html",
                    headers={
                        "X-Solutionist-Source": "smart-sites",
                        **_PUBLIC_SITE_NO_STORE_HEADERS,
                    },
                )

        if not site.get("html_content"):
            return None  # type: ignore

        # Secondary pages at clean paths, on the practitioner's own domain.
        _pages = _cfg.get("generated_pages")
        _page_id = _SITE_PAGE_PATHS.get(_norm)
        if _page_id and isinstance(_pages, dict):
            _page_html = (_pages.get(_page_id) or "").strip()
            if _page_html:
                _page_html = await _augment_html(
                    client, biz_id, slug, _page_html,
                    custom_domain=domain, page_path=_norm)
                return HTMLResponse(
                    content=_page_html, media_type="text/html",
                    headers={"X-Solutionist-Source": "module-composer-multipage",
                             **_PUBLIC_SITE_EDGE_CACHE_HEADERS})

        if _norm != "/":
            return await _render_not_found(client, slug, biz_id, domain)

        # custom_domain=domain is THE fix for the canonical bug: without
        # it every page here declared the platform subdomain canonical.
        html = await _augment_html(client, biz_id, slug, site["html_content"],
                                   custom_domain=domain, page_path="")
        return HTMLResponse(
            content=html, media_type="text/html",
            headers={**_PUBLIC_SITE_EDGE_CACHE_HEADERS},
        )


@router.get("/", include_in_schema=False)
async def subdomain_root(request: Request):
    """Handle subdomain requests at the root path.

    When the request arrives on the Railway API host, raise 404 so it
    falls through to whatever real route might be registered (e.g. the
    `@app.get("/")` root defined in main.py). Do NOT serve the marketing
    page from the API domain — it was shadowing every API endpoint.
    """
    host = public_host(request)

    slug = extract_slug_from_host(request)
    if slug:
        if not _check_rate(slug):
            raise HTTPException(429, "Rate limit exceeded")
        return await _serve_site_by_slug(slug)

    # Custom domain lookup (skip for API/local hosts)
    if not _is_api_host(host):
        is_known_base = any(host == base or host.endswith(f".{base}") for base in BASE_DOMAINS)
        if not is_known_base and "." in host:
            result = await _serve_site_by_custom_domain(host)
            if result:
                return result

    # API domain: let other routers / the app root handler take over.
    if _is_api_host(host):
        raise HTTPException(404, "Not found")

    # Known base domain with no subdomain — serve the new multi-page
    # home (from marketing_pages.py). The legacy MARKETING_HTML
    # constant stays defined for reference but is no longer served.
    from marketing_pages import render_home
    return HTMLResponse(content=render_home(), media_type="text/html")


# ─── Public marketing + legal + help pages ────────────────────────────
# All live at mysolutionist.app/{path}. MUST be registered BEFORE the
# subdomain catch-all or they fall through to a 404. Marketing pages
# in marketing_pages.py; legal/help in legal_content.py.

from legal_content import (
    render_privacy_html, render_data_deletion_html,
    render_terms_html, render_help_html,
)
from marketing_pages import (
    render_features, render_compare, render_faq, render_about, render_get_started,
    render_download, APP_URL as MARKETING_APP_URL,
    handle_lead_intake, LeadIntakeRequest,
)

# ─── Static brand assets ──────────────────────────────────────────────
# Logo + OG image + favicon served straight off disk with long-lived
# cache headers. Sourced from kmj-intake-server/static/brand/.
import pathlib as _pathlib
from fastapi.responses import FileResponse as _FileResponse

_STATIC_BRAND = _pathlib.Path(__file__).resolve().parent / "static" / "brand"
_BRAND_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800, immutable"}  # 7 days

def _brand_file(name: str, media_type: str):
    fp = _STATIC_BRAND / name
    if not fp.exists():
        raise HTTPException(404, f"asset not found: {name}")
    return _FileResponse(str(fp), media_type=media_type, headers=_BRAND_CACHE_HEADERS)


# ─── Byte ranges, for the media that needs them ───────────────────────
# Measured on production 2026-08-21: GET /assets/demo.mp4 with
# `Range: bytes=0-999` answered 200 and the whole 8.7MB. iOS Safari will
# not play a <video> whose server ignores Range, and every seek re-pulls
# the entire file for everyone else.
#
# Starlette's own FileResponse grew range support, but only in a release
# newer than the one fastapi==0.115.0 pins, so upgrading to reach it would
# drag the whole framework under this backend. This is the same behaviour
# in thirty lines, scoped to the media routes, and it stops mattering the
# day that pin moves.
#
# GZipMiddleware was the other suspect and is not guilty: tested against
# this file, a ranged request still returns 206 with an intact
# Content-Range and no Content-Encoding.
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_RANGE_CHUNK = 64 * 1024


def _brand_file_ranged(request: Request, name: str, media_type: str):
    """Same as _brand_file, but honours a single byte range.

    Multi-range requests (`bytes=0-99,200-299`) fall through to the whole
    file rather than being answered wrongly: they are vanishingly rare
    from media elements, and a bad multipart body is worse than a 200."""
    fp = _STATIC_BRAND / name
    if not fp.exists():
        raise HTTPException(404, f"asset not found: {name}")

    size = fp.stat().st_size
    headers = dict(_BRAND_CACHE_HEADERS)
    headers["Accept-Ranges"] = "bytes"

    def _whole():
        """Serve the file ourselves rather than handing an unparseable
        Range down to FileResponse. Newer Starlette parses the header and
        answers 400; the version this backend pins ignores it and answers
        200. RFC 9110 says ignore, and either way the point of this
        helper is that the behaviour must not depend on which Starlette
        happens to be installed."""
        def _all():
            with open(fp, "rb") as fh:
                while True:
                    block = fh.read(_RANGE_CHUNK)
                    if not block:
                        break
                    yield block
        h = dict(headers)
        h["Content-Length"] = str(size)
        return StreamingResponse(_all(), status_code=200,
                                 media_type=media_type, headers=h)

    raw = (request.headers.get("range") or "").strip()
    if not raw:
        return _FileResponse(str(fp), media_type=media_type, headers=headers)

    m = _RANGE_RE.match(raw)
    if not m:
        return _whole()

    first, last = m.group(1), m.group(2)
    if not first and not last:
        return _whole()

    if first:
        start = int(first)
        end = int(last) if last else size - 1
    else:
        # a suffix range: "give me the final N bytes", which is how a
        # player reaches for the moov atom at the tail of an mp4
        n = int(last)
        if n <= 0:
            return Response(status_code=416, headers={
                "Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
        start, end = max(0, size - n), size - 1

    end = min(end, size - 1)
    if start >= size or start > end:
        return Response(status_code=416, headers={
            "Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})

    length = end - start + 1
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)

    def _chunks():
        with open(fp, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                block = fh.read(min(_RANGE_CHUNK, left))
                if not block:
                    break
                left -= len(block)
                yield block

    return StreamingResponse(_chunks(), status_code=206,
                             media_type=media_type, headers=headers)

@router.get("/assets/logo.png", include_in_schema=False)
async def asset_logo_full():
    return _brand_file("solutionist-logo.png", "image/png")

@router.get("/assets/logo-nav.png", include_in_schema=False)
async def asset_logo_nav():
    return _brand_file("solutionist-logo-nav.png", "image/png")

@router.get("/assets/og.png", include_in_schema=False)
async def asset_og():
    return _brand_file("solutionist-og.png", "image/png")

# Square S-mark crop (512²) for the marketing hero's floating core —
# same 700² crop the app's LogoMark uses, pre-rendered so the page
# never ships the 2.2MB lockup. WebP primary, PNG fallback.
@router.get("/assets/mark.webp", include_in_schema=False)
async def asset_mark_webp():
    return _brand_file("solutionist-mark.webp", "image/webp")

@router.get("/assets/mark.png", include_in_schema=False)
async def asset_mark_png():
    return _brand_file("solutionist-mark.png", "image/png")

# The real demo video (Remotion-rendered, ~7MB) + its poster frame —
# replaces the animated HTML loop on the marketing home.
# The film the site plays. Range-aware, because a phone will not play a
# <video> whose server ignores Range.
@router.get("/assets/film.mp4", include_in_schema=False)
async def asset_film(request: Request):
    return _brand_file_ranged(request, "solutionist-film.mp4", "video/mp4")

@router.get("/assets/film-poster.jpg", include_in_schema=False)
async def asset_film_poster(request: Request):
    return _brand_file_ranged(request, "solutionist-film-poster.jpg", "image/jpeg")

# The 55-second walkthrough that ran until 2026-08-22. Deliberately kept
# reachable rather than deleted: it is the only recording of the product
# as it looked this summer, and Kevin asked for it to be saved. Nothing
# on the site links here, which is the intent — it is an archive URL, not
# a surface. Do not remove it to tidy up.
@router.get("/assets/demo.mp4", include_in_schema=False)
async def asset_demo_video(request: Request):
    return _brand_file_ranged(request, "solutionist-demo.mp4", "video/mp4")

@router.get("/assets/demo-poster.jpg", include_in_schema=False)
async def asset_demo_poster(request: Request):
    return _brand_file_ranged(request, "solutionist-demo-poster.jpg", "image/jpeg")

@router.get("/favicon.png", include_in_schema=False)
async def asset_favicon_png():
    return _brand_file("favicon.png", "image/png")

@router.get("/favicon.ico", include_in_schema=False)
async def asset_favicon_ico():
    # Browsers ask for /favicon.ico by default. Serve the PNG with the
    # correct media type — modern browsers accept PNG favicons.
    return _brand_file("favicon.png", "image/png")


# ─── Customer-facing widget bundle (Phase C.1) ─────────────────────────
# Stable public URL for the BookingForm + future customer-facing widgets.
# The bundle itself is built from solutionist-studio/src/embed/bootstrap.tsx
# via `npm run build:embed`, then committed here at static/embed.js.
#
# Refresh procedure (until we wire CI build-and-upload):
#   1. In solutionist-studio repo: `npm run build:embed`
#   2. Copy dist-embed/embed.js → kmj-intake-server/static/embed.js
#   3. Commit + push → Railway redeploys
#
# Practitioner-facing usage:
#   <script src="https://kmj-intake-server-production.up.railway.app/static/embed.js"
#           data-business="<biz uuid>"
#           data-archetype="booking_form"></script>
#
# Cache: 5 minutes. Short because the bundle revs during Phase C builds.
# Tighten to immutable+versioned URL (e.g. /static/embed.v2.js) when the
# bundle stops revving so customer browsers can cache aggressively.
#
# CORS: the global `*` allow_origins middleware on the app covers this
# route too. Script-src loads don't strictly need CORS, but the widget's
# subsequent fetch() calls back to /widgets/* DO — those are covered.
#
# TODO(phase-c-x): replace the committed binary with a CI step that
# builds and uploads on every frontend change. 198KB in git is fine for
# the spike but accumulates if we don't.
_STATIC_EMBED = _pathlib.Path(__file__).resolve().parent / "static" / "embed.js"
_EMBED_CACHE_HEADERS = {"Cache-Control": "public, max-age=300"}

@router.get("/static/embed.js", include_in_schema=False)
async def static_widget_embed():
    if not _STATIC_EMBED.exists():
        raise HTTPException(404, "embed.js bundle is not present — run `npm run build:embed` and copy from dist-embed/")
    return _FileResponse(
        str(_STATIC_EMBED),
        media_type="application/javascript",
        headers=_EMBED_CACHE_HEADERS,
    )


# ─── Platform pages vs. practitioner pages ───────────────────────────
#
# These root-level routes are registered BEFORE the catch-all, with no
# host check — so until 2026-08-02 they answered on EVERY host. A
# practitioner's own site served the SOLUTIONIST marketing About page at
# /about: not a soft-404, a brand collision, on the domain they paid
# for. (Found while verifying the findability bundle: the new sitemap
# would have advertised /about as the practitioner's page.)
#
# The path belongs to whoever owns the host. On mysolutionist.app it is
# the platform's page; on a practitioner subdomain or custom domain it
# belongs to their site (their real page, or their branded 404).

async def _platform_page_or_site(request: Request, render):
    """Serve a platform marketing/legal page ONLY on a platform host.
    On a site host, hand the same path to that site's renderer."""
    host = public_host(request)
    path = "/" + (request.url.path or "").lstrip("/")

    slug = extract_slug_from_host(request)
    if slug:
        if not _check_rate(slug):
            raise HTTPException(429, "Rate limit exceeded")
        return await _serve_site_by_slug(slug, path)

    if not _is_api_host(host):
        is_known_base = any(host == base or host.endswith(f".{base}")
                            for base in BASE_DOMAINS)
        if not is_known_base and "." in host:
            result = await _serve_site_by_custom_domain(host, path)
            if result:
                return result

    return HTMLResponse(content=render(), media_type="text/html")


# Marketing routes
@router.get("/features", include_in_schema=False)
async def public_features(request: Request):
    return await _platform_page_or_site(request, render_features)

@router.get("/compare", include_in_schema=False)
async def public_compare(request: Request):
    return await _platform_page_or_site(request, render_compare)

@router.get("/faq", include_in_schema=False)
async def public_faq(request: Request):
    return await _platform_page_or_site(request, render_faq)

@router.get("/about", include_in_schema=False)
async def public_about(request: Request):
    return await _platform_page_or_site(request, render_about)

@router.get("/get-started", include_in_schema=False)
async def public_get_started(request: Request):
    return await _platform_page_or_site(request, render_get_started)

# Arc 18 — desktop download page + login convenience redirect.
@router.get("/download", include_in_schema=False)
async def public_download(request: Request):
    return await _platform_page_or_site(request, render_download)

@router.get("/login", include_in_schema=False)
async def public_login_redirect(request: Request):
    from fastapi.responses import RedirectResponse
    # On a practitioner host /login is their page (or their 404) — the
    # app-login convenience redirect is a platform-host affordance.
    host = public_host(request)
    if extract_slug_from_host(request) or (
            not _is_api_host(host) and "." in host
            and not any(host == b or host.endswith(f".{b}") for b in BASE_DOMAINS)):
        return await _platform_page_or_site(request, lambda: "")
    return RedirectResponse(url=MARKETING_APP_URL, status_code=302)

# Intake form submission — POSTed via fetch() from /get-started. The
# request rides along so lead_attribution can read the Referer header;
# background_tasks so the Meta CAPI Lead event fires after the response.
@router.post("/api/leads", include_in_schema=False)
async def post_lead(req: LeadIntakeRequest, request: Request,
                    background_tasks: BackgroundTasks):
    return await handle_lead_intake(req, request, background_tasks)

# A2P CTA page — the publicly verifiable SMS opt-in (2026-07-04).
# Carriers' reviewers fetch this; it must stay public + crawlable.
@router.get("/sms", include_in_schema=False)
async def public_sms_optin(request: Request):
    from legal_content import render_sms_page_html
    return await _platform_page_or_site(request, render_sms_page_html)

# Legal + help routes
@router.get("/privacy", include_in_schema=False)
async def public_privacy(request: Request):
    return await _platform_page_or_site(request, render_privacy_html)

@router.get("/data-deletion", include_in_schema=False)
async def public_data_deletion(request: Request):
    return await _platform_page_or_site(request, render_data_deletion_html)

@router.get("/terms", include_in_schema=False)
async def public_terms(request: Request):
    return await _platform_page_or_site(request, render_terms_html)

@router.get("/help", include_in_schema=False)
async def public_help(request: Request):
    return await _platform_page_or_site(request, render_help_html)


@router.get("/{path:path}", include_in_schema=False)
async def subdomain_catch_all(request: Request, path: str):
    """Catch-all for subdomain + custom-domain requests. API-host
    requests MUST 404 here so they fall through to the real API routers
    — otherwise this handler shadows /email/health, /agents/*,
    everything.

    Pass 3.8g: the captured `path` is forwarded into the renderer.
    Multi-page sites use it to serve /about, /services, /contact off the
    same site_config.

    Findability bundle (2026-08-02): this no longer serves the home page
    "regardless of path". The renderer now answers /robots.txt and
    /sitemap.xml, serves real secondary pages at clean paths, and
    returns a genuine branded 404 for anything else — mass soft-404s
    were both an SEO liability and the reason robots/sitemap could not
    be added (the home page was already answering those URLs with 200)."""
    host = public_host(request)

    # API / local dev: bail immediately. Don't even look at the body.
    if _is_api_host(host):
        raise HTTPException(404, "Not found")

    # Normalize: FastAPI strips the leading slash from path:path, but the
    # downstream renderer expects /about, /services, etc.
    request_path = "/" + (path or "")

    # Academy Phase 4B — learner portal. Portal tokens are globally
    # unique, so /learn/* is host-independent: the same link works on
    # subdomains, custom domains, and standalone academy addresses.
    if request_path.startswith("/learn/"):
        return await _serve_learner(request_path)

    slug = extract_slug_from_host(request)
    if slug:
        if not _check_rate(slug):
            raise HTTPException(429, "Rate limit exceeded")
        return await _serve_site_by_slug(slug, request_path)

    # Custom domain check
    is_known_base = any(host == base or host.endswith(f".{base}") for base in BASE_DOMAINS)
    if not is_known_base and "." in host:
        result = await _serve_site_by_custom_domain(host, request_path)
        if result:
            return result

    # Not a subdomain/custom domain — 404
    raise HTTPException(404, "Not found")


@router.post("/learn/{token}/mark", include_in_schema=False)
async def learner_mark(token: str, request: Request):
    """Academy Phase 4B — a student marks a lesson (or its homework)
    done from their portal. The portal token IS the authorization; the
    write feeds the same enrollments.progress/homework the teaching
    view reads. Drip locks are enforced server-side."""
    form = await request.form()
    lesson_id = str(form.get("lesson_id") or "")
    kind = str(form.get("kind") or "lesson")
    back = str(form.get("back") or f"/learn/{token}")
    if not back.startswith("/learn/"):
        back = f"/learn/{token}"
    if not (_academy_valid_id(token) and _academy_valid_id(lesson_id)):
        return RedirectResponse(url=back, status_code=303)
    async with httpx.AsyncClient() as client:
        loaded = await _learn_load(client, token)
        if not loaded:
            raise HTTPException(404, "Link not active")
        enr, course, lessons, _bn, _ac, _th, _sk = loaded
        idx = next((i for i, l in enumerate(lessons) if l["id"] == lesson_id), None)
        if idx is None:
            return RedirectResponse(url=back, status_code=303)
        if _learn_unlock(course.get("drip_mode") or "none", idx,
                         lessons[idx].get("drip_offset_days") or 0,
                         enr.get("enrolled_at") or ""):
            return RedirectResponse(url=f"/learn/{token}", status_code=303)
        patch: Dict[str, Any] = {}
        if kind == "homework":
            hw = dict(enr.get("homework") or {})
            hw[lesson_id] = True
            patch["homework"] = hw
        else:
            prog = dict(enr.get("progress") or {})
            prog[lesson_id] = True
            patch["progress"] = prog
            if lessons and all(prog.get(l["id"]) for l in lessons):
                patch["status"] = "completed"
                patch["completed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            await _sb_service_patch(client,
                f"/academy_enrollments?id=eq.{enr['id']}", patch)
        except Exception as e:
            logger.warning(f"learner mark failed (soft): {e}")
    return RedirectResponse(url=back, status_code=303)
