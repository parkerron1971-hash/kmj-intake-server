from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
import dev_alerts as a
import dev_relay as store
from __tests__.dev_relay_fake import relay, run, D1, D2, S1


def config(relay, **changes):
    values=a.Settings().model_dump();values.update(changes)
    relay.tables['dev_alert_settings']=[{'id':1,'settings':values}]


def raise_one(**kw):
    return run(a.raise_alert(None,**{'source':'missions','kind':'ready','key':'one',
        'level':'warn','title':'Needs your go','body':'A plan is ready',**kw}))


def test_off_never_stores(relay,monkeypatch):
    config(relay,enabled=False)
    assert raise_one()=='off'
    config(relay,sources={'missions':'off'})
    assert raise_one()=='off'
    config(relay)
    monkeypatch.setenv('DEV_ALERTS','off')
    assert raise_one()=='off' and not relay.tables['dev_alerts']


def test_dedupe_increments_count_without_second_push_and_expires(relay):
    assert raise_one()=='pushed'
    assert raise_one()=='deduped'
    assert relay.tables['dev_alerts'][0]['count']==2 and len(relay.pushes)==1
    relay.tick(1801)
    assert raise_one()=='pushed'


def test_dedupe_is_device_scoped_and_kai_uses_content(relay):
    assert raise_one(device_id=D1)=='pushed'
    assert raise_one(device_id=D2)=='pushed'
    assert raise_one(source='kai',key='x')=='pushed'
    assert raise_one(source='kai',key='y')=='deduped'


def test_ci_dedupes_forever_and_sites_alert_on_each_transition(relay):
    assert raise_one(source='ci')=='pushed'
    relay.tick(86400)
    assert raise_one(source='ci')=='deduped'
    for key in ['down','up','down']:
        assert raise_one(source='sites',key=key)=='pushed'
        assert raise_one(source='sites',key=key)=='deduped'


def test_at_desk_and_inbox_source(relay):
    assert raise_one(away=False)=='inbox'
    assert raise_one(source='worker_finished')=='inbox'
    assert not relay.pushes


def test_phone_watching_suppresses_only_matching_target(relay):
    relay.tables['dev_bridge_devices'][0].update(kai_watch_until=store.z(relay.stamp.replace(hour=17)),
                                               fleet_open_until=store.z(relay.stamp.replace(hour=17)))
    assert raise_one(nav=a.NAV+'kai',device_id=D1)=='inbox'
    assert raise_one(key='two',nav=a.NAV+f'fleet:{D1}:{S1}',device_id=D1)=='inbox'
    assert raise_one(key='three',nav=a.NAV+'alerts',device_id=D1)=='pushed'
    assert raise_one(key='four',nav=a.NAV+'kai',device_id=D2)=='pushed'


def test_quiet_hours_and_urgent_breakthrough(relay):
    relay.stamp=datetime(2026,10,16,2,0,tzinfo=timezone.utc)  # 22:00 Eastern
    assert raise_one()=='quiet'
    assert raise_one(source='sites',level='urgent',key='site-down')=='pushed'
    quiet=a.Quiet(urgent_breaks_through=False).model_dump()
    config(relay,quiet=quiet)
    assert raise_one(source='deploys',level='urgent',key='failed')=='quiet'
    assert len(relay.pushes)==1


def test_morning_digest_respects_timezone_and_is_sent_once(relay):
    relay.stamp=datetime(2026,10,16,10,59,tzinfo=timezone.utc)
    assert raise_one()=='quiet'
    run(a.dev_alert_digest_tick());assert not relay.pushes
    relay.tick(60)
    run(a.dev_alert_digest_tick());run(a.dev_alert_digest_tick())
    assert len(relay.pushes)==1 and relay.pushes[0][0]=='1 more alerts'
    assert relay.tables['dev_alerts'][0]['digested_at']


def test_no_morning_digest_when_disabled(relay):
    config(relay,quiet=a.Quiet(morning_digest=False).model_dump())
    relay.stamp=datetime(2026,10,16,10,59,tzinfo=timezone.utc)
    assert raise_one()=='quiet'
    relay.tick(60);run(a.dev_alert_digest_tick())
    assert not relay.pushes


def test_twenty_per_hour_source_limit_and_digest(relay):
    config(relay,limits={'per_hour':20,'per_source_10min':100})
    assert [raise_one(key=str(i)) for i in range(21)]==['pushed']*20+['rate']
    run(a.dev_alert_digest_tick())
    assert len(relay.pushes)==21 and relay.pushes[-1][0]=='1 more alerts'
    assert raise_one(key='another')=='rate'
    run(a.dev_alert_digest_tick());assert len(relay.pushes)==21
    relay.tick(900);run(a.dev_alert_digest_tick());assert len(relay.pushes)==22


def test_per_source_budget_and_configurable_limit(relay):
    assert [raise_one(key=str(i)) for i in range(7)]==['pushed']*6+['rate']
    assert raise_one(source='worker_needs_you',key='other')=='pushed'
    config(relay,limits={'per_hour':1,'per_source_10min':1})
    assert raise_one(source='deploys')=='rate'


