"""Site-builder audit (2026-08-13) — the site's own nav pointed at the
internal preview URL.

build_page_nav built hrefs from the /public/site/{slug} preview base, so
every visitor who clicked About landed on the editor's URL. Three things
followed, all on the real site:

  - a practitioner on the custom domain they paid for got
    theirdomain.com/public/site/acme/about in the address bar
  - the preview path has no offline check (deliberately — it is the
    editor's own view), so taking a site down left every secondary page
    still serving to anyone with the link
  - that handler never passed page_path to _inject_canonical, so every
    secondary page declared itself canonical to the HOME page

The clean routes were built and working the whole time. Only the nav
never moved onto them.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import public_site  # noqa: E402
import site_multipage  # noqa: E402


def _hrefs(current="home"):
    nav = site_multipage.build_page_nav("acme", current)
    return {p["id"]: p["href"] for p in nav["pages"]}


# ─── the nav a visitor actually gets ─────────────────────────────────


def test_nav_uses_clean_root_relative_paths():
    assert _hrefs() == {
        "home": "/", "about": "/about",
        "services": "/services", "contact": "/contact",
    }


def test_nav_never_leaks_the_internal_preview_base():
    """The whole finding: /public/site/... must not reach a visitor."""
    for href in _hrefs().values():
        assert "/public/site/" not in href
        assert "acme" not in href


def test_nav_is_host_agnostic():
    """Root-relative, not absolute — so the same stored HTML is correct
    on the subdomain today and a custom domain added tomorrow, with no
    rebuild."""
    for href in _hrefs().values():
        assert href.startswith("/")
        assert not href.startswith("//")
        assert "://" not in href


def test_active_page_is_marked():
    nav = site_multipage.build_page_nav("acme", "services")
    active = [p["id"] for p in nav["pages"] if p.get("active")]
    assert active == ["services"]


# ─── the preview keeps working ───────────────────────────────────────


_NAV_HTML = (
    '<nav class="sxm-header-nav sxm-header-pagenav" aria-label="Pages">'
    '<a href="/">Home</a><a href="/about">About</a>'
    '<a href="/services">Services</a><a href="/contact">Contact</a></nav>'
)


def test_preview_rewrite_points_nav_at_the_preview_base():
    out = public_site._rewrite_nav_for_preview(_NAV_HTML, "acme")
    assert 'href="/public/site/acme"' in out
    assert 'href="/public/site/acme/about"' in out
    assert 'href="/public/site/acme/contact"' in out


def test_preview_rewrite_leaves_single_page_sites_alone():
    single = '<nav class="sxm-header-nav"><a href="#about">About</a></nav>'
    assert public_site._rewrite_nav_for_preview(single, "acme") == single


def test_preview_rewrite_tolerates_empty_html():
    assert public_site._rewrite_nav_for_preview("", "acme") == ""


def test_preview_rewrite_absolutises_always_wins_subpaths():
    """/book and /store are root-relative in stored HTML so they stay
    correct on a custom domain (2026-08-13 gap list). The preview base is
    not the site root, so left alone they would leave the studio for the
    app root. They become absolute public URLs here — clickable in the
    preview, with no host baked into what a visitor receives."""
    html = _NAV_HTML + '<a href="/book">Book</a><a href="/store">Shop</a>'
    out = public_site._rewrite_nav_for_preview(html, "acme")
    assert 'href="https://acme.mysolutionist.app/book"' in out
    assert 'href="https://acme.mysolutionist.app/store"' in out
    assert 'href="/book"' not in out


def test_preview_rewrite_handles_a_single_page_site_with_a_book_link():
    """A single-page site has no cross-page nav but still carries a Book
    CTA — the rewrite must not skip it just because the nav is absent."""
    html = '<a href="/book">Book</a>'
    out = public_site._rewrite_nav_for_preview(html, "acme")
    assert 'href="https://acme.mysolutionist.app/book"' in out


def test_preview_rewrite_leaves_unrelated_links_alone():
    html = _NAV_HTML + '<a href="/some-other-thing">Other</a>'
    out = public_site._rewrite_nav_for_preview(html, "acme")
    assert 'href="/some-other-thing"' in out
