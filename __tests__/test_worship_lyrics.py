# __tests__/test_worship_lyrics.py
#
# Song words for the Sunday presenter (worship_lyrics.py). Pins: pasted
# words with headers, words with no headers (the stanza that comes back is
# the chorus), a SongSelect download's footer, Proclaim's stored markup,
# chord lines, and how sections become slides. Fixtures are public-domain
# hymns only.

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import worship_lyrics as wl

IT_IS_WELL = """Verse 1
When peace like a river attendeth my way,
When sorrows like sea billows roll;
Whatever my lot, Thou hast taught me to say,
It is well, it is well with my soul.

Refrain
It is well with my soul,
It is well, it is well with my soul.

Verse 2
Though Satan should buffet, though trials should come,
Let this blest assurance control,
That Christ hath regarded my helpless estate,
And hath shed His own blood for my soul.

Refrain
"""


def labels(parsed):
    by_id = {s["id"]: s["label"] for s in parsed["sections"]}
    return [by_id[i] for i in parsed["order"]]


def test_headers_become_sections_and_an_empty_header_repeats_a_part():
    p = wl.parse_lyrics(IT_IS_WELL)
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Refrain", "Verse 2"]
    assert labels(p) == ["Verse 1", "Refrain", "Verse 2", "Refrain"]
    assert p["sections"][0]["lines"][0] == "When peace like a river attendeth my way,"
    assert p["sections"][1]["kind"] == "refrain"


def test_without_headers_the_stanza_that_comes_back_is_the_chorus():
    text = (
        "Amazing grace! How sweet the sound\nThat saved a wretch like me!\n\n"
        "Praise the Lord, praise the Lord\nLet the earth hear His voice\n\n"
        "'Twas grace that taught my heart to fear,\nAnd grace my fears relieved;\n\n"
        "Praise the Lord, praise the Lord\nLet the earth hear His voice\n"
    )
    p = wl.parse_lyrics(text)
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Chorus", "Verse 2"]
    assert labels(p) == ["Verse 1", "Chorus", "Verse 2", "Chorus"]


@pytest.mark.parametrize("header, kind, number", [
    ("Verse 1", "verse", 1), ("[Chorus]", "chorus", None), ("{Verse2}", "verse", 2), ("Pre-Chorus", "prechorus", None),
    ("PreChorus 2", "prechorus", 2), ("Bridge:", "bridge", None), ("(Chorus)", "chorus", None), ("Versus 1", "verse", 1),
    ("V1", "verse", 1), ("Tag", "tag", None), ("Outro", "ending", None), ("Refrain 2", "refrain", 2),
])
def test_headers_people_actually_write(header, kind, number):
    assert wl._header(header) == (kind, number)


@pytest.mark.parametrize("line", ["C", "B", "When peace like a river", "Verse after verse we sing", "The chorus of angels"])
def test_lyric_lines_are_never_mistaken_for_headers(line):
    assert wl._header(line) is None


def test_a_songselect_download_gives_title_ccli_authors_and_copyright_and_drops_the_terms():
    text = (
        "It Is Well With My Soul\n\nVerse 1\nWhen peace like a river attendeth my way,\nWhen sorrows like sea billows roll;\n\n"
        "Chorus\nIt is well with my soul,\nIt is well, it is well with my soul.\n\n"
        "CCLI Song # 1234567\nHoratio Spafford | Philip Bliss\n© Words: Public Domain\n"
        "For use solely with the SongSelect® Terms of Use. All rights reserved. www.ccli.com\nCCLI License # 7654321\n"
    )
    p = wl.parse_lyrics(text)
    assert p["meta"]["title"] == "It Is Well With My Soul"
    assert p["meta"]["ccli_number"] == "1234567"
    assert p["meta"]["authors"] == "Horatio Spafford | Philip Bliss"
    assert p["meta"]["copyright"].startswith("Words: Public Domain")
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Chorus"]
    assert all("CCLI" not in ln for s in p["sections"] for ln in s["lines"])


