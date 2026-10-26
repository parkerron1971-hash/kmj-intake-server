"""
member_portal_serving.py — My serving, in the member app (ChurchSavvy Planning).

From the approved canvas "Sunday Planning + ChurchSavvy" (Ct88v7pxpq5a4PGYX3MuQQ),
built to look as drawn:
  board 7 "The ask": "Production · Marcus asked / Can you serve on Slides?",
    the Sunday in its date box with "Be there by", Yes, I'll serve / Can't
    that day / "I can't, but I can do Nov 8", then "You're on" or "Thanks for
    saying so" with why (only the office sees it), and "On with you".
  board 8 "My serving": the teams and places, Sundays this year / coming up /
    to answer, the asks, Coming up with "Can't make it" (find a sub: someone
    trained or learning and free; you stay on until they say yes, or just
    tell the leader), Away ("Nobody asks you on these days") and How often.

  GET  /my/serving                 (member_portal.serve)
  GET  /my/serving/<id>            one ask, a cover request, or an offered place
  GET  /my/serving/<id>.ics        that Sunday, for a calendar
  POST /my/serving/answer          {id, ans: yes|no|other}
  POST /my/serving/why             {id, why}
  POST /my/serving/take            {id}: an offered place; the first yes takes it
  POST /my/serving/sub             {id, sub}: ask someone to cover
  POST /my/serving/sub/stop        {id}
  POST /my/serving/cant            {id, why}: just tell the leader
  POST /my/serving/away            {start, end}
  POST /my/serving/away/remove     {id}
  POST /my/serving/often           {often: one|two|every}

The logic is sunday_serving.py. The owner's preview shows the pages; nothing
saves. Asks reach phones once the sending sweep ships; until then a member
finds them here and on Home.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import sunday_serving as ss

logger = logging.getLogger("member_portal_serving")
router = APIRouter(tags=["member-portal"])

_ID = re.compile(r"^[0-9a-fA-F-]{36}$")

SERVING_CSS = """
.sv-lt{margin:4px 0 0;}
.sv-eb{margin:0;font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--h-ink);}
.sv-h{font-size:34px;font-weight:720;letter-spacing:-.035em;line-height:1.05;margin:2px 0 0;text-wrap:wrap;}
.sv-h em{font-family:var(--mb-serif);font-style:italic;font-weight:500;letter-spacing:-.02em;color:var(--h-ink);}
.sv-sec{margin-top:32px;}
.sv-sh{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 0 12px;}
.sv-sh h2{margin:0;font-size:21px;font-weight:700;letter-spacing:-.025em;}
.sv-sh a{font-size:15px;font-weight:500;color:var(--h-ink);text-decoration:none;}
.sv-lede{margin:0;padding:8px 0 0;font-size:15px;color:var(--fg2);line-height:1.45;}
.sv-teams{display:flex;gap:6px;flex-wrap:wrap;padding:10px 0 0;}
.sv-chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:999px;background:var(--h-deep);
  color:var(--h-ink);font-size:12.5px;font-weight:650;white-space:nowrap;}
.sv-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;}
.sv-stat{border-radius:var(--r-md);background:var(--s1);padding:14px 12px;display:flex;flex-direction:column;gap:2px;}
.sv-stat b{font-size:26px;font-weight:720;letter-spacing:-.03em;line-height:1.1;}
.sv-stat small{font-size:12.5px;color:var(--fg2);line-height:1.3;}
.sv-date{width:52px;padding:7px 0 8px;border-radius:13px;background:var(--coral);color:var(--on-coral);text-align:center;line-height:1;
  display:flex;flex-direction:column;align-items:center;flex:none;}
.sv-date .m{font-size:10.5px;font-weight:750;letter-spacing:.08em;}
.sv-date .d{font-size:22px;font-weight:750;letter-spacing:-.03em;margin-top:3px;}
.sv-date.soft{background:var(--coral-deep);color:var(--coral-ink);}
.sv-ask{border-radius:var(--r-lg);background:var(--teal-deep);padding:14px 16px;display:flex;align-items:center;gap:14px;
  color:var(--fg);text-decoration:none;}
.sv-ask + .sv-ask{margin-top:10px;}
.sv-ask .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.sv-ask .t b{font-size:16px;font-weight:660;}
.sv-ask .t small{font-size:13px;color:var(--fg2);}
.sv-ask .mb-ic{color:var(--teal-ink);}
.sv-card{border-radius:var(--r-md);background:var(--s1);}
.sv-card > form{margin:0;}
.sv-opt{display:flex;align-items:center;gap:14px;padding:12px 16px;position:relative;width:100%;text-align:left;border:0;
  background:transparent;color:var(--fg);font:inherit;cursor:pointer;}
.sv-card > form + form .sv-opt::before{content:"";position:absolute;top:0;left:16px;right:0;height:.5px;background:var(--line);}
.sv-opt .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.sv-opt .t b{font-size:15.5px;font-weight:620;}
.sv-opt .t small{font-size:13px;color:var(--fg2);line-height:1.35;}
.sv-tg{width:51px;height:31px;border-radius:999px;background:var(--s3);padding:2px;display:flex;flex:none;}
.sv-tg i{width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.25);display:block;}
.sv-tg.on{background:var(--teal);}
.sv-tg.on i{transform:translateX(20px);}
.sv-row{display:flex;align-items:center;gap:14px;padding:14px 16px;position:relative;}
.sv-row + .sv-row::before,.sv-sub + .sv-row::before{content:"";position:absolute;top:0;left:16px;right:0;height:.5px;background:var(--line);}
.sv-row.ind + .sv-row.ind::before{left:62px;}
.sv-row .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.sv-row .ti{font-size:16px;font-weight:620;letter-spacing:-.015em;}
.sv-row .su{font-size:13.5px;color:var(--fg2);}
.sv-st{font-size:12.5px;font-weight:650;color:var(--teal-ink);white-space:nowrap;}
.sv-st.open{color:var(--coral-ink);}
.sv-st.wait{color:var(--gold-ink);}
.sv-av{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--h-deep,var(--s2));
  color:var(--h-ink,var(--fg));font-size:12px;font-weight:650;}
