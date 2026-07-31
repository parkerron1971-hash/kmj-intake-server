# __tests__/test_payments_core.py
#
# The payment adapter seam. Pins:
#   * provider selection (default stripe, per-business override, loud
#     fallback on unknown)
#   * unimplemented verbs answer 409, never silently fall back to Stripe
#   * the live call sites route through the seam (source sweep)

import pathlib
from unittest import mock

import pytest
from fastapi import HTTPException

import payments_core


def test_default_provider_is_stripe():
    assert payments_core.provider_for({"settings": {}}).id == "stripe"
    assert payments_core.provider_for({}).id == "stripe"


def test_per_business_provider_override():
    biz = {"settings": {"payments": {"provider": "square"}}}
    assert payments_core.provider_for(biz).id == "square"


def test_unknown_provider_falls_back_loudly():
    biz = {"id": "biz-1", "settings": {"payments": {"provider": "dogecoin"}}}
    with mock.patch.object(payments_core.logger, "error") as err:
        adapter = payments_core.provider_for(biz)
    assert adapter.id == "stripe"
    err.assert_called_once()


def test_stripe_connectivity_reads_account_id():
    stripe = payments_core.REGISTRY["stripe"]
    assert stripe.is_connected({"stripe_account_id": "acct_123"}) is True
    assert stripe.is_connected({"stripe_account_id": None}) is False
    assert stripe.is_connected({}) is False


@pytest.mark.asyncio
async def test_unimplemented_verbs_409_instead_of_stripe_fallback():
    square = payments_core.REGISTRY["square"]
    with pytest.raises(HTTPException) as exc:
        await square.create_booking_checkout({}, booking_id="b1")
    assert exc.value.status_code == 409
    assert "Square" in str(exc.value.detail)
    with pytest.raises(HTTPException) as exc2:
        await square.create_refund({}, charge_id="ch_1")
    assert exc2.value.status_code == 409


def test_providers_status_shape():
    rows = payments_core.providers_status({"stripe_account_id": "acct_1"})
    by_id = {r["id"]: r for r in rows}
    assert by_id["stripe"]["connected"] is True
    assert by_id["stripe"]["connectable"] is True
    assert by_id["square"]["connected"] is False
    assert by_id["square"]["connectable"] is False


def test_live_call_sites_route_through_the_seam():
    import stripe_payments_router
    src = pathlib.Path(stripe_payments_router.__file__).read_text(encoding="utf-8")
    # The router imports the seam, not the stripe helper module.
    assert "import payments_core" in src
    assert "from stripe_checkout_helpers import" not in src
    assert "provider.create_booking_checkout(" in src
    assert "payments_core.provider_for(biz).create_refund(" in src
