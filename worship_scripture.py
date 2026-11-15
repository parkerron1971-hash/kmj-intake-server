# worship_scripture.py
#
# Scripture on the spot for the Sunday presenter (ChurchSavvy). The booth
# types a passage the way people say it ("rom 8 28", "jn 3 16-17",
# "ps 23", "1 cor 13 4-7") and gets slides back, split at verse breaks so
# no verse is ever cut mid-sentence.
#
# A planned passage can split its own way (2026-10-20, the Bible passage
# editor: canvas board 32): about a slide's worth at a time, one verse a
# slide, or bigger blocks; or at the verses the booth picked by hand. It can
# carry this Sunday's own words for a verse (a "fix"); the Bible itself never
# changes. The search box also finds verses by their words ("be still").
#
# Builds on bible_text (the member app's Bible): its reference parser
# wants "Romans 8:28" and refuses a two-letter book with no verse, which is
# right for scanning sermon notes and wrong for a booth that typed it on
# purpose. normalize_query and lookup bridge the two.

from __future__ import annotations

import re
from typing import Optional

import bible_text as bt

MAX_SLIDE_CHARS = 220
BLOCK_SLIDE_CHARS = 600
SPLITS = ("fit", "verse", "block")
VERSE_KEY = re.compile(r"^\d{1,3}:\d{1,3}$")
_SPACE_VERSE = re.compile(r"(\d{1,3})\s+(\d{1,3})(?=\s*(?:[-–—]\s*\d{1,3})?\s*$)")
_BARE = re.compile(
    r"^\s*(?P<book>(?:[123]\s*)?[a-z]+)\.?\s+(?P<ch>\d{1,3})"
    r"(?::(?P<v1>\d{1,3})(?:\s*[-–—]\s*(?P<v2>\d{1,3}))?)?\s*$",
    re.I,
)


def normalize_query(query: str) -> str:
    """'rom 8 28' -> 'rom 8:28'; '1 cor 13 4-7' -> '1 cor 13:4-7'; anything else unchanged."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    if ":" in q:
        return q
    return _SPACE_VERSE.sub(r"\1:\2", q, count=1)


def lookup(query: str, tr: str = bt.DEFAULT) -> Optional[bt.Ref]:
    """The one passage a booth query names, or None."""
    tr = bt.translation(tr)
    q = normalize_query(query)
    found = bt.find_refs(q, tr)
    if found:
        return found[0][2]
    m = _BARE.match(q)
    if not m:
        return None
    code = bt.ALIASES.get(bt._key(m.group("book")))
    if not code:
        return None
    ch = int(m.group("ch"))
    if not bt.chapter(code, ch, tr):
        return None
    v1 = int(m.group("v1")) if m.group("v1") else None
    v2 = int(m.group("v2")) if m.group("v2") else None
    return bt.Ref(code, ch, v1, v2 if v2 and v1 and v2 > v1 else None)


def plain(text: str) -> str:
    """KJV and ASV mark words the translators supplied with [brackets]; slides show them
    plainly. The ASV also brackets a whole passage (John 7:53 to 8:11), opening in one
    verse and closing in another; a slide drops that lone bracket too."""
    return re.sub(r"[\[\]]", "", re.sub(r"\[([^\]]*)\]", r"\1", text or "")).strip()


def slides(ref: bt.Ref, tr: str = bt.DEFAULT, max_chars: int = MAX_SLIDE_CHARS, *, split: str = "fit",
           breaks: Optional[list[str]] = None, fixes: Optional[dict[str, str]] = None) -> list[dict]:
    """Verses grouped into slides, always breaking between verses.

    split: "fit" (about max_chars a slide), "verse" (one verse a slide) or
    "block" (up to BLOCK_SLIDE_CHARS). breaks: the verses ("chapter:verse")
    that start a slide, when the booth picked them by hand; they win over
    split. fixes: this Sunday's own words for a verse, by the same key."""
    tr = bt.translation(tr)
    limit = BLOCK_SLIDE_CHARS if split == "block" else max_chars
    starts = set(breaks) if breaks is not None else None
    out: list[dict] = []
    cur: list[dict] = []
    size = 0
    for ch, v, text in bt.verses(ref, tr):
        key = f"{ch}:{v}"
        t = (fixes or {}).get(key) or plain(text)
        new = (key in starts) if starts is not None else (split == "verse" or size + len(t) > limit)
        if cur and new:
            out.append(cur)
            cur, size = [], 0
        cur.append({"chapter": ch, "verse": v, "text": t})
        size += len(t) + 1
    if cur:
        out.append(cur)
    return labelled(ref, out)


