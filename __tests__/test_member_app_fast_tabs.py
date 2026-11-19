"""Faster tabs in the member app (Kevin, 2026-11-18: "the members app move
slow when send messages in chat, switching from one tab to another... how
can that be sped up?"; "yes build all four").

1. The look is a file every church shares (/my/app.<hash>.css and its
   Youth, Kids and sign-in siblings), kept a year, and a page carries only
   its church's colours. The file plus the colours are exactly the sheet a
   page used to carry inline.
2. The next tab loads on a touch or hover of the tab bar: speculation rules
   for Chrome, the service worker for Safari. Never News (its GET marks
   posts seen), never a form, never another site.
3. Pages cross-fade with the tab bar held still; reduced motion gets none.
MEMBER_APP_FAST=off puts all of it back the way it was.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import custom_domain_cache
import member_app_install as mai
import member_app_signin as sg
import member_app_ui as ui
import member_portal as mp
import member_spaces as msp

BIZ = {"id": "11111111-1111-4111-8111-111111111111", "name": "Love City Church",
       "settings": {"brand_kit": {"colors": {"primary": "#0B2146"}, "accent": "#F4AE3D"}}}
WHITE = {"id": "22222222-2222-4222-8222-222222222222", "name": "Grace Fellowship",
         "settings": {"brand_kit": {"colors": {"primary": "#B3123A"}, "accent": "#B3123A"},
                      "member_portal": {"base": "white", "youth_color": "#ff3d81"}}}
ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com"}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.delenv("MEMBER_APP_FAST", raising=False)
    # Per test, as test_member_app_give does (a module-level default leaks
    # into other files' collection).
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test")
    yield
    msp.CURRENT.set({})


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mp.router)
    app.add_middleware(custom_domain_cache.NoSharedCacheForCustomDomains)
    return TestClient(app)


def _page(biz=BIZ, space="church", **kw):
    msp.CURRENT.set({"space": space} if space != "church" else {})
    kw.setdefault("tab", "home")
    kw.setdefault("who", ME)
    return mp._shell(biz, None, "Home", "<p>hello</p>", **kw)


def _linked(page):
    return re.findall(r'<link rel="stylesheet" href="(/my/[^"]+\.css)">', page)


def _expand(name, colours):
    """A shared sheet with a page's colours put in: what the browser ends up with."""
    values = dict(re.findall(r"--mbt-([\w]+):([^;]+);", colours))
    return re.sub(r"var\(--mbt-(\w+)\)", lambda m: values[m.group(1)], ui.sheet(name)[0])


# ─── 1. the look as a file ───────────────────────────────────────────


@pytest.mark.parametrize("name", ui.SHEETS)
def test_each_sheet_is_served_once_for_everyone_and_kept_a_year(name):
    r = _client().get(ui.sheet_url(name))
    assert r.status_code == 200 and r.text == ui.sheet(name)[0]
    assert r.headers["content-type"].startswith("text/css")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"
    # the address carries a hash of what's in it, so a change is a new address
    assert re.fullmatch(r"/my/%s\.[0-9a-f]{12}\.css" % name, ui.sheet_url(name))


def test_the_sheet_needs_no_church_and_works_on_any_church_address(monkeypatch):
    monkeypatch.setattr(mp, "_church_for_request", lambda r: (_ for _ in ()).throw(AssertionError("no lookup")))
    c = _client()
    for host in ({"Host": "love-city-church.mysolutionist.app"}, {"Host": "grace.mysolutionist.app"}):
        r = c.get(ui.sheet_url("app"), headers=host)
        assert r.status_code == 200 and r.headers["cache-control"].endswith("immutable")
    # A custom domain comes through Cloudflare's Worker (X-Original-Host). The
    # file is the same for every church, so Cloudflare may keep it too.
    r = c.get(ui.sheet_url("app"), headers={"X-Original-Host": "lovecityc.com"})
    assert r.status_code == 200 and r.text == ui.sheet("app")[0]
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "cloudflare-cdn-cache-control" not in r.headers


def test_a_hash_from_the_other_side_of_a_deploy_keeps_the_look_but_nobody_keeps_it():
    c = _client()
    r = c.get("/my/app.000000000000.css")
    assert r.status_code == 200 and r.text == ui.sheet("app")[0]
    assert r.headers["cache-control"] == "no-store"
    r = c.get("/my/app.000000000000.css", headers={"X-Original-Host": "lovecityc.com"})
    assert r.headers["cloudflare-cdn-cache-control"] == "no-store" and "private" in r.headers["cache-control"]


@pytest.mark.parametrize("path", ["/my/evil.%s.css", "/my/app.css", "/my/app.%s.css.map", "/my/APP.%s.css",
                                  "/my/app.%s0.css"])
