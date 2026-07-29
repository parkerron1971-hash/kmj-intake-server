"""
test_customer_balances.py — the drawdown ledger.

The tests that matter here are the refusal ones. Granting is easy to get
right; the failure mode that costs a practitioner money is a consume() that
succeeds when it should not, so overdraw, validation and the concurrent-draw
reversal get the most attention.

Supabase is stubbed rather than hit: the arithmetic and the guard logic live
in this module, and the parts that live in Postgres (the CHECK constraints,
the view's SUM) are asserted by the migration's own verify block instead of
pretended-at here.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

import customer_balances as cb


# ─── a stub that behaves like the ledger ─────────────────────────────

class FakeSB:
    """Append-only rows + a balance view computed the way Postgres would."""

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []
        self.post_calls = 0

    # -- writes --
    def sb_post_as_service(self, path, row):
        assert path == "/customer_ledger"
        self.post_calls += 1
        r = dict(row)
        r["id"] = f"row-{len(self.rows) + 1}"
        self.rows.append(r)
        return [r]

    # -- reads --
    def sb_get_as_service(self, path):
        if path.startswith("/customer_balances"):
            return self._balances(path)
        if path.startswith("/customer_ledger"):
            return list(reversed(self.rows))
        return []

    def _balances(self, path):
        def val(k):
            for part in path.split("&"):
                if part.split("?")[-1].startswith(f"{k}=eq."):
                    return part.split("=eq.")[1]
            return None
        biz, contact = val("business_id"), val("contact_id")
        kind, unit = val("kind"), val("unit")
        agg: Dict[Any, float] = {}
        for r in self.rows:
            if r["business_id"] != biz or r["contact_id"] != contact:
                continue
            if kind and r["kind"] != kind:
                continue
            if unit and r["unit"] != unit:
                continue
            key = (r["kind"], r["unit"], r.get("currency", "usd"))
            agg[key] = agg.get(key, 0) + float(r["delta"])
        return [{"business_id": biz, "contact_id": contact, "kind": k,
                 "unit": u, "currency": c, "balance": v}
                for (k, u, c), v in agg.items()]


@pytest.fixture
def sb(monkeypatch):
    fake = FakeSB()
    import sys, types
    mod = types.ModuleType("sb_clients")
    mod.sb_post_as_service = fake.sb_post_as_service
    mod.sb_get_as_service = fake.sb_get_as_service
    monkeypatch.setitem(sys.modules, "sb_clients", mod)
    return fake


BIZ, CONTACT = "biz-1", "contact-1"


# ─── granting ────────────────────────────────────────────────────────

def test_grant_then_balance(sb):
    cb.grant(BIZ, CONTACT, 6, "package", "session", "6-session package")
    assert cb.balance(BIZ, CONTACT, "package", "session") == 6


def test_consume_draws_down(sb):
    cb.grant(BIZ, CONTACT, 6, "package", "session", "bought")
    res = cb.consume(BIZ, CONTACT, 1, "package", "session", "session delivered")
    assert res["ok"] is True
    assert res["balance"] == 5


def test_balance_is_a_sum_not_a_counter(sb):
    """Three grants and two draws must reconcile by summation."""
    cb.grant(BIZ, CONTACT, 5, "package", "session", "a")
    cb.grant(BIZ, CONTACT, 3, "package", "session", "b")
    cb.consume(BIZ, CONTACT, 2, "package", "session", "c")
    cb.grant(BIZ, CONTACT, 1, "package", "session", "d")
    cb.consume(BIZ, CONTACT, 4, "package", "session", "e")
    assert cb.balance(BIZ, CONTACT, "package", "session") == 3


# ─── the refusals ────────────────────────────────────────────────────

def test_consume_refuses_to_overdraw(sb):
    """The test that protects the practitioner's money."""
    cb.grant(BIZ, CONTACT, 1, "package", "session", "one session")
    res = cb.consume(BIZ, CONTACT, 2, "package", "session", "two sessions")
    assert res["ok"] is False
    assert res["error"] == "insufficient balance"
    assert res["available"] == 1
    assert res["shortfall"] == 1


def test_refused_consume_writes_nothing(sb):
    cb.grant(BIZ, CONTACT, 1, "package", "session", "one")
    before = sb.post_calls
    cb.consume(BIZ, CONTACT, 5, "package", "session", "nope")
    assert sb.post_calls == before, "a refused consume must not write a row"


def test_overdraw_allowed_when_explicit(sb):
    cb.grant(BIZ, CONTACT, 1, "package", "session", "one")
    res = cb.consume(BIZ, CONTACT, 3, "package", "session", "did the work anyway",
                     allow_overdraw=True)
    assert res["ok"] is True
    assert res["balance"] == -2


def test_consume_on_empty_balance_refuses(sb):
    res = cb.consume(BIZ, CONTACT, 1, "package", "session", "nothing there")
    assert res["ok"] is False
    assert res["available"] == 0


