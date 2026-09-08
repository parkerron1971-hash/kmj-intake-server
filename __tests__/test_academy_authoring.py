import asyncio
from unittest.mock import AsyncMock, patch

import chief_academy_actions as academy


BIZ = {"id": "00000000-0000-4000-8000-000000000002"}
COURSE = "00000000-0000-4000-8000-000000000004"


def test_rich_lesson_reaches_owner_rpc_and_frontend():
    lesson = {"title": "Next class", "content": "Actual lesson", "learning_design": {
        "workbook": {"title": "Practice", "introduction": "Begin", "prompts": ["Try"]},
        "questions": [{"id": "q1", "kind": "choice", "prompt": "Choose", "options": ["A", "B"], "correct": 1}]}}
    action = {"type": "save_course_content", "request_key": "test", "course_id": COURSE, "lessons": [lesson]}
    result = {"saved": True, "course_id": COURSE, "course_title": "Workshop", "lesson_ids": ["lesson-1"]}
    with patch.object(academy.sb_clients, "sb_as_current_context", AsyncMock(return_value=result)) as sb:
        reply = asyncio.run(academy.handle_save_course_content(None, BIZ, action))
    args = sb.call_args
    assert args.args[2] == "/rpc/academy_author"
    assert args.args[3]["p_document"]["lessons"] == [lesson]
    assert args.args[3]["p_business"] == BIZ["id"]
    assert args.kwargs["allow_service_fallback"] is False
    assert reply["frontend_event"]["detail"]["lesson_id"] == "lesson-1"
    assert reply["nav"]["page"] == "course-studio"


def test_failed_save_never_reports_success_or_navigates():
    with patch.object(academy.sb_clients, "sb_as_current_context", AsyncMock(return_value=None)):
        reply = asyncio.run(academy.handle_save_course_content(None, BIZ, {"request_key": "fail", "lessons": [{"title": "No"}]}))
    assert reply["failed"] is True
    assert "frontend_event" not in reply and "nav" not in reply


def test_creator_grading_choice_is_saved_without_rewriting_lessons():
    action = {"request_key": "assessment", "course_id": COURSE, "grading_mode": "letter", "passing_grade": 80, "lessons": []}
    result = {"saved": True, "course_id": COURSE, "course_title": "Workshop", "lesson_ids": []}
    with patch.object(academy.sb_clients, "sb_as_current_context", AsyncMock(return_value=result)) as sb:
        reply = asyncio.run(academy.handle_save_course_content(None, BIZ, action))
    document = sb.call_args.args[3]["p_document"]
    assert document["grading_mode"] == "letter" and document["passing_grade"] == 80
    assert document["lessons"] == []
    assert reply["label"] == "Saved assessment settings for Workshop"


def test_legacy_creation_uses_atomic_save_and_repeatable_key():
    action = {"type": "create_course", "title": "Workshop", "lessons": ["First", "Second"]}
    with patch.object(academy.sb_clients, "sb_as_current_context", AsyncMock(return_value=None)) as sb:
        asyncio.run(academy.handle_save_course_content(None, BIZ, action))
        first = sb.call_args.args[3]
        asyncio.run(academy.handle_save_course_content(None, BIZ, action))
        assert first == sb.call_args.args[3]
        assert first["p_document"]["lessons"] == [{"title": "First"}, {"title": "Second"}]


def test_inspection_is_scoped_and_ids_are_validated():
    with patch.object(academy.sb_clients, "sb_as_current_context", AsyncMock(return_value={"lessons": []})) as sb:
        reply = asyncio.run(academy.handle_inspect_course(None, BIZ, {"course_id": COURSE}))
        assert reply["data"] == {"lessons": []}
        assert sb.call_args.args[3] == {"p_business": BIZ["id"], "p_course": COURSE}
        sb.reset_mock()
        reply = asyncio.run(academy.handle_inspect_course(None, BIZ, {"course_id": "bad&business_id=eq.other"}))
        assert reply["failed"] and not sb.called


def test_actions_are_reachable_from_native_tools_and_dispatch():
    import chief_of_staff
    import mcp_server
    import action_registry
    assert "inspect_course" in mcp_server.TOOL_SCHEMAS
    assert "save_course_content" in mcp_server.WRITE_TOOL_SCHEMAS
    for verb in ("inspect_course", "save_course_content"):
        assert verb in chief_of_staff.ACTION_HANDLERS
        assert action_registry.may_expose_to_agent(verb, allow_writes=True)


def test_legacy_links_and_posts_go_to_graded_classroom(monkeypatch):
    import public_site
    monkeypatch.setenv("ACADEMY_CLASSROOM_V2", "on")
    with patch.object(public_site, "_learn_load", AsyncMock()) as load:
        page = asyncio.run(public_site._serve_learner(f"learn/{COURSE}/lesson"))
        mark = asyncio.run(public_site.learner_mark(COURSE, None))
    assert page.status_code == mark.status_code == 303
    assert page.headers["location"] == f"https://system.mysolutionist.app/classroom/{COURSE}"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert not load.called
