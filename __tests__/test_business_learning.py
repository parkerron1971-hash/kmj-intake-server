"""Learning cycle with model/DB doubles; no paid requests or production writes."""
import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import business_learning as bl
import business_learning_router as router
import chief_business_learning_actions as actions

BIZ = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
OWNER = '33333333-3333-4333-8333-333333333333'


def profile(**updates):
    value = {'trade_label': 'Mobile pet grooming', 'summary': 'Pet grooming at the customer home.',
             'facts': [
                 {'key': 'customers', 'kind': 'customer', 'content': 'Pet owners'},
                 {'key': 'grooming', 'kind': 'offering', 'content': 'Grooming appointments'},
                 {'key': 'travel_buffer', 'kind': 'workflow', 'content': 'Allow travel time between appointments.'},
                 {'key': 'payment', 'kind': 'payment', 'content': 'Confirm how payment is collected.'},
             ], 'gaps': [], 'evidence': []}
    value.update(updates)
    return bl.Profile.model_validate(value).model_dump(mode='json')


@pytest.fixture
def db(monkeypatch):
    records, history, reads, writes = {}, [], [], []

    def get(path):
        reads.append(path)
        if path.startswith('/businesses?'):
            return [{'id': BIZ, 'owner_id': OWNER, 'name': 'Grooming', 'type': 'custom',
                     'settings': {'custom_type': 'Mobile pet grooming'}}]
        if path.startswith('/business_operating_profiles?'):
            key = path.split('business_id=eq.')[1].split('&')[0]
            return [copy.deepcopy(records[key])] if key in records else []
        if path.startswith('/business_operating_profile_history?'):
            key = path.split('business_id=eq.')[1].split('&')[0]
            return [copy.deepcopy(r) for r in history if r['business_id'] == key]
        return []

    def post(path, body):
        writes.append(path)
        assert path == '/rpc/save_business_operating_profile'
        key = body['p_business_id']
        revision = records.get(key, {}).get('revision', 0)
        if body['p_expected_revision'] != revision:
            return {'conflict': True}
        row = {'business_id': key, 'revision': revision + 1, 'profile': copy.deepcopy(body['p_profile']),
               'status': body['p_status']}
        records[key] = row
        history.append(copy.deepcopy(row))
        return copy.deepcopy(row)

    monkeypatch.setattr(bl.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(bl.sb_clients, 'sb_post_as_service', post)
    return SimpleNamespace(records=records, history=history, reads=reads, writes=writes)


def model_reply(monkeypatch, value):
    monkeypatch.setattr(bl, '_call', lambda *a, **k: {
        'content': [{'type': 'text', 'text': json.dumps(value)}]})


def test_full_cycle_remembers_correction_and_uses_it_for_later_build(db, monkeypatch):
    model_reply(monkeypatch, profile())
    first = bl.learn(BIZ, 'I groom pets at their homes.')
    assert first['revision'] == 1 and first['status'] == 'ready_to_build'
    correction = 'Allow 45 minutes between appointments for travel and cleaning.'
    bl.correct(BIZ, key='travel_buffer', kind='workflow', statement=correction, expected_revision=1)
    # A later generated refresh proposes the old default. The correction wins.
    model_reply(monkeypatch, profile())
    third = bl.learn(BIZ, 'We also groom cats.')
    assert third['revision'] == 3
    assert next(f for f in third['profile']['facts'] if f['key'] == 'travel_buffer')['content'] == correction
    context = bl.context_block({'id': BIZ, 'type': 'custom'})
    assert correction in context and 'workflow, owner' in context
    assert len(db.history) == 3
    assert all(path == '/rpc/save_business_operating_profile' for path in db.writes)

    import business_blueprint as bb
    seen = []
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'fake')
    monkeypatch.setattr(bb.llm_call, 'sdk_client', lambda **kw: object())
    monkeypatch.setattr(bb, '_call', lambda client, system, user: seen.append(user) or {'ok': False})
    bb.generate_business_blueprint({'id': BIZ, 'type': 'custom'}, 'Build the grooming workspace.')
    assert correction in seen[0]

    import module_spec_generator as msg
    seen.clear()
    monkeypatch.setattr(msg, '_call_and_parse', lambda client, system, user: seen.append(user) or {'ok': False})
    msg.generate_module_proposal({'id': BIZ, 'type': 'custom'}, 'Appointments that customers book.')
    assert correction in seen[0]


