"""
member_portal_bible.py — the Bible in the member app (Kevin's list,
2026-09-30; tab placement 10-02: Home · Sermons · Bible · Groups · Live,
with Me on the profile picture).

  /my/bible                      go to a passage, keep reading, every book
  /my/bible?q=John 3:16          jump to a typed reference
  /my/bible/<book>               the book's chapters
  /my/bible/<book>/<n>?v=16-18   read a chapter, those verses marked

Public-domain KJV and WEB (bible_text.py). The reader's translation and
where they left off live in a cookie on their phone (`sol_bible`,
path /my) — nothing about their reading is stored on the server. Sermon
scriptures link here (member_portal_sermons.py).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import bible_text as bt

COOKIE = "sol_bible"
COOKIE_AGE = 365 * 86400
PASSAGE_MAX = 40          # verses shown inline on a sermon page


def prefs(request: Request) -> Tuple[str, Optional[Tuple[str, int]]]:
    """(translation, last chapter read) from the cookie: 'kjv|john/3'."""
    raw = str(request.cookies.get(COOKIE) or "")
    tr, _, last = raw.partition("|")
    where = None
    m = re.fullmatch(r"([a-z0-9-]{2,24})/(\d{1,3})", last)
    if m and m.group(1) in bt.SLUGS:
        where = (bt.SLUGS[m.group(1)], int(m.group(2)))
    return bt.translation(tr), where


def _remember(resp, tr: str, where: Optional[Tuple[str, int]]) -> None:
    last = f"{bt.slug(where[0])}/{where[1]}" if where else ""
    resp.set_cookie(COOKIE, f"{tr}|{last}", max_age=COOKIE_AGE, path="/my", secure=True, httponly=True, samesite="lax")


def _verse_html(text: str, tr: str) -> str:
    from member_portal import _e
    t = _e(text.replace("¶", "").strip())
    if tr == "kjv":   # the translators' supplied words, in italics
        t = re.sub(r"\[([^\[\]]+)\]", r"<i>\1</i>", t)
    return t


def where_label(code: str, ch: int) -> str:
    """'Psalm 23', 'John 3' — one chapter's name (the book is Psalms)."""
    return f"{'Psalm' if code == 'PSA' else bt.NAME[code]} {ch}"


def _marked(v: int, rng: Optional[Tuple[int, int]]) -> bool:
    return bool(rng) and rng[0] <= v <= rng[1]


def chapter_html(code: str, ch: int, tr: str, rng: Optional[Tuple[int, int]] = None,
                 only: Optional[Tuple[int, int]] = None) -> str:
    """A chapter as text. KJV keeps its ¶ paragraphs; WEB, which carries
    none, sets a verse to a line. `rng` marks verses; `only` limits to them."""
    verses = bt.chapter(code, ch, tr) or []
    paras: List[List[str]] = [[]]
    for v, text in verses:
        if only and not only[0] <= v <= only[1]:
            continue
        if paras[-1] and (tr != "kjv" or text.lstrip().startswith("¶")):
            paras.append([])
        num = f'<sup class="bb-n" id="v{v}">{v}</sup>'
        body = _verse_html(text, tr)
        paras[-1].append(f'<mark class="bb-hl">{num}{body}</mark>' if _marked(v, rng) else f"{num}{body}")
    cls = "bb-text" + (" bb-lines" if tr != "kjv" else "")
    return f'<div class="{cls}">' + "".join(f"<p>{' '.join(p)}</p>" for p in paras if p) + "</div>"


def _range(raw: str, last: int) -> Optional[Tuple[int, int]]:
    """'16' / '16-18' / '16-' (to the end) → (first, last) within the chapter."""
    m = re.fullmatch(r"(\d{1,3})(?:-(\d{0,3}))?", raw or "")
    if not m:
        return None
    a = int(m.group(1))
    b = (int(m.group(2)) if m.group(2) else last) if m.group(2) is not None else a
    if not 1 <= a <= last:
        return None
    return a, max(a, min(b, last))


# ─── the verse of the day (Home, and Sermons and Live when they're empty) ──
# One a day for every member, from a fixed list of well-loved verses, so
# Home always has something worth reading on day one. The date picks it.

