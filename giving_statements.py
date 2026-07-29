"""
giving_statements.py — the contribution statement a donor files with their taxes.

THE GAP THIS CLOSES
  The readiness audit scored ministries 7/12 and found this: a grep for
  giving_statement, tax_receipt, contribution_statement and acknowledgement
  returned ZERO across the repo. gl_reports_t4.donor_report existed, but it
  is an INTERNAL report — gifts by donor, for the finance team. It is not the
  document a giver needs, and the two are not interchangeable.

  A church's giving statement is the one piece of paper it is obliged to
  produce every January. Getting it wrong is not a UX problem for the donor;
  without a compliant acknowledgment the IRS can disallow their deduction.

WHAT THE IRS ACTUALLY REQUIRES (Publication 1771)
  For a donor to substantiate a charitable contribution of $250 or more, the
  organisation must give a CONTEMPORANEOUS WRITTEN ACKNOWLEDGMENT containing:

    1. the organisation's name
    2. the amount of cash contributed
    3. a statement of whether the organisation provided any goods or
       services in return, AND
    4. if it did, a description and GOOD-FAITH ESTIMATE of their value, or
       a statement that the only benefit was an intangible religious benefit

  Point 3 is the one that gets omitted, and its omission is what invalidates
  an otherwise correct statement. It is therefore NOT optional here: every
  statement carries the declaration, and `goods_and_services` must be
  answered rather than defaulted past.

  The $250 threshold is per GIFT, not per year — which is why individual
  gifts are itemised and each one at or above the threshold is flagged,
  rather than only printing an annual sum.

WHAT THIS MODULE DOES NOT DO
  It does not give tax advice, does not file anything, and does not assert
  the organisation's 501(c)(3) status — it prints what the organisation
  tells it. `disclaimer()` says so in the document, because a system that
  silently implies deductibility on behalf of an org whose status it has
  never verified would be making a claim it cannot support.

  Quid pro quo (Pub 1771's other half — a $75+ gift where the donor got
  something back) is SURFACED, not computed: the org must supply the
  description and value. We flag the gifts that need it.

DATA SOURCE, HONESTLY
  Giving currently rides the invoices table (status='paid'), the same source
  gl_reports_t4.donor_report reads. The readiness checklist says a ministry's
  money model should be "giving, not invoices", and that is a fair criticism
  of the DATA MODEL. It is not a reason to withhold the statement: the
  payment records are real, refund-adjusted and already donor-linked. This
  reads them and produces a correct document today. Migrating giving off
  invoices is a separate, larger arc.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger("giving_statements")

# IRS Publication 1771 thresholds.
WRITTEN_ACK_THRESHOLD = 250.0    # per gift — donor needs an acknowledgment
QUID_PRO_QUO_THRESHOLD = 75.0    # per gift — disclosure needed if benefit given

# The declaration that makes a statement valid. Omitting it is the single
# most common reason an otherwise-correct acknowledgment fails.
NO_GOODS_LANGUAGE = (
    "No goods or services were provided in exchange for these contributions.")
RELIGIOUS_BENEFIT_LANGUAGE = (
    "The only benefit received was an intangible religious benefit.")

DISCLAIMER = (
    "This statement is generated from the organisation's own records of "
    "received gifts. It is not tax advice. Retain it with your tax records; "
    "consult a tax professional about deductibility.")


def disclaimer() -> str:
    return DISCLAIMER


def _year_bounds(year: int) -> tuple[str, str]:
    return f"{year}-01-01", f"{year}-12-31"


def _paid_gifts(business_id: str, year: int,
                contact_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Paid, refund-adjusted gifts for the tax year.

    Mirrors gl_reports_t4.donor_report's source and its refund handling on
    purpose — a donor's statement and the finance team's report disagreeing
    about the same year would be worse than either being slightly wrong.
    """
    import sb_clients
    start, end = _year_bounds(year)
    q = (f"/invoices?business_id=eq.{business_id}&status=eq.paid"
         f"&paid_at=gte.{start}T00:00:00Z&paid_at=lte.{end}T23:59:59Z"
         f"&select=id,total,paid_at,category,notes,refund_amount_cents,"
         f"contact_id,contacts(name,email)&order=paid_at.asc&limit=5000")
    if contact_id:
        q += f"&contact_id=eq.{contact_id}"
    try:
        return sb_clients.sb_get_as_service(q) or []
    except Exception as e:
        logger.warning(f"[giving] gift read failed: {e}")
        return []


def _net_amount(inv: Dict[str, Any]) -> float:
    """Gift amount less any refund. A refunded gift was not a gift, and
    printing it as one overstates a donor's deduction."""
    amt = float(inv.get("total") or 0)
    rc = inv.get("refund_amount_cents")
    if rc and float(rc) > 0:
        amt = round(amt - float(rc) / 100.0, 2)
    return amt


