"""Read-only, bounded Square appointment preview. Never writes calendar/customer rows."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
import square_connector as sq

MAX_LOCATIONS = 20
MAX_ROWS = 200
MAX_REQUESTS = 20
STATUSES = {'PENDING','ACCEPTED','DECLINED','CANCELLED_BY_CUSTOMER','CANCELLED_BY_SELLER','NO_SHOW'}


class Selection(BaseModel):
    connection_id: UUID
    selection_revision: UUID
    location_ids: list[str] = Field(max_length=MAX_LOCATIONS)


class PreviewRequest(BaseModel):
    connection_id: UUID
    selection_revision: UUID
    start_at: datetime
    end_at: datetime


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'Use dates with an explicit time zone.') from None


async def current(business_id, cfg, connection_id=None, selection_revision=None):
    row = await sq.connection(business_id, cfg)
    if not row or row['status'] != 'connected':
        raise HTTPException(409, 'Connect Square first.')
    if (connection_id and str(connection_id) != row['connection_id']) or (
            selection_revision and str(selection_revision) != row['selection_revision']):
        raise HTTPException(409, 'Your Square connection or locations changed. Refresh and try again.')
    return row


async def location_data(business_id, cfg):
    initial = await current(business_id, cfg)
    token = await sq.access_token(business_id, cfg)
    payload = await sq.square(cfg, 'GET', '/v2/locations', token=token)
    row = await current(business_id, cfg, initial['connection_id'])
    return row, payload.get('locations', [])


async def save_selection(business_id, user_id, cfg, body: Selection):
    if len(set(body.location_ids)) != len(body.location_ids):
        raise HTTPException(422, 'Choose each location only once.')
    await current(business_id, cfg, body.connection_id, body.selection_revision)
    row, locations = await location_data(business_id, cfg)
    valid = {r['id'] for r in locations if r.get('status') == 'ACTIVE' and r.get('id')}
    if any(loc not in valid for loc in body.location_ids):
        raise HTTPException(422, 'Choose active locations from this Square account.')
    revision = await sq.rpc('save_locations', p_business=str(business_id), p_environment=cfg.environment,
        p_user=str(user_id), p_connection=str(body.connection_id), p_selection_revision=str(body.selection_revision),
        p_locations=body.location_ids)
    if not revision:
        raise HTTPException(409, 'Your Square connection or locations changed. Refresh and try again.')
    return {'selected_location_ids': body.location_ids, 'selection_revision': revision,
            'connection_id': row['connection_id']}


def booking_row(booking, location, start, end):
    try:
        at = instant(booking['start_at'])
        booking_id = booking['id']
        version = booking.get('version', 0)
        if not isinstance(booking_id, str) or not booking_id or type(version) is not int:
            raise ValueError()
    except (KeyError, ValueError, HTTPException):
        raise HTTPException(502, 'Square returned an incomplete appointment. Try again.') from None
    if booking.get('location_id') != location['id'] or not start <= at < end:
        return None
    segments = booking.get('appointment_segments', [])
    durations = [s.get('duration_minutes') for s in segments]
    duration = sum(durations) if durations and all(type(v) is int and v >= 0 for v in durations) else None
    return {'id': booking_id, 'version': version, 'start_at': at.isoformat(),
            'status': booking.get('status') if booking.get('status') in STATUSES else 'UNKNOWN',
            'location_id': location['id'], 'location_name': location.get('name') or 'Square location',
            'timezone': location.get('timezone') or 'UTC', 'service_duration_minutes': duration,
            'all_day': booking.get('all_day') is True}


async def preview(business_id, cfg, body: PreviewRequest):
    start, end = instant(body.start_at), instant(body.end_at)
    if end <= start or end - start > timedelta(days=93):
        raise HTTPException(422, 'Choose a date range of up to 93 days, with the end after the start.')
    row = await current(business_id, cfg, body.connection_id, body.selection_revision)
    selected = row.get('selected_location_ids', [])
    if not selected:
        raise HTTPException(422, 'Save at least one Square location first.')
    if len(selected) > MAX_LOCATIONS:
        raise HTTPException(422, 'Choose no more than 20 locations.')
    _, locations = await location_data(business_id, cfg)
    by_id = {loc['id']: loc for loc in locations if loc.get('id') and loc.get('status') == 'ACTIVE'}
    if any(loc not in by_id for loc in selected):
        raise HTTPException(409, 'A saved Square location is no longer active. Refresh and save your locations again.')
    token = await sq.access_token(business_id, cfg)
    bookings, requests, truncated = {}, 0, False
    # Square pages each location/window independently. Windows are at most 31 days.
    for loc_id in selected:
        window = start
        while window < end and not truncated:
            window_end = min(window + timedelta(days=31), end)
            cursor, seen_cursors = None, set()
            while True:
                if requests >= MAX_REQUESTS:
                    truncated = True
                    break
                params = {'location_id': loc_id, 'start_at_min': window.isoformat(),
                          'start_at_max': window_end.isoformat(), 'limit': 100}
                if cursor:
                    params['cursor'] = cursor
                payload = await sq.square(cfg, 'GET', '/v2/bookings', token=token, params=params)
                requests += 1
                for booking in payload.get('bookings', []):
                    item = booking_row(booking, by_id[loc_id], start, end)
                    if item is None:
                        continue
                    old = bookings.get(item['id'])
                    if old is None and len(bookings) >= MAX_ROWS:
                        truncated = True
                        break
                    if old is None or item['version'] > old['version']:
                        bookings[item['id']] = item
                cursor = payload.get('cursor')
                if truncated or not cursor:
                    break
                if not isinstance(cursor, str) or cursor in seen_cursors:
                    raise HTTPException(502, 'Square could not finish loading appointments. Try a shorter date range.')
                seen_cursors.add(cursor)
            window = window_end
        if truncated:
            break
    # Discard the response if another tab changed the connection/selection in flight.
    await current(business_id, cfg, body.connection_id, body.selection_revision)
    rows = sorted(bookings.values(), key=lambda r: (r['start_at'], r['id']))
    return {'appointments': rows, 'shown_count': len(rows), 'truncated': truncated,
            'start_at': start.isoformat(), 'end_at': end.isoformat(), 'read_only': True,
            'connection_id': str(body.connection_id), 'selection_revision': str(body.selection_revision)}
