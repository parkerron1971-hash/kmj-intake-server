"""A repair rechecks its changed claims, not every already verified sentence."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import chief_truth as truth

PRICE = 'Your Blueprint price is $3000.'
ADVICE = ('I recommend testing demand with a small group before adding more offers, '
          'and starting with a simple conversation about what people need most.')
GOOD = 'Annual client-slot capacity is $12000.'
BAD = ('Annual client-slot capacity is $24000, ' +
       'which makes this an especially ambitious planning assumption, ' * 12 +
       'and it determines the target.')
SOURCE = PRICE + ' ' + GOOD
SOURCES = {'context:capacity': {'kind': 'record', 'text': SOURCE}}
ORIGINAL = PRICE + ' ' + ADVICE + ' ' + BAD
REPAIRED = PRICE + ' ' + ADVICE + ' ' + GOOD


def claim(text, **kwargs):
    return {'text': text, 'kind': 'fact', 'source_id': 'context:capacity',
            'quote': SOURCE, **kwargs}


def raw(claims, verdict='supported'):
    return json.dumps({'verdict': verdict, 'claims': claims})


FIRST = raw([claim(PRICE), claim(BAD)], 'unsupported')


def test_retains_only_verbatim_supported_claims():
    changed, retained = truth._reuse_review_claims(FIRST, ORIGINAL, REPAIRED, SOURCES)
    assert changed == GOOD
    assert retained == [claim(PRICE)]
    assert truth.assess_review(raw(retained + [claim(GOOD)]), REPAIRED, SOURCES)[0] == 'supported'


@pytest.mark.parametrize('repair', [
    'A wholly different answer.',
    REPAIRED + ' ' + PRICE,
    REPAIRED + ' I sent your invoice.',
])
def test_broad_ambiguous_or_action_rewrites_keep_full_review(repair):
    assert truth._reuse_review_claims(FIRST, ORIGINAL, repair, SOURCES) is None


def test_unsupported_unchanged_claim_cannot_be_reused():
    bad = raw([claim(PRICE, quote='Invented source quote'), claim(BAD)])
    assert truth._reuse_review_claims(bad, ORIGINAL, REPAIRED, SOURCES) is None


def test_cross_sentence_claim_keeps_full_review():
    first = raw([claim(PRICE), claim(ADVICE + ' ' + BAD)])
    repaired = PRICE + ' ' + ADVICE + ' ' + BAD + ' I recommend reconsidering.'
    assert truth._reuse_review_claims(first, ORIGINAL, repaired, SOURCES) is None


def finalize(second, repair=REPAIRED):
    reviewer = AsyncMock(side_effect=[FIRST, second])
    repairer = AsyncMock(return_value=repair)
    token = truth.begin('owner', 'How can I grow this business?')
    try:
        truth.record('context:capacity', SOURCE)
        out, meta = asyncio.run(truth.finalize_reply(None, ORIGINAL, ctx={}, view_detail='',
            taken=[], message='How can I grow this business?', business_id='test',
            reviewer=reviewer, repairer=repairer))
    finally:
        truth.end(token)
    return out, meta, reviewer, repairer


def test_recovery_reviews_changed_math_with_complete_context_and_all_evidence():
    out, meta, reviewer, repairer = finalize(raw([claim(GOOD)]))
    assert out == REPAIRED and meta['recovered']
    assert reviewer.await_count == 2 and repairer.await_count == 1
    payload = json.loads(reviewer.call_args.args[2][0]['content'])
    assert payload['draft'] == GOOD
    assert payload['complete_repaired_answer'] == REPAIRED
    assert payload['sources']['context:capacity']['text'] == SOURCE
    assert 'any conclusion' in reviewer.call_args.args[1]
    assert '$24000' not in out


@pytest.mark.parametrize('second', ['', 'not JSON', raw([], 'unsupported'), raw([]),
    raw([claim(GOOD, quote='Invented proof')]),
    raw([claim(GOOD, source_id='missing')]),
    raw([claim('Annual client-slot capacity is $24000.')]),
])
def test_targeted_review_never_fails_open(second):
    out, meta, reviewer, _ = finalize(second)
    assert out == truth.NO_ACTION_REPLY and meta['status'] == 'withheld'
    assert reviewer.await_count == 2


def test_forged_math_cannot_pass_with_a_real_unrelated_quote():
    wrong = REPAIRED.replace('$12000', '$24001')
    out, meta, _, _ = finalize(raw([claim(GOOD.replace('$12000', '$24001'))]), wrong)
    assert out == truth.NO_ACTION_REPLY and meta['status'] == 'withheld'


def test_cleanup_preserves_advice_accepted_by_the_first_review():
    advice = "I'd start at $750 and test demand before expanding."
    unsupported = 'Demand is guaranteed.'
    draft = PRICE + ' ' + advice + ' ' + unsupported
    review = raw([claim(PRICE),
        claim(advice, source_id='', quote='', gap='This is a recommendation'),
        claim(unsupported, source_id='', quote='', gap='No demand evidence')], 'unsupported')
    verdict, _, reason = truth.assess_review(review, draft, SOURCES)
    assert verdict == 'unsupported'
    gaps = truth.unconfirmed_claims(review, reason)
    out, meta = truth._clean_review_gaps(review, draft, SOURCES, gaps, [])
    assert out == PRICE + ' ' + advice
    assert meta['status'] == 'trimmed' and meta['cuts'] == 1


def test_cache_transport_preserves_complete_answer_context():
    payload = {'draft': GOOD, 'sources': SOURCES, 'complete_repaired_answer': REPAIRED}
    messages = truth._cacheable_review_messages([{'role': 'user', 'content': json.dumps(payload)}])
    decoded = json.loads(''.join(block['text'] for block in messages[0]['content']))
    assert decoded == payload


def test_cleanup_avoids_repair_and_repeated_review_for_valid_advice():
    advice = "I'd start at $750 and test demand before expanding."
    unsupported = 'Demand is guaranteed.'
    draft = PRICE + ' ' + advice + ' ' + unsupported
    review = raw([claim(PRICE),
        claim(advice, source_id='', quote='', gap='This is a recommendation'),
        claim(unsupported, source_id='', quote='', gap='No demand evidence')], 'unsupported')
    reviewer = AsyncMock(return_value=review)
    repairer = AsyncMock(side_effect=AssertionError('Already checked advice needs no repair'))
    token = truth.begin('owner', 'What price would you recommend?')
    try:
        truth.record('context:capacity', SOURCE)
        out, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail='',
            taken=[], message='What price would you recommend?', business_id='test',
            reviewer=reviewer, repairer=repairer))
    finally:
        truth.end(token)
    assert out == PRICE + ' ' + advice and meta['status'] == 'trimmed'
    reviewer.assert_awaited_once()
    repairer.assert_not_awaited()


@pytest.mark.parametrize('unreviewed', [
    'All your invoices are paid.',
    'Your customers have already confirmed their bookings.',
])
def test_omitted_unchanged_nonnumeric_fact_requires_full_review(unreviewed):
    original = ORIGINAL.replace(PRICE, PRICE + ' ' + unreviewed, 1)
    repaired = REPAIRED.replace(PRICE, PRICE + ' ' + unreviewed, 1)
    assert truth._reuse_review_claims(FIRST, original, repaired, SOURCES) is None


def test_partial_sentence_claim_does_not_cover_unreviewed_clause():
    mixed = 'Your Blueprint price is $3000, and all your invoices are paid.'
    original = ORIGINAL.replace(PRICE, mixed, 1)
    repaired = REPAIRED.replace(PRICE, mixed, 1)
    first = raw([claim('Your Blueprint price is $3000'), claim(BAD)], 'unsupported')
    assert truth._reuse_review_claims(first, original, repaired, SOURCES) is None


def test_omitted_fact_reaches_full_independent_second_review():
    omitted = 'All your invoices are paid.'
    original = ORIGINAL.replace(PRICE, PRICE + ' ' + omitted, 1)
    repaired = REPAIRED.replace(PRICE, PRICE + ' ' + omitted, 1)
    reviewer = AsyncMock(side_effect=[FIRST, raw([], 'unsupported')])
    repairer = AsyncMock(return_value=repaired)
    token = truth.begin('owner', 'How can I grow this business?')
    try:
        truth.record('context:capacity', SOURCE)
        out, meta = asyncio.run(truth.finalize_reply(None, original, ctx={}, view_detail='',
            taken=[], message='How can I grow this business?', business_id='test',
            reviewer=reviewer, repairer=repairer))
    finally:
        truth.end(token)
    payload = json.loads(reviewer.call_args.args[2][0]['content'])
    assert payload['draft'] == repaired and omitted in payload['draft']
    assert 'complete_repaired_answer' not in payload
    assert out == truth.NO_ACTION_REPLY and meta['status'] == 'withheld'
    assert reviewer.await_count == 2
