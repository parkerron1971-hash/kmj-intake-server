"""Clips folded into the week (business_marketing_clips.py + the planner, B12).

Solutionist (the autopilot level) gets B9's five flyer posts plus up to two
of its own clips: ready, kept, approved at the fingerprint they have now,
not posted anywhere, not already in a waiting post, with a ready story
cover. Best score first, then newest; each on its own weekday at the desk's
hour or the next free hour, three hours from any other post. One caption
call for the whole week. Every desk account that takes a video, TikTok and
YouTube included; the cover per network is clip_posting's. The clip's
fingerprint is in the post's content hash and the sender refuses a clip that
changed. Professional, Boss and the suggest level never get clips; with no
eligible clip the week is exactly B9's.

No network: the B9 suite's fakes (the marketing tables and RPCs, the
service-role reads, the model, Image Studio, push), plus media_assets,
the clips' covers and social_publications.
"""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '__tests__'))

import pytest

import business_marketing as bm
import business_marketing_clips as clips
import business_marketing_dispatch as d
import business_marketing_planner as plan
import business_marketing_store as store
import clip_covers
import clip_posting
import feature_gates
import marketing_profile as prof
import media_library
import rate_limit
import sb_clients

from test_business_marketing_planner import (  # noqa: E402
    BIZ, CHICAGO, FACTS, NEXT_MONDAY, PRO, PRO_OWNER, THU, _when, business, connection, select)
from test_business_marketing_week import (  # noqa: E402  (the B9 suite's fixture and helpers)
    BOSS, IG, PRO_FB, TIKTOK, ask, finish, posts_of, run_of, settle, w, week_reply)

run = asyncio.run

YOUTUBE = 'c0000000-0000-4000-8000-0000000000a4'
SOURCE = 'f0000000-0000-4000-8000-000000000001'
CLIP_TEXTS = {6: 'Watch this before you plan Monday: one small habit for a calmer week. #planning #coaching',
              7: 'A minute on guarding one quiet hour, and why it changes the whole week. #planning'}


def clip_id(n):
    return f'd0000000-0000-4000-8000-{n:012d}'


def make_clip(n, *, score=None, kept='kept', approved=True, changed=False, status='ready', removed=False,
              created=None, biz=PRO, name=None):
    row = {'id': clip_id(n), 'business_id': biz, 'kind': 'clip', 'source_id': SOURCE,
           'name': name or f'Clip {chr(64 + n)}: a calmer week', 'status': status,
           'configuration': {'origin': 'ai', 'score': score, 'caption': 'Our coach on planning the week.',
                             'destination': '', 'tags': ['planning']},
           'sha256': f'{n:02d}' * 32, 'approval': None, 'decision': kept, 'decided_at': '2026-10-06T12:00:00Z',
           'source_removed_at': '2026-10-06T00:00:00Z' if removed else None, 'duration_seconds': 42.0,
           'created_at': created or f'2026-10-0{min(n, 7)}T12:00:00Z',
           'finished_at': created or f'2026-10-0{min(n, 7)}T12:00:00Z'}
    if approved:
        row['approval'] = {'fingerprint': '0' * 64 if changed else media_library.fingerprint(row),
                           'by': PRO_OWNER, 'at': '2026-10-06T12:00:00Z'}
    return row


def make_cover(cid, shape='story', *, status='ready', biz=PRO, created='2026-10-06T13:00:00Z'):
    image = str(uuid4())
    return {'id': image, 'business_id': biz, 'status': status, 'size': clip_covers.SHAPES[shape],
            'storage_path': f'{biz}/{image}-1.png' if status == 'ready' else None, 'created_at': created,
            'director': {'clip_id': cid}, 'clip_id': cid}


def publication(cid, status='posted', biz=PRO):
    return {'id': str(uuid4()), 'business_id': biz, 'status': status, 'provider_post_id': 'pfm_x',
            'media': [{'kind': 'video', 'clip_id': cid, 'name': 'x'}], 'targets': [], 'results': [],
            'caption': '', 'scheduled_at': None, 'created_at': '2026-10-06T12:00:00Z', 'approved_by': PRO_OWNER}


