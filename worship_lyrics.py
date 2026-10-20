# worship_lyrics.py
#
# Song words for the Sunday presenter (ChurchSavvy). Every way a church
# hands us words ends up in one shape:
#
#   {"sections": [{"id", "kind", "number", "label", "lines"}],
#    "order":    [section ids, in the order the song is sung],
#    "meta":     {"title", "ccli_number", "authors", "copyright", "had_chords"}}
#
# Inputs:
#   - pasted words or a SongSelect .txt download (headers like "Verse 1",
#     "[Chorus]", "Bridge:"; SongSelect's CCLI footer becomes meta)
#   - Proclaim's stored words: WPF <Paragraph><Run Text=…/> markup with
#     "{Verse1}" marker lines (proclaim_lines turns it into plain lines)
#   - a photo of a lyric sheet, once vision has turned it into text
#
# A blank line inside a section is kept as "" and means "start a new slide
# here". Without headers, blank-line stanzas become sections and a stanza
# that comes back is the chorus.
#
# Pure functions, no I/O: the router and the importer call these.

from __future__ import annotations

import html
import re
from typing import Iterable

KIND_LABELS = {
    "verse": "Verse",
    "chorus": "Chorus",
    "prechorus": "Pre-Chorus",
    "bridge": "Bridge",
    "refrain": "Refrain",
    "tag": "Tag",
    "intro": "Intro",
    "ending": "Ending",
    "interlude": "Interlude",
    "vamp": "Vamp",
    "other": "Part",
}
KIND_IDS = {
    "verse": "v", "chorus": "c", "prechorus": "pc", "bridge": "b", "refrain": "r",
    "tag": "t", "intro": "i", "ending": "e", "interlude": "in", "vamp": "vp", "other": "p",
}
_KIND_WORDS = {
    "verse": "verse", "versus": "verse", "v": "verse",
    "chorus": "chorus", "c": "chorus",
    "prechorus": "prechorus", "pre chorus": "prechorus", "pre-chorus": "prechorus", "pc": "prechorus",
    "bridge": "bridge", "b": "bridge",
    "refrain": "refrain",
    "tag": "tag",
    "intro": "intro",
    "outro": "ending", "ending": "ending", "end": "ending", "coda": "ending",
    "interlude": "interlude", "instrumental": "interlude", "turnaround": "interlude",
    "vamp": "vamp", "channel": "vamp",
}
_HEADER_RE = re.compile(
    r"^[\[\{\(]?\s*(?:repeat\s+)?"
    r"(verse|versus|chorus|pre[\s-]?chorus|bridge|refrain|tag|intro|outro|ending|end|coda|"
    r"interlude|instrumental|turnaround|vamp|channel|v|c|pc|b)"
    r"\s*(\d+)?\s*[\]\}\)]?\s*(?:[:.]|\(?\s*x?\d\s*x?\)?)?\s*$",
    re.IGNORECASE,
)
_CHORD_RE = re.compile(r"^[A-G](?:#|b)?(?:maj|min|m|sus|dim|aug|add)?\d*(?:sus\d*|add\d*)?(?:/[A-G](?:#|b)?)?$")
_CCLI_SONG_RE = re.compile(r"^ccli\s+song\s*(?:#|number|no\.?)?\s*:?\s*(\d{3,9})\s*$", re.IGNORECASE)
_SONGSELECT_NOISE = (
    re.compile(r"^for use solely with the songselect", re.IGNORECASE),
    re.compile(r"^ccli\s+licen[cs]e\s*(?:#|number|no\.?)?", re.IGNORECASE),
    re.compile(r"^all rights reserved", re.IGNORECASE),
    re.compile(r"^www\.ccli\.com", re.IGNORECASE),
)


