# __tests__/test_worship_scripture.py
#
# Scripture on the spot (worship_scripture.py). Pins: the booth can type a
# passage the way people say it, two-letter books work when typed on
# purpose, slides break only between verses, KJV's [supplied words] show
# plainly, and the search box offers the passage, one verse more, and the
# chapter.

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import worship_scripture as ws


@pytest.mark.parametrize("typed, want", [
    ("rom 8 28", "rom 8:28"), ("1 cor 13 4-7", "1 cor 13:4-7"), ("jn 3 16-17", "jn 3:16-17"),
    ("ps 23", "ps 23"), ("Romans 8:28", "Romans 8:28"), ("  josh  1 9 ", "josh 1:9"),
])
def test_typed_the_way_people_say_it(typed, want):
    assert ws.normalize_query(typed) == want


@pytest.mark.parametrize("typed, label", [
    ("rom 8 28", "Romans 8:28"), ("jn 3 16-17", "John 3:16-17"), ("ps 23", "Psalm 23"),
    ("1 cor 13 4-7", "1 Corinthians 13:4-7"), ("josh 1 9", "Joshua 1:9"), ("Romans 8", "Romans 8"),
])
def test_the_booth_gets_the_passage_it_asked_for(typed, label):
    assert ws.lookup(typed).label() == label


@pytest.mark.parametrize("typed", ["hello there", "rom 99 1", "zz 3 4", ""])
def test_nonsense_finds_nothing(typed):
    assert ws.lookup(typed) is None
    assert ws.choices(typed)["choices"] == []


def test_supplied_words_show_plainly():
    s = ws.slides(ws.lookup("rom 8 28"))
    assert s == [{"label": "Romans 8:28", "verses": [{"chapter": 8, "verse": 28, "text": (
        "And we know that all things work together for good to them that love God, "
        "to them who are the called according to his purpose.")}]}]


def test_a_long_passage_breaks_only_between_verses():
    s = ws.slides(ws.lookup("ps 23"))
    assert len(s) > 1
    verses = [v["verse"] for slide in s for v in slide["verses"]]
    assert verses == list(range(1, 7))
    assert all(len(" ".join(v["text"] for v in slide["verses"])) <= ws.MAX_SLIDE_CHARS or len(slide["verses"]) == 1 for slide in s)
    assert s[0]["label"].startswith("Psalm 23:1")


def test_the_search_box_offers_the_passage_one_more_verse_and_the_chapter():
    c = ws.choices("rom 8 28")
    assert [x["kind"] for x in c["choices"]] == ["asked", "one_more", "chapter"]
    assert [x["label"] for x in c["choices"]] == ["Romans 8:28", "Romans 8:28-29", "Romans 8"]
    assert c["choices"][2]["verse_count"] == 39 and c["translation_name"] == "KJV"


def test_the_world_english_bible_works_too():
    c = ws.choices("jn 3 16", "web")
    assert c["translation"] == "web" and "loved the world" in c["choices"][0]["slides"][0]["verses"][0]["text"]
