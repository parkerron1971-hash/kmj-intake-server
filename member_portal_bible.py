"""
member_portal_bible.py — the Bible in the member app (Kevin's list,
2026-09-30; tab placement 10-02: Home · Sermons · Bible · Groups · Live,
with Me on the profile picture).

  /my/bible                      find a passage or a word, keep reading, plans,
                                 highlights and notes, the books
  /my/bible?q=John 3:16          jump to a typed reference
  /my/bible?q=shepherd           every verse with those words
  /my/bible/books?t=ot|nt        the book picker: Old Testament first, the books
                                 in their groups, each opening to its chapters
  /my/bible/<book>               the picker, open at that book
  /my/bible/<book>/<n>?v=16-18   read a chapter, those verses marked; tap a verse
                                 to highlight it, add a note, copy, share, bookmark
  /my/bible/notes                the member's highlights, notes and bookmarks
  /my/bible/plans*               plans & devotionals (member_portal_devotionals.py)

Round three (Kevin approved "Member App, Round Three", 2026-10-19): "the
bible section needs major upgrade ... the choice of what book of bible
needs a better flow a mixed of how the bible app looks when selecting book
of the bible . also old testament comes before new testment. and the
ability to highlight and take notes."

Public-domain KJV and WEB (bible_text.py). The reader's translation and
the last chapters they read live in a cookie on their phone (`sol_bible`,
path /my). Highlights, notes and bookmarks are the member's own, kept on
the server so they follow them (member_bible_marks.py), and never shown in
the owner's preview. Sermon scriptures link here (member_portal_sermons.py).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import bible_text as bt

COOKIE = "sol_bible"
COOKIE_AGE = 365 * 86400
PASSAGE_MAX = 40          # verses shown inline on a sermon page


RECENT_MAX = 5


def recents(request: Request) -> List[Tuple[str, int]]:
    """The last chapters read, newest first, from the cookie:
    'kjv|john/3~proverbs/4' (an older cookie holds just one)."""
    raw = str(request.cookies.get(COOKIE) or "")
    out: List[Tuple[str, int]] = []
    for part in re.split(r"[~,]", raw.partition("|")[2])[:RECENT_MAX]:
        m = re.fullmatch(r"([a-z0-9-]{2,24})/(\d{1,3})", part)
        if m and m.group(1) in bt.SLUGS and (bt.SLUGS[m.group(1)], int(m.group(2))) not in out:
            out.append((bt.SLUGS[m.group(1)], int(m.group(2))))
    return out


def prefs(request: Request) -> Tuple[str, Optional[Tuple[str, int]]]:
    """(translation, last chapter read) from the cookie."""
    raw = str(request.cookies.get(COOKIE) or "")
    seen = recents(request)
    return bt.translation(raw.partition("|")[0]), (seen[0] if seen else None)


def _remember(resp, tr: str, where: Optional[Tuple[str, int]], history: List[Tuple[str, int]] = ()) -> None:
    places = ([where] if where else []) + [p for p in history if p != where]
    last = "~".join(f"{bt.slug(c)}/{n}" for c, n in places[:RECENT_MAX])
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
                 only: Optional[Tuple[int, int]] = None, marks: Optional[Dict[int, Dict[str, Any]]] = None) -> str:
    """A chapter as text. KJV keeps its ¶ paragraphs; WEB, which carries
    none, sets a verse to a line. `rng` marks verses; `only` limits to them.
    `marks` (the reader): each verse is something to tap, in its highlight
    colour, with a mark where it has a note."""
    verses = bt.chapter(code, ch, tr) or []
    paras: List[List[str]] = [[]]
    for v, text in verses:
        if only and not only[0] <= v <= only[1]:
            continue
        if paras[-1] and (tr != "kjv" or text.lstrip().startswith("¶")):
            paras.append([])
        num = f'<sup class="bb-n" id="v{v}">{v}</sup>'
        body = _verse_html(text, tr)
        if marks is not None:
            m = marks.get(v) or {}
            hl = f" hl-{m['colour']}" if m.get("colour") else ""
            note = ('<span class="bb-nm" aria-label="Has a note"></span>' if (m.get("note") or "").strip() else "")
            mark = '<span class="bb-bm" aria-label="Bookmarked"></span>' if m.get("bookmarked") else ""
            body = f'<span class="bb-v{hl}" data-v="{v}">{num}{body}{note}{mark}</span>'
            paras[-1].append(f'<mark class="bb-hl">{body}</mark>' if _marked(v, rng) else body)
            continue
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


def _chips(places: List[Tuple[str, int]]) -> str:
    """The last chapters read, as chips."""
    from member_portal import _e
    if not places:
        return ""
    return ('<nav class="bb-recent" aria-label="Recently read">' + "".join(
        f'<a href="/my/bible/{bt.slug(c)}/{n}">{_e(where_label(c, n))}</a>' for c, n in places) + "</nav>")


def render_home(biz, site, me, tr: str, where, *, query: str = "", missed: bool = False, slow: bool = False,
                places: Optional[List[Tuple[str, int]]] = None, reading: str = "", plans: str = "",
                marks: Optional[Sequence[Dict[str, Any]]] = (), preview: bool = False) -> str:
    """The Bible tab (approved board 6): find a passage or a word, the last
    chapters read, keep reading, the church's devotionals and reading plans
    (`plans`, member_portal_devotionals.bible_sections; else the church's
    reading plan alone, `reading`), the member's highlights and notes, and
    the books, Old Testament first. `marks` None = they couldn't load (said
    so, never shown as none at all)."""
    import member_app_ui as ui
    import member_bible_marks as mbm
    from member_portal import _e, _shell
    err = ('<p class="mp-err" role="alert">We couldn\'t find that passage or word. Try something like John 3:16, '
           'Psalm 23 or shepherd.</p>' if missed else
           '<p class="mp-err" role="alert">That\'s a lot of searching at once. Wait a minute, then try again.</p>'
           if slow else "")
    plan = plans
    if reading and not plans:
        plan = (f'{ui.section("Reading plan", "/my/reading", "See the plan")}'
                f'<div class="mb-today">{reading}</div>')
    notes = ""
    if preview:
        pass
    elif marks is None:
        notes = (f'{ui.section("Highlights & notes", "/my/bible/notes", "See all")}<p class="mp-err" role="alert">'
                 f'Your highlights and notes couldn\'t load just now. They\'re still saved.</p>')
    elif marks:
        n = mbm.counts(marks)
        last = next((m for m in marks if m.get("colour") or (m.get("note") or "").strip()), None)
        quote_html = ""
        if last:
            text = dict(bt.chapter(last["book"], int(last["chapter"]), tr) or []).get(int(last["verse"]), "")
            quote_html = (f'<p class="bb-hn-v"><span class="bb-mark hl-{_e(last.get("colour") or "gold")}">'
                          f'{_verse_html(text, tr)}</span></p><p class="bb-hn-ref">{_e(where_label(last["book"], int(last["chapter"])))}'
                          f':{int(last["verse"])}{" · with your note" if (last.get("note") or "").strip() else ""}</p>')
        notes = (f'{ui.section("Highlights & notes", "/my/bible/notes", "See all")}'
                 f'<a class="bb-hn" href="/my/bible/notes"><span class="bb-hn-top"><span><b>{n["highlights"]}</b> '
                 f'highlight{"" if n["highlights"] == 1 else "s"}</span><span><b>{n["notes"]}</b> note{"" if n["notes"] == 1 else "s"}</span>'
                 f'<span><b>{n["bookmarks"]}</b> saved</span></span>{quote_html}</a>')
    else:
        notes = (f'{ui.section("Highlights & notes")}<p class="mp-muted bb-hn-empty">Tap any verse while you read to '
                 f'highlight it, add a private note, or save it. They show up here.</p>')
    books = ('<div class="bb-tst">'
             '<a href="/my/bible/books?t=ot"><span class="bb-tst-ab">Genesis</span><span><b>Old Testament</b>'
             '<span>39 books · Genesis to Malachi</span></span></a>'
             '<a href="/my/bible/books?t=nt"><span class="bb-tst-ab">Matthew</span><span><b>New Testament</b>'
             '<span>27 books · Matthew to Revelation</span></span></a></div>')
    return _shell(biz, site, "Bible", f"""<div class="mb-lt"><h1>Bible</h1>{_switch(tr, "/my/bible")}</div>
