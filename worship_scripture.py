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
    """KJV marks words the translators supplied with [brackets]; slides show them plainly."""
    return re.sub(r"\[([^\]]*)\]", r"\1", text or "").strip()


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
