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


# ─── The paper trail (2026-10-31) ────────────────────────────────────
# Kevin: "add these structure and rules in there as well" (what the IRS
# would ask to see).

def _dated(kind, amount, on, category=None, **kw):
    return {**_e(kind, amount, category), "entry_date": on, **kw}


def test_allowance_paid_before_the_vote_is_taxable_salary():
    """The board votes February 10; January's $2,000 was paid with no
    designation in place, so it's salary, not housing allowance."""
    a = _allowance(designated_amount=24000, designated_on="2026-02-10", fair_rental_value=None)
    entries = [_dated("paid", 2000, "2026-01-31"), _dated("paid", 2000, "2026-02-28"),
               _dated("spent", 30000, "2026-03-01", "rent_mortgage")]
    f = ha.figures(a, entries, today=date(2027, 1, 15))
    assert f["paid"] == 4000 and f["paid_before_designation"] == 2000
    assert f["excludable"] == 2000 and f["limited_by"] == "paid"
    assert f["taxable_excess"] == 2000                  # January's $2,000
    assert f["box_14"] == 2000                          # it goes in Box 1, not 14
    assert f["left_to_pay"] == 22000
    assert "paid before the board's vote" in ha.describe(a, f)
    (step,) = [s for s in ha.paper_trail(a, entries, f, today=date(2027, 1, 15)) if s["key"] == "in_advance"]
    assert step["state"] == "warn" and "$2,000.00" in step["detail"] and "Box 1" in step["detail"]


def test_a_fresh_record_lists_what_the_irs_would_ask_for():
    a = _allowance(board_decision_id=None, fair_rental_value=None)
    f = ha.figures(a, [], today=date(2026, 10, 31))
    trail = {s["key"]: s for s in ha.paper_trail(a, [], f, today=date(2026, 10, 31))}
    assert list(trail) == ["board_vote", "in_advance", "independent", "credential", "se_tax",
                           "fair_rental", "receipts", "w2"]
    assert trail["board_vote"]["state"] == "todo" and "Board & minutes" in trail["board_vote"]["detail"]
    assert trail["in_advance"]["state"] == "done"
    assert trail["independent"]["state"] == "todo"
    assert "stepped out of the vote" in trail["independent"]["detail"]
    assert "similar churches" in trail["independent"]["detail"]
    assert trail["credential"]["state"] == "todo"
    assert "ordained, licensed or commissioned" in trail["credential"]["detail"].lower()
    assert trail["se_tax"]["state"] == "todo" and "January 15, 2027" in trail["se_tax"]["detail"]
    assert trail["fair_rental"]["state"] == "todo"
    assert trail["receipts"]["state"] == "later"
    assert trail["w2"]["state"] == "later" and "January 2027" in trail["w2"]["label"]
    assert ha.open_steps(list(trail.values())) == [trail[k]["label"] for k in
                                                   ("board_vote", "independent", "credential", "se_tax",
                                                    "fair_rental")]


def test_a_complete_record_has_nothing_left():
    a = _allowance(minister_recused=True, comparables_note="2026 survey: three churches our size",
                   minister_credential="ordained", credential_detail="Ordained 2009, Love City",
                   se_tax_plan="estimates", cash_salary=50000, fair_rental_basis="Realtor's letter, May 2026",
                   receipts_kept_where=None, w2_checked_on="2027-01-30")
    entries = [_dated("paid", 30000, "2026-06-01"),
               _dated("spent", 26000, "2026-06-01", "rent_mortgage", receipt_path="x", receipt_type="pdf")]
    f = ha.figures(a, entries, today=date(2027, 2, 1))
    trail = ha.paper_trail(a, entries, f, today=date(2027, 2, 1))
    assert {s["state"] for s in trail} == {"done"}
    assert ha.open_steps(trail) == []
    (se,) = [s for s in trail if s["key"] == "se_tax"]
    assert "$11,303.64" in se["detail"]                 # 14.13% of $80,000
    assert "next quarterly estimate" not in se["detail"]     # all four dates for 2026 have passed


