"""Solutionist's standing OK on the marketing desk (business_marketing_standing.py, B13).

What must hold:
  1. A GRANT is the owner's, for a covered kind, on the Solutionist plan with
     client-facing autonomy on: refused without the plan, without autonomy,
     for a member, for any other kind, and from chat.
  2. A DRAFTED WEEK approves only the granted kinds, through marketing_approve
     with approved_via 'standing' and the owner as the actor, one post at a
     time, once the week has settled: a post still designing waits, and so do
     a words-only post and a flyer Chief's own check was unsure about. Each
     approval is on Chief's log (audit_log + chief_activity); the owner gets
     one Today item and one push for the week.
  3. AT SEND TIME a lapsed plan or autonomy off puts the post back to waiting
     (a draft), never sent; the rest of its kind goes back too; the owner is
     told once. An unreadable business holds it. The design tick's sweep does
     the same at once.
  4. ASK AFTER THREE: the owner's third clean approval of a kind asks once
     (response, Today item, push); an edit in between does not count.
  5. RETIRE AFTER THREE: three standing approvals the owner edited, took back
     or skipped revoke the grant, put the rest back and tell the owner; one
     that went out ends the run.
  6. TAKE BACK: an approved post goes back to a draft until it is claimed.
  7. GUARDS: Professional, Boss and Starter are never approved on a standing
     OK, even with a grant written into their settings; the suggestion, open
     chairs and one-offs never are; Chief's own post_clip proposals never ride
     the marketing grant.

No network: the B9/B12 suites' fakes (the marketing tables and RPCs, the
service-role reads, the model, Image Studio, push), plus marketing_post_events
written the way the database trigger writes them (a snapshot of every insert
and update), businesses.settings writes, audit_log and chief_activity.
"""
from __future__ import annotations

import asyncio
import copy
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '__tests__'))

import pytest

import audit_log
import business_access
import business_marketing as bm
import business_marketing_dispatch as d
import business_marketing_planner as plan
import business_marketing_standing as standing
import business_marketing_store as store
import sb_clients
import standing_permissions as sp

from test_business_marketing_planner import BIZ, PRO, PRO_OWNER, _when, matches  # noqa: E402
from test_business_marketing_week import (  # noqa: E402  (the B9 suite's fixture and helpers)
    BOSS, MEMBER, finish, posts_of, run_of, w)
from test_business_marketing_clips import c, two_clips  # noqa: E402,F401  (B12: PRO on the Solutionist plan)

run = asyncio.run
ALL = ['marketing_post', 'post_clip']


# ── the database's own history, and the rest of the harness ───────────

class Events:
    """marketing_post_events as the trigger writes it: a snapshot of every
    insert and update of a post, served with PostgREST's JSON-path select."""

    def __init__(self, db, clock):
        self.db, self.clock, self.rows, self.seen = db, clock, [], {}

    def snap(self):
        for pid, row in self.db.posts.items():
            if self.seen.get(pid) != row:
                self.rows.append({'id': len(self.rows) + 1, 'post_id': pid, 'business_id': row['business_id'],
                                  'created_at': self.clock().isoformat(), 'snapshot': copy.deepcopy(row)})
                self.seen[pid] = copy.deepcopy(row)

    def get(self, path):
        query = path.split('?', 1)[1]
        rows, columns, order, limit = list(self.rows), '*', None, None
        for part in query.split('&'):
            key, _, expr = part.partition('=')
            if key == 'select':
                columns = expr
            elif key == 'order':
                order = expr
            elif key == 'limit':
                limit = int(expr)
            elif key.startswith('snapshot->>'):
                field = key[len('snapshot->>'):]
                rows = [r for r in rows if matches({'v': r['snapshot'].get(field)}, 'v', expr)]
            else:
                rows = [r for r in rows if matches(r, key, expr)]
        rows.sort(key=lambda r: r['id'], reverse=bool(order and order.endswith('desc')))
        rows = rows[:limit] if limit else rows
        out = []
        for r in rows:
            item = {}
            for col in columns.split(','):
                alias, _, source = col.partition(':')
                if source.startswith('snapshot->>'):
                    value = r['snapshot'].get(source[len('snapshot->>'):])
                    item[alias] = None if value is None else str(value)     # ->> answers text
                else:
                    item[alias] = r[alias]
            out.append(item)
        return out


