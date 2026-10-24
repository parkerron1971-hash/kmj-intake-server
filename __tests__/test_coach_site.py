"""The coaches and consultants section of the public site (coach_site.py, 2026-10-23).

Holds:
  1. EVERY PAGE RENDERS WHOLE: no token left, no canvas leftovers, a
     phone viewport, and the brand voice (brand_voice.offenses).
  2. THE NUMBERS ARE THE PRODUCT'S: prices, AI actions, the trial and card
     wording and the founding seat come from the dials (church_site's
     helpers); the plan-card prose is pinned to feature_gates here, so
     moving a feature between plans fails until the pages move with it.
  3. THE LINKS GO SOMEWHERE: every /coaches link names a real page and a
     real anchor on it, and every page's Products menu lists all eight.
  4. THE ROUTES: on unless COACH_SITE=off; /consultants is the overview;
     switched off, both are the old edition and the product paths go to
     the catch-all as before.
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
import coach_site as cs  # noqa: E402
import marketing_home_v3 as v3  # noqa: E402
import marketing_pages as mp  # noqa: E402


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    import stripe_billing
    monkeypatch.delenv("COACH_SITE", raising=False)
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
                         'href="#signin"', 'href="#founder"', 'href="#churches"', "data-dc-script"):
            assert leftover not in html, (path, leftover)
        assert '<meta name="viewport" content="width=device-width,initial-scale=1.0">' in html, path
        assert f'<link rel="canonical" href="https://mysolutionist.app{path}">' in html, path
        assert html.count("<title>") == 1 and "Solutionist for Coaches and Consultants" in html, path


def test_every_page_speaks_in_the_voice():
    for path, html in _all().items():
        assert brand_voice.offenses(html) == [], path


def test_no_customer_photos():
    # the main site's own: its coach (p-maya, only ever "You") and the workshop
    allowed = {"/assets/home/p-maya.jpg", "/assets/home/w-workshop.jpg"}
    for path, html in _all().items():
        assert set(re.findall(r'<img[^>]*\ssrc="([^"]+)"', html)) <= allowed, path


def test_product_pages_carry_the_shared_style_and_their_own_light():
    for slug in cs.PRODUCTS:
        html = cs.render(slug)
        assert ".pbar{" in html and "--p:" in html, slug       # coach.css inlined, the page's own colour set


def test_the_billing_switch_parses():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    js = [s for s in re.findall(r"<script>(.*?)</script>", cs.render(""), flags=re.S) if "data-billing" in s]
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
    assert "<b>5,000</b><span>AI actions a month" in html and 'style="width: 25%"' in html
    for path, page in _all().items():
        for stale in ("$79", "$149", "$299", "3,000 AI actions", "7,500 AI actions", "17,500 AI actions"):
            assert stale not in page, (path, stale)


@pytest.mark.parametrize("no_card,days", [(True, 7), (False, 7), (False, 0)])
def test_the_trial_and_card_wording_follow_checkout(monkeypatch, no_card, days):
    monkeypatch.setattr(mp, "_no_card_trial_offered", lambda: no_card)
    monkeypatch.setattr(mp, "_trial_days", lambda: days)
    for path, html in _all().items():
        if no_card:
            assert "Start free, no card" in html, path
        else:
            assert "no card needed" not in html.lower() and "start free, no card" not in html.lower(), path
    if no_card:
        assert "7 days free, no card needed." in cs.render("")


def test_the_founding_seat_is_the_live_offer(monkeypatch):
    assert "Founding seat" not in cs.render("")                          # no founder price: no strip
    monkeypatch.setattr(v3, "_founder_state",
                        lambda: {"limit": 50, "taken": 3, "left": 47, "next": 4, "price": 99,
                                 "list_price": 149, "credits": 5000})
    html = cs.render("")
    assert 'href="/start?plan=founder"' in html and "Claim seat 04" in html


def test_the_plan_cards_match_the_gates():
    """Each line on a plan card is pinned to the plan that unlocks it, so a
    feature moving between plans fails here until the card moves too."""
    import chief_models
    import feature_gates as fg
    lim = fg.plan_limits()
    gate = fg.FEATURE_MIN_PLAN
    assert [lim[p]["max_seats"] for p in ("starter", "professional", "practice")] == [1, 3, 7]
    assert [lim[p]["plaid_connections"] for p in ("starter", "professional", "practice")] == [2, 5, None]
    assert [lim[p]["max_businesses"] for p in ("starter", "professional", "practice")] == [1, 1, 3]
    assert [chief_models.deep_analysis_label(p) for p in ("starter", "professional", "practice")] == \
        ["Standard", "Advanced", "Maximum"]
    for feature, plan in (("dedicated_sms_number", "professional"), ("period_close", "professional"),
                          ("contractor_payments", "professional"), ("site_concierge", "professional"),
                          ("marketing_week", "professional"), ("ai_clips", "practice"),
                          ("audit_trail", "practice"), ("accountant_collaborator", "practice"),
                          ("invoicing", "starter"), ("bookkeeping_basic", "starter")):
        assert gate.get(feature) == plan, feature
    cards = re.findall(r'<div class="pc(?: mid)?">.*?</ul>', cs.render(""), flags=re.S)
    assert len(cards) == 3
    starter, pro, sol = cards
    for words in ("Every part of your practice", "1 login", "Texts from our shared number", "Basic books",
                  "2 bank connections", "Chief thinks <b>Standard</b>"):
        assert words in starter, words
    for words in ("3 logins", "A texting number of your own", "Full books: month-end, year-end, and 1099s",
                  "Chief answers your website's visitors", "Chief plans your week of posts",
                  "5 bank connections", "Chief thinks <b>Advanced</b>"):
        assert words in pro, words
    for words in ("7 logins, and a seat for your accountant", "Short clips from your recordings",
                  "An audit trail of every change to a closed month", "Unlimited bank connections",
                  "Up to 3 businesses on one account",
                  "Chief thinks <b>Maximum</b>"):
        assert words in sol, words


def test_every_part_of_the_practice_is_on_every_plan():
    """The overview says every part comes with every plan: nothing that
    runs bookings, clients, proposals, invoices or classes is gated."""
    import feature_gates as fg
    gate = fg.FEATURE_MIN_PLAN
    for feature in ("booking", "bookings", "clients", "proposals", "contracts", "courses", "classes", "academy"):
        assert feature not in gate, feature
    assert gate["invoicing"] == gate["bookkeeping_basic"] == gate["marketing_suggestion"] == "starter"


# ─── 3. the links go somewhere ──────────────────────────────────────

def test_every_coach_link_is_a_real_page_and_anchor():
    pages = _all()
    for path, html in pages.items():
        for target in re.findall(r'href="(/coaches[^"]*)"', html):
            page, _, anchor = target.partition("#")
            assert page in pages, (path, target)
            if anchor:
                assert f'id="{anchor}"' in pages[page], (path, target)
        for anchor in re.findall(r'href="#([\w-]+)"', html):
            assert f'id="{anchor}"' in html, (path, anchor)


def test_every_page_has_the_products_menu_with_every_page():
    pages = _all()
    for path, html in pages.items():
        menu = re.search(r'<details class="pmenu">.*?</details>', html, flags=re.S)
        assert menu, path
        links = re.findall(r'<a href="(/coaches[^"]*)"( aria-current="page")?>', menu.group(0))
        assert [p for p, _ in links] == list(pages), path                   # all eight, in order
        assert [p for p, here in links if here] == [path], path            # this page marked


def test_the_pages_lead_to_the_churches_and_back_to_the_main_site():
    for path, html in _all().items():
        assert 'href="/churches"' in html and 'href="/"' in html, path


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
    for p in ("/coaches", "/coaches/{slug}", "/consultants"):
        assert p in paths and paths.index(p) < catch_all, p


def _req(path="/coaches/bookings"):
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": path, "query_string": b"",
                    "headers": [(b"host", b"mysolutionist.app")]})


OVERVIEW_LINE = b"Every part of your practice has"


def test_switched_on_the_pages_serve_and_join_the_sitemap(monkeypatch):
    ps = _public_site()

    async def no_site(request, **kw):
        return None
    monkeypatch.setattr(ps, "_site_response_or_none", no_site)
    for slug in cs.PRODUCTS:
        res = asyncio.run(ps.public_coach_page(_req(), slug))
        assert res.status_code == 200 and cs.PAGES[slug]["title"].split(" · ")[0].encode() in res.body, slug
    assert OVERVIEW_LINE in asyncio.run(ps.public_edition_coaches(_req("/coaches"))).body
    consult = asyncio.run(ps.public_edition_consultants(_req("/consultants"))).body
    assert OVERVIEW_LINE in consult and b'<link rel="canonical" href="https://mysolutionist.app/coaches">' in consult

    async def no_news():
        return []
    monkeypatch.setattr(ps, "_platform_news_posts", no_news)
    body = asyncio.run(ps.public_sitemap(_req())).body.decode()
    for slug in cs.PRODUCTS:
        assert f"https://mysolutionist.app/coaches/{slug}</loc>" in body, slug


def test_switched_off_nothing_changes(monkeypatch):
    ps = _public_site()
    monkeypatch.setenv("COACH_SITE", "off")

    async def no_site(request, **kw):
        return None
    seen = []

    async def catch_all(request, path):
        seen.append(path)
        return "catch-all"
    monkeypatch.setattr(ps, "_site_response_or_none", no_site)
    monkeypatch.setattr(ps, "subdomain_catch_all", catch_all)
    assert asyncio.run(ps.public_coach_page(_req(), "bookings")) == "catch-all" and seen == ["coaches/bookings"]
    assert OVERVIEW_LINE not in asyncio.run(ps.public_edition_coaches(_req("/coaches"))).body
    assert OVERVIEW_LINE not in asyncio.run(ps.public_edition_consultants(_req("/consultants"))).body
    monkeypatch.setenv("COACH_SITE", "on")
    assert asyncio.run(ps.public_coach_page(_req(), "not-a-room")) == "catch-all"

    async def no_news():
        return []
    monkeypatch.setenv("COACH_SITE", "off")
    monkeypatch.setattr(ps, "_platform_news_posts", no_news)
    assert "/coaches/bookings" not in asyncio.run(ps.public_sitemap(_req())).body.decode()


def test_the_section_is_on_unless_switched_off(monkeypatch):
    assert cs.enabled()
    for off in ("off", "OFF", "0", "false", "no"):
        monkeypatch.setenv("COACH_SITE", off)
        assert not cs.enabled(), off