def test_the_minister_voting_on_their_own_allowance_is_a_warning():
    a = _allowance(minister_recused=False, comparables_note="survey")
    f = ha.figures(a, [])
    (step,) = [s for s in ha.paper_trail(a, [], f) if s["key"] == "independent"]
    assert step["state"] == "warn" and "vote again without Pastor Kevin" in step["detail"]


def test_receipts_are_counted_or_said_where_they_are():
    a = _allowance()
    entries = [_dated("spent", 100, "2026-03-01", receipt_path="x", receipt_type="image"),
               _dated("spent", 200, "2026-04-01")]
    f = ha.figures(a, entries)
    (step,) = [s for s in ha.paper_trail(a, entries, f) if s["key"] == "receipts"]
    assert step["state"] == "todo" and step["detail"].startswith("1 of 2 housing costs have no receipt")
    a["receipts_kept_where"] = "the blue folder in the office"
    (step,) = [s for s in ha.paper_trail(a, entries, f) if s["key"] == "receipts"]
    assert step["state"] == "done" and "blue folder" in step["detail"]


def test_self_employment_tax_estimate_and_due_dates():
    f = ha.figures(_allowance(designated_amount=30000), [])
    assert ha.se_tax_estimate(_allowance(cash_salary=50000), f) == 11303.64
    assert ha.se_tax_estimate(_allowance(), f) is None
    # Over the Social Security wage base, only Medicare keeps going.
    big = ha.se_tax_estimate(_allowance(cash_salary=300000), f)
    assert big == round(0.124 * 184500 + 0.029 * 0.9235 * 330000, 2)
    # The IRS's own dates: weekends, Martin Luther King Day, DC Emancipation Day.
    assert ha.estimate_dates(2022) == [date(2022, 4, 18), date(2022, 6, 15), date(2022, 9, 15),
                                       date(2023, 1, 17)]
    assert ha.estimate_dates(2023)[0] == date(2023, 4, 18)
    assert ha.estimate_dates(2023)[3] == date(2024, 1, 16)
    assert ha.next_estimate(2026, today=date(2026, 10, 31)) == date(2027, 1, 15)
    assert ha.next_estimate(2026, today=date(2027, 1, 16)) is None


def test_the_owner_fills_in_the_paper_trail(db):
    c = _client(OWNER)
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    r = c.patch(f"/housing-allowance/{aid}", json={
        "business_id": BIZ, "minister_recused": True, "comparables_note": "  three   churches  ",
        "minister_credential": "Licensed", "se_tax_plan": "withholding", "cash_salary": 42000,
        "fair_rental_basis": "listings", "w2_checked_on": None})
    assert r.status_code == 200, r.text
    row = db.t["minister_housing_allowances"][0]
    assert row["minister_credential"] == "licensed" and row["comparables_note"] == "three churches"
    assert row["minister_recused"] is True and row["cash_salary"] == 42000
    for bad in ({"minister_credential": "pastor"}, {"se_tax_plan": "later"}, {"cash_salary": -1},
                {"w2_checked_on": "2999-01-01"}):
        assert c.patch(f"/housing-allowance/{aid}", json={"business_id": BIZ, **bad}).status_code == 400, bad
    (a,) = c.get(f"/housing-allowance?business_id={BIZ}").json()["allowances"]
    keys = {s["key"]: s["state"] for s in a["paper_trail"]}
    assert keys["independent"] == keys["credential"] == keys["se_tax"] == keys["fair_rental"] == "done"


@pytest.fixture
def bucket(db, monkeypatch):
    import church_checks
    import storage_links
    files = {}

    def put(path, data, media):
        files[path] = data
        return True, 200, ""
    monkeypatch.setattr(church_checks, "_storage_put", put)
    monkeypatch.setattr(church_checks, "_storage_get", lambda path: files.get(path))
    monkeypatch.setattr(church_checks, "_storage_drop", lambda path: files.pop(path, None))
    monkeypatch.setattr(storage_links, "has_service_key", lambda: True)
    return files


