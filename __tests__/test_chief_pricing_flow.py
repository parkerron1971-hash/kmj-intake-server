"""Synthetic regressions for goal authorization, invalid jobs and pricing math."""
import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import chief_build_runtime as builds
import chief_of_staff as chief
import chief_truth as truth
from chief_projection_math import verified_figures

SOURCES = truth.conversation_for_review('The monthly prices are $79, $149 and $299.', [
    {'role': 'user', 'content': 'Could we make a million dollars in one year?'}])
CONVERSION = 'A million a year is about $83,300 a month in recurring revenue.'
MATH = CONVERSION + ' At $79, about 1,055. At $149, about 560. At $299, about 280.'


def review_for(draft):
    return json.dumps({'verdict': 'unsupported', 'claims': [
        {'text': sentence, 'kind': 'fact', 'source_id': '', 'quote': '', 'gap': 'calculation'}
        for sentence in draft.split('. ') if sentence]})


def test_owner_target_division_is_checked_instead_of_losing_all_pricing_math():
    assert truth.assess_review(review_for(MATH), MATH, SOURCES)[0] == 'supported'


@pytest.mark.parametrize('bad', [
    MATH.replace('83,300', '93,300'), MATH.replace('1,055', '1,155'),
    MATH.replace('560', '600'), MATH.replace('280', '299'),
    MATH.replace('about $83,300', '$83,300'),
])
def test_wrong_or_unlabeled_rounded_math_still_fails(bad):
    assert truth.assess_review(review_for(bad), bad, SOURCES)[0] == 'unsupported'


@pytest.mark.parametrize('sentence', [
    'Our revenue was about $83,300 a month.',
    'We have about 280 subscribers.',
    'Monica owes $280.',
    'At $299, about 280 subscribers have paid.',
    'At $299, about 280. I saved that goal.',
])
def test_calculation_never_proves_record_state_or_completed_actions(sentence):
    assert not verified_figures(sentence, MATH, SOURCES)


def test_target_and_rates_must_come_from_owner_not_assistant():
    sources = {key: {**value, 'role': 'assistant'} for key, value in SOURCES.items()}
    assert not verified_figures(CONVERSION, MATH, sources)
    assert not verified_figures('At $299, about 280.', MATH, sources)
    assert not verified_figures('At $499, about 167.', MATH, SOURCES)


def test_other_targets_and_rates_and_monthly_units_work():
    sources = truth.conversation_for_review('My revenue target is $120,000 a year and the plan is $50 monthly.', [])
    draft = '$120,000 per year means $10,000 per month. At $50 per month, you would need about 200 subscribers.'
    assert truth.assess_review(review_for(draft), draft, sources)[0] == 'supported'
    assert verified_figures('At $50 per month, you would need about 200 subscribers.', draft, sources) == {Decimal(50), Decimal(200)}


def test_a_fake_record_citation_is_never_replaced_with_planning_math():
    sources = {**SOURCES, 'context:revenue': {'kind': 'record', 'text': 'Revenue: $300'}}
    raw = json.dumps({'verdict': 'supported', 'claims': [{'text': CONVERSION, 'kind': 'fact',
        'source_id': 'context:revenue', 'quote': 'Revenue: $300'}]})
    assert truth.assess_review(raw, CONVERSION, sources)[0] == 'unsupported'


def test_checked_math_survives_beside_real_save_receipt():
    receipt = {'type': 'save_note', 'label': 'Saved the pricing assumptions', 'result': 'Note saved'}
    draft = MATH + ' I saved the pricing assumptions.'
    review = json.loads(review_for(MATH))
    review['claims'].append({'text': 'I saved the pricing assumptions.', 'kind': 'action',
        'source_id': 'result:0', 'quote': 'Saved the pricing assumptions'})
    reply, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail='',
        taken=[receipt], message='The monthly prices are $79, $149 and $299.', business_id='fixture',
        conversation_history=[{'role': 'user', 'content': 'Could we make a million dollars in one year?'}],
        reviewer=AsyncMock(return_value=json.dumps(review))))
    assert reply == draft and meta['status'] == 'supported'


@pytest.mark.parametrize('kind', ['goal_setup', 'custom', None, [], {}])
def test_invalid_build_type_is_our_error_and_cannot_read_or_write_storage(monkeypatch, kind):
    submit = AsyncMock(side_effect=AssertionError('invalid kind must not reach storage'))
    monkeypatch.setattr(builds, 'submit', submit)
    result = asyncio.run(builds.handle_submit_work_order(None, {'id': 'fictional'},
        {'type': 'submit_work_order', 'kind': kind, 'facts': {}}))
    assert result['failed'] and result['error_code'] == 'invalid_build_kind'
    assert 'Nothing was queued' in result['label']
    assert 'Choose an event' not in result['label']
    assert 'Do not ask the owner' in result['for_chief']
    submit.assert_not_awaited()


def test_valid_build_keeps_original_authority_and_submission_path(monkeypatch):
    submit = AsyncMock(return_value={'type': 'submit_work_order', 'label': 'Queued'})
    monkeypatch.setattr(builds, 'submit', submit)
    request = {'type': 'submit_work_order', 'kind': 'plan', 'facts': {'steps': []}}
    assert asyncio.run(builds.handle_submit_work_order(None, {'id': 'fictional'}, request))['label'] == 'Queued'
    submit.assert_awaited_once_with(None, {'id': 'fictional'}, request)


