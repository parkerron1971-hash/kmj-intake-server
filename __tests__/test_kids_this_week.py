# __tests__/test_kids_this_week.py
#
# Kids check-in with nothing to check in to (run-through, 2026-11-05): a
# new church has a Services & Events room and no service in it, and the
# week's service is only made once members' Sunday check-in is on. One
# tap (POST /kids/this-week) makes this week's service through the same
# church_checkin.ensure_occasion the hourly sweep uses. Pins:
#   1. a team member gets this week's occasion, at the church's own time
#   2. a viewer or a stranger gets nothing, and nothing is made
#   3. no Services & Events room: a 409 that says what to do
#   4. the occasion is the same one ensure_occasion keeps once
import pathlib
import sys
from datetime import date, datetime, timezone

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import church_checkin as cc  # noqa: E402
from test_kids_checkin import BIZ, MEMBER, STRANGER, VIEWER, client, store  # noqa: E402,F401

SUNDAY = date(2026, 11, 8)


@pytest.fixture
def made(monkeypatch):
    calls = []
    monkeypatch.setattr(cc, "settings", lambda biz: dict(cc.DEFAULTS, timezone="America/Detroit", saved=False))
    monkeypatch.setattr(cc, "window", lambda st, now=None: {
        "day": SUNDAY, "weekday": "Sunday",
        "start": datetime(2026, 11, 8, 11, 0, tzinfo=timezone.utc), "open": False})

    def ensure(biz, st, day):
        calls.append((biz, day))
        return {"id": "occ-1", "title": "Sunday Worship", "date": "2026-11-08T11:00"}

    monkeypatch.setattr(cc, "ensure_occasion", ensure)
    return calls


def test_a_team_member_gets_this_weeks_service(store, made):
    r = client(MEMBER).post("/kids/this-week", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    assert r.json()["occasion"] == {"id": "occ-1", "title": "Sunday Worship", "date": "2026-11-08T11:00",
                                    "day": "2026-11-08", "weekday": "Sunday", "time": "11:00 AM"}
    assert made == [(BIZ, SUNDAY)]


@pytest.mark.parametrize("who", [VIEWER, STRANGER])
def test_a_viewer_or_a_stranger_gets_nothing(store, made, who):
    r = client(who).post("/kids/this-week", json={"business_id": BIZ})
    assert r.status_code == 403
    assert made == []


def test_no_services_room_says_what_to_do(store, made, monkeypatch):
    monkeypatch.setattr(cc, "ensure_occasion", lambda biz, st, day: None)
    r = client(MEMBER).post("/kids/this-week", json={"business_id": BIZ})
    assert r.status_code == 409
    assert "Services & Events" in r.json()["detail"]


def test_the_route_makes_the_occasion_the_sweep_would():
    import inspect
    import kids_checkin as kc
    src = inspect.getsource(kc.this_week)
    assert "church_checkin.ensure_occasion(" in src and "church_checkin.window(" in src
