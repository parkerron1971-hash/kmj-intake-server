"""member_portal_lumen.py — the new look's own pages: Home and Connect.

Kevin approved the "clean Lumen" mock on 2026-11-18 (version 29, accent level
2). Who sees it: member_lumen.py (MEMBER_LUMEN). The look: member_lumen_ui.py.
These pages port the mock's layout and read the same data today's pages do;
nothing here is made up, and a block with nothing in it is left out (Home
never says "nothing yet").

HOME (/my), on an ordinary weekday with nothing live: the next gathering on
the church's own photo, edge to edge, with I'm coming; a greeting by the
phone's clock and Coming up; Today (the verse of the day on the ivory card,
with the reading plan or where they left off); the latest message; your
group; prayer; what's happening (the church's news).
  - The day of a gathering, the lead says Today, and while Sunday check-in is
    open its card follows the lead (church_checkin: it shows only then).
  - While the church is live, live wins: Live now on the photo, Join the room.
The rest of today's Home keeps a place: asks to serve and celebrations under
the lead, the church's own tiles after the message, and installing the app,
phone alerts and Ask the church at the foot. The Messages card is gone: the
bubble at the top carries the unread count.

CONNECT (/my/connect), the people hub: your group, serving (your next date,
with Can't make it), prayer, events, classes (with how far you've come),
your next step (the "I'm new here" card leads it once that lands:
member_lumen.new_here_card), find a group, the directory and news. Read at
once from the readers today's pages use (member_portal_church.groups_for and
upcoming_for, member_portal_classes.classes_for, sunday_serving.mine,
member_asks.entry).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("member_portal_lumen")


def _e(s: Any) -> str:
    from html import escape
    return escape(str(s if s is not None else ""), quote=True)


def _day(iso: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _answer(o: Dict[str, Any]) -> str:
    import member_portal_church as mpc
    a = mpc._my_answer(o)
    return "You're coming" if a == "Going" else a


# ─── Home ────────────────────────────────────────────────────────────


def _when(d: date, today: date) -> str:
    n = (d - today).days
    day = f"{d.strftime('%B')} {d.day}"
    if n <= 0:
        return f"Today · {d.strftime('%A')}, {day}"
    if n == 1:
        return f"Tomorrow · {d.strftime('%A')}, {day}"
    if n < 7:
        return f"This {d.strftime('%A')} · {day}"
    return f"{d.strftime('%A')}, {day}"


def _going(count: int, answered: bool) -> str:
    """How many are coming: a number, never names, and only from two."""
    import member_lumen_ui as lm
    if count < 2:
        return ""
    words = (f"You and {count - 1} other{'' if count == 2 else 's'}" if answered else f"{count} coming")
    return f'<span class="lm-count">{lm.ic("people", 18)}{_e(words)}</span>'


def lead(occasions: Optional[List[Dict[str, Any]]], live: Optional[Dict[str, Any]], *, pic: str, look: str,
         church: str, today: Optional[date] = None, edit: bool = False) -> Tuple[str, str]:
    """Home's top: (the photo and the lead block under it, the entry id of the
    gathering it leads with, '' for none). Live wins; then the next thing on
    the calendar; then the church itself."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_ui as lm
    today = today or date.today()
    pin = ui.pin("/my/pictures/spot?key=home&amp;back=home") if edit else ""
    if live:
        photo = (f'<figure class="lm-bleed lm-hero">{ui.picture(pic, look, "worship", eager=True)}{pin}'
                 f'<span class="lm-livechip"><i class="lm-dotlive"></i>Live now</span></figure>')
        block = (f'<section class="lm-lead" aria-labelledby="lm-lead-h">'
                 f'<p class="lm-eyebrow"><span class="lm-dot lm-dotlive"></span>Live now</p>'
                 f'<h1 class="lm-disp" id="lm-lead-h">{lm.italic_last(live.get("title") or "Live now")}</h1>'
                 f'<p class="lm-meta">Watch and chat with your church</p>'
                 f'<div class="lm-row2"><a class="lm-btn" href="/my/live">Join the room</a></div></section>')
        return photo + block, ""
    o = (occasions or [None])[0]
    d = _day((o or {}).get("date") or "")
    photo = f'<figure class="lm-bleed lm-hero">{ui.picture(pic, look, "welcome", eager=True)}{pin}</figure>'
    if not o or not d:
        block = (f'<section class="lm-lead" aria-labelledby="lm-lead-h"><p class="lm-eyebrow">Welcome home</p>'
                 f'<h1 class="lm-disp" id="lm-lead-h">{lm.italic_last(church)}</h1>'
                 f'<p class="lm-meta">Messages, prayer and your church family, all week.</p>'
                 f'<div class="lm-row2"><a class="lm-btn" href="/my/sermons">Watch a message</a>'
                 f'<a class="lm-btn ghost" href="/my/bible">Read</a></div></section>')
        return photo + block, ""
    eid = _e(o.get("entry_id"))
    sample = ui.sample_tag() if samples.is_sample(o) else ""
    hint = ui.sample_hint(samples.WHERE["events"]) if sample else ""
    n = (d - today).days
    meta = " · ".join(_e(x) for x in (o.get("location") or "", f"in {n} days" if n >= 2 else "") if x)
    mine = o.get("mine") or {}
    answer = _answer(o)
    count = int(o.get("attending") or 0)
    about = 'aria-describedby="lm-lead-h"'
    if answer:
        acts = f'<a class="lm-btn going" href="/my/events" {about}>{ui.icon("check", 16)}{_e(answer)}</a>' + _going(count, True)
    elif o.get("signup"):
        su = o["signup"].get("mine") or {}
        acts = (f'<a class="lm-btn going" href="/my/events" {about}>{ui.icon("check", 16)}You\'re signed up</a>'
                if su.get("status") in ("paid", "confirmed") else
                f'<a class="lm-btn" href="/my/events" {about}>Sign up</a>') + _going(count, False)
    elif o.get("full"):
        acts = f'<span class="lm-btn ghost">Full</span><a class="lm-txtbtn" href="/my/events" {about}>Details</a>'
    else:
        said_no = ('<span class="lm-count">You said you can\'t make it</span>' if mine.get("status") == "no" else "")
        acts = (f'<form method="post" action="/my/rsvp"><input type="hidden" name="entry_id" value="{eid}">'
                f'<input type="hidden" name="back" value="/my"><input type="hidden" name="action" value="coming">'
                f'<button class="lm-btn" type="submit" {about}>I\'m coming</button></form>'
                + (said_no or _going(count, False)))
    block = (f'<section class="lm-lead" aria-labelledby="lm-lead-h">'
             f'<p class="lm-eyebrow"><span class="lm-dot"></span>{_e(_when(d, today))}{sample}</p>'
             f'<h1 class="lm-disp" id="lm-lead-h">{lm.italic_last(o.get("title"))}</h1>'
             f'{f"<p class=lm-meta>{meta}</p>" if meta else ""}'
             f'<div class="lm-row2">{acts}</div>{hint}</section>')
    return photo + block, str(o.get("entry_id") or "")


