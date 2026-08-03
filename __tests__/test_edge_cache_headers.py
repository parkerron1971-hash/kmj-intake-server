# __tests__/test_edge_cache_headers.py
#
# Edge caching for stable public pages (2026-08-02).
#
# Measured before this change: Cloudflare could not cache the HTML, so
# it stopped being a CDN and became a 500ms tax — 1153ms TTFB through
# the edge vs 650ms straight to Railway — and every page view ran the
# full render on the ONE uvicorn worker Chief and site builds share.
#
# The rule these tests protect: only STORED ARTIFACTS may be cached.
# Anything that reflects live state keeps no-store, and the browser
# must always revalidate so a practitioner sees their own edit at once.

import inspect
import re

import public_site as ps


def _cc(headers: dict) -> str:
    return headers.get("Cache-Control", "")


# ─── The shape of the caching header ──────────────────────────────────

def test_browser_always_revalidates():
    """This is the property the original no-store was protecting: a
    practitioner refreshing their own site must never see a stale page
    out of their own browser cache."""
    cc = _cc(ps._PUBLIC_SITE_EDGE_CACHE_HEADERS)
    assert "max-age=0" in cc
    assert "must-revalidate" in cc


def test_the_shared_cache_may_serve_briefly():
    cc = _cc(ps._PUBLIC_SITE_EDGE_CACHE_HEADERS)
    assert "public" in cc
    m = re.search(r"s-maxage=(\d+)", cc)
    assert m, "no s-maxage — Cloudflare still cannot cache the page"
    ttl = int(m.group(1))
    # Long enough to absorb traffic, short enough that an edit reaches
    # the world quickly without any purge plumbing.
    assert 30 <= ttl <= 300, f"s-maxage={ttl} is outside the sane window"
    assert "stale-while-revalidate=" in cc


def test_no_store_and_cacheable_are_mutually_exclusive():
    """no-store anywhere in the value would void the whole thing."""
    cc = _cc(ps._PUBLIC_SITE_EDGE_CACHE_HEADERS)
    assert "no-store" not in cc
    assert "no-store" in _cc(ps._PUBLIC_SITE_NO_STORE_HEADERS)


# ─── What may and may not be cached ───────────────────────────────────

# Pages whose content is a stored artifact — safe at the edge.
_CACHEABLE = ("_serve_site_by_slug", "_serve_site_by_custom_domain")

# Pages that reflect LIVE state. Booking shows real slot availability;
# giving and events reflect what is currently active; the offline page
# and 404s must never be held by a cache.
_MUST_STAY_NO_STORE = (
    "_serve_booking_page",
    "_serve_give_page",
    "_serve_events_page",
    "_render_offline_page",
    "_serve_learner",
)


def test_live_state_pages_never_became_cacheable():
    for fn_name in _MUST_STAY_NO_STORE:
        fn = getattr(ps, fn_name, None)
        if fn is None:
            continue
        src = inspect.getsource(fn)
        assert "_PUBLIC_SITE_EDGE_CACHE_HEADERS" not in src, (
            f"{fn_name} reflects live state — it must not be edge-cached")
        assert "_PUBLIC_SITE_NO_STORE_HEADERS" in src, (
            f"{fn_name} lost its no-store headers")


def test_the_404_page_is_not_cacheable():
    src = inspect.getsource(ps._not_found_page)
    assert "_PUBLIC_SITE_NO_STORE_HEADERS" in src
    assert "_PUBLIC_SITE_EDGE_CACHE_HEADERS" not in src


def test_both_serve_paths_cache_the_stored_page():
    """Home, secondary pages, robots and sitemap on BOTH hosts."""
    for fn_name in _CACHEABLE:
        src = inspect.getsource(getattr(ps, fn_name))
        assert src.count("_PUBLIC_SITE_EDGE_CACHE_HEADERS") >= 4, (
            f"{fn_name} should cache home + secondary + robots + sitemap")


def test_offline_still_wins_over_the_cache_headers():
    """The offline check must happen BEFORE any cacheable response is
    built, or a site could be taken down and still serve a cached page
    from our own process."""
    for fn_name in _CACHEABLE:
        src = inspect.getsource(getattr(ps, fn_name))
        assert src.index("offline") < src.index("_PUBLIC_SITE_EDGE_CACHE_HEADERS"), (
            f"{fn_name} builds a cacheable response before checking offline")
