"""journeys_router.py — the owner's switches for Outreach that runs by itself.

  GET /journeys/{business_id}           viewer   each journey: on or locked,
                                                 its words and settings, and
                                                 what it did in 30 days
  PUT /journeys/{business_id}/{kind}    owner    switch it on or off, change
                                                 its words, days or hours;
                                                 the review link (review_ask)

The journeys themselves, and the rules every note follows, are
outreach_journeys'. A member reads; only the owner changes anything, and a
journey a plan doesn't include can't be switched on (a 409 that says why).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import outreach_journeys as journeys
import sb_clients
from business_access import business_access

router = APIRouter(prefix="/journeys", tags=["journeys"])


class JourneyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: Optional[bool] = None
    days: Optional[int] = Field(default=None, ge=1, le=400)
    hours_after: Optional[int] = Field(default=None, ge=1, le=96)
    subject: Optional[str] = Field(default=None, max_length=400)
    email: Optional[str] = Field(default=None, max_length=4000)
    text: Optional[str] = Field(default=None, max_length=800)
    reset_words: bool = False
    review_url: Optional[str] = Field(default=None, max_length=600)


@router.get("/{business_id}")
async def read(business_id: str, biz: dict = Depends(business_access("viewer"))):
    return {"ok": True, **await journeys.overview(biz)}


@router.put("/{business_id}/{kind}")
async def write(business_id: str, kind: str, body: JourneyChange, biz: dict = Depends(business_access("owner"))):
    try:
        settings = journeys.change(biz, kind, body.model_dump(exclude_unset=True))
    except journeys.JourneyError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    saved = await asyncio.to_thread(
        sb_clients.sb_patch_as_service, f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    if not saved:
        raise HTTPException(503, "That change didn't save. Nothing was changed. Try again in a minute.")
    return {"ok": True, **await journeys.overview({**biz, "settings": settings})}
