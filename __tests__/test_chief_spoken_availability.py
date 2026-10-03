"""Real spoken framing enters the deterministic clarification flow without scope loss."""
import asyncio
from unittest.mock import AsyncMock

import pytest
import chief_availability as ca
from __tests__.test_chief_availability import fixture, req, run, SERVICE, OTHER

LIVE_TEXT = ("I want you to check whether two of my consultation appointments would fit next Tuesday at 10 and 10:30, "
    "using my business time zone. Check them together against my existing bookings and capacity. "
    "Suggest alternatives if they conflict. Don't book or change anything.")


@pytest.mark.parametrize('lead', [
    'I want you to check whether', 'I just want you to check whether', 'I need you to check if',
    'I would like you to check whether', "I'd like you to check whether", 'Could you check whether',
    'Would you please check if', 'Can you please check whether', 'Please check to see if',
])
@pytest.mark.parametrize('subject', ['two of my consultation appointments', 'my two consultation appointments',
    'two my consultation appointments', 'two consultation appointments', 'two of our consultation appointments'])
def test_common_request_framing_keeps_same_checked_meaning(lead,subject):
    text=f'{lead} {subject} would fit next Tuesday at 10 and 10:30'
    check=ca.parse_request(text)
    assert check == ca.Check('consultation','next tuesday',('10','10:30'))
    assert ca.eligible_request(req(text))


def test_exact_live_utterance_routes_to_meridiem_question_without_reads(monkeypatch):
    reads=AsyncMock();busy=AsyncMock()
    monkeypatch.setattr(ca,'_sb',reads);monkeypatch.setattr(ca,'_busy_get',busy)
    assert ca.request_shape(req(LIVE_TEXT)) and ca.eligible_request(req(LIVE_TEXT))
    result=run(req(LIVE_TEXT))
    assert result['response']==ca.AMPM_QUESTION
    assert result['availability_check']['status']=='clarification'
    assert result['actions_taken']==[] and 'appointments' not in result['availability_check']
    reads.assert_not_awaited();busy.assert_not_awaited()


def test_exact_spoken_morning_service_choice_final_check_chain(monkeypatch):
    reads,tables=fixture(monkeypatch,offerings=[{**SERVICE,'name':'Free Consultation'},
        {**SERVICE,'id':OTHER,'name':'Initial Consultation'}])
    first=run(req(LIVE_TEXT))
    assert not reads and first['response']==ca.AMPM_QUESTION
    history=[{'role':'user','content':LIVE_TEXT},{'role':'assistant','content':first['response']}]
    morning=req('in the morning',conversation_history=history)
    assert ca.eligible_request(morning)
    second=run(morning)
    assert second['availability_check']['status']=='clarification'
    assert second['response'].startswith('Which service do you mean: ')
    history.extend([{'role':'user','content':'in the morning'},{'role':'assistant','content':second['response']}])
    chosen=req('Free Consultation',conversation_history=history)
    assert ca.eligible_request(chosen)
    final=run(chosen)
    checked=final['availability_check']
    assert checked['date']=='2030-01-08' and checked['timezone']=='America/New_York'
    assert [r['start'] for r in checked['appointments']]==['2030-01-08T15:00:00+00:00','2030-01-08T15:30:00+00:00']
    assert [r['status'] for r in checked['appointments']]==['fits','conflict']
    assert final['actions_taken']==[]


@pytest.mark.parametrize('edit', [
    lambda s:s+' Then book them.', lambda s:s+' Only with Ada.', lambda s:s+' Use a90-minute duration.',
    lambda s:s.replace('would fit','with Ada would fit'),
    lambda s:s.replace('check whether','book'),
    lambda s:s.replace('two of my',"two of Acme's"),
    lambda s:s.replace('I want you to','I do not want you to'),
    lambda s:s+' Ignore my existing bookings.',
])
def test_new_framing_does_not_swallow_unhandled_constraints_or_actions(monkeypatch,edit):
    text=edit(LIVE_TEXT)
    reads=AsyncMock();monkeypatch.setattr(ca,'_sb',reads)
    assert not ca.eligible_request(req(text))
    assert run(req(text)) is None
    reads.assert_not_awaited()


