# __tests__/test_member_lumen_give.py
#
# Give, Watch and Live in the member app's new look ("Lumen",
# member_lumen_give), behind MEMBER_LUMEN (member_lumen.py). Pins:
#   - off: none of it shows (no Lumen class, sheet or block on any of them);
#   - Give: the same page, payment and script (giving_router's, unchanged),
#     in the Lumen frame; the form keeps every id, class and value the give
#     script reads; the funds are chips that set the same <select>; the
#     thank-you is the mock's sheet holding the same #gv-thanks; Your giving
#     and Recurring gifts; one fund has no chips; the preview never charges;
#   - Watch: Watch & listen, the next live (or Live now), the latest with
#     Watch, Listen and Share, the series, every message; a series keeps
#     today's page;
#   - Live: the room keeps every id its script reads (instant send, hearts,
#     the poll, the pin, the sheets), Back and Live · N here on the video,
#     Give in the box (with I'm here when the chat is closed); between
#     services in Home's shapes;
#   - the same reads on and off; the tab bar and the top bar are solid.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import giving_router as gr
import member_app_ui as ui
import member_lumen_give as mlg
import member_lumen_ui as lm
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import _body_class, _client, _occ

TODAY = date.today()
SER = "00000000-0000-4000-8000-000000000501"
LIB = {"series": [{"id": SER, "title": "Light Has Come", "description": ""}],
       "sermons": [{"id": "00000000-0000-4000-8000-000000000601", "title": "Hope Has a Name", "series_id": SER,
                    "speaker": "Pastor James", "preached_on": (TODAY - timedelta(days=3)).isoformat(),
                    "scripture": "Isaiah 9:6", "audio_url": "https://example.test/a.mp3", "video_url": ""},
                   {"id": "00000000-0000-4000-8000-000000000602", "title": "A Light in the Dark", "series_id": SER,
                    "speaker": "Pastor James", "preached_on": (TODAY - timedelta(days=10)).isoformat(),
                    "scripture": "John 1:5", "audio_url": "", "video_url": ""}]}
LIVE = {"id": "00000000-0000-4000-8000-000000000901", "title": "Sunday Worship", "stream_url": "", "chat_open": True,
        "chat_version": 3, "started_at": datetime.now(timezone.utc).isoformat(), "hearts": 0, "pinned_message_id": None}


@pytest.fixture
def church(fake, monkeypatch):  # noqa: F811
    """Ana at a made-up church, giving on, with a small library. She picked
    Light for the new look (member_lumen_look; the church's base is today's
    black)."""
    fake.person(tct.ANA, "Ana Rivera")
    for c in fake.t["contacts"]:
        if c["id"] == tct.ANA:
            c["email"] = "ana@example.test"
            c["metadata"] = {"member_look": "light"}
    for t in ("live_chat", "live_presence", "live_mutes"):
        fake.t.setdefault(t, [])
    biz = fake.biz[tct.BIZ]
    biz["name"] = "Grace Fellowship"
    biz["stripe_account_id"] = "acct_test123"
    biz["settings"]["brand_kit"] = {"accent": "#D6246E"}
    biz["settings"]["giving"] = {"enabled": True, "funds": ["Tithes", "Missions", "Building Fund"]}
    scene = {"occ": [_occ("Sunday Worship", TODAY + timedelta(days=4), n=40)], "live": {}, "give": True,
             "lib": LIB}
    import member_portal_church as mpc
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [dict(o) for o in scene["occ"]])
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: scene["lib"])
    import live_router as lr
    monkeypatch.setattr(lr, "current", lambda b: scene["live"])
    monkeypatch.setattr(gr, "giving_is_active", lambda b: scene["give"])
    import member_portal_classes as mcl
    monkeypatch.setattr(mcl, "tab_on", lambda b, me: False)
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    monkeypatch.delenv("LIVE_ROOM", raising=False)
    return scene


def _get(fake, monkeypatch, path):  # noqa: F811
    return _client(fake, monkeypatch).get(path).text


def _ids(html):
    return set(re.findall(r'\bid="([^"]+)"', html))


# ─── off ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,live,give", [("/my/give", {}, True), ("/my/give", {}, False), ("/my/sermons", {}, True),
                                            ("/my/live", LIVE, True), ("/my/live", {}, True)])
