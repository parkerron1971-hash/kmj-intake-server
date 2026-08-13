"""Site-builder audit (2026-08-13) — stripe_proxy authorization + tenant
scoping regressions.

Two defects are pinned here, because both were silent:

  1. Both Payment Link endpoints took business_id from the request body
     behind require_user alone. Signed in was treated as authorized, so
     any user could mint links on another merchant's connected account
     or rotate a competitor's live Buy button.

  2. The webhook's amount fallbacks carried no business filter. Price
     was used as identity, so a $14.99 payment could deliver whichever
     $14.99 auto-deliver product was created most recently platform-wide.

Both failures returned 200 and looked like success, which is exactly why
they need a test that fails loudly when the guard is removed.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_CONNECT_CLIENT_ID", "ca_dummy")

import stripe_proxy  # noqa: E402


class _User:
    """Stand-in for AuthedUser — only .id is read by the gate."""

    def __init__(self, uid: str):
        self.id = uid


OWNER = "11111111-1111-1111-1111-111111111111"
STRANGER = "22222222-2222-2222-2222-222222222222"
BIZ = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class _FakeSbClients:
    """Minimal sb_clients stand-in. Returns one business row owned by
    OWNER, or [] to simulate a business that does not exist."""

    def __init__(self, rows):
        self._rows = rows
        self.queries: list = []

    def sb_get_as_service(self, path: str):
        self.queries.append(path)
        return self._rows


@pytest.fixture
def fake_sb(monkeypatch):
    def _install(rows):
        fake = _FakeSbClients(rows)
        monkeypatch.setitem(sys.modules, "sb_clients", fake)
        return fake

    return _install


# ─── _require_owner ──────────────────────────────────────────────────


def test_owner_passes_and_row_carries_connected_account(fake_sb):
    fake_sb([{"id": BIZ, "owner_id": OWNER, "stripe_account_id": "acct_live"}])
    row = stripe_proxy._require_owner(BIZ, _User(OWNER))
    assert row["stripe_account_id"] == "acct_live"


def test_non_owner_is_rejected_with_403(fake_sb):
    """The whole point: authenticated is not authorized."""
    fake_sb([{"id": BIZ, "owner_id": OWNER, "stripe_account_id": "acct_live"}])
    with pytest.raises(HTTPException) as err:
        stripe_proxy._require_owner(BIZ, _User(STRANGER))
    assert err.value.status_code == 403


def test_missing_business_is_404_not_a_silent_pass(fake_sb):
    fake_sb([])
    with pytest.raises(HTTPException) as err:
        stripe_proxy._require_owner(BIZ, _User(OWNER))
    assert err.value.status_code == 404


def test_owner_gate_scopes_its_lookup_to_the_named_business(fake_sb):
    fake = fake_sb([{"id": BIZ, "owner_id": OWNER, "stripe_account_id": ""}])
    stripe_proxy._require_owner(BIZ, _User(OWNER))
    assert f"id=eq.{BIZ}" in fake.queries[0]


# ─── webhook amount fallbacks — tenant scoping ───────────────────────


class _NoRowsClient:
    """Records every PostgREST path the matcher asks for, returns none."""

    def __init__(self):
        self.paths: list = []


async def _fake_sb_get(client, path):
    client.paths.append(path)
    return []


def test_digital_amount_fallback_refuses_to_guess_without_a_business(monkeypatch):
    """No business_id ⇒ no query at all. Delivering the wrong tenant's
    paid file is worse than delivering nothing."""
    monkeypatch.setattr(stripe_proxy, "_sb_get", _fake_sb_get)
    client = _NoRowsClient()
    got = asyncio.run(
        stripe_proxy._match_digital_product_for_payment(client, "", 14.99, None)
    )
    assert got is None
    assert client.paths == []


def test_digital_amount_fallback_is_scoped_when_business_is_known(monkeypatch):
    monkeypatch.setattr(stripe_proxy, "_sb_get", _fake_sb_get)
    client = _NoRowsClient()
    asyncio.run(
        stripe_proxy._match_digital_product_for_payment(client, "", 14.99, BIZ)
    )
    assert len(client.paths) == 1
    assert f"business_id=eq.{BIZ}" in client.paths[0]


def test_invoice_amount_fallback_refuses_to_guess_without_a_business(monkeypatch):
    monkeypatch.setattr(stripe_proxy, "_sb_get", _fake_sb_get)
    client = _NoRowsClient()
    got = asyncio.run(
        stripe_proxy._match_invoice_for_payment(client, "", 500.0, None)
    )
    assert got is None
    assert client.paths == []


def test_invoice_amount_fallback_is_scoped_when_business_is_known(monkeypatch):
    monkeypatch.setattr(stripe_proxy, "_sb_get", _fake_sb_get)
    client = _NoRowsClient()
    asyncio.run(stripe_proxy._match_invoice_for_payment(client, "", 500.0, BIZ))
    assert len(client.paths) == 1
    assert f"business_id=eq.{BIZ}" in client.paths[0]


def test_exact_link_match_still_works_without_a_business(monkeypatch):
    """Scoping the fallback must not break the precise path — an exact
    payment-link match is already unambiguous."""

    async def _hit(client, path):
        client.paths.append(path)
        return [{"id": "prod_1", "name": "Ebook"}]

    monkeypatch.setattr(stripe_proxy, "_sb_get", _hit)
    client = _NoRowsClient()
    got = asyncio.run(
        stripe_proxy._match_digital_product_for_payment(
            client, "plink_abc", 14.99, None
        )
    )
    assert got is not None and got["id"] == "prod_1"
    assert "plink_abc" in client.paths[0]
