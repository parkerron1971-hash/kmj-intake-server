"""
__tests__/test_booking_page.py — Phase D.2.1 unit tests.

Pure-function tests for:
  - slug derivation from business name (business_sites_helpers)
  - canonical URL construction
  - server-rendered HTML shape (head meta, OG tags, brand-applied
    CSS vars, embed mount, footer)
  - "not published" page shape

Tests that touch the DB (ensure_business_site collision resolution,
backfill behavior) are integration-level and run against the live
Supabase via the existing service-role client — kept out of the unit
suite for speed.

Run via:  python -m pytest __tests__/test_booking_page.py -v
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from business_sites_helpers import (
    PUBLIC_DOMAIN,
    booking_url_for_site,
    derive_slug_from_name,
)
from booking_page_renderer import (
    render_booking_page,
    render_not_published_page,
)


# ─── 1. Slug derivation ─────────────────────────────────────────────

def test_slug_simple():
    assert derive_slug_from_name("Royal Barbers") == "royal-barbers"


def test_slug_double_space_normalized():
    assert derive_slug_from_name("KMJ Creative  Solutions") == "kmj-creative-solutions"


def test_slug_apostrophe_and_lowercase():
    assert derive_slug_from_name("kay's creative fashion") == "kays-creative-fashion"


def test_slug_leading_trailing_whitespace():
    assert derive_slug_from_name("  Foo Bar  ") == "foo-bar"


def test_slug_unicode_punctuation_falls_back_to_dashes():
    # Em-dash, comma, slash → all normalized to a single hyphen
    assert derive_slug_from_name("Foo — Bar, Baz/Qux") == "foo-bar-baz-qux"


def test_slug_empty_input_falls_back():
    assert derive_slug_from_name("") == "business"
    assert derive_slug_from_name(None) == "business"
    assert derive_slug_from_name("...") == "business"  # all non-alnum


def test_slug_no_leading_or_trailing_hyphens():
    assert derive_slug_from_name(" - hello -- ") == "hello"
    assert not derive_slug_from_name("Royal Barbers").startswith("-")
    assert not derive_slug_from_name("Royal Barbers").endswith("-")


def test_slug_no_consecutive_hyphens():
    out = derive_slug_from_name("Foo --- Bar")
    assert "--" not in out
    assert out == "foo-bar"


def test_slug_all_lowercase():
    assert derive_slug_from_name("FOO BAR") == "foo-bar"
    assert derive_slug_from_name("FooBarBaz") == "foobarbaz"


# ─── 2. Canonical URL construction ──────────────────────────────────

def test_booking_url_for_site_basic():
    site = {"slug": "royal-barbers"}
    url = booking_url_for_site(site)
    assert url == f"https://royal-barbers.{PUBLIC_DOMAIN}/book"


def test_booking_url_for_site_missing_slug_fallback():
    site = {"slug": None}
    url = booking_url_for_site(site)
    assert url == f"https://business.{PUBLIC_DOMAIN}/book"


# ─── 3. SSR HTML shape — published page ─────────────────────────────

def _sample_business(
    *, name="Royal Barbers",
    brand=None,
    booking_page=None,
) -> dict:
    settings = {
        "brand_kit": brand or {},
        "booking_page": booking_page or {"published": True},
    }
    return {
        "id": "72676739-e851-469d-88f9-ad31606adbb6",
        "name": name,
        "settings": settings,
    }


def test_rendered_page_has_doctype_and_lang():
    biz = _sample_business()
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://kmj-intake-server-production.up.railway.app",
    )
    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in html


def test_rendered_page_has_title_and_og_tags():
    biz = _sample_business(
        booking_page={"published": True, "tagline": "Best fades in town"},
    )
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    assert "<title>Book with Royal Barbers</title>" in html
    assert 'property="og:title" content="Book with Royal Barbers"' in html
    assert 'property="og:url" content="https://royal-barbers.mysolutionist.app/book"' in html
    assert 'rel="canonical" href="https://royal-barbers.mysolutionist.app/book"' in html
    # Description prefers tagline when present
    assert 'content="Best fades in town"' in html


def test_rendered_page_falls_back_to_default_description_when_no_tagline():
    biz = _sample_business(booking_page={"published": True})
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    assert 'content="Book an appointment with Royal Barbers."' in html


def test_rendered_page_applies_brand_kit_as_css_vars():
    biz = _sample_business(
        brand={"accent": "#ff8800", "surface": "#fff8f0", "text_primary": "#3a1f00"},
    )
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    assert "--accent: #ff8800" in html
    assert "--surface: #fff8f0" in html
    assert "--text-primary: #3a1f00" in html


def test_rendered_page_uses_neutral_defaults_when_brand_missing():
    biz = _sample_business(brand={})
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    # Neutral defaults from _css_vars
    assert "--accent: #a78bfa" in html


def test_rendered_page_includes_embed_script_with_correct_attrs():
    biz = _sample_business()
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://kmj-intake-server-production.up.railway.app",
    )
    # script src points to embed.js on the given origin
    assert 'src="https://kmj-intake-server-production.up.railway.app/static/embed.js"' in html
    # business id matches
    assert 'data-business="72676739-e851-469d-88f9-ad31606adbb6"' in html
    # archetype is booking_form
    assert 'data-archetype="booking_form"' in html


def test_rendered_page_includes_powered_by_footer_default():
    biz = _sample_business()
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    assert "Powered by" in html
    assert "Solutionist" in html


def test_rendered_page_uses_practitioner_footer_text_when_present():
    biz = _sample_business(
        booking_page={"published": True, "footer_text": "© 2026 Royal Barbers · All rights reserved"},
    )
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    assert "Royal Barbers · All rights reserved" in html
    # Default attribution NOT present when override is set
    assert "Powered by" not in html


def test_rendered_page_renders_logo_when_url_present():
    biz = _sample_business(
        brand={"logo_url": "https://example.com/logo.png"},
    )
    html = render_booking_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    assert 'class="bk-logo" src="https://example.com/logo.png"' in html
    # Also used as favicon + OG image
    assert 'rel="icon" href="https://example.com/logo.png"' in html
    assert 'property="og:image" content="https://example.com/logo.png"' in html


def test_rendered_page_escapes_html_in_name_and_tagline():
    biz = _sample_business(
        name='Royal "Best" Barbers <script>alert(1)</script>',
        booking_page={"published": True, "tagline": "Open <b>now</b>"},
    )
    html = render_booking_page(
        biz, "https://example.mysolutionist.app/book",
        embed_origin="https://example.com",
    )
    # Both should appear escaped, NOT executable
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html or "alert" not in html
    assert "<b>now</b>" not in html


# ─── 4. Not-published page ──────────────────────────────────────────

def test_not_published_page_has_noindex():
    biz = _sample_business(booking_page={"published": False})
    html = render_not_published_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
    )
    assert 'name="robots" content="noindex,nofollow"' in html
    assert "isn't published yet" in html


def test_not_published_page_still_applies_brand():
    biz = _sample_business(
        brand={"accent": "#ff0000"}, booking_page={"published": False},
    )
    html = render_not_published_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
    )
    assert "--accent: #ff0000" in html


def test_not_published_page_has_no_widget_script():
    biz = _sample_business(booking_page={"published": False})
    html = render_not_published_page(
        biz, "https://royal-barbers.mysolutionist.app/book",
    )
    assert "embed.js" not in html
    assert 'data-archetype="booking_form"' not in html
