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

MY DEPARTMENT (docs/CHURCH_SCHEDULE.md section 8.8; the pastor approved the
mock and four calls on 2026-11-20). For a department's leader and its
overseer on the leaders map, this page opens on their department's week
(church_week.department_week: the office's week, kept to their departments):

    GET /my/lead/sundays[?week=next]     this week, or next week

This week or next, three counts (on the schedule, open places, away), Look at
first, then each department in turn: one card a team, each service's places
and who is on them (On, Asked, no answer yet, Open, Away), Find someone on an
open place of a Volunteers' team still to come, and who is away. No hours and
no check state: someone on a kids place who isn't cleared reads "The office is
handling this place". Worship and production (ChurchSavvy's teams) are read
only, no Find someone. Find someone opens that team's Sunday here (?team=),
with the same fair fill as a team's own leader (sunday_leading, which checks
every write: their team, or a Volunteers' team of a department they lead or
oversee). A team leader over no department sees their own team, as before.
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

import serve_dates as sd
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
.dw-weeks{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:4px;padding:3px;border-radius:12px;
  background:var(--s1);margin:14px 0 0;max-width:340px;}
.dw-weeks a{display:flex;align-items:center;justify-content:center;min-height:38px;border-radius:9px;font-size:14px;font-weight:600;
  color:var(--fg2);text-decoration:none;white-space:nowrap;}
.dw-weeks a[aria-current]{background:var(--s3);color:var(--fg);}
.dw-counts{margin-top:14px;}
.dw-look{display:flex;flex-direction:column;}
.dw-look .it{display:flex;align-items:flex-start;gap:12px;padding:12px 16px;position:relative;}
.dw-look .it + .it::before{content:"";position:absolute;top:0;left:16px;right:0;height:.5px;background:var(--line);}
.dw-look .it .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
.dw-look .it b{font-size:15px;font-weight:620;line-height:1.35;}
.dw-look .it small{font-size:13px;color:var(--fg2);line-height:1.4;}
.dw-dh{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 10px;margin:30px 0 10px;}
.dw-dh h2{margin:0;font-size:22px;font-weight:720;letter-spacing:-.025em;}
.dw-dh small{font-size:13.5px;color:var(--fg2);}
.dw-team + .dw-team{margin-top:12px;}
.dw-th{display:flex;align-items:center;flex-wrap:wrap;gap:6px 10px;padding:14px 16px 4px;}
.dw-th b{font-size:16.5px;font-weight:680;letter-spacing:-.015em;}
.dw-svc{margin:0;padding:10px 16px 0;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--fg3);}
.dw-team .sv-row{padding:10px 16px;}
.dw-team .sv-row .su{overflow-wrap:anywhere;}
.dw-team .su b{font-weight:640;color:var(--fg);}
.dw-team .su i{font-style:normal;}
.dw-team .su i.dw-open,.dw-team .su i.dw-away{color:var(--coral-ink);font-weight:650;}
.dw-team .su i.dw-wait{color:var(--gold-ink);font-weight:600;}
.dw-quiet{margin:0;padding:6px 16px 14px;font-size:13.5px;color:var(--fg2);}
.dw-away{margin-top:12px;}
.dw-away h3{margin:0;padding:14px 16px 4px;font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--fg3);}
.dw-away .r{display:flex;justify-content:space-between;gap:12px;padding:10px 16px;font-size:14.5px;}
.dw-away .r span{color:var(--fg2);text-align:right;}
"""

UNREAD = "Sundays couldn't load just now. Please try again in a moment."
DEPT_UNREAD = "Your department's week couldn't load just now. Please try again in a moment."


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


def _state(a: Optional[Dict[str, Any]], notes: bool = True) -> Dict[str, str]:
    """How a place stands. `notes`: the note someone left with a no, for
    the team's own leader only; a department's leader or overseer on a team
    they don't lead reads "Rory can't" and no more (as the office's week
    never shows an answer's note)."""
    if not a:
        return {"k": "open", "words": "Nobody yet"}
    if a["status"] == "offered":
        return {"k": "team", "words": "Offered to the team"}
    if a["status"] == "no":
        note = f' · {a["note"]}' if notes and a.get("note") else ""
        return {"k": "no", "words": f'{_first(a.get("name"))} can\'t{note}'}
    if a["status"] == "yes":
        return {"k": "yes", "words": f'{a.get("name") or "Someone"} said yes'}
    return {"k": "wait", "words": f'{a.get("name") or "Someone"} · asked' + ("" if a.get("sent") else ", not sent yet")}


