"""
test_expense_categories.py — a business's own expense categories, Chief's
suggestions of where a payment goes, and remembering it. Made-up figures.

Kevin, 2026-10-31: "can chief make expense catagories if i request it so
transactions can go under there?" then "allow for chief to have suggestions
on where things go ... do you want me to save this in my memory so I know to
add this in the future".

Pins:
  * one spelling per name: 'Utilities', 'utilities ', 'Utility' are one
  * make, rename (rows and rules move), merge (and the old one archived);
    one undo puts it back, skipping a row changed since
  * the year's totals per category, and labels in use not on the list
  * filing under a saved category takes its line, its bucket and its
    spelling; moving filed rows between categories, guarded
  * suggestions: a rule for the payee, or how it was filed before
  * remembering: a rule by the payee's wording that the bank feed and
    statements apply; one undo forgets it
  * readers read, the owner changes; the wiring holds
  * the card: rename, a new bucket, merge (a label not on the list too),
    its Undo button through Chief's undo log; owner only, where switched on
"""
from __future__ import annotations

import asyncio
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
import chief_file_bank as cf  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_transactions  # noqa: E402
import expense_categories as ec  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
Y = 2026


def _tx(tid, on, amount, name, cat="other", sub=None, kind=None):
    return {"transaction_id": tid, "business_id": BIZ, "account_id": "acc", "date": on, "name": name,
            "merchant_name": None, "amount": amount, "pending": False, "excluded_from_books": False,
            "business_category": cat, "business_subcategory": sub, "money_kind": kind,
            "plaid_category_primary": None, "plaid_category_detail": None,
            "reconciliation_status": "unmatched", "reconciled_to_payout_id": None}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        plaid_accounts=[{"account_id": "acc", "business_id": BIZ, "name": "Checking", "mask": "0000", "type": "depository",
                         "included_in_bookkeeping": True, "deleted_at": None, "is_trust_account": False}],
        plaid_transactions=[
            # Filed before: Duke Energy went under Utilities, twice.
            _tx("p1", f"{Y}-01-05", 120, "DUKE ENERGY UTIL PYMT", "operating", "Utilities"),
            _tx("p2", f"{Y}-02-05", 130, "DUKE ENERGY UTIL PYMT", "operating", "Utilities"),
            _tx("p3", f"{Y}-02-09", 40, "OFFICE DEPOT", "operating", "Office supplies"),
            _tx("p4", f"{Y}-02-11", 25, "STAPLES", "operating", "office supply"),
            # Waiting.
            _tx("w1", f"{Y}-03-05", 125, "DUKE ENERGY UTIL PYMT"),
            _tx("w2", f"{Y}-03-06", 36, "OVERDRAFT FEE"),
            _tx("w3", f"{Y}-03-07", 60, "CITY WATER DEPT"),
        ],
        business_expenses=[{"id": "e1", "business_id": BIZ, "amount": 15, "category": "operating",
                            "subcategory": "Office Supplies", "date": f"{Y}-02-20"}],
        category_rules=[], expense_categories=[], chief_undo_log=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
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


def _log(db, result):
    db.t["chief_undo_log"].append({"id": f"u{len(db.t['chief_undo_log'])}", "business_id": BIZ,
                                   "action_type": result["type"], "status": "undoable",
                                   "created_at": "2099-01-01T00:00:00Z", "result_json": result})


# ─── The list ────────────────────────────────────────────────────────

def test_one_spelling_per_name():
    assert ec.key_of("Utilities") == ec.key_of("utilities ") == ec.key_of("Utility")
    assert ec.key_of("Bank fees") == ec.key_of("bank fee") and ec.key_of("Bank fees") != ec.key_of("Bank")


def test_chief_makes_a_category_once(db):
    got = _run(ec.handle_set_expense_category, {"name": "Benevolence", "bucket": "operating"})
    assert not got.get("failed") and "Made the category Benevolence" in got["result"]
    again = _run(ec.handle_set_expense_category, {"name": "benevolence "})
    assert "already a category" in again["result"] and len(db.t["expense_categories"]) == 1
    assert _run(ec.handle_set_expense_category, {"name": "X", "bucket": "fun"})["failed"]


