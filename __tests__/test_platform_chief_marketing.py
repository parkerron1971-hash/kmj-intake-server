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
    import platform_chief_authority as authority
    from unittest.mock import AsyncMock
    monkeypatch.setattr(authority, "require_budget", AsyncMock())
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


@pytest.fixture
def empty_marketing(monkeypatch):
    async def config(): return {'channels': []}
    async def empty(*args): return []
    monkeypatch.setattr(marketing, 'config', config)
    monkeypatch.setattr(marketing, 'assets', empty)
    monkeypatch.setattr(marketing, 'db', empty)


def test_empty_calendar_is_loaded_not_inaccessible(empty_marketing):
    snapshot = asyncio.run(m.marketing_snapshot())
    for key in ('recent_posts', 'campaign_briefs'):
        assert snapshot[key] == []
        assert snapshot['source_status'][key] == {
            'status': 'loaded', 'source': 'Mission Control', 'returned_count': 0, 'truncated': False}
    assert snapshot['source_status']['buffer_calendar']['status'] == 'not_loaded'


@pytest.mark.parametrize('failed_source', ['config', 'assets', 'recent_posts', 'campaign_briefs'])
def test_one_failed_source_preserves_other_reads(monkeypatch, empty_marketing, failed_source):
    async def fail(*args): raise HTTPException(503, 'Storage unavailable')
    if failed_source in ('config', 'assets'):
        monkeypatch.setattr(marketing, failed_source, fail)
    else:
        async def db(method, path):
            failed_table = 'posts' if failed_source == 'recent_posts' else 'campaigns'
            if f'/platform_marketing_{failed_table}?' in path:
                raise HTTPException(503, 'Storage unavailable')
            return []
        monkeypatch.setattr(marketing, 'db', db)
    snapshot = asyncio.run(m.marketing_snapshot())
    assert snapshot[failed_source] == {'unavailable': 'Storage unavailable'}
    for key in ('config', 'assets', 'recent_posts', 'campaign_briefs'):
        assert snapshot['source_status'][key]['status'] == ('unavailable' if key == failed_source else 'loaded')


def test_snapshot_marks_bounded_data_and_preserves_campaign_facts(monkeypatch, empty_marketing):
    async def db(method, path):
        if '/platform_marketing_posts?' in path:
            assert 'limit=31' in path
            return [{'id': str(i)} for i in range(31)]
        assert 'limit=11' in path
        return [{'id': str(i), 'name': 'Launch', 'tracking_key': 'launch', 'revision': 2,
                 'stage': 'planning', 'brief': {'facts': 'x' * 2600, 'evidence': [1, 2, 3, 4]},
                 'brief_hash': 'current', 'plan_brief_hash': 'current'} for i in range(11)]
    monkeypatch.setattr(marketing, 'db', db)
    snapshot = asyncio.run(m.marketing_snapshot())
    assert len(snapshot['recent_posts']) == 30
    assert len(snapshot['campaign_briefs']) == 10
    for key in ('recent_posts', 'campaign_briefs'):
        assert snapshot['source_status'][key]['truncated'] is True
    brief = snapshot['campaign_briefs'][0]
    assert len(brief['brief']['facts']) == 2500
    assert brief['brief']['evidence'] == [1, 2, 3]
    assert brief['plan_current'] is True


def test_product_context_follows_runtime_settings(monkeypatch):
    monkeypatch.setenv('LAUNCH_INVITE_ONLY', 'off')
    monkeypatch.setenv('BILLING_TRIAL_DAYS', '14')
    monkeypatch.setenv('PRICE_TIER_STARTER_CENTS', '8900')
    context = m.product_context()
    assert context['invite_only'] is False
    assert context['trial_days'] == 14
    assert context['standard_monthly_prices_usd_cents']['starter'] == 8900
    assert 'founder' not in context['standard_monthly_prices_usd_cents']
    monkeypatch.setenv('LAUNCH_INVITE_ONLY', 'on')
    assert m.product_context()['invite_only'] is True


def test_stale_revision_failure_propagates(monkeypatch):
    async def stale(*args): raise HTTPException(409,'Post changed')
    monkeypatch.setattr(marketing,'cancel',stale)
    with pytest.raises(HTTPException) as error:
        asyncio.run(m.cancel_post({'id':str(uuid4()),'revision':1}))
    assert error.value.status_code==409


