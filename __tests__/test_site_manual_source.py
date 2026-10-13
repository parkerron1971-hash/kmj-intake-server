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


def test_no_verified_sender_removes_a_whole_marked_block(monkeypatch):
    """Contact marks its label + address + note as one block, so an
    unverified sender leaves no orphaned 'Direct email' heading behind."""
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mysolutionist.app")
    monkeypatch.setattr(
        "agents.override_system.override_resolver.resolve_html_overrides",
        lambda html, biz: html)
    page = ('<div class="contact-email" data-needs-email><span>Direct email</span>'
            '<a href="mailto:{{BUSINESS_EMAIL}}">{{BUSINESS_EMAIL}}</a><span>Every inquiry</span></div>'
            '<div class="after">kept</div>')
    out = public_site._apply_manual_source(page, "biz-1", {})
    assert "Direct email" not in out and "Every inquiry" not in out
    assert '<div class="after">kept</div>' in out
    filled = public_site._apply_manual_source(page, "biz-1", VERIFIED)
    assert "Direct email" in filled and "kevin@kmjcreate.com" in filled


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


CUSTOM_PAGE_IDS = ["visit", "about", "beliefs", "sermons", "give", "ministries", "events", "connect", "watch"]


@pytest.fixture
def custom_manual_site(monkeypatch):
    pages = {pid: '<html><head></head><body>' + PAGE.replace("home.hero.lead", pid + ".hero.lead")
             + f'<nav><a href="/{pid}">{pid}</a></nav></body></html>' for pid in CUSTOM_PAGE_IDS}
    row = {"slug": "church", "business_id": "biz-1", "html_content": "HOME",
           "site_config": {"html_source": "manual", "site_pages": ["home"] + CUSTOM_PAGE_IDS,
                           "generated_pages": pages, "custom_domain": "church.example"}}

    async def fake_sb(client, path):
        if path.startswith("/business_sites?"):
            return [row]
        if path.startswith("/businesses?"):
            return [{"settings": VERIFIED}]
        return []

    monkeypatch.setattr(public_site, "_sb", fake_sb)
    monkeypatch.setattr(public_site, "_check_rate", lambda slug: True)
    monkeypatch.setattr(public_site, "_inject_brand_meta", lambda html, biz: html)
    monkeypatch.setattr("agents.override_system.override_resolver.resolve_html_overrides",
                        lambda html, biz: html.replace(">old lead<", ">custom page edited<"))
    return row


@pytest.mark.parametrize("pid", CUSTOM_PAGE_IDS)
@pytest.mark.parametrize("custom_domain", [False, True])
def test_every_custom_page_serves_on_both_public_hosts(monkeypatch, custom_manual_site, pid, custom_domain):
    import asyncio
    calls = []

    async def augment(client, biz, slug, html, custom_domain=None, page_path="", manual=False):
        calls.append((page_path, manual))
        html = public_site._apply_manual_source(html, biz, VERIFIED) if manual else html
        return public_site._inject_canonical(html, slug, custom_domain, page_path)

    monkeypatch.setattr(public_site, "_augment_html", augment)
    serve = public_site._serve_site_by_custom_domain if custom_domain else public_site._serve_site_by_slug
    response = asyncio.run(serve("church.example" if custom_domain else "church", "/" + pid + "/"))
    body = response.body.decode()
    assert response.status_code == 200
    assert response.headers["X-Solutionist-Source"] == "manual-site"
    assert calls == [("/" + pid, True)]
    assert 'href="https://church.example/' + pid + '"' in body
    assert "custom page edited" in body and "kevin@kmjcreate.com" in body


@pytest.mark.parametrize("pid", CUSTOM_PAGE_IDS)
def test_preview_serves_custom_page_with_overrides_and_its_own_canonical(custom_manual_site, pid):
    import asyncio
    response = asyncio.run(public_site.get_site_page_html("church", pid))
    body = response.body.decode()
    assert response.status_code == 200
    assert response.headers["X-Solutionist-Source"] == "manual-site"
    assert "custom page edited" in body and "kevin@kmjcreate.com" in body
    assert 'href="https://church.example/' + pid + '"' in body
    assert 'href="/public/site/church/' + pid + '"' in body


@pytest.mark.parametrize("custom_domain", [False, True])
@pytest.mark.parametrize("pid,handler", [("give", "_serve_give_page"), ("events", "_serve_events_page"),
                                        ("book", "_serve_booking_page"), ("store", "_serve_store_page")])