VERSES = (
    "1 John 4:19", "Psalm 118:24", "Lamentations 3:22-23", "Isaiah 40:31", "Philippians 4:6-7",
    "Proverbs 3:5-6", "Romans 8:28", "Joshua 1:9", "Matthew 11:28", "John 3:16", "Psalm 23:1",
    "Jeremiah 29:11", "2 Corinthians 5:17", "Galatians 2:20", "Ephesians 2:8-9", "Hebrews 11:1",
    "Psalm 46:1", "Isaiah 41:10", "Romans 12:2", "Micah 6:8", "John 14:27", "Psalm 37:4",
    "Matthew 5:14", "1 Peter 5:7", "James 1:5", "Psalm 119:105", "Romans 15:13", "Colossians 3:23",
    "Zephaniah 3:17", "John 15:5", "Psalm 34:8", "2 Timothy 1:7", "Hebrews 13:8", "Matthew 6:33",
    "Psalm 139:14", "Romans 5:8", "Nehemiah 8:10", "Psalm 27:1", "Isaiah 26:3", "John 8:12",
    "Galatians 5:22-23", "Psalm 121:1-2", "Proverbs 16:3", "Ephesians 3:20", "John 10:10",
    "Psalm 51:10", "1 Thessalonians 5:16-18", "Psalm 91:1", "Matthew 28:20", "Isaiah 43:2",
    "Deuteronomy 31:8", "Psalm 16:11", "John 11:25", "Colossians 3:15", "Psalm 100:4",
    "2 Corinthians 12:9", "1 John 1:9", "Revelation 21:4", "Romans 8:38-39", "Psalm 145:18",
)


def verse_of_day(tr: str, today: Optional[date] = None) -> Optional[Dict[str, str]]:
    """{'html', 'label', 'href'} for today's verse in this translation, or
    None when none of the list can be read (the card is then left out)."""
    today = today or date.today()
    for i in range(len(VERSES)):
        refs = bt.find_refs(VERSES[(today.toordinal() + i) % len(VERSES)], tr)
        if not refs:
            continue
        ref = refs[0][2]
        found = bt.verses(ref, tr)
        if not found:
            continue
        return {"html": " ".join(_verse_html(t, tr) for _, _, t in found),
                "label": ref.label(), "href": f"{ref.href()}#v{ref.start or 1}"}
    return None


def verse_card(tr: str, today: Optional[date] = None) -> str:
    import member_app_ui as ui
    from member_portal import _e
    v = verse_of_day(tr, today)
    if not v:
        return ""
    return (f'<section class="mb-verse" aria-labelledby="mb-verse-h"><span class="mb-kick" id="mb-verse-h">Verse of the day</span>'
            f'<blockquote>{v["html"]}</blockquote><div class="mb-verse-foot"><span>{_e(v["label"])} · '
            f'{_e(bt.TRANSLATIONS[tr]["short"])}</span><a href="{_e(v["href"])}">Read the chapter{ui.icon("chevron", 14)}</a>'
            f'</div></section>')


def continue_card(where: Optional[Tuple[str, int]], tr: str) -> str:
    """Keep reading where they stopped, or a first chapter to start with."""
    import member_app_ui as ui
    from member_portal import _e
    code, ch = where if where else ("JOH", 1)
    title = f"Keep reading {where_label(code, ch)}" if where else "Start with John 1"
    sub = (f"Pick up where you stopped · {bt.TRANSLATIONS[tr]['short']}" if where
           else "A good first book. About five minutes a chapter.")
    return (f'<a class="mb-reading-card" href="/my/bible/{bt.slug(code)}/{ch}"><span class="mb-book" aria-hidden="true">'
            f'{_e(bt.NAME[code][:1])}</span><span class="mb-list-text"><strong>{_e(title)}</strong><span>{_e(sub)}</span></span>'
            f'{ui.icon("chevron", 18)}</a>')


def continue_row(where: Optional[Tuple[str, int]], tr: str) -> str:
    """The same, as a row in Home's Today card."""
    import member_app_ui as ui
    from member_portal import _e
    code, ch = where if where else ("JOH", 1)
    title = f"Keep reading {where_label(code, ch)}" if where else "Start with John 1"
    sub = (f"Pick up where you stopped · {bt.TRANSLATIONS[tr]['short']}" if where
           else "A good first book. About five minutes a chapter.")
    return (f'<a class="mb-trow h-gold" href="/my/bible/{bt.slug(code)}/{ch}"><span class="mb-book" aria-hidden="true">'
            f'{_e(bt.NAME[code][:1])}</span><span class="mb-trow-t"><small>{"Keep reading" if where else "Start here"}</small>'
            f'<strong>{_e(title)}</strong><span>{_e(sub)}</span></span>{ui.icon("chevron", 18)}</a>')


