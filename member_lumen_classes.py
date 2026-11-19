"""member_lumen_classes.py — Classes in the member app's new look ("Lumen").

Kevin, 2026-11-18, on today's Classes page: it "doesn't feel like an academy
feel". He approved the "clean Lumen" mock (version 29, accent level 2); this
is its CLASSES view, on the data today's page reads
(member_portal_classes.classes_for: academy_member_classes). Who sees it:
member_lumen.py (MEMBER_LUMEN). Off, the page is today's, byte for byte.

  /my/classes, pushed from Connect:
    - "Keep growing" under the academy's crest;
    - the next class night of a class you're in (or the one live now) on
      a soft gold pane, with the way into the classroom;
    - your path: each program's tracks as steps (done, you're here with
      how far, open to join, coming later) and the night it ends with;
    - your classes that aren't on a path;
    - classes you can join, one tap each.

The mock's academy name ("Grace Academy") is a name no church has chosen:
the crest says Classes. Nothing here is made up; a block with nothing in
it is left out.
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict, List, Optional


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


MEDAL = '<circle cx="12" cy="9" r="6"/><path d="m8.5 14-1.5 7 5-3 5 3-1.5-7"/>'


def _medal(size: int = 15) -> str:
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{MEDAL}</svg>')


def _join(course_id: str, label_id: str, text: str = "Join", cls: str = "lm-btn sm") -> str:
    return (f'<form method="post" action="/my/classes/join"><input type="hidden" name="course_id" value="{_e(course_id)}">'
            f'<button class="{cls}" type="submit" aria-describedby="{_e(label_id)}">{_e(text)}</button></form>')


def night(c: Dict[str, Any], tz: str) -> str:
    """The next class night (or the one live now) on the soft gold pane."""
    import member_portal_classes as mcl
    n = c["next"]
    live = bool(n.get("live"))
    head = " · ".join(x for x in (n.get("title"), n.get("lesson")) if x) or c.get("title") or "Class"
    program = c.get("program") or ""
    track = mcl.short_title(str(c.get("title") or ""), program) if program else (c.get("title") or "")
    facts = " · ".join(x for x in (program, track if track != head else "",
                                   f"with {c['teacher']}" if c.get("teacher") else "") if x)
    when = mcl.when_text(n.get("starts_at"), tz)
    kick = ('<span class="lm-kicker lm-nk is-live"><i class="lm-dotlive"></i>Live now</span>' if live else
            f'<span class="lm-kicker lm-nk">Next class · {_e(when)}</span>' if when else
            '<span class="lm-kicker lm-nk">Your next lesson</span>')
    go = (f'<a class="lm-btn gold sm" href="{_e(mcl.class_link(c["token"]))}">Join the class now</a>' if live else
          f'<a class="lm-btn gold sm" href="{_e(mcl.class_link(c["token"]))}">Open the lesson</a>')
    return (f'<section class="lm-night{" is-live" if live else ""}" aria-labelledby="lm-night-h">{kick}'
            f'<h2 class="lm-night-t" id="lm-night-h">{_e(head)}</h2>{f"<p>{_e(facts)}</p>" if facts else ""}{go}</section>')


def path(p: Dict[str, Any], mine: Dict[str, Dict[str, Any]], tz: str, *, one: bool) -> str:
    """A program's road as steps: done, you're here (with how far), open to
    join, coming later; then the night it ends with."""
    import member_app_ui as ui
    import member_portal_classes as mcl
    pid = f"lm-prog-{_e(p.get('id'))}"
    title = p.get("title") or "Your next steps"
    steps = []
    for k, t in enumerate(p.get("tracks") or [], 1):
        state = t.get("state") if t.get("state") in mcl._ROAD_STATE else "later"
        cid = str(t.get("course_id") or "")
        hid = f"lm-step-{_e(cid)}"
        name = mcl.short_title(str(t.get("title") or ""), p.get("title"))
        starts = mcl.date_text(t.get("starts_at"), tz)
        mc = mine.get(cid) or {}
        bar, act = "", ""
        if state == "done":
            line = "Finished" + (" · certificate earned" if mc.get("certificate") else "")
        elif state == "now":
            total, done = int(mc.get("total") or 0), int(mc.get("done") or 0)
            line = f"You're here · {done} of {total} lessons" if total else "You're here"
            if total:
                bar = (f'<span class="lm-pb" role="progressbar" aria-label="Lessons done" aria-valuemin="0" '
                       f'aria-valuemax="{total}" aria-valuenow="{done}"><i style="width:{round(100 * done / total)}%"></i></span>')
        else:
            line = mcl._ROAD_STATE[state] + (f" · starts {starts}" if starts else "")
            if t.get("teacher"):
                line += f" · {t['teacher']}"
        if state in ("done", "now") and t.get("token"):
            act = (f'<a class="lm-steplink" href="{_e(mcl.class_link(t["token"]))}" aria-describedby="{hid}">'
                   f'{"Open the class" if state == "now" else "Open"}{ui.icon("chevron", 14)}</a>')
        elif state == "open":
            act = _join(cid, hid)
        mark = ui.icon("check", 15) if state == "done" else str(k)
        steps.append(f'<li class="lm-step is-{state}"><span class="lm-node" aria-hidden="true">{mark}</span>'
                     f'<span class="lm-stept"><b id="{hid}">{_e(name)}</b><span>{_e(line)}</span>{bar}{act}</span></li>')
    if p.get("finish_title"):
        when = mcl.date_text(p.get("finish_at"), tz)
        steps.append(f'<li class="lm-step is-finish"><span class="lm-node" aria-hidden="true">{_medal()}</span>'
                     f'<span class="lm-stept"><b>{_e(p["finish_title"])}</b><span>{_e(when or "At the end of the road")}</span></span></li>')
    if one:
        head = (f'<div class="lm-sec"><h2 class="lm-h2" id="{pid}">Your path</h2>'
                f'<span class="lm-secnote">{_e(title)}</span></div>')
    else:
        head = f'<div class="lm-sec"><h2 class="lm-h2" id="{pid}">{_e(title)}</h2></div>'
    return (f'<section aria-labelledby="{pid}">{head}<ol class="lm-path" aria-label="{_e(title)}">'
            f'{"".join(steps)}</ol></section>')


def mono(title: Any) -> str:
    import member_app_ui as ui
    return f'<span class="lm-mono" aria-hidden="true">{_e(ui.initials(title))}</span>'


def mine_row(c: Dict[str, Any]) -> str:
    import member_portal_classes as mcl
    hid = f"lm-cls-{_e(c.get('course_id'))}"
    total, done = int(c.get("total") or 0), int(c.get("done") or 0)
    status = ("Finished" + (" · certificate earned" if c.get("certificate") else "")
              if c.get("status") == "completed" else f"{done} of {total} lessons" if total else "Just started")
    bar = ("" if c.get("status") == "completed" or not total else
           f'<span class="lm-pb" role="progressbar" aria-label="Lessons done" aria-valuemin="0" aria-valuemax="{total}" '
           f'aria-valuenow="{done}"><i style="width:{round(100 * done / total)}%"></i></span>')
    kick = c.get("program") or ""
    kicker = f'<span class="lm-cprog">{_e(kick)}</span>' if kick else ""
    return (f'<div class="lm-course">{mono(c.get("title"))}<span class="lm-coursed">{kicker}<b id="{hid}">{_e(c.get("title"))}</b>'
            f'<span>{_e(status)}</span>{bar}</span>'
            f'<a class="lm-btn sm ghost" href="{_e(mcl.class_link(c["token"]))}" aria-describedby="{hid}">Open</a></div>')


def open_row(c: Dict[str, Any], tz: str) -> str:
    import member_app_ui as ui
    import member_portal_classes as mcl
    hid = f"lm-copen-{_e(c.get('course_id'))}"
    starts = mcl.when_text(c.get("starts_at"), tz) if c.get("starts_at") else ""
    if not starts and c.get("drip") in ("weekly", "custom") and c.get("opens_from"):
        starts = f"Starts {mcl.date_text(c.get('opens_from'), tz)}"
    soon = starts.split(" ")[0] in ("Tonight", "Today", "Tomorrow")
    when = (f"First class {starts[0].lower() + starts[1:] if soon else starts}" if starts and not starts.startswith("Starts")
            else starts) or "Start any time"
    facts = " · ".join(x for x in (f"{c['lessons']} lessons" if c.get("lessons") else "", when, c.get("teacher")) if x)
    kick = c.get("program") or ""
    if kick and c.get("position") is not None:
        kick = f"{kick} · Track {int(c['position']) + 1}"
    sample = ui.sample_tag() if c.get("sample") else ""
    about = f'<span class="lm-about">{_e(c["about"])}</span>' if c.get("about") else ""
    return (f'<div class="lm-course">{mono(c.get("title"))}<span class="lm-coursed">'
            f'{f"<span class=lm-cprog>{_e(kick)}</span>" if kick else ""}<b id="{hid}">{_e(c.get("title"))}{sample}</b>'
            f'<span>{_e(facts)}</span>{about}</span>{_join(str(c.get("course_id") or ""), hid)}</div>')


def render(biz, site, request, data: Optional[Dict[str, Any]], who=None) -> str:
    """Connect › Classes in the new look."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_church as mpc
    from member_portal import _shell
    parts: List[str] = [mpc.connect_head(biz, "classes"), mpc._flash(request)]
    if data is None:
        parts.append('<p class="mp-err" role="alert" style="margin-top:22px">Classes couldn\'t load just now. '
                     'Please try again in a moment.</p>')
    elif not data["mine"] and not data["open"] and not data["programs"]:
        church = biz.get("name") or "the church"
        parts.append(f'<section class="lm-cempty"><span class="lm-aic">{lm.ic("cap", 20)}</span>'
                     f'<h2 class="lm-cempty-t">No classes to join <em>right now</em></h2>'
                     f'<p>When {_e(church)} opens a class, it shows up here and you can join it with one tap.</p></section>')
    else:
        tz = data.get("tz") or "UTC"
        mine = data["mine"]
        by_id = {str(c.get("course_id")): c for c in mine}
        nxt = next((c for c in mine if c.get("status") == "active" and c.get("next") and c.get("token")), None)
        if any(samples.is_sample(x) for x in mine + data["open"]):
            parts.append(ui.sample_hint(samples.WHERE["classes"]))
        if nxt:
            parts.append(night(nxt, tz))
        programs = data["programs"]
        on_road = {str(t.get("course_id")) for p in programs for t in (p.get("tracks") or [])}
        for p in programs:
            parts.append(path(p, by_id, tz, one=len(programs) == 1))
        rows = "".join(mine_row(c) for c in mine if c.get("token") and str(c.get("course_id")) not in on_road)
        if rows:
            parts.append(f'<section aria-labelledby="lm-mine-h">{lm.section("Your classes", hid="lm-mine-h")}'
                         f'<div class="lm-courses">{rows}</div></section>')
        if data["open"]:
            rows = "".join(open_row(c, tz) for c in data["open"])
            parts.append(f'<section aria-labelledby="lm-copen-h">{lm.section("Classes you can join", hid="lm-copen-h")}'
                         f'<div class="lm-courses">{rows}</div><p class="lm-cfoot">Joining puts the class here, '
                         f'and your teacher sees you on the list.</p></section>')
    return _shell(biz, site, "Classes", "".join(p for p in parts if p), tab="classes", who=who)


