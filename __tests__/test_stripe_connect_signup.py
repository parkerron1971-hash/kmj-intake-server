"""Signing up for Stripe inside Solutionist (2026-10-14): the business
gets its own full Stripe account and Stripe's onboarding form runs in
the app. Kevin: "can sign up for the first time through the system?"
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import stripe_connect_helpers as helpers
import stripe_connect_router as router

BIZ = "biz-sign-0001"
OWNER = SimpleNamespace(id="u1", email="pastor@lovecity.example")


class FakeSB:
    def __init__(self, business):
        self.business = business
        self.patches = []

    def sb_get_as_service(self, path):
        if path.startswith("/businesses?"):
            return [self.business] if self.business else []
        if path.startswith("/business_sites?"):
            return [{"slug": "love-city"}]
        return []

    def sb_patch_as_service(self, path, payload):
        self.patches.append((path, payload))
        return [payload]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_live_xyz")
    import financial_policy
    monkeypatch.setattr(financial_policy, "require_operational_write", lambda biz_id: None)

    def setup(**biz):
        fake = FakeSB({"id": BIZ, "name": "Love City Church", "owner_id": "u1",
                       "stripe_account_id": None, **biz})
        monkeypatch.setattr(router, "sb_clients", fake)
        return fake
    return setup


def _create(user=OWNER):
    return asyncio.run(router.stripe_connect_create_account({"business_id": BIZ}, user))


def _session(user=OWNER):
    return asyncio.run(router.stripe_connect_account_session({"business_id": BIZ}, user))


# ─── the account form ─────────────────────────────────────────────────

def test_account_is_a_full_stripe_account_that_owns_its_own_risk():
    form = helpers._full_dashboard_account_form(
        business_id=BIZ, business_name="Love City Church",
        email="pastor@lovecity.example", url="https://love-city.mysolutionist.app")
    # Standard-equivalent: full Dashboard, the account pays Stripe's fees,
    # Stripe carries losses (and so collects requirements). The platform
    # never becomes the liable party.
    assert form["controller[stripe_dashboard][type]"] == "full"
    assert form["controller[fees][payer]"] == "account"
    assert form["controller[losses][payments]"] == "stripe"
    assert form["metadata[business_id]"] == BIZ
    assert form["email"] == "pastor@lovecity.example"
    assert form["business_profile[url]"] == "https://love-city.mysolutionist.app"
    # The owner picks the country in Stripe's form; Stripe requests its capabilities.
    assert "country" not in form and not any(k.startswith("capabilities") for k in form)


def test_signup_calls_pin_a_version_that_knows_controllers():
    assert helpers.SIGNUP_STRIPE_VERSION.startswith("2025-")


# ─── create-account ───────────────────────────────────────────────────

def test_create_account_saves_it_only_into_an_empty_column(env, monkeypatch):
    fake = env()
    got = {}

    async def fake_create(**kw):
        got.update(kw)
        return {"id": "acct_new1"}

    monkeypatch.setattr(router, "create_full_dashboard_account", fake_create)
    out = _create()
    assert out == {"ok": True, "stripe_account_id": "acct_new1"}
    assert got == {"business_id": BIZ, "business_name": "Love City Church",
                   "email": "pastor@lovecity.example",
                   "url": "https://love-city.mysolutionist.app"}
    path, payload = fake.patches[0]
    # A concurrent OAuth connection is never overwritten.
    assert path == f"/businesses?id=eq.{BIZ}&stripe_account_id=is.null"
    assert payload == {"stripe_account_id": "acct_new1"}


def test_create_account_is_owner_only(env, monkeypatch):
    env()
    monkeypatch.setattr(router, "create_full_dashboard_account",
                        lambda **kw: pytest.fail("created for a non-owner"))
    with pytest.raises(HTTPException) as exc:
        _create(SimpleNamespace(id="someone-else", email="x@example.com"))
    assert exc.value.status_code == 403


def test_create_account_refuses_when_connected_or_switched_off(env, monkeypatch):
    monkeypatch.setattr(router, "create_full_dashboard_account",
                        lambda **kw: pytest.fail("should not reach Stripe"))
    env(stripe_account_id="acct_old")
    with pytest.raises(HTTPException) as exc:
        _create()
    assert exc.value.status_code == 409
    env()
    monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY")
    with pytest.raises(HTTPException) as exc:
        _create()
    assert exc.value.status_code == 503


def test_create_account_failure_saves_nothing(env, monkeypatch):
    fake = env()

    async def boom(**kw):
        raise RuntimeError("stripe 400")

    monkeypatch.setattr(router, "create_full_dashboard_account", boom)
    with pytest.raises(HTTPException) as exc:
        _create()
    assert exc.value.status_code == 502 and fake.patches == []


# ─── account-session ──────────────────────────────────────────────────

def test_session_returns_the_secret_and_the_key(env, monkeypatch):
    env(stripe_account_id="acct_new1")
    seen = []

    async def fake_session(acct):
        seen.append(acct)
        return {"client_secret": "accs_secret_1"}

    monkeypatch.setattr(router, "create_onboarding_session", fake_session)
    assert _session() == {"ok": True, "client_secret": "accs_secret_1",
                          "publishable_key": "pk_live_xyz"}
    assert seen == ["acct_new1"]


def test_session_needs_an_account_an_owner_and_the_key(env, monkeypatch):
    monkeypatch.setattr(router, "create_onboarding_session",
                        lambda acct: pytest.fail("should not reach Stripe"))
    env()
    with pytest.raises(HTTPException) as exc:
        _session()
    assert exc.value.status_code == 409
    env(stripe_account_id="acct_new1")
    with pytest.raises(HTTPException) as exc:
        _session(SimpleNamespace(id="someone-else", email="x@example.com"))
    assert exc.value.status_code == 403
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_wrongmode")
    with pytest.raises(HTTPException) as exc:
        _session()
    assert exc.value.status_code == 503


def test_session_stripe_refusal_is_a_plain_502(env, monkeypatch):
    env(stripe_account_id="acct_oauth_old")

    async def refuse(acct):
        raise RuntimeError("stripe 400: not allowed for this account")

    monkeypatch.setattr(router, "create_onboarding_session", refuse)
    with pytest.raises(HTTPException) as exc:
        _session()
    assert exc.value.status_code == 502 and "Stripe Dashboard" in exc.value.detail


# ─── status tells the app whether to offer it ─────────────────────────

def test_status_says_whether_signup_can_open_here(env, monkeypatch):
    env()
    out = asyncio.run(router.stripe_connect_status(BIZ, OWNER))
    assert out["connected"] is False and out["embedded_signup"] is True
    monkeypatch.delenv("STRIPE_PUBLISHABLE_KEY")
    out = asyncio.run(router.stripe_connect_status(BIZ, OWNER))
    assert out["embedded_signup"] is False

    env(stripe_account_id="acct_new1")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_live_xyz")

    async def fake_fetch(acct):
        return {"charges_enabled": False, "requirements": {"currently_due": ["external_account"]}}

    monkeypatch.setattr(router, "fetch_account", fake_fetch)
    out = asyncio.run(router.stripe_connect_status(BIZ, OWNER))
    assert out["connected"] is True and out["embedded_signup"] is True
    assert out["requirements_due"] == ["external_account"]


class _FakeAsyncClient:
    calls = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, auth=None, headers=None):
        import httpx
        _FakeAsyncClient.calls.append((url, dict(data), dict(headers or {})))
        body = {"id": "acct_x"} if url.endswith("/accounts") else {"client_secret": "accs_1"}
        return httpx.Response(200, json=body)


def test_create_is_idempotent_per_business_and_session_targets_the_account(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    monkeypatch.setattr(helpers.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.calls = []
    kw = dict(business_id=BIZ, business_name="Love City Church", email="p@x.example", url="")
    asyncio.run(helpers.create_full_dashboard_account(**kw))
    asyncio.run(helpers.create_full_dashboard_account(**kw))
    (u1, d1, h1), (u2, d2, h2) = _FakeAsyncClient.calls
    assert u1.endswith("/v1/accounts") and d1 == d2
    # A double press sends the same key, so Stripe returns one account.
    assert h1["Idempotency-Key"] == h2["Idempotency-Key"]
    assert h1["Idempotency-Key"].startswith(f"solutionist-signup-{BIZ}-")
    assert h1["Stripe-Version"] == helpers.SIGNUP_STRIPE_VERSION
    assert "Stripe-Account" not in h1     # created by the platform, not on an account

    asyncio.run(helpers.create_onboarding_session("acct_x"))
    url, data, headers = _FakeAsyncClient.calls[-1]
    assert url.endswith("/v1/account_sessions")
    assert data == {"account": "acct_x", "components[account_onboarding][enabled]": "true"}
    assert headers["Stripe-Version"] == helpers.SIGNUP_STRIPE_VERSION