<form class="bb-go" method="get" action="/my/bible" role="search">
  <label class="mp-sr" for="bb-q">Find a passage or a word</label>
  <input class="mp-input" id="bb-q" name="q" value="{_e(query)}" maxlength="60" placeholder="Find a passage or a word" autocomplete="off" enterkeyhint="search">
  <button class="mp-go" type="submit" aria-label="Find">{ui.icon("search", 18)}</button>
</form>{err}
{_chips(places or [])}
<h2 class="mp-sect">{'Keep reading' if where else 'Start here'}</h2>
{continue_card(where, tr)}
{plan}
{notes}
{ui.section("Books")}
{books}
<p class="mp-muted bb-src">{_e(bt.TRANSLATIONS[tr]["name"])} · public domain</p>""", tab="bible", who=me)


def render_books(biz, site, me, tr: str, testament: str, *, open_code: str = "",
                 where: Optional[Tuple[str, int]] = None, places: Optional[List[Tuple[str, int]]] = None) -> str:
    """The book picker (approved board 7, "a mix of how the Bible app looks"):
    Old Testament | New Testament, Old first; a filter; the books in their
    groups, each opening to its chapters right there; the one being read
    open, its chapter marked."""
    import member_app_ui as ui
    from member_portal import _e, _shell
    testament = "nt" if testament == "nt" else "ot"
    out = []
    for _key, name, colour, codes in bt.groups(testament):
        rows = []
        for code in codes:
            n = bt.chapter_count(code, tr)
            here = where[1] if where and where[0] == code else 0
            cells = "".join(
                f'<a href="/my/bible/{bt.slug(code)}/{i}"{" class=is-now aria-current=page" if i == here else ""}>{i}</a>'
                for i in range(1, n + 1))
            rows.append(f'<details class="bk" id="bk-{bt.slug(code)}" data-name="{_e(bt.NAME[code].lower())}"'
                        f'{" open" if code == open_code else ""}><summary><span class="bk-n">{_e(bt.NAME[code])}</span>'
                        f'<span class="bk-c">{n} chapter{"" if n == 1 else "s"}</span>{ui.icon("down", 18)}</summary>'
                        f'<div class="bk-grid" aria-label="{_e(bt.NAME[code])} chapters">{cells}</div></details>')
        out.append(f'<section class="bk-group h-{colour}" aria-label="{_e(name)}"><h2 class="bk-gh"><span class="bk-dot"></span>'
                   f'{_e(name)}<span class="bk-gc">{len(codes)} book{"" if len(codes) == 1 else "s"}</span></h2>{"".join(rows)}</section>')
    seg = ('<nav class="mb-seg" aria-label="Testament">'
           f'<a href="/my/bible/books?t=ot"{" aria-current=page" if testament == "ot" else ""}>Old Testament</a>'
           f'<a href="/my/bible/books?t=nt"{" aria-current=page" if testament == "nt" else ""}>New Testament</a></nav>')
    script = """<script>(function(){var q=document.getElementById('bk-q');var o=document.querySelector('details.bk[open]');
if(o){o.scrollIntoView({block:'center'});}
if(!q)return;q.addEventListener('input',function(){var t=q.value.trim().toLowerCase();
document.querySelectorAll('details.bk').forEach(function(d){d.hidden=!!t&&d.getAttribute('data-name').indexOf(t)<0;});
document.querySelectorAll('.bk-group').forEach(function(g){g.hidden=!g.querySelector('details.bk:not([hidden])');});});})();</script>"""
    return _shell(biz, site, "Choose a book", f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
<div class="mb-lt"><h1>Choose a book</h1></div>
{seg}
<label class="mp-sr" for="bk-q">Find a book</label>
<input class="mp-input bk-find" id="bk-q" type="search" placeholder="Find a book" autocomplete="off">
{_chips(places or [])}
{"".join(out)}""", tab="bible", who=me, script=script)