.sv-av.open{background:transparent;border:1.5px dashed var(--fg3);color:var(--fg3);}
.sv-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:36px;padding:0 14px;border-radius:999px;border:0;
  background:var(--s2);color:var(--fg);font:inherit;font-size:14px;font-weight:600;white-space:nowrap;cursor:pointer;text-decoration:none;}
.sv-btn.hue{background:var(--h);color:var(--on-h);}
.sv-btn.soft{background:var(--s1);}
.sv-row form,.sv-sub form,.sv-hero form{margin:0;}
.sv-sub{margin:0 12px 12px;border-radius:16px;background:var(--s2);padding:14px;display:flex;flex-direction:column;gap:10px;}
.sv-sub b{font-size:15px;font-weight:650;}
.sv-sub .c{display:flex;align-items:center;gap:10px;font-size:14px;}
.sv-sub .c .t{flex:1;min-width:0;display:flex;flex-direction:column;}
.sv-sub .c small{font-size:12.5px;color:var(--fg2);}
.sv-sub .c.dim{opacity:.55;}
.sv-sub p{margin:0;font-size:13.5px;color:var(--fg2);line-height:1.4;}
.sv-acts{display:flex;gap:8px;flex-wrap:wrap;}
.sv-away{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}
.sv-away form{margin:0;}
.sv-away .on{display:inline-flex;align-items:center;gap:6px;min-height:38px;padding:0 6px 0 14px;border-radius:999px;background:var(--s1);
  font-size:14px;font-weight:600;}
.sv-away .on button{width:30px;height:30px;border-radius:50%;border:0;background:transparent;color:var(--fg3);display:grid;place-items:center;cursor:pointer;}
.sv-add summary{display:inline-flex;align-items:center;gap:6px;min-height:38px;padding:0 14px;border-radius:999px;border:1.5px dashed var(--fg3);
  font-size:14px;font-weight:600;color:var(--fg2);cursor:pointer;list-style:none;}
.sv-add summary::-webkit-details-marker{display:none;}
.sv-add[open] summary{margin-bottom:10px;}
.sv-add form{display:flex;flex-direction:column;gap:10px;padding:14px;border-radius:16px;background:var(--s1);}
.sv-add label{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:600;color:var(--fg2);}
.sv-add input{min-height:44px;border-radius:12px;border:1px solid var(--line);background:var(--s2);color:var(--fg);font:inherit;padding:0 12px;}
.sv-add .two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
.sv-seg{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);padding:3px;border-radius:12px;background:var(--s1);margin:0;}
.sv-seg button{min-height:38px;padding:0 2px;border-radius:9px;border:0;background:transparent;font:inherit;font-size:14px;font-weight:600;
  letter-spacing:-.01em;white-space:nowrap;color:var(--fg2);cursor:pointer;}
.sv-seg button[aria-checked="true"]{background:var(--s3);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.2);}
.sv-hero{border-radius:var(--r-lg);background:var(--s1);padding:18px 16px 16px;display:flex;flex-direction:column;gap:16px;margin-top:18px;}
.sv-top{display:flex;gap:14px;align-items:center;}
.sv-top .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
.sv-top .ti{font-size:19px;font-weight:690;letter-spacing:-.02em;}
.sv-top .su{font-size:13.5px;color:var(--fg2);}
.sv-ans{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.sv-ans button{width:100%;min-height:52px;border-radius:15px;border:0;background:var(--s2);color:var(--fg);font:inherit;font-size:16px;
  font-weight:640;display:flex;align-items:center;justify-content:center;gap:8px;cursor:pointer;}
.sv-ans button.yes{background:var(--mb-fill);color:var(--mb-on-fill);}
.sv-ans.one{grid-template-columns:minmax(0,1fr);}
.sv-other{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;min-height:40px;border:0;background:transparent;
  font:inherit;font-size:14px;font-weight:600;color:var(--teal-ink);cursor:pointer;}
.sv-done{display:flex;flex-direction:column;align-items:center;gap:6px;text-align:center;padding:6px 0 2px;}
.sv-done .disc{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;background:var(--h);color:var(--on-h);}
.sv-done b{font-size:20px;font-weight:700;letter-spacing:-.02em;}
.sv-done small{font-size:14px;color:var(--fg2);max-width:30ch;}
.sv-why{display:flex;gap:8px;flex-wrap:wrap;}
.sv-why button{min-height:38px;padding:0 14px;border-radius:999px;border:0;background:var(--s2);font:inherit;font-size:14px;font-weight:600;
  color:var(--fg2);cursor:pointer;}
.sv-why button[aria-pressed="true"]{background:var(--teal-deep);color:var(--teal-ink);box-shadow:inset 0 0 0 1.5px var(--teal-ink);}
.sv-said{display:flex;flex-direction:column;gap:10px;}
.sv-said > b{font-size:16px;}
.sv-said > span{font-size:13.5px;color:var(--fg2);}
.sv-home{margin:4px 0 16px;}
/* The Sunday pack (board 9). */
.sv-pk-when{display:flex;flex-direction:column;gap:4px;margin:4px 0 0;}
.sv-pk-when .sv-eb{color:var(--coral-ink);}
.sv-pk-when h1{margin:0;font-size:30px;font-weight:730;letter-spacing:-.035em;line-height:1.08;text-wrap:wrap;}
.sv-pk-as{padding:14px 0 0;}
.sv-pk-as .sv-seg a{min-height:38px;border-radius:9px;font-size:14px;font-weight:600;color:var(--fg2);display:flex;align-items:center;
  justify-content:center;text-decoration:none;white-space:nowrap;}
.sv-pk-as .sv-seg a[aria-current="page"]{background:var(--s3);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.2);}
.sv-pk-here{border-radius:var(--r-lg);background:var(--s1);padding:16px;display:flex;align-items:center;gap:14px;}
.sv-pk-here.done{background:var(--teal-deep);}
.sv-pk-here.done .t b{color:var(--teal-ink);}
.sv-pk-here .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.sv-pk-here .t b{font-size:16px;font-weight:660;}
.sv-pk-here .t small{font-size:13px;color:var(--fg2);}
.sv-pk-here form{margin:0;}
.sv-pk-disc{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--h);color:var(--on-h);}
.sv-pk-song{display:flex;align-items:flex-start;gap:12px;padding:14px 16px;position:relative;}
.sv-pk-song + .sv-pk-song::before{content:"";position:absolute;top:0;left:56px;right:0;height:.5px;background:var(--line);}
.sv-pk-n{width:28px;height:28px;border-radius:50%;background:var(--gold-deep);color:var(--gold-ink);display:grid;place-items:center;
  font-size:13px;font-weight:750;flex:none;margin-top:2px;}
