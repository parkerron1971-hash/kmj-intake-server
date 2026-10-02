# __tests__/test_sermons_public.py
#
# The public sermon library (sermons_public.py + public_site._serve_sermons_page).
# Pins:
#   1. video links: YouTube (watch / youtu.be / live / shorts), Vimeo,
#      Loom and Facebook play in the page; anything else becomes a plain
#      link; nothing but https is ever embedded
#   2. drafts never appear — not on the list, not by their own address
#   3. the list: newest message first with its player, then each series
#      (newest series first), then messages outside a series
#   4. everything a church typed is escaped
#   5. the route: nothing published → 404; an unknown or malformed id →
#      404; a published one → 200

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import public_site
import sermons_public as sp

BIZ = {"id": "b1", "name": "Rivers of Living Water", "settings": {}}
S1, S2, S3, S4 = ("aaaaaaaa-0000-0000-0000-00000000000" + str(i) for i in range(1, 5))
SER = "bbbbbbbb-0000-0000-0000-000000000001"
SERIES = [{"id": SER, "title": "Romans: Grace Upon Grace", "description": "Eight weeks in Romans."}]


def sermon(i, **k):
    return {"id": i, "series_id": None, "title": f"Message {i[-1]}", "preached_on": "2026-09-27", "speaker": "Pastor Dana",
            "scripture": "Romans 5:1-11", "summary": "", "questions": "", "video_url": "", "audio_url": "",
            "published": True, **k}


# ── 1. video links ───────────────────────────────────────────────────

@pytest.mark.parametrize("url,src", [
    ("https://www.youtube.com/watch?v=abc123XYZ&t=10", "https://www.youtube-nocookie.com/embed/abc123XYZ"),
    ("https://youtu.be/abc123XYZ?si=x", "https://www.youtube-nocookie.com/embed/abc123XYZ"),
    ("https://www.youtube.com/live/abc123XYZ", "https://www.youtube-nocookie.com/embed/abc123XYZ"),
    ("https://youtube.com/shorts/abc123XYZ", "https://www.youtube-nocookie.com/embed/abc123XYZ"),
    ("https://vimeo.com/123456789", "https://player.vimeo.com/video/123456789"),
    ("https://www.loom.com/share/abcdef", "https://www.loom.com/embed/abcdef"),
])
def test_known_hosts_play_in_the_page(url, src):
    assert sp.video_embed_src(url) == src


def test_facebook_video_embeds_through_its_plugin():
    src = sp.video_embed_src("https://www.facebook.com/riverschurch/videos/1234567890/")
    assert src.startswith("https://www.facebook.com/plugins/video.php?")
    assert "href=https%3A%2F%2Fwww.facebook.com%2Friverschurch%2Fvideos%2F1234567890%2F" in src


@pytest.mark.parametrize("url", ["http://youtu.be/abc", "javascript:alert(1)", "https://evil.example/youtube.com/watch?v=x",
                                 "https://vimeo.com/not-a-number", ""])
def test_nothing_else_is_embedded(url):
    assert sp.video_embed_src(url) == ""


def test_an_unknown_host_is_a_plain_link():
    html = sp.player_html(sermon(S1, video_url="https://churchstreams.example/week1"))
    assert "<iframe" not in html and 'href="https://churchstreams.example/week1"' in html


def test_audio_uses_the_browser_player():
    assert '<audio class="sm-audio" controls' in sp.player_html(sermon(S1, audio_url="https://cdn.example/w1.mp3"))


# ── 2. drafts ────────────────────────────────────────────────────────

def test_drafts_never_listed():
    html = sp.render_library(BIZ, [sermon(S1, title="Draft talk", published=False), sermon(S2, title="Live one")],
                             SERIES, "https://x/sermons")
    assert "Draft talk" not in html and "Live one" in html


# ── 3. the list ──────────────────────────────────────────────────────

def test_list_leads_with_the_newest_then_series_then_loose():
    sermons = [sermon(S1, title="Newest", preached_on="2026-09-27", series_id=SER, video_url="https://youtu.be/new1"),
               sermon(S2, title="Older in series", preached_on="2026-09-20", series_id=SER),
               sermon(S3, title="Standalone", preached_on="2026-09-13")]
    html = sp.render_library(BIZ, sermons, SERIES, "https://x/sermons")
    assert html.index("Latest message") < html.index("Newest") < html.index("Romans: Grace Upon Grace") < html.index("More messages")
    assert "youtube-nocookie.com/embed/new1" in html
    assert "Eight weeks in Romans." in html
    assert "Standalone" in html


def test_one_sermon_page_shows_questions_and_the_rest_of_its_series():
    sermons = [sermon(S1, series_id=SER, questions="1. What did grace cost?"), sermon(S2, title="Week two", series_id=SER),
               sermon(S3, title="Hidden draft", series_id=SER, published=False)]
    html = sp.render_sermon(BIZ, sermons[0], sermons, SERIES, "https://x/sermons/" + S1)
    assert "For your group this week" in html and "What did grace cost?" in html
    assert "More in Romans: Grace Upon Grace" in html and "Week two" in html and "Hidden draft" not in html


# ── 4. escaping ──────────────────────────────────────────────────────

def test_everything_typed_is_escaped():
    evil = '<script>alert(1)</script>'
    html = sp.render_sermon({**BIZ, "name": evil}, sermon(S1, title=evil, summary=evil, questions=evil, speaker=evil),
                            [], [], "https://x")
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


# ── 5. the route ─────────────────────────────────────────────────────

def _serve(monkeypatch, sermons, path):
    async def fake(client, p):
        if p.startswith("/businesses"):
            return [BIZ]
        if p.startswith("/business_sites"):
            return []
        if p.startswith("/sermons"):
            assert "published=eq.true" in p  # drafts are never even read
            return [s for s in sermons if s["published"]]
        if p.startswith("/sermon_series"):
            return SERIES
        return []
    monkeypatch.setattr(public_site, "_sb_service", fake)
    return asyncio.run(public_site._serve_sermons_page(None, "b1", "rivers", path))


def test_route_nothing_published_is_404(monkeypatch):
    assert _serve(monkeypatch, [sermon(S1, published=False)], "/sermons").status_code == 404


def test_route_list_and_one(monkeypatch):
    sermons = [sermon(S1), sermon(S2, published=False)]
    assert _serve(monkeypatch, sermons, "/sermons").status_code == 200
    assert _serve(monkeypatch, sermons, f"/sermons/{S1}").status_code == 200
    assert _serve(monkeypatch, sermons, f"/sermons/{S2}").status_code == 404   # a draft by its address
    assert _serve(monkeypatch, sermons, "/sermons/not-an-id").status_code == 404
