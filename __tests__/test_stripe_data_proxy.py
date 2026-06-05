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
