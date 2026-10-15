"""Shared service-role transport, bounded request parsing and retention for M-3."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from dev_bridge import HTTP_TIMEOUT
from lead_admin import SUPABASE_URL, _service_headers

MIGRATION = 'supabase/APPLY-2026-10-15-dev-desk-relay.sql'


def now():
    return datetime.now(timezone.utc)


def z(t):
    return t.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse(value):
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def uid(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise HTTPException(422, 'Expected a UUID')


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method in ('POST', 'PUT', 'PATCH'):
                cap = 10 * 1024 * 1024 if request.url.path == '/dev-bridge/cards' else 64 * 1024
                # Screens allow 16,000 unicode characters plus JSON framing.
                if request.url.path.endswith('/screen'):
                    cap = 128 * 1024
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > cap:
                        raise HTTPException(413, 'Relay request is too large')
                    data.extend(chunk)
                request._body = bytes(data)
            return await original(request)
        return bounded


async def db(c, method, table, params=None, body=None, *, prefer='return=representation'):
    r = await c.request(method, f'{SUPABASE_URL}/rest/v1/{table}',
                        headers={**_service_headers(), 'Prefer': prefer}, params=params, json=body)
    if r.status_code >= 400:
        # Do not echo DB errors: they may contain the submitted text.
        raise HTTPException(502, f'Dev Desk relay needs {MIGRATION} applied; {table} {method} failed ({r.status_code}).')
    return r.json() if r.content else []


async def get(c, table, params):
    return await db(c, 'GET', table, params)


async def patch(c, table, params, body):
    return await db(c, 'PATCH', table, params, body)


async def insert(c, table, body):
    return await db(c, 'POST', table, body=body)


async def delete(c, table, params):
    return await db(c, 'DELETE', table, params)


async def rpc(c, name, body):
    return await db(c, 'POST', 'rpc/' + name, body=body)


async def all_rows(c, table, params):
    """Page explicitly; Supabase's default 1,000-row cap is not retention."""
    out = []
    while True:
        rows = await get(c, table, {**params, 'limit': '500', 'offset': str(len(out))})
        out.extend(rows)
        if len(rows) < 500:
            return out


async def purge_device(c, device_id):
    from dev_cards import purge_cards
    await delete(c, 'dev_fleet_sessions', {'device_id': f'eq.{device_id}'})
    await patch(c, 'dev_bridge_devices', {'id': f'eq.{device_id}'},
                {'fleet_watch': None, 'fleet_open_until': None})
    await purge_cards(c, {'device_id': f'eq.{device_id}'}, strict=True)


async def dev_relay_purge():
    """Storage first, then rows; a failed delete leaves the row for a retry."""
    from dev_cards import purge_cards
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        stamp = now()
        ended = await all_rows(c, 'dev_fleet_sessions', {
            'select': 'device_id,session_key', 'ended_at': f'lt.{z(stamp-timedelta(hours=1))}',
            'order': 'device_id,session_key'})
        for row in ended:
            await delete(c, 'dev_fleet_screens', {'device_id': f"eq.{row['device_id']}",
                                               'session_key': f"eq.{row['session_key']}"})
        await delete(c, 'dev_fleet_sessions', {'ended_at': f'lt.{z(stamp-timedelta(hours=24))}'})
        await purge_cards(c, {'expires_at': f'lt.{z(stamp)}'})
        await delete(c, 'dev_alerts', {'created_at': f'lt.{z(stamp-timedelta(days=30))}'})
        await delete(c, 'dev_kai_messages', {'created_at': f'lt.{z(stamp-timedelta(days=90))}'})
        await delete(c, 'dev_alert_dedupe', {'source': 'neq.ci', 'seen_at': f'lt.{z(stamp-timedelta(days=30))}'})
        # Watch tables and their seven-day/50-run retention ship in a2.