def labelled(ref: bt.Ref, out: list[list[dict]]) -> list[dict]:
    """Groups of verses as slides, each named for the verses on it ("John 3:16-17")."""
    book = "Psalm" if ref.book == "PSA" else bt.NAME[ref.book]
    shaped = []
    for group in out:
        first, last = group[0], group[-1]
        if first["chapter"] == last["chapter"]:
            span = f"{first['verse']}" if first["verse"] == last["verse"] else f"{first['verse']}-{last['verse']}"
            label = f"{book} {first['chapter']}:{span}"
        else:
            label = f"{book} {first['chapter']}:{first['verse']}-{last['chapter']}:{last['verse']}"
        shaped.append({"label": label, "verses": group})
    return shaped


def choices(query: str, tr: str = bt.DEFAULT) -> dict:
    """What the booth's search box offers: the passage asked for, one verse more, the whole chapter."""
    tr = bt.translation(tr)
    ref = lookup(query, tr)
    if not ref:
        found = find_words(query, tr)
        return {"query": query, "translation": tr, "translation_name": bt.TRANSLATIONS[tr]["short"], "choices": [],
                "words": found["hits"], "words_total": found["total"]}

    def pack(r: bt.Ref, kind: str) -> dict:
        ss = slides(r, tr)
        return {"kind": kind, "label": r.label(), "verse_count": sum(len(s["verses"]) for s in ss),
                "slide_count": len(ss), "slides": ss}

    out = [pack(ref, "asked")]
    count = len(bt.chapter(ref.book, ref.chapter, tr) or [])
    if ref.start is not None and not ref.end_chapter:
        last = ref.end or ref.start
        if last < count:
            out.append(pack(bt.Ref(ref.book, ref.chapter, ref.start, last + 1), "one_more"))
        out.append(pack(bt.Ref(ref.book, ref.chapter), "chapter"))
    return {"query": query, "translation": tr, "translation_name": bt.TRANSLATIONS[tr]["short"], "choices": out,
            "verses": verses_of(ref, tr) if len(out) and out[0]["verse_count"] <= 200 else [], "words": [], "words_total": 0}


def verses_of(ref: bt.Ref, tr: str = bt.DEFAULT) -> list[dict]:
    """Every verse of a passage, plainly: the passage editor's word list."""
    return [{"chapter": ch, "verse": v, "text": plain(text)} for ch, v, text in bt.verses(ref, bt.translation(tr))]


def find_words(query: str, tr: str = bt.DEFAULT, limit: int = 8) -> dict:
    """Verses holding every word typed ("be still"), in the Bible's order."""
    tr = bt.translation(tr)
    hits, total = bt.search(query, tr, limit)
    return {"total": total, "hits": [{"label": bt.Ref(code, ch, v).label(), "text": plain(text)} for code, ch, v, text in hits]}


# ─── a passage pasted from the church's own Bible (2026-11-15) ──────
# Sermon notes may name a version we don't have (NIV, ESV …: bible_text.LICENSED).
# The pastor pastes the passage from their own Bible app and it goes up as its
# verses, with the publisher's copyright notice. Nothing is ever fetched: these
# are the pasted words, tidied, split into slides the way real verses split.

MAX_PASTED = 2000           # letters a passage, once tidied
MAX_PASTED_RAW = 4000       # what may come in before tidying (links and copyright lines come off)
_INVISIBLE = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CONTROL = re.compile("[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u00a0\u2000-\u200a\u202f\u205f\u3000\t]")
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.I)
# Bible Gateway copies its footnote letters ([a]) and cross references ((A)) with the words.
_MARKS = re.compile(r"\[[a-z]{1,2}\]|\([A-Z]{1,2}\)")
_SUPER = re.compile("[\u2070\u00b9\u00b2\u00b3\u2074-\u2079]+")
_SUPER_DIGITS = str.maketrans("\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079", "0123456789")
_NOTICE = re.compile(r"©|\bcopyright\b|all rights reserved|used by permission", re.I)
_AFTER = re.compile(r"^(?:footnotes?|cross references?)\s*:?$", re.I)
# A verse number: at the start or after a space or an opening mark, then words (not "3:16", "1,000" or "2.5").
_NUM = re.compile(r"(?:(?<=[\s(\[“\"‘'—–-])|^)(\d{1,3})(?=\s*[^\d\s:.,])")
_SENTENCE = re.compile(r".+?(?:[.!?;:]+[”’\"')\]]*(?=\s|$)|$)")


