# __tests__/test_member_portal_bible.py
#
# The Bible in the member app (member_portal_bible.py). Pins:
#   1. the Bible home lists every book, keeps reading where they left
#      off, and remembers their translation — on their phone only
#   2. "John 3:16" typed into Go to opens that verse; nonsense says so
#   3. a chapter marks the asked-for verses, steps across books, and a
#      bad book or chapter goes back instead of erroring
#   4. KJV shows its supplied words in italics without the ¶ marks
#   5. a sermon's scripture links into the Bible and reads on the page
#   6. nothing typed is echoed unescaped

import asyncio
import pathlib
import sys

import pytest
from starlette.requests import Request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp
import member_portal_bible as mpb
import member_portal_sermons as mps

BIZ = {"id": "b1", "name": "First Light Church", "type": "church", "settings": {}}
ME = {"id": "c1", "name": "Ana Rivers"}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)


def req(path="/my/bible", query="", cookie=""):
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": path, "query_string": query.encode(), "headers": headers})


def go(path, query="", cookie=""):
    return asyncio.run(mpb.serve(req(path, query, cookie), BIZ, None, ME, path))


def cookie_of(resp):
    return resp.headers.get("set-cookie", "")


def test_the_bible_home_lists_the_books_and_remembers_on_the_phone():
    r = go("/my/bible")
    page = r.body.decode()
    assert r.status_code == 200 and page.count('href="/my/bible/') >= 66
    assert 'href="/my/bible/genesis"' in page and 'href="/my/bible/revelation"' in page
    assert 'href="/my/bible?t=kjv" aria-current="true"' in page and "Keep reading" not in page
    later = go("/my/bible", cookie="sol_bible=web|romans/8").body.decode()
    assert 'href="/my/bible?t=web" aria-current="true"' in later
    assert 'href="/my/bible/romans/8"' in later and "Keep reading" in later
    c = cookie_of(go("/my/bible", "t=web"))
    assert "sol_bible=" in c and "web|" in c and "Path=/my" in c and "HttpOnly" in c and "Secure" in c


def test_go_to_opens_the_verse_and_nonsense_says_so():
    r = go("/my/bible", "q=jn 3:16")
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/john/3?v=16#v16"
    miss = go("/my/bible", "q=the best verse")
    assert miss.status_code == 200 and "couldn't find that passage" in miss.body.decode()


def test_a_chapter_marks_its_verses_and_steps_across_books():
    r = go("/my/bible/john/3", "v=16-17")
    page = r.body.decode()
    assert page.count('<mark class="bb-hl">') == 2 and '<sup class="bb-n" id="v16">16</sup>' in page
    assert 'href="/my/bible/john/2"' in page and 'href="/my/bible/john/4"' in page
    assert "kjv|john/3" in cookie_of(r)
    assert "<strong>Psalm 2</strong>" in go("/my/bible/psalms/1").body.decode()      # a chapter, not "Psalms 2"
    edge = go("/my/bible/malachi/4").body.decode()
    assert 'href="/my/bible/malachi/3"' in edge and 'href="/my/bible/matthew/1"' in edge
    assert go("/my/bible/john/3", "v=99").body.decode().count('<mark class="bb-hl">') == 0
    assert go("/my/bible/nowhere").headers["location"] == "/my/bible"
    assert go("/my/bible/john/99").headers["location"] == "/my/bible/john"
    assert go("/my/bible/john/three").headers["location"] == "/my/bible/john"
    assert go("/my/bible/john").body.decode().count('href="/my/bible/john/') == 21


def test_kjv_italics_and_paragraphs_and_web_lines():
    kjv = mpb.chapter_html("PSA", 23, "kjv")
    assert "The LORD <i>is</i> my shepherd" in kjv and "¶" not in kjv and "[" not in kjv
    web = mpb.chapter_html("PSA", 23, "web")
    assert 'class="bb-text bb-lines"' in web and web.count("<p>") == 6 and "Yahweh is my shepherd" in web


def test_a_sermons_scripture_opens_in_the_bible_and_reads_on_the_page():
    lib = {"series": [], "sermons": [{"id": "00000000-0000-4000-8000-000000000001", "series_id": None,
                                      "title": "Planted", "preached_on": "2026-09-27", "speaker": "Pastor Dana",
                                      "scripture": "Psalm 1:1-3; Jeremiah 17:7-8", "summary": "", "questions": "",
                                      "video_url": "", "audio_url": "", "published": True}]}
    page = mps.render_sermon(BIZ, None, ME, lib, "00000000-0000-4000-8000-000000000001", bible="web")
    assert '<a class="bb-ref" href="/my/bible/psalms/1?v=1-3#v1">Psalm 1:1-3</a>' in page
    assert '<a class="bb-ref" href="/my/bible/jeremiah/17?v=7-8#v7">Jeremiah 17:7-8</a>' in page
    assert "Blessed is the man who doesn" in page and "WEB" in page        # read right there
    shelf = mps.render_library(BIZ, None, ME, lib)
    assert 'class="bb-ref"' not in shelf                                     # cards stay one link


def test_nothing_typed_is_echoed_unescaped():
    page = go("/my/bible", 'q=<script>alert(1)</script>').body.decode()
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    assert "t=<" not in cookie_of(go("/my/bible", "t=<b>"))
    for text in ('Psalm 23 <img src=x onerror=alert(1)>', '<img src=x onerror=alert(1)> Psalm 23'):
        links = mpb.scripture_links(text)
        assert "<img" not in links and "&lt;img" in links and 'href="/my/bible/psalms/23#v1"' in links
    # A cookie only ever picks a translation we have.
    odd = go("/my/bible", cookie="sol_bible=<b>|john/3")
    assert odd.status_code == 200 and 'href="/my/bible?t=kjv" aria-current="true"' in odd.body.decode()
    assert "<b>" not in cookie_of(odd)


def test_the_member_app_routes_the_bible(monkeypatch):
    seen = {}

    async def fake(request, biz, site, me, sub):
        seen["sub"] = sub
        return mp._page("ok")
    monkeypatch.setattr(mpb, "serve", fake)
    sess = {"me": ME, "people": [ME]}
    asyncio.run(mp._serve_page(req("/my/bible/john/3"), {"business": BIZ, "site": None}, sess, "/my/bible/john/3"))
    assert seen["sub"] == "/my/bible/john/3"
