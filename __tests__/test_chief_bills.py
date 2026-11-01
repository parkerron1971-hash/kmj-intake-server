"""
test_chief_bills.py — Chief reads the Bills tab, and a bill files under the
business's saved categories. Made-up figures.

Kevin, 2026-11-01: "want to see if it could put under bill tab as well. it
doesn't see the bill tab."

Pins:
  * the lookup: owed (a recurring bill's first copy included), overdue (said,
    never written), due in 30 days, recurring with the next due date, paid in
    the last 30 days, the total; each bill's line by the business's names
  * an empty tab says so; a failed read is never "no bills"
  * only readers of the Bills tab, only where switched on
  * a bill under a saved category takes its spelling and its line, on create
    and on edit; anything else is kept as typed
  * the lookup is wired
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

import action_registry  # noqa: E402
import bills_router  # noqa: E402
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


def _bill(bid, vendor, amount, due, status="pending", **kw):
    return {"id": bid, "business_id": BIZ, "vendor_name": vendor, "amount": amount, "category": "operating",
            "subcategory": None, "status": status, "due_date": due.isoformat() if due else None, "paid_at": None,
            "paid_amount": None, "is_recurring": False, "recurrence_frequency": None, "recurrence_start": None,
            "recurrence_paused": False, "recurrence_parent_id": None, **kw}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "type": "ministry", "owner_id": OWNER}],
        bills=[
            _bill("b1", "Grace Lawn Care", 300, T - timedelta(days=5)),                 # late, still 'pending'
            _bill("b2", "City Water", 61.25, T + timedelta(days=10), subcategory="Utilities"),
            _bill("b3", "Sign Co", 640, T + timedelta(days=60)),
            _bill("b4", "Streamyard", 49, T - timedelta(days=40), is_recurring=True, recurrence_frequency="monthly",
                  recurrence_start=(T - timedelta(days=40)).isoformat(), category="operating",
                  subcategory="Streaming Software"),
            _bill("b5", "Old Printer", 80, T - timedelta(days=20), status="paid",
                  paid_at=(T - timedelta(days=3)).isoformat() + "T12:00:00Z"),
        ],
        expense_categories=[{"id": "c1", "business_id": BIZ, "name": "Utilities", "bucket": "operating", "line": None},
                            {"id": "c2", "business_id": BIZ, "name": "Payroll taxes", "bucket": "tax", "line": None}],
        expense_lines=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: True)
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    return fake


def _run(who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(chief_bills.handle_bills(None, {"id": BIZ, "owner_id": OWNER}, {}))
    finally:
        cos._TURN_USER_ID.reset(token)


def test_the_lookup_reads_the_bills_tab_without_writing(db):
    got = _run()
    assert not got.get("failed"), got
    assert {b["vendor"] for b in got["owed"]} == {"Grace Lawn Care", "City Water", "Sign Co", "Streamyard"}
    assert got["total_owed"] == 1050.25 and got["overdue"] == 2 and got["due_30_days"] == 1 and got["paid_30_days"] == 1
    water = next(b for b in got["owed"] if b["vendor"] == "City Water")
    assert water["line"] == "Ministry & operations, Utilities"                       # the church's own names
    stream = got["recurring"][0]
    assert stream["every"] == "monthly" and date.fromisoformat(stream["next_due"]) >= T
    assert "Overdue: Streamyard $49.00" in got["result"] and "Grace Lawn Care $300.00 (due" in got["result"]
    assert next(b for b in db.t["bills"] if b["id"] == "b1")["status"] == "pending"   # said, never written


def test_ended_cancelled_or_paused_recurring_bills_have_no_next_due(db):
    base = dict(is_recurring=True, recurrence_frequency="monthly", recurrence_start=(T - timedelta(days=90)).isoformat())
    db.t["bills"] += [
        _bill("r1", "Ended Co", 10, T - timedelta(days=90), recurrence_end_type="on_date",
              recurrence_end_value=(T - timedelta(days=1)).isoformat(), **base),
        _bill("r2", "Counted Co", 10, T - timedelta(days=90), recurrence_end_type="after_count",
              recurrence_end_value="2", **base),
        _bill("r3", "Paused Co", 10, T - timedelta(days=90), recurrence_paused=True, **base),
        _bill("r4", "Cancelled Co", 10, T - timedelta(days=90), status="cancelled", **base),
    ]
    rec = {r["vendor"]: r for r in _run()["recurring"]}
    assert "Cancelled Co" not in rec
    assert rec["Ended Co"]["next_due"] is None and rec["Counted Co"]["next_due"] is None
    assert rec["Paused Co"]["next_due"] is None and rec["Streamyard"]["next_due"]


def test_a_bill_under_a_category_on_an_added_line_shows_on_that_line(db):
    db.t["expense_lines"].append({"id": "x", "business_id": BIZ, "key": "l_0000abcd", "base": "operating",
                                  "name": "Missions", "created_at": "2026-01-01T00:00:00Z"})
    db.t["expense_categories"].append({"id": "c3", "business_id": BIZ, "name": "Mission trips", "bucket": "operating",
                                       "line": "l_0000abcd"})
    db.t["bills"].append(_bill("m1", "Airline", 500, T + timedelta(days=3), subcategory="Mission trips"))
    trip = next(b for b in _run()["owed"] if b["vendor"] == "Airline")
    assert trip["line"] == "Missions, Mission trips"


def test_an_empty_tab_says_so_and_a_failed_read_is_never_no_bills(db, monkeypatch):
    db.t["bills"] = []
    assert "The Bills tab is empty" in _run()["result"]
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/bills") else db.get(path))
    got = _run()
    assert got["failed"] and "not 'no bills'" in got["result"]


def test_only_its_readers_and_only_where_switched_on(db, monkeypatch):
    def reader(biz, user):
        if str(user.id) != OWNER:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "owner_id": OWNER}
    monkeypatch.setattr(bills_router, "_reader", reader)
    assert _run(STRANGER)["failed"]
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: False)
    got = _run()
    assert got["failed"] and "switched on" in got["result"]


def test_a_bill_under_a_saved_category_takes_its_spelling_and_line(db, monkeypatch):
    from auth_supabase import AuthedUser
    owner = AuthedUser(id=OWNER, email="x@y.z", role="authenticated")
    made = bills_router.create_bill(bills_router.BillBody(
        business_id=BIZ, vendor_name="IRS", amount=200, category="operating", subcategory="payroll  Taxes"), owner)
    assert (made["bill"]["category"], made["bill"]["subcategory"]) == ("tax", "Payroll taxes")
    typed = bills_router.create_bill(bills_router.BillBody(
        business_id=BIZ, vendor_name="Florist", amount=30, subcategory="Flowers"), owner)
    assert (typed["bill"]["category"], typed["bill"]["subcategory"]) == ("operating", "Flowers")
    bid = typed["bill"]["id"]
    bills_router.update_bill(bid, bills_router.BillPatchBody(business_id=BIZ, subcategory="utility"), owner)
    row = next(b for b in db.t["bills"] if b["id"] == bid)
    assert (row["category"], row["subcategory"]) == ("operating", "Utilities")
    # An unreadable list keeps what was typed.
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/expense_categories") else db.get(path))
    kept = bills_router.create_bill(bills_router.BillBody(
        business_id=BIZ, vendor_name="IRS", amount=10, subcategory="payroll  Taxes"), owner)
    assert kept["bill"]["subcategory"] == "payroll  Taxes"


def test_the_lookup_is_wired():
    import chief_areas
    import chief_prompt
    import chief_tool_loop
    assert cos.ACTION_HANDLERS["bills"] is chief_bills.handle_bills
    assert action_registry.REGISTRY["bills"]["chief_only"] is True
    assert "bills" in {t["name"] for t in chief_tool_loop.read_tool_definitions()}
    assert "bills" in str(chief_areas.__dict__)
    assert "the bills lookup" in open(chief_prompt.__file__, encoding="utf-8").read()