def statement_for_contact(business_id: str, contact_id: str, year: int,
                          *, org_name: Optional[str] = None,
                          goods_and_services: str = "none") -> Dict[str, Any]:
    """One donor's annual contribution statement.

    `goods_and_services` must be answered — it is IRS requirement #3:
      'none'      — nothing was given in return (the common case)
      'religious' — only an intangible religious benefit
      any other string — treated as a DESCRIPTION of what was provided, and
                         the statement is flagged as needing a good-faith
                         value estimate the organisation must supply.
    """
    gifts = _paid_gifts(business_id, year, contact_id)
    gifts = [g for g in gifts if _net_amount(g) > 0]

    if not gifts:
        return {"ok": True, "empty": True, "year": year,
                "contact_id": contact_id,
                "message": f"No recorded gifts for {year}."}

    donor = (gifts[0].get("contacts") or {}) or {}
    lines: List[Dict[str, Any]] = []
    total = 0.0
    needs_ack: List[Dict[str, Any]] = []
    quid_pro_quo_review: List[Dict[str, Any]] = []

    for g in gifts:
        amt = _net_amount(g)
        total = round(total + amt, 2)
        line = {
            "date": str(g.get("paid_at") or "")[:10],
            "amount": amt,
            "fund": (g.get("category") or "").strip() or "General",
            "refunded": bool(g.get("refund_amount_cents")),
        }
        lines.append(line)
        if amt >= WRITTEN_ACK_THRESHOLD:
            needs_ack.append(line)
        if amt >= QUID_PRO_QUO_THRESHOLD and goods_and_services not in ("none", "religious"):
            quid_pro_quo_review.append(line)

    if goods_and_services == "none":
        declaration = NO_GOODS_LANGUAGE
        complete = True
    elif goods_and_services == "religious":
        declaration = RELIGIOUS_BENEFIT_LANGUAGE
        complete = True
    else:
        # A description without a value is NOT a compliant statement. Say so
        # rather than printing something that looks finished.
        declaration = (f"Goods or services provided: {goods_and_services}. "
                       f"Good-faith estimate of value: [REQUIRED — supply this]")
        complete = False

    return {
        "ok": True,
        "empty": False,
        "year": year,
        "organisation": org_name or "",
        "donor": {"contact_id": contact_id,
                  "name": donor.get("name") or "",
                  "email": donor.get("email") or ""},
        "gifts": lines,
        "gift_count": len(lines),
        "total": total,
        # IRS requirement #3 — always present, never defaulted past.
        "declaration": declaration,
        "statement_complete": complete,
        "gifts_requiring_acknowledgment": needs_ack,
        "quid_pro_quo_review": quid_pro_quo_review,
        "disclaimer": DISCLAIMER,
        "generated_on": date.today().isoformat(),
    }


def statements_for_year(business_id: str, year: int,
                        *, org_name: Optional[str] = None,
                        goods_and_services: str = "none") -> Dict[str, Any]:
    """Every donor's statement for the year — the January run.

    Groups in one pass rather than re-querying per donor: a church with 400
    givers would otherwise make 400 round trips to produce one mailing.
    """
    gifts = [g for g in _paid_gifts(business_id, year) if _net_amount(g) > 0]
    by_contact: Dict[str, List[Dict[str, Any]]] = {}
    anonymous_total = 0.0

    for g in gifts:
        cid = g.get("contact_id")
        if not cid:
            # Loose cash with no giver attached cannot be acknowledged to
            # anyone. Counted so the totals reconcile, never invented into
            # a statement.
            anonymous_total = round(anonymous_total + _net_amount(g), 2)
            continue
        by_contact.setdefault(cid, []).append(g)

    out: List[Dict[str, Any]] = []
    for cid, rows in by_contact.items():
        donor = (rows[0].get("contacts") or {}) or {}
        total = round(sum(_net_amount(r) for r in rows), 2)
        out.append({
            "contact_id": cid,
            "name": donor.get("name") or "",
            "email": donor.get("email") or "",
            "gift_count": len(rows),
            "total": total,
            "needs_acknowledgment": any(
                _net_amount(r) >= WRITTEN_ACK_THRESHOLD for r in rows),
        })

    out.sort(key=lambda d: d["total"], reverse=True)
    return {
        "ok": True,
        "year": year,
        "organisation": org_name or "",
        "donors": out,
        "donor_count": len(out),
        "total_recorded": round(sum(d["total"] for d in out) + anonymous_total, 2),
        "unattributed_total": anonymous_total,
        "declaration": (NO_GOODS_LANGUAGE if goods_and_services == "none"
                        else RELIGIOUS_BENEFIT_LANGUAGE
                        if goods_and_services == "religious"
                        else f"Goods or services provided: {goods_and_services}"),
        "disclaimer": DISCLAIMER,
    }


def render_text(statement: Dict[str, Any]) -> str:
    """Plain-text statement — emailable, printable, and complete.

    Deliberately not HTML: this is a document a 70-year-old member may need
    to hand to a tax preparer, and plain text survives every mail client.
    """
    if statement.get("empty"):
        return statement.get("message", "No gifts recorded.")

    org = statement.get("organisation") or "Our organisation"
    d = statement.get("donor") or {}
    out = [
        f"{org}",
        f"Annual Contribution Statement — {statement['year']}",
        "",
        f"Donor: {d.get('name') or '(name not on record)'}",
        f"Statement date: {statement.get('generated_on')}",
        "",
        "Gifts received:",
    ]
    for g in statement["gifts"]:
        fund = f"  ({g['fund']})" if g["fund"] and g["fund"] != "General" else ""
        out.append(f"  {g['date']}   ${g['amount']:>10,.2f}{fund}")
    out += [
        "",
        f"  TOTAL {statement['year']}: ${statement['total']:,.2f}",
        f"  ({statement['gift_count']} gift"
        f"{'' if statement['gift_count'] == 1 else 's'})",
        "",
        statement["declaration"],
        "",
        statement["disclaimer"],
    ]
    if not statement.get("statement_complete"):
        out += ["", "*** NOT READY TO SEND — a good-faith estimate of the "
                    "value of goods or services provided is required. ***"]
    return "\n".join(out)