def clip_reply(over=None):
    reply = week_reply()
    for n, text in CLIP_TEXTS.items():
        reply['captions'].append({'slot': n, 'text': text})
    for item in reply['captions']:
        item.update((over or {}).get(item['slot'], {}))
    return reply


def _pubs(rows, path):
    """social_publications, with the planner's `media->0->>clip_id=in.(...)` filter."""
    want = None
    parts = []
    for part in path.split('?', 1)[1].split('&'):
        if part.startswith('media->0->>clip_id=in.('):
            want = set(part[len('media->0->>clip_id=in.('):-1].split(','))
        else:
            parts.append(part)
    if want is not None:
        rows = [r for r in rows if (r.get('media') or [{}])[0].get('clip_id') in want]
    return select(rows, path.split('?', 1)[0] + '?' + '&'.join(parts))


@pytest.fixture
def c(w, monkeypatch):
    """The B9 week's fixture, with PRO on the Solutionist plan and its clips."""
    w.svc.businesses[PRO]['comp_tier'] = 'practice'
    w.svc.connections.append(connection(YOUTUBE, 'youtube', biz=PRO))
    w.clips, w.covers, w.pubs = [], [], []
    w.reply = clip_reply()
    base = w.svc.get

    def get(path):
        table = path.split('?', 1)[0]
        if table in ('/media_assets', '/social_publications') or (
                table == '/image_artworks' and 'director->>clip_id' in path):
            w.svc.reads.append(path)
            if any(f in path for f in w.svc.fail):
                return None
            if table == '/media_assets':
                return copy.deepcopy(select(w.clips, path))
            if table == '/social_publications':
                return copy.deepcopy(_pubs(w.pubs, path))
            return copy.deepcopy(select(w.covers, path))
        return base(path)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', get)
    return w


def two_clips(c):
    """Two eligible clips (A scores higher, B is newer), each with both covers."""
    c.clips += [make_clip(1, score=0.9, created='2026-10-01T12:00:00Z'),
                make_clip(2, score=0.5, created='2026-10-05T12:00:00Z')]
    for n in (1, 2):
        c.covers += [make_cover(clip_id(n), 'story'), make_cover(clip_id(n), 'wide')]


def cover_of(c, n, shape):
    return next(x['id'] for x in c.covers if x['clip_id'] == clip_id(n) and x['size'] == clip_covers.SHAPES[shape])


def week(c, bid=PRO):
    return run(plan.run_week(bid, trigger='scheduled'))


def clip_posts(c, bid=PRO, status=None):
    return [p for p in posts_of(c, bid, status) if p.get('source') == 'clip']


def reads_of(c, table):
    return [r for r in c.svc.reads if r.startswith(table)]


# ── the week: five flyer posts and two clips ──────────────────────────

def test_a_solutionist_week_is_five_flyer_posts_and_two_clips_saved_at_once(c):
    two_clips(c)
    out = week(c)
    assert out['status'] == 'succeeded' and out['designing'] == 5
    inserts = [b for m, p, b in c.db.writes if m == 'POST' and p == '/marketing_posts']
    assert len(inserts) == 1 and len(inserts[0]) == 7                       # one write, seven drafts
    posts = posts_of(c)
    assert [p['source'] for p in posts].count('plan') == 5 and len(clip_posts(c)) == 2
    r = run_of(c)
    assert r['post_ids'] == [p['id'] for p in inserts[0]]
    for n, p in zip((1, 2), sorted(clip_posts(c), key=lambda p: p['run_at'])):
        row = next(x for x in c.clips if x['id'] == clip_id(n))
        assert p['status'] == 'draft' and p['design_status'] == 'none' and p['play_id'] == clips.PLAY_ID
        assert p['run_id'] == r['id'] and p['id'] == clips.post_id(r['id'], 1, n)
        assert p['media'] == {'clip_id': clip_id(n), 'clip_fingerprint': media_library.fingerprint(row),
                              'covers': {'story': cover_of(c, n, 'story'), 'wide': cover_of(c, n, 'wide')}}
        assert p['content_hash'] == store.digest(p) and p['caption'] == CLIP_TEXTS[5 + n]
        # Every connected account takes a video: TikTok and YouTube too.
        assert {t['platform'] for t in p['targets']} == {'facebook', 'instagram', 'tiktok', 'youtube'}
        assert p['tracked_url'] and '/go/' in p['publish_text'] and p['link_code'] == store.link_code(p['id'])
    for p in posts:
        if p['source'] == 'plan':                                         # B9's posts are unchanged
            assert {t['platform'] for t in p['targets']} == {'facebook', 'instagram'}
    assert len(c.creates) == 5                                            # flyers for the five only
    picked = r['design']['clips']['picked']
    assert [x['clip_id'] for x in picked] == [clip_id(1), clip_id(2)] and all(x['saved'] for x in picked)
    assert not any(path.startswith('/rpc/marketing_approve') for _, path, _ in c.db.writes)


