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


# Per-source desired-entry generators — the SINGLE source of truth for both
# backfill (generate_entries) and live sync (converge). Each returns the
# balanced journal-entry specs a source row should produce right now.

def desired_for_invoice(inv: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    total = float(inv.get("total") or 0)
    status = (inv.get("status") or "").lower()
    if total <= 0:
        return out
    if status in _INVOICE_ISSUE_STATUSES:
        ed = _d(inv.get("sent_at")) or _d(inv.get("created_at")) or _d(inv.get("due_date"))
        out.append(_entry(ed, "invoice_issue", inv["id"], "Invoice issued",
                          [_line("1100", debit=total), _line("4000", credit=total)]))
    if status == "paid" and inv.get("paid_at"):
        cc = "1000" if _is_non_stripe_payment(inv) else "1150"
        out.append(_entry(_d(inv.get("paid_at")), "invoice_payment", inv["id"], "Invoice paid",
                          [_line(cc, debit=total), _line("1100", credit=total)]))
    rc = inv.get("refund_amount_cents")
    if rc and float(rc) > 0:
        amt = round(float(rc) / 100.0, 2)
        cc = "1000" if _is_non_stripe_payment(inv) else "1150"
        out.append(_entry(_d(inv.get("refunded_at")) or _d(inv.get("paid_at")),
                          "invoice_refund", inv["id"], "Invoice refunded",
                          [_line("4000", debit=amt), _line(cc, credit=amt)]))
    return out


def desired_for_expense(e: Dict[str, Any]) -> List[Dict[str, Any]]:
    amt = float(e.get("amount") or 0)
    if amt <= 0:
        return []
    code = _BUCKET_TO_EXPENSE.get(e.get("category") or "other", "5900")
    memo = " · ".join([x for x in [e.get("vendor"), e.get("subcategory")] if x]) or ""
    return [_entry(_d(e.get("date")), "expense", e["id"], "Manual expense",
                   [_line(code, debit=amt, memo=memo), _line("1000", credit=amt)])]


def desired_for_bill(b: Dict[str, Any]) -> List[Dict[str, Any]]:
    # GAAP: a DRAFT bill is not yet a payable (mirrors draft-invoice / AR).
    if (b.get("status") or "").lower() in ("cancelled", "draft"):
        return []
    amt = float(b.get("amount") or 0)
    if amt <= 0:
        return []
    out = []
    code = _BUCKET_TO_EXPENSE.get(b.get("category") or "operating", "5000")
    ed = _d(b.get("created_at")) or _d(b.get("due_date"))
    out.append(_entry(ed, "bill_issue", b["id"], f"Bill from {b.get('vendor_name')}",
               [_line(code, debit=amt, memo=b.get("vendor_name") or ""), _line("2000", credit=amt)]))
    if (b.get("status") or "").lower() == "paid":
        pamt = float(b.get("paid_amount") if b.get("paid_amount") is not None else amt)
        out.append(_entry(_d(b.get("paid_at")), "bill_payment", b["id"], "Bill paid",
                   [_line("2000", debit=pamt), _line("1000", credit=pamt)]))
    return out


def desired_for_plaid(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Pending / excluded-from-books transactions are not in the books — a live
    # toggle of either reverses the entry (matches H.3a scope).
    if t.get("pending") or t.get("excluded_from_books"):
        return []
    amt = float(t.get("amount") or 0)
    sid = t.get("transaction_id")
    if amt < 0:
        inflow = -amt
        if t.get("reconciled_to_payout_id"):
            return [_entry(_d(t.get("date")), "plaid_transaction", sid, "Payout deposit",
                           [_line("1000", debit=inflow), _line("1150", credit=inflow)])]
        if plaid_categorization.is_income_category(
                t.get("plaid_category_primary"), t.get("plaid_category_detail")):
            return [_entry(_d(t.get("date")), "plaid_transaction", sid, "Other income",
                           [_line("1000", debit=inflow), _line("4900", credit=inflow)])]
        return []  # transfer-in / uncategorized → absorbed by opening equity
    if amt > 0 and not plaid_categorization.is_income_category(
            t.get("plaid_category_primary"), t.get("plaid_category_detail")):
        bucket = t.get("business_category") or plaid_categorization.map_plaid_to_bucket(
            t.get("plaid_category_primary"), t.get("plaid_category_detail"))
        code = _BUCKET_TO_EXPENSE.get(bucket, "5900")
        return [_entry(_d(t.get("date")), "plaid_transaction", sid, "Bank expense",
                       [_line(code, debit=amt, memo=t.get("business_subcategory") or ""),
                        _line("1000", credit=amt)])]
    return []


# Source table → its GL source_types (for live reconciliation of one row).
_TABLE_SOURCE_TYPES = {
    "invoices": ("invoice_issue", "invoice_payment", "invoice_refund"),
    "business_expenses": ("expense",),
    "bills": ("bill_issue", "bill_payment"),
    "plaid_transactions": ("plaid_transaction",),
}
_TABLE_DESIRED = {
    "invoices": desired_for_invoice, "business_expenses": desired_for_expense,
    "bills": desired_for_bill, "plaid_transactions": desired_for_plaid,
}


def _cash_net(specs: List[Dict[str, Any]]) -> float:
    n = 0.0
    for s in specs:
        for ln in s["lines"]:
            if ln["code"] == "1000":
                n += ln["debit"] - ln["credit"]
    return round(n, 2)


def _opening_spec(cash_on_hand: float, net_cash: float) -> Optional[Dict[str, Any]]:
    plug = round(cash_on_hand - net_cash, 2)
    if abs(plug) < 0.005:
        return None
    lines = ([_line("1000", debit=plug), _line("3000", credit=plug)] if plug > 0
             else [_line("3000", debit=-plug), _line("1000", credit=-plug)])
    return _entry(_today(), "opening_balance", "opening",
                  "Opening balance (Cash to bank snapshot)", lines)


def generate_entries(sources: Dict[str, Any]) -> List[Dict[str, Any]]:
    """All source rows → balanced journal-entry specs (backfill path). Pure."""
    specs: List[Dict[str, Any]] = []
    for inv in sources["invoices"]:
        specs += desired_for_invoice(inv)
    for e in sources["expenses"]:
        specs += desired_for_expense(e)
    for b in sources["bills"]:
        specs += desired_for_bill(b)
    for t in sources["plaid"]:
        specs += desired_for_plaid(t)
    opening = _opening_spec(sources["cash_on_hand"], _cash_net(specs))
    if opening:
        specs.append(opening)
    return specs


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


# ═══════════════════════════════════════════════════════════════════
# Phase I.2 — live sync (converge-to-desired, append-only)
# ═══════════════════════════════════════════════════════════════════

import asyncio  # noqa: E402
from datetime import timedelta as _timedelta  # noqa: E402

_SOURCE_FETCH = {
    "invoices": ("/invoices?id=eq.{id}&select=id,total,status,paid_at,sent_at,created_at,"
                 "due_date,payment_method,stripe_payment_url,refund_amount_cents,refunded_at&limit=1"),
    "business_expenses": "/business_expenses?id=eq.{id}&select=id,amount,category,subcategory,vendor,date&limit=1",
    "bills": ("/bills?id=eq.{id}&select=id,vendor_name,amount,category,status,due_date,"
              "created_at,paid_at,paid_amount&limit=1"),
    "plaid_transactions": ("/plaid_transactions?transaction_id=eq.{id}&select=transaction_id,amount,date,"
                           "business_category,business_subcategory,plaid_category_primary,"
                           "plaid_category_detail,reconciled_to_payout_id,pending,excluded_from_books,account_id&limit=1"),
}


def _spec_sig(spec: Dict[str, Any]):
    return tuple(sorted((l["code"], round(float(l["debit"]), 2), round(float(l["credit"]), 2))
                        for l in spec["lines"]))


def _persisted_sig(lines: List[Dict[str, Any]]):
    return tuple(sorted((l["account_code"], round(float(l["debit"]), 2), round(float(l["credit"]), 2))
                        for l in lines))


def _je_lines(je_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/ledger_entries?journal_entry_id=eq.{je_id}&select=account_code,debit,credit&limit=500") or []


def _active_jes(biz: str, source_id: str, source_types) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}&source_id=eq.{source_id}"
        f"&status=eq.active&source_type=in.({','.join(source_types)})"
        f"&select=id,source_type&limit=50") or []


def _post_entry(biz: str, spec: Dict[str, Any], coa: Dict[str, str], *,
                is_reversal: bool = False, reverses: Optional[str] = None) -> Optional[str]:
    res = sb_clients.sb_post_as_service("/journal_entries", {
        "business_id": biz, "entry_date": spec["entry_date"], "description": spec["description"],
        "source_type": spec["source_type"], "source_id": spec["source_id"],
        "status": "active", "is_reversal": is_reversal, "reverses_entry_id": reverses,
    })
    je = (res or [None])[0] if isinstance(res, list) else res
    if not je:
        return None
    for ln in spec["lines"]:
        sb_clients.sb_post_as_service("/ledger_entries", {
            "business_id": biz, "journal_entry_id": je["id"], "account_id": coa.get(ln["code"]),
            "account_code": ln["code"], "account_type": ln["type"], "profit_first_bucket": ln["bucket"],
            "source_type": spec["source_type"], "debit": ln["debit"], "credit": ln["credit"],
            "entry_date": spec["entry_date"], "memo": ln["memo"],
        }, prefer=None)
    return je["id"]


def _reverse_je(biz: str, je: Dict[str, Any], coa: Dict[str, str]) -> None:
    """Append-only reversal: mark the entry reversed + post a mirror entry."""
    lines = _je_lines(je["id"])
    rev_lines = [_line(l["account_code"], debit=float(l["credit"]), credit=float(l["debit"]),
                       memo="reversal") for l in lines]
    rev_spec = _entry(_today(), je["source_type"] + "_reversal", je["id"], "Reversal", rev_lines)
    _post_entry(biz, rev_spec, coa, is_reversal=True, reverses=je["id"])
    sb_clients.sb_patch_as_service(f"/journal_entries?id=eq.{je['id']}", {"status": "reversed"})


def process_source_row(biz: str, table: str, source_id: str, coa: Dict[str, str],
                       included_accounts: Optional[set] = None) -> None:
    """Converge the GL for ONE source row to its desired state (idempotent)."""
    types = _TABLE_SOURCE_TYPES.get(table)
    if not types:
        return
    rows = sb_clients.sb_get_as_service(_SOURCE_FETCH[table].format(id=source_id)) or []
    row = rows[0] if rows else None
    desired: List[Dict[str, Any]] = []
    if row is not None:
        if table == "plaid_transactions" and included_accounts is not None \
                and row.get("account_id") not in included_accounts:
            desired = []  # tx on an excluded/removed account → not in books
        else:
            desired = _TABLE_DESIRED[table](row)
    desired_by_type = {s["source_type"]: s for s in desired}

    actives = {je["source_type"]: je for je in _active_jes(biz, source_id, types)}
    for st, je in actives.items():
        spec = desired_by_type.get(st)
        if spec is None:
            _reverse_je(biz, je, coa)                       # event no longer applies
        elif _persisted_sig(_je_lines(je["id"])) != _spec_sig(spec):
            _reverse_je(biz, je, coa)
            _post_entry(biz, spec, coa)                     # changed → reverse + repost
    for st, spec in desired_by_type.items():
        if st not in actives:
            _post_entry(biz, spec, coa)                     # new event


def reconcile_opening_balance(biz: str, coa: Dict[str, str]) -> None:
    """Keep GL Cash == current bank snapshot after any cash-affecting change."""
    lines = read_ledger(biz)
    net_nonopening = round(sum(
        float(l["debit"]) - float(l["credit"]) for l in lines
        if l["account_code"] == "1000" and not str(l["source_type"]).startswith("opening_balance")), 2)
    accts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}&type=eq.depository"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null&select=last_balance") or []
    cash_on_hand = round(sum(float(a.get("last_balance") or 0) for a in accts), 2)
    desired = _opening_spec(cash_on_hand, net_nonopening)

    actives = _active_jes(biz, "opening", ("opening_balance",))
    cur = actives[0] if actives else None
    if desired is None:
        if cur:
            _reverse_je(biz, cur, coa)
        return
    if cur and _persisted_sig(_je_lines(cur["id"])) == _spec_sig(desired):
        return                                              # unchanged
    if cur:
        _reverse_je(biz, cur, coa)
    _post_entry(biz, desired, coa)