@pytest.fixture
def m(c, monkeypatch):
    """B12's Solutionist week (PRO on the Practice plan, its clips), with the
    posts' history, settings writes, Chief's log and the standing door."""
    c.ev = Events(c.db, lambda: c.now)
    c.audit, c.activity, c.patches = [], [], []
    inner = c.db.request

    async def request(method, path, body=None):
        if path.split('?', 1)[0] == '/marketing_post_events':
            return c.ev.get(path)
        out = await inner(method, path, body)
        if method != 'GET':
            c.ev.snap()
        return out
    monkeypatch.setattr(store, 'request', request)

    approve = c.db.approve

    def approve_with_time(body):                    # marketing_approve stamps approved_at = now()
        n = approve(body)
        for item in body['p_items']:
            c.db.posts[item['id']]['approved_at'] = c.now.isoformat()
        return n
    c.db.approve = approve_with_time

    def patch(path, body):
        hit = re.match(r'/businesses\?id=eq\.([0-9a-f-]+)', path)
        if not hit:
            raise AssertionError(f'unexpected service patch {path}')
        c.patches.append((path, copy.deepcopy(body)))
        row = c.svc.businesses[hit.group(1)]
        row.update(copy.deepcopy(body))
        return [copy.deepcopy(row)]
    monkeypatch.setattr(sb_clients, 'sb_patch_as_service', patch)
    post = c.svc.post

    def service_post(path, body, prefer=None):
        if path == '/chief_activity':
            c.activity.append(copy.deepcopy(body))
            return None
        return post(path, body, prefer)
    monkeypatch.setattr(sb_clients, 'sb_post_as_service', service_post)
    monkeypatch.setattr(audit_log, 'record', lambda bid, **kw: c.audit.append({'business_id': bid, **kw}) or True)
    monkeypatch.setattr(sp, '_now', lambda: c.now)
    c.client.app.include_router(sp.router)
    return c


def grant(m, *kinds, bid=PRO, owner=PRO_OWNER):
    for kind in kinds:
        m.user = owner
        r = m.client.post('/agents/chief/standing', json={'business_id': bid, 'verb': kind, 'grant': True})
        assert r.status_code == 200, r.text


def settings(m, bid=PRO):
    return m.svc.businesses[bid]['settings']


def tick(m, minutes=3):
    m.now += timedelta(minutes=minutes)
    return run(plan.marketing_design_tick(m.now))


def planned(m, *, clips=True):
    """The Solutionist week drafted and settled: five flyer posts (and two clips)."""
    if clips:
        two_clips(m)
    assert run(plan.run_week(PRO, trigger='scheduled'))['status'] == 'succeeded'
    finish(m)
    return tick(m)


def approvals(m):
    return [b for meth, p, b in m.db.writes if p == '/rpc/marketing_approve']


def notes(m, key_start):
    return [n for n in m.svc.notifications if str(n['action_payload'].get('dedup_key', '')).startswith(key_start)]


def plan_posts(m, status=None):
    return [p for p in posts_of(m, PRO, status) if p['source'] == 'plan']


def clip_posts(m, status=None):
    return [p for p in posts_of(m, PRO, status) if p['source'] == 'clip']


def edit(m, post, caption='A new caption, written by the owner. #planning'):
    m.now += timedelta(minutes=1)
    r = m.client.post(f'/marketing/{PRO}/slot/edit', json={'items': [{'id': post['id'], 'revision': post['revision']}],
                                                           'caption': caption})
    assert r.status_code == 200, r.text


def take_back(m, post, user=PRO_OWNER):
    m.now += timedelta(minutes=1)
    m.user = user
    return m.client.post(f"/marketing/{PRO}/posts/{post['id']}/take-back", json={'revision': post['revision']})


def skip(m, post):
    m.now += timedelta(minutes=1)
    r = m.client.post(f'/marketing/{PRO}/slot/cancel', json={'items': [{'id': post['id'], 'revision': post['revision']}]})
    assert r.status_code == 200, r.text


def approve_as_owner(m, post):
    m.now += timedelta(minutes=1)
    m.user = PRO_OWNER
    r = m.client.post(f'/marketing/{PRO}/approve', json={'items': [
        {'id': post['id'], 'revision': post['revision'], 'content_hash': post['content_hash']}]})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. the grant ──────────────────────────────────────────────────────

def test_a_grant_is_refused_without_the_plan_without_autonomy_for_a_member_and_for_an_uncovered_kind(m):
    door = '/agents/chief/standing'
    m.user = PRO_OWNER
    for tier in ('professional', 'boss', 'starter', 'solo', 'booked'):
        m.svc.businesses[PRO]['comp_tier'] = tier
        r = m.client.post(door, json={'business_id': PRO, 'verb': 'marketing_post', 'grant': True})
        assert r.status_code == 400 and r.json()['detail'] == sp.NOT_ON_PLAN, tier
    m.svc.businesses[PRO]['comp_tier'] = 'practice'
    settings(m)['autonomy'] = {'client_facing_autonomy': 'disabled'}
    r = m.client.post(door, json={'business_id': PRO, 'verb': 'marketing_post', 'grant': True})
    assert r.status_code == 400 and r.json()['detail'] == sp.AUTONOMY_OFF
    settings(m)['autonomy'] = {}
    for kind in ('marketing_suggestion', 'opening', 'suggestion', 'post_now', 'owner'):
        r = m.client.post(door, json={'business_id': PRO, 'verb': kind, 'grant': True})
        assert r.status_code == 400 and r.json()['detail'] == 'this kind always needs a tap', kind
    m.user = MEMBER
    r = m.client.post(door, json={'business_id': PRO, 'verb': 'marketing_post', 'grant': True})
    assert r.status_code == 403
    assert not sp.granted(m.svc.businesses[PRO])
    # A regulated practice keeps client-facing work to itself by default.
    therapist = {**m.svc.businesses[PRO], 'type': 'therapist', 'settings': {}}
    assert sp.eligible(therapist, 'marketing_post') == (False, sp.AUTONOMY_OFF)
    # The owner, on the Solutionist plan: granted, by the owner.
    grant(m, 'marketing_post', 'post_clip')
    got = sp.granted(m.svc.businesses[PRO])
    assert set(got) == set(ALL) and {g['granted_by'] for g in got.values()} == {PRO_OWNER}
    assert {a['verb'] for a in m.audit} == {'standing_grant'}
    assert m.audit[-1]['summary'] == 'Chief may approve clip posts on its own'
    # The owner's GET lists the marketing kinds apart from the send switches.
    body = m.client.get(f'{door}?business_id={PRO}').json()
    assert [e['verb'] for e in body['eligible']] == list(sp.ELIGIBLE)
    assert [(e['verb'], e['ok']) for e in body['marketing']] == [('marketing_post', True), ('post_clip', True)]


