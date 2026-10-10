"""The marketing desk API for one business (business_marketing.py, B4).

Who may read and who may write, every row tied to this business, the approval
binding, the next open time on the business's own clock, post-now's checks
before any write, settings validation, failed reads as 503, and the plan
level. No network: PostgREST (the marketing_* tables, the approve RPC and the
service-role reads) is an in-memory fake, and nothing is ever sent.
"""
from __future__ import annotations

import copy
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import business_marketing as bm
import business_marketing_store as store
import media_library
import sb_clients
from auth_supabase import require_user

BIZ = '0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d'
OTHER = '9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b'
OWNER = '11111111-1111-4111-8111-111111111111'
MEMBER = '22222222-2222-4222-8222-222222222222'
STRANGER = '33333333-3333-4333-8333-333333333333'
OTHER_OWNER = '44444444-4444-4444-8444-444444444444'
IG = 'c0000000-0000-4000-8000-000000000001'
FB = 'c0000000-0000-4000-8000-000000000002'
TT = 'c0000000-0000-4000-8000-000000000003'
GONE = 'c0000000-0000-4000-8000-000000000004'
THEIR_FB = 'c0000000-0000-4000-8000-000000000005'
ART = 'a0000000-0000-4000-8000-000000000001'
ART_WORKING = 'a0000000-0000-4000-8000-000000000002'
THEIR_ART = 'a0000000-0000-4000-8000-000000000003'
CLIP = 'd0000000-0000-4000-8000-000000000001'
THEIR_CLIP = 'd0000000-0000-4000-8000-000000000002'
COVER = 'e0000000-0000-4000-8000-000000000001'
NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)          # a Wednesday
CHANGED = 'A post changed or its time passed; refresh and review again'


# ── a small PostgREST ─────────────────────────────────────────────────

def pairs(path):
    query = path.split('?', 1)[1] if '?' in path else ''
    return [tuple(p.split('=', 1)) for p in query.split('&') if '=' in p]


