"""member_lumen_plan_day.py — the day, one step at a time (Look 5.1 Plans, screen 3).

Kevin approved the Plans design (2026-11-21, "go ahead"). Its third screen is
the day: a bar with close, "Day N of M" and share; the steps READ ·
SCRIPTURE · ACT · PRAY · JOURNAL as segments; a strip of the days around this
one; then one step at a time, Back and Next at the foot, and on the last step
Mark the day done. Who sees it: member_lumen.py (MEMBER_LUMEN); off, every
page is today's, byte for byte.

  /my/bible/plans/<devotional>/<n>[?step=read|scripture|act|pray|journal]
      a church devotional's day. The steps come from the day's own words,
      leaving out any it doesn't have: READ (the line to hold on to and the
      day's words), SCRIPTURE (the passage, from the app's own Bible in the
      member's translation), ACT ("Today's step"), PRAY, JOURNAL (the day's
      question and the member's private note: devotional_progress.journal,
      which no staff route reads). The last step also carries the question
      for the member's group, the daily checklist and Mark day N done.
  /my/bible/plans/<reading or topic plan>/<n>
      a day of a plan of the member's own: its passages, read right there,
      and Mark day N done (the reading plans' own tick).

Without script every step is its own address (links), and saving is a form
(the journal and the checklist ride along with Mark done); with script the
steps switch in place, the journal saves itself and Mark done saves without
leaving the page, through the same routes (POST /my/bible/plans/day,
/my/reading).

Listen: a devotional's day is read aloud by the church's chosen reading voice
when the server can make it (devotional_voice: one reading per version of the
day, kept); otherwise, and on a plan's day, the phone reads it in its own
voice, as the Bible reader's Listen does (nothing is sent anywhere). A day
read by a voice the church recorded itself would need somewhere to keep that
recording; there is none, so the page never says "in the pastor's voice".

Reads: none of its own. A devotional's day uses today's reads (the
devotional, the member's start, their days); a plan's day the same kept
reads as the plan's page (member_lumen_plans).

The look is CSS (below), joined into the Lumen sheet by
member_lumen_ui.templates(); every rule sits under body.lm.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from member_lumen_ui import dark as _dark

STEPS = (("read", "Read"), ("scripture", "Scripture"), ("act", "Act"), ("pray", "Pray"), ("journal", "Journal"))
LABEL = dict(STEPS)
# The most verses the scripture step shows; the rest is a link to the chapter.
VERSES_MAX = 30
# The day strip: this many days either side of this one.
STRIP = 2
DEFAULT_QUESTION = "What is God showing you today?"


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def _short_date(d: date) -> str:
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}"


def steps_of(day: Dict[str, Any]) -> List[str]:
    """The day's steps, from its own words; an empty one is left out (a
    day with nothing at all still has its one page)."""
    def has(*keys: str) -> bool:
        return any((day.get(k) or "").strip() for k in keys)
    out = [k for k, on in (("read", has("pull", "body")), ("scripture", has("scripture")), ("act", has("act")),
                           ("pray", has("pray")), ("journal", has("journal"))) if on]
    return out or ["read"]


def _the_day(dev: Dict[str, Any], n: int) -> Dict[str, Any]:
    days = dev.get("days") or []
    return days[n - 1] if 1 <= n <= len(days) and isinstance(days[n - 1], dict) else {}


def passage(ref, tr: str, limit: int = VERSES_MAX) -> Tuple[str, bool]:
    """A passage's verses as the reader sets them (a verse to a line, its
    number small), at most `limit`; (html, cut short)."""
    import bible_text as bt
    import member_portal_bible as mpb
    verses = bt.verses(ref, tr) or []
    out = []
    for ch, v, t in verses[:limit]:
        num = f'<sup>{v if ch == ref.chapter or ref.end_chapter is None else f"{ch}:{v}"}</sup>'
        out.append(f'<span class="lm-dy-v">{num}{mpb._verse_html(t, tr)}</span>')
    return "".join(out), len(verses) > limit


def _strip(n: int, count: int, done: set, upto: int, href) -> str:
    """The days around this one as chips: read ones quiet, this one in the
    church's colour, one not open yet plain and not a link."""
    first, last = max(1, n - STRIP), min(count, n + STRIP)
    out = []
    for k in range(first, last + 1):
        cls = " ".join(c for c in ("ok" if k in done else "", "on" if k == n else "") if c)
        attr = f' class="{cls}"' if cls else ""
        said = f"Day {k}" + (", read" if k in done else "") + (", not open yet" if k > upto else "")
        if k == n:
            out.append(f'<span{attr} aria-current="page" aria-label="{_e(said)}">Day {k}</span>')
        elif k <= upto:
            out.append(f'<a{attr} href="{_e(href(k))}" aria-label="{_e(said)}">Day {k}</a>')
        else:
            out.append(f'<span class="shut" aria-label="{_e(said)}">Day {k}</span>')
    return f'<nav class="lm-dy-strip" aria-label="The days">{"".join(out)}</nav>'


