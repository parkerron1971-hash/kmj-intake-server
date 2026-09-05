"""Pay your team — the payroll data layer (2026-09-05).

Pins the things that would hurt if they drifted:
  * the math we own (gross, FICA with the wage base, additional Medicare,
    FUTA) — and that FIT/SIT are NEVER invented
  * a run cannot be approved while any line still needs withholding
  * approval + paid write the spine events; nothing calls a money rail
  * the SSN is encrypted on the way in and never comes back out
  * the seat ladder: owner-only on the tax profile, admin on approve
"""
from __future__ import annotations

import sys
import pathlib
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from test_i2_gl_sync import FakeSB
import payroll_calc as pc
import payroll_router as pr


class _Owner:
    id = "owner"


class _Manager:
    id = "mgr"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "biz1", "name": "Fade Lab", "owner_id": "owner", "settings": {}})
    fb.rows("business_users").append({"business_id": "biz1", "user_id": "mgr",
                                      "role": "manager", "status": "active"})
    fb.rows("employees").append({
        "id": "emp1", "business_id": "biz1", "first_name": "Ana", "last_name": "Cruz",
        "status": "active", "pay_type": "hourly", "pay_rate": 25.0,
        "pay_frequency": "biweekly", "work_state": "TX"})
    fb.rows("employees").append({
        "id": "emp2", "business_id": "biz1", "first_name": "Ben", "last_name": "Ortiz",
        "status": "active", "pay_type": "salary", "pay_rate": 52000.0,
        "pay_frequency": "biweekly", "work_state": "TX"})
    # audit + spine are best-effort writers; keep them quiet and observable
    import audit_log, event_spine
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: True)
    emitted = []
    monkeypatch.setattr(event_spine, "emit",
                        lambda t, biz, data=None, **k: emitted.append((t, biz, data)) or True)
    fb.emitted = emitted
    monkeypatch.setenv("TIN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SYMMETRY_API_KEY", raising=False)
    return fb


# ─── The math we own ─────────────────────────────────────────────────

def test_gross_hourly_with_overtime_and_salary_per_period():
    hourly = {"pay_type": "hourly", "pay_rate": 20.0, "pay_frequency": "weekly"}
    assert pc.gross_for(hourly, 40, 5) == 40 * 20 + 5 * 30           # 950.0
    salary = {"pay_type": "salary", "pay_rate": 52000.0, "pay_frequency": "biweekly"}
    assert pc.gross_for(salary, 0, 0) == 2000.0
    monthly = {"pay_type": "salary", "pay_rate": 60000.0, "pay_frequency": "monthly"}
    assert pc.gross_for(monthly, 999, 0) == 5000.0                  # hours ignored


def test_fica_is_statutory_and_caps_at_the_wage_base():
    t = pc.statutory(1000.0, 0.0, 2026)
    assert t["social_security_employee"] == 62.0
    assert t["employer_social_security"] == 62.0
    assert t["medicare_employee"] == 14.5
    assert t["employer_medicare"] == 14.5
    assert t["employer_futa"] == 6.0
    # One check that straddles the 2026 wage base: only the part below it is taxed.
    base = pc.ss_wage_base(2026)
    t2 = pc.statutory(10_000.0, base - 4_000.0, 2026)
    assert t2["social_security_employee"] == round(4_000 * 0.062, 2)
    # Past the base: nothing.
    assert pc.statutory(5_000.0, base + 1.0, 2026)["social_security_employee"] == 0.0


def test_additional_medicare_and_futa_wage_base():
    # $200k already paid: the whole check carries the extra 0.9%.
    t = pc.statutory(1000.0, 200_000.0, 2026)
    assert t["medicare_employee"] == round(1000 * 0.0145 + 1000 * 0.009, 2)
    assert t["employer_medicare"] == 14.5                          # employer never pays the 0.9%
    assert t["employer_futa"] == 0.0                               # FUTA base long passed
    # FUTA straddle: $7,000 base, $6,500 paid → only $500 taxable.
    assert pc.statutory(1000.0, 6_500.0, 2026)["employer_futa"] == 3.0


