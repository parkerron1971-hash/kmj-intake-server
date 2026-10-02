"""
test_build_progress_and_status.py — background work says where it is (2026-09-24).

Kevin: "if chief is putting something together ... share progress, like
'I am almost done' or 'just finished with ... now going on to ...'", and
"a way for chief to do work in background so ... where recent chats are
it would have working / waiting / done / queued".

Builds already ran on the server and checkpointed each step. Now each
checkpoint carries a line in Chief's voice built from the plan and the
verified receipts (never a model), the build remembers the chat that
asked for it, and a build that finishes or needs the practitioner tells
them once: a notification that opens that chat, a "while you were away"
line, and a push.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_build_runtime as runtime
from chief_code import WorkOrder, run
from __tests__.test_chief_builds import BIZ, USER, MemoryAdapter, order


class StagedAdapter(MemoryAdapter):
    # The real stage names ("Preparing Events", "Creating flyer", ...).
    def stage(self, step):
        return runtime.Adapter.stage(None, step)


def _says(adapter):
    """The line at each checkpoint, repeats dropped (a step saves before
    and after it runs)."""
    out = []
    for c in adapter.checkpoints:
        say = (c.get('progress') or {}).get('say')
        if say and (not out or out[-1] != say):
            out.append(say)
    return out


def test_each_step_says_what_finished_and_what_is_next():
    a = StagedAdapter()
    result = asyncio.run(run(order(), a))
    assert _says(a) == [
        'On it. Preparing Events (1 of 6).',
        'Events is ready in Build. Now saving workshop (2 of 6).',
        'Your workshop is saved. Now checking events page (3 of 6).',
        'Your events page is available. Now checking registration (4 of 6).',
        'Registration is connected to your workshop. Now connecting website (5 of 6).',
        'Your website links to Events. Almost done: creating flyer (6 of 6).',
    ]
    p = result['progress']
    assert (p['step'], p['steps'], p['say']) == (6, 6, 'All done. Every step is checked.')


def test_finished_only_names_a_verified_step():
    a = StagedAdapter(fail_verify='events_page')
    result = asyncio.run(run(order(), a))
    assert not any('could not be verified' in s for s in _says(a))
    # The step after the failure still names the last step that DID check out.
    assert _says(a)[-1] == 'Your workshop is saved. Almost done: creating flyer (6 of 6).'
    assert result['progress']['say'] == 'Finished what I could: 3 of 6 steps checked.'


def test_a_queued_child_is_almost_done_not_done():
    result = asyncio.run(run(order(), StagedAdapter(child=True)))
    assert result['status'] == 'waiting'
    assert result['progress']['say'].startswith('Almost done. Still waiting on this: Your flyer is generating')


def test_the_build_remembers_the_asking_chat_and_only_a_plain_id():
    def make(cid):
        return WorkOrder.create({'kind': 'flyer', 'facts': {'prompt': 'x'}}, business_id=BIZ, user_id=USER,
                                turn_id='t', surface='desktop', words='make a flyer', conversation_id=cid)
    assert make('chat-2026_09_24-abc').conversation_id == 'chat-2026_09_24-abc'
    for bad in ('a b', "x'; drop", 'x' * 81, None, 42):
        assert make(bad).conversation_id == ''
    kept = make('chat-1')
    assert WorkOrder(**kept.payload()).conversation_id == 'chat-1'
    legacy = {k: v for k, v in kept.payload().items() if k != 'conversation_id'}
    assert WorkOrder(**legacy).conversation_id == ''   # rows written before today still load


def test_the_card_payload_carries_the_chat():
    job = {'id': 'j1', 'kind': 'build', 'status': 'queued', 'created_at': 'x', 'build_revision': 1,
           'params': {'kind': 'flyer', 'facts': {'title': 'Fall flyer'}, 'conversation_id': 'chat-1'},
           'result': {'progress': {'pct': 50, 'say': 'On it.'}}}
    public = runtime.public_job(job)
    assert public['conversation_id'] == 'chat-1' and public['result']['progress']['say'] == 'On it.'
    assert runtime.public_job({**job, 'params': {'kind': 'flyer', 'facts': {}}})['conversation_id'] is None


def test_the_turn_hands_the_chat_id_to_the_build():
    import chief_of_staff as cos
    assert 'conversation_id' in cos.ChatRequest.model_fields
    assert "'conversation_id':str(req.conversation_id or '')[:80]" in inspect.getsource(cos.chief_chat)
    assert "conversation_id=ctx.get('conversation_id')" in inspect.getsource(runtime.submit)


def test_starting_says_they_can_leave():
    assert "You can leave this chat" in runtime.QUEUED_LABEL
    assert 'queued_label(order)' in inspect.getsource(runtime.submit)
    flyer = SimpleNamespace(kind='flyer', facts={})
    plan = SimpleNamespace(kind='plan', facts={'steps': [{'title': 'Add Ada'}, {'title': 'Call Ada'}, {'title': 'Print tags'}]})
    assert runtime.queued_label(flyer) == runtime.QUEUED_LABEL
    assert runtime.queued_label(plan).startswith('Working on these in the background: Add Ada, Call Ada and Print tags.')
    assert 'You can leave this chat' in runtime.queued_label(plan)


@pytest.mark.parametrize('status,headline,priority', [
    ('done', 'Done: Fall Workshop', 'normal'),
    ('done_with_gaps', 'Mostly done: Fall Workshop', 'normal'),
    ('failed', "Couldn't finish: Fall Workshop", 'normal'),
    ('held', 'Waiting on you: Fall Workshop', 'high'),
    ('needs_answer', 'One detail needed: Fall Workshop', 'high'),
])
def test_each_outcome_has_its_message(status, headline, priority):
    job = {'params': {'kind': 'event_setup', 'facts': {'title': 'Fall Workshop'}}}
    result = {'status': status, 'summary_label': 'Your events page is available.',
              'held': {'label': 'Your flyer is waiting for your go-ahead.'},
              'question': {'text': 'What time does it start?'}}
    h, body, p = runtime.outcome_message(job, result)
    assert (h, p) == (headline, priority) and body
    if status == 'held':
        assert body == 'Your flyer is waiting for your go-ahead.'
    if status == 'needs_answer':
        assert body == 'What time does it start?'


def test_cancelled_and_running_say_nothing():
    for status in ('cancelled', 'waiting', 'queued'):
        assert runtime.outcome_message({'params': {}}, {'status': status}) is None


class _Store:
    def __init__(self, seen=False, fail=False):
        self.posts, self.seen, self.fail = [], seen, fail

    async def call(self, client, method, path, body=None):
        if self.fail:
            raise RuntimeError('down')
        if method == 'GET':
            return [{'id': 'n1'}] if self.seen else []
        self.posts.append((path, copy.deepcopy(body)))
        return [body]


def _job(age_s=120):
    created = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    return {'id': 'job-1', 'business_id': BIZ, 'user_id': USER, 'build_revision': 3, 'created_at': created,
            'params': {'kind': 'form_and_link', 'facts': {'name': 'Intake form'}, 'conversation_id': 'chat-7'}}


def _announce(monkeypatch, store, job, result):
    import sb_clients
    import push_notifications
    pushes = []
    monkeypatch.setattr(sb_clients, 'sb_as_service', store.call)
    monkeypatch.setattr(push_notifications, 'send_to_user', lambda uid, **kw: pushes.append((uid, kw)) or 1)
    asyncio.run(runtime.announce(None, job, result))
    return pushes


def test_a_finished_build_opens_its_chat(monkeypatch):
    store = _Store()
    pushes = _announce(monkeypatch, store, _job(), {'status': 'done', 'summary_label': 'Your form is ready.'})
    paths = [p for p, _ in store.posts]
    assert paths == ['/chief_activity', '/chief_notifications']
    note = store.posts[1][1]
    assert note['type'] == 'chief_work' and note['title'] == 'Done: Intake form'
    assert note['suggested_action'] == 'open_conversation'
    assert note['action_payload'] == {'conversation_id': 'chat-7', 'job_id': 'job-1'}
    assert note['data']['key'] == 'job-1:done:3'
    assert pushes and pushes[0][1]['data']['conversation_id'] == 'chat-7'


def test_the_same_outcome_is_told_once(monkeypatch):
    store = _Store(seen=True)
    pushes = _announce(monkeypatch, store, _job(), {'status': 'done', 'summary_label': 'x'})
    assert store.posts == [] and pushes == []


def test_a_quick_build_is_told_in_the_chat_not_by_notification(monkeypatch):
    store = _Store()
    pushes = _announce(monkeypatch, store, _job(age_s=5), {'status': 'needs_answer', 'question': {'text': 'When?'}})
    assert [p for p, _ in store.posts] == ['/chief_activity'] and pushes == []


def test_a_notification_failure_never_fails_the_build(monkeypatch):
    _announce(monkeypatch, _Store(fail=True), _job(), {'status': 'failed', 'summary_label': 'x'})


def test_the_worker_announces_both_endings():
    src = inspect.getsource(runtime.worker)
    assert 'await announce(client, job, result)' in src and 'await announce(client, job, failed)' in src
