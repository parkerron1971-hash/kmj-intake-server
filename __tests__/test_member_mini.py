# __tests__/test_member_mini.py
#
# The mini player (member_mini): a message keeps playing while the member
# moves around the app (Look 5.1), behind MEMBER_MINI_PLAYER. Pins:
#   - the switch: off | preview | on, preview by default, unknown is off;
#     only a page in the new look; preview is the platform owner only; no
#     read for an ordinary member;
#   - off: no marks, no script, every page as it was;
#   - on: the message page's player is marked (the Look 5.1 contract) and
#     carries the script once; every other page is byte for byte what it
#     is with the switch off (a page in the frame is the ordinary page);
#   - the script: never inside a frame, only the app's own pages go in the
#     frame (Give, gifts, a group's live meeting, another message... load
#     the ordinary way), no page data through innerHTML;
#   - the sheet: the bar's rules in /my/lumen.<hash>.css before the type
#     block, every move only without reduced motion;
#   - the frame's headers: SAMEORIGIN / 'self' only for a same-site frame's
#     request under /my, nothing else touched, nothing at all when off;
#   - the service worker leaves a frame's page to the browser;
#   - the same reads with the switch on and off.

import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import sys
from collections import Counter

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_install as mai
import member_app_ui as ui
import member_lumen
import member_mini
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_give import church  # noqa: F401  (the fixture)
from test_member_lumen_pages import _client

MSG = "/my/sermons/00000000-0000-4000-8000-000000000601"
QUIET = "/my/sermons/00000000-0000-4000-8000-000000000602"   # no recording posted


def _get(fake, monkeypatch, path, mini="on"):  # noqa: F811
    monkeypatch.setenv("MEMBER_MINI_PLAYER", mini)
    return _client(fake, monkeypatch).get(path).text


# ─── the switch ──────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,want", [(None, "preview"), ("", "preview"), ("on", "on"), (" ON ", "on"),
                                      ("off", "off"), ("preview", "preview"), ("owner", "off"), ("yes", "off")])
def test_the_switch(monkeypatch, raw, want):
    if raw is None:
        monkeypatch.delenv("MEMBER_MINI_PLAYER", raising=False)
    else:
        monkeypatch.setenv("MEMBER_MINI_PLAYER", raw)
    assert member_mini.mode() == want


def _decide(monkeypatch, *, mini, lumen_mode, here, session, owner_church=True):
    monkeypatch.setenv("MEMBER_MINI_PLAYER", mini)
    monkeypatch.setenv("MEMBER_LUMEN", lumen_mode)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "pastor@example.test")
    asked = []
    monkeypatch.setattr(member_lumen, "_platform_church", lambda bid: asked.append(bid) or owner_church)
    tok = member_lumen.CURRENT.set(here)
    try:
        got = asyncio.run(member_mini.decide(session, {"id": "b1"}))
    finally:
        member_lumen.CURRENT.reset(tok)
    return got, asked


MEMBER = {"me": {"id": "c1", "email": "ana@example.test"}, "claims": {}}
OWNER = {"me": {"id": "c2", "email": "pastor@example.test"}, "claims": {}}
PREVIEW = {"me": {"id": "c1", "email": "ana@example.test"}, "claims": {}, "preview": True}


def test_off_is_nobody(monkeypatch):
    for s in (MEMBER, OWNER, PREVIEW):
        assert _decide(monkeypatch, mini="off", lumen_mode="on", here=True, session=s) == (False, [])


def test_only_a_page_in_the_new_look(monkeypatch):
    for s in (MEMBER, OWNER, PREVIEW):
        assert _decide(monkeypatch, mini="on", lumen_mode="on", here=False, session=s) == (False, [])


def test_on_is_everyone_in_the_new_look_without_a_read(monkeypatch):
    assert _decide(monkeypatch, mini="on", lumen_mode="on", here=True, session=MEMBER) == (True, [])


def test_preview_is_the_platform_owner_only(monkeypatch):
    # under MEMBER_LUMEN=preview the new look already is the owner only: no more asked
    assert _decide(monkeypatch, mini="preview", lumen_mode="preview", here=True, session=PREVIEW) == (True, [])
    assert _decide(monkeypatch, mini="preview", lumen_mode="preview", here=True, session=OWNER) == (True, [])
    # the new look for everyone: an ordinary member never gets it, and costs no read
    assert _decide(monkeypatch, mini="preview", lumen_mode="on", here=True, session=MEMBER) == (False, [])
    # the owner's own sign-in, at their church (the cached owner answer) or not
    assert _decide(monkeypatch, mini="preview", lumen_mode="on", here=True, session=OWNER) == (True, ["b1"])
    assert _decide(monkeypatch, mini="preview", lumen_mode="on", here=True, session=OWNER,
                   owner_church=False) == (False, ["b1"])
    assert _decide(monkeypatch, mini="preview", lumen_mode="on", here=True, session=None) == (False, [])
    assert _decide(monkeypatch, mini="preview", lumen_mode="on", here=True,
                   session={**OWNER, "unavailable": True}) == (False, [])


