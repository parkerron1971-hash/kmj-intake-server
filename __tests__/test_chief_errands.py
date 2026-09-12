import asyncio
import copy
from datetime import datetime, timedelta, timezone
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

import chief_errands as ce
import chief_jobs
import sb_clients
import business_access
from access_log_redaction import RedactCredentialPaths, scrub_sentry_event

BID='00000000-0000-4000-8000-000000000001'
UID='00000000-0000-4000-8000-000000000002'
EID='00000000-0000-4000-8000-000000000003'
SID='00000000-0000-4000-8000-000000000004'
JOB='00000000-0000-4000-8000-000000000005'


@pytest.fixture
def api(monkeypatch):
    row={'id':EID,'business_id':BID,'user_id':UID,'kind':'reorder','title':'Test reorder','status':'planned',
        'plan':{'items':[],'__start_url':'https://supplier.test/private'},'hosts':['supplier.test'],
        'spend_limit_cents':15000,'planned_total_cents':200,'hold':None}
    biz={'id':BID,'name':'Test business','settings':{}}
    state={'row':row,'role':'owner','biz':biz,'db':[],'stepup':[]}
    monkeypatch.setattr(ce,'get_row',lambda eid:copy.deepcopy(row) if eid==EID else (_ for _ in ()).throw(HTTPException(404)))
    monkeypatch.setattr(sb_clients,'sb_get_as_service',lambda path:[{'id':BID}] if BID in path else [])
    monkeypatch.setattr(business_access,'_resolve_role',lambda bid,user:state['role'] if bid==BID else None)
    def database(method,path,body=None):
        state['db'].append((method,path,body))
        if path.startswith('/businesses?'):
            return [copy.deepcopy(biz)]
        if path.startswith('/business_secrets?'):
            return [{'id':SID,'business_id':BID,'host':'supplier.test','kind':'login',
                     'label':'Supplier login','display':{'username_hint':'••••'},'status':'active'}]
        if path.startswith('/chief_errand_events?'):
            return []
        if path.startswith('/chief_errands?'):
            return [copy.deepcopy(row)]
        return None
    monkeypatch.setattr(ce,'db',database)
    def unlock(request,user,scope):
        state['stepup'].append(scope)
        if request.headers.get('X-Ledger-Unlock')!='fixture-stepup':
            raise HTTPException(403,{'code':'ledger_locked','scope':scope})
    monkeypatch.setattr(ce,'require_unlock',unlock)
    monkeypatch.setattr(ce,'send_command',AsyncMock(return_value='filled'))
    monkeypatch.setattr(ce,'transition',Mock(side_effect=lambda r,e,p,*a,**k: {**r,**p}))
    monkeypatch.setattr(ce,'rpc',Mock(return_value={'errand':{**row,'status':'approved'},'job':{'id':JOB}}))
    monkeypatch.setattr(chief_jobs,'enqueue',AsyncMock(return_value={'id':JOB}))
    monkeypatch.setenv('ERRANDS_ENABLED','on')
    ce._attempts.clear()
    app=FastAPI()
    app.include_router(ce.router)
    app.dependency_overrides[sb_clients.authed_request]=lambda:SimpleNamespace(user=SimpleNamespace(id=UID))
    with TestClient(app) as client:
        yield client,state


