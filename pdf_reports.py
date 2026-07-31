"""
pdf_reports.py — Phase H.3a v1.2 — professional PDF design system.

Centralized, branded report rendering used by EVERY bookkeeping export
(Balance Sheet, P&L, AR/AP Aging, Cash Flow, Reconciliation; Trial Balance /
GL / Tax later). reportlab Platypus (already a dependency — no WeasyPrint
system-font/cairo deps on Railway).

Each report passes its data dict (the same shape reports_engine produces) +
a meta dict; this module renders consistent chrome (branded header band,
footer with page numbers + Solutionist attribution, accounting-formatted
tables, signature + notes block).

Branding (γ): per-business logo + accent color when set (businesses.settings.
branding), else the Solutionist System default. reportlab is imported inside
the render functions so the module imports even where reportlab is absent
(local test env); pure helpers below are unit-tested.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pdf_reports")

# Solutionist System defaults (refined muted gold + neutral ink).
SOLUTIONIST_ACCENT = "#B8893B"
_INK = "#1B1B1B"
_MUTED = "#6E6E6E"
_RULE = "#D9D5CC"
_STRIPE = "#F7F4EE"
_DANGER = "#C0392B"


# ─── Pure helpers (unit-tested) ──────────────────────────────────────

def fmt_money(n: Any, currency: str = "USD") -> str:
    """Accounting format: $1,825.77 · negatives in parentheses · zero as —."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    if abs(v) < 0.005:
        return "—"
    s = f"{abs(v):,.2f}"
    sym = "$" if currency.upper() == "USD" else ""
    return f"({sym}{s})" if v < 0 else f"{sym}{s}"


def fmt_pct(p: Any) -> str:
    if p is None:
        return "—"
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "—"
    return f"{'+' if v >= 0 else ''}{v:.1f}%"


