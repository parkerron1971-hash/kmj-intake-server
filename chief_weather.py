"""Bounded, timestamped U.S. weather reads from the National Weather Service.

NWS documents its city/state search at weather.gov/ForecastSearchHelp.html and
its free observation/forecast API at weather.gov/documentation/services-web-api.
Search redirects supply coordinates; they are parsed, never followed. No page
snapshot, model-invented coordinates, paid geocoder, or business data is sent.
"""
import asyncio
from datetime import datetime, timezone
import math
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

TOOL = {
    'name': 'get_weather',
    'description': (
        'Read live National Weather Service observations and a timestamped forecast for a U.S. '
        'city/state or ZIP. ALWAYS use this instead of web_search for U.S. weather, including '
        'a retry after stale search results. Use the location the owner named in this conversation; '
        'ask for the state if ambiguous. Report the observation time, distinguish observations '
        'from forecasts, and never call a forecast current conditions. If unavailable, explain '
        'once; do not repeat the lookup, search snapshots, or offer another identical retry.'),
    'input_schema': {'type': 'object', 'properties': {
        'location': {'type': 'string', 'description': 'U.S. City, ST (two-letter state) or five-digit ZIP; no street address.'}},
        'required': ['location'], 'additionalProperties': False},
}
TURN_GUIDANCE = (
    '\n\nWEATHER LOOKUP: Use get_weather for U.S. current weather and forecasts before answering. '
    'A short yes/retry continues the latest user weather request; reuse that user-supplied location, '
    'not an old assistant weather reading. Ask for city/state if unresolved. Outside U.S. coverage, '
    'use a current official weather source. Never present old search snippets or forecast periods '
    'as observations. If retrieval is unavailable, state that once without an offer to search again.\n')
_STATES = set('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP'.split())
_HEADERS = {'User-Agent': 'SolutionistChiefWeather/1.0 (https://solutionist.app)', 'Accept': 'application/geo+json'}
MAX_OBSERVATION_AGE = 90 * 60  # Hourly reports plus NWS's documented QC delay.
MAX_FORECAST_AGE = 18 * 60 * 60


def weather_turn(messages):
    """Only plain owner weather requests/retries; tool results cannot turn on routing."""
    user = [m.get('content') for m in messages if m.get('role') == 'user' and isinstance(m.get('content'), str)]
    if not user:
        return False
    text = user[-1].strip()
    if re.fullmatch(r'(?:yes|yes please|try again|please try again|check again)[.!? ]*', text, re.I):
        text = user[-2] if len(user) > 1 else ''
    return bool(re.search(r'\b(?:weather|forecast|temperature)\b', text, re.I)
                and re.search(r'\b(?:what|how|check|look|weather|forecast)\b', text, re.I))


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def _fresh(value, now, age):
    stamp = _time(value)
    return bool(stamp and 0 <= (now - stamp).total_seconds() <= age)


def supports_claim(data, claim, quote):
    """A forecast-only receipt cannot prove observed/current conditions."""
    if not isinstance(data, dict) or data.get('type') != 'get_weather':
        return False
    now = datetime.now(timezone.utc)
    predicted = bool(re.search(r'\b(?:forecast|predicted|prediction|expected|will|should|tomorrow|tonight)\b', claim, re.I))
    if re.search(r'\b(?:right now|currently|current conditions)\b', claim, re.I):
        predicted = False
    if not predicted:
        current = data.get('current')
        valid = bool(isinstance(current, dict) and _fresh(current.get('observed_at'), now, MAX_OBSERVATION_AGE)
                     and (current.get('conditions') or _number(current.get('temperature_f'))))
        evidence = {'current': current}
    else:
        item = data.get('forecast')
        if not isinstance(item, dict) or not _fresh(item.get('updated_at'), now, MAX_FORECAST_AGE):
            return False
        valid = any(isinstance(p, dict) and _time(p.get('startTime')) and _time(p.get('endTime'))
                    and _time(p['endTime']) > max(now, _time(p['startTime'])) for p in item.get('periods', []))
        evidence = {'forecast': item}
    # Semantic entailment remains the reviewer's job, but it cannot cite a
    # forecast to establish an observation (or vice versa).
    import chief_truth
    import json
    return valid and chief_truth._quote_in_source(quote, {'text': json.dumps(evidence)})


