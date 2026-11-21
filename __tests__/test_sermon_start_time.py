# __tests__/test_sermon_start_time.py
#
# A YouTube link's own start time is kept (sermons_public.youtube_start), so
# the church's team can paste a link that starts at the sermon. Pins:
#   - t= or start= (seconds, 95s, 1h22m5s, 82m), in the query or after #, on
#     watch, youtu.be, live and embed links; anything else is no start;
#   - the embed carries it as ?start=N (every look: the public page, today's
#     member page, the new look's message page and so the mini player, which
#     plays that same frame);
#   - in the new look, where the member left off still wins; the start is
#     always the last parameter (&start=N), where the page's script looks.

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_lumen_watch as mlw
import sermons_public as sp
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_give import church  # noqa: F401  (the fixture)
from test_member_lumen_watch import M, _cut, _get, _places, watch  # noqa: F401  (the fixture)

VID = "AjrqJXkVIcQ"
NOCOOKIE = f"https://www.youtube-nocookie.com/embed/{VID}"


@pytest.mark.parametrize("url,at", [
    (f"https://www.youtube.com/watch?v={VID}&t=95", 95),
    (f"https://www.youtube.com/watch?v={VID}&t=95s", 95),
    (f"https://www.youtube.com/watch?t=1h22m5s&v={VID}", 4925),
    (f"https://www.youtube.com/watch?v={VID}&t=82m", 4920),
    (f"https://m.youtube.com/watch?v={VID}&t=1h", 3600),
    (f"https://youtu.be/{VID}?t=3725", 3725),
    (f"https://youtu.be/{VID}?si=abc&t=61", 61),
    (f"https://www.youtube.com/live/{VID}?si=abc&t=2700", 2700),
    (f"https://www.youtube.com/embed/{VID}?start=30", 30),
    (f"https://www.youtube.com/watch?v={VID}#t=45s", 45),
    (f"https://www.youtube.com/watch?v={VID}&start=12", 12),
    (f"https://www.youtube.com/watch?v={VID}", 0),
    (f"https://www.youtube.com/watch?v={VID}&t=", 0),
    (f"https://www.youtube.com/watch?v={VID}&t=0", 0),
    (f"https://www.youtube.com/watch?v={VID}&t=abc", 0),
    (f"https://www.youtube.com/watch?v={VID}&t=-5", 0),
    (f"https://www.youtube.com/watch?v={VID}&t=99999999", 0),
    (f"https://www.youtube.com/watch?v={VID}&t=1h2h", 0),
    ("https://vimeo.com/123456#t=30s", 0),
    ("https://example.com/watch?v=x&t=30", 0),
    ("", 0),
])
def test_the_links_own_start(url, at):
    assert sp.youtube_start(url) == at


@pytest.mark.parametrize("url,src", [
    (f"https://www.youtube.com/watch?v={VID}&t=1h22m5s", f"{NOCOOKIE}?start=4925"),
    (f"https://youtu.be/{VID}?t=95", f"{NOCOOKIE}?start=95"),
    (f"https://www.youtube.com/live/{VID}?t=2700", f"{NOCOOKIE}?start=2700"),
    (f"https://www.youtube.com/embed/{VID}?start=30", f"{NOCOOKIE}?start=30"),
    (f"https://www.youtube.com/watch?v={VID}", NOCOOKIE),
    ("https://vimeo.com/123456789#t=30s", "https://player.vimeo.com/video/123456789"),
])
def test_the_embed_carries_it(url, src):
    assert sp.video_embed_src(url) == src


def test_the_public_page_and_todays_player_start_there():
    s = {"id": "x", "title": "Love Out Loud", "video_url": f"https://www.youtube.com/watch?v={VID}&t=95"}
    assert f'<iframe src="{NOCOOKIE}?start=95"' in sp.player_html(s)


@pytest.mark.parametrize("src,at,want", [
    (f"{NOCOOKIE}?start=95", 0, f"{NOCOOKIE}?enablejsapi=1&rel=0&playsinline=1&start=95"),     # the link's start
    (f"{NOCOOKIE}?start=95", 697, f"{NOCOOKIE}?enablejsapi=1&rel=0&playsinline=1&start=697"),  # hers wins
    (NOCOOKIE, 697, f"{NOCOOKIE}?enablejsapi=1&rel=0&playsinline=1&start=697"),
    (NOCOOKIE, 0, f"{NOCOOKIE}?enablejsapi=1&rel=0&playsinline=1"),
    ("https://player.vimeo.com/video/1", 40, "https://player.vimeo.com/video/1#t=40s"),
])
def test_where_she_left_off_wins(src, at, want):
    got = mlw._with_start(src, at)
    assert got == want and got.count("start=") <= 1


def _frame(html):
    pv = _cut(html, '<div class="lw-pv', '<div class="lw-pinfo">')
    return re.search(r"<iframe[^>]*>", pv).group(0)


def test_the_message_page_starts_at_the_sermon(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"]["sermons"][0]["video_url"] = f"https://www.youtube.com/watch?v={VID}&t=1h2m"
    frame = _frame(_get(fake, monkeypatch, f"/my/sermons/{M[0]}"))
    assert f'src="{NOCOOKIE}?enablejsapi=1&amp;rel=0&amp;playsinline=1&amp;start=3720"' in frame
    assert 'data-lw-kind="yt"' in frame


def test_her_own_place_still_wins(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"]["sermons"][0]["video_url"] = f"https://www.youtube.com/watch?v={VID}&t=1h2m"
    _places(fake, p={M[0]: [3800, 7200, 30, "v"]})
    frame = _frame(_get(fake, monkeypatch, f"/my/sermons/{M[0]}"))
    assert "start=3797" in frame and "start=3720" not in frame


def test_once_watched_it_starts_at_the_sermon_again(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"]["sermons"][0]["video_url"] = f"https://www.youtube.com/watch?v={VID}&t=1h2m"
    _places(fake, p={M[0]: [7200, 7200, 30, "v"]})
    assert "start=3720" in _frame(_get(fake, monkeypatch, f"/my/sermons/{M[0]}"))


def test_todays_message_page_starts_there_too(watch, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    watch["lib"]["sermons"][0]["video_url"] = f"https://youtu.be/{VID}?t=95"
    html = _get(fake, monkeypatch, f"/my/sermons/{M[0]}")
    assert f'<iframe src="{NOCOOKIE}?start=95"' in html


def test_the_page_script_finds_the_start_at_the_end():
    # The phone's newer place replaces "&start=N" (Watch's own script): the
    # server always draws the start there, never as "?start=".
    assert r"src.replace(/&start=\d+/,'')+'&start='+r0" in mlw.JS
