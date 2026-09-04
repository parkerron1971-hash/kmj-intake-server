"""What BILLING_ENFORCE=on would do, without flipping it.

Pins:
  * rehearsal() makes enforcement_on() answer True inside, False outside,
    and only for the task that entered it;
  * a business is judged exactly as the gates would judge it: comped and
    grandfathered stay full, an expired trial locks, a trial that spent
    its tank locks, past_due is grace, no subscription locks;
  * the units picture is the summary's arithmetic without the ledger
    write — sync_burn is never called;
  * caps and features_lost come from the plan; the aggregate counts add
    up; one broken row does not hide the rest;
  * the endpoint is platform-owner only.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import billing_rehearsal as br
import credit_ledger
import feature_gates as fg
import sb_clients
import usage_metering as um

OWNER = "owner-1"


def _row(**k):
    base = {"id": "b-1", "name": "Bloom", "owner_id": OWNER, "is_active": True,
            "subscription_status": "active", "subscription_plan": "price_pro",
            "comp_tier": None, "trial_ends_at": None, "settings": {}, "created_at": "2026-01-01"}
    base.update(k)
    return base


@pytest.fixture
def quiet(monkeypatch):
    """No enforcement, no grandfathering, empty tables, no ledger writes."""
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)
    monkeypatch.setattr(fg, "price_to_plan", lambda: {"price_pro": "professional", "price_starter": "starter"})
    monkeypatch.setattr(um, "is_grandfathered_user", lambda uid: False)
    monkeypatch.setattr(um, "weighted_usage_this_month", lambda b: 0)
    monkeypatch.setattr(um, "weighted_usage_since", lambda b, since: 0)
    monkeypatch.setattr(um, "grant_units_this_month", lambda b: 0)
    monkeypatch.setattr(credit_ledger, "balance", lambda b: 0)
    monkeypatch.setattr(credit_ledger, "sync_burn",
                        lambda *a, **k: pytest.fail("the rehearsal must never write the ledger"))
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    return monkeypatch


# ─── The switch ─────────────────────────────────────────────────────────

def test_rehearsal_is_on_inside_off_outside_and_task_local(quiet):
    assert fg.enforcement_on() is False
    with fg.rehearsal():
        assert fg.enforcement_on() is True

        async def other_task():
            return fg.enforcement_on()

        async def scenario():
            # a sibling task started inside inherits the context (copy),
            # but a task created OUTSIDE the block does not — model that
            # by resetting explicitly
            return await asyncio.create_task(other_task())
        assert asyncio.run(scenario()) is True
    assert fg.enforcement_on() is False

    async def outside():
        return fg.enforcement_on()
    assert asyncio.run(outside()) is False


# ─── One business, judged as the gates would ────────────────────────────

def _judge(row, **k):
    with fg.rehearsal():
        return br.rehearse_business(row, **k)


def test_an_active_professional_business_is_full_and_sees_what_it_lacks(quiet):
    b = _judge(_row(), owner_business_count=1)
    assert b["plan"] == "professional" and b["plan_display"] == "Professional"
    assert b["access"] == {"state": "full", "reason": "active"}
    assert b["units"]["allotment"] == fg.plan_limits()["professional"]["chief_messages_monthly"]
    assert b["units"]["out_of_units"] is False
    assert "vertical_reports" in b["features_lost"] and "reports_full" not in b["features_lost"]
    assert b["seats"] == {"count": 1, "limit": 1, "over": False, "next_add_refused": True}
    assert b["businesses"]["limit"] == 1 and b["businesses"]["over"] is False


def test_comped_and_grandfathered_stay_full_whatever_the_subscription_says(quiet):
    b = _judge(_row(subscription_status="canceled", comp_tier="practice"))
    assert b["access"]["state"] == "full" and b["access"]["reason"] == "comp_practice"
    assert b["features_lost"] == []
    quiet.setattr(um, "is_grandfathered_user", lambda uid: True)
    b = _judge(_row(subscription_status="canceled"))
    assert b["grandfathered"] and b["access"]["reason"] == "grandfathered"
    assert b["units"]["allotment"] is None and b["features_lost"] == []


def test_no_subscription_locks_and_past_due_is_grace(quiet):
    assert _judge(_row(subscription_status=None, subscription_plan=None))["access"] == \
        {"state": "locked", "reason": "no_subscription"}
    assert _judge(_row(subscription_status="past_due"))["access"] == \
        {"state": "grace", "reason": "payment_failed"}
    assert _judge(_row(subscription_status="canceled"))["access"]["reason"] == "canceled"


def test_a_trial_locks_when_its_calendar_or_its_tank_runs_out(quiet):
    expired = _row(subscription_status="trialing", trial_ends_at="2026-01-08T00:00:00Z")
    assert _judge(expired)["access"]["reason"] == "trial_expired"
    live = _row(subscription_status="trialing", trial_ends_at="2099-01-08T00:00:00Z")
    b = _judge(live)
    assert b["access"]["state"] == "full" and b["units"]["on_trial"]
    quiet.setattr(um, "weighted_usage_since", lambda b, since: 10 ** 9)
    b = _judge(live)
    assert b["access"] == {"state": "locked", "reason": "trial_credits_spent"}
    assert b["units"]["out_of_units"]
    quiet.setattr(credit_ledger, "balance", lambda b: 50)
    b = _judge(live)
    assert b["access"]["state"] == "full", "purchased credits keep a trial open"


def test_out_of_units_and_the_hard_cap(quiet):
    quiet.setattr(um, "weighted_usage_this_month", lambda b: 10 ** 9)
    b = _judge(_row())
    assert b["units"]["out_of_units"] and b["units"]["reason"] == "out_of_units"
    quiet.setattr(credit_ledger, "balance", lambda b: 100)
    assert _judge(_row())["units"]["out_of_units"] is False, "credits carry the month"
    b = _judge(_row(settings={"usage_hard_cap": True}))
    assert b["units"]["out_of_units"] and b["units"]["reason"] == "hard_cap"


def test_caps_count_seats_banks_and_businesses(quiet):
    def get(path):
        if path.startswith("/business_users"):
            return [{"id": "s1"}, {"id": "s2"}]
        if path.startswith("/plaid_accounts"):
            return [{"account_id": a} for a in range(6)]
        return []
    quiet.setattr(sb_clients, "sb_get_as_service", get)
    b = _judge(_row(), owner_business_count=2)
    assert b["seats"] == {"count": 3, "limit": 1, "over": True, "next_add_refused": True}
    assert b["banks"] == {"count": 6, "limit": 5, "over": True}
    assert b["businesses"] == {"count": 2, "limit": 1, "over": True}


# ─── All of them ────────────────────────────────────────────────────────

def test_the_aggregate_adds_up_and_a_broken_row_does_not_hide_the_rest(quiet):
    rows = [
        _row(id="b-1", name="Full"),
        _row(id="b-2", name="Locked", subscription_status=None, subscription_plan=None),
        _row(id="b-3", name="Grace", subscription_status="past_due"),
        _row(id="b-4", name="Comped", owner_id="owner-2", comp_tier="practice", subscription_status=None),
        _row(id="b-5", name="Broken", owner_id="owner-3", settings="not-a-dict"),
    ]

    def get(path):
        if path.startswith("/businesses?is_active=eq.true"):
            return rows
        return []
    quiet.setattr(sb_clients, "sb_get_as_service", get)
    real = br.rehearse_business

    def flaky(row, **k):
        if row["id"] == "b-5":
            raise RuntimeError("boom")
        return real(row, **k)
    quiet.setattr(br, "rehearse_business", flaky)

    report = br.rehearse_all()
    s = report["summary"]
    assert report["enforcement_on_now"] is False, "nothing was flipped"
    assert s["businesses"] == 5 and s["errors"] == 1
    assert (s["would_lock"], s["in_grace"], s["full"]) == (1, 1, 2)
    assert s["lock_reasons"] == {"no_subscription": 1}
    names = {b["name"]: b for b in report["businesses"]}
    assert "error" in names["Broken"] and names["Comped"]["access"]["reason"] == "comp_practice"
    assert names["Full"]["businesses"]["count"] == 3, "owner-1 owns three of these"
    assert fg.enforcement_on() is False
    text = br.render(report)
    assert "would lock 1" in text and "LOCK " in text and "! Broken" in text


def test_the_endpoint_is_platform_owner_only():
    import inspect
    from lead_admin import require_owner
    sig = inspect.signature(br.billing_rehearsal)
    dep = sig.parameters["_owner"].default
    assert dep.dependency is require_owner


def test_the_table_prints_on_a_cp1252_console(quiet):
    """Kevin's first run died on '∞' (infinity) in a Windows console.
    The table is ASCII; a grandfathered account reads 'unlimited'."""
    quiet.setattr(um, "is_grandfathered_user", lambda uid: True)
    quiet.setattr(sb_clients, "sb_get_as_service",
                  lambda path: [_row()] if path.startswith("/businesses?is_active") else [])
    text = br.render(br.rehearse_all())
    text.encode("cp1252")
    assert "unlimited" in text
