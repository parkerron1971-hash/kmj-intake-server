"""Hand-built sites (site_config.html_source == "manual") — 2026-09-03.

The KMJ redesign lives in sites/kmj-creative-solutions/ and is installed
by SQL. These tests pin the three promises that make that safe:

  1. public_site serves the stored page with the override system's text
     edits applied and the verified sending address filled in — and
     strips the mailto element rather than printing a platform address
     when the business has no verified sender.
  2. Neither builder engine touches the row: _use_smart_sites is False and
     refresh_if_composed (the path every offerings/gallery/override save
     fires) returns without rendering.
  3. build.py assembles every page with no unfilled build-time token, keeps
     the serve-time tokens, and leaves the platform's live-injection
     placeholders in place so a future shop can switch on.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import public_site  # noqa: E402


VERIFIED = {"email_domain": {"status": "verified", "domain": "kmjcreate.com",
                             "from_local_part": "kevin", "from_name": "Kevin"}}
PAGE = ('<p data-override-target="home.hero.lead">old lead</p>'
        '<a href="mailto:{{BUSINESS_EMAIL}}" data-needs-email>{{BUSINESS_EMAIL}}</a>')


def test_manual_source_is_detected_only_by_the_exact_flag():
    assert public_site._is_manual_source({"html_source": "manual"})
    assert not public_site._is_manual_source({"html_source": "module-composer"})
    assert not public_site._is_manual_source({})
    assert not public_site._is_manual_source(None)


def test_smart_sites_never_shadows_a_manual_page():
    row = {"site_config": {"html_source": "manual", "use_smart_sites": True}}
    assert public_site._use_smart_sites(row) is False


def test_verified_sender_fills_the_email_token(monkeypatch):
    monkeypatch.setattr(
        "agents.override_system.override_resolver.resolve_html_overrides",
        lambda html, biz: html)
    out = public_site._apply_manual_source(PAGE, "biz-1", VERIFIED)
    assert 'href="mailto:kevin@kmjcreate.com"' in out
    assert ">kevin@kmjcreate.com</a>" in out
    assert "{{BUSINESS_EMAIL}}" not in out


def test_no_verified_sender_removes_the_mailto_rather_than_showing_a_platform_address(monkeypatch):
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mysolutionist.app")
    monkeypatch.setattr(
        "agents.override_system.override_resolver.resolve_html_overrides",
        lambda html, biz: html)
    out = public_site._apply_manual_source(PAGE, "biz-1", {})
    assert "mysolutionist.app" not in out
    assert "data-needs-email" not in out
    assert "{{BUSINESS_EMAIL}}" not in out
    assert 'data-override-target="home.hero.lead"' in out


def test_override_edits_reach_a_manual_page(monkeypatch):
    def fake_resolve(html, biz):
        assert biz == "biz-1"
        return html.replace(">old lead<", ">new lead from Edit Mode<")
    monkeypatch.setattr(
        "agents.override_system.override_resolver.resolve_html_overrides", fake_resolve)
    out = public_site._apply_manual_source(PAGE, "biz-1", VERIFIED)
    assert "new lead from Edit Mode" in out


def test_override_failure_never_blanks_the_page(monkeypatch):
    def boom(html, biz):
        raise RuntimeError("db down")
    monkeypatch.setattr(
        "agents.override_system.override_resolver.resolve_html_overrides", boom)
    out = public_site._apply_manual_source(PAGE, "biz-1", VERIFIED)
    assert "old lead" in out
    assert "kevin@kmjcreate.com" in out


def test_refresh_leaves_a_manual_site_alone(monkeypatch):
    import site_composer
    monkeypatch.setattr(site_composer, "gather_context", lambda biz: {
        "site": {"slug": "kmj", "site_config": {
            "html_source": "manual", "site_type": "multi-page",
            "page_spec": {"sections": [{"module": "hero"}]},
            "canvas": {"html": "<html>stale canvas</html>"},
        }},
        "business": {"name": "KMJ"},
    })

    def must_not_render(*a, **k):
        raise AssertionError("render_and_persist ran on a manual site")
    monkeypatch.setattr(site_composer, "render_and_persist", must_not_render)
    monkeypatch.setattr(site_composer, "rebuild_secondary_pages", must_not_render)
    assert site_composer.refresh_if_composed("biz-1") is False


def _load_build():
    path = os.path.join(ROOT, "sites", "kmj-creative-solutions", "build.py")
    spec = importlib.util.spec_from_file_location("kmj_site_build", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built_pages():
    b = _load_build()
    css = b._read("site.css")
    nav = b._read("_nav.html")
    footer = b._read("_footer.html")
    logo, sig = b._image_refs(inline=False)
    assert logo.startswith("https://") and "/public/site-assets/kmj-creative-solutions/logo.webp?v=" in logo
    return {p: b.assemble(p, css, nav, footer, logo, sig) for p in b.PAGES}


def test_every_page_assembles_with_only_serve_time_tokens_left(built_pages):
    assert set(built_pages) == {"home", "about", "services", "contact"}
    for name, html in built_pages.items():
        assert html.startswith("<!DOCTYPE html>"), name
        assert "{{LOGO}}" not in html and "{{SIGNATURE}}" not in html, name
        assert "{{PORTRAIT}}" not in html and "{{API_BASE}}" not in html, name
        assert "{{BUSINESS_EMAIL}}" in html, name          # footer, every page
        assert 'class="nav-links sxm-header-pagenav"' in html, name


def test_home_keeps_the_live_injection_placeholders_and_wires_the_form(built_pages):
    home = built_pages["home"]
    assert "{{PRODUCTS_SECTION}}" in home
    assert "{{GALLERY_SECTION}}" in home and "{{TESTIMONIALS_SECTION}}" in home
    assert 'name="x-solutionist-composer"' not in home
    contact = built_pages["contact"]
    assert "/sites/12773842-3cc6-41a7-9094-b8606e3f7549/contact-submit" in contact
    assert 'href="/book"' in home and 'href="/book"' in contact


def test_the_public_domain_path_fills_a_manual_page_too(monkeypatch):
    """#805 hooked the /public/site preview handlers; kmjcreate.com went
    live through _augment_html printing {{BUSINESS_EMAIL}}. The fill now
    lives in the one function every public path runs through."""
    import asyncio

    async def fake_sb(client, path):
        if path.startswith("/businesses?"):
            return [{"settings": VERIFIED}]
        return []
    monkeypatch.setattr(public_site, "_sb", fake_sb)
    monkeypatch.setattr(
        "agents.override_system.override_resolver.resolve_html_overrides",
        lambda html, biz: html.replace(">old lead<", ">edited<"))
    page = "<html><head></head><body>" + PAGE + "</body></html>"
    out = asyncio.run(public_site._augment_html(
        None, "biz-1", "kmj-creative-solutions", page,
        custom_domain="kmjcreate.com", page_path="/contact", manual=True))
    assert "kevin@kmjcreate.com" in out
    assert "{{BUSINESS_EMAIL}}" not in out
    assert ">edited<" in out
    untouched = asyncio.run(public_site._augment_html(
        None, "biz-1", "kmj-creative-solutions", page,
        custom_domain="kmjcreate.com", page_path="/contact"))
    assert "{{BUSINESS_EMAIL}}" in untouched      # a composed site is left alone


def test_site_assets_resolve_only_inside_the_assets_folder():
    ok = public_site._site_asset_path("kmj-creative-solutions", "logo.webp")
    assert ok is not None and ok.name == "logo.webp"
    assert public_site._site_asset_path("kmj-creative-solutions", "signature.webp") is not None
    # traversal, dots, extensions the route doesn't serve, missing files
    assert public_site._site_asset_path("..", "logo.webp") is None
    assert public_site._site_asset_path("kmj-creative-solutions", "../build.py") is None
    assert public_site._site_asset_path("kmj-creative-solutions", "build.py") is None
    assert public_site._site_asset_path("kmj-creative-solutions", "site.css") is None
    assert public_site._site_asset_path("kmj-creative-solutions", "nope.webp") is None
    assert public_site._site_asset_path("Kmj", "logo.webp") is None


def test_site_asset_route_sets_long_cache_and_type():
    resp = public_site.site_asset("kmj-creative-solutions", "logo.webp")
    assert resp.media_type == "image/webp"
    assert resp.headers.get("cache-control", "").startswith("public, max-age=")
    with pytest.raises(Exception):
        public_site.site_asset("kmj-creative-solutions", "../build.py")


def test_pages_carry_override_targets_and_no_leftover_facts(built_pages):
    for name, html in built_pages.items():
        assert "data-override-target=" in html, name
        assert "(555)" not in html and "kmjcreative.co" not in html, name
        assert "$25" not in html and "Tues" not in html, name