def test_hosted_pages_still_serve_when_no_manual_page_claims_path(monkeypatch, custom_manual_site, custom_domain, pid, handler):
    import asyncio
    custom_manual_site["site_config"]["generated_pages"].pop(pid, None)

    async def hosted(*args, **kwargs):
        return public_site.HTMLResponse("hosted " + pid)

    monkeypatch.setattr(public_site, handler, hosted)
    serve = public_site._serve_site_by_custom_domain if custom_domain else public_site._serve_site_by_slug
    response = asyncio.run(serve("church.example" if custom_domain else "church", "/" + pid))
    assert response.body.decode() == "hosted " + pid


@pytest.mark.parametrize("custom_domain", [False, True])
def test_custom_manual_routes_respect_offline_and_unknown_path(monkeypatch, custom_manual_site, custom_domain):
    import asyncio

    async def missing(*args, **kwargs):
        return public_site.HTMLResponse("missing", status_code=404)

    async def offline(*args, **kwargs):
        return public_site.HTMLResponse("offline")

    monkeypatch.setattr(public_site, "_render_not_found", missing)
    monkeypatch.setattr(public_site, "_render_offline_page", offline)
    serve = public_site._serve_site_by_custom_domain if custom_domain else public_site._serve_site_by_slug
    host = "church.example" if custom_domain else "church"
    assert asyncio.run(serve(host, "/unknown")).status_code == 404
    custom_manual_site["site_config"]["offline"] = True
    assert asyncio.run(serve(host, "/visit")).body.decode() == "offline"


@pytest.mark.parametrize("host", ["church.mysolutionist.app", "church.example"])
def test_composed_pages_keep_main_routes_through_the_real_app(monkeypatch, custom_manual_site, host):
    import no_card_trial
    import site_check
    import sb_clients
    from fastapi.testclient import TestClient
    from kmj_intake_automation import app

    cfg = custom_manual_site["site_config"]
    cfg.update(html_source="module-composer", offer_page={"path": "/saturday-shave-club"},
               generated_pages={"about": "<html>ABOUT</html>", "offer": "<html><head></head><body>OFFER</body></html>",
                                "faq": "<html>STALE FAQ</html>", "give": "<html>STALE GIVE</html>"})

    async def visible(*args):
        return False

    async def augment(client, biz, slug, html, **kwargs):
        return public_site._inject_canonical(html, slug, kwargs.get("custom_domain"), kwargs.get("page_path", ""))

    async def missing(*args):
        return public_site.HTMLResponse("missing", status_code=404)

    async def hosted(*args):
        return public_site.HTMLResponse("HOSTED GIVING")

    monkeypatch.setattr(no_card_trial, "site_hidden", visible)
    monkeypatch.setattr(public_site, "_augment_html", augment)
    monkeypatch.setattr(public_site, "_render_not_found", missing)
    monkeypatch.setattr(public_site, "_serve_give_page", hosted)
    monkeypatch.setattr(public_site, "secondary_pages", lambda cfg: pytest.fail("composed pages must use main's routing"))
    with_client = TestClient(app, base_url="https://" + host)
    try:
        assert with_client.get("/about").status_code == 200
        assert with_client.get("/offer").status_code == 404
        assert with_client.get("/faq").status_code == 404
        offer = with_client.get("/saturday-shave-club")
        assert offer.status_code == 200 and "OFFER" in offer.text
        assert 'href="https://church.example/saturday-shave-club"' in offer.text
        assert with_client.get("/give").text == "HOSTED GIVING"
    finally:
        with_client.close()
    xml = public_site._site_sitemap_xml("church", cfg, "church.example")
    assert "https://church.example/saturday-shave-club</loc>" in xml
    assert "/offer</loc>" not in xml and "/faq</loc>" not in xml and "/give</loc>" not in xml
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [custom_manual_site])
    monkeypatch.setattr(site_check, "secondary_pages", lambda cfg: pytest.fail("composed check must use main's paths"))
    assert site_check.site_pages("biz-1")[1] == [
        "https://church.example/", "https://church.example/about", "https://church.example/saturday-shave-club"]


