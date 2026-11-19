# __tests__/test_member_lumen_motion.py
#
# Lumen Next's motion and cinema (member_lumen_motion), behind MEMBER_LUMEN.
# Pins:
#   - off: no motion script, no cinema, the phone's bar colour as today;
#   - on: every Lumen page listens for its first reveal from its <head>
#     (Give, which draws its own document, at its foot), and what travels between
#     pages is named only while a page change runs;
#   - every move waits on prefers-reduced-motion: no-preference (a still
#     phone gets none), and the springs fall back to plain curves;
#   - the Watch tab's pages are a cinema: dark tokens, the phone's bar black,
#     the church's colour its readable-on-black shade;
#   - the live room: reactions over the video from the room's own hearts and
#     chat (its script untouched), who's here, Amen · heart · Praying only
#     while the box is open; the same reads on and off.

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import member_lumen_motion as mlm
import member_portal_live as mpl
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_give import LIVE, _get, church  # noqa: F401
from test_member_lumen_pages import _body_class


def _blocks(css):
    """(media condition or '', rule text) for every rule, @keyframes left out."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", css)
    out, depth, cond, stack, buf = [], 0, "", [], ""
    for ch in css:
        if ch == "{":
            head = buf.strip()
            if head.startswith("@"):
                stack.append(head)
            else:
                stack.append(None)
                cond = " ".join(h for h in stack if h)
                out.append([cond, head, ""])
            buf = ""
        elif ch == "}":
            if stack and stack[-1] is None and out:
                out[-1][2] = buf
            if stack:
                stack.pop()
            buf = ""
        else:
            buf += ch
    return out


def test_off_none_of_it(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    for path in ("/my/sermons", "/my"):
        html = _get(fake, monkeypatch, path)
        assert "__lmvt" not in html and "lm" not in _body_class(html).split()
        assert '<meta name="theme-color" content="#050506">' not in html
    church["live"] = dict(LIVE)
    html = _get(fake, monkeypatch, "/my/live")
    assert "lm-rxl" not in html and "lm-rx" not in html and mlm.ROOM_JS not in html


def test_every_lumen_page_listens_from_its_head(church, fake, monkeypatch):  # noqa: F811
    for path in ("/my", "/my/sermons", "/my/bible", "/my/connect"):
        html = _get(fake, monkeypatch, path)
        head, body = html.split("</head>", 1)
        assert head.count(mlm.JS) == 1 and mlm.JS not in body, path
    # Give draws its own document: there it rides at the foot, once.
    html = _get(fake, monkeypatch, "/my/give")
    head, body = html.split("</head>", 1)
    assert mlm.JS not in head and body.count(mlm.JS) == 1
    assert "if(window.__lmvt)return;window.__lmvt=1;" in mlm.JS


def test_what_travels_is_named_only_during_a_page_change():
    rules = _blocks(mlm.CSS.template)
    for cond, sel, body in rules:
        if "view-transition-name" in body:
            assert all(s.strip().startswith("html:active-view-transition") for s in sel.split(",")), sel
            assert "prefers-reduced-motion:no-preference" in cond, sel
    names = " ".join(body for _, _, body in rules)
    for n in ("lm-sermon", "lm-face", "lm-ttl", "lm-t-home", "lm-t-give"):
        assert f"view-transition-name:{n}" in names
    # The script names a clicked message's picture or a conversation's face and name.
    for bit in (".lm-irow", "'lm-face'", "'lm-ttl'", ".lm-poster", ".lm-th", "'lm-sermon'", "pagereveal", "data-vt"):
        assert bit in mlm.JS


def test_every_move_waits_on_no_preference():
    for cond, sel, body in _blocks(mlm.CSS.template):
        moving = re.search(r"(?<![-\w])(animation|transition)\s*:", body) or "view-transition" in sel
        if not moving:
            continue
        if sel.strip() == ".lm .lm-rz" and "reduce" in cond:
            continue                                                          # a still phone's reactions just fade
        assert "prefers-reduced-motion:no-preference" in cond, sel
    # The springs: plain curves first, linear() only where the browser has it.
    text = mlm.CSS.template
    assert "body.lm{--lm-spring:cubic-bezier(" in text
    assert "@supports (transition-timing-function:linear(0,1)){body.lm{--lm-spring:linear(" in text


def test_watch_is_a_cinema(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons")
    assert "pg-watch" in _body_class(html).split()
    assert '<meta name="theme-color" content="#050506">' in html
    home = _get(fake, monkeypatch, "/my")
    assert '<meta name="theme-color" content="#ffffff">' in home and "pg-watch" not in _body_class(home)
    assert "lm-dark" in _body_class(html).split()                         # the new look's one dark switch
    sheet = ui.sheet("lumen")[0]
    assert "body.lm.lm-dark.pg-watch{--bg:#050506;" in sheet and "--acc:var(--acc-lit)" in sheet
    assert "html:has(>body.lm.lm-dark.pg-watch){background:#050506;" in sheet
    assert mlm.cine("live") and mlm.cine("sermons") and mlm.cine("watch") and not mlm.cine("bible")


def test_the_room_has_reactions_over_the_video(church, fake, monkeypatch):  # noqa: F811
    church["live"] = dict(LIVE)
    html = _get(fake, monkeypatch, "/my/live")
    stage = html[html.index('class="lv-stage"'):html.index('class="lv-info"')]
    assert '<div class="lm-rxl" id="lm-rxl" aria-hidden="true"></div>' in stage
    info = html[html.index('class="lv-info"'):html.index('class="lv-acts"')]
    assert 'class="lm-watching"' in info and "<b data-here-n>" in info and "here with you" in info
    bar = info[info.index('id="lm-rx"'):]
    assert 'value="Amen">Amen</button>' in bar and "data-heart" in bar and 'value="Praying">' in bar
    assert 'action="/my/live/chat"' in info and 'id="lm-rx-tpl"' in info
    # The room's own script, untouched, then the reactions'.
    assert html.index(mpl.ROOM_JS.split("__CFG__")[0]) < html.index(mlm.ROOM_JS)
    for bit in ("lv-hearts", "mb-chat", "lv-quick", "lv-send", "MutationObserver", "6000"):
        assert bit in mlm.ROOM_JS


def test_the_room_with_the_box_closed_has_no_reactions_bar(church, fake, monkeypatch):  # noqa: F811
    church["live"] = dict(LIVE, chat_open=False)
    html = _get(fake, monkeypatch, "/my/live")
    assert 'id="lm-rx"' not in html and 'id="lm-rxl"' in html                 # hearts can't be sent; none rise


def test_the_same_reads_on_and_off(church, fake, monkeypatch):  # noqa: F811
    from collections import Counter
    from test_member_lumen_pages import _client
    church["live"] = dict(LIVE)
    for path in ("/my/sermons", "/my/live"):
        got = {}
        for mode in ("off", "on"):
            monkeypatch.setenv("MEMBER_LUMEN", mode)
            c = _client(fake, monkeypatch)
            c.get(path)
            fake.gets.clear()
            c.get(path)
            got[mode] = Counter(r.split("?")[0] for r in fake.gets)
        assert got["off"] == got["on"], path
