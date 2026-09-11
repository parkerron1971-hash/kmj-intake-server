"""HTTP authorization and companion checks. No provider calls or email sends."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID
import zipfile

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import connected_ai as ca
from connected_agents import companion as cp
from connected_agents.contracts import Draft, Provider, invoice_prompt, RehearsalError

B='10000000-0000-4000-8000-000000000001'
U='20000000-0000-4000-8000-000000000001'
D='30000000-0000-4000-8000-000000000001'
J='40000000-0000-4000-8000-000000000001'
TOKEN='sol_device_'+'a'*43
BUSINESS={'id':B,'owner_id':U}
DEVICE={'id':D,'business_id':B,'owner_id':U,'token_hash':ca.digest(TOKEN),'expires_at':'2099-01-01T00:00:00Z'}

@pytest.fixture
def client(monkeypatch):
    app=FastAPI();app.include_router(ca.router)
    app.dependency_overrides[ca.require_user]=lambda: SimpleNamespace(id=U)
    monkeypatch.setattr(ca,'_rows',lambda path:[BUSINESS] if path.startswith('/businesses') else [DEVICE])
    monkeypatch.setenv('CONNECTED_AI_ENABLED','on')
    monkeypatch.setenv('CONNECTED_AI_PILOT_BUSINESSES',B)
    monkeypatch.setattr(ca.feature_gates,'has_feature',lambda *args:True)
    return TestClient(app)

def test_status_requires_owner(client,monkeypatch):
    monkeypatch.setattr(ca,'_rows',lambda path:[{**BUSINESS,'owner_id':'someone-else'}])
    assert client.get('/connected-ai/status',params={'business_id':B}).status_code==403

def test_pilot_fail_closed_without_database_transition(client,monkeypatch):
    monkeypatch.delenv('CONNECTED_AI_ENABLED')
    monkeypatch.setattr(ca,'transition',lambda *args:pytest.fail('Disabled pilot touched DB transitions'))
    r=client.get('/connected-ai/status',params={'business_id':B})
    assert r.json()['enabled'] is False
    assert r.headers['cache-control']=='no-store'
    assert client.post('/connected-ai/pairings',params={'business_id':B},json={'provider':'claude'}).status_code==403

def test_business_settings_cannot_grant_pilot(client,monkeypatch):
    monkeypatch.setenv('CONNECTED_AI_PILOT_BUSINESSES','different-business')
    assert not ca.enabled({**BUSINESS,'settings':{'connected_ai_enabled':True}})

def test_pairing_stores_only_hash(client,monkeypatch):
    seen=[]
    monkeypatch.setattr(ca,'transition',lambda *args:seen.append(args) or {'id':D,'expires_at':'2099-01-01'})
    r=client.post('/connected-ai/pairings',params={'business_id':B},json={'provider':'claude'})
    assert r.status_code==200
    code=r.json()['code'];assert len(code)==43
    assert seen[0][3]['secret_hash']==ca.digest(code)
    assert code not in json.dumps(seen)

@pytest.mark.parametrize('auth',[None,'Bearer user-jwt','Bearer sol_device_short'])
def test_worker_rejects_other_credentials(client,auth):
    assert client.post('/connected-ai/heartbeat',json={'state':'signed_in'},headers={'Authorization':auth} if auth else {}).status_code==401

def test_expired_device_rejected(client,monkeypatch):
    monkeypatch.setattr(ca,'_rows',lambda path:[{**DEVICE,'expires_at':'2020-01-01T00:00:00Z'}])
    assert client.post('/connected-ai/lease',headers={'Authorization':'Bearer '+TOKEN}).status_code==401

def test_worker_cannot_choose_tenant_or_owner(client,monkeypatch):
    seen=[]
    monkeypatch.setattr(ca,'transition',lambda *args:seen.append(args) or {'ok':True})
    r=client.post('/connected-ai/heartbeat',json={'state':'signed_in','business_id':'attacker','owner_id':'attacker'},headers={'Authorization':'Bearer '+TOKEN})
    assert r.status_code==200
    assert seen[0][1:3]==(B,U)
    assert 'attacker' not in json.dumps(seen)

def test_owner_transfer_revokes_device(client,monkeypatch):
    monkeypatch.setattr(ca,'_rows',lambda path:[{**BUSINESS,'owner_id':'new-owner'}] if path.startswith('/businesses') else [DEVICE])
    assert client.post('/connected-ai/lease',headers={'Authorization':'Bearer '+TOKEN}).status_code==403

def test_completion_rejects_header_injection(client,monkeypatch):
    monkeypatch.setattr(ca,'transition',lambda *args:pytest.fail('Invalid draft reached DB'))
    r=client.post(f'/connected-ai/jobs/{J}/complete',headers={'Authorization':'Bearer '+TOKEN},json={'lease':'b'*43,'subject':'Hello\nBcc: unwanted','body':'An otherwise valid message for review.'})
    assert r.status_code==422

def test_companion_download_is_allowlisted(client):
    r=client.get('/connected-ai/companion.zip',params={'business_id':B})
    assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert set(z.namelist())=={'connected_agents/__init__.py','connected_agents/contracts.py','connected_agents/runtime.py','connected_agents/companion.py','Start Solutionist.cmd','README.txt'}
        assert TOKEN.encode() not in r.content

def test_robot_approval_never_claims_send(monkeypatch):
    monkeypatch.setattr(ca,'transition',lambda *args:pytest.fail('Robot claimed send'))
    result=asyncio.run(ca.approve_connected(BUSINESS,{'connected_ai_job_id':J},None))
    assert result['reason']=='human_review_required'

def test_approved_send_claims_before_delivery_and_settles_once(client,monkeypatch):
    import chief_of_staff
    events=[]
    item={'connected_ai_job_id':J,'subject':'Reviewed subject','body':'A reviewed message long enough to send.'}
    def transition(op,*args):
        events.append(op)
        return {'item':item,'expected_email':'alex@example.test'} if op=='claim_send' else {'ok':True}
    async def send(client,biz,item,**kwargs):
        assert kwargs=={'connected_delivery':True,'expected_email':'alex@example.test'}
        events.append('send');return {'sent':True,'provider_id':'fixture'}
    monkeypatch.setattr(ca,'transition',transition)
    monkeypatch.setattr(chief_of_staff,'_send_queued_email',send)
    assert asyncio.run(ca.approve_connected(BUSINESS,item,U))['sent'] is True
    assert events==['claim_send','send','settle_send']

def test_ambiguous_delivery_is_not_retried(client,monkeypatch):
    import chief_of_staff
    events=[]
    item={'connected_ai_job_id':J,'subject':'Reminder','body':'A message that requires explicit review.'}
    def transition(op,*args):
        events.append((op,args))
        return {'item':item,'expected_email':'alex@example.test'}
    async def fail(*args,**kwargs):raise TimeoutError('private provider diagnostic')
    monkeypatch.setattr(ca,'transition',transition)
    monkeypatch.setattr(chief_of_staff,'_send_queued_email',fail)
    result=asyncio.run(ca.approve_connected(BUSINESS,item,U))
    assert result['reason']=='delivery_needs_check' and result['sent'] is False
    assert events[-1][0]=='settle_send' and events[-1][1][-1]['sent'] is False
    assert 'private' not in json.dumps(result)

def test_shared_sender_rejects_unreviewed_connected_draft():
    import chief_of_staff
    result=asyncio.run(chief_of_staff._send_queued_email(None,BUSINESS,{'connected_ai_job_id':J}))
    assert result['sent'] is False and result['reason']=='human_review_required'

def test_recipient_change_stops_delivery(monkeypatch):
    import chief_of_staff
    async def rows(*args):return [{'email':'changed@example.test'}]
    monkeypatch.setattr(chief_of_staff,'_sb',rows)
    result=asyncio.run(chief_of_staff._send_queued_email(None,BUSINESS,{'contact_id':D,'connected_ai_job_id':J},connected_delivery=True,expected_email='alex@example.test'))
    assert result['reason']=='recipient_changed' and result['sent'] is False

@pytest.mark.parametrize('server',['https://evil.example','http://localhost:9000','https://kmj-intake-server-production.up.railway.app@evil.example','https://kmj-intake-server-production.up.railway.app/path'])
def test_companion_disallows_token_exfiltration(server):
    with pytest.raises(ValueError):cp.validate_server(server)

def test_local_test_server_requires_explicit_flag():
    assert cp.validate_server('http://127.0.0.1:9000',True)=='http://127.0.0.1:9000'

def test_saved_device_credential_round_trip(tmp_path):
    saved=[{'id':D,'provider':'chatgpt','server':cp.SERVER,'token':TOKEN}]
    cp.save_connections(tmp_path,saved)
    assert cp.load_connections(tmp_path)==saved
    if os.name=='nt':assert TOKEN.encode() not in (tmp_path/'connections.dat').read_bytes()
    else:assert (tmp_path/'connections.dat').stat().st_mode & 0o777==0o600

def test_cancelled_job_stops_native_task_without_completion(tmp_path,monkeypatch):
    calls=[];cancelled=[]
    async def auth(*args):return {'authenticated':True,'auth_method':'chatgpt'}
    async def draft(*args):
        try:await asyncio.sleep(60)
        finally:cancelled.append(True)
    actual_wait=asyncio.wait
    async def immediate(tasks,timeout):return await actual_wait(tasks,timeout=0.001)
    def api(server,path,body,token):
        calls.append(path)
        if path=='/lease':return {'job':{'id':J,'provider':'chatgpt','facts':{},'lease':'b'*43}}
        return {'active':not bool(body.get('job_id'))}
    monkeypatch.setattr(cp,'find_binary',lambda *args:'unused')
    monkeypatch.setattr(cp,'auth_status',auth);monkeypatch.setattr(cp,'draft_invoice',draft)
    monkeypatch.setattr(cp,'api',api);monkeypatch.setattr(cp.asyncio,'wait',immediate)
    asyncio.run(cp.run_one({'provider':'chatgpt','server':cp.SERVER,'token':TOKEN},tmp_path,once=True))
    assert cancelled==[True] and not any('/complete' in p for p in calls)

def test_invoice_facts_have_no_recipient_or_authority():
    facts={'business_name':'Example','contact_name':'Alex','invoice_number':'DEMO-1','amount_due_cents':10000,'currency':'USD','due_date':'2026-01-01'}
    assert 'DEMO-1' in invoice_prompt(facts)
    with pytest.raises(RehearsalError):invoice_prompt({**facts,'recipient_email':'someone@example.test'})
