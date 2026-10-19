"""
member_portal_devotionals.py — Plans & devotionals in the member app.

Round three, part 4 (Kevin approved the "Member App, Round Three" canvas,
boards 10 and 11, 2026-10-19; "reading plans plus church-made personal
devotionals"; yes to Listen the same day):

    /my/bible/plans                 Plans & devotionals: what the church is
                                    reading this week, its devotionals, its
                                    reading plan, and a plan of your own
    /my/bible/plans?show=church|reading|yours
    /my/bible/plans/<devotional>    a devotional: its welcome, its daily
                                    practices, its days, Start
    /my/bible/plans/<devotional>/<n>   a day: the scripture, the words, Pray,
                                    Do today, Together, the daily checklist,
                                    a private journal, Listen, Mark done
    /my/bible/plans/<reading plan>  a reading plan the member started

    POST /my/bible/plans/start      form {plan}: start a plan of your own
    POST /my/bible/plans/stop       form {plan}: stop it
    POST /my/bible/plans/day        JSON {devotional, day, checks?, journal?,
                                    done?}: the member's own day
    POST /my/bible/plans/listen     devotional_voice.py

A devotional the church dated opens a day a day from its start, everyone on
the same page; one with no date opens a day a day from the day a member
starts it. A member can catch up on any open day and mark it done; a day
that isn't open yet shows its name and when it opens, and nothing to tap.
The journal is the member's own (no staff route reads it), like their
Bible notes. The owner's preview shows every day of what's published and
saves nothing.

Home's Today card gets the member's devotional for today (today_row), and
the Bible tab its "From <church>" and "Reading plans" (bible_sections).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

import devotionals as dv
import reading_plans as rp
import sb_clients

logger = logging.getLogger("member_portal_devotionals")
router = APIRouter(tags=["member-portal"])

JOURNAL_MAX = 4000
SHOWS = (("all", "All"), ("church", ""), ("reading", "Reading plans"), ("yours", "Yours"))
DEFAULT_JOURNAL = "What is God showing you today?"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _who(business_id: str, contact_id: str) -> str:
    return f"business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"


# ─── a member's plans and days ───────────────────────────────────────


def starts(business_id: str, contact_id: str) -> Optional[Dict[str, date]]:
    """{plan: started_on} for the plans the member started on their own
    ("reading:gospels-30", "devotional:<id>"), or None."""
    rows = sb_clients.sb_get_as_service(
        f"/member_plan_starts?{_who(business_id, contact_id)}&select=plan,started_on&limit=200")
    if not isinstance(rows, list):
        return None
    out = {}
    for r in rows:
        try:
            out[str(r["plan"])] = date.fromisoformat(str(r["started_on"]))
        except (KeyError, ValueError):
            continue
    return out


def started_on(business_id: str, contact_id: str, dev: Dict[str, Any]) -> Union[date, None, bool]:
    """The day the member started a devotional with no church date: a date,
    None (not started, or the church dated it), or False (the read failed)."""
    if dev.get("starts_on"):
        return None
    got = starts(business_id, contact_id)
    if got is None:
        return False
    return got.get(f"devotional:{dev['id']}")


def progress(business_id: str, contact_id: str, devotional_id: str) -> Optional[Dict[int, Dict[str, Any]]]:
    """{day: {done_at, checks, journal}} for one devotional, or None."""
    rows = sb_clients.sb_get_as_service(
        f"/devotional_progress?{_who(business_id, contact_id)}&devotional_id=eq.{_q(devotional_id)}"
        "&select=day,done_at,checks,journal&limit=100")
    if not isinstance(rows, list):
        return None
    return {int(r["day"]): r for r in rows}


def done_days(business_id: str, contact_id: str) -> Optional[Dict[str, set]]:
    """{devotional id: the days done, or touched} across every devotional."""
    rows = sb_clients.sb_get_as_service(
        f"/devotional_progress?{_who(business_id, contact_id)}&select=devotional_id,day,done_at&limit=2000")
    if not isinstance(rows, list):
        return None
    out: Dict[str, set] = {}
    for r in rows:
        out.setdefault(f"t:{r['devotional_id']}", set()).add(int(r["day"]))
        if r.get("done_at"):
            out.setdefault(str(r["devotional_id"]), set()).add(int(r["day"]))
    return out


def start(business_id: str, contact_id: str, plan: str, on: date) -> bool:
    rows = sb_clients.sb_post_as_service(
        "/member_plan_starts?on_conflict=business_id,contact_id,plan",
        {"business_id": business_id, "contact_id": contact_id, "plan": plan, "started_on": on.isoformat()},
        prefer="return=representation,resolution=ignore-duplicates")
    return isinstance(rows, list)


def stop(business_id: str, contact_id: str, plan: str) -> bool:
    return bool(sb_clients.sb_delete_as_service(f"/member_plan_starts?{_who(business_id, contact_id)}&plan=eq.{_q(plan)}"))


def save_day(business_id: str, contact_id: str, devotional_id: str, day: int,
             change: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Merge one change into the member's day. The row, or None."""
    key = (f"/devotional_progress?{_who(business_id, contact_id)}&devotional_id=eq.{_q(devotional_id)}"
           f"&day=eq.{int(day)}")
    now = sb_clients.sb_get_as_service(f"{key}&select=done_at,checks,journal")
    if not isinstance(now, list):
        return None
    row = {"done_at": None, "checks": [], "journal": "", **(now[0] if now else {})}
    stamp = datetime.now(timezone.utc).isoformat()
    if "done" in change:
        row["done_at"] = (row.get("done_at") or stamp) if change["done"] else None
    if "checks" in change:
        row["checks"] = change["checks"]
    if "journal" in change:
        row["journal"] = change["journal"]
    saved = sb_clients.sb_post_as_service(
        "/devotional_progress?on_conflict=business_id,contact_id,devotional_id,day",
        {"business_id": business_id, "contact_id": contact_id, "devotional_id": devotional_id, "day": int(day),
         "done_at": row["done_at"], "checks": list(row["checks"] or []), "journal": row["journal"] or "",
         "updated_at": stamp},
        prefer="return=representation,resolution=merge-duplicates")
    if not isinstance(saved, list) or not saved:
        return None
    return saved[0]


def own_plan(key: str, started: Optional[date]) -> Optional[Dict[str, Any]]:
    """A reading plan the member started, in reading_plans' shape."""
    if key not in rp.PLANS or not started:
        return None
    meta = rp.PLANS[key]
    return {"key": key, "title": meta["title"], "start": started, "days": meta["days"], "own": True}


