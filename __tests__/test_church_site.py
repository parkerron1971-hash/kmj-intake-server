"""The church section of the public site (church_site.py, 2026-10-23).

Holds:
  1. EVERY PAGE RENDERS WHOLE: no token left, no canvas leftovers, a
     phone viewport, and the brand voice (brand_voice.offenses).
  2. THE NUMBERS ARE THE PRODUCT'S: prices, yearly prices, AI actions,
     the trial and card wording and the founding seat come from the
     dials; the prose that names logins, banks and the depth ladder is
     pinned to the dials here, so changing a dial fails until the pages
     change with it.
  3. THE LINKS GO SOMEWHERE: every /churches link names a real page (and
     a real anchor on it); ChurchSavvy is linked only once it has a site.
  4. THE ROUTES: switched on, the section serves; switched off, /churches
     is the old edition and the product paths go to the catch-all as before.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
import shutil
import subprocess
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402

import brand_voice  # noqa: E402
import church_site as cs  # noqa: E402
import marketing_home_v3 as v3  # noqa: E402
import marketing_pages as mp  # noqa: E402


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.setenv("CHURCH_SITE", "on")
    monkeypatch.delenv("CHURCHSAVVY_URL", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


def _all():
    return {cs.path_of(s): cs.render(s) for s in cs.PAGES}


# ─── 1. every page renders whole ────────────────────────────────────

def test_every_page_fills_every_token_and_drops_the_canvas():
    for path, html in _all().items():
        assert not re.search(r"\{\{\s*[A-Za-z_]+\s*\}\}", html), path
        for leftover in (".dc.html", "/_blob/", "<x-dc>", "<helmet>", "support.js", 'href="#start"',
                         'href="#signin"', 'href="#founder"', "data-dc-script"):
            assert leftover not in html, (path, leftover)
        assert '<meta name="viewport" content="width=device-width,initial-scale=1.0">' in html, path
        assert f'<link rel="canonical" href="https://mysolutionist.app{path}">' in html, path
        assert html.count("<title>") == 1 and "Solutionist for Churches" in html, path


def test_every_page_speaks_in_the_voice():
    for path, html in _all().items():
        assert brand_voice.offenses(html) == [], path


def test_no_love_city_photos_and_one_photo_only():
    for path, html in _all().items():
        assert "love-city" not in html.lower() and "lovecity" not in html.lower(), path
        assert set(re.findall(r'<img[^>]*\ssrc="([^"]+)"', html)) <= {"/assets/home/p-james.jpg"}, path


def test_product_pages_carry_the_shared_style_and_their_own_light():
    for slug in cs.PRODUCTS:
        html = cs.render(slug)
        assert ".pbar{" in html and "--p:" in html, slug       # church.css inlined, the page's own colour set


def test_the_billing_switch_parses():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    html = cs.render("")
    js = [s for s in re.findall(r"<script>(.*?)</script>", html, flags=re.S) if "data-billing" in s]
    assert len(js) == 1
    res = subprocess.run(["node", "--check", "-"], input=js[0], capture_output=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr


# ─── 2. the numbers are the product's ───────────────────────────────

def test_prices_and_ai_actions_come_from_the_dials(monkeypatch):
    real = mp._tier_dials

    def dials():
        d = real()
        d["starter"].update(price_num=81, credits="2,000")
        d["professional"].update(price_num=151, credits="5,000")
        d["practice"].update(price_num=301, credits="20,000")
        return d
    monkeypatch.setattr(mp, "_tier_dials", dials)
    html = cs.render("")
    assert 'data-m="81" data-y="810">81<' in html and 'data-m="151" data-y="1,510">151<' in html
    assert 'data-m="301" data-y="3,010">301<' in html
    assert "<b>5,000</b><span>AI actions a month" in html and 'style="width: 100%"' in html
    assert 'style="width: 25%"' in html                                     # 5,000 of 20,000
    assert "$81" in cs.render("giving") and "$79" not in cs.render("giving")


@pytest.mark.parametrize("no_card,days", [(True, 7), (False, 7), (False, 0)])
def test_the_trial_and_card_wording_follow_checkout(monkeypatch, no_card, days):
    monkeypatch.setattr(mp, "_no_card_trial_offered", lambda: no_card)
    monkeypatch.setattr(mp, "_trial_days", lambda: days)
    for path, html in _all().items():
        if no_card:
            assert "Start free, no card" in html and "7 days free, no card needed." in html, path
        else:
            assert "no card needed" not in html.lower() and "start free, no card" not in html.lower(), path
    if not no_card and days:
        assert "7 days free, no card charged until the trial ends." in cs.render("")


def test_the_founding_seat_is_the_live_offer(monkeypatch):
    assert "Founding seat" not in cs.render("")                          # no founder price: no strip
    monkeypatch.setattr(v3, "_founder_state",
                        lambda: {"limit": 50, "taken": 3, "left": 47, "next": 4, "price": 99,
                                 "list_price": 149, "credits": 5000})
    html = cs.render("")
    assert 'href="https://mysolutionist.app/start?plan=founder"' in html and "<b style=\"color: #0B0C11\">47</b> of 50 seats left" in html
    assert "Claim seat 04" in html and "Professional for $99 a month" in html
    monkeypatch.setattr(v3, "_founder_state",
                        lambda: {"limit": 50, "taken": 50, "left": 0, "next": 50, "price": 99,
                                 "list_price": 149, "credits": 5000})
    assert "The 50 founding seats are gone." in cs.render("")


def test_the_prose_matches_the_plan_dials():
    """Logins, bank connections and the depth ladder are written into the
    pages; this fails the day a dial moves, so the words move with it."""
    import chief_models
    import feature_gates as fg
    lim = fg.plan_limits()
    assert [lim[p]["max_seats"] for p in ("starter", "professional", "practice")] == [1, 3, 7]
    assert [lim[p]["plaid_connections"] for p in ("starter", "professional", "practice")] == [2, 5, None]
    assert [chief_models.deep_analysis_label(p) for p in ("starter", "professional", "practice")] == \
        ["Standard", "Advanced", "Maximum"]
    html = cs.render("")
    for words in ("1 login", "3 logins", "7 logins, and a seat for your accountant", "2 bank connections",
                  "5 bank connections", "Unlimited bank connections", "Chief thinks <b>Standard</b>",
                  "Chief thinks <b>Advanced</b>", "Chief thinks <b>Maximum</b>"):
        assert words in html, words


def test_the_church_features_are_on_every_plan():
    """The overview says every part of church life comes with every plan."""
    import feature_gates as fg
    gated = set(fg.FEATURE_MIN_PLAN)
    for feature in ("giving", "kids_checkin", "member_app", "groups", "shepherding", "church_news"):
        assert feature not in gated, feature


# ─── 3. the links go somewhere ──────────────────────────────────────

def test_every_church_link_is_a_real_page_and_anchor():
    pages = _all()
    for path, html in pages.items():
        for target in re.findall(r'href="(/churches[^"]*)"', html):
            page, _, anchor = target.partition("#")
            assert page in pages, (path, target)
            if anchor:
                assert f'id="{anchor}"' in pages[page], (path, target)
        for anchor in re.findall(r'href="#([\w-]+)"', html):
            assert f'id="{anchor}"' in html, (path, anchor)


def test_churchsavvy_is_linked_only_once_it_has_a_site(monkeypatch):
    html = cs.render("")
    assert "Visit ChurchSavvy" not in html and "ChurchSavvy, our partner" not in html
    assert "Running Sunday's screens? Meet ChurchSavvy." in html             # the partner band stays
    monkeypatch.setenv("CHURCHSAVVY_URL", "https://churchsavvy.example")
    html = cs.render("")
    assert 'href="https://churchsavvy.example"' in html and "Visit ChurchSavvy" in html


# ─── 4. the routes ──────────────────────────────────────────────────

def _public_site():
    try:
        import public_site
    except ImportError as e:
        pytest.skip(f"public_site needs {e.name}")
    return public_site


def test_the_section_routes_sit_ahead_of_the_catch_all():
    ps = _public_site()
    paths = [getattr(r, "path", "") for r in ps.router.routes]
    catch_all = paths.index("/{path:path}")
    for p in ("/churches", "/churches/{slug}"):
        assert p in paths and paths.index(p) < catch_all, p


def _req():
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": "/churches/giving", "query_string": b"",
                    "headers": [(b"host", b"mysolutionist.app")]})


def test_switched_on_the_pages_serve_and_join_the_sitemap(monkeypatch):
    ps = _public_site()

    async def no_site(request, **kw):
        return None
    monkeypatch.setattr(ps, "_site_response_or_none", no_site)
    res = asyncio.run(ps.public_church_page(_req(), "giving"))
    assert res.status_code == 200 and b"Every gift goes to your church." in res.body
    res = asyncio.run(ps.public_edition_churches(_req()))
    assert b"Every part of church life has" in res.body

    async def no_news():
        return []
    monkeypatch.setattr(ps, "_platform_news_posts", no_news)
    body = asyncio.run(ps.public_sitemap(_req())).body.decode()
    for slug in cs.PRODUCTS:
        assert f"https://mysolutionist.app/churches/{slug}</loc>" in body, slug


def test_switched_off_nothing_changes(monkeypatch):
    ps = _public_site()
    monkeypatch.setenv("CHURCH_SITE", "off")

    async def no_site(request, **kw):
        return None
    seen = []

    async def catch_all(request, path):
        seen.append(path)
        return "catch-all"
    monkeypatch.setattr(ps, "_site_response_or_none", no_site)
    monkeypatch.setattr(ps, "subdomain_catch_all", catch_all)
    assert asyncio.run(ps.public_church_page(_req(), "giving")) == "catch-all" and seen == ["churches/giving"]
    res = asyncio.run(ps.public_edition_churches(_req()))
    assert b"Every part of church life has" not in res.body                 # the old church edition
    monkeypatch.setenv("CHURCH_SITE", "on")
    assert asyncio.run(ps.public_church_page(_req(), "not-a-room")) == "catch-all"

    async def no_news():
        return []
    monkeypatch.setenv("CHURCH_SITE", "off")
    monkeypatch.setattr(ps, "_platform_news_posts", no_news)
    assert "/churches/giving" not in asyncio.run(ps.public_sitemap(_req())).body.decode()


# ─── 5. getting there from mysolutionist.app ────────────────────────

def test_the_section_is_on_unless_switched_off(monkeypatch):
    monkeypatch.delenv("CHURCH_SITE", raising=False)
    assert cs.enabled()
    for off in ("off", "OFF", "0", "false", "no"):
        monkeypatch.setenv("CHURCH_SITE", off)
        assert not cs.enabled(), off


def test_every_church_page_has_the_products_menu_with_every_page():
    pages = _all()
    for path, html in pages.items():
        menu = re.search(r'<details class="pmenu">.*?</details>', html, flags=re.S)
        assert menu, path
        links = re.findall(r'<a href="(/churches[^"]*)"( aria-current="page")?>', menu.group(0))
        assert [p for p, _ in links] == list(pages), path                   # all eight, in order
        assert [p for p, here in links if here] == [path], path            # this page marked


def test_the_main_site_menus_lead_to_the_churches():
    home = v3.render_home_v3()
    for nav in (r'<nav class="links" aria-label="Main">.*?</nav>', r'<nav class="sheet" id="mobileMenu".*?</nav>'):
        block = re.search(nav, home, flags=re.S).group(0)
        assert 'href="/churches">Churches</a>' in block and 'href="/coaches">Coaches</a>' in block
    for page in (mp.render_features(), mp.render_compare(), mp.render_faq(), mp.render_about()):
        assert page.count('<a href="/churches">Churches</a>') == 2          # the top menu and the phone menu
