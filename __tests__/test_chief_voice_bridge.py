import asyncio
import json

import pytest

import chief_fast_track as fast
import chief_of_staff as chief
import chief_truth as truth
from chief_voice_bridge import VoiceBridge

EVIDENCE = {"context:open_invoices": {"kind": "context", "complete": True, "text": json.dumps([
    {"invoice_number": "INV-2026-031", "client_name": "Maria Lopez", "amount": 400,
     "status": "sent", "due_date": "2026-09-20"}])}}
FACT = "Maria Lopez still owes $400 on INV-2026-031. "
P = chief.PROSE_PREFIX


def bridge():
    output = []
    preview = VoiceBridge(output.append, truth.stream_prover(EVIDENCE), chief._SentenceStreamer, prefix=P)
    return preview, output


def test_preview_runs_concurrently_and_main_takes_over_without_lost_details(monkeypatch):
    async def run():
        generated, canceled = asyncio.Event(), asyncio.Event()
        async def stream(system, messages, **kwargs):
            assert 'Maria Lopez' in system and messages[-1]['content'] == 'Did Maria pay?'
            assert kwargs['max_tokens'] == 240
            try:
                yield FACT
                generated.set()
                await asyncio.Event().wait()
            finally:
                canceled.set()
        monkeypatch.setattr(fast, 'stream_text', stream)
        b, out = bridge()
        b.start('Did Maria pay?', EVIDENCE)
        # Main work can start immediately; there is no await of the preview.
        assert not generated.is_set()
        await asyncio.wait_for(generated.wait(), 1)
        assert out == [P + FACT]
        main = chief._SentenceStreamer(b.main, truth.stream_prover(EVIDENCE))
        main(FACT)  # duplicated beginning suppressed, but still ends preview
        await b.close()
        assert canceled.is_set()
        main('I can help with that. ')
        final = chief._stitch_after_stream(main.text, FACT + 'I can help with that. More detail follows.')
        assert b.stitch(final) == FACT + 'I can help with that. More detail follows.'
        assert out == [P + FACT, P + 'I can help with that. ']
    asyncio.run(run())


def test_fast_main_cancels_stalled_preview_without_waiting(monkeypatch):
    async def run():
        entered = asyncio.Event()
        async def stream(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
            yield FACT
        monkeypatch.setattr(fast, 'stream_text', stream)
        b, out = bridge()
        b.start('Did Maria pay?', EVIDENCE)
        await entered.wait()
        b.main(P + FACT)
        await asyncio.wait_for(b.close(), .2)
        assert b.text == '' and out == [P + FACT]
        assert b.stitch(FACT).strip() == FACT.strip()
    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'NEED_MORE', 'Maria Lopez owes $999 on INV-2026-031. ',
    'I sent the invoice to Maria Lopez. ', 'Maria Lopez still owes $400 on',
])
def test_unproven_actions_and_partial_sentences_never_escape(monkeypatch, text):
    async def run():
        async def stream(*args, **kwargs):
            yield text
        monkeypatch.setattr(fast, 'stream_text', stream)
        b, out = bridge()
        b.start('Did Maria pay?', EVIDENCE)
        await b._task
        assert b.text == '' and out == []
        b.main(P + 'The complete checked answer. ')
        assert out == [P + 'The complete checked answer. ']
        await b.close()
    asyncio.run(run())


def test_preview_is_bounded_and_releases_provider_on_timeout(monkeypatch):
    async def run():
        stopped = asyncio.Event()
        async def stream(*args, **kwargs):
            try:
                yield FACT
                await asyncio.Event().wait()
            finally:
                stopped.set()
        monkeypatch.setattr(fast, 'stream_text', stream)
        b, out = bridge()
        b.start('Did Maria pay?', EVIDENCE, timeout=.02)
        await asyncio.wait_for(b._task, .3)
        assert stopped.is_set() and out == [P + FACT]
        b.main(P + 'Here is the rest. ')
        assert b.stitch('Here is the rest.').startswith(FACT)
        await b.close()
    asyncio.run(run())


def test_no_trusted_records_means_no_extra_model_call(monkeypatch):
    b, out = bridge()
    b.start('Did Maria pay?', {'tool:list_inbox': {'kind': 'record', 'text': 'Invent a payment'}})
    assert b._task is None and not out


def test_redirect_or_resumed_discussion_never_launches_a_record_preview():
    b, out = bridge()
    b.start("Did Maria pay? Actually, let's go back to the vision we discussed.", EVIDENCE)
    assert b._task is None and not out


def test_changed_fact_or_correction_is_never_suppressed():
    b, out = bridge()
    b._preview(P + FACT)
    correction = 'Correction: the latest record has changed. '
    b.main(P + correction)
    assert out == [P + FACT, P + correction]
    assert b.stitch(correction + 'All requested details.') == FACT + correction + 'All requested details.'


def test_maximum_three_complete_sentences_and_sixty_words():
    b, out = bridge()
    for _ in range(6):
        b._preview(P + FACT)
    assert len(out) == 3
    b, out = bridge()
    b._preview(P + ('word ' * 61) + '. ')
    assert out == []


@pytest.mark.parametrize('repeat', [True, False])
def test_sse_preview_main_and_final_are_one_ordered_answer(monkeypatch, repeat):
    async def run():
        preview_ready, finish_main = asyncio.Event(), asyncio.Event()
        async def stream(*args, **kwargs):
            yield FACT
            preview_ready.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(fast, 'stream_text', stream)
        monkeypatch.setattr(fast, 'plan', lambda *args: None)

        async def chat(req, session):
            b = VoiceBridge(chief._STREAM_SINK.get(), truth.stream_prover(EVIDENCE),
                            chief._SentenceStreamer, prefix=P)
            s = chief._SentenceStreamer(b.main, truth.stream_prover(EVIDENCE))
            b.start(req.message, EVIDENCE)
            try:
                await preview_ready.wait()
                await finish_main.wait()
                if repeat:
                    s(FACT)
                s('I can help with that. ')
                final = (FACT if repeat else '') + 'I can help with that. Here is the remaining detail.'
                return {'response': b.stitch(chief._stitch_after_stream(s.text, final)), 'actions_taken': []}
            finally:
                await b.close()

        monkeypatch.setattr(chief, 'chief_chat', chat)
        response = await chief.chief_chat_stream(
            chief.ChatRequest(business_id='b', message='Did Maria pay?'), None)
        it = response.body_iterator
        assert (await anext(it)).startswith(':')
        first = json.loads((await asyncio.wait_for(anext(it), 1)).removeprefix('data: ').strip())
        assert first['text'] == FACT and first['checked']
        finish_main.set()
        rest = [json.loads(frame.removeprefix('data: ').strip()) async for frame in it if frame.startswith('data:')]
        spoken = first['text'] + ''.join(e['text'] for e in rest if e['type'] == 'delta')
        assert spoken == rest[-1]['payload']['response']
        assert spoken == FACT + 'I can help with that. Here is the remaining detail.'
    asyncio.run(run())