def test_nothing_else_answers_as_a_sheet(path):
    path = path % ui.sheet("app")[1] if "%s" in path else path
    assert _client().get(path).status_code == 404


def test_the_custom_domain_exception_is_only_the_sheets():
    samples = [ui.sheet_url(n) for n in ui.SHEETS] + ["/my/app.000000000000.css", "/my/evil.000000000000.css",
                                                      "/my/app.css", "/my", "/my/app.00000000000g.css", "/app.css"]
    for path in samples:   # the same addresses as member_app_ui's
        assert bool(custom_domain_cache.SHARED_SHEET_RE.match(path)) == bool(ui.SHEET_PATH_RE.match(path)), path
    forever = [(b"cache-control", b"public, max-age=31536000, immutable")]
    assert custom_domain_cache._shared_sheet({"path": ui.sheet_url("kids")}, forever)
    assert not custom_domain_cache._shared_sheet({"path": "/my"}, forever)
    assert not custom_domain_cache._shared_sheet({"path": "/style.css"}, forever)
    assert not custom_domain_cache._shared_sheet({"path": ui.sheet_url("app")}, [(b"cache-control", b"no-store")])


def test_a_page_links_the_file_and_carries_only_its_churchs_colours():
    page = _page()
    assert _linked(page) == [ui.sheet_url("app")]
    assert ".mb-nav{position:fixed" not in page and ".mb-nav{position:fixed" in ui.sheet("app")[0]
    colours = ui.colours(BIZ, {})
    assert f"<style>{colours}</style>" in page and len(colours) < 3000
    # two churches: the same file, their own colours
    other = _page(WHITE)
    assert _linked(other) == _linked(page)
    assert ui.colours(WHITE, {}) in other and ui.colours(WHITE, {}) != colours
    assert "--mbt-bg:#ffffff;" in ui.colours(WHITE, {}).lower() and "--mbt-bg:#000000;" in colours.lower()
    assert len(page) < 30000                       # was ~100 KB with the sheet inline


@pytest.mark.parametrize("biz", [BIZ, WHITE, {"id": "b3", "name": "Gray", "settings": {"member_portal": {"base": "gray"}}},
                                 {"id": "b4", "name": "Dark", "settings": {"member_portal": {"base": "charcoal"},
                                                                           "brand_kit": {"accent": "#ffd400"}}}])
@pytest.mark.parametrize("space", ["church", "youth", "kids"])
def test_the_file_and_the_colours_are_exactly_the_old_inline_sheet(biz, space):
    colours = ui.colours(biz, {}, space)
    got = _expand("app", colours)
    if space != "church":
        got += _expand(space, colours)
    assert got.replace(ui.MOTION_CSS, "") == ui.css(biz, {}, space)


def test_the_sign_in_pages_look_is_the_same_too():
    page = mp.render_signin(WHITE, None)
    assert _linked(page) == [ui.sheet_url("app"), ui.sheet_url("door")]
    colours = ui.colours(WHITE, {}, door=True)
    assert colours in page
    assert _expand("door", colours) == sg.css(WHITE, {})
    for render in (mp.render_unavailable, mp.render_signin_paused, mp.render_try_again):
        assert _linked(render(BIZ, None)) == [ui.sheet_url("app"), ui.sheet_url("door")]


def test_youth_and_kids_add_their_own_sheet_after_the_app_sheet():
    assert _linked(_page(space="youth")) == [ui.sheet_url("app"), ui.sheet_url("youth")]
    assert _linked(_page(space="kids")) == [ui.sheet_url("app"), ui.sheet_url("kids")]
    assert ui.colours(WHITE, {}, "youth") in _page(WHITE, space="youth")     # Youth's own colours
    assert ui.colours(WHITE, {}, "youth") != ui.colours(WHITE, {})


def test_the_give_tab_links_the_file_too():
    page = mp.render_give(BIZ, None, ME)
    assert ui.sheet_url("app") in page and ui.colours(BIZ, {}) in page and ".mb-nav{position:fixed" not in page


def test_the_offline_page_keeps_the_whole_look_inside_it():
    page = mai.render_offline(BIZ, None)
    assert not _linked(page) and ui.css(BIZ, {}) in page     # with no connection there may be no file


# ─── 2. the next tab, early ──────────────────────────────────────────


def _rules(page):
    m = re.search(r"var R=(\{.*?\}),N=", page)
    return json.loads(m.group(1)) if m else None


def test_pages_with_the_tab_bar_load_the_next_tab_early():
    page = _page()
    assert ui.EARLY_JS in page and "speculationrules" in page
    assert _rules(page) == ui.EARLY_RULES
    assert ui.EARLY_JS in mp.render_give(BIZ, None, ME)                 # Give's own page has the bar too
    assert ui.EARLY_JS in _page(space="youth") and ui.EARLY_JS in _page(space="kids")


