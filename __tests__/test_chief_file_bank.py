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
        "money_kind": None, "business_subcategory": None, "business_category": "other"}


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