def test_a_housing_cost_keeps_its_receipt_for_the_owner_alone(bucket, db):
    c = _client(OWNER)
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    paid = c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "paid", "amount": 100, "entry_date": "2026-03-01"}).json()["entry"]
    cost = c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "spent", "amount": 1800, "category": "rent_mortgage",
        "entry_date": "2026-03-01"}).json()["entry"]
    assert cost["receipt"] is None and "receipt_path" not in cost
    pdf = ("receipt.pdf", b"%PDF-1.4 mortgage statement", "application/pdf")
    r = c.post(f"/housing-allowance/entries/{cost['id']}/receipt", data={"business_id": BIZ}, files={"file": pdf})
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["receipt"] == "pdf" and "receipt_path" not in r.json()["entry"]
    (path,) = bucket
    assert path.startswith(f"{BIZ}/housing-receipts/") and path.endswith(".pdf")
    # Not on allowance paid; not for anyone but the owner.
    assert c.post(f"/housing-allowance/entries/{paid['id']}/receipt", data={"business_id": BIZ},
                  files={"file": pdf}).status_code == 400
    admin = _client(ADMIN).get(f"/housing-allowance/entries/{cost['id']}/receipt?business_id={BIZ}")
    assert admin.status_code == 403
    got = c.get(f"/housing-allowance/entries/{cost['id']}/receipt?business_id={BIZ}")
    assert got.status_code == 200 and got.content.startswith(b"%PDF")
    assert "no-store" in got.headers["cache-control"]
    (a,) = c.get(f"/housing-allowance?business_id={BIZ}").json()["allowances"]
    assert [e["receipt"] for e in a["entries"] if e["kind"] == "spent"] == ["pdf"]
    assert {s["key"]: s["state"] for s in a["paper_trail"]}["receipts"] == "done"
    # A replacement drops the old file; removing the entry drops its receipt.
    c.post(f"/housing-allowance/entries/{cost['id']}/receipt", data={"business_id": BIZ}, files={"file": pdf})
    assert len(bucket) == 1 and path not in bucket
    assert c.delete(f"/housing-allowance/entries/{cost['id']}?business_id={BIZ}").status_code == 200
    assert bucket == {}


def test_a_receipt_path_from_elsewhere_is_never_served(bucket, db):
    c = _client(OWNER)
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    cost = c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "spent", "amount": 50, "category": "utilities",
        "entry_date": "2026-03-01"}).json()["entry"]
    row = next(e for e in db.t["minister_housing_entries"] if e["id"] == cost["id"])
    row.update(receipt_path=f"{BIZ}/check-requests/{'a' * 32}.pdf", receipt_type="pdf")
    bucket[row["receipt_path"]] = b"%PDF the treasurer's"
    assert c.get(f"/housing-allowance/entries/{cost['id']}/receipt?business_id={BIZ}").status_code == 404


def test_chief_names_whats_left_on_the_paper_trail_and_records_it(speaking):
    _run(ha.handle_set_housing_allowance, {"minister_name": "Pastor Kevin", "tax_year": 2026,
                                           "designated_amount": 30000, "designated_on": "2025-12-14"})
    status = _run(ha.handle_housing_allowance_status, {"tax_year": 2026})
    assert "Paper trail, still to do: Record the board's vote" in status["result"]
    assert status["allowances"][0]["paper_trail"]
    # No name: the year's only allowance.
    r = _run(ha.handle_set_housing_allowance, {"tax_year": 2026, "minister_credential": "ordained",
                                               "minister_recused": True})
    assert r["result"].startswith("Changed"), r
    status = _run(ha.handle_housing_allowance_status, {"tax_year": 2026})
    assert "Say how" not in status["result"]


def test_chief_says_allowance_logged_before_the_vote_is_salary(speaking):
    _run(ha.handle_set_housing_allowance, {"minister_name": "Pastor Kevin", "tax_year": 2026,
                                           "designated_amount": 24000, "designated_on": "2026-02-10"})
    early = _run(ha.handle_log_housing_entry, {"kind": "paid", "amount": 2000, "entry_date": "2026-01-31",
                                               "tax_year": 2026})
    assert "before the board's vote on February 10, 2026" in early["result"]
    assert "W-2 Box 1" in early["result"] and "Paid since the vote $0.00 of $24,000.00" in early["result"]
    later = _run(ha.handle_log_housing_entry, {"kind": "paid", "amount": 2000, "entry_date": "2026-02-28",
                                               "tax_year": 2026})
    assert "before the board's vote" not in later["result"]
    assert "Paid since the vote $2,000.00 of $24,000.00" in later["result"]


