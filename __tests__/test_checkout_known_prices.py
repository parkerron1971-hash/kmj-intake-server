"""Checkout takes only our own plan prices; the catalog button never hands
back a stale one.

1. /billing/checkout used a client-sent `price_id` verbatim. Any recurring
   price in the platform's Stripe account could be bought, and a
   subscription on a price the catalog doesn't know resolves to no plan,
   which `feature_gates.limit_for` answers with Starter's limits. The app
   only sends `plan`, so an explicit price must now be a catalog price.

2. /billing/bootstrap-prices reuses prices by lookup key. A key created
   before the 2026-09-04 ladder can still name a $199 / $399 price; its
   env line would put new checkouts back on the old price if pasted. A
   reused price whose amount or interval differs from the catalog is left
   out of the env block and reported as `mismatched`.
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
from auth_supabase import AuthedUser  # noqa: E402

USER = AuthedUser(id="u-1", email="a@b.test", role="authenticated")


@pytest.fixture()
def stripe_calls(monkeypatch):
    posted = []

    async def stripe_post(path, data):
        posted.append((path, data))
        return {"id": "cs_test_x", "url": "https://checkout.stripe.test/x"}

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "name": "Biz", "stripe_customer_id": "cus_1"}

    async def taken():
        return 0

    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_founder_seats_taken", taken)
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter_live")
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro_live")
    return posted


def _checkout(**body):
    return asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id="biz-1", **body), user=USER))


def _session_prices(posted):
    sessions = [d for p, d in posted if p == "/checkout/sessions"]
    assert len(sessions) == 1
    return [v for k, v in sessions[0].items() if k.startswith("line_items") and k.endswith("[price]")] \
        or [sessions[0].get("line_items", [{}])[0].get("price")]


def test_unknown_explicit_price_is_refused_before_stripe(stripe_calls):
    with pytest.raises(HTTPException) as e:
        _checkout(price_id="price_some_other_product")
    assert e.value.status_code == 400
    assert stripe_calls == []


def test_catalog_price_sent_explicitly_still_works(stripe_calls):
    _checkout(price_id="price_starter_live")
    assert _session_prices(stripe_calls) == ["price_starter_live"]


def test_plan_path_is_unchanged(stripe_calls):
    _checkout(plan="professional")
    assert _session_prices(stripe_calls) == ["price_pro_live"]


# ─── bootstrap-prices ───────────────────────────────────────────────

def _run_bootstrap(monkeypatch, existing_prices):
    created_prices = []

    async def stripe_get(path, params):
        if path == "/prices":
            return {"data": existing_prices}
        if path == "/products":
            return {"data": [{"id": "prod_1", "name": "Solutionist Starter"}]}
        return {"data": [{"id": "promo_1"}]}  # MINISTRY20 already exists

    async def stripe_post(path, data):
        if path == "/prices":
            created_prices.append(data)
            return {"id": f"price_new_{data['lookup_key']}"}
        return {"id": "prod_new"}

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(sb, "_stripe_get", stripe_get)
    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    out = asyncio.run(sb.bootstrap_prices(_owner=None))
    return out, created_prices


def _price(lookup_key, cents, interval="month", pid=None):
    return {"id": pid or f"price_{lookup_key}", "lookup_key": lookup_key,
            "unit_amount": cents, "recurring": {"interval": interval}, "product": "prod_1"}


def test_stale_price_under_a_catalog_key_stays_out_of_the_env_block(monkeypatch):
    old_pro = _price("solutionist_professional_monthly", 19900, pid="price_old_199")
    out, created = _run_bootstrap(monkeypatch, [old_pro])

    assert "STRIPE_PRICE_ID_PROFESSIONAL" not in out["env"]
    assert "price_old_199" not in out["railway_block"]
    # DEFAULT copies PROFESSIONAL; it must not resurrect the old price either.
    assert out["env"].get("STRIPE_PRICE_ID_DEFAULT", "") in ("",)
    assert out["mismatched"] == [{"lookup_key": "solutionist_professional_monthly",
                                  "found_cents": 19900, "catalog_cents": 14900}]
    # Nothing is created over the stale key (a duplicate lookup key would fail anyway).
    assert all(p["lookup_key"] != "solutionist_professional_monthly" for p in created)


def test_matching_price_is_reused(monkeypatch):
    starter = _price("solutionist_starter_monthly", 7900, pid="price_starter_ok")
    out, created = _run_bootstrap(monkeypatch, [starter])

    assert out["env"]["STRIPE_PRICE_ID_STARTER"] == "price_starter_ok"
    assert "solutionist_starter_monthly" in out["reused"]
    assert out["mismatched"] == []
    assert all(p["lookup_key"] != "solutionist_starter_monthly" for p in created)


def test_interval_mismatch_counts_as_stale(monkeypatch):
    wrong = _price("solutionist_starter_annual", 79000, interval="month")
    out, _ = _run_bootstrap(monkeypatch, [wrong])
    assert "STRIPE_PRICE_ID_STARTER_ANNUAL" not in out["env"]
    assert out["mismatched"][0]["lookup_key"] == "solutionist_starter_annual"


def test_catalog_matches_the_live_ladder():
    import pricing_config
    by_env = {e: cents for (e, _lk, _n, cents, _i) in sb.BOOTSTRAP_CATALOG}
    tiers = pricing_config.tier_price_cents()
    assert by_env["STRIPE_PRICE_ID_STARTER"] == tiers["starter"]
    assert by_env["STRIPE_PRICE_ID_PROFESSIONAL"] == tiers["professional"]
    assert by_env["STRIPE_PRICE_ID_PRACTICE"] == tiers["practice"]
    assert by_env["STRIPE_PRICE_ID_FOUNDER"] == tiers["founder"]
    for env_key, cents in by_env.items():
        if env_key.endswith("_ANNUAL"):
            assert cents == by_env[env_key[: -len("_ANNUAL")]] * 10, env_key
