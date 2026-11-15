# __tests__/test_worship_countdown.py
#
# The countdown you can grab and the crawl (ChurchSavvy round 5, canvas
# boards 22-25; worship_show.py). Pins:
#   * a countdown item's look (big numbers, over a picture, a ring, just the
#     numbers), what happens at zero, the countdown video's length, the call
#     to the stage, and that they ride on the countdown's slide
#   * the live countdown the booth grabbed: the time it counts to, or the
#     seconds it's held at
#   * the crawl: its words, where it goes, how many times
#   * a church's saved crawl lines in its look
#   * older countdowns, live states and looks still pass

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import worship_show as wsh

STARTS = "2026-11-01T16:05:00Z"


def count(**kw):
    return wsh.clean_item({"id": "count", "kind": "countdown", **kw})


def test_a_countdown_has_a_look_and_a_plan_for_zero():
    plain = count()
    assert (plain["look"], plain["zero"], plain["band_at"], plain["band_text"]) == ("big", "next", 120, "Band to the stage")
    assert plain["video_url"] == "" and plain["video_seconds"] is None
    pic = count(look="picture", picture_url="https://x.example/stage.jpg", welcome="Welcome to Love City Church",
                zero="up", band_at=180, band_text="Worship team, come on up")
    assert (pic["look"], pic["zero"], pic["band_at"], pic["welcome"]) == ("picture", "up", 180, "Welcome to Love City Church")
    # A cleared field takes the default; a whole number sent as 180.0 is 180 (PR review).
    assert count(band_at=None)["band_at"] == 120 and count(band_at=180.0)["band_at"] == 180
    vid = count(video_url="https://x.example/gather.mp4", video_seconds=300)
    assert vid["video_seconds"] == 300.0
    for bad, words in [({"look": "flip"}, "big numbers"), ({"zero": "fireworks"}, "At zero"),
                       ({"look": "picture"}, "Pick the picture"),
                       ({"video_url": "https://x.example/v.mp4"}, "its length"),
                       ({"video_url": "https://x.example/v.mp4", "video_seconds": 0}, "its length"),
                       ({"band_at": 1000}, "0 to 15 minutes"), ({"band_at": True}, "0 to 15 minutes"),
                       ({"picture_url": "http://x.example/a.jpg", "look": "picture"}, "https")]:
        with pytest.raises(ValueError, match=words):
            count(**bad)


def test_the_slide_carries_the_look():
    shown = wsh.compile_item(count(look="ring", welcome="Welcome home", zero="logo",
                                   video_url="https://x.example/gather.mp4", video_seconds=300), {}, STARTS)
    slide = shown["slides"][0]
    assert slide["to"] == STARTS and slide["look"] == "ring" and slide["zero"] == "logo"
    assert slide["welcome"] == "Welcome home" and slide["video_seconds"] == 300.0 and slide["band_at"] == 120
    # An older countdown row (before round 5) compiles with the defaults filled in by clean_item;
    # a raw one straight from the database still draws: nothing new is required.
    old = wsh.compile_item({"id": "count", "kind": "countdown", "show": "all", "title": "We start soon", "to": None}, {}, STARTS)
    assert old["slides"][0] == {"kind": "countdown", "to": STARTS, "title": "We start soon"}


def test_the_booth_grabs_the_countdown():
    live = wsh.clean_live({"item_id": "count", "count": {"to": "2026-11-01T16:07:00Z", "held": None}})
    assert live["count"] == {"to": "2026-11-01T16:07:00Z", "held": None}
    held = wsh.clean_live({"item_id": "count", "count": {"to": None, "held": 251}})
    assert held["count"] == {"to": None, "held": 251.0}
    assert "count" not in wsh.clean_live({"item_id": "count"})
    # Exactly one of the two (PR review): neither, or both, can't be drawn.
    for bad in ({"to": "soon"}, {"held": -5}, {"held": "251"}, "4:59", {"to": None, "held": None},
                {"to": "2026-11-01T16:07:00Z", "held": 30}):
        with pytest.raises(ValueError):
            wsh.clean_live({"item_id": "count", "count": bad})