def test_the_list_shows_totals_and_labels_not_saved(db):
    ec.create(BIZ, OWNER, "Utilities", "operating")
    p = ec.picture(BIZ, Y)
    (u,) = p["categories"]
    assert (u["name"], u["count"], u["total"]) == ("Utilities", 2, 250.0)
    unsaved = {x["label"]: x for x in p["unsaved"]}
    assert "Office supplies" in unsaved and "Office Supplies" in unsaved and "office supply" in unsaved


def test_a_rename_moves_rows_rules_and_expenses_and_one_undo_puts_it_back(db):
    ec.create(BIZ, OWNER, "Office supplies", "operating")
    db.t["category_rules"].append({"id": "r1", "business_id": BIZ, "merchant_name": "office depot",
                                   "business_category": "operating", "business_subcategory": "Office supplies"})
    got = _run(ec.handle_set_expense_category, {"category": "office supplies", "name": "Ministry supplies"})
    assert not got.get("failed"), got
    assert {_row(db, t)["business_subcategory"] for t in ("p3", "p4")} == {"Ministry supplies"}
    assert db.t["business_expenses"][0]["subcategory"] == "Ministry supplies"
    assert db.t["category_rules"][0]["business_subcategory"] == "Ministry supplies"
    assert db.t["expense_categories"][0]["name"] == "Ministry supplies"
    _log(db, got)
    _row(db, "p4")["business_subcategory"] = "Postage"               # changed since: left as it is
    back = _run(ec.handle_undo_category_change, action_inverse.build_inverse("set_expense_category", {}, got))
    assert not back.get("failed") and "1 had been changed since" in back["result"]
    assert _row(db, "p3")["business_subcategory"] == "Office supplies" and _row(db, "p4")["business_subcategory"] == "Postage"
    assert db.t["expense_categories"][0]["name"] == "Office supplies"


def test_a_merge_moves_everything_into_the_other_and_archives_it(db):
    ec.create(BIZ, OWNER, "Bank fees", "operating")
    ec.create(BIZ, OWNER, "Overdraft fees", "operating")
    _row(db, "p3")["business_subcategory"] = "overdraft fee"
    got = _run(ec.handle_set_expense_category, {"category": "Overdraft fees", "into": "bank fees"})
    assert not got.get("failed") and _row(db, "p3")["business_subcategory"] == "Bank fees"
    assert next(c for c in db.t["expense_categories"] if c["name"] == "Overdraft fees")["archived_at"]
    assert [c["name"] for c in ec.categories(BIZ)] == ["Bank fees"]


# ─── Filing under categories ─────────────────────────────────────────

def test_filing_under_a_saved_category_takes_its_line_bucket_and_spelling(db):
    ec.create(BIZ, OWNER, "Utilities", "operating")
    got = _run(cf.handle_file_bank_rows, {"items": [{"payee": "city water dept", "category": "utilities"}]})
    assert got["summary"]["count"] == 1
    assert (_row(db, "w3")["business_category"], _row(db, "w3")["business_subcategory"]) == ("operating", "Utilities")
    bad = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "category": "Utilities", "answer": "tax"}]})
    assert bad["failed"] and "is under Operating" in bad["result"]
    none = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "category": "Hospitality"}]})
    assert none["failed"] and "no category called 'Hospitality'" in none["result"]


def test_moving_filed_rows_between_categories(db):
    ec.create(BIZ, OWNER, "Ministry supplies", "operating")
    got = _run(cf.handle_file_bank_rows, {"items": [
        {"refile": True, "from_category": "Office supplies", "category": "Ministry supplies"}]})
    assert got["summary"]["count"] == 2          # 'Office supplies' and 'office supply' read the same
    assert {_row(db, t)["business_subcategory"] for t in ("p3", "p4")} == {"Ministry supplies"}
    # Only spending lines move; never income, and never a waiting row by refile.
    bad = _run(cf.handle_file_bank_rows, {"items": [{"refile": True, "payee": "duke energy util pymt", "answer": "income"}]})
    assert bad["failed"] and "spending line only" in bad["result"]


