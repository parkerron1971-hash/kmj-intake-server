"""
reports_router.py — Phase H.3a endpoints.

Owner-gated (require_user + explicit business_id ownership), thin HTTP layer
over reports_engine. Export is a direct attachment download (no server-side
storage), CSV always + PDF via reportlab (F.2 v1.6 pattern).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

import sb_clients
from auth_supabase import AuthedUser, require_user
import reports_engine
import gl_reports

logger = logging.getLogger("reports_router")

router = APIRouter(prefix="/reports", tags=["reports"])


def _gl_or_fallback(biz: str, gl_fn, h3a_fn) -> Dict[str, Any]:
    """Phase I.4 — the GL is authoritative once a business has active journal
    entries; businesses without a GL (or on GL read failure) fall back to the
    source-table engine. The response carries which source produced it."""
    if gl_reports.gl_active(biz):
        try:
            data = gl_fn()
            data["source"] = "gl"
            return data
        except Exception as e:
            logger.warning(f"[reports] GL engine failed, falling back: {e}")
    data = h3a_fn()
    data["source"] = "source_tables"
    return data


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _period_label(report: str, data: Dict[str, Any]) -> str:
    if data.get("as_of"):
        return f"As of {data['as_of']}"
    rng = data.get("range") or {}
    if rng.get("from") and rng.get("to"):
        return f"Period: {rng['from']} – {rng['to']}"
    return ""


def _generated_by(biz_row: Dict[str, Any], user: AuthedUser) -> str:
    settings = biz_row.get("settings") or {}
    return (settings.get("practitioner_name") or getattr(user, "email", None) or "")


@router.get("/pl")
def pl(biz: str, period: str = "this_month", comparison: Optional[str] = None,
       from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return _gl_or_fallback(
        biz,
        lambda: gl_reports.gl_profit_and_loss(biz, period, comparison, from_, to),
        lambda: reports_engine.profit_and_loss(biz, period, comparison, from_, to))


@router.get("/ar-aging")
def ar_aging(biz: str, as_of: Optional[str] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    # Aging is a SUBLEDGER report (needs per-invoice due dates); the GL
    # control account validates the total (I.4).
    data = reports_engine.ar_aging(biz, as_of)
    data["source"] = "source_tables"
    try:
        if gl_reports.gl_active(biz):
            ctl = gl_reports.gl_control(biz)
            data["gl_control_balance"] = ctl["ar"]
            data["matches_gl"] = abs(ctl["ar"] - float(data.get("total_outstanding") or 0)) < 0.01
    except Exception as e:
        logger.warning(f"[reports] AR control check failed: {e}")
    return data


@router.get("/ap-aging")
def ap_aging(biz: str, as_of: Optional[str] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    data = reports_engine.ap_aging(biz, as_of)
    data["source"] = "source_tables"
    try:
        if gl_reports.gl_active(biz):
            ctl = gl_reports.gl_control(biz)
            data["gl_control_balance"] = ctl["ap"]
            data["matches_gl"] = abs(ctl["ap"] - float(data.get("total_outstanding") or 0)) < 0.01
    except Exception as e:
        logger.warning(f"[reports] AP control check failed: {e}")
    return data


@router.get("/cash-flow")
def cash_flow(biz: str, period: str = "this_month",
              from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return _gl_or_fallback(
        biz,
        lambda: gl_reports.gl_cash_flow(biz, period, from_, to),
        lambda: reports_engine.cash_flow(biz, period, from_, to))


@router.get("/balance-sheet")
def balance_sheet(biz: str, as_of: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return _gl_or_fallback(
        biz,
        lambda: gl_reports.gl_balance_sheet(biz, as_of),
        lambda: reports_engine.balance_sheet(biz, as_of))


# ─── Phase I.4 — GL-native reports ───────────────────────────────────

@router.get("/trial-balance")
def trial_balance(biz: str, as_of: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    if not gl_reports.gl_active(biz):
        return {"ok": True, "report": "trial_balance", "accounts": [],
                "totals": {"debits": 0, "credits": 0, "difference": 0, "balanced": True},
                "as_of": as_of, "note": "No General Ledger yet — run Backfill in Admin."}
    return gl_reports.trial_balance_report(biz, as_of)


@router.get("/general-ledger")
def general_ledger(biz: str, account: Optional[str] = None,
                   period: Optional[str] = None,
                   from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    if period and not (from_ or to):
        s, e = reports_engine.period_bounds(period)
        from_, to = s.isoformat(), e.isoformat()
    if not gl_reports.gl_active(biz):
        return {"ok": True, "report": "general_ledger", "accounts": [],
                "range": {"from": from_, "to": to},
                "note": "No General Ledger yet — run Backfill in Admin."}
    return gl_reports.general_ledger_report(biz, account, from_, to)


# ─── Phase F.1 — 1099 Summary (Tier 1 completion) ────────────────────

def _summary_1099(biz: str, year: int) -> Dict[str, Any]:
    """Calendar-year contractor payment totals from PAID 1099-eligible bills
    (the single source of truth — Stripe-transfer payments auto-create these;
    manual 1099 bills count too). $600 = the IRS 1099-NEC threshold."""
    start, end = f"{year}-01-01", f"{year}-12-31"
    bills = sb_clients.sb_get_as_service(
        f"/bills?business_id=eq.{biz}&status=eq.paid&is_1099_eligible=eq.true"
        f"&paid_at=gte.{start}&paid_at=lte.{end}T23:59:59"
        f"&select=vendor_name,paid_amount,amount,contractor_id&limit=10000") or []
    contractors = sb_clients.sb_get_as_service(
        f"/contractors?business_id=eq.{biz}"
        f"&select=id,name,email,onboarding_status,stripe_account_id&limit=500") or []
    cmap = {c["id"]: c for c in contractors}

    agg: Dict[str, Dict[str, Any]] = {}
    for b in bills:
        cid = b.get("contractor_id")
        key = cid or f"vendor:{(b.get('vendor_name') or '—').strip().lower()}"
        amt = float(b.get("paid_amount") if b.get("paid_amount") is not None else b.get("amount") or 0)
        e = agg.setdefault(key, {
            "contractor_id": cid, "name": (cmap.get(cid) or {}).get("name") or b.get("vendor_name") or "—",
            "total_paid": 0.0, "payments": 0,
            "stripe_managed": bool((cmap.get(cid) or {}).get("stripe_account_id")),
            "onboarding_status": (cmap.get(cid) or {}).get("onboarding_status"),
        })
        e["total_paid"] += amt
        e["payments"] += 1
    rows = sorted(
        [{**e, "total_paid": round(e["total_paid"], 2),
          "reaches_threshold": e["total_paid"] >= 600.0} for e in agg.values()],
        key=lambda x: -x["total_paid"])
    return {
        "ok": True, "report": "summary_1099", "year": year, "rows": rows,
        "total_paid": round(sum(r["total_paid"] for r in rows), 2),
        "threshold_count": sum(1 for r in rows if r["reaches_threshold"]),
        "note": ("Stripe-managed contractors (Express) get their W-9 + 1099-NEC handled by "
                 "Stripe Tax Reporting. Rows without Stripe management need a manual 1099 "
                 "if they reach the $600 threshold — confirm with your accountant."),
    }


@router.get("/1099-summary")
def summary_1099(biz: str, year: Optional[int] = None,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    from datetime import datetime as _dt, timezone as _tz
    y = year or _dt.now(_tz.utc).year
    return _summary_1099(biz, y)


# ─── Phase I.6 — accountant exports ──────────────────────────────────

def _package_year(year: Optional[int]) -> int:
    from datetime import datetime as _dt, timezone as _tz
    return year or _dt.now(_tz.utc).year


def _accountant_email(biz: str, biz_row: Dict[str, Any]) -> Optional[str]:
    """Active accountant collaborator first; Financial Settings fallback."""
    rows = sb_clients.sb_get_as_service(
        f"/business_collaborators?business_id=eq.{biz}&role=eq.accountant"
        f"&status=eq.active&select=invited_email&limit=1") or []
    if rows and rows[0].get("invited_email"):
        return rows[0]["invited_email"]
    fin = ((biz_row.get("settings") or {}).get("financial") or {})
    return (fin.get("accountant_email") or "").strip() or None


@router.get("/accountant/iif")
def accountant_iif(biz: str, year: Optional[int] = None,
                   user: AuthedUser = Depends(require_user)) -> Response:
    """QuickBooks-importable IIF of the General Ledger."""
    _owner(biz, user)
    import accountant_export
    if not gl_reports.gl_active(biz):
        raise HTTPException(409, "No General Ledger yet — run Backfill in Admin first.")
    y = _package_year(year)
    iif = accountant_export.build_iif(biz, y)
    return Response(content=iif, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="ledger_{y}.iif"'})


@router.get("/accountant/package")
def accountant_package(biz: str, year: Optional[int] = None,
                       user: AuthedUser = Depends(require_user)) -> Response:
    """Year-end ZIP: branded PDFs + CSVs + IIF + cover note."""
    biz_row = _owner(biz, user)
    import accountant_export
    y = _package_year(year)
    blob, _ = accountant_export.build_package_zip(
        biz, biz_row.get("name") or "Business", biz_row.get("settings"), y,
        generated_by=_generated_by(biz_row, user))
    return Response(content=blob, media_type="application/zip",
                    headers={"Content-Disposition":
                             f'attachment; filename="{y}_financial_package.zip"'})


@router.post("/accountant/send")
async def accountant_send(biz: str, year: Optional[int] = None,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Email the year-end package to the accountant (active collaborator, or
    Financial Settings accountant_email). Returns the draft + send result."""
    biz_row = _owner(biz, user)
    import accountant_export
    import base64
    y = _package_year(year)
    to_email = _accountant_email(biz, biz_row)
    biz_name = biz_row.get("name") or "Business"
    blob, reports = accountant_export.build_package_zip(
        biz, biz_name, biz_row.get("settings"), y,
        generated_by=_generated_by(biz_row, user))
    subject, body = accountant_export.summary_email(biz_name, y, reports)
    if not to_email:
        return {"ok": True, "email_sent": False, "recipient": None,
                "subject": subject, "body": body,
                "note": "No accountant on file — invite one in Bookkeeping → Admin → "
                        "Collaborators, or set accountant_email in Financial Settings. "
                        "Download the package and send it yourself meanwhile."}
    email_sent = False
    try:
        from email_sender import send_via_resend
        await send_via_resend(
            to_email=to_email, to_name=None,
            from_email="reports@solutionist.studio", from_name=biz_name,
            reply_to=None, subject=subject, body=body,
            attachments=[{"filename": f"{y}_financial_package.zip",
                          "content": base64.b64encode(blob).decode("ascii"),
                          "content_type": "application/zip"}])
        email_sent = True
    except Exception as e:
        logger.warning(f"[i6] accountant package email failed: {e}")
    return {"ok": True, "email_sent": email_sent, "recipient": to_email,
            "subject": subject, "body": body}