def test_chat_never_grants_a_marketing_kind_and_only_the_owner_revokes_one(m, monkeypatch):
    import chief_of_staff as cos
    biz = copy.deepcopy(m.svc.businesses[PRO])
    out = run(sp.handle_grant_standing_permission(None, biz, {'verb': 'weekly posts'}))
    assert cos._action_failed(out) and 'marketing desk' in out['result']
    grant(m, 'marketing_post')
    biz = copy.deepcopy(m.svc.businesses[PRO])
    token = cos._TURN_USER_ID.set(MEMBER)
    try:
        assert cos._action_failed(run(sp.handle_revoke_standing_permission(None, biz, {'verb': 'posts'})))
    finally:
        cos._TURN_USER_ID.reset(token)
    token = cos._TURN_USER_ID.set(PRO_OWNER)
    try:
        out = run(sp.handle_revoke_standing_permission(None, biz, {'verb': 'weekly posts'}))
    finally:
        cos._TURN_USER_ID.reset(token)
    assert out['verb'] == 'marketing_post' and not sp.granted(m.svc.businesses[PRO])


# ── 2. the drafted week ───────────────────────────────────────────────

def test_a_drafted_week_approves_only_the_granted_kind_through_the_rpc_as_standing(m):
    grant(m, 'marketing_post')
    out = planned(m)
    assert out.get('week_told') == 1
    flyers, clips = plan_posts(m), clip_posts(m)
    assert len(flyers) == 5 and len(clips) == 2
    assert {p['status'] for p in flyers} == {'approved'} and {p['approved_via'] for p in flyers} == {'standing'}
    assert {p['approved_by'] for p in flyers} == {PRO_OWNER}
    assert all(p['approved_hash'] == p['content_hash'] == store.digest(p) for p in flyers)
    assert {p['status'] for p in clips} == {'draft'}, 'post_clip was not granted'
    calls = approvals(m)
    assert len(calls) == 5 and all(len(b['p_items']) == 1 for b in calls), 'one post at a time'
    assert {b['p_via'] for b in calls} == {'standing'} and {b['p_actor'] for b in calls} == {PRO_OWNER}
    # Chief's log: what, when, which permission.
    logged = [a for a in m.audit if a['verb'] == 'marketing_standing_approve']
    assert sorted(a['target_id'] for a in logged) == sorted(p['id'] for p in flyers)
    for a in logged:
        assert a['actor_type'] == 'chief' and a['authorized_by'] == 'standing:marketing_post'
        assert a['payload']['granted_by'] == PRO_OWNER and a['payload']['granted_at']
        assert a['payload']['kind'] == 'marketing_post' and a['summary'].startswith('Approved on your standing OK: ')
    acts = [x for x in m.activity if x['action_type'] == 'marketing_standing_approve']
    assert len(acts) == 5 and {x['user_id'] for x in acts} == {PRO_OWNER} and {x['nav'] for x in acts} == {'grow:marketing'}
    assert acts[0]['label'] == 'Approved on your standing OK: Monday 11:00 AM post'
    # The owner is told once for the week.
    week_notes = notes(m, 'marketing_week:')
    assert len(week_notes) == 1
    assert week_notes[0]['title'] == 'Chief approved 5 posts for next week under your standing OK'
    assert 'take back' in week_notes[0]['body'].lower() and '2 more wait for your OK' in week_notes[0]['body']
    pushes = [p for p in m.pushes if p['title'].startswith('Chief approved 5 posts')]
    assert len(pushes) == 1 and pushes[0]['user'] == PRO_OWNER
    tick(m)
    assert len(notes(m, 'marketing_week:')) == 1 and len(approvals(m)) == 5, 'said once, approved once'


