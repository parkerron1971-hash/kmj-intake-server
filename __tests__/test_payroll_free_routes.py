"""Payroll, the free version: the doors (payroll_router), who may open them,
and the pieces around them (the migration, the switches, the export maps,
the scheduler). Every name and figure is made up.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest
from fastapi import HTTPException

import church_money_gate as gate
import payroll_deposits
import payroll_router as pr
from payroll_free_fake import (ACCOUNTANT, ADMIN, CHURCH, MANAGER, MEMBER, OTHER, OTHER_OWNER, OWNER, SHOP,
                               SHOP_OWNER, SHOP_VIEWER, STAFF, STRANGER, VIEWER, PayrollFake, install, people,
                               run, seed, standard_lines, tick, ticks, uid, user)


@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    people(db)
    db.mail = []

    async def mail(**kw):
        db.mail.append(kw)
        return {}
    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", mail)
    import business_identity
    monkeypatch.setattr(business_identity, "payer_block", lambda biz, row=None: {
        "name": "Grace Harbor Church", "ein": "", "line1": "", "city_state_zip": "", "line2": "", "phone": "",
        "complete": False})
    return db


def status(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except HTTPException as e:
        return e.status_code, e.detail
    return 200, None


# ─── The doors exist, and every one asks who you are ─────────────────

NEW = {("GET", "/payroll/calendar"), ("POST", "/payroll/deposits/mark-sent"), ("POST", "/payroll/deposits/undo"),
       ("PUT", "/payroll/settings"), ("GET", "/payroll/runs/{run_id}/stubs"),
       ("GET", "/payroll/runs/{run_id}/items/{item_id}/stub"),
       ("GET", "/payroll/runs/{run_id}/items/{item_id}/stub.pdf"), ("POST", "/payroll/runs/{run_id}/stubs/send"),
       ("GET", "/payroll/forms/quarter"), ("GET", "/payroll/forms/quarter.pdf"), ("GET", "/payroll/forms/year"),
       ("GET", "/payroll/forms/year.pdf"), ("GET", "/payroll/forms/year.csv")}


def test_every_new_door_is_there_and_takes_a_signed_in_user():
    from auth_supabase import require_user
    have = {}
    for r in pr.router.routes:
        for m in r.methods:
            have[(m, r.path)] = r
    for door in NEW:
        assert door in have, door
        deps = [d.call for d in have[door].dependant.dependencies]
        assert require_user in deps, door


# ─── The calendar: who may read ───────────────────────────────────────

def test_who_may_read_the_calendar(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    cal = lambda u, biz=CHURCH: status(pr.payroll_calendar_month, biz, "2026-12", user=user(u))  # noqa: E731
    assert cal(OWNER)[0] == 200 and cal(ADMIN)[0] == 200
    for u in (MANAGER, MEMBER, VIEWER, STRANGER, OTHER_OWNER):
        assert cal(u) == (403, gate.GIVING_403), u
    # The accountant passes the wall but holds no seat: as today, payroll's ladder refuses.
    assert cal(ACCOUNTANT)[0] == 403
    # A business that isn't a church keeps its own ladder: any seat reads.
    assert cal(SHOP_VIEWER, SHOP)[0] == 200 and cal(SHOP_OWNER, SHOP)[0] == 200
    out = pr.payroll_calendar_month(CHURCH, "2026-12", user=user(OWNER))
    assert set(out) >= {"ok", "month", "settings", "days", "next", "later"}


def test_ids_are_shape_checked_before_any_read(db):
    db.reads.clear()
    for bad in ("biz1", "x&owner_id=neq.0", f"{CHURCH}#", "", f"{CHURCH}\n"):
        assert status(pr.payroll_calendar_month, bad, None, user=user(OWNER))[0] == 400, bad
    assert db.reads == []
    assert status(pr.payroll_calendar_month, CHURCH, "2026-13", user=user(OWNER))[0] == 400
    assert status(pr.run_stubs, "not-a-run", user=user(OWNER))[0] == 400
    assert status(pr.forms_quarter, CHURCH, q=5, year=2026, user=user(OWNER))[0] == 400
    assert status(pr.forms_year, CHURCH, year=1900, user=user(OWNER))[0] == 400


def test_a_failed_read_is_a_503_not_an_empty_page(db):
    db.missing.add("employees")
    assert status(pr.payroll_calendar_month, CHURCH, "2026-12", user=user(OWNER))[0] == 503


# ─── Statements ───────────────────────────────────────────────────────

def test_statements_open_for_approved_and_paid_runs_only(db):
    draft = run(db, "2026-12-15", "draft", lines=standard_lines())
    cancelled = run(db, "2026-12-01", "cancelled", lines=standard_lines())
    paid = run(db, "2026-11-30", "paid", lines=standard_lines())
    assert status(pr.run_stubs, draft["id"], user=user(OWNER)) == (409, "Approve the run first.")
    assert status(pr.run_stubs, cancelled["id"], user=user(OWNER))[0] == 409
    out = pr.run_stubs(paid["id"], user=user(ADMIN))
    assert out["ok"] and len(out["stubs"]) == 2
    item = next(i for i in db.rows("pay_run_items") if i["pay_run_id"] == paid["id"] and i["employee_id"] == STAFF)
    one = pr.item_stub(paid["id"], item["id"], user=user(OWNER))["stub"]
    assert one["item_id"] == item["id"] and one["employee"]["ssn_last4"] == "4321"
    resp = pr.item_stub_pdf(paid["id"], item["id"], user=user(OWNER))
    assert resp.media_type == "application/pdf" and resp.body[:5] == b"%PDF-"
    assert resp.headers["cache-control"] == "no-store" and "attachment" in resp.headers["content-disposition"]


def test_another_churchs_statement_is_a_404(db):
    paid = run(db, "2026-11-30", "paid", lines=standard_lines())
    item = next(i for i in db.rows("pay_run_items") if i["pay_run_id"] == paid["id"])
    for u in (OTHER_OWNER, STRANGER, VIEWER, MANAGER):
        assert status(pr.run_stubs, paid["id"], user=user(u))[0] == 404, u
        assert status(pr.item_stub, paid["id"], item["id"], user=user(u))[0] == 404, u
        assert status(pr.item_stub_pdf, paid["id"], item["id"], user=user(u))[0] == 404, u
        assert status(pr.send_run_stubs, paid["id"], None, user=user(u))[0] == 404, u
    assert status(pr.run_stubs, uid(), user=user(OWNER))[0] == 404              # no such run
    other = run(db, "2026-11-30", "paid", lines=standard_lines())
    stray = next(i for i in db.rows("pay_run_items") if i["pay_run_id"] == other["id"])
    assert status(pr.item_stub, paid["id"], stray["id"], user=user(OWNER)) == (404, "That line isn't on this run.")
    assert status(pr.item_stub, paid["id"], "nope", user=user(OWNER))[0] == 400


def test_sending_statements_is_the_owners_or_an_admins_and_goes_only_to_their_own_addresses(db):
    paid = run(db, "2026-11-30", "paid", lines=standard_lines())
    out = pr.send_run_stubs(paid["id"], None, user=user(ADMIN))
    assert out == {"ok": True, "sent": 2, "skipped": []}
    assert sorted(m["to_email"] for m in db.mail) == ["dana@graceharbor.example", "marcus@graceharbor.example"]
    item = next(i for i in db.rows("pay_run_items") if i["pay_run_id"] == paid["id"] and i["employee_id"] == STAFF)
    db.mail.clear()
    one = pr.send_run_stubs(paid["id"], pr.SendStubsBody(item_ids=[item["id"]]), user=user(OWNER))
    assert one["sent"] == 1 and [m["to_email"] for m in db.mail] == ["dana@graceharbor.example"]
    assert status(pr.send_run_stubs, paid["id"], pr.SendStubsBody(item_ids=[uid()]), user=user(OWNER))[0] == 404
    # A business that isn't a church: a Viewer seat reads the statements but doesn't send them.
    shop_emp = uid()
    db.rows("employees").append({"id": shop_emp, "business_id": SHOP, "first_name": "Rae", "last_name": "Quill",
                                 "status": "active", "pay_type": "salary", "pay_rate": 31200.0,
                                 "pay_frequency": "weekly", "email": "rae@cornerfade.example"})
    shop_run = run(db, "2026-11-27", "paid", SHOP, lines=[{"employee_id": shop_emp, "fit": 30.0, "sit": 0.0}])
    assert pr.run_stubs(shop_run["id"], user=user(SHOP_VIEWER))["ok"]
    assert status(pr.send_run_stubs, shop_run["id"], None, user=user(SHOP_VIEWER))[0] == 403


def test_marking_a_run_paid_queues_the_statements_and_never_fails_for_them(db, monkeypatch):
    def approved():
        r = run(db, "2026-11-30", "approved", lines=standard_lines())
        return r["id"]
    queued = []
    monkeypatch.setattr(pr, "_background", lambda fn: queued.append(fn))
    out = pr.mark_paid(approved(), user=user(OWNER))
    # The answer comes back before any mail: the send is queued, off the request.
    assert out["run"]["status"] == "paid"
    assert out["stubs"] == {"queued": True, "auto": True, "sent": None, "skipped": []}
    assert db.mail == [] and len(queued) == 1
    queued.pop()()                                              # the background work, run here
    assert sorted(m["to_email"] for m in db.mail) == ["dana@graceharbor.example", "marcus@graceharbor.example"]
    db.mail.clear()
    monkeypatch.setenv("PAYROLL_STUB_EMAIL", "off")
    out = pr.mark_paid(approved(), user=user(OWNER))
    assert out["stubs"] == {"queued": False, "auto": False, "sent": None, "skipped": []} and queued == []
    monkeypatch.setenv("PAYROLL_STUB_EMAIL", "owner")
    assert pr.mark_paid(approved(), user=user(OWNER))["stubs"]["queued"] is False and queued == []
    monkeypatch.setenv("PAYROLL_STUB_EMAIL", "on")
    import payroll_stubs
    monkeypatch.setattr(payroll_stubs, "load", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    out = pr.mark_paid(approved(), user=user(OWNER))
    assert out["ok"] and out["stubs"]["queued"] is True
    queued.pop()()                                              # a failure in the background raises nothing
    assert db.mail == []
    # A thread that can't even start still leaves the run paid.
    monkeypatch.setattr(pr, "_background", lambda fn: (_ for _ in ()).throw(RuntimeError("no threads")))
    out = pr.mark_paid(approved(), user=user(OWNER))
    assert out["run"]["status"] == "paid" and out["stubs"]["failed"] is True and out["stubs"]["queued"] is False


def test_the_background_is_a_daemon_thread(monkeypatch):
    started = []

    class T:
        def __init__(self, target, daemon=None):
            started.append(daemon)
            self.target = target

        def start(self):
            self.target()
    import threading
    monkeypatch.setattr(threading, "Thread", T)
    ran = []
    pr._background(lambda: ran.append(1))
    assert started == [True] and ran == [1]


# ─── A run that would pay someone less than nothing ───────────────────

def _hourly(db):
    from payroll_free_fake import HOURLY
    db.rows("employees").append({"id": HOURLY, "business_id": CHURCH, "first_name": "Hal", "last_name": "Oakes",
                                 "status": "active", "pay_type": "hourly", "pay_rate": 25.0,
                                 "pay_frequency": "biweekly", "email": "hal@graceharbor.example"})
    return HOURLY


def test_a_short_hourly_check_carries_nothing_and_a_negative_net_never_approves(db):
    # The reviewer's case: last paid run 80 hours with $300 federal and $90 state; a 4-hour run.
    hal = _hourly(db)
    run(db, "2026-11-13", "paid", lines=[{"employee_id": hal, "hours": 80, "fit": 300.0, "sit": 90.0}])
    out = pr.create_run(pr.RunBody(business_id=CHURCH, period_start="2026-11-14", period_end="2026-11-27",
                                   pay_date="2026-11-30", items=[pr.RunItemInput(employee_id=hal, hours=4)]),
                        user=user(OWNER))
    line = out["items"][0]
    assert line["gross"] == 100.0
    assert line["federal_withholding"] is None and line["state_withholding"] is None
    assert line["calc_status"] == "needs_calculation" and line["net"] is None
    assert "carried_from" not in line["calc_payload"]
    assert line["calc_payload"]["carry_note"] == (
        "Nothing was carried over from the Nov 13 run: this check’s pay ($100.00) isn’t that one’s ($2,000.00), "
        "so its federal and state withholding need typing.")
    # Typed by hand as the same $390: take-home below zero, and approve says so, naming him.
    pr.update_item(out["run"]["id"], line["id"], pr.ItemPatch(federal_withholding=300.0, state_withholding=90.0),
                   user=user(OWNER))
    with pytest.raises(HTTPException) as e:
        pr.approve_run(out["run"]["id"], user=user(OWNER))
    assert e.value.status_code == 409 and e.value.detail["error"] == "negative_net"
    assert e.value.detail["people"] == ["Hal Oakes"]
    assert e.value.detail["message"] == ("Take-home pay would be below zero for Hal Oakes (−$297.65): the taxes and "
                                         "deductions are more than the pay. Fix that line before approving.")
    assert next(r for r in db.rows("pay_runs") if r["id"] == out["run"]["id"])["status"] == "draft"


def test_the_same_hours_carry_and_changing_them_afterwards_clears_what_was_carried(db):
    hal = _hourly(db)
    prev = run(db, "2026-11-13", "paid", lines=[{"employee_id": hal, "hours": 80, "fit": 300.0, "sit": 90.0}])
    out = pr.create_run(pr.RunBody(business_id=CHURCH, period_start="2026-11-14", period_end="2026-11-27",
                                   pay_date="2026-11-30", items=[pr.RunItemInput(employee_id=hal, hours=80)]),
                        user=user(OWNER))
    line = out["items"][0]
    assert line["federal_withholding"] == 300.0 and line["calc_payload"]["carried_from"] == prev["id"]
    assert line["calc_payload"]["carried_gross"] == 2000.0
    changed = pr.update_item(out["run"]["id"], line["id"], pr.ItemPatch(hours=4), user=user(OWNER))["item"]
    assert changed["gross"] == 100.0 and changed["federal_withholding"] is None
    assert changed["calc_status"] == "needs_calculation" and "carried_from" not in changed["calc_payload"]
    assert changed["calc_payload"]["carry_note"].startswith("The hours changed after the withholding was carried over "
                                                            "from the Nov 13 run")
    with pytest.raises(HTTPException) as e:
        pr.approve_run(out["run"]["id"], user=user(OWNER))
    assert e.value.detail["error"] == "needs_calculation"


def test_money_is_never_nan_or_infinite(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert status(_mark, OWNER, amount=bad)[0] == 400, bad
        with pytest.raises(HTTPException) as e:
            pr._money(bad, "hours")
        assert e.value.status_code == 400
    assert db.rows("payroll_deposits") == []


def test_the_pay_records_refusal_names_only_who_can_open_payroll():
    # The accountant holds no seat, and payroll's own ladder refuses a login with none.
    assert "accountant" not in gate.PAY_RECORDS_403
    assert gate.PAY_RECORDS_403 == ("Pay and tax records are kept for the owner, an admin, or a login the owner gave "
                                    "giving at Work.")


# ─── Deposits marked sent ─────────────────────────────────────────────

def _mark(u, key="federal:2026-11", amount=956.0, biz=CHURCH, **kw):
    return pr.mark_deposit_sent(pr.MarkSentBody(business_id=biz, key=key, amount=amount, **kw), user=user(u))


def test_before_the_migration_mark_sent_says_it_is_being_switched_on(db):
    db.missing.add("payroll_deposits")
    assert status(_mark, OWNER) == (503, "Deposit tracking is being switched on. Try again shortly.")
    assert status(pr.undo_deposit_sent, pr.DepositKeyBody(business_id=CHURCH, key="federal:2026-11"),
                  user=user(OWNER)) == (503, payroll_deposits.NOT_READY)
    run(db, "2026-11-30", "paid", lines=standard_lines())
    assert pr.payroll_calendar_month(CHURCH, "2026-12", user=user(OWNER))["deposits_ready"] is False


def test_mark_sent_is_one_row_a_key_and_undo_takes_it_back(db):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    out = _mark(OWNER, sent_on="2026-12-10", reference="  EFT <123>  ")
    assert out["ok"] and out["deposit"]["key"] == "federal:2026-11" and out["deposit"]["amount"] == 956.0
    assert out["deposit"]["due_on"] == "2026-12-15" and out["deposit"]["reference"] == "EFT  123"
    again = _mark(ADMIN, amount=957.25)
    assert again["deposit"]["amount"] == 957.25 and len(db.rows("payroll_deposits")) == 1
    cal = pr.payroll_calendar_month(CHURCH, "2026-12", user=user(OWNER))
    fed = next(e for d in cal["days"] for e in d["events"] if e["kind"] == "deposit_federal")
    assert fed["status"] == "sent"
    assert pr.undo_deposit_sent(pr.DepositKeyBody(business_id=CHURCH, key="federal:2026-11"),
                                user=user(OWNER)) == {"ok": True}
    assert db.rows("payroll_deposits") == []


def test_mark_sent_refuses_who_it_should_and_what_it_should(db):
    for u in (MANAGER, MEMBER, VIEWER, ACCOUNTANT, STRANGER, OTHER_OWNER):
        assert status(_mark, u)[0] == 403, u
    for bad in ({"key": "federal:2026-13"}, {"key": "anything"}, {"amount": -1.0}, {"amount": 2e7},
                {"sent_on": "12/10/2026"}, {"sent_on": "2020-01-01"}, {"biz": "biz1"}):
        kw = {"key": "federal:2026-11", "amount": 956.0, **bad}
        biz = kw.pop("biz", CHURCH)
        assert status(_mark, OWNER, biz=biz, **kw)[0] == 400, bad
    assert db.rows("payroll_deposits") == []


# ─── Settings ─────────────────────────────────────────────────────────

def test_settings_are_the_owners_or_an_admins_and_touch_only_their_own_keys(db):
    body = pr.PayrollSettingsBody(business_id=CHURCH, deposit_schedule="semiweekly", state_day=20,
                                  state_label="Ohio IT 501")
    out = pr.put_payroll_settings(body, user=user(ADMIN))
    assert out == {"ok": True, "settings": {"deposit_schedule": "semiweekly", "state_day": 20,
                                            "state_label": "Ohio IT 501"}}
    biz = next(b for b in db.rows("businesses") if b["id"] == CHURCH)
    assert biz["settings"]["payroll"] == {"deposit_schedule": "semiweekly", "state_day": 20,
                                          "state_label": "Ohio IT 501"}
    assert biz["settings"]["brand_kit"] == {"colors": {"primary": "#0f766e"}}       # untouched
    cleared = pr.put_payroll_settings(pr.PayrollSettingsBody(business_id=CHURCH, state_day=None), user=user(OWNER))
    assert cleared["settings"]["state_day"] is None and cleared["settings"]["deposit_schedule"] == "semiweekly"
    for u in (MANAGER, VIEWER, ACCOUNTANT, STRANGER):
        assert status(pr.put_payroll_settings, body, user=user(u))[0] == 403, u
    for bad in ({"state_day": 29}, {"deposit_schedule": "daily"}, {"state_day": 0}):
        assert status(pr.put_payroll_settings, pr.PayrollSettingsBody(business_id=CHURCH, **bad),
                      user=user(OWNER))[0] == 400, bad


# ─── Worksheets ───────────────────────────────────────────────────────

def test_the_worksheet_doors(db):
    run(db, "2026-10-30", "paid", lines=standard_lines())
    q = pr.forms_quarter(CHURCH, q=4, year=2026, user=user(OWNER))
    # No designation on file for 2026: the pastor's $2,000 of housing is wages too.
    assert q["lines"]["2"] == 8000.0 and q["runs_in"] == 1
    y = pr.forms_year(CHURCH, year=2026, user=user(ADMIN))
    assert y["w3"]["1"] == 8000.0
    for fn, kw, media in ((pr.forms_quarter_pdf, {"q": 4}, "application/pdf"),
                          (pr.forms_year_pdf, {}, "application/pdf"),
                          (pr.forms_year_csv, {}, "text/csv; charset=utf-8")):
        resp = fn(CHURCH, year=2026, user=user(OWNER), **kw)
        assert resp.media_type == media and resp.headers["cache-control"] == "no-store"
    for u in (MANAGER, VIEWER, STRANGER, OTHER_OWNER):
        assert status(pr.forms_year, CHURCH, year=2026, user=user(u))[0] == 403, u
        assert status(pr.forms_quarter, CHURCH, q=4, year=2026, user=user(u))[0] == 403, u


# ─── The giving tick (CHURCH_MONEY_TICKS): Work to read, never See ────

@pytest.mark.parametrize("mode, platform, level, want", [
    ("off", None, "work", (403, gate.GIVING_403)),
    ("off", None, "see", (403, gate.GIVING_403)),
    ("owner", "church", "work", (200, None)),
    ("owner", "church", "see", (403, gate.PAY_RECORDS_403)),
    ("owner", "other", "work", (403, gate.GIVING_403)),
    ("owner", "other", "see", (403, gate.GIVING_403)),
    ("on", None, "work", (200, None)),
    ("on", None, "see", (403, gate.PAY_RECORDS_403)),
])
def test_the_switch_columns_for_payroll_and_contractor_reads(db, monkeypatch, mode, platform, level, want):
    import contractors_router
    import reports_router
    run(db, "2026-11-30", "paid", lines=standard_lines())
    ticks(monkeypatch, {MANAGER: tick(level)}, mode=mode,
          platform={"church": CHURCH, "other": OTHER, None: None}[platform])
    got = status(pr.payroll_calendar_month, CHURCH, "2026-12", user=user(MANAGER))
    assert got == want
    assert status(pr.list_runs, CHURCH, user=user(MANAGER)) == want
    assert status(pr.forms_year, CHURCH, year=2026, user=user(MANAGER)) == want
    assert status(contractors_router.list_contractors, CHURCH, user=user(MANAGER)) == want
    assert status(reports_router.summary_1099, CHURCH, 2026, user=user(MANAGER)) == want
    # The owner and an Admin are never asked anything new.
    for u in (OWNER, ADMIN):
        assert status(pr.payroll_calendar_month, CHURCH, "2026-12", user=user(u))[0] == 200


def test_a_work_tick_marks_deposits_but_settings_and_sending_stay_the_owners_and_admins(db, monkeypatch):
    paid = run(db, "2026-11-30", "paid", lines=standard_lines())
    ticks(monkeypatch, {MANAGER: tick("work"), MEMBER: tick("see", "member")})
    assert _mark(MANAGER)["ok"]
    assert status(_mark, MEMBER) == (403, gate.PAY_RECORDS_403)
    assert status(pr.put_payroll_settings, pr.PayrollSettingsBody(business_id=CHURCH, state_day=10),
                  user=user(MANAGER))[0] == 403
    assert pr.run_stubs(paid["id"], user=user(MANAGER))["ok"]                       # Work reads
    assert status(pr.send_run_stubs, paid["id"], None, user=user(MANAGER))[0] == 403
    assert status(pr.run_stubs, paid["id"], user=user(MEMBER))[0] == 404            # See: not even a statement


def test_with_the_switch_off_nobody_gains_or_loses_payroll(db, monkeypatch):
    run(db, "2026-11-30", "paid", lines=standard_lines())
    everyone = (OWNER, ADMIN, MANAGER, MEMBER, VIEWER, ACCOUNTANT, STRANGER, OTHER_OWNER)

    def answers():
        return {u: status(pr.payroll_calendar_month, CHURCH, "2026-12", user=user(u)) for u in everyone}
    before = answers()
    ticks(monkeypatch, {MANAGER: tick("lead"), MEMBER: tick("work", "member"), VIEWER: tick("see", "viewer")},
          mode="off")
    assert answers() == before
    assert {u for u, a in before.items() if a[0] == 200} == {OWNER, ADMIN}


# ─── Around the doors ─────────────────────────────────────────────────

MIGRATION = ROOT / "supabase" / "APPLY-2026-11-19-payroll-deposits.sql"


def test_the_migration_makes_two_server_only_tables_safely():
    sql = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    for table in ("payroll_deposits", "payroll_reminders_sent"):
        assert f"create table if not exists public.{table}(" in body
        assert f"alter table public.{table} enable row level security;" in body
        assert f"revoke all on public.{table} from public, anon, authenticated;" in body
        assert f"grant all on public.{table} to service_role;" in body
    assert "create policy" not in body.lower() and "drop " not in body.lower()
    assert "unique (business_id, key)" in body and "unique (business_id, key, audience)" in body
    assert "check (kind in ('federal', 'state', 'forms'))" in body and "amount numeric(12,2)" in body
    assert body.strip().startswith("begin;") and "commit;" in body and "notify pgrst, 'reload schema';" in body
    assert "lock_timeout" in body
    # The key shape matches the server's.
    import payroll_calendar
    for key in ("federal:2026-11", "federal:2026-12-22", "state:2026-11", "forms:941:2026Q4", "forms:w2:2026"):
        assert payroll_calendar.parse_key(key)
    assert "forms:941:[0-9]{4}Q[1-4]" in body


def test_the_ledger_names_it_not_applied():
    ledger = (ROOT / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(ln for ln in ledger.splitlines() if "APPLY-2026-11-19-payroll-deposits.sql" in ln)
    assert row.rstrip().endswith("| **NOT APPLIED** |")


def test_the_two_switches_are_documented():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^PAYROLL_STUB_EMAIL=on\b", env, re.M)
    assert re.search(r"^PAYROLL_REMINDERS=on\b", env, re.M)


def test_export_and_delete_know_the_new_tables():
    import account_lifecycle as al
    assert "payroll_deposits" in al.BUSINESS_CHILD_TABLES and "payroll_deposits" in al._IMPORT_SKIP
    assert "payroll_reminders_sent" in al.EXPORT_EXCLUDED
    assert "payroll_reminders_sent" not in al.BUSINESS_CHILD_TABLES


def test_the_reminders_run_hourly_on_the_scheduler():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'scheduler.add_job(g("payroll_reminders", _payroll_reminders.tick), "interval", hours=1,' in src
    assert 'id="payroll_reminders", max_instances=1)' in src


NEW_MODULES = ("payroll_calendar", "payroll_deposits", "payroll_carry", "payroll_stubs", "payroll_forms",
               "payroll_reminders")


def test_no_log_line_carries_a_name_an_email_or_an_amount():
    risky = ("email", "first_name", "last_name", "name_of", "amount", "gross", "net", "ssn", "money(", "who",
             "to)", "body", "title")
    for mod in NEW_MODULES:
        for n, line in enumerate((ROOT / f"{mod}.py").read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith(("logger.", "print(")):
                args = s.split("(", 1)[1]
                code = re.sub(r'"[^"]*"', '""', args)            # the words in quotes aren't data
                for r in risky:
                    assert r not in code, f"{mod}.py:{n}: {s}"


def test_payroll_reads_never_select_the_ssn_or_tin_ciphertext():
    for mod in NEW_MODULES:
        src = (ROOT / f"{mod}.py").read_text(encoding="utf-8")
        for m in re.finditer(r"/employee_tax_profiles\?[^\"']*", src):
            assert "ssn_encrypted" not in m.group(0) and "select=*" not in m.group(0), mod
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
        assert "tin_encrypted" not in code and "decrypt" not in code, mod
