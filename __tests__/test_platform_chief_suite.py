"""With the suite on, Platform Chief, MC Today and the Chief digest work the
suite desk (B15b, platform_chief_suite.py).

  1. Switch off: nothing here is reached (no verdict read, no new verb, the
     Buffer desk's card, Today, digest, prompt and snapshot as before).
  2. Suite active: each Platform Chief verb runs B10's own handler for the
     platform business only, through the real dispatch (ledger, card,
     decision); post-now and replan are always a card and refused
     unattended; there is no approve verb; a tag naming another business is
     refused.
  3. MC Today and the digest read the suite desk (waiting, the standing OK,
     failures, unconfirmed, pulled) and keep the Buffer desk's leftovers
     while it drains; a failed read says "couldn't read".

No network: the desk's tables are the B4 suite's in-memory PostgREST
(test_business_marketing_api.FakeStore / FakeService), the ledger is the
authority suite's fake, the Buffer desk's tables are a fake `db`.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import business_marketing as bm
import business_marketing_planner as planner
import business_marketing_store as store
import chief_marketing_actions as cma
import marketing_desk
import platform_chief_actions as actions
import platform_chief_authority as authority
import platform_chief_marketing as pcm
import platform_chief_suite as suite
import platform_marketing as m
import platform_suite
import platform_today as pt
import rate_limit
import sb_clients
import spend_guard
from auth_supabase import require_user, require_user_session, UserSession
from lead_admin import PLATFORM_OWNER_EMAIL

import __tests__.test_business_marketing_api as api

run = asyncio.run

PID = 'b1500000-0000-4000-8000-000000000015'          # Solutionist's own business
KEVIN = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'        # its owner, the platform owner
PFB = 'c1500000-0000-4000-8000-000000000001'
PIG = 'c1500000-0000-4000-8000-000000000002'
OWNER = SimpleNamespace(id=KEVIN, email=PLATFORM_OWNER_EMAIL)
NOT_PERMITTED = 'This action is not permitted.'


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
    platform_suite.forget()


class SuiteStore(api.FakeStore):
    """B4's store, plus marketing_runs written by the owner's request."""

    async def request(self, method, path, body=None):
        if path.split('?', 1)[0] == '/marketing_runs' and method != 'GET':
            self.writes.append((method, path, copy.deepcopy(body)))
            self.runs.append({**copy.deepcopy(body), 'created_at': api.NOW.isoformat()})
            return [copy.deepcopy(body)]
        return await super().request(method, path, body)


@pytest.fixture
def pc(monkeypatch):
    """The suite active for PID, the desk's tables, the ledger, the Buffer desk's tables."""
    platform_suite.forget()
    verdict = SimpleNamespace(reads=[], fail=False)

    def read_business(bid):
        verdict.reads.append(bid)
        if verdict.fail:
            return None
        return [{'id': PID, 'owner_id': KEVIN, 'platform_books': 'true'}] if bid == PID else \
            [{'id': bid, 'owner_id': api.OWNER, 'platform_books': None}]

    def owner_email(owner_id):
        verdict.reads.append(('auth', owner_id))
        return PLATFORM_OWNER_EMAIL if str(owner_id) == KEVIN else 'owner@fadestreet.com'
    monkeypatch.setattr(platform_suite, '_read_business', read_business)
    monkeypatch.setattr(platform_suite, '_owner_email', owner_email)
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
    monkeypatch.setattr(planner, '_now', lambda: api.NOW)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda business_id=None: False)
    rate_limit._buckets.clear()

    # The ledger (platform_chief_authorizations), as the authority suite fakes it.
    ledger, policy = {}, {'drafts': 'allow', 'creative': 'ask', 'notes': 'allow', 'marketing_stop': 'allow'}

    async def ledger_db(method, path, body=None):
        if path.startswith('/platform_chief_permissions'):
            return [{'revision': 1, 'settings': dict(policy)}]
        if path == '/rpc/platform_chief_propose':
            rid = body['p_id']
            if rid not in ledger:
                ledger[rid] = dict(id=rid, owner_id=body['p_owner'], request_id=body['p_request'],
                                   action=body['p_action'], action_hash=body['p_hash'], automatic=body['p_automatic'],
                                   status='pending', expires_at=(authority.now() + timedelta(hours=24)).isoformat(),
                                   result=None)
            return [copy.deepcopy(ledger[rid])]
        if path.startswith('/platform_chief_authorizations?id=eq.'):
            rid = path.split('id=eq.')[1].split('&')[0]
            row = ledger.get(rid)
            if not row or f"owner_id=eq.{row['owner_id']}" not in path:
                return []
            if method == 'GET':
                return [copy.deepcopy(row)]
            required = 'pending' if '&status=eq.pending' in path else 'executing'
            if row['status'] != required:
                return []
            row.update(body)
            return [copy.deepcopy(row)]
        raise AssertionError((method, path))
    monkeypatch.setattr(authority, 'db', ledger_db)
    logged = []

    async def log_action(**kw):
        logged.append(kw)
    monkeypatch.setattr(actions, '_log_action', log_action)

    # The Buffer desk's own tables (marketing_desk.read_state, buffer_week_live).
    state = SimpleNamespace(db=db, svc=svc, ledger=ledger, policy=policy, logged=logged, verdict=verdict,
                            buffer_posts=[], buffer_runs=[], buffer_fail=False, buffer_live=False)

    async def buffer_db(method, path, body=None):
        assert method == 'GET', ('nothing is written to the Buffer desk', method, path)
        if state.buffer_fail:
            raise HTTPException(503, 'Marketing storage is unavailable. Please retry.')
        if path.startswith('/platform_marketing_runs?'):
            return copy.deepcopy(state.buffer_runs)
        if path.startswith('/platform_marketing_posts?run_id=eq.'):
            return [{'id': 'live'}] if state.buffer_live else []
        if path.startswith('/platform_marketing_posts?'):
            return copy.deepcopy(state.buffer_posts)
        raise AssertionError(path)

    async def buffer_config():
        if state.buffer_fail:
            raise HTTPException(503, 'Marketing storage is unavailable. Please retry.')
        return {'paused': False, 'channels': [{'id': 'ch-1', 'service': 'facebook'}]}
    monkeypatch.setattr(m, 'db', buffer_db)
    monkeypatch.setattr(m, 'config', buffer_config)
    monkeypatch.setattr(m, 'now', lambda: api.NOW)
    return state


def seed(pc, **over):
    return api.seed(pc, biz=PID, targets=over.pop('targets', (PFB,)), **over)


def dispatch(*acts, request_id=None):
    return run(actions.dispatch_actions([dict(a) for a in acts], owner=OWNER, request_id=request_id or uuid4()))


def decide(pc, approval_id, decision='approve'):
    app = FastAPI()
    app.include_router(authority.router)
    app.dependency_overrides[require_user] = lambda: OWNER
    app.dependency_overrides[require_user_session] = lambda: UserSession(OWNER, 'verified-test-token')
    row = pc.ledger[approval_id]
    r = TestClient(app).post(f'/platform/chief/approvals/{approval_id}/decision',
                             json={'action_hash': row['action_hash'], 'decision': decision})
    assert r.status_code == 200, r.text
    return r.json()


def shaped(out):
    """Platform Chief's reply shape: ok, and a label (and result) in words."""
    assert isinstance(out.get('ok'), bool), out
    assert isinstance(out.get('label'), str) and out['label'].strip(), out
    if 'result' in out:
        assert out['result'] == out['label'], out
    return out


