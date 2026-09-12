import copy
import json
import logging
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import card_connections as cc
from access_log_redaction import RedactCredentialPaths, scrub_sentry_event

BID='00000000-0000-4000-8000-000000000001'
UID='00000000-0000-4000-8000-000000000002'
CID='00000000-0000-4000-8000-000000000003'
OTHER='00000000-0000-4000-8000-000000000004'
TOKENS={'access_token':'oauth-secret','refresh_token':'refresh-secret','stripe_user_id':'acct_fixture','scope':'stripe_apps','livemode':False}
CARD={'object':'issuing.card','id':'ic_fixture','type':'virtual','status':'active','livemode':False,
      'last4':'1234','exp_month':12,'exp_year':2099,'currency':'usd','number':'must-never-leave-provider','cvc':'secret-cvc'}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv('CARD_CONNECTION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('STRIPE_CARDS_SANDBOX_CLIENT_ID','ca_fixture')
    monkeypatch.setenv('STRIPE_CARDS_SANDBOX_DEVELOPER_KEY','sk_test_fixture')
    monkeypatch.setenv('STRIPE_CARDS_SANDBOX_WEBHOOK_SECRET','whsec_fixture')
    row={'id':CID,'business_id':BID,'mode':'sandbox','version':0,'status':'disconnected','account_id':None,'tokens_ciphertext':None,'selected_card':None}
    store={'row':row,'states':{},'role':'owner','user':UID,'calls':[]}
    def database(method,path,body=None):
        store['calls'].append((method,path,body))
        parsed=urlparse(path); params=parse_qs(parsed.query)
        candidates=[row] if parsed.path=='/business_card_connections' else list(store['states'].values())
        def matches(r):
            for key,values in params.items():
                if key in ('select','limit'): continue
                op,value=values[0].split('.',1)
                if op=='eq' and str(r.get(key))!=value: return False
                if op=='gt' and r[key]<=value: return False
            return True
        chosen=[r for r in candidates if matches(r)]
        if method=='PATCH':
            for r in chosen: r.update(body)
        result=copy.deepcopy(chosen)
        if method=='DELETE':
            for r in chosen: store['states'].pop(r['state_hash'])
        return result
    def rpc(name,**args):
        if name=='card_connection_begin':
            store['states'].clear()
            store['states'][args['p_state']]={'state_hash':args['p_state'],'verifier_hash':args['p_verifier'],
                'user_id':args['p_user'],'connection_id':CID,'version':row['version'],'status':'issued','expires_at':'2099-01-01T00:00:00Z'}
            return {'id':CID}
        if name=='card_connection_disconnect':
            row.update(status='disconnected',tokens_ciphertext=None,selected_card=None,version=row['version']+1)
            store['states'].clear()
            return None
        assert name=='card_connection_update'
        if args['p_version']!=row['version']: return None
        row.update(status=args['p_status'],account_id=args['p_account'],tokens_ciphertext=args['p_tokens'],
            expires_at=args['p_expires'],selected_card=args['p_card'],version=row['version']+1)
        return copy.deepcopy(row)
    def check(bid,user,role):
        if bid!=BID or store['role']!='owner': raise HTTPException(404)
    def unlock(request,user,scope):
        if request.headers.get('x-ledger-unlock')!='fixture': raise HTTPException(403)
    def stripe(method,path,key,**kwargs):
        if path=='/oauth/token': return dict(TOKENS)
        assert key==TOKENS['access_token']
        if path=='/account': return {'id':'acct_fixture'}
        if path=='/issuing/cards': return {'data':[dict(CARD)],'has_more':False}
        if path=='/issuing/cards/ic_fixture': return dict(CARD)
        raise AssertionError('Unexpected provider request')
    monkeypatch.setattr(cc,'db',database)
    monkeypatch.setattr(cc,'rpc',rpc)
    monkeypatch.setattr(cc.business_access,'assert_access',check)
    monkeypatch.setattr(cc,'require_unlock',unlock)
    monkeypatch.setattr(cc,'stripe_request',Mock(side_effect=stripe))
    app=FastAPI(); app.include_router(cc.router)
    app.dependency_overrides[cc.sb_clients.authed_request]=lambda:SimpleNamespace(user=SimpleNamespace(id=store['user']))
    with TestClient(app) as client: yield client,store


def path(action,bid=BID,mode='sandbox'):
    return f'/payments/card-connections/{bid}/{mode}/{action}'


def authorize(client):
    start=client.post(path('start'),headers={'x-ledger-unlock':'fixture'}).json()
    response=client.get('/payments/card-connections/stripe/callback',params={'code':'ac_fixture','state':start['state']})
    assert 'Finish connection' in response.text
    return {k:start[k] for k in ('state','verifier')}


def connect(client):
    response=client.post(path('complete'),json=authorize(client))
    assert response.status_code==200,response.text
    return response.json()


def test_owner_stepup_configuration_and_separate_environments(api):
    client,store=api
    assert client.post(path('start')).status_code==403
    assert client.get(path('status',bid=OTHER)).status_code==404
    store['role']='admin'
    assert client.get(path('status')).status_code==404
    store['role']='owner'
    assert client.get(path('status',mode='live')).json()['configured'] is False
    assert client.post(path('start',mode='live'),headers={'x-ledger-unlock':'fixture'}).status_code==503
    assert client.get(path('status',mode='anything')).status_code==422
    cc.stripe_request.assert_not_called()


def test_oauth_original_browser_user_replay_and_safe_metadata(api):
    client,store=api
    pending=authorize(client)
    assert store['row']['status']=='disconnected'
    assert client.post(path('complete'),json={**pending,'verifier':'x'*43}).status_code==409
    store['user']=OTHER
    assert client.post(path('complete'),json=pending).status_code==409
    store['user']=UID
    response=client.post(path('complete'),json=pending)
    assert response.json()['status']=='connected'
    assert response.json()['purchasing_enabled'] is False
    assert 'token' not in response.text and 'ciphertext' not in response.text
    assert client.post(path('complete'),json=pending).status_code==409
    count=cc.stripe_request.call_count
    client.get('/payments/card-connections/stripe/callback',params={'code':'ac_fixture','state':pending['state']})
    assert cc.stripe_request.call_count==count
    assert all('/businesses?' not in p for _,p,_ in store['calls'])


def test_disconnect_invalidates_pending_completion(api):
    client,store=api
    pending=authorize(client)
    assert client.post(path('disconnect')).status_code==200
    assert client.post(path('complete'),json=pending).status_code==409
    assert store['row']['tokens_ciphertext'] is None


def test_card_selection_rechecks_provider_and_never_returns_secrets(api):
    client,store=api; connect(client)
    response=client.get(path('cards'))
    assert response.status_code==200
    assert response.json()['cards'][0]['last4']=='1234'
    assert 'cvc' not in response.text and 'number' not in response.text
    assert client.post(path('select'),json={'card_id':'ic_fixture'}).status_code==403
    response=client.post(path('select'),json={'card_id':'ic_fixture'},headers={'x-ledger-unlock':'fixture'})
    assert response.json()['selected_card']['id']=='ic_fixture'
    assert response.json()['purchasing_enabled'] is False
    assert client.post(path('select'),json={'card_id':'ic_fixture','number':'4242'},headers={'x-ledger-unlock':'fixture'}).status_code==422
    cc.stripe_request.return_value={**CARD,'type':'physical'}; cc.stripe_request.side_effect=None
    assert client.post(path('select'),json={'card_id':'ic_fixture'},headers={'x-ledger-unlock':'fixture'}).status_code==422
    assert client.get(path('cards')+'?after=../../account').status_code==422


@pytest.mark.parametrize('change',[{'type':'physical'},{'type':None},{'livemode':True},{'status':'inactive'},
    {'exp_year':2000},{'exp_month':13},{'last4':'12345'},{'currency':'arbitrary'},{'id':'../account'}])
def test_reject_ineligible_cards(api,change):
    assert cc.card_metadata({**CARD,**change},'sandbox') is None


def test_crypto_binding(api):
    _,store=api; row=store['row']
    token=cc.encrypt(TOKENS,row,'acct_fixture')
    for altered,account in [({**row,'business_id':OTHER},'acct_fixture'),({**row,'mode':'live'},'acct_fixture'),(row,'acct_other')]:
        with pytest.raises(HTTPException): cc.decrypt(token,altered,account)
    assert cc.decrypt(token,row,'acct_fixture')['access_token']==TOKENS['access_token']


def test_refresh_rotation_and_disconnect_race(api):
    client,store=api; connect(client)
    store['row']['expires_at']=(cc.clock()-timedelta(minutes=1)).isoformat()
    key,row=cc.access(copy.deepcopy(store['row']))
    assert key==TOKENS['access_token'] and row['status']=='connected'
    store['row']['expires_at']=(cc.clock()-timedelta(minutes=1)).isoformat()
    def revoke(*args,**kwargs):
        cc.rpc('card_connection_disconnect',p_business=BID,p_mode='sandbox')
        return dict(TOKENS)
    cc.stripe_request.side_effect=revoke
    with pytest.raises(HTTPException): cc.access(copy.deepcopy(store['row']))
    assert store['row']['status']=='disconnected' and store['row']['tokens_ciphertext'] is None


def test_refresh_timeout_requires_reconnect_no_retry(api):
    client,store=api; connect(client)
    store['row']['expires_at']=(cc.clock()-timedelta(minutes=1)).isoformat()
    cc.stripe_request.side_effect=HTTPException(503,'Stripe unavailable')
    with pytest.raises(HTTPException): cc.access(copy.deepcopy(store['row']))
    assert store['row']['status']=='reconnect_required'
    count=cc.stripe_request.call_count
    with pytest.raises(HTTPException): cc.access(copy.deepcopy(store['row']))
    assert cc.stripe_request.call_count==count


@pytest.mark.parametrize('change',[{'livemode':True},{'scope':'read_write'},{'stripe_user_id':'acct_another'}])
def test_token_account_scope_and_mode(api,change):
    with pytest.raises(HTTPException): cc.validate_tokens({**TOKENS,**change},'sandbox','acct_fixture')


def test_oauth_and_token_request_logs_are_dropped():
    url='/payments/card-connections/stripe/callback?code=SECRET&state=SECRET'
    record=logging.LogRecord('uvicorn.access',20,'',0,'%s',(url,),None)
    RedactCredentialPaths().filter(record)
    assert 'SECRET' not in record.getMessage()
    assert scrub_sentry_event({'request':{'url':url},'extra':{'token':'SECRET'}}) is None


def test_uninstall_signature_and_scope(api,monkeypatch):
    client,store=api; connect(client)
    event={'type':'account.application.deauthorized','account':'acct_fixture','livemode':False,'data':{'object':{'id':'ca_fixture'}}}
    assert client.post('/payments/card-connections/stripe/webhook/sandbox',json=event).status_code==400
    monkeypatch.setattr(cc,'verify_webhook_signature',lambda *a,**k:True)
    assert client.post('/payments/card-connections/stripe/webhook/live',json=event).status_code==400
    assert client.post('/payments/card-connections/stripe/webhook/sandbox',json={**event,'data':{'object':{'id':'ca_other'}}}).status_code==400
    assert store['row']['status']=='connected'
    assert client.post('/payments/card-connections/stripe/webhook/sandbox',json=event).status_code==200
    assert store['row']['status']=='disconnected'


def test_uninstall_invalidates_authorization_waiting_for_completion(api,monkeypatch):
    client,store=api
    pending=authorize(client)
    monkeypatch.setattr(cc,'verify_webhook_signature',lambda *a,**k:True)
    event={'type':'account.application.deauthorized','account':'acct_fixture','livemode':False,'data':{'object':{'id':'ca_fixture'}}}
    assert client.post('/payments/card-connections/stripe/webhook/sandbox',json=event).status_code==200
    assert client.post(path('complete'),json=pending).status_code==409


def test_status_allowlists_saved_metadata(api):
    client,store=api; connect(client)
    store['row']['selected_card']=dict(CARD)
    response=client.get(path('status'))
    assert 'cvc' not in response.text and 'number' not in response.text
