from datetime import timedelta
from pathlib import Path
import pytest
from fastapi import HTTPException
import dev_relay as store
import dev_cards
import rate_limit
from __tests__.dev_relay_fake import relay, run, D1, D2, S1, S2


def test_exact_retention_and_storage_order(relay):
    def ago(**kw):return store.z(relay.stamp-timedelta(**kw))
    relay.tables['dev_fleet_sessions']=[
        {'device_id':D1,'session_key':S1,'ended_at':ago(hours=25)},
        {'device_id':D1,'session_key':S2,'ended_at':ago(hours=2)},
        {'device_id':D2,'session_key':S1,'ended_at':ago(minutes=59)},
        {'device_id':D2,'session_key':S2,'ended_at':None}]
    relay.tables['dev_fleet_screens']=[dict(r) for r in relay.tables['dev_fleet_sessions']]
    relay.tables['dev_cards']=[{'id':D1,'expires_at':ago(seconds=1),'object_path':'old','thumb_path':'thumb'},
                               {'id':D2,'expires_at':store.z(relay.stamp+timedelta(seconds=1)),'object_path':'new'}]
    relay.uploads={'old':b'a','thumb':b'b','new':b'c'}
    relay.tables['dev_alerts']=[{'id':'old','created_at':ago(days=31)},{'id':'new','created_at':ago(days=29)}]
    relay.tables['dev_kai_messages']=[{'id':'old','created_at':ago(days=91)},{'id':'new','created_at':ago(days=89)}]
    relay.tables['dev_alert_dedupe']=[{'id':'ci','source':'ci','seen_at':ago(days=31)},
        {'id':'old','source':'kai','seen_at':ago(days=31)}]
    run(store.dev_relay_purge())
    assert len(relay.tables['dev_fleet_sessions'])==3
    assert {(r['device_id'],r['session_key']) for r in relay.tables['dev_fleet_screens']}=={(D2,S1),(D2,S2)}
    assert [r['id'] for r in relay.tables['dev_cards']]==[D2]
    assert list(relay.uploads)==['new']
    assert [r['id'] for r in relay.tables['dev_alerts']]==['new']
    assert [r['id'] for r in relay.tables['dev_kai_messages']]==['new']
    assert [r['id'] for r in relay.tables['dev_alert_dedupe']]==['ci']


def test_purge_pages_past_default_database_cap(relay):
    relay.tables['dev_cards']=[{'id':str(i),'expires_at':store.z(relay.stamp-timedelta(days=1))} for i in range(1101)]
    assert run(dev_cards.purge_cards(None,{'expires_at':f'lt.{store.z(relay.stamp)}'}))==1101
    assert not relay.tables['dev_cards']


def test_failed_storage_purge_preserves_pointer_for_retry(relay,monkeypatch):
    relay.tables['dev_cards']=[{'id':D1,'expires_at':store.z(relay.stamp-timedelta(days=1)),'object_path':'retry-me'}]
    async def fail(*a):raise HTTPException(502,'storage failed')
    monkeypatch.setattr(dev_cards,'_remove_objects',fail)
    with pytest.raises(HTTPException):run(store.dev_relay_purge())
    assert relay.tables['dev_cards'][0]['object_path']=='retry-me'


def test_missing_migration_fails_loud_without_echoing_payload(monkeypatch):
    monkeypatch.setattr(store, "_service_headers", lambda: {})
    class Response:
        status_code=404
        content=b'password=should-not-be-shown'
    class Client:
        async def request(self,*a,**kw):return Response()
    with pytest.raises(HTTPException) as e:run(store.db(Client(),'GET','dev_cards'))
    assert store.MIGRATION in e.value.detail and 'should-not-be-shown' not in e.value.detail


def test_configured_limits_reach_shared_window(monkeypatch):
    import sb_clients
    calls=[]
    monkeypatch.setattr(rate_limit,'_buckets',{})
    monkeypatch.setattr(rate_limit,'_shared_ok',True)
    monkeypatch.setattr(rate_limit,'shared_enabled',lambda:True)
    monkeypatch.setattr(sb_clients,'sb_post_as_service',lambda path,body:calls.append((path,body)) or True)
    assert rate_limit.allow_strict('dev_alert_push','owner',max_requests=1)
    assert not rate_limit.allow_strict('dev_alert_push','owner',max_requests=1)
    assert calls[0][1]['p_max']==1 and calls[0][1]['p_window_sec']==3600


def test_jobs_are_leader_gated_and_no_a2_jobs():
    source=Path('kmj_intake_automation.py').read_text(encoding='utf-8')
    assert 'g("dev_relay_purge", dev_relay_purge)' in source
    assert 'g("dev_alert_digest_tick", dev_alert_digest_tick)' in source
    assert 'g("dev_watch_tick"' not in source