def test_preview_on_a_real_page(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.delenv("MEMBER_MINI_PLAYER", raising=False)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "pastor@example.test")
    c = _client(fake, monkeypatch)
    assert "data-lm-media" not in c.get(MSG).text                       # Ana isn't the platform owner
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "ana@example.test")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: True)
    html = c.get(MSG).text
    assert len(re.findall(r"<audio[^>]*data-lm-media", html)) == 1 and html.count(member_mini.JS) == 1


# ─── the pages ───────────────────────────────────────────────────────


def test_off_no_marks_no_script(church, fake, monkeypatch):  # noqa: F811
    for path in (MSG, QUIET, "/my", "/my/sermons"):
        html = _get(fake, monkeypatch, path, "off")
        assert "data-lm-media" not in html and "__lmMini" not in html and 'class="lm-mini' not in html


def test_the_message_page_marks_its_player_and_carries_the_script_once(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, MSG)
    audio = re.search(r"<audio[^>]*>", html).group(0)
    assert "data-lm-media" in audio and 'data-title="Hope Has a Name"' in audio and 'data-sub="Pastor James"' in audio
    assert f'data-href="{MSG}"' in audio and 'data-thumb="' in audio
    assert html.count(member_mini.JS) == 1
    # at the foot, after the page (never in the head)
    assert html.index(member_mini.JS) > html.index("</main>")
    assert 'class="lm-mini' not in html.replace(member_mini.JS, "")      # the bar is drawn by the script only


def test_a_message_with_nothing_to_play_carries_nothing(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, QUIET)
    assert "data-lm-media" not in html and "__lmMini" not in html


