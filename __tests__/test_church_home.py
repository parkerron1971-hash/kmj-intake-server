"""The church page is the front door (church_site.is_home, 2026-11-04).

Kevin approved the church-first mock (claude.ai/artifact/CgBg3zVjHSQ2EFgaZyHdUy): "this design will work for
now. build it and merge it." On 2026-11-08 he approved the next round (claude.ai/artifact/ACaUESdWrwfCyh5ZsLYGQT,
version 8): the window hero, the week as seven windows and the rooms tour. "merge it. i think this is good"

Holds:
  1. THE FRONT DOOR: mysolutionist.app/ serves the church overview; HOME_EDITION=v3 or v2 (or the church
     section switched off) puts the business home back, with no deploy. The overview's canonical address
     follows: / while it's the home, /churches when it isn't. The product pages drop their "All of
     Solutionist" link while it would lead back to the church page.
  2. THE PAGE IS THE APPROVED DESIGN, AND ONLY IT: the window hero (each pane a room, named in the
     sentence in the same order and colour), why we exist, the week as seven windows, the rooms tour, the
     move, the size picker; none of the mock's own furniture (its bar, what's-new tags, the letter, the
     earlier heroes, the switches, the notes and their Listen button), no Love City and no founder by name.
     The tour says what each room's own page says: its headline is that page's h1.
  3. THE NUMBERS ARE THE PRODUCT'S: the size picker's plans, prices, logins, texts and Multi-site price
     come from the dials; the move's offer from church_offer(); the hero says "priced by the size of your
     Sunday" only while the plans by size are on sale, and the picker only shows then.
  4. THE SCRIPT RUNS: the overview's own script parses, and holds no template marker.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402

import church_site as cs  # noqa: E402
import marketing_pages as mp  # noqa: E402


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.setenv("CHURCH_SITE", "on")
    monkeypatch.delenv("HOME_EDITION", raising=False)
    monkeypatch.delenv("CHURCHSAVVY_URL", raising=False)
    monkeypatch.delenv("PLAN_CHURCH_OFFERED", raising=False)
    monkeypatch.delenv("CHURCH_OFFERED", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


@pytest.fixture
def by_size(monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")


# ─── 1. the front door ──────────────────────────────────────────────

def test_the_church_page_is_home_unless_an_edition_or_the_switch_says_otherwise(monkeypatch):
    assert cs.is_home()
    for edition in ("churches", " Churches "):
        monkeypatch.setenv("HOME_EDITION", edition)
        assert cs.is_home(), edition
    for edition in ("v3", "v2", "V3"):
        monkeypatch.setenv("HOME_EDITION", edition)
        assert not cs.is_home(), edition
    monkeypatch.delenv("HOME_EDITION")
    monkeypatch.setenv("CHURCH_SITE", "off")
    assert not cs.is_home()


def _root(monkeypatch):
    try:
        import public_site as ps
    except ImportError as e:
        pytest.skip(f"public_site needs {e.name}")
    from starlette.requests import Request
    req = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"",
                   "headers": [(b"host", b"mysolutionist.app")]})
    return asyncio.run(ps.subdomain_root(req)).body.decode()


def test_the_root_serves_the_church_page_and_rolls_back_without_a_deploy(monkeypatch):
    church = _root(monkeypatch)
    assert "Many pieces." in church and 'id="hero-rooms"' in church and 'id="mission"' in church
    monkeypatch.setenv("HOME_EDITION", "v3")
    business = _root(monkeypatch)
    assert "Many pieces." not in business and business == mp.render_home()
    monkeypatch.setenv("HOME_EDITION", "v2")
    assert "Many pieces." not in _root(monkeypatch)
    monkeypatch.delenv("HOME_EDITION")
    monkeypatch.setenv("CHURCH_SITE", "off")
    assert "Many pieces." not in _root(monkeypatch)


def test_one_address_for_the_overview(monkeypatch):
    assert '<link rel="canonical" href="https://mysolutionist.app/">' in cs.render("")
    monkeypatch.setenv("HOME_EDITION", "v3")
    assert '<link rel="canonical" href="https://mysolutionist.app/churches">' in cs.render("")


def test_no_link_leads_back_to_the_page_it_is_on(monkeypatch):
    for slug in cs.PRODUCTS:                                                     # the business home, by its own address
        assert '<a href="https://mysolutionist.app/business">All of Solutionist</a>' in cs.render(slug), slug
    overview = cs.render("")
    assert "All of Solutionist" not in overview and "Solutionist home" not in overview
    assert 'href="https://mysolutionist.app/coaches"' in overview                 # the coaches door, in the strip
    monkeypatch.setenv("HOME_EDITION", "v3")
    for slug in cs.PRODUCTS:                                                     # / while / is the business home
        assert '<a href="https://mysolutionist.app/">All of Solutionist</a>' in cs.render(slug), slug


# ─── 1b. the business home at /business ─────────────────────────────

def _ps():
    try:
        import public_site as ps
    except ImportError as e:
        pytest.skip(f"public_site needs {e.name}")
    return ps


def _get(ps, route, path):
    from starlette.requests import Request
    req = Request({"type": "http", "method": "GET", "path": path, "query_string": b"",
                   "headers": [(b"host", b"mysolutionist.app")]})
    return asyncio.run(route(req)).body.decode()


def test_the_business_home_has_its_own_address(monkeypatch):
    ps = _ps()
    page = _get(ps, ps.public_business_home, "/business")
    assert "Every problem" in page and "Many pieces." not in page
    assert '<link rel="canonical" href="https://mysolutionist.app/business">' in page
    assert '<meta property="og:url" content="https://mysolutionist.app/business">' in page
    assert 'href="https://mysolutionist.app/">' not in page                    # nothing in it points search at /
    monkeypatch.setenv("HOME_EDITION", "v3")                                    # rolled back: / is this page again
    page = _get(ps, ps.public_business_home, "/business")
    assert page == mp.render_home() and '<link rel="canonical" href="https://mysolutionist.app/">' in page


def test_the_business_route_is_ahead_of_the_catch_all():
    ps = _ps()
    paths = [getattr(r, "path", "") for r in ps.router.routes]
    assert "/business" in paths and paths.index("/business") < paths.index("/{path:path}")


def test_the_coach_pages_lead_to_the_business_home(monkeypatch):
    import coach_site
    for slug in coach_site.PAGES:
        page = coach_site.render(slug)
        assert 'href="https://mysolutionist.app/"' not in page, slug            # not the church page
        assert page.count('href="https://mysolutionist.app/business"') == 3, slug  # strip, footer twice
    monkeypatch.setenv("HOME_EDITION", "v3")
    assert 'href="https://mysolutionist.app/business"' not in coach_site.render("")


def test_the_sitemap_lists_business_only_while_the_church_page_is_home(monkeypatch):
    ps = _ps()

    async def no_news():
        return []
    monkeypatch.setattr(ps, "_platform_news_posts", no_news)
    assert "https://mysolutionist.app/business</loc>" in _get(ps, ps.public_sitemap, "/sitemap.xml")
    monkeypatch.setenv("HOME_EDITION", "v3")
    assert "/business</loc>" not in _get(ps, ps.public_sitemap, "/sitemap.xml")


def test_an_edition_sends_every_kind_of_business_to_the_business_home(monkeypatch):
    import marketing_home_v3
    assert f'href="/business">See every kind of business' in marketing_home_v3.render_edition("coaches")
    monkeypatch.setenv("HOME_EDITION", "v3")
    assert 'href="/">See every kind of business' in marketing_home_v3.render_edition("coaches")


# ─── 2. the approved design, and only it ────────────────────────────

def test_the_page_is_the_approved_design(by_size):
    html = cs.render("")
    for part in ('id="hero-rooms"', '<p class="hx-tag">Many pieces. One light.</p>', "Your whole church office, in one place.",
                 'id="mission"', "Grow.</b>", 'id="msn-map"', "No one unknown.", 'id="week" class="lw"', "Sunday is one day.",
                 'id="products" class="tour"', 'id="tourRose"', 'id="move"', 'id="picker"',
                 'No one unknown. No gift unused. <span class="serif glint"', 'class="glassbar"'):
        assert part in html, part
    order = [html.index(x) for x in ('id="hero-rooms"', 'id="mission"', 'id="week"', 'id="chief"', 'id="products"',
                                     'id="move"', 'id="pricing"', 'id="start"')]
    assert order == sorted(order)
    assert html.count('<button class="lwp-tab"') == 7 and html.count('<button class="tour-tab') == 8


def test_the_hero_names_the_rooms_in_the_windows_order(by_size):
    """The sentence under the headline and the tour name the same rooms, in the order the window's panes go
    round (People at the top, clockwise), so a pane, a word and a tab always mean the same room."""
    html = cs.render("")
    sub = re.search(r'<p class="hx-sub">(.*?)</p>', html, flags=re.S).group(1)
    said = re.findall(r'href="/churches/([a-z-]+)"', sub)
    tabs = re.findall(r'aria-controls="tourPanel\d"[^>]*>.*?<span>([^<]+)</span>', html, flags=re.S)
    assert said == ["people-and-care", "kids-and-youth", "giving", "groups-and-classes", "member-app",
                    "website-and-sermons", "office-and-books"]
    assert tabs == ["People", "Kids", "Giving", "Groups", "Member app", "Website", "Office", "Chief"]


def test_the_tour_says_what_each_room_page_says(by_size):
    """Each room in the tour carries its own page's headline, and links to that page."""
    html = cs.render("")
    for slug in ("people-and-care", "kids-and-youth", "giving", "groups-and-classes", "member-app",
                 "website-and-sermons", "office-and-books"):
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", cs.render(slug), flags=re.S).group(1)
        h1 = " ".join(re.sub(r"<[^>]+>", " ", h1).split())
        assert f"<h3>{h1}</h3>" in html, (slug, h1)
        assert f'class="tour-more" href="/churches/{slug}"' in html, slug