def render_book(biz, site, me, code: str, tr: str, where=None, places=None) -> str:
    """/my/bible/<book>: the picker, open at that book."""
    return render_books(biz, site, me, tr, "ot" if code in bt.OLD_TESTAMENT else "nt", open_code=code,
                        where=where, places=places)


READER_JS = """<script>(function(){
var read=document.querySelector('.bb-read');if(!read)return;
var dock=document.getElementById('bb-dock'),noteBox=document.getElementById('bb-note'),toast=document.getElementById('bb-toast');
var book=read.getAttribute('data-book'),ch=+read.getAttribute('data-ch'),tr=read.getAttribute('data-tr'),label=read.getAttribute('data-label');
var marks={};try{marks=JSON.parse(document.getElementById('bb-marks').textContent)||{};}catch(e){}
var sel=null,timer=null;
function say(t){if(!toast)return;toast.textContent=t;toast.hidden=false;clearTimeout(timer);timer=setTimeout(function(){toast.hidden=true;},1800);}
function span(v){return read.querySelector('.bb-v[data-v="'+v+'"]');}
function textOf(v){var s=span(v);if(!s)return'';var c=s.cloneNode(true);c.querySelectorAll('sup,.bb-nm,.bb-bm').forEach(function(x){x.remove();});return c.textContent.trim();}
function paint(v){var s=span(v),m=marks[v]||{};if(!s)return;
 s.className='bb-v'+(m.colour?' hl-'+m.colour:'')+(sel===v?' is-sel':'');
 var nm=s.querySelector('.bb-nm');if(m.note&&!nm){nm=document.createElement('span');nm.className='bb-nm';nm.setAttribute('aria-label','Has a note');s.appendChild(nm);}if(!m.note&&nm)nm.remove();
 var bm=s.querySelector('.bb-bm');if(m.bookmarked&&!bm){bm=document.createElement('span');bm.className='bb-bm';bm.setAttribute('aria-label','Bookmarked');s.appendChild(bm);}if(!m.bookmarked&&bm)bm.remove();}
function show(){if(!dock)return;var m=marks[sel]||{};dock.hidden=sel===null;document.body.classList.toggle('bb-docked',sel!==null);if(sel===null)return;
 dock.querySelector('.bb-dock-ref').textContent=label+':'+sel;
 dock.querySelectorAll('[data-colour]').forEach(function(b){var on=m.colour===b.getAttribute('data-colour');b.setAttribute('aria-pressed',on?'true':'false');});
 dock.querySelector('[data-act=clear]').hidden=!m.colour;
 dock.querySelector('[data-act=note] span').textContent=m.note?'Edit note':'Note';
 var bk=dock.querySelector('[data-act=bookmark]');bk.setAttribute('aria-pressed',m.bookmarked?'true':'false');bk.querySelector('span').textContent=m.bookmarked?'Saved':'Save';
 noteBox.hidden=true;dock.querySelector('.bb-dock-acts').hidden=false;
 // a verse low on the screen would sit under the dock: bring it up
 var r=span(sel).getBoundingClientRect(),top=dock.getBoundingClientRect().top;
 if(r.bottom>top-16)window.scrollBy({top:r.bottom-top+48,behavior:'smooth'});}
function pick(v){var was=sel;sel=(sel===v)?null:v;if(was!==null)paint(was);if(sel!==null)paint(sel);show();}
read.addEventListener('click',function(e){var s=e.target.closest('.bb-v');if(!s)return;pick(+s.getAttribute('data-v'));});
read.addEventListener('keydown',function(e){if((e.key==='Enter'||e.key===' ')&&e.target.classList.contains('bb-v')){e.preventDefault();pick(+e.target.getAttribute('data-v'));}});
read.querySelectorAll('.bb-v').forEach(function(s){s.tabIndex=0;s.setAttribute('role','button');});
function send(change){var v=sel;var body=Object.assign({book:book,chapter:ch,verse:v,t:tr},change);
 return fetch('/my/bible/mark',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(body)})
 .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw d;return d;});})
 .then(function(d){if(d.mark){marks[v]={colour:d.mark.colour,note:d.mark.note,bookmarked:d.mark.bookmarked};}else{delete marks[v];}paint(v);if(sel===v)show();return d;})
 .catch(function(d){say(d&&d.error==='slow'?'That\\'s a lot at once. Wait a minute.':'That didn\\'t save. Try again.');return null;});}
if(!dock)return;
// out of the page's layer, or the tab bar sits over the dock's buttons
document.body.appendChild(dock);if(toast)document.body.appendChild(toast);
dock.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||sel===null)return;var m=marks[sel]||{};
 var c=b.getAttribute('data-colour');if(c){send({colour:m.colour===c?'':c});return;}
 var act=b.getAttribute('data-act');
 if(act==='clear'){send({colour:''});}
 else if(act==='close'){pick(sel);}
 else if(act==='note'){noteBox.hidden=false;dock.querySelector('.bb-dock-acts').hidden=true;noteBox.querySelector('.bb-note-v').textContent='“'+textOf(sel)+'”';
  var ta=noteBox.querySelector('textarea');ta.value=m.note||'';ta.focus();}
 else if(act==='save-note'){send({note:noteBox.querySelector('textarea').value}).then(function(d){if(d)say('Note saved');});}
 else if(act==='copy'){var t='“'+textOf(sel)+'” '+label+':'+sel+' '+tr.toUpperCase();
  (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){say('Copied '+label+':'+sel);},function(){say('Copying was blocked');});}
 else if(act==='share'){var s='“'+textOf(sel)+'” '+label+':'+sel;
  if(navigator.share){navigator.share({text:s}).catch(function(){});}else if(navigator.clipboard){navigator.clipboard.writeText(s).then(function(){say('Copied to share');});}}
 else if(act==='bookmark'){send({bookmark:!m.bookmarked}).then(function(d){if(d)say(marks[sel]&&marks[sel].bookmarked?'Saved':'Taken off your saved verses');});}});
var aa=document.getElementById('bb-aa'),panel=document.getElementById('bb-aa-panel'),text=read.querySelector('.bb-text');
function setLook(size,font){if(!text)return;text.classList.remove('sz-s','sz-l','f-sans');if(size&&size!=='m')text.classList.add('sz-'+size);if(font==='sans')text.classList.add('f-sans');
 try{localStorage.setItem('bb-look',size+'|'+font);}catch(e){}}
var look='m|serif';try{look=localStorage.getItem('bb-look')||look;}catch(e){}
var parts=look.split('|');setLook(parts[0],parts[1]);
if(aa&&panel){aa.addEventListener('click',function(){panel.hidden=!panel.hidden;aa.setAttribute('aria-expanded',panel.hidden?'false':'true');});
 panel.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var p=look.split('|');
  if(b.getAttribute('data-size')){var order=['s','m','l'],i=order.indexOf(p[0]);i=Math.max(0,Math.min(2,i+(b.getAttribute('data-size')==='up'?1:-1)));p[0]=order[i];}
  if(b.getAttribute('data-font')){p[1]=b.getAttribute('data-font');}
  look=p.join('|');setLook(p[0],p[1]);});}
var hash=location.hash.match(/^#v(\\d+)$/);if(hash){var s=span(+hash[1]);if(s)s.scrollIntoView({block:'center'});}
})();</script>"""


