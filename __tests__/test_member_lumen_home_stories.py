# __tests__/test_member_lumen_home_stories.py
#
# Kevin's Home plan (2026-11-21, "yes to everything"), part one: stories
# that show up. At a church like Love City (one service, no posts, no
# devotional running) the row needed two moments and found one. Two more
# sources join, from what the church's records already hold:
#   - the church's newest message while it's new (preached in the last
#     week: member_feed_more.message_of), after Sunday, opening the message,
#     with Watch (Listen for audio alone) and Share (contract 1: its public
#     page); never twice when Sunday's moment already is that message, never
#     a sample, never an older one;
#   - the class the member is in and hasn't finished, after the groups, with
#     Continue to their classes and no Share (a class has no public page).
#     Read once (academy_member_classes), only at a church that has a class
#     anyone can see, kept two minutes (member_portal_lumen.my_class); a
#     failed read leaves the moment out and isn't kept.
# The order: the pastor, Sunday, the message, the groups, the class, events.

import pathlib
import re
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_portal_lumen as mlp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import TODAY, _client, _group, church  # noqa: F401
from test_member_lumen_home5 import _devotional, _moments

MSG = "00000000-0000-4000-8000-000000000621"
OLD = "00000000-0000-4000-8000-000000000622"
SER = "00000000-0000-4000-8000-000000000521"


def _library(monkeypatch, days_ago=6, **extra):
    import member_portal_sermons as mps
    newest = {"id": MSG, "title": "Sunday, November 15 (Part 1)", "series_id": SER, "speaker": "Pastor KMJ",
              "preached_on": (TODAY - timedelta(days=days_ago)).isoformat(),
              "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", **extra}
    older = {"id": OLD, "title": "Sunday, November 8", "series_id": SER, "speaker": "Pastor KMJ",
             "preached_on": (TODAY - timedelta(days=days_ago + 7)).isoformat()}
    lib = {"series": [{"id": SER, "title": "To The Future Series", "description": ""}], "sermons": [newest, older]}
    monkeypatch.setattr(mps, "load_library", lambda b: lib)
    return lib


@pytest.fixture
def klass(monkeypatch):
    """Ana in The Making: Foundation, lesson 1 of 4; the church has classes.
    Each test starts with nothing kept."""
    import member_portal_classes as mcl
    calls = []
    state = {"mine": [{"course_id": "c-making", "title": "The Making: Foundation", "program": "The Making",
                       "status": "active", "total": 4, "done": 0, "token": "tok",
                       "next": {"lesson": "Lesson 1: Who You Are"}}], "fail": False}

    def member_classes(b, me):
        calls.append(b)
        if state["fail"]:
            return None
        return {"mine": [dict(c) for c in state["mine"]], "programs": [], "open": []}
    monkeypatch.setattr(mcl, "member_classes", member_classes)
    monkeypatch.setattr(mcl, "classes_on", lambda b: True)
    monkeypatch.setattr(mlp, "_CLASS", None)
    state["calls"] = calls
    return state


