"""member_portal_lumen.py — the new look's own pages: Home and Connect.

Kevin approved the "clean Lumen" mock on 2026-11-18 (version 29, accent level
2). Who sees it: member_lumen.py (MEMBER_LUMEN). The look: member_lumen_ui.py.
These pages port the mock's layout and read the same data today's pages do;
nothing here is made up, and a block with nothing in it is left out (Home
never says "nothing yet").

HOME (/my), "Look 4.1" (Kevin, 2026-11-19; the pieces are member_lumen_home):
the greeting by the church's clock and one sentence from the records; Up next,
one card featured by the data (live, Sunday's service with check-in, someone
new's first Sunday, their group's next gathering or the next event) with its
main button; Also for you, two picture tiles (the devotional, prayer, serving,
the latest message, groups to join, and Meet the pastor for someone new:
member_pastor); then what's happening (the news block,
member_portal_news.home_block) and the rest of Home below it: Coming up,
Today (the verse of the day on the ivory card, the reading plan or where they
left off), the latest message, the church's own tiles, the groups not on the
card, prayer, and installing the app, phone alerts and Ask the church at the
foot. What's a tile isn't repeated. Asks to serve and celebrations sit under
Up next. The Messages card is gone: the bubble at the top carries the count.

CONNECT (/my/connect), the people hub: your group, serving (your next date,
with Can't make it), prayer, events, classes (with how far you've come),
your next step (the "I'm new here" card leads it once that lands:
member_lumen.new_here_card), find a group, the pastor (member_pastor), the
directory and news. Read at
once from the readers today's pages use (member_portal_church.groups_for and
upcoming_for, member_portal_classes.classes_for, sunday_serving.mine,
member_asks.entry).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

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


def church_now(biz: Dict[str, Any]) -> datetime:
    """Now on the church's own clock: the Lead tab's (church_checkin
    .church_zone_name, from the church's row already in hand; New York when
    it has none). The greeting, "tonight" and the date read it."""
    from zoneinfo import ZoneInfo
    import church_checkin as cc
    return datetime.now(ZoneInfo(cc.church_zone_name(biz)))


def next_gathering(biz: Dict[str, Any], groups: Optional[Dict[str, List[Dict[str, Any]]]], *,
                   now: Optional[datetime] = None, fresh: bool = False) -> Optional[Dict[str, Any]]:
    """The member's next group gathering in the coming week, from their
    groups' regular times (read with the groups: groups_for), and who's
    answered for it (group_gatherings.answers: kept a little while; `fresh`
    reads it now). {group, day, time, start, answers}; answers None when
    they couldn't be read. None when no group of theirs meets on a schedule
    in the next 7 days."""
    import group_gatherings as gg
    now = now or church_now(biz)
    best = None
    for g in (groups or {}).get("mine") or []:
        sched = g.get("sched") or {}
        if not gg.scheduled(sched):
            continue
        day, _skipped = gg.next_on(sched, now)
        if not day or (day - now.date()).days >= 7:
            continue
        start = gg.starts_at(sched, day, now.tzinfo)
        if best is None or start < best[2]:
            best = (g, day, start)
    if not best:
        return None
    g, day, start = best
    got = gg.answers(str(biz["id"]), str(g["id"]), day, fresh=fresh)
    members = set(g.get("member_ids") or [])
    if got is not None and members:
        got = {k: v for k, v in got.items() if k in members}
    return {"group": g, "day": day, "time": start.time(), "start": start, "answers": got}


def groups_and_next(biz: Dict[str, Any], me: Dict[str, Any], *, fresh: bool = False):
    """Home's groups (groups_for) and, from them, the next gathering. Past
    the groups read, a failure only leaves the gathering out."""
    import member_portal_church as mpc
    groups = mpc.groups_for(biz["id"], me)
    try:
        return groups, next_gathering(biz, groups, fresh=fresh)
    except Exception:  # noqa: BLE001
        logger.warning("home: the next gathering skipped", exc_info=True)
        return groups, None


def told(biz: Dict[str, Any], me: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the member told the church in "I'm new here" (member_im_new),
    when they said it's their first time; None for everyone else and where
    I'm new here doesn't show. Kept there (told_state: a read at most once
    a minute per member, once every ten minutes after they've told)."""
    try:
        import member_im_new as mim
        if not mim.on() or not mim.is_church(biz) or not mim.adult(me):
            return None
        app = mim.told_state(str(biz["id"]), str(me["id"]))
        return app if app and app.get("at") and app.get("first_time") else None
    except Exception:  # noqa: BLE001
        logger.warning("home: what they told the church skipped", exc_info=True)
        return None


