"""Solutionist's own marketing desk on the suite (B15, platform_suite.py,
platform_marketing_suite.py).

Behind MC_MARKETING_SUITE (off by default) and PLATFORM_BUSINESS_ID:
Mission Control's desk reads and writes the suite's store for Solutionist's
own business only, the platform owner alone; nothing new goes to Buffer
while it is on and what was approved before drains; exactly one of the two
weekly loops plans a week; the platform's profile, numbers, plays and caption
rules are used for that business and no other; its links are
mysolutionist.app/go/<code>. With the switch off nothing changes (the
existing platform and suite test files run unchanged).

No network: PostgREST, the platform tables, Buffer, the model and Image
Studio are fakes at the seams (the B4 and B9 suites' fakes, extended).
"""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import re
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '__tests__'))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import business_marketing as bm
import business_marketing_clips as clips
import business_marketing_engine as eng
import business_marketing_links as links
import business_marketing_outcomes as outcomes
import business_marketing_planner as plan
import business_marketing_store as store
import marketing_engine as platform
import marketing_profile as prof
import marketing_signals as msig
import platform_chief_marketing as pcm
import platform_marketing as m
import platform_marketing_suite as suite
import platform_suite
import rate_limit
import sb_clients
import spend_guard
from auth_supabase import require_user
from lead_admin import PLATFORM_OWNER_EMAIL

import test_business_marketing_api as api                     # noqa: E402  (B4's fakes)
from test_business_marketing_planner import business as biz_row, connection as conn_row  # noqa: E402
from test_business_marketing_week import w  # noqa: E402,F401  (B9's fixture: the planner's seams)

REAL_READ_SIGNALS = msig.read_signals
REAL_READ_PROFILE = prof.read_profile
run = asyncio.run

PID = 'b1500000-0000-4000-8000-000000000015'          # Solutionist's own business
KEVIN = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'        # its owner, the platform owner
PFB = 'c1500000-0000-4000-8000-000000000001'
PIG = 'c1500000-0000-4000-8000-000000000002'
NEW_YORK = ZoneInfo('America/New_York')


def platform_row(**over):
    row = {'id': PID, 'owner_id': KEVIN, 'name': 'The Solutionist System', 'type': 'saas', 'comp_tier': None,
           'subscription_status': None, 'subscription_plan': None, 'trial_ends_at': None,
           'stripe_subscription_id': None, 'voice_profile': {}, 'settings': {'platform_books': True}}
    row.update(over)
    return row


def switch(monkeypatch, *, on=True, pid=PID):
    if on:
        monkeypatch.setenv('MC_MARKETING_SUITE', 'on')
    else:
        monkeypatch.delenv('MC_MARKETING_SUITE', raising=False)
    if pid:
        monkeypatch.setenv('PLATFORM_BUSINESS_ID', pid)
    else:
        monkeypatch.delenv('PLATFORM_BUSINESS_ID', raising=False)


class Verdicts:
    """The reads behind platform_suite's verdict: the business rows (the
    narrow select) and the auth users' addresses."""

    def __init__(self):
        self.rows = {PID: {'id': PID, 'owner_id': KEVIN, 'platform_books': 'true'},
                     api.BIZ: {'id': api.BIZ, 'owner_id': api.OWNER, 'platform_books': None}}
        self.emails = {KEVIN: PLATFORM_OWNER_EMAIL, api.OWNER: 'owner@fadestreet.com'}
        self.fail_rows = self.fail_auth = False
        self.reads = []


@pytest.fixture(autouse=True)
def verdicts(monkeypatch):
    platform_suite.forget()
    v = Verdicts()

    def read_business(bid):
        v.reads.append(('business', bid))
        if v.fail_rows:
            return None
        row = v.rows.get(bid)
        return [dict(row)] if row else []

    def flagged():
        v.reads.append(('flagged', None))
        if v.fail_rows:
            return None
        return [dict(r) for r in v.rows.values() if str(r.get('platform_books')).lower() == 'true']

    def owner_email(owner_id):
        v.reads.append(('auth', str(owner_id)))
        if v.fail_auth:
            raise platform_suite._Unread('auth')
        return v.emails.get(str(owner_id))
    monkeypatch.setattr(platform_suite, '_read_business', read_business)
    monkeypatch.setattr(platform_suite, '_flagged_rows', flagged)
    monkeypatch.setattr(platform_suite, '_owner_email', owner_email)
    yield v
    platform_suite.forget()


# ── the switches and who the platform business is ─────────────────────

def test_with_the_switch_off_no_business_is_the_platform_business(monkeypatch):
    for on, pid in ((False, PID), (False, None), (True, None)):
        switch(monkeypatch, on=on, pid=pid)
        row = platform_row()
        assert platform_suite.is_platform(PID) is False
        assert platform_suite.effective_row(row) is row                 # the same object, untouched
        assert platform_suite.zone_for(PID) is None
        assert (platform_suite.platform_site(PID) is not None) is bool(pid)   # its links resolve by id alone
        assert bm.level_for(row)['level'] == 'suggest'                 # its real (empty) plan
    switch(monkeypatch, on=True, pid='not-a-uuid')
    assert platform_suite.platform_id() is None and platform_suite.is_platform(PID) is False


def test_marketing_desk_is_unchanged_without_the_id_but_for_solutionists_own_business(monkeypatch):
    switch(monkeypatch, on=True, pid=None)
    other = str(uuid4())
    for raw, scope in (('', None), ('off', None), ('*', '*'), (other, frozenset({other}))):
        monkeypatch.setenv('MARKETING_DESK', raw)
        assert plan.desk_scope() == scope
        assert plan.desk_on_for(other) is (scope is not None)
        assert plan.desk_on_for(PID) is False          # found by books_business: it runs on Buffer


def test_the_platform_business_is_in_the_suite_fan_out_only_while_the_switch_is_on(monkeypatch):
    other = str(uuid4())
    switch(monkeypatch, on=True)
    monkeypatch.setenv('MARKETING_DESK', 'off')
    assert plan.desk_scope() == frozenset({PID}) and plan.desk_on_for(PID) and not plan.desk_on_for(other)
    monkeypatch.setenv('MARKETING_DESK', other)
    assert plan.desk_scope() == frozenset({PID, other})
    monkeypatch.setenv('MARKETING_DESK', '*')
    assert plan.desk_scope() == '*' and plan.desk_on_for(PID)
    switch(monkeypatch, on=False)
    for raw in ('*', f'{PID},{other}', PID):
        monkeypatch.setenv('MARKETING_DESK', raw)
        assert plan.desk_on_for(PID) is False                          # the Buffer desk's loop owns its week
    monkeypatch.setenv('MARKETING_DESK', f'{PID},{other}')
    assert plan.desk_scope() == frozenset({other}) and plan.desk_on_for(other)
    monkeypatch.setenv('MARKETING_DESK', PID)
    assert plan.desk_scope() is None


def test_autopilot_for_the_platform_business_only_whatever_its_billing(monkeypatch):
    switch(monkeypatch, on=True)
    level = bm.level_for(platform_row())
    assert level['level'] == 'autopilot' and level['plan'] == 'practice' and level['upgrade'] is None
    tenant = platform_row(id=str(uuid4()))                              # platform_books in ITS settings: no grant
    assert bm.level_for(tenant)['level'] == 'suggest'
    assert platform_suite.effective_row(tenant) is tenant
    assert platform_suite.effective_row(platform_row())['comp_tier'] == 'practice'
    assert bm.business_tz(platform_row(settings={'availability': {'timezone': 'America/Denver'}})).key == \
        'America/New_York'
    assert bm.business_tz(platform_row(id=str(uuid4()), settings={'availability': {'timezone': 'America/Denver'}})
                          ).key == 'America/Denver'
    import policy_engine
    import standing_permissions as sp
    monkeypatch.setattr(policy_engine, 'client_facing_autonomy', lambda biz: 'enabled')
    assert sp.marketing_eligible(platform_row(), 'marketing_post') == (True, '')          # B13's standing OK
    assert sp.marketing_eligible(platform_row(id=str(uuid4())), 'marketing_post')[0] is False
    switch(monkeypatch, on=False)
    assert sp.marketing_eligible(platform_row(), 'marketing_post')[0] is False


