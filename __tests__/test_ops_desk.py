# __tests__/test_ops_desk.py
#
# The ops desk: Kevin's lanes (Build holds two, through the door), his week
# (the rhythm, the quiet week, the hour the clocks change), the phone
# calendar (an HMAC link, RFC 5545 lines), the scorecard (a failed source
# reads "unknown", never zero), KAI's line (never into Build, never Kevin's
# tasks) and the Scope keeper's findings. Supabase is faked at the module's
# own storage helpers.

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import ops_desk as od
import platform_today

NY = od.zone("America/New_York")
ROOT = b"test-root-secret-for-the-calendar-link"


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _ny(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=NY)


# ─── The week ─────────────────────────────────────────────────────────

def test_quiet_week_is_the_last_full_week_of_the_month():
    assert od.quiet_week(date(2026, 10, 5)) == (date(2026, 10, 26), date(2026, 10, 30))
    # November 30 is a Monday: that week runs into December, so the quiet
    # week is the one before it.
    assert od.quiet_week(date(2026, 11, 2)) == (date(2026, 11, 23), date(2026, 11, 27))
    assert od.quiet_week(date(2026, 12, 1)) == (date(2026, 12, 21), date(2026, 12, 25))
    assert od.is_quiet(date(2026, 10, 28)) and not od.is_quiet(date(2026, 10, 22))


def _kinds(d):
    return [e["kind"] for e in od.rhythm_for_day(d, od.resolve_rhythm({}), NY)]


def test_the_rhythm_by_day():
    assert _kinds(date(2026, 10, 19)) == ["morning"]                         # Monday
    assert _kinds(date(2026, 10, 20)) == ["morning", "build"]                # Tuesday
    assert _kinds(date(2026, 10, 22)) == ["morning", "build", "release"]     # Thursday
    assert _kinds(date(2026, 10, 23)) == ["morning", "scorecard"]            # Friday
    assert _kinds(date(2026, 10, 24)) == []                                  # Saturday: off
    assert _kinds(date(2026, 11, 2)) == ["morning", "close"]                 # first Monday
    assert _kinds(date(2026, 11, 6)) == ["morning", "scorecard", "audit"]    # first Friday


def test_quiet_week_turns_build_blocks_into_fix_blocks_and_skips_the_release():
    events = od.rhythm_for_day(date(2026, 10, 29), od.resolve_rhythm({}), NY)
    assert [e["kind"] for e in events] == ["morning", "build"]
    assert events[1]["label"] == "Fix block" and events[1]["quiet"]


def test_times_follow_the_clock_change():
    r = od.resolve_rhythm({})
    before = od.rhythm_for_day(date(2026, 10, 20), r, NY)[0]   # EDT
    after = od.rhythm_for_day(date(2026, 11, 3), r, NY)[0]     # EST
    assert before["start"].startswith("2026-10-20T11:30:00")
    assert after["start"].startswith("2026-11-03T12:30:00")
    assert before["at_words"] == "7:30 AM"


def test_overrides_are_checked_not_trusted():
    r = od.resolve_rhythm({"morning": {"at": "06:45", "minutes": 25, "days": [0, 2, 9, "x"]},
                           "build": {"at": "25:00", "on": False}, "nonsense": {"at": "01:00"}})
    assert r["morning"]["at"] == "06:45" and r["morning"]["minutes"] == 25
    assert r["morning"]["days"] == [0, 2]
    assert r["build"]["at"] == "09:00" and r["build"]["on"] is False
    assert "nonsense" not in r
    assert _kinds_for(r, date(2026, 10, 20)) == []  # Tuesday: no morning, build off


def _kinds_for(r, d):
    return [e["kind"] for e in od.rhythm_for_day(d, r, NY)]


def test_events_between_holds_one_quiet_week_event():
    evs = od.events_between(date(2026, 10, 24), date(2026, 11, 1), od.resolve_rhythm({}), NY)
    quiet = [e for e in evs if e["kind"] == "quiet"]
    assert len(quiet) == 1
    assert quiet[0]["date"] == "2026-10-26" and quiet[0]["end_date"] == "2026-10-31"


