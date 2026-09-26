import asyncio
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import chief_creative_execution as execution
import platform_chief_marketing as marketing
import platform_chief_creative as creative
import platform_chief_authority as authority
import platform_chief_actions as actions
import platform_console as console
from auth_supabase import require_user, require_user_session, UserSession
from lead_admin import PLATFORM_OWNER_EMAIL
from __tests__.test_platform_chief_authority import store
from __tests__.test_platform_chief_creative import setup, OWNER, BIZ


def body(message, history=None):
    return marketing.ChiefMessageBody(message=message, history=history or [])


def test_creation_requires_current_direct_instruction_and_visual_context():
    history = [{'role':'chief','text':'Here is the flyer brief; say create it.'}]
    assert execution.create_requested(body('create it', history))
    assert execution.create_requested(body('Create the flyer'))
    assert execution.create_requested(body('Create the flyer. Do not publish.'))
    for text in ['Do not create the flyer yet', 'Suggest five flyer ideas', 'If I say create the flyer, what happens?', 'check this out "create it"', 'Create the invoice']:
        assert not execution.create_requested(body(text, history))
    assert not execution.create_requested(body('create it'))


def test_native_tool_payload_has_priority_and_cannot_spoof_action_type():
    native = [{'type':'tool_use','name':'generate_image','input':{'type':'marketing_pause','prompt':'Approved brief'}}]
    selected, question = execution.selected_actions(native,[{'type':'generate_image','prompt':'duplicate'}])
    assert selected == [{'type':'generate_image','prompt':'Approved brief'}]
    assert question is None
    with pytest.raises(HTTPException): execution.selected_actions(native * 2, [])
    with pytest.raises(HTTPException): execution.selected_actions([{'type':'tool_use','name':'publish','input':{}}], [])


@pytest.mark.parametrize('status,phrase',[('queued','not ready'),('working','not ready'),('ready','ready'),('failed','failed')])
def test_status_overrides_model_prose(status,phrase):
    result = {'type':'generate_image','ok':True,'image':{'id':str(uuid4()),'status':status}}
    reply = execution.display_reply('Yes, it is finished and looks fantastic.',[result],body('Create the flyer'))
    assert phrase in reply
    assert 'fantastic' not in reply and 'finished' not in reply


def test_pending_approval_is_not_queued_or_ready():
    result={'type':'generate_image','ok':False,'approval':{'status':'pending'}}
    assert 'Generation has not started' in execution.display_reply('Your flyer is ready.',[result],body('Create the flyer'))
    assert 'no image was submitted' in execution.display_reply('Requesting the visual now.',[],body('Create the flyer'))
    assert 'cannot verify' in execution.display_reply('The image is ready.',[],body('Hello'))


def test_clarification_can_stop_ambiguous_price_brief():
    selected,q = execution.selected_actions([{'type':'tool_use','name':'creative_clarification','input':{'question':'Billing says $99/month. Use that verified rate?'}}], [])
    assert selected == []
    assert execution.display_reply('', [], body('Create the flyer'), q) == q


def test_status_reads_owned_job_and_returns_real_card(setup, monkeypatch):
    iid = str(uuid4())
    monkeypatch.setattr(creative.images,'artwork',AsyncMock(return_value={'id':iid,'status':'queued'}))
    monkeypatch.setattr(creative.images,'present',AsyncMock(side_effect=lambda c,r:r))
    monkeypatch.setattr(authority,'db',AsyncMock(return_value=[]))
    request=body('got the image?', [{'role':'chief','text':f'Creating. [Image references: {iid}]'}])
    result=asyncio.run(execution.status_result(request,OWNER))
    assert result['images'][0]['id'] == iid and 'not ready' in result['result']
    creative.images.artwork.assert_awaited_once()
    assert creative.images.artwork.call_args.args[1:] == (BIZ['id'],iid)


def test_status_without_receipt_does_not_call_older_art_current(setup, monkeypatch):
    query=AsyncMock(return_value=[{'id':str(uuid4()),'status':'ready'}])
    monkeypatch.setattr(creative.images,'db',query)
    monkeypatch.setattr(creative.images,'present',AsyncMock(side_effect=lambda c,r:r))
    monkeypatch.setattr(authority,'db',AsyncMock(return_value=[]))
    result=asyncio.run(execution.status_result(body("I don't see it"),OWNER))
    assert 'no confirmed image-job ID' in result['result']
    assert 'may belong to earlier requests' in result['result']
    assert 'model.not.is.null' in query.call_args.args[2]


def test_status_unavailable_does_not_invent_wait_time(setup, monkeypatch):
    monkeypatch.setattr(creative.images,'business',AsyncMock(side_effect=HTTPException(403,'Denied')))
    result=asyncio.run(execution.status_result(body('got the image?'),OWNER))
    assert result['ok'] is False and result['images'] == []
    assert 'No new generation' in result['label']


def client_for(monkeypatch):
    app=FastAPI();app.include_router(console.router)
    app.dependency_overrides[require_user]=lambda: OWNER
    app.dependency_overrides[require_user_session]=lambda: UserSession(OWNER,'verified-owner-jwt')
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-only')
    monkeypatch.setattr(console,'_service_headers',lambda:{})
    monkeypatch.setattr(console,'_build_snapshot',AsyncMock(return_value={}))
    monkeypatch.setattr(console,'log_api_usage',AsyncMock())
    monkeypatch.setattr(actions,'_log_action',AsyncMock())
    return TestClient(app)