.sv-pk-song .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px;}
.sv-pk-song .ti{font-size:16px;font-weight:640;letter-spacing:-.015em;display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.sv-pk-song .su{font-size:13px;color:var(--fg2);}
.sv-pk-arr{display:flex;gap:4px;flex-wrap:wrap;}
.sv-pk-arr i{font-style:normal;display:inline-grid;place-items:center;min-width:26px;height:22px;padding:0 6px;border-radius:6px;
  background:var(--s2);font-size:11px;font-weight:700;color:var(--fg2);}
.sv-pk-key{display:inline-grid;place-items:center;min-width:26px;height:22px;padding:0 7px;border-radius:6px;background:var(--gold);
  color:var(--on-gold);font-size:12px;font-weight:750;}
.sv-pk-cue{display:grid;grid-template-columns:52px minmax(0,1fr);gap:10px;padding:11px 16px;position:relative;font-size:14.5px;}
.sv-pk-cue + .sv-pk-cue::before{content:"";position:absolute;top:0;left:16px;right:0;height:.5px;background:var(--line);}
.sv-pk-cue b{font-variant-numeric:tabular-nums;font-size:13.5px;font-weight:650;color:var(--fg2);}
.sv-pk-order{display:grid;grid-template-columns:52px minmax(0,1fr);gap:4px 10px;padding:12px 16px;font-size:14px;}
.sv-pk-order b{font-variant-numeric:tabular-nums;font-size:13px;font-weight:600;color:var(--fg3);}
.sv-sh .sv-pk-only{font-size:13px;font-weight:500;color:var(--fg3);}
"""

DONE = {
    "yes": "", "no": "", "other": "", "why": "Thanks. Only the people who schedule see it.",
    "took": "It's yours. Thank you for serving.", "sub": "Asked. You stay on until they say yes.",
    "stopped": "You're still on for that Sunday.", "told": "Thanks for saying so. The spot is open for someone else.",
    "away": "Saved. Nobody asks you on those days.", "unaway": "Taken off.", "often": "Saved.", "hear": "Saved.", "here": "",
}
ERRS = {"preview": "This is a preview, so nothing was saved.", "slow": "One moment, then try that again.",
        "error": "That didn't save. Please try again in a moment."}


def _e(s: Any) -> str:
    from member_portal import _e as esc
    return esc(s)


def _first(name: Any) -> str:
    return (str(name or "").strip().split(" ") or [""])[0] or "Someone"


def _date(at: datetime, soft: bool = False) -> str:
    return (f'<span class="sv-date{" soft" if soft else ""}" aria-hidden="true"><span class="m">{at.strftime("%b").upper()}</span>'
            f'<span class="d">{at.day}</span></span>')


def _day(at: datetime) -> str:
    return f"{at.strftime('%b')} {at.day}"


def _clock(hhmm: Optional[str]) -> str:
    if not hhmm:
        return ""
    h, m = (int(x) for x in hhmm.split(":")[:2])
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def _at_clock(at: datetime) -> str:
    return _clock(at.strftime("%H:%M"))


def _flash(request: Request) -> str:
    q = request.query_params
    err = ERRS.get(str(q.get("err") or "")) or (str(q.get("msg") or "")[:200] if q.get("err") == "said" else "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    done = DONE.get(str(q.get("done") or ""))
    return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>' if done else ""


def _form(action: str, fields: Dict[str, str], button: str, cls: str = "sv-btn") -> str:
    hidden = "".join(f'<input type="hidden" name="{k}" value="{_e(v)}">' for k, v in fields.items())
    return f'<form method="post" action="{action}">{hidden}<button class="{cls}" type="submit">{button}</button></form>'


# ─── My serving (board 8) ────────────────────────────────────────────


def _ask_row(a: Dict[str, Any]) -> str:
    import member_app_ui as ui
    at = a["service"]["at"]
    t = a["service"]["title"]
    what = f'{_e(a["place"])}, {_e(t + ("" if "sunday" in t.lower() else " Sunday")) if t != "Sunday service" else _day(at)}'
    when = _weekday(a.get("asked_at"), at.tzinfo)
    who = (f'{_e(_first(a["from"]))} asked you to cover · tap to answer' if a.get("from")
           else f'{_e(a["asked_by"] or a["team"])} asked{" " + when if when else ""} · tap to answer')
    return (f'<a class="sv-ask" href="/my/serving/{_e(a["id"])}">{_date(at)}'
            f'<span class="t"><b>{what}</b><small>{who}</small></span>{ui.icon("chevron", 18)}</a>')


def _weekday(iso: Any, zone) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(zone).strftime("%A")
    except (TypeError, ValueError):
        return ""


def _names(names: List[str]) -> str:
    names = [_first(n) for n in names if n]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def _coming_row(c: Dict[str, Any], first_day: Optional[str], subs_html: str) -> str:
    at = c["service"]["at"]
    label = "this Sunday" if c["service"]["day"] == first_day else (
        c["service"]["title"] if c["service"]["title"] != "Sunday service" else at.strftime("%A"))
    be = f'Be there {_clock(c["call_time"])}' if c["call_time"] else f'Service at {_at_clock(at)}'
    if c.get("with"):
        be += f' · with {_names(c["with"])}'
    if c.get("swap_name"):
        sub = f'{_e(_first(c["swap_name"]))} was asked. You stay on until they say yes.'
        act = _form("/my/serving/sub/stop", {"id": c["id"]}, "Stop asking")
    else:
        sub = _e(be)
        act = (f'<a class="sv-btn hue" href="/my/serving/{_e(c["id"])}/pack">Your Sunday</a>' if c["service"]["day"] == first_day
               else '<span class="sv-st">You\'re on</span>' if subs_html
               else f'<a class="sv-btn" href="/my/serving?sub={_e(c["id"])}#sv-{_e(c["id"])}">Can\'t make it</a>')
    return (f'<div class="sv-row" id="sv-{_e(c["id"])}">{_date(at, soft=True)}<span class="t"><span class="ti">{_e(c["place"])} · {_e(label)}</span>'
            f'<span class="su">{sub}</span></span>{act}</div>{subs_html}')


def _subs_panel(c: Dict[str, Any], cands: List[Dict[str, Any]], leader: Optional[str]) -> str:
    import member_app_ui as ui
    at = c["service"]["at"]
    rows = []
    for k in cands[:6]:
        why = ("Away that day" if k["away"] else f'On {k["clash"]} that hour' if k["clash"]
               else f'At their Sundays for the month' if not k["ok"]
               else ("Learning " + c["place"] + " · free that day" if k["trained"] == "learning" else "Free that day"))
        act = (_form("/my/serving/sub", {"id": c["id"], "sub": k["contact_id"]}, f'Ask {_e(_first(k["name"]))}', "sv-btn hue")
               if k["ok"] else "")
        rows.append(f'<div class="c{"" if k["ok"] else " dim"}"><span class="sv-av" aria-hidden="true">{_e(ui.initials(k["name"]))}</span>'
                    f'<span class="t"><span>{_e(k["name"])}</span><small>{_e(why)}</small></span>{act}</div>')
    tell = f'Just tell {_e(_first(leader))}' if leader else "Just tell the church"
    return (f'<div class="sv-sub" role="region" aria-label="Find a sub"><b>Find someone for {_day(at)}</b>'
            + ("".join(rows) or f'<p>Nobody else on {_e(c["team"])} knows {_e(c["place"])} yet.</p>')
            + f'<p>Only people on {_e(c["team"])} who know {_e(c["place"])}. You stay on until someone says yes, so the spot is never empty.</p>'
            + f'<div class="sv-acts">{_form("/my/serving/cant", {"id": c["id"]}, tell, "sv-btn soft")}'
            + '<a class="sv-btn soft" href="/my/serving">Never mind</a></div></div>')


def render_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], m: Dict[str, Any],
                sub_for: Optional[Dict[str, Any]] = None, door: str = "") -> str:
    """`door`: ChurchSavvy's, for someone on its Sunday team (the Serve tab
    opens here for someone whose only part is serving)."""
    import member_app_ui as ui
    from member_portal import _shell
    teams = "".join(
        "".join(f'<span class="sv-chip">{_e(t["name"]) + " · " if i == 0 else ""}{_e(p)}</span>' for i, p in enumerate(t["places"]))
        or f'<span class="sv-chip">{_e(t["name"])}</span>' for t in m["teams"])
    first_day = m.get("next_day")
    asks = (f'<section class="sv-sec" style="margin-top:14px" aria-label="To answer">{"".join(_ask_row(a) for a in m["asks"])}</section>'
            if m["asks"] else "")
    open_ = ""
    if m["open"]:
        rows = "".join(
            f'<div class="sv-row">{_date(o["service"]["at"], soft=True)}<span class="t"><span class="ti">{_e(o["place"])} · {_day(o["service"]["at"])}</span>'
            f'<span class="su">Offered to {_e(o["team"])}. The first yes takes it.</span></span>'
            f'{_form("/my/serving/take", {"id": o["id"]}, "I&#x27;ll take it", "sv-btn hue")}</div>' for o in m["open"])
        open_ = (f'<section class="sv-sec h-gold" aria-labelledby="sv-open-h"><div class="sv-sh"><h2 id="sv-open-h">Open spots you could take</h2></div>'
                 f'<div class="sv-card">{rows}</div></section>')
    coming_rows = "".join(_coming_row(c, first_day, sub_for["html"] if sub_for and sub_for["id"] == c["id"] else "")
                          for c in m["coming"])
    coming = (f'<section class="sv-sec h-teal" aria-labelledby="sv-up-h"><div class="sv-sh"><h2 id="sv-up-h">Coming up</h2></div>'
              + (f'<div class="sv-card">{coming_rows}</div>' if coming_rows
                 else '<p class="sv-lede" style="padding-top:0">Nothing yet. When you say yes to a Sunday, it shows here.</p>')
              + '</section>')
    away_chips = "".join(
        f'<span class="on">{_e(_range(a))}<form method="post" action="/my/serving/away/remove"><input type="hidden" name="id" value="{_e(a["id"])}">'
        f'<button type="submit" aria-label="Take off {_e(_range(a))}">{_x()}</button></form></span>' for a in m["away"])
    add = ('<details class="sv-add"><summary>' + ui.icon("plus", 16) + '<span>Add away dates</span></summary>'
           '<form method="post" action="/my/serving/away"><div class="two">'
           '<label>From<input type="date" name="start" required></label><label>To<input type="date" name="end"></label></div>'
           '<button class="sv-btn hue" type="submit">Save</button></form></details>')
    often = m["often"]
    seg = "".join(f'<button type="submit" name="often" value="{k}" role="radio" aria-checked="{"true" if often == k else "false"}">{t}</button>'
                  for k, t in (("one", "Once a month"), ("two", "Twice"), ("every", "Every week I can")))
    body = f"""<style>{SERVING_CSS}</style><a class="mb-back" href="/my/groups">Connect</a>
