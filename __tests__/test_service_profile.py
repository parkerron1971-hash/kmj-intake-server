"""Execute the billing route: the edition foundation must not change access.

Supabase is mocked at HTTP, so the real business loader and ownership check run.
Any write or unexpected provider call fails the test.
"""
from __future__ import annotations

import copy
import pathlib
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from auth_supabase import AuthedUser, require_user
import feature_gates as fg
import pricing_config
import stripe_billing as billing
import usage_metering


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_FOUNDER", "price_founder")
    monkeypatch.setenv("STRIPE_PRICE_ID_FOUNDER_ANNUAL", "price_founder_annual")
    monkeypatch.setattr(fg, "price_to_plan", lambda: {
        "price_starter": "starter", "price_pro": "professional",
        "price_team": "practice", "price_pro_annual": "professional",
        "price_founder": "professional", "price_founder_annual": "professional",
    })
    monkeypatch.setattr(billing, "SUPABASE_URL", "https://db.test")
    monkeypatch.setattr(billing, "_service_headers", lambda: {"apikey": "test-service"})
    state = {
        "business": {
            "id": "business-1", "owner_id": "owner-1",
            "subscription_status": "active", "subscription_plan": "price_starter",
            "comp_tier": None, "settings": {},
        },
        "grandfathered": False,
        "http_calls": [],
    }
    monkeypatch.setattr(usage_metering, "is_grandfathered_business",
                        lambda *args: state["grandfathered"])

    def database(request):
        assert request.method == "GET", "service profile must not write"
        assert request.url.host == "db.test", "no provider or Stripe request"
        assert request.url.path == "/rest/v1/businesses"
        assert request.url.params["id"] == "eq.business-1"
        assert request.headers["apikey"] == "test-service"
        state["http_calls"].append(request)
        rows = [] if state["business"] is None else [state["business"]]
        return httpx.Response(200, json=rows)

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(database), **kwargs))
    app = FastAPI()
    app.include_router(billing.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(
        id="owner-1", email="owner@example.test", role="authenticated")
    with TestClient(app) as client:
        yield client, app, state


@pytest.mark.parametrize("price,tier,writes", [
    ("price_starter", "starter", False),
    ("price_pro", "professional", True),
    ("price_pro_annual", "professional", True),
    ("price_team", "practice", True),
    ("price_founder", "professional", True),
    ("price_founder_annual", "professional", True),
])
def test_existing_offers_keep_every_entitlement_and_credit_grant(endpoint, price, tier, writes):
    client, _, state = endpoint
    business = state["business"]
    business["subscription_plan"] = price
    before = copy.deepcopy(business)
    expected = fg.entitlements(business)
    expected.update(ok=True, trial_ends_at=None, current_period_end=None,
                    cancel_at_period_end=None, grandfathered=False, comp_tier=None)
    response = client.get("/billing/entitlements?biz=business-1")
    assert response.status_code == 200
    body = response.json()
    profile = body.pop("service_profile")
    assert body == expected  # All previous response fields retain their meaning.
    assert state["business"] == before
    assert len(state["http_calls"]) == 1
    assert profile["business_plan"]["tier"] == tier
    assert profile["external_agent"]["write_included_in_plan"] is writes
    assert profile["external_agent"]["read_included_in_plan"] is True
    grant = (pricing_config.founder_credits() if "founder" in price
             else pricing_config.tier_credits()[tier])
    assert profile["ai_service"]["monthly_plan_credits"] == grant


def test_comp_overrides_founder_without_changing_the_existing_offer(endpoint):
    client, _, state = endpoint
    state["business"].update(subscription_plan="price_founder", comp_tier="practice")
    body = client.get("/billing/entitlements?biz=business-1").json()
    profile = body["service_profile"]
    assert body["comp_tier"] == "practice"
    assert profile["business_plan"]["tier"] == "practice"
    assert profile["ai_service"]["monthly_plan_credits"] == pricing_config.practice_credits()


@pytest.mark.parametrize("status", ["trialing", "past_due", "canceled", None])
def test_subscription_states_keep_the_existing_gate_decisions(endpoint, status):
    client, _, state = endpoint
    state["business"]["subscription_status"] = status
    expected = fg.entitlements(state["business"])
    body = client.get("/billing/entitlements?biz=business-1").json()
    assert body["features"] == expected["features"]
    assert body["plan"] == expected["plan"]
    if status != "trialing":
        assert body["service_profile"]["ai_service"]["monthly_plan_credits"] is None


@pytest.mark.parametrize("bypass", ["grandfathered", "enforcement_off"])
def test_bypasses_do_not_turn_plan_inclusion_into_runtime_permission(endpoint, monkeypatch, bypass):
    client, _, state = endpoint
    if bypass == "grandfathered":
        state["grandfathered"] = True
    else:
        monkeypatch.setenv("BILLING_ENFORCE", "off")
    body = client.get("/billing/entitlements?biz=business-1").json()
    assert body["grandfathered"] is (bypass == "grandfathered")
    assert body["service_profile"]["external_agent"]["write_included_in_plan"] is False
    assert body["features"] == fg.entitlements(state["business"])["features"]


def test_editable_settings_and_unknown_prices_cannot_activate_connect(endpoint):
    client, _, state = endpoint
    state["business"].update(subscription_plan="unknown_price", settings={
        "edition": "connect", "ai_delivery": "customer_provided",
        "in_app_delegation_supported": True,
    })
    profile = client.get("/billing/entitlements?biz=business-1").json()["service_profile"]
    assert profile["edition"] == "legacy"
    assert profile["business_plan"]["tier"] is None
    assert profile["ai_service"]["delivery"] == "solutionist_provided"
    assert profile["external_agent"]["read_included_in_plan"] is False
    assert profile["external_agent"]["write_included_in_plan"] is False
    assert profile["external_agent"]["in_app_delegation_supported"] is False


def test_nonowner_cannot_read_another_business_profile(endpoint):
    client, _, state = endpoint
    state["business"]["owner_id"] = "another-owner"
    response = client.get("/billing/entitlements?biz=business-1")
    assert response.status_code == 403
    assert "service_profile" not in response.json()


def test_missing_auth_is_rejected_before_loading_the_business(endpoint):
    client, app, state = endpoint
    app.dependency_overrides.clear()
    response = client.get("/billing/entitlements?biz=business-1")
    assert response.status_code == 401
    assert state["http_calls"] == []


def test_missing_business_returns_404(endpoint):
    client, _, state = endpoint
    state["business"] = None
    assert client.get("/billing/entitlements?biz=business-1").status_code == 404
