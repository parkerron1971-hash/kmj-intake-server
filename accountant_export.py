"""
accountant_export.py — Phase I.6 — accountant collaboration exports.

1. QuickBooks IIF export of the General Ledger: !ACCNT definitions + one
   GENERAL JOURNAL transaction per journal entry (TRNS = first line,
   SPL = the rest; debits positive / credits negative; MM/DD/YYYY). Only
   ACTIVE, NON-REVERSAL entries export — the accountant gets the current
   books, not the edit noise (reversed pairs net to zero anyway).

2. Year-end financial package: a ZIP of branded PDFs (P&L, Balance Sheet,
   Cash Flow, Trial Balance, General Ledger, 1099 Summary), CSVs for the
   data-heavy reports, the IIF file, and a plain-text cover note — plus a
   deterministic accountant summary email body (Chief LLM voice lands with
   Phase G v1.5).
"""
from __future__ import annotations

import io
import logging
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import sb_clients
import gl_engine
import gl_reports
import reports_engine

logger = logging.getLogger("accountant_export")

# Our COA code → QuickBooks IIF ACCNTTYPE.
_QB_TYPE = {
    "1000": "BANK", "1100": "AR", "1150": "OCASSET", "1200": "OCASSET",
    "2000": "AP", "2100": "OCLIAB",
    "3000": "EQUITY", "3100": "EQUITY", "3200": "EQUITY", "3900": "EQUITY",
    "4000": "INC", "4100": "INC", "4900": "INC",
    "5000": "EXP", "5100": "EXP", "5200": "EXP", "5300": "EXP", "5900": "EXP",
}
_FALLBACK_TYPE = {"asset": "OCASSET", "liability": "OCLIAB", "equity": "EQUITY",
                  "income": "INC", "expense": "EXP"}


def _iif_date(iso: Optional[str]) -> str:
    """yyyy-mm-dd → MM/DD/YYYY (IIF convention)."""
    try:
        y, m, d = (iso or "").split("-")
        return f"{int(m):02d}/{int(d):02d}/{y}"
    except Exception:
        return ""


def _clean(s: Any) -> str:
    """IIF is tab-delimited — strip tabs/newlines from free text."""
    return str(s or "").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()


def build_iif(biz: str, year: Optional[int] = None) -> str:
    """The business's GL as a QuickBooks-importable IIF file."""
    accounts = sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}&select=code,name,type&limit=500") or []
    name_by_code = {a["code"]: a.get("name") or a["code"] for a in accounts}

    jes = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}&status=eq.active"
        f"&order=entry_date.asc,created_at.asc"
        f"&select=id,entry_date,description,source_type,is_reversal&limit=50000") or []
    # Reversal entries filtered in Python (missing field == not a reversal).
    jes = [j for j in jes if not j.get("is_reversal")]
    if year:
        jes = [j for j in jes if (j.get("entry_date") or "").startswith(str(year))]
    je_ids = [j["id"] for j in jes]
    lines_by_je: Dict[str, List[Dict[str, Any]]] = {}
    # Chunk the in.() filter to keep URLs sane.
    for i in range(0, len(je_ids), 100):
        chunk = je_ids[i:i + 100]
        if not chunk:
            continue
        rows = sb_clients.sb_get_as_service(
            f"/ledger_entries?journal_entry_id=in.({','.join(chunk)})"
            f"&select=journal_entry_id,account_code,debit,credit,memo&limit=10000") or []
        for l in rows:
            lines_by_je.setdefault(l["journal_entry_id"], []).append(l)

    out: List[str] = []
    # Account definitions.
    out.append("!ACCNT\tNAME\tACCNTTYPE")
    for a in sorted(accounts, key=lambda x: x.get("code") or ""):
        qb = _QB_TYPE.get(a["code"]) or _FALLBACK_TYPE.get(a.get("type") or "", "OCASSET")
        out.append(f"ACCNT\t{_clean(a.get('name'))}\t{qb}")
    # Transaction schema.
    out.append("!TRNS\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tMEMO")
    out.append("!SPL\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tMEMO")
    out.append("!ENDTRNS")

    for j in jes:
        lines = lines_by_je.get(j["id"]) or []
        if not lines:
            continue
        date = _iif_date(j.get("entry_date"))
        memo = _clean(j.get("description") or j.get("source_type"))
        for idx, l in enumerate(lines):
            amount = round(float(l.get("debit") or 0) - float(l.get("credit") or 0), 2)
            acct = _clean(name_by_code.get(l.get("account_code"), l.get("account_code")))
            row_kind = "TRNS" if idx == 0 else "SPL"
            line_memo = memo if idx == 0 else _clean(l.get("memo"))
            out.append(f"{row_kind}\tGENERAL JOURNAL\t{date}\t{acct}\t{amount:.2f}\t{line_memo}")
        out.append("ENDTRNS")
    return "\n".join(out) + "\n"


# ─── Year-end package ────────────────────────────────────────────────

