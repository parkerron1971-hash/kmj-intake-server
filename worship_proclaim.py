# worship_proclaim.py
#
# Reads a church's own Proclaim data so its songs come over to the Sunday
# presenter (ChurchSavvy). Proclaim keeps one SQLite file per "manager"
# under %LOCALAPPDATA%\Proclaim\Data\<profile>\:
#
#   FaithlifeMusicManager.db   Arrangements (one row per song arrangement:
#                              JSON with key + words) and
#                              WorshipTeamSongData (times sung per year)
#   PresentationManager.db     ServiceItems (every slide group in every
#                              service; songs carry their own copy of the
#                              words in "_richtextfield:Lyrics")
#
# Love City's data showed why both files matter: the song library had words
# for 11 of 89 arrangements, while the services held words for 87 of the
# 92 songs ever used. So a song takes the fullest words found in either.
#
# Files are opened read-only and immutable; nothing is written to them.
# This module only reads and shapes; the router saves the result.

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import worship_lyrics as wl

SQLITE_MAGIC = b"SQLite format 3\x00"
SAMPLE_TITLES = {"example song"}


def is_sqlite_file(path: str | Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _connect(path: str | Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def kind_of(path: str | Path) -> str | None:
    """'music' or 'presentations' for a Proclaim file, None for anything else."""
    if not is_sqlite_file(path):
        return None
    try:
        con = _connect(path)
        try:
            tables = _tables(con)
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if {"Arrangements", "WorshipTeamSongData"} <= tables:
        return "music"
    if {"Presentations", "ServiceItems"} <= tables:
        return "presentations"
    return None


def _norm_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _word_count(lines: list[str]) -> int:
    return sum(1 for ln in lines if ln.strip())


def _order_from_labels(parsed: dict, sequence: str | None) -> list[str] | None:
    """Proclaim's "Versus 1, Pre-chorus, Chorus" order, matched to parsed section ids."""
    if not sequence:
        return None
    by_label: dict[str, str] = {}
    for s in parsed["sections"]:
        by_label[re.sub(r"[^a-z0-9]", "", s["label"].lower())] = s["id"]
        if s.get("number") == 1:  # "Verse" also names "Verse 1"
            by_label.setdefault(re.sub(r"[^a-z0-9]", "", wl.KIND_LABELS[s["kind"]].lower()), s["id"])
    out: list[str] = []
    for part in sequence.split(","):
        h = wl._header(part.strip())
        if not h:
            return None
        key = re.sub(r"[^a-z0-9]", "", wl._label(*h).lower())
        sid = by_label.get(key)
        if not sid:
            return None
        out.append(sid)
    return out or None


def read_proclaim(paths: list[str | Path]) -> dict:
    """Songs from any mix of Proclaim files (one or more profile folders)."""
    songs: dict[str, dict] = {}
    song_id_to_key: dict[str, str] = {}
    usage: dict[str, dict] = {}
    services = 0

    def entry(key: str, title: str) -> dict:
        return songs.setdefault(key, {
            "title": title.strip(), "key": None, "lines": [], "words_from": None,
            "proclaim_song_ids": [], "order_sequence": None,
        })

    def offer_words(e: dict, lines: list[str], source: str) -> None:
        if _word_count(lines) > _word_count(e["lines"]):
            e["lines"], e["words_from"] = lines, source

    music = [p for p in paths if kind_of(p) == "music"]
    presentations = [p for p in paths if kind_of(p) == "presentations"]

    for path in music:
        con = _connect(path)
        try:
            for title, arr in con.execute("select SongDisplayTitle, Arrangement from Arrangements where IsDeleted = 0"):
                try:
                    a = json.loads(arr)
                except (TypeError, ValueError):
                    continue
                key = _norm_title(title or a.get("songDisplayTitle"))
                e = entry(key, title or a.get("songDisplayTitle") or "")
                if a.get("songId") is not None:
                    sid = str(a["songId"])
                    song_id_to_key[sid] = key
                    if sid not in e["proclaim_song_ids"]:
                        e["proclaim_song_ids"].append(sid)
                e["key"] = e["key"] or (a.get("key") or None)
                offer_words(e, wl.proclaim_lines(a.get("lyrics")), "library")
            for song_id, year, ytd, last_used in con.execute(
                "select SongId, Year, YtdUsage, LastUsed from WorshipTeamSongData"
            ):
                u = usage.setdefault(str(song_id), {"by_year": {}, "last_sung": None})
                u["by_year"][int(year)] = max(int(ytd or 0), u["by_year"].get(int(year), 0))
                if last_used and (not u["last_sung"] or last_used > u["last_sung"]):
                    u["last_sung"] = last_used[:10]
        finally:
            con.close()

    for path in presentations:
        con = _connect(path)
        try:
            services += con.execute("select count(*) from Presentations where IsDeleted = 0").fetchone()[0]
            for title, content in con.execute(
                "select Title, Content from ServiceItems where ServiceItemKind = 'SongLyrics'"
            ):
                try:
                    c = json.loads(content or "{}")
                except ValueError:
                    continue
                arrangement = {}
                try:
                    arrangement = json.loads(c.get("ProclaimArrangement") or "{}")
                except ValueError:
                    pass
                sid = str(arrangement.get("songId")) if arrangement.get("songId") is not None else None
                key = song_id_to_key.get(sid) if sid else None
                key = key or _norm_title(title)
                e = entry(key, title or "")
                e["key"] = e["key"] or (arrangement.get("key") or None)
                offer_words(e, wl.proclaim_lines(c.get("_richtextfield:Lyrics")), "service")
                if c.get("CustomOrderSequence") and not e["order_sequence"]:
                    e["order_sequence"] = c["CustomOrderSequence"]
        finally:
            con.close()

    out: list[dict] = []
    for key, e in songs.items():
        if key in SAMPLE_TITLES:
            continue
        parsed = wl.parse_lyrics(e["lines"]) if e["lines"] else {"sections": [], "order": [], "meta": {}}
        order = _order_from_labels(parsed, e["order_sequence"]) or parsed["order"]
        by_year: dict[int, int] = {}
        last_sung = None
        for sid in e["proclaim_song_ids"]:
            u = usage.get(sid)
            if not u:
                continue
            for y, n in u["by_year"].items():
                by_year[y] = by_year.get(y, 0) + n
            if u["last_sung"] and (not last_sung or u["last_sung"] > last_sung):
                last_sung = u["last_sung"]
        out.append({
            "title": e["title"] or "Untitled song",
            "needs_title": not e["title"],
            "key": e["key"],
            "sections": parsed["sections"],
            "order": order,
            "has_words": wl.has_words(parsed),
            "words_from": e["words_from"],
            "proclaim_song_ids": e["proclaim_song_ids"],
            "times_sung_by_year": by_year,
            "last_sung": last_sung,
        })
    out.sort(key=lambda s: (s["needs_title"], s["title"].lower()))
    with_words = sum(1 for s in out if s["has_words"])
    return {
        "songs": out,
        "summary": {
            "songs": len(out),
            "with_words": with_words,
            "without_words": len(out) - with_words,
            "untitled": sum(1 for s in out if s["needs_title"]),
            "services": services,
            "files_read": len(music) + len(presentations),
        },
    }
