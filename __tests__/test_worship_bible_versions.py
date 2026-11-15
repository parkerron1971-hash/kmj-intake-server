# __tests__/test_worship_bible_versions.py
#
# Four free Bible versions, and a sermon's passages in any version
# (2026-11-15; Kevin: "let's do it ... and make sure to add the other free
# version of the bible"). Pins:
#   * BSB and ASV are here like KJV and WEB: 66 books, every verse with words,
#     the verses people know, references, search, the booth's lookup, the
#     member app's Bible
#   * sermon notes keep each passage's own version; a passage in a version we
#     don't have (NIV, ESV …) comes in as the words the pastor pasted, tidied,
#     split like verses, its publisher's notice on its last slide; refusals
#   * what was saved before comes back and draws exactly as it did

import gzip
import pathlib
import sys

import pytest

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import bible_text as bt  # noqa: E402
import member_portal_bible as mpb  # noqa: E402
import worship_scripture as ws  # noqa: E402
import worship_show as wsh  # noqa: E402
from test_member_portal_bible import _quiet, cookie_of, go  # noqa: E402,F401  (the member app's stand-ins)
from test_worship_show_router import BIZ, ITEMS, api, plan  # noqa: E402,F401  (the HTTP stand-ins)

FOUR = ["kjv", "web", "bsb", "asv"]
JOHN_3_16 = {
    "kjv": "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.",
    "web": "For God so loved the world, that he gave his only born Son, that whoever believes in him should not perish, but have eternal life.",
    "bsb": "For God so loved the world that He gave His one and only Son, that everyone who believes in Him shall not perish but have eternal life.",
    "asv": "For God so loved the world, that he gave his only begotten Son, that whosoever believeth on him should not perish, but have eternal life.",
}


# ─── the text ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("tr", ["bsb", "asv"])
def test_the_new_files_hold_the_66_books_and_every_verse_has_words(tr):
    rows = [ln.rstrip("\n").split("\t") for ln in gzip.open(bt.DATA / f"{tr}.tsv.gz", "rt", encoding="utf-8")]
    assert all(len(r) == 4 for r in rows)
    assert [c for c, _, _ in bt.BOOKS] == list(dict.fromkeys(r[0] for r in rows))   # the 66, in order
    assert 31_000 <= len(rows) <= 31_110 and all(r[3].strip() for r in rows)
    assert len({(r[0], r[1], r[2]) for r in rows}) == len(rows)                      # no verse twice
    assert len({(r[0], r[1]) for r in rows}) == 1189


@pytest.mark.parametrize("tr", FOUR)
def test_the_verses_people_know(tr):
    v = lambda code, ch, n: dict(bt.chapter(code, ch, tr))[n]  # noqa: E731
    assert v("JOH", 3, 16).lstrip("¶ ") == JOHN_3_16[tr]       # the KJV's ¶ starts a paragraph there
    assert {"kjv": "The LORD [is] my shepherd", "web": "Yahweh is my shepherd", "bsb": "The LORD is my shepherd",
            "asv": "Jehovah is my shepherd"}[tr] in v("PSA", 23, 1)
    assert v("GEN", 1, 1).startswith("In the beginning")
    assert bt.TRANSLATIONS[tr]["short"] == tr.upper()


def test_the_asv_reads_plainly_on_slides_and_in_italics_in_the_member_app():
    # Its Selah was opened with a bracket and never closed in the download; here it's plain.
    assert dict(bt.chapter("PSA", 3, "asv"))[2].endswith("There is no help for him in God. Selah")
    assert not any(t.count("[") != t.count("]") for ch in range(1, 151) for _, t in bt.chapter("PSA", ch, "asv"))
    gen = dict(bt.chapter("GEN", 1, "asv"))[11]
    assert "[and] fruit-trees" in gen and ws.plain(gen).count("[") == 0 and "and fruit-trees" in ws.plain(gen)
    # The passage it brackets (John 7:53 to 8:11) opens in one verse and closes in another: slides drop the lone mark.
    assert ws.plain(dict(bt.chapter("JOH", 7, "asv"))[53]).startswith("And they went every man")
    assert "<i>and</i> fruit-trees" in mpb.chapter_html("GEN", 1, "asv")
    bsb = mpb.chapter_html("PSA", 23, "bsb")
    assert 'class="bb-text bb-lines"' in bsb and bsb.count("<p>") == 6 and "<i>" not in bsb