def render_chapter(biz, site, me, code: str, ch: int, tr: str, rng=None,
                   marks: Optional[Dict[int, Dict[str, Any]]] = None, preview: bool = False) -> str:
    """Reading a chapter (approved board 8): the chapter's name opens the
    book picker; tap a verse to highlight it in one of five colours, add a
    private note, copy, share or save it; Aa sets the text size and font.
    `marks` None = they couldn't load (or a preview): the text, no editing."""
    import json
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
    editable = marks is not None and not preview
    found = {str(v): {"colour": m.get("colour"), "note": m.get("note"), "bookmarked": bool(m.get("bookmarked"))}
             for v, m in (marks or {}).items()}
    swatches = "".join(f'<button type="button" class="bb-sw sw-{c}" data-colour="{c}" aria-pressed="false" '
                       f'aria-label="Highlight {c}"></button>' for c in ("gold", "pink", "teal", "violet", "coral"))
    dock = "" if not editable else f"""<div class="bb-dock" id="bb-dock" role="group" aria-label="This verse" hidden>
  <div class="bb-dock-h"><strong class="bb-dock-ref"></strong><button type="button" class="bb-x" data-act="close" aria-label="Close">{ui.icon('plus', 18)}</button></div>
  <div class="bb-dock-acts">
    <div class="bb-sws">{swatches}<button type="button" class="mp-link bb-clear" data-act="clear" hidden>Remove</button></div>
    <div class="bb-acts">
      <button type="button" data-act="note">{ui.icon('doc', 20)}<span>Note</span></button>
      <button type="button" data-act="copy">{ui.icon('share', 20)}<span>Copy</span></button>
      <button type="button" data-act="share">{ui.icon('out', 20)}<span>Share</span></button>
      <button type="button" data-act="bookmark" aria-pressed="false">{ui.icon('star', 20)}<span>Save</span></button>
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
    note = ('<p class="mp-muted bb-pv">Highlights and notes are private, so a preview doesn\'t show them.</p>'
            if preview else ('<p class="mp-err" role="alert">Your highlights couldn\'t load just now. Reading still works.</p>'
                             if marks is None else ""))
    data = json.dumps(found).replace("</", "<\\/")
    aa = ("" if not editable else
          f'<button type="button" class="bb-aa" id="bb-aa" aria-expanded="false" aria-controls="bb-aa-panel">Aa</button>')
    panel = ("" if not editable else
             '<div class="bb-aa-panel" id="bb-aa-panel" hidden><div class="bb-aa-row"><span>Text size</span>'
             '<span class="bb-aa-btns"><button type="button" data-size="down" aria-label="Smaller text">A−</button>'
             '<button type="button" data-size="up" aria-label="Larger text">A+</button></span></div>'
             '<div class="bb-aa-row"><span>Font</span><span class="bb-aa-btns"><button type="button" data-font="serif">Book</button>'
             '<button type="button" data-font="sans">Clean</button></span></div></div>')
    return _shell(biz, site, f"{name} {ch}", f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
<div class="bb-head"><a class="bb-where" href="/my/bible/{bt.slug(code)}">{_e(name)} {ch}{ui.icon('down', 16)}</a>
{_switch(tr, here)}{aa}</div>
{panel}
<h1 class="bb-title">{_e(name)} <em>{ch}</em></h1>
{note}
<div class="bb-read" data-book="{code}" data-ch="{ch}" data-tr="{tr}" data-label="{_e(name)} {ch}">
{chapter_html(code, ch, tr, rng, marks=marks if editable else None)}
</div>
<nav class="bb-steps" aria-label="Chapters">{step(prev, "Previous", "bb-prev")}{step(nxt, "Next", "bb-next")}</nav>
<p class="mp-muted bb-src">{_e(bt.TRANSLATIONS[tr]["name"])} · public domain</p>
{dock}
<script type="application/json" id="bb-marks">{data}</script>""", tab="bible", who=me,
                  script=READER_JS if editable else "")


