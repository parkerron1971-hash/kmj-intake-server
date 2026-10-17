"""
church_router.py — the church office's read-only questions about people.

    GET /church/first-time-guests?business_id=   came for the first time,
                                                 nobody has reached out since
    GET /church/care-counts?business_id=         the Prayer & care inbox as
                                                 numbers (owner and staff)
    GET /church/cards?business_id=               every card a guest can fill
                                                 in (the website's own and the
                                                 app's forms) and what came in
                                                 on each (owner and staff)

First-time guests: any active seat may read (the same rule as the
attendance table itself). Care counts: the owner and staff only, see
CARE_MIN_ROLE. The answers come from church_reads, which Chief reads too,
so the Home desk, the room overviews and Chief never disagree about who is
waiting for a call or how many prayer requests are new.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

import church_cards
import church_reads
from business_access import business_access

router = APIRouter(prefix="/church", tags=["church"])

# Who may read the care numbers: the church's owner and its staff, the same
# people Chief gives them to (chief_church_actions._CARE_ROLES: owner, admin,
# manager). business_access takes a MINIMUM rank on the seat ladder in
# business_users_router._ROLE_RANK,
#     viewer 1 < member 2 < manager 3 < admin 4 < owner 5,
# so "manager" lets in exactly manager, admin and owner and keeps member and
# viewer seats out. Accountants are not on that ladder at all: they are
# business_collaborators, not business_users, so role_of gives them no role
# and they are refused like anyone else with no seat (and a seat row naming
# a role the ladder doesn't know ranks 0, also refused). Nothing to order
# around, so no special case. A refusal is business_access's deliberate 404,
# the same answer a stranger gets.
CARE_MIN_ROLE = "manager"

# The only numbers the care route ever sends. Named, so a status or a field
# added to church_reads later cannot reach the app by accident.
CARE_COUNT_KEYS = ("new", "reviewed", "closed", "prayed")


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, "That business id isn't valid")


@router.get("/first-time-guests")
def first_time_guests(business_id: str = Query(...),
                      limit: int = Query(20, ge=1, le=100),
                      biz: Dict[str, Any] = Depends(business_access("viewer"))):
    rows = church_reads.first_time_guests(_uuid(business_id), limit=limit)
    if rows is None:
        raise HTTPException(503, "First-time guests couldn't be loaded. Try again in a moment.")
    return {"guests": rows, "window_days": church_reads.FIRST_VISIT_WINDOW_DAYS}


@router.get("/care-counts")
def care_counts(business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """How many prayer and care requests are new, reviewed, closed and
    marked prayed in the last CARE_WINDOW_DAYS, and how many days the
    oldest new one has waited (None when nothing is new). Numbers only:
    never a request's words, a name, an id or anything about children."""
    care = church_reads.care_request_counts(_uuid(business_id))
    if care is None:
        raise HTTPException(503, "Prayer and care numbers couldn't be loaded. Try again in a moment.")
    oldest = care.get("oldest_new_days")
    return {
        "care": {**{k: int(care.get(k) or 0) for k in CARE_COUNT_KEYS},
                 "oldest_new_days": int(oldest) if oldest is not None else None},
        "window_days": church_reads.CARE_WINDOW_DAYS,
    }


@router.get("/cards")
def cards(business_id: str = Query(...),
          biz: Dict[str, Any] = Depends(business_access(CARE_MIN_ROLE))):
    """The Forms page's cards: the ones written into the church's website,
    with their questions, and how many came in on each card and intake form
    in the last 90 days. Who filled in a card is the office's to see (owner
    and staff, the same seats as the care numbers); a private card is
    numbers only. See church_cards."""
    out = church_cards.cards(_uuid(business_id))
    if out is None:
        raise HTTPException(503, "Your cards couldn't be loaded. Try again in a moment.")
    return out