<div class="sv-lt h-teal"><p class="sv-eb">{_e(me.get("name") or "")}</p><h1 class="sv-h">My <em>serving</em></h1></div>
{f'<div class="sv-teams h-teal">{teams}</div>' if teams else ''}
{f'<style>{_door_css()}</style><div class="sv-door">{door}</div>' if door else ''}
{_flash(request)}
<section class="sv-sec" style="margin-top:20px" aria-label="This year"><div class="sv-stats">
<div class="sv-stat"><b>{m["this_year"]}</b><small>Sundays this year</small></div>
<div class="sv-stat"><b>{len(m["coming"])}</b><small>coming up</small></div>
<div class="sv-stat"><b>{len(m["asks"])}</b><small>to answer</small></div></div></section>
{asks}{open_}{coming}
<section class="sv-sec" id="away" aria-labelledby="sv-aw-h"><div class="sv-sh"><h2 id="sv-aw-h">Away</h2></div>
<p class="sv-lede" style="padding:0 0 12px">Nobody asks you on these days.</p><div class="sv-away">{away_chips}{add}</div></section>
<section class="sv-sec" aria-labelledby="sv-of-h"><div class="sv-sh"><h2 id="sv-of-h">How often</h2></div>
<form method="post" action="/my/serving/often"><div class="sv-seg" role="radiogroup" aria-label="How often">{seg}</div></form>
<p class="sv-lede">Whoever schedules your team sees this when they fill a month. It's a wish, not a promise.</p></section>
{_hear(m.get("hear"))}"""
    return _shell(biz, site, "My serving", body, tab=_tab(), who=me)


def _door_css() -> str:
    """A door is drawn as the Safety room's is (member_portal_safety)."""
    import member_portal_safety
    return member_portal_safety.SAFETY_CSS + ".sv-door{margin-top:16px;}.sv-door .sf-door{margin:0;}"


