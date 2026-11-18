"""The weekly database health check (db_health.py; Mission Control →
Systems → Database).

Kevin, 2026-11-18, after moving production from Nano to Small on a "Disk IO
Budget" warning: a check every week that says when to move the database up
a size. No network here: Supabase's metrics feed, the database and the owner
alert are all faked. The promises under test:
  - the Prometheus text is read right (labels, escapes, timestamps, NaN),
    only the primary database's own series count, partitions and loop
    devices never double the disk numbers;
  - readings are taken once a slot, only in the windows (Sunday 7:45 AM-1 PM
    Eastern, Wednesday 10:45 and 11), whatever the number of server copies;
  - rates come from two readings, never one, and a counter reset is no rate;
  - the verdict follows the planning guide's lines, names the next size and
    what it costs a month, and gives at most two reasons;
  - the owner hears once, when the verdict turns to "Time to move up";
  - every route is owner-only, the switch turns it all off, and a missing
    table is "not set up", never a 500.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import db_health as dh
import dev_alerts
import sb_clients
from auth_supabase import require_user
from lead_admin import PLATFORM_OWNER_EMAIL

ET = dh.ET
SMALL = dh.size_of("small")
GIB = dh.GIB
MB = dh.MB
SUNDAY = date(2026, 11, 22)
WEDNESDAY = date(2026, 11, 18)


def run(coro):
    return asyncio.run(coro)


def et(d: date, h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime.combine(d, dtime(h, m, s), ET)


# ─── A fake store ───────────────────────────────────────────────────────

class FakeDB:
    """The PostgREST paths db_health uses, in memory. missing=True answers
    like a database without the migration."""

    def __init__(self):
        self.samples: list = []
        self.weeks: list = []
        self.pg = {"connections": 20, "active": 3, "max_connections": 90, "db_bytes": 400 * 1024 ** 2}
        self.missing = False
        self.err = None
        self.calls: list = []
        self.churches = [{"id": "c1", "type": "church"}, {"id": "c2", "type": "ministry"},
                         {"id": "b1", "type": "coach"}]

    def _split(self, path):
        u = urlsplit(path)
        return u.path, parse_qsl(u.query)

    def _miss(self):
        self.err = {"status": 404, "code": "PGRST205", "message": "missing"}
        return None

    def last_error(self):
        return self.err

    def post(self, path, body, prefer="return=representation", *, redact=False):
        self.err = None
        self.calls.append(("post", path, body))
        if self.missing:
            return self._miss()
        table, _ = self._split(path)
        if table == "/rpc/db_health_pg":
            return dict(self.pg, **({"top_wal": [{"query": "insert into sol_news_items ...", "calls": 9,
                                                  "wal_bytes": 5000}],
                                     "top_temp": [], "since": "2026-11-01T00:00:00Z"}
                                    if body.get("p_top") else {}))
        if table == "/db_health_samples":
            if any(r["slot"] == body["slot"] for r in self.samples):
                return []
            row = {"taken_at": None, "metrics": None, "pg": None, "problem": None,
                   "created_at": dh._z(dh._now()), **body}
            self.samples.append(row)
            return [row]
        if table == "/db_health_weeks":
            if any(w["week"] == body["week"] for w in self.weeks):
                return []
            row = {"told_at": None, **body}
            self.weeks.append(row)
            return [row]
        raise AssertionError(path)

    def patch(self, path, body):
        self.err = None
        self.calls.append(("patch", path, body))
        if self.missing:
            return self._miss()
        table, q = self._split(path)
        q = dict(q)
        rows = self.samples if table == "/db_health_samples" else self.weeks
        key = "slot" if table == "/db_health_samples" else "week"
        hit = [r for r in rows if r[key] == q[key][3:]]
        if q.get("told_at") == "is.null":
            hit = [r for r in hit if not r.get("told_at")]
        for r in hit:
            r.update(body)
        return hit

    def get(self, path, *, redact=False):
        self.err = None
        self.calls.append(("get", path, None))
        if self.missing:
            return self._miss()
        table, q = self._split(path)
        if table == "/db_health_samples":
            rows = [r for r in self.samples if r.get("taken_at")]
            for k, v in q:
                if k == "taken_at" and v.startswith("gte."):
                    rows = [r for r in rows if dh._parse(r["taken_at"]) >= dh._parse(v[4:])]
                if k == "taken_at" and v.startswith("lt."):
                    rows = [r for r in rows if dh._parse(r["taken_at"]) < dh._parse(v[3:])]
            return sorted(rows, key=lambda r: dh._parse(r["taken_at"]))
        if table == "/db_health_weeks":
            q = dict(q)
            rows = list(self.weeks)
            if "week" in q:
                rows = [w for w in rows if w["week"] == q["week"][3:]]
            return sorted(rows, key=lambda w: w["week"], reverse=True)[: int(q.get("limit", 100))]
        raise AssertionError(path)

    def get_all(self, path, *, key="id", strict=False, redact=False):
        self.calls.append(("get_all", path, None))
        assert "is_sample=not.is.true" in path
        return list(self.churches)

    def delete(self, path):
        self.calls.append(("delete", path, None))
        _, q = self._split(path)
        cut = dh._parse(dict(q)["created_at"][3:])
        self.samples = [r for r in self.samples if dh._parse(r["created_at"]) >= cut]
        return True


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", fake.get_all)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    monkeypatch.setattr(sb_clients, "last_error", fake.last_error)
    monkeypatch.setenv("SUPABASE_URL", "https://abcref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key-not-a-secret")
    monkeypatch.delenv("SUPABASE_METRICS_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_COMPUTE_SIZE", raising=False)
    monkeypatch.delenv("DB_HEALTH_CHECK", raising=False)
    dh.forget()
    yield fake
    dh.forget()


# ─── The metrics feed ───────────────────────────────────────────────────

L = 'service_type="db",supabase_identifier="abcref",supabase_project_ref="abcref"'
FEED = f"""# HELP node_memory_MemTotal_bytes Memory information field MemTotal_bytes.
# TYPE node_memory_MemTotal_bytes gauge
node_memory_MemTotal_bytes{{service_type="db",supabase_identifier="abcref-rr-us-east-1-x1"}} 9e+09
node_memory_MemTotal_bytes{{{L}}} 2.05e+09
node_memory_MemAvailable_bytes{{{L}}} 1.2e+09
node_memory_SwapTotal_bytes{{{L}}} 1073741824
node_memory_SwapFree_bytes{{{L}}} 1073741824 1731900000000
node_memory_Committed_AS_bytes{{{L}}} 1.5e+09
node_cpu_seconds_total{{cpu="0",mode="idle",{L}}} 1000
node_cpu_seconds_total{{cpu="0",mode="user",{L}}} 200
node_cpu_seconds_total{{cpu="1",mode="idle",{L}}} 900
node_cpu_seconds_total{{cpu="1",mode="system",{L}}} 100
node_cpu_seconds_total{{cpu="0",mode="idle",service_type="postgrest"}} 99999
node_disk_read_bytes_total{{device="nvme0n1",{L}}} 1e+09
node_disk_read_bytes_total{{device="nvme1n1",{L}}} 2e+09
node_disk_read_bytes_total{{device="nvme1n1p1",{L}}} 5e+09
node_disk_read_bytes_total{{device="loop0",{L}}} 7e+09
node_disk_written_bytes_total{{device="nvme1n1",{L}}} 3e+09
node_disk_reads_completed_total{{device="nvme1n1",{L}}} 1000
node_disk_writes_completed_total{{device="nvme1n1",{L}}} 2000
pg_stat_database_num_backends{{server="localhost:5432",service_type="postgresql"}} 14
max_connections_connection_count{{server="localhost:5432",service_type="postgresql"}} 90
pg_database_size_bytes{{datname="template1",service_type="postgresql"}} 7e+06
pg_database_size_bytes{{datname="postgres",service_type="postgresql"}} 5e+08
go_memstats_alloc_bytes{{service_type="gotrue"}} 1e+06
node_load1{{{L}}} NaN
this line is not a metric
"""


def test_parse_reads_labels_escapes_timestamps_and_specials():
    got = dh.parse_prometheus('a{x="1",y="q\\"t\\\\n\\n"} 3.5 1700000000\n# c\n\nb +Inf\nc NaN\nd{} 2\nbad line here\n')
    assert got[0] == ("a", {"x": "1", "y": 'q"t\\n\n'}, 3.5)
    assert got[1][0] == "b" and got[1][2] == float("inf")
    assert got[2][0] == "c" and got[2][2] != got[2][2]      # NaN
    assert got[3] == ("d", {}, 2.0)
    assert len(got) == 4
    assert dh.parse_prometheus(None) == [] and dh.parse_prometheus("") == []


def test_reading_keeps_only_the_primary_databases_series():
    r = dh.reading_from(dh.parse_prometheus(FEED), "abcref")
    assert r["mem_total"] == 2.05e9            # not the read replica's 9 GB
    assert r["mem_available"] == 1.2e9
    assert r["swap_total"] == r["swap_free"] == 1073741824
    assert r["committed"] == 1.5e9
    assert r["cpu_idle"] == 1900 and r["cpu_total"] == 2200 and r["cpus"] == 2   # not PostgREST's
    assert r["disk_read"] == 3e9               # no partition, no loop device
    assert r["disk_written"] == 3e9
    assert r["disk_reads"] == 1000 and r["disk_writes"] == 2000
    assert r["backends"] == 14 and r["max_conn"] == 90
    assert r["db_bytes"] == 5e8                # postgres, not template1
    assert "node_load1" not in r


def test_reading_from_an_empty_feed_is_empty():
    assert dh.reading_from(dh.parse_prometheus("# nothing\n")) == {}


def test_metrics_url_comes_from_the_project_address(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abcref.supabase.co")
    assert dh.metrics_url() == "https://abcref.supabase.co/customer/v1/privileged/metrics"
    monkeypatch.setenv("SUPABASE_URL", "https://db.example.org")
    monkeypatch.delenv("SUPABASE_PROJECT_REF", raising=False)
    assert dh.metrics_url() is None
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "otherref")
    assert dh.metrics_url() == "https://otherref.supabase.co/customer/v1/privileged/metrics"
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "bad/ref")
    assert dh.metrics_url() is None


def _transport(status, text, seen):
    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(status, text=text)
    return httpx.MockTransport(handler)


def test_read_metrics_uses_basic_auth_and_never_says_the_key(db, monkeypatch):
    seen: list = []

    async def go(status, text):
        async with httpx.AsyncClient(transport=_transport(status, text, seen)) as c:
            return await dh.read_metrics(c)

    reading, why = run(go(200, FEED))
    assert why is None and reading["mem_total"] == 2.05e9
    req = seen[-1]
    assert str(req.url) == "https://abcref.supabase.co/customer/v1/privileged/metrics"
    assert req.headers["authorization"] == httpx.BasicAuth("service_role", "service-key-not-a-secret")._auth_header
    monkeypatch.setenv("SUPABASE_METRICS_KEY", "sb_secret_abc")
    run(go(200, FEED))
    assert seen[-1].headers["authorization"] == httpx.BasicAuth("service_role", "sb_secret_abc")._auth_header
    reading, why = run(go(401, "no"))
    assert reading is None and "refused" in why and "sb_secret_abc" not in why
    reading, why = run(go(500, "x"))
    assert reading is None and "500" in why
    reading, why = run(go(200, "# empty\n"))
    assert reading is None and "nothing" in why
    monkeypatch.delenv("SUPABASE_METRICS_KEY")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    reading, why = run(go(200, FEED))
    assert reading is None and "key" in why


# ─── Sizes ──────────────────────────────────────────────────────────────

def test_sizes_prices_and_next_size():
    assert dh.monthly(SMALL) == 15
    assert dh.monthly(dh.size_of("medium")) == 60
    assert dh.monthly(dh.size_of("large")) == 111
    assert dh.monthly(dh.size_of("xl")) == 210
    assert dh.monthly(dh.size_of("2xl")) == 410
    assert dh.next_size(SMALL)["key"] == "medium"
    assert dh.next_size(dh.size_of("4xl")) is None
    assert dh.churches_words(SMALL) == "up to ~25"
    assert dh.churches_words(dh.size_of("medium")) == "~25–100"
    assert dh.churches_words(dh.size_of("2xl")) == "500+"
    assert dh.size_of(" Small ")["key"] == "small" and dh.size_of("huge") is None


def test_size_is_read_from_memory_then_the_setting_then_small(monkeypatch):
    assert dh.size_from_memory(1.9 * GIB) == "small"
    assert dh.size_from_memory(2.05 * GIB) == "small"
    assert dh.size_from_memory(0.45 * GIB) == "nano"
    assert dh.size_from_memory(3.8 * GIB) == "medium"
    assert dh.size_from_memory(7.6 * GIB) == "large"
    assert dh.size_from_memory(None) is None and dh.size_from_memory("x") is None
    assert dh.size_from_memory(0) is None and dh.size_from_memory(500 * GIB) is None
    monkeypatch.delenv("SUPABASE_COMPUTE_SIZE", raising=False)
    assert dh.current_size(None)[0]["key"] == "small" and dh.current_size(None)[1] == "default"
    monkeypatch.setenv("SUPABASE_COMPUTE_SIZE", "medium")
    assert dh.current_size(None) == (dh.size_of("medium"), "setting")
    assert dh.current_size(1.9 * GIB) == (SMALL, "measured")
    monkeypatch.setenv("SUPABASE_COMPUTE_SIZE", "typo")
    assert dh.current_size(None)[1] == "default"


def test_sizes_table_marks_current_and_next_and_hides_the_tiny_ones():
    rows = dh.sizes_table(SMALL)
    keys = [r["key"] for r in rows]
    assert keys == ["small", "medium", "large", "xl", "2xl", "4xl"]
    assert [r["key"] for r in rows if r["current"]] == ["small"]
    assert [r["key"] for r in rows if r["next"]] == ["medium"]
    assert "nano" in [r["key"] for r in dh.sizes_table(dh.size_of("nano"))]


# ─── When to read ───────────────────────────────────────────────────────

@pytest.mark.parametrize("when,expect", [
    (et(SUNDAY, 7, 44), None),
    (et(SUNDAY, 7, 45), (et(SUNDAY, 7, 45), "sunday")),
    (et(SUNDAY, 8, 7, 30), (et(SUNDAY, 8, 0), "sunday")),
    (et(SUNDAY, 12, 59), (et(SUNDAY, 12, 45), "sunday")),
    (et(SUNDAY, 13, 4), (et(SUNDAY, 13, 0), "sunday")),
    (et(SUNDAY, 13, 15), None),
    (et(WEDNESDAY, 10, 44), None),
    (et(WEDNESDAY, 10, 50), (et(WEDNESDAY, 10, 45), "weekday")),
    (et(WEDNESDAY, 11, 14), (et(WEDNESDAY, 11, 0), "weekday")),
    (et(WEDNESDAY, 11, 15), None),
    (et(date(2026, 11, 23), 9, 0), None),                     # Monday
    (et(date(2026, 3, 8), 8, 0), (et(date(2026, 3, 8), 8, 0), "sunday")),    # clocks went forward
    (et(date(2026, 11, 1), 10, 0), (et(date(2026, 11, 1), 10, 0), "sunday")),  # and back
])
def test_slot_for(when, expect):
    got = dh.slot_for(when.astimezone(timezone.utc))
    if expect is None:
        assert got is None
    else:
        assert got == (expect[0].astimezone(timezone.utc), expect[1])


def test_the_last_slot_of_each_window_reads_the_top_writers():
    assert dh.last_of_window(et(SUNDAY, 13, 0), "sunday")
    assert not dh.last_of_window(et(SUNDAY, 12, 45), "sunday")
    assert dh.last_of_window(et(WEDNESDAY, 11, 0), "weekday")
    assert not dh.last_of_window(et(WEDNESDAY, 10, 45), "weekday")


def test_due_week_turns_on_monday_at_eight_eastern():
    monday = date(2026, 11, 23)
    assert dh.due_week(et(monday, 7, 59)) == date(2026, 11, 15)
    assert dh.due_week(et(monday, 8, 0)) == SUNDAY
    assert dh.due_week(et(date(2026, 11, 25), 3, 0)) == SUNDAY
    assert dh.due_week(et(SUNDAY, 23, 0)) == date(2026, 11, 15)
    assert dh.last_sunday(et(SUNDAY, 9, 0)) == SUNDAY
    assert dh.last_sunday(et(monday, 9, 0)) == SUNDAY
    assert dh.last_sunday(et(date(2026, 11, 28), 9, 0)) == SUNDAY
    start, end = dh.week_bounds(SUNDAY)
    assert start == et(date(2026, 11, 16), 0, 0) and end == et(monday, 0, 0)


# ─── Summing up a week ──────────────────────────────────────────────────

def series(day, start, steps, kind="sunday", mem_free=0.5, swap_used=0, committed=0.6, gap=15):
    """Readings `gap` minutes apart; each step (cpu busy, MB/s, ops/s) is
    the rate between the reading before it and its own."""
    t = datetime.combine(day, start, ET)
    total = idle = rd = ops = 0.0
    mem = 1.9 * GIB

    def row(at):
        return {"slot": dh._z(at), "kind": kind, "taken_at": dh._z(at), "problem": None,
                "metrics": {"mem_total": mem, "mem_available": mem * mem_free, "swap_total": GIB,
                            "swap_free": GIB - swap_used, "committed": mem * committed,
                            "cpu_idle": idle, "cpu_total": total, "cpus": 2.0,
                            "disk_read": rd, "disk_written": 0.0, "disk_reads": ops, "disk_writes": 0.0},
                "pg": {"connections": 20, "max_connections": 90, "db_bytes": 4e8}}
    rows = [row(t)]
    for busy, mbs, iops in steps:
        dt = gap * 60
        t += timedelta(minutes=gap)
        total += 2 * dt
        idle += 2 * dt * (1 - busy)
        rd += mbs * MB * dt
        ops += iops * dt
        rows.append(row(t))
    return rows


def test_rates_come_from_pairs_of_readings():
    rows = series(SUNDAY, dtime(9, 0), [(0.2, 2, 100), (0.62, 10, 300), (0.3, 25, 400)])
    s = dh.summarize(rows, SMALL)
    assert s["readings"] == 4 and s["sunday_readings"] == 4
    assert s["cpu"]["peak"] == pytest.approx(0.62)
    assert s["cpu"]["at"] == "Sunday at 9:30 AM"
    assert s["cpu"]["readings"] == 3 and s["cpu"]["over_move"] == 0
    assert s["disk"]["peak_mbs"] == pytest.approx(25)
    assert s["disk"]["share"] == pytest.approx(25 / 22)
    assert s["disk"]["over_baseline"] == 1 and s["disk"]["by"] == "throughput"
    assert s["memory"]["free_share"] == pytest.approx(0.5)
    assert s["connections"] == {"peak": 20, "max": 90, "at": "Sunday at 9:00 AM"}


def test_one_reading_has_no_rate_and_far_apart_readings_neither():
    assert dh.summarize(series(SUNDAY, dtime(9, 0), [])[:1], SMALL)["cpu"] is None
    far = series(SUNDAY, dtime(9, 0), [(0.9, 50, 5000)], gap=120)
    s = dh.summarize(far, SMALL)
    assert s["cpu"] is None and s["disk"] is None
    assert s["memory"] is not None          # gauges still count


def test_a_counter_reset_is_no_rate():
    rows = series(SUNDAY, dtime(9, 0), [(0.5, 5, 100), (0.5, 5, 100)])
    rows[2]["metrics"]["cpu_total"] = 10.0      # the database restarted (a resize)
    rows[2]["metrics"]["disk_read"] = 0.0
    s = dh.summarize(rows, SMALL)
    assert s["cpu"]["readings"] == 1 and s["disk"]["readings"] == 1


def test_ops_over_baseline_is_named_as_operations():
    s = dh.summarize(series(SUNDAY, dtime(9, 0), [(0.2, 2, 1200)]), SMALL)
    assert s["disk"]["by"] == "ops" and s["disk"]["share"] == pytest.approx(1.2)


def test_weekday_numbers_are_kept_for_comparison():
    rows = series(WEDNESDAY, dtime(10, 45), [(0.15, 1, 50)], kind="weekday") + \
        series(SUNDAY, dtime(9, 0), [(0.5, 8, 100)])
    s = dh.summarize(rows, SMALL)
    assert s["cpu"]["weekday"] == pytest.approx(0.15)
    assert s["cpu"]["peak"] == pytest.approx(0.5)
    assert s["weekday_readings"] == 2 and s["sunday_readings"] == 2


# ─── The verdict ────────────────────────────────────────────────────────

def verdict(steps, churches=5, size=SMALL, **kw):
    return dh.judge(size, dh.summarize(series(SUNDAY, dtime(9, 0), steps, **kw), size), churches)


def test_fine_at_small():
    v = verdict([(0.2, 2, 100), (0.3, 4, 150)])
    assert v["level"] == "fine" and v["headline"] == "Fine at Small"
    assert v["reasons"] == [] and v["measured"] is True
    assert v["next"] == {"key": "medium", "label": "Medium", "monthly": 60, "more": 45}


def test_watch_cpu():
    v = verdict([(0.2, 2, 100), (0.6, 4, 150)])
    assert v["level"] == "watch" and v["headline"] == "Watch: CPU reached 60%"
    assert "The line is 70%" in v["reasons"][0]["text"]
    one_over = verdict([(0.74, 2, 100), (0.3, 4, 150)])
    assert one_over["level"] == "watch" and "Half an hour over 70%" in one_over["reasons"][0]["text"]


def test_cpu_over_seventy_for_half_an_hour_moves_up():
    v = verdict([(0.72, 2, 100), (0.8, 4, 150), (0.4, 4, 150)])
    assert v["level"] == "move"
    assert v["headline"] == "Time to move up to Medium (+$45/month)"
    assert v["reasons"][0]["code"] == "cpu"
    assert "for 30 minutes" in v["reasons"][0]["text"] and "80%" in v["reasons"][0]["text"]


def test_disk_over_baseline_for_half_an_hour_moves_up():
    v = verdict([(0.2, 23, 100), (0.2, 30, 100)])
    assert v["level"] == "move" and v["reasons"][0]["code"] == "disk"
    assert "Small's 22 MB/s baseline" in v["reasons"][0]["text"]
    assert "Disk IO budget" in v["reasons"][0]["text"]
    watch = verdict([(0.2, 17, 100)])
    assert watch["level"] == "watch" and watch["headline"] == "Watch: disk reached 77% of its baseline"
    ops = verdict([(0.2, 2, 1100), (0.2, 2, 1300)])
    assert ops["level"] == "move" and "1,300 disk operations a second" in ops["reasons"][0]["text"]


def test_swap_and_memory():
    v = verdict([(0.2, 2, 100)], swap_used=300 * 1024 ** 2)
    assert v["level"] == "move" and v["reasons"][0]["code"] == "swap"
    assert "300 MB" in v["reasons"][0]["text"]
    some = verdict([(0.2, 2, 100)], swap_used=100 * 1024 ** 2)
    assert some["level"] == "watch" and some["headline"] == "Watch: swap reached 100 MB"
    low = verdict([(0.2, 2, 100)], mem_free=0.05)
    assert low["level"] == "move" and low["reasons"][0]["code"] == "memory"
    tight = verdict([(0.2, 2, 100)], mem_free=0.15)
    assert tight["level"] == "watch"
    promised = verdict([(0.2, 2, 100)], committed=1.2)
    assert promised["level"] == "watch" and promised["reasons"][0]["code"] == "committed"


def test_connections_near_the_limit_is_watch():
    rows = series(SUNDAY, dtime(9, 0), [(0.2, 2, 100)])
    rows[1]["pg"]["connections"] = 80
    v = dh.judge(SMALL, dh.summarize(rows, SMALL), 5)
    assert v["level"] == "watch" and v["headline"] == "Watch: 80 of 90 connections in use"


def test_church_count_against_the_size():
    near = verdict([(0.2, 2, 100)], churches=21)
    assert near["level"] == "watch" and near["headline"] == "Watch: 21 active churches, close to Small's ~25"
    over = verdict([(0.2, 2, 100)], churches=31)
    assert over["level"] == "watch" and "still fine" in over["reasons"][0]["text"]
    unmeasured = dh.judge(SMALL, dh.summarize([], SMALL), 31)
    assert unmeasured["level"] == "move" and unmeasured["measured"] is False
    assert unmeasured["headline"] == "Time to move up to Medium (+$45/month)"
    quiet = dh.judge(SMALL, dh.summarize([], SMALL), 3)
    assert quiet["level"] == "fine" and quiet["reasons"][0]["code"] == "unmeasured"
    unknown = dh.judge(SMALL, None, None)
    assert unknown["level"] == "fine"
    medium = dh.judge(dh.size_of("medium"), dh.summarize([], dh.size_of("medium")), 31)
    assert medium["level"] == "fine"
    assert dh.judge(dh.size_of("2xl"), None, 900)["level"] == "fine"   # no top to pass


def test_at_most_two_reasons_and_move_first():
    v = verdict([(0.6, 17, 100), (0.6, 17, 100)], churches=22, swap_used=400 * 1024 ** 2)
    assert v["level"] == "move" and len(v["reasons"]) == 2
    assert v["reasons"][0]["level"] == "move"


def test_the_biggest_size_points_at_a_read_replica():
    big = dh.size_of("4xl")
    v = dh.judge(big, dh.summarize(series(SUNDAY, dtime(9, 0), [(0.9, 2, 100), (0.9, 2, 100)]), big), 5)
    assert v["level"] == "move" and v["next"] is None
    assert v["headline"] == "Time to grow past 4XL: ask Supabase about a read replica"
    nxt = dh.judge(dh.size_of("large"), dh.summarize(
        series(SUNDAY, dtime(9, 0), [(0.9, 2, 100), (0.9, 2, 100)]), dh.size_of("large")), 5)
    assert nxt["headline"] == "Time to move up to XL (+$99/month)"


def test_words_never_name_the_builder():
    v = verdict([(0.72, 30, 100), (0.8, 30, 150)], swap_used=400 * 1024 ** 2)
    words = " ".join([v["headline"]] + [r["text"] for r in v["reasons"]]).lower()
    for bad in ("github", "claude", "builder", "pull request"):
        assert bad not in words


def test_tell_once_when_it_turns():
    move = {"level": "move", "headline": "Time to move up to Medium (+$45/month)"}
    assert dh.should_tell(move, None)
    assert dh.should_tell(move, {"level": "watch", "headline": "Watch: CPU reached 60%"})
    assert not dh.should_tell(move, dict(move))
    assert dh.should_tell(move, {"level": "move", "headline": "Time to move up to Large (+$51/month)"})
    assert not dh.should_tell({"level": "watch", "headline": "Watch"}, None)
    title, body = dh.alert_words({**move, "reasons": [{"text": "x" * 300}]})
    assert title == "Database: time to move up to Medium (+$45/month)"
    assert len(title) <= 90 and len(body) <= 220


# ─── Once a slot, on many server copies ─────────────────────────────────

@pytest.fixture
def feed(monkeypatch):
    seen = {"n": 0}

    async def fake_read(client):
        seen["n"] += 1
        return dh.reading_from(dh.parse_prometheus(FEED), "abcref"), None
    monkeypatch.setattr(dh, "read_metrics", fake_read)
    return seen


def test_a_slot_is_read_once(db, feed):
    now = et(SUNDAY, 9, 2).astimezone(timezone.utc)

    async def two_copies():
        return await asyncio.gather(dh.tick(now), dh.tick(now))
    a, b = run(two_copies())
    taken = [x["reading"]["taken"] for x in (a, b)]
    assert sorted(taken) == [False, True]
    assert feed["n"] == 1
    assert len(db.samples) == 1
    row = db.samples[0]
    assert row["slot"] == dh._z(et(SUNDAY, 9, 0)) and row["kind"] == "sunday"
    assert row["metrics"]["mem_total"] == 2.05e9 and row["pg"]["max_connections"] == 90
    assert "top_wal" not in row["pg"]           # only the last reading of the window
    run(dh.tick(et(SUNDAY, 9, 7).astimezone(timezone.utc)))
    assert len(db.samples) == 1 and feed["n"] == 1


def test_the_last_reading_of_sunday_has_the_top_writers(db, feed):
    run(dh.tick(et(SUNDAY, 13, 0).astimezone(timezone.utc)))
    assert db.samples[0]["pg"]["top_wal"][0]["calls"] == 9


def test_nothing_is_read_outside_the_windows(db, feed):
    db.weeks.append({"week": "2026-11-15", "level": "fine", "headline": "Fine at Small", "told_at": None})
    run(dh.tick(et(date(2026, 11, 19), 9, 0).astimezone(timezone.utc)))
    assert db.samples == [] and feed["n"] == 0


def test_an_unread_feed_is_kept_as_a_problem(db, monkeypatch):
    async def down(client):
        return None, "Supabase's metrics answered 503."
    monkeypatch.setattr(dh, "read_metrics", down)
    run(dh.tick(et(SUNDAY, 9, 0).astimezone(timezone.utc)))
    row = db.samples[0]
    assert row["metrics"] is None and row["problem"].startswith("Supabase's metrics answered 503")
    assert row["pg"]["connections"] == 20


def test_switch_off_reads_and_writes_nothing(db, feed, monkeypatch):
    monkeypatch.setenv("DB_HEALTH_CHECK", "off")
    assert run(dh.tick(et(SUNDAY, 9, 0).astimezone(timezone.utc))) == {"skipped": "off"}
    assert db.calls == [] and feed["n"] == 0


def test_without_the_migration_it_stays_quiet(db, feed):
    db.missing = True
    out = run(dh.tick(et(SUNDAY, 9, 0).astimezone(timezone.utc)))
    assert "error" not in out and feed["n"] == 0
    calls = len(db.calls)
    assert run(dh.tick(et(SUNDAY, 9, 15).astimezone(timezone.utc))) == {"skipped": "not set up"}
    assert len(db.calls) == calls


# ─── Monday's report ────────────────────────────────────────────────────

@pytest.fixture
def alerts(monkeypatch):
    raised: list = []

    async def fake_raise(c, **kw):
        raised.append(kw)
        return "pushed"
    monkeypatch.setattr(dev_alerts, "raise_alert", fake_raise)
    return raised


def _hot_week(db):
    db.samples = [dict(r, created_at=r["taken_at"]) for r in
                  series(SUNDAY, dtime(9, 0), [(0.75, 2, 100), (0.8, 2, 100)])]


def test_monday_writes_the_week_once_and_tells_once(db, alerts, monkeypatch):
    monkeypatch.setattr(dh, "_now", lambda: et(date(2026, 11, 23), 8, 0).astimezone(timezone.utc))
    _hot_week(db)
    monday = et(date(2026, 11, 23), 8, 0).astimezone(timezone.utc)
    out = run(dh.tick(monday))
    assert out["report"]["written"] and out["report"]["level"] == "move"
    assert out["report"]["told"] == "pushed"
    assert len(db.weeks) == 1
    week = db.weeks[0]
    assert week["week"] == "2026-11-22" and week["size"] == "small" and week["churches"] == 2
    assert week["headline"] == "Time to move up to Medium (+$45/month)" and week["told_at"]
    assert alerts == [{"source": "database", "kind": "move_up", "key": "db-health:2026-11-22:medium",
                       "level": "warn", "title": "Database: time to move up to Medium (+$45/month)",
                       "body": alerts[0]["body"], "nav": "studio:platform-database"}]
    assert "CPU ran at 70% or more" in alerts[0]["body"]
    # The next ticks, and another copy that never saw it, don't write or tell again.
    run(dh.tick(monday + timedelta(minutes=5)))
    dh.forget()
    run(dh.tick(monday + timedelta(minutes=10)))
    assert len(db.weeks) == 1 and len(alerts) == 1


def test_no_alert_while_last_week_already_said_the_same(db, alerts, monkeypatch):
    monkeypatch.setattr(dh, "_now", lambda: et(date(2026, 11, 23), 8, 0).astimezone(timezone.utc))
    _hot_week(db)
    db.weeks.append({"week": "2026-11-15", "level": "move", "told_at": "2026-11-16T13:00:00Z",
                     "headline": "Time to move up to Medium (+$45/month)"})
    out = run(dh.tick(et(date(2026, 11, 23), 8, 5).astimezone(timezone.utc)))
    assert out["report"]["written"] and out["report"]["told"] is None
    assert alerts == []


def test_a_fine_week_is_written_without_an_alert(db, alerts, monkeypatch):
    monkeypatch.setattr(dh, "_now", lambda: et(date(2026, 11, 23), 8, 0).astimezone(timezone.utc))
    db.samples = [dict(r, created_at=r["taken_at"]) for r in series(SUNDAY, dtime(9, 0), [(0.2, 2, 100)])]
    out = run(dh.tick(et(date(2026, 11, 23), 8, 0).astimezone(timezone.utc)))
    assert out["report"]["level"] == "fine" and alerts == []
    assert db.weeks[0]["headline"] == "Fine at Small"


def test_the_report_removes_old_readings(db, alerts, monkeypatch):
    now = et(date(2026, 11, 23), 8, 0).astimezone(timezone.utc)
    monkeypatch.setattr(dh, "_now", lambda: now)
    db.samples = [{"slot": "2026-09-01T13:00:00Z", "kind": "sunday", "taken_at": "2026-09-01T13:00:00Z",
                   "created_at": "2026-09-01T13:00:00Z", "metrics": {}, "pg": {}}]
    run(dh.tick(now))
    assert db.samples == []


# ─── The card ───────────────────────────────────────────────────────────

def _client(email=PLATFORM_OWNER_EMAIL):
    app = FastAPI()
    app.include_router(dh.router)
    if email is not None:
        app.dependency_overrides[require_user] = lambda: SimpleNamespace(id="u-1", email=email, role="authenticated")
    return TestClient(app)


def test_every_route_is_owner_only(db):
    anonymous, tenant = _client(None), _client("tenant@example.com")
    for method, url in (("get", "/platform/db-health/summary"), ("post", "/platform/db-health/check")):
        assert getattr(anonymous, method)(url).status_code in (401, 403), url
        assert getattr(tenant, method)(url).status_code == 403, url
    assert db.calls == []


def test_card_says_not_set_up_without_the_migration(db):
    db.missing = True
    r = _client().get("/platform/db-health/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["set_up"] is False and body["migration"] == dh.MIGRATION
    assert body["size"]["key"] == "small" and body["churches"]["count"] == 2
    assert [s["key"] for s in body["sizes"] if s["current"]] == ["small"]
    c = _client().post("/platform/db-health/check")
    assert c.status_code == 503 and "isn't set up" in c.json()["detail"]


def test_card_switched_off(db, monkeypatch):
    monkeypatch.setenv("DB_HEALTH_CHECK", "off")
    assert _client().get("/platform/db-health/summary").json() == {"enabled": False}
    assert _client().post("/platform/db-health/check").status_code == 409
    assert db.calls == []


def test_card_shows_last_sundays_peak_and_verdict(db, monkeypatch):
    now = et(date(2026, 11, 23), 10, 0).astimezone(timezone.utc)
    monkeypatch.setattr(dh, "_now", lambda: now)
    db.samples = series(WEDNESDAY, dtime(10, 45), [(0.1, 1, 50)], kind="weekday") + \
        series(SUNDAY, dtime(9, 0), [(0.3, 5, 100), (0.62, 9, 200)])
    for r in db.samples:
        r["metrics"]["mem_total"] = 2.0 * GIB
    db.samples[-1]["pg"]["top_wal"] = [{"query": "insert into sol_news_items ...", "calls": 9, "wal_bytes": 5000}]
    db.samples[-1]["pg"]["top_temp"] = []
    db.weeks.append({"week": "2026-11-15", "level": "fine", "headline": "Fine at Small", "told_at": None})
    body = _client().get("/platform/db-health/summary").json()
    assert body["set_up"] and body["size"]["key"] == "small" and body["size"]["source"] == "measured"
    assert body["week"]["sunday"] == "2026-11-22" and body["week"]["so_far"] is False
    assert body["week"]["sunday_readings"] == 3 and body["week"]["weekday_readings"] == 2
    assert body["verdict"]["headline"] == "Watch: CPU reached 62%"
    assert body["peak"]["cpu"]["weekday"] == pytest.approx(0.1)
    assert body["peak"]["memory"]["total"] == 2.0 * GIB
    assert body["churches"] == {"count": 2, "range": "up to ~25", "top": 25}
    assert body["tops"]["wal"][0]["query"].startswith("insert into sol_news_items")
    assert body["history"] == [{"week": "2026-11-15", "level": "fine", "headline": "Fine at Small", "told": False}]
    assert body["latest"]["kind"] == "sunday"
    assert "Disk IO balance" in body["disk_note"]


def test_check_now_reads_once_a_minute_and_never_counts_toward_the_week(db, feed, monkeypatch):
    now = et(date(2026, 11, 24), 15, 0).astimezone(timezone.utc)
    monkeypatch.setattr(dh, "_now", lambda: now)
    client = _client()
    r = client.post("/platform/db-health/check")
    assert r.status_code == 200, r.text
    assert db.samples[0]["kind"] == "manual" and db.samples[0]["pg"]["top_wal"]
    body = r.json()
    assert body["latest"]["kind"] == "manual" and body["latest"]["memory"]["total"] == 2.05e9
    assert body["week"]["readings"] == 0
    again = client.post("/platform/db-health/check")
    assert again.status_code == 429 and feed["n"] == 1


def test_count_churches_counts_only_churches(db):
    assert dh.count_churches() == 2
    path = next(p for k, p, _ in db.calls if k == "get_all")
    assert "comp_tier.not.is.null" in path and "subscription_status.in.(active,trialing,past_due)" in path


# ─── The wiring ─────────────────────────────────────────────────────────

def test_the_database_alert_source_and_its_page():
    assert dev_alerts.SOURCES["database"] == "push"
    assert "database" in dev_alerts.SERVER_SOURCES
    assert dev_alerts._nav("studio:platform-database") == "studio:platform-database"
    assert dev_alerts.Settings().sources["database"] == "push"


def test_the_job_and_the_router_are_registered():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("db_health", _db_health.tick), "cron", minute="*/5"' in src
    assert "app.include_router(db_health_router)" in src
    assert src.index("app.include_router(db_health_router)") < src.index("app.include_router(public_site_router")