@pytest.fixture
def spy(monkeypatch):
    """Which B10 handler ran, for which business."""
    calls = []
    for verb in ('marketing_desk', 'marketing_new_post', 'marketing_edit_post', 'marketing_skip_post',
                 'marketing_replan', 'marketing_post_now'):
        name = f'handle_{verb}'
        real = getattr(cma, name)

        def make(real, verb):
            async def wrapped(client, biz, action):
                calls.append((verb, str(biz['id']), dict(action)))
                return await real(client, biz, action)
            return wrapped
        monkeypatch.setattr(cma, name, make(real, verb))
    return calls


# ── 1. switch off: nothing changes ────────────────────────────────────

def test_with_the_switch_off_nothing_here_is_reached(monkeypatch):
    platform_suite.forget()
    switch(monkeypatch, on=False)

    def no_read(*a, **k):
        raise AssertionError('no verdict is read with the switch off')
    monkeypatch.setattr(platform_suite, '_read_business', no_read)
    monkeypatch.setattr(platform_suite, '_owner_email', no_read)
    assert suite.active() is False
    assert suite.handlers(OWNER, uuid4()) == {}
    for action in ({'type': 'marketing_post_now', 'caption': 'x', 'channels': ['X'], 'channel_ids': ['x']},
                   {'type': 'marketing_new_post', 'text': 'x'}, {'type': 'send_practitioner_email'}):
        assert suite.card_handlers(OWNER, uuid4(), action) == {}

    async def buffer_review(payload):
        return {'type': 'marketing_post_now', 'buffer': True, 'caption': payload['text']}
    monkeypatch.setattr(pcm, 'post_now_review', buffer_review)
    assert run(suite.post_now_review({'type': 'marketing_post_now', 'text': 'Out now.'})) == \
        {'type': 'marketing_post_now', 'buffer': True, 'caption': 'Out now.'}

    async def state():
        return {'buffer': True}
    monkeypatch.setattr(marketing_desk, 'read_state', state)
    monkeypatch.setattr(marketing_desk, 'today_items', lambda s: [{'id': 'buffer-desk', 'from': s}])
    assert run(pt._marketing()) == [{'id': 'buffer-desk', 'from': {'buffer': True}}]