def render_search(biz, site, me, tr: str, query: str, hits, total: int) -> str:
    """Every verse with the words (the first 50, in the Bible's order)."""
    import member_app_ui as ui
    from member_portal import _e, _shell
    words = [w for w in re.findall(r"[a-z0-9']+", query.lower()) if len(w) >= 2]

    def lit(text: str) -> str:
        out = _verse_html(text, tr)
        for w in words:
            out = re.sub(r"(?i)\b(" + re.escape(w) + r")\b(?![^<]*>)", r'<b class="bb-q">\1</b>', out)
        return out
    rows = "".join(
        f'<li><a href="/my/bible/{bt.slug(c)}/{ch}?v={v}#v{v}"><strong>{_e(where_label(c, ch))}:{v}</strong>'
        f'<span>{lit(text)}</span></a></li>' for c, ch, v, text in hits)
    more = (f'<p class="mp-muted">Showing the first {len(hits)} of {total}. Add a word to narrow it down.</p>'
            if total > len(hits) else "")
    return _shell(biz, site, "Search", f"""<a class="mb-back" href="/my/bible">{ui.icon('back', 16)}Bible</a>
<form class="bb-go" method="get" action="/my/bible" role="search">
  <label class="mp-sr" for="bb-q">Find a passage or a word</label>
  <input class="mp-input" id="bb-q" name="q" value="{_e(query)}" maxlength="60" autocomplete="off" enterkeyhint="search">
  <button class="mp-go" type="submit" aria-label="Find">{ui.icon("search", 18)}</button>
</form>
<p class="mb-sub">{total} verse{'' if total == 1 else 's'} with “{_e(query)}” · {_e(bt.TRANSLATIONS[tr]["short"])}</p>
<ul class="bb-hits">{rows}</ul>
{more}""", tab="bible", who=me)