def _candidates(team: str, day: str, place: Dict[str, Any], slot: int, cands: List[Dict[str, Any]]) -> str:
    from member_portal_serving import _form
    rows = []
    for c in cands:
        why = ("away that day" if c["away"] else f'on {c["clash"]} that hour' if c["clash"]
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


def _chips(teams: List[Dict[str, Any]], current: str, dept: bool) -> str:
    """My department (for a department's leader or overseer), then their own
    teams, then the team open now when it is one of their department's:
    only when there is more than one."""
    here = ' aria-current="page"'
    links = [f'<a class="sv-chip" href="/my/lead/sundays"{here if not current else ""}>My department</a>'] if dept else []
    links += [f'<a class="sv-chip" href="{_e(_url(t["group_id"]))}"{here if t["group_id"] == current else ""}>'
              f'{_e(t["name"])}</a>' for t in teams]
    return f'<div class="sv-teams h-teal">{"".join(links)}</div>' if len(links) > 1 else ""


def _head(me: Dict[str, Any], groups: int) -> str:
    from member_portal_lead import _seg
    return (f'<header class="ld-head"><h1 class="ld-hello">Lead, <em>{_e(_first(me.get("name")))}</em></h1></header>'
            f'{_seg("sundays", False, False, 0, 0, groups)}')


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], teams: List[Dict[str, Any]],
           v: Optional[Dict[str, Any]], day: str, spot: str, cands: Optional[List[Dict[str, Any]]], groups: int = 0,
           dept: bool = False) -> str:
    from member_portal import _shell
    from member_portal_lead import LEAD_CSS
    from member_portal_serving import SERVING_CSS, _form
    head = _head(me, groups)
    css = f"<style>{LEAD_CSS}{SERVING_CSS}{LEADING_CSS}</style>"
    if not v:
        body = (f'{head}<section class="ld-card"><p>You don\'t lead a Sunday team right now. When the church office makes you '
                f'a team\'s leader, its Sundays show up here.</p><p><a href="/my/lead">Back to Lead</a></p></section>')
        return _shell(biz, site, "Sundays", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)
    team = v["team"]
    gid = team["group_id"]
    theirs = not team.get("by_department")
    shown = list(teams) + ([] if any(t["group_id"] == gid for t in teams) else [{"group_id": gid, "name": team["name"]}])
    chips = _chips(shown, gid, dept)
    services = v["services"]
    if not services:
        body = (f'{head}{chips}<div class="h-teal"><p class="sl-team">{_e(team["name"])}</p><h2 class="sl-h">No Sundays to plan yet</h2>'
                f'<p class="sl-sub">When the church office adds the coming Sundays, they show here.</p></div>')
        return _shell(biz, site, "Sundays", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)
    by_spot = {(a["service_id"], a["position_id"], a["slot"]): a for a in v["assignments"]}
    cur = next((s for s in services if s["id"] == day), services[0])

    def open_count(s: Dict[str, Any]) -> int:
        return sum(1 for p in team["places"] for k in range(1, sd.needed(s, p) + 1)
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
        for k in range(1, sd.needed(cur, p) + 1):
            a = by_spot.get((cur["id"], p["id"], k))
            st = _state(a, notes=theirs)
            key = f'{p["id"]}:{k}'
            name = p["name"] + (f" {k}" if sd.needed(cur, p) > 1 else "")
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
    if theirs:
        title, sub = "Your team's Sundays", "You see your team; the office sees every team."
    else:
        # Said only when it is so: the church sends serving notes, and the team has a leader besides them.
        import member_push
        told = "serving" in member_push.church_kinds(biz.get("settings")) and any(
            p.get("leader") and str(p.get("contact_id")) != str(me.get("id")) for p in team.get("people") or [])
        title, sub = "This team's Sundays", "It's one of your department's teams." + (
            " Whoever leads it is told what you ask, offer or fill here." if told else "")
    body = f"""{head}{_flash(request)}{chips}
<div class="h-teal"><p class="sl-team">{_e(team["name"])}</p><h2 class="sl-h">{title}</h2>
<p class="sl-sub">{waiting} waiting on an answer. {sub} Someone on another team that hour shows here, so nobody is double-booked.</p></div>
<div class="sl-acts h-teal">{fill}</div>{fill_out}
<nav class="sl-days h-teal" aria-label="Sunday">{days}</nav>
<section class="sv-sec h-teal" style="margin-top:14px" aria-label="{_e(cur["title"])}">
<div class="sv-sh"><h2>{_e(_day_of(cur).strftime("%A, %B ") + str(_day_of(cur).day))}</h2></div>
<p class="sv-lede" style="padding:0 0 12px">{_e(cur["title"])} at {_e(cur["time"])}{call}</p>
<div class="sv-card">{"".join(rows)}</div></section>"""
    return _shell(biz, site, "Sundays", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)


# ─── My department (docs/CHURCH_SCHEDULE.md section 8.8) ──────────────


def _dept_url(which: str = "") -> str:
    return "/my/lead/sundays" + ("?week=next" if which == "next" else "")


def _dept_row(r: Dict[str, Any]) -> str:
    """One place: who is on it and how it stands, and Find someone on an
    open place of a Volunteers' team still to come. Never an hour, never a
    check: the office's place says only that the office has it."""
    open_ = r["state"] == "open"
    av = ('<span class="sv-av open" aria-hidden="true">+</span>' if open_
          else f'<span class="sv-av" aria-hidden="true">{_e(_initials(r["who"]))}</span>')
    words = f'<i class="dw-{"wait" if r["state"] == "no_answer" else r["state"]}">{_e(r["words"])}</i>'
    said = words if open_ else f'<b>{_e(r["who"])}</b> · {words}'
    note = f'<span class="su">{_e(r["note"])}</span>' if r.get("note") else ""
    f = r.get("find")
    act = (f'<a class="sv-btn" href="{_e(_url(f["team"], f["day"], f["spot"]))}#spot">Find someone</a>' if f else "")
    return (f'<div class="sv-row ind">{av}<span class="t"><span class="ti">{_e(r["place"])}</span>'
            f'<span class="su">{said}</span>{note}</span>{act}</div>')


def _dept_team(t: Dict[str, Any]) -> str:
    chip = '<span class="sv-chip">Scheduled in ChurchSavvy</span>' if t["churchsavvy"] else ""
    parts = [f'<div class="dw-th"><b>{_e(t["name"])}</b>{chip}</div>']
    if not t["services"]:
        parts.append('<p class="dw-quiet">Nothing this week.</p>')
    for s in t["services"]:
        parts.append(f'<p class="dw-svc">{_e(s["words"])}{" · passed" if s["past"] else ""}</p>')
        parts += [_dept_row(r) for r in s["rows"]]
    return f'<div class="sv-card dw-team">{"".join(parts)}</div>'


def _dept_section(d: Dict[str, Any], alone: bool = False) -> str:
    """One department: its name (unless it is the only one and theirs to
    lead, which the page's own heading already says), its teams, who is
    away."""
    led = f'<small>Led by {_e(d["led_by"])}</small>' if d.get("led_by") else ""
    head = "" if alone and not led else f'<div class="dw-dh"><h2>{_e(d["name"])}</h2>{led}</div>'
    if d["teams"]:
        teams = "".join(_dept_team(t) for t in d["teams"])
    elif d.get("elsewhere"):
        # Its teams are on an earlier department's card (one team, two departments): say where.
        lines = "".join(f'<p class="dw-quiet" style="padding-top:14px">{_e(x["team"])} is shown under '
                        f'{_e(x["under"])} above.</p>' for x in d["elsewhere"])
        teams = f'<div class="sv-card">{lines}</div>'
    else:
        teams = (f'<div class="sv-card"><p class="dw-quiet" style="padding-top:14px">No Sunday team is part of '
                 f'{_e(d["name"])} yet. When the church office adds one, its week shows here.</p></div>')
    if d["away"]:
        away = "".join(f'<div class="r"><b>{_e(a["name"])}</b><span>{_e(a["days"])}</span></div>' for a in d["away"])
    else:
        away = '<p class="dw-quiet">Nobody on these teams is away this week.</p>'
    # Who is away is said under the card that shows their team: none here without a team of its own.
    away = f'<div class="sv-card dw-away"><h3>Away</h3>{away}</div>' if d["teams"] else ""
    return (f'<section class="h-teal" aria-label="{_e(d["name"])}"{"" if head else " style=\"margin-top:24px\""}>'
            f'{head}{teams}{away}</section>')


def render_department(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], d: Dict[str, Any],
                      teams: List[Dict[str, Any]], groups: int = 0) -> str:
    """My department: this week or next, the counts, Look at first, then
    each department in turn."""
    from member_portal import _shell
    from member_portal_lead import LEAD_CSS
    from member_portal_serving import SERVING_CSS
    import church_week as cw
    css = f"<style>{LEAD_CSS}{SERVING_CSS}{LEADING_CSS}</style>"
    which = d["week"]["which"]
    here = ' aria-current="page"'
    weeks = (f'<nav class="dw-weeks" aria-label="Week"><a href="{_dept_url()}"{here if which == "this" else ""}>This week</a>'
             f'<a href="{_dept_url("next")}"{here if which == "next" else ""}>Next week</a></nav>')
    names = cw._join([x["name"] for x in d["departments"]])
    n = d["counts"]
    counts = (f'<div class="sv-stats dw-counts">'
              f'<div class="sv-stat"><b>{n["on"]}</b><small>On the schedule</small></div>'
              f'<div class="sv-stat"><b>{n["open"]}</b><small>Open places</small></div>'
              f'<div class="sv-stat"><b>{n["away"]}</b><small>Away</small></div></div>')
    items = []
    for x in d["look"]:
        f = x.get("find")
        act = f'<a class="sv-btn" href="{_e(_url(f["team"], f["day"]))}">Find someone</a>' if f else ""
        details = "".join(f"<small>{_e(t)}</small>" for t in x["details"])
        items.append(f'<div class="it"><span class="t"><b>{_e(x["title"])}</b>{details}</span>{act}</div>')
    look = (f'<section class="sv-sec h-teal" style="margin-top:22px" aria-label="Look at first"><div class="sv-sh">'
            f'<h2>Look at first</h2></div><div class="sv-card dw-look">{"".join(items)}</div></section>')
    body = f"""{_head(me, groups)}{_flash(request)}{_chips(teams, "", True)}
<div class="h-teal"><p class="sl-team">{_e(names)}</p><h2 class="sl-h">My department</h2>
<p class="sl-sub">{_e(d["week"]["words"])}. Who is on, what's open and who is away, team by team.</p></div>
{weeks}{counts}{look}{"".join(_dept_section(x, len(d["departments"]) == 1) for x in d["departments"])}"""
    return _shell(biz, site, "My department", f'{css}<div class="ld-wide">{body}</div>', tab="lead", who=me)


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any]):
    """GET /my/lead/sundays: (html, status). A team asked for (?team=) that
    is theirs, or one of their department's Volunteers' teams, opens on its
    Sundays; otherwise a department's leader or overseer reads My
    department, and anyone else their first team, as before. Someone who
    heads no department (church_week.entry: what it keeps a minute, never
    raising) never waits on a department read: their page is what it was."""
    from member_portal import _shell
    import church_week as cw
    cid = str(me["id"])
    try:
        teams = await asyncio.to_thread(sl.led_teams, str(biz["id"]), cid)
        q = request.query_params
        gid = str(q.get("team") or "")
        import group_lead
        groups = len(await asyncio.to_thread(group_lead.led_groups, str(biz["id"]), cid) or [])
        dept = await asyncio.to_thread(cw.standing, biz, cid)
        if dept is None and not teams:
            # Who heads a department couldn't be read, and there is no team of theirs to show instead.
            raise HTTPException(503, DEPT_UNREAD)
        v = None
        if _ID.match(gid) and gid in {t["group_id"] for t in teams}:
            v = await asyncio.to_thread(sl.team_view, biz, cid, gid)
        elif _ID.match(gid) and dept:
            try:                                    # one of their department's teams (sunday_leading checks)
                v = await asyncio.to_thread(sl.team_view, biz, cid, gid)
            except HTTPException as e:
                if e.status_code != 404:
                    raise
        if v is None and dept:
            try:
                d = await asyncio.to_thread(cw.department_week, biz, cid, str(q.get("week") or ""))
            except HTTPException as e:
                logger.warning("my department read failed: %s", e.status_code)
                return _shell(biz, site, "My department", f'<style>{_lead_css()}</style><div class="ld-wide">'
                              f'{_head(me, groups)}<p class="mp-err" role="alert">{DEPT_UNREAD}</p></div>',
                              tab="lead", who=me), 503
            if d is not None:
                return render_department(biz, site, request, me, d, teams, groups), 200
        if v is None and teams:
            gid = teams[0]["group_id"]
            v = await asyncio.to_thread(sl.team_view, biz, cid, gid)
        day = str(q.get("day") or "")
        spot = str(q.get("spot") or "")
        cands = None
        m = _SPOT.match(spot)
        if v and m and _ID.match(day):
            cands = await asyncio.to_thread(sl.candidates, biz, cid, day, m.group(1))
        return render(biz, site, request, me, teams, v, day, spot if m else "", cands, groups, dept=bool(dept)), 200
    except HTTPException as e:
        logger.warning("lead sundays read failed: %s", e.detail)
        said = DEPT_UNREAD if e.detail == DEPT_UNREAD else UNREAD
        return _shell(biz, site, "Sundays", '<a class="mb-back" href="/my/lead">Lead</a>'
                      f'<p class="mp-err" role="alert">{said}</p>', tab="lead", who=me), 503


def _lead_css() -> str:
    from member_portal_lead import LEAD_CSS
    return LEAD_CSS


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