# ── one post on every channel (2026-10-02) ─────────────────────────────

@pytest.fixture
def idea(monkeypatch):
    """Tuesday's post on X and Facebook, as Chief finds it on the desk."""
    from datetime import timedelta
    run_at = (marketing.now() + timedelta(days=3)).isoformat()
    rows = [{'id': str(uuid4()), 'revision': 2, 'status': 'draft', 'run_at': run_at,
             'payload': {'text': 'Answer the oldest client first. Two minutes a day.', 'service': s}}
            for s in ('twitter', 'facebook')]
    calls = {'edit': [], 'cancel': []}

    async def db(method, path, body=None):
        assert method == 'GET' and path.startswith('/platform_marketing_posts?id=in.(')
        return [r for r in rows if r['id'] in path]

    async def edit(req, *, ai_assisted=None):
        calls['edit'].append((req, ai_assisted))
        return {'posts': [{**r, 'run_at': (req.run_at.isoformat() if req.run_at else r['run_at'])} for r in rows]}

    async def cancel(req):
        calls['cancel'].append(req)
        return {'cancelled': len(req.items), 'posts': rows}
    monkeypatch.setattr(marketing, 'db', db)
    monkeypatch.setattr(marketing, 'edit_slot', edit)
    monkeypatch.setattr(marketing, 'cancel_slot', cancel)
    return {'rows': rows, 'ids': [r['id'] for r in rows], 'calls': calls}


def test_chief_rewrites_one_post_on_every_channel_and_it_goes_back_to_review(idea):
    out = asyncio.run(m.edit_slot({'post_ids': idea['ids'], 'text': 'Reply to whoever waited longest. Two minutes.'}))
    req, ai = idea['calls']['edit'][0]
    assert ai is True and [str(i.id) for i in req.items] == idea['ids'] and [i.revision for i in req.items] == [2, 2]
    assert req.text == 'Reply to whoever waited longest. Two minutes.' and req.run_at is None
    assert out['ok'] and 'post was rewritten on Facebook and X' in out['label'] and 'back in your review' in out['label']


@pytest.mark.parametrize('text,refusal', [
    ('Answer the oldest client first. Join 500 owners.', 'cannot add a number'),
    ('Answer the oldest client first at mysolutionist.app', 'link or a hashtag'),
    ('Answer the oldest client first #smallbusiness', 'link or a hashtag'),
])
def test_chief_cannot_add_a_number_link_or_hashtag(idea, text, refusal):
    out = asyncio.run(m.edit_slot({'post_ids': idea['ids'], 'text': text}))
    assert out['ok'] is False and refusal in out['label'] and idea['calls']['edit'] == []


def test_chief_moves_a_missed_post_with_a_new_time(idea):
    from datetime import timedelta
    when = (marketing.now() + timedelta(days=4)).isoformat()
    out = asyncio.run(m.edit_slot({'post_ids': idea['ids'], 'run_at': when}))
    assert idea['calls']['edit'][0][0].text is None and out['label'].endswith('nothing goes out until you approve it.')
    assert "post was moved on" in out['label']


def test_chief_names_a_post_by_all_its_ids(idea):
    with pytest.raises(HTTPException) as err:
        asyncio.run(m.edit_slot({'post_ids': [], 'text': 'x'}))
    assert err.value.status_code == 422
    with pytest.raises(HTTPException) as err:
        asyncio.run(m.skip_slot({'post_ids': idea['ids'] + [str(uuid4())]}))
    assert err.value.status_code == 409 and idea['calls']['cancel'] == []


def test_chief_skips_a_post_on_every_channel(idea):
    out = asyncio.run(m.skip_slot({'post_ids': idea['ids']}))
    assert len(idea['calls']['cancel'][0].items) == 2 and out['ok'] and 'will not go out' in out['label']