def _hear(h: Optional[Dict[str, Any]]) -> str:
    """How I hear (board 8): phone alerts and an email copy. Nothing shows
    until the church has switched Serving on. Texts wait for the church's
    texting number to be approved."""
    if not h:
        return ""

    def switch(what: str, title: str, sub: str, on: bool) -> str:
        return (f'<form method="post" action="/my/serving/hear"><input type="hidden" name="what" value="{what}">'
                f'<button class="sv-opt" type="submit" name="to" value="{"off" if on else "on"}" role="switch" '
                f'aria-checked="{"true" if on else "false"}"><span class="t"><b>{_e(title)}</b><small>{_e(sub)}</small></span>'
                f'<span class="sv-tg{" on" if on else ""}"><i></i></span></button></form>')
    rows = ""
    if h.get("phone_shown"):
        sub = ("Answer an ask right from the lock screen" if h.get("devices")
               else "Turn them on for this phone in Me, Notifications")
        rows += switch("phone", "Phone alerts", sub, bool(h.get("phone")))
    rows += switch("email", "An email copy", "Of every ask and the Saturday reminder", bool(h.get("email")))
    return ('<section class="sv-sec" aria-labelledby="sv-hr-h"><div class="sv-sh"><h2 id="sv-hr-h">How I hear</h2></div>'
            f'<div class="sv-card">{rows}</div>'
            '<p class="sv-lede">An ask always reaches you one way or another. Nothing comes between 9 PM and 7 AM.</p></section>')


def _range(a: Dict[str, Any]) -> str:
    s, e = datetime.fromisoformat(a["starts_on"]), datetime.fromisoformat(a["ends_on"])
    if s == e:
        return _day(s)
    return f"{_day(s)} – {e.day}" if (s.year, s.month) == (e.year, e.month) else f"{_day(s)} – {_day(e)}"


def _x() -> str:
    return ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
            'stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>')


# ─── The ask (board 7) ───────────────────────────────────────────────


