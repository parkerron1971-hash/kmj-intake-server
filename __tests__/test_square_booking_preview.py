import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException
import square_booking_preview as bp
import square_connector as sq
from test_square_connect import BIZ, USER, cfg, client

CID='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
REV='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
START=datetime(2026,10,1,tzinfo=timezone.utc)
LOC={'id':'L1','name':'Studio','status':'ACTIVE','timezone':'America/New_York'}


def request(days=7):
    return bp.PreviewRequest(connection_id=CID,selection_revision=REV,start_at=START,end_at=START+timedelta(days=days))


def booking(id='B1',**changes):
    return {'id':id,'version':1,'start_at':START.isoformat(),'location_id':'L1','status':'ACCEPTED',
            'appointment_segments':[{'duration_minutes':30,'service_variation_id':'private-service'}],
            'customer_id':'private-customer','customer_note':'private-note','seller_note':'private-staff-note',**changes}


@pytest.fixture
def connected(monkeypatch):
    state={'status':'connected','connection_id':CID,'selection_revision':REV,'selected_location_ids':['L1']}
    async def connection(*args): return state
    async def token(*args): return 'private-token'
    monkeypatch.setattr(sq,'connection',connection)
    monkeypatch.setattr(sq,'access_token',token)
    return state


def provider(monkeypatch,pages):
    calls=[]
    async def square(cfg,method,path,**kwargs):
        assert method=='GET'
        if path=='/v2/locations':return {'locations':[LOC]}
        assert path=='/v2/bookings'
        calls.append(kwargs['params'])
        return pages(len(calls),kwargs['params'])
    monkeypatch.setattr(sq,'square',square)
    return calls


def test_pagination_is_read_only_and_no_private_fields(monkeypatch,cfg,connected):
    calls=provider(monkeypatch,lambda n,p: {'bookings':[booking('B'+str(n))],**({'cursor':'page2'} if n==1 else {})})
    result=asyncio.run(bp.preview(BIZ,cfg,request()))
    assert len(calls)==2 and calls[1]['cursor']=='page2'
    assert result['shown_count']==2 and not result['truncated'] and result['read_only']
    assert 'private' not in str(result)
    assert result['appointments'][0]['service_duration_minutes']==30


def test_windows_split_and_boundary_dedup_keep_latest_version(monkeypatch,cfg,connected):
    boundary=START+timedelta(days=31)
    calls=provider(monkeypatch,lambda n,p: {'bookings':[booking(start_at=boundary.isoformat(),version=n)]})
    result=asyncio.run(bp.preview(BIZ,cfg,request(62)))
    assert len(calls)==2
    assert all(datetime.fromisoformat(p['start_at_max'])-datetime.fromisoformat(p['start_at_min'])<=timedelta(days=31) for p in calls)
    assert result['shown_count']==1 and result['appointments'][0]['version']==2


def test_filters_outside_range_and_foreign_location(monkeypatch,cfg,connected):
    provider(monkeypatch,lambda n,p: {'bookings':[booking('end',start_at=(START+timedelta(days=7)).isoformat()),booking('foreign',location_id='L2'),booking('valid',status='NO_SHOW')]})
    result=asyncio.run(bp.preview(BIZ,cfg,request()))
    assert [r['id'] for r in result['appointments']]==['valid']
    assert result['appointments'][0]['status']=='NO_SHOW'


@pytest.mark.parametrize('kind',['row','page'])
def test_limits_report_partial_results(monkeypatch,cfg,connected,kind):
    if kind=='row':
        monkeypatch.setattr(bp,'MAX_ROWS',2)
        provider(monkeypatch,lambda n,p:{'bookings':[booking('B'+str(i)) for i in range(3)]})
    else:
        monkeypatch.setattr(bp,'MAX_REQUESTS',1)
        provider(monkeypatch,lambda n,p:{'bookings':[booking()], 'cursor':'more'})
    result=asyncio.run(bp.preview(BIZ,cfg,request()))
    assert result['truncated'] is True
    assert result['shown_count'] in (1,2)


def test_repeated_cursor_fails_instead_of_hanging(monkeypatch,cfg,connected):
    calls=provider(monkeypatch,lambda n,p:{'bookings':[], 'cursor':'repeat'})
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,request()))
    assert e.value.status_code==502 and len(calls)==2


def test_changed_selection_discards_inflight_preview(monkeypatch,cfg,connected):
    def page(n,p):
        connected['selection_revision']=BIZ
        return {'bookings':[booking()]}
    provider(monkeypatch,page)
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,request()))
    assert e.value.status_code==409


@pytest.mark.parametrize('change',[{'status':'revocation_pending'},{'connection_id':BIZ}])
def test_disconnect_or_reconnect_discards_inflight_preview(monkeypatch,cfg,connected,change):
    def page(n,p):
        connected.update(change)
        return {'bookings':[booking()]}
    provider(monkeypatch,page)
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,request()))
    assert e.value.status_code==409


