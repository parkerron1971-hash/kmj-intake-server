"""
reports_router.py — Phase H.3a endpoints.

Owner-gated (require_user + explicit business_id ownership), thin HTTP layer
over reports_engine. Export is a direct attachment download (no server-side
storage), CSV always + PDF via reportlab (F.2 v1.6 pattern).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
import billing_limits
import reports_engine
import gl_reports
import gl_reports_t2
import gl_reports_t3
import gl_reports_t4

logger = logging.getLogger("reports_router")

router = APIRouter(prefix="/reports", tags=["reports"])

# 7/30 tier audit — report → plan feature (billing_limits.require_feature;
# dormant until BILLING_ENFORCE). The map's principle: GL-authoritative
# analytical reports are Professional (reports_full); vertical compliance
# deliverables are Practice. Starter keeps the operational core — P&L,
# agings, cash flow, balance sheet, bank reconciliation, statements —
# so basic CSV/PDF export always remains as the data escape hatch.
_REPORT_FEATURES: Dict[str, str] = {
    "trial_balance": "reports_full", "general_ledger": "reports_full",
    "revenue": "reports_full", "expenses_detail": "reports_full",
    "budget_vs_actual": "reports_full", "profitability": "reports_full",
    "trends": "reports_full",
    "summary_1099": "contractor_payments",
    "trust_reconciliation": "vertical_reports", "donors": "vertical_reports",
    "prep_990": "vertical_reports",
    "audit_trail": "audit_trail",
}


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


def _owner_or_accountant(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """Category D — the year-end deliverables (IIF + package) are exactly
    what the accountant collaborator exists for; allow active accountants
    read access alongside the owner."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) == str(user.id):
        return rows[0]
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(biz, str(user.id)):
        return rows[0]
    raise HTTPException(403, "not authorized")


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _owner_or_reader(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """Rails Arc 5 — the financial READ surface.

    Category D opened exactly two endpoints (IIF + package) to the
    accountant; every other report stayed owner-only, which made the
    accountant collaborator and the Team panel's viewer/member/manager/
    admin seats decorative. This is the shared read gate: owner, active
    accountant collaborator, or any active team seat may READ reports.
    Writes (budgets PUT, sends) and the TIN-decrypting 1099 draft PDF
    stay owner-only via _owner."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) == str(user.id):
        return rows[0]
    from business_collaborators_router import is_active_accountant
    if is_active_accountant(biz, str(user.id)):
        return rows[0]
    from business_users_router import role_of
    if role_of(biz, str(user.id)) in ("viewer", "member", "manager", "admin"):
        return rows[0]
    raise HTTPException(403, "not authorized")


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


def _basis_for(biz_row, requested: Optional[str]) -> str:
    """Category E — reporting basis: explicit request → per-business
    default (settings.financial.default_reporting_basis) → cash. Accrual
    needs the GL; the H.3a fallback stays cash."""
    if requested in ("cash", "accrual"):
        return requested
    fin = ((biz_row or {}).get("settings") or {}).get("financial") or {}
    return "accrual" if fin.get("default_reporting_basis") == "accrual" else "cash"


def _fiscal_period(biz_row, period: str, from_: Optional[str], to: Optional[str]):
    """Category D — custom fiscal years. When the business sets
    settings.financial.fiscal_year_start_month != 1, the year-shaped named
    periods translate to fiscal bounds HERE (custom from/to) so every report
    engine stays calendar-agnostic. this_year/ytd → fiscal-year-to-date;
    last_year → the full prior fiscal year."""
    if period not in ("this_year", "last_year", "ytd"):
        return period, from_, to
    try:
        fin = ((biz_row or {}).get("settings") or {}).get("financial") or {}
        fy = int(fin.get("fiscal_year_start_month") or 1)
    except Exception:
        fy = 1
    if fy < 2 or fy > 12:
        return period, from_, to
    from datetime import date as _d2, timedelta as _td
    today = _d2.today()
    start_year = today.year if today.month >= fy else today.year - 1
    if period == "last_year":
        start_year -= 1
    fy_start = _d2(start_year, fy, 1)
    fy_end = _d2(start_year + 1, fy, 1) - _td(days=1)
    if period in ("this_year", "ytd"):
        fy_end = today
    return "custom", fy_start.isoformat(), fy_end.isoformat()


@router.get("/pl")
def pl(biz: str, period: str = "this_month", comparison: Optional[str] = None,
       basis: Optional[str] = None,
       from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    if comparison:  # the comparison view is the reports_full part of P&L
        billing_limits.require_feature(biz, "reports_full")
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    b = _basis_for(biz_row, basis)
    out = _gl_or_fallback(
        biz,
        lambda: gl_reports.gl_profit_and_loss(biz, period, comparison, from_, to, basis=b),
        lambda: reports_engine.profit_and_loss(biz, period, comparison, from_, to))
    out.setdefault("basis", b if out.get("source") == "gl" else "cash")
    out["currency"] = "USD"   # Category E — explicit until multi-currency lands
    return out


@router.get("/ar-aging")
def ar_aging(biz: str, as_of: Optional[str] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
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
    _owner_or_reader(biz, user)
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
    biz_row = _owner_or_reader(biz, user)
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    return _gl_or_fallback(
        biz,
        lambda: gl_reports.gl_cash_flow(biz, period, from_, to),
        lambda: reports_engine.cash_flow(biz, period, from_, to))


@router.get("/balance-sheet")
def balance_sheet(biz: str, as_of: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    return _gl_or_fallback(
        biz,
        lambda: gl_reports.gl_balance_sheet(biz, as_of),
        lambda: reports_engine.balance_sheet(biz, as_of))


# ─── Phase I.4 — GL-native reports ───────────────────────────────────

@router.get("/trial-balance")
def trial_balance(biz: str, as_of: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
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
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
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
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "contractor_payments")
    from datetime import datetime as _dt, timezone as _tz
    y = year or _dt.now(_tz.utc).year
    return _summary_1099(biz, y)


# ─── Rails Arc 2 — 1099-NEC drafts (prep tool, never the filer) ──────

def _payer_block(biz_row: Dict[str, Any]) -> Dict[str, Any]:
    """Payer identity from the business row + settings.financial.payer
    (the 1099 panel collects EIN/address there)."""
    fin = ((biz_row.get("settings") or {}).get("financial") or {})
    payer = (fin.get("payer") or {})
    city_state_zip = ", ".join(
        p for p in [payer.get("city"), payer.get("state")] if p)
    if payer.get("zip"):
        city_state_zip = f"{city_state_zip} {payer['zip']}".strip(", ")
    return {
        "name": payer.get("name") or biz_row.get("name") or "",
        "ein": payer.get("ein") or "",
        "line1": payer.get("line1") or "",
        "line2": payer.get("line2") or "",
        "city_state_zip": city_state_zip,
        "phone": payer.get("phone") or "",
        "complete": bool(payer.get("ein") and payer.get("line1")),
    }


@router.get("/1099-drafts")
def drafts_1099(biz: str, year: Optional[int] = None,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Draft-readiness for every 'Manual 1099 needed' row: who has a
    W-9 profile, who's missing one, and whether the payer block is
    filled in. Stripe-managed rows are excluded — Stripe files those."""
    b = _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "contractor_payments")
    from datetime import datetime as _dt, timezone as _tz
    y = year or _dt.now(_tz.utc).year
    summary = _summary_1099(biz, y)

    manual = [r for r in summary["rows"]
              if not r.get("stripe_managed") and r.get("reaches_threshold")]
    cids = [r["contractor_id"] for r in manual if r.get("contractor_id")]
    profiles: Dict[str, Dict[str, Any]] = {}
    if cids:
        rows = sb_clients.sb_get_as_service(
            f"/contractors?id=in.({','.join(cids)})"
            f"&select=id,tax_name,tax_id_type,tin_last4,tin_encrypted,w9_received_at&limit=500") or []
        profiles = {r["id"]: r for r in rows}

    out = []
    for r in manual:
        p = profiles.get(r.get("contractor_id") or "") or {}
        out.append({
            "contractor_id": r.get("contractor_id"),
            "name": r["name"],
            "total_paid": r["total_paid"],
            "payments": r["payments"],
            "has_contractor": bool(r.get("contractor_id")),
            "has_w9": bool(p.get("tin_encrypted")),
            "tin_last4": p.get("tin_last4"),
            "tax_name": p.get("tax_name"),
            "w9_received_at": p.get("w9_received_at"),
            "draft_ready": bool(p.get("tin_encrypted")),
        })

    payer = _payer_block(b)
    return {
        "ok": True, "year": y, "rows": out,
        "payer": {k: payer[k] for k in ("name", "ein", "line1", "line2",
                                        "city_state_zip", "phone", "complete")},
        "note": ("Drafts for manually-paid contractors at/above the $600 IRS "
                 "threshold. Stripe-managed contractors are excluded — Stripe "
                 "Tax Reporting files those. Prepared by bookkeeping software, "
                 "not a CPA: review with your tax professional before filing."),
    }