def _biz_type(biz: str) -> Optional[str]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{biz}&select=type&limit=1") or []
    return rows[0].get("type") if rows else None


def process_queue(business_id: Optional[str] = None, *, limit: int = 500) -> Dict[str, Any]:
    """Drain unprocessed gl_sync_queue rows → converge each source → mark
    processed. Idempotent. Prunes processed rows older than 7 days."""
    filt = f"&business_id=eq.{business_id}" if business_id else ""
    rows = sb_clients.sb_get_as_service(
        f"/gl_sync_queue?processed_at=is.null{filt}"
        f"&order=enqueued_at.asc&limit={int(limit)}&select=id,business_id,source_table,source_id") or []
    if not rows:
        return {"ok": True, "processed": 0, "businesses": 0}

    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_biz.setdefault(r["business_id"], []).append(r)

    processed = 0
    for biz, biz_rows in by_biz.items():
        coa = ensure_chart_of_accounts(biz, _biz_type(biz))
        included = set(_included_account_ids(biz))
        seen = set()
        for r in biz_rows:
            key = (r["source_table"], r["source_id"])
            if key not in seen:
                seen.add(key)
                try:
                    process_source_row(biz, r["source_table"], r["source_id"], coa, included)
                except Exception as e:
                    logger.warning(f"[gl] process row failed {key}: {e}")
            sb_clients.sb_patch_as_service(
                f"/gl_sync_queue?id=eq.{r['id']}", {"processed_at": _now_iso()})
            processed += 1
        try:
            reconcile_opening_balance(biz, coa)
        except Exception as e:
            logger.warning(f"[gl] opening reconcile failed {biz}: {e}")

    try:
        cutoff = (datetime.now(timezone.utc) - _timedelta(days=7)).isoformat()
        sb_clients.sb_delete_as_service(
            f"/gl_sync_queue?processed_at=not.is.null&processed_at=lt.{cutoff}")
    except Exception as e:
        logger.warning(f"[gl] queue prune failed: {e}")

    return {"ok": True, "processed": processed, "businesses": len(by_biz)}