def test_starting_over_is_refused_once_part_of_the_week_is_approved(monkeypatch):
    import marketing_engine as engine

    async def get_run(run_id):
        return {'id': str(run_id), 'status': 'succeeded', 'post_ids': []}

    async def db(method, path, body=None):
        return [{'status': 'draft'}, {'status': 'approved'}]
    started = []
    monkeypatch.setattr(engine, 'get_run', get_run)
    monkeypatch.setattr(engine, 'start_week', lambda replan=False: started.append(replan) or True)
    monkeypatch.setattr(marketing, 'db', db)
    out = asyncio.run(m.replan_week({}))
    assert out['ok'] is False and 'cannot be started over' in out['label'] and started == []


def test_new_marketing_actions_are_gated():
    import platform_chief_authority as authority
    assert authority.GROUPS['marketing_edit_slot'] == 'drafts'
    assert authority.GROUPS['marketing_skip_slot'] == 'marketing_stop'
    assert authority.GROUPS['marketing_replan_week'] == 'marketing_stop'
    for kind in ('marketing_edit_slot', 'marketing_skip_slot', 'marketing_replan_week'):
        assert kind in actions.HANDLERS and f'"{kind}"' in m.MARKETING_PROMPT
    assert 'marketing_approve' not in actions.HANDLERS and 'never approve posts' in m.MARKETING_PROMPT


def test_a_time_chief_cannot_read_is_refused_plainly(idea):
    out = asyncio.run(m.edit_slot({'post_ids': idea['ids'], 'run_at': 'next tuesday-ish'}))
    assert out['ok'] is False and 'could not be read' in out['label'] and idea['calls']['edit'] == []


# ── Chief makes the post, then says where and when ─────────────────────

@pytest.fixture
def made(monkeypatch):
    calls = []

    async def config():
        return {'channels': [{'id': 'ig', 'service': 'instagram'}, {'id': 'x', 'service': 'twitter'},
                             {'id': 'fb', 'service': 'facebook'}]}

    async def create(req):
        calls.append(req)
        chosen = ['ig', 'x', 'fb'] if req.channel_ids is None else req.channel_ids
        skipped = [] if req.asset_id else [{'channel': 'Instagram', 'reason': 'Instagram needs a picture or video.'}]
        names = {'ig': 'Instagram', 'x': 'X', 'fb': 'Facebook'}
        kept = [c for c in chosen if req.asset_id or c != 'ig']
        return {'posts': [{'id': str(uuid4()), 'payload': {'service': c}} for c in kept], 'skipped': skipped,
                'run_at': '2026-10-05T15:00:00-04:00', 'already_saved': False, 'channels': [names[c] for c in kept]}
    monkeypatch.setattr(marketing, 'config', config)
    monkeypatch.setattr(marketing, 'create_idea', create)
    return calls


def test_chief_makes_a_post_for_every_channel_and_the_next_slot_without_asking(made):
    out = asyncio.run(m.new_post({'type': 'marketing_new_post', 'text': 'Answer the oldest client first.'}))
    req = made[0]
    assert req.channel_ids is None and req.run_at is None and req.ai_assisted is True
    assert out['ok'] and out['label'].startswith('Drafted for Monday 3:00 PM on X and Facebook.')
    assert 'waiting for your OK' in out['label'] and 'Instagram was left out: instagram needs a picture' in out['label']


def test_chief_honours_channels_the_owner_named(made):
    asyncio.run(m.new_post({'text': 'Only Facebook and X.', 'channels': ['Facebook', 'x']}))
    assert sorted(made[0].channel_ids) == ['fb', 'x']


def test_chief_new_post_is_retry_safe_and_a_drafts_action():
    import platform_chief_authority as authority
    request = uuid4()
    first = [{'type': 'marketing_new_post', 'text': 'A'}]
    again = [{'type': 'marketing_new_post', 'text': 'A'}]
    m.prepare_actions(first, request); m.prepare_actions(again, request)
    assert first[0]['id'] == again[0]['id']
    assert authority.GROUPS['marketing_new_post'] == 'drafts' and actions.HANDLERS['marketing_new_post'] is m.new_post
    assert 'do not ask first where or when' in m.MARKETING_PROMPT


def test_chief_keeps_links_out_of_a_new_post(made):
    out = asyncio.run(m.new_post({'text': 'See mysolutionist.app today'}))
    assert out['ok'] is False and made == []