def coming_rows(occasions: Optional[List[Dict[str, Any]]], skip: str = "", top: int = 3) -> str:
    """What's next after the lead, as rows: the date, what, where or their answer."""
    import member_lumen_ui as lm
    rows = []
    for o in occasions or []:
        d = _day(o.get("date") or "")
        if not d or (skip and str(o.get("entry_id")) == skip):
            continue
        answer = _answer(o)
        sub = o.get("location") or o.get("date_label") or ""
        tag = f'<span class="lm-wtag">{_e(answer)}</span>' if answer else ""
        rows.append(lm.row("/my/events", lm.date_box(d), o.get("title") or "", sub, extra=tag))
        if len(rows) == top:
            break
    return "".join(rows)


def verse_page(bible: str) -> str:
    """The verse of the day on the ivory card; '' when none can be read."""
    import bible_text as bt
    import member_portal_bible as mpb
    v = mpb.verse_of_day(bible)
    if not v:
        return ""
    return (f'<a class="lm-page" href="{_e(v["href"])}"><span class="lbl">Verse of the day</span><q>{v["html"]}</q>'
            f'<span class="ref"><span>{_e(v["label"])} · {_e(bt.TRANSLATIONS[bible]["short"])}</span>'
            f'<span>Read the chapter ›</span></span></a>')


