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


# ── the tier table names the whole product (9/02) ─────────────────────
# The table used to be drawn from the gate map alone, so it could only
# describe DIFFERENCES — ten rows, every one of them accounting. Someone
# deciding whether $79 was worth it could not see that the thing sends
# invoices, texts, email or takes bookings. These pin both halves of the
# fix: the everyday product is on the page, and every ✓ still comes from
# the code rather than from a hand-typed guess.

def _gated_keys_on_the_table():
    """Every FEATURE_MIN_PLAN key the compare table places as a row."""
    return {source
            for _group, entries in marketing_pages._COMPARE_GROUPS
            for _label, source, _note in entries
            if isinstance(source, str) and source != marketing_pages._ALL}


def test_compare_table_names_the_everyday_product():
    """The rows a buyer is actually shopping for. Each of these is a
    shipped surface with no gate behind it, which is exactly why the
    old map-driven table could not show them."""
    html = marketing_pages.render_compare()
    for row in ("Contacts &amp; CRM",
                "Invoices &amp; estimates",
                "Card payments &amp; checkout",
                "Text messaging (SMS)",
                "Calendar &amp; self-serve booking page",
                "Documents &amp; e-signature",
                "Expenses &amp; receipt capture",
                "Products, services &amp; online store",
                "Inventory &amp; stock counts",
                "Projects, tasks &amp; billable time",
                "Intake forms &amp; lead capture",
                "Brand kit",
                "Facebook &amp; Instagram publishing",
                "Autopilot",
                "Guided setup",
                "Your data stays yours"):
        assert row in html, row
    # Email is written with an em dash in the label; match the stem.
    assert "Email &mdash; send, receive, templates" in html
    # The bands that make forty rows readable.
    for group in ("The day-to-day work", "Your presence",
                  "Chief, your AI Chief of Staff", "Books, tax &amp; compliance",
                  "Room to grow"):
        assert group in html, group


def test_every_gate_is_placed_on_the_compare_table():
    """THE DRIFT GUARD. A new entry in FEATURE_MIN_PLAN is a new tier
    difference; if nobody decides where it belongs on this table it
    simply does not render, and the rows around it — which say "on
    every plan" — start quietly lying about a capability that now has a
    gate. Failing here forces the decision. To retire a key from the
    table on purpose, name it in marketing_pages._NOT_A_ROW."""
    expected = set(feature_gates.FEATURE_MIN_PLAN) - set(marketing_pages._NOT_A_ROW)
    assert _gated_keys_on_the_table() == expected


def test_every_gated_row_reads_the_map_and_not_a_guess(monkeypatch):
    """Rehearse the alarm: move a top-tier gate down to Starter and the
    Starter column must gain its ✓. If this passes with the map
    patched, the ticks are hand-typed and the table is decoration."""
    def starter_col(html):
        row = html.split("Audit trail")[1].split("</tr>")[0]
        return row.split("<td")[1]

    before = starter_col(marketing_pages.render_compare())
    assert 'class="alt"' in before          # practice-only today

    patched = dict(feature_gates.FEATURE_MIN_PLAN)
    patched["audit_trail"] = "starter"
    monkeypatch.setattr(feature_gates, "FEATURE_MIN_PLAN", patched)
    assert 'class="sol"' in starter_col(marketing_pages.render_compare())


def test_compare_table_never_leaks_a_raw_key_or_an_unrendered_token():
    html = marketing_pages.render_compare()
    for key in feature_gates.FEATURE_MIN_PLAN:
        assert key not in html, key
    # The trial token is substituted by the shell, including inside the
    # new note lines.
    assert marketing_pages.TRIAL_TOKEN not in html
