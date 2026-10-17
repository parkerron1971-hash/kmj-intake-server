"""Class slides: Chief's save_lesson_slides and the slide editor's server routes.

The deck saves through academy_save_deck (owner/teacher JWT, revision-checked;
rehearsed against production in a rolled-back transaction, see the worklog).
These tests hold the server-side rules that keep a slide truthful:
scripture is the Bible text or the lesson's own words, never the model's;
pictures are the business's own; chart numbers are the lesson's.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import academy_slides_router
import action_registry
import chief_academy_actions as academy
import mcp_server
import sb_clients

BIZ = {"id": "00000000-0000-4000-8000-000000000002"}
COURSE = "00000000-0000-4000-8000-000000000004"
LESSON = "00000000-0000-4000-8000-000000000005"
LESSON_TEXT = ("*What happened, and who am I now?*\n\n"
               "> Therefore, if anyone is in Christ, he is a new creation. The old has passed away; behold, the new has come.\n>\n"
               "> 2 Corinthians 5:17\n\nThe shop spent $3,900 on payroll and $1,200 on rent.")
STORAGE = "https://brqjgbpzackdihgjsorf.supabase.co/storage/v1/object/public/business-assets/x/published-artwork/a.jpg"


def course_with(saved=False, revision=None):
    lesson = {"id": LESSON, "title": "New Life & Identity", "content": LESSON_TEXT, "slides_saved": saved}
    if saved:
        lesson.update(slides=[{"id": "s1", "layout": "title"}], slides_revision=revision)
    return {"course": {"id": COURSE}, "lessons": [lesson]}


# ─── The rules ────────────────────────────────────────────────────────

def test_empty_scripture_is_filled_from_the_bible_text_not_the_model():
    [slide] = academy.clean_slides([{"id": "m", "layout": "memory", "quote": {"text": "", "ref": "1 Peter 2:9"}}], LESSON_TEXT)
    assert slide["quote"]["ref"] == "1 Peter 2:9"
    assert slide["quote"]["translation"] == "WEB"
    assert slide["quote"]["text"].startswith("But you are a chosen race, a royal priesthood")


def test_kjv_marks_never_reach_a_slide():
    passage = academy.scripture_passage("Genesis 1:2", "kjv")
    assert "[" not in passage["text"] and "¶" not in passage["text"]
    assert passage["translation"] == "KJV"


def test_a_whole_chapter_or_a_long_passage_is_not_a_slide():
    assert academy.scripture_passage("Psalm 23") is None          # chapter, no verses
    assert academy.scripture_passage("John 3:1-36") is None       # longer than a slide
    assert academy.scripture_passage("not a reference") is None


def test_the_lessons_own_quotation_is_kept_word_for_word():
    text = "Therefore, if anyone is in Christ, he is a new creation."
    [slide] = academy.clean_slides([{"id": "q", "layout": "quote", "quote": {"text": text, "ref": "2 Corinthians 5:17"}}], LESSON_TEXT)
    assert slide["quote"]["text"] == text


def test_typography_differences_do_not_count_as_a_different_quote():
    curly = "Therefore, if anyone is in Christ, he is a new creation. The old has passed away; behold, the new has come."
    [slide] = academy.clean_slides([{"id": "q", "layout": "quote", "quote": {"text": "  " + curly.upper() + " ", "ref": "x"}}], LESSON_TEXT)
    assert slide["layout"] == "quote"


def test_scripture_the_model_typed_is_refused():
    with pytest.raises(ValueError, match="copied exactly from the lesson"):
        academy.clean_slides([{"id": "q", "layout": "quote", "quote": {"text": "For God so loved the world", "ref": "John 3:16"}}], LESSON_TEXT)


def test_a_quote_slide_needs_a_quote():
    with pytest.raises(ValueError, match="has no quote"):
        academy.clean_slides([{"id": "q", "layout": "memory"}], LESSON_TEXT)


def test_pictures_must_be_the_businesses_own():
    ok = academy.clean_slides([{"id": "p", "layout": "picture", "image": {"url": STORAGE}}], LESSON_TEXT)
    assert ok[0]["image"]["url"] == STORAGE
    for url in ("https://example.test/stock.jpg", "http://brqjgbpzackdihgjsorf.supabase.co/storage/v1/object/public/a.jpg"):
        with pytest.raises(ValueError, match="business's own storage"):
            academy.clean_slides([{"id": "p", "layout": "picture", "image": {"url": url}}], LESSON_TEXT)


def test_chart_numbers_come_from_the_lesson():
    chart = {"type": "bar", "items": [{"label": "Payroll", "value": 3900}, {"label": "Rent", "value": 1200}]}
    assert academy.clean_slides([{"id": "c", "layout": "chart", "chart": chart}], LESSON_TEXT)[0]["chart"] == chart
    invented = {"type": "bar", "items": [{"label": "Payroll", "value": 4100}, {"label": "Rent", "value": 1200}]}
    with pytest.raises(ValueError, match="isn't in the lesson"):
        academy.clean_slides([{"id": "c", "layout": "chart", "chart": invented}], LESSON_TEXT)


def test_ids_are_made_unique_and_unknown_layouts_refused():
    slides = academy.clean_slides([{"id": "a", "layout": "title"}, {"id": "a", "layout": "point"}, {"layout": "list"}], LESSON_TEXT)
    assert len({s["id"] for s in slides}) == 3
    assert all(s["source"] == "chief" for s in slides)
    with pytest.raises(ValueError, match="layouts"):
        academy.clean_slides([{"id": "a", "layout": "carousel"}], LESSON_TEXT)
    with pytest.raises(ValueError, match="between 1 and 60"):
        academy.clean_slides([], LESSON_TEXT)


# ─── The tool ─────────────────────────────────────────────────────────

def run_save(inspect, action, saved_result=None):
    calls = []

    async def fake(client, method, path, body, *, allow_service_fallback=False):
        calls.append((path, body, allow_service_fallback))
        if path == "/rpc/academy_inspect":
            return inspect
        return saved_result if saved_result is not None else {"lesson_id": LESSON, "course_id": COURSE, "revision": 1}

    with patch.object(academy.sb_clients, "sb_as_current_context", AsyncMock(side_effect=fake)):
        reply = asyncio.run(academy.handle_save_lesson_slides(None, BIZ, action))
    return reply, calls


def test_a_saved_deck_reaches_the_owner_rpc_and_reopens_the_slides_tab():
    action = {"course_id": COURSE, "lesson_id": LESSON,
              "slides": [{"id": "t", "layout": "title", "title": "New Life & Identity", "notes": "pace yourself"},
                         {"id": "m", "layout": "memory", "quote": {"text": "", "ref": "1 Peter 2:9"}}]}
    reply, calls = run_save(course_with(), action)
    assert [c[0] for c in calls] == ["/rpc/academy_inspect", "/rpc/academy_save_deck"]
    assert all(c[2] is False for c in calls), "never falls back to the service role"
    body = calls[1][1]
    assert body["p_lesson"] == LESSON and body["p_revision"] is None
    assert len(body["p_source_hash"]) == 64
    assert body["p_slides"][0]["notes"] == "pace yourself"
    assert body["p_slides"][1]["quote"]["translation"] == "WEB"
    assert reply["result"] == "saved" and reply["label"] == "Saved 2 slides for New Life & Identity"
    assert reply["frontend_event"]["detail"]["part"] == "slides"
    assert reply["nav"]["page"] == "course-studio"


def test_saved_slides_need_their_revision_so_newer_edits_survive():
    action = {"course_id": COURSE, "lesson_id": LESSON, "slides": [{"id": "t", "layout": "title"}]}
    reply, calls = run_save(course_with(saved=True, revision=3), action)
    assert reply["failed"] is True and "slides_revision" in reply["result"]
    assert [c[0] for c in calls] == ["/rpc/academy_inspect"]
    reply, calls = run_save(course_with(saved=True, revision=3), {**action, "slides_revision": 3},
                            {"lesson_id": LESSON, "course_id": COURSE, "revision": 4})
    assert calls[1][1]["p_revision"] == 3 and reply["result"] == "saved"


def test_a_lesson_from_another_course_or_a_refused_rule_saves_nothing():
    other = {"course": {"id": COURSE}, "lessons": []}
    reply, calls = run_save(other, {"course_id": COURSE, "lesson_id": LESSON, "slides": [{"id": "t", "layout": "title"}]})
    assert reply["failed"] is True and "not found" in reply["result"]
    reply, calls = run_save(course_with(), {"course_id": COURSE, "lesson_id": LESSON,
                                            "slides": [{"id": "q", "layout": "quote", "quote": {"text": "Made up words", "ref": "John 1:1"}}]})
    assert reply["failed"] is True and len(calls) == 1
    assert "frontend_event" not in reply and "nav" not in reply


def test_bad_ids_fail_closed():
    reply, calls = run_save(course_with(), {"course_id": "nope", "lesson_id": LESSON, "slides": [{"id": "t", "layout": "title"}]})
    assert reply["failed"] is True and calls == []


def test_the_tool_is_a_reviewed_class_a_write_with_its_schema():
    description, schema = mcp_server.WRITE_TOOL_SCHEMAS["save_lesson_slides"]
    assert "Does not publish, present, enroll or send anything" in description
    assert schema["required"] == ["course_id", "lesson_id", "slides"]
    assert action_registry.effect("save_lesson_slides") == action_registry.WRITE
    assert action_registry.reversibility("save_lesson_slides") == "A"
    import chief_of_staff
    assert chief_of_staff.ACTION_HANDLERS["save_lesson_slides"] is chief_of_staff.handle_save_lesson_slides
    assert "SLIDES:" in academy.PROMPT and "save_lesson_slides" in academy.PROMPT
    assert academy.is_course_tool([{"type": "tool_use", "name": "save_lesson_slides"}])


# ─── The routes ──────────────────────────────────────────────────────

@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(academy_slides_router.router)
    app.dependency_overrides[sb_clients.authed_request] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="u1", email="owner@example.com"), jwt="jwt")
    return TestClient(app)


def test_scripture_route_returns_the_verse_text(api):
    r = api.get("/academy-slides/scripture", params={"ref": "Rom 8:1"})
    assert r.status_code == 200
    assert r.json()["ref"] == "Romans 8:1" and r.json()["text"].startswith("There is therefore now no condemnation")
    assert api.get("/academy-slides/scripture", params={"ref": "Psalm 23"}).status_code == 404
    assert api.get("/academy-slides/scripture", params={"ref": "x" * 81}).status_code == 400


def test_scripture_route_needs_a_signed_in_person():
    app = FastAPI()
    app.include_router(academy_slides_router.router)
    assert TestClient(app).get("/academy-slides/scripture", params={"ref": "Rom 8:1"}).status_code in (401, 403)


def test_slide_art_checks_the_owner_before_making_a_public_copy(api):
    import image_studio
    order = []
    with patch.object(image_studio, "business", AsyncMock(side_effect=lambda *a: order.append("owner") or {"id": "b"})), \
         patch.object(image_studio, "artwork", AsyncMock(side_effect=lambda *a: order.append("artwork") or {"id": "a"})), \
         patch.object(image_studio, "delivery_jpeg", AsyncMock(side_effect=lambda *a: order.append("copy") or STORAGE)):
        r = api.post("/academy-slides/art", json={"business_id": BIZ["id"], "artwork_id": LESSON})
    assert r.status_code == 200 and r.json() == {"url": STORAGE}
    assert order == ["owner", "artwork", "copy"]


def test_the_router_is_registered_before_the_catch_all():
    src = open("kmj_intake_automation.py", encoding="utf-8").read()
    mine = src.index("app.include_router(academy_slides_router)")
    assert mine < src.index("app.include_router(public_site_router)")