def _header(line: str) -> tuple[str, int | None] | None:
    """('chorus', 2) for 'Chorus 2' / '[Chorus 2]' / '{Chorus2}'; None for a lyric line."""
    text = line.strip()
    if not text or len(text) > 32:
        return None
    m = _HEADER_RE.match(text)
    if not m:
        return None
    word = re.sub(r"\s+", " ", m.group(1).lower().replace("-", " ")).strip()
    kind = _KIND_WORDS.get(word) or _KIND_WORDS.get(word.replace(" ", ""))
    if not kind:
        return None
    # A bare "C", "B" or "V" without brackets is too easy to confuse with a word.
    if word in ("c", "b", "v", "pc") and not re.match(r"^[\[\{\(]", text) and not m.group(2):
        if word != "pc":
            return None
    return kind, (int(m.group(2)) if m.group(2) else None)


def _is_chord_line(line: str) -> bool:
    tokens = line.split()
    return bool(tokens) and all(_CHORD_RE.match(t) for t in tokens)


def _norm(lines: Iterable[str]) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", "", ln.lower()).strip() for ln in lines if ln.strip())


def _label(kind: str, number: int | None) -> str:
    base = KIND_LABELS[kind]
    return f"{base} {number}" if number else base


def _trim_blanks(lines: list[str]) -> list[str]:
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    # collapse runs of blank lines into one slide break
    cleaned: list[str] = []
    for ln in out:
        if not ln.strip() and cleaned and not cleaned[-1]:
            continue
        cleaned.append("" if not ln.strip() else ln.rstrip())
    return cleaned


def proclaim_lines(xaml: str | None) -> list[str]:
    """Plain lines from Proclaim's stored words (one per <Paragraph>), markers turned into headers."""
    lines: list[str] = []
    for para in re.findall(r"<Paragraph\b[^>]*?(?:/>|>(.*?)</Paragraph>)", xaml or "", flags=re.S):
        runs = re.findall(r'<Run\b[^>]*\bText="([^"]*)"', para or "")
        text = html.unescape("".join(runs)).replace(" ", " ").replace(" ", " ")
        marker = re.fullmatch(r"\s*\{([^}]+)\}\s*", text)
        if marker:
            word = marker.group(1)
            word = re.sub(r"(?i)pre\s*chorus", "Pre-Chorus", word)
            word = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", word)
            text = word
        lines.append(text.rstrip())
    return lines


def _songselect_meta(lines: list[str]) -> tuple[list[str], dict]:
    """Pull CCLI number, authors and copyright out of a SongSelect footer; return the remaining lines."""
    meta: dict = {}
    keep: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        m = _CCLI_SONG_RE.match(ln)
        if m:
            meta["ccli_number"] = m.group(1)
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt and not nxt.startswith(("©", "(c)", "Copyright")) and not any(r.match(nxt) for r in _SONGSELECT_NOISE):
                meta["authors"] = nxt
                i += 1
            i += 1
            continue
        if ln.startswith("©") or re.match(r"(?i)^(\(c\)|copyright\b)", ln):
            meta.setdefault("copyright", ln.lstrip("©").strip() if ln.startswith("©") else ln)
            i += 1
            continue
        if any(r.match(ln) for r in _SONGSELECT_NOISE):
            i += 1
            continue
        keep.append(lines[i])
        i += 1
    return keep, meta


_USR_SECTION_RE = re.compile(r"^\[S\s+A?(\d{3,9})\]\s*$", re.IGNORECASE)
_CHORDPRO_DIRECTIVE_RE = re.compile(r"^\{\s*([a-z_]+)\s*(?::\s*(.*?))?\s*\}\s*$", re.IGNORECASE)
_CHORDPRO_SECTIONS = {
    "start_of_chorus": "Chorus", "soc": "Chorus", "start_of_verse": "Verse", "sov": "Verse",
    "start_of_bridge": "Bridge", "sob": "Bridge",
}
# Directives only ChordPro uses: one of these marks a file as a chart (a
# pasted "{Chorus}" marker alone doesn't).
_CHORDPRO_KNOWN = {
    "title", "t", "subtitle", "st", "artist", "composer", "lyricist", "copyright", "ccli", "key", "tempo", "time",
    "capo", "comment", "c", "ci", "cb", "highlight", "start_of_chorus", "soc", "end_of_chorus", "eoc",
    "start_of_verse", "sov", "end_of_verse", "eov", "start_of_bridge", "sob", "end_of_bridge", "eob",
}


