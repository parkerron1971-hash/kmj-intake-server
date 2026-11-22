"""member_lumen_home.py — the top half of the member app's new Home ("Look 4.1",
then "Look 5.1").

LOOK 5.1 (Kevin, 2026-11-20: "this is awesome. much better design. lets build
this including the new still to build!"). Home opens with the moments
(member_lumen_stories), then the greeting (4.1's, unchanged but for the mock's
sizes and "Thursday · November 19"), then:
  - the four doors in one bordered strip: Prayer · Events · Serve · Kids, an
    icon on a soft church-colour tile, the name, and one line from the
    records ("3 new" requests on the member's groups' prayer walls, from the
    unread count Messages already read; "4 this week"; their next date to
    serve, "Sun 9:45"; "Check-in open" while the church's check-in is). With
    nothing to say a door has a quiet line. Serve shows where the church
    schedules volunteers (sunday_serving.on), Kids only to a parent or a
    kids leader (the Kids space: a phone never checks a child in);
  - (Kevin's Home plan, 2026-11-21) the doors' words: Prayer "3 new" else
    "Ask or pray"; Events "2 coming up" (the calendar's upcoming occasions
    and the service when it isn't on the calendar); Serve the next time,
    else what waits, else "3 teams" the member can see; and Give ("Give
    online", while the church takes gifts) as the fourth door, unless Kids
    already is (Give is in the tab bar too). The service is This week's
    first card as a pass (pass_card): a chip on the picture, I'll be there,
    Watch live, Calendar. The sentence names the service's time tomorrow
    and, with no gathering this week to lead with, what's ready to watch
    and the next event a few weeks out (line, _later);
  - This week (week_card, week): horizontal cards, a picture with a date
    leaf, a grey kicker, the title, where, how many are going (a number:
    the new look shows no faces) and the record's own action, in place of
    4.1's single Up next card (pick() now only says what the sentence names);
  - the composer (composer): Share a praise or a prayer (contract 2:
    /my/post, the members' composer, member_posts), and the band before
    the feed.
Also for you moved below the feed, then (Kevin's Home plan, 2026-11-21) left
Home: the feed ends with the church's own cards (member_lumen_feed
.church_cards). What follows is Look 4.1 as first built.

Kevin approved the Look 4.1 Home mock on 2026-11-19 ("build this app"): calm
and confident, warm, with pictures. Restraint is the point (he turned down a
louder version): no gradients, no sky, no countdown, no chips inside
sentences, no coloured card fills, no left borders. The church's colour shows
only on the date leaf, the round icon badges, the small-caps labels, the main
buttons, the count pill and the short rules over the section headings.

From the top:
  - a slim live bar while the church is live (red dot, "Live now · <the
    service>", Join), unless the card under Up next is the live service;
  - the greeting: a thin moon (evening) or sun (morning and day) before the
    date in small capitals; "Good evening, Ana." ("It's Sunday, Ana." on a
    Sunday, "Welcome, Ana." for someone who just told the church it's their
    first time); then one sentence made only of what the church's own records
    say, its key facts in heavier ink (line());
  - "Up next" (a short rule over it, a pill: "3 for you") and one featured
    card: the church's picture for it with the date leaf over its foot, a
    label, the serif title, where, how many are going (a number, never names
    or faces: the new look's rule everywhere), the main button and a quiet
    second one (featured());
  - "Also for you": two picture tiles (since gone from Home).

Which card is featured (pick()): the church live > Sunday's service while
check-in is open > for someone brand new, their first Sunday > the sooner of
their group's next gathering and the next event (a tie goes to the group).
Nothing is made up: a block whose data isn't there is left out.

Every picture is the church's own, through its picture spots
(member_app_photos.choose, member_app_pictures): the gathering's own spot
(group:<id>, event:<name>) or Home's top photo for the service; the
devotional's cover; "prayer" (a spot the new look adds). With no picture a
spot draws its default art (the mock's band of faces would show who's going,
and the new look shows no faces). In edit mode (/my?edit=pictures) every
picture carries the frosted Change button, as today's Home does.

The CSS (CSS) joins the Lumen sheet through member_lumen_ui.templates(),
every rule under body.lm, and draws on the look's dark switch too
(body.lm-dark, a member's Dark: member_lumen_look; checked on black).
Every move waits for the phone's yes to motion. Pure functions, no I/O.
"""
from __future__ import annotations

from datetime import date, datetime, time
from html import escape
from string import Template
from typing import Any, Dict, List, Optional, Tuple

from member_lumen_ui import dark as _dark

# The glyphs before the date: the mock's thin-line moon and sun.
MOON = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>')
SUN = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="3.6"/>'
       '<path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6'
       'M7.2 16.8l-1.6 1.6"/></svg>')