def own_today(plan: Dict[str, Any], today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Today's reading on a plan of the member's own (Home's row), or None."""
    n = rp.day_number(plan, today)
    if not n:
        return None
    reading = rp.schedule(plan["key"])[n - 1]
    return {"day": n, "of": plan["days"], "label": rp.label(reading), "href": rp.href(reading),
            "title": f"Your plan · {plan['title']}", "key": plan["key"], "start": plan["start"].isoformat(),
            "own": True}


# ─── where a member is in a devotional ───────────────────────────────


def state(dev: Dict[str, Any], started: Optional[date], done: set, today: Optional[date] = None,
          *, preview: bool = False) -> Dict[str, Any]:
    """{kind, start, upto, now, done, count, next} for a member and a
    devotional. kind: new (not started; no church date), upcoming (the
    church's date hasn't come), running, over (past its last day, not all
    done), finished. A preview sees every day open."""
    today = today or date.today()
    count = int(dev.get("day_count") or len(dev.get("days") or []))
    begin = dv.run_start(dev, started)
    upto = count if preview else dv.open_upto(begin, count, today)
    now = dv.day_number(begin, count, today)
    done = {d for d in done if 1 <= d <= count}
    if count and len(done) >= count:
        kind = "finished"
    elif dev.get("starts_on") and today < dev["starts_on"]:
        kind = "upcoming"
    elif not begin:
        kind = "new"
    elif now:
        kind = "running"
    else:
        kind = "over"
    nxt = next((d for d in range(1, upto + 1) if d not in done), None)
    return {"kind": kind, "start": begin, "upto": upto, "now": now, "done": done, "count": count, "next": nxt,
            "preview": preview}


def _date(d: date, long: bool = False) -> str:
    return f"{d.strftime('%A' if long else '%a')}, {d.strftime('%B' if long else '%b')} {d.day}"


def chip(st: Dict[str, Any]) -> Tuple[str, str]:
    """(words, class) for a devotional's state on a list."""
    k = st["kind"]
    if k == "finished":
        return "You finished it", "is-done"
    if k == "upcoming":
        return f"Starts {_date(st['start'])}", ""
    if k == "new":
        return "Start", "is-start"
    if k == "running":
        return f"Day {st['now']} of {st['count']}", ""
    return (f"{len(st['done'])} of {st['count']} done", "") if st["done"] else ("Read it any time", "")


def _href(dev: Dict[str, Any], n: Optional[int] = None) -> str:
    return f"/my/bible/plans/{dev['id']}" + (f"/{int(n)}" if n else "")


def _target(dev: Dict[str, Any], st: Dict[str, Any]) -> str:
    """Where tapping a devotional goes: today's day (or the first one not
    done) once it's open, else the devotional itself."""
    if st["kind"] in ("new", "upcoming") or not st["upto"]:
        return _href(dev)
    if st["kind"] == "finished":
        return _href(dev)
    n = st["now"] if st["now"] and st["now"] not in st["done"] else (st["next"] or st["now"] or 1)
    return _href(dev, n)


def _cover(biz, site, dev: Dict[str, Any], pool: List[str], used: Optional[set], cls: str = "",
           night: bool = False) -> str:
    """The devotional's picture: the one the church chose for it
    (member_app_pictures, "devotional:<id>"), a photo named for it, or its
    default picture."""
    import member_app_photos as photos
    import member_app_ui as ui
    url, look = photos.choose(biz, f"devotional:{dev['id']}", pool, title=dev.get("title") or "", look="church",
                              used=used)
    return ui.picture(url, look, "word", cls, night=night)


def _dots(st: Dict[str, Any], dev: Dict[str, Any], *, links: bool, cls: str = "dv-strip") -> str:
    """The days as circles: done (a tick), today's (a ring), open, not open
    yet. `links`: an open day is a link to it."""
    import member_app_ui as ui
    from member_portal import _e
    out = []
    for n in range(1, st["count"] + 1):
        state_cls = " is-done" if n in st["done"] else ""
        if n == (st["now"] if not st.get("here") else st["here"]):
            state_cls += " is-now"
        mark = ui.icon("check", 15) if n in st["done"] else str(n)
        when = dv.day_on(st["start"], n).strftime("%a") if st["start"] else f"Day {n}"
        label = f"Day {n}{', done' if n in st['done'] else ''}"
        inner = f'<span class="dv-c">{mark}</span><span class="dv-w">{_e(when)}</span>'
        if links and n <= st["upto"]:
            cur = ' aria-current="page"' if st.get("here") == n else ""
            out.append(f'<a class="dv-d{state_cls}" href="{_href(dev, n)}" aria-label="{_e(label)}"{cur}>{inner}</a>')
        else:
            out.append(f'<span class="dv-d{state_cls} is-shut" aria-label="{_e(label)}">{inner}</span>')
    wide = " is-wide" if st["count"] > 7 else ""
    if not links:   # inside a card that is itself the link: a picture of the days
        return f'<span class="{cls}{wide}" aria-hidden="true" style="--n:{min(st["count"], 7)}">{"".join(out)}</span>'
    return f'<nav class="{cls}{wide}" aria-label="The days" style="--n:{min(st["count"], 7)}">{"".join(out)}</nav>'


def _verse_line(ref_text: str, tr: str, limit: int = 1) -> Tuple[str, str, str]:
    """(the scripture's words as HTML, its label, the chapter link) — the
    words '' when the reference can't be read."""
    import bible_text as bt
    import member_portal_bible as mpb
    found = bt.find_refs(ref_text or "")
    if not found:
        return "", str(ref_text or ""), ""
    ref = found[0][2]
    verses = bt.verses(ref, tr) or []
    words = " ".join(mpb._verse_html(t, tr) for _, _, t in verses[:limit])
    more = "…" if len(verses) > limit else ""
    return (f"“{words}{more}”" if words else ""), ref.label(), f"{ref.href()}#v{ref.start or 1}"


# ─── pages ───────────────────────────────────────────────────────────


def render_plans(biz, site, me, *, devs: Optional[List[Dict[str, Any]]], done: Optional[Dict[str, set]],
                 mine: Optional[Dict[str, date]], church_today: Optional[Dict[str, Any]], church_done: Optional[set],
                 show: str = "all", preview: bool = False, tr: str = "kjv", today: Optional[date] = None,
                 flash: str = "") -> str:
    """Plans & devotionals (approved board 10)."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    today = today or date.today()
    short = mpc._short_name(biz.get("name") or "") or "your church"
    show = show if show in dict(SHOWS) else "all"
    labels = dict(SHOWS)
    labels["church"] = f"From {short}"
    chips = "".join(f'<a href="/my/bible/plans?show={k}"{" aria-current=page" if k == show else ""}>{_e(labels[k])}</a>'
                    for k, _ in SHOWS)
    pool = photos.photos(biz, site)
    used: set = set()
    mine = mine or {}
    sts = [(d, state(d, mine.get(f"devotional:{d['id']}"), (done or {}).get(str(d["id"]), set()), today,
                     preview=preview)) for d in (devs or [])]
    touched = {k[2:] for k in (done or {}) if k.startswith("t:")}

    def yours(d, st):
        return f"devotional:{d['id']}" in mine or str(d["id"]) in touched

    parts: List[str] = []
    if devs is None:
        parts.append('<p class="mp-err" role="alert">The church\'s devotionals couldn\'t load just now. '
                     'Please try again in a moment.</p>')
    feat = next(((d, st) for d, st in sts if st["kind"] == "running" and d.get("starts_on")), None) or \
        next(((d, st) for d, st in sts if st["kind"] == "running"), None)
    if show in ("all", "church") and feat:
        d, st = feat
        day = (d.get("days") or [{}])[st["now"] - 1] if d.get("days") else {}
        verse, label, _ = _verse_line(day.get("scripture") or "", tr)
        line = (f'<span class="dv-vl">{verse}<b>{_e(label)}</b></span>' if verse else "")
        segs = "".join(f'<span class="dv-seg{" is-done" if n in st["done"] else ""}{" is-now" if n == st["now"] else ""}">'
                       f'</span>' for n in range(1, st["count"] + 1))
        kick = f"{st['count']}-day devotional" + (f" · {d['kind']}" if d.get("kind") else "")
        heading = f"This week at {short}" if d.get("starts_on") else "Keep going"
        parts.append(f"""<section class="h-brand" aria-labelledby="dv-now-h">{ui.section(heading, hid="dv-now-h")}
<a class="dv-now" href="{_target(d, st)}"><span class="dv-cv">{_cover(biz, site, d, pool, used, "dv-cv-p", night=True)}
<span class="dv-cv-in"><span class="dv-glass">{_e(kick)}</span><strong>{_e(d['title'])}</strong>
{f'<span>By {_e(d["author"])}</span>' if d.get("author") else ''}</span></span>
<span class="dv-now-b">{line}<span class="dv-row"><span class="dv-segs" role="img" aria-label="Day {st['now']} of {st['count']}">{segs}</span>
<span class="mp-go dv-sm">Day {st['now']}</span></span></span></a></section>""")
    if show in ("all", "church", "yours"):
        rows = []
        for d, st in sts:
            if feat and d is feat[0] and show != "yours":
                continue
            if show == "yours" and not yours(d, st):
                continue
            words, cls = chip(st)
            sub = (d.get("kind") or "Devotional") + f" · {st['count']} day{'' if st['count'] == 1 else 's'}"
            rows.append(f'<a class="dv-li" href="{_target(d, st)}"><span class="dv-th">{_cover(biz, site, d, pool, used, "dv-th-p")}</span>'
                        f'<span class="dv-t"><strong>{_e(d["title"])}</strong><span>{_e(sub)}</span>'
                        f'<span class="mb-chip dv-chip {cls}">{ui.icon("check", 12) if cls == "is-done" else ""}{_e(words)}</span></span></a>')
        if rows:
            parts.append(f'<section class="h-brand" aria-labelledby="dv-lib-h">'
                         f'{ui.section("Yours" if show == "yours" else f"From {short}", hid="dv-lib-h")}'
                         f'<div class="dv-lib">{"".join(rows)}</div></section>')
    if show in ("all", "reading", "yours"):
        parts.append(_reading_block(church_today, church_done, mine, show=show, today=today))
    body = "".join(p for p in parts if p) or (
        '<p class="mp-muted" style="margin-top:24px">Nothing here yet. Start a reading plan or one of the church\'s '
        'devotionals, and it shows here.</p>' if show == "yours" else
        '<p class="mp-muted" style="margin-top:24px">Nothing here yet.</p>')
    return _shell(biz, site, "Plans & devotionals", f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
<p class="dv-eb">Read with your church</p>
<div class="mb-lt"><h1>Plans <em>&amp; devotionals</em></h1></div>
<nav class="bb-filters" aria-label="Show">{chips}</nav>
{flash}
{body}""", tab="bible", who=me)


def _reading_block(church_today: Optional[Dict[str, Any]], church_done: Optional[set],
                   mine: Dict[str, date], *, show: str, today: date) -> str:
    """Reading plans: the church's (while it runs), then the four plans,
    each started on the member's own day or ready to start."""
    import member_app_ui as ui
    from member_portal import _e
    out = []
    if church_today and show != "yours" or (church_today and church_done):
        t = church_today
        done = church_done or set()
        missed = len([d for d in range(1, t["day"]) if d not in done])
        sub = f"Day {t['day']} today" + (f" · {missed} day{'' if missed == 1 else 's'} to catch up" if missed else "")
        ring = ui.ring(len(done), t["of"], 54, label=f'{len(done)}<small>/{t["of"]}</small>')
        out.append(f'<div class="dv-cp"><div class="dv-cp-top">{ring}<span class="dv-t"><small>The church is reading</small>'
                   f'<strong>{_e(t["title"])}</strong><span>{_e(sub)}</span></span></div>'
                   f'<div class="dv-acts"><a class="mp-go dv-sm dv-hue" href="{_e(t["href"])}">Read today</a>'
                   f'<a class="mp-go mp-go-2 dv-sm" href="/my/reading">{"Catch up" if missed else "See the plan"}</a></div></div>')
    rows = []
    for key, meta in rp.PLANS.items():
        started = mine.get(f"reading:{key}")
        if show == "yours" and not started:
            continue
        box = f'<span class="dv-len"><b>{meta["days"]}</b><small>days</small></span>'
        if started:
            plan = own_plan(key, started)
            n = rp.readable_upto(plan, today)
            now = rp.day_number(plan, today)
            sub = (f"You're on day {now} · {rp.label(rp.schedule(key)[now - 1])}" if now else
                   ("It's finished" if n >= plan["days"] else "It starts today"))
            rows.append(f'<a class="dv-pl" href="/my/bible/plans/{key}">{box}<span class="dv-t"><strong>{_e(meta["title"])}</strong>'
                        f'<span>{_e(sub)}</span></span><span class="mb-chip dv-yours">Yours</span></a>')
        else:
            rows.append(f'<div class="dv-pl">{box}<span class="dv-t"><strong>{_e(meta["title"])}</strong>'
                        f'<span>{_e(meta["about"])}</span></span><form method="post" action="/my/bible/plans/start">'
                        f'<input type="hidden" name="plan" value="reading:{key}">'
                        f'<button class="dv-start" type="submit" aria-label="Start {_e(meta["title"])}">Start</button></form></div>')
    if rows:
        if out or show != "yours":
            out.append('<p class="dv-eb dv-eb-in">' + ("Your plans" if show == "yours" else "Start one on your own") + '</p>')
        out.append(f'<div class="dv-card">{"".join(rows)}</div>')
    if not out:
        return ""
    return f'<section class="h-gold" aria-labelledby="dv-rp-h">{ui.section("Reading plans", hid="dv-rp-h")}{"".join(out)}</section>'


def render_devotional(biz, site, me, dev: Dict[str, Any], st: Dict[str, Any], *, flash: str = "") -> str:
    """One devotional: its picture, its welcome, how far you are, its
    daily practices and its days."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    pool = photos.photos(biz, site)
    k = st["kind"]
    if k == "new":
        go = (f'<form method="post" action="/my/bible/plans/start"><input type="hidden" name="plan" value="devotional:{dev["id"]}">'
              f'<button class="mp-go" type="submit"{" disabled" if st["preview"] else ""}>Start today</button></form>'
              f'<p class="mp-muted dv-fine">A day opens each day from the day you start: {st["count"]} '
              f'day{"" if st["count"] == 1 else "s"}.</p>')
    elif k == "upcoming":
        go = (f'<div class="mp-card dv-when">{ui.icon("calendar", 20)}<span>{_e(mpc._short_name(biz.get("name") or "") or "The church")} '
              f'starts it together on {_e(_date(st["start"], True))}. Day 1 opens that morning.</span></div>')
    elif k == "finished":
        go = (f'<div class="dv-donecard h-teal"><span class="dv-disc">{ui.icon("check", 18)}</span><span class="dv-t">'
              f'<strong>You finished it</strong><span>Every day is still here to read again.</span></span></div>')
    else:
        n = st["now"] if st["now"] and st["now"] not in st["done"] else (st["next"] or st["upto"] or 1)
        missed = len([d for d in range(1, (st["now"] or st["upto"] + 1)) if d not in st["done"]])
        go = (f'<a class="mp-go" href="{_href(dev, n)}">Read day {n}</a>'
              + (f'<p class="mp-muted dv-fine">{missed} day{"" if missed == 1 else "s"} to catch up.</p>' if missed else ""))
    practices = ""
    if dev.get("practices"):
        practices = (f'{ui.section("Every day")}<ul class="dv-prac">' + "".join(
            f'<li><span class="dv-dot" aria-hidden="true"></span><span class="dv-t"><strong>{_e(p["title"])}</strong>'
            f'{f"<span>{_e(p.get("sub"))}</span>" if p.get("sub") else ""}</span></li>' for p in dev["practices"]) + "</ul>")
    rows = []
    for n, day in enumerate(dev.get("days") or [], 1):
        mark = ui.icon("check", 15) if n in st["done"] else str(n)
        shut = n > st["upto"]
        when = _date(dv.day_on(st["start"], n)) if st["start"] else ""
        if shut:
            when = f"Opens {when}" if when else "Opens after you start"
        sub = " · ".join(p for p in (when, day.get("scripture") or "") if p)
        inner = (f'<span class="dv-c">{mark}</span><span class="dv-t"><strong>{_e(day.get("title") or f"Day {n}")}</strong>'
                 f'<span>{_e(sub)}</span></span>')
        if not shut:
            rows.append(f'<a class="dv-dl{" is-done" if n in st["done"] else ""}" href="{_href(dev, n)}">{inner}{ui.icon("chevron", 16)}</a>')
        else:
            rows.append(f'<div class="dv-dl is-shut">{inner}</div>')
    about = "".join(f"<p>{_e(p)}</p>" for p in dv.paragraphs(dev.get("about") or ""))
    kick = f"{st['count']}-day devotional" + (f" · {dev['kind']}" if dev.get("kind") else "")
    return _shell(biz, site, dev["title"], f"""<a class="mb-back" href="/my/bible/plans">{ui.icon('back', 16)}Plans</a>
{flash}
<section class="dv-hero" aria-labelledby="dv-h">{_cover(biz, site, dev, pool, None, "dv-cv-p", night=True)}
<div class="dv-cv-in"><span class="dv-glass">{_e(kick)}</span><h1 id="dv-h">{_e(dev['title'])}</h1>
{f'<p>By {_e(dev["author"])}</p>' if dev.get("author") else ''}</div></section>
<div class="dv-go">{go}</div>
{f'<div class="dv-about">{about}</div>' if about else ''}
{practices}
{ui.section("The days")}
<div class="dv-days">{"".join(rows)}</div>""", tab="bible", who=me)


DAY_JS = """<script>(function(){
var root=document.getElementById('dv-day');if(!root)return;
var dev=root.getAttribute('data-dev'),day=+root.getAttribute('data-day'),live=root.getAttribute('data-live')==='1';
var toast=document.getElementById('dv-toast'),timer=null;
if(toast)document.body.appendChild(toast);
function say(t){if(!toast)return;toast.textContent=t;toast.hidden=false;clearTimeout(timer);timer=setTimeout(function(){toast.hidden=true;},2200);}
function send(change){var body=Object.assign({devotional:dev,day:day},change);
 return fetch('/my/bible/plans/day',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(body)})
 .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
 .catch(function(d){say(d&&d.error==='slow'?'That\\'s a lot at once. Wait a minute.':'That didn\\'t save. Try again.');return null;});}
var list=root.querySelector('.dv-check'),count=root.querySelector('.dv-check-n'),pending=null;
function ticked(){return Array.prototype.map.call(root.querySelectorAll('.dv-ci[aria-pressed=true]'),function(b){return b.getAttribute('data-key');});}
if(list&&live)list.addEventListener('click',function(e){var b=e.target.closest('.dv-ci');if(!b)return;
 var on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on?'true':'false');
 if(count)count.textContent=ticked().length+' of '+root.querySelectorAll('.dv-ci').length;
 clearTimeout(pending);pending=setTimeout(function(){send({checks:ticked()});},500);});
var box=root.querySelector('.dv-journal textarea'),note=root.querySelector('.dv-saved'),jt=null,last=box?box.value:'';
function keep(){if(!box||box.value===last)return;var v=box.value;if(note)note.textContent='Saving…';
 send({journal:v}).then(function(d){if(d){last=v;if(note)note.textContent='Saved';}else if(note){note.textContent='Not saved yet';}});}
if(box&&live){box.addEventListener('input',function(){clearTimeout(jt);jt=setTimeout(keep,1200);});box.addEventListener('blur',keep);}
var mark=root.querySelector('[data-act=done]'),undo=root.querySelector('[data-act=undo]'),card=root.querySelector('.dv-donecard'),
 here=document.querySelector('.dv-strip [aria-current=page]');
function shown(done){if(mark)mark.hidden=done;if(card)card.hidden=!done;
 if(here){here.classList.toggle('is-done',done);var c=here.querySelector('.dv-c');if(c)c.innerHTML=done?'<svg class="mb-ic" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>':String(day);}}
if(mark&&live)mark.addEventListener('click',function(){keep();mark.disabled=true;
 send({done:true}).then(function(d){mark.disabled=false;if(!d)return;shown(true);
  var s=card&&card.querySelector('.dv-streak');if(s&&d.streak>1)s.textContent=' '+d.streak+' in a row.';});});
if(undo&&live)undo.addEventListener('click',function(){send({done:false}).then(function(d){if(d)shown(false);});});
var lb=document.getElementById('dv-listen'),au=document.getElementById('dv-audio');
if(lb&&au){var lw=lb.querySelector('.dv-lw');
 function words(t){if(lw)lw.textContent=t;}
 au.addEventListener('play',function(){lb.setAttribute('aria-pressed','true');words('Pause');});
 au.addEventListener('pause',function(){lb.setAttribute('aria-pressed','false');words(au.ended?'Listen again':'Play');});
 lb.addEventListener('click',function(){
  if(au.getAttribute('src')){if(au.paused){au.play().catch(function(){});}else{au.pause();}return;}
  lb.disabled=true;words('Getting it ready…');
  fetch('/my/bible/plans/listen',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({devotional:dev,day:day})})
  .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
  .then(function(d){lb.disabled=false;au.src=d.url;au.play().catch(function(){words('Play');});})
  .catch(function(d){lb.disabled=false;words('Listen');say(d&&d.error==='slow'?'That\\'s a lot at once. Wait a minute.':'Listen didn\\'t work just now. Try again in a minute.');});});}
