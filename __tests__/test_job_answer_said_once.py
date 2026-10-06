"""Answering a job in progress says its sentence once, and a plan beside
another job says "you can leave this chat" once.

#1290 fixed this for starting a job: the long sentence rides as `say`, and
the step line and receipt carry one short line ("Started your thumbnail").
respond_work_order (the owner answers a job's question, says go ahead, or
cancels it) still returned its summary as the label, the result AND the
reply, so the same sentence stacked the same way: as the step line's end,
as the reply, and on the receipt twice. And a message that started a plan
and a thumbnail printed two background sentences, each telling the owner
they could leave. No live services or paid calls.
"""
import asyncio
import json
from datetime import datetime, timezone

import pytest

import chief_build_runtime as runtime
import chief_of_staff as chief
import chief_truth
from __tests__.test_design_noun_and_said_once import ASK, BIZ, GOAL, TASK, USER, _submit, thumbnail_order

JOB = '22222222-2222-2222-2222-222222222222'
QUEUED = 'Your build is queued to continue.'
CANCELLED = 'Build cancelled. Completed work has been kept.'


def saved_job(result):
    return {'id': JOB, 'business_id': BIZ, 'user_id': USER, 'kind': 'build', 'status': 'done',
            'build_revision': 3, 'params': thumbnail_order().payload(), 'result': result,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'finished_at': datetime.now(timezone.utc).isoformat()}


ASKED = {'status': 'needs_answer', 'question': {'field': 'exact_copy', 'text': 'What should the thumbnail say?'}}
HELD = {'status': 'held', 'held': {'step': 'flyer', 'fingerprint': 'fp', 'say': 'go ahead',
                                   'label': 'Your thumbnail is ready to design.'}}


def _respond(monkeypatch, job, action, words='Sunday 10 AM', **scope):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    saved = []

    async def database(client, method, path, body=None):
        if path.startswith('/businesses'):
            return [{'id': BIZ, 'owner_id': USER}]
        if path.startswith('/rpc/chief_build_respond'):
            saved.append(body)
            return [{**job, 'params': body['p_params'], 'result': body['p_result'],
                     'status': 'cancelled' if body['p_cancel'] else 'queued',
                     'build_revision': job['build_revision'] + 1}]
        if path.startswith('/chief_jobs'):
            return [job]
        return []
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(runtime, 'launch', lambda row: None)
    token = runtime.turn_scope.set({'user_id': USER, 'turn_id': 'turn-2', 'surface': 'desktop',
                                    'words': words, **scope})
    try:
        out = asyncio.run(runtime.handle_respond_work_order(None, {'id': BIZ}, {
            'type': 'respond_work_order', 'job_id': JOB, **action}))
    finally:
        runtime.turn_scope.reset(token)
    return out, saved


def _step_lines(atype, action, out):
    events = []
    token = chief._STREAM_SINK.set(events.append)
    try:
        chief._turn_step_end(chief._turn_step_start(atype, 0, action), out)
    finally:
        chief._STREAM_SINK.reset(token)
    return [json.loads(e[len(chief.STEP_PREFIX):]) for e in events]


def _reply(taken, draft=''):
    return asyncio.run(chief_truth.finalize_reply(
        None, draft, ctx={}, view_detail='', taken=taken, message=ASK, business_id=BIZ, reviewer=None))


# ── Answering a job ──────────────────────────────────────────────────────

def test_answering_a_jobs_question_says_its_sentence_once(monkeypatch):
    action = {'field': 'exact_copy', 'answer': ['Sunday 10 AM']}
    out, saved = _respond(monkeypatch, saved_job(ASKED), action)
    assert saved and saved[0]['p_params']['facts']['exact_copy'] == ['Sunday 10 AM']
    # Both fields present (a missing result blanks the app), one short line
    # naming the job; the sentence rides once, as `say`.
    assert out['label'] == out['result'] == 'Resumed your thumbnail'
    assert out['say'] == QUEUED and not out.get('failed')
    assert out['build']['result']['summary_label'] == QUEUED

    # The step line: never the verb ("Respond work order"), never the sentence.
    steps = _step_lines('respond_work_order', action, out)
    assert [s['label'] for s in steps] == ['Continuing the work', 'Resumed your thumbnail']
    assert steps[-1]['state'] == 'done'

    # The reply says the sentence once, however it is stitched.
    reply, grounding = _reply([out], 'Got it.')
    assert reply == QUEUED and grounding['status'] == 'receipts'
    stitched = chief._stitch_after_stream('Got it, passing that along.', reply)
    assert stitched.count(QUEUED) == 1
    # Everywhere the owner reads this turn: the step lines, the receipt and
    # the reply. The sentence is in exactly one of them.
    seen = [s['label'] for s in steps] + [out['label'], out['result'], stitched]
    assert sum(text.count(QUEUED) for text in seen) == 1