def _a_cost(c):
    aid = c.post("/housing-allowance", json=BODY).json()["allowance"]["id"]
    return c.post(f"/housing-allowance/{aid}/entries", json={
        "business_id": BIZ, "kind": "spent", "amount": 1800, "category": "rent_mortgage",
        "entry_date": "2026-03-01"}).json()["entry"]


PDF = ("receipt.pdf", b"%PDF-1.4 mortgage statement", "application/pdf")


def test_a_receipt_the_record_wont_take_is_dropped_from_the_bucket(bucket, db, monkeypatch):
    c = _client(OWNER)
    cost = _a_cost(c)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: None)
    r = c.post(f"/housing-allowance/entries/{cost['id']}/receipt", data={"business_id": BIZ}, files={"file": PDF})
    assert r.status_code == 503
    assert bucket == {}                                 # no orphaned private file


def test_a_refused_upload_is_a_503_and_nothing_is_recorded(bucket, db, monkeypatch):
    import church_checks
    c = _client(OWNER)
    cost = _a_cost(c)
    monkeypatch.setattr(church_checks, "_storage_put", lambda path, data, media: (False, 403, "denied"))
    r = c.post(f"/housing-allowance/entries/{cost['id']}/receipt", data={"business_id": BIZ}, files={"file": PDF})
    assert r.status_code == 503
    row = next(e for e in db.t["minister_housing_entries"] if e["id"] == cost["id"])
    assert not row.get("receipt_path")


def test_a_receipt_that_cant_be_read_is_a_503_not_an_empty_file(bucket, db, monkeypatch):
    import church_checks
    c = _client(OWNER)
    cost = _a_cost(c)
    assert c.post(f"/housing-allowance/entries/{cost['id']}/receipt", data={"business_id": BIZ},
                  files={"file": PDF}).status_code == 200
    monkeypatch.setattr(church_checks, "_storage_get", lambda path: None)
    assert c.get(f"/housing-allowance/entries/{cost['id']}/receipt?business_id={BIZ}").status_code == 503


# ─── From the bank (2026-10-31) ──────────────────────────────────────
# Kevin: "i want to know exactly based on transaction how much has been paid
# out ... ask chief to go through the transaction and help me find what was
# paid out and attach it to the housing payouts".

AID = "aaaaaaaa-0000-4000-8000-000000000001"
AID2 = "aaaaaaaa-0000-4000-8000-000000000002"
TYPED = "eeeeeeee-0000-4000-8000-000000000001"


def _tx(tid, on, amount, name="ONLINE TRANSFER TO CHK 4417 REF #IB%s", **kw):
    return {"transaction_id": tid, "business_id": kw.pop("business_id", BIZ),
            "account_id": kw.pop("account_id", "acc_books"), "date": on,
            "name": name % tid[-2:] if "%s" in name else name, "merchant_name": None,
            "amount": amount, "pending": False, "excluded_from_books": False, **kw}


