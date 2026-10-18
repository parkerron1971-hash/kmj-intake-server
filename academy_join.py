"""Free classes people join themselves (phase 4b of "One deck, every room").

A published class with no product to buy, whose owner has not closed it
(academy_courses.self_join), shows a join form on its public page
(public_site._serve_academy) in place of "Get in touch". The form posts
here, to the class page's own address plus /join:

  POST /academy/<course_id>/join   on a business site's /academy pages
  POST /course/<course_id>/join    on a standalone academy address

The person's class link goes to the address they typed and nowhere else.
The page that answers says only "check your email", in the same words
whether they were new, already in, or once taken off the class: anyone
can type anyone's address, so showing the link, or the name on it, would
hand a stranger someone else's classroom.

What happens, in order: flood control per network; the class must be
open (public.academy_course_open, said again here as join_open for the
page); the per-address cooldown and daily ceiling; the contact found or
made by lead_identity's one rule; then ONE database step,
public.academy_public_join, which enrolls them or hands back the
enrollment they have. The email and the owner's notice go out after the
page has answered (a failure there never asks the person to try again).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)
router = APIRouter()

# Where a student's classroom lives (the same address Course Studio copies).
CLASSROOM_BASE = "https://system.mysolutionist.app"
_EMAIL_RE = re.compile(r"^[^@\s<>\"',;()]+@[^@\s<>\"',;()]+\.[^@\s<>\"',;()]{2,}$")
_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}


def join_open(course: Dict[str, Any]) -> bool:
    """public.academy_course_open, for the page that shows the form."""
    return (course.get("status") == "published" and course.get("self_join") is not False
            and not course.get("product_id"))


def clean_name(raw: Any) -> str:
    return " ".join(str(raw or "").split())[:120]


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(_EMAIL_RE.match(email))


def _digest(email: str) -> str:
    # The shared rate window is a table: keep addresses out of it.
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]


# ─── The form, on the class page and on the answers below ───────────

JOIN_CSS = """
  .join { align-items: center; }
  .join-copy { flex: 1 1 180px; }
  .join-fields { flex: 2 1 380px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .join-fields label { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; font-weight: 600; }
  .join-fields input {
    font: inherit; font-size: 15px; font-weight: 400; padding: 11px 13px; border-radius: 10px; min-width: 0;
    border: 1px solid color-mix(in srgb, currentColor 26%, transparent); background: transparent; color: inherit;
  }
  .join-fields .btn { grid-column: 1 / -1; border: 0; cursor: pointer; font-family: inherit; }
  .join-err { grid-column: 1 / -1; font-size: 13.5px; font-weight: 600; color: #b42318; margin: 0; }
  .join-hp { position: absolute; left: -10000px; width: 1px; height: 1px; overflow: hidden; }
  .next-live { margin-top: 10px; font-size: 14px; font-weight: 600; }
  .answer { max-width: 560px; }
  .answer p { font-size: 15.5px; margin-top: 12px; }
  @media (prefers-color-scheme: dark) { .join-err { color: #fda29b; } }
  @media (max-width: 560px) { .join-fields { grid-template-columns: 1fr; } .join .btn { width: 100%; } }
"""


def join_box(action: str, accent: str, *, name: str = "", email: str = "", error: str = "") -> str:
    from public_site import _esc
    err = f'<p class="join-err" role="alert">{_esc(error)}</p>' if error else ""
    return f"""
  <form class="price-box join" method="post" action="{_esc(action)}">
    <div class="join-copy">
      <div class="price">Free</div>
      <div class="muted" style="font-size:12.5px">Join, and your class link comes to your email.</div>
    </div>
    <div class="join-fields">
      {err}
      <label>Your name<input name="name" required maxlength="120" autocomplete="name" value="{_esc(name)}"></label>
      <label>Email<input name="email" type="email" required maxlength="254" autocomplete="email" value="{_esc(email)}"></label>
      <label class="join-hp" aria-hidden="true">Leave this empty<input name="website" tabindex="-1" autocomplete="off"></label>
      <button class="btn" type="submit" style="background:{_esc(accent)}">Join the class</button>
    </div>
  </form>"""


# ─── When the class next meets ───────────────────────────────────────

def _clock(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    mins = f":{dt.minute:02d}" if dt.minute else ""
    return f"{dt.strftime('%A, %B')} {dt.day} at {hour}{mins} {'AM' if dt.hour < 12 else 'PM'}"


def next_class_line(business_id: str, course_id: str) -> str:
    """'Thursday, October 23 at 7 PM' for the next live class, or ''.
    Sync (worker thread); quiet on any failure."""
    try:
        import sb_clients
        from zoneinfo import ZoneInfo
        from outside_calendar import business_timezone
        since = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = sb_clients.sb_get_as_service(
            f"/academy_live_sessions?course_id=eq.{course_id}&status=in.(scheduled,live)"
            f"&starts_at=gte.{since}&order=starts_at.asc&limit=1&select=starts_at") or []
        if not rows:
            return ""
        at = datetime.fromisoformat(str(rows[0]["starts_at"]).replace("Z", "+00:00"))
        return _clock(at.astimezone(ZoneInfo(business_timezone(business_id))))
    except Exception as e:
        logger.info(f"[class-join] next class time skipped: {type(e).__name__}")
        return ""


def release_note(business_id: str, course: Dict[str, Any]) -> str:
    """The class page's one line on how lessons open: all at once, one a
    week from the day you join, or together from the class's start date
    (academy_courses.opens_from, in the zone it was set in, else the
    business's). Sync (worker thread)."""
    drip = course.get("drip_mode") or "none"
    if drip not in ("weekly", "custom"):
        return "Everything is available the moment you join."
    try:
        start = datetime.fromisoformat(str(course.get("opens_from") or "").replace("Z", "+00:00"))
    except ValueError:
        start = None
    if start is None:
        return ("New material unlocks each week after you join." if drip == "weekly"
                else "Material unlocks on a guided schedule after you join.")
    try:
        from zoneinfo import ZoneInfo
        zone = course.get("opens_tz")
        if not zone:
            from outside_calendar import business_timezone
            zone = business_timezone(business_id)
        local = start.astimezone(ZoneInfo(zone))
    except Exception as e:
        logger.info(f"[class-join] time zone skipped: {type(e).__name__}")
        local = start
    pace = "One lesson a week, together" if drip == "weekly" else "Lessons open together on the class’s own schedule"
    if start > datetime.now(timezone.utc):
        return f"{pace}, from {_clock(local)}."
    return (f"{pace}, since {local.strftime('%A, %B')} {local.day}. "
            "Join now and the weeks so far are open to catch up.")


# ─── The answers ─────────────────────────────────────────────────────

async def _look(business_id: str) -> Tuple[str, str, str]:
    """(business name, accent, head html) in the academy pages' own look."""
    import httpx
    import public_site as ps
    async with httpx.AsyncClient() as client:
        name, accent, theme, site_config = await ps._academy_brand(client, business_id)
    accent, skin_head = ps._academy_skin(business_id, site_config, theme, accent)
    head = (f"<style>{ps._ACADEMY_CSS}{JOIN_CSS}</style>{skin_head}"
            f"<style>{ps._academy_mode_css(theme)}</style>")
    return name, accent, head


def _page(look: Tuple[str, str, str], course_title: str, heading: str, inner: str, back: str,
          status: int = 200, background: Optional[BackgroundTask] = None) -> HTMLResponse:
    from public_site import _esc
    biz, accent, head = look
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>{_esc(heading)} &mdash; {_esc(biz)}</title>
{head}</head>
<body><div class="wrap answer">
  <a class="back" style="color:{accent}" href="{_esc(back)}">&larr; {_esc(course_title or "Back to the class")}</a>
  <div style="height:26px"></div>
  <div class="eyebrow" style="color:{accent}">{_esc(biz)}</div>
  <h1>{_esc(heading)}</h1>
  {inner}
  <div class="foot muted">Powered by The Solutionist System</div>
</div></body></html>"""
    return HTMLResponse(content=html, status_code=status, headers=_NO_STORE, background=background)


def _sent(look, course, email: str, back: str, background=None) -> HTMLResponse:
    from public_site import _esc
    return _page(look, course["title"], "Check your email", f"""
  <p>Your class link is on its way to <b>{_esc(email)}</b>. Open it on any phone or computer and it takes you straight into {_esc(course["title"])}.</p>
  <p class="muted">It comes from {_esc(look[0])}. Nothing after a few minutes? Look in spam or promotions, or <a style="color:{look[1]}" href="{_esc(back)}">try again</a>.</p>""",
                 back, background=background)


def _closed(look, course, back: str) -> HTMLResponse:
    from public_site import _esc
    return _page(look, course["title"], "Sign-ups are closed here", f"""
  <p>{_esc(course["title"])} isn&rsquo;t taking sign-ups from its page. Get in touch with {_esc(look[0])} and they&rsquo;ll add you.</p>""",
                 back)


def _again(look, course, back: str, action: str, name: str, email: str, error: str, status: int) -> HTMLResponse:
    return _page(look, course["title"], f"Join {course['title']}",
                 join_box(action, look[1], name=name, email=email, error=error), back, status)


async def _missing() -> HTMLResponse:
    return HTMLResponse(content="<!DOCTYPE html><title>Not found</title><p>That class isn&rsquo;t here.</p>",
                        status_code=404, headers=_NO_STORE)


# ─── The routes ──────────────────────────────────────────────────────

@router.post("/academy/{course_id}/join", include_in_schema=False)
async def join_from_site(course_id: str, request: Request):
    return await join(request, course_id, f"/academy/{course_id}")


@router.post("/course/{course_id}/join", include_in_schema=False)
async def join_from_academy(course_id: str, request: Request):
    return await join(request, course_id, f"/course/{course_id}")


async def join(request: Request, course_id: str, back: str) -> HTMLResponse:
    import public_site as ps
    import rate_limit
    if not ps._academy_valid_id(course_id):
        return await _missing()
    action = back + "/join"
    if not rate_limit.allow_strict("class_join_ip", rate_limit.trusted_client_ip(request)):
        return HTMLResponse(
            content="<!DOCTYPE html><title>Give it a few minutes</title><p>Lots of sign-ups from this network "
                    "just now. Wait a few minutes, then try again.</p>", status_code=429, headers=_NO_STORE)
    form = await request.form()
    name = clean_name(form.get("name"))
    email = str(form.get("email") or "").strip().lower()
    rows = await asyncio.to_thread(_course, course_id)
    if not rows:
        return await _missing()
    course = rows[0]
    look = await _look(course["business_id"])
    if not join_open(course):
        return _closed(look, course, back)
    if str(form.get("website") or "").strip():
        return _sent(look, course, email, back)  # a bot filled the hidden field: nothing done
    if not name or not valid_email(email):
        return _again(look, course, back, action, name, email[:254],
                      "Enter your name and the email your class link should go to.", 400)
    key = f"{course['business_id']}|{_digest(email)}"
    if not rate_limit.allow_strict("class_join_email_minute", key) or \
            not rate_limit.allow_strict("class_join_email_day", key):
        from public_site import _esc
        return _page(look, course["title"], "Check your email", f"""
  <p>A class link was just sent to <b>{_esc(email)}</b>. Give it a minute, and look in spam or promotions too.</p>""",
                     back, 429)
    outcome = await asyncio.to_thread(enroll, course, name, email)
    if outcome is None:
        return _again(look, course, back, action, name, email,
                      "That didn’t go through just now. Nothing was saved; try again in a moment.", 503)
    if outcome.get("state") == "closed":
        return _closed(look, course, back)
    return _sent(look, course, email, back,
                 background=BackgroundTask(after_join, course, name, email, outcome))


def _course(course_id: str):
    import sb_clients
    return sb_clients.sb_get_as_service(
        f"/academy_courses?id=eq.{course_id}&limit=1"
        f"&select=id,business_id,title,status,self_join,product_id") or []


def enroll(course: Dict[str, Any], name: str, email: str) -> Optional[Dict[str, Any]]:
    """The contact (found or made), then the one database step. None when
    either could not be confirmed; nothing half-made is reported as made."""
    import lead_identity
    import sb_clients
    biz = str(course["business_id"])
    try:
        found = lead_identity.find(biz, email=email, name=name, select="id,name", strict=True)
    except Exception as e:
        logger.warning(f"[class-join] contact lookup failed biz={biz[:8]}: {type(e).__name__}")
        return None
    if found:
        contact_id, known_as = str(found["id"]), (found.get("name") or name)
    else:
        made = sb_clients.sb_post_as_service("/contacts", {
            "business_id": biz, "name": name, "email": email, "status": "lead",
            "source": "class_signup", "source_detail": f"Joined {course.get('title') or 'a class'}"[:200],
        }, redact=True)
        if not isinstance(made, list) or not made or not made[0].get("id"):
            logger.warning(f"[class-join] contact create failed biz={biz[:8]}")
            return None
        contact_id, known_as = str(made[0]["id"]), name
    out = sb_clients.sb_post_as_service("/rpc/academy_public_join",
                                        {"p_course": course["id"], "p_contact": contact_id}, redact=True)
    if not isinstance(out, dict) or out.get("state") not in ("joined", "already", "dropped", "closed"):
        logger.warning(f"[class-join] join step failed biz={biz[:8]}")
        return None
    return {**out, "contact_id": contact_id, "known_as": known_as}


# ─── After the page has answered ─────────────────────────────────────

async def after_join(course: Dict[str, Any], name: str, email: str, outcome: Dict[str, Any]) -> None:
    state = outcome.get("state")
    biz = str(course["business_id"])
    if state in ("joined", "already") and outcome.get("token"):
        try:
            await send_class_link(course, name, email, outcome, again=state == "already")
        except Exception as e:
            logger.warning(f"[class-join] class link email failed biz={biz[:8]}: {type(e).__name__}: {e}")
    if state in ("joined", "dropped"):
        try:
            await tell_owner(course, outcome)
        except Exception as e:
            logger.warning(f"[class-join] owner notice failed biz={biz[:8]}: {type(e).__name__}")


def class_link_email(biz_name: str, course_title: str, first: str, link: str,
                     when_line: str, again: bool) -> Tuple[str, str, str]:
    """(subject, message, preheader). Plain words; the button carries the link."""
    lead = (f"Here’s your way back into {course_title}." if again
            else f"You’re in {course_title} with {biz_name}.")
    when = f" The next class is {when_line}." if when_line else ""
    message = (f"Hi {first},\n\n" if first else "Hi,\n\n") + lead + when + (
        "\n\nKeep this email. The button below opens your class on any phone or computer, any time.")
    subject = f"Your link to {course_title}" if again else f"You’re in: {course_title}"
    return subject, message, lead


# Under the button and the signature, small: the one line for a stranger.
NOT_YOU = "If you didn’t sign up for this class, you can ignore this email."


async def send_class_link(course: Dict[str, Any], name: str, email: str,
                          outcome: Dict[str, Any], *, again: bool) -> None:
    import email_layout
    import email_sender
    import sb_clients
    biz = str(course["business_id"])
    rows = await asyncio.to_thread(sb_clients.sb_get_as_service,
                                   f"/businesses?id=eq.{biz}&select=name,settings&limit=1")
    row = (rows or [{}])[0]
    settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
    biz_name = (row.get("name") or "").strip() or "Your class"
    when_line = await asyncio.to_thread(next_class_line, biz, str(course["id"]))
    link = f"{CLASSROOM_BASE}/classroom/{outcome['token']}"
    subject, message, preheader = class_link_email(
        biz_name, course.get("title") or "your class", name.split(" ")[0], link, when_line, again)
    html = email_layout.render_html(
        message, business_name=biz_name, brand=email_layout.brand_of(settings),
        sig=email_layout.signature_of(settings), unsubscribe_url=email_sender._unsubscribe_url(email),
        preheader=preheader, cta=("Open your class", link), disclaimer=NOT_YOU)
    reply_to = None
    try:
        reply_to = email_sender.build_routed_reply_to(biz, outcome.get("contact_id"))
    except Exception:
        reply_to = None
    await email_sender.send_via_resend(
        to_email=email, to_name=name or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=biz_name, subject=subject, body=html, reply_to=reply_to, business_id=biz,
        idempotency_key=f"class-link-{outcome.get('enrollment_id')}-{int(time.time() // 60)}")


async def tell_owner(course: Dict[str, Any], outcome: Dict[str, Any]) -> None:
    import httpx
    from notification_engine import create_urgent_alert
    who = outcome.get("known_as") or "Someone"
    title = course.get("title") or "a class"
    enrollment = str(outcome.get("enrollment_id") or "")
    payload = {"type": "navigate", "tab": "build", "sub": "course-studio"}
    async with httpx.AsyncClient() as client:
        if outcome.get("state") == "joined":
            await create_urgent_alert(
                client, str(course["business_id"]), f"{who} joined {title}",
                "They signed up on the class page, and their class link went to their email.",
                notification_id=str(uuid.uuid5(uuid.UUID(enrollment), "class-joined")),
                priority="normal", suggested_action="Open Classes", action_payload=payload,
                related_contact_id=outcome.get("contact_id"))
        else:
            await create_urgent_alert(
                client, str(course["business_id"]), f"{who} asked to join {title} again",
                "You took them off this class earlier, so no link was sent. "
                "If they should be in, add them back from the class's Students.",
                dedup_key=f"class-rejoin:{enrollment}", dedup_hours=24,
                priority="normal", suggested_action="Open Classes", action_payload=payload,
                related_contact_id=outcome.get("contact_id"))