@router.get("/1099-draft/pdf")
def draft_1099_pdf(biz: str, contractor_id: str, year: Optional[int] = None,
                   user: AuthedUser = Depends(require_user)) -> Response:
    """One contractor's draft 1099-NEC. The ONLY place the full TIN is
    ever decrypted — into the PDF the owner downloads to prepare the
    real filing."""
    import form_1099
    import tin_crypto

    # Owner ONLY — this endpoint decrypts the full TIN.
    b = _owner(biz, user)
    billing_limits.require_feature(biz, "contractor_payments")
    from datetime import datetime as _dt, timezone as _tz
    y = year or _dt.now(_tz.utc).year

    rows = sb_clients.sb_get_as_service(
        f"/contractors?id=eq.{contractor_id}&business_id=eq.{biz}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "contractor not found")
    c = rows[0]
    if c.get("stripe_account_id"):
        raise HTTPException(409, "Stripe-managed contractor — Stripe Tax Reporting "
                                 "files their 1099-NEC; no draft needed.")
    if not c.get("tin_encrypted"):
        raise HTTPException(409, "No W-9 on file — add the contractor's tax info first.")

    summary = _summary_1099(biz, y)
    row = next((r for r in summary["rows"]
                if r.get("contractor_id") == contractor_id), None)
    if not row:
        raise HTTPException(404, f"No paid 1099-eligible bills for this contractor in {y}.")

    tin = tin_crypto.decrypt_tin(c["tin_encrypted"])
    addr = c.get("tax_address") or {}
    city_state_zip = ", ".join(p for p in [addr.get("city"), addr.get("state")] if p)
    if addr.get("zip"):
        city_state_zip = f"{city_state_zip} {addr['zip']}".strip(", ")

    pdf = form_1099.build_draft_pdf(
        payer=_payer_block(b),
        recipient={
            "name": c.get("tax_name") or c.get("name") or "",
            "tin_display": tin_crypto.format_tin(tin, c.get("tax_id_type") or "ssn"),
            "line1": addr.get("line1") or "",
            "line2": addr.get("line2") or "",
            "city_state_zip": city_state_zip,
        },
        year=y,
        box1_amount=float(row["total_paid"]),
    )
    safe_name = (c.get("name") or "contractor").replace(" ", "_")[:40]
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{y}_1099NEC_DRAFT_{safe_name}.pdf"'})


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
    _owner_or_accountant(biz, user)
    billing_limits.require_feature(biz, "accountant_package")
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
    biz_row = _owner_or_accountant(biz, user)
    billing_limits.require_feature(biz, "accountant_package")
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
    # Seat-access arc (7/31 matrix): outward sends escalate to manager.
    biz_row = _owner_or_reader(biz, user)
    from business_users_router import require_role
    require_role(biz, str(user.id), "manager")
    billing_limits.require_feature(biz, "accountant_package")
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
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    if not gl_reports.gl_active(biz):
        return {"ok": True, "report": "journal", "entries": [], "has_more": False,
                "note": "No General Ledger yet — run Backfill in Admin."}
    return gl_reports.journal_report(biz, limit, offset)


_REPORT_TITLES = {
    "pl": "Profit & Loss", "ar_aging": "AR Aging", "ap_aging": "AP Aging",
    "cash_flow": "Cash Flow (Operating)", "balance_sheet": "Balance Sheet",
    "trial_balance": "Trial Balance", "general_ledger": "General Ledger",
    "summary_1099": "1099 Summary",
    # Phase I.8 — Tier-2 reports.
    "revenue": "Revenue Report", "expenses_detail": "Expense Report",
    "customer_statement": "Customer Statement",
    # Phase I.9 — Tier-3 analytical reports.
    "budget_vs_actual": "Budget vs Actual", "profitability": "Profitability",
    "trends": "Trends",
    # Phase I.10 — Tier-4 vertical compliance reports.
    "trust_reconciliation": "Trust Account Reconciliation",
    "donors": "Donor Report", "prep_990": "Form 990 Prep",
    "bank_reconciliation": "Bank Reconciliation",
    "audit_trail": "Closed-Period Edit Audit Trail",
}


# ─── Phase I.8 — Tier-2 reports ──────────────────────────────────────

def _needs_gl(report: str, **extra) -> Dict[str, Any]:
    return {"ok": True, "report": report, "needs_gl": True,
            "hint": "This report reads the General Ledger. Run the GL backfill "
                    "in Bookkeeping → Admin to unlock it.", **extra}


@router.get("/revenue")
def revenue(biz: str, period: str = "this_month",
            from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    if not gl_reports.gl_active(biz):
        return _needs_gl("revenue", total_revenue=0, by_account=[], by_source=[],
                         by_customer=[], by_offering=[], monthly=[])
    try:
        return gl_reports_t2.revenue_report(biz, period, from_, to)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/expenses-detail")
def expenses_detail(biz: str, period: str = "this_month",
                    from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    if not gl_reports.gl_active(biz):
        return _needs_gl("expenses_detail", total_expenses=0, by_account=[],
                         by_vendor=[], by_subcategory=[], monthly=[])
    try:
        return gl_reports_t2.expense_report(biz, period, from_, to)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ─── Phase I.9 — Tier-3 analytical reports ───────────────────────────

class BudgetEntry(BaseModel):
    category: str
    amount: float


class BudgetsBody(BaseModel):
    year: int
    month: int
    entries: List[BudgetEntry]


@router.get("/budgets")
def get_budgets(biz: str, year: int, month: int,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    return {"ok": True, "budgets": gl_reports_t3.list_budgets(biz, year, month),
            "categories": list(gl_reports_t3.BUDGET_CATEGORIES)}


@router.put("/budgets")
def put_budgets(biz: str, body: BudgetsBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    # Seat-access arc (7/31 matrix): budgets are everyday operator work —
    # member+ writes (matches the business_budgets RLS write policy).
    _owner_or_reader(biz, user)
    from business_users_router import require_role
    require_role(biz, str(user.id), "member")
    billing_limits.require_feature(biz, "reports_full")
    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month must be 1-12")
    return gl_reports_t3.upsert_budgets(
        biz, body.year, body.month,
        [{"category": e.category, "amount": e.amount} for e in body.entries])


@router.get("/budget-vs-actual")
def budget_vs_actual(biz: str, period: str = "this_month",
                     from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    if not gl_reports.gl_active(biz):
        return _needs_gl("budget_vs_actual", rows=[], has_any_budget=False)
    try:
        return gl_reports_t3.budget_vs_actual(biz, biz_row, period, from_, to)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/cash-forecast")
def cash_forecast(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    if not gl_reports.gl_active(biz):
        return _needs_gl("cash_forecast", horizons=[], monthly_history=[])
    return gl_reports_t3.cash_flow_forecast(biz)


@router.get("/profitability")
def profitability(biz: str, period: str = "this_year",
                  from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    if not gl_reports.gl_active(biz):
        return _needs_gl("profitability", by_customer=[], by_offering=[])
    try:
        return gl_reports_t3.profitability(biz, period, from_, to)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/trends")
def trends_report(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "reports_full")
    if not gl_reports.gl_active(biz):
        return _needs_gl("trends", monthly=[], seasonality=[], momentum={})
    return gl_reports_t3.trends(biz)


# ─── Phase I.10 — Tier-4 vertical compliance reports ─────────────────

@router.get("/trust-reconciliation")
def trust_reconciliation(biz: str, as_of: Optional[str] = None,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "vertical_reports")
    if not gl_reports.gl_active(biz):
        return _needs_gl("trust_reconciliation", three_way={}, by_client=[], activity=[])
    return gl_reports_t4.trust_reconciliation(biz, as_of)


@router.get("/donors")
def donors(biz: str, period: str = "this_year",
           from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "vertical_reports")
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    try:
        return gl_reports_t4.donor_report(biz, period, from_, to)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/990-prep")
def prep_990(biz: str, year: Optional[int] = None,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "vertical_reports")
    if not gl_reports.gl_active(biz):
        return _needs_gl("prep_990", contributions=[], functional_expenses=[],
                         net_assets=[], sme_flags=[])
    return gl_reports_t4.prep_990(biz, year)


@router.get("/bank-reconciliation")
def bank_reconciliation(biz: str, period: str = "this_month",
                        from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner_or_reader(biz, user)
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
    try:
        return gl_reports_t4.bank_reconciliation(biz, period, from_, to)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/audit-trail-report")
def audit_trail_report(biz: str, source_type: Optional[str] = None,
                       from_: Optional[str] = Query(None, alias="from"),
                       to: Optional[str] = None,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    billing_limits.require_feature(biz, "audit_trail")
    return gl_reports_t4.audit_trail(biz, source_type=source_type,
                                     date_from=from_, date_to=to)


@router.get("/statement-customers")
def statement_customers(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    return {"ok": True, "customers": gl_reports_t2.list_statement_customers(biz)}


@router.get("/customer-statement")
def customer_statement(biz: str, contact_id: str, as_of: Optional[str] = None,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner_or_reader(biz, user)
    return gl_reports_t2.customer_statement(biz, contact_id, as_of)


@router.post("/customer-statement/send")
async def customer_statement_send(biz: str, contact_id: str,
                                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Email the statement (PDF attached) to the contact's email on file."""
    # Seat-access arc (7/31 matrix): statements to customers are everyday
    # operator work — member+ sends.
    biz_row = _owner_or_reader(biz, user)
    from business_users_router import require_role
    require_role(biz, str(user.id), "member")
    data = gl_reports_t2.customer_statement(biz, contact_id, None)
    contact = data.get("contact") or {}
    to_email = contact.get("email")
    biz_name = biz_row.get("name") or "Business"
    subject, body = gl_reports_t2.statement_email(biz_name, contact.get("name"), data)
    if not to_email:
        return {"ok": True, "email_sent": False, "recipient": None,
                "subject": subject, "body": body,
                "note": "This contact has no email on file — add one in Contacts, "
                        "or download the PDF and send it yourself."}
    email_sent = False
    try:
        import pdf_reports
        import base64
        meta = pdf_reports.build_meta(
            business_name=biz_name, settings=biz_row.get("settings"),
            report_title="Customer Statement",
            period_label=f"As of {data.get('as_of')}",
            basis_label="Cash Basis", currency="USD",
            generated_by=_generated_by(biz_row, user))
        pdf = pdf_reports.render("customer_statement", data, meta)
        from email_sender import send_via_resend
        await send_via_resend(
            to_email=to_email, to_name=contact.get("name"),
            from_email="reports@solutionist.studio", from_name=biz_name,
            reply_to=None, subject=subject, body=body,
            attachments=[{"filename": "statement.pdf",
                          "content": base64.b64encode(pdf).decode("ascii"),
                          "content_type": "application/pdf"}])
        email_sent = True
    except Exception as e:
        logger.warning(f"[i8] statement email failed: {e}")
    return {"ok": True, "email_sent": email_sent, "recipient": to_email,
            "subject": subject, "body": body}


@router.get("/export")
def export(biz: str, report: str, format: str = "csv",
           period: str = "this_month", as_of: Optional[str] = None,
           comparison: Optional[str] = None, contact_id: Optional[str] = None,
           source_type_filter: Optional[str] = None,
           from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
           user: AuthedUser = Depends(require_user)) -> Response:
    biz_row = _owner_or_reader(biz, user)
    if report not in _REPORT_TITLES:
        raise HTTPException(400, "unknown report")
    # Exports gate exactly like their screens; Starter reports (P&L,
    # agings, cash flow, balance sheet, statements, bank rec) stay free.
    if report in _REPORT_FEATURES:
        billing_limits.require_feature(biz, _REPORT_FEATURES[report])
    period, from_, to = _fiscal_period(biz_row, period, from_, to)
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
        elif report == "revenue":
            data = gl_reports_t2.revenue_report(biz, period, from_, to) \
                if gl_reports.gl_active(biz) else {"report": "revenue", "by_account": [],
                                                   "by_source": [], "by_customer": [],
                                                   "by_offering": [], "monthly": [],
                                                   "total_revenue": 0}
        elif report == "expenses_detail":
            data = gl_reports_t2.expense_report(biz, period, from_, to) \
                if gl_reports.gl_active(biz) else {"report": "expenses_detail", "by_account": [],
                                                   "by_vendor": [], "by_subcategory": [],
                                                   "monthly": [], "total_expenses": 0}
        elif report == "customer_statement":
            if not contact_id:
                raise HTTPException(400, "contact_id required for customer_statement")
            data = gl_reports_t2.customer_statement(biz, contact_id, as_of)
        elif report == "budget_vs_actual":
            data = gl_reports_t3.budget_vs_actual(biz, biz_row, period, from_, to) \
                if gl_reports.gl_active(biz) else {"report": "budget_vs_actual", "rows": []}
        elif report == "profitability":
            data = gl_reports_t3.profitability(biz, period, from_, to) \
                if gl_reports.gl_active(biz) else {"report": "profitability",
                                                   "by_customer": [], "by_offering": []}
        elif report == "trends":
            data = gl_reports_t3.trends(biz) if gl_reports.gl_active(biz) \
                else {"report": "trends", "monthly": [], "seasonality": [], "momentum": {}}
        elif report == "trust_reconciliation":
            data = gl_reports_t4.trust_reconciliation(biz, as_of) \
                if gl_reports.gl_active(biz) else {"report": "trust_reconciliation",
                                                   "three_way": {}, "by_client": [],
                                                   "activity": [], "accounts": []}
        elif report == "donors":
            data = gl_reports_t4.donor_report(biz, period, from_, to)
        elif report == "prep_990":
            from datetime import datetime as _dt2, timezone as _tz2
            y2 = int((as_of or "")[:4]) if (as_of or "")[:4].isdigit() else _dt2.now(_tz2.utc).year
            data = gl_reports_t4.prep_990(biz, y2) if gl_reports.gl_active(biz) \
                else {"report": "prep_990", "contributions": [],
                      "functional_expenses": [], "net_assets": [], "sme_flags": []}
        elif report == "bank_reconciliation":
            data = gl_reports_t4.bank_reconciliation(biz, period, from_, to)
        elif report == "audit_trail":
            data = gl_reports_t4.audit_trail(biz, source_type=source_type_filter,
                                             date_from=from_, date_to=to)
        elif report == "pl":
            b = _basis_for(biz_row, None)
            data = _gl_or_fallback(
                biz, lambda: gl_reports.gl_profit_and_loss(biz, period, comparison, from_, to,
                                                           basis=b),
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
            basis_label=("Accrual Basis" if data.get("basis") == "accrual"
                         else "Cash Basis"), currency="USD",
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
    elif report == "revenue":
        rows.append(["Breakdown", "Item", "Amount"])
        for a in data.get("by_account", []):
            rows.append(["Account", str(a.get("code")) + " " + str(a.get("name")), a.get("amount")])
        for x in data.get("by_source", []):
            rows.append(["Source", x.get("source"), x.get("amount")])
        for c in data.get("by_customer", []):
            rows.append(["Customer", c.get("customer"), c.get("amount")])
        for o in data.get("by_offering", []):
            rows.append(["Offering", o.get("offering"), o.get("amount")])
        for m in data.get("monthly", []):
            rows.append(["Month", m.get("month"), m.get("amount")])
        rows.append(["", "TOTAL REVENUE", data.get("total_revenue", 0)])
    elif report == "expenses_detail":
        rows.append(["Breakdown", "Item", "Amount"])
        for a in data.get("by_account", []):
            rows.append(["Account", str(a.get("code")) + " " + str(a.get("name")), a.get("amount")])
        for v in data.get("by_vendor", []):
            rows.append(["Vendor", v.get("vendor"), v.get("amount")])
        for x in data.get("by_subcategory", []):
            rows.append(["Subcategory", x.get("subcategory"), x.get("amount")])
        for m in data.get("monthly", []):
            rows.append(["Month", m.get("month"), m.get("amount")])
        rows.append(["", "TOTAL EXPENSES", data.get("total_expenses", 0)])
    elif report == "customer_statement":
        rows.append(["Date", "Type", "Ref", "Description", "Amount", "Balance"])
        for l in data.get("lines", []):
            rows.append([l.get("date"), l.get("type"), l.get("ref"),
                         l.get("description"), l.get("amount"), l.get("balance")])
        t = data.get("totals") or {}
        rows.append(["", "", "", "BALANCE DUE", "", t.get("balance", 0)])
    elif report == "budget_vs_actual":
        rows.append(["Category", "Actual", "Budget", "Budget Source", "Variance"])
        for r in data.get("rows", []):
            rows.append([r.get("label"), r.get("actual"), r.get("budget"),
                         r.get("budget_source"), r.get("variance")])
    elif report == "profitability":
        rows.append(["Group", "Name", "Revenue", "Share %", "Allocated Overhead", "Contribution"])
        for c in data.get("by_customer", []):
            rows.append(["Customer", c.get("customer"), c.get("revenue"),
                         c.get("revenue_share_pct"), c.get("allocated_overhead"),
                         c.get("contribution")])
        for o in data.get("by_offering", []):
            rows.append(["Offering", o.get("offering"), o.get("revenue"),
                         o.get("revenue_share_pct"), o.get("allocated_overhead"),
                         o.get("contribution")])
        rows.append(["", "METHOD", data.get("method", ""), "", "", ""])
    elif report == "trends":
        rows.append(["Month", "Revenue", "Expenses", "Net"])
        for m in data.get("monthly", []):
            rows.append([m.get("month"), m.get("revenue"), m.get("expenses"), m.get("net")])
    elif report == "trust_reconciliation":
        tw = data.get("three_way") or {}
        rows.append(["Three-Way Check", "Amount"])
        rows.append(["GL Trust Cash (1200)", tw.get("gl_trust_cash")])
        rows.append(["Client Funds Liability (2200)", tw.get("client_funds_liability")])
        rows.append(["Bank Trust Balance", tw.get("bank_trust_balance")])
        rows.append([])
        rows.append(["Client", "Deposits", "Disbursements", "Balance"])
        for c in data.get("by_client", []):
            rows.append([c.get("client"), c.get("deposits"), c.get("disbursements"),
                         c.get("balance")])
        rows.append([])
        rows.append(["Date", "Description", "Type", "Amount", "Client"])
        for a in data.get("activity", []):
            rows.append([a.get("date"), a.get("description"), a.get("type"),
                         a.get("amount"), a.get("client")])
    elif report == "donors":
        rows.append([data.get("donor_label") or "Donor", "Gifts", "Total", "Restricted"])
        for d2 in data.get("donors", []):
            rows.append([d2.get("donor"), d2.get("gifts"), d2.get("total"),
                         d2.get("restricted")])
        rows.append(["", "TOTAL", data.get("total_gifts", 0),
                     data.get("restricted_gifts", 0)])
    elif report == "prep_990":
        rows.append(["Section", "Line", "Amount"])
        for c in data.get("contributions", []):
            rows.append(["Income", f"{c.get('code')} {c.get('name')}", c.get("amount")])
        for f in data.get("functional_expenses", []):
            rows.append(["Expense (bucket)", f.get("bucket"), f.get("amount")])
        for n in data.get("net_assets", []):
            rows.append(["Net Assets", f"{n.get('code')} {n.get('name')}", n.get("balance")])
        rows.append(["", "CHANGE IN NET ASSETS", data.get("change_in_net_assets", 0)])
    elif report == "bank_reconciliation":
        rows.append(["Account", "Beginning", "Deposits", "Withdrawals", "Ending",
                     "Pending", "Excluded"])
        for a in data.get("accounts", []):
            ri = a.get("reconciling_items") or {}
            rows.append([f"{a.get('name')} ••{a.get('mask')}", a.get("beginning_balance"),
                         a.get("deposits"), a.get("withdrawals"), a.get("ending_balance"),
                         ri.get("pending_count"), ri.get("excluded_count")])
    elif report == "audit_trail":
        rows.append(["When", "Source", "Source ID", "By", "Reason", "Change"])
        for e in data.get("entries", []):
            rows.append([e.get("at"), e.get("source_type"), e.get("source_id"),
                         e.get("by_role"), e.get("reason"), e.get("change")])
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
