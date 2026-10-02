"""The 2026-09-04 ladder: $79 / 3,000 · $149 / 7,500 · $299 / 17,500,
a Founder seat at $99 / 6,000, and the read-only connector on every plan.

Pins:
  * the defaults, the per-credit order (each tier's credit cheaper than
    the one below; founder cheapest), and the forty-percent worst case;
  * the founder tank is read off the Stripe price id, never a flag, and
    a comped business is never on it;
  * limit_for and usage_summary see the founder tank;
  * minting a write key below Professional is a 402 in the app's shape;
    a read key is always available.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import feature_gates as fg
import pricing_config as pc


@pytest.fixture
def prices(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith(("PRICE_", "CREDITS_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STRIPE_PRICE_ID_FOUNDER", "price_founder")
    monkeypatch.setenv("STRIPE_PRICE_ID_FOUNDER_ANNUAL", "price_founder_annual")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro")
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    return monkeypatch


def test_the_ladder_defaults(prices):
    assert pc.tier_price_cents() == {"starter": 7900, "professional": 14900,
                                     "practice": 29900, "founder": 9900}
    assert pc.tier_credits() == {"starter": 3000, "professional": 7500, "practice": 17500}
    assert pc.founder_credits() == 6000
    r = pc.tier_cents_per_credit()
    assert r["starter"] > r["professional"] > r["practice"] > r["founder"]
    assert r["founder"] == pytest.approx(1.65)
    # worst case — every credit on chat — stays under 40% on every tier
    for plan, credits in list(pc.tier_credits().items()) + [("founder", pc.founder_credits())]:
        price = pc.tier_price_cents()[plan]
        worst = credits / pc.chat_price() * pc.MEASURED_CHAT_COST_CENTS
        assert worst / price < 0.40, plan


def test_the_founder_tank_is_read_off_the_price_id(prices):
    founder = {"id": "b", "subscription_status": "active", "subscription_plan": "price_founder"}
    pro = {"id": "b", "subscription_status": "active", "subscription_plan": "price_pro"}
    assert fg.plan_of(founder) == "professional" and fg.plan_of(pro) == "professional"
    assert fg.is_founder_price(founder) and not fg.is_founder_price(pro)
    assert fg.monthly_credits(founder) == 6000
    assert fg.monthly_credits(pro) == 7500
    assert fg.limit_for(founder, "chief_messages_monthly") == 6000
    assert fg.limit_for(pro, "chief_messages_monthly") == 7500
    assert fg.limit_for(founder, "max_seats") == 1, "everything but the tank is Professional's"
    annual = {**founder, "subscription_plan": "price_founder_annual"}
    assert fg.monthly_credits(annual) == 6000


def test_a_comped_business_is_never_on_the_founder_tank(prices):
    comped = {"id": "b", "comp_tier": "professional", "subscription_plan": "price_founder"}
    assert fg.monthly_credits(comped) == 7500
    assert fg.monthly_credits({"id": "b"}) is None


def test_usage_summary_sees_the_founder_tank(prices, monkeypatch):
    import credit_ledger
    import usage_metering as um
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: False)
    monkeypatch.setattr(um, "weighted_usage_this_month", lambda b: 100)
    monkeypatch.setattr(um, "grant_units_this_month", lambda b: 0)
    monkeypatch.setattr(credit_ledger, "sync_burn", lambda b, n: 0)
    monkeypatch.setattr(credit_ledger, "balance", lambda b: 0)
    row = {"id": "b", "owner_id": "o", "subscription_status": "active",
           "subscription_plan": "price_founder", "settings": {}}
    s = um.usage_summary("b", row)
    assert s["allotment"] == 6000 and s["remaining"] == 5900


def test_minting_a_write_key_below_professional_is_a_402(prices, monkeypatch):
    import mcp_server as mcp
    import mcp_tokens

    async def owned(client, user, business_id):
        return {"id": "biz-1", "comp_tier": "starter"}
    monkeypatch.setattr(mcp, "_owned_business", owned)
    monkeypatch.setattr(mcp, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(mcp_tokens, "mint", lambda biz, **k: ("tok", {"jti": "j", "label": k.get("label"),
                                                                      "scopes": k.get("scopes"), "expires_at": "x"}))
    user = type("U", (), {"id": "u", "email": "o@x.com"})()
    body = mcp._MintBody(business_id="biz-1", label="k", scopes=["read", "write"], ttl_days=30)
    with pytest.raises(HTTPException) as ex:
        asyncio.run(mcp.mint_token(body, user))
    assert ex.value.status_code == 402
    assert ex.value.detail["feature"] == "agent_connector_write"
    assert ex.value.detail["required_plan"] == "professional"
    body = mcp._MintBody(business_id="biz-1", label="k", scopes=["read"], ttl_days=30)
    out = asyncio.run(mcp.mint_token(body, user))
    assert out["scopes"] == ["read"], "a read key is always available"
