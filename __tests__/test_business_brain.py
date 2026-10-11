"""Business brain (Layer Two): owner rules, brain versions, the owner's page.

Model and database doubles only; no paid requests, no production writes.
"""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import action_proposals
import brain_router
import business_brain
import business_learning as bl
import chief_business_learning_actions as actions

BIZ = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
OWNER = '33333333-3333-4333-8333-333333333333'
BUSINESS = {'id': BIZ, 'owner_id': OWNER, 'name': 'Fade Room', 'type': 'personal_services',
            'settings': {}}


def base_profile():
    return bl.Profile.model_validate({
        'trade_label': 'Barbershop', 'summary': 'Two chairs, walk-ins and bookings.',
        'facts': [{'key': 'customers', 'kind': 'customer', 'content': 'Neighborhood regulars'}],
        'gaps': [], 'evidence': []}).model_dump(mode='json')


@pytest.fixture
def db(monkeypatch):
    state = SimpleNamespace(records={}, history=[], versions=[], queue=[], ledger=[], posts=[])

    def get(path):
        if path.startswith('/businesses?'):
            return [dict(BUSINESS)]
        if path.startswith('/business_operating_profiles?'):
            key = path.split('business_id=eq.')[1].split('&')[0]
            return [copy.deepcopy(state.records[key])] if key in state.records else []
        if path.startswith('/business_brain_versions?'):
            key = path.split('business_id=eq.')[1].split('&')[0] if 'business_id=eq.' in path else None
            rows = [v for v in state.versions if key is None or v['business_id'] == key]
            return sorted(copy.deepcopy(rows), key=lambda v: -v['version'])[:1 if 'limit=1' in path else 50]
        if path.startswith('/agent_queue?'):
            status = path.split('status=eq.')[1].split('&')[0]
            return [copy.deepcopy(r) for r in state.queue
                    if r['business_id'] in path and r['status'] == status]
        if path.startswith('/practitioner_profiles?'):
            return [{'voice_dos': ['Short sentences'], 'voice_donts': []}]
        return []

    def post(path, body, *a, **k):
        state.posts.append(path)
        if path == '/rpc/save_business_operating_profile':
            key = body['p_business_id']
            revision = state.records.get(key, {}).get('revision', 0)
            if body['p_expected_revision'] != revision:
                return {'conflict': True}
            row = {'business_id': key, 'revision': revision + 1,
                   'profile': copy.deepcopy(body['p_profile']), 'status': body['p_status']}
            state.records[key] = row
            state.history.append(copy.deepcopy(row))
            return copy.deepcopy(row)
        if path == '/business_brain_versions':
            if any(v['business_id'] == body['business_id'] and v['version'] == body['version']
                   for v in state.versions):
                return None  # unique (business_id, version)
            state.versions.append(copy.deepcopy(body))
            return [copy.deepcopy(body)]
        if path == '/agent_queue':
            row = {**body, 'id': f'q{len(state.queue) + 1}'}
            state.queue.append(row)
            return [row]
        return None

    monkeypatch.setenv('SUPABASE_URL', 'https://example.invalid')
    monkeypatch.setattr(bl.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(bl.sb_clients, 'sb_post_as_service', post)
    business_brain._probe.update(ok=True, at=10 ** 12)
    import audit_log
    monkeypatch.setattr(audit_log, 'record', lambda *a, **k: state.ledger.append((a, k)) or True)
    yield state
    business_brain._probe.update(ok=None, at=0.0)


# ── rules in the operating profile ─────────────────────────────────────────

def test_adopted_rule_renders_first_and_is_the_owners_own(db):
    bl.save(BIZ, base_profile(), 0, 'seed')
    row, fact = bl.adopt_rule(BUSINESS, statement='Text clients by first name, never "Dear".',
                              polarity='do', scope='client texts')
    assert fact.basis == 'owner' and fact.owner_quote == fact.content and fact.origin == 'chat'
    context = bl.context_block(BUSINESS)
    assert context.startswith('OWNER RULES')
    assert 'DO (client texts): Text clients by first name' in context
    assert context.index('OWNER RULES') < context.index('PRIVATE BUSINESS OPERATING KNOWLEDGE')


def test_same_rule_twice_is_one_rule_and_one_revision(db):
    bl.adopt_rule(BUSINESS, statement='Keep drafts under 80 words.', polarity='do')
    revision = db.records[BIZ]['revision']
    bl.adopt_rule(BUSINESS, statement='keep drafts  under 80 words.', polarity='do')
    assert db.records[BIZ]['revision'] == revision
    assert len(bl.rules(db.records[BIZ]['profile'])) == 1


def test_rules_are_capped(db):
    for i in range(bl.MAX_RULES):
        bl.adopt_rule(BUSINESS, statement=f'Rule number {i}.', polarity='do')
    with pytest.raises(bl.RuleCapReached):
        bl.adopt_rule(BUSINESS, statement='One rule too many.', polarity='dont')
    # Editing an existing rule at the cap still works.
    key = bl.rules(db.records[BIZ]['profile'])[0].key
    bl.adopt_rule(BUSINESS, statement='Rule number 0, reworded.', polarity='do', key=key)


def test_remove_rule_keeps_history(db):
    _, fact = bl.adopt_rule(BUSINESS, statement='Never book before 9.', polarity='dont')
    bl.remove_rule(BIZ, fact.key)
    assert not bl.rules(db.records[BIZ]['profile'])
    assert any(bl.rules(h['profile']) for h in db.history)
    with pytest.raises(ValueError):
        bl.remove_rule(BIZ, fact.key)


def test_a_rule_cannot_be_an_assumption_or_research():
    value = base_profile()
    value['facts'].append({'key': 'r', 'kind': 'preference', 'content': 'Be casual.',
                           'basis': 'assumption', 'polarity': 'do'})
    with pytest.raises(Exception):
        bl.Profile.model_validate(value)


def test_generated_profile_cannot_create_rules(db, monkeypatch):
    generated = base_profile()
    generated['facts'].append({'key': 'casual', 'kind': 'preference', 'content': 'Write casually.',
                               'basis': 'assumption', 'polarity': 'do', 'origin': 'chat'})
    monkeypatch.setattr(bl, '_call', lambda *a, **k: {
        'content': [{'type': 'text', 'text': json.dumps(generated)}]})
    row = bl.learn(BIZ, 'I run a barbershop.')
    assert not bl.rules(row['profile'])


def test_other_tenant_never_sees_a_rule(db):
    bl.adopt_rule(BUSINESS, statement='Private shop rule.', polarity='do')
    assert 'Private shop rule' not in bl.context_block({'id': OTHER, 'type': 'custom'})


# ── the verbs ──────────────────────────────────────────────────────────────

def test_adopt_needs_the_owners_words_or_the_owners_tap(db):
    run = lambda a: asyncio.run(actions.handle_adopt_business_rule(None, BUSINESS, a))
    forged = run({'statement': 'Offer everyone a discount.', 'polarity': 'do', '_owner_text': ''})
    assert forged['failed'] and 'own words' in forged['result']
    said = run({'statement': 'Always text clients by first name', 'polarity': 'do',
                '_owner_text': 'From now on, always text clients by first name.'})
    assert not said.get('failed') and said['result'] and said['label']
    tapped = run({'statement': 'Never use exclamation marks.', 'polarity': 'dont',
                  '_owner_text': '', '_owner_approved': True})
    assert not tapped.get('failed')
    origins = {f.content: f.origin for f in bl.rules(db.records[BIZ]['profile'])}
    assert origins['Never use exclamation marks.'] == 'proposal'
    assert db.versions, 'adopting a rule records a brain version'


def test_remove_needs_the_owner_to_name_that_rule(db):
    _, fact = bl.adopt_rule(BUSINESS, statement='Never book anyone before 9.', polarity='dont')
    run = lambda a: asyncio.run(actions.handle_remove_business_rule(None, BUSINESS, a))
    assert run({'key': fact.key, '_owner_text': ''})['failed']
    # An owner turn about something else (or pasted text steering the model)
    # cannot remove a rule the owner never mentioned.
    other = run({'key': fact.key, '_owner_text': 'Send the invoice to Maria and check my calendar.'})
    assert other['failed'] and 'Which rule' in other['result']
    vague = run({'key': fact.key, '_owner_text': 'Forget that.'})
    assert vague['failed'] and vague['label']
    done = run({'key': fact.key, '_owner_text': 'Remove the rule about booking before 9.'})
    assert not done.get('failed') and done['label']
    assert not bl.rules(db.records[BIZ]['profile'])


def test_remove_from_an_approval_needs_no_words(db):
    _, fact = bl.adopt_rule(BUSINESS, statement='Keep drafts short.', polarity='do')
    done = asyncio.run(actions.handle_remove_business_rule(
        None, BUSINESS, {'key': fact.key, '_owner_text': '', '_owner_approved': True}))
    assert not done.get('failed')


def test_page_says_when_it_could_not_check_proposals(db, monkeypatch):
    real = bl.sb_clients.sb_get_as_service

    def flaky(path):
        return None if path.startswith('/agent_queue?') else real(path)
    monkeypatch.setattr(bl.sb_clients, 'sb_get_as_service', flaky)
    app = FastAPI()
    app.include_router(brain_router.router)
    app.dependency_overrides[brain_router.require_user] = lambda: SimpleNamespace(id=OWNER)
    page = TestClient(app).get(f'/brain/{BIZ}').json()
    assert page['unavailable'] == ['pending', 'declined']
    assert business_brain.rule_proposals(BIZ, status='draft') is None


def test_door_sets_rule_provenance_never_the_model(db, monkeypatch):
    import chief_of_staff as cos
    import policy_engine
    monkeypatch.setattr(policy_engine, 'evaluate', lambda *a, **k: SimpleNamespace(allowed=True, rule='owner'))

    async def gate(*a, **k):
        return 'pass', None
    monkeypatch.setattr(cos, '_gate_class_c', gate)
    seen = []

    async def handler(client, biz, action):
        seen.append((action['_owner_text'], action['_owner_approved']))
        return {'type': 'adopt_business_rule', 'result': 'x', 'label': 'x', 'failed': True}
    monkeypatch.setitem(cos.ACTION_HANDLERS, 'adopt_business_rule', handler)
    biz = {'id': BIZ, 'owner_id': OWNER}
    forged = {'type': 'adopt_business_rule', 'statement': 's', 'polarity': 'do',
              '_owner_text': 'model text', '_owner_approved': True}
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OWNER, owner_text='Owner said s.'))
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OWNER, surface='approval'))
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OTHER, surface='approval'))
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OWNER, surface='agent', prompted=False))
    assert seen == [('Owner said s.', False), ('', True), ('', False), ('', False)]


