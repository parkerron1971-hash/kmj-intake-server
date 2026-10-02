"""Current weather cannot be proved by repeating the owner's location question."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import chief_truth as truth

QUESTION = 'Can you check the weather in Muskegon, Michigan?'
WEATHER = 'Muskegon is rainy right now.'


def review(sid, quote, *, text=WEATHER, verdict='unsupported', kind='fact'):
    return json.dumps({'verdict': verdict, 'claims': [
        {'text': text, 'kind': kind, 'source_id': sid, 'quote': quote}]})


@pytest.mark.parametrize('sid,kind,quote', [
    ('conversation:current', 'conversation', QUESTION),
    ('owner:message', 'owner_report', QUESTION),
    ('conversation:history:0', 'conversation', WEATHER),
    ('context:business_identity', 'context', 'Muskegon, Michigan'),
    ('context:memories', 'context', WEATHER),
    ('system:weather', 'capability', 'Chief can search current weather.'),
    ('tool:recall_notes', 'record', WEATHER),
    ('tool:revenue_forecast', 'record', WEATHER),
    ('tool:weather', 'conversation', WEATHER),
])
def test_location_questions_and_saved_prose_are_not_current_weather_evidence(sid, kind, quote):
    sources = {sid: {'kind': kind, 'text': quote}}
    verdict, _, reason = truth.assess_review(review(sid, quote), WEATHER, sources)
    assert verdict == 'unsupported' and reason == 'current weather lacks retrieved evidence'


@pytest.mark.parametrize('sid,kind', [
    ('web:https://weather.example/current', 'research'),
    ('tool:get_current_weather', 'record'),
    ('lookup:/weather/current', 'record'),
    ('read:weather', 'record'),
])
def test_actual_retrieved_weather_still_passes(sid, kind):
    sources = {sid: {'kind': kind, 'text': WEATHER}}
    assert truth.assess_review(review(sid, WEATHER, verdict='supported'), WEATHER, sources)[:2] == (
        'supported', [sid])


def test_provider_citation_recorded_during_the_turn_is_valid_weather_evidence():
    token = truth.begin('owner', QUESTION)
    try:
        truth.record_web_citations([{'citations': [
            {'url': 'https://weather.example/current', 'cited_text': WEATHER}]}])
        sources = truth.evidence_for_review({}, '', [])
    finally:
        truth.end(token)
    sid = 'web:https://weather.example/current'
    assert truth.assess_review(review(sid, WEATHER, verdict='supported'), WEATHER, sources)[0] == 'supported'


@pytest.mark.parametrize('raw', [
    json.dumps({'verdict': 'supported', 'claims': []}),
    review('', '', kind='reference'),
    review('conversation:current', QUESTION, text='Muskegon'),
])
def test_omitted_partial_or_reference_claim_cannot_bypass_weather_proof(raw):
    assert truth.assess_review(raw, WEATHER, {
        'conversation:current': {'kind': 'conversation', 'text': QUESTION}})[0] == 'unsupported'


def test_failed_weather_read_is_not_proof():
    sid = 'tool:weather'
    assert truth.assess_review(review(sid, WEATHER), WEATHER,
        {sid: {'kind': 'record', 'text': WEATHER, 'failed': True}})[0] == 'unsupported'


@pytest.mark.parametrize('raw', ['', 'not json', json.dumps({'verdict': 'supported', 'claims': []}),
    review('conversation:current', QUESTION)])
def test_final_reply_never_delivers_weather_when_verification_fails(raw):
    out, meta = asyncio.run(truth.finalize_reply(None, WEATHER, ctx={}, view_detail='',
        taken=[], message=QUESTION, business_id='fixture', reviewer=AsyncMock(return_value=raw)))
    assert WEATHER not in out and meta['status'] == 'withheld'


def test_generic_numeric_trim_cannot_clear_an_unretrieved_weather_claim():
    draft = WEATHER + ' The temperature is 61 degrees. Winds are 12 mph.'
    raw = json.dumps({'verdict': 'unsupported', 'claims': [
        {'text': WEATHER, 'kind': 'fact', 'source_id': 'conversation:current', 'quote': QUESTION},
        {'text': 'The temperature is 61 degrees.', 'kind': 'fact', 'source_id': '', 'quote': '', 'gap': 'No reading'},
        {'text': 'Winds are 12 mph.', 'kind': 'fact', 'source_id': '', 'quote': '', 'gap': 'No reading'}]})
    out, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail='', taken=[],
        message=QUESTION, business_id='fixture', reviewer=AsyncMock(return_value=raw)))
    assert WEATHER not in out and meta['status'] == 'withheld'


def test_weather_cannot_escape_through_gap_cleanup():
    draft = WEATHER + ' Demand is guaranteed.'
    raw = json.dumps({'verdict': 'unsupported', 'claims': [
        {'text': WEATHER, 'kind': 'fact', 'source_id': 'conversation:current', 'quote': QUESTION},
        {'text': 'Demand is guaranteed.', 'kind': 'fact', 'source_id': '', 'quote': '', 'gap': 'No evidence'}]})
    out, meta = truth._clean_review_gaps(raw, draft,
        {'conversation:current': {'kind': 'conversation', 'text': QUESTION}}, ['Demand is guaranteed.'], [])
    assert WEATHER not in out and meta['status'] == 'withheld'


@pytest.mark.parametrize('draft', [WEATHER, "It's rainy.", "It's sunny today."])
def test_deterministic_early_speech_never_guesses_weather(draft):
    assert truth.fast_lane(draft, {}) is None
    assert not truth.streamable_sentence(truth.stream_prover({}), draft)


@pytest.mark.parametrize('sentence', [
    "I haven't checked whether it is rainy.",
    "I couldn't verify the current weather.",
    'If it is rainy, consider moving the event inside.',
    'Is it rainy in Muskegon?',
    "You said it is rainy outside.",
    'The angle is ninety degrees.',
    'The revenue forecast is ambitious.',
    'You said it was rainy.',
    'If it rains, move indoors.',
    'I cannot verify current weather.',
])
def test_questions_uncertainty_reported_weather_and_unrelated_topics_stay_out_of_guard(sentence):
    assert not truth._weather_assertions(sentence)


def test_uncertainty_preface_does_not_excuse_assertion_after_but():
    draft = "I haven't checked the weather, but Muskegon is rainy right now."
    assert truth._weather_provenance_missing(draft, [], {})


def test_provider_review_without_citation_cannot_release_lowercase_weather(monkeypatch):
    monkeypatch.setattr(truth, 'review_reply', AsyncMock(return_value=json.dumps(
        {'supported': True, 'source_id': '', 'quote': ''})))
    assert not asyncio.run(truth.review_stream_prefix(None, "It's rainy.", sources={},
        message=QUESTION, business_id='fixture'))
