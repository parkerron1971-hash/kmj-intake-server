"""Email answers must reach review with the same scoped evidence as the author."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

import chief_of_staff as chief
import chief_truth as truth
import mailbox_policy


def context():
    contacts = [{'id': 'client-ada', 'name': 'Ada', 'email': 'ada@example.com'}]
    rows = [
        {'id': 'message-ada', 'from_email': 'ada@example.com', 'from_name': 'Ada',
         'subject': 'Project update', 'body_text': 'The draft looks good.',
         'received_at': '2026-09-11T17:30:00Z', 'read': True},
        {'id': 'unknown', 'from_email': 'stranger@example.com',
         'subject': 'PRIVATE UNKNOWN SUBJECT', 'body_text': 'PRIVATE UNKNOWN BODY',
         'received_at': '2026-09-11T18:00:00Z'},
    ]
    return {
        'business': {'settings': {'availability': {'timezone': 'America/New_York'},
                                  'secret': 'PRIVATE SETTING'}},
        'context_quality': {'retrieved_at': '2026-09-11T18:08:00Z'},
        'contacts_lookup': contacts,
        'email_context_quality': {'platform_replies': 'available',
                                  'connected_mailbox': 'available',
                                  'scope': 'Recent stored sample, not a full inbox search or a live mailbox sync.'},
        **mailbox_policy.split_for_prompt(chief._merge_inbound_mail([], rows), contacts),
    }


@pytest.mark.parametrize('question', [
    'Did any client email me today?',
    'Can you check to see if any of my clients emailed me today?',
])
def test_reported_questions_keep_supported_email_answer(question):
    ctx = context()
    answer = 'Yes — Ada emailed you today about Project update.'
    async def reviewer(_client, _system, messages, **_kwargs):
        payload = json.loads(messages[0]['content'])
        source = payload['sources'].get('context:email_replies')
        # Reproduces the old failure: the author has this block, but the
        # reviewer had no source it could cite and withheld the answer.
        if source is None:
            return json.dumps({'verdict': 'unsupported', 'claims': []})
        block = source['text']
        assert block == chief._format_email_replies_block(ctx)
        assert 'Today is 2026-09-11 in America/New_York' in block
        assert '2026-09-11T13:30:00-04:00' in block
        assert 'Ada' in block and 'Project update' in block
        return json.dumps({'verdict': 'supported', 'claims': [
            {'text': answer, 'kind': 'fact', 'source_id': 'context:email_replies',
             'quote': source['text']}]})
    token = truth.begin('owner', question)
    try:
        result, meta = asyncio.run(truth.finalize_reply(
            None, answer, ctx=ctx, view_detail={}, taken=[], message=question,
            business_id='business', reviewer=reviewer))
        assert result == answer
        assert meta == {'status': 'supported', 'sources': ['context:email_replies']}
    finally:
        truth.end(token)


def test_email_review_does_not_expose_unknown_senders_or_raw_settings():
    sources = truth.evidence_for_review(context(), {}, [])
    serialized = json.dumps(sources)
    assert 'PRIVATE' not in serialized
    email = sources['context:email_replies']
    assert email['complete'] is False
    assert email['kind'] == 'context'
    assert 'WITHHELD' in email['text']
    assert 'Recent stored sample' in email['text']


def test_email_review_can_cite_literal_quotes_and_newlines():
    ctx = context()
    source = truth.evidence_for_review(ctx, {}, [])['context:email_replies']
    block = chief._format_email_replies_block(ctx)
    # A reviewer sees the rendered email excerpt, not JSON string escapes.
    quote = next(line for line in block.splitlines() if 'The draft looks good.' in line)
    assert '"' in quote
    reply = 'Ada wrote: "The draft looks good."'
    review = json.dumps({'verdict': 'supported', 'claims': [
        {'text': reply, 'kind': 'fact', 'source_id': 'context:email_replies', 'quote': quote}]})
    assert truth.validate_review(review, reply, {'context:email_replies': source})[0]
    assert '\n' in source['text']


def test_sample_remains_incomplete_and_failed_read_is_visible():
    ctx = context()
    ctx['email_replies'] = []
    ctx['email_context_quality']['connected_mailbox'] = 'unavailable'
    block = chief._format_email_replies_block(ctx)
    source = truth.evidence_for_review(ctx, {}, [])['context:email_replies']
    assert source['text'] == block
    assert 'unavailable' in block
    assert 'NEVER tell them nobody emailed them' in block
    assert 'email_setup_status' in block
    assert source['complete'] is False


@pytest.mark.parametrize('stamp,local_date,offset', [
    ('2026-09-12T02:00:00Z', '2026-09-11', '-04:00'),
    ('2026-01-02T02:00:00Z', '2026-01-01', '-05:00'),
    ('2026-03-08T07:30:00Z', '2026-03-08', '-04:00'),
])
def test_today_uses_local_day_including_dst(stamp, local_date, offset):
    ctx = context()
    ctx['context_quality']['retrieved_at'] = stamp
    clock = mailbox_policy.email_clock(ctx)
    assert f'Today is {local_date}' in clock['description']
    received = mailbox_policy.local_received_at(stamp, clock['timezone'])
    assert received.startswith(local_date) and received.endswith(offset)


def test_clock_follows_practitioner_then_platform_fallback(monkeypatch):
    ctx = context()
    ctx['business']['settings']['availability'] = {}
    ctx['practitioner_profile_raw'] = {'timezone': 'America/Los_Angeles', 'secret': 'PRIVATE'}
    monkeypatch.setenv('PLATFORM_DEFAULT_TZ', 'Europe/London')
    assert str(mailbox_policy.email_clock(ctx)['timezone']) == 'America/Los_Angeles'
    ctx['practitioner_profile_raw'] = {}
    assert str(mailbox_policy.email_clock(ctx)['timezone']) == 'Europe/London'


@pytest.mark.parametrize('stamp', [None, '', 'bad', '2026-09-11T17:30:00'])
def test_missing_or_ambiguous_dates_cannot_become_today(stamp):
    ctx = context()
    ctx['context_quality']['retrieved_at'] = stamp
    clock = mailbox_policy.email_clock(ctx)
    assert 'do not infer today' in clock['description']
    assert mailbox_policy.local_received_at(stamp, clock['timezone']).startswith('unknown')


def test_invalid_timezone_is_explicit():
    ctx = context()
    ctx['business']['settings']['availability']['timezone'] = 'invalid/zone'
    assert 'UTC (configured timezone unavailable)' in mailbox_policy.email_clock(ctx)['description']


def test_email_evidence_survives_large_unrelated_context_and_keeps_body_cap():
    ctx = context()
    ctx.update({name: 'x' * truth.MAX_SOURCE_CHARS for name in (
        'brand_block', 'voice_block', 'playbook_block', 'blueprint_block',
        'foundation_block', 'business_profile_block', 'practitioner_block')})
    ctx['email_replies'][0]['body_text'] = 'a' * 281 + 'PRIVATE TAIL'
    sources = truth.evidence_for_review(ctx, {}, [])
    assert 'context:email_replies' in sources
    assert 'PRIVATE TAIL' not in sources['context:email_replies']['text']


def test_unsupported_email_answer_still_fails_closed():
    result, meta = asyncio.run(truth.finalize_reply(
        None, 'Nobody emailed you today.', ctx=context(), view_detail={}, taken=[],
        message='Did any client email me today?', business_id='business',
        reviewer=AsyncMock(return_value='{"verdict":"unsupported","claims":[]}')))
    assert result.startswith('Yes. I found client email dated today')
    assert 'Nobody emailed' not in result
    assert 'not a full inbox search' in result
    assert meta['status'] == 'records'


def test_no_matches_is_limited_to_the_stored_sample():
    ctx = context()
    ctx['email_replies'][0]['received_at'] = '2026-05-01T12:00:00Z'
    reply = mailbox_policy.client_email_today_reply('Did any client email me today?', ctx)
    assert reply.startswith("I don't see client email dated today in the recent stored messages")
    assert 'not a full inbox search or a live mailbox sync' in reply


def test_failed_reads_do_not_become_no_email():
    ctx = context()
    ctx['email_replies'] = []
    ctx['email_context_quality']['connected_mailbox'] = 'unavailable'
    reply = mailbox_policy.client_email_today_reply('Did any client email me today?', ctx)
    assert "couldn't retrieve all the email sources" in reply
    assert "don't see" not in reply


def test_unknown_senders_and_bad_dates_cannot_become_client_mail_today():
    ctx = context()
    ctx['email_replies'][0]['received_at'] = 'bad'
    ctx['email_replies'].append({'from_email': 'stranger@example.com', 'received_at': '2026-09-11T20:00:00Z'})
    reply = mailbox_policy.client_email_today_reply('Did any client email me today?', ctx)
    assert 'missing dates' in reply
    assert 'Yes.' not in reply


def test_email_fallback_never_infers_today_without_snapshot_clock():
    ctx = context()
    ctx['context_quality'] = {}
    reply = mailbox_policy.client_email_today_reply('Did any client email me today?', ctx)
    assert "can't determine today's date" in reply


def test_email_fallback_matches_the_local_day():
    ctx = context()
    ctx['email_replies'][0]['received_at'] = '2026-09-12T02:00:00Z'
    assert mailbox_policy.client_email_today_reply('Did any client email me today?', ctx).startswith('Yes.')


def test_email_fallback_does_not_swallow_actions_or_other_questions():
    for question in ('Did any client email me today? Reply to them.', 'What did Ada say?', 'Did anyone email me last week?'):
        assert mailbox_policy.client_email_today_reply(question, context()) is None


def test_reviewer_outage_answers_reported_question_from_records():
    reply, meta = asyncio.run(truth.finalize_reply(
        None, 'No one emailed you.', ctx=context(), view_detail={}, taken=[],
        message='Can you check to see if any of my clients emailed me today?', business_id='business',
        reviewer=AsyncMock(side_effect=RuntimeError('review unavailable'))))
    assert reply.startswith('Yes.')
    assert meta['status'] == 'records'


def test_read_only_setup_check_does_not_block_scoped_email_answer():
    reply, meta = asyncio.run(truth.finalize_reply(
        None, 'No one emailed you.', ctx=context(), view_detail={},
        taken=[{'type': 'email_setup_status', 'result': 'Mailbox status checked', 'label': 'Email status'}],
        message='Did any client email me today?', business_id='business',
        reviewer=AsyncMock(return_value='')))
    assert reply.startswith('Yes.')
    assert meta['status'] == 'records'
