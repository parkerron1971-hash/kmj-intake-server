"""Close the month is one checklist, and it never says a check is done
when it isn't.

Month-end work was spread over the Reconciliation tab, Admin → Periods and
the Bank Reconciliation report, and none of them said what was left. These
tests hold the checklist to its word. The bank must have synced after the
month ended. Every deposit is explained. Every other row has a category.
The statement balance agrees with what the books expect. The month was
looked over. Closing with checks still open takes an explicit "close
anyway", and opening the page never writes.
"""
from __future__ import annotations

import math
import pathlib
import sys
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bookkeeping_close as bc  # noqa: E402
import bookkeeping_overview as bo  # noqa: E402

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
AUG = date(2026, 8, 1)

PRIMARY = {"account_id": "a-pri", "item_id": "it", "name": "KMJ LLC - Primary", "mask": "9020",
           "type": "depository", "included_in_bookkeeping": True, "last_balance": 500.0}
TAXES = {"account_id": "a-tax", "item_id": "it", "name": "KMJ LLC - Taxes", "mask": "2693",
         "type": "depository", "included_in_bookkeeping": True, "last_balance": 100.0}
ACCTS = {a["account_id"]: a for a in (PRIMARY, TAXES)}
ITEM = {"item_id": "it", "institution_name": "Found", "status": "active",
        "last_sync_at": "2026-09-16T12:00:00+00:00", "last_error": None}


def tx(tid, acct, amount, day, name="X", bucket=None, recon="unmatched", primary=None, **kw):
    # Plaid sign: positive = money out, negative = money in.
    return {"transaction_id": tid, "account_id": acct, "amount": amount, "date": day,
            "name": name, "merchant_name": name, "business_category": bucket,
            "plaid_category_primary": primary, "plaid_category_detail": None,
            "reconciliation_status": recon, "reconciled_to_payout_id": None,
            "excluded_from_books": False, **kw}


# ─── The balance the books expect ────────────────────────────────────

def test_expected_ending_walks_todays_balance_back_to_the_last_day():
    after = [tx("d", "a-pri", -100.0, "2026-09-03"), tx("w", "a-pri", 40.0, "2026-09-10")]
    # 500 today; +100 came in and 40 went out since, so 440 on Aug 31.
    assert bc.expected_ending(PRIMARY, after) == 440.0


def test_on_a_card_a_purchase_adds_to_what_is_owed():
    card = {"type": "credit", "last_balance": 300.0}
    after = [tx("p", "c", 50.0, "2026-09-03"), tx("pay", "c", -200.0, "2026-09-05")]
    assert bc.expected_ending(card, after) == 450.0


def test_no_balance_from_the_bank_is_no_figure_not_zero():
    assert bc.expected_ending({"type": "depository", "last_balance": None}, []) is None


# ─── 1 · Synced past the month's end ─────────────────────────────────

def _sync(items, rows=(), posted=None, active=False, m_start=AUG):
    return bc.sync_step(m_start, bc.month_end(m_start), TODAY, items, [PRIMARY, TAXES],
                        list(rows), posted, active)


def test_a_sync_after_the_month_ended_is_done():
    s = _sync([ITEM])
    assert s["done"] and "Both accounts are covered" in s["detail"]


def test_a_sync_before_the_month_ended_is_not():
    s = _sync([dict(ITEM, last_sync_at="2026-08-20T09:00:00+00:00")])
    assert not s["done"] and s["action"] == "sync" and "before August ended" in s["detail"]


def test_a_month_that_is_not_over_cannot_be_synced_past():
    s = _sync([ITEM], m_start=date(2026, 10, 1))
    assert not s["done"] and "isn’t over yet" in s["detail"]


def test_rows_the_ledger_has_not_posted_hold_the_check_open():
    rows = [tx("r1", "a-pri", 5.0, "2026-08-04"), tx("r2", "a-pri", 6.0, "2026-08-05")]
    s = _sync([ITEM], rows, posted={"r1"}, active=True)
    assert not s["done"] and s["unposted"] == 1 and s["action"] == "ledger"