def hold(state,kind='login',hold_kind='secret'):
    state['row'].update(status='needs_you',hold={'id':'hold-1','kind':hold_kind,'field_kind':kind,
        'host':'supplier.test','observed_total_cents':200,
        'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()})


@pytest.mark.parametrize('role,allowed',[('owner',True),('admin',True),('manager',True),('member',False),('viewer',False),(None,False)])
def test_approval_role_boundary(api,role,allowed):
    client,state=api
    state['role']=role
    response=client.post(f'/agents/chief/errands/{EID}/approve',json={})
    assert response.status_code==(200 if allowed else 404)
    if not allowed:
        chief_jobs.enqueue.assert_not_called()


@pytest.mark.parametrize('total,unpriced,required',[(None,True,True),(None,False,False),(0,True,False),(15000,True,False),(15001,True,True)])
def test_stepup_matrix(api,total,unpriced,required):
    client,state=api
    state['row']['planned_total_cents']=total
    state['biz']['settings']={'computer':{'require_stepup_unpriced':unpriced}}
    response=client.post(f'/agents/chief/errands/{EID}/approve',json={})
    assert response.status_code==(403 if required else 200)
    if required:
        assert response.json()['detail']['code']=='ledger_locked'
        response=client.post(f'/agents/chief/errands/{EID}/approve',json={},headers={'X-Ledger-Unlock':'fixture-stepup'})
        assert response.status_code==200


def test_lowered_settings_limit_applies_to_existing_plan(api):
    client,state=api
    state['biz']['settings']={'computer':{'spend_limit_cents':100}}
    assert client.post(f'/agents/chief/errands/{EID}/approve',json={}).status_code==403


def test_plan_is_saved_when_execution_disabled(api,monkeypatch):
    client,state=api
    monkeypatch.setenv('ERRANDS_ENABLED','off')
    assert client.post(f'/agents/chief/errands/{EID}/approve',json={}).status_code==503
    chief_jobs.enqueue.assert_not_called()


def test_pause_preserves_hold_and_stop_needs_no_stepup(api):
    client,state=api
    hold(state)
    response=client.post(f'/agents/chief/errands/{EID}/pause',json={})
    assert response.status_code==200
    assert response.json()['errand']['hold']['id']=='hold-1'
    response=client.post(f'/agents/chief/errands/{EID}/stop',json={})
    assert response.status_code==200
    assert response.json()['errand']['hold'] is None
    assert not state['stepup']


def test_resume_cannot_bypass_pending_secure_entry(api):
    client,state=api
    hold(state)
    state['row']['status']='paused'
    ce.register_worker(EID)
    try:
        response=client.post(f'/agents/chief/errands/{EID}/resume',json={})
        assert response.status_code==200
        assert response.json()['errand']['status']=='needs_you'
    finally:
        ce.unregister_worker(EID)


def test_secret_path_only_dispatches_matching_live_hold(api):
    client,state=api
    hold(state)
    fields={'username':'NEVER-LOG-USER','password':'NEVER-LOG-PASSWORD'}
    path=f'/agents/chief/errands/{EID}/secret'
    assert client.post(path,json={'hold_id':'other','fields':fields}).status_code==409
    response=client.post(path,json={'hold_id':'hold-1','fields':fields})
    assert response.status_code==200 and response.json()=={'ok':True}
    assert 'NEVER-LOG' not in response.text
    command=ce.send_command.call_args.args[1]
    assert command.fields==fields
    assert 'NEVER-LOG' not in repr(command)
    assert not any('NEVER-LOG' in str(call) for call in state['db'])


def test_saved_login_reuse_requires_stepup_but_does_not_decrypt_in_api(api):
    client,state=api
    hold(state)
    path=f'/agents/chief/errands/{EID}/secret'
    body={'hold_id':'hold-1','use_saved':SID}
    assert client.post(path,json=body).status_code==403
    assert client.post(path,json=body,headers={'X-Ledger-Unlock':'fixture-stepup'}).status_code==200
    assert ce.send_command.call_args.args[1].saved_id==SID
    assert not any('fields_ciphertext' in path for _,path,_ in state['db'])


def test_card_and_otp_cannot_be_saved(api):
    client,state=api
    path=f'/agents/chief/errands/{EID}/secret'
    for kind,fields in [('card',{'name':'Test','number':'4242424242424242','exp':'12/30','cvc':'321'}),('otp',{'code':'123456'})]:
        hold(state,kind)
        response=client.post(path,json={'hold_id':'hold-1','fields':fields,'save':True},headers={'X-Ledger-Unlock':'fixture-stepup'})
        assert response.status_code==422
        assert all(v not in response.text for v in fields.values())
    ce.send_command.assert_not_called()


def test_frontend_virtual_card_contract_is_explicitly_unavailable(api):
    client,state=api
    hold(state,'card')
    response=client.post(f'/agents/chief/errands/{EID}/secret',json={'hold_id':'hold-1','use_saved':'virtual'})
    assert response.status_code==400
    assert isinstance(response.json()['detail'],str)


def test_invalid_secret_bodies_do_not_echo_input_and_are_rate_limited(api):
    client,state=api
    hold(state)
    path=f'/agents/chief/errands/{EID}/secret'
    for _ in range(6):
        response=client.post(path,content='SECRET_BAD_JSON',headers={'Content-Type':'application/json'})
        assert response.status_code==422 and 'SECRET_BAD_JSON' not in response.text
    assert client.post(path,json={}).status_code==429


def test_cross_tenant_and_low_seat_cannot_read_or_fill(api):
    client,state=api
    state['role']=None
    hold(state)
    for method,path in [('get',f'/errands/{EID}'),('post',f'/errands/{EID}/secret'),('get',f'/errands/{EID}/frames?n=1'),('get',f'/computer/settings?business_id={BID}')]:
        assert getattr(client,method)('/agents/chief'+path).status_code==404
    ce.send_command.assert_not_called()


def test_settings_meta_and_secret_revoke_never_select_values(api):
    client,state=api
    assert client.get(f'/agents/chief/computer/settings?business_id={BID}').status_code==200
    assert client.delete(f'/agents/chief/computer/secrets/{SID}').status_code==200
    assert not state['stepup']
    for method,path,body in state['db']:
        if method=='GET' and '/business_secrets' in path:
            assert 'fields_ciphertext' not in path and 'select=*' not in path


def test_settings_changes_require_owner_stepup_and_keep_cards_disabled(api):
    client,state=api
    path='/agents/chief/computer/settings'
    body={'business_id':BID,'settings':{'spend_limit_cents':200}}
    assert client.put(path,json=body).status_code==403
    state['role']='manager'
    assert client.put(path,json=body,headers={'X-Ledger-Unlock':'fixture-stepup'}).status_code==404
    state['role']='owner'
    body['settings']['save_cards']=True
    assert client.put(path,json=body,headers={'X-Ledger-Unlock':'fixture-stepup'}).status_code==422


def test_internal_execution_fields_are_not_in_cards(api):
    client,state=api
    response=client.get(f'/agents/chief/errands/{EID}')
    assert response.status_code==200
    assert '__start_url' not in response.text and 'user_id' not in response.text


@pytest.mark.parametrize('suffix',['','/','?code=SECRET-CODE'])
def test_uvicorn_and_sentry_remove_entire_secure_entry_payload(suffix):
    path=f'https://api.test/agents/chief/errands/{EID}/secret'+suffix
    stream=io.StringIO()
    handler=logging.StreamHandler(stream)
    handler.addFilter(RedactCredentialPaths())
    logger=logging.getLogger('computer-test-access')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info('POST %s %s',path,{'fields':{'password':'SECRET-PASSWORD','code':'SECRET-CODE'}})
    finally:
        logger.removeHandler(handler)
    assert 'SECRET-' not in stream.getvalue()
    event={'request':{'url':path,'data':{'password':'SECRET-PASSWORD'}},
        'exception':{'values':[{'stacktrace':{'frames':[{'vars':{'fields':'SECRET-PASSWORD'}}]}}]},
        'breadcrumbs':{'values':[{'message':'SECRET-PASSWORD'}]}}
    assert scrub_sentry_event(event) is None


def test_unapproved_generic_job_enqueue_is_rejected(monkeypatch):
    # Use the real enqueue function in this independent test, not the API mock.
    with pytest.raises(ValueError,match='transactionally approved'):
        asyncio.run(chief_jobs.enqueue(None,user_id=UID,business_id=BID,kind='errand',params={'errand_id':EID}))


def test_worker_mailbox_cleanup_drops_pending_plaintext():
    mailbox=ce.register_worker(EID)
    command=ce.Command('secret',UID,fields={'password':'NEVER-LOG'})
    mailbox.put(command)
    ce.unregister_worker(EID)
    assert not command.fields
    assert command.result.done()
    assert isinstance(command.result.exception(),HTTPException)


def test_reorder_planning_uses_supplier_and_existing_po_without_account_leak(api,monkeypatch):
    client,state=api
    import chief_inventory_actions
    import reorder_engine
    offering={'id':SID,'business_id':BID,'name':'Paper clips','price':'3.49','reorder_qty':1,
              'category':'product','supplier_name':'Fixture supplier'}
    original=ce.db
    monkeypatch.setattr(ce,'db',lambda method,path,body=None:[offering] if path.startswith('/offerings?') else original(method,path,body))
    monkeypatch.setattr(chief_inventory_actions,'_primary_supplier',lambda *a:{'id':JOB,'business_id':BID,
        'name':'Fixture supplier','website':'https://supplier.test','account_number':'PRIVATE-TRADE-ACCOUNT'})
    monkeypatch.setattr(reorder_engine,'next_po_number',lambda bid:'PO-TEST')
    writes=[]
    def plan_rpc(name,**kwargs):
        writes.append((name,kwargs))
        return {'id':EID,'status':'planned',**kwargs['p_row']}
    monkeypatch.setattr(ce,'rpc',plan_rpc)
    response=client.post('/agents/chief/errands',json={'business_id':BID,'kind':'reorder','offering_ids':[SID],'qty':{SID:2}})
    assert response.status_code==200,response.text
    row=response.json()['errand']
    assert row['planned_total_cents']==698
    assert row['plan']['items'][0]['qty']==2
    assert row['plan']['items'][0]['po_number']=='PO-TEST'
    assert 'PRIVATE-TRADE-ACCOUNT' not in response.text
    assert writes[0][0]=='chief_errand_plan'
    chief_jobs.enqueue.assert_not_called()


def test_all_new_routes_require_an_authenticated_session():
    app=FastAPI()
    app.include_router(ce.router)
    with TestClient(app) as client:
        for route in ce.router.routes:
            path=route.path.replace('{errand_id}',EID).replace('{secret_id}',SID)
            method=next(iter(route.methods))
            response=client.request(method,path+'?business_id='+BID+'&n=1',json={})
            assert response.status_code==401,(method,path,response.text)


def test_orphan_reconciliation_happens_before_job_is_removed_from_sweep(monkeypatch):
    old=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    job={'id':JOB,'kind':'errand','status':'running','created_at':old,'business_id':BID}
    monkeypatch.setattr(sb_clients,'sb_get_as_service',lambda path:[job])
    patch=Mock()
    monkeypatch.setattr(sb_clients,'sb_patch_as_service',patch)
    monkeypatch.setattr(ce,'interrupt_job',Mock(side_effect=HTTPException(503,'Storage unavailable.')))
    assert chief_jobs.sweep_orphans()==0
    patch.assert_not_called()