def _switch(tr: str, here: str) -> str:
    """KJV | WEB — a plain link per translation, back to this page."""
    from member_portal import _e
    sep = "&" if "?" in here else "?"
    return ('<nav class="bb-tr" aria-label="Translation">' + "".join(
        f'<a href="{_e(here)}{sep}t={k}"{" aria-current=\"true\"" if k == tr else ""} title="{_e(v["name"])}">{_e(v["short"])}</a>'
        for k, v in bt.TRANSLATIONS.items()) + "</nav>")


# ─── pages ───────────────────────────────────────────────────────────


def render_home(biz, site, me, tr: str, where, *, query: str = "", missed: bool = False) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    err = ('<p class="mp-err" role="alert">We couldn\'t find that passage. Try something like John 3:16 or Psalm 23.</p>'
           if missed else "")

    def books(codes):
        return "".join(f'<li><a href="/my/bible/{bt.slug(c)}">{_e(bt.NAME[c])}</a></li>' for c in codes)
    old = [c for c, _, _ in bt.BOOKS if c in bt.OLD_TESTAMENT]
    new = [c for c, _, _ in bt.BOOKS if c not in bt.OLD_TESTAMENT]
    return _shell(biz, site, "Bible", f"""<div class="mb-lt"><h1>Bible</h1>{_switch(tr, "/my/bible")}</div>
<form class="bb-go" method="get" action="/my/bible" role="search">
  <label class="mp-sr" for="bb-q">Go to a passage</label>
  <input class="mp-input" id="bb-q" name="q" value="{_e(query)}" maxlength="60" placeholder="Go to… John 3:16" autocomplete="off" enterkeyhint="go">
  <button class="mp-go" type="submit" aria-label="Go">{ui.icon("search", 18)}</button>
</form>{err}
{verse_card(tr)}
<h2 class="mp-sect">{'Keep reading' if where else 'Start here'}</h2>
{continue_card(where, tr)}
<h2 class="mp-sect">New Testament</h2><ul class="bb-books">{books(new)}</ul>
<h2 class="mp-sect">Old Testament</h2><ul class="bb-books">{books(old)}</ul>
<p class="mp-muted bb-src">{_e(bt.TRANSLATIONS[tr]["name"])} · public domain</p>""", tab="bible", who=me)


