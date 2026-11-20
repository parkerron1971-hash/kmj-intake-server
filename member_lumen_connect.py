"""member_lumen_connect.py — Connect and a group's page in the member app's
new look, "Look 5.1".

Kevin approved Look 5.1 (2026-11-20): "this is awesome. much better design.
lets build this including the new still to build!" This file draws the
mock's Connect tab and a group's page from the records the member app
already reads; nothing is made up, and a block with nothing real in it is
left out.

CONNECT (/my/connect, member_portal_lumen.render_connect), in the mock's
order:

  1. "Connect" and "Your people at <church>" (the message bubble with its
     count is the top bar's, which the shell draws).
  2. Your groups: a row per group with its picture (the church's own for the
     group, else its initials), when it meets next on the church's clock
     ("Tonight at 7 PM"), and the chat's real unread count
     (member_portal_threads.counts: notes plus chat messages, kept 15 s);
     Find a group.
  3. Serving: the next date, as a card with the date on a leaf, the team and
     the time, the place and who serves with them; I'll be there and Can't
     make it are My serving's own answers (an ask) or its Can't make it (a
     date already said yes to).
  4. Classes: the class in progress, "Lesson n of m" with the next lesson's
     title when the class names one, a progress bar; and the next class open
     to join, with Sign up (the Classes page's own join).
  5. Prayer: the requests on the walls of the member's groups this week
     (group_prayer.recent: kept two minutes), by first name as the wall shows
     them, never the member's own; Pray for them (the wall) and Ask for
     prayer (to the pastors). With none, How can we pray for you?
  6. Find your people: groups open to join, two to a row, with Join or Ask to
     join (the groups' own join), how many are in each.
  7. Your next step (the "I'm new here" card and the asks), then More: Your
     pastor (member_pastor), Events, the Church directory, each only where
     it's on.

A GROUP (/my/groups/<id>, member_portal_groups.render): the group's picture
across the top with Back and More over it, the name in the serif, "Members
only · N people · when", a few faces and names (who shows is today's rule:
its people to its members, its leaders to anyone else), Joined and Chat,
then Posts · Events · Prayer · Members (the group's Home and Board, Meet,
Prayer and People). On Posts: the next gathering on a card with the date on
a leaf, I'll be there (the group's own answer) and Directions (a map of the
group's street address, which shows only to the group); a box to write to
the group (a leader: the Board; anyone else: the chat, where it's open);
the Board's posts as Home's feed cards.

The CSS joins /my/lumen.<hash>.css through member_lumen_ui.templates();
every rule sits under body.lm, tokens only, so Light, Dark and Same as my
phone all hold.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from string import Template
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

# The mock's own icons (build_hybrid.py) that the app's sets don't have.
ICONS = {
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/>'
             '<path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "mappin": '<path d="M20 10c0 4.99-5.54 10.19-7.4 11.8a1 1 0 0 1-1.2 0C9.54 20.19 4 14.99 4 10a8 8 0 0 1 16 0"/>'
              '<circle cx="12" cy="10" r="3"/>',
    "book2": '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>',
}
DISCOVER_SHOWN = 2      # Find your people, for someone already in a group
DISCOVER_ALONE = 4      # ...and for someone in none
PRAYER_SHOWN = 2        # the requests read out on the prayer card
PRAYER_CHARS = 84


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def ic(name: str, size: int = 20) -> str:
    import member_lumen_ui as lm
    if name in ICONS:
        return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
                f'focusable="false">{ICONS[name]}</svg>')
    return lm.ic(name, size)


def _chev() -> str:
    return ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")


def _leaf(d: date) -> str:
    """The date on a leaf: the weekday small in the church's colour, the
    day in the serif, on the church's soft tint."""
    return (f'<span class="lm-cleaf" aria-hidden="true"><small>{d.strftime("%a").upper()}</small>'
            f'<b>{d.day}</b></span>')