@pytest.mark.parametrize('verb', ['marketing_desk', 'marketing_edit_post', 'marketing_skip_post', 'marketing_replan'])
def test_with_the_switch_off_the_suite_verbs_are_not_permitted_as_before(monkeypatch, verb):
    switch(monkeypatch, on=False)

    async def no_db(*a, **k):
        raise AssertionError('no card is written for a verb that is not permitted')

    async def policy(owner_id):
        return {'settings': dict(authority.DEFAULTS)}
    monkeypatch.setattr(authority, 'db', no_db)
    monkeypatch.setattr(authority, 'policy', policy)
    logged = []

    async def log_action(**kw):
        logged.append(kw)
    monkeypatch.setattr(actions, '_log_action', log_action)
    out = dispatch({'type': verb, 'post_id': str(uuid4()), 'revision': 1})
    assert out == [{'ok': False, 'type': verb, 'label': NOT_PERMITTED}]


def test_the_console_uses_the_buffer_prompt_off_and_the_suite_prompt_on(monkeypatch):
    import llm_call
    import platform_console as console
    from unittest.mock import AsyncMock
    captured = {}
    monkeypatch.setattr(authority, 'require_budget', AsyncMock())

    async def snapshot(*args):
        return {'known_fact': 'Current business data'}

    async def buffer_data():
        return {'config': {'channels': [{'id': 'buffer-account'}]}}

    async def suite_data(owner):
        assert owner.id == KEVIN
        return {'suite': {'on': True}, 'desk': {'posts': [{'post_id': 'suite-post'}]}}

    async def call(client, payload, **kwargs):
        captured.update(payload)
        return SimpleNamespace(status_code=200, json=lambda: {'content': [{'type': 'text', 'text': 'Here.'}],
                                                                'usage': {}})

    async def noop(**kwargs):
        pass
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only')
    monkeypatch.setattr(console, '_service_headers', lambda: {})
    monkeypatch.setattr(console, '_build_snapshot', snapshot)
    monkeypatch.setattr(console, 'marketing_snapshot', buffer_data)
    monkeypatch.setattr(suite, 'snapshot', suite_data)
    monkeypatch.setattr(console, 'log_api_usage', noop)
    monkeypatch.setattr(llm_call, 'apost', call)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda: False)
    monkeypatch.setattr(rate_limit, 'allow', lambda *a: True)
    app = FastAPI()
    app.include_router(console.router)
    app.dependency_overrides[require_user] = lambda: OWNER
    app.dependency_overrides[require_user_session] = lambda: UserSession(OWNER, 'verified-test-jwt')
    client = TestClient(app)
    switch(monkeypatch, on=False)
    assert client.post('/platform/chief/message', json={'message': 'Posts?', 'context': 'marketing'}).status_code == 200
    assert pcm.MARKETING_PROMPT in captured['system'] and marketing_desk.DIGEST_PROMPT in captured['system']
    assert 'buffer-account' in captured['system'] and suite.PROMPT not in captured['system']
    monkeypatch.setattr(suite, 'active', lambda: True)
    assert client.post('/platform/chief/message', json={'message': 'Posts?', 'context': 'marketing'}).status_code == 200
    assert suite.PROMPT in captured['system'] and suite.DIGEST_PROMPT in captured['system']
    assert 'suite-post' in captured['system'] and 'buffer-account' not in captured['system']
    assert pcm.MARKETING_PROMPT not in captured['system'] and marketing_desk.DIGEST_PROMPT not in captured['system']