def _from_usr(lines: list[str]) -> tuple[list[str], dict] | None:
    """A SongSelect .usr file: key=value lines; Fields and Words split their parts on "/t" and lines on "/n"."""
    if not any(ln.startswith("Words=") for ln in lines):
        return None
    values: dict = {}
    meta: dict = {}
    for ln in lines:
        m = _USR_SECTION_RE.match(ln.strip())
        if m:
            meta["ccli_number"] = m.group(1)
            continue
        key, sep, value = ln.partition("=")
        if sep:
            values[key.strip().lower()] = value
    if values.get("title"):
        meta["title"] = values["title"].strip()
    if values.get("author"):
        meta["authors"] = " | ".join(a.strip() for a in values["author"].split("|") if a.strip())
    if values.get("copyright"):
        meta["copyright"] = values["copyright"].strip()
    fields = [f.strip() for f in values.get("fields", "").split("/t")]
    out: list[str] = []
    for k, part in enumerate(values.get("words", "").split("/t")):
        label = fields[k] if k < len(fields) and fields[k] else ""
        if label:
            out.append(label)
        out.extend(part.split("/n"))
        out.append("")
    return out, meta


def _from_chordpro(lines: list[str]) -> tuple[list[str], dict] | None:
    """A ChordPro chart: {title: …} directives, [G] chords inside the lines."""
    if not any((m := _CHORDPRO_DIRECTIVE_RE.match(ln.strip())) and m.group(1).lower() in _CHORDPRO_KNOWN for ln in lines):
        return None
    meta: dict = {}
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("#"):
            continue
        d = _CHORDPRO_DIRECTIVE_RE.match(s)
        if d:
            name, value = d.group(1).lower(), (d.group(2) or "").strip()
            if name in ("title", "t") and value:
                meta["title"] = value
            elif name in ("artist", "composer", "lyricist") and value:
                meta["authors"] = f"{meta['authors']} | {value}" if meta.get("authors") else value
            elif name == "copyright" and value:
                meta["copyright"] = value
            elif name == "ccli" and re.fullmatch(r"\d{3,9}", value):
                meta["ccli_number"] = value
            elif name in _CHORDPRO_SECTIONS:
                out += ["", value or _CHORDPRO_SECTIONS[name]]
            elif name.startswith("end_of") or name in ("eoc", "eov", "eob"):
                out.append("")
            elif name in ("comment", "c", "ci", "cb", "highlight") and value:
                out += ["", value]
            elif name not in _CHORDPRO_KNOWN and _header(s):
                out += ["", s]  # a "{Chorus}" marker among the directives
            continue
        out.append(re.sub(r"\[[^\]]*\]", "", ln).rstrip())
    return out, meta


