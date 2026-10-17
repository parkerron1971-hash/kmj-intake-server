"""Course Studio slides: the two server pieces the slide editor needs.

  GET  /academy-slides/scripture?ref=…&tr=web   the verse text for a scripture
       slide, from the public-domain text the server ships (never typed by a
       model or retyped by hand). Signed-in only; no business data involved.
  POST /academy-slides/art                       a public copy of one of the
       business's own gallery images (an upload or a Chief picture), so a
       slide, the TV and the student classroom can show it. Owner only,
       checked by Image Studio's own business guard.

Decks themselves save through the academy_save_deck function (RLS +
academy_can_teach), and presenting through academy_present_* — see
supabase/APPLY-2026-10-17-academy-slides.sql.
"""
from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import UserSession
from chief_academy_actions import MAX_SLIDE_VERSES, scripture_passage

router = APIRouter(prefix="/academy-slides", tags=["Academy slides"])


@router.get("/scripture")
async def scripture(ref: str, tr: str = "web", session: UserSession = Depends(sb_clients.authed_request)):
    if not ref or len(ref) > 80:
        raise HTTPException(400, "Type a reference like John 3:16 or Romans 8:28-30.")
    passage = scripture_passage(ref, tr)
    if not passage:
        raise HTTPException(404, f"I couldn't find that as a passage of up to {MAX_SLIDE_VERSES} verses. "
                                 "Check the book, chapter and verses.")
    return passage


class SlideArt(BaseModel):
    business_id: UUID
    artwork_id: UUID


@router.post("/art")
async def slide_art(req: SlideArt, session: UserSession = Depends(sb_clients.authed_request)):
    import image_studio
    async with httpx.AsyncClient(timeout=120) as client:
        await image_studio.business(client, req.business_id)
        row = await image_studio.artwork(client, req.business_id, req.artwork_id)
        url = await image_studio.delivery_jpeg(client, req.business_id, row)
    return {"url": url}
