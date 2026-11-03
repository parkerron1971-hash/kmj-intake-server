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


class JournalDB:
    """A church's journal page: two invoice entries (a gift, a charge) and a bank row."""

    def __init__(self, invoices_fail=False):
        self.invoices_fail = invoices_fail
        self.paths = []

    def get(self, path, **_):
        self.paths.append(path)
        if path.startswith("/businesses"):
            return [{"type": "church"}]
        if path.startswith("/journal_entries"):
            return [
                {"id": "j1", "entry_date": "2026-11-01", "description": "Invoice paid",
                 "source_type": "invoice_payment", "source_id": "inv-gift", "status": "active", "is_reversal": False},
                {"id": "j2", "entry_date": "2026-11-01", "description": "Invoice issued",
                 "source_type": "invoice_issue", "source_id": "inv-rent", "status": "active", "is_reversal": False},
                {"id": "j3", "entry_date": "2026-11-02", "description": "Bank expense",
                 "source_type": "plaid_transaction", "source_id": "tx1", "status": "active", "is_reversal": False},
            ]
        if path.startswith("/invoices"):
            return None if self.invoices_fail else [{"id": "inv-gift", "is_gift": True}, {"id": "inv-rent", "is_gift": False}]
        return []


def test_a_churchs_journal_reads_gift_and_charge(monkeypatch):
    db = JournalDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    out = gl_reports.journal_report(BIZ)
    assert [e["description"] for e in out["entries"]] == ["Gift received", "Charge recorded", "Paid from the bank"]
    assert any("source_id" in p for p in db.paths if p.startswith("/journal_entries"))
    inv = [p for p in db.paths if p.startswith("/invoices")]
    assert len(inv) == 1 and "inv-gift" in inv[0] and "inv-rent" in inv[0]


def test_a_failed_gift_lookup_reads_neutral_never_invoice(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", JournalDB(invoices_fail=True).get)
    out = gl_reports.journal_report(BIZ)
    assert [e["description"] for e in out["entries"]][:2] == ["Payment received", "Recorded"]


def test_a_failed_type_read_is_a_business(monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **_: None)
    assert rw.voice_for(BIZ) == "business"


def test_the_pdf_reads_the_voice_from_meta(monkeypatch):
    import pdf_reports
    seen = []
    real = rw.rows
    monkeypatch.setattr(rw, "rows", lambda v: (seen.append(v), real(v))[1])
    meta = pdf_reports.build_meta(business_name="Sample", settings={}, report_title="t", period_label="p")
    meta["voice"] = "church"
    pdf_reports.render("pl", PL, meta)
    assert seen == ["church"]