# ── Mission Control's routes on the suite ─────────────────────────────

class SuiteStore(api.FakeStore):
    """B4's store, plus marketing_runs written by the owner's request (queue_request)."""

    async def request(self, method, path, body=None):
        if path.split('?', 1)[0] == '/marketing_runs' and method != 'GET':
            self.writes.append((method, path, copy.deepcopy(body)))
            if method == 'POST':
                self.runs.append({**copy.deepcopy(body), 'created_at': api.NOW.isoformat()})
                return [copy.deepcopy(body)]
            raise AssertionError(method)
        return await super().request(method, path, body)


@pytest.fixture
def mc(monkeypatch):
    switch(monkeypatch, on=True)
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', f'{api.BIZ},{PID}')
    monkeypatch.setenv('MARKETING_DESK_PUBLISHING', 'on')
    for name in ('MARKETING_DESK', 'PLATFORM_DEFAULT_TZ', 'BILLING_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    db, svc = SuiteStore(), api.FakeService()
    svc.businesses[PID] = platform_row()
    svc.connections += [api.connection(PFB, 'facebook', biz=PID), api.connection(PIG, 'instagram', biz=PID)]
    monkeypatch.setattr(store, 'request', db.request)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', svc.get)

    def no_writes(*a, **k):
        raise AssertionError('the desk writes only through business_marketing_store')
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', no_writes)
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', no_writes)
    monkeypatch.setattr(bm, 'now', lambda: api.NOW)
    monkeypatch.setattr(plan, '_now', lambda: api.NOW)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda business_id=None: False)
    state = SimpleNamespace(db=db, svc=svc, user=KEVIN, email=PLATFORM_OWNER_EMAIL, buffer=[], buffer_fail=False)

    async def buffer_db(method, path, body=None):             # the Buffer desk's own tables
        if state.buffer_fail:
            raise HTTPException(503, 'Marketing storage is unavailable. Please retry.')
        assert method == 'GET' and path.startswith('/platform_marketing_posts?'), path
        return copy.deepcopy(state.buffer)
    monkeypatch.setattr(m, 'db', buffer_db)
    rate_limit._buckets.clear()
    app = FastAPI()
    app.include_router(suite.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=state.user, email=state.email,
                                                                     role='authenticated')
    state.client = TestClient(app)
    return state


def hit(mc, method, path, body=None):
    return mc.client.request(method, f'/platform/marketing{path}', json=body)


ROUTES = [('GET', '/suite/engine', None), ('GET', '/suite/ideas/next-slot', None),
          ('POST', '/suite/ideas', {'caption': 'One place for your clients, bookings and money.'}),
          ('POST', '/suite/approve', {'items': [{'id': str(uuid4()), 'revision': 1, 'content_hash': 'a' * 64}]}),
          ('POST', '/suite/slot/edit', {'items': [{'id': str(uuid4()), 'revision': 1}], 'caption': 'New words.'}),
          ('POST', '/suite/slot/cancel', {'items': [{'id': str(uuid4()), 'revision': 1}]}),
          ('POST', '/suite/post-now', {'items': [{'id': str(uuid4()), 'revision': 1, 'content_hash': 'a' * 64}]}),
          ('POST', f'/suite/posts/{uuid4()}/not-sent', {'revision': 1}),
          ('POST', f'/suite/posts/{uuid4()}/take-back', {'revision': 1}),
          ('PUT', '/suite/settings', {'paused': True}), ('GET', '/suite/results', None),
          ('POST', '/suite/engine/run', None), ('GET', '/suite/preview', None), ('GET', '/drain', None)]


@pytest.mark.parametrize('method,path,body', ROUTES, ids=[r[1] for r in ROUTES])
def test_every_route_is_the_platform_owners_alone(mc, method, path, body):
    for who, email in ((api.OWNER, 'owner@fadestreet.com'), (KEVIN, 'not-kevin@example.com'), (KEVIN, None)):
        mc.user, mc.email = who, email                              # a tenant owner, or anyone else
        r = hit(mc, method, path, body)
        assert r.status_code == 403, (who, email, r.text)
    assert mc.db.writes == [] and mc.db.paths == [] and mc.svc.reads == []


@pytest.mark.parametrize('method,path,body', [r for r in ROUTES if r[1] != '/drain'],
                         ids=[r[1] for r in ROUTES if r[1] != '/drain'])
def test_the_suite_desk_refuses_plainly_until_it_is_switched_on_and_named(mc, monkeypatch, method, path, body):
    switch(monkeypatch, on=False)
    r = hit(mc, method, path, body)
    assert r.status_code == 409 and r.json()['detail'] == platform_suite.NOT_ON
    switch(monkeypatch, on=True, pid=None)
    r = hit(mc, method, path, body)
    assert r.status_code == 409 and r.json()['detail'] == platform_suite.NO_ID
    assert mc.db.writes == [] and mc.db.paths == []


@pytest.mark.parametrize('case', ['tenant_business', 'not_platform_books', 'not_the_platform_owner', 'missing'])
def test_an_id_that_is_not_solutionists_own_business_opens_nothing(mc, monkeypatch, verdicts, case):
    if case == 'tenant_business':
        switch(monkeypatch, on=True, pid=api.BIZ)                     # someone else's business, someone else's row
    elif case == 'not_platform_books':
        verdicts.rows[PID]['platform_books'] = None
    elif case == 'not_the_platform_owner':
        verdicts.emails[KEVIN] = 'someone@else.example'
    else:
        switch(monkeypatch, on=True, pid=str(uuid4()))
    for method, path, body in ROUTES[:-1]:
        r = hit(mc, method, path, body)
        assert r.status_code == 409 and r.json()['detail'] == platform_suite.WRONG_ID, path
    assert mc.db.writes == [] and mc.db.paths == []
    status = hit(mc, 'GET', '/suite/status').json()
    assert status == {'on': True, 'ready': False, 'business_id': None, 'reason': platform_suite.WRONG_ID}


def test_a_failed_read_of_the_business_is_a_503_not_a_desk(mc, verdicts):
    mc.svc.fail = ('/businesses',)
    r = hit(mc, 'GET', '/suite/engine')
    assert r.status_code == 503 and mc.db.paths == []
    platform_suite.forget()
    verdicts.fail_rows = True                                          # the verdict itself unreadable
    r = hit(mc, 'GET', '/suite/engine')
    assert r.status_code == 503 and r.json()['detail'] == platform_suite.UNCONFIRMED and mc.db.paths == []


def test_status_says_which_desk_mission_control_shows(mc, monkeypatch):
    assert hit(mc, 'GET', '/suite/status').json() == {'on': True, 'ready': True, 'business_id': PID, 'reason': None}
    switch(monkeypatch, on=False)
    assert hit(mc, 'GET', '/suite/status').json() == {'on': False, 'ready': False, 'business_id': None,
                                                       'reason': platform_suite.NOT_ON}