def test_other_tenant_never_receives_private_knowledge(db):
    bl.save(BIZ, profile(summary='Private unique operating practice'), 0, 'discovery')
    assert bl.load(OTHER) is None
    assert 'Private unique' not in bl.context_block({'id': OTHER, 'type': 'custom'})
    assert f'business_id=eq.{OTHER}' in db.reads[-1]


def test_concurrent_revision_is_rejected_without_losing_history(db):
    bl.save(BIZ, profile(), 0, 'first')
    bl.correct(BIZ, key='travel_buffer', kind='workflow', statement='Use a 45 minute buffer.', expected_revision=1)
    with pytest.raises(bl.Conflict):
        bl.save(BIZ, profile(), 1, 'stale generation')
    assert len(db.history) == 2
    assert db.records[BIZ]['revision'] == 2


def test_read_or_write_failure_is_not_success(db, monkeypatch):
    monkeypatch.setattr(bl.sb_clients, 'sb_get_as_service', lambda p: None)
    monkeypatch.setattr(bl, '_call', lambda *a, **k: pytest.fail('must fail before model spend'))
    with pytest.raises(RuntimeError, match='could not be read'):
        bl.learn(BIZ, 'My business')
    monkeypatch.setattr(bl.sb_clients, 'sb_post_as_service', lambda *a: None)
    with pytest.raises(RuntimeError, match='not saved'):
        bl.save(BIZ, profile(), 0, 'first')


def test_generated_owner_quotation_must_be_real(db, monkeypatch):
    value = profile(facts=[{'key': 'price', 'kind': 'payment', 'content': 'Costs $99',
                           'basis': 'owner', 'owner_quote': 'I charge $99'}])
    model_reply(monkeypatch, value)
    with pytest.raises(ValueError, match='quotation'):
        bl.learn(BIZ, 'I groom pets.')
    assert not db.writes


def test_real_owner_quote_cannot_launder_a_different_claim(db, monkeypatch):
    value = profile(facts=[{'key': 'price', 'kind': 'payment', 'content': 'Costs $999',
                           'basis': 'owner', 'owner_quote': 'I charge $99'}])
    model_reply(monkeypatch, value)
    row = bl.learn(BIZ, 'I charge $99')
    assert row['profile']['facts'][0]['content'] == 'I charge $99'


def test_research_extracts_real_provider_citations_only(monkeypatch):
    monkeypatch.setattr(bl, '_call', lambda *a, **k: {'content': [
        {'type': 'text', 'text': 'An unsupported URL https://invented.example', 'citations': []},
        {'type': 'text', 'text': 'A finding', 'citations': [
            {'url': 'https://agency.example/guide', 'title': 'Guide', 'cited_text': 'Clean equipment between visits.'},
            {'url': 'javascript:bad', 'cited_text': 'Invalid'},
            {'url': 'https://unsupported.example', 'cited_text': ''}]}]})
    evidence = bl.research(BIZ, 'Equipment cleaning guidance')
    assert len(evidence) == 1
    assert evidence[0].url == 'https://agency.example/guide'
    assert evidence[0].review_after > evidence[0].retrieved_at


def test_uncited_research_cannot_clear_a_gap(db, monkeypatch):
    gap = {'key': 'rules', 'question': 'Which rules apply?', 'route': 'research', 'blocking': True}
    bl.save(BIZ, profile(gaps=[gap]), 0, 'first')
    model_reply(monkeypatch, profile())
    monkeypatch.setattr(bl, 'research', lambda *a: [])
    row = bl.learn(BIZ, '', 'Which rules apply?')
    assert row['status'] == 'needs_research'
    assert any(g['key'] == 'rules' for g in row['profile']['gaps'])


