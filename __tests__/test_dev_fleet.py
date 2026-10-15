from datetime import timedelta
from uuid import UUID
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import dev_fleet as f
import dev_bridge
import dev_relay as store
from __tests__.dev_relay_fake import relay, run, D1, D2, S1, S2


def session(key=S1, **kw):
    return f.FleetSession(key=key,kind='claude',owner='kai',state='working',**kw)


def sync(sessions, full=False, auth='Bearer one'):
    return run(f.fleet_sync(f.FleetBody(sessions=sessions,full=full),auth))


def screen(key=S1, rev=1, text='hello', auth='Bearer one'):
    return run(f.fleet_screen_put(key,f.ScreenBody(rev=rev,text=text),auth))


def test_full_snapshot_and_delta_are_device_scoped(relay):
    sync([session(),session(S2)],full=True)
    sync([session()],full=True,auth='Bearer two')
    sync([],full=False)
    assert all(r['state']=='working' for r in relay.tables['dev_fleet_sessions'])
    sync([session(S2)],full=True)
    states = {(r['device_id'],r['session_key']):r['state'] for r in relay.tables['dev_fleet_sessions']}
    assert states == {(D1,S1):'ended',(D1,S2):'working',(D2,S1):'working'}


@pytest.mark.parametrize('body',[f.FleetBody(sessions=[session()]*61),f.FleetBody(sessions=[session(last='a'*65536)])])
def test_snapshot_caps(relay,body):
    with pytest.raises(HTTPException) as e:
        run(f.fleet_sync(body,'Bearer one'))
    assert e.value.status_code==413


def test_actual_body_cap_counts_whitespace_and_unknown_fields(relay):
    app=FastAPI();app.include_router(f.router)
    with TestClient(app) as client:
        r=client.post('/dev-bridge/fleet',content=' '*65536+'{}',headers={'content-type':'application/json','authorization':'Bearer one'})
    assert r.status_code==413


def test_screen_revision_cadence_and_size(relay):
    sync([session()])
    assert screen(rev=3)=={'ok':True}
    assert screen(rev=2)=={'ok':True,'stale':True}
    with pytest.raises(HTTPException) as e: screen(rev=4)
    assert e.value.status_code==429
    relay.tick(1.5)
    screen(rev=4,text='line\n'*130+'sk-ant-'+'a'*30)
    got=run(f.fleet_screen_get(D1,S1,None,None))
    assert got['rev']==4 and len(got['text'].splitlines())==120 and '[redacted:token]' in got['text']
    assert run(f.fleet_screen_get(D1,S1,4,None))=={'ok':True,'rev':4,'unchanged':True}
    with pytest.raises(HTTPException) as e: screen(text='a'*16001)
    assert e.value.status_code==413


def test_unknown_and_other_device_screen_rejected(relay):
    sync([session()])
    for key,auth in [(S2,'Bearer one'),(S1,'Bearer two')]:
        with pytest.raises(HTTPException) as e: screen(key=key,auth=auth)
        assert e.value.status_code==404


def test_watch_expires_after_one_minute(relay):
    sync([session()])
    got=run(f.fleet_watch(f.WatchBody(device_id=D1,key=S1),None))
    result=sync([])
    assert result['watch']=={'key':S1,'until':got['until']} and result['phone_open']
    assert sync([],auth='Bearer two')['watch'] is None
    relay.tick(60)
    assert sync([])=={'ok':True,'watch':None,'phone_open':False}


def test_list_order_ended_retention_and_no_token_leak(relay):
    sync([session(),f.FleetSession(key=S2,kind='codex',owner='you',state='needs-you')])
    sync([session()],auth='Bearer two')
    sync([],full=True,auth='Bearer two')
    relay.tick(3601)
    got=run(f.fleet_list(None))
    assert [s['key'] for s in got['sessions']]==[S2,S1]
    assert all('token_hash' not in d for d in got['devices'])


def test_delete_and_revoke_are_scoped_and_token_stops(relay):
    for auth in ['Bearer one','Bearer two']:
        sync([session()],auth=auth); screen(auth=auth)
    run(f.fleet_clear_device('Bearer one'))
    assert {r['device_id'] for r in relay.tables['dev_fleet_screens']}=={D2}
    sync([session()]);screen()
    run(dev_bridge.revoke_device(UUID(D1),None))
    assert {r['device_id'] for r in relay.tables['dev_fleet_sessions']}=={D2}
    assert {r['device_id'] for r in relay.tables['dev_fleet_screens']}=={D2}
    with pytest.raises(HTTPException) as e: sync([])
    assert e.value.status_code==401
    run(f.fleet_clear(None))
    assert relay.tables['dev_fleet_sessions']==relay.tables['dev_fleet_screens']==[]


def test_string_caps_redaction_and_write_rate(relay,monkeypatch):
    sync([session(project='p'*100,last='API_KEY=hello',approval=f.Approval(id=1,what='Bearer abcd1234efgh'))])
    row=relay.tables['dev_fleet_sessions'][0]
    assert len(row['project'])==80 and row['last']=='API_KEY=[redacted:secret]'
    assert row['approval']['what']=='Bearer [redacted:token]'
    monkeypatch.setattr(f.rate_limit,'allow_strict',lambda *a,**kw:False)
    with pytest.raises(HTTPException) as e:sync([])
    assert e.value.status_code==429


def test_every_owner_route_is_gated_and_device_routes_require_token():
    import dev_kai, lead_admin
    from auth_supabase import require_user
    app=FastAPI(); app.include_router(dev_kai.router);app.include_router(dev_bridge.router)
    paths=[('/platform/dev-desk/fleet','GET'),('/platform/dev-desk/fleet/watch','POST'),
        ('/platform/dev-desk/fleet','DELETE'),(f'/platform/dev-desk/fleet/{D1}/{S1}/screen','GET'),
        (f'/platform/dev-desk/cards/{D1}','GET'),('/platform/dev-desk/alerts','GET'),
        ('/platform/dev-desk/alerts/read','POST'),('/platform/dev-desk/alerts/settings','GET'),
        ('/platform/dev-desk/alerts/settings','PUT'),('/platform/dev-desk/alerts/test','POST'),
        (f'/platform/dev-desk/devices/{D1}/revoke','POST')]
    with TestClient(app) as client:
        for path,method in paths:
            assert client.request(method,path,json={}).status_code==401
        app.dependency_overrides[require_user]=lambda:type('User',(),{'email':'not-owner@example.com'})()
        for path,method in paths:
            assert client.request(method,path,json={}).status_code==403
        assert client.post('/dev-bridge/fleet',json={'sessions':[]}).status_code==401


def test_screen_auth_runs_before_redaction(relay,monkeypatch):
    def unexpected(_):raise AssertionError('redaction ran before authentication')
    monkeypatch.setattr(f.dev_redact,'text',unexpected)
    with pytest.raises(HTTPException) as e:screen(auth=None)
    assert e.value.status_code==401
