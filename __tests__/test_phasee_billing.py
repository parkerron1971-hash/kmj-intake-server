"""Phase E — billing tiers + feature gates (gate-ready, UNENFORCED)."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import feature_gates as fg
import stripe_billing as sb


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("BILLING_ENFORCE", "STRIPE_PRICE_ID_STARTER", "STRIPE_PRICE_ID_PROFESSIONAL",
              "STRIPE_PRICE_ID_PRACTICE", "STRIPE_PRICE_ID_DEFAULT", "BILLING_TRIAL_DAYS"):
        monkeypatch.delenv(k, raising=False)


def test_unenforced_everything_allowed():
    """The pricing ruling: gates exist but are dormant — everyone gets
    everything, even with no subscription at all."""
    assert fg.enforcement_on() is False
    assert fg.has_feature(None, "general_ledger") is True
    assert fg.has_feature({"subscription_status": None}, "accountant_package") is True
    ent = fg.entitlements({"subscription_status": None})
    assert ent["enforce"] is False
    assert all(f["allowed"] for f in ent["features"].values())


def test_enforced_rank_logic(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")
    starter = {"subscription_status": "active", "subscription_plan": "price_starter"}
    pro = {"subscription_status": "active", "subscription_plan": "price_pro"}
    practice = {"subscription_status": "trialing", "subscription_plan": "price_practice"}
    lapsed = {"subscription_status": "past_due", "subscription_plan": "price_practice"}
    # Tier ladder.
    assert fg.has_feature(starter, "bookkeeping_basic") is True
    assert fg.has_feature(starter, "general_ledger") is False
    assert fg.has_feature(pro, "general_ledger") is True
    assert fg.has_feature(pro, "accountant_package") is True    # pricing review: pro
    assert fg.has_feature(pro, "multi_seat") is False
    assert fg.has_feature(practice, "multi_seat") is True
    # Trialing counts as good standing; past_due does not.
    assert fg.plan_of(practice) == "practice"
    assert fg.plan_of(lapsed) is None
    assert fg.has_feature(lapsed, "general_ledger") is False
    # Unknown features fail open even when enforcing.
    assert fg.has_feature(starter, "some_future_feature") is True


def test_price_to_plan_with_legacy_default(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_DEFAULT", "price_legacy")
    m = fg.price_to_plan()
    assert m["price_pro"] == "professional"
    assert m["price_legacy"] == "professional"   # legacy single plan maps to pro


def test_price_for_plan_resolution(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")
    monkeypatch.setenv("STRIPE_PRICE_ID_DEFAULT", "price_default")
    assert sb._price_for_plan("practice") == "price_practice"
    assert sb._price_for_plan("starter") == "price_default"   # unset tier → default
    assert sb._price_for_plan(None) == "price_default"


def test_trial_only_for_first_subscription(monkeypatch):
    class _U:
        id = "u1"
    fresh = {"id": "biz1", "stripe_subscription_id": None}
    returning = {"id": "biz1", "stripe_subscription_id": "sub_old"}
    d1 = sb._subscription_data(fresh, _U())
    assert d1.get("trial_period_days") == 14            # default trial
    d2 = sb._subscription_data(returning, _U())
    assert "trial_period_days" not in d2                 # no second trial
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "30")
    assert sb._subscription_data(fresh, _U())["trial_period_days"] == 30
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "0")
    assert "trial_period_days" not in sb._subscription_data(fresh, _U())


def test_entitlements_shape(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    biz = {"subscription_status": "active", "subscription_plan": "price_pro"}
    ent = fg.entitlements(biz)
    assert ent["plan"] == "professional"
    gl = ent["features"]["general_ledger"]
    assert gl["allowed"] is True                # unenforced
    assert gl["included_in_plan"] is True       # and would be included anyway
    ms = ent["features"]["multi_seat"]
    assert ms["allowed"] is True                # unenforced
    assert ms["included_in_plan"] is False      # but practice-tier once enforced


def test_plan_limits_unenforced_then_enforced(monkeypatch):
    biz = {"subscription_status": "active", "subscription_plan": "price_starter"}
    assert fg.limit_for(biz, "chief_messages_monthly") is None   # unenforced = unlimited
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    # The grant is a DIAL (2026-08-08 config-driven launch) — assert it
    # tracks config, not a literal that a tuning pass would invalidate.
    import pricing_config as pc
    assert (fg.limit_for(biz, "chief_messages_monthly")
            == pc.tier_credits()["starter"])
    assert fg.limit_for(biz, "max_businesses") == 1
    pro = {"subscription_status": "active", "subscription_plan": "price_pro"}
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    assert (fg.limit_for(pro, "chief_messages_monthly")
            == pc.tier_credits()["professional"])
    # Ranking must hold whatever the dials say.
    assert (pc.tier_credits()["starter"] < pc.tier_credits()["professional"]
            < pc.tier_credits()["practice"])


def test_plans_payload_carries_the_offer_numbers(monkeypatch):
    """The pricing review found the actual tier deltas (credits, seats,
    businesses, banks, model) lived only in Mission Control — the plan
    card showed none of them. /billing/plans now carries plan_details so
    the card can say what the money buys."""
    import asyncio
    import pricing_config as pc
    for k in ("STRIPE_SECRET_KEY", "STRIPE_PRICE_ID_FOUNDER",
              "STRIPE_PRICE_ID_FOUNDER_ANNUAL", "CHIEF_MODEL_DEEP"):
        monkeypatch.delenv(k, raising=False)
    payload = asyncio.run(sb.billing_plans())
    details = payload["plan_details"]
    assert set(details) == set(fg.PLANS)
    # Numbers come from the dials, not literals a tuning pass would break.
    assert details["practice"]["credits_monthly"] == pc.tier_credits()["practice"]
    assert details["practice"]["max_seats"] == 5
    assert details["practice"]["max_businesses"] == 3
    assert details["practice"]["bank_connections"] is None        # unlimited
    assert details["professional"]["bank_connections"] == 5
    assert details["starter"]["max_seats"] == 1
    # The model ladder reaches the payload as display names.
    assert details["starter"]["deep_model"] == "Claude Sonnet 5"
    assert details["professional"]["deep_model"] == "Claude Opus 4.8"
    assert details["practice"]["deep_model"] == "Claude Fable 5"


def test_deep_model_label_honest_under_kill_switch(monkeypatch):
    """A CHIEF_MODEL_DEEP override disables the tier ladder in
    model_for(), so the plans payload must stop advertising per-tier
    models while it is set."""
    import chief_models
    monkeypatch.delenv("CHIEF_MODEL_DEEP", raising=False)
    assert chief_models.tier_deep_model_label("practice") == "Claude Fable 5"
    monkeypatch.setenv("CHIEF_MODEL_DEEP", "claude-sonnet-5")
    assert chief_models.tier_deep_model_label("practice") is None
    assert chief_models.tier_deep_model_label("starter") is None