def test_the_newest_message_joins_after_sunday(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(mlp, "_CLASS", None)
    _library(monkeypatch)
    html = _client(fake, monkeypatch).get("/my").text
    ids, slides = _moments(html)
    sun = church["occ"][0]["date"]
    assert ids == [f"sv:{sun}", f"ms:{MSG}"]           # Love City's shape: two moments, so the row draws
    ms = slides[f"ms:{MSG}"]
    assert "Sunday, November 15 (Part 1)" in ms and "Pastor KMJ · To The Future Series" in ms
    assert f'<a class="lm-mvb" href="/my/sermons/{MSG}">Watch</a>' in ms
    assert "New message · " in ms
    # Share hands over its public page (contract 1, member_lumen_share).
    assert f'href="/sermons/{MSG}" data-share-kind="moment"' in ms and f'data-share-id="message:{MSG}"' in ms
    assert re.search(r'data-mo="ms:[^"]+"[^>]*>.*?<b>Last week</b>', html, re.S)   # under the circle
    assert f'href="/my/sermons/{MSG}" data-mo="ms:{MSG}"' in html              # without script: its page


def test_a_message_with_only_audio_listens(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(mlp, "_CLASS", None)
    _library(monkeypatch, days_ago=1, video_url="", audio_url="https://example.org/a.mp3")
    ids, slides = _moments(_client(fake, monkeypatch).get("/my").text)
    ms = slides[f"ms:{MSG}"]
    assert f'href="/my/sermons/{MSG}?listen=1">Listen</a>' in ms and "Yesterday" in ms


def test_an_old_or_sample_message_is_no_moment(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(mlp, "_CLASS", None)
    _library(monkeypatch, days_ago=8)
    ids, _ = _moments(_client(fake, monkeypatch).get("/my").text)
    assert ids == []                                     # only Sunday: no row
    _library(monkeypatch, days_ago=2, sample=True)
    ids, _ = _moments(_client(fake, monkeypatch).get("/my").text)
    assert ids == []


def test_sundays_own_message_is_not_shown_twice(church, fake, monkeypatch):  # noqa: F811
    from datetime import datetime, time
    from test_member_lumen_home import NY
    monkeypatch.setattr(mlp, "_CLASS", None)
    sun = TODAY + timedelta(days=(6 - TODAY.weekday()) % 7)
    church["now"] = datetime.combine(sun, time(9, 0), tzinfo=NY)
    church["occ"][0]["date"] = sun.isoformat()
    church["checkin"]["w"].update(day=sun, start=datetime.combine(sun, time(10, 30), tzinfo=NY))
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"series": [], "sermons": [
        {"id": MSG, "title": "Hope Has a Name", "preached_on": sun.isoformat()}]})
    _devotional(monkeypatch)                           # a second moment, so the row draws
    ids, slides = _moments(_client(fake, monkeypatch).get("/my").text)
    assert f"sv:{sun.isoformat()}" in ids and f"ms:{MSG}" not in ids          # Sunday's moment carries it
    assert "Hope Has a Name" in slides[f"sv:{sun.isoformat()}"]


def test_the_class_joins_after_the_groups(church, fake, monkeypatch, klass):  # noqa: F811
    _group(fake)
    _library(monkeypatch)
    html = _client(fake, monkeypatch).get("/my").text
    ids, slides = _moments(html)
    sun = church["occ"][0]["date"]
    assert ids == [f"sv:{sun}", f"ms:{MSG}", f"gr:{tct.GROUP}:{TODAY.isoformat()}", "cl:c-making:0"]
    cl = slides["cl:c-making:0"]
    assert "Your class · Lesson 1 of 4" in cl and "The Making: Foundation" in cl and "Lesson 1: Who You Are" in cl
    assert '<a class="lm-mvb" href="/my/classes">Continue</a>' in cl
    assert "lm-share" not in cl                          # a class has no public page
    assert re.search(r'data-mo="cl:c-making:0"[^>]*>.*?<b>The Making</b>', html, re.S)


def test_the_class_is_read_once_and_kept(church, fake, monkeypatch, klass):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.get("/my")
    c.get("/my")
    assert len(klass["calls"]) == 1                      # kept two minutes (member_cache)
    # A finished class, or one with every lesson done, is no moment.
    klass["mine"][0].update(status="completed")
    monkeypatch.setattr(mlp, "_CLASS", None)
    assert mlp.my_class(fake.business(), {"id": tct.ANA}) == {}
    klass["mine"][0].update(status="active", done=4)
    monkeypatch.setattr(mlp, "_CLASS", None)
    assert mlp.my_class(fake.business(), {"id": tct.ANA}) == {}


def test_a_failed_class_read_leaves_it_out_and_isnt_kept(church, fake, monkeypatch, klass):  # noqa: F811
    _group(fake)
    klass["fail"] = True
    c = _client(fake, monkeypatch)
    ids, _ = _moments(c.get("/my").text)
    assert not any(i.startswith("cl:") for i in ids)
    klass["fail"] = False
    ids, _ = _moments(c.get("/my").text)
    assert "cl:c-making:0" in ids and len(klass["calls"]) == 2


def test_no_class_read_at_a_church_without_classes(church, fake, monkeypatch, klass):  # noqa: F811
    import member_portal_classes as mcl
    monkeypatch.setattr(mcl, "classes_on", lambda b: False)
    _client(fake, monkeypatch).get("/my")
    assert klass["calls"] == []


def test_todays_look_reads_no_class(church, fake, monkeypatch, klass):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _library(monkeypatch)
    html = _client(fake, monkeypatch).get("/my").text
    assert klass["calls"] == [] and 'id="lm-mos"' not in html
