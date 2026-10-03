"""Read-only, model-free appointment checks over fresh scheduling evidence.

The caller supplies a freshly owner-verified business and authenticated context.
None means unsupported scope: continue normal conversation handling. Returned
answers are deterministic read results, never bookings or permission to book.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo

from availability import BusinessAvailability, is_open_default
from availability_engine import compute_slots
from chief_host import _sb

PAGE_SIZE = 100
MAX_ROWS = 500
CHECK_BUDGET_S = 6.0
AMPM_QUESTION = 'Do you mean those appointment times in the morning or afternoon? Please include a.m. or p.m.'



class Unavailable(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    service: str
    day: str
    clocks: tuple[str, ...]


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _text(value):
    value = str(value or '').replace('\u2019', "'").lower()
    value = re.sub(r'\b([ap])\.m\.', r'\1m', value)
    value = re.sub(r'\b(?:uh|um)\b|\bof course\b', '', value)
    return re.sub(r'\s+', ' ', value).strip()


def request_shape(req):
    """Early read-candidate gate; never authorizes a write or consumes the request."""
    if os.getenv('CHIEF_AVAILABILITY_CHECK', 'on').lower() in ('off', 'false', '0'):
        return False
    if _followup(req) is not None:
        return True
    text = _text(_field(req, 'message', ''))
    return bool(re.search(r'\b(?:check|see if|would fit|can fit)\b', text)
                and re.search(r'\b(?:appointments?|bookings?|availability)\b', text))


_CLOCK = r'\d{1,2}(?::\d{2})?(?: ?[ap]m)?'
_MAIN = re.compile(
    r'^(?:(?:please )?(?:can you )?check (?:whether|if)|'
    r'(?:(?:i (?:want|need)(?: you)? )?to see if i have)) '
    r'(?P<count>two|2|one|1|a) (?:(?P<service>[a-z][a-z -]{0,70}?) )?appointments?'
    r'(?: would fit| can fit| that i can fit in)? '
    r'(?P<day>next (?:week on )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|'
    r'\d{4}-\d{2}-\d{2})[, ]+'
    r'(?:at |one at )(?P<first>' + _CLOCK + r')'
    r'(?:[, ]+(?:and |the other (?:one )?at )(?P<second>' + _CLOCK + r'))?'
    r'(?P<tail>.*)$')
_TAIL = re.compile(
    r'^(?:using my (?:business )?time ?zone|'
    r'use (?:them[, ]+)?my (?:business )?time ?zone|'
    r'(?:then )?check them (?:again )?together against my existing bookings? and capacity|'
    r'suggest alternatives if they conflict|'
    r"don't (?:book or )?change anything|do not (?:book or )?change anything|"
    r'just share that with me)(?=$|[,.!?; ])')


def parse_request(message):
    text = _text(message)
    match = _MAIN.fullmatch(text)
    if not match:
        return None
    tail = match['tail']
    while tail.strip(' ,.!?;'):
        tail = tail.lstrip(' ,.!?;')
        tail = re.sub(r'^and ', '', tail)
        part = _TAIL.match(tail)
        if not part:
            return None
        tail = tail[part.end():]
    service = (match['service'] or '').strip()
    if re.search(r'\b(?:with|for|only|staff|room|reschedule|move|cancel|send|remind|create)\b', service):
        return None
    clocks = tuple(x for x in (match['first'], match['second']) if x)
    if len(clocks) != (2 if match['count'] in ('two', '2') else 1):
        return None
    return Check(service, match['day'], clocks)


def _ampm_prompt(text):
    if not isinstance(text, str) or not text.endswith(AMPM_QUESTION):
        return False
    lead = text[:-len(AMPM_QUESTION)].strip()
    if not lead:
        return True
    # A small acknowledgment or future-intention opener conveys no constraint.
    # Do not strip arbitrary prose, factual claims, or a different question.
    return bool(re.fullmatch(
        r"(?:(?:okay|ok|sure|all right|absolutely)[,.! ]*)?"
        r"(?:(?:i'll|i will|let me) (?:check|take a look)(?: (?:that|those times|the availability|your calendar))?(?: for you)?)?"
        r"[.! ]*", _text(lead)))


def _choice_prompt(text, answer):
    if not isinstance(text, str):
        return False
    marker = 'Which service do you mean: '
    index = text.find(marker)
    if index < 0 or not text.endswith('?'):
        return False
    # Reuse only the same small, claim-free opener vocabulary.
    if not _ampm_prompt(text[:index] + AMPM_QUESTION):
        return False
    body, names = text[index + len(marker):-1], []
    while body:
        match = re.match(r'([^(),]{1,100}) \((\d{1,4}) minutes\)(?:, |$)', body)
        if not match or not _safe_name(match[1]):
            return False
        names.append(_text(match[1]))
        body = body[match.end():]
    return bool(names) and answer in names


def _resolved_check(req, depth=0):
    check = parse_request(_field(req, 'message', ''))
    if check is not None:
        return check, req
    if depth >= 3:
        return None
    answer = _text(_field(req, 'message', '')).strip(' .!?')
    history = list(_field(req, 'conversation_history', []) or [])
    if history and _field(history[-1], 'role') == 'user' and _text(_field(history[-1], 'content')) == _text(_field(req, 'message')):
        history.pop()
    if (len(history) < 2 or _field(history[-1], 'role') != 'assistant'
            or _field(history[-2], 'role') != 'user'):
        return None
    question = _field(history[-1], 'content')
    period = 'am' if answer in ('morning', 'in the morning') else answer
    meridiem = period in ('am', 'pm') and _ampm_prompt(question)
    service_choice = _choice_prompt(question, answer)
    if not meridiem and not service_choice:
        return None
    previous = {key: _field(req, key) for key in ('business_id', 'mode', 'image_ids', 'intent', 'current_context')}
    previous.update(message=_field(history[-2], 'content'), conversation_history=history[:-2])
    resolved = _resolved_check(previous, depth+1)
    if resolved is None:
        return None
    check, scope = resolved
    if meridiem:
        if resolve_clocks(check.clocks) is not None or any(_clock_parts(c) is None or _clock_parts(c)[0] > 12 for c in check.clocks):
            return None
        check = Check(check.service, check.day, tuple(c if _clock_parts(c)[2] else c + ' ' + period for c in check.clocks))
    else:
        check = Check(answer, check.day, check.clocks)
    return check, scope


def _followup(req):
    return None if parse_request(_field(req, 'message', '')) else _resolved_check(req)


def eligible_request(req):
    """Pure admission for a deterministic answer/clarification, with history intact."""
    if os.getenv('CHIEF_AVAILABILITY_CHECK', 'on').lower() in ('off', 'false', '0'):
        return False
    resolved = _resolved_check(req)
    return resolved is not None and _history_supported(resolved[1])


def recognizes_request(message):
    return parse_request(message) is not None


def _history_supported(req):
    if (_field(req, 'image_ids') or (_field(req, 'mode') or '') not in ('', 'chief')
            or _field(req, 'intent') == 'build'):
        return False
    view = _field(req, 'current_context')
    if any(_field(view, key) for key in ('viewing_contact_id', 'viewing_module_id', 'viewing_session_id')):
        return False
    current = _text(_field(req, 'message', ''))
    history = list(_field(req, 'conversation_history', []) or [])
    # Frontends may include this exact current user turn at the end of history.
    if history and _field(history[-1], 'role') == 'user' and _text(_field(history[-1], 'content')) == current:
        history.pop()
    from chief_invoice_readout import invoice_display_request
    from chief_quick_plan import eligible as plain_plan
    pending = False
    for message in history:
        text = _text(_field(message, 'content', ''))
        role = _field(message, 'role', '')
        if role == 'assistant':
            pending |= '?' in text and bool(re.search(r'\b(?:appointments?|bookings?|calendar|timezone|time zone|staff|rooms?)\b', text))
        elif role == 'user':
            if not text or re.fullmatch(r'\[system:opening_greeting:(?:morning|afternoon|evening)\]', text):
                continue
            if pending:
                return False
            # Only complete known independent operations are proven unrelated.
            # Arbitrary prior prose can contain duration, buffers, timezones or
            # preferences without any scheduling keyword; keep its full context.
            if invoice_display_request(text) or plain_plan(SimpleNamespace(message=text)):
                continue
            if re.fullmatch(r'(?:hi|hello|hey|good morning|good afternoon|good evening)[.!?]*', text):
                continue
            return False

    return True


def _safe_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100 or re.search(r'[\x00-\x1f\x7f\[\]<>]', value):
        return False
    from chief_speech_boundary import internal_scaffolding
    from untrusted_text import detect_injection, ACTION_TAGLIKE_RE
    return not (internal_scaffolding(value) or detect_injection(value) or ACTION_TAGLIKE_RE.search(value))


async def _rows(client, path):
    rows = await _sb(client, 'GET', path)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise Unavailable('I could not read the current scheduling records reliably. Please try the check again.')
    return rows


async def _pages(client, path, *, cap=MAX_ROWS):
    rows, seen = [], set()
    while True:
        page = await _rows(client, f'{path}&order=id.asc&limit={PAGE_SIZE}&offset={len(rows)}')
        if not page:
            return rows
        for row in page:
            key = row.get('id')
            if not isinstance(key, str) or not key or key in seen:
                raise Unavailable('The scheduling records changed during the check. Please try again.')
            seen.add(key)
        rows.extend(page)
        if len(rows) > cap:
            raise Unavailable('There are too many scheduling records for this quick check. Please use the calendar.')


async def load_offerings(client, business_id):
    """Reusable read-only preparation: complete active catalog, bounded to 100 rows."""
    bid = str(UUID(str(business_id)))
    rows = await _pages(client, f'/offerings?business_id=eq.{bid}&is_active=eq.true'
                        '&select=id,business_id,name,is_active,duration_min', cap=100)
    _validate_offerings(rows, bid)
    return rows


def _validate_offerings(rows, bid):
    if not isinstance(rows, list):
        raise Unavailable('I could not verify the available services.')
    for row in rows:
        if (not isinstance(row, dict) or row.get('business_id') != bid or row.get('is_active') is not True
                or not _safe_name(row.get('name'))):
            raise Unavailable('I could not verify the available services.')
        UUID(str(row.get('id')))


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440:
        raise Unavailable('A saved service or booking duration needs checking before I can confirm availability.')
    return value


def _instant(value):
    if not isinstance(value, str):
        raise Unavailable('A saved calendar time needs checking before I can confirm availability.')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise Unavailable('A saved calendar time needs checking before I can confirm availability.') from exc
    return (result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result).astimezone(timezone.utc)


def _settings(raw, practitioner_tz=None):
    if not isinstance(raw, dict) or not raw:
        raise Unavailable('Please set business hours and a timezone before I check these appointments.')
    av = BusinessAvailability.model_validate(raw)
    if is_open_default(av):
        raise Unavailable('Please set business hours before I check these appointments.')
    if raw.get('timezone') and not av.timezone:
        raise Unavailable('The business timezone needs correcting before I can check these appointments.')
    name = av.timezone or practitioner_tz
    if not name:
        raise Unavailable('Please set your business timezone before I check these appointments.')
    tz = ZoneInfo(name)
    if 'concurrent_capacity' in raw and (type(raw['concurrent_capacity']) is not int or not 1 <= raw['concurrent_capacity'] <= 20):
        raise Unavailable('The saved appointment capacity needs checking first.')
    for day in av.overrides:
        date.fromisoformat(day.date)
    for block in av.blocks:
        if date.fromisoformat(block.start) > date.fromisoformat(block.end):
            raise Unavailable('A blocked date range needs correcting first.')
    for hours in [*av.weekly.model_dump().values(), *[o.hours for o in av.overrides]]:
        for entry in hours:
            start, end = (entry['start'], entry['end']) if isinstance(entry, dict) else (entry.start, entry.end)
            if start >= end:
                raise Unavailable('A saved business-hours range needs correcting first.')
    if av.arrival_window_min:
        raise Unavailable('Your schedule uses arrival windows. Please check a window rather than an exact appointment time.')
    return av, tz


def resolve_day(value, now, tz):
    local = now.astimezone(tz).date()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    target = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].index(value.rsplit(' ', 1)[-1])
    if value.startswith('next week'):
        return local + timedelta(days=7 - local.weekday() + target)
    return local + timedelta(days=(target - local.weekday()) % 7 or 7)


def _clock_parts(value):
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(?: ?([ap]m))?', value)
    if not match:
        return None
    hour, minute, period = int(match[1]), int(match[2] or 0), match[3]
    if minute > 59 or hour > 23 or (period and not 1 <= hour <= 12):
        return None
    return hour, minute, period


def resolve_clocks(values):
    parts = [_clock_parts(v) for v in values]
    if any(p is None for p in parts):
        return None
    if len(parts) == 2 and not parts[0][2] and parts[1][2] and 1 <= parts[0][0] <= parts[1][0] <= 12:
        parts[0] = (*parts[0][:2], parts[1][2])
    clocks = []
    for hour, minute, period in parts:
        if not period and 1 <= hour <= 12:
            return None
        if period:
            hour = hour % 12 + (12 if period == 'pm' else 0)
        clocks.append(time(hour, minute))
    return clocks


def _reply(status, response, **data):
    return {'response': response, 'actions_taken': [],
            'grounding': {'status': 'records' if status in ('fits', 'conflicts') else 'clarification', 'sources': []},
            'availability_check': {'status': status, **data}}


def _fmt(instant, tz):
    local = instant.astimezone(tz)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'a.m.' if local.hour < 12 else 'p.m.'}"


def evaluate(*, day, clocks, service, business_id, availability, tz, bookings, busy, now):
    """Pure joint capacity computation; proposed fits consume capacity in order."""
    occupied = []
    for row in bookings:
        if row.get('business_id') != business_id or row.get('status') != 'active':
            raise Unavailable('I could not verify the existing bookings for this business.')
        occupied.append({'appointment_at': _instant(row.get('appointment_at')).isoformat(),
            'duration_min_at_booking': _duration(row.get('duration_min_at_booking'))})
    for row in busy:
        if row.get('business_id') != business_id or _instant(row.get('ends_at')) <= _instant(row.get('starts_at')):
            raise Unavailable('I could not verify the outside-calendar busy times.')
    duration = _duration(service['duration_min'])
    results = []
    for clock in clocks:
        local = datetime.combine(day, clock, tzinfo=tz)
        start = local.astimezone(timezone.utc)
        if start.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None) or local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
            return _reply('clarification', 'That local time is ambiguous or skipped by a clock change. Please choose a different time.')
        slots = compute_slots(availability=availability, practitioner_tz=tz.key,
            existing_bookings=occupied, offering_duration_min=duration, from_date=day,
            to_date=day, now=now, busy_blocks=busy)
        usable = []
        for slot in slots:
            instant = _instant(slot['start_utc'])
            wall = instant.astimezone(tz)
            end = wall + timedelta(minutes=duration)
            if (wall.replace(tzinfo=None).isoformat() == slot['start_local']
                    and end.astimezone(timezone.utc) - instant == timedelta(minutes=duration)
                    and wall.replace(fold=0).utcoffset() == wall.replace(fold=1).utcoffset()):
                usable.append(instant)
        fits = start in usable
        result = {'start': start.isoformat(), 'status': 'fits' if fits else 'conflict', 'duration_min': duration}
        if fits:
            occupied.append({'appointment_at': start.isoformat(), 'duration_min_at_booking': duration})
        else:
            result['alternatives'] = [v.isoformat() for v in sorted(usable, key=lambda v: (abs((v-start).total_seconds()), v))[:2]]
        results.append(result)
    heading = f"For {day.strftime('%A, %B')} {day.day} in your business timezone, using your {duration}-minute {service['name']} service: "
    lines = []
    for result in results:
        label = _fmt(_instant(result['start']), tz)
        if result['status'] == 'fits':
            lines.append(f'{label} fits.')
        else:
            sentence = f'{label} conflicts with the saved schedule or capacity, when checked together.'
            alternatives = result.get('alternatives', [])
            if alternatives:
                sentence += ' Nearby options: ' + ' or '.join(_fmt(_instant(v), tz) for v in alternatives) + '.'
            else:
                sentence += ' I found no same-day alternative.'
            lines.append(sentence)
    if any(r.get('alternatives') for r in results):
        lines.append('Those alternatives are separate options; check a revised pair together before booking.')
    lines.append('Nothing is booked or changed.')
    return _reply('conflicts' if any(r['status']=='conflict' for r in results) else 'fits',
        heading + ' '.join(lines), timezone=tz.key, date=day.isoformat(), checked_at=now.isoformat(),
        offering_id=service['id'], appointments=results)


async def _check_request(client, req, biz, *, now=None, prepared=None):
    """Return deterministic read answer or None for unsupported conversational scope."""
    if os.getenv('CHIEF_AVAILABILITY_CHECK', 'on').lower() in ('off', 'false', '0'):
        return None
    continuation = _followup(req)
    if continuation is not None:
        check, req = continuation
    else:
        check = parse_request(_field(req, 'message', ''))
    if check is None or not _history_supported(req):
        return None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    clocks = resolve_clocks(check.clocks)
    if clocks is None:
        return _reply('clarification', AMPM_QUESTION)
    if not check.service:
        return _reply('clarification', 'Which service should I use for these appointments?')
    try:
        bid = str(UUID(str(biz['id'])))
        if str(_field(req, 'business_id', bid)) != bid:
            return None
        rows = await _rows(client, f'/businesses?id=eq.{bid}&select=id,owner_id,settings&limit=1')
        if len(rows) != 1 or rows[0].get('id') != bid or rows[0].get('owner_id') != biz.get('owner_id'):
            raise Unavailable('I could not verify the current business scheduling settings.')
        settings = rows[0].get('settings')
        if not isinstance(settings, dict):
            raise Unavailable('Please set your business hours and timezone first.')
        raw = settings.get('availability')
        profile_tz = None
        if isinstance(raw, dict) and not raw.get('timezone') and biz.get('owner_id'):
            owner = str(UUID(str(biz['owner_id'])))
            profiles = await _rows(client, f'/practitioner_profiles?owner_id=eq.{owner}&select=timezone&limit=1')
            profile_tz = profiles[0].get('timezone') if len(profiles) == 1 else None
        av, tz = _settings(raw, profile_tz)
        day = resolve_day(check.day, now, tz)
        if day < now.astimezone(tz).date() or (day-now.astimezone(tz).date()).days > 31:
            return _reply('clarification', 'Please choose a date within the next 31 days for this check.')
        # Preparation is only a candidate index. A fresh narrowed query checks
        # renamed/disabled/duration-changed services AND newly matching names.
        catalog_path = None
        if isinstance(prepared, dict) and prepared.get('business_id') == bid:
            try:
                age = (now - _instant(prepared.get('captured_at'))).total_seconds()
                cached = prepared.get('offerings')
                _validate_offerings(cached, bid)
                if 0 <= age <= 30 and len(cached) <= 100:
                    candidates = [o for o in cached if re.search(r'\b'+re.escape(check.service)+r'\b', _text(o['name']))]
                    ids = sorted({str(UUID(o['id'])) for o in candidates})
                    condition = 'name.ilike.*' + check.service + '*'
                    if ids:
                        condition += ',id.in.(' + ','.join(ids) + ')'
                    catalog_path = f'/offerings?business_id=eq.{bid}&is_active=eq.true&or=({quote(condition, safe=".,()*")})' + '&select=id,business_id,name,is_active,duration_min'
            except (ValueError, TypeError, KeyError, Unavailable):
                pass
        lo = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
        hi = lo + timedelta(days=2)
        async with asyncio.TaskGroup() as tasks:
            catalog_task = tasks.create_task(_pages(client, catalog_path, cap=100) if catalog_path else load_offerings(client, bid))
            bookings_task = tasks.create_task(_pages(client, f'/module_entries?business_id=eq.{bid}&status=eq.active&appointment_at=not.is.null'
                '&select=id,business_id,status,appointment_at,duration_min_at_booking'))
            busy_task = tasks.create_task(_pages(client, f'/calendar_busy_blocks?business_id=eq.{bid}&starts_at=lt.{quote(hi.isoformat(), safe="")}'
                f'&ends_at=gt.{quote(lo.isoformat(), safe="")}&select=id,business_id,starts_at,ends_at'))
        offerings, bookings, busy = catalog_task.result(), bookings_task.result(), busy_task.result()
        _validate_offerings(offerings, bid)
        exact = [o for o in offerings if _text(o['name']) == check.service]
        matches = exact or [o for o in offerings if re.search(r'\b'+re.escape(check.service)+r'\b', _text(o['name']))]
        if len(matches) != 1:
            choices = [o for o in (matches or offerings) if type(o.get('duration_min')) is int and 1 <= o['duration_min'] <= 1440]
            options = ', '.join(f"{o['name']} ({o['duration_min']} minutes)" for o in choices[:4])
            return _reply('clarification', ('Which service do you mean: '+options+'?') if options else 'I could not find an active service with that name. Which service should I check?')
        service = matches[0]
        return evaluate(day=day, clocks=clocks, service=service, business_id=bid,
                        availability=av, tz=tz, bookings=bookings, busy=busy, now=now)
    except Unavailable as exc:
        return _reply('unavailable', str(exc))
    except (ValueError, TypeError, KeyError, AttributeError):
        return _reply('unavailable', 'The saved scheduling details need checking before I can confirm availability.')
    except Exception:
        return _reply('unavailable', 'I could not retrieve all the current scheduling records, so these appointments have not been checked. Please try again.')


async def check_request(client, req, biz, *, now=None, prepared=None):
    """Bounded read check. No partial snapshot, write, reservation or model call."""
    try:
        async with asyncio.timeout(CHECK_BUDGET_S):
            return await _check_request(client, req, biz, now=now, prepared=prepared)
    except TimeoutError:
        return _reply('unavailable', "I couldn't retrieve all the current scheduling records in time, so these appointments have not been checked. Please try again.")
