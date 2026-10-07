"""The marketing desk's sender and delivery watch (business_marketing_dispatch.py, B5).

The switch, sending through the one posting door, the publication id that
makes a retry harmless, the platform desk's error rules (before the hand-off
→ approved, refused → failed, after → uncertain), the checks at send time
(content, pause, accounts, clip approval), the build actor's scope, the
delivery watch's mapping, one push per problem, and the jobs' registration.

No network: PostgREST (the marketing_* tables and the claim RPC, the
service-role reads and writes), Post for Me, storage signing and push are
in-memory fakes. image_studio.storage_headers is the real one, so the build
actor's folder check is the code that runs in production.
"""
from __future__ import annotations

import asyncio
import ast
import copy
import fnmatch
import inspect
import pathlib
import sys
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote
from uuid import UUID, uuid4, uuid5

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

import business_marketing as bm
import business_marketing_dispatch as d
import business_marketing_store as store
import clip_posting
import image_studio as images
import media_library
import post_for_me as pfm
import push_notifications
import sb_clients
import social_publish_router as social

BIZ = '0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d'
OTHER = '9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b'
OWNER = '11111111-1111-4111-8111-111111111111'
OTHER_OWNER = '44444444-4444-4444-8444-444444444444'
IG = 'c0000000-0000-4000-8000-000000000001'
FB = 'c0000000-0000-4000-8000-000000000002'
THEIR_FB = 'c0000000-0000-4000-8000-000000000005'
ART = 'a0000000-0000-4000-8000-000000000001'
THEIR_ART = 'a0000000-0000-4000-8000-000000000003'
STRAY_ART = 'a0000000-0000-4000-8000-000000000004'      # this business's row, stored in another's folder
CLIP = 'd0000000-0000-4000-8000-000000000001'
COVER = 'e0000000-0000-4000-8000-000000000001'
NOW = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)
run = asyncio.run


# ── a small PostgREST ─────────────────────────────────────────────────

