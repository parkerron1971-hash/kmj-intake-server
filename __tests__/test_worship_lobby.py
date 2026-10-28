# __tests__/test_worship_lobby.py
#
# The lobby TV on its own (ChurchSavvy round 5, canvas board 26;
# worship_show.py + worship_show_router.py). Pins:
#   * a lobby TV that was never set follows the booth, with a first week
#     ready (Sunday morning's welcome loop, this week every day) and every
#     "what it shows" on
#   * its week is checked: the days (0 is Sunday), from and to as times of
#     day, ending after it starts, what it shows, a countdown's time and name
#   * a verse for the day, KJV, the member app's verse that day
#   * over HTTP: setup saves a lobby screen's week; its link reads it; the
#     lobby's own page brings the announcements marked Lobby, the verse, the
#     next service and the church's clock; only a lobby screen has one

import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import worship_show as wsh
import test_worship_show_router as base
from test_worship_show_router import BIZ, api, plan  # noqa: E402,F401  (api is the fixture)


def own(**kw):
    return {"mode": "own", "times": [{"days": [3], "from": "18:00", "to": "20:30", "what": "count", "title": "Bible study", "count_to": "19:00"}], **kw}


def test_a_lobby_tv_follows_until_it_is_set():
    lobby = wsh.clean_lobby({})
    assert lobby["mode"] == "follow" and all(lobby["shows"].values())
    assert [(t["days"], t["what"]) for t in lobby["times"]] == [([0], "welcome"), ([0, 1, 2, 3, 4, 5, 6], "week")]
    assert wsh.clean_lobby(None) == lobby


def test_its_week_is_checked():
    week = wsh.clean_lobby(own(shows={"verse": False, "logo": False}))
    assert week["mode"] == "own" and week["times"][0] == {"days": [3], "from": "18:00", "to": "20:30", "what": "count",
                                                         "title": "Bible study", "count_to": "19:00"}
    assert (week["shows"]["verse"], week["shows"]["logo"], week["shows"]["announcements"]) == (False, False, True)
    # Days come back in order, once each; a non-countdown time keeps no count_to.
    t = wsh.clean_lobby({"mode": "own", "times": [{"days": [6, 0, 6], "from": "09:00", "to": "18:00", "what": "week", "count_to": "10:00"}]})["times"][0]
    assert (t["days"], t["count_to"]) == ([0, 6], "")
    bad_time = lambda **kw: {"mode": "own", "times": [{"days": [0], "from": "08:00", "to": "13:00", "what": "welcome", **kw}]}  # noqa: E731
    for raw, words in [({"mode": "always"}, "follows the booth"),
                       (bad_time(days=[]), "Pick the days"), (bad_time(days=[7]), "Pick the days"), (bad_time(days=[True]), "Pick the days"),
                       (bad_time(**{"from": "8:00"}), "time of day"), (bad_time(to="24:00"), "time of day"),
                       (bad_time(to="08:00"), "ends after it starts"), (bad_time(what="movies"), "welcome loop"),
                       (bad_time(what="count", title="Bible study"), "counts to a time"),
                       (bad_time(what="count", count_to="19:00"), "Give the night a name"),
                       ({"mode": "own", "times": [bad_time()["times"][0]] * 13}, "up to 12")]:
        with pytest.raises(ValueError, match=words):
            wsh.clean_lobby(raw)


def test_a_verse_for_the_day():
    v = wsh.lobby_verse(date(2026, 11, 1))
    assert (v["kind"], v["label"], v["translation"]) == ("verse", "Psalm 118:24", "kjv")
    assert v["verses"][0]["text"].startswith("This is the day which the LORD hath made")
    # The member app's verse of the day, the same day.
    import member_portal_bible as mpb
    assert mpb.verse_of_day("kjv", date(2026, 11, 1))["label"] == v["label"]
    assert wsh.lobby_verse(date(2026, 11, 2))["label"] != v["label"]


def _match(row, filters):
    """The fake database's filters, with the two the lobby asks for: eq.false on a
    yes/no column and gte. on a time (PostgREST compares them as the column's type)."""
    for k, v in filters:
        cell = row.get(k)
        if k == "is_template" and cell is None:
            cell = False  # the column's default (APPLY-2026-10-19-worship-show.sql: not null default false)
        if v == "is.null":
            if cell is not None:
                return False
        elif v.startswith("eq."):
            want = v[3:]
            if (str(cell).lower() if isinstance(cell, bool) else str(cell)) != want:
                return False
        elif v.startswith("gte."):
            if cell is None or datetime.fromisoformat(str(cell).replace("Z", "+00:00")) < datetime.fromisoformat(v[4:]):
                return False
        elif v.startswith("in.("):
            if str(cell) not in v[4:-1].split(","):
                return False
    return True


def test_the_lobby_over_http(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setattr(base.FakeDb, "_match", staticmethod(_match))
    import worship_announce_router as war
    asked = {}

    def board_for(biz, starts_at, where="room"):
        asked["where"] = where
        return [{"kind": "announcement", "id": "an-1", "title": "Community Day", "design": "side"}]

    monkeypatch.setattr(war, "board_for", board_for)
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    plan(as_, title="Sunday, Nov 1", starts_at=soon)
    plan(as_, title="Old Sunday", starts_at="2026-01-04T16:05:00+00:00")
    plan(as_, title="The template", starts_at=soon, is_template=True)
    r = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Lobby TV", "role": "lobby"})
    screen = r.json()["screen"]
    assert screen["lobby"]["mode"] == "follow"
    saved = as_("owner").put(f"/worship/screens/{screen['id']}", json={"business_id": BIZ, "lobby": own()})
    assert saved.status_code == 200, saved.text
    assert saved.json()["screen"]["lobby"]["times"][0]["title"] == "Bible study"
    assert as_("owner").put(f"/worship/screens/{screen['id']}", json={"business_id": BIZ, "lobby": {"mode": "always"}}).status_code == 400
    assert as_("member").put(f"/worship/screens/{screen['id']}", json={"business_id": BIZ, "lobby": own()}).status_code == 403
    # Its link reads its week (no sign-in, never its link).
    info = as_("stranger").get(f"/worship/screen/{screen['token']}").json()
    assert info["screen"]["lobby"]["mode"] == "own" and "token" not in info["screen"]
    # The lobby's own page: the board marked Lobby, the verse, the next real service, the church's clock.
    page = as_("stranger").get(f"/worship/screen/{screen['token']}/lobby")
    assert page.status_code == 200, page.text
    body = page.json()
    assert asked["where"] == "lobby" and body["slides"][0]["title"] == "Community Day"
    assert body["verse"]["translation"] == "kjv" and body["next"]["title"] == "Sunday, Nov 1"
    assert body["lobby"]["mode"] == "own" and isinstance(body["zone"], str) and body["church"]["name"] == "Love City Church"
    # A board that can't be read leaves the rest.
    def broken(*a, **k):
        from fastapi import HTTPException
        raise HTTPException(503, "The announcements didn't load")
    monkeypatch.setattr(war, "board_for", broken)
    assert as_("stranger").get(f"/worship/screen/{screen['token']}/lobby").json()["slides"] == []
    # Only a lobby screen runs on its own.
    room = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    assert as_("stranger").get(f"/worship/screen/{room}/lobby").status_code == 403
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert as_("stranger").get(f"/worship/screen/{screen['token']}/lobby").status_code == 404
