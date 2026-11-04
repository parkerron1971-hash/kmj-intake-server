"""
test_chief_keep_warm.py — a no-reply read keeps Chief's cached brief alive while the business is active (2026-10-07).

30 days: 37 re-writes of Chief's whole ~100k-token brief came 1-4 h after the
business's previous message, at ~35c each, because the cached copy lives an
hour after its last use. A read costs a tenth of the input price and resets
that hour. The ping re-sends what the last call had in front of its 1-hour
breakpoints, asks for no reply, and stops when the business goes quiet or
when a ping finds no copy to read.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_keep_warm as kw

ONE_H = {"type": "ephemeral", "ttl": "1h"}


def _payload():
    return {
        "model": "claude-sonnet-5-5", "max_tokens": 1600, "stream": True,
        "output_config": {"effort": "low"},
        "tools": [{"name": "get_contacts"}, {"name": "show_view"}],
        "system": [
            {"type": "text", "text": "UNIVERSAL", "cache_control": ONE_H},
            {"type": "text", "text": "MANUAL", "cache_control": ONE_H},
            {"type": "text", "text": "STATE", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "THIS TURN"},
        ],
        "messages": [{"role": "user", "content": "what's overdue?"}],
    }


def test_the_ping_is_the_cached_prefix_with_no_reply():
    ping = kw.ping_payload(_payload())
    assert ping["max_tokens"] == 0 and "stream" not in ping
    assert [b["text"] for b in ping["system"]] == ["UNIVERSAL", "MANUAL"]
    assert ping["tools"] == _payload()["tools"] and ping["output_config"] == {"effort": "low"}
    assert ping["model"] == "claude-sonnet-5-5"
    assert ping["messages"] == [{"role": "user", "content": "."}]


def test_nothing_cached_for_an_hour_means_no_ping():
    p = _payload()
    for b in p["system"]:
        b.pop("cache_control", None)
    assert kw.ping_payload(p) is None
    assert kw.ping_payload({"system": "one string"}) is None


def test_off_and_no_business_schedule_nothing(monkeypatch):
    monkeypatch.setenv("CHIEF_KEEP_WARM", "off")
    assert kw.remember("biz", _payload()) is False
    monkeypatch.setenv("CHIEF_KEEP_WARM", "on")
    assert kw.remember(None, _payload()) is False
    assert kw.remember("biz", _payload()) is False   # no running loop


class _Resp:
    def __init__(self, read, wrote, status=200):
        self.status_code = status
        self._u = {"cache_read_input_tokens": read, "cache_creation_input_tokens": wrote}

    def json(self):
        return {"usage": self._u, "content": [], "stop_reason": "max_tokens"}


def _wire(monkeypatch, responses, every=0.01, window=1.0):
    import llm_call
    import spend_guard
    sent = []

    async def apost(client, payload, **kw_):
        sent.append((payload, kw_))
        return responses.pop(0) if responses else _Resp(95000, 0)
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(kw, "every_s", lambda: every)
    monkeypatch.setattr(kw, "window_s", lambda: window)
    # These pin the in-process chain: the table isn't there.
    monkeypatch.setattr(kw, "record", lambda *a, **k: False)
    kw._tasks.clear()
    return sent


def test_pings_repeat_while_the_business_is_active(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=30)

    async def run():
        assert kw.remember("biz-1", _payload(), {"anthropic-beta": "extended-cache-ttl-2025-04-11"})
        for _ in range(200):
            if len(sent) >= 2:
                break
            await asyncio.sleep(0.02)
        kw._tasks["biz-1"].cancel()
    asyncio.run(run())
    assert len(sent) >= 2
    payload, opts = sent[0]
    assert payload["max_tokens"] == 0 and opts["units"] == 0 and opts["task"] == "chief_keep_warm"
    assert opts["business_id"] == "biz-1"
    assert opts["extra_headers"] == {"anthropic-beta": "extended-cache-ttl-2025-04-11"}


def test_pings_stop_once_the_window_has_passed(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=0.001)

    async def run():
        kw.remember("biz-1b", _payload())
        for _ in range(200):
            if "biz-1b" not in kw._tasks:
                break
            await asyncio.sleep(0.02)
    asyncio.run(run())
    assert "biz-1b" not in kw._tasks
    assert sent == []


def test_a_ping_that_writes_stops_the_pings(monkeypatch):
    sent = _wire(monkeypatch, [_Resp(0, 95000)], every=0.01, window=5)

    async def run():
        kw.remember("biz-2", _payload())
        await asyncio.sleep(0.1)
    asyncio.run(run())
    assert len(sent) == 1


def test_a_refused_ping_stops_the_pings(monkeypatch):
    sent = _wire(monkeypatch, [_Resp(0, 0, status=400)], every=0.01, window=5)

    async def run():
        kw.remember("biz-3", _payload())
        await asyncio.sleep(0.1)
    asyncio.run(run())
    assert len(sent) == 1


def test_a_new_message_restarts_the_clock(monkeypatch):
    _wire(monkeypatch, [], every=10, window=50)

    async def run():
        kw.remember("biz-4", _payload())
        first = kw._tasks["biz-4"]
        kw.remember("biz-4", _payload())
        await asyncio.sleep(0)
        assert first.cancelled() or first.done()
        assert kw._tasks["biz-4"] is not first
        kw._tasks["biz-4"].cancel()
    asyncio.run(run())


class _ChiefResp:
    status_code = 200
    text = ""

    def json(self):
        return {"stop_reason": "end_turn", "model": "claude-sonnet-5-5",
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_read_input_tokens": 90000, "cache_creation_input_tokens": 0},
                "content": [{"type": "text", "text": "ok"}]}


def _chief_call(monkeypatch, role):
    import chief_of_staff as cos
    import llm_call
    import spend_guard
    seen = []

    async def apost(client, payload, **k):
        return _ChiefResp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(kw, "remember", lambda biz, payload, headers=None: seen.append((biz, payload, headers)) or True)
    system = ("U " * 600 + "[[CHIEF_GLOBAL_SPLIT]]" + "M " * 900 + "[[CHIEF_CACHE_SPLIT]]"
              + "STATE A\n\nSTATE B " * 300 + "[[CHIEF_TURN_SPLIT]]" + "TURN")
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                 business_id="biz-c", stable_tools=True, timing_role=role))
    return seen


def test_the_owners_main_call_schedules_the_pings(monkeypatch):
    seen = _chief_call(monkeypatch, "chief_main")
    assert len(seen) == 1 and seen[0][0] == "biz-c"
    assert kw.ping_payload(seen[0][1]) is not None


def test_auxiliary_calls_do_not(monkeypatch):
    assert _chief_call(monkeypatch, "chief_auxiliary") == []


# ── Daily users stay warm for a day (2026-10-07) ─────────────────────
# Simulated on 30 days of real call times: cold starts plus pings cost
# $37.27 with no keep-warm, $25.52 at 4 h and $18.56 at 24 h. A business
# that uses Chief most days keeps its brief warm through the night.

def _rows(*days):
    return [{"created_at": f"{d}T10:00:00Z"} for d in days]


def test_a_daily_user_gets_the_long_window(monkeypatch):
    import sb_clients
    kw._daily.clear()
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: _rows("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-07"))
    assert kw.window_for("daily-biz") == kw.daily_window_s() == 24 * 3600


def test_two_days_of_use_keeps_the_short_window(monkeypatch):
    import sb_clients
    kw._daily.clear()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: _rows("2026-10-06", "2026-10-07"))
    assert kw.window_for("new-biz") == kw.window_s() == 4 * 3600


def test_a_failed_read_keeps_the_short_window(monkeypatch):
    import sb_clients
    kw._daily.clear()

    def boom(path):
        raise RuntimeError("no database")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert kw.window_for("biz-x") == kw.window_s()


def test_daily_use_is_read_once_a_day(monkeypatch):
    import sb_clients
    kw._daily.clear()
    calls = []

    def get(path):
        calls.append(path)
        return _rows("2026-10-05", "2026-10-06", "2026-10-07")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    kw.window_for("biz-y")
    kw.window_for("biz-y")
    assert len(calls) == 1
    assert "endpoint=eq./chief/backend" in calls[0] and "business_id=eq.biz-y" in calls[0]


def test_a_daily_users_pings_outlast_the_short_window(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=0.001)
    monkeypatch.setattr(kw, "window_for", lambda b: 30.0)

    async def run():
        kw.remember("biz-daily", _payload())
        for _ in range(200):
            if len(sent) >= 2:
                break
            await asyncio.sleep(0.02)
        kw._tasks["biz-daily"].cancel()
    asyncio.run(run())
    assert len(sent) >= 2


# ── Held in the database (2026-11-03) ────────────────────────────────
# 475 deploys in 30 days, a median of 26 minutes apart, and the pings were
# tasks in the web process that every deploy killed before the first one
# (due at 55 minutes) went out: 33 pings in 30 days, and 4 of the 5
# messages 1-4 h after the last one were full re-writes. The web now writes
# the ping to chief_keep_warm and the worker sends it, so a deploy costs a
# tick, not the copy. And the copy is gone after 00:00 UTC (all 3 pings
# that crossed it paid for a whole new copy), so no ping crosses it.

import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from urllib.parse import parse_qsl  # noqa: E402

T0 = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)
_real_record = kw.record


def _when(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class _Table:
    """chief_keep_warm as PostgREST would answer the calls the module makes."""

    TIMES = ("touched_at", "last_call_at", "window_ends_at", "stopped_at", "pinging_at")

    def __init__(self):
        import threading
        self.rows = {}
        self.calls = []
        self.lock = threading.Lock()   # one statement at a time, as Postgres locks the row
        # (method, path) -> True for a call that fails: the sb_clients helpers
        # then answer None, never [] (a failure is not "no rows").
        self.fail = lambda method, path: False

    @classmethod
    def _cond(cls, row, col, cond):
        op, _, val = cond.partition(".")
        have = row.get(col)
        if op == "is":
            return have is None
        if col in cls.TIMES:
            if have is None:
                return False
            return _when(have) == _when(val) if op == "eq" else _when(have) < _when(val)
        return str(have) == val

    @classmethod
    def _match(cls, row, filters):
        for col, cond in filters:
            if col == "or":
                parts = [p.split(".", 1) for p in cond.strip("()").split(",")]
                if not any(cls._cond(row, c, rest) for c, rest in parts):
                    return False
            elif not cls._cond(row, col, cond):
                return False
        return True

    @staticmethod
    def _parse(path):
        assert path.startswith("/chief_keep_warm"), path
        q = dict(parse_qsl(path.partition("?")[2], keep_blank_values=True))
        select = q.pop("select", "*").split(",")
        for k in ("order", "limit", "on_conflict"):
            q.pop(k, None)
        return list(q.items()), select

    @staticmethod
    def _shape(row, select):
        return dict(row) if select == ["*"] else {k: row.get(k) for k in select}

    def get(self, path, **_):
        self.calls.append(("GET", path))
        if self.fail("GET", path):
            return None
        filters, select = self._parse(path)
        rows = sorted((r for r in self.rows.values() if self._match(r, filters)),
                      key=lambda r: _when(r["touched_at"]))
        return [self._shape(r, select) for r in rows]

    def patch(self, path, body):
        self.calls.append(("PATCH", path, dict(body)))
        if self.fail("PATCH", path):
            return None
        filters, select = self._parse(path)
        out = []
        with self.lock:
            for r in self.rows.values():
                if self._match(r, filters):
                    r.update(body)
                    out.append(self._shape(r, select))
        return out

    def post(self, path, body, prefer=None, redact=False):
        self.calls.append(("POST", path, dict(body), prefer, redact))
        if self.fail("POST", path):
            return None
        _, select = self._parse(path)
        row = self.rows.setdefault(body["business_id"], {})
        row.update(body)
        return [self._shape(row, select)]


def _db(monkeypatch):
    import sb_clients
    t = _Table()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", t.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", t.patch)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", t.post)
    monkeypatch.setattr(kw, "table_state", lambda: True)
    monkeypatch.setattr(kw, "window_for", lambda b: 4 * 3600.0)
    kw._stored.clear()
    kw._latest.clear()
    return t


def _row(biz="biz-w", touched=T0, ends=None, ping=None):
    ping = ping or kw.ping_payload(_payload())
    return {"business_id": biz, "payload": kw.ping_text(ping), "headers": {"anthropic-beta": "x"},
            "prefix_hash": "0" * 64, "last_call_at": touched.isoformat(),
            "touched_at": touched.isoformat(),
            "window_ends_at": (ends or touched + timedelta(hours=4)).isoformat(),
            "pings": 0, "pinging_at": None, "stopped_at": None, "stopped_reason": None}


def test_the_ping_is_kept_as_the_text_it_was_sent_as():
    """jsonb would sort a tool schema's keys, and a schema with its keys
    moved is another prompt to the cache: the ping would pay to write a
    copy instead of reading one."""
    ping = kw.ping_payload(_payload())
    ping["tools"] = [{"name": "z_tool", "input_schema": {"type": "object",
                                                         "properties": {"zeta": {}, "alpha": {}}}}]
    back = json.loads(kw.ping_text(ping))
    assert json.dumps(back) == json.dumps(ping)
    assert list(back["tools"][0]["input_schema"]["properties"]) == ["zeta", "alpha"]


def test_record_hands_the_ping_to_the_worker(monkeypatch):
    t = _db(monkeypatch)
    ping = kw.ping_payload(_payload())
    assert kw.record("biz-r", ping, {"anthropic-beta": "extended-cache-ttl-2025-04-11"}) is True
    row = t.rows["biz-r"]
    assert json.loads(row["payload"]) == ping
    assert row["headers"] == {"anthropic-beta": "extended-cache-ttl-2025-04-11"}
    assert row["touched_at"] == row["last_call_at"] and row["stopped_at"] is None and row["pings"] == 0
    assert _when(row["window_ends_at"]) - _when(row["last_call_at"]) == timedelta(hours=4)
    post = [c for c in t.calls if c[0] == "POST"][0]
    assert "on_conflict=business_id" in post[1] and "select=business_id" in post[1]
    assert "merge-duplicates" in post[3] and post[4] is True   # the brief never reaches a log


def test_the_brief_is_sent_again_only_when_it_changed(monkeypatch):
    t = _db(monkeypatch)
    ping = kw.ping_payload(_payload())
    kw.record("biz-s", ping, {})
    t.rows["biz-s"].update(stopped_at="2026-11-03T10:00:00+00:00", stopped_reason="window")
    kw.record("biz-s", ping, {})
    assert [c[0] for c in t.calls] == ["POST", "PATCH"]
    assert "payload" not in t.calls[1][2] and "prefix_hash=eq." in t.calls[1][1]
    assert t.rows["biz-s"]["stopped_at"] is None            # a new message restarts the chain
    moved = kw.ping_payload(_payload())
    moved["system"][1]["text"] = "MANUAL, CHANGED"
    kw.record("biz-s", moved, {})
    assert t.calls[-1][0] == "POST" and json.loads(t.rows["biz-s"]["payload"]) == moved


def test_a_row_another_process_rewrote_gets_the_whole_brief(monkeypatch):
    t = _db(monkeypatch)
    ping = kw.ping_payload(_payload())
    kw.record("biz-o", ping, {})
    t.rows["biz-o"]["prefix_hash"] = "f" * 64                # another deploy's brief
    kw.record("biz-o", ping, {})
    assert [c[0] for c in t.calls] == ["POST", "PATCH", "POST"]


def test_an_older_call_never_replaces_a_newer_brief(monkeypatch):
    t = _db(monkeypatch)
    kw._latest["biz-n"] = 7
    assert kw.record("biz-n", kw.ping_payload(_payload()), {}, seq=6) is True
    assert t.calls == []


def test_no_table_means_the_web_pings_as_before(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=30)
    monkeypatch.setattr(kw, "record", _real_record)
    monkeypatch.setattr(kw, "table_state", lambda: False)

    async def run():
        kw.remember("biz-old", _payload())
        for _ in range(200):
            if sent:
                break
            await asyncio.sleep(0.02)
        kw._tasks["biz-old"].cancel()
    asyncio.run(run())
    assert sent


def test_a_recorded_brief_is_not_pinged_by_the_web(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=30)
    monkeypatch.setattr(kw, "record", lambda *a, **k: True)

    async def run():
        kw.remember("biz-rec", _payload())
        for _ in range(20):
            if "biz-rec" not in kw._tasks:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
    asyncio.run(run())
    assert "biz-rec" not in kw._tasks and sent == []


def test_the_webs_pings_stop_at_midnight_utc(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=30)
    monkeypatch.setattr(kw, "crosses_midnight", lambda a, b: True)

    async def run():
        kw.remember("biz-mid", _payload())
        for _ in range(100):
            if "biz-mid" not in kw._tasks:
                break
            await asyncio.sleep(0.02)
    asyncio.run(run())
    assert sent == [] and "biz-mid" not in kw._tasks


def test_crossing_midnight_is_by_the_utc_date():
    late = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)
    assert kw.crosses_midnight(late, late + timedelta(minutes=50))
    assert not kw.crosses_midnight(late, late + timedelta(minutes=20))
    eastern = timezone(timedelta(hours=-5))
    # 19:30 and 20:10 Eastern are 00:30 and 01:10 UTC: the same UTC day
    assert not kw.crosses_midnight(datetime(2026, 11, 3, 19, 30, tzinfo=eastern),
                                   datetime(2026, 11, 3, 20, 10, tzinfo=eastern))


def test_what_happens_to_a_due_copy():
    due = T0 + timedelta(minutes=51)
    assert kw.verdict(_row(), due) == "ping"
    assert kw.verdict(_row(), T0 + timedelta(minutes=56)) == "lapsed"
    late = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)
    assert kw.verdict(_row(touched=late), late + timedelta(minutes=51)) == "midnight"
    assert kw.verdict(_row(ends=T0 + timedelta(minutes=30)), due) == "window"
    assert kw.verdict({"touched_at": None, "window_ends_at": None}, due) == "lapsed"


def test_the_ping_interval_never_outruns_the_late_line(monkeypatch):
    monkeypatch.setenv("CHIEF_KEEP_WARM_EVERY_MIN", "59")
    assert kw.every_s() + 2 * kw.TICK_MIN * 60 <= kw.LATE_S   # two looks before the line
    monkeypatch.delenv("CHIEF_KEEP_WARM_EVERY_MIN")
    assert kw.every_s() == 50 * 60


def _worker(monkeypatch, rows, outcomes=None, now=None):
    t = _db(monkeypatch)
    for r in rows:
        t.rows[r["business_id"]] = r
    sent = []

    async def send(biz, ping, headers):
        sent.append((biz, ping, headers))
        return (outcomes or {}).get(biz, "read")
    monkeypatch.setattr(kw, "send_ping", send)
    at = now or T0 + timedelta(minutes=51)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at
    monkeypatch.setattr(kw, "datetime", _Clock)
    return t, sent


def test_the_worker_pings_a_due_copy_with_the_brief_as_sent(monkeypatch):
    ping = kw.ping_payload(_payload())
    t, sent = _worker(monkeypatch, [_row("biz-a", ping=ping),
                                    _row("biz-fresh", touched=T0 + timedelta(minutes=30))])
    assert asyncio.run(kw.tick()) == {"read": 1}
    assert sent == [("biz-a", ping, {"anthropic-beta": "x"})]
    assert json.dumps(sent[0][1]) == json.dumps(ping)        # same bytes, same cache key
    row = t.rows["biz-a"]
    assert _when(row["touched_at"]) == T0 + timedelta(minutes=51) and row["pings"] == 1
    assert row["pinging_at"] is None                         # the hold let go
    assert t.rows["biz-fresh"]["pings"] == 0                 # not due yet


def test_the_last_use_moves_only_once_the_ping_has_read(monkeypatch):
    """While the ping is out the row says when the copy was really last
    used, so a worker that dies mid-ping (it deploys as often as the web)
    never leaves a later use the API didn't see."""
    t, _ = _worker(monkeypatch, [_row("biz-z")])
    during = {}

    async def send(biz, ping, headers):
        during.update(t.rows[biz])
        return "read"
    monkeypatch.setattr(kw, "send_ping", send)
    asyncio.run(kw.tick())
    assert _when(during["touched_at"]) == T0 and during["pinging_at"]
    assert _when(t.rows["biz-z"]["touched_at"]) == T0 + timedelta(minutes=51)


