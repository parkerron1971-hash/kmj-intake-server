"""Site-builder audit (2026-08-13) — nothing checked that a buyer would
ever RECEIVE what they paid for.

There is no is_digital column. The frontend preset is category 'product'
with requires_shipping false, so "digital product with no file" is not a
state this schema can express. What IS expressible — and what actually
takes money for nothing — is an item with no delivery path at all: not
shipped, no hosted file, and no note saying how the buyer gets it.

Production had exactly one such item when this was written: a $1 product
with requires_shipping false, no file and no note.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import offering_profiles as op  # noqa: E402


READY_STATE = {
    "booking_enabled": True,
    "stripe_connected": True,
    "site_slug": "acme",
    "booking_url": "https://acme.example/book",
    "store_url": "https://acme.example/store",
    "product_file_ids": {"has-file"},
}


def _sellable(**kw):
    row = {"id": "o1", "name": "Thing", "category": "product",
           "current_price": 25.0}
    row.update(kw)
    return row


def _codes(o, state=None):
    r = op.offering_readiness(o, state or READY_STATE)
    return {i["code"] for i in r["issues"]}


def test_item_with_no_delivery_path_is_flagged():
    """Money taken, buyer holding a receipt for nothing."""
    assert "no_delivery_path" in _codes(_sellable())


def test_shipped_item_has_a_delivery_path():
    assert "no_delivery_path" not in _codes(_sellable(requires_shipping=True))


def test_item_with_a_hosted_file_has_a_delivery_path():
    assert "no_delivery_path" not in _codes(_sellable(id="has-file"))


def test_item_with_a_collection_note_has_a_delivery_path():
    assert "no_delivery_path" not in _codes(
        _sellable(fulfillment_note="Collect from the front desk"))


def test_a_blank_note_is_not_a_delivery_path():
    assert "no_delivery_path" in _codes(_sellable(fulfillment_note="   "))


def test_bookable_offerings_are_not_asked_for_a_delivery_path():
    """A session is not shipped, downloaded or collected."""
    booking = {"id": "s1", "name": "Session", "category": "service",
               "current_price": 90.0, "duration_min": 60}
    assert "no_delivery_path" not in _codes(booking)


def test_missing_file_map_does_not_invent_a_failure():
    """A state built before product_file_ids existed must not make every
    item look undeliverable."""
    state = dict(READY_STATE)
    state.pop("product_file_ids")
    assert "no_delivery_path" in _codes(_sellable(), state)
    assert "no_delivery_path" not in _codes(_sellable(requires_shipping=True), state)


def test_readiness_query_selects_the_columns_the_check_reads():
    """The check is only as good as the row it is handed — omitting
    these columns would report a missing delivery path on every sellable
    offering that has one."""
    import inspect
    src = inspect.getsource(op.business_readiness)
    assert "requires_shipping" in src
    assert "fulfillment_note" in src
