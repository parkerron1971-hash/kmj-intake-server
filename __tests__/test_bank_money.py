"""What a bank row IS: one rule set, honoured by the ledger, the reports,
the counts and the review queue.

Plaid's category decided income vs. spending on its own, so a move between
two of the business's own accounts was income on one side and spending on
the other, and a deposit couldn't be marked "money from the owner" at all.
money_kind (income / owner / transfer) is the practitioner's answer, and
NULL keeps every old behaviour exactly. These tests hold both halves of
that promise.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bank_money  # noqa: E402
import gl_engine as gl  # noqa: E402
import bookkeeping_overview as bo  # noqa: E402


def tx(amount, kind=None, primary=None, detail=None, bucket=None, payout=None, tid="t", acct="a1",
       day="2026-08-25", name="X"):
    return {"transaction_id": tid, "account_id": acct, "amount": amount, "date": day,
            "name": name, "merchant_name": name, "money_kind": kind,
            "plaid_category_primary": primary, "plaid_category_detail": detail,
            "business_category": bucket, "reconciled_to_payout_id": payout,
            "pending": False, "excluded_from_books": False}


def lines(t):
    [entry] = gl.desired_for_plaid(t)
    return {(l["code"], "dr" if l["debit"] else "cr") for l in entry["lines"]}


# ─── NULL keeps the old automatic behaviour ──────────────────────────

def test_without_an_answer_the_bank_label_still_decides():
    assert lines(tx(-10.0, primary="TRANSFER_IN")) == {("1000", "dr"), ("4900", "cr")}   # income, as before
    assert lines(tx(-10.0, primary="OTHER")) == {("1000", "dr"), ("3100", "cr")}         # equity, as before
    assert lines(tx(10.0, primary="GENERAL_SERVICES", bucket="operating")) == {("5000", "dr"), ("1000", "cr")}
    out = lines(tx(10.0, primary="TRANSFER_OUT"))            # an expense line, as before
    assert ("1000", "cr") in out and any(c.startswith("5") for c, side in out if side == "dr")


# ─── An answer overrides the label ───────────────────────────────────

def test_a_transfer_never_touches_income_or_expense():
    assert lines(tx(-10.7, kind="transfer", primary="TRANSFER_IN")) == {("1000", "dr"), ("1050", "cr")}
    assert lines(tx(10.7, kind="transfer", primary="GOVERNMENT_AND_NON_PROFIT", bucket="tax")) == \
        {("1050", "dr"), ("1000", "cr")}


def test_owner_money_is_equity_both_ways():
    assert lines(tx(-314.0, kind="owner", primary="TRANSFER_IN")) == {("1000", "dr"), ("3100", "cr")}
    assert lines(tx(41.0, kind="owner", primary="TRANSFER_OUT", bucket="operating")) == \
        {("3200", "dr"), ("1000", "cr")}


def test_income_is_income_whatever_the_bank_says():
    assert lines(tx(-41.45, kind="income", primary="OTHER")) == {("1000", "dr"), ("4900", "cr")}


def test_a_payout_deposit_stays_with_stripe_clearing_even_if_answered():
    assert lines(tx(-41.45, kind="income", payout="po_1")) == {("1000", "dr"), ("1150", "cr")}


def test_the_rules_agree_with_the_ledger():
    assert bank_money.is_income(tx(-1, kind="income")) and not bank_money.is_income(tx(-1, kind="owner"))
    assert not bank_money.is_expense(tx(5, kind="transfer", bucket="tax"))
    assert not bank_money.needs_category(tx(-1, kind="owner"))
    assert bank_money.needs_category(tx(-1, bucket="other"))
    assert not bank_money.needs_category(tx(5, bucket="operating"))


def test_transfers_in_transit_is_in_every_chart():
    assert any(code == "1050" for code, *_ in gl.COA_SEED)


# ─── The review queue ────────────────────────────────────────────────

ACCTS = [
    {"account_id": "pri", "name": "KMJ LLC - Primary", "mask": "9020", "type": "depository",
     "included_in_bookkeeping": True, "is_trust_account": False},
    {"account_id": "tax", "name": "KMJ LLC - Taxes", "mask": "2693", "type": "depository",
     "included_in_bookkeeping": True, "is_trust_account": False},
]


@pytest.fixture
def db(monkeypatch):
    tables = {"/plaid_accounts": ACCTS, "/plaid_transactions": []}
    patched = []

    def get(path):
        table = path.split("?")[0]
        rows = tables.get(table, [])
        if "offset=" in path:
            off = int(path.split("offset=")[1].split("&")[0])
            return rows[off:off + 1000]
        return rows

    def patch(path, body):
        patched.append((path, body))
        return [body]
    monkeypatch.setattr(bo.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(bo.sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(bank_money, "supported", lambda: True)
    return tables, patched


def test_review_suggests_what_each_row_most_likely_is(db):
    tables, _ = db
    tables["/plaid_transactions"] = [
        tx(10.7, tid="out", acct="tax", primary="GOVERNMENT_AND_NON_PROFIT", bucket="tax", name="Taxes to Primary"),
        tx(-10.7, tid="in", acct="pri", primary="TRANSFER_IN", bucket="other", name="Taxes to Primary"),
        tx(-41.45, tid="stripe", acct="pri", primary="INCOME", bucket="other", name="STRIPE - TRANSFER ST-1",
           day="2026-08-11"),
        tx(-314.0, tid="visa", acct="pri", primary="TRANSFER_IN", bucket="other",
           name="Instant transfer from Visa debit", day="2026-09-15"),
        tx(20.0, tid="sb", acct="pri", primary="GENERAL_SERVICES", bucket="other", name="Supabase", day="2026-07-02"),
        tx(-5.0, tid="done", acct="pri", kind="owner", name="answered"),
    ]
    out = bo.build_review("biz")
    by = {r["transaction_id"]: r for r in out["rows"]}
    assert "done" not in by and "out" not in by              # answered / already bucketed
    assert by["in"]["suggestion"]["kind"] == "transfer" and by["in"]["pair_with"] == "out"
    assert by["stripe"]["suggestion"]["kind"] == "income"
    assert by["visa"]["suggestion"]["kind"] == "owner"
    assert by["sb"]["suggestion"]["bucket"] == "operating"
    assert out["pairs"] == [{"out_id": "out", "in_id": "in", "date": "2026-08-25", "amount": 10.7,
                             "from": "Taxes ••2693", "to": "Primary ••9020"}]


def test_confirming_a_pair_marks_both_legs_and_rechecks_it(db, monkeypatch):
    tables, patched = db
    tables["/plaid_transactions"] = [
        tx(10.7, tid="out", acct="tax", day="2026-08-25"),
        tx(-10.7, tid="in", acct="pri", day="2026-08-25"),
        tx(-99.0, tid="wrong", acct="pri", day="2026-08-25"),
    ]
    import plaid_router
    monkeypatch.setattr(plaid_router, "_require_owner", lambda biz, user: {"id": biz})
    body = bo.ConfirmPairsBody(business_id="biz", pairs=[["out", "in"], ["out", "wrong"]])
    res = bo.confirm_transfer_pairs(body, user=object())
    assert res["confirmed_pairs"] == 1 and res["skipped"] == [["out", "wrong"]]
    [(path, patch)] = patched
    assert "transaction_id=in.(out,in)" in path and patch["money_kind"] == "transfer"


def test_confirming_before_the_migration_says_so(db, monkeypatch):
    import plaid_router
    from fastapi import HTTPException
    monkeypatch.setattr(plaid_router, "_require_owner", lambda biz, user: {"id": biz})
    monkeypatch.setattr(bank_money, "supported", lambda: False)
    with pytest.raises(HTTPException) as e:
        bo.confirm_transfer_pairs(bo.ConfirmPairsBody(business_id="biz", pairs=[["a", "b"]]), user=object())
    assert e.value.status_code == 409
