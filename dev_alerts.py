"""One owner alert inbox, with dedupe, quiet hours, budgets and email fallback."""
import asyncio
import hashlib
import os
import re
from datetime import timedelta
from typing import Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

import dev_redact
import dev_relay as store
import rate_limit
from dev_bridge import HTTP_TIMEOUT, _require_device, _push_owner
from lead_admin import require_owner

router = APIRouter(tags=['dev-bridge'], route_class=store.BoundedRoute)
NAV = 'studio:platform-dev-desk:'
SOURCES = {'worker_needs_you': 'push', 'worker_finished': 'inbox', 'kai': 'push', 'missions': 'push',
           'session_crashed': 'push', 'ci': 'push', 'deploys': 'push', 'sites': 'push',
           'schedules': 'push', 'desktop_offline': 'push'}
DEVICE_SOURCES = {'worker_needs_you', 'worker_finished', 'kai', 'missions', 'session_crashed'}
SERVER_SOURCES = set(SOURCES) - DEVICE_SOURCES
Level = Literal['info', 'warn', 'urgent']
Mode = Literal['push', 'inbox', 'off']
_COLUMNS = 'id,created_at,source,kind,level,title,body,nav,card_id,delivered,count,read_at'


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Quiet(StrictModel):
    on: bool = True
    start: str = '22:00'
    end: str = '07:00'
    urgent_breaks_through: bool = True
    morning_digest: bool = True

    @field_validator('start', 'end')
    @classmethod
    def clock(cls, value):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError('Use HH:MM')
        return value


class Limits(StrictModel):
    per_hour: int = Field(default=20, ge=1, le=200)
    per_source_10min: int = Field(default=6, ge=1, le=100)


class Settings(StrictModel):
    enabled: bool = True
    tz: str = 'America/New_York'
    quiet: Quiet = Field(default_factory=Quiet)
    sources: dict[str, Mode] = Field(default_factory=lambda: dict(SOURCES))
    limits: Limits = Field(default_factory=Limits)
    email_fallback: Literal['off', 'urgent'] = 'urgent'

    @field_validator('tz')
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Use a real IANA time zone')
        return value

    @field_validator('sources')
    @classmethod
    def source_names(cls, value):
        if set(value) - set(SOURCES):
            raise ValueError('Unknown alert source')
        return {**SOURCES, **value}