var sh=document.getElementById('dv-share');
if(sh)sh.addEventListener('click',function(){var t=sh.getAttribute('data-text');
 if(navigator.share){navigator.share({text:t}).catch(function(){});}
 else if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){say('Copied to share');},function(){say('Copying was blocked');});}});
})();</script>"""


def render_day(biz, site, me, dev: Dict[str, Any], n: int, st: Dict[str, Any],
               mine: Optional[Dict[str, Any]], *, tr: str = "kjv", listen: bool = False) -> str:
    """A devotional's day (approved board 11). `mine` is the member's own
    day (done, ticks, journal); None = it couldn't load, so nothing on the
    page can save."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e, _shell
    pool = photos.photos(biz, site)
    day = dev["days"][n - 1]
    live = mine is not None and not st["preview"]
    mine = mine or {}
    when = dv.day_on(st["start"], n) if st["start"] else None
    church = (biz.get("name") or "").strip()
    st = {**st, "here": n}
    note = ""
    if st["preview"]:
        note = ('<p class="mb-hint">' + ui.icon("lock", 14) + '<span>This is a preview: the checklist, the journal and '
                'Mark done don\'t save here.</span></p>')
    elif not live:
        note = '<p class="mp-err" role="alert">Your day couldn\'t load just now, so nothing here will save. Please try again.</p>'
    verse, label, link = _verse_line(day.get("scripture") or "", tr, limit=3)
    scrip = ""
    if day.get("scripture"):
        import bible_text as bt
        read = (f'<a href="{_e(link)}">Read {_e(re.sub(r":.*$", "", label))}{ui.icon("chevron", 14)}</a>' if link else "")
        scrip = (f'<section class="dv-scrip" aria-label="Today\'s scripture"><p class="dv-eb">Today\'s scripture</p>'
                 + (f'<blockquote>{verse}</blockquote>' if verse else "")
                 + f'<div class="dv-scrip-f"><span>{_e(label)}{" · " + _e(bt.TRANSLATIONS[tr]["short"]) if verse else ""}</span>{read}</div></section>')
    body = "".join(f"<p>{_e(p)}</p>" for p in dv.paragraphs(day.get("body") or ""))
    pull = f'<p class="dv-pull">{_e(day["pull"])}</p>' if (day.get("pull") or "").strip() else ""
    blocks = []
    for key, hue, ic, name in (("pray", "brand", "pray", "Pray"), ("act", "teal", "check", "Do today"),
                               ("together", "violet", "users", "Together")):
        text = (day.get(key) or "").strip()
        if text:
            blocks.append(f'<div class="dv-blk h-{hue}"><span class="dv-disc">{ui.icon(ic, 18)}</span><span class="dv-t">'
                          f'<small>{name}</small><span class="{"dv-serif" if key == "pray" else ""}">{_e(text)}</span></span></div>')
    checks = set(mine.get("checks") or [])
    practices = dev.get("practices") or []
    check = ""
    if practices:
        items = "".join(
            f'<button class="dv-ci" type="button" data-key="{_e(p["key"])}" aria-pressed="{"true" if p["key"] in checks else "false"}"'
            f'{"" if live else " disabled"}><span class="dv-box">{ui.icon("check", 15)}</span><span class="dv-t"><strong>{_e(p["title"])}</strong>'
            f'{f"<span>{_e(p.get("sub"))}</span>" if p.get("sub") else ""}</span></button>' for p in practices)
        n_on = len([p for p in practices if p["key"] in checks])
        check = (f'<section class="dv-check" aria-labelledby="dv-chk-h"><div class="dv-check-h"><h2 id="dv-chk-h">Your daily checklist</h2>'
                 f'<span class="dv-check-n">{n_on} of {len(practices)}</span></div>{items}</section>')
    question = (day.get("journal") or "").strip() or DEFAULT_JOURNAL
    journal = (f'<section class="dv-journal" aria-labelledby="dv-j-h"><h2 id="dv-j-h">{_e(question)}</h2>'
               f'<label class="mp-sr" for="dv-j">Your answer</label><textarea class="mp-input" id="dv-j" maxlength="{JOURNAL_MAX}" '
               f'placeholder="Write it down, then give it to God."{"" if live else " disabled"}>{_e(mine.get("journal") or "")}</textarea>'
               f'<p class="bb-priv">{ui.icon("lock", 14)}<span>Private to you. Only you can read it.</span>'
               f'<span class="dv-saved" role="status"></span></p></section>')
    done = bool(mine.get("done_at"))
    later = n < st["count"]
    if later and n + 1 <= st["upto"]:
        after = f"Day {n + 1} is ready when you are."
    elif later and st["start"]:
        after = f"Day {n + 1} opens {_date(dv.day_on(st['start'], n + 1))}."
    else:
        after = "That's every day of it. Well done."
    streak = dv.streak(st["done"] | ({n} if done else set()), max(st["upto"], 1))
    donebox = (f'<div class="dv-donebox"><button class="mp-go" type="button" data-act="done"{" hidden" if done else ""}'
               f'{"" if live else " disabled"}>Mark day {n} done</button>'
               f'<div class="dv-donecard h-teal"{"" if done else " hidden"}><span class="dv-disc">{ui.icon("check", 18)}</span>'
               f'<span class="dv-t"><strong>Day {n} done.<span class="dv-streak">{f" {streak} in a row." if streak > 1 else ""}</span></strong>'
               f'<span>{_e(after)}</span></span>'
               f'<button class="mp-link dv-undo" type="button" data-act="undo"{"" if live else " disabled"}>Not done yet</button></div></div>')
    nxt = ""
    if later:
        nd = dev["days"][n]
        what = "Next" if n + 1 <= st["upto"] else ("Tomorrow" if st["now"] == n else "Next")
        inner = (f'<span class="dv-t"><small>{what} · Day {n + 1}</small><strong>{_e(nd.get("title") or "")}</strong>'
                 f'<span>{_e(nd.get("scripture") or "")}</span></span>')
        if n + 1 <= st["upto"]:
            nxt = f'<a class="dv-next" href="{_href(dev, n + 1)}">{inner}{ui.icon("chevron", 16)}</a>'
        else:
            opens = f"Opens {_date(dv.day_on(st['start'], n + 1))}" if st["start"] else ""
            nxt = f'<div class="dv-next is-shut">{inner}<span class="dv-opens">{_e(opens)}</span></div>'
    author = dev.get("author") or ""
    listen_btn = ""
    if listen:
        listen_btn = (f'<button class="dv-listen" id="dv-listen" type="button" aria-pressed="false">'
                      f'<span class="dv-play">{ui.icon("play", 12)}</span><span class="dv-lw">Listen</span></button>'
                      f'<audio id="dv-audio" preload="none"></audio>')
    av = f'<span class="dv-av" aria-hidden="true">{_e(ui.initials(author or church))}</span>'
    who = (f'<div class="dv-author">{av}<span class="dv-t"><strong>{_e(author or church)}</strong>'
           f'{f"<span>{_e(church)}</span>" if author and church else ""}</span>{listen_btn}</div>')
    kick = f"{dev['title']} · Day {n} of {st['count']}"
    sub = (f"{when.strftime('%A')} · " if when else "") + f"about {dv.minutes(day)} minutes"
    share = f"{day.get('title') or ''}: {label} · {dev['title']}" + (f", {church}" if church else "")
    return _shell(biz, site, day.get("title") or dev["title"], f"""<a class="mb-back" href="{_href(dev)}">{ui.icon('back', 16)}{_e(dev['title'][:28])}</a>
<div id="dv-day" class="dv-day" data-dev="{dev['id']}" data-day="{n}" data-live="{'1' if live else '0'}">
<section class="dv-hero is-day" aria-labelledby="dv-h">{_cover(biz, site, dev, pool, None, "dv-cv-p", night=True)}
<button class="dv-share" id="dv-share" type="button" aria-label="Share this day" data-text="{_e(share)}">{ui.icon('share', 18)}</button>
<div class="dv-cv-in"><span class="dv-glass">{_e(kick)}</span><h1 id="dv-h">{_e(day.get('title') or f'Day {n}')}</h1><p>{_e(sub)}</p></div></section>
{_dots(st, dev, links=True)}
{note}
{who}
{scrip}
<div class="dv-body">{body}</div>
{pull}
{f'<div class="dv-blocks">{"".join(blocks)}</div>' if blocks else ''}
{check}
{journal}
{donebox}
{nxt}
</div>
<p class="dv-toast" id="dv-toast" role="status" hidden></p>""", tab="bible", who=me, script=DAY_JS)


