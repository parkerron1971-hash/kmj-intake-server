"""bill_words.py — what the person who is asked to pay reads: an invoice, or
for a church a bill.

A church's Bills page (the app's Office door) says bill everywhere. What
the person who got one read still said Invoice: the email Chief sends, its
subject, the line over the pay buttons, the text message, the name on
Stripe's pay page and receipt, and the overdue reminder (Kevin, 2026-11-17:
the church pages still in business words). This is the one place those
words are chosen, so every path says the same thing.

WHO READS BILL
  A church (church_follow_up.is_church) whose row is not a gift. A church's
  gifts are kept as paid invoices too (is_gift, numbered GIVE-…): a gift is
  never a bill, so a gift row keeps the wording it had and nothing a giver
  reads changes here.

WHAT DOES NOT CHANGE
  * A business: every string below is the one it read before, held by
    __tests__/test_bill_words.py against the literal old text.
  * The number. A bill already sent keeps its number and its prefix
    ("Bill INV-2026-004"); nothing is renumbered.
  * Amounts, dates, line items and the church's details.
  * Table names, API fields, Stripe metadata (source_type stays "invoice"),
    event types and logs.
  * What Chief calls it in chat. Chief already uses "bills" for what a
    church OWES (chief_bills, the bookkeeping bills). These words are only
    for the person who receives one.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def is_bill(biz: Optional[Dict[str, Any]], invoice: Optional[Dict[str, Any]] = None) -> bool:
    """A church's bill: the business is a church and the row is not a gift.
    Never raises; anything unreadable is an invoice, as before."""
    try:
        if invoice and (invoice.get("is_gift") or str(invoice.get("invoice_number") or "").startswith("GIVE-")):
            return False
        import church_follow_up
        return bool(church_follow_up.is_church(biz or {}))
    except Exception:
        return False


# The business column is the text each path had, character for character.
_INVOICE = {
    "label": "INVOICE",
    "intro": "Please find your invoice below.",
    "pay_header": "Pay This Invoice — {total}",
    "stripe_named": "Invoice {number}",
    "stripe_unnamed": "Invoice Payment",
}
_BILL = {
    "label": "BILL",
    "intro": "Please find your bill below.",
    "pay_header": "Pay this bill: {total}",
    "stripe_named": "Bill {number}",
    "stripe_unnamed": "Bill payment",
}


def words(biz: Optional[Dict[str, Any]], invoice: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    return _BILL if is_bill(biz, invoice) else _INVOICE


def email_subject(biz: Optional[Dict[str, Any]], invoice: Optional[Dict[str, Any]], number: Any, sender: str) -> str:
    """The subject of the email that carries it."""
    if is_bill(biz, invoice):
        return f"Bill {number} from {sender}"
    return f"Invoice {number} from {sender}"


def pay_header(biz: Optional[Dict[str, Any]], invoice: Optional[Dict[str, Any]], total: str) -> str:
    """The line over the pay buttons in the email."""
    return words(biz, invoice)["pay_header"].format(total=total)


def stripe_name(biz: Optional[Dict[str, Any]], invoice: Optional[Dict[str, Any]], number: Any = "") -> str:
    """The name on Stripe's pay page and on the receipt Stripe sends. A
    link made before this keeps the name it was made with."""
    w = words(biz, invoice)
    number = str(number or "").strip()
    return w["stripe_named"].format(number=number) if number else w["stripe_unnamed"]


def text_head(biz: Optional[Dict[str, Any]], invoice: Optional[Dict[str, Any]], number: Any) -> str:
    """The first line of the text message."""
    if is_bill(biz, invoice):
        return f"{(biz or {}).get('name') or 'Your church'}: bill {number}"
    return f"{(biz or {}).get('name') or 'Your business'} — Invoice {number}"


def overdue_nudge(biz: Optional[Dict[str, Any]], invoice: Dict[str, Any], name: Optional[str],
                  total: float, due: Any, days: int) -> Dict[str, str]:
    """The reminder proposed for one that is a week past due: the subject
    and body the payer would read, and the reason the office reads before
    approving it."""
    number = invoice.get("invoice_number")
    if is_bill(biz, invoice):
        return {
            "subject": f"A reminder about bill {number}",
            "body": (f"Hi {name or 'there'},\n\nThis is a gentle reminder that bill {number} "
                     f"(${total:,.2f}) was due on {due}. The link to pay is in the bill we sent, "
                     f"and if anything is off, just reply here.\n\nThank you!"),
            "reasoning": (f"Bill {number} is {days} days overdue and {name or 'the person'} has not "
                          "been reminded. Approve to send this reminder. Nothing sends until you say so."),
        }
    return {
        "subject": f"Friendly nudge — invoice {number}",
        "body": (f"Hi {name or 'there'},\n\nJust a gentle "
                 f"reminder that invoice {number} "
                 f"(${total:,.2f}) was due on "
                 f"{due}. The payment link is on the invoice — and if "
                 f"anything's off, just reply here.\n\nThank you!"),
        "reasoning": (f"Invoice {number} is {days} days "
                      f"overdue and {name or 'the client'} hasn't "
                      "been nudged. Approve to send this reminder — nothing "
                      "sends until you say so."),
    }
