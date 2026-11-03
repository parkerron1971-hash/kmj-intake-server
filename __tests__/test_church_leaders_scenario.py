"""The four needs the leaders map is for (docs/CHURCH_LEADERS_MAP.md §6), at
each of the three test churches, for Youth's leader Y, asserting the NEW
routing on a filled map.

A case today's code routes differently is xfail(strict=True) with the PR (§5)
that makes it pass: a strict xfail fails the moment it passes, so that PR
takes the mark off. A case today already routes right is a plain test, and
must stay right. Only an AssertionError counts as the expected failure, so a
broken probe never hides as one. db.map_intent reaches the map's tables once
church_map exists (PR 3 on); until then these run on today's data."""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
from church_three import (GRACE as GR, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, build, drift_told,  # noqa: E402
                          late_follow_up, late_task, money, room_alerts)


def case(biz, pr=None, why=""):
    marks = [pytest.mark.xfail(strict=True, raises=AssertionError, reason=f"PR {pr}: {why}")] if pr else []
    return pytest.param(biz, marks=marks, id=NAMES[biz])


@pytest.fixture
def db(monkeypatch):
    return build(monkeypatch)


# 1. A room request: its phone alerts go to the rooms duty's holders (the
# owner, the admins, and its Manager holders: Naiya and Jessica, the
# secretary, New Hope's office-lane login and its office overseer), never the
# People & Care login.
ROOMS = {LC: ["Jessica", "Minnie", "Naiya", "owner"], GR: ["Sharon", "Thelma", "owner"],
         NH: ["Olive", "Owen", "Tessa", "owner"]}


@pytest.mark.parametrize("biz", [case(LC, 7, "a room ask phones the rooms duty, not everyone who sees the office"),
                                 case(GR), case(NH)])
def test_1_a_room_request_phones_the_rooms_duty(db, monkeypatch, biz):
    got = room_alerts(monkeypatch, db, biz)
    assert got == sorted(db.label[u] for u in cd.holders_of(biz, "rooms")) == ROOMS[biz]
    assert not {"Tiara", "Paige"} & set(got), "People & Care doesn't book rooms"


# 2. A drifting youth family, three Mondays: the shepherd, then the person the
# shepherd answers to, then the senior pastor. Grace stops at its Pastor.
DRIFT = {LC: [["Marcus"], ["Jessica"], ["Kevin"]], GR: [["Doris"], ["Samuel"], []],
         NH: [["Elena"], ["Amara"], ["Nathan"]]}


# Grace passes from PR 4: its Deacon Board shepherds once the map says so, and
# D2 leads no department and answers to no one, so today's chain (the Deacon
# Board answers to the Pastor) is already the line PR 6's would give.
@pytest.mark.parametrize("biz", [case(LC, 6, "Marcus answers to Jessica"), case(GR),
                                 case(NH, 6, "each elder answers to one associate pastor")])
def test_2_a_drifting_youth_family_climbs_the_shepherds_own_line(db, monkeypatch, biz):
    assert drift_told(monkeypatch, db, biz) == DRIFT[biz]


# 3. A pay-back: $180 is the treasurer's alone everywhere; $250 needs Grace's
# pastor too ($200 there) and nobody else's; $600 is still the treasurer's
# alone at New Hope ($1,000 there). A Manager, the secretary too, never gives
# the treasurer's step.
T, P = "treasurer", "pastor"
NEEDS = {LC: {18_000: [T], 25_000: [T], 60_000: [T, P]}, GR: {18_000: [T], 25_000: [T, P], 60_000: [T, P]},
         NH: {18_000: [T], 25_000: [T], 60_000: [T]}}
TREASURERS = {LC: ["Minnie", "owner"], GR: ["Thelma", "owner"], NH: ["Tessa", "owner"]}


@pytest.mark.parametrize("biz", [case(LC), case(GR, 7, "Grace's levels are $200 / $1,000"),
                                 case(NH, 7, "New Hope's levels are $1,000 / $5,000")])
def test_3_a_pay_back_asks_the_churchs_own_levels(db, biz):
    needs, who = money(db, biz)
    assert needs == NEEDS[biz]
    assert who[T] == TREASURERS[biz]


# 4. Y's late task, and Y's late follow-up a day on, email exactly Youth's
# overseer; three days on, one person further up.
LATE = {LC: (["Andre"], ["Kevin"]), GR: (["Daniel"], ["Samuel"]), NH: (["Amara"], ["Nathan"])}


@pytest.mark.parametrize("biz", [case(LC), case(GR, 6, "deacon D1 oversees Youth"),
                                 case(NH, 6, "A2 alone oversees Youth; A1 and A3 are never emailed")])
def test_4_late_work_goes_to_youths_overseer_then_one_further(db, monkeypatch, biz):
    one, three = LATE[biz]
    assert late_task(monkeypatch, db, biz) == one
    assert late_follow_up(monkeypatch, db, biz) == [one, three]
