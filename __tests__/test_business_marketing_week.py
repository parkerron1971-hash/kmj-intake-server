"""The weekly plan (business_marketing_planner.py, B9).

Five drafts saved at once while their flyers are made; a designing post is
never approved; a finished flyer is attached (a new revision and content
hash, still a draft); a late, failed or capped flyer leaves its post words
only with Instagram left out, never holding up the week; the owner is told
once, after every post has settled; the flyers are included in the plan
(no credits, still metered and spend-guarded) and nothing a request or Chief
sends can say so; replans; plays lean on the business's own results only
with 3 samples; the openings level (Boss) gets its open-chairs week instead
(B11); the fan-out counts a week's cost against the spend headroom.

No network: the marketing tables, the claim and approve RPCs, the
service-role reads, the model, Image Studio and the push sender are fakes at
the seams the planner calls (the B8 suite's, extended).
"""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '__tests__'))

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import business_marketing as bm
import business_marketing_engine as eng
import business_marketing_outcomes as outcomes
import business_marketing_planner as plan
import business_marketing_store as store
import creative_director as cd
import image_studio as images
import llm_call
import marketing_profile as prof
import marketing_signals as msig
import push_notifications
import rate_limit
import sb_clients
import social_publish_router as social
import spend_guard
from auth_supabase import require_user
from creative_director_models import DesignRequest

REAL_CREATE = images.create

from test_business_marketing_planner import (  # noqa: E402  (the B8 suite's fakes)
    BIZ, CHICAGO, FACTS, NEXT_MONDAY, OWNER, PRO, PRO_OWNER, THU, FakeService, FakeStore, Reply, _when,
    business, connection, quiet_signals, select)

run = asyncio.run

IG = 'c0000000-0000-4000-8000-0000000000a1'
PRO_FB = 'c0000000-0000-4000-8000-0000000000a2'
TIKTOK = 'c0000000-0000-4000-8000-0000000000a3'
MEMBER = '22222222-2222-4222-8222-222222222222'
BOSS = '5b5b5b5b-5b5b-4b5b-8b5b-5b5b5b5b5b5b'
BOSS_OWNER = '66666666-6666-4666-8666-666666666666'


def week_reply(n=5, over=None):
    over = over or {}
    texts = ['A clear plan beats a busy week. Here is one small habit that keeps Mondays calm. #coaching',
             'Our strategy session is where a scattered plan becomes a clear next step. #smallbusiness',
             'Write down the one thing that matters most tomorrow, before you close the laptop tonight.',
             'We are a coaching practice in Cleveland that helps owners plan the week ahead with less stress.',
             'Try this: block one quiet hour for planning, and guard it like a client meeting. #planning']
    out = []
    for i in range(n):
        item = {'slot': i + 1, 'text': texts[i],
                'flyer': {'headline': ['Plan the week ahead', 'A clear next step', 'One thing first',
                                       'Meet your coach', 'Guard one hour'][i],
                          'line': 'One small change makes the whole week calmer.', 'cta': 'Book a time'}}
        item.update(over.get(i + 1, {}))
        out.append(item)
    return {'captions': out}


class WeekStore(FakeStore):
    """B8's store, plus a bulk insert (all or nothing) and marketing_approve as the migration writes it."""

    async def request(self, method, path, body=None):
        table = path.split('?', 1)[0]
        if table == '/rpc/marketing_approve':
            if any(f in path for f in self.fail):
                raise store.StoreUnavailable('down')
            self.writes.append((method, path, copy.deepcopy(body)))
            return self.approve(body)
        if method == 'POST' and table == '/marketing_posts' and isinstance(body, list):
            if any(f in path for f in self.fail + self.fail_writes):
                raise store.StoreUnavailable('Marketing storage is unavailable. Please retry.')
            self.writes.append((method, path, copy.deepcopy(body)))
            assert len({tuple(sorted(b)) for b in body}) == 1, 'a bulk insert needs the same keys in every row'
            if any(str(b['id']) in self.posts for b in body):
                raise store.StoreConflict('The post changed. Refresh and review again.')
            out = []
            for b in body:
                row = {'approved_hash': None, 'approved_by': None, **copy.deepcopy(b),
                       'created_at': self.clock().isoformat()}
                assert row['status'] in store.POST_STATUSES and row['source'] in store.POST_SOURCES
                assert row['design_status'] in store.DESIGN_STATUSES
                self.posts[str(b['id'])] = row
                out.append(copy.deepcopy(row))
            return out
        return await super().request(method, path, body)

    def approve(self, body):
        n = 0
        for item in sorted(body['p_items'], key=lambda i: i['id']):
            r = self.posts.get(item['id'])
            if not r or r['business_id'] != body['p_business_id']:
                raise store.StoreConflict('A post changed or its time passed; refresh and review again')
            if r['design_status'] == 'designing':
                raise store.StoreConflict('A flyer is still being made; approve that post when it is ready')
            if (r['status'] != 'draft' or r['revision'] != item['revision']
                    or r['content_hash'] != item['content_hash'] or _when(r['run_at']) <= self.clock()):
                raise store.StoreConflict('A post changed or its time passed; refresh and review again')
            r.update(status='approved', approved_hash=r['content_hash'], approved_by=body['p_actor'],
                     approved_via=body['p_via'])
            n += 1
        return n


class WeekService(FakeService):
    """B8's service-role reads, plus image_artworks (the flyers)."""

    def __init__(self):
        super().__init__()
        self.images = []

    def get(self, path):
        if path.split('?', 1)[0] == '/image_artworks':
            self.reads.append(path)
            if any(f in path for f in self.fail):
                return None
            return copy.deepcopy(select(self.images, path))
        return super().get(path)


SPEC_KEYS = ('version', 'scope', 'goal', 'copy', 'references', 'owner_request', 'owner_context', 'facts',
             'preferences', 'max_renders', 'phase', 'attempts', 'review')


