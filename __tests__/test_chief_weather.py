import asyncio
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import httpx
import pytest

import chief_weather as weather


NOW = datetime.now(timezone.utc)
STAMP = (NOW - timedelta(minutes=20)).isoformat()
FORECAST = 'https://api.weather.gov/gridpoints/GRR/20,58/forecast'
STATIONS = 'https://api.weather.gov/gridpoints/GRR/20,58/stations'
OBS = {'properties': {'timestamp': STAMP, 'textDescription': 'Light Rain',
    'temperature': {'value': 10, 'unitCode': 'wmoUnit:degC'},
    'windSpeed': {'value': 16.09344, 'unitCode': 'wmoUnit:km_h-1'}}}
PREDICTION = {'properties': {'updateTime': STAMP, 'periods': [{
    'name': 'Tonight', 'startTime': (NOW + timedelta(hours=1)).isoformat(),
    'endTime': (NOW + timedelta(hours=9)).isoformat(), 'temperature': 45,
    'temperatureUnit': 'F', 'shortForecast': 'Rain Likely'}]}}


def client_with(*, obs=None, redirect=None, forecast=None, station_failure=False):
    calls = []
    def serve(request):
        calls.append(request)
        assert request.headers['user-agent'].startswith('SolutionistChiefWeather/')
        assert 'authorization' not in request.headers
        if request.url.path == '/zipcity.php':
            return httpx.Response(302, headers={'location': redirect or
                '//forecast.weather.gov/MapClick.php?CityName=Muskegon&state=MI&textField1=43.2276&textField2=-86.2555'})
        if request.url.path.startswith('/points/'):
            return httpx.Response(200, json={'properties': {'forecast': FORECAST, 'observationStations': STATIONS,
                'timeZone': 'America/Detroit'}})
        if str(request.url) == FORECAST:
            return httpx.Response(200, json=forecast if forecast is not None else PREDICTION)
        if str(request.url) == STATIONS:
            return httpx.Response(200, json={'features': [{'id': 'https://api.weather.gov/stations/KMKG',
                'properties': {'name': 'Muskegon County Airport'}}]})
        if request.url.path.endswith('/observations/latest'):
            return httpx.Response(503 if station_failure else 200, json=obs if obs is not None else OBS)
        raise AssertionError(str(request.url))
    return httpx.AsyncClient(transport=httpx.MockTransport(serve)), calls


def run_lookup(**kwargs):
    client, calls = client_with(**kwargs)
    async def run():
        async with client:
            return await weather.lookup(client, 'Muskegon, MI')
    return asyncio.run(run()), calls


def test_fresh_observation_and_forecast_remain_separate_timestamped_evidence():
    out, calls = run_lookup()
    assert out['status'] == 'available'
    assert out['current']['temperature_f'] == 50
    assert out['current']['wind_mph'] == 10
    assert out['current']['observed_at'] == STAMP
    assert out['forecast']['periods'][0]['name'] == 'Tonight'
    assert out['forecast']['updated_at'] == STAMP
    assert out['retrieved_at'] and len(calls) == 5
    assert out['location'] == 'Muskegon, MI'
    assert 'observed_local' in out['current'] and 'summary' in out['current']


@pytest.mark.parametrize('stamp', [
    (NOW - timedelta(days=1)).isoformat(), (NOW + timedelta(minutes=1)).isoformat(),
    NOW.replace(tzinfo=None).isoformat(), 'invalid', None,
])
def test_old_future_or_unverifiable_observations_never_become_current(stamp):
    out, _ = run_lookup(obs={'properties': {**OBS['properties'], 'timestamp': stamp}})
    assert out['status'] == 'forecast_only' and out['current'] is None
    assert out['forecast']


def test_current_read_failure_preserves_valid_forecast():
    out, _ = run_lookup(station_failure=True)
    assert out['status'] == 'forecast_only' and out['current'] is None


@pytest.mark.parametrize('updated', [NOW - timedelta(days=1), NOW + timedelta(hours=1)])
def test_stale_or_future_forecast_issue_is_not_used(updated):
    data = {'properties': {**PREDICTION['properties'], 'updateTime': updated.isoformat()}}
    out, _ = run_lookup(forecast=data)
    assert out['forecast'] is None and out['current']


def test_expired_forecast_period_not_used_even_with_fresh_issue():
    data = {'properties': {'updateTime': STAMP, 'periods': [{
        'startTime': (NOW-timedelta(days=1)).isoformat(), 'endTime': STAMP}]}}
    assert weather.forecast(data, NOW, FORECAST) is None


@pytest.mark.parametrize('location', ['Springfield', 'Paris, France', '123 Main St, MI', '', 'Muskegon, ZZ'])
def test_ambiguous_or_private_location_is_not_sent(location):
    client = AsyncMock()
    out = asyncio.run(weather.lookup(client, location))
    assert out['status'] == 'needs_location'
    client.get.assert_not_called()


@pytest.mark.parametrize('target', [
    'https://attacker.test/MapClick.php?lat=43&lon=-86',
    'https://forecast.weather.gov.evil.test/MapClick.php?lat=43&lon=-86',
    'http://forecast.weather.gov/MapClick.php?lat=43&lon=-86',
    'https://forecast.weather.gov/other?lat=43&lon=-86',
    '//forecast.weather.gov/MapClick.php?lat=nan&lon=-86',
])
def test_bad_resolver_redirect_never_followed(target):
    out, calls = run_lookup(redirect=target)
    assert out['status'] == 'unavailable' and len(calls) == 1


