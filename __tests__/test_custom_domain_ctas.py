"""Post-audit gap list (2026-08-13) — a practitioner's own domain is the
address, not a fallback.

Two shapes of the same bug:

  1. Links SHARED with people (Embed tab copy button, QR code, email
     templates, readiness surfaces) hardcoded the platform subdomain, so
     a practitioner who connected and paid for a domain still handed out
     mysolutionist.app.

  2. Links rendered INTO the site's own HTML were absolute, freezing
     whichever host existed at compose time. The Book button walked a
     custom-domain visitor onto mysolutionist.app, and the store CTA sent
     them to a railway.app URL at the exact moment they decided to buy.

Shared links must be absolute and honour the domain. Links inside the
page must be root-relative, so the same stored HTML is correct on
whichever host serves it — including a domain connected next month, with
no rebuild.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import business_sites_helpers as bsh  # noqa: E402
import public_site  # noqa: E402


# ─── shared links: absolute, and the domain wins ─────────────────────


def test_booking_link_uses_the_custom_domain_when_one_is_connected():
    site = {"slug": "acme", "site_config": {"custom_domain": "acmecoaching.com"}}
    assert bsh.booking_url_for_site(site) == "https://acmecoaching.com/book"


def test_booking_link_falls_back_to_the_subdomain():
    assert bsh.booking_url_for_site({"slug": "acme"}) == \
        "https://acme.mysolutionist.app/book"


def test_blank_or_malformed_custom_domain_falls_back():
    for cfg in ({"custom_domain": ""}, {"custom_domain": "   "},
                {"custom_domain": None}, "not-a-dict", None):
        site = {"slug": "acme", "site_config": cfg}
        assert bsh.booking_url_for_site(site) == \
            "https://acme.mysolutionist.app/book"


def test_custom_domain_is_normalised():
    site = {"slug": "acme", "site_config": {"custom_domain": "/AcmeCoaching.com"}}
    assert bsh.booking_url_for_site(site) == "https://acmecoaching.com/book"


# ─── the store is served on the site's own domain now ────────────────


def test_store_is_an_always_wins_path():
    """Without this, /store on a practitioner's domain falls through to
    the catch-all and serves the home page — the same soft-404 /book had
    before 2026-08-02."""
    assert "/store" in public_site._ALWAYS_WINS_PATHS
    for expected in ("/book", "/give", "/events"):
        assert expected in public_site._ALWAYS_WINS_PATHS


def test_a_store_route_exists_to_serve_it():
    assert callable(getattr(public_site, "_serve_store_page", None))


# ─── links inside the page stay host-agnostic ────────────────────────


def test_composed_booking_and_store_hrefs_are_root_relative():
    """Read from the source rather than composing a site, because
    composing costs money. The assertion that matters is that neither
    href carries a scheme — an absolute URL is what froze the host."""
    import inspect

    import site_composer
    src = inspect.getsource(site_composer.gather_context)
    assert '"url": "/book" if (site and slug) else ""' in src, (
        "the composed Book CTA is not root-relative")
    assert '"url": "/store" if slug else ""' in src, (
        "the composed store CTA is not root-relative")
    assert "RAILWAY_BASE}/public/store/" not in src, (
        "the store CTA still hardcodes the railway origin")