def test_an_unread_ledger_is_not_a_posted_ledger():
    s = _sync([ITEM], [tx("r1", "a-pri", 5.0, "2026-08-04")], posted=None, active=True)
    assert not s["done"]


# ─── 2 · Money in ────────────────────────────────────────────────────

def test_money_in_sorts_deposits_into_what_they_need():
    rows = [
        tx("out", "a-pri", 10.70, "2026-08-11", "Primary to Taxes", bucket="tax"),
        tx("in", "a-tax", -10.70, "2026-08-11", "Primary to Taxes"),
        tx("st", "a-pri", -41.45, "2026-08-11", "STRIPE TRANSFER"),
        tx("chime", "a-pri", -25.0, "2026-08-14", "Chime"),
        tx("paid", "a-pri", -90.0, "2026-08-20", "STRIPE TRANSFER", recon="auto_matched"),
        tx("told", "a-pri", -12.0, "2026-08-21", "Venmo", money_kind="owner"),
    ]
    s = bc.money_in_step(AUG, rows, rows, ACCTS, has_stripe=True)
    assert not s["done"]
    assert [(t["out_id"], t["in_id"]) for t in s["transfers"]] == [("out", "in")]
    assert [t["transaction_id"] for t in s["stripe"]] == ["st"]
    assert [t["transaction_id"] for t in s["other"]] == ["chime"]
    assert s["detail"].startswith("Five deposits in August. One is a move between your own accounts")


def test_money_in_is_done_when_every_deposit_is_explained():
    rows = [tx("paid", "a-pri", -90.0, "2026-08-20", "STRIPE", recon="auto_matched"),
            tx("cat", "a-pri", -15.0, "2026-08-22", "Interest", bucket="operating")]
    s = bc.money_in_step(AUG, rows, rows, ACCTS, has_stripe=True)
    assert s["done"] and s["detail"] == "Both August deposits are explained."


def test_a_transfer_that_straddles_the_month_still_pairs():
    rows = [tx("out", "a-pri", 30.0, "2026-08-31"), tx("in", "a-tax", -30.0, "2026-09-02")]
    s = bc.money_in_step(AUG, rows[:1], rows, ACCTS, has_stripe=True)
    assert len(s["transfers"]) == 1


# ─── 3 · Categories ──────────────────────────────────────────────────

def test_categorize_is_the_review_queue_less_the_transfer_legs():
    rows = [tx("a", "a-pri", 20.0, "2026-08-02", "Chime"),
            tx("b", "a-pri", 9.0, "2026-08-03", "Railway", bucket="operating"),
            tx("st", "a-pri", -41.45, "2026-08-11", "STRIPE TRANSFER"),
            tx("leg", "a-pri", 10.70, "2026-08-11")]
    s = bc.categorize_step(AUG, rows, {"leg"}, ACCTS)
    assert s["count"] == 2 and not s["done"]
    assert s["detail"].startswith("Once the transfers are confirmed, two rows remain: Chime and a Stripe transfer.")


def test_with_no_transfers_it_just_counts():
    s = bc.categorize_step(AUG, [tx("a", "a-pri", 20.0, "2026-08-02", "Chime")], set(), ACCTS)
    assert s["detail"].startswith("One row still needs a category: Chime.")


# ─── 4 · Statement ───────────────────────────────────────────────────

def _statement(checklist, supported=True, rows=()):
    return bc.statement_step(AUG, bc.month_end(AUG), [PRIMARY], list(rows), checklist, supported)


def test_statement_is_not_done_before_the_checklist_exists():
    s = _statement({"statements": {"a-pri": {"balance": 500.0}}}, supported=False)
    assert not s["done"] and s["supported"] is False


def test_a_statement_that_agrees_is_done():
    s = _statement({"statements": {"a-pri": {"balance": 440.0}}},
                   rows=[tx("d", "a-pri", -100.0, "2026-09-03"), tx("w", "a-pri", 40.0, "2026-09-10")])
    assert s["done"] and s["accounts"][0]["agrees"] is True