@pytest.fixture
def bank(monkeypatch):
    fake = FakeDB(
        businesses=[{"id": BIZ, "owner_id": OWNER}, {"id": OTHER, "owner_id": ADMIN}],
        plaid_accounts=[
            {"account_id": "acc_books", "business_id": BIZ, "included_in_bookkeeping": True, "deleted_at": None},
            {"account_id": "acc_personal", "business_id": BIZ, "included_in_bookkeeping": False, "deleted_at": None}],
        plaid_transactions=[
            _tx("tx_first", "2026-07-17", 40, name="BANK FEE"),   # the first day the app has
            _tx("tx_jul", "2026-07-31", 1500), _tx("tx_aug", "2026-08-31", 1500), _tx("tx_sep", "2026-09-30", 1500),
            _tx("tx_pay", "2026-10-15", 4200, name="GUSTO NET PAY 2210"),
            _tx("tx_light", "2026-08-03", 212.40, name="=CLEVELAND ELECTRIC"),
            _tx("tx_in", "2026-08-02", -900, name="SUNDAY DEPOSIT"),
            _tx("tx_pending", "2026-10-30", 1500, pending=True),
            _tx("tx_2025", "2025-12-31", 1500),
            _tx("tx_personal", "2026-09-01", 1500, account_id="acc_personal"),
            _tx("tx_theirs", "2026-09-01", 1500, business_id=OTHER)],
        minister_housing_allowances=[
            {"id": AID, "business_id": BIZ, "minister_name": "Pastor Kevin", "tax_year": 2026,
             "designated_amount": 18000, "designated_on": "2026-08-15", "archived_at": None},
            {"id": AID2, "business_id": BIZ, "minister_name": "Pastor Dee", "tax_year": 2026,
             "designated_amount": 6000, "designated_on": "2026-01-05", "archived_at": None}],
        minister_housing_entries=[])
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("HOUSING_ALLOWANCE", "on")
    return fake


def _bank_entries(fake):
    return sorted(fake.t["minister_housing_entries"], key=lambda e: e["entry_date"])


def test_find_lists_the_years_payments_out_and_the_repeats(bank):
    got = ha.find_bank_payments(BIZ, AID)
    ids = {r["transaction_id"] for r in got["rows"]}
    # Money in, pending, last year, an account outside the books and another
    # business's rows are never candidates.
    assert ids == {"tx_jul", "tx_aug", "tx_sep", "tx_pay", "tx_light", "tx_first"}
    assert got["count"] == 6 and got["total"] == round(1500 * 3 + 4200 + 212.40 + 40, 2)
    (rep,) = got["repeats"]
    assert rep["amount"] == 1500 and rep["count"] == 3 and rep["transaction_ids"] == ["tx_jul", "tx_aug", "tx_sep"]
    assert got["history_starts"] == "2026-07-17" and got["history_late"] is True
    assert [r["transaction_id"] for r in got["rows"]][:2] == ["tx_pay", "tx_sep"]          # newest first
    narrowed = ha.find_bank_payments(BIZ, AID, words=["gusto"])
    assert [r["transaction_id"] for r in narrowed["rows"]] == ["tx_pay"]
    assert {r["transaction_id"] for r in ha.find_bank_payments(BIZ, AID, amount=1500)["rows"]} == {
        "tx_jul", "tx_aug", "tx_sep"}


def test_attach_ties_whole_payments_and_the_housing_part_of_a_paycheck(bank):
    done = ha.attach_bank_payments(BIZ, OWNER, AID, [
        {"transaction_id": "tx_aug"}, {"transaction_id": "tx_sep"},
        {"transaction_id": "tx_pay", "amount": 1500}])
    assert done["total"] == 4500 and len(done["created_ids"]) == 3 and done["restore"] == []
    rows = _bank_entries(bank)
    assert [(e["entry_date"], e["amount"], e["source"], e["source_id"]) for e in rows] == [
        ("2026-08-31", 1500, "bank", "tx_aug"), ("2026-09-30", 1500, "bank", "tx_sep"),
        ("2026-10-15", 1500, "bank", "tx_pay")]
    assert rows[2]["note"].startswith("Bank: GUSTO NET PAY") and "part of $4,200.00" in rows[2]["note"]
    # Tied once: again is a 409, and the paycheck's other $2,700 is what's left
    # for anyone else's allowance, never more.
    with pytest.raises(ha.HTTPException) as again:
        ha.attach_bank_payments(BIZ, OWNER, AID, [{"transaction_id": "tx_aug"}])
    assert again.value.status_code == 409
    left = {r["transaction_id"]: r for r in ha.find_bank_payments(BIZ, AID2)["rows"]}
    assert left["tx_pay"]["left"] == 2700 and "tx_aug" not in left
    with pytest.raises(ha.HTTPException) as over:
        ha.attach_bank_payments(BIZ, OWNER, AID2, [{"transaction_id": "tx_pay", "amount": 3000}])
    assert over.value.status_code == 400 and "$2,700.00 of it is left" in over.value.detail