def test_with_both_kinds_granted_the_clips_are_approved_too(m):
    grant(m, 'marketing_post', 'post_clip')
    planned(m)
    assert {p['status'] for p in posts_of(m, PRO)} == {'approved'}
    assert {p['approved_via'] for p in clip_posts(m)} == {'standing'}
    note = notes(m, 'marketing_week:')[0]
    assert note['title'] == 'Chief approved 7 posts for next week under your standing OK'
    assert 'more wait' not in note['body']
    assert {a['authorized_by'] for a in m.audit if a['verb'] == 'marketing_standing_approve'} == {
        'standing:marketing_post', 'standing:post_clip'}


def test_a_clip_no_longer_kept_is_not_approved(m):
    grant(m, 'post_clip')
    two_clips(m)
    assert run(plan.run_week(PRO, trigger='scheduled'))['status'] == 'succeeded'
    m.clips[0]['decision'] = 'skipped'
    finish(m)
    tick(m)
    by_clip = {p['media']['clip_id']: p for p in clip_posts(m)}
    assert by_clip[m.clips[0]['id']]['status'] == 'draft' and by_clip[m.clips[1]['id']]['status'] == 'approved'


def test_designing_posts_wait_and_so_do_words_only_and_unsure_flyers(m):
    grant(m, 'marketing_post')
    assert run(plan.run_week(PRO, trigger='scheduled'))['status'] == 'succeeded'
    flyers = plan_posts(m)
    first = [str(plan.flyer_request_id(p['run_id'], p['id'])) for p in flyers[:3]]
    finish(m, first)
    tick(m)
    assert not approvals(m), 'the week has not settled: two flyers are still being made'
    assert {p['design_status'] for p in plan_posts(m)} == {'ready', 'designing'}
    unsure, failed = (str(plan.flyer_request_id(p['run_id'], p['id'])) for p in flyers[3:])
    finish(m, [unsure], phase='needs_review', review={'issues': ['the date looks small']})
    finish(m, [failed], status='failed')
    tick(m)
    by_id = {p['id']: p for p in plan_posts(m)}
    assert [by_id[p['id']]['status'] for p in flyers] == ['approved', 'approved', 'approved', 'draft', 'draft']
    assert by_id[flyers[3]['id']]['error'].startswith("Chief's own check of this flyer")
    assert by_id[flyers[4]['id']]['design_status'] == 'failed'
    assert len(approvals(m)) == 3
    note = notes(m, 'marketing_week:')[0]
    assert note['title'].startswith('Chief approved 3 posts') and '2 more wait for your OK' in note['body']


def test_a_post_due_within_the_hour_is_left_for_the_owner(m):
    grant(m, 'marketing_post')
    two_clips(m)
    run(plan.run_week(PRO, trigger='scheduled'))
    finish(m)
    first = min(plan_posts(m), key=lambda p: p['run_at'])
    m.now = _when(first['run_at']) - timedelta(minutes=30)
    tick(m, minutes=0)
    assert m.db.posts[first['id']]['status'] == 'draft'
    assert len([p for p in plan_posts(m) if p['status'] == 'approved']) == 4


# ── 3. send time and the sweep ────────────────────────────────────────

def claimed(m, post):
    row = m.db.posts[post['id']]
    row.update(status='dispatching', claimed_at=m.now.isoformat())
    m.ev.snap()
    return copy.deepcopy(row)


@pytest.mark.parametrize('lapse', ['plan', 'autonomy'])
def test_at_send_time_a_lapsed_plan_or_autonomy_off_is_not_sent_back_to_waiting_and_told(m, lapse):
    grant(m, 'marketing_post')
    planned(m)
    first = min(plan_posts(m), key=lambda p: p['run_at'])
    if lapse == 'plan':
        m.svc.businesses[PRO]['comp_tier'] = 'professional'
        why = sp.NOT_ON_PLAN
    else:
        settings(m).setdefault('autonomy', {})['client_facing_autonomy'] = 'disabled'
        why = sp.AUTONOMY_OFF
    row = claimed(m, first)
    out = run(d.dispatch(row))
    assert out['status'] == 'draft'
    after = m.db.posts[first['id']]
    assert after['status'] == 'draft' and after['revision'] == row['revision'] + 1
    assert after['approved_via'] is None and after['approved_by'] is None and after['approved_hash'] is None
    assert after['content_hash'] == row['content_hash'], 'the same post, waiting for the owner'
    assert after['error'] == standing.withdrawn_note(why)
    # The rest of its kind went back too, and the owner was told once.
    assert {p['status'] for p in plan_posts(m)} == {'draft'}
    told = notes(m, 'marketing_standing_held:')
    assert len(told) == 1 and '5 posts Chief approved are back to waiting' in told[0]['body']
    assert any(p['title'] == "Chief's standing OK no longer covers your posts" for p in m.pushes)