def resolve_brand(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-business branding with Solutionist fallback."""
    b = ((settings or {}).get("branding") or {})
    accent = (b.get("accent_color") or "").strip() or SOLUTIONIST_ACCENT
    if not accent.startswith("#") or len(accent) not in (4, 7):
        accent = SOLUTIONIST_ACCENT
    return {
        "logo_url": (b.get("logo_url") or "").strip() or None,
        "accent": accent,
        "secondary": (b.get("secondary_color") or "").strip() or None,
        "has_business_logo": bool((b.get("logo_url") or "").strip()),
    }


def build_meta(*, business_name: str, settings: Optional[Dict[str, Any]],
               report_title: str, period_label: str, basis_label: str = "Cash Basis",
               currency: str = "USD", generated_by: str = "",
               notes: str = "", confidential: bool = False) -> Dict[str, Any]:
    brand = resolve_brand(settings)
    now = datetime.now(timezone.utc).astimezone()
    # Portable (no %-m/%-I — those are Linux-only).
    hour12 = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    generated_at = f"{now.month}/{now.day}/{now.year} {hour12}:{now.minute:02d} {ampm}"
    return {
        "business_name": business_name or "Business",
        "report_title": report_title,
        "period_label": period_label,
        "basis_label": basis_label,
        "currency": currency,
        "currency_label": f"Amounts in {currency.upper()}",
        "generated_by": generated_by or "",
        "generated_at": generated_at,
        "notes": notes or "",
        "confidential": confidential,
        "brand": brand,
    }


def _fetch_logo(url: Optional[str]) -> Optional[bytes]:
    if not url:
        return None
    try:
        import httpx
        r = httpx.get(url, timeout=5.0)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception as e:  # cold-start / network — degrade gracefully (no logo)
        logger.warning(f"[pdf] logo fetch failed: {e}")
    return None


# ─── Render (reportlab) ──────────────────────────────────────────────

def render(report_key: str, data: Dict[str, Any], meta: Dict[str, Any]) -> bytes:
    """Render a report to branded PDF bytes. Raises ImportError if reportlab
    is unavailable (caller falls back to CSV)."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_LEFT
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.utils import ImageReader

    accent = colors.HexColor(meta["brand"]["accent"])
    ink = colors.HexColor(_INK)
    muted = colors.HexColor(_MUTED)
    rule = colors.HexColor(_RULE)
    stripe = colors.HexColor(_STRIPE)
    danger = colors.HexColor(_DANGER)
    logo_bytes = _fetch_logo(meta["brand"]["logo_url"])

    styles = {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18,
                                textColor=ink, leading=22),
        "biz": ParagraphStyle("biz", fontName="Helvetica-Bold", fontSize=11,
                              textColor=ink, leading=14),
        "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=9,
                               textColor=muted, leading=13),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=11,
                                  textColor=accent, leading=15, spaceBefore=10, spaceAfter=4),
        "row": ParagraphStyle("row", fontName="Helvetica", fontSize=9.5, textColor=ink, leading=13),
        "rowind": ParagraphStyle("rowind", fontName="Helvetica", fontSize=9, textColor=muted,
                                 leading=12, leftIndent=14),
        "amt": ParagraphStyle("amt", fontName="Helvetica", fontSize=9.5, textColor=ink,
                              leading=13, alignment=TA_RIGHT),
        "amtb": ParagraphStyle("amtb", fontName="Helvetica-Bold", fontSize=10, textColor=ink,
                               leading=13, alignment=TA_RIGHT),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8, textColor=muted, leading=11),
        "thr": ParagraphStyle("thr", fontName="Helvetica-Bold", fontSize=8, textColor=muted,
                              leading=11, alignment=TA_RIGHT),
        "danger": ParagraphStyle("danger", fontName="Helvetica-Bold", fontSize=10,
                                 textColor=danger, leading=13),
        "sign": ParagraphStyle("sign", fontName="Helvetica", fontSize=9, textColor=ink, leading=20),
        "note": ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8.5,
                               textColor=muted, leading=12),
        # Total-row label (bold, left) paired with a bold right-aligned amount.
        "totlbl": ParagraphStyle("totlbl", fontName="Helvetica-Bold", fontSize=10, textColor=ink, leading=13),
        "netlbl": ParagraphStyle("netlbl", fontName="Helvetica-Bold", fontSize=11, textColor=accent, leading=15),
        "drr": ParagraphStyle("drr", fontName="Helvetica-Bold", fontSize=9, textColor=danger,
                              leading=12, alignment=TA_RIGHT),
        "drl": ParagraphStyle("drl", fontName="Helvetica-Bold", fontSize=9, textColor=danger, leading=12),
    }

    def money_cell(n, bold=False):
        return Paragraph(fmt_money(n, meta["currency"]), styles["amtb" if bold else "amt"])

    # ── chrome: header band + footer on every page (two-pass for "of N") ──
    class _Doc(BaseDocTemplate):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def afterFlowable(self, flowable):
            pass

    def _draw_chrome(canv, doc):
        w, h = letter
        page = canv.getPageNumber()
        # header
        canv.saveState()
        if page == 1 and logo_bytes:
            try:
                img = ImageReader(io.BytesIO(logo_bytes))
                iw, ih = img.getSize()
                dh = 0.42 * inch
                dw = dh * (iw / ih) if ih else dh
                canv.drawImage(img, 0.75 * inch, h - 0.9 * inch, width=min(dw, 1.6 * inch),
                               height=dh, preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
        canv.setFont("Helvetica-Bold", 9)
        canv.setFillColor(ink)
        name = meta["business_name"]
        if len(name) > 42:
            name = name[:40] + "…"
        canv.drawString(2.5 * inch if (page == 1 and logo_bytes) else 0.75 * inch,
                        h - 0.62 * inch, name)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(muted)
        title = meta["report_title"] + ("  (continued)" if page > 1 else "")
        canv.drawRightString(w - 0.75 * inch, h - 0.62 * inch, title)
        canv.setStrokeColor(accent)
        canv.setLineWidth(1.4)
        canv.line(0.75 * inch, h - 0.74 * inch, w - 0.75 * inch, h - 0.74 * inch)
        # footer
        canv.setStrokeColor(rule)
        canv.setLineWidth(0.5)
        canv.line(0.75 * inch, 0.62 * inch, w - 0.75 * inch, 0.62 * inch)
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(muted)
        if meta["generated_by"]:
            canv.drawString(0.75 * inch, 0.46 * inch,
                            f"Generated by {meta['generated_by']} on {meta['generated_at']}")
        canv.drawRightString(w - 0.75 * inch, 0.46 * inch, "Solutionist System")
        total = getattr(doc, "_total_pages", page)
        canv.drawCentredString(w / 2.0, 0.46 * inch, f"Page {page} of {total}")
        if meta["confidential"]:
            canv.setFont("Helvetica-Bold", 7)
            canv.drawCentredString(w / 2.0, 0.30 * inch, "CONFIDENTIAL — FOR INTERNAL USE")
        canv.restoreState()

    buf = io.BytesIO()
    doc = _Doc(buf, pagesize=letter, topMargin=0.95 * inch, bottomMargin=0.8 * inch,
               leftMargin=0.75 * inch, rightMargin=0.75 * inch, title=meta["report_title"])
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_draw_chrome)])

    # ── story: metadata block + body + signature/notes ──
    story: List[Any] = []
    story.append(Paragraph(meta["report_title"], styles["title"]))
    sub = " · ".join([x for x in [meta["period_label"], meta["basis_label"], meta["currency_label"]] if x])
    story.append(Paragraph(sub, styles["meta"]))
    story.append(Spacer(1, 0.18 * inch))

    builder = _BUILDERS.get(report_key, _generic_body)
    story += builder(data, styles, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                     Paragraph, Spacer, inch, meta)

    # signature + notes
    story.append(Spacer(1, 0.35 * inch))
    sig = Table([[Paragraph("Reviewed by  ______________________", styles["sign"]),
                  Paragraph("Date  ____________", styles["sign"])]],
                colWidths=[3.6 * inch, 2.4 * inch])
    sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(sig)
    default_note = ("Prepared on a cash basis unless otherwise noted. Figures derive from linked "
                    "bank activity, invoices, and recorded expenses; verify against source records.")
    note_text = meta["notes"] or default_note
    story.append(Spacer(1, 0.12 * inch))
    story.append(Paragraph("Notes: " + note_text, styles["note"]))

    # two-pass page count
    class _Counter(_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            doc._total_pages = len(self._saved)
            for st in self._saved:
                self.__dict__.update(st)
                super().showPage()
            super().save()

    doc.build(story, canvasmaker=_Counter)
    return buf.getvalue()


# ─── Per-report body builders ────────────────────────────────────────
# Signature kept verbose so each builder is self-contained.

def _amount_table(rows, money_cell, Table, TableStyle, colors, rule, stripe, total_idx=None,
                  ind_flags=None, col2=2.0):
    """rows: list of (label_paragraph, value_or_paragraph). Right-aligned amounts,
    light rule under totals, subtle striping."""
    from reportlab.lib.units import inch
    data = [[lbl, val] for (lbl, val) in rows]
    t = Table(data, colWidths=[None, col2 * inch])
    style = [("ALIGN", (1, 0), (1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    for i in (total_idx or []):
        style.append(("LINEABOVE", (0, i), (1, i), 0.8, rule))
        style.append(("LINEBELOW", (0, i), (1, i), 1.2, colors.HexColor(_INK)))
        style.append(("TOPPADDING", (0, i), (-1, i), 5))
    t.setStyle(TableStyle(style))
    return t


def _balance_sheet_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                        Paragraph, Spacer, inch, meta):
    a, li, eq = d.get("assets") or {}, d.get("liabilities") or {}, d.get("equity") or {}
    out = []

    def section(title, rows, total_label, total_val):
        out.append(Paragraph(title, s["section"]))
        body = [(Paragraph(lbl, s["row"]), money_cell(v)) for lbl, v in rows]
        body.append((Paragraph(total_label, s["totlbl"]), money_cell(total_val, bold=True)))
        out.append(_amount_table(body, money_cell, Table, TableStyle, colors, rule, stripe,
                                 total_idx=[len(body) - 1]))

    section("ASSETS", [("Cash (bank balances)", a.get("cash")),
                       ("Accounts Receivable", a.get("accounts_receivable"))],
            "Total Assets", a.get("total"))
    section("LIABILITIES", [("Accounts Payable", li.get("accounts_payable"))],
            "Total Liabilities", li.get("total"))
    section("EQUITY", [("Retained Earnings", eq.get("retained_earnings"))],
            "Total Equity", eq.get("total"))

    le = round(float(li.get("total") or 0) + float(eq.get("total") or 0), 2)
    ta = round(float(a.get("total") or 0), 2)
    out.append(Spacer(1, 0.1 * inch))
    if abs(le - ta) < 0.01:
        out.append(Paragraph(f"✓ Balanced — Liabilities + Equity = Total Assets "
                             f"({fmt_money(le, meta['currency'])})", s["row"]))
    else:
        out.append(Paragraph("Books not balanced — Liabilities + Equity ≠ Total Assets. "
                             "Contact support.", s["danger"]))
    return out


def _pl_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
             Paragraph, Spacer, inch, meta):
    cur = d.get("current") or {}
    rev, exp = cur.get("revenue") or {}, cur.get("expenses") or {}
    cmp_ = (d.get("comparison") or {}).get("change") or {}
    out = [Paragraph("REVENUE", s["section"])]
    rrows = [(Paragraph("Invoiced (paid)", s["row"]), money_cell(rev.get("invoiced")))]
    if float(rev.get("refunds") or 0) > 0:
        rrows.append((Paragraph("Less refunds", s["rowind"]), money_cell(-float(rev.get("refunds") or 0))))
    rrows.append((Paragraph("Other (non-Stripe) income", s["row"]), money_cell(rev.get("plaid_other_income"))))
    rrows.append((Paragraph("Gross Revenue", s["totlbl"]),
                  money_cell(rev.get("gross_revenue"), bold=True)))
    out.append(_amount_table(rrows, money_cell, Table, TableStyle, colors, rule, stripe,
                             total_idx=[len(rrows) - 1]))

    out.append(Paragraph("EXPENSES", s["section"]))
    erows = []
    for b in (exp.get("by_bucket") or []):
        erows.append((Paragraph(f"{b['label']}  <font size=7 color='#9A9A9A'>· {b.get('pct',0)}%</font>", s["row"]),
                      money_cell(b["total"])))
        for ln in (b.get("lines") or []):
            if ln.get("subcategory") and ln["subcategory"] != "—":
                erows.append((Paragraph(ln["subcategory"], s["rowind"]), money_cell(ln["amount"])))
    if not erows:
        erows.append((Paragraph("No expenses in this period", s["rowind"]), Paragraph("—", s["amt"])))
    erows.append((Paragraph("Total Expenses", s["totlbl"]),
                  money_cell(exp.get("total"), bold=True)))
    out.append(_amount_table(erows, money_cell, Table, TableStyle, colors, rule, stripe,
                             total_idx=[len(erows) - 1]))

    out.append(Spacer(1, 0.12 * inch))
    out.append(_amount_table(
        [(Paragraph("NET INCOME", s["netlbl"]),
          money_cell(cur.get("net_income"), bold=True))],
        money_cell, Table, TableStyle, colors, rule, stripe, total_idx=[0]))

    if cmp_:
        out.append(Spacer(1, 0.2 * inch))
        out.append(Paragraph("VS PRIOR PERIOD", s["section"]))
        cmp_rows = [[Paragraph("Metric", s["th"]), Paragraph("Change", s["thr"])]]
        for k, label in (("gross_revenue", "Gross Revenue"), ("total_expenses", "Total Expenses"),
                         ("net_income", "Net Income")):
            cmp_rows.append([Paragraph(label, s["row"]),
                             Paragraph(fmt_pct(cmp_.get(k)), s["amt"])])
        t = Table(cmp_rows, colWidths=[None, 1.6 * inch])
        t.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule)]))
        out.append(t)
    return out


