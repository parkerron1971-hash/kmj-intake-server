"""
billable_time.py — what work was done, and whether it has been paid for.

THE GAP THIS CLOSES
  The readiness audit scored lawyers 7/12 with an odd shape to the missing
  half: IOLTA trust reconciliation with per-client sub-balances was already
  BUILT (gl_reports_t4), but a grep for time_entries / billable_hours /
  hourly_rate returned zero across the repo. A firm could reconcile client
  trust funds to the penny and had nowhere to record that somebody worked
  ninety minutes on a matter.

MINUTES, NOT HOURS
  Legal billing runs in tenths of an hour. As floats, 0.1 + 0.2 != 0.3, and
  a drifted bill is not a rounding curiosity — it is a fee dispute. Minutes
  are integers everywhere in this module; tenths are presentation only, and
  parsing rounds UP to the firm's increment the way a firm actually bills.

TWO TABLES, TWO QUESTIONS
  time_entries    — what WORK was done (the narrative the client reads)
  customer_ledger — what the client PREPAID and has left (the retainer)

  Billing an entry against a retainer writes to both and links them by
  ledger_entry_id, so the same ninety minutes can never be billed twice.
  That link is the whole reason this module talks to customer_balances
  rather than keeping its own balance.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger("billable_time")

# Most firms bill in 6-minute (0.1h) increments. Configurable per business
# later; six is the default because it is the legal-industry norm.
DEFAULT_INCREMENT_MIN = 6


def round_to_increment(minutes: int, increment: int = DEFAULT_INCREMENT_MIN) -> int:
    """Round UP to the billing increment — how firms actually bill. Four
    minutes of work is billed as a tenth of an hour, not discarded."""
    if increment <= 1:
        return int(minutes)
    return int(math.ceil(minutes / increment) * increment)


def parse_duration(raw: Any) -> Optional[int]:
    """Accept what a practitioner would actually say and return MINUTES.

        90        -> 90     (bare number = minutes)
        "90m"     -> 90
        "1.5h"    -> 90
        "1:30"    -> 90
        1.5       -> 90     (bare float = hours; nobody says 1.5 minutes)

    The float rule is the one worth stating: an integer is minutes and a
    fraction is hours, because "log 1.5" means an hour and a half and
    "log 90" means ninety minutes. Returns None when it cannot tell.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float):
        return int(round(raw * 60)) if raw > 0 else None

    s = str(raw).strip().lower().replace(" ", "")
    if not s:
        return None
    try:
        if ":" in s:                                  # 1:30
            h, m = s.split(":", 1)
            out = int(h) * 60 + int(m)
        elif s.endswith("h"):                         # 1.5h
            out = int(round(float(s[:-1]) * 60))
        elif s.endswith("m") or s.endswith("min"):    # 90m
            out = int(float(s.rstrip("min").rstrip("m")))
        else:
            v = float(s)
            out = int(v) if v.is_integer() else int(round(v * 60))
    except (ValueError, TypeError):
        return None
    # Single exit guard. "-1h" parsed cleanly to -60 before this existed;
    # log_time would have rejected it, but a parser that hands back a
    # negative duration and leaves the caller to notice is the wrong shape.
    return out if out > 0 else None


def format_hours(minutes: int) -> str:
    """0.1-hour presentation, the way it appears on a bill."""
    return f"{minutes / 60:.1f}"


# ─────────────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────────────

def log_time(business_id: str, contact_id: str, minutes: int, description: str,
             *, rate: Optional[float] = None, billable: bool = True,
             matter_ref: Optional[str] = None, occurred_on: Optional[str] = None,
             increment: int = DEFAULT_INCREMENT_MIN,
             created_by: Optional[str] = None) -> Dict[str, Any]:
    """Record work done. Does NOT bill it — see bill_to_retainer."""
    if not (description or "").strip():
        return {"ok": False, "error": "description is required — a bill line "
                                      "with no narrative is a fee dispute"}
    try:
        mins = int(minutes)
    except (TypeError, ValueError):
        return {"ok": False, "error": "minutes must be a whole number"}
    if mins <= 0:
        return {"ok": False, "error": "minutes must be positive"}
    if mins > 1440:
        return {"ok": False, "error": "a single entry cannot exceed 24 hours"}

    billed_mins = round_to_increment(mins, increment)

    import sb_clients
    row = {
        "business_id": business_id, "contact_id": contact_id,
        "description": description.strip(), "minutes": billed_mins,
        "rate": rate, "billable": bool(billable),
        "matter_ref": matter_ref, "status": "unbilled",
        "occurred_on": occurred_on or date.today().isoformat(),
        "created_by": created_by,
    }
    try:
        written = sb_clients.sb_post_as_service("/time_entries", row)
    except Exception as e:
        logger.warning(f"[time] log failed: {e}")
        return {"ok": False, "error": str(e)[:200]}

    entry_id = written[0].get("id") if isinstance(written, list) and written else None
    return {"ok": True, "id": entry_id, "minutes": billed_mins,
            "rounded_from": mins if billed_mins != mins else None,
            "hours": format_hours(billed_mins),
            "amount": round((rate or 0) * billed_mins / 60, 2) if rate else None}


