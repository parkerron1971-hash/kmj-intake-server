"""A bank linked twice doubles the books; the fix must never lose a row.

KMJ relinked Found on 2026-06-07. The old connection was revoked, but its
copies of Primary ••9020 and Taxes ••2693 stayed in the books, so 68 groups
of rows were doubled. These tests hold the fix to two promises: it only
sets aside a copy whose every row has a twin on the copy kept, and an
answer that exists only on the old copy is carried over first.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bookkeeping_overview as bo  # noqa: E402

ITEMS = [{"item_id": "old", "status": "revoked"}, {"item_id": "new", "status": "active"}]
OLD = {"account_id": "a-old", "item_id": "old", "name": "KMJ LLC - Primary", "mask": "9020",
       "type": "depository", "included_in_bookkeeping": True, "is_trust_account": False}
NEW = dict(OLD, account_id="a-new", item_id="new")


def tx(tid, acct, amount, day, name="Railway", bucket=None):
    return {"transaction_id": tid, "account_id": acct, "amount": amount, "date": day,
            "name": name, "merchant_name": name, "business_category": bucket}


def test_the_revoked_copy_is_the_extra_and_safe_when_every_row_has_a_twin():
    txs = [tx("o1", "a-old", 5.0, "2026-06-01", bucket="operating"),
           tx("n1", "a-new", 5.0, "2026-06-01"),
           tx("n2", "a-new", 20.0, "2026-09-02", name="Resend")]
    [plan] = bo.linked_twice_plans([OLD, NEW], ITEMS, txs)
    assert plan["old_account_id"] == "a-old" and plan["keep_account_id"] == "a-new"
    assert plan["old_connection"] == "revoked"
    assert plan["rows"] == 1 and plan["rows_without_twin"] == 0
    assert plan["answers_to_carry"] == 1          # the old copy's category, the new one has none


def test_a_row_without_a_twin_makes_the_copy_unsafe():
    txs = [tx("o1", "a-old", 5.0, "2026-06-01"), tx("o2", "a-old", 9.0, "2026-05-01", name="Only here"),
           tx("n1", "a-new", 5.0, "2026-06-01")]
    [plan] = bo.linked_twice_plans([OLD, NEW], ITEMS, txs)
    assert plan["rows_without_twin"] == 1


def test_one_copy_per_account_is_not_a_plan():
    assert bo.linked_twice_plans([NEW], ITEMS, [tx("n1", "a-new", 5.0, "2026-06-01")]) == []


@pytest.fixture
def db(monkeypatch):
    tables = {"/plaid_items": ITEMS, "/plaid_accounts": [OLD, NEW], "/plaid_transactions": []}
    writes = []

    def get(path):
        rows = tables.get(path.split("?")[0], [])
        if "offset=" in path:
            off = int(path.split("offset=")[1].split("&")[0])
            return rows[off:off + 1000]
        return rows
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(bo.sb_clients, "sb_patch_as_service", lambda p, b: writes.append(("patch", p, b)) or [b])
    monkeypatch.setattr(bo.sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: writes.append(("post", p, b)) or [])
    import plaid_router
    monkeypatch.setattr(plaid_router, "_require_owner", lambda biz, user: {"id": biz})
    return tables, writes


def test_resolve_carries_answers_then_switches_the_copy_off(db):
    tables, writes = db
    tables["/plaid_transactions"] = [tx("o1", "a-old", 5.0, "2026-06-01", bucket="operating"),
                                     tx("n1", "a-new", 5.0, "2026-06-01")]
    out = bo.resolve_linked_twice(bo.ResolveTwiceBody(business_id="biz", account_ids=["a-old"]), user=object())
    assert out["resolved"][0]["answers_carried"] == 1 and out["refused"] == []
    kinds = [(w[0], w[1].split("?")[0]) for w in writes]
    # answers first, then the ledger is told, and only then the copy goes off
    assert kinds == [("patch", "/plaid_transactions"), ("post", "/gl_sync_queue"), ("patch", "/plaid_accounts")]
    assert writes[0][2]["business_category"] == "operating"
    assert writes[2][2]["included_in_bookkeeping"] is False


def test_resolve_refuses_a_copy_that_would_lose_rows(db):
    tables, writes = db
    tables["/plaid_transactions"] = [tx("o2", "a-old", 9.0, "2026-05-01", name="Only here")]
    out = bo.resolve_linked_twice(bo.ResolveTwiceBody(business_id="biz", account_ids=["a-old"]), user=object())
    assert out["resolved"] == [] and "no twin" in out["refused"][0]["why"]
    assert writes == []


def test_resolve_refuses_the_copy_being_kept(db):
    tables, writes = db
    tables["/plaid_transactions"] = [tx("n1", "a-new", 5.0, "2026-06-01")]
    out = bo.resolve_linked_twice(bo.ResolveTwiceBody(business_id="biz", account_ids=["a-new"]), user=object())
    assert out["resolved"] == [] and writes == []


def test_an_owner_answer_carries_even_when_the_twin_has_a_category(db):
    tables, writes = db
    old = dict(tx("o1", "a-old", 41.0, "2026-08-12", name="Chime", bucket="operating"), money_kind="owner")
    twin = tx("n1", "a-new", 41.0, "2026-08-12", name="Chime", bucket="operating")
    tables["/plaid_transactions"] = [old, twin]
    out = bo.resolve_linked_twice(bo.ResolveTwiceBody(business_id="biz", account_ids=["a-old"]), user=object())
    assert out["resolved"][0]["answers_carried"] == 1
    assert writes[0][2] == {"money_kind": "owner"}         # not the category: the twin had one


def test_if_the_ledger_cant_be_told_nothing_is_switched_off(db, monkeypatch):
    tables, writes = db
    tables["/plaid_transactions"] = [tx("o1", "a-old", 5.0, "2026-06-01"), tx("n1", "a-new", 5.0, "2026-06-01")]
    monkeypatch.setattr(bo.sb_clients, "sb_post_as_service", lambda p, b, prefer=None: None)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        bo.resolve_linked_twice(bo.ResolveTwiceBody(business_id="biz", account_ids=["a-old"]), user=object())
    assert e.value.status_code == 502
    assert not any(w[1].startswith("/plaid_accounts") for w in writes)


def test_plans_are_withheld_when_bank_rows_did_not_load(monkeypatch):
    from datetime import datetime, timezone
    tables = {"/plaid_items": ITEMS, "/plaid_accounts": [OLD, NEW]}

    def get(path):
        t = path.split("?")[0]
        return None if t == "/plaid_transactions" else tables.get(t, [])
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(bo, "year_so_far", lambda biz, row: None)
    o = bo.build_overview("biz", {"id": "biz", "settings": {}}, now=datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert o["bank"]["linked_twice"] == []
