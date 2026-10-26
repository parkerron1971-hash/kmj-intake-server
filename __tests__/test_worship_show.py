# __tests__/test_worship_show.py
#
# The show engine, without a network (worship_show.py). Pins:
#   * what an item may hold: each kind's fields, refusals in plain words,
#     a passage that can't be found refused when it's planned, not on Sunday
#   * a service becomes slides in order: a song in the arrangement asked
#     for (or its first), a passage split between verses, text slides, an
#     announcement, a picture or video, a countdown to the start time
#   * a song that lost its words, or was taken out, says so instead of
#     going up blank
#   * the look: defaults, and refusals for a color, a link or a size that
#     isn't one
#   * what the booth puts on screen: modes, a passage on the spot, a
#     message to the stage

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import worship_show as wsh

SONG_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SONG = {
    "id": SONG_ID, "title": "It Is Well With My Soul", "song_key": "D", "authors": "Horatio Spafford",
    "ccli_number": None, "copyright": "", "public_domain": True, "lines_per_slide": 2,
    "sections": [
        {"id": "v1", "kind": "verse", "number": 1, "label": "Verse 1",
         "lines": ["When peace like a river attendeth my way,", "When sorrows like sea billows roll;",
                   "Whatever my lot, Thou hast taught me to say,", "It is well, it is well with my soul."]},
        {"id": "r", "kind": "refrain", "number": None, "label": "Refrain",
         "lines": ["It is well with my soul,", "It is well, it is well with my soul."]},
    ],
    "arrangements": [{"id": "main", "name": "Sunday", "order": ["v1", "r", "r"]},
                     {"id": "short", "name": "Short", "order": ["r"]}],
}


def item(kind, **kw):
    return {"id": kw.pop("id", kind[:4] + "1"), "kind": kind, **kw}


def test_each_kind_is_cleaned():
    assert wsh.clean_item(item("section", title="Worship"))["title"] == "Worship"
    s = wsh.clean_item(item("song", song_id=SONG_ID, arrangement_id="short", minutes=5, who="Worship team"))
    assert (s["song_id"], s["arrangement_id"], s["minutes"], s["show"]) == (SONG_ID, "short", 5.0, "all")
    v = wsh.clean_item(item("scripture", ref="josh 4 6-7"))
    assert (v["ref"], v["translation"]) == ("Joshua 4:6-7", "kjv")
    t = wsh.clean_item(item("text", title="What Mean These Stones?", slides=[{"kicker": "Point 1", "text": "Pick up stones."}]))
    assert t["slides"] == [{"kicker": "Point 1", "text": "Pick up stones.", "notes": ""}]
    a = wsh.clean_item(item("announcement", title="The Making", when="Thursdays", image_url="https://x.example/a.jpg"))
    assert a["image_url"] == "https://x.example/a.jpg"
    m = wsh.clean_item(item("media", url="https://x.example/v.mp4", media_kind="video", loop=True, show="room"))
    assert (m["media_kind"], m["loop"], m["show"]) == ("video", True, "room")
    c = wsh.clean_item(item("countdown"))
    assert (c["title"], c["to"]) == ("We start soon", None)