@pytest.mark.parametrize("tr", FOUR)
@pytest.mark.parametrize("text, want", [
    ("Psalm 1:1-3", ["Psalm 1:1-3"]), ("I John 1:9", ["1 John 1:9"]), ("Romans 5:1-5; 8:28", ["Romans 5:1-5", "Romans 8:28"]),
    ("John 3:16, 18-19", ["John 3:16", "John 3:18-19"]), ("John 3:16-4:2", ["John 3:16-4:2"]), ("Jude 3", ["Jude 1:3"]),
    ("see Psalm 23 and Matt. 5:3-12", ["Psalm 23", "Matthew 5:3-12"]), ("This is 3 things", []), ("John 3:99", []),
])
def test_references_read_the_same_in_every_version(tr, text, want):
    assert [r.label() for _, _, r in bt.find_refs(text, tr)] == want


@pytest.mark.parametrize("tr, words, ref", [
    ("bsb", "lord is my shepherd", "Psalm 23:1"), ("asv", "jehovah is my shepherd", "Psalm 23:1"),
    ("bsb", "one and only son", "John 3:16"), ("asv", "believeth on him should not perish", "John 3:16"),
])
def test_search_finds_words_in_the_new_versions(tr, words, ref):
    hits, total = bt.search(words, tr)
    assert total >= 1 and ref in [bt.Ref(c, ch, v).label() for c, ch, v, _ in hits]
    assert ref in [h["label"] for h in ws.find_words(words, tr)["hits"]]


@pytest.mark.parametrize("tr", ["bsb", "asv"])
def test_the_booth_looks_up_and_splits_a_passage_in_the_new_versions(tr):
    ref = ws.lookup("jn 3 16-17", tr)
    assert ref.label() == "John 3:16-17"
    got = ws.choices("jn 3 16", tr)
    assert got["translation"] == tr and got["translation_name"] == tr.upper()
    assert got["choices"][0]["slides"][0]["verses"][0]["text"] == JOHN_3_16[tr]
    assert [s["label"] for s in ws.slides(ws.lookup("psalm 23", tr), tr)][0].startswith("Psalm 23:1")


def test_the_member_app_offers_all_four_and_remembers_the_one_picked():
    page = go("/my/bible").body.decode()
    for tr in FOUR:
        assert f'href="/my/bible?t={tr}"' in page
    r = go("/my/bible/john/3", "t=bsb")
    body = r.body.decode()
    assert "bsb|john/3" in cookie_of(r) and 'href="/my/bible/john/3?t=bsb" aria-current="true"' in body
    assert "He gave His one and only Son" in body and "Berean Standard Bible · public domain" in body
    later = go("/my/bible", cookie="sol_bible=asv|psalms/23").body.decode()
    assert 'href="/my/bible?t=asv" aria-current="true"' in later and "· ASV" in later
    # A search reads the version picked.
    found = go("/my/bible", "q=jehovah is my shepherd&t=asv").body.decode()
    assert "Psalm 23:1" in found and "ASV" in found


# ─── a church's look and Scripture items ──────────────────────────────


@pytest.mark.parametrize("tr", FOUR)
def test_the_look_and_a_scripture_item_take_any_of_the_four(tr):
    assert wsh.clean_look({"translation": tr})["translation"] == tr
    it = wsh.clean_item({"id": "word", "kind": "scripture", "ref": "jn 3 16", "translation": tr})
    shown = wsh.compile_item(it, {})
    assert shown["title"] == f"John 3:16 · {tr.upper()}" and shown["slides"][0]["translation"] == tr.upper()
    assert "notice" not in shown["slides"][-1]


def test_a_scripture_item_still_refuses_a_version_we_dont_have():
    for tr in ("niv", "tpt"):
        with pytest.raises(ValueError, match="isn't here yet"):
            wsh.clean_item({"id": "word", "kind": "scripture", "ref": "jn 3 16", "translation": tr})
    with pytest.raises(ValueError, match="isn't here yet"):
        wsh.clean_look({"translation": "niv"})


# ─── sermon notes: each passage its own version ───────────────────────