def test_a_statement_that_disagrees_names_the_difference():
    s = _statement({"statements": {"a-pri": {"balance": 480.0}}})
    assert not s["done"] and s["accounts"][0]["difference"] == -20.0
    assert "off by $20.00" in s["detail"]


def test_rows_inside_the_month_do_not_move_its_ending_balance():
    s = _statement({"statements": {"a-pri": {"balance": 500.0}}},
                   rows=[tx("aug", "a-pri", 60.0, "2026-08-31")])
    assert s["accounts"][0]["expected"] == 500.0 and s["done"]


# ─── States ──────────────────────────────────────────────────────────

def test_the_first_open_check_is_now_the_second_next_the_rest_later():
    steps = bc.with_states([{"key": k, "done": d} for k, d in
                            [("a", True), ("b", False), ("c", False), ("d", False), ("e", True)]])
    assert [s["state"] for s in steps] == ["done", "now", "next", "later", "done"]


# ─── The whole page, from a fake database ────────────────────────────

class FakeDB:
    def __init__(self, tables):
        self.tables = tables
        self.writes = []

    def get(self, path):
        rows = self.tables.get(path.split("?")[0], [])
        if "offset=" in path:
            off = int(path.split("offset=")[1].split("&")[0])
            return rows[off:off + 1000]
        return rows

    def patch(self, path, body):
        self.writes.append(("patch", path, body))
        return [body]

    def post(self, path, body, prefer=None):
        self.writes.append(("post", path, body))
        return []