# Words in an occasion's name that make it the church's service.
SERVICE_WORDS = ("worship", "service", "sunday", "mass")


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


# ─── clocks and words ────────────────────────────────────────────────


def hm(t: time) -> str:
    """'7' or '7:30': a time in a sentence."""
    h = t.hour % 12 or 12
    return f"{h}" if t.minute == 0 else f"{h}:{t.minute:02d}"


def clock(t: time) -> str:
    """'7:00 PM'."""
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def leaf_time(t: Optional[time]) -> str:
    """The leaf's foot: '7 PM', '10:30' (no room for AM and PM)."""
    if not t:
        return ""
    return f"{t.hour % 12 or 12} {'AM' if t.hour < 12 else 'PM'}" if t.minute == 0 else f"{t.hour % 12 or 12}:{t.minute:02d}"


def parse_hm(v: Any) -> Optional[time]:
    try:
        return time.fromisoformat(str(v)[:5]) if v else None
    except ValueError:
        return None


def when(d: date, t: Optional[time], now: datetime) -> Tuple[str, str]:
    """(the card's label, the sentence's words) for a day and time:
    ("Tonight · 7:00 PM", "tonight at 7"), ("This Thursday · 7:00 PM",
    "Thursday at 7"), ("Saturday, November 28", "on Saturday, November 28")."""
    n = (d - now.date()).days
    at = f" at {hm(t)}" if t else ""
    if n <= 0:
        evening = bool(t) and t >= time(17, 0)
        word = "Tonight" if evening else "Today"
        words = word.lower() + at
    elif n == 1:
        word, words = "Tomorrow", "tomorrow" + at
    elif n < 7:
        word, words = f"This {d:%A}", f"{d:%A}" + at
    else:
        word = f"{d:%A}, {d:%B} {d.day}"
        words = f"on {word}" + at
    return word + (f" · {clock(t)}" if t else ""), words


def hello(first: str, now: datetime, *, new: bool) -> str:
    """The greeting, by the church's clock: 'Good evening, <em>Ana.</em>'."""
    if new:
        lead = "Welcome"
    elif now.weekday() == 6:
        lead = "It's Sunday"
    else:
        lead = "Good morning" if now.hour < 12 else ("Good afternoon" if now.hour < 17 else "Good evening")
    return f"{_e(lead)}, <em>{_e(first)}.</em>" if first else f"{_e(lead)}."


def greeting(first: str, now: datetime, parts: List[Tuple[str, bool]], *, new: bool) -> str:
    """The top of Home: the glyph and the date, the greeting, the sentence."""
    glyph = SUN if 5 <= now.hour < 17 else MOON
    line = "".join(f"<b>{_e(t)}</b>" if bold else _e(t) for t, bold in parts)
    return (f'<header class="lm-brief"><p class="lm-ey4">{glyph}<time datetime="{now.date().isoformat()}">'
            f'{now:%A} · {now:%B} {now.day}</time></p>'
            f'<h1 class="lm-disp lm-hi4">{hello(first, now, new=new)}</h1>'
            f'{f"<p class=lm-line4>{line}</p>" if line else ""}</header>')


# ─── what's next, from the records ───────────────────────────────────


def service_next(ck: Optional[Dict[str, Any]], serving: Optional[Dict[str, Any]],
                 occasions: Optional[List[Dict[str, Any]]], now: datetime) -> Optional[Dict[str, Any]]:
    """The church's next service: {day, time, title, where}, or None.
    Where its time comes from, first found: the check-in settings (the
    service day and start time the office set, church_checkin), Planning's
    schedule (worship_services, through My serving: only someone on a team
    reads it), an occasion on the calendar named for the service."""
    def named(d: date) -> Optional[Dict[str, Any]]:
        # The calendar's own entry for that day's service, for its name and room.
        return next((o for o in occasions or [] if _day(o.get("date")) == d
                     and any(x in str(o.get("title") or "").lower() for x in SERVICE_WORDS)), None)
    w = (ck or {}).get("w") if (ck or {}).get("state") in ("open", "closed") else None
    if w and w.get("day") and w.get("start"):
        o = named(w["day"]) or {}
        title = (((ck or {}).get("occasion") or {}).get("title") or ((ck or {}).get("settings") or {}).get("title")
                 or o.get("title") or "")
        return {"day": w["day"], "time": w["start"].time(), "title": title, "where": o.get("location") or "",
                "entry_id": o.get("entry_id") or "", "from": "checkin"}
    at = (serving or {}).get("next_at")
    if isinstance(at, datetime) and at.date() >= now.date():
        o = named(at.date()) or {}
        return {"day": at.date(), "time": at.time(), "title": o.get("title") or "", "where": o.get("location") or "",
                "entry_id": o.get("entry_id") or "", "from": "planning"}
    for o in occasions or []:
        d = _day(o.get("date"))
        if d and d.weekday() == 6 and 0 <= (d - now.date()).days < 7 and o is named(d):
            return {"day": d, "time": parse_hm(o.get("time")), "title": str(o.get("title") or ""),
                    "where": o.get("location") or "", "entry_id": o.get("entry_id") or "", "from": "calendar"}
    return None


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def serving_on(serving: Optional[Dict[str, Any]], day: date) -> Optional[Dict[str, Any]]:
    """The member's place on the schedule that day (said yes), or None."""
    for c in (serving or {}).get("coming") or []:
        if str((c.get("service") or {}).get("day") or "") == day.isoformat():
            return c
    return None