def test_unknown_year_falls_back_to_latest_known_base():
    assert pc.ss_wage_base(2099) == pc.SOCIAL_SECURITY_WAGE_BASE[max(pc.SOCIAL_SECURITY_WAGE_BASE)]


def test_item_without_withholding_has_no_net_and_needs_calculation():
    emp = {"pay_type": "hourly", "pay_rate": 25.0, "pay_frequency": "biweekly"}
    item = pc.compute_item(employee=emp, hours=80, overtime_hours=0,
                           ytd_gross_before=0, year=2026)
    assert item["gross"] == 2000.0
    assert item["federal_withholding"] is None and item["state_withholding"] is None
    assert item["net"] is None
    assert item["calc_status"] == "needs_calculation"
    # Once both are supplied the net closes and the line is complete.
    done = pc.compute_item(employee=emp, hours=80, overtime_hours=0, ytd_gross_before=0,
                           year=2026, federal_withholding=180.0, state_withholding=0.0)
    assert done["net"] == round(2000 - 180 - 124 - 29, 2)
    assert done["calc_status"] == "manual"


def test_symmetry_adapter_is_honest_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SYMMETRY_API_KEY", raising=False)
    assert pc.active_calculator().name == "manual"
    with pytest.raises(HTTPException) as e:
        pc.SymmetryCalculator().withholding(gross=1.0, employee={}, profile={},
                                            pay_frequency="weekly", ytd_gross_before=0, year=2026)
    assert e.value.status_code == 501
    monkeypatch.setenv("SYMMETRY_API_KEY", "sk_test")
    assert pc.active_calculator().name == "symmetry"


def test_run_totals_build_the_941_deposit_from_both_halves():
    items = [
        {"gross": 2000.0, "net": 1667.0, "federal_withholding": 180.0, "state_withholding": 0.0,
         "social_security_employee": 124.0, "medicare_employee": 29.0,
         "employer_social_security": 124.0, "employer_medicare": 29.0,
         "employer_futa": 12.0, "employer_suta": None, "calc_status": "manual"},
        {"gross": 1000.0, "net": None, "federal_withholding": None, "state_withholding": None,
         "social_security_employee": 62.0, "medicare_employee": 14.5,
         "employer_social_security": 62.0, "employer_medicare": 14.5,
         "employer_futa": 6.0, "employer_suta": None, "calc_status": "needs_calculation"},
    ]
    t = pc.run_totals(items)
    assert t["employees"] == 2 and t["needs_calculation"] == 1
    assert t["deposits"]["federal_941"] == round(180 + 124 + 124 + 29 + 29 + 62 + 62 + 14.5 + 14.5, 2)
    assert t["deposits"]["federal_940_futa"] == 18.0
    assert t["employer_cost"] == round(3000 + 186 + 43.5 + 18, 2)


# ─── Employees + the W-4 ─────────────────────────────────────────────

def test_create_employee_validates_and_records(fake):
    out = pr.create_employee(pr.EmployeeBody(
        business_id="biz1", first_name="Cal", last_name="Reyes", pay_type="hourly",
        pay_rate=18.5, pay_frequency="weekly", work_state="tx", hire_date="2026-09-01"),
        user=_Manager())
    row = out["employee"]
    assert row["status"] == "active" and row["work_state"] == "TX"
    assert row["hire_date"] == "2026-09-01"
    with pytest.raises(HTTPException) as e:
        pr.create_employee(pr.EmployeeBody(business_id="biz1", first_name="X", last_name="Y",
                                           pay_frequency="fortnightly"), user=_Owner())
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        pr.create_employee(pr.EmployeeBody(business_id="biz1", first_name="X", last_name="Y",
                                           work_state="Texas"), user=_Owner())
    assert e.value.status_code == 400


