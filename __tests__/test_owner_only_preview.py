"""A no-card trial's site preview is its own team's (2026-10-03).

The public address already says "coming soon" until a card. The editor's
preview addresses — /public/site/{slug} on the API host, /sites/{id}/preview
— needed no sign-in, so the same site could be shared from there. Now they
show a no-card site only with a short-lived token the app mints for the
signed-in team (GET /billing/trial/preview-token, added as ?pv=).
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import no_card_trial as nct  # noqa: E402


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    nct._hidden_cache.clear()


def test_a_token_opens_its_own_business_only():
    t = nct.preview_token("biz1", now=1_000)
    assert nct.preview_ok("biz1", t, now=1_001)
    assert not nct.preview_ok("biz2", t, now=1_001)


def test_a_token_expires():
    t = nct.preview_token("biz1", now=1_000)
    assert not nct.preview_ok("biz1", t, now=1_000 + nct.PREVIEW_TTL_SECONDS + 1)


def test_a_tampered_or_missing_token_fails():
    t = nct.preview_token("biz1", now=1_000)
    exp, sig = t.split(".")
    assert not nct.preview_ok("biz1", f"{int(exp) + 9999}.{sig}", now=1_001)
    for bad in (None, "", "garbage", "123", "abc.def"):
        assert not nct.preview_ok("biz1", bad, now=1_001)


def _hidden(monkeypatch, hidden: bool):
    async def _site_hidden(client, business_id):
        return hidden
    monkeypatch.setattr(nct, "site_hidden", _site_hidden)


def test_blocked_only_for_a_no_card_site_without_a_token(monkeypatch):
    _hidden(monkeypatch, True)
    good = nct.preview_token("biz1")
    assert asyncio.run(nct.preview_blocked(object(), "biz1", None)) is True
    assert asyncio.run(nct.preview_blocked(object(), "biz1", good)) is False
    _hidden(monkeypatch, False)
    assert asyncio.run(nct.preview_blocked(object(), "biz1", None)) is False


def test_every_preview_route_is_gated_and_takes_the_token():
    import public_site
    for fn in (public_site.get_site_html, public_site.get_site_page_html,
               public_site.get_site_news_index, public_site.get_site_news_post,
               public_site.preview_site_endpoint, public_site.preview_page_endpoint):
        src = inspect.getsource(fn)
        assert "pv: Optional[str] = None" in src, fn.__name__
        assert "preview_blocked(" in src, fn.__name__
    # A secondary page that falls back to home keeps the token.
    assert "get_site_html(slug, pv)" in inspect.getsource(public_site.get_site_page_html)


def test_the_preview_shows_coming_soon_without_the_token(monkeypatch):
    import public_site
    _hidden(monkeypatch, True)
    monkeypatch.setattr(public_site, "_check_rate", lambda slug: True)

    async def _sb(client, path):
        if path.startswith("/business_sites?"):
            return [{"business_id": "biz1", "html_content": "<html>SITE</html>",
                     "status": "published", "site_config": {}}]
        return []
    monkeypatch.setattr(public_site, "_sb", _sb)
    resp = asyncio.run(public_site.get_site_html("ana"))
    body = resp.body.decode("utf-8")
    assert "Coming soon" in body and "SITE" not in body


def test_the_token_endpoint_is_for_the_team():
    import stripe_billing
    src = inspect.getsource(stripe_billing.trial_preview_token)
    assert 'require_role(business_id, str(user.id), "member")' in src
