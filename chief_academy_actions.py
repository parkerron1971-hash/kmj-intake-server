"""Owner-scoped, atomic Course Studio authoring shared by chat and voice tools."""
import hashlib
import json
import re
from uuid import UUID
import sb_clients

COURSE_AUTHORING_MAX_TOKENS = 16000
COURSE_READ_MAX_CHARS = 96000
COURSE_INCOMPLETE_REPLY = (
    "I couldn't finish this course-writing step, so that step was not saved. "
    "Any earlier saved lessons are still in Course Studio. "
    "Please ask me to build one lesson at a time to finish the course."
)


def is_course_tool(content):
    return any(isinstance(block, dict) and block.get('type') == 'tool_use'
               and block.get('name') in ('inspect_course', 'save_course_content', 'save_lesson_slides')
               for block in content)


def allow_course_output(payload, content):
    """Expand only after an actual Academy tool choice, not ordinary chat."""
    if is_course_tool(content) and payload.get('max_tokens', 0) < COURSE_AUTHORING_MAX_TOKENS:
        payload['max_tokens'] = COURSE_AUTHORING_MAX_TOKENS
        return True
    return False


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
READ_SCHEMA = ("Read this business's courses, or a course's complete lessons, materials, answer keys and edit revisions. Use before setting up the next lesson or changing existing work. For a focused edit, provide course_id and lesson_id to read that complete lesson. Large courses return a lesson index; read individual lessons by ID before editing.",
               obj({"course_id": TEXT, "lesson_id": TEXT}))
WRITE_SCHEMA = ("Save a complete course or append/update lessons in Course Studio. Creates real teaching content, downloadable workbook prompts, resources, written exercises, quizzes and live-class details atomically. New courses stay drafts. Does not publish, enroll or send anything. Existing published-course edits are immediately visible to students.",
                obj({"request_key": {**TEXT, "description": "Unique key for this requested save. Reuse exactly when retrying the same payload."},
                     "course_id": {**TEXT, "description": "Existing course ID; omit to create a new draft course."},
                     "title": TEXT, "description": TEXT,
                     "grading_mode": {"type": "string", "enum": ["completion", "percentage", "letter"], "description": "Creator's chosen assessment: completion pass/fail, percentage average, or A-F. Omit to preserve existing settings."},
                     "passing_grade": {"type": "integer", "minimum": 1, "maximum": 100},
                     "lessons": {"type": "array", "minItems": 0, "maxItems": 24, "items": LESSON, "description": "Complete lessons. Empty only when updating assessment settings on an existing course."}}, ["request_key", "lessons"]))


# ─── Slides ──────────────────────────────────────────────────────────
# One deck per lesson: what a teacher presents on the TV or online and what
# students review. The app builds a deck from the lesson text until someone
# saves one; the layouts and icons here are the app's (courseDeck.ts).
SLIDE_LAYOUTS = ["title", "quote", "point", "list", "tiles", "columns", "diagram",
                 "question", "memory", "chart", "picture", "closing"]
SLIDE_ICONS = ["shield-check", "user", "home", "zap", "target", "book-open", "heart", "users",
               "sparkles", "flame", "sun", "compass", "key", "crown", "star", "check", "clock",
               "calendar", "dollar-sign", "bar-chart", "lightbulb", "message-circle", "mountain",
               "sprout", "hand-heart", "globe", "anchor", "music", "gift", "cross"]
