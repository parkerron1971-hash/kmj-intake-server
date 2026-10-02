"""Connection metadata is portable; access must end on account erasure."""
import asyncio
from types import SimpleNamespace

import pytest
import account_lifecycle as al


@pytest.mark.parametrize('table,secret',[
    ('connected_ai_devices','token_hash'),
    ('connected_ai_pairings','secret_hash'),
])
def test_export_asks_for_metadata_without_credential_hashes(table,secret):
    class Client:
        async def get(self,url,headers,params):
            assert url.endswith('/'+table)
            assert params['business_id']=='eq.example-business'
            fields=params['select'].split(',')
            assert '*' not in fields and secret not in fields
            assert {'id','business_id','provider','expires_at'} <= set(fields)
            return SimpleNamespace(status_code=200,json=lambda:[{'id':'example','provider':'claude'}])
    rows,complete=asyncio.run(al._fetch_table(Client(),table,'example-business'))
    assert complete and rows==[{'id':'example','provider':'claude'}]


def test_business_erasure_removes_connections_before_jobs(monkeypatch):
    deleted=[]
    async def noop(*args):return 0
    async def remove(client,table,business):
        assert business=='example-business'
        deleted.append(table)
        return 1
    class Client:
        async def delete(self,url,headers,params):
            assert params['id']=='eq.example-business'
            deleted.append('businesses')
            return SimpleNamespace(status_code=204)
    monkeypatch.setattr(al,'_release_sms_lines',noop)
    monkeypatch.setattr(al,'_delete_storage_objects',noop)
    monkeypatch.setattr(al,'_delete_table_rows',remove)
    counts=asyncio.run(al._delete_business(Client(),{'id':'example-business'}))
    for table in ('connected_ai_devices','connected_ai_pairings'):
        assert counts[table]==1
        assert deleted.index(table)<deleted.index('chief_jobs')<deleted.index('businesses')
