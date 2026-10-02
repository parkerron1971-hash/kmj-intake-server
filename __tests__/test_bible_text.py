# __tests__/test_bible_text.py
#
# The Bible text and the references read out of plain words
# (bible_text.py). Pins: both translations carry all 66 books with the
# right chapter counts; references people actually type become the right
# passage; words that only look like books never do.

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bible_text as bt


@pytest.mark.parametrize("tr", ["kjv", "web"])
def test_both_translations_have_the_66_books_and_their_chapters(tr):
    counts = {code: bt.chapter_count(code, tr) for code, _, _ in bt.BOOKS}
    assert len(counts) == 66 and all(counts.values())
    assert (counts["GEN"], counts["PSA"], counts["ISA"], counts["MAT"], counts["REV"]) == (50, 150, 66, 28, 22)
    assert (counts["JUD"], counts["OBA"], counts["PHM"], counts["3JO"]) == (1, 1, 1, 1)
    assert bt.chapter("JOH", 3, tr)[15][0] == 16 and "loved the world" in bt.chapter("JOH", 3, tr)[15][1]


def refs(text, tr="kjv"):
    return [r.label() for _, _, r in bt.find_refs(text, tr)]


@pytest.mark.parametrize("text, want", [
    ("Psalm 1:1-3", ["Psalm 1:1-3"]),
    ("1 Corinthians 12:12-27", ["1 Corinthians 12:12-27"]),
    ("1 Cor 13", ["1 Corinthians 13"]),
    ("I John 1:9", ["1 John 1:9"]),
    ("First Peter 5:7", ["1 Peter 5:7"]),
    ("Phil. 4:13", ["Philippians 4:13"]),
    ("Song of Solomon 2:4", ["Song of Solomon 2:4"]),
    ("Romans 5:1-5; 8:28", ["Romans 5:1-5", "Romans 8:28"]),
    ("John 3:16, 18-19", ["John 3:16", "John 3:18-19"]),
    ("John 3:16-4:2", ["John 3:16-4:2"]),
    ("see Psalm 23 and Matt. 5:3-12", ["Psalm 23", "Matthew 5:3-12"]),
    ("Jude 3", ["Jude 1:3"]),
    ("Am 5:24", ["Amos 5:24"]),
])
def test_references_people_type(text, want):
    assert refs(text) == want


@pytest.mark.parametrize("text", [
    "This is 3 things", "I am 40 years old", "Acts of kindness 3", "Psalm 151", "John 3:99", "Genesis 51",
    "Romans 5:9-2", "", "Sunday 10:30",
])
def test_things_that_are_not_references(text):
    assert refs(text) == []


def test_links_and_passages():
    r = bt.find_refs("Romans 8:28-30")[0][2]
    assert r.href() == "/my/bible/romans/8?v=28-30"
    assert [v for _, v, _ in bt.verses(r)] == [28, 29, 30]
    whole = bt.find_refs("Psalm 23")[0][2]
    assert whole.href() == "/my/bible/psalms/23" and len(bt.verses(whole)) == 6
    across = bt.find_refs("John 3:35-4:2")[0][2]
    assert [(c, v) for c, v, _ in bt.verses(across)] == [(3, 35), (3, 36), (4, 1), (4, 2)]
    assert bt.neighbours("MAL", 4) == (("MAL", 3), ("MAT", 1))
    assert bt.neighbours("GEN", 1)[0] is None and bt.neighbours("REV", 22)[1] is None
