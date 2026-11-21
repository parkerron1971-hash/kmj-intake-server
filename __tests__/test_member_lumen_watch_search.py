# __tests__/test_member_lumen_watch_search.py
#
# Search on Watch in the new look (member_lumen_watch.search_page), as the
# Look 5.1 mock draws it: the search button at the right of Watch's own top
# bar and "Search" beside Every message. Pins:
#   - both open /my/sermons?q= (a link: no script); the page is a GET form
#     with the field and Cancel back to Watch;
#   - the results are Every message's rows for the messages whose title,
#     speaker, scripture or series has every word (any case, accents and
#     apostrophes aside), newest first, at most RESULTS; "No messages match"
#     with the way back; an empty query shows the field and a hint;
#   - it reads nothing Watch doesn't (no read of its own, and no service
#     time); a failed library read says so;
#   - today's look ignores ?q= (Watch as it is);
#   - the CSS lives in Watch's block, under .lm.

import json
import pathlib
import re
import sys
from collections import Counter

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_lumen_watch as mlw
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_give import church  # noqa: F401  (the fixture)
from test_member_lumen_watch import LIB, M, S1, _app, _cut, _get, _s, _service, watch  # noqa: F401  (the fixture)


def _rows(html):
    return re.findall(r'<a class="lw-mrow" href="/my/sermons/([^"]+)"', html)


def test_the_bar_and_every_message_open_the_search(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons")
    bar = _cut(html, '<header class="mb-top lm-own lm-own-watch">', "</header>")
    assert '<span class="mb-top-right"><a class="lm-icb mp-noprint lw-findb" href="/my/sermons?q=" aria-label="Search messages">' in bar
    assert 'aria-current' not in bar
    every = _cut(html, 'id="lw-every"', "</div>")
    assert '<h2 id="lw-ev-h">Every message</h2><a class="lw-shl" href="/my/sermons?q=">Search</a>' in every


def test_the_empty_search_is_the_field(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons?q=")
    assert '<form class="lw-find" method="get" action="/my/sermons" role="search">' in html
    assert re.search(r'<input type="search" name="q" value="" placeholder="Search messages" '
                     r'maxlength="80" enterkeyhint="search" autocomplete="off" autofocus>', html)
    assert '<a class="lw-fx" href="/my/sermons">Cancel</a>' in html
    assert "Find a message by its title" in html and not _rows(html)
    bar = _cut(html, '<header class="mb-top lm-own lm-own-watch">', "</header>")
    assert 'aria-label="Search messages" aria-current="page"' in bar        # the bar's button marks it
    assert 'class="lw-seg"' not in html and 'class="lw-hero"' not in html
    assert "<title>Search" in html


@pytest.mark.parametrize("q,want", [
    ("light", [0, 1, 2]),                         # the title, and the series "Light Has Come"
    ("LIGHT dark", [1]),                          # every word, any case
    ("isaiah", [0, 2]),                           # the scripture
    ("dana", [3]),                                # the speaker
    ("rooted", [4, 5]),                           # the series' name
    ("john 1:5", [1]),
    ("  good   soil ", [5]),
])
def test_the_results_are_every_messages_rows(watch, fake, monkeypatch, q, want):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons?q=" + q.replace(" ", "+"))
    assert _rows(html) == [M[i] for i in want]                            # newest first, as the library
    n = len(want)
    assert f'<h2 id="lw-fr-h" role="status">{n} message{"" if n == 1 else "s"}</h2>' in html
    assert f'value="{" ".join(q.split())}"' in html and " autofocus" not in html


def test_accents_and_apostrophes_aside():
    lib = {"series": [], "sermons": [{"id": "a", "title": "God’s Plan", "speaker": "Pastor José", "scripture": ""},
                                     {"id": "b", "title": "Gods Among Us", "speaker": "", "scripture": ""}]}
    assert [s["id"] for s in mlw.search(lib, "god's")] == ["a", "b"]
    assert [s["id"] for s in mlw.search(lib, "jose")] == ["a"]
    assert mlw.search(lib, "   ") == [] and mlw.search(lib, None) == []


def test_nothing_matches(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons?q=zzqq")
    nf = _cut(html, '<div class="lw-nf lw-pad" role="status">', "</div>")
    assert "<h2>No messages match “zzqq”</h2>" in nf
    assert '<a class="lw-pill" href="/my/sermons">' in nf and "Back to Watch</a>" in nf
    assert not _rows(html)


def test_the_words_are_escaped_and_cut(watch, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, '/my/sermons?q=%3Cscript%3E"x')
    assert "<script>\"x" not in html and "&lt;script&gt;&quot;x" in html
    long = "a" * 200
    assert f'value="{"a" * 80}"' in _get(fake, monkeypatch, "/my/sermons?q=" + long)


def test_at_most_results_then_a_line(watch, fake, monkeypatch):  # noqa: F811
    lib = json.loads(json.dumps(LIB))
    lib["sermons"] = [_s(i % 29, None, f"Grace {i}", i) for i in range(70)]
    for i, s in enumerate(lib["sermons"]):
        s["id"] = f"00000000-0000-4000-8000-{i:012d}"
    watch["lib"] = lib
    html = _get(fake, monkeypatch, "/my/sermons?q=grace")
    assert len(_rows(html)) == mlw.RESULTS and '>70 messages</h2>' in html
    assert "These are the newest 60. Add a word to narrow it down." in html


def test_no_read_of_its_own(watch, fake, monkeypatch):  # noqa: F811
    _service(fake)
    c = _app(fake, monkeypatch)
    seen = {}
    for path in ("/my/sermons", "/my/sermons?q=light"):
        c.get(path)
        fake.gets.clear()
        c.get(path)
        seen[path] = Counter(g.split("?")[0] for g in fake.gets)
    assert seen["/my/sermons?q=light"] <= seen["/my/sermons"]               # nothing Watch doesn't read
    assert "/church_checkin_settings" not in seen["/my/sermons?q=light"]     # and not the service time


def test_a_failed_library_read_says_so(watch, fake, monkeypatch):  # noqa: F811
    watch["lib"] = None
    r = _app(fake, monkeypatch).get("/my/sermons?q=light")
    assert r.status_code == 503 and "Messages couldn't load just now" in r.text and 'class="lw-find"' in r.text


def test_todays_look_ignores_it(watch, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _app(fake, monkeypatch)
    assert c.get("/my/sermons?q=light").text.replace("?q=light", "") == c.get("/my/sermons").text
    assert "lw-find" not in c.get("/my/sermons?q=light").text


def test_the_css_is_watchs_under_lm():
    css = mlw.CSS.template
    i = css.index(".lm .lw-find{")
    assert i > css.index("/* Watch, Look 5.1 (member_lumen_watch) */")
    for rule in re.findall(r"^([^\n{]*\.lw-(?:find|fbox|fx|nf|shl)[^\n{]*)\{", css, re.M):
        assert all(sel.strip().startswith(".lm ") for sel in rule.split(",")), rule
