"""Background plans (chief_plans): several pieces of work from one message,
run on the durable build worker, with Chief's first look at any stop.
No live services, no model calls."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

import chief_build_runtime as runtime
import chief_plans
from chief_code import WorkOrder, digest, finish

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER = '11111111-1111-1111-1111-111111111111'

ADD_ADA = {'title': 'Add Ada', 'action': {'type': 'create_contact', 'name': 'Ada Lovelace', 'status': 'lead'}}
CALL_ADA = {'title': 'Call Ada', 'action': {'type': 'create_task', 'title': 'Call Ada',
                                             'contact_id': '@create_contact.contact_id'}}
EMAIL_ADA = {'title': 'Email Ada', 'action': {'type': 'draft_and_send', 'contact_id': 'c-ada',
                                               'subject': 'Workshop', 'body': 'See you there'}}


def plan_order(steps, surface='desktop', words='Add Ada and remind me to call her', **facts):
    return WorkOrder.create({'kind': 'plan', 'facts': {'title': 'Ada', 'steps': steps, **facts}},
                            business_id=BIZ, user_id=USER, turn_id='turn-1', surface=surface, words=words)


class Adapter(chief_plans.PlanAdapter):
    def __init__(self, order):
        super().__init__(None, {'id': order.order_id, 'business_id': BIZ, 'user_id': USER}, 'lease', order)
        self.biz = {'id': BIZ, 'owner_id': USER, 'name': 'Test Coach'}
        self.saved = []

    async def assert_authority(self, step):
        pass

    async def save(self, state, status='running'):
        self.saved.append(copy.deepcopy(state))


class Door:
    """Stands in for chief_of_staff._execute_actions: the one door."""

    def __init__(self, fail=(), raise_on=()):
        self.calls = []
        self.fail = set(fail)
        self.raise_on = set(raise_on)

    async def __call__(self, client, biz, actions, user_id=None, prior_results=None, surface='chat',
                       prompted=True, owner_text=None):
        import chief_of_staff as chief
        self.calls.append({'actions': copy.deepcopy(actions), 'prior': copy.deepcopy(prior_results),
                           'user': chief._TURN_USER_ID.get(), 'owner_text': owner_text,
                           'confirmed': chief._TURN_CONFIRMED.get()})
        out = []
        for a in actions:
            t = a['type']
            if t in self.raise_on:
                raise TimeoutError('handler hung')
            if t in self.fail:
                out.append({'type': t, 'result': "Failed: no contact with that id", 'label': 'Could not do it',
                            'failed': True})
            elif t == 'create_contact':
                out.append({'type': t, 'result': 'created', 'label': 'Added Ada Lovelace', 'contact_id': 'c-ada'})
            elif t == 'show_view':
                out.append({'type': t, 'result': 'shown', 'label': 'Your leads',
                            'rows': [{'contact_id': 'c1', 'name': 'Bo'}, {'contact_id': 'c2', 'name': 'Cy'}]})
            else:
                out.append({'type': t, 'result': 'done', 'label': f'Done: {a.get("title") or t}', 'id': 'x-1'})
        return out


@pytest.fixture
def door(monkeypatch):
    import chief_of_staff as chief
    d = Door()
    monkeypatch.setattr(chief, '_execute_actions', d)
    import spend_guard
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **kw: False)
    return d


def looks(*decisions, seen=None):
    """A stand-in first look that answers with the given decisions in turn."""
    queue = list(decisions)

    async def fake(client, adapter, order, state, answer=None):
        if seen is not None:
            seen.append({'answer': answer, 'state': copy.deepcopy(state)})
        return (queue.pop(0) if queue else None), False
    return fake


# ─── The plan itself ─────────────────────────────────────────────────

def test_a_plan_is_checked_by_the_mission_rules_before_a_row_exists():
    o = plan_order([ADD_ADA, CALL_ADA])
    assert [s['id'] for s in o.facts['steps']] == ['step-1', 'step-2']
    assert o.facts['title'] == 'Ada'
    for bad, why in [
        ([{'title': 'x', 'action': {'type': 'no_such_verb'}}], 'unknown action'),
        ([{'title': 'x', 'action': {'type': 'propose_mission'}}], 'not allowed'),
        ([{'title': 'x', 'action': {'type': 'create_client_form', 'name': 'Sign up'}}], 'its own piece of work'),
        ([{'title': 'x', 'action': {'type': 'ensure_module', 'archetype': 'event_roster'}}], 'its own build'),
        ([{'title': 'x', 'action': {'type': 'generate_image', 'prompt': 'a'}},
          {'title': 'y', 'action': {'type': 'generate_image', 'prompt': 'b'}}], 'at most one image'),
        ([{'title': 'x', 'for_each': '@show_view.rows', 'action': {'type': 'send_sms', 'to': '{{item.phone}}'}}],
         'cleanly undoable'),
        ([], 'at least one step'),
    ]:
        with pytest.raises(ValueError) as exc:
            plan_order(bad)
        assert why in str(exc.value)
        assert 'mission' not in str(exc.value)


def test_the_model_cannot_pre_answer_or_pre_approve_a_plan():
    o = plan_order([ADD_ADA], plan_answer='yes, send everything', approvals={'step-1': 'x'}, brief='hi')
    assert set(o.facts) == {'title', 'goal', 'steps'} and o.approvals == {}


def test_steps_run_in_order_and_only_an_image_is_passed_over():
    image = {'title': 'Flyer', 'action': {'type': 'generate_image', 'prompt': 'Workshop flyer'}}
    uses_image = {'title': 'Share it', 'action': {'type': 'create_task', 'title': '@generate_image.image_id'}}
    o = plan_order([ADD_ADA, image, CALL_ADA, uses_image, EMAIL_ADA])
    steps = chief_plans.steps_for(o)
    by = {s.name: s for s in steps}
    assert by['step-2'].requires == ('step-1',)
    assert by['step-3'].requires == ('step-1',)          # the image doesn't hold it up
    assert set(by['step-4'].requires) == {'step-2', 'step-3'}   # it uses the image
    assert by['step-5'].sensitive and not by['step-5'].gate
    assert not by['step-1'].sensitive
    reviewed = plan_order([{**EMAIL_ADA, 'approval': True}])
    assert chief_plans.steps_for(reviewed)[0].gate


# ─── Running it ──────────────────────────────────────────────────────

def test_a_plan_runs_through_the_one_door_and_later_steps_use_earlier_results(door):
    o = plan_order([ADD_ADA, CALL_ADA])
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'done'
    assert [r['step'] for r in state['receipts']] == ['step-1', 'step-2']
    assert state['receipts'][0]['label'] == 'Added Ada Lovelace'
    # Step two was handed what step one found, for "@create_contact.contact_id".
    assert door.calls[1]['prior'][0]['contact_id'] == 'c-ada'
    assert door.calls[0]['user'] == USER and door.calls[0]['owner_text'] == o.practitioner_words
    public = runtime.public_job({'status': 'done', 'result': state, 'params': o.payload()})
    assert 'ref' not in public['result']['receipts'][0] and 'detail' not in public['result']['receipts'][0]


def test_a_step_repeats_over_the_rows_an_earlier_step_found(door):
    o = plan_order([{'title': 'Find leads', 'action': {'type': 'show_view', 'view': 'contacts'}},
                    {'title': 'A task for each', 'for_each': '@show_view.rows',
                     'action': {'type': 'create_task', 'title': 'Call {{item.name}}', 'contact_id': '{{item.contact_id}}'}}])
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'done'
    fanned = door.calls[1]['actions']
    assert [a['contact_id'] for a in fanned] == ['c1', 'c2'] and fanned[0]['title'] == 'Call Bo'
    assert state['receipts'][1]['label'] == 'A task for each: 2 done.'


def test_a_send_the_owner_asked_for_runs_on_their_ask_like_chat(door):
    o = plan_order([ADD_ADA, EMAIL_ADA])
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'done' and [c['actions'][0]['type'] for c in door.calls] == ['create_contact', 'draft_and_send']


def test_a_spoken_plan_holds_its_send_for_a_spoken_yes(door):
    o = plan_order([ADD_ADA, EMAIL_ADA], surface='voice')
    a = Adapter(o)
    held = asyncio.run(chief_plans.run_plan(o, a))
    assert held['status'] == 'held' and len(door.calls) == 1
    o.approvals = {'step-2': held['held']['fingerprint']}
    state = asyncio.run(chief_plans.run_plan(o, a, held))
    assert state['status'] == 'done' and door.calls[-1]['confirmed'] is True
    assert sum(1 for c in door.calls if c['actions'][0]['type'] == 'create_contact') == 1


def test_a_step_the_owner_wants_to_review_waits_on_every_surface(door):
    o = plan_order([ADD_ADA, {**CALL_ADA, 'approval': True}])
    held = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert held['status'] == 'held' and held['held']['step'] == 'step-2'
    assert 'Say “go ahead”' in held['held']['label']


def test_a_hung_write_is_never_repeated_blind(door, monkeypatch):
    door.raise_on = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA])
    monkeypatch.setattr(chief_plans, 'look', looks())
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['steps']['step-2']['outcome'] == 'uncertain'
    door.raise_on = set()
    again = asyncio.run(chief_plans.run_plan(o, Adapter(o), state))
    assert sum(1 for c in door.calls if c['actions'][0]['type'] == 'create_task') == 1
    assert again['steps']['step-2']['outcome'] == 'uncertain'


def test_a_clean_refusal_can_be_retried(door, monkeypatch):
    door.fail = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA])
    monkeypatch.setattr(chief_plans, 'look', looks())
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['steps']['step-2']['outcome'] == 'failed'
    assert 'no contact with that id' in state['steps']['step-2']['detail']
    door.fail = set()
    again = asyncio.run(chief_plans.run_plan(o, Adapter(o), state))
    assert again['status'] == 'done'


# ─── The first look ──────────────────────────────────────────────────

def test_at_a_stop_chief_looks_and_redirects_and_says_so(door, monkeypatch):
    door.fail = {'complete_task'}
    finish_it = {'title': 'Close the old task', 'action': {'type': 'complete_task', 'task_id': 't-9'}}
    o = plan_order([ADD_ADA, finish_it, CALL_ADA])
    decision = {'type': 'plan_decision', 'choice': 'continue',
                'note': 'The old task was already closed, so I skipped it and made the call task.',
                'steps': [CALL_ADA]}
    seen = []
    monkeypatch.setattr(chief_plans, 'look', looks(decision, seen=seen))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'done'
    assert [r['step'] for r in state['receipts']] == ['step-1', 'r1-1']
    assert state['summary_label'].startswith('The old task was already closed')
    assert state['looks'][0]['auto'] and state['looks'][0]['choice'] == 'continue'
    assert seen[0]['state']['steps']['step-2']['outcome'] == 'failed'
    # Ada was added once; the redirect didn't redo finished work.
    assert sum(1 for c in door.calls if c['actions'][0]['type'] == 'create_contact') == 1
    public = runtime.public_job({'status': 'done', 'result': state, 'params': o.payload()})
    assert public['result']['notes'] == [decision['note']]


def test_a_redirect_never_adds_a_send_on_its_own(door, monkeypatch):
    door.fail = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA])
    decision = {'type': 'plan_decision', 'choice': 'continue', 'note': 'I emailed Ada instead.',
                'steps': [EMAIL_ADA]}
    monkeypatch.setattr(chief_plans, 'look', looks(decision))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'held' and state['held']['step'] == 'r1-1'
    assert not any(c['actions'][0]['type'] == 'draft_and_send' for c in door.calls)


def test_a_send_the_owner_asked_for_survives_a_redirect_unchanged(door, monkeypatch):
    door.fail = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA, EMAIL_ADA])
    decision = {'type': 'plan_decision', 'choice': 'continue', 'note': 'Skipped the call task.',
                'steps': [EMAIL_ADA]}
    monkeypatch.setattr(chief_plans, 'look', looks(decision))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'done'
    changed = dict(EMAIL_ADA, action={**EMAIL_ADA['action'], 'body': 'Different words'})
    o2 = plan_order([ADD_ADA, CALL_ADA, EMAIL_ADA])
    door.calls.clear()
    monkeypatch.setattr(chief_plans, 'look', looks({**decision, 'steps': [changed]}))
    state2 = asyncio.run(chief_plans.run_plan(o2, Adapter(o2)))
    assert state2['status'] == 'held'


def test_chief_asks_when_it_needs_the_owner_and_their_answer_redirects(door, monkeypatch):
    door.fail = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA])
    ask = {'type': 'plan_decision', 'choice': 'ask', 'question': 'Which Ada did you mean?',
           'suggestion': 'Ada Lovelace.'}
    monkeypatch.setattr(chief_plans, 'look', looks(ask))
    asked = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert asked['status'] == 'needs_answer'
    assert asked['question'] == {'field': 'plan_answer', 'text': 'Which Ada did you mean? I suggest: Ada Lovelace.'}
    # The card or the chat answers; respond() stores it in the order's facts.
    door.fail = set()
    o.facts['plan_answer'] = 'Ada Lovelace'
    seen = []
    go = {'type': 'plan_decision', 'choice': 'continue', 'note': 'Using Ada Lovelace.', 'steps': [CALL_ADA]}
    monkeypatch.setattr(chief_plans, 'look', looks(go, seen=seen))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o), dict(asked, question=None, status='queued')))
    assert seen[0]['answer'] == 'Ada Lovelace'
    assert state['status'] == 'done' and not state.get('asked')
    assert [l['auto'] for l in state['looks']] == [True, False]
    # The same answer is not read twice on a later run.
    seen.clear()
    asyncio.run(chief_plans.run_plan(o, Adapter(o), state))
    assert seen == []


def test_chief_looks_at_most_twice_on_its_own(door, monkeypatch):
    door.fail = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA])
    again = {'type': 'plan_decision', 'choice': 'continue', 'note': 'Trying the task again.', 'steps': [CALL_ADA]}
    seen = []
    monkeypatch.setattr(chief_plans, 'look', looks(again, again, again, seen=seen))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert len(seen) == 2 and state['status'] == 'done_with_gaps'


def test_a_look_with_no_usable_answer_leaves_the_stop_standing(door, monkeypatch):
    door.fail = {'create_task'}
    o = plan_order([ADD_ADA, CALL_ADA])
    monkeypatch.setattr(chief_plans, 'look', looks(None))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'done_with_gaps'
    assert state['looks'][0]['choice'] == 'none'
    too_long = {'type': 'plan_decision', 'choice': 'continue', 'note': 'x', 'steps': [CALL_ADA] * 12}
    monkeypatch.setattr(chief_plans, 'look', looks(too_long))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['looks'][0]['choice'] == 'none' and state['status'] == 'done_with_gaps'


def test_the_look_reads_but_cannot_write(monkeypatch):
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    import spend_guard
    seen = {}

    async def call(client, system, messages, **kw):
        seen['writes'] = ctl.writes_allowed()
        seen['tools'] = {t['name'] for t in kw['read_tools']}
        seen['brief'] = messages[0]['content']
        return ('Ada was missing, so I will add her first. [ACTION:{"type":"plan_decision","choice":"continue",'
                '"note":"Added Ada first.","steps":[]}]')
    monkeypatch.setattr(cos, '_call_claude', call)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **kw: False)
    o = plan_order([ADD_ADA, CALL_ADA])
    a = Adapter(o)
    state = {'order': ['step-1', 'step-2'], 'steps': {
        'step-1': {'step': 'step-1', 'outcome': 'failed', 'label': 'Add Ada: this didn\'t go through.',
                   'detail': 'Failed: duplicate email', 'verified': {'ok': False}}}}
    decision, tainted = asyncio.run(chief_plans.look(None, a, o, state))
    assert decision['choice'] == 'continue' and tainted is False
    assert seen['writes'] is False
    assert not ({'create_contact', 'create_task', 'draft_and_send'} & seen['tools'])
    assert 'duplicate email' in seen['brief'] and o.practitioner_words in seen['brief']
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **kw: True)
    seen.clear()
    assert asyncio.run(chief_plans.look(None, a, o, state)) == (None, False) and not seen


# ─── Wiring ──────────────────────────────────────────────────────────

def test_the_worker_runs_a_plan_with_its_first_look(monkeypatch):
    o = plan_order([ADD_ADA, CALL_ADA])
    ran = []

    async def rpc(client, name, body):
        if name == 'claim':
            return [{'id': o.order_id, 'business_id': BIZ, 'user_id': USER, 'params': o.payload(),
                     'created_at': '2026-09-26T00:00:00+00:00'}]
        return [{'id': o.order_id}]

    async def database(*args, **kwargs):
        return []

    async def run_plan(order, adapter, previous=None):
        ran.append((order.kind, type(adapter).__name__))
        return {'status': 'done', 'summary_label': 'Done', 'receipts': []}

    async def announce(*args):
        pass
    monkeypatch.setattr(runtime, 'rpc', rpc)
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(runtime, 'announce', announce)
    monkeypatch.setattr(chief_plans, 'run_plan', run_plan)
    asyncio.run(runtime.worker(o.order_id))
    assert ran == [('plan', 'PlanAdapter')]


def test_chief_is_told_how_to_submit_a_plan(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    assert '- plan:' in runtime.routing_instructions()
    assert 'plan_answer' in runtime.routing_instructions()
    assert 'plan' in runtime.BUILD_TOOLS['submit_work_order'][1]['properties']['kind']['enum']
    assert 'kind plan' in runtime.context_block([])


def test_a_plan_submitted_in_a_turn_is_saved_as_one_build(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    saved = []

    async def database(client, method, path, body=None):
        return [{'id': BIZ, 'owner_id': USER}] if path.startswith('/businesses') else []

    async def service(client, method, path, body=None):
        saved.append(body)
        return [{**body, 'build_revision': 0}]
    import sb_clients
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(sb_clients, 'sb_as_service', service)
    monkeypatch.setattr(runtime, 'launch', lambda job: saved.append('launched'))
    token = runtime.turn_scope.set({'user_id': USER, 'turn_id': 'turn-1', 'surface': 'desktop',
                                    'words': 'add Ada and remind me to call her'})
    try:
        result = asyncio.run(runtime.submit(None, {'id': BIZ}, {'kind': 'plan', 'facts': {'steps': [ADD_ADA, CALL_ADA]}}))
    finally:
        runtime.turn_scope.reset(token)
    assert result['label'] == runtime.QUEUED_LABEL and saved[-1] == 'launched'
    assert saved[0]['params']['kind'] == 'plan' and saved[0]['params']['facts']['title'] == 'Add Ada'


def test_an_ask_runs_what_does_not_need_the_answer_first(door, monkeypatch):
    door.fail = {'create_task'}
    prep = {'title': 'Prep the room', 'action': {'type': 'complete_task', 'task_id': 't-prep'}}
    o = plan_order([ADD_ADA, CALL_ADA, prep])
    ask = {'type': 'plan_decision', 'choice': 'ask', 'question': 'Which Ada did you mean?',
           'suggestion': 'Ada Lovelace.', 'steps': [prep]}
    monkeypatch.setattr(chief_plans, 'look', looks(ask))
    state = asyncio.run(chief_plans.run_plan(o, Adapter(o)))
    assert state['status'] == 'needs_answer' and state['question']['field'] == 'plan_answer'
    assert [c['actions'][0]['type'] for c in door.calls][-1] == 'complete_task'
    assert state['steps']['r1-1']['verified']['ok'] and state['asked']


def test_a_look_that_ran_out_of_lookups_decides_once_more_without_tools(monkeypatch):
    import chief_of_staff as cos
    import spend_guard
    calls = []

    async def call(client, system, messages, **kw):
        calls.append({'tools': bool(kw.get('read_tools')), 'messages': messages})
        if len(calls) == 1:
            return 'Still checking the contacts'
        return '[ACTION:{"type":"plan_decision","choice":"ask","question":"Who is Dana?"}]'
    monkeypatch.setattr(cos, '_call_claude', call)
    monkeypatch.setattr(spend_guard, 'over_budget', lambda **kw: False)
    o = plan_order([ADD_ADA, CALL_ADA])
    state = {'order': ['step-1', 'step-2'], 'steps': {
        'step-1': {'step': 'step-1', 'outcome': 'failed', 'label': 'x', 'verified': {'ok': False}}}}
    decision, _ = asyncio.run(chief_plans.look(None, Adapter(o), o, state))
    assert decision['question'] == 'Who is Dana?'
    assert [c['tools'] for c in calls] == [True, False]
    assert calls[1]['messages'][1] == {'role': 'assistant', 'content': 'Still checking the contacts'}


# ─── What's left after the direct-change limit ─────────────────────────

def _tool_turn(monkeypatch, results, calls, *, submitted=False):
    import chief_of_staff as cos
    import chief_tool_loop as ctl
    queue = list(results)

    async def door(client, biz, actions, user_id=None, prior_results=None, surface='chat', prompted=True):
        calls.append(actions[0]['type'])
        return [queue.pop(0) if queue else {'type': actions[0]['type'], 'result': 'ok', 'label': 'x'}]
    monkeypatch.setattr(cos, '_execute_actions', door)

    async def main(names):
        ctl.reset_turn(writes_allowed=True)
        token = runtime.turn_scope.set({'user_id': USER, 'turn_id': 't', 'surface': 'desktop', 'words': 'w',
                                        'submitted': submitted})
        try:
            return [await ctl.execute_tool_use(None, {'id': BIZ}, n, a) for n, a in names]
        finally:
            runtime.turn_scope.reset(token)
    return main


PLAN_ARGS = {'kind': 'plan', 'facts': {'steps': [ADD_ADA, CALL_ADA]}}
TASK = ('create_task', {'title': 'x'})


def test_after_three_direct_changes_the_rest_goes_out_as_one_plan(monkeypatch):
    # Live 2026-09-26: nine changes asked, three made, "I'll finish the rest in the next pass".
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    calls = []
    main = _tool_turn(monkeypatch, [], calls)
    out = asyncio.run(main([TASK, TASK, TASK, TASK, ('submit_work_order', PLAN_ARGS)]))
    assert [err for err, _ in out] == [False, False, False, True, False]
    assert 'kind plan' in out[3][1] and 'next pass' in out[3][1]
    assert calls == ['create_task'] * 3 + ['submit_work_order']


def test_a_held_change_still_closes_the_turn(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    calls = []
    held = {'type': 'create_task', 'failed': True, 'result': 'Failed: HELD for a spoken yes', 'label': 'Held'}
    main = _tool_turn(monkeypatch, [held], calls)
    out = asyncio.run(main([TASK, ('submit_work_order', PLAN_ARGS)]))
    assert out[1][0] is True and 'HELD' in out[1][1] and calls == ['create_task']


def test_without_builds_or_after_the_one_order_the_old_limit_stands(monkeypatch):
    monkeypatch.setenv('CHIEF_BUILDS', 'off')
    calls = []
    out = asyncio.run(_tool_turn(monkeypatch, [], calls)([TASK] * 4))
    assert out[3][0] is True and 'kind plan' not in out[3][1]
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    calls.clear()
    out = asyncio.run(_tool_turn(monkeypatch, [], calls, submitted=True)([TASK] * 4))
    assert out[3][0] is True and 'kind plan' not in out[3][1]
