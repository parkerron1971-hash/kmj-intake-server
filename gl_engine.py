"""
gl_engine.py — Phase I.1 — Double-entry General Ledger generator + backfill.

Deterministic, idempotent projection of every money event into balanced
journal entries (GL-1 derived-sync). Accrual-recorded (GL-2): invoices book
Dr AR / Cr Revenue on issue; bills book Dr Expense / Cr AP on entry. A
Stripe-Clearing / Undeposited-Funds account (GL-4) prevents revenue
double-count between an invoice payment and its bank-deposited payout.

Reports read back from the ledger. The cash-basis P&L (default reporting
basis) is reconstructed from ledger lines by source_type + account_type so it
equals the H.3a engine to the cent (proven in test_i1_gl on synthetic data).

Every journal entry balances by construction (Σdebit == Σcredit), so the
trial balance is always $0. A per-business opening-balance entry plugs GL
Cash to the current bank balance (offset to Opening Balance Equity) so the
GL Balance Sheet Cash equals the H.3a snapshot.

Idempotency: journal_entries are unique on (business_id, source_type,
source_id); backfill skips existing. Reversal: drop a business's journal
entries (ledger lines cascade) — source tables are never touched.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, date as _date
from typing import Any, Dict, List, Optional, Tuple

import sb_clients
import plaid_categorization

logger = logging.getLogger("gl_engine")

# ─── Chart of accounts seed ──────────────────────────────────────────
# (code, name, type, normal_balance, profit_first_bucket, is_trust)
COA_SEED: List[Tuple[str, str, str, str, Optional[str], bool]] = [
    ("1000", "Cash - Operating",      "asset",     "debit",  None, False),
    ("1100", "Accounts Receivable",   "asset",     "debit",  None, False),
    ("1150", "Stripe Clearing",       "asset",     "debit",  None, False),
    ("2000", "Accounts Payable",      "liability", "credit", None, False),
    ("2100", "Sales Tax Payable",     "liability", "credit", None, False),
    ("3000", "Opening Balance Equity","equity",    "credit", None, False),
    ("3100", "Owner's Equity",        "equity",    "credit", None, False),
    ("3200", "Owner's Draw",          "equity",    "debit",  None, False),
    ("3900", "Retained Earnings",     "equity",    "credit", None, False),
    ("4000", "Service Revenue",       "income",    "credit", None, False),
    ("4100", "Product Revenue",       "income",    "credit", None, False),
    ("4900", "Other Income",          "income",    "credit", None, False),
    ("5000", "Operating Expenses",    "expense",   "debit",  "operating", False),
    ("5100", "Owner Pay",             "expense",   "debit",  "owner_pay", False),
    ("5200", "Tax Expense",           "expense",   "debit",  "tax",       False),
    ("5300", "Savings Allocation",    "expense",   "debit",  "savings",   False),
    ("5900", "Other Expenses",        "expense",   "debit",  "other",     False),
]
# Lawyer (IOLTA prep, I.7): provision a Trust Account.
COA_LAWYER_EXTRA = [("1200", "Trust Account", "asset", "debit", None, True)]

_BUCKET_TO_EXPENSE = {
    "operating": "5000", "owner_pay": "5100", "tax": "5200",
    "savings": "5300", "other": "5900",
}
_ACCOUNT_TYPE = {c[0]: c[2] for c in (COA_SEED + COA_LAWYER_EXTRA)}
_ACCOUNT_BUCKET = {c[0]: c[4] for c in (COA_SEED + COA_LAWYER_EXTRA)}

_INCOME_CODES = {"4000", "4100", "4900"}
_EXPENSE_CODES = set(_BUCKET_TO_EXPENSE.values())
_INVOICE_ISSUE_STATUSES = ("sent", "viewed", "paid", "overdue")
_NON_STRIPE_PAYMENT_HINTS = ("cash", "check", "bank", "manual", "ach", "venmo", "zelle")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> _date:
    return datetime.now(timezone.utc).date()


def _d(s: Optional[str]) -> Optional[_date]:
    try:
        return _date(*(int(p) for p in (s or "")[:10].split("-")))
    except Exception:
        return None


def _coa_for(business_type: Optional[str]) -> List[Tuple]:
    seed = list(COA_SEED)
    if (business_type or "").lower().strip() == "lawyer":
        seed += COA_LAWYER_EXTRA
    return seed


# ─── Chart of accounts provisioning ──────────────────────────────────

def ensure_chart_of_accounts(business_id: str, business_type: Optional[str]) -> Dict[str, str]:
    """Idempotently seed the COA for a business; return {code: account_id}."""
    existing = sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{business_id}&select=id,code") or []
    have = {r["code"]: r["id"] for r in existing}
    for code, name, typ, normal, bucket, is_trust in _coa_for(business_type):
        if code in have:
            continue
        res = sb_clients.sb_post_as_service("/chart_of_accounts", {
            "business_id": business_id, "code": code, "name": name, "type": typ,
            "normal_balance": normal, "profit_first_bucket": bucket, "is_trust": is_trust,
        })
        row = (res or [None])[0] if isinstance(res, list) else res
        if row:
            have[code] = row["id"]
    return have


# ─── Source fetch ────────────────────────────────────────────────────

def _included_account_ids(biz: str) -> List[str]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=account_id") or []
    return [r["account_id"] for r in rows if r.get("account_id")]


def _fetch_sources(biz: str) -> Dict[str, Any]:
    invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}"
        f"&select=id,total,status,paid_at,sent_at,created_at,due_date,payment_method,"
        f"stripe_payment_url,refund_amount_cents,refunded_at&limit=10000") or []
    expenses = sb_clients.sb_get_as_service(
        f"/business_expenses?business_id=eq.{biz}"
        f"&select=id,amount,category,subcategory,vendor,date&limit=10000") or []
    bills = sb_clients.sb_get_as_service(
        f"/bills?business_id=eq.{biz}"
        f"&select=id,vendor_name,amount,category,status,due_date,created_at,paid_at,paid_amount&limit=10000") or []
    included = _included_account_ids(biz)
    plaid = []
    if included:
        acct = "account_id=in.(" + ",".join(included) + ")"
        plaid = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}&{acct}"
            f"&pending=eq.false&excluded_from_books=eq.false"
            f"&select=transaction_id,amount,date,business_category,business_subcategory,"
            f"plaid_category_primary,plaid_category_detail,reconciled_to_payout_id&limit=20000") or []
    cash_accts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}&type=eq.depository"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=last_balance") or []
    cash_on_hand = round(sum(float(a.get("last_balance") or 0) for a in cash_accts), 2)
    return {"invoices": invoices, "expenses": expenses, "bills": bills,
            "plaid": plaid, "cash_on_hand": cash_on_hand}


# ─── Entry generation (pure given fetched sources) ───────────────────

def _line(code: str, debit: float = 0.0, credit: float = 0.0, memo: str = "") -> Dict[str, Any]:
    return {"code": code, "type": _ACCOUNT_TYPE.get(code), "bucket": _ACCOUNT_BUCKET.get(code),
            "debit": round(debit, 2), "credit": round(credit, 2), "memo": memo}


def _entry(entry_date: Optional[_date], source_type: str, source_id: str,
           description: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"entry_date": (entry_date or _today()).isoformat(),
            "source_type": source_type, "source_id": str(source_id),
            "description": description, "lines": lines}


def _is_non_stripe_payment(inv: Dict[str, Any]) -> bool:
    pm = (inv.get("payment_method") or "").lower()
    if any(h in pm for h in _NON_STRIPE_PAYMENT_HINTS):
        return True
    # No Stripe link + no Stripe-ish payment method → treat as direct cash.
    return not inv.get("stripe_payment_url") and not pm


def generate_entries(sources: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map all source rows → balanced journal-entry specs. Pure."""
    entries: List[Dict[str, Any]] = []
    net_cash = 0.0  # Σ(Dr − Cr) on Cash (1000) across generated entries

    def cash_delta(lines):
        nonlocal net_cash
        for ln in lines:
            if ln["code"] == "1000":
                net_cash += ln["debit"] - ln["credit"]

    # ── Invoices: issue / payment / refund ──
    for inv in sources["invoices"]:
        total = float(inv.get("total") or 0)
        status = (inv.get("status") or "").lower()
        if total <= 0:
            continue
        if status in _INVOICE_ISSUE_STATUSES:
            ed = _d(inv.get("sent_at")) or _d(inv.get("created_at")) or _d(inv.get("due_date"))
            entries.append(_entry(ed, "invoice_issue", inv["id"],
                f"Invoice issued", [_line("1100", debit=total), _line("4000", credit=total)]))
        if status == "paid" and inv.get("paid_at"):
            ed = _d(inv.get("paid_at"))
            cash_code = "1000" if _is_non_stripe_payment(inv) else "1150"
            lines = [_line(cash_code, debit=total), _line("1100", credit=total)]
            entries.append(_entry(ed, "invoice_payment", inv["id"], "Invoice paid", lines))
            cash_delta(lines)
        rc = inv.get("refund_amount_cents")
        if rc and float(rc) > 0:
            ed = _d(inv.get("refunded_at")) or _d(inv.get("paid_at"))
            amt = round(float(rc) / 100.0, 2)
            cash_code = "1000" if _is_non_stripe_payment(inv) else "1150"
            lines = [_line("4000", debit=amt), _line(cash_code, credit=amt)]
            entries.append(_entry(ed, "invoice_refund", inv["id"], "Invoice refunded", lines))
            cash_delta(lines)

    # ── Manual expenses (cash paid) ──
    for e in sources["expenses"]:
        amt = float(e.get("amount") or 0)
        if amt <= 0:
            continue
        code = _BUCKET_TO_EXPENSE.get(e.get("category") or "other", "5900")
        memo = " · ".join([x for x in [e.get("vendor"), e.get("subcategory")] if x]) or ""
        lines = [_line(code, debit=amt, memo=memo), _line("1000", credit=amt)]
        entries.append(_entry(_d(e.get("date")), "expense", e["id"], "Manual expense", lines))
        cash_delta(lines)

    # ── Bills: accrual (Dr Expense / Cr AP) + payment (Dr AP / Cr Cash) ──
    for b in sources["bills"]:
        if (b.get("status") or "").lower() == "cancelled":
            continue
        amt = float(b.get("amount") or 0)
        if amt <= 0:
            continue
        code = _BUCKET_TO_EXPENSE.get(b.get("category") or "operating", "5000")
        ed = _d(b.get("created_at")) or _d(b.get("due_date"))
        entries.append(_entry(ed, "bill_issue", b["id"], f"Bill from {b.get('vendor_name')}",
            [_line(code, debit=amt, memo=b.get("vendor_name") or ""), _line("2000", credit=amt)]))
        if (b.get("status") or "").lower() == "paid":
            pamt = float(b.get("paid_amount") if b.get("paid_amount") is not None else amt)
            lines = [_line("2000", debit=pamt), _line("1000", credit=pamt)]
            entries.append(_entry(_d(b.get("paid_at")), "bill_payment", b["id"], "Bill paid", lines))
            cash_delta(lines)

    # ── Plaid transactions (bank-level cash effects) ──
    for t in sources["plaid"]:
        amt = float(t.get("amount") or 0)
        sid = t.get("transaction_id")
        if amt < 0:  # inflow / deposit
            inflow = -amt
            if t.get("reconciled_to_payout_id"):
                # Stripe payout deposit settles the clearing account.
                lines = [_line("1000", debit=inflow), _line("1150", credit=inflow)]
                entries.append(_entry(_d(t.get("date")), "plaid_transaction", sid, "Payout deposit", lines))
                cash_delta(lines)
            elif plaid_categorization.is_income_category(
                    t.get("plaid_category_primary"), t.get("plaid_category_detail")):
                lines = [_line("1000", debit=inflow), _line("4900", credit=inflow)]
                entries.append(_entry(_d(t.get("date")), "plaid_transaction", sid, "Other income", lines))
                cash_delta(lines)
            # else: transfer-in / uncategorized inflow → absorbed by opening equity.
        elif amt > 0:  # outflow / debit
            if not plaid_categorization.is_income_category(
                    t.get("plaid_category_primary"), t.get("plaid_category_detail")):
                bucket = t.get("business_category") or plaid_categorization.map_plaid_to_bucket(
                    t.get("plaid_category_primary"), t.get("plaid_category_detail"))
                code = _BUCKET_TO_EXPENSE.get(bucket, "5900")
                lines = [_line(code, debit=amt, memo=t.get("business_subcategory") or ""),
                         _line("1000", credit=amt)]
                entries.append(_entry(_d(t.get("date")), "plaid_transaction", sid, "Bank expense", lines))
                cash_delta(lines)
            # else: income-categorized outflow → absorbed by opening equity.

    # ── Opening balance: plug Cash to the current bank snapshot ──
    plug = round(sources["cash_on_hand"] - net_cash, 2)
    if abs(plug) >= 0.005:
        if plug > 0:
            lines = [_line("1000", debit=plug), _line("3000", credit=plug)]
        else:
            lines = [_line("3000", debit=-plug), _line("1000", credit=-plug)]
        entries.append(_entry(_today(), "opening_balance", "opening",
                              "Opening balance (Cash to bank snapshot)", lines))

    return entries


