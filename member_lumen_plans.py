"""member_lumen_plans.py — Plans in the member app's new look (Look 5.1).

Kevin approved the "Plans built from what Love City already writes" design
(2026-11-21, "go ahead"): three screens, the Plans tab, a plan's page and
the day. This is the Plans tab and a plan's page for the plans read a day at
a time from the Bible itself (the four whole-Bible reading plans and the six
topic plans, topic_plans.py). Who sees it: member_lumen.py (MEMBER_LUMEN).
Off, and for anyone the switch doesn't show the new look to, every page is
today's, byte for byte.

  /my/bible?tab=plans ...... the Bible tab's Plans (its segmented control on
                             top, member_lumen_bible.seg):
                             - Continue: the plan the member is in, first a
                               devotional the church dated and is reading
                               now, then one they started, then a plan of
                               their own (the latest started), then the
                               church's reading plan. Its day row (a circle
                               a day, up to seven; today ringed, the days read
                               filled) and "N days in a row" only where their
                               days could be read; Read day N.
                             - From <church>: the church's devotionals as
                               square covers, its picture for each
                               (member_app_pictures "devotional:<id>") drawn in
                               the church's colour with the title in serif
                               over it; with no picture, a cover made of the
                               church's colour (no stock art).
                             - What are you walking through?: the six topic
                               plans as colour tiles with an icon.
                             - Read the whole Bible: the four reading plans
                               as covers (365, 260, 30 and 31 days).
  /my/bible/plans/<plan> ... a reading plan's or a topic plan's page: its
                             cover, what it is, Start (or Continue day N, or
                             You finished it), every day (up to 31; a longer
                             plan the two weeks around today and the days to
                             catch up) with its passages and whether it's
                             read, a tick to mark it, and Stop.

A piece whose read failed is left out (never a made-up number, never an
empty "nothing here"); a church with no devotionals simply has no "From"
row.

Reads (all through member_cache.Kept, so tapping back to Plans reads
nothing): the church's devotionals (catalog) and the Continue devotional's
days, kept CHURCH_SECONDS per church; the member's plans started, days done
and the ticks of the Continue plan, kept MEMBER_SECONDS per member. Every
route that writes a member's plans (start, stop, a tick, a devotional's day)
forgets them on its server copy and gives the phone a new VERSION_COOKIE,
which is part of the key, so the next page on any server copy reads them
afresh. The owner's preview reads none of the member's own rows.

The look is CSS (below), joined into the Lumen sheet by
member_lumen_ui.templates(); every rule sits under body.lm.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import date, timedelta
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from member_lumen_ui import dark as _dark

logger = logging.getLogger("member_lumen_plans")

MEMBER_SECONDS = 30.0
CHURCH_SECONDS = 60.0
# The member's plans version, on their phone: a write gives it a new value,
# so every server copy's kept rows for them are passed over.
VERSION_COOKIE = "lm_pl"
_VER = re.compile(r"[0-9a-f]{1,16}")
# How many devotionals the "From" row shows (All lists every one).
COVERS_MAX = 8
# A plan up to this many days lists every day on its page.
LIST_ALL = 31
# The day row on Continue: this many circles at most.
ROW = 7

_GLYPHS = {
    "wind": '<path d="M3 8h10.5a2.5 2.5 0 1 0-2.5-2.5"/><path d="M3 12h15.5a2.5 2.5 0 1 1-2.5 2.5"/><path d="M3 16h7"/>',
    "heal": '<path d="M19.4 12.6 12 20l-7.4-7.4A4.8 4.8 0 0 1 12 6.1a4.8 4.8 0 0 1 7.4 6.5z"/><path d="M8.5 12.5h2l1.2-2 2 4 1.2-2h.6"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    "rings": '<circle cx="9" cy="14" r="5"/><circle cx="15" cy="14" r="5"/><path d="m10 5.5 2-2.5 2 2.5"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M14.6 9.3A2.7 2.7 0 0 0 12 8c-1.5 0-2.6.8-2.6 2s1.1 1.7 2.6 2 2.6.8 2.6 2-1.1 2-2.6 2a2.8 2.8 0 0 1-2.6-1.4"/>'
            '<path d="M12 6.5V8M12 16v1.5"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
}


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def _glyph(name: str, size: int = 22) -> str:
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{_GLYPHS[name]}</svg>')


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def _short_date(d: date) -> str:
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}"


# ─── kept reads ──────────────────────────────────────────────────────

_MEMBER = None
_CHURCH = None


def _stores():
    global _MEMBER, _CHURCH
    if _MEMBER is None:
        import member_cache
        _MEMBER = member_cache.Kept("plans_member", MEMBER_SECONDS)
        _CHURCH = member_cache.Kept("plans_church", CHURCH_SECONDS)
    return _MEMBER, _CHURCH


def forget_everything() -> None:
    """For the tests (conftest) and the local harness."""
    if _MEMBER is not None:
        _MEMBER.clear()
        _CHURCH.clear()


def version(request: Any) -> str:
    """The member's plans version from their phone ('' before any write)."""
    try:
        raw = str(request.cookies.get(VERSION_COOKIE) or "")
    except Exception:  # noqa: BLE001
        return ""
    return raw if _VER.fullmatch(raw) else ""


def stamp(resp: Any) -> Any:
    """After a write to the member's own plans: a new version on their
    phone (every server copy then reads their plans afresh)."""
    resp.set_cookie(VERSION_COOKIE, secrets.token_hex(6), max_age=30 * 86400, path="/my", secure=True,
                    httponly=True, samesite="lax")
    return resp


def forget(business_id: Any, contact_id: Any) -> None:
    """The member's kept plans on this server copy, dropped after a write."""
    m, _ = _stores()
    tag = f"{business_id}|{contact_id}"
    m.forget(lambda _k, t: t == tag)


def wrote(resp: Any, business_id: Any, contact_id: Any) -> Any:
    """A write to the member's plans went through: forget and stamp."""
    try:
        forget(business_id, contact_id)
    except Exception:  # noqa: BLE001
        logger.warning("plans: forget failed", exc_info=True)
    return stamp(resp)


def _member(kind: str, bid: Any, cid: Any, ver: str, fn, enc, dec, *args):
    m, _ = _stores()
    key = ("m", kind, str(bid), str(cid), ver) + tuple(str(a) for a in args)
    hit, got = m.get(key)
    if hit:
        return dec(got)
    val = fn()
    if val is not None:
        m.put(key, enc(val), tag=f"{bid}|{cid}")
    return val


def starts(bid: Any, cid: Any, ver: str = "", preview: bool = False) -> Optional[Dict[str, date]]:
    """member_portal_devotionals.starts, kept: {plan: started_on} or None."""
    import member_portal_devotionals as mpd
    if preview:
        return {}
    return _member("starts", bid, cid, ver, lambda: mpd.starts(bid, cid),
                   lambda v: {k: d.isoformat() for k, d in v.items()},
                   lambda v: {k: date.fromisoformat(d) for k, d in v.items()})


