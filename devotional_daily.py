"""
devotional_daily.py — the devotional a church is reading together, a day
at a time, before anyone signs in.

Kevin, 2026-10-25 (Love City's 21 days: Focus, Finances, Food): "how can
we make this devotional available where people can get them daily before
i reveal the app?" ... "build the page and nightly text".

    GET  /daily            today's day of the devotional the church reads
                           together (a published devotional with a start
                           date), on the church's own address;
                           ?date=YYYY-MM-DD opens another day that's open;
                           ?t=1 (every link we text) means "on the list"
    POST /daily/join      form {phone, name?, consent}: text me the next
                           day each evening
    the word DAILY         texted to the church's own number does the same
                           (sms_routing, beside GIVE)
    sweep_tick()           7:30, 7:35 ... 7:55 PM Eastern (on the clock);
                           texts each person tomorrow's day and its link
    morning_tick()         9:00 ... 9:25 AM Eastern: a day whose evening
                           text didn't go, as today's, to those who missed it

A day opens on its date, and tomorrow's opens the evening before, so the
text can be read that night and the morning's first look goes to God, not
the phone. The member app keeps the whole devotional (checklist, journal,
Listen); this page reads the same rows, so a day is written once. Nothing
here names the app.

Which churches: DEVOTIONAL_DAILY_BUSINESSES, comma-separated church ids
(default Love City, the first church on it), "*" for every church, "off"
for none. DEVOTIONAL_DAILY=off stops the evening texts alone.

Sign-ups are devotional_texts rows (APPLY-2026-10-25-devotional-texts.sql),
one per church and phone. A row is the consent for these texts and nothing
else: it isn't an sms_consents row, so the church's campaigns and
reminders never count it. STOP (sms_opt_outs) still wins at send time.
Kevin, the first evening: after reading the day, the page asked people to
sign up again. Someone who came from a text, or signed up here, is
remembered on that phone and sees "You're on the text list" instead, with
a way to sign up another number (a link forwarded to a friend carries
t=1 too, so that way stays one tap away).
No Listen button: the phone's own reading voice sounded like a machine
(Kevin, 10-25: "it doesn't sound natural"), so the page is read, not heard.
The evening claim is last_key: one PATCH moves it from anything else to
"<devotional id>_<day>", so one replica wins and nobody gets a day twice.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import devotionals as dv
import sb_clients

router = APIRouter(tags=["devotional-daily"])

FIRST_CHURCH = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"   # Love City Church
TZ = ZoneInfo("America/New_York")      # the same clock as texting's quiet hours
SEND_FROM, SEND_UNTIL = time(19, 30), time(19, 58)    # quiet hours start at 8 PM
SEND_AT = "7:30"
# When the scheduler runs sweep_tick: every 5 minutes of the window, by
# the Eastern clock (DST included), whenever the worker last booted.
SWEEP_CRON = {"hour": 19, "minute": "30-55/5", "timezone": "America/New_York"}
# A day whose evening text didn't go, the next morning once quiet hours end.
MORNING_FROM, MORNING_UNTIL = time(9, 0), time(9, 28)
MORNING_CRON = {"hour": 9, "minute": "0-25/5", "timezone": "America/New_York"}
DAILY_WORDS = {"DAILY", "DEVOTION", "DEVOTIONAL"}
CONSENT = ("Text me the daily devotional from {name}: one text each evening while the church reads a "
           "devotional together. Msg & data rates may apply. Reply STOP to stop, HELP for help.")
TRANSLATION = "kjv"
VERSES_SHOWN = 4


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _e(v: Any) -> str:
    return html.escape(str(v or ""), quote=True)


def enabled_for(business_id: Optional[str]) -> bool:
    raw = (os.environ.get("DEVOTIONAL_DAILY_BUSINESSES") or FIRST_CHURCH).strip()
    if not business_id or raw.lower() == "off":
        return False
    return raw == "*" or str(business_id) in {p.strip() for p in raw.split(",")}


def now_local() -> datetime:
    return datetime.now(TZ)


# ─── which day ───────────────────────────────────────────────────────


def dated(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """The church's published devotionals that have a start date, oldest
    first (no days), or None when the read failed."""
    rows = dv.catalog(business_id)
    if rows is None:
        return None
    return sorted((r for r in rows if r.get("starts_on") and int(r.get("day_count") or 0) > 0),
                  key=lambda r: r["starts_on"])


def last_day(dev: Dict[str, Any]) -> date:
    return dv.day_on(dev["starts_on"], int(dev.get("day_count") or 0))


def place(devs: List[Dict[str, Any]], on: date) -> Optional[Tuple[Dict[str, Any], int]]:
    """(the devotional, its day number) read on `on`; when two overlap,
    the one that started last."""
    for dev in sorted(devs, key=lambda r: r["starts_on"], reverse=True):
        n = dv.day_number(dev["starts_on"], int(dev.get("day_count") or 0), on)
        if n:
            return dev, n
    return None


def still_coming(devs: List[Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    """The devotionals not over yet: running, or starting later."""
    return [d for d in devs if last_day(d) >= today]


def label(dev: Dict[str, Any], n: int) -> str:
    kind = str(dev.get("kind") or "").strip()
    return f"{kind}, day {n}" if kind else f"Day {n}"


def _long(d: date) -> str:
    return f"{d:%A}, {d:%B} {d.day}"


def _short(d: date) -> str:
    return f"{d:%a}, {d:%b} {d.day}"


def _span(dev: Dict[str, Any]) -> str:
    a, b = dev["starts_on"], last_day(dev)
    return f"{a:%b} {a.day}–{b.day}" if a.month == b.month else f"{a:%b} {a.day}–{b:%b} {b.day}"


# ─── the page ────────────────────────────────────────────────────────


def _church(request: Request) -> Optional[Dict[str, Any]]:
    """The church this address belongs to, when it's on; else None."""
    import member_portal
    church = member_portal._church_for_request(request)
    if not church or not enabled_for(church["business"].get("id")):
        return None
    return church


