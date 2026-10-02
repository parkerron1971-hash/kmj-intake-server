"""No external publishing. Exercise authorization, versioning and ambiguous writes."""
import asyncio
import copy
import io
import pathlib
import sys
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from starlette.datastructures import UploadFile, Headers

import platform_marketing as m
from buffer_client import BufferClient, BufferError
from auth_supabase import require_user
from lead_admin import PLATFORM_OWNER_EMAIL


def run(coro):
    return asyncio.run(coro)


def channel(**kw):
    return {'id':'channel-1','name':'Solutionist','service':'facebook',
            'isDisconnected':False,'isLocked':False,'isQueuePaused':False, **kw}


def cfg(**kw):
    return {'organization_id':'org-1','channels':[channel()],'paused':False, **kw}


@pytest.fixture
def state(monkeypatch):
    s = {'config':cfg(), 'writes':[], 'posts':[], 'assets':[]}
    async def config(): return s['config']
    async def db(method,path,body=None):
        if method == 'GET':
            return s['assets'] if 'assets' in path else s['posts']
        s['writes'].append((method,path,copy.deepcopy(body)))
        return [body]
    monkeypatch.setattr(m,'config',config)
    monkeypatch.setattr(m,'db',db)
    return s


def draft(**kw):
    return m.Draft(campaign='service-owners',text='Bring your business work together.',
        channel_id='channel-1',run_at=m.now()+timedelta(days=1),**kw)


def approved_row(state):
    row=run(m.build_draft(draft()))
    row.update(status='dispatching',approved_hash=row['content_hash'],approved_by=str(uuid4()))
    return row


def test_all_routes_require_verified_platform_owner(monkeypatch):
    app=FastAPI(); app.include_router(m.router)
    client=TestClient(app)
    assert client.get('/platform/marketing/status').status_code in (401,403)
    app.dependency_overrides[require_user]=lambda: SimpleNamespace(id=str(uuid4()),email='tenant@example.com')
    assert client.get('/platform/marketing/status').status_code == 403
    assert client.post('/platform/marketing/slot/edit',json={}).status_code == 403
    assert client.post('/platform/marketing/slot/cancel',json={}).status_code == 403
    assert client.post(f'/platform/marketing/posts/{uuid4()}/not-sent',json={}).status_code == 403
    assert client.post('/platform/marketing/assets').status_code == 403


def test_owner_status_does_not_return_key(state,monkeypatch):
    monkeypatch.setenv('BUFFER_API_KEY','secret-never-returned')
    app=FastAPI(); app.include_router(m.router)
    app.dependency_overrides[require_user]=lambda: SimpleNamespace(id=str(uuid4()),email=PLATFORM_OWNER_EMAIL)
    r=TestClient(app).get('/platform/marketing/status')
    assert r.status_code==200 and r.json()['configured']
    assert 'secret-never-returned' not in r.text


def test_tracking_replaces_tags_and_preserves_destination():
    url=m.tracked_link('https://mysolutionist.app/features?utm_medium=cpc&ref=partner#demo','twitter','fall','creative-1')
    parsed=urlsplit(url); tags=parse_qs(parsed.query)
    assert tags['utm_medium']==['organic_social'] and tags['utm_source']==['x']
    assert tags['ref']==['partner'] and parsed.fragment=='demo'


@pytest.mark.parametrize('url',['http://mysolutionist.app/','https://evil.test/','https://mysolutionist.app.evil.test/', 'https://user@mysolutionist.app/'])
def test_campaign_destination_scope(url):
    with pytest.raises(HTTPException): m.tracked_link(url,'facebook','a','b')


def test_asset_content_and_schedule_bound_into_review_hash(state):
    d=draft(); one=run(m.build_draft(d))
    two=run(m.build_draft(d.model_copy(update={'text':'A changed caption'})))
    three=run(m.build_draft(d.model_copy(update={'run_at':d.run_at+timedelta(hours=1)})))
    assert len({one['content_hash'],two['content_hash'],three['content_hash']})==3
    assert one['payload']['publish_text'].endswith(m.short_link(m.link_code(d.id)))
    assert one['link_code'] == m.link_code(d.id) and m.GO_CODE.match(one['link_code'])
    assert 'utm_' not in one['payload']['publish_text']
    assert 'utm_content=' in one['payload']['tracked_url']


@pytest.mark.parametrize('website', ['mysolutionist.app', 'https://mysolutionist.app/',
    'https://www.mysolutionist.app', '(mysolutionist.app).'])