def _when(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(unquote(str(value)).replace('Z', '+00:00'))


def _norm(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else str(value)


TIMES = {'run_at', 'expires_at', 'created_at', 'claimed_at'}


def matches(row, column, expr):
    column = {'director->>clip_id': 'clip_id'}.get(column, column)
    value = row.get(column)
    if expr == 'is.null':
        return value is None
    op, _, arg = expr.partition('.')
    if op == 'not' and arg.startswith('in.('):
        return _norm(value) not in arg[4:-1].split(',')
    if op == 'in':
        return _norm(value) in arg[1:-1].split(',')
    if op in ('gte', 'gt', 'lte', 'lt') and column in TIMES:
        a, b = _when(value), _when(arg)
        return {'gte': a >= b, 'gt': a > b, 'lte': a <= b, 'lt': a < b}[op]
    if op == 'eq':
        return _norm(value) == arg
    if op == 'neq':
        return _norm(value) != arg
    raise AssertionError(f'unexpected filter {column}={expr}')


def select(rows, path):
    out = list(rows)
    order = None
    limit = None
    for key, expr in pairs(path):
        if key == 'select':
            continue
        if key == 'order':
            order = expr
        elif key == 'limit':
            limit = int(expr)
        elif key == 'or':
            parts = [p.split('.', 1) for p in expr[1:-1].split(',')]
            out = [r for r in out if any(matches(r, c, e) for c, e in parts)]
        else:
            out = [r for r in out if matches(r, key, expr)]
    if order:
        column, _, direction = order.partition('.')
        out.sort(key=lambda r: str(r.get(column) or ''), reverse=direction.startswith('desc'))
    return out[:limit] if limit else out


class FakeStore:
    """marketing_desks, marketing_posts, marketing_runs and the approve RPC."""

    def __init__(self):
        self.desks, self.posts, self.runs = {}, {}, []
        self.writes, self.paths, self.fail = [], [], ()

    async def request(self, method, path, body=None):
        self.paths.append((method, path))
        query = path.split('?', 1)[1] if '?' in path else ''
        assert '+' not in query, f'unencoded + in a PostgREST query: {path}'
        if any(f in path for f in self.fail):
            raise store.StoreUnavailable('Marketing storage is unavailable. Please retry.')
        table = path.split('?', 1)[0]
        if method != 'GET':
            self.writes.append((method, path, copy.deepcopy(body)))
        if table == '/rpc/marketing_approve':
            return self.approve(body)
        if table == '/marketing_desks':
            return self.table(self.desks, method, path, body, key='business_id')
        if table == '/marketing_posts':
            return self.table(self.posts, method, path, body, key='id')
        if table == '/marketing_runs':
            assert method == 'GET'
            return copy.deepcopy(select(self.runs, path))
        raise AssertionError(f'unexpected store call {method} {path}')

    def table(self, rows, method, path, body, *, key):
        if method == 'GET':
            return copy.deepcopy(select(rows.values(), path))
        if method == 'POST':
            if str(body[key]) in rows:
                raise store.StoreConflict('The post changed. Refresh and review again.')
            row = {**(bm.DESK_DEFAULTS if key == 'business_id' else
                      {'design_status': 'none', 'approved_hash': None, 'approved_by': None, 'approved_at': None,
                       'approved_via': None, 'error': None, 'external_urls': [], 'run_id': None, 'play_id': None,
                       'opening': None}),
                   **copy.deepcopy(body), 'created_at': NOW.isoformat(), 'updated_at': NOW.isoformat()}
            self.check(row, key)
            rows[str(body[key])] = row
            return [copy.deepcopy(row)]
        if method == 'PATCH':
            hit = select(rows.values(), path)
            for row in hit:
                row.update(copy.deepcopy(body))
                self.check(row, key)
            return copy.deepcopy(hit)
        raise AssertionError(method)

    @staticmethod
    def check(row, key):
        """The migration's CHECKs, so a write the database would refuse fails here too."""
        if key == 'business_id':
            assert 6 <= row['post_hour'] <= 21
            return
        assert row['status'] in store.POST_STATUSES and row['source'] in store.POST_SOURCES
        assert len(row['content_hash']) == 64 and _when(row['expires_at']) > _when(row['run_at'])
        assert isinstance(row['targets'], list) and isinstance(row['media'], dict)

    def approve(self, body):
        """marketing_approve: every exact reviewed version, or none."""
        items, biz = body['p_items'], body['p_business_id']
        staged = []
        for item in sorted(items, key=lambda i: i['id']):
            r = self.posts.get(item['id'])
            if not r or r['business_id'] != biz:
                raise store.StoreConflict(CHANGED)
            if r['design_status'] == 'designing':
                raise store.StoreConflict('A flyer is still being made; approve that post when it is ready')
            if (r['status'] != 'draft' or r['revision'] != item['revision']
                    or r['content_hash'] != item['content_hash'] or _when(r['run_at']) <= NOW):
                raise store.StoreConflict(CHANGED)
            staged.append(r)
        for r in staged:
            r.update(status='approved', approved_hash=r['content_hash'], approved_by=body['p_actor'],
                     approved_at=NOW.isoformat(), approved_via=body['p_via'])
        return len(staged)


def connection(cid, platform, *, biz=BIZ, status='connected', username=None):
    return {'id': cid, 'business_id': biz, 'provider': 'post_for_me', 'platform': platform, 'status': status,
            'username': username or f'fade.{platform}', 'profile_photo_url': None,
            'connected_at': '2026-10-01T12:00:00Z', 'provider_account_id': f'spc_{platform}_{cid[-2:]}',
            'access_token': 'NEVER-LEAVES'}


def clip_row(cid, biz=BIZ, **over):
    row = {'id': cid, 'business_id': biz, 'kind': 'clip', 'status': 'ready', 'source_id': str(uuid4()),
           'sha256': 'b' * 64, 'configuration': {'caption': 'A cut in sixty seconds.'}, 'name': 'Sixty seconds',
           'source_removed_at': None}
    row.update(over)
    row.setdefault('approval', {'fingerprint': media_library.fingerprint(row)})
    return row


class FakeService:
    """The service-role reads: businesses, members, profiles, accounts,
    pictures, clips, sites and modules."""

    def __init__(self):
        self.businesses = {
            BIZ: {'id': BIZ, 'owner_id': OWNER, 'name': 'Fade Street', 'type': 'barber', 'comp_tier': 'starter',
                  'subscription_status': None, 'subscription_plan': None,
                  'settings': {'availability': {'timezone': 'America/Chicago'}}},
            OTHER: {'id': OTHER, 'owner_id': OTHER_OWNER, 'name': 'Elsewhere', 'type': 'coach', 'comp_tier': 'starter',
                    'settings': {}},
        }
        self.members = [{'business_id': BIZ, 'user_id': MEMBER, 'status': 'active', 'role': 'member'}]
        self.profiles = [{'owner_id': OWNER, 'timezone': 'America/Denver'}]
        self.connections = [connection(IG, 'instagram'), connection(FB, 'facebook'), connection(TT, 'tiktok'),
                            connection(GONE, 'x', status='disconnected'),
                            connection(THEIR_FB, 'facebook', biz=OTHER)]
        self.artworks = [
            {'id': ART, 'business_id': BIZ, 'status': 'ready', 'storage_path': f'{BIZ}/{ART}.png', 'size': '1024x1536',
             'created_at': '2026-10-06T12:00:00Z', 'clip_id': None},
            {'id': ART_WORKING, 'business_id': BIZ, 'status': 'working', 'storage_path': None, 'size': '1024x1536',
             'created_at': '2026-10-06T12:00:00Z', 'clip_id': None},
            {'id': THEIR_ART, 'business_id': OTHER, 'status': 'ready', 'storage_path': f'{OTHER}/{THEIR_ART}.png',
             'size': '1024x1536', 'created_at': '2026-10-06T12:00:00Z', 'clip_id': None},
            {'id': COVER, 'business_id': BIZ, 'status': 'ready', 'storage_path': f'{BIZ}/{COVER}.png',
             'size': '1088x1920', 'created_at': '2026-10-06T13:00:00Z', 'clip_id': CLIP},
        ]
        self.clips = [clip_row(CLIP), clip_row(THEIR_CLIP, biz=OTHER)]
        self.sites = [{'business_id': BIZ, 'slug': 'fade-street',
                       'site_config': {'custom_domain': 'fadestreet.com', 'custom_domain_status': 'verified'}},
                      {'business_id': OTHER, 'slug': 'elsewhere', 'site_config': {}}]
        self.modules = []
        self.reads, self.fail = [], ()

    def get(self, path):
        self.reads.append(path)
        if any(f in path for f in self.fail):
            return None
        table = path.split('?', 1)[0]
        rows = {
            '/businesses': [{**b, 'availability': (b.get('settings') or {}).get('availability')}
                            for b in self.businesses.values()],
            '/business_users': self.members, '/practitioner_profiles': self.profiles,
            '/social_connections': self.connections, '/image_artworks': self.artworks,
            '/media_assets': self.clips, '/business_sites': self.sites, '/custom_modules': self.modules,
        }.get(table)
        if rows is None:
            raise AssertionError(f'unexpected read {path}')
        return copy.deepcopy(select(rows, path))


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', BIZ)
    monkeypatch.setenv('MARKETING_DESK_PUBLISHING', 'on')
    monkeypatch.delenv('PLATFORM_DEFAULT_TZ', raising=False)
    monkeypatch.delenv('BILLING_ENFORCE', raising=False)
    db, svc = FakeStore(), FakeService()
    monkeypatch.setattr(store, 'request', db.request)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', svc.get)

    def no_writes(*a, **k):
        raise AssertionError('the desk API writes only through business_marketing_store')
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', no_writes)
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', no_writes)
    monkeypatch.setattr(bm, 'now', lambda: NOW)
    state = SimpleNamespace(db=db, svc=svc, user=OWNER)
    api = FastAPI()
    api.include_router(bm.router)
    api.dependency_overrides[require_user] = lambda: SimpleNamespace(id=state.user, email='x@example.com',
                                                                     role='authenticated')
    api.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=state.user), token='jwt')
    state.client = TestClient(api)
    return state


def seed(s, *, biz=BIZ, run_at=None, status='draft', targets=(FB,), media=None, caption='Fresh fades all week.',
         **over):
    """A post as the desk saves it, put straight into the fake table."""
    pid = str(uuid4())
    by_id = {c['id']: c for c in s.svc.connections}
    row = bm.new_post(biz, pid, caption=caption, media=media or {},
                      targets=[bm._target(by_id[t]) for t in targets],
                      run_at=run_at or NOW + timedelta(days=2), expires_at=(run_at or NOW + timedelta(days=2)) + bm.WINDOW,
                      landing=None)
    row.update(status=status, design_status='none', approved_hash=None, approved_by=None, approved_at=None,
               approved_via=None, error=None, external_urls=[], run_id=None, play_id=None, opening=None,
               created_at=NOW.isoformat(), updated_at=NOW.isoformat())
    row.update(over)
    s.db.posts[pid] = row
    return copy.deepcopy(row)            # what the owner saw, not the live row


def item(row):
    return {'id': row['id'], 'revision': row['revision'], 'content_hash': row['content_hash']}