def render_ask(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], v: Dict[str, Any]) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    at = v["at"]
    q = request.query_params
    changing = str(q.get("change") or "") == "1"
    leader = _first(v["leader"]) if v["leader"] else None
    if v["cover"]:
        kicker = f'{v["team"]} · {_first(v["cover_from"])} asked you to cover'
        head = f'Can you cover <em>{_e(v["place"])}?</em>'
    elif v["status"] == "offered":
        kicker = f'{v["team"]} · open to the team'
        head = f'Can you take <em>{_e(v["place"])}?</em>'
    else:
        kicker = f'{v["team"]} · {v["asked_by"]} asked' if v["asked_by"] else v["team"]
        head = f'Can you serve on <em>{_e(v["place"])}?</em>'
    title = "Sunday" if at.weekday() == 6 else at.strftime("%A")
    su = (f'Be there by {_clock(v["call_time"])} · service at {_at_clock(at)}' if v["call_time"] else f'Service at {_at_clock(at)}')
    top = (f'<div class="sv-top">{_date(at)}<span class="t"><span class="ti">{_e(title)}'
           f'{" · " + _e(v["title"]) if v["title"] != "Sunday service" else ""}</span><span class="su">{_e(su)}</span></span></div>')
    vid = v["id"]
    if v["past"]:
        state = '<p class="sv-lede" style="padding:0">That Sunday has passed. Thank you.</p>'
    elif v["status"] == "offered":
        state = (f'<div class="sv-ans one">{_form("/my/serving/take", {"id": vid}, ui.icon("check", 18) + "<span>Yes, I&#x27;ll take it</span>", "yes")}</div>')
    elif v["status"] == "yes" and not v["cover"] and not changing:
        state = (f'<div class="sv-done"><span class="disc" aria-hidden="true">{ui.icon("check", 26)}</span>'
                 f'<b>You\'re on for {_day(at)}.</b><small>Your yes is on {_e(v["team"])}\'s schedule.</small></div>'
                 f'<div class="sv-acts" style="justify-content:center"><a class="sv-btn hue" href="/my/serving/{_e(vid)}/pack">Your Sunday</a>'
                 f'<a class="sv-btn" href="/my/serving/{_e(vid)}.ics">Add to my calendar</a>'
                 f'<a class="sv-btn" href="/my/serving/{_e(vid)}?change=1">Change my answer</a></div>')
    elif v["status"] == "no" and not changing:
        note = v["note"]
        offered = note.startswith("Can do ")
        why_now = note.split(" · ")[-1] if " · " in note else ("" if offered else note)
        head2 = (f'Thanks. {_e(leader or "The church")} will see you offered {_e(note.split(" · ")[0][7:])}.' if offered
                 else "Thanks for saying so.")
        sub2 = ("They'll find someone for this Sunday, and you'll get an ask for that one if they need you. You don't have to find a sub."
                if offered else f'{_e(leader or "Whoever schedules")} finds someone. You don\'t have to text around. '
                                f'Want to say why? Only the people who schedule see it.')
        chips = "".join(
            f'<form method="post" action="/my/serving/why"><input type="hidden" name="id" value="{_e(vid)}">'
            f'<button type="submit" name="why" value="{_e(w if why_now != w else "")}" aria-pressed="{"true" if why_now == w else "false"}">{_e(w)}</button></form>'
            for w in ss.WHY)
        state = (f'<div class="sv-said"><b>{head2}</b><span>{sub2}</span>'
                 f'<div class="sv-why" role="group" aria-label="Why, if you want to say">{chips}</div>'
                 f'<a class="sv-btn" style="align-self:flex-start" href="/my/serving/{_e(vid)}?change=1">Change my answer</a></div>')
    else:
        yes = _form("/my/serving/answer", {"id": vid, "ans": "yes"}, ui.icon("check", 18) + "<span>Yes, I&#x27;ll serve</span>", "yes")
        no = _form("/my/serving/answer", {"id": vid, "ans": "no"}, "<span>Can&#x27;t that day</span>")
        other = (_form("/my/serving/answer", {"id": vid, "ans": "other"},
                       f'<span>I can&#x27;t, but I can do {_day(v["can_do"]["at"])}</span>', "sv-other") if v["can_do"] else "")
        state = f'<div class="sv-ans">{yes}{no}</div>{other}'
    with_rows = "".join(
        (f'<div class="sv-row ind"><span class="sv-av" aria-hidden="true">{_e(ui.initials(w["name"]))}</span>'
         f'<span class="t"><span class="ti">{_e(w["name"])}</span><span class="su">{_e(w["place"])}</span></span>'
         f'<span class="sv-st{"" if w["status"] == "yes" else " wait"}">{"said yes" if w["status"] == "yes" else "asked"}</span></div>')
        if w["name"] else
        (f'<div class="sv-row ind"><span class="sv-av open" aria-hidden="true">+</span>'
         f'<span class="t"><span class="ti">{_e(w["place"])}</span><span class="su">'
         f'{_e(_first(w["learning"][0]) + " is learning it") if w.get("learning") else "Nobody yet"}</span></span>'
         f'<span class="sv-st open">open</span></div>')
        for w in v["with"])
    with_html = (f'<section class="sv-sec h-teal" aria-labelledby="sv-on-h"><div class="sv-sh"><h2 id="sv-on-h">On with you</h2></div>'
                 f'<div class="sv-card">{with_rows}</div></section>') if with_rows else ""
    thread = (f'<section class="sv-sec" aria-label="{_e(v["team"])}"><div class="sv-card"><a class="sv-row" href="/my/groups/{_e(v["group_id"])}" '
              f'style="color:inherit;text-decoration:none"><span class="sv-av" style="border-radius:13px;width:36px;height:36px">{ui.icon("chat", 18)}</span>'
              f'<span class="t"><span class="ti">{_e(v["team"])}\'s group</span><span class="su">Your team, and its chat</span></span>'
              f'{ui.icon("chevron", 18)}</a></div></section>')
    body = f"""<style>{SERVING_CSS}</style><a class="mb-back" href="/my/serving">My serving</a>
<div class="sv-lt h-teal"><p class="sv-eb">{_e(kicker)}</p><h1 class="sv-h">{head}</h1></div>
{_flash(request)}
<section class="sv-hero h-teal" aria-label="Your answer">{top}{state}</section>
{with_html}{thread}"""
    return _shell(biz, site, "Serving", body, tab=_tab(), who=me)


def ics(biz: Dict[str, Any], v: Dict[str, Any]) -> str:
    """That Sunday as a calendar event: from the arrive-by time, two hours."""
    at = v["at"]
    if v["call_time"]:
        h, m = (int(x) for x in v["call_time"].split(":")[:2])
        start = at.replace(hour=h, minute=m)
        if start > at:
            start = at
    else:
        start = at
    from datetime import timedelta
    end = at + timedelta(hours=2)
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    church = (biz.get("name") or "Church").strip()
    clean = lambda s: str(s).replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Solutionist//Serving//EN", "BEGIN:VEVENT",
        f"UID:serve-{v['id']}@mysolutionist.app", f"DTSTAMP:{fmt(datetime.now(timezone.utc))}",
        f"DTSTART:{fmt(start)}", f"DTEND:{fmt(end)}",
        f"SUMMARY:{clean(v['place'])} · {clean(church)}",
        f"DESCRIPTION:{clean(v['team'])}. Service at {_at_clock(at)}.",
        "END:VEVENT", "END:VCALENDAR", ""])


def home_card(items: List[Dict[str, Any]]) -> str:
    """Home: the first ask waiting on this member, and how many more."""
    if not items:
        return ""
    more = len(items) - 1
    first = items[0]
    row = _ask_row(first)
    extra = (f'<a class="sv-btn soft" href="/my/serving" style="align-self:flex-start">'
             f'{more} more to answer</a>' if more > 0 else "")
    return f'<style>{SERVING_CSS}</style><div class="sv-home h-teal" style="display:flex;flex-direction:column;gap:8px">{row}{extra}</div>'