def _when(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(unquote(str(value)).replace('Z', '+00:00'))


def _norm(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return '' if value is None else str(value)


TIMES = {'run_at', 'expires_at', 'created_at', 'claimed_at', 'updated_at'}


def _value(row, column):
    if column == 'director->>clip_id':
        return row.get('clip_id')
    if column == 'action_payload->>dedup_key':
        return (row.get('action_payload') or {}).get('dedup_key')
    return row.get(column)


def matches(row, column, expr):
    value = _value(row, column)
    if expr == 'is.null':
        return value is None
    op, _, arg = expr.partition('.')
    if op == 'not' and arg.startswith('in.('):
        return _norm(value) not in arg[4:-1].split(',')
    if op == 'in':
        return _norm(value) in arg[1:-1].split(',')
    if op in ('gte', 'gt', 'lte', 'lt') and column in TIMES:
        if value is None:
            return False
        a, b = _when(value), _when(arg)
        return {'gte': a >= b, 'gt': a > b, 'lte': a <= b, 'lt': a < b}[op]
    if op == 'eq':
        return _norm(value) == unquote(arg)
    if op == 'like':
        return value is not None and fnmatch.fnmatchcase(str(value), arg)
    if op == 'neq':
        return _norm(value) != arg
    raise AssertionError(f'unexpected filter {column}={expr}')


def select(rows, path):
    query = path.split('?', 1)[1] if '?' in path else ''
    out, order, limit, offset = list(rows), None, None, 0
    for key, expr in (p.split('=', 1) for p in query.split('&') if '=' in p):
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
    for term in reversed((order or '').split(',') if order else []):
        column, _, direction = term.partition('.')
        if column in TIMES:
            out.sort(key=lambda r: _when(r.get(column)) if r.get(column) else datetime.min.replace(tzinfo=timezone.utc),
                     reverse=direction.startswith('desc'))
        else:
            out.sort(key=lambda r: str(r.get(column) or ''), reverse=direction.startswith('desc'))
    out = out[offset:]
    return out[:limit] if limit else out


class FakeStore:
    """marketing_desks, marketing_posts and marketing_claim_due."""

    def __init__(self, clock):
        self.clock = clock
        self.posts, self.desks = {}, {}
        self.calls, self.fail = [], ()
        self.pause_after_claim = None

    async def request(self, method, path, body=None):
        self.calls.append((method, path))
        query = path.split('?', 1)[1] if '?' in path else ''
        assert '+' not in query, f'unencoded + in a PostgREST query: {path}'
        if any(f in path for f in self.fail):
            raise store.StoreUnavailable('Marketing storage is unavailable. Please retry.')
        table = path.split('?', 1)[0]
        if table == '/rpc/marketing_claim_due':
            return self.claim(body['p_limit'])
        if table == '/marketing_desks':
            assert method == 'GET'
            return copy.deepcopy(select(self.desks.values(), path))
        if table == '/marketing_posts':
            if method == 'GET':
                return copy.deepcopy(select(self.posts.values(), path))
            assert method == 'PATCH'
            hit = select(self.posts.values(), path)
            for row in hit:
                row.update(copy.deepcopy(body))
                row['updated_at'] = self.clock().isoformat()        # the touch trigger
                assert row['status'] in store.POST_STATUSES
            return copy.deepcopy(hit)
        raise AssertionError(f'unexpected store call {method} {path}')

    def claim(self, limit):
        """The migration's marketing_claim_due, row for row."""
        now = self.clock()
        for p in self.posts.values():
            if p['status'] == 'dispatching' and _when(p['claimed_at']) < now - timedelta(minutes=10):
                p.update(status='uncertain', updated_at=now.isoformat(),
                         error='Sending was interrupted. Check the accounts before sending it again.')
            if p['status'] == 'approved' and _when(p['expires_at']) <= now:
                p.update(status='failed', updated_at=now.isoformat(),
                         error='Its time to post passed before it went out. Edit it and approve a new time.')
        due = [p for p in self.posts.values()
               if p['status'] == 'approved' and _when(p['run_at']) <= now < _when(p['expires_at'])
               and p['approved_hash'] == p['content_hash'] and p['approved_by'] and p['approved_via']
               and p['business_id'] in self.desks and not self.desks[p['business_id']]['paused']]
        due.sort(key=lambda p: (_when(p['run_at']), p['id']))
        for p in due[:limit]:
            p.update(status='dispatching', claimed_at=now.isoformat(), updated_at=now.isoformat())
        if self.pause_after_claim:
            self.desks[self.pause_after_claim]['paused'] = True
        return copy.deepcopy(due[:limit])


def connection(cid, platform, *, biz=BIZ, status='connected'):
    return {'id': cid, 'business_id': biz, 'provider': 'post_for_me', 'platform': platform, 'status': status,
            'username': f'fade.{platform}', 'provider_account_id': f'spc_{platform}_{cid[-2:]}'}


def artwork(aid, biz=BIZ, *, path=None, clip=None, size='1024x1536'):
    return {'id': aid, 'business_id': biz, 'status': 'ready', 'size': size,
            'storage_path': path or f'{biz}/{aid}.png', 'prompt': 'A fresh fade, Friday', 'model': 'gpt-image',
            'created_at': '2026-10-06T12:00:00Z', 'goal': None, 'clip_id': clip}


def clip_row(**over):
    row = {'id': CLIP, 'business_id': BIZ, 'kind': 'clip', 'status': 'ready', 'name': 'Sixty seconds',
           'source_id': 'src-1', 'sha256': 'b' * 64, 'source_removed_at': None,
           'configuration': {'caption': 'A cut in sixty seconds.'}}
    row.update(over)
    row.setdefault('approval', {'fingerprint': media_library.fingerprint(row)})
    return row


class FakeService:
    """The service-role tables the send touches: businesses, accounts,
    pictures, clips, the shared door's publications and Today items."""

    def __init__(self, clock):
        self.clock = clock
        self.businesses = [{'id': BIZ, 'owner_id': OWNER}, {'id': OTHER, 'owner_id': OTHER_OWNER}]
        self.connections = [connection(IG, 'instagram'), connection(FB, 'facebook'),
                            connection(THEIR_FB, 'facebook', biz=OTHER)]
        self.artworks = [artwork(ART), artwork(THEIR_ART, OTHER), artwork(STRAY_ART, path=f'{OTHER}/{STRAY_ART}.png'),
                         artwork(COVER, clip=CLIP, size='1088x1920')]
        self.clips = [clip_row()]
        self.pubs, self.notes = [], []
        self.fail = ()
        self.patch_threads = []
        self.receipt_fails = False       # the provider_post_id write after a hand-off does not land
        self.receipt_writes = 0

    def get(self, path):
        if any(f in path for f in self.fail):
            return None
        table = path.split('?', 1)[0]
        rows = {'/businesses': self.businesses, '/social_connections': self.connections,
                '/image_artworks': self.artworks, '/media_assets': self.clips,
                '/social_publications': self.pubs, '/chief_notifications': self.notes}.get(table)
        if rows is None:
            raise AssertionError(f'unexpected read {path}')
        return copy.deepcopy(select(rows, path))

    def post(self, path, body, prefer='return=representation'):
        if any(f in path for f in self.fail):
            return None
        if path == '/social_publications':
            if any(r['id'] == body.get('id') for r in self.pubs):
                return None                      # the primary key is taken: PostgREST answers 409
            row = {'id': body.get('id') or str(uuid4()), 'created_at': self.clock().isoformat(),
                   'provider_post_id': None, 'results': [], **body}
            self.pubs.append(row)
            return [copy.deepcopy(row)]
        if path == '/chief_notifications':
            row = {'id': str(uuid4()), 'created_at': self.clock().isoformat(), **copy.deepcopy(body)}
            self.notes.append(row)
            return [copy.deepcopy(row)]
        raise AssertionError(f'unexpected write {path}')

    def patch(self, path, body):
        self.patch_threads.append(threading.get_ident())
        assert path.startswith('/social_publications?')
        if 'provider_post_id' in body:
            self.receipt_writes += 1
            if self.receipt_fails:
                return None
        hit = select(self.pubs, path)
        for row in hit:
            row.update(copy.deepcopy(body))
        return copy.deepcopy(hit)


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', f'{BIZ},{OTHER}')
    monkeypatch.setenv('MARKETING_DESK_PUBLISHING', 'on')
    monkeypatch.setenv('SUPABASE_URL', 'https://sb.test')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-test')
    state = SimpleNamespace(now=NOW, sent=[], jpegs=[], signed=[], pushes=[], results={},
                            refuse=False, explode=False)
    clock = lambda: state.now                                          # noqa: E731
    state.db, state.svc = FakeStore(clock), FakeService(clock)
    monkeypatch.setattr(store, 'request', state.db.request)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', state.svc.get)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', state.svc.post)
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', state.svc.patch)
    monkeypatch.setattr(d, 'now', clock)
    monkeypatch.setattr(social, '_now', clock)

    real_headers = images.storage_headers

    async def jpeg(client, business_id, row):
        # The real storage check, under whatever build actor is bound now.
        real_headers(row['storage_path'])
        state.jpegs.append((business_id, row['id'], images.build_actor.get()))
        return f'https://sb.test/storage/v1/object/public/business-assets/{business_id}/published-artwork/{row["id"]}.jpg'
    monkeypatch.setattr(images, 'delivery_jpeg', jpeg)

    def sign(bucket, path, ttl=3600, download_as=None):
        state.signed.append(path)
        return f'https://sb.test/storage/v1/object/sign/{bucket}/{path}?token=t{len(state.signed)}'
    monkeypatch.setattr(clip_posting.storage_links, 'signed_url_sync', sign)
    monkeypatch.setattr(clip_posting.media_library, 'audit', lambda *a, **k: None)

    async def create_post(**kw):
        state.sent.append(kw)
        if state.refuse:
            raise pfm.PostForMeError('Post for Me answered 400.', 400)
        if state.explode:
            raise RuntimeError('the connection dropped mid-answer')
        return {'id': f'sp_{len(state.sent)}', 'status': 'processing'}
    monkeypatch.setattr(pfm, 'create_post', create_post)

    async def post_results(post_id):
        return copy.deepcopy(state.results.get(post_id, []))
    monkeypatch.setattr(pfm, 'post_results', post_results)

    def send_to_user(user_id, **kw):
        state.pushes.append((user_id, kw))
        return 1
    monkeypatch.setattr(push_notifications, 'send_to_user', send_to_user)

    state.db.desks[BIZ] = {'business_id': BIZ, 'paused': False, 'connection_ids': [], 'post_hour': 11}
    state.db.desks[OTHER] = {'business_id': OTHER, 'paused': False, 'connection_ids': [], 'post_hour': 11}
    assert images.build_actor.get() is None
    yield state
    assert images.build_actor.get() is None


def seed(s, *, biz=BIZ, targets=(IG, FB), media=None, caption='Fresh fades all week.', run_at=None, **over):
    """An approved post, as the desk saves and approves it."""
    pid = str(uuid4())
    by_id = {c['id']: c for c in s.svc.connections}
    run_at = run_at or s.now - timedelta(minutes=1)
    row = bm.new_post(biz, pid, caption=caption, media=media if media is not None else {'artwork_ids': [ART]},
                      targets=[bm._target(by_id[t]) for t in targets], run_at=run_at,
                      expires_at=run_at + bm.WINDOW, landing=None)
    row.update(status='approved', approved_hash=row['content_hash'], approved_by=OWNER,
               approved_at=(s.now - timedelta(hours=1)).isoformat(), approved_via='owner', publication_id=None,
               external_urls=[], error=None, claimed_at=None, checked_at=None, run_id=None, play_id=None,
               opening=None, created_at=s.now.isoformat(), updated_at=s.now.isoformat())
    row.update(over)
    s.db.posts[pid] = row
    return pid


def post(s, pid):
    return s.db.posts[pid]


def clip_media():
    return {'clip_id': CLIP, 'clip_fingerprint': media_library.fingerprint(clip_row()), 'covers': {'story': COVER}}


def expected_id(pid, revision=1):
    return str(uuid5(UUID(pid), f'rev:{revision}'))


# ── the switch ────────────────────────────────────────────────────────

@pytest.mark.parametrize('value', [None, 'off', '', 'yes'])
def test_while_the_switch_is_off_nothing_is_claimed_or_checked(s, monkeypatch, value):
    if value is None:
        monkeypatch.delenv('MARKETING_DESK_PUBLISHING')
    else:
        monkeypatch.setenv('MARKETING_DESK_PUBLISHING', value)
    pid = seed(s)
    assert run(d.due_tick()) == {'skipped': 'off'}
    assert run(d.delivery_tick()) == {'skipped': 'off'}
    assert s.db.calls == [] and s.sent == [] and s.svc.notes == [] and s.pushes == []
    assert post(s, pid)['status'] == 'approved'


def test_without_the_posting_key_nothing_is_claimed(s, monkeypatch):
    """A server without Post for Me must not fail every business's posts as
    'not switched on for this business'."""
    monkeypatch.delenv('POST_FOR_ME_API_KEY')
    pid = seed(s)
    assert run(d.due_tick()) == {'skipped': 'not configured'}
    assert s.db.calls == [] and post(s, pid)['status'] == 'approved'


# ── sending ───────────────────────────────────────────────────────────

def test_an_approved_picture_post_goes_out_once_through_the_shared_door(s):
    pid = seed(s)
    out = run(d.due_tick())
    assert out == {'claimed': 1, 'submitted': 1}
    row = post(s, pid)
    assert row['status'] == 'submitted' and row['error'] is None
    assert row['publication_id'] == expected_id(pid)
    [sent] = s.sent
    assert sent['external_id'] == expected_id(pid)          # our row id goes to Post for Me
    assert sent['caption'] == row['publish_text'] and sent['scheduled_at'] is None
    assert sent['account_ids'] == ['spc_instagram_01', 'spc_facebook_02']
    assert sent['media_urls'] == [f'https://sb.test/storage/v1/object/public/business-assets/{BIZ}/published-artwork/{ART}.jpg']
    [pub] = s.svc.pubs
    assert pub['id'] == expected_id(pid) and pub['approved_hash'] == row['approved_hash'] and pub['approved_by'] == OWNER
    assert s.jpegs == [(BIZ, ART, {'business_id': BIZ, 'user_id': OWNER})]
    assert run(d.due_tick()) == {'claimed': 0}
    assert len(s.sent) == 1


def test_words_only_go_out_without_a_picture(s):
    pid = seed(s, targets=(FB,), media={})
    run(d.due_tick())
    assert post(s, pid)['status'] == 'submitted'
    assert s.sent[0]['media_urls'] == [] and s.jpegs == []


def test_a_retry_reuses_the_same_publication_id_and_never_posts_twice(s):
    pid = seed(s)
    s.svc.fail = ('created_at=gte',)                 # the daily-cap read fails inside the door
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'approved' and row['claimed_at'] is None and row['error'] == d.RETRY
    assert s.sent == []
    s.svc.fail = ()
    run(d.due_tick())
    assert post(s, pid)['status'] == 'submitted' and [x['external_id'] for x in s.sent] == [expected_id(pid)]
    # The same approved version claimed again (its result lost, say): the door
    # finds the publication by its id and does not hand it over a second time.
    post(s, pid).update(status='approved', claimed_at=None, publication_id=None)
    run(d.due_tick())
    assert len(s.sent) == 1 and len(s.svc.pubs) == 1
    assert post(s, pid)['status'] == 'submitted' and post(s, pid)['publication_id'] == expected_id(pid)


def test_an_edited_post_is_a_new_send(s):
    """A new revision is a new publication id: after a fix and a new approval
    it goes out, instead of being answered with the old failure."""
    a = seed(s)
    b = seed(s, revision=2)
    assert d.publication_id_for(post(s, a)) == expected_id(a)
    assert d.publication_id_for(post(s, b)) == expected_id(b, 2) != expected_id(b, 1)


def test_a_refusal_from_the_posting_service_fails_in_plain_words(s):
    pid = seed(s)
    s.refuse = True
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'failed' and row['error'] == d.REFUSED
    assert s.svc.pubs[0]['status'] == 'failed'               # the door recorded it as failed, never as sent
    s.refuse = False
    assert run(d.due_tick()) == {'claimed': 0}
    assert len(s.sent) == 1
    # Even if that same version were claimed again, the answer is the same refusal.
    row.update(status='approved', claimed_at=None)
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and len(s.sent) == 1


def test_a_storage_blip_before_the_hand_off_puts_it_back_to_approved(s):
    pid = seed(s)
    s.db.fail = ('/marketing_desks',)
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'approved' and row['claimed_at'] is None and row['error'] == d.RETRY
    assert s.sent == [] and s.jpegs == []
    s.db.fail = ()
    run(d.due_tick())
    assert post(s, pid)['status'] == 'submitted' and len(s.sent) == 1


def test_a_failed_owner_read_holds_and_a_missing_owner_refuses(s):
    pid = seed(s)
    s.svc.fail = ('/businesses',)
    run(d.due_tick())
    assert post(s, pid)['status'] == 'approved' and s.sent == []
    s.svc.fail = ()
    s.svc.businesses[0]['owner_id'] = None
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and post(s, pid)['error'] == d.NO_OWNER and s.sent == []


def test_an_error_after_the_hand_off_began_is_uncertain_and_never_resent(s):
    pid = seed(s)
    s.explode = True
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'uncertain' and row['error'] == d.INTERRUPTED
    assert row['publication_id'] == expected_id(pid)
    s.explode = False
    run(d.due_tick())
    run(d.delivery_tick())
    assert len(s.sent) == 1 and post(s, pid)['status'] == 'uncertain'


def test_the_daily_cap_fails_the_post_in_plain_words(s):
    for _ in range(social.POSTS_PER_DAY_CAP):
        s.svc.pubs.append({'id': str(uuid4()), 'business_id': BIZ, 'status': 'posted',
                           'created_at': (s.now - timedelta(hours=2)).isoformat()})
    pid = seed(s)
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and post(s, pid)['error'] == d.CAPPED and s.sent == []


def test_a_window_that_closed_after_the_claim_fails(s):
    pid = seed(s, run_at=NOW - timedelta(hours=5, minutes=59, seconds=50))
    claimed = run(store.claim_due(5))
    s.now = NOW + timedelta(seconds=30)
    run(d.dispatch(claimed[0]))
    assert post(s, pid)['status'] == 'failed' and post(s, pid)['error'] == d.EXPIRED and s.sent == []


# ── checks at send time ───────────────────────────────────────────────

def test_a_paused_desk_sends_nothing(s):
    pid = seed(s)
    s.db.desks[BIZ]['paused'] = True
    assert run(d.due_tick()) == {'claimed': 0}
    assert post(s, pid)['status'] == 'approved' and s.sent == []
    # Paused in the instant after the claim: it goes back to waiting, quietly,
    # as the desk says ("will not go out until you resume it").
    s.db.desks[BIZ]['paused'] = False
    s.db.pause_after_claim = BIZ
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'approved' and row['claimed_at'] is None and row['error'] is None
    assert s.sent == [] and s.jpegs == []


def test_a_disconnected_account_fails_in_plain_words(s):
    pid = seed(s)
    next(c for c in s.svc.connections if c['id'] == FB)['status'] = 'disconnected'
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'failed'
    assert row['error'].startswith('Facebook (@fade.facebook) is no longer connected to this business, so nothing went out.')
    assert s.sent == [] and s.jpegs == []


def test_a_failed_account_read_is_not_a_disconnected_account(s):
    pid = seed(s)
    s.svc.fail = ('/social_connections',)
    run(d.due_tick())
    assert post(s, pid)['status'] == 'approved' and post(s, pid)['error'] == d.RETRY and s.sent == []


def test_an_account_that_changed_since_approval_is_not_posted_to(s):
    pid = seed(s)
    next(c for c in s.svc.connections if c['id'] == FB)['provider_account_id'] = 'spc_someone_else'
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and 'changed since this post was approved' in post(s, pid)['error']
    assert s.sent == []


def test_another_business_account_is_never_posted_to(s):
    """A post can only name accounts connected to its own business."""
    pid = seed(s)
    post(s, pid)['targets'] = [bm._target(next(c for c in s.svc.connections if c['id'] == THEIR_FB))]
    post(s, pid)['content_hash'] = post(s, pid)['approved_hash'] = store.digest(post(s, pid))
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and 'no longer connected to this business' in post(s, pid)['error']
    assert s.sent == []


def test_a_post_whose_content_changed_after_approval_is_not_sent(s):
    edited = seed(s)
    post(s, edited)['content_hash'] = 'f' * 64                # edited: the hash moved, the approval did not
    tampered = seed(s)
    post(s, tampered)['caption'] = 'Something nobody approved.'   # words changed without a new hash
    run(d.due_tick())
    assert post(s, edited)['status'] == 'approved'            # never claimed
    assert post(s, tampered)['status'] == 'failed' and post(s, tampered)['error'] == d.CHANGED
    assert s.sent == []


def test_a_business_whose_pilot_is_off_is_held_not_failed(s, monkeypatch):
    """A business can be switched back on: its posts wait, saying why, and
    nobody is pushed."""
    pid = seed(s)
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    out = run(d.due_tick())
    assert out == {'claimed': 1, 'held': 1}
    row = post(s, pid)
    assert row['status'] == 'approved' and row['claimed_at'] is None and row['error'] == d.PILOT_HELD
    assert s.sent == [] and s.jpegs == []
    run(d.delivery_tick())
    assert s.svc.notes == [] and s.pushes == []
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', f'{BIZ},{OTHER}')
    run(d.due_tick())
    assert post(s, pid)['status'] == 'submitted' and post(s, pid)['error'] is None and len(s.sent) == 1


def test_a_pilot_switched_off_in_the_instant_before_sending_holds_too(s, monkeypatch):
    pid = seed(s)
    claimed = run(store.claim_due(5))
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    run(d.dispatch(claimed[0]))
    assert post(s, pid)['status'] == 'approved' and post(s, pid)['error'] == d.PILOT_HELD and s.sent == []
    # ...and if it flips inside the shared door, the door's own refusal holds as well.
    assert d._after_handoff(d.HTTPException(403, d._PILOT_OFF)) == {
        'status': 'approved', 'claimed_at': None, 'error': d.PILOT_HELD}
    assert d._PILOT_OFF in inspect.getsource(social._require_pilot)


def test_held_posts_never_crowd_out_other_businesses(s, monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    held = [seed(s, run_at=NOW - timedelta(minutes=30 - i)) for i in range(6)]       # older, so claimed first
    theirs = seed(s, biz=OTHER, targets=(THEIR_FB,), media={'artwork_ids': [THEIR_ART]})
    out = run(d.due_tick())
    assert post(s, theirs)['status'] == 'submitted' and len(s.sent) == 1
    assert out['held'] == 6 and out['submitted'] == 1
    assert all(post(s, p)['status'] == 'approved' and post(s, p)['error'] == d.PILOT_HELD for p in held)


def test_an_empty_pilot_list_claims_nothing(s, monkeypatch):
    """A configuration slip on the worker never becomes failed posts."""
    for value in ('', ' , '):
        monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', value)
        pid = seed(s)
        assert run(d.due_tick()) == {'skipped': 'not configured'}
        assert s.db.calls == [] and post(s, pid)['status'] == 'approved' and s.sent == []


# ── clips ─────────────────────────────────────────────────────────────

def test_an_approved_clip_goes_out_with_its_cover(s):
    pid = seed(s, media=clip_media())
    run(d.due_tick())
    row = post(s, pid)
    rid = uuid5(UUID(pid), 'rev:1')
    assert row['status'] == 'submitted'
    assert row['publication_id'] == d.publication_id_for(row) == str(uuid5(UUID(CLIP), f'post:{rid}'))
    [sent] = s.sent
    assert sent['external_id'] == row['publication_id']
    assert sent['platform_configurations']['instagram']['placement'] == 'reels'
    assert s.jpegs == [(BIZ, COVER, {'business_id': BIZ, 'user_id': OWNER})]
    assert s.signed == [f'{BIZ}/{CLIP}.mp4']


def test_a_clip_changed_after_approval_fails_and_nothing_is_signed_or_sent(s):
    pid = seed(s, media=clip_media())
    s.svc.clips[0]['configuration'] = {'caption': 'Recut.'}       # the clip changed; its approval did not
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'failed' and row['error'].startswith('This clip changed after the post was approved')
    assert s.sent == [] and s.signed == [] and s.jpegs == []


def test_a_clip_approved_again_at_another_version_is_not_the_one_the_post_approved(s):
    pid = seed(s, media=clip_media())
    changed = clip_row(configuration={'caption': 'Recut.'})
    s.svc.clips[0] = changed                                      # re-approved as it is now
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and s.sent == []


def test_a_clip_read_that_fails_holds(s):
    pid = seed(s, media=clip_media())
    s.svc.fail = ('/media_assets',)
    run(d.due_tick())
    assert post(s, pid)['status'] == 'approved' and s.sent == []


# ── the build actor ───────────────────────────────────────────────────

def test_the_build_actor_is_bound_per_post_and_reset_after_each(s, monkeypatch):
    seen = []
    real_owner = d._owner_of

    def owner_of(business_id):
        seen.append(images.build_actor.get())                     # before this post binds its own
        return real_owner(business_id)
    monkeypatch.setattr(d, '_owner_of', owner_of)
    mine = seed(s, run_at=NOW - timedelta(minutes=2))
    theirs = seed(s, biz=OTHER, targets=(THEIR_FB,), media={'artwork_ids': [THEIR_ART]})
    run(d.due_tick())
    assert post(s, mine)['status'] == post(s, theirs)['status'] == 'submitted'
    assert seen == [None, None]
    assert s.jpegs == [(BIZ, ART, {'business_id': BIZ, 'user_id': OWNER}),
                       (OTHER, THEIR_ART, {'business_id': OTHER, 'user_id': OTHER_OWNER})]


def test_another_business_artwork_is_refused(s):
    pid = seed(s, media={'artwork_ids': [THEIR_ART]})
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'failed'
    assert row['error'] == "That design isn't in this business's Media Library. Nothing went out."
    assert s.sent == [] and s.jpegs == []


def test_storage_outside_this_business_folder_is_refused_under_the_actor(s):
    """The real storage_headers: with the actor bound to this business, a
    path in another business's folder is refused before anything is fetched."""
    pid = seed(s, media={'artwork_ids': [STRAY_ART]})
    run(d.due_tick())
    assert post(s, pid)['status'] == 'failed' and post(s, pid)['error'] == d.PICTURE_GONE
    assert s.sent == [] and s.jpegs == []


def test_one_bad_post_never_stops_the_batch(s, monkeypatch):
    first = seed(s, run_at=NOW - timedelta(minutes=3))
    second = seed(s, run_at=NOW - timedelta(minutes=2))
    real = d.dispatch

    async def dispatch(row):
        if row['id'] == first:
            raise RuntimeError('unexpected')
        return await real(row)
    monkeypatch.setattr(d, 'dispatch', dispatch)
    out = run(d.due_tick())
    assert out['error'] == 1 and out['submitted'] == 1
    assert post(s, second)['status'] == 'submitted'


# ── the delivery watch ────────────────────────────────────────────────

def ok(account, url=None):
    return {'social_account_id': account, 'success': True, 'url': url or f'https://social.test/{account}', 'error': None}


def bad(account):
    return {'social_account_id': account, 'success': False, 'url': None, 'error': 'Media aspect ratio not supported'}


def test_delivery_maps_published_partly_published_and_failed(s):
    pids = [seed(s, run_at=NOW - timedelta(minutes=5 - i)) for i in range(3)]
    run(d.due_tick())
    assert [post(s, p)['status'] for p in pids] == ['submitted'] * 3
    s.results = {'sp_1': [ok('spc_instagram_01'), ok('spc_facebook_02')],
                 'sp_2': [ok('spc_instagram_01'), bad('spc_facebook_02')],
                 'sp_3': [bad('spc_instagram_01'), bad('spc_facebook_02')]}
    s.now = NOW + timedelta(minutes=5)
    out = run(d.delivery_tick())
    assert out['published'] == out['partly_published'] == out['failed'] == 1
    done, partly, failed = (post(s, p) for p in pids)
    assert done['status'] == 'published' and done['error'] is None
    assert [u['url'] for u in done['external_urls']] == ['https://social.test/spc_instagram_01',
                                                        'https://social.test/spc_facebook_02']
    assert done['checked_at'] == s.now.isoformat()
    assert partly['status'] == 'partly_published'
    assert partly['error'] == 'It went out on Instagram, but Facebook did not take it. Open Build, Social Media to see why.'
    assert [u['label'] for u in partly['external_urls']] == ['Instagram']
    assert failed['status'] == 'failed' and failed['external_urls'] == []
    assert failed['error'].startswith("Instagram and Facebook did not take it, so it didn't go out.")
    assert 'aspect ratio' not in failed['error']             # the network's own words stay on the publication
    assert [p['status'] for p in s.svc.pubs] == ['posted', 'partly_posted', 'failed']


def test_a_post_still_in_flight_after_two_hours_is_uncertain(s):
    pid = seed(s)
    run(d.due_tick())
    s.now = NOW + timedelta(minutes=30)
    run(d.delivery_tick())
    assert post(s, pid)['status'] == 'submitted' and post(s, pid)['checked_at'] is None
    s.now = NOW + timedelta(hours=2, minutes=1)
    run(d.delivery_tick())
    assert post(s, pid)['status'] == 'uncertain' and post(s, pid)['error'] == d.STILL_GOING
    # The answer comes in late: the watch settles it.
    s.results = {'sp_1': [ok('spc_instagram_01'), ok('spc_facebook_02')]}
    s.now = NOW + timedelta(hours=3)
    run(d.delivery_tick())
    assert post(s, pid)['status'] == 'published'


def test_an_unrecorded_send_is_found_by_its_publication_id(s):
    """The send went out but its result could not be written: the claim
    RPC makes it uncertain, and the watch finds the publication by the id
    the post's revision gives it."""
    pid = seed(s)
    s.db.fail = ('status=eq.dispatching',)
    run(d.due_tick())
    assert post(s, pid)['status'] == 'dispatching' and len(s.sent) == 1
    s.db.fail = ()
    s.now = NOW + timedelta(minutes=11)
    run(d.due_tick())                                         # the RPC's sweep: dispatching -> uncertain
    assert post(s, pid)['status'] == 'uncertain' and len(s.sent) == 1
    s.results = {'sp_1': [ok('spc_instagram_01'), ok('spc_facebook_02')]}
    run(d.delivery_tick())
    assert post(s, pid)['status'] == 'published' and post(s, pid)['publication_id'] == expected_id(pid)


def test_the_refresh_writes_off_the_event_loop(s):
    pid = seed(s)
    run(d.due_tick())
    s.results = {'sp_1': [ok('spc_instagram_01'), ok('spc_facebook_02')]}
    loop_thread = {}

    async def go():
        loop_thread['id'] = threading.get_ident()
        return await d.delivery_tick()
    run(go())
    assert post(s, pid)['status'] == 'published'
    assert s.svc.patch_threads and loop_thread['id'] not in s.svc.patch_threads


# ── telling the owner ─────────────────────────────────────────────────

def test_exactly_one_push_and_one_today_item_per_problem(s):
    pids = [seed(s, run_at=NOW - timedelta(minutes=5 - i)) for i in range(3)]
    expired = seed(s, run_at=NOW - timedelta(hours=7))        # the claim RPC fails it: its window closed
    run(d.due_tick())
    s.results = {'sp_1': [ok('spc_instagram_01'), ok('spc_facebook_02')],
                 'sp_2': [ok('spc_instagram_01'), bad('spc_facebook_02')],
                 'sp_3': [bad('spc_instagram_01'), bad('spc_facebook_02')]}
    for minutes in (5, 10, 15):
        s.now = NOW + timedelta(minutes=minutes)
        run(d.delivery_tick())
    published, partly, failed = pids
    told = {n['action_payload']['post_id']: n for n in s.svc.notes}
    assert set(told) == {partly, failed, expired}                 # never for a success
    assert len(s.svc.notes) == 3 and len(s.pushes) == 3
    assert {u for u, _ in s.pushes} == {OWNER}
    assert all(kw['nav'] == 'grow:marketing' for _, kw in s.pushes)
    note = told[failed]
    assert note['type'] == 'reminder' and note['priority'] == 'high'
    assert note['title'] == "A post didn't go out on Instagram and Facebook"
    assert note['action_payload'] == {'type': 'navigate', 'tab': 'grow', 'sub': 'marketing', 'post_id': failed,
                                      'dedup_key': f'marketing_post:{failed}:r1:failed'}
    assert told[partly]['title'] == 'A post went out on only some of Instagram and Facebook'
    assert told[expired]['body'] == 'Its time to post passed before it went out. Edit it and approve a new time.'


def test_an_uncertain_post_is_told_once(s):
    pid = seed(s)
    s.explode = True
    run(d.due_tick())
    for minutes in (5, 10):
        s.now = NOW + timedelta(minutes=minutes)
        run(d.delivery_tick())
    assert [n['action_payload']['post_id'] for n in s.svc.notes] == [pid]
    assert s.svc.notes[0]['title'] == 'A post may not have gone out on Instagram and Facebook'
    assert len(s.pushes) == 1


def test_the_owner_marking_it_not_sent_is_not_announced_back(s):
    pid = seed(s, status='failed', error=bm.NOT_SENT_NOTE, revision=2)
    run(d.delivery_tick())
    assert s.svc.notes == [] and s.pushes == []
    assert post(s, pid)['status'] == 'failed'


def test_a_failure_after_a_fix_is_told_again(s):
    pid = seed(s)
    s.refuse = True
    run(d.due_tick())
    run(d.delivery_tick())
    # Fixed and approved again (a new revision), and it fails again.
    row = post(s, pid)
    row.update(revision=2, status='approved', claimed_at=None, error=None)
    run(d.due_tick())
    run(d.delivery_tick())
    assert [n['action_payload']['dedup_key'] for n in s.svc.notes] == [
        f'marketing_post:{pid}:r1:failed', f'marketing_post:{pid}:r2:failed']
    assert len(s.pushes) == 2


def test_a_failed_dedup_read_says_nothing_until_it_can_check(s):
    pid = seed(s)
    s.refuse = True
    run(d.due_tick())
    s.svc.fail = ('/chief_notifications',)
    run(d.delivery_tick())
    assert s.svc.notes == [] and s.pushes == []
    s.svc.fail = ()
    run(d.delivery_tick())
    run(d.delivery_tick())
    assert len(s.svc.notes) == 1 and len(s.pushes) == 1 and post(s, pid)['status'] == 'failed'


# ── the shared door's words this module reads ─────────────────────────

def test_the_ambiguous_refusals_are_still_the_doors_own_words():
    """If these drift, a blip inside the door would fail a post for good."""
    assert "One of those accounts isn't connected to this business." in inspect.getsource(social._targets)
    assert "'Business not found.'" in inspect.getsource(clip_posting._require_owner)
    assert 'REFUSED' in inspect.getsource(social.send_post)


# ── the jobs ──────────────────────────────────────────────────────────

APP = (ROOT / 'kmj_intake_automation.py').read_text(encoding='utf-8')


def test_the_jobs_are_registered_leader_gated_and_only_started_where_jobs_run():
    startup = APP.index('async def startup')
    started = APP.index('if runs_scheduled_jobs():\n        scheduler.start()')
    for job, minutes in (('business_marketing_due', 1), ('business_marketing_delivery', 5)):
        at = APP.index(f'g("{job}", _business_marketing.')
        assert startup < at < started, f'{job} must be registered in startup, before the gated start'
        call = APP[at:APP.index('\n', APP.index(f'id="{job}"'))]
        assert f'minutes={minutes}' in call and f'id="{job}"' in call and 'max_instances=1' in call
    tree = ast.parse(APP)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    ns: dict = {'os': __import__('os')}
    exec(compile(ast.Module(body=[fns['process_role'], fns['runs_scheduled_jobs']], type_ignores=[]),
                 '<roles>', 'exec'), ns)
    import os
    before = os.environ.get('PROCESS_ROLE')
    try:
        for role, runs in (('web', False), ('worker', True), ('all', True)):
            os.environ['PROCESS_ROLE'] = role
            assert ns['runs_scheduled_jobs']() is runs
    finally:
        if before is None:
            os.environ.pop('PROCESS_ROLE', None)
        else:
            os.environ['PROCESS_ROLE'] = before


def test_the_ticks_take_no_arguments_from_the_scheduler():
    """scheduler_lock.gate calls fn() with nothing."""
    for fn in (d.due_tick, d.delivery_tick):
        params = inspect.signature(fn).parameters.values()
        assert all(p.default is not inspect.Parameter.empty for p in params)
        assert inspect.iscoroutinefunction(fn)


# ── review of #1315: unconfirmed hand-offs ────────────────────────────

def test_an_earlier_record_without_a_receipt_is_uncertain_not_submitted(s):
    """The door answers (row, False) for a publication this id already has.
    Without the posting service's id on it, nothing confirms it went out."""
    pid = seed(s)
    s.svc.pubs.append({'id': expected_id(pid), 'business_id': BIZ, 'status': 'posting', 'provider_post_id': None,
                       'results': [], 'targets': [], 'created_at': s.now.isoformat()})
    run(d.due_tick())
    row = post(s, pid)
    assert row['status'] == 'uncertain' and row['error'] == d.UNCONFIRMED
    assert row['publication_id'] == expected_id(pid) and s.sent == []


def test_a_receipt_that_could_not_be_written_is_uncertain(s):
    pid = seed(s)
    s.svc.receipt_fails = True
    run(d.due_tick())
    row = post(s, pid)
    assert len(s.sent) == 1 and s.svc.receipt_writes == 2          # tried twice
    assert row['status'] == 'uncertain' and row['error'] == d.UNCONFIRMED
    assert row['publication_id'] == expected_id(pid)
    # Never resent; the watch can't follow it up without the id, so it stays
    # for the owner to check, and the owner is told once.
    s.now = NOW + timedelta(hours=3)
    run(d.due_tick())
    run(d.delivery_tick())
    run(d.delivery_tick())
    assert len(s.sent) == 1 and post(s, pid)['status'] == 'uncertain'
    assert len(s.svc.notes) == 1 and len(s.pushes) == 1


def test_the_door_says_when_its_receipt_was_not_written(s):
    """send_post's own answer: still (row, True), the same public shape for
    /social/publish, but no provider_post_id on the row it hands back."""
    s.svc.receipt_fails = True
    targets = [{'connection_id': IG, 'platform': 'instagram', 'username': 'x', 'provider_account_id': 'spc_ig'}]
    row, sent_now = run(social.send_post(BIZ, OWNER, caption='Hi', media=[{'url': 'https://x.test/a.jpg', 'kind': 'image'}],
                                         targets=targets, scheduled_at=None, approved_hash='h' * 64))
    assert sent_now is True and not row.get('provider_post_id') and row['unrecorded_provider_post_id'] == 'sp_1'
    assert set(social._public(row)) == {'id', 'caption', 'media', 'targets', 'status', 'scheduled_at', 'results',
                                        'created_at'}
    s.svc.receipt_fails = False
    row, sent_now = run(social.send_post(BIZ, OWNER, caption='Hi again', media=[], targets=targets,
                                         scheduled_at=None, approved_hash='i' * 64))
    assert sent_now is True and row['provider_post_id'] == 'sp_2' and 'unrecorded_provider_post_id' not in row


def test_a_clip_whose_receipt_was_not_written_is_uncertain(s):
    pid = seed(s, media=clip_media())
    s.svc.receipt_fails = True
    run(d.due_tick())
    row = post(s, pid)
    assert len(s.sent) == 1
    assert row['status'] == 'uncertain' and row['error'] == d.UNCONFIRMED
    assert row['publication_id'] == d.publication_id_for(row)


# ── review of #1315: a failed read is never a verdict ─────────────────

def test_a_failed_publication_read_changes_nothing_even_past_two_hours(s):
    pid = seed(s)
    run(d.due_tick())
    before = copy.deepcopy(post(s, pid))
    s.now = NOW + timedelta(hours=3)
    s.svc.fail = ('/social_publications',)
    out = run(d.delivery_tick())
    assert out['unreadable'] == 1
    assert post(s, pid) == before                                  # not uncertain, not even checked_at
    assert s.svc.notes == [] and s.pushes == []
    s.svc.fail = ()
    run(d.delivery_tick())                                         # readable again: now the two hours count
    assert post(s, pid)['status'] == 'uncertain' and post(s, pid)['error'] == d.STILL_GOING
    assert len(s.pushes) == 1


# ── review of #1315: the newest problem is always considered ──────────

def failed_post(s, minutes_ago, *, told):
    pid = seed(s, status='failed', error='The posting service did not take it.',
               updated_at=(NOW - timedelta(minutes=minutes_ago)).isoformat())
    if told:
        s.svc.notes.append({'id': str(uuid4()), 'business_id': BIZ, 'created_at': (NOW - timedelta(minutes=minutes_ago)).isoformat(),
                            'action_payload': {'dedup_key': d.dedup_key(post(s, pid))}})
    return pid


def test_posts_already_told_never_crowd_out_a_new_problem(s):
    for i in range(120):
        failed_post(s, 10 + i, told=True)
    newest = failed_post(s, 1, told=False)
    out = run(d.delivery_tick())
    assert out['told'] == 1
    new = [n for n in s.svc.notes if n['action_payload'].get('post_id')]
    assert [n['action_payload']['post_id'] for n in new] == [newest] and len(s.pushes) == 1


def test_more_problems_than_one_tick_tells_are_all_told_once(s):
    order = [failed_post(s, i, told=False) for i in range(130)]      # newest first
    pids = set(order)
    assert run(d.delivery_tick())['told'] == d.TELL_LIMIT
    # The tick that cannot tell them all tells the newest ones first.
    assert {n['action_payload']['post_id'] for n in s.svc.notes} == set(order[:d.TELL_LIMIT])
    assert run(d.delivery_tick())['told'] == 30
    assert run(d.delivery_tick())['told'] == 0
    keys = [n['action_payload']['dedup_key'] for n in s.svc.notes]
    assert len(keys) == len(set(keys)) == 130 and {n['action_payload']['post_id'] for n in s.svc.notes} == pids
    assert len(s.pushes) == 130


def test_when_the_announcements_cannot_be_read_nothing_is_said(s):
    failed_post(s, 1, told=False)
    s.svc.fail = ('like.marketing_post',)
    run(d.delivery_tick())
    assert s.svc.notes == [] and s.pushes == []
    s.svc.fail = ()
    run(d.delivery_tick())
    assert len(s.svc.notes) == 1 and len(s.pushes) == 1
