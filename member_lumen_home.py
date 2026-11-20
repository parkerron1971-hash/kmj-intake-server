"""member_lumen_home.py — the top half of the member app's new Home ("Look 4.1").

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
  - "Also for you": two picture tiles, each with a round icon badge, a label,
    a title and one line (tiles()).

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
(body.lm-dark: checked on black; the new look itself is still always white).
Every move waits for the phone's yes to motion. Pure functions, no I/O.
"""
from __future__ import annotations

from datetime import date, datetime, time
from html import escape
from string import Template
from typing import Any, Dict, List, Optional, Tuple

# The glyphs before the date: the mock's thin-line moon and sun.
MOON = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>')
SUN = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="3.6"/>'
       '<path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6'
       'M7.2 16.8l-1.6 1.6"/></svg>')
# The tiles' badge icons the look doesn't have yet (member_lumen_ui.ICONS has the rest).
WAVE = ('<path d="M7 11V6a1.5 1.5 0 0 1 3 0v4M10 10V4.5a1.5 1.5 0 0 1 3 0V10M13 10V5.5a1.5 1.5 0 0 1 3 0V12'
        'M16 9.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-2.7L4.3 15a1.5 1.5 0 0 1 2.5-1.7L7 13.6"/>')

# Words in an occasion's name that make it the church's service.
SERVICE_WORDS = ("worship", "service", "sunday", "mass")


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def icon(name: str, size: int = 15) -> str:
    import member_lumen_ui as lm
    if name == "wave":
        return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
                f'{WAVE}</svg>')
    return lm.ic(name, size)


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
            f'{now:%A}, {now:%B} {now.day}</time></p>'
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
         new: bool, first: Optional[Dict[str, Any]], now: datetime) -> List[Tuple[str, bool]]:
    """The greeting's sentence, as (words, heavier ink) parts. Only what the
    records say: the gathering it features and when, the church's next
    service, where the member serves and when to be there."""
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
        soon = "tomorrow" if n == 1 else f"in {n} days"
        c = serving_on(serving, service["day"])
        gap = " " if parts else ""
        if c:
            parts += [(f"{gap}{name} is {soon}, and you're ", False), (serve_words(c), True), (".", False)]
            said_serving = True
        else:
            parts += [(f"{gap}{name} is {soon}.", False)]
    if not said_serving:
        for c in (serving or {}).get("coming") or []:
            d = _day((c.get("service") or {}).get("day"))
            if d and 0 < (d - today).days < 7 and (not service or d != service["day"]):
                parts += [(f"{' ' if parts else ''}On {d:%A} you're ", False), (serve_words(c), True), (".", False)]
                break
    return parts


# ─── the featured card ───────────────────────────────────────────────


def leaf(d: date, foot: str) -> str:
    return (f'<span class="lm-leaf4" aria-hidden="true"><small>{d:%a}</small><b>{d.day}</b>'
            f'{f"<small>{_e(foot)}</small>" if foot else ""}</span>')


def going(n: int, mine: bool) -> str:
    """How many are going: a number, never names or faces, and only from two."""
    import member_lumen_ui as lm
    if n < 2:
        return ""
    label = _e(f"You and {n - 1} other{'' if n == 2 else 's'}") if mine else f"<b>{int(n)}</b> going"
    return f'<span class="lm-f4n">{lm.ic("people", 18)}<span>{label}</span></span>'


def done_pill(words: str, about: str = "") -> str:
    import member_app_ui as ui
    return f'<span class="lm-btn sm done4"{about}>{ui.icon("check", 16)}{_e(words)}</span>'