# ─── The Sunday pack (board 9) ───────────────────────────────────────


def _hm(hhmm: Optional[str]) -> str:
    """"13:05" → "1:05": a run of times reads without AM and PM."""
    if not hhmm:
        return ""
    h, m = hhmm.split(":")[:2]
    return f"{int(h) % 12 or 12}:{m}"


def _pk_song(s: Dict[str, Any]) -> str:
    """One song: its title and key, the team's note, who leads, the band's
    order. Never its words."""
    key = f'<span class="sv-pk-key">{_e(s["key"])}</span>' if s["key"] else ""
    note = f'<span class="su">{_e(s["note"])}</span>' if s["note"] else ""
    who = f'<span class="su">{_e(s["who"])}</span>' if s["who"] else ""
    parts = ('<span class="sv-pk-arr">' + "".join(f"<i>{_e(x)}</i>" for x in s["parts"]) + "</span>") if s["parts"] else ""
    return (f'<div class="sv-pk-song"><span class="sv-pk-n">{s["n"]}</span><span class="t">'
            f'<span class="ti"><span>{_e(s["title"])}</span>{key}</span>{note}{who}{parts}</span></div>')


def render_pack(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], p: Dict[str, Any]) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    at, role = p["at"], p["role"]
    day = at.strftime("%A, %B ") + str(at.day)
    roles = ""
    if len(p["roles"]) > 1:
        tabs = "".join(f'<a href="/my/serving/{_e(r["id"])}/pack"{" aria-current=\"page\"" if r["id"] == role["id"] else ""}>{_e(r["team"])}</a>'
                       for r in p["roles"])
        roles = f'<div class="sv-pk-as"><nav class="sv-seg" aria-label="See the pack as">{tabs}</nav></div>'
    due = f'Be there by {_hm(role["call"])}' if role["call"] else f'The service is at {_hm(at.strftime("%H:%M"))}'
    where = f'{role["place"]} · {role["team"]}'
    if role["here"]:
        here = (f'<div class="sv-pk-here done h-teal"><span class="sv-pk-disc" aria-hidden="true">{ui.icon("check", 20)}</span>'
                f'<span class="t"><b>You\'re here. Thank you!</b><small>{_e(_first(role["leader"]) if role["leader"] else "Your team")} sees you on the list.</small></span></div>')
    else:
        btn = (_form("/my/serving/here", {"id": role["id"]}, "<span>I&#x27;m here</span>", "sv-btn hue")
               if p["here_open"] else "")
        here = (f'<div class="sv-pk-here h-teal"><span class="sv-pk-disc" aria-hidden="true">{ui.icon("clock", 20)}</span>'
                f'<span class="t"><b>{_e(due)}</b><small>{_e(where)}</small></span>{btn}</div>')
    songs = ""
    if p["songs"]:
        rows = "".join(_pk_song(s) for s in p["songs"])
        count = f'{len(p["songs"])} song' + ("" if len(p["songs"]) == 1 else "s")
        songs = (f'<section class="sv-sec h-gold" aria-labelledby="pk-sg-h"><div class="sv-sh"><h2 id="pk-sg-h">The songs</h2>'
                 f'<span class="sv-pk-only">{count}</span></div><div class="sv-card">{rows}</div></section>')
    moments = ""
    if p["moments"]:
        rows = "".join(f'<div class="sv-pk-cue"><b>{_e(_hm(m["time"]))}</b><span>{_e(m["note"])}</span></div>' for m in p["moments"])
        moments = (f'<section class="sv-sec h-coral" aria-labelledby="pk-mo-h"><div class="sv-sh"><h2 id="pk-mo-h">Your moments</h2>'
                   f'<span class="sv-pk-only">{_e(role["team"])} only</span></div><div class="sv-card">{rows}</div></section>')
    order = ""
    if p["order"]:
        rows = "".join(f'<b>{_e(_hm(o["time"]))}</b><span>{_e(o["title"])}{" · " + _e(o["who"]) if o["who"] else ""}</span>'
                       for o in p["order"])
        order = (f'<section class="sv-sec" aria-labelledby="pk-or-h"><div class="sv-sh"><h2 id="pk-or-h">Today&#x27;s order</h2></div>'
                 f'<div class="sv-card"><div class="sv-pk-order">{rows}</div></div></section>')
    thread = (f'<section class="sv-sec"><a class="sv-ask h-teal" href="/my/groups/{_e(role["group_id"])}">'
              f'<span class="t"><b>{_e(role["team"])}&#x27;s group</b><small>Its board, its people and its chat</small></span>'
              f'{ui.icon("chevron", 18)}</a></section>')
    body = f"""<style>{SERVING_CSS}</style><a class="mb-back" href="/my/serving">Serving</a>
{_flash(request)}
<div class="sv-pk-when h-teal"><p class="sv-eb">{_e(day)} · {_e(_at_clock(at))}</p>
<h1>{_e(_first(me.get("name")))}, here&#x27;s your Sunday</h1></div>
{roles}
<section class="sv-sec" style="margin-top:16px" aria-label="When and where">{here}</section>
{songs}{moments}{order}{thread}"""
    return _shell(biz, site, "Your Sunday", body, tab=_tab(), who=me)


# ─── GET (through member_portal.serve) ───────────────────────────────


def _tab() -> str:
    """Serving lives under the Serve tab once Who sees what is on (member_app_ui.SERVE_TAB)."""
    import member_app_ui
    return "lead" if member_app_ui.serve_mode() else "connect"