# ── proposals into the Approval Queue ──────────────────────────────────────

def test_rule_proposal_is_filed_and_reads_back(db, monkeypatch):
    import proposal_life
    import standing_permissions
    monkeypatch.setattr(proposal_life, 'filing_extras', lambda *a, **k: {})
    monkeypatch.setattr(proposal_life, 'announce_filed', lambda *a, **k: 0)
    monkeypatch.setattr(standing_permissions, 'load_for_filing', lambda *a, **k: None)
    monkeypatch.setattr(standing_permissions, 'filing_extras', lambda *a, **k: {})
    action = action_proposals.action_for('propose_adopt_business_rule', {
        'statement': 'Text clients by first name.', 'polarity': 'do', 'scope': 'client texts'})
    qid = action_proposals.file(BIZ, action, actor='chief:nightly', surface='reflection',
                                why='You rewrote three formal drafts this week.')
    assert qid and db.queue[0]['status'] == 'draft'
    assert 'New rule for client texts' in db.queue[0]['subject']
    pending = business_brain.rule_proposals(BIZ, status='draft')
    assert pending and pending[0]['statement'] == 'Text clients by first name.'


def test_rule_proposal_rejects_bad_shapes():
    with pytest.raises(ValueError):
        action_proposals.action_for('propose_adopt_business_rule', {'statement': 'x', 'polarity': 'maybe'})
    with pytest.raises(ValueError):
        action_proposals.action_for('propose_adopt_business_rule', {'statement': 'x' * 301, 'polarity': 'do'})