@pytest.mark.parametrize("raw, words", [
    (item("hymn"), "isn't a kind of item"),
    ({"id": "BAD ID", "kind": "section"}, "its own id"),
    (item("section", show="lobby"), "room only, or online only"),
    (item("song", song_id="not-a-uuid"), "Pick a song"),
    (item("scripture", ref="hezekiah 4 1"), "isn't a passage we can find"),
    (item("scripture", ref="john 3 16", translation="niv"), "isn't here yet"),
    (item("text", slides=[]), "1 to 30 slides"),
    (item("text", slides=[{"text": " "}]), "has no words"),
    (item("announcement", title=""), "Give the announcement a title"),
    (item("announcement", title="x", image_url="http://plain.example/a.jpg"), "https://"),
    (item("media", url=""), "Pick a picture or video"),
    (item("media", url="https://x.example/a.gif", media_kind="gif"), "a picture or a video"),
    (item("countdown", to="soonish"), "a time to count to"),
    (item("section", minutes=500), "0 to 240"),
])
def test_what_an_item_cannot_be(raw, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_item(raw)


def test_items_need_their_own_ids():
    with pytest.raises(ValueError, match="share an id"):
        wsh.clean_items([item("section", id="a"), item("section", id="a")])
    with pytest.raises(ValueError, match="at most 80"):
        wsh.clean_items([item("section", id=f"s{k}") for k in range(81)])


def test_a_service_becomes_slides_in_order():
    service = {"id": "svc", "title": "Sunday", "starts_at": "2026-10-25T15:05:00+00:00", "items": wsh.clean_items([
        item("countdown", id="count"),
        item("section", id="worship", title="Worship"),
        item("song", id="well", song_id=SONG_ID),
        item("song", id="well-short", song_id=SONG_ID, arrangement_id="short"),
        item("scripture", id="word", ref="Joshua 4:6-7"),
        item("text", id="pts", slides=[{"kicker": "Point 1", "text": "One"}, {"kicker": "Point 2", "text": "Two"}]),
        item("announcement", id="ann", title="The Making", when="Thursdays"),
        item("media", id="vid", url="https://x.example/v.mp4", media_kind="video"),
    ])}
    show = wsh.compile_show(service, {SONG_ID: SONG})
    by = {i["id"]: i for i in show["items"]}
    assert [i["id"] for i in show["items"]] == ["count", "worship", "well", "well-short", "word", "pts", "ann", "vid"]
    assert by["count"]["slides"] == [{"kind": "countdown", "to": "2026-10-25T15:05:00+00:00", "title": "We start soon"}]
    assert by["worship"]["slides"] == []
    # The first arrangement: verse 1 in two slides, then the refrain twice.
    assert [s["label"] for s in by["well"]["slides"]] == ["Verse 1", "Verse 1", "Refrain", "Refrain"]
    assert by["well"]["slides"][0]["lines"] == SONG["sections"][0]["lines"][:2]
    assert by["well"]["song"]["order"] == ["Verse 1", "Refrain", "Refrain"]
    assert [s["label"] for s in by["well-short"]["slides"]] == ["Refrain"]
    verses = [v["verse"] for s in by["word"]["slides"] for v in s["verses"]]
    assert verses == [6, 7] and by["word"]["slides"][0]["translation"] == "KJV"
    assert by["word"]["title"] == "Joshua 4:6-7 · KJV"
    assert [s["kicker"] for s in by["pts"]["slides"]] == ["Point 1", "Point 2"]
    assert by["ann"]["slides"][0]["kind"] == "announcement"
    assert by["vid"]["slides"][0] == {"kind": "video", "url": "https://x.example/v.mp4", "title": "", "loop": False}
    assert show["slide_count"] == 1 + 4 + 1 + len(by["word"]["slides"]) + 2 + 1 + 1
    assert show["missing"] == []


def test_a_song_without_words_or_taken_out_says_so():
    empty = {**SONG, "sections": [], "arrangements": []}
    service = {"items": [item("song", id="a", song_id=SONG_ID), item("song", id="b", song_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")]}
    show = wsh.compile_show(service, {SONG_ID: empty})
    assert [(m["id"], m["missing"]) for m in show["missing"]] == [("a", "words"), ("b", "song")]
    assert show["slide_count"] == 0


def test_the_look_defaults_and_refusals():
    assert wsh.clean_look({}) == wsh.clean_look(None) == {**wsh.DEFAULT_LOOK, "background": {**wsh.DEFAULT_LOOK["background"]}}
    look = wsh.clean_look({"background": {"kind": "image", "url": "https://x.example/stage.jpg", "dim": 0.6},
                           "size": "big", "caps": True, "translation": "web", "lower_third": {"style": "shadow"}})
    assert look["background"] == {"kind": "image", "color": None, "url": "https://x.example/stage.jpg", "dim": 0.6}
    assert (look["size"], look["caps"], look["translation"], look["lower_third"]) == ("big", True, "web", {"style": "shadow", "position": "bottom"})
    for bad, words in [({"background": {"kind": "color"}}, "Pick the background color"),
                       ({"background": {"kind": "color", "color": "plum"}}, "#2E1A47"),
                       ({"background": {"kind": "image", "url": "javascript:alert(1)"}}, "https://"),
                       ({"background": {"dim": 0.95}}, "0 to 0.85"),
                       ({"size": "huge"}, "smaller, standard or larger"),
                       ({"font": "Comic</style>"}, "isn't a font"),
                       ({"lower_third": {"style": "neon"}}, "bar or words with a shadow")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_look(bad)


def test_what_the_booth_puts_on_screen():
    live = wsh.clean_live({"service_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "item_id": "well", "slide": 3, "mode": "black"})
    assert (live["mode"], live["slide"], live["item_id"]) == ("black", 3, "well")
    adhoc = wsh.clean_live({"adhoc": {"kind": "verse", "title": "Romans 8:28", "slides": [{"kind": "verse", "label": "Romans 8:28", "verses": []}]},
                            "message": "  Wrap up in 5 "})
    assert adhoc["adhoc"]["title"] == "Romans 8:28" and adhoc["message"] == "Wrap up in 5"
    for bad, words in [({"mode": "party"}, "black, the logo or no words"),
                       ({"slide": -1}, "isn't a slide"),
                       ({"item_id": "Not Ok"}, "isn't an item"),
                       ({"adhoc": {"kind": "hymnbook", "slides": [{}]}}, "a passage, a song or words"),
                       ({"adhoc": {"kind": "song", "slides": [{"kind": "verse"}]}}, "don't match"),
                       ({"message": "x" * 121}, "at most 120")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_live(bad)


def test_a_church_without_a_brand_kit_sets_its_colors_in_the_look():
    look = wsh.clean_look({"brand": {"primary": "#1C0B1F", "accent": "#C2125F", "logo_url": "https://x.example/logo.png"}})
    assert look["brand"] == {"primary": "#1C0B1F", "accent": "#C2125F", "background": None, "logo_url": "https://x.example/logo.png"}
    assert wsh.clean_look({})["brand"] == {"primary": None, "accent": None, "background": None, "logo_url": None}
    for bad, words in [({"brand": {"primary": "plum"}}, "#2E1A47"), ({"brand": {"logo_url": "http://x.example/l.png"}}, "https://")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_look(bad)


def test_a_song_slot_waits_for_its_song():
    slot = wsh.clean_item(item("song", id="slot"))
    assert slot["song_id"] is None
    show = wsh.compile_show({"items": [slot]}, {})
    assert show["items"][0]["title"] == "Pick a song" and show["items"][0]["slides"] == []
    assert show["missing"] == [{"id": "slot", "title": "Pick a song", "missing": "pick"}]


def test_a_passage_slot_waits_for_its_passage():
    slot = wsh.clean_item(item("scripture", id="word", ref=""))
    assert slot["ref"] == ""
    show = wsh.compile_show({"items": [slot]}, {})
    assert show["items"][0]["title"] == "Pick a passage" and show["items"][0]["slides"] == []
    assert show["missing"] == [{"id": "word", "title": "Pick a passage", "missing": "pick"}]


def test_a_song_or_typed_words_go_up_on_the_spot():
    song = wsh.clean_live({"adhoc": {"kind": "song", "title": "A song", "slides": [{"kind": "lyric", "label": "Verse 1", "lines": ["line one"]}]}})
    assert song["adhoc"]["kind"] == "song"
    words = wsh.clean_live({"adhoc": {"kind": "text", "title": "Welcome", "slides": [{"kind": "text", "kicker": "", "text": "Welcome home"}]}})
    assert words["adhoc"]["slides"][0]["text"] == "Welcome home"



# ─── the passage editor (canvas board 32) ─────────────────────────────

def test_a_passage_keeps_how_it_goes_up():
    v = wsh.clean_item(item("scripture", ref="ps 23", split="verse", breaks=["23:4", "23:1", "23:4"],
                            fixes={"23:1": "  Our   own words  ", "23:2": ""}, show_nums=False, size="big", align="left"))
    assert (v["split"], v["breaks"], v["fixes"]) == ("verse", ["23:1", "23:4"], {"23:1": "Our own words"})
    assert (v["show_ref"], v["show_nums"], v["show_version"], v["size"], v["align"]) == (True, False, True, "big", "left")
    plain = wsh.clean_item(item("scripture", ref="ps 23"))
    assert (plain["split"], plain["breaks"], plain["fixes"], plain["size"], plain["align"]) == ("fit", None, {}, None, None)


@pytest.mark.parametrize("extra, words", [
    ({"split": "chunks"}, "splits to fit"),
    ({"breaks": ["four"]}, "name a verse"),
    ({"breaks": "23:4"}, "name a verse"),
    ({"fixes": {"verse four": "x"}}, "names its verse"),
    ({"fixes": {"23:1": "x" * 601}}, "600 letters"),
    ({"size": "huge"}, "small, standard or big"),
    ({"align": "right"}, "centered or on the left"),
])
def test_what_a_passage_cannot_be(extra, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_item(item("scripture", ref="ps 23", **extra))


def test_a_passage_goes_up_its_own_way():
    one_a_slide = wsh.compile_item(wsh.clean_item(item("scripture", ref="ps 23", split="verse")), {})
    assert [s["label"] for s in one_a_slide["slides"]] == [f"Psalm 23:{n}" for n in range(1, 7)]
    by_hand = wsh.compile_item(wsh.clean_item(item("scripture", ref="ps 23", breaks=["23:4"])), {})
    assert [s["label"] for s in by_hand["slides"]] == ["Psalm 23:1-3", "Psalm 23:4-6"]
    fixed = wsh.compile_item(wsh.clean_item(item("scripture", ref="jn 3 16", fixes={"3:16": "Our own words"}, show_ref=False)), {})
    slide = fixed["slides"][0]
    assert slide["verses"][0]["text"] == "Our own words"
    assert slide["opts"] == {"ref": False, "nums": True, "version": True, "size": None, "align": None}


# ─── the confidence screen (canvas board 33) ───────────────────────────

def test_notes_for_the_stage_ride_with_the_item():
    s = wsh.clean_item(item("song", song_id=SONG_ID, stage="  Key change into verse 4  "))
    assert s["stage"] == "Key change into verse 4"
    t = wsh.clean_item(item("text", title="Points", slides=[{"kicker": "Point 1", "text": "Pick up stones.", "notes": "Hold up the river stone."}]))
    assert t["slides"][0]["notes"] == "Hold up the river stone."
    shown = wsh.compile_item(t, {})
    assert shown["stage"] == "" and shown["slides"][0]["notes"] == "Hold up the river stone."
    with pytest.raises(ValueError, match="note for the stage"):
        wsh.clean_item(item("song", stage="x" * 501))
    with pytest.raises(ValueError, match="point's notes"):
        wsh.clean_item(item("text", slides=[{"text": "a", "notes": "x" * 1001}]))


def test_a_stage_screen_keeps_its_own_settings():
    assert wsh.clean_stage(None) == {"layout": "auto", "size": "std",
                                     "show": {k: k != "picture" for k in wsh.STAGE_SHOWS}}
    got = wsh.clean_stage({"layout": "pastor", "size": "big", "show": {"next": False, "picture": True, "bogus": True}})
    assert (got["layout"], got["size"], got["show"]["next"], got["show"]["picture"], got["show"]["clock"]) == ("pastor", "big", False, True, True)
    assert "bogus" not in got["show"]
    with pytest.raises(ValueError, match="band's, the pastor's"):
        wsh.clean_stage({"layout": "karaoke"})
    with pytest.raises(ValueError, match="small, standard or big"):
        wsh.clean_stage({"size": "huge"})


def test_the_live_state_says_when_the_item_went_up():
    live = wsh.clean_live({"item_id": "well", "slide": 2, "since": "2026-10-25T15:12:00.000Z"})
    assert live["since"] == "2026-10-25T15:12:00.000Z"
    assert "since" not in wsh.clean_live({"item_id": "well"})
    for bad in ("soon", 5, "x" * 41):
        with pytest.raises(ValueError, match="isn't a time"):
            wsh.clean_live({"item_id": "well", "since": bad})


# ─── loops and a church's own quick screens (canvas board 29) ──────────

def test_a_loop_plays_its_slides_by_themselves():
    loop = wsh.clean_item(item("loop", title="Welcome loop", seconds=7, shuffle=True, until="press", slides=[
        {"kind": "image", "url": "https://x.example/series.jpg", "title": "Series"},
        {"kind": "text", "text": "Welcome home", "seconds": 10}]))
    assert (loop["seconds"], loop["until"], loop["shuffle"], len(loop["slides"])) == (7, "press", True, 2)
    shown = wsh.compile_item(loop, {})
    assert [s["seconds"] for s in shown["slides"]] == [7, 10]
    assert shown["slides"][0]["kind"] == "image" and shown["slides"][1] == {"kind": "text", "kicker": "", "text": "Welcome home", "seconds": 10}
    assert shown["loop"] == {"seconds": 7, "until": "press", "until_at": "", "shuffle": True,
                             "from_board": False, "corner": False, "count_to": None}
    timed = wsh.clean_item(item("loop", until="time", until_at="2026-10-25T14:58:00Z", slides=[{"kind": "text", "text": "Hi"}]))
    assert timed["until_at"] == "2026-10-25T14:58:00Z"


@pytest.mark.parametrize("extra, words", [
    ({"slides": []}, "1 to 40 slides"),
    ({"slides": [{"kind": "song"}]}, "pictures, videos or words"),
    ({"slides": [{"kind": "image", "url": "http://x.example/a.jpg"}]}, "https://"),
    ({"slides": [{"kind": "text", "text": ""}]}, "no words"),
    ({"slides": [{"kind": "text", "text": "a"}], "seconds": 1}, "3 to 120 seconds"),
    ({"slides": [{"kind": "text", "text": "a", "seconds": 500}]}, "3 to 120 seconds"),
    ({"slides": [{"kind": "text", "text": "a"}], "until": "forever"}, "a press or until a time"),
    ({"slides": [{"kind": "text", "text": "a"}], "until": "time", "until_at": "soon"}, "time the loop stops"),
])
def test_what_a_loop_cannot_be(extra, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_item(item("loop", **extra))


def test_a_church_keeps_its_own_quick_screens():
    look = wsh.clean_look({"quick": [{"id": "amen", "kind": "text", "label": "Amen", "key": "a"},
                                     {"id": "give", "kind": "image", "label": "Giving", "url": "https://x.example/g.png", "key": "G"}]})
    assert look["quick"] == [{"id": "amen", "kind": "text", "label": "Amen", "key": "A", "text": "Amen"},
                             {"id": "give", "kind": "image", "label": "Giving", "key": "G", "url": "https://x.example/g.png"}]
    assert wsh.clean_look({})["quick"] == []
    for bad, words in [([{"id": "x", "kind": "text", "label": "X", "key": "B"}], "C, L and B are taken"),
                       ([{"id": "x", "kind": "text", "label": "X", "key": "A"}, {"id": "y", "kind": "text", "label": "Y", "key": "A"}], "its own letter"),
                       ([{"id": "x", "kind": "video", "label": "X"}], "words or a picture"),
                       ([{"id": "x", "kind": "image", "label": "X"}], "Pick the quick screen's picture"),
                       ([{"id": "x", "kind": "text", "label": ""}], "Give the quick screen a name"),
                       ([{"id": f"q{k}", "kind": "text", "label": "Q"} for k in range(9)], "Up to 8")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_look({"quick": bad})


def test_a_quick_screen_picture_goes_up_on_the_spot():
    live = wsh.clean_live({"adhoc": {"kind": "image", "title": "Giving", "slides": [{"kind": "image", "url": "https://x.example/g.png", "title": "Giving"}]}})
    assert live["adhoc"]["kind"] == "image"
    with pytest.raises(ValueError, match="https://"):
        wsh.clean_live({"adhoc": {"kind": "image", "title": "x", "slides": [{"kind": "image", "url": "javascript:alert(1)"}]}})