def test_at_send_time_a_covered_post_goes_on_and_an_unreadable_business_holds_it(m, monkeypatch):
    grant(m, 'marketing_post')
    planned(m)
    first = min(plan_posts(m), key=lambda p: p['run_at'])

    def past_the_check(bid):
        raise d.Hold('reached the owner read')
    monkeypatch.setattr(d, '_owner_of', past_the_check)
    out = run(d.dispatch(claimed(m, first)))
    assert out == {'status': 'approved', 'claimed_at': None, 'error': d.RETRY}, 'the standing check let it through'
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, 'sb_get_as_service',
                        lambda path: None if path.startswith('/businesses') else real(path))
    out = run(d.dispatch(claimed(m, first)))
    assert out['status'] == 'approved' and m.db.posts[first['id']]['approved_via'] == 'standing'
    assert not notes(m, 'marketing_standing_held:')


def test_the_sweep_puts_lapsed_posts_back_at_once_and_a_revoke_quietly(m):
    grant(m, 'marketing_post', 'post_clip')
    planned(m)
    settings(m)['automations_paused'] = True
    out = tick(m)
    assert out['standing_withdrawn'] == 7 and {p['status'] for p in posts_of(m, PRO)} == {'draft'}
    assert all(p['error'] == standing.withdrawn_note(standing.PAUSED) for p in posts_of(m, PRO))
    assert len(notes(m, 'marketing_standing_held:')) == 2, 'once per kind put back'
    assert 'standing_withdrawn' not in tick(m)
    # The owner's own revoke: back to waiting, without being told about it.
    m2_posts = posts_of(m, PRO)
    for p in m2_posts:
        m.db.posts[p['id']].update(status='approved', approved_via='standing', approved_by=PRO_OWNER,
                                   approved_hash=p['content_hash'], error=None)
    settings(m)['automations_paused'] = False
    m.user = PRO_OWNER
    r = m.client.post('/agents/chief/standing', json={'business_id': PRO, 'verb': 'marketing_post', 'grant': False})
    assert r.status_code == 200 and r.json()['granted'] is False
    out = tick(m)
    assert out['standing_withdrawn'] == 5 and {p['status'] for p in plan_posts(m)} == {'draft'}
    assert {p['status'] for p in clip_posts(m)} == {'approved'}, 'the clip grant still stands'
    assert len(notes(m, 'marketing_standing_held:')) == 2


# ── 4. ask after three ────────────────────────────────────────────────

def test_the_third_clean_approval_asks_once(m):
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    assert not approvals(m), 'no grant: nothing approved by Chief'
    assert 'standing_offer' not in approve_as_owner(m, flyers[0])
    assert 'standing_offer' not in approve_as_owner(m, flyers[1])
    body = approve_as_owner(m, flyers[2])
    offer = body['standing_offer']
    assert offer['verb'] == 'marketing_post' and 'last 3 weekly posts' in offer['question']
    assert sp.offered(m.svc.businesses[PRO], 'marketing_post')
    said = notes(m, 'marketing_standing_offer:marketing_post')
    assert len(said) == 1 and said[0]['action_payload']['standing_offer'] == 'marketing_post'
    assert any(p['title'] == 'Want Chief to approve your weekly posts?' for p in m.pushes)
    assert 'standing_offer' not in approve_as_owner(m, flyers[3]), 'asked once'
    assert len(notes(m, 'marketing_standing_offer:')) == 1
    # The desk shows the open question until the owner answers it.
    block = standing.desk_block(m.svc.businesses[PRO])
    assert block['kinds'][0]['offer'] == offer['question'] and block['kinds'][0]['granted'] is False
    grant(m, 'marketing_post')
    assert standing.desk_block(m.svc.businesses[PRO])['kinds'][0]['offer'] is None


def test_an_edited_approval_does_not_count_toward_the_question(m):
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    approve_as_owner(m, flyers[0])
    edit(m, m.db.posts[flyers[1]['id']])
    approve_as_owner(m, m.db.posts[flyers[1]['id']])
    assert 'standing_offer' not in approve_as_owner(m, flyers[2])
    assert 'standing_offer' not in approve_as_owner(m, flyers[3]), 'the edited one is among the last three'
    assert 'standing_offer' in approve_as_owner(m, flyers[4])


def test_the_question_never_comes_without_the_plan(m):
    m.svc.businesses[PRO]['comp_tier'] = 'professional'
    run(plan.run_week(PRO, trigger='scheduled'))
    finish(m)
    tick(m)
    for p in plan_posts(m)[:4]:
        assert 'standing_offer' not in approve_as_owner(m, p)
    assert not notes(m, 'marketing_standing_offer:')


# ── 5. retire after three ─────────────────────────────────────────────

