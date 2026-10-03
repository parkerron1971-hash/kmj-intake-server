"""Leased event delivery. Retry preparation; never replay uncertain effects."""
from __future__ import annotations

import asyncio
import contextvars
import os
from contextlib import suppress
from uuid import uuid4

import sb_clients

_delivery = contextvars.ContextVar('chief_event_delivery', default=None)


def enabled():
    return os.getenv('CHIEF_DURABLE_EVENTS', 'off').lower() in ('on', 'true', '1')


def rpc(name, args):
    result = sb_clients.sb_post_as_service('/rpc/chief_event_' + name, args)
    if result is None:
        raise RuntimeError('Chief event delivery storage is unavailable.')
    return result


def pending(types):
    rpc('recover', {})
    rows = rpc('pending', {'p_types': list(types)})
    if not isinstance(rows, list):
        raise RuntimeError('Chief event delivery returned an invalid queue.')
    return rows


async def before_actions():
    """Persist the uncertain-effect boundary before tools are exposed."""
    delivery = _delivery.get()
    if delivery is not None:
        ok = await asyncio.to_thread(rpc, 'checkpoint', {**delivery, 'p_phase': 'acting'})
        if ok is not True:
            raise RuntimeError('Chief lost its event lease before acting.')


async def execute(biz, events, runner):
    token = str(uuid4())
    bid = str(biz['id'])
    ids = list(dict.fromkeys(str(e['id']) for e in events if e.get('id') and str(e.get('business_id')) == bid))
    if not ids:
        return None
    claimed = await asyncio.to_thread(rpc, 'claim', {'p_business': bid, 'p_ids': ids, 'p_token': token})
    if not isinstance(claimed, list):
        raise RuntimeError('Chief could not verify the event claim.')
    mine = {str(r['event_id']) for r in claimed}
    if not mine:
        return None
    args = {'p_business': bid, 'p_ids': sorted(mine), 'p_token': token}
    ctx = _delivery.set(args)
    parent = asyncio.current_task()

    async def heartbeat():
        while True:
            await asyncio.sleep(30)
            try:
                ok = await asyncio.to_thread(rpc, 'renew', args)
            except Exception:
                ok = False
            if ok is not True:
                parent.cancel()
                return

    pulse = asyncio.create_task(heartbeat())
    try:
        record = await runner(biz, [e for e in events if str(e['id']) in mine])
        phase = 'needs_review' if record.get('failed') else 'completed'
        ok = await asyncio.to_thread(rpc, 'checkpoint', {
            **args, 'p_phase': phase,
            'p_summary': 'Some actions need review.' if record.get('failed') else str(record.get('recap') or '')[:600]})
        if ok is not True:
            raise RuntimeError('Chief could not confirm completion of the event delivery.')
        return record
    finally:
        # Preparation leases expire into a bounded retry; acting leases expire
        # into needs_review. Cancellation must not erase either durable record.
        pulse.cancel()
        with suppress(asyncio.CancelledError):
            await pulse
        _delivery.reset(ctx)
