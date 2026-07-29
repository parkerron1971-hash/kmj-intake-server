"""
chief_balance_actions.py — Chief verbs for the customer drawdown ledger.

THE GAP THIS CLOSES
  customer_balances.py gives the system a place to record that a client
  bought six sessions and has used two. Without verbs it would be a module
  with a table and no way in — which is precisely the "UI but no Chief-
  callable action interface" failure the readiness audit lists separately.
  A practitioner should be able to say "Marcus bought the 6-session package"
  and "log a session for Marcus" and have both land.

  Handlers follow the house contract: every return carries `result` AND
  `label`, because a missing label crashes the client on toLowerCase.

CLASSIFICATION
  grant_balance and consume_balance are class A writes. They record what
  already happened between two people — money that changed hands offline,
  a session that was delivered. They send nothing, touch no Stripe object,
  and post no GL entry. A wrong one is corrected by an adjusting row, which
  is exactly the class A test.

  They are NOT class C despite being money-adjacent, and the distinction is
  worth stating: create_invoice is C because it can arm an unattended send
  and reaches Stripe. These verbs reach neither. They are bookkeeping about
  money, not movement of it.

  check_balance is a read.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import customer_balances as cb

logger = logging.getLogger("chief_balance_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}", "label": msg[:80],
            "nav": None}


async def _resolve_contact(client, biz, action) -> Optional[Dict[str, Any]]:
    """Reuse chief_of_staff's contact validation so name-vs-id resolution
    and business scoping behave identically to every other verb."""
    from chief_of_staff import _validate_contact
    return await _validate_contact(client, biz["id"], action.get("contact_id"))


def _kind_unit(biz: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, str]:
    """Explicit args win; otherwise fall back to what this vertical most
    naturally prepays in, so Chief does not have to interrogate the
    practitioner about ledger taxonomy to record a package sale."""
    d = cb.defaults_for_vertical(biz.get("type"))
    return {
        "kind": (action.get("kind") or d["kind"]).strip().lower(),
        "unit": (action.get("unit") or d["unit"]).strip().lower(),
    }


async def handle_grant_balance(client, biz, action) -> Dict[str, Any]:
    """Record that a customer prepaid for something not yet delivered."""
    contact = await _resolve_contact(client, biz, action)
    if not contact:
        return _fail("grant_balance",
                     f"Contact {action.get('contact_id')} not found")

    try:
        amount = float(action.get("amount"))
    except (TypeError, ValueError):
        return _fail("grant_balance", "amount must be a number")

    ku = _kind_unit(biz, action)
    reason = (action.get("reason") or "").strip() or \
             f"{ku['kind'].replace('_', ' ').title()} purchased"

    res = await asyncio.to_thread(
        cb.grant, biz["id"], contact["id"], amount, ku["kind"], ku["unit"],
        reason,
        offering_id=action.get("offering_id"),
        invoice_id=action.get("invoice_id"),
        expires_at=action.get("expires_at"),
        created_by=biz.get("owner_id"),
    )
    if not res.get("ok"):
        return _fail("grant_balance", res.get("error") or "grant failed")

    unit_word = _unit_word(ku["unit"], res.get("granted"))
    return {
        "type": "grant_balance",
        "result": (f"granted {_fmt(res['granted'], ku['unit'])} {unit_word} "
                   f"— {contact.get('name')} now has "
                   f"{_fmt(res['balance'], ku['unit'])}"),
        "label": f"{contact.get('name')}: +{_fmt(res['granted'], ku['unit'])} {unit_word}",
        "nav": _contact_nav(contact),
    }


async def handle_consume_balance(client, biz, action) -> Dict[str, Any]:
    """Draw down a prepaid balance — a session delivered, an hour billed."""
    contact = await _resolve_contact(client, biz, action)
    if not contact:
        return _fail("consume_balance",
                     f"Contact {action.get('contact_id')} not found")

    raw = action.get("amount", 1)
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return _fail("consume_balance", "amount must be a number")

    ku = _kind_unit(biz, action)
    reason = (action.get("reason") or "").strip() or "Delivered"

    res = await asyncio.to_thread(
        cb.consume, biz["id"], contact["id"], amount, ku["kind"], ku["unit"],
        reason,
        allow_overdraw=bool(action.get("allow_overdraw")),
        booking_id=action.get("booking_id"),
        session_id=action.get("session_id"),
        invoice_id=action.get("invoice_id"),
        created_by=biz.get("owner_id"),
    )

    if not res.get("ok"):
        # The insufficient-balance path is a NORMAL outcome, not an error to
        # bury. Chief should say what is left and what was asked for, so the
        # practitioner can decide to sell more or override.
        if res.get("available") is not None:
            avail = _fmt(res["available"], ku["unit"])
            unit_word = _unit_word(ku["unit"], res.get("available"))
            return {
                "type": "consume_balance",
                "result": (f"not enough balance — {contact.get('name')} has "
                           f"{avail} {unit_word}, needs "
                           f"{_fmt(res.get('requested'), ku['unit'])}. "
                           f"Sell more, or pass allow_overdraw to go negative."),
                "label": f"{contact.get('name')}: only {avail} {unit_word} left",
                "nav": _contact_nav(contact),
            }
        return _fail("consume_balance", res.get("error") or "consume failed")

    unit_word = _unit_word(ku["unit"], res.get("balance"))
    left = _fmt(res["balance"], ku["unit"])
    tail = " — that was the last one" if res.get("low") and res["balance"] <= 0 else ""
    return {
        "type": "consume_balance",
        "result": (f"logged {_fmt(res['consumed'], ku['unit'])} — "
                   f"{contact.get('name')} has {left} {unit_word} left{tail}"),
        "label": f"{contact.get('name')}: {left} {unit_word} left",
        "nav": _contact_nav(contact),
    }


async def handle_check_balance(client, biz, action) -> Dict[str, Any]:
    """What does this contact have left? Pure read."""
    contact = await _resolve_contact(client, biz, action)
    if not contact:
        return _fail("check_balance",
                     f"Contact {action.get('contact_id')} not found")

    summary = await asyncio.to_thread(
        cb.describe_balances, biz["id"], contact["id"])
    return {
        "type": "check_balance",
        "result": f"{contact.get('name')}: {summary}",
        "label": f"{contact.get('name')} — {summary}",
        "nav": _contact_nav(contact),
    }


# ── formatting helpers ───────────────────────────────────────────────

def _fmt(value: Any, unit: str) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "money":
        return f"${v:,.2f}"
    return f"{v:g}"


def _unit_word(unit: str, value: Any) -> str:
    if unit == "money":
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0
    base = "session" if unit == "session" else "hour"
    return base if v == 1 else base + "s"


def _contact_nav(contact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from chief_of_staff import _nav
        return _nav("operate", "contacts", contact["id"])
    except Exception:
        return None