def test_existing_landing_link_becomes_the_short_link_once(state, website):
    d = draft()
    link = m.short_link(m.link_code(d.id))
    row = run(m.build_draft(d.model_copy(update={'text': 'Claim your founding seat → ' + website})))
    expected = 'Claim your founding seat → ' + ('(' + link + ').' if website.startswith('(') else link)
    assert row['payload']['publish_text'] == expected
    assert m.post_payload(row)['text'] == expected
    assert expected.count('mysolutionist.app') == 1


@pytest.mark.parametrize('existing', ['mysolutionist.app/features',
    'mysolutionist.app.evil.test', 'info@mysolutionist.app'])
def test_other_destination_or_email_does_not_hide_landing_link(state, existing):
    d = draft()
    row = run(m.build_draft(d.model_copy(update={'text': 'See ' + existing})))
    assert row['payload']['publish_text'] == 'See ' + existing + '\n\n' + m.short_link(m.link_code(d.id))


def test_clean_link_preserves_functional_destination_and_trims_campaign(state):
    row = run(m.build_draft(draft(landing_url='https://mysolutionist.app/start?plan=founder&utm_source=old#offer')
        .model_copy(update={'campaign': ' Founding Seats Launch '})))
    assert row['campaign'] == 'Founding Seats Launch'
    assert row['payload']['publish_text'].endswith(m.short_link(row['link_code']))
    assert 'utm_' not in m.post_payload(row)['text']
    # The redirect behind the short link keeps the functional destination.
    tracked = urlsplit(row['payload']['tracked_url'])
    assert tracked.path == '/start' and tracked.fragment == 'offer'
    tags = parse_qs(tracked.query)
    assert tags['plan'] == ['founder'] and tags['utm_source'] == ['facebook']


def test_rejects_cross_account_draft(state):
    with pytest.raises(HTTPException) as e: run(m.build_draft(draft().model_copy(update={'channel_id':'other'})))
    assert e.value.status_code==422


def test_instagram_requires_owned_media(state):
    state['config']['channels']=[channel(service='instagram')]
    with pytest.raises(HTTPException): run(m.build_draft(draft()))
    state['assets']=[{'id':str(uuid4()),'kind':'video','url':'https://storage.example/video.mp4','sha256':'a'*64}]
    row=run(m.build_draft(draft(asset_id=state['assets'][0]['id'])))
    payload=m.post_payload(row)
    assert payload['metadata']['instagram']=={'type':'reel','shouldShareToFeed':True}
    assert payload['assets']==[{'video':{'url':'https://storage.example/video.mp4'}}]


def test_edit_invalidates_approval_and_uses_compare_and_swap(state):
    result=run(m.save_draft(draft(revision=2)))
    method,path,body=state['writes'][0]
    assert method=='PATCH' and 'revision=eq.2' in path and 'provider_id=is.null' in path
    assert body['approved_hash'] is None and body['approved_by'] is None
    assert body['status']=='draft' and result['revision']==3


def test_approval_passes_exact_versions_and_actor(state,monkeypatch):
    row=run(m.build_draft(draft())); state['posts']=[row]
    async def channels(self,org): return [channel()]
    monkeypatch.setattr(BufferClient,'channels',channels)
    actor=SimpleNamespace(id=str(uuid4()))
    run(m.approve(m.Review(items=[{'id':row['id'],'revision':1,'content_hash':row['content_hash']}]),actor))
    _,path,body=state['writes'][0]
    assert path=='/rpc/platform_marketing_approve' and body['actor']==actor.id
    assert body['items'][0]['content_hash']==row['content_hash']


class FakeBuffer:
    def __init__(self,error=None,channels=None): self.error=error; self.creates=[]; self.live=channels or [channel()]
    async def channels(self,org): return self.live
    async def create(self,payload):
        self.creates.append(payload)
        if self.error: raise self.error
        return {'id':'buffer-post-1','status':'buffer','externalLink':None}


def test_success_is_submitted_not_published(state):
    api=FakeBuffer(); run(m.dispatch(approved_row(state),api))
    assert len(api.creates)==1 and api.creates[0]['mode']=='shareNow'
    assert state['writes'][-1][2]['status']=='submitted'
    assert state['writes'][-1][2]['provider_id']=='buffer-post-1'


