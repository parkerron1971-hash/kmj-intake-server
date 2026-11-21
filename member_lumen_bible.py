"""member_lumen_bible.py — the Bible in the member app's new look ("Lumen").

Kevin, 2026-11-18, on today's Bible tab: it "seems all over the place and
doesn't feel like a bible app ... needs more organization and feel of a top
tier bible app". He approved the "clean Lumen" mock (version 29, accent
level 2); this is its BIBLE and READER views, built on the data today's
pages read (member_portal_bible, member_portal_devotionals,
member_portal_reading, member_bible_marks). Who sees it: member_lumen.py
(MEMBER_LUMEN). Off, every page here is today's, byte for byte.

Look 5.1 (Kevin, 2026-11-20: "when someone click bible the bible should
open directly with devotional tabs at the top"): the Bible tab opens
straight into reading. Its top bar is a segmented control, Read ·
Devotional · Plans · Saved, with a search button beside it and a small dot
on Devotional while today's day of the devotional on top isn't read yet;
there is no church bar over it (as the mock draws it).
Every tab is a real address, so it works without script and the back
button stays sane (with script, switching tabs replaces the page in the
history instead of stacking it):

  /my/bible ................. Read: the reader, at the chapter read last
                              (the sol_bible cookie); someone who has read
                              nothing yet starts at today's reading of the
                              church's plan, else John 1.
  /my/bible/<b>/<n> ......... Read at that chapter (every old link works).
  /my/bible?tab=devotional .. today's devotional (member_lumen_devotional's
                              green card), this week's days as circles,
                              the verse of the day, more devotionals.
  /my/bible?tab=plans ....... the reading plans running for this member as
                              rings (today's reading, Read), then the plans
                              to start.
  /my/bible?tab=saved ....... their highlights, notes and saved verses, each
                              back into the reader at that verse.
  /my/bible?tab=search ...... find a passage or a word, recently read, the
                              books (the search itself is today's ?q=).

The reader: the chapter pill (opens the book picker), the translation pill,
Aa (size and font), Listen (the phone reads the chapter aloud with its own
voice; nothing is sent anywhere, and the button shows only on a phone that
can), the moon; the chapter's number large in the church's colour, the
book in small capitals, the verses in the reading face; the previous and
next chapter at the end. Tapping a verse opens the verse bar: Share (the
shared share sheet, .lm-share kind=verse), the five highlighters, Note,
Copy, Save, Make a card. The tab bar stays while reading.

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

Nothing here is made up: a block with nothing real in it is left out.
The tabs read no more than the old Bible tab did (each reads only what it
shows; the dot is kept for the day in a cookie, lm_dv, so a chapter page
reads nothing for it).

The look is CSS (below), joined into the Lumen sheet by member_lumen_ui.css;
every rule sits under body.lm.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
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


def _ring(n: int, of: int, label: str) -> str:
    arc = round(119.4 * max(0, min(n, of)) / max(1, of), 1)
    return (f'<span class="lm-ring" aria-hidden="true"><svg viewBox="0 0 46 46"><circle cx="23" cy="23" r="19" fill="none" '
            f'stroke="var(--s2)" stroke-width="3.5"/><circle cx="23" cy="23" r="19" fill="none" stroke="var(--lm-gold)" '
            f'stroke-width="3.5" stroke-linecap="round" stroke-dasharray="{arc} 120"/></svg><b>{_e(label)}</b></span>')


BOOKS = ('<div class="lm-books">'
         '<a class="lm-book" href="/my/bible/books?t=ot"><b>Old Testament</b><span>39 books · Genesis to Malachi</span></a>'
         '<a class="lm-book" href="/my/bible/books?t=nt"><b>New Testament</b><span>27 books · Matthew to Revelation</span></a>'
         '</div>')


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
    # Look 5.1's: text size, listen, share (out of a tray)
    "type": '<path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/>',
    "listen": '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2'
              'v-3a2 2 0 0 1 2-2h3"/>',
    "up": '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="m16 6-4-4-4 4"/><path d="M12 2v13"/>',
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


# A shared verse's public page (member_lumen_share.VERSE_HREF): the church's
# own site, where the member app lives too, so relative.
VERSE_HREF = "/"


def verse_share(label: str, words: str, tr: str, sid: str = "", *, cls: str = "", inner: str = "Share",
                aria: str = "") -> str:
    """A verse's share control (contract 1, kind=verse), its attributes as
    the share sheet reads them: the reference and version, the words cut
    short, the story picture's id (BOOK.CH.V[-W]), the words for the message
    and the translation for the picture (member_lumen_share.link, which
    escapes it all)."""
    import bible_text as bt
    import member_lumen_share as mls
    short = bt.TRANSLATIONS[tr]["short"]
    cut = words if len(words) <= 96 else re.sub(r"\s+\S*$", "", words[:94]) + "…"
    return mls.link("verse", mls.VERSE_HREF, f"{label} · {short}", inner, sub=f"“{cut}”", sid=sid,
                    text=f"“{words}” {label} ({short})", tr=tr, cls=cls, label=aria)


def verse_id(ref_label: str, tr: str) -> str:
    """'Lamentations 3:22-23' → 'LAM.3.22-23' (the story picture's id); ''
    when it isn't one passage within a chapter."""
    import bible_text as bt
    found = bt.find_refs(ref_label or "", tr)
    if not found:
        return ""
    r = found[0][2]
    if not r.start or r.end_chapter:
        return ""
    return f"{r.book}.{r.chapter}.{r.start}" + (f"-{r.end}" if r.end and r.end != r.start else "")


def version_pick(tr: str, here: str) -> str:
    """The translation pill: KJV, and the four to choose from (a link each,
    back to this page). A <details>, so it opens without script."""
    import bible_text as bt
    sep = "&" if "?" in here else "?"
    items = "".join(
        f'<a href="{_e(here)}{sep}t={k}"{" aria-current=\"true\"" if k == tr else ""}><b>{_e(v["short"])}</b>'
        f'<span>{_e(v["name"])}</span></a>' for k, v in bt.TRANSLATIONS.items())
    cur = bt.TRANSLATIONS[tr]
    return (f'<details class="lm-ver"><summary aria-label="Translation: {_e(cur["name"])}">{_e(cur["short"])}</summary>'
            f'<nav class="lm-verpop" aria-label="Translation">{items}</nav></details>')


def render_chapter(biz, site, me, code: str, ch: int, tr: str, rng=None,
                   marks: Optional[Dict[int, Dict[str, Any]]] = None, preview: bool = False,
                   night: Optional[bool] = False, *, dot: bool = False, home: bool = False, lead: str = "") -> str:
    """Read: the Bible tab's first tab (Look 5.1), at a chapter. Today's
    reader underneath (member_portal_bible.READER_JS: tap a verse to
    highlight it, add a note, copy or save it; Aa) in the tab's frame: the
    segmented control on top (`dot`: today's devotional day isn't read
    yet), the chapter and translation pills, Aa, Listen and the moon, the
    chapter's number large, the previous and next chapter at the end, the
    tab bar below. `home`: the page is /my/bible itself (its translation
    links come back there); `lead` a quiet line over the chapter (why a
    first reader starts where they do). Lumen Next stays: the moon
    (`night`, member_lumen_look.reader_night; None when the phone decides),
    the line of how far you've read, the ink sweep, Make a card
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
    chap = f"/my/bible/{bt.slug(code)}/{ch}"
    here = "/my/bible" if home else chap
    editable = marks is not None and not preview
    found = {str(v): {"colour": m.get("colour"), "note": m.get("note"), "bookmarked": bool(m.get("bookmarked"))}
             for v, m in (marks or {}).items()}
    swatches = "".join(f'<button type="button" class="bb-sw sw-{c}" data-colour="{c}" aria-pressed="false" '
                       f'aria-label="Highlight {c}"></button>' for c in SWATCHES)
    # The share sheet reads the verse the member tapped (data-share-from="reader");
    # READ_JS keeps the same verse on the attributes as well.
    shared = (f'<a class="lm-share" data-share-kind="verse" data-share-from="reader" href="{VERSE_HREF}" '
              f'data-share-title="" data-share-sub="" data-share-id="" data-share-text="" data-share-tr="{_e(tr)}">'
              f'{_glyph("up", 16)}<span>Share</span></a>')
    dock = "" if not editable else f"""<div class="bb-dock lm-sel" id="bb-dock" role="group" aria-label="This verse" hidden>
  <div class="bb-dock-h"><strong class="bb-dock-ref"></strong>{shared}<button type="button" class="bb-x" data-act="close" aria-label="Close">{ui.icon('plus', 18)}</button></div>
  <div class="bb-dock-acts">
    <div class="bb-sws">{swatches}<button type="button" class="mp-link bb-clear" data-act="clear" hidden>Remove</button></div>
    <div class="bb-acts">
      <button type="button" data-act="note">{lm.ic('doc', 16)}<span>Note</span></button>
      <button type="button" data-act="copy">{lm.ic('share', 16)}<span>Copy</span></button>
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
    note = ('<p class="mp-muted bb-pv">Highlights and notes are private, so a preview doesn\'t show them.</p>'
            if preview else ('<p class="mp-err" role="alert">Your highlights couldn\'t load just now. Reading still works.</p>'
                             if marks is None else ""))
    data = json.dumps(found).replace("</", "<\\/")
    pill = (f'<a class="lm-pill lm-chpill" href="/my/bible/{bt.slug(code)}" aria-label="{_e(name)} {ch}: choose a book '
            f'or chapter">{_e(name)} {ch}{lm.ic("down", 15)}</a>')
    aa = ("" if not editable else
          f'<button type="button" class="lm-aa" id="bb-aa" aria-expanded="false" aria-controls="bb-aa-panel" '
          f'aria-label="Text size and font">{_glyph("type", 21)}</button>')
    say = (f'<button type="button" class="lm-aa lm-say" id="lm-say" aria-pressed="false" aria-label="Listen to this '
           f'chapter" hidden>{_glyph("listen", 21)}</button>')
    bar = f'<div class="lm-rbar">{pill}{version_pick(tr, here)}<span class="lm-sp"></span>{aa}{say}{moon}</div>'
    panel = ("" if not editable else
             '<div class="bb-aa-panel lm-aapanel" id="bb-aa-panel" hidden><div class="bb-aa-row"><span>Text size</span>'
             '<span class="bb-aa-btns"><button type="button" data-size="down" aria-label="Smaller text">A−</button>'
             '<button type="button" data-size="up" aria-label="Larger text">A+</button></span></div>'
             '<div class="bb-aa-row"><span>Font</span><span class="bb-aa-btns"><button type="button" data-font="serif">Book</button>'
             '<button type="button" data-font="sans">Clean</button></span></div></div>')

    def step(to, cls: str) -> str:
        if not to:
            return "<span></span>"
        c, n = to
        label = mpb.where_label(c, n)
        inner = (f'{lm.ic("back", 16)}<span>{_e(label)}</span>' if cls == "prev" else
                 f'<span>{_e(label)}</span>{lm.ic("chevron", 16)}')
        return (f'<a class="lm-rstep {cls}" href="/my/bible/{bt.slug(c)}/{n}" aria-label="{"Previous" if cls == "prev" else "Next"}: '
                f'{_e(label)}">{inner}</a>')
    book = "Psalms" if code == "PSA" else bt.NAME[code]
    head = (f'<h1 class="lm-chap"><span class="mp-sr">{_e(name)} {ch}</span><b aria-hidden="true">{ch}</b>'
            f'<span aria-hidden="true">{_e(book)}</span></h1>')
    first = f'<p class="lm-rlead">{_e(lead)}</p>' if lead else ""
    body = f"""{bar}
{panel}
{note}
{first}
{head}
<div class="bb-read lm-read" data-book="{code}" data-ch="{ch}" data-tr="{tr}" data-label="{_e(name)} {ch}">
{mpb.chapter_html(code, ch, tr, rng, marks=marks if editable else None)}
</div>
<nav class="lm-rnav" aria-label="Chapters">{step(prev, "prev")}{step(nxt, "next")}</nav>
{_src(tr)}
{dock}
{sheet}
<script type="application/json" id="bb-marks">{data}</script>"""
    return _shell(biz, site, f"{name} {ch}", body, tab="bible", who=me, lumen_reader=True,
                  script=(mpb.READER_JS if editable else "") + READER_MORE_JS + READ_JS + SEG_JS,
                  lumen_top=seg("read", dot, prog=True))


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


# ─── the Bible tab: Read · Devotional · Plans · Saved (Look 5.1) ──────

# (key, label, address) for each tab of the segmented control.
TABS = (("read", "Read", "/my/bible"), ("devotional", "Devotional", "/my/bible?tab=devotional"),
        ("plans", "Plans", "/my/bible?tab=plans"), ("saved", "Saved", "/my/bible?tab=saved"))
# ?tab= values the server knows; anything else is Read.
TAB_KEYS = ("read", "devotional", "plans", "saved", "search")
# Whether today's day of the devotional on top is unread, kept for the day
# on the member's phone ("2026-11-20.1"), so a chapter page shows the dot
# without reading anything. The tabs that read the devotionals anyway write
# it; opening a devotional's day clears it (member_portal_bible.serve).
DEVO_COOKIE = "lm_dv"
# The plans' letter squares in the mock: a letter and a family colour each.
PLAN_MARKS = {"bible-year": ("B", "violet"), "nt-260": ("N", "teal"), "gospels-30": ("G", "coral"),
              "psalms-proverbs-31": ("P", "gold")}
# About how many words a minute a chapter is read at (devotionals.minutes reads 170).
WPM = 170
# The newest saved verses shown on Saved; the rest are on /my/bible/notes.
SAVED_MAX = 40


def dot_cookie(raw: Any, today: date) -> Optional[bool]:
    """The dot from its cookie: True/False when it was decided today, None
    when there is nothing kept for today (the tab reads it)."""
    d, _, v = str(raw or "").partition(".")
    if d != today.isoformat() or v not in ("0", "1"):
        return None
    return v == "1"


def dot_value(dot: bool, today: date) -> str:
    return f"{today.isoformat()}.{1 if dot else 0}"


def devo_unread(sts) -> bool:
    """Whether the devotional on top of the Devotional tab is running and
    today's day of it isn't read (member_lumen_devotional.pick)."""
    import member_lumen_devotional as mld
    got = mld.pick(sts or [])
    if not got or got[0] != "today":
        return False
    st = got[2]
    return bool(st.get("now")) and st["now"] not in st["done"]


def seg(active: str, dot: bool, *, prog: bool = False) -> str:
    """The segmented control on top of every Bible tab, and the search
    button: the page's top bar (_shell's lumen_top, in place of the church's
    bar). The dot on Devotional says today's day isn't read; it isn't
    shown on the Devotional tab itself. `prog`: the reader's line of how
    far you've read rides on the bar's lower edge."""
    import member_lumen_ui as lm
    links = []
    for key, label, href in TABS:
        cur = ' aria-current="page"' if key == active else ""
        nd = ('<span class="lm-nd" aria-hidden="true"></span><span class="mp-sr"> (today\'s day isn\'t read yet)</span>'
              if key == "devotional" and dot and active != "devotional" else "")
        links.append(f'<a class="lm-bsg" href="{href}"{cur}>{label}{nd}</a>')
    find = ' aria-current="page"' if active == "search" else ""
    line = '<span class="lm-rprog" aria-hidden="true"></span>' if prog else ""
    return (f'<div class="lm-bseg"><nav class="lm-bsegs" aria-label="Bible">{"".join(links)}</nav>'
            f'<a class="lm-icb lm-bfind" href="/my/bible?tab=search" aria-label="Search the Bible"{find}>'
            f'{lm.ic("search", 22)}</a>{line}</div>')


def _shell_tab(biz, site, me, title: str, active: str, dot: bool, body: str, script: str = "") -> str:
    """A Bible tab's page: its segmented control (seg) is the bar at the top,
    in place of the church's bar (Look 5.1)."""
    from member_portal import _shell
    return _shell(biz, site, title, body, tab="bible", who=me, script=script + SEG_JS, lumen_top=seg(active, dot))


def _plain(html_text: str) -> str:
    """A verse's markup (escaped words, the translators' words in <i>) as text."""
    from html import unescape
    return unescape(re.sub(r"<[^>]+>", "", html_text or "")).strip()


def _words(reading, tr: str) -> int:
    """The words in a day of a reading plan ([(book, first, last)])."""
    import bible_text as bt
    return sum(t.count(" ") + 1 for code, a, b in reading for n in range(a, b + 1) for _, t in (bt.chapter(code, n, tr) or []))


def chapters_minutes(reading, tr: str) -> int:
    """About how long a day of a reading plan takes: its words at WPM."""
    return max(1, round(_words(reading, tr) / WPM))


def _when(raw: Any, today: date) -> str:
    """'today', 'yesterday', 'Tuesday' (this week), 'Nov 3', 'Nov 3, 2025'."""
    from datetime import datetime
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return ""
    days = (today - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%b')} {d.day}" + ("" if d.year == today.year else f", {d.year}")


# ─── Devotional ──────────────────────────────────────────────────────


def week(dev: Dict[str, Any], st: Dict[str, Any], today: date) -> str:
    """This week of the devotional on top, Monday to Sunday: a circle a day,
    its number, filled once read, ringed today, plain ahead (and plain on a
    day missed: it's still there to read). A day of the week outside the
    devotional is an empty place."""
    from datetime import timedelta
    start, count = st.get("start"), int(st.get("count") or 0)
    if not start or not count:
        return ""
    monday = today - timedelta(days=today.weekday())
    cells = []
    for i in range(7):
        d = monday + timedelta(days=i)
        n = (d - start).days + 1
        wd = d.strftime("%a")
        if not 1 <= n <= count:
            cells.append(f'<li class="lm-wd is-none"><b aria-hidden="true"></b><span aria-hidden="true">{wd}</span></li>')
            continue
        done = n in st["done"]
        cls = "is-done" if done else ("is-today" if d == today else ("is-ahead" if d > today else ""))
        said = f"Day {n}, {d.strftime('%A')}" + (", read" if done else "") + (", today" if d == today else "")
        inner = f'<b>{n}</b><span>{wd}</span>'
        if n <= st["upto"]:
            cur = ' aria-current="date"' if d == today else ""
            cells.append(f'<li class="lm-wd {cls}"><a href="/my/bible/plans/{_e(dev["id"])}/{n}" aria-label="{_e(said)}"{cur}>'
                         f'{inner}</a></li>')
        else:
            cells.append(f'<li class="lm-wd {cls}"><span class="lm-wdx" role="img" aria-label="{_e(said)}">{inner}</span></li>')
    return f'<ol class="lm-week" aria-label="This week of {_e(dev.get("title") or "the devotional")}">{"".join(cells)}</ol>'


def vod(tr: str) -> str:
    """The verse of the day (member_portal_bible.verse_of_day) on the ivory
    card, opening its chapter, with Share (kind=verse) by its heading."""
    import bible_text as bt
    import member_portal_bible as mpb
    v = mpb.verse_of_day(tr)
    if not v:
        return ""
    name = bt.TRANSLATIONS[tr]["name"]
    share = verse_share(v["label"], _plain(v["html"]), tr, verse_id(v["label"], tr), cls="lm-more lm-vodshare",
                        aria="Share the verse of the day")
    return (f'<section aria-labelledby="lm-vod-h"><div class="lm-sec"><h2 class="lm-h2" id="lm-vod-h">Verse of the day</h2>'
            f'{share}</div><a class="lm-vod" href="{_e(v["href"])}"><span class="lm-vod-k">{_e(v["label"])}</span>'
            f'<q>{v["html"]}</q><small>{_e(name)}</small></a></section>')


def more_devotionals(biz, site, sts, shown_id: Optional[str]) -> str:
    """The church's other devotionals the member can read now (running,
    any-time, ended: not one still to come), as covers, two a row."""
    import member_app_photos as photos
    import member_app_ui as ui
    import member_portal_devotionals as mpd
    order = {"running": 0, "new": 1, "over": 2, "finished": 3}
    rest = sorted((x for x in sts or [] if str(x[0].get("id")) != str(shown_id) and x[1]["kind"] in order),
                  key=lambda x: order[x[1]["kind"]])[:4]
    if not rest:
        return ""
    pool = photos.photos(biz, site)
    used: set = set()
    covers = []
    for i, (d, st) in enumerate(rest):
        title = d.get("title") or "Devotional"
        url, look = photos.choose(biz, f"devotional:{d['id']}", pool, title=title, look="church", used=used)
        art = ui.photo(url, look=look) if url else ""
        n = st["count"]
        small = f"{n} day{'' if n == 1 else 's'}" if n else (d.get("kind") or "Devotional")
        if st["kind"] == "running" and st.get("now"):
            small = f"Day {st['now']} of {n}"
        cls = "has-ph" if url else f"cv-{COVERS[i % len(COVERS)]}"
        covers.append(f'<a class="lm-cv lm-mcov {cls}" href="{_e(mpd._target(d, st))}">{art}<b>{_e(title)}</b>'
                      f'<small>{_e(small)}</small></a>')
    import member_lumen_ui as lm
    return (f'<section aria-labelledby="lm-mdev-h">{lm.section("More devotionals", "/my/bible/plans", "All", hid="lm-mdev-h")}'
            f'<div class="lm-mcovs">{"".join(covers)}</div></section>')


def render_devotional(biz, site, me, tr: str, sts, *, dot: bool = False, preview: bool = False,
                      today: Optional[date] = None) -> str:
    """Devotional: today's devotional (member_lumen_devotional.card, with its
    fallbacks: what's next, the last one again, one to start), this week's
    days, the verse of the day, more devotionals. `sts` None: the
    devotionals couldn't load (said so; the verse still shows)."""
    import devotional_voice as dvv
    import member_lumen_devotional as mld
    import member_lumen_ui as lm
    today = today or date.today()
    parts: List[str] = []
    script = ""
    if sts is None:
        parts.append('<p class="mp-err lm-btabmsg" role="alert">The church\'s devotionals couldn\'t load just now. '
                     'Please try again in a moment.</p>')
        shown = None
    else:
        card, shown = mld.card(biz, sts, listen=dvv.can_speak()) if sts else ("", None)
        if card:
            parts.append(card)
            if "data-devo-listen" in card:
                script = mld.CARD_JS
            got = mld.pick(sts)
            if got and got[0] == "today":
                wk = week(got[1], got[2], today)
                if wk:
                    parts.append(f'<section aria-labelledby="lm-week-h">{lm.section("This week", hid="lm-week-h")}{wk}</section>')
        else:
            parts.append(f'<p class="lm-quiet lm-btabmsg">When {_e(_short(biz))} shares a devotional, it opens here, a day at a '
                         f'time.</p>')
    parts.append(vod(tr))
    if sts:
        parts.append(more_devotionals(biz, site, sts, shown["id"] if shown else None))
    body = '<h1 class="mp-sr">Devotional</h1>' + "".join(p for p in parts if p)
    return _shell_tab(biz, site, me, "Devotional", "devotional", dot, body, script)


# ─── Plans ───────────────────────────────────────────────────────────


def _bigring(n: int, of: int) -> str:
    """The plan's ring in the mock: 64px, how far round, the day inside."""
    arc = round(175.9 * max(0, min(n, of)) / max(1, of), 1)
    return (f'<span class="lm-ringp" aria-hidden="true"><svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" fill="none" '
            f'stroke="var(--s2)" stroke-width="5"/><circle cx="32" cy="32" r="28" fill="none" stroke="var(--lm-gold)" '
            f'stroke-width="5" stroke-linecap="round" stroke-dasharray="{arc} 176"/></svg><b>{n}</b></span>')


def plan_title(title: str) -> str:
    """'The Gospels in 30 days' → 'The Gospels' (the days are said beside it)."""
    return re.sub(r"\s+in (\d+ days|a month|a year)$", "", title or "") or title


def _aplan(kicker: str, href: str, n: int, of: int, reading, read_href: str, tr: str, *, read: bool = False,
           sample: str = "") -> str:
    """A plan running today: the ring (day n), what it is and the day, today's
    reading, about how long, Read."""
    import reading_plans as rp
    mins = chapters_minutes(reading, tr)
    quiet = f"About {mins} minute{'' if mins == 1 else 's'}" + (" · read today" if read else "")
    return (f'<div class="lm-aplan">{_bigring(n, of)}<a class="lm-aplan-t" href="{_e(href)}"><small>{_e(kicker)} · day {n}'
            f'{sample}</small><b>Today: {_e(rp.label(reading))}</b><small>{_e(quiet)}</small></a>'
            f'<a class="lm-btn sm lm-aplan-go" href="{_e(read_href)}" aria-label="Read {_e(rp.label(reading))}">Read</a></div>')


def render_plans_tab(biz, site, me, tr: str, mine: Optional[Dict[str, date]], church_today: Optional[Dict[str, Any]],
                     church_done: Optional[set], *, dot: bool = False, preview: bool = False,
                     today: Optional[date] = None) -> str:
    """Plans: the reading plans running for this member (the church's, then
    their own) as rings with today's reading and Read, then the plans to
    start (member_portal_devotionals' start). `mine` None: their plans
    couldn't load (said so; the plans to start still show)."""
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_ui as lm
    import member_portal_devotionals as mpd
    import reading_plans as rp
    today = today or date.today()
    active: List[str] = []
    if church_today:
        t = church_today
        reading = rp.schedule(t["key"])[t["day"] - 1]
        tag = ui.sample_tag() if samples.is_sample(t) else ""
        read = bool(church_done) and t["day"] in church_done
        active.append(_aplan("With your church", "/my/reading", t["day"], t["of"], reading, t["href"], tr, read=read,
                             sample=tag))
    starts: List[str] = []
    for key, meta in rp.PLANS.items():
        started = (mine or {}).get(f"reading:{key}")
        plan = mpd.own_plan(key, started)
        if plan:
            now = rp.day_number(plan, today)
            if now:
                reading = rp.schedule(key)[now - 1]
                active.append(_aplan(plan_title(meta["title"]), f"/my/bible/plans/{key}", now, plan["days"], reading,
                                     rp.href(reading), tr))
            else:
                done = rp.readable_upto(plan, today) >= plan["days"]
                active.append(f'<a class="lm-aplan is-quiet" href="/my/bible/plans/{key}">{_bigring(plan["days"] if done else 0, plan["days"])}'
                              f'<span class="lm-aplan-t"><small>{_e(meta["title"])}</small>'
                              f'<b>{"You finished it" if done else "It starts today"}</b><small>See the plan</small></span>'
                              f'{lm.ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a>')
            continue
        letter, hue = PLAN_MARKS.get(key, (meta["title"][:1], "gold"))
        per = _plan_minutes(key, tr)
        starts.append(f'<form class="lm-pstart" method="post" action="/my/bible/plans/start"><input type="hidden" name="plan" '
                      f'value="reading:{key}"><button type="submit" aria-label="Start {_e(meta["title"])}">'
                      f'<span class="lm-pc h-{hue}" aria-hidden="true">{letter}</span><span class="lm-pstart-t"><b>{_e(meta["title"])}</b>'
                      f'<small>{meta["days"]} days · {per} min a day</small></span>'
                      f'<span class="lm-pstart-go">Start</span></button></form>')
    parts: List[str] = []
    if mine is None and not preview:
        parts.append('<p class="mp-err lm-btabmsg" role="alert">Your plans couldn\'t load just now. Please try again in a moment.</p>')
    if active:
        parts.append(f'<section aria-label="Your reading plans">{"".join(active)}</section>')
    elif mine is not None:
        parts.append('<p class="lm-quiet lm-btabmsg">A plan reads the Bible a little each day. Start one below, and today\'s '
                     'reading waits here.</p>')
    if starts:
        parts.append(f'<section aria-labelledby="lm-pstart-h">{lm.section("Start a plan", hid="lm-pstart-h")}'
                     f'<div class="lm-pstarts">{"".join(starts)}</div></section>')
    parts.append('<p class="lm-bmore"><a class="lm-more" href="/my/bible/plans">Plans &amp; devotionals'
                 f'{lm.ic("chevron", 15)}</a></p>')
    return _shell_tab(biz, site, me, "Plans", "plans", dot, '<h1 class="mp-sr">Reading plans</h1>' + "".join(parts))


@lru_cache(maxsize=None)
def _plan_minutes(key: str, tr: str) -> int:
    """About how long a day of a plan takes, on average (its words at WPM)."""
    import reading_plans as rp
    days = rp.schedule(key)
    return max(1, round(sum(_words(r, tr) for r in days) / max(1, len(days)) / WPM))


# ─── Saved ───────────────────────────────────────────────────────────


def render_saved(biz, site, me, tr: str, marks: Optional[Sequence[Dict[str, Any]]], *, dot: bool = False,
                 preview: bool = False, today: Optional[date] = None) -> str:
    """Saved: the member's highlights, notes and saved verses, newest first
    (member_bible_marks), each a colour bar, the verse, the reference and
    when, and their note; a tap opens the reader at that verse."""
    import bible_text as bt
    import member_lumen_ui as lm
    import member_portal_bible as mpb
    today = today or date.today()
    if preview:
        return _shell_tab(biz, site, me, "Saved", "saved", dot, '<p class="lm-quiet lm-btabmsg">Highlights and notes are private to '
                          'each member, so a preview doesn\'t show them.</p>')
    if marks is None:
        return _shell_tab(biz, site, me, "Saved", "saved", dot, '<p class="mp-err lm-btabmsg" role="alert">Your highlights and notes '
                          'couldn\'t load just now. They\'re still saved.</p>')
    if not marks:
        return _shell_tab(biz, site, me, "Saved", "saved", dot, (
            '<div class="lm-saved0"><p class="lm-saved0-t">Nothing saved yet</p><p class="lm-quiet">Tap any verse while you '
            'read to highlight it, add a private note, or save it. It shows up here.</p>'
            '<a class="lm-btn sm" href="/my/bible">Start reading</a></div>'))
    rows = []
    for m in list(marks)[:SAVED_MAX]:
        try:
            code, ch, v = str(m["book"]), int(m["chapter"]), int(m["verse"])
        except (KeyError, TypeError, ValueError):
            continue
        if code not in bt.NAME:
            continue
        text = dict(bt.chapter(code, ch, tr) or []).get(v, "")
        if not text:
            continue
        note = (m.get("note") or "").strip()
        colour = m.get("colour") if m.get("colour") in SWATCHES else ""
        what = "highlighted" if colour else ("noted" if note else "saved")
        when = _when(m.get("updated_at"), today)
        ref = f"{mpb.where_label(code, ch)}:{v}"
        meta = " · ".join(p for p in (ref, f"{what} {when}".strip()) if p)
        bar = f'<i class="sw-{colour}" aria-hidden="true"></i>' if colour else '<i class="is-plain" aria-hidden="true"></i>'
        rows.append(f'<li><a class="lm-hlr" href="/my/bible/{bt.slug(code)}/{ch}#v{v}">{bar}<span class="lm-hlr-t">'
                    f'<span class="lm-hlr-v">{mpb._verse_html(text, tr)}</span>'
                    + (f'<span class="lm-hlr-n">{_e(note)}</span>' if note else "")
                    + f'<small>{_e(meta)}</small></span></a></li>')
    more = (f'<p class="lm-bmore"><a class="lm-more" href="/my/bible/notes">Every highlight and note'
            f'{lm.ic("chevron", 15)}</a></p>')
    body = (f'<h1 class="mp-sr">Saved</h1><ul class="lm-hls">{"".join(rows)}</ul>{more}'
            f'<p class="lm-bpriv">Only you can see these.</p>')
    return _shell_tab(biz, site, me, "Saved", "saved", dot, body)


# ─── Search ──────────────────────────────────────────────────────────


def render_find(biz, site, me, tr: str, *, query: str = "", places=None, missed: bool = False, slow: bool = False,
                dot: bool = False) -> str:
    """The search button's page: find a passage or a word (today's ?q=),
    the chapters read lately, the books."""
    import member_lumen_ui as lm
    import member_portal_bible as mpb
    err = ('<p class="mp-err" role="alert">We couldn\'t find that passage or word. Try something like John 3:16, '
           'Psalm 23 or shepherd.</p>' if missed else
           '<p class="mp-err" role="alert">That\'s a lot of searching at once. Wait a minute, then try again.</p>'
           if slow else "")
    recent = mpb._chips(places or [])
    body = (f'<h1 class="mp-sr">Search the Bible</h1>{field(query, autofocus=not query)}{err}'
            + (f'<section aria-labelledby="lm-recent-h">{lm.section("Recently read", hid="lm-recent-h")}{recent}</section>'
               if recent else "")
            + f'<section aria-labelledby="lm-books-h">{lm.section("Books", hid="lm-books-h")}{BOOKS}</section>{_src(tr)}')
    return _shell_tab(biz, site, me, "Search", "search", dot, body)


# The tabs' own script: switching tabs replaces the page in the history (the
# back button leaves the Bible instead of walking back through its tabs;
# tapping the tab you're on goes back to the top). The segmented control is
# the page's top bar, so it needs no placing.
SEG_JS = r"""<script>(function(){var s=document.querySelector('.lm-bseg');if(!s)return;
s.addEventListener('click',function(e){var a=e.target.closest?e.target.closest('a.lm-bsg,a.lm-bfind'):null;
 if(!a||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();
 if(a.getAttribute('aria-current')==='page'){var q=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({top:0,behavior:q?'auto':'smooth'});return;}
 location.replace(a.href);});
})();</script>"""

# The reader's Look 5.1 moments, beside today's reader script and Lumen
# Next's (which it leaves alone): the verse bar sits just over the tab bar
# and the mini player when one is showing (member_mini; measured as the bar
# opens; its CSS place is the fallback); its Share carries
# the verse it was opened on (data-share-*, as the share sheet,
# member_lumen_share, reads it); the translation pill closes on a
# tap outside it; Listen reads the chapter aloud with the phone's own voice,
# verse by verse from the one picked (or the first), marking the one being
# read; nothing is sent anywhere, and the button shows only where the phone
# can speak.
READ_JS = r"""<script>(function(){
var read=document.querySelector('.bb-read');if(!read)return;
var dock=document.getElementById('bb-dock'),sh=dock?dock.querySelector('.bb-dock-h .lm-share'):null;
var nav=document.querySelector('.mb-nav'),toast=document.getElementById('bb-toast');
function lift(){if(!dock)return;var r=nav?nav.getBoundingClientRect():null,up=0,m=document.querySelector('.lm-mini');
 if(r&&r.height&&r.top<window.innerHeight&&r.width>window.innerWidth*.6)up=Math.round(window.innerHeight-r.top);
 if(m&&!m.hidden){var q=m.getBoundingClientRect();if(q.height&&q.top<window.innerHeight)up=Math.max(up,Math.round(window.innerHeight-q.top));}
 dock.style.bottom=up?(up+8)+'px':'';if(toast)toast.style.bottom=up?(up+184)+'px':'';}
lift();window.addEventListener('resize',lift);
if(dock&&window.MutationObserver)new MutationObserver(function(){if(!dock.hidden)lift();}).observe(dock,{attributes:true,attributeFilter:['hidden']});
var label=read.getAttribute('data-label')||'',tr=(read.getAttribute('data-tr')||'').toUpperCase(),bk=read.getAttribute('data-book')||'',
 ch=read.getAttribute('data-ch')||'';
function words(s){var c=s.cloneNode(true);c.querySelectorAll('sup,.bb-nm,.bb-bm').forEach(function(x){x.remove();});return c.textContent.replace(/\s+/g,' ').trim();}
if(sh&&window.MutationObserver){var put=function(){var s=read.querySelector('.bb-v.is-sel');if(!s)return;
  var v=s.getAttribute('data-v'),t=words(s),ref=label+':'+v,cut=t.length>96?t.slice(0,94).replace(/\s+\S*$/,'')+'\u2026':t;
  sh.setAttribute('data-share-title',ref+' \u00b7 '+tr);sh.setAttribute('data-share-sub','\u201c'+cut+'\u201d');
  sh.setAttribute('data-share-id',bk+'.'+ch+'.'+v);sh.setAttribute('data-share-text','\u201c'+t+'\u201d '+ref+' ('+tr+')');};
 new MutationObserver(put).observe(read,{subtree:true,attributes:true,attributeFilter:['class']});}
document.addEventListener('click',function(e){[].forEach.call(document.querySelectorAll('details.lm-ver[open]'),function(d){if(!d.contains(e.target))d.open=false;});});
document.addEventListener('keydown',function(e){if(e.key==='Escape')[].forEach.call(document.querySelectorAll('details.lm-ver[open]'),function(d){d.open=false;d.querySelector('summary').focus();});});
var say=document.getElementById('lm-say'),ss=window.speechSynthesis;
if(!say||!ss||!window.SpeechSynthesisUtterance)return;
say.hidden=false;var on=false,items=[],i=0,now=null,calm=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function mark(el){if(now)now.classList.remove('is-say');now=el;if(el){el.classList.add('is-say');var r=el.getBoundingClientRect();
 if(r.top<120||r.bottom>window.innerHeight-120)el.scrollIntoView({block:'center',behavior:calm?'auto':'smooth'});}}
function list(){var vs=[].slice.call(read.querySelectorAll('.bb-v'));
 if(vs.length)return vs.map(function(s){return{el:s,text:words(s)};});
 return [].slice.call(read.querySelectorAll('.bb-text p')).map(function(p){return{el:p,text:words(p)};});}
function stop(){on=false;ss.cancel();mark(null);say.setAttribute('aria-pressed','false');say.setAttribute('aria-label','Listen to this chapter');}
function next(){if(!on)return;if(i>=items.length){stop();return;}var it=items[i++];if(!it.text){next();return;}mark(it.el);
 var u=new SpeechSynthesisUtterance(it.text);u.lang='en-US';u.rate=.95;u.onend=function(){if(on)next();};
 u.onerror=function(ev){if(ev&&(ev.error==='interrupted'||ev.error==='canceled'))return;stop();};ss.speak(u);}
say.addEventListener('click',function(){if(on){stop();return;}items=list();var s=read.querySelector('.bb-v.is-sel');
 i=s?Math.max(0,items.map(function(x){return x.el;}).indexOf(s)):0;on=true;say.setAttribute('aria-pressed','true');
 say.setAttribute('aria-label','Stop listening');ss.cancel();next();});
window.addEventListener('pagehide',function(){if(on)stop();});
})();</script>"""


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
/* a devotional's cover */
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
body.lm .lm-quiet{margin:0;font:400 14.5px/1.5 var(--mb-ui);color:var(--fg2);}
/* the books */
body.lm .lm-books{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
body.lm .lm-book{display:block;padding:18px 16px;border-radius:18px;background:var(--s1);color:var(--fg);text-decoration:none;}
body.lm .lm-book b{display:block;font:400 22px/1.05 var(--mb-serif);}
body.lm .lm-book span{display:block;margin-top:6px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
body.lm .lm-src{margin:28px 0 0;font:500 12px/1.4 var(--mb-ui);color:var(--fg3);}
/* a devotional's day keeps the bar's middle (member_lumen_devotional) */
body.lm .mb-top.lm-mid .mb-top-right{flex:1;justify-content:flex-end;}
body.lm .lm-barmid{flex:none;}
/* the Bible tab (Look 5.1): the segmented control is the bar at the top, no church bar over it; the search button
   beside it; a hairline under it */
body.lm{--lm-wk:#10261C;--lm-wk-ink:#BDE3C2;}
body.lm .mb-top.lm-own-bible{min-height:0;padding-top:calc(8px + env(safe-area-inset-top,0px));padding-bottom:10px;
  padding-right:max(8px,env(safe-area-inset-right,0px));box-shadow:0 1px 0 var(--lm-line);}
body.lm .lm-bseg{flex:1;min-width:0;display:flex;align-items:center;gap:6px;}
body.lm .lm-bsegs{flex:1;display:flex;padding:3px;border-radius:14px;background:var(--s1);}
body.lm .lm-bsg{flex:1 1 0;height:36px;padding:0 8px;border-radius:11px;display:flex;align-items:center;justify-content:center;gap:6px;
  color:var(--fg2);font:650 14px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;-webkit-tap-highlight-color:transparent;}
body.lm .lm-bsg[aria-current]{background:var(--lm-raise);color:var(--fg);box-shadow:0 1px 3px var(--lm-shadow),0 0 0 .5px var(--lm-line);}
body.lm .lm-nd{width:6px;height:6px;flex:none;border-radius:50%;background:var(--acc-fill);}
body.lm .lm-bfind{width:44px;height:44px;}
body.lm .lm-bfind[aria-current]{color:var(--acc);}
body.lm .lm-btabmsg{margin-top:24px;}
body.lm .lm-bmore{margin:22px 0 0;}
body.lm .lm-bpriv{margin:12px 0 0;font:500 12.5px/1.4 var(--mb-ui);color:var(--fg3);}
/* Read: the chapter and translation pills, Aa, Listen, the moon */
body.lm .lm-rbar{display:flex;align-items:center;gap:6px;margin:14px -12px 0 0;}
body.lm .lm-pill{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 14px;border-radius:18px;background:var(--s1);color:var(--fg);
  font:650 14px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;}
body.lm .lm-chpill{height:40px;padding:0 12px 0 14px;gap:4px;border-radius:20px;font:700 15px/1 var(--mb-ui);}
body.lm .lm-ver{position:relative;flex:none;}
body.lm .lm-ver>summary{display:grid;place-items:center;height:40px;padding:0 12px;border-radius:20px;box-shadow:inset 0 0 0 1.5px var(--lm-line);
  color:var(--fg);font:700 12.5px/1 var(--mb-ui);letter-spacing:.06em;list-style:none;cursor:pointer;-webkit-tap-highlight-color:transparent;}
body.lm .lm-ver>summary::-webkit-details-marker{display:none;}
body.lm .lm-ver[open]>summary{background:var(--s1);box-shadow:none;}
body.lm .lm-verpop{position:absolute;z-index:13;top:calc(100% + 8px);left:0;width:250px;padding:6px;border-radius:16px;background:var(--bg);
  box-shadow:0 0 0 1px var(--lm-line),0 14px 36px var(--lm-shadow);}
body.lm .lm-verpop a{display:flex;align-items:baseline;gap:10px;padding:12px;border-radius:11px;color:var(--fg2);text-decoration:none;}
body.lm .lm-verpop b{width:36px;flex:none;font:700 12.5px/1 var(--mb-ui);letter-spacing:.06em;color:var(--fg);}
body.lm .lm-verpop span{font:500 14px/1.2 var(--mb-ui);}
body.lm .lm-verpop a[aria-current]{background:var(--s1);color:var(--fg);}
body.lm .lm-sp{flex:1;}
body.lm .lm-aa{width:40px;height:40px;border:0;border-radius:50%;background:none;color:var(--fg);font:600 16px/1 var(--mb-serif);cursor:pointer;}
body.lm .lm-rbar .lm-aa{width:44px;height:44px;display:grid;place-items:center;padding:0;}
body.lm .lm-aa[aria-expanded=true]{background:var(--lm-gold-9);color:var(--lm-gold);}
body.lm .lm-say[hidden]{display:none;}
body.lm .lm-say[aria-pressed=true]{background:var(--lm-tint-10);color:var(--acc);}
body.lm .lm-aapanel{position:fixed;z-index:16;top:calc(64px + env(safe-area-inset-top,0px));left:12px;right:12px;max-width:420px;margin:0 auto;
  padding:14px 16px;border-radius:18px;background:var(--bg);box-shadow:0 0 0 1px var(--lm-line),0 14px 36px var(--lm-shadow);gap:12px;}
body.lm .lm-aapanel[hidden]{display:none;}
body.lm .lm-aapanel .bb-aa-btns button{background:var(--s1);border-radius:11px;font:650 13.5px/1 var(--mb-ui);}
body.lm .lm-rbar+.lm-aapanel{position:static;max-width:none;margin:12px 0 0;box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-rlead{margin:18px 0 0;font:500 13.5px/1.45 var(--mb-ui);color:var(--fg2);}
/* the chapter: its number large in the church's colour, the book in small capitals, the verses in the reading face */
body.lm .lm-chap{display:block;margin:14px 0 14px;}
body.lm .lm-chap b{display:block;font:300 92px/1 var(--mb-serif);color:var(--acc);letter-spacing:-.04em;}
body.lm .lm-chap>span:last-child{display:block;margin-top:2px;font:700 11px/1.3 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;
  color:var(--fg3);}
body.lm .lm-read{padding-bottom:4px;}
body.lm .lm-read .bb-text{margin:0;color:var(--fg);}
body.lm .lm-read .bb-text.sz-s{font-size:17px;}
body.lm .lm-read .bb-text.sz-l{font-size:23px;}
body.lm .lm-read .bb-text.f-sans{font-family:var(--mb-ui);}
body.lm .lm-read .bb-n{font:700 10.5px/1 var(--mb-ui);color:var(--fg3);margin:0 4px 0 2px;vertical-align:4px;}
body.lm .lm-read .bb-v{border-radius:3px;transition:background-color .3s;}
body.lm .lm-read .bb-v.is-sel{text-decoration:underline;text-decoration-color:var(--acc);text-decoration-thickness:2px;text-underline-offset:5px;}
body.lm .lm-read .is-say{text-decoration:underline dotted;text-decoration-color:var(--fg3);text-decoration-thickness:2px;text-underline-offset:5px;}
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
body.lm .lm-read~.lm-src{margin-top:18px;}
/* the chapters before and after, at the end */
body.lm .lm-rnav{display:flex;gap:10px;margin:26px 0 0;}
body.lm .lm-rnav>*{flex:1;min-width:0;}
body.lm .lm-rstep{height:48px;padding:0 14px;border-radius:24px;background:var(--s1);color:var(--fg);display:flex;align-items:center;
  justify-content:center;gap:4px;font:650 14px/1 var(--mb-ui);text-decoration:none;}
body.lm .lm-rstep span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
/* the verse bar: the verse, Share, the highlighters, the rest; over the tab bar */
body.lm .bb-dock{left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom,0px));max-width:576px;padding:12px 12px 14px 16px;
  border-radius:18px;background:var(--bg);box-shadow:0 0 0 1px var(--lm-line),0 12px 32px var(--lm-shadow);}
body.lm.lm-tab .bb-dock{bottom:calc(76px + env(safe-area-inset-bottom,0px));}
body.lm.lm-tab.lm-mini-pad .bb-dock{bottom:calc(158px + env(safe-area-inset-bottom,0px));}
body.lm .bb-dock-h{gap:8px;}
body.lm .bb-dock-ref{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:700 14px/1.2 var(--mb-ui);}
body.lm .bb-dock-h .lm-share{flex:none;display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 13px;border-radius:18px;
  box-shadow:inset 0 0 0 1.5px var(--lm-line);color:var(--fg);font:650 13.5px/1 var(--mb-ui);text-decoration:none;}
body.lm .bb-x{width:32px;height:32px;background:var(--s1);}
body.lm .bb-sws{gap:10px;margin-top:12px;}
body.lm .bb-sw{width:30px;height:30px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.08);}
body.lm .bb-dock .bb-sw.sw-gold{background:rgba(233,182,90,.6);}
body.lm .bb-dock .bb-sw.sw-pink{background:rgba(246,112,150,.5);}
body.lm .bb-dock .bb-sw.sw-teal{background:rgba(46,196,160,.45);}
body.lm .bb-dock .bb-sw.sw-violet{background:rgba(150,135,255,.48);}
body.lm .bb-dock .bb-sw.sw-coral{background:rgba(255,140,90,.52);}
body.lm .bb-sw[aria-pressed=true]{box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--fg);}
body.lm .bb-acts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:12px;}
body.lm .bb-acts button{flex-direction:column;justify-content:center;gap:5px;min-height:52px;padding:8px 2px;border-radius:14px;
  background:var(--s1);color:var(--fg);font:650 12px/1.1 var(--mb-ui);}
body.lm .bb-acts button span{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
body.lm .bb-acts button .lm-ic{color:var(--fg);}
body.lm .bb-acts button[aria-pressed=true] .lm-ic{color:var(--lm-gold);fill:var(--gold);}
body.lm .bb-toast{bottom:calc(200px + env(safe-area-inset-bottom,0px));}
body.lm.lm-tab .bb-toast{bottom:calc(264px + env(safe-area-inset-bottom,0px));}
@media (min-width:1100px){
  body.lm.lm-tab .bb-dock{bottom:calc(12px + env(safe-area-inset-bottom,0px));}
  body.lm.lm-tab .bb-toast{bottom:calc(200px + env(safe-area-inset-bottom,0px));}
}
/* Devotional: this week, the verse of the day, more devotionals */
body.lm .lm-week{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin:0;padding:0;list-style:none;}
body.lm .lm-wd>a,body.lm .lm-wd>.lm-wdx,body.lm .lm-wd.is-none{display:flex;flex-direction:column;align-items:center;gap:6px;padding:4px 0;
  border-radius:14px;color:var(--fg3);font:650 11.5px/1 var(--mb-ui);text-decoration:none;}
body.lm .lm-wd b{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:var(--s1);color:var(--fg);
  font:600 14px/1 var(--mb-ui);}
body.lm .lm-wd.is-done b{background:var(--lm-wk);color:var(--lm-wk-ink);}
body.lm .lm-wd.is-today b{background:var(--bg);box-shadow:0 0 0 2px var(--lm-wk);}
body.lm .lm-wd.is-today span{color:var(--fg);}
body.lm .lm-wd.is-none b{background:none;box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm .lm-vod{display:block;padding:20px;border-radius:20px;background:var(--lm-paper);color:var(--lm-ink);text-decoration:none;}
body.lm .lm-vod-k{display:block;font:700 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-ink2);}
body.lm .lm-vod q{display:block;margin:12px 0 10px;font:400 20px/1.5 var(--lm-read);quotes:none;text-wrap:pretty;}
body.lm .lm-vod q::before,body.lm .lm-vod q::after{content:none;}
body.lm .lm-vod small{display:block;font:650 13px/1.3 var(--mb-ui);color:var(--lm-ink2);}
body.lm .lm-mcovs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
body.lm .lm-cv.lm-mcov{height:150px;border-radius:16px;text-decoration:none;}
body.lm .lm-cv.lm-mcov b{bottom:30px;left:12px;right:12px;font-style:normal;font-size:20px;line-height:1.05;-webkit-line-clamp:3;}
body.lm .lm-cv.lm-mcov small{top:auto;bottom:12px;left:12px;font:500 12px/1 var(--mb-ui);letter-spacing:0;text-transform:none;opacity:.85;}
body.lm .lm-cv.lm-mcov.has-ph::after{background:linear-gradient(180deg,rgba(0,0,0,0) 35%,rgba(0,0,0,.7));}
/* Plans: a plan running as a ring, the plans to start */
body.lm .lm-aplan{display:flex;align-items:center;gap:16px;margin-top:16px;padding:16px;border-radius:20px;box-shadow:inset 0 0 0 1px var(--lm-line);
  color:var(--fg);text-decoration:none;}
body.lm .lm-aplan+.lm-aplan{margin-top:10px;}
body.lm .lm-ringp{position:relative;width:64px;height:64px;flex:none;}
body.lm .lm-ringp svg{display:block;width:64px;height:64px;transform:rotate(-90deg);}
body.lm .lm-ringp b{position:absolute;inset:0;display:grid;place-items:center;font:500 22px/1 var(--mb-serif);color:var(--fg);}
body.lm .lm-aplan-t{flex:1;min-width:0;color:var(--fg);text-decoration:none;}
body.lm .lm-aplan-t small{display:block;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-aplan-t b{display:block;margin:2px 0;font:700 16px/1.25 var(--mb-ui);}
body.lm .lm-aplan .lm-aplan-go{flex:none;background:var(--fg);color:var(--bg);}
body.lm .lm-aplan .lm-chev{color:var(--fg3);}
body.lm .lm-pstarts{border-radius:18px;box-shadow:inset 0 0 0 1px var(--lm-line);overflow:hidden;}
body.lm .lm-pstart+.lm-pstart{border-top:1px solid var(--lm-line);}
body.lm .lm-pstart button{display:flex;align-items:center;gap:14px;width:100%;padding:12px 16px;border:0;background:none;color:var(--fg);
  text-align:left;font:inherit;cursor:pointer;}
body.lm .lm-pc{width:48px;height:48px;flex:none;border-radius:12px;display:grid;place-items:center;background:var(--h,var(--acc-fill));
  color:var(--on-h,var(--on-acc));font:italic 500 18px/1 var(--mb-serif);}
body.lm .lm-pstart-t{flex:1;min-width:0;}
body.lm .lm-pstart-t b{display:block;font:650 15px/1.25 var(--mb-ui);}
body.lm .lm-pstart-t small{display:block;margin-top:2px;font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-pstart-go{flex:none;height:32px;padding:0 14px;border-radius:16px;background:var(--s1);display:grid;place-items:center;
  font:650 13px/1 var(--mb-ui);color:var(--fg);}
/* Saved: a colour bar, the verse, the reference and when, the note */
body.lm .lm-hls{margin:6px -20px 0;padding:0;list-style:none;}
body.lm .lm-hlr{display:flex;gap:14px;padding:14px 20px;border-bottom:1px solid var(--lm-line);color:var(--fg);text-decoration:none;}
body.lm .lm-hlr>i{width:4px;flex:none;border-radius:2px;}
body.lm .lm-hlr>i.is-plain{background:var(--s3);}
body.lm .lm-hlr-t{flex:1;min-width:0;}
body.lm .lm-hlr-v{display:block;font:400 16.5px/1.55 var(--lm-read);text-wrap:pretty;}
body.lm .lm-hlr-n{display:-webkit-box;margin-top:8px;padding:10px 12px;border-radius:12px;background:var(--s1);overflow:hidden;
  -webkit-line-clamp:3;-webkit-box-orient:vertical;font:400 14px/1.45 var(--mb-ui);color:var(--fg);}
body.lm .lm-hlr small{display:block;margin-top:6px;font:650 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
body.lm .lm-saved0{margin-top:44px;text-align:center;}
body.lm .lm-saved0-t{margin:0 0 8px;font:400 26px/1.15 var(--mb-serif);color:var(--fg);}
body.lm .lm-saved0 .lm-btn{margin-top:18px;}
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
  body.lm .lm-book,body.lm .lm-dfeat,body.lm .lm-drow,body.lm .lm-rstep,body.lm .lm-vod,body.lm .lm-mcov,body.lm .lm-aplan-t,
  body.lm .lm-pstart button,body.lm .lm-hlr,body.lm .lm-wd>a{transition:transform .15s ease;}
  body.lm .lm-book:active,body.lm .lm-dfeat:active,body.lm .lm-drow:active,body.lm .lm-rstep:active,body.lm .lm-vod:active,body.lm .lm-mcov:active,
  body.lm .lm-aplan-t:active,body.lm .lm-pstart button:active,body.lm .lm-hlr:active,body.lm .lm-wd>a:active{transform:scale(.985);}
  body.lm .lm-bsg{transition:background-color .2s ease,color .2s ease,box-shadow .2s ease;}
}
body.lm .lm-trs a:focus-visible,body.lm .lm-bsg:focus-visible,body.lm .lm-ver>summary:focus-visible,body.lm .lm-verpop a:focus-visible,
body.lm .lm-book:focus-visible,body.lm .lm-pill:focus-visible,body.lm .lm-aa:focus-visible,body.lm .lm-rstep:focus-visible,
body.lm .bb-dock-h .lm-share:focus-visible,body.lm .lm-wd>a:focus-visible,body.lm .lm-vod:focus-visible,body.lm .lm-mcov:focus-visible,
body.lm .lm-aplan-t:focus-visible,body.lm .lm-pstart button:focus-visible,body.lm .lm-hlr:focus-visible,
body.lm .lm-dfeat:focus-visible,body.lm .lm-drow:focus-visible,body.lm .lm-field-go:focus-visible,
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
body.lm.lm-dark .lm-verpop,body.lm.lm-dark .bb-dock,body.lm.lm-dark .lm-aapanel{box-shadow:0 0 0 1px var(--lm-line),0 14px 36px rgba(0,0,0,.6);}
body.lm.lm-dark .lm-rbar+.lm-aapanel{box-shadow:inset 0 0 0 1px var(--lm-line);}
body.lm.lm-dark{--lm-wk:#BDE3C2;--lm-wk-ink:#10261C;}
body.lm.lm-dark .bb-dock .bb-sw.sw-gold{background:rgba(233,182,90,.82);}
body.lm.lm-dark .bb-dock .bb-sw.sw-pink{background:rgba(246,112,150,.78);}
body.lm.lm-dark .bb-dock .bb-sw.sw-teal{background:rgba(46,196,160,.75);}
body.lm.lm-dark .bb-dock .bb-sw.sw-violet{background:rgba(150,135,255,.78);}
body.lm.lm-dark .bb-dock .bb-sw.sw-coral{background:rgba(255,140,90,.78);}
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
  body.lm .lm-rstep{transition:background-color .5s ease,color .5s ease,transform .15s ease;}
  body.lm .lm-vc:not([hidden]) .lm-vc-scrim{animation:lm-vcfade .3s both;}
  body.lm .lm-vc:not([hidden]) .lm-vc-sheet{animation:lm-vcup .55s cubic-bezier(.2,.8,.2,1) both;}
  body.lm .lm-vc-cv.is-pop{animation:lm-vcpop .6s cubic-bezier(.34,1.56,.64,1) both;}
}
@keyframes lm-vcfade{from{opacity:0}to{opacity:1}}
@keyframes lm-vcup{from{transform:translateY(100%)}to{transform:none}}
@keyframes lm-vcpop{from{transform:scale(.92);opacity:.5}to{transform:none;opacity:1}}
"""