def _segments(steps: List[str], cur: str, base: str) -> str:
    i = steps.index(cur)
    out = []
    for k, s in enumerate(steps):
        cls = "on" if s == cur else ("ok" if k < i else "")
        cur_attr = ' aria-current="step"' if s == cur else ""
        out.append(f'<a class="{cls}" href="{_e(base)}?step={s}" data-go="{s}"{cur_attr}>{LABEL[s]}</a>' if cls else
                   f'<a href="{_e(base)}?step={s}" data-go="{s}">{LABEL[s]}</a>')
    return f'<nav class="lm-dy-steps" aria-label="Steps">{"".join(out)}</nav>'


def _listen(kind: str) -> str:
    """Listen: kind "voice" (the church's reading voice, made once on the
    server) or "phone" (the phone's own voice; shown only by the script,
    where the phone can speak)."""
    import member_lumen_ui as lm
    hidden = " hidden" if kind == "phone" else ""
    sub = "Today's reading, read aloud" if kind == "voice" else "Read aloud by your phone"
    audio = '<audio id="dv-audio" preload="none"></audio>' if kind == "voice" else ""
    return (f'<button class="lm-dy-lis" id="dv-listen" type="button" data-kind="{kind}" aria-pressed="false"{hidden}>'
            f'<i aria-hidden="true">{lm.ic("playfill", 14)}</i><span><b class="lm-dy-lw">Listen</b><small>{_e(sub)}</small></span>'
            f'</button>{audio}')


def _foot(steps: List[str], cur: str, base: str, back_href: str, last_html: str) -> str:
    i = steps.index(cur)
    back = (f'<a class="lm-dy-b" href="{_e(base)}?step={steps[i - 1]}" data-go="{steps[i - 1]}">Back</a>' if i else
            f'<a class="lm-dy-b" href="{_e(back_href)}">Back</a>')
    if i < len(steps) - 1:
        nxt = steps[i + 1]
        go = f'<a class="lm-dy-b is-go" href="{_e(base)}?step={nxt}" data-go="{nxt}">Next: {LABEL[nxt]}</a>'
        return f'<div class="lm-dy-foot">{back}{go}</div>'
    return f'<div class="lm-dy-foot">{back}{last_html}</div>'


