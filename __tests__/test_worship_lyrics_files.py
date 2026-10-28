# __tests__/test_worship_lyrics_files.py
#
# Song files a church already has, read into parts (worship_lyrics.parse_lyrics).
# Placeholder words only: these tests never carry a real song's lyrics.
#   * a SongSelect .usr file: Fields and Words split on "/t", lines on "/n";
#     its title, CCLI number, authors and copyright become the song's facts
#   * a ChordPro chart: {title}/{artist}/{ccli} directives, start/end of
#     verse/chorus/bridge, {comment: Bridge}, and [G] chords stripped
#   * a pasted "{Chorus}" marker is not mistaken for a chart

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import worship_lyrics as wl

USR = "\n".join([
    "[File]",
    "Type=SongSelect Import File",
    "Version=3.0",
    "[S A1234567]",
    "Title=Sample Song",
    "Author=First Writer | Second Writer",
    "Copyright=2020 Sample Music",
    "Admin=Sample Admin",
    "Keys=G",
    "Fields=Verse 1/tChorus/tVerse 2",
    "Words=line one of verse one/nline two of verse one/tline one of the chorus/nline two of the chorus"
    "/tline one of verse two/nline two of verse two",
])

CHORDPRO = "\n".join([
    "# a chart from the worship leader",
    "{title: Sample Song}",
    "{artist: First Writer}",
    "{ccli: 7654321}",
    "{key: G}",
    "{start_of_verse: Verse 1}",
    "[G]line one of [C]verse one",
    "line [D]two of verse one",
    "{end_of_verse}",
    "{start_of_chorus}",
    "[Em]line one of the [C]chorus",
    "{end_of_chorus}",
    "{comment: Bridge}",
    "line one of the [Am]bridge",
])


def test_a_songselect_usr_file():
    p = wl.parse_lyrics(USR)
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Chorus", "Verse 2"]
    assert p["sections"][0]["lines"] == ["line one of verse one", "line two of verse one"]
    assert p["order"] == ["v1", "c", "v2"]
    m = p["meta"]
    assert (m["title"], m["ccli_number"], m["authors"], m["copyright"]) == (
        "Sample Song", "1234567", "First Writer | Second Writer", "2020 Sample Music")


def test_a_chordpro_chart():
    p = wl.parse_lyrics(CHORDPRO)
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Chorus", "Bridge"]
    assert p["sections"][0]["lines"] == ["line one of verse one", "line two of verse one"]
    assert p["sections"][1]["lines"] == ["line one of the chorus"]
    assert all("[" not in ln for s in p["sections"] for ln in s["lines"])
    assert (p["meta"]["title"], p["meta"]["authors"], p["meta"]["ccli_number"]) == ("Sample Song", "First Writer", "7654321")


def test_a_pasted_chorus_marker_is_not_a_chart():
    pasted = "{Verse 1}\nline one of verse one\nline two of verse one\n\n{Chorus}\nline one of the chorus\nline two of the chorus"
    p = wl.parse_lyrics(pasted)
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Chorus"]


def test_plain_words_are_unchanged():
    plain = "Verse 1\nline one\nline two\n\nChorus\nline three\nline four"
    assert [s["label"] for s in wl.parse_lyrics(plain)["sections"]] == ["Verse 1", "Chorus"]
