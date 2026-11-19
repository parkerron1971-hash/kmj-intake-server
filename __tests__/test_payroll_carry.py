"""Payroll, the free version: last time's typed withholding carried into a new
run (payroll_carry.py, payroll_router.create_run / update_item). Made up."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import payroll_carry
import payroll_router as pr
from payroll_free_fake import (CHURCH, OWNER, PASTOR, STAFF, PayrollFake, install, people, run, seed,
                               standard_lines, user)


@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    people(db)
    return db


def _new_run(pay_date="2026-12-15"):
    return pr.create_run(pr.RunBody(business_id=CHURCH, period_start="2026-12-01", period_end=pay_date,
                                    pay_date=pay_date), user=user(OWNER))


def _line(out, emp):
    return next(i for i in out["items"] if i["employee_id"] == emp)


def test_unchanged_pay_carries_the_typed_figures_and_names_the_run(db):
    prev = run(db, "2026-11-30", "paid", lines=standard_lines())
    out = _new_run()
    dana = _line(out, STAFF)
    assert dana["federal_withholding"] == 150.0 and dana["state_withholding"] == 40.0
    assert dana["calc_status"] == "manual" and dana["net"] is not None
    assert dana["calc_payload"]["carried_from"] == prev["id"]
    assert dana["calc_payload"]["carried_from_pay_date"] == "2026-11-30"
    assert dana["calc_payload"]["pay"] == {"type": "salary", "rate": 52000.0, "frequency": "biweekly"}
    pastor = _line(out, PASTOR)
    assert pastor["federal_withholding"] == 500.0 and pastor["calc_payload"]["carried_from"] == prev["id"]


def test_the_latest_approved_or_paid_line_wins_and_drafts_never_count(db):
    run(db, "2026-10-30", "paid", lines=[{"employee_id": STAFF, "fit": 111.0, "sit": 11.0}])
    newer = run(db, "2026-11-13", "approved", lines=[{"employee_id": STAFF, "fit": 122.0, "sit": 22.0}])
    run(db, "2026-11-27", "draft", lines=[{"employee_id": STAFF, "fit": 999.0, "sit": 99.0}])
    run(db, "2026-11-28", "cancelled", lines=[{"employee_id": STAFF, "fit": 888.0, "sit": 88.0}])
    dana = _line(_new_run(), STAFF)
    assert dana["federal_withholding"] == 122.0 and dana["calc_payload"]["carried_from"] == newer["id"]


def test_a_change_in_rate_type_or_frequency_carries_nothing(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    for change in ({"pay_rate": 55000.0}, {"pay_frequency": "semimonthly"}, {"pay_type": "hourly"}):
        emp = next(e for e in db.rows("employees") if e["id"] == STAFF)
        saved = dict(emp)
        emp.update(change)
        dana = _line(_new_run(), STAFF)
        assert dana["federal_withholding"] is None and "carried_from" not in dana["calc_payload"], change
        assert dana["calc_status"] == "needs_calculation"
        emp.clear()
        emp.update(saved)


def test_an_older_line_without_a_record_of_its_pay_is_judged_by_its_gross(db):
    prev = run(db, "2026-11-30", "paid", lines=standard_lines())
    for i in db.rows("pay_run_items"):
        i["calc_payload"] = {}
    assert _line(_new_run(), STAFF)["calc_payload"]["carried_from"] == prev["id"]
    next(e for e in db.rows("employees") if e["id"] == STAFF)["pay_rate"] = 54000.0
    assert "carried_from" not in _line(_new_run(), STAFF)["calc_payload"]
    assert not payroll_carry.unchanged({"gross": 0, "calc_payload": {}}, {"pay_type": "hourly", "pay_rate": 20})


def test_typing_a_figure_drops_the_carried_note(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    out = _new_run()
    dana = _line(out, STAFF)
    kept = pr.update_item(out["run"]["id"], dana["id"], pr.ItemPatch(other_deductions=10.0), user=user(OWNER))
    assert kept["item"]["calc_payload"]["carried_from"]                  # an unrelated edit keeps it
    typed = pr.update_item(out["run"]["id"], dana["id"], pr.ItemPatch(federal_withholding=160.0), user=user(OWNER))
    assert "carried_from" not in typed["item"]["calc_payload"] and typed["item"]["federal_withholding"] == 160.0
    assert typed["item"]["calc_payload"]["pay"]["rate"] == 52000.0


def test_a_read_that_fails_carries_nothing_and_the_run_still_drafts(db, monkeypatch):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    monkeypatch.setattr(payroll_carry, "sources", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    out = _new_run()
    assert all(i["federal_withholding"] is None for i in out["items"])
    _ = CHURCH