def test_composer_receives_question_and_calculation_with_receipt(monkeypatch):
    composer = AsyncMock(return_value=MATH + ' Saved the assumptions note.')
    monkeypatch.setattr(chief, '_call_claude', composer)
    receipt = {'type': 'save_note', 'label': 'Assumptions', 'result': 'Note saved'}
    result = asyncio.run(chief._compose_post_action_reply(None, 'Explain the pricing math.', MATH, [receipt]))
    assert MATH in result
    system = composer.call_args.args[1]
    payload = composer.call_args.args[2][0]['content']
    assert 'receipts supplement' in system and 'calculations' in system
    assert 'Explain the pricing math.' in payload and MATH in payload and 'Note saved' in payload


@pytest.mark.parametrize('owner,draft,gap', [
    ('We aim for 1,000,000 website views. Our membership costs $299 per year, not per month.',
     '$1,000,000 per year means about $83,333 per month. At $299 per month, you would need about 280 subscribers.',
     'Owner target is website views, not revenue; the rate is annual, not monthly'),
    ('My goal is $120,000 over five years. The plan costs $50 monthly.',
     '$120,000 per year means $10,000 per month. At $50 per month, you would need about 200 subscribers.',
     'calculation'),
    ('My annual revenue target is $120,000; the offer costs $50 per session.',
     '$120,000 per year means $10,000 per month. At $50 per month, you would need about 200 subscribers.',
     'calculation'),
    ('My annual revenue target is $120,000. The plan is not $50 per month.',
     '$120,000 per year means $10,000 per month. At $50 per month, you would need about 200 subscribers.',
     'calculation'),
])
def test_wrong_meaning_and_billing_period_cannot_pass_as_arithmetic(owner, draft, gap):
    sources = truth.conversation_for_review(owner, [])
    review = json.loads(review_for(draft))
    for claim in review['claims']:
        claim['gap'] = gap
    assert truth.assess_review(json.dumps(review), draft, sources)[0] == 'unsupported'


@pytest.mark.parametrize('gap', [
    'The latest target is different', 'Owner did not authorize this target',
    'The monthly billing assumption contradicts the owner',
    'calculation, but the source is website views',
])
def test_semantic_gap_is_never_overridden_by_matching_numbers(gap):
    raw = json.loads(review_for(MATH))
    raw['claims'][0]['gap'] = gap
    assert truth.assess_review(json.dumps(raw), MATH, SOURCES)[0] == 'unsupported'


def test_latest_correction_is_not_overridden_by_older_arithmetic_inputs():
    sources = truth.conversation_for_review('Actually use $500,000 per year instead.', [
        {'role': 'user', 'content': 'My annual revenue target is $1,000,000.'}])
    draft = '$1,000,000 per year means about $83,333 per month.'
    raw = json.loads(review_for(draft))
    raw['claims'][0]['gap'] = 'This uses the old target; the latest owner correction is $500,000'
    assert truth.assess_review(json.dumps(raw), draft, sources)[0] == 'unsupported'


@pytest.mark.parametrize('owner', [
    'My annual revenue target is $120,000. We pay $50 per month in office rent.',
    'My annual revenue target is $120,000. Our office rent is $50 per month and the plan is $100 per month.',
    'My annual revenue target is $120,000. The plan is $100 per month and we pay $50 per month in office rent.',
    'My annual revenue target is $120,000. The plan is $50 per month for office rent.',
    'My annual revenue target is $120,000. Our insurance plan is $50 per month.',
])
def test_monthly_expenses_cannot_supply_a_subscription_price(owner):
    sources = truth.conversation_for_review(owner, [])
    draft = '$120,000 per year means $10,000 per month. At $50 per month, you would need about 200 subscribers.'
    assert truth.assess_review(review_for(draft), draft, sources)[0] == 'unsupported'


def test_price_and_rent_in_same_sentence_preserve_only_the_explicit_price():
    sources = truth.conversation_for_review(
        'My annual revenue target is $120,000. Our office rent is $50 per month and the plan is $100 per month.', [])
    draft = '$120,000 per year means $10,000 per month. At $100 per month, you would need about 100 subscribers.'
    assert truth.assess_review(review_for(draft), draft, sources)[0] == 'supported'


@pytest.mark.parametrize('owner', [
    'My profit target is $120,000 per year. The plan costs $50 monthly.',
    'The spending target is $120,000 per year. The plan costs $50 monthly.',
    'My annual budget target is $120,000. The plan costs $50 monthly.',
    'I want to make $120,000 per year in profit. The plan costs $50 monthly.',
    'I want to earn $120,000 per year in net income. The plan costs $50 monthly.',
    'My target is $120,000 per year. The plan costs $50 monthly.',
])
def test_non_revenue_or_ambiguous_targets_cannot_prove_customer_counts(owner):
    sources = truth.conversation_for_review(owner, [])
    draft = '$120,000 per year means $10,000 per month. At $50 per month, you would need about 200 subscribers.'
    assert truth.assess_review(review_for(draft), draft, sources)[0] == 'unsupported'
