"""
test_chief_reconcile.py — "reconcile all you can", then check it and undo it.

Kevin, 2026-10-30: Chief should do what he can do on request, except what
needs his permission, and let him check what it did. What this file holds:

  1. ONLY THE CLEAR ROWS change: a payout that matches, a move between the
     business's own accounts where both sides say transfer, a deposit that
     can't be a Stripe payout. A deposit that says Stripe but matched
     nothing is left and listed.
  2. EVERY CHANGE RECORDS ITS BEFORE-VALUES, the write is guarded on them,
     and a row changed meanwhile is left alone.
  3. UNDO puts one batch back, guarded on what Chief wrote, so a later
     human decision is never overwritten; a partial undo stays retryable.
  4. WHO MAY: the owner, as the person talking; bulk never runs unprompted.
  5. The registry, undo and lane wiring hold their invariants.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import action_inverse
import action_registry
import chief_of_staff as cos
import chief_reconcile as cr


TODAY = date(2026, 10, 30)


def _tx(tid, amount, name, *, acct="a1", day="2026-10-01", primary=None, kind=None):
    return {"transaction_id": tid, "account_id": acct, "amount": amount, "date": day,
            "name": name, "merchant_name": None, "business_id": "biz-1",
            "plaid_category_primary": primary, "plaid_category_detail": None,
            "reconciliation_status": "unmatched", "reconciled_to_payout_id": None,
            "reconciled_to_transfer_id": None, "reconciled_payout_amount": None,
            "reconciled_payout_date": None, "manual_match_reason": None, "ignored_at": None,
            "money_kind": kind}


def _pairs(rows):
    import bookkeeping_overview as bo
    accts = {"a1": {"account_id": "a1", "name": "Checking", "mask": "1111", "type": "depository"},
             "a2": {"account_id": "a2", "name": "Savings", "mask": "2222", "type": "depository"}}
    return bo.find_transfer_pairs(rows, accts)


def _plan(deposits, outs=(), *, match=lambda t: None, has_stripe=True, kinds=True):
    return cr.plan(list(deposits), list(outs), match=match, has_stripe=has_stripe,
                   kinds_supported=kinds, pair=_pairs, account_label=lambda aid: f"acct {aid}",
                   today=TODAY)


PAYOUT = {"reconciled_to_payout_id": "po_1", "reconciliation_status": "auto_matched",
          "reconciled_payout_amount": 120.0, "reconciled_payout_date": "2026-10-01"}


# ─── 1. Only the clear rows ──────────────────────────────────────────

def test_a_matching_payout_is_matched_with_its_before_values():
    d = _tx("d1", -120.0, "STRIPE TRANSFER")
    changes, left = _plan([d], match=lambda t: PAYOUT if t["transaction_id"] == "d1" else None)
    assert [c["kind"] for c in changes] == ["payout"] and not left
    assert changes[0]["after"] == PAYOUT
    assert changes[0]["before"]["reconciliation_status"] == "unmatched"
    assert changes[0]["before"]["reconciled_to_payout_id"] is None


def test_stripe_in_the_name_but_no_match_is_left_for_the_owner():
    changes, left = _plan([_tx("d1", -50.0, "STRIPE PAYOUT 8812")])
    assert changes == [] and left[0]["_why"].startswith("says Stripe")


def test_a_deposit_that_cant_be_a_payout_is_settled_with_the_reason():
    changes, _ = _plan([_tx("d1", -40.0, "PAYPAL INST XFER")], has_stripe=False)
    (c,) = changes
    assert c["kind"] == "no_payout"
    assert c["after"]["reconciliation_status"] == "ignored"
    assert "no Stripe account is connected" in c["after"]["manual_match_reason"]
    assert c["after"]["manual_match_reason"].startswith("Chief, 2026-10-30")
    assert c["row"]["amount"] == 40.0


def test_own_transfer_needs_both_sides_to_say_transfer():
    out = _tx("o1", 300.0, "ONLINE TRANSFER TO SAV", acct="a1", day="2026-10-02")
    dep = _tx("d1", -300.0, "ONLINE TRANSFER FROM CHK", acct="a2", day="2026-10-02")
    changes, _ = _plan([dep], [out])
    kinds = sorted((c["id"], c["kind"]) for c in changes)
    assert kinds == [("d1", "own_transfer"), ("o1", "own_transfer")]
    by = {c["id"]: c for c in changes}
    assert by["o1"]["after"] == {"money_kind": "transfer"}
    assert by["d1"]["after"]["money_kind"] == "transfer"
    assert by["d1"]["after"]["reconciliation_status"] == "ignored"


def test_a_coincidence_of_amounts_is_not_a_transfer():
    out = _tx("o1", 100.0, "OFFICE DEPOT", acct="a1", day="2026-10-02")
    gift = _tx("d1", -100.0, "MOBILE DEPOSIT", acct="a2", day="2026-10-03")
    changes, _ = _plan([gift], [out], has_stripe=False)
    assert [(c["id"], c["kind"]) for c in changes] == [("d1", "no_payout")], \
        "the gift is settled as a deposit, never folded into a transfer"
    assert "money_kind" not in changes[0]["after"]


def test_without_the_money_kind_column_no_transfer_is_marked():
    out = _tx("o1", 300.0, "TRANSFER", acct="a1")
    dep = _tx("d1", -300.0, "TRANSFER", acct="a2")
    changes, _ = _plan([dep], [out], has_stripe=False, kinds=False)
    assert all("money_kind" not in c["after"] for c in changes)


def test_payments_out_are_never_settled_as_nothing_to_match():
    changes, left = _plan([], [_tx("o1", 25.0, "HOME DEPOT")])
    assert changes == [] and left == []


# ─── 2. Guarded writes ───────────────────────────────────────────────

@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv("CHIEF_BANK_SEARCH", "on")
    token = cos._TURN_USER_ID.set("owner-1")
    import plaid_router
    monkeypatch.setattr(plaid_router, "_require_owner", lambda biz, user: {"id": biz})
    monkeypatch.setattr(plaid_router, "_require_money_writer", lambda biz, user: {"id": biz})
    yield
    cos._TURN_USER_ID.reset(token)


class FakeDB:
    def __init__(self, rows, accounts=None, sent=(), undo_log=()):
        self.rows = {r["transaction_id"]: dict(r) for r in rows}
        self.accounts = accounts or [{"account_id": "a1", "name": "Checking", "mask": "1111",
                                      "type": "depository", "is_trust_account": False}]
        self.sent = list(sent)
        self.undo_log = list(undo_log)
        self.patches = []

    def get(self, path, **kw):
        if path.startswith("/plaid_accounts"):
            return self.accounts
        if path.startswith("/outbound_transfers"):
            return self.sent
        if path.startswith("/chief_undo_log"):
            return self.undo_log
        if path.startswith("/plaid_transactions"):
            if "offset=0" not in path:
                return []
            want_in = "amount=lt.0" in path
            return [dict(r) for r in self.rows.values()
                    if r["reconciliation_status"] == "unmatched" and (r["amount"] < 0) == want_in]
        raise AssertionError(path)

    def patch(self, path, body):
        self.patches.append((path, body))
        if path.startswith("/chief_undo_log"):
            return [{}]
        tid = path.split("transaction_id=eq.", 1)[1].split("&", 1)[0]
        row = self.rows[tid]
        for clause in path.split("&")[2:]:
            k, cond = clause.split("=", 1)
            want = None if cond == "is.null" else cond.split("eq.", 1)[1]
            if row.get(k) != want:
                return []
        row.update({k: v for k, v in body.items() if k != "updated_at"})
        return [row]


@pytest.fixture
def db(monkeypatch):
    holder = {}

    def install(fake):
        monkeypatch.setattr(cr.sb_clients, "sb_get_as_service", fake.get)
        monkeypatch.setattr(cr.sb_clients, "sb_patch_as_service", fake.patch)
        import plaid_reconciliation as pr
        monkeypatch.setattr(pr, "stripe_account_for_business", lambda biz: None)
        import bank_money
        monkeypatch.setattr(bank_money, "supported", lambda: True)
        holder["db"] = fake
        return fake
    return install


def test_reconcile_writes_records_and_lists_every_change(db, owner):
    fake = db(FakeDB([_tx("d1", -40.0, "PAYPAL TRANSFER", primary="TRANSFER_IN"),
                      _tx("d2", -60.0, "CHECK DEPOSIT")]))
    out = cr.reconcile("biz-1", {})
    assert out["type"] == "reconcile_books" and out["display"] == "table"
    assert out["view"] == "reconciled" and out["columns"] and out["rows"]
    assert out["summary"]["count"] == 2 and len(out["changes"]) == 2
    assert out["batch_id"] and len(out["batch_id"]) == 32
    assert fake.rows["d1"]["reconciliation_status"] == "ignored"
    assert all("reconciliation_status=eq.unmatched" in p for p, _ in fake.patches)
    assert "2 deposits marked 'nothing to match'" in out["result"]
    assert "can be undone as one batch" in out["result"]
    assert "1 of the deposits" in out["note_for_chief"], "the PayPal transfer isn't income: ask"


def test_the_answer_check_sees_a_write(db, owner):
    """Live, 2026-10-30: typed show_view, the result counted as a read, and
    "I reconciled 49 bank rows" was withheld as a claim with no write receipt."""
    import chief_truth as truth
    db(FakeDB([_tx("d1", -40.0, "CHECK DEPOSIT")]))
    out = cr.reconcile("biz-1", {})
    assert truth.wrote_anything(truth.evidence_for_review({}, {}, [out]))


def test_a_row_changed_meanwhile_is_left_alone(db, owner, monkeypatch):
    fake = db(FakeDB([_tx("d1", -40.0, "CHECK DEPOSIT")]))
    real_patch = fake.patch

    def someone_else_first(path, body):
        fake.rows["d1"]["reconciliation_status"] = "manual_matched"
        return real_patch(path, body)
    monkeypatch.setattr(cr.sb_clients, "sb_patch_as_service", someone_else_first)
    out = cr.reconcile("biz-1", {})
    assert fake.rows["d1"]["reconciliation_status"] == "manual_matched"
    assert "1 changed while I worked" in out["result"] and "changes" not in out


def test_a_failed_read_changes_nothing(db, owner, monkeypatch):
    db(FakeDB([_tx("d1", -40.0, "CHECK")]))
    monkeypatch.setattr(cr.sb_clients, "sb_get_as_service", lambda *a, **k: None)
    out = cr.reconcile("biz-1", {})
    assert out["failed"] and "nothing was changed" in out["result"]


def test_nothing_clear_changes_nothing_and_says_so(db, owner):
    fake = db(FakeDB([_tx("d1", -40.0, "STRIPE")]))
    out = cr.reconcile("biz-1", {})
    assert fake.patches == [] and "Nothing was clear enough" in out["result"]
    assert "batch_id" not in out


# ─── 3. Undo ─────────────────────────────────────────────────────────

def _reconciled(db):
    fake = db(FakeDB([_tx("d1", -40.0, "CHECK DEPOSIT"), _tx("d2", -60.0, "CASH DEPOSIT")]))
    out = cr.reconcile("biz-1", {})
    fake.undo_log = [{"id": "log-1", "created_at": "2026-10-30T12:00:00Z",
                      "result_json": {"batch_id": out["batch_id"], "changes": out["changes"]}}]
    fake.patches.clear()
    return fake, out


def test_undo_puts_the_batch_back(db, owner):
    fake, out = _reconciled(db)
    res = cr.undo("biz-1", {})
    assert res["result"].startswith("Put back 2 bank rows")
    assert fake.rows["d1"]["reconciliation_status"] == "unmatched"
    assert fake.rows["d1"]["manual_match_reason"] is None
    assert any(p.startswith("/chief_undo_log?id=eq.log-1") and b["status"] == "undone"
               for p, b in fake.patches)


def test_undo_never_overwrites_a_later_decision(db, owner):
    fake, _ = _reconciled(db)
    fake.rows["d2"]["reconciliation_status"] = "manual_matched"   # the owner matched it since
    res = cr.undo("biz-1", {})
    assert fake.rows["d2"]["reconciliation_status"] == "manual_matched"
    assert "1 had been changed since" in res["result"]


def test_a_partial_undo_stays_retryable(db, owner, monkeypatch):
    fake, _ = _reconciled(db)
    real = fake.patch

    def flaky(path, body):
        return None if "d2" in path else real(path, body)
    monkeypatch.setattr(cr.sb_clients, "sb_patch_as_service", flaky)
    res = cr.undo("biz-1", {})
    assert res["failed"] and "Ask again to finish" in res["result"]
    assert not any(p.startswith("/chief_undo_log") for p, _ in fake.patches)


def test_undo_only_restores_the_fields_a_batch_may_touch(db, owner):
    fake, _ = _reconciled(db)
    fake.undo_log[0]["result_json"]["changes"][0]["before"]["amount"] = 999999
    cr.undo("biz-1", {})
    assert fake.rows["d1"]["amount"] == -40.0


def test_undo_with_nothing_recorded_says_where_to_go(db, owner):
    db(FakeDB([]))
    res = cr.undo("biz-1", {})
    assert res["failed"] and "Reconciliation screen" in res["result"]


def test_a_bad_batch_id_is_refused():
    assert cr.undo("biz-1", {"batch_id": "x&status=eq.undoable"})["failed"]


# ─── 4. Who may ──────────────────────────────────────────────────────

def test_a_seat_that_isnt_the_owner_is_refused_before_any_read(monkeypatch):
    monkeypatch.setenv("CHIEF_BANK_SEARCH", "on")
    import plaid_router

    def refuse(biz, user):
        raise HTTPException(403, "not authorized")
    monkeypatch.setattr(plaid_router, "_require_owner", refuse)
    monkeypatch.setattr(plaid_router, "_require_money_writer", refuse)
    monkeypatch.setattr(cr.sb_clients, "sb_get_as_service",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("read before the gate")))
    token = cos._TURN_USER_ID.set("seat-3")
    try:
        out = cr.reconcile("biz-1", {})
    finally:
        cos._TURN_USER_ID.reset(token)
    assert out["failed"] and "Only the owner" in out["result"]


def test_nobody_talking_reconciles_nothing(monkeypatch):
    monkeypatch.setenv("CHIEF_BANK_SEARCH", "on")
    assert cr.reconcile("biz-1", {})["failed"]


def test_switched_off_changes_nothing(monkeypatch):
    monkeypatch.setenv("CHIEF_BANK_SEARCH", "off")
    out = cr.reconcile("biz-1", {})
    assert out["failed"] and "Reconciliation" in out["result"]


# ─── 5. Wiring ───────────────────────────────────────────────────────

def test_registry_bulk_on_request_only_and_undo_is_one_operation():
    assert action_registry.is_bulk("reconcile_books")
    assert action_registry.reversibility("reconcile_books") == "A"
    assert not action_registry.is_bulk("undo_reconcile_books")
    assert action_registry.reversibility("undo_reconcile_books") == "A"


def test_bulk_never_runs_unprompted(monkeypatch):
    import policy_engine
    monkeypatch.setattr(policy_engine, "_biz", lambda business_id, biz_row=None: biz_row or {})
    v = policy_engine.evaluate("biz-1", verb="reconcile_books", surface="scheduler",
                               prompted=False, biz_row={"id": "biz-1", "settings": {}})
    assert not v.allowed


def test_the_undo_log_can_reach_it():
    assert action_inverse.can_undo("reconcile_books")
    inv = action_inverse.build_inverse("reconcile_books", {}, {"batch_id": "a" * 32, "changes": [{}]})
    assert inv == {"type": "undo_reconcile_books", "batch_id": "a" * 32}
    assert action_inverse.build_inverse("reconcile_books", {}, {"result": "Nothing"}) is None


def test_handlers_and_lane():
    import chief_areas
    assert cos.ACTION_HANDLERS["reconcile_books"] is cr.handle_reconcile_books
    assert cos.ACTION_HANDLERS["undo_reconcile_books"] is cr.handle_undo_reconcile_books
    assert chief_areas.VERBS["reconcile_books"] == chief_areas.MONEY
    assert chief_areas.VERBS["undo_reconcile_books"] == chief_areas.MONEY