def render_book(biz, site, me, code: str, tr: str) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    n = bt.chapter_count(code, tr)
    cells = "".join(f'<li><a href="/my/bible/{bt.slug(code)}/{i}">{i}</a></li>' for i in range(1, n + 1))
    return _shell(biz, site, bt.NAME[code], f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
<h1>{_e(bt.NAME[code])}</h1>
<p class="mp-muted">{n} chapter{'' if n == 1 else 's'}</p>
<ul class="bb-chapters" aria-label="Chapters">{cells}</ul>""", tab="bible", who=me)


def render_chapter(biz, site, me, code: str, ch: int, tr: str, rng=None) -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    prev, nxt = bt.neighbours(code, ch, tr)
    name = "Psalm" if code == "PSA" else bt.NAME[code]

    def step(to, label, cls):
        if not to:
            return '<span></span>'
        c, n = to
        return (f'<a class="bb-step {cls}" href="/my/bible/{bt.slug(c)}/{n}">'
                f'{ui.icon("back", 16) if cls == "bb-prev" else ""}<span>{_e(label)}<strong>{_e(where_label(c, n))}</strong></span>'
                f'{ui.icon("chevron", 16) if cls == "bb-next" else ""}</a>')
    here = f"/my/bible/{bt.slug(code)}/{ch}"
    return _shell(biz, site, f"{name} {ch}", f"""<a class="mb-back" href="/my/bible/{bt.slug(code)}">{ui.icon('back', 16)}{_e(bt.NAME[code])}</a>
<div class="bb-head"><h1>{_e(name)} {ch}</h1>{_switch(tr, here)}</div>
{chapter_html(code, ch, tr, rng)}
<nav class="bb-steps" aria-label="Chapters">{step(prev, "Previous", "bb-prev")}{step(nxt, "Next", "bb-next")}</nav>
<p class="mp-muted bb-src">{_e(bt.TRANSLATIONS[tr]["name"])} · public domain</p>""", tab="bible", who=me)


def scripture_links(text: str) -> str:
    """A sermon's scripture line with every reference a link into the
    Bible; anything else stays plain (escaped)."""
    from member_portal import _e
    out, pos = [], 0
    for a, b, ref in bt.find_refs(text or ""):
        out.append(_e(text[pos:a]))
        out.append(f'<a class="bb-ref" href="{_e(ref.href())}#v{ref.start or 1}">{_e(text[a:b])}</a>')
        pos = b
    out.append(_e((text or "")[pos:]))
    return "".join(out)


def passage_card(text: str, tr: str) -> str:
    """The sermon's passages, to read right on the sermon page."""
    from member_portal import _e
    refs = [r for _, _, r in bt.find_refs(text or "")]
    if not refs:
        return ""
    parts, shown = [], 0
    for ref in refs:
        if shown >= PASSAGE_MAX:
            break
        if ref.start is None or ref.end_chapter:
            parts.append(f'<p class="bb-pass-ref"><a class="bb-ref" href="{_e(ref.href())}">{_e(ref.label())}</a></p>')
            continue
        last = ref.end or ref.start
        last = min(last, ref.start + PASSAGE_MAX - shown - 1)
        shown += last - ref.start + 1
        parts.append(f'<p class="bb-pass-ref"><a class="bb-ref" href="{_e(ref.href())}#v{ref.start}">{_e(ref.label())}</a></p>'
                     + chapter_html(ref.book, ref.chapter, tr, only=(ref.start, last)))
    return (f'<section class="mp-card bb-pass" aria-label="Scripture"><h2 class="mp-sect" style="margin-top:0">Scripture</h2>'
            f'{"".join(parts)}<p class="mp-muted bb-src">{_e(bt.TRANSLATIONS[tr]["short"])}</p></section>')


async def serve(request: Request, biz, site, me, sub: str):
    """GET /my/bible* → a response (sets the reading cookie)."""
    import asyncio
    from member_portal import _SECURE_HEADERS
    tr, where = prefs(request)
    asked = request.query_params.get("t")
    if asked in bt.TRANSLATIONS:
        tr = asked
    rest = sub[len("/my/bible"):].strip("/")
    parts = rest.split("/") if rest else []

    def page(html, status=200, *, at=where):
        resp = HTMLResponse(html, status_code=status, headers=_SECURE_HEADERS)
        _remember(resp, tr, at)
        return resp
    if not parts:
        q = str(request.query_params.get("q") or "").strip()[:60]
        if q:
            found = await asyncio.to_thread(bt.find_refs, q, tr)
            if found:
                ref = found[0][2]
                to = ref.href() + (f"#v{ref.start}" if ref.start else "")
                resp = RedirectResponse(to, status_code=303, headers=_SECURE_HEADERS)
                _remember(resp, tr, where)
                return resp
            return page(render_home(biz, site, me, tr, where, query=q, missed=True))
        return page(render_home(biz, site, me, tr, where))
    code = bt.SLUGS.get(parts[0])
    if not code or len(parts) > 2:
        return RedirectResponse("/my/bible", status_code=303, headers=_SECURE_HEADERS)
    if len(parts) == 1:
        return page(await asyncio.to_thread(render_book, biz, site, me, code, tr))
    if not parts[1].isdigit():
        return RedirectResponse(f"/my/bible/{bt.slug(code)}", status_code=303, headers=_SECURE_HEADERS)
    ch = int(parts[1])
    verses = await asyncio.to_thread(bt.chapter, code, ch, tr)
    if not verses:
        return RedirectResponse(f"/my/bible/{bt.slug(code)}", status_code=303, headers=_SECURE_HEADERS)
    rng = _range(str(request.query_params.get("v") or ""), verses[-1][0])
    return page(render_chapter(biz, site, me, code, ch, tr, rng), at=(code, ch))