def reading_row(today: Optional[Dict[str, Any]], done: Optional[set]) -> str:
    """Today's reading under the verse: the plan's ring, the chapters, and the
    round button that marks it read (member_portal_reading's form)."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_portal_reading as mpr
    import reading_plans as rp
    if not today:
        return ""
    day, of = int(today["day"]), max(1, int(today["of"]))
    read = bool(done) and today["day"] in done
    arc = round(119.4 * min(day, of) / of, 1)
    ring = (f'<span class="lm-ring" aria-hidden="true"><svg viewBox="0 0 46 46"><circle cx="23" cy="23" r="19" fill="none" '
            f'stroke="var(--s2)" stroke-width="3.5"/><circle cx="23" cy="23" r="19" fill="none" stroke="var(--gold)" '
            f'stroke-width="3.5" stroke-linecap="round" stroke-dasharray="{arc} 120"/></svg><b>{day}</b></span>')
    tag = ui.sample_tag() if samples.is_sample(today) else ""
    own = mpr._own_key(today)
    if read:
        tick = f'<span class="lm-circle done" role="img" aria-label="Read today">{ui.icon("check", 18)}</span>'
    else:
        tick = (f'<form method="post" action="/my/reading"><input type="hidden" name="day" value="{day}">'
                f'<input type="hidden" name="read" value="yes"><input type="hidden" name="back" value="/my">'
                + (f'<input type="hidden" name="plan" value="{_e(own)}">' if own in rp.PLANS else "")
                + f'<button class="lm-circle" type="submit" aria-label="Mark today&#x27;s reading as read">'
                f'{ui.icon("check", 18)}</button></form>')
    return (f'<div class="lm-prow"><a href="{_e(today["href"])}">{ring}<span style="flex:1;min-width:0">'
            f'<span class="lm-kicker" style="color:var(--lm-gold)">Reading plan · day {day} of {of}{tag}</span>'
            f'<b>{_e(today["label"])}</b><span class="m">{_e(today["title"])}</span></span></a>{tick}</div>')


def continue_row(where: Optional[Tuple[str, int]], bible: str) -> str:
    """With no plan running: keep reading where they stopped, or John 1."""
    import bible_text as bt
    import member_lumen_ui as lm
    import member_portal_bible as mpb
    code, ch = where if where else ("JOH", 1)
    title = f"Keep reading {mpb.where_label(code, ch)}" if where else "Start with John 1"
    sub = (f"Pick up where you stopped · {bt.TRANSLATIONS[bible]['short']}" if where
           else "A good first book. About five minutes a chapter.")
    kick = "Keep reading" if where else "Start here"
    return (f'<a class="lm-prow" href="/my/bible/{bt.slug(code)}/{ch}">{lm.round_icon("book", "var(--lm-gold)")}'
            f'<span style="flex:1;min-width:0"><span class="lm-kicker" style="color:var(--lm-gold)">{kick}</span>'
            f'<b>{_e(title)}</b><span class="m">{_e(sub)}</span></span>{lm.ic("chevron", 18)}</a>')


def message_tile(lib: Optional[Dict[str, Any]], pal: Dict[str, str], *, site=None, pool=None, used=None,
                 today: Optional[date] = None) -> str:
    """The latest message: its art edge to edge in a tile, the title under it.
    "Last Sunday" when it was preached in the past week, else "Latest message"."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_sermons as mps
    from sermons_public import day_label
    if not lib or not lib.get("sermons"):
        return ""
    s = lib["sermons"][0]
    today = today or date.today()
    d = _day(s.get("preached_on") or "")
    recent = bool(d) and 0 <= (today - d).days <= 7 and d.weekday() == 6
    series = mps._titles(lib).get(str(s.get("series_id") or ""), "")
    sub = " · ".join(x for x in ("Rewatch" if recent else "", s.get("speaker") or "", series,
                                 day_label(s.get("preached_on"))) if x)
    sample = samples.is_sample(s)
    hint = ui.sample_hint(samples.WHERE["sermons"]) if sample else ""
    return (f'<section aria-labelledby="lm-msg-h">{lm.section("Last Sunday" if recent else "Latest message", "/my/sermons", "All messages")}'
            f'{hint}<a class="lm-tile" href="/my/sermons/{_e(s["id"])}"><span class="img">{mps._art(lib, s, pal, site, pool, used)}'
            f'<span class="lm-playdot">{lm.ic("playfill", 18)}</span>{ui.sample_tag() if sample else ""}</span>'
            f'<span class="tt" id="lm-msg-h">{_e(s.get("title"))}</span><span class="tm">{_e(sub)}</span></a></section>')


