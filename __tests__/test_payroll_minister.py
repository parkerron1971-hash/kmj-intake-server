"""A minister in Pay your team (2026-10-31).

Kevin isn't paid through the app yet, "not to say it's something in the
future i want accounted for". Pins:
  * a minister's pay owes no Social Security, Medicare or FUTA, either half
  * the housing part rides the line (never more than the check); no one
    else's line carries the key, so a run saves before the migration
  * the minister setting and the housing part are the owner's alone
  * marking a run paid logs each housing part to the minister's housing
    allowance record once, and says what it couldn't log
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest
from fastapi import HTTPException

from test_payroll_data_layer import fake, _Owner, _Manager  # noqa: F401  (fixture)
import housing_allowance as ha
import payroll_calc as pc
import payroll_router as pr

PASTOR = {"id": "emp9", "business_id": "biz1", "first_name": "Ana", "last_name": "Rivera",
          "status": "active", "pay_type": "salary", "pay_rate": 60000.0, "pay_frequency": "monthly",
          "work_state": "TX", "minister": True, "housing_allowance_per_period": 2000.0}


@pytest.fixture
def church(fake, monkeypatch):
    fake.rows("employees").append(dict(PASTOR))
    fake.rows("business_users").append({"business_id": "biz1", "user_id": "adm",
                                        "role": "admin", "status": "active"})
    monkeypatch.setattr(ha, "switched_on", lambda biz: True)
    # FakeSB's ids aren't uuids; the link check itself is pinned in test_housing_allowance.
    monkeypatch.setattr(ha, "_belongs", lambda *a, **k: True)
    return fake


class _Admin:
    id = "adm"


HA1 = "a1a1a1a1-0000-4000-8000-000000000001"


def _designate(fake, **over):
    row = {"id": HA1, "business_id": "biz1", "minister_name": "Pastor Ana Rivera", "tax_year": 2026,
           "designated_amount": 24000.0, "designated_on": "2025-12-14", "employee_id": None,
           "board_decision_id": None, "fair_rental_value": None, "notes": "", "archived_at": None,
           **over}
    fake.rows("minister_housing_allowances").append(row)
    return row


def _paid_run(fake):
    out = pr.create_run(pr.RunBody(business_id="biz1", period_start="2026-10-01", period_end="2026-10-31",
                                   pay_date="2026-10-31",
                                   items=[pr.RunItemInput(employee_id="emp9")]), user=_Owner())
    run_id, item = out["run"]["id"], out["items"][0]
    pr.update_item(run_id, item["id"], pr.ItemPatch(federal_withholding=0.0, state_withholding=0.0),
                   user=_Owner())
    pr.approve_run(run_id, user=_Owner())
    return run_id, item


# ─── The math ────────────────────────────────────────────────────────

def test_a_ministers_pay_owes_no_fica_or_futa():
    t = pc.statutory(5000.0, 0.0, 2026, minister=True)
    assert set(t.values()) == {0.0}
    item = pc.compute_item(employee=PASTOR, hours=0, overtime_hours=0, ytd_gross_before=0, year=2026,
                           federal_withholding=0.0, state_withholding=0.0, housing_allowance=2000.0)
    assert item["gross"] == 5000.0 and item["housing_allowance"] == 2000.0
    assert item["social_security_employee"] == item["medicare_employee"] == 0.0
    assert item["employer_social_security"] == item["employer_medicare"] == item["employer_futa"] == 0.0
    assert item["net"] == 5000.0                    # the housing part is paid, not deducted


def test_the_housing_part_is_never_more_than_the_check_and_only_a_ministers():
    hourly_minister = {**PASTOR, "pay_type": "hourly", "pay_rate": 20.0}
    item = pc.compute_item(employee=hourly_minister, hours=10, overtime_hours=0, ytd_gross_before=0,
                           year=2026, housing_allowance=2000.0)
    assert item["housing_allowance"] == item["gross"] == 200.0
    # Anyone else: FICA as before, and no housing key (a run saves before the column exists).
    lay = {"pay_type": "salary", "pay_rate": 60000.0, "pay_frequency": "monthly"}
    plain = pc.compute_item(employee=lay, hours=0, overtime_hours=0, ytd_gross_before=0, year=2026,
                            housing_allowance=2000.0)
    assert "housing_allowance" not in plain
    assert plain["social_security_employee"] == 310.0


def test_run_totals_carry_the_housing_and_leave_the_minister_out_of_the_941():
    items = [pc.compute_item(employee=PASTOR, hours=0, overtime_hours=0, ytd_gross_before=0, year=2026,
                             federal_withholding=300.0, state_withholding=0.0, housing_allowance=2000.0)]
    t = pc.run_totals(items)
    assert t["housing_allowance"] == 2000.0
    assert t["deposits"]["federal_941"] == 300.0    # the income tax they asked to have withheld, alone
    assert t["deposits"]["federal_940_futa"] == 0.0


# ─── Who may set it ──────────────────────────────────────────────────

def test_the_minister_setting_is_the_owners_alone(church):
    body = dict(business_id="biz1", first_name="Sam", last_name="Lee", pay_type="salary",
                pay_rate=40000.0, pay_frequency="monthly")
    with pytest.raises(HTTPException) as e:
        pr.create_employee(pr.EmployeeBody(**body, minister=True), user=_Manager())
    assert e.value.status_code == 403
    # A manager still adds anyone else.
    assert pr.create_employee(pr.EmployeeBody(**body), user=_Manager())["ok"]
    with pytest.raises(HTTPException) as e:
        pr.create_employee(pr.EmployeeBody(**body, housing_allowance_per_period=500.0), user=_Owner())
    assert e.value.status_code == 400               # a housing allowance needs a minister
    out = pr.create_employee(pr.EmployeeBody(**body, minister=True, housing_allowance_per_period=500.0),
                             user=_Owner())
    assert out["employee"]["minister"] is True and out["employee"]["housing_allowance_per_period"] == 500.0

    with pytest.raises(HTTPException) as e:
        pr.update_employee("emp9", pr.EmployeePatch(housing_allowance_per_period=10.0), user=_Manager())
    assert e.value.status_code == 403
    # A manager's ordinary edit doesn't touch the setting.
    assert pr.update_employee("emp9", pr.EmployeePatch(phone="555"), user=_Manager())["employee"]["minister"]
    off = pr.update_employee("emp9", pr.EmployeePatch(minister=False), user=_Owner())["employee"]
    assert off["minister"] is False and off["housing_allowance_per_period"] is None


def test_a_draft_line_takes_the_housing_part_and_only_the_owner_changes_it(church):
    out = pr.create_run(pr.RunBody(business_id="biz1", period_start="2026-10-01", period_end="2026-10-31",
                                   pay_date="2026-10-31"), user=_Owner())
    line = next(i for i in out["items"] if i["employee_id"] == "emp9")
    assert line["gross"] == 5000.0 and line["housing_allowance"] == 2000.0
    assert line["social_security_employee"] == 0.0 and line["employer_futa"] == 0.0
    lay = next(i for i in out["items"] if i["employee_id"] == "emp2")
    assert lay["social_security_employee"] > 0 and "housing_allowance" not in lay

    run_id = out["run"]["id"]
    with pytest.raises(HTTPException) as e:
        pr.update_item(run_id, line["id"], pr.ItemPatch(housing_allowance=1500.0), user=_Manager())
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        pr.update_item(run_id, lay["id"], pr.ItemPatch(housing_allowance=100.0), user=_Owner())
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        pr.update_item(run_id, line["id"], pr.ItemPatch(housing_allowance=6000.0), user=_Owner())
    assert e.value.status_code == 400
    upd = pr.update_item(run_id, line["id"], pr.ItemPatch(housing_allowance=1500.0), user=_Owner())
    assert upd["item"]["housing_allowance"] == 1500.0
    # A manager's withholding edit keeps the owner's housing part.
    upd = pr.update_item(run_id, line["id"], pr.ItemPatch(federal_withholding=0.0), user=_Manager())
    assert upd["item"]["housing_allowance"] == 1500.0
    assert upd["totals"]["housing_allowance"] == 1500.0


# ─── Paid → the housing allowance record ─────────────────────────────

def test_marking_paid_logs_the_housing_part_once(church):
    _designate(church)
    run_id, item = _paid_run(church)
    out = pr.mark_paid(run_id, user=_Admin())
    assert out["housing"]["logged"] == [{"employee_id": "emp9", "name": "Ana Rivera", "amount": 2000.0}]
    assert out["housing"]["not_logged"] == []
    entries = church.rows("minister_housing_entries")
    assert len(entries) == 1
    e = entries[0]
    assert (e["allowance_id"], e["kind"], e["amount"], e["entry_date"], e["source"], e["source_id"]) == \
        (HA1, "paid", 2000.0, "2026-10-31", "pay_run", item["id"])
    # Again (the owner's retry): counted once.
    again = pr.log_housing(run_id, user=_Owner())
    assert again["housing"]["logged"][0]["amount"] == 2000.0
    assert len(church.rows("minister_housing_entries")) == 1
    with pytest.raises(HTTPException) as e:
        pr.log_housing(run_id, user=_Admin())
    assert e.value.status_code == 403


def test_without_a_designation_it_says_so_and_logs_later(church):
    run_id, _ = _paid_run(church)
    notes = pr.get_run(run_id, user=_Owner())["housing_notes"]
    assert len(notes) == 1 and "No 2026 housing allowance is recorded for Ana Rivera" in notes[0]
    out = pr.mark_paid(run_id, user=_Admin())
    assert out["housing"]["logged"] == []
    assert out["housing"]["not_logged"][0]["reason"] == "no 2026 housing allowance is recorded for Ana Rivera"
    assert church.rows("minister_housing_entries") == []
    # Recorded afterwards (linked to the employee this time), then logged.
    _designate(church, minister_name="A. Rivera", employee_id="emp9")
    assert pr.log_housing(run_id, user=_Owner())["housing"]["logged"][0]["amount"] == 2000.0
    assert pr.get_run(run_id, user=_Owner())["housing_notes"] == []


def test_switched_off_the_run_is_paid_and_nothing_is_logged(church, monkeypatch):
    _designate(church)
    monkeypatch.setattr(ha, "switched_on", lambda biz: False)
    run_id, _ = _paid_run(church)
    out = pr.mark_paid(run_id, user=_Admin())
    assert out["run"]["status"] == "paid"
    assert out["housing"]["not_logged"][0]["reason"] == "the housing allowance records aren't switched on here"
    assert church.rows("minister_housing_entries") == []


def test_a_failed_read_never_fails_the_paid_run(church, monkeypatch):
    _designate(church)
    run_id, _ = _paid_run(church)

    def boom(*a, **k):
        raise ha.Unavailable("minister_housing_allowances")
    monkeypatch.setattr(ha, "list_allowances", boom)
    out = pr.mark_paid(run_id, user=_Admin())
    assert out["run"]["status"] == "paid"
    assert out["housing"]["not_logged"][0]["reason"] == "the housing allowance records couldn't be read just now"
    assert pr.get_run(run_id, user=_Owner())["housing_notes"] == []     # a hint, skipped


def test_a_failed_read_of_the_lines_is_not_nothing_to_log(church, monkeypatch):
    _designate(church)
    run_id, _ = _paid_run(church)
    import sb_clients
    real = sb_clients.sb_get_as_service

    def failing(prefix):
        return lambda p: None if p.startswith(prefix) else real(p)
    # mark-paid: the run is paid, and the answer says the log failed.
    monkeypatch.setattr(sb_clients, "sb_get_as_service", failing("/pay_run_items?pay_run_id"))
    out = pr.mark_paid(run_id, user=_Admin())
    assert out["run"]["status"] == "paid" and out["housing"]["failed"] is True
    # The owner's retry: a 503, for the lines or the people, never "nothing to log".
    for prefix in ("/pay_run_items?pay_run_id", "/employees?business_id"):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", failing(prefix))
        with pytest.raises(HTTPException) as e:
            pr.log_housing(run_id, user=_Owner())
        assert e.value.status_code == 503
    assert church.rows("minister_housing_entries") == []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    assert pr.log_housing(run_id, user=_Owner())["housing"]["logged"][0]["amount"] == 2000.0


def test_names_match_word_for_word(church):
    _designate(church, minister_name="Pastor Susana Rivera-Cruz")
    run_id, _ = _paid_run(church)
    out = pr.mark_paid(run_id, user=_Admin())
    assert out["housing"]["not_logged"][0]["reason"] == "no 2026 housing allowance is recorded for Ana Rivera"
    assert church.rows("minister_housing_entries") == []


def test_no_longer_a_minister_takes_the_housing_part_off_a_draft_line(church):
    out = pr.create_run(pr.RunBody(business_id="biz1", period_start="2026-10-01", period_end="2026-10-31",
                                   pay_date="2026-10-31", items=[pr.RunItemInput(employee_id="emp9")]),
                        user=_Owner())
    line = out["items"][0]
    assert line["housing_allowance"] == 2000.0
    pr.update_employee("emp9", pr.EmployeePatch(minister=False), user=_Owner())
    upd = pr.update_item(out["run"]["id"], line["id"], pr.ItemPatch(federal_withholding=0.0), user=_Manager())
    assert upd["item"]["housing_allowance"] == 0.0
    assert upd["item"]["social_security_employee"] > 0                  # FICA again
    assert upd["totals"]["housing_allowance"] == 0.0