def test_timeout_is_uncertain_and_never_retried(state):
    api=FakeBuffer(BufferError('Timed out',True)); run(m.dispatch(approved_row(state),api))
    assert len(api.creates)==1 and state['writes'][-1][2]['status']=='uncertain'


@pytest.mark.parametrize('reason',['paused','channel','hash','disconnect'])
def test_preflight_prevents_wrong_or_unapproved_publish(state,reason):
    row=approved_row(state); api=FakeBuffer()
    if reason=='paused': state['config']['paused']=True
    if reason=='channel': state['config']['channels']=[]
    if reason=='hash': row['payload']['publish_text']='Changed behind approval'
    if reason=='disconnect': api.live=[channel(isDisconnected=True)]
    run(m.dispatch(row,api))
    assert api.creates==[] and state['writes'][-1][2]['status']=='failed'


def test_failed_receipt_storage_does_not_resend(state,monkeypatch):
    row=approved_row(state); api=FakeBuffer()
    async def broken(*args): raise HTTPException(503,'storage unavailable')
    monkeypatch.setattr(m,'db',broken)
    assert run(m.dispatch(row,api))['status']=='dispatching'   # left for the sweep, never re-sent
    assert len(api.creates)==1


def test_reconciliation_rejects_different_content(state,monkeypatch):
    row=approved_row(state); state['posts']=[row]
    async def post(self,id): return {'id':id,'channelId':'other-account','text':row['payload']['publish_text'],'status':'sent'}
    monkeypatch.setattr(BufferClient,'post',post)
    with pytest.raises(HTTPException) as e: run(m.reconcile(UUID(row['id']),m.Reconcile(provider_id='p1')))
    assert e.value.status_code==422 and not state['writes']


def test_buffer_transport_uses_variables_and_no_secret_in_body(monkeypatch):
    monkeypatch.setenv('BUFFER_API_KEY','private-key')
    def handle(req):
        assert req.url==httpx.URL('https://api.buffer.com')
        assert req.headers['authorization']=='Bearer private-key'
        assert b'private-key' not in req.content
        return httpx.Response(200,json={'data':{'createPost':{'__typename':'PostActionSuccess','post':{'id':'p1','status':'buffer'}}}})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            return await BufferClient(c).create({'text':'quotes " and $variables','channelId':'c'})
    assert run(go())['id']=='p1'


@pytest.mark.parametrize('status,uncertain',[(401,False),(403,False),(429,False),(500,True)])
def test_buffer_failure_classification_and_redaction(monkeypatch,status,uncertain):
    monkeypatch.setenv('BUFFER_API_KEY','private-key')
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,text='private-key sensitive details'))) as c:
            return await BufferClient(c).create({})
    with pytest.raises(BufferError) as e: run(go())
    assert e.value.uncertain==uncertain and 'private-key' not in str(e.value)


def test_worker_disabled_makes_no_claims(state,monkeypatch):
    monkeypatch.setenv('BUFFER_PUBLISHING','off')
    run(m.due_tick()); assert not state['writes']


def test_fake_image_is_rejected_before_storage(state):
    f=UploadFile(io.BytesIO(b'<html>not a png</html>'),filename='fake.png',headers=Headers({'content-type':'image/png'}))
    with pytest.raises(HTTPException) as e: run(m.upload_asset(f))
    assert e.value.status_code==422 and not state['writes']


def test_upload_persists_verified_bytes_without_overwrite(state,monkeypatch):
    blob=io.BytesIO(); Image.new('RGB',(16,16),'blue').save(blob,format='PNG'); data=blob.getvalue()
    monkeypatch.setenv('SUPABASE_URL','https://storage.example')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY','server-secret')
    original=httpx.AsyncClient
    requests=[]
    def handle(req):
        requests.append(req)
        assert req.headers['x-upsert']=='false' and req.content==data
        assert req.headers['content-type']=='image/png'
        return httpx.Response(200,json={})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    f=UploadFile(io.BytesIO(data),filename='flyer.png',headers=Headers({'content-type':'image/png'}))
    result=run(m.upload_asset(f))
    assert len(requests)==1 and result['sha256']==m.hashlib.sha256(data).hexdigest()
    assert result['sha256'] in result['url'] and 'server-secret' not in str(result)


def test_the_seven_caption_generator_is_retired():
    # 2026-10-02: the weekly plan is the one way a week is drafted. The old
    # generator had no number guard, no flyers and no play, so its posts never
    # fed what the plan learns from.
    paths = {r.path for r in m.router.routes}
    assert '/platform/marketing/week' not in paths and not hasattr(m, 'draft_week')


