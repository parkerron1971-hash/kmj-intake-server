import asyncio
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from growth_intelligence import periods, report, normalize_bookings
import growth_intelligence_router as api
import chief_growth_intelligence_actions as chief

NOW = datetime(2026, 9, 16, 12, tzinfo=timezone.utc)
PREFS = {'timezone': 'UTC', 'currency': 'USD', 'weekly_hours': 30}
BID = '10000000-0000-4000-8000-000000000001'
RID = '20000000-0000-4000-8000-000000000001'


def invoice(id, person, paid, amount, **kw):
    return dict(id=id, contact_id=person, paid_at=paid, total=amount, status='paid', category='Consulting', **kw)


def data():
    return {'contacts': [{'id': 'a', 'name': 'Ada', 'created_at': '2026-01-01T00:00:00Z', 'source': 'Referral'},
                         {'id': 'b', 'name': 'Bea', 'created_at': '2026-09-01T00:00:00Z', 'source': 'Search'}],
            'invoices': [invoice('1', 'a', '2026-07-01T10:00:00Z', 100), invoice('2', 'a', '2026-08-03T10:00:00Z', 100),
                         invoice('3', 'a', '2026-09-02T10:00:00Z', 150), invoice('4', 'a', '2026-09-05T10:00:00Z', 150),
                         invoice('5', 'b', '2026-09-06T10:00:00Z', 200)],
            'sessions': [], 'campaigns': [], 'events': [], 'costs': [], 'attributions': [], 'actions': []}


def test_comparison_excludes_later_days_of_prior_month():
    d = data(); d['invoices'].append(invoice('late', 'a', '2026-08-20T10:00:00Z', 900))
    r = report(d, PREFS, now=NOW)
    assert r['previous']['collected'] == 100
    assert r['current']['collected'] == 500
    assert sum(x['value'] for x in r['drivers']) == r['change'] == 400


@pytest.mark.parametrize('period', ['mtd','qtd','ytd','30d','90d'])
@pytest.mark.parametrize('comparison', ['previous','year'])
def test_periods_have_equal_duration_and_no_future(period, comparison):
    a,b,c,d = periods(period, comparison, now=NOW)
    assert b == NOW and d <= a and b-a == d-c


def test_short_month_is_capped_without_overlapping_current():
    a,b,c,d = periods(now=datetime(2026,3,31,12,tzinfo=timezone.utc))
    assert d == a and c.day == 1 and c.month == 2


def test_custom_timezone_and_invalid_range():
    a,b,c,d = periods('custom', now=NOW, tz='America/New_York', start='2026-09-01', end='2026-09-03')
    assert a.hour == 0 and a.utcoffset().total_seconds() == -14400 and (b-a).days == 3
    with pytest.raises(ValueError): periods('custom', now=NOW, start='2026-10-01', end='2026-10-02')


def test_zero_baseline_and_empty_business_are_not_infinite_growth():
    r = report({}, PREFS, now=NOW)
    assert r['change_pct'] is None and r['current']['average_purchase'] is None
    assert r['capacity']['rebooking_rate'] is None and r['cohorts'] == []


def test_first_payment_not_contact_creation_defines_new_buyer():
    d = data(); d['contacts'][1]['created_at'] = '2020-01-01T00:00:00Z'
    r = report(d, PREFS, now=NOW)
    assert r['current']['new_buyers'] == 1 and r['current']['new_revenue'] == 200
    assert r['current']['returning_buyers'] == 1


def test_missing_dates_currency_and_unlinked_money_are_explicit():
    d = data(); d['invoices'] += [invoice('x', None, '2026-09-04T10:00:00Z', 50), invoice('eur', 'a', '2026-09-04T10:00:00Z', 999, currency='EUR'), invoice('missing', 'a', None, 800)]
    r = report(d, PREFS, now=NOW)
    assert r['current']['collected'] == 550
    assert r['quality']['other_currency_invoices'] == 1 and r['quality']['missing_payment_dates'] == 1
    assert r['quality']['unlinked_collections'] == 50
    assert sum(x['value'] for x in r['drivers']) == r['change']


def test_cohort_only_counts_mature_buyers_and_actual_repeat_payments():
    r = report(data(), PREFS, now=NOW)
    september = next(c for c in r['cohorts'] if c['month'] == '2026-09')
    july = next(c for c in r['cohorts'] if c['month'] == '2026-07')
    assert all(c['rate'] is None and c['eligible'] == 0 for c in september['cells'])
    assert july['cells'][0]['rate'] == 0 and july['cells'][1]['rate'] == 100
    assert july['cells'][2]['rate'] is None


