"""A design is called what was asked for, and "I'm on it" is said once.

Live 2026-10-06 (Church, Chief chat): "Make a YouTube thumbnail ...
widescreen" came back as "Designing your flyer" and "All done with your
flyer", and one reply printed "I'm on it and working in the background.
You can leave this chat; ..." three or four times: as the step line,
after the reply, and as the receipt's label and again as its result.

Every design still goes through design_flyer and a kind-flyer work order;
only the words people read changed. No live services or paid calls.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import chief_build_runtime as runtime
import chief_of_staff as chief
import chief_truth
import clip_covers
import creative_director as d
import image_studio as images
from chief_code import WorkOrder, design_noun, flyer_noun, plan as plan_steps, question

BIZ = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
USER = '11111111-1111-1111-1111-111111111111'
ASK = 'Make a YouTube thumbnail for Sunday, widescreen, with Pastor Mike on it'
GOAL = 'A widescreen YouTube thumbnail for Sunday with Pastor Mike positioned on it'


def thumbnail_order(**facts):
    return WorkOrder.create({'kind': 'flyer', 'facts': {'prompt': GOAL, 'size': '1920x1088', **facts}},
                            business_id=BIZ, user_id=USER, turn_id='turn-1', surface='desktop', words=ASK)


# ── The noun ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('goal,size,owner,noun', [
    (GOAL, '1920x1088', ASK, 'thumbnail'),
    ('Bold widescreen art for the sermon video', '1920x1088', 'make a thumb nail for the video', 'thumbnail'),
    ('Bold art for our YouTube video', None, '', 'thumbnail'),
    (clip_covers.GOAL.format(title='Grace'), '1088x1920', 'Make a cover for this clip', 'cover'),
    ('A poster for the spring concert', None, '', 'poster'),
    ('A YouTube banner for the channel', '1920x1088', '', 'banner'),
    ('A bold flyer for the Saturday fade special', '1024x1536', '', 'flyer'),
    ('A flier for the bake sale', None, '', 'flyer'),
    ('A square Instagram post for the sale', '1024x1024', '', 'graphic'),
    ('A bold graphic announcing the sale', '1024x1024', '', 'graphic'),
    ('Saturday fade special, bold', None, '', 'flyer'),
    ('Saturday fade special, bold', '1024x1536', '', 'flyer'),
    ('Saturday fade special, bold', '1024x1024', '', 'graphic'),
])
def test_a_design_is_called_what_was_asked_for(goal, size, owner, noun):
    assert design_noun(goal, size, owner) == noun


def test_the_designs_own_brief_speaks_before_the_whole_message():
    # One message, two designs: each order is named by its own brief.
    both = 'Make a flyer for the workshop and a YouTube thumbnail for the recording'
    assert design_noun('A flyer for the workshop', None, both) == 'flyer'
    assert design_noun('A thumbnail for the recording', '1920x1088', both) == 'thumbnail'
    # With no noun in the brief, the owner's words decide.
    assert design_noun('Pastor Mike, bold, high contrast', '1920x1088', ASK) == 'thumbnail'


def test_cover_the_verb_is_not_a_cover():
    assert design_noun('A flyer that covers the costs and the date', None, '') == 'flyer'
    assert design_noun('Make sure it covers all the details', None, '') == 'flyer'


@pytest.mark.parametrize('goal,size,noun', [
    # A door charge, not a design: named by the shape.
    ('Saturday party, cover charge $10, bold', None, 'flyer'),
    ('Saturday party, cover charge $10, bold', '1024x1536', 'flyer'),
    ('Saturday party, cover charge $10, bold', '1920x1088', 'graphic'),
    ('Saturday party, $10 cover at the door, bold', None, 'flyer'),
    ('Saturday party, no cover before 10, bold', None, 'flyer'),
    ('Jazz night with a cover band, bold', None, 'flyer'),
    ('Fall cookout, cover-charge $5', '1024x1024', 'graphic'),
    # A picture to use, not the thing to make.
    ('Use the cover photo of the venue behind the headline', None, 'flyer'),
    ('Open house, cover image from our website in the background, then a poster layout', None, 'poster'),
    # Other non-design uses of the same words.
    ('Our poster child for the fundraiser, bold', None, 'flyer'),
    ('Celebrating a banner year for the youth group', '1024x1024', 'graphic'),
    # Still a cover when it is the thing to make.
    ('A Facebook cover photo for the church', '1920x1088', 'cover'),
    ('Album cover art for the choir', '1024x1024', 'cover'),
    ('A cover for this clip', '1088x1920', 'cover'),
])
def test_a_cover_charge_is_not_a_cover(goal, size, noun):
    assert design_noun(goal, size, '') == noun


def test_the_noun_never_reaches_a_machine_key():
    o = thumbnail_order()
    assert o.kind == 'flyer'
    steps = plan_steps(o)
    assert [(s.name, s.verb) for s in steps] == [('flyer', 'design_flyer')]
    assert steps[0].label == 'Your thumbnail is ready in Media Library.'
    assert flyer_noun(o) == 'thumbnail'


def test_a_workshops_flyer_is_still_a_flyer():
    from __tests__.test_chief_builds import order
    o = order()
    assert flyer_noun(o) == 'flyer'
    assert plan_steps(o)[-1].label == 'Your flyer is ready in Media Library.'


def test_the_questions_name_the_design():
    o = thumbnail_order()
    assert question(o)['text'].startswith('What should the thumbnail say, word for word?')


# ── Where people read it ─────────────────────────────────────────────────

def test_the_build_stages_holds_and_notices_name_the_design():
    o = thumbnail_order()
    adapter = SimpleNamespace(order=o)
    flyer_step = plan_steps(o)[0]
    assert runtime.Adapter.stage(adapter, flyer_step) == 'Creating thumbnail'
    held = asyncio.run(runtime.Adapter.confirmation(adapter, flyer_step, {}))
    assert held.startswith('Your thumbnail is ready to design')
    job = {'id': 'j', 'params': o.payload(), 'status': 'done', 'created_at': '2026-10-06T00:00:00+00:00'}
    headline, body, _ = runtime.outcome_message(job, {'status': 'done', 'summary_label': flyer_step.label})
    assert headline == 'Done: your thumbnail' and 'flyer' not in body
    # The app's "All done with ..." reads the noun the build carries.
    assert runtime.public_job(job)['noun'] == 'thumbnail'


def test_a_saved_job_from_before_today_still_reads():
    legacy = {'id': 'j', 'status': 'done', 'params': {'kind': 'flyer', 'facts': {'prompt': 'Saturday special'}}}
    assert runtime.public_job(legacy)['noun'] == 'flyer'
    assert 'noun' not in runtime.public_job({'id': 'j', 'status': 'done', 'params': {'kind': 'plan', 'facts': {}}})


def test_the_directors_receipt_names_the_design(monkeypatch):
    async def prepare(client, biz, req, **kw):
        return {'scope': 'business', 'references': [], 'goal': req.goal}
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[]))
    monkeypatch.setattr(d, 'prepare_for_business', prepare)
    monkeypatch.setattr(images, 'create', AsyncMock(return_value={'id': 'img', 'status': 'queued'}))
    turn, index = images.turn_id.set('t-thumb'), images.turn_image_index.set(0)
    try:
        result = asyncio.run(d.handle_design_flyer(None, {'id': BIZ}, {
            'goal': GOAL, 'exact_copy': ['Sunday 10 AM'], 'size': '1920x1088', 'owner_request': ASK}))
        cover = asyncio.run(d.handle_design_flyer(None, {'id': BIZ}, {
            'goal': clip_covers.GOAL.format(title='Grace'), 'exact_copy': ['Grace'], 'size': '1088x1920',
            'owner_request': 'Make a cover for this clip'}))
    finally:
        images.turn_id.reset(turn); images.turn_image_index.reset(index)
    assert result['type'] == 'design_flyer'
    assert result['label'] == 'Designing your thumbnail' and result['result'].startswith('Your thumbnail is being designed')
    assert cover['label'] == 'Designing your cover' and cover['result'].startswith('Your cover is being designed')
    for r in (result, cover):
        assert 'flyer' not in r['label'] + r['result']


def test_a_replayed_design_keeps_its_name(monkeypatch):
    existing = {'id': 'img', 'status': 'working'}
    monkeypatch.setattr(images, 'db', AsyncMock(return_value=[existing]))
    monkeypatch.setattr(images, 'present', AsyncMock(return_value=existing))
    result = asyncio.run(d.handle_design_flyer(None, {'id': BIZ}, {'goal': GOAL, 'exact_copy': ['A']}))
    assert result['label'] == 'Your thumbnail' and result['result'].startswith('This thumbnail is already')


def test_the_step_line_names_the_design_while_it_starts():
    assert chief._step_phrase('design_flyer', {'goal': GOAL, 'size': '1920x1088'}) == 'Designing your thumbnail'
    action = {'type': 'submit_work_order', 'kind': 'flyer', 'facts': {'prompt': GOAL}}
    assert chief._step_phrase('submit_work_order', action) == 'Starting your thumbnail'
    assert chief._step_phrase('submit_work_order', {'kind': 'form_and_link', 'facts': {}}) == 'Starting your form'
    # Without the action (a read, an old caller) it is the plain phrase.
    assert chief._step_phrase('create_contact') == 'Adding the contact'
    # The turn's one-phrase status says it the same way.
    assert chief._humanize_actions([{'type': 'design_flyer', 'goal': GOAL}]) == 'designing your thumbnail'


def test_a_broken_name_is_logged_and_never_falls_back_to_the_verb(monkeypatch, caplog):
    def broken(action):
        raise KeyError('kind')
    monkeypatch.setattr(runtime, 'starting_phrase', broken)
    action = {'type': 'submit_work_order', 'kind': 'flyer', 'facts': {'prompt': GOAL}}
    with caplog.at_level('WARNING', logger='chief_of_staff'):
        line = chief._step_phrase('submit_work_order', action)
        status = chief._humanize_actions([action])
    assert line == 'Starting the work' and status == 'starting the work'
    warned = [r for r in caplog.records if 'step phrase for submit_work_order failed' in r.getMessage()]
    assert len(warned) == 2 and 'KeyError' in warned[0].getMessage()
    import chief_code
    monkeypatch.setattr(chief_code, 'design_noun', lambda *a: 1 / 0)
    with caplog.at_level('WARNING', logger='chief_of_staff'):
        assert chief._step_phrase('design_flyer', {'goal': GOAL}) == 'Starting the design'
    assert any('step phrase for design_flyer failed' in r.getMessage() for r in caplog.records)


# ── Said once ────────────────────────────────────────────────────────────

def _submit(monkeypatch, payload, words=ASK):
    monkeypatch.setenv('CHIEF_BUILDS', 'on')
    async def database(client, method, path, body=None):
        return [{'id': BIZ, 'owner_id': USER}] if path.startswith('/businesses') else []
    async def service(client, method, path, body=None):
        return [{**body, 'build_revision': 0}]
    import sb_clients
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(sb_clients, 'sb_as_service', service)
    monkeypatch.setattr(runtime, 'launch', lambda job: None)
    token = runtime.turn_scope.set({'user_id': USER, 'turn_id': 'turn-1', 'surface': 'desktop', 'words': words})
    try:
        return asyncio.run(runtime.handle_submit_work_order(None, {'id': BIZ}, payload))
    finally:
        runtime.turn_scope.reset(token)


def test_starting_a_design_says_the_sentence_once(monkeypatch):
    out = _submit(monkeypatch, {'type': 'submit_work_order', 'kind': 'flyer',
                                'facts': {'prompt': GOAL, 'exact_copy': ['Sunday 10 AM'], 'size': '1920x1088'}})
    # Both fields present (a missing result blanks the app), one short line.
    assert out['label'] == out['result'] == 'Started your thumbnail'
    assert out['say'] == runtime.QUEUED_LABEL
    assert 'leave this chat' not in out['label'] + out['result']
    assert out['build']['noun'] == 'thumbnail'

    # The step line: starts named, ends with the short line, never the sentence.
    events = []
    token = chief._STREAM_SINK.set(events.append)
    try:
        step = chief._turn_step_start('submit_work_order', 0, {'kind': 'flyer', 'facts': {'prompt': GOAL}})
        chief._turn_step_end(step, out)
    finally:
        chief._STREAM_SINK.reset(token)
    steps = [json.loads(e[len(chief.STEP_PREFIX):]) for e in events]
    assert [s['label'] for s in steps] == ['Starting your thumbnail', 'Started your thumbnail']
    assert steps[-1]['state'] == 'done'

    # The reply: what already streamed, then the sentence, once.
    reply, grounding = asyncio.run(chief_truth.finalize_reply(
        None, 'On it.', ctx={}, view_detail='', taken=[out], message=ASK, business_id=BIZ, reviewer=None))
    assert reply == runtime.QUEUED_LABEL and grounding['status'] == 'receipts'
    stitched = chief._stitch_after_stream("On it — I'll draft a widescreen thumbnail.", reply)
    assert stitched.count('You can leave this chat') == 1


def test_several_jobs_in_one_message_say_it_once(monkeypatch):
    first = {'type': 'submit_work_order', 'label': 'Started your thumbnail', 'result': 'Started your thumbnail',
             'say': runtime.QUEUED_LABEL}
    second = {'type': 'submit_work_order', 'label': 'Started your form', 'result': 'Started your form',
              'say': runtime.QUEUED_LABEL}
    reply, _ = asyncio.run(chief_truth.finalize_reply(
        None, '', ctx={}, view_detail='', taken=[first, second], message=ASK, business_id=BIZ, reviewer=None))
    assert reply == runtime.QUEUED_LABEL


def test_a_refused_start_still_says_why(monkeypatch):
    out = _submit(monkeypatch, {'type': 'submit_work_order', 'kind': 'goal_setup', 'facts': {}})
    assert out['failed'] and out['label'] and out['result']
    reply, _ = asyncio.run(chief_truth.finalize_reply(
        None, '', ctx={}, view_detail='', taken=[out], message=ASK, business_id=BIZ, reviewer=None))
    assert reply == out['label']


# ── Said once when the reply did other things too ────────────────────────

TASK = {'type': 'create_task', 'result': 'added', 'label': 'Task: Call Ada about Sunday'}


def _started(monkeypatch):
    return _submit(monkeypatch, {'type': 'submit_work_order', 'kind': 'flyer',
                                 'facts': {'prompt': GOAL, 'exact_copy': ['Sunday 10 AM'], 'size': '1920x1088'}})


def test_a_job_and_a_task_in_one_reply_still_say_they_can_leave(monkeypatch):
    job = _started(monkeypatch)
    taken = [job, TASK]
    reply = "I added a task to call Ada about Sunday. Started your thumbnail."
    review = json.dumps({'verdict': 'supported', 'claims': [
        {'text': 'I added a task to call Ada about Sunday', 'kind': 'action', 'source_id': 'result:1',
         'quote': 'Task: Call Ada about Sunday'},
        {'text': 'Started your thumbnail', 'kind': 'action', 'source_id': 'result:0',
         'quote': 'Started your thumbnail'}]})

    async def reviewer(*a, **k):
        return review
    text, _ = asyncio.run(chief_truth.finalize_reply(
        None, reply, ctx={}, view_detail='', taken=taken, message=ASK, business_id=None,
        reviewer=reviewer, repairer=None, budget_s=20.0))
    assert text.count('You can leave this chat') == 1
    assert text.rstrip().endswith(runtime.QUEUED_LABEL)
    assert 'Ada' in text


def test_a_failed_task_beside_a_started_job_says_both(monkeypatch):
    job = _started(monkeypatch)
    failed = {'type': 'create_task', 'failed': True, 'result': 'Failed: no title', 'label': 'Task'}
    text, grounding = asyncio.run(chief_truth.finalize_reply(
        None, 'Done.', ctx={}, view_detail='', taken=[job, failed], message=ASK, business_id=None,
        reviewer=None, repairer=None, budget_s=20.0))
    assert grounding['status'] == 'receipts'
    assert text.count('You can leave this chat') == 1


def test_a_reply_that_already_told_them_is_not_told_twice():
    job = {'type': 'submit_work_order', 'label': 'Started your thumbnail', 'result': 'Started your thumbnail',
           'say': runtime.QUEUED_LABEL}
    told = "Started your thumbnail. You can leave this chat and I'll tell you here."
    assert chief_truth.with_job_sentences(told, [job, TASK]) == told
    assert chief_truth.with_job_sentences('Added the task.', [job, TASK]).endswith(runtime.QUEUED_LABEL)
    assert chief_truth.with_job_sentences('Added the task.', [TASK]) == 'Added the task.'
    assert chief_truth.with_job_sentences(None, [TASK]) is None


def test_the_model_reads_the_sentence_in_the_tool_result(monkeypatch):
    # Native tool turns: chief_tool_loop hands the model the receipt it
    # shrank, so `say` (what to tell the owner) reaches the model.
    import chief_tool_loop as ctl
    monkeypatch.setenv('CHIEF_BUILDS', 'on')

    async def door(client, biz, actions, user_id=None, prior_results=None, surface='chat', prompted=True):
        return [await runtime.handle_submit_work_order(client, biz, actions[0])]
    monkeypatch.setattr(chief, '_execute_actions', door)

    async def database(client, method, path, body=None):
        return [{'id': BIZ, 'owner_id': USER}] if path.startswith('/businesses') else []

    async def service(client, method, path, body=None):
        return [{**body, 'build_revision': 0}]
    import sb_clients
    monkeypatch.setattr(runtime, 'db', database)
    monkeypatch.setattr(sb_clients, 'sb_as_service', service)
    monkeypatch.setattr(runtime, 'launch', lambda job: None)

    async def main():
        ctl.reset_turn(writes_allowed=True)
        token = runtime.turn_scope.set({'user_id': USER, 'turn_id': 't-tool', 'surface': 'desktop', 'words': ASK})
        try:
            out = await ctl.execute_tool_use(None, {'id': BIZ}, 'submit_work_order',
                                             {'kind': 'flyer', 'facts': {'prompt': GOAL, 'exact_copy': ['Sunday']}})
            # The full receipt, say included, is what the turn keeps for its reply.
            return out, list(ctl.writes_this_turn())
        finally:
            runtime.turn_scope.reset(token)
    (is_error, text), kept = asyncio.run(main())
    assert not is_error
    seen = json.loads(text)
    assert seen['say'] == runtime.QUEUED_LABEL and seen['label'] == 'Started your thumbnail'
    assert seen['result'] == 'Started your thumbnail' and seen['for_chief']
    assert kept[-1]['say'] == runtime.QUEUED_LABEL
