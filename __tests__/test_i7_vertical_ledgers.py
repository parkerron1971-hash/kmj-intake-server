"""Phase I.7 — vertical ledger separation (lawyer IOLTA trust / nonprofit COA).

Trust-account activity books Trust Account (1200) ↔ Client Trust Funds (2200)
— NEVER income, expense, or operating cash — and stays out of the H.3a
operating reports, so GL↔H.3a parity holds with a trust account present.
"""
from __future__ import annotations

import sys
import pathlib
from datetime import date

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import gl_engine as gl  # noqa: E402
import gl_reports  # noqa: E402
import reports_engine  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "law1", "type": "lawyer", "owner_id": "owner"})
    return fb


def _add_account(fb, account_id, *, balance=0.0, trust=False, included=True):
    fb.rows("plaid_accounts").append({
        "account_id": account_id, "business_id": "law1", "item_id": "item1",
        "type": "depository", "included_in_bookkeeping": included,
        "is_trust_account": trust, "deleted_at": None, "last_balance": balance,
    })


def _add_tx(fb, tid, account_id, amount, *, date_="2026-06-01", category=None):
    fb.rows("plaid_transactions").append({
        "transaction_id": tid, "business_id": "law1", "account_id": account_id,
        "amount": amount, "date": date_, "pending": False, "excluded_from_books": False,
        "business_category": category, "business_subcategory": None,
        "plaid_category_primary": None, "plaid_category_detail": None,
        "reconciled_to_payout_id": None,
    })


def _enqueue(fb, sid):
    fb.rows("gl_sync_queue").append({
        "id": f"q{len(fb.rows('gl_sync_queue'))}", "business_id": "law1",
        "source_table": "plaid_transactions", "source_id": sid,
        "op": "update", "processed_at": None, "enqueued_at": "2026-06-09T00:00:00Z"})


# ─── COA provisioning per vertical ───────────────────────────────────

def test_coa_provisioning_per_vertical():
    lawyer = {c[0] for c in gl._coa_for("lawyer")}
    assert {"1200", "2200"} <= lawyer
    nonprofit = {c[0] for c in gl._coa_for("nonprofit")}
    assert {"3300", "4200"} <= nonprofit
    assert not {"1200", "2200"} & nonprofit
    barber = {c[0] for c in gl._coa_for("barber")}
    assert not {"1200", "2200", "3300", "4200"} & barber
    # tolerant spellings
    assert "3300" in {c[0] for c in gl._coa_for("Non-Profit")}


def test_nonprofit_coa_provisions_via_fakesb(fake):
    fb = fake
    fb.rows("businesses").append({"id": "np1", "type": "nonprofit", "owner_id": "owner"})
    coa = gl.ensure_chart_of_accounts("np1", "nonprofit")
    assert "3300" in coa and "4200" in coa and "2200" not in coa


# ─── Trust routing in desired_for_plaid ──────────────────────────────

def test_trust_deposit_and_disbursement_routing():
    trust = {"trust_acct"}
    dep = {"transaction_id": "t1", "account_id": "trust_acct", "amount": -1000, "date": "2026-06-01"}
    specs = gl.desired_for_plaid(dep, trust)
    assert len(specs) == 1
    codes = {(l["code"], l["debit"], l["credit"]) for l in specs[0]["lines"]}
    assert codes == {("1200", 1000.0, 0.0), ("2200", 0.0, 1000.0)}

    out = {"transaction_id": "t2", "account_id": "trust_acct", "amount": 400, "date": "2026-06-02"}
    specs = gl.desired_for_plaid(out, trust)
    codes = {(l["code"], l["debit"], l["credit"]) for l in specs[0]["lines"]}
    assert codes == {("2200", 400.0, 0.0), ("1200", 0.0, 400.0)}

    # Non-trust account: unchanged routing (expense → 5900 + operating cash).
    exp = {"transaction_id": "t3", "account_id": "op_acct", "amount": 50, "date": "2026-06-03"}
    specs = gl.desired_for_plaid(exp, trust)
    assert {l["code"] for l in specs[0]["lines"]} == {"5900", "1000"}
    # And with no trust set at all (backward compat).
    assert {l["code"] for s in gl.desired_for_plaid(exp) for l in s["lines"]} == {"5900", "1000"}


# ─── Full backfill: separation + parity + trust opening plug ─────────

