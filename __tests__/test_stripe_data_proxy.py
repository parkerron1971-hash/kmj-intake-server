"""Phase D.4 PR 2 — stripe_data_proxy unit tests.

Focused on the helpers — pagination shape, limit clamp. The httpx
calls themselves are exercised in integration; here we cover the
logic that lives in our process.
"""
from __future__ import annotations

import os
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_CONNECT_CLIENT_ID", "ca_dummy")

from stripe_data_proxy import (  # noqa: E402
    _built_in_pagination,
    _clamp_limit,
    DEFAULT_LIMIT,
    MAX_LIMIT,
)


# ─── _clamp_limit ────────────────────────────────────────────────────


def test_clamp_default_on_none():
    assert _clamp_limit(None) == DEFAULT_LIMIT


def test_clamp_default_on_zero():
    assert _clamp_limit(0) == DEFAULT_LIMIT


def test_clamp_default_on_negative():
    assert _clamp_limit(-5) == DEFAULT_LIMIT


def test_clamp_passthrough_within_range():
    assert _clamp_limit(10) == 10
    assert _clamp_limit(50) == 50


def test_clamp_caps_at_max():
    assert _clamp_limit(500) == MAX_LIMIT


# ─── _built_in_pagination ────────────────────────────────────────────


def test_pagination_empty():
    out = _built_in_pagination({"data": [], "has_more": False})
    assert out["data"] == []
    assert out["has_more"] is False
    assert out["next_starting_after"] is None


def test_pagination_one_page_no_more():
    rows = [{"id": "ch_1"}, {"id": "ch_2"}]
    out = _built_in_pagination({"data": rows, "has_more": False})
    assert out["data"] == rows
    assert out["has_more"] is False
    # When has_more is False, cursor should be None — frontend stops.
    assert out["next_starting_after"] is None


def test_pagination_with_more_returns_cursor():
    rows = [{"id": "ch_1"}, {"id": "ch_2"}]
    out = _built_in_pagination({"data": rows, "has_more": True})
    assert out["data"] == rows
    assert out["has_more"] is True
    # Cursor is the LAST id, per Stripe's starting_after contract.
    assert out["next_starting_after"] == "ch_2"


def test_pagination_missing_data_treated_as_empty():
    out = _built_in_pagination({"has_more": False})
    assert out["data"] == []
    assert out["has_more"] is False
    assert out["next_starting_after"] is None


def test_pagination_missing_has_more_defaults_false():
    out = _built_in_pagination({"data": [{"id": "x"}]})
    assert out["has_more"] is False
    assert out["next_starting_after"] is None


# ─── PR 3d — Refunds endpoint params + gating ────────────────────────


def test_refunds_router_registered():
    """The /payments/refunds route exists on the router with the GET
    method. Catches a missing-decorator regression cheaply."""
    from stripe_data_proxy import router
    paths = {(r.path, tuple(sorted(r.methods or set())))
             for r in router.routes if hasattr(r, "path")}
    assert ("/payments/refunds", ("GET",)) in paths


def test_refunds_param_handler_signature():
    """list_refunds accepts the same filter + cursor shape as
    list_charges — biz, limit, starting_after, created_gte, created_lte.
    Mirrors the established Charges/Payouts pattern."""
    import inspect
    from stripe_data_proxy import list_refunds
    sig = inspect.signature(list_refunds)
    expected = {
        "biz", "limit", "starting_after",
        "created_gte", "created_lte", "user",
    }
    assert expected.issubset(set(sig.parameters.keys())), (
        f"missing params: {expected - set(sig.parameters.keys())}"
    )


def test_refunds_owner_gate_rejects_unowned(monkeypatch):
    """Owner-gating reuses _require_owner_with_acct, which 404s on
    missing biz, 403s on owner mismatch, 409s on no Connect. Hit the
    403 path explicitly so a future refactor of the gate doesn't
    silently expose the endpoint."""
    import asyncio
    from fastapi import HTTPException
    import sb_clients
    from stripe_data_proxy import list_refunds

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: [{
            "id": "biz1", "name": "Foo",
            "owner_id": "the_owner",
            "stripe_account_id": "acct_x",
        }],
    )

    class _U:
        id = "someone_else"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(list_refunds(biz="biz1", user=_U()))
    assert exc.value.status_code == 403


