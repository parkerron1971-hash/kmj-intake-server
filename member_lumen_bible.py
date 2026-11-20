"""member_lumen_bible.py — the Bible in the member app's new look ("Lumen").

Kevin, 2026-11-18, on today's Bible tab: it "seems all over the place and
doesn't feel like a bible app ... needs more organization and feel of a top
tier bible app". He approved the "clean Lumen" mock (version 29, accent
level 2); this is its BIBLE and READER views, built on the data today's
pages read (member_portal_bible, member_portal_devotionals,
member_portal_reading, member_bible_marks). Who sees it: member_lumen.py
(MEMBER_LUMEN). Off, every page here is today's, byte for byte.

  /my/bible ......... "The Word": the translation switcher beside the
                      heading, today's devotional on top (Lumen Next:
                      member_lumen_devotional.card; the rail below keeps the
                      church's others), find a passage or a word, pick up where you
                      left off (a book spine), Today (the ivory verse card),
                      the church's devotionals as cards with progress dots,
                      reading plans (the church's, yours, the four to start),
                      your highlights and notes, the books.
  /my/bible/<b>/<n> . the reader: a plain bar (Bible · the chapter, which
                      opens the book picker · Aa), the chapter's number large
                      in gold, the text in a calm serif, the previous and
                      next chapter at the foot; tap a verse for the
                      highlighter. No tab bar while reading. Aa holds the
                      text size, the font and the translation.
  /my/bible/books, ?q=, /notes ... today's pages under the new heading.
  /my/bible/plans ... plans and devotionals, in the same cards.
  /my/reading ....... a reading plan: how far, this week, catch up.

Lumen Next (Kevin approved every moment of the Lumen Next mock, 2026-11-19)
adds to the reader: night reading (the moon beside Aa: dark and full-bleed,
kept in a cookie on the member's phone that the server reads, so the next
chapter arrives dark), a thin gold line of how far through the chapter you
are, a highlight that sweeps across the verse like ink, and Make a card
(the verse drawn on the phone in four looks, shared or saved; nothing is
sent anywhere). See READER_MORE_JS. A devotional's day reads at night by
the same moon and cookie (NIGHT_JS, member_lumen_devotional).

The mock's "Listen to this chapter" is not built (Kevin never approved
it). Nothing here is made up: a block with nothing real in it is left out.

The look is CSS (below), joined into the Lumen sheet by member_lumen_ui.css;
every rule sits under body.lm.
"""
from __future__ import annotations

import re
from datetime import date
from html import escape
from typing import Any, Dict, List, Optional, Sequence, Tuple

from member_lumen_ui import dark as _dark


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


# ─── small pieces ────────────────────────────────────────────────────


def trs(tr: str, here: str) -> str:
    """KJV · WEB · BSB · ASV, a link each, back to this page."""
    import bible_text as bt
    sep = "&" if "?" in here else "?"
    return ('<nav class="lm-trs" aria-label="Translation">' + "".join(
        f'<a href="{_e(here)}{sep}t={k}"{" aria-current=\"true\"" if k == tr else ""} title="{_e(v["name"])}">{_e(v["short"])}</a>'
        for k, v in bt.TRANSLATIONS.items()) + "</nav>")


def field(query: str = "", *, autofocus: bool = False) -> str:
    """Find a passage or a word: one quiet field; the glass is its button."""
    import member_lumen_ui as lm
    return (f'<form class="lm-field" method="get" action="/my/bible" role="search">'
            f'<button class="lm-field-go" type="submit" aria-label="Find">{lm.ic("search", 18)}</button>'
            f'<label class="mp-sr" for="bb-q">Find a passage or a word</label>'
            f'<input id="bb-q" name="q" value="{_e(query)}" maxlength="60" placeholder="Find a passage or a word" '
            f'autocomplete="off" enterkeyhint="search"{" autofocus" if autofocus else ""}></form>')


def _src(tr: str) -> str:
    import bible_text as bt
    return f'<p class="lm-src">{_e(bt.TRANSLATIONS[tr]["name"])} · public domain</p>'


def _short(biz: Dict[str, Any]) -> str:
    import member_portal_church as mpc
    return mpc._short_name(biz.get("name") or "") or "your church"


def continue_block(where: Optional[Tuple[str, int]], tr: str) -> str:
    """Pick up where you left off: the book as a spine, the chapter large.
    With nothing read yet, John 1."""
    import bible_text as bt
    import member_lumen_ui as lm
    import member_portal_bible as mpb
    code, ch = where if where else ("JOH", 1)
    kick = "Pick up where you left off" if where else "Start here"
    go = f"Continue reading · {bt.TRANSLATIONS[tr]['short']}" if where else "Start reading"
    return (f'<a class="lm-cont" href="/my/bible/{bt.slug(code)}/{ch}"><span class="lm-spine" aria-hidden="true">'
            f'<b>{_e(bt.NAME[code])}</b></span><span class="lm-cont-t"><span class="lm-kicker">{kick}</span>'
            f'<span class="lm-ct">{_e(mpb.where_label(code, ch))}</span>'
            f'<span class="lm-go">{_e(go)}{lm.ic("chevron", 15)}</span></span></a>')


# ─── devotionals and plans as cards ──────────────────────────────────

# The flat covers a devotional wears when the church gave it no picture
# (the mock's: peach with a sun, lavender with a moon, mint with a horizon).
COVERS = ("a", "b", "c")


def cover(biz: Dict[str, Any], dev: Dict[str, Any], pool: List[str], used: Optional[set], i: int,
          count: int) -> str:
    """A devotional's cover: the church's picture for it (or a photo named
    for it) with its title on it, else a flat cover in one of three quiet
    colours. "7 days" at the top."""
    import member_app_photos as photos
    import member_app_ui as ui
    url, look = photos.choose(biz, f"devotional:{dev['id']}", pool, title=dev.get("title") or "", look="church",
                              used=used)
    small = f"<small>{count} day{'' if count == 1 else 's'}</small>" if count else ""
    if url:
        return f'<span class="lm-cv has-ph">{ui.photo(url, look=look)}{small}<b>{_e(dev.get("title"))}</b></span>'
    return f'<span class="lm-cv cv-{COVERS[i % len(COVERS)]}">{small}<b>{_e(dev.get("title"))}</b></span>'


def dots(st: Dict[str, Any]) -> str:
    """How far, as short dashes: one a day up to seven; a longer one as
    seven, filled in proportion."""
    count = int(st.get("count") or 0)
    if not count:
        return ""
    done = len(st.get("done") or ())
    if count <= 7:
        marks = [n in st["done"] for n in range(1, count + 1)]
    else:
        on = round(7 * done / count)
        marks = [k < on for k in range(7)]
    return '<span class="lm-dots" aria-hidden="true">' + "".join(
        f'<i{" class=on" if m else ""}></i>' for m in marks) + "</span>"


def dev_words(dev: Dict[str, Any], st: Dict[str, Any]) -> Tuple[str, str]:
    """(the bold line, the quiet line) under a devotional's cover."""
    import devotionals as dv
    import member_portal_devotionals as mpd
    k = st["kind"]
    if k == "running":
        day = (dev.get("days") or [{}])[st["now"] - 1] if dev.get("days") else {}
        title = (day.get("title") or "").strip()
        bold = f"Day {st['now']} · {title}" if title else f"Day {st['now']} of {st['count']}"
        quiet = f"About {dv.minutes(day)} minutes" if day else (dev.get("kind") or "Devotional")
        return bold, quiet + (" · done" if st["now"] in st["done"] else "")
    if k == "new":
        bold = "Start any time"
    else:
        bold = mpd.chip(st)[0]
    quiet = f"By {dev['author']}" if dev.get("author") else (dev.get("kind") or "Devotional")
    return bold, quiet


def _sts(devs, done, mine, today, preview):
    import member_portal_devotionals as mpd
    return [(d, mpd.state(d, (mine or {}).get(f"devotional:{d['id']}"), (done or {}).get(str(d["id"]), set()), today,
                          preview=preview)) for d in (devs or [])]


def dev_rail(biz, site, sts) -> str:
    """The church's devotionals, running ones first, as cards in a rail."""
    import member_app_photos as photos
    import member_portal_devotionals as mpd
    if not sts:
        return ""
    pool = photos.photos(biz, site)
    used: set = set()
    ordered = [x for x in sts if x[1]["kind"] == "running"] + [x for x in sts if x[1]["kind"] != "running"]
    cards = []
    for i, (d, st) in enumerate(ordered[:8]):
        bold, quiet = dev_words(d, st)
        cards.append(f'<a class="lm-dev" href="{_e(mpd._target(d, st))}">{cover(biz, d, pool, used, i, st["count"])}'
                     f'{dots(st)}<span class="lm-dvt">{_e(bold)}</span><span class="lm-dvp">{_e(quiet)}</span></a>')
    return f'<div class="lm-rail lm-devs">{"".join(cards)}</div>'


def plan_title(title: str) -> str:
    """'The Gospels in 30 days' → 'The Gospels' (the days are said beside it)."""
    return re.sub(r"\s+in (\d+ days|a month)$", "", title or "") or title


def _ring(n: int, of: int, label: str) -> str:
    arc = round(119.4 * max(0, min(n, of)) / max(1, of), 1)
    return (f'<span class="lm-ring" aria-hidden="true"><svg viewBox="0 0 46 46"><circle cx="23" cy="23" r="19" fill="none" '
            f'stroke="var(--s2)" stroke-width="3.5"/><circle cx="23" cy="23" r="19" fill="none" stroke="var(--lm-gold)" '
            f'stroke-width="3.5" stroke-linecap="round" stroke-dasharray="{arc} 120"/></svg><b>{_e(label)}</b></span>')