def test_the_desk_reads_the_platform_business_at_autopilot_on_eastern_time(mc):
    mine = api.seed(mc, biz=PID, targets=(PFB,))
    api.seed(mc, targets=(api.FB,))                                   # a tenant's post, never shown
    body = hit(mc, 'GET', '/suite/engine').json()
    assert body['business_id'] == PID and body['level'] == 'autopilot' and body['upgrade'] is None
    assert body['time_zone'] == 'America/New_York' and body['can_edit'] is True and body['role'] == 'owner'
    shown = [p['id'] for wk in ('this_week', 'next_week') for p in body[wk]['posts']]
    assert shown == [mine['id']]
    assert {c['id'] for c in body['connections']} == {PFB, PIG}
    assert set(body) >= {'desk', 'posting', 'this_week', 'next_week', 'latest', 'planning', 'note'}
    tenant = TestClient(_tenant_app(mc)).get(f'/marketing/{api.BIZ}/engine').json()
    assert set(body) == set(tenant)                                    # the business desk's own shape


def _tenant_app(mc):
    app = FastAPI()
    app.include_router(bm.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=api.OWNER, email='o@x.com', role='authenticated')
    app.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=api.OWNER), token='jwt')
    return app


def test_a_new_post_lands_on_the_platform_business_with_its_mysolutionist_link(mc):
    r = hit(mc, 'POST', '/suite/ideas', {'caption': 'One place for your clients, bookings and money.'})
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out) == {'dropped', 'note', 'accounts', 'link', 'post', 'run_at', 'already_saved', 'posting'}
    [row] = mc.db.posts.values()
    assert row['business_id'] == PID and row['source'] == 'owner'
    assert {t['connection_id'] for t in row['targets']} == {PFB}        # Instagram left out: no picture
    assert row['landing_url'] == 'https://mysolutionist.app/'
    code = store.link_code(row['id'])
    assert out['link'] == f'https://mysolutionist.app/go/{code}'
    assert row['publish_text'].endswith(f'https://mysolutionist.app/go/{code}')
    tracked = urlsplit(row['tracked_url'])
    assert tracked.hostname == 'mysolutionist.app' and parse_qs(tracked.query)['utm_content'] == [row['id']]
    local = datetime.fromisoformat(row['run_at']).astimezone(NEW_YORK)
    assert (local.hour, local.minute) == (15, 0)                       # 11:00 ET had passed; 3:00 PM ET
    assert all(f'business_id=eq.{PID}' in p for _, p in mc.db.paths if p.startswith('/marketing_posts?'))
    assert all(b['business_id'] == PID for meth, p, b in mc.db.writes if meth == 'POST')


def test_a_link_to_a_business_site_is_refused_on_the_platform_desk(mc):
    r = hit(mc, 'POST', '/suite/ideas', {'caption': 'Look at this.', 'landing_url': 'https://fadestreet.com/'})
    assert r.status_code == 422 and mc.db.posts == {}
    r = hit(mc, 'POST', '/suite/ideas', {'caption': 'See the features.',
                                         'landing_url': 'https://mysolutionist.app/features'})
    assert r.status_code == 200 and next(iter(mc.db.posts.values()))['landing_url'] == \
        'https://mysolutionist.app/features'


def test_approve_change_skip_post_now_and_not_sent_work_on_the_platform_store(mc):
    a = api.seed(mc, biz=PID, targets=(PFB,))
    r = hit(mc, 'POST', '/suite/approve', {'items': [api.item(a)]})
    assert r.status_code == 200 and r.json() == {'approved': 1} and mc.db.posts[a['id']]['approved_by'] == KEVIN
    b = api.seed(mc, biz=PID, targets=(PFB,))
    r = hit(mc, 'POST', '/suite/slot/edit', {'items': [api.slot(b)], 'caption': 'Your week, in one place.'})
    assert r.status_code == 200 and mc.db.posts[b['id']]['revision'] == 2
    c = api.seed(mc, biz=PID, targets=(PFB,))
    assert hit(mc, 'POST', '/suite/slot/cancel', {'items': [api.slot(c)]}).json()['cancelled'] == 1
    d = api.seed(mc, biz=PID, targets=(PFB,))
    r = hit(mc, 'POST', '/suite/post-now', {'items': [api.item(d)]})
    assert r.status_code == 200 and r.json()['posting'] is True and mc.db.posts[d['id']]['status'] == 'approved'
    u = api.seed(mc, biz=PID, targets=(PFB,), status='uncertain', run_at=api.NOW - timedelta(hours=1))
    r = hit(mc, 'POST', f"/suite/posts/{u['id']}/not-sent", {'revision': u['revision']})
    assert r.status_code == 200 and mc.db.posts[u['id']]['status'] == 'failed'
    t = api.seed(mc, biz=PID, targets=(PFB,))
    assert hit(mc, 'POST', '/suite/approve', {'items': [api.item(t)]}).status_code == 200
    r = hit(mc, 'POST', f"/suite/posts/{t['id']}/take-back", {'revision': mc.db.posts[t['id']]['revision']})
    assert r.status_code == 200 and mc.db.posts[t['id']]['status'] == 'draft'           # B13's take-back
    r = hit(mc, 'PUT', '/suite/settings', {'plan_enabled': True, 'post_hour': 11})
    assert r.status_code == 200 and mc.db.desks[PID]['plan_enabled'] is True
    r = hit(mc, 'GET', '/suite/results')
    assert r.status_code == 200 and r.json()['business_id'] == PID
    assert r.json()['site'] == {'state': 'ready', 'origin': 'https://mysolutionist.app'}
    for method, path, body in mc.db.writes:
        if path.startswith('/rpc/'):
            assert body['p_business_id'] == PID
        else:
            assert f'business_id=eq.{PID}' in path or body.get('business_id') == PID, path


def test_a_tenant_post_cannot_be_reached_through_mission_control(mc):
    theirs = api.seed(mc, targets=(api.FB,))
    before = copy.deepcopy(mc.db.posts)
    for method, path, body in (('POST', '/suite/approve', {'items': [api.item(theirs)]}),
                               ('POST', '/suite/slot/edit', {'items': [api.slot(theirs)], 'caption': 'Taken over.'}),
                               ('POST', '/suite/slot/cancel', {'items': [api.slot(theirs)]}),
                               ('POST', '/suite/post-now', {'items': [api.item(theirs)]}),
                               ('POST', f"/suite/posts/{theirs['id']}/not-sent", {'revision': 1})):
        assert hit(mc, method, path, body).status_code == 409, path
    assert mc.db.posts == before


def test_running_the_week_queues_it_for_the_platform_business(mc):
    r = hit(mc, 'POST', '/suite/engine/run')
    assert r.status_code == 202, r.text
    out = r.json()
    assert out['kind'] == 'week' and out['queued'] is True and out['week_of'] == '2026-10-05'
    [queued] = mc.db.runs
    assert queued['business_id'] == PID and queued['kind'] == 'week' and queued['trigger'] == 'manual'


def test_a_week_the_buffer_desk_has_live_is_not_queued_again(mc):
    mc.buffer = [{'id': str(uuid4())}]
    r = hit(mc, 'POST', '/suite/engine/run')
    assert r.status_code == 409 and r.json()['detail'] == platform_suite.BUFFER_WEEK and mc.db.runs == []
    mc.buffer_fail = True
    r = hit(mc, 'POST', '/suite/engine/run')
    assert r.status_code == 503 and mc.db.runs == []


# ── nothing new goes to Buffer while the suite is on ──────────────────

