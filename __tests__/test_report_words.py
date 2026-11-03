"""Report words in the business's voice on the server (2026-11-03): a church
reads church words in account names, journal labels and the CSV/PDF rows;
a business reads exactly what it read before."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import expense_lines
import gl_reports
import report_words as rw
import reports_router
import sb_clients

BIZ = "00000000-0000-4000-8000-0000000000c1"


@pytest.mark.parametrize("kind,voice", [
    ("church", "church"), ("ministry", "church"), ("nonprofit", "nonprofit"),
    ("coach", "business"), ("consultant", "business"), (None, "business"),
])
def test_voice_of(kind, voice):
    assert rw.voice_of(kind) == voice


@pytest.fixture
def standard_lines(monkeypatch):
    # Chief's categories off: the standard five names, as expense_lines answers.
    monkeypatch.setattr(expense_lines, "names", lambda biz: dict(expense_lines.STANDARD))


def test_a_business_keeps_its_chart_names(standard_lines):
    assert rw.account_names(BIZ, "business") == {}


def test_a_church_reads_contributions_and_its_own_lines(standard_lines):
    names = rw.account_names(BIZ, "church")
    assert names["4000"] == "Contributions"
    assert names["3100"] == "Unsorted deposits (net assets)"
    assert names["5100"] == "Pastor & staff pay"          # not "Owner pay"
    assert names["5000"] == "Ministry & operations"


def test_a_line_the_church_renamed_keeps_its_name(monkeypatch):
    monkeypatch.setattr(expense_lines, "names",
                        lambda biz: {**expense_lines.STANDARD, "operating": "Missions & outreach"})
    assert rw.account_names(BIZ, "church")["5000"] == "Missions & outreach"


def test_a_nonprofit_has_no_owner_either(standard_lines):
    assert rw.account_names(BIZ, "nonprofit")["5100"] == "Staff pay"


def test_the_trial_balance_names_come_through(monkeypatch, standard_lines):
    coa = [{"code": "4000", "name": "Service Revenue", "type": "income", "normal_balance": "credit"},
           {"code": "1000", "name": "Cash - Operating", "type": "asset", "normal_balance": "debit"}]

    def get(path, **_):
        if path.startswith("/chart_of_accounts"):
            return coa
        if path.startswith("/businesses"):
            return [{"type": "church"}]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    meta = gl_reports._account_meta(BIZ)
    assert meta["4000"]["name"] == "Contributions" and meta["4000"]["type"] == "income"
    assert meta["1000"]["name"] == "Cash - Operating"     # not renamed: the chart's own name


@pytest.mark.parametrize("desc,st,gift,church", [
    ("Invoice issued", "invoice_issue", True, "Gift recorded"),
    ("Invoice paid", "invoice_payment", True, "Gift received"),
    ("Invoice paid", "invoice_payment", False, "Charge paid"),
    ("Bank expense", "plaid_transaction", None, "Paid from the bank"),
    ("Transfer in / uncategorized deposit", "plaid_transaction", None, "Deposit not sorted yet"),
    ("Deposit of recorded gifts", "plaid_transaction", None, "Deposit of recorded gifts"),
])
def test_journal_labels(desc, st, gift, church):
    assert rw.journal_label(desc, st, "church", gift) == church
    assert rw.journal_label(desc, st, "business", gift) == desc          # unchanged for a business


PL = {"current": {"revenue": {"invoiced": 100, "refunds": 0, "plaid_other_income": 5, "gross_revenue": 105},
                  "expenses": {"total": 40, "by_bucket": []}, "net_income": 65}}


def test_csv_rows_in_each_voice():
    biz_rows = [r[1] for r in reports_router._csv_rows("pl", PL, "business")]
    church_rows = [r[1] for r in reports_router._csv_rows("pl", PL, "church")]
    assert "Gross Revenue" in biz_rows and "Net Income" in biz_rows
    assert "Total income" in church_rows and "Surplus (or shortfall)" in church_rows
    assert "Gross Revenue" not in church_rows
    assert [r[1] for r in reports_router._csv_rows("pl", PL)] == biz_rows   # no voice: as before


def test_titles():
    assert rw.title("pl", "Profit & Loss", "business") == "Profit & Loss"
    assert rw.title("pl", "Profit & Loss", "church").startswith("Income & Spending")
    assert "the Church" in rw.title("balance_sheet", "Balance Sheet", "church")
    assert rw.title("general_ledger", "General Ledger", "church") == "General Ledger"
