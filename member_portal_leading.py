"""member_portal_leading.py — a Sunday team's leader schedules their team, in
the member app's Lead tab (ChurchSavvy Planning, step 7; Kevin, 2026-10-23:
"TEAM LEADERS schedule their own team"; canvas Ct88v7pxpq5a4PGYX3MuQQ,
board 4's leader view: "Marcus leads Production, so he sees and fills
Production. He still sees who on his team is serving on another team that
hour, so he never double-books them").

    GET  /my/lead/sundays[?team=&day=&spot=<place>:<slot>]   one Sunday at a time
    POST /my/lead/sundays/ask        {team, day, place, slot, person}
    POST /my/lead/sundays/offer      {team, day, place, slot}   to the whole team
    POST /my/lead/sundays/takeback   {team, day, id}            an ask nobody said yes to
    POST /my/lead/sundays/fill       {team}                     the next five Sundays, fairly
    POST /my/lead/sundays/unfill     {team, ids}                that fill, before it goes out

The logic is sunday_leading.py (their team only, every write checked); the
office's own page is Operate → Sunday → Who serves when. The owner's preview
reads and never writes. A phone shows one Sunday at a time, as the office
does on a phone (there is no phone board for this on the canvas).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import sunday_leading as sl

logger = logging.getLogger("member_portal_leading")
router = APIRouter(tags=["member-portal"])

_ID = re.compile(r"^[0-9a-fA-F-]{36}$")
_SPOT = re.compile(r"^([0-9a-fA-F-]{36}):(\d{1,2})$")

LEADING_CSS = """
.sl-team{margin:0 0 4px;font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--h-ink);}
.sl-h{margin:0;font-size:26px;font-weight:720;letter-spacing:-.03em;line-height:1.1;}
.sl-sub{margin:6px 0 0;font-size:14.5px;color:var(--fg2);line-height:1.4;}
.sl-days{display:flex;gap:8px;overflow-x:auto;padding:14px 0 4px;margin:0 -2px;scrollbar-width:none;}
.sl-days a{flex:none;display:flex;flex-direction:column;align-items:center;gap:2px;min-width:62px;padding:8px 10px;border-radius:14px;
  background:var(--s1);color:var(--fg2);text-decoration:none;font-size:12px;font-weight:600;}