@pytest.fixture
def w(monkeypatch):
    for name in ('MARKETING_MAX_PER_TICK', 'BILLING_ENFORCE', 'PLATFORM_DEFAULT_TZ', 'MARKETING_DESK_PUBLISHING',
                 'MARKETING_DESIGNS_AT_ONCE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('MARKETING_DESK', '*')
    monkeypatch.setenv('POST_FOR_ME_API_KEY', 'pfm_test_key')
    monkeypatch.setenv('POST_FOR_ME_PILOT_BUSINESSES', '*')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    state = SimpleNamespace(now=THU, user=PRO_OWNER, share=0.0, cap=50.0, over=set(), reply=week_reply(),
                            calls=[], pushes=[], signals=quiet_signals(business_id=PRO), creates=[], specs=[],
                            create_error={}, scores={}, prepared=[])
    db, svc = WeekStore(lambda: state.now), WeekService()
    state.db, state.svc = db, svc
    svc.connections = [connection(PRO_FB, 'facebook', biz=PRO), connection(IG, 'instagram', biz=PRO),
                       connection(TIKTOK, 'tiktok', biz=PRO), connection(str(uuid4()), 'facebook', biz=BIZ)]
    svc.businesses[BOSS] = {**business(BOSS, BOSS_OWNER, name='Fade Lab', tier='boss'), 'type': 'barbershop'}
    svc.businesses[BOSS]['settings']['booking_page'] = {'published': True}
    svc.modules.append({'id': str(uuid4()), 'business_id': BOSS, 'archetype': 'booking_calendar', 'is_active': True})
    svc.connections.append(connection(str(uuid4()), 'facebook', biz=BOSS))
    svc.sites.append({'business_id': BOSS, 'slug': 'fade-lab', 'status': 'published', 'site_config': {},
                      'updated_at': '2026-10-01T00:00:00Z'})
    monkeypatch.setattr(store, 'request', db.request)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', svc.get)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', svc.post)
    monkeypatch.setattr(bm, 'now', lambda: state.now)
    monkeypatch.setattr(plan, '_now', lambda: state.now)

    async def read_signals(bid, *, now=None, business=None, tz=None):
        return copy.deepcopy({**state.signals, 'business_id': bid})

    async def read_profile(bid, *, business=None):
        site = next((x for x in svc.sites if x['business_id'] == bid), None)
        import business_marketing_links as links
        return prof.build_profile(business, hosts=links.own_hosts(links.site_from_row(site)), tz=CHICAGO)
    monkeypatch.setattr(msig, 'read_signals', read_signals)
    monkeypatch.setattr(prof, 'read_profile', read_profile)
    monkeypatch.setattr(cd, 'business_facts', lambda bid: copy.deepcopy(FACTS))

    async def play_scores(bid, *, now=None):
        return copy.deepcopy(state.scores)
    monkeypatch.setattr(outcomes, 'play_scores', play_scores)

    async def apost(client, payload=None, **kw):
        state.calls.append((copy.deepcopy(payload), kw))
        return Reply({'content': [{'type': 'text', 'text': json.dumps(state.reply)}],
                      'usage': {'input_tokens': 3000, 'output_tokens': 900}})
    monkeypatch.setattr(llm_call, 'apost', apost)

    async def biz_under_actor(client, business_id):
        actor = images.build_actor.get()
        assert actor == {'business_id': str(business_id), 'user_id': svc.businesses[str(business_id)]['owner_id']}
        return {'id': str(business_id), 'owner_id': actor['user_id'], 'name': 'x', 'settings': {}}
    monkeypatch.setattr(images, 'business', biz_under_actor)

    async def prepare_for_business(client, biz, req, *, owner_request, owner_context='', clip_id=None):
        state.prepared.append({'goal': req.goal, 'copy': list(req.exact_copy), 'size': req.size,
                               'quality': req.quality, 'owner_request': owner_request})
        return {'version': 1, 'scope': 'business', 'goal': req.goal, 'copy': list(req.exact_copy), 'references': [],
                'owner_request': owner_request, 'owner_context': owner_context, 'facts': FACTS, 'preferences': {},
                'max_renders': 2, 'phase': 'queued', 'attempts': 0, 'review': None}
    monkeypatch.setattr(cd, 'prepare_for_business', prepare_for_business)

    async def create(req, client, *, director=None):
        state.creates.append({'request_id': str(req.request_id), 'size': req.size, 'quality': req.quality,
                              'director': copy.deepcopy(director), 'actor': images.build_actor.get()})
        error = state.create_error.get(len(state.creates))
        if error:
            raise error
        if not any(i['id'] == str(req.request_id) for i in svc.images):
            svc.images.append({'id': str(req.request_id), 'business_id': str(req.business_id), 'status': 'queued',
                               'storage_path': None, 'created_at': state.now.isoformat(), 'phase': 'queued',
                               'review': None})
        return {'id': str(req.request_id), 'status': 'queued'}
    monkeypatch.setattr(images, 'create', create)

    import chief_flyer_composer as composer

    async def compose(client, biz, action, request_id):          # the suggestion's free flyer (B8)
        return {'image': {'id': str(uuid4())}}
    monkeypatch.setattr(composer, 'compose', compose)

    async def no_send(*a, **k):
        raise AssertionError('the planner never sends')
    monkeypatch.setattr(social, 'send_post', no_send)
    monkeypatch.setattr(push_notifications, 'send_to_user',
                        lambda user_id, **kw: state.pushes.append({'user': user_id, **kw}) or 1)
    monkeypatch.setattr(spend_guard, 'platform_share', lambda force=False: state.share)
    monkeypatch.setattr(spend_guard, 'platform_cap_usd', lambda: state.cap)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda business_id=None: business_id in state.over)
    rate_limit._buckets.clear()

    for bid in (BIZ, PRO, BOSS):
        db.desks[bid] = {'business_id': bid, 'plan_enabled': True, 'paused': False, 'connection_ids': [],
                         'post_hour': 11}
    api = FastAPI()
    api.include_router(plan.router)
    api.include_router(bm.router)
    api.dependency_overrides[require_user] = lambda: SimpleNamespace(id=state.user, email='x@example.com',
                                                                     role='authenticated')
    state.client = TestClient(api)
    return state


def posts_of(w, bid=PRO, status=None):
    return sorted((p for p in w.db.posts.values() if p['business_id'] == bid and (status is None or p['status'] == status)),
                  key=lambda p: p['run_at'])


def run_of(w, bid=PRO):
    return next(r for r in w.db.runs.values() if r['business_id'] == bid)


def finish(w, ids=None, *, phase='complete', status='ready', review=None):
    """The Director finished these flyers (all of them by default)."""
    for image in w.svc.images:
        if ids is None or image['id'] in ids:
            image.update(status=status, phase=phase, review=review,
                         storage_path=f"{image['business_id']}/{image['id']}-1.png" if status == 'ready' else None)


def flyer_of(post):
    return str(plan.flyer_request_id(post['run_id'], post['id']))


def week(w):
    return run(plan.run_week(PRO, trigger='scheduled'))


# ── five drafts, saved at once ────────────────────────────────────────

def test_a_professional_week_is_five_drafts_saved_at_once_each_designing(w):
    out = week(w)
    assert out['status'] == 'succeeded' and out['week_of'] == NEXT_MONDAY.isoformat() and out['designing'] == 5
    inserts = [(m, p, b) for m, p, b in w.db.writes if m == 'POST' and p == '/marketing_posts']
    assert len(inserts) == 1 and isinstance(inserts[0][2], list) and len(inserts[0][2]) == 5    # one write
    posts = posts_of(w)
    r = run_of(w)
    assert r['kind'] == 'week' and r['status'] == 'succeeded' and r['post_ids'] == [p['id'] for p in inserts[0][2]]
    assert len(posts) == 5 and {p['source'] for p in posts} == {'plan'}
    assert {p['status'] for p in posts} == {'draft'} and {p['design_status'] for p in posts} == {'designing'}
    for i, p in enumerate(posts):
        local = _when(p['run_at']).astimezone(CHICAGO)
        assert local.date() == NEXT_MONDAY + timedelta(days=i) and local.hour == 11      # Mon-Fri at the desk's hour
        assert p['run_id'] == r['id'] and p['play_id'] in eng.PLAYS
        assert p['id'] == plan.week_post_id(r['id'], 1, i + 1)
        assert p['content_hash'] == store.digest(p) and p['media'] == {}
        assert p['tracked_url'] and p['link_code'] == store.link_code(p['id']) and '/go/' in p['publish_text']
        # Instagram waits for its flyer; TikTok takes only videos, so it is left out.
        assert {t['platform'] for t in p['targets']} == {'facebook', 'instagram'}
    assert r['design']['left_out'] == [{'platform': 'tiktok', 'label': 'TikTok', 'username': 'kev.tiktok',
                                        'why': 'needs_video'}]
    assert [s['play_id'] for s in r['slots']] == [p['play_id'] for p in posts]
    assert r['design']['tell'] == 'pending' and len(r['design']['flyers']) == 5
    assert not any(path.startswith('/rpc/marketing_approve') for _, path, _ in w.db.writes)   # never approved here


def test_one_caption_call_metered_to_the_business_bills_nothing(w):
    week(w)
    assert len(w.calls) == 1
    payload, kw = w.calls[0]
    assert kw['task'] == plan.WEEK_TASK and kw['business_id'] == PRO and kw['units'] == 0
    asked = json.loads(payload['messages'][0]['content'])
    assert [s['slot'] for s in asked['slots']] == [1, 2, 3, 4, 5]


def test_every_flyer_is_a_director_design_under_the_owner_included_in_the_plan(w):
    out = week(w)
    posts = posts_of(w)
    assert len(w.creates) == 5
    for c, p in zip(w.creates, posts):
        assert c['request_id'] == flyer_of(p) == str(uuid5(UUID(p['run_id']), f"flyer:{p['id']}"))
        assert c['size'] == '1088x1360' and c['quality'] == 'high'                 # 4:5, Instagram-safe
        assert c['actor'] == {'business_id': PRO, 'user_id': PRO_OWNER}       # bound for the design only
        assert c['director']['billing'] == cd.INCLUDED and cd.included(c['director'])
    assert images.build_actor.get() is None
    goal = w.prepared[0]['goal']
    assert 'Portrait 4:5' in goal and 'a twentieth of the width' in goal and 'brand colours' in goal
    assert w.prepared[0]['size'] == '1088x1360'
    assert w.prepared[0]['copy'][-1] == 'Pro Shop'                           # the business's own name, small
    assert out['designing'] == 5


