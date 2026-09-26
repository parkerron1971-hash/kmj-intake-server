"""Creative bridge boundaries; no paid generation or public posting in tests."""
import asyncio
import io
import pathlib
import sys
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import platform_chief_creative as creative
import platform_chief_actions as actions
import platform_marketing as marketing
import sb_clients
import spend_guard
import rate_limit
import platform_chief_authority as authority
from __tests__.test_platform_chief_authority import store
from auth_supabase import UserSession, require_user
from lead_admin import PLATFORM_OWNER_EMAIL

OWNER = SimpleNamespace(id=str(uuid4()), email=PLATFORM_OWNER_EMAIL)
BIZ = {'id': str(uuid4()), 'owner_id': OWNER.id, 'name': 'The Solutionist System'}

def run(coro): return asyncio.run(coro)

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(creative, 'platform_business', AsyncMock(return_value=BIZ))
    monkeypatch.setattr(creative.images, 'business', AsyncMock(return_value=BIZ))
    monkeypatch.setattr(creative.images, 'db', AsyncMock(return_value=[]))
    monkeypatch.setattr(spend_guard, 'over_budget', lambda *a: False)
    monkeypatch.setattr(rate_limit, 'allow', lambda *a: True)
    monkeypatch.setattr(authority, 'require_budget', AsyncMock())


def test_dispatch_binds_platform_and_resets_image_context(setup, monkeypatch):
    seen = []
    async def generate(client, biz, action):
        seen.append((biz, action, creative.images.turn_id.get(), sb_clients.get_current_user_jwt()))
        return {'result': 'Queued', 'label': 'Creating', 'image': {'id': str(uuid4()), 'status': 'queued'}}
    monkeypatch.setattr(creative.images, 'handle_generate_image', generate)
    rid = uuid4()
    async def check():
        with sb_clients.with_user_jwt('verified-test-token'):
            result = await creative.handlers(OWNER, rid)['generate_image']({'type':'generate_image', 'business_id':str(uuid4()), 'model':'untrusted', 'website_url':'http://private', 'prompt':'Make a flyer'})
            assert result['ok'] and result['business_id'] == BIZ['id']
        assert creative.images.turn_id.get() == ''
        assert sb_clients.get_current_user_jwt() is None
    run(check())
    assert seen == [(BIZ, {'prompt':'Make a flyer'}, str(rid), 'verified-test-token')]


def test_failure_resets_context_and_is_visible(setup, store, monkeypatch):
    monkeypatch.setattr(authority, "policy", AsyncMock(return_value={"settings": {"creative": "allow"}}))
    async def fail(*args): raise HTTPException(403, 'Reference belongs to another business.')
    monkeypatch.setattr(creative.images, 'handle_generate_image', fail)
    monkeypatch.setattr(actions, '_log_action', AsyncMock())
    async def check():
        with sb_clients.with_user_jwt('verified-test-token'):
            results = await actions.dispatch_actions([{'type':'generate_image','prompt':'Edit'}], extra_handlers=creative.handlers(OWNER, uuid4()), owner=OWNER, request_id=uuid4())
        assert results[0]['ok'] is False
        assert results[0]['approval']['status'] == 'uncertain'
        assert creative.images.turn_id.get() == ''
    run(check())


def test_one_paid_asset_per_turn(setup, monkeypatch):
    monkeypatch.setattr(creative.images, 'handle_generate_image', AsyncMock(return_value={'result':'Queued','label':'Queued'}))
    async def check():
        handlers = creative.handlers(OWNER, uuid4())
        with sb_clients.with_user_jwt('verified-test-token'):
            await handlers['generate_image']({'type':'generate_image','prompt':'Flyer'})
            with pytest.raises(HTTPException) as e:
                await handlers['create_video']({'type':'create_video','brief':'Video'})
            assert e.value.status_code == 422
    run(check())


@pytest.mark.parametrize('label,expected', [('standard','medium'), ('draft','low'), ('best','high'), (' low ','low')])
def test_quality_labels_match_engine_values(setup, monkeypatch, label, expected):
    async def generate(client, biz, action):
        assert action['quality'] == expected
        return {'result': 'Queued', 'label': 'Queued'}
    monkeypatch.setattr(creative.images, 'handle_generate_image', generate)
    async def check():
        with sb_clients.with_user_jwt('verified-test-token'):
            await creative.handlers(OWNER, uuid4())['generate_image']({'type':'generate_image','prompt':'A flyer','quality':label})
    run(check())


def test_creative_tools_have_no_publish_or_approval(setup):
    assert set(creative.handlers(OWNER, uuid4())) == {'generate_image','find_images','create_video','compose_flyer'}