def test_proclaim_markup_with_markers_and_blank_paragraphs():
    xaml = (
        '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="{Verse1}" /></Paragraph>'
        '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="When peace like a river attendeth my way," /></Paragraph>'
        '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="When sorrows like sea" /><Run Text=" billows roll;" /></Paragraph>'
        '<Paragraph Language="en-US" Margin="0,0,0,0" />'
        '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="Whatever my lot, Thou hast taught me to say," /></Paragraph>'
        '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="{PreChorus}" /></Paragraph>'
        '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="It is well, it is well with my soul." /></Paragraph>'
    )
    lines = wl.proclaim_lines(xaml)
    assert lines[0] == "Verse 1" and lines[2] == "When sorrows like sea billows roll;" and lines[3] == ""
    p = wl.parse_lyrics(lines)
    assert [s["label"] for s in p["sections"]] == ["Verse 1", "Pre-Chorus"]
    assert p["sections"][0]["lines"] == [
        "When peace like a river attendeth my way,", "When sorrows like sea billows roll;", "", "Whatever my lot, Thou hast taught me to say,"
    ]


def test_proclaim_words_with_no_markers_still_find_the_chorus():
    para = '<Paragraph Language="en-US" Margin="0,0,0,0"><Run Text="{}" /></Paragraph>'.format
    blank = '<Paragraph Language="en-US" Margin="0,0,0,0" />'
    xaml = "".join([para("Holy, holy, holy! Lord God Almighty!"), para("Early in the morning our song shall rise to Thee;"), blank,
                    para("Holy, holy, holy! merciful and mighty!"), para("God in three Persons, blessed Trinity!"), blank,
                    para("Holy, holy, holy! all the saints adore Thee,"), para("Casting down their golden crowns around the glassy sea;"), blank,
                    para("Holy, holy, holy! merciful and mighty!"), para("God in three Persons, blessed Trinity!")])
    p = wl.parse_lyrics(wl.proclaim_lines(xaml))
    assert labels(p) == ["Verse 1", "Chorus", "Verse 2", "Chorus"]


def test_chord_lines_are_dropped_from_the_words_and_noted():
    text = "Verse 1\nD          G         D\nWhen peace like a river attendeth my way,\nA7/C#   D\nWhen sorrows like sea billows roll;\n"
    p = wl.parse_lyrics(text)
    assert p["meta"]["had_chords"] is True
    assert p["sections"][0]["lines"] == ["When peace like a river attendeth my way,", "When sorrows like sea billows roll;"]


def test_the_same_name_with_different_words_is_numbered():
    p = wl.parse_lyrics("Chorus\nfirst chorus words here\n\nVerse\nverse words\n\nChorus\nanother chorus entirely\n")
    assert [s["label"] for s in p["sections"]] == ["Chorus", "Verse", "Chorus 2"]


def test_slides_two_lines_at_a_time_and_a_blank_line_starts_a_new_slide():
    sec = {"id": "v1", "label": "Verse 1", "lines": ["a", "b", "c", "d", "e", "", "f"]}
    assert wl.slides_for_section(sec) == [["a", "b"], ["c", "d"], ["e"], ["f"]]
    assert wl.slides_for_section(sec, lines_per_slide=4) == [["a", "b", "c", "d"], ["e"], ["f"]]


def test_slides_for_a_song_follow_the_sung_order():
    p = wl.parse_lyrics(IT_IS_WELL)
    slides = wl.slides_for_song(p)
    assert [s["label"] for s in slides] == ["Verse 1", "Verse 1", "Refrain", "Verse 2", "Verse 2", "Refrain"]
    short = wl.slides_for_song(p, order=[p["sections"][1]["id"]])
    assert len(short) == 1 and short[0]["lines"][0] == "It is well with my soul,"


def test_text_round_trip_keeps_the_sections():
    p = wl.parse_lyrics(IT_IS_WELL)
    again = wl.parse_lyrics(wl.to_text(p))
    assert [(s["label"], s["lines"]) for s in again["sections"]] == [(s["label"], s["lines"]) for s in p["sections"]]
    assert wl.has_words(p) and not wl.has_words({"sections": []})
