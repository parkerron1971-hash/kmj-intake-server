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
#   * a background of its own: an item's, or one sermon point's, rides on
#     its slides; nothing set (or "look") follows the church's look
#   * 2026-11-14: a font pair, a design behind the words (the look's or a
#     slide's own), and a sermon series' look on its days; an old look and
#     old backgrounds come back key for key as they were

import pathlib
import sys
from datetime import date

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
    # Round 5: a countdown also carries its look, what happens at zero and the call to the stage.
    assert by["count"]["slides"] == [{"kind": "countdown", "to": "2026-10-25T15:05:00+00:00", "title": "We start soon",
                                      "look": "big", "zero": "next", "band_at": 120, "band_text": "Band to the stage"}]
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
                       ({"lower_third": {"style": "neon"}}, "one of the designs")]:
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


PIC = "https://x.example/stones.jpg"


def test_a_point_or_an_item_can_have_its_own_background():
    # Kevin, 2026-10-26: "if there only want certain design background for certain slides".
    points = wsh.clean_item(item("text", title="Stones", bg={"kind": "color", "color": "#1C0B1F", "url": "https://ignored.example/x.png"}, slides=[
        {"kicker": "Point 1", "text": "Stop and pick up stones."},
        {"kicker": "Point 2", "text": "Stones are for questions.", "bg": {"kind": "image", "url": PIC, "dim": 0.3}},
        {"kicker": "Point 3", "text": "Your story is a stone.", "bg": {"kind": "look"}}]))
    assert points["bg"] == {"kind": "color", "color": "#1C0B1F", "url": None, "dim": 0.55}
    assert "bg" not in points["slides"][0] and "bg" not in points["slides"][2]
    assert points["slides"][1]["bg"] == {"kind": "image", "color": None, "url": PIC, "dim": 0.3}
    slides = wsh.compile_item(points, {})["slides"]
    # The point's own wins; the others take the item's.
    assert [s["bg"]["kind"] for s in slides] == ["color", "image", "color"]

    song = wsh.compile_item(wsh.clean_item(item("song", song_id=SONG_ID, bg={"kind": "video", "url": "https://x.example/waves.mp4"})), {SONG_ID: SONG})
    assert song["slides"] and all(s["bg"]["kind"] == "video" for s in song["slides"])
    verse = wsh.compile_item(wsh.clean_item(item("scripture", ref="jn 3 16", bg={"kind": "color", "color": "#203040"})), {})
    assert verse["slides"][0]["bg"]["color"] == "#203040"
    ann = wsh.compile_item(wsh.clean_item(item("announcement", title="Community Day", bg={"kind": "image", "url": PIC})), {})
    assert ann["slides"][0]["bg"]["url"] == PIC


def test_without_its_own_background_a_slide_follows_the_look():
    for raw in (None, {}, {"kind": "look"}, {"kind": ""}):
        assert wsh.clean_bg(raw) is None
    plain = wsh.compile_item(wsh.clean_item(item("text", slides=[{"text": "Welcome home"}])), {})
    assert "bg" not in plain and "bg" not in plain["slides"][0]
    # Pictures, videos, countdowns and the board's own designs draw their own way: no background of their own.
    media = wsh.clean_item(item("media", url=PIC, bg={"kind": "color", "color": "#000000"}))
    assert "bg" not in media and "bg" not in wsh.compile_item(media, {})["slides"][0]
    spot = wsh.clean_item(item("announcement", from_board=True, bg={"kind": "color", "color": "#000000"}))
    assert "bg" not in spot
    board = [{"kind": "announcement", "title": "Community Day", "when": "", "body": "", "image_url": "", "link": ""}]
    assert all("bg" not in s for s in wsh.compile_item(spot, {}, board=board)["slides"])