@pytest.mark.parametrize("bad", [0, -1, -0.5])
def test_non_positive_amounts_rejected(sb, bad):
    assert cb.grant(BIZ, CONTACT, bad, "package", "session", "x")["ok"] is False
    assert cb.consume(BIZ, CONTACT, bad, "package", "session", "x")["ok"] is False


def test_reason_is_required(sb):
    """An unexplained movement in a money ledger is worse than no ledger."""
    assert cb.grant(BIZ, CONTACT, 5, "package", "session", "   ")["ok"] is False
    cb.grant(BIZ, CONTACT, 5, "package", "session", "real")
    assert cb.consume(BIZ, CONTACT, 1, "package", "session", "")["ok"] is False


@pytest.mark.parametrize("kind,unit", [
    ("nonsense", "session"), ("package", "nonsense"), ("", ""),
])
def test_invalid_taxonomy_rejected(sb, kind, unit):
    assert cb.grant(BIZ, CONTACT, 1, kind, unit, "x")["ok"] is False


# ─── the concurrent-draw reversal ────────────────────────────────────

def test_lost_race_reverses_its_own_row(sb, monkeypatch):
    """Two draws read '1 left' at the same time. The loser must undo itself
    rather than leaving the ledger at -1."""
    cb.grant(BIZ, CONTACT, 1, "package", "session", "one session")

    # Simulate the other writer landing between our read and our write.
    real_post = sb.sb_post_as_service
    fired = {"done": False}

    def racing_post(path, row):
        out = real_post(path, row)
        if not fired["done"] and float(row["delta"]) < 0:
            fired["done"] = True
            real_post("/customer_ledger", {
                "business_id": BIZ, "contact_id": CONTACT, "kind": "package",
                "unit": "session", "delta": -1, "reason": "the other booking"})
        return out

    import sys
    sys.modules["sb_clients"].sb_post_as_service = racing_post

    res = cb.consume(BIZ, CONTACT, 1, "package", "session", "my booking")

    assert res["ok"] is False
    assert res["overdrawn"] is True
    assert res["reversed"] is True
    # Net: grant 1, their draw -1, our draw -1, our reversal +1 == 0.
    assert cb.balance(BIZ, CONTACT, "package", "session") == 0


# ─── separation of ledgers ───────────────────────────────────────────

def test_kinds_and_units_do_not_bleed(sb):
    """A retainer in dollars must never satisfy a package in sessions."""
    cb.grant(BIZ, CONTACT, 5000, "retainer", "money", "retainer")
    res = cb.consume(BIZ, CONTACT, 1, "package", "session", "session")
    assert res["ok"] is False
    assert cb.balance(BIZ, CONTACT, "retainer", "money") == 5000


def test_contacts_do_not_share_balances(sb):
    cb.grant(BIZ, "contact-A", 5, "package", "session", "A bought")
    assert cb.balance(BIZ, "contact-B", "package", "session") == 0


# ─── vertical defaults ───────────────────────────────────────────────

@pytest.mark.parametrize("vertical,kind,unit", [
    ("coach",           "package",  "session"),
    ("coaching",        "package",  "session"),
    ("lawyer",          "retainer", "hour"),
    ("consultant",      "retainer", "money"),
    ("contractor",      "deposit",  "money"),
    ("attorney",        "retainer", "hour"),     # alias resolves
])
def test_vertical_defaults(vertical, kind, unit):
    d = cb.defaults_for_vertical(vertical)
    assert (d["kind"], d["unit"]) == (kind, unit)


def test_unknown_vertical_gets_a_usable_default():
    d = cb.defaults_for_vertical("crypto_yacht_rental")
    assert d["kind"] in cb.KINDS and d["unit"] in cb.UNITS


# ─── describe ────────────────────────────────────────────────────────

def test_describe_money_and_sessions(sb):
    cb.grant(BIZ, CONTACT, 4, "package", "session", "pkg")
    cb.grant(BIZ, CONTACT, 2500, "retainer", "money", "ret")
    text = cb.describe_balances(BIZ, CONTACT)
    assert "4 sessions" in text
    assert "$2,500.00" in text


def test_describe_empty(sb):
    assert cb.describe_balances(BIZ, CONTACT) == "no prepaid balance"


def test_describe_singular_session(sb):
    cb.grant(BIZ, CONTACT, 1, "package", "session", "pkg")
    assert "1 session" in cb.describe_balances(BIZ, CONTACT)
    assert "1 sessions" not in cb.describe_balances(BIZ, CONTACT)


# ─── zero-balance rows are hidden, not shown as noise ────────────────

def test_fully_consumed_balance_drops_out_of_the_summary(sb):
    cb.grant(BIZ, CONTACT, 2, "package", "session", "pkg")
    cb.consume(BIZ, CONTACT, 2, "package", "session", "both used")
    assert cb.balances_for_contact(BIZ, CONTACT) == []
    assert cb.describe_balances(BIZ, CONTACT) == "no prepaid balance"