@pytest.mark.parametrize("tid, says", [
    ("tx_in", "money coming in"), ("tx_pending", "still pending"), ("tx_2025", "outside 2026"),
    ("tx_theirs", "isn't a bank payment of this business"), ("nope!", "needs the bank payment"),
    ("tx_personal", "isn't in the books")])
def test_attach_is_all_or_none(bank, tid, says):
    with pytest.raises(ha.HTTPException) as e:
        ha.attach_bank_payments(BIZ, OWNER, AID, [{"transaction_id": "tx_jul"}, {"transaction_id": tid}])
    assert says in e.value.detail
    assert bank.t["minister_housing_entries"] == []


def test_a_typed_in_payment_is_tied_not_counted_twice_and_undo_puts_it_back(bank):
    bank.t["minister_housing_entries"].append({
        "id": TYPED, "business_id": BIZ, "allowance_id": AID, "kind": "paid", "category": "allowance",
        "entry_date": "2026-09-28", "amount": 1500, "source": "manual", "source_id": None, "note": "Sept"})
    found = {r["transaction_id"]: r for r in ha.find_bank_payments(BIZ, AID)["rows"]}
    assert found["tx_sep"]["typed_in"] == {"entry_id": TYPED, "entry_date": "2026-09-28"}
    token = cos._TURN_USER_ID.set(OWNER)
    try:
        r = _run(ha.handle_attach_housing_payments, {"transaction_ids": ["tx_aug", "tx_sep"], "minister_name": "kevin"})
        assert not r.get("failed"), r["result"]
        assert "1 of them were already typed in" in r["result"]
        rows = _bank_entries(bank)
        assert len(rows) == 2 and {e["source"] for e in rows} == {"bank"}
        typed = next(e for e in rows if e["id"] == TYPED)
        assert typed["source_id"] == "tx_sep" and typed["entry_date"] == "2026-09-30"
        inv = action_inverse.build_inverse("attach_housing_payments", {}, r)
        back = _run(ha.handle_detach_housing_payments, inv)
    finally:
        cos._TURN_USER_ID.reset(token)
    assert "removed 1" in back["result"] and "1 are typed-in again" in back["result"]
    (left,) = bank.t["minister_housing_entries"]
    assert left["id"] == TYPED and left["source"] == "manual" and left["source_id"] is None
    assert left["entry_date"] == "2026-09-28"


def test_detach_never_touches_a_typed_in_or_pay_run_entry(bank):
    bank.t["minister_housing_entries"].append({
        "id": TYPED, "business_id": BIZ, "allowance_id": AID, "kind": "paid", "category": "allowance",
        "entry_date": "2026-02-01", "amount": 1500, "source": "manual", "source_id": None, "note": ""})
    assert ha.detach_bank_payments(BIZ, [TYPED], []) == {"removed": 0, "untied": 0}
    assert len(bank.t["minister_housing_entries"]) == 1


def test_a_failed_delete_is_a_503_not_success(bank, monkeypatch):
    done = ha.attach_bank_payments(BIZ, OWNER, AID, [{"transaction_id": "tx_aug"}])
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda path, **kw: False)
    with pytest.raises(ha.HTTPException) as e:
        ha.detach_bank_payments(BIZ, done["created_ids"], [])
    assert e.value.status_code == 503
    with pytest.raises(ha.HTTPException) as e:
        ha.delete_entry(BIZ, done["created_ids"][0])
    assert e.value.status_code == 503


