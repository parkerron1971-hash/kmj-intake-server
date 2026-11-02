"""
test_chief_file_bank.py — "put these in expense and revenue": Chief files the
waiting bank rows in one batch the owner confirmed, and one undo.

Kevin, 2026-10-31: "NOW CAN I ASK CHIEF TO PLACE IN EXPENSE AND REVENUE ETC
WOULD CHIEF DO THAT?"

Pins:
  * the read is the To review queue, grouped by payee and direction, money in
    positive; readers may read, a stranger may not; off says so
  * filing writes the screen's own answers (money_kind, a bucket, a label, or
    out of the books), only on rows still waiting, each guarded on its values
    from before; money in can't be an expense, money out can't be income
  * a row answered meanwhile is left as it is and counted
  * undo puts the batch back, skipping a row answered since
  * the owner alone files; the wiring holds (registry, inverse, tool, prompt)
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_inverse  # noqa: E402
import action_registry  # noqa: E402
import bank_money  # noqa: E402
import bookkeeping_overview as bo  # noqa: E402
import chief_file_bank as cf  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_transactions  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
STRANGER = "00000000-0000-4000-8000-000000000009"


def _tx(tid, on, amount, name, **kw):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc", "date": on, "name": name,
            "merchant_name": None, "amount": amount, "pending": False, "excluded_from_books": False,
            "business_category": "other", "business_subcategory": None, "money_kind": None,
            "plaid_category_primary": None, "plaid_category_detail": None,
            "reconciliation_status": "unmatched", "reconciled_to_payout_id": None, **kw}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        plaid_accounts=[{"account_id": "acc", "business_id": BIZ, "name": "Checking", "mask": "5565",
                         "type": "depository", "included_in_bookkeeping": True, "deleted_at": None,
                         "is_trust_account": False}],
        # Plaid's sign: money out positive. Made-up figures.
        plaid_transactions=[
            _tx("t1", "2026-01-05", -1200, "TITHELY PAYOUT 0105"),
            _tx("t2", "2026-01-12", -950.5, "TITHELY PAYOUT 0112"),
            _tx("t3", "2026-01-19", -1010, "TITHELY PAYOUT 0119"),
            _tx("o1", "2026-01-07", 36, "OVERDRAFT FEE"),
            _tx("o2", "2026-01-21", 36, "OVERDRAFT FEE"),
            _tx("u1", "2026-01-15", 212.4, "DUKE ENERGY UTIL PYMT"),
            _tx("c1", "2026-01-09", -300, "MONEYSEND TRANSF CASH APP"),
            _tx("done", "2026-01-20", 80, "OFFICE DEPOT", business_category="operating"),   # answered already
        ],
        chief_undo_log=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    # The fake treats offset as a filter; the queue reads one page here.
    monkeypatch.setattr(bo, "_get_all", lambda path, cap=0: bo._get(path))
    monkeypatch.setattr(bank_money, "state", lambda: True)
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: True)

    def reader(business_id, user):
        if str(user.id) not in (OWNER, READER) or business_id != BIZ:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "owner_id": OWNER}

    def owner(business_id, user):
        if str(user.id) != OWNER or business_id != BIZ:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "owner_id": OWNER}
    monkeypatch.setattr(plaid_router, "_require_reader", reader)
    monkeypatch.setattr(plaid_router, "_require_owner", owner)
    monkeypatch.setattr(plaid_router, "_require_money_writer", owner)
    return fake


def _run(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


def _row(db, tid):
    return next(t for t in db.t["plaid_transactions"] if t["transaction_id"] == tid)


# ─── The read ────────────────────────────────────────────────────────

def test_the_waiting_rows_come_grouped_by_payee(db):
    got = _run(cf.handle_bank_to_file, {}, who=READER)
    assert not got.get("failed"), got
    assert got["total"] == 7                                   # the answered one isn't waiting
    first = got["groups"][0]
    assert (first["payee"], first["direction"], first["count"], first["total"]) == ("tithely payout", "in", 3, 3160.5)
    assert first["transaction_ids"] == ["t1", "t2", "t3"]       # oldest first
    fees = next(g for g in got["groups"] if g["payee"] == "overdraft fee")
    assert (fees["direction"], fees["count"], fees["total"]) == ("out", 2, -72)
    assert "7 bank rows wait for an answer (4 money in, 3 money out)" in got["result"]
    only_in = _run(cf.handle_bank_to_file, {"direction": "in", "words": ["cash app"]})
    assert [g["payee"] for g in only_in["groups"]] == ["moneysend transf cash app"]


def test_a_stranger_reads_nothing_and_off_says_so(db, monkeypatch):
    assert _run(cf.handle_bank_to_file, {}, who=STRANGER)["failed"]
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: False)
    got = _run(cf.handle_bank_to_file, {})
    assert got["failed"] and "isn't switched on" in got["result"]


# ─── Filing ──────────────────────────────────────────────────────────

def test_filing_writes_the_screens_answers_on_the_confirmed_payees(db):
    got = _run(cf.handle_file_bank_rows, {"items": [
        {"payee": "tithely payout", "direction": "in", "answer": "income", "label": "Giving"},
        {"payee": "overdraft fee", "answer": "operating", "label": "Bank fees"},
        {"transaction_ids": ["u1"], "answer": "operating", "label": "Utilities"}]})
    assert not got.get("failed"), got
    assert got["summary"]["count"] == 6 and len(got["changes"]) == 6 and len(got["batch_id"]) == 32
    assert (_row(db, "t1")["money_kind"], _row(db, "t1")["business_subcategory"]) == ("income", "Giving")
    assert (_row(db, "o2")["business_category"], _row(db, "o2")["business_subcategory"]) == ("operating", "Bank fees")
    assert _row(db, "u1")["business_subcategory"] == "Utilities"
    assert _row(db, "c1")["money_kind"] is None                # never named: left waiting
    assert "Filed 6 bank rows: 3 as income (Giving); 2 as operating expense (Bank fees)" in got["result"]
    assert got["display"] == "table" and got["rows"][0]["filed"]
    assert {c["id"]: c["before"] for c in got["changes"]}["t1"] == {
        "money_kind": None, "business_subcategory": None, "business_category": "other", "excluded_from_books": False}


def test_money_in_is_never_an_expense_and_money_out_never_income(db):
    got = _run(cf.handle_file_bank_rows, {"items": [
        {"transaction_ids": ["t1"], "answer": "operating"}, {"transaction_ids": ["o1"], "answer": "income"}]})
    assert got["failed"] and "money in, so it can't be operating expense" in got["result"]
    assert "money out, so it can't be income" in got["result"]
    assert _row(db, "t1")["business_category"] == "other" and _row(db, "o1")["money_kind"] is None


def test_only_waiting_rows_are_touched(db):
    got = _run(cf.handle_file_bank_rows, {"items": [{"transaction_ids": ["done", "u1"], "answer": "tax"}]})
    assert got["summary"]["count"] == 1 and _row(db, "done")["business_category"] == "operating"
    assert "1 of its rows aren't waiting any more" in got["result"]


def test_a_row_answered_meanwhile_is_left_as_it_is(db, monkeypatch):
    stale = cf.queue(BIZ)                                       # read before the screen answered o1
    _row(db, "o1").update(business_category="tax")
    monkeypatch.setattr(cf, "queue", lambda biz: stale)
    got = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "answer": "operating"}]})
    assert got["summary"]["count"] == 1 and "1 were answered by someone else" in got["result"]
    assert _row(db, "o1")["business_category"] == "tax"


def test_personal_never_hides_a_row_answered_meanwhile(db, monkeypatch):
    stale = cf.queue(BIZ)                                       # read before the screen answered c1
    _row(db, "c1").update(money_kind="income", business_subcategory="Giving")
    monkeypatch.setattr(cf, "queue", lambda biz: stale)
    got = _run(cf.handle_file_bank_rows, {"items": [{"transaction_ids": ["c1"], "answer": "personal"}]})
    assert _row(db, "c1")["excluded_from_books"] is False and "1 were answered by someone else" in got["result"]


def test_without_the_money_kind_column_expenses_still_file(db, monkeypatch):
    monkeypatch.setattr(bank_money, "state", lambda: False)
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **kw: None if "money_kind" in path else real(path, body, **kw))
    got = _run(cf.handle_file_bank_rows, {"items": [
        {"payee": "overdraft fee", "answer": "operating"}, {"payee": "tithely payout", "answer": "income"}]})
    assert got["summary"]["count"] == 2 and _row(db, "o1")["business_category"] == "operating"
    assert "needs the bank money update" in got["result"] and _row(db, "t1")["money_kind"] is None


def test_personal_leaves_the_books_and_comes_back_on_undo(db):
    got = _run(cf.handle_file_bank_rows, {"items": [{"transaction_ids": ["c1"], "answer": "personal"}]})
    assert _row(db, "c1")["excluded_from_books"] is True
    db.t["chief_undo_log"].append({"id": "u", "business_id": BIZ, "action_type": "file_bank_rows",
                                   "status": "undoable", "created_at": "2099-01-01T00:00:00Z", "result_json": got})
    back = _run(cf.handle_undo_file_bank_rows, {})
    assert not back.get("failed"), back
    assert _row(db, "c1")["excluded_from_books"] is False


def test_undo_puts_the_batch_back_and_skips_a_row_answered_since(db):
    got = _run(cf.handle_file_bank_rows, {"items": [
        {"payee": "tithely payout", "answer": "income", "label": "Giving"}]})
    db.t["chief_undo_log"].append({"id": "u", "business_id": BIZ, "action_type": "file_bank_rows",
                                   "status": "undoable", "created_at": "2099-01-01T00:00:00Z", "result_json": got})
    _row(db, "t3").update(business_subcategory="Building fund")          # the owner relabels one since
    back = _run(cf.handle_undo_file_bank_rows, {"batch_id": got["batch_id"]})
    assert "Put back 2 bank rows" in back["result"] and "1 had been answered since" in back["result"]
    assert (_row(db, "t1")["money_kind"], _row(db, "t1")["business_subcategory"]) == (None, None)
    assert _row(db, "t3")["money_kind"] == "income"
    assert db.t["chief_undo_log"][0]["status"] == "undone"
    assert _run(cf.handle_undo_file_bank_rows, {})["failed"]           # nothing left to undo


def test_the_owner_alone_files_and_a_big_batch_is_split(db, monkeypatch):
    got = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "answer": "operating"}]}, who=READER)
    assert got["failed"] and "Only the owner" in got["result"] and _row(db, "o1")["business_category"] == "other"
    monkeypatch.setattr(cf, "ROW_MAX", 2)
    big = _run(cf.handle_file_bank_rows, {"items": [{"payee": "tithely payout", "answer": "income"}]})
    assert big["failed"] and "at most 2" in big["result"]


def test_a_failed_read_files_nothing(db, monkeypatch):
    monkeypatch.setattr(bo, "_get_all", lambda path, cap=0: (_ for _ in ()).throw(bo.SourceFailed("x")))
    got = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "answer": "operating"}]})
    assert got["failed"] and "nothing was filed" in got["result"]


# ─── A church that records its gifts ─────────────────────────────────

def _records_gifts(db):
    db.t["invoices"] = [{"id": "g1", "business_id": BIZ, "is_gift": True, "status": "paid",
                         "paid_at": "2099-01-04T12:00:00Z", "payment_method": "cash", "total": 650}]


def test_a_giving_deposit_is_never_filed_as_income_where_gifts_are_recorded(db):
    """Love City records its Sunday gifts by person (cash, check, Subsplash,
    Cash App); each is income in the books already, so the bank deposit of
    that money filed as income would count it twice (Kevin, 2026-10-31)."""
    _records_gifts(db)
    seen = _run(cf.handle_bank_to_file, {})
    assert seen["gifts_recorded"] is True and "count them twice" in seen["result"]
    assert "IMPORTANT" in seen["note_for_chief"]
    got = _run(cf.handle_file_bank_rows, {"items": [
        {"payee": "tithely payout", "answer": "income", "label": "Giving"},
        {"payee": "overdraft fee", "answer": "operating", "label": "Bank fees"}]})
    assert got["summary"]["count"] == 2 and "would count it twice" in got["result"]
    assert _row(db, "t1")["money_kind"] is None and _row(db, "o1")["business_category"] == "operating"
    # not_a_gift: one row at a time, and never on a deposit that reads like giving.
    whole = _run(cf.handle_file_bank_rows, {"items": [
        {"payee": "duke energy util pymt", "answer": "income", "not_a_gift": True}]})
    assert whole["failed"] and "never a whole payee" in whole["result"]
    cashapp = _run(cf.handle_file_bank_rows, {"items": [
        {"transaction_ids": ["c1"], "answer": "income", "label": "Rent", "not_a_gift": True}]})
    assert cashapp["failed"] and "reads like a giving deposit" in cashapp["result"]
    assert _row(db, "c1")["money_kind"] is None
    db.t["plaid_transactions"].append(_tx("r1", "2026-01-26", -500, "CHECK DEPOSIT ACME PROPERTY RENT"))
    rent = _run(cf.handle_file_bank_rows, {"items": [
        {"transaction_ids": ["r1"], "answer": "income", "label": "Rent", "not_a_gift": True}]})
    assert rent["summary"]["count"] == 1 and _row(db, "r1")["money_kind"] == "income"
    assert "not giving, per the owner" in rent["rows"][0]["filed"]


def test_old_unpaid_or_non_gift_invoices_dont_count_as_recorded_gifts(db):
    db.t["invoices"] = [
        {"id": "a", "business_id": BIZ, "is_gift": True, "status": "paid", "paid_at": "2020-01-04T12:00:00Z"},
        {"id": "b", "business_id": BIZ, "is_gift": True, "status": "sent", "paid_at": None},
        {"id": "c", "business_id": BIZ, "is_gift": False, "status": "paid", "paid_at": "2099-01-04T12:00:00Z"}]
    assert cf.gifts_recorded(BIZ) is False
    _records_gifts(db)
    assert cf.gifts_recorded(BIZ) is True


def test_a_failed_gift_read_blocks_only_income(db, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/invoices") else real(path, **kw))
    seen = _run(cf.handle_bank_to_file, {})
    assert not seen.get("failed") and seen["gifts_recorded"] is None and "couldn't be checked" in seen["result"]
    fees = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "answer": "operating"}]})
    assert fees["summary"]["count"] == 2
    inc = _run(cf.handle_file_bank_rows, {"items": [{"transaction_ids": ["c1"], "answer": "income"}]})
    assert inc["failed"] and "couldn't be checked" in inc["result"] and _row(db, "c1")["money_kind"] is None


# ─── Wiring ──────────────────────────────────────────────────────────

def test_the_verbs_are_wired():
    import chief_tool_loop
    assert cos.ACTION_HANDLERS["file_bank_rows"] is cf.handle_file_bank_rows
    assert cos.ACTION_HANDLERS["undo_file_bank_rows"] is cf.handle_undo_file_bank_rows
    assert cos.ACTION_HANDLERS["bank_to_file"] is cf.handle_bank_to_file
    assert action_registry.REGISTRY["file_bank_rows"]["chief_only"] is True
    assert "bank_to_file" in {t["name"] for t in chief_tool_loop.read_tool_definitions()}
    inv = action_inverse.build_inverse("file_bank_rows", {}, {"batch_id": "a" * 32, "changes": [{"id": "t1"}]})
    assert inv == {"type": "undo_file_bank_rows", "batch_id": "a" * 32}
    import chief_prompt
    src = open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
    assert '"type":"file_bank_rows"' in src and '"type":"undo_file_bank_rows"' in src and '"type":"bank_to_file"' in src
