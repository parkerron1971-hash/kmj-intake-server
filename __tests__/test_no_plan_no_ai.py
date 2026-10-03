"""No plan, no AI on the server (2026-10-03).

A cancelled subscription (or a business that never had one) had no plan,
so no allowance — and an allowance of None meant no limit: only the app's
wall stood between it and Chief on the API. Now it is held at the meter
like an ended no-card trial: allowance 0, bought credits still work.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import billing_limits  # noqa: E402
import usage_metering as um  # noqa: E402

NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _row(status, **over):
    r = {"id": "biz1", "owner_id": "u1", "subscription_status": status,
         "subscription_plan": None, "stripe_subscription_id": "sub_1",
         "trial_ends_at": None, "comp_tier": None, "settings": {},
         "current_period_end": _iso(NOW - timedelta(days=2))}
    r.update(over)
    return r


@pytest.fixture
def meter(monkeypatch):
    calls = {"balance": 0}

    def _since(biz, since):
        calls["since"] = since
        return 50
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setattr(um, "weighted_usage_since", _since)
    monkeypatch.setattr(um, "weighted_usage_this_month", lambda biz: 50)
    monkeypatch.setattr(um, "grant_units_this_month", lambda biz: 0)
    monkeypatch.setattr(um, "is_grandfathered_business", lambda biz, r=None: calls.get("gf", False))
    monkeypatch.setattr(um.credit_ledger, "sync_burn", lambda biz, n: 0)
    monkeypatch.setattr(um.credit_ledger, "balance", lambda biz: calls["balance"])
    return calls


def test_a_cancelled_plan_has_no_ai(meter):
    s = um.usage_summary("biz1", _row("canceled"))
    assert s["allotment"] == 0 and s["blocked"] is True and s["blocked_reason"] == "no_plan"


def test_never_subscribed_has_no_ai(meter):
    s = um.usage_summary("biz1", _row(None, stripe_subscription_id=None, current_period_end=None))
    assert s["blocked"] is True


def test_bought_credits_still_work(meter):
    meter["balance"] = 740
    assert um.usage_summary("biz1", _row("canceled"))["blocked"] is False


def test_usage_counts_from_when_the_plan_ended(meter):
    """Usage in the paid period was the plan's; a pack bought after the
    cancellation must not pay for it."""
    row = _row("canceled")
    um.usage_summary("biz1", row)
    since = datetime.fromisoformat(meter["since"].replace("Z", "+00:00"))
    assert since >= datetime.fromisoformat(row["current_period_end"].replace("Z", "+00:00"))


@pytest.mark.parametrize("status", ["past_due", "unpaid", "incomplete"])
def test_grace_keeps_ai(meter, status):
    """Payment failed: access_state warns, it does not lock."""
    assert um.usage_summary("biz1", _row(status))["blocked"] is False


def test_a_paying_status_on_an_unknown_price_keeps_ai(meter):
    """Never lock out a paying customer because a price id is unmapped."""
    assert um.usage_summary("biz1", _row("active", subscription_plan="price_unknown"))["blocked"] is False


def test_grandfathered_and_comped_keep_ai(meter):
    meter["gf"] = True
    assert um.usage_summary("biz1", _row("canceled"))["blocked"] is False
    meter["gf"] = False
    assert um.usage_summary("biz1", _row("canceled", comp_tier="practice"))["blocked"] is False


def test_nothing_changes_while_enforcement_is_off(meter, monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    s = um.usage_summary("biz1", _row("canceled"))
    assert s["blocked"] is False and s["allotment"] is None


def test_the_refusal_says_what_to_do(monkeypatch):
    monkeypatch.setattr(billing_limits, "chief_can_send", lambda biz: False)
    monkeypatch.setattr(um, "_biz_row", lambda biz: _row("canceled"))
    with pytest.raises(billing_limits.HTTPException) as ei:
        billing_limits.require_units("biz1")
    assert "subscription has ended" in ei.value.detail["message"]
    monkeypatch.setattr(um, "_biz_row", lambda biz: _row(None, stripe_subscription_id=None))
    with pytest.raises(billing_limits.HTTPException) as ei:
        billing_limits.require_units("biz1")
    assert "need a plan" in ei.value.detail["message"]


def test_the_row_reader_carries_the_period_end():
    import inspect
    assert inspect.getsource(um._biz_row).count("current_period_end") == 2