def test_the_record_shows_each_payments_bank_row_and_where_paid_came_from(bank):
    ha.attach_bank_payments(BIZ, OWNER, AID, [{"transaction_id": "tx_aug"}, {"transaction_id": "tx_jul"}])
    ha.add_entry(BIZ, OWNER, AID, {"kind": "paid", "amount": 1500, "entry_date": "2026-03-31"})
    got = ha.summary(BIZ, 2026)
    a = next(x for x in got["allowances"] if x["id"] == AID)
    assert a["paid_from"]["bank"] == {"count": 2, "amount": 3000}
    assert a["paid_from"]["manual"] == {"count": 1, "amount": 1500}
    bank_rows = [e["bank"] for e in a["entries"] if e.get("bank")]
    assert {"date": "2026-08-31", "description": "ONLINE TRANSFER TO CHK 4417 REF #IBug", "amount": 1500} in bank_rows
    assert got["bank"] == {"accounts": 1, "history_starts": "2026-07-17"}
    # July's $1,500 came before the August 15 vote: salary, not allowance.
    assert a["figures"]["paid_before_designation"] == 3000
    token = cos._TURN_USER_ID.set(OWNER)
    try:
        status = _run(ha.handle_housing_allowance_status, {"tax_year": 2026})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert "$3,000.00 tied to a bank payment, $1,500.00 typed in" in status["result"]