def test_going_ahead_on_a_held_job_says_it_once(monkeypatch):
    out, saved = _respond(monkeypatch, saved_job(HELD), {'approve': True}, words='go ahead')
    assert saved and saved[0]['p_params']['approvals'] == {'flyer': 'fp'}
    assert out['label'] == out['result'] == 'Resumed your thumbnail' and out['say'] == QUEUED
    assert _reply([out])[0] == QUEUED


def test_cancelling_a_job_names_it_and_says_why_once(monkeypatch):
    action = {'cancel': True}
    out, saved = _respond(monkeypatch, saved_job(ASKED), action, words='cancel the thumbnail')
    assert saved and saved[0]['p_cancel'] is True
    assert out['label'] == out['result'] == 'Cancelled your thumbnail' and out['say'] == CANCELLED
    steps = _step_lines('respond_work_order', action, out)
    assert [s['label'] for s in steps] == ['Cancelling the work', 'Cancelled your thumbnail']
    assert _reply([out])[0] == CANCELLED


def test_a_plan_is_resumed_by_name(monkeypatch):
    job = {**saved_job({'status': 'needs_answer', 'question': {'field': 'plan_answer', 'text': 'Which Ada?'}}),
           'params': {'kind': 'plan', 'facts': {'title': 'Ada', 'steps': []}, 'practitioner_words': 'w'}}
    out, _ = _respond(monkeypatch, job, {'field': 'plan_answer', 'answer': 'Ada Lovelace'})
    assert out['label'] == out['result'] == 'Resumed your plan'


def test_a_refused_answer_still_says_why(monkeypatch):
    # One message cannot both start a job and answer one.
    out, saved = _respond(monkeypatch, saved_job(ASKED), {'field': 'exact_copy', 'answer': ['A']}, submitted=1)
    assert not saved and out['failed'] and out['label'] and out['result'] and 'say' not in out
    assert _reply([out])[0] == out['label']


def test_a_name_that_cannot_be_made_never_breaks_the_answer(monkeypatch, caplog):
    def broken(order):
        raise KeyError('kind')
    monkeypatch.setattr(runtime, 'order_name', broken)
    with caplog.at_level('WARNING', logger='chief_build_runtime'):
        out, saved = _respond(monkeypatch, saved_job(ASKED), {'field': 'exact_copy', 'answer': ['A']})
    assert saved and out['label'] == out['result'] == 'Resumed your work' and out['say'] == QUEUED
    assert any('job name for' in r.getMessage() and 'KeyError' in r.getMessage() for r in caplog.records)


def test_the_step_line_never_falls_back_to_the_verb():
    assert chief._step_phrase('respond_work_order') == 'Continuing the work'
    assert chief._step_phrase('respond_work_order', {'job_id': JOB, 'approve': True}) == 'Continuing the work'
    assert chief._humanize_actions([{'type': 'respond_work_order', 'job_id': JOB}]) == 'continuing the work'
    assert chief._humanize_actions([{'type': 'respond_work_order', 'cancel': True}]) == 'cancelling the work'


def test_an_answer_beside_other_work_still_says_it_once(monkeypatch):
    out, _ = _respond(monkeypatch, saved_job(ASKED), {'field': 'exact_copy', 'answer': ['A']})
    # A reviewed prose reply that did other things gets the sentence once...
    assert chief_truth.with_job_sentences('Added the task.', [out, TASK]) == f'Added the task.\n\n{QUEUED}'
    # ...and never a second time when it already said it.
    told = f'Added the task. {QUEUED}'
    assert chief_truth.with_job_sentences(told, [out, TASK]) == told


def test_the_model_reads_the_sentence_in_the_tool_result(monkeypatch):
    import chief_tool_loop as ctl
    out, _ = _respond(monkeypatch, saved_job(ASKED), {'field': 'exact_copy', 'answer': ['A']})
    seen = json.loads(ctl._shrink(out))
    assert seen['say'] == QUEUED and seen['label'] == seen['result'] == 'Resumed your thumbnail'


