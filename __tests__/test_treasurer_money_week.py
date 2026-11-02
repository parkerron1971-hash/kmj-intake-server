"""The treasurer's money week (church_money_gate.py). Kevin, 2026-11-01:
Love City's treasurer holds an Admin seat, and must be able to do the money
week: match Sunday's deposit, work the bank (file, match, sync, rules),
reconcile, the categories, the bills and the store orders. And a Giving
keeper's lock must not be a dead end: in CHURCH_KEYS=owner the key routes
were open to the platform owner's email alone, so a locked-out treasurer
couldn't even ask for a key.

Pins, for every door that opened:
  * the owner gets in; a church's Admin seat gets in
  * a church's Manager seat is refused (403), and so is a stranger
  * a non-church business's Admin seat is refused, exactly as before
  * a refusal writes nothing
And:
  * linking or unlinking a bank, and which accounts count, stay owner-only
  * the Giving wall still holds a church's Admins at the bank's doors until
    a keeper gives them a key; bills and store orders were never behind it
  * Chief's verbs follow the same gate (reconcile, file the bank, categories,
    the Sunday match, add and remove bills); only the owner is shown a bank
    payment that fits a new bill, since only they match bills to the bank
  * a church's bills list: owner, Admin, the outside accountant; anyone
    else's list as before
  * the keys in owner mode: the platform owner's churches open the key
    routes to their own logins and accountants, nobody else's
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import bills_router  # noqa: E402
import chief_bills  # noqa: E402
import chief_file_bank  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_reconcile  # noqa: E402
import chief_transactions  # noqa: E402
import church_keys as ck  # noqa: E402
import church_money_gate  # noqa: E402
import expense_categories as ec  # noqa: E402
import expense_lines  # noqa: E402
import giving_deposits as gd  # noqa: E402
import period_lock  # noqa: E402
import plaid_reconciliation  # noqa: E402
import plaid_router  # noqa: E402
import store_router  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_keys import BIZ, ID, PEOPLE, _refused, db  # noqa: E402,F401

SHOP = "33333333-3333-4333-8333-333333333333"
MATCH_ID = "44444444-4444-4444-8444-444444444444"


def _person(n, name):
    return AuthedUser(id=f"00000000-0000-4000-8000-0000000001{n:02d}", email=f"{name}@example.org",
                      role="authenticated")


MANAGER = _person(1, "manager")
SHOP_ADMIN = _person(2, "shopadmin")
SHOP_MEMBER = _person(3, "shopmember")
ACCOUNTANT = _person(4, "books")
WHO = {"owner": PEOPLE["owner"], "treasurer": PEOPLE["treasurer"], "manager": MANAGER,
       "stranger": PEOPLE["stranger"], "shop admin": SHOP_ADMIN}


@pytest.fixture
def money(db, monkeypatch):
    """Love City (a church) with its treasurer's Admin seat and a Manager
    seat; Fade Shop (a barber, the same owner) with an Admin seat. Each has
    a bank row, an account, a linked bank, a bill and a paid order."""
    db.t["businesses"].append({"id": SHOP, "name": "Fade Shop", "type": "barber", "owner_id": ID["owner"]})
    db.t["business_users"] += [
        {"business_id": BIZ, "user_id": MANAGER.id, "role": "manager", "status": "active",
         "invited_email": MANAGER.email},
        {"business_id": SHOP, "user_id": SHOP_ADMIN.id, "role": "admin", "status": "active",
         "invited_email": SHOP_ADMIN.email},
        {"business_id": SHOP, "user_id": SHOP_MEMBER.id, "role": "member", "status": "active",
         "invited_email": SHOP_MEMBER.email}]
    db.t["business_collaborators"] = [{"business_id": BIZ, "user_id": ACCOUNTANT.id, "status": "active",
                                       "role": "accountant", "invited_email": ACCOUNTANT.email}]
    for biz in (BIZ, SHOP):
        db.t.setdefault("plaid_transactions", []).append(
            {"transaction_id": f"t-{biz}", "business_id": biz, "account_id": f"acct-{biz}", "date": "2026-10-20",
             "amount": 40.0, "name": "CITY WATER", "merchant_name": "City Water", "money_kind": None,
             "reconciled_to_payout_id": None})
        db.t.setdefault("plaid_accounts", []).append(
            {"account_id": f"acct-{biz}", "business_id": biz, "item_id": f"item-{biz}", "deleted_at": None,
             "included_in_bookkeeping": True})
        db.t.setdefault("plaid_items", []).append({"item_id": f"item-{biz}", "business_id": biz, "status": "active"})
        db.t.setdefault("bills", []).append(
            {"id": f"bill-{biz}", "business_id": biz, "vendor_name": "City Water", "amount": 40.0,
             "status": "pending", "is_recurring": False, "created_at": "2026-10-20T00:00:00Z",
             "due_date": "2026-11-20"})
        db.t.setdefault("orders", []).append(
            {"id": f"order-{biz}", "business_id": biz, "status": "paid", "customer_email": None})
    monkeypatch.setattr(period_lock, "guard", lambda *a, **k: None)
    monkeypatch.setattr(plaid_router.plaid_helpers, "plaid_configured", lambda: True)
    monkeypatch.setattr(plaid_reconciliation, "reconcile_business", lambda biz: (0, 0))
    monkeypatch.setenv("GIVING_DEPOSITS", "on")
    monkeypatch.setattr(gd, "match_clear", lambda *a, **k: {"matched": [], "skipped": [], "batch_id": None})
    monkeypatch.setattr(gd, "unmatch", lambda *a, **k: {"unmatched": 1})
    monkeypatch.setattr(gd, "status", lambda *a, **k: {"proposals": []})
    monkeypatch.setattr(chief_transactions, "switched_on", lambda biz: True)
    monkeypatch.setattr(ec, "create", lambda biz, uid, name, bucket, line=None: ({"name": name}, True))
    monkeypatch.setattr(ec, "change", lambda *a, **k: {"result": "Renamed it.", "changes": []})
    monkeypatch.setattr(ec, "take_back", lambda *a, **k: {"result": "Put it back."})
    monkeypatch.setattr(ec, "picture", lambda *a, **k: {"categories": []})
    monkeypatch.setattr(expense_lines, "change", lambda *a, **k: {"result": "Renamed the line.", "changes": []})
    return db


def _session(user):
    return SimpleNamespace(user=user)


BUCKET = plaid_router.plaid_categorization.ALL_BUCKETS[0]


def _doors():
    """Each opened door, called the way its route calls it, for one business."""
    P = plaid_router
    return {
        # The bank (plaid_router), behind the Giving wall.
        "bank sync": lambda u, b: P.sync_business(P.SyncBody(business_id=b), user=u),
        "bank row edit": lambda u, b: P.update_transaction(f"t-{b}", P.TxPatchBody(notes="water"), user=u),
        "bank categorize": lambda u, b: P.bulk_categorize(
            P.BulkCategorizeBody(business_id=b, transaction_ids=[f"t-{b}"], business_category=BUCKET), user=u),
        "bank exclude": lambda u, b: P.bulk_exclude(
            P.BulkExcludeBody(business_id=b, transaction_ids=[f"t-{b}"], excluded_from_books=False), user=u),
        "bank rule": lambda u, b: P.upsert_rule(
            P.RuleBody(business_id=b, merchant_name="City Water", business_category=BUCKET), user=u),
        "bank rule delete": lambda u, b: P.delete_rule("rule-1", b, user=u),
        "payout match": lambda u, b: P.reconciliation_match(
            P.MatchBody(business_id=b, plaid_transaction_id=f"t-{b}", stripe_payout_id="po_1"), user=u),
        "payout unmatch": lambda u, b: P.reconciliation_unmatch(
            P.UnmatchBody(business_id=b, plaid_transaction_id=f"t-{b}"), user=u),
        "payout ignore": lambda u, b: P.reconciliation_ignore(
            P.IgnoreBody(business_id=b, plaid_transaction_id=f"t-{b}"), user=u),
        "payout run": lambda u, b: P.reconciliation_run(P.SyncBody(business_id=b), user=u),
        # The Sunday match (giving_deposits).
        "deposit match": lambda u, b: gd.post_match(gd.MatchBody(business_id=b, clear=True), user=u),
        "deposit unmatch": lambda u, b: gd.delete_match(MATCH_ID, business_id=b, user=u),
        # The categories (expense_categories).
        "category add": lambda u, b: ec.post_category(ec.CategoryBody(business_id=b, name="Utilities"), user=u),
        "category change": lambda u, b: ec.post_change(
            ec.ChangeBody(business_id=b, category="Utilities", name="Water"), user=u),
        "line change": lambda u, b: ec.post_line(ec.LineBody(business_id=b, line="operating", name="Running"), user=u),
        "category undo": lambda u, b: ec.post_undo(ec.UndoBody(business_id=b, batch_id="b1"), user=u),
        # The bills (bills_router).
        "bill add": lambda u, b: bills_router.create_bill(
            bills_router.BillBody(business_id=b, vendor_name="Light Co", amount=25), user=u),
        "bill edit": lambda u, b: bills_router.update_bill(
            f"bill-{b}", bills_router.BillPatchBody(business_id=b, notes="autopay"), user=u),
        "bill paid": lambda u, b: bills_router.mark_paid(
            f"bill-{b}", bills_router.MarkPaidBody(business_id=b), user=u),
        "bill delete": lambda u, b: bills_router.delete_bill(f"bill-{b}", b, user=u),
        # The store orders (store_router).
        "orders list": lambda u, b: store_router.list_orders(b, session=_session(u)),
        "order fulfill": lambda u, b: store_router.fulfill_order(f"order-{b}", session=_session(u)),
        "order ship": lambda u, b: store_router.ship_order(
            f"order-{b}", store_router.ShipOrderBody(notify=False), session=_session(u)),
    }


DOORS = sorted(_doors())


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("who", ["owner", "treasurer"])
def test_the_owner_and_a_churchs_admin_get_in(money, door, who):
    _doors()[door](WHO[who], BIZ)


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("who", ["manager", "stranger"])
def test_a_churchs_manager_and_a_stranger_are_refused_and_nothing_is_written(money, door, who):
    before = len(money.writes)
    assert _refused(_doors()[door], WHO[who], BIZ).status_code == 403
    assert len(money.writes) == before, "nothing is written before the refusal"


@pytest.mark.parametrize("door", DOORS)
def test_outside_a_church_an_admin_seat_is_refused_as_before_and_the_owner_isnt(money, door):
    before = len(money.writes)
    assert _refused(_doors()[door], SHOP_ADMIN, SHOP).status_code == 403
    assert len(money.writes) == before
    _doors()[door](PEOPLE["owner"], SHOP)


def test_the_gate_itself(money):
    assert church_money_gate.require_money_writer(BIZ, PEOPLE["treasurer"])["id"] == BIZ
    for who, biz in ((MANAGER, BIZ), (PEOPLE["member"], BIZ), (ACCOUNTANT, BIZ), (SHOP_ADMIN, SHOP)):
        assert _refused(church_money_gate.require_money_writer, biz, who).status_code == 403
    assert _refused(church_money_gate.require_money_writer, "99999999-9999-4999-8999-999999999999",
                    PEOPLE["owner"]).status_code == 404
    money.t["business_users"][0]["status"] = "removed"          # the treasurer's seat taken back
    assert _refused(church_money_gate.require_money_writer, BIZ, PEOPLE["treasurer"]).status_code == 403


def test_a_church_that_stops_being_one_holds_its_admins_to_the_owner_rule(money):
    money.t["businesses"][0]["type"] = "consultant"
    assert _refused(_doors()["bill add"], PEOPLE["treasurer"], BIZ).status_code == 403
    _doors()["bill add"](PEOPLE["owner"], BIZ)


def test_the_screens_say_who_can_change(money):
    for who, can in (("owner", True), ("treasurer", True)):
        assert gd.get_status(BIZ, year=2026, user=WHO[who])["can_change"] is can, who
        assert ec.get_categories(BIZ, year=2026, user=WHO[who])["can_change"] is can, who
    assert gd.get_status(SHOP, year=2026, user=SHOP_ADMIN)["can_change"] is False
    assert ec.get_categories(SHOP, year=2026, user=SHOP_ADMIN)["can_change"] is False


# ─── What stays the owner's ───────────────────────────────────────────

def test_linking_unlinking_and_which_accounts_count_stay_owner_only(money):
    P = plaid_router
    owner_only = {
        "link a bank": lambda u: P.create_link_token(P.LinkTokenBody(business_id=BIZ), user=u),
        "finish linking": lambda u: P.exchange_public_token(
            P.ExchangeBody(business_id=BIZ, public_token="public-x"), user=u),
        "relink": lambda u: P.relink(f"item-{BIZ}", user=u),
        "unlink": lambda u: P.unlink(f"item-{BIZ}", BIZ, user=u),
        "account in the books": lambda u: P.update_account(
            f"acct-{BIZ}", P.AccountPatchBody(included_in_bookkeeping=False), user=u),
        "remove an account": lambda u: P.remove_account(f"acct-{BIZ}", user=u),
    }
    before = len(money.writes)
    for name, fn in owner_only.items():
        assert _refused(fn, PEOPLE["treasurer"]).status_code == 403, name
    assert len(money.writes) == before
    P.update_account(f"acct-{BIZ}", P.AccountPatchBody(included_in_bookkeeping=True), user=PEOPLE["owner"])


# ─── The Giving wall ──────────────────────────────────────────────────

BANK_DOORS = [d for d in DOORS if d.startswith(("bank", "payout", "deposit"))]


@pytest.mark.parametrize("door", BANK_DOORS)
def test_a_giving_keeper_holds_the_treasurer_at_the_bank_until_a_key(money, door):
    ck.put_keeper(BIZ, PEOPLE["admin"], "giving_money", ID["pastor"], True)
    e = _refused(_doors()[door], PEOPLE["treasurer"], BIZ)
    assert e.status_code == 403 and e.detail["code"] == "area_locked"
    asked = ck.ask(BIZ, PEOPLE["treasurer"], "giving_money", "Monday deposit")
    ck.answer(BIZ, PEOPLE["pastor"], asked["key"]["id"], True)
    _doors()[door](PEOPLE["treasurer"], BIZ)


def test_bills_and_store_orders_were_never_behind_the_wall(money):
    ck.put_keeper(BIZ, PEOPLE["admin"], "giving_money", ID["pastor"], True)
    for door in ("bill add", "bill paid", "orders list", "order fulfill"):
        _doors()[door](PEOPLE["treasurer"], BIZ)


# ─── Chief ────────────────────────────────────────────────────────────

def _as(user, fn, *args, **kw):
    token = cos._TURN_USER_ID.set(user.id)
    try:
        return fn(*args, **kw)
    finally:
        cos._TURN_USER_ID.reset(token)


def test_chief_follows_the_same_gate(money):
    gates = {
        "reconcile": lambda biz: chief_reconcile._owner(biz),
        "file the bank": lambda biz: chief_file_bank._gate(biz, write=True),
        "categories": lambda biz: ec._gate(biz, write=True),
        "bills": lambda biz: chief_bills._owner_gate(biz),
        "sunday match": lambda biz: gd._chief({"id": biz}, "match_giving_deposits", write=True)[0],
    }
    for name, gate in gates.items():
        assert _as(PEOPLE["owner"], gate, BIZ) is None, name
        assert _as(PEOPLE["treasurer"], gate, BIZ) is None, name
        for who, biz in ((MANAGER, BIZ), (SHOP_ADMIN, SHOP)):
            refused = _as(who, gate, biz)
            said = refused if isinstance(refused, str) else refused["result"]
            assert "only the owner" in said.lower(), (name, said)


def test_the_treasurers_chief_adds_a_bill_and_only_the_owner_is_shown_the_bank(money, monkeypatch):
    import bill_payments
    looked = []
    monkeypatch.setattr(bill_payments, "candidates", lambda biz, row, *a, **k: looked.append(biz) or [])
    ask = {"vendor": "Light Co", "amount": 25, "due_date": "2026-12-01"}
    got = _as(PEOPLE["treasurer"], asyncio.run, chief_bills.handle_add_bill(None, {"id": BIZ}, ask))
    assert not got.get("failed"), got
    assert any(b.get("vendor_name") == "Light Co" for b in money.t["bills"]) and looked == []
    _as(PEOPLE["owner"], asyncio.run, chief_bills.handle_add_bill(None, {"id": BIZ}, ask))
    assert looked == [BIZ]
    refused = _as(MANAGER, asyncio.run, chief_bills.handle_add_bill(None, {"id": BIZ}, ask))
    assert refused["failed"] and "Only the owner" in refused["result"]


# ─── A church's bills list ────────────────────────────────────────────

def test_a_churchs_bills_list_is_the_owner_an_admin_or_the_accountant(money):
    for who in (PEOPLE["owner"], PEOPLE["treasurer"], ACCOUNTANT):
        assert bills_router.list_bills(BIZ, user=who)["ok"], who.email
    for who in (MANAGER, PEOPLE["member"], PEOPLE["stranger"]):
        assert _refused(bills_router.list_bills, BIZ, user=who).status_code == 403, who.email
    # Anyone else's list as before: any seat reads it.
    for who in (SHOP_ADMIN, SHOP_MEMBER):
        assert bills_router.list_bills(SHOP, user=who)["ok"], who.email
    # Chief reads the list through the same gate.
    assert _as(PEOPLE["treasurer"], chief_bills._gate, BIZ) is None
    assert _as(MANAGER, chief_bills._gate, BIZ)


# ─── The keys, in owner mode ──────────────────────────────────────────

def _client(user):
    app = FastAPI()
    app.include_router(ck.router)
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def platform_church(money, monkeypatch):
    monkeypatch.setenv("CHURCH_KEYS", "owner")
    money.t["businesses"][0]["owner_id"] = cos.PLATFORM_OWNER_ID
    ck.put_keeper(BIZ, PEOPLE["admin"], "giving_money", ID["pastor"], True)
    return money


def test_in_owner_mode_a_locked_out_treasurer_asks_for_a_key_and_works_the_bank(platform_church):
    assert not ck.is_open(BIZ, PEOPLE["treasurer"], "giving_money")
    seen = _client(PEOPLE["treasurer"]).get(f"/church/keys?business_id={BIZ}")
    assert seen.status_code == 200, seen.text
    assert next(a for a in seen.json()["areas"] if a["area"] == "giving_money")["locked"]
    r = _client(PEOPLE["treasurer"]).post("/church/keys/ask",
                                          json={"business_id": BIZ, "area": "giving_money", "reason": "Deposit"})
    assert r.status_code == 200, r.text
    r = _client(PEOPLE["pastor"]).post(f"/church/keys/{r.json()['key']['id']}/answer",
                                       json={"business_id": BIZ, "yes": True})
    assert r.status_code == 200 and r.json()["key"]["status"] == "open"
    _doors()["bank categorize"](PEOPLE["treasurer"], BIZ)


def test_in_owner_mode_the_platform_churchs_accountant_sees_the_keys_and_a_stranger_doesnt(platform_church):
    assert _client(ACCOUNTANT).get(f"/church/keys?business_id={BIZ}").status_code == 200
    assert _client(PEOPLE["stranger"]).get(f"/church/keys?business_id={BIZ}").status_code == 404
    assert _client(MANAGER).post("/church/keys/ask", json={"business_id": BIZ, "area": "giving_money"}).status_code == 200


def test_in_owner_mode_anyone_elses_church_stays_closed(money, monkeypatch):
    monkeypatch.setenv("CHURCH_KEYS", "owner")
    assert _client(PEOPLE["treasurer"]).get(f"/church/keys?business_id={BIZ}").status_code == 404
    assert _client(PEOPLE["treasurer"]).get("/church/keys?business_id=not-a-church").status_code == 404
    monkeypatch.setenv("CHURCH_KEYS", "off")
    money.t["businesses"][0]["owner_id"] = cos.PLATFORM_OWNER_ID
    assert _client(PEOPLE["treasurer"]).get(f"/church/keys?business_id={BIZ}").status_code == 404