def test_clock_words():
    assert od.clock_words("07:30") == "7:30 AM"
    assert od.clock_words("15:00") == "3 PM"
    assert od.clock_words("00:05") == "12:05 AM"
    assert od.clock_words("12:00") == "12 PM"


# ─── KAI's moments ────────────────────────────────────────────────────

def test_morning_prep_is_due_from_its_lead_until_the_queue_ends():
    r = od.resolve_rhythm({})
    assert od.due_moments(_ny(2026, 10, 20, 6, 59).astimezone(timezone.utc), NY, r, {}) == []
    due = od.due_moments(_ny(2026, 10, 20, 7, 5).astimezone(timezone.utc), NY, r, {})
    assert [m["moment"] for m in due] == ["morning_prep"]
    assert "7:30 AM" in due[0]["text"] and due[0]["key"] == "2026-10-20:morning_prep"
    # Acked, it isn't offered again; after the queue ends, it is gone.
    assert od.due_moments(_ny(2026, 10, 20, 7, 10).astimezone(timezone.utc), NY, r,
                          {"2026-10-20:morning_prep": "x"}) == []
    assert od.due_moments(_ny(2026, 10, 20, 7, 51).astimezone(timezone.utc), NY, r, {}) == []


def test_block_prep_and_quiet_week_wording():
    r = od.resolve_rhythm({})
    due = od.due_moments(_ny(2026, 10, 20, 8, 45).astimezone(timezone.utc), NY, r, {})
    assert [m["moment"] for m in due] == ["block_prep"]
    quiet = od.due_moments(_ny(2026, 10, 27, 8, 45).astimezone(timezone.utc), NY, r, {})
    assert quiet and "quiet week" in quiet[0]["text"]
    assert od.due_moments(_ny(2026, 10, 19, 8, 45).astimezone(timezone.utc), NY, r, {}) == []  # Monday


# ─── The lanes ────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
DOOR = {"who_asked": "a church", "owner_seat": "Code", "monthly_cost": "none",
        "off_switch": "X=off", "what_waits": "editions"}
B1 = {"id": "b1", "title": "One"}
B2 = {"id": "b2", "title": "Two"}


def test_build_holds_two():
    with pytest.raises(od.OpsRefusal) as e:
        od.apply_change({}, {"title": "Third", "lane": "build", "door": DOOR}, [B1, B2], "kevin", NOW)
    assert e.value.status == 409 and "One" in e.value.message and "Two" in e.value.message
    ok = od.apply_change({}, {"title": "Second", "lane": "build", "door": DOOR}, [B1], "kevin", NOW)
    assert ok["lane"] == "build" and ok["lane_since"] == NOW.isoformat()


def test_build_is_entered_through_the_door():
    with pytest.raises(od.OpsRefusal) as e:
        od.apply_change({}, {"title": "X", "lane": "build", "door": {"who_asked": "me"}}, [], "kevin", NOW)
    assert e.value.status == 422 and "What switches it off?" in e.value.message
    # An existing Try item brings its answers with it.
    before = {"id": "t1", "lane": "try", "status": "open", "door": DOOR}
    assert od.apply_change(before, {"lane": "build"}, [B1], "kevin", NOW)["lane"] == "build"


def test_a_build_item_already_in_its_slot_can_change_freely():
    before = {"id": "b1", "lane": "build", "status": "doing", "door": {}}
    out = od.apply_change(before, {"detail": "more"}, [B1, B2], "kevin", NOW)
    assert out["detail"] == "more" and "lane_since" not in out


def test_reopening_a_finished_build_item_needs_a_free_slot():
    before = {"id": "b3", "lane": "build", "status": "done", "door": DOOR}
    with pytest.raises(od.OpsRefusal):
        od.apply_change(before, {"status": "doing"}, [B1, B2], "kevin", NOW)


