"""
test_funds.py — funds for the year, placed from the bank.

Kevin, 2026-10-31: "if we created a fund for the year. we can place all what
was paid out or sent out aligned with that. wether it is housing pay etc...",
then "build that", "exactly based on transaction".

Pins:
  * the figures: paid out, money in, the balance, left of the budget and
    over it, from what's placed
  * the finder: the year's cleared transactions in the books' accounts not
    on this fund, what's left of one split across funds, the repeats, where
    the history starts; the housing allowance's payments tagged for the
    owner alone, never anyone else
  * placing is all or none, never past the bank row across funds, once a
    fund; a personal account, another business, a pending row or another
    year is refused
  * the Transactions screen's readers read, the owner alone changes; off
    is a 404; a failed read is a 503, never "nothing"
  * Chief: status quotes the figures, set makes then changes, find gives
    ids, place is one batch that one undo takes back
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_inverse  # noqa: E402
import action_registry  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import funds  # noqa: E402
import plaid_router  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER = "00000000-0000-4000-8000-000000000001"
READER = "00000000-0000-4000-8000-000000000002"
STRANGER = "00000000-0000-4000-8000-000000000009"
STAFF = "f0000000-0000-4000-8000-000000000001"
BUILDING = "f0000000-0000-4000-8000-000000000002"
OLD = "f0000000-0000-4000-8000-000000000003"
ALLOWANCE = "aaaaaaaa-0000-4000-8000-000000000001"


def _tx(tid, on, amount, name="ONLINE TRANSFER TO CHK 4417 REF #IB%s", **kw):
    return {"transaction_id": tid, "business_id": kw.pop("business_id", BIZ),
            "account_id": kw.pop("account_id", "acc_books"), "date": on,
            "name": name % tid[-2:] if "%s" in name else name, "merchant_name": None,
            "amount": amount, "pending": False, "excluded_from_books": False, **kw}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "owner_id": OWNER, "name": "Love City", "type": "church"},
                    {"id": OTHER, "owner_id": STRANGER, "name": "Other", "type": "church"}],
        plaid_accounts=[
            {"account_id": "acc_books", "business_id": BIZ, "included_in_bookkeeping": True, "deleted_at": None},
            {"account_id": "acc_personal", "business_id": BIZ, "included_in_bookkeeping": False, "deleted_at": None}],
        plaid_transactions=[
            _tx("tx_first", "2026-07-17", 12, name="MONTHLY SERVICE FEE"),     # the first day the app has
            _tx("tx_jul", "2026-07-31", 2500), _tx("tx_aug", "2026-08-31", 2500), _tx("tx_sep", "2026-09-30", 2500),
            _tx("tx_pay", "2026-10-15", 4200, name="GUSTO NET PAY 2210"),
            _tx("tx_roof", "2026-09-12", 8000, name="ACME ROOFING"),
            _tx("tx_gift", "2026-08-02", -5000, name="BUILDING FUND DEPOSIT"),
            _tx("tx_pending", "2026-10-30", 2500, pending=True),
            _tx("tx_2025", "2025-12-31", 2500),
            _tx("tx_personal", "2026-09-01", 2500, account_id="acc_personal"),
            _tx("tx_theirs", "2026-09-01", 2500, business_id=OTHER)],
        business_funds=[
            {"id": STAFF, "business_id": BIZ, "year": 2026, "name": "Pastoral staff", "budget": 60000,
             "notes": "", "archived_at": None},
            {"id": BUILDING, "business_id": BIZ, "year": 2026, "name": "Building", "budget": None,
             "notes": "", "archived_at": None},
            {"id": OLD, "business_id": BIZ, "year": 2025, "name": "Pastoral staff", "budget": 50000,
             "notes": "", "archived_at": None}],
        business_fund_items=[],
        minister_housing_allowances=[{"id": ALLOWANCE, "business_id": BIZ, "minister_name": "Pastor Kevin"}],
        minister_housing_entries=[{"id": "h1", "business_id": BIZ, "allowance_id": ALLOWANCE, "source": "bank",
                                   "source_id": "tx_aug"}])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("FUNDS", "on")

    # The Transactions screen's gates, as they answer: the owner reads and
    # writes, a seat reads, anyone else is refused.
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


def _client(user_id):
    app = FastAPI()
    app.include_router(funds.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email="x@y.z", role="authenticated")
    return TestClient(app)


def _run(handler, action, who=OWNER):
    token = cos._TURN_USER_ID.set(who)
    try:
        return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))
    finally:
        cos._TURN_USER_ID.reset(token)


# ─── The figures ─────────────────────────────────────────────────────

def test_the_figures_come_from_what_is_placed():
    fund = {"year": 2026, "name": "Building", "budget": 10000}
    items = [{"amount": 8000, "direction": "out"}, {"amount": 4000, "direction": "out"},
             {"amount": 5000, "direction": "in"}]
    f = funds.figures(fund, items)
    assert (f["paid_out"], f["money_in"], f["balance"]) == (12000, 5000, -7000)
    assert f["left"] == 0 and f["over"] == 2000
    assert "over it by $2,000.00" in funds.describe(fund, f)
    g = funds.figures({**fund, "budget": None}, items)
    assert g["left"] is None and "no budget set" in funds.describe(fund | {"budget": None}, g)


# ─── The finder ──────────────────────────────────────────────────────

def test_the_finder_lists_the_years_transactions_not_on_the_fund(db):
    got = funds.find_bank(BIZ, STAFF)
    ids = {r["transaction_id"] for r in got["rows"]}
    assert ids == {"tx_first", "tx_jul", "tx_aug", "tx_sep", "tx_pay", "tx_roof"}   # money out, cleared, books
    (rep,) = got["repeats"]
    assert rep["amount"] == 2500 and rep["transaction_ids"] == ["tx_jul", "tx_aug", "tx_sep"]
    assert got["history_starts"] == "2026-07-17" and got["history_late"] is True
    came = funds.find_bank(BIZ, BUILDING, direction="in")
    assert [r["transaction_id"] for r in came["rows"]] == ["tx_gift"] and came["rows"][0]["amount"] == 5000


def test_housing_payments_are_tagged_for_the_owner_alone(db):
    owner_view = {r["transaction_id"]: r for r in funds.find_bank(BIZ, STAFF, housing_view=True)["rows"]}
    assert owner_view["tx_aug"]["housing"] == "Pastor Kevin"
    assert funds.find_bank(BIZ, STAFF, housing_view=True)["housing"] == ["tx_aug"]
    assert [r["transaction_id"] for r in funds.find_bank(BIZ, STAFF, housing_view=True, housing_only=True)["rows"]] \
        == ["tx_aug"]
    assert all("housing" not in r for r in funds.find_bank(BIZ, STAFF)["rows"])


# ─── Placing ─────────────────────────────────────────────────────────

def test_placing_a_paycheck_part_leaves_the_rest_for_another_fund(db):
    done = funds.place(BIZ, OWNER, STAFF, [{"transaction_id": "tx_jul"}, {"transaction_id": "tx_pay", "amount": 3000}])
    assert len(done["created_ids"]) == 2 and done["total_out"] == 5500
    items = db.t["business_fund_items"]
    assert {(i["transaction_id"], i["amount"], i["direction"]) for i in items} == {
        ("tx_jul", 2500, "out"), ("tx_pay", 3000, "out")}
    assert any("part of $4,200.00" in i["note"] for i in items)
    left = {r["transaction_id"]: r for r in funds.find_bank(BIZ, BUILDING)["rows"]}
    assert left["tx_pay"]["left"] == 1200 and left["tx_pay"]["on_funds"] == ["Pastoral staff"]
    with pytest.raises(HTTPException) as over:
        funds.place(BIZ, OWNER, BUILDING, [{"transaction_id": "tx_pay", "amount": 1500}])
    assert over.value.status_code == 400 and "$1,200.00 of it is left" in over.value.detail
    with pytest.raises(HTTPException) as again:
        funds.place(BIZ, OWNER, STAFF, [{"transaction_id": "tx_jul"}])
    assert again.value.status_code == 409
    fig = funds.summary(BIZ, 2026)
    staff = next(f for f in fig["funds"] if f["id"] == STAFF)
    assert staff["figures"]["paid_out"] == 5500 and staff["figures"]["left"] == 54500


def test_money_in_is_placed_as_in(db):
    funds.place(BIZ, OWNER, BUILDING, [{"transaction_id": "tx_gift"}, {"transaction_id": "tx_roof"}])
    b = funds.one(BIZ, BUILDING)["fund"]["figures"]
    assert (b["money_in"], b["paid_out"], b["balance"]) == (5000, 8000, -3000)


@pytest.mark.parametrize("tid, says", [
    ("tx_pending", "still pending"), ("tx_2025", "outside 2026"),
    ("tx_theirs", "isn't a bank transaction of this business"), ("tx_personal", "isn't in the books"),
    ("bad id!", "needs the bank transaction")])
def test_placing_is_all_or_none(db, tid, says):
    with pytest.raises(HTTPException) as e:
        funds.place(BIZ, OWNER, STAFF, [{"transaction_id": "tx_jul"}, {"transaction_id": tid}])
    assert says in e.value.detail
    assert db.t["business_fund_items"] == []


def test_removing_a_fund_frees_its_transactions(db):
    funds.place(BIZ, OWNER, STAFF, [{"transaction_id": "tx_jul"}])
    funds.archive_fund(BIZ, STAFF)
    assert db.t["business_fund_items"] == []
    assert "tx_jul" in {r["transaction_id"] for r in funds.find_bank(BIZ, BUILDING)["rows"]}


# ─── Routes ──────────────────────────────────────────────────────────

def test_readers_read_and_the_owner_alone_changes(db):
    assert _client(READER).get(f"/year-funds?business_id={BIZ}&year=2026").json()["can_change"] is False
    assert _client(READER).post("/year-funds", json={"business_id": BIZ, "name": "Youth"}).status_code == 403
    assert _client(READER).get(f"/year-funds/{STAFF}/bank?business_id={BIZ}").status_code == 403
    assert _client(READER).post(f"/year-funds/{STAFF}/bank", json={
        "business_id": BIZ, "items": [{"transaction_id": "tx_jul"}]}).status_code == 403
    assert _client(STRANGER).get(f"/year-funds?business_id={BIZ}").status_code == 403
    c = _client(OWNER)
    got = c.get(f"/year-funds?business_id={BIZ}&year=2026").json()
    assert got["can_change"] is True and {f["name"] for f in got["funds"]} == {"Pastoral staff", "Building"}
    made = c.post("/year-funds", json={"business_id": BIZ, "name": "Youth", "year": 2026, "budget": 4000})
    assert made.status_code == 200
    assert c.post("/year-funds", json={"business_id": BIZ, "name": "youth", "year": 2026}).status_code == 409
    placed = c.post(f"/year-funds/{STAFF}/bank", json={"business_id": BIZ, "items": [{"transaction_id": "tx_sep"}]})
    assert placed.status_code == 200 and placed.json()["total_out"] == 2500
    one = c.get(f"/year-funds/{STAFF}?business_id={BIZ}").json()
    assert one["items"][0]["bank"]["description"].startswith("ONLINE TRANSFER")
    report = c.get(f"/year-funds/{STAFF}/report.csv?business_id={BIZ}")
    assert report.status_code == 200 and "Paid out (1),2500.00" in report.content.decode("utf-8-sig")
    gone = c.post("/year-funds/bank/detach", json={"business_id": BIZ, "item_ids": placed.json()["created_ids"]})
    assert gone.json() == {"ok": True, "removed": 1}


def test_switched_off_is_not_there_and_a_failed_read_is_a_503(db, monkeypatch):
    monkeypatch.setenv("FUNDS", "off")
    assert _client(OWNER).get(f"/year-funds?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("FUNDS", "on")
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_fund") else real(path, **kw))
    assert _client(OWNER).get(f"/year-funds?business_id={BIZ}").status_code == 503
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/plaid_transactions") else real(path, **kw))
    with pytest.raises(funds.Unavailable):
        funds.find_bank(BIZ, STAFF)


def test_a_formula_in_the_report_is_quoted(db):
    db.t["business_funds"][1]["name"] = "=CMD()"
    text, name = funds.report_csv(BIZ, BUILDING)
    assert text.startswith("'=CMD(): 2026") and name == "fund-2026-cmd.csv"


# ─── Chief ───────────────────────────────────────────────────────────

def test_chief_makes_changes_finds_places_and_takes_back(db):
    made = _run(funds.handle_set_fund, {"name": "Youth", "budget": 4000, "year": 2026})
    assert made["result"] == "Made the 2026 fund Youth, budget $4,000.00."
    changed = _run(funds.handle_set_fund, {"name": "Youth", "budget": 5000, "year": 2026})
    assert changed["result"].startswith("Changed the 2026 fund Youth, budget $5,000.00")
    renamed = _run(funds.handle_set_fund, {"fund": "youth", "name": "Youth ministry", "year": 2026})
    assert renamed["result"].startswith("Changed the 2026 fund Youth ministry")
    found = _run(funds.handle_find_fund_payments, {"fund": "pastoral", "year": 2026})
    assert not found.get("failed"), found["result"]
    assert found["result"].startswith("Pastoral staff (2026): 6 transaction(s) out of the bank aren't on it yet")
    assert "transaction_ids tx_jul, tx_aug, tx_sep" in found["result"]
    assert "1 of them are tied to a housing allowance" in found["result"]
    housing = _run(funds.handle_find_fund_payments, {"fund": "pastoral", "year": 2026, "housing": True})
    assert "tied to Pastor Kevin's housing allowance" in housing["result"]
    placed = _run(funds.handle_place_fund_payments, {"fund": "Pastoral staff", "year": 2026,
                                                     "transaction_ids": ["tx_jul", "tx_aug", "tx_sep"]})
    assert placed["result"].startswith("Placed 3 bank transaction(s) on Pastoral staff (2026)")
    assert "paid out $7,500.00" in placed["result"] and "$52,500.00 left" in placed["result"]
    status = _run(funds.handle_fund_status, {"year": 2026})
    assert "Pastoral staff, 2026: paid out $7,500.00 (3 payment(s))" in status["result"]
    inv = action_inverse.build_inverse("place_fund_payments", {}, placed)
    back = _run(funds.handle_unplace_fund_payments, inv)
    assert back["result"] == "Took 3 bank transaction(s) off the fund."
    assert db.t["business_fund_items"] == []


def test_chief_lets_a_reader_read_and_only_the_owner_place(db):
    assert not _run(funds.handle_fund_status, {"year": 2026}, who=READER).get("failed")
    r = _run(funds.handle_place_fund_payments, {"fund": "Building", "transaction_ids": ["tx_roof"]}, who=READER)
    assert r["failed"] and "only the owner" in r["result"]
    r = _run(funds.handle_find_fund_payments, {"fund": "Building"}, who=READER)
    assert r["failed"]
    assert _run(funds.handle_fund_status, {}, who=STRANGER)["failed"]
    assert db.t["business_fund_items"] == []


def test_the_fund_verbs_are_placed():
    import chief_areas
    import chief_prompt
    import chief_tool_loop as ctl
    prompt = open(chief_prompt.__file__, encoding="utf-8").read()
    for verb in ("fund_status", "set_fund", "find_fund_payments", "place_fund_payments", "unplace_fund_payments"):
        assert not action_registry.may_expose_to_agent(verb, allow_writes=True), verb
        # Giving & money, like the bank search: a treasurer's login reads;
        # the handlers keep changes to the owner.
        assert chief_areas.VERBS.get(verb) == chief_areas.MONEY and verb in cos.ACTION_HANDLERS
        assert f'"type":"{verb}"' in prompt, verb
    assert action_registry.is_sensitive("find_fund_payments") and action_registry.is_sensitive("fund_status")
    assert action_registry.is_bulk("place_fund_payments") and not action_registry.is_bulk("unplace_fund_payments")
    names = {t["name"] for t in ctl.read_tool_definitions()}
    assert {"fund_status", "find_fund_payments"} <= names
    assert action_inverse.can_undo("place_fund_payments")


# ─── From the review on #1662 ────────────────────────────────────────

def _paged(db, page):
    """The fake answering like PostgREST: at most `page` rows a read, with
    offset honoured, whatever the limit asks."""
    import re as _re

    def get(path, **kw):
        m = _re.search(r"&offset=(\d+)", path)
        off = int(m.group(1)) if m else 0
        bare = _re.sub(r"&offset=\d+", "", _re.sub(r"&limit=\d+", "", path))
        return db.get(bare)[off:off + page]
    return get


def test_more_placements_than_one_read_are_all_counted(db, monkeypatch):
    import bank_picks
    for n, tid in enumerate(("tx_jul", "tx_aug", "tx_sep", "tx_roof", "tx_first")):
        db.t["business_fund_items"].append({"id": f"i{n}", "business_id": BIZ, "fund_id": STAFF, "transaction_id": tid,
                                            "amount": 12 if tid == "tx_first" else (8000 if tid == "tx_roof" else 2500),
                                            "direction": "out", "entry_date": "2026-08-01", "note": "",
                                            "created_at": f"2026-08-01T00:0{n}:00Z"})
    monkeypatch.setattr(bank_picks, "PAGE", 2)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _paged(db, 2))
    assert len(funds._used(BIZ)) == 5
    assert funds.figures(funds.get_fund(BIZ, STAFF), funds.items_for(BIZ, [STAFF]))["paid_out"] == 15512
    with pytest.raises(HTTPException) as again:
        funds.place(BIZ, OWNER, BUILDING, [{"transaction_id": "tx_roof"}])     # the 5th row read, all of it used
    assert again.value.status_code == 409


def test_a_failed_housing_read_is_never_none_are_housing(db, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/minister_housing") else real(path, **kw))
    with pytest.raises(funds.Unavailable):
        funds.find_bank(BIZ, STAFF, housing_view=True, housing_only=True)
    got = funds.find_bank(BIZ, STAFF, housing_view=True)      # the rows still come, untagged
    assert got["count"] == 6 and got["housing"] == []


def test_a_fund_is_archived_before_its_placements_go(db, monkeypatch):
    funds.place(BIZ, OWNER, STAFF, [{"transaction_id": "tx_jul"}])
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path, **kw: False)
    funds.archive_fund(BIZ, STAFF)                             # the delete failed; the fund is gone all the same
    assert next(f for f in db.t["business_funds"] if f["id"] == STAFF)["archived_at"]
    assert len(db.t["business_fund_items"]) == 1               # left behind...
    assert "tx_jul" in {r["transaction_id"] for r in funds.find_bank(BIZ, BUILDING)["rows"]}   # ...holding nothing