def test_research_references_cannot_be_fabricated():
    with pytest.raises(ValidationError, match='stored evidence'):
        profile(facts=[{'key': 'rule', 'kind': 'workflow', 'content': 'A rule',
                        'basis': 'research', 'evidence_ids': ['invented']}])
    with pytest.raises(ValidationError):
        profile(execute_code='malicious')


def test_stale_sources_are_labeled_and_returned_with_their_facts(db):
    old = datetime.now(timezone.utc) - timedelta(days=60)
    value = profile(facts=[{'key': 'cleaning', 'kind': 'workflow', 'content': 'Clean equipment.',
                           'basis': 'research', 'evidence_ids': ['guide']}], evidence=[{
        'id': 'guide', 'url': 'https://agency.example/guide', 'title': 'Guide', 'excerpt': 'Clean equipment.',
        'retrieved_at': old.isoformat(), 'review_after': (old + timedelta(days=30)).isoformat()}])
    bl.save(BIZ, value, 0, 'research')
    result = bl.context_block({'id': BIZ})
    assert 'STALE' in result and 'https://agency.example/guide' in result


def test_blocking_discovery_stops_custom_workspace_before_generation(db, monkeypatch):
    import business_blueprint as bb
    bl.save(BIZ, profile(gaps=[{'key': 'pay', 'question': 'How do people pay?',
                               'route': 'ask_owner', 'blocking': True}]), 0, 'first')
    monkeypatch.setattr(bb, 'generate_business_blueprint', lambda *a: pytest.fail('blocked build'))
    result = bb.propose_business_from_idea(BIZ, 'Mobile grooming')
    assert result['ok'] is False and result['discovery_status'] == 'needs_input'


def test_owner_correction_resolves_owner_gap_only(db):
    gaps = [{'key': 'travel_buffer', 'question': 'How much travel time?', 'route': 'ask_owner', 'blocking': True},
            {'key': 'rules', 'question': 'Which rules apply?', 'route': 'research', 'blocking': True}]
    bl.save(BIZ, profile(gaps=gaps), 0, 'first')
    row = bl.correct(BIZ, key='travel_buffer', kind='workflow', statement='45 minutes.',
                     expected_revision=1, resolves_gap='travel_buffer')
    assert [g['key'] for g in row['profile']['gaps']] == ['rules']


def test_correction_action_requires_actual_owner_text(db):
    bl.save(BIZ, profile(), 0, 'first')
    action = {'key': 'travel_buffer', 'kind': 'workflow', 'statement': '45 minutes.', 'expected_revision': 1}
    result = asyncio.run(actions.handle_correct_business_knowledge(None, {'id': BIZ}, action))
    assert result['failed'] and db.records[BIZ]['revision'] == 1
    action['_owner_text'] = 'Actually, allow 45 minutes.'
    result = asyncio.run(actions.handle_correct_business_knowledge(None, {'id': BIZ}, action))
    assert result['revision'] == 2


def test_failed_enqueue_does_not_claim_started(db, monkeypatch):
    import chief_jobs
    async def enqueue(*a, **k):
        return None
    monkeypatch.setattr(chief_jobs, 'enqueue', enqueue)
    result = asyncio.run(actions.handle_learn_business(None, {'id': BIZ, 'owner_id': OWNER},
                                                       {'_owner_text': 'Mobile grooming'}))
    assert result['failed'] and 'could not be started' in result['result']