def group_rows(groups: Optional[Dict[str, List[Dict[str, Any]]]], top: int = 2) -> str:
    """Your group: the groups you're in, when they meet next."""
    import member_app_ui as ui
    import member_lumen_ui as lm
    rows = []
    for g in (groups or {}).get("mine", [])[:top]:
        href = f"/my/groups/live/{g['live']['id']}" if g.get("live") else f"/my/groups/{g['id']}"
        sub = ("Meeting now" if g.get("live") else
               " · ".join(x for x in (g.get("meets") or "", g.get("location") or "") if x))
        if g.get("role") == "leader" and not g.get("live"):
            sub = " · ".join(x for x in ("You lead", sub) if x)
        mini = f'<span class="lm-gmini" aria-hidden="true">{_e(ui.initials(g.get("name")))}</span>'
        rows.append(lm.row(href, mini, g.get("name") or "", sub, cls="lm-pray" if not rows else "lm-wrow"))
    if not rows:
        return ""
    return f'<section aria-labelledby="lm-grp-h">{lm.section("Your group" if len(rows) == 1 else "Your groups", hid="lm-grp-h")}{"".join(rows)}</section>'


def prayer_row(title: str = "How can we pray for you?") -> str:
    import member_lumen_ui as lm
    return (f'<section aria-labelledby="lm-pray-h">{lm.section("Prayer", hid="lm-pray-h")}'
            f'{lm.row("/my/prayer", lm.round_icon("flame"), title, "It goes privately to the pastors.", cls="lm-pray")}</section>')


def render_home(biz: Dict[str, Any], site, *, me: Dict[str, Any], occasions, groups, library, live,
                bible: str, where, plan_today, plan_done, devotional: str = "", checkin: str = "",
                serving: str = "", celebrate: str = "", flash: str = "", news: str = "", news_n: Optional[int] = None,
                cards: Tuple[str, ...] = (), edit: bool = False, editbar: str = "", today: Optional[date] = None) -> str:
    """Home in the new look. `news` is the news block (member_portal_news
    .home_block, titled What's happening), `cards` the small cards at the
    foot (installing the app, phone alerts, Ask the church), each '' to
    leave it out."""
    import member_app_photos as photos
    import member_lumen_ui as lm
    import member_portal_church as mpc
    from member_portal import _shell, first_name, palette_for
    pal = palette_for(biz, site)
    pool = photos.photos(biz, site)
    used: set = set()
    # Full-bleed photos in colour, unless the church chose a look for this one.
    pic, look = photos.choose(biz, "home", pool, fallback=photos.hero(pool), look="colour", used=used)
    church = (biz.get("name") or "").strip() or "Your church"
    top, first = lead(occasions, live, pic=pic, look=look, church=church, today=today, edit=edit)
    hello = first_name(me.get("name") or "") or "there"
    rows = coming_rows(occasions, skip=first)
    is_today = bool(first) and _day((occasions or [{}])[0].get("date") or "") == (today or date.today())
    hint = ("Here's what's next after today." if is_today else "Here's what's coming up.") if rows else ""
    coming = (f'{lm.section("Coming up", "/my/events", "All events")}<div class="lm-list">{rows}</div>' if rows else "")
    hello_html = (f'<div class="lm-hello"><h2 class="lm-disp s" data-first="{_e(hello)}">Hi, <em>{_e(hello)}.</em></h2>'
                  f'{f"<p class=lm-hint>{hint}</p>" if hint else ""}{coming}</div>')
    reading = reading_row(plan_today, plan_done) or continue_row(where, bible)
    today_html = (f'<section aria-labelledby="lm-today-h">{lm.section("Today", "/my/bible/plans", "Plans", hid="lm-today-h")}'
                  f'{verse_page(bible)}{reading}{f"<div class=lm-today-more>{devotional}</div>" if devotional else ""}</section>')
    # The church's own tiles, when it saved some (the ways in every church
    # has, which today's Home shows without them, are on this page already).
    from member_portal import portal_settings
    saved = mpc.clean_tiles(portal_settings(biz.get("settings")).get("tiles"))
    tiles = mpc.home_tiles(biz, site, pool, used, edit=edit) if saved else ""
    check = f'<div class="lm-ck">{checkin}</div>' if checkin else ""
    under = "".join(x for x in (serving, celebrate) if x)
    foot = "".join(c for c in cards if c)
    body = (f'{editbar}{flash}{top}{check}{f"<div class=lm-cards>{under}</div>" if under else ""}'
            f'{hello_html}{today_html}'
            f'{message_tile(library, pal, site=site, pool=pool, used=used, today=today)}'
            f'{tiles}{group_rows(groups)}{prayer_row()}{news}'
            f'{f"<div class=lm-cards>{foot}</div>" if foot else ""}')
    import member_portal_news as mpn
    import member_portal_celebrations as mcl
    script = lm.GREETING_JS + (mpn.RX_JS if news else "") + (mcl.STRIP_JS if celebrate else "")
    style = ""
    if news or celebrate:
        style = f"<style>{mpn.NEWS_CSS}{mcl.CEL_CSS if celebrate else ''}</style>"
    return _shell(biz, site, "Home", style + body, tab="home", who=me, script=script)