def test_refunds_owner_gate_rejects_no_connect(monkeypatch):
    """409 when the business hasn't completed Connect onboarding."""
    import asyncio
    from fastapi import HTTPException
    import sb_clients
    from stripe_data_proxy import list_refunds

    monkeypatch.setattr(
        sb_clients, "sb_get_as_service",
        lambda path: [{
            "id": "biz1", "name": "Foo",
            "owner_id": "the_owner",
            "stripe_account_id": None,
        }],
    )

    class _U:
        id = "the_owner"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(list_refunds(biz="biz1", user=_U()))
    assert exc.value.status_code == 409


import pytest  # noqa: E402  (needed for raises() blocks above)


# ─── Refunds for a login that may not see who gave ───────────────────

_REFUND_ROW = {
    "id": "re_1", "object": "refund", "amount": 4000, "currency": "usd", "created": 1763600000,
    "status": "succeeded", "reason": "requested_by_customer", "receipt_number": "1234-5678",
    "metadata": {"refunded_by": "someone"},
    "destination_details": {"type": "card", "card": {"reference": "ref_abc"}},
    "charge": {
        "id": "ch_1", "object": "charge", "amount": 4000, "amount_refunded": 4000, "currency": "usd",
        "created": 1763500000, "paid": True, "refunded": True, "status": "succeeded",
        "billing_details": {"name": "Dana Hill", "email": "dana@example.invalid", "phone": "555-0100",
                            "address": {"line1": "1 Elm"}},
        "receipt_email": "dana@example.invalid", "customer": "cus_123",
        "payment_method_details": {"type": "card", "card": {"last4": "4242", "brand": "visa"}},
        "metadata": {"source_type": "gift", "source_id": "g1", "giver_name": "Dana Hill",
                     "covered_fee_cents": "150"},
    },
}


def _refunds_as(monkeypatch, uid, sees):
    import asyncio
    import church_keys
    import church_money_gate
    import sb_clients
    import stripe_data_proxy as sdp
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "id": "biz1", "name": "Grace Harbor", "owner_id": "the_owner", "stripe_account_id": "acct_x"}])
    monkeypatch.setattr(church_money_gate, "tick_admits", lambda *a, **k: True)
    monkeypatch.setattr(church_money_gate, "sees_givers", lambda *a, **k: sees)
    monkeypatch.setattr(church_keys, "wall", lambda *a, **k: None)
    seen = {}

    async def fake_get(path, *, stripe_account_id, params=None):
        seen["path"], seen["acct"] = path, stripe_account_id
        import copy
        return {"data": [copy.deepcopy(_REFUND_ROW)], "has_more": False}
    monkeypatch.setattr(sdp, "_stripe_get", fake_get)

    class _U:
        id = uid
    out = asyncio.run(sdp.list_refunds(biz="biz1", user=_U()))
    assert seen == {"path": "/refunds", "acct": "acct_x"}
    return out["data"][0]


def test_a_bank_holder_without_who_gave_reads_refunds_with_no_giver_in_them(monkeypatch):
    row = _refunds_as(monkeypatch, "treasurer", sees=False)
    text = repr(row)
    for secret in ("Dana", "dana@", "555-0100", "1 Elm", "4242", "visa", "cus_123", "ref_abc", "1234-5678",
                   "refunded_by", "covered_fee"):
        assert secret not in text, secret
    assert row["amount"] == 4000 and row["status"] == "succeeded" and row["reason"] == "requested_by_customer"
    ch = row["charge"]
    assert ch["metadata"] == {"source_type": "gift", "source_id": "g1"}     # the tab still labels it a Gift
    assert ch["payment_method_details"] == {"type": "card"}
    assert ch["amount_refunded"] == 4000 and ch["created"] == 1763500000


def test_the_owner_and_a_login_that_sees_who_gave_read_refunds_as_before(monkeypatch):
    assert _refunds_as(monkeypatch, "the_owner", sees=False) == _REFUND_ROW
    assert _refunds_as(monkeypatch, "treasurer", sees=True) == _REFUND_ROW


def test_a_failed_who_gave_check_hides_the_giver(monkeypatch):
    import church_money_gate

    def boom(*a, **k):
        raise RuntimeError("read failed")
    row = _refunds_as(monkeypatch, "treasurer", sees=False)
    assert "Dana" not in repr(row)
    monkeypatch.setattr(church_money_gate, "sees_givers", boom)
    import stripe_data_proxy as sdp
    assert sdp._sees_givers("biz1", object()) is False