def plan_rows(church_today: Optional[Dict[str, Any]], church_done: Optional[set], mine: Optional[Dict[str, date]],
              today: date) -> str:
    """Today's reading on the plans running for this member: the church's,
    then their own."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_devotionals as mpd
    import reading_plans as rp
    rows = []
    if church_today:
        t = church_today
        tag = ui.sample_tag() if samples.is_sample(t) else ""
        read = bool(church_done) and t["day"] in church_done
        rows.append(f'<a class="lm-prow" href="{_e(t["href"])}">{_ring(t["day"], t["of"], str(t["day"]))}'
                    f'<span class="lm-prow-t"><span class="lm-kicker lm-gk">The church is reading{tag}</span>'
                    f'<b>{_e(t["label"])}</b><span class="m">{_e(t["title"])} · day {t["day"]} of {t["of"]}'
                    f'{" · read today" if read else ""}</span></span>'
                    f'{lm.ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a>')
    for key, meta in rp.PLANS.items():
        plan = mpd.own_plan(key, (mine or {}).get(f"reading:{key}"))
        if not plan:
            continue
        now = rp.day_number(plan, today)
        if not now:
            continue
        reading = rp.schedule(key)[now - 1]
        rows.append(f'<a class="lm-prow" href="/my/bible/plans/{key}">{_ring(now, plan["days"], str(now))}'
                    f'<span class="lm-prow-t"><span class="lm-kicker lm-tk">Your plan</span>'
                    f'<b>{_e(rp.label(reading))}</b><span class="m">{_e(meta["title"])} · day {now} of {plan["days"]}</span></span>'
                    f'{lm.ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a>')
    return "".join(rows)


def plan_grid(mine: Optional[Dict[str, date]], today: date) -> str:
    """The four plans anyone can start, as panes: the days large in gold.
    One the member started says so and opens it; the others open the list
    where Start is."""
    import member_portal_devotionals as mpd
    import reading_plans as rp
    panes = []
    for key, meta in rp.PLANS.items():
        plan = mpd.own_plan(key, (mine or {}).get(f"reading:{key}"))
        if plan:
            now = rp.day_number(plan, today)
            tag = f'<em class="lm-yours">Yours · day {now}</em>' if now else '<em class="lm-yours">Yours</em>'
            href = f"/my/bible/plans/{key}"
        else:
            tag, href = "", "/my/bible/plans?show=reading"
        panes.append(f'<a class="lm-plan" href="{href}"><b>{meta["days"]}</b><small>days</small>'
                     f'<span>{_e(plan_title(meta["title"]))}</span>{tag}</a>')
    return f'<div class="lm-plans">{"".join(panes)}</div>'


def marks_block(marks: Optional[Sequence[Dict[str, Any]]], preview: bool) -> str:
    """Your highlights & notes: how many of each, a tap to see them."""
    import member_bible_marks as mbm
    import member_lumen_ui as lm
    if preview:
        return ""
    head = lm.section("Your highlights & notes", hid="lm-marks-h")
    if marks is None:
        return (f'<section aria-labelledby="lm-marks-h">{head}<p class="mp-err" role="alert">Your highlights and notes '
                f'couldn\'t load just now. They\'re still saved.</p></section>')
    if not marks:
        return (f'<section aria-labelledby="lm-marks-h">{head}<p class="lm-quiet">Tap any verse while you read to highlight '
                f'it, add a private note, or save it. They show up here.</p></section>')
    n = mbm.counts(marks)

    def one(k: int, word: str, cls: str) -> str:
        return f'<span><i class="{cls}"></i>{k} {word}{"" if k == 1 else "s"}</span>'
    return (f'<section aria-labelledby="lm-marks-h">{head}<a class="lm-marks" href="/my/bible/notes">'
            f'{one(n["highlights"], "highlight", "mk-hl")}{one(n["notes"], "note", "mk-note")}'
            f'<span><i class="mk-saved"></i>{n["bookmarks"]} saved</span>'
            f'{lm.ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a></section>')


BOOKS = ('<div class="lm-books">'
         '<a class="lm-book" href="/my/bible/books?t=ot"><b>Old Testament</b><span>39 books · Genesis to Malachi</span></a>'
         '<a class="lm-book" href="/my/bible/books?t=nt"><b>New Testament</b><span>27 books · Matthew to Revelation</span></a>'
         '</div>')


# ─── /my/bible ───────────────────────────────────────────────────────


def render_home(biz, site, me, tr: str, where, *, query: str = "", missed: bool = False, slow: bool = False,
                data: Optional[Dict[str, Any]] = None, church_today: Optional[Dict[str, Any]] = None,
                church_done: Optional[set] = None, marks: Optional[Sequence[Dict[str, Any]]] = (),
                preview: bool = False, today: Optional[date] = None) -> str:
    """The Bible tab. `data` is member_portal_devotionals.bible_home_data
    (None when it couldn't be read: the church's reading plan alone then,
    `church_today`/`church_done`, as today's page does)."""
    import member_lumen_ui as lm
    import member_portal_lumen as mlp
    from member_portal import _shell
    today = today or date.today()
    err = ('<p class="mp-err" role="alert">We couldn\'t find that passage or word. Try something like John 3:16, '
           'Psalm 23 or shepherd.</p>' if missed else
           '<p class="mp-err" role="alert">That\'s a lot of searching at once. Wait a minute, then try again.</p>'
           if slow else "")
    head = (f'<header class="lm-mast lm-bmast"><div class="lm-mastrow"><p class="lm-eyebrow">Bible</p>{trs(tr, "/my/bible")}</div>'
            f'<h1 class="lm-disp">The <em>Word</em></h1></header>')
    verse = mlp.verse_page(tr)
    today_html = f'<section aria-labelledby="lm-today-h">{lm.section("Today", hid="lm-today-h")}{verse}</section>' if verse else ""
    if data is not None:
        church_today, church_done = data.get("church_today"), data.get("church_done")
    mine = (data or {}).get("mine") or {}
    sts = _sts((data or {}).get("devs"), (data or {}).get("done"), mine, today, preview)
    # Lumen Next: today's devotional on top (member_lumen_devotional); the
    # rail below keeps the church's others.
    import member_lumen_devotional as mld
    devo, shown = "", None
    if sts:
        import devotional_voice as dvv
        devo, shown = mld.card(biz, sts, listen=dvv.can_speak())
    rail = dev_rail(biz, site, [x for x in sts if x[0] is not shown])
    devs_html = (f'<section aria-labelledby="lm-from-h">{lm.section(f"From {_short(biz)}", "/my/bible/plans", "All", hid="lm-from-h")}'
                 f'{rail}</section>') if rail else ""
    rows = plan_rows(church_today, church_done, mine, today)
    grid = plan_grid(mine, today) if data is not None else ""
    plans_html = ""
    if rows or grid:
        link = ("/my/bible/plans?show=reading", "See all") if data is not None else ("/my/reading", "See the plan")
        plans_html = (f'<section aria-labelledby="lm-plans-h">{lm.section("Reading plans", link[0], link[1], hid="lm-plans-h")}'
                      f'{f"<div class=lm-list>{rows}</div>" if rows else ""}{grid}</section>')
    books = f'<section aria-labelledby="lm-books-h">{lm.section("Books", hid="lm-books-h")}{BOOKS}</section>'
    body = (f'{head}{devo}{field(query)}{err}{continue_block(where, tr)}{today_html}{devs_html}{plans_html}'
            f'{marks_block(marks, preview)}{books}{_src(tr)}')
    return _shell(biz, site, "Bible", body, tab="bible", who=me,
                  script=mld.CARD_JS if "data-devo-listen" in devo else "")


# ─── the reader ──────────────────────────────────────────────────────


SWATCHES = ("gold", "pink", "teal", "violet", "coral")

# Lumen Next (Kevin approved every moment of the Lumen Next mock, 2026-11-19):
# the reader at night (dark and full-bleed; the phone keeps the choice in a
# cookie the server reads, so the page arrives dark with no flash), a thin
# line of how far through the chapter you are, a highlight that sweeps
# across the verse like ink, and a verse made into a card to share.
NIGHT_BG = "#100E0B"
NIGHT_COOKIE = "lm_night"
# the card's looks, in the mock's order: (key, label)
LOOKS = (("ivory", "Ivory"), ("photo", "Photo"), ("night", "Night"), ("church", "Church"))
_GLYPHS = {
    "moon": '<path d="M20.5 13.4A8.5 8.5 0 1 1 10.6 3.5a6.6 6.6 0 0 0 9.9 9.9z"/>',
    "card": '<rect x="5" y="2.5" width="14" height="19" rx="2.5"/><path d="M8.5 8.5c1.2-1.4 2.6-1.4 3.5 0s2.3 1.4 3.5 0"/>'
            '<path d="M8.5 15.5h7"/>',
}


def _glyph(name: str, size: int = 20) -> str:
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{_GLYPHS[name]}</svg>')


def card_sheet(biz: Dict[str, Any], site, photo: str, logo: str) -> str:
    """The "Make a card" sheet: the phone draws the verse on a canvas in one
    of four looks (ivory, a church photo, night, the church's colour) and
    shares or saves the picture. Nothing is sent anywhere. `photo` is the
    church's first photo ('' leaves the Photo look out); `logo` its logo
    ('' draws its initials)."""
    import member_app_ui as ui
    name = (biz.get("name") or "").strip() or "Your church"
    looks = "".join(
        f'<button type="button" role="radio" aria-checked="{"true" if k == "ivory" else "false"}" data-look="{k}">{label}</button>'
        for k, label in LOOKS if k != "photo" or photo)
    return f"""<div class="lm-vc" id="lm-vc" hidden data-church="{_e(name)}" data-mark="{_e(ui.initials(name))}" data-logo="{_e(logo)}" data-photo="{_e(photo)}">
  <div class="lm-vc-scrim" data-vc="close"></div>
  <div class="lm-vc-sheet" role="dialog" aria-modal="true" aria-labelledby="lm-vc-t">
    <span class="lm-vc-grab" aria-hidden="true"></span>
    <div class="lm-vc-h"><b id="lm-vc-t">Make a card</b><button type="button" class="bb-x" data-vc="close" aria-label="Close">{ui.icon('plus', 18)}</button></div>
    <canvas class="lm-vc-cv" width="1080" height="1350" role="img" aria-label="Your verse card"></canvas>
    <div class="lm-vc-looks" role="radiogroup" aria-label="How the card looks">{looks}</div>
    <div class="lm-vc-go"><button type="button" class="lm-btn ghost" data-vc="save">Save image</button><button type="button" class="lm-btn" data-vc="share">Share</button></div>
    <p class="lm-vc-priv">Made on your phone. Nothing is sent anywhere until you share it.</p>
  </div>
</div>"""


def render_chapter(biz, site, me, code: str, ch: int, tr: str, rng=None,
                   marks: Optional[Dict[int, Dict[str, Any]]] = None, preview: bool = False,
                   night: Optional[bool] = False) -> str:
    """Reading a chapter: the same reader (member_portal_bible.READER_JS:
    tap a verse to highlight it, add a note, copy, share or save it; Aa),
    laid out calm: no tab bar, the chapter's number large, the chapters
    before and after floating at the foot. Lumen Next adds the moon in the
    bar (night reading: `night` whether the page arrives at night,
    member_lumen_look.reader_night; None when the phone decides), the line
    of how far you've read, the ink sweep and Make a card
    (READER_MORE_JS)."""
    import json
    import bible_text as bt
    import member_app_photos as photos
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_bible as mpb
    from member_portal import _shell
    from public_form_theme import resolve_theme
    prev, nxt = bt.neighbours(code, ch, tr)
    name = "Psalm" if code == "PSA" else bt.NAME[code]
    here = f"/my/bible/{bt.slug(code)}/{ch}"
    editable = marks is not None and not preview
    found = {str(v): {"colour": m.get("colour"), "note": m.get("note"), "bookmarked": bool(m.get("bookmarked"))}
             for v, m in (marks or {}).items()}
    swatches = "".join(f'<button type="button" class="bb-sw sw-{c}" data-colour="{c}" aria-pressed="false" '
                       f'aria-label="Highlight {c}"></button>' for c in SWATCHES)
    dock = "" if not editable else f"""<div class="bb-dock" id="bb-dock" role="group" aria-label="This verse" hidden>
  <div class="bb-dock-h"><strong class="bb-dock-ref"></strong><button type="button" class="bb-x" data-act="close" aria-label="Close">{ui.icon('plus', 18)}</button></div>
  <div class="bb-dock-acts">
    <div class="bb-sws">{swatches}<button type="button" class="mp-link bb-clear" data-act="clear" hidden>Remove</button></div>
    <div class="bb-acts">
      <button type="button" data-act="note">{lm.ic('doc', 16)}<span>Note</span></button>
      <button type="button" data-act="copy">{lm.ic('share', 16)}<span>Copy</span></button>
      <button type="button" class="lm-share" data-share-kind="verse" data-share-from="reader">{lm.ic('out', 16)}<span>Share</span></button>
      <button type="button" data-act="bookmark" aria-pressed="false">{lm.ic('star', 16)}<span>Save</span></button>
      <button type="button" data-act="card" aria-haspopup="dialog">{_glyph('card', 16)}<span>Make a card</span></button>
    </div>
  </div>
  <div class="bb-note" id="bb-note" hidden>
    <p class="bb-note-v"></p>
    <label class="mp-sr" for="bb-note-in">Your note</label>
    <textarea class="mp-input bb-note-in" id="bb-note-in" maxlength="2000" placeholder="What is God showing you here?"></textarea>
    <p class="bb-priv">{ui.icon('lock', 14)}Private to you. It follows you to any phone you sign in on.</p>
    <button type="button" class="mp-go" data-act="save-note">Save note</button>
  </div>
</div>
<p class="bb-toast" id="bb-toast" role="status" hidden></p>"""
    theme = resolve_theme(biz, site)
    pool = photos.photos(biz, site)
    sheet = card_sheet(biz, site, pool[0] if pool else "", theme.get("logo_url") or "") if editable else ""
    day = ui.palette(biz, theme)["bg"]
    moon = moon_button(day, NIGHT_BG, night)
    prog = '<span class="lm-rprog" aria-hidden="true"></span>'
    note = ('<p class="mp-muted bb-pv">Highlights and notes are private, so a preview doesn\'t show them.</p>'
            if preview else ('<p class="mp-err" role="alert">Your highlights couldn\'t load just now. Reading still works.</p>'
                             if marks is None else ""))
    data = json.dumps(found).replace("</", "<\\/")
    pill = f'<a class="lm-pill" href="/my/bible/{bt.slug(code)}">{_e(name)} {ch}{lm.ic("down", 15)}</a>'
    aa = ("" if not editable else
          '<button type="button" class="lm-aa" id="bb-aa" aria-expanded="false" aria-controls="bb-aa-panel" '
          'aria-label="Text size, font and translation">Aa</button>')
    panel = ("" if not editable else
             '<div class="bb-aa-panel lm-aapanel" id="bb-aa-panel" hidden><div class="bb-aa-row"><span>Text size</span>'
             '<span class="bb-aa-btns"><button type="button" data-size="down" aria-label="Smaller text">A−</button>'
             '<button type="button" data-size="up" aria-label="Larger text">A+</button></span></div>'
             '<div class="bb-aa-row"><span>Font</span><span class="bb-aa-btns"><button type="button" data-font="serif">Book</button>'
             '<button type="button" data-font="sans">Clean</button></span></div>'
             f'<div class="bb-aa-row"><span>Translation</span>{trs(tr, here)}</div></div>')

    def step(to, cls: str) -> str:
        if not to:
            return "<span></span>"
        c, n = to
        label = mpb.where_label(c, n)
        inner = (f'{lm.ic("back", 15)}<span>{_e(label)}</span>' if cls == "prev" else
                 f'<span>{_e(label)}</span>{lm.ic("chevron", 15)}')
        return f'<a class="lm-chstep {cls}" href="/my/bible/{bt.slug(c)}/{n}" aria-label="{"Previous" if cls == "prev" else "Next"}: {_e(label)}">{inner}</a>'
    book = "Psalms" if code == "PSA" else bt.NAME[code]
    head = (f'<h1 class="lm-chap"><span class="mp-sr">{_e(name)} {ch}</span><b aria-hidden="true">{ch}</b>'
            f'<span aria-hidden="true">{_e(book)} · {_e(bt.TRANSLATIONS[tr]["short"])}</span></h1>')
    foot = _src(tr) + ("" if editable else f'<div class="lm-trfoot">{trs(tr, here)}</div>')
    body = f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
{panel}
{head}
{note}
<div class="bb-read lm-read" data-book="{code}" data-ch="{ch}" data-tr="{tr}" data-label="{_e(name)} {ch}">
{mpb.chapter_html(code, ch, tr, rng, marks=marks if editable else None)}
</div>
{foot}
<nav class="lm-chnav" aria-label="Chapters">{step(prev, "prev")}{step(nxt, "next")}</nav>
{dock}
{sheet}
<script type="application/json" id="bb-marks">{data}</script>"""
    return _shell(biz, site, f"{name} {ch}", body, tab="bible", who=me, bar=False,
                  lumen_bar=(pill, aa + moon + prog), lumen_reader=True,
                  script=(mpb.READER_JS if editable else "") + READER_MORE_JS)


def moon_button(day: str, night_bg: str, night: Optional[bool]) -> str:
    """The moon in the reader's bar: pressed when the page arrives at night
    (`night`; None: the phone decides, and the script reads it). It carries
    the member's look when that isn't Light (data-look: the script clears
    the moon's cookie when the moon lands where the look would anyway)."""
    import member_lumen_look as mll
    look = mll.here()
    said = f' data-look="{look}"' if look != "light" else ""
    return (f'<button type="button" class="lm-aa lm-moon" id="lm-moon" aria-pressed="{"true" if night else "false"}" '
            f'aria-label="Night reading" data-day="{_e(day)}" data-night="{night_bg}"{said}>{_glyph("moon", 19)}</button>')


# The reader's Lumen Next moments, beside today's reader script (which it
# leaves alone): the moon (night reading: the body's class, the phone's bar
# colour, and a cookie on /my the server reads next time), the line of how
# far you've read, and Make a card (the selected verse drawn on a canvas,
# 1080×1350, in one of four looks; Share hands the picture to the phone,
# Save downloads it; a picture from another site that won't let the canvas
# read it is left out rather than spoiling the card).
# The moon and the line are their own part (_NIGHT), so a devotional's day
# (member_lumen_devotional) reads at night by the same switch: NIGHT_JS.
_NIGHT = r"""
var B=document.body,moon=document.getElementById('lm-moon'),nQ=window.matchMedia?matchMedia('(prefers-color-scheme: dark)'):null;
function nPhone(){return !!(nQ&&nQ.matches);}
function nLook(){var l=moon?moon.getAttribute('data-look'):'';return l==='dark'||(l==='auto'&&nPhone());}
function nDark(){return B.classList.contains('lm-dark')||(B.classList.contains('lm-auto')&&nPhone());}
function night(on){B.classList.remove('lm-auto');B.classList.toggle('lm-dark',on);
 if(moon){moon.setAttribute('aria-pressed',on?'true':'false');var c=moon.getAttribute(on?'data-night':'data-day');
  [].forEach.call(document.querySelectorAll('meta[name="theme-color"]'),function(m){m.setAttribute('content',c);});}
 var v=on===nLook()?'':(on?'1':'0');
 try{document.cookie='lm_night='+(v?v+'; Max-Age=31536000':'; Max-Age=0')+'; Path=/my; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');}catch(e){}}
if(moon){moon.setAttribute('aria-pressed',nDark()?'true':'false');moon.addEventListener('click',function(){night(!nDark());});
 if(nQ&&nQ.addEventListener)nQ.addEventListener('change',function(){moon.setAttribute('aria-pressed',nDark()?'true':'false');});}
var line=document.querySelector('.lm-rprog'),queued=false;
function far(){queued=false;var h=document.documentElement.scrollHeight-window.innerHeight;
 line.style.transform='scaleX('+(h>0?Math.max(0,Math.min(1,window.scrollY/h)):0).toFixed(4)+')';}
if(line){window.addEventListener('scroll',function(){if(!queued){queued=true;requestAnimationFrame(far);}},{passive:true});
 window.addEventListener('resize',far);far();}
"""
_CARD = r"""var vc=document.getElementById('lm-vc'),read=document.querySelector('.bb-read');if(!vc||!read)return;
// out of the page's layer, above the verse dock and the bar
document.body.appendChild(vc);
var cv=vc.querySelector('canvas'),cx=cv.getContext('2d'),W=1080,H=1350,P=96;
var look='ivory',verse='',ref='',back=null,blob=null,photo=null,logo=null,asked=false,gen=0;
var tr=(read.getAttribute('data-tr')||'').toUpperCase(),church=vc.getAttribute('data-church')||'',mark=vc.getAttribute('data-mark')||'';
var toast=document.getElementById('bb-toast'),tt=null;
function say(t){if(!toast)return;toast.textContent=t;toast.hidden=false;clearTimeout(tt);tt=setTimeout(function(){toast.hidden=true;},1800);}
function prop(n,d){var v=getComputedStyle(B).getPropertyValue(n).trim();return v||d;}
function load(src,done){if(!src){done(null);return;}var i=new Image();i.crossOrigin='anonymous';
 i.onload=function(){done(i);};i.onerror=function(){done(null);};i.src=src;}
function pick(){vc.querySelectorAll('[data-look]').forEach(function(b){b.setAttribute('aria-checked',b.getAttribute('data-look')===look?'true':'false');});}
function drop(k){var b=vc.querySelector('[data-look="'+k+'"]');if(!b)return;if(look===k){look='ivory';}b.remove();pick();}
function art(){if(asked)return;asked=true;
 load(vc.getAttribute('data-photo'),function(i){photo=i;if(!i)drop('photo');if(!vc.hidden)draw();});
 load(vc.getAttribute('data-logo'),function(i){logo=i;if(!vc.hidden)draw();});}
function textOf(s){var c=s.cloneNode(true);c.querySelectorAll('sup,.bb-nm,.bb-bm').forEach(function(x){x.remove();});
 return c.textContent.replace(/\s+/g,' ').trim();}
function wrap(t,max){var w=t.split(' '),out=[],ln='';
 for(var i=0;i<w.length;i++){var s=ln?ln+' '+w[i]:w[i];if(ln&&cx.measureText(s).width>max){out.push(ln);ln=w[i];}else{ln=s;}}
 if(ln)out.push(ln);return out;}
function tracked(t,x,y,sp){for(var i=0;i<t.length;i++){cx.fillText(t[i],x,y);x+=cx.measureText(t[i]).width+sp;}}
function fit(t,max){if(cx.measureText(t).width<=max)return t;while(t.length>1&&cx.measureText(t+'…').width>max)t=t.slice(0,-1);return t+'…';}
function cover(img){var r=Math.max(W/img.naturalWidth,H/img.naturalHeight),w=img.naturalWidth*r,h=img.naturalHeight*r;
 cx.drawImage(img,(W-w)/2,(H-h)*0.35,w,h);}
function draw(){var serif=prop('--mb-serif','Georgia,serif'),ui=prop('--mb-ui','system-ui,sans-serif');
 var acc=prop('--acc-fill','#333333'),on=prop('--on-acc','#FFFFFF'),bg='#F7F0E1',fg='#22190B',sub='#6A5426';
 if(look==='night'){bg='#0F0E12';fg='#EFE7D6';sub='rgba(239,231,214,.66)';}
 else if(look==='church'){bg=acc;fg=on;sub=on;}
 else if(look==='photo'){bg='#120D08';fg='#FFFFFF';sub='rgba(255,255,255,.8)';}
 cx.setTransform(1,0,0,1,0,0);cx.globalCompositeOperation='source-over';cx.globalAlpha=1;cx.textAlign='left';cx.textBaseline='alphabetic';
 cx.fillStyle=bg;cx.fillRect(0,0,W,H);
 if(look==='photo'&&photo){cover(photo);
  cx.globalCompositeOperation='saturation';cx.fillStyle='#000';cx.fillRect(0,0,W,H);
  cx.globalCompositeOperation='multiply';cx.globalAlpha=.35;cx.fillStyle='#C99A4A';cx.fillRect(0,0,W,H);
  cx.globalAlpha=1;cx.globalCompositeOperation='source-over';
  var g=cx.createLinearGradient(0,0,0,H);g.addColorStop(0,'rgba(18,13,8,.64)');g.addColorStop(.5,'rgba(18,13,8,.46)');g.addColorStop(1,'rgba(18,13,8,.88)');
  cx.fillStyle=g;cx.fillRect(0,0,W,H);}
 if(look==='church'){cx.globalAlpha=.08;cx.fillStyle=on;cx.beginPath();cx.arc(W*.96,H*.02,300,0,Math.PI*2);cx.fill();cx.globalAlpha=1;}
 var size=96,lines=[],lh=0,room=H-2*P-230,max=W-2*P;
 for(;size>=34;size-=2){cx.font='italic 400 '+size+'px '+serif;lines=wrap(verse,max);lh=Math.round(size*1.3);if(lines.length*lh<=room)break;}
 cx.fillStyle=fg;var y=P+size;for(var i=0;i<lines.length;i++){cx.fillText(lines[i],P,y);y+=lh;}
 var r=48,mx=W-P-r,my=H-P-r+4,fy=H-P-56;
 cx.font='700 30px '+ui;tracked((ref+(tr?'  ·  '+tr:'')).toUpperCase(),P,fy,4.2);
 cx.fillStyle=sub;cx.font='500 28px '+ui;cx.fillText(fit(church,mx-r-32-P),P,fy+48);
 cx.save();cx.beginPath();cx.arc(mx,my,r,0,Math.PI*2);cx.closePath();
 if(logo){cx.fillStyle='#FFFFFF';cx.fill();cx.clip();var s=Math.min(r*1.45/logo.naturalWidth,r*1.45/logo.naturalHeight);
  cx.drawImage(logo,mx-logo.naturalWidth*s/2,my-logo.naturalHeight*s/2,logo.naturalWidth*s,logo.naturalHeight*s);}
 else{cx.fillStyle=look==='church'?'#FFFFFF':acc;cx.fill();cx.fillStyle=look==='church'?acc:on;cx.font='700 34px '+ui;
  cx.textAlign='center';cx.textBaseline='middle';cx.fillText(mark,mx,my+2);}
 cx.restore();
 var mine=++gen;blob=null;
 try{cx.getImageData(0,0,1,1);}catch(e){if(look==='photo'&&photo){photo=null;drop('photo');}else{logo=null;}draw();return;}
 try{cv.toBlob(function(b){if(mine===gen)blob=b;},'image/png');}catch(e){}}
function pop(){cv.classList.remove('is-pop');void cv.offsetWidth;cv.classList.add('is-pop');}
function open(){var s=read.querySelector('.bb-v.is-sel');if(!s)return;
 verse=textOf(s);ref=(read.getAttribute('data-label')||'')+':'+s.getAttribute('data-v');back=document.activeElement;
 vc.hidden=false;B.classList.add('lm-vc-on');art();draw();pop();
 var f=vc.querySelector('[data-look][aria-checked="true"]');if(f)f.focus();
 if(document.fonts&&document.fonts.load){Promise.all([document.fonts.load('italic 400 60px '+prop('--mb-serif','serif')),
  document.fonts.load('700 30px '+prop('--mb-ui','sans-serif'))]).then(function(){if(!vc.hidden)draw();},function(){});}}
function close(){vc.hidden=true;B.classList.remove('lm-vc-on');if(back&&back.focus)back.focus();}
function file(){return(ref.replace(/[^A-Za-z0-9]+/g,'-').replace(/^-+|-+$/g,'')||'verse')+'.png';}
function save(){if(!blob){say('One moment…');return;}var u=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=u;a.download=file();document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(u);},4000);say('Saved');}
function share(){var f=null;try{f=blob?new File([blob],file(),{type:'image/png'}):null;}catch(e){}
 if(f&&navigator.canShare&&navigator.canShare({files:[f]})){navigator.share({files:[f],title:ref}).catch(function(){});}
 else if(navigator.share){navigator.share({text:'“'+verse+'” '+ref}).catch(function(){});}
 else{save();}}
document.addEventListener('click',function(e){var t=e.target.closest?e.target.closest('[data-act="card"]'):null;if(t)open();});
vc.addEventListener('click',function(e){var t=e.target.closest('[data-vc],[data-look]');if(!t)return;
 var l=t.getAttribute('data-look'),a=t.getAttribute('data-vc');
 if(l){if(l!==look){look=l;pick();draw();pop();}}else if(a==='close'){close();}else if(a==='save'){save();}else if(a==='share'){share();}});
document.addEventListener('keydown',function(e){if(!vc.hidden&&e.key==='Escape'){e.preventDefault();close();}});
vc.addEventListener('keydown',function(e){
 var ls=[].slice.call(vc.querySelectorAll('[data-look]')),i=ls.indexOf(e.target);
 if(i>=0&&(e.key==='ArrowRight'||e.key==='ArrowLeft')){e.preventDefault();i=(i+(e.key==='ArrowRight'?1:ls.length-1))%ls.length;ls[i].focus();ls[i].click();return;}
 if(e.key==='Tab'){var f=[].slice.call(vc.querySelectorAll('button')).filter(function(b){return b.offsetParent!==null;});if(!f.length)return;
  if(e.shiftKey&&document.activeElement===f[0]){e.preventDefault();f[f.length-1].focus();}
  else if(!e.shiftKey&&document.activeElement===f[f.length-1]){e.preventDefault();f[0].focus();}}});
"""
READER_MORE_JS = "<script>(function(){" + _NIGHT + _CARD + "})();</script>"
# Night reading alone: the moon and the line of how far you've read.
NIGHT_JS = "<script>(function(){" + _NIGHT + "})();</script>"


# ─── the book picker, search, highlights & notes ─────────────────────


def render_books(biz, site, me, *, groups: str, seg: str, chips: str, script: str) -> str:
    """The book picker (member_portal_bible.render_books' groups), under the
    new heading."""
    import member_app_ui as ui
    import member_lumen_ui as lm
    from member_portal import _shell
    body = (f'<a class="mb-back" href="/my/bible">{ui.icon("back", 16)}Bible</a>'
            f'{lm.mast("Bible", "Choose a <em>book</em>")}{seg}'
            f'<div class="lm-field lm-find">{lm.ic("search", 18)}<label class="mp-sr" for="bk-q">Find a book</label>'
            f'<input id="bk-q" type="search" placeholder="Find a book" autocomplete="off"></div>'
            f'{chips}<div class="lm-bk">{groups}</div>')
    return _shell(biz, site, "Choose a book", body, tab="bible", who=me, script=script)


def render_search(biz, site, me, tr: str, query: str, rows: str, total: int, more: str) -> str:
    """Every verse with the words, as a quiet list."""
    import bible_text as bt
    import member_app_ui as ui
    from member_portal import _shell
    body = (f'<a class="mb-back" href="/my/bible">{ui.icon("back", 16)}Bible</a>'
            f'<div class="lm-searchtop">{field(query)}</div>'
            f'<p class="lm-meta lm-hitcount">{total} verse{"" if total == 1 else "s"} with “{_e(query)}” · '
            f'{_e(bt.TRANSLATIONS[tr]["short"])}</p><ul class="bb-hits lm-hits">{rows}</ul>{more}')
    return _shell(biz, site, "Search", body, tab="bible", who=me)


def notes_head() -> str:
    import member_app_ui as ui
    import member_lumen_ui as lm
    return (f'<a class="mb-back" href="/my/bible">{ui.icon("back", 16)}Bible</a>'
            f'{lm.mast("Bible", "Highlights &amp; <em>notes</em>")}')


# ─── /my/bible/plans ─────────────────────────────────────────────────


def render_plans(biz, site, me, *, devs, done, mine, church_today, church_done, show: str = "all",
                 preview: bool = False, today: Optional[date] = None, flash: str = "") -> str:
    """Plans & devotionals: what the church is reading this week, its
    devotionals, its reading plan, and a plan of your own."""
    import member_app_photos as photos
    import member_lumen_ui as lm
    import member_portal_devotionals as mpd
    import reading_plans as rp
    from member_portal import _shell
    import member_app_ui as ui
    today = today or date.today()
    short = _short(biz)
    show = show if show in dict(mpd.SHOWS) else "all"
    labels = dict(mpd.SHOWS)
    labels["church"] = f"From {short}"
    chips = "".join(f'<a href="/my/bible/plans?show={k}"{" aria-current=page" if k == show else ""}>{_e(labels[k])}</a>'
                    for k, _ in mpd.SHOWS)
    mine = mine or {}
    sts = _sts(devs, done, mine, today, preview)
    touched = {k[2:] for k in (done or {}) if k.startswith("t:")}
    pool = photos.photos(biz, site)
    used: set = set()
    parts: List[str] = []
    if devs is None:
        parts.append('<p class="mp-err" role="alert" style="margin-top:24px">The church\'s devotionals couldn\'t load just now. '
                     'Please try again in a moment.</p>')
    feat = next(((d, st) for d, st in sts if st["kind"] == "running" and d.get("starts_on")), None) or \
        next(((d, st) for d, st in sts if st["kind"] == "running"), None)
    if show in ("all", "church") and feat:
        d, st = feat
        bold, quiet = dev_words(d, st)
        heading = f"This week at {short}" if d.get("starts_on") else "Keep going"
        parts.append(f'<section aria-labelledby="lm-feat-h">{lm.section(heading, hid="lm-feat-h")}'
                     f'<a class="lm-dfeat" href="{_e(mpd._target(d, st))}">{cover(biz, d, pool, used, 0, st["count"])}'
                     f'{dots(st)}<span class="lm-dvt">{_e(bold)}</span><span class="lm-dvp">{_e(quiet)}</span>'
                     f'<span class="lm-btn sm">Read day {st["now"]}</span></a></section>')
    if show in ("all", "church", "yours"):
        rows = []
        i = 1
        for d, st in sts:
            if feat and d is feat[0] and show != "yours":
                continue
            if show == "yours" and not (f"devotional:{d['id']}" in mine or str(d["id"]) in touched):
                continue
            bold, quiet = dev_words(d, st)
            rows.append(f'<a class="lm-drow" href="{_e(mpd._target(d, st))}">{cover(biz, d, pool, used, i, st["count"])}'
                        f'<span class="lm-wt"><b>{_e(d.get("title"))}</b><span>{_e(bold)}</span>'
                        f'{f"<span>{_e(quiet)}</span>" if quiet else ""}</span>'
                        f'{lm.ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a>')
            i += 1
        if rows:
            parts.append(f'<section aria-labelledby="lm-lib-h">{lm.section("Yours" if show == "yours" else f"From {short}", hid="lm-lib-h")}'
                         f'<div class="lm-list">{"".join(rows)}</div></section>')
    if show in ("all", "reading", "yours"):
        out = []
        if church_today and show != "yours" or (church_today and church_done):
            t = church_today
            cdone = church_done or set()
            missed = len([x for x in range(1, t["day"]) if x not in cdone])
            sub = f"Day {t['day']} today" + (f" · {missed} day{'' if missed == 1 else 's'} to catch up" if missed else "")
            out.append(f'<div class="lm-cplan"><div class="lm-cplan-top">{_ring(t["day"], t["of"], str(t["day"]))}'
                       f'<span class="lm-prow-t"><span class="lm-kicker lm-gk">The church is reading</span><b>{_e(t["title"])}</b>'
                       f'<span class="m">{_e(sub)}</span></span></div><div class="lm-crow">'
                       f'<a class="lm-btn gold sm" href="{_e(t["href"])}">Read today</a>'
                       f'<a class="lm-btn ghost sm" href="/my/reading">{"Catch up" if missed else "See the plan"}</a></div></div>')
        rows = []
        for key, meta in rp.PLANS.items():
            started = mine.get(f"reading:{key}")
            if show == "yours" and not started:
                continue
            box = f'<span class="lm-len" aria-hidden="true"><b>{meta["days"]}</b><small>days</small></span>'
            if started:
                plan = mpd.own_plan(key, started)
                n = rp.readable_upto(plan, today)
                now = rp.day_number(plan, today)
                sub = (f"You're on day {now} · {rp.label(rp.schedule(key)[now - 1])}" if now else
                       ("It's finished" if n >= plan["days"] else "It starts today"))
                rows.append(f'<a class="lm-wrow lm-lrow" href="/my/bible/plans/{key}">{box}<span class="lm-wt"><b>{_e(meta["title"])}</b>'
                            f'<span>{_e(sub)}</span></span><span class="lm-tag">Yours</span></a>')
            else:
                rows.append(f'<div class="lm-wrow lm-lrow">{box}<span class="lm-wt"><b>{_e(meta["title"])}</b>'
                            f'<span>{_e(meta["about"])}</span></span><form method="post" action="/my/bible/plans/start">'
                            f'<input type="hidden" name="plan" value="reading:{key}">'
                            f'<button class="lm-btn sm ghost" type="submit" aria-label="Start {_e(meta["title"])}">Start</button></form></div>')
        if rows:
            if out or show != "yours":
                out.append('<p class="lm-kicker lm-sub2">' + ("Your plans" if show == "yours" else "Start one on your own") + '</p>')
            out.append(f'<div class="lm-list">{"".join(rows)}</div>')
        if out:
            parts.append(f'<section aria-labelledby="lm-rp-h">{lm.section("Reading plans", hid="lm-rp-h")}{"".join(out)}</section>')
    body = "".join(p for p in parts if p) or (
        '<p class="lm-quiet" style="margin-top:24px">Nothing here yet. Start a reading plan or one of the church\'s '
        'devotionals, and it shows here.</p>' if show == "yours" else
        '<p class="lm-quiet" style="margin-top:24px">Nothing here yet.</p>')
    return _shell(biz, site, "Plans & devotionals", f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
{lm.mast("Read with your church", "Plans &amp; <em>devotionals</em>")}
<nav class="lm-chips" aria-label="Show">{chips}</nav>
{flash}
{body}""", tab="bible", who=me)


# ─── /my/reading (and a plan of your own) ────────────────────────────


def render_reading(biz, site, request, me, done: Optional[set], today: Optional[date] = None, *,
                   plan: Optional[Dict[str, Any]] = None) -> str:
    """A reading plan: how far you've come, this week's days to tick, the
    ones to catch up. The church's, or one the member started (with Stop)."""
    from datetime import timedelta
    import member_lumen_ui as lm
    import member_portal_reading as mpr
    import reading_plans as rp
    import member_app_ui as ui
    from member_portal import _shell
    own = bool(plan and plan.get("own"))
    plan = plan if own else rp.current(biz)
    here = f"/my/bible/plans/{plan['key']}" if own and plan else "/my/reading"
    key = plan["key"] if own and plan else ""
    # A reading plan sits under the Bible: back to Plans (your own) or to the
    # Bible (the church's), never a bare Home tab.
    back = f'<a class="mb-back" href="/my/bible/plans">{ui.icon("back", 16)}Plans</a>' if own else ""
    bar = None if own else ("/my/bible", "Bible")
    if not plan:
        return _shell(biz, site, "Reading plan", lm.mast("Bible", "Reading <em>plan</em>") +
                      '<p class="lm-quiet" style="margin-top:18px">The church hasn\'t started a reading plan. You can always '
                      'read in the Bible tab.</p><div class="lm-row2"><a class="lm-btn" href="/my/bible">Open the Bible</a></div>',
                      tab="bible", who=me, back=bar)
    today = today or date.today()
    upto = rp.readable_upto(plan, today)
    days = rp.schedule(plan["key"])

    def tick(d: int, read: bool) -> str:
        mine = f'<input type="hidden" name="plan" value="{key}">' if key in rp.PLANS else ""
        label = f"Day {d}: mark as not read" if read else f"Day {d}: mark as read"
        return (f'<form method="post" action="/my/reading"><input type="hidden" name="day" value="{d}">'
                f'<input type="hidden" name="read" value="{"no" if read else "yes"}"><input type="hidden" name="back" value="{here}">'
                f'{mine}<button class="lm-circle{" done" if read else ""}" type="submit" aria-label="{label}" '
                f'aria-pressed="{"true" if read else "false"}">{ui.icon("check", 18)}</button></form>')

    def day_row(d: int) -> str:
        when = plan["start"] + timedelta(days=d - 1)
        read = d in (done or set())
        return (f'<div class="lm-rday"><span class="lm-wdate" aria-hidden="true"><small>{_e(when.strftime("%a"))}</small>'
                f'<b>{when.day}</b></span><a class="lm-wt" href="{_e(rp.href(days[d - 1]))}"><b>{_e(rp.label(days[d - 1]))}</b>'
                f'<span>Day {d}</span></a>{tick(d, read)}</div>')
    if done is None:
        body = '<p class="mp-err" role="alert" style="margin-top:20px">Your progress couldn\'t load just now. Please try again in a moment.</p>'
    elif upto == 0:
        body = (f'<div class="lm-rp"><span class="lm-kicker lm-gk">Starts {_e(plan["start"].strftime("%A, %B"))} {plan["start"].day}</span>'
                f'<b class="lm-rp-t">{_e(rp.label(days[0]))}</b><span class="m">Day 1</span></div>')
    else:
        n_today = rp.day_number(plan, today)
        streak = rp.streak(done, n_today) if n_today else 0
        missed = [d for d in range(1, upto + (0 if n_today else 1)) if d not in done][-14:]
        pct = round(100 * len(done) / plan["days"]) if plan["days"] else 0
        rows = "".join(day_row(d) for d in range(upto, max(0, upto - 7), -1))
        catch = ""
        if missed and n_today:
            catch = (f'<details class="lm-catch"><summary>{len(missed)} {"day" if len(missed) == 1 else "days"} to catch up'
                     f'{lm.ic("down", 16)}</summary><div class="lm-list">{"".join(day_row(d) for d in missed)}</div></details>')
        body = (f'<div class="lm-rp"><span class="lm-rp-n"><b>{len(done)}</b> of {plan["days"]} days read</span>'
                f'<span class="lm-pb"><i style="width:{pct}%"></i></span>'
                + (f'<span class="m">{streak} {"day" if streak == 1 else "days"} in a row.</span>' if streak > 1 else "")
                + f'</div>{lm.section("This week", hid="lm-week-h")}<div class="lm-list">{rows}</div>{catch}')
    stop = ""
    if own:
        stop = (f'<form method="post" action="/my/bible/plans/stop" class="lm-stop"><input type="hidden" name="plan" '
                f'value="reading:{key}"><button class="lm-txtbtn" type="submit">Stop this plan</button></form>')
    sub = f'{rp.PLANS[plan["key"]]["about"]} {"You started it" if own else "Started"} {plan["start"].strftime("%B")} {plan["start"].day}.'
    return _shell(biz, site, "Reading plan", f"""{back}
{lm.mast("Your plan" if own else "Reading plan", lm.italic_last(plan["title"]), sub)}
{mpr._flash(request)}
{body}
{stop}""", tab="bible", who=me, back=bar)


# ─── the look ────────────────────────────────────────────────────────
# Accent level 2: gold for the Word (the spine, the plans' days, the chapter
# number, the verse numbers), soft gold behind "pick up where you left off".
# Fixed colours are the mock's: the book spine, the three flat covers and
# the five highlighters (a highlight keeps its meaning whatever the church's
# colour).
CSS = """
/* the Bible (member_lumen_bible) */
body.lm{--lm-gold-8:var(--s1);--lm-gold-9:var(--s1);}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm{--lm-gold-8:color-mix(in srgb,var(--gold-ink) 8%,var(--bg));--lm-gold-9:color-mix(in srgb,var(--gold-ink) 9%,var(--bg));}
}
body.lm .lm-mastrow{display:flex;align-items:center;justify-content:space-between;gap:12px;}
body.lm .lm-bmast{margin-top:10px;}
body.lm .lm-trs{display:inline-flex;gap:2px;padding:3px;border-radius:12px;background:var(--s1);flex:none;}
body.lm .lm-trs a{display:grid;place-items:center;height:30px;padding:0 10px;border-radius:9px;color:var(--fg2);text-decoration:none;
  font:700 11.5px/1 var(--mb-ui);letter-spacing:.04em;}
body.lm .lm-trs a[aria-current]{background:var(--bg);color:var(--fg);box-shadow:0 1px 3px var(--lm-shadow);}
body.lm .lm-field{display:flex;align-items:center;gap:6px;height:50px;margin-top:20px;padding:0 14px 0 6px;border-radius:14px;
  background:var(--s1);color:var(--fg3);}
body.lm .lm-field input{flex:1;min-width:0;height:48px;border:0;background:none;color:var(--fg);font:400 16px/1 var(--mb-ui);outline:none;}
body.lm .lm-field input::placeholder{color:var(--fg3);}
body.lm .lm-field-go{width:40px;height:40px;flex:none;border:0;border-radius:12px;background:none;color:var(--fg3);display:grid;place-items:center;
  cursor:pointer;padding:0;}
body.lm .lm-find{padding-left:16px;gap:10px;margin-top:16px;}
body.lm .lm-field:focus-within{box-shadow:inset 0 0 0 1.5px var(--lm-ring);}
/* pick up where you left off */
body.lm .lm-cont{display:grid;grid-template-columns:70px minmax(0,1fr);gap:18px;align-items:center;margin:6px -20px 0;padding:20px;
  background:var(--lm-gold-8);color:var(--fg);text-decoration:none;}
body.lm .lm-spine{position:relative;display:block;height:96px;border-radius:6px 12px 12px 6px;background:#D9A13B;overflow:hidden;}
body.lm .lm-spine::before{content:"";position:absolute;left:0;top:0;bottom:0;width:8px;background:#9C6A12;}
body.lm .lm-spine::after{content:"";position:absolute;left:16px;right:10px;top:14px;height:1px;background:rgba(40,25,0,.4);
  box-shadow:0 5px 0 rgba(40,25,0,.4);}
body.lm .lm-spine b{position:absolute;left:14px;right:6px;bottom:10px;font:italic 500 15px/1.05 var(--mb-serif);color:#2a1a02;
  overflow-wrap:anywhere;}
body.lm .lm-cont-t{min-width:0;}
body.lm .lm-ct{display:block;margin:6px 0 8px;font:400 34px/1 var(--mb-serif);letter-spacing:-.02em;}
body.lm .lm-go{display:inline-flex;align-items:center;gap:6px;font:650 14px/1 var(--mb-ui);color:var(--lm-gold);}
/* the church's devotionals */
body.lm .lm-devs{gap:14px;}
body.lm .lm-dev{width:150px;color:var(--fg);text-decoration:none;}
body.lm .lm-cv{position:relative;display:block;height:190px;border-radius:14px;overflow:hidden;isolation:isolate;}
body.lm .lm-cv b{position:absolute;left:14px;right:12px;bottom:14px;z-index:2;font:italic 400 26px/1 var(--mb-serif);letter-spacing:-.02em;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}
body.lm .lm-cv small{position:absolute;left:14px;top:14px;z-index:2;font:700 10px/1 var(--mb-ui);letter-spacing:.18em;text-transform:uppercase;opacity:.75;}
body.lm .lm-cv::after{content:"";position:absolute;z-index:1;}
body.lm .lm-cv.cv-a{background:#F6E2D6;color:#5a2410;}
body.lm .lm-cv.cv-a::after{right:-30px;top:30px;width:110px;height:110px;border-radius:50%;background:#EDB495;}
body.lm .lm-cv.cv-b{background:#E6E1FA;color:#2b2366;}
body.lm .lm-cv.cv-b::after{right:16px;top:22px;width:52px;height:52px;border-radius:50%;box-shadow:-14px 6px 0 0 #B7ACF0;}
body.lm .lm-cv.cv-c{background:#DCF0EA;color:#0b4a40;}
body.lm .lm-cv.cv-c::after{left:0;right:0;top:46%;height:2px;background:#0b4a40;opacity:.5;}
body.lm .lm-cv.has-ph{background:var(--s2);color:#fff;}
body.lm .lm-cv.has-ph>.mb-ph{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
body.lm .lm-cv.has-ph::after{inset:0;background:linear-gradient(180deg,rgba(0,0,0,.28),rgba(0,0,0,0) 34%,rgba(0,0,0,.62));}
body.lm .lm-cv.has-ph small{opacity:.92;}
body.lm .lm-dots{display:flex;gap:4px;margin-top:10px;}
body.lm .lm-dots i{width:14px;height:3px;border-radius:2px;background:var(--s3);}
body.lm .lm-dots i.on{background:var(--lm-gold);}
body.lm .lm-dvt{display:block;margin-top:8px;font:650 14.5px/1.25 var(--mb-ui);}
body.lm .lm-dvp{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
/* reading plans */
body.lm .lm-prow-t{flex:1;min-width:0;}
body.lm .lm-prow-t b{margin-top:6px;}
body.lm .lm-gk{color:var(--lm-gold);}
body.lm .lm-tk{color:var(--lm-teal);}
body.lm .lm-plans{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:14px;}
body.lm .lm-list+.lm-plans{margin-top:18px;}
body.lm .lm-plan{position:relative;display:block;padding:16px;border-radius:18px;background:var(--s1);color:var(--fg);text-decoration:none;}
body.lm .lm-plan b{display:block;font:italic 300 44px/.85 var(--mb-serif);color:var(--lm-gold);letter-spacing:-.04em;}
body.lm .lm-plan small{display:block;margin-top:4px;font:700 10px/1 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:var(--fg3);}
body.lm .lm-plan span{display:block;margin-top:14px;font:650 14px/1.25 var(--mb-ui);}
body.lm .lm-yours{display:block;margin-top:8px;font:normal 650 12px/1.2 var(--mb-ui);color:var(--lm-teal);}
/* your highlights & notes */
body.lm .lm-marks{display:flex;gap:18px;align-items:center;flex-wrap:wrap;padding:16px 0;border-top:1px solid var(--lm-line);
  border-bottom:1px solid var(--lm-line);color:var(--fg2);text-decoration:none;}
body.lm .lm-marks>span{display:inline-flex;align-items:center;gap:7px;font:600 13.5px/1 var(--mb-ui);}
body.lm .lm-marks i{width:10px;height:10px;border-radius:50%;}
body.lm .lm-marks .lm-chev{margin-left:auto;}
body.lm .mk-hl{background:#E3A92B;}
body.lm .mk-note{background:#17A894;}
body.lm .mk-saved{background:#6D57E8;}
body.lm .lm-quiet{margin:0;font:400 14.5px/1.5 var(--mb-ui);color:var(--fg2);}
/* the books */
body.lm .lm-books{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
body.lm .lm-book{display:block;padding:18px 16px;border-radius:18px;background:var(--s1);color:var(--fg);text-decoration:none;}
body.lm .lm-book b{display:block;font:400 22px/1.05 var(--mb-serif);}
body.lm .lm-book span{display:block;margin-top:6px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
body.lm .lm-src{margin:28px 0 0;font:500 12px/1.4 var(--mb-ui);color:var(--fg3);}
/* the reader: no tab bar, a plain bar with the chapter in the middle */
body.lm .mb-top.lm-mid .mb-top-right{flex:1;justify-content:flex-end;}
body.lm .lm-barmid{flex:none;}
body.lm .lm-pill{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 14px;border-radius:18px;background:var(--s1);color:var(--fg);
  font:650 14px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;}
body.lm .lm-aa{width:40px;height:40px;border:0;border-radius:50%;background:none;color:var(--fg);font:600 16px/1 var(--mb-serif);cursor:pointer;}
body.lm .lm-aa[aria-expanded=true]{background:var(--lm-gold-9);color:var(--lm-gold);}
body.lm .lm-aapanel{position:fixed;z-index:16;top:calc(64px + env(safe-area-inset-top,0px));left:12px;right:12px;max-width:420px;margin:0 auto;
  padding:14px 16px;border-radius:18px;background:var(--bg);box-shadow:0 0 0 1px var(--lm-line),0 14px 36px var(--lm-shadow);gap:12px;}
body.lm .lm-aapanel[hidden]{display:none;}
body.lm .lm-aapanel .bb-aa-btns button{background:var(--s1);border-radius:11px;font:650 13.5px/1 var(--mb-ui);}
body.lm .lm-aapanel .lm-trs a{height:32px;}
body.lm .lm-chap{display:flex;align-items:flex-end;gap:14px;margin:8px 0 22px;}
body.lm .lm-chap b{font:300 104px/.78 var(--mb-serif);color:var(--lm-gold);letter-spacing:-.05em;}
body.lm .lm-chap>span:last-child{max-width:12em;padding-bottom:6px;font:650 11px/1.4 var(--mb-ui);letter-spacing:.18em;text-transform:uppercase;
  color:var(--fg2);}
body.lm .lm-read{padding-bottom:8px;}
body.lm .lm-read .bb-text{font-size:20px;line-height:1.65;letter-spacing:0;color:var(--fg);}
body.lm .lm-read .bb-text.sz-s{font-size:17px;}
body.lm .lm-read .bb-text.sz-l{font-size:23px;}
body.lm .lm-read .bb-text.f-sans{font-family:var(--mb-ui);}
body.lm .lm-read .bb-n{font:700 10px/1 var(--mb-ui);color:var(--lm-gold);margin:0 4px 0 2px;vertical-align:7px;}
body.lm .lm-read .bb-v{border-radius:4px;transition:background-color .3s;}
body.lm .lm-read .bb-v.is-sel{text-decoration:underline;text-decoration-color:var(--lm-gold);text-decoration-thickness:2px;text-underline-offset:6px;}
body.lm .lm-read .bb-hl{background:var(--lm-gold-9);box-shadow:0 0 0 3px var(--lm-gold-9);}
body.lm .hl-gold{background:rgba(227,169,43,.28);}
body.lm .hl-pink{background:rgba(236,72,153,.22);}
body.lm .hl-teal{background:rgba(23,168,148,.24);}
body.lm .hl-violet{background:rgba(109,87,232,.22);}
body.lm .hl-coral{background:rgba(240,122,67,.26);}
body.lm .sw-gold{background:#E3A92B;}
body.lm .sw-pink{background:#EC4899;}
body.lm .sw-teal{background:#17A894;}
body.lm .sw-violet{background:#6D57E8;}
body.lm .sw-coral{background:#F07A43;}
body.lm .lm-trfoot{margin-top:10px;}
body.lm .lm-read~.lm-src{margin-top:18px;}
body.lm main:has(.lm-read){padding-bottom:calc(110px + env(safe-area-inset-bottom,0px));}
body.lm .lm-chnav{position:fixed;z-index:14;left:14px;right:14px;bottom:calc(18px + env(safe-area-inset-bottom,0px));max-width:572px;margin:0 auto;
  display:flex;justify-content:space-between;pointer-events:none;}
body.lm .lm-chstep{pointer-events:auto;display:inline-flex;align-items:center;gap:6px;height:42px;padding:0 16px;border-radius:21px;
  background:var(--bg);color:var(--fg);font:650 13px/1 var(--mb-ui);text-decoration:none;box-shadow:0 0 0 1px var(--lm-line),0 6px 18px var(--lm-shadow);}
body.lm.bb-docked .lm-chnav{display:none;}
body.lm .bb-dock{left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom,0px));max-width:576px;padding:12px 14px 14px;border-radius:20px;
  background:var(--bg);box-shadow:0 0 0 1px var(--lm-line),0 14px 36px var(--lm-shadow);}
body.lm .bb-dock-ref{font:650 14px/1.2 var(--mb-ui);}
body.lm .bb-x{width:32px;height:32px;background:var(--s1);}
body.lm .bb-sws{gap:10px;margin-top:10px;}
body.lm .bb-sw{width:32px;height:32px;box-shadow:none;}
body.lm .bb-sw[aria-pressed=true]{box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--fg);}
body.lm .bb-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;}
body.lm .bb-acts button{flex-direction:row;gap:6px;height:36px;padding:0 12px;border-radius:11px;background:var(--s1);color:var(--fg);
  font:650 12.5px/1 var(--mb-ui);}
body.lm .bb-acts button .lm-ic{color:var(--fg);}
body.lm .bb-acts button[aria-pressed=true] .lm-ic{color:var(--lm-gold);fill:var(--gold);}
body.lm .bb-toast{bottom:calc(200px + env(safe-area-inset-bottom,0px));}
/* the book picker */
body.lm .mb-seg{margin:20px 0 0;border-radius:14px;}
body.lm .mb-seg a{min-height:36px;border-radius:11px;font:650 13px/1 var(--mb-ui);}
body.lm .mb-seg a[aria-current]{background:var(--bg);box-shadow:0 1px 3px var(--lm-shadow);}
body.lm .lm-bk .bk-group{margin-top:28px;}
body.lm .lm-bk .bk-gh{font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;color:var(--fg2);margin-bottom:8px;}
body.lm .lm-bk details.bk{border-bottom:1px solid var(--lm-line);}
body.lm .lm-bk details.bk:first-of-type{border-top:1px solid var(--lm-line);}
body.lm .lm-bk .bk-n{font:400 19px/1.2 var(--mb-serif);letter-spacing:-.01em;}
body.lm .lm-bk details.bk[open]>summary .bk-n{color:var(--lm-gold);font-weight:400;}
body.lm .lm-bk .bk-grid a{border-radius:12px;font:600 15px/1 var(--mb-ui);}
body.lm .lm-bk .bk-grid a.is-now{background:var(--lm-gold);color:#fff;}
body.lm .bb-recent{margin-top:14px;}
body.lm .bb-recent a{min-height:34px;font:650 13px/1 var(--mb-ui);}
body.lm .bb-recent a:first-child{background:var(--lm-gold-9);color:var(--lm-gold);}
/* search */
body.lm .lm-searchtop .lm-field{margin-top:12px;}
body.lm .lm-hitcount{margin-top:16px;}
body.lm .lm-hits{gap:0;margin-top:14px;border-top:1px solid var(--lm-line);}
body.lm .lm-hits a{padding:16px 0;border-radius:0;background:none;border-bottom:1px solid var(--lm-line);}
body.lm .lm-hits strong{font:700 10.5px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-gold);}
body.lm .lm-hits span{margin-top:4px;font:400 18px/1.5 var(--mb-serif);}
/* highlights & notes */
body.lm .bb-filters,body.lm .lm-chips{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;margin:20px -20px 0;padding:0 20px 2px;}
body.lm .lm-chips::-webkit-scrollbar{display:none;}
body.lm .bb-filters a,body.lm .lm-chips a{flex:none;display:inline-flex;align-items:center;gap:6px;height:38px;min-height:0;padding:0 16px;border-radius:19px;
  background:var(--s1);color:var(--fg2);font:650 13.5px/1 var(--mb-ui);text-decoration:none;}
body.lm .bb-filters a[aria-current],body.lm .lm-chips a[aria-current]{background:var(--fg);color:var(--bg);}
body.lm .bb-colours{margin-top:16px;}
body.lm .bb-day{margin:30px 0 0;padding-bottom:10px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;color:var(--fg2);
  border-bottom:1px solid var(--lm-line);}
body.lm .bb-it{margin:0;padding:16px 0;border-radius:0;background:none;border-bottom:1px solid var(--lm-line);}
body.lm .bb-it-h strong{font:700 10.5px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-gold);}
body.lm .bb-it-v{font-size:19px;line-height:1.5;}
body.lm .bb-it-note{background:var(--s1);border-radius:14px;}
body.lm .bb-it-f a{color:var(--acc);}
/* plans & devotionals */
body.lm .lm-dfeat{display:block;color:var(--fg);text-decoration:none;}
body.lm .lm-dfeat .lm-cv{height:220px;}
body.lm .lm-dfeat .lm-cv b{font-size:32px;right:18px;}
body.lm .lm-dfeat .lm-dvt{margin-top:12px;font:700 18px/1.25 var(--mb-ui);letter-spacing:-.015em;}
body.lm .lm-dfeat .lm-dvp{font-size:13.5px;}
body.lm .lm-dfeat .lm-btn{margin-top:14px;}
body.lm .lm-drow{display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid var(--lm-line);color:var(--fg);text-decoration:none;}
body.lm .lm-drow .lm-cv{width:56px;height:66px;flex:none;border-radius:10px;}
body.lm .lm-drow .lm-cv b,body.lm .lm-drow .lm-cv small{display:none;}
body.lm .lm-drow .lm-cv.cv-a::after{right:-14px;top:14px;width:44px;height:44px;}
body.lm .lm-drow .lm-cv.cv-b::after{right:8px;top:10px;width:22px;height:22px;box-shadow:-6px 3px 0 0 #B7ACF0;}
body.lm .lm-drow .lm-wt>span+span{margin-top:1px;color:var(--fg3);}
body.lm .lm-cplan{padding:18px 20px 20px;margin:0 -20px;background:var(--lm-gold-8);}
body.lm .lm-cplan-top{display:flex;align-items:center;gap:14px;}
body.lm .lm-cplan .lm-prow-t b{display:block;margin-top:6px;font:650 16px/1.25 var(--mb-ui);}
body.lm .lm-cplan .lm-prow-t .m{display:block;margin-top:3px;font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-cplan .lm-crow{margin-top:14px;}
body.lm .lm-sub2{margin:26px 0 10px;}
body.lm .lm-len{width:52px;flex:none;}
body.lm .lm-len b{display:block;font:italic 300 32px/.9 var(--mb-serif);color:var(--lm-gold);letter-spacing:-.03em;}
body.lm .lm-len small{display:block;margin-top:3px;font:700 9.5px/1 var(--mb-ui);letter-spacing:.16em;text-transform:uppercase;color:var(--fg3);}
body.lm .lm-lrow form{flex:none;}
body.lm .lm-tag{flex:none;font:700 10px/1 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--lm-teal);}
/* a devotional and its days: today's markup, quieter */
body.lm .dv-hero{border-radius:20px;}
body.lm .dv-days,body.lm .dv-prac,body.lm .dv-check{border-radius:0;background:none;border-top:1px solid var(--lm-line);}
body.lm .dv-dl,body.lm .dv-prac li,body.lm .dv-ci{padding-left:0;padding-right:0;border-bottom:1px solid var(--lm-line);}
body.lm .dv-dl+.dv-dl::before,body.lm .dv-prac li+li::before,body.lm .dv-ci+.dv-ci::before{display:none;}
body.lm .dv-check-h{padding:16px 0 6px;}
body.lm .dv-scrip{border-radius:20px;background:var(--lm-paper);color:var(--lm-ink);box-shadow:inset 0 0 0 1.5px var(--lm-ring);}
body.lm .dv-blk{border-radius:16px;}
body.lm .dv-next{border-radius:0;background:none;padding:16px 0;border-top:1px solid var(--lm-line);border-bottom:1px solid var(--lm-line);}
body.lm .dv-d.is-now .dv-c{color:var(--acc);}
/* a reading plan */
body.lm .lm-rp{display:block;margin:22px -20px 0;padding:20px;background:var(--lm-gold-8);}
body.lm .lm-rp-n{display:block;font:500 15px/1.2 var(--mb-ui);color:var(--fg2);}
body.lm .lm-rp-n b{font:400 44px/1 var(--mb-serif);color:var(--fg);letter-spacing:-.03em;margin-right:4px;}
body.lm .lm-rp-t{display:block;margin-top:10px;font:400 26px/1.1 var(--mb-serif);}
body.lm .lm-rp .lm-pb i{background:var(--lm-gold);}
body.lm .lm-rp .m{display:block;margin-top:10px;font:500 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-rday{display:flex;align-items:center;gap:14px;padding:12px 0;border-bottom:1px solid var(--lm-line);}
body.lm .lm-rday .lm-wt{color:var(--fg);text-decoration:none;}
body.lm .lm-rday form{flex:none;}
body.lm .lm-rday .lm-wdate small{color:var(--lm-gold);}
body.lm .lm-catch{margin-top:24px;}
body.lm .lm-catch>summary{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:48px;cursor:pointer;list-style:none;
  font:650 15px/1.2 var(--mb-ui);color:var(--acc);}
body.lm .lm-catch>summary::-webkit-details-marker{display:none;}
body.lm .lm-catch[open]>summary .lm-ic{transform:rotate(180deg);}
body.lm .lm-stop{margin-top:24px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-cont,body.lm .lm-dev,body.lm .lm-plan,body.lm .lm-book,body.lm .lm-marks,body.lm .lm-dfeat,body.lm .lm-drow,body.lm .lm-chstep{transition:transform .15s ease;}
  body.lm .lm-cont:active,body.lm .lm-dev:active,body.lm .lm-plan:active,body.lm .lm-book:active,body.lm .lm-marks:active,body.lm .lm-dfeat:active,
  body.lm .lm-drow:active,body.lm .lm-chstep:active{transform:scale(.985);}
}
body.lm .lm-trs a:focus-visible,body.lm .lm-cont:focus-visible,body.lm .lm-dev:focus-visible,body.lm .lm-plan:focus-visible,
body.lm .lm-book:focus-visible,body.lm .lm-marks:focus-visible,body.lm .lm-pill:focus-visible,body.lm .lm-aa:focus-visible,
body.lm .lm-chstep:focus-visible,body.lm .lm-dfeat:focus-visible,body.lm .lm-drow:focus-visible,body.lm .lm-field-go:focus-visible,
body.lm .lm-chips a:focus-visible,body.lm .lm-catch>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
/* Lumen Next, the reader: how far you've read, the moon, the ink, night, the card */
body.lm .lm-rprog{position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--lm-gold);transform:scaleX(0);
  transform-origin:0 50%;pointer-events:none;}
body.lm .lm-moon{display:grid;place-items:center;color:var(--fg);}
body.lm .lm-moon[aria-pressed=true]{background:var(--lm-gold-9);color:var(--lm-gold);}
body.lm .lm-read .bb-v{--hlc:transparent;background-color:transparent;background-image:linear-gradient(var(--hlc),var(--hlc));
  background-repeat:no-repeat;background-position:0 0;background-size:0% 100%;}
body.lm .lm-read .bb-v.hl-gold,body.lm .lm-read .bb-v.hl-pink,body.lm .lm-read .bb-v.hl-teal,body.lm .lm-read .bb-v.hl-violet,
body.lm .lm-read .bb-v.hl-coral{background-color:transparent;background-size:100% 100%;}
body.lm .lm-read .bb-v.hl-gold{--hlc:rgba(227,169,43,.32);}
body.lm .lm-read .bb-v.hl-pink{--hlc:rgba(236,72,153,.22);}
body.lm .lm-read .bb-v.hl-teal{--hlc:rgba(23,168,148,.24);}
body.lm .lm-read .bb-v.hl-violet{--hlc:rgba(109,87,232,.22);}
body.lm .lm-read .bb-v.hl-coral{--hlc:rgba(240,122,67,.26);}
""" + _dark("""
body.lm.lm-dark:has(.lm-read),body.lm.lm-dark:has(.lm-dd){overscroll-behavior-y:none;--bg:#100E0B;--fg:#E8DFCC;--fg2:#A79E8E;--fg3:#857D70;
  --s1:#1C1914;--s2:#27231C;--s3:#3A342B;--line:rgba(255,255,255,.1);--lm-line:rgba(255,255,255,.08);--lm-shadow:rgba(0,0,0,.55);
  --gold:#E9B65A;--gold-ink:#E9B65A;--lm-gold:#E9B65A;--lm-gold-9:rgba(233,182,90,.15);--bar:rgba(16,14,11,.82);
  --surface:var(--bg);--input-surface:var(--s1);--mb-surface:var(--s1);--mb-surface-2:var(--s2);color-scheme:dark;
  background:var(--bg);color:var(--fg);}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm.lm-dark:has(.lm-read),body.lm.lm-dark:has(.lm-dd){--acc:color-mix(in srgb,var(--acc-fill) 58%,#fff);}
}
body.lm.lm-dark .lm-read .bb-v.hl-gold{--hlc:rgba(233,182,90,.3);}
body.lm.lm-dark .lm-read .bb-v.hl-pink{--hlc:rgba(246,112,150,.3);}
body.lm.lm-dark .lm-read .bb-v.hl-teal{--hlc:rgba(46,196,160,.28);}
body.lm.lm-dark .lm-read .bb-v.hl-violet{--hlc:rgba(150,135,255,.3);}
body.lm.lm-dark .lm-read .bb-v.hl-coral{--hlc:rgba(255,140,90,.3);}
body.lm.lm-dark .lm-chstep,body.lm.lm-dark .bb-dock,body.lm.lm-dark .lm-aapanel{box-shadow:0 0 0 1px var(--lm-line),0 14px 36px rgba(0,0,0,.6);}
body.lm.lm-dark .lm-moon{background:var(--lm-gold-9);color:var(--lm-gold);}
""") + """body.lm.lm-vc-on{overflow:hidden;}
body.lm.lm-vc-on .bb-toast{z-index:70;}
body.lm .lm-vc{position:fixed;inset:0;z-index:60;}
body.lm .lm-vc[hidden]{display:none;}
body.lm .lm-vc-scrim{position:absolute;inset:0;background:rgba(10,8,6,.46);}
body.lm .lm-vc-sheet{position:absolute;left:0;right:0;bottom:0;max-width:600px;max-height:calc(100% - 24px);overflow:auto;margin:0 auto;
  padding:10px 20px calc(20px + env(safe-area-inset-bottom,0px));border-radius:28px 28px 0 0;background:var(--bg);color:var(--fg);
  box-shadow:0 -10px 40px rgba(0,0,0,.2);}
body.lm .lm-vc-grab{display:block;width:38px;height:5px;margin:0 auto 12px;border-radius:3px;background:var(--s3);}
body.lm .lm-vc-h{display:flex;align-items:center;justify-content:space-between;}
body.lm .lm-vc-h b{font:700 17px/1.2 var(--mb-ui);}
body.lm .lm-vc-cv{display:block;width:min(268px,62vw);height:auto;aspect-ratio:4/5;margin:16px auto 0;border-radius:22px;
  box-shadow:0 22px 44px -20px rgba(0,0,0,.45);}
body.lm .lm-vc-looks{display:flex;justify-content:center;flex-wrap:wrap;gap:8px;margin-top:18px;}
body.lm .lm-vc-looks button{height:36px;padding:0 14px;border:0;border-radius:18px;background:var(--s1);color:var(--fg2);
  font:650 13px/1 var(--mb-ui);cursor:pointer;}
body.lm .lm-vc-looks button[aria-checked=true]{background:var(--fg);color:var(--bg);}
body.lm .lm-vc-go{display:flex;gap:8px;margin-top:18px;}
body.lm .lm-vc-go .lm-btn{flex:1;}
body.lm .lm-vc-priv{margin:12px 0 0;text-align:center;font:500 12px/1.4 var(--mb-ui);color:var(--fg3);}
body.lm .lm-vc-looks button:focus-visible,body.lm .lm-vc-go .lm-btn:focus-visible,body.lm .lm-moon:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-read .bb-v{transition:background-size .9s cubic-bezier(.2,.8,.2,1);}
  body.lm:has(.lm-read),body.lm:has(.lm-read) .mb-top,body.lm .lm-pill{transition:background-color .5s ease,color .5s ease;}
  body.lm .lm-chstep{transition:background-color .5s ease,color .5s ease,transform .15s ease;}
  body.lm .lm-vc:not([hidden]) .lm-vc-scrim{animation:lm-vcfade .3s both;}
  body.lm .lm-vc:not([hidden]) .lm-vc-sheet{animation:lm-vcup .55s cubic-bezier(.2,.8,.2,1) both;}
  body.lm .lm-vc-cv.is-pop{animation:lm-vcpop .6s cubic-bezier(.34,1.56,.64,1) both;}
}
@keyframes lm-vcfade{from{opacity:0}to{opacity:1}}
@keyframes lm-vcup{from{transform:translateY(100%)}to{transform:none}}
@keyframes lm-vcpop{from{transform:scale(.92);opacity:.5}to{transform:none;opacity:1}}
"""