def test_onboarding_queues_once_and_reuses_saved_profile(db, monkeypatch):
    import chief_jobs
    calls = []
    async def enqueue(*a, **kw):
        calls.append(kw)
        return {'id': 'job'}
    monkeypatch.setattr(chief_jobs, 'enqueue', enqueue)
    biz = {'id': BIZ, 'owner_id': OWNER, 'type': 'custom', 'settings': {'custom_type': 'Mobile grooming'}}
    assert asyncio.run(actions.seed_custom_business(biz))['status'] == 'queued'
    assert calls[0]['params']['build_workspace'] is True
    bl.save(BIZ, profile(), 0, 'first')
    assert asyncio.run(actions.seed_custom_business(biz))['status'] == 'ready_to_build'
    assert len(calls) == 1


def test_http_requires_auth_and_owner_and_rejects_stale_correction(db):
    app = FastAPI()
    app.include_router(router.router)
    client = TestClient(app)
    assert client.get(f'/business-learning/{BIZ}').status_code in (401, 403)
    app.dependency_overrides[router.require_user] = lambda: SimpleNamespace(id=OTHER)
    assert client.get(f'/business-learning/{BIZ}').status_code == 403
    assert client.get(f'/business-learning/{BIZ}/history').status_code == 403
    assert client.post(f'/business-learning/{BIZ}/discover', json={'description': 'Grooming'}).status_code == 403
    assert client.post(f'/business-learning/{BIZ}/correct', json={
        'key': 'travel_buffer', 'kind': 'workflow', 'statement': '45 minutes.', 'expected_revision': 1}).status_code == 403
    app.dependency_overrides[router.require_user] = lambda: SimpleNamespace(id=OWNER)
    bl.save(BIZ, profile(), 0, 'first')
    response = client.post(f'/business-learning/{BIZ}/correct', json={
        'key': 'travel_buffer', 'kind': 'workflow', 'statement': '45 minutes.', 'expected_revision': 9})
    assert response.status_code == 409
    assert client.get('/business-learning/not-a-uuid').status_code == 422


def test_job_research_is_bounded_and_builds_only_when_ready(db, monkeypatch):
    import business_blueprint as bb
    calls = []
    def learn(business_id, description, question='', progress_cb=None):
        calls.append(question)
        value = profile(gaps=[{'key': 'rules', 'question': 'Which rules?', 'route': 'research', 'blocking': True}])
        return {'revision': len(calls), 'status': 'needs_research', 'profile': value}
    monkeypatch.setattr(bl, 'learn', learn)
    monkeypatch.setattr(bb, 'run_job', lambda *a, **k: pytest.fail('must not build while blocked'))
    result = bl.run_job(BIZ, {'description': 'Grooming', 'build_workspace': True})
    assert result['status'] == 'needs_research' and len(calls) == 2


def test_context_budget_prioritizes_owner_corrections(db):
    value = profile(facts=[{'key': f'assumption_{i}', 'kind': 'workflow', 'content': 'Long suggestion. ' * 30}
                           for i in range(40)] + [{'key': 'owner_rule', 'kind': 'workflow', 'basis': 'owner',
                              'content': 'Use a 45 minute buffer.', 'owner_quote': 'Use a 45 minute buffer.'}])
    bl.save(BIZ, value, 0, 'first')
    text = bl.context_block({'id': BIZ}, max_chars=1500)
    assert len(text) <= 1500 and 'Use a 45 minute buffer.' in text


def test_researched_fact_and_its_source_survive_a_new_read(db, monkeypatch):
    now = datetime.now(timezone.utc)
    evidence = bl.Evidence(id='guide', url='https://agency.example/guide', title='Guide',
        excerpt='Clean equipment between visits.', retrieved_at=now, review_after=now + timedelta(days=30))
    value = profile()
    value['facts'].append({'key': 'cleaning', 'kind': 'workflow', 'content': 'Clean equipment between visits.',
                           'basis': 'research', 'evidence_ids': ['guide']})
    model_reply(monkeypatch, value)
    monkeypatch.setattr(bl, 'research', lambda *a: [evidence])
    row = bl.learn(BIZ, 'I groom pets at their homes.', 'How should equipment be cleaned?')
    assert row['profile']['evidence'][0]['url'] == evidence.url
    assert 'https://agency.example/guide' in bl.context_block({'id': BIZ})


