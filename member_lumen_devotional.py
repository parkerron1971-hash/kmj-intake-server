"""member_lumen_devotional.py — the devotional in the member app's new look ("Lumen Next").

Kevin, 2026-11-19, on the member app: "where is the devotional section. I
didn't see it". The Lumen Next mock answered with the devotional in three
places (its boards "Bible tab: the devotional on top", "A devotional day"
and "A devotional day, night reading"), and he said "build this app". Who
sees it: member_lumen.py (MEMBER_LUMEN). Off, every page is today's, byte
for byte.

  the Bible tab .. today's devotional on top, as the one rich card on the
                   page (deep green, a hairline frame): "Devotional · Day 3
                   of 7", the devotional's title with its last word in
                   italics, today's day and how long, a dot for every day
                   (read ones filled, today's ringed), Read today and Listen.
                   With nothing running it says what is next ("Next
                   devotional · starts Sunday, Nov 29"), or offers the last
                   one again, or one to start (card()).
  a day .......... /my/bible/plans/<devotional>/<n>, read like a book: the
                   church's picture for it, the deep green plate (the
                   devotional · Day N of M, the day's title, who wrote it and
                   how long, the days as dots, Listen and Share), the
                   scripture on the ivory card, the words in the reading
                   face with a drop capital, the line to hold, Reflect (the
                   day's question and the private journal), Pray, Do today,
                   Together, the daily checklist, Mark the day as read (and
                   Not done yet), and the days before and after. No tab bar
                   while reading. Aa holds the text size and the font (kept
                   with the Bible reader's, on the phone).
  night reading .. the same day dark: the Bible reader's moon and cookie
                   (member_lumen_bible.NIGHT_COOKIE, read by the server so the
                   page arrives dark) and _shell's lumen_dark, the reader's
                   warm night. The green bar and plate stay green.

Nothing here is made up: the card and the day are drawn from the rows
today's pages read (member_portal_devotionals), with no read of their own.
The mock's "Remind me" (before the next devotional) is not built: there is
no reminder to keep. A picture shows only when the church chose one for the
devotional or has a photo named for it (member_app_photos.choose).

The day's script (DAY_JS) saves through the same routes as today's day page
(/my/bible/plans/day, /my/bible/plans/listen); it is today's DAY_JS on the
new markup, plus Aa.

The look is CSS (below), joined into the Lumen sheet by
member_lumen_ui.templates(); every rule sits under body.lm.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from member_lumen_ui import dark as _dark

# The devotional's own colours (the mock's): the deep green it wears, the
# mint on it, and the leaf green of its labels on the page (lighter at night).
GREEN = "#10261C"
MINT = "#BDE3C2"
LEAF = "#2F7A4E"
# Past this many days the dots are a picture only (no day of its own to tap).
TAP_DAYS = 14
# Past this many, the Bible tab's card shows how far as 21 dots in proportion.
CARD_DAYS = 31
_WORDS = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve")
_GLYPHS = {
    "listen": '<path d="M3 14v-2a9 9 0 0 1 18 0v2"/><path d="M21 15a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2z"/>'
              '<path d="M3 15a2 2 0 0 0 2 2h1v-6H5a2 2 0 0 0-2 2z"/>',
}


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def _glyph(name: str, size: int = 16) -> str:
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{_GLYPHS[name]}</svg>')


def _short_date(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _day_date(d: date) -> str:
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}"


def _long_date(d: date) -> str:
    return f"{d.strftime('%A')}, {d.strftime('%b')} {d.day}"


def in_a_row(n: int) -> str:
    """'Three in a row.' (a number in words up to twelve)."""
    return f"{_WORDS[n] if n < len(_WORDS) else n} in a row." if n > 1 else ""


def _href(dev: Dict[str, Any], n: Optional[int] = None) -> str:
    return f"/my/bible/plans/{dev['id']}" + (f"/{int(n)}" if n else "")


def _the_day(dev: Dict[str, Any], n: int) -> Dict[str, Any]:
    days = dev.get("days") or []
    return days[n - 1] if 1 <= n <= len(days) and isinstance(days[n - 1], dict) else {}


def _end(st: Dict[str, Any]) -> date:
    import devotionals as dv
    return dv.day_on(st["start"], max(1, st["count"]))


# ─── the Bible tab: today's devotional on top ────────────────────────


def pick(sts: List[Tuple[Dict[str, Any], Dict[str, Any]]]):
    """What the card on top of the Bible tab shows, from each devotional and
    where the member is in it (member_portal_devotionals.state):
    ("today", dev, st, None): one running today (the church's first);
    ("next", dev, st, last): none running, the next one the church dated,
      and the last one that ended (or None) to read until then;
    ("again", dev, st, None): the last one that ended, to read again;
    ("start", dev, st, None): one to start on your own day;
    None: the church has none."""
    running = [x for x in sts if x[1]["now"] and x[1]["kind"] in ("running", "finished")]
    if running:
        d, st = next((x for x in running if x[0].get("starts_on")), running[0])
        return "today", d, st, None
    past = sorted((x for x in sts if x[1]["kind"] in ("over", "finished") and x[1]["start"]),
                  key=lambda x: _end(x[1]), reverse=True)
    coming = sorted((x for x in sts if x[1]["kind"] == "upcoming" and x[1]["start"]), key=lambda x: x[1]["start"])
    if coming:
        return "next", coming[0][0], coming[0][1], (past[0] if past else None)
    if past:
        return "again", past[0][0], past[0][1], None
    new = [x for x in sts if x[1]["kind"] == "new"]
    if new:
        return "start", new[0][0], new[0][1], None
    return None


def dots(st: Dict[str, Any], *, ring: bool = True) -> str:
    """A dot for every day: read ones filled, today's ringed (filled once
    it's read). A long one is 21 dots, filled in proportion."""
    count, done = int(st.get("count") or 0), st.get("done") or set()
    if not count:
        return ""
    if count > CARD_DAYS:
        on = round(21 * len(done) / count)
        marks = ["d" if k < on else "" for k in range(21)]
    else:
        marks = []
        for n in range(1, count + 1):
            if n in done:
                marks.append("d")
            elif ring and n == st.get("now"):
                marks.append("t")
            else:
                marks.append("")
    said = (f"Day {st['now']} of {count}. " if ring and st.get("now") else f"{count} days. ") + \
        f"{len(done)} {'day' if len(done) == 1 else 'days'} read."
    return (f'<span class="lm-devo-dots" role="img" aria-label="{_e(said)}">'
            + "".join(f'<i class="{m}"></i>' if m else "<i></i>" for m in marks) + "</span>")


def card(biz: Dict[str, Any], sts, *, listen: bool = False) -> Tuple[str, Optional[Dict[str, Any]]]:
    """The devotional on top of the Bible tab: (its markup, the devotional
    it shows, so the rail below leaves it out). ('', None) when the church
    has none. `listen`: Listen can work (devotional_voice.can_speak)."""
    import devotionals as dv
    import member_lumen_ui as lm
    got = pick(sts)
    if not got:
        return "", None
    kind, d, st, last = got
    count = st["count"]
    title = d.get("title") or "Devotional"
    acts: List[str] = []
    track = ""
    say = ""
    if kind == "today":
        n = st["now"]
        day = _the_day(d, n)
        kick = f"Devotional · Day {n} of {count}"
        if (day.get("title") or "").strip():
            meta = f"Today: {day['title'].strip()} · {dv.minutes(day)} min"
        else:
            meta = f"Day {n} today" + (f" · {dv.minutes(day)} min" if day else "")
        read = n in st["done"]
        acts.append(f'<a class="lm-devo-go" href="{_href(d, n)}">{"Read again" if read else "Read today"}</a>')
        if listen:
            acts.append(f'<button class="lm-devo-go ghost" type="button" data-devo-listen data-dev="{_e(d["id"])}" '
                        f'data-day="{n}" aria-pressed="false">{_glyph("listen")}<span>Listen</span></button>'
                        f'<audio id="lm-devo-audio" preload="none"></audio>')
            say = '<p class="lm-devo-say" role="status" data-devo-say hidden></p>'
        track = dots(st)
    elif kind == "next":
        kick = f"Next devotional · starts {_long_date(st['start'])}"
        if last:
            ld, lst = last
            meta = (f"Until then, read {ld.get('title') or 'the last one'} again "
                    f"({lst['count']} day{'' if lst['count'] == 1 else 's'}, ended {_short_date(_end(lst))}).")
            name = ld.get("title") or ""
            go = f"Read {name}" if name and len(name) <= 22 else "Read it again"
            acts.append(f'<a class="lm-devo-go" href="{_href(ld, lst["next"] or 1)}">{_e(go)}</a>')
        else:
            meta = f"{count} day{'' if count == 1 else 's'}" + (f" · by {d['author']}" if d.get("author") else "")
            acts.append(f'<a class="lm-devo-go" href="{_href(d)}">See the days</a>')
    elif kind == "again":
        kick = f"Devotional · {count} day{'' if count == 1 else 's'} · ended {_short_date(_end(st))}"
        if st["kind"] == "finished":
            meta = "You finished it. Every day is still here to read again."
            acts.append(f'<a class="lm-devo-go" href="{_href(d, 1)}">Read it again</a>')
        elif st["done"]:
            meta = f"{len(st['done'])} of {count} days read. Every day is still open."
            acts.append(f'<a class="lm-devo-go" href="{_href(d, st["next"] or 1)}">Pick up at day {st["next"] or 1}</a>')
        else:
            meta = "Every day is still open to read."
            acts.append(f'<a class="lm-devo-go" href="{_href(d, 1)}">Start at day 1</a>')
        track = dots(st, ring=False)
    else:   # start
        kick = f"Devotional · {count} day{'' if count == 1 else 's'}"
        meta = "Start any time. A day opens each day from the day you start."
        acts.append(f'<a class="lm-devo-go" href="{_href(d)}">See the days</a>')
    html = (f'<section class="lm-devo" aria-labelledby="lm-devo-h"><p class="lm-devo-k">{_e(kick)}</p>'
            f'<h2 class="lm-devo-t" id="lm-devo-h">{lm.italic_last(title)}</h2><p class="lm-devo-m">{_e(meta)}</p>'
            f'{track}<div class="lm-devo-acts">{"".join(acts)}</div>{say}</section>')
    return html, d


# The card's Listen: the day's reading, made once and kept (devotional_voice),
# played here without leaving the Bible tab.
CARD_JS = r"""<script>(function(){
var b=document.querySelector('[data-devo-listen]'),au=document.getElementById('lm-devo-audio');if(!b||!au)return;
var w=b.querySelector('span'),out=document.querySelector('[data-devo-say]'),t=null;
function words(s){if(w)w.textContent=s;}
function tell(s){if(!out)return;out.textContent=s;out.hidden=false;clearTimeout(t);t=setTimeout(function(){out.hidden=true;},4000);}
au.addEventListener('play',function(){b.setAttribute('aria-pressed','true');words('Pause');});
au.addEventListener('pause',function(){b.setAttribute('aria-pressed','false');words(au.ended?'Listen again':'Play');});
b.addEventListener('click',function(){
 if(au.getAttribute('src')){if(au.paused){au.play().catch(function(){});}else{au.pause();}return;}
 b.disabled=true;words('Getting it ready…');
 fetch('/my/bible/plans/listen',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
  body:JSON.stringify({devotional:b.getAttribute('data-dev'),day:+b.getAttribute('data-day')})})
 .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
 .then(function(d){b.disabled=false;au.src=d.url;au.play().catch(function(){words('Play');});})
 .catch(function(d){b.disabled=false;words('Listen');
  tell(d&&d.error==='slow'?'That’s a lot at once. Wait a minute.':'Listen didn’t work just now. Try again in a minute.');});});
})();</script>"""


# ─── a day ───────────────────────────────────────────────────────────


def track(st: Dict[str, Any], dev: Dict[str, Any]) -> str:
    """The days on the green plate as dots: read ones filled, the one you're
    on ringed, ones not open yet faint. Up to TAP_DAYS, each open day is a
    link to it; past that, a picture of how far."""
    count, done, here = st["count"], st["done"], st.get("here")
    if not count:
        return ""

    def cls(n: int) -> str:
        return " ".join(c for c in ("is-done" if n in done else "", "is-here" if n == here else "",
                                    "is-shut" if n > st["upto"] else "") if c)
    if count > TAP_DAYS:
        said = f"Day {here} of {count}. {len(done)} {'day' if len(done) == 1 else 'days'} read."
        return (f'<span class="lm-dd-track is-many" role="img" aria-label="{_e(said)}">'
                + "".join(f'<span class="{cls(n)}"{" data-here" if n == here else ""}><i></i></span>'
                          for n in range(1, count + 1)) + "</span>")
    out = []
    for n in range(1, count + 1):
        label = f"Day {n}" + (", read" if n in done else "") + (", not open yet" if n > st["upto"] else "")
        mark = ' data-here' if n == here else ""
        if n <= st["upto"]:
            cur = ' aria-current="page"' if n == here else ""
            out.append(f'<a class="{cls(n)}" href="{_href(dev, n)}" aria-label="{_e(label)}"{cur}{mark}><i></i></a>')
        else:
            out.append(f'<span class="{cls(n)}" aria-label="{_e(label)}" role="img"{mark}><i></i></span>')
    return f'<nav class="lm-dd-track" aria-label="The days">{"".join(out)}</nav>'


def scripture(ref_text: str, tr: str, limit: int = 3) -> Tuple[str, str, str]:
    """(the verses as HTML, '' when the reference can't be read; their label;
    the chapter's link)."""
    import bible_text as bt
    import member_portal_bible as mpb
    found = bt.find_refs(ref_text or "")
    if not found:
        return "", str(ref_text or ""), ""
    ref = found[0][2]
    verses = bt.verses(ref, tr) or []
    words = " ".join(mpb._verse_html(t, tr) for _, _, t in verses[:limit])
    more = "…" if len(verses) > limit else ""
    return (words + more if words else ""), ref.label(), f"{ref.href()}#v{ref.start or 1}"


def _step(dev: Dict[str, Any], st: Dict[str, Any], k: int, which: str, today: date) -> str:
    """The day before or after, at the foot: a link once it's open, else
    when it opens."""
    import devotionals as dv
    import member_lumen_ui as lm
    nd = _the_day(dev, k)
    name = (nd.get("title") or "").strip() or f"Day {k}"
    if k <= st["upto"]:
        label = (f'{lm.ic("back", 13)}<span>Day {k}</span>' if which == "prev" else
                 f'<span>Day {k}</span>{lm.ic("chevron", 13)}')
        said = f'{"Previous" if which == "prev" else "Next"}: day {k}, {name}'
        return (f'<a class="lm-dd-step {which}" href="{_href(dev, k)}" aria-label="{_e(said)}"><small>{label}</small>'
                f'<b>{_e(name)}</b></a>')
    opens = ""
    if st["start"]:
        when = dv.day_on(st["start"], k)
        opens = " · tomorrow" if when == today + timedelta(days=1) else f" · {_day_date(when)}"
    return f'<div class="lm-dd-step {which} is-shut"><small><span>Day {k}{_e(opens)}</span></small><b>{_e(name)}</b></div>'


def render_day(biz, site, me, dev: Dict[str, Any], n: int, st: Dict[str, Any], mine: Optional[Dict[str, Any]], *,
               tr: str = "kjv", listen: bool = False, night: Optional[bool] = False, today: Optional[date] = None) -> str:
    """A devotional's day in the new look. `mine` is the member's own day
    (done, ticks, journal); None = it couldn't load, so nothing on the page
    can save. `night`: the reader's night cookie (dark, the same switch)."""
    import bible_text as bt
    import devotionals as dv
    import member_app_photos as photos
    import member_app_ui as ui
    import member_lumen_bible as mlb
    import member_lumen_ui as lm
    from member_portal import _shell
    today = today or date.today()
    day = _the_day(dev, n)
    live = mine is not None and not st["preview"]
    mine = mine or {}
    church = (biz.get("name") or "").strip()
    author = (dev.get("author") or "").strip()
    st = {**st, "here": n}
    name = (day.get("title") or "").strip() or f"Day {n}"
    dtitle = dev.get("title") or "Devotional"
    off = "" if live else " disabled"
    # The picture: the church's for this devotional, or a photo named for it;
    # in colour unless the church chose a look for it. None: the green alone.
    url, look = photos.choose(biz, f"devotional:{dev['id']}", photos.photos(biz, site), title=dtitle, look="colour")
    pic = f'<span class="lm-dd-ph">{ui.photo(url, look=look, eager=True)}</span>' if url else ""
    verse, label, link = scripture(day.get("scripture") or "", tr)
    share = f"{name}: {label} · {dtitle}" + (f", {church}" if church else "")
    btns = ""
    if listen:
        btns += (f'<button class="lm-dd-btn" id="dv-listen" type="button" aria-pressed="false">{_glyph("listen")}'
                 f'<span class="lm-dd-lw">Listen</span></button><audio id="dv-audio" preload="none"></audio>')
    btns += (f'<button class="lm-dd-btn ghost" id="dv-share" type="button" data-text="{_e(share)}">'
             f'{lm.ic("share", 16)}<span>Share</span></button>')
    who = author or church
    meta = " · ".join(p for p in (who, f"about {dv.minutes(day)} minutes") if p)
    hero = (f'<section class="lm-dd-hero{" has-ph" if pic else ""}" aria-labelledby="dv-h">{pic}<div class="lm-dd-plate">'
            f'<p class="lm-dd-k">{_e(dtitle)} · Day {n} of {st["count"]}</p>'
            f'<h1 class="lm-dd-t" id="dv-h">{lm.italic_last(name)}</h1><p class="lm-dd-m">{_e(meta)}</p>'
            f'{track(st, dev)}<div class="lm-dd-acts">{btns}</div></div></section>')
    note = ""
    if st["preview"]:
        note = (f'<p class="lm-dd-note">{ui.icon("lock", 14)}<span>This is a preview: the checklist, the journal and '
                f'Mark as read don\'t save here.</span></p>')
    elif not live:
        note = '<p class="mp-err" role="alert">Your day couldn\'t load just now, so nothing here will save. Please try again.</p>'
    scrip = ""
    if (day.get("scripture") or "").strip():
        read = (f'<a class="lm-dd-read" href="{_e(link)}">Read {_e(re.sub(r":.*$", "", label))}{lm.ic("chevron", 14)}</a>'
                if link else "")
        scrip = (f'<section class="lm-dd-scrip" aria-label="Today\'s scripture"><p class="lm-dd-lbl">{_e(label)}'
                 f'{" · " + _e(bt.TRANSLATIONS[tr]["short"]) if verse else ""}</p>'
                 + (f'<blockquote class="lm-dd-q">{verse}</blockquote>' if verse else "") + f'{read}</section>')
    body = "".join(f"<p>{_e(p)}</p>" for p in dv.paragraphs(day.get("body") or ""))
    pull = f'<p class="lm-dd-pull">{_e(day["pull"].strip())}</p>' if (day.get("pull") or "").strip() else ""
    question = (day.get("journal") or "").strip() or "What is God showing you today?"
    import member_portal_devotionals as mpd
    reflect = (f'<section aria-labelledby="lm-dd-rh"><h2 class="lm-dd-h" id="lm-dd-rh">Reflect</h2><div class="lm-dd-refl">'
               f'<p class="lm-dd-qn" id="lm-dd-qn">{_e(question)}</p><label class="mp-sr" for="dv-j">Your answer</label>'
               f'<textarea class="lm-dd-ta" id="dv-j" data-journal maxlength="{mpd.JOURNAL_MAX}" aria-describedby="lm-dd-qn" '
               f'placeholder="Write it down, then give it to God."{off}>{_e(mine.get("journal") or "")}</textarea>'
               f'<p class="lm-dd-priv">{ui.icon("lock", 13)}<span>Private to you. Only you can read it.</span>'
               f'<span class="lm-dd-saved" role="status" data-saved></span></p></div></section>')
    blocks = []
    for key, head, cls in (("pray", "Pray", "lm-dd-pray"), ("act", "Do today", "lm-dd-txt"),
                           ("together", "Together", "lm-dd-txt")):
        text = (day.get(key) or "").strip()
        if text:
            blocks.append(f'<section aria-labelledby="lm-dd-{key}"><h2 class="lm-dd-h" id="lm-dd-{key}">{head}</h2>'
                          f'<p class="{cls}">{_e(text)}</p></section>')
    checks = set(mine.get("checks") or [])
    practices = dev.get("practices") or []
    check = ""
    if practices:
        items = "".join(
            f'<button class="lm-dd-ci" type="button" data-key="{_e(p["key"])}" aria-pressed="{"true" if p["key"] in checks else "false"}"'
            f'{off}><span class="lm-dd-box">{ui.icon("check", 15)}</span><span class="lm-dd-ct"><b>{_e(p["title"])}</b>'
            f'{f"<span>{_e(p.get("sub"))}</span>" if p.get("sub") else ""}</span></button>' for p in practices)
        n_on = len([p for p in practices if p["key"] in checks])
        check = (f'<section aria-labelledby="lm-dd-ch" data-check><div class="lm-dd-hrow"><h2 class="lm-dd-h" id="lm-dd-ch">'
                 f'Your daily checklist</h2><span class="lm-dd-n" data-count>{n_on} of {len(practices)}</span></div>'
                 f'<div class="lm-dd-list">{items}</div></section>')
    done = bool(mine.get("done_at"))
    later = n < st["count"]
    if later:
        nd = (_the_day(dev, n + 1).get("title") or "").strip()
        what = f"Day {n + 1}" + (f", “{nd}”," if nd else "")
        if n + 1 <= st["upto"]:
            after = f"{what} is ready when you are."
        elif st["start"]:
            when = dv.day_on(st["start"], n + 1)
            after = f"{what} opens " + ("tomorrow morning." if when == today + timedelta(days=1) else f"{_day_date(when)}.")
        else:
            after = f"{what} opens tomorrow."
    else:
        after = "That's every day of it. Well done."
    streak = dv.streak(st["done"] | ({n} if done else set()), max(st["upto"], 1))
    donebox = (f'<div class="lm-dd-done"><button class="lm-dd-mark" type="button" data-act="done"{" hidden" if done else ""}{off}>'
               f'Mark day {n} as read</button>'
               f'<div class="lm-dd-card" data-donecard{"" if done else " hidden"}><span class="lm-dd-cko">{ui.icon("check", 18)}</span>'
               f'<span class="lm-dd-cw"><b>Day {n} is done.<span data-streak>{" " + in_a_row(streak) if streak > 1 else ""}</span></b>'
               f'<small>{_e(after)}</small><button class="lm-txtbtn lm-dd-undo" type="button" data-act="undo"{off}>Not done yet</button>'
               f'</span></div></div>')
    steps = ""
    if n > 1 or later:
        steps = (f'<nav class="lm-dd-nav" aria-label="The days before and after">'
                 f'{_step(dev, st, n - 1, "prev", today) if n > 1 else ""}'
                 f'{_step(dev, st, n + 1, "next", today) if later else ""}</nav>')
    aa = ('<button type="button" class="lm-aa" id="lm-dd-aa" aria-expanded="false" aria-controls="lm-dd-aa-panel" '
          'aria-label="Text size and font">Aa</button>')
    panel = ('<div class="bb-aa-panel lm-aapanel" id="lm-dd-aa-panel" hidden><div class="bb-aa-row"><span>Text size</span>'
             '<span class="bb-aa-btns"><button type="button" data-size="down" aria-label="Smaller text">A−</button>'
             '<button type="button" data-size="up" aria-label="Larger text">A+</button></span></div>'
             '<div class="bb-aa-row"><span>Font</span><span class="bb-aa-btns">'
             '<button type="button" data-font="serif" aria-pressed="true">Book</button>'
             '<button type="button" data-font="sans" aria-pressed="false">Clean</button></span></div></div>')
    moon = mlb.moon_button(GREEN, GREEN, night)
    mid = f'<span class="lm-dd-bt">{_e(dtitle)} · Day {n}</span>'
    page = f"""<a class="mb-back" href="{_href(dev)}">{ui.icon('back', 16)}{_e(dtitle[:28])}</a>
{panel}
<div id="dv-day" class="lm-dd" data-dev="{_e(dev['id'])}" data-day="{n}" data-live="{'1' if live else '0'}">
{hero}
{note}
{scrip}
<div class="lm-dd-body">{body}</div>
{pull}
{reflect}
{"".join(blocks)}
{check}
{donebox}
{steps}
</div>
<p class="lm-dd-toast" id="lm-dd-toast" role="status" hidden></p>"""
    return _shell(biz, site, name, page, tab="bible", who=me, bar=False,
                  lumen_bar=(mid, aa + moon + '<span class="lm-rprog" aria-hidden="true"></span>'),
                  lumen_reader=True, lumen_bar_colour=GREEN, script=DAY_JS + mlb.NIGHT_JS)


# Today's DAY_JS (member_portal_devotionals) on this markup: the checklist
# (rapid taps send one save), the journal saving itself, Mark as read and
# Not done yet, Listen, Share; plus Aa (the size and font, kept on the phone
# with the Bible reader's, 'bb-look').
DAY_JS = r"""<script>(function(){
var root=document.getElementById('dv-day');if(!root)return;
var dev=root.getAttribute('data-dev'),day=+root.getAttribute('data-day'),live=root.getAttribute('data-live')==='1';
var toast=document.getElementById('lm-dd-toast'),timer=null;
if(toast)document.body.appendChild(toast);
function say(t){if(!toast)return;toast.textContent=t;toast.hidden=false;clearTimeout(timer);timer=setTimeout(function(){toast.hidden=true;},2400);}
function send(change){var body=Object.assign({devotional:dev,day:day},change);
 return fetch('/my/bible/plans/day',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(body)})
 .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
 .catch(function(d){say(d&&d.error==='slow'?'That’s a lot at once. Wait a minute.':'That didn’t save. Try again.');return null;});}
var list=root.querySelector('[data-check]'),count=root.querySelector('[data-count]'),pending=null;
function ticked(){return Array.prototype.map.call(root.querySelectorAll('.lm-dd-ci[aria-pressed=true]'),function(b){return b.getAttribute('data-key');});}
if(list&&live)list.addEventListener('click',function(e){var b=e.target.closest('.lm-dd-ci');if(!b)return;
 var on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on?'true':'false');
 if(count)count.textContent=ticked().length+' of '+root.querySelectorAll('.lm-dd-ci').length;
 clearTimeout(pending);pending=setTimeout(function(){send({checks:ticked()});},500);});
var box=root.querySelector('[data-journal]'),note=root.querySelector('[data-saved]'),jt=null,last=box?box.value:'';
function keep(){if(!box||box.value===last)return;var v=box.value;if(note)note.textContent='Saving…';
 send({journal:v}).then(function(d){if(d){last=v;if(note)note.textContent='Saved';}else if(note){note.textContent='Not saved yet';}});}
if(box&&live){box.addEventListener('input',function(){clearTimeout(jt);jt=setTimeout(keep,1200);});box.addEventListener('blur',keep);}
var mark=root.querySelector('[data-act=done]'),undo=root.querySelector('[data-act=undo]'),card=root.querySelector('[data-donecard]'),
 here=root.querySelector('[data-here]'),W=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve'];
function shown(done){if(mark)mark.hidden=done;if(card){card.hidden=!done;card.classList.toggle('is-new',done);}
 if(here)here.classList.toggle('is-done',done);}
if(mark&&live)mark.addEventListener('click',function(){keep();mark.disabled=true;
 send({done:true}).then(function(d){mark.disabled=false;if(!d)return;shown(true);
  var s=card&&card.querySelector('[data-streak]');if(s)s.textContent=d.streak>1?' '+(W[d.streak]||d.streak)+' in a row.':'';
  if(undo)undo.focus();});});
if(undo&&live)undo.addEventListener('click',function(){send({done:false}).then(function(d){if(d){shown(false);if(mark)mark.focus();}});});
var lb=document.getElementById('dv-listen'),au=document.getElementById('dv-audio');
if(lb&&au){var lw=lb.querySelector('.lm-dd-lw');
 function words(t){if(lw)lw.textContent=t;}
 au.addEventListener('play',function(){lb.setAttribute('aria-pressed','true');words('Pause');});
 au.addEventListener('pause',function(){lb.setAttribute('aria-pressed','false');words(au.ended?'Listen again':'Play');});
 lb.addEventListener('click',function(){
  if(au.getAttribute('src')){if(au.paused){au.play().catch(function(){});}else{au.pause();}return;}
  lb.disabled=true;words('Getting it ready…');
  fetch('/my/bible/plans/listen',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({devotional:dev,day:day})})
  .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
  .then(function(d){lb.disabled=false;au.src=d.url;au.play().catch(function(){words('Play');});})
  .catch(function(d){lb.disabled=false;words('Listen');say(d&&d.error==='slow'?'That’s a lot at once. Wait a minute.':'Listen didn’t work just now. Try again in a minute.');});});}
var sh=document.getElementById('dv-share');
if(sh)sh.addEventListener('click',function(){var t=sh.getAttribute('data-text');
 if(navigator.share){navigator.share({text:t}).catch(function(){});}
 else if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){say('Copied to share');},function(){say('Copying was blocked');});}});
var aa=document.getElementById('lm-dd-aa'),panel=document.getElementById('lm-dd-aa-panel'),look='m|serif';
function setLook(size,font){root.classList.remove('sz-s','sz-l','f-sans');if(size&&size!=='m')root.classList.add('sz-'+size);
 if(font==='sans')root.classList.add('f-sans');
 if(panel)Array.prototype.forEach.call(panel.querySelectorAll('[data-font]'),function(b){
  b.setAttribute('aria-pressed',b.getAttribute('data-font')===(font==='sans'?'sans':'serif')?'true':'false');});}
try{look=localStorage.getItem('bb-look')||look;}catch(e){}
var lp=look.split('|');setLook(lp[0],lp[1]);
if(aa&&panel){aa.addEventListener('click',function(){panel.hidden=!panel.hidden;aa.setAttribute('aria-expanded',panel.hidden?'false':'true');});
 panel.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var p=look.split('|');
  if(b.getAttribute('data-size')){var o=['s','m','l'],i=o.indexOf(p[0]);if(i<0)i=1;
   i=Math.max(0,Math.min(2,i+(b.getAttribute('data-size')==='up'?1:-1)));p[0]=o[i];}
  if(b.getAttribute('data-font'))p[1]=b.getAttribute('data-font');
  look=p.join('|');setLook(p[0],p[1]);try{localStorage.setItem('bb-look',look);}catch(e){}});
 document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!panel.hidden){panel.hidden=true;aa.setAttribute('aria-expanded','false');aa.focus();}});}
})();</script>"""


# ─── the look ────────────────────────────────────────────────────────
# The one rich surface is the devotional's deep green (the card on the
# Bible tab, the day's bar and plate), with a hairline frame inside it.
# Everything else is calm: the ivory scripture card, the words in the
# reading face, leaf-green small capitals over each part, hairlines.
CSS = """
/* the devotional (member_lumen_devotional) */
body.lm{--dd-leaf:#2F7A4E;--dd-tint:var(--s1);}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm{--dd-tint:color-mix(in srgb,#2F7A4E 10%,var(--bg));}
}
""" + _dark("""
body.lm.lm-dark{--dd-leaf:#8ED3A2;}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm.lm-dark{--dd-tint:color-mix(in srgb,#2F7A4E 16%,var(--bg));}
}
body.lm.lm-dark .lm-dd-scrip{background:#1C1914;color:#E8DFCC;}
body.lm.lm-dark .lm-dd-lbl,body.lm.lm-dark .lm-dd-read{color:#BFA97C;}
body.lm.lm-dark .lm-devo{box-shadow:inset 0 0 0 1px rgba(189,227,194,.14);}
""") + """/* the Bible tab: today's devotional on top */
body.lm .lm-devo{position:relative;margin-top:22px;padding:20px 20px 22px;border-radius:26px;background:#10261C;color:#E3F1E5;overflow:hidden;}
body.lm .lm-devo::before{content:"";position:absolute;inset:8px;border:1px solid rgba(189,227,194,.25);border-radius:20px;pointer-events:none;}
body.lm .lm-devo-k{position:relative;margin:0;font:700 10.5px/1.3 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:#BDE3C2;}
body.lm .lm-devo-t{position:relative;margin:10px 0 0;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:38px;line-height:1.02;
  letter-spacing:var(--lm-dtr);font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);color:#fff;text-wrap:balance;}
body.lm .lm-devo-t em{font-style:italic;font-weight:var(--lm-iw);color:#BDE3C2;}
body.lm .lm-devo-m{position:relative;margin:8px 0 0;font:500 14px/1.4 var(--mb-ui);color:rgba(227,241,229,.82);}
body.lm .lm-devo-dots{position:relative;display:flex;flex-wrap:wrap;gap:4px;margin-top:14px;}
body.lm .lm-devo-dots i{width:7px;height:7px;border-radius:50%;background:rgba(189,227,194,.22);}
body.lm .lm-devo-dots i.d{background:#BDE3C2;}
body.lm .lm-devo-dots i.t{background:#10261C;box-shadow:0 0 0 2px #BDE3C2;}
body.lm .lm-devo-acts{position:relative;display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;}
body.lm .lm-devo-go{height:38px;padding:0 16px;border:0;border-radius:19px;background:#BDE3C2;color:#10261C;font:650 13.5px/1 var(--mb-ui);
  display:inline-flex;align-items:center;justify-content:center;gap:7px;text-decoration:none;cursor:pointer;white-space:nowrap;}
body.lm .lm-devo-go.ghost{background:rgba(255,255,255,.12);color:#fff;}
body.lm .lm-devo-go[aria-pressed=true]{background:rgba(189,227,194,.24);color:#fff;}
body.lm .lm-devo-go:disabled{opacity:.7;cursor:progress;}
body.lm .lm-devo-say{position:relative;margin:12px 0 0;font:500 13px/1.35 var(--mb-ui);color:#E3F1E5;}
body.lm .lm-devo-say[hidden]{display:none;}
/* a day: the bar and the plate wear the devotional's green */
body.lm:has(.lm-dd) .mb-top,body.lm:has(.lm-dd) .mb-top.is-solid{background:#10261C;color:#fff;box-shadow:none;}
body.lm:has(.lm-dd) .mb-top .mb-back{color:#fff;font-size:0;gap:0;}
body.lm:has(.lm-dd) .mb-top .lm-aa{color:#fff;}
body.lm:has(.lm-dd) .mb-top .lm-aa[aria-expanded=true],body.lm:has(.lm-dd) .mb-top .lm-moon[aria-pressed=true]{background:rgba(189,227,194,.16);color:#BDE3C2;}
body.lm:has(.lm-dd) .mb-top .lm-rprog{background:#BDE3C2;}
body.lm:has(.lm-dd) .lm-aapanel [aria-pressed=true]{background:var(--fg);color:var(--bg);}
body.lm .lm-dd-bt{display:block;max-width:min(54vw,300px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:650 15px/1.2 var(--mb-ui);color:#fff;}
body.lm .lm-dd-hero{position:relative;margin:0 -20px;background:#10261C;color:#fff;overflow:hidden;}
body.lm .lm-dd-ph{position:relative;display:block;height:212px;background:#0B1B14;}
body.lm .lm-dd-ph>.mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
body.lm .lm-dd-ph img{display:block;width:100%;height:100%;object-fit:cover;object-position:50% 30%;}
body.lm .lm-dd-plate{position:relative;padding:24px 20px 26px;}
body.lm .lm-dd-plate::before{content:"";position:absolute;inset:10px;border:1px solid rgba(189,227,194,.22);border-radius:18px;pointer-events:none;}
body.lm .lm-dd-k{position:relative;margin:0;font:650 11px/1.3 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:#BDE3C2;}
body.lm .lm-dd-t{position:relative;margin:10px 0 0;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:40px;line-height:1.03;
  letter-spacing:var(--lm-dtr);font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);color:#fff;text-wrap:balance;}
body.lm .lm-dd-t em{font-style:italic;font-weight:var(--lm-iw);color:#BDE3C2;}
body.lm .lm-dd-m{position:relative;margin:10px 0 0;font:500 14.5px/1.45 var(--mb-ui);color:rgba(227,241,229,.82);}
body.lm .lm-dd-track{position:relative;display:flex;flex-wrap:wrap;margin:12px 0 0 -8px;}
body.lm .lm-dd-track>a,body.lm .lm-dd-track>span{display:grid;place-items:center;width:24px;height:28px;border-radius:8px;}
body.lm .lm-dd-track i{display:block;width:8px;height:8px;border-radius:50%;background:rgba(189,227,194,.24);}
body.lm .lm-dd-track .is-done i{background:#BDE3C2;}
body.lm .lm-dd-track .is-here i{background:#10261C;box-shadow:0 0 0 2px #BDE3C2;}
body.lm .lm-dd-track .is-here.is-done i{background:#BDE3C2;box-shadow:0 0 0 2px #10261C,0 0 0 3.5px #BDE3C2;}
body.lm .lm-dd-track .is-shut i{background:rgba(189,227,194,.12);}
body.lm .lm-dd-track.is-many{gap:4px;margin-left:0;}
body.lm .lm-dd-track.is-many>span{width:7px;height:7px;}
body.lm .lm-dd-track.is-many i{width:7px;height:7px;}
body.lm .lm-dd-acts{position:relative;display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;}
body.lm .lm-dd-btn{height:40px;padding:0 16px;border:0;border-radius:20px;background:#BDE3C2;color:#10261C;font:650 14px/1 var(--mb-ui);
  display:inline-flex;align-items:center;gap:8px;cursor:pointer;white-space:nowrap;}
body.lm .lm-dd-btn.ghost{background:rgba(255,255,255,.12);color:#fff;}
body.lm .lm-dd-btn[aria-pressed=true]{background:rgba(189,227,194,.24);color:#fff;}
body.lm .lm-dd-btn:disabled{opacity:.7;cursor:progress;}
body.lm .lm-dd-note{display:flex;align-items:center;gap:8px;margin:18px 0 0;font:500 13px/1.4 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dd .mp-err{margin-top:18px;}
/* the scripture on the ivory card */
body.lm .lm-dd-scrip{margin:22px 0 0;padding:20px 20px 18px;border-radius:20px;background:var(--lm-paper);color:var(--lm-ink);}
body.lm .lm-dd-lbl{margin:0;font:700 10.5px/1.3 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:var(--lm-ink2);}
body.lm .lm-dd-q{margin:12px 0 0;font-family:var(--lm-read);font-style:italic;font-size:19px;line-height:1.5;}
body.lm .lm-dd-q i{font-style:normal;}
body.lm .lm-dd-read{display:inline-flex;align-items:center;gap:4px;margin-top:14px;font:650 13px/1 var(--mb-ui);color:var(--lm-ink2);text-decoration:none;}
/* the words, read like a book */
body.lm .lm-dd-body p{margin:20px 0 0;font-family:var(--lm-read);font-size:19px;line-height:1.74;hyphens:auto;color:var(--fg);}
body.lm .lm-dd-body p:first-child::first-letter{float:left;margin:6px 9px 0 0;font-family:var(--mb-serif);font-weight:var(--lm-dw);
  font-size:60px;line-height:.86;font-variation-settings:var(--lm-dvar);color:var(--dd-leaf);}
body.lm .lm-dd-pull{margin:26px 0 0;padding:2px 0 2px 16px;border-left:2px solid var(--dd-leaf);font-family:var(--lm-read);font-style:italic;
  font-size:21px;line-height:1.45;color:var(--fg);}
body.lm .lm-dd-h{margin:32px 0 0;font:700 11px/1.2 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:var(--dd-leaf);}
body.lm .lm-dd-refl{margin-top:12px;padding:18px;border-radius:20px;background:var(--dd-tint);}
body.lm .lm-dd-qn{margin:0;font-family:var(--lm-read);font-size:18px;line-height:1.55;color:var(--fg);}
body.lm .lm-dd-ta{display:block;box-sizing:border-box;width:100%;min-height:112px;margin-top:14px;padding:12px 14px;border:0;border-radius:14px;
  background:var(--bg);color:var(--fg);box-shadow:inset 0 0 0 1px var(--lm-line);font:400 16px/1.5 var(--mb-ui);resize:vertical;}
body.lm .lm-dd-ta::placeholder{color:var(--fg3);}
body.lm .lm-dd-ta:focus{outline:none;box-shadow:inset 0 0 0 1.5px var(--dd-leaf);}
body.lm .lm-dd-priv{display:flex;align-items:center;gap:6px;margin:10px 0 0;font:500 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dd-saved{margin-left:auto;}
body.lm .lm-dd-pray{margin:12px 0 0;font-family:var(--lm-read);font-style:italic;font-size:19px;line-height:1.7;color:var(--fg);}
body.lm .lm-dd-txt{margin:12px 0 0;font-family:var(--lm-read);font-size:18px;line-height:1.6;color:var(--fg);}
body.lm .lm-dd.sz-s .lm-dd-body p,body.lm .lm-dd.sz-s .lm-dd-pray{font-size:17px;}
body.lm .lm-dd.sz-s .lm-dd-txt,body.lm .lm-dd.sz-s .lm-dd-qn,body.lm .lm-dd.sz-s .lm-dd-q{font-size:16.5px;}
body.lm .lm-dd.sz-l .lm-dd-body p,body.lm .lm-dd.sz-l .lm-dd-pray{font-size:22px;}
body.lm .lm-dd.sz-l .lm-dd-txt,body.lm .lm-dd.sz-l .lm-dd-qn,body.lm .lm-dd.sz-l .lm-dd-q{font-size:20.5px;}
body.lm .lm-dd.f-sans .lm-dd-body p,body.lm .lm-dd.f-sans .lm-dd-pray,body.lm .lm-dd.f-sans .lm-dd-txt,body.lm .lm-dd.f-sans .lm-dd-qn,
body.lm .lm-dd.f-sans .lm-dd-q,body.lm .lm-dd.f-sans .lm-dd-pull{font-family:var(--mb-ui);}
/* the daily checklist */
body.lm .lm-dd-hrow{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-top:32px;}
body.lm .lm-dd-hrow .lm-dd-h{margin:0;}
body.lm .lm-dd-n{font:600 12.5px/1 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dd-list{margin-top:10px;border-top:1px solid var(--lm-line);}
body.lm .lm-dd-ci{display:flex;align-items:center;gap:14px;width:100%;padding:14px 0;border:0;border-bottom:1px solid var(--lm-line);background:none;
  color:var(--fg);text-align:left;font:inherit;cursor:pointer;}
body.lm .lm-dd-ci:disabled{cursor:default;}
body.lm .lm-dd-box{width:26px;height:26px;flex:none;border-radius:50%;display:grid;place-items:center;box-shadow:inset 0 0 0 1.5px var(--s3);
  color:transparent;}
body.lm .lm-dd-ci[aria-pressed=true] .lm-dd-box{background:#2F7A4E;box-shadow:none;color:#fff;}
body.lm .lm-dd-ct{flex:1;min-width:0;}
body.lm .lm-dd-ct b{display:block;font:650 15.5px/1.25 var(--mb-ui);}
body.lm .lm-dd-ct span{display:block;margin-top:3px;font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
/* mark the day as read */
body.lm .lm-dd-mark{display:flex;align-items:center;justify-content:center;width:100%;height:56px;margin-top:32px;border:0;border-radius:18px;
  background:#2F7A4E;color:#fff;font:650 16px/1 var(--mb-ui);cursor:pointer;}
body.lm .lm-dd-mark:disabled{opacity:.6;cursor:default;}
body.lm .lm-dd-card{display:flex;align-items:flex-start;gap:14px;margin-top:32px;padding:16px;border-radius:20px;background:var(--dd-tint);}
body.lm .lm-dd-mark[hidden],body.lm .lm-dd-card[hidden],body.lm .lm-dd-toast[hidden]{display:none;}
body.lm .lm-dd-cko{width:46px;height:46px;flex:none;border-radius:50%;display:grid;place-items:center;background:#2F7A4E;color:#fff;}
body.lm .lm-dd-cw{flex:1;min-width:0;padding-top:2px;}
body.lm .lm-dd-cw b{display:block;font:700 16px/1.25 var(--mb-ui);color:var(--fg);}
body.lm .lm-dd-cw small{display:block;margin-top:4px;font:500 13px/1.4 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dd-undo{margin:6px 0 0 -6px;padding:8px 6px;}
/* the days before and after */
body.lm .lm-dd-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:32px;border-top:1px solid var(--lm-line);
  border-bottom:1px solid var(--lm-line);}
body.lm .lm-dd-step{display:block;min-width:0;padding:16px 12px 16px 0;color:var(--fg);text-decoration:none;}
body.lm .lm-dd-step.next{grid-column:2;padding:16px 0 16px 12px;text-align:right;border-left:1px solid var(--lm-line);}
body.lm .lm-dd-step small{display:flex;align-items:center;gap:3px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;
  color:var(--fg3);}
body.lm .lm-dd-step.next small{justify-content:flex-end;}
body.lm .lm-dd-step b{display:-webkit-box;margin-top:6px;overflow:hidden;-webkit-line-clamp:2;-webkit-box-orient:vertical;font-family:var(--mb-serif);
  font-weight:var(--lm-dw);font-size:19px;line-height:1.2;letter-spacing:-.01em;font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);}
body.lm .lm-dd-step.is-shut b{color:var(--fg2);}
body.lm .lm-dd-toast{position:fixed;left:50%;bottom:calc(24px + env(safe-area-inset-bottom,0px));z-index:40;max-width:calc(100% - 40px);margin:0;
  padding:12px 16px;border-radius:14px;background:var(--fg);color:var(--bg);font:600 14px/1.3 var(--mb-ui);transform:translateX(-50%);
  box-shadow:0 10px 30px var(--lm-shadow);}
body.lm .lm-devo-go:focus-visible,body.lm .lm-dd-btn:focus-visible{outline:2px solid #BDE3C2;outline-offset:2px;}
body.lm .lm-dd-track>a:focus-visible{outline:2px solid #BDE3C2;outline-offset:0;}
body.lm .lm-dd-read:focus-visible,body.lm .lm-dd-ci:focus-visible,body.lm .lm-dd-mark:focus-visible,body.lm .lm-dd-step:focus-visible,
body.lm .lm-dd-undo:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm:has(.lm-dd){transition:background-color .5s ease,color .5s ease;}
  body.lm .lm-devo-go,body.lm .lm-dd-btn,body.lm .lm-dd-mark,body.lm .lm-dd-step{transition:transform .15s ease,background-color .25s ease;}
  body.lm .lm-devo-go:active,body.lm .lm-dd-btn:active,body.lm .lm-dd-mark:active{transform:scale(.97);}
  body.lm .lm-dd-box{transition:background-color .2s ease,box-shadow .2s ease,color .2s ease;}
  body.lm .lm-dd-card.is-new{animation:lm-ddarrive .6s cubic-bezier(.2,.8,.2,1) both;}
  body.lm .lm-dd-card.is-new .lm-dd-cko{animation:lm-ddpop .7s cubic-bezier(.34,1.56,.64,1) both;}
}
@keyframes lm-ddarrive{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes lm-ddpop{from{transform:scale(.4)}to{transform:none}}
"""