@pytest.fixture
def old(monkeypatch):
    s = {'config': {'organization_id': 'org-1', 'paused': False,
                    'channels': [{'id': 'channel-1', 'name': 'Solutionist', 'service': 'facebook',
                                  'isDisconnected': False, 'isLocked': False, 'isQueuePaused': False}]},
         'writes': [], 'posts': []}

    async def config():
        return s['config']

    async def db(method, path, body=None):
        if method == 'GET':
            return copy.deepcopy(s['posts'])
        s['writes'].append((method, path, copy.deepcopy(body)))
        return [body]
    monkeypatch.setattr(m, 'config', config)
    monkeypatch.setattr(m, 'db', db)
    monkeypatch.setenv('BUFFER_PUBLISHING', 'on')
    monkeypatch.setenv('BUFFER_API_KEY', 'key')
    app = FastAPI()
    app.include_router(m.router)
    app.include_router(platform.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(id=KEVIN, email=PLATFORM_OWNER_EMAIL)
    s['client'] = TestClient(app)
    return s


def _draft_body(**over):
    return {'campaign': 'service-owners', 'text': 'Bring your business work together.', 'channel_id': 'channel-1',
            'run_at': (m.now() + timedelta(days=1)).isoformat(), **over}


NEW_FOR_BUFFER = [('POST', '/ideas', lambda: {'text': 'Bring your business work together.'}),
                  ('POST', '/ideas', lambda: {'text': 'Out now.', 'post_now': True}),
                  ('POST', '/posts', _draft_body),
                  ('POST', '/approve', lambda: {'items': [{'id': str(uuid4()), 'revision': 1, 'content_hash': 'a' * 64}]}),
                  ('POST', '/post-now', lambda: {'items': [{'id': str(uuid4()), 'revision': 1, 'content_hash': 'a' * 64}]}),
                  ('POST', '/engine/run', lambda: {})]


@pytest.mark.parametrize('method,path,body', NEW_FOR_BUFFER, ids=[f'{r[1]}-{i}' for i, r in enumerate(NEW_FOR_BUFFER)])
def test_the_buffer_desk_takes_nothing_new_with_the_suite_on(old, monkeypatch, method, path, body):
    switch(monkeypatch, on=True)
    r = old['client'].request(method, f'/platform/marketing{path}', json=body())
    assert r.status_code == 409 and r.json()['detail'] == platform_suite.BUFFER_CLOSED
    assert old['writes'] == []


@pytest.mark.parametrize('case', ['unset', 'tenant_id', 'not_platform_books'])
def test_switch_on_without_a_valid_platform_business_keeps_the_buffer_desk_and_says_so(old, monkeypatch, verdicts,
                                                                                      caplog, case):
    switch(monkeypatch, on=True, pid=None if case == 'unset' else api.BIZ if case == 'tenant_id' else PID)
    if case == 'not_platform_books':
        verdicts.rows[PID]['platform_books'] = None
    with caplog.at_level('ERROR'):
        r = old['client'].post('/platform/marketing/ideas', json={'text': 'Bring your business work together.'})
    assert r.status_code == 200 and r.json()['already_saved'] is False              # as before
    assert 'MC_MARKETING_SUITE is on' in caplog.text                                  # loudly
    assert platform_suite.buffer_state() == 'open' and platform_suite.chief_closed() is None
    assert platform_suite.problem() == (platform_suite.NO_ID if case == 'unset' else platform_suite.WRONG_ID)
    calls = _old_job(monkeypatch)

    async def nothing(path):
        return []
    monkeypatch.setattr(store, 'rows', nothing)
    run(platform.engine_tick())
    assert calls == ['scheduled']                                      # the Thursday job still plans


def test_when_the_platform_business_cannot_be_confirmed_neither_desk_takes_anything_new(old, monkeypatch,
                                                                                         verdicts):
    switch(monkeypatch, on=True)
    verdicts.fail_rows = True
    r = old['client'].post('/platform/marketing/ideas', json={'text': 'Bring your business work together.'})
    assert r.status_code == 503 and r.json()['detail'] == platform_suite.UNCONFIRMED and old['writes'] == []
    assert run(pcm.new_post({'text': 'Make a post.'})) == {'ok': False, 'label': platform_suite.UNCONFIRMED}
    assert platform_suite.is_platform(PID) is False
    assert platform_suite.effective_row(platform_row())['comp_tier'] is None             # no autopilot
    monkeypatch.setenv('MARKETING_DESK', '*')
    assert plan.desk_on_for(PID) is False                              # planned by neither loop this hour
    calls = _old_job(monkeypatch)
    run(platform.engine_tick())
    assert calls == []
    platform_suite.forget()
    verdicts.fail_rows, verdicts.fail_auth = False, True               # the owner's address unreadable
    assert platform_suite.state() == (platform_suite.UNKNOWN, PID) and platform_suite.is_platform(PID) is False


def test_with_the_suite_off_the_buffer_desk_is_as_before(old, monkeypatch):
    switch(monkeypatch, on=False)
    r = old['client'].post('/platform/marketing/posts', json=_draft_body())
    assert r.status_code == 200 and old['writes'][0][1] == '/platform_marketing_posts'
    r = old['client'].post('/platform/marketing/ideas', json={'text': 'Bring your business work together.'})
    assert r.status_code == 200 and r.json()['already_saved'] is False


def test_posts_already_on_the_buffer_desk_can_still_be_changed_or_skipped(old, monkeypatch):
    switch(monkeypatch, on=True)
    r = old['client'].post('/platform/marketing/posts', json=_draft_body(id=str(uuid4()), revision=1))
    assert r.status_code == 200 and old['writes'][0][0] == 'PATCH'      # an edit takes it out of the queue
    r = old['client'].put('/platform/marketing/pause', json={'paused': True})
    assert r.status_code == 200


def test_posts_approved_before_the_switch_still_drain(old, monkeypatch, caplog):
    switch(monkeypatch, on=True)
    row = {'id': str(uuid4()), 'status': 'dispatching'}
    claims, sent = [[row], []], []

    async def db(method, path, body=None):
        if path == '/rpc/platform_marketing_claim':
            return claims.pop(0)
        return [body]

    async def dispatch(r, api_):
        sent.append(r['id'])
        return {'status': 'submitted'}
    monkeypatch.setattr(m, 'db', db)
    monkeypatch.setattr(m, 'dispatch', dispatch)
    with caplog.at_level('INFO'):
        run(m.due_tick())
    assert sent == [row['id']] and 'Buffer drain' in caplog.text


def test_platform_chief_makes_nothing_new_for_buffer(monkeypatch):
    switch(monkeypatch, on=True)
    closed = {'ok': False, 'label': platform_suite.BUFFER_CLOSED}

    async def boom(*a, **k):
        raise AssertionError('nothing of the Buffer desk is read or written')
    monkeypatch.setattr(m, 'db', boom)
    monkeypatch.setattr(m, 'config', boom)
    assert run(pcm.new_post({'text': 'Make a post.'})) == closed
    assert run(pcm.save_draft({'draft': _draft_body()})) == closed
    assert run(pcm.post_now({'caption': 'Now.', 'channels': ['Facebook'], 'channel_ids': ['channel-1']})) == closed
    assert run(pcm.run_week({})) == closed and run(pcm.replan_week({})) == closed
    with pytest.raises(HTTPException) as err:
        run(pcm.post_now_review({'type': 'marketing_post_now', 'text': 'Now.'}))
    assert err.value.status_code == 409

    async def pause(req):
        return {'paused': True}
    monkeypatch.setattr(m, 'pause', pause)
    assert run(pcm.pause_marketing({}))['ok'] is True                   # managing the drain still works


def test_a_refused_post_now_card_is_an_ordinary_answer_in_platform_chiefs_reply(monkeypatch, verdicts):
    """Through the real dispatch (platform_chief_actions.dispatch_actions ->
    platform_chief_authority.dispatch -> propose -> post_now_review): a
    refusal while the card is prepared is that action's own answer, never the
    whole reply's failure. (B15b: with the suite active a post-now card is
    made on the suite desk, test_platform_chief_suite; the refusal here is
    the business that couldn't be confirmed, where neither desk takes
    anything new.)"""
    import platform_chief_actions as actions
    import platform_chief_authority as authority
    switch(monkeypatch, on=True)
    verdicts.fail_rows = True

    async def policy(owner_id):
        return {'settings': {'drafts': 'ask', 'creative': 'ask', 'notes': 'ask', 'marketing_stop': 'ask'}}

    async def no_write(*a, **k):
        raise AssertionError('no card is written for a refused action')
    logged = []

    async def log_action(**kw):
        logged.append(kw['result'])
    monkeypatch.setattr(authority, 'policy', policy)
    monkeypatch.setattr(authority, 'db', no_write)
    monkeypatch.setattr(actions, '_log_action', log_action)
    owner = SimpleNamespace(id=KEVIN, email=PLATFORM_OWNER_EMAIL)
    out = run(actions.dispatch_actions([{'type': 'marketing_post_now', 'text': 'Out now.'}],
                                       owner=owner, request_id=uuid4()))
    assert out == [{'ok': False, 'type': 'marketing_post_now', 'label': platform_suite.UNCONFIRMED}]
    assert logged == out


def test_platform_chiefs_snapshot_says_where_marketing_runs_now(monkeypatch):
    async def fail(*a, **k):
        raise HTTPException(503, 'down')
    for name in ('founder_offer', '_link_results', '_this_week', '_desk'):
        monkeypatch.setattr(pcm, name, fail)
    monkeypatch.setattr(m, 'config', fail)
    monkeypatch.setattr(m, 'db', fail)
    monkeypatch.setattr(m, 'assets', fail)
    switch(monkeypatch, on=False)
    assert 'suite' not in run(pcm.marketing_snapshot())
    switch(monkeypatch, on=True)
    assert run(pcm.marketing_snapshot())['suite']['on'] is True
    switch(monkeypatch, on=True, pid=None)
    assert run(pcm.marketing_snapshot())['suite'] == {'on': False, 'note': platform_suite.NO_ID}


# ── the drain report ──────────────────────────────────────────────────

def test_the_drain_counts_what_is_left_for_buffer_and_never_calls_it(mc, monkeypatch):
    now = m.now()

    def post(status, hours, expires=6):
        return {'id': str(uuid4()), 'status': status, 'run_at': (now + timedelta(hours=hours)).isoformat(),
                'expires_at': (now + timedelta(hours=hours + expires)).isoformat()}
    mc.buffer = [post('approved', 5), post('approved', 30), post('approved', -10, expires=2), post('dispatching', 0),
                 post('submitted', -1), post('uncertain', -3), post('draft', 40)]

    async def config():
        return {'paused': False}
    monkeypatch.setattr(m, 'config', config)
    monkeypatch.setenv('BUFFER_PUBLISHING', 'on')
    import buffer_client

    def no_buffer(*a, **k):
        raise AssertionError('the drain never calls Buffer')
    monkeypatch.setattr(buffer_client.BufferClient, '__init__', no_buffer)
    out = hit(mc, 'GET', '/drain').json()
    assert {k: out[k] for k in ('queued', 'sending', 'in_buffer', 'unconfirmed', 'missed', 'drafts')} == \
        {'queued': 2, 'sending': 1, 'in_buffer': 1, 'unconfirmed': 1, 'missed': 1, 'drafts': 1}
    assert out['safe_to_switch_off'] is False and out['buffer_publishing'] is True and out['paused'] is False
    assert out['last_goes_out'] == mc.buffer[1]['run_at'] and 'Keep BUFFER_PUBLISHING on' in out['message']
    mc.buffer = [post('submitted', -1), post('draft', 40), post('approved', -10, expires=2)]
    out = hit(mc, 'GET', '/drain').json()
    assert out['safe_to_switch_off'] is True and out['queued'] == 0 and 'safe to set BUFFER_PUBLISHING=off' in \
        out['message']
    mc.buffer = [post('approved', 5)]
    monkeypatch.setenv('BUFFER_PUBLISHING', 'off')
    out = hit(mc, 'GET', '/drain').json()
    assert out['safe_to_switch_off'] is False and 'will not go out' in out['message']
    monkeypatch.setenv('BUFFER_PUBLISHING', 'on')
    mc.buffer = [post('submitted', -1)]
    switch(monkeypatch, on=True, pid=None)                             # the switch is on, the suite is not
    out = hit(mc, 'GET', '/drain').json()
    assert out['suite_on'] is True and out['suite_active'] is False and out['suite_problem'] == platform_suite.NO_ID
    assert out['safe_to_switch_off'] is False and out['message'].startswith(platform_suite.NO_ID)
    assert hit(mc, 'GET', '/suite/status').json()['reason'] == platform_suite.NO_ID
    switch(monkeypatch, on=True)
    mc.buffer_fail = True
    assert hit(mc, 'GET', '/drain').status_code == 503                 # never "0 left" on a failed read
    assert mc.db.writes == []


# ── one loop a week ───────────────────────────────────────────────────

THU_9_ET = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)


