"""The weekly suggestion and the hourly fan-out (business_marketing_planner.py, B8).

When a suggestion is due on each business's own clock (time zones, daylight
saving, the jitter, the Monday-to-Wednesday catch-up, never overnight), who
is a candidate, the per-tick cap and the spend headroom, one claim per
business per week, the caption checks (up to three hashtags for a business,
numbers and prices only from the facts, links only to its own site), the free
flyer in the business's own colours and name, one push and one Today item,
the owner's queued request and the read-only preview.

No network: PostgREST (the marketing_* tables, the claim RPC and the
service-role reads) is an in-memory fake; the model, the flyer renderer, the
push sender and the spend guard are faked at the seams the planner calls.
Nothing is ever approved or sent.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import business_marketing as bm
import business_marketing_engine as eng
import business_marketing_planner as plan
import business_marketing_store as store
import chief_flyer_composer as composer
import creative_director
import image_studio as images
import llm_call
import marketing_design as design
import marketing_engine as platform
import marketing_profile as prof
import marketing_signals as msig
import push_notifications
import rate_limit
import sb_clients
import social_publish_router as social
import spend_guard
from auth_supabase import require_user

run = asyncio.run

BIZ = '0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d'
PRO = '9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b'
OWNER = '11111111-1111-4111-8111-111111111111'
PRO_OWNER = '44444444-4444-4444-8444-444444444444'
MEMBER = '22222222-2222-4222-8222-222222222222'
FB = 'c0000000-0000-4000-8000-000000000002'
IG = 'c0000000-0000-4000-8000-000000000001'
ART = 'a0000000-0000-4000-8000-000000000001'
CHICAGO = ZoneInfo('America/Chicago')
THU = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)          # Thursday 10:00 in Chicago
NEXT_MONDAY = date(2026, 10, 12)
THIS_MONDAY = date(2026, 10, 5)

FACTS = {'name': "Kev's Coaching", 'type': 'coach', 'city': 'Cleveland',
         'offerings': [{'name': 'Strategy session', 'price': '$150', 'minutes': 60}]}
GOOD = {'captions': [{'slot': 1,
                      'text': 'A clear plan beats a busy week. Book a strategy session and leave knowing your next '
                              'step. #coaching #smallbusiness',
                      'flyer': {'headline': 'Plan the week ahead', 'line': 'One session, a clear plan, your next step.',
                                'cta': 'Book a time'}}]}


# ── a small PostgREST ─────────────────────────────────────────────────

TIMES = {'run_at', 'expires_at', 'created_at', 'claimed_at', 'updated_at'}


def _when(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(unquote(str(value)).replace('Z', '+00:00'))


def _norm(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else str(value)


def _value(row, column):
    if '->>' in column:
        col, key = column.split('->>', 1)
        obj = row.get(col)
        return obj.get(key) if isinstance(obj, dict) else None
    return row.get(column)


def matches(row, column, expr):
    value = _value(row, column)
    if expr == 'is.null':
        return value is None
    if expr == 'not.is.null':
        return value is not None
    op, _, arg = expr.partition('.')
    if op == 'not' and arg.startswith('in.('):
        return _norm(value) not in arg[4:-1].split(',')
    if op == 'in':
        return _norm(value) in arg[1:-1].split(',')
    if op in ('gte', 'gt', 'lte', 'lt'):
        if value is None:
            return False
        a, b = (_when(value), _when(arg)) if column in TIMES else (float(value), float(arg))
        return {'gte': a >= b, 'gt': a > b, 'lte': a <= b, 'lt': a < b}[op]
    if op == 'eq':
        return _norm(value) == arg
    if op == 'neq':
        return _norm(value) != arg
    raise AssertionError(f'unexpected filter {column}={expr}')


def select(rows, path):
    query = path.split('?', 1)[1] if '?' in path else ''
    out, order, limit, offset = list(rows), None, None, 0
    for part in query.split('&'):
        if '=' not in part:
            continue
        key, expr = part.split('=', 1)
        if key == 'select':
            continue
        if key == 'order':
            order = expr
        elif key == 'limit':
            limit = int(expr)
        elif key == 'offset':
            offset = int(expr)
        else:
            out = [r for r in out if matches(r, key, expr)]
    if order:
        column, _, direction = order.split(',')[0].partition('.')
        out.sort(key=lambda r: str(r.get(column) or ''), reverse=direction.startswith('desc'))
    out = out[offset:]
    return out[:limit] if limit else out


class FakeStore:
    """marketing_desks, marketing_runs, marketing_posts and the claim RPC."""

    def __init__(self, clock):
        self.clock = clock
        self.desks, self.runs, self.posts = {}, {}, {}
        self.writes, self.fail = [], ()

    async def request(self, method, path, body=None):
        query = path.split('?', 1)[1] if '?' in path else ''
        assert '+' not in query, f'unencoded + in a PostgREST query: {path}'
        if any(f in path for f in self.fail):
            raise store.StoreUnavailable('Marketing storage is unavailable. Please retry.')
        table = path.split('?', 1)[0]
        if method != 'GET':
            self.writes.append((method, path, copy.deepcopy(body)))
        if table == '/rpc/marketing_claim_run':
            return self.claim(body)
        if table == '/rpc/marketing_approve':
            raise AssertionError('a suggestion is never approved by the planner')
        if table == '/marketing_desks':
            return self.table(self.desks, 'business_id', method, path, body)
        if table == '/marketing_runs':
            return self.table(self.runs, 'id', method, path, body)
        if table == '/marketing_posts':
            return self.table(self.posts, 'id', method, path, body)
        raise AssertionError(f'unexpected store call {method} {path}')

    def table(self, rows, key, method, path, body):
        if method == 'GET':
            return copy.deepcopy(select(rows.values(), path))
        if method == 'POST':
            if str(body[key]) in rows:
                raise store.StoreConflict('The post changed. Refresh and review again.')
            row = {**({'plan_enabled': False, 'paused': False, 'connection_ids': [], 'post_hour': 11}
                      if key == 'business_id' else {'approved_hash': None, 'approved_by': None}),
                   **copy.deepcopy(body), 'created_at': self.clock().isoformat()}
            if key == 'id' and 'content_hash' in row:
                assert row['status'] in store.POST_STATUSES and row['source'] in store.POST_SOURCES
                assert _when(row['expires_at']) > _when(row['run_at'])
            rows[str(body[key])] = row
            return [copy.deepcopy(row)]
        if method == 'PATCH':
            hit = select(rows.values(), path)
            for row in hit:
                row.update(copy.deepcopy(body))
            return copy.deepcopy(hit)
        raise AssertionError(method)

    def claim(self, body):
        """marketing_claim_run, as the migration writes it."""
        bid, week, rid, source = body['p_business_id'], body['p_week'], body['p_run_id'], body['p_source']
        now = self.clock()
        r = next((r for r in self.runs.values() if r['business_id'] == bid and r['week_of'] == week), None)
        if r is None:
            self.runs[rid] = {'id': rid, 'business_id': bid, 'week_of': week, 'kind': body['p_kind'],
                              'trigger': source, 'status': 'running', 'attempts': 1, 'created_at': now.isoformat(),
                              'design': None, 'post_ids': [], 'error': None, 'finished_at': None}
            return True
        if r['id'] != rid:
            return False
        if (body['p_replan'] and source == 'manual' and r['status'] == 'succeeded'
                and not any(p.get('run_id') == r['id'] and p['status'] not in ('draft', 'cancelled')
                            for p in self.posts.values())):
            for p in self.posts.values():
                if p.get('run_id') == r['id'] and p['status'] == 'draft':
                    p.update(status='cancelled', revision=p['revision'] + 1)
        elif not ((r['status'] in ('failed', 'skipped') and (source == 'manual' or r['attempts'] < 3))
                  or (r['status'] == 'running' and _when(r['created_at']) < now - timedelta(minutes=15))):
            return False
        r.update(status='running', trigger=source, kind=body['p_kind'], attempts=r['attempts'] + 1, error=None,
                 created_at=now.isoformat(), finished_at=None)
        return True


def business(bid, owner, *, name="Kev's Coaching", tier='starter', tz='America/Chicago', **settings):
    return {'id': bid, 'owner_id': owner, 'name': name, 'type': 'coach', 'comp_tier': tier,
            'subscription_status': None, 'subscription_plan': None, 'trial_ends_at': None,
            'stripe_subscription_id': None, 'voice_profile': {'tone': 'warm and plain'},
            'settings': {'availability': {'timezone': tz} if tz else {},
                         'brand_kit': {'colors': {'primary': '#1F4E79', 'accent': '#F2A900'}}, **settings}}


def connection(cid, platform_, biz=BIZ, status='connected'):
    return {'id': cid, 'business_id': biz, 'provider': 'post_for_me', 'platform': platform_, 'status': status,
            'username': f'kev.{platform_}', 'profile_photo_url': None, 'connected_at': '2026-10-01T12:00:00Z',
            'provider_account_id': f'spc_{platform_}_{cid[-4:]}'}


class FakeService:
    """The service-role reads and writes the planner makes outside the store."""

    def __init__(self):
        self.businesses = {BIZ: business(BIZ, OWNER), PRO: business(PRO, PRO_OWNER, name='Pro Shop', tier='professional')}
        self.connections = [connection(FB, 'facebook'), connection(str(uuid4()), 'facebook', biz=PRO)]
        self.sites = [{'business_id': BIZ, 'slug': 'kevs-fades', 'status': 'published', 'site_config': {},
                       'updated_at': '2026-10-01T00:00:00Z'},
                      {'business_id': PRO, 'slug': 'pro-shop', 'status': 'published', 'site_config': {},
                       'updated_at': '2026-10-01T00:00:00Z'}]
        self.profiles, self.notifications, self.modules, self.offerings = [], [], [], []
        self.reads, self.posts, self.fail = [], [], ()

    def get(self, path):
        self.reads.append(path)
        if any(f in path for f in self.fail):
            return None
        table = path.split('?', 1)[0]
        if table == '/businesses':
            rows = []
            for b in self.businesses.values():
                s = b.get('settings') or {}
                rows.append({**b, 'availability': s.get('availability'), 'booking_page': s.get('booking_page'),
                             'automations_paused': s.get('automations_paused')})
        else:
            rows = {'/social_connections': self.connections, '/business_sites': self.sites,
                    '/practitioner_profiles': self.profiles, '/chief_notifications': self.notifications,
                    '/custom_modules': self.modules, '/offerings': self.offerings}.get(table)
            if rows is None:
                raise AssertionError(f'unexpected read {path}')
        return copy.deepcopy(select(rows, path))

    def post(self, path, body, prefer=None):
        self.posts.append((path, copy.deepcopy(body)))
        if path == '/chief_notifications':
            row = {**copy.deepcopy(body), 'id': str(uuid4())}
            self.notifications.append(row)
            return [row]
        raise AssertionError(f'unexpected service write {path}')


class Reply:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        return None


def quiet_signals(**over):
    base = {'read_at': THU.isoformat(), 'business_id': BIZ, 'time_zone': 'America/Chicago',
            'traffic': {'visits': 30, 'weekly_visits_before': 28.0, 'counted_any': True, 'truncated': False},
            'leads': {'last_7_days': 2, 'weekly_before': 1.0},
            'bookings': {'next_7_days': 9, 'weekly_before': 10.0}, 'capacity': None,
            'new_offerings': [], 'unmarketed_offerings': [], 'news': [], 'fresh_news': [], 'unmarketed_news': [],
            'posts': {'last_published': '2026-10-05T16:00:00Z', 'published_last_7_days': 1,
                      'published_last_14_days': 2, 'approved_next_7_days': 1, 'looked_back_days': 90},
            'used_subjects': [], 'play_scores': {}, 'unread': []}
    base.update(over)
    return base


@pytest.fixture
def s(monkeypatch):
    for name in ('MARKETING_MAX_PER_TICK', 'BILLING_ENFORCE', 'PLATFORM_DEFAULT_TZ', 'MARKETING_DESK_PUBLISHING'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('MARKETING_DESK', '*')
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', '*')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    state = SimpleNamespace(now=THU, user=OWNER, share=[0.0], over=set(), reply=GOOD, calls=[], composed=[],
                            pushes=[], signals=quiet_signals(), compose_error=None, llm_error_for=set())
    db, svc = FakeStore(lambda: state.now), FakeService()
    state.db, state.svc = db, svc
    monkeypatch.setattr(store, 'request', db.request)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', svc.get)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', svc.post)

    def no_patch(*a, **k):
        raise AssertionError('the planner writes through business_marketing_store')
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', no_patch)
    monkeypatch.setattr(bm, 'now', lambda: state.now)
    monkeypatch.setattr(plan, '_now', lambda: state.now)

    async def read_signals(bid, *, now=None, business=None, tz=None):
        return copy.deepcopy({**state.signals, 'business_id': bid})

    async def read_profile(bid, *, business=None):
        site = next((x for x in svc.sites if x['business_id'] == bid), None)
        import business_marketing_links as links
        hosts = links.own_hosts(links.site_from_row(site))
        return prof.build_profile(business, hosts=hosts, tz=CHICAGO)
    monkeypatch.setattr(msig, 'read_signals', read_signals)
    monkeypatch.setattr(prof, 'read_profile', read_profile)
    monkeypatch.setattr(creative_director, 'business_facts', lambda bid: copy.deepcopy(FACTS))

    async def apost(client, payload=None, **kw):
        state.calls.append((copy.deepcopy(payload), kw))
        if kw.get('business_id') in state.llm_error_for:
            raise RuntimeError('the model did not answer')
        return Reply({'content': [{'type': 'text', 'text': json.dumps(state.reply)}],
                      'usage': {'input_tokens': 2000, 'output_tokens': 150}})
    monkeypatch.setattr(llm_call, 'apost', apost)

    async def compose(client, biz, action, request_id):
        state.composed.append({'biz': biz, 'layout': copy.deepcopy(action['layout']),
                               'actor': images.build_actor.get(), 'request_id': request_id})
        if state.compose_error:
            raise state.compose_error
        return {'image': {'id': ART}}
    monkeypatch.setattr(composer, 'compose', compose)

    async def no_paid_design(*a, **k):
        raise AssertionError('a suggestion never makes a paid design')
    monkeypatch.setattr(images, 'create', no_paid_design)
    monkeypatch.setattr(creative_director, 'prepare_for_business', no_paid_design)

    async def no_send(*a, **k):
        raise AssertionError('the planner never sends')
    monkeypatch.setattr(social, 'send_post', no_send)
    monkeypatch.setattr(push_notifications, 'send_to_user',
                        lambda user_id, **kw: state.pushes.append({'user': user_id, **kw}) or 1)

    def share(force=False):
        return state.share.pop(0) if len(state.share) > 1 else state.share[0]
    monkeypatch.setattr(spend_guard, 'platform_share', share)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda business_id=None: business_id in state.over)
    rate_limit._buckets.clear()

    db.desks[BIZ] = {'business_id': BIZ, 'plan_enabled': True, 'paused': False, 'connection_ids': [],
                     'post_hour': 11}
    db.desks[PRO] = {'business_id': PRO, 'plan_enabled': True, 'paused': False, 'connection_ids': [],
                     'post_hour': 11}

    api = FastAPI()
    api.include_router(plan.router)
    api.dependency_overrides[require_user] = lambda: SimpleNamespace(id=state.user, email='x@example.com',
                                                                     role='authenticated')
    state.client = TestClient(api)
    return state


def add_business(s, *, tier='starter', tz='America/Chicago', plan_enabled=True, connected=True, name=None):
    bid = str(uuid4())
    owner = str(uuid4())
    s.svc.businesses[bid] = business(bid, owner, name=name or f'Shop {bid[:4]}', tier=tier, tz=tz)
    s.svc.sites.append({'business_id': bid, 'slug': f'shop-{bid[:8]}', 'status': 'published', 'site_config': {},
                        'updated_at': '2026-10-01T00:00:00Z'})
    if connected:
        s.svc.connections.append(connection(str(uuid4()), 'facebook', biz=bid))
    s.db.desks[bid] = {'business_id': bid, 'plan_enabled': plan_enabled, 'paused': False, 'connection_ids': [],
                       'post_hour': 11}
    return bid


def posts_of(s, bid=BIZ, status=None):
    return [p for p in s.db.posts.values() if p['business_id'] == bid and (status is None or p['status'] == status)]


def runs_of(s, bid=BIZ):
    return [r for r in s.db.runs.values() if r['business_id'] == bid]


# ── when a suggestion is due ──────────────────────────────────────────

def at_local(tz, y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def test_the_jitter_is_stable_bounded_and_spread():
    ids = [str(uuid4()) for _ in range(1000)]
    values = [plan.jitter_minutes(i) for i in ids]
    assert all(0 <= v < 120 for v in values)
    assert len(set(values)) > 100 and min(values) < 10 and max(values) > 110
    for i in ids[:20]:
        digest = hashlib.sha256(f'marketing-jitter:{UUID(i)}'.encode()).digest()
        assert plan.jitter_minutes(i) == int.from_bytes(digest[:8], 'big') % 120 == plan.jitter_minutes(i.upper())


@pytest.mark.parametrize('tz', ['America/Chicago', 'America/New_York', 'Asia/Kolkata', 'Pacific/Auckland',
                                'Europe/London', 'America/Los_Angeles'])
def test_thursday_opens_at_seven_plus_jitter_on_the_business_clock(tz):
    j = plan.jitter_minutes(BIZ)
    opens = at_local(tz, 2026, 10, 8, 7) + timedelta(minutes=j)
    zone = ZoneInfo(tz)
    assert plan.due_week(opens - timedelta(minutes=1), zone, BIZ) is None
    assert plan.due_week(opens, zone, BIZ) == NEXT_MONDAY
    assert plan.due_week(at_local(tz, 2026, 10, 8, 20, 59), zone, BIZ) == NEXT_MONDAY
    assert plan.due_week(at_local(tz, 2026, 10, 8, 21, 0), zone, BIZ) is None       # never overnight
    assert plan.due_week(at_local(tz, 2026, 10, 9, 3, 0), zone, BIZ) is None
    assert plan.due_week(at_local(tz, 2026, 10, 11, 12, 0), zone, BIZ) == NEXT_MONDAY   # Sunday: still next week


def test_auckland_is_due_on_its_own_thursday_while_utc_says_wednesday():
    zone = ZoneInfo('Pacific/Auckland')
    j = plan.jitter_minutes(BIZ)
    at = at_local('Pacific/Auckland', 2026, 10, 8, 7) + timedelta(minutes=j)
    assert at.weekday() == 2                                   # Wednesday in UTC
    assert plan.due_week(at, zone, BIZ) == NEXT_MONDAY


@pytest.mark.parametrize('day,offset', [(date(2026, 10, 29), 4), (date(2026, 11, 5), 5)])
def test_new_york_keeps_seven_oclock_across_the_daylight_saving_change(day, offset):
    """2026-11-01 ends daylight saving in New York: 7:00 local is 11:00 UTC
    the Thursday before and 12:00 UTC the Thursday after."""
    zone = ZoneInfo('America/New_York')
    j = plan.jitter_minutes(BIZ)
    opens = datetime(day.year, day.month, day.day, 7 + offset, tzinfo=timezone.utc) + timedelta(minutes=j)
    assert plan.due_week(opens - timedelta(minutes=1), zone, BIZ) is None
    assert plan.due_week(opens, zone, BIZ) == day + timedelta(days=4)


def test_the_spring_change_too():
    zone = ZoneInfo('America/Chicago')            # 2026-03-08: daylight saving starts
    j = plan.jitter_minutes(BIZ)
    before = datetime(2026, 3, 5, 13, tzinfo=timezone.utc) + timedelta(minutes=j)       # CST, UTC-6
    after = datetime(2026, 3, 12, 12, tzinfo=timezone.utc) + timedelta(minutes=j)       # CDT, UTC-5
    assert plan.due_week(before, zone, BIZ) == date(2026, 3, 9)
    assert plan.due_week(after, zone, BIZ) == date(2026, 3, 16)
    assert plan.due_week(after - timedelta(minutes=1), zone, BIZ) is None


def test_monday_to_wednesday_is_this_week_and_thursday_morning_is_not_due():
    zone = CHICAGO
    assert plan.due_week(at_local('America/Chicago', 2026, 10, 6, 10), zone, BIZ) == THIS_MONDAY
    assert plan.due_week(at_local('America/Chicago', 2026, 10, 7, 20), zone, BIZ) == THIS_MONDAY
    assert plan.due_week(at_local('America/Chicago', 2026, 10, 8, 6, 59), zone, BIZ) is None
    assert plan.target_week(at_local('America/Chicago', 2026, 10, 8, 6, 59), zone) == THIS_MONDAY


def test_what_the_claim_would_allow():
    assert plan.claimable(None, THU)
    assert not plan.claimable({'status': 'succeeded'}, THU)
    assert plan.claimable({'status': 'failed', 'attempts': 2}, THU)
    assert not plan.claimable({'status': 'skipped', 'attempts': 3}, THU)
    assert not plan.claimable({'status': 'running', 'created_at': (THU - timedelta(minutes=5)).isoformat()}, THU)
    assert plan.claimable({'status': 'running', 'created_at': (THU - timedelta(minutes=20)).isoformat()}, THU)


# ── the switches ──────────────────────────────────────────────────────

def test_marketing_desk_off_ids_and_star(monkeypatch):
    for raw in (None, '', 'off', 'OFF', 'on', 'not-an-id'):
        if raw is None:
            monkeypatch.delenv('MARKETING_DESK', raising=False)
        else:
            monkeypatch.setenv('MARKETING_DESK', raw)
        assert plan.desk_scope() is None and not plan.desk_on_for(BIZ)
    monkeypatch.setenv('MARKETING_DESK', f' {BIZ.upper()} , junk')
    assert plan.desk_on_for(BIZ) and not plan.desk_on_for(PRO)
    monkeypatch.setenv('MARKETING_DESK', '*')
    assert plan.desk_on_for(BIZ) and plan.desk_on_for(PRO)


def test_the_per_tick_cap_reads_its_env(monkeypatch):
    monkeypatch.delenv('MARKETING_MAX_PER_TICK', raising=False)
    assert plan.max_per_tick() == 10
    for raw, want in (('3', 3), ('0', 1), ('500', 100), ('lots', 10)):
        monkeypatch.setenv('MARKETING_MAX_PER_TICK', raw)
        assert plan.max_per_tick() == want


def test_the_env_example_documents_both_switches():
    text = (ROOT / '.env.example').read_text(encoding='utf-8')
    assert '\nMARKETING_DESK=off' in text and '\nMARKETING_MAX_PER_TICK=10' in text


# ── one suggestion ────────────────────────────────────────────────────

def test_a_starter_business_gets_one_draft_for_next_week(s):
    out = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert out['status'] == 'succeeded' and out['week_of'] == NEXT_MONDAY.isoformat()
    (post,) = posts_of(s)
    assert post['source'] == 'suggestion' and post['status'] == 'draft' and post['revision'] == 1
    assert post['approved_hash'] is None and post['content_hash'] == store.digest(post)
    assert post['run_id'] == out['run_id'] and post['play_id'] == 'useful_tip'
    assert _when(post['run_at']).astimezone(CHICAGO) == datetime(2026, 10, 12, 11, tzinfo=CHICAGO)
    assert post['media'] == {'artwork_ids': [ART]} and post['design_status'] == 'ready'
    assert [t['connection_id'] for t in post['targets']] == [FB]
    assert post['landing_url'] == 'https://kevs-fades.mysolutionist.app/'
    assert '/go/' in post['publish_text'] and post['tracked_url'].startswith('https://kevs-fades.mysolutionist.app/')
    (r,) = runs_of(s)
    assert r['status'] == 'succeeded' and r['kind'] == 'suggestion' and r['trigger'] == 'scheduled'
    assert r['post_ids'] == [post['id']] and r['week_of'] == NEXT_MONDAY.isoformat()
    assert r['diagnosis']['rule'] == 'steady' and r['slots'][0]['play_id'] == 'useful_tip'
    assert r['design']['cost_usd'] == 0 and r['design']['made_by'] == 'composer'


def test_the_one_caption_call_is_small_metered_and_low_effort(s):
    run(plan.run_suggestion(BIZ, trigger='scheduled'))
    (payload, kw), = s.calls
    assert kw['task'] == 'business_marketing_suggestion' and kw['business_id'] == BIZ and kw['units'] == 0
    assert payload['max_tokens'] <= 1500 and payload['output_config'] == {'effort': 'low'}
    request = json.loads(payload['messages'][0]['content'])
    assert len(request['slots']) == 1 and request['facts']['offerings'][0]['price'] == '$150'
    assert '"Kev\'s Coaching"' in payload['system'] and 'at most 3 short hashtags' in payload['system']


def test_the_draft_is_never_approved_or_sent(s):
    run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert all(not path.startswith('/rpc/marketing_approve') for _, path, _ in s.db.writes)
    assert [p['status'] for p in posts_of(s)] == ['draft']


def test_a_professional_business_gets_no_suggestion_in_b8_even_with_billing_enforce_off(s, monkeypatch):
    monkeypatch.setenv('BILLING_ENFORCE', 'off')
    out = run(plan.run_suggestion(PRO, trigger='scheduled'))
    assert out['status'] == 'not_eligible' and out['reason'] == plan.WEEK_LEVEL
    assert runs_of(s, PRO) == [] and posts_of(s, PRO) == [] and s.calls == []
    starter = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert starter['status'] == 'succeeded'


def test_a_business_with_no_plan_gets_none(s):
    s.svc.businesses[BIZ]['comp_tier'] = None
    out = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert out == {'status': 'not_eligible', 'reason': plan.NO_PLAN} and s.db.runs == {}


def test_one_run_per_business_per_week(s):
    first = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    s.now = THU + timedelta(hours=1)
    second = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert first['status'] == 'succeeded' and second == {'status': 'exists', 'week_of': NEXT_MONDAY.isoformat()}
    assert len(runs_of(s)) == 1 and len(posts_of(s)) == 1 and len(s.calls) == 1


def test_a_crashed_attempt_keeps_its_draft_and_says_so_once(s):
    run(plan.run_suggestion(BIZ, trigger='scheduled'))
    (r,) = runs_of(s)
    r.update(status='failed', post_ids=[])            # the record was lost after the draft was saved
    s.svc.notifications.clear()
    s.pushes.clear()
    s.now = THU + timedelta(hours=1)
    out = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert out['status'] == 'succeeded' and out.get('resumed') is True
    assert len(posts_of(s)) == 1 and len(s.calls) == 1 and r['status'] == 'succeeded'
    assert len(s.svc.notifications) == 1 and len(s.pushes) == 1


# ── the caption checks ────────────────────────────────────────────────

def test_business_captions_take_up_to_three_hashtags_and_the_platform_none():
    profile = prof.build_profile(business(BIZ, OWNER), hosts=['kevs-fades.mysolutionist.app'])
    facts = eng.verified_facts(FACTS)
    three = 'Plan the week, then work the plan. Book a session. #coaching #plans #focus'
    four = three + ' #more'
    assert eng.check_caption(three, facts, profile) is None
    assert eng.check_caption(four, facts, profile) == 'more than 3 hashtags'
    assert platform.check_caption('Your week, handled. #smallbusiness #solutionist', set()) == 'hashtag'
    assert platform.check_caption('Your week, handled, every single day of it.', set()) is None
    assert eng.check_flyer({'headline': 'Plan your week', 'line': 'One session, one plan. #coaching',
                            'cta': 'Book a time'}, facts, profile) == 'hashtag on the flyer'


@pytest.mark.parametrize('text,why', [
    ('Plan the week, then work the plan. Book a session. #coaching #plans #focus #more', 'more than 3 hashtags'),
    # 60 is a number in the facts (the session's minutes), so only the price rule can catch it.
    ('A strategy session is just $60 this week, so book one and get your plan.', 'a price that is not in the facts'),
    ('A strategy session is just $99 this week, so book one and get your plan.', 'number not in the facts (99)'),
    ('Over 500 owners planned their week with us. Book a strategy session today.', 'number not in the facts (500)'),
    ('Book a strategy session at calendly.com/kev and plan your week the right way.',
     "link to somewhere other than the business's own site"),
])
def test_a_caption_that_breaks_a_rule_is_never_saved(s, text, why):
    s.reply = {'captions': [{**GOOD['captions'][0], 'text': text}]}
    out = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert out['status'] == 'failed' and out['reason'] == plan.CAPTION_BROKE
    (r,) = runs_of(s)
    assert r['status'] == 'failed' and r['dropped'] == [{'slot': 1, 'reason': why}]
    assert posts_of(s) == [] and s.composed == [] and s.pushes == [] and s.svc.notifications == []


def test_a_caption_may_name_its_own_site_and_its_own_price(s):
    text = 'A strategy session is $150 and takes 60 minutes. Book at kevs-fades.mysolutionist.app today.'
    s.reply = {'captions': [{**GOOD['captions'][0], 'text': text}]}
    assert run(plan.run_suggestion(BIZ, trigger='scheduled'))['status'] == 'succeeded'
    assert posts_of(s)[0]['caption'] == text


def test_flyer_words_that_break_a_rule_cost_the_picture_not_the_post(s):
    bad = {**GOOD['captions'][0]['flyer'], 'line': 'Only $49 this week for a session.'}
    s.reply = {'captions': [{**GOOD['captions'][0], 'flyer': bad}]}
    out = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert out['status'] == 'succeeded' and s.composed == []
    (post,) = posts_of(s)
    assert post['media'] == {} and post['design_status'] == 'none'
    assert runs_of(s)[0]['dropped'][0]['flyer_only'] is True


# ── the flyer: free, the business's own ───────────────────────────────

def _texts(layout):
    return [l['text'] for l in layout['layers'] if l['kind'] == 'text']


def test_the_flyer_is_the_free_composer_flyer_in_the_business_name_and_colours(s):
    run(plan.run_suggestion(BIZ, trigger='scheduled'))
    (made,) = s.composed
    layout = composer.Layout.model_validate(made['layout'])
    texts = _texts(made['layout'])
    assert "KEV'S COACHING" in texts and 'kevs-fades.mysolutionist.app' in texts
    assert not any('SOLUTIONIST SYSTEM' in t for t in texts) and 'mysolutionist.app' not in texts
    assert 'TIP' in texts                                       # the business play's eyebrow
    palette = design.brand_palette({'primary': '#1F4E79', 'accent': '#F2A900'})
    assert made['layout']['background'] == palette['bg'] != design.NAVY
    assert design.contrast(palette['bg'], '#FFFFFF') >= 7
    assert (layout.width, layout.height) == (1080, 1350)
    assert made['actor'] == {'business_id': BIZ, 'user_id': OWNER}       # bound to this business and owner
    assert images.build_actor.get() is None                                # and reset after


def test_a_flyer_that_cannot_be_made_leaves_a_words_only_post(s):
    s.compose_error = HTTPException(502, 'The image could not be saved.')
    assert run(plan.run_suggestion(BIZ, trigger='scheduled'))['status'] == 'succeeded'
    (post,) = posts_of(s)
    assert post['media'] == {} and runs_of(s)[0]['design']['failed'][0]['what'] == 'flyer'
    assert images.build_actor.get() is None


def test_instagram_alone_and_no_flyer_saves_nothing(s):
    s.compose_error = HTTPException(502, 'The image could not be saved.')
    s.svc.connections = [connection(IG, 'instagram')]
    out = run(plan.run_suggestion(BIZ, trigger='scheduled'))
    assert out['status'] == 'skipped' and 'Instagram' in out['reason'] and posts_of(s) == []


def test_tiktok_and_youtube_are_left_out_of_a_picture_post_not_gated(s):
    s.svc.connections += [connection(IG, 'instagram'), connection(str(uuid4()), 'tiktok'),
                          connection(str(uuid4()), 'youtube')]
    assert run(plan.run_suggestion(BIZ, trigger='scheduled'))['status'] == 'succeeded'
    (post,) = posts_of(s)
    assert sorted(t['platform'] for t in post['targets']) == ['facebook', 'instagram']
    left = runs_of(s)[0]['design']['left_out']
    assert sorted((d['platform'], d['why']) for d in left) == [('tiktok', 'needs_video'), ('youtube', 'needs_video')]


def test_an_overflowing_flyer_shrinks_and_tries_again(s):
    calls = []

    async def compose(client, biz, action, request_id):
        calls.append(action['layout'])
        if len(calls) < 3:
            raise HTTPException(422, 'Text exceeds its allocated width in layer-5.')
        return {'image': {'id': ART}}
    composer_compose = composer.compose
    try:
        composer.compose = compose
        run(plan.run_suggestion(BIZ, trigger='scheduled'))
    finally:
        composer.compose = composer_compose
    assert len(calls) == 3 and posts_of(s)[0]['media'] == {'artwork_ids': [ART]}


@pytest.mark.parametrize('name,host', [
    ("Kev's Coaching", 'kevs-fades.mysolutionist.app'),
    ('The Northeast Ohio Family Barbershop Co', 'northeast-ohio-family-barbershop.mysolutionist.app'),
    ('A' * 40, 'a-very-long-custom-domain-name-for-a-small-business.com'),
    ('Shop', None),
])
def test_a_business_footer_fits_and_names_only_the_business(name, host):
    footer = prof.flyer_footer(name, host)
    copy_ = {'headline': 'Plan the week ahead', 'line': 'One session, a clear plan, your next step.', 'cta': 'Book a time'}
    raw = design.flyer_layout('useful_tip', copy_, eyebrow='TIP', footer=footer, palette=design.brand_palette({}))
    composer.Layout.model_validate(raw)
    feet = [l for l in raw['layers'] if l['kind'] == 'text' and l['y'] >= 1350 - 110]
    assert feet and all(l['x'] >= 0 and l['x'] + l['width'] <= 1080 for l in feet)
    label = next(l for l in feet if l['text'] == footer['label'])
    assert len(label['text']) * (label['font_size'] * 0.8 + label['tracking']) <= label['width'] + 1
    hosts = [l for l in feet if l is not label]
    if hosts:
        assert hosts[0]['text'] == host and len(host) * hosts[0]['font_size'] * 0.6 <= hosts[0]['width']
        assert hosts[0]['x'] >= label['x'] + label['width']
    assert not any('SOLUTIONIST' in l['text'] for l in raw['layers'] if l['kind'] == 'text')


def test_the_platform_flyer_is_unchanged_without_a_business():
    copy_ = {'headline': 'Take a founding seat', 'line': 'Locked while you keep your seat.', 'cta': 'Claim your seat'}
    raw = design.flyer_layout('workflow_tip', copy_)
    texts = _texts(raw)
    assert 'THE SOLUTIONIST SYSTEM' in texts and 'mysolutionist.app' in texts and raw['background'] == design.NAVY


def test_palettes_stay_readable_whatever_the_brand():
    for colors in ({}, {'primary': '#FFFFFF'}, {'primary': '#FFD700', 'accent': '#FFD700'}, {'primary': '#000'},
                   {'primary': '#123456', 'secondary': '#ff6600'}, {'primary': 'not a colour'}):
        p = design.brand_palette(colors)
        assert design.contrast(p['ink'], p['bg']) >= 7 and design.contrast(p['ink'], p['bg2']) >= 4.5
        assert design.contrast(p['on_accent'], p['accent']) >= 3 and design.contrast(p['ice'], p['bg']) >= 4.5
        assert design.contrast(p['mist'], p['bg']) >= 4.5


# ── telling the owner, once ───────────────────────────────────────────

def test_exactly_one_push_and_one_today_item_per_suggestion(s):
    run(plan.run_suggestion(BIZ, trigger='scheduled'))
    (item,) = s.svc.notifications
    (push,) = s.pushes
    post = posts_of(s)[0]
    assert item['title'] == 'Chief has a post ready for next week' and item['type'] == 'reminder'
    assert "It's a useful tip" in item['body'] and 'Monday at 11:00 AM' in item['body']
    assert item['action_payload'] == {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing', 'post_id': post['id'],
                                      'dedup_key': f"marketing_suggestion:{post['id']}"}
    assert push['user'] == OWNER and push['nav'] == 'grow:marketing' and push['title'] == item['title']
    slot = runs_of(s)[0]['slots'][0]
    told = run(plan.tell_owner(s.svc.businesses[BIZ], post, slot, CHICAGO, NEXT_MONDAY, THU))
    assert told is False and len(s.svc.notifications) == 1 and len(s.pushes) == 1


def test_nothing_is_said_when_what_was_said_cannot_be_read(s):
    s.svc.fail = ('/chief_notifications',)
    assert run(plan.run_suggestion(BIZ, trigger='scheduled'))['status'] == 'succeeded'
    assert s.svc.notifications == [] and s.pushes == []


def test_an_offering_post_names_the_offering():
    slot = {'play_id': 'offer_spotlight', 'subject': 'Strategy session'}
    assert plan.about(slot, 'Kev') == 'about "Strategy session"'
    assert plan.about({'play_id': 'meet_us'}, "Kev's Coaching") == "an introduction to Kev's Coaching"


# ── the hourly fan-out ────────────────────────────────────────────────

def test_the_fan_out_writes_for_the_due_suggest_businesses_only(s):
    out = run(plan.marketing_tick(THU))
    assert out['candidates'] == 1 and out['succeeded'] == 1               # PRO is a week level: not a candidate
    assert len(posts_of(s)) == 1 and posts_of(s, PRO) == []


def test_off_does_nothing(s, monkeypatch):
    monkeypatch.setenv('MARKETING_DESK', 'off')
    assert run(plan.marketing_tick(THU)) == {'skipped': 'off'}
    assert run(plan.manual_tick(THU)) == {'skipped': 'off'}
    assert s.db.writes == [] and s.svc.reads == []


def test_named_ids_only(s, monkeypatch):
    other = add_business(s)
    monkeypatch.setenv('MARKETING_DESK', other)
    out = run(plan.marketing_tick(THU))
    assert out['succeeded'] == 1 and posts_of(s) == [] and len(posts_of(s, other)) == 1


def test_no_connected_account_or_switched_off_desk_is_not_a_candidate(s):
    add_business(s, connected=False)
    add_business(s, plan_enabled=False)
    nodesk = add_business(s)
    del s.db.desks[nodesk]
    out = run(plan.marketing_tick(THU))
    assert out['candidates'] == 1 and out['succeeded'] == 1
    assert {p['business_id'] for p in s.db.posts.values()} == {BIZ}
    assert nodesk not in s.db.desks                                        # no desk row is made here


def test_paused_automations_and_the_pilot_are_respected(s, monkeypatch):
    paused = add_business(s)
    s.svc.businesses[paused]['settings']['automations_paused'] = True
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', f'{BIZ},{paused}')
    outside = add_business(s)
    out = run(plan.marketing_tick(THU))
    assert out['candidates'] == 1 and posts_of(s, paused) == [] and posts_of(s, outside) == []


def test_never_overnight(s):
    night = at_local('America/Chicago', 2026, 10, 8, 3)
    out = run(plan.marketing_tick(night))
    assert out == {'candidates': 1, 'due': 0} and s.db.runs == {}


def test_monday_to_wednesday_writes_only_a_week_never_planned(s):
    tuesday = at_local('America/Chicago', 2026, 10, 6, 10)
    s.now = tuesday
    planned = add_business(s)
    rid = str(store.run_id_for(planned, THIS_MONDAY))
    s.db.runs[rid] = {'id': rid, 'business_id': planned, 'week_of': THIS_MONDAY.isoformat(), 'kind': 'suggestion',
                      'trigger': 'scheduled', 'status': 'succeeded', 'attempts': 1,
                      'created_at': '2026-10-01T12:00:00Z'}
    tried = add_business(s)
    rid2 = str(store.run_id_for(tried, THIS_MONDAY))
    s.db.runs[rid2] = {'id': rid2, 'business_id': tried, 'week_of': THIS_MONDAY.isoformat(), 'kind': 'suggestion',
                       'trigger': 'scheduled', 'status': 'failed', 'attempts': 3, 'created_at': '2026-10-01T12:00:00Z'}
    out = run(plan.marketing_tick(tuesday))
    assert out['due'] == 3 and out['to_do'] == 1 and out['succeeded'] == 1
    (post,) = posts_of(s)
    assert runs_of(s)[0]['week_of'] == THIS_MONDAY.isoformat()
    when = _when(post['run_at']).astimezone(CHICAGO)
    assert when == datetime(2026, 10, 6, 15, tzinfo=CHICAGO)        # the rest of this week, an hour away or more
    assert posts_of(s, planned) == [] and posts_of(s, tried) == []


def test_the_per_tick_cap_and_the_rest_wait(s, monkeypatch):
    monkeypatch.setenv('MARKETING_MAX_PER_TICK', '2')
    for _ in range(4):
        add_business(s)
    first = run(plan.marketing_tick(THU))
    assert first['to_do'] == 5 and first['succeeded'] == 2 and first['next_tick'] == 3
    s.now = THU + timedelta(hours=1)
    second = run(plan.marketing_tick(s.now))
    assert second['to_do'] == 3 and second['succeeded'] == 2
    s.now = THU + timedelta(hours=2)
    third = run(plan.marketing_tick(s.now))
    assert third['to_do'] == 1 and third['succeeded'] == 1
    assert len(s.db.posts) == 5 and len(s.db.runs) == 5


def test_a_second_tick_the_same_week_writes_nothing(s):
    run(plan.marketing_tick(THU))
    s.now = THU + timedelta(hours=1)
    out = run(plan.marketing_tick(s.now))
    assert out['to_do'] == 0 and len(s.db.posts) == 1 and len(s.calls) == 1


def test_one_failing_business_never_stops_the_batch(s):
    bad, good = add_business(s), add_business(s)
    s.llm_error_for = {bad}
    out = run(plan.marketing_tick(THU))
    assert out['succeeded'] == 2 and out['failed'] == 1
    (r,) = runs_of(s, bad)
    assert r['status'] == 'failed' and r['error'] == plan.FAILED and posts_of(s, bad) == []
    assert len(posts_of(s, good)) == 1


def test_one_business_raising_never_stops_the_batch(s, monkeypatch):
    bad = add_business(s)
    real = plan.run_suggestion

    async def flaky(business_id, **kw):
        if business_id == bad:
            raise RuntimeError('boom')
        return await real(business_id, **kw)
    monkeypatch.setattr(plan, 'run_suggestion', flaky)
    out = run(plan.marketing_tick(THU))
    assert out['error'] == 1 and out['succeeded'] == 1


def test_at_sixty_percent_of_the_cap_everything_waits(s):
    s.share = [0.6]
    assert run(plan.marketing_tick(THU)) == {'deferred': 'platform spend'}
    assert s.db.runs == {} and s.calls == []


def test_crossing_sixty_percent_mid_tick_defers_the_rest(s):
    for _ in range(3):
        add_business(s)
    s.share = [0.1, 0.2, 0.65]                    # the top, the first business, then the line is crossed
    out = run(plan.marketing_tick(THU))
    assert out['succeeded'] == 1 and out['deferred'] == 3 and len(s.db.runs) == 1


def test_a_business_over_its_own_ceiling_is_skipped(s):
    other = add_business(s)
    s.over = {other}
    out = run(plan.marketing_tick(THU))
    assert out['over_budget'] == 1 and out['succeeded'] == 1 and runs_of(s, other) == []


def test_the_platform_over_its_ceiling_defers_everyone(s):
    add_business(s)
    s.over = {''}
    out = run(plan.marketing_tick(THU))
    assert out['deferred'] == 2 and s.db.runs == {}


def test_a_failed_candidate_read_is_not_an_empty_list(s):
    s.svc.fail = ('/social_connections',)
    assert run(plan.marketing_tick(THU)) == {'skipped': 'unreadable'}
    assert s.db.runs == {}


def test_a_failed_profile_read_skips_those_businesses_not_guessing_utc(s):
    nozone = add_business(s, tz=None)
    s.svc.fail = ('/practitioner_profiles',)
    out = run(plan.marketing_tick(THU))
    assert out['candidates'] == 2 and out['due'] == 1 and posts_of(s, nozone) == []


def test_the_owner_profile_clock_is_used_when_the_business_has_none(s):
    nozone = add_business(s, tz=None)
    owner = s.svc.businesses[nozone]['owner_id']
    s.svc.profiles = [{'owner_id': owner, 'timezone': 'Pacific/Auckland'}]
    zones = plan.zones([dict(b, availability=b['settings'].get('availability')) for b in s.svc.businesses.values()])
    assert zones[nozone] == ZoneInfo('Pacific/Auckland') and zones[BIZ] == CHICAGO
    assert zones[nozone] == bm.business_tz(s.svc.businesses[nozone])


# ── the owner's own request ───────────────────────────────────────────

def ask(s, biz=BIZ):
    return s.client.post(f'/marketing/{biz}/engine/run')


def test_the_owner_queues_and_the_worker_writes(s, monkeypatch):
    async def web_never_calls_the_model(*a, **k):
        raise AssertionError('the web process never calls the model')
    real = llm_call.apost
    monkeypatch.setattr(llm_call, 'apost', web_never_calls_the_model)
    r = ask(s)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body['queued'] is True and body['week_of'] == NEXT_MONDAY.isoformat() and body['message'] == plan.QUEUED
    (queued,) = runs_of(s)
    assert queued['status'] == 'running' and queued['trigger'] == 'manual'
    assert queued['design']['queued_by'] == OWNER and 'started_at' not in queued['design']
    assert posts_of(s) == [] and s.composed == []
    monkeypatch.setattr(llm_call, 'apost', real)
    s.now = THU + timedelta(minutes=1)
    out = run(plan.manual_tick(s.now))
    assert out == {'succeeded': 1}
    assert queued['status'] == 'succeeded' and queued['design']['started_at'] and queued['design']['cost_usd'] == 0
    assert len(posts_of(s)) == 1 and len(s.pushes) == 1
    assert run(plan.manual_tick(s.now + timedelta(minutes=1))) == {}               # written once


def test_only_the_owner_may_ask(s):
    s.user = MEMBER
    r = ask(s)
    assert r.status_code == 403 and r.json()['detail'] == bm.OWNER_ONLY and s.db.writes == []


def test_asking_is_rate_limited(s, monkeypatch):
    monkeypatch.setattr(rate_limit, 'allow', lambda bucket, key: bucket != 'business_marketing_engine')
    r = ask(s)
    assert r.status_code == 429 and s.db.writes == []


def test_once_a_day(s):
    assert ask(s).status_code == 202
    s.now = THU + timedelta(minutes=1)
    run(plan.manual_tick(s.now))
    s.now = THU + timedelta(hours=2)
    r = ask(s)
    assert r.status_code == 429 and r.json()['detail'] == plan.ONCE_A_DAY
    s.now = THU + timedelta(days=1)                       # Friday: a new day on the business's clock
    assert ask(s).status_code == 202


def test_a_new_request_replaces_a_waiting_draft_never_an_approved_one(s):
    run(plan.run_suggestion(BIZ, trigger='scheduled'))
    (old,) = posts_of(s)
    s.now = THU + timedelta(days=1)
    assert ask(s).status_code == 202
    assert s.db.posts[old['id']]['status'] == 'cancelled'
    s.now += timedelta(minutes=1)
    assert run(plan.manual_tick(s.now)) == {'succeeded': 1}
    drafts = posts_of(s, status='draft')
    assert len(drafts) == 1 and drafts[0]['id'] != old['id']
    drafts[0].update(status='approved', approved_hash=drafts[0]['content_hash'])
    s.now = THU + timedelta(days=2)
    r = ask(s)
    assert r.status_code == 409 and r.json()['detail'] == plan.BUSY and drafts[0]['status'] == 'approved'


@pytest.mark.parametrize('setup,code,detail', [
    (lambda s, mp: mp.setenv('MARKETING_DESK', 'off'), 409, plan.NOT_SWITCHED_ON),
    (lambda s, mp: s.svc.businesses[BIZ].update(comp_tier='professional'), 409, plan.WEEK_LEVEL),
    (lambda s, mp: s.svc.businesses[BIZ].update(comp_tier=None), 403, plan.NO_PLAN),
    (lambda s, mp: setattr(s.svc, 'connections', []), 409, plan.NO_ACCOUNTS),
    (lambda s, mp: mp.setenv('POST_FOR_ME_PILOT_BUSINESSES', PRO), 409, plan.NO_POSTING),
])
def test_what_refuses_a_request_before_anything_is_written(s, monkeypatch, setup, code, detail):
    setup(s, monkeypatch)
    r = ask(s)
    assert r.status_code == code and r.json()['detail'] == detail
    assert s.db.writes == []


def test_a_queued_request_older_than_the_claim_window_is_left_alone(s):
    assert ask(s).status_code == 202
    s.now = THU + timedelta(minutes=16)
    assert run(plan.manual_tick(s.now)) == {} and posts_of(s) == []


# ── the preview ───────────────────────────────────────────────────────

def test_the_preview_reads_only(s, monkeypatch):
    async def no_model(*a, **k):
        raise AssertionError('the preview never calls the model')
    monkeypatch.setattr(llm_call, 'apost', no_model)
    r = s.client.get(f'/marketing/{BIZ}/preview')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['level'] == 'suggest' and len(body['slots']) == 1 and body['diagnosis']['rule'] == 'steady'
    assert body['plays'][0]['play_id'] == 'useful_tip' and body['week_of'] == NEXT_MONDAY.isoformat()
    assert body['profile']['flyer_footer'] == {'label': "KEV'S COACHING", 'host': 'kevs-fades.mysolutionist.app'}
    assert 'system_prompt' not in body['profile'] and body['switched_on'] is True
    assert s.db.writes == [] and s.svc.posts == [] and s.composed == [] and s.pushes == []


def test_only_the_owner_previews(s):
    s.user = MEMBER
    assert s.client.get(f'/marketing/{BIZ}/preview').status_code == 403


# ── the jobs ──────────────────────────────────────────────────────────

APP = (ROOT / 'kmj_intake_automation.py').read_text(encoding='utf-8')


def test_the_jobs_are_registered_leader_gated_before_the_gated_start():
    startup = APP.index('async def startup')
    started = APP.index('if runs_scheduled_jobs():\n        scheduler.start()')
    for job, every in (('business_marketing_suggest', 'hours=1'), ('business_marketing_requests', 'minutes=1')):
        at = APP.index(f'g("{job}", _marketing_planner.')
        assert startup < at < started
        call = APP[at:APP.index('\n', APP.index(f'id="{job}"'))]
        assert every in call and 'max_instances=1' in call
    assert APP.index('include_router(business_marketing_planner_router)') < APP.index('include_router(public_site')


def test_the_ticks_take_no_arguments_from_the_scheduler(s, monkeypatch):
    monkeypatch.setenv('MARKETING_DESK', 'off')
    assert run(plan.marketing_tick()) == {'skipped': 'off'} and run(plan.manual_tick()) == {'skipped': 'off'}