def test_wrong_resolved_city_asks_instead_of_silently_using_it():
    out, calls = run_lookup(redirect='//forecast.weather.gov/MapClick.php?CityName=Detroit&state=MI&lat=42&lon=-83')
    assert out['status'] == 'needs_location' and len(calls) == 1


@pytest.mark.parametrize('url', ['http://api.weather.gov/stations/KMKG',
    'https://api.weather.gov@attacker.test/stations/KMKG',
    'https://api.weather.gov/stations/KMKG?url=http://127.0.0.1',
    'https://api.weather.gov/other'])
def test_api_links_are_pinned_to_known_host_and_path(url):
    with pytest.raises(ValueError):
        weather._api_url(url, r'/stations/[A-Za-z0-9_-]+')


def test_yes_uses_latest_owner_weather_request_but_not_assistant_invention():
    assert weather.weather_turn([{'role': 'user', 'content': 'What is the weather in Muskegon like?'},
        {'role': 'assistant', 'content': 'Try again?'}, {'role': 'user', 'content': 'yes'}])
    assert not weather.weather_turn([{'role': 'assistant', 'content': 'Check the weather?'}, {'role': 'user', 'content': 'yes'}])
    assert not weather.weather_turn([{'role': 'user', 'content': 'weather in Muskegon?'},
        {'role': 'user', 'content': 'Show invoices'}, {'role': 'user', 'content': 'yes'}])


def test_native_weather_read_records_evidence_and_reuses_identical_result(monkeypatch):
    import chief_of_staff as chief
    import chief_tool_loop as loop
    import chief_truth as truth
    out, _ = run_lookup()
    handler = AsyncMock(return_value=out)
    monkeypatch.setitem(chief.ACTION_HANDLERS, 'get_weather', handler)
    token = truth.begin('fixture-owner', 'Weather in Muskegon, MI?')
    try:
        async def run():
            loop.reset_turn()
            for _ in range(2):
                error, value = await loop.execute_tool_use(None, {'id': 'fixture'}, 'get_weather', {'location': 'Muskegon, MI'})
                assert not error and 'observed_at' in value
            sources = truth.evidence_for_review({}, '', [])
            sid = 'tool:get_weather'
            claim = 'It is rainy right now.'
            raw = json.dumps({'verdict': 'supported', 'claims': [{'text': claim, 'kind': 'fact',
                'source_id': sid, 'quote': 'Light Rain'}]})
            assert truth.assess_review(raw, claim, sources)[0] == 'supported'
        asyncio.run(run())
        assert handler.await_count == 1
    finally:
        truth.end(token)


def test_server_conversions_supply_exact_citable_speech_numbers():
    import chief_truth as truth
    out, _ = run_lookup()
    cur = out['current']
    claim = f"It is {cur['temperature_f_rounded']} degrees Fahrenheit, with {cur['wind_mph_rounded']} mph wind."
    sid = 'tool:get_weather'
    raw = json.dumps({'verdict': 'supported', 'claims': [{'text': claim, 'kind': 'fact',
        'source_id': sid, 'quote': cur['summary']}]})
    sources = {sid: {'kind': 'record', 'text': json.dumps(out)}}
    assert truth.assess_review(raw, claim, sources)[0] == 'supported'


def test_forecast_only_cannot_prove_current_conditions_even_if_reviewer_says_supported():
    import chief_truth as truth
    out, _ = run_lookup(station_failure=True)
    sid = 'tool:get_weather'
    sources = {sid: {'kind': 'record', 'text': json.dumps(out)}}
    for claim, verdict in [('It is rainy right now.', 'unsupported'), ('It will be rainy tonight.', 'supported')]:
        raw = json.dumps({'verdict': 'supported', 'claims': [{'text': claim, 'kind': 'fact',
            'source_id': sid, 'quote': 'Rain Likely'}]})
        assert truth.assess_review(raw, claim, sources)[0] == verdict


def test_forecast_quote_cannot_replace_a_different_valid_observation():
    import chief_truth as truth
    out, _ = run_lookup(obs={'properties': {**OBS['properties'], 'textDescription': 'Clear'}})
    sid = 'tool:get_weather'
    claim = 'It is rainy right now.'
    raw = json.dumps({'verdict': 'supported', 'claims': [{'text': claim, 'kind': 'fact',
        'source_id': sid, 'quote': 'Rain Likely'}]})
    assert truth.assess_review(raw, claim, {sid: {'kind': 'record', 'text': json.dumps(out)}})[0] == 'unsupported'


@pytest.mark.parametrize('heading', ["Here's the current weather in Muskegon.", 'Here is the weather for New York.',
    "Here's the current weather."])
def test_weather_topic_heading_does_not_claim_a_condition(heading):
    import chief_truth as truth
    assert not truth._weather_assertions(heading)
    assert truth._weather_assertions(heading + ' It is rainy right now.') == ['It is rainy right now.']


def test_heading_cannot_hide_conditions():
    import chief_truth as truth
    assert truth._weather_assertions("Here's the current weather in Muskegon is rainy.")
    assert truth._weather_assertions("Here's the current weather: it is rainy right now.")


def test_forecast_only_cannot_escape_through_early_speech(monkeypatch):
    import chief_truth as truth
    out, _ = run_lookup(station_failure=True)
    sid = 'tool:get_weather'
    monkeypatch.setattr(truth, 'review_reply', AsyncMock(return_value=json.dumps(
        {'supported': True, 'source_id': sid, 'quote': 'Rain Likely'})))
    assert not asyncio.run(truth.review_stream_prefix(None, 'It is rainy right now.',
        sources={sid: {'kind': 'record', 'text': json.dumps(out)}},
        message='Weather in Muskegon?', business_id=None))