def first_sunday(told: Optional[Dict[str, Any]], service: Optional[Dict[str, Any]],
                 now: datetime) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """(brand new, their first Sunday). Brand new: they told the church it's
    their first time (member_im_new) and their first service since hasn't
    passed. Their first Sunday: the church's next service, when it's the
    first on or after the day they told us. Without a known service, brand
    new for the week after they told us, with no first Sunday."""
    if not told or not told.get("at") or not told.get("first_time"):
        return False, None
    try:
        at = datetime.fromisoformat(str(told["at"]).replace("Z", "+00:00"))
        said = at.astimezone(now.tzinfo).date() if at.tzinfo and now.tzinfo else at.date()
    except ValueError:
        return False, None
    if service and said <= service["day"] and (service["day"] - said).days < 7 and service["day"] >= now.date():
        return True, service
    return (0 <= (now.date() - said).days < 7), None


def pick(*, live: Optional[Dict[str, Any]], ck: Optional[Dict[str, Any]], gnext: Optional[Dict[str, Any]],
         occasions: Optional[List[Dict[str, Any]]], first: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Which card Up next features: {"kind": live | service | first | group |
    event | welcome, ...}. Live wins, unless check-in is open (then the slim
    bar carries Join and the card carries check-in)."""
    ck_open = (ck or {}).get("state") == "open"
    if live and not ck_open:
        return {"kind": "live"}
    if ck_open:
        return {"kind": "service"}
    if first:
        return {"kind": "first", "service": first}
    o = next((x for x in occasions or [] if _day(x.get("date")) and _day(x.get("date")) >= now.date()), None)
    if gnext and o:
        g_at = (gnext["day"], gnext.get("time") or time(23, 59))
        o_at = (_day(o["date"]), parse_hm(o.get("time")) or time(23, 59))
        return {"kind": "group", "g": gnext} if g_at <= o_at else {"kind": "event", "o": o}
    if gnext:
        return {"kind": "group", "g": gnext}
    if o:
        return {"kind": "event", "o": o}
    return {"kind": "welcome"}


def line(choice: Dict[str, Any], *, service: Optional[Dict[str, Any]], serving: Optional[Dict[str, Any]],
         new: bool, first: Optional[Dict[str, Any]], now: datetime, message: Optional[Dict[str, Any]] = None,
         occasions: Optional[List[Dict[str, Any]]] = None) -> List[Tuple[str, bool]]:
    """The greeting's sentence, as (words, heavier ink) parts. Only what the
    records say: the gathering it features and when, the church's next
    service (and its time, tomorrow), where the member serves and when to be
    there. With no gathering this week to lead with (Kevin's Home plan,
    2026-11-21: "Sunday is tomorrow at 11:00. Last week's message is ready to
    watch, and Oh Give Thanks is two weeks out."), what's ready to watch
    (`message`: the newest message while it's new, member_feed_more
    .message_of) and the church's next event a week to three weeks out
    (`occasions`, never a service)."""
    today = now.date()
    if new:
        parts: List[Tuple[str, bool]] = [("We're so glad you found us.", False)]
        if first:
            words = ("today" if first["day"] == today else f"{first['day']:%A}") + (
                f" at {hm(first['time'])}" if first.get("time") else "")
            parts += [(" Your first Sunday is ", False), (words, True), (".", False)]
        return parts
    parts = []

    def serve_words(c: Dict[str, Any]) -> str:
        t = parse_hm(c.get("call_time"))
        return f"on {c.get('team') or 'your team'}" + (f" at {hm(t)}" if t else "")

    if service and service["day"] == today:
        t = service.get("time")
        if t and now.time() < t:
            parts += [("Service starts at ", False), (hm(t), True), (".", False)]
        c = serving_on(serving, today)
        if c:
            parts += [(" You're " if parts else "You're ", False), (serve_words(c), True), (".", False)]
        return parts
    lead = None
    if choice.get("kind") in ("group", "event"):
        if choice["kind"] == "group":
            g = choice["g"]
            title, d, t = g["group"].get("name") or "", g["day"], g.get("time")
            where = g["group"].get("location") or ""
        else:
            o = choice["o"]
            title, d, t, where = o.get("title") or "", _day(o["date"]), parse_hm(o.get("time")), o.get("location") or ""
        if d and (d - today).days < 7 and title:
            lead = d
            started = d == today and t is not None and now.time() >= t
            words = f"started at {hm(t)}" if started else when(d, t, now)[1]
            parts += [(f"{title} {'' if started else 'is '}".replace("  ", " "), False), (words, True),
                      (f" at {where}." if where else ".", False)]
    said_serving = False
    if service and 0 < (service["day"] - today).days < 7 and service["day"] != lead:
        n = (service["day"] - today).days
        name = "Sunday" if service["day"].weekday() == 6 else f"{service['day']:%A}'s service"
        st = service.get("time")
        soon = ("tomorrow" + (f" at {hm(st)}" if st else "")) if n == 1 else f"in {n} days"
        c = serving_on(serving, service["day"])
        gap = " " if parts else ""
        if c:
            parts += [(f"{gap}{name} is ", False), (soon, True), (", and you're ", False), (serve_words(c), True),
                      (".", False)]
            said_serving = True
        else:
            parts += [(f"{gap}{name} is ", False), (soon, True), (".", False)]
    if not said_serving:
        for c in (serving or {}).get("coming") or []:
            d = _day((c.get("service") or {}).get("day"))
            if d and 0 < (d - today).days < 7 and (not service or d != service["day"]):
                parts += [(f"{' ' if parts else ''}On {d:%A} you're ", False), (serve_words(c), True), (".", False)]
                break
    if lead is None:
        parts += _later(today, message, occasions, service, gap=bool(parts))
    return parts


def _later(today: date, message: Optional[Dict[str, Any]], occasions: Optional[List[Dict[str, Any]]],
           service: Optional[Dict[str, Any]], *, gap: bool) -> List[Tuple[str, bool]]:
    """"Last week's message is ready to watch, and Oh Give Thanks is two
    weeks out.": the newest message while it's new, the next event a week to
    three weeks out (not a service, not the service's own entry)."""
    bits: List[List[Tuple[str, bool]]] = []
    d = _day((message or {}).get("preached_on"))
    if message and d and 0 <= (today - d).days <= 7:
        k = (today - d).days
        whose = ("Today's" if k == 0 else "Yesterday's" if k == 1 else "Last week's" if d.weekday() == 6
                 else f"{d:%A}'s")
        bits.append([(f"{whose} message is ", False), ("ready to watch", True)])
    skip = str((service or {}).get("entry_id") or "")
    for o in occasions or []:
        od, title = _day(o.get("date")), " ".join(str(o.get("title") or "").split())
        if not od or not title or (skip and str(o.get("entry_id") or "") == skip):
            continue
        if any(x in title.lower() for x in SERVICE_WORDS):
            continue
        n = (od - today).days
        if n < 7:
            continue
        if n <= 24:
            out_words = {1: "a week out", 2: "two weeks out"}.get(round(n / 7), "three weeks out")
            bits.append([(f"{title} is ", False), (out_words, True)])
        break
    out: List[Tuple[str, bool]] = []
    for i, b in enumerate(bits):
        words, bold = b[0]
        if i == 0:
            words = (" " if gap else "") + words
        else:
            out.append((", and ", False))
        out += [(words, bold)] + b[1:]
    if out:
        out.append((".", False))
    return out


# ─── the featured card ───────────────────────────────────────────────


def going(n: int, mine: bool) -> str:
    """How many are going: a number, never names or faces (the new look's
    rule), and only from two."""
    import member_lumen_ui as lm
    if n < 2:
        return ""
    label = _e(f"You and {n - 1} other{'' if n == 2 else 's'}") if mine else f"<b>{int(n)}</b> going"
    return f'<span class="lm-wkn">{lm.ic("people", 17)}<span>{label}</span></span>'


def said_no() -> str:
    return '<span class="lm-wkn">You said you can&#x27;t make it</span>'


def done(words: str, cls: str = "lm-wkb") -> str:
    """An answer already given, in place of its button: a check and the words."""
    import member_app_ui as ui
    return f'<span class="{cls} on">{ui.icon("check", 15)}{_e(words)}</span>'


def post_button(action: str, fields: Any, label: str, cls: str = "lm-wkb") -> str:
    """One of today's forms as a single button (its route keeps its own
    checks: the member's session, same site, its limit). `fields`: a dict,
    or (name, value) pairs when a name repeats. `label` escaped."""
    pairs = fields.items() if isinstance(fields, dict) else fields
    hidden = "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">' for k, v in pairs)
    quiet = ' class="q"' if "q" in cls.split() else ""
    return (f'<form method="post" action="{_e(action)}"{quiet}>{hidden}<button class="{cls}" type="submit">{_e(label)}'
            f'</button></form>')


def link_button(href: str, label: str, cls: str = "lm-wkb") -> str:
    return f'<a class="{cls}" href="{_e(href)}">{_e(label)}</a>'


# ─── Look 5.1: the doors, This week, the composer ────────────────────


def door(href: str, icon_name: str, label: str, line: str, *, new: bool = False) -> str:
    """One of the four doors: its icon on a soft tile, the name, and a line
    of status from the records (in the church's colour when it's new)."""
    import member_lumen_ui as lm
    return (f'<a class="lm-door" href="{_e(href)}"><span class="lm-di" aria-hidden="true">{lm.ic(icon_name, 21)}</span>'
            f'<b>{_e(label)}</b><small{" class=new" if new else ""}>{_e(line)}</small></a>')


def doors(items: List[str]) -> str:
    items = [x for x in items if x]
    if not items:
        return ""
    return f'<nav class="lm-doors" aria-label="Shortcuts" style="--n:{len(items)}">{"".join(items)}</nav>'


def week_card(pic: str, *, href: str, day: date, kicker: str, title: str, place: str = "", count: str = "",
              action: str = "", note: str = "", pin: str = "") -> str:
    """One card of This week: the picture with the date leaf, the kicker,
    the title (the card's link), where, how many are going (a number) and
    the record's own action. `pic`, `kicker`, `count`, `action`, `note` and
    `pin` are trusted markup; the title and place are escaped."""
    return (f'<article class="lm-wk"><span class="lm-wkp"><span class="lm-wka">{pic}</span>'
            f'<span class="lm-wkl" aria-hidden="true"><small>{day:%a}</small><b>{day.day}</b></span>{pin}</span>'
            f'<div class="lm-wkbd"><p class="lm-wkk">{kicker}</p><h3 class="lm-wkt"><a href="{_e(href)}">{_e(title)}</a></h3>'
            f'{f"<p class=lm-wkm>{_e(place)}</p>" if place else ""}'
            f'{f"<div class=lm-wkf>{count}{action}</div>" if count or action else ""}'
            f'{f"<p class=lm-wknote>{note}</p>" if note else ""}</div></article>')


def icon_link(href: str, icon_name: str, label: str, cls: str = "lm-wkb o", *, download: bool = False,
              aria: str = "") -> str:
    """A quiet outlined button that is a link, its icon before the words
    (the pass's Watch live and Calendar)."""
    import member_lumen_ui as lm
    extra = (" download" if download else "") + (f' aria-label="{_e(aria)}"' if aria else "")
    return f'<a class="{_e(cls)}" href="{_e(href)}"{extra}>{lm.ic(icon_name, 15)}{_e(label)}</a>'


def pass_card(pic: str, *, href: str, day: date, chip: str, kicker: str, title: str, place: str = "",
              count: str = "", buttons: Tuple[str, ...] = (), note: str = "", pin: str = "") -> str:
    """The service as This week's first card, a pass (Kevin's Home plan,
    2026-11-21): week_card's picture and date leaf with a chip on the
    picture ("Today", "Tomorrow", the weekday), the kicker, the title, where
    (or that it can be watched live), how many are going, and its buttons in
    a row that wraps: the record's own answer (I'll be there, check-in on
    the day), Watch live, Calendar. `pic`, `kicker`, `count`, `buttons`,
    `note` and `pin` are trusted markup; the chip, title and place are
    escaped."""
    btns = "".join(b for b in buttons if b)
    chip_html = f'<span class="lm-chip" aria-hidden="true">{_e(chip)}</span>' if chip else ""
    place_html = f'<p class="lm-wkm">{_e(place)}</p>' if place else ""
    count_html = f'<div class="lm-wkg">{count}</div>' if count else ""
    btn_html = f'<div class="lm-wkf lm-wkf3">{btns}</div>' if btns else ""
    note_html = f'<p class="lm-wknote">{note}</p>' if note else ""
    return (f'<article class="lm-wk lm-pass"><span class="lm-wkp"><span class="lm-wka">{pic}</span>'
            f'<span class="lm-wkl" aria-hidden="true"><small>{day:%a}</small><b>{day.day}</b></span>{chip_html}{pin}</span>'
            f'<div class="lm-wkbd"><p class="lm-wkk">{kicker}</p><h3 class="lm-wkt"><a href="{_e(href)}">{_e(title)}</a></h3>'
            f'{place_html}{count_html}{btn_html}{note_html}</div></article>')


def week(cards: List[str]) -> str:
    """This week: the cards side by side, See all to Events."""
    cards = [c for c in cards if c]
    if not cards:
        return ""
    return (f'<section class="lm-wk5" aria-labelledby="lm-wk-h"><div class="lm-sh5"><h2 id="lm-wk-h">This week</h2>'
            f'<a href="/my/events">See all</a></div><div class="lm-wks">{"".join(cards)}</div></section>')


def composer(face: str) -> str:
    """Share a praise or a prayer (contract 2: the members' composer,
    /my/post, member_posts), the member's own circle beside it, then the band
    before the feed. `face` is trusted markup."""
    import member_lumen_ui as lm
    return (f'<div class="lm-hcp"><span class="lm-hcpav" aria-hidden="true">{face}</span>'
            f'<a class="lm-hcpin" href="/my/post">Share a praise or a prayer…</a>'
            f'<a class="lm-icb" href="/my/post" aria-label="Share a photo">{lm.ic("image", 22)}</a></div>'
            f'<div class="lm-band" aria-hidden="true"></div>')


def _came(iso: str, now: datetime) -> str:
    """'today', 'yesterday', 'on Thursday', 'on November 12': when it came in."""
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    d = at.astimezone(now.tzinfo).date() if at.tzinfo and now.tzinfo else at.date()
    n = (now.date() - d).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    return f"on {d:%A}" if n < 7 else f"on {d:%B} {d.day}"


def desk(counts: Optional[Dict[str, Any]], *, church: str, short: str, office: str, now: datetime,
         first_news: bool = False, quiet: bool = False) -> str:
    """The owner's desk strip (Kevin's Home plan, 2026-11-21), after This week:
    good news members shared that waits to be posted, members' group posts
    and comments the check held (Review, in the office's News room:
    `office`), and, at a church with no news yet, Post the church's first
    news (/my/news/write). `counts` from member_portal_lumen.desk_counts
    (None when it couldn't be read: no rows at all, not even the first news,
    which the feed keeps then); `quiet` no news reaches Home yet. A count
    that reached the read's window says "60+". '' with nothing waiting."""
    if counts is None:
        return ""
    rows = []
    c = counts
    good = int(c.get("good") or 0)
    if good:
        came = _came(c.get("good_at") or "", now)
        when = ((f"It came in {came}." if good == 1 else f"The newest came in {came}.") if came else "")
        nudge = (f"Approve {'it' if good == 1 else 'them'} and {short}'s feed begins." if quiet else
                 f"Approve {'it' if good == 1 else 'them'} to post {'it' if good == 1 else 'them'}.")
        title = (f"{good}+ good news posts are waiting" if c.get("good_more") else
                 f"{good} good news post{' is' if good == 1 else 's are'} waiting")
        rows.append((title, " ".join(x for x in (when, nudge) if x), office, "Review"))
    hc, hp = int(c.get("held_comments") or 0), int(c.get("held_posts") or 0)
    if hc or hp:
        bits = [f"{n} {word}{'' if n == 1 else 's'}" for n, word in ((hc, "comment"), (hp, "post")) if n]
        title = (" and ".join(bits) + (" is held" if hc + hp == 1 else " are held") if not c.get("held_more")
                 else f"{hc + hp}+ comments and posts are held")
        rows.append((title, "The check held " + ("it" if hc + hp == 1 else "them") + " for a safety officer to read.",
                     office, "Review"))
    if first_news and not good:
        rows.append(("Post the church's first news", f"Everyone at {church} sees it here, on Home.", "/my/news/write",
                     "Post"))
    if not rows:
        return ""
    out = []
    for i, (title, line, href, btn) in enumerate(rows):
        line = line + (" Only you see this." if i == 0 else "")
        out.append(f'<div class="lm-dk"><div class="lm-dkt"><b>{_e(title)}</b><p>{_e(line.strip())}</p></div>'
                   f'<a class="lm-dkb" href="{_e(href)}">{_e(btn)}</a></div>')
    return (f'<section class="lm-desk" aria-labelledby="lm-desk-h"><h2 class="mp-sr" id="lm-desk-h">Waiting for you</h2>'
            f'{"".join(out)}</section>')


def live_bar(live: Dict[str, Any]) -> str:
    title = (live or {}).get("title") or ""
    return (f'<a class="lm-lv4" href="/my/live"><i aria-hidden="true"></i>'
            f'<span>Live now{f" · {_e(title)}" if title else ""}</span><b>Join</b></a>')


# ─── the sheet ───────────────────────────────────────────────────────
# Accent level 2's tokens (member_lumen_ui): --acc reads as words on the page,
# --acc-fill is a button's colour with --on-acc on it, --lm-tint-12 the soft
# church-colour surface. The card's 4% church tint is a color-mix over the
# page; a browser without it gets the plain page colour.
CSS = Template("""
/* Home, Look 5.1 (member_lumen_home): the greeting, the doors, This week, the composer */
.lm-brief{margin:18px 0 0;}
.lm-ey4{margin:0;display:flex;align-items:center;gap:6px;font:700 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm-ey4 svg{width:15px;height:15px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
body.lm .lm-brief .lm-hi4{margin-top:10px;font-size:30px;line-height:1.12;letter-spacing:-.02em;}
.lm-line4{margin:8px 0 0;max-width:350px;font:400 15px/1.45 var(--mb-ui);color:var(--fg2);text-wrap:pretty;}
.lm-line4 b{font-weight:650;color:var(--fg);}
.lm-lv4{display:flex;align-items:center;gap:10px;height:44px;margin:14px 0 0;padding:0 6px 0 14px;border-radius:14px;background:var(--s1);
  color:var(--fg);font:600 13.5px/1 var(--mb-ui);text-decoration:none;}
.lm-lv4 i{width:8px;height:8px;flex:none;border-radius:50%;background:var(--lm-live);}
.lm-lv4 span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm-lv4 b{height:32px;padding:0 14px;border-radius:16px;background:var(--fg);color:var(--bg);display:inline-flex;align-items:center;font-weight:650;}
/* the four doors: Prayer · Events · Serve · Kids, each with its line from the records */
.lm-doors{display:grid;grid-template-columns:repeat(var(--n,4),minmax(0,1fr));margin:18px 0 0;border:1px solid var(--lm-line);
  border-radius:20px;overflow:hidden;background:var(--bg);}
.lm-door{position:relative;min-width:0;display:flex;flex-direction:column;align-items:center;padding:14px 2px 13px;color:var(--fg);
  text-decoration:none;-webkit-tap-highlight-color:transparent;}
.lm-door+.lm-door::before{content:"";position:absolute;left:0;top:18px;bottom:18px;width:1px;background:var(--lm-line);}
.lm-di{width:40px;height:40px;margin-bottom:9px;border-radius:13px;display:grid;place-items:center;background:var(--lm-tint-12);color:var(--acc);}
.lm-di svg{width:21px;height:21px;stroke-width:1.9;}
.lm-door b{font:700 13.5px/1.2 var(--mb-ui);}
.lm-door small{max-width:100%;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:400 11.5px/1.3 var(--mb-ui);
  color:var(--fg3);}
.lm-door small.new{color:var(--acc);font-weight:700;}
/* This week: horizontal cards, a picture with its date leaf, the record's own action */
.lm-sh5{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:28px 0 12px;}
.lm-sh5 h2{margin:0;font:750 18px/1.2 var(--mb-ui);letter-spacing:-.012em;color:var(--fg);}
.lm-sh5 a{padding:6px 0;font:650 14px/1 var(--mb-ui);color:var(--acc);text-decoration:none;}
.lm-wks{display:flex;gap:12px;margin:0 -20px;padding:0 20px 2px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding-inline:20px;
  scrollbar-width:none;}
.lm-wks::-webkit-scrollbar{display:none;}
.lm-wk{position:relative;flex:none;width:264px;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--lm-line);
  border-radius:18px;background:var(--bg);scroll-snap-align:start;}
.lm-wks>.lm-wk:only-child{width:100%;}
.lm-wkp{position:relative;display:block;height:124px;background:var(--s2);}
.lm-wka{position:absolute;inset:0;overflow:hidden;}
.lm-wka>*{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-wka img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-wkl{position:absolute;left:12px;top:12px;z-index:2;width:46px;padding:6px 0 7px;border-radius:12px;background:var(--bg);text-align:center;
  box-shadow:0 2px 10px rgba(0,0,0,.14);}
.lm-wkl small{display:block;font:750 10px/1 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--acc);}
.lm-wkl b{display:block;margin-top:3px;font:500 21px/1.05 var(--mb-serif);color:var(--fg);}
.lm-wkbd{flex:1;display:flex;flex-direction:column;padding:12px 14px 14px;}
.lm-wkk{margin:0;font:750 11px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--fg2);}
.lm-wkt{margin:7px 0 2px;font:650 17px/1.25 var(--mb-ui);letter-spacing:-.01em;}
.lm-wkt a{color:var(--fg);text-decoration:none;}
.lm-wkt a::after{content:"";position:absolute;inset:0;z-index:1;}
.lm-wkm{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:400 13.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm-wkf{display:flex;align-items:center;gap:8px;min-height:38px;margin-top:auto;padding-top:12px;}
.lm-wkf>*,.lm-wknote{position:relative;z-index:2;}
.lm-wkn{min-width:0;display:inline-flex;align-items:center;gap:6px;overflow:hidden;white-space:nowrap;font:400 13px/1.2 var(--mb-ui);color:var(--fg2);}
.lm-wkn svg{width:17px;height:17px;flex:none;color:var(--fg3);}
.lm-wkn b{font-weight:650;color:var(--fg);}
.lm-wkb{height:34px;padding:0 14px;border:0;border-radius:17px;display:inline-flex;align-items:center;gap:6px;background:var(--acc-fill);
  color:var(--on-acc);font:650 13.5px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;cursor:pointer;}
.lm-wkb.on{background:var(--lm-tint-12);color:var(--acc);}
.lm-wkb.q{padding:0 6px;background:none;color:var(--fg2);}
.lm-wkb svg{width:15px;height:15px;}
.lm-wkf>.lm-wkb:not(.q),.lm-wkf>form:not(.q){margin-left:auto;}
.lm-wknote{margin:8px 0 0;font:500 12px/1.4 var(--mb-ui);color:var(--fg2);}
.lm-wknote a{color:var(--acc);font-weight:650;text-decoration:none;}
.lm-wkp .mb-pin{z-index:3;top:auto;bottom:10px;right:10px;height:28px;padding:0 11px;font-size:12px;background:rgba(20,18,16,.55);box-shadow:none;}
.lm-wkp .mb-pin svg{display:none;}
.lm-wk5+.lm-ck{margin-top:16px;}
/* the service as a pass (Kevin's Home plan): a chip on the picture, its buttons in a row that wraps */
.lm-chip{position:absolute;right:12px;top:12px;z-index:2;height:26px;padding:0 11px;border-radius:13px;display:inline-flex;
  align-items:center;background:rgba(20,18,16,.62);color:#fff;font:650 12px/1 var(--mb-ui);letter-spacing:.01em;}
.lm-wkg{position:relative;z-index:2;margin-top:10px;}
.lm-wkf3{flex-wrap:wrap;gap:8px;}
.lm-wkf3>.lm-wkb:not(.q),.lm-wkf3>form:not(.q){margin-left:0;}
.lm-wkb.o{background:none;color:var(--fg);box-shadow:inset 0 0 0 1px var(--lm-line);}
.lm-wkb.o svg{color:var(--fg2);}
/* the owner's desk strip (Kevin's Home plan): what waits in the office's News room, the church's first news */
.lm-desk{margin:22px 0 0;border-radius:18px;background:var(--lm-tint-12);overflow:hidden;}
.lm-dk{display:flex;align-items:center;gap:12px;padding:14px 14px 14px 16px;}
.lm-dk+.lm-dk{border-top:1px solid var(--lm-line);}
.lm-dkt{flex:1;min-width:0;}
.lm-dkt b{display:block;font:700 14.5px/1.3 var(--mb-ui);color:var(--fg);}
.lm-dkt p{margin:3px 0 0;font:400 13px/1.4 var(--mb-ui);color:var(--fg2);text-wrap:pretty;}
.lm-dkb{flex:none;height:34px;padding:0 16px;border-radius:17px;display:inline-flex;align-items:center;background:var(--bg);
  color:var(--fg);font:650 13.5px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;}
.lm-dkb:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
/* the composer, then the band before the feed */
.lm-hcp{display:flex;align-items:center;gap:10px;margin:22px -10px 0 0;padding:0 0 16px;}
.lm-hcpav{position:relative;width:40px;height:40px;flex:none;border-radius:50%;overflow:hidden;display:grid;place-items:center;
  background:var(--s2);color:var(--fg2);font:700 13px/1 var(--mb-ui);}
.lm-hcpav img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-hcpin{flex:1;min-width:0;height:44px;display:flex;align-items:center;padding:0 16px;overflow:hidden;border-radius:22px;background:var(--s1);
  color:var(--fg3);font:400 15px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;text-overflow:ellipsis;}
.lm-band{height:8px;margin:0 -20px;background:var(--s1);}
@media (prefers-reduced-motion:no-preference){
  .lm-lv4,.lm-wk,.lm-door{transition:transform .2s ease-out;}
  .lm-lv4:active,.lm-wk:active,.lm-door:active{transform:scale(.98);}
}
.lm-lv4:focus-visible,.lm-hcpin:focus-visible,.lm-sh5 a:focus-visible,.lm-wkb:focus-visible
{outline:2px solid var(--acc);outline-offset:3px;border-radius:12px;}
.lm-door:focus-visible{outline:2px solid var(--acc);outline-offset:-3px;border-radius:18px;}
.lm-wkt a:focus-visible{outline:none;}
.lm-wkt a:focus-visible::after{outline:2px solid var(--acc);outline-offset:-2px;border-radius:18px;}
/* the dark look (member_lumen_look; its colours are member_lumen_ui.DARK_TOKENS): the date leaf on a raised surface */
""" + _dark("""
body.lm.lm-dark .lm-wkl{background:var(--s2);box-shadow:0 2px 10px rgba(0,0,0,.4);}
body.lm.lm-dark .lm-dkb{background:var(--fg);color:var(--bg);}
"""))