def _api_url(url, pattern):
    parsed = urlsplit(str(url or ''))
    if (parsed.scheme != 'https' or parsed.netloc != 'api.weather.gov' or parsed.query
            or parsed.fragment or not re.fullmatch(pattern, parsed.path)):
        raise ValueError('Invalid NWS endpoint')
    return str(url)


async def _json(client, url, pattern):
    response = await client.get(_api_url(url, pattern), headers=_HEADERS, timeout=5, follow_redirects=False)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError('Invalid NWS response')
    return data


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _quantity(props, key, unit):
    item = props.get(key) or {}
    value = item.get('value')
    return value if item.get('unitCode') == unit and _number(value) else None


def observation(data, now, source, station):
    p = data.get('properties') or {}
    if not _fresh(p.get('timestamp'), now, MAX_OBSERVATION_AGE):
        return None
    temp = _quantity(p, 'temperature', 'wmoUnit:degC')
    condition = str(p.get('textDescription') or '')[:160]
    if temp is None and not condition:
        return None
    wind = _quantity(p, 'windSpeed', 'wmoUnit:km_h-1')
    return {'observed_at': p['timestamp'], 'source_url': source, 'station': station,
            'conditions': condition or None, 'temperature_f': round(temp * 9 / 5 + 32, 1) if temp is not None else None,
            'wind_mph': round(wind / 1.609344, 1) if wind is not None else None}


def forecast(data, now, source):
    p = data.get('properties') or {}
    updated = p.get('updateTime')
    if not _fresh(updated, now, MAX_FORECAST_AGE):
        return None
    periods = []
    for row in (p.get('periods') or [])[:14]:
        start, end = _time(row.get('startTime')), _time(row.get('endTime'))
        if not start or not end or end <= now or end <= start or (start - now).total_seconds() > 7 * 86400:
            continue
        periods.append({k: row.get(k) for k in (
            'name', 'startTime', 'endTime', 'temperature', 'temperatureUnit', 'windSpeed', 'windDirection', 'shortForecast')})
        if len(periods) == 4:
            break
    return {'updated_at': updated, 'source_url': source, 'periods': periods} if periods else None


