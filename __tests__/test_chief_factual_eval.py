import asyncio
import pytest
from scripts import chief_factual_eval as factual


@pytest.mark.parametrize('case', factual.CASES, ids=lambda c: c['id'])
def test_good_answers_pass_and_injected_bad_answers_are_withheld(case):
    good = asyncio.run(factual.run_case(case))
    bad = asyncio.run(factual.run_case(case, inject_bad=True))
    assert good['passed'], good
    assert bad['passed'], bad


@pytest.mark.parametrize('case', factual.CASES, ids=lambda c: c['id'])
def test_scorer_rejects_false_claims_and_does_not_reward_blanket_refusal(case):
    assert not factual.score(case, case['bad'])['factual_answer_correct']
    assert not factual.score(case, case['bad'])['known_false_claim_absent']
    if case['id'] in ('count_above_page_cap', 'poisoned_email'):
        assert not factual.score(case, "I couldn't verify that answer.")['factual_answer_correct']
