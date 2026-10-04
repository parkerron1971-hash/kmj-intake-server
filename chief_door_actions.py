"""THE LAST DOORS, FROM THE CHAT (2026-10-04).

Kevin: "yes i do want chief to do these" — switching giving on, publishing a
course, publishing a sermon, switching the member app on. site_doors.py
listed them as doors only the owner could open; these are Chief's verbs for
them. Each holds to the same rule as the screen it mirrors, so Chief can
never open a door the app itself would refuse:

  set_giving      giving_router PATCH: ministries and nonprofits only, and
                  (new here) never live without a way to take the card.
                  Owner only, as in the app.
  set_member_app  member_portal PATCH: churches and nonprofits only; turning
                  it on starts a fresh sign-in epoch. Refused while members
                  could not receive a sign-in code. "sign_in" pauses or
                  resumes new sign-ins, the panel's own switch. Owner only.
  publish_course  Course Studio's Publish: the same checklist (a description,
                  at least one lesson, each lesson with a title and something
                  to read, watch or do, links complete). Through the owner's
                  own session (RLS), never the service key, like every other
                  course write.
  publish_sermon  Sermons: a sermon with a title and something to watch,
                  listen to or read. The owner's session, like the panel.

Each names exactly what it opened and where it now lives. The page links a
newly opened door on its own (site_doors.wire_html, cached two minutes).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients
from chief_host import _fail, _nav

logger = logging.getLogger("chief_door_actions")


def _on(action: Dict[str, Any], key: str) -> bool:
    v = action.get(key)
    return True if v is None else bool(v)


def _caller_id() -> str:
    """The signed-in caller's user id, from the session Chief runs under."""
    jwt = sb_clients.get_current_user_jwt() or ""
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get("sub") or "")
    except Exception:
        return ""


def _owner_only(biz: Dict[str, Any], kind: str, what: str) -> Optional[Dict[str, Any]]:
    owner = str(biz.get("owner_id") or "")
    if not owner or _caller_id() != owner:
        return _fail(kind, f"Only the owner can switch {what} on or off.")
    return None


def _fresh_settings(business_id: str) -> Optional[Dict[str, Any]]:
    """Settings read right before the write, so a change made meanwhile is
    never undone by a whole-object write from an older copy."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{quote(str(business_id), safe='')}"
        "&select=type,settings,stripe_account_id&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def _site_origin(business_id: str) -> str:
    import site_doors
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=slug,custom_domain:site_config->>custom_domain&limit=1") or []
    return site_doors.site_origin(rows[0] if rows else {})


def _forget_doors(business_id: str) -> None:
    """The page's door cache should see this change on the next visit."""
    try:
        import site_doors
        site_doors._LIVE_CACHE.pop(str(business_id), None)
    except Exception:
        pass


# ─── giving ──────────────────────────────────────────────────────────

def _set_giving_sync(biz: Dict[str, Any], on: bool) -> Dict[str, Any]:
    import payments_core
    import vertical_family
    from giving_router import giving_settings
    row = _fresh_settings(biz["id"])
    if row is None:
        return _fail("set_giving", "That change didn't save. Please try again.")
    if not vertical_family.is_nonprofit_like(row.get("type")):
        return _fail("set_giving", "Giving is for churches and nonprofits.")
    if on and not (row.get("stripe_account_id") and payments_core.can_charge(row)):
        return _fail("set_giving",
                     "Card payments aren't connected yet, so a give page couldn't take a "
                     "gift. Connect Stripe in Settings → Payments, then ask me again.")
    settings = dict(row.get("settings") or {})
    cfg = dict(giving_settings(settings))
    cfg["enabled"] = on
    settings["giving"] = cfg
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    _forget_doors(biz["id"])
    url = _site_origin(biz["id"]) + "/give"
    return {"type": "set_giving",
            "result": (f"Giving is on. People can give at {url}, and the site links it."
                       if on else "Giving is off. The give page and its link are gone."),
            "label": "💝 Giving on" if on else "💝 Giving off",
            "url": url, "nav": _nav("operate")}


async def handle_set_giving(client, biz, action) -> Dict[str, Any]:
    """Switch giving on (or "on": false to switch it off)."""
    refused = _owner_only(biz, "set_giving", "giving")
    if refused:
        return refused
    return await asyncio.to_thread(_set_giving_sync, biz, _on(action, "on"))


# ─── the member app ──────────────────────────────────────────────────

def sign_in_can_be_delivered() -> bool:
    """A member signs in with a code sent by email or text: the page is no
    use while neither can go out."""
    from member_portal import codes_can_go_out
    return codes_can_go_out()


_PAUSED_NOTE = (" Member sign-in is paused right now, so no one new can sign in until "
                "you switch it back on.")


