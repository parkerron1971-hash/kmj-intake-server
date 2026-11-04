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
  6. THE CHURCH PLANS BY SIZE: while PLAN_CHURCH_OFFERED is off the pages
     are what they were; on, the overview draws Small / Growing /
     Established / Large from the dials, the product pages' strips and
     plan prose follow, and the founding seat gives way to the move.
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
    monkeypatch.delenv("PLAN_CHURCH_OFFERED", raising=False)
    monkeypatch.delenv("CHURCH_OFFERED", raising=False)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])


def _all():
    return {cs.path_of(s): cs.render(s) for s in cs.PAGES}


# ─── 1. every page renders whole ────────────────────────────────────

def test_every_page_fills_every_token_and_drops_the_canvas():
    for path, html in _all().items():
        assert not re.search(r"\{\{\s*[A-Za-z_]+\s*\}\}", html), path
        assert "{{" not in html, path                                       # no section marker either
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


# ─── 6. the church plans by size ────────────────────────────────────

_SIZES = ("Up to 100 people on a Sunday", "100–250 people on a Sunday", "250–500 people on a Sunday",
          "500–1,500 people on a Sunday")


@pytest.fixture
def by_size(monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")


def _cards(html):
    start = html.index('<div class="plans four">')
    block = html[start:html.index("On every plan</b>", start)]
    return re.split(r'(?=<div class="pc[ "])', block)[1:]


def _strip(html):
    return re.search(r'<div class="planrow[^"]*">.*?\n</div>\n', html, flags=re.S).group(0)


def test_switched_off_the_pages_keep_the_public_ladder():
    assert not cs.plans_by_size()
    html = cs.render("")
    assert '<div class="plans">' in html and 'class="plans four"' not in html
    assert "Every plan is <b" in html and "Priced by" not in html
    for name in ("Starter", "Professional", "Solutionist"):
        assert f'<span class="pname">{name}</span>' in html, name
    assert "Small Church" not in html and "Multi-site" not in html
    assert "on Starter, " in html                                         # the conversations line
    for slug in cs.PRODUCTS:
        page = cs.render(slug)
        assert '<div class="planrow">' in page and 'class="planrow four"' not in page, slug
        assert '<span class="pn">Professional</span>' in page and "Small Church" not in page, slug


def test_switched_off_a_page_is_its_template_without_the_markers():
    """Off, a section's own words stand, character for character."""
    for slug, meta in cs.PAGES.items():
        raw = cs._read(meta["file"])
        assert cs._sections(raw) == cs._SECTION.sub(lambda m: m.group(2), raw)
        assert "{{#" not in cs._sections(raw) and "{{/" not in cs._sections(raw), slug


def test_every_section_has_words_for_the_church_plans(by_size):
    named = set()
    for meta in cs.PAGES.values():
        names = cs._SECTION.findall(cs._read(meta["file"]))
        assert names, meta["file"]
        named |= {n for n, _ in names}
    assert named == set(cs._by_size()), named ^ set(cs._by_size())


def test_the_overview_draws_four_plans_from_the_dials(by_size):
    html = cs.render("")
    cards = _cards(html)
    assert len(cards) == 4
    assert [re.search(r'class="pname">([^<]+)<', c).group(1) for c in cards] == [
        "Small Church", "Growing Church", "Established Church", "Large Church"]
    assert [c.startswith('<div class="pc mid">') for c in cards] == [False, True, False, False]   # Growing is lit
    for price, year in (("79", "790"), ("199", "1,990"), ("399", "3,990"), ("699", "6,990")):
        assert f'data-m="{price}" data-y="{year}">{price}<' in html, price
    for card, size, logins, texts, hours in zip(cards, _SIZES, (3, 8, 15, 35), ("500", "1,500", "3,000", "8,000"),
                                                (2, 5, 10, 20)):
        assert f'<div class="pds">{size}.</div>' in card
        assert f"<span>{logins} office logins</span>" in card
        assert f"<span>{texts} texts a month</span>" in card
        assert f"<span>Clips from {hours} hours of sermons a month</span>" in card
        assert "<span>Your own texting number and text-to-give</span>" in card
        assert "<span>Full books, budgets and the donors report</span>" in card
    assert [("an audit trail" in c.lower()) for c in cards] == [False, False, True, True]
    assert [("Up to 3 organizations, like a church and its school" in c) for c in cards] == [False, False, False, True]
    assert [re.search(r"Chief thinks <b>(\w+)</b>", c).group(1) for c in cards] == \
        ["Standard", "Advanced", "Maximum", "Maximum"]
    # Meters measured against the four church plans: 3,000 / 7,500 / 15,000 of 27,500.
    assert [re.search(r'class="mbar"><i style="width: (\d+)%"', c).group(1) for c in cards] == ["11", "27", "55", "100"]
    assert [re.search(r"<b>([\d,]+)</b><span>AI actions", c).group(1) for c in cards] == \
        ["3,000", "7,500", "15,000", "27,500"]
    # The heading, the lede and the conversations line speak in sizes.
    assert "Priced by <b style=\"font-weight: 600\">your church's size.</b>" in html
    assert "Your plan is set by how many people come on a Sunday" in html
    assert "about 250 conversations a month on Small, 625 on Growing, 1,250 on Established and 2,275 on Large" in html
    for gone in ("Starter", "Professional", "Every plan is <b", "Founding seat"):
        assert gone not in html, gone


def test_the_move_takes_the_founding_seats_place(by_size, monkeypatch):
    monkeypatch.setattr(v3, "_founder_state",
                        lambda: {"limit": 50, "taken": 3, "left": 47, "next": 4, "price": 99,
                                 "list_price": 149, "credits": 5000})
    html = cs.render("")
    assert "Founding seat" not in html and "Claim seat" not in html and "plan=founder" not in html
    assert ("Over 1,500 people or more than one campus? Multi-site starts at $999 a month. Extra texts are $20 per "
            "1,000. A text is up to 160 characters; a longer one counts as 2 or more. "
            "One more office login is $15 a month. Moving from another system costs three months of your "
            "plan, and the first five churches move free.") in html
    assert "On every plan</b>" in html                                      # the strip stays
    assert "no cut of giving" in html                                       # and the fine print


def test_what_a_text_is_is_said_once_under_the_plans(by_size):
    """Texts are counted by 160-character part (church_texts.py): the page
    says so once, under the cards, and not on every line that says texts."""
    unit = "A text is up to 160 characters; a longer one counts as 2 or more."
    html = cs.render("")
    assert html.count(unit) == 1
    assert html.index(unit) > html.index('<div class="plans four">')
    for slug in cs.PRODUCTS:
        assert unit not in cs.render(slug), slug


def test_switched_off_no_page_speaks_of_parts(monkeypatch):
    monkeypatch.delenv("PLAN_CHURCH_OFFERED", raising=False)
    for slug in cs.PAGES:
        assert "160 characters" not in cs.render(slug), slug
    assert "160 characters" not in mp.render_faq()


def test_moving_a_dial_moves_the_page(by_size, monkeypatch):
    monkeypatch.setenv("PRICE_TIER_CHURCH_GROWING_CENTS", "15900")
    monkeypatch.setenv("LIMIT_CHURCH_GROWING_SEATS", "9")
    monkeypatch.setenv("LIMIT_CHURCH_SMALL_TEXTS", "600")
    monkeypatch.setenv("LIMIT_CHURCH_LARGE_CLIP_HOURS", "1")
    monkeypatch.setenv("CREDITS_CHURCH_LARGE_CREDITS", "35000")
    monkeypatch.setenv("PRICE_MULTI_SITE_FROM_CENTS", "120000")
    monkeypatch.setenv("PRICE_EXTRA_LOGIN_CENTS", "1250")
    monkeypatch.setenv("LIMIT_FOUNDING_CHURCH_MOVES", "1")
    html = cs.render("")
    cards = _cards(html)
    assert 'data-m="159" data-y="1,590">159<' in html and 'data-m="199"' not in html
    assert "<span>9 office logins</span>" in cards[1] and "<span>600 texts a month</span>" in cards[0]
    assert "<span>Clips from 1 hour of sermons a month</span>" in cards[3]
    assert "<b>35,000</b>" in cards[3] and 'style="width: 43%"' in cards[2]  # 15,000 of 35,000
    assert "Multi-site starts at $1,200 a month" in html and "One more office login is $12.50 a month" in html
    assert "and the first church moves free." in html
    assert "$159" in cs.render("giving") and "9 office logins" in cs.render("member-app")


def test_the_product_pages_strips_follow(by_size):
    for slug in cs.PRODUCTS:
        page = cs.render(slug)
        strip = _strip(page)
        assert strip.startswith('<div class="planrow four">'), slug
        assert re.findall(r'<span class="pn">([^<]+)</span>', strip) == [
            "Small Church", "Growing Church", "Established Church", "Large Church"], slug
        assert re.findall(r'<span class="pp">\$(\d+) <small>', strip) == ["79", "199", "399", "699"], slug
        for words in (*_SIZES, "3 office logins", "8 office logins", "15 office logins", "35 office logins",
                      "1,500 texts a month", "7,500 AI actions a month", "Clips from 20 hours of sermons a month"):
            assert words in strip, (slug, words)
        assert strip.count('class="plan mid"') == 1 and '<div class="plan mid"><span class="pn">Growing' in strip
        for gone in ("Starter", "Professional", "Solutionist plan", "on Solutionist"):
            assert gone not in page, (slug, gone)
        assert 'href="/churches#pricing"' in page                           # Compare every plan stays


def test_the_plan_prose_is_held_to_the_gates(by_size):
    """The product pages say 'every plan' only where every church plan has
    it, and name the plans that carry the rest."""
    import feature_gates as fg
    every = ("vertical_ledgers", "period_close", "vertical_reports", "reports_full", "chief_bookkeeping",
             "site_concierge", "marketing_week", "ai_clips", "dedicated_sms_number")
    for feature in every:
        assert all(feature in fg.plan_features(p) for p in fg.CHURCH_PLANS), feature
    assert [("accountant_collaborator" in fg.plan_features(p)) for p in fg.CHURCH_PLANS] == [False, False, True, True]
    giving, books, site, app = (cs.render(s) for s in ("giving", "office-and-books", "website-and-sermons", "member-app"))
    assert "the books keep each restricted fund apart for you, on every plan" in giving
    assert "Month-end and year-end close on every plan" in giving and "990 prep on every plan" in giving
    assert "Budget against actual on every plan" in books
    assert "3 office logins on Small, 8 on Growing, 15 on Established and 35 on Large" in books
    assert "A seat for your accountant on Established and Large" in books
    assert "Established and Large add an audit trail and a seat for your accountant." in books
    assert books.count("<span>On every plan</span>") == 2                  # the close and Chief's sorting
    assert "<span>On every plan</span>" in site and "sermon clips are on every plan" in site
    assert "sign-in codes are texted from your church's own number" in app


def test_by_size_every_page_is_whole_true_and_linked(by_size):
    pages = _all()
    for path, html in pages.items():
        assert "{{" not in html, path
        assert brand_voice.offenses(html) == [], path
        for target in re.findall(r'href="(/churches[^"]*)"', html):
            page, _, anchor = target.partition("#")
            assert page in pages and (not anchor or f'id="{anchor}"' in pages[page]), (path, target)
        assert "love-city" not in html.lower(), path
    assert pages["/churches"].count('href="https://mysolutionist.app/start" class="pbtn"') == 4


def test_the_faq_says_how_logins_come(monkeypatch):
    html = mp.render_faq()
    assert "adds staff seats" not in html
    assert ("Office logins come with every plan: one on Starter, three on Professional and seven on "
            "Solutionist.") in html
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    html = mp.render_faq()
    assert ("Churches pick a plan by how many people come on a Sunday, and each plan comes with its office logins: "
            "3 on Small, 8 on Growing, 15 on Established and 35 on Large.") in html
    assert "Office logins come with every plan: one on Starter" not in html


def test_the_faq_says_what_a_text_is(monkeypatch):
    assert "texts a month" not in mp.render_faq()                         # no allowance off the church plans
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    html = mp.render_faq()
    assert ("never need one. Each plan comes with its texts a month too: 500 on Small, 1,500 on Growing, "
            "3,000 on Established and 8,000 on Large, and extra texts are $20 per 1,000. A text is up to "
            "160 characters; a longer one counts as 2 or more.</p>") in html
    assert html.count("A text is up to 160 characters") == 1
    monkeypatch.setenv("LIMIT_CHURCH_SMALL_TEXTS", "600")
    assert "600 on Small" in mp.render_faq()
    assert brand_voice.offenses(mp.render_faq()) == []