def _aging_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                Paragraph, Spacer, inch, meta, *, party_key, party_label, items_key, amt_key, party_field):
    bk = d.get("buckets") or {}
    out = [Paragraph("AGING SUMMARY", s["section"])]
    cols = [("current", "Current"), ("d1_30", "1–30"), ("d31_60", "31–60"),
            ("d61_90", "61–90"), ("d90_plus", "90+")]
    head = [Paragraph(lbl, s["thr"] if i else s["th"]) for i, (_, lbl) in enumerate(cols)]
    vals = []
    for key, _ in cols:
        risk = key in ("d61_90", "d90_plus")
        vals.append(Paragraph(fmt_money(bk.get(key), meta["currency"]),
                              s["drr"] if risk else s["amt"]))
    t = Table([head, vals], colWidths=[1.1 * inch] * 5)
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
                           ("TOPPADDING", (0, 1), (-1, 1), 4)]))
    out.append(t)
    out.append(Spacer(1, 0.06 * inch))
    out.append(_amount_table([
        (Paragraph("Total outstanding", s["totlbl"]),
         money_cell(d.get("total_outstanding"), bold=True)),
        (Paragraph("At risk (60+ days)", s["drl"]),
         Paragraph(fmt_money(d.get("at_risk"), meta["currency"]), s["drr"]))],
        money_cell, Table, TableStyle, colors, rule, stripe, total_idx=[0]))

    parties = d.get(party_key) or []
    if parties:
        out.append(Paragraph(f"BY {party_label.upper()}", s["section"]))
        prows = [(Paragraph(f"{p[party_field]}  <font size=7 color='#9A9A9A'>· {p.get('count',0)}</font>", s["row"]),
                  money_cell(p["total"])) for p in parties]
        out.append(_amount_table(prows, money_cell, Table, TableStyle, colors, rule, stripe))

    items = d.get(items_key) or []
    if items:
        out.append(Paragraph("DETAIL", s["section"]))
        head = [Paragraph(h, s["th"]) for h in (party_label, "Due", "Overdue")] + [Paragraph("Amount", s["thr"])]
        rows = [head]
        for it in items[:120]:
            od = it.get("days_overdue", 0)
            rows.append([Paragraph(str(it.get(party_field) or it.get("vendor") or it.get("contact") or "—"), s["row"]),
                         Paragraph(str(it.get("due_date") or "—"), s["rowind"]),
                         Paragraph(f"{od}d" if od else "—",
                                   s["drl"] if od else s["rowind"]),
                         money_cell(it.get(amt_key))])
        t = Table(rows, colWidths=[None, 1.0 * inch, 0.8 * inch, 1.2 * inch])
        st = [("ALIGN", (3, 0), (3, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe])]
        t.setStyle(TableStyle(st))
        out.append(t)
    return out


