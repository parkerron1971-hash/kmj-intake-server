"""No provider calls: exercise the owner/device/report boundaries and campaign handoff."""
import asyncio
import copy
from types import SimpleNamespace
from uuid import UUID, uuid4
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from auth_supabase import require_user
from lead_admin import PLATFORM_OWNER_EMAIL
import chief_local_work as w
import dev_bridge as b
from __tests__.test_marketing_campaigns import row, plan

def run(value): return asyncio.run(value)

@pytest.fixture
def state(monkeypatch):
    s=SimpleNamespace(owner=SimpleNamespace(id=str(uuid4()),email=PLATFORM_OWNER_EMAIL),works={},tasks={},calls=[],campaign=row())
    async def db(method,path,body=None):
        s.calls.append((method,path,copy.deepcopy(body)))
        if path=='/rpc/chief_work_create':
            work=copy.deepcopy(body['work']); task=copy.deepcopy(body['task']); key=work['id']
            s.works[key]={**work,'device_id':None,'result':None,'result_version':0}
            s.tasks[key]={**task,'id':key,'status':'queued'}
            return key
        if path=='/rpc/chief_work_note':
            t=s.tasks[body['task_id']]
            if not any(n.get('id')==body['note'].get('id') for n in t['notes']): t['notes'].append(copy.deepcopy(body['note']))
            return True
        if path=='/rpc/chief_work_claim': return getattr(s,'claim',False)
        parsed=urlsplit(path); query=parse_qs(parsed.query)
        table=s.works if parsed.path=='/platform_chief_work' else s.tasks
        values=list(table.values())
        for k,v in query.items():
            if v[0].startswith('eq.'): values=[x for x in values if str(x.get(k))==v[0][3:]]
        if method=='PATCH':
            for v in values: v.update(copy.deepcopy(body))
        return copy.deepcopy(values)
    async def campaign(_id): return copy.deepcopy(s.campaign)
    async def update(_id,revision,fields,owner):
        assert revision==s.campaign['revision']
        s.campaign.update(copy.deepcopy(fields)); s.campaign['revision']+=1
        return copy.deepcopy(s.campaign)
    monkeypatch.setattr(w,'db',db); monkeypatch.setattr(w.campaigns,'get_campaign',campaign); monkeypatch.setattr(w.campaigns,'update',update)
    return s

def start(s,agent='codex',**extra):
    return run(w.start(w.WorkRequest(id=uuid4(),agent=agent,message='Build a useful draft',**extra),s.owner))

@pytest.mark.parametrize('email',[None,'tenant@example.com'])
def test_all_owner_routes_reject_unauthorized(email):
    app=FastAPI(); app.include_router(w.router)
    if email: app.dependency_overrides[require_user]=lambda:SimpleNamespace(id=str(uuid4()),email=email)
    api=TestClient(app); key=str(uuid4())
    for method,path in [('GET',''),('POST',''),('GET',f'/{key}'),('POST',f'/{key}/reply'),('POST',f'/{key}/apply-plan')]:
        assert api.request(method,'/platform/chief/work'+path,json={}).status_code in (401,403)

@pytest.mark.parametrize('agent',['codex','claude'])
def test_start_pins_agent_scope_and_hides_report_credentials(state,agent):
    result=start(state,agent); task=state.tasks[result['task']['id']]
    assert task['agent']==agent and task['authority_record']['scope']['account_mode']=='subscription'
    assert result['task']['notes'][0]['text']=='Build a useful draft'
    assert 'report_key' not in result['task'] and 'authority_record' not in result['task']
    assert 'Do not publish' in task['details']
    req=w.WorkRequest(id=task['id'],agent=agent,message='Build a useful draft')
    assert run(w.start(req,state.owner))['task']['id']==task['id']
    assert len([c for c in state.calls if c[1]=='/rpc/chief_work_create'])==1
    with pytest.raises(HTTPException) as e: run(w.start(req.model_copy(update={'message':'Changed request'}),state.owner))
    assert e.value.status_code==409

