"""The reverse trial: a no-card trial that is over keeps a free workspace
(2026-10-03, feature_gates._free_workspace).

Before, an ended no-card trial met the same full-screen wall as a cancelled
subscription. Now the workspace keeps working — contacts, bookings,
invoices, books — and only what costs money waits for a card: Chief and
the other AI (held at the meter), and the live site (already a preview).
Card trials and paid subscriptions are untouched.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import billing_limits  # noqa: E402
import feature_gates as fg  # noqa: E402
import no_card_trial as nct  # noqa: E402
import usage_metering as um  # noqa: E402

NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _no_card(days_left=3, status="trialing", **over):
    row = {"id": "biz1", "owner_id": "u1", "subscription_status": status,
           "stripe_subscription_id": None, "comp_tier": None,
           "subscription_plan": "price_pro",
           "trial_ends_at": _iso(NOW + timedelta(days=days_left)),
           "settings": {nct.MARKER: {"started_at": _iso(NOW - timedelta(days=4)),
                                     "credits": 500}}}
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")
    monkeypatch.delenv("PRICE_NO_CARD_FREE_WORKSPACE", raising=False)


# ─── Access: free, not locked ────────────────────────────────────────

def test_spent_credits_keep_a_free_workspace():
    assert fg.access_state(_no_card(), trial_spent=True) == {
        "state": "free", "reason": "trial_credits_spent"}


def test_the_calendar_end_keeps_a_free_workspace():
    assert fg.access_state(_no_card(days_left=-1)) == {
        "state": "free", "reason": "trial_expired"}


def test_after_trial_expiry_closes_it_the_workspace_stays_free():
    closed = _no_card(days_left=-2, status="canceled")
    assert fg.access_state(closed) == {"state": "free", "reason": "trial_expired"}


def test_a_running_no_card_trial_is_still_full():
    assert fg.access_state(_no_card())["state"] == "full"


def test_card_trials_and_paid_subscriptions_are_untouched():
    card_trial_spent = _no_card(stripe_subscription_id="sub_1")
    assert fg.access_state(card_trial_spent, trial_spent=True)["state"] == "locked"
    paid_canceled = {"subscription_status": "canceled", "stripe_subscription_id": "sub_1",
                     "trial_ends_at": _iso(NOW - timedelta(days=40)), "settings": {}}
    assert fg.access_state(paid_canceled) == {"state": "locked", "reason": "canceled"}
    hand_given = {"subscription_status": "canceled", "settings": {},
                  "stripe_subscription_id": None, "trial_ends_at": _iso(NOW - timedelta(days=2))}
    assert fg.access_state(hand_given) == {"state": "locked", "reason": "trial_expired"}


def test_the_switch_puts_the_wall_back(monkeypatch):
    monkeypatch.setenv("PRICE_NO_CARD_FREE_WORKSPACE", "0")
    assert fg.access_state(_no_card(days_left=-1))["state"] == "locked"


def test_the_api_gate_lets_a_free_workspace_through(monkeypatch):
    """require_live_access only stops 'locked'. What a free workspace may
    not do is stopped where it costs money: require_card and the meter."""
    row = _no_card(days_left=-1)
    monkeypatch.setattr(um, "_biz_row", lambda biz: row)
    monkeypatch.setattr(um, "is_grandfathered_business", lambda biz, r=None: False)
    monkeypatch.setattr(um, "trial_credits_exhausted", lambda biz, r=None: False)
    billing_limits.require_live_access("biz1")


# ─── The meter: no AI without a card (or bought credits) ─────────────

@pytest.fixture
def meter(monkeypatch):
    calls = {}

    def _since(biz, since):
        calls["since"] = since
        return calls.get("used", 0)
    monkeypatch.setattr(um, "weighted_usage_since", _since)
    monkeypatch.setattr(um, "weighted_usage_this_month", lambda biz: 9999)
    monkeypatch.setattr(um, "grant_units_this_month", lambda biz: 0)
    monkeypatch.setattr(um, "is_grandfathered_business", lambda biz, r=None: False)
    monkeypatch.setattr(um.credit_ledger, "sync_burn", lambda biz, n: 0)
    monkeypatch.setattr(um.credit_ledger, "balance", lambda biz: calls.get("balance", 0))
    return calls


def test_an_ended_no_card_trial_has_no_ai(meter):
    s = um.usage_summary("biz1", _no_card(days_left=-1, status="canceled"))
    assert s["allotment"] == 0 and s["on_trial"] is False
    assert s["blocked"] is True and s["blocked_reason"] == "trial_over"


def test_also_before_the_hourly_sweep_closes_it(meter):
    """Still 'trialing' with the end date passed: no AI either."""
    s = um.usage_summary("biz1", _no_card(days_left=-1))
    assert s["blocked"] is True


def test_bought_credits_still_work(meter):
    meter["balance"] = 740
    s = um.usage_summary("biz1", _no_card(days_left=-1, status="canceled"))
    assert s["blocked"] is False


def test_usage_after_the_trial_is_measured_from_its_end(meter):
    """What the trial spent was the trial's: a pack bought afterwards must
    not be drawn down to pay for it."""
    row = _no_card(days_left=-1, status="canceled")
    um.usage_summary("biz1", row)
    since = datetime.fromisoformat(meter["since"].replace("Z", "+00:00"))
    ended = datetime.fromisoformat(row["trial_ends_at"].replace("Z", "+00:00"))
    assert since >= ended


def test_a_running_no_card_trial_keeps_its_tank(meter):
    s = um.usage_summary("biz1", _no_card())
    assert s["allotment"] == 500 and s["blocked"] is False


def test_later_z_is_url_safe():
    out = um._later_z("2026-10-01T00:00:00Z", "2026-10-05T12:00:00+00:00")
    assert out == "2026-10-05T12:00:00Z"
    assert um._later_z("2026-10-01T00:00:00Z", None) == "2026-10-01T00:00:00Z"
    assert "+" not in um._later_z("2026-10-01T00:00:00Z", "garbage")


def test_the_refusal_says_the_workspace_still_works(monkeypatch):
    monkeypatch.setattr(um, "_biz_row", lambda biz: _no_card(days_left=-1, status="canceled"))
    monkeypatch.setattr(billing_limits, "chief_can_send", lambda biz: False)
    with pytest.raises(billing_limits.HTTPException) as ei:
        billing_limits.require_units("biz1")
    msg = ei.value.detail["message"]
    assert "Add one in Settings → Billing" in msg and "keep working" in msg


# ─── Building waits for a card once the trial is over ───────────────

def test_no_build_or_blueprint_after_the_trial(monkeypatch):
    m = {"started_at": _iso(NOW), "credits": 500, "phone_hash": "h",
         "phone_verified_at": _iso(NOW)}
    ended = _no_card(days_left=-1, status="canceled", settings={nct.MARKER: m})
    monkeypatch.setattr(um, "_biz_row", lambda biz: ended)
    for fn in (nct.check_build, nct.check_phone):
        with pytest.raises(nct.CardRequired) as ei:
            fn("biz1")
        assert ei.value.what == "trial_over"


# ─── The mail ────────────────────────────────────────────────────────

def test_the_ended_mail_says_the_workspace_keeps_working(monkeypatch):
    import lifecycle_emails as le
    closed = _no_card(days_left=-1, status="canceled")
    need = le._classify(closed, NOW)
    assert need == {"kind": "trial_ended", "reason": "no_card_trial_expired"}
    body = le.trial_ended_body(business_name="Ana's Studio", first_name="Ana",
                               reason="no_card_trial_expired")
    assert "keeps working" in body and "wait for a card" in body
