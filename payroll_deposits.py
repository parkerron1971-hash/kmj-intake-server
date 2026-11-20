"""payroll_deposits.py — tax deposits and forms marked sent, and the reminders' ledger.

Payroll, the free version (2026-11-19): the church sends its own tax deposits
(EFTPS for the IRS, its state's portal) and files its own forms. When it has,
someone presses "Mark sent" and the calendar says so; the reminders stop.

Two server-only tables (supabase/APPLY-2026-11-19-payroll-deposits.sql, NOT
applied until Kevin applies it):

    payroll_deposits ........ one row per (business, key): the amount, the
                              day it was sent, a reference, who marked it.
                              Marking again updates the row; undo deletes it
    payroll_reminders_sent .. one row per (business, key, audience): the
                              reminders' memory, claimed before an alert goes,
                              so nobody hears the same thing twice

Until the file is applied: the calendar reads "nothing marked", marking a
deposit answers 503 with NOT_READY, and the reminders skip. Whether a table
answers is asked once and kept for good once it does; a "no" is asked again
in five minutes (church_money_ticks.tables_ready's pattern).

Logs carry ids and counts only: never an amount, a name or an email.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("payroll_deposits")

DEPOSITS = "payroll_deposits"
REMINDERS = "payroll_reminders_sent"
NOT_READY = "Deposit tracking is being switched on. Try again shortly."
SAVE_503 = "That didn't save. Nothing changed. Try again."
READ_503 = "The deposits couldn't be read just now. Try again."
_SELECT = "business_id,key,kind,period,amount,due_on,sent_on,reference,marked_by,marked_at"

_READY: Dict[str, Dict[str, float]] = {DEPOSITS: {"yes": 0.0, "until": 0.0},
                                       REMINDERS: {"yes": 0.0, "until": 0.0}}
_RETRY_S = 300.0


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def ready(table: str = DEPOSITS) -> bool:
    """Whether the table answers (the migration is applied)."""
    st = _READY[table]
    if st["yes"]:
        return True
    if time.monotonic() < st["until"]:
        return False
    ok = isinstance(sb_clients.sb_get_as_service(f"/{table}?select=business_id&limit=1"), list)
    st["yes"] = 1.0 if ok else 0.0
    st["until"] = 0.0 if ok else time.monotonic() + _RETRY_S
    if not ok:
        # Railway shows print() only.
        print(f"[payroll] {table} doesn't answer yet: supabase/APPLY-2026-11-19-payroll-deposits.sql "
              "isn't applied (or the read failed); deposits read as none marked", flush=True)
    return ok


def forget_ready() -> None:
    for st in _READY.values():
        st.update(yes=0.0, until=0.0)


def marked(business_id: str) -> Tuple[Optional[Dict[str, Dict[str, Any]]], bool]:
    """(key → row for every deposit or form marked sent, whether the table is
    there). Before the migration: ({}, False), "nothing marked". After it, a
    read that fails is (None, True): the caller says so, never "open"."""
    if not ready(DEPOSITS):
        return {}, False
    rows = sb_clients.sb_get_as_service(
        f"/{DEPOSITS}?business_id=eq.{_q(business_id)}&select={_SELECT}&order=key.asc&limit=1000", redact=True)
    if not isinstance(rows, list):
        return None, True
    return {str(r.get("key")): r for r in rows if isinstance(r, dict) and r.get("key")}, True


def public(row: Dict[str, Any]) -> Dict[str, Any]:
    def num(v: Any) -> Optional[float]:
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None
    return {"key": row.get("key"), "kind": row.get("kind"), "period": row.get("period"),
            "amount": num(row.get("amount")), "due_on": row.get("due_on"), "sent_on": row.get("sent_on"),
            "reference": row.get("reference"), "marked_at": row.get("marked_at")}


class NotReady(Exception):
    """The tables aren't there yet."""


class SaveFailed(Exception):
    """A write that didn't go through."""


def mark_sent(business_id: str, key: str, parsed: Dict[str, Any], *, amount: float, sent_on: date,
              reference: Optional[str], due_on: Optional[date], by: str) -> Dict[str, Any]:
    """Mark one deposit or form sent; a second call for the same key updates
    its amount, day and reference (one row per business and key)."""
    if not ready(DEPOSITS):
        raise NotReady()
    row = {
        "business_id": str(business_id), "key": key, "kind": parsed["kind"], "period": parsed["period"],
        "amount": round(float(amount), 2), "due_on": due_on.isoformat() if due_on else None,
        "sent_on": sent_on.isoformat(), "reference": reference or None, "marked_by": str(by),
        "marked_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = sb_clients.sb_post_as_service(
        f"/{DEPOSITS}?on_conflict=business_id,key", row,
        prefer="resolution=merge-duplicates,return=representation", redact=True)
    if not isinstance(saved, list) or not saved:
        raise SaveFailed()
    logger.info("[payroll] deposit marked sent biz=%s kind=%s", str(business_id)[:8], parsed["kind"])
    return saved[0] if isinstance(saved[0], dict) else row


def undo(business_id: str, key: str) -> None:
    """Take a "sent" back. Nothing there is not an error (undo twice)."""
    if not ready(DEPOSITS):
        raise NotReady()
    if not sb_clients.sb_delete_as_service(f"/{DEPOSITS}?business_id=eq.{_q(business_id)}&key=eq.{_q(key)}"):
        raise SaveFailed()
    logger.info("[payroll] deposit mark undone biz=%s", str(business_id)[:8])


def deposited(marked_rows: Dict[str, Dict[str, Any]], keys) -> float:
    total = 0.0
    for k in keys:
        r = marked_rows.get(k)
        if r:
            try:
                total += float(r.get("amount") or 0)
            except (TypeError, ValueError):
                pass
    return round(total + 1e-9, 2)


# ─── The reminders' memory ────────────────────────────────────────────

def claim_reminder(business_id: str, key: str, audience: str, day: date) -> Optional[bool]:
    """Claim one reminder before it goes: True when this call claimed it,
    False when it was claimed before (any day), None when the write failed
    (nothing is sent then; the next hour tries again)."""
    got = sb_clients.sb_post_as_service(
        f"/{REMINDERS}?on_conflict=business_id,key,audience",
        {"business_id": str(business_id), "key": key, "audience": audience, "sent_on": day.isoformat()},
        prefer="resolution=ignore-duplicates,return=representation", redact=True)
    if not isinstance(got, list):
        return None
    return bool(got)