.sl-days a b{font-size:18px;font-weight:720;color:var(--fg);letter-spacing:-.02em;}
.sl-days a[aria-current]{background:var(--h);color:var(--on-h);}
.sl-days a[aria-current] b{color:var(--on-h);}
.sl-days a small{font-size:11px;font-weight:600;}
.sl-acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:14px;}
.sl-acts form{margin:0;}
.sl-filled{margin-top:14px;border-radius:var(--r-lg);background:var(--teal-deep);padding:14px 16px;display:flex;flex-direction:column;gap:10px;}
.sl-filled b{font-size:15px;}
.sl-filled span{font-size:13.5px;color:var(--fg2);line-height:1.4;}
.sl-filled form{margin:0;}
.sl-who{display:flex;flex-direction:column;}
.sl-who .c{display:flex;align-items:center;gap:10px;padding:8px 0;font-size:14px;}
.sl-who .c + .c{border-top:.5px solid var(--line);}
.sl-who .c .t{flex:1;min-width:0;display:flex;flex-direction:column;}
.sl-who .c small{font-size:12.5px;color:var(--fg2);}
.sl-who .c.dim{opacity:.55;}
.sl-who form{margin:0;}
"""


def _e(s: Any) -> str:
    from member_portal import _e as esc
    return esc(s)


def _first(name: Any) -> str:
    return (str(name or "").strip().split(" ")[0]) or "Someone"


def _initials(name: Any) -> str:
    import member_app_ui as ui
    return ui.initials(str(name or ""))


def _day_of(s: Dict[str, Any]) -> datetime:
    return datetime.fromisoformat(s["day"])


def _label(s: Dict[str, Any]) -> str:
    d = _day_of(s)
    return f'{d.strftime("%b")} {d.day}'


def _url(team: str, day: str = "", spot: str = "", **q: str) -> str:
    qs = urlencode({k: v for k, v in {"team": team, "day": day, "spot": spot, **q}.items() if v})
    return "/my/lead/sundays" + (f"?{qs}" if qs else "")


DONE = {"asked": "Asked. It goes out on the next sweep, and you can still take it back until then.",
        "offered": "Offered to the whole team. The first yes takes it.",
        "back": "Taken back.", "unfilled": "Taken back. Nothing went out."}


def _flash(request: Request) -> str:
    q = request.query_params
    if q.get("err") == "said":
        return f'<p class="mp-err mp-flash" role="alert">{_e(str(q.get("msg") or "")[:200])}</p>'
    if q.get("err"):
        return ('<p class="mp-err mp-flash" role="alert">'
                + ("This is a preview, so nothing was saved." if q.get("err") == "preview" else "That didn't save. Please try again.")
                + "</p>")
    done = DONE.get(str(q.get("done") or ""))
    return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else ""


# ─── the page ────────────────────────────────────────────────────────


def _state(a: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not a:
        return {"k": "open", "words": "Nobody yet"}
    if a["status"] == "offered":
        return {"k": "team", "words": "Offered to the team"}
    if a["status"] == "no":
        return {"k": "no", "words": f'{_first(a.get("name"))} can\'t' + (f' · {a["note"]}' if a.get("note") else "")}
    if a["status"] == "yes":
        return {"k": "yes", "words": f'{a.get("name") or "Someone"} said yes'}
    return {"k": "wait", "words": f'{a.get("name") or "Someone"} · asked' + ("" if a.get("sent") else ", not sent yet")}


def _candidates(team: str, day: str, place: Dict[str, Any], slot: int, cands: List[Dict[str, Any]]) -> str:
    from member_portal_serving import _form
    rows = []
    for c in cands:
        why = ("away that Sunday" if c["away"] else f'on {c["clash"]} that hour' if c["clash"]
               else f'at {c["at_most"]} Sundays this month' if c["at_most"] and c["load"] >= c["at_most"]
               else "learning it" if c["trained"] == "learning" else "not trained on it" if not c["trained"] else "")
        load = f'{c["load"]} Sunday{"" if c["load"] == 1 else "s"} this month'
        sub = why or load
        can = c["ok"] and c["trained"]
        act = (_form("/my/lead/sundays/ask", {"team": team, "day": day, "place": place["id"], "slot": str(slot),
                                              "person": c["contact_id"]}, "Ask", "sv-btn hue") if can else "")
        rows.append(f'<div class="c{"" if can else " dim"}"><span class="sv-av" aria-hidden="true">{_e(_initials(c["name"]))}</span>'
                    f'<span class="t"><b>{_e(c["name"])}</b><small>{_e(sub)}</small></span>{act}</div>')
    offer = _form("/my/lead/sundays/offer", {"team": team, "day": day, "place": place["id"], "slot": str(slot)},
                  "Offer it to the whole team")
    return (f'<div class="sv-sub" id="spot"><b>Who could take {_e(place["name"])}</b>'
            f'<p>Free and not away first, then the most rested. Learning it means pairing them with someone.</p>'
            f'<div class="sl-who">{"".join(rows) or "<p>Nobody is on the team yet.</p>"}</div>'
            f'<div class="sv-acts">{offer}</div></div>')


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], teams: List[Dict[str, Any]],
           v: Optional[Dict[str, Any]], day: str, spot: str, cands: Optional[List[Dict[str, Any]]], groups: int = 0) -> str:
    from member_portal import _shell
    from member_portal_lead import LEAD_CSS, _seg
    from member_portal_serving import SERVING_CSS, _form
    first = _first(me.get("name"))
    head = (f'<header class="ld-head"><h1 class="ld-hello">Lead, <em>{_e(first)}</em></h1></header>'
            f'{_seg("sundays", False, False, 0, 0, groups)}')
    css = f"<style>{LEAD_CSS}{SERVING_CSS}{LEADING_CSS}</style>"
    if not teams:
        body = (f'{head}<section class="ld-card"><p>You don\'t lead a Sunday team right now. When the church office makes you '
                f'a team\'s leader, its Sundays show up here.</p><p><a href="/my/lead">Back to Lead</a></p></section>')
        return _shell(biz, site, "Sundays", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)
    team = v["team"]
    gid = team["group_id"]
    chips = ""
    if len(teams) > 1:
        chips = '<div class="sv-teams h-teal">' + "".join(
            f'<a class="sv-chip" href="{_e(_url(t["group_id"]))}"{" aria-current=\"page\"" if t["group_id"] == gid else ""}>{_e(t["name"])}</a>'
            for t in teams) + "</div>"
    services = v["services"]
    if not services:
        body = (f'{head}{chips}<div class="h-teal"><p class="sl-team">{_e(team["name"])}</p><h2 class="sl-h">No Sundays to plan yet</h2>'
                f'<p class="sl-sub">When the church office adds the coming Sundays, they show here.</p></div>')
        return _shell(biz, site, "Sundays", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)
    by_spot = {(a["service_id"], a["position_id"], a["slot"]): a for a in v["assignments"]}
    cur = next((s for s in services if s["id"] == day), services[0])

    def open_count(s: Dict[str, Any]) -> int:
        return sum(1 for p in team["places"] for k in range(1, (p["needed"] or 1) + 1)
                   if _state(by_spot.get((s["id"], p["id"], k)))["k"] in ("open", "no", "team"))

    days = "".join(
        f'<a href="{_e(_url(gid, s["id"]))}"{" aria-current=\"page\"" if s["id"] == cur["id"] else ""}>'
        f'<small>{_day_of(s).strftime("%a")}</small><b>{_day_of(s).day}</b>'
        f'<small>{open_count(s)} open</small></a>' for s in services)
    waiting = sum(1 for a in v["assignments"] if a["status"] == "asked")
    filled = request.query_params.get("filled")
    fill_out = ""
    if filled is not None:
        ids = str(request.query_params.get("ids") or "")
        n, left = filled, str(request.query_params.get("left") or "0")
        fill_out = (f'<div class="sl-filled h-teal"><b>{"Nobody free to ask." if n == "0" else f"Asked people for {_e(n)} spot" + ("" if n == "1" else "s") + "."}</b>'
                    f'<span>Only people trained for the place, free that hour and not away, and nobody past the team\'s Sundays a month. '
                    f'Nothing has gone out yet.{f" {_e(left)} still need someone." if left != "0" else ""}</span>'
                    + (_form("/my/lead/sundays/unfill", {"team": gid, "ids": ids}, "Take them back") if ids else "") + "</div>")
    rows = []
    for p in team["places"]:
        for k in range(1, (p["needed"] or 1) + 1):
            a = by_spot.get((cur["id"], p["id"], k))
            st = _state(a)
            key = f'{p["id"]}:{k}'
            name = p["name"] + (f" {k}" if (p["needed"] or 1) > 1 else "")
            if st["k"] in ("open", "team"):
                av = '<span class="sv-av open" aria-hidden="true">+</span>'
            else:
                av = f'<span class="sv-av" aria-hidden="true">{_e(_initials(a.get("name")))}</span>'
            if st["k"] in ("open", "no", "team"):
                act = f'<a class="sv-btn" href="{_e(_url(gid, cur["id"], key))}#spot">Find someone</a>'
            elif st["k"] == "wait":
                act = _form("/my/lead/sundays/takeback", {"team": gid, "day": cur["id"], "id": a["id"]}, "Take back")
            else:
                act = '<span class="sv-st">Said yes</span>'
            rows.append(f'<div class="sv-row ind">{av}<span class="t"><span class="ti">{_e(name)}</span>'
                        f'<span class="su">{_e(st["words"])}</span></span>{act}</div>')
            if spot == key and cands is not None:
                rows.append(_candidates(gid, cur["id"], p, k, cands))
    call = f' · be there by {_e(team["call_time"])}' if team.get("call_time") else ""
    fill = _form("/my/lead/sundays/fill", {"team": gid}, "Fill the next five Sundays", "sv-btn hue")
    body = f"""{head}{_flash(request)}{chips}