# ─── Home and the Bible tab ──────────────────────────────────────────


def today_row(dev: Optional[Dict[str, Any]], st: Optional[Dict[str, Any]]) -> str:
    """The member's devotional for today, as a row in Home's Today card
    (board 1): its ring, the day's title, the devotional and how long."""
    import member_app_ui as ui
    from member_portal import _e
    if not dev or not st or not st.get("now"):
        return ""
    n = st["now"]
    day = (dev.get("days") or [{}])[n - 1] if dev.get("days") else {}
    done = n in st["done"]
    ring = ui.ring(n, st["count"], 54, label=f'{n}<small>/{st["count"]}</small>')
    return (f'<a class="mb-trow h-brand dv-trow" href="{_href(dev, n)}">{ring}<span class="mb-trow-t">'
            f'<small>Devotional · Day {n} of {st["count"]}{" · done" if done else ""}</small>'
            f'<strong>{_e(day.get("title") or dev["title"])}</strong>'
            f'<span>{_e(dev["title"])} · {dv.minutes(day)} min</span></span>{ui.icon("chevron", 18)}</a>')


def pick_today(devs: Optional[List[Dict[str, Any]]], done: Optional[Dict[str, set]], mine: Optional[Dict[str, date]],
               today: Optional[date] = None) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """The devotional Home shows today: one the church dated that's running,
    else one the member started that's running. (devotional, state)."""
    today = today or date.today()
    best = None
    for d in devs or []:
        st = state(d, (mine or {}).get(f"devotional:{d['id']}"), (done or {}).get(str(d["id"]), set()), today)
        if st["kind"] not in ("running", "finished") or not st["now"]:
            continue
        rank = (1 if d.get("starts_on") else 0, str(st["start"]))
        if best is None or rank > best[0]:
            best = (rank, d, st)
    return (best[1], best[2]) if best else (None, None)


