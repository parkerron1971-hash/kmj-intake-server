"""Device-owned latest session state; owner-only Workers and screen reads."""
import json
from datetime import datetime, timedelta
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

import dev_relay as store
import dev_redact
import rate_limit
from dev_bridge import HTTP_TIMEOUT, _require_device
from lead_admin import require_owner

router = APIRouter(tags=['dev-bridge'], route_class=store.BoundedRoute)
State = Literal['starting', 'working', 'needs-you', 'ready', 'held', 'ended', 'unwatched']


class Hold(BaseModel):
    why: str = ''
    since: Optional[datetime] = None


class Approval(BaseModel):
    id: int
    label: str = ''
    what: str = ''


class Mission(BaseModel):
    id: str = Field(max_length=80)
    step: Optional[str | int] = None


class FleetSession(BaseModel):
    key: str = Field(pattern=r'^s-[0-9a-fA-F-]{36}$')
    handle: str = ''
    kind: Literal['claude', 'codex', 'grok', 'shell']
    owner: Literal['you', 'kai', 'chief']
    project: str = ''
    branch: str = ''
    task: str = ''
    state: State
    since: Optional[datetime] = None
    doing: str = ''
    ask: str = ''
    last: str = ''
    idle_s: Optional[int] = Field(default=None, ge=0, le=2147483647)
    hold: Optional[Hold] = None
    approval: Optional[Approval] = None
    mission: Optional[Mission] = None
    subagents: int = Field(default=0, ge=0, le=10000)
    task_id: Optional[str] = None
    on_phone: bool = False
    permission_mode: Optional[Literal['auto', 'acceptEdits', 'default']] = None
    screen_rev: int = Field(default=0, ge=0, le=2147483647)

    @field_validator('key')
    @classmethod
    def session_id(cls, value):
        return 's-' + store.uid(value[2:])

    @field_validator('task_id')
    @classmethod
    def task_uuid(cls, value):
        return store.uid(value) if value else None


class FleetBody(BaseModel):
    full: bool = False
    away: bool = False
    sessions: list[FleetSession] = Field(default_factory=list)


class ScreenBody(BaseModel):
    rev: int = Field(ge=0, le=2147483647)
    text: str
    state: Optional[State] = None
    at: Optional[datetime] = None


class WatchBody(BaseModel):
    device_id: str
    key: Optional[str] = None


def session_key(key):
    if not key.startswith('s-'):
        raise HTTPException(422, 'Expected a session key')
    return 's-' + store.uid(key[2:])


def _row(session):
    row = dev_redact.deep(session.model_dump(mode='json'))
    row['session_key'] = row.pop('key')
    for name, cap in {'handle': 20, 'project': 80, 'branch': 120, 'task': 120,
                      'doing': 160, 'ask': 200, 'last': 600}.items():
        row[name] = row[name][:cap]
    if row['hold']:
        row['hold']['why'] = row['hold']['why'][:160]
    if row['approval']:
        row['approval']['label'] = row['approval']['label'][:200]
        row['approval']['what'] = row['approval']['what'][:300]
    if row['mission']:
        row['mission']['id'] = dev_redact.text(row['mission']['id'])[:80]
        row['mission']['step'] = dev_redact.text(str(row['mission']['step'] or ''))[:120]
    if row['state'] != 'unwatched':
        row['idle_s'] = None
    return row


@router.post('/dev-bridge/fleet')
async def fleet_sync(body: FleetBody, authorization: Optional[str] = Header(None)):
    if len(body.sessions) > 60 or len(json.dumps(body.model_dump(mode='json'), ensure_ascii=False).encode()) > 65536:
        raise HTTPException(413, 'At most 60 sessions and 64 KB per snapshot')
    if len({s.key for s in body.sessions}) != len(body.sessions):
        raise HTTPException(422, 'Duplicate session key')
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        if not rate_limit.allow_strict('dev_fleet', device['id']):
            raise HTTPException(429, 'Fleet write limit', headers={'Retry-After': '60'})
        result = await store.rpc(c, 'dev_fleet_sync', {'p_device': device['id'], 'p_full': body.full,
                                                    'p_sessions': [_row(s) for s in body.sessions]})
        if result.get('error'):
            raise HTTPException(result['error'], 'Fleet capacity or device unavailable')
        rows = await store.get(c, 'dev_bridge_devices', {'id': f"eq.{device['id']}",
                                                       'select': 'fleet_watch,fleet_open_until'})
    me = rows[0] if rows else {}
    watch = me.get('fleet_watch') or {}
    until = store.parse(watch.get('until'))
    opened = store.parse(me.get('fleet_open_until'))
    stamp = store.now()
    return {'ok': True, 'watch': {'key': watch['session_key'], 'until': watch['until']}
            if until and until > stamp and watch.get('session_key') else None,
            'phone_open': bool(opened and opened > stamp)}