def test_the_member_app_and_the_office_live_in_the_tour(by_size):
    """The Member App and Office sections repeated the tour's rooms, so they were folded in (Kevin,
    2026-11-09). #app and #office still land: the menu and every room page's "Member app" link go to
    the tour, and the tour opens that room."""
    html = cs.render("")
    assert '<section id="app"' not in html and '<section id="office"' not in html
    tour = html[html.index('<section id="products" class="tour"'):]
    tour = tour[:tour.index("</section>")]
    assert 'id="app"' in tour and 'id="office"' in tour
    assert 'href="#app"' in html, "the menu's Member app link"
    assert "/churches#app" in cs.render("giving"), "the room pages' Member app link"
    src = (cs.DIR / "overview.js").read_text(encoding="utf-8")
    assert "'#app': 'app', '#office': 'office'" in src and "addEventListener('hashchange', fromHash)" in src
    for gone in ('class="ma-', 'class="oa', '.ma-hero{', '.oa-side{', '@keyframes toast'):
        assert gone not in html, gone


def test_the_window_film_and_the_tour_screens_are_served(by_size):
    """Every file the hero and the tour ask for is on disk and served from /assets/home/: the films with
    byte ranges (a phone won't play a video whose server ignores Range), the screens as webp. A name
    outside the pattern still can't reach anything."""
    try:
        import public_site as ps
    except ImportError as e:
        pytest.skip(f"public_site needs {e.name}")
    from starlette.requests import Request
    html = cs.render("")
    wanted = set(re.findall(r'/assets/home/([a-z0-9-]+\.(?:webp|jpg|mp4))', html))
    wanted |= {f"hero3-{k}-{p}-{s}.mp4" for k, s in (("wide", 1920), ("wide", 1280), ("square", 720)) for p in ("intro", "hold")}
    wanted |= {"hero3-wide-poster.jpg", "hero3-square-poster.jpg", "church-film.mp4", "church-film-poster.jpg"}
    for name in wanted:
        assert ps._home_asset_path(name) is not None, name
    for bad in ("../brand/favicon.png", "x.png", "tour-giving.WEBP", "church-film.mov", "..%2fchurch-film.mp4"):
        assert ps._home_asset_path(bad) is None, bad

    def req(headers=()):
        return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": list(headers)})
    film = asyncio.run(ps.asset_home_photo("church-film.mp4", req([(b"range", b"bytes=0-99")])))
    assert film.status_code == 206 and film.headers["content-range"].startswith("bytes 0-99/") and film.media_type == "video/mp4"
    assert asyncio.run(ps.asset_home_photo("tour-giving.webp", req())).media_type == "image/webp"
    assert asyncio.run(ps.asset_home_photo("p-james.jpg", req())).media_type == "image/jpeg"


