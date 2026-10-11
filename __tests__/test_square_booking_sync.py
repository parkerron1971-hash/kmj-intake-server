import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
import square_booking_sync as sync
import square_connector as sq
from test_square_connect import BIZ, USER, cfg, client
from test_square_booking_preview import CID, REV, connected, provider, booking, request

@pytest.fixture(autouse=True)
def switches(monkeypatch):
    monkeypatch.setenv('SQUARE_BOOKING_SYNC_ENABLED','true')


def mock_rpc(monkeypatch):
    calls=[]
    async def rpc(name, **params):
        calls.append((name,params))
        if name=='sync_claim': return [{'connection_id':CID,'selection_revision':REV,'lease':BIZ}]
        return True
    monkeypatch.setattr(sq,'rpc',rpc)
    return calls


def test_complete_snapshot_never_writes_native_bookings(monkeypatch,cfg):
    calls=mock_rpc(monkeypatch)
    async def read(biz,config,body,**limits):
        assert body.end_at-body.start_at==timedelta(days=93)
        assert limits=={'max_rows':5000,'max_requests':100}
        return {'truncated':False,'appointments':[{'id':'one','version':2}]}
    monkeypatch.setattr(sync.preview,'preview',read)
    assert asyncio.run(sync.sync_one(BIZ,USER,cfg))
    assert [c[0] for c in calls]==['sync_claim','sync_finish']
    assert calls[-1][1]['p_appointments']==[{'id':'one','version':2}]
    assert calls[-1][1]['p_error'] is None


@pytest.mark.parametrize('failure',['truncated','network','authorization','timeout'])
def test_partial_or_failed_read_preserves_last_copy(monkeypatch,cfg,failure):
    calls=mock_rpc(monkeypatch)
    async def read(*a,**k):
        if failure=='truncated': return {'truncated':True,'appointments':[{'id':'partial'}]}
        if failure=='timeout': raise asyncio.TimeoutError()
        if failure=='authorization': raise HTTPException(409,{'code':'square_authorization_required','secret':'do-not-store'})
        raise HTTPException(502,'private provider body')
    monkeypatch.setattr(sync.preview,'preview',read)
    asyncio.run(sync.sync_one(BIZ,USER,cfg))
    saved=calls[-1][1]
    assert saved['p_appointments']==[]
    assert saved['p_error']=={'truncated':'capacity','authorization':'authorization'}.get(failure,'unavailable')
    assert 'private' not in str(saved) and 'secret' not in str(saved)


def test_lost_lease_does_not_contact_provider(monkeypatch,cfg):
    async def rpc(*a,**k): return []
    async def read(*a,**k): pytest.fail('lost lease reached provider')
    monkeypatch.setattr(sq,'rpc',rpc); monkeypatch.setattr(sync.preview,'preview',read)
    assert asyncio.run(sync.sync_one(BIZ,USER,cfg)) is False


def test_worker_checks_pilot_owner_before_storage(monkeypatch,cfg):
    async def rpc(*a,**k): pytest.fail('not allowed')
    monkeypatch.setattr(sq,'rpc',rpc)
    assert asyncio.run(sync.sync_one(BIZ,BIZ,cfg)) is False


def test_kill_switch_blocks_worker_but_allows_removal(monkeypatch,cfg):
    monkeypatch.setenv('SQUARE_BOOKING_SYNC_ENABLED','false')
    calls=mock_rpc(monkeypatch)
    with pytest.raises(HTTPException): asyncio.run(sync.sync_one(BIZ,USER,cfg))
    with pytest.raises(HTTPException): asyncio.run(sync.set_enabled(BIZ,USER,cfg,sync.SyncSetting(connection_id=CID,selection_revision=REV,enabled=True)))
    assert asyncio.run(sync.set_enabled(BIZ,USER,cfg,sync.SyncSetting(connection_id=CID,selection_revision=REV,enabled=False)))=={'enabled':False}
    assert len(calls)==1 and calls[0][0]=='sync_set'