# ─── Divergence reconciliation ───────────────────────────────────────

def run_divergence_check(biz: str) -> Dict[str, Any]:
    """Compute verify deltas; raise/clear an alarm. Returns the summary."""
    import reports_engine
    lines = read_ledger(biz)
    if not lines:
        return {"all_match": True, "empty": True}
    tb = trial_balance(lines)
    today = reports_engine._today()
    start = _date(2000, 1, 1)
    gl_pl = gl_pl_cash_basis(lines, start, today)
    h_pl = reports_engine.profit_and_loss(biz, "custom", None, start.isoformat(), today.isoformat())["current"]
    deltas = {
        "trial_balance": abs(tb["difference"]),
        "pl_revenue": abs(gl_pl["revenue"] - h_pl["revenue"]["gross_revenue"]),
        "pl_expenses": abs(gl_pl["expenses"] - h_pl["expenses"]["total"]),
        "ar": abs(gl_ar(lines) - reports_engine.ar_aging(biz).get("total_outstanding", 0)),
        "ap": abs(gl_ap(lines) - reports_engine.ap_aging(biz).get("total_outstanding", 0)),
        "cash": abs(gl_cash(lines) - reports_engine.balance_sheet(biz)["assets"]["cash"]),
    }
    all_match = all(v < 0.01 for v in deltas.values())
    summary = {"all_match": all_match, "deltas": {k: round(v, 2) for k, v in deltas.items()}}

    active = sb_clients.sb_get_as_service(
        f"/gl_divergence_alarms?business_id=eq.{biz}&status=eq.active&select=id&limit=1") or []
    if not all_match and not active:
        sb_clients.sb_post_as_service("/gl_divergence_alarms",
            {"business_id": biz, "status": "active", "summary": summary}, prefer=None)
    elif all_match and active:
        sb_clients.sb_patch_as_service(
            f"/gl_divergence_alarms?business_id=eq.{biz}&status=eq.active",
            {"status": "resolved", "resolved_at": _now_iso()})
    return summary


def _backfilled_businesses() -> List[str]:
    rows = sb_clients.sb_get_as_service(
        "/journal_entries?status=eq.active&select=business_id&limit=50000") or []
    return list({r["business_id"] for r in rows if r.get("business_id")})


# ─── Scheduler ticks (driven by the existing AsyncIOScheduler) ───────

async def drain_tick() -> None:
    try:
        await asyncio.to_thread(process_queue)
    except Exception as e:
        logger.warning(f"[gl] drain_tick failed: {e}")


async def divergence_tick() -> None:
    def _run():
        for biz in _backfilled_businesses():
            try:
                run_divergence_check(biz)
            except Exception as e:
                logger.warning(f"[gl] divergence check failed {biz}: {e}")
    try:
        await asyncio.to_thread(_run)
    except Exception as e:
        logger.warning(f"[gl] divergence_tick failed: {e}")