def test_cross_owner_cannot_read_or_reply(state):
    result=start(state); other=SimpleNamespace(id=str(uuid4()))
    with pytest.raises(HTTPException) as e: run(w.detail(UUID(result['task']['id']),other))
    assert e.value.status_code==404

def test_campaign_revision_checked_before_start(state):
    with pytest.raises(HTTPException) as e: start(state,campaign_id=state.campaign['id'],campaign_revision=2,purpose='strategy')
    assert e.value.status_code==409 and not state.tasks

def test_result_validation_and_reviewed_plan_idempotency(state):
    detail=start(state,campaign_id=state.campaign['id'],campaign_revision=1,purpose='strategy')
    key=detail['task']['id']; task=state.tasks[key]
    with pytest.raises(HTTPException) as e: run(w.save_result(task,{'plan':{}}))
    assert e.value.status_code==422
    result={'summary':'Prepared coordinated drafts.','plan':plan()}
    run(w.save_result(task,result)); run(w.save_result(task,result))
    assert state.works[key]['result_version']==1 and state.campaign['plan'] is None
    applied=run(w.apply_plan(UUID(key),w.Apply(revision=1,result_version=1),state.owner))
    assert len(applied['plan']['deliverables'])==3
    assert all(x['status']=='planned' and x['asset_id'] is None for x in applied['plan']['deliverables'])
    assert run(w.apply_plan(UUID(key),w.Apply(revision=1,result_version=1),state.owner))==applied

@pytest.mark.parametrize('change',['revision','brief_hash','stage','result_version'])
def test_stale_campaign_or_result_cannot_apply(state,change):
    detail=start(state,campaign_id=state.campaign['id'],campaign_revision=1,purpose='strategy'); key=detail['task']['id']
    run(w.save_result(state.tasks[key],{'summary':'Draft only','plan':plan()}))
    if change=='result_version': state.works[key][change]=2
    else: state.campaign[change]={'revision':2,'brief_hash':'changed','stage':'archived'}[change]
    with pytest.raises(HTTPException) as e: run(w.apply_plan(UUID(key),w.Apply(revision=1,result_version=1),state.owner))
    assert e.value.status_code==409 and state.campaign['plan'] is None

def test_atomic_reply_has_retry_identity(state):
    key=start(state)['task']['id']; req=w.Reply(id=uuid4(),text='Use this direction')
    run(w.reply(UUID(key),req,state.owner)); run(w.reply(UUID(key),req,state.owner))
    assert len(state.tasks[key]['notes'])==2

def test_device_must_own_claim(state):
    key=start(state)['task']['id']; task=state.tasks[key]; device={'id':str(uuid4())}
    with pytest.raises(HTTPException) as e: run(b._bound_work(task,device))
    assert e.value.status_code==409
    state.works[key]['device_id']=device['id']; run(b._bound_work(task,device))

def test_old_desktop_does_not_receive_subscription_work(state,monkeypatch):
    key=start(state)['task']['id']; task={**state.tasks[key],'lane':'local','created_at':'now'}
    async def device(*_): return {'id':str(uuid4())}
    async def rows(_c,_table,params): return [task] if params.get('status')=='eq.queued' else []
    monkeypatch.setattr(b,'_require_device',device); monkeypatch.setattr(b,'_sb_get',rows)
    assert run(b.bridge_queue(authorization='Bearer test',agents='codex,claude'))['tasks']==[]
    delivered=run(b.bridge_queue(authorization='Bearer test',agents='codex,claude',capabilities='workbench-v1'))['tasks']
    assert delivered[0]['agent']=='codex' and delivered[0]['account_mode']=='subscription'
    assert 'work_result' in delivered[0]['prompt']

def test_report_key_required_before_storing_result(state,monkeypatch):
    key=start(state)['task']['id']; task=state.tasks[key]
    async def get(*_): return task
    monkeypatch.setattr(b,'_get_task',get)
    with pytest.raises(HTTPException) as e:
        run(b.bridge_report(key,b.ReportBody(key='wrong',status='done',work_result={'summary':'wrong'})))
    assert e.value.status_code==401 and state.works[key]['result'] is None