def render_day(biz: Dict[str, Any], site, me: Dict[str, Any], dev: Dict[str, Any], n: int, st: Dict[str, Any],
               mine: Optional[Dict[str, Any]], *, tr: str = "kjv", listen: bool = False, night: Optional[bool] = False,
               step: str = "", today: Optional[date] = None, flash: str = "",
               with_g: Optional[Dict[str, Any]] = None) -> str:
    """A church devotional's day in steps. `mine` is the member's own day
    (done, ticks, journal); None = it couldn't load, so nothing can save.
    `listen`: the church's reading voice can be made (else the phone's)."""
    import bible_text as bt
    import devotionals as dv
    import member_app_ui as ui
    import member_lumen_devotional as mld
    import member_lumen_ui as lm
    import member_portal_devotionals as mpd
    from member_portal import _shell
    today = today or date.today()
    day = _the_day(dev, n)
    live = mine is not None and not st["preview"]
    mine = mine or {}
    off = "" if live else " disabled"
    count, upto = st["count"], st["upto"]
    done_days = set(st["done"])
    done = bool(mine.get("done_at"))
    if done:
        done_days.add(n)
    else:
        done_days.discard(n)
    steps = steps_of(day)
    cur = step if step in steps else steps[0]
    base = f"/my/bible/plans/{dev['id']}/{n}"
    name = (day.get("title") or "").strip() or f"Day {n}"
    dtitle = dev.get("title") or "Devotional"
    church = (biz.get("name") or "").strip()
    panels: Dict[str, str] = {}
    say = '<h1 class="lm-dy-t">' + _e(name) + "</h1>"
    if "read" in steps:
        pull = (day.get("pull") or "").strip()
        body = "".join(f"<p>{_e(p)}</p>" for p in dv.paragraphs(day.get("body") or ""))
        panels["read"] = ((f'<p class="lm-dy-pull lm-dy-say">{_e(pull)}</p>' if pull else "")
                          + (f'<div class="lm-dy-body lm-dy-say">{body}</div>' if body else ""))
    if "scripture" in steps:
        text = day["scripture"].strip()
        found = bt.find_refs(text, tr)
        if found:
            cards = []
            for _, _, ref in found[:3]:
                words, cut = passage(ref, tr)
                more = (f'<a class="lm-dy-read" href="{_e(ref.href())}">Read {_e(re.sub(r":.*$", "", ref.label()))}'
                        f'{lm.ic("chevron", 14)}</a>')
                cards.append(f'<div class="lm-dy-scrip"><p class="lm-dy-k">{_e(ref.label())} · {_e(bt.TRANSLATIONS[tr]["short"])}'
                             f'</p><p class="lm-dy-vs lm-dy-say">{words}{"…" if cut else ""}</p>{more}</div>')
            panels["scripture"] = "".join(cards)
        else:
            panels["scripture"] = f'<div class="lm-dy-scrip"><p class="lm-dy-k">{_e(text)}</p></div>'
    if "act" in steps:
        panels["act"] = (f'<div class="lm-dy-act"><p class="lm-dy-k">Today\'s step</p>'
                         f'<p class="lm-dy-say">{_e(day["act"].strip())}</p></div>')
    if "pray" in steps:
        panels["pray"] = (f'<p class="lm-dy-k lm-dy-kp">Pray</p><p class="lm-dy-pray lm-dy-say">{_e(day["pray"].strip())}</p>')
    question = (day.get("journal") or "").strip() or DEFAULT_QUESTION
    journal = ""
    if "journal" in steps:
        journal = (f'<p class="lm-dy-q" id="lm-dy-qn">{_e(question)}</p><label class="mp-sr" for="dv-j">Your answer</label>'
                   f'<textarea class="lm-dy-ta" id="dv-j" name="journal" data-journal maxlength="{mpd.JOURNAL_MAX}" '
                   f'aria-describedby="lm-dy-qn" placeholder="Write it down, then give it to God."{off}>'
                   f'{_e(mine.get("journal") or "")}</textarea>'
                   f'<p class="lm-dy-priv">{ui.icon("lock", 13)}<span>Private to you. Only you can read it.</span>'
                   f'<span class="lm-dy-saved" role="status" data-saved></span></p>')
    # the last step: the group's question, the checklist, Mark done
    together = (day.get("together") or "").strip()
    send = ""
    if together and with_g and live:
        import member_plan_prefs as mpp
        send = mpp.send_button(with_g, together)
    group = (f'<div class="lm-dy-tog"><p class="lm-dy-k">For your group</p><p>{_e(together)}</p>{send}</div>'
             if together else "")
    checks = set(mine.get("checks") or [])
    practices = dev.get("practices") or []
    check = ""
    if practices:
        items = "".join(
            f'<label class="lm-dy-ci"><input type="checkbox" name="checks" value="{_e(p["key"])}" data-key="{_e(p["key"])}"'
            f'{" checked" if p["key"] in checks else ""}{off}><span class="lm-dy-box">{ui.icon("check", 14)}</span>'
            f'<span class="lm-dy-ct"><b>{_e(p["title"])}</b>{f"<small>{_e(p.get("sub"))}</small>" if p.get("sub") else ""}'
            f'</span></label>' for p in practices)
        n_on = len([p for p in practices if p["key"] in checks])
        check = (f'<fieldset class="lm-dy-check" data-check><legend class="lm-dy-k">Your daily checklist '
                 f'<span data-count>{n_on} of {len(practices)}</span></legend><input type="hidden" name="checks_in" value="1">'
                 f'{items}</fieldset>')
    streak = dv.streak(done_days, max(upto, 1))
    later = n < count
    if later:
        nd = (_the_day(dev, n + 1).get("title") or "").strip()
        what = f"Day {n + 1}" + (f", “{nd}”," if nd else "")
        if n + 1 <= upto:
            after = f'<a href="/my/bible/plans/{_e(dev["id"])}/{n + 1}">{_e(what)} is ready</a>'
        elif st["start"]:
            when = dv.day_on(st["start"], n + 1)
            after = _e(f"{what} opens " + ("tomorrow." if when == today + timedelta(days=1) else f"{_short_date(when)}."))
        else:
            after = _e(f"{what} opens tomorrow.")
    else:
        after = "That's every day of it. Well done."
    mark = (f'<button class="lm-dy-b is-go lm-dy-mark" type="submit" name="done" value="1" data-act="done"'
            f'{" hidden" if done else ""}{off}>Mark day {n} done</button>')
    card = (f'<div class="lm-dy-done" data-donecard{"" if done else " hidden"}><span class="lm-dy-cko">{ui.icon("check", 18)}</span>'
            f'<span class="lm-dy-cw"><b>Day {n} is done.<span data-streak>'
            f'{" " + mld.in_a_row(streak) if streak > 1 else ""}</span></b><small>{after}</small>'
            f'<button class="lm-txtbtn lm-dy-undo" type="submit" name="done" value="0" data-act="undo"{off}>Not done yet'
            f'</button></span></div>')
    save = ('<noscript><button class="lm-txtbtn lm-dy-save" type="submit" name="save" value="1">Save without marking '
            'it done</button></noscript>' if live and (journal or check) else "")
    last = steps[-1]
    form_open = (f'<form class="lm-dy-form" method="post" action="/my/bible/plans/day"><input type="hidden" name="devotional" '
                 f'value="{_e(dev["id"])}"><input type="hidden" name="day" value="{n}"><input type="hidden" name="step" '
                 f'value="{last}">')
    sections = []
    for s in steps:
        inner = panels.get(s, "")
        if s == steps[0] and listen is not None:
            inner = _listen("voice" if listen else "phone") + inner
        if s == "journal" and s != last:
            inner += journal
        if s == last:
            body_last = (journal if s == "journal" else "") + group + check + card + save
            foot = _foot(steps, s, base, f"/my/bible/plans/{dev['id']}", mark)
            sections.append(f'<section class="lm-dy-p" data-step="{s}" aria-label="{LABEL[s]}"{"" if s == cur else " hidden"}>'
                            f'{inner}{form_open}{body_last}{foot}</form></section>')
            continue
        foot = _foot(steps, s, base, f"/my/bible/plans/{dev['id']}", "")
        sections.append(f'<section class="lm-dy-p" data-step="{s}" aria-label="{LABEL[s]}"{"" if s == cur else " hidden"}>'
                        f'{inner}{foot}</section>')
    note = ""
    if st["preview"]:
        note = (f'<p class="lm-dy-note">{ui.icon("lock", 14)}<span>This is a preview: the journal, the checklist and '
                f'Mark done don\'t save here.</span></p>')
    elif not live:
        note = '<p class="mp-err" role="alert">Your day couldn\'t load just now, so nothing here will save. Please try again.</p>'
    share = f"{name}: {(day.get('scripture') or '').strip()} · {dtitle}" + (f", {church}" if church else "")
    share_btn = (f'<button class="lm-icb lm-dy-share" id="dv-share" type="button" aria-label="Share this day" '
                 f'data-text="{_e(share)}">{lm.ic("share", 21)}</button>')
    mid = f'<span class="lm-dy-bt">Day {n} of {count}</span>'
    page = (f'<a class="mb-back" href="/my/bible/plans/{_e(dev["id"])}">{ui.icon("back", 16)}Close</a>'
            f'<div id="dv-day" class="lm-dy" data-dev="{_e(dev["id"])}" data-day="{n}" data-live="{"1" if live else "0"}" '
            f'data-base="{_e(base)}">{_segments(steps, cur, base)}'
            f'{_strip(n, count, done_days, upto, lambda k: f"/my/bible/plans/{dev["id"]}/{k}")}'
            f'{flash}{note}<p class="lm-dy-kick">{_e(dtitle)}</p>{say}{"".join(sections)}</div>'
            f'<p class="lm-dd-toast" id="lm-dd-toast" role="status" hidden></p>')
    import member_lumen_bible as mlb
    return _shell(biz, site, name, page, tab="bible", who=me, bar=False, lumen_bar=(mid, share_btn),
                  lumen_reader=True, script=DAY_JS + mlb.NIGHT_JS)


