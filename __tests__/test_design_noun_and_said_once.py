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