def test_one_caption_call_for_the_whole_week_clips_included(c):
    two_clips(c)
    week(c)
    assert len(c.calls) == 1                                              # no extra paid call per clip
    payload, kw = c.calls[0]
    assert kw['task'] == plan.WEEK_TASK and kw['units'] == 0 and kw['business_id'] == PRO
    assert payload['max_tokens'] == plan.WEEK_MAX_TOKENS + 2 * clips.MAX_TOKENS_EACH
    asked = json.loads(payload['messages'][0]['content'])
    assert [s['slot'] for s in asked['slots']] == [1, 2, 3, 4, 5, 6, 7]
    six = asked['slots'][5]
    assert six['play'] == clips.PLAY_LABEL and six['clip']['title'] == 'Clip A: a calmer week'
    assert six['clip']['words'] == 'Our coach on planning the week.' and 'no flyer' in six['play_brief']


# ── which clips, and when ─────────────────────────────────────────────

def test_the_pick_is_best_score_then_newest_each_on_its_own_day_spaced_from_the_flyers(c):
    c.clips += [make_clip(1, score=0.4, created='2026-10-06T12:00:00Z'),
                make_clip(2, score=0.9, created='2026-10-02T12:00:00Z'),
                make_clip(3, score=None, created='2026-10-07T12:00:00Z'),
                make_clip(4, score=0.4, created='2026-10-03T12:00:00Z')]
    for n in (1, 2, 3, 4):
        c.covers.append(make_cover(clip_id(n)))
    assert [r['id'] for r in clips.rank(c.clips)] == [clip_id(2), clip_id(1), clip_id(4), clip_id(3)]
    week(c)
    got = sorted(clip_posts(c), key=lambda p: p['run_at'])
    assert [p['media']['clip_id'] for p in got] == [clip_id(2), clip_id(1)]   # best score, then the newer 0.4
    local = [_when(p['run_at']).astimezone(CHICAGO) for p in got]
    assert [(t.date(), t.hour) for t in local] == [(NEXT_MONDAY + timedelta(days=1), 14),     # Tuesday
                                                   (NEXT_MONDAY + timedelta(days=3), 14)]     # Thursday
    others = [_when(p['run_at']) for p in posts_of(c) if p['source'] == 'plan']
    for p in got:
        assert all(abs(_when(p['run_at']) - o) >= clips.GAP for o in others)
    assert len({t.date() for t in local}) == 2                              # never two the same day


