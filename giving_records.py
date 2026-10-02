"""Authoritative gift reads. Invoices remain the GL source, never the gift classifier."""
from urllib.parse import quote
from fastapi import HTTPException
import sb_clients

GIFT_FIELDS = "id,invoice_number,is_gift,gift_fund,updated_at,payment_method,total,paid_at,category,notes,refund_amount_cents,contact_id,contacts(name,email)"

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

def require_finance(business_id, user):
    """Giving access: owner, admin, or explicitly invited active accountant."""
    from business_users_router import role_of
    from business_collaborators_router import is_active_accountant
    role = role_of(business_id, str(user.id))
    if role in ("owner", "admin") or is_active_accountant(business_id, str(user.id)):
        return role or "accountant"
    raise HTTPException(403, "Giving records require owner, admin, or accountant access.")

def require_ministry_finance(business_id, user, business=None):
    import vertical_family
    rows = [business] if business else sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,type&limit=1")
    if not rows:
        raise HTTPException(404, "Business not found")
    if vertical_family.is_nonprofit_like(rows[0].get("type")):
        require_finance(business_id, user)