def test_an_unreadable_list_never_stops_filing_by_label(db, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/expense_categories") else real(path, **kw))
    got = _run(cf.handle_file_bank_rows, {"items": [{"payee": "overdraft fee", "answer": "operating", "label": "Bank fees"}]})
    assert got["summary"]["count"] == 1 and _row(db, "w2")["business_subcategory"] == "Bank fees"
    named = _run(cf.handle_file_bank_rows, {"items": [{"payee": "city water dept", "category": "Utilities"}]})
    assert named["failed"] and "saved categories couldn't be read" in named["result"]


# ─── Suggestions and remembering ─────────────────────────────────────

def test_chief_suggests_from_how_a_payee_was_filed_and_from_rules(db):
    db.t["category_rules"].append({"id": "r1", "business_id": BIZ, "merchant_name": "overdraft fee",
                                   "business_category": "operating", "business_subcategory": "Bank fees"})
    got = _run(cf.handle_bank_to_file, {}, who=READER)
    by = {g["payee"]: g for g in got["groups"]}
    assert by["duke energy util pymt"]["suggest"] == {"from": "history", "answer": "operating", "label": "Utilities",
                                                      "times": 2, "of": 2}
    assert by["overdraft fee"]["suggest"] == {"from": "rule", "answer": "operating", "label": "Bank fees"}
    assert "suggest" not in by["city water dept"]
    assert "2 of these payees have been filed before or have a rule" in got["result"]
    assert "save_category_rule" in got["note_for_chief"]


def test_remembering_a_payee_files_its_next_payments_and_undo_forgets(db):
    ec.create(BIZ, OWNER, "Utilities", "operating")
    got = _run(ec.handle_save_category_rule, {"payee": "city water dept", "category": "utilities"})
    assert not got.get("failed") and "from now on" in got["result"]
    (rule,) = db.t["category_rules"]
    assert (rule["merchant_name"], rule["business_category"], rule["business_subcategory"]) == (
        "city water dept", "operating", "Utilities")
    rule_map = {"city water dept": {"cat": "operating", "sub": "Utilities"}}
    # The bank feed's next payment: matched on the bank's wording, merchant unknown.
    tx = SimpleNamespace(transaction_id="n1", account_id="acc", amount=61.0, iso_currency_code="USD", date="2026-04-07",
                         authorized_date=None, datetime=None, name="CITY WATER DEPT 0407", merchant_name=None,
                         personal_finance_category=None, pending=False)
    payload = plaid_router._tx_payload(tx, BIZ, rule_map)
    assert (payload["business_category"], payload["business_subcategory"]) == ("operating", "Utilities")
    assert ec.rule_for(rule_map, None, "CITY WATER DEPT 0507") and not ec.rule_for(rule_map, None, "CITY GAS")
    _log(db, got)
    back = _run(ec.handle_undo_category_change, action_inverse.build_inverse("save_category_rule", {}, got))
    assert not back.get("failed") and db.t["category_rules"] == []


def test_a_rule_files_a_statements_spending_as_it_arrives(db, monkeypatch):
    import bank_statements as bs
    db.t["category_rules"].append({"id": "r1", "business_id": BIZ, "merchant_name": "city water dept",
                                   "business_category": "operating", "business_subcategory": "Utilities"})
    db.t["bank_statement_imports"] = []
    db.t["plaid_accounts"][0]["mask"] = "0000"
    import plaid_reconciliation
    monkeypatch.setattr(plaid_reconciliation, "reconcile_business", lambda *a, **k: (0, 0))
    bs.add(BIZ, OWNER, {"account_id": "acc", "rows": [
        {"date": f"{Y - 1}-12-10", "description": "CITY WATER DEPT 0110", "amount": -58},     # before the feed
        {"date": f"{Y - 1}-12-11", "description": "SOMETHING ELSE", "amount": -9}]})
    rows = {t["name"]: t for t in db.t["plaid_transactions"] if str(t["transaction_id"]).startswith("stmt_")}
    assert rows["CITY WATER DEPT 0110"]["business_subcategory"] == "Utilities"
    assert rows["SOMETHING ELSE"]["business_category"] == "other"


def test_a_rename_that_fails_partway_records_what_moved_and_finishes_on_asking_again(db, monkeypatch):
    ec.create(BIZ, OWNER, "Office supplies", "operating")
    real = ec._patch_row
    calls = {"n": 0}

    def flaky(business_id, table, rid, guard, body):
        if table == "plaid_transactions":
            calls["n"] += 1
            if calls["n"] == 2:
                return None                                    # one write fails
        return real(business_id, table, rid, guard, body)
    monkeypatch.setattr(ec, "_patch_row", flaky)
    got = _run(ec.handle_set_expense_category, {"category": "Office supplies", "name": "Ministry supplies"})
    assert not got.get("failed") and "Partway through" in got["result"] and got["changes"]
    assert db.t["expense_categories"][0]["name"] == "Office supplies"          # the old name stands
    again = _run(ec.handle_set_expense_category, {"category": "Office supplies", "name": "Ministry supplies"})
    assert not again.get("failed") and db.t["expense_categories"][0]["name"] == "Ministry supplies"
    assert {_row(db, t)["business_subcategory"] for t in ("p3", "p4")} == {"Ministry supplies"}


def test_a_refund_from_a_remembered_payee_is_never_filed_as_its_spending():
    rule_map = {"city water dept": {"cat": "operating", "sub": "Utilities"}}
    assert ec.rule_for(rule_map, None, "CITY WATER DEPT REFUND", money_out=False) is None
    assert ec.rule_for(rule_map, None, "CITY WATER DEPT 0407", money_out=True)
    refund = SimpleNamespace(transaction_id="n2", account_id="acc", amount=-20.0, iso_currency_code="USD",
                             date="2026-04-09", authorized_date=None, datetime=None, name="CITY WATER DEPT REFUND",
                             merchant_name=None, personal_finance_category=None, pending=False)
    assert plaid_router._tx_payload(refund, BIZ, rule_map)["business_subcategory"] is None


def test_the_routes_let_readers_read_and_only_the_owner_add(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_supabase import AuthedUser, require_user

    def client(uid):
        app = FastAPI()
        app.include_router(ec.router)
        app.dependency_overrides[require_user] = lambda: AuthedUser(id=uid, email="x@y.z", role="authenticated")
        return TestClient(app)
    got = client(READER).get("/expense-categories", params={"business_id": BIZ, "year": Y})
    assert got.status_code == 200 and got.json()["can_change"] is False
    assert client(READER).post("/expense-categories", json={"business_id": BIZ, "name": "X"}).status_code == 403
    made = client(OWNER).post("/expense-categories", json={"business_id": BIZ, "name": "Benevolence"})
    assert made.status_code == 200 and made.json()["made"] is True
    assert client("00000000-0000-4000-8000-000000000009").get("/expense-categories",
                                                               params={"business_id": BIZ}).status_code == 403


# ─── The card ────────────────────────────────────────────────────────

def _client(uid):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_supabase import AuthedUser, require_user
    app = FastAPI()
    app.include_router(ec.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=uid, email="x@y.z", role="authenticated")
    return TestClient(app)


def test_the_card_renames_and_its_undo_button_puts_it_back(db):
    ec.create(BIZ, OWNER, "Office supplies", "operating")
    got = _client(OWNER).post("/expense-categories/change", json={
        "business_id": BIZ, "category": "office supplies", "name": "Ministry supplies", "bucket": "operating"})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["said"].startswith("Office supplies is now Ministry supplies") and "undo" not in body["said"].lower()
    assert {_row(db, t)["business_subcategory"] for t in ("p3", "p4")} == {"Ministry supplies"}
    # Recorded in Chief's undo log, by the person who clicked.
    log = db.t["chief_undo_log"][-1]
    assert (log["action_type"], log["user_id"], log["status"]) == ("set_expense_category", OWNER, "undoable")
    assert log["result_json"]["batch_id"] == body["batch_id"]
    log["created_at"] = "2099-01-01T00:00:00Z"
    back = _client(OWNER).post("/expense-categories/undo", json={"business_id": BIZ, "batch_id": body["batch_id"]})
    assert back.status_code == 200, back.text
    assert {_row(db, t)["business_subcategory"] for t in ("p3", "p4")} == {"Office supplies", "office supply"}
    assert db.t["expense_categories"][0]["name"] == "Office supplies"
    again = _client(OWNER).post("/expense-categories/undo", json={"business_id": BIZ, "batch_id": body["batch_id"]})
    assert again.status_code == 409 and "no such change" in again.json()["detail"]


def test_the_card_moves_a_bucket_and_merges_a_label_not_on_the_list(db):
    ec.create(BIZ, OWNER, "Office supplies", "operating")
    ec.create(BIZ, OWNER, "Utilities", "operating")
    moved = _client(OWNER).post("/expense-categories/change", json={
        "business_id": BIZ, "category": "Utilities", "name": "Utilities", "bucket": "tax"})
    assert moved.status_code == 200 and (_row(db, "p1")["business_category"], _row(db, "p1")["business_subcategory"])         == ("tax", "Utilities")
    _row(db, "p3")["business_subcategory"] = "Supplies misc"            # in use, never saved
    merged = _client(OWNER).post("/expense-categories/change", json={
        "business_id": BIZ, "category": "supplies misc", "into": "office supplies"})
    assert merged.status_code == 200, merged.text
    assert _row(db, "p3")["business_subcategory"] == "Office supplies"
    assert [c["name"] for c in ec.categories(BIZ)] == ["Office supplies", "Utilities"]      # nothing archived
    nothing = _client(OWNER).post("/expense-categories/change", json={
        "business_id": BIZ, "category": "never used", "into": "Utilities"})
    assert nothing.status_code == 409 and nothing.json()["detail"] == "Nothing is filed under 'never used'"
    missing = _client(OWNER).post("/expense-categories/change", json={
        "business_id": BIZ, "category": "never used", "name": "X"})
    assert missing.status_code == 409 and "no category called" in missing.json()["detail"]


def test_a_card_change_whose_undo_record_fails_says_it_cant_be_undone(db, monkeypatch):
    ec.create(BIZ, OWNER, "Utilities", "operating")
    real = sb_clients.sb_post_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, *a, **k: None if path.startswith("/chief_undo_log") else real(path, body, *a, **k))
    got = _client(OWNER).post("/expense-categories/change", json={
        "business_id": BIZ, "category": "Utilities", "name": "Power"})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["batch_id"] is None and "can't be undone" in body["said"]
    assert _row(db, "p1")["business_subcategory"] == "Power"              # the change itself stands
    assert db.t["chief_undo_log"] == []


def test_the_card_changes_only_for_the_owner_and_only_where_switched_on(db, monkeypatch):
    ec.create(BIZ, OWNER, "Utilities", "operating")
    ask = {"business_id": BIZ, "category": "Utilities", "name": "Power"}
    assert _client(READER).post("/expense-categories/change", json=ask).status_code == 403
    assert _client(READER).post("/expense-categories/undo",
                                json={"business_id": BIZ, "batch_id": "a" * 32}).status_code == 403
    assert _client(OWNER).post("/expense-categories/change",
                               json={"business_id": BIZ, "category": "Utilities"}).status_code == 422
    assert _client(READER).get("/expense-categories", params={"business_id": BIZ}).json()["card"] is True
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: False)
    off = _client(OWNER).post("/expense-categories/change", json=ask)
    assert off.status_code == 403 and "switched on" in off.json()["detail"]
    assert _client(OWNER).get("/expense-categories", params={"business_id": BIZ}).json()["card"] is False
    assert db.t["expense_categories"][0]["name"] == "Utilities"


# ─── Who may, and the wiring ─────────────────────────────────────────

def test_readers_read_and_only_the_owner_changes(db):
    assert not _run(ec.handle_expense_categories, {}, who=READER).get("failed")
    for h, a in ((ec.handle_set_expense_category, {"name": "X"}),
                 (ec.handle_save_category_rule, {"payee": "x", "answer": "operating"})):
        got = _run(h, a, who=READER)
        assert got["failed"] and "Only the owner" in got["result"]


def test_the_verbs_are_wired():
    import chief_tool_loop
    import chief_prompt
    for verb in ("expense_categories", "set_expense_category", "save_category_rule", "undo_category_change"):
        assert verb in cos.ACTION_HANDLERS and action_registry.REGISTRY[verb]["chief_only"] is True
    assert "expense_categories" in {t["name"] for t in chief_tool_loop.read_tool_definitions()}
    src = open(chief_prompt.__file__, encoding="utf-8").read().replace("{{", "{")
    assert all(f'"type":"{v}"' in src for v in ("set_expense_category", "save_category_rule", "undo_category_change"))
