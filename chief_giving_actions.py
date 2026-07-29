"""
chief_giving_actions.py — Chief verbs for contribution statements.

"Print Marcus's giving statement for last year" and "run the January
statements" are the two sentences this exists to make work. Both are reads
and both are marked SENSITIVE in action_registry — a congregation's giving
history does not go on an agent surface.

Handlers return `result` AND `label` per the house contract.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Dict, Optional

import giving_statements as gs


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}",
            "label": msg[:80], "nav": None}


def _year(action: Dict[str, Any]) -> int:
    """Default to LAST year, not this one. Statements are a January job for
    the year that just closed; defaulting to the current year would hand
    someone a half-finished document in most months they ask."""
    raw = action.get("year")
    try:
        y = int(raw)
        if 2000 <= y <= 2200:
            return y
    except (TypeError, ValueError):
        pass
    today = date.today()
    return today.year - 1 if today.month <= 6 else today.year


async def handle_giving_statement(client, biz, action) -> Dict[str, Any]:
    """One donor's annual contribution statement."""
    from chief_of_staff import _validate_contact, _nav
    contact = await _validate_contact(client, biz["id"], action.get("contact_id"))
    if not contact:
        return _fail("giving_statement",
                     f"Contact {action.get('contact_id')} not found")

    year = _year(action)
    stmt = await asyncio.to_thread(
        gs.statement_for_contact, biz["id"], contact["id"], year,
        org_name=biz.get("name"),
        goods_and_services=action.get("goods_and_services") or "none")

    if stmt.get("empty"):
        return {"type": "giving_statement",
                "result": f"{contact.get('name')} has no recorded gifts in {year}",
                "label": f"No {year} gifts for {contact.get('name')}",
                "nav": _nav("operate", "contacts", contact["id"])}

    text = gs.render_text(stmt)
    warn = ("" if stmt["statement_complete"]
            else " — NOT ready to send, a good-faith value estimate is required")
    ack = len(stmt["gifts_requiring_acknowledgment"])
    ack_note = f" · {ack} gift{'' if ack == 1 else 's'} at/over $250" if ack else ""

    return {
        "type": "giving_statement",
        "result": (f"{year} statement for {contact.get('name')}: "
                   f"${stmt['total']:,.2f} across {stmt['gift_count']} "
                   f"gift{'' if stmt['gift_count'] == 1 else 's'}"
                   f"{ack_note}{warn}"),
        "label": f"{contact.get('name')} — {year}: ${stmt['total']:,.2f}",
        "statement": text,
        "summary": text,
        "nav": _nav("operate", "contacts", contact["id"]),
    }


async def handle_giving_statements_run(client, biz, action) -> Dict[str, Any]:
    """Every donor's totals for a tax year — the January mailing."""
    year = _year(action)
    run = await asyncio.to_thread(
        gs.statements_for_year, biz["id"], year,
        org_name=biz.get("name"),
        goods_and_services=action.get("goods_and_services") or "none")

    if not run["donor_count"]:
        return {"type": "giving_statements_run",
                "result": f"no recorded gifts in {year}",
                "label": f"No {year} giving on record", "nav": None}

    needing = sum(1 for d in run["donors"] if d["needs_acknowledgment"])
    unattrib = (f" · ${run['unattributed_total']:,.2f} unattributed"
                if run["unattributed_total"] else "")
    lines = "\n".join(
        f"  {d['name'] or '(no name)'}: ${d['total']:,.2f} "
        f"({d['gift_count']} gift{'' if d['gift_count'] == 1 else 's'})"
        + ("  ← needs written acknowledgment" if d["needs_acknowledgment"] else "")
        for d in run["donors"][:50])

    return {
        "type": "giving_statements_run",
        "result": (f"{year}: {run['donor_count']} donors, "
                   f"${run['total_recorded']:,.2f} total. "
                   f"{needing} need a written acknowledgment (gift of $250+)"
                   f"{unattrib}"),
        "label": f"{year} giving — {run['donor_count']} donors, "
                 f"${run['total_recorded']:,.2f}",
        "summary": lines,
        "nav": None,
    }