def _old_job(monkeypatch):
    calls = []

    async def fake(trigger, now=None):
        calls.append(trigger)
    monkeypatch.setattr(platform, 'run_week', fake)
    monkeypatch.setattr(m, 'now', lambda: THU_9_ET)
    monkeypatch.delenv('MARKETING_ENGINE', raising=False)
    return calls


def test_the_old_thursday_job_does_nothing_while_the_suite_is_on(monkeypatch):
    calls = _old_job(monkeypatch)

    async def no_read(path):
        raise AssertionError('nothing is read')
    monkeypatch.setattr(store, 'rows', no_read)
    switch(monkeypatch, on=True)
    run(platform.engine_tick())
    assert calls == []
    switch(monkeypatch, on=False, pid=None)
    run(platform.engine_tick())
    assert calls == ['scheduled']                                       # off, no id: exactly as before, no read


def test_off_the_suite_the_old_job_leaves_a_week_the_suite_has_live(monkeypatch):
    calls = _old_job(monkeypatch)
    switch(monkeypatch, on=False)
    answer, paths = [[]], []

    async def rows(path):
        paths.append(path)
        if answer[0] is None:
            raise store.StoreUnavailable('down')
        return answer[0]
    monkeypatch.setattr(store, 'rows', rows)
    run(platform.engine_tick())
    assert calls == ['scheduled']
    week = platform.week_window(THU_9_ET)[0]
    assert f'business_id=eq.{PID}' in paths[0] and f'run_id=eq.{store.run_id_for(PID, week)}' in paths[0]
    answer[0] = [{'id': str(uuid4())}]
    run(platform.engine_tick())
    answer[0] = None
    run(platform.engine_tick())
    assert calls == ['scheduled']


def _platform_in_w(w, monkeypatch, *, buffer=()):
    w.svc.businesses[PID] = {**biz_row(PID, KEVIN, name='The Solutionist System', tier=None, tz=None,
                                       platform_books=True), 'type': 'saas'}
    w.svc.connections += [conn_row(PFB, 'facebook', biz=PID), conn_row(PIG, 'instagram', biz=PID)]
    w.db.desks[PID] = {'business_id': PID, 'plan_enabled': True, 'paused': False, 'connection_ids': [],
                       'post_hour': 11}
    w.buffer, w.buffer_paths = list(buffer), []

    async def buffer_db(method, path, body=None):
        w.buffer_paths.append(path)
        if w.buffer is None:
            raise HTTPException(503, 'down')
        return copy.deepcopy(w.buffer)
    monkeypatch.setattr(m, 'db', buffer_db)