def _set_member_app_sync(biz: Dict[str, Any], on: Optional[bool],
                         sign_in: Optional[bool] = None) -> Dict[str, Any]:
    """`on` switches the app (None leaves it); `sign_in` pauses or resumes
    new sign-ins (member_portal.sign_in_open; None leaves it)."""
    from member_portal import portal_eligible, portal_settings
    row = _fresh_settings(biz["id"])
    if row is None:
        return _fail("set_member_app", "That change didn't save. Please try again.")
    if (on or sign_in is not None) and not portal_eligible({**biz, **row}):
        return _fail("set_member_app", "The member app is for churches and nonprofits.")
    if (on or sign_in) and not sign_in_can_be_delivered():
        return _fail("set_member_app",
                     "Members sign in with a code by email or text, and neither can be sent "
                     "yet, so no one could get in. Email or text sending has to be set up first.")
    settings = dict(row.get("settings") or {})
    cfg = dict(portal_settings(settings))
    was_on = bool(cfg.get("enabled"))
    if on is not None:
        cfg["enabled"] = on
    if on and not was_on:
        # the app's own rule: switching on starts a fresh sign-in epoch, so
        # old sessions never come back to life
        cfg["epoch"] = int(time.time())
    if sign_in is not None:
        cfg["sign_in"] = sign_in
    settings["member_portal"] = cfg
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz['id']}", {"settings": settings})
    _forget_doors(biz["id"])
    url = _site_origin(biz["id"]) + "/my"
    paused = cfg.get("sign_in") is False
    if on is None:
        app_off = "" if cfg.get("enabled") else " The member app itself is still off."
        return {"type": "set_member_app",
                "result": ((f"Member sign-in is back on at {url}: members get a 6-digit code "
                            "by email or text." if sign_in else
                            "Member sign-in is paused: no codes go out and no one new can sign "
                            "in. Anyone already signed in stays in.") + app_off),
                "label": "📱 Member sign-in on" if sign_in else "📱 Member sign-in paused",
                "url": url, "nav": _nav("operate")}
    return {"type": "set_member_app",
            "result": ((f"The member app is on at {url}. Members sign in with the email or "
                        "mobile number the church has for them." + (_PAUSED_NOTE if paused else ""))
                       if on else "The member app is off. Everyone signed in is signed out."),
            "label": "📱 Member app on" if on else "📱 Member app off",
            "url": url, "nav": _nav("operate")}


async def handle_set_member_app(client, biz, action) -> Dict[str, Any]:
    """Switch the member app on (or "on": false to switch it off); "sign_in":
    false pauses new member sign-ins without switching the app off, true
    resumes them."""
    refused = _owner_only(biz, "set_member_app", "the member app")
    if refused:
        return refused
    sign_in = action.get("sign_in")
    sign_in = sign_in if isinstance(sign_in, bool) else None
    on = None if (sign_in is not None and "on" not in action) else _on(action, "on")
    return await asyncio.to_thread(_set_member_app_sync, biz, on, sign_in)


# ─── courses ─────────────────────────────────────────────────────────

_SAFE_URL = re.compile(r"^https?://[^\s]+\.[^\s]+$", re.IGNORECASE)


def lesson_issues(lesson: Dict[str, Any]) -> List[str]:
    """Course Studio's per-lesson checklist (courseLearning.ts lessonIssues),
    the parts that decide whether a student has anything to do."""
    d = lesson.get("learning_design") if isinstance(lesson.get("learning_design"), dict) else {}
    workbook = d.get("workbook") if isinstance(d.get("workbook"), dict) else {}
    session = d.get("session") if isinstance(d.get("session"), dict) else {}
    resources = [r for r in (d.get("resources") or []) if isinstance(r, dict)]
    title = str(lesson.get("title") or "").strip()
    issues = []
    if not title:
        issues.append("Give this lesson a title.")
    if not (str(lesson.get("content") or "").strip() or lesson.get("video_url")
            or str(workbook.get("title") or "").strip() or (d.get("questions") or [])
            or session.get("url")):
        issues.append("Add something for students to read, watch, or do.")
    for url in [lesson.get("video_url"), lesson.get("resource_url"), session.get("url"),
                *[r.get("url") for r in resources]]:
        if url and not _SAFE_URL.match(str(url).strip()):
            issues.append("Use a complete http or https link.")
            break
    if any(not str(r.get("title") or "").strip() or not str(r.get("url") or "").strip()
           for r in resources):
        issues.append("Give every resource a name and link.")
    return issues


def course_readiness(course: Dict[str, Any], lessons: List[Dict[str, Any]]) -> List[str]:
    out = []
    for lesson in lessons:
        for issue in lesson_issues(lesson):
            out.append(f"{str(lesson.get('title') or 'A lesson').strip()}: {issue}")
    if not lessons:
        out.append("Add your first lesson.")
    if not str(course.get("description") or "").strip():
        out.append("Tell students what this course helps them achieve.")
    return out


def _pick(rows: List[Dict[str, Any]], wanted: str, label: str, kind: str,
          title_key: str = "title") -> Any:
    """The one row the owner means, or a _fail naming the choices."""
    w = " ".join(str(wanted or "").lower().split())
    exact = [r for r in rows if " ".join(str(r.get(title_key) or "").lower().split()) == w]
    near = exact or [r for r in rows if w and w in str(r.get(title_key) or "").lower()]
    if len(near) == 1:
        return near[0]
    names = ", ".join(f"'{r.get(title_key)}'" for r in (near or rows)[:6])
    if not rows:
        return _fail(kind, f"There are no {label}s yet.")
    if not near:
        return _fail(kind, f"I couldn't find a {label} called '{wanted}'. On file: {names}.")
    return _fail(kind, f"More than one {label} matches '{wanted}': {names}. Which one?")