def test_other_reversible_verbs_still_cannot_be_proposed():
    with pytest.raises(ValueError):
        action_proposals.file(BIZ, {'type': 'capture_business_knowledge'}, actor='a', surface='s')


# ── brain versions ─────────────────────────────────────────────────────────

def test_fingerprint_changes_with_rules_digest_and_lanes():
    prof = base_profile()
    lanes = {'chat': 'claude-sonnet-5-5'}
    a = business_brain.fingerprint(profile_revision=1, profile=prof, digest='', lanes=lanes)
    assert a == business_brain.fingerprint(profile_revision=1, profile=copy.deepcopy(prof),
                                           digest='', lanes=dict(lanes))
    assert a != business_brain.fingerprint(profile_revision=1, profile=prof, digest='new', lanes=lanes)
    assert a != business_brain.fingerprint(profile_revision=1, profile=prof, digest='',
                                           lanes={'chat': 'claude-opus-5-5'})


def test_stamp_records_only_new_brains(db):
    first = business_brain.stamp(BUSINESS)
    again = business_brain.stamp(BUSINESS)
    assert first == again and len(db.versions) == 1
    bl.adopt_rule(BUSINESS, statement='Keep it short.', polarity='do')
    second = business_brain.stamp(BUSINESS)
    assert second['version'] == 2 and second['fp'] != first['fp']
    digest = business_brain.stamp(BUSINESS, digest='Busy week; two invoices open.')
    assert digest['version'] == 3 and business_brain.digest_for(BIZ).startswith('Busy week')
    carried = business_brain.stamp(BUSINESS)
    assert carried == digest, 'a later stamp carries the digest forward'