<div class="h-teal"><p class="sl-team">{_e(team["name"])}</p><h2 class="sl-h">Your team's Sundays</h2>
<p class="sl-sub">{waiting} waiting on an answer. You see your team; the office sees every team. Someone on another team that hour shows here, so nobody is double-booked.</p></div>
<div class="sl-acts h-teal">{fill}</div>{fill_out}
<nav class="sl-days h-teal" aria-label="Sunday">{days}</nav>
<section class="sv-sec h-teal" style="margin-top:14px" aria-label="{_e(cur["title"])}">
<div class="sv-sh"><h2>{_e(_day_of(cur).strftime("%A, %B ") + str(_day_of(cur).day))}</h2></div>
<p class="sv-lede" style="padding:0 0 12px">{_e(cur["title"])} at {_e(cur["time"])}{call}</p>
<div class="sv-card">{"".join(rows)}</div></section>"""
    return _shell(biz, site, "Sundays", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any]):
    """GET /my/lead/sundays: (html, status)."""
    from member_portal import _shell
    cid = str(me["id"])
    try:
        teams = await asyncio.to_thread(sl.led_teams, str(biz["id"]), cid)
        q = request.query_params
        gid = str(q.get("team") or "")
        if teams and gid not in {t["group_id"] for t in teams}:
            gid = teams[0]["group_id"]
        v = await asyncio.to_thread(sl.team_view, biz, cid, gid) if teams else None
        day = str(q.get("day") or "")
        spot = str(q.get("spot") or "")
        cands = None
        m = _SPOT.match(spot)
        if v and m and _ID.match(day):
            cands = await asyncio.to_thread(sl.candidates, biz, cid, day, m.group(1))
        import group_lead
        groups = len(await asyncio.to_thread(group_lead.led_groups, str(biz["id"]), cid) or [])
        return render(biz, site, request, me, teams, v, day, spot if m else "", cands, groups), 200
    except HTTPException as e:
        logger.warning("lead sundays read failed: %s", e.detail)
        return _shell(biz, site, "Sundays", '<a class="mb-back" href="/my/lead">Lead</a>'
                      '<p class="mp-err" role="alert">Your team\'s Sundays couldn\'t load just now. Please try again in a moment.</p>',
                      tab="lead", who=me), 503


# ─── POST ────────────────────────────────────────────────────────────


def _go(team: str, day: str = "", **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    team = team if _ID.match(team) else ""
    day = day if _ID.match(day) else ""
    return RedirectResponse(_url(team, day, **q), status_code=303, headers=_SECURE_HEADERS)


async def _act(request: Request, fn):
    """Signed in, not a preview, not too fast; then fn(biz, me, form)."""
    from member_portal_church import _signed_in
    import rate_limit
    church, me, unavailable = await _signed_in(request)
    form = await request.form()
    team, day = str(form.get("team") or ""), str(form.get("day") or "")
    if unavailable:
        return None, _go(team, day, err="preview" if unavailable == "preview" else "error")
    if not me:
        return None, RedirectResponse("/my", status_code=303)
    biz = church["business"]
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return None, _go(team, day, err="error")
    try:
        out = await asyncio.to_thread(fn, biz, me, form)
    except HTTPException as e:
        if e.status_code in (400, 404, 409):
            return None, _go(team, day, err="said", msg=str(e.detail))
        return None, _go(team, day, err="error")
    return out, None


def _ids_of(form, key: str) -> List[str]:
    return [x for x in str(form.get(key) or "").split(",") if _ID.match(x)][:200]


def _need(form, *keys: str) -> List[str]:
    vals = [str(form.get(k) or "") for k in keys]
    if not all(_ID.match(v) for v in vals):
        raise HTTPException(400, "That didn't come through. Try again.")
    return vals


def _slot(form) -> int:
    try:
        return int(str(form.get("slot") or "1"))
    except ValueError:
        raise HTTPException(400, "That place doesn't have that many spots")


@router.post("/my/lead/sundays/ask", include_in_schema=False)
async def ask(request: Request):
    def go(biz, me, form):
        day, place, person = _need(form, "day", "place", "person")
        return sl.ask(biz, me, day, place, _slot(form), person)
    out, err = await _act(request, go)
    form = await request.form()
    return err or _go(str(form.get("team") or ""), str(form.get("day") or ""), done="asked")


@router.post("/my/lead/sundays/offer", include_in_schema=False)
async def offer(request: Request):
    def go(biz, me, form):
        day, place = _need(form, "day", "place")
        return sl.offer(biz, me, day, place, _slot(form))
    out, err = await _act(request, go)
    form = await request.form()
    return err or _go(str(form.get("team") or ""), str(form.get("day") or ""), done="offered")


@router.post("/my/lead/sundays/takeback", include_in_schema=False)
async def takeback(request: Request):
    def go(biz, me, form):
        (aid,) = _need(form, "id")
        return sl.take_back(biz, me, aid)
    out, err = await _act(request, go)
    form = await request.form()
    return err or _go(str(form.get("team") or ""), str(form.get("day") or ""), done="back")


@router.post("/my/lead/sundays/fill", include_in_schema=False)
async def fill(request: Request):
    def go(biz, me, form):
        (team,) = _need(form, "team")
        return sl.fill(biz, me, team)
    out, err = await _act(request, go)
    form = await request.form()
    if err:
        return err
    return _go(str(form.get("team") or ""), filled=str(out["asked"]), left=str(out["still_open"]), ids=",".join(out["ids"]))


@router.post("/my/lead/sundays/unfill", include_in_schema=False)
async def unfill(request: Request):
    def go(biz, me, form):
        (team,) = _need(form, "team")
        return sl.unfill(biz, me, team, _ids_of(form, "ids"))
    out, err = await _act(request, go)
    form = await request.form()
    return err or _go(str(form.get("team") or ""), done="unfilled")
