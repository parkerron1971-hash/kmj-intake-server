"""My week's weekly text job says who gets the church's texts
(church_my_week.texts_fact).

Kevin, 2026-11-17, approving it for the Office & Leadership admin: "check
how many people have signed up for texts each week".

Pins:
  * the weekly text's job carries `fact`: "N people get the church's texts
    (+k this week)", the week from Monday on the church's clock; no one new
    is said as such
  * while the church's own texting registration isn't sent, `fact_note`
    says how people join until then and where it's sent from; once it's
    sent, or when the registration can't be read, no note
  * only the weekly text's job, and only for a login that holds it
  * a count that can't be read says nothing, never a wrong number; the week
    stands
  * kept a while a church: a second look reads nothing again
  * MY_WEEK_TEXT_COUNT=off leaves it out
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_my_week as mw  # noqa: E402
import sms_routing  # noqa: E402
import texting_registration as tr  # noqa: E402
from test_church_follow_up import BIZ  # noqa: E402
from test_church_areas import db  # noqa: E402,F401
from test_church_my_week import client, week  # noqa: E402,F401
from test_church_week_rhythm import _as_manager, _item, _keys, _rhythm, fresh  # noqa: E402,F401


@pytest.fixture
def count(monkeypatch):
    """The count faked, the registration not sent, the switch on, the kept
    counts empty."""
    world = {"said_yes": 37, "new": 2, "fail": False, "calls": [], "registration": None, "reg_fail": False}

    async def said_yes_count(business_id, since=None):
        world["calls"].append((business_id, since))
        if world["fail"]:
            return None
        return {"said_yes": world["said_yes"], "new": world["new"] if since else None}

    def registration(business_id):
        if world["reg_fail"]:
            raise RuntimeError("read failed")
        return world["registration"]

    monkeypatch.setenv("MY_WEEK_TEXT_COUNT", "on")
    monkeypatch.setattr(sms_routing, "said_yes_count", said_yes_count)
    monkeypatch.setattr(tr, "registration", registration)
    mw._texts.clear()
    yield world
    mw._texts.clear()


def test_the_weekly_text_says_who_gets_the_churchs_texts(client, count):
    item = _item(_rhythm(client), "weekly_text")
    assert item["fact"] == "37 people get the church's texts (+2 this week)"
    # The week is Monday on the church's clock (Chicago), midnight.
    assert count["calls"] == [(BIZ, "2026-11-02T06:00:00+00:00")]
    assert item["fact_note"] == mw.TEXTS_NOTE
    assert "texting registration" in item["fact_note"] and "Your name on texts" in item["fact_note"]
    # Only the weekly text's job carries it.
    others = [i for d in _rhythm(client)["days"] for i in d["items"] if i["key"] != "weekly_text"]
    assert not any("fact" in i or "fact_note" in i for i in others)


def test_no_one_new_and_one_person_are_said_plainly(client, count):
    count.update(said_yes=1, new=0)
    assert _item(_rhythm(client), "weekly_text")["fact"] == "1 person gets the church's texts (no one new this week)"
    mw._texts.clear()
    count.update(said_yes=1240, new=31)
    assert _item(_rhythm(client), "weekly_text")["fact"] == "1,240 people get the church's texts (+31 this week)"


def test_once_the_registration_is_sent_there_is_no_note(client, count):
    count["registration"] = {"status": "brand_pending", "twilio": {}}
    item = _item(_rhythm(client), "weekly_text")
    assert item["fact"].startswith("37 people") and "fact_note" not in item
    mw._texts.clear()
    count.update(registration=None, reg_fail=True)       # can't be read: no claim either way
    assert "fact_note" not in _item(_rhythm(client), "weekly_text")


def test_a_count_that_cant_be_read_says_nothing_and_the_week_stands(client, count):
    count["fail"] = True
    item = _item(_rhythm(client), "weekly_text")
    assert "fact" not in item and "fact_note" not in item
    assert item["label"]


def test_a_manager_without_the_weekly_text_reads_nothing_for_it(client, week, count):
    _as_manager(client, week, lane="media_comms")
    r = _rhythm(client)
    assert "weekly_text" not in _keys(r) and count["calls"] == []


def test_the_office_lane_sees_it(client, week, count):
    _as_manager(client, week, lane="office_leadership")
    assert _item(_rhythm(client), "weekly_text")["fact"].startswith("37 people")


def test_it_is_kept_a_while_a_church(client, count):
    _rhythm(client)
    _rhythm(client)
    assert len(count["calls"]) == 1
    # A failed read is kept only a minute.
    mw._texts.clear()
    count["fail"] = True
    _rhythm(client)
    key = next(iter(mw._texts))
    assert mw._texts[key][1] is None


def test_a_slow_count_comes_on_the_next_look(client, count, monkeypatch):
    import threading
    gate = threading.Event()

    async def slow(business_id, since=None):
        gate.wait(5)
        return {"said_yes": 5, "new": 1}
    monkeypatch.setattr(sms_routing, "said_yes_count", slow)
    monkeypatch.setattr(mw, "TEXTS_WAIT", 0.05)
    assert "fact" not in _item(_rhythm(client), "weekly_text")
    gate.set()
    for t in list(mw._texts_reading.values()):
        t.join(5)
    assert _item(_rhythm(client), "weekly_text")["fact"] == "5 people get the church's texts (+1 this week)"


def test_the_switch(client, count, monkeypatch):
    monkeypatch.setenv("MY_WEEK_TEXT_COUNT", "off")
    assert "fact" not in _item(_rhythm(client), "weekly_text") and count["calls"] == []


def test_the_note_is_true_to_the_rule():
    # Before its own registration, the yes that counts is a consent (the
    # member app's among them) or a keyword texted (sms_alerts); the sign-up
    # page (/texts) opens only once the registration is sent.
    import inspect
    import sms_alerts
    src = inspect.getsource(sms_alerts.said_yes_to_texts)
    assert "sms_bindings" in src and "sms_consents" in src
    assert "keyword" in mw.TEXTS_NOTE and "member app" in mw.TEXTS_NOTE
    assert "source.neq.booking_marketing" in src and "is_sent(row)" in inspect.getsource(tr.overview)
