"""
bible_text.py — the Bible text the member app reads, and scripture
references read out of plain words ("Psalm 1:1-3", "1 Cor 13; 15:3-4").

Two public-domain translations ship with the server (eBible.org's
verse-per-line files, the 66 books; see bible_data/README.md):

  kjv   King James Version (1769). Words the translators supplied are
        marked [like this] and shown in italics; ¶ starts a paragraph.
  web   World English Bible.

Licensed translations (NIV, ESV, NLT …) need a publisher's licence and
are not here. The text is read once per translation, lazily, and kept in
memory (about 10 MB each).
"""
from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

DATA = Path(__file__).with_name("bible_data")

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "kjv": {"name": "King James Version", "short": "KJV"},
    "web": {"name": "World English Bible", "short": "WEB"},
}
DEFAULT = "kjv"

# (code in the data, name, extra spellings people write)
BOOKS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("GEN", "Genesis", ("gen", "ge", "gn")), ("EXO", "Exodus", ("ex", "exo", "exod")),
    ("LEV", "Leviticus", ("lev", "le", "lv")), ("NUM", "Numbers", ("num", "nu", "nm", "numb")),
    ("DEU", "Deuteronomy", ("deut", "de", "dt", "deu")), ("JOS", "Joshua", ("josh", "jos", "jsh")),
    ("JDG", "Judges", ("judg", "jdg", "jg", "jdgs")), ("RUT", "Ruth", ("ru", "rth", "rut")),
    ("1SA", "1 Samuel", ("1sam", "1sa", "1sm")), ("2SA", "2 Samuel", ("2sam", "2sa", "2sm")),
    ("1KI", "1 Kings", ("1kgs", "1ki", "1kin", "1kg")), ("2KI", "2 Kings", ("2kgs", "2ki", "2kin", "2kg")),
    ("1CH", "1 Chronicles", ("1chr", "1ch", "1chron")), ("2CH", "2 Chronicles", ("2chr", "2ch", "2chron")),
    ("EZR", "Ezra", ("ezr",)), ("NEH", "Nehemiah", ("neh", "ne")), ("EST", "Esther", ("esth", "est", "es")),
    ("JOB", "Job", ("jb",)), ("PSA", "Psalms", ("psalm", "ps", "psa", "pss", "psm")),
    ("PRO", "Proverbs", ("prov", "pro", "prv", "pr")), ("ECC", "Ecclesiastes", ("eccl", "ecc", "eccles", "qoh")),
    ("SOL", "Song of Solomon", ("songofsongs", "song", "sos", "songs", "sng", "canticles")),
    ("ISA", "Isaiah", ("isa", "is")), ("JER", "Jeremiah", ("jer", "je", "jr")),
    ("LAM", "Lamentations", ("lam", "la")), ("EZE", "Ezekiel", ("ezek", "eze", "ezk")),
    ("DAN", "Daniel", ("dan", "da", "dn")), ("HOS", "Hosea", ("hos", "ho")), ("JOE", "Joel", ("jl", "joe")),
    ("AMO", "Amos", ("am", "amo")), ("OBA", "Obadiah", ("obad", "ob", "oba")), ("JON", "Jonah", ("jnh", "jon")),
    ("MIC", "Micah", ("mic", "mc")), ("NAH", "Nahum", ("nah", "na")), ("HAB", "Habakkuk", ("hab", "hb")),
    ("ZEP", "Zephaniah", ("zeph", "zep", "zp")), ("HAG", "Haggai", ("hag", "hg")),
    ("ZEC", "Zechariah", ("zech", "zec", "zc")), ("MAL", "Malachi", ("mal", "ml")),
    ("MAT", "Matthew", ("matt", "mat", "mt")), ("MAR", "Mark", ("mrk", "mk", "mr", "mar")),
    ("LUK", "Luke", ("luk", "lk")), ("JOH", "John", ("jn", "jhn", "joh")), ("ACT", "Acts", ("act", "ac")),
    ("ROM", "Romans", ("rom", "ro", "rm")), ("1CO", "1 Corinthians", ("1cor", "1co")),
    ("2CO", "2 Corinthians", ("2cor", "2co")), ("GAL", "Galatians", ("gal", "ga")),
    ("EPH", "Ephesians", ("eph", "ephes")), ("PHI", "Philippians", ("phil", "php", "pp")),
    ("COL", "Colossians", ("col", "co")), ("1TH", "1 Thessalonians", ("1thess", "1th", "1thes")),
    ("2TH", "2 Thessalonians", ("2thess", "2th", "2thes")), ("1TI", "1 Timothy", ("1tim", "1ti", "1tm")),
    ("2TI", "2 Timothy", ("2tim", "2ti", "2tm")), ("TIT", "Titus", ("tit", "ti")),
    ("PHM", "Philemon", ("philem", "phm", "phlm")), ("HEB", "Hebrews", ("heb",)),
    ("JAM", "James", ("jas", "jm", "jam")), ("1PE", "1 Peter", ("1pet", "1pe", "1pt")),
    ("2PE", "2 Peter", ("2pet", "2pe", "2pt")), ("1JO", "1 John", ("1jn", "1jo", "1jhn")),
    ("2JO", "2 John", ("2jn", "2jo", "2jhn")), ("3JO", "3 John", ("3jn", "3jo", "3jhn")),
    ("JUD", "Jude", ("jud", "jd")), ("REV", "Revelation", ("rev", "re", "rv", "revelations", "apocalypse")),
]
NAME = {code: name for code, name, _ in BOOKS}
ORDER = {code: i for i, (code, _, _) in enumerate(BOOKS)}
OLD_TESTAMENT = {code for code, _, _ in BOOKS[:39]}


