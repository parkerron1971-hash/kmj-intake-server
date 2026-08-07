"""
superbill.py — therapist superbills (vertical completion: the last
NOT-COVERED readiness cell).

A superbill is a BILLING artifact: the statement a private-pay client
submits to their insurer for out-of-network reimbursement. It is inside
the platform's posture for the therapist vertical (scheduling, billing
and admin only — see vertical_registry.py + vertical_scope.py) PROVIDED
no clinical data is ever stored, and this module enforces that line
rather than documenting it:

  * NO diagnosis codes. There is no diagnosis field anywhere — not
    stored, not rendered, not accepted as input. The rendered statement
    carries a BLANK "Diagnosis (completed by provider)" line for the
    therapist to fill in BY HAND after download. That blank line is the
    deliberate design, and the UI says so.
  * NO session content, notes, or modality. The sessions query selects
    exactly date/title/duration/status — never `notes`, never
    `session_type`. The statement shows: practitioner block, client
    name/contact, per-session rows (date, service description +
    optional procedure code, fee, amount paid), totals. Nothing else.
  * A hard TABLE ALLOWLIST. Every read this module makes goes through
    _read(), which refuses any table outside ALLOWED_TABLES — and the
    recording test (__tests__/test_superbill.py, the PR #352 pattern)
    fails if a query ever reaches beyond it.

PROCEDURE CODES are operator-entered free text kept in
businesses.settings.superbill.service_codes keyed by offering id (the
offerings table has no jsonb column, and this needs no SQL). The
platform never ships a procedure-code library: CPT is licensed by the
AMA, so we render exactly what the practitioner types and nothing more.

PAYMENT-LINKAGE RULE (documented because the linkage is loose):
sessions carry no invoice reference and invoices carry no session
reference. So:
  * A session counts as RENDERED if it falls in the requested window,
    is not in the future, and its status is neither cancelled nor
    no_show.
  * Its FEE is the current price of the offering whose name matches the
    session title (bookings mirror the offering name into the session
    title), else settings.superbill.default_fee, else unpriced (shown
    as missing, never invented).
  * PAID amounts come from the client's PAID invoices whose paid_at
    falls inside the same window (minus refunds), pooled and allocated
    to sessions oldest-first, capped at each session's fee. Honest
    approximation, stated on the statement itself.

TIN discipline: the practitioner block includes the practice EIN/tax id
the owner typed for this exact purpose. The platform treats TIN-class
data as owner-only (contractors_router tax-profile, the 1099 draft PDF)
— so superbill config AND generation endpoints are OWNER-ONLY in
reports_router.py, matching that rule.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import sb_clients
import vertical_registry

# ─── The wall ────────────────────────────────────────────────────────
# Every table this module may read. Widening this set is a deliberate,
# reviewable act — the recording test pins it, and _read() enforces it
# at runtime so a stray query fails closed in production too.
ALLOWED_TABLES = frozenset({
    "businesses",   # settings.superbill (practitioner block, codes) + type
    "contacts",     # client name / contact details
    "sessions",     # date, title, duration, status — never notes/type
    "invoices",     # paid amounts in the window
    "offerings",    # service names + prices (fee resolution)
})

# The blank line the provider completes by hand — the ONLY place the
# word "diagnosis" appears on the statement, and it is always empty.
DIAGNOSIS_BLANK_LINE = "Diagnosis (completed by provider):"

STATEMENT_NOTE = (
    "Superbill — statement for out-of-network reimbursement. Prepared from "
    "scheduling and billing records only; this platform stores no diagnosis "
    "codes and no clinical information. The provider completes the diagnosis "
    "line by hand. Amounts paid are allocated from payments received in the "
    "same period, oldest session first."
)


def _table_of(path: str) -> str:
    return (path or "").split("?", 1)[0].lstrip("/")


def _read(path: str) -> List[Dict[str, Any]]:
    """The single read seam. Refuses non-allowlisted tables — fail closed."""
    table = _table_of(path)
    if table not in ALLOWED_TABLES:
        raise ValueError(
            f"superbill module attempted to read '{table}' — outside the "
            f"scheduling/billing allowlist {sorted(ALLOWED_TABLES)}")
    return sb_clients.sb_get_as_service(path) or []


# ─── Vertical gate ───────────────────────────────────────────────────

def is_superbill_vertical(business_type: Optional[str]) -> bool:
    """Therapist family only (aliases included via the canonical registry)."""
    return vertical_registry.resolve(business_type or "") == "therapist"


def require_superbill_vertical(business_type: Optional[str]) -> None:
    if not is_superbill_vertical(business_type):
        raise HTTPException(
            403, "Superbills are a therapist-practice report — this business "
                 "type doesn't have them.")


def business_context(biz: str) -> Dict[str, Any]:
    rows = _read(f"/businesses?id=eq.{biz}&select=id,name,type,settings&limit=1")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


# ─── Practitioner block (businesses.settings.superbill) ──────────────

# field key → (label, max length). EIN/tax id is TIN-class: owner-only
# endpoints only, and it appears nowhere but the downloaded statement.
_PRACTITIONER_FIELDS: Dict[str, Tuple[str, int]] = {
    "practitioner_name": ("Practitioner", 120),
    "license_type":      ("License type", 40),      # e.g. LCSW, LMFT, LPC
    "license_number":    ("License #", 60),
    "npi":               ("NPI", 20),
    "ein":               ("Tax ID (EIN)", 20),
    "address":           ("Practice address", 240),
    "phone":             ("Phone", 40),
}

# Without these three an insurer will bounce the claim — the UI shows an
# honest setup state instead of generating an incomplete statement.
_REQUIRED_FIELDS = ("practitioner_name", "license_number", "npi")


def practitioner_info(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Practitioner block for a superbill.

    Reads only settings.superbill. The EIN is the same federal number the
    1099 panel and Foundation Phase 2 collect, but the fallback to the shared
    identity store happens in reports_router — this module's ALLOWED_TABLES
    wall stays exactly as narrow as it is, and a locally-saved EIN still wins
    (a practice can legitimately bill under a different TIN than the entity).
    """
    sp = ((settings or {}).get("superbill") or {})
    out = {k: str(sp.get(k) or "").strip() for k in _PRACTITIONER_FIELDS}
    out["complete"] = all(out[k] for k in _REQUIRED_FIELDS)
    out["missing"] = [k for k in _REQUIRED_FIELDS if not out[k]]
    return out