def card(pic: str, *, day: Optional[date], foot: str, kicker: str, title: str, meta: str = "", row: str = "",
         pin: str = "", after: str = "", note: str = "") -> str:
    """One featured card. `pic`, `kicker`, `row`, `pin` and `after` are
    trusted markup; the title, meta and note are escaped here."""
    lf = leaf(day, foot) if day else ""
    return (f'<section class="lm-f4" aria-labelledby="lm-f4-t"><span class="lm-f4p"><span class="lm-f4a">{pic}</span>'
            f'{lf}{pin}</span><div class="lm-f4b{"" if day else " noleaf"}"><p class="lm-f4k">{kicker}</p>'
            f'<h3 class="lm-f4t" id="lm-f4-t">{_e(title)}</h3>{f"<p class=lm-f4m>{_e(meta)}</p>" if meta else ""}'
            f'{f"<div class=lm-f4row>{row}</div>" if row else ""}{f"<p class=lm-f4note>{_e(note)}</p>" if note else ""}'
            f'</div>{after}</section>')


def up_next(count: int) -> str:
    """The heading over the card, with its pill."""
    pill = f'<span class="lm-cp4">{count} for you</span>' if count > 1 else ""
    return f'<div class="lm-up4"><h2 class="lm-h2" id="lm-up-h">Up next</h2>{pill}</div>'


def live_bar(live: Dict[str, Any]) -> str:
    title = (live or {}).get("title") or ""
    return (f'<a class="lm-lv4" href="/my/live"><i aria-hidden="true"></i>'
            f'<span>Live now{f" · {_e(title)}" if title else ""}</span><b>Join</b></a>')


# ─── Also for you ────────────────────────────────────────────────────


def tile(href: str, pic: str, badge: str, kicker: str, title: str, meta: str = "", *, day_leaf: Optional[int] = None,
         progress: Optional[int] = None, pin: bool = False, tag: str = "") -> str:
    """One picture tile. `href`, `pic` and `tag` (a Sample mark) are trusted
    markup; the words are escaped."""
    import member_app_ui as ui
    dl = f'<span class="lm-dl4" aria-hidden="true"><small>DAY</small><b>{int(day_leaf)}</b></span>' if day_leaf else ""
    bar = (f'<span class="lm-t4bar" aria-hidden="true"><i style="width:{max(0, min(100, int(progress)))}%"></i></span>'
           if progress is not None else "")
    return (f'<a class="lm-t4" href="{href}"><span class="lm-t4p"><span class="lm-t4a">{pic}</span>'
            f'<span class="lm-bdg" aria-hidden="true">{icon(badge)}</span>{dl}{ui.pin("", link=False) if pin else ""}</span>'
            f'<span class="lm-t4k">{_e(kicker)}{tag}</span><b class="lm-t4t">{_e(title)}</b>'
            f'{f"<span class=lm-t4m>{_e(meta)}</span>" if meta else ""}{bar}</a>')


def also(tiles_html: List[str]) -> str:
    if not tiles_html:
        return ""
    return (f'<section class="lm-also" aria-labelledby="lm-also-h"><h2 class="lm-also4" id="lm-also-h">Also for you</h2>'
            f'<div class="lm-g4{" one" if len(tiles_html) == 1 else ""}">{"".join(tiles_html)}</div></section>')