PICTURE_TEMPLATES = ["cover", "split", "frame", "duotone", "band"]
MAX_SLIDE_VERSES = 8
_SHORT = {"type": "string", "maxLength": 160}
_LINE = {"type": "string", "maxLength": 240}
SLIDE = obj({
    "id": {"type": "string", "maxLength": 64, "description": "Stable id; keep existing ids for slides you keep."},
    "layout": {"type": "string", "enum": SLIDE_LAYOUTS},
    "eyebrow": _SHORT, "title": _SHORT, "subtitle": _LINE, "body": {"type": "string", "maxLength": 600},
    "points": {"type": "array", "maxItems": 8, "items": _LINE},
    "tiles": {"type": "array", "maxItems": 6, "items": obj({"label": _SHORT, "text": _LINE, "ref": _SHORT,
                                                            "icon": {"type": "string", "enum": SLIDE_ICONS}}, ["label", "text"])},
    "columns": obj({"left_label": _SHORT, "right_label": _SHORT,
                    "rows": {"type": "array", "maxItems": 8, "items": obj({"left": _LINE, "right": _LINE}, ["left", "right"])}},
                   ["left_label", "right_label", "rows"]),
    "steps": {"type": "array", "minItems": 2, "maxItems": 5, "items": obj({"label": _SHORT, "ref": _SHORT, "note": _LINE}, ["label"])},
    "quote": obj({"text": {"type": "string", "maxLength": 900, "description": "Empty for scripture: the real verse text is filled in. Otherwise copied exactly from the lesson."},
                  "ref": _SHORT, "translation": {"type": "string", "maxLength": 12}, "highlight": _SHORT}, ["text", "ref"]),
    "chart": obj({"type": {"type": "string", "enum": ["bar", "donut"]}, "title": _SHORT,
                  "format": {"type": "string", "enum": ["money", "percent", "number"]},
                  "items": {"type": "array", "minItems": 2, "maxItems": 8,
                            "items": obj({"label": _SHORT, "value": {"type": "number"}}, ["label", "value"])}}, ["type", "items"]),
    "image": obj({"url": {"type": "string", "maxLength": 600}, "alt": _LINE}, ["url"]),
    "template": {"type": "string", "enum": PICTURE_TEMPLATES, "description": "How a picture sits on the slide."},
    "tone": {"type": "string", "enum": ["dark", "light", "accent"]},
    "notes": {"type": "string", "maxLength": 2000, "description": "The teacher's private notes; never shown to students or on the TV."},
}, ["id", "layout"])
SLIDES_WRITE_SCHEMA = (
    "Save one lesson's complete slide deck in Course Studio; it replaces that lesson's slides. Read the lesson with "
    "inspect_course first: lessons carry slides, slides_saved and slides_revision. The deck is what a teacher presents "
    "on the TV or online and what students review. Keep slide words short. Scripture: give quote.ref and leave quote.text "
    "empty so the real verse text is filled in, or copy the text exactly as the lesson quotes it. Chart numbers must come "
    "from the lesson. Pictures: only https links already in the lesson or the business's own storage; never invent one. "
    "notes are the teacher's private notes. Does not publish, present, enroll or send anything; on a published course "
    "students see the new slides.",
    obj({"course_id": TEXT, "lesson_id": TEXT,
         "slides_revision": {"type": "integer", "minimum": 1, "description": "slides_revision from inspect_course when slides_saved is true; omit when false."},
         "slides": {"type": "array", "minItems": 1, "maxItems": 60, "items": SLIDE}},
        ["course_id", "lesson_id", "slides"]))


