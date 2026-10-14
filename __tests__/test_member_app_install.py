"""
test_member_app_install.py — the member page installs like an app.

Pins the manifest (scope and start inside /my, standalone, the church's
name and colours), real PNG icons at the sizes it names, a service worker
that serves pages from the network, keeps only the offline page and has
NO push handler (member notifications are still Kevin's open decision),
and that every member page links them.
"""
from __future__ import annotations

import json

import pytest

import member_app_install as I

BIZ = {"id": "11111111-1111-1111-1111-111111111111", "name": "Love City Church",
       "type": "church", "settings": {}}


def test_manifest_is_the_churchs_and_stays_inside_my():
    m = I.manifest(BIZ, None)
    assert m["name"] == "Love City Church" and m["short_name"] == "Love City"
    assert m["start_url"] == "/my" and m["scope"] == "/my" and m["display"] == "standalone"
    assert m["theme_color"].startswith("#") and m["background_color"] == m["theme_color"]
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}
    assert any("maskable" in i["purpose"] for i in m["icons"])


@pytest.mark.parametrize("name,short", [
    ("Grace", "Grace"), ("Love City Church", "Love City"),
    ("The Church of the Living God", "The Church"), ("Supercalifragilistic Church", "SC"), ("", "Church")])
def test_short_names_fit_under_an_icon(name, short):
    assert I.short_name(name) == short and len(I.short_name(name)) <= 12


@pytest.mark.parametrize("size", I.ICON_SIZES)
def test_icons_are_real_pngs_of_the_size_named(size):
    from PIL import Image
    import io
    png = I.icon_png(BIZ, None, size)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(png)).size == (size, size)


def test_every_asset_is_served_with_its_type():
    m = I.serve_asset(BIZ, None, "/my/manifest.webmanifest")
    assert m.media_type == "application/manifest+json" and json.loads(m.body)["scope"] == "/my"
    sw = I.serve_asset(BIZ, None, "/my/sw.js")
    assert sw.media_type == "text/javascript"
    assert sw.headers["service-worker-allowed"] == "/my" and sw.headers["cache-control"] == "no-cache"
    assert I.serve_asset(BIZ, None, "/my/icon-192.png").media_type == "image/png"
    assert I.serve_asset(BIZ, None, "/my/icon-999.png") is None


def test_the_service_worker_never_caches_pages():
    assert "fetch(e.request).catch" in I.SW_JS          # network first
    assert "caches.match(OFFLINE)" in I.SW_JS           # only the offline page
    assert "e.request.mode !== 'navigate'" in I.SW_JS   # leaves other requests alone


def test_the_service_worker_shows_a_push_and_only_opens_member_pages():
    # Kevin said yes to member notifications (2026-10-14); member_push.py
    # decides who gets what.
    assert "self.addEventListener('push'" in I.SW_JS
    assert "showNotification" in I.SW_JS and "notificationclick" in I.SW_JS
    # A push can only open this app's own pages, never another site.
    assert "d.url.indexOf('/my') === 0" in I.SW_JS
    assert "const url = ok ? d.url : '/my';" in I.SW_JS


def test_head_tags_link_the_manifest_and_iphone_icon():
    tags = I.head_tags(BIZ)
    assert '<link rel="manifest" href="/my/manifest.webmanifest">' in tags
    assert '<link rel="apple-touch-icon" href="/my/icon-180.png">' in tags
    assert 'content="Love City"' in tags


def test_install_card_starts_hidden_and_offers_both_ways():
    card = I.install_card("Love City Church")
    assert 'id="mb-install" hidden' in card
    assert "beforeinstallprompt" in card and "Add to Home Screen" in card
    assert "mb-install-dismissed" in card and "display-mode: standalone" in card


def test_every_member_page_carries_the_tags_and_registers_the_worker():
    import member_portal
    html = member_portal.render_signin(BIZ, None)
    assert '<link rel="manifest" href="/my/manifest.webmanifest">' in html
    assert "navigator.serviceWorker.register('/my/sw.js',{scope:'/my'})" in html


def test_assets_are_served_without_sign_in(monkeypatch):
    import asyncio
    import member_portal
    from starlette.requests import Request
    church = {"business": dict(BIZ, settings={"member_portal": {"enabled": True}}), "site": None}
    monkeypatch.setattr(member_portal, "_church_for_request", lambda r: church)
    monkeypatch.setattr(member_portal, "portal_active", lambda b: True)
    monkeypatch.setattr(member_portal, "_session_for",
                        lambda *a: (_ for _ in ()).throw(AssertionError("no session needed")))
    req = Request({"type": "http", "method": "GET", "path": "/my/manifest.webmanifest",
                   "query_string": b"", "headers": []})
    resp = asyncio.run(member_portal.serve(req, "/my/manifest.webmanifest"))
    assert resp.media_type == "application/manifest+json"
    resp = asyncio.run(member_portal.serve(req, "/my/offline"))
    assert b"You're offline" in resp.body or "You&#x27;re offline".encode() in resp.body


def test_assets_404_when_the_member_page_is_off(monkeypatch):
    import asyncio
    import member_portal
    from starlette.requests import Request
    monkeypatch.setattr(member_portal, "_church_for_request", lambda r: {"business": BIZ, "site": None})
    monkeypatch.setattr(member_portal, "portal_active", lambda b: False)
    monkeypatch.setattr(member_portal, "_previewing", lambda r, b: False)
    req = Request({"type": "http", "method": "GET", "path": "/my/sw.js", "query_string": b"", "headers": []})
    resp = asyncio.run(member_portal.serve(req, "/my/sw.js"))
    assert resp.status_code == 404
