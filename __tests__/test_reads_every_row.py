"""Reads that can pass PostgREST's 1,000-row cap page through every row.

2026-11-03: Love City's trial balance read 1,000 of its 6,802 ledger lines
and called balanced books "Out of balance". The stand-in below behaves like
PostgREST on this project: whatever `limit` asks for, at most 1,000 rows
come back, in table order unless `order=` is given.
"""
from __future__ import annotations

import pathlib
import sys
from urllib.parse import unquote

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import gl_engine
import gl_reports
import sb_clients

CAP = 1000
BIZ = "biz-big"


class CappedDB:
    """A PostgREST stand-in with the 1,000-row cap and keyset filters."""

    def __init__(self, tables):
        self.t = tables
        self.calls = []
        self.fail_on_call = None

    def get(self, path, **_):
        self.calls.append(path)
        if self.fail_on_call == len(self.calls):
            return None
        table, _, query = path.lstrip("/").partition("?")
        rows = list(self.t.get(table, []))
        order, limit = None, None
        for part in query.split("&"):
            k, _, v = part.partition("=")
            if k == "order":
                order = v.split(".")[0]
            elif k == "limit":
                limit = int(v)
            elif v.startswith("eq."):
                rows = [r for r in rows if str(r.get(k)) == v[3:]]
            elif v.startswith("gt."):
                rows = [r for r in rows if str(r.get(k)) > unquote(v[3:])]
        if order:
            rows.sort(key=lambda r: str(r.get(order)))
        return rows[:min(limit or CAP, CAP)]


def _books(entries: int):
    """`entries` balanced entries (cash 10 / contributions 10), stored the
    way a heap can hand them back: every debit line before every credit."""
    jes, debits, credits = [], [], []
    for i in range(entries):
        je = f"je{i:05d}"
        jes.append({"id": je, "business_id": BIZ, "status": "active", "is_reversal": False,
                    "source_type": "invoice_paid", "source_id": f"inv{i}"})
        common = {"business_id": BIZ, "journal_entry_id": je, "entry_date": "2026-10-01",
                  "account_type": None, "profit_first_bucket": None, "source_type": "invoice_paid",
                  "subcategory": None, "vendor": None, "memo": ""}
        debits.append({**common, "id": f"l{i:05d}a", "account_code": "1000", "debit": 10, "credit": 0})
        credits.append({**common, "id": f"l{i:05d}b", "account_code": "4000", "debit": 0, "credit": 10})
    coa = [{"business_id": BIZ, "code": "1000", "name": "Operating Cash", "type": "asset", "normal_balance": "debit"},
           {"business_id": BIZ, "code": "4000", "name": "Service Revenue", "type": "income", "normal_balance": "credit"}]
    return {"journal_entries": jes, "ledger_entries": debits + credits, "chart_of_accounts": coa}


@pytest.fixture
def db(monkeypatch):
    fake = CappedDB(_books(1600))                    # 1,600 entries, 3,200 lines: past the cap
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    return fake


def test_the_stand_in_caps_like_postgrest(db):
    # The bug itself: one read asking for 100,000 lines gets 1,000, all debits.
    got = sb_clients.sb_get_as_service(f"/ledger_entries?business_id=eq.{BIZ}&limit=100000")
    assert len(got) == CAP and {r["account_code"] for r in got} == {"1000"}


def test_every_row_comes_back_once(db):
    rows = sb_clients.sb_get_all_as_service(f"/ledger_entries?business_id=eq.{BIZ}&select=id,debit")
    assert len(rows) == 3200 and len({r["id"] for r in rows}) == 3200
    assert len(db.calls) == 4                        # 1,000 + 1,000 + 1,000 + 200
    assert all("order=id.asc" in c and "limit=1000" in c for c in db.calls)
    assert "=gt." not in db.calls[0]                 # the first page has no cursor
    assert db.calls[1].endswith("&id=gt.l00499b")     # the next starts after the last id seen


def test_trial_balance_sees_every_line_and_balances(db):
    tb = gl_reports.trial_balance_report(BIZ, "2026-12-31")
    by_code = {a["code"]: a for a in tb["accounts"]}
    assert set(by_code) == {"1000", "4000"}
    assert by_code["1000"]["debits"] == 16000 and by_code["4000"]["credits"] == 16000
    assert tb["totals"]["balanced"] is True and tb["totals"]["difference"] == 0


def test_the_ledger_read_is_whole(db):
    assert len(gl_engine.read_ledger(BIZ)) == 3200
    assert len(gl_reports.effective_lines(BIZ)) == 3200


def test_a_failed_first_page_is_none_like_a_single_read(db):
    db.fail_on_call = 1
    assert sb_clients.sb_get_all_as_service(f"/ledger_entries?business_id=eq.{BIZ}&select=id") is None


def test_a_failed_later_page_raises_instead_of_a_short_list(db):
    db.fail_on_call = 2
    with pytest.raises(sb_clients.PartialRead):
        sb_clients.sb_get_all_as_service(f"/ledger_entries?business_id=eq.{BIZ}&select=id")


def test_a_select_without_the_key_is_caught(monkeypatch):
    fake = CappedDB({"things": [{"n": i} for i in range(1500)]})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    with pytest.raises(ValueError):
        sb_clients.sb_get_all_as_service("/things?select=n")


def test_backfill_never_reads_a_failed_list_as_nothing_posted(db):
    # An empty "already posted" set would post every source a second time.
    db.fail_on_call = 1
    with pytest.raises(RuntimeError):
        gl_engine._existing_entry_keys(BIZ)


def test_backfill_sees_entries_past_the_cap(db):
    keys = gl_engine._existing_entry_keys(BIZ)
    assert len(keys) == 1600 and ("invoice_paid", "inv1599") in keys