def test_caption_checks_are_the_businesses_a_broken_one_costs_only_its_slot(w):
    w.reply = week_reply(over={2: {'text': 'Over 500 owners planned with us this year. Book your session today.'},
                               4: {'flyer': {'headline': 'Save 40 percent', 'line': 'One small change this week.',
                                             'cta': 'Book'}}})
    week(w)
    posts = posts_of(w)
    assert len(posts) == 4                                                    # slot 2's caption broke a rule
    assert all('500' not in p['caption'] for p in posts)
    no_flyer = [p for p in posts if p['design_status'] == 'failed']
    assert len(no_flyer) == 1 and "didn't pass" in no_flyer[0]['error']       # slot 4: words only, no picture
    assert {t['platform'] for t in no_flyer[0]['targets']} == {'facebook'}
    assert 'Instagram is left out' in no_flyer[0]['error']
    assert len(w.creates) == 3
    assert any(d['slot'] == 2 for d in run_of(w)['dropped'])


def test_every_caption_broken_saves_nothing(w):
    w.reply = {'captions': [{'slot': n, 'text': 'Call 555 0100 now'} for n in range(1, 6)]}
    out = week(w)
    assert out['status'] == 'failed' and posts_of(w) == [] and w.creates == []
    assert run_of(w)['error'] == plan.WEEK_CAPTIONS_BROKE


def test_a_taken_hour_moves_to_three_and_a_monday_catch_up_gets_the_days_left(w):
    taken = datetime(2026, 10, 13, 11, tzinfo=CHICAGO)                        # Tuesday 11:00 already has a post
    w.db.posts['x'] = {'id': 'x', 'business_id': PRO, 'status': 'draft', 'run_at': taken.isoformat()}
    times = run(plan.week_times(PRO, CHICAGO, 11, NEXT_MONDAY, THU))
    assert [t.hour for t in times] == [11, 15, 11, 11, 11]
    wednesday = datetime(2026, 10, 7, 14, tzinfo=CHICAGO).astimezone(timezone.utc)
    left = run(plan.week_times(PRO, CHICAGO, 11, NEXT_MONDAY - timedelta(days=7), wednesday))
    assert [t.date().isoformat() for t in left] == ['2026-10-08', '2026-10-09']


def test_a_week_already_planned_is_left_alone(w):
    week(w)
    assert week(w) == {'status': 'exists', 'week_of': NEXT_MONDAY.isoformat()}
    assert len(w.creates) == 5 and len(w.calls) == 1


# ── a designing post cannot be approved ───────────────────────────────

def test_the_rpc_refuses_a_designing_post():
    sql = (ROOT / 'supabase' / 'APPLY-2026-10-07-marketing-suite.sql').read_text(encoding='utf-8')
    body = sql[sql.index('CREATE OR REPLACE FUNCTION public.marketing_approve'):]
    body = body[:body.index('END $$;')]
    assert "IF r.design_status = 'designing' THEN" in body and 'RAISE EXCEPTION' in body


def test_the_api_says_so_before_the_rpc(w):
    week(w)
    p = posts_of(w)[0]
    item = {'id': p['id'], 'revision': p['revision'], 'content_hash': p['content_hash']}
    r = w.client.post(f'/marketing/{PRO}/approve', json={'items': [item]})
    assert r.status_code == 409 and r.json()['detail'] == bm.DESIGNING
    assert not any(path.startswith('/rpc/marketing_approve') for _, path, _ in w.db.writes)
    assert posts_of(w)[0]['status'] == 'draft'
    # and the RPC itself refuses it too
    with pytest.raises(store.StoreConflict, match='still being made'):
        run(store.approve(PRO, [item], actor=PRO_OWNER))


def test_a_designing_post_is_not_edited_skipped_or_posted_now(w, monkeypatch):
    week(w)
    p = posts_of(w)[0]
    monkeypatch.setenv('MARKETING_DESK_PUBLISHING', 'on')
    for path, body in (('/slot/edit', {'items': [{'id': p['id'], 'revision': 1}], 'caption': 'New words for it'}),
                       ('/slot/cancel', {'items': [{'id': p['id'], 'revision': 1}]}),
                       ('/post-now', {'items': [{'id': p['id'], 'revision': 1, 'content_hash': p['content_hash']}]})):
        r = w.client.post(f'/marketing/{PRO}{path}', json=body)
        assert r.status_code == 409 and 'still being made' in r.json()['detail'], path


# ── the flyers land ───────────────────────────────────────────────────

def test_a_finished_flyer_is_attached_rehashed_and_stays_a_draft(w):
    week(w)
    before = {p['id']: p['content_hash'] for p in posts_of(w)}
    finish(w)
    w.now += timedelta(minutes=6)
    out = run(plan.marketing_design_tick(w.now))
    assert out['attached'] == 5
    for p in posts_of(w):
        assert p['status'] == 'draft' and p['design_status'] == 'ready' and p['revision'] == 2
        assert p['media'] == {'artwork_ids': [flyer_of(p)]}
        assert p['content_hash'] == store.digest(p) != before[p['id']]
        assert p['approved_hash'] is None and p['error'] is None
        assert {t['platform'] for t in p['targets']} == {'facebook', 'instagram'}   # Instagram has its picture
    # and now the owner can approve the week, at the content they see
    items = [{'id': p['id'], 'revision': p['revision'], 'content_hash': p['content_hash']} for p in posts_of(w)]
    r = w.client.post(f'/marketing/{PRO}/approve', json={'items': items})
    assert r.status_code == 200 and r.json() == {'approved': 5}


def test_a_flyer_chiefs_check_was_unsure_about_says_so(w):
    week(w)
    first = posts_of(w)[0]
    finish(w, {flyer_of(first)}, phase='needs_review',
           review={'issues': ['Missing or incorrect wording: Book a time'], 'passed': False})
    run(plan.marketing_design_tick(w.now + timedelta(minutes=5)))
    p = posts_of(w)[0]
    assert p['design_status'] == 'ready' and p['media'] == {'artwork_ids': [flyer_of(p)]}
    assert 'Book a time' in p['error'] and 'before you approve' in p['error']


def test_twenty_minutes_without_a_flyer_and_the_post_goes_words_only(w):
    week(w)
    posts = posts_of(w)
    finish(w, {flyer_of(p) for p in posts[:4]})
    w.now += timedelta(minutes=19)
    run(plan.marketing_design_tick(w.now))
    late = posts_of(w)[4]
    assert late['design_status'] == 'designing' and w.pushes == []             # not yet: still inside 20 minutes
    w.now += timedelta(minutes=2)
    out = run(plan.marketing_design_tick(w.now))
    late = posts_of(w)[4]
    assert out['timed_out'] == 1
    assert late['status'] == 'draft' and late['design_status'] == 'failed' and late['media'] == {}
    assert {t['platform'] for t in late['targets']} == {'facebook'}           # Instagram dropped
    assert late['error'] == "The flyer wasn't ready in time, so this post goes as words only, and Instagram is left out."
    assert late['content_hash'] == store.digest(late) and late['revision'] == 2
    # the week was not held up: the owner hears about it the same tick
    assert len(w.pushes) == 1 and '1 goes as words only' in w.pushes[0]['body']


def test_a_flyer_that_never_started_or_failed_also_settles(w):
    week(w)
    posts = posts_of(w)
    w.svc.images = [i for i in w.svc.images if i['id'] != flyer_of(posts[0])]      # the worker died before it began
    finish(w, {flyer_of(posts[1])}, status='failed', phase='planning')
    finish(w, {flyer_of(p) for p in posts[2:]})
    w.now += timedelta(minutes=3)
    run(plan.marketing_design_tick(w.now))
    assert [p['design_status'] for p in posts_of(w)] == ['designing', 'failed', 'ready', 'ready', 'ready']
    assert "couldn't be made" in posts_of(w)[1]['error']
    w.now += timedelta(minutes=20)
    run(plan.marketing_design_tick(w.now))
    assert posts_of(w)[0]['design_status'] == 'failed' and len(w.pushes) == 1


