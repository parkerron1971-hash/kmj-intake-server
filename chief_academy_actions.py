"""Owner-scoped, atomic Course Studio authoring shared by chat and voice tools."""
import hashlib
import json
from uuid import UUID
import sb_clients


def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TEXT = {"type": "string"}
QUESTION = obj({"id": TEXT, "prompt": TEXT, "kind": {"type": "string", "enum": ["written", "choice"]},
                "options": {"type": "array", "items": TEXT}, "correct": {"type": "integer", "minimum": 0},
                "required": {"type": "boolean"}}, ["id", "prompt", "kind", "required"])
DESIGN = obj({"version": {"type": "integer", "enum": [1]}, "module": TEXT, "objective": TEXT,
              "workbook": obj({"title": TEXT, "introduction": TEXT, "prompts": {"type": "array", "items": TEXT}}, ["title", "introduction", "prompts"]),
              "resources": {"type": "array", "items": obj({"id": TEXT, "title": TEXT, "url": TEXT}, ["id", "title", "url"])},
              "questions": {"type": "array", "items": QUESTION, "maxItems": 50},
              "passing_score": {"type": "integer", "minimum": 0, "maximum": 100},
              "session": obj({"starts_at": {"type": "string", "description": "ISO date with time zone, or empty if unknown."}, "url": TEXT, "preparation": TEXT}, ["starts_at", "url", "preparation"])})
LESSON = obj({"id": {**TEXT, "description": "Existing lesson ID for edits; omit to append a new lesson."},
              "revision": {**TEXT, "description": "Required on edits. Exact revision from inspect_course; detects intervening edits."},
              "title": TEXT, "content": {**TEXT, "description": "Complete teaching content in Markdown."}, "homework": TEXT,
              "lesson_type": {"type": "string", "enum": ["lesson", "video", "reading", "exercise"]},
              "video_url": TEXT, "resource_url": TEXT, "duration_minutes": {"type": "integer", "minimum": 0, "maximum": 1440},
              "drip_offset_days": {"type": "integer", "minimum": 0, "maximum": 3650},
              "learning_design": {**DESIGN, "description": "Complete learning design. On edits, preserve existing fields when changing only one section."}}, ["title"])
READ_SCHEMA = ("Read this business's courses, or a course's complete lessons, materials, answer keys and edit revisions. Use before setting up the next lesson or changing existing work.",
               obj({"course_id": TEXT}))
WRITE_SCHEMA = ("Save a complete course or append/update lessons in Course Studio. Creates real teaching content, downloadable workbook prompts, resources, written exercises, quizzes and live-class details atomically. New courses stay drafts. Does not publish, enroll or send anything. Existing published-course edits are immediately visible to students.",
                obj({"request_key": {**TEXT, "description": "Unique key for this requested save. Reuse exactly when retrying the same payload."},
                     "course_id": {**TEXT, "description": "Existing course ID; omit to create a new draft course."},
                     "title": TEXT, "description": TEXT,
                     "grading_mode": {"type": "string", "enum": ["completion", "percentage", "letter"], "description": "Creator's chosen assessment: completion pass/fail, percentage average, or A-F. Omit to preserve existing settings."},
                     "passing_grade": {"type": "integer", "minimum": 1, "maximum": 100},
                     "lessons": {"type": "array", "minItems": 0, "maxItems": 24, "items": LESSON, "description": "Complete lessons. Empty only when updating assessment settings on an existing course."}}, ["request_key", "lessons"]))


async def rpc(client, path, body):
    # Never silently substitute service credentials for a creator's session.
    return await sb_clients.sb_as_current_context(client, "POST", "/rpc/" + path, body, allow_service_fallback=False)


async def handle_inspect_course(client, biz, action):
    try:
        cid = str(UUID(action["course_id"])) if action.get("course_id") else None
        data = await rpc(client, "academy_inspect", {"p_business": biz["id"], "p_course": cid})
        if not isinstance(data, dict):
            raise ValueError("Course records could not be loaded. Retry before authoring.")
        return {"type": "inspect_course", "result": "Course records loaded", "label": "Course Studio", "data": data}
    except Exception as exc:
        return {"type": "inspect_course", "failed": True, "result": str(exc), "label": "Could not load course"}


