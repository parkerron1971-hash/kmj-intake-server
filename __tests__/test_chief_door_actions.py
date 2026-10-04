"""Chief opens the last doors (2026-10-04, Kevin: "yes i do want chief to do
these"): giving, the member app, publishing a course, publishing a sermon.
Pins: each holds to the screen it mirrors (giving and the member app owner
only; giving never without card payments; the member app never while a
sign-in code can't go out; a course only when Course Studio's checklist
passes; a sermon only with something to watch, hear or read), picks
exactly the thing named and asks when two match, writes courses and
sermons through the owner's own session, and forgets the page's door cache.
"""
import asyncio
import base64
import json
from unittest import mock

import action_registry
import chief_door_actions as cda
import chief_of_staff
import site_doors

OWNER = "owner-1"
BIZ = {"id": "b1", "owner_id": OWNER, "type": "church"}


def _jwt(sub):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


def _run(coro):
    return asyncio.run(coro)


# ─── who may switch money and member sign-in ────────────────────────

def test_only_the_owner_switches_giving_and_the_member_app():
    with mock.patch.object(cda.sb_clients, "get_current_user_jwt", return_value=_jwt("seat-7")):
        g = _run(cda.handle_set_giving(None, BIZ, {}))
        m = _run(cda.handle_set_member_app(None, BIZ, {}))
    assert g["failed"] and "Only the owner can switch giving" in g["result"]
    assert m["failed"] and "Only the owner can switch the member app" in m["result"]
    with mock.patch.object(cda.sb_clients, "get_current_user_jwt", return_value=None):
        assert _run(cda.handle_set_giving(None, BIZ, {}))["failed"]


# ─── giving ─────────────────────────────────────────────────────────

def _giving(row, **kw):
    seen = {}
    with mock.patch.object(cda.sb_clients, "get_current_user_jwt", return_value=_jwt(OWNER)), \
            mock.patch.object(cda, "_fresh_settings", return_value=row), \
            mock.patch.object(cda, "_site_origin", return_value="https://grace.org"), \
            mock.patch.object(cda.sb_clients, "sb_patch_as_service",
                              side_effect=lambda path, body: seen.update(body=body) or [body]), \
            mock.patch("payments_core.can_charge", return_value=kw.get("charge", True)):
        out = _run(cda.handle_set_giving(None, BIZ, kw.get("action", {})))
    return out, seen


def test_giving_needs_a_church_and_a_way_to_take_the_card():
    out, seen = _giving({"type": "consultant", "settings": {}, "stripe_account_id": "acct"})
    assert out["failed"] and "churches and nonprofits" in out["result"] and not seen
    out, seen = _giving({"type": "church", "settings": {}, "stripe_account_id": None})
    assert out["failed"] and "Connect Stripe" in out["result"] and not seen
    out, seen = _giving({"type": "church", "settings": {}, "stripe_account_id": "acct"}, charge=False)
    assert out["failed"] and not seen


def test_giving_goes_on_keeps_the_funds_and_forgets_the_door_cache():
    site_doors._LIVE_CACHE["b1"] = (0, [])
    row = {"type": "church", "stripe_account_id": "acct",
           "settings": {"giving": {"funds": ["Missions"]}, "brand_kit": {"x": 1}}}
    out, seen = _giving(row)
    assert seen["body"]["settings"]["giving"] == {"funds": ["Missions"], "enabled": True}
    assert seen["body"]["settings"]["brand_kit"] == {"x": 1}
    assert "b1" not in site_doors._LIVE_CACHE
    assert out["url"] == "https://grace.org/give" and "Giving is on" in out["result"]
    off, seen = _giving(row, action={"on": False})
    assert seen["body"]["settings"]["giving"]["enabled"] is False


# ─── the member app ─────────────────────────────────────────────────