def test_place_keeps_the_desks_hour_or_the_next_free_one_and_never_crowds_a_day():
    tue = NEXT_MONDAY + timedelta(days=1)
    at = THU
    busy = [datetime.combine(NEXT_MONDAY + timedelta(days=i), datetime.min.time().replace(hour=11), CHICAGO)
            for i in range(5)]
    times = clips.place(2, week_of=NEXT_MONDAY, tz=CHICAGO, post_hour=11, at=at, busy=busy)
    assert [(t.date(), t.hour) for t in times] == [(tue, 14), (NEXT_MONDAY + timedelta(days=3), 14)]
    # Nothing that day: the desk's own hour.
    assert clips.place(1, week_of=NEXT_MONDAY, tz=CHICAGO, post_hour=11, at=at, busy=[])[0].hour == 11
    # The desk posts at 15:00: the next free hour three hours on.
    at15 = [b.replace(hour=15) for b in busy]
    assert clips.place(1, week_of=NEXT_MONDAY, tz=CHICAGO, post_hour=15, at=at, busy=at15)[0].hour == 18
    # The desk's last hour taken: 3:00 PM, the desk's other hour.
    at21 = [b.replace(hour=21) for b in busy]
    assert clips.place(1, week_of=NEXT_MONDAY, tz=CHICAGO, post_hour=21, at=at, busy=at21)[0].hour == 15
    # A week planned on Wednesday afternoon gets the days it has left, at least an hour away.
    wed = datetime(2026, 10, 14, 14, tzinfo=CHICAGO)
    left = clips.place(2, week_of=NEXT_MONDAY, tz=CHICAGO, post_hour=11, at=wed, busy=busy)
    assert [t.date().isoformat() for t in left] == ['2026-10-15', '2026-10-14']
    assert all(t > wed + bm.SLOT_AFTER for t in left)
    # No room left: fewer, never a crowded day.
    full = [datetime.combine(NEXT_MONDAY + timedelta(days=i), datetime.min.time().replace(hour=h), CHICAGO)
            for i in range(5) for h in range(6, 22)]
    assert clips.place(2, week_of=NEXT_MONDAY, tz=CHICAGO, post_hour=11, at=at, busy=full) == []


def test_each_disqualifier_keeps_a_clip_out(c):
    good, failed_pub = make_clip(1, score=0.2), make_clip(2, score=0.1)
    c.clips += [good, failed_pub,
                make_clip(3, score=0.99, status='processing'),         # not ready
                make_clip(4, score=0.98, kept='skipped'),              # skipped
                make_clip(5, score=0.97, kept=None),                   # never kept
                make_clip(6, score=0.96, approved=False),              # not approved
                make_clip(7, score=0.95, changed=True),                # approved, then changed
                make_clip(8, score=0.94, removed=True),                # no longer stored
                make_clip(9, score=0.93),                              # already posted
                make_clip(10, score=0.92),                             # in a waiting post
                make_clip(11, score=0.91),                             # only a wide cover
                make_clip(12, score=0.90),                             # its story cover is still being made
                make_clip(13, score=0.89, biz=BIZ)]                    # another business's
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13):
        c.covers.append(make_cover(clip_id(n)))
    c.covers += [make_cover(clip_id(11), 'wide'), make_cover(clip_id(12), status='queued')]
    c.pubs += [publication(clip_id(9)), publication(clip_id(2), status='failed')]   # a failed one is not posted
    c.db.posts['owner-post'] = {'id': 'owner-post', 'business_id': PRO, 'run_id': None, 'status': 'approved', 'source': 'owner',
                                'media': {'clip_id': clip_id(10)}, 'run_at': '2026-10-09T16:00:00Z'}
    week(c)
    assert {p['media']['clip_id'] for p in clip_posts(c)} == {clip_id(1), clip_id(2)}
    record = run_of(c)['design']['clips']
    assert record['state'] == 'ok' and record['eligible'] == 2
    assert {(x['clip_id'], x['why']) for x in record['skipped']} == {
        (clip_id(7), 'changed'), (clip_id(9), 'posted'), (clip_id(10), 'in_a_post'),
        (clip_id(11), 'no_cover'), (clip_id(12), 'no_cover')}
    # The others are never even read: the query asks for ready, kept, approved, stored clips of this business.
    query = reads_of(c, '/media_assets')[0]
    for part in (f'business_id=eq.{PRO}', 'kind=eq.clip', 'status=eq.ready', 'decision=eq.kept',
                 'approval=not.is.null', 'source_removed_at=is.null'):
        assert part in query