@router.get("/journal")
def journal(biz: str, limit: int = 50, offset: int = 0,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    if not gl_reports.gl_active(biz):
        return {"ok": True, "report": "journal", "entries": [], "has_more": False,
                "note": "No General Ledger yet — run Backfill in Admin."}
    return gl_reports.journal_report(biz, limit, offset)


_REPORT_TITLES = {
    "pl": "Profit & Loss", "ar_aging": "AR Aging", "ap_aging": "AP Aging",
    "cash_flow": "Cash Flow (Operating)", "balance_sheet": "Balance Sheet",
    "trial_balance": "Trial Balance", "general_ledger": "General Ledger",
    "summary_1099": "1099 Summary",
}


@router.get("/export")
def export(biz: str, report: str, format: str = "csv",
           period: str = "this_month", as_of: Optional[str] = None,
           comparison: Optional[str] = None,
           from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
           user: AuthedUser = Depends(require_user)) -> Response:
    biz_row = _owner(biz, user)
    if report not in _REPORT_TITLES:
        raise HTTPException(400, "unknown report")
    try:
        # Phase I.4 — exports use the same authoritative source as the screen.
        if report == "summary_1099":
            from datetime import datetime as _dt, timezone as _tz
            y = int((as_of or "")[:4]) if (as_of or "")[:4].isdigit() else _dt.now(_tz.utc).year
            data = _summary_1099(biz, y)
        elif report == "trial_balance":
            data = gl_reports.trial_balance_report(biz, as_of) if gl_reports.gl_active(biz) \
                else {"ok": True, "report": "trial_balance", "as_of": as_of, "accounts": [],
                      "totals": {"debits": 0, "credits": 0, "difference": 0, "balanced": True}}
        elif report == "general_ledger":
            data = gl_reports.general_ledger_report(biz, None, from_, to) \
                if gl_reports.gl_active(biz) else {"ok": True, "report": "general_ledger",
                                                   "accounts": [], "range": {"from": from_, "to": to}}
        elif report == "pl":
            data = _gl_or_fallback(
                biz, lambda: gl_reports.gl_profit_and_loss(biz, period, comparison, from_, to),
                lambda: reports_engine.profit_and_loss(biz, period, comparison, from_, to))
        elif report == "cash_flow":
            data = _gl_or_fallback(
                biz, lambda: gl_reports.gl_cash_flow(biz, period, from_, to),
                lambda: reports_engine.cash_flow(biz, period, from_, to))
        elif report == "balance_sheet":
            data = _gl_or_fallback(
                biz, lambda: gl_reports.gl_balance_sheet(biz, as_of),
                lambda: reports_engine.balance_sheet(biz, as_of))
        else:
            data = reports_engine.run_report(
                biz, report, period=period, as_of=as_of, comparison=comparison,
                custom_from=from_, custom_to=to)
    except ValueError as e:
        raise HTTPException(400, str(e))

    biz_name = biz_row.get("name") or "Business"

    if format == "pdf":
        import pdf_reports
        period_label = _period_label(report, data)
        # Phase I.3 — mark the header when the report covers a CLOSED period.
        try:
            import gl_engine
            day = data.get("as_of") or (data.get("range") or {}).get("to")
            if day:
                per = gl_engine.period_covering(biz, day, "month")
                if per and per.get("status") == "closed":
                    period_label = f"{period_label}  (CLOSED)"
        except Exception:
            pass
        meta = pdf_reports.build_meta(
            business_name=biz_name, settings=biz_row.get("settings"),
            report_title=_REPORT_TITLES[report], period_label=period_label,
            basis_label="Cash Basis", currency="USD",
            generated_by=_generated_by(biz_row, user))
        try:
            pdf = pdf_reports.render(report, data, meta)
        except ImportError:
            raise HTTPException(503, "PDF export unavailable (reportlab missing). Use format=csv.")
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{report}.pdf"'})

    rows = _csv_rows(report, data)

    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{report}.csv"'})


def _csv_rows(report: str, data: Dict[str, Any]) -> list:
    """Flatten a report into [header, *rows] for CSV + PDF table reuse."""
    rows = []
    if report == "pl":
        cur = data.get("current") or {}
        rev = cur.get("revenue") or {}
        rows.append(["Section", "Line", "Amount"])
        rows.append(["Revenue", "Invoiced", rev.get("invoiced", 0)])
        rows.append(["Revenue", "Refunds", -rev.get("refunds", 0)])
        rows.append(["Revenue", "Other (non-Stripe) income", rev.get("plaid_other_income", 0)])
        rows.append(["Revenue", "Gross Revenue", rev.get("gross_revenue", 0)])
        for b in (cur.get("expenses") or {}).get("by_bucket", []):
            rows.append(["Expense", b["label"], b["total"]])
            for ln in b.get("lines", []):
                rows.append(["Expense", f"  {b['label']} · {ln['subcategory']}", ln["amount"]])
        rows.append(["Expense", "Total Expenses", (cur.get("expenses") or {}).get("total", 0)])
        rows.append(["Net", "Net Income", cur.get("net_income", 0)])
    elif report == "ar_aging":
        rows.append(["Invoice", "Contact", "Total", "Due", "Bucket", "Days Overdue"])
        for i in data.get("invoices", []):
            rows.append([i.get("invoice_number"), i.get("contact"), i.get("total"),
                         i.get("due_date"), i.get("bucket"), i.get("days_overdue")])
        rows.append(["", "TOTAL OUTSTANDING", data.get("total_outstanding", 0), "", "", ""])
        rows.append(["", "AT RISK (60+)", data.get("at_risk", 0), "", "", ""])
    elif report == "ap_aging":
        rows.append(["Vendor", "Amount", "Due", "Bucket", "Days Overdue"])
        for b in data.get("bills", []):
            rows.append([b.get("vendor"), b.get("amount"), b.get("due_date"),
                         b.get("bucket"), b.get("days_overdue")])
        rows.append(["TOTAL OUTSTANDING", data.get("total_outstanding", 0), "", "", ""])
        rows.append(["AT RISK (60+)", data.get("at_risk", 0), "", "", ""])
    elif report == "cash_flow":
        op = data.get("operating") or {}
        rows.append(["Operating Activity", "Amount"])
        rows.append(["Cash from customers", op.get("cash_from_customers", 0)])
        rows.append(["Cash to suppliers", -op.get("cash_to_suppliers", 0)])
        rows.append(["Net cash from operations", op.get("net_cash_from_operations", 0)])
    elif report == "balance_sheet":
        a, li, eq = data.get("assets") or {}, data.get("liabilities") or {}, data.get("equity") or {}
        rows.append(["Section", "Line", "Amount"])
        rows.append(["Assets", "Cash", a.get("cash", 0)])
        rows.append(["Assets", "Accounts Receivable", a.get("accounts_receivable", 0)])
        if a.get("stripe_clearing"):
            rows.append(["Assets", "Stripe Clearing (in transit, informational)", a.get("stripe_clearing", 0)])
        rows.append(["Assets", "Total Assets", a.get("total", 0)])
        rows.append(["Liabilities", "Accounts Payable", li.get("accounts_payable", 0)])
        rows.append(["Liabilities", "Total Liabilities", li.get("total", 0)])
        rows.append(["Equity", "Retained Earnings", eq.get("retained_earnings", 0)])
    elif report == "trial_balance":
        rows.append(["Code", "Account", "Type", "Debits", "Credits", "Balance"])
        for a in data.get("accounts", []):
            rows.append([a.get("code"), a.get("name"), a.get("type"),
                         a.get("debits"), a.get("credits"), a.get("balance")])
        t = data.get("totals") or {}
        rows.append(["", "TOTALS", "", t.get("debits", 0), t.get("credits", 0), t.get("difference", 0)])
    elif report == "summary_1099":
        rows.append(["Contractor / Vendor", "Payments", "Total Paid", "Reaches $600", "Stripe-managed 1099"])
        for r in data.get("rows", []):
            rows.append([r.get("name"), r.get("payments"), r.get("total_paid"),
                         "yes" if r.get("reaches_threshold") else "no",
                         "yes" if r.get("stripe_managed") else "no"])
        rows.append(["TOTAL", "", data.get("total_paid", 0), "", ""])
    elif report == "general_ledger":
        rows.append(["Account", "Date", "Source", "Memo", "Debit", "Credit", "Running Balance"])
        for acct in data.get("accounts", []):
            rows.append([f"{acct.get('code')} {acct.get('name')}", "", "OPENING", "", "", "",
                         acct.get("opening_balance", 0)])
            for e in acct.get("entries", []):
                rows.append(["", e.get("date"), e.get("source_type"), e.get("memo"),
                             e.get("debit"), e.get("credit"), e.get("running_balance")])
            rows.append(["", "", "CLOSING", "", "", "", acct.get("closing_balance", 0)])
    return rows


def _render_pdf(biz_name: str, title: str, data: Dict[str, Any], rows: list) -> bytes:
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title=title)
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Paragraph(biz_name, styles["Heading2"])]
    rng = data.get("range") or {}
    when = data.get("as_of") or (f"{rng.get('from')} → {rng.get('to')}" if rng else "")
    if when:
        story.append(Paragraph(str(when), styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    if rows:
        t = Table(rows, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(t)
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph("_______________________________", styles["Normal"]))
    story.append(Paragraph("Reviewed by / date", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()
