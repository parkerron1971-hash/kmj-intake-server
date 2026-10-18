"""Classes in the church member app (phase 5 of the approved "Class
Experience" design, "One deck, every room"; Kevin 2026-10-17: classes in the
member app, yes).

Connect gains Classes beside Groups (and Messages). GET /my/classes shows a
signed-in member:

  * the next class night of a class they're in, or the one live now, with
    the way into their classroom;
  * the road of each program they're on (The Making's four tracks): done,
    now, open to join, later, and the night it ends with;
  * their classes, and how far they've come in each;
  * the church's other classes they can join, one tap each.

Joining (POST /my/classes/join) is academy_public_join, the same step the
class page's form uses, with the member's own contact id from their
session: no email to type, no link to wait for. The owner hears about a new
student as from the class page, and the class link goes to the member's
email too when they have one.

One read, academy_member_classes (service-only;
APPLY-2026-10-18-academy-member-classes.sql). The Classes tab shows when the
church has a published class (classes_on, kept a minute) or in the owner's
preview, so a church without classes never shows an empty tab.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from starlette.background import BackgroundTask

import sb_clients

logger = logging.getLogger(__name__)
router = APIRouter(tags=["member-portal"])

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Whether this request's Connect pages carry the Classes tab (set by
# member_portal._serve_page, read by member_portal_church.connect_tabs).
TAB: contextvars.ContextVar[bool] = contextvars.ContextVar("member_classes_tab", default=False)

_ON_TTL = 60.0
_on_cache: Dict[str, Tuple[float, bool]] = {}


def classes_on(business_id: str) -> bool:
    """Does the church have a published class? Kept a minute; a failed read
    hides the tab for that page only (it isn't kept)."""
    now = time.monotonic()
    hit = _on_cache.get(business_id)
    if hit and hit[0] > now:
        return hit[1]
    rows = sb_clients.sb_get_as_service(
        f"/academy_courses?business_id=eq.{business_id}&status=eq.published&select=id&limit=1")
    if rows is None:
        return False
    on = bool(rows)
    _on_cache[business_id] = (now + _ON_TTL, on)
    return on


def classes_for(business_id: str, me: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """{'mine', 'programs', 'open', 'tz'}, or None when it couldn't be read
    (the page says "try again" rather than showing no classes)."""
    out = sb_clients.sb_post_as_service("/rpc/academy_member_classes",
                                        {"p_business": business_id, "p_contact": str(me["id"])})
    if not isinstance(out, dict) or not all(isinstance(out.get(k), list) for k in ("mine", "programs", "open")):
        return None
    try:
        from outside_calendar import business_timezone
        tz = business_timezone(business_id)
    except Exception:  # noqa: BLE001
        tz = "UTC"
    return {"mine": out["mine"], "programs": out["programs"], "open": out["open"], "tz": tz}


def class_link(token: Any) -> str:
    from academy_join import CLASSROOM_BASE
    return f"{CLASSROOM_BASE}/classroom/{token}"


# ─── Joining ──────────────────────────────────────────────────────────

def join_class(business_id: str, me: Dict[str, Any], course_id: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """(ok, flash code, what happened for the owner's notice and the email)."""
    import academy_join
    rows = sb_clients.sb_get_as_service(
        f"/academy_courses?id=eq.{course_id}&business_id=eq.{business_id}&limit=1"
        f"&select=id,business_id,title,status,self_join,product_id")
    if rows is None:
        return False, "error", None
    if not rows or not academy_join.join_open(rows[0]):
        return False, "class_closed", None
    course = rows[0]
    out = sb_clients.sb_post_as_service("/rpc/academy_public_join",
                                        {"p_course": course["id"], "p_contact": str(me["id"])}, redact=True)
    state = out.get("state") if isinstance(out, dict) else None
    if state == "joined":
        return True, "class_joined", {"course": course, "outcome": {**out, "contact_id": str(me["id"]),
                                                                     "known_as": me.get("name") or "A member"}}
    if state == "already":
        return True, "class_already", None
    if state == "dropped":
        return False, "class_dropped", {"course": course, "outcome": {**out, "contact_id": str(me["id"]),
                                                                       "known_as": me.get("name") or "A member"}}
    if state == "closed":
        return False, "class_closed", None
    return False, "error", None


async def after_join(course: Dict[str, Any], me: Dict[str, Any], outcome: Dict[str, Any]) -> None:
    """The class link to their email (when they have one), and the owner told.
    Never raises; the member already has the class on their page."""
    import academy_join
    email = str(me.get("email") or "").strip()
    if outcome.get("state") == "joined" and outcome.get("token") and academy_join.valid_email(email):
        try:
            await academy_join.send_class_link(course, me.get("name") or "", email, outcome, again=False)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[member-classes] class link email failed: {type(e).__name__}")
    try:
        await academy_join.tell_owner(course, outcome, came_from="app")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[member-classes] owner notice failed: {type(e).__name__}")


@router.post("/my/classes/join", include_in_schema=False)
async def join(request: Request):
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my/classes", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    form = await request.form()
    course_id = str(form.get("course_id") or "")
    if not _UUID.fullmatch(course_id):
        return mpc._back("/my/classes", err="class_closed")
    if not mpc._allowed(church, me):
        return mpc._back("/my/classes", err="slow")
    ok, code, ctx = await asyncio.to_thread(join_class, church["business"]["id"], me, course_id)
    resp = mpc._back("/my/classes", **({"done": code} if ok else {"err": code}))
    if ctx:
        resp.background = BackgroundTask(after_join, ctx["course"], me, ctx["outcome"])
    return resp


# ─── When ─────────────────────────────────────────────────────────────

def _at(iso: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _clock(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}{f':{dt.minute:02d}' if dt.minute else ''} {'AM' if dt.hour < 12 else 'PM'}"


def when_text(iso: Any, tz: str, now: Optional[datetime] = None) -> str:
    """'Tonight at 6 PM', 'Tomorrow at 6 PM', 'Thursday at 6 PM', 'Thu, Nov 19
    at 6 PM', in the church's own clock; '' when there's no time."""
    at = _at(iso)
    if at is None:
        return ""
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    local = at.astimezone(zone)
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    days = (local.date() - today).days
    clock = _clock(local)
    if days == 0:
        return f"{'Tonight' if local.hour >= 17 else 'Today'} at {clock}"
    if days == 1:
        return f"Tomorrow at {clock}"
    if 1 < days < 7:
        return f"{local.strftime('%A')} at {clock}"
    return f"{local.strftime('%a, %b')} {local.day} at {clock}"


def date_text(iso: Any, tz: str) -> str:
    """'Nov 19' (and the year when it isn't this one)."""
    at = _at(iso)
    if at is None:
        return ""
    from zoneinfo import ZoneInfo
    try:
        local = at.astimezone(ZoneInfo(tz or "UTC"))
    except Exception:  # noqa: BLE001
        local = at
    year = f", {local.year}" if local.year != datetime.now(timezone.utc).year else ""
    return f"{local.strftime('%b')} {local.day}{year}"


def short_title(title: str, program: Optional[str]) -> str:
    """'The Making: Foundation' on The Making's road reads 'Foundation'."""
    if program and title.lower().startswith(program.lower()):
        rest = title[len(program):].lstrip(" :·-–—")
        return rest or title
    return title


# ─── The page ─────────────────────────────────────────────────────────

def _join_form(course_id: str, label_id: str, text: str = "Join") -> str:
    from member_portal import _e
    return (f'<form method="post" action="/my/classes/join"><input type="hidden" name="course_id" value="{_e(course_id)}">'
            f'<button class="mp-go" type="submit" aria-describedby="{label_id}">{_e(text)}</button></form>')


def _next_card(c: Dict[str, Any], tz: str) -> str:
    import member_app_ui as ui
    from member_portal import _e
    n = c["next"]
    live = bool(n.get("live"))
    head = " · ".join(x for x in (n.get("title"), n.get("lesson")) if x) or c.get("title") or "Class"
    facts = " · ".join(_e(x) for x in (c.get("title"), c.get("teacher")) if x)
    when = ('<span class="mb-when is-live"><span class="mb-live-dot" aria-hidden="true"></span>Live now</span>' if live
            else f'<span class="mb-when">{ui.icon("calendar", 14)}{_e(when_text(n.get("starts_at"), tz))}</span>')
    go = (f'<a class="mp-go" href="{_e(class_link(c["token"]))}"><span class="mb-live-dot" aria-hidden="true"></span>Join the class now</a>'
          if live else f'<a class="mp-go" href="{_e(class_link(c["token"]))}">{ui.icon("book", 18)}Open the lesson</a>')
    return (f'<section class="mb-cnext{" is-live" if live else ""}" aria-labelledby="mb-cnext-h">{when}'
            f'<h2 id="mb-cnext-h">{_e(head)}</h2>{f"<p>{facts}</p>" if facts else ""}'
            f'<div class="mp-actions">{go}</div></section>')


_ROAD_STATE = {"done": "Done", "now": "You're here", "open": "Open to join", "later": "Coming later"}


def _road(p: Dict[str, Any], mine: Dict[str, Dict[str, Any]], tz: str) -> str:
    import member_app_ui as ui
    from member_portal import _e
    items = []
    for k, t in enumerate(p.get("tracks") or [], 1):
        state = t.get("state") if t.get("state") in _ROAD_STATE else "later"
        cid = str(t.get("course_id") or "")
        hid = f"mb-road-{_e(cid)}"
        name = short_title(str(t.get("title") or ""), p.get("title"))
        starts = date_text(t.get("starts_at"), tz)
        line = _ROAD_STATE[state]
        if state == "now" and cid in mine and mine[cid].get("total"):
            line = f"You're here · {mine[cid].get('done', 0)} of {mine[cid]['total']} lessons"
        elif state in ("open", "later") and starts:
            line = f"{line} · starts {starts}"
        if t.get("teacher"):
            line += f" · {t['teacher']}"
        mark = ui.icon("check", 16) if state == "done" else str(k)
        act = ""
        if state in ("done", "now") and t.get("token"):
            act = f'<a class="mp-go mp-go-2" href="{_e(class_link(t["token"]))}" aria-describedby="{hid}">Open</a>'
        elif state == "open":
            act = _join_form(cid, hid)
        items.append(f'<li data-state="{state}"><span class="mb-road-dot" aria-hidden="true">{mark}</span>'
                     f'<div class="mb-road-t"><b id="{hid}">{_e(name)}</b><span>{_e(line)}</span></div>'
                     f'<div class="mp-actions">{act}</div></li>')
    if p.get("finish_title"):
        when = date_text(p.get("finish_at"), tz)
        items.append(f'<li data-state="finish"><span class="mb-road-dot" aria-hidden="true">{ui.icon("star", 16)}</span>'
                     f'<div class="mb-road-t"><b>{_e(p["finish_title"])}</b><span>{_e(when or "At the end of the road")}</span></div></li>')
    return f'<ol class="mb-road" aria-label="{_e(p.get("title") or "Your next steps")}">{"".join(items)}</ol>'


def _mine_row(c: Dict[str, Any]) -> str:
    from member_portal import _e
    hid = f"mb-cls-{_e(c.get('course_id'))}"
    total, done = int(c.get("total") or 0), int(c.get("done") or 0)
    pct = round(100 * done / total) if total else 0
    kick = c.get("program") or ""
    if kick and c.get("position") is not None:
        kick = f"{kick} · Track {int(c['position']) + 1}"
    status = ("Finished" + (" · certificate earned" if c.get("certificate") else "")
              if c.get("status") == "completed" else f"{done} of {total} lessons" if total else "Just started")
    bar = ("" if c.get("status") == "completed" or not total else
           f'<span class="mb-cls-bar" role="progressbar" aria-label="Lessons done" aria-valuemin="0" aria-valuemax="{total}" '
           f'aria-valuenow="{done}"><i style="width:{pct}%"></i></span>')
    kicker = f'<span class="mb-kick">{_e(kick)}</span>' if kick else ""
    return (f'<li class="mb-cls"><div class="mb-cls-t">{kicker}'
            f'<b id="{hid}">{_e(c.get("title") or "")}</b><span>{_e(status)}</span>{bar}</div>'
            f'<a class="mp-go mp-go-2" href="{_e(class_link(c["token"]))}" aria-describedby="{hid}">Open</a></li>')


def _open_card(c: Dict[str, Any], tz: str) -> str:
    import member_app_ui as ui
    from member_portal import _e
    hid = f"mb-copen-{_e(c.get('course_id'))}"
    kick = c.get("program") or "Class"
    if c.get("program") and c.get("position") is not None:
        kick = f"{kick} · Track {int(c['position']) + 1}"
    starts = when_text(c.get("starts_at"), tz) if c.get("starts_at") else ""
    if not starts and c.get("drip") in ("weekly", "custom") and c.get("opens_from"):
        starts = f"Starts {date_text(c.get('opens_from'), tz)}"
    soon_word = starts.split(" ")[0] in ("Tonight", "Today", "Tomorrow")
    when = (f"First class {starts[0].lower() + starts[1:] if soon_word else starts}" if starts and not starts.startswith("Starts")
            else starts) or "Start any time"
    facts = " · ".join(x for x in (when, f"{c['lessons']} lessons" if c.get("lessons") else "", c.get("teacher")) if x)
    about = f'<p>{_e(c["about"])}</p>' if c.get("about") else ""
    sample = ui.sample_tag() if c.get("sample") else ""
    return (f'<article class="mb-copen" aria-labelledby="{hid}"><span class="mb-kick">{_e(kick)}</span>'
            f'<h3 id="{hid}">{_e(c.get("title") or "")}{sample}</h3><span class="mb-copen-f">{_e(facts)}</span>{about}'
            f'<div class="mp-actions">{_join_form(str(c.get("course_id") or ""), hid, "Join this class")}</div></article>')


def render_classes(biz, site, request: Request, data: Optional[Dict[str, Any]], who=None) -> str:
    """Connect › Classes: the next class night, the road, your classes,
    classes to join."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    if data is None:
        body = '<p class="mp-err" role="alert">Classes couldn\'t load just now. Please try again in a moment.</p>'
    elif not data["mine"] and not data["open"] and not data["programs"]:
        church = _e(biz.get("name") or "the church")
        body = (f'<section class="mb-cempty">{ui.icon("book", 28)}<h2>No classes to join right now</h2>'
                f'<p>When {church} opens a class, it shows up here and you can join it with one tap.</p></section>')
    else:
        tz = data.get("tz") or "UTC"
        mine = data["mine"]
        by_id = {str(c.get("course_id")): c for c in mine}
        nxt = next((c for c in mine if c.get("status") == "active" and c.get("next") and c.get("token")), None)
        parts = []
        if any(samples.is_sample(x) for x in mine + data["open"]):
            parts.append(ui.sample_hint(samples.WHERE["classes"]))
        if nxt:
            parts.append(_next_card(nxt, tz))
        for p in data["programs"]:
            hid = f"mb-prog-{_e(p.get('id'))}"
            parts.append(f'<section aria-labelledby="{hid}">{ui.section(p.get("title") or "Your next steps", hid=hid)}'
                         f'{_road(p, by_id, tz)}</section>')
        if mine:
            rows = "".join(_mine_row(c) for c in mine if c.get("token"))
            parts.append(f'<section aria-labelledby="mb-mine-h">{ui.section("Your classes", hid="mb-mine-h")}'
                         f'<ul class="mb-clist">{rows}</ul></section>')
        if data["open"]:
            cards = "".join(_open_card(c, tz) for c in data["open"])
            parts.append(f'<section aria-labelledby="mb-copen-h">{ui.section("Classes you can join", hid="mb-copen-h")}'
                         f'{cards}<p class="mp-muted mb-cfoot">Joining puts the class here, '
                         f'and your teacher sees you on the list.</p></section>')
        body = "".join(parts)
    return _shell(biz, site, "Classes", f"""
<div class="mb-lt"><h1>Connect</h1></div>
{mpc.connect_tabs(biz, "classes")}
{mpc._flash(request)}
{body}""", tab="connect", who=who)
