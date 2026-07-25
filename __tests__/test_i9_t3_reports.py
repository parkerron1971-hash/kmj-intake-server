"""Phase I.9 — Tier-3 analytical reports (Budget vs Actual, Forecast,
Profitability, Trends)."""
from __future__ import annotations

import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import gl_engine as gl  # noqa: E402
import gl_reports_t3 as t3  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    fb.rows("contacts").append({"id": "c1", "name": "Sarah", "email": None, "phone": None})
    return fb


def _inv(fb, iid, total, *, sent, paid=None, status="paid", category="coaching"):
    fb.rows("invoices").append({
        "id": iid, "business_id": "biz1", "invoice_number": iid.upper(), "total": total,
        "status": status, "sent_at": sent, "created_at": sent, "due_date": sent[:10],
        "paid_at": paid or sent, "payment_method": "cash", "stripe_payment_url": None,
        "refund_amount_cents": None, "refunded_at": None, "contact_id": "c1",
        "category": category, "contacts": {"name": "Sarah", "email": None}})


def _exp(fb, eid, amount, *, category="operating", d):
    fb.rows("business_expenses").append({
        "id": eid, "business_id": "biz1", "amount": amount, "category": category,
        "subcategory": None, "vendor": "V", "date": d})


def test_budget_upsert_and_vs_actual(fake):
    fb = fake
    _inv(fb, "i1", 1000, sent="2026-06-01T00:00:00Z")
    _exp(fb, "e1", 300, d="2026-06-05")
    gl.backfill("biz1", "consultant")
    t3.upsert_budgets("biz1", 2026, 6, [
        {"category": "revenue", "amount": 1200},
        {"category": "operating", "amount": 250},
        {"category": "bogus", "amount": 1},          # invalid → skipped
    ])
    assert len(fb.rows("business_budgets")) == 2
    # Upsert is idempotent (update, not duplicate).
    t3.upsert_budgets("biz1", 2026, 6, [{"category": "revenue", "amount": 1500}])
    assert len(fb.rows("business_budgets")) == 2

    biz_row = {"settings": {}}
    out = t3.budget_vs_actual("biz1", biz_row, "custom", "2026-06-01", "2026-06-30")
    rows = {r["category"]: r for r in out["rows"]}
    assert rows["revenue"]["actual"] == 1000.0
    assert rows["revenue"]["budget"] == 1500.0
    assert rows["revenue"]["variance"] == -500.0     # under target
    assert rows["operating"]["actual"] == 300.0
    assert rows["operating"]["variance"] == 50.0     # over budget
    assert rows["tax"]["budget"] is None             # no budget, no allocator


def test_budget_profit_first_fallback(fake):
    fb = fake
    _inv(fb, "i1", 1000, sent="2026-06-01T00:00:00Z")
    gl.backfill("biz1", "consultant")
    biz_row = {"settings": {"revenue_allocator": {"operating": 50, "owner_pay": 30},
                            "financial": {"tax_rate": 15}}}
    out = t3.budget_vs_actual("biz1", biz_row, "custom", "2026-06-01", "2026-06-30")
    rows = {r["category"]: r for r in out["rows"]}
    assert rows["operating"]["budget"] == 500.0      # 50% × $1000 actual revenue
    assert rows["operating"]["budget_source"] == "profit_first"
    assert rows["tax"]["budget"] == 150.0


