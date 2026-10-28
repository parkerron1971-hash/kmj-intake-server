"""
member_portal_checkin.py — Sunday check-in on the member's own page.

The code on the welcome slide opens the church's /here, which lands on
/my/here: the member (signed in, or after the usual passwordless sign-in,
which brings them to Home where the same card waits) says "At church" or
"Watching online" and ticks who of their family came; one tap counts
them all (church_checkin.check_in). While check-in is open the card sits
at the top of Home too. Canvas 31su6kdYmYecH5b2NxjBJN, boards 10 and 11.

  GET  /my/here        the card (through member_portal.serve)
  POST /my/here        {where: in|online, people: [contact ids], back}

The owner's preview reads but never writes; a member can only ever count
themselves and the adults of their own family.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import church_checkin as cc

router = APIRouter(tags=["member-portal"])

CHECKIN_CSS = """
.ck{background:var(--s1);border-radius:var(--r-lg);padding:18px 16px 16px;margin:4px 0 18px;display:flex;flex-direction:column;gap:14px;
  box-shadow:inset 0 0 0 1px var(--mb-soft-line);}
.ck-k{margin:0;font-size:11.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
.ck-h{margin:2px 0 0;font-size:28px;font-weight:750;letter-spacing:-.03em;line-height:1.08;}
.ck-h em{font-family:var(--mb-serif);font-style:italic;font-weight:500;color:var(--acc);}
.ck form{display:flex;flex-direction:column;gap:14px;margin:0;}
.ck fieldset{border:0;margin:0;padding:0;min-width:0;}
.ck legend{font-size:13px;font-weight:600;color:var(--fg2);padding:0;margin-bottom:8px;}
.ck-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;}
.ck-where{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.ck-where label{position:relative;display:block;}
.ck-where input,.ck-p input{position:absolute;opacity:0;width:1px;height:1px;}
.ck-where span{display:flex;flex-direction:column;gap:2px;min-height:64px;padding:11px 12px;border-radius:14px;background:var(--s2);
  box-sizing:border-box;cursor:pointer;}
.ck-where b{font-size:15px;font-weight:650;color:var(--fg);}
.ck-where small{font-size:12px;color:var(--fg3);}
.ck-where input:checked + span{background:var(--mb-fill);}
.ck-where input:checked + span b,.ck-where input:checked + span small{color:var(--mb-on-fill);}
.ck-where input:focus-visible + span,.ck-p input:focus-visible ~ .ck-box{outline:2px solid var(--acc);outline-offset:2px;}
.ck-fam{display:flex;flex-direction:column;gap:6px;}
.ck-p{position:relative;display:flex;align-items:center;gap:12px;min-height:52px;padding:0 12px;border-radius:12px;background:var(--s2);cursor:pointer;}
.ck-av{width:34px;height:34px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--s3);font-size:12px;font-weight:700;}
.ck-n{display:flex;flex-direction:column;min-width:0;flex:1;}
.ck-n b{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ck-n small{font-size:12px;color:var(--fg3);}
.ck-box{width:24px;height:24px;border-radius:7px;flex:none;box-sizing:border-box;border:1.5px solid var(--line);display:grid;place-items:center;color:transparent;}
.ck-p input:checked ~ .ck-box{background:#5fd08a;border-color:#5fd08a;color:#08130c;}
.ck-go{display:flex;align-items:center;justify-content:center;gap:8px;min-height:54px;border:0;border-radius:999px;background:var(--mb-fill);
  color:var(--mb-on-fill);font:inherit;font-weight:650;font-size:16.5px;width:100%;cursor:pointer;}
.ck-done{flex-direction:row;align-items:center;gap:14px;background:rgba(95,208,138,.10);box-shadow:none;}
.ck-tick{width:44px;height:44px;border-radius:50%;flex:none;display:grid;place-items:center;background:#5fd08a;color:#08130c;}
.ck-done .t{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1;}
.ck-done b{font-family:var(--mb-serif);font-size:22px;font-weight:500;letter-spacing:-.01em;}
.ck-done .t > span{font-size:14px;color:var(--fg2);}
.ck-change{font-size:13.5px;font-weight:600;color:var(--acc);white-space:nowrap;min-height:44px;display:inline-flex;align-items:center;}
.ck-msg{margin:0;font-size:15px;color:var(--fg2);line-height:1.5;}
.ck-err{margin:0;font-size:14px;color:var(--error);}
.ck-note{margin:0;font-size:12.5px;color:var(--fg3);}
"""

ERRS = {
    "closed": "Check-in has closed for today. See you next time.",
    "pick": "Tick at least one person.",
    "preview": "This is a preview, so nothing was saved.",
    "slow": "One moment — try that again.",
    "error": "That didn’t save. Please try again in a moment.",
}


def _e(s: Any) -> str:
    from member_portal import _e as esc
    return esc(s)


def _names(names: List[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or name


def _kicker(c: Dict[str, Any]) -> str:
    w = c["w"]
    return f'{_e(c["occasion"]["title"])} · {_e(cc.clock(w["start"]))}'


def _done(c: Dict[str, Any], back: str) -> str:
    import member_app_ui as ui
    fam, got = c["family"], c["marks"]
    here = [p for p in fam if p["id"] in got]
    online = all(got[p["id"]].get("method") == "online" for p in here)
    who = _names([("You" if p["me"] and len(here) == 1 else _first(p["name"])) for p in here])
    verb = "are" if len(here) != 1 or (here and here[0]["me"]) else "is"
    line = (f"{who} {verb} counted as watching online." if online
            else f"{who} {verb} checked in for {c['occasion']['title']}.")
    href = "/my/here?change=1" if back == "/my/here" else "/my/here?change=1&from=home"
    return (f'<section class="ck ck-done" role="status" aria-live="polite">'
            f'<span class="ck-tick" aria-hidden="true">{ui.icon("check", 24)}</span>'
            f'<span class="t"><b>{"Glad you’re with us." if online else "Welcome home."}</b><span>{_e(line)}</span></span>'
            f'<a class="ck-change" href="{href}">Change it</a></section>')


def _form(c: Dict[str, Any], back: str, err: str = "") -> str:
    import member_app_ui as ui
    fam, got = c["family"], c["marks"]
    changing = bool(got)
    online = changing and all(r.get("method") == "online" for r in got.values())
    people = []
    for p in fam:
        row = got.get(p["id"])
        on = (p["id"] in got) if changing else True
        if row and row.get("method") not in cc.MINE:
            sub = "Checked in already"
        else:
            sub = "You" if p["me"] else "Your family"
        people.append(
            f'<label class="ck-p"><input type="checkbox" name="people" value="{_e(p["id"])}"{" checked" if on else ""}>'
            f'<span class="ck-av" aria-hidden="true">{_e(ui.initials(p["name"]))}</span>'
            f'<span class="ck-n"><b>{_e(p["name"])}</b><small>{_e(sub)}</small></span>'
            f'<span class="ck-box" aria-hidden="true">{ui.icon("check", 15)}</span></label>')
    fam_html = (f'<fieldset class="ck-fam"><legend>Who’s with you</legend>{"".join(people)}</fieldset>'
                if len(fam) > 1 else f'<input type="hidden" name="people" value="{_e(fam[0]["id"])}">')
    hello = _first(next((p["name"] for p in fam if p["me"]), "")) or "friend"
    hour = c["w"]["start"].hour
    greet = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    return f"""<section class="ck" aria-labelledby="ck-h">
<p class="ck-k">{_kicker(c)}</p>
<h2 class="ck-h" id="ck-h">{greet}, <em>{_e(hello)}</em>. Are you with us today?</h2>
{f'<p class="ck-err" role="alert">{_e(err)}</p>' if err else ''}
<form method="post" action="/my/here">
<input type="hidden" name="back" value="{_e(back)}">
<fieldset class="ck-where"><legend class="ck-sr">Where are you</legend>
<label><input type="radio" name="where" value="in"{'' if online else ' checked'}><span><b>At church</b><small>In the building</small></span></label>
<label><input type="radio" name="where" value="online"{' checked' if online else ''}><span><b>Watching online</b><small>From home or away</small></span></label>
</fieldset>
{fam_html}
<button class="ck-go" type="submit">{'Save' if changing else 'Check in'}</button>
</form>
</section>"""


def home_card(c: Dict[str, Any], request: Request) -> str:
    """Home's card while check-in is open; nothing otherwise."""
    if c.get("state") != "open":
        return ""
    err = ERRS.get(str(request.query_params.get("ck") or ""), "")
    body = _done(c, "/my") if c["marks"] and not err else _form(c, "/my", err)
    return f"<style>{CHECKIN_CSS}</style>{body}"


def render_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], c: Dict[str, Any]) -> str:
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "your church"
    err = ERRS.get(str(request.query_params.get("ck") or ""), "")
    state = c.get("state")
    if state == "open":
        changing = str(request.query_params.get("change") or "") == "1"
        back = "/my" if str(request.query_params.get("from") or "") == "home" else "/my/here"
        inner = (_done(c, back) if c["marks"] and not changing and not err else _form(c, back, err))
        inner += ('<p class="ck-note">Only ' + _e(church) + ' sees who came. You can change it any time '
                  'until check-in closes.</p>')
    elif state == "closed":
        w = c["w"]
        when = (f"today at {cc.clock(w['opens'])}" if w["opens"].date() == cc._now().astimezone(w["opens"].tzinfo).date()
                else f"{w['weekday']} at {cc.clock(w['opens'])}")
        said = f'<p class="ck-err" role="alert">{_e(err)}</p>' if err else ""
        inner = (f'<section class="ck"><p class="ck-k">Check-in</p><h2 class="ck-h">Check-in opens <em>{_e(when)}</em>.</h2>'
                 f'<p class="ck-msg">Come back then, or just open your page: the card will be waiting at the top of Home.</p>'
                 f'{said}</section>')
    elif state == "off":
        inner = (f'<section class="ck"><p class="ck-k">Check-in</p><h2 class="ck-h">Check-in isn’t on at {_e(church)} yet.</h2>'
                 f'<p class="ck-msg">Welcome! You don’t need to do anything.</p></section>')
    else:
        inner = ('<section class="ck"><h2 class="ck-h">Check-in couldn’t load just now.</h2>'
                 '<p class="ck-msg">Please try again in a moment.</p></section>')
    return _shell(biz, site, "Check in", f'<style>{CHECKIN_CSS}</style><a class="mb-back" href="/my">Home</a>{inner}',
                  tab="home", who=me)


def _go(back: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    target = back if back in ("/my", "/my/here") else "/my/here"
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


@router.post("/my/here", include_in_schema=False)
async def check_in(request: Request):
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    form = await request.form()
    back = str(form.get("back") or "/my/here")
    if unavailable:
        return _go(back, ck="preview" if unavailable == "preview" else "error")
    if not me:
        return _go("/my")
    import rate_limit
    biz = church["business"]
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return _go(back, ck="slow")
    c = await asyncio.to_thread(cc.card, biz, me)
    if c.get("state") == "closed" or c.get("state") == "off":
        return _go(back, ck="closed")
    if c.get("state") != "open":
        return _go(back, ck="error")
    chosen = [str(v) for v in form.getlist("people")]
    where = "online" if str(form.get("where") or "") == "online" else "in"
    try:
        await asyncio.to_thread(cc.check_in, str(biz["id"]), c["occasion"]["id"], c["family"], chosen, where)
    except HTTPException as e:
        return _go(back, ck="pick" if e.status_code == 400 else "error")
    return _go(back, done="here")
