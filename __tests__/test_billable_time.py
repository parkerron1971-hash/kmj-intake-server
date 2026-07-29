"""
test_billable_time.py — billable time.

The duration parser and the increment rounding get the most attention here,
because they are where a bill quietly becomes wrong. A time entry that is
off by a tenth of an hour is not a rounding curiosity in a law practice — it
is a fee dispute, and eventually a bar complaint.
"""
from __future__ import annotations

import pytest

import billable_time as bt


# ─── duration parsing ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (90,        90),        # bare int = minutes
    ("90",      90),
    ("90m",     90),
    ("90min",   90),
    ("1.5h",    90),
    ("1:30",    90),
    ("1h",      60),
    ("0:45",    45),
    (1.5,       90),        # bare float = HOURS
    (2.0,       120),
    (" 1.5H ",  90),        # whitespace + case
])
def test_parse_duration(raw, expected):
    assert bt.parse_duration(raw) == expected


def test_int_is_minutes_but_float_is_hours():
    """The rule worth pinning: 'log 90' means ninety minutes, 'log 1.5'
    means an hour and a half. Nobody says 1.5 minutes."""
    assert bt.parse_duration(2) == 2
    assert bt.parse_duration(2.0) == 120


@pytest.mark.parametrize("bad", [None, "", "   ", "abc", 0, -30, "-1h", True, False])
def test_unparseable_durations_return_none(bad):
    """None means 'ask again', never a silently-wrong number on a bill."""
    assert bt.parse_duration(bad) is None


# ─── increment rounding ──────────────────────────────────────────────

@pytest.mark.parametrize("mins,expected", [
    (1, 6), (5, 6), (6, 6),        # anything in the first tenth bills as one
    (7, 12), (11, 12), (12, 12),
    (90, 90),                       # already on the increment
    (61, 66),
])
def test_rounds_up_to_the_six_minute_increment(mins, expected):
    assert bt.round_to_increment(mins) == expected


def test_rounding_never_loses_time():
    """Rounding DOWN would mean working for free. Every value must round up
    or stay put — never below."""
    for m in range(1, 200):
        assert bt.round_to_increment(m) >= m


def test_increment_is_configurable():
    assert bt.round_to_increment(10, increment=15) == 15
    assert bt.round_to_increment(1, increment=1) == 1


# ─── presentation ────────────────────────────────────────────────────

@pytest.mark.parametrize("mins,shown", [
    (90, "1.5"), (60, "1.0"), (6, "0.1"), (30, "0.5"), (450, "7.5"),
])
def test_format_hours(mins, shown):
    assert bt.format_hours(mins) == shown


# ─── writes, against a stub ──────────────────────────────────────────

class FakeSB:
    def __init__(self):
        self.entries = {}
        self.ledger = []
        self.n = 0

    def sb_post_as_service(self, path, row):
        self.n += 1
        rid = f"id-{self.n}"
        r = dict(row); r["id"] = rid
        if path.startswith("/time_entries"):
            self.entries[rid] = r
        else:
            self.ledger.append(r)
        return [r]

    def sb_get_as_service(self, path):
        if path.startswith("/time_entries"):
            for rid in self.entries:
                if f"id=eq.{rid}" in path:
                    return [self.entries[rid]]
            return [e for e in self.entries.values()
                    if e.get("status") == "unbilled" and e.get("billable")]
        if path.startswith("/customer_ledger"):
            return list(reversed(self.ledger))[:1]
        if path.startswith("/customer_balances"):
            total = sum(float(r["delta"]) for r in self.ledger
                        if r.get("kind") == "retainer" and r.get("unit") == "hour")
            return [{"balance": total, "kind": "retainer", "unit": "hour",
                     "currency": "usd"}]
        return []

    def sb_patch_as_service(self, path, body):
        for rid in self.entries:
            if f"id=eq.{rid}" in path:
                self.entries[rid].update(body)
                return [self.entries[rid]]
        return []


@pytest.fixture
def sb(monkeypatch):
    import sys, types
    fake = FakeSB()
    mod = types.ModuleType("sb_clients")
    mod.sb_post_as_service = fake.sb_post_as_service
    mod.sb_get_as_service = fake.sb_get_as_service
    mod.sb_patch_as_service = fake.sb_patch_as_service
    monkeypatch.setitem(sys.modules, "sb_clients", mod)
    return fake


BIZ, CONTACT = "biz-1", "contact-1"