def bible_sections(biz, site, *, devs: Optional[List[Dict[str, Any]]], done: Optional[Dict[str, set]],
                   mine: Optional[Dict[str, date]], church_today: Optional[Dict[str, Any]], church_done: Optional[set],
                   preview: bool = False, today: Optional[date] = None) -> str:
    """The Bible tab's "From <church>" (its devotional this week, and the
    others) and "Reading plans" (board 6)."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_portal_church as mpc
    from member_portal import _e
    today = today or date.today()
    short = mpc._short_name(biz.get("name") or "") or "your church"
    out = []
    sts = [(d, state(d, (mine or {}).get(f"devotional:{d['id']}"), (done or {}).get(str(d["id"]), set()), today,
                     preview=preview)) for d in (devs or [])]
    if sts:
        pool = photos.photos(biz, site)
        used: set = set()
        feat = next(((d, st) for d, st in sts if st["kind"] == "running"), None) or sts[0]
        d, st = feat
        kick = f"{st['count']}-day devotional" + (f" · {d['kind']}" if d.get("kind") else "")
        if st["kind"] == "running":
            day = (d.get("days") or [{}])[st["now"] - 1] if d.get("days") else {}
            line = f"Day {st['now']} today" + (f": {day.get('title')}" if day.get("title") else "")
            go = f"Read day {st['now']}"
        else:
            line, _cls = chip(st)
            go = "Open it" if st["kind"] != "new" else "Start"
        dots = _dots(st, d, links=False, cls="dv-mini") if st["start"] and st["count"] <= 7 else ""
        others = [(o, ost) for o, ost in sts if o is not d][:3]
        rail = ""
        if others:
            rail = '<div class="dv-rail">' + "".join(
                f'<a class="dv-mc" href="{_target(o, ost)}"><span class="dv-mc-p">{_cover(biz, site, o, pool, used, "dv-th-p")}</span>'
                f'<strong>{_e(o["title"])}</strong><span>{_e(chip(ost)[0])}</span></a>' for o, ost in others) + "</div>"
        out.append(f"""<section class="h-brand" aria-labelledby="dv-from-h">{ui.section(f"From {short}", "/my/bible/plans", "All", hid="dv-from-h")}