def test_urgent_email_fallback_is_once_per_thirty_minutes(relay):
    relay.push_count=0
    assert raise_one(source='sites',level='urgent')=='email'
    assert raise_one(source='sites',level='urgent',key='two')=='inbox'
    assert len(relay.emails)==1
    relay.tick(1801)
    assert raise_one(source='sites',level='urgent',key='three')=='email'
    config(relay,email_fallback='off')
    relay.tick(1801)
    assert raise_one(source='sites',level='urgent',key='four')=='inbox'
    assert len(relay.emails)==2


def test_kai_urgent_capped_and_seventh_notify_limited(relay):
    results=[raise_one(source='kai',title=f'Notice {i}',key=str(i),level='urgent') for i in range(7)]
    assert results==['pushed']*6+['rate']
    assert all(r['level']=='warn' for r in relay.tables['dev_alerts'])


@pytest.mark.parametrize('changes',[{'tz':'Mars/Olympus'},{'quiet':{'start':'24:00'}},
    {'quiet':{'end':'7:00'}},{'sources':{'bogus':'push'}},{'email_fallback':'all'},
    {'limits':{'per_hour':0}},{'extra':True}])
def test_settings_validation(changes):
    with pytest.raises(ValidationError):a.Settings(**changes)


def test_unknown_source_and_cross_device_card_rejected_before_batch_write(relay):
    with pytest.raises(ValidationError):a.Alert(key='x',source='bogus',title='x')
    own={'key':'x','source':'kai','title':'x'}
    relay.tables['dev_cards'].append({'id':D2,'device_id':D2,'expires_at':store.z(relay.stamp.replace(year=2027))})
    for bad in [dict(own,source='ci'),dict(own,card_id=D2)]:
        with pytest.raises(HTTPException):
            run(a.alerts_raise(a.AlertsBody(alerts=[a.Alert(**own),a.Alert(**bad)]),'Bearer one'))
    assert not relay.tables['dev_alerts']


def test_owner_inbox_read_count_and_test_route(relay):
    raise_one();raise_one(key='two')
    got=run(a.alerts_list(None,50,None));assert got['unread']==2 and len(got['alerts'])==2
    run(a.alerts_read(a.ReadBody(ids=[got['alerts'][0]['id']]),None))
    assert run(a.alerts_list(None,50,None))['unread']==1
    run(a.alerts_read(a.ReadBody(all=True),None))
    assert run(a.alerts_list(None,50,None))['unread']==0
    assert run(a.alerts_test(a.TestBody(),None))['delivered']=='pushed'


def test_feed_has_only_server_failures_and_this_devices_watch_results(relay):
    raise_one(source='kai',device_id=D1)
    raise_one(source='ci',key='global')
    raise_one(source='ci',key='other-device',device_id=D2)
    raise_one(source='deploys',key='success',level='info')
    raise_one(source='sites',key='own-watch',device_id=D1,watch_id=D1)
    got=run(a.alerts_feed(store.z(relay.stamp.replace(hour=15)),'Bearer one'))
    assert {r['source'] for r in got['alerts']}=={'ci','sites'} and len(got['alerts'])==2


def test_resend_only_uses_configured_owner_and_idempotency(monkeypatch):
    import email_sender
    sent=[]
    async def send(**kw):sent.append(kw);return {'id':'email'}
    monkeypatch.setattr(email_sender,'send_via_resend',send)
    monkeypatch.setenv('PLATFORM_OWNER_EMAIL','owner@example.com')
    assert run(a._email({'id':D1,'title':'Site down','body':'<script>oops</script>'}))
    assert sent[0]['to_email']=='owner@example.com' and sent[0]['idempotency_key']=='dev-alert-'+D1
    assert '<script>' not in sent[0]['body']


def test_default_settings_are_complete():
    s=a.Settings()
    assert s.tz=='America/New_York' and s.quiet.start=='22:00' and s.quiet.end=='07:00'
    assert s.sources['worker_finished']=='inbox' and s.email_fallback=='urgent'


def test_settings_round_trip_through_owner_http_route(relay,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    async def upsert(c,method,table,params=None,body=None,**kw):
        assert method=='POST' and table=='dev_alert_settings'
        relay.tables[table]=[body]
        return [body]
    monkeypatch.setattr(store,'db',upsert)
    app=FastAPI();app.include_router(a.router)
    app.dependency_overrides[a.require_owner]=lambda:object()
    saved=a.Settings(tz='UTC',quiet=a.Quiet(start='09:00',end='17:00'),
                     limits=a.Limits(per_hour=25,per_source_10min=7)).model_dump()
    with TestClient(app) as client:
        response=client.put('/platform/dev-desk/alerts/settings',json=saved)
        assert response.status_code==200 and response.json()['settings']==saved
        assert client.get('/platform/dev-desk/alerts/settings').json()['settings']==saved
        assert client.put('/platform/dev-desk/alerts/settings',json={**saved,'tz':'invalid'}).status_code==422


def test_device_cannot_claim_server_urgent_privileges(relay):
    body=a.AlertsBody(alerts=[a.Alert(key='worker',source='worker_needs_you',title='Need input',level='urgent')])
    run(a.alerts_raise(body,'Bearer one'))
    assert relay.tables['dev_alerts'][0]['level']=='warn'
