"""member_portal_lumen.py — the new look's own pages: Home and Connect.

Kevin approved the "clean Lumen" mock on 2026-11-18 (version 29, accent level
2). Who sees it: member_lumen.py (MEMBER_LUMEN). The look: member_lumen_ui.py.
These pages port the mock's layout and read the same data today's pages do;
nothing here is made up, and a block with nothing in it is left out (Home
never says "nothing yet").

HOME (/my), "Look 5.1" (Kevin, 2026-11-20; the pieces are member_lumen_home
and member_lumen_stories): the moments (the pastor's word, Sunday, the
church's newest message while it's new, the member's groups, the class
they're in (my_class, kept), the church's events, each opening a
full-screen viewer);
the greeting by the church's clock and one sentence from the records (Look
4.1's, with the service's time and, at a quiet church, what's ready to
watch and what's coming); the four doors (Prayer · Events · Serve · Kids or
Give, each with a line from the records); This week, horizontal cards for
the service (a pass: I'll be there, Watch live where the church streams,
streams() kept, Calendar where the office set the time), each of
the member's groups' next gathering and the church's events this week, each
with its own action (check-in on the day, someone new's Your path, the group
RSVP, I'm coming, Sign up); the asks to serve and the celebrations (each
wants an answer); the composer (Share a praise or a prayer); then the feed
(the news block, member_portal_news.home_block: the church's and the groups'
posts) and, after it, the church's own cards (Kevin's Home plan, 2026-11-21:
its newest message with Meet the pastor for someone new, Pick up where you
left off and the member's class under it, its events after this week, the
verse of the day: member_lumen_feed.church_cards), the church's own tiles,
and "You're all caught up". Nothing below it: Also for you, Coming up,
Today, the message tile, Your group, prayer and the foot cards are gone
(installing the app is on Me, as are notifications and Ask the church). The
Messages card is gone too: the bubble at the top carries the count. (Look
4.1's Up next card became This week.)

CONNECT (/my/connect), the people hub, "Look 5.1" (Kevin, 2026-11-20; the
pieces are member_lumen_connect): your groups (each with its next gathering
and its chat's unread count), serving (your next date, I'll be there and
Can't make it), classes (Lesson n of m, and the next class to sign up for),
prayer (this week's requests from your groups), find your people (groups
to join), your next step (the "I'm new here" card: member_lumen
.new_here_card), then your pastor (member_pastor), events and the
directory. Read at once from the readers today's pages use
(member_portal_church.groups_for and upcoming_for,
member_portal_classes.classes_for, sunday_serving.mine, member_asks.entry,
group_prayer.recent, member_portal_threads.counts).
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
            f'{hint}<a class="lm-tile" href="/my/sermons/{_e(s["id"])}"><span class="img">{mps._art(lib, s, pal, site, pool, used, yt="wide")}'
            f'<span class="lm-playdot">{lm.ic("playfill", 18)}</span>{ui.sample_tag() if sample else ""}</span>'
            f'<span class="tt" id="lm-msg-h">{_e(s.get("title"))}</span><span class="tm">{_e(sub)}</span></a></section>')


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


def next_gatherings(biz: Dict[str, Any], groups: Optional[Dict[str, List[Dict[str, Any]]]], *,
                    now: Optional[datetime] = None, fresh: bool = False, days: int = 7) -> List[Dict[str, Any]]:
    """Each of the member's groups' next gathering in the coming `days`
    (Look 5.1's This week and its moments), soonest first, each as
    next_gathering() gives one: {group, day, time, start, answers}. Who's
    answered comes in one read for all of them (group_gatherings.answers_many:
    kept 30 s; a member in one group reads what next_gathering read)."""
    import group_gatherings as gg
    now = now or church_now(biz)
    found = []
    for g in (groups or {}).get("mine") or []:
        sched = g.get("sched") or {}
        if not gg.scheduled(sched):
            continue
        day, _skipped = gg.next_on(sched, now)
        if not day or not 0 <= (day - now.date()).days < days:
            continue
        found.append((g, day, gg.starts_at(sched, day, now.tzinfo)))
    if not found:
        return []
    found.sort(key=lambda x: (x[2], str(x[0].get("name") or "")))
    got = gg.answers_many(str(biz["id"]), [(str(g["id"]), day) for g, day, _ in found], fresh=fresh)
    out = []
    for g, day, start in found:
        ans = got.get((str(g["id"]), day.isoformat()))
        members = set(g.get("member_ids") or [])
        if ans is not None and members:
            ans = {k: v for k, v in ans.items() if k in members}
        out.append({"group": g, "day": day, "time": start.time(), "start": start, "answers": ans})
    return out


def groups_and_next(biz: Dict[str, Any], me: Dict[str, Any], *, fresh: bool = False):
    """Home's groups (groups_for), the next gathering, and every group's
    next gathering this week (next_gatherings, the first of which is the
    next): (groups, next or None, [gatherings]). Past the groups read, a
    failure only leaves the gatherings out."""
    import member_portal_church as mpc
    groups = mpc.groups_for(biz["id"], me)
    try:
        week = next_gatherings(biz, groups, fresh=fresh)
        return groups, (week[0] if week else None), week
    except Exception:  # noqa: BLE001
        logger.warning("home: the next gathering skipped", exc_info=True)
        return groups, None, []


# Whether member messages let this member write to someone (member_pastor
# .may_message: three reads), kept ten minutes per (church, member, person):
# the reply on a pastor's moment asks it.
_MAY_WRITE = None


def may_write(biz: Dict[str, Any], me: Dict[str, Any], other_id: str) -> bool:
    """member_pastor.may_message, kept ten minutes (member_cache). False on
    any failure (the reply goes to the church instead)."""
    global _MAY_WRITE
    import member_cache
    import member_pastor
    if _MAY_WRITE is None:
        _MAY_WRITE = member_cache.Kept("may_write", 600.0)
    key = (str(biz.get("id")), str(me.get("id")), str(other_id))
    hit, got = _MAY_WRITE.get(key)
    if hit:
        return bool(got)
    ok = bool(member_pastor.may_message(biz, me, str(other_id)))
    _MAY_WRITE.put(key, ok, tag=key[0])
    return ok


# The class the member is in and hasn't finished (Home's moments), kept
# CLASS_SECONDS per (church, member): member_cache, as may_write.
CLASS_SECONDS = 120.0
_CLASS = None


def my_class(biz: Dict[str, Any], me: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The first class the member is in and hasn't finished, as Connect's
    Classes row picks it (academy_member_classes' "mine", not completed):
    {course_id, title, program, total, done, lesson}; {} when there's none (or the
    church has no class anyone can see: member_portal_classes.classes_on,
    kept a minute, so a church without classes asks nothing more; that no is
    not kept here, as classes_on says no for a failed read too); None when a
    read failed (the moment is left out, nothing is kept). Kept
    CLASS_SECONDS per (church, member)."""
    global _CLASS
    import member_cache
    import member_portal_classes as mcl
    if _CLASS is None:
        _CLASS = member_cache.Kept("home_class", CLASS_SECONDS)
    key = (str(biz.get("id")), str(me.get("id")))
    hit, got = _CLASS.get(key)
    if hit:
        return got
    out: Dict[str, Any] = {}
    try:
        # classes_on is False for "no class anyone can see" and for a failed
        # read alike, so its no is never kept here (it keeps its own yes or no
        # a minute when its read worked: no read again either way).
        on = mcl.classes_on(key[0])
        raw = mcl.member_classes(key[0], me) if on else {}
    except Exception:  # noqa: BLE001 — the moment is left out
        logger.warning("home: the class skipped", exc_info=True)
        raw = None
    if raw is None:
        return None
    if raw:
        for c in raw.get("mine") or []:
            total, done = int(c.get("total") or 0), int(c.get("done") or 0)
            if c.get("status") == "completed" or (total and done >= total) or not c.get("course_id"):
                continue
            n = c.get("next") if isinstance(c.get("next"), dict) else {}
            out = {"course_id": str(c["course_id"]), "title": str(c.get("title") or c.get("program") or "").strip(),
                   "program": str(c.get("program") or "").strip(), "total": total, "done": done,
                   "lesson": str(n.get("lesson") or n.get("title") or "").strip()}
            break
    if on:
        _CLASS.put(key, out, tag=key[0])
    return out


# Whether the church streams (Sunday's Watch live), kept STREAMS_SECONDS per
# church: member_cache, as may_write.
STREAMS_SECONDS = 600.0
_STREAMS = None


def streams(biz: Dict[str, Any]) -> Optional[bool]:
    """Whether the church has gone live in the app (live_sessions: the
    office's Go live and the stream relay both open one), the sign that its
    services can be watched live there: one row asked for, kept
    STREAMS_SECONDS per church. None when the read failed (Watch live is left
    out, nothing is kept). Home adds the church being live right now (its
    own live read) to this."""
    global _STREAMS
    import member_cache
    import sb_clients
    if _STREAMS is None:
        _STREAMS = member_cache.Kept("home_streams", STREAMS_SECONDS)
    bid = str(biz.get("id") or "")
    if not bid:
        return None
    hit, got = _STREAMS.get(bid)
    if hit:
        return bool(got)
    try:
        rows = sb_clients.sb_get_as_service(f"/live_sessions?business_id=eq.{quote(bid, safe='')}&select=id&limit=1")
    except Exception:  # noqa: BLE001 — Watch live is left out
        logger.warning("home: whether the church streams skipped", exc_info=True)
        return None
    if not isinstance(rows, list):
        return None
    ok = bool(rows)
    _STREAMS.put(bid, ok, tag=bid)
    return ok


# What waits for the church's owner (Home's desk strip), kept DESK_SECONDS
# per church: member_cache, as may_write.
DESK_SECONDS = 60.0
_DESK = None
GOOD_DAYS = 30           # news_share's office list shows waiting good news this long
DESK_MOST = 60           # each count is read up to this; at it, the strip says "60+"


def is_owner(biz: Dict[str, Any], me: Dict[str, Any], preview_owner: bool = False) -> bool:
    """The church's owner on Home: their preview, or their own member record
    (settings.church_owner_contact_id, as member_moments.may_take_down). No
    read."""
    if preview_owner:
        return True
    pick = str(((biz or {}).get("settings") or {}).get("church_owner_contact_id") or "")
    return bool(pick) and pick == str((me or {}).get("id") or "")


def desk_counts(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What waits for the owner (Kevin's Home plan, 2026-11-21: "1 good news
    post is waiting"), the counts the office's News room lists as Waiting for
    you: good news members shared for the whole church, waiting to be posted
    (news_share, the last GOOD_DAYS days as its list shows them), members'
    group posts the check held (member_posts.held_posts), and comments the
    check held (church_news). Three small reads, each filtered in the query
    with its own window of DESK_MOST (a count that reaches it is "60+": the
    `*_more` flags), kept DESK_SECONDS per church; None when any failed (the
    counts are left out)."""
    global _DESK
    import member_cache
    import sb_clients
    from datetime import timedelta, timezone
    if _DESK is None:
        _DESK = member_cache.Kept("home_desk", DESK_SECONDS)
    bid = str((biz or {}).get("id") or "")
    if not bid:
        return None
    hit, got = _DESK.get(bid)
    if hit:
        return got
    b = quote(bid, safe="")
    # A UTC "Z" time: a "+00:00" in the address would read as a space.
    since = (datetime.now(timezone.utc) - timedelta(days=GOOD_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    member = f"/church_posts?business_id=eq.{b}&source=eq.member&status=eq.waiting&removed_at=is.null"
    try:
        good = sb_clients.sb_get_as_service(
            f"{member}&group_id=is.null&created_at=gte.{since}&select=id,created_at&order=created_at.desc"
            f"&limit={DESK_MOST}")
        group = sb_clients.sb_get_as_service(
            f"{member}&group_id=not.is.null&select=id,attach&order=created_at.desc&limit={DESK_MOST}")
        held = sb_clients.sb_get_as_service(
            f"/church_post_comments?business_id=eq.{b}&status=eq.held&select=id&limit={DESK_MOST}")
    except Exception:  # noqa: BLE001 — the counts are left out
        logger.warning("home: the desk's counts skipped", exc_info=True)
        return None
    if not isinstance(good, list) or not isinstance(group, list) or not isinstance(held, list):
        return None
    # A member's group post waits only while the check holds it (member_posts).
    held_posts = [r for r in group if isinstance(r.get("attach"), dict) and r["attach"].get("held")]
    out = {"good": len(good), "good_more": len(good) >= DESK_MOST,
           "good_at": str(good[0].get("created_at") or "") if good else "",
           "held_posts": len(held_posts), "held_comments": len(held),
           "held_more": len(group) >= DESK_MOST or len(held) >= DESK_MOST}
    _DESK.put(bid, out, tag=bid)
    return out


async def news_and_reply(biz: Dict[str, Any], me: Dict[str, Any], feed_kw: Dict[str, Any], *, preview: bool = False):
    """Home's news read (church_news.home_view) and, for the new Home's
    pastor's moment, whether the member may write to the pastor who posted
    (may_write, kept): ((posts, unseen count), {author id: may write}). The
    second read waits only on the first, inside Home's one gather."""
    import church_news as cn
    import member_lumen_stories as mls
    got = await asyncio.to_thread(cn.home_view, str(biz["id"]), str(me["id"]), **feed_kw)
    write: Dict[str, bool] = {}
    try:
        p = mls.pastor_post((got or (None, 0))[0], church_now(biz))
        if p and not preview and str(p.get("posted_by") or "") and str(p.get("posted_by")) != str(me.get("id")):
            write[str(p["posted_by"])] = await asyncio.to_thread(may_write, biz, me, str(p["posted_by"]))
    except Exception:  # noqa: BLE001 — the reply goes to the church instead
        logger.warning("home: may write to the pastor skipped", exc_info=True)
    return got, write


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
                pastor: Optional[Dict[str, Any]] = None, posts: Optional[List[Dict[str, Any]]] = None,
                gatherings: Optional[List[Dict[str, Any]]] = None, write: Optional[Dict[str, bool]] = None,
                leaders: Optional[Dict[str, Any]] = None, leaders_owner: bool = False,
                klass: Optional[Dict[str, Any]] = None, streams: bool = False,
                desk: Optional[Dict[str, Any]] = None, desk_post: bool = False, owner: bool = False) -> str:
    """Home in the new look (Look 5.1: member_lumen_home, member_lumen_stories):
    the moments, the greeting and its sentence, the four doors, This week,
    the composer, then `news` (the feed, member_portal_news.home_block), the
    church's own cards (member_lumen_feed.church_cards) and the end.

    `checkin` is the check-in card (member_portal_checkin.lumen_card) and
    `ck` what it was drawn from (church_checkin.card); `ck_err` a check-in
    that didn't go through (?ck=): the full card follows This week then.
    `serving` and `celebrate` are the asks to serve and the celebrations,
    above the composer; `serving_info` My serving (sunday_serving.home); `devo`
    today's devotional (member_portal_devotionals.home_extras' info);
    `gatherings` each of the member's groups' next gathering this week
    (next_gatherings; `gnext`, the first, when only it is given); `told_us`
    what a brand-new person told the church (told()); `pastor` the church's
    pastor (member_pastor.who, for someone new: Meet the pastor, a row
    among the church's cards); `klass` the class the member is in
    (my_class); `streams` whether the church streams (streams()); `owner`
    the church's owner (is_owner), who alone gets the desk strip: `desk` what
    waits (desk_counts; None when it couldn't be read) and `desk_post`
    whether they may post the church's first news (church_news.can_post,
    read only when no news reaches them); `posts`
    Home's posts (church_news.home_view: a pastor's word for the moments)
    and `write` whether the member may write to its author
    (news_and_reply). `leaders` is what leaders' own moments are drawn
    from (member_moments.home_data; None before its tables are there, and
    then Home is as it was), `leaders_owner` the church owner's preview
    (Take it down on anyone's moment). `cards`, `devotional`, `plan_today`,
    `plan_done` and `where` are no longer drawn (the older look's sections
    left Home). `dark`
    draws it dark whatever the member's look (member_lumen_look decides it
    for every page; nothing in the app passes it)."""
    import member_app_photos as photos
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_home as lh
    import member_lumen_share as msh
    import member_lumen_stories as mls
    import member_photos as ph
    import member_portal_church as mpc
    import member_portal_messaging as mpm
    import member_portal_sermons as mps
    import member_portal_threads as mpt
    import member_spaces as msp
    import sunday_serving as ssv
    from datetime import time as _time, timedelta
    from member_portal import _shell, first_name, portal_settings
    from public_form_theme import resolve_theme
    pool = photos.photos(biz, site)
    used: set = set()
    now = now or church_now(biz)
    if today and today != now.date():
        now = datetime.combine(today, now.timetz())
    day0 = now.date()
    church = (biz.get("name") or "").strip() or "Your church"
    occ = [o for o in occasions or [] if _day(o.get("date"))]
    week_g = [g for g in (gatherings if gatherings is not None else ([gnext] if gnext else [])) if g]
    gnext = week_g[0] if week_g else None
    service = lh.service_next(ck, serving_info, occ, now)
    new, first = lh.first_sunday(told_us, service, now)
    ck_open = (ck or {}).get("state") == "open"
    mid = str(me["id"])
    chat_on = mpm.turned_on(biz)
    # The church's conversation is open to this member when Messages' unread
    # count was read for this page (church threads open, in Church): no read.
    counts = mpt.NOW.get()
    to_church = ("/my/inbox/church", "Write to the church…") if counts is not None else None

    def spot(key: str, art_kind: str, *, title: str = "", fallback: str = "", look: str = "colour") -> Tuple[str, str]:
        pic, lk = photos.choose(biz, key, pool, title=title, fallback=fallback, look=look, used=used)
        pin = ui.pin(f"/my/pictures/spot?key={quote(key, safe=':')}&amp;back=home") if edit else ""
        return ui.picture(pic, lk, art_kind, eager=True), pin

    # The records' own actions, as This week's buttons (cls "lm-wkb") and the
    # moments' (cls "lm-mvb"): today's forms and links.
    def group_act(gx: Dict[str, Any], cls: str) -> Tuple[str, str]:
        g = gx["group"]
        gid = str(g["id"])
        ans = gx.get("answers")
        mine = (ans or {}).get(mid)
        n_going = sum(1 for a in (ans or {}).values() if a == "going")
        if g.get("live"):
            main = lh.link_button(f"/my/groups/live/{g['live']['id']}", "Join", cls)
        elif mine == "going":
            main = lh.done("You're going", cls)
        elif ans is None:
            main = lh.link_button(f"/my/groups/{gid}/meet", "Are you coming?", cls)
        else:
            main = lh.post_button("/my/groups/meet/rsvp", {"group_id": gid, "answer": "going", "back": "/my"},
                                  "I'll be there", cls)
        return main, (lh.said_no() if mine == "no" else lh.going(n_going, mine == "going"))

    def event_act(o: Dict[str, Any], cls: str, coming: str = "I'm coming") -> Tuple[str, str]:
        answer, count, mine = _answer(o), int(o.get("attending") or 0), o.get("mine") or {}
        if answer:
            return lh.done(answer, cls), lh.going(count, True)
        if o.get("signup"):
            su = o["signup"].get("mine") or {}
            main = (lh.done("You're signed up", cls) if su.get("status") in ("paid", "confirmed") else
                    lh.link_button("/my/events", "Sign up", cls))
            return main, lh.going(count, False)
        if o.get("full"):
            return f'<span class="{cls} q">Full</span>', ""
        main = lh.post_button("/my/rsvp", {"entry_id": str(o.get("entry_id") or ""), "back": "/my", "action": "coming"},
                              coming, cls)
        return main, (lh.said_no() if mine.get("status") == "no" else lh.going(count, False))

    # The church's next service this week: its calendar entry (for its name,
    # room, answer), check-in while it's open, someone new's first Sunday.
    svc, svc_o = None, None
    if service and 0 <= (service["day"] - day0).days < 7:
        svc = service
        title = (service.get("title") or ((ck or {}).get("occasion") or {}).get("title") or "").strip()
        eid = str(service.get("entry_id") or "")
        svc_o = next((x for x in occ if eid and str(x.get("entry_id")) == eid), None) or next(
            (x for x in occ if _day(x["date"]) == service["day"] and title and (x.get("title") or "") == title), None)
        svc = dict(service, title=title)

    def service_act(cls: str, coming: str = "I'm coming") -> Tuple[str, str, str]:
        """(the button, the count, a note) for the service. `coming`: the
        calendar entry's RSVP button's words."""
        d = svc["day"]
        if ck_open and ((ck or {}).get("w") or {}).get("day") == d:
            marks, fam = ck.get("marks") or {}, ck.get("family") or []
            if ck_err:
                return "", "", ""
            if marks:
                online = all((m or {}).get("method") == "online" for m in marks.values())
                return (lh.done("Glad you're with us." if online else "Welcome home.", cls), "",
                        '<a href="/my/here?change=1&amp;from=home">Change it</a>')
            people = [("people", str(p["id"])) for p in fam]
            many = len(fam) > 1
            both = [("back", "/my")] + people
            here = (lh.post_button("/my/here", [("where", "online")] + both, "Watching online", f"{cls} q")
                    + lh.post_button("/my/here", [("where", "in")] + both, "I'm here", cls))
            note = ('One tap counts you and your family · <a href="/my/here?from=home">Choose who</a>' if many
                    else "One tap counts you.")
            return here, "", note
        if new and first and first["day"] == d:
            return lh.link_button("/my/new", "Your path", cls), "", ""
        if svc_o:
            main, cnt = event_act(svc_o, cls, coming)
            return main, cnt, ""
        return "", "", ""

    # ── This week: the service, each group's next gathering, the church's events ──
    items: List[Tuple[Tuple[Any, ...], str]] = []
    week_eids: set = set()
    if svc:
        d, t = svc["day"], svc.get("time")
        firsts = new and first and first["day"] == d
        kicker = ("Your first Sunday" + (f" · {lh.clock(t)}" if t else "")) if firsts else lh.when(d, t, now)[0]
        art, pin = spot("home", "welcome", fallback=photos.hero(pool))
        # Sunday as a pass (Kevin's Home plan, 2026-11-21): the record's own
        # answer (the calendar entry's RSVP as I'll be there, check-in on the
        # day), Watch live where the church streams (the live page), and
        # Calendar where the office set the service's day and time (Watch's
        # own .ics: member_lumen_watch.service_ics), each only where its
        # route is there.
        main, cnt, note = service_act("lm-wkb", "I'll be there")
        on_day = d == day0
        watch = (lh.icon_link("/my/live", "live", "Watch live") if streams and (live or not (ck_open and on_day))
                 else "")
        cal = (lh.icon_link("/my/sermons/live.ics", "calendar", "Calendar", download=True, aria="Add to calendar")
               if svc.get("from") == "checkin" and ((ck or {}).get("settings") or {}).get("saved") and not on_day
               else "")
        place = (svc_o or {}).get("location") or svc.get("where") or ""
        if streams:
            place = f"{place} · or watch live in the app" if place else "In person, or watch live in the app"
        n_days = (d - day0).days
        chip = "Today" if n_days == 0 else "Tomorrow" if n_days == 1 else f"{d:%A}"
        href = "/my/here?from=home" if ck_open and not ck_err and not (ck or {}).get("marks") else "/my/events"
        items.append(((d, t or _time(23, 59), 0), lh.pass_card(
            art, href=href, day=d, chip=chip, kicker=_e(kicker), title=svc["title"] or church, place=place, count=cnt,
            buttons=(main, watch, cal), note=note, pin=pin)))
        if svc_o:
            week_eids.add(str(svc_o.get("entry_id") or ""))
    for gx in week_g:
        g, d, t = gx["group"], gx["day"], gx.get("time")
        art, pin = spot(f"group:{g['id']}", "groups", title=g.get("name") or "")
        main, cnt = group_act(gx, "lm-wkb")
        items.append(((d, t or _time(23, 59), 1), lh.week_card(
            art, href=f"/my/groups/{g['id']}", day=d, kicker=_e(lh.when(d, t, now)[0]), title=g.get("name") or "",
            place=g.get("location") or (g.get("sched") or {}).get("meet_address") or "", count=cnt, action=main,
            pin=pin)))
    week_occ = []
    for o in occ:
        d = _day(o["date"])
        if not 0 <= (d - day0).days < 7 or str(o.get("entry_id") or "") in week_eids:
            continue
        week_occ.append(o)
        t = lh.parse_hm(o.get("time"))
        art, pin = spot(mpc.event_key(o.get("title")), "events", title=o.get("title") or "")
        if not edit and isinstance(o.get("flyer"), dict) and o["flyer"].get("thumb"):
            # The flyer the church gave the event (event_volunteers.flyer_of), in its colour.
            art = ui.art(o["flyer"]["thumb"])
        main, cnt = event_act(o, "lm-wkb")
        tag = ui.sample_tag() if samples.is_sample(o) else ""
        items.append(((d, t or _time(23, 59), 2), lh.week_card(
            art, href="/my/events", day=d, kicker=_e(lh.when(d, t, now)[0]) + tag, title=o.get("title") or "",
            place=o.get("location") or "", count=cnt, action=main, pin=pin)))
        week_eids.add(str(o.get("entry_id") or ""))
    items.sort(key=lambda x: x[0])
    week_html = lh.week([c for _k, c in items[:8]])
    after = f'<div class="lm-ck">{checkin}</div>' if ck_err and checkin else ""

    # ── the doors: Prayer · Events · Serve · Kids, each with its line ──
    pn, pgroups = mpt.prayer_new(counts)
    doors = [lh.door(f"/my/inbox/group/{pgroups[0]}", "hands", "Prayer", f"{pn} new", new=True) if pn else
             lh.door("/my/connect#lm-pray-h", "hands", "Prayer", "Ask or pray")]
    # What's coming up: the calendar's upcoming occasions (the list Events
    # shows) and this week's service when it isn't on the calendar. A failed
    # calendar read says no number.
    n_events = (sum(1 for o in occ if _day(o["date"]) >= day0) + (1 if svc and not svc_o else 0)
                if occasions is not None else 0)
    doors.append(lh.door("/my/events", "calendar", "Events", f"{n_events} coming up" if n_events else "Calendar"))
    if ssv.on():
        si = serving_info or {}
        soon = None
        for c in si.get("coming") or []:
            d = _day((c.get("service") or {}).get("day"))
            if d and d >= day0:
                at = (c.get("service") or {}).get("at")
                soon = (d, lh.parse_hm(c.get("call_time")) or (at.time() if isinstance(at, datetime) else None))
                break
        # The teams the member can see (theirs and those open to join),
        # from Home's groups read; none when that read failed.
        n_teams = sum(1 for g in ((groups or {}).get("mine") or []) + ((groups or {}).get("open") or [])
                      if g.get("kind") == mpc.GROUP_KINDS["team"])
        if soon:
            line = f"{soon[0]:%a} {lh.leaf_time(soon[1])}".strip()
        elif si.get("asks"):
            line = f"{len(si['asks'])} to answer"
        elif n_teams:
            line = f"{n_teams} team{'' if n_teams == 1 else 's'}"
        else:
            line = "Your teams" if si.get("teams") else "Ways to serve"
        mine_sv = bool(si.get("coming") or si.get("asks") or si.get("teams"))
        doors.append(lh.door("/my/connect#lm-sv-h" if mine_sv else "/my/serving", "hand", "Serve", line,
                             new=bool(si.get("asks")) and not soon))
    ctx = msp.CURRENT.get() or {}
    if "kids" in (ctx.get("options") or []):
        doors.append(lh.door("/my/space?to=kids", "smile", "Kids",
                             "Check-in open" if ck_open else ("Your kids" if ctx.get("kids_parent") else "Your rooms"),
                             new=ck_open))
    # Give, while the church takes gifts in the app, as the fourth door; with
    # Kids already the fourth, Give stays in the tab bar only.
    from giving_router import giving_is_active
    if len(doors) < 4 and giving_is_active(biz):
        doors.append(lh.door("/my/give", "heart", "Give", "Give online"))
    doors_html = lh.doors(doors)

    # ── the moments: the pastor, Sunday, the groups, the events (member_lumen_stories) ──
    theme = resolve_theme(biz, site)
    logo = theme.get("logo_url") or ""
    church_face = (f'<span class="lm-mvlogo"><img src="{_e(logo)}" alt=""></span>' if logo
                   else mls.ring_initials(church))
    moments: List[Dict[str, Any]] = []
    derived_who: Dict[str, str] = {}
    st = (devo or {}).get("st") or {}
    p_post = None if st.get("now") else mls.pastor_post(posts, now)
    if st.get("now"):
        dv_, day = devo["dev"], devo.get("day") or {}
        n, of = int(st["now"]), max(1, int(st.get("count") or 1))
        pic, lk = photos.choose(biz, f"devotional:{dv_['id']}", pool, title=dv_.get("title") or "", look="church")
        author = " ".join(str(dv_.get("author") or "").split())
        line = (day.get("pull") or day.get("title") or dv_.get("title") or "").strip()
        verse = (day.get("scripture") or "").strip()
        sub = " · ".join(x for x in (verse, f"{dv_.get('title') or 'Devotional'}, day {n} of {of}") if x)
        derived_who = {"name": author}
        if line:
            moments.append(mls.moment(
                mid=f"dv:{dv_['id']}:{n}", label=mls.short_name(author) or "Devotional",
                ring=ui.picture(pic, lk, "word"), bg=ui.picture(pic, lk, "word", night=True),
                face=ui.picture(pic, lk, "word"), name=author or (dv_.get("title") or "Devotional"), href=devo["href"],
                kicker=f"A word for {now:%A}", line=mls.clip(line, 160), sub=sub,
                action=lh.link_button(devo["href"], "Read today's", "lm-mvb"), reply=to_church))
    elif p_post:
        a = p_post.get("author") or {}
        aid = str(p_post.get("posted_by"))
        name = " ".join(str(a.get("name") or "").split()) or "Your pastor"
        own = ph.src(a) if ph.shown_to_members(a) else ""
        title, body = (p_post.get("title") or "").strip(), (p_post.get("body") or "").strip()
        posted = mls._at(p_post.get("created_at"))
        derived_who = {"id": aid}
        reply = ((f"/my/messages/to/{aid}", f"Send {name.split()[0]} a note…") if (write or {}).get(aid)
                 else to_church)
        moments.append(mls.moment(
            mid=f"po:{p_post['id']}", label=mls.short_name(name), ring=ui.photo(own, look="colour") if own else
            mls.ring_initials(name), bg=ui.photo(own, look="colour") if own else ui.default_art("word", night=True),
            face=ui.photo(own, look="colour") if own else mls.ring_initials(name), name=name,
            href=f"/my/news/{p_post['id']}", when=mls.ago(p_post.get("created_at"), now),
            kicker=f"A word for {posted.astimezone(now.tzinfo):%A}" if posted else "A word",
            line=mls.clip(title or body, 140), sub=mls.clip(body, 170) if title and body else "",
            action=lh.link_button(f"/my/news/{p_post['id']}", "Read", "lm-mvb"), reply=reply,
            love=mls.love_form(str(p_post["id"]), "love" in (p_post.get("my_rx") or []))))
    # Leaders' own moments (member_moments): the member's own circle and the
    # pastors' first, then the word above (unless it joined its pastor's
    # circle), then the other leaders'. A moment's button is drawn from This
    # week's own records, for this member.
    can_post, lead_love = "", False
    if leaders:
        import member_moments as mmo

        def lead_button(kind: str, ref: str) -> str:
            if kind in ("service", "event"):
                if svc and svc_o and str(svc_o.get("entry_id") or "") == ref:
                    return service_act("lm-mvb")[0]
                o = next((x for x in occ if str(x.get("entry_id") or "") == ref
                          and 0 <= (_day(x["date"]) - day0).days < 7), None)
                return event_act(o, "lm-mvb")[0] if o else ""
            if kind == "gathering":
                gid, _, gday = ref.partition("@")
                gx = next((x for x in week_g if str(x["group"]["id"]) == gid and x["day"].isoformat() == gday), None)
                return group_act(gx, "lm-mvb")[0] if gx else ""
            return ""
        derived = moments.pop() if moments else None
        first_c, after_c, took = mmo.circles(
            leaders, me=me, groups=groups, now=now, church=church, button=lead_button, derived=derived,
            derived_who=derived_who, owner=leaders_owner,
            owner_contact=str((biz.get("settings") or {}).get("church_owner_contact_id") or ""))
        moments.extend(first_c + ([derived] if derived and not took else []) + after_c)
        can_post = "" if mmo.own_showing(leaders, me) else mmo.home_rights(leaders, me, groups)
        lead_love = any(not c.get("mine") and c.get("slides") for c in first_c + after_c)
    sun_msg = ""
    if svc and not samples.is_sample(svc_o or {}):
        d, t = svc["day"], svc.get("time")
        msg = next((s for s in (library or {}).get("sermons") or [] if str(s.get("preached_on") or "")[:10] == d.isoformat()
                    and not samples.is_sample(s)), None)
        sun_msg = str((msg or {}).get("id") or "")
        series = mps._titles(library).get(str((msg or {}).get("series_id") or ""), "") if msg else ""
        pic, lk = photos.choose(biz, "home", pool, fallback=photos.hero(pool), look="colour")
        if not pic and msg:
            # No photo of the church's own: the day's message's video picture
            # (member_yt_pictures) in place of the default picture.
            import member_yt_pictures as myp
            pic, lk = myp.picture_url(msg.get("video_url"), wide=True), "colour"
        main, _cnt, _note = service_act("lm-mvb")
        firsts = new and first and first["day"] == d
        kicker = ("Your first Sunday" + (f" · {lh.clock(t)}" if t else "")) if firsts else lh.when(d, t, now)[0]
        line = (msg or {}).get("title") or svc["title"] or f"See you {'Sunday' if d.weekday() == 6 else d.strftime('%A')}."
        place = (svc_o or {}).get("location") or svc.get("where") or ""
        # Shared only as what has a public page: its message, else the service on the public events page.
        if msg:
            share = mls.share("message", msg["id"], msh.message_href(msg["id"]), line, kicker,
                              msh.message_art(library, msg, site, pool))
        elif svc_o and msh.event_shareable(biz, svc_o):
            share = mls.share("event", svc_o.get("entry_id"), msh.EVENTS_HREF, line, kicker,
                              msh.event_picture(biz, site, svc_o.get("title") or ""))
        else:
            share = ""
        moments.append(mls.moment(
            mid=f"sv:{d.isoformat()}", label="Sunday" if d.weekday() == 6 else f"{d:%A}",
            ring=ui.picture(pic, lk, "welcome"), bg=ui.picture(pic, lk, "welcome", night=True), face=church_face,
            name=church, href="/my/events", kicker=kicker, line=line, sub=" · ".join(x for x in (series, place) if x),
            action=main, reply=(to_church[0], "Ask the church…") if to_church else None, share=share))
    # The church's newest message while it's new (member_feed_more.message_of:
    # preached in the last week, never a sample), unless Sunday's moment is it.
    import member_feed_more as mfm
    new_msg = mfm.message_of(library, day0)
    if new_msg and str(new_msg.get("id")) != sun_msg:
        moments.append(mls.message_moment(biz, site, library, new_msg, pool, day0, face=church_face, church=church))
    for gx in week_g:
        if gx["start"] - now > timedelta(days=mls.GROUP_DAYS):
            continue
        g, d, t = gx["group"], gx["day"], gx.get("time")
        gid = str(g["id"])
        pic, lk = photos.choose(biz, f"group:{gid}", pool, title=g.get("name") or "", look="colour")
        n_going = sum(1 for x in (gx.get("answers") or {}).values() if x == "going")
        place = g.get("location") or (g.get("sched") or {}).get("meet_address") or ""
        moments.append(mls.moment(
            mid=f"gr:{gid}:{d.isoformat()}", label=g.get("name") or "Your group", ring=ui.picture(pic, lk, "groups"),
            bg=ui.picture(pic, lk, "groups", night=True), face=ui.picture(pic, lk, "groups"), name=g.get("name") or "",
            href=f"/my/groups/{gid}", kicker=lh.when(d, t, now)[0], line=g.get("name") or "",
            sub=" · ".join(x for x in (place, f"{n_going} going" if n_going >= 2 else "") if x),
            action=group_act(gx, "lm-mvb")[0],
            reply=(f"/my/groups/{gid}/chat", "Message the group…") if chat_on and g.get("chat_on") is not False else None))
    # The class the member is in and hasn't finished (my_class, kept).
    if klass and klass.get("course_id") and klass.get("title"):
        pic, lk = photos.choose(biz, f"class:{klass['course_id']}", pool, title=klass["title"], look="colour")
        moments.append(mls.class_moment(klass, ui.picture(pic, lk, "classes"),
                                        ui.picture(pic, lk, "classes", night=True), face=church_face, church=church))
    for o in week_occ:
        if samples.is_sample(o):
            continue
        pic, lk = photos.choose(biz, mpc.event_key(o.get("title")), pool, title=o.get("title") or "", look="colour")
        if not pic:
            continue
        d, t = _day(o["date"]), lh.parse_hm(o.get("time"))
        n_going = int(o.get("attending") or 0)
        kicker = lh.when(d, t, now)[0]
        moments.append(mls.moment(
            mid=f"ev:{o.get('entry_id')}", label=o.get("title") or "", ring=ui.picture(pic, lk, "events"),
            bg=ui.picture(pic, lk, "events", night=True), face=church_face, name=church, href="/my/events",
            kicker=kicker, line=o.get("title") or "",
            sub=" · ".join(x for x in (o.get("location") or "", f"{n_going} going" if n_going >= 2 else "") if x),
            action=event_act(o, "lm-mvb")[0], reply=(to_church[0], "Ask about this…") if to_church else None,
            share=mls.share("event", o.get("entry_id"), msh.EVENTS_HREF, o.get("title") or "", kicker,
                            msh.event_picture(biz, site, o.get("title") or ""))
            if msh.event_shareable(biz, o) else ""))
    stories_html = mls.row(moments)

    # The greeting and its sentence (Look 4.1's, unchanged): it names the next
    # gathering, the church's next service, and where the member serves.
    name = first_name(me.get("name") or "")
    said = lh.pick(live=None, ck=None, gnext=gnext, occasions=occ, first=None, now=now)
    import member_feed_more as mfm
    hello = lh.greeting(name, now, lh.line(said, service=service, serving=serving_info, new=new, first=first, now=now,
                                           message=mfm.message_of(library, day0), occasions=occ),
                        new=new)
    mine_pic = ph.src(me)
    face = f'<img src="{_e(mine_pic)}" alt="">' if mine_pic else _e(ui.initials(me.get("name")))
    tip = mmo.soft_card(can_post) if can_post else ""
    # The asks to serve and the celebrations (each wants an answer) after
    # This week, then the composer and the feed.
    under = "".join(x for x in (serving, celebrate) if x)
    # The owner's desk (Kevin's Home plan, 2026-11-21): what waits for them
    # in the office's News room, and the church's first news.
    desk_html = ""
    if owner:
        import app_base
        desk_html = lh.desk(desk, church=church, short=mpc._short_name(church) or church,
                            office=f"{app_base.app_base_url()}/?nav=operate:news", now=now,
                            first_news=desk_post and posts == [], quiet=posts == [])
    top = (f'{editbar}{flash}{stories_html}{lh.live_bar(live) if live else ""}{hello}{tip}{doors_html}{week_html}{after}'
           f'{f"<div class=lm-cards>{under}</div>" if under else ""}{desk_html}{lh.composer(face)}')
    # The feed (`news`: the church's and the groups' posts), then the
    # church's own cards (Kevin's Home plan, 2026-11-21: its newest message,
    # Pick up where you left off and the class, its events after this week,
    # the verse of the day: member_lumen_feed.church_cards), the church's own
    # tiles when it saved some, and "You're all caught up". Nothing below it:
    # the older look's sections are gone (Also for you, Coming up, Today,
    # the message tile, Your group, prayer, and the foot cards: installing
    # the app is on Me, as are notifications and Ask the church).
    import member_lumen_feed as mlf
    shown_msgs = {str((p_.get("sermon") or {}).get("id") or "") for p_ in posts or []}
    church_cards = mlf.church_cards(biz, site, me=me, library=library, occasions=occ, klass=klass, bible=bible,
                                    today=day0, shown=shown_msgs, pool=pool, used=used,
                                    label="New message" if mfm.message_of(library, day0) else "Latest message",
                                    pastor=pastor if new else None)
    saved = mpc.clean_tiles(portal_settings(biz.get("settings")).get("tiles"))
    own_tiles = mpc.home_tiles(biz, site, pool, used, edit=edit) if saved else ""
    # "You're all caught up" ends the feed, unless the feed already said it
    # (between what's new and what's been seen), or the news couldn't be read.
    ending = posts is not None and 'class="lf-done"' not in news
    body = f'{top}{news}{mlf.church_block(biz, church_cards, tiles=own_tiles, ending=ending)}'
    import member_portal_news as mpn
    import member_portal_celebrations as mcl
    script = (mpn.RX_JS if news or lead_love else "") + (mcl.STRIP_JS if celebrate else "")
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
    import member_portal_threads as mpt

    async def groups_and_prayer():
        # Look 5.1's prayer card: this week's requests on the walls of the
        # member's groups (group_prayer.recent: kept two minutes per church
        # and set of groups), once their groups are known.
        got = await asyncio.to_thread(mpc.groups_for, bid, me)
        mine = [str(g["id"]) for g in ((got or {}).get("mine") or [])]
        pr = await asyncio.to_thread(_quiet, group_prayer.recent, bid, mine) if mine and not preview else []
        return got, pr
    import group_prayer
    (groups, prayers), occ, classes, serving, asks, pastor, unread = await asyncio.gather(
        groups_and_prayer(),
        asyncio.to_thread(mpc.upcoming_for, bid, me),
        asyncio.to_thread(_quiet, mcl.classes_for, bid, me) if tab else _nothing(),
        asyncio.to_thread(_quiet, ssv.mine, biz, str(me["id"])) if ssv.on() and not preview else _nothing(),
        _ask_entry(biz, me),
        # Meet the pastor's row (member_pastor.who: kept five minutes).
        asyncio.to_thread(member_pastor.who, biz),
        # Each group's unread count: the top bar's own count, read for this
        # page already (member_portal_threads.counts keeps it 15 s).
        mpt.counts(biz, me))
    per: Dict[str, int] = {}
    if unread:
        for gid, n in (unread.get("groups") or {}).items():
            per[str(gid).lower()] = per.get(str(gid).lower(), 0) + int(n or 0)
        for t, v in (unread.get("notes") or {}).items():
            if str(t).startswith("group:") and v.get("unread"):
                gid = str(t)[len("group:"):].lower()
                per[gid] = per.get(gid, 0) + int(v["unread"])
    return {"groups": samples.fill(groups, "groups", preview), "occasions": samples.fill(occ, "occasions", preview),
            "classes": samples.fill(classes, "classes", preview) if tab else None, "serving": serving,
            "asks": asks or [], "pastor": pastor, "prayers": prayers, "unread": per}


def render_connect(biz: Dict[str, Any], site, request, me: Dict[str, Any], data: Dict[str, Any],
                   *, new_card: str = "") -> str:
    """Connect in Look 5.1 (member_lumen_connect): the title, your groups,
    serving, classes, prayer, find your people, your next step, more."""
    import member_app_photos as photos
    import member_directory
    import member_lumen_connect as lc
    import member_lumen_ui as lm
    import member_portal_church as mpc
    import member_spaces as msp
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "your church"
    pool = photos.photos(biz, site)
    used: set = set()
    groups = data.get("groups")
    now = church_now(biz)
    parts = [lc.sub(church), mpc._flash(request, data.get("occasions"))]
    mine = (groups or {}).get("mine") or []
    if groups is None:
        parts.append('<p class="mp-err" role="alert" style="margin-top:24px">Your groups couldn\'t load just now. '
                     'Please try again in a moment.</p>')
    else:
        parts.append(lc.group_rows(biz, mine, data.get("unread") or {}, pool, used, now))
    parts.append(lc.serving_card(data.get("serving")))
    parts.append(lc.classes_list(data.get("classes")))
    parts.append(lc.prayer_card(data.get("prayers"), str(me.get("id") or ""), bool(mine)))
    if groups is not None:
        parts.append(lc.discover(biz, (groups or {}).get("open") or [], pool, used, alone=not mine))
    asks = data.get("asks") or []
    steps = []
    if "life_event" in asks:
        steps.append(lm.row("/my/ask/life", lm.round_icon("drop", "var(--lm-teal)"), "Get baptized",
                            "Ask the church to plan it with you"))
    if "visit" in asks or "help" in asks:
        steps.append(lm.row("/my/ask", lm.round_icon("chat", "var(--lm-coral)"), "Ask for a visit or help",
                            "It goes straight to the people who care for members"))
    steps_html = "".join(steps)
    if new_card or steps_html:
        parts.append(f'<section aria-labelledby="lm-next-h">{lm.section("Your next step", hid="lm-next-h")}'
                     f'<div class="lm-newslot">{new_card}</div>'
                     f'{f"<div class=lm-list>{steps_html}</div>" if steps_html else ""}</section>')
    ctx = msp.CURRENT.get() or {}
    directory = (member_directory.church_on(biz) and (ctx.get("space") or "church") == "church"
                 and not ctx.get("youth"))
    parts.append(lc.more_rows(biz, pastor=data.get("pastor"), week_events=lc.week_count(data.get("occasions"), now.date()),
                              directory=directory))
    body = f'<div class="lm-cx">{"".join(p for p in parts if p)}</div>'
    return _shell(biz, site, "Connect", body, tab="connect", who=me, lumen_top=lc.top(biz))
