"""The Money auditor reads the billing rails and reports only what needs eyes.

A fake PostgREST answers by table. Each check is pinned by the finding it
must raise, and by staying quiet when the rails are right. A read that
fails is reported as unseen, never as "all clear".
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import money_auditor as ma

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeDB:
    """tables: name -> list of rows, or an int status to fail with."""

    def __init__(self, **tables):
        self.tables = tables
        self.posts = []

    async def get(self, url, headers=None, params=None):
        table = url.rsplit("/", 1)[-1]
        data = self.tables.get(table, [])
        if isinstance(data, int):
            return _Resp(data, {"message": "boom"})
        rows = list(data)
        p = params or {}
        # Just enough filtering for the auditor's webhook reads.
        if p.get("type"):
            rows = [r for r in rows if r.get("type") == p["type"].removeprefix("eq.")]
        if p.get("processed_error") == "not.is.null":
            rows = [r for r in rows if r.get("processed_error")]
        if p.get("processed_error") == "is.null":
            rows = [r for r in rows if not r.get("processed_error")]
        if p.get("processed_at") == "is.null":
            rows = [r for r in rows if not r.get("processed_at")]
        return _Resp(200, rows)

    async def post(self, url, headers=None, json=None):
        self.posts.append((url.rsplit("/", 1)[-1], json))
        return _Resp(201, None)


def run(db, prices=None, monkeypatch=None):
    if monkeypatch is not None:
        import feature_gates
        monkeypatch.setattr(feature_gates, "price_to_plan", lambda: dict(prices or {}))
    return asyncio.run(ma.audit(db, {}, now=NOW))


def codes(result):
    return {f["code"] for f in result["findings"]}


def test_quiet_when_the_rails_are_right(monkeypatch):
    db = FakeDB(
        businesses=[{"id": "b1", "name": "Acme", "subscription_status": "active",
                     "subscription_plan": "price_pro", "stripe_subscription_id": "sub_1"}],
        stripe_webhook_events=[{"id": "evt_1", "type": "invoice.paid",
                                "processed_at": NOW.isoformat()}],
        credit_ledger=[{"business_id": "b1", "delta_units": 1000},
                       {"business_id": "b1", "delta_units": -200}],
    )
    result = run(db, {"price_pro": "professional"}, monkeypatch)
    assert result["findings"] == []
    assert result["details"]["unseen"] == []


def test_subscriptions_without_any_recorded_webhook_is_flagged(monkeypatch):
    """The 2026-10-01 discovery: 0 events ever, while businesses pay."""
    db = FakeDB(businesses=[{"id": "b1", "name": "Acme", "subscription_status": "active",
                             "subscription_plan": "price_pro",
                             "stripe_subscription_id": "sub_1"}],
                stripe_webhook_events=[], credit_ledger=[])
    assert "webhooks:never_recorded" in codes(run(db, {"price_pro": "professional"}, monkeypatch))


def test_failed_payments_past_due_and_failed_webhooks(monkeypatch):
    db = FakeDB(
        businesses=[{"id": "b2", "name": "Grace Church", "subscription_status": "past_due",
                     "stripe_subscription_id": "sub_2"}],
        stripe_webhook_events=[
            {"id": "evt_a", "type": "invoice.payment_failed", "business_id": "b2",
             "processed_at": NOW.isoformat()},
            {"id": "evt_b", "type": "customer.subscription.updated",
             "processed_error": "KeyError: items"},
        ],
        credit_ledger=[],
    )
    got = codes(run(db, {"price_pro": "professional"}, monkeypatch))
    assert {"payments:failed", "subs:past_due", "webhooks:failed"} <= got


def test_stuck_webhook(monkeypatch):
    db = FakeDB(businesses=[],
                stripe_webhook_events=[{"id": "evt_s", "type": "checkout.session.completed"}],
                credit_ledger=[])
    assert "webhooks:stuck" in codes(run(db, {"p": "starter"}, monkeypatch))


def test_trial_that_ended_but_still_reads_trialing(monkeypatch):
    db = FakeDB(businesses=[
        {"id": "b3", "name": "Old trial", "subscription_status": "trialing",
         "trial_ends_at": (NOW - timedelta(days=3)).isoformat(), "subscription_plan": "price_pro"},
        {"id": "b4", "name": "Fresh trial", "subscription_status": "trialing",
         "trial_ends_at": (NOW + timedelta(days=3)).isoformat(), "subscription_plan": "price_pro"},
    ], stripe_webhook_events=[{"id": "evt"}], credit_ledger=[])
    result = run(db, {"price_pro": "professional"}, monkeypatch)
    [f] = [f for f in result["findings"] if f["code"] == "subs:trial_overrun"]
    assert "Old trial" in f["detail"] and "Fresh trial" not in f["detail"]


def test_paying_on_an_unrecognised_price_but_not_comped(monkeypatch):
    db = FakeDB(businesses=[
        {"id": "b5", "name": "Mystery", "subscription_status": "active",
         "subscription_plan": "price_old"},
        {"id": "b6", "name": "Comped", "subscription_status": "active",
         "subscription_plan": "price_old", "comp_tier": "professional"},
    ], stripe_webhook_events=[{"id": "evt"}], credit_ledger=[])
    result = run(db, {"price_pro": "professional"}, monkeypatch)
    [f] = [f for f in result["findings"] if f["code"] == "subs:plan_unrecognised"]
    assert "Mystery" in f["detail"] and "Comped" not in f["detail"]


def test_negative_credit_balance(monkeypatch):
    db = FakeDB(businesses=[], stripe_webhook_events=[{"id": "evt"}],
                credit_ledger=[{"business_id": "b7", "delta_units": 100},
                               {"business_id": "b7", "delta_units": -300}])
    assert "credits:negative" in codes(run(db, {"p": "starter"}, monkeypatch))


def test_a_failed_read_is_unseen_not_all_clear(monkeypatch):
    db = FakeDB(businesses=500, stripe_webhook_events=500, credit_ledger=500)
    result = run(db, {}, monkeypatch)
    assert result["findings"] == []
    unseen = " ".join(result["details"]["unseen"])
    for word in ("subscriptions", "webhook", "credits", "plan prices"):
        assert word in unseen


def test_tick_records_a_run_and_logs_each_finding(monkeypatch):
    db = FakeDB(businesses=[{"id": "b2", "name": "Grace", "subscription_status": "past_due",
                             "stripe_subscription_id": "sub_2"}],
                stripe_webhook_events=[], credit_ledger=[])
    import feature_gates
    monkeypatch.setattr(feature_gates, "price_to_plan", lambda: {"p": "starter"})
    monkeypatch.setattr(ma, "_service_headers", lambda: {})
    monkeypatch.setattr(ma.httpx, "AsyncClient", lambda **kw: _Ctx(db))
    out = asyncio.run(ma.audit_tick())
    assert out["ok"] and out["findings"] == 2
    tables = [t for t, _ in db.posts]
    assert tables.count("platform_changelog") == 2
    run_row = [j for t, j in db.posts if t == "platform_agent_runs"][0]
    assert run_row["agent"] == "money_auditor" and run_row["ok"] is True
    assert run_row["findings"] == 2


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("MONEY_AUDITOR", "off")
    assert asyncio.run(ma.audit_tick()) == {"skipped": True}


class _Ctx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *a):
        return False