def test_instagram_alone_keeps_its_place_and_the_note_asks_for_a_picture(w):
    w.svc.connections = [connection(IG, 'instagram', biz=PRO)]
    week(w)
    w.now += timedelta(minutes=21)
    run(plan.marketing_design_tick(w.now))
    p = posts_of(w)[0]
    assert p['design_status'] == 'failed' and [t['platform'] for t in p['targets']] == ['instagram']
    assert 'Instagram needs a picture' in p['error']
    item = {'id': p['id'], 'revision': p['revision'], 'content_hash': p['content_hash']}
    r = w.client.post(f'/marketing/{PRO}/approve', json={'items': [item]})
    assert r.status_code == 409 and 'Add a picture' in r.json()['detail']     # never approved to fail at send


def test_the_daily_design_limit_makes_that_post_words_only_now(w):
    w.create_error = {3: HTTPException(429, images.DAILY_LIMIT_REACHED)}
    out = week(w)
    assert out['status'] == 'succeeded' and out['designing'] == 4
    third = posts_of(w)[2]
    assert third['design_status'] == 'failed' and third['revision'] == 2      # right away, not after 20 minutes
    assert third['error'].startswith("This business reached today's limit on new pictures")
    assert {t['platform'] for t in third['targets']} == {'facebook'}
    assert run_of(w)['design']['flyers'][third['id']]['why'] == 'limit'
    assert [p['design_status'] for p in posts_of(w)].count('designing') == 4


def test_image_studio_answers_the_daily_limit_with_429(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': PRO, 'owner_id': PRO_OWNER}))
    reserved = []

    async def database(client, method, path, body=None, **kw):
        if method == 'GET' and path.startswith('/image_artworks?id=eq.'):
            return []
        if method == 'GET':
            assert 'model=not.is.null' in path and 'created_at=gte.' in path and '+' not in path
            assert f'id=neq.{req.request_id}' in path            # this request's own row never counts
            return [{'id': str(uuid4())} for _ in range(20)]
        reserved.append(path)
        return [{}]
    monkeypatch.setattr(images, 'db', database)
    req = images.CreateImage(business_id=PRO, request_id=uuid4(), prompt='A flyer', size='1024x1536')
    included = cd.include_in_plan({'scope': 'business', 'version': 1, 'max_renders': 2})
    for director in (None, included):        # the limit holds for a design included in the plan too
        with pytest.raises(HTTPException) as refused:
            run(images.create(req, None, director=director))
        assert refused.value.status_code == 429 and refused.value.detail == images.DAILY_LIMIT_REACHED
    assert reserved == []


# ── a replay is never refused at the daily limit ──────────────────────

class ImageDb:
    """image_artworks and reserve_image_artwork as the migration writes them (20 a day, a known id answered with its row)."""

    def __init__(self):
        self.rows, self.reserved, self.hide_once = {}, [], set()

    def fill(self, business_id, n):
        for _ in range(n):
            iid = str(uuid4())
            self.rows[iid] = {'id': iid, 'business_id': str(business_id), 'model': images.MODELS[0], 'status': 'ready',
                              'prompt': 'another', 'quality': 'high', 'size': '1024x1024', 'reference_ids': [],
                              'director': None, 'created_at': datetime.now(timezone.utc).isoformat()}

    async def __call__(self, client, method, path, body=None, **kw):
        table = path.split('?', 1)[0]
        if method == 'GET' and table == '/image_artworks':
            hidden = [i for i in self.hide_once if f'id=eq.{i}' in path]
            for i in hidden:
                self.hide_once.discard(i)
                return []                       # the row appears just after this read (a racing retry)
            return copy.deepcopy(select(self.rows.values(), path))
        if method == 'POST' and path == '/rpc/reserve_image_artwork':
            rec = body['p_record']
            if rec['id'] in self.rows:
                return [copy.deepcopy(self.rows[rec['id']])]
            today = [r for r in self.rows.values() if r['business_id'] == rec['business_id'] and r.get('model')]
            if len(today) >= body['p_daily_limit']:
                raise HTTPException(503, 'Image storage is unavailable.')
            row = {**copy.deepcopy(rec), 'status': 'queued', 'director': None,
                   'created_at': datetime.now(timezone.utc).isoformat()}
            self.rows[rec['id']] = row
            self.reserved.append(rec['id'])
            return [copy.deepcopy(row)]
        if method == 'PATCH' and table == '/image_artworks':
            hit = select(self.rows.values(), path)
            for r in hit:
                r.update(copy.deepcopy(body))
            return copy.deepcopy(hit)
        raise AssertionError(f'unexpected image call {method} {path}')


@pytest.fixture
def real_images(monkeypatch):
    """The real image_studio.create over an in-memory image table."""
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.delenv('OPENAI_IMAGE_MODEL', raising=False)
    imgs = ImageDb()
    monkeypatch.setattr(images, 'create', REAL_CREATE)
    monkeypatch.setattr(images, 'db', imgs)
    monkeypatch.setattr(images, 'launch_worker', lambda row: None)

    async def present(client, row):
        return row
    monkeypatch.setattr(images, 'present', present)
    import billing_limits
    monkeypatch.setattr(billing_limits, 'require_units', lambda bid: None)
    return imgs


def test_a_replay_at_the_daily_limit_gets_its_row_back_on_the_owners_own_path(monkeypatch, real_images):
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': PRO, 'owner_id': PRO_OWNER}))
    api = FastAPI()
    api.include_router(images.router)
    api.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=PRO_OWNER))
    client = TestClient(api)
    body = {'business_id': PRO, 'request_id': str(uuid4()), 'prompt': 'A flyer for Saturday', 'size': '1024x1536'}
    first = client.post('/ai/images/generate', json=body)
    assert first.status_code == 202 and first.json()['status'] == 'queued'
    real_images.fill(PRO, 19)                               # 20 today, this one included: the limit
    again = client.post('/ai/images/generate', json=body)
    assert again.status_code == 202 and again.json()['id'] == body['request_id']
    assert real_images.reserved == [body['request_id']]      # answered with its row, never reserved twice
    fresh = client.post('/ai/images/generate', json={**body, 'request_id': str(uuid4())})
    assert fresh.status_code == 429 and fresh.json()['detail'] == images.DAILY_LIMIT_REACHED
    assert len(real_images.reserved) == 1


def test_a_row_that_appears_between_the_lookup_and_the_count_is_not_refused(monkeypatch, real_images):
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': PRO, 'owner_id': PRO_OWNER}))
    req = images.CreateImage(business_id=PRO, request_id=uuid4(), prompt='A flyer for Saturday', size='1024x1536')
    run(images.create(req, None))
    real_images.fill(PRO, 19)
    real_images.hide_once.add(str(req.request_id))           # a retry racing the first call
    row = run(images.create(req, None))
    assert row['id'] == str(req.request_id) and real_images.reserved == [str(req.request_id)]


def test_the_planners_replay_at_the_daily_limit_keeps_designing(w, real_images):
    out = week(w)
    assert out['designing'] == 5 and len(real_images.reserved) == 5
    real_images.fill(PRO, 15)                                # 20 today: the business is at its limit
    p = posts_of(w)[0]
    row = run(asyncio.to_thread(plan.read_business, PRO))
    profile = run(prof.read_profile(PRO, business=row))
    slot = next(s for s in run_of(w)['slots'] if s['play_id'] == p['play_id'])
    copy_ = week_reply()['captions'][0]['flyer']
    # the same post's flyer again (a retried run): its design, never a 429, never words only
    assert run(plan.start_flyer(row, p, slot, copy_, profile, p['run_id'])) == ('started', None)
    assert len(real_images.reserved) == 5
    first = real_images.rows[flyer_of(p)]
    assert first['size'] == '1088x1360' and cd.included(first['director'])
    # a NEW flyer at the limit is still refused
    other = {**p, 'id': plan.week_post_id(p['run_id'], 9, 1)}
    outcome, why = run(plan.start_flyer(row, other, slot, copy_, profile, p['run_id']))
    assert outcome == 'limit' and why == images.DAILY_LIMIT_REACHED and len(real_images.reserved) == 5