def slug(code: str) -> str:
    """'1CO' → '1-corinthians', the book's part of a reader URL."""
    return NAME[code].lower().replace(" ", "-")


SLUGS = {slug(code): code for code, _, _ in BOOKS}


def _key(words: str) -> str:
    """'1st Cor.' / 'I Corinthians' / 'First Corinthians' → '1cor…'."""
    s = words.lower().replace(".", " ").strip()
    s = re.sub(r"^(iii|third|3rd)\s+", "3", s)
    s = re.sub(r"^(ii|second|2nd)\s+", "2", s)
    s = re.sub(r"^(i|first|1st)\s+", "1", s)
    return re.sub(r"\s+", "", s)


ALIASES: Dict[str, str] = {}
for _code, _name, _extra in BOOKS:
    for _a in (_name, *_extra):
        ALIASES[_key(_a)] = _code
ALIASES["songofsolomon"] = "SOL"


# ─── the text ────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def _load(tr: str) -> Dict[Tuple[str, int], List[Tuple[int, str]]]:
    chapters: Dict[Tuple[str, int], List[Tuple[int, str]]] = {}
    with gzip.open(DATA / f"{tr}.tsv.gz", "rt", encoding="utf-8") as f:
        for line in f:
            book, ch, v, text = line.rstrip("\n").split("\t", 3)
            chapters.setdefault((book, int(ch)), []).append((int(v), text))
    return chapters


def translation(tr: Optional[str]) -> str:
    return tr if tr in TRANSLATIONS else DEFAULT


def chapter_count(code: str, tr: str = DEFAULT) -> int:
    data = _load(translation(tr))
    n = 0
    while (code, n + 1) in data:
        n += 1
    return n


def chapter(code: str, ch: int, tr: str = DEFAULT) -> Optional[List[Tuple[int, str]]]:
    """[(verse, text)] for one chapter, or None when there's no such
    chapter."""
    return _load(translation(tr)).get((code, ch))


def neighbours(code: str, ch: int, tr: str = DEFAULT) -> Tuple[Optional[Tuple[str, int]], Optional[Tuple[str, int]]]:
    """The chapter before and after, crossing book boundaries."""
    i = ORDER[code]
    prev = (code, ch - 1) if ch > 1 else (
        (BOOKS[i - 1][0], chapter_count(BOOKS[i - 1][0], tr)) if i > 0 else None)
    nxt = (code, ch + 1) if ch < chapter_count(code, tr) else (
        (BOOKS[i + 1][0], 1) if i + 1 < len(BOOKS) else None)
    return prev, nxt


# ─── references in plain words ───────────────────────────────────────


class Ref(NamedTuple):
    book: str
    chapter: int
    start: Optional[int] = None       # first verse; None = the whole chapter
    end: Optional[int] = None         # last verse in `chapter`, or in end_chapter
    end_chapter: Optional[int] = None  # "John 3:16-4:2"

    def label(self) -> str:
        out = f"{'Psalm' if self.book == 'PSA' else NAME[self.book]} {self.chapter}"
        if self.start is None:
            return out
        out += f":{self.start}"
        if self.end_chapter:
            return out + f"-{self.end_chapter}:{self.end}"
        return out + (f"-{self.end}" if self.end and self.end != self.start else "")

    def href(self) -> str:
        base = f"/my/bible/{slug(self.book)}/{self.chapter}"
        if self.start is None:
            return base
        last = self.end if self.end and not self.end_chapter else None
        return base + f"?v={self.start}" + (f"-{last}" if last and last != self.start else ("-" if self.end_chapter else ""))