# ─── the sheet ───────────────────────────────────────────────────────
# Accent level 2's tokens (member_lumen_ui): --acc reads as words on the page,
# --acc-fill is a button's colour with --on-acc on it, --lm-tint-12 the soft
# church-colour surface. The card's 4% church tint is a color-mix over the
# page; a browser without it gets the plain page colour.
CSS = Template("""
/* Home, Look 4.1 (member_lumen_home): the greeting, Up next, Also for you */
.lm-brief{margin:18px 0 0;}
.lm-ey4{margin:0;display:flex;align-items:center;gap:7px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg2);}
.lm-ey4 svg{width:14px;height:14px;flex:none;fill:none;stroke:var(--fg);stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round;}
body.lm .lm-brief .lm-hi4{margin-top:12px;font-size:36px;line-height:1.05;}
.lm-line4{margin:14px 0 0;max-width:345px;font:400 16.5px/1.6 var(--mb-ui);color:var(--fg2);text-wrap:pretty;}
.lm-line4 b{font-weight:600;color:var(--fg);}
.lm-lv4{display:flex;align-items:center;gap:10px;height:44px;margin:14px 0 0;padding:0 6px 0 14px;border-radius:14px;background:var(--s1);
  color:var(--fg);font:600 13.5px/1 var(--mb-ui);text-decoration:none;}
.lm-lv4 i{width:8px;height:8px;flex:none;border-radius:50%;background:#E11D48;}
.lm-lv4 span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm-lv4 b{height:32px;padding:0 14px;border-radius:16px;background:var(--fg);color:var(--bg);display:inline-flex;align-items:center;font-weight:650;}
.lm-up4{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:32px 0 14px;}
.lm-up4 .lm-h2::before{content:"";display:block;width:24px;height:3px;margin-bottom:12px;border-radius:2px;background:var(--acc-fill);}
.lm-cp4{height:24px;padding:0 10px;border-radius:12px;background:var(--lm-tint-12);color:var(--acc);font:700 11.5px/24px var(--mb-ui);white-space:nowrap;}
.lm-f4{--lm-f4bg:var(--bg);position:relative;border-radius:20px;overflow:hidden;background:var(--lm-f4bg);
  box-shadow:0 0 0 1px var(--lm-line),0 28px 50px -36px var(--lm-shadow);}
@supports (background:color-mix(in srgb,red 50%,blue)){.lm-f4{--lm-f4bg:color-mix(in srgb,var(--acc-fill) 4%,var(--bg));}}
.lm-f4p{position:relative;display:block;height:180px;background:var(--s2);}
.lm-f4a{position:absolute;inset:0;overflow:hidden;}
.lm-f4a>*,.lm-t4a>*{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-f4a .mb-ph.is-colour img,.lm-t4a .mb-ph.is-colour img{filter:saturate(.9) sepia(.05);}
.lm-leaf4{position:absolute;left:16px;bottom:-22px;z-index:2;width:58px;height:66px;border-radius:14px;background:var(--acc-fill);color:var(--on-acc);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  box-shadow:0 0 0 3px var(--lm-f4bg),0 10px 20px -12px rgba(0,0,0,.5);}
.lm-leaf4 small{font:700 9.5px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;}
.lm-leaf4 b{margin:3px 0;font-family:var(--lm-num);font-weight:var(--lm-nw);font-stretch:var(--lm-nst);font-variant-numeric:var(--lm-nvn);
  font-size:24px;line-height:1;}
.lm-f4b{padding:32px 16px 16px;}
.lm-f4b.noleaf{padding-top:16px;}
.lm-f4k{margin:0;display:flex;align-items:center;gap:8px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
.lm-f4t{margin:8px 0 0;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);
  font-size:26px;line-height:1.1;letter-spacing:-.02em;color:var(--fg);text-wrap:balance;}
.lm-f4m{margin:4px 0 0;font:400 14px/1.4 var(--mb-ui);color:var(--fg2);}
.lm-f4row{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:16px;min-height:40px;}
.lm-f4n{display:inline-flex;align-items:center;gap:7px;font:500 13.5px/1 var(--mb-ui);color:var(--fg2);white-space:nowrap;}
.lm-f4n b{font-weight:700;color:var(--fg);}
.lm-f4acts{display:flex;align-items:center;flex-wrap:wrap;gap:2px;margin-left:auto;}
.lm-btn.done4{background:transparent;color:var(--fg);box-shadow:inset 0 0 0 1px var(--lm-line);gap:6px;}
.lm-btn.done4 svg{color:var(--acc);}
.lm-q4{height:38px;padding:0 12px;border:0;border-radius:19px;background:none;display:inline-flex;align-items:center;
  font:600 13.5px/1 var(--mb-ui);color:var(--fg2);text-decoration:none;cursor:pointer;white-space:nowrap;}
.lm-f4note{margin:10px 0 0;font:500 12.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm-f4 .mb-hint{margin:0 16px 16px;}
.lm-f4p .mb-pin,.lm-t4p .mb-pin{top:auto;bottom:10px;right:10px;height:30px;padding:0 12px;font-size:12px;background:rgba(20,18,16,.55);
  box-shadow:none;}
.lm-f4p .mb-pin svg,.lm-t4p .mb-pin svg{display:none;}
.lm-up4+.lm-cards,.lm-f4+.lm-cards,.lm-f4+.lm-ck{margin-top:16px;}
.lm-also{margin-top:34px;}
.lm-also4{margin:0 0 12px;font:650 11px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm-g4{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;}
.lm-g4.one{grid-template-columns:minmax(0,1fr);}
.lm-t4{display:flex;flex-direction:column;align-items:flex-start;min-width:0;color:var(--fg);text-decoration:none;}
.lm-t4p{position:relative;display:block;width:100%;height:112px;margin-bottom:10px;border-radius:16px;overflow:hidden;background:var(--s2);}
.lm-t4a{position:absolute;inset:0;}
.lm-bdg{position:absolute;right:8px;top:8px;z-index:2;width:28px;height:28px;border-radius:50%;background:var(--acc-fill);color:var(--on-acc);
  display:grid;place-items:center;box-shadow:0 0 0 2px rgba(255,255,255,.85);}
.lm-bdg svg{width:15px;height:15px;stroke-width:2;}
.lm-dl4{position:absolute;left:8px;bottom:8px;z-index:2;width:38px;height:42px;border-radius:10px;background:rgba(255,255,255,.94);color:#1D3A2A;
  display:flex;flex-direction:column;align-items:center;justify-content:center;}
.lm-dl4 small{font:700 8px/1 var(--mb-ui);letter-spacing:.14em;}
.lm-dl4 b{margin-top:1px;font-family:var(--lm-num);font-weight:var(--lm-nw);font-size:19px;line-height:1;}
.lm-t4p .mb-pin{bottom:8px;right:8px;height:26px;padding:0 10px;font-size:11px;}
.lm-t4k{display:block;font:650 10.5px/1.1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
.lm-t4t{display:block;margin-top:6px;font:600 15px/1.25 var(--mb-ui);}
.lm-t4m{display:block;max-width:100%;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
.lm-t4bar{display:block;width:100%;height:2px;margin-top:9px;border-radius:1px;background:var(--lm-line);overflow:hidden;}
.lm-t4bar i{display:block;height:100%;background:var(--fg);}
@media (prefers-reduced-motion:no-preference){
  .lm-t4,.lm-lv4{transition:transform .2s ease-out;}
  .lm-t4:active,.lm-lv4:active{transform:scale(.98);}
}
.lm-t4:focus-visible,.lm-lv4:focus-visible,.lm-q4:focus-visible{outline:2px solid var(--acc);outline-offset:3px;border-radius:12px;}
/* on the look's dark switch (a black base): a neutral black, the card's tint and the badges' ring with it */
body.lm.lm-dark:has(.lm-brief){--bg:#0A0A0B;--s1:#161618;--s2:#202023;--s3:#2E2E32;--line:rgba(255,255,255,.1);--lm-line:rgba(255,255,255,.1);
  --fg:#F4F2EE;--fg2:#AAA7A1;--fg3:#8F8C86;--lm-shadow:rgba(0,0,0,.6);}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm.lm-dark:has(.lm-brief){--acc:color-mix(in srgb,var(--acc-fill) 58%,#fff);--lm-tint-12:color-mix(in srgb,var(--acc-fill) 26%,#0A0A0B);}
}
html:has(>body.lm.lm-dark .lm-brief){background:#0A0A0B;}
.lm.lm-dark .lm-bdg{box-shadow:0 0 0 2px rgba(10,10,11,.85);}
""")
