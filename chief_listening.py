"""Read-only scheduling preparation from unfinished speech.

Only an active offering catalog is cached, never a slot verdict or an action.
Final handling must authorize again and freshly check selected offerings,
scheduling rules, bookings, and outside-calendar capacity. Process-local misses
(including another web worker) simply use the ordinary final-request path.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import threading
import time
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_supabase import UserSession, require_user_session
import sb_clients

router = APIRouter()
TTL_SECONDS = 30.0
MIN_INTERVAL_SECONDS = 1.0
MAX_ENTRIES = 500
MAX_ACTIVE = 16
PREPARE_TIMEOUT_SECONDS = 3.0


class ListeningRequest(BaseModel):
    business_id: UUID
    turn_id: UUID
    revision: int = Field(ge=0, le=1000000, strict=True)
    text: str = Field(default='', max_length=2000)
    cancel: bool = False


@dataclass
class _Entry:
    revision: int
    text: str
    at: float
    terminal: bool = False
    payload: dict | None = None
    lineage: object = field(default_factory=object)
    fetching: bool = False


_lock = threading.Lock()
_entries: dict[tuple[str, str, str], _Entry] = {}
_started: dict[str, float] = {}
_active: set[str] = set()
_SCHEDULING = re.compile(r'\b(?:appointment|appointments|availability|schedule|scheduling|book|booking|openings|slots)\b|\b(?:free|available)\s+(?:time|tomorrow|today|on|at|next)', re.I)


def _normalized(text: str) -> str:
    return ' '.join(re.findall(r'\w+', text.casefold()))


def _extends(text: str, prefix: str) -> bool:
    return bool(prefix and (text == prefix or text.startswith(prefix + ' ')))


def _prune(now: float) -> None:
    for key, entry in list(_entries.items()):
        if now - entry.at >= TTL_SECONDS:
            _entries.pop(key, None)
    for user, at in list(_started.items()):
        if now - at >= TTL_SECONDS and user not in _active:
            _started.pop(user, None)
    while len(_entries) >= MAX_ENTRIES:
        _entries.pop(min(_entries, key=lambda key: _entries[key].at))
    while len(_started) >= MAX_ENTRIES:
        removable = [user for user in _started if user not in _active]
        if not removable:
            break
        _started.pop(min(removable, key=_started.get))


def consume(user_id: str, business_id: str, turn_id: str | None,
            revision: int | None, final_text: str) -> dict | None:
    """Claim a matching catalog once; a final utterance closes this turn.

    Call only after final-request authorization. Returned data is candidate
    search input, not proof of current service duration or free capacity.
    """
    if not turn_id or revision is None:
        return None
    key = (str(user_id), str(business_id), str(turn_id))
    with _lock:
        entry = _entries.get(key)
        if entry is None or entry.terminal:
            return None
        payload = entry.payload
        entry.payload = None
        entry.terminal = True
        prefix = _normalized(entry.text)
        if (time.monotonic() - entry.at >= TTL_SECONDS or revision != entry.revision
                or not _extends(_normalized(final_text), prefix)):
            return None
        return deepcopy(payload)


async def _load_offerings(client: httpx.AsyncClient, business_id: str) -> list:
    from chief_availability import load_offerings
    return await load_offerings(client, business_id)


async def _fetch(req: ListeningRequest, session: UserSession) -> dict:
    business_id = str(req.business_id)
    user_id = str(session.user.id)
    with sb_clients.with_user_jwt(session.token):
        async with httpx.AsyncClient(timeout=2.5) as client:
            rows = await sb_clients.sb_as_user(
                client, 'GET', f'/businesses?id=eq.{business_id}'
                f'&owner_id=eq.{quote(user_id, safe="")}&select=id,owner_id&limit=1', session.token)
            if not isinstance(rows, list) or not rows:
                raise HTTPException(403, 'Business unavailable')
            biz = rows[0]
            if str(biz.get('id')) != business_id or str(biz.get('owner_id')) != user_id:
                raise HTTPException(403, 'Business unavailable')
            offerings = await _load_offerings(client, business_id)
            if not isinstance(offerings, list):
                raise ValueError('catalog unavailable')
            return {'business_id': business_id,
                    'captured_at': datetime.now(timezone.utc).isoformat(),
                    'offerings': offerings}


@router.post('/agents/chief/listening')
async def prepare_listening(req: ListeningRequest,
                            user_session: UserSession = Depends(require_user_session)):
    user_id = str(user_session.user.id)
    key = (user_id, str(req.business_id), str(req.turn_id))
    response = {'ok': True, 'turn_id': str(req.turn_id), 'revision': req.revision}
    now = time.monotonic()
    with _lock:
        _prune(now)
        prior = _entries.get(key)
        if prior and (prior.terminal or req.revision <= prior.revision):
            return {**response, 'status': 'stale'}
        entry = _Entry(req.revision, req.text, now, terminal=req.cancel)
        # Catalog search input does not change as a sentence grows. Rebind
        # completed/in-flight work to the latest revision without sliding its
        # TTL. A correction or cancellation creates a different lineage.
        prefix = _normalized(prior.text) if prior else ''
        extending = bool(prior and not req.cancel
                         and _extends(_normalized(req.text), prefix))
        if extending and (prior.payload is not None or prior.fetching):
            entry.at = prior.at
            entry.lineage = prior.lineage
            entry.payload = prior.payload
            entry.fetching = prior.fetching
        _entries[key] = entry  # Immediately invalidate an older in-flight result.
        if req.cancel:
            return {**response, 'status': 'cancelled'}
        if not _SCHEDULING.search(req.text):
            return {**response, 'status': 'ignored'}
        if entry.payload is not None:
            return {**response, 'status': 'prepared'}
        if entry.fetching:
            return {**response, 'status': 'preparing'}
        if (user_id in _active or len(_active) >= MAX_ACTIVE
                or now - _started.get(user_id, float('-inf')) < MIN_INTERVAL_SECONDS):
            return {**response, 'status': 'throttled'}
        _active.add(user_id)
        _started[user_id] = now
        entry.fetching = True
    try:
        payload = await asyncio.wait_for(_fetch(req, user_session), PREPARE_TIMEOUT_SECONDS)
        with _lock:
            current = _entries.get(key)
            if current is None or current.lineage is not entry.lineage or current.terminal:
                return {**response, 'status': 'superseded'}
            current.payload = payload
        return {**response, 'status': 'prepared'}
    except HTTPException:
        raise
    except Exception:
        return {**response, 'status': 'unavailable'}
    finally:
        with _lock:
            _active.discard(user_id)
            current = _entries.get(key)
            if current is not None and current.lineage is entry.lineage:
                current.fetching = False