def test_marketing_credit_requires_explicit_link_and_never_counts_spend_twice():
    d = data(); d['campaigns'] = [{'id': 'c', 'name': 'Fall', 'status': 'running'}]
    d['costs'] = [{'id': 'cost', 'date':'2026-09-01', 'kind':'marketing','source':'SEARCH', 'amount':40, 'campaign_id':'c'}]
    r = report(d, PREFS, now=NOW)
    assert r['campaigns'][0]['credited_revenue'] == 0
    assert next(c for c in r['channels'] if c['source'] == 'search')['cost_per_new_buyer'] == 40
    d['attributions'] = [{'invoice_id':'5','campaign_id':'c','evidence':'Buyer supplied campaign code'}]
    r = report(d, PREFS, now=NOW)
    assert r['campaigns'][0]['credited_revenue'] == 200 and r['campaigns'][0]['return_on_spend'] == 5


def test_missing_direct_costs_are_unknown_not_full_margin():
    d = data(); r = report(d, PREFS, now=NOW)
    assert all(p['margin'] is None for p in r['profitability'])
    d['costs'] = [{'id':'c','date':'2026-09-01','kind':'direct','offering':'Consulting','contact_id':'a','amount':100,'hours':5}]
    r = report(d, PREFS, now=NOW)
    service = next(p for p in r['profitability'] if p['dimension'] == 'offering')
    assert service['contribution'] == 400 and service['margin'] == 80
    assert service['revenue_per_hour'] == 100


def test_capacity_excludes_cancelled_future_and_flags_missing_durations():
    d = data(); d['sessions'] = [
        {'id':'s1','contact_id':'a','status':'scheduled','scheduled_for':'2026-09-18T12:00:00Z','duration_minutes':120},
        {'id':'s2','contact_id':'a','status':'cancelled','scheduled_for':'2026-09-19T12:00:00Z','duration_minutes':600},
        {'id':'s3','contact_id':'b','status':'scheduled','scheduled_for':'2026-09-20T12:00:00Z'}]
    r = report(d, PREFS, now=NOW)
    assert r['capacity']['booked_hours'] == 2 and r['capacity']['open_hours'] == 58
    assert r['capacity']['missing_duration'] == 1 and r['capacity']['booked_count'] == 2
    assert report(d, {}, now=NOW)['capacity']['utilization'] is None


def test_action_window_is_independent_of_report_and_scoped_to_audience():
    d = data(); d['actions'] = [{'id':'a1','title':'Follow up','start_date':'2026-09-01','due_date':'2026-09-30','metric':'revenue','target':400,'contact_ids':['a']}]
    a = report(d, PREFS, now=NOW)['actions'][0]
    assert a['current'] == 300 and a['baseline'] == 100 and a['progress'] == 75


def test_interaction_history_keeps_prior_touch_when_latest_changes():
    d = data(); d['events'] = [{'contact_id':'a','kind':'interaction','occurred_at':'2026-08-03T12:00:00Z'}, {'contact_id':'a','kind':'interaction','occurred_at':'2026-09-02T12:00:00Z'}]
    r = report(d, PREFS, now=NOW)
    assert r['engagement']['current'] == r['engagement']['previous'] == 1


def action_payload(**updates):
    return {'title':'Follow up','start_date':'2026-09-01','due_date':'2026-09-30','metric':'revenue','target':200, **updates}


def test_invalid_values_and_unknown_fields_are_rejected():
    for fields in (action_payload(target=float('nan')), action_payload(target=-1), action_payload(title='   '), action_payload(unrecognized=True)):
        with pytest.raises(ValueError): api.GrowthAction(**fields)


def test_save_stale_version_cannot_overwrite_newer_record(monkeypatch):
    seen=[]
    async def fake(client, method, path, body=None):
        seen.append((method,path,body))
        return [{'id':RID,'revision':3,'data':action_payload()}] if method == 'GET' else []
    monkeypatch.setattr(api,'db',fake)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.save_record(None,BID,'actions',api.SaveRecord(id=RID,revision=2,data=action_payload())))
    assert exc.value.status_code == 409
    assert f'business_id=eq.{BID}' in seen[-1][1] and 'revision=eq.2' in seen[-1][1]


def test_foreign_link_is_rejected_before_any_write(monkeypatch):
    seen=[]
    async def fake(client,method,path,body=None): seen.append((method,path)); return []
    monkeypatch.setattr(api,'db',fake)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.save_record(None,BID,'actions',api.SaveRecord(data=action_payload(contact_ids=[RID]))))
    assert exc.value.status_code == 422 and all(m == 'GET' for m,p in seen)
    assert f'business_id=eq.{BID}' in seen[0][1]