def slot(row):
    return {'id': row['id'], 'revision': row['revision']}


def url(path, biz=BIZ):
    return f'/marketing/{biz}{path}'


def call(s, method, path, body=None, biz=BIZ):
    return s.client.request(method, url(path, biz), json=body)


# ── who may read, who may write ───────────────────────────────────────

WRITES = [
    ('GET', '/ideas/next-slot', lambda s, p, u: None),
    ('POST', '/ideas', lambda s, p, u: {'caption': 'Fresh fades all week.'}),
    ('POST', '/approve', lambda s, p, u: {'items': [item(p)]}),
    ('POST', '/slot/edit', lambda s, p, u: {'items': [slot(p)], 'caption': 'New words.'}),
    ('POST', '/slot/cancel', lambda s, p, u: {'items': [slot(p)]}),
    ('POST', '/post-now', lambda s, p, u: {'items': [item(p)]}),
    ('POST', 'not-sent', lambda s, p, u: {'revision': u['revision']}),
    ('PUT', '/settings', lambda s, p, u: {'paused': True}),
]


def _route(s, method, path, body):
    p = seed(s)
    u = seed(s, status='uncertain', run_at=NOW - timedelta(hours=1))
    if path == 'not-sent':
        path = f"/posts/{u['id']}/not-sent"
    return path, body(s, p, u), p, u


@pytest.mark.parametrize('who', [MEMBER, STRANGER], ids=['member', 'stranger'])
@pytest.mark.parametrize('method,path,body', WRITES, ids=[w[1] for w in WRITES])
def test_only_the_owner_writes(s, who, method, path, body):
    path, payload, p, u = _route(s, method, path, body)
    before = copy.deepcopy(s.db.posts)
    s.user = who
    r = call(s, method, path, payload)
    assert r.status_code == 403 and r.json()['detail'] == bm.OWNER_ONLY
    assert s.db.writes == [] and s.db.posts == before and s.db.desks == {}


@pytest.mark.parametrize('method,path,body', WRITES, ids=[w[1] for w in WRITES])
def test_the_owner_writes(s, method, path, body):
    path, payload, p, u = _route(s, method, path, body)
    r = call(s, method, path, payload)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize('method,path,body', WRITES, ids=[w[1] for w in WRITES])
def test_an_unknown_business_is_not_found(s, method, path, body):
    path, payload, p, u = _route(s, method, path, body)
    r = call(s, method, path, payload, biz=str(uuid4()))
    assert r.status_code == 404 and s.db.writes == []


def test_owner_and_members_read_the_desk_and_a_stranger_does_not(s):
    seed(s)
    owner = call(s, 'GET', '/engine')
    assert owner.status_code == 200 and owner.json()['can_edit'] is True and owner.json()['role'] == 'owner'
    s.user = MEMBER
    member = call(s, 'GET', '/engine')
    assert member.status_code == 200 and member.json()['can_edit'] is False and member.json()['role'] == 'member'
    assert member.json()['this_week'] == owner.json()['this_week']
    s.user = STRANGER
    assert call(s, 'GET', '/engine').status_code == 404
    assert s.db.writes == []


def test_reading_the_desk_writes_nothing_and_shows_no_secrets(s):
    seed(s, targets=(FB, IG), media={'artwork_ids': [ART]})
    body = call(s, 'GET', '/engine').json()
    assert s.db.writes == []
    text = repr(body)
    assert 'NEVER-LEAVES' not in text and 'spc_' not in text and 'provider_account_id' not in text
    assert [c['label'] for c in body['connections']] == ['Instagram', 'Facebook', 'TikTok']
    assert set(body['connections'][0]) == {'id', 'platform', 'label', 'username', 'profile_photo_url',
                                           'connected_at', 'in_desk'}
    assert body['desk'] == {**bm.DESK_DEFAULTS, 'updated_at': None, 'exists': False}
    assert body['posting'] == {'configured': True, 'allowed': True, 'sending': True}
    assert body['time_zone'] == 'America/Chicago'


def test_the_desk_shows_this_week_and_next_week_on_the_business_clock(s):
    # Chicago: Wednesday 2026-10-07 09:00 local. This week is Oct 5-11, next week Oct 12-18.
    this = seed(s, run_at=datetime(2026, 10, 9, 16, tzinfo=timezone.utc))
    late_sunday = seed(s, run_at=datetime(2026, 10, 12, 3, tzinfo=timezone.utc))   # Sunday 22:00 in Chicago
    nxt = seed(s, run_at=datetime(2026, 10, 13, 16, tzinfo=timezone.utc))
    seed(s, run_at=datetime(2026, 10, 25, 16, tzinfo=timezone.utc))
    seed(s, run_at=datetime(2026, 10, 9, 18, tzinfo=timezone.utc), status='cancelled')
    body = call(s, 'GET', '/engine').json()
    assert body['this_week']['week_of'] == '2026-10-05' and body['next_week']['week_of'] == '2026-10-12'
    assert [p['id'] for p in body['this_week']['posts']] == [this['id'], late_sunday['id']]
    assert [p['id'] for p in body['next_week']['posts']] == [nxt['id']]
    assert body['this_week']['posts'][0]['accounts'] == ['Facebook']
    assert body['note']['headline'] == 'Four posts wait for your OK.'
    assert body['note']['body'][0] == "Friday's goes out at 11:00 AM once you approve it."   # 16:00Z in Chicago


# ── this business's rows only ─────────────────────────────────────────

def test_another_business_post_reads_like_a_missing_one_everywhere(s):
    theirs = seed(s, biz=OTHER, targets=(THEIR_FB,))
    unsure = seed(s, biz=OTHER, targets=(THEIR_FB,), status='uncertain', run_at=NOW - timedelta(hours=1))
    before = copy.deepcopy(s.db.posts)
    r = call(s, 'POST', '/approve', {'items': [item(theirs)]})
    assert r.status_code == 409 and r.json()['detail'] == CHANGED
    for path, body in (('/slot/edit', {'items': [slot(theirs)], 'caption': 'Mine now.'}),
                       ('/slot/cancel', {'items': [slot(theirs)]})):
        r = call(s, 'POST', path, body)
        assert r.status_code == 409 and r.json()['detail'] == bm.GONE_POST
    r = call(s, 'POST', '/post-now', {'items': [item(theirs)]})
    assert r.status_code == 409 and 'Nothing was sent' in r.json()['detail']
    r = call(s, 'POST', f"/posts/{unsure['id']}/not-sent", {'revision': unsure['revision']})
    assert r.status_code == 409
    assert s.db.posts == before
    assert not any(m == 'POST' and p.startswith('/rpc/') for m, p, _ in s.db.writes)