def test_status_has_stale_indicator_and_never_exposes_internal_state(monkeypatch,cfg,connected):
    async def db(*a,**k):
        assert 'lease' not in k['params']['select'] and 'owner_id' not in k['params']['select']
        return [{'enabled':True,'appointments':[], 'last_synced_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}]
    monkeypatch.setattr(sq,'db',db)
    result=asyncio.run(sync.state(BIZ,USER,cfg))
    assert result['stale'] and result['enabled']


def test_status_rechecks_disconnect(monkeypatch,cfg,connected):
    async def db(*a,**k):
        connected['status']='revocation_pending'
        return [{'enabled':True,'appointments':[{'id':'old'}]}]
    monkeypatch.setattr(sq,'db',db)
    with pytest.raises(HTTPException): asyncio.run(sync.state(BIZ,USER,cfg))


def test_sync_endpoints_require_owner_and_strict_consent(client,monkeypatch,connected):
    import square_connect_router as routes
    calls=mock_rpc(monkeypatch)
    body={'connection_id':CID,'selection_revision':REV,'enabled':True}
    response=client.put('/square/bookings/sync',params={'business_id':BIZ},json=body)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert client.put('/square/bookings/sync',params={'business_id':BIZ},json={**body,'enabled':'yes'}).status_code==422
    def deny(*a): raise HTTPException(403,'denied')
    monkeypatch.setattr(routes,'owner',deny)
    for method in ['get','put','post']:
        kwargs={'json':body} if method=='put' else {}
        assert getattr(client,method)('/square/bookings/sync',params={'business_id':BIZ},**kwargs).status_code==403
    assert len(calls)==1


@pytest.mark.parametrize('page',[{'bookings':None},{'bookings':{}},{'bookings':[None]}])
def test_invalid_list_cannot_clear_snapshot(monkeypatch,cfg,connected,page):
    provider(monkeypatch,lambda n,p:page)
    with pytest.raises(HTTPException): asyncio.run(sync.preview.preview(BIZ,cfg,request()))


def test_production_configuration_requires_explicit_gate(monkeypatch,cfg):
    monkeypatch.setenv('SQUARE_ENABLED','true')
    monkeypatch.setenv('SQUARE_ENVIRONMENT','production')
    for name,value in {'SQUARE_PRODUCTION_APPLICATION_ID':'sq0idp-real','SQUARE_PRODUCTION_APPLICATION_SECRET':cfg.secret,
        'SQUARE_TOKEN_ENCRYPTION_KEY':cfg.encryption_key,'SQUARE_REDIRECT_URI':cfg.callback,
        'SQUARE_APP_RETURN_URL':cfg.app_url,'SQUARE_PILOT_OWNER_IDS':USER}.items(): monkeypatch.setenv(name,value)
    monkeypatch.delenv('SQUARE_PRODUCTION_PILOT_APPROVED',raising=False)
    with pytest.raises(HTTPException): sq.config()
    monkeypatch.setenv('SQUARE_PRODUCTION_PILOT_APPROVED','true')
    assert sq.config().environment=='production'
    monkeypatch.setenv('SQUARE_PRODUCTION_APPLICATION_ID','sandbox-app')
    with pytest.raises(HTTPException): sq.config()
    monkeypatch.setenv('SQUARE_PRODUCTION_APPLICATION_ID','sq0idp-real')
    monkeypatch.setenv('SQUARE_PILOT_OWNER_IDS','*')
    with pytest.raises(HTTPException): sq.config()


def test_scheduler_filters_due_unleased_pilot_accounts_and_isolates_failures(monkeypatch,cfg):
    monkeypatch.setattr(sq,'config',lambda:cfg)
    calls=[]
    async def db(method,path,**kwargs):
        p=kwargs['params']
        assert path=='square_booking_sync' and method=='GET'
        assert p['environment']=='eq.sandbox' and p['owner_id']=='in.('+USER+')'
        assert p['limit']=='5' and p['order']=='due_at.asc'
        assert p['due_at'].startswith('lte.') and p['or'].startswith('(lease_until.is.null,lease_until.lt.')
        assert p['select']=='business_id,owner_id'
        return [{'business_id':BIZ,'owner_id':USER},{'business_id':'second','owner_id':USER}]
    async def one(business,owner,config):
        calls.append((business,owner))
        if business==BIZ: raise HTTPException(503,'private')
        return True
    monkeypatch.setattr(sq,'db',db);monkeypatch.setattr(sync,'sync_one',one)
    asyncio.run(sync.sync_due_tick())
    assert calls==[(BIZ,USER),('second',USER)]


def test_scheduler_storage_failure_is_safe_and_disabled_tick_is_silent(monkeypatch,cfg,caplog):
    monkeypatch.setattr(sq,'config',lambda:cfg)
    calls=[]
    async def db(*a,**k): calls.append(True);raise HTTPException(503,'private credentials')
    monkeypatch.setattr(sq,'db',db)
    asyncio.run(sync.sync_due_tick())
    assert len(calls)==1 and 'private' not in caplog.text
    monkeypatch.setenv('SQUARE_BOOKING_SYNC_ENABLED','false')
    asyncio.run(sync.sync_due_tick());assert len(calls)==1
