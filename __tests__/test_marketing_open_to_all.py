"""The marketing suite opens to every business (plan B14, 2026-10-08).

Kevin: "open to everyone because right now no one is using it so you can set
how it will work for everyone." Pinned here:
  1. Both switches are on when unset, and each is a kill switch
     (marketing_switches is their one reader).
  2. Chief's Thursday work is on for a business with no saved desk row, the
     rows the server makes write it on, and an owner who turned it off stays
     off.
  3. The three levels are announced: off the unannounced list and the
     compare table's skip list, on /compare, /features, the FAQ and
     /billing/plans, in feature_gates.MARKETING_LADDER's words, which match
     what each plan really includes.
  4. The public pages name no vendor and no longer send people to the old
     Facebook connection.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import business_marketing as bm  # noqa: E402
import feature_gates as fg  # noqa: E402
import marketing_pages as mp  # noqa: E402
import marketing_switches as ms  # noqa: E402
import stripe_billing as sb  # noqa: E402

BIZ = "11111111-2222-4333-8444-555555555555"
OTHER = "99999999-8888-4777-8666-555555555555"


@pytest.fixture(autouse=True)
def _clean_switches(monkeypatch):
    monkeypatch.delenv(ms.DESK_ENV, raising=False)
    monkeypatch.delenv(ms.PUBLISHING_ENV, raising=False)


# ─── 1. the switches ──────────────────────────────────────────────────

def test_unset_desk_covers_every_business():
    assert ms.desk_scope() == ms.EVERY
    assert ms.desk_names(BIZ) is True


@pytest.mark.parametrize("value", ["", "  ", "*", "on", "ON"])
def test_every_word_covers_every_business(monkeypatch, value):
    monkeypatch.setenv(ms.DESK_ENV, value)
    assert ms.desk_scope() == ms.EVERY
    assert ms.desk_names(BIZ) is True


@pytest.mark.parametrize("value", ["off", "OFF", "false", "no", "0"])
def test_off_is_the_kill_switch(monkeypatch, value):
    monkeypatch.setenv(ms.DESK_ENV, value)
    assert ms.desk_scope() is None
    assert ms.desk_names(BIZ) is False


def test_a_list_names_only_its_businesses(monkeypatch):
    monkeypatch.setenv(ms.DESK_ENV, f"{BIZ}, not-an-id")
    assert ms.desk_scope() == frozenset({BIZ})
    assert ms.desk_names(BIZ) is True
    assert ms.desk_names(OTHER) is False
    assert ms.desk_names("not-an-id") is False


def test_a_typo_never_widens_the_desk(monkeypatch):
    monkeypatch.setenv(ms.DESK_ENV, "evrey business")
    assert ms.desk_scope() is None
    assert ms.desk_names(BIZ) is False


def test_publishing_is_on_unless_it_says_off(monkeypatch):
    assert ms.publishing_on() is True
    assert bm.publishing_on() is True
    for value in ("off", "False", "no", "0"):
        monkeypatch.setenv(ms.PUBLISHING_ENV, value)
        assert ms.publishing_on() is False, value
        assert bm.publishing_on() is False, value
    monkeypatch.setenv(ms.PUBLISHING_ENV, "on")
    assert ms.publishing_on() is True


# ─── 2. Chief's Thursday work is on by default ────────────────────────

def test_no_saved_desk_means_the_plan_is_on():
    assert bm.DESK_DEFAULTS["plan_enabled"] is True
    assert bm.plan_on(None) is True
    assert bm.plan_on({}) is True


def test_an_owner_who_turned_it_off_stays_off():
    assert bm.plan_on({"plan_enabled": False}) is False
    assert bm.plan_on({"plan_enabled": True}) is True


def test_rows_the_server_makes_write_the_plan_on():
    # The column itself still defaults to false (no migration), so a new row
    # must say so out loud.
    assert bm.new_desk_row(BIZ) == {"business_id": BIZ, "plan_enabled": True}
    assert bm.new_desk_row(BIZ, plan_enabled=False, post_hour=9) == {
        "business_id": BIZ, "plan_enabled": False, "post_hour": 9}


def test_the_public_desk_reads_the_default_for_a_new_business():
    assert bm.public_desk(None)["plan_enabled"] is True


# ─── 3. announced, in words that match the plans ──────────────────────

LEVEL_KEYS = ("marketing_suggestion", "marketing_week", "marketing_autopilot")


def test_the_levels_are_announced():
    for key in LEVEL_KEYS:
        assert key not in fg.UNANNOUNCED_FEATURES, key
        assert key not in mp._NOT_A_ROW, key


def test_the_ladder_covers_every_plan_on_sale():
    assert set(fg.MARKETING_LADDER) == set(fg.PLANS) | {"solo", "booked", "boss"}


@pytest.mark.parametrize("plan,words", [
    ("starter", fg.MARKETING_SUGGEST_WORDS),
    ("solo", fg.MARKETING_SUGGEST_WORDS),
    ("booked", fg.MARKETING_SUGGEST_WORDS),
    ("professional", fg.MARKETING_WEEK_WORDS),
    ("boss", fg.MARKETING_OPENINGS_WORDS),
    ("practice", fg.MARKETING_AUTOPILOT_WORDS),
])
def test_each_plans_words_match_what_it_includes(plan, words):
    assert fg.MARKETING_LADDER[plan] == words
    feats = fg.plan_features(plan)
    assert "marketing_suggestion" in feats
    if words == fg.MARKETING_SUGGEST_WORDS:
        assert "marketing_week" not in feats and "marketing_autopilot" not in feats
    if words in (fg.MARKETING_WEEK_WORDS, fg.MARKETING_OPENINGS_WORDS):
        assert "marketing_week" in feats and "marketing_autopilot" not in feats
    if words == fg.MARKETING_AUTOPILOT_WORDS:
        assert "marketing_autopilot" in feats


def test_compare_features_and_faq_carry_the_ladder():
    compare, features, faq = mp.render_compare(), mp.render_features(), mp.render_faq()
    for words in (fg.MARKETING_SUGGEST_WORDS, fg.MARKETING_WEEK_WORDS, fg.MARKETING_AUTOPILOT_WORDS):
        assert words in compare, words
        assert words in features, words
        assert words in faq, words
    assert "Does anything post without my OK?" in faq
    assert "__MARKETING_LADDER__" not in features + faq
    assert "__SOCIAL_NETWORKS__" not in faq


def test_the_plans_endpoint_says_what_chief_does_per_plan(monkeypatch):
    async def no_display(pid):
        return {}
    monkeypatch.setattr(sb, "_price_display", no_display)

    async def no_founder():
        return {"configured": False}
    monkeypatch.setattr(sb, "_founder_summary", no_founder)
    plain = asyncio.run(sb.billing_plans())
    assert plain["marketing_by_plan"] == {p: fg.MARKETING_LADDER[p] for p in fg.PLANS}
    for plan in fg.PLANS:
        assert "marketing_suggestion" in plain["features_by_plan"][plan], plan
    monkeypatch.setenv("PLAN_BOSS_OFFERED", "1")
    barber = asyncio.run(sb.billing_plans(for_type="barber"))
    assert barber["marketing_by_plan"]["boss"] == fg.MARKETING_OPENINGS_WORDS


# ─── 4. honest public pages ───────────────────────────────────────────

def test_no_vendor_names_on_the_public_pages():
    # The posting service is plumbing, never a name on our pages. (Buffer does
    # appear, rightly: the compare page lists it among the tools we replace.)
    for html in (mp.render_compare(), mp.render_features(), mp.render_faq()):
        for vendor in ("Post for Me", "postforme"):
            assert vendor not in html, vendor


def test_the_faq_no_longer_points_at_the_old_facebook_connection():
    faq = mp.render_faq()
    assert "Integrations → Social Publishing" not in faq
    assert "Build → Social Media" in faq