def test_another_business_picture_clip_or_account_is_refused(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Look at this.', 'artwork_id': THEIR_ART})
    assert r.status_code == 404 and "isn't in this business" in r.json()['detail']
    r = call(s, 'POST', '/ideas', {'caption': 'Look at this.', 'clip_id': THEIR_CLIP})
    assert r.status_code == 404 and r.json()['detail'] == 'That clip is not in this business.'
    r = call(s, 'POST', '/ideas', {'caption': 'Look at this.', 'connection_ids': [FB, THEIR_FB]})
    assert r.status_code == 422 and r.json()['detail'] == bm.NOT_CONNECTED
    r = call(s, 'POST', '/ideas', {'caption': 'Look at this.', 'connection_ids': [GONE]})
    assert r.status_code == 422 and r.json()['detail'] == bm.NOT_CONNECTED
    p = seed(s)
    r = call(s, 'POST', '/slot/edit', {'items': [slot(p)], 'connection_ids': [THEIR_FB]})
    assert r.status_code == 422
    r = call(s, 'POST', '/slot/edit', {'items': [slot(p)], 'artwork_id': THEIR_ART})
    assert r.status_code == 404
    r = call(s, 'PUT', '/settings', {'connection_ids': [FB, THEIR_FB]})
    assert r.status_code == 422 and r.json()['detail'] == bm.NOT_CONNECTED
    assert s.db.writes == [] and len(s.db.posts) == 1


def test_a_picture_still_being_made_is_refused(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Look at this.', 'artwork_id': ART_WORKING})
    assert r.status_code == 409 and 'still being made' in r.json()['detail'] and s.db.writes == []


# ── new posts ─────────────────────────────────────────────────────────

def test_a_new_post_goes_to_every_account_that_can_take_it_and_says_which_cannot(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Fresh fades all week.', 'run_at': '2026-10-09T16:00:00Z'})
    assert r.status_code == 200, r.text
    body = r.json()
    saved = s.db.posts[body['post']['id']]
    assert [t['platform'] for t in saved['targets']] == ['facebook']          # Instagram and TikTok left out
    assert {d['label'] for d in body['dropped']} == {'Instagram', 'TikTok'}
    assert body['note'] == 'Instagram needs a picture; TikTok takes only videos, so this post leaves them out.'
    assert saved['status'] == 'draft' and saved['source'] == 'owner' and saved['revision'] == 1
    assert saved['content_hash'] == store.digest(saved) and saved['link_code'] == store.link_code(saved['id'])
    assert saved['expires_at'] == (datetime(2026, 10, 9, 16, tzinfo=timezone.utc) + bm.WINDOW).isoformat()
    assert BIZ in s.db.desks                                   # the desk row the sender needs now exists
    assert 'provider_account_id' not in repr(body)


def test_a_picture_post_takes_instagram_too(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Fresh fades all week.', 'artwork_id': ART})
    saved = s.db.posts[r.json()['post']['id']]
    assert [t['platform'] for t in saved['targets']] == ['instagram', 'facebook']
    assert saved['media'] == {'artwork_ids': [ART]}
    assert r.json()['note'] == 'TikTok takes only videos, so this post leaves it out.'


def test_a_clip_post_binds_its_fingerprint_and_cover_and_goes_everywhere(s):
    fp = media_library.fingerprint(s.svc.clips[0])
    r = call(s, 'POST', '/ideas', {'caption': 'Sixty seconds.', 'clip_id': CLIP, 'clip_fingerprint': fp})
    assert r.status_code == 200, r.text
    saved = s.db.posts[r.json()['post']['id']]
    assert saved['media'] == {'clip_id': CLIP, 'clip_fingerprint': fp, 'covers': {'story': COVER}}
    assert [t['platform'] for t in saved['targets']] == ['instagram', 'facebook', 'tiktok']


def test_an_unapproved_or_changed_clip_is_refused(s):
    s.svc.clips[0]['approval'] = None
    r = call(s, 'POST', '/ideas', {'caption': 'Sixty seconds.', 'clip_id': CLIP})
    assert r.status_code == 409 and 'Approve this clip' in r.json()['detail']
    s.svc.clips[0]['approval'] = {'fingerprint': 'f' * 64}
    r = call(s, 'POST', '/ideas', {'caption': 'Sixty seconds.', 'clip_id': CLIP})
    assert r.status_code == 409 and 'changed after it was approved' in r.json()['detail']
    assert s.db.writes == []


ART2 = 'a0000000-0000-4000-8000-000000000009'


def _second_picture(s):
    s.svc.artworks.append({'id': ART2, 'business_id': BIZ, 'status': 'ready', 'storage_path': f'{BIZ}/{ART2}.png',
                           'size': '1024x1024', 'created_at': '2026-10-08T12:00:00Z', 'clip_id': None})


def test_several_pictures_are_one_post_in_the_owners_order(s):
    _second_picture(s)
    r = call(s, 'POST', '/ideas', {'caption': 'Three looks this week.', 'artwork_ids': [ART2, ART, ART2]})
    assert r.status_code == 200, r.text
    saved = s.db.posts[r.json()['post']['id']]
    assert saved['media'] == {'artwork_ids': [ART2, ART]}              # in order, each once: the first is the one people see
    assert [t['platform'] for t in saved['targets']] == ['instagram', 'facebook']
    assert saved['content_hash'] == store.digest(saved)


def test_pictures_are_refused_with_a_clip_with_artwork_id_past_ten_or_not_this_business(s):
    _second_picture(s)
    fp = media_library.fingerprint(s.svc.clips[0])
    r = call(s, 'POST', '/ideas', {'caption': 'x', 'artwork_ids': [ART], 'clip_id': CLIP, 'clip_fingerprint': fp})
    assert r.status_code == 422 and r.json()['detail'] == 'A post carries a clip or a picture, not both.'
    r = call(s, 'POST', '/ideas', {'caption': 'x', 'artwork_id': ART, 'artwork_ids': [ART2]})
    assert r.status_code == 422 and r.json()['detail'] == 'Send the pictures as one list.'
    r = call(s, 'POST', '/ideas', {'caption': 'x', 'artwork_ids': [ART] * 11})
    assert r.status_code == 422                                          # the door takes at most ten
    r = call(s, 'POST', '/ideas', {'caption': 'x', 'artwork_ids': [ART, THEIR_ART]})
    assert r.status_code == 404 and "isn't in this business" in r.json()['detail']
    r = call(s, 'POST', '/ideas', {'caption': 'x', 'artwork_ids': [ART, ART_WORKING]})
    assert r.status_code == 409 and 'still being made' in r.json()['detail']
    assert s.db.writes == []


def test_an_edit_can_set_several_pictures(s):
    _second_picture(s)
    p = seed(s, targets=(FB,), media={'artwork_ids': [ART]})
    r = call(s, 'POST', '/slot/edit', {'items': [slot(p)], 'artwork_ids': [ART, ART2]})
    assert r.status_code == 200, r.text
    row = s.db.posts[p['id']]
    assert row['media'] == {'artwork_ids': [ART, ART2]} and row['revision'] == 2 and row['status'] == 'draft'
    r = call(s, 'POST', '/slot/edit', {'items': [slot(row)], 'artwork_ids': [ART], 'remove_media': True})
    assert r.status_code == 422


def test_only_instagram_without_a_picture_saves_nothing(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Fresh fades.', 'connection_ids': [IG]})
    assert r.status_code == 422 and 'Instagram needs a picture' in r.json()['detail']
    assert s.db.writes == [] and s.db.posts == {}


def test_the_desk_accounts_are_the_default_when_it_names_some(s):
    s.db.desks[BIZ] = {**bm.DESK_DEFAULTS, 'business_id': BIZ, 'connection_ids': [IG, GONE]}
    r = call(s, 'POST', '/ideas', {'caption': 'Fresh fades.', 'artwork_id': ART})
    assert [t['platform'] for t in s.db.posts[r.json()['post']['id']]['targets']] == ['instagram']
    s.db.desks[BIZ]['connection_ids'] = [GONE]
    r = call(s, 'POST', '/ideas', {'caption': 'Fresh fades.', 'artwork_id': ART})
    assert r.status_code == 422 and "desk's accounts" in r.json()['detail']


def test_a_retried_save_is_the_same_post(s):
    idea = str(uuid4())
    a = call(s, 'POST', '/ideas', {'id': idea, 'caption': 'Fresh fades.'}).json()
    b = call(s, 'POST', '/ideas', {'id': idea, 'caption': 'Fresh fades.'}).json()
    assert a['post']['id'] == b['post']['id'] and b['already_saved'] is True and len(s.db.posts) == 1
    assert a['post']['id'] == bm.idea_post_id(BIZ, idea) != bm.idea_post_id(OTHER, idea)


def test_a_caption_too_long_for_a_network_is_refused(s):
    s.svc.connections.append(connection('c0000000-0000-4000-8000-000000000009', 'x'))
    r = call(s, 'POST', '/ideas', {'caption': 'y' * 300})
    assert r.status_code == 422 and 'X allows 280 characters' in r.json()['detail'] and s.db.writes == []


def test_a_link_must_be_the_business_own_site(s):
    ok = call(s, 'POST', '/ideas', {'caption': 'Book now.', 'landing_url': 'https://fade-street.mysolutionist.app/book'})
    assert ok.status_code == 200 and ok.json()['post']['landing_url'].endswith('/book')
    for bad in ('https://elsewhere.mysolutionist.app/', 'https://evil.example/fadestreet.com', 'http://fadestreet.com/',
                'https://fadestreet.com.evil.example/', 'https://user@fadestreet.com/'):
        r = call(s, 'POST', '/ideas', {'caption': 'Book now.', 'landing_url': bad})
        assert r.status_code == 422, bad


# ── the next open time ────────────────────────────────────────────────

def test_next_slot_across_a_dst_change_keeps_the_local_hour(s, monkeypatch):
    s.svc.businesses[BIZ]['settings']['availability'] = {'timezone': 'Europe/London'}
    friday = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)      # 17:00 BST; clocks go back on Sunday the 25th
    monkeypatch.setattr(bm, 'now', lambda: friday)
    r = call(s, 'GET', '/ideas/next-slot')
    assert r.status_code == 200, r.text
    assert r.json() == {'run_at': '2026-10-26T11:00:00+00:00', 'time_zone': 'Europe/London',
                        'when': 'Monday 11:00 AM'}                     # 11:00 GMT, not 10:00 (BST's 11:00)
    seed(s, run_at=datetime(2026, 10, 26, 11, tzinfo=timezone.utc))
    assert call(s, 'GET', '/ideas/next-slot').json()['run_at'] == '2026-10-26T15:00:00+00:00'
    read = [p for m, p in s.db.paths if p.startswith('/marketing_posts?') and 'select=run_at' in p]
    assert read and all('+' not in p for p in read)
    assert '&status=not.in.(cancelled,pulled)' in read[0] and f'business_id=eq.{BIZ}' in read[0]


def test_next_slot_uses_the_desk_hour_and_skips_the_weekend(s, monkeypatch):
    s.db.desks[BIZ] = {**bm.DESK_DEFAULTS, 'business_id': BIZ, 'post_hour': 18}
    saturday = datetime(2026, 10, 10, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(bm, 'now', lambda: saturday)
    # Chicago (CDT, UTC-5): Monday 15:00 local is 20:00Z.
    assert call(s, 'GET', '/ideas/next-slot').json()['run_at'] == '2026-10-12T20:00:00+00:00'


def test_the_time_zone_falls_back_to_the_owner_profile(s, monkeypatch):
    s.svc.businesses[BIZ]['settings'] = {}
    monkeypatch.setattr(bm, 'now', lambda: datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
    r = call(s, 'GET', '/ideas/next-slot').json()
    assert r['time_zone'] == 'America/Denver' and r['run_at'] == '2026-10-07T17:00:00+00:00'   # 11:00 MDT
    s.svc.fail = ('/practitioner_profiles',)
    r = call(s, 'GET', '/ideas/next-slot')
    assert r.status_code == 503 and 'time zone' in r.json()['detail']


def test_a_new_post_without_a_time_takes_the_next_open_slot(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Fresh fades.'})
    # Wednesday 09:00 in Chicago: 11:00 today is open and more than an hour away.
    assert r.json()['run_at'] == '2026-10-07T16:00:00+00:00'


# ── approve ───────────────────────────────────────────────────────────

def test_approve_binds_the_exact_reviewed_version(s):
    p = seed(s)
    r = call(s, 'POST', '/approve', {'items': [item(p)]})
    assert r.status_code == 200 and r.json() == {'approved': 1}
    row = s.db.posts[p['id']]
    assert row['status'] == 'approved' and row['approved_hash'] == p['content_hash']
    assert row['approved_by'] == OWNER and row['approved_via'] == 'owner'


def test_content_changed_since_review_is_409(s):
    p = seed(s)
    r = call(s, 'POST', '/approve', {'items': [{**item(p), 'content_hash': 'a' * 64}]})
    assert r.status_code == 409 and r.json()['detail'] == CHANGED
    assert s.db.posts[p['id']]['status'] == 'draft'
    edited = call(s, 'POST', '/slot/edit', {'items': [slot(p)], 'caption': 'Changed after review.'})
    assert edited.status_code == 200
    r = call(s, 'POST', '/approve', {'items': [item(p)]})              # what the owner saw before the edit
    assert r.status_code == 409 and s.db.posts[p['id']]['status'] == 'draft'


def test_approve_is_all_or_nothing_and_says_what_the_database_said(s):
    a, b = seed(s), seed(s)
    r = call(s, 'POST', '/approve', {'items': [item(a), {**item(b), 'revision': 7}]})
    assert r.status_code == 409 and r.json()['detail'] == CHANGED
    assert s.db.posts[a['id']]['status'] == s.db.posts[b['id']]['status'] == 'draft'
    s.db.posts[b['id']]['design_status'] = 'designing'
    r = call(s, 'POST', '/approve', {'items': [item(a), item(b)]})
    assert r.status_code == 409 and r.json()['detail'] == 'A flyer is still being made; approve that post when it is ready'
    assert s.db.posts[a['id']]['status'] == 'draft'


def test_approve_refuses_a_post_whose_account_was_disconnected(s):
    p = seed(s, targets=(FB, GONE))
    r = call(s, 'POST', '/approve', {'items': [item(p)]})
    assert r.status_code == 409 and 'no longer connected' in r.json()['detail']
    assert not any(path.startswith('/rpc/') for _, path, _ in s.db.writes)


# ── change and skip ───────────────────────────────────────────────────

def test_an_edit_bumps_the_revision_recomputes_the_hash_and_drops_the_approval(s):
    p = seed(s)
    call(s, 'POST', '/approve', {'items': [item(p)]})
    approved = s.db.posts[p['id']]
    r = call(s, 'POST', '/slot/edit', {'items': [slot(approved)], 'caption': 'Two chairs open Friday.'})
    assert r.status_code == 200, r.text
    row = s.db.posts[p['id']]
    assert row['revision'] == 2 and row['status'] == 'draft' and row['caption'] == 'Two chairs open Friday.'
    assert row['publish_text'] == 'Two chairs open Friday.'
    assert row['approved_hash'] is row['approved_by'] is row['approved_at'] is row['approved_via'] is None
    assert row['content_hash'] == store.digest(row) != p['content_hash']
    assert row['run_at'] == p['run_at'] and row['expires_at'] == p['expires_at']


def test_a_new_time_gets_a_fresh_window_and_removing_the_picture_drops_instagram(s):
    p = seed(s, targets=(IG, FB), media={'artwork_ids': [ART]})
    when = '2026-10-20T16:00:00+00:00'
    r = call(s, 'POST', '/slot/edit', {'items': [slot(p)], 'run_at': when, 'remove_media': True})
    assert r.status_code == 200, r.text
    row = s.db.posts[p['id']]
    assert row['run_at'] == when and row['expires_at'] == '2026-10-20T22:00:00+00:00'
    assert row['media'] == {} and [t['platform'] for t in row['targets']] == ['facebook']
    assert r.json()['note'] == 'Instagram needs a picture, so this post leaves it out.'


def test_a_stale_edit_or_cancel_changes_nothing(s):
    p = seed(s)
    for path, body in (('/slot/edit', {'items': [{**slot(p), 'revision': 9}], 'caption': 'x'}),
                       ('/slot/cancel', {'items': [{**slot(p), 'revision': 9}]})):
        r = call(s, 'POST', path, body)
        assert r.status_code == 409 and r.json()['detail'] == bm.STALE
    sent = seed(s, status='submitted')
    assert call(s, 'POST', '/slot/cancel', {'items': [slot(sent)]}).status_code == 409
    assert s.db.writes == []


def test_an_edit_with_nothing_to_change_is_refused(s):
    p = seed(s)
    r = call(s, 'POST', '/slot/edit', {'items': [slot(p)]})
    assert r.status_code == 422 and s.db.writes == []


def test_cancel_skips_the_post(s):
    p = seed(s)
    r = call(s, 'POST', '/slot/cancel', {'items': [slot(p)]})
    assert r.status_code == 200 and r.json()['cancelled'] == 1
    assert s.db.posts[p['id']]['status'] == 'cancelled' and s.db.posts[p['id']]['revision'] == 2


def test_not_sent_turns_only_an_unconfirmed_delivery_into_a_failure(s):
    u = seed(s, status='uncertain', run_at=NOW - timedelta(hours=1))
    r = call(s, 'POST', f"/posts/{u['id']}/not-sent", {'revision': 1})
    assert r.status_code == 200
    row = s.db.posts[u['id']]
    assert row['status'] == 'failed' and row['revision'] == 2 and 'marked not sent' in row['error']
    d = seed(s)
    assert call(s, 'POST', f"/posts/{d['id']}/not-sent", {'revision': 1}).status_code == 409
    assert s.db.posts[d['id']]['status'] == 'draft'


# ── post now ──────────────────────────────────────────────────────────

def test_post_now_moves_the_reviewed_post_two_minutes_out_and_approves_it(s):
    p = seed(s)
    r = call(s, 'POST', '/post-now', {'items': [item(p)]})
    assert r.status_code == 200, r.text
    row = s.db.posts[p['id']]
    assert row['status'] == 'approved' and row['revision'] == 2 and row['approved_by'] == OWNER
    assert row['run_at'] == (NOW + bm.POST_NOW_LEAD).isoformat() and row['approved_hash'] == store.digest(row)
    assert r.json()['posting'] is True


def test_a_refused_post_now_puts_an_approved_post_back_as_it_was(s, monkeypatch):
    """Review of #1313: post-now moves the post, then approves it. If the
    approval is refused, the post must not quietly stop being approved."""
    p = seed(s)
    s.db.approve({'p_items': [item(p)], 'p_business_id': BIZ, 'p_actor': OWNER, 'p_via': 'owner'})
    before = copy.deepcopy(s.db.posts[p['id']])
    assert before['status'] == 'approved'

    def refuse(body):
        raise store.StoreConflict('A flyer is still being made; approve that post when it is ready')
    monkeypatch.setattr(s.db, 'approve', refuse)
    r = call(s, 'POST', '/post-now', {'items': [item(before)]})
    assert r.status_code == 409 and 'back as they were' in r.json()['detail']
    row = s.db.posts[p['id']]
    for key in ('run_at', 'expires_at', 'status', 'content_hash', 'approved_hash', 'approved_by', 'approved_via'):
        assert row[key] == before[key], key
    assert row['revision'] == before['revision'] + 2 and row['approved_hash'] == store.digest(row)


def test_a_post_now_whose_approval_cannot_be_confirmed_undoes_nothing(s, monkeypatch):
    p = seed(s)

    def down(body):
        raise store.StoreUnavailable('down')
    monkeypatch.setattr(s.db, 'approve', down)
    r = call(s, 'POST', '/post-now', {'items': [item(p)]})
    assert r.status_code == 503 and 'could not be confirmed' in r.json()['detail']
    assert s.db.posts[p['id']]['run_at'] == (NOW + bm.POST_NOW_LEAD).isoformat()


def test_a_new_post_now_is_saved_and_approved_in_one_step(s):
    r = call(s, 'POST', '/ideas', {'caption': 'Walk-ins welcome today.', 'post_now': True})
    assert r.status_code == 200, r.text
    row = s.db.posts[r.json()['post']['id']]
    assert row['status'] == 'approved' and row['run_at'] == (NOW + bm.POST_NOW_LEAD).isoformat()
    assert r.json()['posting'] is True


def test_a_retried_post_now_is_one_post_and_a_later_draft_is_not_sent_by_it(s):
    idea = str(uuid4())
    a = call(s, 'POST', '/ideas', {'id': idea, 'caption': 'Walk-ins welcome today.', 'post_now': True}).json()
    b = call(s, 'POST', '/ideas', {'id': idea, 'caption': 'Walk-ins welcome today.', 'post_now': True}).json()
    assert a['post']['id'] == b['post']['id'] and b['already_saved'] is True and len(s.db.posts) == 1
    assert s.db.posts[a['post']['id']]['status'] == 'approved'
    later = str(uuid4())
    call(s, 'POST', '/ideas', {'id': later, 'caption': 'Friday special.', 'run_at': '2026-10-09T16:00:00Z'})
    r = call(s, 'POST', '/ideas', {'id': later, 'caption': 'Friday special.', 'post_now': True})
    assert r.status_code == 409 and 'later time' in r.json()['detail']
    assert s.db.posts[bm.idea_post_id(BIZ, later)]['status'] == 'draft'


@pytest.mark.parametrize('setup,code,words', [
    (lambda s, m: m.setenv('MARKETING_DESK_PUBLISHING', 'off'), 409, 'not switched on yet'),
    (lambda s, m: m.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER), 403, 'switched on for this business'),
    (lambda s, m: m.delenv('POST_FOR_ME_API_KEY'), 503, "isn't set up"),
    (lambda s, m: s.db.desks.update({BIZ: {**bm.DESK_DEFAULTS, 'business_id': BIZ, 'paused': True}}), 409, 'paused'),
], ids=['sending off', 'pilot off', 'not configured', 'paused'])
def test_post_now_checks_run_before_any_write(s, monkeypatch, setup, code, words):
    p = seed(s)
    setup(s, monkeypatch)
    before = copy.deepcopy(s.db.posts)
    r = call(s, 'POST', '/post-now', {'items': [item(p)]})
    assert r.status_code == code and words in r.json()['detail']
    r = call(s, 'POST', '/ideas', {'caption': 'Walk-ins welcome today.', 'post_now': True})
    assert r.status_code == code and words in r.json()['detail']
    assert s.db.writes == [] and s.db.posts == before


@pytest.mark.parametrize('make,words', [
    (lambda s: seed(s, targets=(FB, GONE)), 'no longer connected'),
    (lambda s: seed(s, targets=(IG,)), 'Instagram needs a picture'),
    (lambda s: seed(s, caption='y' * 63300), 'Facebook allows'),
    (lambda s: seed(s, status='failed'), 'no longer waiting'),
    (lambda s: seed(s, design_status='designing'), 'flyer is still being made'),
], ids=['disconnected', 'instagram without a picture', 'caption rules', 'not waiting', 'designing'])
def test_post_now_refuses_a_post_that_cannot_go_and_moves_nothing(s, make, words):
    p = make(s)
    before = copy.deepcopy(s.db.posts)
    r = call(s, 'POST', '/post-now', {'items': [item(p)]})
    assert r.status_code in (409, 422) and words in r.json()['detail']
    assert s.db.writes == [] and s.db.posts == before


# ── settings ──────────────────────────────────────────────────────────

def test_settings_create_the_desk_and_change_only_what_was_sent(s):
    r = call(s, 'PUT', '/settings', {'post_hour': 9, 'connection_ids': [FB, IG],
                                     'landing_url': 'https://www.fadestreet.com/book', 'audience': '  Busy dads.  '})
    assert r.status_code == 200, r.text
    desk = s.db.desks[BIZ]
    assert desk['post_hour'] == 9 and desk['connection_ids'] == [FB, IG] and desk['audience'] == 'Busy dads.'
    assert desk['landing_url'] == 'https://www.fadestreet.com/book' and desk['paused'] is False
    r = call(s, 'PUT', '/settings', {'paused': True, 'landing_url': ''})
    desk = s.db.desks[BIZ]
    assert desk['paused'] is True and desk['landing_url'] is None and desk['post_hour'] == 9
    assert r.json()['desk']['exists'] is True
    assert call(s, 'GET', '/engine').json()['desk']['post_hour'] == 9


def test_an_empty_settings_call_still_makes_the_desk(s):
    r = call(s, 'PUT', '/settings', {})
    assert r.status_code == 200 and BIZ in s.db.desks and r.json()['desk']['exists'] is True


@pytest.mark.parametrize('body', [
    {'post_hour': 5}, {'post_hour': 22}, {'connection_ids': [THEIR_FB]}, {'connection_ids': [GONE]},
    {'landing_url': 'https://evil.example/'}, {'landing_url': 'http://fadestreet.com/'},
    {'landing_url': 'https://elsewhere.mysolutionist.app/'}, {'paused': None}, {'surprise': 1},
], ids=['hour 5', 'hour 22', 'foreign account', 'disconnected account', 'foreign host', 'http',
        'another business site', 'null paused', 'unknown field'])
def test_settings_validation(s, body):
    r = call(s, 'PUT', '/settings', body)
    assert r.status_code == 422, r.text
    assert s.db.writes == [] and s.db.desks == {}


def test_a_pending_custom_domain_is_not_a_landing_host(s):
    s.svc.sites[0]['site_config']['custom_domain_status'] = 'pending'
    assert call(s, 'PUT', '/settings', {'landing_url': 'https://fadestreet.com/'}).status_code == 422
    assert call(s, 'PUT', '/settings', {'landing_url': 'https://fade-street.mysolutionist.app/'}).status_code == 200


# ── a read that fails is a 503, never an empty desk ───────────────────

@pytest.mark.parametrize('where,fail', [
    ('store', '/marketing_posts'), ('store', '/marketing_desks'), ('store', '/marketing_runs'),
    ('service', '/social_connections'), ('service', '/practitioner_profiles'),
], ids=['posts', 'desk', 'runs', 'accounts', 'time zone'])
def test_the_desk_read_fails_closed(s, where, fail):
    s.svc.businesses[BIZ]['settings'] = {}
    seed(s)
    (s.db if where == 'store' else s.svc).fail = (fail,)
    r = call(s, 'GET', '/engine')
    assert r.status_code == 503 and r.json()['detail']


def test_the_calendar_read_fails_closed_for_a_chair_business(s):
    s.svc.businesses[BIZ].update(comp_tier='boss', settings={'availability': {'timezone': 'America/Chicago'},
                                                              'booking_page': {'published': True}})
    s.svc.fail = ('/custom_modules',)
    assert call(s, 'GET', '/engine').status_code == 503


@pytest.mark.parametrize('method,path,body,where,fail', [
    ('GET', '/ideas/next-slot', None, 'store', '/marketing_posts'),
    ('POST', '/ideas', {'caption': 'x'}, 'store', '/marketing_desks'),
    ('POST', '/ideas', {'caption': 'x'}, 'service', '/social_connections'),
    ('POST', '/ideas', {'caption': 'x', 'artwork_id': ART}, 'service', '/image_artworks'),
    ('POST', '/ideas', {'caption': 'x', 'landing_url': 'https://fadestreet.com/'}, 'service', '/business_sites'),
    ('POST', '/approve', 'ITEM', 'service', '/social_connections'),
    ('POST', '/approve', 'ITEM', 'store', '/marketing_posts'),
    ('POST', '/post-now', 'ITEM', 'service', '/social_connections'),
    ('PUT', '/settings', {'connection_ids': [FB]}, 'service', '/social_connections'),
    ('PUT', '/settings', {'paused': True}, 'service', '/businesses'),
], ids=['next-slot posts', 'ideas desk', 'ideas accounts', 'ideas picture', 'ideas site', 'approve accounts',
        'approve posts', 'post-now accounts', 'settings accounts', 'owner check'])
def test_a_failed_read_refuses_and_writes_nothing(s, method, path, body, where, fail):
    p = seed(s)
    if body == 'ITEM':
        body = {'items': [item(p)]}
    before = copy.deepcopy(s.db.posts)
    (s.db if where == 'store' else s.svc).fail = (fail,)
    r = call(s, method, path, body)
    assert r.status_code == 503, r.text
    assert s.db.writes == [] and s.db.posts == before


# ── how much Chief does ───────────────────────────────────────────────

def business(tier, kind='coach', calendar=False):
    settings = {'booking_page': {'published': True}} if calendar else {}
    return {'id': BIZ, 'owner_id': OWNER, 'type': kind, 'comp_tier': tier, 'settings': settings}


@pytest.mark.parametrize('tier,kind,calendar,level,upgrade', [
    ('starter', 'coach', False, 'suggest', {'feature': 'marketing_week', 'plan': 'professional', 'label': 'Professional'}),
    ('solo', 'barber', True, 'suggest', {'feature': 'marketing_week', 'plan': 'boss', 'label': 'Boss'}),
    ('booked', 'salon', True, 'suggest', {'feature': 'marketing_week', 'plan': 'boss', 'label': 'Boss'}),
    ('boss', 'barber', True, 'openings', {'feature': 'marketing_autopilot', 'plan': 'practice', 'label': 'Solutionist'}),
    ('boss', 'barber', False, 'week', {'feature': 'marketing_autopilot', 'plan': 'practice', 'label': 'Solutionist'}),
    ('professional', 'coach', False, 'week', {'feature': 'marketing_autopilot', 'plan': 'practice', 'label': 'Solutionist'}),
    ('professional', 'barber', True, 'openings', {'feature': 'marketing_autopilot', 'plan': 'practice', 'label': 'Solutionist'}),
    ('practice', 'coach', False, 'autopilot', None),
    ('practice', 'barber', True, 'autopilot', None),
    (None, 'coach', False, 'suggest', {'feature': 'marketing_week', 'plan': 'professional', 'label': 'Professional'}),
], ids=['starter', 'solo', 'booked', 'boss barber', 'boss without a calendar', 'professional',
        'professional barber', 'practice', 'practice barber', 'no plan'])
def test_level_and_upgrade_by_plan(s, tier, kind, calendar, level, upgrade):
    s.svc.modules = [{'business_id': BIZ, 'archetype': 'booking_calendar', 'is_active': True, 'id': str(uuid4())}]
    got = bm.level_for(business(tier, kind, calendar))
    assert got['level'] == level and got['upgrade'] == upgrade and got['plan'] == tier


def test_a_chair_business_needs_a_live_calendar_for_openings(s):
    row = business('boss', 'barber', calendar=True)
    assert bm.level_for(row)['level'] == 'week'                       # published page, no active calendar module
    s.svc.modules = [{'business_id': BIZ, 'archetype': 'booking_calendar', 'is_active': False, 'id': 'm1'}]
    assert bm.level_for(row)['level'] == 'week'
    s.svc.modules[0]['is_active'] = True
    assert bm.level_for(row)['level'] == 'openings'
    row['settings'] = {'booking_page': {'published': False}}
    assert bm.level_for(row)['level'] == 'week'


def test_the_level_ignores_billing_enforcement(s, monkeypatch):
    monkeypatch.setenv('BILLING_ENFORCE', 'off')
    assert bm.level_for(business('starter'))['level'] == 'suggest'    # has_feature would say yes to everything
    body = call(s, 'GET', '/engine').json()
    assert body['level'] == 'suggest' and body['upgrade']['plan'] == 'professional'


# ── wiring ────────────────────────────────────────────────────────────

def test_mounted_after_clip_posting_and_before_the_catch_all():
    src = (ROOT / 'kmj_intake_automation.py').read_text(encoding='utf-8')
    clip = src.index('app.include_router(clip_posting_router)')
    mine = src.index('app.include_router(business_marketing_router)')
    catch_all = src.index('app.include_router(public_site_router)')
    assert clip < mine < catch_all
    assert src.rfind('app.include_router(') == catch_all


def test_the_provider_is_the_connect_flow_provider():
    import social_connect_router
    assert bm.PROVIDER == social_connect_router.PROVIDER


def test_route_type_hints_resolve():
    import typing
    for route in bm.router.routes:
        typing.get_type_hints(route.endpoint)