def done_days(bid: Any, cid: Any, ver: str = "", preview: bool = False) -> Optional[Dict[str, set]]:
    """member_portal_devotionals.done_days, kept."""
    import member_portal_devotionals as mpd
    if preview:
        return {}
    return _member("done", bid, cid, ver, lambda: mpd.done_days(bid, cid),
                   lambda v: {k: sorted(s) for k, s in v.items()},
                   lambda v: {k: set(s) for k, s in v.items()})


def read_days(bid: Any, cid: Any, plan: Dict[str, Any], ver: str = "", preview: bool = False) -> Optional[set]:
    """reading_plans.read_days for one run of a plan, kept."""
    import reading_plans as rp
    if preview:
        return set()
    return _member("ticks", bid, cid, ver, lambda: rp.read_days(bid, cid, plan), sorted, set,
                   plan["key"], plan["start"].isoformat())


def _church(kind: str, bid: Any, fn, *args):
    _, c = _stores()
    key = ("c", kind, str(bid)) + tuple(str(a) for a in args)
    hit, got = c.get(key)
    if hit:
        return got, True
    val = fn()
    return val, False


def _undate(row: Dict[str, Any]) -> Dict[str, Any]:
    d = row.get("starts_on")
    return {**row, "starts_on": d.isoformat() if isinstance(d, date) else d}


def catalog(bid: Any) -> Optional[List[Dict[str, Any]]]:
    """devotionals.catalog (published), kept a minute per church."""
    import devotionals as dv
    got, hit = _church("catalog", bid, lambda: dv.catalog(bid))
    if hit:
        return [dv._dated(r) for r in got]
    if got is not None:
        _stores()[1].put(("c", "catalog", str(bid)), [_undate(r) for r in got], tag=str(bid))
    return got


def one(bid: Any, dev_id: Any) -> Optional[Dict[str, Any]]:
    """devotionals.one (published, with its days), kept a minute per
    church; None when it isn't there or the read failed."""
    import devotionals as dv
    got, hit = _church("one", bid, lambda: dv.one(bid, str(dev_id))[0], dev_id)
    if hit:
        return dv._dated(got)
    if got is not None:
        _stores()[1].put(("c", "one", str(bid), str(dev_id)), _undate(got), tag=str(bid))
    return got


# ─── the plans a member can read: reading plans and topic plans ──────


def meta(key: str) -> Optional[Dict[str, Any]]:
    """What a reading-style plan is: {kind: reading|topic, title, about,
    count}; None for anything else."""
    import reading_plans as rp
    import topic_plans as tp
    if key in rp.PLANS:
        m = rp.PLANS[key]
        return {"kind": "reading", "title": m["title"], "about": m["about"], "count": m["days"]}
    if key in tp.TOPICS:
        t = tp.TOPICS[key]
        return {"kind": "topic", "title": t["name"], "about": t["about"], "count": tp.count(key), "word": t["title"],
                "hue": t["hue"], "icon": t["icon"]}
    return None


def own(key: str, started: Optional[date]) -> Optional[Dict[str, Any]]:
    """A plan the member started, in reading_plans' shape."""
    import member_portal_devotionals as mpd
    import topic_plans as tp
    if tp.is_topic(key):
        return tp.plan(key, started)
    return mpd.own_plan(key, started)


def day_label(key: str, n: int) -> str:
    """What day n reads: "Genesis 1–3" or "1 Peter 5:6-7 · Psalm 55:22"."""
    import reading_plans as rp
    import topic_plans as tp
    if tp.is_topic(key):
        return tp.label(key, n)
    return rp.label(rp.schedule(key)[n - 1])


def day_title(key: str, n: int) -> str:
    """Day n's own title (a topic plan's), else "Day n"."""
    import topic_plans as tp
    if tp.is_topic(key):
        return tp.day(key, n).get("title") or f"Day {n}"
    return f"Day {n}"


def day_href(key: str, n: int) -> str:
    """Where reading day n opens: the Bible reader at its first passage."""
    import reading_plans as rp
    import topic_plans as tp
    if tp.is_topic(key):
        return tp.href(key, n)
    return rp.href(rp.schedule(key)[n - 1])


def minutes(key: str, tr: str) -> int:
    import member_lumen_bible as mlb
    import topic_plans as tp
    return tp.minutes(key, tr) if tp.is_topic(key) else mlb._plan_minutes(key, tr)


def _target(now: Optional[int], upto: int, done: Optional[set]) -> int:
    """The day Continue opens: today's unless it's read, else the first
    open day not read, else today's (or the last open day)."""
    done = done or set()
    if now and now not in done:
        return now
    first = next((d for d in range(1, upto + 1) if d not in done), None)
    return first or now or max(1, upto)


# ─── Continue ────────────────────────────────────────────────────────


def pick(sts, mine: Optional[Dict[str, date]], church_today: Optional[Dict[str, Any]],
         today: date) -> Optional[Dict[str, Any]]:
    """What Continue shows, without its ticks: {kind: devotional|own|church,
    ...}. `sts` [(devotional, state)] or None (their read failed: no
    devotional is offered); `mine` None (the member's plans couldn't be
    read: none of theirs is offered)."""
    running = [x for x in (sts or []) if x[1]["kind"] == "running" and x[1]["now"]]
    if running:
        d, st = next((x for x in running if x[0].get("starts_on")), None) or \
            sorted(running, key=lambda x: x[1]["start"], reverse=True)[0]
        return {"kind": "devotional", "dev": d, "st": st}
    ours = []
    for key, started in (mine or {}).items():
        if not key.startswith("reading:"):
            continue
        plan = own(key[8:], started)
        if plan and plan_day(plan, today):
            ours.append(plan)
    if ours:
        return {"kind": "own", "plan": sorted(ours, key=lambda p: p["start"], reverse=True)[0]}
    if church_today:
        return {"kind": "church", "today": church_today}
    return None


def plan_day(plan: Dict[str, Any], today: date) -> Optional[int]:
    import reading_plans as rp
    return rp.day_number(plan, today)


def row(count: int, now: int, done: Optional[set]) -> str:
    """The day row: a circle a day (up to seven; a longer plan the seven
    around today), the day's number in it, today ringed, the days read
    filled. `done` None (its read failed): no row."""
    if done is None or not count:
        return ""
    first = 1 if count <= ROW else max(1, min(now - (ROW - 2), count - ROW + 1))
    cells = []
    for n in range(first, min(count, first + ROW - 1) + 1):
        cls = " ".join(c for c in ("ok" if n in done else "", "now" if n == now else "") if c)
        cells.append(f'<i class="{cls}">{n}</i>' if cls else f"<i>{n}</i>")
    read = len([d for d in done if 1 <= d <= count])
    said = f"Day {now} of {count}. {read} {'day' if read == 1 else 'days'} read."
    return f'<span class="lm-pl-dots" role="img" aria-label="{_e(said)}">{"".join(cells)}</span>'


def _streak(n: int) -> str:
    import member_lumen_ui as lm
    if n < 2:
        return ""
    return f'<span class="lm-pl-streak">{lm.ic("flame", 15)}{n} days in a row</span>'


