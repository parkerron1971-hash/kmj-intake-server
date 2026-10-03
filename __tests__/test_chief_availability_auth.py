"""Real credential dispatch for the authenticated appointment-check path."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import chief_availability as ca
import chief_availability_readout as readout
import sb_clients
from __tests__.test_chief_availability import BIZ, BID, OWNER, OTHER, SERVICE, NOW, req


@pytest.fixture
def transport_setup(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://database.example')
    monkeypatch.setenv('SUPABASE_ANON', 'fixture-anon')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'fixture-service')


def execute(*, business=None, business_status=200, busy_status=200, busy_business=BID):
    calls=[]
    tables={'/rest/v1/businesses':[deepcopy(business or BIZ)], '/rest/v1/offerings':[deepcopy(SERVICE)],
            '/rest/v1/module_entries':[], '/rest/v1/calendar_busy_blocks':[
                {'id':'busy-fixture','business_id':busy_business,'starts_at':'2030-01-08T15:00:00Z','ends_at':'2030-01-08T17:00:00Z'}]}
    def respond(request):
        assert request.method=='GET' and request.content==b''
        path=request.url.path
        auth=request.headers['authorization']
        calls.append((path,auth,str(request.url)))
        if path=='/rest/v1/calendar_busy_blocks':
            # Reproduce the deployed table grants: user JWTs cannot read it.
            if auth!='Bearer fixture-service':
                return httpx.Response(403,json={'code':'42501','message':'permission denied'})
            assert request.url.params['business_id']=='eq.'+BID
            assert request.url.params['select']=='id,business_id,starts_at,ends_at'
            if busy_status!=200:
                return httpx.Response(busy_status,json={'message':'unavailable'})
        else:
            assert auth=='Bearer fixture-user', (path,auth)
            assert request.headers['apikey']=='fixture-anon'
            if path=='/rest/v1/businesses':
                assert request.url.params['id']=='eq.'+BID
                if business_status!=200:
                    return httpx.Response(business_status,json={'message':'denied'})
            else:
                assert request.url.params['business_id']=='eq.'+BID
        rows=tables[path]
        offset=int(request.url.params.get('offset','0'))
        return httpx.Response(200,json=rows[offset:offset+100])
    async def check():
        with sb_clients.with_user_jwt('fixture-user'):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                result=await ca.check_request(client,req(),BIZ,now=NOW)
                assert sb_clients.get_current_user_jwt()=='fixture-user'
                return result
    return asyncio.run(check()),calls


def test_authenticated_request_reads_only_server_owned_busy_rows_as_service(transport_setup):
    result,calls=execute()
    assert result['availability_check']['status']=='conflicts'
    assert [r['status'] for r in result['availability_check']['appointments']]==['conflict','conflict']
    assert result['actions_taken']==[]
    assert calls[0][0]=='/rest/v1/businesses'
    assert all(path=='/rest/v1/calendar_busy_blocks' for path,auth,_ in calls if auth=='Bearer fixture-service')
    assert sum(path=='/rest/v1/calendar_busy_blocks' for path,_,_ in calls)==2  # data + explicit empty page
    assert sb_clients.get_current_user_jwt() is None


@pytest.mark.parametrize('business_status', [401,403])
def test_failed_user_business_read_never_escalates_to_service(transport_setup,business_status):
    result,calls=execute(business_status=business_status)
    assert result['availability_check']['status']=='unavailable'
    assert len(calls)==1 and calls[0][1]=='Bearer fixture-user'


@pytest.mark.parametrize('changes', [{'owner_id':OTHER},{'owner_id':None},{'id':OTHER}])
def test_changed_owner_or_business_blocks_every_service_read(transport_setup,changes):
    result,calls=execute(business={**BIZ,**changes})
    assert result['availability_check']['status']=='unavailable'
    assert len(calls)==1 and calls[0][1]=='Bearer fixture-user'


@pytest.mark.parametrize('kwargs', [{'busy_status':403},{'busy_status':500},{'busy_business':OTHER}])
def test_service_error_or_cross_tenant_row_never_means_free(transport_setup,kwargs):
    result,_=execute(**kwargs)
    assert result['availability_check']['status']=='unavailable'
    assert 'appointments' not in result['availability_check']


def test_nonowner_readout_never_enters_checker_or_service_transport(monkeypatch):
    check=AsyncMock();service=AsyncMock()
    monkeypatch.setattr(ca,'check_request',check)
    monkeypatch.setattr(sb_clients,'sb_as_service',service)
    session=SimpleNamespace(user=SimpleNamespace(id=OTHER))
    assert asyncio.run(readout.serve_request(None,req(),session,BIZ)) is None
    check.assert_not_awaited();service.assert_not_awaited()


@pytest.mark.parametrize('method,path,body', [('POST','/calendar_busy_blocks?business_id=eq.fixture',{}),
    ('GET','/calendar_feeds?business_id=eq.fixture',None),('GET','/offerings?business_id=eq.fixture',None)])
def test_service_adapter_cannot_be_reused_for_writes_or_other_tables(monkeypatch,method,path,body):
    service=AsyncMock();monkeypatch.setattr(sb_clients,'sb_as_service',service)
    with pytest.raises(ValueError):
        asyncio.run(ca._busy_get(None,method,path,body))
    service.assert_not_awaited()