NOTE_FILTERS = (("all", "All"), ("highlights", "Highlights"), ("notes", "Notes"), ("saved", "Saved"))


def render_notes(biz, site, me, tr: str, rows: Optional[List[Dict[str, Any]]], *, show: str = "all",
                 colour: str = "", preview: bool = False, today: Optional[date] = None) -> str:
    """The member's highlights, notes and saved verses (approved board 9),
    newest first, in Today / This week / Earlier."""
    import member_app_ui as ui
    import member_bible_marks as mbm
    from member_portal import _e, _shell
    today = today or date.today()
    head = f'<a class="mb-back" href="/my/bible">{ui.icon("back", 16)}Bible</a><div class="mb-lt"><h1>Highlights <em>&amp; notes</em></h1></div>'
    if preview:
        return _shell(biz, site, "Highlights & notes", head + '<p class="mp-muted">These are private to each member, '
                      'so a preview doesn\'t show them.</p>', tab="bible", who=me)
    if rows is None:
        return _shell(biz, site, "Highlights & notes", head + '<p class="mp-err" role="alert">Your highlights couldn\'t '
                      'load just now. Please try again in a moment.</p>', tab="bible", who=me)
    show = show if show in dict(NOTE_FILTERS) else "all"
    colour = colour if colour in mbm.COLOURS else ""
    n = mbm.counts(rows)
    total = {"all": len(rows), "highlights": n["highlights"], "notes": n["notes"], "saved": n["bookmarks"]}

    def keep(r):
        if show == "highlights" and not r.get("colour"):
            return False
        if show == "notes" and not (r.get("note") or "").strip():
            return False
        if show == "saved" and not r.get("bookmarked"):
            return False
        return not colour or r.get("colour") == colour
    chips = "".join(f'<a href="/my/bible/notes?show={k}"{" aria-current=page" if show == k and not colour else ""}>'
                    f'{label} <span>{total[k]}</span></a>' for k, label in NOTE_FILTERS)
    dots = "".join(f'<a class="bb-cdot sw-{c}" href="/my/bible/notes?show={show}&amp;colour={c}" aria-label="{c.title()} highlights"'
                   f'{" aria-current=page" if colour == c else ""}></a>' for c in mbm.COLOURS)
    buckets: Dict[str, List[str]] = {}
    for r in rows:
        if not keep(r):
            continue
        try:
            when = datetime.fromisoformat(str(r.get("updated_at")).replace("Z", "+00:00")).date()
        except ValueError:
            when = today
        group = "Today" if when == today else ("This week" if (today - when).days < 7 else "Earlier")
        text = dict(bt.chapter(r["book"], int(r["chapter"]), tr) or []).get(int(r["verse"]), "")
        ref = f'{where_label(r["book"], int(r["chapter"]))}:{int(r["verse"])}'
        hl = f'hl-{_e(r["colour"])}' if r.get("colour") else ""
        note = (f'<div class="bb-it-note">{ui.icon("doc", 16)}<span>{_e(r["note"])}</span></div>'
                if (r.get("note") or "").strip() else "")
        saved = '<span class="mb-chip">Saved</span>' if r.get("bookmarked") else ""
        buckets.setdefault(group, []).append(
            f'<article class="bb-it"><div class="bb-it-h"><strong>{_e(ref)}</strong>'
            f'<span>{_e(bt.TRANSLATIONS[tr]["short"])}</span></div>'
            f'<p class="bb-it-v"><span class="bb-mark {hl}">{_verse_html(text, tr)}</span></p>{note}'
            f'<div class="bb-it-f"><a href="/my/bible/{bt.slug(r["book"])}/{int(r["chapter"])}#v{int(r["verse"])}">'
            f'Open in {_e(where_label(r["book"], int(r["chapter"])))}{ui.icon("chevron", 14)}</a>{saved}</div></article>')
    body = "".join(f'<h2 class="bb-day">{g}</h2>{"".join(items)}' for g, items in buckets.items()) or (
        '<p class="mp-muted" style="margin-top:20px">Nothing here yet. While you read, tap a verse to highlight it, '
        'add a note or save it.</p>')
    return _shell(biz, site, "Highlights & notes", f"""{head}
<nav class="bb-filters" aria-label="Show">{chips}</nav>
<div class="bb-colours"><span>Colour</span>{dots}</div>
{body}
<p class="bb-priv bb-priv-foot">{ui.icon('lock', 14)}Only you can see these. They follow you to any phone you sign in on,
and the church's staff can't read them.</p>""", tab="bible", who=me)


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


