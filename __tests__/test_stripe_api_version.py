"""current_period_end has been writing NULL, and nothing noticed.

Stripe's Basil version (2025-03-31) REMOVED current_period_start/end
from the Subscription object and moved them onto each subscription item,
which each track their own billing period. This repo pins no API
version, so every live call runs at the account's version — Basil or
later — and `sub_obj.get("current_period_end")` came back None.

businesses.current_period_end has been NULL for every subscription, and
/billing/entitlements has been serving that null to anything that wants
to say when a subscription renews. Nothing broke loudly: access is
decided by subscription_status, so a blank renewal date was the only
symptom.

Pinning is opt-in (STRIPE_API_VERSION). A wrong version string 400s
every call including checkout, which is not a risk worth taking to fix a
display field — so the reader below handles BOTH shapes and stays
correct whether or not a version is ever pinned.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import stripe_billing as sb  # noqa: E402


# ─── Reading the period end from either shape ────────────────────────

def test_basil_shape_reads_off_the_item():
    """The live shape. This is the one that was returning None."""
    sub = {"id": "sub_1", "items": {"data": [{"current_period_end": 1800000000}]}}
    assert sb._period_end(sub) == 1800000000


def test_pre_basil_shape_still_reads_off_the_subscription():
    """Kept working, in case STRIPE_API_VERSION ever pins an older one."""
    sub = {"id": "sub_1", "current_period_end": 1700000000,
           "items": {"data": [{}]}}
    assert sb._period_end(sub) == 1700000000


def test_the_item_wins_when_both_are_present():
    sub = {"current_period_end": 1700000000,
           "items": {"data": [{"current_period_end": 1800000000}]}}
    assert sb._period_end(sub) == 1800000000


def test_a_mixed_interval_subscription_reports_the_next_charge():
    """Items can bill on different intervals. "When does this renew" is
    honestly answered by the EARLIEST end — that is when the customer is
    next charged."""
    sub = {"items": {"data": [{"current_period_end": 1800000000},
                              {"current_period_end": 1750000000},
                              {"current_period_end": 1900000000}]}}
    assert sb._period_end(sub) == 1750000000


def test_nothing_to_read_is_none_not_a_crash():
    for sub in ({}, {"items": {}}, {"items": {"data": []}},
                {"items": {"data": [{}]}}, {"items": None}):
        assert sb._period_end(sub) is None


def test_the_webhook_uses_the_reader():
    """The whole point — _apply_subscription_state is what writes the
    column, so it must not go back to reading the subscription directly."""
    import inspect
    src = inspect.getsource(sb._apply_subscription_state)
    assert "_period_end(sub_obj)" in src
    assert 'sub_obj.get("current_period_end")' not in src


# ─── The opt-in version pin ──────────────────────────────────────────

def test_no_version_header_by_default(monkeypatch):
    """Unset = the account's own version, which is what every call has
    always used. A default here would change behaviour silently."""
    monkeypatch.delenv("STRIPE_API_VERSION", raising=False)
    assert "Stripe-Version" not in sb._stripe_headers()


def test_the_version_pins_when_set(monkeypatch):
    monkeypatch.setenv("STRIPE_API_VERSION", "2025-06-30.basil")
    assert sb._stripe_headers()["Stripe-Version"] == "2025-06-30.basil"


def test_a_blank_setting_does_not_send_an_empty_version(monkeypatch):
    """An empty Railway value must read as "unpinned", not as a version
    of "" — which Stripe would reject on every call."""
    monkeypatch.setenv("STRIPE_API_VERSION", "   ")
    assert "Stripe-Version" not in sb._stripe_headers()


def test_the_pin_does_not_clobber_the_content_type(monkeypatch):
    """_stripe_post passes its form encoding through this."""
    monkeypatch.setenv("STRIPE_API_VERSION", "2025-06-30.basil")
    h = sb._stripe_headers({"Content-Type": "application/x-www-form-urlencoded"})
    assert h["Content-Type"] == "application/x-www-form-urlencoded"
    assert h["Stripe-Version"] == "2025-06-30.basil"


def test_every_stripe_call_carries_the_headers():
    """A call site that skips _stripe_headers is a call site running at a
    different API version from the rest — the exact class of bug this
    fixes. Every auth=(_stripe_key()...) request must pass them."""
    src = pathlib.Path("stripe_billing.py").read_text(encoding="utf-8")
    assert src.count("auth=(_stripe_key()") == src.count("_stripe_headers(")- 1, (
        "a Stripe call site is missing _stripe_headers "
        f"({src.count('auth=(_stripe_key()')} call sites, "
        f"{src.count('_stripe_headers(') - 1} uses)")