def _member(row, deliver=True, eligible=True, action=None):
    seen = {}
    with mock.patch.object(cda.sb_clients, "get_current_user_jwt", return_value=_jwt(OWNER)), \
            mock.patch.object(cda, "_fresh_settings", return_value=row), \
            mock.patch.object(cda, "_site_origin", return_value="https://grace.org"), \
            mock.patch.object(cda, "sign_in_can_be_delivered", return_value=deliver), \
            mock.patch("member_portal.portal_eligible", return_value=eligible), \
            mock.patch.object(cda.sb_clients, "sb_patch_as_service",
                              side_effect=lambda path, body: seen.update(body=body) or [body]):
        out = _run(cda.handle_set_member_app(None, BIZ, action or {}))
    return out, seen


def test_the_member_app_waits_for_sign_in_codes_that_can_be_sent():
    out, seen = _member({"type": "church", "settings": {}}, deliver=False)
    assert out["failed"] and "neither can be sent" in out["result"] and not seen
    out, seen = _member({"type": "consultant", "settings": {}}, eligible=False)
    assert out["failed"] and not seen


def test_switching_the_member_app_on_starts_a_fresh_sign_in_epoch():
    out, seen = _member({"type": "church", "settings": {}})
    cfg = seen["body"]["settings"]["member_portal"]
    assert cfg["enabled"] is True and cfg["epoch"] > 0
    assert out["url"] == "https://grace.org/my"
    already = {"type": "church", "settings": {"member_portal": {"enabled": True, "epoch": 5}}}
    out, seen = _member(already)
    assert seen["body"]["settings"]["member_portal"]["epoch"] == 5, "already on: sessions kept"


def test_chief_pauses_and_resumes_member_sign_in_without_switching_the_app():
    row = {"type": "church", "settings": {"member_portal": {"enabled": True, "epoch": 5}}}
    out, seen = _member(row, action={"sign_in": False})
    assert seen["body"]["settings"]["member_portal"] == {"enabled": True, "epoch": 5, "sign_in": False}
    assert "paused" in out["result"] and not out.get("failed")
    out, seen = _member(row, action={"sign_in": True}, deliver=False)
    assert out["failed"] and not seen, "resuming waits for codes that can go out"
    off = {"type": "church", "settings": {"member_portal": {"enabled": False, "epoch": 5}}}
    out, seen = _member(off, action={"sign_in": False})
    assert seen["body"]["settings"]["member_portal"]["enabled"] is False, "pausing never opens the app"
    assert "still off" in out["result"]
    out, seen = _member({"type": "consultant", "settings": {}}, action={"sign_in": False}, eligible=False)
    assert out["failed"] and not seen


def test_turning_the_app_on_while_paused_says_sign_in_is_paused():
    out, _ = _member({"type": "church", "settings": {"member_portal": {"sign_in": False}}})
    assert "sign-in is paused" in out["result"]


# ─── courses ────────────────────────────────────────────────────────

COURSES = [{"id": "c1", "title": "Six-Week Reset", "description": "Find the next direction.",
            "status": "draft"},
           {"id": "c2", "title": "Reset for Teams", "description": "x", "status": "draft"}]
GOOD_LESSON = {"title": "Week 1", "content": "Start here.", "learning_design": {}}


def _course(action, lessons=(GOOD_LESSON,), courses=COURSES):
    writes = []

    async def _ctx(client, method, path, body=None, **kw):
        if method == "GET" and path.startswith("/academy_courses"):
            return list(courses)
        if method == "GET" and path.startswith("/academy_lessons"):
            return list(lessons)
        writes.append((method, path, body))
        return [body]
    with mock.patch.object(cda.sb_clients, "sb_as_current_context", side_effect=_ctx), \
            mock.patch.object(cda, "_site_origin", return_value="https://coach.org"):
        out = _run(cda.handle_publish_course(None, BIZ, action))
    return out, writes


def test_a_ready_course_is_published_through_the_owners_session():
    out, writes = _course({"course": "six-week reset"})
    assert writes == [("PATCH", "/academy_courses?id=eq.c1", {"status": "published"})]
    assert out["url"] == "https://coach.org/academy/c1" and "is published" in out["result"]