def test_create_retry_is_idempotent(monkeypatch):
    stored=[]
    async def fake(client,method,path,body=None):
        if method == 'POST': stored.append({**body,'revision':1}); return stored
        return stored
    monkeypatch.setattr(api,'db',fake)
    req = api.SaveRecord(data=action_payload())
    a=asyncio.run(api.save_record(None,BID,'actions',req)); b=asyncio.run(api.save_record(None,BID,'actions',req))
    assert a==b and len(stored)==1


def test_paginated_reads_continue_when_server_page_cap_is_lower(monkeypatch):
    seen=[]
    async def fake(client,method,path,body=None):
        seen.append(path); offset=int(path.split('offset=')[1]); return [{'id':str(offset)}] if offset<3 else []
    monkeypatch.setattr(api,'db',fake)
    assert len(asyncio.run(api.all_rows(None,'invoices',BID)))==3
    assert len(seen)==4 and all(f'business_id=eq.{BID}' in p for p in seen)


def test_upstream_failure_never_becomes_empty_data(monkeypatch):
    monkeypatch.setattr(api.sb_clients,'sb_headers_service',lambda: {})
    monkeypatch.setattr(api.sb_clients,'sb_url',lambda: 'https://example.invalid')
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500,json={'message':'down'}))) as client:
            with pytest.raises(HTTPException) as exc: await api.db(client,'GET','/invoices')
            assert exc.value.status_code==502
    asyncio.run(check())


def test_chief_and_http_use_identical_shared_mutation_core(monkeypatch):
    calls=[]
    async def save(client,bid,kind,req): calls.append((bid,kind,req.data)); return {'id':RID,'revision':1}
    monkeypatch.setattr(chief,'save_record',save)
    r=asyncio.run(chief.handle_save_growth_record(None,{'id':BID},{'kind':'actions','data':action_payload()}))
    assert calls[0][0]==BID and r['result'] and r['label'] and not r.get('failed')
    assert r['frontend_event']['detail']['business_id']==BID


def test_chief_failed_save_does_not_claim_success(monkeypatch):
    async def save(*args): raise HTTPException(409,'Refresh the record')
    monkeypatch.setattr(chief,'save_record',save)
    r=asyncio.run(chief.handle_save_growth_record(None,{'id':BID},{'kind':'actions','data':action_payload()}))
    assert r['failed'] and r['label'] and r['result']=='Refresh the record' and 'frontend_event' not in r


def test_authorize_requires_business_owner_or_verified_team_role(monkeypatch):
    async def fake(*args): return [{'id':BID,'owner_id':'owner'}]
    monkeypatch.setattr(api,'db',fake)
    assert asyncio.run(api.authorize(None,BID,SimpleNamespace(id='owner')))['id']==BID
    import sys, types
    def refuse(*args): raise HTTPException(403,'Forbidden')
    monkeypatch.setitem(sys.modules,'business_users_router',types.SimpleNamespace(require_role=refuse))
    with pytest.raises(HTTPException) as exc: asyncio.run(api.authorize(None,BID,SimpleNamespace(id='other'),True))
    assert exc.value.status_code==403


def test_native_tools_and_classification_are_registered():
    import action_registry
    assert action_registry.is_read_only('growth_report')
    assert action_registry.reversibility('save_growth_record')=='A'
    assert chief.WRITE_SCHEMA[1]['required']==['kind','data']


def test_booking_mirrors_are_counted_once_and_reschedules_use_booking_truth():
    sessions=[{'id':'s','notes':'Booked online. [booking:e]','status':'scheduled','scheduled_for':'2026-09-17T10:00:00Z','duration_minutes':60}]
    entries=[{'id':'e','appointment_at':'2026-09-18T10:00:00Z','duration_min_at_booking':90,'status':'active','data':{'contact_id':'a'}}]
    combined=normalize_bookings(sessions,entries)
    assert len(combined)==1 and combined[0]['scheduled_for']=='2026-09-18T10:00:00Z' and combined[0]['duration_minutes']==90
    entries[0]['status']='archived'
    assert normalize_bookings(sessions,entries)[0]['status']=='cancelled'


def test_custom_cost_end_is_inclusive_without_next_day():
    d = data()
    d['costs'] = [{'date': '2026-09-03', 'kind': 'overhead', 'amount': 100}, {'date': '2026-09-04', 'kind': 'overhead', 'amount': 900}]
    r = report(d, PREFS, period='custom', start='2026-09-01', end='2026-09-03', now=NOW)
    assert r['overhead'] == 100