def bill_to_retainer(business_id: str, contact_id: str, entry_id: str,
                     created_by: Optional[str] = None) -> Dict[str, Any]:
    """Draw an unbilled entry against the client's prepaid retainer hours.

    Order matters. The ledger draw happens FIRST and the entry is only
    marked billed if it succeeded — so a client without enough retainer
    leaves the entry unbilled and billable another way, rather than marked
    paid against a draw that never landed.
    """
    import sb_clients
    import customer_balances as cb

    rows = sb_clients.sb_get_as_service(
        f"/time_entries?id=eq.{entry_id}&business_id=eq.{business_id}"
        "&select=*&limit=1") or []
    if not rows:
        return {"ok": False, "error": "time entry not found"}
    entry = rows[0]

    if entry.get("status") != "unbilled":
        return {"ok": False, "error": f"already {entry.get('status')}"}
    if not entry.get("billable"):
        return {"ok": False, "error": "entry is marked non-billable"}

    hours = float(entry["minutes"]) / 60.0
    draw = cb.consume(
        business_id, contact_id, hours, "retainer", "hour",
        f"Billed: {entry.get('description')}",
        created_by=created_by)
    if not draw.get("ok"):
        return {"ok": False, "error": draw.get("error"),
                "available": draw.get("available"), "requested": hours}

    # The ledger row is the proof this was paid for. Without capturing its
    # id the entry could be billed again against the same retainer.
    ledger_id = None
    try:
        recent = sb_clients.sb_get_as_service(
            f"/customer_ledger?business_id=eq.{business_id}"
            f"&contact_id=eq.{contact_id}&order=created_at.desc&limit=1"
            "&select=id") or []
        ledger_id = recent[0].get("id") if recent else None
    except Exception as e:
        logger.warning(f"[time] could not capture ledger id: {e}")

    try:
        sb_clients.sb_patch_as_service(
            f"/time_entries?id=eq.{entry_id}",
            {"status": "billed", "ledger_entry_id": ledger_id})
    except Exception as e:
        # The draw succeeded but the entry did not move. Say so loudly —
        # silently returning ok would let it be billed a second time.
        logger.error(f"[time] retainer drawn but entry {entry_id} not marked "
                     f"billed: {e}")
        return {"ok": False, "error": "retainer was drawn but the entry could "
                                      "not be marked billed — reconcile manually",
                "ledger_entry_id": ledger_id}

    return {"ok": True, "hours": format_hours(entry["minutes"]),
            "retainer_left": draw.get("balance"), "ledger_entry_id": ledger_id}


def write_off(business_id: str, entry_id: str) -> Dict[str, Any]:
    """Mark time as never-to-be-billed. Reversible by editing the row."""
    import sb_clients
    try:
        sb_clients.sb_patch_as_service(
            f"/time_entries?id=eq.{entry_id}&business_id=eq.{business_id}"
            "&status=eq.unbilled",
            {"status": "written_off"})
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────

def unbilled(business_id: str, contact_id: Optional[str] = None,
             limit: int = 100) -> List[Dict[str, Any]]:
    import sb_clients
    q = (f"/time_entries?business_id=eq.{business_id}&status=eq.unbilled"
         f"&billable=eq.true&order=occurred_on.desc&limit={int(limit)}"
         "&select=id,contact_id,description,minutes,rate,occurred_on,matter_ref")
    if contact_id:
        q += f"&contact_id=eq.{contact_id}"
    return sb_clients.sb_get_as_service(q) or []


def unbilled_summary(business_id: str,
                     contact_id: Optional[str] = None) -> Dict[str, Any]:
    """Totals for "what am I owed". Entries with no rate contribute time but
    not money, and are counted separately so the number is never quietly
    understated."""
    rows = unbilled(business_id, contact_id, limit=500)
    minutes = sum(int(r.get("minutes") or 0) for r in rows)
    amount, unpriced = 0.0, 0
    for r in rows:
        rate = r.get("rate")
        if rate in (None, ""):
            unpriced += 1
        else:
            amount += float(rate) * int(r.get("minutes") or 0) / 60.0
    return {"entries": len(rows), "minutes": minutes,
            "hours": format_hours(minutes), "amount": round(amount, 2),
            "unpriced_entries": unpriced}