@pytest.mark.parametrize('over, why', [
    ({'status': 'processing'}, 'not_ready'), ({'kind': 'source'}, 'not_ready'),
    ({'source_removed_at': '2026-10-06T00:00:00Z'}, 'not_stored'), ({'decision': 'skipped'}, 'not_kept'),
    ({'decision': None}, 'not_kept'), ({'approval': None}, 'unapproved'),
    ({'configuration': {'caption': 'changed after approval'}}, 'changed'), ({'business_id': BIZ}, 'not_this_business'),
])
def test_each_disqualifier_by_itself(over, why):
    row = {**make_clip(1), **over}
    assert clips.problem(make_clip(1), PRO) is None
    assert clips.problem(row, PRO) == why


def test_a_clip_in_an_open_week_is_not_picked_again_and_a_posted_one_counts(c):
    two_clips(c)
    c.clips.append(make_clip(3, score=0.1))
    c.covers.append(make_cover(clip_id(3)))
    week(c)                                                               # next week: A and B
    assert {p['media']['clip_id'] for p in clip_posts(c)} == {clip_id(1), clip_id(2)}
    first = run_of(c)['id']
    c.now = THU + timedelta(days=7)                                      # a week on: plan the week after
    week(c)
    later = [p for p in clip_posts(c) if p['run_id'] != first]
    assert [p['media']['clip_id'] for p in later] == [clip_id(3)]        # A and B wait in an open week
    # A clip posted through Chief's post_clip or the clip screen counts as posted;
    # a post the owner skipped, or one that failed, does not hold its clip.
    for p in c.db.posts.values():
        if p.get('media', {}).get('clip_id') == clip_id(1):
            p['status'] = 'cancelled'
        if p.get('media', {}).get('clip_id') == clip_id(3):
            p['status'] = 'failed'
    c.pubs.append(publication(clip_id(3)))
    c.now = THU + timedelta(days=14)
    week(c)
    newest = max(c.db.runs.values(), key=lambda r: r['week_of'])
    assert [p['media']['clip_id'] for p in clip_posts(c) if p['run_id'] == newest['id']] == [clip_id(1)]


def test_a_replan_picks_its_own_clips_again_and_retires_the_old_drafts(c):
    two_clips(c)
    week(c)
    settle(c)
    old = {p['id'] for p in clip_posts(c)}
    c.now += timedelta(minutes=10)
    assert ask(c).status_code == 202
    run(plan.manual_tick(c.now))
    fresh = clip_posts(c, status='draft')
    assert {p['media']['clip_id'] for p in fresh} == {clip_id(1), clip_id(2)}
    assert not ({p['id'] for p in fresh} & old)
    assert all(c.db.posts[i]['status'] == 'cancelled' for i in old)
    # A worker that stopped after saving and is run again keeps this attempt's clips.
    r = run_of(c)
    again = run(plan.run_week(PRO, trigger='manual', run={**r, 'status': 'running'}))
    assert again['resumed'] and {p['id'] for p in clip_posts(c, status='draft')} == {p['id'] for p in fresh}


# ── where, and with which cover ───────────────────────────────────────

def test_targets_take_every_video_network_and_skip_an_account_that_cannot(c):
    two_clips(c)
    c.svc.connections.append(connection(str(uuid4()), 'bluesky', biz=PRO))   # not a network clips go to
    week(c)
    for p in clip_posts(c):
        assert {t['platform'] for t in p['targets']} == {'facebook', 'instagram', 'tiktok', 'youtube'}
    assert run_of(c)['design']['clips']['left_out'][0]['platform'] == 'bluesky'


def test_the_desks_own_accounts_are_kept_tiktok_included(c):
    two_clips(c)
    c.db.desks[PRO]['connection_ids'] = [PRO_FB, TIKTOK]
    week(c)
    assert {t['platform'] for p in clip_posts(c) for t in p['targets']} == {'facebook', 'tiktok'}
    assert {t['platform'] for p in posts_of(c) if p['source'] == 'plan' for t in p['targets']} == {'facebook'}