<a class="dv-feat" href="{_target(d, st)}"><span class="dv-cv">{_cover(biz, site, d, pool, used, "dv-cv-p", night=True)}
<span class="dv-cv-in"><span class="dv-glass">{_e(kick)}</span><strong>{_e(d['title'])}</strong><span>{_e(line)}</span></span></span>
<span class="dv-foot">{dots}<span class="mp-go dv-sm">{_e(go)}</span></span></a>{rail}</section>""")
    rows = []
    if church_today:
        t = church_today
        ring = ui.ring(len(church_done or set()), t["of"], 54, label=f'{len(church_done or set())}<small>/{t["of"]}</small>')
        rows.append(f'<a class="dv-plan h-gold" href="{_e(t["href"])}">{ring}<span class="dv-t"><small>The church is reading</small>'
                    f'<strong>{_e(t["title"])}</strong><span>Today: {_e(t["label"])}</span></span></a>')
    left = []
    for key, meta in rp.PLANS.items():
        started = (mine or {}).get(f"reading:{key}")
        plan = own_plan(key, started)
        if not plan:
            left.append((key, meta))
            continue
        now = rp.day_number(plan, today)
        n = min(plan["days"], max(0, (today - started).days + 1))
        ring = ui.ring(n, plan["days"], 54, label=f'{n}<small>/{plan["days"]}</small>')
        sub = f"Today: {rp.label(rp.schedule(key)[now - 1])}" if now else "Finished"
        rows.append(f'<a class="dv-plan h-teal" href="/my/bible/plans/{key}">{ring}<span class="dv-t"><small>Your plan</small>'
                    f'<strong>{_e(meta["title"])}</strong><span>{_e(sub)}</span></span></a>')
    chips = "".join(f'<a class="mb-chip" href="/my/bible/plans?show=reading">+ {_e(meta["title"])}</a>' for _, meta in left[:2])
    if not rows:
        rows.append('<p class="dv-plain">Read the Bible a day at a time, on your own or with the church.</p>')
    out.append(f'<section aria-labelledby="dv-plans-h">{ui.section("Reading plans", "/my/bible/plans?show=reading", "See all", hid="dv-plans-h")}'
               f'<div class="dv-card">{"".join(rows)}{f"<div class=dv-starts>{chips}</div>" if chips else ""}</div></section>')
    return "".join(out)


# ─── GET /my/bible/plans* (from member_portal_bible.serve) ───────────


async def serve(request: Request, biz, site, me, parts: List[str], *, tr: str, preview: bool = False):
    """(html, status) for a page, or a RedirectResponse."""
    import asyncio
    import member_portal_reading as mpr
    from member_portal import _SECURE_HEADERS
    bid, cid = biz["id"], str(me["id"])
    if not parts:
        devs, mine, done = await asyncio.gather(
            asyncio.to_thread(dv.catalog, bid), asyncio.to_thread(_or_empty, starts, preview, bid, cid),
            asyncio.to_thread(_or_empty, done_days, preview, bid, cid))
        running = [d for d in devs or [] if d.get("day_count")]
        # the one this week needs its days (its verse); the rest don't
        full = await asyncio.gather(*[asyncio.to_thread(dv.one, bid, str(d["id"])) for d in running[:3]])
        byid = {str(f[0]["id"]): f[0] for f in full if f[0]}
        devs = None if devs is None else [byid.get(str(d["id"]), d) for d in devs]
        plan = rp.current(biz)
        today = rp.today_for(biz)
        cdone = await asyncio.to_thread(rp.read_days, bid, cid, plan) if plan and today and not preview else set()
        import member_portal_church as mpc
        return render_plans(biz, site, me, devs=devs, done=done, mine=mine, church_today=today, church_done=cdone,
                            show=str(request.query_params.get("show") or "all"), preview=preview, tr=tr,
                            flash=mpc._flash(request)), (503 if devs is None else 200)
    key = parts[0]
    if key in rp.PLANS and len(parts) == 1:
        mine = await asyncio.to_thread(_or_empty, starts, preview, bid, cid)
        plan = own_plan(key, (mine or {}).get(f"reading:{key}"))
        if not plan:
            return RedirectResponse("/my/bible/plans?show=reading", status_code=303, headers=_SECURE_HEADERS)
        done = await asyncio.to_thread(rp.read_days, bid, cid, plan)
        return mpr.render_page(biz, site, request, me, done, plan=plan), (503 if done is None else 200)
    if not _UUID.fullmatch(key) or len(parts) > 2:
        return RedirectResponse("/my/bible/plans", status_code=303, headers=_SECURE_HEADERS)
    dev, ok = await asyncio.to_thread(dv.one, bid, key)
    if not ok:
        return _unavailable(biz, site, me), 503
    if not dev:
        return RedirectResponse("/my/bible/plans", status_code=303, headers=_SECURE_HEADERS)
    started = None if preview else await asyncio.to_thread(started_on, bid, cid, dev)
    days = None if preview else await asyncio.to_thread(progress, bid, cid, key)
    if started is False or (days is None and not preview):
        return _unavailable(biz, site, me), 503
    done = {d for d, r in (days or {}).items() if r.get("done_at")}
    st = state(dev, started, done, preview=preview)
    if len(parts) == 1:
        import member_portal_church as mpc
        return render_devotional(biz, site, me, dev, st, flash=mpc._flash(request)), 200
    if not parts[1].isdigit() or not 1 <= int(parts[1]) <= st["count"] or int(parts[1]) > st["upto"]:
        return RedirectResponse(_href(dev), status_code=303, headers=_SECURE_HEADERS)
    n = int(parts[1])
    import devotional_voice as dvv
    return render_day(biz, site, me, dev, n, st, None if days is None and not preview else (days or {}).get(n, {}),
                      tr=tr, listen=dvv.can_speak()), 200


def _or_empty(fn, preview: bool, *args):
    """A member's own rows; a preview has none (and reads none)."""
    return {} if preview else fn(*args)