def test_tax_profile_is_owner_only_and_never_returns_the_ssn(fake):
    body = pr.TaxProfileBody(ssn="123-45-6789", address_line1="1 Main", city="Austin",
                             state="TX", zip="78701", filing_status="single",
                             dependents_amount=2000, signed=True)
    with pytest.raises(HTTPException) as e:
        pr.put_tax_profile("emp1", body, user=_Manager())
    assert e.value.status_code == 403

    out = pr.put_tax_profile("emp1", body, user=_Owner())
    assert out["ssn_last4"] == "6789" and out["w4_signed_at"]
    stored = fake.rows("employee_tax_profiles")[0]
    assert stored["ssn_encrypted"] and "123456789" not in stored["ssn_encrypted"]
    assert stored["federal"]["dependents_amount"] == 2000.0
    assert stored["address"]["state"] == "TX"

    got = pr.get_tax_profile("emp1", user=_Owner())
    assert got["ssn_last4"] == "6789" and got["has_ssn"] is True
    assert "ssn_encrypted" not in got and "ssn" not in got

    # Second save without an SSN keeps the one on file and the signature date.
    again = pr.put_tax_profile("emp1", pr.TaxProfileBody(filing_status="married_joint", signed=True),
                               user=_Owner())
    assert again["ssn_last4"] == "6789" and again["w4_signed_at"] == out["w4_signed_at"]
    assert fake.rows("employee_tax_profiles")[0]["federal"]["filing_status"] == "married_joint"

    # A brand-new profile with no SSN is refused.
    with pytest.raises(HTTPException) as e:
        pr.put_tax_profile("emp2", pr.TaxProfileBody(), user=_Owner())
    assert e.value.status_code == 400

    listed = pr.list_employees("biz1", user=_Owner())["employees"]
    by_id = {e["id"]: e for e in listed}
    assert by_id["emp1"]["ssn_last4"] == "6789" and by_id["emp2"]["has_ssn"] is False


# ─── Pay runs ────────────────────────────────────────────────────────

def _draft(fake, items=None):
    return pr.create_run(pr.RunBody(business_id="biz1", period_start="2026-09-01",
                                    period_end="2026-09-14", pay_date="2026-09-18",
                                    items=items), user=_Owner())


def test_draft_run_covers_every_active_employee_and_needs_calculation(fake):
    fake.rows("employees").append({
        "id": "emp3", "business_id": "biz1", "first_name": "Old", "last_name": "Hire",
        "status": "terminated", "pay_type": "hourly", "pay_rate": 10.0, "pay_frequency": "weekly"})
    out = _draft(fake)
    assert out["run"]["status"] == "draft" and out["run"]["calc_source"] == "manual"
    assert {i["employee_id"] for i in out["items"]} == {"emp1", "emp2"}   # not emp3
    salary_line = next(i for i in out["items"] if i["employee_id"] == "emp2")
    assert salary_line["gross"] == 2000.0
    hourly_line = next(i for i in out["items"] if i["employee_id"] == "emp1")
    assert hourly_line["gross"] == 0.0                                  # no hours yet
    assert out["run"]["totals"]["needs_calculation"] == 2

    with pytest.raises(HTTPException) as e:
        pr.approve_run(out["run"]["id"], user=_Owner())
    assert e.value.status_code == 409
    assert e.value.detail["error"] == "needs_calculation"
    assert fake.emitted == []                                           # nothing on the spine


