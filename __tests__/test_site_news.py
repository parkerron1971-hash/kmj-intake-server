# __tests__/test_site_news.py
#
# The news feed is the one publishing channel with no gatekeeper, which
# makes it the one whose failures nobody else will report to us: no API
# returns an error, no review gets denied, the page is just quietly
# wrong. So the renderers are tested directly.

import json
import re

import site_news as sn


def _post(**kw):
    base = {"id": "1", "title": "We are open late", "body": "Thursdays until 9.",
            "published_at": "2026-08-20T14:00:00Z"}
    base.update(kw)
    return base


# ─── normalize_posts ────────────────────────────────────────────────

def test_a_headline_with_no_body_is_dropped():
    """An empty post still gets a real URL and a real page. That is
    worse for search than not existing."""
    posts = sn.normalize_posts([_post(), {"title": "Coming soon", "body": "  "}])
    assert [p["title"] for p in posts] == ["We are open late"]


def test_newest_first_and_undated_posts_sort_last_without_crashing():
    posts = sn.normalize_posts([
        _post(id="old", title="Older", published_at="2026-01-02T00:00:00Z"),
        _post(id="none", title="Undated", published_at=None),
        _post(id="new", title="Newer", published_at="2026-08-01T00:00:00Z"),
    ])
    assert [p["id"] for p in posts] == ["new", "old", "none"]


def test_two_posts_with_the_same_title_get_different_urls():
    """Both would otherwise resolve to /news/were-hiring and one would
    be unreachable — the frontend can't see the whole list when it
    writes, so uniqueness has to happen here."""
    posts = sn.normalize_posts([
        _post(id="a", title="We're hiring", published_at="2026-08-02T00:00:00Z"),
        _post(id="b", title="We're hiring", published_at="2026-01-02T00:00:00Z"),
    ])
    slugs = [p["slug"] for p in posts]
    assert len(set(slugs)) == 2, slugs
    assert sn.find_post(posts, slugs[0])["id"] == "a"
    assert sn.find_post(posts, slugs[1])["id"] == "b"


def test_accents_fold_instead_of_vanishing():
    assert sn.slugify("Café hours") == "cafe-hours"


def test_a_title_of_pure_punctuation_still_yields_a_usable_slug():
    assert sn.slugify("!!!") == "post"


def test_garbage_in_settings_is_not_a_500():
    assert sn.normalize_posts(None) == []
    assert sn.normalize_posts({"news": []}) == []
    assert sn.normalize_posts(["a string", 7, None]) == []


def test_an_unparseable_date_does_not_drop_the_post():
    posts = sn.normalize_posts([_post(published_at="last Tuesday")])
    assert len(posts) == 1
    assert posts[0]["published_at"] is None


# ─── rendering ──────────────────────────────────────────────────────

ORIGIN = "https://macnificent.mysolutionist.app"


def test_the_practitioners_words_are_escaped_not_executed():
    posts = sn.normalize_posts([_post(body="<script>alert(1)</script> come by")])
    html = sn.render_post_page(posts[0], business_name="Mac", origin=ORIGIN)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_a_post_page_carries_its_own_canonical_and_description():
    posts = sn.normalize_posts([_post()])
    html = sn.render_post_page(posts[0], business_name="Mac", origin=ORIGIN)
    assert f'<link rel="canonical" href="{ORIGIN}/news/we-are-open-late" />' in html
    assert '<meta name="description" content="Thursdays until 9."' in html


def test_article_schema_is_valid_json_and_names_the_business():
    posts = sn.normalize_posts([_post()])
    html = sn.render_post_page(posts[0], business_name="MaCnificent", origin=ORIGIN)
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert block, "no JSON-LD emitted"
    data = json.loads(block.group(1).replace("<\\/", "</"))
    assert data["@type"] == "Article"
    assert data["publisher"]["name"] == "MaCnificent"
    assert data["datePublished"].startswith("2026-08-20")


def test_a_closing_script_tag_in_the_body_cannot_break_out_of_the_json():
    """Asserts the escaped form is present rather than only that the
    JSON parses: without the escape the regex below stops at the body's
    own </script> and the payload happens to still be valid JSON, so a
    parse-only check would go on passing while the document broke."""
    posts = sn.normalize_posts([_post(body="Ends with </script> in the text.")])
    html = sn.render_post_page(posts[0], business_name="Mac", origin=ORIGIN)
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert block, "no JSON-LD emitted"
    payload = block.group(1)
    # The escape is what keeps the block open to its real end.
    assert "<\\/script>" in payload, "closing tag was not escaped"
    assert "</script>" not in payload
    data = json.loads(payload.replace("<\\/", "</"))
    assert "</script>" in data["description"]


def test_the_listing_links_every_post_to_its_own_page():
    posts = sn.normalize_posts([_post(id="a", title="One"), _post(id="b", title="Two")])
    html = sn.render_listing_page(posts, business_name="Mac", origin=ORIGIN)
    assert f'href="{ORIGIN}/news/one"' in html
    assert f'href="{ORIGIN}/news/two"' in html


def test_an_empty_feed_renders_a_real_page_not_a_blank_one():
    """The site links here, so the URL exists whether or not anything
    has been written yet."""
    html = sn.render_listing_page([], business_name="Mac", origin=ORIGIN)
    assert "Nothing posted yet" in html
    assert "<title>" in html


def test_every_page_is_responsive():
    posts = sn.normalize_posts([_post()])
    for html in (sn.render_listing_page(posts, business_name="M", origin=ORIGIN),
                 sn.render_post_page(posts[0], business_name="M", origin=ORIGIN)):
        assert 'name="viewport"' in html
        assert "@media(max-width:600px)" in html


def test_blank_lines_become_paragraphs_and_single_breaks_are_kept():
    posts = sn.normalize_posts([_post(body="First para.\n\nSecond para.\nSame para.")])
    html = sn.render_post_page(posts[0], business_name="M", origin=ORIGIN)
    assert html.count("<p style=\"margin:0 0 18px;\">") == 2
    assert "Second para.<br />Same para." in html


def test_summary_cuts_on_a_word_boundary():
    body = "word " * 100
    out = sn.summarize(body)
    assert len(out) <= 181
    assert not out.rstrip("…").endswith("wor")


def test_the_date_format_does_not_depend_on_the_host_platform():
    """`%-d` is glibc-only. Rendering must not raise on Windows."""
    posts = sn.normalize_posts([_post()])
    html = sn.render_post_page(posts[0], business_name="M", origin=ORIGIN)
    assert "2026" in html


# ─── routing ────────────────────────────────────────────────────────

def test_news_routes_are_registered_before_the_page_path_catch_all():
    """FastAPI matches in registration order. Declared after the
    catch-all, '/news' would be handed to it, find no generated page by
    that id, and fall back to serving the HOME page — a 200 with the
    wrong content, which no error log would ever report.
    """
    import public_site as ps

    paths = [getattr(r, "path", "") for r in ps.router.routes]
    assert "/public/site/{slug}/news" in paths, "news index route missing"
    assert "/public/site/{slug}/news/{post_slug}" in paths, "news post route missing"
    assert paths.index("/public/site/{slug}/news") < paths.index("/public/site/{slug}/{page_path}")