def get_config(biz: str) -> Dict[str, Any]:
    ctx = business_context(biz)
    require_superbill_vertical(ctx.get("type"))
    sp = ((ctx.get("settings") or {}).get("superbill") or {})
    offerings = _read(
        f"/offerings?business_id=eq.{biz}&is_active=eq.true"
        f"&select=id,name,current_price,duration_min&order=name.asc&limit=500")
    codes = sp.get("service_codes") or {}
    return {
        "ok": True,
        "practitioner": practitioner_info(ctx.get("settings")),
        "default_fee": sp.get("default_fee"),
        "service_codes": {k: v for k, v in codes.items() if isinstance(v, str)},
        "offerings": [{
            "id": o["id"], "name": o.get("name"),
            "current_price": o.get("current_price"),
            "duration_min": o.get("duration_min"),
            "procedure_code": codes.get(o["id"]) or "",
        } for o in offerings],
    }


def save_config(biz: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Merge practitioner info + service codes into settings.superbill.
    Codes are free text typed by the operator (no code library — see
    module docstring); everything is trimmed and length-capped."""
    ctx = business_context(biz)
    require_superbill_vertical(ctx.get("type"))
    settings = dict(ctx.get("settings") or {})
    sp = dict(settings.get("superbill") or {})

    for key, (_, cap) in _PRACTITIONER_FIELDS.items():
        if key in body:
            sp[key] = str(body.get(key) or "").strip()[:cap]

    if "default_fee" in body:
        raw = body.get("default_fee")
        if raw in (None, ""):
            sp.pop("default_fee", None)
        else:
            try:
                fee = round(float(raw), 2)
            except (TypeError, ValueError):
                raise HTTPException(400, "default_fee must be a number")
            if fee < 0:
                raise HTTPException(400, "default_fee must be non-negative")
            sp["default_fee"] = fee

    if "service_codes" in body:
        raw_codes = body.get("service_codes") or {}
        if not isinstance(raw_codes, dict):
            raise HTTPException(400, "service_codes must be a map of offering id → code")
        clean: Dict[str, str] = {}
        for oid, code in raw_codes.items():
            c = str(code or "").strip()[:20]
            if c:
                clean[str(oid)] = c
        sp["service_codes"] = clean

    settings["superbill"] = sp
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz}", {"settings": settings})
    return {"ok": True, "practitioner": practitioner_info(settings),
            "default_fee": sp.get("default_fee"),
            "service_codes": sp.get("service_codes") or {}}


# ─── Clients with sessions (picker source) ───────────────────────────

def list_clients(biz: str) -> List[Dict[str, Any]]:
    ctx = business_context(biz)
    require_superbill_vertical(ctx.get("type"))
    rows = _read(
        f"/sessions?business_id=eq.{biz}&contact_id=not.is.null"
        f"&select=contact_id&limit=10000")
    counts: Dict[str, int] = {}
    for r in rows:
        cid = r.get("contact_id")
        if cid:
            counts[cid] = counts.get(cid, 0) + 1
    if not counts:
        return []
    ids = list(counts.keys())
    contacts: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 100):   # chunk the in.() filter (URL sanity)
        chunk = ids[i:i + 100]
        contacts += _read(
            f"/contacts?id=in.({','.join(chunk)})&business_id=eq.{biz}"
            f"&select=id,name,email&limit=200")
    out = [{"contact_id": c["id"], "name": c.get("name") or "—",
            "email": c.get("email"), "sessions": counts.get(c["id"], 0)}
           for c in contacts]
    return sorted(out, key=lambda x: (x["name"] or "").lower())


# ─── Window parsing ──────────────────────────────────────────────────

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def window_bounds(month: Optional[str], date_from: Optional[str],
                  date_to: Optional[str]) -> Tuple[str, str]:
    """month='YYYY-MM' → that calendar month; else explicit from/to; else
    the current calendar month. Returns (from, to) as YYYY-MM-DD."""
    if month:
        m = _MONTH_RE.match(month.strip())
        if not m:
            raise HTTPException(400, "month must look like 2026-07")
        y, mo = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12):
            raise HTTPException(400, "month must look like 2026-07")
        start = date(y, mo, 1)
        end = (date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)) - timedelta(days=1)
        return start.isoformat(), end.isoformat()
    if date_from and date_to:
        try:
            f, t = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(400, "from/to must be YYYY-MM-DD")
        if t < f:
            raise HTTPException(400, "'to' is before 'from'")
        return f.isoformat(), t.isoformat()
    today = datetime.now(timezone.utc).date()
    return today.replace(day=1).isoformat(), today.isoformat()


def _norm_name(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ─── The statement itself ────────────────────────────────────────────

def build_superbill(biz: str, contact_id: str, month: Optional[str] = None,
                    date_from: Optional[str] = None,
                    date_to: Optional[str] = None) -> Dict[str, Any]:
    ctx = business_context(biz)
    require_superbill_vertical(ctx.get("type"))
    settings = ctx.get("settings") or {}
    sp = (settings.get("superbill") or {})
    w_from, w_to = window_bounds(month, date_from, date_to)

    crows = _read(f"/contacts?id=eq.{contact_id}&business_id=eq.{biz}"
                  f"&select=id,name,email,phone&limit=1")
    if not crows:
        raise HTTPException(404, "client not found")
    contact = crows[0]

    # Sessions in the window. Deliberately narrow select: date, title,
    # duration, status — NEVER notes and NEVER session_type (no session
    # content, no modality). Timestamps in the Z form (PostgREST rule).
    sessions = _read(
        f"/sessions?business_id=eq.{biz}&contact_id=eq.{contact_id}"
        f"&scheduled_for=gte.{w_from}T00:00:00Z"
        f"&scheduled_for=lte.{w_to}T23:59:59Z"
        f"&status=not.in.(cancelled,no_show)"
        f"&select=id,title,scheduled_for,duration_minutes,status"
        f"&order=scheduled_for.asc&limit=500")
    # Rendered means it happened: a still-future session never bills.
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sessions = [s for s in sessions if (s.get("scheduled_for") or "") <= now_iso]

    offerings = _read(
        f"/offerings?business_id=eq.{biz}"
        f"&select=id,name,current_price&limit=500")
    by_name = {_norm_name(o.get("name")): o for o in offerings}
    codes = sp.get("service_codes") or {}
    default_fee = sp.get("default_fee")

    # Paid pool: the client's paid invoices inside the same window, less
    # refunds. See the payment-linkage rule in the module docstring.
    invoices = _read(
        f"/invoices?business_id=eq.{biz}&contact_id=eq.{contact_id}"
        f"&status=eq.paid"
        f"&paid_at=gte.{w_from}T00:00:00Z&paid_at=lte.{w_to}T23:59:59Z"
        f"&select=id,total,paid_at,refund_amount_cents&limit=1000")
    payments_received = 0.0
    for inv in invoices:
        payments_received += float(inv.get("total") or 0)
        rc = inv.get("refund_amount_cents")
        if rc:
            payments_received -= float(rc) / 100.0
    payments_received = round(max(payments_received, 0.0), 2)

    rows: List[Dict[str, Any]] = []
    total_fees = 0.0
    unpriced = 0
    for s in sessions:
        title = (s.get("title") or "Session").strip()
        off = by_name.get(_norm_name(title))
        fee: Optional[float] = None
        code = ""
        if off is not None:
            if off.get("current_price") is not None:
                fee = float(off["current_price"])
            code = str(codes.get(off["id"]) or "")
        if fee is None and default_fee is not None:
            fee = float(default_fee)
        if fee is None:
            unpriced += 1
        else:
            total_fees = round(total_fees + fee, 2)
        rows.append({
            "date": (s.get("scheduled_for") or "")[:10],
            "description": title,
            "procedure_code": code,
            "duration_minutes": s.get("duration_minutes"),
            "fee": fee,
            "paid": 0.0,
        })

    # FIFO allocation of the paid pool, oldest session first, capped at fee.
    pool = payments_received
    for r in rows:
        if not pool:
            break
        take = round(min(float(r["fee"] or 0), pool), 2)
        r["paid"] = take
        pool = round(pool - take, 2)
    total_paid = round(sum(float(r["paid"]) for r in rows), 2)

    return {
        "ok": True,
        "report": "superbill",
        "range": {"from": w_from, "to": w_to},
        "business_name": ctx.get("name") or "Practice",
        "practitioner": practitioner_info(settings),
        "client": {"id": contact.get("id"), "name": contact.get("name") or "—",
                   "email": contact.get("email"), "phone": contact.get("phone")},
        "diagnosis_line": DIAGNOSIS_BLANK_LINE,   # always blank, by design
        "rows": rows,
        "totals": {
            "sessions": len(rows),
            "fees": round(total_fees, 2),
            "paid": total_paid,
            "payments_received": payments_received,
            "balance": round(total_fees - total_paid, 2),
        },
        "unpriced_sessions": unpriced,
        "note": STATEMENT_NOTE,
    }


# ─── PDF body (pdf_reports design system) ────────────────────────────

def _superbill_body(d, s, money_cell, accent, stripe, rule, danger, colors,
                    Table, TableStyle, Paragraph, Spacer, inch, meta):
    p = d.get("practitioner") or {}
    c = d.get("client") or {}
    out = []

    def _kv_block(title, pairs):
        out.append(Paragraph(title, s["section"]))
        rows = [[Paragraph(str(k), s["rowind"]), Paragraph(str(v or "—"), s["row"])]
                for k, v in pairs if v]
        if rows:
            t = Table(rows, colWidths=[1.5 * inch, None])
            t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
            out.append(t)

    license_line = " ".join(x for x in [p.get("license_type"), p.get("license_number")] if x)
    _kv_block("PROVIDER", [
        ("Practitioner", p.get("practitioner_name")),
        ("License", license_line),
        ("NPI", p.get("npi")),
        ("Tax ID (EIN)", p.get("ein")),
        ("Address", p.get("address")),
        ("Phone", p.get("phone")),
    ])
    _kv_block("CLIENT", [
        ("Name", c.get("name")),
        ("Email", c.get("email")),
        ("Phone", c.get("phone")),
    ])

    # The deliberate blank — completed by the provider by hand.
    out.append(Spacer(1, 0.12 * inch))
    out.append(Paragraph(
        f"{d.get('diagnosis_line') or DIAGNOSIS_BLANK_LINE}  "
        f"__________________________________________", s["row"]))
    out.append(Paragraph(
        "This platform stores no diagnosis codes or clinical information — "
        "the provider completes this line by hand.", s["note"]))
    out.append(Spacer(1, 0.12 * inch))

    out.append(Paragraph("SESSIONS", s["section"]))
    head = [Paragraph(h, s["th"]) for h in ("Date", "Service", "Code")] + \
           [Paragraph(h, s["thr"]) for h in ("Fee", "Paid")]
    rows = [head]
    for r in d.get("rows") or []:
        fee_cell = money_cell(r.get("fee")) if r.get("fee") is not None \
            else Paragraph("—", s["amt"])
        rows.append([
            Paragraph(str(r.get("date") or ""), s["rowind"]),
            Paragraph(str(r.get("description") or "")[:60], s["row"]),
            Paragraph(str(r.get("procedure_code") or "—"), s["rowind"]),
            fee_cell,
            money_cell(r.get("paid")),
        ])
    t_tot = d.get("totals") or {}
    rows.append([Paragraph("TOTAL", s["totlbl"]), Paragraph("", s["row"]),
                 Paragraph("", s["row"]),
                 money_cell(t_tot.get("fees"), bold=True),
                 money_cell(t_tot.get("paid"), bold=True)])
    tbl = Table(rows, colWidths=[0.9 * inch, None, 0.9 * inch, 1.0 * inch, 1.0 * inch],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("ALIGN", (3, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, rule),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, stripe]),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor("#1B1B1B")),
    ]))
    out.append(tbl)
    out.append(Spacer(1, 0.08 * inch))
    out.append(Paragraph(
        f"Payments received in period: {_fmt(t_tot.get('payments_received'))} · "
        f"Balance: {_fmt(t_tot.get('balance'))}", s["row"]))
    if d.get("unpriced_sessions"):
        out.append(Paragraph(
            f"{d['unpriced_sessions']} session(s) have no fee on record — set the "
            f"offering price or a standard session fee in Superbill setup.",
            s["danger"]))
    return out


def _fmt(n: Any) -> str:
    import pdf_reports
    return pdf_reports.fmt_money(n)


def render_pdf(data: Dict[str, Any], settings: Optional[Dict[str, Any]],
               generated_by: str = "") -> bytes:
    """Branded PDF via the shared pdf_reports design system (reuse, not
    reinvention). Raises ImportError when reportlab is unavailable."""
    import pdf_reports
    pdf_reports.register_builder("superbill", _superbill_body)
    rng = data.get("range") or {}
    meta = pdf_reports.build_meta(
        business_name=data.get("business_name") or "Practice",
        settings=settings,
        report_title="Superbill",
        period_label=f"Period: {rng.get('from')} – {rng.get('to')}",
        basis_label="Statement for reimbursement",
        generated_by=generated_by,
        notes=data.get("note") or STATEMENT_NOTE,
    )
    return pdf_reports.render("superbill", data, meta)