def test_done_stamps_and_reopen_clears():
    out = od.apply_change({"id": "t", "lane": "fix", "status": "open"}, {"status": "done"}, [], "kevin", NOW)
    assert out["done_at"] == NOW.isoformat()
    out = od.apply_change({"id": "t", "lane": "fix", "status": "done"}, {"status": "open"}, [], "kevin", NOW)
    assert out["done_at"] is None


def test_kai_never_moves_work_into_or_out_of_build():
    with pytest.raises(od.OpsRefusal) as e:
        od.apply_change({}, {"title": "X", "lane": "build", "door": DOOR}, [], "kai", NOW)
    assert e.value.status == 403
    mine = {"id": "k", "lane": "build", "status": "doing", "holder": "kai", "source": "plan"}
    with pytest.raises(od.OpsRefusal):
        od.apply_change(mine, {"lane": "try"}, [B1], "kai", NOW)
    assert od.apply_change(mine, {"status": "waiting"}, [B1], "kai", NOW)["status"] == "waiting"


def test_kai_keeps_its_own_tasks_and_leaves_kevins_alone():
    kevins = {"id": "x", "lane": "ops", "status": "open", "holder": "kevin", "source": "plan"}
    with pytest.raises(od.OpsRefusal) as e:
        od.apply_change(kevins, {"status": "done"}, [], "kai", NOW)
    assert e.value.status == 403
    filed = {"id": "y", "lane": "fix", "status": "open", "holder": "kevin", "source": "kai"}
    assert od.apply_change(filed, {"status": "done"}, [], "kai", NOW)["status"] == "done"


def test_links_are_https_or_a_repo_path():
    assert od.clean_link("docs/OPERATIONS.md") == "docs/OPERATIONS.md"
    assert od.clean_link("https://github.com/x/y/pull/1") == "https://github.com/x/y/pull/1"
    for bad in ("javascript:alert(1)", "http://x.com", "file:///c:/x"):
        with pytest.raises(od.OpsRefusal):
            od.clean_link(bad)


def test_lanes_view_counts_due_and_stale():
    tasks = [
        {"id": "1", "title": "Old build", "lane": "build", "status": "doing",
         "lane_since": (NOW - timedelta(days=30)).isoformat()},
        {"id": "2", "title": "Late", "lane": "ops", "status": "open", "holder": "kevin", "due_on": "2026-10-19"},
        {"id": "3", "title": "KAI's", "lane": "fix", "status": "open", "holder": "kai", "due_on": "2026-10-19"},
        {"id": "4", "title": "Done", "lane": "fix", "status": "done", "done_at": (NOW - timedelta(days=1)).isoformat()},
    ]
    lv = od.lanes_view(tasks, NOW, NY)
    assert lv["build_slots"] == {"used": 1, "of": 2, "open": 1}
    assert lv["build_stale"][0]["days"] == 30
    assert [t["id"] for t in lv["due"]] == ["2"]   # Kevin's only
    assert [t["id"] for t in lv["done_this_week"]] == ["4"]


# ─── The calendar ─────────────────────────────────────────────────────

def test_calendar_token_is_stable_per_version_and_checked_in_constant_time():
    a = od.calendar_token(1, root=ROOT)
    assert len(a) == 32 and a == od.calendar_token(1, root=ROOT)
    assert a != od.calendar_token(2, root=ROOT)
    assert od.token_ok(a, 1, root=ROOT) and not od.token_ok(a, 2, root=ROOT)
    assert not od.token_ok("x" * 32, 1, root=ROOT)


def test_ics_folding_never_passes_75_octets_or_splits_a_character():
    line = "DESCRIPTION:" + "Morning queue — approve, send, decide. " * 6
    folded = od.ics_fold(line)
    for part in folded.split("\r\n"):
        assert len(part.encode("utf-8")) <= 75
    assert folded.replace("\r\n ", "") == line