def test_budget_blocks_before_generation(setup, monkeypatch):
    monkeypatch.setattr(spend_guard, 'over_budget', lambda *a: True)
    generate = AsyncMock()
    monkeypatch.setattr(creative.images, 'handle_generate_image', generate)
    with pytest.raises(HTTPException) as e:
        run(creative.handlers(OWNER, uuid4())['generate_image']({'type':'generate_image'}))
    assert e.value.status_code == 429
    generate.assert_not_called()


def test_import_requires_owner_and_verified_session():
    app = FastAPI(); app.include_router(marketing.router)
    client = TestClient(app)
    assert client.post('/platform/marketing/assets/from-chief', json={'image_id':str(uuid4())}).status_code in (401,403)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=str(uuid4()),email='tenant@example.com')
    assert client.post('/platform/marketing/assets/from-chief', json={'image_id':str(uuid4())}).status_code == 403


def test_import_only_reads_owned_original_and_deduplicates(setup, monkeypatch):
    iid = uuid4(); bid = BIZ['id']; calls = []
    raw = io.BytesIO(); Image.new('RGB',(2,2)).save(raw,'PNG')
    async def artwork(client, business_id, image_id):
        assert business_id == bid and image_id == iid
        return {'id':str(iid),'status':'ready'}
    monkeypatch.setattr(creative.images,'artwork',artwork)
    monkeypatch.setattr(creative.images,'original',AsyncMock(return_value=raw.getvalue()))
    async def save(file, *, asset_id):
        calls.append(asset_id)
        assert file.content_type == 'image/png'
        return {'id':str(asset_id)}
    monkeypatch.setattr(marketing,'save_asset',save)
    req = marketing.ChiefArtwork(image_id=iid)
    first=run(marketing.import_chief_artwork(req,OWNER,UserSession(OWNER,'test')))
    second=run(marketing.import_chief_artwork(req,OWNER,UserSession(OWNER,'test')))
    assert first == second and calls[0] == calls[1]


def test_import_rejects_foreign_artwork_before_public_copy(setup, monkeypatch):
    monkeypatch.setattr(creative.images,'artwork',AsyncMock(side_effect=HTTPException(404,'Not found')))
    save=AsyncMock();monkeypatch.setattr(marketing,'save_asset',save)
    with pytest.raises(HTTPException):
        run(marketing.import_chief_artwork(marketing.ChiefArtwork(image_id=uuid4()),OWNER,UserSession(OWNER,'test')))
    save.assert_not_called()


def test_video_retry_reuses_project_and_does_not_requeue(setup,monkeypatch):
    import video_studio as studio
    ids=[]
    def create(biz,body,owner,*,project_id):
        assert biz == BIZ['id'] and owner is OWNER
        ids.append(project_id)
        return {'id':str(project_id),'revision':1}
    monkeypatch.setattr(studio,'configuration',lambda:{'planning_available':True})
    monkeypatch.setattr(studio,'create',create)
    monkeypatch.setattr(studio,'detail',lambda *args:{'jobs':[{'id':'existing'}]})
    def never(*args): raise AssertionError('Duplicate planning job')
    monkeypatch.setattr(studio,'enqueue',never)
    rid=uuid4()
    for _ in range(2): run(creative.create_video(BIZ,OWNER,{'brief':'Make a 15 second video'},rid))
    assert ids[0] == ids[1]

def test_chief_endpoint_requires_review_before_paid_generation(setup, store, monkeypatch):
    import platform_console as console
    from auth_supabase import require_user_session
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-only')
    monkeypatch.setattr(console,'_service_headers',lambda: {})
    monkeypatch.setattr(console,'_build_snapshot',AsyncMock(return_value={}))
    monkeypatch.setattr(console,'log_api_usage',AsyncMock())
    monkeypatch.setattr(actions,'_log_action',AsyncMock())
    import httpx
    monkeypatch.setattr(console.llm_call,'apost',AsyncMock(return_value=httpx.Response(200,json={'content':[{'type':'text','text':'Requesting your flyer. [ACTION:{"type":"generate_image","prompt":"A clean Solutionist flyer"}]'}]})))
    async def generate(client,biz,action):
        assert sb_clients.get_current_user_jwt() == 'verified-owner-jwt'
        return {'result':'Image queued','label':'Creating your image','image':{'id':str(uuid4()),'business_id':biz['id'],'status':'queued'}}
    monkeypatch.setattr(creative.images,'handle_generate_image',generate)
    app=FastAPI();app.include_router(console.router)
    app.dependency_overrides[require_user]=lambda: OWNER
    app.dependency_overrides[require_user_session]=lambda: UserSession(OWNER,'verified-owner-jwt')
    with TestClient(app) as client:
        response=client.post('/platform/chief/message',json={'message':'Create the flyer','request_id':str(uuid4())})
    assert response.status_code == 200, response.text
    assert response.json()['actions_taken'][0]['approval']['status'] == 'pending'
    assert '[ACTION:' not in response.json()['reply']