def hero(biz: Dict[str, Any], site, c: Dict[str, Any], *, ticks: Optional[set], pool: List[str],
         today: Optional[date] = None) -> str:
    """Continue (screen 1's top): the plan the member is in. `ticks` the
    days read of a reading-style plan (None: they couldn't be read)."""
    import devotionals as dv
    import member_app_photos as photos
    import member_app_ui as ui
    import reading_plans as rp
    art, cls = "", ""
    if c["kind"] == "devotional":
        d, st = c["dev"], c["st"]
        n, count, now = _target(st["now"], st["upto"], st["done"]), st["count"], st["now"]
        days = d.get("days") or []
        day = days[now - 1] if 1 <= now <= len(days) and isinstance(days[now - 1], dict) else {}
        title = d.get("title") or "Devotional"
        sub = " · ".join(p for p in ((day.get("title") or "").strip(), (day.get("scripture") or "").strip()) if p)
        href = f"/my/bible/plans/{d['id']}/{n}"
        done = st["done"]
        streak = dv.streak(done, max(st["upto"], 1))
        url, _look = photos.choose(biz, f"devotional:{d['id']}", pool, title=title, look="church")
        if url:
            art, cls = ui.photo(url, look="church", eager=True), " has-ph"
    elif c["kind"] == "own":
        plan = c["plan"]
        key = plan["key"]
        m = meta(key) or {}
        now = plan_day(plan, today or date.today()) or 1
        count = plan["days"]
        done = ticks
        upto = rp.readable_upto(plan, today)
        n = _target(now, upto, done)
        title = m.get("title") or plan["title"]
        sub = (f"{day_title(key, now)} · {day_label(key, now)}" if m.get("kind") == "topic"
               else f"Today: {day_label(key, now)}")
        href = f"/my/bible/plans/{key}/{n}"
        streak = rp.streak(done, now) if done is not None else 0
        if m.get("kind") == "topic":
            cls = f" tp-{m['hue']}"
            art = f'<span class="lm-pl-mark">{_glyph(m["icon"], 120)}</span>'
    else:
        t = c["today"]
        now = n = t["day"]
        count = t["of"]
        done = ticks
        title = t["title"]
        sub = f"With your church · {t['label']}"
        href = t["href"]
        streak = rp.streak(done, now) if done is not None else 0
    foot = f'<a class="lm-pl-go" href="{_e(href)}">Read day {n}</a>{_streak(streak) if done is not None else ""}'
    return (f'<section class="lm-pl-hero{cls}" aria-labelledby="lm-pl-hh">{art}<div class="lm-pl-in">'
            f'<p class="lm-pl-k">Continue · Day {now} of {count}</p><h2 class="lm-pl-ht" id="lm-pl-hh">{_e(title)}</h2>'
            + (f'<p class="lm-pl-hs">{_e(sub)}</p>' if sub else "")
            + f'{row(count, now, done)}<div class="lm-pl-hf">{foot}</div></div></section>')


# ─── the tab's shelves ───────────────────────────────────────────────


def covers(biz: Dict[str, Any], site, sts, pool: List[str]) -> str:
    """From <church>: each devotional a square cover, its picture drawn in
    the church's colour with its title in serif over it, or a cover made of
    the church's colour; how many days and what it is under it."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_lumen_bible as mlb
    import member_lumen_ui as lm
    import member_portal_devotionals as mpd
    if not sts:
        return ""
    used: set = set()
    out = []
    for d, st in sts[:COVERS_MAX]:
        title = d.get("title") or "Devotional"
        url, _look = photos.choose(biz, f"devotional:{d['id']}", pool, title=title, look="church", used=used)
        art = (f'<span class="lm-pl-art has-ph">{ui.photo(url, look="church")}<b>{_e(title)}</b></span>' if url else
               f'<span class="lm-pl-art is-made"><b>{_e(title)}</b></span>')
        if st["kind"] == "upcoming" and st["start"]:
            cap = f"Starts {_short_date(st['start'])}"
        else:
            cap = " · ".join(p for p in (_days(st["count"]) if st["count"] else "", (d.get("kind") or "").strip()) if p)
        out.append(f'<a class="lm-pl-cv" href="{_e(mpd._target(d, st))}">{art}<small>{_e(cap)}</small></a>')
    return (f'<section aria-labelledby="lm-pl-fh">{lm.section(f"From {mlb._short(biz)}", "/my/bible/plans?show=church", "See all", hid="lm-pl-fh")}'
            f'<div class="lm-pl-rail">{"".join(out)}</div></section>')


def topics(mine: Optional[Dict[str, date]], today: date) -> str:
    """What are you walking through?: the topic plans, a colour tile each
    with its icon; one the member is in says which day."""
    import member_lumen_ui as lm
    import topic_plans as tp
    tiles = []
    for key, t in tp.TOPICS.items():
        plan = own(key, (mine or {}).get(f"reading:{key}"))
        now = plan_day(plan, today) if plan else None
        status = f"<small>Day {now} of {plan['days']}</small>" if now else ""
        tiles.append(f'<a class="lm-pl-tp tp-{t["hue"]}" href="/my/bible/plans/{key}">'
                     f'<span class="lm-pl-tpi">{_glyph(t["icon"], 22)}</span><b>{_e(t["title"])}</b>{status}</a>')
    return (f'<section aria-labelledby="lm-pl-th">{lm.section("What are you walking through?", hid="lm-pl-th")}'
            f'<div class="lm-pl-topics">{"".join(tiles)}</div></section>')


def shelf(mine: Optional[Dict[str, date]], church_today: Optional[Dict[str, Any]], today: date) -> str:
    """Read the whole Bible: the four reading plans as covers, how many
    days large on each; one the member is in says which day, the church's
    (running) says so and opens the church's plan."""
    import member_lumen_bible as mlb
    import member_lumen_ui as lm
    import reading_plans as rp
    out = []
    for key, m in rp.PLANS.items():
        plan = own(key, (mine or {}).get(f"reading:{key}"))
        now = plan_day(plan, today) if plan else None
        href = f"/my/bible/plans/{key}"
        cap = mlb.plan_title(m["title"])
        status = ""
        if now:
            status = f"Day {now} of {m['days']}"
        elif church_today and church_today.get("key") == key and not plan:
            href, status = "/my/reading", f"With your church · day {church_today['day']}"
        out.append(f'<a class="lm-pl-cv" href="{_e(href)}"><span class="lm-pl-art is-len"><b>{m["days"]}</b>'
                   f'<small>days</small></span><small>{_e(cap)}</small>'
                   + (f'<small class="lm-pl-on">{_e(status)}</small>' if status else "") + "</a>")
    return (f'<section aria-labelledby="lm-pl-bh">{lm.section("Read the whole Bible", hid="lm-pl-bh")}'
            f'<div class="lm-pl-rail">{"".join(out)}</div></section>')


def _together(biz: Dict[str, Any], me: Dict[str, Any], request: Any, c: Dict[str, Any]) -> str:
    """The line under Continue: the group the member reads it with, and how
    many of them do (member_plan_prefs; kept reads)."""
    import member_plan_prefs as mpp
    plan = f"devotional:{c['dev']['id']}" if c["kind"] == "devotional" else f"reading:{c['plan']['key']}"
    got = mpp.choices(biz, me, request, plan)
    if not got or not got[2]:
        return ""
    return mpp.together_line(biz, plan, got[2], mpp.reading_with(biz["id"], got[2]["id"], plan))