def parse_lyrics(text: str | list[str]) -> dict:
    """Sections + order + meta from pasted words, a SongSelect .txt or .usr file,
    a ChordPro chart, or Proclaim lines."""
    raw = text if isinstance(text, list) else (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    file_meta: dict = {}
    if not isinstance(text, list):
        converted = _from_usr(raw) or _from_chordpro(raw)
        if converted:
            raw, file_meta = converted
    lines, meta = _songselect_meta([ln.replace("\t", " ") for ln in raw])
    for key, value in file_meta.items():
        meta.setdefault(key, value)
    had_chords = any(_is_chord_line(ln) for ln in lines if ln.strip())
    lines = [ln for ln in lines if not (ln.strip() and _is_chord_line(ln))]

    # A title sits alone on top when the words start with a header after a blank line.
    first = next((k for k, ln in enumerate(lines) if ln.strip()), None)
    if first is not None and _header(lines[first]) is None:
        rest = lines[first + 1:]
        nxt = next((ln for ln in rest if ln.strip()), "")
        if rest and not rest[0].strip() and _header(nxt) is not None:
            meta["title"] = lines[first].strip()
            lines = rest

    has_headers = any(_header(ln) for ln in lines)
    sections: list[dict] = []
    order: list[str] = []
    by_norm: dict[str, str] = {}
    by_label: dict[str, dict] = {}
    used_ids: set[str] = set()

    def new_id(kind: str, number: int | None) -> str:
        base = KIND_IDS[kind] + (str(number) if number else "")
        sid, k = base, 2
        while sid in used_ids:
            sid, k = f"{base}-{k}", k + 1
        used_ids.add(sid)
        return sid

    def add(kind: str, number: int | None, body: list[str]) -> None:
        body = _trim_blanks(body)
        label = _label(kind, number)
        key = _norm(body)
        if not key:
            # A header with no words repeats a part sung before ("Chorus" after verse 2).
            prior = by_label.get(label)
            if prior:
                order.append(prior["id"])
            return
        if key in by_norm:
            order.append(by_norm[key])
            return
        if label in by_label:  # same name, different words: number it
            n = 2
            while _label(kind, n) in by_label:
                n += 1
            number, label = n, _label(kind, n)
        sec = {"id": new_id(kind, number), "kind": kind, "number": number, "label": label, "lines": body}
        sections.append(sec)
        by_norm[key] = sec["id"]
        by_label[label] = sec
        order.append(sec["id"])

    if has_headers:
        cur: tuple[str, int | None] | None = None
        body: list[str] = []
        for ln in lines:
            h = _header(ln)
            if h:
                if cur or _norm(body):
                    add(*(cur or ("verse", None)), body)
                cur, body = h, []
            else:
                body.append(ln)
        if cur or _norm(body):
            add(*(cur or ("verse", None)), body)
    else:
        stanzas: list[list[str]] = []
        block: list[str] = []
        for ln in lines + [""]:
            if ln.strip():
                block.append(ln)
            elif block:
                stanzas.append(block)
                block = []
        counts: dict[str, int] = {}
        for st in stanzas:
            counts[_norm(st)] = counts.get(_norm(st), 0) + 1
        verse_n = chorus_n = 0
        verses_total = sum(1 for st in {_norm(s): s for s in stanzas}.values() if counts[_norm(st)] == 1)
        for st in stanzas:
            key = _norm(st)
            if key in by_norm:
                order.append(by_norm[key])
                continue
            if counts[key] > 1:
                chorus_n += 1
                add("chorus", chorus_n if chorus_n > 1 else None, st)
            else:
                verse_n += 1
                add("verse", verse_n if verses_total > 1 else None, st)

    meta["had_chords"] = had_chords
    return {"sections": sections, "order": order, "meta": meta}


def slides_for_section(section: dict, lines_per_slide: int = 2) -> list[list[str]]:
    """Slides for one section: a "" line forces a new slide, otherwise lines go up in groups."""
    slides: list[list[str]] = []
    run: list[str] = []

    def flush() -> None:
        for k in range(0, len(run), max(1, lines_per_slide)):
            slides.append(run[k:k + lines_per_slide])

    for ln in section.get("lines") or []:
        if ln.strip():
            run.append(ln.strip())
        else:
            flush()
            run = []
    flush()
    return slides


def slides_for_song(song: dict, order: list[str] | None = None, lines_per_slide: int = 2) -> list[dict]:
    """Every slide of a song in sung order: [{section_id, label, lines}]."""
    by_id = {s["id"]: s for s in song.get("sections") or []}
    seq = order if order is not None else (song.get("order") or [s["id"] for s in song.get("sections") or []])
    out: list[dict] = []
    for sid in seq:
        sec = by_id.get(sid)
        if not sec:
            continue
        for lines in slides_for_section(sec, lines_per_slide):
            out.append({"section_id": sid, "label": sec["label"], "lines": lines})
    return out


def has_words(song: dict) -> bool:
    return any(ln.strip() for s in song.get("sections") or [] for ln in s.get("lines") or [])


def to_text(song: dict) -> str:
    """Back to editable text: each section as a header line, its words, a blank line between."""
    parts = []
    for s in song.get("sections") or []:
        parts.append(s["label"] + "\n" + "\n".join(s.get("lines") or []))
    return "\n\n".join(parts).strip() + ("\n" if parts else "")