def test_the_suite_never_plans_a_week_the_buffer_desk_has_live(w, monkeypatch):
    switch(monkeypatch, on=True)
    _platform_in_w(w, monkeypatch, buffer=[{'id': str(uuid4())}])
    out = run(plan.run_week(PID, trigger='scheduled'))
    assert out['status'] == 'buffer_week' and out['reason'] == platform_suite.BUFFER_WEEK
    assert not any(r['business_id'] == PID for r in w.db.runs.values())          # nothing claimed
    week = date(2026, 10, 12)
    assert f'run_id=eq.{platform.run_id_for(week)}' in w.buffer_paths[0]
    w.buffer = None
    out = run(plan.run_week(PID, trigger='scheduled'))
    assert out['status'] == 'unavailable' and not any(r['business_id'] == PID for r in w.db.runs.values())
    w.buffer = []
    out = run(plan.run_week(PID, trigger='scheduled'))
    assert out['status'] == 'succeeded' and out['week_of'] == week.isoformat()


def test_exactly_one_loop_plans_the_platform_week(w, monkeypatch):
    _platform_in_w(w, monkeypatch)
    w.svc.businesses[PID]['comp_tier'] = 'practice'        # even on a plan with the week, off the suite it waits
    # Off the suite (MARKETING_DESK '*' names everyone): the suite's fan-out leaves it to the Buffer desk.
    switch(monkeypatch, on=False)
    run(plan.marketing_tick())
    assert not any(r['business_id'] == PID for r in w.db.runs.values())
    assert any(r['business_id'] != PID for r in w.db.runs.values())
    # On the suite with MARKETING_DESK off: the suite plans the platform business, and only it.
    switch(monkeypatch, on=True)
    monkeypatch.setenv('MARKETING_DESK', 'off')
    w.db.runs.clear()
    w.db.posts.clear()
    tally = run(plan.marketing_tick())
    assert tally['candidates'] == 1 and tally['week_succeeded'] == 1, tally
    assert {r['business_id'] for r in w.db.runs.values()} == {PID}
    old_job = _old_job(monkeypatch)
    run(platform.engine_tick())
    assert old_job == []


# ── who is the platform business ──────────────────────────────────────

def test_a_tenant_id_in_the_env_by_mistake_gets_nothing_special(monkeypatch):
    switch(monkeypatch, on=True, pid=api.BIZ)
    tenant = platform_row(id=api.BIZ, owner_id=api.OWNER, settings={})
    assert platform_suite.state() == (platform_suite.INVALID, api.BIZ)
    assert platform_suite.is_platform(api.BIZ) is False and platform_suite.effective_row(tenant) is tenant
    assert bm.level_for(tenant)['level'] == 'suggest' and platform_suite.zone_for(api.BIZ) is None
    assert platform_suite.desk_switch(api.BIZ) is None and platform_suite.platform_site(api.BIZ) is None
    monkeypatch.setenv('MARKETING_DESK', api.BIZ)
    assert plan.desk_scope() == frozenset({api.BIZ}) and plan.desk_on_for(api.BIZ) is True     # as any business
    switch(monkeypatch, on=False, pid=api.BIZ)
    assert plan.desk_on_for(api.BIZ) is True                           # never excluded from its own desk either


def test_the_verdict_needs_the_flag_and_the_platform_owner_and_is_remembered(monkeypatch, verdicts):
    switch(monkeypatch, on=True)
    assert platform_suite.state() == (platform_suite.VALID, PID)
    assert verdicts.reads == [('business', PID), ('auth', KEVIN)]
    for _ in range(5):
        platform_suite.is_platform(PID)
        platform_suite.effective_row(platform_row())
    assert len(verdicts.reads) == 2                                    # remembered, not read per call
    platform_suite.is_platform(str(uuid4()))
    assert len(verdicts.reads) == 2                                    # another business: no read at all
    platform_suite.forget()
    verdicts.rows[PID]['platform_books'] = 'false'
    assert platform_suite.state()[0] == platform_suite.INVALID
    platform_suite.forget()
    verdicts.rows[PID]['platform_books'] = 'true'
    verdicts.emails[KEVIN] = 'kevin@elsewhere.example'
    assert platform_suite.state()[0] == platform_suite.INVALID
    platform_suite.forget()
    verdicts.emails[KEVIN] = PLATFORM_OWNER_EMAIL
    verdicts.fail_rows = True
    assert platform_suite.state()[0] == platform_suite.UNKNOWN
    assert platform_suite._cache[f'id:{PID}'][0] - platform_suite.time.monotonic() <= platform_suite.TTL_FAILED


def test_a_tenant_flagging_its_own_row_is_never_the_platforms_books(monkeypatch, verdicts):
    import marketing_design
    import public_site
    switch(monkeypatch, on=False, pid=None)
    flagger = str(uuid4())
    verdicts.rows = {flagger: {'id': flagger, 'owner_id': api.OWNER, 'platform_books': 'true'}}
    assert platform_suite.books_business() == (platform_suite.INVALID, None)
    read = []

    async def service(client, path):
        read.append(path)
        return [{'news': [{'title': 'Their post', 'body': 'Words.', 'published_at': '2026-08-30T00:00:00Z'}]}]

    async def buffer_db(method, path, body=None):
        read.append(path)
        return [{'news': []}]
    monkeypatch.setattr(public_site, '_sb_service', service)
    monkeypatch.setattr(m, 'db', buffer_db)
    assert run(public_site._platform_news_posts()) == [] and read == []          # the news page
    with pytest.raises(HTTPException) as err:
        run(marketing_design.platform_owner())                                   # the Buffer desk's flyers
    assert err.value.status_code == 409
    assert run(platform._news()) == [] and read == []                            # the Buffer desk's numbers
    platform_suite.forget()
    verdicts.rows[PID] = {'id': PID, 'owner_id': KEVIN, 'platform_books': 'true'}
    assert platform_suite.books_business() == (platform_suite.VALID, {'id': PID, 'owner_id': KEVIN})
    assert [p['title'] for p in run(public_site._platform_news_posts())] == ['Their post']
    assert read[-1].startswith(f'/businesses?id=eq.{PID}&settings->>platform_books=eq.true')
    assert run(marketing_design.platform_owner()) == {'business_id': PID, 'user_id': KEVIN}
    platform_suite.forget()
    verdicts.fail_rows = True
    assert run(public_site._platform_news_posts()) == []
    with pytest.raises(HTTPException) as err:
        run(marketing_design.platform_owner())
    assert err.value.status_code == 503
    with pytest.raises(HTTPException):
        run(platform._news())                                                    # unread, never "no news"


# ── Solutionist's own profile, numbers, plays and rules ───────────────

def test_the_platform_profile_is_for_the_platform_business_only(monkeypatch):
    switch(monkeypatch, on=True)

    async def get_desk(bid):
        return {'audience': None, 'landing_url': 'https://fadestreet.com/'}
    monkeypatch.setattr(store, 'get_desk', get_desk)
    monkeypatch.setattr(prof, 'read_profile', REAL_READ_PROFILE)
    p = run(prof.read_profile(PID, business=platform_row()))
    assert p['platform'] is True and p['system_prompt'] == platform.SYSTEM and p['audience'] == platform.AUDIENCE
    assert p['timezone'] == 'America/New_York' and p['max_hashtags'] == 0 and p['brand_name'] == 'The Solutionist System'
    assert p['own_hosts'] == ['mysolutionist.app', 'www.mysolutionist.app']
    assert p['landing_url'] == 'https://mysolutionist.app/'               # a link off its site is not its link
    assert p['flyer_footer'] == {'label': 'THE SOLUTIONIST SYSTEM', 'host': 'mysolutionist.app'}
    assert set(plan.PROFILE_PUBLIC) <= set(p)
    other = str(uuid4())
    seen = []

    def build(row, **kw):
        seen.append(row['id'])
        return {'business_id': row['id']}
    monkeypatch.setattr(prof, 'build_profile', build)
    monkeypatch.setattr(bm, '_own_hosts', lambda bid: set())
    monkeypatch.setattr(bm, 'has_chair_calendar', lambda row: False)
    monkeypatch.setattr(bm, 'business_tz', lambda row: ZoneInfo('America/Chicago'))
    monkeypatch.setattr(prof, 'booking_open', lambda row: False)
    assert 'platform' not in run(prof.read_profile(other, business=platform_row(id=other)))
    switch(monkeypatch, on=False)
    assert 'platform' not in run(prof.read_profile(PID, business=platform_row()))
    assert seen == [other, PID]


