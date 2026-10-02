"""Campaign ownership, durable planning, immutable tracking and honest metrics."""
import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import platform_marketing_campaigns as c
import platform_marketing as m
from auth_supabase import require_user
from lead_admin import PLATFORM_OWNER_EMAIL


def run(value):
    return asyncio.run(value)


def brief(**kw):
    today = m.now().date().isoformat()
    return {'objective':'Help solo owners activate a useful trial workflow.', 'audience':'Solo consultants',
        'offer':'Explore the product demo', 'facts':'The system brings client records and invoices together.',
        'starts_on':today,'ends_on':today,'target':10, **kw}


def row(**kw):
    b = c.Brief(**brief()).model_dump(mode='json')
    return {'id':str(uuid4()),'tracking_key':'mc-test','name':'A real workflow','revision':1,
        'brief':b,'brief_hash':m.digest(b),'plan':None,'plan_brief_hash':None,'stage':'planning', **kw}


def plan():
    return {'hypothesis':'A real demo may help owners understand the offer.', 'message':'One useful workflow.',
        'experiment':'Compare two hooks over fourteen days.', 'measurement':'Measure activated trials after connecting attribution.',
        'gaps':['Activation attribution is not yet connected.'], 'deliverables':[
            {'title':f'Demo {i}','format':'short_video','purpose':'Show a real workflow.',
             'direction':'Record a real demo using sample data.','copy':'See the workflow in action.'} for i in range(3)]}


@pytest.fixture
def state(monkeypatch):
    s={'campaign':row(), 'writes':[], 'claim':{'claimed':True,'status':'running'},'metrics_claim':{'claimed':True,'posts':[]}}
    async def db(method,path,body=None):
        if method=='GET':
            if 'platform_marketing_campaigns' in path: return [copy.deepcopy(s['campaign'])] if s['campaign'] else []
            if 'assets' in path: return [{'id':'asset'}]
            return []
        s['writes'].append((method,path,copy.deepcopy(body)))
        if path=='/rpc/platform_marketing_claim_plan': return s['claim']
        if path=='/rpc/platform_marketing_claim_metrics': return s['metrics_claim']
        if 'platform_marketing_campaigns?' in path:
            if f"revision=eq.{s['campaign']['revision']}" not in path: return []
            s['campaign'].update(body)
            return [copy.deepcopy(s['campaign'])]
        return [body]
    monkeypatch.setattr(c,'db',db)
    monkeypatch.setattr(m,'db',db)
    import llm_call, spend_guard
    monkeypatch.setattr(llm_call,'api_key',lambda:'test-key')
    monkeypatch.setattr(spend_guard,'over_budget',lambda:False)
    return s


def client(email):
    app=FastAPI(); app.include_router(c.router)
    if email:
        app.dependency_overrides[require_user]=lambda:SimpleNamespace(id=str(uuid4()),email=email)
    return TestClient(app)


@pytest.mark.parametrize('email',[None,'tenant@example.com'])
def test_every_route_rejects_non_owner(email):
    api=client(email); cid=str(uuid4())
    for method,path in [('GET','/campaigns'),('POST','/campaigns'),('GET',f'/campaigns/{cid}'),
        ('PUT',f'/campaigns/{cid}'),('POST',f'/campaigns/{cid}/plan'),('PATCH',f'/campaigns/{cid}/tasks/{cid}'),
        ('GET','/performance'),('POST','/performance/sync')]:
        assert api.request(method,'/platform/marketing'+path,json={}).status_code in (401,403)


@pytest.mark.parametrize('changes',[{'ends_on':'2000-01-01'}, {'target':0},
    {'landing_url':'https://evil.example/'}, {'facts':' '}, {'evidence':[{'claim':'Evidence claim','url':'javascript:alert(1)','observed_on':'2026-01-01'}]}])
def test_invalid_briefs_rejected(changes):
    with pytest.raises(ValidationError): c.Brief(**brief(**changes))


def test_stale_edit_cannot_overwrite(state):
    state['campaign']['revision']=2
    req=c.CampaignEdit(revision=1,name='Changed',brief=c.Brief(**brief()))
    with pytest.raises(HTTPException) as error:
        run(c.edit_campaign(state['campaign']['id'],req,SimpleNamespace(id=uuid4())))
    assert error.value.status_code==409 and state['campaign']['name']=='A real workflow'


def test_brief_edit_invalidates_plan_without_changing_tracking(state):
    state['campaign'].update(plan=plan(),plan_brief_hash=state['campaign']['brief_hash'])
    req=c.CampaignEdit(revision=1,name='New display name',brief=c.Brief(**brief(audience='Small agencies')))
    saved=run(c.edit_campaign(state['campaign']['id'],req,SimpleNamespace(id=uuid4())))
    assert saved['tracking_key']=='mc-test' and saved['plan_brief_hash']!=saved['brief_hash']


def test_plan_is_proposal_only_and_records_success(state,monkeypatch):
    async def generate(_): return plan()
    monkeypatch.setattr(c,'generate_strategy',generate)
    req=c.PlanRequest(revision=1,request_id=uuid4())
    saved=run(c.plan_campaign(state['campaign']['id'],req,SimpleNamespace(id=uuid4())))
    assert saved['stage']=='planning' and saved['revision']==2
    assert all(t['status']=='planned' for t in saved['plan']['deliverables'])
    assert not any('/platform_marketing_posts' in w[1] or '/approve' in w[1] for w in state['writes'])
    assert state['writes'][-1][2]['status']=='succeeded'