# ── 2. the verbs on the suite desk ────────────────────────────────────

def test_a_new_post_is_a_chief_draft_on_the_platform_desk(pc, spy):
    [out] = dispatch({'type': 'marketing_new_post', 'caption': 'One place for your clients, bookings and money.',
                      'platforms': ['facebook']})
    shaped(out)
    assert out['ok'] is True and out['type'] == 'marketing_new_post' and out['approval']['status'] == 'done'
    assert 'Mission Control → Growth → Marketing' in out['label'] and 'Grow → Marketing' not in \
        out['label'].replace('Growth → Marketing', '')
    [row] = pc.db.posts.values()
    assert row['business_id'] == PID and row['source'] == 'chief' and row['status'] == 'draft'
    assert {t['connection_id'] for t in row['targets']} == {PFB}
    assert spy == [('marketing_new_post', PID, spy[0][2])] and '_unattended' not in spy[0][2]
    assert all(b.get('business_id') == PID for meth, p, b in pc.db.writes if meth == 'POST')


def test_the_buffer_spelling_of_a_new_post_lands_on_the_suite_desk_too(pc):
    [out] = dispatch({'type': 'marketing_new_post', 'text': 'Your week, in one place.', 'channels': ['facebook']})
    assert out['ok'] is True
    [row] = pc.db.posts.values()
    assert row['caption'] == 'Your week, in one place.' and row['business_id'] == PID


def test_edit_and_skip_run_the_desks_own_functions_for_the_platform_business(pc, spy):
    a, b = seed(pc), seed(pc)
    [edit] = dispatch({'type': 'marketing_edit_post', 'post_id': a['id'], 'revision': a['revision'],
                       'caption': 'Your week, in one place.'})
    assert shaped(edit)['ok'] is True and edit['revision'] == 2 and edit['status'] == 'draft'
    assert pc.db.posts[a['id']]['caption'] == 'Your week, in one place.' and pc.db.posts[a['id']]['revision'] == 2
    [skip] = dispatch({'type': 'marketing_skip_post', 'post_id': b['id'], 'revision': b['revision']})
    assert shaped(skip)['ok'] is True and pc.db.posts[b['id']]['status'] == 'cancelled'
    assert [(v, biz) for v, biz, _ in spy] == [('marketing_edit_post', PID), ('marketing_skip_post', PID)]
    # Stale: the revision Chief read moved on.
    [stale] = dispatch({'type': 'marketing_edit_post', 'post_id': a['id'], 'revision': 1, 'caption': 'Old.'})
    assert shaped(stale)['ok'] is False and stale.get('stale') is True and pc.db.posts[a['id']]['revision'] == 2


