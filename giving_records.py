"""Authoritative gift reads. Invoices remain the GL source, never the gift classifier."""
from urllib.parse import quote
from fastapi import HTTPException
import sb_clients

GIFT_FIELDS = "id,invoice_number,is_gift,gift_fund,updated_at,payment_method,total,paid_at,category,notes,refund_amount_cents,contact_id,giving_count_id,contacts(name,email)"

def is_gift(row):
    return row.get("is_gift") is True

def read_gifts(business_id, start, end_exclusive, contact_id=None):
    """Keyset pages; incomplete/error reads never mean zero."""
    import sb_clients
    base = (f"/invoices?business_id=eq.{quote(str(business_id), safe='')}"
            f"&is_gift=eq.true&status=eq.paid&paid_at=gte.{start}"
            f"&paid_at=lt.{end_exclusive}&select={GIFT_FIELDS}")
    if contact_id:
        base += f"&contact_id=eq.{quote(str(contact_id), safe='')}"
    result, cursor = [], None
    # PostgREST may cap below the requested page size. Continue until EMPTY.
    for _ in range(10000):
        q = base + "&order=id.asc&limit=500"
        if cursor:
            q += f"&id=gt.{quote(str(cursor), safe='')}"
        try:
            page = sb_clients.sb_get_as_service(q)
        except Exception as exc:
            raise HTTPException(503, "Giving records could not be loaded. Please retry.") from exc
        if not isinstance(page, list):
            raise HTTPException(503, "Giving records could not be loaded. Please retry.")
        if not page:
            return result
        next_cursor = page[-1].get("id")
        if not next_cursor or (cursor is not None and str(next_cursor) <= str(cursor)):
            raise HTTPException(503, "Giving records were incomplete. Please retry.")
        result.extend(row for row in page if is_gift(row))
        cursor = next_cursor
    raise HTTPException(503, "Giving report is too large. Choose a shorter date range.")

def require_finance(business_id, user, need="see"):
    """Giving access: owner, admin, or explicitly invited active accountant.
    The rule is church_money_gate's ("giving"); this name is kept for the
    doors that already call it. `need` is "see" for a door that reads and
    "work" for one that writes (a gift entered or corrected, a pledge, a
    count, statements mailed): the same people today, and the place the
    giving tick will tell them apart. Returns the role, or "accountant"."""
    import church_money_gate
    return church_money_gate.require_money(business_id, user, need, "giving").role or "accountant"

def require_ministry_finance(business_id, user, business=None, part="books", need="see"):
    """Reading the books or the bank of a church or nonprofit takes the
    giving rule; any other business isn't asked here (church_money_gate,
    "books" / "bank" at "see"). `need="work"` from a door that is about to
    CHANGE something behind its own seat ladder: a login let through only
    by a giving tick must then hold Work (church_money_gate
    .require_church_wall); everyone else is answered as at "see"."""
    import church_money_gate
    church_money_gate.require_church_wall(business_id, user, need, part, business=business)
