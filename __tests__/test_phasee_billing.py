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
    assert fg.limit_for(biz, "chief_messages_monthly") == 75   # Arc 19 locked
    assert fg.limit_for(biz, "max_businesses") == 1
    pro = {"subscription_status": "active", "subscription_plan": "price_pro"}
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    assert fg.limit_for(pro, "chief_messages_monthly") == 350   # Arc 19 locked
