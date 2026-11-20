"""payroll_carry.py — last time's typed withholding, carried into a new run.

Payroll, the free version (2026-11-19). Federal and state income tax
withholding are typed by the church (payroll_calc never computes them). When
a run is drafted, each person's figures are copied from their latest approved
or paid line, if how they're paid hasn't changed since: the same pay type,
rate and frequency. The line then says where they came from
(calc_payload.carried_from = that run's id, carried_from_pay_date = its pay
date), and the app shows "carried over from Nov 13" beside them. Typing a new
figure on the line drops the note (payroll_router.update_item).

An HOURLY line carries only when this check's pay equals the copied line's
(check()): otherwise the line needs typing and calc_payload.carry_note says
why. Changing a carried hourly line's hours later clears what was carried, the
same way. And approve refuses any line whose take-home would be below zero.

How they were paid on a line is kept on the line from now on
(calc_payload.pay = {type, rate, frequency}). A line written before this has
no such record; for those, "unchanged" means the line's own hours, paid on
today's terms, come to the same gross it had (and it had one).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import payroll_calc
import sb_clients

CARRY_KEYS = ("carried_from", "carried_from_pay_date", "carried_item", "carried_gross", "carry_note")


def terms(employee: Dict[str, Any]) -> Dict[str, Any]:
    """How a person is paid, as a line records it."""
    return {"type": employee.get("pay_type") or "hourly",
            "rate": round(float(employee.get("pay_rate") or 0), 2),
            "frequency": employee.get("pay_frequency") or "biweekly"}


def unchanged(item: Dict[str, Any], employee: Dict[str, Any]) -> bool:
    payload = item.get("calc_payload") if isinstance(item.get("calc_payload"), dict) else {}
    then = payload.get("pay") if isinstance(payload.get("pay"), dict) else None
    now = terms(employee)
    if then is not None:
        try:
            return (then.get("type") == now["type"] and then.get("frequency") == now["frequency"]
                    and round(float(then.get("rate") or 0), 2) == now["rate"])
        except (TypeError, ValueError):
            return False
    gross = float(item.get("gross") or 0)
    if gross <= 0:
        return False
    again = payroll_calc.gross_for(employee, float(item.get("hours") or 0), float(item.get("overtime_hours") or 0))
    return abs(again - gross) < 0.005


def sources(business_id: str, employees: List[Dict[str, Any]],
            exclude_run_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """employee id → {run_id, pay_date, item_id, federal, state} to carry, for
    each person whose latest approved or paid line can be carried. A read
    that fails carries nothing (the lines then need typing, as before)."""
    b = quote(str(business_id), safe="")
    runs = sb_clients.sb_get_as_service(
        f"/pay_runs?business_id=eq.{b}&status=in.(approved,paid)&select=id,pay_date"
        f"&order=pay_date.desc&limit=200")
    if not isinstance(runs, list) or not runs:
        return {}
    by_run = {str(r["id"]): r for r in runs if r.get("id") and str(r.get("id")) != str(exclude_run_id or "")}
    out: Dict[str, Dict[str, Any]] = {}
    for emp in employees:
        items = sb_clients.sb_get_as_service(
            f"/pay_run_items?business_id=eq.{b}&employee_id=eq.{quote(str(emp['id']), safe='')}"
            f"&select=id,pay_run_id,gross,hours,overtime_hours,federal_withholding,state_withholding,"
            f"calc_payload,created_at&order=created_at.desc&limit=50")
        if not isinstance(items, list):
            continue
        mine = [i for i in items if str(i.get("pay_run_id")) in by_run]
        if not mine:
            continue
        mine.sort(key=lambda i: (str(by_run[str(i["pay_run_id"])].get("pay_date") or ""),
                                 str(i.get("created_at") or "")), reverse=True)
        last = mine[0]
        if last.get("federal_withholding") is None and last.get("state_withholding") is None:
            continue
        if not unchanged(last, emp):
            continue
        run = by_run[str(last["pay_run_id"])]
        out[str(emp["id"])] = {"run_id": str(run["id"]), "pay_date": str(run.get("pay_date") or "")[:10],
                               "item_id": str(last.get("id")), "gross": round(float(last.get("gross") or 0), 2),
                               "federal": last.get("federal_withholding"), "state": last.get("state_withholding")}
    return out


def _when(src: Dict[str, Any]) -> str:
    try:
        from datetime import date
        from payroll_calendar import short_day
        return short_day(date.fromisoformat(str(src.get("pay_date") or "")[:10]))
    except ValueError:
        return "last"


def check(src: Optional[Dict[str, Any]], employee: Dict[str, Any],
          new_gross: float) -> "tuple[Optional[Dict[str, Any]], Optional[str]]":
    """(what to carry, or None; and why nothing was, for the line's note).
    Withholding follows the size of the check: a salary is the same every
    period, but an hourly check with different hours is a different check,
    and last time's figures could take more than it pays (a 4-hour check
    carrying an 80-hour check's $390 would leave take-home below zero). So an
    hourly line carries only when its pay equals the line it would copy."""
    if not src:
        return None, None
    if terms(employee)["type"] == "hourly" and abs(float(src.get("gross") or 0) - float(new_gross or 0)) >= 0.005:
        return None, (f"Nothing was carried over from the {_when(src)} run: this check’s pay "
                      f"(${float(new_gross or 0):,.2f}) isn’t that one’s (${float(src.get('gross') or 0):,.2f}), so "
                      f"its federal and state withholding need typing.")
    return src, None


HOURS_CHANGED = ("The hours changed after the withholding was carried over from the {when} run, so it was "
                 "cleared: type this check’s federal and state withholding.")


def payload(employee: Dict[str, Any], carried: Optional[Dict[str, Any]] = None,
            before: Optional[Dict[str, Any]] = None, note: Optional[str] = None) -> Dict[str, Any]:
    """A line's calc_payload: what it had, how the person is paid now, and
    (when given) where its withholding was carried from, or why it wasn't."""
    out = dict(before) if isinstance(before, dict) else {}
    out["pay"] = terms(employee)
    if carried:
        out["carried_from"] = carried["run_id"]
        out["carried_from_pay_date"] = carried["pay_date"]
        out["carried_item"] = carried["item_id"]
        out["carried_gross"] = carried.get("gross")
    if note:
        out["carry_note"] = note
    return out


def dropped(before: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The payload without the carried-over note (a figure was typed again)."""
    return {k: v for k, v in (before or {}).items() if k not in CARRY_KEYS}
