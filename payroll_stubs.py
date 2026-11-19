"""payroll_stubs.py — pay statements (Payroll, the free version, 2026-11-19).

Every approved or paid run has a pay statement for each person on it: the
JSON the app draws (GET /payroll/runs/{id}/stubs, .../items/{id}/stub), the
same statement as a one-page PDF (.../stub.pdf, reportlab, letter, laid out
like the approved mock PayStub.dc.html), and an email to each person with the
PDF attached, from the church (POST .../stubs/send, and on its own when a run
is marked paid, behind PAYROLL_STUB_EMAIL = off | owner | on, default on).

    YEAR TO DATE ... this person's lines on PAID runs in the same calendar
                     year with a pay date on or before this run's, plus this
                     line (a draft or approved run's lines never count twice)
    A MINISTER ..... Social Security and Medicare read "none, minister" (IRC
                     3121(b)(8): pay for ministry is not FICA wages; the
                     minister pays self-employment tax); the housing allowance
                     is its own earnings line and its own box (designated by
                     the board, paid so far this year, left), and two plain
                     notes say why (IRC 107; IRS Publication 517)
    WHAT IT CARRIES  the last four of a Social Security number (never more:
                     the profile's ciphertext is never read here), the last
                     four of the church's EIN when it is on file. No bank
                     account number exists to carry (none is stored)
    WHO GETS MAIL .. only the person, at the address on their own record;
                     nobody else's address is ever taken from a request

Logs carry ids and counts only: never a name, an email or an amount.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import payroll_calc
import sb_clients
from payroll_calendar import MONTHS, long_day, money, short_day

logger = logging.getLogger("payroll_stubs")

DEFAULT_ACCENT = "#c2125f"
FREQ_WORDS = {"weekly": "Paid every week", "biweekly": "Paid every two weeks",
              "semimonthly": "Paid twice a month", "monthly": "Paid once a month"}
PAID_BY_WORDS = {"direct_deposit": "Direct deposit", "check": "Check"}
STATUSES_WITH_STUBS = ("approved", "paid")
DRAFT_409 = "Approve the run first."
CANCELLED_409 = "This run was cancelled, so it has no pay statements."


class Unavailable(Exception):
    """A read the statements need failed: never shown as a statement of zeros."""


def _r(x: Any) -> float:
    try:
        return payroll_calc._r(float(x or 0))
    except (TypeError, ValueError):
        return 0.0


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def name_of(e: Dict[str, Any]) -> str:
    return f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip() or "Someone"


def _get(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise Unavailable(path.split("?", 1)[0])
    return rows


# ─── What a statement reads ───────────────────────────────────────────

def load(run: Dict[str, Any], biz_row: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the run's statements need, read once as the server."""
    import church_follow_up
    biz = str(run["business_id"])
    b = _q(biz)
    items = _get(f"/pay_run_items?pay_run_id=eq.{_q(run['id'])}&select=*&order=created_at.asc&limit=500")
    emps = {str(e["id"]): e for e in _get(f"/employees?business_id=eq.{b}&select=*&limit=1000")}
    # Never the ciphertext: the last four alone.
    profiles = {str(p["employee_id"]): p for p in _get(
        f"/employee_tax_profiles?business_id=eq.{b}&select=employee_id,ssn_last4&limit=1000")}
    pd = _day(run.get("pay_date")) or date.today()
    paid_runs = _get(f"/pay_runs?business_id=eq.{b}&status=eq.paid&pay_date=gte.{pd.year}-01-01"
                     f"&pay_date=lte.{pd.isoformat()}&select=id,pay_date&limit=1000")
    run_dates = {str(r["id"]): str(r.get("pay_date") or "")[:10] for r in paid_runs
                 if str(r.get("id")) != str(run["id"])}
    ytd: Dict[str, List[Dict[str, Any]]] = {}
    if run_dates:
        ids = ",".join(_q(i) for i in sorted(run_dates))
        try:
            rows = sb_clients.sb_get_all_as_service(
                f"/pay_run_items?business_id=eq.{b}&pay_run_id=in.({ids})&select=*", strict=True) or []
        except sb_clients.PartialRead:
            raise Unavailable("pay_run_items")
        for i in rows:
            ytd.setdefault(str(i.get("employee_id")), []).append(i)
    church = church_follow_up.is_church(biz_row)
    return {"biz": biz_row, "run": run, "items": items, "emps": emps, "profiles": profiles,
            "ytd": ytd, "run_dates": run_dates, "church": church, "payer": None, "housing": {}}