def test_pages_without_the_bar_never_load_anything_early():
    assert "speculationrules" not in mp.render_signin(BIZ, None)              # signed out
    assert "speculationrules" not in mp.render_unavailable(BIZ, None)
    assert "speculationrules" not in mai.render_offline(BIZ, None)
    assert "speculationrules" not in _page(bar=False)                          # a chat: no tab bar
    assert "speculationrules" not in _page(tab=None, who=None)


def test_only_the_tab_bar_on_a_touch_or_hover_never_news_never_the_page_you_are_on():
    rule = ui.EARLY_RULES["prefetch"][0]
    assert rule["eagerness"] == "moderate"                    # a press or a 200 ms hover: not on sight
    # a touch screen: the touch only (Chrome's phone "moderate" guesses at links with no touch)
    assert "if(!matchMedia('(hover: hover)').matches)R.prefetch[0].eagerness='conservative';" in ui.EARLY_JS
    where = rule["where"]["and"]
    assert {"selector_matches": ".mb-nav a[href]"} in where   # the tab bar and the sidebar only
    assert {"not": {"selector_matches": "[aria-current]"}} in where
    assert {"or": [{"href_matches": "/my"}, {"href_matches": "/my/*"}]} in where
    assert {"not": {"or": [{"href_matches": "/my/news"}, {"href_matches": "/my/news/*"}]}} in where
    assert "/my/news" in ui.NO_EARLY
    # the same rules for Safari's way, in the script
    js = ui.EARLY_JS
    assert "a.closest('.mb-nav')" in js and "hasAttribute('aria-current')" in js
    assert r"N=/^(\/my\/news)(\/|$)/" in js and "u.origin!==location.origin" in js and "u.search" in js
    assert "'touchstart'" in js and "'mousedown'" in js and "},200);" in js
    # Chrome gets the rules (its own prefetch); everyone else the worker; never both
    assert "navigator.userAgentData&&" in js and "return;}if(!('serviceWorker' in navigator))return;" in js


def test_sign_out_and_every_change_is_a_form_never_a_link_in_the_bar():
    me_page = mp.render_me(BIZ, None, me=ME, people=[ME], year=2026, gifts=[], give_url="", this_year=2026)
    assert '<form method="post" action="/my/signout">' in me_page and 'href="/my/signout"' not in me_page
    # what the bar and the sidebar link to: pages only, none of them a POST route
    posts = {r.path for r in mp.router.routes if "POST" in getattr(r, "methods", set())}
    for biz in (BIZ, dict(BIZ, settings={"member_portal": {"tabs": ["home", "news", "events", "give", "prayer"]}})):
        for kw in ({}, {"wide": True}):
            msp.CURRENT.set({"space": "church", "lead": True, "board": True})
            page = mp._shell(biz, None, "Home", "<p>x</p>", tab="home", who=ME, **kw)
            nav = page[page.index('<nav class="mb-nav'):page.index("</nav>", page.index('<nav class="mb-nav'))]
            hrefs = re.findall(r'href="([^"]+)"', nav)
            assert hrefs and all(h == "/my" or h.startswith("/my/") for h in hrefs)
            assert not set(hrefs) & posts and "<form" not in nav


def test_the_worker_keeps_an_early_tab_in_memory_once_and_only_briefly():
    sw = mai.SW_JS
    assert "const EARLY_MS = 10000;" in sw and "new Map()" in sw
    assert "if (e.request.method !== 'GET') early.clear();" in sw          # a form or sign-out drops it
    assert "caches.open" in sw and sw.count("caches.put") == 0                # nothing but offline on disk
    assert "redirect: 'manual'" in sw and "r.type === 'basic' && !r.redirected" in sw


