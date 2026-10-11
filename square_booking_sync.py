"""Opt-in Square -> Solutionist calendar copies. No native bookings or messages.
Polling reconciles complete rolling windows; an incomplete read never replaces a snapshot.
The DB lease is authoritative across processes, restarts, disconnects and location changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, StrictBool
import square_connector as sq
import square_booking_preview as preview

log = logging.getLogger(__name__)
MAX_ROWS = 5000
MAX_REQUESTS = 100

class SyncSetting(BaseModel):
    connection_id: UUID
    selection_revision: UUID
    enabled: StrictBool


def enabled():
    return os.getenv('SQUARE_BOOKING_SYNC_ENABLED', 'false').lower() == 'true'


def require_enabled():
    if not enabled():
        raise HTTPException(503, 'Square automatic sync is not enabled.')


async def state(business_id, user_id, cfg):
    if not enabled():
        return {'available': False, 'enabled': False, 'appointments': []}
    row = await sq.connection(business_id, cfg)
    if not row or row['status'] != 'connected':
        return {'available': True, 'enabled': False, 'appointments': []}
    rows = await sq.db('GET', 'square_booking_sync', params={
        'business_id': 'eq.' + str(business_id), 'environment': 'eq.' + cfg.environment,
        'owner_id': 'eq.' + str(user_id), 'connection_id': 'eq.' + row['connection_id'],
        'selection_revision': 'eq.' + row['selection_revision'],
        'select': 'enabled,last_synced_at,last_error,window_start,window_end,appointments', 'limit': '1'})
    # Recheck after read: a disconnect/selection change must not release old copies.
    current = await sq.connection(business_id, cfg)
    if not current or current['status'] != 'connected' or any(current[k] != row[k] for k in ('connection_id','selection_revision')):
        raise HTTPException(409, 'Your Square connection changed. Refresh before continuing.')
    data = rows[0] if rows else {'enabled': False, 'appointments': []}
    last = data.get('last_synced_at')
    stale = bool(data.get('enabled') and (not last or preview.instant(last) < datetime.now(timezone.utc)-timedelta(minutes=30)))
    return {'available': True, **data, 'stale': stale, 'environment': cfg.environment,
            'connection_id': row['connection_id'], 'selection_revision': row['selection_revision'],
            'refresh_minutes': 15, 'read_only': True}


async def set_enabled(business_id, user_id, cfg, body):
    # Turning off remains possible even when the worker kill switch is off.
    if body.enabled:
        require_enabled()
    saved = await sq.rpc('sync_set', p_business=str(business_id), p_environment=cfg.environment,
        p_user=str(user_id), p_connection=str(body.connection_id), p_selection=str(body.selection_revision), p_enabled=body.enabled)
    if not saved:
        raise HTTPException(409, 'Your Square connection or locations changed. Refresh before continuing.')
    return {'enabled': body.enabled}


def error_code(exc):
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get('code') == 'square_authorization_required': return 'authorization'
        if detail.get('code') == 'square_appointments_setup_required': return 'setup'
        if exc.status_code == 409: return 'changed'
    return 'unavailable'


async def sync_one(business_id, user_id, cfg):
    require_enabled()
    if str(user_id) not in cfg.owners:
        return False
    claims = await sq.rpc('sync_claim', p_business=str(business_id), p_environment=cfg.environment, p_user=str(user_id))
    if not claims:
        return False
    claim = claims[0]
    start = datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=7)
    end = start + timedelta(days=93)
    rows, error = [], None
    try:
        result = await asyncio.wait_for(preview.preview(business_id, cfg, preview.PreviewRequest(
            connection_id=claim['connection_id'], selection_revision=claim['selection_revision'], start_at=start, end_at=end),
            max_rows=MAX_ROWS, max_requests=MAX_REQUESTS), timeout=120)
        if result['truncated']:
            error = 'capacity'
        else:
            rows = result['appointments']
    except (HTTPException, asyncio.TimeoutError) as exc:
        error = error_code(exc)
    # Don't release any exception text, customer data or provider body to logs/storage.
    if not enabled():
        return False
    return await sq.rpc('sync_finish', p_business=str(business_id), p_environment=cfg.environment,
        p_user=str(user_id), p_lease=claim['lease'], p_appointments=rows,
        p_start=start.isoformat(), p_end=end.isoformat(), p_error=error)


async def sync_due_tick():
    if not enabled(): return
    try:
        cfg = sq.config()
        now = datetime.now(timezone.utc).isoformat()
        rows = await sq.db('GET','square_booking_sync',params={
            'environment':'eq.'+cfg.environment, 'enabled':'eq.true',
            'owner_id':'in.('+','.join(sorted(cfg.owners))+')',
            'due_at':'lte.'+now, 'or':'(lease_until.is.null,lease_until.lt.'+now+')',
            'select':'business_id,owner_id', 'order':'due_at.asc', 'limit':'5'})
        # Max 5 accounts / tick, concurrent under per-account DB leases.
        results = await asyncio.gather(*(sync_one(r['business_id'],r['owner_id'],cfg) for r in rows), return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results):
            log.warning('Square sync tick could not finish one or more accounts')
    except Exception:
        log.warning('Square sync tick unavailable')
