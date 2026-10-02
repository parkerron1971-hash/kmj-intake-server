"""A trial ends on whichever runs out first: the calendar or the tank.

Before this (2026-08-24) only the calendar existed, and the tank was the
tier's whole MONTHLY allowance — because plan_of() treats 'trialing'
exactly like 'active'. Three things followed:

  · a trialing Solutionist got 25,000 credits free, ~$154 of measured
    cost, against a $399 plan they had not paid for;
  · the rational move was to trial the DEAREST tier for the biggest free
    tank and downgrade after, which is a hole, not a funnel;
  · the allowance window is the UTC calendar month, so a trial straddling
    the 1st was handed a SECOND full tank — up to ~$307.

Now: one flat tank for every tier, measured from the day the trial began,
and the trial's first site build is free because 600 credits of a
1,000-credit tank is the demo eating the trial.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import feature_gates as fg  # noqa: E402
import pricing_config as pc  # noqa: E402
import usage_metering as um  # noqa: E402


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _trialing(days_left=3, plan_price="price_pro"):
    return {"id": "biz1", "owner_id": "u1",
            "subscription_status": "trialing",
            "subscription_plan": plan_price,
            "trial_ends_at": _iso(datetime.now(timezone.utc)
                                  + timedelta(days=days_left))}


@pytest.fixture(autouse=True)
def _enforcing(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")


# ─── The tank is flat, and it is not a month ─────────────────────────

def test_the_trial_tank_is_one_thousand_by_default(monkeypatch):
    monkeypatch.delenv("PRICE_TRIAL_CREDITS", raising=False)
    monkeypatch.delenv("TRIAL_CREDITS", raising=False)
    assert pc.trial_credits() == 1000


def test_the_tank_is_a_railway_value_like_every_other_price(monkeypatch):
    monkeypatch.setenv("PRICE_TRIAL_CREDITS", "2500")
    assert pc.trial_credits() == 2500


def test_the_tank_does_not_vary_by_tier():
    """The whole point. If Solutionist's trial were bigger than
    Starter's, the move would be to trial Solutionist and downgrade."""
    tanks = set()
    for price in ("price_starter", "price_pro", "price_practice"):
        row = _trialing(plan_price=price)
        assert um.trial_window_start(row) is not None
        tanks.add(pc.trial_credits())
    assert len(tanks) == 1


def test_the_trial_window_starts_when_the_trial_did(monkeypatch):
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "7")
    row = _trialing(days_left=2)          # 2 left of 7 → started 5 days ago
    start = um.trial_window_start(row)
    began = datetime.fromisoformat(start.replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - began).total_seconds() / 86400
    assert 4.9 < age_days < 5.1


def test_a_trial_across_the_first_of_the_month_gets_one_tank():
    """THE BUG THIS EXISTS FOR. The allowance window is the UTC calendar
    month, so a trial spanning the 1st used to reset to a full second
    tank. Measured from the trial's own start, the 1st is not special."""
    now = datetime.now(timezone.utc)
    row = {"id": "biz1", "owner_id": "u1", "subscription_status": "trialing",
           "trial_ends_at": _iso(now + timedelta(days=2))}
    start = um.trial_window_start(row)
    assert start is not None
    began = datetime.fromisoformat(start.replace("Z", "+00:00"))
    assert began < now
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.day > 8:
        assert began > month_start, "window collapsed back onto the month"


def test_not_on_a_trial_means_no_trial_window():
    for status in ("active", "canceled", "past_due", "", None):
        row = {"id": "b", "subscription_status": status,
               "trial_ends_at": _iso(datetime.now(timezone.utc))}
        assert um.trial_window_start(row) is None


def test_an_unreadable_trial_date_falls_back_to_the_month():
    """Never a crash, never a lockout — the caller just uses the
    calendar month, which is the behaviour that shipped before."""
    assert um.trial_window_start({"subscription_status": "trialing",
                                  "trial_ends_at": "whenever"}) is None
    assert um.trial_window_start({"subscription_status": "trialing"}) is None
    assert um.trial_window_start(None) is None


# ─── Whichever comes first ───────────────────────────────────────────

def test_a_trial_with_credits_left_is_open():
    assert fg.access_state(_trialing(), trial_spent=False)["state"] == "full"


def test_a_trial_that_spent_its_tank_is_locked():
    state = fg.access_state(_trialing(days_left=5), trial_spent=True)
    assert state["state"] == "locked"
    assert state["reason"] == "trial_credits_spent"


def test_the_calendar_still_ends_a_trial_that_has_credits_left():
    expired = _trialing(days_left=-1)
    state = fg.access_state(expired, trial_spent=False)
    assert state["state"] == "locked"
    assert state["reason"] == "trial_expired"


def test_a_spent_tank_never_locks_a_grandfathered_account():
    assert fg.access_state(_trialing(), grandfathered=True,
                           trial_spent=True)["state"] == "full"


