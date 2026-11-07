"""Manage Subscription carries its own settings (stripe_billing._portal_configuration).

The live Stripe account never saved a customer-portal default, and Stripe
refuses a session with neither a default nor a configuration, so the button
that changes a card or cancels had nothing to open with.

  1. The settings are made once and every session carries them.
  2. Replicas find the same settings by their mark; a second look makes none.
  3. Cancelling runs to the end of the paid period, and plan changes stay in
     the app, where extra logins are looked after and the price shows first.
  4. Stripe not answering costs nobody the portal: the session still goes out.
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

import stripe_billing as sb  # noqa: E402


@pytest.fixture()
def stripe(monkeypatch):
    world = {"held": [], "posted": []}

    async def get(path, params):
        assert path == "/billing_portal/configurations"
        assert ("active", "true") in params
        return {"data": world["held"]}

    async def post(path, data):
        world["posted"].append((path, data))
        return {"id": "bpc_made", "metadata": data.get("metadata")}

    monkeypatch.setattr(sb, "_portal_configuration_id", None)
    monkeypatch.setattr(sb, "_stripe_get", get)
    monkeypatch.setattr(sb, "_stripe_post", post)
    return world


def _config():
    return asyncio.run(sb._portal_configuration())


def test_made_once_and_remembered(stripe):
    assert _config() == "bpc_made"
    assert _config() == "bpc_made"
    assert len(stripe["posted"]) == 1
    assert stripe["posted"][0][0] == "/billing_portal/configurations"


def test_a_replica_finds_the_settings_another_one_made(stripe):
    stripe["held"] = [{"id": "bpc_other", "metadata": {}},
                      {"id": "bpc_ours", "metadata": {"made_by": sb.PORTAL_MARK}}]
    assert _config() == "bpc_ours"
    assert stripe["posted"] == []


def test_what_the_portal_offers():
    f = sb._portal_settings()["features"]
    assert f["subscription_cancel"] == {"enabled": True, "mode": "at_period_end"}
    assert f["payment_method_update"]["enabled"] is True
    assert f["invoice_history"]["enabled"] is True
    assert f["subscription_update"]["enabled"] is False


def test_the_mark_goes_on_what_it_makes():
    assert sb._portal_settings()["metadata"] == {"made_by": sb.PORTAL_MARK}


def test_stripe_not_answering_costs_nobody_the_portal(monkeypatch):
    async def boom(path, params):
        raise HTTPException(500, "Stripe error")

    monkeypatch.setattr(sb, "_portal_configuration_id", None)
    monkeypatch.setattr(sb, "_stripe_get", boom)
    assert _config() is None
    flat = {}
    sb._flatten(flat, "configuration", None)
    assert flat == {}   # a session then goes out without it


def test_every_session_carries_the_settings(monkeypatch):
    posted = []

    async def post(path, data):
        posted.append((path, data))
        return {"url": "https://billing.stripe.test/s"}

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "stripe_customer_id": "cus_1", "settings": {}}

    monkeypatch.setattr(sb, "_portal_configuration_id", "bpc_ours")
    monkeypatch.setattr(sb, "_stripe_post", post)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb.ledger_unlock, "require_unlock", lambda *a, **k: None)
    from auth_supabase import AuthedUser
    user = AuthedUser(id="u-1", email="pastor@church.test", role="authenticated")
    out = asyncio.run(sb.create_portal(sb.PortalBody(business_id="biz-1"), request=None, user=user))
    assert out["url"].startswith("https://billing")
    assert posted[0][0] == "/billing_portal/sessions"
    assert posted[0][1]["configuration"] == "bpc_ours"
