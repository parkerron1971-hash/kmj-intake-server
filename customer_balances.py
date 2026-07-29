"""
customer_balances.py — what a customer paid for and has not yet received.

THE GAP THIS CLOSES
  The vertical readiness audit scored "Money in" PARTIAL for ALL SEVEN
  verticals on a single finding: a repo-wide grep for sessions_remaining,
  package_balance, drawdown, retainer_balance and session_credit returned
  zero matches. Every vertical could SELL a package; none could track its
  consumption. A coach sold six sessions and then counted them in their head.

ONE PRIMITIVE, FIVE MONEY MODELS
  coach       package  / session : +6 on purchase, -1 per session
  consultant  retainer / money   : +5000 on invoice, -750 per milestone
  lawyer      retainer / hour    : +20 hours, -1.5 per time entry
  contractor  deposit  / money   : +500 taken, -500 applied to final invoice
  any         gift_card / money  : +100 sold, -35 redeemed

  The verticals differ in the WORDS, not the mechanics. Resisting five
  bespoke tables is the whole design.

WHY A LEDGER, NOT A COUNTER
  A sessions_remaining column would be simpler and wrong: it cannot answer
  "why is it four", cannot be audited, and races. This is money already
  handed over, so it gets what the GL gets — append-only signed rows,
  balance by summation, nothing mutated in place.

NOT public.credit_ledger
  That is platform AI credits (a business buying action units from KMJ).
  This is a business's own customer prepaying that business. Different
  money, different direction, deliberately different name.

THE OVERDRAW RACE
  consume() reads the balance and then writes a negative row. Two bookings
  confirming at once can both read "1 session left" and both draw, leaving
  -1. There is no transaction boundary across two PostgREST calls, so this
  module does NOT pretend to have solved it: it re-reads after writing and
  SELF-CORRECTS by reversing its own row when it lost the race, returning
  overdrawn=True. Callers get a truthful answer either way.

  The clean fix is a database function with SELECT ... FOR UPDATE, which is
  a schema change beyond this arc. The reversal keeps the ledger honest
  meanwhile, and the docstring says so rather than leaving a comment that
  claims safety it does not have.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("customer_balances")

KINDS = ("package", "retainer", "deposit", "gift_card")
UNITS = ("session", "hour", "money")

# What each vertical most naturally prepays in. Used to pick sensible
# defaults when Chief is told "Marcus bought the 6-session package" without
# being told which ledger to touch.
VERTICAL_DEFAULT: Dict[str, Dict[str, str]] = {
    "coach":              {"kind": "package",  "unit": "session"},
    "coaching":           {"kind": "package",  "unit": "session"},
    "fitness_wellness":   {"kind": "package",  "unit": "session"},
    "course_creator":     {"kind": "package",  "unit": "session"},
    "consultant":         {"kind": "retainer", "unit": "money"},
    "lawyer":             {"kind": "retainer", "unit": "hour"},
    "creative":           {"kind": "deposit",  "unit": "money"},
    "contractor":         {"kind": "deposit",  "unit": "money"},
    "personal_services":  {"kind": "package",  "unit": "session"},
    "ministry":           {"kind": "gift_card", "unit": "money"},
    "nonprofit":          {"kind": "gift_card", "unit": "money"},
}


def defaults_for_vertical(business_type: Optional[str]) -> Dict[str, str]:
    try:
        import vertical_registry
        key = vertical_registry.resolve(business_type)
    except Exception:
        key = "custom"
    return dict(VERTICAL_DEFAULT.get(key) or {"kind": "package", "unit": "session"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate(kind: str, unit: str) -> Optional[str]:
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}"
    if unit not in UNITS:
        return f"unit must be one of {', '.join(UNITS)}"
    return None


# ─────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────

def balances_for_contact(business_id: str, contact_id: str) -> List[Dict[str, Any]]:
    """Every non-zero balance this contact holds. Reads the derived view —
    there is no stored total to drift."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/customer_balances?business_id=eq.{business_id}"
        f"&contact_id=eq.{contact_id}&select=*") or []
    return [r for r in rows if _num(r.get("balance")) != 0]