def test_off_none_of_it_shows(church, fake, monkeypatch, path, live, give):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    church["live"], church["give"] = dict(live), give
    html = _get(fake, monkeypatch, path)
    assert "lm" not in _body_class(html).split()
    assert ui.sheet_url("lumen") not in html and 'class="lm-' not in html and "lm-" not in _body_class(html)


def test_off_give_page_is_todays(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _get(fake, monkeypatch, "/my/give")
    assert "<body>\n<main class=\"gv-shell\">" in html and ">Give</h1>" in html
    assert 'class="mb-tab" href="/my/give" aria-current="page"' in html                  # today's tab bar


# ─── Give ────────────────────────────────────────────────────────────


def test_give_wears_the_new_look_around_the_same_payment(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/give")
    assert _body_class(html).split()[:2] == ["lm", "lm-tab"]
    assert ui.sheet_url("lumen") in html and "--mbt-bg:#ffffff" in html
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'class="mb-brand lm-brand"' in top and 'href="/my/notifications"' in top and 'href="/my/me"' in top
    nav = html[html.index('<nav class="mb-nav lm-nav'):]
    assert 'href="/my/give" aria-current="page"' in nav[:nav.index("</nav>")]
    assert ui.EARLY_JS in html and lm.SCROLL_JS in html
    # The payment: the give page's own script, byte for byte, for the app.
    from business_sites_helpers import PUBLIC_DOMAIN  # noqa: F401
    import public_site
    script = gr._give_script(api_origin=public_site._EMBED_ORIGIN, slug="", embed_json="null", app=True)
    assert script in html
    assert "/public/giving/" in html and "return_to: APP ? 'app'" in html
    # The mock's layout, the church's own words.
    assert '<h1 class="lm-eyebrow lm-gvto">Give to Grace Fellowship</h1>' in html
    assert "Tithes · one time" in html
    chips = re.findall(r'<button type="button" class="lm-fchip[^"]*" data-fund="([^"]+)"', html)
    assert chips == ["Tithes", "Missions", "Building Fund"]
    assert '<div class="lm-fundsel" hidden>' in html and '<select id="gv-fund"' in html     # the script sends this
    assert "Receipt to <b>ana@example.test</b>" in html and 'value="ana@example.test"' in html
    assert 'href="/my/gifts"' in html and 'href="/my/me#mp-giving"' in html
    assert f"Your giving · {TODAY.year}" in html
    gave = html[html.index('<dialog class="lm-gave"'):html.index("</dialog>")]
    assert 'id="gv-thanks"' in gave and "Thank you, <em>Ana.</em>" in gave
    assert mlg.GIVE_JS in html
    head = html[:html.index("</head>")]
    assert ".lm " not in head and "lm-amt" not in head                                    # the look is in the file


def test_the_give_form_keeps_everything_the_script_reads():
    """Called like giving_router._give_body, the new form draws the same
    controls: every id, every gv- class, the amounts and frequencies."""
    biz = {"id": "b1", "name": "Grace", "settings": {"giving": {"funds": ["Tithes", "Missions"]}}}
    presets = "".join(f'<button type="button" class="gv-amt" data-cents="{p * 100}">${p:,}</button>' for p in (25, 50))
    funds = ('<label class="gv-label" for="gv-fund">Designate my gift to</label><select id="gv-fund" class="gv-input">'
             '<option value="Tithes">Tithes</option><option value="Missions">Missions Fund</option></select>')
    ways = '<section class="gv-ways"><a class="gv-way" data-way-base="x" data-way-amt>Cash App</a></section>'
    args = (presets, funds, "Secure.", "Ana", "ana@example.test")
    kw = {"pay_block": gr.PAY_WITH_BLOCK, "ways_block": ways}
    old, new = gr._give_body(*args, **kw), mlg.give_form(biz, {"name": "Ana Rivera"})(*args, **kw)
    assert _ids(old) <= _ids(new)
    gv = lambda h: set(re.findall(r"\bgv-[a-z-]+", " ".join(re.findall(r'class="([^"]*)"', h))))  # noqa: E731
    assert gv(old) <= gv(new)
    for attr in ("data-cents", "data-freq", "data-pay"):
        assert re.findall(rf'{attr}="([^"]+)"', old) == re.findall(rf'{attr}="([^"]+)"', new), attr
    assert 'aria-pressed="true">One time</button>' in new
    # Every element the script looks up by id is on the page.
    script = gr._give_script(api_origin="https://x", slug="s", embed_json="null", app=True)
    for i in re.findall(r"getElementById\('([^']+)'\)", script):
        assert f'id="{i}"' in new, i


def test_one_fund_has_no_chips_and_no_email_shows_the_fields(church, fake, monkeypatch):  # noqa: F811
    fake.biz[tct.BIZ]["settings"]["giving"]["funds"] = ["General"]
    for c in fake.t["contacts"]:
        if c["id"] == tct.ANA:
            c["email"] = ""
    html = _get(fake, monkeypatch, "/my/give")
    assert 'class="lm-fchip' not in html and 'id="gv-fund"' not in html
    assert "One time</p>" in html                                                         # no fund on the line
    assert "Receipt to" not in html and '<div class="lm-who is-open">' in html and 'id="gv-em"' in html


def test_the_preview_never_charges(church, fake, monkeypatch):  # noqa: F811
    import member_portal as mp
    import member_lumen
    import member_spaces as msp
    seen, space = member_lumen.CURRENT.set(True), msp.CURRENT.set({"space": "church"})
    try:
        biz = dict(fake.business(), name="Grace Fellowship")
        html = mp.render_give(biz, {"slug": "grace"}, {"id": tct.ANA, "name": "Ana Rivera", "email": "a@x.test"},
                              preview=True)
    finally:
        member_lumen.CURRENT.reset(seen)
        msp.CURRENT.reset(space)
    assert "PREVIEW = true" in html and "won't charge anything" in html.replace("&#x27;", "'")


def test_give_before_online_giving(church, fake, monkeypatch):  # noqa: F811
    church["give"] = False
    html = _get(fake, monkeypatch, "/my/give")
    assert _body_class(html).split()[:2] == ["lm", "lm-tab"]
    assert "Every gift <em>matters</em>" in html and "Give in person at any service." in html
    assert 'href="/my/me#mp-giving"' in html and "In person" in html


# ─── Watch ───────────────────────────────────────────────────────────


def test_watch(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/sermons")
    assert _body_class(html).split()[:3] == ["lm", "lm-tab", "pg-watch"]             # the cinema
    assert '<meta name="theme-color" content="#050506">' in html
    assert '<h1 class="mp-sr">Watch &amp; listen</h1>' in html                       # the bar says whose it is
    row = html[html.index('class="lm-nrow'):]
    assert row.startswith('class="lm-nrow" href="/my/live"') and "Next live" in row[:600] and "Sunday Worship" in row[:600]
    feat = html[html.index('class="lm-feat"'):]
    assert '<h2 class="lm-disp m" id="lm-feat-h">' in feat[:3000] and "Hope Has a <em>Name</em>" in feat[:3000]
    assert "Latest message · " in feat[:3000] and "Pastor James · Isaiah 9:6" in feat[:3000]
    assert 'class="lm-btn lm-light"' in feat[:3000]
    assert "Listen</a>" in feat[:3000]
    # Share is the new look's share sheet (member_lumen_share): the public message, its story picture.
    assert 'class="lm-share lm-btn ghost lm-sq" href="/sermons/' in feat[:3000] and 'data-share-kind="message"' in feat[:3000]
    posters = html[html.index('class="lm-rail lm-sposts"'):]
    assert f'class="lm-spost" href="/my/sermons?series={SER}"' in posters and "2 messages" in posters
    assert "Light Has <em>Come</em>" in posters
    assert html.count('class="lm-lrow"') == 2
    nav = html[html.index('<nav class="mb-nav lm-nav'):]
    assert 'href="/my/sermons" aria-current="page"' in nav[:nav.index("</nav>")]


def test_watch_while_live_and_with_nothing_posted(church, fake, monkeypatch):  # noqa: F811
    church["live"] = dict(LIVE)
    html = _get(fake, monkeypatch, "/my/sermons")
    assert 'class="lm-nrow is-live" href="/my/live"' in html and "Live now" in html
    church["live"], church["lib"] = {}, {"sermons": [], "series": []}
    html = _get(fake, monkeypatch, "/my/sermons")
    assert "Messages are on the <em>way</em>" in html and 'class="lm-feat"' not in html


def test_a_series_keeps_todays_page(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, f"/my/sermons?series={SER}")
    assert 'class="lm-feat"' not in html and 'class="mb-mtile-art"' in html
    assert "pg-watch" in _body_class(html)                                             # dark like Watch
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'class="mb-back" href="/my/sermons"' in top


# ─── Live ────────────────────────────────────────────────────────────


def test_the_room_keeps_every_id_its_script_reads(church, fake, monkeypatch):  # noqa: F811
    church["live"] = dict(LIVE)
    fake.add("live_presence", session_id=LIVE["id"], business_id=tct.BIZ, contact_id=tct.BEN,
             created_at=datetime.now(timezone.utc).isoformat())
    on = _get(fake, monkeypatch, "/my/live")
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    off = _get(fake, monkeypatch, "/my/live")
    assert _ids(off) - _ids(on) == {"lv-clock"}                                         # the clock's chip is Live · N here
    import member_portal_live as mpl
    assert mpl.ROOM_JS.split("__CFG__")[1] in on and '"instant": true' in on            # instant send, unchanged
    assert _body_class(on).split()[:2] == ["lm", "lm-push"]
    stage = on[on.index('<div class="lv-stage">'):on.index('<div class="lv-info">')]
    assert 'class="lm-lvback" href="/my/sermons"' in stage
    assert '<span id="lv-herewrap">· <b data-here-n>1</b> here</span>' in stage
    acts = on[on.index('<div class="lv-acts">'):on.index("</div>", on.index('<div class="lv-acts">'))]
    assert "Prayer" in acts and 'href="/my/give"' not in acts
    box = on[on.index('id="mb-compose"'):on.index("</form>", on.index('id="mb-compose"'))]
    assert 'class="lm-lvgive" href="/my/give"' in box and 'id="lv-send"' in box


def test_the_room_with_the_chat_closed_keeps_give_with_im_here(church, fake, monkeypatch):  # noqa: F811
    church["live"] = dict(LIVE, chat_open=False)
    import member_portal_live as mpl
    monkeypatch.setattr(mpl, "here_count", lambda b, sid: None)
    on = _get(fake, monkeypatch, "/my/live")
    acts = on[on.index('<div class="lv-acts">'):on.index("</div>", on.index('<div class="lv-acts">'))]
    assert 'class="lv-pill" href="/my/give"' in acts and "lm-lvgive" not in on
    assert '<span id="lv-herewrap" hidden>' in on                                         # never "0 here"


def test_between_services(church, fake, monkeypatch):  # noqa: F811
    html = _get(fake, monkeypatch, "/my/live")
    assert "Between <em>services</em>" in html and "No service is live right now." in html
    assert "Next service" in html and "Sunday Worship" in html
    assert "Last Sunday" in html or "Latest message" in html                              # the latest message
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'class="mb-back" href="/my/sermons"' in top


# ─── reads, the bars, the sheet ──────────────────────────────────────


@pytest.mark.parametrize("path,live,give", [("/my/give", {}, True), ("/my/give", {}, False), ("/my/sermons", {}, True),
                                            ("/my/live", LIVE, True), ("/my/live", {}, True)])
def test_the_same_reads_on_and_off(church, fake, monkeypatch, path, live, give):  # noqa: F811
    church["live"], church["give"] = dict(live), give
    reads = {}
    for mode in ("on", "off"):
        monkeypatch.setenv("MEMBER_LUMEN", mode)
        c = _client(fake, monkeypatch)
        c.get(path)                                                                       # warm what's kept
        fake.gets.clear()
        c.get(path)
        reads[mode] = Counter(r.split("?")[0] for r in fake.gets)
    assert reads["on"] == reads["off"], (reads["on"] - reads["off"], reads["off"] - reads["on"])


def _rule(css, selector):
    i = css.index(selector + "{")
    return css[i:css.index("}", i)]


def test_the_tab_bar_and_the_top_bar_are_solid():
    css = lm.css()
    nav = _rule(css, ".lm .mb-nav.lm-nav")
    assert "background:var(--bg)" in nav and "border-top:1px solid var(--lm-line)" in nav
    assert "var(--bar)" not in nav and "backdrop-filter:none" in nav
    top = _rule(css, ".lm .mb-top.is-solid")
    assert "background:var(--bg)" in top and "var(--bar)" not in top


def test_the_sheet_carries_the_give_watch_live_block():
    assert mlg.CSS.template in lm.css()
    text = ui.sheet("lumen")[0]
    assert ".lm .lm-amt{" in text and ".lm .lm-nrow{" in text and ".lm .lm-lvchip{" in text
    assert "$" not in mlg.CSS.template                                                     # no tokens to fill
