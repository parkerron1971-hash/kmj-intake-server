"""The First Week report: what each new business did, joined from the
events the frontend now records, the track rows, the plug-in probes and
chief_activity.

The shape these tests pin is the one the audit had to assemble by hand
on 2026-09-02: two real strangers opened the coached session, stopped in
phase one, and never came back. The report must say exactly that from
the rows, and must keep saying something useful when any one read fails.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import first_week as fw  # noqa: E402
import sb_clients  # noqa: E402

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
BIZ_A = "aaaaaaaa-0000-0000-0000-000000000001"   # opened the session, stopped, never returned
BIZ_B = "bbbbbbbb-0000-0000-0000-000000000002"   # plugged three in, came back on day 2
BIZ_C = "cccccccc-0000-0000-0000-000000000003"   # created, nothing else


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _wire(monkeypatch, *, businesses, events=(), tracks=(), strategies=(), activity=(),
          plugins=None, fail_prefix=None):
    def _get(path):
        if fail_prefix and path.startswith(fail_prefix):
            raise RuntimeError("boom")
        if path.startswith("/businesses?"):
            return list(businesses)
        if path.startswith("/product_events?business_id="):
            return list(events)
        if path.startswith("/product_events?event=in."):
            return [{"event": "meet_chief_started"}, {"event": "meet_chief_skipped"}]
        if path.startswith("/business_tracks?"):
            return list(tracks)
        if path.startswith("/strategy_tracks?"):
            return list(strategies)
        if path.startswith("/chief_activity?"):
            return list(activity)
        raise AssertionError(f"unexpected read {path}")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(fw, "_now", lambda: NOW)
    monkeypatch.setattr(fw, "_plugins_for", lambda biz: (plugins or {}).get(biz["id"]))


def _biz(bid, name, days_ago):
    return {"id": bid, "name": name, "type": "personal_services", "owner_id": "o",
            "created_at": _iso(NOW - timedelta(days=days_ago)), "settings": {},
            "subscription_status": "trialing", "trial_ends_at": None}


def _ev(bid, event, at, **props):
    return {"business_id": bid, "event": event, "props": props, "created_at": _iso(at)}


def _plugin(key, done, blocked=()):
    return {"key": key, "title": key.replace("_", " ").title(), "done": done,
            "blocked_by": list(blocked)}


class TestEmptyWindow:
    def test_no_businesses_is_zeros_not_an_error(self, monkeypatch):
        _wire(monkeypatch, businesses=[])
        r = fw.first_week_report(days=30)
        assert r["businesses"] == []
        assert r["funnel"] == {"signups": 0, "session_opened": 0, "session_completed": 0,
                               "plugin_opened": 0, "one_plugged_in": 0, "activated": 0,
                               "returned": 0}
        # Anonymous intro counts still come through — they exist before a business does.
        assert r["intro"] == {"started": 1, "completed": 0, "skipped": 1}


class TestTheAuditShape:
    def _wire_three(self, monkeypatch, **over):
        a_created = NOW - timedelta(days=13)
        b_created = NOW - timedelta(days=5)
        kwargs = dict(
            businesses=[_biz(BIZ_B, "B", 5), _biz(BIZ_A, "A", 13), _biz(BIZ_C, "C", 1)],
            events=[
                _ev(BIZ_A, "onboarding_step", a_created - timedelta(minutes=3), step=3, name="your_work"),
                _ev(BIZ_A, "onboarding_step", a_created - timedelta(minutes=2), step=5, name="launch"),
                _ev(BIZ_A, "business_created", a_created),
                _ev(BIZ_A, "session_opened", a_created + timedelta(minutes=1), kind="business"),
                _ev(BIZ_A, "session_paused", a_created + timedelta(minutes=12), kind="business", phase="owner"),
                _ev(BIZ_B, "business_created", b_created),
                _ev(BIZ_B, "plugin_opened", b_created + timedelta(minutes=5), key="import_contacts", via="home"),
                _ev(BIZ_B, "plugin_opened", b_created + timedelta(days=1, hours=2), key="offerings", via="chief"),
            ],
            tracks=[{"business_id": BIZ_A, "status": "in_progress", "current_phase": "owner"}],
            activity=[
                {"business_id": BIZ_A, "created_at": _iso(a_created + timedelta(minutes=5))},
                {"business_id": BIZ_A, "created_at": _iso(a_created + timedelta(minutes=9))},
                {"business_id": BIZ_B, "created_at": _iso(b_created + timedelta(minutes=6))},
                {"business_id": BIZ_B, "created_at": _iso(b_created + timedelta(days=1, hours=3))},
            ],
            plugins={
                BIZ_A: [_plugin("import_contacts", False), _plugin("offerings", False),
                        _plugin("availability", False, blocked=("offerings",))],
                BIZ_B: [_plugin("import_contacts", True), _plugin("offerings", True),
                        _plugin("payments", True), _plugin("site", False, blocked=("offerings",)),
                        _plugin("brand", False)],
                BIZ_C: None,   # probes could not run
            },
        )
        kwargs.update(over)
        _wire(monkeypatch, **kwargs)
        return fw.first_week_report(days=30)

    def test_rows_come_back_newest_first_with_a_day_number(self, monkeypatch):
        r = self._wire_three(monkeypatch)
        assert [b["name"] for b in r["businesses"]] == ["B", "A", "C"]
        by = {b["business_id"]: b for b in r["businesses"]}
        assert by[BIZ_A]["day"] == 14
        assert by[BIZ_C]["day"] == 2

    def test_the_stranger_who_stopped_in_phase_one(self, monkeypatch):
        r = self._wire_three(monkeypatch)
        a = {b["business_id"]: b for b in r["businesses"]}[BIZ_A]
        assert a["onboarding"]["furthest_step"] == 5
        assert a["onboarding"]["furthest_step_name"] == "launch"
        assert a["session"] == {"kind": "business", "status": "in_progress", "phase": "owner",
                                "opened": True, "paused": True, "completed": False}
        assert a["plugins"]["done"] == 0 and a["plugins"]["total"] == 3
        # The next move skips the blocked item.
        assert a["plugins"]["next"] == "Import Contacts"
        assert a["chief_actions"] == 2
        assert a["days_active"] == 1
        assert a["returned"] is False
        assert a["activated"] is False

    def test_the_one_who_came_back_and_plugged_three_in(self, monkeypatch):
        r = self._wire_three(monkeypatch)
        b = {x["business_id"]: x for x in r["businesses"]}[BIZ_B]
        assert b["plugins"] == {"done": 3, "total": 5, "next": "Brand", "probed": True, "opened": 2}
        assert b["returned"] is True
        assert b["days_active"] == 2
        assert b["activated"] is True
        assert b["session"]["opened"] is False

    def test_a_business_whose_probes_failed_still_has_a_row(self, monkeypatch):
        r = self._wire_three(monkeypatch)
        c = {x["business_id"]: x for x in r["businesses"]}[BIZ_C]
        assert c["plugins"] == {"done": 0, "total": 0, "next": None, "probed": False, "opened": 0}
        assert c["onboarding"]["furthest_step"] == -1
        assert c["onboarding"]["furthest_step_name"] is None
        assert c["returned"] is False

    def test_the_funnel_counts_businesses_not_events(self, monkeypatch):
        r = self._wire_three(monkeypatch)
        assert r["funnel"] == {"signups": 3, "session_opened": 1, "session_completed": 0,
                               "plugin_opened": 1, "one_plugged_in": 1, "activated": 1,
                               "returned": 1}
        assert r["activation_plugins"] == 3

    def test_a_failed_read_degrades_to_what_could_be_learned(self, monkeypatch):
        r = self._wire_three(monkeypatch, fail_prefix="/chief_activity?")
        b = {x["business_id"]: x for x in r["businesses"]}[BIZ_B]
        # No activity rows, but the day-2 plugin_opened event still makes it a return.
        assert b["chief_actions"] == 0
        assert b["returned"] is True

    def test_a_completed_strategy_track_reads_as_completed(self, monkeypatch):
        r = self._wire_three(
            monkeypatch,
            tracks=[],
            strategies=[{"business_id": BIZ_A, "status": "completed", "current_phase": "launch_plan"}],
        )
        a = {x["business_id"]: x for x in r["businesses"]}[BIZ_A]
        assert a["session"]["kind"] == "strategy"
        assert a["session"]["completed"] is True


class TestBounds:
    def test_days_and_limit_are_clamped(self, monkeypatch):
        paths = []
        def _get(path):
            paths.append(path)
            return []
        monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
        monkeypatch.setattr(fw, "_now", lambda: NOW)
        r = fw.first_week_report(days=9999, limit=500)
        assert r["days"] == 365
        # The businesses read is the first call and carries the clamped cap.
        assert paths[0].startswith("/businesses?") and "limit=25" in paths[0]
        # With no businesses, only the anonymous intro read follows.
        assert len(paths) == 2 and paths[1].startswith("/product_events?event=in.")


class TestRoute:
    def test_first_week_is_a_literal_route_on_the_platform_router(self):
        import platform_console as pc
        from starlette.routing import Match
        paths = [r.path for r in pc.router.routes]
        assert "/platform/first-week" in paths
        # No parameter route on this router may capture it (route-order class).
        scope = {"type": "http", "method": "GET", "path": "/platform/first-week"}
        first = next(r for r in pc.router.routes if r.matches(scope)[0] == Match.FULL)
        assert first.path == "/platform/first-week"