_NODE_HARNESS = r"""
const listeners = {}; let now = 1000; const asked = [];
global.self = {location: {origin: 'https://lovecityc.com'}, addEventListener: (t, f) => { listeners[t] = f; },
               skipWaiting() {}, clients: {claim() {}}, registration: {}};
global.caches = {open: async () => ({add: async () => {}}), keys: async () => [], match: async () => 'OFFLINE'};
global.Date = {now: () => now};
global.fetch = (req, init) => { const url = typeof req === 'string' ? req : req.url;
  asked.push(url + (init && init.headers ? ' (early)' : ''));
  return Promise.resolve({ok: !url.includes('/gone'), type: url.includes('/gone') ? 'opaqueredirect' : 'basic',
                          redirected: false, url, from: init && init.headers ? 'early' : 'net'}); };
eval(require('fs').readFileSync(0, 'utf8'));
const msg = (url) => listeners.message({data: {t: 'early', url}, waitUntil() {}});
const nav = async (url, method = 'GET', mode = 'navigate') => { let out = null;
  listeners.fetch({request: {url, method, mode}, respondWith: (p) => { out = p; }});
  return out ? (await out).from || 'offline' : 'browser'; };
(async () => {
  const r = {};
  msg('https://lovecityc.com/my/bible');
  r.used = await nav('https://lovecityc.com/my/bible');
  r.once = await nav('https://lovecityc.com/my/bible');
  msg('https://lovecityc.com/my/bible'); r.other = await nav('https://lovecityc.com/my/give');
  r.afterOther = await nav('https://lovecityc.com/my/bible');
  msg('https://lovecityc.com/my/bible'); await nav('https://lovecityc.com/my/feed', 'POST', 'cors');
  r.afterPost = await nav('https://lovecityc.com/my/bible');
  msg('https://lovecityc.com/my/bible'); now += 10001; r.stale = await nav('https://lovecityc.com/my/bible');
  msg('https://lovecityc.com/my/gone'); r.redirect = await nav('https://lovecityc.com/my/gone');
  const n = asked.length;
  msg('https://evil.example/my/x'); msg('https://lovecityc.com/give'); msg('https://lovecityc.com/my?x=1');
  r.refused = asked.length - n;
  msg('https://lovecityc.com/my/sermons'); r.formNav = await nav('https://lovecityc.com/my/sermons', 'POST');
  r.image = await nav('https://lovecityc.com/my/icon-192.png', 'GET', 'no-cors');
  console.log(JSON.stringify(r));
})();
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node runs the service worker")
def test_the_worker_uses_an_early_tab_once_and_never_after_a_form_or_too_late():
    out = subprocess.run(["node", "-e", _NODE_HARNESS], input=mai.SW_JS, capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["used"] == "early"            # the tap gets the answer that was waiting
    assert r["once"] == "net"              # once only
    assert r["other"] == "net" and r["afterOther"] == "net"   # another page opened drops it
    assert r["afterPost"] == "net"         # anything that isn't a GET drops it
    assert r["stale"] == "net"             # ten seconds at most
    assert r["redirect"] == "net"          # signed out (a redirect): asked again the usual way
    assert r["refused"] == 0               # another site, a page outside /my, a query: never fetched
    assert r["formNav"] == "net"           # a form posted to a page is never answered early
    assert r["image"] == "browser"         # everything else is left to the browser


# ─── 3. motion ───────────────────────────────────────────────────────


def test_pages_cross_fade_with_the_bars_held_and_reduced_motion_gets_none():
    m = ui.MOTION_CSS
    assert m in ui.sheet("app")[0] and m.count("@view-transition") == 1
    body = m[m.index("@media (prefers-reduced-motion:no-preference){"):]
    assert "@view-transition{navigation:auto;}" in body                     # only without reduced motion
    assert "html:active-view-transition .mb-nav{view-transition-name:mb-nav;}" in body
    assert "html:active-view-transition .mb-top{view-transition-name:mb-top;}" in body
    assert re.search(r"::view-transition-group\(\*\)\{animation-duration:\.\d+s;\}", body)
    # the tab bar never fades: the old one stays drawn and the new one is laid over it
    assert "::view-transition-old(mb-nav),::view-transition-new(mb-nav){animation:none;mix-blend-mode:normal;}" in body
    for name in ("youth", "kids", "door"):
        assert "view-transition" not in ui.sheet(name)[0]


# ─── the way back ────────────────────────────────────────────────────


@pytest.mark.parametrize("off", ["off", "0", "false", "no", " OFF "])
def test_member_app_fast_off_is_every_page_as_it_was(monkeypatch, off):
    monkeypatch.setenv("MEMBER_APP_FAST", off)
    assert not ui.fast()
    page = _page()
    assert not _linked(page) and f"<style>{ui.css(BIZ, {})}</style>" in page
    assert "speculationrules" not in page and "view-transition" not in page and "--mbt-" not in page
    signin = mp.render_signin(BIZ, None)
    assert f"<style>{sg.css(BIZ, {})}</style>" in signin and not _linked(signin)
    youth = _page(space="youth")
    assert f"<style>{ui.css(BIZ, {}, 'youth')}</style>" in youth
    give = mp.render_give(BIZ, None, ME)
    assert ui.css(BIZ, {}) in give and "speculationrules" not in give


def test_unset_or_empty_is_on(monkeypatch):
    assert ui.fast()
    monkeypatch.setenv("MEMBER_APP_FAST", "")
    assert ui.fast()
    monkeypatch.setenv("MEMBER_APP_FAST", "on")
    assert ui.fast()