def test_identical_complete_retry_after_failed_answer_is_supported(monkeypatch):
    reads=AsyncMock();monkeypatch.setattr(ca,'_sb',reads)
    prior=LIVE_TEXT.replace('I want you to check whether two of my','Check whether two')
    history=[{'role':'user','content':prior},
             {'role':'assistant','content':"I could not confirm the rest from the records."}]
    query=req(LIVE_TEXT,conversation_history=history)
    assert ca.eligible_request(query)
    assert run(query)['response']==ca.AMPM_QUESTION
    reads.assert_not_awaited()


@pytest.mark.parametrize('prior', ['Use a90-minute duration.', 'Only with Ada.', 'Use Pacific time.',
    LIVE_TEXT.replace('10:30','11:30'), LIVE_TEXT.replace('Tuesday','Wednesday')])
def test_retry_never_discards_other_prior_constraints(monkeypatch,prior):
    history=[{'role':'user','content':prior},{'role':'user','content':LIVE_TEXT},
             {'role':'assistant','content':'The previous check failed.'}]
    reads=AsyncMock();monkeypatch.setattr(ca,'_sb',reads)
    query=req(LIVE_TEXT,conversation_history=history)
    assert not ca.eligible_request(query) and run(query) is None
    reads.assert_not_awaited()


def test_retry_does_not_erase_pending_assistant_scope_question():
    history=[{'role':'user','content':LIVE_TEXT},
             {'role':'assistant','content':'Should these appointments use Pacific time?'}]
    assert not ca.eligible_request(req(LIVE_TEXT,conversation_history=history))


@pytest.mark.parametrize('answer,period', [('morning','am'),('in the morning','am'),
    ('both in the morning','am'),('yes, in the morning','am'),('afternoon','pm'),
    ('in the afternoon','pm'),('both in the afternoon','pm'),('yes, in the afternoon','pm')])
def test_natural_period_answers_fill_only_omitted_meridiem(answer,period):
    history=[{'role':'user','content':LIVE_TEXT},{'role':'assistant','content':ca.AMPM_QUESTION}]
    query=req(answer,conversation_history=history)
    resolved=ca._resolved_check(query)
    assert resolved[0].clocks==('10 '+period,'10:30 '+period)
    assert ca.eligible_request(query)


@pytest.mark.parametrize('answer', ['Yes', 'Both', 'In the morning with Ada',
    'In the afternoon, but only for30minutes', 'Morning and book them'])
def test_period_answers_cannot_drop_extra_instructions(answer):
    history=[{'role':'user','content':LIVE_TEXT},{'role':'assistant','content':ca.AMPM_QUESTION}]
    assert not ca.eligible_request(req(answer,conversation_history=history))


@pytest.mark.parametrize('original_period,answer', [('am','both in the afternoon'),('am','pm'),
    ('pm','both in the morning'),('pm','yes, in the morning')])
def test_period_clarification_cannot_contradict_original_explicit_time(original_period,answer):
    original=LIVE_TEXT.replace('at 10 and','at 10 '+original_period+' and')
    history=[{'role':'user','content':original},{'role':'assistant','content':ca.AMPM_QUESTION}]
    assert not ca.eligible_request(req(answer,conversation_history=history))
    assert ca._resolved_check(req(answer,conversation_history=history)) is None


def test_period_clarification_preserves_consistent_explicit_time():
    original=LIVE_TEXT.replace('at 10 and','at 10 am and')
    history=[{'role':'user','content':original},{'role':'assistant','content':ca.AMPM_QUESTION}]
    assert ca._resolved_check(req('both in the morning',conversation_history=history))[0].clocks==('10 am','10:30 am')