# ─── Connect ─────────────────────────────────────────────────────────


async def _nothing():
    return None


def _quiet(fn, *args):
    """A reader whose failure only leaves its block out (None)."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        logger.warning("connect: %s skipped", getattr(fn, "__name__", "a block"), exc_info=True)
        return None


async def connect_data(biz: Dict[str, Any], me: Dict[str, Any], *, preview: bool = False) -> Dict[str, Any]:
    """Everything Connect shows, read at once."""
    import member_app_samples as samples
    import member_portal_church as mpc
    import member_portal_classes as mcl
    import sunday_serving as ssv
    from member_portal import _ask_entry
    bid = biz["id"]
    tab = preview or await asyncio.to_thread(_quiet, mcl.tab_on, bid, me)
    groups, occ, classes, serving, asks = await asyncio.gather(
        asyncio.to_thread(mpc.groups_for, bid, me),
        asyncio.to_thread(mpc.upcoming_for, bid, me),
        asyncio.to_thread(_quiet, mcl.classes_for, bid, me) if tab else _nothing(),
        asyncio.to_thread(_quiet, ssv.mine, biz, str(me["id"])) if ssv.on() and not preview else _nothing(),
        _ask_entry(biz, me))
    return {"groups": samples.fill(groups, "groups", preview), "occasions": samples.fill(occ, "occasions", preview),
            "classes": samples.fill(classes, "classes", preview) if tab else None, "serving": serving,
            "asks": asks or []}


def _group_art(biz: Dict[str, Any], g: Dict[str, Any], pool, used, *, big: bool = True) -> str:
    """A group's picture (the one the church gave it, or a photo named for
    it), else its name in serif on the people colour."""
    import member_app_photos as photos
    import member_app_ui as ui
    pic, look = photos.choose(biz, "group:" + str(g.get("id")), pool or [], title=g.get("name") or "", used=used)
    word = (str(g.get("meets") or "").split() or [""])[0].rstrip(",") if big else ""
    label = word if word[:1].isupper() and word.isalpha() else (g.get("name") or "")
    inner = ui.photo(pic, look=look) if pic else ""
    return f'<span class="lm-gart{" has-ph" if pic else ""}">{inner}<b>{_e(label)}</b></span>'


def _serving_block(m: Optional[Dict[str, Any]]) -> str:
    import member_lumen_ui as lm
    if not m:
        return ""
    coming = m.get("coming") or []
    asks = m.get("asks") or []
    out = []
    if coming:
        c = coming[0]
        at = c["service"]["at"]
        title = c["service"]["title"]
        what = " · ".join(x for x in (c.get("place") or "", title if title not in ("Sunday service", "An event") else "") if x)
        line = c.get("team") or ""
        if c.get("call_time"):
            import member_portal_serving as mpsv
            line = " · ".join(x for x in (f"Be there {mpsv._clock(c['call_time'])}", line) if x)
        if c.get("swap_name"):
            act = '<span class="lm-count">Someone was asked to cover. You stay on until they say yes.</span>'
        else:
            act = (f'<a class="lm-btn sm ghost" href="/my/serving">Details</a>'
                   f'<a class="lm-txtbtn" href="/my/serving?sub={_e(c["id"])}#sv-{_e(c["id"])}">Can\'t make it</a>')
        out.append(f'<div class="lm-cblock">{lm.date_box(at, "var(--lm-violet)")}<span class="lm-wt"><b>{_e(what or "Serving")}</b>'
                   f'<span>{_e(line)}</span><span class="lm-crow">{act}</span></span></div>')
    if asks:
        n = len(asks)
        out.append(lm.row("/my/serving", lm.round_icon("give", "var(--lm-violet)"),
                          f"{n} ask{'' if n == 1 else 's'} to serve", "Say yes, or that you can't that day",
                          cls="lm-wrow"))
    if not out:
        if not m.get("teams"):
            return ""
        out.append(lm.row("/my/serving", lm.round_icon("give", "var(--lm-violet)"), "My serving",
                          ", ".join(t["name"] for t in m["teams"][:3]), cls="lm-pray"))
    return (f'<section aria-labelledby="lm-sv-h">{lm.section("Serving", "/my/serving", "My serving", hid="lm-sv-h")}'
            f'{"".join(out)}</section>')


def _classes_block(data: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """(the classes card, a 'keep going' row for Your next step)."""
    import member_lumen_ui as lm
    import member_portal_classes as mcl
    if not data:
        return "", ""
    mine = [c for c in data.get("mine") or [] if c.get("status") != "completed"]
    tz = data.get("tz") or "UTC"
    if mine:
        c = mine[0]
        total, done = int(c.get("total") or 0), int(c.get("done") or 0)
        pct = round(100 * done / total) if total else 0
        title = c.get("program") or c.get("title") or "Your class"
        track = mcl.short_title(str(c.get("title") or ""), c.get("program")) if c.get("program") else ""
        head = f'{_e(title)} · <em>{_e(track)}</em>' if track else lm.italic_last(title)
        bits = [f"{done} of {total} lessons" if total else "Just started"]
        n = c.get("next") or {}
        if n.get("starts_at"):
            bits.append(("Live now" if n.get("live") else f"Next {mcl.when_text(n.get('starts_at'), tz)}"))
        bar = f'<span class="lm-pb"><i style="width:{pct}%"></i></span>' if total else ""
        card = (f'<a class="lm-acad" href="/my/classes"><span class="lm-eyebrow lm-crest"><i>{lm.ic("cap", 15)}</i>Your classes</span>'
                f'<span class="lm-acadt">{head}</span>{bar}<span class="lm-acadm">{_e(" · ".join(bits))}</span></a>')
        step = lm.row("/my/classes", lm.round_icon("cap", "var(--lm-gold)"), f"Keep going on {c.get('title') or 'your class'}",
                      f"{done} of {total} lessons" if total else "Open the first lesson")
    elif data.get("open"):
        c = data["open"][0]
        more = len(data["open"]) - 1
        card = (f'<a class="lm-acad" href="/my/classes"><span class="lm-eyebrow lm-crest"><i>{lm.ic("cap", 15)}</i>Classes</span>'
                f'<span class="lm-acadt">{lm.italic_last(c.get("title") or "A class to join")}</span>'
                f'<span class="lm-acadm">{_e("Open to join" + (f" · {more} more" if more > 0 else ""))}</span></a>')
        step = ""
    else:
        return "", ""
    return (f'<section aria-labelledby="lm-cls-h">{lm.section("Classes", "/my/classes", "All classes", hid="lm-cls-h")}'
            f'{card}</section>'), step


def render_connect(biz: Dict[str, Any], site, request, me: Dict[str, Any], data: Dict[str, Any],
                   *, new_card: str = "") -> str:
    import member_app_photos as photos
    import member_app_ui as ui
    import member_directory
    import member_lumen_ui as lm
    import member_portal_church as mpc
    import member_spaces as msp
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "your church"
    pool = photos.photos(biz, site)
    used: set = set()
    groups = data.get("groups")
    parts = [lm.mast("Connect", "Your <em>people</em>",
                     f"Your group, where you serve, what you're learning, and your next step at {church}."),
             mpc._flash(request)]
    mine = (groups or {}).get("mine") or []
    if groups is None:
        parts.append('<p class="mp-err" role="alert" style="margin-top:24px">Your groups couldn\'t load just now. '
                     'Please try again in a moment.</p>')
    elif mine:
        g = mine[0]
        href = f"/my/groups/live/{_e(g['live']['id'])}" if g.get("live") else f"/my/groups/{_e(g['id'])}"
        led = ", ".join(g.get("leaders") or [])
        bits = ["Meeting now" if g.get("live") else (f"Next: {g['meets']}" if g.get("meets") else ""),
                g.get("location") or "",
                "You lead" if g.get("role") == "leader" else (f"led by {led}" if led else "")]
        more = "".join(lm.row(f"/my/groups/{x['id']}", f'<span class="lm-gmini" aria-hidden="true">{_e(ui.initials(x.get("name")))}</span>',
                              x.get("name") or "", x.get("meets") or x.get("location") or "") for x in mine[1:3])
        parts.append(f'<section aria-labelledby="lm-grp-h"><div class="lm-sec" style="margin-top:28px"><h2 class="lm-h2" id="lm-grp-h">'
                     f'{"Your group" if len(mine) == 1 else "Your groups"}</h2><a class="lm-more" href="{href}">Open</a></div>'
                     f'<a class="lm-tile" href="{href}">{_group_art(biz, g, pool, used)}'
                     f'<span class="tt" style="margin-top:14px">{_e(g.get("name"))}</span>'
                     f'<span class="tm">{_e(" · ".join(b for b in bits if b))}</span></a>'
                     f'{f"<div class=lm-list style=margin-top:16px>{more}</div>" if more else ""}</section>')
    parts.append(_serving_block(data.get("serving")))
    parts.append(f'<section aria-labelledby="lm-pray-h">{lm.section("Prayer", hid="lm-pray-h")}'
                 f'{lm.row("/my/prayer", lm.round_icon("flame"), "Send a prayer request", "It goes privately to the pastors.", cls="lm-pray")}</section>')
    occ = data.get("occasions")
    rows = coming_rows(occ, top=3)
    if rows:
        parts.append(f'<section>{lm.section("Events", "/my/events", "All events")}<div class="lm-list">{rows}</div></section>')
    classes_card, keep_going = _classes_block(data.get("classes"))
    parts.append(classes_card)
    asks = data.get("asks") or []
    steps = [keep_going]
    if "life_event" in asks:
        steps.append(lm.row("/my/ask/life", lm.round_icon("drop", "var(--lm-teal)"), "Get baptized",
                            "Ask the church to plan it with you"))
    if "visit" in asks or "help" in asks:
        steps.append(lm.row("/my/ask", lm.round_icon("chat", "var(--lm-coral)"), "Ask for a visit or help",
                            "It goes straight to the people who care for members"))
    steps_html = "".join(s for s in steps if s)
    if new_card or steps_html:
        parts.append(f'<section aria-labelledby="lm-next-h">{lm.section("Your next step", hid="lm-next-h")}'
                     f'<div class="lm-newslot">{new_card}</div>'
                     f'{f"<div class=lm-list>{steps_html}</div>" if steps_html else ""}</section>')
    open_ = (groups or {}).get("open") or []
    if open_:
        cards = "".join(
            f'<a class="lm-gcard" href="/my/groups/{_e(g["id"])}">{_group_art(biz, g, pool, used, big=False)}'
            f'<h3>{_e(g.get("name"))}</h3><p>{_e(g.get("meets") or g.get("kind") or "")}</p>'
            f'<span class="lm-btn sm {"going" if g.get("asked") else "ghost"}">{"Asked" if g.get("asked") else "See the group"}</span></a>'
            for g in open_[:8])
        parts.append(f'<section aria-labelledby="lm-find-h">{lm.section("Find a group", "/my/groups", "All groups", hid="lm-find-h")}'
                     f'<div class="lm-rail">{cards}</div></section>')
    ctx = msp.CURRENT.get() or {}
    rooms = []
    if member_directory.church_on(biz) and (ctx.get("space") or "church") == "church" and not ctx.get("youth"):
        rooms.append(lm.row("/my/directory", lm.round_icon("person", "var(--lm-teal)"), "Directory",
                            "Members who chose to be listed", cls="lm-room"))
    rooms.append(lm.row("/my/news", lm.round_icon("megaphone", "var(--fg2)"), "News", f"What's happening at {church}",
                        cls="lm-room"))
    parts.append(f'<div class="lm-rooms">{"".join(rooms)}</div>')
    return _shell(biz, site, "Connect", "".join(p for p in parts if p), tab="connect", who=me)
