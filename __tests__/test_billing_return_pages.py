"""The three URLs Stripe sends a customer's browser back to.

Checkout's success_url / cancel_url and the Customer Portal's return_url
default to mysolutionist.app/billing/{success,cancel,done}. Nothing
served those paths: they fell through public_site's `/{path:path}`
catch-all and answered `{"detail":"Not found"}` with a 404. Because
checkout opens in a NEW TAB (AccessGate.checkout → window.open), that
404 was the last thing a practitioner saw after paying — the
subscription was live, but it did not look like it.

These tests hold the ending in place: the pages exist, they render HTML
(not JSON), they point back at the app, and the catch-all cannot shadow
them again.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import stripe_billing as sb  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(sb.router)
    return TestClient(app)


RETURN_PATHS = ["/billing/success", "/billing/cancel", "/billing/done"]


@pytest.mark.parametrize("path", RETURN_PATHS)
def test_return_page_is_html_not_a_404(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text[:300]
    assert "text/html" in r.headers.get("content-type", "")
    assert "Not found" not in r.text
    assert "<h1" in r.text


@pytest.mark.parametrize("path", RETURN_PATHS)
def test_every_return_page_leads_back_to_the_app(client, path):
    """A dead end is what the 404 was. Each page hands the tab a way
    back into the workspace."""
    assert sb.APP_HOME in client.get(path).text


def test_success_page_survives_a_session_it_cannot_read(client):
    """Stripe unconfigured, network down, session expired — the peek
    fails soft and the person who just paid still gets a page."""
    r = client.get("/billing/success?session_id=cs_test_unreadable")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_credit_pack_success_says_credits_not_subscription(client):
    """/billing/credits/checkout appends credits=1 to the same
    success_url — the copy has to follow what was actually bought."""
    r = client.get("/billing/success?credits=1&session_id=cs_test_pack")
    assert "credits" in r.text.lower()
    assert "subscription is active" not in r.text.lower()


def test_session_id_from_the_query_string_cannot_walk_the_api_path():
    """The value is interpolated into a Stripe API path, so it is
    validated as a session id and nothing else."""
    assert sb._valid_session_id("cs_test_a1B2c3")
    assert not sb._valid_session_id("cs_test/../../account")
    assert not sb._valid_session_id("../../v1/accounts")
    assert not sb._valid_session_id("sub_123")
    assert not sb._valid_session_id("")
    assert not sb._valid_session_id("cs_" + "a" * 200)


def test_peek_is_skipped_entirely_without_a_key(monkeypatch):
    """asyncio.run rather than @pytest.mark.asyncio: pytest-asyncio is
    not a dependency of this repo, and CI has no plugin to honour the
    marker — it collects the coroutine and fails. Every other async test
    here drives the loop directly."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert asyncio.run(sb._peek_checkout_session("cs_test_abc")) is None
    assert asyncio.run(sb._peek_checkout_session(None)) is None


def test_the_catch_all_does_not_shadow_the_return_pages():
    """public_site_router owns `/{path:path}` and MUST stay registered
    last; the billing router is registered long before it. Assert the
    real app, on the real marketing host, still resolves these."""
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    import kmj_intake_automation  # noqa: E402

    c = TestClient(kmj_intake_automation.app)
    for path in RETURN_PATHS:
        r = c.get(path, headers={"host": "mysolutionist.app"})
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:200]}"
        assert "text/html" in r.headers.get("content-type", "")