# ─── a day of a reading or topic plan ────────────────────────────────


def render_plan_day(biz: Dict[str, Any], site, request: Any, me: Dict[str, Any], key: str, n: int,
                    plan: Dict[str, Any], done: Optional[set], *, tr: str = "kjv", preview: bool = False,
                    today: Optional[date] = None) -> str:
    """A day of a reading plan or a topic plan the member started: its
    passages, read right here, and Mark day N done (the reading plans' own
    route). `done` None: the days read couldn't be read, so nothing saves."""
    import bible_text as bt
    import member_app_ui as ui
    import member_lumen_plans as mlp
    import member_lumen_ui as lm
    import member_portal_reading as mpr
    import reading_plans as rp
    import topic_plans as tp
    from member_portal import _shell
    today = today or date.today()
    m = mlp.meta(key)
    count = m["count"]
    upto = rp.readable_upto(plan, today)
    live = done is not None and not preview
    days = set(done or set())
    read = n in days
    if tp.is_topic(key):
        refs = tp.day(key, n)["refs"]
        title = tp.day(key, n)["title"]
    else:
        refs = [bt.Ref(code, c) for code, a, b in rp.schedule(key)[n - 1] for c in range(a, b + 1)]
        title = mlp.day_label(key, n)
    cards = []
    for ref in refs:
        words, cut = passage(ref, tr, limit=200)
        cards.append(f'<section class="lm-dy-scrip is-plan"><h2 class="lm-dy-k">{_e(ref.label())} · '
                     f'{_e(bt.TRANSLATIONS[tr]["short"])}</h2><p class="lm-dy-vs lm-dy-say">{words}{"…" if cut else ""}</p>'
                     f'<a class="lm-dy-read" href="{_e(ref.href())}">Open in the Bible{lm.ic("chevron", 14)}</a></section>')
    base = f"/my/bible/plans/{key}/{n}"
    form = (f'<form method="post" action="/my/reading"><input type="hidden" name="day" value="{n}">'
            f'<input type="hidden" name="read" value="{"no" if read else "yes"}"><input type="hidden" name="back" value="{base}">'
            f'<input type="hidden" name="plan" value="{key}">')
    if not live:
        mark = ""
    elif read:
        streak = rp.streak(days, rp.day_number(plan, today) or n)
        nxt = (f'<a href="/my/bible/plans/{key}/{n + 1}">Day {n + 1} is ready</a>' if n < count and n + 1 <= upto else
               (_e(f"Day {n + 1} opens {_short_date(plan['start'] + timedelta(days=n))}.") if n < count else
                "That's every day of it. Well done."))
        mark = (f'{form}<div class="lm-dy-done"><span class="lm-dy-cko">{ui.icon("check", 18)}</span><span class="lm-dy-cw">'
                f'<b>Day {n} is done.{(" " + str(streak) + " days in a row.") if streak > 1 else ""}</b><small>{nxt}</small>'
                f'<button class="lm-txtbtn lm-dy-undo" type="submit">Not done yet</button></span></div></form>')
    else:
        mark = f'{form}<button class="lm-dy-b is-go lm-dy-mark" type="submit">Mark day {n} done</button></form>'
    prev = (f'<a class="lm-dy-b" href="/my/bible/plans/{key}/{n - 1}">Day {n - 1}</a>' if n > 1 else
            f'<a class="lm-dy-b" href="/my/bible/plans/{key}">Back</a>')
    nxt_link = (f'<a class="lm-dy-b" href="/my/bible/plans/{key}/{n + 1}">Day {n + 1}</a>' if n < count and n + 1 <= upto
                else "")
    note = ""
    if preview:
        note = (f'<p class="lm-dy-note">{ui.icon("lock", 14)}<span>This is a preview: Mark done doesn\'t save here.</span></p>')
    elif done is None:
        note = '<p class="mp-err" role="alert">Your days couldn\'t load just now, so nothing here will save. Please try again.</p>'
    share = f"{title}: {mlp.day_label(key, n)} · {m['title']}"
    share_btn = (f'<button class="lm-icb lm-dy-share" id="dv-share" type="button" aria-label="Share this day" '
                 f'data-text="{_e(share)}">{lm.ic("share", 21)}</button>')
    mid = f'<span class="lm-dy-bt">Day {n} of {count}</span>'
    page = (f'<a class="mb-back" href="/my/bible/plans/{key}">{ui.icon("back", 16)}Close</a>'
            f'<div id="dv-day" class="lm-dy is-plan" data-live="0">'
            f'{_strip(n, count, days, upto, lambda k: f"/my/bible/plans/{key}/{k}")}{mpr._flash(request)}{note}'
            f'<p class="lm-dy-kick">{_e(m["title"])}</p><h1 class="lm-dy-t">{_e(title)}</h1>'
            f'{_listen("phone")}{"".join(cards)}{mark}<div class="lm-dy-foot">{prev}{nxt_link}</div></div>'
            f'<p class="lm-dd-toast" id="lm-dd-toast" role="status" hidden></p>')
    import member_lumen_bible as mlb
    return _shell(biz, site, title, page, tab="bible", who=me, bar=False, lumen_bar=(mid, share_btn),
                  lumen_reader=True, script=DAY_JS + mlb.NIGHT_JS)