def _base_platform_signals(now):
    news = [{'id': 'n1', 'slug': 'booking-links', 'title': 'Booking links', 'body': 'Share one link.',
             'published_at': now - timedelta(days=3)},
            {'id': 'n2', 'slug': 'invoices', 'title': 'Invoices', 'body': 'Get paid.',
             'published_at': now - timedelta(days=5)}]
    return {'read_at': now.isoformat(),
            'traffic': {'visits': 40, 'signups': 2, 'leads': 1, 'weekly_visits_before': 38.0,
                        'weekly_signups_before': 1.0},
            'posts': {'last_published': (now - timedelta(days=9)).isoformat(), 'published_last_7_days': 0,
                      'approved_next_7_days': 0},
            'news': news, 'unmarketed_news': news, 'founder': None, 'founder_available': False,
            'used_subjects': [], 'play_scores': {'workflow_tip': {'samples': 2, 'average': 4.0}}}


def test_platform_signals_count_both_desks(monkeypatch):
    switch(monkeypatch, on=True)
    now = THU_9_ET

    async def base(at=None):
        return _base_platform_signals(now)

    async def suite_posts(bid, at):
        assert bid == PID
        return {'last_published': (now - timedelta(days=2)).isoformat(), 'published_last_7_days': 1,
                'published_last_14_days': 1, 'approved_next_7_days': 2, 'looked_back_days': 90}

    async def suite_used(bid, at):
        return ['news:n1']                                             # told on the suite already
    monkeypatch.setattr(platform, 'read_signals', base)
    monkeypatch.setattr(msig, '_posts', suite_posts)
    monkeypatch.setattr(msig, '_used', suite_used)
    s = run(REAL_READ_SIGNALS(PID, now=now))
    assert s['profile'] == 'platform' and s['time_zone'] == 'America/New_York'
    assert s['posts'] == {'last_published': (now - timedelta(days=2)).isoformat(), 'published_last_7_days': 1,
                          'approved_next_7_days': 2}
    assert [n['id'] for n in s['unmarketed_news']] == ['n2'] and s['used_subjects'] == ['news:n1']
    assert s['buffer_play_scores'] == {'workflow_tip': {'samples': 2, 'average': 4.0}} and s['play_scores'] == {}
    assert msig.summary(s)['profile'] == 'platform' and msig.summary(s)['unmarketed_news'] == ['Invoices']

    async def down(bid, at):
        raise store.StoreUnavailable('down')
    monkeypatch.setattr(msig, '_posts', down)
    s = run(REAL_READ_SIGNALS(PID, now=now))
    assert s['posts'] is None and 'suite_posts' in s['unread']         # unknown, never a quiet week
    assert eng.diagnose(s)['rule'] != 'gone_quiet'
    other = str(uuid4())
    switch(monkeypatch, on=False)

    async def never(at=None):
        raise AssertionError('the platform numbers are never read for a business')
    monkeypatch.setattr(platform, 'read_signals', never)

    async def unread_async(*a, **k):
        raise store.StoreUnavailable('down')

    def unread(*a, **k):
        raise store.StoreUnavailable('down')
    for name in ('_traffic', '_posts', '_used'):
        monkeypatch.setattr(msig, name, unread_async)
    for name in ('_bookings', '_capacity', '_new_offerings'):
        monkeypatch.setattr(msig, name, unread)
    for bid in (PID, other):
        assert run(REAL_READ_SIGNALS(bid, now=now, business={'id': bid, 'settings': {}},
                                     tz=NEW_YORK)).get('profile') is None


FACTS = {'product': {'trial_days': 14, 'standard_monthly_prices_usd': {'starter': 79.0, 'professional': 149.0}},
         'public_claims': {'features': [], 'faq': [{'question': 'Do I need a website?', 'answer': 'No.'}]},
         'news': [], 'founder': {'plan': 'professional', 'monthly_price_usd': 99.0, 'seat_limit': 50}}
PROFILE = {'platform': True, 'own_hosts': ['mysolutionist.app', 'www.mysolutionist.app']}


def test_the_platform_week_uses_the_platform_library_and_rules():
    signals = {**_base_platform_signals(THU_9_ET), 'profile': 'platform', 'founder_available': True,
               'play_scores': {'workflow_tip': {'samples': 2, 'average': 10.0}},
               'buffer_play_scores': {'workflow_tip': {'samples': 2, 'average': 2.0}}}
    d = eng.diagnose(signals)
    assert d['primary_problem'] in platform.PROBLEMS and d['rule'] == 'unmarketed_news' and 'numbers' in d
    picked = eng.pick_plays(d, 5, signals, PROFILE, FACTS)
    assert len(picked['slots']) == 5 and {s['play_id'] for s in picked['slots']} <= set(platform.PLAYS)
    assert all(urlsplit(s['landing_url']).hostname == 'mysolutionist.app' for s in picked['slots'])
    assert all(s['offering'] == (eng.FOUNDING if s['play_id'] == 'founder_invitation' else None)
               for s in picked['slots'])
    assert eng.merge_scores(signals['play_scores'], signals['buffer_play_scores']) == \
        {'workflow_tip': {'samples': 4, 'average': 6.0}}
    for play in platform.PLAYS:
        assert eng.PLAYS[play]['label'] == platform.PLAYS[play]['label'] and play not in eng.PLAYS
    assert list(eng.PLAYS) == ['offer_spotlight', 'book_a_time', 'whats_new', 'useful_tip', 'meet_us', 'come_back']
    ok = 'Send one link and let people pick their own time. Your booking page does the back and forth for you.'
    assert eng.check_caption(ok, FACTS, PROFILE) is None
    assert eng.check_caption(ok + ' #smallbusiness', FACTS, PROFILE) == 'hashtag'
    assert eng.check_caption(ok + ' mysolutionist.app', FACTS, PROFILE) == 'link in the caption'
    founder = 'Take a founding seat at $149 a month and keep that rate while you hold it. Set up takes an afternoon.'
    assert eng.check_caption(founder, FACTS, PROFILE, eng.FOUNDING) == 'a price that is not the founding price'
    assert eng.check_caption(founder.replace('$149', '$99'), FACTS, PROFILE, eng.FOUNDING) is None
    assert eng.check_caption(founder, FACTS, PROFILE, None) is None    # a real price, outside a founder post
    flyer = {'headline': 'One link to book', 'line': 'People pick their own time.', 'cta': 'See how'}
    assert eng.check_flyer(flyer, FACTS, PROFILE) is None
    assert eng.check_flyer({**flyer, 'cta': '#booknow'}, FACTS, PROFILE) == 'hashtag on the flyer'
    business = {'own_hosts': ['fade-street.mysolutionist.app']}         # a business keeps its three hashtags
    assert eng.check_caption(ok + ' #barber #fade', {}, business) is None


