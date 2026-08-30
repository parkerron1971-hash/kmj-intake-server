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


# ─── Routing ──────────────────────────────────────────────────────────

def test_empty_archive_404s_rather_than_serving_a_thin_page(client, monkeypatch):
    async def _none():
        return []
    monkeypatch.setattr(public_site, "_platform_news_posts", _none)
    assert _apex(client, "/news").status_code == 404


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
