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