def test_a_blip_before_buffer_is_reached_tries_again(state, monkeypatch):
    row = approved_row(state); api = FakeBuffer()

    async def broken():
        raise HTTPException(503, 'Marketing storage is unavailable. Please retry.')
    monkeypatch.setattr(m, 'config', broken)
    patch = run(m.dispatch(row, api))
    assert api.creates == [] and patch['status'] == 'approved' and patch['claimed_at'] is None
    assert state['writes'][-1][2]['status'] == 'approved'       # the next tick claims it again


def test_a_payload_that_cannot_be_built_was_never_sent(state, monkeypatch):
    row = approved_row(state); api = FakeBuffer()
    monkeypatch.setattr(m, 'post_payload', lambda row: {}['missing'])
    patch = run(m.dispatch(row, api))
    assert api.creates == [] and patch['status'] == 'approved'


def test_a_result_that_cannot_be_recorded_is_left_for_the_sweep(state, monkeypatch):
    row = approved_row(state); api = FakeBuffer()

    async def down(*a, **k):
        raise HTTPException(503, 'down')
    monkeypatch.setattr(m, 'db', down)
    patch = run(m.dispatch(row, api))
    assert len(api.creates) == 1 and patch['status'] == 'dispatching'   # never re-created; swept to unconfirmed


def test_an_unknown_error_during_create_is_uncertain(state):
    api = FakeBuffer(RuntimeError('socket closed'))
    patch = run(m.dispatch(approved_row(state), api))
    assert len(api.creates) == 1 and patch['status'] == 'uncertain'


@pytest.fixture
def slot(monkeypatch):
    """Two channel posts of one idea, stored by id, with a db that filters by id."""
    x = channel(id='channel-2', name='SolutionistSys', service='twitter')
    s = {'config': cfg(channels=[channel(), x]), 'writes': [], 'rows': {}}

    async def config():
        return s['config']

    async def db(method, path, body=None):
        if method == 'GET' and path.startswith('/platform_marketing_posts?id=eq.'):
            key = path.split('id=eq.')[1].split('&')[0]
            return [copy.deepcopy(s['rows'][key])] if key in s['rows'] else []
        if method == 'GET':
            return []
        s['writes'].append((method, path, copy.deepcopy(body)))
        key = path.split('id=eq.')[1].split('&')[0]
        if method == 'PATCH' and key in s['rows']:
            s['rows'][key].update(copy.deepcopy(body))
            return [copy.deepcopy(s['rows'][key])]
        return []
    monkeypatch.setattr(m, 'config', config)
    monkeypatch.setattr(m, 'db', db)
    for cid in ('channel-1', 'channel-2'):
        row = run(m.build_draft(m.Draft(campaign='week-2026-10-05', text='Answer the oldest client first.',
                                        channel_id=cid, run_at=m.now() + timedelta(days=2), ai_assisted=True)))
        row.update(revision=1, status='approved', approved_hash=row['content_hash'], play_id='workflow_tip')
        s['rows'][row['id']] = row
    s['items'] = [{'id': k, 'revision': 1} for k in s['rows']]
    return s


def test_one_caption_rewrites_every_channel_and_sends_it_back_to_review(slot):
    out = run(m.edit_slot(m.SlotEdit(items=slot['items'], text='Reply to the client who waited longest.')))
    assert len(out['posts']) == 2
    for post in out['posts']:
        assert post['payload']['text'] == 'Reply to the client who waited longest.'
        assert post['status'] == 'draft' and post['approved_hash'] is None and post['revision'] == 2
        assert post['play_id'] == 'workflow_tip'              # what the plan learns from survives the edit
    assert all('revision=eq.1' in w[1] for w in slot['writes'])


def test_moving_an_idea_gives_it_a_fresh_delivery_window(slot):
    later = m.now() + timedelta(days=5)
    out = run(m.edit_slot(m.SlotEdit(items=slot['items'], run_at=later)))
    for post in out['posts']:
        assert m.aware(post['run_at']) == m.aware(later)
        assert m.aware(post['expires_at']) == m.aware(later) + timedelta(hours=6)


def test_every_channel_is_checked_before_any_is_saved(slot):
    with pytest.raises(HTTPException) as err:
        run(m.edit_slot(m.SlotEdit(items=slot['items'], text='x' * 270)))   # fine on Facebook, too long for X
    assert err.value.status_code == 422 and slot['writes'] == []


