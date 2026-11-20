"""Payroll, the free version: deposits marked sent and the reminders' memory
(payroll_deposits.py). Made-up figures only."""
from __future__ import annotations

import logging
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest

import payroll_calendar as pcal
import payroll_deposits as pdep
from payroll_free_fake import CHURCH, OWNER, PayrollFake, install, seed


@pytest.fixture
def db(monkeypatch):
    return install(monkeypatch, seed(PayrollFake()))


def _mark(key="federal:2026-11", amount=956.0, ref="EFT-123"):
    return pdep.mark_sent(CHURCH, key, pcal.parse_key(key), amount=amount, sent_on=date(2026, 12, 10),
                          reference=ref, due_on=date(2026, 12, 15), by=OWNER)


def test_marking_twice_keeps_one_row_and_updates_it(db):
    first = _mark()
    assert first["kind"] == "federal" and first["period"] == "2026-11" and first["amount"] == 956.0
    again = _mark(amount=960.5, ref="EFT-124")
    rows = db.rows("payroll_deposits")
    assert len(rows) == 1 and rows[0]["amount"] == 960.5 and rows[0]["reference"] == "EFT-124"
    assert again["sent_on"] == "2026-12-10" and again["due_on"] == "2026-12-15"
    marked, ready = pdep.marked(CHURCH)
    assert ready and set(marked) == {"federal:2026-11"}
    assert pdep.public(marked["federal:2026-11"]) == {
        "key": "federal:2026-11", "kind": "federal", "period": "2026-11", "amount": 960.5,
        "due_on": "2026-12-15", "sent_on": "2026-12-10", "reference": "EFT-124",
        "marked_at": rows[0]["marked_at"]}


def test_undo_takes_it_back_and_twice_is_fine(db):
    _mark()
    pdep.undo(CHURCH, "federal:2026-11")
    assert db.rows("payroll_deposits") == []
    pdep.undo(CHURCH, "federal:2026-11")


def test_before_the_migration_nothing_is_marked_and_writes_say_not_ready(db):
    db.missing.update({"payroll_deposits", "payroll_reminders_sent"})
    assert pdep.marked(CHURCH) == ({}, False)
    with pytest.raises(pdep.NotReady):
        _mark()
    with pytest.raises(pdep.NotReady):
        pdep.undo(CHURCH, "federal:2026-11")
    assert pdep.NOT_READY == "Deposit tracking is being switched on. Try again shortly."


def test_a_no_is_asked_again_later_and_a_yes_is_kept(db, monkeypatch):
    db.missing.add("payroll_deposits")
    assert not pdep.ready()
    db.missing.clear()
    assert not pdep.ready()                       # held for five minutes
    monkeypatch.setitem(pdep._READY[pdep.DEPOSITS], "until", 0.0)
    assert pdep.ready()
    db.missing.add("payroll_deposits")
    assert pdep.ready()                           # kept for good once yes


def test_after_the_migration_a_failed_read_is_none_not_nothing(db, monkeypatch):
    assert pdep.ready()
    db.missing.add("payroll_deposits")
    assert pdep.marked(CHURCH) == (None, True)


def test_a_failed_write_is_not_a_save(db, monkeypatch):
    assert pdep.ready()
    monkeypatch.setattr(db, "post", lambda *a, **k: None)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    with pytest.raises(pdep.SaveFailed):
        _mark()


def test_a_reminder_is_claimed_once_per_key_and_audience(db):
    day = date(2026, 12, 8)
    assert pdep.claim_reminder(CHURCH, "approve:abc", "team", day) is True
    assert pdep.claim_reminder(CHURCH, "approve:abc", "team", day) is False
    assert pdep.claim_reminder(CHURCH, "approve:abc", "team", date(2026, 12, 9)) is False
    assert pdep.claim_reminder(CHURCH, "approve:abc", "owner", day) is True
    db.missing.add("payroll_reminders_sent")
    assert pdep.claim_reminder(CHURCH, "approve:xyz", "team", day) is None


def test_logs_never_carry_amounts(db, caplog):
    caplog.set_level(logging.INFO)
    _mark(amount=1234.56, ref="EFT-SECRET")
    text = caplog.text
    assert "1234" not in text and "EFT-SECRET" not in text


def test_deposited_sums_only_the_keys_asked():
    rows = {"federal:2026-10": {"amount": "956.00"}, "federal:2026-11": {"amount": 950.5},
            "state:2026-11": {"amount": 140}}
    assert pdep.deposited(rows, ["federal:2026-10", "federal:2026-11", "federal:2026-12"]) == 1906.5
