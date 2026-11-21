"""church_tells_sunday: the sermon draft, Sunday's count and the flyers."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import church_leader_tasks as clt
import church_tells as ct
import church_tells_sunday as cts
import sb_clients
import stream_relay_router as srr

CHICAGO = ZoneInfo("America/Chicago")
BIZ = "11111111-2222-3333-4444-555555555555"
BASE = "https://db.example.co"
# Sunday, November 22, 2026: 13:30 in Chicago.
SUNDAY_AFTER = datetime(2026, 11, 22, 19, 30, tzinfo=timezone.utc)


def _church(**settings):
    return {"id": BIZ, "name": "Grace Church", "type": "ministry", "owner_id": "owner", "settings": settings}


@pytest.fixture
def db(monkeypatch):
    """Every server read faked: the tables are lists of rows by path start;
    a table set to None is a read that failed. Returns (tables, paths)."""
    tables = {}
    paths = []

    def get(path):
        paths.append(path)
        for start, rows in tables.items():
            if path.startswith(start):
                return rows
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(clt, "zone", lambda church: CHICAGO)
    monkeypatch.setenv("SUPABASE_URL", BASE)
    return tables, paths


# ─── The sermon draft ─────────────────────────────────────────────────

def test_a_recording_draft_tells_sermons(db):
    tables, paths = db
    tables["/sermons?"] = [
        {"id": "s-1", "preached_on": "2026-11-22", "video_url": srr.watch_url("a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12)},
        {"id": "s-2", "preached_on": "2026-11-22", "video_url": "https://youtube.com/watch?v=x"},   # typed by hand
        {"id": "s-3", "preached_on": "2026-11-22", "video_url": ""},
    ]
    got = cts.sermon_draft(_church(), SUNDAY_AFTER)
    assert [(i.key, i.title, i.line, i.duty) for i in got] == [
        ("sermon-draft:s-1", "Sunday's sermon is ready to post", "The recording is in. Add the title and post it.",
         "sermons")]
    p = paths[0]
    assert f"business_id=eq.{BIZ}" in p and "published=eq.false" in p
    since = (SUNDAY_AFTER - timedelta(days=3)).isoformat()
    assert f"created_at=gte.{ct.q(since)}" in p and "+" not in p


def test_the_draft_names_its_day_and_quotes_the_church(db):
    tables, paths = db
    tables["/sermons?"] = [{"id": "s-9", "preached_on": "2026-11-18",
                            "video_url": srr.watch_url("b" * 8 + "-bbbb-bbbb-bbbb-" + "b" * 12)}]
    got = cts.sermon_draft({**_church(), "id": "a b&c"}, SUNDAY_AFTER)
    assert got[0].title == "Wednesday's sermon is ready to post"
    assert "business_id=eq.a%20b%26c&" in paths[0]


def test_a_failed_sermon_read_is_nothing(db):
    tables, _ = db
    tables["/sermons?"] = None
    assert cts.sermon_draft(_church(), SUNDAY_AFTER) == []


# ─── Sunday's count ───────────────────────────────────────────────────

def _plan_today(tables):
    tables["/worship_services?"] = [{"id": "plan-1", "title": "Sunday service",
                                     "starts_at": "2026-11-22T16:00:00+00:00"}]


def test_no_count_after_one_tells_attendance(db):
    tables, paths = db
    _plan_today(tables)
    got = cts.count_missing(_church(), SUNDAY_AFTER)
    assert [(i.key, i.title, i.line, i.duty) for i in got] == [
        ("count-missing:2026-11-22", "Sunday's count isn't in yet", "Enter today's head count before the day is out.",
         "attendance")]
    ws = next(p for p in paths if p.startswith("/worship_services?"))
    lo = datetime(2026, 11, 22, tzinfo=CHICAGO).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    assert f"business_id=eq.{BIZ}" in ws and f"starts_at=gte.{ct.q(lo)}" in ws
    assert any(p.startswith(f"/attendance_headcounts?business_id=eq.{BIZ}") for p in paths)
    assert any(p.startswith(f"/attendance?business_id=eq.{BIZ}") for p in paths)


def test_a_headcount_for_today_is_counted(db):
    tables, _ = db
    _plan_today(tables)
    tables["/attendance_headcounts?"] = [{"entry_id": "e-1", "updated_at": "2026-11-22T17:00:00+00:00"}]
    tables["/module_entries?"] = [{"id": "e-1", "module_id": "m-1", "data": {"date": "2026-11-22"}}]
    tables["/custom_modules?"] = [{"id": "m-1", "archetype_params": {}}]
    assert cts.count_missing(_church(), SUNDAY_AFTER) == []


def test_a_checkin_today_is_counted(db):
    tables, _ = db
    _plan_today(tables)
    tables["/attendance?"] = [{"entry_id": None, "checked_in_at": "2026-11-22T16:10:00+00:00"}]
    assert cts.count_missing(_church(), SUNDAY_AFTER) == []


def test_last_weeks_count_is_not_todays(db):
    tables, _ = db
    _plan_today(tables)
    tables["/attendance_headcounts?"] = [{"entry_id": "e-1", "updated_at": "2026-11-22T17:00:00+00:00"}]
    tables["/module_entries?"] = [{"id": "e-1", "module_id": "m-1", "data": {"date": "2026-11-15"}}]
    tables["/custom_modules?"] = [{"id": "m-1", "archetype_params": {}}]
    assert [i.key for i in cts.count_missing(_church(), SUNDAY_AFTER)] == ["count-missing:2026-11-22"]


@pytest.mark.parametrize("now", [
    datetime(2026, 11, 22, 18, 59, tzinfo=timezone.utc),     # 12:59 in Chicago
    datetime(2026, 11, 21, 21, 0, tzinfo=timezone.utc),      # Saturday afternoon
    datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc),       # Sunday 23:00 in Chicago is Monday in UTC: still Sunday
])
def test_only_sunday_after_one_on_the_churchs_clock(db, now):
    tables, paths = db
    _plan_today(tables)
    got = cts.count_missing(_church(), now)
    if now.day == 23:
        assert [i.key for i in got] == ["count-missing:2026-11-22"]
    else:
        assert got == [] and paths == []


def test_no_service_today_is_nothing(db):
    tables, _ = db
    assert cts.count_missing(_church(), SUNDAY_AFTER) == []


def test_a_service_occasion_counts_as_a_service(db):
    tables, _ = db
    tables["/custom_modules?"] = [{"id": "m-1", "name": "Services", "archetype_params": {}}]
    tables["/module_entries?"] = [{"id": "e-1", "module_id": "m-1", "data": {"date": "2026-11-22", "type": "service"}}]
    assert [i.key for i in cts.count_missing(_church(), SUNDAY_AFTER)] == ["count-missing:2026-11-22"]


def test_the_clock_failing_is_nothing(db, monkeypatch):
    _, paths = db
    monkeypatch.setattr(clt, "zone", lambda church: None)
    assert cts.count_missing(_church(), SUNDAY_AFTER) == [] and paths == []


@pytest.mark.parametrize("table", ["/worship_services?", "/attendance_headcounts?", "/attendance?"])
def test_a_failed_read_is_never_missed(db, table):
    tables, _ = db
    _plan_today(tables)
    tables[table] = None
    assert cts.count_missing(_church(), SUNDAY_AFTER) == []


def test_told_today_reads_nothing(db):
    tables, paths = db
    _plan_today(tables)
    church = _church(church_tells={"count-missing:2026-11-22": "2026-11-22T19:00:00+00:00"})
    assert cts.count_missing(church, SUNDAY_AFTER) == [] and paths == []


# ─── The flyer ────────────────────────────────────────────────────────

NOW = datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc)      # Saturday noon in Chicago
OLD = "2026-11-19T12:00:00+00:00"


def _flyer(eid):
    art = "c" * 8 + "-cccc-cccc-cccc-" + "c" * 12
    folder = f"{BASE}/storage/v1/object/public/business-assets/{BIZ}/event-flyers/{eid}/"
    return {"url": f"{folder}{art}.jpg", "thumb": f"{folder}{art}-thumb.jpg", "w": 1080, "h": 1350}


def _entry(n, day, **data):
    eid = f"{n:08d}-0000-0000-0000-000000000000"
    return {"id": eid, "module_id": "m-1", "created_at": OLD, "data": {"title": f"Event {n}", "date": day, **data}}


@pytest.fixture
def events(db):
    tables, paths = db
    tables["/custom_modules?"] = [{"id": "m-1", "archetype_params": {}}]
    e = [
        _entry(1, "2026-11-28T18:00:00"),                                  # in a week: needs one
        _entry(2, "2026-11-24"),                                           # Tuesday: needs one (soonest)
        _entry(3, "2026-11-25T19:00:00"),                                  # has a flyer
        _entry(4, "2026-11-26", _visibility="private"),                    # church only
        _entry(5, "2026-11-27", _visibility="invite"),                     # invite only
        _entry(6, "2026-11-29", type="service"),                           # a service
        _entry(7, "2026-12-10"),                                           # past 14 days
        _entry(8, "2026-11-21T09:00:00"),                                  # this morning: over
        _entry(9, "2026-11-30"),                                           # needs one
        _entry(10, "2026-12-01"),                                          # needs one (the 4th)
    ]
    e[2]["data"]["_flyer"] = _flyer(e[2]["id"])
    tables["/module_entries?"] = e
    return tables, paths


def test_the_soonest_three_events_without_a_flyer(events):
    _, paths = events
    got = cts.flyer_needed(_church(), NOW)
    assert [i.key for i in got] == [f"flyer:{n:08d}-0000-0000-0000-000000000000" for n in (2, 1, 9)]
    assert got[0].title == "Event 2 needs a flyer" and got[0].duty == "flyers"
    assert got[0].line == "It's on Tuesday, November 24. Make its flyer so people can share it."
    me = next(p for p in paths if p.startswith("/module_entries?"))
    settled = (NOW - timedelta(hours=12)).isoformat()
    assert f"business_id=eq.{BIZ}" in me and f"created_at=lte.{ct.q(settled)}" in me and "status=eq.active" in me
    assert "module_id=in.(m-1)" in me
    cm = next(p for p in paths if p.startswith("/custom_modules?"))
    assert f"business_id=eq.{BIZ}" in cm and "archetype=eq.event_roster" in cm


def test_told_events_make_room_for_the_next(events):
    told = {f"flyer:{n:08d}-0000-0000-0000-000000000000": "x" for n in (2, 1)}
    got = cts.flyer_needed(_church(church_tells=told), NOW)
    assert [i.key for i in got] == [f"flyer:{n:08d}-0000-0000-0000-000000000000" for n in (9, 10)]


def test_flyers_need_the_clock_and_the_reads(events, monkeypatch):
    tables, _ = events
    monkeypatch.setattr(clt, "zone", lambda church: None)
    assert cts.flyer_needed(_church(), NOW) == []
    monkeypatch.setattr(clt, "zone", lambda church: CHICAGO)
    tables["/module_entries?"] = None
    assert cts.flyer_needed(_church(), NOW) == []
    tables["/custom_modules?"] = None
    assert cts.flyer_needed(_church(), NOW) == []


def test_no_database_address_tells_nothing(events, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert cts.flyer_needed(_church(), NOW) == []


def test_the_finders_are_the_sweeps():
    for name in ("sermon_draft", "count_missing", "flyer_needed"):
        assert f"church_tells_sunday:{name}" in ct.FINDERS
        assert ct._finder(f"church_tells_sunday:{name}") is getattr(cts, name)