def test_log_time_records_and_rounds(sb):
    res = bt.log_time(BIZ, CONTACT, 91, "Drafted the response", rate=350)
    assert res["ok"] is True
    assert res["minutes"] == 96          # rounded up to the increment
    assert res["rounded_from"] == 91
    assert res["hours"] == "1.6"
    assert res["amount"] == pytest.approx(560.0)


def test_description_is_required(sb):
    """A bill line with no narrative is a fee dispute waiting to happen."""
    assert bt.log_time(BIZ, CONTACT, 60, "   ")["ok"] is False


@pytest.mark.parametrize("bad", [0, -5, 1441])
def test_impossible_durations_rejected(sb, bad):
    assert bt.log_time(BIZ, CONTACT, bad, "work")["ok"] is False


def test_entry_starts_unbilled(sb):
    res = bt.log_time(BIZ, CONTACT, 60, "work")
    assert sb.entries[res["id"]]["status"] == "unbilled"


# ─── billing to a retainer ───────────────────────────────────────────

def _fund(sb, hours):
    sb.ledger.append({"id": "grant-1", "kind": "retainer", "unit": "hour",
                      "delta": hours, "business_id": BIZ, "contact_id": CONTACT})


def test_bill_to_retainer_draws_and_marks_billed(sb):
    _fund(sb, 10)
    e = bt.log_time(BIZ, CONTACT, 90, "Drafted the response")
    res = bt.bill_to_retainer(BIZ, CONTACT, e["id"])
    assert res["ok"] is True
    assert sb.entries[e["id"]]["status"] == "billed"
    assert sb.entries[e["id"]]["ledger_entry_id"] is not None


def test_insufficient_retainer_leaves_the_entry_unbilled(sb):
    """The order that matters: the draw happens first, and a failed draw
    must NOT leave an entry marked paid."""
    _fund(sb, 1)
    e = bt.log_time(BIZ, CONTACT, 180, "Long day")
    res = bt.bill_to_retainer(BIZ, CONTACT, e["id"])
    assert res["ok"] is False
    assert sb.entries[e["id"]]["status"] == "unbilled"


def test_cannot_bill_the_same_entry_twice(sb):
    """The double-billing guard — the reason ledger_entry_id is stored."""
    _fund(sb, 10)
    e = bt.log_time(BIZ, CONTACT, 60, "work")
    assert bt.bill_to_retainer(BIZ, CONTACT, e["id"])["ok"] is True
    second = bt.bill_to_retainer(BIZ, CONTACT, e["id"])
    assert second["ok"] is False
    assert "already" in second["error"]


def test_non_billable_time_cannot_be_billed(sb):
    _fund(sb, 10)
    e = bt.log_time(BIZ, CONTACT, 60, "Pro bono", billable=False)
    res = bt.bill_to_retainer(BIZ, CONTACT, e["id"])
    assert res["ok"] is False
    assert "non-billable" in res["error"]


def test_missing_entry_is_reported_not_crashed(sb):
    assert bt.bill_to_retainer(BIZ, CONTACT, "nope")["ok"] is False


# ─── unbilled summary ────────────────────────────────────────────────

def test_unbilled_summary_totals(sb):
    bt.log_time(BIZ, CONTACT, 60, "a", rate=300)
    bt.log_time(BIZ, CONTACT, 30, "b", rate=300)
    s = bt.unbilled_summary(BIZ)
    assert s["entries"] == 2
    assert s["minutes"] == 90
    assert s["amount"] == pytest.approx(450.0)


def test_unpriced_entries_counted_separately(sb):
    """Entries with no rate contribute TIME but not MONEY. Counting them
    silently would understate what the firm is owed."""
    bt.log_time(BIZ, CONTACT, 60, "priced", rate=300)
    bt.log_time(BIZ, CONTACT, 60, "no rate yet")
    s = bt.unbilled_summary(BIZ)
    assert s["entries"] == 2
    assert s["unpriced_entries"] == 1
    assert s["amount"] == pytest.approx(300.0)


def test_billed_time_leaves_the_unbilled_list(sb):
    _fund(sb, 10)
    e = bt.log_time(BIZ, CONTACT, 60, "work", rate=300)
    bt.bill_to_retainer(BIZ, CONTACT, e["id"])
    assert bt.unbilled_summary(BIZ)["entries"] == 0


def test_written_off_time_leaves_the_unbilled_list(sb):
    e = bt.log_time(BIZ, CONTACT, 60, "goodwill", rate=300)
    bt.write_off(BIZ, e["id"])
    assert bt.unbilled_summary(BIZ)["entries"] == 0