async def handle_save_course_content(client, biz, action):
    kind = action.get("type", "save_course_content")
    try:
        document = {k: action[k] for k in ("course_id", "title", "description", "lessons", "grading_mode", "passing_grade") if k in action}
        if document.get("course_id"):
            document["course_id"] = str(UUID(document["course_id"]))
        # Keep older ACTION-tag callers compatible without the old partial-write loop.
        if kind == "create_course":
            document["lessons"] = [{"title": v} if isinstance(v, str) else v for v in document.get("lessons", [])]
            if not document["lessons"]:
                document["lessons"] = [{"title": "Welcome", "content": document.get("description", "")}]
        key = action.get("request_key")
        if not key and kind == "create_course":
            key = "legacy:" + hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        if not isinstance(key, str) or not 1 <= len(key) <= 160:
            raise ValueError("A request_key is required for a safe retry.")
        result = await rpc(client, "academy_author", {"p_business": biz["id"], "p_request_key": key, "p_document": document})
        if not isinstance(result, dict) or result.get("saved") is not True:
            raise ValueError("The course was not saved. Check Course Studio availability and retry.")
        count = len(result.get("lesson_ids", []))
        detail = {"business_id": biz["id"], "course_id": result["course_id"], "lesson_id": (result.get("lesson_ids") or [None])[0]}
        label = f"Saved {count} lesson(s) in {result['course_title']}" if count else f"Saved assessment settings for {result['course_title']}"
        return {"type": kind, "result": "saved", "label": label,
                "data": result, "nav": {"tab": "build", "page": "course-studio"},
                "frontend_event": {"name": "solutionist-course-updated", "detail": detail}}
    except Exception as exc:
        return {"type": kind, "failed": True, "result": str(exc), "label": "Course content was not saved"}


PROMPT = '''COURSE STUDIO AUTHORING: When asked to set up the next class/lesson or build a course, do the saved work using inspect_course and save_course_content. Read courses to resolve a unique course; if ambiguous, ask which. Read the selected course's lessons to continue its sequence and preserve existing work. Generate complete useful teaching prose, an objective, practical workbook prompts (Course Studio renders the downloadable PDF automatically), written exercises and valid quiz options/zero-based correct answers when appropriate. Use stable distinct question IDs; preserve IDs for unchanged questions. All fields go into the native schema, not merely a chat outline. Append by omitting lesson id; update with id and exact revision. Preserve complete learning_design when editing a section. New courses stay draft. Tell the teacher if the target course is published and changes will be student-visible. Only claim saved after the tool succeeds; use returned course/lesson IDs and frontend navigation. Use one request_key per intended save and reuse on retry. Never fabricate a video URL, hosted PDF URL, meeting link, date, payment link, or email delivery. Reuse relevant verified existing/provided URLs. If a real meeting link or date is missing, leave blank, save everything else, and clearly name the remaining setup item. Authoring does not create a Zoom/Meet room. Drafts do not enroll students or send messages. The practitioner's direct request is authorization to author; do not ask them to copy content from chat or to reconfirm routine saves.'''

PROMPT += " For course assessment, preserve the existing grading_mode and passing_grade unless the creator asks to change them. New courses default to completion pass/fail; explain this and ask the creator to choose completion, percentage or letter grading when they have not specified a preference, while still saving the requested lesson content. Percentage and letter modes use an equal average of lesson activity grades, with written work awaiting teacher grading. Letter bands are A 90+, B 80+, C 70+, D 60+, F below 60; passing_grade is configurable. Students submit all activities before completing a lesson; course passing is separate from lesson completion. An existing course assessment-only change may use an empty lessons array. Teacher logins and gradebook live in Course Studio; never claim teacher invitations or enrollment emails were sent by authoring."