# ─── the tab ─────────────────────────────────────────────────────────


async def tab(request: Any, biz: Dict[str, Any], site, me: Dict[str, Any], *, kept_dot: Optional[bool],
              preview: bool = False, today: Optional[date] = None) -> Tuple[str, Optional[bool]]:
    """The Plans tab: (its page, the Devotional dot to keep: True/False, or
    None to leave the cookie alone)."""
    import asyncio
    import member_app_photos as photos
    import member_lumen_bible as mlb
    import reading_plans as rp
    today = today or date.today()
    bid, cid = biz["id"], str(me["id"])
    ver = "" if preview else version(request)
    church_today = rp.today_for(biz, today)
    jobs = {"devs": asyncio.to_thread(catalog, bid),
            "mine": asyncio.to_thread(starts, bid, cid, ver, preview),
            "done": asyncio.to_thread(done_days, bid, cid, ver, preview)}
    got = dict(zip(jobs, await asyncio.gather(*jobs.values(), return_exceptions=True)))
    got = {k: (None if isinstance(v, BaseException) else v) for k, v in got.items()}
    devs, mine, done = got["devs"], got["mine"], got["done"]
    sts = None
    if devs is not None and done is not None:
        # a devotional started on the member's own day needs their starts;
        # without them, only the ones the church dated can say where they are
        usable = devs if mine is not None else [d for d in devs if d.get("starts_on")]
        sts = mlb._sts(usable, done, mine or {}, today, preview)
    c = pick(sts, mine, church_today, today)
    ticks = None
    if c and c["kind"] == "devotional" and not c["dev"].get("days"):
        try:
            full = await asyncio.to_thread(one, bid, c["dev"]["id"])
        except Exception:  # noqa: BLE001
            full = None
        if full:
            c = {**c, "dev": full}
    elif c and c["kind"] == "own":
        try:
            ticks = await asyncio.to_thread(read_days, bid, cid, c["plan"], ver, preview)
        except Exception:  # noqa: BLE001
            ticks = None
    elif c and c["kind"] == "church":
        try:
            ticks = await asyncio.to_thread(read_days, bid, cid, rp.current(biz), ver, preview)
        except Exception:  # noqa: BLE001
            ticks = None
    pool = photos.photos(biz, site)
    together = ""
    if c and c["kind"] in ("devotional", "own") and not preview:
        try:
            together = await asyncio.to_thread(_together, biz, me, request, c)
        except Exception:  # noqa: BLE001  (left out)
            together = ""
    parts: List[str] = ['<h1 class="mp-sr">Plans</h1>']
    if mine is None:
        parts.append('<p class="mp-err lm-btabmsg" role="alert">Your plans couldn\'t load just now. Please try again in a '
                     'moment.</p>')
    if c:
        parts.append(hero(biz, site, c, ticks=ticks, pool=pool, today=today) + together)
    if sts is not None and devs is not None and mine is not None:
        parts.append(covers(biz, site, sts, pool))
    parts.append(topics(mine, today))
    parts.append(shelf(mine, church_today, today))
    keep = None
    dot = bool(kept_dot)
    if sts is not None and mine is not None:
        dot = mlb.devo_unread(sts)
        keep = None if preview else dot
    return mlb._shell_tab(biz, site, me, "Plans", "plans", dot, "".join(p for p in parts if p)), keep


# ─── a plan's page (a reading plan, a topic plan) ────────────────────


def _cover(key: str, m: Dict[str, Any], tr: str) -> str:
    """The plan's cover at the top of its page: its colour (a topic's, or
    the page's own for a reading plan), the kind of plan, its title in serif,
    how many days and about how long a day takes."""
    import member_lumen_bible as mlb
    mins = minutes(key, tr)
    sub = f"{_days(m['count'])} · about {mins} minute{'' if mins == 1 else 's'} a day"
    if m["kind"] == "topic":
        cls, art, kick = f" tp-{m['hue']}", f'<span class="lm-pl-mark">{_glyph(m["icon"], 150)}</span>', f"Topic · {m['word']}"
    else:
        cls, art, kick = " is-len", f'<span class="lm-pp-n" aria-hidden="true">{m["count"]}</span>', "Read the whole Bible"
    title = m["title"] if m["kind"] == "topic" else mlb.plan_title(m["title"])
    return (f'<section class="lm-pp-top{cls}" aria-labelledby="lm-pp-h">{art}<div class="lm-pp-tt">'
            f'<small>{_e(kick)}</small><h1 id="lm-pp-h">{_e(title)}</h1><small>{_e(sub)}</small></div></section>')


def _tick(key: str, n: int, read: bool, live: bool) -> str:
    """A day's circle: a form that marks it read (or not) on the reading
    plans' own route; plain when nothing can save."""
    label = f"Day {n}: mark as not read" if read else f"Day {n}: mark as read"
    if not live:
        return f'<span class="lm-pp-c{" ok" if read else ""}" aria-hidden="true">{n}</span>'
    return (f'<form method="post" action="/my/reading"><input type="hidden" name="day" value="{n}">'
            f'<input type="hidden" name="read" value="{"no" if read else "yes"}">'
            f'<input type="hidden" name="back" value="/my/bible/plans/{key}"><input type="hidden" name="plan" value="{key}">'
            f'<button class="lm-pp-c{" ok" if read else ""}" type="submit" aria-label="{label}" '
            f'aria-pressed="{"true" if read else "false"}">{n}</button></form>')


def _day_row(key: str, n: int, plan: Optional[Dict[str, Any]], done: set, upto: int, now: Optional[int],
             live: bool) -> str:
    import reading_plans as rp
    import topic_plans as tp
    read = n in done
    shut = bool(plan) and n > upto
    title = day_title(key, n) if tp.is_topic(key) else day_label(key, n)
    sub = day_label(key, n) if tp.is_topic(key) else f"Day {n}"
    if n == now:
        sub += " · today"
    elif shut and plan:
        sub += f" · opens {_short_date(plan['start'] + timedelta(days=n - 1))}"
    cls = " ".join(c for c in ("is-done" if read else "", "is-now" if n == now else "", "is-shut" if shut else "") if c)
    circle = (_tick(key, n, read, live) if plan and not shut else
              f'<span class="lm-pp-c" aria-hidden="true">{n}</span>')
    text = f'<b>{_e(title)}</b><small>{_e(sub)}</small>'
    to = f"/my/bible/plans/{key}/{n}" if plan else day_href(key, n)
    body = (f'<span class="lm-pp-dt">{text}</span>' if shut else
            f'<a class="lm-pp-dt" href="{_e(to)}">{text}</a>')
    return f'<li class="lm-pp-d{" " + cls if cls else ""}">{circle}{body}</li>'