def test_currency_changes_never_relabel_recorded_costs_or_targets():
    d = data()
    d['costs'] = [{'date': '2026-09-03', 'kind': 'overhead', 'amount': 100, 'currency': 'USD'}]
    d['actions'] = [dict(action_payload(), id=RID, currency='USD')]
    r = report(d, dict(PREFS, currency='EUR'), now=NOW)
    assert r['overhead'] == 0 and r['current']['collected'] == 0
    assert r['actions'][0]['currency'] == 'USD' and r['actions'][0]['current'] == 500


def test_capacity_days_reconcile_and_undated_sessions_do_not_break_rebooking():
    d = data()
    d['sessions'] = [
        {'id':'s1','contact_id':'a','status':'completed','scheduled_for':'2026-09-02T12:00:00Z'},
        {'id':'s2','contact_id':'a','status':'scheduled','scheduled_for':None},
        {'id':'s3','contact_id':'a','status':'scheduled','scheduled_for':'2026-09-18T12:00:00Z','duration_minutes':60},
    ]
    r = report(d, PREFS, now=NOW)
    assert r['capacity']['rebooking_rate'] == 100
    assert sum(day['bookings'] for day in r['capacity']['days']) == r['capacity']['booked_count']


def test_update_retry_returns_existing_revision_without_another_write(monkeypatch):
    fields = api.GrowthAction(**action_payload(currency='USD')).model_dump(mode='json')
    old = {'id': RID, 'kind':'actions', 'revision':3, 'last_request_id':BID, 'data':fields}
    seen = []
    async def fake(client, method, path, body=None):
        seen.append(method)
        return [old]
    monkeypatch.setattr(api, 'db', fake)
    result = asyncio.run(api.save_record(None, BID, 'actions', api.SaveRecord(id=RID,revision=2,request_id=BID,data=fields)))
    assert result['revision'] == 3 and seen == ['GET']


def test_chief_recall_pages_lists_and_can_fetch_complete_record():
    r = report(data(), PREFS, now=NOW)
    rows = [dict(action_payload(), id=str(i), revision=1, notes='x'*4000, contact_ids=[RID]*200) for i in range(12)]
    r.update(records={'actions':rows,'costs':[],'attributions':[]}, preferences=PREFS)
    page = chief.recall_view(r, {'section':'records','kind':'actions','offset':5})
    assert len(page['rows']) == 5 and page['next_offset'] == 10 and 'notes' not in page['rows'][0]
    full = chief.recall_view(r, {'record_id':'7'})
    assert full['record']['notes'] == 'x'*4000 and len(full['record']['contact_ids']) == 200


def test_native_chief_growth_read_and_write_use_registered_handlers(monkeypatch):
    import json
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    assert cos.ACTION_HANDLERS['growth_report'] is chief.handle_growth_report
    assert cos.ACTION_HANDLERS['save_growth_record'] is chief.handle_save_growth_record
    assert 'growth_report' in {t['name'] for t in ctl.read_tool_definitions()}
    assert 'save_growth_record' in {t['name'] for t in ctl.write_tool_definitions()}
    r = report(data(), PREFS, now=NOW)
    r.update(records={'actions':[],'costs':[],'attributions':[]}, preferences=PREFS)
    async def load(*args): return r
    monkeypatch.setattr(chief,'load_report',load)
    saved=[]
    async def save(client,bid,kind,req):
        saved.append((bid,kind,req.data))
        return {'id':RID,'revision':1, **req.data}
    monkeypatch.setattr(chief,'save_record',save)
    # Spy only the existing policy door; tool dispatch and Growth handlers are real.
    async def door(client,biz,actions,**kwargs):
        return [await cos.ACTION_HANDLERS[a['type']](client,biz,a) for a in actions]
    monkeypatch.setattr(cos,'_execute_actions',door)
    async def run():
        ctl.reset_turn(writes_allowed=True)
        error, text = await ctl.execute_tool_use(None, {'id':BID}, 'growth_report', {})
        assert not error and json.loads(text)['data']['current']['collected'] == 500
        error, text = await ctl.execute_tool_use(None, {'id':BID}, 'save_growth_record', {'kind':'actions','data':action_payload()})
        assert not error and json.loads(text)['data']['id'] == RID
        assert ctl.writes_this_turn()[0]['frontend_event']['detail']['business_id'] == BID
        ctl.reset_turn(writes_allowed=False)
    asyncio.run(run())
    assert saved[0][0] == BID
