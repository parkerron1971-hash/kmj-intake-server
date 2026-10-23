"""The early check matches a list row by row, and a name must sit in the
record it is quoted from (2026-10-22: KMJ's voice turns never streamed)."""
import asyncio
import json

import chief_truth as truth

BIG = truth.STREAM_REVIEW_EVIDENCE_CHARS


def _memory(i, content):
    return {'id': f'mem-{i}', 'category': 'context', 'content': content, 'importance': 5}


def _memories(*extra):
    filler = [_memory(i, f'Workshop color palette note {i}. ' + 'x' * 1200) for i in range(30)]
    return {'kind': 'context', 'complete': False,
            'text': json.dumps(filler + list(extra), ensure_ascii=False)}


def _check(monkeypatch, sentence, sources, reply, message='Give me a rundown.'):
    seen = []

    async def reviewer(client, system, messages, **kwargs):
        seen.append(json.loads(messages[0]['content']))
        return json.dumps(reply)
    monkeypatch.setattr(truth, 'review_reply', reviewer)
    ok = asyncio.run(truth.review_stream_prefix(None, sentence, sources=sources,
                                                message=message, business_id=None))
    return ok, seen


def test_a_long_list_is_narrowed_to_its_matching_rows(monkeypatch):
    fact = _memory(99, 'Kevin lives in Muskegon, Michigan.')
    sources = {'context:memories': _memories(fact)}
    assert len(sources['context:memories']['text']) > BIG
    ok, seen = _check(monkeypatch, 'Kevin lives in Muskegon, Michigan.', sources,
                      {'supported': True, 'source_id': 'context:memories',
                       'quote': 'Kevin lives in Muskegon, Michigan.'})
    assert ok
    sent = seen[0]['sources']['context:memories']
    assert json.loads(sent['text']) == [fact]
    assert sent['rows_omitted'] == 30 and sent['complete'] is False


def test_a_row_that_contradicts_the_sentence_is_kept(monkeypatch):
    rows = [{'id': 'a', 'note': 'Your busiest day is Tuesday.'},
            {'id': 'b', 'note': 'Correction: your busiest day is Friday.'}]
    rows += [{'id': f'n{i}', 'note': 'Workshop color palette. ' + 'x' * 1200} for i in range(30)]
    sources = {'context:notes': {'kind': 'context', 'complete': True, 'text': json.dumps(rows)}}
    ok, seen = _check(monkeypatch, 'Your busiest day is Tuesday.', sources,
                      {'supported': False, 'source_id': '', 'quote': ''})
    assert not ok
    kept = json.loads(seen[0]['sources']['context:notes']['text'])
    assert [r['id'] for r in kept] == ['a', 'b']


def test_a_warning_row_is_kept_without_sharing_the_subject(monkeypatch):
    stale = _memory(98, 'All cash figures before October are stale.')
    sources = {'context:memories': _memories(_memory(99, 'Kevin lives in Muskegon, Michigan.'), stale)}
    _, seen = _check(monkeypatch, 'Kevin lives in Muskegon, Michigan.', sources,
                     {'supported': False, 'source_id': '', 'quote': ''})
    assert stale in json.loads(seen[0]['sources']['context:memories']['text'])


def test_a_list_the_sentence_names_stays_whole(monkeypatch):
    rows = [{'number': f'INV-{i}', 'client': f'Client {i}', 'total': 10 + i, 'note': 'x' * 900}
            for i in range(30)]
    sources = {'context:open_invoices': {'kind': 'context', 'complete': True, 'text': json.dumps(rows)}}
    assert len(sources['context:open_invoices']['text']) > BIG
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(True)
        return ''
    monkeypatch.setattr(truth, 'review_reply', forbidden)
    # "invoices" names the whole list: too big to check early, so it waits.
    assert not asyncio.run(truth.review_stream_prefix(None, 'You have 30 open invoices.',
        sources=sources, message='How many invoices?', business_id=None))
    assert calls == []


def test_a_cut_off_row_that_matches_is_kept_verbatim(monkeypatch):
    whole = _memories()['text']
    fragment = '{"id": "mem-77", "category": "context", "content": "Kevin lives in Muskeg'
    sources = {'context:memories': {'kind': 'context', 'complete': False,
                                    'text': whole[:-1] + ', ' + fragment}}
    _, seen = _check(monkeypatch, 'Kevin lives nearby.', sources,
                     {'supported': False, 'source_id': '', 'quote': ''})
    sent = seen[0]['sources']['context:memories']['text']
    assert sent.endswith(fragment) and 'Workshop color palette' not in sent


def test_everyday_words_do_not_pull_records_in(monkeypatch):
    sources = {'context:memories': _memories(_memory(99, 'Good to hear the launch went well.'))}
    # Nothing but everyday words: no record is relevant, so nothing is sent.
    sentence_terms = truth._stream_review_terms('Hey, good to hear from you.')
    assert sentence_terms == set()
    selected, _ = truth._stream_review_sources(sources, 'Hey, good to hear from you.', '', 'hi')
    assert selected is None


def test_a_record_noun_is_never_an_everyday_word():
    for word in ('invoice', 'paid', 'booked', 'cash', 'balance', 'sent', 'overdue'):
        assert word not in truth._STREAM_REVIEW_EVERYDAY


def test_a_swapped_name_is_held_even_when_the_figures_match(monkeypatch):
    row = {'number': 'INV-2026-013', 'client': 'Demetrio Dockery', 'total': 55.0, 'status': 'draft'}
    sources = {'context:open_invoices': {'kind': 'context', 'complete': True, 'text': json.dumps([row])},
               'context:memories': _memories()}
    cite = {'supported': True, 'source_id': 'context:open_invoices',
            'quote': '"number": "INV-2026-013", "client": "Demetrio Dockery", "total": 55.0'}
    ok, _ = _check(monkeypatch, "Monica Walton's invoice INV-2026-013 is for $55.", sources, cite)
    assert not ok
    ok, _ = _check(monkeypatch, "Demetrio Dockery's invoice INV-2026-013 is for $55.", sources, cite)
    assert ok


def test_a_name_from_another_row_does_not_count(monkeypatch):
    rows = [{'name': 'Monica Walton', 'status': 'active'}, {'name': 'Bradley Sherrod', 'status': 'lead'}]
    sources = {'context:contacts_lookup': {'kind': 'context', 'complete': True, 'text': json.dumps(rows)},
               'context:memories': _memories()}
    ok, _ = _check(monkeypatch, 'Monica Walton is still a lead.', sources,
                   {'supported': True, 'source_id': 'context:contacts_lookup', 'quote': '"status": "lead"'})
    assert not ok