def render_plan(biz: Dict[str, Any], site, request: Any, me: Dict[str, Any], key: str,
                started: Optional[date], done: Optional[set], *, tr: str = "kjv", preview: bool = False,
                failed: bool = False, today: Optional[date] = None, prefs=None) -> str:
    """A reading plan's or a topic plan's page (screen 2). `started` None:
    not started; `done` the days read of this run (None: couldn't be read);
    `failed`: whether they started it couldn't be read."""
    import member_app_ui as ui
    import member_lumen_bible as mlb
    import member_portal_reading as mpr
    import reading_plans as rp
    from member_portal import _shell
    today = today or date.today()
    m = meta(key)
    plan = own(key, started)
    count = m["count"]
    upto = rp.readable_upto(plan, today) if plan else 0
    now = rp.day_number(plan, today) if plan else None
    live = bool(plan) and done is not None and not preview
    acts = ""
    note = ""
    if failed:
        note = ('<p class="mp-err" role="alert">Your plan couldn\'t load just now, so nothing here will save. Please try '
                'again in a moment.</p>')
    elif not plan:
        acts = (f'<form method="post" action="/my/bible/plans/start"><input type="hidden" name="plan" value="reading:{key}">'
                f'<button class="lm-btn" type="submit"{" disabled" if preview else ""}>Start</button></form>')
        note = f'<p class="lm-pp-fine">A day opens each day from the day you start: {_days(count)}.</p>'
    elif done is None:
        note = ('<p class="mp-err" role="alert">Your days couldn\'t load just now, so nothing here will save. Please try '
                'again in a moment.</p>')
    elif len([d for d in done if 1 <= d <= count]) >= count:
        note = (f'<div class="lm-pp-fin"><span class="lm-pp-c ok" aria-hidden="true">{ui.icon("check", 16)}</span>'
                f'<span><b>You finished it</b><small>Every day is still here to read again.</small></span></div>')
    elif upto:
        n = _target(now, upto, done)
        acts = f'<a class="lm-btn" href="/my/bible/plans/{key}/{n}">{"Continue" if done else "Read"} day {n}</a>'
    else:
        note = f'<p class="lm-pp-fine">Day 1 opens {_short_date(plan["start"])}.</p>'
    if plan and done is not None and not preview and not failed and plan["start"] < today:
        acts += over(f"reading:{key}", "Day 1 opens again today, and the plan runs from here. The days you marked "
                                       "read stay with the start you're leaving.")
    days = done or set()
    if count <= LIST_ALL or not plan:
        shown = range(1, min(count, LIST_ALL) + 1) if not plan else range(1, count + 1)
        rows = "".join(_day_row(key, n, plan, days, upto, now, live) for n in shown)
        more = ""
        if not plan and count > LIST_ALL:
            more = f'<p class="lm-pp-fine">And on, a day at a time, to day {count}.</p>'
    else:
        here = now or upto or 1
        first, last = max(1, here - 6), min(count, here + 7)
        rows = "".join(_day_row(key, n, plan, days, upto, now, live) for n in range(first, last + 1))
        missed = [d for d in range(1, first) if d not in days][-14:]
        more = ""
        if missed and live:
            more = (f'<details class="lm-catch"><summary>{len(missed)} {"day" if len(missed) == 1 else "days"} to catch up'
                    f'{ui.icon("chevron", 16)}</summary><ol class="lm-pp-days">'
                    + "".join(_day_row(key, n, plan, days, upto, now, live) for n in missed) + "</ol></details>")
    stop = ""
    if plan and not preview and not failed:
        stop = (f'<form method="post" action="/my/bible/plans/stop" class="lm-stop"><input type="hidden" name="plan" '
                f'value="reading:{key}"><input type="hidden" name="back" value="tab">'
                f'<button class="lm-txtbtn" type="submit">Stop this plan</button></form>')
    body = (f'<a class="mb-back" href="/my/bible?tab=plans">{ui.icon("back", 16)}Plans</a>'
            f'{_cover(key, m, tr)}<p class="lm-pp-about">{_e(m["about"])}</p>'
            f'{mpr._flash(request)}' + (f'<div class="lm-pp-acts">{acts}</div>' if acts else "") + note
            + _prefs_rows(biz, f"reading:{key}", prefs, started=bool(plan) and not failed)
            + f'<section aria-labelledby="lm-pp-dh"><h2 class="mp-sr" id="lm-pp-dh">The days</h2>'
            f'<ol class="lm-pp-days">{rows}</ol>{more}</section>{stop}')
    return _shell(biz, site, m["title"], body, tab="bible", who=me)


def _own_flash(request: Any) -> str:
    """The notices of this page's own forms (Start over, read with, remind;
    a day's form sent for a day not open yet)."""
    import member_portal_reading as mpr
    q = request.query_params
    return mpr._flash(request) if q.get("done") in ("over", "with", "remind", "remind_off") or q.get("err") == "day" else ""


def _prefs_rows(biz: Dict[str, Any], plan: str, prefs, *, started: bool) -> str:
    """Remind me and who you read with (member_plan_prefs); '' until its
    table is there, or when a read failed."""
    if not prefs:
        return ""
    import member_plan_prefs as mpp
    return mpp.rows_html(biz, plan, prefs, started=started)


def over(plan: str, words: str) -> str:
    """Start over: a quiet button that opens to say what it does, then the
    form that does it (no script needed)."""
    return (f'<details class="lm-pp-over"><summary>Start over</summary><p>{_e(words)}</p>'
            f'<form method="post" action="/my/bible/plans/over"><input type="hidden" name="plan" value="{_e(plan)}">'
            f'<button class="lm-btn sm" type="submit">Start over today</button></form></details>')


def _dev_minutes(dev: Dict[str, Any]) -> int:
    import devotionals as dv
    days = [d for d in dev.get("days") or [] if isinstance(d, dict)]
    return max(1, round(sum(dv.minutes(d) for d in days) / len(days))) if days else 0


