"""church_money_gate.py — who may do a church's money week.

Kevin, 2026-11-01: Love City's treasurer holds an Admin seat, and most of her
week was refused: matching Sunday's deposit, filing and matching the bank,
reconciling, the categories, the bills and the store orders all asked one
question, "is this the business's owner?", so even an Admin seat got a 403.

    THE GATE ....... require_money_writer(): the owner, always; in a church
                     (church_follow_up.is_church), an active Admin seat too.
                     Anyone else gets the same 403 as before, a Manager seat
                     included. Every business that isn't a church: the owner
                     alone, exactly as before
    THE WALL ....... not here, and not moved: the bank's doors still call
                     church_keys.wall(.., "giving_money") after this gate
                     (plaid_router._require_money_writer), so a church that
                     names a Giving keeper locks its Admins out, the owner
                     too, until a keeper gives them a key
    KEPT OWNER-ONLY  linking or unlinking a bank, which bank accounts count in
                     the books, and the church's payout and Stripe accounts:
                     those doors keep their own owner gates and never call
                     this one

A read that fails is a refusal (404 for no business row, no seat read as no
seat), never a yes.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients


def _business(business_id: Any) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}&select=id,name,type,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _is_church(business: Dict[str, Any]) -> bool:
    import church_follow_up
    return church_follow_up.is_church(business)


def _church_admin(business_id: Any, user_id: str) -> bool:
    from business_users_router import role_of
    return role_of(str(business_id), user_id) == "admin"


def standing(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """'owner', 'admin' (a church's active Admin seat), or None."""
    row = business if isinstance(business, dict) and "owner_id" in business else _business(business_id)
    uid = str(user.id)
    if str(row.get("owner_id")) == uid:
        return "owner"
    if "type" not in row:
        row = _business(business_id)
    if _is_church(row) and _church_admin(business_id, uid):
        return "admin"
    return None


def can_write(business_id: Any, user: Any, business: Optional[Dict[str, Any]] = None) -> bool:
    """For a screen's can_change: whether require_money_writer would let them
    in. A read that fails is a no."""
    try:
        return standing(business_id, user, business) is not None
    except Exception:
        return False


def require_money_writer(business_id: Any, user: Any, *, detail: str = "not authorized") -> Dict[str, Any]:
    """The business row when this person may change its money records: the
    owner_id matches, or the business is a church and they hold an active
    Admin seat (business_users_router.role_of). Else 403 with `detail`, the
    message each door already gave."""
    row = _business(business_id)
    uid = str(user.id)
    if str(row.get("owner_id")) == uid:
        return row
    if _is_church(row) and _church_admin(business_id, uid):
        return row
    raise HTTPException(403, detail)
