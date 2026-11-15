# __tests__/test_worship_count_auto.py
#
# The countdown that starts by itself (worship_count_auto.py; Kevin
# 2026-11-14: "a pre service clock starts it that a person can set"). Pins:
#   * a time goes up at its moment on the church's own clock (America/New_York
#     here), for WINDOW_MINUTES after, on its days only, switched on only
#   * what goes up: an on-the-spot countdown to the time plus its minutes, shown
#     where the time says, marked as started by itself; the plan's countdown's
#     design and words when the service nearest its end has one, else the
#     church's own, with the logo at zero when there's no plan to move into
#   * once a day: the claim in the look's row; a booth that moved on a minute
#     later isn't overridden; of two copies of the server only one claims it;
#     a look saved from a page keeps the claim
#   * never over a booth that is running something (busy): the rule, case by case
#   * a read that fails skips the church this minute, never guesses (no UTC);
#     the switch off stops it; a sample church never gets one

import pathlib
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, unquote
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import sb_clients
import worship_count_auto as wca
import worship_router
import worship_show as wsh
import worship_show_router as wsr

BIZ = "11111111-1111-4111-8111-111111111111"
SVC = "33333333-3333-4333-8333-333333333333"
NY = ZoneInfo("America/New_York")
# Sunday 2026-11-15, 10:15 in New York (EST, UTC-5).
SUNDAY_1015 = datetime(2026, 11, 15, 15, 15, 20, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return SUNDAY_1015 + timedelta(minutes=minutes)


def times(*extra):
    return [{"id": "sun", "on": True, "days": [0], "at": "10:15", "minutes": 15, "where": "all"}, *extra]


class FakeDb:
    """The few reads and writes the sweep makes, with the filters it uses
    (eq, gte, lte, is.null, not.is.null on a json path)."""

    def __init__(self):
        self.look = {**wsh.clean_look({"countdown": {"times": times()}})}
        self.settings = [{"business_id": BIZ, "look": self.look, "updated_at": "2026-11-14T20:00:00.123456+00:00"}]
        self.live = []
        self.services = []
        self.fail = set()
        self.writes = []

    @staticmethod
    def _f(path):
        table, _, q = path.lstrip("/").partition("?")
        return table, dict((k, v) for k, v in parse_qsl(q, keep_blank_values=True) if k not in ("order", "limit")), \
            [(k, v) for k, v in parse_qsl(q, keep_blank_values=True)]

    def get(self, path, **_):
        table, one, many = self._f(path)
        if table in self.fail:
            return None
        if table == "worship_settings" and "look->countdown->times" in one:
            return [{"business_id": r["business_id"], "church": r["look"].get("countdown")}
                    for r in self.settings if (r["look"].get("countdown") or {}).get("times") is not None]
        if table == "worship_settings":
            return [dict(r) for r in self.settings if r["business_id"] == one["business_id"][3:]]
        if table == "worship_live":
            return [dict(r) for r in self.live if r["business_id"] == one["business_id"][3:]]
        if table == "businesses":
            return [{"id": BIZ, "owner_id": None, "availability": {"timezone": "America/New_York"}}]
        if table == "worship_services":
            rows = [r for r in self.services if r["business_id"] == one["business_id"][3:]]
            for k, v in many:
                if k == "id":
                    rows = [r for r in rows if r["id"] == v[3:]]
                if k == "starts_at" and v.startswith("gte."):
                    rows = [r for r in rows if r["starts_at"] >= unquote(v[4:])]
                if k == "starts_at" and v.startswith("lte."):
                    rows = [r for r in rows if r["starts_at"] <= unquote(v[4:])]
            return [dict(r) for r in rows]
        raise AssertionError(path)

    def patch(self, path, body):
        table, one, _ = self._f(path)
        if table in self.fail:
            return None
        if table == "worship_settings":
            hit = [r for r in self.settings if r["business_id"] == one["business_id"][3:]
                   and r["updated_at"] == unquote(one["updated_at"][3:])]
        elif table == "worship_live":
            hit = [r for r in self.live if r["business_id"] == one["business_id"][3:] and str(r["rev"]) == one["rev"][3:]]
        else:
            raise AssertionError(path)
        for r in hit:
            r.update(body)
            self.writes.append((table, body))
        return [dict(r) for r in hit]

    def post(self, path, body, prefer=None, **_):
        table, _, _ = self._f(path)
        if table in self.fail:
            return None
        if table == "worship_live":
            if any(r["business_id"] == body["business_id"] for r in self.live):
                return None  # a conflict: the row was made in between
            self.live.append(dict(body))
            self.writes.append((table, body))
            return [dict(body)]
        raise AssertionError(path)

    def state(self):
        return self.live[0]["state"] if self.live else None

    def fired(self):
        return self.settings[0]["look"].get(wsh.FIRED_KEY)


@pytest.fixture
def db(monkeypatch):
    d = FakeDb()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(wsr, "HUB", wsr.LiveHub())
    monkeypatch.setattr(wca, "_ZONES", {})
    monkeypatch.setenv("WORSHIP_SONGS", "owner")
    monkeypatch.setattr(worship_router, "sunday_tools_mode", lambda: "owner", raising=False)
    import sample_church
    monkeypatch.setattr(sample_church, "skip_id", lambda biz: False)
    return d


def test_it_goes_up_by_itself_at_its_time_on_the_churchs_clock(db):
    assert wca.sweep_tick(at(-1))["up"] == 0 and db.state() is None  # 10:14
    got = wca.sweep_tick(at(0))
    assert got["up"] == 1
    state = db.state()
    up = state["adhoc"]
    assert up["kind"] == "countdown" and up["show"] == "all" and state["auto"] == {"id": "sun", "at": "10:15"}
    # It counts to 10:30 in New York, the time plus its minutes, whatever second the tick came.
    assert datetime.fromisoformat(up["slides"][0]["to"]) == datetime(2026, 11, 15, 10, 30, tzinfo=NY)
    # The church's own countdown (no plan near): its design, and the logo at zero.
    slide = up["slides"][0]
    assert (slide["design"], slide["title"], slide["big_last"], slide["zero"]) == ("glass", "We start soon", True, "logo")
    assert state["mode"] == "show" and state["service_id"] is None and state["at"] and state["since"]
    # The state is one the booth itself could have sent: it passes clean_live.
    assert wsh.clean_live(state)["adhoc"] == up
    # This copy's screens heard it at once.
    assert wsr.HUB.latest(BIZ)[1] == state


def test_its_days_its_window_and_its_switch(db):
    db.look["countdown"]["times"] = times({"id": "wed", "on": True, "days": [3], "at": "18:45", "minutes": 15, "where": "room"})
    # Monday at 10:15 nothing; Wednesday 18:47 (inside the window) the Wednesday one, on the room only.
    assert wca.sweep_tick(at(60 * 24))["up"] == 0
    assert wca.sweep_tick(at(60 * 24 * 3 + 8 * 60 + 32))["up"] == 1
    assert db.state()["adhoc"]["show"] == "room" and db.state()["auto"]["id"] == "wed"
    # Past the window it doesn't go up late.
    db.live.clear()
    assert wca.sweep_tick(at(WINDOW := wca.WINDOW_MINUTES))["up"] == 0 and db.state() is None
    # Switched off, nothing.
    db.look["countdown"]["times"] = times()
    db.look["countdown"]["times"][0]["on"] = False
    assert wca.sweep_tick(at(0))["up"] == 0
    assert WINDOW == 3


def test_once_a_day_and_never_back_over_the_booth(db):
    assert wca.sweep_tick(at(0))["up"] == 1
    assert db.fired() == {"sun": "2026-11-15"}
    # 10:16: the booth moved on to the logo (which is idle). The time stays claimed: it never comes back.
    db.live[0]["state"] = {"service_id": None, "item_id": None, "slide": 0, "mode": "logo", "at": at(1).isoformat()}
    db.live[0]["rev"] += 5
    got = wca.sweep_tick(at(1.5))
    assert got["up"] == 0 and got["claimed"] == 1 and db.state()["mode"] == "logo"
    # Next Sunday it goes up again.
    db.live[0]["state"] = {}
    assert wca.sweep_tick(at(7 * 24 * 60))["up"] == 1


def test_two_copies_of_the_server_claim_it_once(db, monkeypatch):
    # Both read the same look; the first to write it changes updated_at, so the second's write matches nothing.
    stale = dict(db.settings[0])
    real_get = db.get

    def get(path, **kw):
        if path.startswith("/worship_settings?business_id="):
            return [dict(stale)]
        return real_get(path, **kw)
    assert wca.sweep_tick(at(0))["up"] == 1
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    db.live[0]["state"] = {}  # as if the second copy read the live row before the first wrote it
    assert wca._claim(BIZ, "sun", "2026-11-15", times(), at(0)) is False


def test_a_booth_that_pressed_between_the_check_and_the_write_wins(db, monkeypatch):
    db.live.append({"business_id": BIZ, "rev": 100, "state": {}})
    real = wca._live

    def moved(biz):
        ok, row = real(biz)
        db.live[0]["rev"] = 200  # the booth pressed after the sweep read the row
        return ok, row
    monkeypatch.setattr(wca, "_live", moved)
    got = wca.sweep_tick(at(0))
    assert got["moved"] == 1 and got["up"] == 0 and db.live[0]["state"] == {}


def state(**kw):
    return {"service_id": SVC, "item_id": "song-1", "slide": 0, "mode": "show", "at": at(-5).isoformat(), **kw}


ITEMS = {"song-1": {"id": "song-1", "kind": "song"}, "loop-1": {"id": "loop-1", "kind": "loop"},
         "count": {"id": "count", "kind": "countdown", "to": None}}


@pytest.mark.parametrize("live,why", [
    (None, None), ({}, None),
    # Off air, the logo: nothing running.
    ({"service_id": None, "item_id": None, "mode": "logo", "at": at(-1).isoformat()}, None),
    (state(mode="logo", at=at(-1).isoformat()), None),
    # Black is pressed on purpose (to hide something): the booth's for 30 minutes, then a forgotten screen.
    (state(mode="black"), "pressed"), (state(mode="black", item_id=None, service_id=None), "pressed"),
    (state(mode="black", item_id="loop-1"), "pressed"), (state(mode="black", at=at(-31).isoformat()), None),
    # A welcome loop waits for the countdown.
    (state(item_id="loop-1", at=at(-1).isoformat()), None),
    # A song pressed 5 minutes ago: the booth is running. Left up 31 minutes with no press: a forgotten screen.
    (state(), "pressed"), (state(at=at(-31).isoformat()), None),
    (state(mode="clear"), "pressed"),
    # Something on the spot, the same.
    (state(item_id=None, adhoc={"kind": "verse", "slides": [{"kind": "verse"}]}), "pressed"),
    # The plan's countdown counting to the start, or held: already counting.
    (state(item_id="count", at=at(-40).isoformat()), "counting"),
    (state(item_id="count", count={"to": None, "held": 300}), "held"),
    # A countdown that ended a few minutes ago: the next may replace it.
    (state(item_id="count", count={"to": at(-3).isoformat(), "held": None}), None),
    (state(item_id=None, adhoc={"kind": "countdown", "slides": [{"kind": "countdown", "to": at(5).isoformat()}]}), "counting"),
    (state(item_id=None, adhoc={"kind": "countdown", "slides": [{"kind": "countdown", "to": at(-10).isoformat()}]}), None),
])
def test_the_rule_for_a_booth_that_is_running_something(live, why):
    got = wca.busy(live, SUNDAY_1015, ITEMS, at(15).isoformat())
    assert (got is None) if why is None else (why in got)


def test_it_leaves_a_running_booth_and_tries_again_inside_the_window(db):
    db.live.append({"business_id": BIZ, "rev": 100, "state": state()})
    db.services.append({"id": SVC, "business_id": BIZ, "starts_at": "2026-11-15T15:30:00+00:00", "items": list(ITEMS.values())})
    got = wca.sweep_tick(at(0))
    assert got["busy"] == 1 and got["up"] == 0 and db.fired() is None
    # 10:16 the booth went to the welcome loop: now it goes up, over the loop.
    db.live[0]["state"] = state(item_id="loop-1", at=at(1).isoformat())
    assert wca.sweep_tick(at(1.2))["up"] == 1


def test_it_wears_the_plans_countdown_when_the_service_has_one(db):
    planned = wsh.clean_item({"id": "count", "kind": "countdown", "title": "Service starts in", "design": "drift",
                              "welcome": "Welcome home", "zero": "next", "big_last": True, "band_at": 180})
    db.services.append({"id": SVC, "business_id": BIZ, "starts_at": "2026-11-15T15:30:00+00:00",
                        "items": [planned, {"id": "song-1", "kind": "song"}]})
    # A service hours away isn't this countdown's.
    db.services.append({"id": "44444444-4444-4444-8444-444444444444", "business_id": BIZ,
                        "starts_at": "2026-11-15T23:00:00+00:00", "items": []})
    assert wca.sweep_tick(at(0))["up"] == 1
    s = db.state()
    slide = s["adhoc"]["slides"][0]
    assert s["service_id"] == SVC and s["adhoc"]["title"] == "Service starts in"
    assert (slide["design"], slide["welcome"], slide["zero"], slide["big_last"], slide["band_at"]) == ("drift", "Welcome home", "next", True, 180)
    # It still counts to its own end, not the plan's time.
    assert datetime.fromisoformat(slide["to"]) == datetime(2026, 11, 15, 10, 30, tzinfo=NY)
    # The church's own countdown with a plan to move into: zero starts the plan, not the logo.
    assert wca.count_slide({"items": [{"id": "s", "kind": "song"}]}, wsh.clean_count_look({}), at(15).isoformat())["zero"] == "next"


def test_a_read_that_fails_skips_the_church_and_never_guesses(db, monkeypatch):
    for table in ("worship_live", "worship_services", "worship_settings"):
        db.fail = {table}
        got = wca.sweep_tick(at(0))
        assert got["up"] == 0 and db.state() is None, table
    db.fail = set()
    # No time zone this minute (the owner's profile couldn't be read): no countdown at UTC's 10:15.
    import business_marketing

    def no_zone(row):
        raise RuntimeError("profile unreadable")
    monkeypatch.setattr(business_marketing, "business_tz", no_zone)
    monkeypatch.setattr(wca, "_ZONES", {})
    got = wca.sweep_tick(datetime(2026, 11, 15, 10, 15, 10, tzinfo=timezone.utc))
    assert got["unread"] == 1 and got["up"] == 0
    monkeypatch.undo()


def test_the_switch_and_sample_churches(db, monkeypatch):
    monkeypatch.setattr(worship_router, "sunday_tools_mode", lambda: "off", raising=False)
    assert wca.sweep_tick(at(0)).get("off") == 1 and db.state() is None
    monkeypatch.setattr(worship_router, "sunday_tools_mode", lambda: "owner", raising=False)
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert wca.sweep_tick(at(0)).get("off") == 1
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    import sample_church
    monkeypatch.setattr(sample_church, "skip_id", lambda biz: True)
    assert wca.sweep_tick(at(0))["up"] == 0 and db.state() is None


def test_due_on_the_churchs_clock_across_the_week():
    t = times()
    local = SUNDAY_1015.astimezone(NY)
    assert [x[0]["id"] for x in wca.due(t, local)] == ["sun"]
    assert list(wca.due(t, local - timedelta(minutes=1))) == []
    assert list(wca.due(t, local + timedelta(minutes=3))) == []
    assert list(wca.due(t, local + timedelta(days=1))) == []
    # Summer time: 10:15 is still 10:15 on the church's clock (EDT, UTC-4).
    june = datetime(2026, 6, 14, 14, 15, 30, tzinfo=timezone.utc).astimezone(NY)
    assert [x[1].hour for x in wca.due(t, june)] == [10]