def test_three_standing_approvals_overridden_retire_the_grant_and_tell(m):
    grant(m, 'marketing_post')
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    m.user = PRO_OWNER
    edit(m, m.db.posts[flyers[0]['id']])
    assert take_back(m, m.db.posts[flyers[1]['id']]).status_code == 200
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO]), 'two is not three'
    skip(m, m.db.posts[flyers[2]['id']])
    assert 'marketing_post' not in sp.granted(m.svc.businesses[PRO]), 'retired'
    revoke = [a for a in m.audit if a['verb'] == 'standing_revoke']
    assert revoke and revoke[-1]['source'] == 'retire' and revoke[-1]['actor_type'] == 'chief'
    for p in flyers[3:]:
        after = m.db.posts[p['id']]
        assert after['status'] == 'draft' and after['error'] == standing.withdrawn_note(standing.RETIRED)
    told = notes(m, 'marketing_standing_retired:marketing_post')
    assert len(told) == 1 and told[0]['title'] == "I'm back to asking before your weekly posts"
    assert not notes(m, 'marketing_standing_held:'), 'told once, about the retire'
    assert any(p['title'] == "I'm back to asking before your weekly posts" for p in m.pushes)


@pytest.mark.parametrize('third', ['edit', 'take_back', 'skip', 'not_sent'])
def test_each_override_route_can_be_the_third_that_retires_it(m, third):
    grant(m, 'marketing_post')
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    m.user = PRO_OWNER
    edit(m, m.db.posts[flyers[0]['id']])
    skip(m, m.db.posts[flyers[1]['id']])
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO])
    target = m.db.posts[flyers[2]['id']]
    if third == 'edit':
        edit(m, target)
    elif third == 'take_back':
        assert take_back(m, target).status_code == 200
    elif third == 'skip':
        skip(m, target)
    else:
        m.now += timedelta(minutes=1)
        target.update(status='uncertain')                 # it went out, unconfirmed
        m.ev.snap()
        m.now += timedelta(minutes=1)
        r = m.client.post(f"/marketing/{PRO}/posts/{target['id']}/not-sent", json={'revision': target['revision']})
        assert r.status_code == 200, r.text
    assert 'marketing_post' not in sp.granted(m.svc.businesses[PRO]), third
    assert len(notes(m, 'marketing_standing_retired:marketing_post')) == 1


def test_a_post_that_went_out_ends_the_run(m):
    grant(m, 'marketing_post')
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    m.user = PRO_OWNER
    edit(m, m.db.posts[flyers[0]['id']])
    assert take_back(m, m.db.posts[flyers[1]['id']]).status_code == 200
    m.now += timedelta(minutes=1)
    m.db.posts[flyers[2]['id']].update(status='submitted')        # this one went out
    m.ev.snap()
    skip(m, m.db.posts[flyers[3]['id']])
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO]), 'skipped, sent, taken back: not three in a row'
    edit(m, m.db.posts[flyers[4]['id']])
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO]), 'edited, skipped, sent: still not'
    assert not notes(m, 'marketing_standing_retired:')


def test_marked_not_sent_counts_and_withdrawn_does_not(m):
    grant(m, 'marketing_post')
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    for p in flyers[:2]:
        m.now += timedelta(minutes=1)
        m.db.posts[p['id']].update(status='uncertain', revision=m.db.posts[p['id']]['revision'])
        m.ev.snap()
        m.user = PRO_OWNER
        r = m.client.post(f"/marketing/{PRO}/posts/{p['id']}/not-sent",
                          json={'revision': m.db.posts[p['id']]['revision']})
        assert r.status_code == 200, r.text
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO])
    # Chief's own withdrawal (autonomy turned off and on again) is not the owner's.
    settings(m).setdefault('autonomy', {})['client_facing_autonomy'] = 'disabled'
    tick(m)
    settings(m)['autonomy']['client_facing_autonomy'] = 'enabled'
    assert m.db.posts[flyers[2]['id']]['status'] == 'draft'
    hist = run(standing.history(PRO, 'marketing_post', m.now))
    fates = {a['post_id']: a['fate'] for a in hist if a['via'] == 'standing'}
    assert [fates[p['id']] for p in flyers] == ['not_sent', 'not_sent', 'withdrawn', 'withdrawn', 'withdrawn']
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO])