def test_the_crawl():
    live = wsh.clean_live({"crawl": {"text": "  The overflow lot   is open on 5th Street. ", "room": True, "online": True,
                                     "times": 3, "at": "2026-11-01T16:12:00Z"}})
    assert live["crawl"] == {"text": "The overflow lot is open on 5th Street.", "room": True, "online": True, "times": 3,
                             "at": "2026-11-01T16:12:00Z"}
    for bad, words in [({"text": ""}, "1 to 160"), ({"text": "x" * 161}, "1 to 160"),
                       ({"text": "Hi", "times": 2, "at": "2026-11-01T16:12:00Z"}, "three times"),
                       ({"text": "Hi", "times": True, "at": "2026-11-01T16:12:00Z"}, "three times"),
                       ({"text": "Hi", "times": 3.0, "at": "2026-11-01T16:12:00Z"}, "three times"),
                       ({"text": "Hi", "room": False, "online": False, "at": "2026-11-01T16:12:00Z"}, "room, online"),
                       ({"text": "Hi", "at": "noon"}, "isn't a time")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_live({"crawl": {"room": True, "times": 1, "at": "2026-11-01T16:12:00Z", **bad}})


def test_saved_crawl_lines_in_the_look():
    look = wsh.clean_look({"crawls": ["  Lunch is in the   Fellowship Hall. ", "Watching online? Tap Give."]})
    assert look["crawls"] == ["Lunch is in the Fellowship Hall.", "Watching online? Tap Give."]
    assert wsh.clean_look({})["crawls"] == []
    with pytest.raises(ValueError, match="up to 10"):
        wsh.clean_look({"crawls": ["x"] * 11})
    with pytest.raises(ValueError, match="1 to 160"):
        wsh.clean_look({"crawls": [""]})


# ─── 2026-11-14: designs, the last ten seconds, on the spot, and its own times ───


def test_a_countdown_wears_a_design_in_the_churchs_colors():
    for key in wsh.DESIGNS:
        assert count(design=key)["design"] == key
    assert count()["design"] is None and count(design="")["design"] is None
    # A design draws its own background: a picture behind it isn't needed, and the look is big numbers.
    glass = count(design="glass", look="picture")
    assert glass["look"] == "big" and glass["design"] == "glass"
    assert count(design="ring", look="plain")["look"] == "plain"
    with pytest.raises(ValueError, match="isn't one of the designs"):
        count(design="confetti")
    # Big numbers for the last ten seconds: on only when it's said so.
    assert count(big_last=True)["big_last"] is True
    assert count()["big_last"] is False and count(big_last="yes")["big_last"] is False
    slide = wsh.compile_item(count(design="drift", big_last=True), {}, STARTS)["slides"][0]
    assert slide["design"] == "drift" and slide["big_last"] is True
    # A saved countdown from before keeps drawing as it did: no design, no big last seconds.
    before = wsh.compile_item(count(look="ring"), {}, STARTS)["slides"][0]
    assert "design" not in before and "big_last" not in before and before["look"] == "ring"


def test_a_countdown_goes_up_on_the_spot():
    spot = {"kind": "countdown", "title": "Back in five", "show": "room",
            "slides": [{"kind": "countdown", "to": "2026-11-01T16:10:00Z", "title": "Back in five", "design": "night",
                        "big_last": True, "zero": "logo"}]}
    live = wsh.clean_live({"adhoc": spot, "auto": {"id": "sun", "at": "10:15"}})
    up = live["adhoc"]
    assert up["kind"] == "countdown" and up["show"] == "room" and len(up["slides"]) == 1
    slide = up["slides"][0]
    assert (slide["to"], slide["title"], slide["design"], slide["big_last"], slide["zero"], slide["look"]) == (
        "2026-11-01T16:10:00Z", "Back in five", "night", True, "logo", "big")
    # Started by itself: the booth's line rides along with the countdown, and only with it.
    assert live["auto"] == {"id": "sun", "at": "10:15"}
    words = {"kind": "text", "title": "Hi", "slides": [{"kind": "text", "kicker": "", "text": "Hi"}]}
    assert "auto" not in wsh.clean_live({"adhoc": words, "auto": {"id": "sun", "at": "10:15"}})
    # Something on the spot from before says nothing of who sees it: everyone, as before.
    assert wsh.clean_live({"adhoc": words})["adhoc"]["show"] == "all"
    for bad, msg in [({"slides": []}, "1 to 60"),
                     ({"slides": [spot["slides"][0], spot["slides"][0]]}, "one slide"),
                     ({"slides": [{"kind": "countdown", "to": "soon"}]}, "a time to count to"),
                     # A time with no zone can't mean the same moment on every screen.
                     ({"slides": [{"kind": "countdown", "to": "2026-11-01T16:10:00"}]}, "a time to count to"),
                     ({"slides": [{"kind": "countdown", "to": "2026-11-01T16:10:00Z", "design": "x"}]}, "designs"),
                     ({"show": "lobby"}, "the room only"),
                     ({"slides": [{"kind": "text", "text": "x"}]}, "don't match")]:
        with pytest.raises(ValueError, match=msg):
            wsh.clean_live({"adhoc": {**spot, **bad}})
    for bad in ({"id": "sun"}, {"id": "Sun!", "at": "10:15"}, {"id": "sun", "at": "25:00"}, "10:15"):
        with pytest.raises(ValueError, match="started by itself"):
            wsh.clean_live({"adhoc": spot, "auto": bad})


def sunday(**kw):
    return {"id": "sun", "days": [0], "at": "10:15", "minutes": 15, "where": "all", **kw}


def test_the_churchs_own_countdown_and_its_times():
    plain = wsh.clean_look({})["countdown"]
    assert plain == {"design": "glass", "title": "We start soon", "welcome": "", "big_last": True, "times": []}
    cd = wsh.clean_look({"countdown": {"design": None, "title": "Service starts in", "big_last": False, "times": [
        sunday(), {"id": "wed", "days": [3, 3], "at": "18:45", "minutes": 15.0, "where": "room", "on": False}]}})["countdown"]
    assert cd["design"] is None and cd["title"] == "Service starts in" and cd["big_last"] is False
    assert cd["times"] == [{"id": "sun", "on": True, "days": [0], "at": "10:15", "minutes": 15, "where": "all"},
                           {"id": "wed", "on": False, "days": [3], "at": "18:45", "minutes": 15, "where": "room"}]
    for bad, msg in [([sunday()] * 7, "up to 6"), ([sunday(), sunday()], "its own id"),
                     ([sunday(), sunday(id="sun2", days=[0, 3])], "Two countdowns go up at 10:15"),
                     ([sunday(days=[])], "Pick the days"), ([sunday(days=[7])], "Pick the days"),
                     ([sunday(days=[True])], "Pick the days"), ([sunday(at="10:15 AM")], "time of day"),
                     ([sunday(minutes=0)], "1 to 120"), ([sunday(minutes=121)], "1 to 120"),
                     ([sunday(minutes=True)], "1 to 120"), ([sunday(minutes=2.5)], "1 to 120"),
                     ([sunday(where="lobby")], "every screen"), ([sunday(id="")], "its own id")]:
        with pytest.raises(ValueError, match=msg):
            wsh.clean_look({"countdown": {"times": bad}})
    with pytest.raises(ValueError, match="designs"):
        wsh.clean_look({"countdown": {"design": "fireworks"}})
    # The day each time last went up is the server's: a look read back never carries it.
    assert wsh.FIRED_KEY not in wsh.clean_look({wsh.FIRED_KEY: {"sun": "2026-11-15"}})
