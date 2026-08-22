"""The public site's pricing surfaces must tell the product's truth.

The 8/18 pricing review found mysolutionist.app carried hand-typed
numbers and copy that contradicted the shipped product: "no seat math"
while Practice sells 5 seats, "priority onboarding" that does not
exist, and an FAQ claiming pricing was unpublished underneath a
homepage that published it. These tests pin the site to the same dials
the app reads (feature_gates.plan_limits / pricing_config /
chief_models), so a rescale flows through and a walked-back claim
cannot quietly return.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import feature_gates
import marketing_pages
import pricing_config


@pytest.fixture(autouse=True)
def _no_model_override(monkeypatch):
    monkeypatch.delenv("CHIEF_MODEL_DEEP", raising=False)


def test_home_price_cards_read_the_dials():
    html = marketing_pages.render_home()
    credits = pricing_config.tier_credits()
    for plan in ("starter", "professional", "practice"):
        assert f"{credits[plan]:,} AI actions" in html
    limits = feature_gates.plan_limits()
    assert f"{limits['practice']['max_seats']} team seats" in html
    assert f"{limits['practice']['max_businesses']} businesses" in html
    assert "Unlimited bank connections" in html
    assert "Maximum deep analysis" in html     # the ladder reaches the page
    # 2026-08-19 rename ruling: the top tier is the brand's namesake,
    # with Kevin's tagline under it so the name explains itself.
    assert '<div class="price-name">Solutionist</div>' in html
    assert '<div class="price-name">Practice</div>' not in html
    assert "operator running everything through the system" in html
    # Claims the product cannot back stay off the page.
    assert "priority onboarding" not in html
    assert "no seat math" not in html.lower()


def test_price_figure_and_its_countup_target_agree():
    """The figure counts up to data-to, so the two must be the same
    number. Both read one dial today, but a later edit could move the
    label and leave the target behind, and the card would animate up to
    a price the product does not charge.

    Added 2026-08-21 with the hover pass, because this suite went green
    with the displayed figure replaced by the word BROKEN: it pinned the
    credits, the seats and the businesses, and never the price."""
    html = marketing_pages.render_home()
    prices = pricing_config.tier_price_cents()
    for plan in ("starter", "professional", "practice"):
        dollars = prices[plan] // 100
        assert f'data-to="{dollars}" data-prefix="$">${dollars}</b>' in html, plan


def test_compare_page_has_the_tier_table():
    html = marketing_pages.render_compare()
    credits = pricing_config.tier_credits()
    assert f"{credits['practice']:,}" in html
    for label in ("Standard", "Advanced", "Maximum"):
        assert label in html
    assert "Team seats" in html
    assert "Bank connections" in html
    assert "Audit trail" in html               # feature rows from the map
    # No raw feature keys leak onto the page.
    assert "vertical_reports" not in html
    assert "accountant_collaborator" not in html


def test_public_pages_never_name_vendor_models():
    """Kevin's ruling 2026-08-19: the deep-analysis ladder is sold as a
    capability (Standard/Advanced/Maximum), never as vendor model names
    — providers will diversify beyond one vendor."""
    for html in (marketing_pages.render_home(), marketing_pages.render_compare(),
                 marketing_pages.render_faq()):
        for name in ("Claude", "Sonnet", "Opus", "Fable", "GPT-", "Gemini"):
            assert name not in html


def test_model_kill_switch_drops_the_analysis_lines(monkeypatch):
    """A CHIEF_MODEL_DEEP override disables the tier ladder — every
    tier runs the same model — so the site must stop advertising a
    per-tier analysis difference while it is set."""
    monkeypatch.setenv("CHIEF_MODEL_DEEP", "claude-sonnet-5")
    assert "deep analysis</li>" not in marketing_pages.render_home()
    assert "Maximum" not in marketing_pages.render_compare()


def test_faq_publishes_the_ladder_and_drops_the_contradictions():
    html = marketing_pages.render_faq()
    assert "$79" in html and "$199" in html and "$399" in html
    assert "Pricing is coming" not in html
    assert "no seat math" not in html.lower()
    assert "team seats" in html                # the team answer tells the truth