def test_the_cover_on_each_network_is_clip_postings():
    targets = [{'platform': p} for p in ('instagram', 'facebook', 'tiktok', 'youtube', 'x', 'threads',
                                         'pinterest', 'linkedin')]
    both = clips.covers_by_network(targets, {'story': 'S', 'wide': 'W'})
    assert both['linkedin'] == {'shape': 'wide', 'image_id': 'W'}
    assert all(both[p] == {'shape': 'story', 'image_id': 'S'} for p in both if p != 'linkedin')
    story = clips.covers_by_network(targets, {'story': 'S'})
    assert set(v['shape'] for v in story.values()) == {'story'}
    wide = clips.covers_by_network(targets, {'wide': 'W'})
    assert wide['linkedin'] == {'shape': 'wide', 'image_id': 'W'} and wide['tiktok'] is None


def test_the_run_records_the_cover_each_network_shows(c):
    two_clips(c)
    week(c)
    picked = run_of(c)['design']['clips']['picked'][0]
    story = cover_of(c, 1, 'story')
    assert picked['covers'] == {p: {'shape': 'story', 'image_id': story}
                                for p in ('facebook', 'instagram', 'tiktok', 'youtube')}


# ── the approval binds the clip as it is ──────────────────────────────

def _approved_clip_post(c, n=1):
    p = next(p for p in clip_posts(c) if p['media']['clip_id'] == clip_id(n))
    assert run(store.approve(PRO, [{'id': p['id'], 'revision': p['revision'], 'content_hash': p['content_hash']}],
                             actor=PRO_OWNER)) == 1
    row = c.db.posts[p['id']]
    row['status'] = 'dispatching'                                         # what marketing_claim_due hands over
    c.now = _when(row['run_at']) + timedelta(minutes=1)
    return row


def test_the_fingerprint_is_in_the_content_hash(c):
    two_clips(c)
    week(c)
    p = clip_posts(c)[0]
    changed = copy.deepcopy(p)
    changed['media']['clip_fingerprint'] = 'f' * 64
    assert store.digest(changed) != p['content_hash']


@pytest.mark.parametrize('how', ['changed', 'approved_again', 'skipped'])
def test_a_clip_that_changed_after_the_post_was_approved_is_refused_at_send(c, monkeypatch, how):
    two_clips(c)
    week(c)
    row = _approved_clip_post(c)
    monkeypatch.setattr(d, 'now', lambda: c.now)
    clip = next(x for x in c.clips if x['id'] == clip_id(1))
    if how in ('changed', 'approved_again'):
        clip['configuration'] = {**clip['configuration'], 'caption': 'New words after the post was approved.'}
        if how == 'approved_again':
            clip['approval'] = {**clip['approval'], 'fingerprint': media_library.fingerprint(clip)}
    else:
        clip['decision'] = 'skipped'                                      # taken off the kept clips since

    async def never(*a, **k):
        raise AssertionError('a changed clip is never handed to the posting door')
    monkeypatch.setattr(clip_posting, 'post_clip_for', never)
    out = run(d.dispatch(copy.deepcopy(row)))
    assert out['status'] == 'failed'
    assert ('changed after the post was approved' in out['error'] if how != 'skipped'
            else out['error'] == d.UNKEPT)
    assert c.db.posts[row['id']]['status'] == 'failed'


def test_an_unchanged_clip_goes_through_post_clip_for_with_its_fingerprint_and_covers(c, monkeypatch):
    two_clips(c)
    week(c)
    row = _approved_clip_post(c)
    monkeypatch.setattr(d, 'now', lambda: c.now)
    sent, pub = [], str(uuid4())

    async def post_clip_for(biz, user, cid, **kw):
        sent.append({'biz': biz, 'user': user, 'clip': cid, **kw})
        c.pubs.append({**publication(cid, status='scheduled'), 'id': pub, 'provider_post_id': 'pfm_1'})
        return {'ok': True, 'publication': {'id': pub}}
    monkeypatch.setattr(clip_posting, 'post_clip_for', post_clip_for)
    out = run(d.dispatch(copy.deepcopy(row)))
    assert out['status'] == 'submitted' and out['publication_id'] == pub
    call = sent[0]
    assert call['user'] == PRO_OWNER and call['clip'] == clip_id(1)
    assert call['fingerprint'] == row['media']['clip_fingerprint'] and call['caption'] == row['publish_text']
    assert call['covers'] == row['media']['covers'] and call['request_id'] == d.request_id(row)
    assert {str(t) for t in call['connection_ids']} == {t['connection_id'] for t in row['targets']}