@router.put('/dev-bridge/fleet/{key}/screen')
async def fleet_screen_put(key: str, body: ScreenBody, authorization: Optional[str] = Header(None)):
    key = session_key(key)
    if len(body.text) > 16000:
        raise HTTPException(413, 'Screen exceeds 16,000 characters')
    text = dev_redact.text(body.text)
    # Redaction may expand a short secret. Keep the final stored text within the cap.
    text = '\n'.join(text.splitlines()[-120:])[-12000:]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        result = await store.rpc(c, 'dev_fleet_screen', {'p_device': device['id'], 'p_key': key,
            'p_rev': body.rev, 'p_text': text, 'p_state': body.state,
            'p_at': body.at.isoformat() if body.at else store.z(store.now())})
    if result.get('error'):
        code = result['error']
        raise HTTPException(code, 'Screen unavailable or written too quickly',
                            headers={'Retry-After': '2'} if code == 429 else None)
    return result


@router.delete('/dev-bridge/fleet')
async def fleet_clear_device(authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        rows = await store.delete(c, 'dev_fleet_sessions', {'device_id': f"eq.{device['id']}"})
        await store.patch(c, 'dev_bridge_devices', {'id': f"eq.{device['id']}"},
                          {'fleet_watch': None, 'fleet_open_until': None})
    return {'ok': True, 'removed': len(rows)}


@router.get('/platform/dev-desk/fleet')
async def fleet_list(_owner=Depends(require_owner)):
    stamp = store.now()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        devices = await store.all_rows(c, 'dev_bridge_devices', {'revoked': 'eq.false',
            'select': 'id,name,last_seen_at', 'order': 'id'})
        sessions = await store.all_rows(c, 'dev_fleet_sessions', {'select': '*',
            'or': f'(ended_at.is.null,ended_at.gte.{store.z(stamp-timedelta(hours=1))})',
            'order': 'device_id,session_key'})
        screens = await store.all_rows(c, 'dev_fleet_screens', {'select': 'device_id,session_key',
                                                                'order': 'device_id,session_key'})
    visible = {d['id'] for d in devices}
    has_screen = {(s['device_id'], s['session_key']) for s in screens}
    for d in devices:
        seen = store.parse(d.get('last_seen_at'))
        d['online'] = bool(seen and (stamp-seen).total_seconds() <= 45)
    out = []
    for row in sessions:
        if row['device_id'] not in visible:
            continue
        item = dict(row, key=row['session_key'], has_screen=(row['device_id'], row['session_key']) in has_screen)
        item.pop('session_key', None)
        out.append(item)
    order = {s: i for i, s in enumerate(['needs-you', 'working', 'ready', 'held', 'starting', 'unwatched', 'ended'])}
    out.sort(key=lambda s: (order.get(s['state'], 7), s.get('handle') or '', s['key']))
    return {'ok': True, 'now': store.z(stamp), 'devices': devices, 'sessions': out}


@router.get('/platform/dev-desk/fleet/{device_id}/{key}/screen')
async def fleet_screen_get(device_id: str, key: str, rev: Optional[int] = None, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        rows = await store.get(c, 'dev_fleet_screens', {'device_id': f'eq.{store.uid(device_id)}',
            'session_key': f'eq.{session_key(key)}', 'select': 'rev,text,state,at'})
    if not rows:
        raise HTTPException(404, 'No screen yet')
    row = rows[0]
    return {'ok': True, 'rev': row['rev'], 'unchanged': True} if rev == row['rev'] else {'ok': True, **row}


@router.post('/platform/dev-desk/fleet/watch')
async def fleet_watch(body: WatchBody, _owner=Depends(require_owner)):
    device_id = store.uid(body.device_id)
    key = session_key(body.key) if body.key else None
    until = store.z(store.now() + timedelta(seconds=60))
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        devices = await store.get(c, 'dev_bridge_devices', {'id': f'eq.{device_id}', 'revoked': 'eq.false'})
        if not devices:
            raise HTTPException(404, 'No paired device')
        if key and not await store.get(c, 'dev_fleet_sessions', {'device_id': f'eq.{device_id}', 'session_key': f'eq.{key}'}):
            raise HTTPException(404, 'No such session')
        await store.patch(c, 'dev_bridge_devices', {'id': f'eq.{device_id}', 'revoked': 'eq.false'},
                          {'fleet_watch': {'session_key': key, 'until': until} if key else None,
                           'fleet_open_until': until})
    return {'ok': True, 'until': until}


@router.delete('/platform/dev-desk/fleet')
async def fleet_clear(_owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        rows = await store.delete(c, 'dev_fleet_sessions', {'device_id': 'not.is.null'})
        await store.patch(c, 'dev_bridge_devices', {'id': 'not.is.null'},
                          {'fleet_watch': None, 'fleet_open_until': None})
    return {'ok': True, 'removed': len(rows)}