def test_the_planner_never_gives_up_on_a_flyer_that_already_exists(w):
    run_id = store.run_id_for(PRO, NEXT_MONDAY)
    first = plan.week_post_id(run_id, 1, 1)
    flyer = str(plan.flyer_request_id(run_id, first))
    w.svc.images.append({'id': flyer, 'business_id': PRO, 'status': 'working', 'storage_path': None,
                         'created_at': w.now.isoformat(), 'phase': 'generating', 'review': None})
    w.create_error = {1: HTTPException(429, images.DAILY_LIMIT_REACHED)}     # however this call ends
    out = week(w)
    p = w.db.posts[first]
    assert p['design_status'] == 'designing' and p['error'] is None and p['revision'] == 1
    assert {t['platform'] for t in p['targets']} == {'facebook', 'instagram'}
    assert run_of(w)['design']['flyers'][first]['state'] == 'designing' and out['designing'] == 5
    finish(w, {flyer})
    run(plan.marketing_design_tick(w.now + timedelta(minutes=4)))
    assert w.db.posts[first]['design_status'] == 'ready'                        # and it is attached


def test_when_it_cannot_tell_whether_a_flyer_exists_the_post_waits_for_the_tick(w, monkeypatch):
    real = plan.flyer_rows

    def blind_to_one(business_id, ids):
        if len(ids) == 1:
            raise plan.Unavailable('image_artworks')
        return real(business_id, ids)
    monkeypatch.setattr(plan, 'flyer_rows', blind_to_one)
    w.create_error = {1: HTTPException(503, 'Image storage is unavailable.')}
    week(w)
    first = posts_of(w)[0]
    assert first['design_status'] == 'designing' and run_of(w)['design']['flyers'][first['id']]['why'] == 'unknown'
    w.now += timedelta(minutes=21)
    run(plan.marketing_design_tick(w.now))                    # no design came: words only, at the usual 20 minutes
    assert posts_of(w)[0]['design_status'] == 'failed'


# ── every desk picture is 4:5 ─────────────────────────────────────────

def test_four_by_five_is_offered_only_on_the_models_that_take_custom_sizes(monkeypatch):
    assert '1088x1360' in images.model_sizes('gpt-image-2.5-sunburst')
    assert '1088x1360' in images.model_sizes('gpt-image-2.5-flare')
    assert images.model_sizes('gpt-image-2') == ('1024x1024', '1536x1024', '1024x1536')        # unchanged
    assert images.CreateImage(business_id=PRO, request_id=uuid4(), prompt='A flyer', size='1088x1360').size == '1088x1360'
    assert DesignRequest(goal='A flyer for the week', size='1088x1360').size == '1088x1360'
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': PRO, 'owner_id': PRO_OWNER}))
    database = AsyncMock()
    monkeypatch.setattr(images, 'db', database)
    req = images.CreateImage(business_id=PRO, request_id=uuid4(), prompt='A flyer', model='gpt-image-2',
                             size='1088x1360')
    with pytest.raises(HTTPException) as refused:
        run(images.create(req, None))
    assert refused.value.status_code == 422 and not database.called


def test_the_plan_asks_for_four_by_five_and_square_without_custom_sizes(w, monkeypatch):
    monkeypatch.delenv('OPENAI_IMAGE_MODEL', raising=False)
    assert plan.flyer_size() == '1088x1360'
    w_, h = map(int, plan.FLYER_SIZE.split('x'))
    assert w_ * 5 == h * 4 and w_ % 16 == 0 and h % 16 == 0
    monkeypatch.setenv('OPENAI_IMAGE_MODEL', 'gpt-image-2')
    assert plan.flyer_size() == '1024x1024'
    week(w)
    assert {c['size'] for c in w.creates} == {'1024x1024'} and 'Square' in w.prepared[0]['goal']


def test_the_suggestions_free_flyer_is_four_by_five_too():
    import marketing_design as design
    layout = design.flyer_layout('useful_tip', {'headline': 'Plan the week ahead',
                                                'line': 'One small change makes the whole week calmer.',
                                                'cta': 'Book a time'},
                                 eyebrow='TIP', footer={'label': 'PRO SHOP', 'host': 'pro-shop.mysolutionist.app'},
                                 palette=design.brand_palette({'primary': '#1F4E79'}))
    assert (layout['width'], layout['height']) == (1080, 1350) and layout['width'] * 5 == layout['height'] * 4


# ── idempotent design requests ────────────────────────────────────────

def test_a_retried_run_never_designs_twice(w, monkeypatch):
    real = plan.start_flyer
    calls = []

    async def dies_on_the_third(*a, **k):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError('the worker restarted')
        return await real(*a, **k)
    monkeypatch.setattr(plan, 'start_flyer', dies_on_the_third)
    out = week(w)
    assert out['status'] == 'failed' and len(posts_of(w)) == 5 and len(w.creates) == 2
    monkeypatch.setattr(plan, 'start_flyer', real)
    w.now += timedelta(minutes=30)
    again = week(w)                                                          # the scheduler's retry (attempt 2)
    assert again['status'] == 'succeeded' and again['resumed'] is True
    assert len(w.creates) == 2 and len(w.calls) == 1 and len(posts_of(w)) == 5   # no new design, no new caption
    assert run_of(w)['attempts'] == 2 and run_of(w)['design']['tell'] == 'pending'
    # the same post always names the same design; a replan's new posts never do
    p = posts_of(w)[0]
    assert plan.flyer_request_id(p['run_id'], p['id']) == plan.flyer_request_id(p['run_id'], p['id'])
    assert plan.week_post_id(p['run_id'], 1, 1) != plan.week_post_id(p['run_id'], 2, 1)


def test_starting_the_same_flyer_again_lands_on_the_same_design(w):
    week(w)
    p = posts_of(w)[0]
    slot = {'play_id': p['play_id'], 'subject': None}
    copy_ = {'headline': 'Plan the week ahead', 'line': 'One small change makes the whole week calmer.', 'cta': 'Book'}
    row = run(asyncio.to_thread(plan.read_business, PRO))
    profile = run(prof.read_profile(PRO, business=row))
    assert run(plan.start_flyer(row, p, slot, copy_, profile, p['run_id'])) == ('started', None)
    assert w.creates[-1]['request_id'] == w.creates[0]['request_id'] == flyer_of(p)
    assert len(w.svc.images) == 5                                            # no second reservation


# ── included in the plan: no credits, still metered, server-set only ──

def test_an_included_design_is_never_charged_but_its_cost_is_still_logged(monkeypatch):
    import test_creative_director as tcd
    seen = SimpleNamespace(charges=[], guards=[])

    async def render(client, record, prompt, refs, charge=True):
        seen.charges.append(charge)
        return tcd.png(), {'output_tokens': 10}, .05

    async def db(client, method, path, body=None, **kw):
        return [body]
    monkeypatch.setattr(images, 'db', db)
    monkeypatch.setattr(images, 'store', AsyncMock())
    monkeypatch.setattr(cd, 'references', AsyncMock(return_value={}))
    monkeypatch.setattr(cd, 'make_plan', AsyncMock(return_value=tcd.plan()))
    monkeypatch.setattr(cd, 'render', render)
    monkeypatch.setattr(cd, 'review', AsyncMock(return_value=dict(passed=False, issues=['Title clipped'],
                                                                  repair_instruction='Fit the title')))
    spec = cd.include_in_plan({**tcd.spec(), 'scope': 'business'})
    run(cd.run(None, tcd.row(spec)))
    assert seen.charges == [False, False]                    # paid renders, never charged in credits
    paid = tcd.spec()
    seen.charges.clear()
    run(cd.run(None, tcd.row({**paid, 'scope': 'business'})))
    assert seen.charges == [True, False]                     # a design the owner asked for: one price


def test_included_planning_checks_the_spend_guard_not_the_credits(monkeypatch):
    import test_creative_director as tcd
    calls = []

    async def guard(business_id, scope='platform', *, credits=True):
        calls.append(credits)
    import api_usage_logger
    monkeypatch.setattr(cd, 'guard', guard)
    monkeypatch.setattr(api_usage_logger, 'log_api_usage_sync', lambda **kw: None)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake')

    def respond(req):
        return httpx.Response(200, json={'usage': {'input_tokens': 10, 'output_tokens': 20}, 'content': [
            {'type': 'tool_use', 'name': 'return_result', 'input': tcd.plan().model_dump(mode='json')}]})

    async def exercise(spec):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await cd.structured(client, tcd.row(spec), cd.Plan, 'Plan this', [{'type': 'text', 'text': 'brief'}])
    run(exercise(cd.include_in_plan({**tcd.spec(), 'scope': 'business'})))
    run(exercise({**tcd.spec(), 'scope': 'business'}))
    assert calls == [False, True]