def render_devotional(biz: Dict[str, Any], site, request: Any, me: Dict[str, Any], dev: Dict[str, Any],
                      st: Dict[str, Any], *, today: Optional[date] = None, prefs=None) -> str:
    """A church devotional's page (screen 2): its cover (the church's
    picture for it in the church's colour, or a cover of that colour), the
    church and what kind of devotional, how many days and about how long a
    day takes, what it's about, Start or Continue day N (or when the church
    starts it, or You finished it), Start over, and every day with its
    scripture and whether it's read. `st` is where the member is in it
    (member_portal_devotionals.state)."""
    import devotionals as dv
    import member_app_photos as photos
    import member_app_ui as ui
    import member_lumen_bible as mlb
    import member_portal_church as mpc
    from member_portal import _shell
    today = today or date.today()
    short = mlb._short(biz)
    title = dev.get("title") or "Devotional"
    count, done, upto, now = st["count"], st["done"], st["upto"], st["now"]
    url, _look = photos.choose(biz, f"devotional:{dev['id']}", photos.photos(biz, site), title=title, look="church")
    art = ui.photo(url, look="church", eager=True) if url else ""
    mins = _dev_minutes(dev)
    sub = _days(count) + (f" · about {mins} minute{'' if mins == 1 else 's'} a day" if mins else "")
    kind = (dev.get("kind") or "").strip() or "Devotional"
    top = (f'<section class="lm-pp-top{" has-ph" if url else " is-made"}" aria-labelledby="lm-pp-h">{art}'
           f'<div class="lm-pp-tt"><small>{_e(short)} · {_e(kind)}</small><h1 id="lm-pp-h">{_e(title)}</h1>'
           f'<small>{_e(sub)}</small></div></section>')
    about = "".join(f"<p>{_e(p)}</p>" for p in dv.paragraphs(dev.get("about") or ""))
    k, preview = st["kind"], st["preview"]
    acts, note = "", ""
    if k == "new":
        acts = (f'<form method="post" action="/my/bible/plans/start"><input type="hidden" name="plan" '
                f'value="devotional:{_e(dev["id"])}"><button class="lm-btn" type="submit"{" disabled" if preview else ""}>'
                f'Start</button></form>')
        note = f'<p class="lm-pp-fine">A day opens each day from the day you start: {_days(count)}.</p>'
    elif k == "upcoming":
        note = (f'<p class="lm-pp-fine">{_e(short)} starts it together on {_e(_short_date(st["start"]))}. Day 1 opens '
                f'that morning.</p>')
    elif k == "finished":
        note = (f'<div class="lm-pp-fin"><span class="lm-pp-c ok" aria-hidden="true">{ui.icon("check", 16)}</span>'
                f'<span><b>You finished it</b><small>Every day is still here to read again.</small></span></div>')
        acts = f'<a class="lm-btn" href="/my/bible/plans/{_e(dev["id"])}/1">Read it again</a>'
    elif upto:
        n = _target(now, upto, done)
        acts = f'<a class="lm-btn" href="/my/bible/plans/{_e(dev["id"])}/{n}">{"Continue" if done else "Read"} day {n}</a>'
    if not preview and done:
        words = ("The days you marked read are cleared, so you can walk through it again on the church's days. "
                 "Your journal stays." if dev.get("starts_on") else
                 "Day 1 opens again today, and the days you marked read are cleared. Your journal stays.")
        acts += over(f"devotional:{dev['id']}", words)
    days = dev.get("days") or []
    rows = []
    for n in range(1, count + 1):
        day = days[n - 1] if n <= len(days) and isinstance(days[n - 1], dict) else {}
        name = (day.get("title") or "").strip() or f"Day {n}"
        bits = [(day.get("scripture") or "").strip()]
        shut = n > upto
        if n == now:
            bits.append("today")
        elif shut and st["start"]:
            bits.append(f"opens {_short_date(dv.day_on(st['start'], n))}")
        elif shut:
            bits.append("opens after you start")
        sub = " · ".join(b for b in bits if b)
        cls = " ".join(c for c in ("is-done" if n in done else "", "is-now" if n == now else "",
                                   "is-shut" if shut else "") if c)
        circle = f'<span class="lm-pp-c{" ok" if n in done else ""}" aria-hidden="true">{n}</span>'
        said = f"Day {n}" + (", read" if n in done else "") + f": {name}"
        text = f'<b>{_e(name)}</b><small>{_e(sub)}</small>'
        body = (f'<span class="lm-pp-dt">{text}</span>' if shut else
                f'<a class="lm-pp-dt" href="/my/bible/plans/{_e(dev["id"])}/{n}" aria-label="{_e(said)}">{text}</a>')
        rows.append(f'<li class="lm-pp-d{" " + cls if cls else ""}">{circle}{body}</li>')
    page = (f'<a class="mb-back" href="/my/bible?tab=plans">{ui.icon("back", 16)}Plans</a>{top}'
            + (f'<div class="lm-pp-about">{about}</div>' if about else "")
            + (_own_flash(request) or mpc._flash(request)) + (f'<div class="lm-pp-acts">{acts}</div>' if acts else "") + note
            + _prefs_rows(biz, f"devotional:{dev['id']}", prefs, started=k not in ("new", "upcoming"))
            + f'<section aria-labelledby="lm-pp-dh"><h2 class="mp-sr" id="lm-pp-dh">The days</h2>'
            f'<ol class="lm-pp-days">{"".join(rows)}</ol></section>')
    return _shell(biz, site, title, page, tab="bible", who=me)


async def day_page(request: Any, biz: Dict[str, Any], site, me: Dict[str, Any], key: str, raw: str, *,
                   tr: str = "kjv", preview: bool = False):
    """GET /my/bible/plans/<reading or topic plan>/<n> under the new look: a
    day of a plan the member started, open (today's or before), else back to
    the plan's page. (html, status) or a redirect."""
    import asyncio
    import member_lumen_plan_day as mlpd
    import reading_plans as rp
    from fastapi.responses import RedirectResponse
    from member_portal import _SECURE_HEADERS
    bid, cid = biz["id"], str(me["id"])
    ver = "" if preview else version(request)
    mine = await asyncio.to_thread(starts, bid, cid, ver, preview)
    plan = own(key, (mine or {}).get(f"reading:{key}"))
    if preview:
        # The owner's preview sees every day, as started long enough ago, and saves nothing.
        m = meta(key) or {}
        plan = own(key, date.today() - timedelta(days=max(0, int(m.get("count") or 1) - 1)))
    back = RedirectResponse(f"/my/bible/plans/{key}", status_code=303, headers=_SECURE_HEADERS)
    if mine is None or not plan or not raw.isdigit():
        return back
    n = int(raw)
    if not 1 <= n <= rp.readable_upto(plan):
        return back
    done = await asyncio.to_thread(read_days, bid, cid, plan, ver, preview)
    html = mlpd.render_plan_day(biz, site, request, me, key, n, plan, done, tr=tr, preview=preview)
    return html, (503 if done is None else 200)


async def plan_page(request: Any, biz: Dict[str, Any], site, me: Dict[str, Any], key: str, *, tr: str = "kjv",
                    preview: bool = False):
    """GET /my/bible/plans/<reading or topic plan> under the new look:
    (html, status)."""
    import asyncio
    bid, cid = biz["id"], str(me["id"])
    ver = "" if preview else version(request)
    mine = await asyncio.to_thread(starts, bid, cid, ver, preview)
    started = (mine or {}).get(f"reading:{key}")
    plan = own(key, started)
    done = None
    if plan:
        done = await asyncio.to_thread(read_days, bid, cid, plan, ver, preview)
    prefs = None
    if mine is not None:
        import member_plan_prefs as mpp
        try:
            prefs = await asyncio.to_thread(mpp.choices, biz, me, request, f"reading:{key}", preview=preview)
        except Exception:  # noqa: BLE001  (the rows are left out)
            prefs = None
    html = render_plan(biz, site, request, me, key, started, done, tr=tr, preview=preview, failed=mine is None,
                       prefs=prefs)
    return html, (503 if mine is None or (plan and done is None) else 200)