def notes(*lines, mode="build"):
    return {"id": "sermon", "kind": "text", "outline": "typed", "slides": [
        {"kicker": "Point 1", "text": "Stop", "mode": mode, "lines": list(lines)}]}


def verse(ref, tr="kjv", **kw):
    return {"kind": "verse", "ref": ref, "translation": tr, "note": "", "br": False, **kw}


def passages(item):
    return [s for s in wsh.compile_item(wsh.clean_item(item), {})["slides"] if s["kind"] == "verse"]


def test_each_passage_keeps_its_own_version():
    item = wsh.clean_item(notes(verse("jn 3 16"), verse("ps 23 1", "bsb"), verse("gen 1 1", "asv"), verse("rom 8 28", "web")))
    assert [(ln["ref"], ln["translation"]) for ln in item["slides"][0]["lines"]] == [
        ("John 3:16", "kjv"), ("Psalm 23:1", "bsb"), ("Genesis 1:1", "asv"), ("Romans 8:28", "web")]
    shown = passages(item)
    assert [(s["label"], s["translation"]) for s in shown] == [
        ("John 3:16", "KJV"), ("Psalm 23:1", "BSB"), ("Genesis 1:1", "ASV"), ("Romans 8:28", "WEB")]
    assert shown[1]["verses"][0]["text"] == "A Psalm of David. The LORD is my shepherd; I shall not want."
    assert all(s["opts"]["version"] is True and "notice" not in s for s in shown)


OLD_NOTES = {"id": "points", "kind": "text", "title": "", "outline": "Stones\n1. Stop\n- Pick up stones\nJoshua 4:6-7\nPs 23 (WEB)",
             "slides": [{"kicker": "", "text": "Stones", "notes": "", "lines": [], "mode": "build"},
                        {"kicker": "Point 1", "text": "Stop", "notes": "", "mode": "build", "lines": [
                            {"kind": "statement", "text": "Pick up stones", "note": "", "br": False},
                            {"kind": "verse", "ref": "Joshua 4:6-7", "translation": "kjv", "note": "", "br": False},
                            {"kind": "statement", "text": "Ps 23 (WEB)", "note": "", "br": False}]}]}


def test_notes_saved_before_come_back_and_draw_exactly_as_they_did():
    clean = wsh.clean_item(OLD_NOTES)
    assert clean["slides"][1]["lines"] == OLD_NOTES["slides"][1]["lines"]   # key for key, no new keys
    assert clean["outline"] == OLD_NOTES["outline"]
    slides = wsh.compile_item(clean, {})["slides"]
    # (Checked against origin/main's worship_show on 2026-11-15: the same, key for key.)
    assert [s["kind"] for s in slides] == ["text", "text", "text", "verse", "verse", "text"]
    for v in slides[3:5]:
        assert set(v) == {"kind", "label", "translation", "verses", "opts", "point"}
        assert (v["translation"], v["opts"]) == ("KJV", {"ref": True, "nums": True, "version": True, "size": None, "align": None})
    assert [slides[3]["label"], slides[4]["label"]] == ["Joshua 4:6", "Joshua 4:7"]
    assert slides[5]["lines"] == ["Pick up stones", "Ps 23 (WEB)"]       # a statement stays a statement
    # A Scripture item saved before is the same too.
    old = {"id": "word", "kind": "scripture", "ref": "Joshua 4:6-7", "translation": "web", "show_nums": False}
    first = wsh.compile_item(wsh.clean_item(old), {})["slides"][0]
    assert {k: v for k, v in first.items() if k != "verses"} == {
        "kind": "verse", "label": "Joshua 4:6", "translation": "WEB",
        "opts": {"ref": True, "nums": False, "version": True, "size": None, "align": None}}


def test_words_sent_with_a_free_version_are_left_off():
    line = wsh.clean_item(notes(verse("jn 3 16", "bsb", words="anything at all")))["slides"][0]["lines"][0]
    assert "words" not in line and line["translation"] == "bsb"


# ─── a passage pasted from the church's own Bible ─────────────────────