def test_replayed_inflight_request_never_repeats_paid_call(state,monkeypatch):
    state['claim']={'claimed':False,'status':'running'}
    async def forbidden(_): pytest.fail('Paid generation repeated')
    monkeypatch.setattr(c,'generate_strategy',forbidden)
    with pytest.raises(HTTPException) as error:
        run(c.plan_campaign(state['campaign']['id'],c.PlanRequest(revision=1,request_id=uuid4()),SimpleNamespace(id=uuid4())))
    assert error.value.status_code==409


def test_edit_during_generation_preserves_new_brief(state,monkeypatch):
    async def generate(_):
        state['campaign'].update(revision=2,name='Edited while Chief worked')
        return plan()
    monkeypatch.setattr(c,'generate_strategy',generate)
    with pytest.raises(HTTPException):
        run(c.plan_campaign(state['campaign']['id'],c.PlanRequest(revision=1,request_id=uuid4()),SimpleNamespace(id=uuid4())))
    assert state['campaign']['name']=='Edited while Chief worked' and not state['campaign']['plan']
    assert state['writes'][-1][2]['status']=='failed'


def test_metric_totals_exclude_missing_errors_nonadditive_and_foreign_posts():
    posts=[{'id':'a','status':'published'},{'id':'b','status':'published'}]
    metric=lambda kind,value,unit='count': {'type':kind,'value':value,'unit':unit}
    result=c.performance(posts,[{'post_id':'a','metrics':[metric('impressions',12),metric('reactions',0),metric('reach',9),metric('engagementRate',10,'percentage')]},
        {'post_id':'b','error':'unavailable','metrics':[metric('impressions',300)]},
        {'post_id':'other','metrics':[metric('impressions',500)]}])
    assert result['totals']['impressions']=={'value':12,'covered_posts':1,'published_posts':2}
    assert result['totals']['comments']['value'] is None
    assert result['totals']['reactions']['value']==0
    assert 'reach' not in result['totals'] and result['customer_outcomes'] is None


def test_metrics_validate_provider_and_channel_identity(state,monkeypatch):
    monkeypatch.setenv('BUFFER_API_KEY','test')
    state['metrics_claim']['posts']=[{'id':str(uuid4()),'provider_id':'buffer-one','payload':{'channel_id':'chosen'}}]
    async def metrics(_self,_ids):
        return {'p0':{'id':'buffer-one','channelId':'wrong','metrics':[{'type':'impressions','value':999,'unit':'count'}]}}
    monkeypatch.setattr(c.BufferClient,'metrics',metrics)
    with pytest.raises(HTTPException): run(c.sync_metrics())
    stored=next(w[2]['items'][0] for w in state['writes'] if w[1]=='/rpc/platform_marketing_store_metrics')
    assert stored['error'] and stored['metrics']==[]


def test_metric_sync_respects_durable_cooldown(state,monkeypatch):
    monkeypatch.setenv('BUFFER_API_KEY','test')
    state['metrics_claim']={'claimed':False,'posts':[]}
    assert run(c.sync_metrics())['deferred']
    assert len(state['writes'])==1


def test_provider_outage_marks_rows_unavailable_without_erasing_values(state,monkeypatch):
    monkeypatch.setenv('BUFFER_API_KEY','test')
    state['metrics_claim']['posts']=[{'id':str(uuid4()),'provider_id':'buffer-one','payload':{'channel_id':'chosen'}}]
    async def unavailable(_self,_ids): raise c.BufferError('Unavailable')
    monkeypatch.setattr(c.BufferClient,'metrics',unavailable)
    with pytest.raises(HTTPException): run(c.sync_metrics())
    stored=next(w[2]['items'][0] for w in state['writes'] if w[1]=='/rpc/platform_marketing_store_metrics')
    assert stored['error'] and stored['provider_id']=='buffer-one'


def test_linked_week_preserves_campaign_on_all_drafts(state,monkeypatch):
    import json, httpx, llm_call, rate_limit
    monkeypatch.setattr(rate_limit,'allow',lambda *_:True)
    async def config(): return {'organization_id':'org','channels':[{'id':'channel','name':'Owner','service':'facebook'}]}
    monkeypatch.setattr(m,'config',config)
    async def generate(*_args,**_kwargs):
        return httpx.Response(200,request=httpx.Request('POST','https://example.test'),json={
            'content':[{'type':'text','text':json.dumps({'captions':['Review this useful workflow.']*7})}]})
    monkeypatch.setattr(llm_call,'apost',generate)
    req=m.Week(id=uuid4(),campaign_id=state['campaign']['id'],campaign='mc-test',audience='Solo owners',
        facts='Client records and invoices live together.',offer='Explore the demo',channel_id='channel',start_at=m.now()+timedelta(days=1))
    run(m.draft_week(req,SimpleNamespace(id=uuid4())))
    rows=next(w[2] for w in state['writes'] if w[1]=='/platform_marketing_posts')
    assert len(rows)==7 and all(r['campaign_id']==state['campaign']['id'] for r in rows)


def test_linked_post_uses_permanent_tracking_and_still_needs_review(state,monkeypatch):
    async def config():
        return {'organization_id':'org','channels':[{'id':'channel','name':'Owner','service':'facebook'}]}
    monkeypatch.setattr(m,'config',config)
    req=m.Draft(campaign_id=state['campaign']['id'],campaign='mc-test',text='See the real workflow.',
        channel_id='channel',run_at=m.now()+timedelta(days=1))
    saved=run(m.build_draft(req))
    assert saved['campaign_id']==state['campaign']['id'] and 'utm_campaign=mc-test' in saved['payload']['tracked_url']
    assert 'approved_by' not in saved
    with pytest.raises(HTTPException): run(m.build_draft(req.model_copy(update={'campaign':'renamed'})))