# ─── Compute reports from ledger lines (or generated specs) ──────────

def _lines_from_specs(specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten entry specs → ledger-line dicts (the shape verify() reads from
    the DB), for in-memory computation/testing."""
    out = []
    for s in specs:
        for ln in s["lines"]:
            out.append({"account_code": ln["code"], "account_type": ln["type"],
                        "profit_first_bucket": ln["bucket"], "source_type": s["source_type"],
                        "debit": ln["debit"], "credit": ln["credit"], "entry_date": s["entry_date"]})
    return out


def trial_balance(lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    deb = round(sum(float(l["debit"]) for l in lines), 2)
    cred = round(sum(float(l["credit"]) for l in lines), 2)
    return {"debits": deb, "credits": cred, "difference": round(deb - cred, 2)}


def _bal(lines, code, normal="debit", upto: Optional[_date] = None) -> float:
    s = 0.0
    for l in lines:
        if l["account_code"] != code:
            continue
        if upto and _d(l["entry_date"]) and _d(l["entry_date"]) > upto:
            continue
        s += float(l["debit"]) - float(l["credit"])
    return round(s if normal == "debit" else -s, 2)


def gl_cash(lines, upto=None): return _bal(lines, "1000", "debit", upto)
def gl_ar(lines, upto=None):   return _bal(lines, "1100", "debit", upto)
def gl_ap(lines, upto=None):   return _bal(lines, "2000", "credit", upto)
def gl_clearing(lines, upto=None): return _bal(lines, "1150", "debit", upto)


def gl_pl_cash_basis(lines: List[Dict[str, Any]], start: _date, end: _date) -> Dict[str, Any]:
    """Cash-basis P&L from the ledger, reconstructed to match the H.3a engine:
       revenue = invoice cash receipts (Cr AR on invoice_payment)
                 + Plaid other income (Cr income on plaid_transaction)
                 − refunds (Dr income on invoice_refund)
       expenses = Dr to expense accounts from manual expense + plaid (NOT bills)."""
    revenue = expenses = 0.0
    for l in lines:
        ed = _d(l["entry_date"])
        if not ed or ed < start or ed > end:
            continue
        st, code = l["source_type"], l["account_code"]
        if st == "invoice_payment" and code == "1100":
            revenue += float(l["credit"])                     # AR credit = cash received
        elif st == "plaid_transaction" and code in _INCOME_CODES:
            revenue += float(l["credit"])                     # non-Stripe income
        elif st == "invoice_refund" and code in _INCOME_CODES:
            revenue -= float(l["debit"])                      # refund
        elif st in ("expense", "plaid_transaction") and code in _EXPENSE_CODES:
            expenses += float(l["debit"])                     # cash-paid expense (excludes bills)
    revenue = round(revenue, 2)
    expenses = round(expenses, 2)
    return {"revenue": revenue, "expenses": expenses, "net_income": round(revenue - expenses, 2)}


# ─── Persistence / backfill / reverse ────────────────────────────────

def _existing_entry_keys(biz: str) -> set:
    rows = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}&select=source_type,source_id&limit=50000") or []
    return {(r["source_type"], r["source_id"]) for r in rows}


def backfill(business_id: str, business_type: Optional[str]) -> Dict[str, Any]:
    """Idempotent backfill. Returns counts. Re-running creates nothing new."""
    coa = ensure_chart_of_accounts(business_id, business_type)
    sources = _fetch_sources(business_id)
    specs = generate_entries(sources)
    existing = _existing_entry_keys(business_id)
    created = skipped = lines_created = 0
    for s in specs:
        if (s["source_type"], s["source_id"]) in existing:
            skipped += 1
            continue
        res = sb_clients.sb_post_as_service("/journal_entries", {
            "business_id": business_id, "entry_date": s["entry_date"],
            "description": s["description"], "source_type": s["source_type"],
            "source_id": s["source_id"],
        })
        je = (res or [None])[0] if isinstance(res, list) else res
        if not je:
            continue
        je_id = je["id"]
        for ln in s["lines"]:
            acct_id = coa.get(ln["code"])
            sb_clients.sb_post_as_service("/ledger_entries", {
                "business_id": business_id, "journal_entry_id": je_id,
                "account_id": acct_id, "account_code": ln["code"],
                "account_type": ln["type"], "profit_first_bucket": ln["bucket"],
                "source_type": s["source_type"], "debit": ln["debit"], "credit": ln["credit"],
                "entry_date": s["entry_date"], "memo": ln["memo"],
            }, prefer=None)
            lines_created += 1
        created += 1
    return {"ok": True, "journal_entries_created": created, "skipped_existing": skipped,
            "ledger_lines_created": lines_created, "total_specs": len(specs)}


def reverse_backfill(business_id: str) -> Dict[str, Any]:
    """Drop a business's journal entries (ledger lines cascade). Source tables
    untouched. For the I.1b reversibility check."""
    je = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{business_id}&select=id&limit=50000") or []
    sb_clients.sb_delete_as_service(f"/journal_entries?business_id=eq.{business_id}")
    return {"ok": True, "deleted_journal_entries": len(je)}


def read_ledger(business_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/ledger_entries?business_id=eq.{business_id}"
        f"&select=account_code,account_type,profit_first_bucket,source_type,debit,credit,entry_date"
        f"&limit=100000") or []