def test_none_of_the_mock_furniture_and_no_one_named(by_size):
    html = cs.render("")
    for gone in ("newtag", "mockbar", "mb-hero", "mb-mid", "hero-v1", "hero-v2", "mid-letter", 'id="pastor"',
                 "Draft in your words", "churchHomeHero", "speechSynthesis", "Love City", "Kevin",
                 'class="ribbon"', "the church office", "Chief keeps the office", "dl-mock", "dlNotes",
                 'id="hero-v3"', 'id="wk-days"'):
        assert gone not in html, gone


# ─── 3. the numbers are the product's ───────────────────────────────

def _picker(html):
    return json.loads(re.search(r'<script type="application/json" id="pk-data">(.*?)</script>', html, flags=re.S).group(1))


def test_the_picker_draws_the_plans_from_the_dials(by_size):
    import feature_gates as fg
    import pricing_config
    d = _picker(cs.render(""))
    plans = fg.CHURCH_PLANS
    prices, bands, lim = pricing_config.church_price_cents(), pricing_config.church_size_bands(), fg.plan_limits()
    assert [p["name"] for p in d["plans"]] == [cs._name(p) for p in plans]
    for row, plan in zip(d["plans"], plans):
        assert row["m"] == f"${cs._dollars(prices[plan])}" and row["y"] == f"${cs._dollars(prices[plan] * mp.ANNUAL_MONTHS)}"
        assert row["max"] == bands[plan][1]
        assert f"{lim[plan]['max_seats']:,} office login" in row["items"][0]
        assert f"{lim[plan]['texts_monthly']:,} text" in row["items"][1]
    o = pricing_config.church_offer()
    assert d["multi"]["price"] == f"From ${cs._dollars(o['multi_site_from_cents'])}"
    assert d["top"] == max(h for _l, h in bands.values() if h)
    assert [s[0] for s in d["seg"]][0] == 0 and d["seg"][-1][1] == 980


