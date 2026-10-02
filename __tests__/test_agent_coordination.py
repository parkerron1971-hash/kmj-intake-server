"""Behavioral coverage for tenant boundaries and delegated work's state machine."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException
import agent_coordination as ac

BID, AID, OTHER = (str(uuid4()) for _ in range(3))
FUTURE = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
BIZ = {"id": BID, "owner_id": "owner", "settings": {}}


@pytest.fixture
def db(monkeypatch):
    data = {"connected_agents": [{"id": AID, "business_id": BID, "token_jti": "key-1",
        "name": "Research", "capabilities": "Research suppliers", "use_when": "Need suppliers",
        "boundaries": "No purchases", "enabled": True, "approval_mode": "ask", "revision": 1,
        "allowed_tools": []}], "mcp_tokens": [{"jti": "key-1", "business_id": BID,
            "revoked_at": None, "expires_at": FUTURE, "scopes": ["read", "coordinate"]}], "agent_assignments": [], "events": []}

    def selected(path):
        table = urlsplit(path).path.lstrip('/')
        query = parse_qs(urlsplit(path).query)
        found = data[table]
        for field, values in query.items():
            val = values[0]
            if val.startswith('eq.'):
                found = [r for r in found if str(r.get(field)) == val[3:]]
            elif val.startswith('in.('):
                found = [r for r in found if r.get(field) in val[4:-1].split(',')]
        return found

    def get(path):
        return copy.deepcopy(selected(path))

    def post(path, body, **kwargs):
        table = urlsplit(path).path.lstrip('/')
        if table == 'agent_assignments' and any(r['business_id'] == body['business_id'] and r['request_id'] == body['request_id'] for r in data[table]):
            return []
        row = {"id": str(uuid4()), "progress": "", "result": "", "review_note": "", "claim_id": None, **copy.deepcopy(body)}
        data[table].append(row)
        return [copy.deepcopy(row)]

    def patch(path, body, **kwargs):
        found = selected(path)
        for row in found:
            row.update(copy.deepcopy(body))
        return copy.deepcopy(found)

    monkeypatch.setattr(ac.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(ac.sb_clients, 'sb_post_as_service', post)
    monkeypatch.setattr(ac.sb_clients, 'sb_patch_as_service', patch)
    monkeypatch.setattr(ac, 'operational', lambda biz: None)
    return data


def caller(bid=BID, jti='key-1', scopes=None):
    from types import SimpleNamespace
    return SimpleNamespace(kind='token', business_id=bid, jti=jti, scopes=scopes or ['read', 'coordinate'])


def brief(**changes):
    return ac.BriefBody(**{"agent_id": AID, "request_id": str(uuid4()), "title": "Compare suppliers",
        "objective": "Find three suppliers", "expected_output": "Sources and prices", "deadline": FUTURE, **changes})


def approve(task, action='approve', note=''):
    return ac.review(BIZ, task['id'], ac.ReviewBody(business_id=BID, action=action, note=note))


def test_full_approval_claim_result_review_loop(db):
    task = ac.create_assignment(BIZ, brief())
    assert task['status'] == 'awaiting_approval'
    assert ac.mailbox(caller(), BIZ, 'agent_inbox', {})['assignments'] == []
    with pytest.raises(HTTPException):
        ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    approve(task)
    claimed = ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    assert claimed['status'] == 'running'
    with pytest.raises(HTTPException):
        ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    report = {'assignment_id': task['id'], 'claim_id': claimed['claim_id'], 'status': 'submitted', 'message': 'Three sourced suppliers'}
    result = ac.mailbox(caller(), BIZ, 'report_agent_assignment', report)
    assert result['status'] == 'submitted'
    assert ac.mailbox(caller(), BIZ, 'report_agent_assignment', report) == result
    assert len(db['events']) == 1
    assert db['events'][0]['event_type'] == 'agent_assignment_reported'
    assert approve(task, 'accept')['status'] == 'accepted'


def test_automatic_mode_and_idempotent_creation(db):
    db['connected_agents'][0]['approval_mode'] = 'automatic'
    body = brief()
    first = ac.create_assignment(BIZ, body)
    assert first['status'] == 'queued'
    assert ac.create_assignment(BIZ, body)['id'] == first['id']
    assert len(db['agent_assignments']) == 1
    with pytest.raises(HTTPException):
        ac.create_assignment(BIZ, body.model_copy(update={'objective': 'Different work'}))


@pytest.mark.parametrize('bad', [caller(OTHER), caller(jti='another-key'), caller(scopes=['read'])])
def test_other_business_key_or_unscoped_caller_cannot_read_inbox(db, bad):
    with pytest.raises(HTTPException):
        ac.mailbox(bad, BIZ, 'agent_inbox', {})


def test_same_business_other_bot_cannot_claim_or_read_a_brief(db):
    task = ac.create_assignment(BIZ, brief())
    approve(task)
    db['connected_agents'].append({**db['connected_agents'][0], 'id': OTHER, 'token_jti': 'key-2'})
    db['mcp_tokens'].append({**db['mcp_tokens'][0], 'jti': 'key-2'})
    assert ac.mailbox(caller(jti='key-2'), BIZ, 'agent_inbox', {})['assignments'] == []
    with pytest.raises(HTTPException):
        ac.mailbox(caller(jti='key-2'), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})


@pytest.mark.parametrize('change', ['paused', 'revoked', 'expired', 'revision'])
def test_authority_is_rechecked_at_execution(db, change):
    task = ac.create_assignment(BIZ, brief()); approve(task)
    if change == 'paused': db['connected_agents'][0]['enabled'] = False
    if change == 'revoked': db['mcp_tokens'][0]['revoked_at'] = ac.now()
    if change == 'expired': db['mcp_tokens'][0]['expires_at'] = '2000-01-01T00:00:00+00:00'
    if change == 'revision': db['connected_agents'][0]['revision'] = 2
    with pytest.raises(HTTPException):
        ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})


def test_cancellation_and_wrong_claim_prevent_completion(db):
    task = ac.create_assignment(BIZ, brief()); approve(task)
    claimed = ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    args = {'assignment_id': task['id'], 'claim_id': str(uuid4()), 'status': 'submitted', 'message': 'Done'}
    with pytest.raises(HTTPException): ac.mailbox(caller(), BIZ, 'report_agent_assignment', args)
    approve(task, 'cancel')
    with pytest.raises(HTTPException): ac.mailbox(caller(), BIZ, 'report_agent_assignment', {**args, 'claim_id': claimed['claim_id']})


def test_agent_cannot_accept_approve_or_spoof_business(db):
    task = ac.create_assignment(BIZ, brief()); approve(task)
    claimed = ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    for extra in ({'status': 'accepted'}, {'business_id': OTHER}, {'agent_id': OTHER}):
        with pytest.raises(HTTPException):
            ac.mailbox(caller(), BIZ, 'report_agent_assignment', {'assignment_id': task['id'], 'claim_id': claimed['claim_id'], 'status': 'submitted', 'message': 'Done', **extra})


def test_feedback_requeues_with_a_new_claim(db):
    task = ac.create_assignment(BIZ, brief()); approve(task)
    claimed = ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    ac.mailbox(caller(), BIZ, 'report_agent_assignment', {'assignment_id': task['id'], 'claim_id': claimed['claim_id'], 'status': 'submitted', 'message': 'Findings'})
    with pytest.raises(HTTPException): approve(task, 'request_changes')
    assert approve(task, 'request_changes', 'Add source links')['status'] == 'queued'
    next_claim = ac.mailbox(caller(), BIZ, 'claim_agent_assignment', {'assignment_id': task['id']})
    assert next_claim['claim_id'] != claimed['claim_id']
    assert next_claim['review_note'] == 'Add source links'


def test_tool_access_is_explicit_and_does_not_expand_legacy_keys(db):
    assert not ac.permits_tool(caller(), 'catch_up')
    db['connected_agents'][0]['allowed_tools'] = ['catch_up']
    assert ac.permits_tool(caller(), 'catch_up')
    assert not ac.permits_tool(caller(), 'send_sms')
    assert ac.permits_tool(caller(scopes=['read']), 'catch_up')


def test_unavailable_storage_fails_closed(monkeypatch):
    monkeypatch.setattr(ac.sb_clients, 'sb_get_as_service', lambda path: None)
    with pytest.raises(HTTPException) as exc: ac.caller_profile(caller())
    assert exc.value.status_code == 503


def test_deadline_and_required_brief_fields(db):
    for deadline in ('2000-01-01T00:00:00+00:00', '2099-01-01T00:00:00'):
        with pytest.raises(HTTPException): ac.create_assignment(BIZ, brief(deadline=deadline))
    with pytest.raises(ValueError): brief(objective=' ')


def test_chief_tools_exist_but_are_not_exposed_to_external_agents():
    import action_registry, chief_tool_loop, mcp_server
    reads = {t['name'] for t in chief_tool_loop.read_tool_definitions()}
    writes = {t['name'] for t in chief_tool_loop.write_tool_definitions()}
    assert {'list_connected_agents', 'connected_agent_assignments'} <= reads
    assert 'delegate_to_agent' in writes
    for name in ac.CHIEF_TOOLS:
        assert not action_registry.may_expose_to_agent(name, allow_writes=True)
        assert name not in {t['name'] for t in mcp_server.tool_definitions()}


def test_real_mcp_dispatch_routes_mailbox_and_blocks_unapproved_tools(db, monkeypatch):
    import mcp_server
    from unittest.mock import AsyncMock
    c = mcp_server.Caller('token', 'test', business_id=BID, jti='key-1', scopes=['read', 'coordinate'])
    monkeypatch.setattr(mcp_server, '_resolve_business', AsyncMock(return_value=BIZ))
    monkeypatch.setattr(mcp_server, '_ledger', lambda *a, **k: None)
    tools = {t['name'] for t in mcp_server.tool_definitions(c)}
    assert tools == set(ac.MAILBOX_TOOLS)
    allowed, ok, payload, bid = asyncio.run(mcp_server._call_tool('agent_inbox', {}, c))
    assert allowed and ok and bid == BID and payload['agent']['id'] == AID
    assert asyncio.run(mcp_server._call_tool('catch_up', {}, c))[:2] == (False, False)
    assert asyncio.run(mcp_server._call_tool('delegate_to_agent', {}, c))[:2] == (False, False)


def test_owner_http_routes_and_cross_business_refusal(db, monkeypatch):
    import mcp_server
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    app = FastAPI(); app.include_router(ac.router)
    app.dependency_overrides[ac.require_user] = lambda: SimpleNamespace(id='owner', email='owner@example.test')
    monkeypatch.setattr(mcp_server, '_business_by_id', AsyncMock(side_effect=lambda client, bid: BIZ if bid == BID else {'id': bid, 'owner_id': 'someone-else'}))
    monkeypatch.setattr(ac, 'tool_choices', lambda: [])
    client = TestClient(app)
    assert client.get('/agent-coordination', params={'business_id': OTHER}).status_code == 403
    overview = client.get('/agent-coordination', params={'business_id': BID})
    assert overview.status_code == 200
    assert 'token_jti' not in overview.json()['agents'][0]
    body = brief().model_dump(mode='json')
    response = client.post('/agent-coordination/assignments', params={'business_id': BID}, json=body)
    assert response.status_code == 200
    task = response.json()['assignment']
    assert client.post(f"/agent-coordination/assignments/{task['id']}/review", json={'business_id': OTHER, 'action': 'approve'}).status_code == 403
    assert client.post(f"/agent-coordination/assignments/{task['id']}/review", json={'business_id': BID, 'action': 'approve'}).json()['assignment']['status'] == 'queued'


def test_configuration_revision_guard_cancels_existing_work(db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ac, 'owned', AsyncMock(return_value=BIZ))
    monkeypatch.setattr(ac, 'validate_tools', lambda body, biz: None)
    task = ac.create_assignment(BIZ, brief()); approve(task)
    body = ac.AgentBody(business_id=BID, name='Research', capabilities='Supplier research', enabled=False, revision=1)
    result = asyncio.run(ac.configure(ac.UUID(AID), body, SimpleNamespace(id='owner')))
    assert result['agent']['revision'] == 2 and not result['agent']['enabled']
    assert db['agent_assignments'][0]['status'] == 'cancelled'
    with pytest.raises(HTTPException): asyncio.run(ac.configure(ac.UUID(AID), body, SimpleNamespace(id='owner')))


def test_key_rotation_disconnects_old_key_even_if_revoke_fails(db, monkeypatch):
    import mcp_tokens
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    monkeypatch.setattr(ac, 'owned', AsyncMock(return_value=BIZ))
    def mint(*a, **kw):
        db['mcp_tokens'].append({**db['mcp_tokens'][0], 'jti': 'key-new'})
        return 'new-secret', {'jti': 'key-new', 'expires_at': FUTURE}
    monkeypatch.setattr(mcp_tokens, 'mint', mint)
    monkeypatch.setattr(mcp_tokens, 'revoke', lambda *a: False)
    task = ac.create_assignment(BIZ, brief()); approve(task)
    result = asyncio.run(ac.rotate_key(ac.UUID(AID), ac.RotateBody(business_id=BID, revision=1), SimpleNamespace(id='owner')))
    assert result['token'] == 'new-secret'
    assert db['agent_assignments'][0]['status'] == 'cancelled'
    with pytest.raises(HTTPException): ac.caller_profile(caller())


def test_business_pause_and_connector_kill_switch(monkeypatch):
    import mcp_server, policy_engine
    monkeypatch.setattr(mcp_server, '_tier_allows', lambda biz: True)
    monkeypatch.setattr(mcp_server, 'enabled', lambda: False)
    with pytest.raises(HTTPException): ac.operational(BIZ)
    monkeypatch.setattr(mcp_server, 'enabled', lambda: True)
    monkeypatch.setattr(policy_engine, 'is_paused', lambda biz: True)
    with pytest.raises(HTTPException): ac.operational(BIZ)


def test_failed_credential_persistence_is_not_reported_as_connected(db):
    with pytest.raises(HTTPException): ac.verify_key_saved(BID, 'missing-key')


def test_chief_can_read_complete_profiles_and_long_results(db):
    import chief_tool_loop
    db['connected_agents'][0]['capabilities'] = 'Detailed research ability. ' * 100
    roster = asyncio.run(ac.chief_handler(None, BIZ, {'type': 'list_connected_agents'}))
    assert len(roster['agents'][0]['capabilities_preview']) == 240
    full = asyncio.run(ac.chief_handler(None, BIZ, {'type': 'list_connected_agents', 'agent_id': AID}))
    assert full['agents'][0]['capabilities'] == db['connected_agents'][0]['capabilities']
    task = ac.create_assignment(BIZ, brief())
    db['agent_assignments'][0]['result'] = 'Detailed findings. ' * 700 + 'FINAL FINDING'
    listing = asyncio.run(ac.chief_handler(None, BIZ, {'type': 'connected_agent_assignments'}))
    assert 'result' not in listing['assignments'][0]
    result = asyncio.run(ac.chief_handler(None, BIZ, {'type': 'connected_agent_assignments', 'assignment_id': task['id']}))
    assert 'FINAL FINDING' in chief_tool_loop._shrink(result)