def test_cash_forecast_trend_and_band(fake):
    fb = fake
    # Six months of history: deposits of 1000, 1100, ..., 1500 (cash inflows).
    for i, m in enumerate(("2026-01", "2026-02", "2026-03", "2026-04", "2026-05")):
        fb.rows("plaid_transactions").append({
            "transaction_id": f"t{i}", "business_id": "biz1", "account_id": "a1",
            "amount": -(1000 + i * 100), "date": f"{m}-15", "pending": False,
            "excluded_from_books": False, "business_category": None,
            "business_subcategory": None, "plaid_category_primary": "INCOME",
            "plaid_category_detail": "INCOME_WAGES", "reconciled_to_payout_id": None})
    fb.rows("plaid_accounts").append({
        "account_id": "a1", "business_id": "biz1", "type": "depository",
        "included_in_bookkeeping": True, "deleted_at": None, "last_balance": 6000.0})
    import plaid_categorization as pc
    if not pc.is_income_category("INCOME", "INCOME_WAGES"):
        pytest.skip("income mapping differs")
    gl.backfill("biz1", "consultant")
    # Unpaid invoice due soon + open bill.
    fb.rows("invoices").append({
        "id": "i9", "business_id": "biz1", "total": 800, "status": "sent",
        "paid_at": None, "due_date": "2026-06-20", "sent_at": "2026-06-01T00:00:00Z",
        "created_at": "2026-06-01T00:00:00Z", "payment_method": None,
        "stripe_payment_url": "x", "refund_amount_cents": None, "refunded_at": None})
    fb.rows("bills").append({"id": "b1", "business_id": "biz1", "amount": 200,
                             "status": "unpaid", "due_date": "2026-06-25"})
    out = t3.cash_flow_forecast("biz1")
    assert out["trend"]["months_used"] == 5
    assert out["trend"]["mean_monthly_flow"] == 1200.0
    h30 = out["horizons"][0]
    assert h30["days"] == 30
    assert h30["projected"] == out["current_cash"] + 1200.0
    assert h30["low"] < h30["projected"] < h30["high"]
    assert h30["scheduled_ar_in"] == 800.0
    assert h30["scheduled_ap_out"] == 200.0


def test_profitability_contribution_and_method_surfaced(fake):
    fb = fake
    _inv(fb, "i1", 600, sent="2026-06-01T00:00:00Z", category="coaching")
    _inv(fb, "i2", 400, sent="2026-06-02T00:00:00Z", category="design")
    _exp(fb, "e1", 500, d="2026-06-05")
    gl.backfill("biz1", "consultant")
    out = t3.profitability("biz1", "custom", "2026-06-01", "2026-06-30")
    assert out["total_revenue"] == 1000.0 and out["total_expenses"] == 500.0
    offs = {o["offering"]: o for o in out["by_offering"]}
    assert offs["coaching"]["allocated_overhead"] == 300.0   # 60% share of $500
    assert offs["coaching"]["contribution"] == 300.0
    assert offs["design"]["contribution"] == 200.0
    assert "proportionally" in out["method"]                 # fork surfaced in-band


def test_trends_momentum_and_seasonality(fake, monkeypatch):
    # trends() reads the wall clock: the 12-month window ends at the current
    # month and momentum compares the last 3 FULL months against the prior 3.
    # With fixed 2026-01..05 invoices that made the expected averages drift
    # month to month — the assertion below only held during 2026-06 and went
    # red on 2026-07-01. Pin the clock so the arithmetic is stable forever.
    from datetime import date as _date
    monkeypatch.setattr(gl, "_today", lambda: _date(2026, 6, 15))
    fb = fake
    _inv(fb, "i1", 100, sent="2026-01-10T00:00:00Z")
    _inv(fb, "i2", 200, sent="2026-02-10T00:00:00Z")
    _inv(fb, "i3", 300, sent="2026-03-10T00:00:00Z")
    _inv(fb, "i4", 400, sent="2026-04-10T00:00:00Z")
    _inv(fb, "i5", 500, sent="2026-05-10T00:00:00Z")
    gl.backfill("biz1", "consultant")
    out = t3.trends("biz1")
    assert len(out["monthly"]) == 12
    june = [m for m in out["monthly"] if m["month"] == "2026-05"][0]
    assert june["revenue"] == 500.0
    mom = out["momentum"]
    assert mom["revenue_last3_avg"] == 400.0                 # (300+400+500)/3
    assert mom["revenue_prior3_avg"] > 0
    assert any(s["month_num"] == 1 and s["avg_revenue"] == 100.0
               for s in out["seasonality"])