async def told_and_pastor(biz: Dict[str, Any], me: Dict[str, Any]):
    """(told(), the pastor or None): the church's pastor (member_pastor.who,
    kept five minutes) only for someone new, the one person Home shows Meet
    the pastor to, after what they told the church; everyone else's Home
    reads nothing more."""
    said = await asyncio.to_thread(told, biz, me)
    if not said:
        return said, None
    import member_pastor
    return said, await asyncio.to_thread(member_pastor.who, biz)


def render_home(biz: Dict[str, Any], site, *, me: Dict[str, Any], occasions, groups, library, live,
                bible: str, where, plan_today, plan_done, devotional: str = "", checkin: str = "",
                serving: str = "", celebrate: str = "", flash: str = "", news: str = "", news_n: Optional[int] = None,
                cards: Tuple[str, ...] = (), edit: bool = False, editbar: str = "", today: Optional[date] = None,
                ck: Optional[Dict[str, Any]] = None, ck_err: bool = False, serving_info: Optional[Dict[str, Any]] = None,
                devo: Optional[Dict[str, Any]] = None, gnext: Optional[Dict[str, Any]] = None,
                told_us: Optional[Dict[str, Any]] = None, now: Optional[datetime] = None, dark: bool = False,
                pastor: Optional[Dict[str, Any]] = None) -> str:
    """Home in the new look (Look 4.1, member_lumen_home): the greeting and
    its sentence, Up next and its card, Also for you, then `news` (the news
    block, member_portal_news.home_block) and the rest of Home below it.

    `checkin` is the check-in card (member_portal_checkin.lumen_card) and
    `ck` what it was drawn from (church_checkin.card); `ck_err` a check-in
    that didn't go through (?ck=): the full card follows Up next then.
    `serving` and `celebrate` are the asks to serve and the celebrations,
    under Up next; `serving_info` My serving (sunday_serving.home); `devo`
    today's devotional (member_portal_devotionals.home_extras' info);
    `gnext` the next group gathering (next_gathering); `told_us` what a
    brand-new person told the church (told()); `pastor` the church's pastor
    (member_pastor.who, for someone new: Meet the pastor). `cards` are the small cards
    at the foot (installing the app, phone alerts, Ask the church), each ''
    to leave it out. `dark` draws it dark whatever the member's look
    (member_lumen_look decides it for every page; nothing in the app passes
    it)."""
    import member_app_photos as photos
    import member_app_pictures as mapic
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_home as lh
    import member_lumen_ui as lm
    import member_portal_church as mpc
    import member_portal_messaging as mpm
    import member_portal_sermons as mps
    from member_portal import _shell, first_name, palette_for, portal_settings
    from sermons_public import day_label
    pal = palette_for(biz, site)
    pool = photos.photos(biz, site)
    used: set = set()
    now = now or church_now(biz)
    if today and today != now.date():
        now = datetime.combine(today, now.timetz())
    church = (biz.get("name") or "").strip() or "Your church"
    occ = [o for o in occasions or [] if _day(o.get("date"))]
    service = lh.service_next(ck, serving_info, occ, now)
    new, first = lh.first_sunday(told_us, service, now)
    choice = lh.pick(live=live, ck=ck, gnext=gnext, occasions=occ, first=first if new else None, now=now)
    kind = choice["kind"]
    about = ' aria-describedby="lm-f4-t"'

    def spot(key: str, art_kind: str, *, title: str = "", fallback: str = "", look: str = "colour") -> Tuple[str, str]:
        pic, lk = photos.choose(biz, key, pool, title=title, fallback=fallback, look=look, used=used)
        pin = ui.pin(f"/my/pictures/spot?key={quote(key, safe=':')}&amp;back=home") if edit else ""
        return ui.picture(pic, lk, art_kind, eager=True), pin

    def acts(inner: str) -> str:
        return f'<div class="lm-f4acts">{inner}</div>'

    feat, after, feat_eid, feat_gid = "", "", "", ""
    if kind == "live":
        art, pin = spot("home", "worship", fallback=photos.hero(pool))
        feat = lh.card(art, day=now.date(), foot="Live", kicker='<i class="lm-dotlive" aria-hidden="true"></i>Live now',
                       title=live.get("title") or "Live now", meta="Watch and chat with your church",
                       row=acts(f'<a class="lm-btn sm" href="/my/live"{about}>Join the room</a>'), pin=pin)
    elif kind == "service":
        w = ck["w"]
        d, t = w["day"], w["start"].time()
        title = ((ck.get("occasion") or {}).get("title") or "").strip() or church
        o = next((x for x in occ if _day(x["date"]) == d and (x.get("title") or "") == title), None)
        art, pin = spot("home", "welcome", fallback=photos.hero(pool))
        word = "Your first Sunday" if new and first and first["day"] == d else lh.when(d, t, now)[0].split(" · ")[0]
        marks, fam = ck.get("marks") or {}, ck.get("family") or []
        note = ""
        if ck_err:
            row = ""
            after = f'<div class="lm-ck">{checkin}</div>' if checkin else ""
        elif marks:
            online = all((m or {}).get("method") == "online" for m in marks.values())
            row = acts(lh.done_pill("Glad you're with us." if online else "Welcome home.")
                       + '<a class="lm-q4" href="/my/here?change=1&amp;from=home">Change it</a>')
        else:
            people = "".join(f'<input type="hidden" name="people" value="{_e(p["id"])}">' for p in fam)

            def one(where_: str, label: str, cls: str) -> str:
                return (f'<form method="post" action="/my/here"><input type="hidden" name="back" value="/my">'
                        f'<input type="hidden" name="where" value="{where_}">{people}'
                        f'<button class="{cls}" type="submit"{about}>{label}</button></form>')
            many = len(fam) > 1
            row = acts(one("in", "I&#x27;m here", "lm-btn sm") + one("online", "Watching online", "lm-q4")
                       + ('<a class="lm-q4" href="/my/here?from=home">Choose who</a>' if many else ""))
            note = "One tap counts you and your family." if many else "One tap counts you."
        feat = lh.card(art, day=d, foot=lh.leaf_time(t), kicker=_e(f"{word} · {lh.clock(t)}"), title=title,
                       meta=(o or {}).get("location") or "", row=row, pin=pin, note=note)
        feat_eid = str((o or {}).get("entry_id") or "")
    elif kind == "first":
        sv = choice["service"]
        d, t = sv["day"], sv.get("time")
        art, pin = spot("home", "welcome", fallback=photos.hero(pool))
        # Its name when the church's records give one (else "Your first Sunday",
        # and the label says when).
        kicker = ("Your first Sunday" + (f" · {lh.clock(t)}" if t else "")) if sv.get("title") else lh.when(d, t, now)[0]
        feat = lh.card(art, day=d, foot=lh.leaf_time(t), kicker=_e(kicker), title=sv.get("title") or "Your first Sunday",
                       meta=sv.get("where") or "", row=acts(f'<a class="lm-btn sm" href="/my/new"{about}>Your path</a>'),
                       pin=pin)
        feat_eid = str(sv.get("entry_id") or "")
    elif kind == "group":
        gx = choice["g"]
        g, d, t = gx["group"], gx["day"], gx.get("time")
        gid = _e(g["id"])
        art, pin = spot(f"group:{g['id']}", "groups", title=g.get("name") or "")
        ans = gx.get("answers")
        mine = (ans or {}).get(str(me["id"]))
        n_going = sum(1 for a in (ans or {}).values() if a == "going")
        second = (f'<a class="lm-q4" href="/my/groups/{gid}/chat">Chat</a>'
                  if mpm.turned_on(biz) and g.get("chat_on") is not False else
                  f'<a class="lm-q4" href="/my/groups/{gid}">Open the group</a>')
        if g.get("live"):
            main = f'<a class="lm-btn sm" href="/my/groups/live/{_e(g["live"]["id"])}"{about}>Join</a>'
        elif mine == "going":
            main = lh.done_pill("You're going", about)
        elif ans is None:
            main = f'<a class="lm-btn sm" href="/my/groups/{gid}/meet"{about}>Are you coming?</a>'
        else:
            main = (f'<form method="post" action="/my/groups/meet/rsvp"><input type="hidden" name="group_id" value="{gid}">'
                    f'<input type="hidden" name="answer" value="going"><input type="hidden" name="back" value="/my">'
                    f'<button class="lm-btn sm" type="submit"{about}>I&#x27;ll be there</button></form>')
        count = '<span class="lm-f4n">You said you can&#x27;t make it</span>' if mine == "no" else lh.going(n_going, mine == "going")
        feat = lh.card(art, day=d, foot=lh.leaf_time(t), kicker=_e(lh.when(d, t, now)[0]), title=g.get("name") or "",
                       meta=g.get("location") or (g.get("sched") or {}).get("meet_address") or "",
                       row=count + acts(main + second), pin=pin)
        feat_gid = str(g["id"])
    elif kind == "event":
        o = choice["o"]
        d, t = _day(o["date"]), lh.parse_hm(o.get("time"))
        art, pin = spot(mpc.event_key(o.get("title")), "events", title=o.get("title") or "")
        eid = _e(o.get("entry_id"))
        answer, count, mine = _answer(o), int(o.get("attending") or 0), o.get("mine") or {}
        if answer:
            main, cnt = lh.done_pill(answer, about), lh.going(count, True)
        elif o.get("signup"):
            su = o["signup"].get("mine") or {}
            main = (lh.done_pill("You're signed up", about) if su.get("status") in ("paid", "confirmed") else
                    f'<a class="lm-btn sm" href="/my/events"{about}>Sign up</a>')
            cnt = lh.going(count, False)
        elif o.get("full"):
            main, cnt = '<span class="lm-btn sm ghost">Full</span>', ""
        else:
            main = (f'<form method="post" action="/my/rsvp"><input type="hidden" name="entry_id" value="{eid}">'
                    f'<input type="hidden" name="back" value="/my"><input type="hidden" name="action" value="coming">'
                    f'<button class="lm-btn sm" type="submit"{about}>I&#x27;m coming</button></form>')
            cnt = ('<span class="lm-f4n">You said you can&#x27;t make it</span>' if mine.get("status") == "no"
                   else lh.going(count, False))
        sample = samples.is_sample(o)
        feat = lh.card(art, day=d, foot=lh.leaf_time(t),
                       kicker=_e(lh.when(d, t, now)[0]) + (ui.sample_tag() if sample else ""), title=o.get("title") or "",
                       meta=o.get("location") or "", row=cnt + acts(main + '<a class="lm-q4" href="/my/events">Details</a>'),
                       pin=pin, after=ui.sample_hint(samples.WHERE["events"]) if sample else "")
        feat_eid = str(o.get("entry_id") or "")
    else:
        art, pin = spot("home", "welcome", fallback=photos.hero(pool))
        feat = lh.card(art, day=None, foot="", kicker="Welcome home", title=church,
                       meta="Messages, prayer and your church family, all week.",
                       row=acts('<a class="lm-btn sm" href="/my/sermons">Watch a message</a>'
                                '<a class="lm-q4" href="/my/bible">Read</a>'), pin=pin)

    # Also for you: two picture tiles, by the day and the person.
    shown: List[str] = []

    def to_spot(key: str, href: str) -> str:
        return f"/my/pictures/spot?key={quote(key, safe=':')}&amp;back=home" if edit else _e(href)

    def t_devo() -> str:
        if not devo or not (devo.get("st") or {}).get("now"):
            return ""
        d, st, day = devo["dev"], devo["st"], devo.get("day") or {}
        n, of = int(st["now"]), max(1, int(st["count"] or 1))
        key = f"devotional:{d['id']}"
        pic, lk = photos.choose(biz, key, pool, title=d.get("title") or "", look="church", used=used)
        shown.append("devo")
        return lh.tile(to_spot(key, devo["href"]), ui.picture(pic, lk, "word"), "book",
                       f"Devotional · {devo.get('minutes') or 1} min", day.get("title") or d.get("title") or "",
                       f"{d.get('title') or 'Devotional'} · day {n} of {of}" + (" · done" if n in st.get("done", ()) else ""),
                       day_leaf=n, progress=round(100 * n / of), pin=edit)

    def t_prayer() -> str:
        pic, lk = photos.choose(biz, "prayer", pool, words=mapic.PRAYER_WORDS, look="colour", used=used)
        shown.append("prayer")
        return lh.tile(to_spot("prayer", "/my/prayer"), ui.picture(pic, lk, "prayer"), "flame", "Prayer",
                       "How can we pray for you?", "It goes privately to the pastors.", pin=edit)

    def t_serving(today_only: bool) -> str:
        today_d = now.date()
        for c in (serving_info or {}).get("coming") or []:
            d = _day((c.get("service") or {}).get("day"))
            if not d or (d != today_d if today_only else not 0 <= (d - today_d).days < 7):
                continue
            import member_portal_serving as mpsv
            at = (c.get("service") or {}).get("at")
            t = lh.parse_hm(c.get("call_time")) or (at.time() if isinstance(at, datetime) else None)
            key = f"group:{c['group_id']}" if c.get("group_id") else ""
            pic, lk = (photos.choose(biz, key, pool, title=c.get("team") or "", look="colour", used=used) if key else ("", ""))
            when_ = ("" if d == today_d else f"{d:%a} ") + (lh.hm(t) if t else "")
            meta = ", ".join(x for x in (c.get("place") or "", f"with {mpsv._names(c['with'])}" if c.get("with") else "") if x)
            return lh.tile(to_spot(key, "/my/serving") if key else "/my/serving", ui.picture(pic, lk, "serve"), "wave",
                           f"Serving · {when_}".strip(" ·"), c.get("team") or "Serving", meta, pin=edit and bool(key))
        return ""

    def t_message() -> str:
        if not library or not library.get("sermons"):
            return ""
        s = library["sermons"][0]
        d = _day(s.get("preached_on") or "")
        label = ("Today's message" if d == now.date() else
                 "Last Sunday" if d and 0 <= (now.date() - d).days <= 7 and d.weekday() == 6 else "Latest message")
        meta = " · ".join(x for x in (s.get("speaker") or "", s.get("scripture") or "") if x) or day_label(s.get("preached_on"))
        shown.append("message")
        return lh.tile(f"/my/sermons/{_e(s['id'])}", mps._art(library, s, pal, site, pool, used), "playfill", label,
                       s.get("title") or "", meta, tag=ui.sample_tag() if samples.is_sample(s) else "")

    def t_pastor() -> str:
        # Meet the pastor (member_pastor): someone new, at a church with someone in the senior role.
        if not pastor or not pastor.get("id"):
            return ""
        import member_pastor
        return member_pastor.tile(biz, pastor, href=to_spot("pastor", "/my/pastor"), edit=edit)

    def t_groups() -> str:
        open_ = [g for g in (groups or {}).get("open") or [] if g.get("name")]
        if not open_:
            return ""
        g = open_[0]
        key = f"group:{g['id']}"
        pic, lk = photos.choose(biz, key, pool, title=g.get("name") or "", look="colour", used=used)
        return lh.tile(to_spot(key, "/my/groups"), ui.picture(pic, lk, "groups"), "people", "Find your people",
                       "Groups to join", " · ".join(x["name"] for x in open_[:3]), pin=edit)

    if new:
        order = [t_groups, t_pastor, t_prayer, t_devo, t_message]
    elif service and service["day"] == now.date():
        order = [lambda: t_serving(True), t_message, t_devo, t_prayer]
    else:
        order = [t_devo, t_prayer, lambda: t_serving(False), t_message]
    tiles_html: List[str] = []
    for fn in order:
        if len(tiles_html) == 2:
            break
        got = fn()
        if got:
            tiles_html.append(got)

    name = first_name(me.get("name") or "")
    # The sentence names the next gathering even when the card is the live
    # service.
    said = choice if kind in ("group", "event") else lh.pick(live=None, ck=None, gnext=gnext, occasions=occ, first=None,
                                                             now=now)
    hello = lh.greeting(name, now, lh.line(said, service=service, serving=serving_info, new=new, first=first, now=now),
                        new=new)
    up = lh.up_next(1 + len(tiles_html)) if kind != "welcome" else ""
    under = "".join(x for x in (serving, celebrate) if x)
    top = (f'{editbar}{flash}{lh.live_bar(live) if live and kind != "live" else ""}{hello}'
           f'<div class="lm-up">{up}{feat}</div>'
           f'{after}{f"<div class=lm-cards>{under}</div>" if under else ""}{lh.also(tiles_html)}')
    # The rest of Home, below the news: what's coming after Up next, Today
    # (the verse, the reading plan, the devotional unless it's a tile), the
    # latest message unless it's a tile, the church's own tiles (when it
    # saved some), the groups not on the card, prayer unless it's a tile,
    # and the small cards at the foot.
    rows = coming_rows(occ, skip=feat_eid)
    coming = (f'<section aria-labelledby="lm-cu-h">{lm.section("Coming up", "/my/events", "All events", hid="lm-cu-h")}'
              f'<div class="lm-list">{rows}</div></section>' if rows else "")
    reading = reading_row(plan_today, plan_done) or continue_row(where, bible)
    devo_row = devotional if "devo" not in shown else ""
    today_html = (f'<section aria-labelledby="lm-today-h">{lm.section("Today", "/my/bible/plans", "Plans", hid="lm-today-h")}'
                  f'{verse_page(bible)}{reading}{f"<div class=lm-today-more>{devo_row}</div>" if devo_row else ""}</section>')
    message = "" if "message" in shown else message_tile(library, pal, site=site, pool=pool, used=used, today=now.date())
    saved = mpc.clean_tiles(portal_settings(biz.get("settings")).get("tiles"))
    own_tiles = mpc.home_tiles(biz, site, pool, used, edit=edit) if saved else ""
    rest_groups = {"mine": [g for g in (groups or {}).get("mine") or [] if str(g.get("id")) != feat_gid]}
    prayer = "" if "prayer" in shown else prayer_row()
    foot = "".join(c for c in cards if c)
    body = (f'{top}{news}{coming}{today_html}{message}{own_tiles}{group_rows(rest_groups)}{prayer}'
            f'{f"<div class=lm-cards>{foot}</div>" if foot else ""}')
    import member_portal_news as mpn
    import member_portal_celebrations as mcl
    script = (mpn.RX_JS if news else "") + (mcl.STRIP_JS if celebrate else "")
    style = ""
    if news or celebrate:
        style = f"<style>{mpn.NEWS_CSS}{mcl.CEL_CSS if celebrate else ''}</style>"
    return _shell(biz, site, "Home", style + body, tab="home", who=me, script=script, lumen_dark=dark)

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
    import member_pastor
    tab = preview or await asyncio.to_thread(_quiet, mcl.tab_on, bid, me)
    groups, occ, classes, serving, asks, pastor = await asyncio.gather(
        asyncio.to_thread(mpc.groups_for, bid, me),
        asyncio.to_thread(mpc.upcoming_for, bid, me),
        asyncio.to_thread(_quiet, mcl.classes_for, bid, me) if tab else _nothing(),
        asyncio.to_thread(_quiet, ssv.mine, biz, str(me["id"])) if ssv.on() and not preview else _nothing(),
        _ask_entry(biz, me),
        # Meet the pastor's row (member_pastor.who: kept five minutes).
        asyncio.to_thread(member_pastor.who, biz))
    return {"groups": samples.fill(groups, "groups", preview), "occasions": samples.fill(occ, "occasions", preview),
            "classes": samples.fill(classes, "classes", preview) if tab else None, "serving": serving,
            "asks": asks or [], "pastor": pastor}


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
    pastor = data.get("pastor")
    if pastor and pastor.get("id"):
        import member_pastor
        rooms.append(member_pastor.row(biz, pastor))
    if member_directory.church_on(biz) and (ctx.get("space") or "church") == "church" and not ctx.get("youth"):
        rooms.append(lm.row("/my/directory", lm.round_icon("person", "var(--lm-teal)"), "Directory",
                            "Members who chose to be listed", cls="lm-room"))
    rooms.append(lm.row("/my/news", lm.round_icon("megaphone", "var(--fg2)"), "News", f"What's happening at {church}",
                        cls="lm-room"))
    parts.append(f'<div class="lm-rooms">{"".join(rooms)}</div>')
    return _shell(biz, site, "Connect", "".join(p for p in parts if p), tab="connect", who=me)
