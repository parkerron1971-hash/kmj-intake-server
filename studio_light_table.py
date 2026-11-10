"""The Light Table: the Studio's flyer flow.

Kevin, 2026-11-09, on the redesign canvas (https://claude.ai/artifact/Vcma193TFunxdNoUnEKwLv):
"this design is good. let's go with it".

A short brief becomes the Creative Director's flyer request, the same one
Chief's design_flyer makes from a chat. The brief holds the kind of flyer, a
headline, a line under it, when, where, a last line, and where the flyer
goes. The Director then plans the flyer, draws it, checks it and repairs it
once, on the business's own facts, daily limit and credits. Nothing in this
module draws or charges: handle_design_flyer does both, exactly as it does
for chat, so the owner check, the credit check, the daily limit and the
replay guard all come with it.

  GET  /ai/images/studio/{business_id}          is the Light Table open, what a
                                                 flyer costs, and the next occasion
                                                 on the calendar to start from
  POST /ai/images/studio/{business_id}/design   start a flyer from the brief

The switch, STUDIO_LIGHT_TABLE = off | owner | on (default owner). Owner opens
it for the platform owner only, to rehearse before it turns on for everyone
(features switch on on Thursdays). Off, the app keeps today's Studio.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import image_studio as images
import sb_clients
from auth_supabase import UserSession

router = APIRouter(prefix='/ai/images/studio', tags=['studio'])

# Where the flyer goes -> the Director's canvas. All three are sizes the
# 2.5 models draw (image_studio.SIZES).
SIZES = {'post': '1088x1360', 'story': '1088x1920', 'wide': '1920x1088'}
# The closest shapes gpt-image-2 draws, if OPENAI_IMAGE_MODEL is ever set back
# to it: a filled-in brief must never fail on its size.
FALLBACK_SIZES = {'post': '1024x1536', 'story': '1024x1536', 'wide': '1536x1024'}
KINDS = {'event': 'an event', 'series': 'a series', 'announcement': 'an announcement', 'offer': 'an offer'}
# How far ahead the calendar is read for an occasion to start from.
LOOKAHEAD_DAYS = 60


# ─── The switch ──────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get('STUDIO_LIGHT_TABLE') or 'owner').strip().lower()
    return m if m in ('off', 'owner', 'on') else 'off'


def open_to(user: Any) -> bool:
    m = mode()
    if m == 'on':
        return True
    if m == 'owner':
        owner = (os.environ.get('PLATFORM_OWNER_EMAIL') or 'kmjcreativesolution@gmail.com').strip().lower()
        return (getattr(user, 'email', None) or '').strip().lower() == owner
    return False


# ─── The brief ───────────────────────────────────────────────────────

class Brief(BaseModel):
    model_config = ConfigDict(extra='forbid')

    request_id: UUID
    kind: Literal['event', 'series', 'announcement', 'offer'] = 'event'
    headline: str = Field(min_length=1, max_length=120)
    sub: str = Field(default='', max_length=200)
    when: str = Field(default='', max_length=120)
    where: str = Field(default='', max_length=160)
    last: str = Field(default='', max_length=120)
    format: Literal['post', 'story', 'wide'] = 'post'
    reference_ids: List[UUID] = Field(default_factory=list, max_length=4)


def brief_copy(brief: Brief) -> List[str]:
    """The only words the flyer may print, in reading order. The Director
    checks the finished design for every one of them."""
    return [s.strip() for s in (brief.headline, brief.sub, brief.when, brief.where, brief.last) if s and s.strip()]


def size_for(fmt: str) -> str:
    """The canvas for where the flyer goes, on the model that will draw it."""
    want = SIZES[fmt]
    try:
        allowed = images.model_sizes(images.configured_model())
    except Exception:  # a misconfigured model is refused later, with its own message
        return want
    return want if want in allowed else FALLBACK_SIZES[fmt]


def brief_action(brief: Brief) -> Dict[str, Any]:
    """The brief as the design_flyer action Chief would send."""
    headline = brief.headline.strip()
    if not headline:
        raise HTTPException(422, 'Give the flyer a headline.')
    kind = KINDS[brief.kind]
    return {
        'goal': f'A flyer for {kind}: {headline}.',
        'exact_copy': brief_copy(brief),
        'size': size_for(brief.format),
        # A photo the owner adds is drawn from, never pasted; their saved
        # logo is added by the Director itself (settle_references).
        'references': [{'id': str(i), 'role': 'subject', 'use': 'A photo the owner added for this flyer'}
                       for i in brief.reference_ids],
        'owner_request': f'Make a flyer for {kind}: {headline}.',
    }


# ─── The calendar's next occasion ────────────────────────────────────

def _parse(raw: Any) -> Optional[datetime]:
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text[:19].replace('Z', ''))
    except ValueError:
        return None
    return when.replace(tzinfo=None)


def when_words(raw: Any) -> str:
    """'2026-11-21T18:00' -> 'Sat, Nov 21 · 6 PM'. A date with no time keeps
    no time; anything unreadable is left out rather than guessed."""
    when = _parse(raw)
    if when is None:
        return ''
    day = f"{when.strftime('%a, %b')} {when.day}"
    if len(str(raw).strip()) <= 10:
        return day
    hour = when.hour % 12 or 12
    minutes = f':{when.minute:02d}' if when.minute else ''
    return f"{day} · {hour}{minutes} {'AM' if when.hour < 12 else 'PM'}"


def _first_sentence(text: Any, limit: int = 140) -> str:
    words = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not words:
        return ''
    match = re.match(r'(.+?[.!?])(\s|$)', words)
    first = match.group(1) if match else words
    return first if len(first) <= limit else ''


def local_now(zone_name: Optional[str]) -> datetime:
    """Now on the church's own clock, as a plain local time: occasions are
    saved in local time, and the server runs on UTC."""
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(zone_name) if zone_name else ZoneInfo('America/New_York')
    except Exception:
        zone = ZoneInfo('America/New_York')
    return datetime.now(zone).replace(tzinfo=None)


def next_occasion(business_id: str, *, now: Optional[datetime] = None,
                  zone: Optional[str] = None) -> Optional[Dict[str, str]]:
    """The next occasion in Services & Events (any event_roster room) to
    start a flyer from: its own title, time, place and first sentence.
    Services (the weekly worship occasions check-in makes) and private
    occasions are skipped. "Now" is the church's clock (zone); a dated
    occasion with no time counts until its day is over. None when nothing
    is coming up or it can't be read: the brief then starts empty."""
    from church_checkin import _entries, _roster
    from events_rsvp_router import resolve_fields
    try:
        mods = _roster(business_id) or []
        if not mods:
            return None
        fields = {str(m['id']): resolve_fields(m.get('archetype_params')) for m in mods}
        entries = _entries(business_id, list(fields)) or []
    except Exception as e:  # a read we can't make leaves the brief empty
        print(f'[studio] next occasion unreadable for {business_id}: {e}')
        return None
    now = now or local_now(zone)
    soonest = None
    for entry in entries:
        f = fields.get(str(entry.get('module_id')))
        data = entry.get('data') or {}
        if not f or str(data.get('type') or '') == 'service' or data.get('private') is True:
            continue
        raw = data.get(f['date_field'])
        when = _parse(raw)
        title = str(data.get(f['title_field']) or '').strip()
        if not title or when is None or when > now + timedelta(days=LOOKAHEAD_DAYS):
            continue
        # Over: a timed occasion two hours after it starts, a day-only one when its day ends.
        over = when + (timedelta(days=1) if len(str(raw).strip()) <= 10 else timedelta(hours=2))
        if over <= now:
            continue
        if soonest is None or when < soonest[0]:
            soonest = (when, entry, f, title)
    if soonest is None:
        return None
    _, entry, f, title = soonest
    data = entry.get('data') or {}
    return {
        'entry_id': str(entry.get('id')),
        'kind': 'event',
        'headline': title[:120],
        'sub': _first_sentence(data.get('description')),
        'when': when_words(data.get(f['date_field'])),
        'where': str(data.get(f['location_field']) or '').strip()[:160],
        'source': 'Services & Events',
    }