def _ar_body(d, *a, **k):
    return _aging_body(d, *a, party_key="by_contact", party_label="Contact", items_key="invoices",
                       amt_key="total", party_field="contact", **k)


def _ap_body(d, *a, **k):
    return _aging_body(d, *a, party_key="by_vendor", party_label="Vendor", items_key="bills",
                       amt_key="amount", party_field="vendor", **k)


def _cash_flow_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                    Paragraph, Spacer, inch, meta):
    op = d.get("operating") or {}
    out = [Paragraph("OPERATING ACTIVITIES", s["section"])]
    out.append(_amount_table([
        (Paragraph("Cash from customers", s["row"]), money_cell(op.get("cash_from_customers"))),
        (Paragraph("Cash to suppliers", s["row"]), money_cell(-float(op.get("cash_to_suppliers") or 0))),
        (Paragraph("Net cash from operations", s["totlbl"]),
         money_cell(op.get("net_cash_from_operations"), bold=True))],
        money_cell, Table, TableStyle, colors, rule, stripe, total_idx=[2]))
    out.append(Spacer(1, 0.1 * inch))
    out.append(Paragraph(d.get("note") or "Operating activities only.", s["note"]))
    return out


def _reconciliation_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                         Paragraph, Spacer, inch, meta):
    matched = d.get("matched") or []
    un_plaid = d.get("unmatched_plaid") or []
    un_stripe = d.get("unmatched_stripe") or []
    ccy = meta["currency"]
    out = [Paragraph("SUMMARY", s["section"])]
    msum = sum(abs(float(r.get("amount") or 0)) for r in matched)
    psum = sum(abs(float(r.get("amount") or 0)) for r in un_plaid)
    ssum = sum(float(r.get("amount") or 0) for r in un_stripe)
    out.append(_amount_table([
        (Paragraph(f"Matched ({len(matched)})", s["row"]), money_cell(msum)),
        (Paragraph(f"Unmatched bank deposits ({len(un_plaid)})", s["row"]), money_cell(psum)),
        (Paragraph(f"Unmatched Stripe payouts ({len(un_stripe)})", s["row"]), money_cell(ssum))],
        money_cell, Table, TableStyle, colors, rule, stripe))

    if matched:
        out.append(Paragraph("MATCHED", s["section"]))
        head = [Paragraph(h, s["th"]) for h in ("Stripe Payout", "Payout date", "Bank deposit", "Type")]
        head.append(Paragraph("Amount", s["thr"]))
        rows = [head]
        for m in matched[:150]:
            manual = m.get("reconciliation_status") == "manual_matched"
            rows.append([
                Paragraph((m.get("reconciled_to_payout_id") or "")[:16] + "…", s["rowind"]),
                Paragraph(str(m.get("reconciled_payout_date") or "—"), s["rowind"]),
                Paragraph(str(m.get("merchant_name") or m.get("name") or "—"), s["row"]),
                Paragraph("Manual" if manual else "Auto", s["row"]),
                money_cell(abs(float(m.get("amount") or 0)))])
        t = Table(rows, colWidths=[1.5 * inch, 0.9 * inch, None, 0.7 * inch, 1.0 * inch])
        t.setStyle(TableStyle([("ALIGN", (4, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe])]))
        out.append(t)

    def _unmatched(title, items, cols):
        if not items:
            return
        out.append(Paragraph(title, s["section"]))
        head = [Paragraph(c[0], s["th"]) for c in cols[:-1]] + [Paragraph(cols[-1][0], s["thr"])]
        rows = [head]
        for it in items[:150]:
            line = [Paragraph(str(c[1](it)), s["row"]) for c in cols[:-1]]
            line.append(money_cell(cols[-1][1](it)))
            rows.append(line)
        t = Table(rows, colWidths=[None] * (len(cols) - 1) + [1.0 * inch])
        t.setStyle(TableStyle([("ALIGN", (len(cols) - 1, 0), (-1, -1), "RIGHT"),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe])]))
        out.append(t)

    _unmatched("BANK DEPOSITS · NO MATCH", un_plaid,
               [("Date", lambda r: r.get("date") or "—"),
                ("Description", lambda r: r.get("merchant_name") or r.get("name") or "—"),
                ("Amount", lambda r: abs(float(r.get("amount") or 0)))])
    _unmatched("STRIPE PAYOUTS · NO MATCH", un_stripe,
               [("Arrival", lambda r: r.get("arrival_date") or "—"),
                ("Payout", lambda r: (r.get("stripe_payout_id") or "")[:18] + "…"),
                ("Amount", lambda r: float(r.get("amount") or 0))])
    return out


