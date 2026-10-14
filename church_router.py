"""
church_router.py — the church office's read-only questions about people.

    GET /church/first-time-guests?business_id=   came for the first time,
                                                 nobody has reached out since

Any active seat may read (the same rule as the attendance table itself).
The answers come from church_reads, which Chief reads too, so the Home
desk and Chief never disagree about who is waiting for a call.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

import church_reads
from business_access import business_access

router = APIRouter(prefix="/church", tags=["church"])


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
