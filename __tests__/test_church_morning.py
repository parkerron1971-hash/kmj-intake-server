"""Who sees what on the phone (church_morning.py + push_notifications, Kevin
2026-10-26): a business push reaches the people who still open the business,
and on a church with Church Areas on, an office login that works only some
areas hears its own week instead of the church-wide brief.

Pins:
  * a removed login's phone hears no business push (nothing clears its
    subscription when the seat goes); the owner and active seats still do
  * on a church with the switch on, a login that works some areas is left
    out of business pushes; the owner, admins and a login that sees the whole
    church hear them; with the switch not on, everyone hears them as before
  * each limited login gets one morning line of its own, the first thing in
    its week and how many more, on its devices on this church, opening on
    My week; nobody else gets one, and a morning with nothing is quiet
  * a failed read sends as before; a week that can't be read sends no note
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

import church_areas as ca  # noqa: E402
import church_morning as cm  # noqa: E402
import church_my_week as mw  # noqa: E402
import push_notifications as push  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import BIZ, MARCUS, NAMES, OWNER  # noqa: E402
from test_church_areas import db  # noqa: E402,F401
from test_church_my_week import MARCUS_SEAT, week  # noqa: E402,F401

GONE = "99999999-0000-0000-0000-000000000009"


def _sub(user, n=1, biz=BIZ):
    return {"business_id": biz, "user_id": user, "endpoint": f"https://push.example/{user}/{n}",
            "subscription": {"endpoint": f"https://push.example/{user}/{n}"}}


@pytest.fixture
def phones(week, monkeypatch):
    week.t["push_subscriptions"] = [_sub(OWNER), _sub("u-admin"), _sub("u-view"), _sub(MARCUS_SEAT),
                                    _sub(MARCUS_SEAT, 2, biz="another-business"), _sub(GONE)]
    sent = []
    monkeypatch.setattr(push, "push_enabled", lambda: True)
    monkeypatch.setattr(push, "_send_one", lambda row, payload, table="push_subscriptions":
                        sent.append((row["user_id"], row["endpoint"], payload)) or True)
    monkeypatch.setenv("CHURCH_AREAS", "on")
    ca._MY_CACHE.clear()
    week.sent = sent
    return week


def _who(sent):
    return sorted({u for u, _, _ in sent})


def test_a_removed_login_hears_no_business_push(phones, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert push.send_to_business(BIZ, title="Chief", body="A new booking") == 4
    assert GONE not in _who(phones.sent)
    assert _who(phones.sent) == sorted([OWNER, "u-admin", "u-view", MARCUS_SEAT])


def test_a_login_that_works_some_areas_is_left_out_of_business_pushes(phones):
    push.send_to_business(BIZ, title="Good morning ✦ Chief here", body="2 new leads · 1 overdue invoice.")
    assert _who(phones.sent) == sorted([OWNER, "u-admin", "u-view"]), \
        "Marcus works Kids & youth; the intern sees the whole church, as before"


def test_with_the_switch_not_on_everyone_hears_them_as_before(phones, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    push.send_to_business(BIZ, title="Chief", body="hello")
    assert MARCUS_SEAT in _who(phones.sent)


def test_a_failed_read_sends_as_before(phones, monkeypatch):
    real = phones.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_users") else real(path, **kw))
    assert push.send_to_business(BIZ, title="Chief", body="hello") == 5


def test_each_limited_login_hears_its_own_week_on_this_church_only(phones):
    n = cm.notes(phones.t["businesses"][0], today="2026-11-05")
    assert n == 1
    (uid, endpoint, payload), = phones.sent
    assert uid == MARCUS_SEAT and endpoint.endswith("/1"), "only the device signed up from this church"
    assert payload["nav"] == "operate:my-week" and payload["tag"] == "morning-2026-11-05"
    assert "background check" in payload["body"]
    assert payload["title"] == f"Good morning, {NAMES[MARCUS].split()[0]} ✦ Chief here", "their own name"


def test_a_login_whose_email_names_no_one_is_greeted_without_a_name(phones):
    seat = phones.t["business_users"][-1]
    seat.update(invited_email="kids-desk@lovecity.org", areas=["kids_youth"])
    cm.notes(phones.t["businesses"][0], today="2026-11-05")
    assert [p["title"] for _, _, p in phones.sent] == [cm.TITLE]


def test_a_week_that_cant_be_read_sends_no_note(phones, monkeypatch):
    def boom(*a, **k):
        raise mw.HTTPException(503, "no")
    monkeypatch.setattr(mw, "build", boom)
    assert cm.notes(phones.t["businesses"][0], today="2026-11-05") == 0
    assert phones.sent == []


def test_not_a_church_or_the_switch_off_sends_no_notes(phones, monkeypatch):
    phones.t["businesses"][0]["type"] = "salon"
    assert cm.notes(phones.t["businesses"][0], today="2026-11-05") == 0
    phones.t["businesses"][0]["type"] = "ministry"
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    assert cm.notes(phones.t["businesses"][0], today="2026-11-05") == 0
    assert phones.sent == []


@pytest.mark.parametrize("week_,said", [
    ({"next": None, "counts": {"needs": 0}}, None),
    ({"next": {"title": "Robert Hayes was handed to you."}, "counts": {"needs": 1}}, "Robert Hayes was handed to you."),
    ({"next": {"title": "A kids room has no background check"}, "counts": {"needs": 2}},
     "A kids room has no background check. 1 more needs you this week."),
    ({"next": {"title": "Robert Hayes is waiting to hear from you."}, "counts": {"needs": 4}},
     "Robert Hayes is waiting to hear from you. 3 more need you this week."),
    ({"next": {"kind": "task", "title": "Order the VBS shirts"}, "counts": {"needs": 1}},
     "Your task: Order the VBS shirts."),
])
def test_the_line_is_the_weeks_first_thing_and_how_many_more(week_, said):
    assert cm.line(week_) == said


def test_the_morning_tick_sends_the_notes_and_leaves_limited_phones_out(phones, monkeypatch):
    import asyncio
    phones.t["contacts"].append({"id": "c-new", "business_id": BIZ, "name": "New Lead", "status": "lead",
                                 "created_at": "2099-01-01T00:00:00Z", "email": "lead@example.com"})
    asyncio.run(push.morning_brief_tick())
    to_marcus = [p for u, _, p in phones.sent if u == MARCUS_SEAT]
    assert len(to_marcus) == 1 and to_marcus[0]["nav"] == "operate:my-week"
    church_wide = [u for u, _, p in phones.sent if p["nav"] == "home"]
    assert sorted(church_wide) == sorted([OWNER, "u-admin", "u-view"])
