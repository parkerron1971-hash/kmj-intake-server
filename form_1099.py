"""
form_1099.py — Rails Arc 2 — draft 1099-NEC PDFs.

DRAFTS, not filings (ruling: we are the prep tool, never the filer).
The output is deliberately NOT a facsimile of the official IRS form:
the IRS red-ink Copy A is scannable stock that must never be printed
from software like this, and imitating it would invite exactly the
confusion the disclaimer exists to prevent. This renders every field a
preparer needs to transcribe onto real forms (or hand to a filing
service): payer block, recipient block from the W-9 profile, and Box 1
nonemployee compensation — under a DRAFT watermark and a
"bookkeeping software, not a CPA" footer.
"""
from __future__ import annotations

import io
from typing import Any, Dict


DISCLAIMER = (
    "DRAFT prepared by Solutionist System, bookkeeping software — not a CPA, "
    "not tax advice, and not an official IRS form. Verify every figure with "
    "your tax professional and file using official forms or an authorized "
    "e-file provider. Copy A of Form 1099-NEC must never be printed from "
    "this document."
)


def build_draft_pdf(payer: Dict[str, Any], recipient: Dict[str, Any],
                    year: int, box1_amount: float) -> bytes:
    """One draft 1099-NEC page.

    payer:     {name, ein, line1, line2, city_state_zip, phone}
    recipient: {name, tin_display, line1, line2, city_state_zip}
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as _canvas

    buf = io.BytesIO()
    c = _canvas.Canvas(buf, pagesize=letter)
    W, H = letter

    # ── DRAFT watermark ────────────────────────────────────────────
    c.saveState()
    c.setFont("Helvetica-Bold", 96)
    c.setFillColor(colors.Color(0.85, 0.85, 0.85, alpha=0.5))
    c.translate(W / 2, H / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "DRAFT")
    c.restoreState()

    # ── Header ─────────────────────────────────────────────────────
    y = H - 0.9 * inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.9 * inch, y, f"Form 1099-NEC — {year}")
    c.setFont("Helvetica", 10)
    c.drawString(0.9 * inch, y - 16, "Nonemployee Compensation — PREPARATION DRAFT")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(W - 0.9 * inch, y, "DRAFT — DO NOT FILE")

    def _block(x: float, top: float, w: float, h: float, title: str,
               lines: list[str]) -> None:
        c.setStrokeColor(colors.Color(0.4, 0.4, 0.4))
        c.setLineWidth(0.8)
        c.rect(x, top - h, w, h)
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.Color(0.35, 0.35, 0.35))
        c.drawString(x + 6, top - 12, title.upper())
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 10.5)
        ly = top - 27
        for line in lines:
            if line:
                c.drawString(x + 6, ly, str(line)[:70])
                ly -= 14

    # ── Payer / recipient blocks ───────────────────────────────────
    top = y - 40
    _block(0.9 * inch, top, 3.3 * inch, 1.5 * inch, "Payer",
           [payer.get("name"), payer.get("line1"), payer.get("line2"),
            payer.get("city_state_zip"), payer.get("phone")])
    _block(4.4 * inch, top, 3.3 * inch, 1.5 * inch, "Payer's TIN (EIN)",
           [payer.get("ein") or "— add your EIN in the 1099 panel —"])

    top2 = top - 1.5 * inch - 18
    _block(0.9 * inch, top2, 3.3 * inch, 1.5 * inch, "Recipient",
           [recipient.get("name"), recipient.get("line1"), recipient.get("line2"),
            recipient.get("city_state_zip")])
    _block(4.4 * inch, top2, 3.3 * inch, 1.5 * inch, "Recipient's TIN",
           [recipient.get("tin_display") or "— no W-9 on file —"])

    # ── Box 1 ──────────────────────────────────────────────────────
    top3 = top2 - 1.5 * inch - 18
    _block(0.9 * inch, top3, 3.3 * inch, 0.9 * inch,
           "Box 1 — Nonemployee compensation",
           [f"$ {box1_amount:,.2f}"])
    _block(4.4 * inch, top3, 3.3 * inch, 0.9 * inch,
           "Box 4 — Federal income tax withheld",
           ["$ 0.00  (backup withholding not tracked)"])

    # ── Disclaimer footer ──────────────────────────────────────────
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.Color(0.3, 0.3, 0.3))
    footer_y = 1.0 * inch
    words = DISCLAIMER.split()
    line, lines = "", []
    for w_ in words:
        if len(line) + len(w_) + 1 > 110:
            lines.append(line)
            line = w_
        else:
            line = f"{line} {w_}".strip()
    lines.append(line)
    for i, l in enumerate(lines):
        c.drawString(0.9 * inch, footer_y - i * 10, l)

    c.showPage()
    c.save()
    return buf.getvalue()
