"""Legacy proposal compatibility; execution guards live in controller tests."""
import asyncio
import copy
from unittest.mock import AsyncMock,Mock
import pytest
from fastapi import HTTPException
import browser_hand as bh
import chief_errands as ce
import chief_hand_actions as actions

BIZ='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
USER='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
EID='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
QID='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
SPEC={'task':'Find the renewal date on the license lookup page',
      'start_url':'https://licensing.example.gov/lookup','domains':['licensing.example.gov'],'max_steps':6}

def test_legacy_specs_still_round_trip_and_validate():
    spec=bh.make_spec(**SPEC)
    assert bh.spec_from_body(bh.spec_to_body(spec))==spec
    assert bh.spec_from_body('garbage') is None
    with pytest.raises(ValueError): bh.make_spec('too short','http://bad.example')

@pytest.mark.parametrize('field',[{'type':'password'},{'autocomplete':'cc-number'},{'name':'routing_number'},
                                 {'label':'Social Security Number'},{'autocomplete':'one-time-code'}])
def test_shared_credential_detector_is_preserved(field):
    assert bh.forbidden_field(field)

def test_retired_job_never_opens_browser_or_calls_model():
    result=bh.run(BIZ,'old-job',SPEC,open_browser=lambda:pytest.fail('retired browser opened'),
                  ask=lambda *a:pytest.fail('retired model called'))
    assert not result['ok'] and result['stopped']=='retired' and not result['frames']

def test_generic_job_api_cannot_enqueue_the_retired_kind():
    import chief_jobs
    with pytest.raises(ValueError,match='retired'):
        asyncio.run(chief_jobs.enqueue(None,user_id=USER,business_id=BIZ,kind='browser_hand',params={'spec':SPEC}))

def test_use_browser_hand_is_only_a_portal_plan_alias(monkeypatch):
    call=AsyncMock(return_value={'type':'errand_plan'})
    monkeypatch.setattr(actions,'_errand_action',call)
    assert asyncio.run(actions.handle_use_browser_hand(None,{'id':BIZ},SPEC))['type']=='errand_plan'
    assert call.call_args.args[2]['kind']=='portal'
    assert call.call_args.args[3]=='plan'

def test_portal_plan_keeps_queue_semantics_without_starting_work(monkeypatch):
    calls=[]
    def rpc(name,**body):
        calls.append((name,body))
        return {'id':EID,'status':'planned',**body['p_row']}
    monkeypatch.setattr(ce,'rpc',rpc)
    database=Mock(return_value=[{'id':QID}])
    monkeypatch.setattr(ce,'db',database)
    monkeypatch.setattr(ce,'transition',lambda row,expected,patch:{**row,**patch})
    monkeypatch.setattr(ce,'_audit',Mock())
    result=asyncio.run(ce.plan_portal({'id':BIZ,'settings':{}},USER,SPEC))
    assert result['errand']['kind']=='portal' and result['errand']['planned_total_cents']==0
    assert result['queue_id']==QID
    queued=database.call_args.args[2]
    assert queued['channel']=='hand' and queued['status']=='draft'
    assert '\nerrand: '+EID in queued['body']
    assert result['errand']['steps_total_hint']==6
    assert [name for name,_ in calls]==['chief_errand_plan']

def test_portal_extra_host_requires_settings_approval():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ce.plan_portal({'id':BIZ,'settings':{}},USER,{**SPEC,'domains':['outside.example']}))
    assert exc.value.status_code==422

def test_autopilot_cannot_release_hand_queue(monkeypatch):
    import chief_of_staff as cos
    monkeypatch.setattr(cos,'_sb',AsyncMock(side_effect=AssertionError('No queue mutation permitted')))
    result=asyncio.run(cos._do_approve_one(None,{'id':BIZ},{'id':QID,'channel':'hand'}))
    assert not result['ok'] and result['reason']=='hand_approval_required'

def test_real_queue_approval_uses_bound_portal_plan_and_current_actor(monkeypatch):
    row={'id':EID,'business_id':BIZ,'kind':'portal','status':'planned',
         'plan':{'__queue_id':QID,'__legacy_spec':bh.make_spec(**SPEC)}}
    monkeypatch.setattr(ce,'business',lambda bid,user,role:{'id':bid,'settings':{}})
    monkeypatch.setattr(ce,'get_row',lambda eid:copy.deepcopy(row))
    approved=AsyncMock(return_value={**row,'status':'approved','job_id':'fixture-job'})
    monkeypatch.setattr(ce,'approve',approved)
    db=Mock(return_value=[])
    monkeypatch.setattr(ce,'db',db)
    item={'id':QID,'body':bh.spec_to_body(bh.make_spec(**SPEC))+'\nerrand: '+EID}
    result=asyncio.run(ce.approve_portal_queue({'id':BIZ},item,USER))
    assert result['ok'] and result['errand_id']==EID
    assert approved.call_args.args[1].id==USER
    assert db.call_args.args[2]['status']=='approved'
    row['plan']['__queue_id']=USER
    with pytest.raises(HTTPException): asyncio.run(ce.approve_portal_queue({'id':BIZ},item,USER))

def test_the_hand_alias_stays_class_c_and_is_not_external_agent_executable():
    import action_registry
    import mcp_server
    assert action_registry.reversibility('use_browser_hand')=='C'
    assert 'use_browser_hand' not in mcp_server.WRITE_TOOL_SCHEMAS