@pytest.mark.parametrize('days',[0,-1,94])
def test_invalid_range_never_calls_square(monkeypatch,cfg,connected,days):
    calls=provider(monkeypatch,lambda n,p:pytest.fail('invalid range reached Square'))
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,request(days)))
    assert e.value.status_code==422 and not calls


def test_naive_time_rejected(cfg,connected):
    body=request().model_copy(update={'start_at':datetime(2026,10,1)})
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,body))
    assert e.value.status_code==422


def test_no_selected_location_never_lists_bookings(monkeypatch,cfg,connected):
    connected['selected_location_ids']=[]
    calls=provider(monkeypatch,lambda n,p:pytest.fail('empty selection reached bookings'))
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,request()))
    assert e.value.status_code==422 and not calls


@pytest.mark.parametrize('ids',[['other-business'],['L1','L1']])
def test_bad_location_selection_does_not_write(monkeypatch,cfg,connected,ids):
    provider(monkeypatch,lambda n,p:{})
    async def no_rpc(*args,**kwargs):pytest.fail('invalid locations reached database')
    monkeypatch.setattr(sq,'rpc',no_rpc)
    body=bp.Selection(connection_id=CID,selection_revision=REV,location_ids=ids)
    with pytest.raises(HTTPException) as e:asyncio.run(bp.save_selection(BIZ,USER,cfg,body))
    assert e.value.status_code==422


def test_selection_save_cas_and_clear(monkeypatch,cfg,connected):
    provider(monkeypatch,lambda n,p:{})
    async def rpc(name,**kwargs):
        assert name=='save_locations' and kwargs['p_locations']==[]
        assert kwargs['p_connection']==CID and kwargs['p_selection_revision']==REV and kwargs['p_user']==USER
        return BIZ
    monkeypatch.setattr(sq,'rpc',rpc)
    result=asyncio.run(bp.save_selection(BIZ,USER,cfg,bp.Selection(connection_id=CID,selection_revision=REV,location_ids=[])))
    assert result['selection_revision']==BIZ and result['selected_location_ids']==[]


def test_upstream_failure_is_not_an_empty_success(monkeypatch,cfg,connected):
    def fail(n,p):raise HTTPException(502,'Square is unavailable')
    provider(monkeypatch,fail)
    with pytest.raises(HTTPException):asyncio.run(bp.preview(BIZ,cfg,request()))


def test_preview_endpoint_and_owner_gate(client,monkeypatch,connected):
    provider(monkeypatch,lambda n,p:{'bookings':[booking()]})
    response=client.post('/square/bookings/preview',params={'business_id':BIZ},json=request().model_dump(mode='json'))
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    import square_connect_router as routes
    def denied(*a):raise HTTPException(404,'business not found')
    monkeypatch.setattr(routes,'owner',denied)
    assert client.post('/square/bookings/preview',params={'business_id':BIZ},json=request().model_dump(mode='json')).status_code==404
    assert client.put('/square/locations',params={'business_id':BIZ},json={'connection_id':CID,'selection_revision':REV,'location_ids':['L1']}).status_code==404


def test_square_http_query_preserves_timezone_and_scope(monkeypatch,cfg):
    import httpx
    original=httpx.AsyncClient
    observed=[]
    def handler(req):
        observed.append(req)
        return httpx.Response(200,json={'bookings':[]})
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(sq.httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    asyncio.run(sq.square(cfg,'GET','/v2/bookings',token='private-token',params={
        'location_id':'L1','start_at_min':'2026-10-01T00:00:00+04:00','cursor':'opaque+cursor'}))
    assert observed[0].url.host=='connect.squareupsandbox.com'
    assert observed[0].url.params['start_at_min']=='2026-10-01T00:00:00+04:00'
    assert observed[0].url.params['cursor']=='opaque+cursor'
    assert observed[0].headers['Authorization']=='Bearer private-token'


def test_selection_cas_conflict_is_explicit(monkeypatch,cfg,connected):
    provider(monkeypatch,lambda n,p:{})
    async def rpc(*args,**kwargs):return None
    monkeypatch.setattr(sq,'rpc',rpc)
    with pytest.raises(HTTPException) as e:
        asyncio.run(bp.save_selection(BIZ,USER,cfg,bp.Selection(connection_id=CID,selection_revision=REV,location_ids=['L1'])))
    assert e.value.status_code==409


def test_inactive_saved_location_needs_reselection(monkeypatch,cfg,connected):
    async def square(*args,**kwargs):return {'locations':[{**LOC,'status':'INACTIVE'}]}
    monkeypatch.setattr(sq,'square',square)
    with pytest.raises(HTTPException) as e:asyncio.run(bp.preview(BIZ,cfg,request()))
    assert e.value.status_code==409