# ── A plan and another job, said once ────────────────────────────────────

PLAN = {'type': 'submit_work_order', 'kind': 'plan', 'facts': {'title': 'Ada', 'steps': [
    {'title': 'Add Ada', 'action': {'type': 'create_contact', 'name': 'Ada Lovelace', 'status': 'lead'}},
    {'title': 'Call Ada', 'action': {'type': 'create_task', 'title': 'Call Ada'}}]}}
THUMBNAIL = {'type': 'submit_work_order', 'kind': 'flyer',
             'facts': {'prompt': GOAL, 'exact_copy': ['Sunday 10 AM'], 'size': '1920x1088'}}
BOTH = ("Started your thumbnail. Working on these in the background: Add Ada and Call Ada. "
        "You can leave this chat; I'll let you know here when they're done or if I need you.")


def test_a_plan_and_a_thumbnail_say_they_can_leave_once(monkeypatch):
    thumbnail, plan = _submit(monkeypatch, THUMBNAIL), _submit(monkeypatch, PLAN)
    assert thumbnail['say'] == runtime.QUEUED_LABEL and plan['say'].startswith('Working on these')
    for taken in ([thumbnail, plan], [plan, thumbnail]):
        reply, grounding = _reply(taken, 'On it.')
        assert reply == BOTH and grounding['status'] == 'receipts'
        assert reply.count('You can leave this chat') == 1


def test_a_plan_a_thumbnail_and_a_form_name_every_job_once(monkeypatch):
    form = _submit(monkeypatch, {'type': 'submit_work_order', 'kind': 'form_and_link', 'facts': {'name': 'Signup'}})
    taken = [_submit(monkeypatch, THUMBNAIL), _submit(monkeypatch, PLAN), form]
    reply, _ = _reply(taken)
    assert reply.startswith('Started your thumbnail and your form. Working on these in the background: Add Ada')
    assert reply.count('You can leave this chat') == 1


def test_a_plan_and_a_thumbnail_beside_a_task_still_say_it_once(monkeypatch):
    thumbnail, plan = _submit(monkeypatch, THUMBNAIL), _submit(monkeypatch, PLAN)
    # Before, whichever job came first won: a thumbnail first dropped the
    # plan's pieces from the reply.
    for taken in ([thumbnail, plan, TASK], [plan, thumbnail, TASK]):
        assert chief_truth.with_job_sentences('Added the task.', taken) == f'Added the task.\n\n{BOTH}'


def test_a_refused_job_beside_a_plan_and_a_thumbnail_still_says_why(monkeypatch):
    thumbnail, plan = _submit(monkeypatch, THUMBNAIL), _submit(monkeypatch, PLAN)
    refused = _submit(monkeypatch, {'type': 'submit_work_order', 'kind': 'goal_setup', 'facts': {}})
    reply, _ = _reply([thumbnail, refused, plan])
    assert reply == f"{BOTH}\n\n{refused['label']}"


@pytest.mark.parametrize('says,expected', [
    # One job, or several saying the same: that sentence, untouched.
    ([runtime.QUEUED_LABEL], runtime.QUEUED_LABEL),
    ([runtime.QUEUED_LABEL, runtime.QUEUED_LABEL], runtime.QUEUED_LABEL),
    ([], ''),
    # A job already on its way says where it stands; the closing still comes once.
    ([runtime.QUEUED_LABEL, 'Your poster is generating. It will appear in Media Library.'],
     'Started your thumbnail. Your poster is generating. It will appear in Media Library. ' + runtime.LEAVE_MANY),
    # Nothing to close when no sentence offered to let them leave.
    (['Your poster is generating.', 'Your form is ready.'], 'Your poster is generating. Your form is ready.'),
])
def test_job_sentence(says, expected):
    labels = ['Started your thumbnail', 'Your poster']
    taken = [{'type': 'submit_work_order', 'label': labels[i], 'result': labels[i], 'say': s} for i, s in enumerate(says)]
    taken.append({'type': 'submit_work_order', 'failed': True, 'label': 'No.', 'result': 'No.', 'say': 'ignored'})
    assert runtime.job_sentence(taken + [TASK]) == expected