@pytest.fixture
def db(monkeypatch):
    periods = [{"id": "p-aug", "period_start": "2026-08-01", "period_end": "2026-08-31",
                "status": "open", "close_checklist": {}}]
    rows = [tx("j1", "a-pri", 9.0, "2026-07-03", "Railway", bucket="operating"),
            tx("a1", "a-pri", 20.0, "2026-08-02", "Chime"),
            tx("a2", "a-pri", -50.0, "2026-08-10", "STRIPE", recon="auto_matched"),
            tx("s1", "a-pri", 12.0, "2026-09-04", "Resend", bucket="operating")]
    fake = FakeDB({"/plaid_items": [ITEM], "/plaid_accounts": [PRIMARY, TAXES],
                   "/accounting_periods": periods, "/journal_entries": [],
                   "/plaid_transactions": rows, "/bills": []})
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(bo.sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(bo.sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(bc, "month_summary", lambda biz, row, m: {"money_in": 0, "money_out": 0})
    return fake


BIZ = {"id": "biz", "settings": {}, "stripe_account_id": "acct_1"}


def test_the_page_opens_on_the_oldest_month_still_open_and_never_writes(db):
    out = bc.build_close("biz", BIZ, now=NOW)
    assert out["month"] == "2026-07"
    assert db.writes == []
    aug = next(m for m in out["months"] if m["month"] == "2026-08")
    assert aug["status"] == "open" and aug["total"] == 6 and isinstance(aug["done"], int)
    assert [s["key"] for s in out["steps"]] == list(bc.STEP_KEYS)


def test_a_month_can_be_asked_for(db):
    out = bc.build_close("biz", BIZ, month="2026-08", now=NOW)
    cat = next(s for s in out["steps"] if s["key"] == "categorize")
    # Chime, and the matched Stripe deposit the To review queue still lists.
    assert out["label"] == "August 2026" and cat["count"] == 2
    assert out["glance"]["bank_rows"] == 2


def test_a_future_month_is_refused(db):
    with pytest.raises(HTTPException) as e:
        bc.build_close("biz", BIZ, month="2026-12", now=NOW)
    assert e.value.status_code == 400


def _as_manager(monkeypatch):
    import accounting_periods_router
    monkeypatch.setattr(accounting_periods_router, "_access", lambda biz, user, role="viewer": BIZ)


class U:
    id = "user-1"


def test_closing_with_checks_open_takes_an_explicit_close_anyway(db, monkeypatch):
    _as_manager(monkeypatch)
    import accounting_periods_router
    calls = []
    monkeypatch.setattr(accounting_periods_router, "close",
                        lambda pid, user: calls.append(pid) or {"ok": True, "closed": True})
    with pytest.raises(HTTPException) as e:
        bc.lock_month(bc.LockBody(business_id="biz", month="2026-08"), user=U())
    assert e.value.status_code == 409 and "categorize" in e.value.detail["open"]
    assert calls == []
    out = bc.lock_month(bc.LockBody(business_id="biz", month="2026-08", with_open=True), user=U())
    assert out["closed"] and calls == ["p-aug"] and "categorize" in out["open"]


def test_close_anyway_records_what_was_skipped_once_the_column_exists(db, monkeypatch):
    _as_manager(monkeypatch)
    monkeypatch.setattr(bc, "checklist_supported", lambda: True)
    import accounting_periods_router
    monkeypatch.setattr(accounting_periods_router, "close", lambda pid, user: {"ok": True, "closed": True})
    bc.lock_month(bc.LockBody(business_id="biz", month="2026-08", with_open=True), user=U())
    note = [w for w in db.writes if w[0] == "patch"][-1][2]["close_checklist"]
    assert "categorize" in note["closed_with_open"]


def test_statement_saves_wait_for_the_checklist_column(db, monkeypatch):
    _as_manager(monkeypatch)
    with pytest.raises(HTTPException) as e:
        bc.save_statement(bc.StatementBody(business_id="biz", month="2026-08",
                                           balances=[{"account_id": "a-pri", "balance": 440}]), user=U())
    assert e.value.status_code == 409 and db.writes == []


def test_a_statement_merges_into_the_months_checklist(db, monkeypatch):
    _as_manager(monkeypatch)
    monkeypatch.setattr(bc, "checklist_supported", lambda: True)
    db.tables["/accounting_periods"][0]["close_checklist"] = {"reviewed": {"at": "2026-09-30"}}
    bc.save_statement(bc.StatementBody(business_id="biz", month="2026-08",
                                       balances=[{"account_id": "a-pri", "balance": 440.004}]), user=U())
    [(_, path, body)] = db.writes
    assert "id=eq.p-aug" in path
    saved = body["close_checklist"]
    assert saved["reviewed"] == {"at": "2026-09-30"} and saved["statements"]["a-pri"]["balance"] == 440.0


def test_a_statement_for_an_account_outside_the_books_is_refused(db, monkeypatch):
    _as_manager(monkeypatch)
    monkeypatch.setattr(bc, "checklist_supported", lambda: True)
    with pytest.raises(HTTPException) as e:
        bc.save_statement(bc.StatementBody(business_id="biz", month="2026-08",
                                           balances=[{"account_id": "someone-else", "balance": 1}]), user=U())
    assert e.value.status_code == 400 and db.writes == []


def test_a_balance_that_is_not_a_number_is_refused(db, monkeypatch):
    _as_manager(monkeypatch)
    monkeypatch.setattr(bc, "checklist_supported", lambda: True)
    with pytest.raises(HTTPException) as e:
        bc.save_statement(bc.StatementBody(business_id="biz", month="2026-08",
                                           balances=[{"account_id": "a-pri", "balance": math.nan}]), user=U())
    assert e.value.status_code == 400


def test_a_closed_month_keeps_its_answers(db, monkeypatch):
    _as_manager(monkeypatch)
    monkeypatch.setattr(bc, "checklist_supported", lambda: True)
    db.tables["/accounting_periods"][0]["status"] = "closed"
    with pytest.raises(HTTPException) as e:
        bc.save_reviewed(bc.ReviewedBody(business_id="biz", month="2026-08"), user=U())
    assert e.value.status_code == 409 and db.writes == []


def test_answers_wait_for_the_month_to_end(db, monkeypatch):
    _as_manager(monkeypatch)
    monkeypatch.setattr(bc, "checklist_supported", lambda: True)
    with pytest.raises(HTTPException) as e:
        bc.save_reviewed(bc.ReviewedBody(business_id="biz", month="2026-10"), user=U())
    assert e.value.status_code == 400


# ─── The review queue, one month at a time ───────────────────────────

def test_the_review_queue_narrows_to_one_month(db):
    out = bo.build_review("biz", month="2026-08")
    assert [r["transaction_id"] for r in out["rows"]] == ["a1", "a2"] and out["total"] == 2


# ─── A close that didn't save never says "closed" ────────────────────

def test_a_rejected_close_write_is_an_error_not_a_lock(monkeypatch):
    import gl_engine
    monkeypatch.setattr(gl_engine.sb_clients, "sb_get_as_service",
                        lambda p: [{"id": "p", "period_type": "month", "status": "open"}])
    monkeypatch.setattr(gl_engine.sb_clients, "sb_patch_as_service", lambda p, b: None)
    with pytest.raises(HTTPException) as e:
        gl_engine.close_period("biz", "p", closed_by="u")
    assert e.value.status_code == 502


def test_a_revoked_connection_holds_open_only_the_months_it_never_reached():
    old = {"item_id": "old", "institution_name": "Found", "status": "revoked",
           "last_sync_at": "2026-06-07T10:00:00+00:00"}
    accounts = [PRIMARY, dict(TAXES, item_id="old")]
    aug = bc.sync_step(AUG, bc.month_end(AUG), TODAY, [ITEM, old], accounts, [], None, False)
    assert not aug["done"] and aug["action"] == "connections" and "old Found connection" in aug["detail"]
    apr = date(2026, 4, 1)
    assert bc.sync_step(apr, bc.month_end(apr), TODAY, [ITEM, old], accounts, [], None, False)["done"]


def test_a_quiet_empty_pocket_does_not_hold_the_statement_check_open():
    pocket = dict(PRIMARY, account_id="a-pocket", name="Office Supplies", mask="9035", last_balance=0.0)
    s = bc.statement_step(AUG, bc.month_end(AUG), [PRIMARY, pocket], [],
                          {"statements": {"a-pri": {"balance": 500.0}}}, True)
    assert s["done"] and [a["quiet"] for a in s["accounts"]] == [False, True]


def test_a_balance_typed_for_a_quiet_pocket_still_has_to_agree():
    pocket = dict(PRIMARY, account_id="a-pocket", name="Office Supplies", mask="9035", last_balance=0.0)
    s = bc.statement_step(AUG, bc.month_end(AUG), [PRIMARY, pocket], [],
                          {"statements": {"a-pri": {"balance": 500.0}, "a-pocket": {"balance": 3.0}}}, True)
    assert not s["done"] and "Office Supplies" in s["detail"]


def test_a_revoked_copy_of_a_live_account_is_not_asked_twice(db):
    old = {"item_id": "old", "institution_name": "Found", "status": "revoked",
           "last_sync_at": "2026-06-07T10:00:00+00:00", "last_error": None}
    db.tables["/plaid_items"] = [ITEM, old]
    db.tables["/plaid_accounts"] = [PRIMARY, TAXES, dict(PRIMARY, account_id="a-pri-old", item_id="old")]
    out = bc.build_close("biz", BIZ, month="2026-04", now=NOW)
    st = next(s for s in out["steps"] if s["key"] == "statement")
    assert [a["account_id"] for a in st["accounts"]] == ["a-pri", "a-tax"]


def test_an_account_in_the_books_twice_holds_every_month_open():
    old = {"item_id": "old", "institution_name": "Found", "status": "revoked",
           "last_sync_at": "2026-06-07T10:00:00+00:00"}
    accounts = [PRIMARY, TAXES, dict(PRIMARY, account_id="a-pri-old", item_id="old")]
    apr = date(2026, 4, 1)
    s = bc.sync_step(apr, bc.month_end(apr), TODAY, [ITEM, old], accounts, [], None, False)
    assert not s["done"] and s["action"] == "connections"
    assert s["detail"].startswith("One account is in the books twice, from an old Found connection")


def test_a_sentence_names_rows_the_way_people_say_them():
    assert bc.display_name({"name": "STRIPE - TRANSFER ST-O8S1O5T2L6I7"}) == "a Stripe transfer"
    assert bc.display_name({"name": "RAILWAY CORPORATION"}) == "Railway Corporation"
    assert bc.display_name({"name": "Resend"}) == "Resend"
