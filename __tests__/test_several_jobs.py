"""Step 2 of Kevin's multi-task plan (Dev Desk, 2026-09-26): one message can
start several background jobs (a workshop, a flyer, a plan for the rest),
and jobs in different lanes run side by side. The lane rule itself lives
in SQL (APPLY-2026-09-26-chief-build-lanes.sql) and is checked by
scripts/chief-build-lanes-db-check.mjs. No live services."""
import asyncio

import pytest

import chief_build_runtime as runtime
from chief_code import stable_id

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER = '11111111-1111-1111-1111-111111111111'
PLAN = {'kind': 'plan', 'facts': {'steps': [{'title': 'Add Ada', 'action': {'type': 'create_contact', 'name': 'Ada'}}]}}


@pytest.fixture
def saving(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    saved, launched = [], []

    async def database(client, method, path, body=None):
        return [{'id': BIZ, 'owner_id': USER}] if path.startswith('/businesses') else []

    async def service(client, method, path, body=None):
        saved.append(body)
        return [{**body, 'build_revision': 0}]
    import sb_clients
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(sb_clients, 'sb_as_service', service)
    monkeypatch.setattr(runtime, 'launch', lambda job: launched.append(job['id']))
    return saved, launched


def _turn(**extra):
    return runtime.turn_scope.set({'user_id': USER, 'turn_id': 'turn-7', 'surface': 'desktop',
                                   'words': 'set up the workshop, make a flyer and handle the rest',
                                   'submitted': False, **extra})


def test_one_message_starts_several_jobs_each_with_its_own_identity(saving):
    saved, launched = saving
    token = _turn()
    try:
        out = [asyncio.run(runtime.submit(None, {'id': BIZ}, p)) for p in (
            {'kind': 'flyer', 'facts': {'prompt': 'Workshop flyer'}},
            PLAN,
            {'kind': 'site_door', 'facts': {}})]
        ctx = runtime.turn_scope.get()
        assert ctx['submitted'] == 3
    finally:
        runtime.turn_scope.reset(token)
    ids = [o['job_id'] for o in out]
    assert len(set(ids)) == 3 and launched == ids
    # The first keeps the original identity, so a replayed turn still matches.
    assert ids[0] == stable_id(BIZ, 'turn-7') and ids[1] == stable_id(BIZ, 'turn-7', 'build:2')
    assert [s['params']['kind'] for s in saved] == ['flyer', 'plan', 'site_door']


def test_a_message_starts_at_most_four(saving):
    token = _turn(submitted=runtime.MAX_ORDERS_PER_TURN)
    try:
        with pytest.raises(ValueError) as exc:
            asyncio.run(runtime.submit(None, {'id': BIZ}, PLAN))
    finally:
        runtime.turn_scope.reset(token)
    assert 'Put the rest into a plan' in str(exc.value)


def test_answering_a_job_and_starting_one_stay_separate_turns(saving, monkeypatch):
    token = _turn(submitted=1)
    try:
        answered = asyncio.run(runtime.handle_respond_work_order(None, {'id': BIZ}, {'job_id': BIZ, 'approve': True}))
    finally:
        runtime.turn_scope.reset(token)
    assert answered['failed']
    token = _turn(responded=True)
    try:
        started = asyncio.run(runtime.handle_submit_work_order(None, {'id': BIZ}, PLAN))
    finally:
        runtime.turn_scope.reset(token)
    assert started['failed'] and 'next message' in started['label']


def test_the_overflow_stays_open_until_the_last_job(monkeypatch):
    import chief_tool_loop as ctl
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    ctl.reset_turn(writes_allowed=True)
    for count, open_ in ((0, True), (runtime.MAX_ORDERS_PER_TURN - 1, True), (runtime.MAX_ORDERS_PER_TURN, False)):
        token = _turn(submitted=count)
        try:
            assert ctl._overflow_to_plan_open() is open_
        finally:
            runtime.turn_scope.reset(token)
    token = _turn(responded=True)
    try:
        assert ctl._overflow_to_plan_open() is False
    finally:
        runtime.turn_scope.reset(token)


def test_a_finished_job_starts_whatever_waited_behind_it(monkeypatch):
    from chief_code import WorkOrder
    o = WorkOrder.create(PLAN, business_id=BIZ, user_id=USER, turn_id='t', surface='desktop', words='w')
    launched, asked = [], []

    async def rpc(client, name, body):
        if name == 'claim':
            return [{'id': o.order_id, 'business_id': BIZ, 'user_id': USER, 'params': o.payload(),
                     'created_at': '2026-09-26T00:00:00+00:00'}]
        return [{'id': o.order_id}]

    async def database(client, method, path, body=None):
        asked.append(path)
        return [{'id': 'waiting-1'}, {'id': 'waiting-2'}] if 'status=eq.queued' in path else []

    async def run_plan(order, adapter, previous=None):
        return {'status': 'done', 'summary_label': 'Done', 'receipts': []}

    async def announce(*args):
        pass
    import chief_plans
    monkeypatch.setattr(runtime, 'rpc', rpc)
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(runtime, 'announce', announce)
    monkeypatch.setattr(runtime, 'launch', lambda job: launched.append(job['id']))
    monkeypatch.setattr(chief_plans, 'run_plan', run_plan)
    asyncio.run(runtime.worker(o.order_id))
    assert launched == ['waiting-1', 'waiting-2']
    assert any(f'business_id=eq.{BIZ}' in p and 'status=eq.queued' in p for p in asked)


def test_chief_is_told_it_can_start_one_job_per_piece(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    text = runtime.routing_instructions()
    assert 'one order per piece' in text and 'up to four orders per turn' in text
    assert 'only one work order per turn' not in text