def _plain(text):
    """Compare quoted words, not typography: quotes, dashes, case, spacing."""
    text = re.sub(r"[‘’'`´]", "'", str(text or ""))
    text = re.sub(r"[“”\"«»]", "", text)
    text = re.sub(r"[–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def scripture_passage(ref, tr="web"):
    """{'ref', 'text', 'translation'} for a reference, from the public-domain
    text the server ships, or None. Slides get up to MAX_SLIDE_VERSES verses."""
    import bible_text
    tr = bible_text.translation((tr or "web").lower())
    found = bible_text.find_refs(str(ref or ""), tr)
    if not found:
        return None
    target = found[0][2]
    if target.start is None:
        return None  # a whole chapter is a reading, not a slide
    verses = bible_text.verses(target, tr)
    if not verses or len(verses) > MAX_SLIDE_VERSES:
        return None
    words = " ".join(t for _, _, t in verses)
    words = re.sub(r"[\[\]¶]", "", words)  # KJV marks supplied words and paragraphs
    words = re.sub(r"\s+", " ", words).strip()
    return {"ref": target.label(), "text": words, "translation": bible_text.TRANSLATIONS[tr]["short"]}


_OWN_STORAGE = re.compile(r"^https://[a-z0-9]+\.supabase\.co/storage/v1/object/public/")


def clean_slides(slides, lesson_text):
    """Check a deck before it is saved. Scripture is never typed by the model:
    an empty quote is filled from the Bible text, any other quote must be the
    lesson's own words. Raises ValueError in words the creator can act on."""
    if not isinstance(slides, list) or not 1 <= len(slides) <= 60:
        raise ValueError("A deck needs between 1 and 60 slides.")
    lesson = _plain(lesson_text)
    lesson_numbers = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", str(lesson_text or ""))}
    seen, out = set(), []
    for n, raw in enumerate(slides, 1):
        if not isinstance(raw, dict) or raw.get("layout") not in SLIDE_LAYOUTS:
            raise ValueError(f"Slide {n} needs one of these layouts: {', '.join(SLIDE_LAYOUTS)}.")
        slide = {k: v for k, v in raw.items() if v not in (None, "", [], {})}
        sid = str(slide.get("id") or f"s{n}")[:64]
        while sid in seen:
            sid = f"{sid[:58]}-{n}"
        seen.add(sid)
        slide["id"] = sid
        slide.setdefault("source", "chief")
        quote = slide.get("quote")
        if slide["layout"] in ("quote", "memory") and not isinstance(quote, dict):
            raise ValueError(f"Slide {n} is a {slide['layout']} slide but has no quote.")
        if isinstance(quote, dict):
            text = str(quote.get("text") or "").strip()
            if not text:
                passage = scripture_passage(quote.get("ref"), quote.get("translation") or "web")
                if not passage:
                    raise ValueError(f"Slide {n}: I couldn't find {quote.get('ref') or 'that reference'} as a passage of up to "
                                     f"{MAX_SLIDE_VERSES} verses. Check the book, chapter and verses.")
                slide["quote"] = {**quote, **passage}
            elif _plain(text) not in lesson:
                raise ValueError(f"Slide {n}: quoted words must be copied exactly from the lesson. For scripture, leave "
                                 "quote.text empty and give the reference; the real verse text is filled in.")
        image = slide.get("image")
        if isinstance(image, dict):
            url = str(image.get("url") or "")
            if not url.startswith("https://") or not (_OWN_STORAGE.match(url) or url in str(lesson_text or "")):
                raise ValueError(f"Slide {n}: a picture must be one already in the lesson or the business's own storage. "
                                 "Leave it out and the creator can add one in Course Studio.")
        chart = slide.get("chart")
        if isinstance(chart, dict):
            for item in chart.get("items") or []:
                value = item.get("value")
                shown = f"{value:g}" if isinstance(value, (int, float)) else str(value)
                if shown not in lesson_numbers:
                    raise ValueError(f"Slide {n}: the chart value {shown} isn't in the lesson. Charts only show the lesson's own numbers.")
        out.append(slide)
    return out


async def handle_save_lesson_slides(client, biz, action):
    kind = "save_lesson_slides"
    try:
        cid = str(UUID(str(action.get("course_id"))))
        lid = str(UUID(str(action.get("lesson_id"))))
        data = await rpc(client, "academy_inspect", {"p_business": biz["id"], "p_course": cid})
        if not isinstance(data, dict):
            raise ValueError("Course records could not be loaded. Retry before saving slides.")
        lesson = next((row for row in data.get("lessons") or [] if row.get("id") == lid), None)
        if not lesson:
            raise ValueError("This lesson was not found in the selected course.")
        revision = action.get("slides_revision")
        if lesson.get("slides_saved") and revision is None:
            raise ValueError("This lesson's slides are already saved. Read them with inspect_course and pass "
                             "slides_revision, so newer edits aren't overwritten.")
        content = str(lesson.get("content") or "")
        slides = clean_slides(action.get("slides"), content)
        result = await rpc(client, "academy_save_deck", {
            "p_lesson": lid, "p_slides": slides,
            "p_source_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "p_revision": revision if lesson.get("slides_saved") else None})
        if not isinstance(result, dict) or result.get("lesson_id") != lid:
            raise ValueError("The slides were not saved. Check Course Studio availability and retry.")
        title = str(lesson.get("title") or "this lesson")
        detail = {"business_id": biz["id"], "course_id": cid, "lesson_id": lid, "part": "slides"}
        return {"type": kind, "result": "saved", "label": f"Saved {len(slides)} slides for {title}",
                "data": {**result, "slide_count": len(slides)}, "nav": {"tab": "build", "page": "course-studio"},
                "frontend_event": {"name": "solutionist-course-updated", "detail": detail}}
    except Exception as exc:
        return {"type": kind, "failed": True, "result": str(exc), "label": "The slides were not saved"}


async def rpc(client, path, body):
    # Never silently substitute service credentials for a creator's session.
    return await sb_clients.sb_as_current_context(client, "POST", "/rpc/" + path, body, allow_service_fallback=False)


async def handle_inspect_course(client, biz, action):
    try:
        cid = str(UUID(action["course_id"])) if action.get("course_id") else None
        lid = str(UUID(action["lesson_id"])) if action.get("lesson_id") else None
        if lid and not cid:
            raise ValueError("course_id is required when reading a specific lesson.")
        data = await rpc(client, "academy_inspect", {"p_business": biz["id"], "p_course": cid})
        if not isinstance(data, dict):
            raise ValueError("Course records could not be loaded. Retry before authoring.")
        if lid:
            lessons = [lesson for lesson in data.get("lessons", []) if lesson.get("id") == lid]
            if not lessons:
                raise ValueError("This lesson was not found in the selected course.")
            data = {**data, "lessons": lessons}
        return {"type": "inspect_course", "result": "Course records loaded", "label": "Course Studio", "data": data}
    except Exception as exc:
        return {"type": "inspect_course", "failed": True, "result": str(exc), "label": "Could not load course"}


def course_read_index(result):
    """Never give the model a cut-off lesson that it could overwrite as complete."""
    data = result.get("data") or {}
    lessons = data.get("lessons") or []
    if len(lessons) <= 1:
        return {"type": "inspect_course", "failed": True,
                "result": "This course record exceeds the reading limit. No complete lesson was loaded; do not edit from partial data. Open the lesson in Course Studio."}
    course = data.get("course") or {}
    return {"type": "inspect_course", "result": "Lesson index loaded; teaching content omitted for size.",
            "data": {"course": {key: course.get(key) for key in ("id", "title", "status", "grading_mode", "passing_grade")},
                     "lesson_count": len(lessons), "content_omitted": True,
                     "lessons": [{"id": lesson.get("id"), "title": str(lesson.get("title") or "")[:300]}
                                 for lesson in lessons[:200]]},
            "next_step": "Call inspect_course with course_id and the desired lesson_id to load its complete content and revision before editing. Never save from this index."}


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

PROMPT += " For focused lesson edits, inspect_course accepts both course_id and lesson_id. If an inspection returns content_omitted, use its lesson index to fetch the specific complete lesson; never retry the same oversized read or reconstruct missing content. Before saving, check the requested quiz question count and remove accidental placeholder questions."

PROMPT += (" SLIDES: every lesson has a slide deck the teacher presents on the TV or online and students review afterwards. "
           "inspect_course returns each lesson's saved slides (slides_saved, slides, slides_revision); when slides_saved is false the app "
           "builds the deck from the lesson text, so to make slides more visual save a complete deck with save_lesson_slides that follows "
           "the lesson's order: a title slide, quote slides for key scripture or quotes, point slides with up to four short lines, tiles "
           "for a list of 3-6 parallel ideas (each with an icon), columns for two-sided comparisons, a diagram for 2-5 steps that lead "
           "into each other, question slides for discussion questions, a memory slide for a memory verse, a list slide for homework, and "
           "chart slides only for numbers the lesson states. Put the lesson's teaching detail and any teacher notes in each slide's notes "
           "(teacher-only). Scripture text is never typed: give quote.ref and leave quote.text empty, or copy the lesson's quotation exactly. "
           "Never invent picture links; the creator adds pictures in Course Studio. Keep existing slide ids for slides you keep, pass "
           "slides_revision when slides were saved, and say what changed after the tool succeeds.")
