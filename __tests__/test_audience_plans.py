"""Solo / Booked / Boss — plans sold only to barbers and salons.

Kevin, 2026-10-04: Solo $49, Booked $79, Boss $99, for personal_services.
Pinned here:
  1. The public ladder answers exactly as before (plan_features == the old
     rank rule, feature by feature).
  2. Each audience plan carries its own list: Boss has Professional's
     bookkeeping but not Professional's AI surfaces.
  3. Limits fail CLOSED: a plan key with no limits entry gets Starter's,
     never unlimited AI.
  4. Prices, credits and the catalog hold the economics floors.
  5. Hidden until offered; only that kind of business can buy; a comp works
     on any business (the owner trying a plan on a test business).
  6. Checkout never falls back to Professional's price for an audience plan.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import feature_gates as fg  # noqa: E402
import pricing_config  # noqa: E402
import stripe_billing as sb  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402

USER = AuthedUser(id="u-1", email="a@b.test", role="authenticated")


# ─── 1. the public ladder is unchanged ────────────────────────────────

@pytest.mark.parametrize("plan", fg.PLANS)
def test_public_plans_answer_as_the_rank_rule_did(plan):
    old = {f for f, mp in fg.FEATURE_MIN_PLAN.items() if fg._PLAN_RANK[plan] >= fg._PLAN_RANK[mp]}
    assert set(fg.plan_features(plan)) == old


def test_unknown_plan_includes_nothing():
    assert fg.plan_features("platinum") == frozenset()
    assert fg.plan_features(None) == frozenset()


# ─── 2. each audience plan's own list ─────────────────────────────────

def test_solo_is_starter():
    assert fg.plan_features("solo") == fg.plan_features("starter")


def test_booked_adds_the_business_number():
    assert fg.plan_features("booked") == fg.plan_features("solo") | {"dedicated_sms_number"}


def test_boss_has_the_books_not_the_ai_surfaces():
    boss = fg.plan_features("boss")
    for f in ("period_close", "reports_full", "chief_bookkeeping", "accountant_package",
              "contractor_payments", "dedicated_sms_number"):
        assert f in boss, f
    for f in ("site_concierge", "sourcing_desk", "agent_connector_write", "vertical_ledgers",
              "vertical_reports", "multi_seat"):
        assert f not in boss, f


def test_every_listed_feature_is_a_real_gate():
    for plan, feats in fg.AUDIENCE_PLAN_FEATURES.items():
        assert feats <= set(fg.FEATURE_MIN_PLAN), plan


def test_has_feature_reads_the_plan_list_when_enforced(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    boss = {"comp_tier": "boss"}
    assert fg.has_feature(boss, "period_close")
    assert not fg.has_feature(boss, "site_concierge")
    assert not fg.has_feature({"comp_tier": "solo"}, "dedicated_sms_number")
    assert fg.has_feature({"comp_tier": "booked"}, "dedicated_sms_number")


def test_upgrade_prompt_stays_on_the_barber_ladder():
    assert fg.upgrade_plan_for("period_close", "solo") == "boss"
    assert fg.upgrade_plan_for("dedicated_sms_number", "solo") == "booked"
    assert fg.upgrade_plan_for("period_close", "starter") == "professional"
    ent = fg.entitlements({"comp_tier": "solo"})["features"]
    assert ent["period_close"]["min_plan"] == "boss"
    assert ent["period_close"]["included_in_plan"] is False
    assert ent["invoicing"]["included_in_plan"] is True


# ─── 3. limits fail closed ────────────────────────────────────────────

def test_every_plan_key_has_limits():
    limits = fg.plan_limits()
    for p in fg.ALL_PLANS:
        assert limits[p]["chief_messages_monthly"], p


def test_a_plan_without_limits_gets_starter_not_unlimited(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setattr(fg, "plan_of", lambda row: "platinum")
    starter = fg.plan_limits()["starter"]
    assert fg.limit_for({}, "max_seats") == starter["max_seats"]
    assert fg.monthly_credits({}, "platinum") == starter["chief_messages_monthly"]


def test_audience_credits_flow_through():
    assert fg.monthly_credits({"comp_tier": "solo"}) == 1200
    assert fg.monthly_credits({"comp_tier": "booked"}) == 2000
    assert fg.monthly_credits({"comp_tier": "boss"}) == 2500


# ─── 4. the economics floors ──────────────────────────────────────────

@pytest.mark.parametrize("plan", fg.AUDIENCE_PLANS)
def test_audience_plan_clears_the_chat_floor_and_the_trial(plan):
    cents = pricing_config.audience_price_cents()[plan]
    credits = pricing_config.audience_credits()[plan]
    # Same line test_chat_repricing holds the public ladder to.
    assert pricing_config.chat_price() * (cents / credits) >= 18.43
    assert credits > pricing_config.trial_credits()


def test_prices_are_kevins():
    assert pricing_config.audience_price_cents() == {"solo": 4900, "booked": 7900, "boss": 9900}


def test_catalog_carries_the_audience_prices():
    by_env = {e: cents for (e, _lk, _n, cents, _i) in sb.BOOTSTRAP_CATALOG}
    for plan, cents in pricing_config.audience_price_cents().items():
        assert by_env[f"STRIPE_PRICE_ID_{plan.upper()}"] == cents
        assert by_env[f"STRIPE_PRICE_ID_{plan.upper()}_ANNUAL"] == cents * 10


def test_price_ids_resolve_to_the_plan(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_BOSS", "price_boss")
    monkeypatch.setenv("STRIPE_PRICE_ID_BOSS_ANNUAL", "price_boss_y")
    p2p = fg.price_to_plan()
    assert p2p["price_boss"] == p2p["price_boss_y"] == "boss"
    assert fg.plan_of({"subscription_status": "active", "subscription_plan": "price_boss"}) == "boss"


# ─── 5. hidden until offered, audience only, comps anywhere ──────────

def test_hidden_until_offered(monkeypatch):
    assert fg.audience_plans_for("barber") == []
    monkeypatch.setenv("PLAN_SOLO_OFFERED", "1")
    assert fg.audience_plans_for("barber") == ["solo"]
    assert fg.audience_plans_for("salon") == ["solo"]
    assert fg.audience_plans_for("lawyer") == []
    assert fg.audience_plans_for("barber", offered_only=False) == list(fg.AUDIENCE_PLANS)


def test_comp_resolves_on_any_business():
    assert fg.plan_of({"comp_tier": "booked", "type": "coach"}) == "booked"


def test_plans_endpoint_keeps_the_public_list_and_adds_audience(monkeypatch):
    async def no_display(pid):
        return {}
    monkeypatch.setattr(sb, "_price_display", no_display)

    async def no_founder():
        return {"configured": False}
    monkeypatch.setattr(sb, "_founder_summary", no_founder)
    plain = asyncio.run(sb.billing_plans())
    assert [p["plan"] for p in plain["plans"]] == list(fg.PLANS)
    assert plain["audience_plans"] == []
    monkeypatch.setenv("PLAN_BOOKED_OFFERED", "1")
    barber = asyncio.run(sb.billing_plans(for_type="barber"))
    assert [p["plan"] for p in barber["plans"]] == list(fg.PLANS)
    assert [p["plan"] for p in barber["audience_plans"]] == ["booked"]
    assert "dedicated_sms_number" in barber["features_by_plan"]["booked"]
    assert barber["plan_details"]["booked"]["credits_monthly"] == 2000


# ─── 6. checkout ──────────────────────────────────────────────────────

@pytest.fixture
def checkout(monkeypatch):
    posted = []

    async def stripe_post(path, data):
        posted.append((path, data))
        return {"id": "cs_x", "url": "https://checkout.stripe.test/x"}

    state = {"type": "barber"}

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "name": "Fresh Cutz",
                "stripe_customer_id": "cus_1", "type": state["type"]}

    async def taken():
        return 0
    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_founder_seats_taken", taken)
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_DEFAULT", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_ID_SOLO", "price_solo")
    return posted, state


def _buy(**body):
    return asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id="biz-1", **body), user=USER))


def _sessions(posted):
    return [d for p, d in posted if p == "/checkout/sessions"]


def test_unpriced_audience_plan_never_falls_back_to_professional(checkout):
    posted, _ = checkout
    with pytest.raises(HTTPException) as e:
        _buy(plan="boss")          # no STRIPE_PRICE_ID_BOSS set
    assert e.value.status_code == 409
    assert _sessions(posted) == []


def test_not_offered_is_refused(checkout):
    posted, _ = checkout
    with pytest.raises(HTTPException) as e:
        _buy(plan="solo")
    assert e.value.status_code == 409
    assert _sessions(posted) == []


def test_offered_and_right_business_goes_through(checkout, monkeypatch):
    posted, _ = checkout
    monkeypatch.setenv("PLAN_SOLO_OFFERED", "1")
    _buy(plan="solo")
    assert len(_sessions(posted)) == 1


def test_wrong_kind_of_business_is_refused_even_by_raw_price(checkout, monkeypatch):
    posted, state = checkout
    monkeypatch.setenv("PLAN_SOLO_OFFERED", "1")
    state["type"] = "coach"
    with pytest.raises(HTTPException) as e:
        _buy(price_id="price_solo")
    assert e.value.status_code == 409
    assert _sessions(posted) == []