def test_the_read_lists_the_platform_desk_and_never_a_tenants_posts(pc, spy):
    mine = seed(pc, caption='One place for your clients.')
    api.seed(pc, targets=(api.FB,))                                   # a tenant's post
    [out] = dispatch({'type': 'marketing_desk'})
    shaped(out)
    assert out['ok'] is True and out['level'] == 'autopilot' and out['time_zone'] == 'America/New_York'
    assert [p['post_id'] for p in out['posts']] == [mine['id']]
    assert pc.ledger == {}                                           # a read is never a card
    assert spy[0][:2] == ('marketing_desk', PID)


def test_a_tag_naming_another_business_is_refused_and_a_tenants_post_is_not_found(pc, spy):
    theirs = api.seed(pc, targets=(api.FB,))
    before = copy.deepcopy(pc.db.posts)
    for act in ({'type': 'marketing_new_post', 'caption': 'Taken over.', 'business_id': api.BIZ},
                {'type': 'marketing_edit_post', 'post_id': theirs['id'], 'revision': 1, 'caption': 'x',
                 'business_id': api.BIZ},
                {'type': 'marketing_desk', 'business_id': api.BIZ}):
        [out] = dispatch(act)
        assert shaped(out)['ok'] is False and "Solutionist's own marketing desk" in out['label'], out
    assert spy == [] and pc.db.posts == before
    for act in ({'type': 'marketing_edit_post', 'post_id': theirs['id'], 'revision': 1, 'caption': 'x'},
                {'type': 'marketing_skip_post', 'post_id': theirs['id'], 'revision': 1}):
        [out] = dispatch(act)
        assert out['ok'] is False and "couldn't find that post" in out['label']
    assert pc.db.posts == before and all(biz == PID for _, biz, _ in spy)


def test_post_now_is_a_card_that_freezes_the_post_and_runs_on_the_owners_yes(pc, spy):
    a = seed(pc)
    [card] = dispatch({'type': 'marketing_post_now', 'post_id': a['id'], 'revision': a['revision'],
                       'business_id': PID})
    approval = card['approval']
    assert card['ok'] is False and approval['status'] == 'pending' and spy == []
    frozen = approval['action']
    assert frozen['desk'] == 'suite' and frozen['business_id'] == PID and frozen['post_id'] == a['id']
    assert frozen['content_hash'] == a['content_hash'] and frozen['caption'] == a['caption']
    assert frozen['accounts'] == ['Facebook'] and pc.db.posts[a['id']]['status'] == 'draft'
    out = decide(pc, approval['id'])
    assert out['ok'] is True and out['approval']['status'] == 'done' and 'goes out at' in out['label']
    row = pc.db.posts[a['id']]
    assert row['status'] == 'approved' and row['approved_by'] == KEVIN
    assert spy[-1][:2] == ('marketing_post_now', PID) and spy[-1][2]['_unattended'] is False


def test_post_now_refuses_a_post_that_changed_after_its_card(pc):
    a = seed(pc)
    [card] = dispatch({'type': 'marketing_post_now', 'post_id': a['id'], 'revision': a['revision']})
    [edit] = dispatch({'type': 'marketing_edit_post', 'post_id': a['id'], 'revision': a['revision'],
                       'caption': 'Changed meanwhile.'})
    assert edit['ok'] is True
    out = decide(pc, card['approval']['id'])
    assert out['ok'] is False and out['label'] == suite.CHANGED_SINCE_CARD
    assert pc.db.posts[a['id']]['status'] == 'draft'


def test_a_new_post_now_card_freezes_its_words_and_accounts(pc):
    [card] = dispatch({'type': 'marketing_post_now', 'caption': 'Doors open today.', 'platforms': ['facebook']})
    frozen = card['approval']['action']
    assert frozen['caption'] == 'Doors open today.' and frozen['platforms'] == ['facebook']
    assert frozen['accounts'] == ['Facebook'] and pc.db.posts == {}
    out = decide(pc, card['approval']['id'])
    assert out['ok'] is True, out
    [row] = pc.db.posts.values()
    assert row['business_id'] == PID and row['source'] == 'chief' and row['status'] == 'approved'
    assert row['caption'] == 'Doors open today.'