def test_old_look_never_gets_it(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _get(fake, monkeypatch, MSG)
    assert "data-lm-media" not in html and "__lmMini" not in html


@pytest.mark.parametrize("path", ["/my", "/my/sermons", "/my/connect", "/my/bible", "/my/me", "/my/give",
                                  "/my/sermons?series=00000000-0000-4000-8000-000000000501", QUIET])
def test_every_other_page_is_what_it_was(church, fake, monkeypatch, path):  # noqa: F811
    """A page in the frame is the ordinary page: switched on, every page but a
    message with something to play is byte for byte the page switched off."""
    on = _get(fake, monkeypatch, path, "on")
    off = _get(fake, monkeypatch, path, "off")
    assert on == off


def test_the_same_reads_on_and_off(church, fake, monkeypatch):  # noqa: F811
    for path in (MSG, "/my", "/my/sermons"):
        reads = {}
        for mode in ("on", "off"):
            monkeypatch.setenv("MEMBER_MINI_PLAYER", mode)
            c = _client(fake, monkeypatch)
            c.get(path)
            fake.gets.clear()
            c.get(path)
            reads[mode] = Counter(r.split("?")[0] for r in fake.gets)
        assert reads["on"] == reads["off"], path


# ─── marking ─────────────────────────────────────────────────────────


def test_mark_marks_each_player_once_and_escapes():
    player = ('<div class="sm-video"><iframe src="https://www.youtube-nocookie.com/embed/x" title="t"></iframe></div>'
              '<audio id="listen" class="sm-audio" controls src="https://a/x.mp3"></audio><img src="p.jpg">')
    out = member_mini.mark(player, title='Hope "Has" <a> Name', sub="Pastor & James", thumb="/p.jpg", href="/my/sermons/1")
    assert out.count("data-lm-media") == 2 and "<img src" in out and "data-lm-media data-title" not in out.split("<img")[1]
    assert 'data-title="Hope &quot;Has&quot; &lt;a&gt; Name"' in out and 'data-sub="Pastor &amp; James"' in out
    assert member_mini.mark(out, title="Other") == out                     # one already marked is left alone
    assert member_mini.mark("<p>nothing</p>", title="x") == "<p>nothing</p>"


def test_the_picture_follows_the_message_art_rules(monkeypatch):
    import member_app_photos as photos
    monkeypatch.setattr(photos, "series_art", lambda site, s: "/public/site-assets/x/series-light.webp" if s else "")
    assert member_mini.thumb({}, {}, "Light Has Come", "Hope") == "/public/site-assets/x/series-light.webp"
    monkeypatch.setattr(photos, "series_art", lambda site, s: "")
    monkeypatch.setattr(photos, "photos", lambda b, site, limit=None: ["https://x/light-has-come.jpg", "https://x/b.jpg"])
    assert member_mini.thumb({}, {}, "Light Has Come", "Hope") == "https://x/light-has-come.jpg"
    assert member_mini.thumb({}, {}, "", "Nothing Named") == ""


# ─── the script ──────────────────────────────────────────────────────


def _js():
    return member_mini.JS[len("<script>"):-len("</script>")]


@pytest.mark.skipif(not shutil.which("node"), reason="node checks the script")
def test_the_script_parses(tmp_path):
    p = tmp_path / "mini.js"
    p.write_text(_js(), encoding="utf-8")
    out = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr


def test_the_script_rules():
    js = _js()
    assert "w.top!==w" in js                                               # never inside the frame
    assert "if(!on||staged||cancel(e))return;" in js                       # nothing playing: the page as always
    assert "p==='/my'||p.indexOf('/my/')===0" in js                        # only the app's own pages go in the frame
    out = re.compile(json.loads(js.split("OUT=new RegExp(")[1].split("),")[0]))
    for p in ("/my/give", "/my/gifts", "/my/statement", "/my/groups/live/abc", "/my/photo/x", "/my/kids/lesson",
              "/my/preview", "/my/signout"):
        assert out.search(p), p
    for p in ("/my", "/my/connect", "/my/bible/john/1", "/my/groups", "/my/live", "/my/giving", "/my/messages"):
        assert not out.search(p), p
    assert "MSG.test(p)&&p!==HOME" in js                                   # another message loads the ordinary way
    assert "history.pushState({lmStage:seq}" in js and "history.replaceState(s,''" in js
    # page data only ever through textContent, an Image's src or an attribute: innerHTML gets fixed markup
    for m in re.finditer(r"innerHTML=([^;]+);", js):
        assert m.group(1).startswith(("'<a class=\"lm-mini-go\"", "I.", "I[")), m.group(1)
    assert "new MediaMetadata(" in js and "setActionHandler" in js        # the lock screen
    assert "'Back to the message'" in js                                   # a player from another site: no time
    for word in ("GitHub", "Claude", "builder"):
        assert word not in member_mini.JS


# ─── the sheet ───────────────────────────────────────────────────────


def test_the_bar_is_in_the_lumen_sheet_before_the_type():
    import member_lumen_fonts
    import member_lumen_ui as lm
    parts = lm.templates()
    assert member_mini.CSS in parts and parts[-1].template == member_lumen_fonts.template().template
    assert parts.index(member_mini.CSS) == len(parts) - 2
    text = ui.sheet("lumen")[0]
    assert "body.lm .lm-mini{" in text and "body.lm .lm-stagew{" in text
    for name in ("app", "youth", "kids", "door"):
        assert "lm-mini" not in ui.sheet(name)[0]


def test_the_bar_moves_only_without_reduced_motion():
    css = member_mini.CSS.template
    still = css.replace(css[css.index("@media (prefers-reduced-motion:no-preference){"):css.index("@keyframes lmMiniIn")], "")
    assert "animation" not in still.replace("@keyframes lmMiniIn", "") and "transition" not in still
    assert "$" not in css                                                  # no palette tokens: the page's own colours
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel in re.findall(r"(?:^|[{}])\s*([^\s@{}][^{}]*)\{", rules):
        for one in sel.split(","):
            one = one.strip()
            if one and not one.startswith(("from", "to")):
                assert one.startswith(("body.lm ", "body.lm.lm-mini-pad ", "html:has(>body.lm).lm-staged")), one


# ─── the frame's headers ─────────────────────────────────────────────


def _scope(path="/my", dest=b"iframe", site=b"same-origin"):
    h = [(b"host", b"lovecityc.com")]
    if dest is not None:
        h.append((b"sec-fetch-dest", dest))
    if site is not None:
        h.append((b"sec-fetch-site", site))
    return {"type": "http", "path": path, "method": "GET", "headers": h}


def test_a_frame_request_is_a_same_site_frame_under_my(monkeypatch):
    monkeypatch.setenv("MEMBER_MINI_PLAYER", "preview")
    assert member_mini.stage_request(_scope())
    assert member_mini.stage_request(_scope("/my/connect"))
    assert not member_mini.stage_request(_scope(site=b"cross-site"))
    assert not member_mini.stage_request(_scope(site=b"same-site"))
    assert not member_mini.stage_request(_scope(dest=b"document"))
    assert not member_mini.stage_request(_scope(dest=b"empty"))
    assert not member_mini.stage_request(_scope(dest=None, site=None))       # no fetch metadata: never
    assert not member_mini.stage_request(_scope("/sermons/1"))
    assert not member_mini.stage_request(_scope("/myother"))
    monkeypatch.setenv("MEMBER_MINI_PLAYER", "off")
    assert not member_mini.stage_request(_scope())


def test_relax_turns_only_the_refusal_into_this_site_only():
    got = dict(member_mini.relax([(b"x-frame-options", b"DENY"), (b"content-security-policy", b"frame-ancestors 'none'"),
                                  (b"cache-control", b"no-store")]))
    assert got == {b"x-frame-options": b"SAMEORIGIN", b"content-security-policy": b"frame-ancestors 'self'",
                   b"cache-control": b"no-store"}
    other = [(b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")]
    assert member_mini.relax(other) == other                                 # a page's own policy is kept


def _served(monkeypatch, mode, headers, path="/my"):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient
    import member_portal as mp
    monkeypatch.setenv("MEMBER_MINI_PLAYER", mode)
    app = FastAPI()

    @app.get("/{rest:path}")
    async def page(rest: str):
        return HTMLResponse("<p>x</p>", headers=mp._SECURE_HEADERS)
    app.add_middleware(member_mini.FrameForStage)
    r = TestClient(app, base_url="https://lovecityc.com").get(path, headers=headers)
    return r.headers.get("x-frame-options"), r.headers.get("content-security-policy"), r.text


def test_the_middleware(monkeypatch):
    frame = {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "same-origin"}
    assert _served(monkeypatch, "preview", frame) == ("SAMEORIGIN", "frame-ancestors 'self'", "<p>x</p>")
    assert _served(monkeypatch, "on", frame, "/my/bible/john/1")[:2] == ("SAMEORIGIN", "frame-ancestors 'self'")
    # everything else exactly as it was
    deny = ("DENY", "frame-ancestors 'none'", "<p>x</p>")
    assert _served(monkeypatch, "off", frame) == deny
    assert _served(monkeypatch, "on", {"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site"}) == deny
    assert _served(monkeypatch, "on", {"Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "same-origin"}) == deny
    assert _served(monkeypatch, "on", {}) == deny
    assert _served(monkeypatch, "on", frame, "/give") == deny


def test_the_app_has_the_middleware():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "from member_mini import FrameForStage\napp.add_middleware(FrameForStage)" in src


# ─── the service worker ──────────────────────────────────────────────

_NODE = r"""
const listeners = {}; let now = 1000; const asked = [];
global.self = {location: {origin: 'https://lovecityc.com'}, addEventListener: (t, f) => { listeners[t] = f; },
               skipWaiting() {}, clients: {claim() {}}, registration: {}};
global.caches = {open: async () => ({add: async () => {}}), keys: async () => [], match: async () => 'OFFLINE'};
global.Date = {now: () => now};
global.fetch = (req, init) => { const url = typeof req === 'string' ? req : req.url;
  asked.push(url + (init && init.headers ? ' (early)' : ''));
  return Promise.resolve({ok: true, type: 'basic', redirected: false, url, from: init && init.headers ? 'early' : 'net'}); };
eval(require('fs').readFileSync(0, 'utf8'));
const msg = (url) => listeners.message({data: {t: 'early', url}, waitUntil() {}});
const nav = async (url, destination) => { let out = null;
  listeners.fetch({request: {url, method: 'GET', mode: 'navigate', destination}, respondWith: (p) => { out = p; }});
  return out ? (await out).from || 'offline' : 'browser'; };
(async () => {
  const r = {};
  msg('https://lovecityc.com/my/bible');
  r.frame = await nav('https://lovecityc.com/my/bible', 'iframe');
  r.page = await nav('https://lovecityc.com/my/bible', 'document');
  r.plain = await nav('https://lovecityc.com/my/connect', 'document');
  console.log(JSON.stringify(r));
})();
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node runs the service worker")
def test_the_worker_leaves_a_frames_page_to_the_browser():
    out = subprocess.run(["node", "-e", _NODE], input=mai.SW_JS, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["frame"] == "browser"       # the frame's page goes out with the frame's own headers
    assert r["page"] == "early"          # a page in the browser still gets the copy kept early
    assert r["plain"] == "net"