def test_the_report_puts_each_payment_beside_its_bank_row(bank):
    bank.t["minister_housing_entries"].append({
        "id": TYPED, "business_id": BIZ, "allowance_id": AID, "kind": "spent", "category": "utilities",
        "entry_date": "2026-08-03", "amount": 212.40, "source": "manual", "source_id": None,
        "note": "-light bill", "receipt_path": None})
    ha.attach_bank_payments(BIZ, OWNER, AID, [{"transaction_id": "tx_aug"}, {"transaction_id": "tx_jul"}])
    c = _client(OWNER)
    r = c.get(f"/housing-allowance/{AID}/report.csv?business_id={BIZ}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="housing-allowance-2026-pastor-kevin.csv"' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "private, no-store"
    text = r.content.decode("utf-8-sig")
    assert "2026-08-31,Allowance paid,,1500.00,tied to a bank payment,2026-08-31,ONLINE TRANSFER" in text
    assert "2026-07-31,Allowance paid,,1500.00,tied to a bank payment,2026-07-31" in text and ",Yes,," in text
    assert "'-light bill" in text                       # never a formula
    assert "Tied to a bank payment (2),,3000.00" in text
    assert "Paid since the vote: W-2 Box 14,,1500.00" in text
    assert "starts July 17, 2026" in text


def test_the_bank_routes_are_the_owners_alone(bank):
    for who in (ADMIN, "00000000-0000-4000-8000-000000000009"):
        c = _client(who)
        assert c.get(f"/housing-allowance/{AID}/bank?business_id={BIZ}").status_code == 403
        assert c.post(f"/housing-allowance/{AID}/bank", json={
            "business_id": BIZ, "items": [{"transaction_id": "tx_aug"}]}).status_code == 403
        assert c.post("/housing-allowance/bank/detach", json={"business_id": BIZ, "remove_ids": [AID]}).status_code == 403
        assert c.get(f"/housing-allowance/{AID}/report.csv?business_id={BIZ}").status_code == 403
    assert bank.t["minister_housing_entries"] == []
    c = _client(OWNER)
    got = c.get(f"/housing-allowance/{AID}/bank?business_id={BIZ}&q=transfer&amount=1500").json()
    assert got["count"] == 3 and "allowance" not in got
    tied = c.post(f"/housing-allowance/{AID}/bank", json={
        "business_id": BIZ, "items": [{"transaction_id": "tx_sep"}]}).json()
    assert tied["total"] == 1500 and tied["figures"]["paid_since_designation"] == 1500
    gone = c.post("/housing-allowance/bank/detach", json={"business_id": BIZ, "remove_ids": tied["created_ids"]})
    assert gone.json() == {"ok": True, "removed": 1, "untied": 0}


def test_chief_finds_with_the_servers_numbers_and_says_where_history_starts(bank):
    token = cos._TURN_USER_ID.set(OWNER)
    try:
        r = _run(ha.handle_find_housing_payments, {"minister_name": "kevin"})
        none = _run(ha.handle_find_housing_payments, {"tax_year": 2025})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert not r.get("failed"), r["result"]
    assert r["result"].startswith("Pastor Kevin's 2026 housing allowance: 6 payment(s) out of the bank aren't on "
                                  "its record yet, $8,952.40 in all.")
    assert "starts July 17, 2026" in r["result"]
    assert "$1,500.00 × 3 (Jul 31, Aug 31, Sep 30)" in r["result"]
    assert "transaction_ids tx_jul, tx_aug, tx_sep" in r["result"]
    assert "not proof" in r["note_for_chief"]
    assert none["failed"] and "no 2025 housing allowance" in none["result"]


def test_chief_refuses_anyone_but_the_owner_the_bank(bank):
    token = cos._TURN_USER_ID.set(ADMIN)
    try:
        r = _run(ha.handle_find_housing_payments, {})
        a = _run(ha.handle_attach_housing_payments, {"transaction_ids": ["tx_aug"]})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert r["failed"] and a["failed"] and "owner's alone" in a["result"]
    assert bank.t["minister_housing_entries"] == []


def test_the_bank_verbs_are_placed_and_one_undo_covers_the_batch():
    import chief_areas
    import chief_prompt
    import chief_tool_loop as ctl
    for verb in ("find_housing_payments", "attach_housing_payments", "detach_housing_payments"):
        assert not action_registry.may_expose_to_agent(verb, allow_writes=True), verb
        assert verb in chief_areas.OWNERS and verb in cos.ACTION_HANDLERS
        assert f'"type":"{verb}"' in open(chief_prompt.__file__, encoding="utf-8").read(), verb
    assert action_registry.is_sensitive("find_housing_payments")
    assert action_registry.is_bulk("attach_housing_payments")
    assert not action_registry.is_bulk("detach_housing_payments")
    assert "find_housing_payments" in {t["name"] for t in ctl.read_tool_definitions()}
    assert action_inverse.can_undo("attach_housing_payments")
    assert action_inverse.build_inverse("attach_housing_payments", {}, {"created_ids": [], "restore": []}) is None


def test_a_failed_bank_read_is_never_nothing(bank, monkeypatch):
    real = sb_clients.sb_get_as_service

    def no_bank(path, **kw):
        return None if path.startswith("/plaid_transactions") else real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", no_bank)
    with pytest.raises(ha.Unavailable):
        ha.find_bank_payments(BIZ, AID)
    assert _client(OWNER).get(f"/housing-allowance/{AID}/bank?business_id={BIZ}").status_code == 503
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    ha.attach_bank_payments(BIZ, OWNER, AID, [{"transaction_id": "tx_aug"}])
    monkeypatch.setattr(sb_clients, "sb_get_as_service", no_bank)
    a = next(x for x in ha.summary(BIZ, 2026)["allowances"] if x["id"] == AID)
    assert a["bank_read"] is False and a["figures"]["paid"] == 1500      # the record still reads


def test_tied_but_the_totals_unread_still_says_tied_and_keeps_the_undo(bank, monkeypatch):
    real = sb_clients.sb_get_as_service
    tied = {"done": False}
    real_attach = ha.attach_bank_payments

    def attach(*a, **kw):
        out = real_attach(*a, **kw)
        tied["done"] = True
        return out

    def after(path, **kw):
        return None if tied["done"] and path.startswith("/minister_housing_entries") else real(path, **kw)
    monkeypatch.setattr(ha, "attach_bank_payments", attach)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", after)
    r = _client(OWNER).post(f"/housing-allowance/{AID}/bank", json={
        "business_id": BIZ, "items": [{"transaction_id": "tx_aug"}]})
    assert r.status_code == 200 and r.json()["figures"] is None and len(r.json()["created_ids"]) == 1
    tied["done"] = False
    token = cos._TURN_USER_ID.set(OWNER)
    try:
        c = _run(ha.handle_attach_housing_payments, {"transaction_ids": ["tx_sep"], "minister_name": "kevin"})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert not c.get("failed") and c["result"].startswith("Tied 1 bank payment(s), $1,500.00")
    assert "couldn't be read just now" in c["result"] and len(c["created_ids"]) == 1


def test_a_formula_name_is_quoted_in_the_report(bank):
    bank.t["minister_housing_allowances"][0]["minister_name"] = "=HYPERLINK(1)"
    text, _ = ha.report_csv(BIZ, AID)
    assert text.startswith("'=HYPERLINK(1): 2026 housing allowance")