def test_the_guard_still_blocks_an_included_design_over_the_spend_ceiling(monkeypatch):
    monkeypatch.setattr(spend_guard, 'over_budget', lambda business_id=None: True)
    with pytest.raises(HTTPException) as blocked:
        run(cd.guard(PRO, 'business', credits=False))
    assert blocked.value.status_code == 429


def test_an_included_render_logs_its_cost_with_no_units(monkeypatch):
    import base64
    import test_creative_director as tcd
    from creative_director_render import render
    billed = []

    async def record(**kw):
        billed.append(kw)
    monkeypatch.setattr(images, 'log_api_usage', record)
    monkeypatch.setattr(cd, 'guard', AsyncMock())

    def respond(req):
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(tcd.png()).decode()}],
                                         'usage': {'input_tokens': 100, 'output_tokens': 6000,
                                                   'input_tokens_details': {'text_tokens': 100, 'image_tokens': 0}}})

    async def exercise(charge):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await render(client, tcd.row({**tcd.spec(), 'scope': 'business'}), 'art', [], charge=charge)
    run(exercise(False))
    run(exercise(True))
    assert billed[0]['units'] == 0 and billed[0]['cost_cents_override'] > 0 and billed[0]['ok'] is True
    assert billed[1]['units'] == images.image_units('high') and billed[1]['cost_cents_override'] == billed[0][
        'cost_cents_override']


def test_image_studio_skips_the_credit_check_only_for_an_included_design(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': PRO, 'owner_id': PRO_OWNER}))
    monkeypatch.setattr(images, 'launch_worker', lambda row: None)
    monkeypatch.setattr(images, 'present', AsyncMock(side_effect=lambda c, r: r))
    checked = []
    import billing_limits
    monkeypatch.setattr(billing_limits, 'require_units', lambda bid: checked.append(bid))

    async def database(client, method, path, body=None, **kw):
        if method == 'GET':
            return []
        if path == '/rpc/reserve_image_artwork':
            return [{**body['p_record'], 'status': 'queued', 'director': None}]
        return [{**body, 'id': 'x', 'business_id': PRO, 'status': 'queued'}] if isinstance(body, dict) else [{}]
    monkeypatch.setattr(images, 'db', database)
    spec = {'version': 1, 'scope': 'business', 'goal': 'g', 'copy': ['a'], 'references': [], 'max_renders': 2}
    for director in (spec, cd.include_in_plan(spec)):
        req = images.CreateImage(business_id=PRO, request_id=uuid4(), prompt='A flyer', size='1024x1536')
        run(images.create(req, None, director=director))
    assert checked == [PRO]                                   # the paid one only


def test_nothing_a_request_or_chief_sends_can_say_a_design_is_included(monkeypatch):
    # The Director's contract forbids the key outright.
    with pytest.raises(ValidationError):
        DesignRequest(goal='A flyer for the week', exact_copy=['Hi'], billing='included')
    # Chief's design_flyer (the business door): the spec is built from named fields.
    captured = []

    async def create(req, client, *, director=None):
        captured.append(director)
        return {'id': str(req.request_id), 'status': 'queued'}
    monkeypatch.setattr(images, 'create', create)
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[]))
    monkeypatch.setattr(images, 'business', AsyncMock(return_value={'id': PRO, 'owner_id': PRO_OWNER, 'settings': {}}))
    monkeypatch.setattr(cd, 'profile', AsyncMock(return_value={}))
    monkeypatch.setattr(cd, 'business_facts', lambda bid: {})
    action = {'type': 'design_flyer', 'goal': 'A flyer for Saturday', 'exact_copy': ['Saturday special'],
              'billing': 'included', 'director': {'billing': 'included', 'scope': 'business'},
              'scope': 'business', 'size': '1024x1536'}
    run(cd.handle_design_flyer(None, {'id': PRO}, action))
    assert 'billing' not in captured[-1] and not cd.included(captured[-1])
    # The platform door takes a spec on an action, and drops the flag from it.
    prepared = {'type': 'design_flyer', 'size': '1024x1536', 'quality': 'high',
                'director': {'version': 1, 'goal': 'A flyer for Saturday', 'copy': ['a'], 'references': [],
                             'max_renders': 2, 'scope': 'business', 'billing': 'included'}}
    run(cd.start(None, {'id': PRO}, prepared, uuid4()))
    assert 'billing' not in captured[-1] and not cd.included(captured[-1])
    # Image Studio's own door has no director at all.
    body = images.CreateImage.model_validate({'business_id': PRO, 'request_id': str(uuid4()), 'prompt': 'A flyer',
                                              'director': {'billing': 'included'}, 'billing': 'included'})
    assert not hasattr(body, 'director') and not hasattr(body, 'billing')
    # Only a business design can be marked, and only by include_in_plan.
    assert not cd.included({'billing': 'included'})
    with pytest.raises(ValueError):
        cd.include_in_plan({'version': 1})
    src = (ROOT / 'business_marketing_planner.py').read_text(encoding='utf-8')
    users = [p.name for p in ROOT.glob('*.py') if 'include_in_plan(' in p.read_text(encoding='utf-8', errors='ignore')]
    assert sorted(users) == ['business_marketing_planner.py', 'creative_director.py']
    assert src.count('include_in_plan(') == 1


def test_the_image_route_never_passes_a_director(monkeypatch):
    seen = []

    async def create(req, client, *, director=None):
        seen.append(director)
        return {'ok': True}
    monkeypatch.setattr(images, 'create', create)
    api = FastAPI()
    api.include_router(images.router)
    api.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=PRO_OWNER))
    r = TestClient(api).post('/ai/images/generate', json={
        'business_id': PRO, 'request_id': str(uuid4()), 'prompt': 'A flyer', 'billing': 'included',
        'director': {'billing': 'included', 'scope': 'business'}})
    assert r.status_code == 202 and seen == [None]


# ── telling the owner once, after every post settles ──────────────────

def test_one_push_and_one_today_item_only_once_every_post_settles(w):
    week(w)
    posts = posts_of(w)
    run(plan.marketing_design_tick(w.now))
    assert w.pushes == [] and w.svc.notifications == []                       # all five still designing
    finish(w, {flyer_of(p) for p in posts[:3]})
    run(plan.marketing_design_tick(w.now + timedelta(minutes=4)))
    assert w.pushes == [] and w.svc.notifications == []                       # two still designing
    finish(w)
    run(plan.marketing_design_tick(w.now + timedelta(minutes=8)))
    assert len(w.pushes) == 1 and len(w.svc.notifications) == 1
    push, item = w.pushes[0], w.svc.notifications[0]
    assert push['user'] == PRO_OWNER and push['nav'] == 'grow:marketing'
    assert push['title'] == 'Chief planned next week: 5 posts wait for your OK'
    assert push['body'] == 'Each has its flyer. Nothing posts until you approve them.'
    assert item['type'] == 'reminder' and item['title'] == push['title']
    assert item['action_payload']['dedup_key'] == plan.week_dedup_key(run_of(w)['id'], 1)
    assert run_of(w)['design']['tell'] == 'done'
    for minutes in (10, 12, 30):
        run(plan.marketing_design_tick(w.now + timedelta(minutes=minutes)))
    assert len(w.pushes) == 1 and len(w.svc.notifications) == 1               # never again


def test_a_week_with_nothing_designing_is_told_on_the_next_tick(w):
    w.create_error = {n: HTTPException(429, images.DAILY_LIMIT_REACHED) for n in range(1, 6)}
    week(w)
    assert all(p['design_status'] == 'failed' for p in posts_of(w)) and w.pushes == []
    run(plan.marketing_design_tick(w.now))
    assert len(w.pushes) == 1 and w.pushes[0]['body'] == 'They go as words only this time. Nothing posts until you approve them.'


