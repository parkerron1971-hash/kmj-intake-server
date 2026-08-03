"""
ledger_report.py — THE ACTION LEDGER: the artifact you can hand to
someone who will never have a login.

A licensing board, an insurer, an accountant, opposing counsel — none of
them get a Solutionist account, and a portal they cannot open is not a
proof. This module produces a document that travels: the chain's state,
the range it covers, the erasures on record, and the actions themselves.

THE RULE, AGAIN: report, never reassure. The report states what the
check found and lets the reader conclude. It carries no verdict language
beyond the facts, it declares rows that predate the hash chain as
unprovable rather than counting them as clean, and it prints the reasons
for gaps rather than smoothing them over. A document that argues its own
innocence is worth less than one that simply shows its work.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ledger_report")

REPORT_KEY = "ledger_verification"
REPORT_TITLE = "Action Ledger — Verification Report"


def build(biz_row: Dict[str, Any], *, limit: int = 500,
          since: Optional[str] = None, until: Optional[str] = None,
          include_db: bool = True) -> Dict[str, Any]:
    """Assemble the report payload.

    include_db defaults TRUE here, unlike the History screen: an auditor
    wants the provable tier (the database's own before/after record of
    every change), not the readable summary.
    """
    import audit_log
    biz = str(biz_row.get("id") or "")
    verification = audit_log.verification_report(biz)
    entries = audit_log.ledger_entries(
        biz, limit=limit, include_db=include_db, since=since, until=until)
    return {
        "report": REPORT_KEY,
        "business_id": biz,
        "business_name": biz_row.get("name") or "Business",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "range": {"since": since, "until": until, "limit": limit},
        "verification": verification,
        "entries": entries,
        "entry_count": len(entries),
    }


def _verdict_line(v: Dict[str, Any]) -> str:
    """One sentence of fact. Never 'everything looks fine'."""
    if v.get("hashed", 0) == 0:
        return ("No record in this ledger carries a cryptographic fingerprint "
                "yet, so nothing here can be proven unaltered either way.")
    if v.get("intact"):
        return (f"{v.get('hashed')} records carry fingerprints and each one "
                "matches. Altering any of them would break every record after it.")
    return (f"Record #{v.get('broken_at')} does not match its own fingerprint. "
            f"{v.get('reason') or ''}").strip()


# ─── CSV ─────────────────────────────────────────────────────────────

def csv_rows(data: Dict[str, Any]) -> List[List[Any]]:
    v = data.get("verification") or {}
    rows: List[List[Any]] = [
        ["Action Ledger — Verification Report"],
        ["Business", data.get("business_name")],
        ["Generated at (UTC)", data.get("generated_at")],
        [],
        ["Chain state"],
        ["Records in range", v.get("checked")],
        ["Carrying a fingerprint", v.get("hashed")],
        ["First sequence", v.get("first_sequence")],
        ["Last sequence", v.get("last_sequence")],
        ["Unprovable (predate the chain)", v.get("unverifiable_rows")],
        ["Broken at", v.get("broken_at") if v.get("broken_at") is not None else "—"],
        ["Finding", _verdict_line(v)],
    ]
    gaps = v.get("gaps") or []
    if gaps:
        rows += [[], ["Sequence gaps after"], *[[f"#{g}"] for g in gaps]]
    erasures = v.get("erasures") or []
    if erasures:
        rows += [[], ["Erasures on record"],
                 ["When", "Records removed", "From", "To", "Reason"]]
        for e in erasures:
            rows.append([e.get("erased_at"), e.get("rows_erased"),
                         e.get("first_sequence"), e.get("last_sequence"),
                         e.get("reason")])
    rows += [[], ["Actions"],
             ["Seq", "When (UTC)", "Actor", "Action", "Outcome",
              "Permitted by", "Touched", "Detail"]]
    for e in data.get("entries") or []:
        refs = "; ".join(f"{r.get('type')}:{r.get('id')}"
                         for r in (e.get("subject_refs") or [])
                         if isinstance(r, dict))
        rows.append([
            e.get("sequence"), e.get("created_at"),
            e.get("actor_id") or e.get("actor_type"), e.get("verb"),
            "ok" if e.get("ok") else "FAILED",
            e.get("authorized_by") or "", refs,
            (e.get("error") or e.get("summary") or "")[:200],
        ])
    return rows


def to_csv(data: Dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in csv_rows(data):
        w.writerow(r)
    return buf.getvalue()


# ─── PDF ─────────────────────────────────────────────────────────────
# Registered through pdf_reports.register_builder so pdf_reports never
# has to import this module. Positional signature is fixed by that
# module's contract.

def _body(d, s, money_cell, accent, stripe, rule, danger, colors, Table,
          TableStyle, Paragraph, Spacer, inch, meta):
    v = d.get("verification") or {}
    out = [Paragraph("CHAIN STATE", s["section"])]

    intact = bool(v.get("intact")) and v.get("hashed", 0) > 0
    out.append(Paragraph(_verdict_line(v), s["danger"] if not intact else s["row"]))
    out.append(Spacer(1, 8))

    facts = [
        ["Records in range", str(v.get("checked", 0))],
        ["Carrying a fingerprint", str(v.get("hashed", 0))],
        ["Sequence range",
         f"#{v.get('first_sequence')} – #{v.get('last_sequence')}"
         if v.get("first_sequence") is not None else "—"],
    ]
    if v.get("unverifiable_rows"):
        facts.append(["Cannot be proven",
                      f"{v['unverifiable_rows']} (recorded before the chain began)"])
    if v.get("gaps"):
        facts.append(["Sequence gaps after",
                      ", ".join(f"#{g}" for g in v["gaps"])])
    t = Table([[Paragraph(a, s["row"]), Paragraph(b, s["row"])] for a, b in facts],
              colWidths=[2.4 * inch, None])
    t.setStyle(TableStyle([("ROWBACKGROUNDS", (0, 0), (-1, -1),
                            [colors.white, stripe])]))
    out += [t, Spacer(1, 12)]

    erasures = v.get("erasures") or []
    if erasures:
        out.append(Paragraph("ERASURES ON RECORD", s["section"]))
        head = [Paragraph(h, s["th"]) for h in
                ("When", "Records removed", "Range", "Reason")]
        rows = [head]
        for e in erasures:
            rng = (f"#{e.get('first_sequence')}–#{e.get('last_sequence')}"
                   if e.get("first_sequence") is not None else "—")
            rows.append([
                Paragraph(str(e.get("erased_at") or "")[:19], s["row"]),
                Paragraph(str(e.get("rows_erased") or 0), s["row"]),
                Paragraph(rng, s["row"]),
                Paragraph(str(e.get("reason") or ""), s["row"]),
            ])
        et = Table(rows, colWidths=[1.5 * inch, 1.2 * inch, 1.2 * inch, None],
                   repeatRows=1)
        et.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
        ]))
        out += [et, Paragraph(
            "A deletion request removes records permanently. The gap it leaves is "
            "deliberate and stays visible — it is not evidence of tampering, and it "
            "is not hidden either.", s["note"]), Spacer(1, 12)]

    out.append(Paragraph("ACTIONS", s["section"]))
    head = [Paragraph(h, s["th"]) for h in
            ("Seq", "When (UTC)", "Actor", "Action", "Permitted by", "Outcome")]
    rows = [head]
    for e in (d.get("entries") or [])[:400]:
        rows.append([
            Paragraph(str(e.get("sequence") or ""), s["row"]),
            Paragraph(str(e.get("created_at") or "")[:19], s["row"]),
            Paragraph(str(e.get("actor_id") or e.get("actor_type") or ""), s["row"]),
            Paragraph(str(e.get("verb") or ""), s["row"]),
            Paragraph(str(e.get("authorized_by") or ""), s["row"]),
            Paragraph("ok" if e.get("ok") else "FAILED",
                      s["row"] if e.get("ok") else s["danger"]),
        ])
    at = Table(rows, colWidths=[0.5 * inch, 1.4 * inch, 1.0 * inch, 1.5 * inch,
                                1.5 * inch, None], repeatRows=1)
    at.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, stripe]),
    ]))
    out.append(at)
    if len(d.get("entries") or []) > 400:
        out.append(Paragraph(
            f"Showing the first 400 of {d.get('entry_count')} records. "
            "Export CSV for the complete range — a truncated table must never "
            "be mistaken for a complete one.", s["note"]))
    return out


def to_pdf(data: Dict[str, Any], biz_row: Dict[str, Any],
           generated_by: str = "") -> bytes:
    """Branded PDF. Raises ImportError when reportlab is absent; every
    caller falls back to CSV (the house pattern)."""
    import pdf_reports
    pdf_reports.register_builder(REPORT_KEY, _body)
    v = data.get("verification") or {}
    rng = data.get("range") or {}
    period = "Full ledger"
    if rng.get("since") or rng.get("until"):
        period = f"{(rng.get('since') or 'start')[:10]} → {(rng.get('until') or 'now')[:10]}"
    meta = pdf_reports.build_meta(
        business_name=data.get("business_name") or "Business",
        settings=biz_row.get("settings"),
        report_title=REPORT_TITLE,
        period_label=period,
        basis_label=f"{v.get('hashed', 0)} of {v.get('checked', 0)} records fingerprinted",
        generated_by=generated_by,
        notes=("This report is generated from an append-only ledger. The "
               "database refuses edits and deletions to it; deletions made "
               "under a data-erasure request leave a visible, recorded gap."),
        confidential=True)
    return pdf_reports.render(REPORT_KEY, data, meta)
