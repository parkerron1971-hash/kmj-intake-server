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