def _trial_balance_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                        Paragraph, Spacer, inch, meta):
    accounts = d.get("accounts") or []
    t = d.get("totals") or {}
    out = [Paragraph("TRIAL BALANCE", s["section"])]
    head = [Paragraph(h, s["th"]) for h in ("Code", "Account", "Type")] + \
           [Paragraph(h, s["thr"]) for h in ("Debits", "Credits", "Balance")]
    rows = [head]
    for a in accounts:
        rows.append([
            Paragraph(str(a.get("code")), s["rowind"]),
            Paragraph(str(a.get("name")), s["row"]),
            Paragraph(str(a.get("type")), s["rowind"]),
            money_cell(a.get("debits")), money_cell(a.get("credits")), money_cell(a.get("balance")),
        ])
    rows.append([Paragraph("", s["row"]), Paragraph("TOTALS", s["totlbl"]), Paragraph("", s["row"]),
                 money_cell(t.get("debits"), bold=True), money_cell(t.get("credits"), bold=True),
                 money_cell(t.get("difference"), bold=True)])
    tbl = Table(rows, colWidths=[0.6 * inch, None, 0.8 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (3, 0), (5, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, stripe]),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor(_INK)),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.08 * inch))
    balanced = bool(t.get("balanced"))
    out.append(Paragraph("✓ In balance — total debits equal total credits." if balanced
                         else "✗ OUT OF BALANCE — contact support.",
                         s["row"] if balanced else s["danger"]))
    return out


def _general_ledger_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                         Paragraph, Spacer, inch, meta):
    out = []
    for acct in (d.get("accounts") or []):
        out.append(Paragraph(f"{acct.get('code')} — {acct.get('name')}", s["section"]))
        head = [Paragraph(h, s["th"]) for h in ("Date", "Source", "Memo")] + \
               [Paragraph(h, s["thr"]) for h in ("Debit", "Credit", "Balance")]
        rows = [head,
                [Paragraph("", s["rowind"]), Paragraph("Opening balance", s["rowind"]),
                 Paragraph("", s["rowind"]), Paragraph("", s["amt"]), Paragraph("", s["amt"]),
                 money_cell(acct.get("opening_balance"))]]
        for e in (acct.get("entries") or []):
            rows.append([
                Paragraph(str(e.get("date") or ""), s["rowind"]),
                Paragraph(str(e.get("source_type") or "").replace("_", " "), s["rowind"]),
                Paragraph(str(e.get("memo") or "")[:48], s["rowind"]),
                money_cell(e.get("debit")), money_cell(e.get("credit")),
                money_cell(e.get("running_balance")),
            ])
        rows.append([Paragraph("", s["rowind"]), Paragraph("Closing balance", s["totlbl"]),
                     Paragraph("", s["rowind"]), Paragraph("", s["amt"]), Paragraph("", s["amt"]),
                     money_cell(acct.get("closing_balance"), bold=True)])
        tbl = Table(rows, colWidths=[0.8 * inch, 1.1 * inch, None, 0.85 * inch, 0.85 * inch, 1.0 * inch],
                    repeatRows=1)
        tbl.setStyle(TableStyle([
            ("ALIGN", (3, 0), (5, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
            ("ROWBACKGROUNDS", (0, 2), (-1, -2), [colors.white, stripe]),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, rule),
        ]))
        out.append(tbl)
        if acct.get("truncated"):
            out.append(Paragraph("… additional entries truncated; export CSV for the full account.",
                                 s["note"]))
        out.append(Spacer(1, 0.12 * inch))
    if not out:
        out.append(Paragraph("No ledger activity in this window.", s["row"]))
    return out


def _summary_1099_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                       Paragraph, Spacer, inch, meta):
    rows_data = d.get("rows") or []
    out = [Paragraph(f"1099 SUMMARY — {d.get('year')}", s["section"])]
    head = [Paragraph(h, s["th"]) for h in ("Contractor / Vendor", "Payments", "1099 handling")] + \
           [Paragraph("Total Paid", s["thr"])]
    rows = [head]
    for r in rows_data:
        handling = "Stripe Tax Reporting" if r.get("stripe_managed") else \
            ("Manual 1099 needed" if r.get("reaches_threshold") else "Below $600 threshold")
        style = s["drl"] if (r.get("reaches_threshold") and not r.get("stripe_managed")) else s["row"]
        rows.append([
            Paragraph(str(r.get("name")), s["row"]),
            Paragraph(str(r.get("payments")), s["rowind"]),
            Paragraph(handling, style),
            money_cell(r.get("total_paid")),
        ])
    rows.append([Paragraph("TOTAL", s["totlbl"]), Paragraph("", s["row"]),
                 Paragraph("", s["row"]), money_cell(d.get("total_paid"), bold=True)])
    t = Table(rows, colWidths=[None, 0.8 * inch, 1.7 * inch, 1.1 * inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, stripe]),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor(_INK)),
    ]))
    out.append(t)
    out.append(Spacer(1, 0.1 * inch))
    out.append(Paragraph(d.get("note") or "", s["note"]))
    return out