def test_a_stale_channel_refuses_the_whole_idea_before_any_write(slot):
    second = slot['items'][1]['id']
    slot['rows'][second]['revision'] = 2                    # changed since the desk was loaded
    with pytest.raises(HTTPException) as err:
        run(m.edit_slot(m.SlotEdit(items=slot['items'], text='Reply to the client who waited longest.')))
    assert err.value.status_code == 409 and 'Nothing was changed' in err.value.detail and slot['writes'] == []
    with pytest.raises(HTTPException):
        run(m.cancel_slot(m.SlotCancel(items=slot['items'])))
    assert slot['writes'] == []


def test_a_channel_that_changes_mid_write_is_named(slot, monkeypatch):
    real = m.save_draft
    calls = []

    async def flaky(draft):
        calls.append(draft.channel_id)
        if len(calls) == 2:
            raise HTTPException(409, 'Post changed or delivery has started. Refresh before editing.')
        return await real(draft)
    monkeypatch.setattr(m, 'save_draft', flaky)
    with pytest.raises(HTTPException) as err:
        run(m.edit_slot(m.SlotEdit(items=slot['items'], text='Reply to the client who waited longest.')))
    assert err.value.status_code == 409
    assert err.value.detail == ('Only part of this post was changed: Facebook changed, X did not. '
                                'Refresh the desk and try again.')


def test_an_edit_must_change_something(slot):
    with pytest.raises(HTTPException) as err:
        run(m.edit_slot(m.SlotEdit(items=slot['items'])))
    assert err.value.status_code == 422


def test_skipping_an_idea_cancels_each_channel(slot):
    out = run(m.cancel_slot(m.SlotCancel(items=slot['items'])))
    assert out['cancelled'] == 2 and all(p['status'] == 'cancelled' for p in out['posts'])


def test_only_an_unconfirmed_delivery_can_be_marked_not_sent(state):
    post_id = uuid4()
    run(m.mark_not_sent(post_id, m.Revision(revision=3)))
    method, path, body = state['writes'][-1]
    assert method == 'PATCH' and 'status=eq.uncertain' in path and 'provider_id=is.null' in path
    assert 'revision=eq.3' in path and body['status'] == 'failed' and body['revision'] == 4

    async def nothing(*a, **k):
        return []
    import platform_marketing
    state_db = platform_marketing.db
    try:
        platform_marketing.db = nothing
        with pytest.raises(HTTPException) as err:
            run(m.mark_not_sent(post_id, m.Revision(revision=3)))
        assert err.value.status_code == 409
    finally:
        platform_marketing.db = state_db


def test_a_post_that_does_not_go_out_tells_the_owner(state, monkeypatch):
    import marketing_desk
    monkeypatch.setenv('BUFFER_PUBLISHING', 'on')
    monkeypatch.setenv('BUFFER_API_KEY', 'key')
    row = approved_row(state)
    claims = [[row], []]
    told = []

    async def db(method, path, body=None):
        if path == '/rpc/platform_marketing_claim':
            return claims.pop(0)
        state['writes'].append((method, path, body))
        return [body]

    async def tell(rows):
        told.append(rows)
    monkeypatch.setattr(m, 'db', db)
    monkeypatch.setattr(marketing_desk, 'tell_owner_about_delivery', tell)
    state['config']['paused'] = True                        # the preflight refuses: a plain failure
    run(m.due_tick())
    assert len(told) == 1 and told[0][0]['status'] == 'failed' and told[0][0]['id'] == row['id']


def test_paid_attribution_does_not_count_organic_facebook_clicks():
    from platform_console import _traffic_kind, _growth_channel
    assert _traffic_kind({'fbclid':'organic-click'})=='unspecified'
    assert _growth_channel({'utm_source':'facebook','utm_medium':'organic_social'})=='facebook · organic'
    assert _growth_channel({'utm_source':'facebook','utm_medium':'paid_social'})=='facebook · paid'
    assert _traffic_kind({'gclid':'paid-click'})=='paid'


def test_partial_status_batch_keeps_other_posts_readable(monkeypatch):
    monkeypatch.setenv('BUFFER_API_KEY','private-key')
    async def go():
        transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':{'p0':None,'p1':{'id':'good','status':'sent'}},'errors':[{'message':'not found'}]}))
        async with httpx.AsyncClient(transport=transport) as c:
            return await BufferClient(c).posts(['missing','good'])
    assert run(go())['p1']['status']=='sent'
