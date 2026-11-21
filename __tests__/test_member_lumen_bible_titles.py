# __tests__/test_member_lumen_bible_titles.py
#
# The new look's Bible reader names the book in full under the chapter's big
# number, as the Look 5.1 mock reads ("THE GOSPEL OF JOHN"): bible_text.TITLES.
# Pins: a title for every one of the 66 books, short and plain; the reader
# shows it (the label a screen reader hears stays "<book> <chapter>"); today's
# reader is unchanged.

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import bible_text as bt
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client  # noqa: F401  (church is a fixture)
from test_member_lumen_bible import bible  # noqa: F401  (bible is a fixture)


def test_every_book_has_a_short_plain_title():
    assert list(bt.TITLES) == [code for code, _, _ in bt.BOOKS]
    for code, title in bt.TITLES.items():
        assert title.startswith("The ") and len(title) <= 40, title
        # the book's own name is in its title ("1 Samuel" as "First Book of Samuel")
        name = bt.NAME[code].split(" ", 1)[-1] if bt.NAME[code][0].isdigit() else bt.NAME[code]
        assert name.rstrip("s") in title or code == "SOL", (code, title)


@pytest.mark.parametrize("code,title", [
    ("GEN", "The Book of Genesis"), ("PSA", "The Book of Psalms"), ("JOH", "The Gospel of John"),
    ("ACT", "The Acts of the Apostles"), ("ROM", "The Letter to the Romans"),
    ("1CO", "The First Letter to the Corinthians"), ("REV", "The Revelation to John"),
    ("1SA", "The First Book of Samuel"), ("JAM", "The Letter of James"), ("3JO", "The Third Letter of John"),
])
def test_the_titles(code, title):
    assert bt.TITLES[code] == title


def _chap(html):
    m = re.search(r'<h1 class="lm-chap">(.*?)</h1>', html, re.S)
    return m.group(1) if m else ""


@pytest.mark.parametrize("path,sr,number,title", [
    ("/my/bible/john/3", "John 3", "3", "The Gospel of John"),
    ("/my/bible/psalms/23", "Psalm 23", "23", "The Book of Psalms"),
    ("/my/bible/1-corinthians/13", "1 Corinthians 13", "13", "The First Letter to the Corinthians"),
    ("/my/bible/acts/2", "Acts 2", "2", "The Acts of the Apostles"),
])
def test_the_reader_names_the_book_in_full(bible, fake, monkeypatch, path, sr, number, title):  # noqa: F811
    html = _client(fake, monkeypatch).get(path).text
    assert _chap(html) == (f'<span class="mp-sr">{sr}</span><b aria-hidden="true">{number}</b>'
                           f'<span aria-hidden="true">{title}</span>')


def test_todays_reader_is_unchanged(bible, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _client(fake, monkeypatch).get("/my/bible/john/3").text
    assert "The Gospel of John" not in html and 'class="lm-chap"' not in html