def test_old_module_and_offering_cards_are_refused_after_correction(db, monkeypatch):
    import module_spec_generator as msg
    bl.save(BIZ, profile(), 0, 'first')
    bl.correct(BIZ, key='travel_buffer', kind='workflow', statement='45 minutes.', expected_revision=1)
    real_get = bl.sb_clients.sb_get_as_service
    for kind in ('module', 'offering'):
        draft = {'id': 'draft', 'business_id': BIZ, 'status': 'draft', 'draft_json': {
            '__kind': kind, '__operating_revision': 1, 'slug': 'grooming', 'name': 'Grooming'}}
        monkeypatch.setattr(bl.sb_clients, 'sb_get_as_service',
            lambda path: [draft] if path.startswith('/module_specs?') else real_get(path))
        before = len(db.writes)
        result = msg.materialize_spec('draft')
        assert result['ok'] is False and 'regenerate' in result['error']
        assert len(db.writes) == before


def test_signup_build_uses_shared_layout_queue_and_reports_queue_failure(monkeypatch):
    import chief_jobs
    calls = []
    async def enqueue(*a, **kw):
        calls.append(kw)
        return {'id': 'layout', 'deduped': True}
    monkeypatch.setattr(chief_jobs, 'enqueue', enqueue)
    result = asyncio.run(chief_jobs._learning_followup(None, OWNER, BIZ,
        {'build_workspace': True, 'description': 'Mobile grooming'},
        {'ok': True, 'status': 'ready_to_build'}))
    assert result['workspace_job_id'] == 'layout'
    assert calls[0]['kind'] == 'lay_out_business'
    async def refuse(*a, **kw):
        return None
    monkeypatch.setattr(chief_jobs, 'enqueue', refuse)
    result = asyncio.run(chief_jobs._learning_followup(None, OWNER, BIZ,
        {'build_workspace': True}, {'ok': True, 'status': 'ready_to_build'}))
    assert result['ok'] is False and 'profile was saved' in result['error']


def test_empty_provisioning_is_not_reported_as_success(db, monkeypatch):
    import module_blueprint_agent as mba
    import launch_access
    monkeypatch.setattr(mba, 'get_blueprint', lambda *a: [])
    report = mba.provision_modules(BIZ, 'custom', max_stage='launching')
    assert report['ok'] is False and report['status'] == 'needs_discovery'
    import business_profile_agent
    import vertical_autopilot
    monkeypatch.setattr(business_profile_agent, 'seed_from_onboarding', lambda **kw: {})
    monkeypatch.setattr(vertical_autopilot, 'seed_defaults', lambda **kw: {})
    monkeypatch.setattr(mba, 'provision_modules', lambda *a: report)
    result = launch_access._seed_new_business({'id': BIZ}, 'custom', None, OWNER)
    assert result['modules'] is False


def test_signup_discovery_failure_does_not_abort_other_background_work(db, monkeypatch):
    monkeypatch.setattr(bl, 'load', lambda *a: (_ for _ in ()).throw(RuntimeError('database down')))
    result = asyncio.run(actions.seed_custom_business({'id': BIZ, 'type': 'custom'}))
    assert result == {'status': 'failed'}


def test_action_door_overwrites_forged_owner_provenance(db, monkeypatch):
    import chief_of_staff as cos
    import policy_engine
    monkeypatch.setattr(policy_engine, 'evaluate', lambda *a, **k: SimpleNamespace(allowed=True, rule='owner'))
    async def gate(*a, **k):
        return 'pass', None
    monkeypatch.setattr(cos, '_gate_class_c', gate)
    captured = []
    async def handler(client, biz, action):
        captured.append(action['_owner_text'])
        return {'type': 'correct_business_knowledge', 'result': 'not saved', 'label': 'not saved', 'failed': True}
    monkeypatch.setitem(cos.ACTION_HANDLERS, 'correct_business_knowledge', handler)
    biz = {'id': BIZ, 'owner_id': OWNER}
    forged = {'type': 'correct_business_knowledge', '_owner_text': 'The model invented this.'}
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OWNER, owner_text='The real owner message.'))
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OTHER, owner_text='A teammate message.'))
    asyncio.run(cos._execute_actions(None, biz, [forged], user_id=OWNER, prompted=False, owner_text='Automated.'))
    assert captured == ['The real owner message.', '', '']