def test_a_ping_that_writes_ends_the_chain(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-b")], {"biz-b": "wrote"})
    assert asyncio.run(kw.tick()) == {"wrote": 1}
    assert t.rows["biz-b"]["stopped_reason"] == "wrote" and t.rows["biz-b"]["stopped_at"]
    assert t.rows["biz-b"]["pinging_at"] is None


def test_a_refused_ping_ends_the_chain(monkeypatch):
    t, _ = _worker(monkeypatch, [_row("biz-c")], {"biz-c": "refused"})
    asyncio.run(kw.tick())
    assert t.rows["biz-c"]["stopped_reason"] == "refused"


def test_a_busy_api_gets_one_more_try_while_the_copy_lasts(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-d")], {"biz-d": "busy"})
    assert asyncio.run(kw.tick()) == {"busy": 1}
    row = t.rows["biz-d"]
    assert row["stopped_at"] is None and _when(row["touched_at"]) == T0 and row["pings"] == 0
    assert row["pinging_at"] is None


def test_no_ping_crosses_midnight_utc(monkeypatch):
    late = datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)
    t, sent = _worker(monkeypatch, [_row("biz-e", touched=late, ends=late + timedelta(hours=24))],
                      now=late + timedelta(minutes=51))
    assert asyncio.run(kw.tick()) == {"midnight": 1}
    assert sent == [] and t.rows["biz-e"]["stopped_reason"] == "midnight"


def test_a_copy_too_old_to_trust_is_never_pinged(monkeypatch):
    """A worker down past the hour (a long deploy) must not ping a copy
    that may be gone: the ping would pay for a whole new one."""
    t, sent = _worker(monkeypatch, [_row("biz-f")], now=T0 + timedelta(minutes=58))
    assert asyncio.run(kw.tick()) == {"lapsed": 1}
    assert sent == [] and t.rows["biz-f"]["stopped_reason"] == "lapsed"


def test_the_window_still_ends_the_pings(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-g", ends=T0 + timedelta(minutes=40))])
    assert asyncio.run(kw.tick()) == {"window": 1}
    assert sent == []


def test_a_message_during_the_ping_keeps_its_own_chain(monkeypatch):
    """The ping found the old copy gone, but a message landed meanwhile
    and wrote its own: the stop is for the chain the ping claimed, and
    the message's chain lives on."""
    t, _ = _worker(monkeypatch, [_row("biz-h")])
    fresh = (T0 + timedelta(minutes=52)).isoformat()

    async def send(biz, ping, headers):
        t.rows[biz].update(touched_at=fresh, last_call_at=fresh, pings=0, pinging_at=None)
        return "wrote"
    monkeypatch.setattr(kw, "send_ping", send)
    asyncio.run(kw.tick())
    assert t.rows["biz-h"]["stopped_at"] is None and t.rows["biz-h"]["touched_at"] == fresh


def test_two_workers_ping_a_copy_once(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-i")])

    async def both():
        return await asyncio.gather(kw.tick(), kw.tick())
    asyncio.run(both())
    assert len(sent) == 1


def test_another_workers_live_hold_is_left_alone_and_a_dead_one_runs_out(monkeypatch):
    held = _row("biz-k")
    held["pinging_at"] = (T0 + timedelta(minutes=50, seconds=30)).isoformat()   # 30 s ago
    t, sent = _worker(monkeypatch, [held])
    assert asyncio.run(kw.tick()) == {"taken": 1} and sent == []
    held["pinging_at"] = (T0 + timedelta(minutes=48)).isoformat()                # 3 min ago: it died
    assert asyncio.run(kw.tick()) == {"read": 1} and len(sent) == 1


# A failed call answers None in sb_clients, never []: none of these may be
# read as "no row" or "nothing due".

def test_a_failed_read_of_the_due_copies_is_not_nothing_due(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-l")])
    t.fail = lambda method, path: method == "GET"
    assert asyncio.run(kw.tick()) == {"unread": 1} and sent == []
    assert t.rows["biz-l"]["stopped_at"] is None


def test_a_failed_hold_sends_no_ping(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-m")])
    t.fail = lambda method, path: method == "PATCH"
    assert asyncio.run(kw.tick()) == {"error": 1} and sent == []
    assert _when(t.rows["biz-m"]["touched_at"]) == T0


def test_a_read_that_was_not_noted_brings_the_next_ping_early_never_late(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-p")])
    t.fail = lambda method, path: method == "PATCH" and "pinging_at=eq." in path
    assert asyncio.run(kw.tick()) == {"read": 1}
    assert _when(t.rows["biz-p"]["touched_at"]) == T0        # the older use: early, never late
    t.fail = lambda method, path: False
    t2, sent2 = _worker(monkeypatch, [t.rows["biz-p"]], now=T0 + timedelta(minutes=53))
    assert asyncio.run(kw.tick()) == {"read": 1} and len(sent2) == 1


def test_a_busy_ping_whose_let_go_failed_tries_again_once_the_hold_runs_out(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-q")], {"biz-q": "busy"})
    t.fail = lambda method, path: method == "PATCH" and "pinging_at=eq." in path
    assert asyncio.run(kw.tick()) == {"busy": 1}
    assert t.rows["biz-q"]["pinging_at"]                     # still held
    t2, sent2 = _worker(monkeypatch, [t.rows["biz-q"]], now=T0 + timedelta(minutes=53))
    assert asyncio.run(kw.tick()) == {"read": 1} and len(sent2) == 1


def test_a_failed_stop_is_said_and_tried_again(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-u", ends=T0 + timedelta(minutes=40))])
    t.fail = lambda method, path: method == "PATCH"
    assert asyncio.run(kw.tick()) == {"error": 1}
    t.fail = lambda method, path: False
    assert asyncio.run(kw.tick()) == {"window": 1} and sent == []


def test_a_failed_record_falls_back_to_the_webs_own_pings(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=30)
    t = _db(monkeypatch)
    monkeypatch.setattr(kw, "record", _real_record)
    t.fail = lambda method, path: True
    assert kw.record("biz-v", kw.ping_payload(_payload()), {}) is False

    async def run():
        kw.remember("biz-v", _payload())
        for _ in range(200):
            if sent:
                break
            await asyncio.sleep(0.02)
        kw._tasks["biz-v"].cancel()
    asyncio.run(run())
    assert sent and "biz-v" not in t.rows


def test_nothing_runs_without_the_table_or_when_off(monkeypatch):
    t, sent = _worker(monkeypatch, [_row("biz-j")])
    monkeypatch.setattr(kw, "table_state", lambda: False)
    assert asyncio.run(kw.tick()) == {} and sent == [] and t.calls == []
    monkeypatch.setattr(kw, "table_state", lambda: True)
    monkeypatch.setenv("CHIEF_KEEP_WARM", "off")
    assert asyncio.run(kw.tick()) == {} and sent == []


def test_table_state_remembers_yes_and_asks_again_after_no(monkeypatch):
    import sb_clients
    kw._table.clear()
    answers = {"/chief_keep_warm": None, "/businesses": [{"id": "b"}]}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: answers[p.split("?")[0]])
    assert kw.table_state() is False
    answers["/chief_keep_warm"] = []
    assert kw.table_state() is False                        # remembered for 10 minutes
    kw._table["missing_until"] = 0
    assert kw.table_state() is True
    answers["/chief_keep_warm"] = None
    assert kw.table_state() is True                         # once yes, always yes
    kw._table.clear()
    answers["/businesses"] = None
    assert kw.table_state() is None                         # the probe itself failed
    kw._table.clear()


def test_the_worker_job_is_registered_and_leader_gated():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("chief_keep_warm", _keep_warm.tick)' in src and 'id="chief_keep_warm"' in src
