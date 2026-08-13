"""Site-builder audit (2026-08-13) — "has an account id" was never the
same as "can take money".

Every gate on the platform asked `stripe_account_id is not null`. That is
the cheapest available proxy, not the condition that has to hold.
Standard OAuth hands back an account id for a restricted or
half-onboarded account, and the account.updated webhook faithfully
persists charges_enabled / payouts_enabled / details_submitted into
settings.stripe — where nothing ever read them back.

This was not hypothetical: at the time of the audit, one of the three
connected businesses in production had charges_enabled=false and passed
every gate in the codebase.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import payments_core  # noqa: E402
import store_page  # noqa: E402


def _biz(acct="acct_1", charges=None):
    row = {"id": "b1", "stripe_account_id": acct}
    if charges is not None:
        row["settings"] = {"stripe": {"charges_enabled": charges}}
    return row


# ─── can_charge ──────────────────────────────────────────────────────


def test_no_account_cannot_charge():
    assert payments_core.can_charge({"id": "b1"}) is False
    assert payments_core.can_charge(_biz(acct=None)) is False


def test_charges_enabled_true_can_charge():
    assert payments_core.can_charge(_biz(charges=True)) is True


def test_charges_enabled_false_cannot_charge():
    """The exact production state that passed every previous gate."""
    assert payments_core.can_charge(_biz(charges=False)) is False


def test_string_flags_are_honoured_both_ways():
    """PostgREST hands JSON back as strings often enough to matter."""
    assert payments_core.can_charge(_biz(charges="true")) is True
    assert payments_core.can_charge(_biz(charges="false")) is False


def test_unknown_flags_are_treated_as_chargeable():
    """A business that connects before the account.updated webhook lands
    has no flags yet. Refusing it would break onboarding to fix a subset
    of it — so unknown means yes, deliberately."""
    assert payments_core.can_charge(_biz(charges=None)) is True
    assert payments_core.can_charge(_biz(charges="")) is True


def test_malformed_settings_do_not_crash_the_gate():
    assert payments_core.can_charge(
        {"id": "b1", "stripe_account_id": "acct_1", "settings": "not-a-dict"}) is True
    assert payments_core.can_charge(
        {"id": "b1", "stripe_account_id": "acct_1",
         "settings": {"stripe": "not-a-dict"}}) is True


# ─── the storefront must not offer a button it can't honour ──────────


_ITEM = {"id": "o1", "name": "Thing", "current_price": 25.0,
         "category": "product", "in_stock": True, "image_url": ""}


def test_buy_buttons_render_when_payments_are_ready():
    html = store_page._card(dict(_ITEM), True)
    assert "st-buy" in html and "st-add" in html
    assert "st-unavailable" not in html


def test_buy_buttons_are_replaced_when_payments_are_not_ready():
    """The visitor used to fill a cart, click Buy, and only THEN get a
    409 — as a toast that auto-hides in five seconds."""
    html = store_page._card(dict(_ITEM), False)
    assert "st-buy" not in html and "st-add" not in html
    assert "st-unavailable" in html
    assert "contact us" in html.lower()


def test_sold_out_items_offer_nothing_either_way():
    out = dict(_ITEM, in_stock=False)
    for ready in (True, False):
        html = store_page._card(out, ready)
        assert "st-buy" not in html
        assert "st-unavailable" not in html


def test_readiness_threads_all_the_way_through_sections():
    """A flag that stops at the section builder is the bug being fixed —
    the store computed payments_ready and never passed it down."""
    html = store_page._sections([dict(_ITEM)], "coach", False)
    assert "st-unavailable" in html
    assert "st-buy" not in html