def _generic_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                  Paragraph, Spacer, inch, meta):
    return [Paragraph("Report data:", s["section"]),
            Paragraph(str(d)[:4000], s["row"])]


def _breakdown_table(title, head_label, rows_data, key, s, money_cell, stripe, rule,
                     colors, Table, TableStyle, Paragraph, Spacer, inch):
    """Two-column breakdown table (label, amount) used by the I.8 reports."""
    out = [Paragraph(title, s["section"])]
    head = [Paragraph(head_label, s["th"]), Paragraph("Amount", s["thr"])]
    rows = [head]
    for r in rows_data:
        rows.append([Paragraph(str(r.get(key)), s["row"]), money_cell(r.get("amount"))])
    if not rows_data:
        rows.append([Paragraph("(none)", s["rowind"]), money_cell(0)])
    tbl = Table(rows, colWidths=[None, 1.2 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.12 * inch))
    return out


def _revenue_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                  Paragraph, Spacer, inch, meta):
    out = [Paragraph("TOTAL REVENUE", s["section"]),
           Paragraph(fmt_money(d.get("total_revenue")), s["kpi"] if "kpi" in s else s["section"]),
           Spacer(1, 0.12 * inch)]
    args = (s, money_cell, stripe, rule, colors, Table, TableStyle, Paragraph, Spacer, inch)
    out += _breakdown_table("BY ACCOUNT", "Account",
                            [{"label": str(a.get("code")) + "  " + str(a.get("name")),
                              "amount": a.get("amount")} for a in d.get("by_account") or []],
                            "label", *args)
    out += _breakdown_table("BY SOURCE", "Source", d.get("by_source") or [], "source", *args)
    out += _breakdown_table("BY CUSTOMER", "Customer", d.get("by_customer") or [], "customer", *args)
    out += _breakdown_table("BY OFFERING", "Offering / Category", d.get("by_offering") or [],
                            "offering", *args)
    out += _breakdown_table("BY MONTH", "Month", d.get("monthly") or [], "month", *args)
    return out


def _expenses_detail_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                          TableStyle, Paragraph, Spacer, inch, meta):
    out = [Paragraph("TOTAL EXPENSES", s["section"]),
           Paragraph(fmt_money(d.get("total_expenses")), s["kpi"] if "kpi" in s else s["section"]),
           Spacer(1, 0.12 * inch)]
    args = (s, money_cell, stripe, rule, colors, Table, TableStyle, Paragraph, Spacer, inch)
    out += _breakdown_table("BY ACCOUNT", "Account",
                            [{"label": str(a.get("code")) + "  " + str(a.get("name")),
                              "amount": a.get("amount")} for a in d.get("by_account") or []],
                            "label", *args)
    out += _breakdown_table("BY VENDOR", "Vendor", d.get("by_vendor") or [], "vendor", *args)
    out += _breakdown_table("BY SUBCATEGORY", "Subcategory", d.get("by_subcategory") or [],
                            "subcategory", *args)
    out += _breakdown_table("BY MONTH", "Month", d.get("monthly") or [], "month", *args)
    return out


def _customer_statement_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                             TableStyle, Paragraph, Spacer, inch, meta):
    contact = d.get("contact") or {}
    t = d.get("totals") or {}
    out = [Paragraph("STATEMENT FOR", s["section"]),
           Paragraph(str(contact.get("name") or "—"), s["row"]),
           Spacer(1, 0.10 * inch)]
    head = [Paragraph(h, s["th"]) for h in ("Date", "Ref", "Description")] +            [Paragraph(h, s["thr"]) for h in ("Amount", "Balance")]
    rows = [head]
    for l in d.get("lines") or []:
        rows.append([Paragraph(str(l.get("date")), s["rowind"]),
                     Paragraph(str(l.get("ref")), s["rowind"]),
                     Paragraph(str(l.get("description")), s["row"]),
                     money_cell(l.get("amount")), money_cell(l.get("balance"))])
    rows.append([Paragraph("", s["row"]), Paragraph("", s["row"]),
                 Paragraph("BALANCE DUE", s["totlbl"]),
                 Paragraph("", s["row"]), money_cell(t.get("balance"), bold=True)])
    tbl = Table(rows, colWidths=[0.9 * inch, 0.9 * inch, None, 1.0 * inch, 1.0 * inch],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (3, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, stripe]),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor(_INK)),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.12 * inch))
    aging = d.get("aging") or {}
    out += [Paragraph("AGING (OUTSTANDING)", s["section"])]
    ahead = [Paragraph(h, s["thr"]) for h in ("Current", "1-30", "31-60", "61-90", "90+")]
    atbl = Table([ahead, [money_cell(aging.get(k)) for k in
                          ("current", "d1_30", "d31_60", "d61_90", "d90_plus")]],
                 colWidths=[1.1 * inch] * 5)
    atbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                              ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule)]))
    out.append(atbl)
    return out