def _package_reports(biz: str, year: int) -> Dict[str, Dict[str, Any]]:
    """All report payloads for the package, GL-authoritative where active."""
    y_from, y_to = f"{year}-01-01", f"{year}-12-31"
    use_gl = gl_reports.gl_active(biz)
    if use_gl:
        pl = gl_reports.gl_profit_and_loss(biz, "custom", None, y_from, y_to)
        bs = gl_reports.gl_balance_sheet(biz, y_to)
        cf = gl_reports.gl_cash_flow(biz, "custom", y_from, y_to)
    else:
        pl = reports_engine.profit_and_loss(biz, "custom", None, y_from, y_to)
        bs = reports_engine.balance_sheet(biz, y_to)
        cf = reports_engine.cash_flow(biz, "custom", y_from, y_to)
    out = {"pl": pl, "balance_sheet": bs, "cash_flow": cf,
           "ar_aging": reports_engine.ar_aging(biz, y_to),
           "ap_aging": reports_engine.ap_aging(biz, y_to)}
    if use_gl:
        out["trial_balance"] = gl_reports.trial_balance_report(biz, y_to)
        out["general_ledger"] = gl_reports.general_ledger_report(biz, None, y_from, y_to)
    from reports_router import _summary_1099
    out["summary_1099"] = _summary_1099(biz, year)
    return out


def summary_email(biz_name: str, year: int, reports: Dict[str, Dict[str, Any]]) -> Tuple[str, str]:
    """(subject, body) — a deterministic, accountant-friendly cover email."""
    pl = (reports.get("pl") or {}).get("current") or {}
    rev = (pl.get("revenue") or {}).get("gross_revenue", 0)
    exp = (pl.get("expenses") or {}).get("total", 0)
    net = pl.get("net_income", 0)
    bs = reports.get("balance_sheet") or {}
    cash = (bs.get("assets") or {}).get("cash", 0)
    ar = (bs.get("assets") or {}).get("accounts_receivable", 0)
    ap = (bs.get("liabilities") or {}).get("accounts_payable", 0)
    tb = (reports.get("trial_balance") or {}).get("totals") or {}
    n1099 = (reports.get("summary_1099") or {}).get("threshold_count", 0)
    subject = f"{biz_name} — {year} year-end financial package"
    body = (
        f"Hi,\n\n"
        f"Attached is the {year} year-end financial package for {biz_name}, "
        f"prepared in Solutionist System (cash basis, double-entry).\n\n"
        f"Headlines:\n"
        f"  - Gross revenue: ${rev:,.2f}\n"
        f"  - Total expenses: ${exp:,.2f}\n"
        f"  - Net income: ${net:,.2f}\n"
        f"  - Cash at year end: ${cash:,.2f} · AR ${ar:,.2f} · AP ${ap:,.2f}\n"
        f"  - Trial balance: {'in balance' if tb.get('balanced', True) else 'OUT OF BALANCE — see note'}\n"
        f"  - 1099 contractors at/above $600: {n1099}\n\n"
        f"The ZIP contains the P&L, Balance Sheet, Cash Flow, Trial Balance, "
        f"General Ledger (PDF + CSV), AR/AP aging, the 1099 summary, and a "
        f"QuickBooks-importable IIF of the full ledger.\n\n"
        f"Questions or adjusting entries — just reply and we'll record them.\n\n"
        f"— Sent from Solutionist System on behalf of {biz_name}"
    )
    return subject, body


def build_package_zip(biz: str, biz_name: str, settings: Optional[Dict[str, Any]],
                      year: int, generated_by: str = "") -> Tuple[bytes, Dict[str, Dict[str, Any]]]:
    """Build the year-end ZIP. Returns (zip_bytes, report_payloads)."""
    import pdf_reports
    from reports_router import _csv_rows, _REPORT_TITLES

    reports = _package_reports(biz, year)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for key, data in reports.items():
            title = _REPORT_TITLES.get(key, key)
            label = (f"Period: {year}-01-01 – {year}-12-31"
                     if key in ("pl", "cash_flow", "general_ledger")
                     else f"As of {year}-12-31" if key != "summary_1099" else f"Tax year {year}")
            # PDF (skip gracefully if reportlab is somehow absent).
            try:
                meta = pdf_reports.build_meta(
                    business_name=biz_name, settings=settings, report_title=title,
                    period_label=label, basis_label="Cash Basis", currency="USD",
                    generated_by=generated_by)
                z.writestr(f"{year}_{key}.pdf", pdf_reports.render(key, data, meta))
            except Exception as e:
                logger.warning(f"[i6] PDF for {key} skipped: {e}")
            # CSV for the data-heavy reports.
            if key in ("general_ledger", "trial_balance", "summary_1099", "ar_aging", "ap_aging"):
                import csv as _csv
                sbuf = io.StringIO()
                w = _csv.writer(sbuf)
                for r in _csv_rows(key, data):
                    w.writerow(r)
                z.writestr(f"{year}_{key}.csv", sbuf.getvalue())
        # QuickBooks IIF of the ledger.
        z.writestr(f"{year}_general_ledger.iif", build_iif(biz, year))
        # Cover note.
        subject, body = summary_email(biz_name, year, reports)
        z.writestr("README.txt", subject + "\n" + "=" * len(subject) + "\n\n" + body + "\n")
    return buf.getvalue(), reports
