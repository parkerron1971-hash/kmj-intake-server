"""Chief posts an approved clip (chief_clip_actions.post_clip). No live services.

  1. Which clip: by id, or by name (exact, then part of it); ambiguous or
     unknown is asked about, never guessed.
  2. Every refusal is plain words with a result and a label, and nothing is
     signed, read past the gate, or sent.
  3. Where it goes: every connected account by default, or the networks asked
     for; a network with no account is refused, never dropped.
  4. The caption (the clip's own, else its title; Chief's words win) and the
     covers (auto or none).
  5. Never twice: the same turn asking again returns the first post.
  6. Unattended runs are held, like publish_post's gate, at the handler and
     through the door; schedule_action will not wrap it.
  7. The registry: class C, client-facing, registered, never an agent tool.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import action_registry
import chief_clip_actions as cca
import chief_of_staff as cos
import clip_posting as cp
import image_studio as images
import media_library
import policy_engine
import post_for_me as pfm
import sb_clients

BIZ_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
OWNER = '11111111-1111-4111-8111-111111111111'
MANAGER = '33333333-3333-4333-8333-333333333333'
CLIP = '22222222-2222-4222-8222-222222222222'
AGAIN = '44444444-4444-4444-8444-444444444444'
PHARISEE = '55555555-5555-4555-8555-555555555555'
OLDER = '66666666-6666-4666-8666-666666666666'
STORY, WIDE = str(uuid4()), str(uuid4())
BIZ = {'id': BIZ_ID, 'owner_id': OWNER, 'name': 'Grace Church', 'type': 'church', 'settings': {}}

# Back-room names a practitioner must never read (CLAUDE.md).
FORBIDDEN = re.compile(r'\b(post for me|provider|api|github|claude|builder)\b', re.I)


def clip(cid=CLIP, name='Separate Them', at='2026-10-06T12:00:00Z', **over):
    row = {'id': cid, 'business_id': BIZ_ID, 'kind': 'clip', 'status': 'ready', 'name': name,
           'source_id': None, 'sha256': 'abc' + cid[:4], 'source_removed_at': None, 'created_at': at,
           'configuration': {'origin': 'ai', 'frame': True, 'caption': ''}}
    row.update(over)
    if 'approval' not in over:
        row['approval'] = {'fingerprint': media_library.fingerprint(row), 'by': OWNER}
    return row


def art(image_id, *, size='1088x1920', at='2026-10-06T10:00:00Z'):
    return {'id': image_id, 'business_id': BIZ_ID, 'status': 'ready', 'size': size,
            'storage_path': f'{BIZ_ID}/{image_id}.png', 'created_at': at, 'clip_id': CLIP}


def q(path):
    query = path.split('?', 1)[1] if '?' in path else ''
    return dict(p.split('=', 1) for p in query.split('&') if '=' in p)


class FakeDB:
    def __init__(self):
        self.owner = OWNER
        self.clips = [clip(), clip(AGAIN, 'Separate Them Again', at='2026-10-05T12:00:00Z'),
                      clip(PHARISEE, 'The Pharisee and the Tax Collector', at='2026-10-04T12:00:00Z')]
        self.artworks = [art(STORY), art(WIDE, size='1920x1088')]
        self.connections = [
            {'id': 'c-ig', 'business_id': BIZ_ID, 'status': 'connected', 'platform': 'instagram', 'username': 'gracechurch', 'provider_account_id': 'spc_ig'},
            {'id': 'c-tt', 'business_id': BIZ_ID, 'status': 'connected', 'platform': 'tiktok', 'username': 'gracechurch', 'provider_account_id': 'spc_tt'},
            {'id': 'c-yt', 'business_id': BIZ_ID, 'status': 'connected', 'platform': 'youtube', 'username': 'Grace Church', 'provider_account_id': 'spc_yt'},
            {'id': 'c-gone', 'business_id': BIZ_ID, 'status': 'disconnected', 'platform': 'facebook', 'username': 'old', 'provider_account_id': 'spc_fb'},
            {'id': 'c-other', 'business_id': OTHER, 'status': 'connected', 'platform': 'x', 'username': 'elsewhere', 'provider_account_id': 'spc_o'},
        ]
        self.pubs = []
        self.reads = []
        self.fail = ()

    def get(self, path):
        self.reads.append(path)
        if any(f in path for f in self.fail):
            return None
        p = q(path)
        if path.startswith('/businesses'):
            return [{'owner_id': self.owner}] if p['id'] == f'eq.{BIZ_ID}' else []
        if path.startswith('/social_connections'):
            rows = [c for c in self.connections if c['business_id'] == p['business_id'][3:]
                    and c['status'] == p['status'][3:]]
            if 'id' in p:
                rows = [c for c in rows if c['id'] in p['id'][4:-1].split(',')]
            return [dict(c) for c in rows]
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

    def media(self, path):
        """media_library.read: the clip table."""
        self.reads.append(path)
        if any(f in path for f in self.fail):
            raise cp.HTTPException(503, 'The media library is unavailable.')
        p = q(path)
        rows = [c for c in self.clips if c['business_id'] == p['business_id'][3:] and c['kind'] == p['kind'][3:]]
        if 'id' in p:
            rows = [c for c in rows if c['id'] == p['id'][3:]]
        if 'status' in p:
            rows = [c for c in rows if c['status'] == p['status'][3:]]
        if p.get('order') == 'created_at.desc':
            rows = sorted(rows, key=lambda c: c['created_at'], reverse=True)
        return [dict(c) for c in rows]

    def post(self, path, body, prefer=None):
        assert path == '/social_publications', path
        if any(r['id'] == body.get('id') for r in self.pubs):
            return None
        row = {'id': f'pub{len(self.pubs) + 1}', 'created_at': '2026-10-06T12:00:00Z',
               'provider_post_id': None, 'results': [], **body}
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
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', BIZ_ID)
    db = FakeDB()
    state = SimpleNamespace(db=db, sent=[], signed=[], jpegs=[], audited=[])
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', db.get)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', db.post)
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', db.patch)
    monkeypatch.setattr(media_library, 'read', db.media)

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
    monkeypatch.setattr(media_library, 'audit', lambda biz, user, action, asset: state.audited.append((action, asset, user.id)))

    # The chat turn: who is driving it, and its id.
    user_token = cos._TURN_USER_ID.set(OWNER)
    turn_token = images.turn_id.set('turn-1')
    state.turn = lambda t: images.turn_id.set(t)
    state.user = lambda u: cos._TURN_USER_ID.set(u)
    yield state
    images.turn_id.reset(turn_token)
    cos._TURN_USER_ID.reset(user_token)


def run(action, biz=BIZ):
    return asyncio.run(cos.ACTION_HANDLERS['post_clip'](None, biz, {'type': 'post_clip', **action}))


def config(s, platform, n=0):
    return s.sent[n]['platform_configurations'][platform]


def thumb(image_id):
    return f'https://sb.test/storage/v1/object/public/business-assets/{BIZ_ID}/published-artwork/{image_id}.jpg'


def plain(out):
    """A card the app can always show: both keys, real words, no back-room names."""
    assert isinstance(out.get('result'), str) and out['result'].strip()
    assert isinstance(out.get('label'), str) and out['label'].strip()
    assert not FORBIDDEN.search(out['result'] + ' ' + out['label']), out
    return out


def refused(s, out):
    plain(out)
    assert out['failed'] is True and out['ok'] is False and cos._action_failed(out)
    assert 'nothing' in out['result'].lower() or 'which' in out['result'].lower()
    assert s.sent == [] and s.signed == [] and s.db.pubs == [] and s.jpegs == []
    return out


# ─── 1. which clip ────────────────────────────────────────────────────

def test_by_id_it_goes_to_every_connected_account(s):
    out = plain(run({'clip_id': CLIP}))
    assert out['ok'] is True and out.get('failed') is not True and not cos._action_failed(out)
    assert len(s.sent) == 1
    assert sorted(s.sent[0]['account_ids']) == ['spc_ig', 'spc_tt', 'spc_yt']
    assert out['label'] == 'Sent your clip to Instagram, TikTok and YouTube'
    assert '“Separate Them”' in out['result'] and 'Instagram (gracechurch)' in out['result']
    assert 'Video Clips' in out['result'] and out['nav'] == {'tab': 'grow', 'sub': 'video-clips'}
    # Approved by the owner who asked; the record says so.
    assert s.db.pubs[0]['approved_by'] == OWNER and s.audited == [('post', CLIP, OWNER)]


def test_by_exact_name_case_insensitive_before_part_of_a_name(s):
    # "Separate Them Again" also contains the words; the exact name wins.
    out = plain(run({'clip_name': '  separate THEM '}))
    assert out['ok'] is True and out['clip_id'] == CLIP


def test_by_part_of_the_name(s):
    out = plain(run({'clip_name': 'pharisee'}))
    assert out['ok'] is True and out['clip_id'] == PHARISEE
    assert s.sent[0]['caption'] == 'The Pharisee and the Tax Collector'


def test_more_than_one_match_is_asked_about_newest_first(s):
    out = refused(s, run({'clip_name': 'them'}))
    assert out['label'] == 'Which clip?'
    names = [c['name'] for c in out['clips']]
    assert names == ['Separate Them', 'Separate Them Again']
    assert '“Separate Them” (made Oct 6); “Separate Them Again” (made Oct 5)' in out['result']


def test_two_clips_with_the_same_name_are_asked_about(s):
    s.db.clips.append(clip(OLDER, 'Separate Them', at='2026-10-01T12:00:00Z'))
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert [c['clip_id'] for c in out['clips']] == [CLIP, OLDER]


def test_at_most_five_names_are_listed(s):
    for n in range(7):
        s.db.clips.append(clip(str(uuid4()), f'Grace moment {n}', at=f'2026-09-2{n}T12:00:00Z'))
    out = refused(s, run({'clip_name': 'grace moment'}))
    assert len(out['clips']) == 5 and 'and 2 more' in out['result']
    assert out['clips'][0]['name'] == 'Grace moment 6'


def test_no_matching_clip(s):
    out = refused(s, run({'clip_name': 'Easter sunrise'}))
    assert out['label'] == 'Clip not found' and 'Easter sunrise' in out['result']


def test_no_clip_named_at_all(s):
    out = refused(s, run({}))
    assert out['label'] == 'Which clip?'


@pytest.mark.parametrize('clip_id', ['not-a-uuid', str(uuid4())])
def test_an_unknown_or_malformed_id(s, clip_id):
    out = refused(s, run({'clip_id': clip_id}))
    assert out['label'] == 'Clip not found'
    assert not any('not-a-uuid' in r for r in s.db.reads), 'a malformed id never reaches a query'


def test_a_clip_still_being_made_or_no_longer_stored(s):
    s.db.clips[0] = clip(status='processing', approval=None)
    assert 'still being made' in refused(s, run({'clip_id': CLIP}))['result']
    s.db.clips[0] = clip(source_removed_at='2026-10-01T00:00:00Z')
    assert 'no longer stored' in refused(s, run({'clip_name': 'Separate Them'}))['result']


# ─── 2. refusals ──────────────────────────────────────────────────────

def test_only_the_owner_and_nothing_is_read_first(s):
    s.user(MANAGER)
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert out['label'] == 'Only the owner can post clips'
    assert not any(r.startswith(('/social_connections', '/media_assets')) for r in s.db.reads)


def test_no_signed_in_turn_posts_nothing(s):
    s.user('')
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert 'owner asks me in chat' in out['result'] and s.db.reads == []


def test_posting_switched_off_for_the_business(s, monkeypatch):
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', OTHER)
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert "isn't switched on" in out['result']


def test_posting_not_set_up(s, monkeypatch):
    monkeypatch.delenv('POST_FOR_ME_API_KEY')
    assert "isn't set up" in refused(s, run({'clip_name': 'Separate Them'}))['result']


def test_no_account_connected(s):
    s.db.connections = [c for c in s.db.connections if c['business_id'] != BIZ_ID or c['status'] != 'connected']
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert 'Connect an account in Build, Social Media' in out['result']
    assert out['nav'] == {'tab': 'build', 'sub': 'social-media'}


def test_a_failed_accounts_read_posts_nothing(s):
    s.db.fail = ('/social_connections',)
    assert "couldn't read your connected accounts" in refused(s, run({'clip_name': 'Separate Them'}))['result']


def test_a_failed_clips_read_posts_nothing(s):
    s.db.fail = ('/media_assets',)
    assert "couldn't read your clips" in refused(s, run({'clip_name': 'Separate Them'}))['result']


def test_a_clip_never_approved(s):
    s.db.clips[0] = clip(approval=None)
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert 'Approve it in Video Clips first' in out['result'] and "can't approve a clip for you" in out['result']
    assert out['label'] == 'Approve it in Video Clips first'


def test_a_clip_changed_since_it_was_approved(s):
    approved = clip()
    s.db.clips[0] = clip(configuration={**approved['configuration'], 'caption': 'new words'},
                         approval=approved['approval'])
    out = refused(s, run({'clip_name': 'Separate Them'}))
    assert 'changed after it was approved' in out['result']
    assert out['label'] == 'Approve it again in Video Clips first'


def test_a_time_in_the_past(s):
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    out = refused(s, run({'clip_name': 'Separate Them', 'when': past}))
    assert out['label'] == 'That time has passed' and 'already passed' in out['result']


@pytest.mark.parametrize('when', ['next thursday', '2026-12-01T09:00:00'])
def test_a_time_that_does_not_read_or_has_no_zone(s, when):
    refused(s, run({'clip_name': 'Separate Them', 'when': when}))


def test_a_time_more_than_90_days_out_is_the_door_s_refusal_in_plain_words(s):
    far = (datetime.now(timezone.utc) + timedelta(days=120)).isoformat()
    out = refused(s, run({'clip_name': 'Separate Them', 'when': far}))
    assert '90 days' in out['result'] and 'Nothing was posted' in out['result']


def test_network_rules_still_apply(s):
    s.db.connections.append({'id': 'c-x', 'business_id': BIZ_ID, 'status': 'connected', 'platform': 'x',
                             'username': 'grace', 'provider_account_id': 'spc_x'})
    out = plain(run({'clip_name': 'Separate Them', 'platforms': ['twitter'], 'caption': 'x' * 281}))
    assert out['failed'] is True and '280' in out['result'] and 'Nothing was posted' in out['result']
    assert s.sent == [] and s.db.pubs == []


def test_a_refused_hand_off_says_nothing_went_out(s, monkeypatch):
    async def refuse(**kw):
        s.sent.append(kw)
        raise pfm.PostForMeError('Post for Me answered 422.', 422)
    monkeypatch.setattr(pfm, 'create_post', refuse)
    out = plain(run({'clip_name': 'Separate Them'}))
    assert out['failed'] is True and 'nothing went out' in out['result']
    assert s.db.pubs[0]['status'] == 'failed'


def test_a_cover_that_cannot_be_prepared_stops_the_post(s, monkeypatch):
    async def broken(client, business_id, row):
        raise cp.HTTPException(502, 'The original image could not be loaded.')
    monkeypatch.setattr(images, 'delivery_jpeg', broken)
    out = plain(run({'clip_name': 'Separate Them'}))
    assert out['failed'] is True and 'post without the cover' in out['result']
    assert s.sent == [] and s.db.pubs == []


# ─── 3. where it goes ─────────────────────────────────────────────────

def test_the_networks_asked_for_and_only_those(s):
    out = plain(run({'clip_name': 'Separate Them', 'platforms': ['Instagram', 'tik tok']}))
    assert sorted(s.sent[0]['account_ids']) == ['spc_ig', 'spc_tt']
    assert out['label'] == 'Sent your clip to Instagram and TikTok'


def test_one_network_as_a_word(s):
    plain(run({'clip_name': 'Separate Them', 'platforms': 'yt'}))
    assert s.sent[0]['account_ids'] == ['spc_yt']


def test_a_network_with_no_account_is_refused_not_dropped(s):
    out = refused(s, run({'clip_name': 'Separate Them', 'platforms': ['instagram', 'twitter']}))
    assert 'No X account is connected' in out['result'] and 'Instagram (gracechurch)' in out['result']
    assert out['nav'] == {'tab': 'build', 'sub': 'social-media'}


def test_a_disconnected_or_another_business_s_account_is_never_used(s):
    refused(s, run({'clip_name': 'Separate Them', 'platforms': ['facebook']}))
    plain(run({'clip_name': 'Separate Them'}))
    assert 'spc_fb' not in s.sent[0]['account_ids'] and 'spc_o' not in s.sent[0]['account_ids']


# ─── 4. caption and covers ────────────────────────────────────────────

def test_the_caption_defaults_to_the_title(s):
    out = plain(run({'clip_name': 'Separate Them'}))
    assert s.sent[0]['caption'] == 'Separate Them'
    assert 'the caption “Separate Them”' in out['result']


def test_the_clip_s_own_caption_is_the_default(s):
    s.db.clips[0] = clip(configuration={'origin': 'upload', 'caption': 'Join us Sunday', 'destination': 'Instagram'})
    plain(run({'clip_name': 'Separate Them'}))
    assert s.sent[0]['caption'] == 'Join us Sunday'


def test_chief_s_caption_wins(s):
    out = plain(run({'clip_name': 'Separate Them', 'caption': '  Sunday at 10. Come as you are.  '}))
    assert s.sent[0]['caption'] == 'Sunday at 10. Come as you are.'
    assert '“Sunday at 10. Come as you are.”' in out['result']


def test_covers_auto_uses_the_story_cover_on_vertical_networks(s):
    out = plain(run({'clip_name': 'Separate Them'}))
    for platform in ('instagram', 'tiktok', 'youtube'):
        assert config(s, platform)['media'][0]['thumbnail_url'] == thumb(STORY)
    assert s.jpegs == [STORY] and 'story cover' in out['result']


def test_covers_none_posts_with_no_thumbnail(s):
    out = plain(run({'clip_name': 'Separate Them', 'covers': 'none'}))
    assert all('thumbnail_url' not in config(s, p)['media'][0] for p in ('instagram', 'tiktok', 'youtube'))
    assert s.jpegs == [] and 'no cover, as you asked' in out['result']


def test_a_clip_with_no_finished_cover_says_so(s):
    s.db.artworks = []
    out = plain(run({'clip_name': 'Separate Them'}))
    assert 'no finished cover' in out['result'] and s.jpegs == []


# ─── 5. a time, and never twice ───────────────────────────────────────

def test_a_scheduled_post_says_when_in_the_owner_s_time(s):
    zone = timezone(timedelta(hours=-4))
    at = (datetime.now(zone) + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    out = plain(run({'clip_name': 'Separate Them', 'when': at.isoformat()}))
    assert out['ok'] is True and out['publication']['status'] == 'scheduled'
    assert out['label'] == f'Scheduled your clip for {at:%A} {at:%b} {at.day}, 9:00 AM'
    assert 'cancel it in Video Clips' in out['result']
    assert s.sent[0]['scheduled_at'] and s.db.pubs[0]['status'] == 'scheduled'


def test_the_same_turn_twice_posts_once(s):
    first = plain(run({'clip_name': 'Separate Them', 'platforms': ['instagram', 'tiktok']}))
    again = plain(run({'clip_name': 'Separate Them', 'platforms': ['tiktok', 'instagram']}))
    assert first['already'] is False and again['already'] is True
    assert len(s.sent) == 1 and len(s.db.pubs) == 1
    assert again['publication']['id'] == first['publication']['id']
    assert again['label'] == 'Already sent, not posted twice' and not cos._action_failed(again)


def test_the_post_id_comes_from_the_turn(s):
    run({'clip_name': 'Separate Them'})
    s.turn('turn-2')
    out = plain(run({'clip_name': 'Separate Them'}))
    # A new turn is a new request id; the same post the same day is still
    # caught by the door's duplicate guard, the second line.
    assert out['already'] is True and len(s.sent) == 1 and len(s.db.pubs) == 1


def test_different_words_in_the_same_turn_are_a_different_post(s):
    run({'clip_name': 'Separate Them'})
    out = plain(run({'clip_name': 'Separate Them', 'caption': 'Another line'}))
    assert out['already'] is False and len(s.sent) == 2


def test_chief_calls_the_same_door_as_the_post_tap(s, monkeypatch):
    seen = []
    real = cp.post_clip_for

    async def spy(*a, **k):
        seen.append((a, k))
        return await real(*a, **k)
    monkeypatch.setattr(cp, 'post_clip_for', spy)
    run({'clip_name': 'Separate Them', 'covers': 'none'})
    (args, kw), = seen
    assert args == (BIZ_ID, OWNER, CLIP)
    assert kw['fingerprint'] == media_library.fingerprint(s.db.clips[0])
    assert kw['caption'] is None and kw['covers'] == {} and kw['scheduled_at'] is None
    assert sorted(kw['connection_ids']) == ['c-ig', 'c-tt', 'c-yt']
    assert 'post_clip_for(' in inspect.getsource(cp.post_clip)


# ─── 6. unattended ────────────────────────────────────────────────────

def test_an_unattended_run_is_held_before_anything_is_read(s):
    # The scheduler's mark (chief_scheduler sets it on every run it makes),
    # even with the owner's id still about.
    out = refused(s, run({'clip_name': 'Separate Them', '_unattended': True}))
    assert 'only when you ask me' in out['result'] and s.db.reads == []


def _quiet_policy(monkeypatch):
    seen = []

    class _V:
        allowed, rule, reason = True, 'spy', 'ok'

    def evaluate(business_id, *, verb, surface, prompted, user_id=None, biz_row=None):
        seen.append({'verb': verb, 'surface': surface, 'prompted': prompted})
        return _V()
    monkeypatch.setattr(policy_engine, 'evaluate', evaluate)
    return seen


def test_through_the_door_unattended_is_held_and_cannot_claim_otherwise(s, monkeypatch):
    seen = _quiet_policy(monkeypatch)
    taken = asyncio.run(cos._execute_actions(
        None, BIZ, [{'type': 'post_clip', 'clip_name': 'Separate Them', '_unattended': False}],
        user_id=OWNER, surface='agent', prompted=False))
    assert seen == [{'verb': 'post_clip', 'surface': 'agent', 'prompted': False}]
    refused(s, taken[0])
    assert 'only when you ask me' in taken[0]['result']


def test_through_the_door_when_the_owner_asks_it_posts(s, monkeypatch):
    _quiet_policy(monkeypatch)
    cos._UNTRUSTED_TAINT.set(0)
    taken = asyncio.run(cos._execute_actions(
        None, BIZ, [{'type': 'post_clip', 'clip_name': 'Separate Them'}], user_id=OWNER))
    out = plain(taken[0])
    assert out['ok'] is True and len(s.sent) == 1 and out['_authorized_by'] == 'spy'


def test_schedule_action_will_not_wrap_a_clip_post(monkeypatch):
    import chief_strategy_actions as csa
    monkeypatch.setattr(sb_clients, 'sb_post_as_service',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('nothing is scheduled')))
    out = asyncio.run(cos.ACTION_HANDLERS['schedule_action'](None, BIZ, {
        'type': 'schedule_action', 'in_minutes': 60,
        'action': {'type': 'post_clip', 'clip_name': 'Separate Them'}}))
    assert cos._action_failed(out) and 'when' in out['result']
    assert 'post_clip' in inspect.getsource(csa.handle_schedule_action)


# ─── 7. the registry ──────────────────────────────────────────────────

def test_post_clip_is_class_c_client_facing_and_never_an_agent_tool():
    cls = action_registry.classification('post_clip')
    assert cls['effect'] == 'write' and cls['reversibility'] == 'C' and not cls.get('bulk')
    assert 'cancelled' in cls['why'] and 'recalled' in cls['why']
    assert not action_registry.is_autonomy_eligible('post_clip')
    assert not action_registry.is_autonomy_eligible('post_clip', granted_scope=True)
    assert not action_registry.may_expose_to_agent('post_clip', allow_writes=True)
    assert 'post_clip' in policy_engine.CLIENT_FACING
    assert cos.ACTION_HANDLERS['post_clip'] is cos.handle_post_clip is cca.handle_post_clip
    import mcp_server
    assert 'post_clip' not in getattr(mcp_server, 'WRITE_TOOL_SCHEMAS', {})


def test_the_prompt_teaches_the_tag_and_its_rules():
    import chief_prompt
    src = inspect.getsource(chief_prompt)
    assert '"type":"post_clip"' in src
    rule = src[src.index('POSTING A VIDEO CLIP'):][:1500]
    for must in ('only when the owner asks', 'approved in Video Clips', 'state the caption and the accounts',
                 'only as the action result says', 'never wrap post_clip in schedule_action'):
        assert must in rule, must


def test_the_back_room_words_check_bites():
    """Guarding the guard: a pattern that matched nothing would pass every
    wording check above."""
    assert FORBIDDEN.search('The Post for Me API said no') and FORBIDDEN.search('provider error')
    assert not FORBIDDEN.search('Approve it in Video Clips first, rapidly')