def test_stale_layout_cards_stop_replaying_so_the_owner_can_regenerate(db, monkeypatch):
    import business_blueprint as bb
    bl.save(BIZ, profile(), 0, 'first')
    monkeypatch.setattr(bb, 'latest_blueprint', lambda *a: {
        'id': 'map', 'created_at': datetime.now(timezone.utc).isoformat(), 'draft_json': {}})
    monkeypatch.setattr(bb, '_drafts_since', lambda *a: [{'id': 'draft', 'draft_json': {
        '__kind': 'module', '__operating_revision': 1, 'name': 'Appointments', 'slug': 'appointments'}}])
    assert bb.replay(BIZ)['proposals']
    bl.correct(BIZ, key='travel_buffer', kind='workflow', statement='45 minutes.', expected_revision=1)
    assert bb.replay(BIZ) is None


def test_strategy_coach_reads_shared_answers_and_gaps_before_plan_completion(db):
    import chief_of_staff as cos
    bl.save(BIZ, profile(gaps=[{'key': 'travel', 'question': 'How long do you need between visits?',
                              'route': 'ask_owner', 'blocking': True}]), 0, 'first')
    ctx = {'business': {'id': BIZ, 'type': 'custom', 'name': 'Grooming'},
           'strategy_track': {'status': 'in_progress', 'current_phase': 'discovery'}}
    prompt = cos._build_system_prompt(ctx, False, mode='strategy_coach')
    assert 'PRIVATE BUSINESS OPERATING KNOWLEDGE revision 1' in prompt
    assert 'How long do you need between visits?' in prompt
    assert 'capture_business_knowledge' in prompt
    assert 'Do not wait for save_phase' in prompt
    assert 'not automatically established business facts' in prompt
    assert 'owner\'s existing launch confirmation' in prompt


def test_strategy_answer_is_available_to_chief_and_business_coach_next_session(db, monkeypatch):
    from collections import defaultdict
    import chief_of_staff as cos
    biz = {'id': BIZ, 'owner_id': OWNER, 'type': 'custom', 'settings': {'custom_type': 'Mobile grooming'}}
    monkeypatch.setattr(bl, '_call', lambda *a, **k: pytest.fail('capturing an answer needs no paid call'))
    statement = 'I leave 45 minutes between grooming appointments.'
    result = asyncio.run(actions.handle_capture_business_knowledge(None, biz, {
        '_owner_text': statement, 'expected_revision': 0, 'facts': [{
            'key': 'travel_buffer', 'kind': 'workflow', 'statement': statement, 'certainty': 'reported'}]}))
    assert result['revision'] == 1 and result['status'] == 'discovering'
    for mode in ('strategy_coach', 'business_coach', None):
        prompt = cos._build_system_prompt(defaultdict(list, {'business': biz}), False, mode=mode)
        assert statement in prompt, mode
    assert len(db.history) == 1


def test_batch_capture_preserves_tentative_plans_and_resolves_only_answered_owner_gaps(db):
    bl.save(BIZ, profile(gaps=[{'key': 'buffer', 'question': 'Travel time?', 'route': 'ask_owner', 'blocking': True},
                             {'key': 'pricing', 'question': 'What do you charge?', 'route': 'ask_owner', 'blocking': True}]), 0, 'first')
    statement = 'I leave 45 minutes. I might charge $100.'
    row = bl.capture({'id': BIZ}, {'expected_revision': 1, 'facts': [
        {'key': 'travel_buffer', 'kind': 'workflow', 'statement': 'I leave 45 minutes.',
         'certainty': 'decided', 'resolves_gap': 'buffer'},
        {'key': 'possible_price', 'kind': 'payment', 'statement': 'I might charge $100.',
         'certainty': 'tentative', 'resolves_gap': 'pricing'}]}, statement)
    facts = {f['key']: f for f in row['profile']['facts']}
    assert facts['travel_buffer']['basis'] == 'owner'
    assert facts['possible_price']['basis'] == 'assumption'
    assert [g['key'] for g in row['profile']['gaps']] == ['pricing']
    assert row['revision'] == 2