# The day's script. Steps switch in place (the address follows, the history
# isn't stacked); the journal saves itself; the checklist saves each tap;
# Mark done and Not done yet save without leaving the page (the form is the
# no-script way, through the same route); Listen plays the church's reading
# voice, or the phone reads the step aloud in its own voice; Share.
DAY_JS = r"""<script>(function(){
var root=document.getElementById('dv-day');if(!root)return;
var dev=root.getAttribute('data-dev'),day=+root.getAttribute('data-day'),live=root.getAttribute('data-live')==='1';
var toast=document.getElementById('lm-dd-toast'),timer=null;if(toast)document.body.appendChild(toast);
function say(t){if(!toast)return;toast.textContent=t;toast.hidden=false;clearTimeout(timer);timer=setTimeout(function(){toast.hidden=true;},2400);}
var panels=[].slice.call(root.querySelectorAll('.lm-dy-p')),order=panels.map(function(p){return p.getAttribute('data-step');});
function show(s){var i=order.indexOf(s);if(i<0)return false;
 panels.forEach(function(p,k){p.hidden=k!==i;});
 [].forEach.call(root.querySelectorAll('.lm-dy-steps a'),function(a){var k=order.indexOf(a.getAttribute('data-go'));
  a.className=k===i?'on':(k<i?'ok':'');if(k===i)a.setAttribute('aria-current','step');else a.removeAttribute('aria-current');});
 var calm=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;window.scrollTo({top:0,behavior:calm?'auto':'smooth'});
 stopVoice();return true;}
root.addEventListener('click',function(e){var a=e.target.closest?e.target.closest('a[data-go]'):null;
 if(!a||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
 if(show(a.getAttribute('data-go'))){e.preventDefault();try{history.replaceState(null,'',a.getAttribute('href'));}catch(x){}}});
function send(change){var body=Object.assign({devotional:dev,day:day},change);
 return fetch('/my/bible/plans/day',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(body)})
 .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
 .catch(function(d){say(d&&d.error==='slow'?'That’s a lot at once. Wait a minute.':'That didn’t save. Try again.');return null;});}
var box=root.querySelector('[data-journal]'),note=root.querySelector('[data-saved]'),jt=null,last=box?box.value:'';
function keep(){if(!box||!live||box.value===last)return;var v=box.value;if(note)note.textContent='Saving…';
 send({journal:v}).then(function(d){if(d){last=v;if(note)note.textContent='Saved';}else if(note){note.textContent='Not saved yet';}});}
if(box&&live){box.addEventListener('input',function(){clearTimeout(jt);jt=setTimeout(keep,1200);});box.addEventListener('blur',keep);}
var list=root.querySelector('[data-check]'),count=list?list.querySelector('[data-count]'):null,pending=null;
function ticked(){return [].map.call(root.querySelectorAll('[data-check] input[type=checkbox]:checked'),function(b){return b.value;});}
if(list&&live)list.addEventListener('change',function(){var n=root.querySelectorAll('[data-check] input[type=checkbox]').length;
 if(count)count.textContent=ticked().length+' of '+n;clearTimeout(pending);pending=setTimeout(function(){send({checks:ticked()});},500);});
var form=root.querySelector('.lm-dy-form'),mark=root.querySelector('[data-act=done]'),undo=root.querySelector('[data-act=undo]'),
 card=root.querySelector('[data-donecard]'),W=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve'];
function shown(done){if(mark)mark.hidden=done;if(card){card.hidden=!done;card.classList.toggle('is-new',done);}
 var here=root.querySelector('.lm-dy-strip [aria-current]');if(here)here.classList.toggle('ok',done);}
if(form&&live&&dev)form.addEventListener('submit',function(e){var b=e.submitter;if(!b||!b.getAttribute('data-act'))return;
 e.preventDefault();var done=b.getAttribute('data-act')==='done';keep();b.disabled=true;
 send({done:done}).then(function(d){b.disabled=false;if(!d)return;shown(done);
  var s=card&&card.querySelector('[data-streak]');if(s&&done)s.textContent=d.streak>1?' '+(W[d.streak]||d.streak)+' in a row.':'';
  var f=done?undo:mark;if(f)f.focus();});});
var lb=document.getElementById('dv-listen'),au=document.getElementById('dv-audio'),ss=window.speechSynthesis,on=false;
function words(t){var w=lb&&lb.querySelector('.lm-dy-lw');if(w)w.textContent=t;}
function stopVoice(){if(on&&ss){on=false;ss.cancel();if(lb){lb.setAttribute('aria-pressed','false');words('Listen');}}}
if(lb&&lb.getAttribute('data-kind')==='voice'&&au){
 au.addEventListener('play',function(){lb.setAttribute('aria-pressed','true');words('Pause');});
 au.addEventListener('pause',function(){lb.setAttribute('aria-pressed','false');words(au.ended?'Listen again':'Play');});
 lb.addEventListener('click',function(){
  if(au.getAttribute('src')){if(au.paused){au.play().catch(function(){});}else{au.pause();}return;}
  lb.disabled=true;words('Getting it ready…');
  fetch('/my/bible/plans/listen',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({devotional:dev,day:day})})
  .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
  .then(function(d){lb.disabled=false;au.src=d.url;au.play().catch(function(){words('Play');});})
  .catch(function(d){lb.disabled=false;words('Listen');say(d&&d.error==='slow'?'That’s a lot at once. Wait a minute.':'Listen didn’t work just now. Try again in a minute.');});});}
else if(lb&&ss&&window.SpeechSynthesisUtterance){lb.hidden=false;
 lb.addEventListener('click',function(){if(on){stopVoice();return;}
  var scope=root.querySelector('.lm-dy-p:not([hidden])')||root,parts=[].map.call(scope.querySelectorAll('.lm-dy-say'),function(el){
   var c=el.cloneNode(true);[].forEach.call(c.querySelectorAll('sup'),function(x){x.remove();});return c.textContent.replace(/\s+/g,' ').trim();})
   .filter(Boolean);if(!parts.length)return;on=true;lb.setAttribute('aria-pressed','true');words('Stop');ss.cancel();
  var i=0;(function next(){if(!on)return;if(i>=parts.length){stopVoice();return;}var u=new SpeechSynthesisUtterance(parts[i++]);u.lang='en-US';u.rate=.95;
   u.onend=function(){if(on)next();};u.onerror=function(ev){if(ev&&(ev.error==='interrupted'||ev.error==='canceled'))return;stopVoice();};ss.speak(u);})();});
 window.addEventListener('pagehide',stopVoice);}
var sh=document.getElementById('dv-share');
if(sh)sh.addEventListener('click',function(){var t=sh.getAttribute('data-text');
 if(navigator.share){navigator.share({text:t}).catch(function(){});}
 else if(navigator.clipboard){navigator.clipboard.writeText(t).then(function(){say('Copied to share');},function(){say('Copying was blocked');});}});
})();</script>"""