def _unavailable(biz, site, me) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    return _shell(biz, site, "Plans & devotionals", f'<a class="mb-back" href="/my/bible/plans">{ui.icon("back", 16)}Plans</a>'
                  '<p class="mp-err" role="alert" style="margin-top:20px">This couldn\'t load just now. '
                  'Please try again in a moment.</p>', tab="bible", who=me)


async def home_extras(biz, me, *, preview: bool = False, church_reading: bool = True
                      ) -> Tuple[str, Optional[Dict[str, Any]], Optional[set]]:
    """For Home: (today's devotional row or '', today's reading on a plan
    of the member's own when the church has none running, its days read).
    Never stops Home: anything that fails is left out."""
    import asyncio
    devotional, own, own_done = "", None, None
    try:
        bid, cid = biz["id"], str(me["id"])
        devs, mine, done = await asyncio.gather(
            asyncio.to_thread(dv.catalog, bid), asyncio.to_thread(_or_empty, starts, preview, bid, cid),
            asyncio.to_thread(_or_empty, done_days, preview, bid, cid))
        dev, st = pick_today(devs, done, mine)
        if dev:
            full, _ok = await asyncio.to_thread(dv.one, bid, str(dev["id"]))
            devotional = today_row(full or dev, st)
        if not church_reading and mine:
            for key in rp.PLANS:
                plan = own_plan(key, mine.get(f"reading:{key}"))
                own = own_today(plan) if plan else None
                if own:
                    own_done = await asyncio.to_thread(rp.read_days, bid, cid, plan)
                    break
    except Exception:  # noqa: BLE001
        logger.warning("member home: devotional and own plan skipped", exc_info=True)
    return devotional, own, own_done


