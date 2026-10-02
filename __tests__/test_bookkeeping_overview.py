"""The Bookkeeping room's front page tells the truth about the books.

The old room opened on a vault card that always said "on · tracking". The
overview replaces it with facts, and these tests hold the facts to their
word: a move between two of your own accounts is one transfer, not income
plus spending; a bank linked twice shows up as doubled rows, not as a
transfer; a month whose bank rows never reached the ledger is "behind";
and a broken source costs its own section, never the page — and opening
the page never writes.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bookkeeping_overview as bo

NOW = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)

PRIMARY = {"account_id": "a-pri", "name": "KMJ Creative Solutions LLC - Primary",
           "mask": "9020", "type": "depository", "included_in_bookkeeping": True}
TAXES = {"account_id": "a-tax", "name": "KMJ Creative Solutions LLC - Taxes",
         "mask": "2693", "type": "depository", "included_in_bookkeeping": True}
PRIMARY_AGAIN = dict(PRIMARY, account_id="a-pri-2")  # same bank, linked a second time
ACCTS = {a["account_id"]: a for a in (PRIMARY, TAXES, PRIMARY_AGAIN)}


def tx(tid, acct, amount, day, name="X", primary=None, detail=None, bucket=None,
       recon="unmatched", payout=None):
    # Plaid sign convention: positive = money out, negative = money in.
    return {"transaction_id": tid, "account_id": acct, "amount": amount, "date": day,
            "name": name, "merchant_name": name, "business_category": bucket,
            "plaid_category_primary": primary, "plaid_category_detail": detail,
            "reconciliation_status": recon, "reconciled_to_payout_id": payout}


# ─── Transfer pairs ──────────────────────────────────────────────────

def test_a_move_between_your_accounts_pairs_up():
    out = tx("t1", "a-tax", 10.70, "2026-08-25", "Taxes to Primary",
             "GOVERNMENT_AND_NON_PROFIT", "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT", "tax")
    inn = tx("t2", "a-pri", -10.70, "2026-08-25", "Taxes to Primary", "TRANSFER_IN")
    pairs = bo.find_transfer_pairs([out, inn], ACCTS)
    assert [(p["out"]["transaction_id"], p["in"]["transaction_id"]) for p in pairs] == [("t1", "t2")]


def test_same_account_and_far_apart_rows_are_not_transfers():
    rows = [tx("o", "a-pri", 20.0, "2026-06-02"), tx("i", "a-pri", -20.0, "2026-06-02"),
            tx("o2", "a-pri", 49.0, "2026-06-05"), tx("i2", "a-tax", -49.0, "2026-06-20")]
    assert bo.find_transfer_pairs(rows, ACCTS) == []


def test_a_bank_linked_twice_is_not_a_transfer():
    rows = [tx("o", "a-pri", 20.0, "2026-06-02"), tx("i", "a-pri-2", -20.0, "2026-06-02")]
    assert bo.find_transfer_pairs(rows, ACCTS) == []


def test_payout_deposits_are_explained_by_stripe_not_paired():
    rows = [tx("o", "a-tax", 41.45, "2026-08-11"),
            tx("i", "a-pri", -41.45, "2026-08-11", payout="po_1", recon="auto_matched")]
    assert bo.find_transfer_pairs(rows, ACCTS) == []


def test_each_row_pairs_once_and_closest_date_wins():
    rows = [tx("o", "a-tax", 25.0, "2026-05-21"),
            tx("far", "a-pri", -25.0, "2026-05-23"), tx("near", "a-pri", -25.0, "2026-05-21")]
    pairs = bo.find_transfer_pairs(rows, ACCTS)
    assert len(pairs) == 1 and pairs[0]["in"]["transaction_id"] == "near"


def test_transfer_notice_names_what_the_books_counted():
    out = tx("t1", "a-tax", 10.70, "2026-08-25", "Taxes to Primary",
             "GOVERNMENT_AND_NON_PROFIT", "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT", "tax")
    inn = tx("t2", "a-pri", -10.70, "2026-08-25", "Taxes to Primary", "TRANSFER_IN")
    n = bo.transfer_notice(bo.find_transfer_pairs([out, inn], ACCTS), ACCTS)
    assert n["title"] == "Moves between your own accounts are counted as income and spending"
    assert "left Taxes ••2693 and landed in Primary ••9020" in n["body"]
    assert n["income"] == 10.70 and n["spending"] == 10.70


def test_pairs_the_books_already_treat_as_neutral_raise_nothing():
    # Transfer out (income-ish category → owner's draw) + uncategorized deposit
    # (→ owner's equity): neither moves the P&L, so there is nothing to say.
    out = tx("t1", "a-tax", 10.0, "2026-08-25", "x", "TRANSFER_OUT", "TRANSFER_OUT_ACCOUNT_TRANSFER")
    out["plaid_category_primary"] = "INCOME"  # is_income_category → not spending
    inn = tx("t2", "a-pri", -10.0, "2026-08-25", "x", "OTHER", "OTHER_OTHER")
    assert bo.transfer_notice(bo.find_transfer_pairs([out, inn], ACCTS), ACCTS) is None


# ─── Duplicates ──────────────────────────────────────────────────────

def test_rows_from_a_bank_linked_twice_are_certain_duplicates():
    rows = [tx("r1", "a-pri", 5.0, "2026-06-01", "Railway"),
            tx("r2", "a-pri-2", 5.0, "2026-06-01", "Railway")]
    [g] = bo.find_duplicates(rows, ACCTS)
    assert g["count"] == 2 and g["linked_twice"] is True


def test_a_repeat_charge_on_one_account_only_looks_doubled():
    rows = [tx("r1", "a-pri", 49.0, "2026-06-05", "Tradesyncer"),
            tx("r2", "a-pri", 49.0, "2026-06-05", "Tradesyncer"),
            tx("r3", "a-pri", 20.0, "2026-06-02", "Resend")]
    [g] = bo.find_duplicates(rows, ACCTS)
    assert g["name"] == "Tradesyncer" and g["linked_twice"] is False


def test_linked_twice_counts_the_extra_copies():
    assert bo.accounts_linked_twice([PRIMARY, TAXES, PRIMARY_AGAIN]) == 1
    assert bo.accounts_linked_twice([PRIMARY, TAXES]) == 0


def test_duplicate_notice_reads_like_a_person():
    dups = [{"date": "2026-06-05", "name": "Tradesyncer", "amount": 49.0, "count": 2,
             "linked_twice": False, "transaction_ids": ["a", "b"]},
            {"date": "2026-06-01", "name": "Railway", "amount": 5.0, "count": 2,
             "linked_twice": True, "transaction_ids": ["c", "d"]}]
    n = bo.duplicate_notice(dups, linked_twice=1, accounts_total=17)
    assert n["body"].startswith("Tradesyncer on Jun 5 and Railway on Jun 1 each appear twice.")
    assert "17 accounts are linked, and 1 looks like the same bank account" in n["body"]


# ─── Months ──────────────────────────────────────────────────────────

def test_month_statuses():
    txs = [tx("a", "a-pri", 5.0, "2026-04-03"), tx("b", "a-pri", 5.0, "2026-07-02"),
           tx("c", "a-pri", 5.0, "2026-05-09")]
    months = bo.month_rows(date(2026, 1, 1), date(2026, 10, 1), txs,
                           posted_by_month={"2026-04": 1, "2026-05": 1},
                           unposted_by_month={"2026-07": 1}, closed_months={"2026-05"})
    by = {m["month"]: m["status"] for m in months}
    assert by["2026-01"] == "quiet"
    assert by["2026-04"] == "open"
    assert by["2026-05"] == "closed"
    assert by["2026-07"] == "behind"
    assert by["2026-10"] == "current"
    assert by["2026-11"] == "future"


def test_fiscal_year_start():
    assert bo.fiscal_year_start(date(2026, 10, 1), 1) == date(2026, 1, 1)
    assert bo.fiscal_year_start(date(2026, 3, 1), 7) == date(2025, 7, 1)


# ─── Headline ────────────────────────────────────────────────────────

def _path(done=98, total=164, matched=1, deposits=66):
    return {"categorize": {"done": done, "total": total},
            "match": {"matched": matched, "total": deposits}}


def test_headline_counts_months_behind_in_words():
    months = [{"status": "behind"}] * 3 + [{"status": "open"}]
    h = bo.compose_headline({"linked": True}, _path(), months,
                            {"active": True, "last_entry_date": "2026-06-13"})
    assert (h["lead"], h["emphasis"]) == ("Your books are", "three months behind.")
    assert h["detail"] == ("The ledger last posted on June 13. 66 transactions still need a "
                           "category, and 65 deposits aren’t matched to where they came from.")


def test_headline_without_a_bank_asks_for_one():
    h = bo.compose_headline({"linked": False}, _path(), [], {})
    assert h["emphasis"] == "when your bank is connected."


def test_headline_when_everything_is_done():
    h = bo.compose_headline({"linked": True}, _path(done=10, total=10, matched=3, deposits=3),
                            [{"status": "open"}], {"active": True})
    assert h["emphasis"] == "current."


# ─── The whole read ──────────────────────────────────────────────────

def _fake_reads(fail=()):
    tables = {
        "/plaid_items": [{"item_id": "i1", "institution_name": "Huntington",
                          "last_sync_at": "2026-09-16T12:09:39+00:00"}],
        "/plaid_accounts": [PRIMARY, TAXES, PRIMARY_AGAIN],
        "/journal_entries": [{"entry_date": "2026-06-13", "source_type": "plaid_transaction",
                              "source_id": "jun", "created_at": "2026-06-13T09:55:00+00:00"}],
        "/gl_sync_queue": [],
        "/gl_divergence_alarms": [{"detected_at": "2026-06-14T00:00:00+00:00"}],
        "/bills": [{"id": "b1", "vendor_name": "Acme Test", "amount": 50, "due_date": "2026-06-10",
                    "status": "overdue"}],
        "/accounting_periods": [],
        "/plaid_transactions": [
            tx("jun", "a-pri", 20.0, "2026-06-02", "Anthropic", bucket="operating"),
            tx("t1", "a-tax", 10.70, "2026-08-25", "Taxes to Primary",
               "GOVERNMENT_AND_NON_PROFIT", "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT", "tax"),
            tx("t2", "a-pri", -10.70, "2026-08-25", "Taxes to Primary", "TRANSFER_IN"),
            tx("w", "a-pri", 314.0, "2026-09-15", "Walmart"),
        ],
    }

    def get(path):
        table = path.split("?")[0]
        if table in fail:
            return None
        rows = tables.get(table, [])
        q = dict(part.split("=", 1) for part in path.split("?", 1)[-1].split("&") if "=" in part)
        if "offset" in q:  # honour paging the way PostgREST does
            off, lim = int(q["offset"]), int(q.get("limit", 1000))
            return rows[off:off + lim]
        return rows
    return get


@pytest.fixture
def reads(monkeypatch):
    def install(fail=()):
        monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", _fake_reads(fail))

        def no_writes(*a, **k):
            raise AssertionError("opening the overview must not write")
        for name in ("sb_post_as_service", "sb_patch_as_service", "sb_delete_as_service"):
            if hasattr(bo.sb_clients, name):
                monkeypatch.setattr(bo.sb_clients, name, no_writes)
        monkeypatch.setattr(bo, "year_so_far", lambda biz, row: {
            "money_in": 3089.10, "money_out": 3234.44, "net": -145.34, "buckets": []})
    return install


def test_overview_reads_the_books(reads):
    reads()
    o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=NOW)
    assert o["sources_failed"] == []
    assert o["bank"]["accounts_linked_twice"] == 1
    assert o["bank"]["sync_stale"] is True
    assert o["ledger"]["state"] == "behind"
    assert o["ledger"]["unposted"] == 3 and o["ledger"]["oldest_unposted_date"] == "2026-08-25"
    assert o["ledger"]["posted_through"] == "2026-08-24"
    months = {m["month"]: m["status"] for m in o["months"]}
    assert months["2026-06"] == "open" and months["2026-08"] == "behind"
    assert o["counts"]["to_review"] == 2          # the uncategorized deposit + Walmart
    assert o["counts"]["bills_overdue"] == 1
    assert o["bills"]["overdue"][0]["days_late"] == 113
    kinds = [n["kind"] for n in o["noticed"]]
    assert kinds[0] == "ledger"                   # bad news first
    assert "transfer_pairs" in kinds and "bank_sync" in kinds
    assert o["headline"]["emphasis"] == "two months behind."
    walmart = next(r for r in o["recent"] if r["name"] == "Walmart")
    assert walmart["needs_category"] is True and walmart["account"] == "Primary ••9020"


def test_a_broken_source_costs_its_section_not_the_page(reads):
    reads(fail=("/bills",))
    o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=NOW)
    assert o["sources_failed"] == ["bills"]
    assert o["bills"] is None
    assert o["ledger"]["state"] == "behind"       # everything else still renders


def test_a_failed_journal_read_is_unknown_not_empty(reads):
    reads(fail=("/journal_entries",))
    o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=NOW)
    assert o["ledger"] == {"active": False, "state": "unknown"}
    assert "ledger" in o["sources_failed"]
    assert not any(n["kind"] == "ledger" for n in o["noticed"])


def test_failed_bank_rows_withhold_every_claim_about_them(reads):
    for failing, name in (("/plaid_transactions", "transactions"), ("/plaid_accounts", "bank")):
        reads(fail=(failing,))
        o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=NOW)
        assert name in o["sources_failed"]
        assert o["headline"] == bo.UNREAD_HEADLINE        # never "current"
        assert o["ledger"]["state"] == "unknown"
        assert o["path"] is None and o["months"] == [] and o["counts"] is None
        assert not any(n["kind"] in ("ledger", "transfer_pairs", "duplicates") for n in o["noticed"])
        assert o["bills"]["overdue_count"] == 1           # bills don't depend on bank rows


def test_a_failed_alarm_read_is_not_no_divergence(reads):
    reads(fail=("/gl_divergence_alarms",))
    o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=NOW)
    assert "ledger" in o["sources_failed"]
    assert o["ledger"]["state"] == "unknown"
    assert o["headline"]["emphasis"] != "current."


def test_paging_survives_a_server_that_caps_pages(monkeypatch):
    rows = [{"n": i} for i in range(7)]

    def capped(path):  # the server returns at most 3 rows whatever we ask for
        off = int(path.split("offset=")[1].split("&")[0])
        return rows[off:off + 3]
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", capped)
    assert bo._get_all("/t?select=n&order=n.asc") == rows


def test_paging_past_the_cap_fails_instead_of_returning_part(monkeypatch):
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", lambda path: [{"n": 1}] * 1000)
    with pytest.raises(bo.SourceFailed):
        bo._get_all("/t?select=n", cap=2500)


def test_year_so_far_runs_through_the_reports_helpers(monkeypatch):
    import gl_reports
    import reports_engine
    seen = {}

    def pl(biz, period, comparison, from_, to):
        seen.update(period=period, from_=from_, to=to)
        return {"range": {"from": from_, "to": to}, "current": {
            "revenue": {"gross_revenue": 100.0},
            "expenses": {"total": 40.0, "by_bucket": [
                {"bucket": "operating", "label": "Operating", "total": 40.0, "pct": 100.0}]},
            "net_income": 60.0}}
    monkeypatch.setattr(gl_reports, "gl_active", lambda biz: False)
    monkeypatch.setattr(reports_engine, "profit_and_loss", pl)
    y = bo.year_so_far("biz", {"id": "biz", "settings": {"financial": {"fiscal_year_start_month": 7}}})
    assert y["source"] == "source_tables" and y["basis"] == "cash"
    assert (y["money_in"], y["money_out"], y["net"]) == (100.0, 40.0, 60.0)
    assert seen["period"] == "custom" and seen["from_"].endswith("-07-01")   # the fiscal year, not January


def test_an_unreadable_business_row_refuses_rather_than_guesses(monkeypatch):
    import plaid_router
    from fastapi import HTTPException
    monkeypatch.setattr(plaid_router, "_require_reader", lambda biz, user: {"id": biz})
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", lambda path: None)
    with pytest.raises(HTTPException) as e:
        bo.overview("biz", user=object())
    assert e.value.status_code == 503


def test_a_copy_already_switched_off_is_not_counted_as_linked_twice(monkeypatch):
    """Right after an old copy comes out, the notice must not keep saying
    "Fix in Settings": only accounts in the books can double their rows."""
    off = dict(PRIMARY_AGAIN, included_in_bookkeeping=False)
    tables = {"/plaid_items": [], "/plaid_accounts": [PRIMARY, TAXES, off]}

    def get(path):
        return tables.get(path.split("?")[0], [])
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(bo, "year_so_far", lambda biz, row: None)
    o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=NOW)
    assert o["bank"]["accounts_linked_twice"] == 0