async def serve(request: Request, church: Dict[str, Any], me: Dict[str, Any], sub: str):
    from member_portal import _page, _SECURE_HEADERS
    biz, site = church["business"], church.get("site")
    if not ss.on():
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    rest = sub[len("/my/serving"):].strip("/")
    try:
        if not rest:
            m = await asyncio.to_thread(ss.mine, biz, str(me["id"]))
            if m is None:
                return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
            sub_for = None
            want = str(request.query_params.get("sub") or "")
            hit = next((c for c in m["coming"] if c["id"] == want), None)
            if hit and not hit.get("swap_to"):
                cands = await asyncio.to_thread(ss.subs, biz, str(me["id"]), want)
                v = await asyncio.to_thread(ss.ask_view, biz, str(me["id"]), want)
                sub_for = {"id": want, "html": _subs_panel(hit, cands, v["leader"])}
            m["hear"] = await asyncio.to_thread(ss.hearing, biz, str(me["id"]))
            return _page(render_page(biz, site, request, me, m, sub_for))
        if rest.endswith("/pack"):
            aid = rest[:-5]
            if not _ID.match(aid):
                return RedirectResponse("/my/serving", status_code=303, headers=_SECURE_HEADERS)
            p = await asyncio.to_thread(ss.pack, biz, str(me["id"]), aid)
            return _page(render_pack(biz, site, request, me, p))
        aid, cal = (rest[:-4], True) if rest.endswith(".ics") else (rest, False)
        if not _ID.match(aid):
            return RedirectResponse("/my/serving", status_code=303, headers=_SECURE_HEADERS)
        v = await asyncio.to_thread(ss.ask_view, biz, str(me["id"]), aid)
        if cal:
            return Response(ics(biz, v), media_type="text/calendar; charset=utf-8",
                            headers={**_SECURE_HEADERS, "Content-Disposition": 'attachment; filename="serving.ics"'})
        return _page(render_ask(biz, site, request, me, v))
    except HTTPException as e:
        if e.status_code == 404:
            return RedirectResponse("/my/serving", status_code=303, headers=_SECURE_HEADERS)
        logger.warning("my serving read failed: %s", e.detail)
        from member_portal import _shell
        return _page(_shell(biz, site, "My serving", '<a class="mb-back" href="/my">Home</a>'
                            '<p class="mp-err" role="alert">Your serving couldn\'t load just now. Please try again in a moment.</p>',
                            tab="connect", who=me), 503)


# ─── POST ────────────────────────────────────────────────────────────


def _go(path: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    from urllib.parse import urlencode
    rest = path[len("/my/serving/"):].removesuffix("/pack") if path.startswith("/my/serving/") else ""
    target = path if path == "/my/serving" or _ID.match(rest) else "/my/serving"
    qs = urlencode({k: v for k, v in q.items() if v})
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


async def _act(request: Request, back_to_ask, fn, *fields: str):
    """Signed in, not a preview, not too fast; then fn(biz, cid, *values).
    back_to_ask: True goes back to the ask, "pack" to the Sunday pack."""
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    form = await request.form()
    vals = [str(form.get(f) or "") for f in fields]
    aid = vals[0] if fields and fields[0] == "id" else ""
    back = (f"/my/serving/{aid}" + ("/pack" if back_to_ask == "pack" else "")
            if back_to_ask and _ID.match(aid) else "/my/serving")
    if unavailable:
        return None, _go(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return None, _go("/my")
    if not ss.on():
        return None, _go("/my")
    import rate_limit
    biz = church["business"]
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return None, _go(back, err="slow")
    if fields and fields[0] == "id" and not _ID.match(aid):
        return None, _go("/my/serving")
    try:
        await asyncio.to_thread(fn, biz, str(me["id"]), *vals)
    except HTTPException as e:
        if e.status_code in (400, 409):
            return None, _go(back, err="said", msg=str(e.detail))
        if e.status_code == 404:
            return None, _go("/my/serving")
        return None, _go(back, err="error")
    return back, None


@router.post("/my/serving/answer", include_in_schema=False)
async def answer(request: Request):
    form = await request.form()
    ans = str(form.get("ans") or "")
    back, out = await _act(request, True, lambda b, c, aid, a: ss.answer(b, c, aid, a), "id", "ans")
    return out or _go(back, done=ans if ans in ("yes", "no", "other") else "")


@router.post("/my/serving/why", include_in_schema=False)
async def why(request: Request):
    back, out = await _act(request, True, ss.set_why, "id", "why")
    return out or _go(back, done="why")


@router.post("/my/serving/take", include_in_schema=False)
async def take(request: Request):
    back, out = await _act(request, True, ss.take, "id")
    return out or _go(back, done="took")


@router.post("/my/serving/sub", include_in_schema=False)
async def sub(request: Request):
    back, out = await _act(request, False, ss.ask_sub, "id", "sub")
    return out or _go("/my/serving", done="sub")


@router.post("/my/serving/sub/stop", include_in_schema=False)
async def stop_sub(request: Request):
    back, out = await _act(request, False, ss.stop_sub, "id")
    return out or _go("/my/serving", done="stopped")


@router.post("/my/serving/cant", include_in_schema=False)
async def cant(request: Request):
    back, out = await _act(request, False, ss.cant_make_it, "id")
    return out or _go("/my/serving", done="told")


@router.post("/my/serving/away", include_in_schema=False)
async def away(request: Request):
    back, out = await _act(request, False, ss.add_away, "start", "end")
    return out or _go("/my/serving", done="away")


@router.post("/my/serving/away/remove", include_in_schema=False)
async def unaway(request: Request):
    back, out = await _act(request, False, ss.drop_away, "id")
    return out or _go("/my/serving", done="unaway")


@router.post("/my/serving/often", include_in_schema=False)
async def often(request: Request):
    back, out = await _act(request, False, ss.set_often, "often")
    return out or _go("/my/serving", done="often")


@router.post("/my/serving/here", include_in_schema=False)
async def here(request: Request):
    back, out = await _act(request, "pack", ss.here, "id")
    return out or _go(back, done="here")


@router.post("/my/serving/hear", include_in_schema=False)
async def hear(request: Request):
    back, out = await _act(request, False, lambda b, c, what, to: ss.set_hearing(b, c, what, to == "on"), "what", "to")
    return out or _go("/my/serving", done="hear")
