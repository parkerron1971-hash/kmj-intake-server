"""Step 4 (2026-11-03): the reports a church needs. Funds matches a giving
fund to the year fund of the same name (Kevin's pick "A"); Giving & income
adds gifts by fund and by way; one person's giving; the budget in the
church's own line names, with no Profit First amounts made up for it."""
from __future__ import annotations

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import expense_lines
import funds
import giving_reports as gr
import gl_reports_t2
import gl_reports_t3
import reports_router

BIZ = "00000000-0000-4000-8000-0000000000c2"
P1 = "00000000-0000-4000-8000-00000000aa01"
P2 = "00000000-0000-4000-8000-00000000aa02"

GIFTS = [
    {"id": "g1", "contact_id": P1, "contacts": {"name": "Grace Holloway"}, "gift_fund": "Tithes",
     "total": 100, "payment_method": "stripe", "paid_at": "2026-10-05T15:00:00Z"},
    {"id": "g2", "contact_id": P2, "contacts": {"name": "Marcus Reed"}, "gift_fund": "Youth",
     "total": 50, "payment_method": "cash", "paid_at": "2026-10-12T15:00:00Z"},
    {"id": "g3", "contact_id": P1, "contacts": {"name": "Grace Holloway"}, "gift_fund": "youth fund",
     "total": 40, "refund_amount_cents": 1000, "payment_method": "check", "paid_at": "2026-10-19T15:00:00Z"},
    {"id": "g4", "contact_id": P2, "contacts": {"name": "Marcus Reed"}, "gift_fund": None,
     "total": 25, "payment_method": "cashapp", "paid_at": "2026-10-26T15:00:00Z"},
]


@pytest.fixture
def church(monkeypatch):
    monkeypatch.setattr(gr, "_gifts", lambda biz, start, end, contact_id=None:
                        [g for g in GIFTS if contact_id in (None, g["contact_id"])])
    monkeypatch.setattr(gr, "_configured", lambda biz: ["Tithes", "Offering", "Youth"])
    monkeypatch.setattr(funds, "switched_on", lambda biz: True)
    monkeypatch.setattr(funds, "list_funds", lambda biz, year=None: [
        {"id": "f-youth", "name": "Youth Fund", "year": 2026},
        {"id": "f-house", "name": "Housing", "year": 2026}])
    monkeypatch.setattr(funds, "items_for", lambda biz, ids: [
        {"fund_id": "f-youth", "direction": "out", "amount": 30, "entry_date": "2026-10-20"},
        {"fund_id": "f-youth", "direction": "out", "amount": 999, "entry_date": "2025-12-31"},   # before the window
        {"fund_id": "f-youth", "direction": "in", "amount": 5, "entry_date": "2026-10-21"},     # money in isn't spending
        {"fund_id": "f-house", "direction": "out", "amount": 900, "entry_date": "2026-10-01"}])


def _funds():
    return gr.funds_report(BIZ, "custom", "2026-01-01", "2026-12-31")


def test_a_giving_fund_meets_its_year_fund_by_name(church):
    rows = {r["fund"]: r for r in _funds()["funds"]}
    youth = rows["Youth"]
    assert youth["given"] == 80.0 and youth["gifts"] == 2           # 50 + (40 - 10 refunded)
    assert youth["spent"] == 30.0 and youth["left"] == 50.0 and youth["year_fund"] == "Youth Fund"
    assert youth["designated"] is True


def test_general_funds_and_gifts_without_a_fund(church):
    rows = {r["fund"]: r for r in _funds()["funds"]}
    assert rows["Tithes"]["given"] == 100.0 and rows["Tithes"]["designated"] is False
    assert rows["General"]["given"] == 25.0                          # no fund named: the general fund
    assert rows["Offering"]["given"] == 0.0                          # a configured fund with no gifts yet
    assert rows["Tithes"]["spent"] is None and rows["Tithes"]["left"] is None   # no year fund by that name


def test_a_year_fund_no_giving_fund_matches_is_listed_on_its_own(church):
    out = _funds()
    assert out["other_funds"] == [{"fund": "Housing", "spent": 900.0, "payments": 1}]
    assert out["total_given"] == 205.0 and out["total_spent"] == 930.0


def test_year_funds_switched_off_show_only_what_was_given(church, monkeypatch):
    monkeypatch.setattr(funds, "switched_on", lambda biz: False)
    out = _funds()
    assert out["year_funds_on"] is False and out["other_funds"] == []
    assert all(r["spent"] is None for r in out["funds"])


def test_gifts_by_fund_and_by_way(church):
    out = gr.by_fund_and_way(BIZ, date(2026, 1, 1), date(2026, 12, 31))
    assert {f["fund"]: f["amount"] for f in out["by_fund"]} == {"Tithes": 100.0, "Youth": 80.0, "General": 25.0}
    ways = {w["way"]: w["amount"] for w in out["by_way"]}
    assert ways["Online"] == 100.0 and ways["Cash"] == 50.0 and ways["Check"] == 30.0
    assert ways["Cash App"] == 25.0


def test_givers_and_one_persons_giving(church):
    people = gr.givers(BIZ, 2026)["givers"]
    assert [p["name"] for p in people] == ["Grace Holloway", "Marcus Reed"]
    assert people[0]["total"] == 130.0 and people[0]["gifts"] == 2
    h = gr.giver_history(BIZ, P1, 2026)
    assert h["name"] == "Grace Holloway" and h["total"] == 130.0
    assert [(g["fund"], g["way"], g["amount"]) for g in h["gifts"]] == [("Tithes", "Online", 100.0),
                                                                         ("youth fund", "Check", 30.0)]