def test_moving_a_dial_moves_the_picker(by_size, monkeypatch):
    import pricing_config
    real = pricing_config.church_price_cents
    monkeypatch.setattr(pricing_config, "church_price_cents", lambda: {**real(), "church_growing": 21900})
    html = cs.render("")
    assert _picker(html)["plans"][1]["m"] == "$219"
    assert '<b id="pk-price">$219</b>' in html                                   # the page opens on Growing


def test_the_picker_and_by_size_lines_only_while_the_plans_are_on_sale(monkeypatch):
    off = cs.render("")
    assert 'id="picker"' not in off and 'id="pk-data"' not in off
    assert "For churches of every size" in off and "priced by the size of your Sunday" not in off
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    on = cs.render("")
    assert 'id="picker"' in on and "For churches, priced by the size of your Sunday" in on and "Priced by your size" in on


@pytest.mark.parametrize("moves,months,free,after", [
    (5, 3, "The first five churches move free.",
     "<span>They also keep the price they start at, for as long as they stay. "
     "After that, the move is three months of your plan, paid once."),
    (1, 2, "The first church moves free.",
     "<span>It also keeps the price it starts at, for as long as it stays. "
     "After that, the move is two months of your plan, paid once."),
    (0, 3, "The move is three months of your plan, paid once.", "<span>People do it with you, by hand."),
    (0, 0, "Moving over is free.", "<span>People do it with you, by hand."),
])
def test_the_move_offer_is_church_offer(monkeypatch, moves, months, free, after):
    import pricing_config
    real = pricing_config.church_offer
    monkeypatch.setattr(pricing_config, "church_offer", lambda: {**real(), "founding_moves": moves, "move_months": months})
    html = cs.render("")
    assert f"<b>{free}</b>" in html and after in html
    # the founding churches keep their price only while there are founding churches
    kept = "keep the price they start at" in html or "keeps the price it starts at" in html
    assert kept == bool(moves)
    assert re.search(r'<span class="five" aria-hidden="true">((?:<i></i>)*)</span>', html).group(1) == "<i></i>" * min(moves, 5)


# ─── 4. the script runs ─────────────────────────────────────────────

def test_the_overview_script_parses_and_is_plain(by_size):
    js = cs._read("overview.js")
    assert "{{" not in js and "}}" not in js
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    res = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