# Shaped like a copy from Bible Gateway and from a phone's Bible app; the words are public-domain
# (BSB, WEB) standing in for the pastor's own NIV and ESV, so no licensed text lives here.
BG_PASTE = ("John 3:16-18 New International Version (NIV)\n"
            "16 For God so loved the world that He gave His one and only Son,[a] that everyone who believes in Him shall "
            "not perish but have eternal life. 17 For God did not send His Son into the world to condemn the world, but to "
            "save the world through Him.(A) 18 Whoever believes in Him is not condemned, but whoever does not believe has "
            "already been condemned, because he has not believed in the name of God’s one and only Son.\n\n"
            "Footnotes\nJohn 3:16 Or his only begotten Son\n"
            "New International Version (NIV)\nHoly Bible, New International Version®, NIV® Copyright ©1973, 1978, 1984, "
            "2011 by Biblica, Inc.® Used by permission. All rights reserved worldwide.")
YOUVERSION = ("“For God so loved the world, that he gave his only born Son, that whoever believes in him should not perish, "
              "but have eternal life.”\n\u202d\u202dJohn\u202c \u202d3\u202c:\u202d16\u202c \u202dESV\u202c\u202c\nhttps://bible.com/bible/59/jhn.3.16.ESV")


def test_a_pasted_niv_passage_is_tidied_and_kept_on_its_line():
    line = wsh.clean_item(notes(verse("jn 3 16-18", "niv", words=BG_PASTE, note="slow")))["slides"][0]["lines"][0]
    assert (line["kind"], line["ref"], line["translation"], line["note"]) == ("verse", "John 3:16-18", "niv", "slow")
    w = line["words"]
    assert w.startswith("16 For God so loved the world that He gave His one and only Son, that everyone")
    for gone in ("[a]", "(A)", "Footnotes", "begotten", "©", "Biblica", "New International Version"):
        assert gone not in w
    # Tidied once, it stays the same when it comes back.
    again = wsh.clean_item(notes(dict(line)))["slides"][0]["lines"][0]
    assert again == line


def test_a_pasted_passage_splits_like_verses_and_shows_its_notice_on_its_last_slide():
    shown = passages(notes(verse("jn 3 16-18", "niv", words=BG_PASTE)))
    assert [(s["label"], s["translation"]) for s in shown] == [("John 3:16", "NIV"), ("John 3:17", "NIV"), ("John 3:18", "NIV")]
    assert [v["verse"] for s in shown for v in s["verses"]] == [16, 17, 18]
    assert all(s["opts"]["nums"] is True for s in shown)
    assert "notice" not in shown[0] and "notice" not in shown[1]
    assert shown[-1]["notice"] == bt.LICENSED["niv"]["notice"] and "Biblica" in shown[-1]["notice"]
    # Copied with no verse numbers (a phone's Bible app): one slide, named for the passage, no numbers drawn.
    one = passages(notes(verse("jn 3 16", "esv", words=YOUVERSION)))
    assert len(one) == 1 and one[0]["label"] == "John 3:16" and one[0]["opts"]["nums"] is False
    assert one[0]["verses"][0]["text"].startswith("“For God so loved") and "bible.com" not in one[0]["verses"][0]["text"]
    assert one[0]["notice"].startswith("Scripture quotations are from the ESV® Bible")


def test_a_long_pasted_passage_takes_several_slides_and_counts_toward_the_cap():
    words = " ".join(f"{n} " + "Blessed are they who keep his word and walk in it. " * 3 for n in range(1, 13))
    shown = passages(notes(verse("psalm 119:1-12", "nkjv", words=words)))
    assert len(shown) >= 6 and all(len(" ".join(v["text"] for v in s["verses"])) <= 330 for s in shown)
    assert shown[0]["label"].startswith("Psalm 119:1") and shown[-1]["label"].endswith("12")
    assert sum(1 for s in shown if "notice" in s) == 1
    # No numbers: split between sentences.
    flat = passages(notes(verse("psalm 119:1-12", "nkjv", words="Blessed are they who keep his word. " * 30)))
    assert len(flat) >= 4 and all(s["label"] == "Psalm 119:1-12" for s in flat)
    assert all(s["verses"][0]["text"].endswith(".") for s in flat)


def test_a_pasted_passage_never_goes_up_without_its_words():
    item = wsh.clean_item(notes(verse("jn 3 16", "niv", words="16 For God so loved the world.")))
    assert len(passages(item)) == 1
    item["slides"][0]["lines"][0]["words"] = ""      # a row edited by hand
    assert [s for s in wsh.compile_item(item, {})["slides"] if s["kind"] == "verse"] == []


