import asyncio
import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import platform_chief_marketing as m
import platform_console as console
import platform_chief_actions as actions
import platform_marketing as marketing
from auth_supabase import require_user, require_user_session, UserSession
from lead_admin import PLATFORM_OWNER_EMAIL


def picture(color='red'):
    out = io.BytesIO(); Image.new('RGB', (16, 16), color).save(out, format='JPEG')
    return {'name':color+'.jpg', 'data_url':'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode()}


def test_real_images_and_history_reach_model():
    body = m.ChiefMessageBody(message='Compare these', images=[picture(), picture('blue')],
        history=[{'role':'you','text':'I like warm colors','images':[picture('yellow')]}, {'role':'chief','text':'Let us compare.'}])
    messages=m.conversation_messages(body)
    assert len(messages)==3
    assert len([b for b in messages[-1]['content'] if b['type']=='image'])==2
    assert messages[0]['content'][1]['source']['media_type']=='image/jpeg'
    assert messages[-1]['content'][-1]['text']=='Compare these'


@pytest.mark.parametrize('value',['https://example.com/a.jpg','data:image/jpeg;base64,bad','data:image/svg+xml;base64,PHN2Zz4='])
def test_invalid_images_rejected(value):
    with pytest.raises(ValidationError): m.ChiefImage(name='bad',data_url=value)


def test_image_count_and_role_limits():
    with pytest.raises(ValidationError): m.ChiefMessageBody(message='x',images=[picture()]*5)
    body=m.ChiefMessageBody(message='x',images=[picture()]*4,history=[{'role':'you','text':'x','images':[picture()]*4}]*2)
    with pytest.raises(HTTPException): m.conversation_messages(body)
    body=m.ChiefMessageBody(message='x',history=[{'role':'chief','text':'x','images':[picture()]}])
    with pytest.raises(HTTPException): m.conversation_messages(body)


def test_existing_owner_gate_still_covers_multimodal_chat():
    app=FastAPI(); app.include_router(console.router); client=TestClient(app)
    assert client.post('/platform/chief/message',json={'message':'hi','images':[picture()]}).status_code in (401,403)
    app.dependency_overrides[require_user]=lambda:SimpleNamespace(id=str(uuid4()),email='tenant@example.com')
    assert client.post('/platform/chief/message',json={'message':'hi','context':'marketing'}).status_code==403


def test_endpoint_uses_vision_and_marketing_context(monkeypatch):
    import llm_call, spend_guard, rate_limit
    captured={}
    async def snapshot(*args): return {'known_fact':'Current business data'}
    async def marketing_data(): return {'config':{'channels':[{'id':'actual-account'}]}}
    async def call(client,payload,**kwargs):
        captured.update(payload)
        return SimpleNamespace(status_code=200,json=lambda:{'content':[{'type':'text','text':'Try a workflow demo.'}],'usage':{}})
    async def noop(**kwargs): pass
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-only')
    monkeypatch.setattr(console,'_service_headers',lambda:{})
    monkeypatch.setattr(console,'_build_snapshot',snapshot)
    monkeypatch.setattr(console,'marketing_snapshot',marketing_data)
    monkeypatch.setattr(console,'log_api_usage',noop)
    monkeypatch.setattr(llm_call,'apost',call)
    monkeypatch.setattr(spend_guard,'over_budget',lambda:False)
    monkeypatch.setattr(rate_limit,'allow',lambda *a:True)
    app=FastAPI(); app.include_router(console.router)
    owner=SimpleNamespace(id=str(uuid4()),email=PLATFORM_OWNER_EMAIL)
    app.dependency_overrides[require_user]=lambda:owner
    app.dependency_overrides[require_user_session]=lambda:UserSession(owner,'verified-test-jwt')
    result=TestClient(app).post('/platform/chief/message',json={'message':'Ideas please','context':'marketing','images':[picture()]})
    assert result.status_code==200, result.text
    assert 'actual-account' in captured['system']
    assert captured['messages'][-1]['content'][1]['type']=='image'
    assert result.json()['actions_taken']==[]


def test_draft_reuses_existing_validation_and_retries(monkeypatch):
    from datetime import timedelta
    saved=[]
    async def db(method,path,body=None): return saved
    async def save(draft):
        assert draft.ai_assisted is True
        saved.append({'id':str(draft.id),'revision':1}); return saved[-1]
    monkeypatch.setattr(marketing,'db',db); monkeypatch.setattr(marketing,'save_draft',save)
    action={'type':'marketing_save_draft','draft':{'campaign':'test','text':'Useful caption','channel_id':'real', 'run_at':(marketing.now()+timedelta(days=1)).isoformat()}}
    request=uuid4(); m.prepare_actions([action],request)
    first=asyncio.run(m.save_draft(action)); second=asyncio.run(m.save_draft(action))
    assert first['post_id']==second['post_id'] and len(saved)==1
    assert actions.HANDLERS['marketing_save_draft'] is m.save_draft
    assert 'marketing_approve' not in actions.HANDLERS


def test_snapshot_failure_is_not_empty_success(monkeypatch):
    async def fail(): raise HTTPException(503,'Storage unavailable')
    monkeypatch.setattr(marketing,'config',fail)
    assert asyncio.run(m.marketing_snapshot())=={'unavailable':'Storage unavailable'}


def test_stale_revision_failure_propagates(monkeypatch):
    async def stale(*args): raise HTTPException(409,'Post changed')
    monkeypatch.setattr(marketing,'cancel',stale)
    with pytest.raises(HTTPException) as error:
        asyncio.run(m.cancel_post({'id':str(uuid4()),'revision':1}))
    assert error.value.status_code==409