def test_when_what_was_said_cannot_be_read_nothing_is_said(w):
    week(w)
    finish(w)
    w.svc.fail = ('/chief_notifications',)
    run(plan.marketing_design_tick(w.now + timedelta(minutes=5)))
    assert w.pushes == [] and run_of(w)['design']['tell'] == 'pending'        # tried again next tick
    w.svc.fail = ()
    run(plan.marketing_design_tick(w.now + timedelta(minutes=7)))
    assert len(w.pushes) == 1


def test_the_design_tick_does_nothing_unless_the_desk_covers_the_business(w, monkeypatch):
    week(w)
    finish(w)
    monkeypatch.setenv('MARKETING_DESK', BIZ)
    out = run(plan.marketing_design_tick(w.now + timedelta(minutes=5)))
    assert {p['design_status'] for p in posts_of(w)} == {'designing'} and w.pushes == [] and 'attached' not in out
    monkeypatch.setenv('MARKETING_DESK', 'off')
    assert run(plan.marketing_design_tick()) == {'skipped': 'off'}


# ── the owner's own request: replans ──────────────────────────────────

def ask(w, biz=PRO):
    return w.client.post(f'/marketing/{biz}/engine/run')


def settle(w):
    finish(w)
    w.now += timedelta(minutes=3)
    run(plan.marketing_design_tick(w.now))


def test_a_week_is_queued_and_the_worker_plans_it(w):
    r = ask(w)
    assert r.status_code == 202, r.text
    assert r.json()['kind'] == 'week' and r.json()['message'] == plan.WEEK_QUEUED and w.calls == []
    out = run(plan.manual_tick(w.now))
    assert out == {'week_succeeded': 1} and len(posts_of(w)) == 5 and run_of(w)['trigger'] == 'manual'


def test_a_replan_saves_the_new_week_before_it_retires_the_old_one(w):
    week(w)
    settle(w)
    old = {p['id'] for p in posts_of(w)}
    w.now += timedelta(minutes=10)
    assert ask(w).status_code == 202
    mark = len(w.db.writes)
    run(plan.manual_tick(w.now))
    writes = w.db.writes[mark:]
    insert = next(i for i, (m, p, b) in enumerate(writes) if m == 'POST' and p == '/marketing_posts')
    cancels = [i for i, (m, p, b) in enumerate(writes) if m == 'PATCH' and p.startswith('/marketing_posts')
               and (b or {}).get('status') == 'cancelled']
    assert len(cancels) == 5 and all(i > insert for i in cancels)            # new first, old after
    assert {p['id'] for p in posts_of(w, status='cancelled')} == old
    fresh = [p for p in posts_of(w) if p['status'] == 'draft']
    assert len(fresh) == 5 and not ({p['id'] for p in fresh} & old)
    r = run_of(w)
    assert r['design']['replans'] == 1 and r['attempts'] == 2 and set(r['post_ids']) == {p['id'] for p in fresh}


def test_the_replan_shares_the_weeks_five_flyers(w):
    week(w)
    settle(w)
    assert ask(w).status_code == 202
    run(plan.manual_tick(w.now))
    fresh = [p for p in posts_of(w) if p['status'] == 'draft']
    assert len(w.creates) == 5 and {p['design_status'] for p in fresh} == {'failed'}   # all five already made
    assert all(p['error'].startswith("This week's five included flyers are already made") for p in fresh)


def test_at_most_two_replans_a_week(w):
    w.create_error = {n: HTTPException(429, images.DAILY_LIMIT_REACHED) for n in range(1, 30)}
    week(w)
    for n in (1, 2):
        run(plan.marketing_design_tick(w.now))
        w.now += timedelta(minutes=5)
        rate_limit._buckets.clear()
        assert ask(w).status_code == 202
        run(plan.manual_tick(w.now))
        assert run_of(w)['design']['replans'] == n
    run(plan.marketing_design_tick(w.now))
    rate_limit._buckets.clear()
    r = ask(w)
    assert r.status_code == 429 and r.json()['detail'] == plan.REPLANNED_TWICE


def test_no_replan_while_a_flyer_is_being_made_or_a_post_is_approved(w):
    week(w)
    before = copy.deepcopy(w.db.runs)
    r = ask(w)
    assert r.status_code == 409 and r.json()['detail'] == plan.STILL_DESIGNING and w.db.runs == before
    settle(w)
    p = posts_of(w)[0]
    item = {'id': p['id'], 'revision': p['revision'], 'content_hash': p['content_hash']}
    assert w.client.post(f'/marketing/{PRO}/approve', json={'items': [item]}).status_code == 200
    rate_limit._buckets.clear()
    r = ask(w)
    assert r.status_code == 409 and r.json()['detail'] == plan.WEEK_BUSY


def test_a_replan_that_writes_nothing_keeps_the_week(w):
    week(w)
    settle(w)
    old = {p['id'] for p in posts_of(w)}
    assert ask(w).status_code == 202
    w.reply = {'captions': []}
    out = run(plan.manual_tick(w.now))
    assert out == {'week_kept': 1}
    assert {p['id'] for p in posts_of(w, status='draft')} == old
    r = run_of(w)
    assert r['status'] == 'succeeded' and plan.WEEK_KEPT in r['error'] and r['design']['replans'] == 0


def test_a_week_waits_for_room_and_gives_up_in_plain_words(w, monkeypatch):
    other = str(uuid4())
    for n in range(8):                                      # eight flyers in progress elsewhere; room for two
        w.db.posts[f'busy{n}'] = {'id': f'busy{n}', 'business_id': other, 'status': 'draft',
                                  'design_status': 'designing', 'run_at': (THU + timedelta(days=3)).isoformat()}
    assert ask(w).status_code == 202
    assert run(plan.manual_tick(w.now)) == {'week_waiting': 1} and posts_of(w) == []
    w.now += timedelta(minutes=11)
    assert run(plan.manual_tick(w.now)) == {'week_busy': 1}
    r = run_of(w)
    assert r['status'] == 'skipped' and r['error'] == plan.DESIGNS_BUSY and w.calls == []


# ── plays lean on the business's own results, from 3 samples ──────────

def test_play_scores_come_from_the_businesss_own_links(monkeypatch):
    now = THU
    posts = [{'id': str(uuid4()), 'business_id': PRO, 'status': 'published', 'play_id': play,
              'tracked_url': 'https://pro-shop.mysolutionist.app/?utm_content=x',
              'run_at': (now - timedelta(days=d)).isoformat()}
             for d, play in enumerate(['meet_us'] * 3 + ['offer_spotlight'] * 2, start=3)]
    reads = []

    async def rows(path):
        reads.append(path)
        if path.startswith('/marketing_posts'):
            assert 'status=in.(published,partly_published)' in path and 'tracked_url=not.is.null' in path
            return copy.deepcopy(posts)
        if path.startswith('/marketing_link_clicks'):
            return [{'post_id': p['id'], 'clicks': 6} for p in posts]
        raise AssertionError(path)

    def service(path):
        if path.startswith('/site_events'):
            return [{'session_id': f's{i}', 'data': {'utm_content': posts[0]['id']}} for i in range(9)]
        if path.startswith('/contacts'):
            return [{'id': 'c1', 'attribution': {'utm_content': posts[3]['id']}}]
        if path.startswith('/module_entries'):                  # a booking through the link (2026-10-09)
            return [{'id': 'b1', 'paid_at': None, 'post': posts[4]['id'], 'charged': None}]
        raise AssertionError(path)
    monkeypatch.setattr(store, 'rows', rows)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', service)
    scores = run(outcomes.play_scores(PRO, now=now))
    # offer_spotlight: (6 + a lead's 4) and (6 + a booking's 8), averaged
    assert scores == {'meet_us': {'samples': 3, 'average': 7.0}, 'offer_spotlight': {'samples': 2, 'average': 12.0}}

    def failing(path):
        return None if path.startswith('/contacts') else service(path)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', failing)
    assert run(outcomes.play_scores(PRO, now=now)) == {}                       # a source unread: the default order