CSS = """
/* the day, in steps (member_lumen_plan_day) */
body.lm .lm-dy-bt{display:block;font:650 15px/1.2 var(--mb-ui);color:var(--fg);}
body.lm:has(.lm-dy) .mb-top .mb-back{font-size:0;gap:0;}
body.lm:has(.lm-dy) .mb-top .mb-back svg{display:none;}
body.lm:has(.lm-dy) .mb-top .mb-back::before{content:"";width:22px;height:22px;background:currentColor;
  -webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Cpath d='M18 6 6 18M6 6l12 12'/%3E%3C/svg%3E") center/contain no-repeat;
  mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Cpath d='M18 6 6 18M6 6l12 12'/%3E%3C/svg%3E") center/contain no-repeat;}
body.lm:has(.lm-dy) .mb-top .mb-back{color:var(--fg);}
body.lm .lm-dy-share{color:var(--fg);border:0;background:none;cursor:pointer;}
body.lm .lm-dy-steps{display:flex;gap:4px;margin-top:6px;}
body.lm .lm-dy-steps a{flex:1;min-width:0;display:grid;gap:6px;padding-bottom:4px;color:var(--fg2);text-align:center;text-decoration:none;
  font:650 10px/1.2 var(--mb-ui);letter-spacing:.06em;text-transform:uppercase;}
body.lm .lm-dy-steps a::before{content:"";height:3px;border-radius:3px;background:var(--s2);}
body.lm .lm-dy-steps a.ok::before{background:var(--acc-fill);}
body.lm .lm-dy-steps a.on{color:var(--fg);}
body.lm .lm-dy-steps a.on::before{background:linear-gradient(90deg,var(--acc-fill) 50%,var(--s2) 50%);}
body.lm .lm-dy-strip{display:flex;gap:6px;margin-top:12px;overflow-x:auto;scrollbar-width:none;}
body.lm .lm-dy-strip>*{flex:none;padding:7px 12px;border-radius:999px;box-shadow:inset 0 0 0 1px var(--lm-line);color:var(--fg2);
  text-decoration:none;font:650 12px/1 var(--mb-ui);}
body.lm .lm-dy-strip>.ok{color:var(--fg);}
body.lm .lm-dy-strip>.on{background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
body.lm .lm-dy-strip>.shut{opacity:.55;}
body.lm .lm-dy-kick{margin:20px 0 0;font:700 10.5px/1.3 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:var(--fg2);}
body.lm .lm-dy-t{margin:6px 0 0;font:700 17px/1.3 var(--mb-ui);color:var(--fg);}
body.lm .lm-dy-p[hidden]{display:none;}
body.lm .lm-dy-pull{margin:16px 0 0;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:25px;line-height:1.28;
  font-variation-settings:var(--lm-dvar);color:var(--fg);text-wrap:balance;}
body.lm .lm-dy-body p{margin:16px 0 0;font-family:var(--lm-read);font-size:18px;line-height:1.65;color:var(--fg);}
body.lm .lm-dy-k{margin:0;font:700 10.5px/1.3 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
body.lm .lm-dy-scrip{display:grid;gap:8px;margin-top:16px;padding:16px;border-radius:18px;background:var(--lm-tint);
  box-shadow:inset 0 0 0 1px var(--lm-ring);}
body.lm .lm-dy-vs{margin:0;font-family:var(--lm-read);font-size:18px;line-height:1.55;color:var(--fg);}
body.lm .lm-dy-vs i{font-style:italic;}
body.lm .lm-dy-v{display:block;}
body.lm .lm-dy-v+.lm-dy-v{margin-top:4px;}
body.lm .lm-dy-v sup{margin-right:4px;font:700 10px/1 var(--mb-ui);color:var(--fg3);vertical-align:.5em;}
body.lm .lm-dy-read{display:inline-flex;align-items:center;gap:4px;font:650 13px/1 var(--mb-ui);color:var(--acc);text-decoration:none;}
body.lm .lm-dy-lis{display:flex;align-items:center;gap:12px;width:100%;margin-top:16px;padding:10px 12px;border:0;border-radius:16px;
  background:var(--s1);color:var(--fg);text-align:left;font:inherit;cursor:pointer;}
body.lm .lm-dy-lis[hidden]{display:none;}
body.lm .lm-dy-lis i{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--acc-fill);
  color:var(--on-acc);}
body.lm .lm-dy-lis span{display:grid;gap:1px;}
body.lm .lm-dy-lis b{font:650 14px/1.2 var(--mb-ui);}
body.lm .lm-dy-lis small{font:500 12px/1.3 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dy-lis[aria-pressed=true] i{background:var(--fg);color:var(--bg);}
body.lm .lm-dy-lis:disabled{opacity:.7;cursor:progress;}
body.lm .lm-dy-act{display:grid;gap:6px;margin-top:16px;padding:6px 0 6px 14px;border-left:3px solid var(--lm-gold);}
body.lm .lm-dy-act .lm-dy-k{color:var(--lm-gold);}
body.lm .lm-dy-act p:last-child{margin:0;font:500 17px/1.5 var(--mb-ui);color:var(--fg);}
body.lm .lm-dy-kp{margin-top:18px;}
body.lm .lm-dy-pray{margin:10px 0 0;font-family:var(--lm-read);font-style:italic;font-size:19px;line-height:1.65;color:var(--fg);}
body.lm .lm-dy-q{margin:18px 0 0;font-family:var(--mb-serif);font-weight:var(--lm-dw);font-size:22px;line-height:1.25;
  font-variation-settings:var(--lm-dvar);color:var(--fg);}
body.lm .lm-dy-ta{display:block;box-sizing:border-box;width:100%;min-height:140px;margin-top:14px;padding:12px 14px;border:0;border-radius:14px;
  background:var(--s1);color:var(--fg);box-shadow:inset 0 0 0 1px var(--lm-line);font:400 16px/1.5 var(--mb-ui);resize:vertical;}
body.lm .lm-dy-ta::placeholder{color:var(--fg3);}
body.lm .lm-dy-ta:focus{outline:none;box-shadow:inset 0 0 0 1.5px var(--acc);}
body.lm .lm-dy-priv{display:flex;align-items:center;gap:6px;margin:10px 0 0;font:500 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dy-saved{margin-left:auto;}
body.lm .lm-dy-tog{display:grid;gap:6px;margin-top:20px;padding:14px;border-radius:16px;background:var(--s1);}
body.lm .lm-dy-tog p:last-child{margin:0;font:500 15.5px/1.45 var(--mb-ui);color:var(--fg);}
body.lm .lm-dy-send{justify-self:start;display:inline-flex;align-items:center;gap:7px;margin-top:6px;padding:9px 14px;border-radius:999px;
  background:var(--acc-fill);color:var(--on-acc);text-decoration:none;font:650 13.5px/1 var(--mb-ui);}
body.lm .lm-dy-send:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
body.lm .lm-dy-check{margin:22px 0 0;padding:0;border:0;}
body.lm .lm-dy-check legend{display:flex;justify-content:space-between;width:100%;padding:0;}
body.lm .lm-dy-check legend span{color:var(--fg2);letter-spacing:0;text-transform:none;font-weight:600;}
body.lm .lm-dy-ci{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--lm-line);color:var(--fg);cursor:pointer;}
body.lm .lm-dy-ci input{position:absolute;opacity:0;width:1px;height:1px;}
body.lm .lm-dy-box{width:26px;height:26px;flex:none;border-radius:50%;display:grid;place-items:center;box-shadow:inset 0 0 0 1.5px var(--s3);
  color:transparent;}
body.lm .lm-dy-ci input:checked+.lm-dy-box{background:#2F7A4E;color:#fff;box-shadow:none;}
body.lm .lm-dy-ci input:focus-visible+.lm-dy-box{outline:2px solid var(--acc);outline-offset:2px;}
body.lm .lm-dy-ct{display:grid;gap:2px;}
body.lm .lm-dy-ct b{font:650 15px/1.25 var(--mb-ui);}
body.lm .lm-dy-ct small{font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dy-done{display:flex;align-items:flex-start;gap:12px;margin-top:20px;padding:14px;border-radius:18px;background:var(--lm-tint);}
body.lm .lm-dy-done[hidden],body.lm .lm-dy-mark[hidden]{display:none;}
body.lm .lm-dy-cko{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;background:#2F7A4E;color:#fff;}
body.lm .lm-dy-cw{display:grid;gap:3px;}
body.lm .lm-dy-cw b{font:700 15.5px/1.3 var(--mb-ui);color:var(--fg);}
body.lm .lm-dy-cw small,body.lm .lm-dy-cw small a{font:500 13px/1.4 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dy-cw small a{color:var(--acc);text-decoration:none;}
body.lm .lm-dy-undo{justify-self:start;margin:2px 0 0 -6px;padding:6px;}
body.lm .lm-dy-save{display:block;margin:10px 0 0 -6px;padding:6px;}
body.lm .lm-dy-note{display:flex;align-items:center;gap:8px;margin:14px 0 0;font:500 13px/1.4 var(--mb-ui);color:var(--fg2);}
body.lm .lm-dy-foot{display:flex;gap:8px;margin-top:24px;}
body.lm .lm-dy-foot form{flex:1;display:flex;margin:0;}
body.lm .lm-dy-b{flex:1;display:inline-flex;align-items:center;justify-content:center;height:48px;padding:0 12px;border:0;border-radius:24px;
  background:none;box-shadow:inset 0 0 0 1px var(--lm-line);color:var(--fg);text-decoration:none;font:650 15px/1 var(--mb-ui);cursor:pointer;}
body.lm .lm-dy-b.is-go{background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
body.lm .lm-dy-b:disabled{opacity:.6;cursor:default;}
body.lm .lm-dy.is-plan .lm-dy-mark{width:100%;margin-top:22px;}
body.lm .lm-dy-steps a:focus-visible,body.lm .lm-dy-strip a:focus-visible,body.lm .lm-dy-b:focus-visible,body.lm .lm-dy-lis:focus-visible,
body.lm .lm-dy-read:focus-visible,body.lm .lm-dy-undo:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-dy-b,body.lm .lm-dy-lis{transition:transform .15s ease,background-color .2s ease;}
  body.lm .lm-dy-b:active,body.lm .lm-dy-lis:active{transform:scale(.97);}
  body.lm .lm-dy-p:not([hidden]){animation:lm-dyin .25s ease both;}
  body.lm .lm-dy-done.is-new{animation:lm-dyin .5s cubic-bezier(.2,.8,.2,1) both;}
}
@keyframes lm-dyin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
""" + _dark("""
body.lm.lm-dark .lm-dy-ci input:checked+.lm-dy-box,body.lm.lm-dark .lm-dy-cko{background:#3C8A5C;}
""")