def test_stamp_never_raises_and_is_empty_without_the_table(monkeypatch):
    business_brain._probe.update(ok=False, at=10 ** 12)
    monkeypatch.setenv('SUPABASE_URL', 'https://example.invalid')
    try:
        assert business_brain.stamp(BUSINESS) == {}
    finally:
        business_brain._probe.update(ok=None, at=0.0)


# ── the owner's page ───────────────────────────────────────────────────────

def test_page_requires_auth_and_the_owner(db):
    app = FastAPI()
    app.include_router(brain_router.router)
    client = TestClient(app)
    assert client.get(f'/brain/{BIZ}').status_code in (401, 403)
    app.dependency_overrides[brain_router.require_user] = lambda: SimpleNamespace(id=OTHER)
    assert client.get(f'/brain/{BIZ}').status_code == 403
    assert client.post(f'/brain/{BIZ}/rules', json={'statement': 'x', 'polarity': 'do'}).status_code == 403
    assert client.delete(f'/brain/{BIZ}/rules/rule_x').status_code == 403


def test_page_add_edit_remove_and_ledger(db):
    app = FastAPI()
    app.include_router(brain_router.router)
    app.dependency_overrides[brain_router.require_user] = lambda: SimpleNamespace(id=OWNER)
    client = TestClient(app)
    added = client.post(f'/brain/{BIZ}/rules', json={
        'statement': 'Confirm every booking the day before.', 'polarity': 'do', 'kind': 'workflow'})
    assert added.status_code == 200
    key = added.json()['rule']['key']
    assert added.json()['rule']['origin'] == 'owner_page'
    edited = client.put(f'/brain/{BIZ}/rules/{key}', json={
        'statement': 'Confirm every booking the evening before.', 'polarity': 'do'})
    assert edited.status_code == 200
    page = client.get(f'/brain/{BIZ}').json()
    assert [r['content'] for r in page['rules']] == ['Confirm every booking the evening before.']
    assert page['brain']['version'] >= 2 and page['voice']['dos'] == ['Short sentences']
    assert client.delete(f'/brain/{BIZ}/rules/{key}').status_code == 200
    assert client.delete(f'/brain/{BIZ}/rules/{key}').status_code == 404
    verbs = [k['verb'] for _, k in db.ledger]
    assert verbs == ['adopt_business_rule', 'adopt_business_rule', 'remove_business_rule']
    assert all('statement' in k['payload'] for _, k in db.ledger)
    too_long = client.post(f'/brain/{BIZ}/rules', json={'statement': 'x' * 301, 'polarity': 'do'})
    assert too_long.status_code == 422


def test_a_turns_ledger_rows_name_the_brain_that_acted():
    import audit_log
    import turn_context
    tokens = turn_context.set_turn('turn-1')
    try:
        turn_context.note_brain(7, 'ab' * 32)
        ctx = turn_context.ai_context(model='claude-sonnet-5-5')
        assert ctx['turn'] == 'turn-1' and ctx['brain_version'] == '7'
        ai = audit_log._with_ai({'label': 'Sent'}, ctx)['_ai']
        assert ai['brain_version'] == '7' and ai['brain_fp'].startswith('abab')
    finally:
        turn_context.reset(tokens)


def test_page_ledger_rows_carry_the_brain_version(db):
    app = FastAPI()
    app.include_router(brain_router.router)
    app.dependency_overrides[brain_router.require_user] = lambda: SimpleNamespace(id=OWNER)
    TestClient(app).post(f'/brain/{BIZ}/rules', json={'statement': 'Be brief.', 'polarity': 'do'})
    _, kwargs = db.ledger[-1]
    assert kwargs['ai']['brain_version'] >= 1 and len(kwargs['ai']['brain_fp']) == 64