@pytest.mark.parametrize('payload,words', [
    ({'post_ids': [str(uuid4())]}, 'post_id and revision'),
    ({'caption': 'New.', 'flyer': {'headline': 'Saturday', 'line': 'One line here.', 'cta': 'Come'}}, 'draft first'),
    ({'caption': 'Out.', 'platforms': ['tiktok']}, 'No TikTok account'),
    ({'post_id': str(uuid4()), 'revision': 1}, "couldn't find that post"),
    ({'caption': 'Out.', 'business_id': api.BIZ}, "Solutionist's own marketing desk"),
])
def test_a_post_now_card_that_cannot_be_made_is_that_actions_plain_answer(pc, payload, words):
    [out] = dispatch({'type': 'marketing_post_now', **payload})
    assert out['ok'] is False and words in out['label'] and pc.ledger == {} and pc.db.writes == []


@pytest.mark.parametrize('verb,body', [('marketing_post_now', {'caption': 'Out now.', 'platforms': ['facebook']}),
                                       ('marketing_replan', {})])
def test_class_c_is_refused_unattended(pc, spy, verb, body):
    """Run without the owner's approved card (no authorization, or an
    automatic one): refused before anything is read."""
    action = {'type': verb, **body}
    if verb == 'marketing_post_now':
        action = run(suite.post_now_review(action))
    handler = suite.card_handlers(OWNER, uuid4(), action)[verb]
    assert run(handler(action))['label'] == suite.NOT_CARD[verb][0]
    token = authority.current_authorization.set((OWNER, {'id': str(uuid4()), 'automatic': True}))
    try:
        assert run(handler(action))['label'] == suite.NOT_CARD[verb][0]
    finally:
        authority.current_authorization.reset(token)
    assert spy == [] and pc.db.writes == [] and pc.db.runs == []
    # Through dispatch, whatever the owner's policy says, it is a card.
    pc.policy.update(drafts='allow', marketing_stop='allow')
    [card] = dispatch(action if verb == 'marketing_replan' else {'type': verb, **body})
    assert card['approval']['status'] == 'pending' and pc.db.runs == [] and spy == []


def test_replan_on_the_owners_card_queues_the_platform_week(pc, spy):
    [card] = dispatch({'type': 'marketing_replan', 'business_id': PID})
    assert card['approval']['status'] == 'pending' and pc.db.runs == []
    out = decide(pc, card['approval']['id'])
    shaped(out)
    assert out['ok'] is True and out['queued'] is True and out['kind'] == 'week'
    [queued] = pc.db.runs
    assert queued['business_id'] == PID and queued['kind'] == 'week' and queued['trigger'] == 'manual'
    assert spy[-1][:2] == ('marketing_replan', PID) and spy[-1][2]['_unattended'] is False


def test_replan_respects_one_loop_a_week(pc):
    pc.buffer_live = True
    [card] = dispatch({'type': 'marketing_replan'})
    out = decide(pc, card['approval']['id'])
    assert out['ok'] is False and out['label'] == platform_suite.BUFFER_WEEK and pc.db.runs == []
    pc.buffer_fail = True
    [card] = dispatch({'type': 'marketing_replan'})
    out = decide(pc, card['approval']['id'])
    assert out['ok'] is False and out['label'] == platform_suite.BUFFER_WEEK_UNREAD and pc.db.runs == []


def test_there_is_no_approve_verb(pc):
    assert 'marketing_approve' not in authority.GROUPS and 'marketing_approve' not in actions.HANDLERS
    assert 'marketing_approve' not in suite.handlers(OWNER, uuid4())
    assert suite.card_handlers(OWNER, uuid4(), {'type': 'marketing_approve'}) == {}
    a = seed(pc)
    [out] = dispatch({'type': 'marketing_approve', 'items': [api.item(a)]})
    assert out == {'ok': False, 'type': 'marketing_approve', 'label': NOT_PERMITTED}
    assert pc.db.posts[a['id']]['status'] == 'draft' and pc.ledger == {}
    assert 'You NEVER approve a post' in suite.PROMPT


