# __tests__/test_findability_bundle.py
#
# The findability bundle (2026-08-02), from the site-builder audit:
# published sites had no sitemap, no robots.txt, returned 200 + the home
# page for EVERY unknown path (mass soft-404s), and — on a custom domain
# — told Google the canonical page was the platform subdomain, handing
# the ranking value of the domain the practitioner paid for to one they
# don't own.

import public_site as ps


# ─── Canonical: the domain they paid for wins ─────────────────────────

_HTML = ('<html><head><title>T</title>'
         '<link rel="canonical" href="https://slug.mysolutionist.app">'
         '<meta property="og:url" content="https://slug.mysolutionist.app">'
         '</head><body>hi</body></html>')


def test_canonical_uses_the_custom_domain_when_there_is_one():
    out = ps._inject_canonical(_HTML, "slug", "kmjcreate.com")
    assert 'href="https://kmjcreate.com"' in out
    assert "slug.mysolutionist.app" not in out


def test_canonical_falls_back_to_the_subdomain():
    out = ps._inject_canonical(_HTML, "slug", None)
    assert 'href="https://slug.mysolutionist.app"' in out


def test_exactly_one_canonical_survives():
    """The builder bakes one in at build time; serve time must REPLACE
    it, not add a second — two competing tags is the same as none."""
    out = ps._inject_canonical(_HTML, "slug", "kmjcreate.com")
    assert out.count("rel=\"canonical\"") == 1
    assert out.count("og:url") == 1


def test_secondary_pages_are_canonical_to_themselves():
    out = ps._inject_canonical(_HTML, "slug", "kmjcreate.com", "/about")
    assert 'href="https://kmjcreate.com/about"' in out


def test_public_origin_normalizes_a_messy_domain():
    assert ps._public_origin("s", "  KMJCreate.com ") == "https://kmjcreate.com"
    assert ps._public_origin("s", "/kmjcreate.com") == "https://kmjcreate.com"
    assert ps._public_origin("s", "") == "https://s.mysolutionist.app"


# ─── robots.txt ───────────────────────────────────────────────────────

def test_robots_points_at_the_sitemap_on_the_right_host():
    r = ps._site_robots_txt("slug", "kmjcreate.com")
    assert "Sitemap: https://kmjcreate.com/sitemap.xml" in r
    assert "User-agent: *" in r and "Allow: /" in r

    r2 = ps._site_robots_txt("slug", None)
    assert "Sitemap: https://slug.mysolutionist.app/sitemap.xml" in r2


# ─── sitemap.xml ──────────────────────────────────────────────────────

def test_sitemap_lists_home_and_real_secondary_pages_only():
    cfg = {"generated_pages": {"about": "<html>a</html>",
                               "services": "",            # built empty → excluded
                               "contact": "<html>c</html>"}}
    xml = ps._site_sitemap_xml("slug", cfg, None)
    assert "<loc>https://slug.mysolutionist.app/</loc>" in xml
    assert "<loc>https://slug.mysolutionist.app/about</loc>" in xml
    assert "<loc>https://slug.mysolutionist.app/contact</loc>" in xml
    # A sitemap that lists a page which 404s is worse than no sitemap.
    assert "/services" not in xml


def test_sitemap_is_wellformed_and_uses_the_custom_domain():
    import xml.etree.ElementTree as ET
    xml = ps._site_sitemap_xml("slug", {"generated_pages": {"about": "x"}},
                               "kmjcreate.com")
    root = ET.fromstring(xml)          # raises if malformed
    assert root.tag.endswith("urlset")
    assert "https://kmjcreate.com/about" in xml
    assert "mysolutionist.app" not in xml


def test_single_page_site_gets_a_valid_one_url_sitemap():
    import xml.etree.ElementTree as ET
    xml = ps._site_sitemap_xml("slug", {}, None)
    ET.fromstring(xml)
    assert xml.count("<loc>") == 1


# ─── real 404s ────────────────────────────────────────────────────────

def test_not_found_page_is_a_real_404_and_noindexes_itself():
    resp = ps._not_found_page("slug", "Clean Quick", "#2E7DFF", None)
    assert resp.status_code == 404
    body = resp.body.decode()
    assert 'name="robots" content="noindex"' in body
    # Never a dead end — it always offers the way home.
    assert 'href="https://slug.mysolutionist.app/"' in body
    assert "Clean Quick" in body and "#2E7DFF" in body


def test_not_found_sends_custom_domain_visitors_home_to_that_domain():
    body = ps._not_found_page("slug", "X", "#000", "kmjcreate.com").body.decode()
    assert 'href="https://kmjcreate.com/"' in body


# ─── routing tables ───────────────────────────────────────────────────

def test_clean_page_paths_map_to_generated_page_ids():
    assert ps._SITE_PAGE_PATHS == {"/about": "about",
                                   "/services": "services",
                                   "/contact": "contact"}


def test_custom_domain_serves_every_door_the_subdomain_does():
    """A practitioner who connects their own domain must not silently
    lose /book — it was missing here while present on the subdomain."""
    import inspect
    src = inspect.getsource(ps._serve_site_by_custom_domain)
    for door in ('"/book"', '"/give"', '"/events"', '"/academy"',
                 '"/robots.txt"', '"/sitemap.xml"'):
        assert door in src, f"custom-domain path is missing {door}"


def test_both_serve_paths_pass_the_custom_domain_into_augment():
    """The canonical bug was _augment_html(html, slug) — dropping the
    argument the injector already accepted."""
    import inspect
    for fn in (ps._serve_site_by_slug, ps._serve_site_by_custom_domain):
        src = inspect.getsource(fn)
        assert "custom_domain=" in src, f"{fn.__name__} drops custom_domain"
