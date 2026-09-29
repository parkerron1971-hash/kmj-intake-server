"""Continuous response regressions: ordered output, bounded work, shared voice."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import chief_of_staff as chief
import chief_truth as truth
import chief_fast_track as fast
import chief_conversation
import chief_prompt
import model_router
import route_ledger


def test_blocked_sentence_resumes_in_order_before_generation_finishes():
    async def run():
        ready = asyncio.Event()
        requested = asyncio.Event()
        out, seen = [], []
        async def review(prefix):
            seen.append(prefix)
            requested.set()
            await ready.wait()
            return True
        s = chief._SentenceStreamer(out.append, truth.stream_prover({}), review=review)
        s("Your busiest day is Tuesday. ")
        await requested.wait()
        s("Let's keep this manageable. ")
        assert out == []
        ready.set()
        for _ in range(8):
            await asyncio.sleep(0)
        assert s.text == "Your busiest day is Tuesday. Let's keep this manageable. "
        assert seen == ["Your busiest day is Tuesday. "]
        assert s.open  # writer still running; no final payload required
        s.close()
        await s.wait_closed()
    asyncio.run(run())


@pytest.mark.parametrize('verdict', [False, 'error'])
def test_rejected_or_failed_check_never_skips_to_later_sentences(verdict):
    async def run():
        out = []
        async def review(prefix):
            if verdict == 'error':
                raise RuntimeError('unavailable')
            return verdict
        s = chief._SentenceStreamer(out.append, truth.stream_prover({}), review=review)
        s("Your busiest day is Tuesday. Anything else? ")
        for _ in range(8):
            await asyncio.sleep(0)
        assert out == [] and not s.open
        await s.wait_closed()
    asyncio.run(run())


def test_closing_cancels_the_check_and_cannot_emit_late():
    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def review(prefix):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        out = []
        s = chief._SentenceStreamer(out.append, truth.stream_prover({}), review=review)
        s("Your busiest day is Tuesday. ")
        await started.wait()
        s.close()
        await s.wait_closed()
        assert cancelled.is_set() and out == []
        s("This must not appear. ")
        assert out == []
    asyncio.run(run())


def test_extra_checks_are_bounded_and_keep_the_committed_prefix():
    async def run():
        calls = []
        async def review(prefix):
            calls.append(prefix)
            return True
        s = chief._SentenceStreamer(lambda _: None, truth.stream_prover({}), review=review)
        s("Your busiest day is Tuesday. Your quietest day is Monday. Your balance is missing. ")
        for _ in range(15):
            await asyncio.sleep(0)
        assert len(calls) == 2 and not s.open
        assert s.text == "Your busiest day is Tuesday. Your quietest day is Monday. "
        assert calls[1].startswith(calls[0])
        await s.wait_closed()
    asyncio.run(run())


def test_action_tag_cancels_pending_prose():
    async def run():
        out = []
        async def review(prefix):
            await asyncio.sleep(1)
            return True
        s = chief._SentenceStreamer(out.append, truth.stream_prover({}), review=review)
        s("Your busiest day is Tuesday. ")
        s('[ACTION:{"type":"send_sms"}]')
        await s.wait_closed()
        assert out == [] and not s.open
    asyncio.run(run())


@pytest.mark.parametrize('prefix', ["I've sent the invoice. ", "All done. ", '[ACTION:{}]', 'x' * 1801])
def test_completion_and_oversized_prefixes_never_call_an_early_reviewer(monkeypatch, prefix):
    async def forbidden(*a, **kw):
        raise AssertionError('must not call a reviewer')
    monkeypatch.setattr(truth, 'review_reply', forbidden)
    assert not asyncio.run(truth.review_stream_prefix(None, prefix, sources={}, message='send it', business_id='b'))


@pytest.mark.parametrize('raw', ['', 'garbage', '{"supported":true,"source_id":"","quote":""}'])
def test_empty_or_vacuous_review_cannot_release_a_business_assertion(monkeypatch, raw):
    async def review(*a, **kw):
        return raw
    monkeypatch.setattr(truth, 'review_reply', review)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Your busiest day is Tuesday.',
        sources={}, message='Which day is busiest?', business_id='b'))


def test_early_review_requires_real_citations_and_uses_metered_fast_lane(monkeypatch):
    sentence = 'Your busiest day is Tuesday.'
    sources = {'context:summary': {'kind': 'context', 'text': sentence, 'complete': True}}
    calls = []
    async def review(*a, **kw):
        calls.append(kw)
        return json.dumps({'supported': True, 'source_id': 'context:summary', 'quote': sentence})
    monkeypatch.setattr(truth, 'review_reply', review)
    assert asyncio.run(truth.review_stream_prefix(None, sentence, sources=sources,
        message='Which day is busiest?', business_id='b'))
    assert calls[0]['model_lane'] == 'fast' and calls[0]['business_id'] == 'b'
    sources['context:summary']['text'] = 'No supporting evidence.'
    assert not asyncio.run(truth.review_stream_prefix(None, sentence, sources=sources,
        message='Which day is busiest?', business_id='b'))


def test_personality_is_shared_and_preferences_are_isolated(monkeypatch):
    monkeypatch.setattr(fast, '_STYLES', {})
    biz = {'id': 'b', 'voice_profile': {'tone': 'brand playful', 'chief_tone': {'tone': 'calm and direct'}}}
    fast.remember_style('u', biz)
    assert fast.style_for('u', 'b') == chief_prompt._build_personality_block(biz, {})
    assert 'calm and direct' in fast.style_for('u', 'b')
    assert 'brand playful' not in fast.style_for('u', 'b')
    assert fast.style_for('other', 'b') == chief_conversation.conversation_style({})
    assert fast.style_for('u', 'different') == chief_conversation.conversation_style({})
    monkeypatch.setattr(fast.time, 'time', lambda: 10**12)
    assert fast.style_for('u', 'b') == chief_conversation.conversation_style({})


def test_a_purposeful_opening_can_finish_without_the_old_fourteen_word_cut():
    sentence = "I'll look at which invoices need attention first and help you decide where a reminder would be useful."
    gate = model_router.OpenerGate('Which invoices should I chase?')
    chunks = [gate.feed(ch) for ch in sentence]
    chunks.append(gate.finish())
    assert ''.join(chunks) == sentence
    assert gate.cut_reason == 'sentence_end'


def test_optional_enrichment_has_a_deadline_but_records_do_not(monkeypatch):
    async def run():
        monkeypatch.setattr(chief, 'OPTIONAL_CONTEXT_BUDGET_S', 0.001)
        async def slow():
            await asyncio.sleep(0.02)
            return 'loaded'
        token = truth.begin('u', 'hello')
        try:
            assert await chief._resolve_source({}, 'habit_block', slow, '') == ''
            assert 'context:habit_block' in truth.unavailable_sources()
            assert await chief._resolve_source({}, 'bookkeeping_block', slow, '') == 'loaded'
            assert await chief._resolve_source({'habit_block': 'warm'}, 'habit_block', slow, '') == 'warm'
        finally:
            truth.end(token)
    asyncio.run(run())


def test_content_clock_does_not_count_acknowledgments(monkeypatch):
    now = [1.0]
    monkeypatch.setattr(route_ledger.time, 'perf_counter', lambda: now[0])
    record = route_ledger.RouteRecord(arrived=1.0)
    now[0] = 1.4
    record.mark_first_token('local')
    assert record.flow_metrics()['first_content_ms'] is None
    now[0] = 2.5
    record.mark_content()
    assert record.flow_metrics()['first_content_ms'] == 1500
    now[0] = 4.0
    record.mark_content()
    assert record.flow_metrics()['max_content_gap_ms'] == 1500


def test_sse_delivers_resumed_prose_before_the_final_event(monkeypatch):
    async def run():
        finish_turn = asyncio.Event()
        async def approved(prefix):
            await asyncio.sleep(0)
            return True
        async def chat(req, session):
            s = chief._SentenceStreamer(chief._STREAM_SINK.get(), truth.stream_prover({}), review=approved)
            s('Your busiest day is Tuesday. ')
            await finish_turn.wait()
            s.close()
            await s.wait_closed()
            return {'response': s.text + 'Keep the next step simple.', 'actions_taken': []}
        monkeypatch.setattr(fast, 'plan', lambda *a: None)
        monkeypatch.setattr(chief, 'chief_chat', chat)
        response = await chief.chief_chat_stream(chief.ChatRequest(business_id='b', message='Busiest day?'), None)
        iterator = response.body_iterator
        assert (await anext(iterator)).startswith(':')
        early = json.loads((await asyncio.wait_for(anext(iterator), 1)).removeprefix('data: ').strip())
        assert early['type'] == 'delta' and early['checked']
        assert early['text'] == 'Your busiest day is Tuesday. '
        assert not finish_turn.is_set()
        finish_turn.set()
        rest = [json.loads(f.removeprefix('data: ').strip()) async for f in iterator if f.startswith('data:')]
        text = early['text'] + ''.join(e['text'] for e in rest if e['type'] == 'delta')
        assert rest[-1]['type'] == 'final' and text == rest[-1]['payload']['response']
    asyncio.run(run())


def test_a_complete_last_sentence_streams_before_final_review():
    out = []
    s = chief._SentenceStreamer(out.append, truth.stream_prover({}))
    s('Keep the next step simple.')
    assert out == []
    s.finish_input()
    assert s.text == 'Keep the next step simple. ' and s.open
    s.close()


@pytest.mark.parametrize('result', [
    {'supported': True, 'source_id': '', 'quote': ''},
    {'supported': True, 'source_id': 'missing', 'quote': 'Invoices are outstanding.'},
    {'supported': True, 'source_id': 's', 'quote': 'Invented quotation.'},
    {'supported': 'true', 'source_id': 's', 'quote': 'Invoices are outstanding.'},
])
def test_record_claims_need_a_real_citation(monkeypatch, result):
    async def review(*a, **kw):
        return json.dumps(result)
    monkeypatch.setattr(truth, 'review_reply', review)
    assert not asyncio.run(truth.review_stream_prefix(None, 'Invoices are outstanding.',
        sources={'s': {'kind': 'record', 'text': 'Invoices are outstanding.', 'complete': True}},
        message='What is outstanding?', business_id='b'))