def test_two_matches_are_asked_about_and_a_missing_one_lists_the_courses():
    out, writes = _course({"course": "reset"})
    assert out["failed"] and "More than one course matches 'reset'" in out["result"] and not writes
    out, writes = _course({"course": "pottery"})
    assert out["failed"] and "'Six-Week Reset'" in out["result"] and not writes


def test_a_course_that_isnt_ready_stays_a_draft_with_the_reasons():
    empty = {"title": "Week 2", "content": "", "learning_design": {}}
    out, writes = _course({"course": "Six-Week Reset"}, lessons=(GOOD_LESSON, empty))
    assert out["failed"] and "Week 2: Add something for students to read, watch, or do." in out["result"]
    assert not writes
    out, writes = _course({"course": "Six-Week Reset"}, lessons=())
    assert "Add your first lesson." in out["result"]


def test_unpublishing_needs_no_checklist():
    out, writes = _course({"course": "Six-Week Reset", "published": False}, lessons=())
    assert writes == [("PATCH", "/academy_courses?id=eq.c1", {"status": "draft"})]


def test_the_lesson_checklist_matches_course_studio():
    assert cda.lesson_issues({"title": "", "content": "x"}) == ["Give this lesson a title."]
    assert cda.lesson_issues({"title": "A", "video_url": "youtube.com/x"}) == \
        ["Use a complete http or https link."]
    assert cda.lesson_issues({"title": "A", "learning_design": {"questions": [{"q": 1}]}}) == []
    assert cda.lesson_issues({"title": "A", "content": "x", "learning_design":
                              {"resources": [{"title": "", "url": "https://a.b"}]}}) == \
        ["Give every resource a name and link."]


# ─── sermons ────────────────────────────────────────────────────────

SERMONS = [{"id": "s2", "title": "Rest", "summary": "", "video_url": "", "audio_url": "",
            "published": False},
           {"id": "s1", "title": "Bread", "summary": "On manna.", "video_url": "",
            "audio_url": "", "published": False}]


def _sermon(action, sermons=SERMONS):
    writes = []

    async def _ctx(client, method, path, body=None, **kw):
        if method == "GET":
            return list(sermons)
        writes.append((method, path, body))
        return [body]
    with mock.patch.object(cda.sb_clients, "sb_as_current_context", side_effect=_ctx), \
            mock.patch.object(cda, "_site_origin", return_value="https://grace.org"):
        out = _run(cda.handle_publish_sermon(None, BIZ, action))
    return out, writes


def test_a_sermon_with_something_to_hear_or_read_is_published():
    out, writes = _sermon({"sermon": "Bread"})
    assert writes == [("PATCH", "/sermons?id=eq.s1", {"published": True})]
    assert out["url"] == "https://grace.org/sermons/s1"


def test_an_empty_sermon_stays_a_draft_and_latest_means_the_newest_draft():
    out, writes = _sermon({"sermon": "latest"})
    assert out["failed"] and "'Rest' isn't ready to publish" in out["result"] and not writes
    ready = [dict(SERMONS[0], audio_url="https://a.b/rest.mp3"), SERMONS[1]]
    out, writes = _sermon({}, sermons=ready)
    assert writes == [("PATCH", "/sermons?id=eq.s2", {"published": True})]


# ─── wired into Chief ───────────────────────────────────────────────

def test_the_four_verbs_are_registered_dispatched_and_taught():
    import chief_prompt
    src = open(chief_prompt.__file__, encoding="utf-8").read()
    for verb in ("set_giving", "set_member_app", "publish_course", "publish_sermon"):
        assert verb in action_registry.REGISTRY, verb
        assert verb in chief_of_staff.ACTION_HANDLERS, verb
        assert f'"type":"{verb}"' in src, verb
    assert all(d.chief_can_open for d in site_doors.DOORS)