# ─── Routes ──────────────────────────────────────────────────────────

@router.get('/{business_id}')
async def studio_status(business_id: UUID, session: UserSession = Depends(sb_clients.authed_request)):
    async with httpx.AsyncClient(timeout=30) as client:
        biz = await images.business(client, business_id)  # this business's owner only
    if not open_to(session.user):
        return {'light_table': False}
    import credit_ledger
    from church_checkin import church_zone_name
    zone = church_zone_name(biz or {})
    return {'light_table': True, 'flyer_credits': credit_ledger.flyer_credits(), 'formats': list(SIZES),
            'suggestion': await asyncio.to_thread(lambda: next_occasion(str(business_id), zone=zone))}


@router.post('/{business_id}/design')
async def studio_design(business_id: UUID, brief: Brief, session: UserSession = Depends(sb_clients.authed_request)):
    if not open_to(session.user):
        raise HTTPException(404, 'Not Found')
    action = brief_action(brief)
    import creative_director
    # The request id is the identity: a retried tap finds the same row
    # instead of paying for a second design.
    turn = images.turn_id.set(f'studio:{brief.request_id}')
    index = images.turn_image_index.set(0)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            biz = await images.business(client, business_id)
            return await creative_director.handle_design_flyer(client, biz, action)
    finally:
        images.turn_id.reset(turn)
        images.turn_image_index.reset(index)