def test_tentative_scenario_cannot_replace_settled_rule(db):
    bl.save(BIZ, profile(), 0, 'first')
    bl.correct(BIZ, key='payment', kind='payment', statement='I charge $80.', expected_revision=1)
    with pytest.raises(ValueError, match='tentative scenario'):
        bl.capture({'id': BIZ}, {'expected_revision': 2, 'facts': [
            {'key': 'payment', 'kind': 'payment', 'statement': 'Maybe $100.', 'certainty': 'tentative'}]}, 'Maybe $100.')
    assert db.records[BIZ]['revision'] == 2


def test_capture_does_not_accept_assistant_suggestions_as_owner_answers(db):
    with pytest.raises(ValueError, match='actual current owner message'):
        bl.capture({'id': BIZ}, {'expected_revision': 0, 'facts': [
            {'key': 'price', 'kind': 'payment', 'statement': 'Charge $100.', 'certainty': 'decided'}]},
            'I have not decided on pricing.')
    assert not db.writes


def test_capture_uses_existing_door_owner_check(db, monkeypatch):
    import chief_of_staff as cos
    import policy_engine
    monkeypatch.setattr(policy_engine, 'evaluate', lambda *a, **k: SimpleNamespace(allowed=True, rule='owner'))
    async def gate(*a, **k):
        return 'pass', None
    monkeypatch.setattr(cos, '_gate_class_c', gate)
    action = {'type': 'capture_business_knowledge', '_owner_text': 'I groom pets.', 'expected_revision': 0,
              'facts': [{'key': 'offering', 'kind': 'offering', 'statement': 'I groom pets.', 'certainty': 'reported'}]}
    biz = {'id': BIZ, 'owner_id': OWNER}
    rejected = asyncio.run(cos._execute_actions(None, biz, [action], user_id=OTHER, owner_text='I groom pets.'))
    assert rejected[0]['failed'] and not db.writes
    accepted = asyncio.run(cos._execute_actions(None, biz, [action], user_id=OWNER, owner_text='I groom pets.'))
    assert accepted[0]['revision'] == 1


def test_new_session_answer_survives_a_research_job_already_in_progress(db, monkeypatch):
    bl.save(BIZ, profile(), 0, 'first')
    def research_model(*a, **k):
        bl.capture({'id': BIZ}, {'expected_revision': 1, 'facts': [
            {'key': 'travel_buffer', 'kind': 'workflow', 'statement': '45 minutes.', 'certainty': 'reported'}]},
            '45 minutes.')
        return {'content': [{'type': 'text', 'text': json.dumps(profile())}]}
    monkeypatch.setattr(bl, '_call', research_model)
    with pytest.raises(bl.Conflict):
        bl.learn(BIZ, 'An earlier description.')
    assert '45 minutes.' in bl.context_block({'id': BIZ})
    assert db.records[BIZ]['revision'] == 2


def test_duplicate_session_answer_is_a_noop(db):
    fact = {'key': 'travel_buffer', 'kind': 'workflow', 'statement': '45 minutes.', 'certainty': 'reported'}
    bl.capture({'id': BIZ}, {'expected_revision': 0, 'facts': [fact]}, '45 minutes.')
    result = bl.capture({'id': BIZ}, {'expected_revision': 1, 'facts': [fact]}, '45 minutes.')
    assert result['revision'] == 1 and len(db.history) == 1