def test_a_platform_week_is_written_in_solutionists_voice_on_its_own_site(w, monkeypatch):
    switch(monkeypatch, on=True)
    _platform_in_w(w, monkeypatch)
    monkeypatch.setattr(prof, 'read_profile', REAL_READ_PROFILE)

    async def platform_signals(bid, *, now=None, business=None, tz=None):
        assert bid == PID
        return {**_base_platform_signals(w.now), 'profile': 'platform', 'business_id': PID,
                'time_zone': 'America/New_York', 'buffer_play_scores': {}, 'play_scores': {}, 'unread': []}
    monkeypatch.setattr(msig, 'read_signals', platform_signals)
    monkeypatch.setattr(eng, 'platform_facts', lambda signals: copy.deepcopy(FACTS))

    async def no_clips(*a, **k):
        return [], {'state': 'none', 'picked': [], 'skipped': []}
    monkeypatch.setattr(clips, 'plan_clips', no_clips)
    texts = ['Send one link and let people pick their own time. Your booking page does the back and forth.',
             'We built booking links because every owner we met was stuck in a text thread about times.',
             'Do you need a website to start? No. You can begin with your booking link and add the rest later.',
             'One habit for a calmer week: send every invoice the day the work is done. #getpaid',
             'Keep clients, bookings and money in one place, so Monday starts with a clear list.']
    w.reply = {'captions': [{'slot': i + 1, 'text': t,
                             'flyer': {'headline': 'One link to book', 'line': 'People pick their own time.',
                                       'cta': 'See how'}} for i, t in enumerate(texts)]}
    out = run(plan.run_week(PID, trigger='scheduled'))
    assert out['status'] == 'succeeded', out
    payload, kw = w.calls[-1]
    assert payload['system'] == platform.SYSTEM and kw['business_id'] == PID and kw['units'] == 0
    request = json.loads(payload['messages'][0]['content'])
    assert request['audience'] == platform.AUDIENCE and request['facts'] == FACTS
    posts = sorted((p for p in w.db.posts.values() if p['business_id'] == PID), key=lambda p: p['run_at'])
    assert len(posts) == 4                                             # the hashtag caption cost only its slot
    assert {p['play_id'] for p in posts} <= set(platform.PLAYS) and {p['source'] for p in posts} == {'plan'}
    for p in posts:
        assert '#' not in p['caption']
        local = datetime.fromisoformat(p['run_at']).astimezone(NEW_YORK)
        assert local.hour == 11 and local.date() >= date(2026, 10, 12)
        assert f"https://mysolutionist.app/go/{p['link_code']}" in p['publish_text']
        assert urlsplit(p['tracked_url']).hostname == 'mysolutionist.app'
    r = next(r for r in w.db.runs.values() if r['business_id'] == PID)
    assert r['kind'] == 'week' and r['diagnosis']['rule'] == 'unmarketed_news'
    assert r['signals']['profile'] == 'platform'
    assert all(x['actor'] == {'business_id': PID, 'user_id': KEVIN} for x in w.creates)
    assert any('flyer for a' in p['owner_request'] for p in w.prepared)


def test_the_platform_results_read_the_platforms_own_pages(monkeypatch):
    switch(monkeypatch, on=True)
    paths = []

    async def read(path):
        paths.append(path)
        return []
    monkeypatch.setattr(outcomes, '_service', read)
    monkeypatch.setattr(outcomes, '_store', read)
    pid_post = str(uuid4())
    run(outcomes._measure_posts(PID, [pid_post], THU_9_ET - timedelta(days=30)))
    assert any(p.startswith('/site_events?business_id=is.null&') for p in paths)
    assert any(p.startswith('/marketing_leads?attribution') for p in paths)
    paths.clear()
    run(outcomes._measure_posts(api.BIZ, [pid_post], THU_9_ET - timedelta(days=30)))
    assert any(p.startswith(f'/site_events?business_id=eq.{api.BIZ}&') for p in paths)
    assert any(p.startswith(f'/contacts?business_id=eq.{api.BIZ}&') for p in paths)


# ── mysolutionist.app/go/<code> ───────────────────────────────────────

PERSON = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


@pytest.fixture
def apex(monkeypatch):
    import public_site
    state = SimpleNamespace(found=None, follows=[], platform=[])

    async def platform_follow(code, *, count_click):
        state.platform.append((code, count_click))
        return None                                                    # not a Buffer desk code

    async def follow(code, *, count_click):
        state.follows.append((code, count_click))
        return copy.deepcopy(state.found)
    monkeypatch.setattr(m, 'follow', platform_follow)
    monkeypatch.setattr(store, 'follow', follow)
    monkeypatch.setattr(public_site, '_rate_buckets', {})
    app = FastAPI()
    app.include_router(public_site.router)

    def go(code, agent=PERSON, host='mysolutionist.app'):
        client = TestClient(app, base_url=f'https://{host}')
        return client.get(f'/go/{code}', headers={'user-agent': agent}, follow_redirects=False)
    state.go = go
    return state


def test_the_apex_follows_a_suite_post_of_the_platform_business(apex, monkeypatch):
    switch(monkeypatch, on=True)
    target = 'https://mysolutionist.app/features?utm_source=social&utm_content=x'
    apex.found = {'business_id': PID, 'tracked_url': target}
    r = apex.go('abcdefgh')
    assert r.status_code == 302 and r.headers['location'] == target
    assert apex.platform == [('abcdefgh', True)] and apex.follows == [('abcdefgh', False), ('abcdefgh', True)]
    apex.follows.clear()
    r = apex.go('abcdefgh', agent='facebookexternalhit/1.1')
    assert r.headers['location'] == target and apex.follows == [('abcdefgh', False)]          # not counted
    switch(monkeypatch, on=False)                                       # a link already out outlives the switch
    assert apex.go('abcdefgh').headers['location'] == target


def test_the_apex_never_follows_another_business_post_or_an_off_site_link(apex, monkeypatch):
    switch(monkeypatch, on=True)
    for found in ({'business_id': api.BIZ, 'tracked_url': 'https://fadestreet.com/?utm_content=x'},
                  {'business_id': PID, 'tracked_url': 'https://evil.example/'},
                  {'business_id': PID, 'tracked_url': 'http://mysolutionist.app/'}, None):
        apex.found, apex.follows[:] = found, []
        r = apex.go('abcdefgh')
        assert r.status_code == 302 and r.headers['location'] == 'https://mysolutionist.app/'
        assert apex.follows in ([('abcdefgh', False)], [])               # never counted
    for pid in (None, api.BIZ):                                          # no id, or a tenant's: nothing is read
        switch(monkeypatch, on=True, pid=pid)
        apex.follows.clear()
        assert apex.go('abcdefgh').headers['location'] == 'https://mysolutionist.app/'
        assert apex.follows == []


# ── the docs, the switches and the work log ───────────────────────────

def test_the_docs_env_and_worklog_say_what_was_built():
    doc = (ROOT / 'docs' / 'MARKETING_DESK.md').read_text(encoding='utf-8')
    section = doc.split("## Solutionist's own desk on the suite (B15)", 1)
    assert len(section) == 2 and 'MC_MARKETING_SUITE' in section[1] and 'PLATFORM_BUSINESS_ID' in section[1]
    assert '/platform/marketing/drain' in section[1]
    env = (ROOT / '.env.example').read_text(encoding='utf-8')
    assert re.search(r'^MC_MARKETING_SUITE=off$', env, re.M) and re.search(r'^PLATFORM_BUSINESS_ID=$', env, re.M)
    import worklog
    text = (ROOT / 'worklog' / '2026-10-08-marketing-platform-suite.md').read_text(encoding='utf-8')
    entry = worklog.parse_entry(text, 'kmj-intake-server', 'worklog/2026-10-08-marketing-platform-suite.md')
    assert entry and entry['agent'] == 'Claude Code (Claude Opus 5.5)'
    assert entry['asked'] == "This will work. let's build this."
    assert re.search(r'^migrations: \[\]$', text.split('---')[1], re.M)


def test_the_suite_router_is_mounted_before_the_catch_all():
    source = (ROOT / 'kmj_intake_automation.py').read_text(encoding='utf-8')
    mounted = source.index('app.include_router(platform_marketing_suite_router)')
    assert source.index('app.include_router(marketing_engine_router)') < mounted
    assert mounted < source.index('app.include_router(public_site_router)')