def _clip(text: Any, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _and(names: List[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


# ─── Connect ─────────────────────────────────────────────────────────


def title(church: str) -> str:
    """The tab's title and who it's about."""
    return (f'<header class="lm-ctop"><h1 class="lm-ctt">Connect</h1>'
            f'<p class="lm-ctsub">Your people at {_e(church)}</p></header>')


def _thumb(biz: Dict[str, Any], g: Dict[str, Any], pool: List[str], used: set, cls: str = "lm-gth") -> str:
    """A group's picture: the church's own for it (or a photo named for
    it), else its initials on the soft teal."""
    import member_app_photos as photos
    import member_app_ui as ui
    pic, look = photos.choose(biz, "group:" + str(g.get("id")), pool or [], title=g.get("name") or "", used=used)
    if pic:
        return f'<span class="{cls} has-ph">{ui.photo(pic, look=look)}</span>'
    return f'<span class="{cls}" aria-hidden="true"><b>{_e(ui.initials(g.get("name")))}</b></span>'


def when_local(start: datetime, now: datetime) -> str:
    """"Tonight at 7 PM", "Tomorrow at 7 PM", "Thursday at 7 PM", "Thu, Dec 4
    at 7 PM": a start on the same clock as `now` (the Classes page's words,
    member_portal_classes.when_text, without changing clocks)."""
    import member_portal_classes as mcl
    days = (start.date() - now.date()).days
    clock = mcl._clock(start)
    if days == 0:
        return f"{'Tonight' if start.hour >= 17 else 'Today'} at {clock}"
    if days == 1:
        return f"Tomorrow at {clock}"
    if 1 < days < 7:
        return f"{start.strftime('%A')} at {clock}"
    return f"{start.strftime('%a, %b')} {start.day} at {clock}"


def next_start(g: Dict[str, Any], now: datetime) -> Optional[datetime]:
    """When the group next meets, on the church's clock, from its regular
    time (read with the group); None for a group with no regular time."""
    import group_gatherings as gg
    sched = g.get("sched") or {}
    if not gg.scheduled(sched):
        return None
    day, _skipped = gg.next_on(sched, now)
    return gg.starts_at(sched, day, now.tzinfo) if day else None


def next_text(biz: Dict[str, Any], g: Dict[str, Any], now: datetime) -> str:
    """When the group meets next ("Tonight at 7 PM", "Thursday at 7 PM",
    "Thu, Dec 4 at 7 PM"); '' for a group with no regular time."""
    start = next_start(g, now)
    return when_local(start, now) if start else ""


def group_rows(biz: Dict[str, Any], mine: List[Dict[str, Any]], unread: Dict[str, int], pool: List[str],
               used: set, now: datetime, top: int = 5) -> str:
    """Your groups: a row per group, its next gathering (or its regular
    time) and where, and its chat's unread count when there is one."""
    rows = []
    # Meeting now first, then the soonest gathering, then the rest by name.
    far = now.replace(year=now.year + 5)
    order = sorted(mine, key=lambda g: (not g.get("live"), next_start(g, now) or far, str(g.get("name") or "").lower()))
    for g in order[:top]:
        gid = str(g["id"])
        href = f"/my/groups/live/{g['live']['id']}" if g.get("live") else f"/my/groups/{gid}"
        when = "Meeting now" if g.get("live") else (next_text(biz, g, now) or g.get("meets") or "")
        bits = [when or (g.get("kind") or ""), g.get("location") or ""]
        if g.get("role") == "leader":
            bits.insert(0, "You lead")
        n = int(unread.get(gid.lower()) or 0)
        end = (f'<span class="lm-gnew" aria-label="{n} new">{n if n < 100 else "99+"}</span>' if n else _chev())
        rows.append(f'<a class="lm-grow" href="{_e(href)}">{_thumb(biz, g, pool, used)}<span class="lm-wt"><b>{_e(g.get("name"))}</b>'
                    f'<span>{_e(" · ".join(b for b in bits if b))}</span></span>{end}</a>')
    if not rows:
        return ""
    more = (f'<a class="lm-cxmore" href="/my/groups">See all {len(mine)} groups</a>' if len(mine) > top else "")
    import member_lumen_ui as lm
    return (f'<section aria-labelledby="lm-grp-h">{lm.section("Your groups", "/my/groups", "Find a group", hid="lm-grp-h")}'
            f'<div class="lm-glist">{"".join(rows)}</div>{more}</section>')


def _clock(hhmm: Optional[str]) -> str:
    import member_portal_serving as mpsv
    return mpsv._clock(hhmm) if hhmm else ""


def serving_card(m: Optional[Dict[str, Any]]) -> str:
    """Serving: the next date the member is asked for or on, as a card."""
    import member_lumen_ui as lm
    if not m:
        return ""
    asks = sorted(m.get("asks") or [], key=lambda x: x["service"]["at"])
    coming = sorted(m.get("coming") or [], key=lambda x: x["service"]["at"])
    first = min(asks[:1] + coming[:1], key=lambda x: x["service"]["at"]) if (asks or coming) else None
    out = []
    if first:
        c = first
        at = c["service"]["at"]
        clock = _clock(c.get("call_time")) or at.strftime("%I:%M %p").lstrip("0")
        head = " · ".join(x for x in (c.get("team") or "", clock) if x)
        title_ = c["service"].get("title") or ""
        place = c.get("place") or ""
        if title_ not in ("", "Sunday service", "An event"):
            place = " · ".join(x for x in (place, title_) if x)
        names = [str(n).split(" ")[0] for n in (c.get("with") or []) if n]
        line = f"{place} with {_and(names)}" if names and place else (place or "")
        cid = _e(c["id"])
        if c in asks:
            ask_line = f'{_e(c.get("asked_by") or c.get("team") or "Your team")} asked you'
            acts = (f'<form method="post" action="/my/serving/answer"><input type="hidden" name="id" value="{cid}">'
                    f'<input type="hidden" name="ans" value="yes"><button class="lm-cpill pri" type="submit">I\'ll be there</button></form>'
                    f'<a class="lm-cpill" href="/my/serving/{cid}">Can\'t make it</a>')
            note = f'<span class="lm-svwho">{ask_line}</span>'
        elif c.get("swap_name"):
            acts = ""
            note = (f'<span class="lm-svwho">{_e(str(c["swap_name"]).split(" ")[0])} was asked to cover. '
                    f'You stay on until they say yes.</span>')
        else:
            acts = (f'<a class="lm-cpill on" href="/my/serving">{ic("check", 15)}You\'re on</a>'
                    f'<a class="lm-cpill" href="/my/serving?sub={cid}#sv-{cid}">Can\'t make it</a>')
            note = ""
        out.append(f'<div class="lm-svc"><div class="lm-svr">{_leaf(at.date() if hasattr(at, "date") else at)}'
                   f'<span class="lm-wt"><b>{_e(head or "Serving")}</b>{f"<span>{_e(line)}</span>" if line else ""}{note}</span></div>'
                   f'{f"<div class=lm-cpills>{acts}</div>" if acts else ""}</div>')
        more = len(asks) - (1 if c in asks else 0)
        if more > 0:
            out.append(lm.row("/my/serving", lm.round_icon("give", "var(--lm-violet)"),
                              f"{more} more ask{'' if more == 1 else 's'} to serve", "Say yes, or that you can't that day",
                              cls="lm-wrow"))
    elif m.get("teams"):
        out.append(lm.row("/my/serving", lm.round_icon("give", "var(--lm-violet)"), "My serving",
                          ", ".join(t["name"] for t in m["teams"][:3]), cls="lm-pray"))
    if not out:
        return ""
    return (f'<section aria-labelledby="lm-sv-h">{lm.section("Serving", "/my/serving", "My schedule", hid="lm-sv-h")}'
            f'{"".join(out)}</section>')


def classes_list(data: Optional[Dict[str, Any]]) -> str:
    """Classes: the one in progress (Lesson n of m, the bar) and the next
    one open to join (Sign up)."""
    import member_lumen_ui as lm
    import member_portal_classes as mcl
    if not data:
        return ""
    tz = data.get("tz") or "UTC"
    rows = []
    mine = [c for c in data.get("mine") or [] if c.get("status") != "completed"]
    if mine:
        c = mine[0]
        total, done = int(c.get("total") or 0), int(c.get("done") or 0)
        name = c.get("program") or c.get("title") or "Your class"
        n = c.get("next") or {}
        if total and done < total:
            line = f"Lesson {done + 1} of {total}"
        elif total:
            line = f"{done} of {total} lessons"
        else:
            line = "Just started"
        if n.get("lesson"):
            line += f" · {n['lesson']}"
        elif n.get("live"):
            line += " · Live now"
        elif n.get("starts_at"):
            line += f" · Next {mcl.when_text(n.get('starts_at'), tz)}"
        bar = (f'<span class="lm-cbar" role="progressbar" aria-label="Lessons done" aria-valuemin="0" aria-valuemax="{total}" '
               f'aria-valuenow="{done}"><i style="width:{round(100 * done / total)}%"></i></span>' if total else "")
        rows.append(f'<a class="lm-crow2" href="/my/classes"><span class="lm-cic">{ic("cap", 22)}</span>'
                    f'<span class="lm-wt"><b>{_e(name)}</b><span>{_e(line)}</span>{bar}</span>{_chev()}</a>')
    if data.get("open"):
        o = data["open"][0]
        hid = f"lm-co-{_e(o.get('course_id'))}"
        when = mcl.date_text(o.get("starts_at"), tz)
        bits = [f"Starts {when}" if when else "", f"with {o['teacher']}" if o.get("teacher") else "",
                "" if when else (f"{o['lessons']} lessons" if o.get("lessons") else "")]
        line = " · ".join(b for b in bits if b) or "Open to join"
        rows.append(f'<div class="lm-crow2"><span class="lm-cic alt">{ic("book2", 22)}</span>'
                    f'<span class="lm-wt"><b id="{hid}">{_e(o.get("title") or "A class")}</b><span>{_e(line)}</span></span>'
                    f'<form method="post" action="/my/classes/join"><input type="hidden" name="course_id" value="{_e(o.get("course_id"))}">'
                    f'<button class="lm-cpill sm" type="submit" aria-describedby="{hid}">Sign up</button></form></div>')
    if not rows:
        return ""
    return (f'<section aria-labelledby="lm-cls-h">{lm.section("Classes", "/my/classes", "All classes", hid="lm-cls-h")}'
            f'<div class="lm-clist">{"".join(rows)}</div></section>')


def prayer_card(items: Optional[List[Dict[str, Any]]], me_id: str, has_groups: bool) -> str:
    """Prayer: this week's requests from the member's groups (never their
    own), Pray for them and Ask for prayer; with none, the private ask."""
    import member_lumen_ui as lm
    shown = [p for p in (items or []) if str(p.get("contact_id") or "") != str(me_id)]
    if shown:
        n = len(shown)
        wall = f"/my/groups/{_e(shown[0]['group_id'])}/prayer"
        said = "".join(f'<span class="lm-pwi"><b>{_e(p.get("first") or "Someone")}</b>'
                       f'<span>{_e(_clip(p.get("body"), PRAYER_CHARS))}</span></span>'
                       for p in shown[:PRAYER_SHOWN])
        kick = f"{n} new this week from your group{'s' if len({p['group_id'] for p in shown}) > 1 else ''}"
        body = (f'<p class="lm-pwk">{_e(kick)}</p><div class="lm-pwsay">{said}</div>'
                f'<div class="lm-cpills"><a class="lm-cpill pri" href="{wall}">{ic("pray", 15)}Pray for them</a>'
                f'<a class="lm-cpill" href="/my/prayer">Ask for prayer</a></div>')
        head = lm.section("Prayer", wall, "Prayer wall", hid="lm-pray-h")
    else:
        body = (f'<p class="lm-pwsay lm-pwask">{lm.ic("flame", 18)}<span>How can we pray for you?</span></p>'
                f'<p class="lm-pwn">It goes privately to the pastors.</p>'
                f'<div class="lm-cpills"><a class="lm-cpill pri" href="/my/prayer">Ask for prayer</a></div>')
        head = lm.section("Prayer", hid="lm-pray-h")
    return f'<section aria-labelledby="lm-pray-h">{head}<div class="lm-pw">{body}</div></section>'


def discover(biz: Dict[str, Any], open_: List[Dict[str, Any]], pool: List[str], used: set, *, alone: bool) -> str:
    """Find your people: groups open to join, two to a row, each with Join
    (in right away) or Ask to join (a leader says yes)."""
    import member_lumen_ui as lm
    shown = open_[:DISCOVER_ALONE if alone else DISCOVER_SHOWN]
    if not shown:
        return ""
    cards = []
    for g in shown:
        gid = _e(g["id"])
        hid = f"lm-dc-{gid}"
        n = int(g.get("count") or 0)
        bits = [g.get("meets") or g.get("kind") or "", f"{n} member{'' if n == 1 else 's'}" if n else ""]
        if g.get("asked"):
            act = f'<a class="lm-cpill full on" href="/my/groups/{gid}">{ic("check", 15)}Asked</a>'
        else:
            label = "Join" if g.get("mode") == "open" else "Ask to join"
            act = (f'<form method="post" action="/my/groups/ask"><input type="hidden" name="group_id" value="{gid}">'
                   f'<button class="lm-cpill full" type="submit" aria-describedby="{hid}">{label}</button></form>')
        cards.append(f'<div class="lm-dc"><a href="/my/groups/{gid}" class="lm-dcl">{_thumb(biz, g, pool, used, "lm-dimg")}'
                     f'<b id="{hid}">{_e(g.get("name"))}</b><small>{_e(" · ".join(b for b in bits if b))}</small></a>{act}</div>')
    return (f'<section aria-labelledby="lm-find-h">{lm.section("Find your people", "/my/groups", "See all", hid="lm-find-h")}'
            f'<div class="lm-disc">{"".join(cards)}</div></section>')


def _lrow(href: str, lead: str, title_: str, sub: str) -> str:
    return (f'<a class="lm-mrow" href="{_e(href)}">{lead}<span class="lm-wt"><b>{_e(title_)}</b>'
            f'{f"<span>{_e(sub)}</span>" if sub else ""}</span>{_chev()}</a>')


def more_rows(biz: Dict[str, Any], *, pastor: Optional[Dict[str, Any]], week_events: Optional[int],
              directory: bool) -> str:
    """More: Your pastor, Events, the Church directory, each only where it's on."""
    rows = []
    if pastor and pastor.get("id"):
        import member_pastor
        face = f'<span class="lm-lface lm-pface">{member_pastor._art(biz, pastor)}</span>'
        rows.append(_lrow("/my/pastor", face, "Your pastor",
                          " · ".join(x for x in (pastor.get("name") or "", pastor.get("title") or "") if x)))
    if week_events is not None:
        sub = (f"{week_events} this week" if week_events else "What's coming up")
        rows.append(_lrow("/my/events", f'<span class="lm-lic">{ic("calendar", 19)}</span>', "Events", sub))
    if directory:
        rows.append(_lrow("/my/directory", f'<span class="lm-lic">{ic("directory", 19)}</span>', "Church directory",
                          "Members who chose to be listed"))
    if not rows:
        return ""
    import member_lumen_ui as lm
    return (f'<section aria-labelledby="lm-more-h">{lm.section("More", hid="lm-more-h")}'
            f'<div class="lm-clist">{"".join(rows)}</div></section>')


def week_count(occasions: Optional[List[Dict[str, Any]]], today: date) -> Optional[int]:
    """How many events fall in the coming seven days (Coming up's own list);
    None when it couldn't be read."""
    if occasions is None:
        return None
    n = 0
    for o in occasions:
        try:
            d = date.fromisoformat(str(o.get("date"))[:10])
        except ValueError:
            continue
        if 0 <= (d - today).days < 7:
            n += 1
    return n


# ─── a group's page ──────────────────────────────────────────────────


def cover(biz: Dict[str, Any], site, g: Dict[str, Any], *, menu: str = "") -> str:
    """The group's picture across the top (the church's own for it, or a
    photo named for it; else its initials on the soft teal), with Back
    (Connect, or wherever they came from) and More over it."""
    import member_app_photos as photos
    import member_app_ui as ui
    pool = photos.photos(biz, site)
    pic, look = photos.choose(biz, f"group:{g['id']}", pool, title=g.get("name") or "")
    art = (ui.photo(pic, eager=True, look=look) if pic else
           f'<span class="lm-gcov-i" aria-hidden="true">{_e(ui.initials(g.get("name")))}</span>')
    more = (f'<details class="lm-gmore"><summary class="lm-fab r" aria-label="More">{ic("more", 20)}</summary>'
            f'<div class="lm-gmenu">{menu}</div></details>' if menu else "")
    return (f'<div class="lm-gcov{" has-ph" if pic else ""}">{art}'
            f'<a class="lm-fab l" href="/my/connect" data-back aria-label="Back">{ic("back", 20)}</a>{more}</div>')


def regular(g: Dict[str, Any]) -> str:
    """When the group meets, as the mock says it: "Thursdays at 7 PM", else
    the group's own words for it."""
    import group_gatherings as gg
    if gg.scheduled(g) and int(g.get("meet_every") or 1) == 1:
        t = gg._time(g)
        hour = t.hour % 12 or 12
        clock = f"{hour}{f':{t.minute:02d}' if t.minute else ''} {'AM' if t.hour < 12 else 'PM'}"
        return f"{gg.DAYS[int(g['meet_day'])]}s at {clock}"
    if gg.scheduled(g):
        return gg.regular_text(g)
    return str(g.get("meets") or "")


def head(g: Dict[str, Any], people: List[Dict[str, Any]], leaders: List[Dict[str, Any]], in_group: bool, *,
         me_id: str, face, name) -> str:
    """The name in the serif; Members only, how many, when; faces and names.
    `face` and `name` are the group page's own helpers (photos members may
    see; names the way the group shows them)."""
    n = len(people)
    when = regular(g)
    if in_group:
        bits = [f"{n} {'person' if n == 1 else 'people'}", when]
        sub = (f'<p class="lm-gsub">{ic("lock", 14)}<span>Members only · {_e(" · ".join(b for b in bits if b))}</span></p>')
        others = [p for p in leaders + [p for p in people if p["role"] != "leader"] if p["id"] != me_id]
        shown = others[:5]
        named = [name(p).split(" ")[0] for p in others[:2]]
        rest = n - len(named) - (1 if any(p["id"] == me_id for p in people) else 0)
        said = (_and(named + ([f"{rest} other{'s' if rest != 1 else ''}"] if rest > 0 else [])) +
                (" and you" if any(p["id"] == me_id for p in people) and not rest else ""))
    else:
        how = {"open": "Open to join", "ask": "A leader says yes"}.get(g.get("join_mode") or "", "")
        sub = f'<p class="lm-gsub"><span>{_e(" · ".join(b for b in (how, when) if b))}</span></p>'
        shown = leaders[:3]
        said = ("Led by " + _and([name(p).split(" ")[0] for p in leaders])) if leaders else ""
    faces = "".join(face(p) for p in shown)
    mem = (f'<p class="lm-gmem"><span class="lm-gfaces" aria-hidden="true">{faces}</span><span>{_e(said)}</span></p>'
           if faces or said else "")
    return f'<header class="lm-gh"><h1 class="lm-gname" id="gs-name">{_e(g.get("name") or "")}</h1>{sub}{mem}</header>'


def buttons(gid: str, role: Optional[str], chat: bool) -> str:
    """Joined (or You lead) and Chat. Invite is left out: a group has no
    invitation to send yet (leaders bring people in from the office)."""
    joined = (f'<a class="lm-cpill on" href="/my/groups/{_e(gid)}/people">{ic("check", 15)}'
              f'{"You lead" if role == "leader" else "Joined"}</a>')
    talk = (f'<a class="lm-cpill" href="/my/groups/{_e(gid)}/chat">{ic("chat", 15)}Chat</a>' if chat else "")
    return f'<div class="lm-gbtns">{joined}{talk}</div>'


TABS = (("", "Posts"), ("meet", "Events"), ("prayer", "Prayer"), ("people", "Members"))


def tabs(gid: str, current: str, *, board_new: int, live: Optional[Dict[str, Any]]) -> str:
    """Posts · Events · Prayer · Members: the group's Home and Board, Meet,
    Prayer and People (and Video while a meeting is open)."""
    cur = "" if current == "board" else current
    out = []
    for key, label in TABS:
        here = ' aria-current="page"' if key == cur else ""
        n = board_new if key == "" and cur != "" else 0
        badge = f'<span class="lm-gtn" aria-label="{n} new">{n}</span>' if n else ""
        href = f"/my/groups/{_e(gid)}" + (f"/{key}" if key else "")
        out.append(f'<a href="{href}"{here}>{label}{badge}</a>')
    if live:
        out.append(f'<a href="/my/groups/live/{_e(live["id"])}">Video</a>')
    return f'<nav class="lm-gtabs" aria-label="In this group">{"".join(out)}</nav>'


def tonight(biz: Dict[str, Any], g: Dict[str, Any], v: Optional[Dict[str, Any]], people: List[Dict[str, Any]], *,
            me_id: str, face) -> str:
    """The next gathering: the date on a leaf, when, where and the leaders'
    note, who's going; I'll be there (the group's own answer, back here) and
    Directions (a map of the group's street address)."""
    import group_gatherings as gg
    if not v or not v.get("next"):
        return ""
    nxt = v["next"]
    gid = _e(g["id"])
    start = gg.starts_at(g, nxt, v["now"].tzinfo)
    when = when_local(start, v["now"])
    where = " · ".join(_clip(x, 60) for x in (g.get("location") or "", g.get("meet_note") or "") if x)
    rs = v.get("rsvps") or {}
    going = [p for p in people if rs.get(p["id"]) == "going"]
    mine = v.get("mine")
    others = len([p for p in going if p["id"] != me_id])
    count = (("You" + (f" and {others} other{'s' if others != 1 else ''}" if others else "") + " going")
             if mine == "going" else (f"{len(going)} going" if going else ""))
    faces = "".join(face(p) for p in going[:3])
    who = (f'<span class="lm-gwho"><span class="lm-gfaces" aria-hidden="true">{faces}</span><span>{_e(count)}</span></span>'
           if count else "")
    hidden = f'<input type="hidden" name="group_id" value="{gid}"><input type="hidden" name="back" value="/my/groups/{gid}">'
    if v.get("today") and v.get("here"):
        main = f'<span class="lm-cpill on">{ic("check", 15)}You\'re counted</span>'
    elif v.get("today") and v.get("can_here"):
        main = (f'<form method="post" action="/my/groups/meet/here">{hidden}'
                f'<button class="lm-cpill pri" type="submit">{ic("check", 15)}I\'m here</button></form>')
    elif mine == "going":
        main = f'<a class="lm-cpill on" href="/my/groups/{gid}/meet">{ic("check", 15)}You\'re going</a>'
    else:
        main = (f'<form method="post" action="/my/groups/meet/rsvp">{hidden}<input type="hidden" name="answer" value="going">'
                f'<button class="lm-cpill pri" type="submit">I\'ll be there</button></form>')
    addr = str(g.get("meet_address") or "").strip()
    maps = (f'<a class="lm-cpill" href="https://www.google.com/maps/search/?api=1&amp;query={quote(addr, safe="")}" '
            f'target="_blank" rel="noopener">{ic("mappin", 15)}Directions</a>' if addr else "")
    return (f'<section class="lm-meet" aria-label="The next gathering"><a class="lm-meetc" href="/my/groups/{gid}/meet">'
            f'{_leaf(nxt)}<span class="lm-wt"><b>{_e(when[:1].upper() + when[1:])}</b>'
            f'{f"<span>{_e(where)}</span>" if where else ""}{who}</span></a>'
            f'<div class="lm-cpills">{main}{maps}</div></section>')


def composer(me: Dict[str, Any], href: str, placeholder: str = "Write something to the group…") -> str:
    """The box to write to the group: the member's face, the prompt, a photo
    button; it opens where this member can write (`href`)."""
    import member_app_ui as ui
    import member_photos as ph
    mine = ph.src(me) if me else ""
    face = (f'<span class="lm-gme"><img src="{_e(mine)}" alt=""></span>' if mine
            else f'<span class="lm-gme" aria-hidden="true">{_e(ui.initials((me or {}).get("name")))}</span>')
    return (f'<div class="lm-gcomp">{face}<a class="lm-gin" href="{_e(href)}">{_e(placeholder)}</a>'
            f'<a class="lm-icb" href="{_e(href)}" aria-label="Add a photo">{ic("image", 22)}</a></div>')


CSS = Template("""
/* Connect and a group's page, Look 5.1 (member_lumen_connect) */
.lm .lm-ctop{margin:14px 0 0;}
.lm .lm-ctt{margin:0;font:800 30px/1.05 var(--mb-ui);letter-spacing:-.028em;color:var(--fg);}
.lm .lm-ctsub{margin:6px 0 0;font:400 14.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm .lm-cx .lm-sec{margin:32px 0 10px;}
.lm .lm-cx .lm-h2{font-size:19px;}
.lm .lm-cxmore{display:inline-block;margin-top:6px;padding:6px 0;color:var(--acc);font:650 14px/1 var(--mb-ui);text-decoration:none;}

/* Your groups */
.lm .lm-glist{display:flex;flex-direction:column;}
.lm .lm-grow{display:flex;align-items:center;gap:14px;padding:9px 0;color:var(--fg);text-decoration:none;}
.lm .lm-gth{position:relative;width:58px;height:58px;flex:none;border-radius:16px;overflow:hidden;display:grid;place-items:center;
  background:var(--lm-mint);color:var(--lm-mint-ink);}
.lm .lm-gth b{font:italic 500 19px/1 var(--mb-serif);}
.lm .lm-gth .mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;}
.lm .lm-gth img,.lm .lm-dimg img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lm-grow .lm-wt b{font-size:16px;font-weight:700;}
.lm .lm-grow .lm-wt>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lm-gnew{min-width:22px;height:22px;padding:0 7px;flex:none;border-radius:11px;background:var(--acc-fill);color:var(--on-acc);
  font:700 12px/22px var(--mb-ui);text-align:center;}

/* pills: the mock's round buttons */
.lm .lm-cpills{display:flex;gap:8px;margin-top:12px;}
.lm .lm-cpills>*{flex:1;min-width:0;}
.lm .lm-cpills form{display:flex;}
.lm .lm-cpill{display:inline-flex;align-items:center;justify-content:center;gap:7px;width:100%;height:42px;padding:0 16px;border-radius:21px;
  border:1.5px solid var(--lm-line);background:var(--bg);color:var(--fg);font:650 14px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;
  cursor:pointer;transition:transform .15s ease,background-color .2s,color .2s;}
.lm .lm-cpill:active{transform:scale(.97);}
.lm .lm-cpill.sm{width:auto;height:36px;padding:0 14px;font-size:13.5px;}
.lm .lm-cpill.pri{background:var(--acc-fill);border-color:var(--acc-fill);color:var(--on-acc);}
.lm .lm-cpill.on{background:var(--lm-tint-10);border-color:transparent;color:var(--acc);}
.lm .lm-cpill .lm-ic{flex:none;}
.lm .lm-cpill:focus-visible,.lm .lm-fab:focus-visible,.lm .lm-gtabs a:focus-visible,.lm .lm-gin:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}

/* the date on a leaf */
.lm .lm-cleaf{width:46px;flex:none;padding:6px 0 7px;border-radius:12px;background:var(--lm-tint-10);text-align:center;}
.lm .lm-cleaf small{display:block;font:750 10px/1 var(--mb-ui);letter-spacing:.12em;color:var(--acc);}
.lm .lm-cleaf b{display:block;margin-top:3px;font:500 21px/1.05 var(--mb-serif);color:var(--fg);}

/* Serving */
.lm .lm-svc{padding:14px;border-radius:18px;box-shadow:inset 0 0 0 1px var(--lm-line);}
.lm .lm-svr{display:flex;align-items:center;gap:14px;}
.lm .lm-svc .lm-wt b{font-size:15.5px;font-weight:700;}
.lm .lm-svc .lm-wt>span{font-size:13px;}
.lm .lm-svwho{display:block;margin-top:3px;font:500 12.5px/1.35 var(--mb-ui);color:var(--fg3);}
.lm .lm-svc+.lm-wrow{margin-top:6px;}

/* Classes and More: one bordered list */
.lm .lm-clist{border-radius:18px;box-shadow:inset 0 0 0 1px var(--lm-line);overflow:hidden;}
.lm .lm-crow2{display:flex;align-items:center;gap:14px;padding:14px;color:var(--fg);text-decoration:none;}
.lm .lm-crow2+.lm-crow2,.lm .lm-mrow+.lm-mrow{border-top:1px solid var(--lm-line);}
.lm .lm-cic{width:52px;height:52px;flex:none;border-radius:14px;display:grid;place-items:center;background:var(--lm-tint-10);color:var(--acc);}
.lm .lm-cic.alt{background:var(--s1);color:var(--lm-teal);}
@supports (background:color-mix(in srgb,red 50%,blue)){.lm .lm-cic.alt{background:color-mix(in srgb,var(--lm-teal) 13%,var(--bg));}}
.lm .lm-crow2 .lm-wt b{font-size:15.5px;font-weight:700;}
.lm .lm-crow2 .lm-wt>span{font-size:13px;}
.lm .lm-cbar{display:block;height:4px;margin-top:9px;border-radius:2px;background:var(--s2);overflow:hidden;}
.lm .lm-cbar i{display:block;height:100%;border-radius:2px;background:var(--acc-fill);}
.lm .lm-crow2 form{flex:none;}
.lm .lm-mrow{display:flex;align-items:center;gap:14px;padding:12px 14px;color:var(--fg);text-decoration:none;}
.lm .lm-mrow .lm-wt b{font-size:15px;font-weight:650;}
.lm .lm-mrow .lm-wt>span{margin-top:1px;font-size:13px;}
.lm .lm-lic,.lm .lm-lface{position:relative;width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;
  background:var(--s1);color:var(--fg);}
.lm .lm-lface .mb-ph,.lm .lm-lface .lm-pini{position:absolute;inset:0;width:100%;height:100%;border-radius:50%;display:grid;place-items:center;}
.lm .lm-lface img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lm-lface .lm-pini b{font:650 13px/1 var(--mb-ui);color:var(--fg2);}

/* Prayer */
.lm .lm-pw{padding:16px;border-radius:18px;background:var(--s1);}
.lm .lm-pwk{display:flex;align-items:center;gap:6px;margin:0;font:750 11px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--acc);}
.lm .lm-pwsay{margin:8px 0 0;font:400 17px/1.45 var(--lm-read,var(--mb-serif));color:var(--fg);text-wrap:pretty;}
.lm .lm-pwi{display:block;}
.lm .lm-pwask{display:flex;align-items:center;gap:8px;margin-top:0;}
.lm .lm-pwask .lm-ic{color:var(--acc);}
.lm .lm-pwi+.lm-pwi{margin-top:10px;}
.lm .lm-pwi b{display:block;font:650 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-pwi>span{display:-webkit-box;margin-top:2px;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lm-pwn{margin:4px 0 0;font:400 13.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm .lm-pw .lm-cpills{margin-top:14px;}
.lm .lm-pw .lm-cpill:not(.pri){background:var(--bg);}

/* Find your people */
.lm .lm-disc{display:grid;grid-template-columns:1fr 1fr;gap:18px 12px;}
.lm .lm-dc{min-width:0;display:flex;flex-direction:column;}
.lm .lm-dcl{display:block;color:var(--fg);text-decoration:none;}
.lm .lm-dimg{position:relative;display:grid;place-items:center;height:112px;border-radius:14px;overflow:hidden;background:var(--lm-mint);color:var(--lm-mint-ink);}
.lm .lm-dimg b{font:italic 500 26px/1 var(--mb-serif);}
.lm .lm-dimg .mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;}
.lm .lm-dc .lm-dcl>b{display:block;margin-top:9px;font:700 15px/1.25 var(--mb-ui);}
.lm .lm-dc .lm-dcl>small{display:-webkit-box;margin:2px 0 10px;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);
  -webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lm-dc form{display:flex;margin-top:auto;}
.lm .lm-cpill.full{height:36px;font-size:13.5px;}

/* a group's page: the cover, Back and More over it */
.lm .lm-gcov{position:relative;height:200px;margin:0 -20px;background:var(--lm-mint);color:var(--lm-mint-ink);overflow:hidden;}
.lm .lm-gcov:not(.has-ph){height:150px;}
.lm .lm-gcov .mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;}
.lm .lm-gcov img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lm-gcov-i{position:absolute;inset:0;display:grid;place-items:center;padding-top:env(safe-area-inset-top,0px);
  font:italic 400 48px/1 var(--mb-serif);opacity:.55;}
.lm .lm-fab{position:absolute;top:calc(10px + env(safe-area-inset-top,0px));z-index:2;width:40px;height:40px;border-radius:50%;
  display:grid;place-items:center;background:rgba(255,255,255,.92);color:#111;box-shadow:0 2px 10px rgba(0,0,0,.12);text-decoration:none;
  cursor:pointer;list-style:none;}
.lm .lm-fab::-webkit-details-marker{display:none;}
.lm .lm-fab.l{left:12px;}
.lm .lm-fab.r{right:12px;}
.lm .lm-gmore{position:static;}
.lm .lm-gmenu{position:absolute;top:calc(56px + env(safe-area-inset-top,0px));right:12px;z-index:3;min-width:200px;padding:6px;border-radius:16px;
  background:var(--bg);box-shadow:0 0 0 1px var(--lm-line),0 12px 32px var(--lm-shadow);}
.lm .lm-gmenu a,.lm .lm-gmenu button{display:block;width:100%;padding:12px 14px;border:0;border-radius:11px;background:none;color:var(--fg);
  font:600 15px/1.2 var(--mb-ui);text-align:left;text-decoration:none;cursor:pointer;}
.lm .lm-gmenu .warn{color:var(--error,#c4162a);}
.lm .lm-gh{padding-top:16px;}
.lm .lm-gname{margin:0;font-family:var(--mb-serif);font-size:31px;line-height:1.1;font-weight:var(--lm-dw,400);letter-spacing:var(--lm-dtr,-.02em);
  color:var(--fg);text-wrap:balance;}
.lm .lm-gsub{display:flex;align-items:center;gap:6px;margin:6px 0 0;font:400 14px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lm-gsub .lm-ic{flex:none;}
.lm .lm-gmem{display:flex;align-items:center;gap:9px;margin:12px 0 0;font:400 13.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-gfaces{display:flex;align-items:center;flex:none;}
.lm .lm-gfaces .gs-av{width:26px;height:26px;margin-left:-3px;font-size:9.5px;letter-spacing:-.02em;box-shadow:0 0 0 2px var(--bg);}
.lm .lm-gfaces .gs-av.has-photo{margin-left:-5px;}
.lm .lm-gfaces .gs-av:first-child{margin-left:0;}
.lm .lm-gbtns{display:flex;gap:8px;margin-top:14px;}
.lm .lm-gbtns>*{flex:1;min-width:0;}
.lm .lm-gbtns .lm-cpill{height:38px;font-size:14px;}
.lm .lm-gtabs{display:flex;gap:24px;margin:16px -20px 0;padding:0 20px;border-bottom:1px solid var(--lm-line);overflow-x:auto;scrollbar-width:none;}
.lm .lm-gtabs::-webkit-scrollbar{display:none;}
.lm .lm-gtabs a{position:relative;display:inline-flex;align-items:center;gap:5px;height:46px;flex:none;color:var(--fg3);
  font:650 14.5px/1 var(--mb-ui);text-decoration:none;border-bottom:2px solid transparent;margin-bottom:-1px;}
.lm .lm-gtabs a[aria-current]{color:var(--fg);border-bottom-color:var(--acc-fill);}
.lm .lm-gtn{display:inline-grid;place-items:center;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:var(--acc-fill);
  color:var(--on-acc);font:700 10px/1 var(--mb-ui);}
.lm .lm-gbody{margin-top:16px;}

/* the next gathering */
.lm .lm-meet{margin-top:0;}
.lm .lm-meetc{display:flex;align-items:center;gap:14px;padding:14px;border-radius:18px;box-shadow:inset 0 0 0 1px var(--lm-line);
  color:var(--fg);text-decoration:none;}
.lm .lm-meetc .lm-wt b{font-size:15.5px;font-weight:700;}
.lm .lm-meetc .lm-wt>span{font-size:13px;}
.lm .lm-gwho{display:flex!important;align-items:center;gap:7px;margin-top:8px!important;color:var(--fg2);}
.lm .lm-meet .lm-cpills{margin-top:10px;}

/* writing to the group */
.lm .lm-gcomp{display:flex;align-items:center;gap:10px;margin:18px -12px 0 0;}
.lm .lm-gme{width:40px;height:40px;flex:none;border-radius:50%;overflow:hidden;display:grid;place-items:center;background:var(--s2);
  color:var(--fg2);font:700 13px/1 var(--mb-ui);}
.lm .lm-gme img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lm-gin{flex:1;min-width:0;height:44px;border-radius:22px;background:var(--s1);display:flex;align-items:center;padding:0 16px;
  color:var(--fg3);font:400 15px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lm-gband{height:8px;margin:16px -20px 0;background:var(--s1);}
/* the group's posts: Home's feed cards (member_lumen_feed), edge to edge under the band */
.lm .lm-gposts{margin:0 -20px;}
.lm .lm-gposts .lf-post .gs-foot,.lm .lm-gposts .lf-post .gs-acts{padding:10px 20px 0;}
.lm .lm-gposts .lf-post .gs-acts{display:flex;gap:8px;flex-wrap:wrap;}
.lm .lm-gposts .lf-txt p{-webkit-line-clamp:12;}
/* a member's post: the composer (member_posts) */
.lm .lm-mpform{margin-top:22px;}
.lm .lm-pme{display:flex;align-items:center;gap:10px;font:650 15px/1.2 var(--mb-ui);color:var(--fg);}
.lm .lm-pset{margin:20px 0 0;padding:0;border:0;min-width:0;}
.lm .lm-pset legend{padding:0;margin-bottom:10px;font:650 12px/1.2 var(--mb-ui);letter-spacing:.08em;text-transform:uppercase;color:var(--fg3);}
.lm .lm-pchips{display:flex;flex-wrap:wrap;gap:8px;}
.lm .lm-pchip{position:relative;display:inline-flex;cursor:pointer;}
.lm .lm-pchip input,.lm .lm-pwhere input{position:absolute;opacity:0;width:1px;height:1px;}
.lm .lm-pchip span{display:inline-flex;align-items:center;min-height:40px;padding:0 16px;border-radius:20px;
  box-shadow:inset 0 0 0 1.5px var(--lm-line);color:var(--fg);font:600 14px/1 var(--mb-ui);}
.lm .lm-pchip input:checked+span{background:var(--lm-tint-10);box-shadow:inset 0 0 0 1.5px var(--acc-fill);color:var(--acc);}
.lm .lm-pchip input:focus-visible+span,.lm .lm-pwhere input:focus-visible+span{outline:2px solid var(--acc);outline-offset:2px;}
.lm .lm-pwheres{display:flex;flex-direction:column;gap:8px;}
.lm .lm-pwhere{position:relative;display:block;cursor:pointer;}
.lm .lm-pwhere span{display:block;padding:12px 14px;border-radius:14px;box-shadow:inset 0 0 0 1.5px var(--lm-line);}
.lm .lm-pwhere b{display:block;font:650 15px/1.25 var(--mb-ui);color:var(--fg);}
.lm .lm-pwhere small{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-pwhere input:checked+span{background:var(--lm-tint-6);box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lm-pbox{display:block;margin-top:20px;}
.lm .lm-pbox textarea{display:block;width:100%;box-sizing:border-box;min-height:132px;padding:14px 16px;border:0;border-radius:16px;
  background:var(--s1);color:var(--fg);font:400 16px/1.45 var(--mb-ui);resize:vertical;}
.lm .lm-pbox textarea:focus{outline:2px solid var(--acc);outline-offset:1px;}
.lm .lm-pphoto{position:relative;display:flex;align-items:center;gap:12px;margin-top:10px;padding:12px 14px;border-radius:14px;
  background:var(--s1);color:var(--fg);cursor:pointer;}
.lm .lm-pphoto b{display:block;font:650 15px/1.25 var(--mb-ui);}
.lm .lm-pphoto small{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-pphoto input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;}
.lm .lm-pguard{display:flex;gap:8px;align-items:flex-start;margin:18px 0 0;font:400 13px/1.45 var(--mb-ui);color:var(--fg2);}
.lm .lm-pguard .lm-ic{flex:none;margin-top:1px;color:var(--acc);}
.lm .lm-mpform>button{margin-top:18px;height:48px;font-size:15.5px;}
.lm .lm-mpform>button[disabled]{opacity:.65;}
.lm .lm-pnote{margin:14px 0 0;padding:12px 14px;border-radius:14px;background:var(--s1);font:400 14px/1.45 var(--mb-ui);color:var(--fg2);}
.lm .lm-pswitch{display:flex;align-items:center;gap:12px;margin:12px 0 0;padding:12px 14px;border-radius:14px;
  box-shadow:inset 0 0 0 1px var(--lm-line);}
.lm .lm-pswitch>span{flex:1;min-width:0;}
.lm .lm-pswitch b{display:block;font:650 14.5px/1.25 var(--mb-ui);}
.lm .lm-pswitch small{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-mpform.js:not(.is-church) .lm-pkinds,.lm .lm-mpform.js.is-church .lm-pcomments,
.lm .lm-mpform.js.is-prayer .lm-pphoto,.lm .lm-mpform.js.is-prayer .lm-pcomments,.lm .lm-mpform.js.is-prayer .lm-pkinds{display:none;}
.lm .lm-gheld{display:flex;gap:8px;align-items:flex-start;margin:12px 20px 0;}
.lm .lm-gpost.is-held{box-shadow:inset 4px 0 0 var(--lm-gold);}
.lm .lm-gtools{padding:10px 16px 0;}
@media (prefers-reduced-motion:reduce){.lm .lm-cpill{transition:none;}.lm .lm-cpill:active{transform:none;}}
""")