async def serve(request: Request, biz, site, me, sub: str, *, preview: bool = False):
    """GET /my/bible* → a response (sets the reading cookie). `preview`:
    the owner's Preview as a member, which never shows the member's own
    highlights and notes."""
    import asyncio
    import member_bible_marks as mbm
    from member_portal import _SECURE_HEADERS
    tr, where = prefs(request)
    places = recents(request)
    asked = request.query_params.get("t")
    if asked in bt.TRANSLATIONS:
        tr = asked
    rest = sub[len("/my/bible"):].strip("/")
    parts = rest.split("/") if rest else []

    def page(html, status=200, *, at=where):
        resp = HTMLResponse(html, status_code=status, headers=_SECURE_HEADERS)
        _remember(resp, tr, at, places)
        return resp
    if not parts:
        q = str(request.query_params.get("q") or "").strip()[:60]
        if q:
            found = await asyncio.to_thread(bt.find_refs, q, tr)
            if found:
                ref = found[0][2]
                to = ref.href() + (f"#v{ref.start}" if ref.start else "")
                resp = RedirectResponse(to, status_code=303, headers=_SECURE_HEADERS)
                _remember(resp, tr, where, places)
                return resp
            import rate_limit
            if not rate_limit.allow("bible_search", f"{biz['id']}|{me['id']}"):
                return page(render_home(biz, site, me, tr, where, query=q, places=places, slow=True,
                                        marks=() if preview else await asyncio.to_thread(mbm.all_marks, biz["id"], str(me["id"])),
                                        preview=preview))
            hits, total = await asyncio.to_thread(bt.search, q, tr)
            if hits:
                return page(render_search(biz, site, me, tr, q, hits, total))
        import member_portal_devotionals as mpd
        plans, marks = await asyncio.gather(
            mpd.bible_home(biz, site, me, preview=preview),
            asyncio.to_thread(lambda: None if preview else mbm.all_marks(biz["id"], str(me["id"]))))
        reading = ""
        if not plans:
            import reading_plans as rp
            import member_portal_reading as mpr
            plan = rp.current(biz)
            done = await asyncio.to_thread(rp.read_days, biz["id"], me["id"], plan) if plan and not preview else set()
            reading = mpr.today_row(rp.today_for(biz), done) if plan else ""
        return page(render_home(biz, site, me, tr, where, query=q, missed=bool(q), places=places,
                                reading=reading, plans=plans, marks=marks, preview=preview))
    if parts[0] == "plans":
        # Plans & devotionals (member_portal_devotionals.py).
        import member_portal_devotionals as mpd
        got = await mpd.serve(request, biz, site, me, parts[1:], tr=tr, preview=preview)
        if not isinstance(got, tuple):
            return got
        return page(got[0], got[1])
    if parts == ["books"]:
        t = str(request.query_params.get("t") or "")
        if t not in ("ot", "nt"):
            t = "nt" if where and where[0] not in bt.OLD_TESTAMENT else "ot"
        open_code = where[0] if where and (where[0] in bt.OLD_TESTAMENT) == (t == "ot") else ""
        return page(render_books(biz, site, me, tr, t, open_code=open_code, where=where, places=places))
    if parts == ["notes"]:
        rows = None if preview else await asyncio.to_thread(mbm.all_marks, biz["id"], str(me["id"]))
        return page(render_notes(biz, site, me, tr, rows, show=str(request.query_params.get("show") or "all"),
                                 colour=str(request.query_params.get("colour") or ""), preview=preview))
    code = bt.SLUGS.get(parts[0])
    if not code or len(parts) > 2:
        return RedirectResponse("/my/bible", status_code=303, headers=_SECURE_HEADERS)
    if len(parts) == 1:
        return page(await asyncio.to_thread(render_book, biz, site, me, code, tr, where, places))
    if not parts[1].isdigit():
        return RedirectResponse(f"/my/bible/{bt.slug(code)}", status_code=303, headers=_SECURE_HEADERS)
    ch = int(parts[1])
    verses = await asyncio.to_thread(bt.chapter, code, ch, tr)
    if not verses:
        return RedirectResponse(f"/my/bible/{bt.slug(code)}", status_code=303, headers=_SECURE_HEADERS)
    rng = _range(str(request.query_params.get("v") or ""), verses[-1][0])
    marks = None if preview else await asyncio.to_thread(mbm.chapter_marks, biz["id"], str(me["id"]), code, ch)
    return page(render_chapter(biz, site, me, code, ch, tr, rng, marks=marks, preview=preview), at=(code, ch))
