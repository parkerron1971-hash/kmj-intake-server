"""The Love City Church site (sites/love-city-church/) builds clean.

Every page renders through build.py, home included; no build-time token is
left in a page; no recipient email address ever reaches the HTML (the old
SnapPages forms printed theirs in the page source); and while BUSINESS_ID
is a placeholder, site_sync can never install the site anywhere.
"""
from __future__ import annotations

import html.parser
import importlib.util
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_sync  # noqa: E402

SITE = os.path.join(ROOT, "sites", "love-city-church")
SERVE_TIME_TOKENS = {"BUSINESS_EMAIL", "PRODUCTS_SECTION", "GALLERY_SECTION", "TESTIMONIALS_SECTION"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
OLD_RECIPIENTS = ("cityofloveoutreach@gmail.com", "lovecitychurchmi@gmail.com",
                  "colmprayer@gmail.com", "kmccloudjrministries@gmail.com")


def _load_build():
    spec = importlib.util.spec_from_file_location("love_city_site_build", os.path.join(SITE, "build.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def build():
    return _load_build()


@pytest.fixture(scope="module")
def pages(build):
    return build.render_pages()


def test_render_pages_returns_every_page_and_home(build, pages):
    assert "home" in pages
    assert set(pages) == set(build.PAGES)
    for page_id in build.PAGES:
        assert os.path.isfile(os.path.join(SITE, f"{page_id}.html")), page_id


def test_no_build_time_tokens_are_left(pages):
    for name, page in pages.items():
        assert page.startswith("<!DOCTYPE html>"), name
        left = set(re.findall(r"\{\{([A-Z_]+)\}\}", page)) - SERVE_TIME_TOKENS
        assert not left, f"{name}: {sorted(left)}"
        # The platform fills these in place; without them it would append
        # sections before </body>.
        for token in ("PRODUCTS_SECTION", "GALLERY_SECTION", "TESTIMONIALS_SECTION"):
            assert "{{" + token + "}}" in page, f"{name}: {token}"


def test_the_inline_build_renders_too(build):
    inline = build.render_pages(inline=True)
    assert set(inline) == set(build.PAGES)
    assert all("/public/site-assets/" not in p for p in inline.values())


def test_no_recipient_email_is_in_any_page(pages):
    for name, page in pages.items():
        assert EMAIL_RE.findall(page) == [], name
        for addr in OLD_RECIPIENTS:
            assert addr not in page, f"{name}: {addr}"
        assert "mailto:{{BUSINESS_EMAIL}}" in page or "mailto:" not in page, name


def test_assets_are_served_from_the_site_asset_route(build, pages):
    for name, page in pages.items():
        for ref in re.findall(r'src="([^"]+\.webp[^"]*)"', page):
            assert ref.startswith(f"{build.API_BASE}/public/site-assets/love-city-church/"), (name, ref)


def test_every_asset_is_a_sensible_webp():
    names = os.listdir(os.path.join(SITE, "assets"))
    assert names
    for n in names:
        assert re.match(r"^[a-z0-9][a-z0-9_-]{0,63}\.webp$", n), n   # the asset route's own pattern
        assert os.path.getsize(os.path.join(SITE, "assets", n)) < 150_000, n


class _Audit(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.imgs_without_alt = []
        self.fields = []           # (tag, id, name, labelled inline or by aria-label)
        self.label_for = set()
        self.iframes_without_title = []
        self.in_label = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img" and "alt" not in a:
            self.imgs_without_alt.append(a.get("src", "")[:60])
        if tag == "iframe" and not a.get("title"):
            self.iframes_without_title.append(a.get("src"))
        if tag == "label":
            self.in_label += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit"):
            self.fields.append((tag, a.get("id"), a.get("name"), bool(a.get("aria-label")) or self.in_label > 0))

    def handle_endtag(self, tag):
        if tag == "label" and self.in_label:
            self.in_label -= 1


def test_images_have_alt_text_frames_have_titles_and_fields_have_labels(pages):
    for name, page in pages.items():
        audit = _Audit()
        audit.feed(page)
        assert audit.imgs_without_alt == [], name
        assert audit.iframes_without_title == [], name
        for tag, fid, fname, labelled in audit.fields:
            if fname == "website":      # the hidden field only bots fill in
                continue
            assert labelled or (fid and fid in audit.label_for), f"{name}: {tag} {fname} has no label"


def test_forms_post_through_the_one_submission_script(build, pages):
    for name, page in pages.items():
        if "data-church-form" in page:
            assert f"{build.API_BASE}/sites/{build.BUSINESS_ID}/contact-submit" in page, name
            assert page.count("/contact-submit") == 1, name
        assert 'action="' not in page, name     # nothing posts natively


def test_service_times_and_address_are_real_text(pages):
    for name, page in pages.items():
        for text in ("Sundays", "11am", "Thursdays", "6pm", "1084 Allen Ave", "Muskegon, MI 49442"):
            assert text in page, f"{name}: {text}"
    assert "We love." in pages["home"] and "Love City Church" in pages["home"]
    # Kevin: the midweek service is Thursday 6pm. The old site's Wednesday
    # time (and its "Refuel" name) must not come back.
    everything = "".join(pages.values())
    assert not re.search(r"Wednesdays?\W{0,3}(at\W)?\d", everything)
    assert "Refuel" not in everything


def test_every_internal_link_lands_on_a_page_the_site_builds(build, pages):
    for name, page in pages.items():
        for href in re.findall(r'href="(/[^"]*)"', page):
            path = href.split("#")[0].split("?")[0].strip("/")
            assert path == "" or path in build.PAGES, f"{name}: {href}"
            if "#" in href and path:
                anchor = href.split("#", 1)[1]
                assert f'id="{anchor}"' in pages[path], f"{name}: {href} has no target"


def test_the_placeholder_business_id_can_never_install(build, monkeypatch):
    monkeypatch.setenv("SITE_CHECK", "off")
    monkeypatch.setenv("SITE_ADOPT", "off")
    mod = next(m for m in site_sync.discover() if m.SLUG == "love-city-church")
    if not build.BUSINESS_ID.startswith("PLACEHOLDER"):
        pytest.skip("the church's real business id is set")
    import sb_clients
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda *a, **k: patches.append(a))

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    assert site_sync.sync_site(mod) == "no-row"

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [
        {"id": "row-1", "business_id": "3f1c2b9e-0000-4000-8000-000000000001",
         "html_content": "<html>someone else's</html>", "site_config": {}}])
    assert site_sync.sync_site(mod) == "wrong-business"
    assert patches == []