async def handle_publish_course(client, biz, action) -> Dict[str, Any]:
    """Publish a course by title or id ("published": false unpublishes it)."""
    kind = "publish_course"
    publish = _on(action, "published")
    wanted = str(action.get("course") or action.get("title") or action.get("course_id") or "").strip()
    rows = await sb_clients.sb_as_current_context(
        client, "GET", f"/academy_courses?business_id=eq.{biz['id']}"
        "&select=id,title,description,status&order=updated_at.desc&limit=50")
    if rows is None:
        return _fail(kind, "I couldn't read your courses just now. Try again.")
    course = next((r for r in rows if str(r.get("id")) == wanted), None) \
        or _pick(rows, wanted, "course", kind)
    if course.get("failed"):
        return course
    if publish:
        lessons = await sb_clients.sb_as_current_context(
            client, "GET", f"/academy_lessons?course_id=eq.{course['id']}"
            "&select=title,content,video_url,resource_url,learning_design&limit=200")
        if lessons is None:
            return _fail(kind, "I couldn't read that course's lessons just now. Try again.")
        issues = course_readiness(course, lessons)
        if issues:
            return _fail(kind, f"'{course['title']}' isn't ready to publish yet, so I left it "
                               "as a draft: " + " ".join(issues[:4]))
    saved = await sb_clients.sb_as_current_context(
        client, "PATCH", f"/academy_courses?id=eq.{course['id']}",
        {"status": "published" if publish else "draft"})
    if not saved:
        return _fail(kind, "That change didn't save. Please try again.")
    _forget_doors(biz["id"])
    url = (await asyncio.to_thread(_site_origin, biz["id"])) + f"/academy/{course['id']}"
    return {"type": kind,
            "result": (f"'{course['title']}' is published at {url}. The site's Courses link "
                       "opens your courses." if publish
                       else f"'{course['title']}' is back to a draft; students can't open it."),
            "label": f"🎓 Published {course['title']}" if publish else f"🎓 Unpublished {course['title']}",
            "url": url, "nav": {"tab": "build", "page": "course-studio"},
            "frontend_event": {"name": "solutionist-course-updated",
                               "detail": {"business_id": biz["id"], "course_id": course["id"]}}}


# ─── sermons ─────────────────────────────────────────────────────────

def sermon_issues(sermon: Dict[str, Any]) -> List[str]:
    issues = []
    if not str(sermon.get("title") or "").strip():
        issues.append("Give it a title.")
    if not (sermon.get("video_url") or sermon.get("audio_url")
            or str(sermon.get("summary") or "").strip()):
        issues.append("Add a video, an audio link, or a summary so people have something to "
                      "watch, hear, or read.")
    return issues


async def handle_publish_sermon(client, biz, action) -> Dict[str, Any]:
    """Publish a sermon by title, or the latest draft ("published": false
    unpublishes it)."""
    kind = "publish_sermon"
    publish = _on(action, "published")
    wanted = str(action.get("sermon") or action.get("title") or "").strip()
    rows = await sb_clients.sb_as_current_context(
        client, "GET", f"/sermons?business_id=eq.{biz['id']}"
        "&select=id,title,summary,video_url,audio_url,published,preached_on"
        "&order=preached_on.desc,created_at.desc&limit=100")
    if rows is None:
        return _fail(kind, "I couldn't read your sermons just now. Try again.")
    if not wanted or wanted.lower() in ("latest", "the latest", "newest", "last"):
        pool = [r for r in rows if bool(r.get("published")) != publish]
        if not pool:
            return _fail(kind, "There is no sermon to " + ("publish" if publish else "unpublish") + ".")
        sermon = pool[0]
    else:
        sermon = _pick(rows, wanted, "sermon", kind)
        if sermon.get("failed"):
            return sermon
    if publish:
        issues = sermon_issues(sermon)
        if issues:
            return _fail(kind, f"'{sermon.get('title') or 'That sermon'}' isn't ready to publish "
                               "yet, so it stays a draft: " + " ".join(issues))
    saved = await sb_clients.sb_as_current_context(
        client, "PATCH", f"/sermons?id=eq.{sermon['id']}", {"published": publish})
    if not saved:
        return _fail(kind, "That change didn't save. Please try again.")
    _forget_doors(biz["id"])
    url = (await asyncio.to_thread(_site_origin, biz["id"])) + f"/sermons/{sermon['id']}"
    return {"type": kind,
            "result": (f"'{sermon['title']}' is published at {url}, and the site's Sermons "
                       "link opens your sermons." if publish
                       else f"'{sermon['title']}' is back to a draft."),
            "label": f"🎙 Published {sermon['title']}" if publish else f"🎙 Unpublished {sermon['title']}",
            "url": url, "nav": {"tab": "operate"}}