def test_a_comped_business_is_not_locked_by_a_spent_tank():
    row = _trialing()
    row["comp_tier"] = "professional"
    assert fg.access_state(row, trial_spent=True)["state"] == "full"


def test_a_paying_subscription_is_untouched_by_the_tank_flag():
    """trial_spent is meaningless off a trial and must not leak into the
    active path — a paying customer who happens to carry the flag keeps
    their workspace."""
    active = {"subscription_status": "active", "subscription_plan": "price_pro"}
    assert fg.access_state(active, trial_spent=True)["state"] == "full"


def test_the_default_leaves_behaviour_exactly_as_it_was():
    """Callers that don't pass trial_spent get the calendar-only rules,
    so an unconverted call site cannot silently start locking people."""
    assert fg.access_state(_trialing())["state"] == "full"


# ─── The gates read it ───────────────────────────────────────────────

def test_exhausted_is_false_while_enforcement_is_dormant(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    assert um.trial_credits_exhausted("biz1", _trialing()) is False


def test_exhausted_is_false_when_not_on_a_trial():
    active = {"id": "biz1", "subscription_status": "active"}
    assert um.trial_credits_exhausted("biz1", active) is False


def test_exhausted_fails_open_when_the_meter_errors(monkeypatch):
    """A metering hiccup must never lock someone out of their own
    workspace."""
    def _boom(*a, **k):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(um, "usage_summary", _boom)
    assert um.trial_credits_exhausted("biz1", _trialing()) is False


def test_both_access_gates_ask_about_the_tank():
    """The lock is worthless if only one caller consults it: the app
    shell reads /billing/access, the API surfaces read
    require_live_access. Both have to pass trial_spent through."""
    import inspect

    import billing_limits
    import stripe_billing
    for mod, fn in ((stripe_billing, "billing_access"),
                    (billing_limits, "require_live_access")):
        src = inspect.getsource(getattr(mod, fn))
        assert "trial_credits_exhausted" in src, f"{fn} ignores the tank"


def test_the_locked_message_says_credits_not_cancellation():
    import inspect

    import billing_limits
    src = inspect.getsource(billing_limits.require_live_access)
    assert "trial_credits_spent" in src
    assert "used all the credits" in src


# ─── The first build is on the house ─────────────────────────────────

def test_the_dial_defaults_to_a_free_first_build(monkeypatch):
    monkeypatch.delenv("PRICE_TRIAL_BUILD_FREE", raising=False)
    monkeypatch.delenv("TRIAL_BUILD_FREE", raising=False)
    assert pc.trial_build_free() is True


def test_the_free_build_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("PRICE_TRIAL_BUILD_FREE", "0")
    assert pc.trial_build_free() is False


def test_no_free_build_when_the_dial_is_off(monkeypatch):
    monkeypatch.setenv("PRICE_TRIAL_BUILD_FREE", "0")
    assert um.trial_first_build_is_free("biz1", _trialing()) is False


def test_no_free_build_off_a_trial():
    active = {"id": "biz1", "subscription_status": "active"}
    assert um.trial_first_build_is_free("biz1", active) is False


def test_the_free_build_check_fails_closed(monkeypatch):
    """The inverse of the lock: an error here must CHARGE, not hand out
    free builds forever."""
    def _boom(*a, **k):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(um.sb_clients, "sb_get_as_service", _boom)
    assert um.trial_first_build_is_free("biz1", _trialing()) is False


def test_the_composer_asks_before_charging_for_a_build():
    src = pathlib.Path("site_composer.py").read_text(encoding="utf-8")
    assert "trial_first_build_is_free" in src
    # The marker is still written, at zero — a free build stays visible
    # in usage and Costs rather than vanishing.
    assert "_units = 0" in src


# ─── The arithmetic this was priced on ───────────────────────────────

def test_a_thousand_credits_with_a_free_build_is_a_real_week(monkeypatch):
    monkeypatch.delenv("PRICE_CHAT_PRICE", raising=False)
    monkeypatch.delenv("CHAT_PRICE", raising=False)
    turns = pc.trial_credits() / pc.chat_price()
    assert turns > 80, f"only {turns:.0f} Chief turns in a trial"
    cogs = turns * pc.MEASURED_CHAT_COST_CENTS / 100
    assert cogs < 10, f"${cogs:.2f} of chat in a single trial"


def test_charging_for_the_build_would_gut_the_tank():
    """Documents WHY the free build exists: without it the same 1,000
    credits is a third of the trial."""
    left = pc.trial_credits() - pc.price_for_build(3)
    assert left / pc.chat_price() < 40


def test_the_trial_tank_is_far_below_every_tier_allowance():
    """If the trial tank ever reached a tier's monthly grant, the hole
    this closed would be open again."""
    for _plan, lim in fg.plan_limits().items():
        assert pc.trial_credits() < lim["chief_messages_monthly"]
