"""
test_chief_adds_bills.py — Chief adds the bills the owner asks for, and
suggests recurring ones from what the bank shows is paid every month (Bills
step 3). Made-up figures.

Kevin, 2026-11-01: the categories Chief made should work under the Bills tab.

Pins:
  * add: a one-time bill under a saved category takes its spelling and line;
    a bill a bank payment already fits says so (match it, counts once)
  * recurring: starts at its next due date, never in the past, so the Bills
    tab makes no copies for months already paid
  * could_be_bills: monthly payees not yet a recurring bill, with the next due
    date; irregular or already-covered payees aren't offered
  * undo / remove: an owed, unmatched bill goes; a paid one stays; a closed
    month refuses; only the owner, only where on
  * the verbs are wired
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
import chief_bills  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_transactions  # noqa: E402
import period_lock  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
STRANGER = "00000000-0000-4000-8000-000000000009"
T = date.today()


def _tx(tid, on, amount, name, cat="operating", sub=None):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc", "date": on.isoformat(), "name": name,
            "merchant_name": None, "amount": amount, "pending": False, "excluded_from_books": False,
            "money_kind": None, "business_category": cat, "business_subcategory": sub}


@pytest.fixture
def db(monkeypatch):
    stream = [_tx(f"s{i}", T - timedelta(days=90 - 30 * i), 49.0, "STREAMYARD.COM", sub="Streaming Software")
              for i in range(4)]                                       # every 30 days, the last today
    fake = FakeDB(
        businesses=[{"id": BIZ, "type": "ministry", "owner_id": OWNER}],
        plaid_accounts=[{"account_id": "acc", "business_id": BIZ, "included_in_bookkeeping": True, "deleted_at": None}],
        plaid_transactions=stream + [
            _tx("w1", T - timedelta(days=5), 61.25, "CITY WATER DEPT AUTOPAY", sub="Utilities"),
            _tx("a1", T - timedelta(days=80), 20.0, "AMAZON MKTPL"),            # irregular
            _tx("a2", T - timedelta(days=12), 210.0, "AMAZON MKTPL"),
            _tx("a3", T - timedelta(days=9), 15.0, "AMAZON MKTPL"),
            _tx("r1", T - timedelta(days=61), 1200.0, "GRACE PROPERTY RENT"),   # monthly, but already a bill
            _tx("r2", T - timedelta(days=31), 1200.0, "GRACE PROPERTY RENT"),
            _tx("r3", T - timedelta(days=1), 1200.0, "GRACE PROPERTY RENT"),
        ],
        bills=[{"id": "rent", "business_id": BIZ, "vendor_name": "Grace Property", "amount": 1200, "status": "paid",
                "category": "operating", "subcategory": "Rent", "due_date": (T - timedelta(days=60)).isoformat(),
                "is_recurring": True, "recurrence_frequency": "monthly", "recurrence_parent_id": None,
                "recurrence_start": (T - timedelta(days=60)).isoformat(), "recurrence_paused": False,
                "paid_transaction_id": None, "created_at": f"{T - timedelta(days=60)}T00:00:00Z"}],
        expense_categories=[{"id": "c1", "business_id": BIZ, "name": "Utilities", "bucket": "operating", "line": None},
                            {"id": "c2", "business_id": BIZ, "name": "Streaming Software", "bucket": "operating",
                             "line": None}],
        expense_lines=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: True)
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    return fake


def _run(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


def _bill(db, bid):
    return next(b for b in db.t["bills"] if b["id"] == bid)


def test_a_one_time_bill_takes_the_saved_category_and_says_when_its_already_paid(db):
    got = _run(chief_bills.handle_add_bill, {"vendor": "City Water Dept", "amount": 61.25,
                                             "due_date": (T - timedelta(days=4)).isoformat(), "category": "utilities"})
    assert not got.get("failed"), got
    b = _bill(db, got["bill_id"])
    assert (b["category"], b["subcategory"], b["is_recurring"], b["status"]) == ("operating", "Utilities", False, "pending")
    assert "Ministry & operations, Utilities" in got["result"]                       # the church's line name
    assert got["looks_paid_by"]["transaction_id"] == "w1" and "offer to match it" in got["result"]


def test_a_recurring_bill_starts_at_its_next_due_date(db):
    start = T - timedelta(days=70)
    got = _run(chief_bills.handle_add_bill, {"vendor": "Streamyard", "amount": 49, "due_date": start.isoformat(),
                                             "every": "monthly", "category": "Streaming Software"})
    assert not got.get("failed"), got
    b = _bill(db, got["bill_id"])
    assert b["is_recurring"] and date.fromisoformat(b["due_date"]) >= T
    assert b["recurrence_start"] == b["due_date"] and "already paid from the bank" in got["result"]
    bad = _run(chief_bills.handle_add_bill, {"vendor": "X", "amount": 5, "due_date": T.isoformat(), "every": "daily"})
    assert bad["failed"]
    assert _run(chief_bills.handle_add_bill, {"vendor": "X", "amount": 0, "due_date": T.isoformat()})["failed"]


def test_could_be_bills_offers_monthly_payees_not_yet_bills(db):
    look = _run(chief_bills.handle_bills, {})
    maybe = {m["payee_key"]: m for m in look["could_be_bills"]}
    assert set(maybe) == {"streamyard com"}, maybe                                    # not Amazon, not the rent
    s = maybe["streamyard com"]
    assert (s["amount"], s["every"], s["times"], s["category"]) == (49.0, "monthly", 4, "Streaming Software")
    assert date.fromisoformat(s["next_due"]) >= T and "could_be_bills" in look["result"]


def test_undo_removes_an_owed_bill_and_a_paid_one_stays(db, monkeypatch):
    got = _run(chief_bills.handle_add_bill, {"vendor": "Sign Co", "amount": 640, "due_date": (T + timedelta(days=9)).isoformat()})
    inv = action_inverse.build_inverse("add_bill", {}, got)
    assert inv == {"type": "remove_bill", "bill_id": got["bill_id"]}
    gone = _run(chief_bills.handle_remove_bill, inv)
    assert not gone.get("failed") and not any(b["id"] == got["bill_id"] for b in db.t["bills"])
    stays = _run(chief_bills.handle_remove_bill, {"bill_id": "rent"})
    assert stays["failed"] and "stays" in stays["result"] and _bill(db, "rent")
    again = _run(chief_bills.handle_add_bill, {"vendor": "Sign Co", "amount": 640, "due_date": (T + timedelta(days=9)).isoformat()})

    def closed(*a, **k):
        raise HTTPException(409, {"message": "This is in a closed period (2026-10-01–2026-10-31)."})
    monkeypatch.setattr(period_lock, "guard", closed)
    locked = _run(chief_bills.handle_remove_bill, {"bill_id": again["bill_id"]})
    assert locked["failed"] and "closed period" in locked["result"] and _bill(db, again["bill_id"])


def test_a_recurring_bills_first_copy_offers_the_match_too(db):
    got = _run(chief_bills.handle_add_bill, {"vendor": "City Water Dept", "amount": 61.25, "every": "monthly",
                                             "due_date": (T + timedelta(days=10)).isoformat(), "category": "Utilities"})
    assert not got.get("failed") and got["looks_paid_by"]["transaction_id"] == "w1"   # paid 5 days ago, due in 10


def test_failures_are_said_never_half_done_in_silence(db, monkeypatch):
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, *a, **k: None)
    got = _run(chief_bills.handle_add_bill, {"vendor": "X", "amount": 5, "due_date": T.isoformat()})
    assert got["failed"] and "didn't save" in got["result"]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    db.t["bills"] += [{"id": "tpl", "business_id": BIZ, "vendor_name": "Lawn", "amount": 50, "status": "pending",
                       "is_recurring": True, "recurrence_parent_id": None, "paid_transaction_id": None,
                       "created_at": f"{T}T00:00:00Z", "due_date": T.isoformat()},
                      {"id": "k1", "business_id": BIZ, "vendor_name": "Lawn", "amount": 50, "status": "pending",
                       "is_recurring": False, "recurrence_parent_id": "tpl", "paid_transaction_id": None,
                       "created_at": f"{T}T00:00:00Z", "due_date": T.isoformat()}]
    calls = {"n": 0}

    def flaky(path, *a, **k):
        calls["n"] += 1
        return db.delete(path) if calls["n"] == 1 else False         # the copy goes, the bill fails
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", flaky)
    half = _run(chief_bills.handle_remove_bill, {"bill_id": "tpl"})
    assert half["failed"] and "only 1 of the 2" in half["result"] and _bill(db, "tpl")
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/plaid_transactions") else db.get(path))
    look = _run(chief_bills.handle_bills, {})
    assert not look.get("failed") and look["could_be_bills"] == []                   # a suggestion never breaks it
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/bills") else db.get(path))
    gone = _run(chief_bills.handle_remove_bill, {"bill_id": "tpl"})
    assert gone["failed"] and "nothing was removed" in gone["result"]


def test_only_the_owner_and_only_where_on(db, monkeypatch):
    import bills_router

    def owner(biz, user):
        if str(user.id) != OWNER:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "owner_id": OWNER}
    monkeypatch.setattr(bills_router, "_owner", owner)
    ask = {"vendor": "X", "amount": 5, "due_date": T.isoformat()}
    assert _run(chief_bills.handle_add_bill, ask, who=STRANGER)["failed"]
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: False)
    got = _run(chief_bills.handle_add_bill, ask)
    assert got["failed"] and "switched on" in got["result"]


def test_the_verbs_are_wired():
    import chief_areas
    import chief_prompt
    for verb in ("add_bill", "remove_bill"):
        assert verb in cos.ACTION_HANDLERS and action_registry.REGISTRY[verb]["chief_only"] is True
        assert verb in str(chief_areas.__dict__)
    src = open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
    assert '"type":"add_bill"' in src and '"type":"remove_bill"' in src