def _just_the_ref(line: str, version: str) -> bool:
    """A line that only names the passage ("John 3:16 NIV", "John 3:16 New International
    Version (NIV)"), the way Bible apps head or sign a copied passage."""
    v = next((x for x in bt.LICENSED.values() if x["short"].lower() == version.lower()), None)
    s = line
    for word in ([v["name"], v["short"]] if v else [version]):
        s = re.sub(rf"\(?\b{re.escape(word)}\b\)?", " ", s, flags=re.I)
    s = s.strip(" .,:;()[]-–—")
    if not s:
        return True                     # the version's name on its own
    m = bt.REF_RE.fullmatch(s)
    return bool(m and bt.ALIASES.get(bt._key(m.group("book"))))


def clean_pasted(raw: str, version: str) -> str:
    """The words pasted for a passage, tidied: what a Bible app adds around a copied
    passage comes off (a link back to it, its reference on a line of its own, the
    copyright lines, footnote letters); verse numbers written small become plain;
    spaces settle. Lines stay lines."""
    text = _SUPER.sub(lambda m: f" {m.group().translate(_SUPER_DIGITS)} ", (raw or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = _CONTROL.sub(" ", _INVISIBLE.sub("", text))
    text = _MARKS.sub("", _LINK.sub(" ", text))
    lines = []
    for line in text.split("\n"):
        line = re.sub(r" {2,}", " ", line).strip()
        if _AFTER.match(line):
            break                       # Bible Gateway's footnotes and cross references, under the words
        if line and (_NOTICE.search(line) or _just_the_ref(line, version)):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _cut_at_numbers(flat: str, ref: bt.Ref) -> Optional[list[dict]]:
    """The words cut at their verse numbers when they carry them ("16 For God so loved …
    17 For God did not send …"): each verse of the passage, in order, that's numbered;
    None when they carry none. Only the numbers the passage expects count (a new
    chapter may write its first verse as the chapter's number), so "the 12" stays."""
    want = [(ch, v) for ch, v, _ in bt.verses(ref, bt.DEFAULT)]
    cuts: list[tuple[int, int, int, int]] = []
    pos = 0
    for k, (ch, v) in enumerate(want):
        names = {v, ch} if v == 1 else {v}
        hit = next((m for m in _NUM.finditer(flat, pos) if int(m.group(1)) in names), None)
        if hit is None or (k == 0 and hit.start() != 0):
            continue                    # left off, or not in this version (NIV has no Matthew 17:21)
        cuts.append((hit.start(), hit.end(), ch, v))
        pos = hit.end()
    return _pieces(flat, want, cuts) if cuts else None


def _pieces(flat: str, want: list[tuple[int, int]], cuts: list[tuple[int, int, int, int]]) -> list[dict]:
    """The words between the numbers, each the verse its number names."""
    out = []
    if cuts[0][0] > 0:                  # the first verse's number was left off
        out.append({"chapter": want[0][0], "verse": want[0][1], "text": flat[:cuts[0][0]].strip()})
    for i, (_s, e, ch, v) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(flat)
        out.append({"chapter": ch, "verse": v, "text": flat[e:end].strip()})
    return [x for x in out if x["text"]]


def pasted_slides(words: str, ref: bt.Ref, max_chars: int = MAX_SLIDE_CHARS) -> tuple[list[dict], bool]:
    """Pasted words as slides ([{label, verses}]) and whether they carried verse numbers.
    With numbers they split between verses like slides(); without, between sentences,
    each slide named for the whole passage."""
    flat = " ".join((words or "").split())
    if not flat:
        return [], False
    numbered = _cut_at_numbers(flat, ref)
    if numbered:
        groups: list[list[dict]] = []
        cur: list[dict] = []
        size = 0
        for v in numbered:
            if cur and size + len(v["text"]) > max_chars:
                groups.append(cur)
                cur, size = [], 0
            cur.append(v)
            size += len(v["text"]) + 1
        if cur:
            groups.append(cur)
        return labelled(ref, groups), True
    chunks: list[str] = []
    for s in (m.group().strip() for m in _SENTENCE.finditer(flat)):
        if s and chunks and len(chunks[-1]) + 1 + len(s) <= max_chars:
            chunks[-1] = f"{chunks[-1]} {s}"
        elif s:
            chunks.append(s)    # a sentence longer than a slide stays whole, as a long verse does
    first = {"chapter": ref.chapter, "verse": ref.start or 1}
    return [{"label": ref.label(), "verses": [{**first, "text": c}]} for c in chunks], False
