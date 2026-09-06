"""The founding-seat flyer (marketing_founder_ad.py).

What must hold:
  1. IT CARRIES THE LIVE DEAL: the same seat count the strip reads, the
     founding price, the list price it beats, the credits, and the one
     link that takes the seat. Hidden until the script opens it, and a
     real dialog (role, label, close, focus target).
  2. IT IS GONE WHEN THE DEAL IS GONE: zero seats, no founder price, or
     a database error — no dialog, and the page still renders.
  3. IT STAYS OFF THE PAGES WHERE IT WOULD BE IN THE WAY: the contact
     form carries nothing; the reading pages and the news carry it.
  4. THE SCRIPT REMEMBERS: it keys storage, waits before showing, and
     honours the preview switch.
  5. NO STRAY WORDS: nothing in the flyer names a vendor model, and the
     word the About rewrite retired stays retired.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import marketing_founder_ad as fad
import marketing_pages as mp
import pricing_config


@pytest.fixture
def seats(monkeypatch):
    """Seven of fifty taken, price configured, cache cleared."""
    import sb_clients
    import stripe_billing
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: ["price_f"])
    monkeypatch.setattr(stripe_billing, "_founder_seat_limit", lambda: 50)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": i} for i in range(7)])


def _ad(html: str) -> str:
    i = html.find('id="founderAd"')
    assert i > 0, "no flyer on the page"
    return html[i - 200:i + 6000]


# ─── 1. the live deal ────────────────────────────────────────────────

def test_the_flyer_carries_the_live_deal(seats):
    html = mp.render_home()
    seg = _ad(html)
    prices = pricing_config.tier_price_cents()
    price, lst = prices["founder"] // 100, prices["professional"] // 100
    assert 'data-left="43"' in seg and "<b>43</b> of 50 seats left" in seg
    assert f'<span class="fad-dollar">$</span>{price}<span class="fad-per">/mo</span>' in seg
    assert f"Professional is ${lst}" in seg
    assert f"${lst - price} a month less than the list price" in seg
    assert f"{pricing_config.founder_credits():,} AI actions a month" in seg
    assert 'href="/start?plan=founder"' in seg and "Take a founding seat" in seg
    # a real dialog, closed until the script says otherwise
    assert 'role="dialog"' in seg and 'aria-modal="true"' in seg
    assert 'aria-labelledby="founderAdTitle"' in seg and 'id="founderAdTitle"' in seg
    assert re.search(r'id="founderAd"[^>]*\bhidden\b', seg)
    assert 'id="founderAdClose"' in seg and 'aria-label="Close"' in seg
    markup = seg[:seg.index("<script>")]
    assert markup.count("data-fad-close") == 3, "scrim, X, and Not now all close it"
    assert 'id="founderAdCard" tabindex="-1"' in seg
    # the strip and the flyer read one query
    assert 'id="founderStrip"' in html and 'data-left="43"' in html[html.index('id="founderStrip"'):][:200]
    # styles and script ride with it
    assert ".fad-card{" in html and "id=\"founderAdCta\"" in html


# ─── 2. gone when the deal is gone ───────────────────────────────────

def test_zero_seats_means_no_flyer(seats, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": i} for i in range(50)])
    html = mp.render_home()
    assert 'id="founderAd"' not in html and ".fad-card{" not in html
    assert "founder is-gone" in html, "the strip still says the seats went; the flyer does not nag"


def test_no_founder_price_means_no_flyer(seats, monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    html = mp.render_home()
    assert 'id="founderAd"' not in html and "founderAdCta" not in html


def test_a_database_error_never_breaks_the_page(seats, monkeypatch):
    import sb_clients

    def _boom(p):
        raise RuntimeError("down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    html = mp.render_home()
    assert 'id="founderAd"' not in html and "price-card is-mid" in html


# ─── 3. which pages carry it ─────────────────────────────────────────

def test_the_reading_pages_carry_it_and_the_rest_do_not(seats):
    for render in (mp.render_home, mp.render_about, mp.render_features,
                   mp.render_compare, mp.render_faq, mp.render_download):
        assert 'id="founderAd"' in render(), f"{render.__name__} should carry the flyer"
    assert 'id="founderAd"' not in mp.render_get_started(), "not on top of the contact form"
    css, markup = fad.founder_ad_bundle("/privacy")
    assert css == "" and markup == ""


def test_the_news_carries_it_too(seats):
    """Kevin, 2026-09-06: 'add it to the news pages too' — the index and
    every post, whose addresses are /news/{slug}."""
    import site_news
    posts = site_news.normalize_posts([
        {"id": "a", "title": "Publish to your own site", "body": "The first paragraph.",
         "published_at": "2026-08-29T12:00:00Z"}])
    assert 'id="founderAd"' in mp.render_news_index(posts)
    assert 'id="founderAd"' in mp.render_news_index([])
    assert 'id="founderAd"' in mp.render_news_post(posts[0])
    assert fad.carries_the_flyer("/news/publish-to-your-own-site")
    assert not fad.carries_the_flyer("/newsletter")


# ─── 4. the script remembers ─────────────────────────────────────────

def test_the_script_waits_remembers_and_can_be_forced():
    s = fad.FOUNDER_AD_SCRIPT
    assert f"var KEY = '{fad.STORAGE_KEY}'" in s
    assert f"QUIET_MS = {fad.QUIET_DAYS} * 24 * 60 * 60 * 1000" in s
    assert f"setTimeout(open, {fad.SHOW_AFTER_MS})" in s and str(fad.MIN_DWELL_MS) in s
    assert f"indexOf('{fad.FORCE_PARAM}')" in s
    assert "if (!forced && seenRecently()) return;" in s
    assert "cta.addEventListener('click', remember)" in s
    assert "somethingElseIsOpen" in s and "videoModal" in s and "mobileMenu" in s
    assert "e.key === 'Escape'" in s


# ─── 5. no stray words ───────────────────────────────────────────────

def test_no_vendor_and_no_retired_word(seats):
    seg = _ad(mp.render_home())
    for bad in ("Claude", "Sonnet", "Opus", "Fable", "GPT-", "Gemini", "Founder "):
        assert bad not in seg, f"{bad!r} appears in the flyer"