def test_switch_on_without_a_valid_business_keeps_the_buffer_verbs_and_says_so(pc, monkeypatch):
    switch(monkeypatch, on=True, pid=None)
    handlers = suite.handlers(OWNER, uuid4())
    assert 'marketing_new_post' not in handlers                         # the Buffer desk's own, as before
    [out] = dispatch({'type': 'marketing_desk'})
    assert out['ok'] is False and out['label'].startswith(platform_suite.NO_ID)
    switch(monkeypatch, on=True)
    pc.verdict.fail = True                                              # the business couldn't be confirmed
    [out] = dispatch({'type': 'marketing_edit_post', 'post_id': str(uuid4()), 'revision': 1, 'caption': 'x'})
    assert out['ok'] is False and out['label'].startswith(platform_suite.UNCONFIRMED)
    assert pc.db.writes == []


def test_the_owner_check_runs_too(pc):
    pc.svc.businesses[PID]['owner_id'] = str(uuid4())                   # the row no longer the signed-in owner's
    [out] = dispatch({'type': 'marketing_new_post', 'caption': 'x'})
    assert out['ok'] is False and out['label'].startswith(platform_suite.WRONG_ID) and pc.db.writes == []


# ── 3. MC Today and the digest ────────────────────────────────────────

def _buffer_post(status, hours, **over):
    at = api.NOW + timedelta(hours=hours)
    row = {'id': str(uuid4()), 'revision': 1, 'status': status, 'run_at': at.isoformat(),
           'expires_at': (at + timedelta(hours=6)).isoformat(), 'run_id': None, 'play_id': None,
           'campaign': 'c', 'payload': {'service': 'facebook', 'text': f'{status} {hours}'}, 'error': None,
           'content_hash': 'a' * 64, 'external_url': None}
    row.update(over)
    return row


def _seed_week(pc):
    out = SimpleNamespace()
    out.waiting = seed(pc, run_at=api.NOW + timedelta(days=1))
    out.standing = seed(pc, run_at=api.NOW + timedelta(days=2), status='approved', approved_via='standing',
                        approved_by=KEVIN)
    out.failed = seed(pc, run_at=api.NOW - timedelta(hours=3), status='failed', error='The network refused it.')
    out.uncertain = seed(pc, run_at=api.NOW - timedelta(hours=2), status='uncertain')
    out.pulled = seed(pc, run_at=api.NOW + timedelta(hours=5), status='pulled',
                      error='Every open time in it was booked before the post went out, so nothing was posted.')
    api.seed(pc, targets=(api.FB,))                                   # a tenant's: never on MC Today
    pc.buffer_posts = [_buffer_post('uncertain', -30), _buffer_post('approved', -10, expires_at=(
        api.NOW - timedelta(hours=4)).isoformat()), _buffer_post('draft', -5), _buffer_post('draft', 30)]
    return out


def test_today_reads_the_suite_desk_and_keeps_the_buffer_leftovers(pc):
    _seed_week(pc)
    items = run(pt._marketing())
    ids = [i['id'] for i in items]
    assert f'marketing:{PID}:waiting' in ids and f'marketing:{PID}:failed' in ids
    assert f'marketing:{PID}:uncertain' in ids
    assert 'marketing:suite:standing' in ids and 'marketing:suite:pulled' in ids
    assert {'buffer:marketing:uncertain', 'buffer:marketing:missed', 'buffer:marketing:window'} <= set(ids)
    assert not [i for i in ids if i.startswith('buffer:') and 'waiting' in i]   # nothing approves on Buffer now
    assert not [i for i in ids if api.BIZ in i]
    for item in items:
        assert item['action']['nav'] == 'platform-growth' and item['room'] == 'growth', item
        assert item['title'] and item['detail'] and 'Grow → Marketing' not in item['detail'].replace(
            'Growth → Marketing', '')
    standing = next(i for i in items if i['id'] == 'marketing:suite:standing')
    assert standing['title'] == 'Chief approved one post on your standing OK' and 'take back' in standing['detail']
    missed = next(i for i in items if i['id'] == 'buffer:marketing:missed')
    assert missed['title'].endswith('(Buffer desk)') and 'nothing new is approved on the Buffer desk' in \
        missed['detail']
    window = next(i for i in items if i['id'] == 'buffer:marketing:window')
    assert 'will not go out' in window['detail'] and window['post_ids']
    assert pc.db.writes == []