def balance(business_id: str, contact_id: str, kind: str, unit: str) -> float:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/customer_balances?business_id=eq.{business_id}"
        f"&contact_id=eq.{contact_id}&kind=eq.{kind}&unit=eq.{unit}"
        "&select=balance") or []
    return _num(rows[0].get("balance")) if rows else 0.0


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def history(business_id: str, contact_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """The audit trail — why the balance is what it is."""
    import sb_clients
    return sb_clients.sb_get_as_service(
        f"/customer_ledger?business_id=eq.{business_id}"
        f"&contact_id=eq.{contact_id}&order=created_at.desc&limit={int(limit)}"
        "&select=id,kind,unit,delta,reason,created_at,expires_at,invoice_id") or []


def expiring_soon(business_id: str, within_days: int = 30) -> List[Dict[str, Any]]:
    """Grants about to lapse. A package that expires unused is a refund
    request or a lost customer, and either is worth a heads-up."""
    import sb_clients
    from datetime import timedelta
    cutoff = (_now() + timedelta(days=int(within_days)))
    # PostgREST timestamp class: the Z form, never isoformat's +00:00 —
    # the offset form silently returns empty in a query string.
    cutoff_z = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_z = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return sb_clients.sb_get_as_service(
        f"/customer_ledger?business_id=eq.{business_id}"
        f"&expires_at=gte.{now_z}&expires_at=lte.{cutoff_z}"
        "&delta=gt.0&order=expires_at.asc&limit=50"
        "&select=id,contact_id,kind,unit,delta,expires_at,reason") or []


# ─────────────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────────────

def grant(business_id: str, contact_id: str, amount: float, kind: str, unit: str,
          reason: str, *, currency: str = "usd",
          offering_id: Optional[str] = None, invoice_id: Optional[str] = None,
          expires_at: Optional[str] = None,
          created_by: Optional[str] = None) -> Dict[str, Any]:
    """Record that a customer bought something they have not consumed yet."""
    err = _validate(kind, unit)
    if err:
        return {"ok": False, "error": err}
    amount = _num(amount)
    if amount <= 0:
        return {"ok": False, "error": "grant amount must be positive"}
    if not (reason or "").strip():
        return {"ok": False, "error": "reason is required"}

    import sb_clients
    row = {
        "business_id": business_id, "contact_id": contact_id,
        "kind": kind, "unit": unit, "delta": amount, "currency": currency,
        "reason": reason.strip(), "offering_id": offering_id,
        "invoice_id": invoice_id, "expires_at": expires_at,
        "created_by": created_by,
    }
    try:
        sb_clients.sb_post_as_service("/customer_ledger", row)
    except Exception as e:
        logger.warning(f"[balances] grant failed: {e}")
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "granted": amount, "kind": kind, "unit": unit,
            "balance": balance(business_id, contact_id, kind, unit)}


def consume(business_id: str, contact_id: str, amount: float, kind: str, unit: str,
            reason: str, *, allow_overdraw: bool = False,
            booking_id: Optional[str] = None, session_id: Optional[str] = None,
            invoice_id: Optional[str] = None,
            created_by: Optional[str] = None) -> Dict[str, Any]:
    """Draw down a balance.

    Refuses by default when the balance will not cover it — a coach whose
    client has run out should be told, not silently put into debt. Pass
    allow_overdraw=True for the cases where the work genuinely happened
    anyway and the practitioner will settle it.

    See the module docstring on the overdraw race: this re-reads after
    writing and reverses its own row if it lost, rather than claiming a
    safety it cannot provide across two PostgREST calls.
    """
    err = _validate(kind, unit)
    if err:
        return {"ok": False, "error": err}
    amount = _num(amount)
    if amount <= 0:
        return {"ok": False, "error": "consume amount must be positive"}
    if not (reason or "").strip():
        return {"ok": False, "error": "reason is required"}

    available = balance(business_id, contact_id, kind, unit)
    if available < amount and not allow_overdraw:
        return {"ok": False, "error": "insufficient balance",
                "available": available, "requested": amount,
                "kind": kind, "unit": unit,
                "shortfall": round(amount - available, 4)}

    import sb_clients
    row = {
        "business_id": business_id, "contact_id": contact_id,
        "kind": kind, "unit": unit, "delta": -amount,
        "reason": reason.strip(), "booking_id": booking_id,
        "session_id": session_id, "invoice_id": invoice_id,
        "created_by": created_by,
    }
    try:
        written = sb_clients.sb_post_as_service("/customer_ledger", row)
    except Exception as e:
        logger.warning(f"[balances] consume failed: {e}")
        return {"ok": False, "error": str(e)[:200]}

    after = balance(business_id, contact_id, kind, unit)

    # Lost-race self-correction. If we did not intend an overdraw and the
    # post-write balance is negative, someone else drew between our read
    # and our write. Reverse OUR row and report honestly.
    if after < 0 and not allow_overdraw:
        rid = None
        if isinstance(written, list) and written:
            rid = written[0].get("id")
        reversed_ok = False
        if rid:
            try:
                sb_clients.sb_post_as_service("/customer_ledger", {
                    "business_id": business_id, "contact_id": contact_id,
                    "kind": kind, "unit": unit, "delta": amount,
                    "reason": f"Reversal of concurrent overdraw ({reason.strip()})",
                    "created_by": created_by,
                })
                reversed_ok = True
            except Exception as e:
                logger.error(f"[balances] OVERDRAW REVERSAL FAILED for "
                             f"{business_id}/{contact_id}: {e}")
        return {"ok": False, "error": "insufficient balance (concurrent draw)",
                "overdrawn": True, "reversed": reversed_ok,
                "available": after + amount, "requested": amount}

    return {"ok": True, "consumed": amount, "kind": kind, "unit": unit,
            "balance": after, "low": after <= 1 and unit == "session"}


def describe_balances(business_id: str, contact_id: str) -> str:
    """One human line — for Chief replies and contact_deep_dive."""
    rows = balances_for_contact(business_id, contact_id)
    if not rows:
        return "no prepaid balance"
    parts = []
    for r in rows:
        bal = _num(r.get("balance"))
        unit = r.get("unit")
        kind = r.get("kind")
        if unit == "money":
            parts.append(f"{kind}: ${bal:,.2f}")
        elif unit == "hour":
            parts.append(f"{kind}: {bal:g} hours")
        else:
            parts.append(f"{kind}: {bal:g} session{'' if bal == 1 else 's'}")
    return " · ".join(parts)