@pytest.mark.parametrize("bg, words", [
    ({"kind": "pattern"}, "a color, a picture or a video"),
    ("navy", "a color, a picture or a video"),
    ({"kind": "color", "color": "navy"}, "pick the color"),
    ({"kind": "image"}, "pick the picture"),
    ({"kind": "video", "url": "http://x.example/w.mp4"}, "pick the video"),
    ({"kind": "image", "url": "javascript:alert(1)"}, "pick the picture"),
    ({"kind": "image", "url": PIC, "dim": 0.95}, "darkening is 0 to 0.85"),
    ({"kind": "image", "url": PIC, "dim": True}, "darkening is 0 to 0.85"),
])
def test_what_a_background_cannot_be(bg, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_item(item("song", song_id=SONG_ID, bg=bg))
    with pytest.raises(ValueError, match="Slide 1's background"):
        wsh.clean_item(item("text", slides=[{"text": "Welcome", "bg": bg}]))


# ─── sermon notes as an outline (Kevin, 2026-11-14) ───────────────────


def _old_text_compile(item):
    """compile_item for a text item as it was before sermon notes (main at 8edc0d7d), to hold old items to it."""
    body = {"title": item.get("title") or (item["slides"][0]["kicker"] if item.get("slides") else "") or "Slides",
            "slides": [{"kind": "text", "kicker": s.get("kicker") or "", "text": s["text"], "notes": s.get("notes") or ""}
                       for s in item.get("slides") or []]}
    points = item.get("slides") or []
    for k, s in enumerate(body["slides"]):
        bg = (points[k].get("bg") if k < len(points) else None) or item.get("bg")
        if bg:
            s["bg"] = dict(bg)
    base = {k: item.get(k) for k in ("id", "kind", "show", "notes", "who", "minutes", "stage")}
    return {**base, **body}


@pytest.mark.parametrize("raw", [
    item("text", slides=[{"text": "Welcome home"}]),
    item("text", title="What Mean These Stones?", minutes=30, who="Pastor", stage="Slow down here", slides=[
        {"kicker": "Point 1", "text": "Stop and pick up stones.", "notes": "The stone on my desk"},
        {"kicker": "Point 2", "text": "Stones are for questions.", "bg": {"kind": "image", "url": PIC, "dim": 0.3}},
        {"kicker": "", "text": "Your story is a stone."}]),
    item("text", bg={"kind": "color", "color": "#1C0B1F"}, show="online", slides=[
        {"kicker": "Watching from home?", "text": "Give in the app, under Give."},
        {"kicker": "Point 2", "text": "Two", "bg": {"kind": "look"}}]),
])
def test_text_typed_slide_by_slide_compiles_exactly_as_before(raw):
    cleaned = wsh.clean_item(raw)
    # Nothing new is kept for a text item typed slide by slide.
    assert "outline" not in cleaned and all(set(s) <= {"kicker", "text", "notes", "bg"} for s in cleaned["slides"])
    assert wsh.compile_item(cleaned, {}) == _old_text_compile(cleaned)


NOTES = ("Stones of Remembrance\n1. Stop and pick up stones\n- God stopped them in the middle of the river\n"
         "Note: tell the story of the stone on my desk\n- Remembering is an act of obedience\nJoshua 4:6-7\n"
         "2. Build where people can see\n- Your story is someone else’s stepping stone\n--\n- What will your children ask you?\n"
         "3. Carry it to the next generation\n- Faith is caught before it is taught\n- Tell them what God did for you\n")


def say(text, note="", br=False):
    return {"kind": "statement", "text": text, "note": note, "br": br}


def notes_item(modes=("build", "build", "each"), **kw):
    """The mock's sermon, as the app sends it once it has read the outline (the title: a point with no number)."""
    return item("text", id="sermon", outline=NOTES, minutes=30, **kw, slides=[
        {"kicker": "", "text": "Stones of Remembrance", "lines": [], "mode": "build"},
        {"kicker": "Point 1", "text": "Stop and pick up stones", "mode": modes[0], "lines": [
            say("God stopped them in the middle of the river", "tell the story of the stone on my desk"),
            say("Remembering is an act of obedience"),
            {"kind": "verse", "ref": "josh 4 6-7", "translation": "kjv"}]},
        {"kicker": "Point 2", "text": "Build where people can see", "mode": modes[1], "lines": [
            say("Your story is someone else’s stepping stone"), say("What will your children ask you?", br=True)]},
        {"kicker": "Point 3", "text": "Carry it to the next generation", "mode": modes[2], "lines": [
            say("Faith is caught before it is taught"), say("Tell them what God did for you")]},
    ])


def test_sermon_notes_keep_their_points_lines_and_the_words_as_typed():
    cleaned = wsh.clean_item(notes_item())
    assert cleaned["outline"] == NOTES  # exactly as typed, the last newline too
    title, p1, p2, p3 = cleaned["slides"]
    assert title == {"kicker": "", "text": "Stones of Remembrance", "notes": "", "lines": [], "mode": "build"}
    assert (p1["mode"], p3["mode"]) == ("build", "each")
    assert p1["lines"][0] == say("God stopped them in the middle of the river", "tell the story of the stone on my desk")
    # A passage is found when it's planned and kept by its full name, in the Bible version it was typed for.
    assert p1["lines"][2] == {"kind": "verse", "ref": "Joshua 4:6-7", "translation": "kjv", "note": "", "br": False}
    assert p2["lines"][1]["br"] is True
    # A point with no mode builds up.
    raw = notes_item()
    del raw["slides"][1]["mode"]
    assert wsh.clean_item(raw)["slides"][1]["mode"] == "build"


def test_sermon_notes_go_up_the_way_each_point_says():
    show = wsh.compile_item(wsh.clean_item(notes_item()), {})
    s = show["slides"]
    assert show["title"] == "Stones of Remembrance"
    # The title slide, as words (no number, so no place among the points).
    assert s[0] == {"kind": "text", "kicker": "", "text": "Stones of Remembrance", "notes": ""}
    # Point 1 builds up: the point, then each press adds the next line, the newest marked.
    assert s[1] == {"kind": "text", "kicker": "Point 1", "text": "Stop and pick up stones", "notes": "", "point": 1}
    assert (s[2]["lines"], s[2]["newest"], s[2]["notes"]) == (["God stopped them in the middle of the river"], 0,
                                                             "tell the story of the stone on my desk")
    assert (s[3]["lines"], s[3]["newest"], s[3]["notes"]) == (
        ["God stopped them in the middle of the river", "Remembering is an act of obedience"], 1, "")
    # Its passage comes in as its verses, like a Scripture item's slides.
    assert [(v["kind"], v["label"], v["translation"], v["point"]) for v in s[4:6]] == [
        ("verse", "Joshua 4:6", "KJV", 1), ("verse", "Joshua 4:7", "KJV", 1)]
    assert s[4]["opts"] == {"ref": True, "nums": True, "version": True, "size": None, "align": None}
    # Point 2 builds up too, and "--" starts a fresh slide under the same point.
    assert [(x.get("lines"), x.get("newest")) for x in s[6:9]] == [
        (None, None), (["Your story is someone else’s stepping stone"], 0), (["What will your children ask you?"], 0)]
    # Point 3, one line each: each statement its own slide, the point above it as the small heading.
    assert s[9] == {"kind": "text", "kicker": "Point 3", "text": "Carry it to the next generation", "notes": "", "point": 3}
    assert [(x["kicker"], x["text"]) for x in s[10:]] == [
        ("Point 3 · Carry it to the next generation", "Faith is caught before it is taught"),
        ("Point 3 · Carry it to the next generation", "Tell them what God did for you")]
    assert all("lines" not in x for x in s[10:])
    assert len(s) == 12


def test_all_at_once_puts_the_point_and_its_lines_together_and_the_break_splits():
    raw = item("text", outline="1. One\n- a\n- b\n--\n- c\nps 23:1", slides=[{
        "kicker": "Point 1", "text": "One", "notes": "Breathe", "mode": "all", "lines": [
            say("a", "say it slowly"), say("b"), say("c", br=True),
            {"kind": "verse", "ref": "ps 23:1", "translation": "web", "note": "read it"}]}])
    s = wsh.compile_item(wsh.clean_item(raw), {})["slides"]
    # No point alone first: the point and its lines at once; the notes for the slide come together.
    assert [(x["kind"], x.get("lines"), x.get("notes")) for x in s] == [
        ("text", ["a", "b"], "Breathe\nsay it slowly"), ("text", ["c"], "Breathe"), ("verse", None, "read it")]
    assert "newest" not in s[0] and s[2]["translation"] == "WEB"
    # A point with no statements still shows, whatever its press.
    for mode in wsh.POINT_MODES:
        lone = wsh.compile_item(wsh.clean_item(item("text", outline="1. Alone", slides=[
            {"kicker": "Point 1", "text": "Alone", "mode": mode, "lines": []}])), {})["slides"]
        assert lone == [{"kind": "text", "kicker": "Point 1", "text": "Alone", "notes": "", "point": 1}]


def test_only_numbered_points_count_and_a_point_keeps_its_own_background():
    raw = item("text", bg={"kind": "color", "color": "#203040"}, outline="x", slides=[
        {"kicker": "", "text": "Opening", "mode": "each", "lines": [say("Welcome")]},
        {"kicker": "Point 1", "text": "First", "mode": "build", "bg": {"kind": "image", "url": PIC},
         "lines": [say("a"), {"kind": "verse", "ref": "jn 3 16", "translation": "kjv"}]},
        {"kicker": "Point 2", "text": "Second", "mode": "build", "lines": []}])
    s = wsh.compile_item(wsh.clean_item(raw), {})["slides"]
    assert [x.get("point") for x in s] == [None, None, 1, 1, 1, 2]
    # A point's own background is behind every slide it makes, its verses too; the others take the item's.
    assert [x["bg"]["kind"] for x in s] == ["color", "color", "image", "image", "image", "color"]
    # Without a title of its own, sermon notes are named by their first line; text typed slide by slide is "Slides" as before.
    assert wsh.compile_item(wsh.clean_item(raw), {})["title"] == "Opening"
    assert wsh.compile_item(wsh.clean_item(item("text", slides=[{"text": "Welcome home"}])), {})["title"] == "Slides"


def _point(**kw):
    return {"kicker": "Point 1", "text": "One", "mode": "build", "lines": [say("a")], **kw}


@pytest.mark.parametrize("raw, words", [
    (item("text", slides=[_point(mode="slow")]), "builds up, shows one line each, or all at once"),
    (item("text", slides=[_point(lines="a, b")]), "at most 24 lines"),
    (item("text", slides=[_point(lines=[say(str(k)) for k in range(25)])]), "Point 1 has at most 24 lines"),
    (item("text", slides=[_point(lines=[{"kind": "song", "text": "x"}])]), "a statement or a passage"),
    (item("text", slides=[_point(lines=["just words"])]), "a statement or a passage"),
    (item("text", slides=[_point(lines=[say(" ")])]), "A line under Point 1 has no words"),
    (item("text", slides=[_point(lines=[say("x" * 401)])]), "at most 400"),
    (item("text", slides=[_point(lines=[say("x", note="n" * 501)])]), "at most 500"),
    (item("text", slides=[_point(lines=[{"kind": "verse", "ref": "hezekiah 4 1"}])]), "isn't a passage we can find"),
    (item("text", slides=[_point(lines=[{"kind": "verse", "ref": ""}])]), "isn't a passage we can find"),
    (item("text", slides=[_point(lines=[{"kind": "verse", "ref": "jn 3 16", "translation": "niv"}])]), "isn't here yet"),
    (item("text", outline=["1. One"], slides=[_point()]), "notes should be text"),
    (item("text", outline="x" * 20001, slides=[_point()]), "at most 20,000"),
    (item("text", slides=[_point(lines=[{"kind": "verse", "ref": "jn 3 16"}] * 21)]), "up to 20 passages"),
    (item("text", slides=[_point(lines=[{"kind": "verse", "ref": "psalm 119"}] * 3)]), "make 214 slides; at most 150"),
])
def test_what_sermon_notes_cannot_be(raw, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_item(raw)


# ─── fonts, the background library and a look for a sermon series (2026-11-14) ───
# Kevin: "background and font choices would be a huge help as well".

OLD_LOOK = {"background": {"kind": "image", "url": PIC, "dim": 0.4}, "size": "big", "caps": True, "align": "left",
            "font": "Playfair Display", "translation": "web", "lower_third": {"style": "shadow", "position": "top"},
            "crawls": ["Lunch is in the hall."]}


def test_an_old_look_and_old_backgrounds_come_back_exactly_as_they_were():
    look = wsh.clean_look(OLD_LOOK)
    # The same background, key for key (no design key), the old font kept, nothing new switched on.
    assert look["background"] == {"kind": "image", "color": None, "url": PIC, "dim": 0.4}
    assert (look["font"], look["fonts"], look["series"]) == ("Playfair Display", None, [])
    # Saved before the shadow switch (2026-11-15): on, as its songs always had it.
    assert look["shadow"] is True
    for kind, extra in (("brand", {}), ("color", {"color": "#1C0B1F"}), ("video", {"url": PIC})):
        assert "design" not in wsh.clean_look({"background": {"kind": kind, **extra}})["background"]
    for bg in ({"kind": "color", "color": "#203040"}, {"kind": "image", "url": PIC, "dim": 0.3}, {"kind": "video", "url": PIC}):
        assert set(wsh.clean_bg(bg)) == {"kind", "color", "url", "dim"}
    # A look without series is the same dict on any day: a church that sets none gets what it always did.
    assert wsh.look_on(look, None) is look
    assert wsh.look_on(look, date(2026, 11, 15)) is look


def test_the_fonts_are_one_of_eight_pairs():
    assert wsh.FONT_PAIRS == ("clean", "modern", "poster", "classic", "warm", "quiet", "strong", "gentle")
    for key in wsh.FONT_PAIRS:
        assert wsh.clean_look({"fonts": key})["fonts"] == key
    assert wsh.clean_look({"fonts": ""})["fonts"] is None and wsh.clean_look({})["fonts"] is None
    # The brand's typeface (a look's old `font`) still rides along under a pair.
    both = wsh.clean_look({"fonts": "warm", "font": "Archivo"})
    assert (both["fonts"], both["font"]) == ("warm", "Archivo")
    for bad in ("Comic Sans", "WARM", 3, ["warm"]):
        with pytest.raises(ValueError, match="aren't one of the font pairs"):
            wsh.clean_look({"fonts": bad})


def test_a_design_behind_the_words_of_the_churchs_look():
    assert wsh.BG_DESIGNS == ("glass", "linen", "stones", "night", "light", "haze", "drift", "water", "duo")
    assert set(wsh.BG_DESIGNS) <= set(wsh.DESIGNS)
    for key in wsh.BG_DESIGNS:
        bg = wsh.clean_look({"background": {"kind": "design", "design": key}})["background"]
        assert bg == {"kind": "design", "color": None, "url": None, "dim": 0.55, "design": key}
    # A design picked before, then the brand again, stays in hand like a color does.
    back = wsh.clean_look({"background": {"kind": "brand", "design": "linen", "color": "#203040"}})["background"]
    assert back == {"kind": "brand", "color": "#203040", "url": None, "dim": 0.55, "design": "linen"}
    for bad, words in [({"kind": "design"}, "Pick the background design"),
                       ({"kind": "design", "design": "numbers"}, "isn't one of the backgrounds"),
                       ({"kind": "design", "design": "ring"}, "isn't one of the backgrounds"),
                       ({"kind": "brand", "design": "confetti"}, "isn't one of the backgrounds"),
                       ({"kind": "pattern"}, "your brand, a design, a color")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_look({"background": bad})


def test_a_song_or_a_sermon_point_can_wear_a_design():
    song = wsh.clean_item(item("song", song_id=SONG_ID, bg={"kind": "design", "design": "water", "color": "#000000", "url": PIC}))
    assert song["bg"] == {"kind": "design", "color": None, "url": None, "dim": 0.55, "design": "water"}
    assert all(s["bg"]["design"] == "water" for s in wsh.compile_item(song, {SONG_ID: SONG})["slides"])
    points = wsh.clean_item(item("text", bg={"kind": "design", "design": "glass"}, slides=[
        {"kicker": "Point 1", "text": "Stop and pick up stones."},
        {"kicker": "Point 2", "text": "Stones are for questions.", "bg": {"kind": "design", "design": "linen"}}]))
    slides = wsh.compile_item(points, {})["slides"]
    assert [s["bg"]["design"] for s in slides] == ["glass", "linen"]
    for bad in ({"kind": "design"}, {"kind": "design", "design": "numbers"}, {"kind": "design", "design": "ring"}):
        with pytest.raises(ValueError, match="pick one of the designs"):
            wsh.clean_item(item("song", song_id=SONG_ID, bg=bad))


def series(**kw):
    return {"id": "crossing", "name": "Crossing Over", "from": "2026-11-01", "to": "2026-11-29", "fonts": "warm",
            "background": {"kind": "design", "design": "glass"}, **kw}


def test_a_sermon_series_wears_its_own_look_on_its_days():
    advent = series(id="advent", name="Advent", fonts=None, background={"kind": "color", "color": "#0F5132"})
    advent.update({"from": "2026-11-30", "to": "2026-12-24"})
    look = wsh.clean_look({**OLD_LOOK, "fonts": "clean", "series": [series(), advent]})
    assert look["series"][0] == {"id": "crossing", "name": "Crossing Over", "from": "2026-11-01", "to": "2026-11-29", "fonts": "warm",
                                 "background": {"kind": "design", "color": None, "url": None, "dim": 0.55, "design": "glass"}}
    # Its first and last days count; the rest of the year keeps the church's look.
    for day in (date(2026, 11, 1), date(2026, 11, 15), date(2026, 11, 29)):
        worn = wsh.look_on(look, day)
        assert (worn["fonts"], worn["background"]["design"]) == ("warm", "glass")
        assert worn["wearing"] == {"id": "crossing", "name": "Crossing Over", "from": "2026-11-01", "to": "2026-11-29"}
        # Only the fonts and the background change: the rest is the church's, the series list too.
        assert {k: v for k, v in worn.items() if k not in ("fonts", "background", "wearing")} == \
            {k: v for k, v in look.items() if k not in ("fonts", "background")}
    on = wsh.look_on(look, date(2026, 12, 6))
    assert on["fonts"] is None and on["background"]["color"] == "#0F5132" and on["wearing"]["name"] == "Advent"
    for day in (date(2026, 10, 31), date(2026, 12, 25)):
        assert wsh.look_on(look, day) is look and "wearing" not in look
    # What a page sends back never sticks as the church's: clean_look drops `wearing`.
    assert "wearing" not in wsh.clean_look(wsh.look_on(look, date(2026, 11, 8)))


def _dated(start, end, **kw):
    s = series(**kw)
    s.update({"from": start, "to": end})
    return s


@pytest.mark.parametrize("raw, words", [
    ("crossing", "up to 12 series looks"),
    ([_dated(f"2026-{k + 1:02d}-01", f"2026-{k + 1:02d}-10", id=f"s{k}") for k in range(12)] + [series(id="x")], "up to 12 series looks"),
    (["Crossing Over"], "isn't a look for a series"),
    ([series(id="Not ok")], "its own id"),
    ([series(), _dated("2027-01-01", "2027-01-31")], "its own id"),
    ([series(name="  ")], "Give the series a name"),
    ([series(name="x" * 61)], "at most 60"),
    ([_dated("Nov 1", "2026-11-29")], "Crossing Over's first day is a date"),
    ([_dated("2026-11-01", "2026-11-31")], "Crossing Over's last day is a date"),
    ([_dated("2026-11-29", "2026-11-01")], "last day comes before its first"),
    ([_dated("2026-11-01", "2027-12-01")], "a year at most"),
    ([series(), _dated("2026-11-29", "2026-12-24", id="advent", name="Advent")], "Advent and Crossing Over share some days"),
    ([series(fonts="comic")], "Crossing Over: the fonts aren't one of the font pairs"),
    ([series(background={"kind": "design", "design": "ring"})], "Crossing Over: that isn't one of the backgrounds"),
    ([series(background={"kind": "image"})], "Crossing Over: pick the background photo"),
])
def test_what_a_series_look_cannot_be(raw, words):
    with pytest.raises(ValueError, match=words):
        wsh.clean_look({"series": raw})


# ─── the soft shadow behind the words (2026-11-15) ───────────────────
# Kevin: "yes add the shadow switch too" (the mock's "A soft shadow behind the words").

def test_the_shadow_behind_the_words_is_on_unless_the_church_turns_it_off():
    assert wsh.DEFAULT_LOOK["shadow"] is True
    assert wsh.clean_look({})["shadow"] is True and wsh.clean_look({"shadow": None})["shadow"] is True
    assert wsh.clean_look({"shadow": False})["shadow"] is False
    assert wsh.clean_look({"shadow": True})["shadow"] is True
    for bad in ("off", 0, 1, "", [], {}):
        with pytest.raises(ValueError, match="shadow behind the words is on or off"):
            wsh.clean_look({"shadow": bad})
    # A series changes the fonts and the background only: the church's shadow rides along.
    crossing = {"id": "crossing", "name": "Crossing Over", "from": "2026-11-01", "to": "2026-11-29", "fonts": "warm",
                "background": {"kind": "design", "design": "linen"}}
    look = wsh.clean_look({"shadow": False, "series": [crossing]})
    assert wsh.look_on(look, date(2026, 11, 15))["shadow"] is False