async def bible_home(biz, site, me, *, preview: bool = False) -> str:
    """The Bible tab's devotional and reading-plan sections ('' on any
    failure: the rest of the tab still shows)."""
    import asyncio
    try:
        bid, cid = biz["id"], str(me["id"])
        devs, mine, done = await asyncio.gather(
            asyncio.to_thread(dv.catalog, bid), asyncio.to_thread(_or_empty, starts, preview, bid, cid),
            asyncio.to_thread(_or_empty, done_days, preview, bid, cid))
        running = [d for d in devs or [] if d.get("day_count")]
        full = await asyncio.gather(*[asyncio.to_thread(dv.one, bid, str(d["id"])) for d in running[:3]])
        byid = {str(f[0]["id"]): f[0] for f in full if f[0]}
        devs = [byid.get(str(d["id"]), d) for d in devs or []]
        plan = rp.current(biz)
        today = rp.today_for(biz)
        cdone = await asyncio.to_thread(rp.read_days, bid, cid, plan) if plan and today and not preview else set()
        return bible_sections(biz, site, devs=devs, done=done, mine=mine, church_today=today, church_done=cdone,
                              preview=preview)
    except Exception:  # noqa: BLE001
        logger.warning("member bible: plans sections skipped", exc_info=True)
        return ""


# ─── POST ────────────────────────────────────────────────────────────


@router.post("/my/bible/plans/start", include_in_schema=False)
async def start_plan(request: Request):
    """Start a reading plan or a devotional on your own day (today)."""
    import asyncio
    import member_portal_church as mpc
    from member_portal import _SECURE_HEADERS
    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    plan = str(form.get("plan") or "")

    def go(to: str, **q: str) -> RedirectResponse:
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return RedirectResponse(to + (f"?{qs}" if qs else ""), status_code=303, headers=_SECURE_HEADERS)
    back = "/my/bible/plans" + (f"/{plan[11:]}" if plan.startswith("devotional:") and _UUID.fullmatch(plan[11:]) else "")
    if unavailable:
        return go(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    bid = church["business"]["id"]
    if plan.startswith("reading:") and plan[8:] in rp.PLANS:
        to = f"/my/bible/plans/{plan[8:]}"
    elif plan.startswith("devotional:") and _UUID.fullmatch(plan[11:]):
        dev, ok = await asyncio.to_thread(dv.one, bid, plan[11:])
        if not ok:
            return go(back, err="error")
        if not dev or dev.get("starts_on"):
            return go("/my/bible/plans")
        to = _href(dev, 1)
    else:
        return go("/my/bible/plans")
    if not mpc._allowed(church, me):
        return go(back, err="slow")
    if not await asyncio.to_thread(start, bid, str(me["id"]), plan, date.today()):
        return go(back, err="error")
    return go(to)


@router.post("/my/bible/plans/stop", include_in_schema=False)
async def stop_plan(request: Request):
    """Stop a reading plan you started (its days read stay with it)."""
    import asyncio
    import member_portal_church as mpc
    from member_portal import _SECURE_HEADERS
    church, me, unavailable = await mpc._signed_in(request)
    form = await request.form()
    plan = str(form.get("plan") or "")
    if unavailable or not me or not (plan.startswith("reading:") and plan[8:] in rp.PLANS):
        return RedirectResponse("/my/bible/plans?show=reading", status_code=303, headers=_SECURE_HEADERS)
    ok = await asyncio.to_thread(stop, church["business"]["id"], str(me["id"]), plan)
    return RedirectResponse("/my/bible/plans?show=reading" if ok else f"/my/bible/plans/{plan[8:]}?err=error",
                            status_code=303, headers=_SECURE_HEADERS)


def clean_change(body: Dict[str, Any], dev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The member's change to their day, checked: practices of this
    devotional's, a journal of at most 4,000 characters, done yes or no."""
    out: Dict[str, Any] = {}
    if "checks" in body:
        raw = body.get("checks")
        keys = [p["key"] for p in dev.get("practices") or []]
        if not isinstance(raw, list) or any(str(k) not in keys for k in raw):
            return None
        out["checks"] = [k for k in keys if k in {str(x) for x in raw}]
    if "journal" in body:
        text = str(body.get("journal") or "").strip()
        if len(text) > JOURNAL_MAX:
            return None
        out["journal"] = text
    if "done" in body:
        if not isinstance(body.get("done"), bool):
            return None
        out["done"] = body["done"]
    return out or None


@router.post("/my/bible/plans/day", include_in_schema=False)
async def save_my_day(request: Request):
    """A member's own day: the practices ticked, the journal, done. JSON in,
    JSON out (the day page's script)."""
    import asyncio
    import member_portal as mp
    import member_portal_church as mpc
    import rate_limit
    h = mp._SECURE_HEADERS

    def no(error: str, status: int) -> JSONResponse:
        return JSONResponse({"ok": False, "error": error}, status_code=status, headers=h)
    if not mp._same_origin(request):
        return no("origin", 403)
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable == "preview":
        return no("preview", 403)
    if unavailable:
        return no("unavailable", 503)
    if not me:
        return no("signin", 401)
    bid, cid = church["business"]["id"], str(me["id"])
    # The same budget as Bible marks: a checklist is many taps.
    if not rate_limit.allow("bible_mark", f"{bid}|{cid}"):
        return no("slow", 429)
    try:
        body = await request.json()
        n = int((body or {}).get("day"))
        dev_id = str((body or {}).get("devotional") or "")
    except Exception:  # noqa: BLE001
        return no("bad", 400)
    dev, ok = await asyncio.to_thread(dv.one, bid, dev_id)
    if not ok:
        return no("unavailable", 503)
    if not dev or not isinstance(body, dict):
        return no("bad", 400)
    started = await asyncio.to_thread(started_on, bid, cid, dev)
    if started is False:
        return no("unavailable", 503)
    count = int(dev.get("day_count") or 0)
    if not 1 <= n <= dv.open_upto(dv.run_start(dev, started), count):
        return no("closed", 403)
    change = clean_change(body, dev)
    if not change:
        return no("bad", 400)
    row = await asyncio.to_thread(save_day, bid, cid, dev_id, n, change)
    if row is None:
        return no("error", 503)
    days = await asyncio.to_thread(progress, bid, cid, dev_id) or {}
    done = {d for d, r in days.items() if r.get("done_at")}
    upto = dv.open_upto(dv.run_start(dev, started), count)
    return JSONResponse({"ok": True, "done": bool(row.get("done_at")), "checks": row.get("checks") or [],
                         "streak": dv.streak(done, upto)}, headers=h)