def test_a_play_reorders_the_week_only_with_three_results(w):
    signals = quiet_signals()
    profile = prof.build_profile(business(PRO, PRO_OWNER, tier='professional'), hosts={'pro-shop.mysolutionist.app'})
    facts = eng.verified_facts(FACTS)
    default = [p['play_id'] for p in eng.pick_plays('stay_visible', 5, signals, profile, facts)['plays']]
    assert default == ['useful_tip', 'offer_spotlight', 'meet_us']
    two = {**signals, 'play_scores': {'meet_us': {'samples': 2, 'average': 99.0}}}
    assert [p['play_id'] for p in eng.pick_plays('stay_visible', 5, two, profile, facts)['plays']] == default
    three = {**signals, 'play_scores': {'meet_us': {'samples': 3, 'average': 99.0}}}
    assert [p['play_id'] for p in eng.pick_plays('stay_visible', 5, three, profile, facts)['plays']] == [
        'useful_tip', 'meet_us', 'offer_spotlight']
    # and the week reads them: the run records the scores it leaned on
    w.scores = {'meet_us': {'samples': 3, 'average': 99.0}}
    week(w)
    r = run_of(w)
    assert r['signals']['play_scores'] == w.scores
    assert [p['play_id'] for p in r['plays']] == ['useful_tip', 'meet_us', 'offer_spotlight']
    assert 'done well through their own links (3 so far)' in r['plays'][1]['reason']


# ── who gets a week ───────────────────────────────────────────────────

def test_boss_with_open_chairs_gets_the_open_chairs_week_not_the_plain_one(w):
    # B11: the openings level is never planned as a plain week; its own week
    # is the open-chairs one (__tests__/test_business_marketing_openings.py).
    out = run(plan.run_week(BOSS, trigger='scheduled'))
    assert out == {'status': 'not_eligible', 'reason': plan.OPENINGS_LEVEL}
    assert not [r for r in w.db.runs.values() if r['business_id'] == BOSS] and w.calls == []
    assert plan.run_kind(w.svc.businesses[BOSS]) == ('openings', None)
    tick = run(plan.marketing_tick(THU + timedelta(hours=3)))
    assert tick['candidates'] == 3 and tick['openings_skipped'] == 1         # no weekly hours set here
    assert not [p for p in w.db.posts.values() if p['business_id'] == BOSS]
    boss_run = next(r for r in w.db.runs.values() if r['business_id'] == BOSS)
    assert boss_run['kind'] == 'openings' and boss_run['error'] == plan.NO_HOURS
    assert len(posts_of(w)) == 5                                             # the Professional week is unchanged
    suggestion = run(plan.run_suggestion(BOSS, trigger='scheduled'))
    assert suggestion['reason'] == plan.WEEK_LEVEL                           # nor a suggestion


def test_practice_gets_the_plain_week_and_starter_still_gets_its_suggestion(w):
    w.svc.businesses[PRO]['comp_tier'] = 'practice'
    assert plan.run_kind(w.svc.businesses[PRO]) == ('week', None)
    assert plan.run_kind(w.svc.businesses[BIZ]) == ('suggestion', None)
    assert plan.run_suggestion is not plan.run_week
    out = run(plan.marketing_tick(THU + timedelta(hours=3)))
    assert out['week_succeeded'] == 1 and out['succeeded'] == 1
    assert len(posts_of(w, BIZ)) == 1 and posts_of(w, BIZ)[0]['source'] == 'suggestion'
    assert len(posts_of(w)) == 5 and {p['source'] for p in posts_of(w)} == {'plan'}


# ── the fan-out: designs at once and the spend headroom ───────────────

def test_a_week_waits_while_its_estimate_would_cross_the_headroom(w):
    tick_at = THU + timedelta(hours=3)
    w.cap = 50.0
    w.share = (30.0 - plan.WEEK_ESTIMATE_USD + 0.01) / 50.0                  # $27.46 spent: the week would cross $30
    assert plan.WEEK_ESTIMATE_USD == pytest.approx(2.55)
    out = run(plan.marketing_tick(tick_at))
    assert out['week_waits_for_headroom'] == 1 and out['succeeded'] == 1     # the suggestion still goes
    assert posts_of(w) == [] and len(posts_of(w, BIZ)) == 1
    w.share = (30.0 - plan.WEEK_ESTIMATE_USD - 0.5) / 50.0
    out = run(plan.marketing_tick(tick_at))
    assert out['week_succeeded'] == 1 and len(posts_of(w)) == 5


def test_designs_already_in_progress_count_against_the_headroom_and_the_room(w, monkeypatch):
    tick_at = THU + timedelta(hours=3)
    other = str(uuid4())
    for n in range(4):
        w.db.posts[f'busy{n}'] = {'id': f'busy{n}', 'business_id': other, 'status': 'draft',
                                  'design_status': 'designing', 'run_at': (THU + timedelta(days=3)).isoformat()}
    # $25.50 spent: alone a week fits under $30, but four flyers on their way ($2.00) tip it over.
    w.share = 25.5 / 50.0
    out = run(plan.marketing_tick(tick_at))
    assert out['week_waits_for_headroom'] == 1 and posts_of(w) == []
    w.share = 0.0
    monkeypatch.setenv('MARKETING_DESIGNS_AT_ONCE', '8')                     # room for four: not a week
    out = run(plan.marketing_tick(tick_at))
    assert out['week_waits_for_designs'] == 1 and posts_of(w) == []
    monkeypatch.setenv('MARKETING_DESIGNS_AT_ONCE', '9')
    out = run(plan.marketing_tick(tick_at))
    assert out['week_succeeded'] == 1


def test_two_weeks_in_one_tick_reserve_each_others_cost(w):
    tick_at = THU + timedelta(hours=3)
    second = str(uuid4())
    w.svc.businesses[second] = business(second, str(uuid4()), name='Second Shop', tier='professional')
    w.svc.connections.append(connection(str(uuid4()), 'facebook', biz=second))
    w.svc.sites.append({'business_id': second, 'slug': 'second-shop', 'status': 'published', 'site_config': {},
                        'updated_at': '2026-10-01T00:00:00Z'})
    w.db.desks[second] = {'business_id': second, 'plan_enabled': True, 'paused': False, 'connection_ids': [],
                          'post_hour': 11}
    w.share = 25.0 / 50.0                                                    # room under $30 for one week ($2.55), not two
    out = run(plan.marketing_tick(tick_at))
    assert out['week_succeeded'] == 1 and out['week_waits_for_headroom'] == 1


def test_the_design_room_env_is_bounded(monkeypatch):
    for raw, want in ((None, 10), ('3', 5), ('20', 20), ('500', 50), ('lots', 10)):
        if raw is None:
            monkeypatch.delenv('MARKETING_DESIGNS_AT_ONCE', raising=False)
        else:
            monkeypatch.setenv('MARKETING_DESIGNS_AT_ONCE', raw)
        assert plan.designs_at_once() == want
    text = (ROOT / '.env.example').read_text(encoding='utf-8')
    assert '\nMARKETING_DESIGNS_AT_ONCE=10' in text


# ── the job ───────────────────────────────────────────────────────────

APP = (ROOT / 'kmj_intake_automation.py').read_text(encoding='utf-8')


def test_the_design_tick_is_registered_leader_gated_every_two_minutes():
    startup = APP.index('async def startup')
    started = APP.index('if runs_scheduled_jobs():\n        scheduler.start()')
    at = APP.index('g("business_marketing_designs", _marketing_planner.marketing_design_tick)')
    assert startup < at < started
    call = APP[at:APP.index('\n', APP.index('id="business_marketing_designs"'))]
    assert 'minutes=2' in call and 'max_instances=1' in call
    suggest = APP.index('g("business_marketing_suggest", _marketing_planner.')
    assert abs(at - suggest) < 800                                           # beside the B8 jobs


def test_the_docs_and_worklog_say_what_was_built():
    doc = (ROOT / 'docs' / 'MARKETING_DESK.md').read_text(encoding='utf-8')
    assert '### The weekly plan (B9)' in doc and 'MARKETING_DESIGNS_AT_ONCE' in doc
    log = (ROOT / 'worklog' / '2026-10-07-marketing-weekly-plan.md').read_text(encoding='utf-8')
    head = log.split('---')[1]
    assert re.search(r'^agent: Claude Code \(Claude Opus 5\.5\)$', head, re.M)
    assert re.search(r'^migrations: \[\]$', head, re.M)