def _payer(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.get("payer") is None:
        ctx["payer"] = payer_of(ctx["biz"])
    return ctx["payer"]


def payer_of(biz_row: Dict[str, Any]) -> Dict[str, Any]:
    """The church's name, address and the last four of its EIN, when known."""
    name = str(biz_row.get("name") or "").strip() or "Your church"
    address, ein4 = "", None
    try:
        import business_identity
        p = business_identity.payer_block(str(biz_row.get("id") or ""), biz_row)
        address = " · ".join(x for x in (p.get("line1"), p.get("city_state_zip")) if x)
        digits = re.sub(r"\D", "", str(p.get("ein") or ""))
        ein4 = digits[-4:] if len(digits) >= 4 else None
    except Exception:  # noqa: BLE001 — the statement goes without it
        pass
    return {"name": name, "address": address or None, "ein_last4": ein4}


def _housing(ctx: Dict[str, Any], emp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The minister's housing allowance record for the run's year, when the
    records are on for this church and one is found (payroll_router's own
    matching). Cached on the context."""
    eid = str(emp.get("id"))
    if eid in ctx["housing"]:
        return ctx["housing"][eid]
    rec = None
    try:
        import housing_allowance as ha
        import payroll_router
        biz = str(ctx["run"]["business_id"])
        if ha.switched_on(biz):
            year = int(str(ctx["run"]["pay_date"])[:4])
            rec, _why = payroll_router._housing_record(biz, year, emp)
    except Exception:  # noqa: BLE001 — the box shows what payroll paid, without the designation
        rec = None
    ctx["housing"][eid] = rec
    return rec


# ─── One statement ────────────────────────────────────────────────────

def _payload(item: Dict[str, Any]) -> Dict[str, Any]:
    p = item.get("calc_payload")
    return p if isinstance(p, dict) else {}


def _pay_type(item: Dict[str, Any], emp: Dict[str, Any]) -> str:
    pay = _payload(item).get("pay")
    if isinstance(pay, dict) and pay.get("type") in ("hourly", "salary"):
        return pay["type"]
    return emp.get("pay_type") or "hourly"


def _freq(item: Dict[str, Any], emp: Dict[str, Any]) -> str:
    pay = _payload(item).get("pay")
    if isinstance(pay, dict) and pay.get("frequency") in payroll_calc.PERIODS_PER_YEAR:
        return pay["frequency"]
    return emp.get("pay_frequency") or "biweekly"


def components(item: Dict[str, Any], emp: Dict[str, Any]) -> Dict[str, float]:
    """One line's earnings, split: salary, or regular and overtime, and the
    housing allowance (part of gross, its own line)."""
    gross, housing = _r(item.get("gross")), _r(item.get("housing_allowance"))
    housing = min(housing, gross)
    if _pay_type(item, emp) == "salary":
        return {"salary": _r(gross - housing), "housing": housing}
    h, ot = float(item.get("hours") or 0), float(item.get("overtime_hours") or 0)
    weight = h + ot * payroll_calc.OVERTIME_MULTIPLIER
    overtime = _r(gross * ot * payroll_calc.OVERTIME_MULTIPLIER / weight) if ot > 0 and weight > 0 else 0.0
    regular = _r(gross - overtime - housing)
    if regular < 0:
        overtime, regular = _r(overtime + regular), 0.0
    return {"regular": regular, "overtime": overtime, "housing": housing}


_EARN_ORDER = ("salary", "regular", "overtime", "housing")


def _earn_label(key: str, item: Dict[str, Any]) -> str:
    if key == "regular":
        h = float(item.get("hours") or 0)
        return f"Regular pay, {h:g} hours" if h else "Regular pay"
    if key == "overtime":
        ot = float(item.get("overtime_hours") or 0)
        return f"Overtime, {ot:g} hours" if ot else "Overtime"
    return {"salary": "Salary", "housing": "Housing allowance"}[key]


def _index(item: Dict[str, Any], emp: Dict[str, Any], run: Dict[str, Any], earlier: int) -> Dict[str, Any]:
    freq = _freq(item, emp)
    end = _day(run.get("period_end")) or _day(run.get("pay_date"))
    of = payroll_calc.PERIODS_PER_YEAR.get(freq)
    if not end or not of:
        return {"index": None, "of": None}
    if freq == "semimonthly":
        idx = (end.month - 1) * 2 + (1 if end.day <= 15 else 2)
    elif freq == "monthly":
        idx = end.month
    else:
        idx = earlier + 1
    return {"index": idx, "of": of if idx <= of else None}


def build(ctx: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """The Stub for one line of the run in `ctx`."""
    run = ctx["run"]
    emp = ctx["emps"].get(str(item.get("employee_id"))) or {"id": item.get("employee_id")}
    prof = ctx["profiles"].get(str(item.get("employee_id"))) or {}
    minister = payroll_calc.is_minister(emp, ctx["church"])
    earlier = ctx["ytd"].get(str(item.get("employee_id")), [])
    lines = earlier + [item]

    this_c = components(item, emp)
    ytd_c: Dict[str, float] = {}
    for i in lines:
        for k, v in components(i, emp).items():
            ytd_c[k] = _r(ytd_c.get(k, 0) + v)
    earnings = [{"key": k, "label": _earn_label(k, item), "this": _r(this_c.get(k, 0)), "ytd": _r(ytd_c.get(k, 0))}
                for k in _EARN_ORDER if this_c.get(k) or ytd_c.get(k)]

    def total(key: str) -> float:
        return _r(sum(_r(i.get(key)) for i in lines))

    fit, sit = _r(item.get("federal_withholding")), _r(item.get("state_withholding"))
    ss, med = _r(item.get("social_security_employee")), _r(item.get("medicare_employee"))
    taxes = [
        {"key": "federal", "label": "Federal income tax", "this": fit, "ytd": total("federal_withholding"),
         "note": "asked for on their W-4" if minister and fit else None},
        {"key": "state", "label": "State income tax", "this": sit, "ytd": total("state_withholding"), "note": None},
    ]
    if minister:
        taxes += [{"key": "social_security", "label": "Social Security", "this": None, "ytd": None,
                   "note": "none, minister"},
                  {"key": "medicare", "label": "Medicare", "this": None, "ytd": None, "note": "none, minister"}]
    else:
        taxes += [{"key": "social_security", "label": "Social Security", "this": ss,
                   "ytd": total("social_security_employee"), "note": None},
                  {"key": "medicare", "label": "Medicare", "this": med, "ytd": total("medicare_employee"),
                   "note": None}]
    tax_this = _r(fit + sit + (0 if minister else ss + med))
    tax_ytd = _r(total("federal_withholding") + total("state_withholding")
                 + (0 if minister else total("social_security_employee") + total("medicare_employee")))
    other_this, other_ytd = _r(item.get("other_deductions")), total("other_deductions")
    deductions = ([{"key": "other", "label": "Other deductions", "this": other_this, "ytd": other_ytd}]
                  if other_this or other_ytd else [])

    housing_box = None
    notes: List[str] = []
    if minister:
        rec = _housing(ctx, emp)
        paid = _r(ytd_c.get("housing", 0))
        designated = _r(rec.get("designated_amount")) if rec and rec.get("designated_amount") is not None else None
        housing_box = {"designated": designated,
                       "designated_on": str(rec.get("designated_on"))[:10] if rec and rec.get("designated_on") else None,
                       "paid_ytd": paid,
                       "left": _r(max(0.0, designated - paid)) if designated is not None else None}
        who = name_of(emp)
        notes.append(f"Why no Social Security or Medicare: as a minister, {who} pays these through "
                     f"self-employment tax. The church doesn’t take them out or match them.")
        if paid or designated:
            notes.append("Housing allowance: left out of federal income tax (section 107) but counted for "
                         "self-employment tax. It shows in Box 14 of the W-2.")
    pd = _day(run.get("pay_date"))
    paid_by = emp.get("paid_by") if emp.get("paid_by") in PAID_BY_WORDS else (
        "direct_deposit" if emp.get("direct_deposit_consented_at") else None)
    return {
        "item_id": str(item.get("id")),
        "run_id": str(run.get("id")),
        "employee": {"id": str(emp.get("id") or item.get("employee_id")), "name": name_of(emp),
                     "title": (str(emp.get("title")).strip() or None) if emp.get("title") else None,
                     "ssn_last4": prof.get("ssn_last4") or None, "minister": minister,
                     "credential": emp.get("minister_credential") if minister else None},
        "period": {"start": str(run.get("period_start") or "")[:10] or None,
                   "end": str(run.get("period_end") or "")[:10] or None,
                   "pay_date": pd.isoformat() if pd else None, **_index(item, emp, run, len(earlier))},
        "paid_by": paid_by,
        "earnings": earnings,
        "gross": {"this": _r(item.get("gross")), "ytd": total("gross")},
        "taxes": taxes,
        "total_taxes": {"this": tax_this, "ytd": tax_ytd},
        "deductions": deductions,
        "net": {"this": _r(item.get("net")), "ytd": total("net")},
        "housing": housing_box,
        "notes": notes,
        "payer": _payer(ctx),
        "frequency": _freq(item, emp),
        "status": run.get("status"),
    }


def all_stubs(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [build(ctx, i) for i in ctx["items"]]


# ─── The PDF ──────────────────────────────────────────────────────────

def _accent(biz_row: Dict[str, Any]) -> str:
    try:
        import email_layout
        primary = (email_layout.brand_of(biz_row.get("settings")) or {}).get("primary") or ""
        if primary and primary != email_layout.DEFAULT_ACCENT:
            return primary
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_ACCENT


def _church(biz_row: Dict[str, Any]) -> bool:
    try:
        import church_follow_up
        return church_follow_up.is_church(biz_row)
    except Exception:  # noqa: BLE001
        return False


def _period_words(stub: Dict[str, Any]) -> str:
    s, e = _day(stub["period"]["start"]), _day(stub["period"]["end"])
    if not s or not e:
        return "—"
    if s.year == e.year and s.month == e.month:
        return f"{MONTHS[s.month - 1][:3]} {s.day} to {e.day}, {e.year}"
    if s.year == e.year:
        return f"{short_day(s)} to {short_day(e)}, {e.year}"
    return f"{short_day(s)}, {s.year} to {short_day(e)}, {e.year}"


def pdf(stub: Dict[str, Any], biz_row: Dict[str, Any]) -> bytes:
    """One letter page, laid out like the mock: the church and "Pay
    statement", paid to / pay period / paid by, earnings and taxes for this
    period and this year, the take-home box, a minister's housing box and
    notes. Plain shapes only: it is the church's own statement."""
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    W, H = letter
    M = 46
    ink, muted, faint, line = HexColor("#17171a"), HexColor("#5a5a64"), HexColor("#6b6b75"), HexColor("#e4e4e7")
    try:
        acc = HexColor(_accent(biz_row))
    except Exception:  # noqa: BLE001
        acc = HexColor(DEFAULT_ACCENT)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    payer = stub.get("payer") or {}
    c.setTitle(f"Pay statement, {stub['period']['pay_date'] or ''}")
    c.setAuthor(str(payer.get("name") or ""))
    c.setCreator("Solutionist")

    def text(x, y, s, font="Helvetica", size=9.5, color=ink, align="left"):
        c.setFont(font, size)
        c.setFillColor(color)
        s = str(s)
        if align == "right":
            c.drawRightString(x, y, s)
        elif align == "center":
            c.drawCentredString(x, y, s)
        else:
            c.drawString(x, y, s)

    # The mark: four panes of the church's colour.
    top = H - M
    mx, my, ms = M, top - 30, 30
    panes = [((0, 0), (0.64, 0), (0.55, 0.45), (0, 0.36), 0.95),
             ((0.64, 0), (1, 0), (1, 0.55), (0.55, 0.45), 0.7),
             ((1, 0.55), (1, 1), (0.68, 1), (0.55, 0.45), 0.52),
             ((0.68, 1), (0, 1), (0, 0.68), (0.55, 0.45), 0.82),
             ((0, 0.68), (0, 0.36), (0.55, 0.45), (0.55, 0.45), 0.62)]
    for *pts, alpha in panes:
        p = c.beginPath()
        x0, y0 = pts[0]
        p.moveTo(mx + x0 * ms, my + (1 - y0) * ms)
        for x1, y1 in pts[1:]:
            p.lineTo(mx + x1 * ms, my + (1 - y1) * ms)
        p.close()
        c.setFillColor(acc)
        c.setFillAlpha(alpha)
        c.setStrokeColor(white)
        c.setLineWidth(1)
        c.drawPath(p, fill=1, stroke=1)
    c.setFillAlpha(1)

    text(M + 42, top - 13, payer.get("name") or "", "Helvetica-Bold", 15)
    sub = " · ".join(x for x in (payer.get("address"),
                                 f"EIN ending {payer['ein_last4']}" if payer.get("ein_last4") else None) if x)
    if sub:
        text(M + 42, top - 27, sub, size=8.5, color=muted)
    text(W - M, top - 14, "Pay statement", "Helvetica-Bold", 19, align="right")
    pd = _day(stub["period"]["pay_date"])
    text(W - M, top - 28, f"Pay date {long_day(pd)}" if pd else "", size=8.5, color=muted, align="right")
    y = top - 46
    c.setFillColor(acc)
    c.roundRect(M, y, W - 2 * M, 2.5, 1.2, fill=1, stroke=0)

    # Paid to / Pay period / Paid by.
    emp = stub["employee"]
    col = (W - 2 * M) / 3
    y -= 22
    who_sub = [x for x in (emp.get("title"),
                           f"minister, {emp['credential']}" if emp.get("minister") and emp.get("credential")
                           else ("minister" if emp.get("minister") else None)) if x]
    blocks = [
        ("Paid to", emp["name"], [" · ".join(who_sub)] if who_sub else [],
         f"Social Security number ending {emp['ssn_last4']}" if emp.get("ssn_last4") else None),
        ("Pay period", _period_words(stub),
         [FREQ_WORDS.get(stub.get("frequency") or "", "")
          + (f" · period {stub['period']['index']} of {stub['period']['of']}"
             if stub["period"].get("index") and stub["period"].get("of") else "")], None),
        ("Paid by", PAID_BY_WORDS.get(stub.get("paid_by") or "", "Not recorded"),
         [("From the church’s own bank" if _church(biz_row) else "From the employer’s own bank")
          if stub.get("paid_by") else ""], None),
    ]
    for n, (label, value, subs, extra) in enumerate(blocks):
        x = M + n * col
        text(x, y, label, "Helvetica-Bold", 8.5, muted)
        for i, ln in enumerate(simpleSplit(str(value), "Helvetica-Bold", 11.5, col - 12)[:2]):
            text(x, y - 15 - i * 13, ln, "Helvetica-Bold", 11.5)
        yy = y - 30 - (13 if len(simpleSplit(str(value), "Helvetica-Bold", 11.5, col - 12)) > 1 else 0)
        for s in [*(subs or []), extra]:
            if not s:
                continue
            for ln in simpleSplit(str(s), "Helvetica", 8.5, col - 12)[:2]:
                text(x, yy, ln, size=8.5, color=muted)
                yy -= 11
    y -= 74

    # The tables (left) and the take-home box (right).
    box_w = 168
    tw = W - 2 * M - box_w - 22
    tx = M
    c1, c2 = tx + tw - 88, tx + tw

    def table(y0: float, head: str, rows: List[Dict[str, Any]], sum_label: str, sum_this: float,
              sum_ytd: float) -> float:
        text(tx, y0, head, "Helvetica-Bold", 8.5, muted)
        text(c1, y0, "This period", "Helvetica-Bold", 8.5, muted, "right")
        text(c2, y0, "This year", "Helvetica-Bold", 8.5, muted, "right")
        y0 -= 6
        c.setStrokeColor(ink)
        c.setLineWidth(1.2)
        c.line(tx, y0, tx + tw, y0)
        for r in rows:
            y0 -= 16
            label = r["label"]
            if r.get("note") and r.get("this") is not None:
                text(tx, y0, label, size=10)
                text(tx + c.stringWidth(label, "Helvetica", 10) + 4, y0, f"({r['note']})", size=8.5, color=faint)
            else:
                text(tx, y0, label, size=10)
            if r.get("this") is None:
                text(c1, y0, r.get("note") or "—", size=8.5, color=faint, align="right")
                text(c2, y0, "none" if r.get("note") else "—", size=8.5, color=faint, align="right")
            else:
                text(c1, y0, money(r["this"]), size=10, align="right")
                text(c2, y0, money(r["ytd"]), size=10, align="right")
            y0 -= 6
            c.setStrokeColor(line)
            c.setLineWidth(0.6)
            c.line(tx, y0, tx + tw, y0)
        y0 -= 16
        text(tx, y0, sum_label, "Helvetica-Bold", 10)
        text(c1, y0, money(sum_this), "Helvetica-Bold", 10, align="right")
        text(c2, y0, money(sum_ytd), "Helvetica-Bold", 10, align="right")
        y0 -= 6
        c.setStrokeColor(ink)
        c.setLineWidth(1.2)
        c.line(tx, y0, tx + tw, y0)
        return y0 - 24

    body_top = y
    y = table(y, "Earnings", stub["earnings"], "Pay before taxes", stub["gross"]["this"], stub["gross"]["ytd"])
    y = table(y, "Taxes taken out", stub["taxes"], "Total taxes", stub["total_taxes"]["this"],
              stub["total_taxes"]["ytd"])
    if stub.get("deductions"):
        d = stub["deductions"]
        y = table(y, "Other deductions", d, "Total other deductions",
                  _r(sum(x["this"] for x in d)), _r(sum(x["ytd"] for x in d)))

    bx = W - M - box_w
    by_top = body_top + 10
    inner = box_w - 28
    parts: List[tuple] = [("k", "Take-home pay"), ("big", money(stub["net"]["this"])),
                          ("s", f"This year: {money(stub['net']['ytd'])}")]
    hb = stub.get("housing")
    if hb:
        year = (pd.year if pd else "")
        parts += [("rule", ""), ("k", f"Housing allowance for {year}")]
        if hb.get("designated") is not None:
            on = _day(hb.get("designated_on"))
            set_words = f"The board set {money(hb['designated'])}" + (
                f" on {MONTHS[on.month - 1]} {on.day}, {on.year}." if on else ".")
            parts.append(("p", set_words))
            parts.append(("bar", min(1.0, (hb["paid_ytd"] / hb["designated"]) if hb["designated"] else 0.0)))
            parts.append(("p", f"{money(hb['paid_ytd'])} paid · {money(hb['left'])} left"))
        else:
            parts.append(("p", f"{money(hb['paid_ytd'])} paid this year. No designation is on file here."))
    heights = {"k": 13, "big": 34, "s": 13, "rule": 18, "bar": 14}
    lines_of = {i: simpleSplit(v, "Helvetica", 8.5, inner) for i, (k, v) in enumerate(parts) if k == "p"}
    box_h = 22 + sum(heights.get(k, 0) if k != "p" else 11 * len(lines_of[i]) + 2 for i, (k, _v) in enumerate(parts))
    c.setStrokeColor(ink)
    c.setLineWidth(1.2)
    c.roundRect(bx, by_top - box_h, box_w, box_h, 10, fill=0, stroke=1)
    yy = by_top - 20
    for i, (k, v) in enumerate(parts):
        if k == "k":
            text(bx + 14, yy, v, "Helvetica-Bold", 8.5, muted)
            yy -= heights["k"]
        elif k == "big":
            text(bx + 14, yy - 22, v, "Helvetica-Bold", 26)
            yy -= heights["big"]
        elif k == "s":
            text(bx + 14, yy - 2, v, size=8.5, color=muted)
            yy -= heights["s"]
        elif k == "rule":
            c.setStrokeColor(line)
            c.setLineWidth(0.8)
            c.line(bx + 14, yy - 2, bx + box_w - 14, yy - 2)
            yy -= heights["rule"]
        elif k == "bar":
            c.setFillColor(line)
            c.roundRect(bx + 14, yy - 4, inner, 6, 3, fill=1, stroke=0)
            if v > 0:
                c.setFillColor(acc)
                c.roundRect(bx + 14, yy - 4, max(6.0, inner * v), 6, 3, fill=1, stroke=0)
            yy -= heights["bar"]
        else:
            for ln in lines_of[i]:
                text(bx + 14, yy, ln, size=8.5, color=HexColor("#3f3f46"))
                yy -= 11
            yy -= 2
    y = min(y, by_top - box_h - 20)

    # A minister's notes.
    if stub.get("notes"):
        nw = W - 2 * M - 28
        rows = []
        for note in stub["notes"]:
            head, _, rest = note.partition(": ")
            rows.append((head + ":" if rest else "", rest or note))
        lines_n = [simpleSplit(f"{h} {r}".strip(), "Helvetica", 8.5, nw) for h, r in rows]
        nh = 20 + sum(11 * len(x) + 4 for x in lines_n)
        c.setFillColor(HexColor("#f4f4f5"))
        c.roundRect(M, y - nh, W - 2 * M, nh, 9, fill=1, stroke=0)
        yy = y - 16
        for (h, _r_), lns in zip(rows, lines_n):
            for j, ln in enumerate(lns):
                if j == 0 and h and ln.startswith(h):
                    text(M + 14, yy, h, "Helvetica-Bold", 8.5, HexColor("#3f3f46"))
                    text(M + 14 + c.stringWidth(h + " ", "Helvetica-Bold", 8.5), yy, ln[len(h):].strip(),
                         size=8.5, color=HexColor("#3f3f46"))
                else:
                    text(M + 14, yy, ln, size=8.5, color=HexColor("#3f3f46"))
                yy -= 11
            yy -= 4
        y -= nh + 16

    # The foot.
    c.setStrokeColor(line)
    c.setLineWidth(0.8)
    c.line(M, M + 14, W - M, M + 14)
    text(M, M, f"For your records. {payer.get('name') or 'The church'} pays from its own bank.", size=8,
         color=faint)
    text(W - M, M, "Prepared with Solutionist", size=8, color=faint, align="right")
    c.showPage()
    c.save()
    return buf.getvalue()


def filename(stub: Dict[str, Any]) -> str:
    return f"pay-statement-{stub['period']['pay_date'] or 'run'}-{str(stub['item_id'])[:8]}.pdf"


# ─── Sending ──────────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("PAYROLL_STUB_EMAIL") or "on").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def auto_on(business_id: Any) -> bool:
    """Whether a run marked paid emails its statements on its own here."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        try:
            import member_asks
            return bool(member_asks.platform_church(business_id))
        except Exception:  # noqa: BLE001 — couldn't tell: nothing goes
            return False
    return False


_EMAIL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def _run_async(coro):
    """Run a coroutine to the end from sync code, on a thread of its own when
    this thread already has a running loop."""
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def send(ctx: Dict[str, Any], *, only: Optional[List[str]] = None, auto: bool = False) -> Dict[str, Any]:
    """Email each person on the run their statement, at the address on their
    own record, from the church. {sent, skipped: [{name, why}]}. One that
    fails never stops the rest."""
    import email_sender
    import sample_church
    biz_row, run = ctx["biz"], ctx["run"]
    church = str(biz_row.get("name") or "").strip() or "Your church"
    biz = str(run["business_id"])
    pd = _day(run.get("pay_date"))
    sent, skipped = 0, []
    for item in ctx["items"]:
        if only is not None and str(item.get("id")) not in only:
            continue
        emp = ctx["emps"].get(str(item.get("employee_id"))) or {}
        who = name_of(emp)
        to = str(emp.get("email") or "").strip()
        if not to or len(to) > 200 or not _EMAIL.match(to):
            skipped.append({"name": who, "why": "no email address on file"})
            continue
        try:
            stub = build(ctx, item)
            data = pdf(stub, biz_row)
            body = (f"Hello {emp.get('first_name') or who},\n\n"
                    f"Your pay statement from {church} for the pay date "
                    f"{long_day(pd) if pd else ''} is attached as a PDF. Keep it for your records.\n\n"
                    f"Questions about it? Ask {church}'s office.\n")
            key = f"paystub-{item.get('id')}-" + ("paid" if auto else date.today().isoformat())
            _run_async(email_sender.send_via_resend(
                to_email=to, to_name=who, from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                from_name=church, subject=f"Your pay statement for {short_day(pd)}, {pd.year}" if pd
                else "Your pay statement", body=body, reply_to=None, business_id=biz, idempotency_key=key,
                attachments=[{"filename": filename(stub), "content": base64.b64encode(data).decode("ascii"),
                              "content_type": "application/pdf"}]))
            sent += 1
        except sample_church.SendRefused:
            skipped.append({"name": who, "why": "a sample church sends nothing"})
        except Exception as e:  # noqa: BLE001 — the rest still go
            logger.warning("[payroll] a pay statement email failed run=%s: %s", str(run.get("id"))[:8],
                           type(e).__name__)
            skipped.append({"name": who, "why": "the email didn’t go; try again"})
    logger.info("[payroll] statements run=%s sent=%d skipped=%d auto=%s", str(run.get("id"))[:8], sent,
                len(skipped), auto)
    return {"sent": sent, "skipped": skipped}
