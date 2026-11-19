"""Payroll, the free version: the hourly reminders (payroll_reminders.py).

Three days out the payroll team hears once; the day before, the owner alone;
never twice for the same key and day; never for something marked sent or
done; never for a sample church, in quiet hours, before the migration, or
with the switch off. Every name and figure is made up.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import payroll_reminders as prm
from payroll_free_fake import (ADMIN, CHURCH, MANAGER, MEMBER, OWNER, PayrollFake, install, people, run, seed,
                               standard_lines, tick, ticks)


REAL_TELL = prm._tell          # before any fixture stands in for it


def at(day: int, hour: int = 15, month: int = 12) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    db = install(monkeypatch, seed(PayrollFake()))
    people(db)
    monkeypatch.setattr(prm, "_zone", lambda biz: ZoneInfo("UTC"))
    import sample_church
    monkeypatch.setattr(sample_church, "drop_samples", lambda ids, key="business_id": list(ids))
    db.told = []
    monkeypatch.setattr(prm, "_tell", lambda biz, to, title, body, tag: db.told.append(
        {"biz": biz["id"], "to": set(to), "title": title, "body": body, "tag": tag}))
    db.draft = run(db, "2026-12-15", "draft", lines=standard_lines())
    db.paid = run(db, "2026-11-30", "paid", lines=standard_lines())
    return db


def test_three_days_out_the_team_hears_once_and_the_day_before_the_owner(db):
    out = prm.sweep(at(8))
    assert out["alerts"] == 1 and len(db.told) == 1
    t = db.told[0]
    assert t["to"] == {OWNER, ADMIN} and t["title"] == "Approve the Dec 15 run by Fri, Dec 11"
    assert "two bank days before payday" in t["body"] and "the church’s bank" in t["body"]
    claimed = db.rows("payroll_reminders_sent")
    assert [(c["key"], c["audience"], c["sent_on"]) for c in claimed] == [
        (f"approve:{db.draft['id']}", "team", "2026-12-08")]
    # The same hour again, and the next day: nothing new.
    assert prm.sweep(at(8, 16))["alerts"] == 0
    assert prm.sweep(at(9))["alerts"] == 0
    assert len(db.told) == 1
    # The day before: the owner alone.
    assert prm.sweep(at(10))["alerts"] == 1
    assert db.told[-1]["to"] == {OWNER} and db.told[-1]["title"] == "Tomorrow: Approve the Dec 15 run by Fri, Dec 11"
    assert prm.sweep(at(10, 18))["alerts"] == 0


def test_a_deposit_three_days_out_and_nothing_once_it_is_marked_sent(db):
    prm.sweep(at(8))
    assert prm.sweep(at(12))["alerts"] == 1                         # Saturday the 12th: due Tuesday the 15th
    t = db.told[-1]
    assert t["title"] == "IRS deposit due Tue, Dec 15: $956.00" and "EFTPS.gov" in t["body"]
    db.rows("payroll_deposits").append({"business_id": CHURCH, "key": "federal:2026-11", "kind": "federal",
                                        "period": "2026-11", "amount": 956.0, "sent_on": "2026-12-12"})
    before = len(db.told)
    prm.sweep(at(14))
    assert len(db.told) == before                                   # marked sent: no owner alert


def test_an_approved_run_needs_no_reminder(db):
    db.draft["status"] = "approved"
    assert prm.sweep(at(8))["alerts"] == 0 and db.told == []


def test_quiet_hours_send_nothing_and_claim_nothing(db):
    assert prm.sweep(at(8, 5))["alerts"] == 0
    assert prm.sweep(at(8, 21))["alerts"] == 0
    assert db.rows("payroll_reminders_sent") == [] and db.told == []
    assert prm.sweep(at(8, 8))["alerts"] == 1


def test_the_switch_off_reads_nothing(db, monkeypatch):
    monkeypatch.setenv("PAYROLL_REMINDERS", "off")
    db.reads.clear()
    assert prm.sweep(at(8))["skipped"] == "off"
    assert asyncio.run(prm.tick()) == {"skipped": "off"}
    assert db.reads == [] and db.told == []


@pytest.mark.parametrize("platform, hears", [(True, 1), (False, 0)])
def test_owner_mode_is_the_platform_owners_church_alone(db, monkeypatch, platform, hears):
    import member_asks
    monkeypatch.setenv("PAYROLL_REMINDERS", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: platform and str(biz) == CHURCH)
    assert prm.sweep(at(8))["alerts"] == hears


def test_before_the_migration_the_reminders_skip(db):
    db.missing.add("payroll_reminders_sent")
    assert prm.sweep(at(8))["skipped"] == "not_ready" and db.told == []


def test_a_sample_church_is_skipped(db, monkeypatch):
    import sample_church
    monkeypatch.setattr(sample_church, "drop_samples", lambda ids, key="business_id": [i for i in ids if i != CHURCH])
    assert prm.sweep(at(8))["alerts"] == 0 and db.told == []


def test_a_business_with_no_runs_is_never_read(db):
    for r in db.rows("pay_runs"):
        r["status"] = "cancelled"
    db.reads.clear()
    assert prm.sweep(at(8))["alerts"] == 0
    assert not any(r.startswith("/businesses") for r in db.reads)


def test_with_the_giving_tick_on_a_work_holder_hears_and_a_see_holder_does_not(db, monkeypatch):
    ticks(monkeypatch, {MANAGER: tick("work"), MEMBER: tick("see", "member")})
    prm.sweep(at(8))
    assert db.told[0]["to"] == {OWNER, ADMIN, MANAGER}


def test_the_alert_goes_by_phone_and_email_through_the_church_path(db, monkeypatch, caplog):
    import email_sender
    import messaging_router
    import push_notifications
    import threading
    pushes, mails = [], []
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: pushes.append((uid, kw)) or 1)

    async def mail(**kw):
        mails.append(kw)
        return {}
    monkeypatch.setattr(email_sender, "send_via_resend", mail)
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda uid: "pastor@graceharbor.example")

    class Now:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(threading, "Thread", Now)
    biz = next(b for b in db.rows("businesses") if b["id"] == CHURCH)
    caplog.set_level(logging.INFO)
    REAL_TELL(biz, {OWNER, ADMIN}, "IRS deposit due Tue, Dec 15: $956.00", "Pay it on EFTPS.gov.", "payroll-x")
    assert sorted(u for u, _ in pushes) == sorted([OWNER, ADMIN])
    assert all(kw["nav"] == "operate:pay-staff" and kw["business_id"] == CHURCH for _, kw in pushes)
    assert sorted(m["to_email"] for m in mails) == ["admin@graceharbor.example", "pastor@graceharbor.example"]
    assert all(m["from_name"] == "Grace Harbor Church" and m["business_id"] == CHURCH for m in mails)
    assert "956" not in caplog.text and "pastor@" not in caplog.text


def test_several_dates_at_once_are_one_alert(db):
    db.paid["pay_date"] = "2026-11-30"
    run(db, "2026-12-14", "draft", lines=standard_lines())    # approve-by Thursday Dec 10
    prm.sweep(at(8))                                          # Dec 10 is 2 days out, Dec 11 is 3
    assert len(db.told) == 1 and db.told[0]["title"] == "2 payroll dates in the next 3 days"
    assert db.told[0]["body"].count("Approve the") == 2
    assert len(db.rows("payroll_reminders_sent")) == 2


def test_the_audience_rule():
    assert [prm.audience_for(n) for n in range(0, 6)] == [None, "owner", "team", "team", None, None]