# ─── the look ────────────────────────────────────────────────────────
# The church's colour carries the Continue card and the covers made of it;
# a topic keeps its own colour whatever the church's (a topic's tile means
# the same thing everywhere), deep enough for white words in both looks.
# Everything else is the page's own tokens, so Light, Dark and Same as my
# phone turn with it.
CSS = """
/* plans (member_lumen_plans) */
body.lm .lm-pl-hero,body.lm .lm-pp-top{--pl-a:var(--acc-fill);--pl-b:var(--acc-night);}
body.lm .tp-a{--pl-a:#4A4FA6;--pl-b:#1F2152;}
body.lm .tp-b{--pl-a:#2F7E9C;--pl-b:#103645;}
body.lm .tp-c{--pl-a:#A06A1F;--pl-b:#45290A;}
body.lm .tp-d{--pl-a:#A02B5E;--pl-b:#4A0E28;}
body.lm .tp-e{--pl-a:#357A54;--pl-b:#12341F;}
body.lm .tp-f{--pl-a:#6A45A0;--pl-b:#2A1747;}
/* Continue */
body.lm .lm-pl-hero{position:relative;display:flex;align-items:flex-end;min-height:250px;margin-top:16px;border-radius:22px;overflow:hidden;
  background:linear-gradient(160deg,var(--pl-a) 0%,var(--pl-b) 100%);color:#fff;isolation:isolate;}
body.lm .lm-pl-hero>.mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;z-index:-2;}
body.lm .lm-pl-hero>.mb-ph img{width:100%;height:100%;object-fit:cover;}
body.lm .lm-pl-hero::before{content:"";position:absolute;inset:0;z-index:-1;
  background:linear-gradient(180deg,rgba(0,0,0,0) 0%,rgba(0,0,0,.18) 34%,rgba(0,0,0,.7) 100%);}
body.lm .lm-pl-hero.has-ph::before{background:linear-gradient(180deg,rgba(0,0,0,.08) 0%,rgba(0,0,0,.5) 42%,rgba(0,0,0,.86) 100%);}
body.lm .lm-pl-mark{position:absolute;right:-18px;top:-14px;z-index:-1;color:rgba(255,255,255,.14);}
body.lm .lm-pl-mark .lm-ic{display:block;}
body.lm .lm-pl-in{display:grid;gap:8px;width:100%;padding:18px 16px 16px;}
body.lm .lm-pl-k{margin:0;font:700 10.5px/1.2 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:#FFE1A6;}
body.lm .lm-pl-ht{margin:0;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:28px;line-height:1.06;letter-spacing:var(--lm-dtr);
  font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);color:#fff;text-wrap:balance;}
body.lm .lm-pl-hs{margin:0;font:500 13.5px/1.4 var(--mb-ui);color:rgba(255,255,255,.86);}
body.lm .lm-pl-dots{display:flex;gap:6px;margin-top:4px;}
body.lm .lm-pl-dots i{width:28px;height:28px;flex:none;border-radius:50%;display:grid;place-items:center;font:700 11.5px/1 var(--mb-ui);
  font-style:normal;color:#fff;box-shadow:inset 0 0 0 1.5px rgba(255,255,255,.4);}
body.lm .lm-pl-dots i.ok{background:#fff;color:var(--pl-b);box-shadow:none;}
body.lm .lm-pl-dots i.now{box-shadow:inset 0 0 0 1.5px #FFE1A6,0 0 0 3px rgba(255,225,166,.3);}
body.lm .lm-pl-dots i.ok.now{box-shadow:0 0 0 3px rgba(255,225,166,.45);}
body.lm .lm-pl-hf{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:6px;}
body.lm .lm-pl-go{display:inline-flex;align-items:center;height:40px;padding:0 18px;border-radius:20px;background:#fff;color:#141414;
  font:700 14px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;}
body.lm .lm-pl-streak{display:inline-flex;align-items:center;gap:6px;font:650 12.5px/1.2 var(--mb-ui);color:#FFE1A6;text-align:right;}
/* the rails of covers */
body.lm .lm-pl-rail{display:flex;gap:12px;margin:0 -20px;padding:0 20px 4px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding:0 20px;scrollbar-width:none;}
body.lm .lm-pl-rail::-webkit-scrollbar{display:none;}
body.lm .lm-pl-cv{flex:none;width:128px;display:grid;align-content:start;gap:6px;color:var(--fg);text-decoration:none;scroll-snap-align:start;}
body.lm .lm-pl-cv>small{font:500 12px/1.3 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pl-cv>small.lm-pl-on{margin-top:-3px;font-weight:650;color:var(--acc);}
body.lm .lm-pl-art{position:relative;display:flex;align-items:flex-end;aspect-ratio:1;border-radius:16px;overflow:hidden;isolation:isolate;
  background:linear-gradient(160deg,var(--acc-fill),var(--acc-night));color:#fff;}
body.lm .lm-pl-art>.mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;z-index:-2;}
body.lm .lm-pl-art>.mb-ph img{width:100%;height:100%;object-fit:cover;}
body.lm .lm-pl-art.has-ph::before{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,rgba(0,0,0,0) 30%,rgba(0,0,0,.62) 100%);}
body.lm .lm-pl-art.is-made::before{content:"";position:absolute;inset:0;z-index:-1;
  background:radial-gradient(circle at 82% 14%,rgba(255,255,255,.26) 0 18%,transparent 19%),
    repeating-radial-gradient(circle at 82% 14%,transparent 0 22px,rgba(255,255,255,.08) 22px 23px);}
body.lm .lm-pl-art b{padding:10px;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:16px;line-height:1.08;
  font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);text-shadow:0 1px 8px rgba(0,0,0,.35);overflow-wrap:anywhere;}
body.lm .lm-pl-art.is-len{flex-direction:column;align-items:flex-start;justify-content:flex-end;gap:2px;padding:12px;background:var(--s1);
  color:var(--fg);box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-pl-art.is-len b{padding:0;font-size:34px;line-height:1;text-shadow:none;}
body.lm .lm-pl-art.is-len small{font:700 10.5px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-gold);}
/* the topics */
body.lm .lm-pl-topics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;}
body.lm .lm-pl-tp{position:relative;display:flex;flex-direction:column;justify-content:flex-end;gap:2px;aspect-ratio:1/1.02;padding:10px;
  border-radius:16px;overflow:hidden;background:linear-gradient(160deg,var(--pl-a),var(--pl-b));color:#fff;text-decoration:none;}
body.lm .lm-pl-tpi{position:absolute;top:10px;left:10px;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;
  background:rgba(255,255,255,.14);}
body.lm .lm-pl-tp b{font:700 14px/1.15 var(--mb-ui);}
body.lm .lm-pl-tp small{font:600 11.5px/1.2 var(--mb-ui);color:rgba(255,255,255,.82);}
/* a plan's page */
body.lm .lm-pp-top{position:relative;display:flex;align-items:flex-end;min-height:220px;margin-top:8px;border-radius:22px;overflow:hidden;
  isolation:isolate;background:linear-gradient(160deg,var(--pl-a),var(--pl-b));color:#fff;}
body.lm .lm-pp-top.is-len{background:var(--s1);color:var(--fg);box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-pp-n{position:absolute;right:14px;top:4px;z-index:-1;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:120px;line-height:1;
  font-variation-settings:var(--lm-dvar);color:var(--lm-gold);opacity:.32;}
body.lm .lm-pp-top .lm-pl-mark{right:-24px;top:-20px;}
body.lm .lm-pp-tt{display:grid;gap:6px;padding:18px 16px 16px;}
body.lm .lm-pp-tt small{font:600 12px/1.3 var(--mb-ui);color:rgba(255,255,255,.86);}
body.lm .lm-pp-tt small:first-child{font-weight:700;font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:#FFE1A6;}
body.lm .lm-pp-top.is-len .lm-pp-tt small{color:var(--fg2);}
body.lm .lm-pp-top.is-len .lm-pp-tt small:first-child{color:var(--lm-gold);}
body.lm .lm-pp-tt h1{margin:0;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:32px;line-height:1.04;letter-spacing:var(--lm-dtr);
  font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);text-wrap:balance;}
body.lm .lm-pp-about{margin:16px 0 0;font:400 15px/1.55 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;}
body.lm .lm-pp-acts form{margin:0;}
body.lm .lm-pp-top>.mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;z-index:-2;}
body.lm .lm-pp-top>.mb-ph img{width:100%;height:100%;object-fit:cover;}
body.lm .lm-pp-top.has-ph::before{content:"";position:absolute;inset:0;z-index:-1;
  background:linear-gradient(180deg,rgba(0,0,0,.05) 0%,rgba(0,0,0,.45) 45%,rgba(0,0,0,.85) 100%);}
body.lm .lm-pp-top.is-made::before{content:"";position:absolute;inset:0;z-index:-1;
  background:radial-gradient(circle at 84% 16%,rgba(255,255,255,.22) 0 14%,transparent 15%),
    repeating-radial-gradient(circle at 84% 16%,transparent 0 30px,rgba(255,255,255,.07) 30px 31px);}
body.lm .lm-pp-about p{margin:16px 0 0;font:400 15px/1.55 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-acts{align-items:center;}
body.lm .lm-pp-over{display:block;}
body.lm .lm-pp-over[open]{flex-basis:100%;}
body.lm .lm-pp-over>summary{display:inline-flex;align-items:center;height:48px;padding:0 18px;border-radius:24px;list-style:none;
  cursor:pointer;box-shadow:inset 0 0 0 1px var(--lm-line);color:var(--fg);font:650 15px/1 var(--mb-ui);}
body.lm .lm-pp-over>summary::-webkit-details-marker{display:none;}
body.lm .lm-pp-over[open]>summary{background:var(--s1);}
body.lm .lm-pp-over>p{margin:12px 0 0;font:500 13.5px/1.45 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-over>form{margin:10px 0 0;}
body.lm .lm-pp-over>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
body.lm .lm-pp-opt{display:flex;align-items:center;gap:10px;margin-top:16px;padding:12px 14px;border-radius:16px;background:var(--s1);}
body.lm .lm-pp-optt{flex:1;min-width:0;display:grid;gap:2px;}
body.lm .lm-pp-optt b{font:650 15px/1.25 var(--mb-ui);color:var(--fg);}
body.lm .lm-pp-optt small{font:500 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-opt select{height:36px;max-width:112px;padding:0 8px;border:0;border-radius:10px;background:var(--bg);color:var(--fg);
  box-shadow:inset 0 0 0 1px var(--lm-line);font:600 14px/1 var(--mb-ui);}
body.lm .lm-pp-with{margin-top:14px;}
body.lm .lm-pp-wk{margin:0;font:700 10.5px/1.3 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg2);}
body.lm .lm-pp-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;}
body.lm .lm-pp-chips button{padding:8px 13px;border:0;border-radius:999px;background:none;box-shadow:inset 0 0 0 1px var(--lm-line);
  color:var(--fg);font:650 13px/1 var(--mb-ui);cursor:pointer;}
body.lm .lm-pp-chips button[aria-pressed=true]{background:var(--fg);color:var(--bg);box-shadow:none;}
body.lm .lm-pp-chips button:focus-visible,body.lm .lm-pp-opt select:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
body.lm .lm-pl-tog{display:flex;align-items:center;gap:12px;margin-top:12px;padding:12px 14px;border-radius:16px;
  box-shadow:inset 0 0 0 1px var(--lm-line);color:var(--fg);text-decoration:none;}
body.lm .lm-pl-tog>.lm-ic{flex:none;color:var(--acc);}
body.lm .lm-pl-tog span{display:grid;gap:2px;}
body.lm .lm-pl-tog b{font:650 14px/1.3 var(--mb-ui);}
body.lm .lm-pl-tog small{font:500 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-fine{margin:12px 0 0;font:500 13px/1.4 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-fin{display:flex;align-items:center;gap:12px;margin-top:16px;padding:14px;border-radius:18px;background:var(--lm-tint);}
body.lm .lm-pp-fin b{display:block;font:700 15px/1.25 var(--mb-ui);}
body.lm .lm-pp-fin small{display:block;margin-top:2px;font:500 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-days{margin:20px 0 0;padding:0;list-style:none;border-top:1px solid var(--lm-line);}
body.lm .lm-catch .lm-pp-days{margin-top:6px;}
body.lm .lm-pp-d{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--lm-line);}
body.lm .lm-pp-d form{margin:0;}
body.lm .lm-pp-c{width:32px;height:32px;flex:none;border:0;border-radius:50%;display:grid;place-items:center;padding:0;background:none;
  font:700 12px/1 var(--mb-ui);color:var(--fg2);box-shadow:inset 0 0 0 1.5px var(--s3);cursor:pointer;}
body.lm span.lm-pp-c{cursor:default;}
body.lm .lm-pp-c.ok{background:#2F7A4E;color:#fff;box-shadow:none;}
body.lm .lm-pp-d.is-now .lm-pp-c{color:var(--fg);box-shadow:inset 0 0 0 1.5px var(--acc),0 0 0 3px var(--lm-tint-12);}
body.lm .lm-pp-d.is-now .lm-pp-c.ok{box-shadow:0 0 0 3px var(--lm-tint-12);}
body.lm .lm-pp-d.is-shut .lm-pp-c{opacity:.55;}
body.lm .lm-pp-dt{flex:1;min-width:0;display:grid;gap:2px;color:var(--fg);text-decoration:none;}
body.lm .lm-pp-dt b{font:650 15px/1.25 var(--mb-ui);}
body.lm .lm-pp-dt small{font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pp-d.is-shut .lm-pp-dt{color:var(--fg2);}
body.lm .lm-pl-go:focus-visible,body.lm .lm-pl-cv:focus-visible,body.lm .lm-pl-tp:focus-visible,body.lm .lm-pp-c:focus-visible,
body.lm .lm-pp-dt:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-pl-go,body.lm .lm-pl-cv,body.lm .lm-pl-tp,body.lm .lm-pp-c{transition:transform .15s ease,background-color .2s ease;}
  body.lm .lm-pl-go:active,body.lm .lm-pl-cv:active,body.lm .lm-pl-tp:active,body.lm .lm-pp-c:active{transform:scale(.97);}
}
""" + _dark("""
body.lm.lm-dark .lm-pp-c.ok{background:#3C8A5C;}
""")