def test_lawyer_backfill_trust_separation_and_parity(fake):
    fb = fake
    _add_account(fb, "op_acct", balance=900.0)
    # Trust bank balance 1600 = 1000 deposit − 400 disbursement + 1000 pre-history.
    _add_account(fb, "trust_acct", balance=1600.0, trust=True)
    _add_tx(fb, "op_in", "op_acct", -1000)                       # transfer in → 3100
    _add_tx(fb, "op_exp", "op_acct", 100, category="operating")  # expense → 5000
    _add_tx(fb, "tr_dep", "trust_acct", -1000)                   # client deposit
    _add_tx(fb, "tr_out", "trust_acct", 400)                     # disbursement

    out = gl.backfill("law1", "lawyer")
    assert out["ok"]
    lines = gl.read_ledger("law1")

    # Trial balance $0 with trust + both opening plugs present.
    assert gl.trial_balance(lines)["difference"] == 0.0
    # Operating cash mirrors the OPERATING bank only (900), never trust.
    assert gl.gl_cash(lines) == 900.0
    # Trust ledger: cash == client-funds liability == bank (1600, incl. plug).
    assert gl_reports._net(lines, "1200", normal="debit") == 1600.0
    assert gl_reports._net(lines, "2200", normal="credit") == 1600.0
    # The pre-history plug (1000) booked as trust_opening_balance vs LIABILITY.
    plug = [l for l in lines if l["source_type"] == "trust_opening_balance"]
    assert {l["account_code"] for l in plug} == {"1200", "2200"}
    assert sum(float(l["debit"]) for l in plug if l["account_code"] == "1200") == 1000.0

    # P&L (cash basis): only the operating expense — trust activity invisible.
    pl = gl.gl_pl_cash_basis(lines, date(2026, 1, 1), date(2026, 12, 31))
    assert pl == {"revenue": 0.0, "expenses": 100.0, "net_income": -100.0}

    # H.3a parity: reports_engine excludes the trust account too.
    assert reports_engine._included_account_ids("law1") == ["op_acct"]
    assert reports_engine._cash_on_hand("law1") == 900.0


def test_backfill_idempotent_with_trust(fake):
    fb = fake
    _add_account(fb, "trust_acct", balance=500.0, trust=True)
    _add_tx(fb, "tr1", "trust_acct", -500)
    gl.backfill("law1", "lawyer")
    n = len(fb.rows("journal_entries"))
    out = gl.backfill("law1", "lawyer")
    assert out["journal_entries_created"] == 0
    assert len(fb.rows("journal_entries")) == n


# ─── Live converge: toggling an account trust re-routes its entries ──

def test_live_toggle_account_to_trust_reroutes(fake):
    fb = fake
    _add_account(fb, "acct1", balance=0.0)
    _add_tx(fb, "tx1", "acct1", 250, category="operating")
    _enqueue(fb, "tx1")
    gl.process_queue("law1")
    lines = gl.read_ledger("law1")
    assert any(l["account_code"] == "5000" for l in lines)       # booked as expense

    # Mark the account a trust account (what PATCH /plaid/accounts does),
    # re-enqueue its transactions, drain.
    fb.rows("plaid_accounts")[0]["is_trust_account"] = True
    _enqueue(fb, "tx1")
    gl.process_queue("law1")
    lines = gl.read_ledger("law1")
    # Expense entry reversed; active entry is now 2200/1200. The trust plug
    # then converges 1200 to the bank's $0 snapshot (Dr 1200 / Cr 2200 250),
    # so both trust accounts net to zero == bank. Books mirror the bank.
    assert gl_reports._net(lines, "1200", normal="debit") == 0.0
    assert gl_reports._net(lines, "2200", normal="credit") == 0.0
    plug = [l for l in lines if l["source_type"] == "trust_opening_balance"
            and l["account_code"] == "1200"]
    assert sum(float(l["debit"]) for l in plug) == 250.0
    eff = gl_reports.effective_lines("law1")
    assert {l["account_code"] for l in eff if l["source_type"] == "plaid_transaction"} <= {"1200", "2200"}
    assert all(l["account_code"] != "5000" for l in eff)
    assert gl.trial_balance(lines)["difference"] == 0.0


def test_trust_opening_reconciles_on_drain(fake):
    fb = fake
    _add_account(fb, "trust_acct", balance=750.0, trust=True)
    _add_tx(fb, "tr1", "trust_acct", -500)
    _enqueue(fb, "tr1")
    gl.process_queue("law1")                                     # drain + reconcile
    lines = gl.read_ledger("law1")
    # 500 from the deposit + 250 plug = bank's 750, liability matches.
    assert gl_reports._net(lines, "1200", normal="debit") == 750.0
    assert gl_reports._net(lines, "2200", normal="credit") == 750.0
    assert gl.trial_balance(lines)["difference"] == 0.0
    # Bank balance moves (deposit settles) → plug converges, no duplicates.
    fb.rows("plaid_accounts")[0]["last_balance"] = 900.0
    _enqueue(fb, "tr1")
    gl.process_queue("law1")
    lines = gl.read_ledger("law1")
    assert gl_reports._net(lines, "1200", normal="debit") == 900.0
    assert gl_reports._net(lines, "2200", normal="credit") == 900.0
    actives = [r for r in fb.rows("journal_entries")
               if r["source_type"] == "trust_opening_balance" and r["status"] == "active"]
    assert len(actives) == 1
