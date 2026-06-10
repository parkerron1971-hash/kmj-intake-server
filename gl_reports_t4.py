"""
gl_reports_t4.py — Phase I.10 — Tier-4 vertical compliance reports.

Trust Reconciliation — the formal IOLTA three-way: GL Trust cash (1200) vs
                       Client Trust Funds liability (2200) vs bank trust
                       balances, plus the full trust activity ledger and
                       PER-CLIENT sub-balances (trust_contact_id tagging on
                       trust transactions; untagged funds called out — a
                       compliant book tags everything).
Donor Report         — gifts by donor (paid invoices) + restricted vs
                       unrestricted split from the GL (4200 Restricted
                       Contributions vs other income). Restricted routing:
                       a nonprofit invoice with category "restricted" books
                       to 4200 (gl_engine I.10 mechanic).
990 Prep             — best-effort packet: contribution totals by account,
                       net-asset reconciliation, functional-expense PREP
                       (Profit-First buckets only — program/management/
                       fundraising allocation is an SME ruling, flagged
                       in-band per the stop condition).
Bank Reconciliation  — formal per-account statement: beginning balance
                       (computed), deposits, withdrawals, ending balance,
                       reconciling items (pending + excluded counts), GL
                       cash comparison.
Audit Trail export   — period_edit_overrides formatted for compliance
                       review (CSV + branded PDF via the export endpoint).
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict, List, Optional

import sb_clients
import gl_engine
import gl_reports
import reports_engine

logger = logging.getLogger("gl_reports_t4")


# ─── Trust Reconciliation (lawyer) ───────────────────────────────────

def trust_reconciliation(biz: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    asof = gl_engine._d(as_of) or gl_engine._today()
    lines = gl_reports.effective_lines(biz)
    trust_cash = gl_reports._net(lines, "1200", normal="debit", upto=asof)
    client_funds = gl_reports._net(lines, "2200", normal="credit", upto=asof)

    taccts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}&is_trust_account=is.true"
        f"&deleted_at=is.null"
        f"&select=account_id,name,mask,last_balance,included_in_bookkeeping") or []
    bank_total = round(sum(float(a.get("last_balance") or 0)
                           for a in taccts if a.get("included_in_bookkeeping")), 2)

    trust_ids = [a["account_id"] for a in taccts if a.get("account_id")]
    activity: List[Dict[str, Any]] = []
    by_client: Dict[str, Dict[str, Any]] = {}
    if trust_ids:
        acct = "account_id=in.(" + ",".join(trust_ids) + ")"
        txs = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}&{acct}"
            f"&pending=eq.false&excluded_from_books=eq.false"
            f"&date=lte.{asof.isoformat()}&order=date.desc"
            f"&select=transaction_id,amount,date,name,merchant_name,trust_contact_id,"
            f"contacts:trust_contact_id(name)&limit=10000") or []
        for t in txs:
            amt = float(t.get("amount") or 0)
            client = ((t.get("contacts") or {}) or {}).get("name")
            activity.append({
                "transaction_id": t.get("transaction_id"), "date": t.get("date"),
                "description": t.get("merchant_name") or t.get("name") or "—",
                "type": "deposit" if amt < 0 else "disbursement",
                "amount": round(abs(amt), 2),
                "client": client,
                "trust_contact_id": t.get("trust_contact_id"),
            })
            key = t.get("trust_contact_id") or "__untagged__"
            c = by_client.setdefault(key, {
                "trust_contact_id": None if key == "__untagged__" else key,
                "client": client or ("(untagged)" if key == "__untagged__" else "—"),
                "deposits": 0.0, "disbursements": 0.0, "balance": 0.0})
            if amt < 0:
                c["deposits"] = round(c["deposits"] + abs(amt), 2)
            else:
                c["disbursements"] = round(c["disbursements"] + amt, 2)
            c["balance"] = round(c["deposits"] - c["disbursements"], 2)

    # Pre-history plug (client funds with no transaction history) is real
    # money on the books that no client tag can explain yet.
    plug = round(sum(float(l["debit"]) - float(l["credit"]) for l in lines
                     if l["account_code"] == "1200"
                     and str(l["source_type"]).startswith("trust_opening_balance")), 2)

    clients = sorted(by_client.values(), key=lambda c: -c["balance"])
    untagged = next((c for c in clients if c["trust_contact_id"] is None), None)
    tagged_total = round(sum(c["balance"] for c in clients if c["trust_contact_id"]), 2)

    return {
        "ok": True, "report": "trust_reconciliation", "as_of": asof.isoformat(),
        "three_way": {
            "gl_trust_cash": trust_cash,
            "client_funds_liability": client_funds,
            "bank_trust_balance": bank_total,
            "ledger_in_balance": abs(round(trust_cash - client_funds, 2)) < 0.01,
            "matches_bank": abs(round(trust_cash - bank_total, 2)) < 0.01,
        },
        "accounts": [{"account_id": a.get("account_id"), "name": a.get("name"),
                      "mask": a.get("mask"), "balance": a.get("last_balance"),
                      "included_in_bookkeeping": a.get("included_in_bookkeeping")}
                     for a in taccts],
        "by_client": clients,
        "tagged_total": tagged_total,
        "untagged_balance": round((untagged or {}).get("balance", 0.0) + plug, 2),
        "opening_plug": plug,
        "activity": activity[:200],
        "note": ("A compliant trust book tags every transaction with its client. "
                 "Untagged funds (including pre-history balances) are listed so "
                 "nothing hides. Per-jurisdiction IOLTA report formats are an "
                 "SME ruling — this is the bookkeeping substance."),
    }


# ─── Donor Report (nonprofit) ────────────────────────────────────────

def donor_report(biz: str, period: str = "this_year",
                 custom_from: Optional[str] = None,
                 custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    end_excl = end.isoformat()
    invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&status=eq.paid"
        f"&paid_at=gte.{start.isoformat()}&paid_at=lte.{end_excl}T23:59:59Z"
        f"&select=id,total,paid_at,category,refund_amount_cents,contact_id,"
        f"contacts(name,email)&limit=10000") or []

    donors: Dict[str, Dict[str, Any]] = {}
    restricted_gifts = 0.0
    total_gifts = 0.0
    for inv in invoices:
        amt = float(inv.get("total") or 0)
        rc = inv.get("refund_amount_cents")
        if rc and float(rc) > 0:
            amt = round(amt - float(rc) / 100.0, 2)
        if amt <= 0:
            continue
        c = (inv.get("contacts") or {}) or {}
        name = c.get("name") or "(no donor on record)"
        is_restricted = (inv.get("category") or "").lower().strip() in gl_engine._RESTRICTED_HINTS
        d = donors.setdefault(name, {"donor": name, "email": c.get("email"),
                                     "gifts": 0, "total": 0.0, "restricted": 0.0})
        d["gifts"] += 1
        d["total"] = round(d["total"] + amt, 2)
        if is_restricted:
            d["restricted"] = round(d["restricted"] + amt, 2)
            restricted_gifts = round(restricted_gifts + amt, 2)
        total_gifts = round(total_gifts + amt, 2)

    # GL view of the same split (4200 vs all income) — ties out when the
    # restricted workflow (invoice category "restricted") is used.
    gl_restricted = gl_unrestricted = 0.0
    if gl_reports.gl_active(biz):
        lines = [l for l in gl_reports.effective_lines(biz)
                 if gl_reports._in_window(l, start, end)
                 and l.get("account_type") == "income"
                 and not str(l.get("source_type") or "").startswith("closing")]
        for l in lines:
            net = float(l["credit"]) - float(l["debit"])
            if l["account_code"] == "4200":
                gl_restricted = round(gl_restricted + net, 2)
            else:
                gl_unrestricted = round(gl_unrestricted + net, 2)

    return {
        "ok": True, "report": "donors", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "total_gifts": total_gifts,
        "restricted_gifts": restricted_gifts,
        "unrestricted_gifts": round(total_gifts - restricted_gifts, 2),
        "gl_split": {"restricted_4200": gl_restricted, "unrestricted": gl_unrestricted},
        "donors": sorted(donors.values(), key=lambda d: -d["total"]),
        "note": ("Mark a gift restricted by setting the invoice category to "
                 "\"restricted\" — it then books to 4200 Restricted "
                 "Contributions automatically. Releases from restriction "
                 "(3300 → unrestricted net assets) are an SME ruling."),
    }


# ─── 990 Prep (nonprofit) ────────────────────────────────────────────

def prep_990(biz: str, year: Optional[int] = None) -> Dict[str, Any]:
    y = year or gl_engine._today().year
    start, end = _date(y, 1, 1), _date(y, 12, 31)
    lines = gl_reports.effective_lines(biz)
    win = [l for l in lines if gl_reports._in_window(l, start, end)
           and not str(l.get("source_type") or "").startswith("closing")]

    income_by_code: Dict[str, float] = {}
    expense_by_bucket: Dict[str, float] = {}
    for l in win:
        if l.get("account_type") == "income":
            net = float(l["credit"]) - float(l["debit"])
            income_by_code[l["account_code"]] = round(
                income_by_code.get(l["account_code"], 0.0) + net, 2)
        elif l.get("account_type") == "expense":
            b = l.get("profit_first_bucket") or "other"
            expense_by_bucket[b] = round(
                expense_by_bucket.get(b, 0.0)
                + float(l["debit"]) - float(l["credit"]), 2)

    names = {c[0]: c[1] for c in (gl_engine.COA_SEED + gl_engine.COA_NONPROFIT_EXTRA)}
    equity_codes = ("3000", "3100", "3200", "3300", "3900")
    net_assets = []
    for code in equity_codes:
        bal = gl_reports._net(lines, code, normal="credit", upto=end)
        if abs(bal) >= 0.005 or code == "3300":
            net_assets.append({"code": code, "name": names.get(code, code), "balance": bal})
    total_income = round(sum(income_by_code.values()), 2)
    total_expense = round(sum(expense_by_bucket.values()), 2)

    return {
        "ok": True, "report": "prep_990", "year": y,
        "contributions": [{"code": c, "name": names.get(c, c), "amount": a}
                          for c, a in sorted(income_by_code.items())],
        "total_income": total_income,
        "functional_expenses": [{"bucket": b, "amount": a}
                                for b, a in sorted(expense_by_bucket.items(),
                                                   key=lambda kv: -kv[1])],
        "total_expenses": total_expense,
        "change_in_net_assets": round(total_income - total_expense, 2),
        "net_assets": net_assets,
        "sme_flags": [
            "Functional expense allocation (program / management & general / "
            "fundraising — 990 Part IX) needs an SME mapping from the "
            "Profit-First buckets; the prep totals above are the inputs.",
            "Restricted-release schedule (3300 → unrestricted) is an SME ruling.",
            "990 line-number mappings are intentionally NOT asserted here — "
            "this packet gives the accountant the substance, not the form.",
        ],
    }


# ─── Formal Bank Reconciliation ──────────────────────────────────────

def bank_reconciliation(biz: str, period: str = "this_month",
                        custom_from: Optional[str] = None,
                        custom_to: Optional[str] = None) -> Dict[str, Any]:
    start, end = reports_engine.period_bounds(period, custom_from, custom_to)
    accts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}&type=eq.depository"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null"
        f"&select=account_id,name,mask,last_balance,is_trust_account") or []

    out_accts: List[Dict[str, Any]] = []
    for a in accts:
        aid = a.get("account_id")
        txs = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}&account_id=eq.{aid}"
            f"&pending=eq.false&date=gte.{start.isoformat()}&date=lte.{end.isoformat()}"
            f"&select=amount,excluded_from_books&limit=20000") or []
        deposits = round(sum(-float(t["amount"]) for t in txs
                             if float(t.get("amount") or 0) < 0
                             and not t.get("excluded_from_books")), 2)
        withdrawals = round(sum(float(t["amount"]) for t in txs
                                if float(t.get("amount") or 0) > 0
                                and not t.get("excluded_from_books")), 2)
        excluded = sum(1 for t in txs if t.get("excluded_from_books"))
        # Activity since period start (incl. after period end) reconciles the
        # CURRENT bank balance back to the period boundaries.
        since = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}&account_id=eq.{aid}"
            f"&pending=eq.false&excluded_from_books=eq.false"
            f"&date=gt.{end.isoformat()}&select=amount&limit=20000") or []
        net_after = round(sum(-float(t["amount"]) for t in since), 2)
        current = float(a.get("last_balance") or 0)
        ending = round(current - net_after, 2)            # balance at period end
        beginning = round(ending - (deposits - withdrawals), 2)
        pend = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}&account_id=eq.{aid}"
            f"&pending=eq.true&select=transaction_id&limit=1000") or []
        out_accts.append({
            "account_id": aid, "name": a.get("name"), "mask": a.get("mask"),
            "is_trust_account": bool(a.get("is_trust_account")),
            "beginning_balance": beginning, "deposits": deposits,
            "withdrawals": withdrawals, "ending_balance": ending,
            "current_balance": current,
            "reconciling_items": {"pending_count": len(pend), "excluded_count": excluded},
        })

    gl_cash = None
    if gl_reports.gl_active(biz):
        lines = gl_reports.effective_lines(biz)
        gl_cash = {"operating_1000": gl_reports._net(lines, "1000", normal="debit"),
                   "trust_1200": gl_reports._net(lines, "1200", normal="debit")}

    op_total = round(sum(x["ending_balance"] for x in out_accts
                         if not x["is_trust_account"]), 2)
    return {
        "ok": True, "report": "bank_reconciliation", "period": period,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "accounts": out_accts,
        "operating_ending_total": op_total,
        "gl_cash": gl_cash,
        "note": ("Beginning/ending balances are computed from the current "
                 "synced balance and settled activity (Plaid does not expose "
                 "historical statement balances). Pending and excluded "
                 "transactions are listed as reconciling items."),
    }


# ─── Audit Trail (period_edit_overrides) ─────────────────────────────

def audit_trail(biz: str, *, limit: int = 500) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/period_edit_overrides?business_id=eq.{biz}"
        f"&order=override_at.desc&limit={int(limit)}"
        f"&select=id,source_type,source_id,override_reason,override_by_role,"
        f"override_at,accounting_period_id") or []
    return {
        "ok": True, "report": "audit_trail",
        "entries": [{
            "at": r.get("override_at"), "source_type": r.get("source_type"),
            "source_id": r.get("source_id"), "reason": r.get("override_reason"),
            "by_role": r.get("override_by_role") or "owner",
        } for r in rows],
        "count": len(rows),
    }