def test_the_history_reads_each_approval_and_what_became_of_it():
    def ev(i, pid, status, rev, via=None, at=None, h='h1', ah=None, design='ready', error=None, run_at=None):
        return {'id': i, 'post_id': pid, 'status': status, 'revision': str(rev), 'via': via, 'approved_at': at,
                'hash': h, 'approved_hash': ah, 'design': design, 'error': error,
                'run_at': run_at or '2026-10-12T16:00:00+00:00',
                'created_at': (datetime(2026, 10, 8, 15, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat()}
    a1, a2 = '2026-10-08T15:00:00+00:00', '2026-10-09T15:00:00+00:00'
    events = [
        ev(1, 'p1', 'draft', 1, design='designing', h='h0'), ev(2, 'p1', 'draft', 2),
        ev(3, 'p1', 'approved', 2, 'standing', a1, ah='h1'), ev(4, 'p1', 'dispatching', 2, 'standing', a1, ah='h1'),
        ev(5, 'p1', 'published', 2, 'standing', a1, ah='h1'),
        ev(6, 'p2', 'draft', 1), ev(7, 'p2', 'approved', 1, 'standing', a1, ah='h1'), ev(8, 'p2', 'draft', 2, h='h9'),
        ev(9, 'p3', 'draft', 1), ev(10, 'p3', 'approved', 1, 'standing', a1, ah='h1'),
        ev(11, 'p3', 'cancelled', 2, 'standing', a1, ah='h1'),
        ev(12, 'p4', 'draft', 1), ev(13, 'p4', 'approved', 1, 'standing', a1, ah='h1'),
        ev(14, 'p4', 'draft', 2, error=standing.withdrawn_note('x')),
        ev(15, 'p5', 'draft', 1), ev(16, 'p5', 'approved', 1, 'standing', a1, ah='h1'),
        ev(17, 'p5', 'draft', 2, h='h2', run_at='2026-10-09T15:02:00+00:00'),
        ev(18, 'p5', 'approved', 2, 'owner', a2, h='h2', ah='h2', run_at='2026-10-09T15:02:00+00:00'),
        ev(19, 'p6', 'draft', 3), ev(20, 'p6', 'approved', 3, 'owner', a1, ah='h1'),     # its first snapshot is gone
        ev(21, 'p7', 'draft', 1), ev(22, 'p7', 'approved', 1, 'owner', a1, ah='h1'),
        ev(23, 'p7', 'uncertain', 1, 'owner', a1, ah='h1'),
        ev(24, 'p7', 'failed', 2, 'owner', a1, ah='h1', error=bm.NOT_SENT_NOTE),
        ev(25, 'p7', 'draft', 3, h='h3'),
    ]
    got = {(a['post_id'], a['via']): a for a in standing.approvals_from(events)}
    assert got[('p1', 'standing')]['fate'] == 'sent' and got[('p1', 'standing')]['chief_hash'] == 'h1'
    assert got[('p2', 'standing')]['fate'] == 'edited'
    assert got[('p3', 'standing')]['fate'] == 'skipped'
    assert got[('p4', 'standing')]['fate'] == 'withdrawn'
    assert got[('p5', 'standing')]['fate'] == 'posted_now' and got[('p5', 'owner')]['fate'] == 'waiting'
    assert ('p6', 'owner') not in got
    assert got[('p7', 'owner')]['fate'] == 'not_sent', 'an edit after it settled does not change what happened'
    since = datetime(2026, 10, 1, tzinfo=timezone.utc)
    mine = list(got.values())
    assert not standing.retires(mine, since), 'p5 was posted now: among the last three outcomes'
    assert got[('p3', 'standing')]['settled_at'] == events[10]['created_at'], 'settled when it was skipped'
    assert standing.retires([got[('p2', 'standing')], got[('p3', 'standing')], got[('p7', 'owner')] | {'via': 'standing'}],
                            since)
    assert not standing.retires([got[('p2', 'standing')], got[('p3', 'standing')]], since), 'two is not three'
    assert not standing.retires([got[('p2', 'standing')], got[('p3', 'standing')], got[('p3', 'standing')]],
                                datetime(2026, 10, 10, tzinfo=timezone.utc)), 'before the grant does not count'


# ── 6. take back ──────────────────────────────────────────────────────

def test_take_back_puts_an_approved_post_back_to_a_draft_until_it_is_claimed(m):
    grant(m, 'marketing_post')
    planned(m, clips=False)
    flyers = sorted(plan_posts(m), key=lambda p: p['run_at'])
    post = m.db.posts[flyers[0]['id']]
    before = copy.deepcopy(post)
    assert take_back(m, post, user=MEMBER).status_code == 403
    stale = take_back(m, {**post, 'revision': post['revision'] + 5})
    assert stale.status_code == 409
    r = take_back(m, post)
    assert r.status_code == 200, r.text
    after = m.db.posts[post['id']]
    assert after['status'] == 'draft' and after['revision'] == before['revision'] + 1
    assert after['approved_via'] is None and after['approved_by'] is None
    assert after['content_hash'] == before['content_hash'] and after['caption'] == before['caption']
    assert r.json()['post']['status'] == 'draft'
    going = claimed(m, flyers[1])
    assert take_back(m, going).status_code == 409, 'already going out'
    # The owner's own approval can be taken back too, and it is not Chief's to count.
    owner_approved = m.db.posts[post['id']]
    approve_as_owner(m, owner_approved)
    assert take_back(m, m.db.posts[post['id']]).status_code == 200
    assert 'marketing_post' in sp.granted(m.svc.businesses[PRO])


# ── 7. guards ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('tier', ['professional', 'boss', 'starter'])
def test_no_other_plan_is_ever_approved_on_a_standing_ok_even_with_a_grant_written_in(m, tier):
    m.svc.businesses[PRO]['comp_tier'] = tier
    settings(m)['autonomy'] = {'standing': {k: {'granted_at': '2026-10-01T00:00:00Z', 'granted_by': PRO_OWNER,
                                                'via': 'app'} for k in ALL}}
    biz = m.svc.businesses[PRO]
    assert not standing.covers(biz, 'marketing_post')[0] and not standing.covers(biz, 'post_clip')[0]
    if tier == 'professional':
        run(plan.run_week(PRO, trigger='scheduled'))
        finish(m)
        tick(m)
        assert plan_posts(m) and {p['status'] for p in plan_posts(m)} == {'draft'}
    rid = str(uuid4())
    assert run(standing.approve_run(copy.deepcopy(biz), rid, m.now)) == []
    assert not approvals(m)
    assert standing.desk_block(biz)['kinds'][0]['available'] is False


def test_only_the_two_kinds_are_ever_approved(m):
    grant(m, 'marketing_post', 'post_clip')
    planned(m, clips=False)
    rid = run_of(m, PRO)['id']
    template = plan_posts(m, 'approved')[0]
    for source in ('suggestion', 'opening', 'owner', 'chief'):
        pid = str(uuid4())
        row = {**copy.deepcopy(template), 'id': pid, 'source': source, 'status': 'draft', 'approved_hash': None,
               'approved_by': None, 'approved_via': None, 'approved_at': None, 'revision': 1}
        row['content_hash'] = store.digest(row)
        m.db.posts[pid] = row
    before = len(approvals(m))
    assert run(standing.approve_run(copy.deepcopy(m.svc.businesses[PRO]), rid, m.now)) == []
    assert len(approvals(m)) == before
    assert {standing.kind_of({'source': s}) for s in ('suggestion', 'opening', 'owner', 'chief')} == {None}


def test_a_boss_open_chairs_week_and_a_suggestion_never_reach_the_standing_ok(m, monkeypatch):
    called = []

    async def spy(*a, **k):
        called.append(a)
        return []
    monkeypatch.setattr(standing, 'approve_run', spy)
    import inspect
    assert 'approve_run' not in inspect.getsource(plan.tell_openings)
    assert 'approve_run' not in inspect.getsource(plan.run_suggestion)
    assert 'approve_run' in inspect.getsource(plan.tell_week)
    assert BOSS in m.svc.businesses and not called


def test_chiefs_own_post_clip_proposals_never_ride_the_marketing_grant(m):
    grant(m, 'post_clip')
    biz = copy.deepcopy(m.svc.businesses[PRO])
    assert sp.is_granted(biz, 'post_clip')
    assert sp.filing_extras(biz, 'post_clip') == {}, 'no release time for a proposal'
    assert sp.offer_after_approval(biz, 'post_clip', moves=[]) is None
    lines = sp.context_lines(biz)
    assert len(lines) == 1 and 'marketing desk' in lines[0] and 'minute window' not in lines[0]


def test_the_desk_shows_the_standing_ok_to_the_owner_and_members(m, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    grant(m, 'marketing_post')
    api = FastAPI()
    api.include_router(bm.router)
    api.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=m.user))
    monkeypatch.setattr(business_access, '_resolve_role',
                        lambda bid, uid: 'owner' if uid == PRO_OWNER else ('member' if uid == MEMBER else None))
    client = TestClient(api)
    for who in (PRO_OWNER, MEMBER):
        m.user = who
        r = client.get(f'/marketing/{PRO}/engine')
        assert r.status_code == 200, r.text
        kinds = {k['kind']: k for k in r.json()['standing']['kinds']}
        assert kinds['marketing_post']['granted'] and kinds['marketing_post']['active']
        assert kinds['post_clip']['available'] and not kinds['post_clip']['granted']
    settings(m)['autonomy']['client_facing_autonomy'] = 'disabled'
    m.user = PRO_OWNER
    kinds = {k['kind']: k for k in client.get(f'/marketing/{PRO}/engine').json()['standing']['kinds']}
    assert kinds['marketing_post']['active'] is False and kinds['marketing_post']['held'] == sp.AUTONOMY_OFF
    # A member reads it but never changes it.
    m.user = MEMBER
    r = m.client.post('/agents/chief/standing', json={'business_id': PRO, 'verb': 'marketing_post', 'grant': False})
    assert r.status_code == 403 and 'marketing_post' in sp.granted(m.svc.businesses[PRO])


def test_a_grant_given_before_the_owner_changed_covers_nothing(m):
    grant(m, 'marketing_post')
    m.svc.businesses[PRO]['owner_id'] = BIZ.replace('0a1b', 'ffff')
    assert standing.covers(m.svc.businesses[PRO], 'marketing_post') == (False, standing.NEW_OWNER)


def test_the_kill_switch_stops_every_standing_approval(m, monkeypatch):
    grant(m, 'marketing_post')
    monkeypatch.setenv('STANDING_PERMISSIONS', 'off')
    planned(m, clips=False)
    assert not approvals(m) and {p['status'] for p in plan_posts(m)} == {'draft'}
    assert notes(m, 'marketing_week:')[0]['title'].startswith('Chief planned next week')