# ── who gets clips ────────────────────────────────────────────────────

def test_only_the_solutionist_plan_takes_clips():
    for tier in ('starter', 'solo', 'booked', 'boss', 'professional', None):
        assert not clips.takes_clips(business(PRO, PRO_OWNER, tier=tier)), tier
    assert clips.takes_clips(business(PRO, PRO_OWNER, tier='practice'))
    assert 'ai_clips' not in feature_gates.plan_features('boss')            # Boss: "No Video Clips"


def test_professional_boss_and_the_suggestion_never_get_clips(c):
    two_clips(c)
    c.clips += [make_clip(5, biz=BOSS), make_clip(6, biz=BIZ)]
    c.covers += [make_cover(clip_id(5), biz=BOSS), make_cover(clip_id(6), biz=BIZ)]
    c.svc.businesses[PRO]['comp_tier'] = 'professional'
    week(c)
    assert len(posts_of(c)) == 5 and clip_posts(c) == [] and 'clips' not in run_of(c)['design']
    # Boss without a live chair calendar plans the plain week: no clips either.
    c.svc.businesses[BOSS]['settings']['booking_page'] = {'published': False}
    assert plan.run_kind(c.svc.businesses[BOSS]) == ('week', None)
    assert week(c, BOSS)['status'] == 'succeeded'
    assert posts_of(c, BOSS) and clip_posts(c, BOSS) == []
    # Starter gets its one suggestion, never a clip.
    assert run(plan.run_suggestion(BIZ, trigger='scheduled'))['status'] == 'succeeded'
    assert [p['source'] for p in posts_of(c, BIZ)] == ['suggestion']
    assert reads_of(c, '/media_assets') == [] and reads_of(c, '/social_publications') == []


def test_no_eligible_clip_and_the_week_is_exactly_b9s(c):
    c.clips.append(make_clip(1, kept='skipped'))
    c.covers.append(make_cover(clip_id(1)))
    c.svc.businesses[PRO]['comp_tier'] = 'professional'
    c.reply = week_reply()
    week(c)
    b9 = {p['id']: {k: v for k, v in p.items() if k != 'created_at'} for p in posts_of(c)}
    b9_call = c.calls[0]
    for store_rows in (c.db.posts, c.db.runs):
        store_rows.clear()
    c.calls.clear()
    c.svc.images.clear()
    c.svc.businesses[PRO]['comp_tier'] = 'practice'
    week(c)
    assert {p['id']: {k: v for k, v in p.items() if k != 'created_at'} for p in posts_of(c)} == b9
    assert c.calls == [b9_call]
    assert run_of(c)['design']['clips'] == {'state': 'ok', 'per_week': 2, 'eligible': 0, 'picked': [],
                                            'skipped': []}


@pytest.mark.parametrize('table', ['/media_assets', '/social_publications', 'director->>clip_id'])
def test_a_read_that_fails_puts_no_clip_in_the_week(c, table):
    two_clips(c)
    c.svc.fail = (table,)
    out = week(c)
    assert out['status'] == 'succeeded' and len(posts_of(c)) == 5 and clip_posts(c) == []
    assert run_of(c)['design']['clips']['state'] == 'unreadable'


# ── the caption ───────────────────────────────────────────────────────

def test_a_clip_caption_takes_at_most_three_hashtags_and_a_broken_one_costs_only_that_clip(c):
    two_clips(c)
    c.reply = clip_reply({6: {'text': 'A calmer week starts here. #planning #coaching #calm #week'},
                          7: {'text': 'Seven days, one quiet hour: watch how it changes the week. #planning'}})
    week(c)
    got = clip_posts(c)
    assert [p['media']['clip_id'] for p in got] == [clip_id(2)]           # slot 6 broke a rule
    assert got[0]['caption'].count('#') == 1
    dropped = {d['slot']: d for d in run_of(c)['dropped']}
    assert dropped[6]['reason'] == 'more than 3 hashtags' and dropped[6]['clip_id'] == clip_id(1)
    assert len(posts_of(c)) == 6 and len(c.creates) == 5                 # the five flyer posts stand
    picked = {x['clip_id']: x for x in run_of(c)['design']['clips']['picked']}
    assert picked[clip_id(1)]['saved'] is False and picked[clip_id(2)]['saved'] is True


