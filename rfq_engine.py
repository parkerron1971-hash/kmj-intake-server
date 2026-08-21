"""
rfq_engine.py — THE SOURCING DESK, stage 2: the request for quote
(2026-08-21).

THE ASYMMETRY THIS USES
  A manufacturer's inbox is full of "please send info". Those get
  ignored, because answering one costs the vendor time and tells them
  nothing about whether the sender is real. The emails that get answered
  name a quantity, a spec, and a business.

  Chief already holds all three — the business name, what it sells, at
  what price, at what volume. So the letter writes itself with REAL
  numbers, and that is the actual product here. Finding the vendor was
  the easy half.

WHY THE COMPOSER IS PURE, AND WHY IT IS THE ONLY ONE
  compose_rfq() takes rows and returns strings. It touches no network and
  no clock beyond the date stamp, so the preview the practitioner reads
  and the email that leaves the building are produced by the same
  function from the same inputs — approving a preview means approving the
  send, exactly like the purchase order. Two composers would eventually
  disagree, and the day they did, the practitioner would have approved
  something that was never sent.

QUANTITY TIERS, BECAUSE ONE NUMBER IS A WORSE QUESTION
  A vendor quoting 200 units will usually quote 500 in the same reply if
  asked, and the second number is what tells the practitioner whether
  scaling up is worth it. Asking costs nothing and the answer is the
  whole basis of stage 3's comparison.

WHAT THIS DELIBERATELY DOES NOT DO
  It does not write with a model. An RFQ is a form letter with real
  numbers in it — a generated one would vary between vendors for no
  reason, cost money per send, and introduce a way for the quantity to
  come out wrong. The one thing a model would add is charm, and a
  manufacturer quoting blanks does not need charm.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# The second tier is 2.5x the first, rounded to something a human would
# actually say. A vendor asked for "200 and 500" answers both; asked for
# "200 and 512" they wonder what the second number means.
_TIER_MULTIPLIER = 2.5
_NICE = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000)


def _nice_number(n: int) -> int:
    for v in _NICE:
        if v >= n:
            return v
    return int(round(n / 1000.0)) * 1000


def quantity_tiers(qty: Optional[int]) -> List[int]:
    """The quantities to ask about. One if we have nothing to go on."""
    if not qty or qty <= 0:
        return []
    second = _nice_number(int(qty * _TIER_MULTIPLIER))
    if second <= qty:
        return [qty]
    return [qty, second]


def compose_rfq(*, biz: Dict[str, Any],
                supplier: Dict[str, Any],
                need: str,
                qty: Optional[int] = None,
                offering: Optional[Dict[str, Any]] = None,
                sells: Optional[List[str]] = None) -> Dict[str, Any]:
    """The RFQ email. One format for preview and send.

    Every line is dropped when the fact behind it is missing rather than
    filled with a placeholder — "we sell []" is worse than not saying it,
    and a vendor reading a template with the blanks showing knows exactly
    how much attention this request deserves.
    """
    biz_name = (biz.get("name") or "our business").strip()
    supplier_name = (supplier.get("name") or "").strip()
    to_email = (supplier.get("email") or "").strip()
    contact = (supplier.get("contact_name") or "").strip()
    need = (need or "").strip()

    rfq_number = (f"RFQ-{datetime.now(timezone.utc):%Y%m%d}"
                  f"-{str(supplier.get('id') or '')[:6].upper()}")

    tiers = quantity_tiers(qty)
    greeting = f"Hello {contact}," if contact else (
        f"Hello {supplier_name}," if supplier_name else "Hello,")

    lines: List[str] = [greeting, ""]

    intro = f"I'm getting in touch from {biz_name}"
    if sells:
        shown = [s for s in sells if s][:3]
        if shown:
            intro += f", where we sell {_and_join(shown)}"
    lines.append(intro + ".")
    lines.append("")

    lines.append("We're looking for a supplier for:")
    lines.append(f"  {need}")
    if offering and (offering.get("name") or "").strip():
        oname = offering["name"].strip()
        if oname.lower() not in need.lower():
            lines.append(f"  (for our {oname})")
    lines.append("")

    lines.append("Could you quote on the following?")
    if tiers:
        qty_text = " and ".join(f"{t:,}" for t in tiers)
        lines.append(f"  - Unit cost at {qty_text} units")
    else:
        lines.append("  - Unit cost, and the quantity your pricing starts at")
    lines.extend([
        "  - Your minimum order",
        "  - Lead time from order to delivery",
        "  - Any setup, tooling or sampling costs",
        "  - Payment terms",
        "",
        "Happy to send more detail on the spec if that helps.",
        "",
        "Thanks,",
        biz_name,
    ])

    subject_qty = f"{tiers[0]:,} " if tiers else ""
    subject = f"Quote request — {subject_qty}{_trim(need, 60)} ({biz_name})"

    return {
        "rfq_number": rfq_number,
        "subject": subject,
        "body": "\n".join(lines),
        "to_email": to_email,
        "to_name": supplier_name or None,
        "tiers": tiers,
    }


def _and_join(items: List[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _trim(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