class Alert(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    source: str
    kind: str = Field(default='', max_length=40)
    level: Level = 'info'
    title: str = Field(min_length=1, max_length=90)
    body: str = Field(default='', max_length=220)
    nav: Optional[str] = Field(default=None, max_length=240)
    card_id: Optional[str] = None
    away: bool = True

    @field_validator('source')
    @classmethod
    def source_name(cls, value):
        if value not in SOURCES:
            raise ValueError('Unknown alert source')
        return value


class AlertsBody(StrictModel):
    alerts: list[Alert] = Field(max_length=20)


class ReadBody(StrictModel):
    ids: list[str] = Field(default_factory=list, max_length=100)
    all: bool = False


class TestBody(StrictModel):
    level: Level = 'info'


def enabled():
    return os.environ.get('DEV_ALERTS', 'on').strip().lower() != 'off'


async def settings(c):
    rows = await store.get(c, 'dev_alert_settings', {'id': 'eq.1', 'select': 'settings'})
    return Settings.model_validate(rows[0]['settings']) if rows else Settings()


def quiet_at(config, stamp):
    q = config.quiet
    if not q.on or q.start == q.end:
        return False
    clock = stamp.astimezone(ZoneInfo(config.tz)).strftime('%H:%M')
    return q.start <= clock < q.end if q.start < q.end else clock >= q.start or clock < q.end


async def budget(bucket, key, maximum=None):
    # The shared DB limiter is synchronous; do not block the request loop.
    return await asyncio.to_thread(rate_limit.allow_strict, bucket, key, max_requests=maximum)


async def _watched(c, nav, device_id):
    if nav != NAV + 'kai' and not nav.startswith(NAV + 'fleet:'):
        return False
    params = {'revoked': 'eq.false', 'select': 'id,kai_watch_until,fleet_open_until'}
    if nav.startswith(NAV + 'fleet:'):
        parts = nav[len(NAV):].split(':')
        if len(parts) != 3:
            return False
        params['id'] = f'eq.{store.uid(parts[1])}'
    elif device_id:
        params['id'] = f'eq.{device_id}'
    rows = await store.get(c, 'dev_bridge_devices', params)
    field = 'kai_watch_until' if nav == NAV + 'kai' else 'fleet_open_until'
    return any((store.parse(r.get(field)) or store.now()-timedelta(days=1)) > store.now() for r in rows)


def _nav(value):
    value = value or NAV + 'alerts'
    if not value.startswith(NAV):
        raise HTTPException(422, 'Alert nav must target the Dev Desk')
    target = value[len(NAV):]
    if target in ('kai', 'alerts'):
        return value
    if target.startswith('fleet:'):
        from dev_fleet import session_key
        bits = target.split(':')
        if len(bits) != 3:
            raise HTTPException(422, 'Invalid fleet nav')
        return NAV + 'fleet:' + store.uid(bits[1]) + ':' + session_key(bits[2])
    if target.startswith('watch:'):
        return NAV + 'watch:' + store.uid(target[6:])
    return NAV + store.uid(target)


async def _email(row):
    from email_sender import send_via_resend
    recipient = os.environ.get('PLATFORM_OWNER_EMAIL')
    if not recipient:
        return False
    try:
        await send_via_resend(to_email=recipient, to_name=None,
            from_email=os.environ.get('RESEND_FROM_EMAIL') or 'noreply@mysolutionist.app',
            from_name='Dev Desk', subject='[Dev Desk] ' + row['title'],
            # Plain text; never allow relay text to become email markup.
            body=__import__('html').escape(row['body']), reply_to=None,
            idempotency_key='dev-alert-' + row['id'])
        return True
    except Exception:
        return False  # The inbox remains the durable delivery path.


async def raise_alert(c, *, source, kind, key, level, title, body, nav=None,
                      card_id=None, device_id=None, watch_id=None, away=True):
    config = await settings(c)
    if source not in SOURCES:
        raise HTTPException(422, 'Unknown alert source')
    if level not in ('info', 'warn', 'urgent'):
        raise HTTPException(422, 'Unknown alert level')
    if not enabled() or not config.enabled or config.sources[source] == 'off':
        return 'off'
    title, body = dev_redact.text(title)[:90], dev_redact.text(body)[:220]
    if source in DEVICE_SOURCES and level == 'urgent':
        level = 'warn'
    # Dedupe keys may themselves contain secrets. Hash before storing them;
    # KAI cannot evade dedupe by supplying a different caller key.
    identity = title + '\n' + body if source == 'kai' else key
    dedupe_key = hashlib.sha256(identity.encode()).hexdigest()
    row = {'id': str(uuid4()), 'source': source, 'kind': dev_redact.text(kind)[:40], 'key': dedupe_key,
           'level': level, 'title': title, 'body': body, 'nav': _nav(nav),
           'device_id': device_id, 'watch_id': watch_id, 'card_id': card_id,
           'delivered': 'inbox', 'count': 1, 'pushed': 0, 'created_at': store.z(store.now())}
    claim = await store.rpc(c, 'dev_alert_claim', {'p_row': row})
    if claim.get('deduped'):
        return 'deduped'
    row = claim['row']

    async def finish(outcome, pushed=0):
        await store.patch(c, 'dev_alerts', {'id': f"eq.{row['id']}"}, {'delivered': outcome, 'pushed': pushed})
        return outcome

    # KAI notify is a separate source budget, including inbox/quiet events.
    if source == 'kai' and not await budget('dev_kai_notify', 'owner'):
        return await finish('rate')
    if config.sources[source] == 'inbox' or (not away and level != 'urgent'):
        return 'inbox'
    if await _watched(c, row['nav'], device_id):
        return 'inbox'
    if quiet_at(config, store.now()) and not (level == 'urgent' and config.quiet.urgent_breaks_through):
        return await finish('quiet')
    if (not await budget('dev_alert_source', source, config.limits.per_source_10min) or
            not await budget('dev_alert_push', 'owner', config.limits.per_hour)):
        return await finish('rate')
    tag = f"dev-alert-{source}-{hashlib.sha1(identity.encode()).hexdigest()[:8]}"
    pushed = await _push_owner(c, title, body, nav=row['nav'], tag=tag)
    if pushed:
        return await finish('pushed', pushed)
    if (level == 'urgent' and config.email_fallback == 'urgent' and
            await budget('dev_alert_email', 'owner') and await _email(row)):
        return await finish('email')
    return 'inbox'


@router.post('/dev-bridge/alerts')
async def alerts_raise(body: AlertsBody, authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        # Validate the whole batch before writing any row.
        for alert in body.alerts:
            if alert.source not in DEVICE_SOURCES:
                raise HTTPException(422, 'This source is server-only')
            _nav(alert.nav)
            if alert.card_id and not await store.get(c, 'dev_cards', {
                    'id': f'eq.{store.uid(alert.card_id)}', 'device_id': f"eq.{device['id']}",
                    'expires_at': f'gt.{store.z(store.now())}'}):
                raise HTTPException(404, 'No such device card')
        results = []
        for alert in body.alerts:
            delivered = await raise_alert(c, **alert.model_dump(), device_id=device['id'])
            results.append({'key': alert.key, 'delivered': delivered})
    return {'ok': True, 'results': results}


def shown(row):
    return {k: row.get(k) for k in _COLUMNS.split(',')}


def cursor(since):
    if not since:
        return None
    stamp = store.parse(since)
    if stamp is None:
        raise HTTPException(422, 'Invalid since timestamp')
    return store.z(stamp)


@router.get('/dev-bridge/alerts/feed')
async def alerts_feed(since: Optional[str] = None, authorization: Optional[str] = Header(None)):
    start = cursor(since) or store.z(store.now()-timedelta(minutes=5))
    stamp = store.z(store.now())
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        device = await _require_device(c, authorization)
        # Global CI/deploy failures plus this device's watch results. Never
        # another device's data, nor desktop events that could feed a loop.
        rows = await store.all_rows(c, 'dev_alerts', {'source': f"in.({','.join(sorted(SERVER_SOURCES))})",
            'created_at': f'gt.{start}', 'and': f'(created_at.lte.{stamp})',
            'or': f"(device_id.eq.{device['id']},device_id.is.null)", 'order': 'created_at,id'})
    rows = [r for r in rows if (r['source'] in ('ci', 'deploys') and r['level'] in ('warn', 'urgent'))
            or (r.get('device_id') == device['id'] and r.get('watch_id'))]
    return {'ok': True, 'alerts': [shown(r) for r in rows], 'now': stamp}


@router.get('/platform/dev-desk/alerts')
async def alerts_list(since: Optional[str] = None, limit: int = 50, _owner=Depends(require_owner)):
    if not 1 <= limit <= 100:
        raise HTTPException(422, 'limit must be 1..100')
    params = {'select': _COLUMNS, 'order': 'created_at.desc', 'limit': str(limit)}
    if since:
        params['created_at'] = f'gt.{cursor(since)}'
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        rows = await store.get(c, 'dev_alerts', params)
        count = await store.rpc(c, 'dev_alert_unread', {})
    return {'ok': True, 'alerts': [shown(r) for r in rows], 'unread': count, 'now': store.z(store.now())}


@router.post('/platform/dev-desk/alerts/read')
async def alerts_read(body: ReadBody, _owner=Depends(require_owner)):
    params = {'read_at': 'is.null'}
    if not body.all:
        if not body.ids:
            raise HTTPException(422, 'ids or all required')
        params['id'] = f"in.({','.join(store.uid(i) for i in body.ids)})"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await store.patch(c, 'dev_alerts', params, {'read_at': store.z(store.now())})
    return {'ok': True}


@router.get('/platform/dev-desk/alerts/settings')
async def alerts_settings_get(_owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        config = await settings(c)
    return {'ok': True, 'settings': config.model_dump()}


@router.put('/platform/dev-desk/alerts/settings')
async def alerts_settings_put(body: Settings, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await store.db(c, 'POST', 'dev_alert_settings', body={'id': 1, 'settings': body.model_dump(),
                       'updated_at': store.z(store.now())}, prefer='resolution=merge-duplicates,return=representation')
    return {'ok': True, 'settings': body.model_dump()}


@router.post('/platform/dev-desk/alerts/test')
async def alerts_test(body: TestBody, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        delivered = await raise_alert(c, source='schedules', kind='test', key=str(uuid4()),
            level=body.level, title='Dev Desk test', body='Your alert delivery test.', nav=NAV+'alerts')
    return {'ok': True, 'delivered': delivered}


async def dev_alert_digest_tick():
    if not enabled():
        return
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        config = await settings(c)
        if not config.enabled or quiet_at(config, store.now()):
            return
        modes = 'rate,quiet' if config.quiet.morning_digest else 'rate'
        rows = await store.all_rows(c, 'dev_alerts', {'delivered': f'in.({modes})', 'digested_at': 'is.null',
            'created_at': f'gt.{store.z(store.now()-timedelta(days=30))}', 'order': 'created_at,id'})
        rows = [r for r in rows if config.sources.get(r['source']) == 'push']
        if not rows or not await budget('dev_alert_digest', 'owner'):
            return
        total = sum(r.get('count', 1) for r in rows)
        pushed = await _push_owner(c, f'{total} more alerts', 'Open your Dev Desk inbox for the details.',
                                   nav=NAV+'alerts', tag='dev-alert-digest')
        if pushed:
            for offset in range(0, len(rows), 100):
                ids = ','.join(r['id'] for r in rows[offset:offset+100])
                await store.patch(c, 'dev_alerts', {'id': f'in.({ids})'}, {'digested_at': store.z(store.now())})