def test_the_funds_csv(church):
    rows = reports_router._csv_rows("funds", _funds(), "church")
    assert rows[0] == ["Fund", "Designated", "Gifts", "Given", "Spent", "Left"]
    assert ["Youth", "yes", 2, 80.0, 30.0, 50.0] in rows
    assert rows[-1][:5] == ["TOTAL", "", "", 205.0, 930.0]


@pytest.fixture
def ledger(monkeypatch):
    lines = [
        {"account_type": "income", "account_code": "4000", "debit": 0, "credit": 500},
        {"account_type": "expense", "account_code": "5100", "debit": 200, "credit": 0},
    ]
    monkeypatch.setattr(gl_reports_t2, "_window_lines", lambda biz, s, e: lines)
    monkeypatch.setattr(gl_reports_t3, "_budgets_in_window", lambda biz, s, e: {})
    monkeypatch.setattr(expense_lines, "names", lambda biz: dict(expense_lines.STANDARD))


def test_a_churchs_budget_reads_its_lines_and_makes_up_nothing(ledger):
    row = {"type": "church", "settings": {"revenue_allocator": {"owner_pay": 50}}}
    out = gl_reports_t3.budget_vs_actual(BIZ, row, "custom", "2026-10-01", "2026-10-31")
    labels = {r["category"]: r for r in out["rows"]}
    assert labels["revenue"]["label"] == "Giving & income"
    assert labels["owner_pay"]["label"] == "Pastor & staff pay"
    assert labels["owner_pay"]["budget"] is None and labels["owner_pay"]["budget_source"] is None


def test_a_business_budget_is_as_before(ledger):
    row = {"type": "coach", "settings": {"revenue_allocator": {"owner_pay": 50}}}
    out = gl_reports_t3.budget_vs_actual(BIZ, row, "custom", "2026-10-01", "2026-10-31")
    labels = {r["category"]: r for r in out["rows"]}
    assert labels["revenue"]["label"] == "Revenue" and labels["owner_pay"]["label"] == "Owner Pay"
    assert labels["owner_pay"]["budget"] == 250.0 and labels["owner_pay"]["budget_source"] == "profit_first"


# ─── Gates and failed reads (review) ──────────────────────────────────

from fastapi import HTTPException

import billing_limits
import giving_records
import sb_clients


@pytest.fixture
def gates(monkeypatch):
    calls = []
    monkeypatch.setattr(giving_records, "require_finance", lambda biz, user: calls.append("finance"))
    monkeypatch.setattr(reports_router, "_owner_or_reader",
                        lambda biz, user: (calls.append("owner"), {"type": "church", "settings": {}})[1])
    monkeypatch.setattr(reports_router, "_giving_wall", lambda biz, user: calls.append("keeper"))
    monkeypatch.setattr(billing_limits, "require_feature", lambda biz, f: calls.append(f"plan:{f}"))
    return calls


@pytest.mark.parametrize("call", [
    lambda u: reports_router.funds_report(BIZ, "this_year", None, None, u),
    lambda u: reports_router.givers_list(BIZ, 2026, u),
    lambda u: reports_router.giver_history(BIZ, P1, 2026, u),
])
def test_the_new_routes_have_the_givers_gates_and_the_plan(church, gates, call):
    call(object())
    assert {"finance", "owner", "keeper", "plan:vertical_reports"} <= set(gates)


def test_the_funds_export_is_on_the_vertical_plan():
    assert reports_router._REPORT_FEATURES["funds"] == "vertical_reports"


def test_an_unreadable_funds_tab_is_a_503_not_no_spending(church, gates, monkeypatch):
    def boom(biz, ids):
        raise funds.Unavailable("business_fund_items")
    monkeypatch.setattr(funds, "items_for", boom)
    with pytest.raises(HTTPException) as e:
        reports_router.funds_report(BIZ, "this_year", None, None, object())
    assert e.value.status_code == 503


def test_an_unreadable_settings_row_is_a_503_not_the_default_funds(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **_: None)
    with pytest.raises(HTTPException) as e:
        gr._configured(BIZ)
    assert e.value.status_code == 503


def test_giving_and_income_stands_when_the_gifts_read_fails(monkeypatch):
    import gl_reports
    monkeypatch.setattr(reports_router, "_owner_or_reader", lambda biz, user: {"type": "church", "settings": {}})
    monkeypatch.setattr(billing_limits, "require_feature", lambda biz, f: None)
    monkeypatch.setattr(gl_reports, "gl_active", lambda biz: True)
    monkeypatch.setattr(gl_reports_t2, "revenue_report", lambda *a: {"ok": True, "total_revenue": 10, "by_account": []})
    monkeypatch.setattr(reports_router, "_givers_hidden", lambda biz, user, data: data)

    def fail(*a, **k):
        raise HTTPException(503, "Giving records could not be loaded. Please retry.")
    monkeypatch.setattr(gr, "by_fund_and_way", fail)
    out = reports_router.revenue(BIZ, "this_month", None, None, object())
    assert out["total_revenue"] == 10 and out["gift_tables_unavailable"] is True and "by_fund" not in out