def test_edit_line_recomputes_and_approve_then_paid_emit_events(fake):
    out = _draft(fake, items=[pr.RunItemInput(employee_id="emp1", hours=80, overtime_hours=2)])
    run_id = out["run"]["id"]
    item = out["items"][0]
    assert item["gross"] == 80 * 25 + 2 * 37.5                          # 2075.0

    upd = pr.update_item(run_id, item["id"], pr.ItemPatch(federal_withholding=190.0,
                                                          state_withholding=0.0),
                         user=_Manager())
    assert upd["item"]["calc_status"] == "manual"
    assert upd["item"]["net"] == round(2075 - 190 - 2075 * 0.062 - 2075 * 0.0145, 2)
    assert upd["totals"]["needs_calculation"] == 0

    # manager cannot approve; owner can
    with pytest.raises(HTTPException) as e:
        pr.approve_run(run_id, user=_Manager())
    assert e.value.status_code == 403
    ap = pr.approve_run(run_id, user=_Owner())
    assert ap["run"]["status"] == "approved"
    assert fake.rows("pay_runs")[0]["status"] == "approved"
    assert fake.emitted[-1][0] == "pay_run_approved"
    assert fake.emitted[-1][2]["federal_941"] == ap["run"]["totals"]["deposits"]["federal_941"]

    # Frozen: no more edits.
    with pytest.raises(HTTPException) as e:
        pr.update_item(run_id, item["id"], pr.ItemPatch(hours=1), user=_Owner())
    assert e.value.status_code == 409

    paid = pr.mark_paid(run_id, user=_Owner())
    assert paid["run"]["status"] == "paid" and paid["run"]["payout_rail"] == "manual"
    assert fake.emitted[-1][0] == "pay_run_paid"
    # No table for any rail was touched: the fake has no such rows.
    assert "outbound_transfers" not in fake.t and "plaid_transfers" not in fake.t


def test_ytd_from_approved_runs_feeds_the_next_run(fake):
    # An approved run earlier in the year at $6,500 gross → the next check's
    # FUTA only covers the remaining $500 of the $7,000 base.
    fake.rows("pay_runs").append({"id": "run0", "business_id": "biz1", "status": "approved",
                                  "pay_date": "2026-03-06", "period_start": "2026-02-21",
                                  "period_end": "2026-03-06", "totals": {}})
    fake.rows("pay_run_items").append({"id": "it0", "pay_run_id": "run0", "business_id": "biz1",
                                       "employee_id": "emp1", "gross": 6500.0})
    # A cancelled run must NOT count.
    fake.rows("pay_runs").append({"id": "runx", "business_id": "biz1", "status": "cancelled",
                                  "pay_date": "2026-04-03", "period_start": "2026-03-21",
                                  "period_end": "2026-04-03", "totals": {}})
    fake.rows("pay_run_items").append({"id": "itx", "pay_run_id": "runx", "business_id": "biz1",
                                       "employee_id": "emp1", "gross": 9999.0})
    out = _draft(fake, items=[pr.RunItemInput(employee_id="emp1", hours=40)])
    line = out["items"][0]
    assert line["gross"] == 1000.0
    assert line["employer_futa"] == 3.0


def test_cancel_only_from_draft_and_summary_counts(fake):
    out = _draft(fake)
    run_id = out["run"]["id"]
    s = pr.summary("biz1", user=_Owner())
    assert s["employees_active"] == 2 and s["runs_draft"] == 1 and s["employees_missing_w4"] == 2
    assert s["calculator"] == "manual"
    assert pr.cancel_run(run_id, user=_Manager())["run"]["status"] == "cancelled"
    with pytest.raises(HTTPException) as e:
        pr.cancel_run(run_id, user=_Owner())
    assert e.value.status_code == 409


def test_run_needs_an_active_employee_and_a_sane_period(fake):
    for e in fake.rows("employees"):
        e["status"] = "terminated"
    with pytest.raises(HTTPException) as ex:
        _draft(fake)
    assert ex.value.status_code == 409
    for e in fake.rows("employees"):
        e["status"] = "active"
    with pytest.raises(HTTPException) as ex:
        pr.create_run(pr.RunBody(business_id="biz1", period_start="2026-09-14",
                                 period_end="2026-09-01", pay_date="2026-09-18"), user=_Owner())
    assert ex.value.status_code == 400
