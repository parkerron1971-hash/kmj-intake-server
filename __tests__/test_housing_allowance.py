"""
test_housing_allowance.py — a minister's housing allowance, the owner's alone.

Kevin, 2026-10-30: "I do have a housing allowance setup. so we need structure
for this setup in the system"; who sees it: the owner only; paid through the
app's payroll or outside it, both.

Pins:
  * the figures: excludable is the least of designated, paid, spent and the
    fair rental value; anything paid above it is taxable; Box 14 is what was
    paid; a missing fair rental value or Board decision is said, not guessed
  * from November, next year's allowance not yet designated is a reminder
  * the owner alone: an admin seat, a stranger and nobody are refused; the
    switch off is a 404; another business's Board decision, person, employee
    or bank row can't be linked
  * one allowance per minister per year; an entry dated in another year is
    refused; a bank row or pay run counts once
  * Chief: the lookup quotes the figures, log is undone by delete, set
    records then changes; never on the agent surface
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_inverse  # noqa: E402
import action_registry  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import housing_allowance as ha  # noqa: E402
import sb_clients  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER = "00000000-0000-4000-8000-000000000001"
ADMIN = "00000000-0000-4000-8000-000000000002"
DECISION = "dddddddd-0000-4000-8000-000000000001"
THEIR_DECISION = "dddddddd-0000-4000-8000-000000000002"


def _allowance(**kw):
    a = {"id": "a1", "minister_name": "Pastor Kevin", "tax_year": 2026, "designated_amount": 30000,
         "designated_on": "2025-12-14", "board_decision_id": DECISION, "fair_rental_value": 28000}
    a.update(kw)
    return a


def _e(kind, amount, category=None):
    return {"kind": kind, "amount": amount, "category": category or ("allowance" if kind == "paid" else "other")}


# ─── The figures ─────────────────────────────────────────────────────

def test_excludable_is_the_least_of_the_four():
    f = ha.figures(_allowance(), [_e("paid", 30000), _e("spent", 26500, "rent_mortgage")],
                   today=date(2027, 1, 15))
    assert f["excludable"] == 26500 and f["limited_by"] == "spent"
    assert f["taxable_excess"] == 3500
    assert f["box_14"] == 30000 and f["final"] is True and f["left_to_pay"] == 0


def test_fair_rental_value_can_be_the_limit():
    f = ha.figures(_allowance(fair_rental_value=20000), [_e("paid", 30000), _e("spent", 29000)])
    assert f["excludable"] == 20000 and f["limited_by"] == "fair_rental_value"


def test_paid_less_than_designated_limits_it_and_shows_whats_left():
    f = ha.figures(_allowance(), [_e("paid", 12500), _e("spent", 20000)], today=date(2026, 6, 1))
    assert f["excludable"] == 12500 and f["limited_by"] == "paid"
    assert f["left_to_pay"] == 17500 and f["taxable_excess"] == 0 and f["final"] is False


def test_missing_pieces_are_named_not_guessed():
    f = ha.figures(_allowance(fair_rental_value=None, board_decision_id=None), [_e("paid", 1000)])
    assert f["fair_rental_value"] is None
    assert set(f["missing"]) == {"fair_rental_value", "board_decision"}
    text = ha.describe(_allowance(fair_rental_value=None, board_decision_id=None), f)
    assert "fair rental value isn't set" in text and "Board decision" in text


def test_spent_is_kept_by_category():
    f = ha.figures(_allowance(), [_e("spent", 1500, "utilities"), _e("spent", 2000, "rent_mortgage"),
                                  _e("spent", 500, "utilities")])
    assert f["spent_by_category"] == {"rent_mortgage": 2000, "utilities": 2000}


def test_next_years_designation_is_a_november_reminder():
    rows = [_allowance()]
    assert ha.reminders(rows, today=date(2026, 10, 30)) == []
    (r,) = ha.reminders(rows, today=date(2026, 11, 2))
    assert "2027 housing allowance isn't designated" in r and "before January 1" in r
    assert ha.reminders(rows + [_allowance(id="a2", tax_year=2027)], today=date(2026, 11, 2)) == []


# ─── Routes ──────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "owner_id": OWNER}, {"id": OTHER, "owner_id": ADMIN}],
        church_board_decisions=[{"id": DECISION, "business_id": BIZ},
                                {"id": THEIR_DECISION, "business_id": OTHER}],
        contacts=[], employees=[],
        plaid_transactions=[{"transaction_id": "tx_1", "business_id": BIZ},
                            {"transaction_id": "tx_theirs", "business_id": OTHER}],
        pay_run_items=[], minister_housing_allowances=[], minister_housing_entries=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("HOUSING_ALLOWANCE", "on")
    return fake


def _client(user_id):
    app = FastAPI()
    app.include_router(ha.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email="x@y.z", role="authenticated")
    return TestClient(app)


BODY = {"business_id": BIZ, "minister_name": "Pastor Kevin", "tax_year": 2026,
        "designated_amount": 30000, "designated_on": "2025-12-14", "board_decision_id": DECISION,
        "fair_rental_value": 28000}


def test_the_owner_records_an_allowance_and_reads_its_figures(db):
    c = _client(OWNER)
    r = c.post("/housing-allowance", json=BODY)
    assert r.status_code == 200, r.text
    aid = r.json()["allowance"]["id"]
    assert c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "paid", "amount": 2500, "entry_date": "2026-01-31"}).status_code == 200
    assert c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "spent", "amount": 1800, "category": "rent_mortgage",
        "entry_date": "2026-02-01"}).status_code == 200
    got = c.get(f"/housing-allowance?business_id={BIZ}").json()
    (a,) = got["allowances"]
    assert a["figures"]["paid"] == 2500 and a["figures"]["spent"] == 1800
    assert "tax preparer" in got["care"]


@pytest.mark.parametrize("who", [ADMIN, "00000000-0000-4000-8000-000000000009"])
def test_anyone_but_the_owner_is_refused(db, who):
    c = _client(who)
    assert c.get(f"/housing-allowance?business_id={BIZ}").status_code == 403
    assert c.post("/housing-allowance", json=BODY).status_code == 403


def test_switched_off_is_not_there(db, monkeypatch):
    monkeypatch.setenv("HOUSING_ALLOWANCE", "off")
    assert _client(OWNER).get(f"/housing-allowance?business_id={BIZ}").status_code == 404


def test_another_businesss_records_cant_be_linked(db):
    c = _client(OWNER)
    assert c.post("/housing-allowance", json={**BODY, "board_decision_id": THEIR_DECISION}).status_code == 400
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    r = c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "paid", "amount": 100, "entry_date": "2026-03-01",
        "source": "bank", "source_id": "tx_theirs"})
    assert r.status_code == 400


def test_one_allowance_a_minister_a_year(db):
    c = _client(OWNER)
    assert c.post("/housing-allowance", json=BODY).status_code == 200
    assert c.post("/housing-allowance", json={**BODY, "minister_name": "pastor kevin"}).status_code == 409
    assert c.post("/housing-allowance", json={**BODY, "tax_year": 2027}).status_code == 200


def test_an_entry_belongs_to_its_year_and_a_bank_row_counts_once(db):
    c = _client(OWNER)
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    base = {"business_id": BIZ, "kind": "paid", "amount": 100}
    assert c.post(f"/housing-allowance/{aid}/entries", json={**base, "entry_date": "2025-12-31"}).status_code == 400
    bank = {**base, "entry_date": "2026-03-01", "source": "bank", "source_id": "tx_1"}
    assert c.post(f"/housing-allowance/{aid}/entries", json=bank).status_code == 200
    assert c.post(f"/housing-allowance/{aid}/entries", json=bank).status_code == 409


def test_spent_needs_a_real_category(db):
    c = _client(OWNER)
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    r = c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "spent", "amount": 50, "category": "boat", "entry_date": "2026-04-01"})
    assert r.status_code == 400


def test_a_failed_read_is_a_503_not_nothing(db, monkeypatch):
    c = _client(OWNER)
    real = sb_clients.sb_get_as_service

    def flaky(path, **kw):
        return None if path.startswith("/minister_housing") else real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", flaky)
    assert c.get(f"/housing-allowance?business_id={BIZ}").status_code == 503


# ─── Chief ───────────────────────────────────────────────────────────

@pytest.fixture
def speaking(db):
    token = cos._TURN_USER_ID.set(OWNER)
    yield db
    cos._TURN_USER_ID.reset(token)


def _run(handler, action):
    return asyncio.run(handler(None, {"id": BIZ, "owner_id": OWNER}, action))


def test_chief_records_logs_and_reads(speaking):
    r = _run(ha.handle_set_housing_allowance, {"minister_name": "Pastor Kevin", "tax_year": 2026,
                                               "designated_amount": 30000, "designated_on": "2025-12-14"})
    assert r["result"].startswith("Recorded Pastor Kevin's 2026 housing allowance: $30,000.00")
    r = _run(ha.handle_set_housing_allowance, {"minister_name": "Pastor Kevin", "tax_year": 2026,
                                               "fair_rental_value": 28000})
    assert r["result"].startswith("Changed")
    logged = _run(ha.handle_log_housing_entry, {"kind": "spent", "amount": 1200, "category": "utilities",
                                                "entry_date": "2026-05-01", "tax_year": 2026})
    assert logged["entry_id"] and "of utilities" in logged["result"]
    status = _run(ha.handle_housing_allowance_status, {"tax_year": 2026})
    assert "designated $30,000.00" in status["result"]
    assert "housing costs logged $1,200.00" in status["result"]
    inv = action_inverse.build_inverse("log_housing_entry", {}, logged)
    gone = _run(ha.handle_delete_housing_entry, inv)
    assert gone["result"].startswith("Removed the $1,200.00 entry")


def test_chief_refuses_anyone_but_the_owner(db):
    token = cos._TURN_USER_ID.set(ADMIN)
    try:
        r = _run(ha.handle_housing_allowance_status, {})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert r["failed"] and "owner's alone" in r["result"]


def test_chief_with_nothing_recorded_says_so(speaking):
    r = _run(ha.handle_housing_allowance_status, {})
    assert r["result"].startswith("No housing allowance is recorded")


def test_never_on_the_agent_surface_and_placed_for_lanes():
    import chief_areas
    import chief_tool_loop as ctl
    for verb in ("housing_allowance_status", "set_housing_allowance", "log_housing_entry",
                 "delete_housing_entry"):
        assert not action_registry.may_expose_to_agent(verb, allow_writes=True), verb
        assert verb in chief_areas.OWNERS and verb in cos.ACTION_HANDLERS
    assert action_registry.is_sensitive("housing_allowance_status")
    assert "housing_allowance_status" in {t["name"] for t in ctl.read_tool_definitions()}
    assert action_inverse.can_undo("log_housing_entry")
    assert not action_inverse.can_undo("set_housing_allowance")