@pytest.mark.parametrize("line, words", [
    (verse("jn 3 16", "niv"), "Paste John 3:16 from your NIV, or take NIV off the passage"),
    (verse("jn 3 16", "niv", words="   \n "), "Paste John 3:16 from your NIV"),
    (verse("jn 3 16", "niv", words="https://bible.com/bible/111/jhn.3.16.NIV"), "Paste John 3:16 from your NIV"),
    (verse("jn 3 16", "esv", words=["For God"]), "should be text"),
    (verse("jn 3 16", "niv", words="x" * 2001), "too long to show: at most 2,000 letters"),
    (verse("jn 3 16", "niv", words="Love. " * 700), "too long to show"),
    (verse("hezekiah 1 1", "niv", words="Words."), "isn't a passage we can find"),
    (verse("jn 3 16", "tpt", words="Words."), "isn't here yet"),
])
def test_what_a_pasted_passage_cannot_be(line, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_item(notes(line))


def test_a_long_link_and_copyright_lines_dont_count_against_the_words():
    tail = "\n" + "https://www.biblegateway.com/passage/?search=" + "x" * 300 + "\n" + bt.LICENSED["niv"]["notice"] + "\n"
    words = "16 " + "For God so loved the world. " * 60
    line = wsh.clean_item(notes(verse("jn 3 16", "niv", words=words[:1990] + tail * 3)))["slides"][0]["lines"][0]
    assert len(line["words"]) <= 2000 and "biblegateway" not in line["words"]


def test_the_notices_table():
    assert set(bt.LICENSED) == {"niv", "esv", "nkjv", "nlt", "csb", "hcsb", "nasb", "amp", "ampc", "msg", "nrsv", "nrsvue", "rsv"}
    assert not set(bt.LICENSED) & set(bt.TRANSLATIONS)
    shorts = [v["short"] for v in bt.LICENSED.values()]
    assert len(set(s.lower() for s in shorts)) == len(shorts)
    for code, v in bt.LICENSED.items():
        assert v["short"].lower() == code and v["name"]
        assert "©" in v["notice"] and len(v["notice"]) < 400, code


def test_a_pasted_passage_saves_and_reaches_the_screens_with_its_notice(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    sermon = {"id": "sermon", "kind": "text", "title": "Loved", "outline": "1. Loved\nJohn 3:16-18 NIV\nPs 23:1 BSB",
              "slides": [{"kicker": "Point 1", "text": "Loved", "mode": "build", "lines": [
                  verse("John 3:16-18", "niv", words=BG_PASTE, note="read it slowly"), verse("Psalm 23:1", "bsb")]}]}
    sid = plan(as_, items=ITEMS + [sermon]).json()["service"]["id"]
    saved = as_("manager").get(f"/worship/services/{sid}?business_id={BIZ}").json()["service"]["items"][-1]
    lines = saved["slides"][0]["lines"]
    assert lines[0]["translation"] == "niv" and lines[0]["words"].startswith("16 For God") and lines[1]["translation"] == "bsb"
    room = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector", "role": "room"}).json()["screen"]
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "sermon", "slide": 1}})
    slides = as_("stranger").get(f"/worship/screen/{room['token']}/show").json()["items"][-1]["slides"]
    verses = [s for s in slides if s["kind"] == "verse"]
    assert [(s["label"], s["translation"]) for s in verses] == [("John 3:16", "NIV"), ("John 3:17", "NIV"), ("John 3:18", "NIV"),
                                                                ("Psalm 23:1", "BSB")]
    assert verses[2]["notice"] == bt.LICENSED["niv"]["notice"] and "notice" not in verses[3]
    assert all("notes" not in s for s in slides)              # the pastor's note stays on the stage
    # And refused like any line, with nothing saved.
    bad = dict(sermon, slides=[dict(sermon["slides"][0], lines=[verse("John 3:16", "niv")])])
    r = as_("owner").put(f"/worship/services/{sid}", json={"business_id": BIZ, "items": ITEMS + [bad]})
    assert r.status_code == 400 and "Paste John 3:16 from your NIV" in r.json()["detail"]
