"""Connected speech: verification overlaps, but speech stays an ordered proof."""
import asyncio
import json

import pytest

import chief_of_staff as chief
import chief_truth as truth


def test_second_check_runs_while_first_pending_but_cannot_overtake():
    async def run():
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        prefixes, out = [], []
        async def review(prefix):
            index = len(prefixes)
            prefixes.append(prefix)
            entered[index].set()
            await release[index].wait()
            return True
        s = chief._SentenceStreamer(out.append, truth.stream_prover({}), review=review)
        s('Your busiest day is Tuesday. Your quietest day is Monday. ')
        await asyncio.wait_for(entered[1].wait(), .2)
        assert prefixes[1].startswith(prefixes[0])
        release[1].set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert out == []
        release[0].set()
        await asyncio.gather(*tuple(s._review_tasks))
        assert s.text == 'Your busiest day is Tuesday. Your quietest day is Monday. '
        assert out == [chief.PROSE_PREFIX + 'Your busiest day is Tuesday. ',
                       chief.PROSE_PREFIX + 'Your quietest day is Monday. ']
        s.close()
    asyncio.run(run())


def test_first_rejection_holds_an_already_approved_second_sentence():
    async def run():
        calls = []
        release = asyncio.Event()
        async def review(prefix):
            calls.append(prefix)
            if len(calls) == 1:
                await release.wait()
                return False
            return True
        out = []
        s = chief._SentenceStreamer(out.append, truth.stream_prover({}), review=review)
        s('Your busiest day is Tuesday. Your quietest day is Monday. ')
        for _ in range(8):
            await asyncio.sleep(0)
        assert len(calls) == 2 and out == []
        release.set()
        await asyncio.gather(*tuple(s._review_tasks), return_exceptions=True)
        assert not s.open and not s.text and out == []
    asyncio.run(run())


@pytest.mark.parametrize('chunks', [
    ['Keep the next step simple. [ACTION:{"type":"send_sms"}]I sent it. '],
    ['Keep the next step simple. [AC', 'TION:{"type":"send_sms"}]I sent it. '],
    ['Keep the next step simple. ', '[ACTION:{"type":"send_sms"}]I sent it. '],
])
def test_action_chunk_boundaries_do_not_erase_preceding_checked_sentence(chunks):
    out = []
    s = chief._SentenceStreamer(out.append, truth.stream_prover({}))
    for chunk in chunks:
        s(chunk)
    assert out == [chief.PROSE_PREFIX + 'Keep the next step simple. ']
    assert not s.open and s.text == 'Keep the next step simple. '


def test_early_review_omits_large_unrelated_context_but_validates_original_quote(monkeypatch):
    sources = {
        'context:summary': {'kind': 'context', 'complete': True,
                            'text': 'Your busiest day is Tuesday.'},
        'context:brand_block': {'kind': 'context', 'complete': False,
                               'text': 'Color palette and typography. ' * 1500},
    }
    seen = []
    async def review(client, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'])
        seen.append(payload)
        assert list(payload['sources']) == ['context:summary']
        assert payload['omitted_sources'] == ['context:brand_block']
        return json.dumps({'supported': True, 'source_id': 'context:summary',
                           'quote': 'Your busiest day is Tuesday.'})
    monkeypatch.setattr(truth, 'review_reply', review)
    assert asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))
    assert len(json.dumps(seen[0])) < 1000
    assert len(sources['context:brand_block']['text']) > 14000


def test_early_review_keeps_contradictions_and_cannot_cite_an_omitted_source(monkeypatch):
    sources = {
        'context:summary': {'kind': 'context', 'complete': True,
                            'text': 'Your busiest day is Tuesday.'},
        'context:corrected_summary': {'kind': 'context', 'complete': True,
                                      'text': 'Your busiest day is Friday.'},
        'context:brand_block': {'kind': 'context', 'complete': False,
                               'text': 'Color palette. ' * 1500},
    }
    async def review(client, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'])
        assert 'context:corrected_summary' in payload['sources']
        return json.dumps({'supported': True, 'source_id': 'context:brand_block',
                           'quote': 'Color palette.'})
    monkeypatch.setattr(truth, 'review_reply', review)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))


def test_large_relevant_record_is_never_truncated_or_falsely_marked_complete(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('oversized evidence must defer to the final review')
    monkeypatch.setattr(truth, 'review_reply', forbidden)
    sources = {'context:summary': {'kind': 'context', 'complete': True,
                                   'text': 'Tuesday bookings. ' * 1200}}
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))


def _noisy_sources():
    return {
        'context:summary': {'kind': 'context', 'complete': True,
                            'text': 'Your busiest day is Tuesday.'},
        'context:context_quality': {'kind': 'context', 'complete': True,
                                    'text': 'Some secondary context is unavailable.'},
        **{f'context:design_note_{i}': {'kind': 'context', 'complete': False,
            'text': 'Unrelated historical draft color palette. ' + ('x' * 1600)}
           for i in range(10)},
    }