def own_number(business_id: str) -> str:
    rows = sb_clients.sb_get_as_service(
        f"/sms_numbers?business_id=eq.{_q(business_id)}&status=eq.active&select=phone_number&limit=1")
    return str(rows[0].get("phone_number") or "") if isinstance(rows, list) and rows else ""


def pretty_phone(e164: str) -> str:
    d = re.sub(r"\D", "", e164 or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else e164


def _colours(biz: Dict[str, Any], site: Dict[str, Any]) -> Dict[str, str]:
    """The church's colour, made to read on the paper and on the night page."""
    import member_app_ui as ui
    try:
        from public_form_theme import resolve_theme
        c = ui.brand_colour(biz, resolve_theme(biz, site) or {})
    except Exception:
        c = None
    c = c or "#6d28d9"
    return {"light": ui._readable_on(c, "#f7f5f2", False), "dark": ui._readable_on(c, "#151217", True)}


def _scripture(ref_text: str) -> Tuple[str, str]:
    """(the verses as HTML, the reference's label); the verses '' when
    the reference can't be read."""
    import bible_text as bt
    import member_portal_bible as mpb
    found = bt.find_refs(ref_text or "")
    if not found:
        return "", str(ref_text or "")
    ref = found[0][2]
    verses = bt.verses(ref, TRANSLATION) or []
    many = len(verses) > 1
    words = " ".join((f"<sup>{v}</sup>" if many else "") + mpb._verse_html(t, TRANSLATION)
                     for _, v, t in verses[:VERSES_SHOWN])
    more = "…" if len(verses) > VERSES_SHOWN else ""
    return (f"{words}{more}" if words else ""), f"{ref.label()} · {bt.TRANSLATIONS[TRANSLATION]['short']}"


def _paras(text: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return "".join(f"<p{c}>{_e(p)}</p>" for p in dv.paragraphs(text))


def _series(devs: List[Dict[str, Any]], current: Optional[Dict[str, Any]], today: date) -> str:
    if len(devs) < 2:
        return ""
    chips = []
    for d in devs:
        here = current is not None and d["id"] == current["id"]
        start = d["starts_on"]
        go = min(max(start, today), last_day(d)) if start <= today + timedelta(days=1) else None
        name = _e(d.get("kind") or d.get("title"))
        inner = f'<b>{name}</b><span>{_e(_span(d))}</span>'
        if here:
            chips.append(f'<span class="chip on" aria-current="true">{inner}</span>')
        elif go:
            chips.append(f'<a class="chip" href="/daily?date={go.isoformat()}">{inner}</a>')
        else:
            chips.append(f'<span class="chip later">{inner}</span>')
    return f'<nav class="series" aria-label="The devotionals">{"".join(chips)}</nav>'


def _strip(dev: Dict[str, Any], shown: Optional[int], today: date) -> str:
    """The devotional's days: open ones link, later ones say when."""
    out = []
    count = int(dev.get("day_count") or 0)
    for n in range(1, count + 1):
        d = dv.day_on(dev["starts_on"], n)
        inner = f'<span>{d:%a}</span><b>{d.day}</b>'
        if n == shown:
            out.append(f'<span class="day on" aria-current="date">{inner}</span>')
        elif d <= today + timedelta(days=1):
            out.append(f'<a class="day" href="/daily?date={d.isoformat()}" aria-label="Day {n}, {_e(_long(d))}">{inner}</a>')
        else:
            out.append(f'<span class="day later" title="Opens {_e(_short(d))}">{inner}</span>')
    return f'<div class="strip" role="list">{"".join(out)}</div>'


def _checklist(dev: Dict[str, Any], n: int) -> str:
    practices = dev.get("practices") or []
    if not practices:
        return ""
    key = f"daily:{dev['id']}:{n}"
    items = "".join(
        f'<li><label><input type="checkbox" data-i="{i}"><span><b>{_e(p.get("title"))}</b>'
        f'{(" " + _e(p.get("sub"))) if p.get("sub") else ""}</span></label></li>'
        for i, p in enumerate(practices))
    return (f'<section class="card check" data-key="{_e(key)}"><h2>Today’s checklist</h2>'
            f'<ul>{items}</ul><p class="note">Your ticks stay on this phone.</p></section>')


def _join_box(church: Dict[str, Any], number: str, flash: str, now: datetime) -> str:
    name = church["business"].get("name") or "the church"
    msgs = {
        "joined": ("ok", f"You’re signed up. Your first text comes "
                         f"{'this' if now.time() < SEND_FROM else 'tomorrow'} evening at {SEND_AT}."),
        "phone": ("bad", "That number doesn’t look right. Use a mobile number with its area code."),
        "consent": ("bad", "Tick the box to say yes to the texts."),
        "stopped": ("bad", f"That number texted STOP before. Text START to {pretty_phone(number)} first, then sign up again."
                           if number else "That number texted STOP before, so texts can’t reach it."),
        "busy": ("bad", "Too many tries from here. Wait a few minutes and try again."),
        "none": ("bad", "There’s no devotional to send right now."),
        "error": ("bad", "That didn’t save. Try again in a minute."),
    }
    note, state = "", ""
    if flash in msgs:
        kind, words = msgs[flash]
        note = f'<p class="flash {kind}" role="status">{_e(words)}</p>'
        state = " done" if flash == "joined" else " open"     # a problem always shows the form
    text_line = (f'<p class="or">Or text <b>DAILY</b> to <a href="sms:{_e(number)}?&body=DAILY">{_e(pretty_phone(number))}</a>.</p>'
                 if number else "")
    return f"""<section class="card join{state}" id="join">
<div class="onlist">
<h2>You’re on the text list</h2>
{note if flash == "joined" else ""}
<p>Each evening at {SEND_AT}, the next day comes to your phone. No need to sign up again.</p>
<button type="button" class="another">Not on the list yet? Sign up here</button>
</div>
<div class="ask">
<h2>Get the next day by text</h2>
<p>Each evening at {SEND_AT}, tomorrow’s day comes to your phone, ready for the morning.</p>
{note if flash != "joined" else ""}
<form method="post" action="/daily/join">
<label class="f"><span>Your name <i>(optional)</i></span><input name="name" autocomplete="name" maxlength="120"></label>
<label class="f"><span>Mobile number</span><input name="phone" type="tel" inputmode="tel" autocomplete="tel" required maxlength="20" placeholder="(231) 555-0123"></label>
<label class="hp" aria-hidden="true">Leave this empty <input name="website" tabindex="-1" autocomplete="off"></label>
<label class="consent"><input type="checkbox" name="consent" value="yes" required><span>{_e(CONSENT.format(name=name))}</span></label>
<button type="submit">Text me each evening</button>
</form>
{text_line}
</div>
</section>"""


def _day_html(dev: Dict[str, Any], n: int, today: date) -> str:
    day = (dev.get("days") or [])[n - 1]
    when = dv.day_on(dev["starts_on"], n)
    verses, ref_label = _scripture(day.get("scripture") or "")
    count = int(dev.get("day_count") or len(dev.get("days") or []))
    kicker = " · ".join(x for x in (_e(dev.get("kind") or dev.get("title")), f"Day {n} of {count}") if x)
    scripture = (f'<figure class="scripture"><blockquote>{verses}</blockquote><figcaption>{_e(ref_label)}</figcaption></figure>'
                 if verses else (f'<p class="ref">{_e(ref_label)}</p>' if ref_label else ""))
    pull = f'<p class="pull">{_e(day["pull"])}</p>' if day.get("pull") else ""
    parts = [("Pray", day.get("pray")), ("Do today", day.get("act")), ("Together", day.get("together"))]
    cards = "".join(f'<div class="do"><h3>{h}</h3>{_paras(t)}</div>' for h, t in parts if t)
    when_line = "Today" if when == today else ("Tomorrow" if when == today + timedelta(days=1) else "")
    return f"""<header class="head">
<p class="kicker">{kicker}</p>
<p class="when">{(when_line + " · ") if when_line else ""}{_e(_long(when))}</p>
<h1>{_e(day.get("title") or f"Day {n}")}</h1>
</header>
{scripture}
<article class="words">{_paras(day.get("body") or "")}{pull}</article>
<section class="dos">{cards}</section>"""


def _shell(church: Dict[str, Any], title: str, body: str) -> str:
    import member_app_photos as photos
    import member_app_ui as ui
    biz, site = church["business"], church["site"]
    col = _colours(biz, site)
    name = biz.get("name") or ""
    ink, light = photos.wordmark(site, light=False), photos.wordmark(site, light=True)
    if ink and light:        # the dark logo on paper, the light one on the night page
        brand = (f'<picture><source srcset="{_e(light)}" media="(prefers-color-scheme: dark)">'
                 f'<img src="{_e(ink)}" alt="{_e(name)}"></picture>')
    elif ink or light:
        brand = f'<img class="{"ink" if ink else "lit"}" src="{_e(ink or light)}" alt="{_e(name)}">'
    else:
        brand = f"<b>{_e(name)}</b>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{_e(title)} · {_e(name)}</title>
<meta name="description" content="The devotional {_e(name)} is reading together, a day at a time.">
<meta name="theme-color" content="#f7f5f2" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#151217" media="(prefers-color-scheme: dark)">
<script>try{{if(/[?&](t|joined)=1(&|$)/.test(location.search))localStorage.setItem('daily-listed','1');if(localStorage.getItem('daily-listed'))document.documentElement.className+=' listed';}}catch(e){{}}</script>
{ui.FONTS}
<style>
:root{{--paper:#f7f5f2;--card:#fff;--ink:#1d1720;--soft:#5d5562;--line:#e6e1e7;--accent:{col['light']};color-scheme:light dark}}
@media (prefers-color-scheme:dark){{:root{{--paper:#151217;--card:#1e1a21;--ink:#f2eef4;--soft:#a9a0ad;--line:#2e2832;--accent:{col['dark']}}}}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--paper);color:var(--ink);font:400 17px/1.65 Geist,system-ui,-apple-system,sans-serif}}
a{{color:var(--accent)}}
.wrap{{max-width:680px;margin:0 auto;padding:0 20px 64px}}
.top{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 0 14px;border-bottom:1px solid var(--line)}}
.top a{{color:var(--ink);text-decoration:none;display:flex;align-items:center}}
.top img{{height:34px;width:auto;display:block}}
@media (prefers-color-scheme:dark){{.top img.ink{{filter:invert(1) hue-rotate(180deg)}}}}
@media (prefers-color-scheme:light){{.top img.lit{{filter:invert(1) hue-rotate(180deg)}}}}
.top span{{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--soft)}}
.series{{display:flex;gap:8px;overflow-x:auto;padding:16px 0 4px;scrollbar-width:none}}
.series::-webkit-scrollbar{{display:none}}
.chip{{flex:0 0 auto;display:flex;flex-direction:column;padding:8px 12px;border:1px solid var(--line);border-radius:14px;text-decoration:none;color:var(--ink);font-size:13px;line-height:1.3}}
.chip span{{color:var(--soft);font-size:12px}}
.chip.on{{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}}
.chip.later{{opacity:.55}}
.head{{padding:28px 0 8px}}
.kicker{{margin:0;color:var(--accent);font-weight:600;font-size:14px;letter-spacing:.04em;text-transform:uppercase}}
.when{{margin:4px 0 0;color:var(--soft);font-size:15px}}
h1{{font:500 clamp(34px,8vw,46px)/1.08 Newsreader,Georgia,serif;letter-spacing:-.01em;margin:14px 0 0}}
.scripture{{margin:26px 0 8px;padding:22px 22px 18px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:16px}}
.scripture blockquote{{margin:0;font:italic 400 21px/1.5 Newsreader,Georgia,serif}}
.scripture sup{{font:600 11px Geist,system-ui,sans-serif;color:var(--soft);margin-right:2px}}
.scripture figcaption,.ref{{margin-top:10px;color:var(--soft);font-size:14px;font-weight:600}}
.words p{{margin:18px 0}}
.pull{{font:italic 500 24px/1.35 Newsreader,Georgia,serif;color:var(--accent);margin:28px 0!important;padding-left:16px;border-left:2px solid var(--accent)}}
.dos{{display:grid;gap:12px;margin:24px 0}}
.do,.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 20px}}
.do h3,.card h2{{margin:0 0 6px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}}
.do p{{margin:0}}
.days{{margin:32px 0 8px}}
.days h2{{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--soft);margin:0 0 10px}}
.strip{{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}}
.day{{display:flex;flex-direction:column;align-items:center;padding:8px 0;border:1px solid var(--line);border-radius:12px;text-decoration:none;color:var(--ink);font-size:12px;line-height:1.2}}
.day b{{font-size:17px}}
.day.on{{background:var(--accent);border-color:var(--accent);color:var(--paper)}}
.day.later{{opacity:.4}}
.card{{margin:16px 0}}
.check ul{{list-style:none;margin:8px 0 0;padding:0}}
.check li{{border-top:1px solid var(--line)}}
.check li:first-child{{border-top:0}}
.check label{{display:flex;gap:12px;align-items:flex-start;padding:10px 0;cursor:pointer}}
.check input{{width:20px;height:20px;margin-top:3px;accent-color:var(--accent);flex:0 0 auto}}
.check span{{color:var(--soft)}}
.check b{{color:var(--ink);font-weight:600}}
.note{{margin:6px 0 0;font-size:13px;color:var(--soft)}}
.join p{{margin:4px 0 14px}}
.f{{display:block;margin:0 0 12px}}
.f span{{display:block;font-size:14px;font-weight:600;margin-bottom:4px}}
.f i{{font-weight:400;color:var(--soft)}}
.f input{{width:100%;font:inherit;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--paper);color:var(--ink)}}
.consent{{display:flex;gap:10px;align-items:flex-start;font-size:13px;line-height:1.5;color:var(--soft);margin:4px 0 16px}}
.consent input{{width:18px;height:18px;margin-top:2px;accent-color:var(--accent);flex:0 0 auto}}
.join button{{width:100%;font:600 16px Geist,system-ui,sans-serif;color:#fff;background:var(--accent);border:0;border-radius:12px;padding:14px;cursor:pointer}}
.join .onlist{{display:none}}
.join.done .ask,.listed .join:not(.open) .ask{{display:none}}
.join.done .onlist,.listed .join:not(.open) .onlist{{display:block}}
.join .onlist button{{width:auto;background:none;color:var(--accent);padding:0;font-size:15px;text-decoration:underline;text-underline-offset:3px}}
.or{{text-align:center;font-size:14px;color:var(--soft);margin:14px 0 0!important}}
.hp{{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}}
.flash{{padding:10px 14px;border-radius:12px;font-size:14px;font-weight:600}}
.flash.ok{{background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--ink)}}
.flash.bad{{background:#fbebeb;color:#8a1c1c}}
@media (prefers-color-scheme:dark){{.flash.bad{{background:#3a1c1c;color:#ffd5d5}}.join button{{color:#151217}}}}
.about p{{margin:14px 0}}
.foot{{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);font-size:14px;color:var(--soft)}}
</style></head><body><div class="wrap">
<div class="top"><a href="/">{brand}</a><span>Daily devotional</span></div>
{body}
<p class="foot">{_e(name)} · <a href="/">Visit our site</a></p>
</div>
<script>
(function(){{
 if(/[?&]t=1/.test(location.search)&&history.replaceState){{
  var u=new URL(location.href);u.searchParams.delete('t');history.replaceState(null,'',u.pathname+u.search+u.hash);
 }}
 var a=document.querySelector('.join .another');
 if(a)a.addEventListener('click',function(){{
  var j=document.getElementById('join');j.classList.remove('done');j.classList.add('open');
  var p=j.querySelector('input[name=phone]');if(p)p.focus();
 }});
 var c=document.querySelector('.check');
 if(c){{var k=c.getAttribute('data-key'),s={{}};
  try{{s=JSON.parse(localStorage.getItem(k)||'{{}}')||{{}};}}catch(e){{s={{}};}}
  c.querySelectorAll('input[type=checkbox]').forEach(function(b){{
   b.checked=!!s[b.getAttribute('data-i')];
   b.addEventListener('change',function(){{s[b.getAttribute('data-i')]=b.checked;try{{localStorage.setItem(k,JSON.stringify(s));}}catch(e){{}}}});
  }});}}
}})();
</script></body></html>"""


def render(church: Dict[str, Any], devs: List[Dict[str, Any]], *, ask: Optional[date],
           flash: str = "", now: Optional[datetime] = None, number: str = "") -> str:
    """The /daily page: the asked-for day when it's open, else today's;
    before the first day, the devotional's welcome; after the last, the
    last one's days, all open."""
    now = now or now_local()
    today = now.date()
    want = ask if ask and ask <= today + timedelta(days=1) else today
    hit = place(devs, want) or (place(devs, today) if want != today else None)
    join = _join_box(church, number, flash, now) if still_coming(devs, today) else ""
    if hit:
        dev, n = hit
        full, _ = dv.one(church["business"]["id"], dev["id"])
        if full and len(full.get("days") or []) >= n:
            body = (_series(devs, dev, today) + _day_html(full, n, today)
                    + _checklist(full, n)
                    + f'<section class="days"><h2>{_e(full.get("title"))} · {_e(_span(dev))}</h2>{_strip(dev, n, today)}</section>'
                    + join)
            return _shell(church, full["days"][n - 1].get("title") or full.get("title") or "Today", body)
    coming = [d for d in devs if d["starts_on"] > today]
    if coming:
        dev = coming[0]
        full, _ = dv.one(church["business"]["id"], dev["id"])
        full = full or dev
        practices = "".join(f'<li><b>{_e(p.get("title"))}</b>{(" " + _e(p.get("sub"))) if p.get("sub") else ""}</li>'
                            for p in full.get("practices") or [])
        body = (_series(devs, None, today)
                + f'<header class="head"><p class="kicker">Starts {_e(_long(dev["starts_on"]))}</p>'
                + f'<h1>{_e(full.get("title"))}</h1></header>'
                + f'<article class="about words">{_paras(full.get("about") or "")}</article>'
                + (f'<section class="card"><h2>Every day</h2><ul>{practices}</ul></section>' if practices else "")
                + join)
        return _shell(church, full.get("title") or "Daily devotional", body)
    dev = devs[-1]
    body = (_series(devs, dev, today)
            + f'<header class="head"><p class="kicker">{_e(dev.get("kind") or "Devotional")}</p>'
            + f'<h1>{_e(dev.get("title"))}</h1>'
            + f'<p class="when">That was {_e(_span(dev))}. Every day is still here.</p></header>'
            + f'<section class="days">{_strip(dev, None, today)}</section>')
    return _shell(church, dev.get("title") or "Daily devotional", body)


def _not_here() -> HTMLResponse:
    return HTMLResponse("<!doctype html><title>Not found</title><p>Not found.</p>", status_code=404)


@router.get("/daily", include_in_schema=False)
async def daily_page(request: Request, on: Optional[str] = Query(None, alias="date"),
                     joined: Optional[str] = None, why: Optional[str] = None):
    church = await asyncio.to_thread(_church, request)
    if not church:
        return _not_here()
    biz_id = church["business"]["id"]
    devs = await asyncio.to_thread(dated, biz_id)
    if devs is None:
        return HTMLResponse("<!doctype html><title>One moment</title><p>This page couldn’t load just now. "
                            "Try again in a minute.</p>", status_code=503)
    if not devs:
        return _not_here()
    try:
        ask = datetime.strptime(on, "%Y-%m-%d").date() if on else None
    except ValueError:
        ask = None
    number = await asyncio.to_thread(own_number, biz_id)
    flash = "joined" if joined == "1" else (why or "")
    page = await asyncio.to_thread(render, church, devs, ask=ask, flash=flash, number=number)
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=0, s-maxage=120"})


# ─── joining ─────────────────────────────────────────────────────────


def _save(business_id: str, phone: str, *, name: str, source: str, consent: str) -> bool:
    """The church's row for this phone, live again (a stopped one comes
    back); last_key is left as it was, so a day already sent isn't sent
    again."""
    row = {"business_id": business_id, "phone": phone, "source": source, "consent": consent[:600],
           "joined_at": datetime.now(timezone.utc).isoformat(), "stopped_at": None}
    if name:
        row["name"] = name[:120]
    rows = sb_clients.sb_post_as_service("/devotional_texts?on_conflict=business_id,phone", row,
                                         prefer="resolution=merge-duplicates,return=representation")
    return isinstance(rows, list) and bool(rows)


def page_link(business_id: str, on: Optional[date] = None) -> str:
    """The page as we text it, only ever to someone on the list: t=1 tells
    the page so, and it stops asking them to sign up."""
    import church_follow_up
    origin = church_follow_up.site_origin(business_id) or ""
    return f"{origin}/daily?" + (f"date={on.isoformat()}&" if on else "") + "t=1"


def is_daily_word(body: str) -> bool:
    """'daily', 'DAILY!', ' Devotional. ': one word, punctuation ignored."""
    words = re.sub(r"[^A-Za-z ]", " ", body or "").split()
    return len(words) == 1 and words[0].upper() in DAILY_WORDS


def join_by_text(business_id: str, phone: str) -> Optional[Dict[str, str]]:
    """{name, url} for the reply when DAILY on the church's own number
    signs this phone up, or None when it shouldn't answer (not on for this
    church, nothing to send, a failed read or write): the text then goes
    to the inbox like any other."""
    if not enabled_for(business_id):
        return None
    devs = dated(business_id)
    if not devs or not still_coming(devs, now_local().date()):
        return None
    biz = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=name&limit=1")
    name = (biz[0].get("name") if isinstance(biz, list) and biz else "") or "the church"
    if not _save(business_id, phone, name="", source="text", consent=f"Texted DAILY to {name}'s number"):
        return None
    return {"name": name, "url": page_link(business_id)}


def _welcome(name: str, link: str) -> str:
    import sms_service
    return sms_service.compose_outbound_body(
        name, f"You're signed up for the daily devotional: 1 text each evening at {SEND_AT} with the next day. "
              f"Today's is here: {link} Msg & data rates may apply. Reply HELP for help.", include_optout=True)


@router.post("/daily/join", include_in_schema=False)
async def daily_join(request: Request):
    import httpx
    import rate_limit
    import sms_routing
    import sms_service
    church = await asyncio.to_thread(_church, request)
    if not church:
        return _not_here()

    def back(why: str = "") -> RedirectResponse:
        return RedirectResponse(f"/daily?{'joined=1' if not why else 'why=' + why}#join", status_code=303)

    form = await request.form()
    if str(form.get("website") or "").strip():
        return back()                    # a bot filled the hidden box; nothing saved
    if not rate_limit.allow_strict("daily_join", rate_limit.trusted_client_ip(request)):
        return back("busy")
    phone = sms_service.normalize_phone(str(form.get("phone") or "")[:20])
    if not re.fullmatch(r"\+1\d{10}", phone or ""):
        return back("phone")
    if str(form.get("consent") or "").lower() not in ("yes", "on", "true", "1"):
        return back("consent")
    biz = church["business"]
    devs = await asyncio.to_thread(dated, biz["id"])
    now = now_local()
    if devs is None:
        return back("error")
    if not still_coming(devs, now.date()):
        return back("none")
    async with httpx.AsyncClient(timeout=10) as client:
        if await sms_service.is_opted_out(client, phone, biz["id"]):
            return back("stopped")
        name = re.sub(r"\s+", " ", str(form.get("name") or "")).strip()[:120]
        words = CONSENT.format(name=biz.get("name") or "the church")
        if not await asyncio.to_thread(_save, biz["id"], phone, name=name, source="web", consent=words):
            return back("error")
        try:
            await sms_routing._ensure_contact(client, biz["id"], phone)
        except Exception as e:
            print(f"[daily] contact for a new sign-up not made: {e}", flush=True)
        import sms_alerts
        if sms_alerts.QUIET_SEND_START_HOUR <= now.hour < sms_alerts.QUIET_SEND_END_HOUR and sms_alerts.alerts_enabled():
            body = _welcome(biz.get("name") or "", page_link(biz["id"]))
            try:
                sid = await sms_routing._send_platform_sms(phone, body, business_id=biz["id"], client=client)
                await sms_service._store_sms(client, biz["id"], None, phone, body, "outbound",
                                             telnyx_id=sid or "", sent_by="system")
            except Exception as e:
                print(f"[daily] welcome text to a new sign-up failed: {e}", flush=True)
    return back()


# ─── the evening text ────────────────────────────────────────────────


def evening_text(name: str, dev: Dict[str, Any], n: int, day: Dict[str, Any], link: str,
                 *, morning: bool = False) -> str:
    import sms_service
    ref = str(day.get("scripture") or "").strip()
    what = f"{day.get('title') or ('Day ' + str(n))}" + (f", {ref}" if ref else "")
    if morning:
        return sms_service.compose_outbound_body(
            name, f"Today's devotional ({label(dev, n)}): {what}. Read it: {link}", include_optout=True)
    return sms_service.compose_outbound_body(
        name, f"Tomorrow's devotional ({label(dev, n)}): {what}. Read it tonight: {link}", include_optout=True)


def _plan(on: date, *, morning: bool = False) -> List[Dict[str, Any]]:
    """Each church to text: its people and the day's text. In the morning
    each church also names `after`, the evening before's key: only someone
    still on it missed this day's text."""
    rows = sb_clients.sb_get_as_service(
        "/devotional_texts?stopped_at=is.null&select=id,business_id,phone,last_key&order=joined_at.asc&limit=5000")
    if not isinstance(rows, list):
        print("[daily] the sign-ups couldn't be read; no texts tonight", flush=True)
        return []
    by_biz: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_biz.setdefault(r["business_id"], []).append(r)
    out = []
    for biz_id, people in by_biz.items():
        if not enabled_for(biz_id):
            continue
        devs = dated(biz_id)
        hit = place(devs or [], on)
        if not hit:
            continue
        dev, n = hit
        after = None
        if morning:
            before = place(devs or [], on - timedelta(days=1))
            if not before:
                continue                         # a first day: no evening before to have missed
            after = f"{before[0]['id']}_{before[1]}"
        full, _ = dv.one(biz_id, dev["id"])
        if not full or len(full.get("days") or []) < n:
            continue
        biz = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=name&limit=1")
        name = (biz[0].get("name") if isinstance(biz, list) and biz else "") or ""
        out.append({"business_id": biz_id, "key": f"{dev['id']}_{n}", "after": after, "people": people,
                    "body": evening_text(name, full, n, full["days"][n - 1], page_link(biz_id, on),
                                         morning=morning)})
    return out


def _claim(row_id: str, key: str, at: str, after: Optional[str] = None) -> bool:
    """Move this person's last_key to tonight's key; True for the one
    replica whose PATCH found it on something else (in the morning, on
    the evening before's key and nothing else)."""
    which = (f"&last_key=eq.{_q(after)}" if after
             else f"&or=(last_key.is.null,last_key.neq.{_q(key)})")
    rows = sb_clients.sb_patch_as_service(
        f"/devotional_texts?id=eq.{_q(row_id)}&stopped_at=is.null{which}",
        {"last_key": key, "last_sent_at": at})
    return isinstance(rows, list) and bool(rows)


def _unclaim(row_id: str, key: str, before: Optional[str]) -> None:
    """A text that didn't go: put last_key back, so a later tick tries again."""
    sb_clients.sb_patch_as_service(f"/devotional_texts?id=eq.{_q(row_id)}&last_key=eq.{_q(key)}",
                                   {"last_key": before})


async def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """From 7:30 to 8 PM Eastern, text everyone signed up tomorrow's day."""
    return await _send_round(now, morning=False)


async def morning_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """From 9:00 to 9:30 AM Eastern, the day whose evening text never came
    goes out as today's, to the people who had the evening before's and
    to nobody else. 10-28 nobody got Day 4 at 7:30 and quiet hours had
    begun by the time it was noticed; Kevin: "send the one that was
    suppose to be sent out at 7:30pm as soon as you can"."""
    return await _send_round(now, morning=True)


async def _send_round(now: Optional[datetime], *, morning: bool) -> Dict[str, int]:
    import httpx
    import sms_alerts
    import sms_routing
    import sms_service
    counts = {"sent": 0, "skipped": 0, "failed": 0}
    if (os.environ.get("DEVOTIONAL_DAILY") or "on").strip().lower() == "off" or not sms_alerts.alerts_enabled():
        return counts
    now = (now or now_local()).astimezone(TZ)
    start, until = (MORNING_FROM, MORNING_UNTIL) if morning else (SEND_FROM, SEND_UNTIL)
    if not (start <= now.time() < until):
        return counts
    what = "morning catch-up" if morning else "evening sweep"
    # Every run in the window leaves a line, sent or not: 10-28's miss left
    # no trace of whether the sweep ran at all.
    plan = await asyncio.to_thread(_plan, now.date() + timedelta(days=0 if morning else 1), morning=morning)
    if not plan:
        print(f"[daily] {what} {now:%H:%M}: no devotional day to send", flush=True)
        return counts
    at = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=15) as client:
        for church in plan:
            biz_id, key, body, after = church["business_id"], church["key"], church["body"], church.get("after")
            for person in church["people"]:
                if person.get("last_key") == key or (morning and person.get("last_key") != after):
                    continue
                phone = person["phone"]
                if await sms_service.is_opted_out(client, phone, biz_id):
                    counts["skipped"] += 1
                    continue
                if not await asyncio.to_thread(_claim, person["id"], key, at, after):
                    continue                     # another replica has them
                try:
                    sid = await sms_routing._send_platform_sms(phone, body, business_id=biz_id, client=client)
                    contact = await sms_service._find_contact_by_phone(client, biz_id, phone)
                    await sms_service._store_sms(client, biz_id, (contact or {}).get("id"), phone, body,
                                                 "outbound", telnyx_id=sid or "", sent_by="system")
                    counts["sent"] += 1
                except Exception as e:
                    counts["failed"] += 1
                    print(f"[daily] {what} text failed for biz {biz_id[:8]}: {e}", flush=True)
                    await asyncio.to_thread(_unclaim, person["id"], key, person.get("last_key"))
                await asyncio.sleep(0.25)
    print(f"[daily] {what} {now:%H:%M}: {json.dumps(counts)}", flush=True)
    return counts