def _budget_vs_actual_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                           TableStyle, Paragraph, Spacer, inch, meta):
    out = [Paragraph("BUDGET VS ACTUAL", s["section"])]
    head = [Paragraph("Category", s["th"]), Paragraph("Source", s["th"])] + \
           [Paragraph(h, s["thr"]) for h in ("Actual", "Budget", "Variance")]
    rows = [head]
    for r in d.get("rows") or []:
        src = {"set": "set", "profit_first": "Profit-First %"}.get(r.get("budget_source") or "", "—")
        rows.append([Paragraph(str(r.get("label")), s["row"]),
                     Paragraph(src, s["rowind"]),
                     money_cell(r.get("actual")), money_cell(r.get("budget")),
                     money_cell(r.get("variance"))])
    tbl = Table(rows, colWidths=[None, 1.1 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (2, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    return out


def _profitability_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                        TableStyle, Paragraph, Spacer, inch, meta):
    out = [Paragraph("PROFITABILITY (CONTRIBUTION)", s["section"])]
    for title, key, rows_data in (("BY CUSTOMER", "customer", d.get("by_customer") or []),
                                  ("BY OFFERING", "offering", d.get("by_offering") or [])):
        out.append(Paragraph(title, s["section"]))
        head = [Paragraph("Name", s["th"])] + \
               [Paragraph(h, s["thr"]) for h in ("Revenue", "Share %", "Overhead", "Contribution")]
        rows = [head]
        for r in rows_data:
            rows.append([Paragraph(str(r.get(key)), s["row"]),
                         money_cell(r.get("revenue")),
                         Paragraph(f"{r.get('revenue_share_pct', 0)}%", s["rowind"]),
                         money_cell(r.get("allocated_overhead")),
                         money_cell(r.get("contribution"))])
        tbl = Table(rows, colWidths=[None, 1.0 * inch, 0.7 * inch, 1.0 * inch, 1.0 * inch],
                    repeatRows=1)
        tbl.setStyle(TableStyle([
            ("ALIGN", (1, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
        ]))
        out.append(tbl)
        out.append(Spacer(1, 0.10 * inch))
    out.append(Paragraph(str(d.get("method") or ""), s["row"]))
    return out


def _trends_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                 TableStyle, Paragraph, Spacer, inch, meta):
    out = [Paragraph("TRAILING 12 MONTHS", s["section"])]
    head = [Paragraph("Month", s["th"])] + \
           [Paragraph(h, s["thr"]) for h in ("Revenue", "Expenses", "Net")]
    rows = [head]
    for m in d.get("monthly") or []:
        rows.append([Paragraph(str(m.get("month")), s["rowind"]),
                     money_cell(m.get("revenue")), money_cell(m.get("expenses")),
                     money_cell(m.get("net"))])
    tbl = Table(rows, colWidths=[None, 1.1 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (3, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    return out


def _kv_table(pairs, s, money_cell, stripe, rule, colors, Table, TableStyle, Paragraph, inch):
    rows = [[Paragraph(str(k), s["row"]), money_cell(v)] for k, v in pairs]
    tbl = Table(rows, colWidths=[None, 1.3 * inch])
    tbl.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"),
                             ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, stripe])]))
    return tbl


def _trust_reconciliation_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                               TableStyle, Paragraph, Spacer, inch, meta):
    tw = d.get("three_way") or {}
    ok = bool(tw.get("ledger_in_balance")) and bool(tw.get("matches_bank"))
    out = [Paragraph("THREE-WAY RECONCILIATION", s["section"]),
           _kv_table([("GL Trust Cash (1200)", tw.get("gl_trust_cash")),
                      ("Client Trust Funds Liability (2200)", tw.get("client_funds_liability")),
                      ("Bank Trust Balance", tw.get("bank_trust_balance"))],
                     s, money_cell, stripe, rule, colors, Table, TableStyle, Paragraph, inch),
           Spacer(1, 0.06 * inch),
           Paragraph("✓ All three balances agree." if ok
                     else "✗ BALANCES DO NOT AGREE — investigate before filing.",
                     s["row"] if ok else s["danger"]),
           Spacer(1, 0.12 * inch),
           Paragraph("PER-CLIENT SUB-BALANCES", s["section"])]
    head = [Paragraph("Client", s["th"])] + \
           [Paragraph(h, s["thr"]) for h in ("Deposits", "Disbursements", "Balance")]
    rows = [head]
    for c in d.get("by_client") or []:
        rows.append([Paragraph(str(c.get("client")), s["row"]),
                     money_cell(c.get("deposits")), money_cell(c.get("disbursements")),
                     money_cell(c.get("balance"))])
    if d.get("opening_plug"):
        rows.append([Paragraph("(pre-history client funds)", s["rowind"]),
                     Paragraph("", s["row"]), Paragraph("", s["row"]),
                     money_cell(d.get("opening_plug"))])
    tbl = Table(rows, colWidths=[None, 1.1 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (3, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.12 * inch))
    out.append(Paragraph("TRUST ACTIVITY", s["section"]))
    head2 = [Paragraph(h, s["th"]) for h in ("Date", "Description", "Type", "Client")] + \
            [Paragraph("Amount", s["thr"])]
    rows2 = [head2]
    for a in (d.get("activity") or [])[:120]:
        rows2.append([Paragraph(str(a.get("date")), s["rowind"]),
                      Paragraph(str(a.get("description"))[:48], s["row"]),
                      Paragraph(str(a.get("type")), s["rowind"]),
                      Paragraph(str(a.get("client") or "—"), s["rowind"]),
                      money_cell(a.get("amount"))])
    tbl2 = Table(rows2, colWidths=[0.8 * inch, None, 0.95 * inch, 1.2 * inch, 0.9 * inch],
                 repeatRows=1)
    tbl2.setStyle(TableStyle([
        ("ALIGN", (4, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl2)
    out.append(Spacer(1, 0.08 * inch))
    out.append(Paragraph(str(d.get("note") or ""), s["row"]))
    return out


def _donors_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                 Paragraph, Spacer, inch, meta):
    out = [Paragraph("GIFTS", s["section"]),
           _kv_table([("Total gifts", d.get("total_gifts")),
                      ("Restricted", d.get("restricted_gifts")),
                      ("Unrestricted", d.get("unrestricted_gifts"))],
                     s, money_cell, stripe, rule, colors, Table, TableStyle, Paragraph, inch),
           Spacer(1, 0.12 * inch),
           Paragraph(f"BY {str(d.get('donor_label') or 'Donor').upper()}", s["section"])]
    head = [Paragraph(str(d.get("donor_label") or "Donor"), s["th"])] + \
           [Paragraph(h, s["thr"]) for h in ("Gifts", "Total", "Restricted")]
    rows = [head]
    for dn in d.get("donors") or []:
        rows.append([Paragraph(str(dn.get("donor")), s["row"]),
                     Paragraph(str(dn.get("gifts")), s["rowind"]),
                     money_cell(dn.get("total")), money_cell(dn.get("restricted"))])
    tbl = Table(rows, colWidths=[None, 0.7 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (3, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.08 * inch))
    out.append(Paragraph(str(d.get("note") or ""), s["row"]))
    return out


def _prep_990_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                   Paragraph, Spacer, inch, meta):
    out = [Paragraph(f"990 PREP — {d.get('year')}", s["section"])]
    for title, key, lk, vk in (("CONTRIBUTIONS / INCOME", "contributions", "name", "amount"),
                               ("FUNCTIONAL EXPENSE PREP (PROFIT-FIRST BUCKETS)",
                                "functional_expenses", "bucket", "amount"),
                               ("NET ASSETS", "net_assets", "name", "balance")):
        out.append(Paragraph(title, s["section"]))
        out.append(_kv_table([(r.get(lk), r.get(vk)) for r in d.get(key) or []],
                             s, money_cell, stripe, rule, colors, Table, TableStyle,
                             Paragraph, inch))
        out.append(Spacer(1, 0.08 * inch))
    out.append(_kv_table([("CHANGE IN NET ASSETS", d.get("change_in_net_assets"))],
                         s, money_cell, stripe, rule, colors, Table, TableStyle,
                         Paragraph, inch))
    out.append(Spacer(1, 0.08 * inch))
    for f in d.get("sme_flags") or []:
        out.append(Paragraph("⚑ " + str(f), s["row"]))
    return out


def _bank_reconciliation_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
                              TableStyle, Paragraph, Spacer, inch, meta):
    out = [Paragraph("BANK RECONCILIATION", s["section"])]
    head = [Paragraph("Account", s["th"])] + \
           [Paragraph(h, s["thr"]) for h in ("Beginning", "Deposits", "Withdrawals", "Ending")]
    rows = [head]
    for a in d.get("accounts") or []:
        label = f"{a.get('name')} ••{a.get('mask')}" + (" (TRUST)" if a.get("is_trust_account") else "")
        rows.append([Paragraph(label, s["row"]), money_cell(a.get("beginning_balance")),
                     money_cell(a.get("deposits")), money_cell(a.get("withdrawals")),
                     money_cell(a.get("ending_balance"))])
    tbl = Table(rows, colWidths=[None, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.08 * inch))
    gl = d.get("gl_cash") or {}
    if gl:
        out.append(_kv_table([("GL Operating Cash (1000)", gl.get("operating_1000")),
                              ("GL Trust Cash (1200)", gl.get("trust_1200")),
                              ("Bank operating ending total", d.get("operating_ending_total"))],
                             s, money_cell, stripe, rule, colors, Table, TableStyle,
                             Paragraph, inch))
        out.append(Spacer(1, 0.06 * inch))
    out.append(Paragraph(str(d.get("note") or ""), s["row"]))
    return out


def _audit_trail_body(d, s, money_cell, accent, stripe, rule, danger, colors, Table, TableStyle,
                      Paragraph, Spacer, inch, meta):
    out = [Paragraph("CLOSED-PERIOD EDIT AUDIT TRAIL", s["section"])]
    head = [Paragraph(h, s["th"]) for h in ("When", "Source", "By", "Reason")]
    rows = [head]
    for e in d.get("entries") or []:
        reason = str(e.get("reason"))[:90]
        change = str(e.get("change") or "")[:140]
        body = reason + (f"<br/><font size=6 color=grey>{change}</font>" if change else "")
        rows.append([Paragraph(str(e.get("at"))[:19].replace("T", " "), s["rowind"]),
                     Paragraph(f"{e.get('source_type')} {str(e.get('source_id'))[:12]}", s["rowind"]),
                     Paragraph(str(e.get("by_role")), s["rowind"]),
                     Paragraph(body, s["row"])])
    if not (d.get("entries") or []):
        rows.append([Paragraph("(no closed-period edits on record)", s["rowind"]),
                     Paragraph("", s["row"]), Paragraph("", s["row"]), Paragraph("", s["row"])])
    tbl = Table(rows, colWidths=[1.3 * inch, 1.7 * inch, 0.9 * inch, None], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(tbl)
    return out


def register_builder(key: str, builder) -> None:
    """Public hook: a vertical module (e.g. superbill.py) registers its
    body builder without this module importing it — same signature as
    the builders below."""
    _BUILDERS[key] = builder


_BUILDERS = {
    "balance_sheet": _balance_sheet_body,
    "pl": _pl_body,
    "ar_aging": _ar_body,
    "ap_aging": _ap_body,
    "cash_flow": _cash_flow_body,
    "reconciliation": _reconciliation_body,
    "trial_balance": _trial_balance_body,
    "general_ledger": _general_ledger_body,
    "summary_1099": _summary_1099_body,
    "revenue": _revenue_body,
    "expenses_detail": _expenses_detail_body,
    "customer_statement": _customer_statement_body,
    "budget_vs_actual": _budget_vs_actual_body,
    "profitability": _profitability_body,
    "trends": _trends_body,
    "trust_reconciliation": _trust_reconciliation_body,
    "donors": _donors_body,
    "prep_990": _prep_990_body,
    "bank_reconciliation": _bank_reconciliation_body,
    "audit_trail": _audit_trail_body,
}