def test_unrelated_historical_drafts_do_not_disable_a_checked_prefix(monkeypatch):
    sources = _noisy_sources()
    seen = []
    async def reviewer(client, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'])
        seen.append(payload)
        assert set(payload['sources']) == {'context:summary', 'context:context_quality'}
        assert len(payload['omitted_sources']) == 10
        return json.dumps({'supported': True, 'source_id': 'context:summary',
                           'quote': 'Your busiest day is Tuesday.'})
    monkeypatch.setattr(truth, 'review_reply', reviewer)

    async def run():
        out = []
        async def check(prefix):
            return await truth.review_stream_prefix(None, prefix, sources=sources,
                message='Which day is busiest?', business_id=None)
        streamer = chief._SentenceStreamer(out.append, truth.stream_prover(sources), review=check)
        streamer('Your busiest day is Tuesday. ')
        await streamer.wait_closed()
        # No final draft or full-review response has been supplied yet.
        assert out == [chief.PROSE_PREFIX + 'Your busiest day is Tuesday. ']
        assert streamer.open
        streamer.close()
    asyncio.run(run())
    assert len(seen) == 1


@pytest.mark.parametrize('qualifier', ['historical', 'draft', 'failed', 'unverified'])
def test_relevant_hedged_conflicts_stay_in_early_review(monkeypatch, qualifier):
    sources = _noisy_sources()
    sources['context:corrected_summary'] = {'kind': 'context', 'complete': False,
        'text': f'{qualifier}: Your busiest day is Friday, not Tuesday.'}
    async def reviewer(client, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'])
        assert payload['sources']['context:corrected_summary'] == sources['context:corrected_summary']
        return json.dumps({'supported': False, 'source_id': '', 'quote': ''})
    monkeypatch.setattr(truth, 'review_reply', reviewer)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))


def test_global_context_quality_cannot_be_dropped_to_make_the_check_fit(monkeypatch):
    sources = _noisy_sources()
    sources['context:context_quality']['text'] = 'Unavailable context. ' * 1000
    async def forbidden(*args, **kwargs):
        raise AssertionError('oversized global availability must defer the check')
    monkeypatch.setattr(truth, 'review_reply', forbidden)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))


def test_global_invalidation_without_shared_subject_still_reaches_reviewer(monkeypatch):
    sources = _noisy_sources()
    warning = {'kind': 'context', 'complete': True,
               'text': 'All fetched summaries are stale; current database is unavailable.'}
    sources['context:sync_status'] = warning
    async def reviewer(client, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'])
        assert payload['sources']['context:sync_status'] == warning
        return json.dumps({'supported': False, 'source_id': '', 'quote': ''})
    monkeypatch.setattr(truth, 'review_reply', reviewer)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))


def test_global_invalidation_cannot_be_omitted_to_fit_the_budget(monkeypatch):
    sources = _noisy_sources()
    sources['context:sync_status'] = {'kind': 'context', 'complete': True,
        'text': 'All fetched summaries are stale. ' * 1000}
    async def forbidden(*args, **kwargs):
        raise AssertionError('uncertain global invalidation must defer early speech')
    monkeypatch.setattr(truth, 'review_reply', forbidden)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources=sources, message='Which day is busiest?', business_id=None))


def test_uncited_personal_forecast_still_waits_for_final_review(monkeypatch):
    # This persisted opening from the latency report is a separate gate:
    # omitting irrelevant drafts must not turn a forecast into proved fact.
    sentence = "Realistically, the first thing you'd see is proof, not revenue."
    assert not truth.streamable_sentence(truth.stream_prover({}), sentence)
    calls = []
    async def reviewer(*args, **kwargs):
        calls.append(True)
        return json.dumps({'supported': True, 'source_id': '', 'quote': ''})
    monkeypatch.setattr(truth, 'review_reply', reviewer)
    assert not asyncio.run(truth.review_stream_prefix(None, sentence,
        sources=_noisy_sources(), message='What results would this plan produce?', business_id=None))
    assert calls == [True]


def test_prefix_budget_diagnostic_is_content_free_and_scoped(caplog):
    import chief_request_timing
    import time
    token = chief_request_timing.CURRENT.set(chief_request_timing.Trace(time.perf_counter(), 'prefix-test'))
    sources = {'context:summary': {'kind': 'context', 'complete': True,
                                   'text': 'Tuesday PRIVATE CONTENT ' * 1000}}
    try:
        with caplog.at_level('INFO', logger=truth.logger.name):
            assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
                sources=sources, message='Which day is busiest?', business_id=None))
    finally:
        chief_request_timing.CURRENT.reset(token)
    assert '"request_id":"prefix-test"' in caplog.text
    assert '"reason":"evidence_budget"' in caplog.text
    assert 'PRIVATE CONTENT' not in caplog.text and 'Your busiest day' not in caplog.text


@pytest.mark.parametrize('sentence', [
    'The message is on its way. ', 'The text is on the way. ', 'It is on its way. ',
    'That is taken care of. ', 'It is handled. ', 'The booking went through. ',
    'The update went through. ', 'The payment has gone through. ',
    'The emails are on their way. ', 'The bookings have gone through. ',
])
def test_delivery_idioms_require_receipts_and_never_enter_early_review(monkeypatch, sentence):
    assert truth.has_completion_claim(sentence)
    assert not truth.streamable_sentence(truth.stream_prover({}), sentence)
    async def forbidden(*args, **kwargs):
        raise AssertionError('receipt-free completion must not call an early reviewer')
    monkeypatch.setattr(truth, 'review_reply', forbidden)
    assert not asyncio.run(truth.review_stream_prefix(None, sentence, sources={},
        message='Please send the message.', business_id=None))


@pytest.mark.parametrize('sentence', [
    "Let's keep the conversation moving. ", 'The plan is taking shape. ',
    'I would send a personal invitation. ', 'The message is not on its way. ',
])
def test_non_completion_language_is_not_caught_by_delivery_idioms(sentence):
    assert not truth._DELIVERY_COMPLETION.search(sentence)