def test_ics_escapes_text():
    assert od.ics_escape("a, b; c\nd\\") == "a\\, b\\; c\\nd\\\\"


def _feed(tasks):
    events = od.events_between(date(2026, 10, 20), date(2026, 10, 30), od.resolve_rhythm({}), NY)
    return od.calendar_ics(events, tasks, NOW, NY, link_for=lambda page: f"https://app.test/?nav=studio:{page}")


def test_the_feed():
    tasks = [
        {"id": "t1", "title": "Break-glass", "status": "open", "holder": "kevin", "lane": "ops",
         "due_on": "2026-10-23", "detail": "Backup card, vault"},
        {"id": "t2", "title": "Old one", "status": "open", "holder": "kevin", "lane": "ops", "due_on": "2026-10-01"},
        {"id": "t3", "title": "KAI's job", "status": "open", "holder": "kai", "lane": "fix", "due_on": "2026-10-21"},
        {"id": "t4", "title": "Call Love City", "status": "open", "holder": "kevin", "lane": "ops",
         "starts_at": "2026-10-21T18:00:00+00:00", "minutes": 30},
        {"id": "t5", "title": "Finished", "status": "done", "holder": "kevin", "lane": "ops", "due_on": "2026-10-22"},
    ]
    ics = _feed(tasks)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:Morning queue" in unfolded and "SUMMARY:Build block" in unfolded
    assert "SUMMARY:Quiet week: fixes only" in unfolded
    assert "SUMMARY:Due: Break-glass" in unfolded and "DTSTART;VALUE=DATE:20261023" in unfolded
    # Past due shows on today, not in the past.
    assert "SUMMARY:Past due: Old one" in unfolded and "DTSTART;VALUE=DATE:20261020" in unfolded
    assert "KAI's job" not in unfolded and "Finished" not in unfolded
    assert "SUMMARY:Call Love City" in unfolded and "DTSTART:20261021T180000Z" in unfolded
    assert "DTSTART:20261020T113000Z" in unfolded          # 7:30 AM EDT
    assert "TRIGGER:-PT5M" in unfolded
    assert "URL:https://app.test/?nav=studio:platform-today" in unfolded
    assert unfolded.count("BEGIN:VEVENT") == unfolded.count("END:VEVENT")