def test_native_creation_endpoint_produces_review_card(setup, store, monkeypatch):
    call=AsyncMock(return_value=httpx.Response(200,json={'stop_reason':'tool_use','content':[{'type':'tool_use','name':'generate_image','input':{'prompt':'Approved abstract founder flyer'}}]}))
    monkeypatch.setattr(console.llm_call,'apost',call)
    generate=AsyncMock();monkeypatch.setattr(creative.images,'handle_generate_image',generate)
    response=client_for(monkeypatch).post('/platform/chief/message',json={'message':'Create the flyer'})
    assert response.status_code==200,response.text
    assert response.json()['actions_taken'][0]['approval']['status']=='pending'
    assert 'Generation has not started' in response.json()['reply']
    assert call.call_args.args[1]['tool_choice']=={'type':'any','disable_parallel_tool_use':True}
    generate.assert_not_called()


def test_truncated_response_never_dispatches(setup, store, monkeypatch):
    monkeypatch.setattr(console.llm_call,'apost',AsyncMock(return_value=httpx.Response(200,json={'stop_reason':'max_tokens','content':[{'type':'tool_use','name':'generate_image','input':{'prompt':'partial'}}]})))
    dispatch=AsyncMock();monkeypatch.setattr(console,'dispatch_actions',dispatch)
    response=client_for(monkeypatch).post('/platform/chief/message',json={'message':'Create the flyer'})
    assert response.status_code==422
    dispatch.assert_not_called()


def test_status_endpoint_does_not_call_model_or_budget(setup, monkeypatch):
    import spend_guard
    monkeypatch.setattr(spend_guard,'over_budget',lambda:True)
    model=AsyncMock();monkeypatch.setattr(console.llm_call,'apost',model)
    monkeypatch.setattr(execution,'status_result',AsyncMock(return_value={'type':'find_images','ok':True,'result':'No matching job.','images':[]}))
    response=client_for(monkeypatch).post('/platform/chief/message',json={'message':'got the image?'})
    assert response.status_code==200 and response.json()['reply']=='No matching job.'
    model.assert_not_called();authority.require_budget.assert_not_awaited()


@pytest.mark.parametrize('count_fails',[False,True])
def test_founder_offer_is_monthly_and_unavailable_count_is_not_zero(monkeypatch,count_fails):
    import stripe_billing as billing
    import platform_marketing as data
    monkeypatch.setattr(billing,'_founder_price_ids',lambda:['price_monthly'])
    monkeypatch.setattr(billing,'_founder_seat_price_ids',lambda:['price_monthly','price_legacy'])
    monkeypatch.setattr(billing,'_founder_seat_limit',lambda:50)
    monkeypatch.setattr(billing,'_price_display',AsyncMock(return_value={'unit_amount':9900,'currency':'usd','interval':'month'}))
    monkeypatch.setattr(data,'db',AsyncMock(side_effect=HTTPException(503,'Unavailable')) if count_fails else AsyncMock(return_value=[{'id':'a'},{'id':'b'}]))
    facts=asyncio.run(marketing.founder_offer())
    assert facts['interval']=='month' and facts['unit_amount']==9900
    assert 'not a one-time' in facts['rate_terms']
    assert facts['seats_left']==(None if count_fails else 48)
    assert facts['availability_status']==('unavailable' if count_fails else 'verified')


def test_native_creation_executes_once_when_policy_allows(setup, store, monkeypatch):
    monkeypatch.setattr(authority,'policy',AsyncMock(return_value={'settings':{'creative':'allow'}}))
    native={'type':'tool_use','name':'generate_image','input':{'prompt':'Approved original abstract flyer'}}
    monkeypatch.setattr(console.llm_call,'apost',AsyncMock(return_value=httpx.Response(200,json={'stop_reason':'tool_use','content':[{'type':'text','text':'Done! [ACTION:{"type":"generate_image","prompt":"duplicate"}]'},native]})))
    generate=AsyncMock(return_value={'type':'generate_image','result':'Queued','label':'Creating','image':{'id':str(uuid4()),'business_id':BIZ['id'],'status':'queued'}})
    monkeypatch.setattr(creative.images,'handle_generate_image',generate)
    response=client_for(monkeypatch).post('/platform/chief/message',json={'message':'Create the flyer'})
    assert response.status_code==200,response.text
    assert response.json()['actions_taken'][0]['image']['status']=='queued'
    assert 'not ready yet' in response.json()['reply']
    generate.assert_awaited_once()


def test_new_creation_does_not_reuse_old_receipt(setup,monkeypatch):
    old=str(uuid4())
    monkeypatch.setattr(creative.images,'present',AsyncMock(side_effect=lambda c,r:r))
    monkeypatch.setattr(authority,'db',AsyncMock(return_value=[]))
    artwork=AsyncMock();monkeypatch.setattr(creative.images,'artwork',artwork)
    request=body('got the image?',[
        {'role':'chief','text':f'Old flyer [Image references: {old}]'},
        {'role':'you','text':'Create a new flyer'},
        {'role':'chief','text':'Requesting it now.'}])
    result=asyncio.run(execution.status_result(request,OWNER))
    assert 'no confirmed image-job ID' in result['result']
    artwork.assert_not_called()
