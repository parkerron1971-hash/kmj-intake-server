"""The platform's own news feed, on the platform's own domain.

site_news.py renders a feed for a PRACTITIONER's site. The company's
launch writing needs the same thing at mysolutionist.app/news instead —
the apex, where every CTA on the marketing site already points — rather
than on a bare subdomain with no inbound links.

What these pin:
  • the marketing shell renders it (nav, footer, tokens), not the
    practitioner shell;
  • a post's own address is canonical to itself, so the archive and the
    post never claim to be the same page;
  • post text is escaped — a post is data, not markup;
  • the archive 404s while empty and the sitemap only advertises it once
    it is real, so the two can never disagree;
  • robots.txt and sitemap.xml exist on the apex at all, which they did
    not before: both answered 404 on mysolutionist.app.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import marketing_pages
import public_site
import site_news


RAW_POSTS = [
    {"id": "a", "title": "Publish to your own site",
     "body": "The first paragraph.\n\nA second one with <b>markup</b> in it.",
     "published_at": "2026-08-29T12:00:00Z"},
    {"id": "b", "title": "Café hours",
     "body": "Body two.", "published_at": "2026-08-28T12:00:00Z"},
]


@pytest.fixture
def posts():
    return site_news.normalize_posts(RAW_POSTS)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(public_site.router)
    return TestClient(app)


def _apex(client, path):
    return client.get(path, headers={"Host": "mysolutionist.app"})


# ─── Rendering ────────────────────────────────────────────────────────

def test_index_renders_in_the_marketing_shell(posts):
    html = marketing_pages.render_news_index(posts)
    # The shell's own furniture — this is the marketing site, not a
    # practitioner site that happens to share a renderer.
    assert "nav-cta" in html
    assert "The Solutionist System" in html
    assert '<link rel="canonical" href="https://mysolutionist.app/news">' in html


def test_index_links_every_post_at_its_own_address(posts):
    html = marketing_pages.render_news_index(posts)
    for post in posts:
        assert f'href="/news/{post["slug"]}"' in html


def test_post_page_is_canonical_to_itself(posts):
    html = marketing_pages.render_news_post(posts[0])
    url = "https://mysolutionist.app/news/publish-to-your-own-site"
    assert f'<link rel="canonical" href="{url}">' in html
    # ...and not to the archive, which would tell Google the post is a
    # duplicate of a page it does not appear on in full.
    assert '<link rel="canonical" href="https://mysolutionist.app/news">' not in html


def test_post_text_is_escaped_not_rendered(posts):
    html = marketing_pages.render_news_post(posts[0])
    assert "<b>markup</b>" not in html
    assert "&lt;b&gt;markup&lt;/b&gt;" in html


def test_post_carries_article_schema(posts):
    html = marketing_pages.render_news_post(posts[0])
    assert 'application/ld+json' in html
    assert '"@type": "Article"' in html
    assert '"datePublished"' in html


def test_accented_title_keeps_a_readable_slug(posts):
    assert posts[1]["slug"] == "cafe-hours"


def test_paragraph_helper_leaves_styling_to_the_caller():
    # An inline style would beat the marketing stylesheet, so the public
    # helper carries none while the practitioner shell still gets one.
    assert site_news.paragraphs("one") == "<p>one</p>"
    assert 'style="margin:0 0 18px;"' in site_news._paragraphs("one")


# ─── The read itself ──────────────────────────────────────────────────
# Every routing test below monkeypatches _platform_news_posts, which is
# exactly why the first version shipped broken: nothing exercised the
# query. It used the anon reader, RLS on businesses calls
# is_business_member which anon may not execute, the read failed 42501,
# and _sb turns any 4xx into None — so the archive 404ed with a
# published post in the row, looking identical to "nothing posted yet".

def test_platform_news_reads_with_the_service_role(monkeypatch):
    seen = {"anon": 0, "service": []}

    async def fake_anon(client, path):
        seen["anon"] += 1
        return None

    async def fake_service(client, path):
        seen["service"].append(path)
        return [{"news": [{"title": "Hello", "body": "Words.",
                           "published_at": "2026-08-30T00:00:00Z"}]}]

    monkeypatch.setattr(public_site, "_sb", fake_anon)
    monkeypatch.setattr(public_site, "_sb_service", fake_service)

    posts = asyncio.run(public_site._platform_news_posts())

    assert seen["anon"] == 0, "the anon reader cannot see this row at all"
    assert len(seen["service"]) == 1
    assert [p["title"] for p in posts] == ["Hello"]


def test_platform_news_asks_only_for_the_posts(monkeypatch):
    """Bypassing RLS is worth doing narrowly. The same settings blob
    holds the platform's Stripe state, and a select of the whole thing
    would drag it into a request that only renders posts."""
    captured = {}

    async def fake_service(client, path):
        captured["path"] = path
        return []

    monkeypatch.setattr(public_site, "_sb_service", fake_service)
    asyncio.run(public_site._platform_news_posts())

    path = captured["path"]
    assert "platform_books" in path, "must select the platform's own row"
    assert "settings->website_content->news" in path
    assert "select=settings&" not in path and not path.endswith("select=settings")


# ─── Routing ──────────────────────────────────────────────────────────

def test_empty_archive_renders_noindex_rather_than_404ing(client, monkeypatch):
    """It used to 404 to keep a thin page out of search. The footer now
    links here from every page, so a 404 would be a dead end — noindex
    says the same thing to a crawler without withholding the page from
    a person who followed the link."""
    async def _none():
        return []
    monkeypatch.setattr(public_site, "_platform_news_posts", _none)
    r = _apex(client, "/news")
    assert r.status_code == 200
    assert '<meta name="robots" content="noindex">' in r.text


def test_a_real_archive_is_indexable(client, monkeypatch, posts):
    """The noindex belongs to the empty state alone — leaving it on once
    posts exist would quietly delist the whole point of the feature."""
    async def _posts():
        return posts
    monkeypatch.setattr(public_site, "_platform_news_posts", _posts)
    r = _apex(client, "/news")
    assert r.status_code == 200
    assert "noindex" not in r.text


def test_every_page_links_to_the_news_archive(client, monkeypatch):
    """The footer link is unconditional, which is only safe because the
    empty archive resolves. These two facts have to move together."""
    async def _none():
        return []
    monkeypatch.setattr(public_site, "_platform_news_posts", _none)
    for path in ("/features", "/about", "/news"):
        assert '<a href="/news">News</a>' in _apex(client, path).text, path


def test_archive_serves_once_there_is_something_to_read(client, monkeypatch, posts):
    async def _posts():
        return posts
    monkeypatch.setattr(public_site, "_platform_news_posts", _posts)
    r = _apex(client, "/news")
    assert r.status_code == 200
    assert "What we shipped" in r.text


def test_unknown_post_is_a_real_404(client, monkeypatch, posts):
    async def _posts():
        return posts
    monkeypatch.setattr(public_site, "_platform_news_posts", _posts)
    # Serving the archive here would answer 200 for every typo and
    # invite search to index endless duplicates of it.
    assert _apex(client, "/news/no-such-post").status_code == 404


# ─── robots.txt + sitemap.xml ─────────────────────────────────────────

def test_apex_robots_exists_and_points_at_the_sitemap(client):
    r = _apex(client, "/robots.txt")
    assert r.status_code == 200
    assert "Sitemap: https://mysolutionist.app/sitemap.xml" in r.text


def test_sitemap_lists_the_marketing_pages(client, monkeypatch):
    async def _none():
        return []
    monkeypatch.setattr(public_site, "_platform_news_posts", _none)
    r = _apex(client, "/sitemap.xml")
    assert r.status_code == 200
    for path in ("/features", "/compare", "/get-started"):
        assert f"<loc>https://mysolutionist.app{path}</loc>" in r.text


def test_sitemap_hides_news_until_a_post_exists(client, monkeypatch):
    async def _none():
        return []
    monkeypatch.setattr(public_site, "_platform_news_posts", _none)
    assert "/news" not in _apex(client, "/sitemap.xml").text


def test_sitemap_lists_news_and_every_post_once_they_exist(client, monkeypatch, posts):
    async def _posts():
        return posts
    monkeypatch.setattr(public_site, "_platform_news_posts", _posts)
    body = _apex(client, "/sitemap.xml").text
    assert "<loc>https://mysolutionist.app/news</loc>" in body
    for post in posts:
        assert f"<loc>https://mysolutionist.app/news/{post['slug']}</loc>" in body


def test_every_sitemap_path_is_a_route_that_exists(client, monkeypatch):
    """A sitemap that lists a page which 404s is worse than no sitemap.
    The marketing paths are hardcoded, so nothing but a test stops one
    from outliving the page it names."""
    async def _none():
        return []
    monkeypatch.setattr(public_site, "_platform_news_posts", _none)
    for path, _priority in public_site._MARKETING_SITEMAP_PATHS:
        r = _apex(client, path)
        assert r.status_code == 200, f"{path} is in the sitemap but answers {r.status_code}"
