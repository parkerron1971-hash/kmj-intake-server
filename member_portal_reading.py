"""
member_portal_reading.py — the church's reading plan on a member's page.

    Home            a "Today's reading" card (only while a plan is running)
    GET  /my/reading   the plan: today, the days read, the ones to catch up
    POST /my/reading   tick a day read (or un-tick it)

The plan itself, its days and the ticks live in reading_plans.py. A
member only ever ticks their own days, today's or earlier; the owner's
preview reads and never writes.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import reading_plans as rp

router = APIRouter(tags=["member-portal"])

DONE = {"read": "Marked as read. Well done.", "unread": "Unmarked."}
ERRORS = {"error": "That didn't save. Please try again.",
          "day": "That day can't be marked yet.",
          "preview": "This is a preview. Nothing is saved for the member.",
          "slow": "That's a lot at once. Please wait a minute."}


def _flash(request: Request) -> str:
    from member_portal import _e
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def _tick_form(day: int, read: bool, label: str, back: str) -> str:
    return (f'<form method="post" action="/my/reading" style="display:inline">'
            f'<input type="hidden" name="day" value="{day}"><input type="hidden" name="read" value="{"no" if read else "yes"}">'
            f'<input type="hidden" name="back" value="{back}">'
            f'<button class="mp-go{" mp-go-2" if read else ""}" type="submit">{label}</button></form>')


def home_card(today: Optional[Dict[str, Any]], done: Optional[set]) -> str:
    """Home's card. Nothing at all when no plan is running."""
    import member_app_ui as ui
    from member_portal import _e
    if not today:
        return ""
    read = bool(done) and today["day"] in done
    buttons = f'<a class="mp-go" href="{_e(today["href"])}">{ui.icon("doc", 16)}Read it</a>'
    if read:
        buttons += f'<span class="mb-chip">{ui.icon("check", 12)}Read today</span>'
    else:
        buttons += _tick_form(today["day"], False, "Mark as read", "/my")
    return f"""
<h2 class="mp-sect">Reading plan <a href="/my/reading">See the plan</a></h2>
<section class="mb-plan mb-reading" aria-labelledby="mb-reading-h">
  {ui.ring(today['day'], today['of'])}
  <div class="mb-plan-b"><span class="mp-muted" style="font-size:12.5px">{_e(today['title'])} · Today's reading · Day {today['day']} of {today['of']}</span>
  <strong id="mb-reading-h">{_e(today['label'])}</strong>
  <div class="mb-plan-acts">{buttons}</div></div>
</section>"""


def render_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                done: Optional[set], today: Optional[date] = None) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    plan = rp.current(biz)
    back = f'<a class="mb-back" href="/my">{ui.icon("back", 16)}Home</a>'
    if not plan:
        return _shell(biz, site, "Reading plan", back + """
<h1>Reading plan</h1>
<div class="mp-card"><p class="mp-muted">The church hasn't started a reading plan. You can always read in the Bible tab.</p>
<a class="mp-go" href="/my/bible">Open the Bible</a></div>""", tab="home", who=me)
    today = today or date.today()
    upto = rp.readable_upto(plan, today)
    days = rp.schedule(plan["key"])
    if done is None:
        body = '<p class="mp-err" role="alert">Your progress couldn\'t load just now. Please try again in a moment.</p>'
    elif upto == 0:
        body = (f'<div class="mp-card"><p>It starts {_e(plan["start"].strftime("%A, %B"))} {plan["start"].day}.</p>'
                f'<p class="mp-muted">Day 1: {_e(rp.label(days[0]))}</p></div>')
    else:
        n_today = rp.day_number(plan, today)
        streak = rp.streak(done, n_today) if n_today else 0
        missed = [d for d in range(1, upto + (0 if n_today else 1)) if d not in done][-14:]
        rows = []
        for d in range(upto, max(0, upto - 7), -1):
            when = plan["start"] + timedelta(days=d - 1)
            read = d in done
            rows.append(
                f'<li><span><strong>Day {d}</strong> · {_e(when.strftime("%a"))} {when.day} · '
                f'<a href="{_e(rp.href(days[d - 1]))}">{_e(rp.label(days[d - 1]))}</a></span>'
                f'{_tick_form(d, read, "Read ✓" if read else "Mark as read", "/my/reading")}</li>')
        catch = ""
        if missed and n_today:
            catch = (f'<details class="mb-each"><summary>{len(missed)} '
                     f'{"day" if len(missed) == 1 else "days"} to catch up</summary><ul class="mp-gifts">'
                     + "".join(f'<li><span>Day {d} · <a href="{_e(rp.href(days[d - 1]))}">{_e(rp.label(days[d - 1]))}</a></span>'
                               f'{_tick_form(d, False, "Mark as read", "/my/reading")}</li>' for d in missed)
                     + '</ul></details>')
        body = (f'<div class="mp-card"><p class="mp-total">{len(done)} <span class="mp-muted">of {plan["days"]} days read</span></p>'
                + (f'<p class="mp-muted">{streak} {"day" if streak == 1 else "days"} in a row.</p>' if streak > 1 else '')
                + f'<ul class="mp-gifts">{"".join(rows)}</ul>{catch}</div>')
    return _shell(biz, site, "Reading plan", f"""{back}
<h1>{_e(plan['title'])}</h1>
<p class="mp-muted">{_e(rp.PLANS[plan['key']]['about'])} Started {_e(plan['start'].strftime('%B'))} {plan['start'].day}.</p>
{_flash(request)}
{body}""", tab="home", who=me)


@router.post("/my/reading", include_in_schema=False)
async def tick(request: Request):
    import asyncio
    import member_portal_church as mpc
    from member_portal import _SECURE_HEADERS
    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    back = "/my" if str(form.get("back") or "") == "/my" else "/my/reading"

    def go(**q: str) -> RedirectResponse:
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return RedirectResponse(back + (f"?{qs}" if qs else ""), status_code=303, headers=_SECURE_HEADERS)
    if unavailable:
        return go(err="preview" if unavailable == "preview" else "error")
    if not me:
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    plan = rp.current(church["business"])
    try:
        day = int(str(form.get("day") or ""))
    except ValueError:
        return go(err="day")
    if not plan or not (1 <= day <= rp.readable_upto(plan)):
        return go(err="day")
    if not mpc._allowed(church, me):
        return go(err="slow")
    read = str(form.get("read") or "yes") == "yes"
    ok = await asyncio.to_thread(rp.mark, church["business"]["id"], me["id"], plan, day, read)
    return go(**({"done": "read" if read else "unread"} if ok else {"err": "error"}))
