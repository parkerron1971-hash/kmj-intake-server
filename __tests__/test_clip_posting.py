"""Post an approved clip with its cover (clip_posting). No live services.

  1. Only the owner; only a clip approved as it is now, and the one shown.
  2. The cover per network: story on vertical players, wide where a 16:9
     thumbnail is used, falling back to story, then none.
  3. A cover is used only when it is a ready design of this business naming
     this clip in that shape; nothing else is ever fetched.
  4. The post goes through the shared door: our row id as external_id, the
     video by a short-lived link that is handed over and never stored.
  5. A retried tap or the same post again is returned, never sent twice.
  6. A refused hand-off is recorded as failed and answered the same way.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import clip_posting as cp
import image_studio as images
import media_library
import post_for_me as pfm
import sb_clients

BIZ = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
OWNER = '11111111-1111-4111-8111-111111111111'
MANAGER = '33333333-3333-4333-8333-333333333333'
CLIP = '22222222-2222-4222-8222-222222222222'
CLIP2 = '44444444-4444-4444-8444-444444444444'
STORY, WIDE, OLD_STORY = (str(uuid4()) for _ in range(3))
FOREIGN, DRAFT, OTHER_CLIP_COVER = (str(uuid4()) for _ in range(3))


def clip(**over):
    row = {'id': CLIP, 'business_id': BIZ, 'kind': 'clip', 'status': 'ready', 'name': 'Separate Them',
           'source_id': None, 'sha256': 'abc', 'source_removed_at': None,
           'configuration': {'origin': 'ai', 'frame': True, 'caption': ''}}
    row.update(over)
    if 'approval' not in over:
        row['approval'] = {'fingerprint': media_library.fingerprint(row), 'by': OWNER}
    return row


def art(image_id, *, clip_id=CLIP, biz=BIZ, size='1088x1920', status='ready', at='2026-10-06T10:00:00Z'):
    return {'id': image_id, 'business_id': biz, 'status': status, 'size': size, 'storage_path': f'{biz}/{image_id}.png',
            'created_at': at, 'clip_id': clip_id}


def q(path):
    query = path.split('?', 1)[1] if '?' in path else ''
    return dict(p.split('=', 1) for p in query.split('&') if '=' in p)


class FakeDB:
    def __init__(self):
        self.owner = OWNER
        self.clips = [clip()]
        self.artworks = [art(STORY, at='2026-10-06T12:00:00Z'), art(OLD_STORY, at='2026-10-06T09:00:00Z'),
                         art(WIDE, size='1920x1088'), art(FOREIGN, biz=OTHER), art(DRAFT, status='working', at='2026-10-06T13:00:00Z'),
                         art(OTHER_CLIP_COVER, clip_id=CLIP2)]
        self.connections = [
            {'id': 'c-ig', 'business_id': BIZ, 'status': 'connected', 'platform': 'instagram', 'username': 'church', 'provider_account_id': 'spc_ig'},
            {'id': 'c-tt', 'business_id': BIZ, 'status': 'connected', 'platform': 'tiktok', 'username': 'church', 'provider_account_id': 'spc_tt'},
            {'id': 'c-yt', 'business_id': BIZ, 'status': 'connected', 'platform': 'youtube', 'username': 'church', 'provider_account_id': 'spc_yt'},
            {'id': 'c-fb', 'business_id': BIZ, 'status': 'connected', 'platform': 'facebook', 'username': 'Church Page', 'provider_account_id': 'spc_fb'},
            {'id': 'c-li', 'business_id': BIZ, 'status': 'connected', 'platform': 'linkedin', 'username': 'church', 'provider_account_id': 'spc_li'},
            {'id': 'c-x', 'business_id': BIZ, 'status': 'connected', 'platform': 'x', 'username': 'church', 'provider_account_id': 'spc_x'},
            {'id': 'c-other', 'business_id': OTHER, 'status': 'connected', 'platform': 'instagram', 'username': 'elsewhere', 'provider_account_id': 'spc_o'},
        ]
        self.pubs = []
        self.reads = []

    def get(self, path):
        self.reads.append(path)
        p = q(path)
        if path.startswith('/businesses'):
            return [{'owner_id': self.owner}] if p['id'] == f'eq.{BIZ}' else []
        if path.startswith('/social_connections'):
            ids = p.get('id', 'in.()')[4:-1].split(',')
            return [dict(c) for c in self.connections if c['business_id'] == p['business_id'][3:]
                    and c['status'] == 'connected' and c['id'] in ids]
        if path.startswith('/image_artworks'):
            rows = [a for a in self.artworks if a['business_id'] == p['business_id'][3:]
                    and a['clip_id'] == p['director->>clip_id'][3:] and a['status'] == p['status'][3:]]
            if 'id' in p:
                rows = [a for a in rows if a['id'] in p['id'][4:-1].split(',')]
            return sorted((dict(a) for a in rows), key=lambda a: a['created_at'], reverse=True)
        if path.startswith('/social_publications'):
            rows = [r for r in self.pubs if r['business_id'] == p['business_id'][3:]]
            if 'id' in p:
                rows = [r for r in rows if r['id'] == p['id'][3:]]
            if 'approved_hash' in p:
                rows = [r for r in rows if r.get('approved_hash') == p['approved_hash'][3:]]
            if p.get('status') == 'neq.failed':
                rows = [r for r in rows if r['status'] != 'failed']
            if p.get('status') == 'not.in.(failed,cancelled)':
                rows = [r for r in rows if r['status'] not in ('failed', 'cancelled')]
            return [dict(r) for r in rows]
        raise AssertionError(f'unexpected read {path}')

    def post(self, path, body, prefer=None):
        assert path == '/social_publications'
        if any(r['id'] == body.get('id') for r in self.pubs):
            return None   # the primary key is taken: PostgREST answers 409
        row = {'id': f'pub{len(self.pubs) + 1}', 'created_at': '2026-10-06T12:00:00Z', 'provider_post_id': None, 'results': [], **body}
        self.pubs.append(row)
        return [dict(row)]

    def patch(self, path, body):
        rid = q(path)['id'][3:]
        for r in self.pubs:
            if r['id'] == rid:
                r.update(body)


@pytest.fixture
def s(monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', BIZ)
    db = FakeDB()
    state = SimpleNamespace(db=db, sent=[], signed=[], jpegs=[], audited=[], user=OWNER)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', db.get)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', db.post)
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', db.patch)

    def read(path):
        p = q(path)
        return [dict(c) for c in db.clips if c['id'] == p['id'][3:] and c['business_id'] == p['business_id'][3:]]
    monkeypatch.setattr(cp.media_library, 'read', read)

    def sign(bucket, path, ttl=3600, download_as=None):
        state.signed.append((bucket, path, ttl))
        return f'https://sb.test/storage/v1/object/sign/{bucket}/{path}?token=secret-{len(state.signed)}'
    monkeypatch.setattr(cp.storage_links, 'signed_url_sync', sign)

    async def jpeg(client, business_id, row):
        state.jpegs.append(row['id'])
        return f'https://sb.test/storage/v1/object/public/business-assets/{business_id}/published-artwork/{row["id"]}.jpg'
    monkeypatch.setattr(images, 'delivery_jpeg', jpeg)

    async def create_post(**kw):
        state.sent.append(kw)
        return {'id': f'sp_{len(state.sent)}', 'status': 'processing'}
    monkeypatch.setattr(pfm, 'create_post', create_post)
    monkeypatch.setattr(cp.media_library, 'audit', lambda biz, user, action, asset: state.audited.append((action, asset)))

    api = FastAPI()
    api.include_router(cp.router)
    api.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=state.user))
    state.client = TestClient(api)
    return state


def thumb(image_id):
    return f'https://sb.test/storage/v1/object/public/business-assets/{BIZ}/published-artwork/{image_id}.jpg'


def post(s, clip_id=CLIP, **body):
    row = next((c for c in s.db.clips if c['id'] == clip_id), None)
    payload = {'request_id': str(uuid4()), 'fingerprint': media_library.fingerprint(row) if row else 'a' * 64,
               'connection_ids': ['c-ig'], **body}
    return s.client.post(f'/media-library/{BIZ}/clips/{clip_id}/post', json=payload)


def config(s, platform, n=0):
    return s.sent[n]['platform_configurations'][platform]


# ─── 1. who and which clip ────────────────────────────────────────────

def test_only_the_owner_posts(s):
    s.user = MANAGER
    r = post(s)
    assert r.status_code == 403 and s.sent == [] and s.signed == []
    assert not any(path.startswith('/social_connections') for path in s.db.reads)


def test_an_unknown_business_is_not_found(s):
    r = s.client.post(f'/media-library/{OTHER}/clips/{CLIP}/post',
                      json={'request_id': str(uuid4()), 'fingerprint': 'a' * 64, 'connection_ids': ['c-ig']})
    assert r.status_code == 404 and s.sent == []


def test_posting_switched_off_for_the_business(s, monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    r = post(s)
    assert r.status_code == 403 and 'switched on' in r.json()['detail'] and s.sent == []


def test_an_unapproved_clip_is_refused_in_plain_words(s):
    s.db.clips = [clip(approval=None)]
    r = post(s)
    assert r.status_code == 409 and 'Approve this clip' in r.json()['detail']
    assert s.sent == [] and s.signed == [] and s.db.pubs == []


def test_a_clip_changed_since_its_approval_is_refused(s):
    approved = clip()
    changed = clip(name='Separate Them', configuration={**approved['configuration'], 'caption': 'new words'},
                   approval=approved['approval'])
    s.db.clips = [changed]
    r = post(s)
    assert r.status_code == 409 and 'approve it again' in r.json()['detail'] and s.sent == []


def test_the_clip_must_be_the_one_the_owner_saw(s):
    r = post(s, fingerprint='f' * 64)
    assert r.status_code == 409 and 'since you opened it' in r.json()['detail'] and s.sent == []


def test_a_clip_of_another_business_or_not_ready(s):
    assert post(s, clip_id=CLIP2).status_code == 404
    s.db.clips = [clip(status='processing', approval=None)]
    assert post(s).status_code == 409
    assert s.sent == []


def test_an_account_of_another_business_is_refused(s):
    r = post(s, connection_ids=['c-ig', 'c-other'])
    assert r.status_code == 400 and s.sent == []


# ─── 2. the cover on each network ─────────────────────────────────────

def test_vertical_networks_get_the_story_cover(s):
    r = post(s, connection_ids=['c-ig', 'c-tt', 'c-yt', 'c-fb', 'c-x'], covers={'story': STORY, 'wide': WIDE})
    assert r.status_code == 200, r.text
    sent = s.sent[0]
    for platform in ('instagram', 'tiktok', 'youtube', 'facebook', 'x'):
        media = config(s, platform)['media']
        assert media[0]['thumbnail_url'] == thumb(STORY) and media[0]['url'].startswith('https://sb.test/')
    assert config(s, 'instagram')['placement'] == 'reels' and config(s, 'facebook')['placement'] == 'reels'
    assert config(s, 'youtube')['title'] == 'Separate Them'
    assert sent['media_urls'][0]['thumbnail_url'] == thumb(STORY)
    # Only the cover in use is published as a JPEG.
    assert s.jpegs == [STORY]
    assert r.json()['covers']['tiktok'] == {'shape': 'story', 'image_id': STORY}


def test_the_wide_cover_goes_where_a_16_9_thumbnail_is_used(s):
    post(s, connection_ids=['c-ig', 'c-li'], covers={'story': STORY, 'wide': WIDE})
    assert config(s, 'linkedin')['media'][0]['thumbnail_url'] == thumb(WIDE)
    assert config(s, 'instagram')['media'][0]['thumbnail_url'] == thumb(STORY)
    assert sorted(s.jpegs) == sorted([STORY, WIDE])


def test_without_a_wide_cover_the_story_cover_stands_in(s):
    r = post(s, connection_ids=['c-li'], covers={'story': STORY})
    assert config(s, 'linkedin')['media'][0]['thumbnail_url'] == thumb(STORY)
    assert r.json()['covers']['linkedin'] == {'shape': 'story', 'image_id': STORY}


def test_a_vertical_network_never_gets_the_wide_cover(s):
    r = post(s, connection_ids=['c-ig'], covers={'wide': WIDE})
    assert 'thumbnail_url' not in config(s, 'instagram')['media'][0]
    assert r.json()['covers']['instagram'] is None and s.jpegs == []


def test_no_covers_posts_with_no_thumbnail(s):
    post(s, connection_ids=['c-ig', 'c-li'], covers={})
    assert all('thumbnail_url' not in config(s, p)['media'][0] for p in ('instagram', 'linkedin'))
    assert 'thumbnail_url' not in s.sent[0]['media_urls'][0] and s.jpegs == []


def test_left_out_the_newest_ready_cover_of_each_shape_is_used(s):
    # DRAFT is newer but still being designed; OLD_STORY is older than STORY.
    post(s, connection_ids=['c-ig', 'c-li'])
    assert config(s, 'instagram')['media'][0]['thumbnail_url'] == thumb(STORY)
    assert config(s, 'linkedin')['media'][0]['thumbnail_url'] == thumb(WIDE)


# ─── 3. a cover must be this clip's, this business's, ready ───────────

@pytest.mark.parametrize('covers', [
    {'story': FOREIGN},             # another business's design
    {'story': OTHER_CLIP_COVER},    # another clip's cover
    {'story': DRAFT},               # still being designed
    {'story': WIDE},                # the other shape
    {'story': str(uuid4())},        # no such design
])
def test_a_cover_that_is_not_this_clips_finished_cover_is_refused(s, covers):
    r = post(s, covers=covers)
    assert r.status_code == 409 and 'not a finished cover of this clip' in r.json()['detail']
    assert s.sent == [] and s.jpegs == [] and s.signed == [] and s.db.pubs == []


def test_an_unknown_shape_is_refused_before_anything_is_read(s):
    r = post(s, covers={'square': STORY})
    assert r.status_code == 422 and s.sent == []


def test_a_cover_that_cannot_be_prepared_stops_the_post(s, monkeypatch):
    async def broken(client, business_id, row):
        from fastapi import HTTPException
        raise HTTPException(502, 'The original image could not be loaded.')
    monkeypatch.setattr(images, 'delivery_jpeg', broken)
    r = post(s, covers={'story': STORY})
    assert r.status_code == 502 and 'post without the cover' in r.json()['detail']
    assert s.sent == [] and s.db.pubs == []


# ─── 4. the shared door, the link, the record ─────────────────────────

def test_the_post_carries_our_id_and_keeps_no_link(s):
    request_id = str(uuid4())
    r = post(s, request_id=request_id, connection_ids=['c-ig', 'c-tt'], covers={'story': STORY})
    row = s.db.pubs[0]
    assert row['id'] == str(uuid5(UUID(CLIP), f'post:{request_id}')) == s.sent[0]['external_id']
    assert sorted(s.sent[0]['account_ids']) == ['spc_ig', 'spc_tt']
    assert row['approved_by'] == OWNER and len(row['approved_hash']) == 64 and row['status'] == 'posting'
    assert row['media'] == [{'kind': 'video', 'clip_id': CLIP, 'name': 'Separate Them', 'thumbnail_url': thumb(STORY),
                             'covers': {'instagram': STORY, 'tiktok': STORY}}]
    # The signed video link goes to the posting service only.
    assert 'secret-' not in json.dumps(row) and 'secret-' in s.sent[0]['media_urls'][0]['url']
    assert s.signed[0][:2] == ('program-media', f'{BIZ}/{CLIP}.mp4')
    assert r.json()['already'] is False and r.json()['publication']['status'] == 'posting'
    assert s.audited == [('post', CLIP)]


def test_a_post_now_gets_an_hour_long_link_and_a_scheduled_one_outlives_its_time(s):
    post(s)
    assert s.signed[0][2] == 3600
    when = datetime.now(timezone.utc) + timedelta(days=2)
    r = post(s, scheduled_at=when.isoformat(), caption='later')
    assert r.json()['publication']['status'] == 'scheduled'
    assert 2 * 86400 + 3000 < s.signed[1][2] <= 2 * 86400 + 3600
    assert s.sent[1]['scheduled_at']


def test_a_schedule_in_the_past_is_refused(s):
    r = post(s, scheduled_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    assert r.status_code == 400 and s.sent == []


def test_the_caption_defaults_to_the_title_and_the_owner_words_win(s):
    post(s)
    assert s.sent[0]['caption'] == 'Separate Them'
    post(s, caption='  Sunday, 10am. Come as you are.  ')
    assert s.sent[1]['caption'] == 'Sunday, 10am. Come as you are.'


def test_a_clip_caption_written_in_review_is_the_default(s):
    s.db.clips = [clip(configuration={'origin': 'upload', 'caption': 'Join us Sunday', 'destination': 'Instagram'})]
    post(s)
    assert s.sent[0]['caption'] == 'Join us Sunday'


def test_network_rules_still_apply(s):
    r = post(s, connection_ids=['c-x'], caption='x' * 281)
    assert r.status_code == 400 and '280' in r.json()['detail'] and s.sent == []


# ─── 5. never twice ───────────────────────────────────────────────────

def test_the_same_tap_twice_posts_once(s):
    request_id = str(uuid4())
    first = post(s, request_id=request_id)
    again = post(s, request_id=request_id)
    assert first.json()['already'] is False and again.json()['already'] is True
    assert len(s.sent) == 1 and len(s.db.pubs) == 1
    assert again.json()['publication']['id'] == first.json()['publication']['id']


def test_the_same_post_again_the_same_day_is_already_sent(s):
    post(s, connection_ids=['c-ig', 'c-tt'])
    again = post(s, connection_ids=['c-tt', 'c-ig'])
    assert again.json()['already'] is True and len(s.sent) == 1
    # Different words are a different post.
    post(s, connection_ids=['c-ig', 'c-tt'], caption='Another line')
    assert len(s.sent) == 2


def test_two_taps_at_once_post_once(s, monkeypatch):
    # The other tap saves this id after both of our looks and before our save:
    # our save is refused (the id is taken) and the other tap's post is returned.
    request_id = str(uuid4())
    pub_id = str(uuid5(UUID(CLIP), f'post:{request_id}'))
    real = s.db.get
    looks = []

    def get(path):
        if path.startswith(f'/social_publications?id=eq.{pub_id}'):
            looks.append(path)
            if len(looks) == 2:
                s.db.pubs.append({'id': pub_id, 'business_id': BIZ, 'status': 'posting', 'caption': '', 'media': [],
                                  'targets': [], 'results': [], 'created_at': 'now', 'scheduled_at': None})
                return []
        return real(path)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', get)
    r = post(s, request_id=request_id)
    assert r.status_code == 200 and r.json()['already'] is True and s.sent == [] and len(looks) == 3
    assert s.audited == []


# ─── 6. a refused hand-off ────────────────────────────────────────────

def test_a_refused_hand_off_is_failed_and_the_same_tap_says_so_again(s, monkeypatch):
    async def refuse(**kw):
        s.sent.append(kw)
        raise pfm.PostForMeError('Post for Me answered 422.', 422)
    monkeypatch.setattr(pfm, 'create_post', refuse)
    request_id = str(uuid4())
    r = post(s, request_id=request_id)
    assert r.status_code == 502 and 'Nothing went out' in r.json()['detail']
    assert 'Post for Me' not in r.json()['detail']
    assert s.db.pubs[0]['status'] == 'failed'
    assert post(s, request_id=request_id).status_code == 502 and len(s.sent) == 1
    # A new tap is a new try: a failed post never counts as already sent.
    async def accept(**kw):
        s.sent.append(kw)
        return {'id': 'sp_ok', 'status': 'processing'}
    monkeypatch.setattr(pfm, 'create_post', accept)
    ok = post(s)
    assert ok.status_code == 200 and ok.json()['already'] is False and len(s.sent) == 2


@pytest.mark.parametrize('failing', ['approved_hash=eq.', 'status=neq.failed'])
def test_a_failed_read_posts_nothing(s, monkeypatch, failing):
    """Review of #1298: the real service answers None on a failed read. The
    same-post-today check and the daily cap must not read that as nothing."""
    real = s.db.get
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', lambda path: None if failing in path else real(path))
    r = post(s, connection_ids=['c-ig'])
    assert r.status_code == 503 and 'Nothing was' in r.json()['detail']
    assert s.sent == [] and s.db.pubs == [] and s.audited == []


def test_no_signed_link_means_nothing_is_posted(s, monkeypatch):
    monkeypatch.setattr(cp.storage_links, 'signed_url_sync', lambda *a, **k: None)
    r = post(s)
    assert r.status_code == 503 and s.sent == [] and s.db.pubs == []


# ─── the posting service's request shape ──────────────────────────────

def test_a_video_goes_to_the_posting_service_with_its_thumbnail(monkeypatch):
    seen = {}

    async def request(method, path, *, params=None, json=None):
        seen.update(method=method, path=path, body=json)
        return {'id': 'sp_1', 'status': 'processing'}
    monkeypatch.setattr(pfm, '_request', request)
    out = asyncio.run(pfm.create_post(
        caption='hi', account_ids=['spc_ig'], external_id='pub1',
        media_urls=[{'url': 'https://v.test/c.mp4', 'thumbnail_url': 'https://t.test/c.jpg'}, 'https://i.test/a.jpg',
                    {'url': 'https://v.test/d.mp4', 'thumbnail_url': None}],
        platform_configurations={'instagram': {'placement': 'reels'}}))
    assert out == {'id': 'sp_1', 'status': 'processing'}
    assert seen['path'] == '/social-posts' and seen['body']['media'] == [
        {'url': 'https://v.test/c.mp4', 'thumbnail_url': 'https://t.test/c.jpg'},
        {'url': 'https://i.test/a.jpg'}, {'url': 'https://v.test/d.mp4'}]
    assert seen['body']['platform_configurations'] == {'instagram': {'placement': 'reels'}}


def test_the_cover_rule_table():
    covers = {'story': {'id': 's'}, 'wide': {'id': 'w'}}
    assert {p: cp.cover_for(p, covers) for p in ('instagram', 'facebook', 'tiktok', 'youtube', 'x', 'linkedin')} == {
        'instagram': 'story', 'facebook': 'story', 'tiktok': 'story', 'youtube': 'story', 'x': 'story', 'linkedin': 'wide'}
    assert cp.cover_for('linkedin', {'story': {}}) == 'story'
    assert cp.cover_for('youtube', {'wide': {}}) is None
    assert cp.cover_for('somethingnew', {'story': {}}) == 'story'