@pytest.mark.parametrize("custom_domain", [False, True])
def test_manual_sermon_index_and_hosted_detail_paths_have_explicit_owners(monkeypatch, custom_manual_site, custom_domain):
    import asyncio
    import no_card_trial
    sermon_id = "b25fcb29-0837-4f7c-9d9a-2bfbcaf0bdee"
    hosted_paths = []

    async def visible(*args):
        return False

    async def augment(client, biz, slug, html, **kwargs):
        assert kwargs["manual"] is True
        return "MANUAL SERMON INDEX"

    async def hosted(client, biz, slug, path):
        hosted_paths.append(path)
        return public_site.HTMLResponse("HOSTED SERMON DETAIL")

    monkeypatch.setattr(no_card_trial, "site_hidden", visible)
    monkeypatch.setattr(public_site, "_augment_html", augment)
    monkeypatch.setattr(public_site, "_serve_sermons_page", hosted)
    serve = public_site._serve_site_by_custom_domain if custom_domain else public_site._serve_site_by_slug
    host = "church.example" if custom_domain else "church"
    assert asyncio.run(serve(host, "/sermons")).body.decode() == "MANUAL SERMON INDEX"
    assert asyncio.run(serve(host, "/sermons/" + sermon_id)).body.decode() == "HOSTED SERMON DETAIL"
    assert hosted_paths == ["/sermons/" + sermon_id]
    xml = public_site._site_sitemap_xml("church", custom_manual_site["site_config"], "church.example")
    assert xml.count("<loc>https://church.example/sermons</loc>") == 1


def test_manual_custom_preview_preserves_pv_gate_and_fallback(monkeypatch, custom_manual_site):
    import asyncio
    import no_card_trial
    seen = []

    async def blocked(client, biz, pv):
        seen.append((biz, pv))
        return pv != "team-token"

    async def offline(*args, **kwargs):
        assert kwargs["coming_soon"] is True
        return public_site.HTMLResponse("COMING SOON")

    async def home(slug, pv):
        return public_site.HTMLResponse("HOME " + pv)

    monkeypatch.setattr(no_card_trial, "preview_blocked", blocked)
    monkeypatch.setattr(public_site, "_render_offline_page", offline)
    assert asyncio.run(public_site.get_site_page_html("church", "visit")).body.decode() == "COMING SOON"
    allowed = asyncio.run(public_site.get_site_page_html("church", "visit", "team-token"))
    assert allowed.headers["X-Solutionist-Source"] == "manual-site"
    monkeypatch.setattr(public_site, "get_site_html", home)
    assert asyncio.run(public_site.get_site_page_html("church", "missing", "team-token")).body.decode() == "HOME team-token"
    assert seen == [("biz-1", None), ("biz-1", "team-token"), ("biz-1", "team-token")]


@pytest.mark.parametrize("custom_domain", [False, True])
def test_manual_page_cannot_bypass_no_card_public_gate(monkeypatch, custom_manual_site, custom_domain):
    import asyncio
    import no_card_trial

    async def hidden(*args):
        return True

    async def offline(*args, **kwargs):
        assert kwargs["coming_soon"] is True
        return public_site.HTMLResponse("COMING SOON")

    monkeypatch.setattr(no_card_trial, "site_hidden", hidden)
    monkeypatch.setattr(public_site, "_render_offline_page", offline)
    serve = public_site._serve_site_by_custom_domain if custom_domain else public_site._serve_site_by_slug
    assert asyncio.run(serve("church.example" if custom_domain else "church", "/sermons")).body.decode() == "COMING SOON"


@pytest.mark.parametrize("source,offer_href", [
    ("module-composer", "/saturday-shave-club"),
    ("manual", "/public/site/acme/saturday-shave-club"),
])
def test_home_preview_keeps_main_composed_offer_link_and_rewrites_manual_link(
        monkeypatch, custom_manual_site, source, offer_href):
    import asyncio
    from unittest.mock import AsyncMock

    custom_manual_site["html_content"] = (
        '<html><head></head><body><nav class="sxm-header-pagenav">'
        '<a href="/about">About</a><a href="/saturday-shave-club">Club</a>'
        '</nav></body></html>')
    cfg = custom_manual_site["site_config"]
    cfg.update(html_source=source, offer_page={"path": "/saturday-shave-club"})
    page_id = "offer" if source == "module-composer" else "saturday-shave-club"
    cfg["generated_pages"][page_id] = "OFFER"
    monkeypatch.setattr(public_site, "_use_smart_sites", lambda site: False)
    monkeypatch.setattr("no_card_trial.preview_blocked", AsyncMock(return_value=False))

    response = asyncio.run(public_site.get_site_html("acme"))
    body = response.body.decode()
    assert response.status_code == 200
    assert f'href="{offer_href}"' in body
    assert 'href="/public/site/acme/about"' in body
    if source == "module-composer":
        assert 'href="/public/site/acme/saturday-shave-club"' not in body
