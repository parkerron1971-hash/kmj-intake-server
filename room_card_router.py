"""room_card_router.py — GET /rooms/{business_id}/card?tab=&sub=&page=

The card the app shows when someone taps "What is this room?". Member+,
same gate as the plug-in list. Built without a model call (room_card.py)
so it opens at once; the chat stays one tap further for anyone who wants
Chief's voice on it.

Literal paths go ABOVE parameter routes at the same depth — this router
has only the one parameterised path, but the rule is written down here
so the next route added does not repeat #777.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("room_card")

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _gate(biz_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}"
        f"&select=id,name,type,owner_id,settings,stripe_account_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz_id, str(user.id), "member")
    return rows[0]


@router.get("/{business_id}/card")
def room_card(business_id: str, tab: Optional[str] = None, sub: Optional[str] = None,
              page: Optional[str] = None,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What this room is for, what is in it right now, the one next thing,
    and where it sits in the building."""
    biz = _gate(business_id, user)
    import room_card
    return room_card.build_room_card(biz, tab, sub, page)
