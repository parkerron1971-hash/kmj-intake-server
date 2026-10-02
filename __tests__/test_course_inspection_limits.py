import asyncio
import json
from unittest.mock import AsyncMock, patch

import chief_academy_actions as academy
import chief_tool_loop as loop

COURSE = '00000000-0000-4000-8000-000000000001'
LESSON = '00000000-0000-4000-8000-000000000002'
BIZ = {'id': '00000000-0000-4000-8000-000000000003'}


def record(size=7000):
    return {'type': 'inspect_course', 'data': {'course': {'id': COURSE, 'title': 'Six weeks'},
        'lessons': [{'id': str(index), 'title': f'Week {index + 1}',
                     'content': 'Teaching ' * size, 'revision': f'revision-{index}',
                     'learning_design': {'questions': [{'id': 'last-question', 'correct': 2}]}}
                    for index in range(6)]}}


def test_six_week_course_reaches_model_with_last_lesson_and_revision_intact():
    result = record(size=800)
    assert len(json.dumps(result)) > loop.MAX_RESULT_CHARS
    assert json.loads(loop._shrink(result)) == result


def test_large_course_returns_parseable_index_with_actionable_lesson_ids():
    result = record()
    reduced = json.loads(loop._shrink(result))
    assert reduced['data']['content_omitted'] is True
    assert reduced['data']['lesson_count'] == 6
    assert reduced['data']['lessons'][-1] == {'id': '5', 'title': 'Week 6'}
    assert 'lesson_id' in reduced['next_step']
    assert 'content' not in reduced['data']['lessons'][0]
    assert 'revision' not in reduced['data']['lessons'][0]


def test_single_oversized_lesson_fails_without_partial_teaching_content():
    result = record(size=20000)
    result['data']['lessons'] = result['data']['lessons'][:1]
    reduced = json.loads(loop._shrink(result))
    assert reduced['failed'] is True
    assert 'data' not in reduced


def test_even_oversized_index_stays_bounded_and_parseable():
    result = record()
    result['data']['course']['title'] = 'title' * academy.COURSE_READ_MAX_CHARS
    text = loop._shrink(result)
    assert len(text) <= academy.COURSE_READ_MAX_CHARS
    assert json.loads(text)['failed'] is True


def test_specific_lesson_read_preserves_complete_record_under_owner_rpc():
    data = record(size=800)['data']
    data['lessons'][4]['id'] = LESSON
    with patch.object(academy.sb_clients, 'sb_as_current_context', AsyncMock(return_value=data)) as rpc:
        reply = asyncio.run(academy.handle_inspect_course(None, BIZ, {'course_id': COURSE, 'lesson_id': LESSON}))
    assert rpc.call_args.args[3] == {'p_business': BIZ['id'], 'p_course': COURSE}
    assert rpc.call_args.kwargs['allow_service_fallback'] is False
    serialized = json.loads(loop._shrink(reply))
    assert serialized['data']['lessons'] == [data['lessons'][4]]
    assert serialized['data']['course'] == data['course']
    assert len(data['lessons']) == 6


def test_wrong_course_lesson_is_not_returned():
    with patch.object(academy, 'rpc', AsyncMock(return_value=record()['data'])):
        reply = asyncio.run(academy.handle_inspect_course(None, BIZ, {'course_id': COURSE, 'lesson_id': LESSON}))
    assert reply['failed'] is True and 'data' not in reply


def test_missing_course_or_invalid_lesson_fails_before_rpc():
    for action in ({'lesson_id': LESSON}, {'course_id': COURSE, 'lesson_id': 'invalid'}):
        with patch.object(academy, 'rpc', AsyncMock()) as rpc:
            reply = asyncio.run(academy.handle_inspect_course(None, BIZ, action))
        assert reply['failed'] is True
        rpc.assert_not_called()


def test_inspection_schema_advertises_narrow_read():
    assert 'lesson_id' in academy.READ_SCHEMA[1]['properties']