def test_clip_captions_meet_the_business_checks():
    profile = prof.build_profile(business(PRO, PRO_OWNER, tier='practice'), hosts={'pro-shop.mysolutionist.app'})
    facts = plan.engine.verified_facts(FACTS)
    slot = {'slot': 6, 'clip_id': clip_id(1), 'clip': {'title': 'x'}}

    def said(text):
        return clips.judge({'captions': [{'slot': 6, 'text': text}]}, slot, facts, profile)
    assert said('A calmer week starts with one quiet hour. #planning #coaching #calm')[0]
    assert said('A calmer week starts with one quiet hour. #a #b #c #d')[2][0]['reason'] == 'more than 3 hashtags'
    assert 'number' in said('Three steps, 7 days: a calmer week starts with one quiet hour.')[2][0]['reason']
    assert 'link' in said('A calmer week starts here: https://example.com/watch')[2][0]['reason']
    assert said('A calmer week starts here: https://pro-shop.mysolutionist.app/book')[0]
    assert said('$150 for a session that plans your week')[0]              # a stated price
    assert clips.judge({'captions': []}, slot, facts, profile)[2][0]['reason'] == 'missing'


# ── telling the owner ─────────────────────────────────────────────────

def test_the_owner_is_told_once_and_the_clips_are_named(c):
    two_clips(c)
    week(c)
    settle(c)
    assert len(c.pushes) == 1 and len(c.svc.notifications) == 1
    push = c.pushes[0]
    assert push['title'] == 'Chief planned next week: 7 posts wait for your OK'
    assert push['body'] == ('5 have a flyer and 2 are your own video clips, with their covers. '
                            'Nothing posts until you approve them.')


def test_the_weeks_words_with_and_without_clips():
    assert plan.week_words(5, 0, 'next week') == {
        'title': 'Chief planned next week: 5 posts wait for your OK',
        'body': 'Each has its flyer. Nothing posts until you approve them.'}
    assert plan.week_words(6, 1, 'next week', 1)['body'] == (
        '4 have a flyer, 1 goes as words only and 1 is your own video clip, with its cover. '
        'Nothing posts until you approve them.')
    assert plan.week_words(1, 0, 'this week', 1)['body'] == (
        'It is your own video clip, with its cover. Nothing posts until you approve it.')


def test_the_owners_request_says_clips_come_with_the_week(c):
    r = ask(c)
    assert r.status_code == 202 and r.json()['message'] == plan.WEEK_CLIPS_QUEUED
    rate_limit._buckets.clear()


# ── docs and the log ──────────────────────────────────────────────────

def test_the_docs_and_worklog_say_what_was_built():
    doc = (ROOT / 'docs' / 'MARKETING_DESK.md').read_text(encoding='utf-8')
    assert '### Clips in the week (B12)' in doc
    assert doc.index('### The barber-sized week (B11)') < doc.index('### Clips in the week (B12)')
    log = (ROOT / 'worklog' / '2026-10-08-marketing-clips.md').read_text(encoding='utf-8')
    head = log.split('---')[1]
    assert re.search(r'^agent: Claude Code \(Claude Opus 5\.5\)$', head, re.M)
    assert re.search(r'^migrations: \[\]$', head, re.M)
    import worklog
    entry = worklog.parse_entry(log, 'kmj-intake-server', 'worklog/2026-10-08-marketing-clips.md')
    assert entry and entry['title'] and entry['date'] == '2026-10-08' and entry['migrations'] == []
    assert entry['asked'] == "This will work. let's build this."
    assert entry['agent'] == 'Claude Code (Claude Opus 5.5)'
