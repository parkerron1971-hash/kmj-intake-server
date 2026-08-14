"""
chief_time_actions.py — Chief verbs for billable time.

"Log 90 minutes on the Henderson matter — drafting the response" is the
sentence this exists to make work. Without verbs, time_entries would be a
table nobody can reach from the one surface practitioners actually use.

Every handler returns `result` AND `label` per the house contract — a
missing label crashes the client on toLowerCase.

CLASSIFICATION
  log_time and write_off_time are class A: they record what already
  happened, send nothing, and touch no Stripe object.

  bill_time_to_retainer is ALSO class A, and that is worth defending. It
  moves a prepaid balance the client already funded, posts no GL entry, and
  reaches nothing external. It is the same reasoning as consume_balance,
  which it delegates to.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import billable_time as bt


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}",
            "label": msg[:80], "nav": None}


async def _resolve_contact(client, biz, action) -> Optional[Dict[str, Any]]:
    from chief_of_staff import _validate_contact
    return await _validate_contact(client, biz["id"], action.get("contact_id"))


def _nav_contact(contact) -> Optional[Dict[str, Any]]:
    try:
        from chief_of_staff import _nav
        return _nav("operate", "contacts", contact["id"])
    except Exception:
        return None


async def handle_log_time(client, biz, action) -> Dict[str, Any]:
    """Record billable (or non-billable) work against a client."""
    contact = await _resolve_contact(client, biz, action)
    if not contact:
        return _fail("log_time", f"Contact {action.get('contact_id')} not found")

    minutes = bt.parse_duration(
        action.get("minutes") if action.get("minutes") is not None
        else action.get("duration") or action.get("hours"))
    if not minutes:
        return _fail("log_time",
                     "couldn't read the duration — try '90m', '1.5h' or '1:30'")

    description = (action.get("description") or action.get("what") or "").strip()
    if not description:
        return _fail("log_time",
                     "what was the work? a bill line with no narrative is a "
                     "fee dispute waiting to happen")

    rate = action.get("rate")
    try:
        rate = float(rate) if rate not in (None, "") else None
    except (TypeError, ValueError):
        rate = None

    res = await asyncio.to_thread(
        bt.log_time, biz["id"], contact["id"], minutes, description,
        rate=rate, billable=action.get("billable", True) is not False,
        matter_ref=action.get("matter") or action.get("matter_ref"),
        occurred_on=action.get("date") or action.get("occurred_on"),
        created_by=biz.get("owner_id"))
    if not res.get("ok"):
        return _fail("log_time", res.get("error") or "could not log time")

    tail = ""
    if res.get("rounded_from"):
        tail = f" (rounded up from {res['rounded_from']}m)"
    money = f" · ${res['amount']:,.2f}" if res.get("amount") else ""
    return {
        "type": "log_time",
        "result": (f"logged {res['hours']}h for {contact.get('name')}"
                   f"{tail}{money} — {description}"),
        "label": f"{contact.get('name')}: {res['hours']}h logged",
        "nav": _nav_contact(contact),
    }


async def handle_bill_time_to_retainer(client, biz, action) -> Dict[str, Any]:
    """Draw a logged entry against the client's prepaid retainer hours."""
    contact = await _resolve_contact(client, biz, action)
    if not contact:
        return _fail("bill_time_to_retainer",
                     f"Contact {action.get('contact_id')} not found")

    entry_id = (action.get("entry_id") or action.get("time_entry_id") or "").strip()
    if not entry_id:
        return _fail("bill_time_to_retainer", "entry_id required")

    res = await asyncio.to_thread(
        bt.bill_to_retainer, biz["id"], contact["id"], entry_id,
        created_by=biz.get("owner_id"))
    if not res.get("ok"):
        if res.get("available") is not None:
            return {
                "type": "bill_time_to_retainer",
                "result": (f"not enough retainer — {contact.get('name')} has "
                           f"{res['available']:g}h left, this entry needs "
                           f"{res['requested']:g}h. Top up the retainer or "
                           f"invoice it instead."),
                "label": f"{contact.get('name')}: retainer short",
                "nav": _nav_contact(contact),
            }
        return _fail("bill_time_to_retainer", res.get("error") or "could not bill")

    return {
        "type": "bill_time_to_retainer",
        "result": (f"billed {res['hours']}h to {contact.get('name')}'s "
                   f"retainer — {res['retainer_left']:g}h remaining"),
        "label": f"{contact.get('name')}: {res['retainer_left']:g}h retainer left",
        "nav": _nav_contact(contact),
    }


async def handle_unbilled_time(client, biz, action) -> Dict[str, Any]:
    """What work has been done and not yet billed. Pure read."""
    contact = None
    if action.get("contact_id"):
        contact = await _resolve_contact(client, biz, action)
        if not contact:
            return _fail("unbilled_time",
                         f"Contact {action.get('contact_id')} not found")

    summary = await asyncio.to_thread(
        bt.unbilled_summary, biz["id"], contact["id"] if contact else None)

    who = f" for {contact.get('name')}" if contact else ""
    if not summary["entries"]:
        return {"type": "unbilled_time", "result": f"nothing unbilled{who}",
                "label": f"No unbilled time{who}", "nav": None,
                "signal": {"entries": 0}}

    money = f" · ${summary['amount']:,.2f}" if summary["amount"] else ""
    unpriced = (f" ({summary['unpriced_entries']} with no rate set)"
                if summary["unpriced_entries"] else "")
    return {
        "type": "unbilled_time",
        "result": (f"{summary['hours']}h unbilled{who} across "
                   f"{summary['entries']} entries{money}{unpriced}"),
        "label": f"{summary['hours']}h unbilled{money}",
        "nav": _nav_contact(contact) if contact else None,
        # Machine-readable twin of `result`. The prose above is for a
        # human; anything deciding on this (the MCP handoff table, a
        # future card) reads numbers, because a predicate that greps a
        # sentence breaks the day the sentence is reworded.
        "signal": {"entries": summary["entries"], "hours": summary["hours"],
                   "amount": summary["amount"], "contact": bool(contact)},
    }


async def handle_write_off_time(client, biz, action) -> Dict[str, Any]:
    """Mark time as never-to-be-billed."""
    entry_id = (action.get("entry_id") or action.get("time_entry_id") or "").strip()
    if not entry_id:
        return _fail("write_off_time", "entry_id required")
    res = await asyncio.to_thread(bt.write_off, biz["id"], entry_id)
    if not res.get("ok"):
        return _fail("write_off_time", res.get("error") or "could not write off")
    return {"type": "write_off_time", "result": "written off",
            "label": "Time written off", "nav": None}