BOOK_WORDS = r"(?:(?:[123]|i{1,3}|first|second|third|1st|2nd|3rd)\s*\.?\s*)?[a-z]+\.?(?:\s+of\s+(?:solomon|songs))?"
REF_RE = re.compile(
    rf"\b(?P<book>{BOOK_WORDS})\s*(?P<ch>\d{{1,3}})"
    r"(?::(?P<v1>\d{1,3})(?:\s*[-–—]\s*(?:(?P<ch2>\d{1,3}):)?(?P<v2>\d{1,3}))?)?",
    re.I)
MORE_RE = re.compile(r"\s*(?P<sep>[;,])\s*(?P<a>\d{1,3})(?::(?P<b>\d{1,3}))?(?:\s*[-–—]\s*(?P<c>\d{1,3}))?(?![\d:])")


def _valid(r: Ref, tr: str) -> bool:
    ch = chapter(r.book, r.chapter, tr)
    if not ch:
        return False
    if r.start is None:
        return True
    last = ch[-1][0]
    if not 1 <= r.start <= last:
        return False
    if r.end_chapter:
        nxt = chapter(r.book, r.end_chapter, tr)
        return bool(nxt) and r.end_chapter > r.chapter and r.end is not None and 1 <= r.end <= nxt[-1][0]
    return r.end is None or r.start <= r.end <= last


def find_refs(text: str, tr: str = DEFAULT) -> List[Tuple[int, int, Ref]]:
    """Every scripture reference in `text` as (start, end, Ref), in order.
    A word that only looks like a book ("Acts of kindness 3") is skipped
    unless it names a real chapter; "Romans 5:1-5; 8:28" yields two."""
    out: List[Tuple[int, int, Ref]] = []
    pos = 0
    while True:
        m = REF_RE.search(text, pos)
        if not m:
            return out
        code = ALIASES.get(_key(m.group("book")))
        if not code:
            # "See Psalm" — the book may start further in ("see psalm 23").
            pos = m.start() + max(1, len(m.group("book").split()[0]))
            continue
        ch = int(m.group("ch"))
        v1 = int(m.group("v1")) if m.group("v1") else None
        if v1 is None and len(re.sub(r"^\d", "", _key(m.group("book")))) <= 2:
            # "is 3", "am 5": a two-letter abbreviation is a book only
            # with chapter AND verse ("Am 5:24").
            pos = m.end()
            continue
        if v1 is None and chapter_count(code, tr) == 1 and ch > 1:
            ch, v1 = 1, ch                # "Jude 3" is verse 3
        ch2 = int(m.group("ch2")) if m.group("ch2") else None
        v2 = int(m.group("v2")) if m.group("v2") else None
        ref = Ref(code, ch, v1, v2 if v1 else None, ch2 if (v1 and ch2 and ch2 != ch) else None)
        if ch2 == ch:
            ref = Ref(code, ch, v1, v2)
        end = m.end()
        if _valid(ref, tr):
            out.append((m.start(), end, ref))
            last = ref
            while True:
                more = MORE_RE.match(text, end)
                if not more:
                    break
                a, b, c = (int(x) if x else None for x in (more.group("a"), more.group("b"), more.group("c")))
                if more.group("sep") == ";" or b is not None or last.start is None:
                    nxt = Ref(code, a, b, c if b else None) if b is not None else Ref(code, a)
                else:                       # "John 3:16, 18-19" — more verses
                    nxt = Ref(code, last.chapter, a, c)
                if not _valid(nxt, tr):
                    break
                out.append((more.start("a"), more.end(), nxt))
                last, end = nxt, more.end()
        pos = end


def verses(ref: Ref, tr: str = DEFAULT) -> List[Tuple[int, int, str]]:
    """(chapter, verse, text) for a reference — the whole chapter when it
    names no verses."""
    out: List[Tuple[int, int, str]] = []
    last_ch = ref.end_chapter or ref.chapter
    for ch in range(ref.chapter, last_ch + 1):
        for v, t in chapter(ref.book, ch, tr) or []:
            if ref.start is not None:
                if ch == ref.chapter and v < ref.start:
                    continue
                if ch == last_ch and ref.end is not None and v > ref.end:
                    continue
                if ref.end is None and not ref.end_chapter and v != ref.start:
                    continue
            out.append((ch, v, t))
    return out