def test_the_feed_endpoint(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", ROOT.decode())

    async def settings(_c):
        return {"id": "owner", "tz": "America/New_York", "calendar_version": 3}

    async def tasks(_c):
        return []
    monkeypatch.setattr(od, "load_settings", settings)
    monkeypatch.setattr(od, "load_tasks", tasks)
    good = od.calendar_token(3)
    r = _run(od.ops_calendar_feed(good))
    assert r.media_type.startswith("text/calendar")
    assert b"BEGIN:VCALENDAR" in r.body and r.headers["referrer-policy"] == "no-referrer"
    for bad in (od.calendar_token(2), "short", good[:-1] + ("A" if good[-1] != "A" else "B")):
        with pytest.raises(HTTPException) as e:
            _run(od.ops_calendar_feed(bad))
        assert e.value.status_code == 404


# ─── The scorecard ────────────────────────────────────────────────────

def _metric(score, key):
    return next(m for m in score["metrics"] if m["key"] == key)


def test_a_failed_source_reads_unknown_never_zero():
    score = od.compose_scorecard({"tasks": [], "lanes": od.lanes_view([], NOW, NY)}, NOW, NY)
    for key in ("queue_waiting", "tickets", "night_alerts", "chief_errors", "ai_spend", "prs", "paying"):
        m = _metric(score, key)
        assert m["state"] == "unknown" and m["value"] is None, key


def test_scorecard_states():
    x = {
        "queue": [{"at": (NOW - timedelta(hours=30)).isoformat()}, {"at": NOW.isoformat()}],
        "tickets": [{"created_at": (NOW - timedelta(hours=50)).isoformat()}],
        "pages": [{"created_at": "2026-10-20T03:00:00Z"}, {"created_at": "2026-10-20T15:00:00Z"}],
        "chief": {"error_rate": 0.11, "turns": 40},
        "spend_7d_cents": 7000, "mrr_cents": 0, "paying": 3,
        "prs": {"backend": 3, "frontend": 40}, "hours": 22,
        "tasks": [{"id": "s", "kind": "switch", "status": "open", "due_on": "2026-10-01", "title": "Barber plans"}],
        "lanes": od.lanes_view([], NOW, NY), "history": {},
    }
    s = od.compose_scorecard(x, NOW, NY)
    assert _metric(s, "queue_waiting")["value"] == 1
    assert _metric(s, "tickets")["state"] == "bad"
    assert _metric(s, "night_alerts")["value"] == 1          # 11 PM EDT counts; 11 AM doesn't
    assert _metric(s, "chief_errors")["state"] == "bad" and _metric(s, "chief_errors")["value"] == "11.0%"
    assert _metric(s, "ai_spend")["state"] == "warn" and "No subscription revenue" in _metric(s, "ai_spend")["detail"]
    assert _metric(s, "switches")["state"] == "bad"
    assert _metric(s, "prs")["state"] == "bad" and _metric(s, "hours")["state"] == "bad"
    assert s["metrics"][0]["state"] == "bad"                 # worst first


def test_spend_against_revenue():
    x = {"spend_7d_cents": 700, "mrr_cents": 30000, "tasks": [], "lanes": od.lanes_view([], NOW, NY)}
    m = _metric(od.compose_scorecard(x, NOW, NY), "ai_spend")
    assert m["value"] == "10%" and m["state"] == "ok"


def test_hiring_signals():
    hist = [{"date": (date(2026, 10, 20) - timedelta(days=i)).isoformat(), "queue_waiting": 1 if i < 3 else 0}
            for i in range(7)]
    sig = od.hire_signals({"tickets_14d": 70, "paying": 30}, hist, date(2026, 10, 20))
    met = {i["key"]: i["met"] for i in sig["items"]}
    assert met == {"tickets": True, "queue": True, "paying": True, "support_hours": None}
    assert sig["met"] == 3


def test_keeper_findings():
    lv = od.lanes_view([{"id": "1", "title": "Old build", "lane": "build", "status": "doing",
                         "lane_since": (NOW - timedelta(days=25)).isoformat()}], NOW, NY)
    tasks = [{"id": "s", "kind": "switch", "status": "open", "due_on": "2026-10-01", "title": "Barber plans"}]
    hist = [{"date": "2026-10-01", "signals_met": 2}]
    found = od.keeper_findings({"signals": {"met": 2}}, lv, tasks, hist, date(2026, 10, 20))
    titles = [f["title"] for f in found]
    assert "“Old build” has been in Build 25 days" in titles
    assert "“Barber plans” is past its decide-by date" in titles
    assert "Two hiring signals have held for two weeks" in titles


def test_keeper_findings_land_on_plan_in_today():
    g = {"agent": "scope_keeper", "title": "“Old build” has been in Build 25 days", "seen": 1,
         "latest_at": NOW, "first_at": NOW, "detail": ""}
    item = platform_today.classify_finding(g)
    assert item["room"] == "build" and item["action"] == {"label": "Open Plan", "nav": "platform-plan"}
    assert item["source"] == "Scope keeper"


# ─── Writes, through the fake ─────────────────────────────────────────

class Fake:
    def __init__(self, tasks=()):
        self.tasks = {t["id"]: dict(t) for t in tasks}
        self.settings = {"id": "owner", "tz": "America/New_York", "calendar_version": 1}

    async def select(self, _c, table, params):
        if table == "platform_ops_settings":
            return [dict(self.settings)]
        rows = list(self.tasks.values())
        if params.get("lane") == "eq.build":
            rows = [r for r in rows if r.get("lane") == "build" and r.get("status") in od.ACTIVE]
        if params.get("source") == "eq.kai":
            rows = [r for r in rows if r.get("source") == "kai"]
        if params.get("id", "").startswith("eq."):
            rows = [r for r in rows if r["id"] == params["id"][3:]]
        return [dict(r) for r in rows]

    async def insert(self, _c, table, row):
        new = {"id": f"00000000-0000-4000-8000-{len(self.tasks) + 1:012d}", **row}
        self.tasks[new["id"]] = new
        return dict(new)

    async def update(self, _c, table, params, body):
        if table == "platform_ops_settings":
            self.settings.update(body)
            return [dict(self.settings)]
        tid = params["id"][3:]
        self.tasks[tid].update(body)
        return [dict(self.tasks[tid])]


@pytest.fixture
def fake(monkeypatch):
    f = Fake([{"id": "11111111-1111-4111-8111-111111111111", "title": "One", "lane": "build", "status": "doing"},
              {"id": "22222222-2222-4222-8222-222222222222", "title": "Two", "lane": "build", "status": "doing"},
              {"id": "33333333-3333-4333-8333-333333333333", "title": "Kevin's", "lane": "ops",
               "status": "open", "holder": "kevin", "source": "plan"}])
    monkeypatch.setattr(od, "_select", f.select)
    monkeypatch.setattr(od, "_insert", f.insert)
    monkeypatch.setattr(od, "_update", f.update)

    async def device(_c, _a):
        return {"id": "dev-1"}
    monkeypatch.setattr(od, "_device", device)
    return f


def test_owner_create_into_a_full_build_is_refused(fake):
    with pytest.raises(HTTPException) as e:
        _run(od.ops_task_create(od.TaskIn(title="Third", lane="build", door=DOOR)))
    assert e.value.status_code == 409
    out = _run(od.ops_task_create(od.TaskIn(title="An idea", lane="try")))
    assert out["task"]["lane"] == "try" and out["task"]["source"] == "kevin"


def test_kai_files_and_keeps_its_own(fake):
    out = _run(od.kai_task_create(od.KaiTaskIn(title="CI red on W3's branch", lane="fix"), authorization="Bearer x"))
    assert out["task"]["source"] == "kai" and out["task"]["holder"] == "kai"
    tid = out["task"]["id"]
    done = _run(od.kai_task_update(tid, od.KaiTaskPatch(status="done"), authorization="Bearer x"))
    assert done["task"]["status"] == "done"
    with pytest.raises(HTTPException) as e:
        _run(od.kai_task_update("33333333-3333-4333-8333-333333333333", od.KaiTaskPatch(status="done"),
                                authorization="Bearer x"))
    assert e.value.status_code == 403


def test_kai_has_a_daily_cap(fake, monkeypatch):
    monkeypatch.setattr(od, "KAI_TASKS_PER_DAY", 2)
    for i in range(2):
        _run(od.kai_task_create(od.KaiTaskIn(title=f"Thing {i}"), authorization="Bearer x"))
    with pytest.raises(HTTPException) as e:
        _run(od.kai_task_create(od.KaiTaskIn(title="One too many"), authorization="Bearer x"))
    assert e.value.status_code == 429


def test_kai_note_and_moment_ack(fake):
    _run(od.kai_note(od.KaiNoteIn(text="Nothing needs you. Two PRs updated.", moment="morning_prep"),
                     authorization="Bearer x"))
    assert fake.settings["kai_note"]["text"].startswith("Nothing needs you")
    _run(od.kai_moment_ack(od.AckIn(key="2026-10-20:morning_prep"), authorization="Bearer x"))
    assert "2026-10-20:morning_prep" in fake.settings["moments"]


def test_hours_are_logged_by_week(fake):
    out = _run(od.ops_hours(od.HoursIn(hours=13.25, week="2026-W43")))
    assert out == {"ok": True, "week": "2026-W43", "hours": 13.2}
    assert fake.settings["hours"]["2026-W43"] == 13.2
