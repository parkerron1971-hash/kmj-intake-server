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
    assert "Claude Fable 5" in html            # the ladder reaches the page
    # Claims the product cannot back stay off the page.
    assert "priority onboarding" not in html
    assert "no seat math" not in html.lower()


def test_compare_page_has_the_tier_table():
    html = marketing_pages.render_compare()
    credits = pricing_config.tier_credits()
    assert f"{credits['practice']:,}" in html
    for label in ("Claude Sonnet 5", "Claude Opus 4.8", "Claude Fable 5"):
        assert label in html
    assert "Team seats" in html
    assert "Bank connections" in html
    assert "Audit trail" in html               # feature rows from the map
    # No raw feature keys leak onto the page.
    assert "vertical_reports" not in html
    assert "accountant_collaborator" not in html


def test_model_kill_switch_drops_the_model_lines(monkeypatch):
    """A CHIEF_MODEL_DEEP override disables the tier ladder, so the
    site must stop advertising per-tier models while it is set."""
    monkeypatch.setenv("CHIEF_MODEL_DEEP", "claude-sonnet-5")
    assert "Deep analysis by" not in marketing_pages.render_home()
    assert "Claude Fable 5" not in marketing_pages.render_compare()


def test_faq_publishes_the_ladder_and_drops_the_contradictions():
    html = marketing_pages.render_faq()
    assert "$79" in html and "$199" in html and "$399" in html
    assert "Pricing is coming" not in html
    assert "no seat math" not in html.lower()
    assert "team seats" in html                # the team answer tells the truth