async def lookup(client, location):
    """At most six requests, 12 seconds overall; one failed branch keeps the other."""
    location = str(location or '').strip()
    match = re.fullmatch(r"([A-Za-z .'-]{2,70}),\s*([A-Za-z]{2})", location)
    if not (re.fullmatch(r'\d{5}', location) or (match and match[2].upper() in _STATES)):
        return {'type': 'get_weather', 'status': 'needs_location', 'result': 'Which U.S. city and state should I check?', 'label': 'Weather location needed'}
    result = {'type': 'get_weather', 'label': 'National Weather Service', 'location_requested': location,
              'status': 'unavailable', 'current': None, 'forecast': None,
              'result': 'The National Weather Service reading is unavailable. I cannot verify current conditions.'}
    try:
        async with asyncio.timeout(12):
            response = await client.get('https://forecast.weather.gov/zipcity.php', params={'inputstring': location},
                                        headers=_HEADERS, timeout=5, follow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308):
                response.raise_for_status()
                return {**result, 'status': 'needs_location', 'result': 'That location did not resolve uniquely. Which city and state should I check?'}
            target = urlsplit(urljoin(str(response.url), response.headers.get('location', '')))
            if target.scheme != 'https' or target.netloc != 'forecast.weather.gov' or target.path != '/MapClick.php':
                raise ValueError('Invalid location redirect')
            query = parse_qs(target.query)
            lat = float((query.get('lat') or query.get('textField1') or [''])[0])
            lon = float((query.get('lon') or query.get('textField2') or [''])[0])
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError('Invalid coordinates')
            # The official resolver, not the model, supplies the place and coordinates.
            city, state = query.get('CityName', [''])[0], query.get('state', [''])[0]
            if match and (not city or city.casefold() != match[1].strip().casefold() or state.upper() != match[2].upper()):
                return {**result, 'status': 'needs_location', 'result': 'The weather location did not match. Please specify the city and state.'}
            point = await _json(client, f'https://api.weather.gov/points/{lat:.4f},{lon:.4f}', r'/points/-?[\d.]+,-?[\d.]+')
            props = point.get('properties') or {}
            relative = (props.get('relativeLocation') or {}).get('properties') or {}
            result['location'] = f'{city}, {state}' if city and state else f"{relative.get('city', '')}, {relative.get('state', '')}"
            result['timezone'] = props.get('timeZone')
            forecast_url, stations_url = props.get('forecast'), props.get('observationStations')

            async def read_current():
                stations = await _json(client, stations_url, r'/gridpoints/[A-Z]{3}/\d+,\d+/stations')
                candidates = (stations.get('features') or [])[:2]
                async def read_station(row):
                    source = _api_url(row.get('id'), r'/stations/[A-Za-z0-9_-]+') + '/observations/latest'
                    data = await _json(client, source, r'/stations/[A-Za-z0-9_-]+/observations/latest')
                    return observation(data, datetime.now(timezone.utc), source, (row.get('properties') or {}).get('name'))
                values = await asyncio.gather(*(read_station(r) for r in candidates), return_exceptions=True)
                valid = [r for r in values if isinstance(r, dict)]
                return max(valid, key=lambda r: _time(r['observed_at'])) if valid else None

            async def read_forecast():
                data = await _json(client, forecast_url, r'/gridpoints/[A-Z]{3}/\d+,\d+/forecast')
                return forecast(data, datetime.now(timezone.utc), forecast_url)

            current, predicted = await asyncio.gather(read_current(), read_forecast(), return_exceptions=True)
            result['current'] = current if isinstance(current, dict) else None
            result['forecast'] = predicted if isinstance(predicted, dict) else None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError):
        pass
    result['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    if result['current']:
        current = result['current']
        try:
            local = _time(current['observed_at']).astimezone(ZoneInfo(result.get('timezone') or 'UTC'))
        except (ZoneInfoNotFoundError, ValueError):
            local = _time(current['observed_at'])
        # Exact, server-derived speech forms keep time-zone conversion/rounding
        # verifiable by the ordinary numerical guard; the model need not invent them.
        current['observed_local'] = local.strftime('%I:%M %p %Z on %B ') + f'{local.day}, {local.year}'
        pieces = [current['conditions']] if current['conditions'] else []
        for field, suffix in [('temperature_f', 'degrees Fahrenheit'), ('wind_mph', 'mph wind')]:
            if current[field] is not None:
                current[field + '_rounded'] = round(current[field])
                pieces.append(f'{round(current[field])} {suffix}')
        current['summary'] = (f"{result['location']}: {', '.join(pieces)}. "
                              f"Observed at {current['observed_local']} at {current['station']}.")
    if result['current'] or result['forecast']:
        result['status'] = 'available' if result['current'] else 'forecast_only'
        result['result'] = ('A timestamped NWS observation and/or forecast was retrieved. '
                            'Use only non-null fields. Lead with the observation and its local time in 1-3 sentences. '
                            'Use the supplied rounded values when rounding. Add a multi-day forecast only if asked; '
                            'forecast periods are predictions, not current conditions.')
    return result


async def handle_get_weather(client, biz, action):
    # A dedicated client never forwards the authenticated business client's headers.
    async with httpx.AsyncClient() as public:
        return await lookup(public, action.get('location'))