# ─── the look ────────────────────────────────────────────────────────
# Accent level 2: gold for the academy (the crest, the next class night's
# pane, the path's line and nodes, the course marks); the church's colour on
# Join.
CSS = """
/* Classes (member_lumen_classes) */
body.lm{--lm-gold-9:var(--s1);}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm{--lm-gold-9:color-mix(in srgb,var(--gold-ink) 9%,var(--bg));}
}
body.lm .lm-night{margin-top:22px;padding:20px;border-radius:18px;background:var(--lm-gold-9);}
body.lm .lm-nk{display:flex;align-items:center;gap:8px;color:var(--lm-gold);}
body.lm .lm-nk.is-live{color:#c4162a;}
body.lm .lm-night-t{margin:10px 0 4px;font:400 28px/1.05 var(--mb-serif);letter-spacing:-.02em;color:var(--fg);}
body.lm .lm-night p{margin:0 0 16px;font:400 14px/1.45 var(--mb-ui);color:var(--fg2);}
body.lm .lm-secnote{font:500 12.5px/1.2 var(--mb-ui);color:var(--fg3);text-align:right;}
body.lm .lm-path{list-style:none;margin:0;padding:0 0 0 2px;}
body.lm .lm-step{position:relative;display:grid;grid-template-columns:32px minmax(0,1fr);gap:14px;padding-bottom:22px;}
body.lm .lm-step::before{content:"";position:absolute;left:15px;top:32px;bottom:0;width:2px;background:var(--s3);}
body.lm .lm-step:last-child::before{display:none;}
body.lm .lm-step.is-done::before{background:var(--lm-gold);}
body.lm .lm-node{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:var(--bg);color:var(--fg3);
  font:700 13px/1 var(--mb-ui);box-shadow:inset 0 0 0 1.5px var(--s3);}
body.lm .lm-step.is-done .lm-node{background:var(--lm-gold);color:#fff;box-shadow:none;}
body.lm .lm-step.is-now .lm-node{color:var(--lm-gold);box-shadow:inset 0 0 0 2px var(--lm-gold);}
body.lm .lm-stept{min-width:0;}
body.lm .lm-stept>b{display:block;padding-top:5px;font:650 16px/1.2 var(--mb-ui);}
body.lm .lm-stept>span{display:block;margin-top:4px;font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-step.is-later .lm-stept>b{color:var(--fg2);}
body.lm .lm-stept .lm-pb{margin-top:10px;}
body.lm .lm-stept .lm-pb i,body.lm .lm-coursed .lm-pb i{background:var(--lm-gold);}
body.lm .lm-stept form{margin-top:10px;}
body.lm .lm-steplink{display:inline-flex;align-items:center;gap:2px;margin-top:8px;color:var(--acc);font:650 13.5px/1 var(--mb-ui);text-decoration:none;}
body.lm .lm-courses{border-top:1px solid var(--lm-line);}
body.lm .lm-course{display:grid;grid-template-columns:52px minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px 0;
  border-bottom:1px solid var(--lm-line);}
body.lm .lm-mono{width:52px;height:62px;border-radius:8px;display:grid;place-items:center;font:italic 400 22px/1 var(--mb-serif);
  color:#2a1a02;background:#ECCB7A;}
body.lm .lm-coursed{min-width:0;}
body.lm .lm-coursed>b{display:block;font:650 15px/1.2 var(--mb-ui);}
body.lm .lm-coursed>span:not(.lm-pb){display:block;margin-top:4px;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-coursed>.lm-cprog{margin:0 0 4px;font:700 10px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--lm-gold);}
body.lm .lm-coursed>.lm-about{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:var(--fg3);}
body.lm .lm-coursed .lm-pb{margin-top:8px;}
body.lm .lm-course form{flex:none;}
body.lm .lm-cfoot{margin:14px 0 0;font:400 12.5px/1.45 var(--mb-ui);color:var(--fg3);}
body.lm .lm-cempty{margin-top:28px;padding:22px 20px;border-radius:18px;background:var(--lm-gold-9);}
body.lm .lm-cempty .lm-aic{color:var(--lm-gold);background:var(--bg);}
body.lm .lm-cempty-t{margin:14px 0 6px;font:400 26px/1.1 var(--mb-serif);letter-spacing:-.015em;color:var(--fg);}
body.lm .lm-cempty-t em{font-style:italic;color:var(--lm-gold);}
body.lm .lm-cempty p{margin:0;font:400 14.5px/1.5 var(--mb-ui);color:var(--fg2);}
body.lm .lm-steplink:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
"""