def test_failed_reads_say_couldnt_read_never_nothing(pc):
    pc.db.fail = ('/marketing_posts',)
    pc.buffer_fail = True
    items = run(pt._marketing())
    assert [i['id'] for i in items] == ['marketing:suite:unread', 'buffer:unread']
    assert all("couldn't be read" in i['title'] and 'not the same as nothing' in i['detail'] for i in items)
    d = run(suite.digest())
    assert d['posts_readable'] is False and "couldn't be read" in d['needs_owner'][0]
    assert d['buffer_drain']['readable'] is False and d['desk'] == 'suite'


def test_the_digest_reads_the_suite_desk_in_mission_controls_words(pc):
    _seed_week(pc)
    d = run(suite.digest())
    assert d['desk'] == 'suite' and d['where'] == suite.WHERE_MC and d['time_zone'] == 'America/New_York'
    assert d['posts_waiting_for_approval'] == 1 and d['approved_on_standing_ok'] == 1
    assert d['pulled_last_7_days'] == 1 and d['posts_readable'] is True
    joined = ' | '.join(d['needs_owner'])
    assert 'wait for your OK' in joined or 'waits for your OK' in joined
    assert 'on your standing OK' in joined and 'pulled' in joined and '(Buffer desk)' in joined
    assert d['buffer_drain']['readable'] is True and d['buffer_drain']['needs_a_hand']


def test_platform_chiefs_snapshot_carries_the_suite_desk_and_the_drain(pc, monkeypatch):
    mine = seed(pc)

    async def founder_offer():
        return {'configured': False}
    monkeypatch.setattr(pcm, 'founder_offer', founder_offer)
    pc.buffer_posts = [_buffer_post('uncertain', -30)]
    snap = run(suite.snapshot(OWNER))
    assert snap['suite']['on'] is True and snap['suite']['business_id'] == PID
    assert [p['post_id'] for p in snap['desk']['posts']] == [mine['id']]
    assert snap['buffer_drain']['needs_a_hand'][0]['post_ids'] == [pc.buffer_posts[0]['id']]
    assert snap['source_status']['desk'] == {'status': 'loaded'}
    pc.db.fail = ('/marketing_posts',)
    pc.buffer_fail = True
    snap = run(suite.snapshot(OWNER))
    assert 'unavailable' in snap['desk'] and 'unavailable' in snap['buffer_drain']
    assert snap['source_status']['desk'] == {'status': 'unavailable'}


def test_the_docs_and_worklog_say_what_was_built():
    import pathlib
    import re
    import worklog
    root = pathlib.Path(__file__).resolve().parent.parent
    doc = (root / 'docs' / 'MARKETING_DESK.md').read_text(encoding='utf-8')
    section = doc.split('### With the suite on, Platform Chief and MC Today', 1)
    assert len(section) == 2 and 'platform_chief_suite' in section[1]
    text = (root / 'worklog' / '2026-10-08-marketing-platform-chief.md').read_text(encoding='utf-8')
    entry = worklog.parse_entry(text, 'kmj-intake-server', 'worklog/2026-10-08-marketing-platform-chief.md')
    assert entry and entry['agent'] == 'Claude Code (Claude Opus 5.5)'
    assert entry['asked'] == "This will work. let's build this."
    assert re.search(r'^migrations: \[\]$', text.split('---')[1], re.M)
