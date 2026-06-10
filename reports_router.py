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

logger = logging.getLogger("reports_router")

router = APIRouter(prefix="/reports", tags=["reports"])


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
    return reports_engine.profit_and_loss(biz, period, comparison, from_, to)


@router.get("/ar-aging")
def ar_aging(biz: str, as_of: Optional[str] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return reports_engine.ar_aging(biz, as_of)


@router.get("/ap-aging")
def ap_aging(biz: str, as_of: Optional[str] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return reports_engine.ap_aging(biz, as_of)


@router.get("/cash-flow")
def cash_flow(biz: str, period: str = "this_month",
              from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return reports_engine.cash_flow(biz, period, from_, to)


@router.get("/balance-sheet")
def balance_sheet(biz: str, as_of: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    return reports_engine.balance_sheet(biz, as_of)


_REPORT_TITLES = {
    "pl": "Profit & Loss", "ar_aging": "AR Aging", "ap_aging": "AP Aging",
    "cash_flow": "Cash Flow (Operating)", "balance_sheet": "Balance Sheet",
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
        rows.append(["Assets", "Total Assets", a.get("total", 0)])
        rows.append(["Liabilities", "Accounts Payable", li.get("accounts_payable", 0)])
        rows.append(["Liabilities", "Total Liabilities", li.get("total", 0)])
        rows.append(["Equity", "Retained Earnings", eq.get("retained_earnings", 0)])
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
