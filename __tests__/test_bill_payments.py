"""
test_bill_payments.py — a bill matched to the bank payment that paid it, so it
counts once (Bills step 2). Made-up figures.

Kevin, 2026-11-01: the categories Chief made should work under the Bills tab
too; before Chief adds bills, a bill and its bank payment must count once.

Pins:
  * the ledger: a bank-paid bill books a settle (Dr AP / Cr its expense), never
    a second cash leg; with its bank row the expense counts once, AP clears and
    cash goes out once. A bill paid by hand books its payment as before
  * candidates: exact amount, or near with the vendor's name; inside the
    window; a row already paying another bill never offered; the plain one
  * the match: the bill reads paid from the bank; a waiting bank row takes the
    bill's line and category, a filed one is left; refusals: not money out in
    the books, already paying a bill, a bill already matched or not owed
  * unmatch: owed again (overdue when past due), or back as it was
  * the Bills tab's routes: the owner only, only where switched on
  * Chief: the plain ones, its undo, and the lookup's looks_paid_by
  * a bill's bank payment can't be moved out of the books; a category rename
    moves bills too
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_inverse  # noqa: E402
import action_registry  # noqa: E402
import bill_payments as bp  # noqa: E402
import bills_router  # noqa: E402
import chief_bills  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_transactions  # noqa: E402
import expense_categories as ec  # noqa: E402
import gl_engine  # noqa: E402
import period_lock  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
STRANGER = "00000000-0000-4000-8000-000000000009"
T = date.today()


def _bill(bid, vendor, amount, due, status="pending", **kw):
    return {"id": bid, "business_id": BIZ, "vendor_name": vendor, "amount": amount, "category": "operating",
            "subcategory": None, "status": status, "due_date": due.isoformat(), "created_at": f"{due}T00:00:00Z",
            "paid_at": None, "paid_amount": None, "paid_via": None, "paid_transaction_id": None,
            "is_recurring": False, "recurrence_parent_id": None, **kw}


def _tx(tid, on, amount, name, cat=None, sub=None, kind=None):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc", "date": on.isoformat(), "name": name,
            "merchant_name": None, "amount": amount, "pending": False, "excluded_from_books": False,
            "money_kind": kind, "business_category": cat, "business_subcategory": sub}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "type": "ministry", "owner_id": OWNER}],
        plaid_accounts=[{"account_id": "acc", "business_id": BIZ, "included_in_bookkeeping": True, "deleted_at": None}],
        bills=[_bill("b1", "City Water Dept", 61.25, T - timedelta(days=3), subcategory="Utilities"),
               _bill("b2", "Streamyard", 49.0, T - timedelta(days=2)),
               _bill("b3", "Grace Lawn Care", 300.0, T - timedelta(days=1))],
        plaid_transactions=[
            _tx("t1", T - timedelta(days=1), 61.25, "CITY WATER DEPT AUTOPAY"),                 # waiting
            _tx("t2", T - timedelta(days=2), 49.0, "STREAMYARD.COM", "operating", "Streaming Software"),
            _tx("t3", T - timedelta(days=1), 300.0, "CHECK 1044"),                             # no name
            _tx("t4", T - timedelta(days=1), 300.0, "CHECK 1045"),                             # same amount
            _tx("t5", T - timedelta(days=1), 52.0, "STREAMYARD.COM"),                          # near, named
            _tx("t6", T - timedelta(days=1), 61.25, "TRANSFER", kind="transfer"),              # not an expense
        ],
        expense_categories=[{"id": "c1", "business_id": BIZ, "name": "Utilities", "bucket": "operating", "line": None}],
        expense_lines=[], category_rules=[], business_expenses=[], chief_undo_log=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: True)
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    return fake


def _b(db, bid):
    return next(b for b in db.t["bills"] if b["id"] == bid)


def _t(db, tid):
    return next(t for t in db.t["plaid_transactions"] if t["transaction_id"] == tid)


def _chief(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


# ─── The ledger ──────────────────────────────────────────────────────

def _sum(entries, code, side):
    return round(sum(float(l.get(side) or 0) for e in entries for l in e["lines"] if l["code"] == code), 2)


def test_a_bank_paid_bill_settles_instead_of_paying_cash_twice():
    paid = {"id": "b", "vendor_name": "City Water", "amount": 61.25, "category": "operating", "subcategory": "Utilities",
            "status": "paid", "created_at": "2026-10-01T00:00:00Z", "due_date": "2026-10-10",
            "paid_at": "2026-10-09T12:00:00+00:00", "paid_amount": 61.25, "paid_transaction_id": "t1"}
    bill = gl_engine.desired_for_bill(paid)
    assert [e["source_type"] for e in bill] == ["bill_issue", "bill_settle"]
    bank = gl_engine.desired_for_plaid({"transaction_id": "t1", "account_id": "acc", "amount": 61.25,
                                        "date": "2026-10-09", "business_category": "operating",
                                        "business_subcategory": "Utilities", "money_kind": None})
    both = bill + bank
    assert _sum(both, "5000", "debit") - _sum(both, "5000", "credit") == 61.25        # the expense, once
    assert _sum(both, "2000", "debit") == _sum(both, "2000", "credit") == 61.25        # AP clears
    assert _sum(both, "1000", "credit") == 61.25 and _sum(bill, "1000", "credit") == 0  # cash out once
    by_hand = gl_engine.desired_for_bill({**paid, "paid_transaction_id": None})
    assert [e["source_type"] for e in by_hand] == ["bill_issue", "bill_payment"] and _sum(by_hand, "1000", "credit") == 61.25
    assert "bill_settle" in gl_engine._TABLE_SOURCE_TYPES["bills"]


def test_a_near_amount_settles_the_whole_bill_and_the_books_show_what_was_paid():
    near = {"id": "b", "vendor_name": "Grace Lawn Care", "amount": 100.0, "category": "operating", "subcategory": None,
            "status": "paid", "created_at": "2026-10-01T00:00:00Z", "due_date": "2026-10-10",
            "paid_at": "2026-10-09T12:00:00+00:00", "paid_amount": 95.0, "paid_transaction_id": "t9"}
    both = gl_engine.desired_for_bill(near) + gl_engine.desired_for_plaid(
        {"transaction_id": "t9", "account_id": "acc", "amount": 95.0, "date": "2026-10-09",
         "business_category": "operating", "business_subcategory": None, "money_kind": None})
    assert _sum(both, "2000", "debit") == _sum(both, "2000", "credit") == 100.0          # AP clears
    assert round(_sum(both, "5000", "debit") - _sum(both, "5000", "credit"), 2) == 95.0  # what was spent


# ─── Candidates and the match ────────────────────────────────────────

def test_candidates_by_amount_and_name_and_the_plain_one(db):
    water = bp.candidates(BIZ, _b(db, "b1"))
    assert [c["transaction_id"] for c in water] == ["t1"] and water[0]["exact"] and water[0]["payee"]   # t6 isn't money out
    assert bp.clear_one(water)["transaction_id"] == "t1"
    stream = bp.candidates(BIZ, _b(db, "b2"))
    assert [c["transaction_id"] for c in stream] == ["t2", "t5"]                     # exact first, then near + named
    lawn = bp.candidates(BIZ, _b(db, "b3"))
    assert {c["transaction_id"] for c in lawn} == {"t3", "t4"} and bp.clear_one(lawn) is None   # two checks: ask


def test_the_match_and_its_refusals(db):
    got = bp.match(BIZ, "b1", "t1")
    assert got["ok"], got
    b = _b(db, "b1")
    assert (b["status"], b["paid_via"], b["paid_transaction_id"], b["paid_amount"]) == ("paid", "bank", "t1", 61.25)
    assert (_t(db, "t1")["business_category"], _t(db, "t1")["business_subcategory"]) == ("operating", "Utilities")
    assert not bp.match(BIZ, "b1", "t5")["ok"]                                         # already matched
    assert not bp.match(BIZ, "b2", "t1")["ok"]                                         # t1 already pays a bill
    assert not bp.match(BIZ, "b2", "t6")["ok"]                                         # a transfer pays nothing
    filed = bp.match(BIZ, "b2", "t2")
    assert filed["ok"] and _t(db, "t2")["business_subcategory"] == "Streaming Software"   # a filed row is left
    assert bp.candidates(BIZ, _b(db, "b3")) and all(
        c["transaction_id"] not in ("t1", "t2") for c in bp.candidates(BIZ, _b(db, "b3")))


def test_unmatch_owes_it_again_or_puts_it_back(db):
    bp.match(BIZ, "b1", "t1")
    back = bp.unmatch(BIZ, "b1")
    b = _b(db, "b1")
    assert back["ok"] and (b["status"], b["paid_transaction_id"], b["paid_at"]) == ("overdue", None, None)
    assert _t(db, "t1")["business_category"] == "operating"                           # the filing stands
    by_hand = _b(db, "b3")
    by_hand.update(status="paid", paid_via="manual", paid_at=f"{T}T09:00:00Z", paid_amount=300.0)
    got = bp.match(BIZ, "b3", "t3")
    assert got["ok"] and _b(db, "b3")["paid_via"] == "bank"
    bp.unmatch(BIZ, "b3", got["changes"][0]["before"])
    assert (_b(db, "b3")["status"], _b(db, "b3")["paid_via"]) == ("paid", "manual")


def test_an_undo_puts_back_only_the_payment_fields(db):
    got = bp.match(BIZ, "b1", "t1")
    forged = {"status": "paid", "paid_via": "manual", "paid_at": "2026-01-01", "paid_amount": 1,
              "amount": 1, "business_id": "someone-else", "vendor_name": "X"}
    bp.unmatch(BIZ, "b1", forged)
    b = _b(db, "b1")
    assert (b["amount"], b["business_id"], b["vendor_name"]) == (61.25, BIZ, "City Water Dept")
    assert (b["status"], b["paid_amount"], b["paid_via"]) == ("paid", 1, "manual")      # the four fields, checked
    bp.match(BIZ, "b1", "t5") if False else None
    _b(db, "b1").update(status="pending", paid_at=None, paid_amount=None, paid_via=None)
    assert bp.match(BIZ, "b1", "t1")["ok"]
    bp.unmatch(BIZ, "b1", {"status": "hacked", "paid_via": "bank"})
    assert _b(db, "b1")["status"] == "overdue" and got["ok"]                           # not restorable: owed


def test_a_closed_month_needs_a_reason_and_chief_says_so(db, monkeypatch):
    import importlib
    real = importlib.reload(period_lock)
    monkeypatch.setattr(real, "locked_period", lambda biz, day: {"id": "p1", "period_start": "2026-01-01",
                                                                  "period_end": "2099-12-31"})
    monkeypatch.setattr(real, "lock_mode", lambda biz: "soft")
    logged = []
    monkeypatch.setattr(real, "record_override", lambda *a, **k: logged.append(k))
    with pytest.raises(HTTPException) as e:
        bp.match(BIZ, "b1", "t1", by=OWNER)
    assert e.value.status_code == 409 and _b(db, "b1")["paid_transaction_id"] is None
    assert bp.match(BIZ, "b1", "t1", by=OWNER, reason="paid late, closing fix")["ok"] and logged
    said = _chief(bp.handle_match_bill_payment, {"items": [{"bill_id": "b2", "transaction_id": "t2"}]})
    assert said["failed"] and "closed period" in said["result"]


def test_a_waiting_other_row_is_filed_a_failed_filing_is_said_and_a_null_status_matches(db, monkeypatch):
    _t(db, "t3").update(business_category="other")
    _b(db, "b3").update(status=None, subcategory="Lawn care")
    got = bp.match(BIZ, "b3", "t3")
    assert got["ok"] and _t(db, "t3")["business_subcategory"] == "Lawn care" and not got["note"]
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, *a, **k: None if path.startswith("/plaid_transactions") else real(path, body, *a, **k))
    got = bp.match(BIZ, "b1", "t1")
    assert got["ok"] and "still waits in To review" in got["note"]


def test_chief_filing_never_moves_a_bills_payment_out_of_the_books():
    import chief_file_bank as cf
    row = {"transaction_id": "t1", "name": "CITY WATER DEPT AUTOPAY", "date": "2026-10-09", "direction": "out",
           "amount": 61.25, "business_category": None, "business_subcategory": None, "money_kind": None,
           "excluded_from_books": False}
    for answer in ("transfer", "owner", "personal"):
        changes, problems = cf.plan([row], [{"transaction_ids": ["t1"], "answer": answer}], True, paying={"t1": "b1"})
        assert not changes and "paid a bill" in problems[0], answer
    changes, problems = cf.plan([row], [{"transaction_ids": ["t1"], "answer": "operating", "label": "Utilities"}],
                                True, paying={"t1": "b1"})
    assert changes and not problems                                                     # spending is fine


# ─── The Bills tab's routes ──────────────────────────────────────────

def _client(uid):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_supabase import AuthedUser, require_user
    app = FastAPI()
    app.include_router(bp.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=uid, email="x@y.z", role="authenticated")
    return TestClient(app)


def test_the_routes_are_the_owners_and_only_where_on(db, monkeypatch):
    got = _client(OWNER).get("/bills/b1/bank-matches", params={"biz": BIZ})
    assert got.status_code == 200 and got.json()["clear"] == "t1"
    assert _client(STRANGER).post("/bills/b1/bank-match", json={"business_id": BIZ, "transaction_id": "t1"}).status_code == 403
    made = _client(OWNER).post("/bills/b1/bank-match", json={"business_id": BIZ, "transaction_id": "t1"})
    assert made.status_code == 200 and "counts once" in made.json()["said"]
    again = _client(OWNER).post("/bills/b2/bank-match", json={"business_id": BIZ, "transaction_id": "t1"})
    assert again.status_code == 409 and "already paid another bill" in again.json()["detail"]
    undone = _client(OWNER).post("/bills/b1/bank-unmatch", json={"business_id": BIZ})
    assert undone.status_code == 200 and _b(db, "b1")["paid_transaction_id"] is None
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: False)
    off = _client(OWNER).get("/bills/b1/bank-matches", params={"biz": BIZ})
    assert off.status_code == 403 and "switched on" in off.json()["detail"]


# ─── Chief ───────────────────────────────────────────────────────────

def test_chief_matches_the_plain_ones_and_one_undo_takes_them_back(db):
    look = _chief(chief_bills.handle_bills, {})
    paid_by = {b["vendor"]: b.get("looks_paid_by", {}).get("transaction_id") for b in look["owed"]}
    assert paid_by == {"City Water Dept": "t1", "Streamyard": "t2", "Grace Lawn Care": None}
    got = _chief(bp.handle_match_bill_payment, {"clear": True})
    assert not got.get("failed") and {m["bill_id"] for m in got["matched"]} == {"b1", "b2"}, got
    assert _b(db, "b3")["status"] == "pending"                                          # two checks: asked, not taken
    inv = action_inverse.build_inverse("match_bill_payment", {}, got)
    back = _chief(bp.handle_unmatch_bill_payment, inv)
    assert not back.get("failed") and all(_b(db, b)["paid_transaction_id"] is None for b in ("b1", "b2"))
    assert _chief(bp.handle_match_bill_payment, {"clear": True}, who=STRANGER)["failed"]
    one = _chief(bp.handle_match_bill_payment, {"items": [{"bill_id": "b3", "transaction_id": "t4"}]})
    assert not one.get("failed") and _b(db, "b3")["paid_transaction_id"] == "t4"


def test_the_verbs_are_wired():
    import chief_areas
    import chief_prompt
    for verb in ("match_bill_payment", "unmatch_bill_payment"):
        assert verb in cos.ACTION_HANDLERS and action_registry.REGISTRY[verb]["chief_only"] is True
        assert verb in str(chief_areas.__dict__)
    src = open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
    assert '"type":"match_bill_payment"' in src and '"type":"unmatch_bill_payment"' in src


# ─── Guards elsewhere ────────────────────────────────────────────────

def test_a_bills_bank_payment_stays_in_the_books_and_a_rename_moves_bills(db, monkeypatch):
    from auth_supabase import AuthedUser
    monkeypatch.setattr(plaid_router, "_require_money_writer_for_tx",
                        lambda tid, user: {"transaction_id": tid, "business_id": BIZ})
    bp.match(BIZ, "b1", "t1")
    owner = AuthedUser(id=OWNER, email="x@y.z", role="authenticated")
    with pytest.raises(HTTPException) as e:
        plaid_router.update_transaction("t1", plaid_router.TxPatchBody(money_kind="transfer"), owner)
    assert e.value.status_code == 409 and "City Water Dept bill" in e.value.detail
    with pytest.raises(HTTPException):
        plaid_router.update_transaction("t1", plaid_router.TxPatchBody(excluded_from_books=True), owner)
    token = cos._TURN_USER_ID.set(OWNER)
    try:
        monkeypatch.setattr(plaid_router, "_require_owner", lambda biz, user: {"id": BIZ, "owner_id": OWNER})
        monkeypatch.setattr(plaid_router, "_require_money_writer", lambda biz, user: {"id": BIZ, "owner_id": OWNER})
        got = ec.set_category(BIZ, {"category": "Utilities", "name": "Utilities & water"})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert not got.get("failed"), got
    assert _b(db, "b1")["subcategory"] == "Utilities & water"
