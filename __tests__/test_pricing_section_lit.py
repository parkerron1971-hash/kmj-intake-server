"""
test_pricing_section_lit.py — the pricing section, lit (2026-09-04).

What must hold:
  1. THE FOUNDER STRIP READS THE REAL COUNT: the same businesses query
     checkout enforces, cached; "N of 50 seats left" moves with it;
     zero flips the strip to "gone" and drops the button; no founder
     price on the server means no strip at all.
  2. ONE CARD IS LIT: Professional carries the ribbon and the grid the
     lit class; the other two do not.
  3. THE WORDS UNDER THE CREDITS come from the dials: conversations at
     the chat price, a build at the build price, and Chief works
     between them on the plans where the standing agent has headroom.
  4. THE ANNUAL FIGURE is ten months over twelve, carried on the same
     element the count-up reads, and the monthly figure is still the
     default the older tests pin.
  5. THE GRABBER AND THE HEADLINE are on the page; no vendor is named
     (the existing suite covers that).
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import marketing_pages as mp
import pricing_config


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setitem(mp._FOUNDER_CACHE, "at", 0.0)
    yield


def _pricing(html: str) -> str:
    i = html.index('id="pricing"')
    return html[i:i + 12000]


# ─── 1. the founder strip ────────────────────────────────────────────

def test_the_strip_reads_the_live_count(monkeypatch):
    import sb_clients
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: ["price_f", "price_fa"])
    monkeypatch.setattr(stripe_billing, "_founder_seat_limit", lambda: 50)
    seen = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: seen.append(p) or [{"id": i} for i in range(7)])
    seg = _pricing(mp.render_home())
    assert 'id="founderStrip"' in seg and 'data-left="43"' in seg and "43 of 50 seats left" in seg
    assert "subscription_plan=in.(price_f,price_fa)" in seen[0] and "active,trialing,past_due" in seen[0]
    price = pricing_config.tier_price_cents()["founder"] // 100
    assert f"50 founding seats at ${price} a month" in seg
    assert f"{pricing_config.founder_credits():,} AI actions a month" in seg
    assert 'href="/start?plan=founder"' in seg
    assert "locked for as long as you keep it" in seg
    # cached: a second render does not hit the database again
    mp.render_home()
    assert len(seen) == 1


def test_zero_left_is_gone_and_no_price_is_no_strip(monkeypatch):
    import sb_clients
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: ["price_f"])
    monkeypatch.setattr(stripe_billing, "_founder_seat_limit", lambda: 50)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": i} for i in range(50)])
    seg = _pricing(mp.render_home())
    assert "founder is-gone" in seg and "The 50 founding seats are gone" in seg
    assert "Take a founding seat" not in seg and 'data-left="0"' in seg
    monkeypatch.setitem(mp._FOUNDER_CACHE, "taken", None)
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    seg = _pricing(mp.render_home())
    assert "founderStrip" not in seg, "no founder price on the server: the section is the three cards"


def test_a_database_error_never_breaks_the_page(monkeypatch):
    import sb_clients
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: ["price_f"])

    def _boom(p):
        raise RuntimeError("down")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    seg = _pricing(mp.render_home())
    assert "founderStrip" not in seg and "price-card is-mid" in seg


# ─── 2. one card is lit ──────────────────────────────────────────────

def test_one_card_is_lit(monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    seg = _pricing(mp.render_home())
    assert seg.count("Most people land here") == 1 and "is-lit-grid" in seg
    mid = seg[seg.index('price-card is-mid'):]
    assert mid.index("ribbon") < mid.index("price-name")
    assert seg.count('class="price-card"') == 2


# ─── 3. the words under the credits ──────────────────────────────────

def test_the_words_come_from_the_dials(monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    seg = _pricing(mp.render_home())
    words = re.findall(r"<small>([^<]+)</small>", seg)
    credits = pricing_config.tier_credits()
    per = pricing_config.chat_price()
    build = pricing_config.build_base()
    assert words[0] == f"about {mp._about(credits['starter'] // per):,} conversations, or a site build and {mp._about((credits['starter'] - build) // per):,}"
    assert words[1].startswith(f"about {mp._about(credits['professional'] // per):,} conversations") and "Chief works between them" in words[1]
    assert "three site builds" in words[2]
    assert "Chief works between them" not in words[0]
    assert mp._credits_in_words(3000, chief_works=False) == "about 250 conversations, or a site build and 200"
    assert mp._credits_in_words(7500, chief_works=True) == "about 625 conversations, or a site build and 575 &mdash; and Chief works between them"
    assert mp._credits_in_words(17500, chief_works=True, builds=3) == "about 1,450 conversations, or three site builds and 1,300 &mdash; and Chief works between them"


# ─── 4. the annual figure ────────────────────────────────────────────

def test_the_annual_figure_is_ten_months_over_twelve(monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    seg = _pricing(mp.render_home())
    prices = pricing_config.tier_price_cents()
    for plan in ("starter", "professional", "practice"):
        monthly = prices[plan] // 100
        annual_total = monthly * mp.ANNUAL_MONTHS
        assert f'data-monthly="{monthly}" data-annual="{annual_total // 12}"' in seg, plan
        assert f'data-annual="${annual_total:,} a year, billed once"' in seg, plan
        assert f'data-to="{monthly}" data-prefix="$">${monthly}</b>' in seg, "monthly stays the default"
    assert 'data-period="annual"' in seg and "2 months free" in seg


# ─── 5. the grabber ──────────────────────────────────────────────────

def test_the_grabber_and_the_headline(monkeypatch):
    import stripe_billing
    monkeypatch.setattr(stripe_billing, "_founder_price_ids", lambda: [])
    seg = _pricing(mp.render_home())
    assert "Chief works while you work" in seg and "every plan, from day one" in seg
    assert "A chief of staff who never clocks out" in seg
    assert "Priced for one person running the whole thing" not in seg
    assert "Connect your own AI, read-only" in seg and seg.count("Your own AI can keep records here") == 2
