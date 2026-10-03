"""Read-only appointment checks: clear language, full current evidence, joint capacity."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import pytest
import chief_availability as ca

BID = '11111111-1111-4111-8111-111111111111'
OWNER = '22222222-2222-4222-8222-222222222222'
SID = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'
NOW = datetime(2030, 1, 7, 12, tzinfo=timezone.utc)
HOURS = {'timezone': 'America/New_York', 'weekly': {'tue': [{'start':'09:00','end':'17:00'}]}, 'slot_granularity_min':30}
BIZ = {'id':BID, 'owner_id':OWNER, 'settings':{'availability':HOURS}}
SERVICE = {'id':SID, 'business_id':BID, 'name':'Consultation', 'is_active':True, 'duration_min':60}
TEXT = ("Check whether two consultation appointments would fit next Tuesday at 10:00 and 10:30 a.m., using my business timezone. "
        "Check them together against my existing bookings and capacity. Suggest alternatives if they conflict. Don't book or change anything.")
SPOKEN = ("to see if I have uh two consultation appointments that I can fit in next week on Tuesday, one at 10, the other one at 10:30, "
          "and uh use them, of course, my time zone, and then check them again together against my existing booking and capacity, "
          "and suggest alternatives if they conflict. Don't change anything, just share that with me.")


def req(text=TEXT, **kwargs):
    return SimpleNamespace(message=text, business_id=BID, **kwargs)


def fixture(monkeypatch, *, biz=None, offerings=None, bookings=None, busy=None):
    tables={'/businesses':[deepcopy(biz or BIZ)], '/offerings':deepcopy(offerings if offerings is not None else [SERVICE]),
            '/module_entries':deepcopy(bookings or []), '/calendar_busy_blocks':deepcopy(busy or []),
            '/practitioner_profiles':[{'timezone':'America/New_York'}]}
    calls=[]
    async def read(client, method, path, body=None):
        assert method=='GET' and body is None
        url=urlsplit(path); query=parse_qs(url.query)
        assert query.get('business_id',query.get('id',query.get('owner_id'))) in (['eq.'+BID],['eq.'+OWNER])
        if url.path == '/module_entries':
            assert 'duration_min' not in query.get('select',[''])[0].split(',')
            assert 'duration_min_at_booking' in query['select'][0].split(',')
        calls.append(path)
        offset=int(query.get('offset',['0'])[0])
        return deepcopy(tables[url.path][offset:offset+100])
    monkeypatch.setattr(ca,'_sb',read)
    return calls,tables


def run(query=None, **kwargs):
    return asyncio.run(ca.check_request(None,query or req(),BIZ,now=NOW,**kwargs))


def test_exact_typed_and_filler_request_parse_and_ambiguous_speech_clarifies(monkeypatch):
    assert ca.recognizes_request(TEXT) and ca.recognizes_request(SPOKEN)
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    result=run(req(SPOKEN))
    assert result['response']==ca.AMPM_QUESTION
    spy.assert_not_awaited()


def test_joint_capacity_conflict_returns_natural_read_only_answer(monkeypatch):
    calls,_=fixture(monkeypatch)
    result=run()
    checked=result['availability_check']
    assert checked['status']=='conflicts'
    assert [a['status'] for a in checked['appointments']]==['fits','conflict']
    assert checked['date']=='2030-01-08'
    assert checked['appointments'][1]['alternatives'][0]=='2030-01-08T16:00:00+00:00'
    assert result['actions_taken']==[]
    assert 'Nothing is booked or changed.' in result['response']
    assert 'America/New_York' not in result['response']
    assert {urlsplit(c).path for c in calls}=={'/businesses','/offerings','/module_entries','/calendar_busy_blocks'}


def booking(start='2030-01-08T15:00:00Z', **changes):
    return {'id':'booking1','business_id':BID,'status':'active','appointment_at':start,'duration_min_at_booking':60,**changes}


def test_shared_capacity_includes_existing_booking_and_both_proposals(monkeypatch):
    biz=deepcopy(BIZ);biz['settings']['availability']['concurrent_capacity']=2
    fixture(monkeypatch,biz=biz,bookings=[booking()])
    assert [a['status'] for a in run()['availability_check']['appointments']]==['fits','conflict']


def test_nonappointment_product_does_not_block_consultation(monkeypatch):
    fixture(monkeypatch, offerings=[SERVICE,{**SERVICE,'id':OTHER,'name':'Workbook','duration_min':None}])
    assert run()['availability_check']['status']=='conflicts'


@pytest.mark.parametrize('offerings', [[SERVICE,{**SERVICE,'id':OTHER}],
    [{**SERVICE,'name':'Initial Consultation'},{**SERVICE,'id':OTHER,'name':'Followup Consultation'}]])
def test_ambiguous_services_require_choice_not_first_row(monkeypatch,offerings):
    fixture(monkeypatch,offerings=offerings)
    assert run()['availability_check']['status']=='clarification'


def test_prepared_search_rechecks_duration_and_current_matching_names(monkeypatch):
    calls,_=fixture(monkeypatch,offerings=[{**SERVICE,'duration_min':30}])
    snapshot={'business_id':BID,'captured_at':NOW.isoformat(),'offerings':[SERVICE]}
    result=run(prepared=snapshot)
    assert result['availability_check']['status']=='fits'
    assert result['availability_check']['appointments'][0]['duration_min']==30
    assert any('or=(name.ilike.*consultation*,id.in.' in p for p in calls)
    fixture(monkeypatch,offerings=[SERVICE,{**SERVICE,'id':OTHER}])
    assert run(prepared=snapshot)['availability_check']['status']=='clarification'


@pytest.mark.parametrize('snapshot', [
    {'business_id':OTHER,'captured_at':NOW.isoformat(),'offerings':[SERVICE]},
    {'business_id':BID,'captured_at':'2020-01-01T00:00:00Z','offerings':[SERVICE]},
    {'business_id':BID,'captured_at':NOW.isoformat(),'offerings':'bad'},
])
def test_bad_prepared_snapshot_falls_back_to_fresh_catalog(monkeypatch,snapshot):
    calls,_=fixture(monkeypatch)
    assert run(prepared=snapshot)['availability_check']['status']=='conflicts'
    assert not any('&or=' in p for p in calls)


def test_outside_calendar_busy_blocks_all_shared_capacity(monkeypatch):
    biz=deepcopy(BIZ);biz['settings']['availability']['concurrent_capacity']=3
    fixture(monkeypatch,biz=biz,busy=[{'id':'busy1','business_id':BID,'starts_at':'2030-01-08T15:00:00Z','ends_at':'2030-01-08T17:00:00Z'}])
    assert [a['status'] for a in run()['availability_check']['appointments']]==['conflict','conflict']


@pytest.mark.parametrize('change', [{'lead_time_min':10000}, {'blocks':[{'start':'2030-01-08','end':'2030-01-08'}]},
                                   {'overrides':[{'date':'2030-01-08','hours':[]}]}])
def test_canonical_rules_are_preserved(monkeypatch,change):
    biz=deepcopy(BIZ);biz['settings']['availability'].update(change)
    fixture(monkeypatch,biz=biz)
    assert all(a['status']=='conflict' for a in run()['availability_check']['appointments'])


@pytest.mark.parametrize('change', [{'timezone':'bad/timezone'},{'concurrent_capacity':'bad'},
    {'weekly':{'tue':[{'start':'17:00','end':'09:00'}]}},{'overrides':[{'date':'2030-99-99','hours':[]}]}])
def test_invalid_saved_rules_never_mean_free(monkeypatch,change):
    biz=deepcopy(BIZ);biz['settings']['availability'].update(change)
    fixture(monkeypatch,biz=biz)
    assert run()['availability_check']['status']=='unavailable'


@pytest.mark.parametrize('row', [booking(duration_min_at_booking=None), booking(appointment_at='bad'),booking(business_id=OTHER)])
def test_bad_occupancy_never_reports_fit(monkeypatch,row):
    fixture(monkeypatch,bookings=[row])
    assert run()['availability_check']['status']=='unavailable'


@pytest.mark.parametrize('extra', [' Send reminders too.', ' Only with Ada.', ' Exclude my existing bookings.',
                                  ' Then book them.', ' And check Acme invoices.'])
def test_mixed_or_unsupported_constraints_are_not_consumed(monkeypatch,extra):
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    assert run(req(TEXT+extra)) is None
    spy.assert_not_awaited()


def test_inherited_scheduling_constraint_defers(monkeypatch):
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    history=[{'role':'user','content':'Only schedule with Ada.'}]
    assert run(req(conversation_history=history)) is None
    spy.assert_not_awaited()


def test_exact_meridiem_followup_preserves_original_request(monkeypatch):
    fixture(monkeypatch)
    history=[{'role':'user','content':SPOKEN},{'role':'assistant','content':ca.AMPM_QUESTION}]
    query=req('a.m.',conversation_history=history)
    assert ca.request_shape(query)
    result=run(query)
    assert result['availability_check']['date']=='2030-01-15'  # next week, not tomorrow
    assert result['availability_check']['status']=='conflicts'


@pytest.mark.parametrize('history', [[],[{'role':'user','content':SPOKEN},{'role':'assistant','content':'Morning?'}]])
def test_meridiem_without_exact_question_does_not_reconstruct(monkeypatch,history):
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    assert run(req('am',conversation_history=history)) is None
    spy.assert_not_awaited()


def test_next_tuesday_uses_business_calendar_date_and_is_strictly_future():
    from zoneinfo import ZoneInfo
    # Already Tuesday in UTC, still Monday in California.
    now=datetime(2030,1,8,1,tzinfo=timezone.utc)
    assert ca.resolve_day('next tuesday',now,ZoneInfo('America/Los_Angeles')).isoformat()=='2030-01-08'
    assert ca.resolve_day('next tuesday',now,ZoneInfo('UTC')).isoformat()=='2030-01-15'
    assert ca.resolve_day('next week on tuesday',now,ZoneInfo('America/Los_Angeles')).isoformat()=='2030-01-15'


def test_missing_timezone_is_explicit_not_utc_guess(monkeypatch):
    biz=deepcopy(BIZ);biz['settings']['availability'].pop('timezone')
    _,tables=fixture(monkeypatch,biz=biz);tables['/practitioner_profiles']=[]
    assert run()['availability_check']['status']=='unavailable'


def test_timeout_cancels_reads_and_never_claims_checked(monkeypatch):
    active=set()
    async def slow(*args):
        active.add('read')
        try: await asyncio.sleep(1)
        finally: active.clear()
    monkeypatch.setattr(ca,'_sb',slow);monkeypatch.setattr(ca,'CHECK_BUDGET_S',0.01)
    result=run()
    assert result['availability_check']['status']=='unavailable' and 'not been checked' in result['response']
    assert not active


def test_rollback_switch_prevents_lookup(monkeypatch):
    monkeypatch.setenv('CHIEF_AVAILABILITY_CHECK','off')
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    assert not ca.request_shape(req()) and run() is None
    spy.assert_not_awaited()


@pytest.mark.parametrize('prior', ['Use a 90-minute duration.', 'Leave 30 minutes between sessions.',
    'I cannot do mornings.', 'Make it virtual.', 'Use Pacific time.', 'Only Acme.',
    'Avoid the same provider.', 'Budget three hours for these.'])
def test_unrecognized_prior_constraints_keep_full_context(monkeypatch,prior):
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    assert run(req(conversation_history=[{'role':'user','content':prior}])) is None
    spy.assert_not_awaited()


def test_complete_prior_invoice_display_is_independent(monkeypatch):
    fixture(monkeypatch)
    result=run(req(conversation_history=[{'role':'user','content':'Show all invoices'}]))
    assert result['availability_check']['status']=='conflicts'


@pytest.mark.parametrize('day,clock', [('2030-11-03','1:30 am'),('2030-03-10','2:30 am')])
def test_dst_ambiguous_and_nonexistent_local_times_are_not_certified(day,clock):
    from zoneinfo import ZoneInfo
    from datetime import date
    av,_=ca._settings({**HOURS,'weekly':{'sun':[{'start':'00:00','end':'05:00'}]}})
    result=ca.evaluate(day=date.fromisoformat(day),clocks=ca.resolve_clocks([clock]),service=SERVICE,
        business_id=BID,availability=av,tz=ZoneInfo('America/New_York'),bookings=[],busy=[],now=NOW)
    assert result['availability_check']['status']=='clarification'


def test_failed_parallel_read_cancels_siblings_before_reply(monkeypatch):
    original_calls,tables=fixture(monkeypatch)
    original=ca._sb
    active=set(); started=asyncio.Event()
    async def reader(client,method,path,body=None):
        if path.startswith('/module_entries?'):
            await started.wait()
            raise RuntimeError('read failed')
        if path.startswith('/calendar_busy_blocks?'):
            active.add('calendar'); started.set()
            try: await asyncio.sleep(1)
            finally: active.remove('calendar')
        return await original(client,method,path,body)
    monkeypatch.setattr(ca,'_sb',reader)
    result=run()
    assert result['availability_check']['status']=='unavailable'
    assert 'not been checked' in result['response'] and not active


@pytest.mark.parametrize('lead', ["Okay, I'll check that. ", "Sure. ", "Let me check those times.\n\n", ""])
def test_exact_question_with_safe_opener_accepts_morning_followup(monkeypatch,lead):
    fixture(monkeypatch)
    history=[{'role':'user','content':SPOKEN},{'role':'assistant','content':lead+ca.AMPM_QUESTION}]
    query=req('in the morning',conversation_history=history)
    assert ca.request_shape(query)
    assert run(query)['availability_check']['appointments'][0]['start'].endswith('15:00:00+00:00')


@pytest.mark.parametrize('lead', ['Only with Ada. ', 'Use a90-minute service. ', 'Those times are free. ', 'Which provider? '])
def test_arbitrary_preceding_facts_or_constraints_are_not_stripped(lead):
    history=[{'role':'user','content':SPOKEN},{'role':'assistant','content':lead+ca.AMPM_QUESTION}]
    assert ca._followup(req('am',conversation_history=history)) is None


def test_service_choice_rechecks_fresh_offering_with_original_date_and_joint_capacity(monkeypatch):
    services=[{**SERVICE,'name':'Free Consultation'},{**SERVICE,'id':OTHER,'name':'Initial Consultation'}]
    fixture(monkeypatch,offerings=services)
    question=run()['response']
    history=[{'role':'user','content':TEXT},{'role':'assistant','content':question}]
    query=req('Free Consultation',conversation_history=history)
    assert ca.eligible_request(query) and ca.request_shape(query)
    result=run(query)
    assert result['availability_check']['offering_id']==SID
    assert result['availability_check']['date']=='2030-01-08'
    assert [a['status'] for a in result['availability_check']['appointments']]==['fits','conflict']


def test_meridiem_then_service_choice_keeps_entire_original_check(monkeypatch):
    services=[{**SERVICE,'name':'Free Consultation'},{**SERVICE,'id':OTHER,'name':'Initial Consultation'}]
    fixture(monkeypatch,offerings=services)
    history=[{'role':'user','content':SPOKEN},{'role':'assistant','content':ca.AMPM_QUESTION}]
    question=run(req('in the morning',conversation_history=history))['response']
    history += [{'role':'user','content':'in the morning'},{'role':'assistant','content':question}]
    result=run(req('Free Consultation',conversation_history=history))
    assert result['availability_check']['offering_id']==SID
    assert result['availability_check']['date']=='2030-01-15'


@pytest.mark.parametrize('answer', ['The first one', 'Free Consultation and book it', 'Free Consultation with Ada'])
def test_service_selection_does_not_infer_or_drop_extra_instructions(monkeypatch,answer):
    spy=AsyncMock();monkeypatch.setattr(ca,'_sb',spy)
    question='Which service do you mean: Free Consultation (60 minutes), Initial Consultation (60 minutes)?'
    query=req(answer,conversation_history=[{'role':'user','content':TEXT},{'role':'assistant','content':question}])
    assert not ca.eligible_request(query) and run(query) is None
    spy.assert_not_awaited()
