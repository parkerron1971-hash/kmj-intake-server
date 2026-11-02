"""
test_expense_lines.py — a business's own names for the lines of its books, and
lines of its own. Made-up figures.

Kevin, 2026-11-01: "build option 1 with church names as default but allow for
them to be changed because other business would want different names also
allow for there to be added more to this list."

Pins:
  * off: the standard five names, no reads, the P&L as it was
  * a church starts with church names, anyone else the standard ones
  * renaming a built-in line, then again; one undo puts the default back
  * adding a line on a base; a category on it keeps the base's bucket; the
    P&L shows the line as its own section and the totals don't move
  * moving a category to a line of another base moves its rows' bucket
  * removing an added line sends its categories back; undo restores both;
    the five can't be removed; names can't clash
  * the card's routes: readers read, the owner changes, only where on
  * Chief's verb is wired
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys
from types import SimpleNamespace

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
import chief_of_staff as cos  # noqa: E402
import chief_transactions  # noqa: E402
import expense_categories as ec  # noqa: E402
import expense_lines as el  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
Y = 2026


def _tx(tid, amount, name, cat="operating", sub=None):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc", "date": f"{Y}-03-05", "name": name,
            "merchant_name": None, "amount": amount, "pending": False, "excluded_from_books": False,
            "business_category": cat, "business_subcategory": sub, "money_kind": None,
            "plaid_category_primary": None, "plaid_category_detail": None}


def _db(monkeypatch, kind="ministry", on=True):
    fake = FakeDB(
        businesses=[{"id": BIZ, "type": kind, "owner_id": OWNER}],
        plaid_accounts=[{"account_id": "acc", "business_id": BIZ, "name": "Checking", "mask": "0000",
                         "type": "depository", "included_in_bookkeeping": True, "deleted_at": None,
                         "is_trust_account": False}],
        plaid_transactions=[_tx("p1", 120, "DUKE ENERGY", sub="Utilities"),
                            _tx("p2", 50, "AIRLINE", sub="Mission trips"),
                            _tx("p3", 75, "AIRLINE", sub="Mission trips")],
        business_expenses=[], category_rules=[], expense_categories=[], expense_lines=[], chief_undo_log=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setattr(bo, "_get_all", lambda path, cap=0: bo._get(path))
    monkeypatch.setattr(bank_money, "state", lambda: True)
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: on)

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


@pytest.fixture
def db(monkeypatch):
    return _db(monkeypatch)


def _run(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


def _log(db, result):
    db.t["chief_undo_log"].append({"id": f"u{len(db.t['chief_undo_log'])}", "business_id": BIZ,
                                   "action_type": result["type"], "status": "undoable",
                                   "created_at": "2099-01-01T00:00:00Z", "result_json": result})


def _undo(db, got):
    _log(db, got)
    return _run(ec.handle_undo_category_change, action_inverse.build_inverse(got["type"], {}, got))


def _names():
    return [ln["name"] for ln in el.lines(BIZ)]


def _pl(by_bucket):
    total = round(sum(b["total"] for b in by_bucket), 2)
    return {"current": {"expenses": {"total": total, "by_bucket": by_bucket}}}


# ─── Names ───────────────────────────────────────────────────────────

def test_off_answers_the_standard_five_and_leaves_the_report_alone(monkeypatch):
    fake = _db(monkeypatch, on=False)
    fake.t["expense_lines"].append({"id": "x", "business_id": BIZ, "key": "operating", "base": "operating",
                                    "name": "Ministry"})
    assert _names() == ["Operating", "Owner pay", "Tax", "Savings", "Other"]
    pl = _pl([{"bucket": "operating", "label": "Operating", "total": 10.0, "pct": 100.0,
               "lines": [{"subcategory": "Utilities", "amount": 10.0}]}])
    assert el.present(BIZ, copy.deepcopy(pl)) == pl


def test_a_church_starts_with_church_names_and_anyone_else_the_standard(monkeypatch):
    _db(monkeypatch)
    assert _names() == ["Ministry & operations", "Pastor & staff pay", "Taxes", "Reserves", "Other"]
    _db(monkeypatch, kind="barbershop")
    assert _names() == ["Operating", "Owner pay", "Tax", "Savings", "Other"]


def test_renaming_a_built_in_line_and_one_undo_puts_the_default_back(db):
    got = _run(ec.handle_set_expense_line, {"line": "Reserves", "name": "Building fund"})
    assert not got.get("failed"), got
    assert _names()[3] == "Building fund"
    again = _run(ec.handle_set_expense_line, {"line": "savings", "name": "Rainy day"})
    assert not again.get("failed") and _names()[3] == "Rainy day"
    assert len([r for r in db.t["expense_lines"] if not r.get("archived_at")]) == 1    # one row, patched
    back = _undo(db, again)
    assert not back.get("failed") and _names()[3] == "Building fund"
    back = _undo(db, got)
    assert not back.get("failed") and _names()[3] == "Reserves"                        # the church default


# ─── Added lines ─────────────────────────────────────────────────────

def test_an_added_line_carries_its_categories_into_its_own_pl_section(db):
    got = _run(ec.handle_set_expense_line, {"name": "Missions", "base": "Ministry & operations"})
    assert not got.get("failed") and "counts as Ministry & operations" in got["result"]
    assert _names() == ["Ministry & operations", "Missions", "Pastor & staff pay", "Taxes", "Reserves", "Other"]
    made = _run(ec.handle_set_expense_category, {"name": "Mission trips", "line": "missions"})
    assert not made.get("failed") and "under Missions" in made["result"]
    cat = ec.categories(BIZ)[0]
    assert cat["bucket"] == "operating" and cat["line"].startswith("l_")              # the books: Operating
    pic = ec.picture(BIZ, Y)
    assert pic["categories"][0]["line"] == cat["line"] and [ln["name"] for ln in pic["lines"]][1] == "Missions"

    pl = _pl([{"bucket": "operating", "label": "Operating", "total": 245.0, "pct": 80.0,
               "lines": [{"subcategory": "Utilities", "amount": 120.0}, {"subcategory": "Mission trips", "amount": 125.0}]},
              {"bucket": "tax", "label": "Tax", "total": 61.25, "pct": 20.0,
               "lines": [{"subcategory": "Payroll taxes", "amount": 61.25}]}])
    out = el.present(BIZ, pl)["current"]["expenses"]
    secs = [(s["label"], s["bucket"], s["total"]) for s in out["by_bucket"]]
    assert secs == [("Ministry & operations", "operating", 120.0), ("Missions", "operating", 125.0),
                    ("Taxes", "tax", 61.25)]
    assert out["total"] == 306.25 and round(sum(s["pct"] for s in out["by_bucket"]), 0) == 100
    # Not split (the overview's five): named, nothing moved.
    flat = el.present(BIZ, _pl([{"bucket": "operating", "label": "Operating", "total": 245.0, "pct": 100.0,
                                 "lines": [{"subcategory": "Mission trips", "amount": 245.0}]}]), split=False)
    assert [(s["label"], s["total"]) for s in flat["current"]["expenses"]["by_bucket"]] == [("Ministry & operations", 245.0)]


def test_moving_a_category_to_a_line_on_another_base_moves_its_rows(db):
    _run(ec.handle_set_expense_line, {"name": "Missions", "base": "operating"})
    _run(ec.handle_set_expense_category, {"name": "Mission trips", "bucket": "operating"})
    to_line = _run(ec.handle_set_expense_category, {"category": "Mission trips", "line": "Missions"})
    assert not to_line.get("failed"), to_line
    assert ec.categories(BIZ)[0]["line"].startswith("l_")
    to_tax = _run(ec.handle_set_expense_category, {"category": "Mission trips", "line": "Taxes"})
    assert not to_tax.get("failed"), to_tax
    c = ec.categories(BIZ)[0]
    assert (c["bucket"], c["line"]) == ("tax", None)
    assert {t["business_category"] for t in db.t["plaid_transactions"] if t["business_subcategory"] == "Mission trips"} == {"tax"}
    nothing = _run(ec.handle_set_expense_category, {"category": "Mission trips", "line": "Taxes"})
    assert nothing["failed"]
    unknown = _run(ec.handle_set_expense_category, {"category": "Mission trips", "line": "Nowhere"})
    assert unknown["failed"] and "no line called" in unknown["result"]


def test_removing_an_added_line_sends_its_categories_back_and_undo_restores_both(db):
    _run(ec.handle_set_expense_line, {"name": "Missions", "base": "operating"})
    _run(ec.handle_set_expense_category, {"name": "Mission trips", "line": "Missions"})
    key = ec.categories(BIZ)[0]["line"]
    gone = _run(ec.handle_set_expense_line, {"line": "Missions", "remove": True})
    assert not gone.get("failed") and "went back under Ministry & operations" in gone["result"]
    assert "Missions" not in _names() and ec.categories(BIZ)[0]["line"] is None
    back = _undo(db, gone)
    assert not back.get("failed"), back
    assert "Missions" in _names() and ec.categories(BIZ)[0]["line"] == key


def test_the_five_stay_and_names_never_clash(db):
    stays = _run(ec.handle_set_expense_line, {"line": "Taxes", "remove": True})
    assert stays["failed"] and "stays" in stays["result"]
    _run(ec.handle_set_expense_line, {"name": "Missions", "base": "operating"})
    assert _run(ec.handle_set_expense_line, {"name": "missions", "base": "tax"})["failed"]
    assert _run(ec.handle_set_expense_line, {"line": "Reserves", "name": "Missions"})["failed"]
    assert _run(ec.handle_set_expense_line, {"name": "Savings", "base": "tax"})["failed"]   # a built-in's own name
    assert _run(ec.handle_set_expense_line, {"line": "Nowhere", "name": "X"})["failed"]
    assert _run(ec.handle_set_expense_line, {"name": "Anything"}, who=READER)["failed"]


# ─── A failed read or write is never "no lines" or "done" ────────────

def test_an_unreadable_lines_table_is_said_never_shown_as_no_lines(db, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/expense_lines") else real(path, *a, **k))
    with pytest.raises(el.Unavailable):
        el.lines(BIZ, strict=True)
    assert _names() == ["Operating", "Owner pay", "Tax", "Savings", "Other"]     # a label: the standard names
    got = _run(ec.handle_set_expense_line, {"name": "Missions", "base": "operating"})
    assert got["failed"] and "nothing changed" in got["result"] and db.t["expense_lines"] == []
    pl = _pl([{"bucket": "operating", "label": "Operating", "total": 10.0, "pct": 100.0,
               "lines": [{"subcategory": "Utilities", "amount": 10.0}]}])
    assert el.present(BIZ, copy.deepcopy(pl)) == pl                                # the report untouched
    with pytest.raises(ec.Unavailable):
        ec.picture(BIZ, Y)                                                          # the card says it didn't load


def test_a_removal_that_fails_partway_records_what_moved_and_keeps_the_line(db, monkeypatch):
    _run(ec.handle_set_expense_line, {"name": "Missions", "base": "operating"})
    _run(ec.handle_set_expense_category, {"name": "Mission trips", "line": "Missions"})
    _run(ec.handle_set_expense_category, {"name": "Short-term teams", "line": "Missions"})
    real, calls = sb_clients.sb_patch_as_service, {"n": 0}

    def flaky(path, body, *a, **k):
        if path.startswith("/expense_categories"):
            calls["n"] += 1
            if calls["n"] == 2:
                return None                                  # the second category's write fails
        return real(path, body, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", flaky)
    got = _run(ec.handle_set_expense_line, {"line": "Missions", "remove": True})
    assert not got.get("failed") and got.get("partial") and "Partway through removing Missions" in got["result"]
    assert len(got["changes"]) == 1 and "Missions" in _names()                     # the line stands
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", real)
    again = _run(ec.handle_set_expense_line, {"line": "Missions", "remove": True})  # asking again finishes
    assert not again.get("failed") and "Missions" not in _names()
    assert all(c["line"] is None for c in ec.categories(BIZ))


# ─── The card ────────────────────────────────────────────────────────

def _client(uid):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_supabase import AuthedUser, require_user
    app = FastAPI()
    app.include_router(ec.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=uid, email="x@y.z", role="authenticated")
    return TestClient(app)


def test_the_card_reads_lines_and_only_the_owner_changes_them(db, monkeypatch):
    got = _client(READER).get("/expense-categories/lines", params={"business_id": BIZ})
    assert got.status_code == 200 and got.json()["lines"][0]["name"] == "Ministry & operations"
    assert got.json()["can_change"] is False and got.json()["card"] is True
    ask = {"business_id": BIZ, "name": "Missions", "base": "operating"}
    assert _client(READER).post("/expense-categories/lines", json=ask).status_code == 403
    made = _client(OWNER).post("/expense-categories/lines", json=ask)
    assert made.status_code == 200 and made.json()["batch_id"], made.text
    db.t["chief_undo_log"][-1]["created_at"] = "2099-01-01T00:00:00Z"
    assert db.t["chief_undo_log"][-1]["action_type"] == "set_expense_line"
    cat = _client(OWNER).post("/expense-categories", json={"business_id": BIZ, "name": "Mission trips", "line": "Missions"})
    assert cat.status_code == 200 and cat.json()["category"]["line"].startswith("l_")
    undo = _client(OWNER).post("/expense-categories/undo", json={"business_id": BIZ, "batch_id": made.json()["batch_id"]})
    assert undo.status_code == 200 and "Missions" not in _names()
    assert _client(OWNER).post("/expense-categories/lines", json={"business_id": BIZ}).status_code == 422
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: False)
    assert _client(OWNER).post("/expense-categories/lines", json=ask).status_code == 403
    off = _client(OWNER).get("/expense-categories/lines", params={"business_id": BIZ}).json()
    assert off["card"] is False and off["lines"][0]["name"] == "Operating"


def test_the_verb_is_wired():
    import chief_areas
    import chief_prompt
    assert cos.ACTION_HANDLERS["set_expense_line"] is ec.handle_set_expense_line
    assert action_registry.REGISTRY["set_expense_line"]["chief_only"] is True
    assert action_inverse.build_inverse("set_expense_line", {}, {"batch_id": "a" * 32, "changes": [{}]}) == \
        {"type": "undo_category_change", "batch_id": "a" * 32}
    assert "set_expense_line" in str(chief_areas.__dict__)
    src = open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
    assert '"type":"set_expense_line"' in src
