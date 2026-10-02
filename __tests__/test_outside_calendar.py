"""Outside calendars: a private iCal link's busy times block booking slots.

What these pin (outside_calendar.py, calendar_feeds_router.py):
  - the SSRF guard: https only (webcal → https), no private / loopback /
    link-local / metadata / IPv6-wrapped addresses, re-checked on every
    redirect, pinned connection, 5 MB cap, VCALENDAR only;
  - parsing: RRULE, EXDATE, TRANSP:TRANSPARENT, STATUS:CANCELLED, all-day,
    TZID and floating times; only times leave the parser;
  - the booking paths: a slot overlapping a busy block is not offered and
    cannot be booked; an all-day block closes the day, at any capacity;
  - the sync is idempotent (upsert + sweep of other runs), keeps good
    blocks when a write fails, backs off, and one claim at a time;
  - the feed URL never reaches the client, and the feature says "not set
    up" instead of failing before the migration is applied.
"""
from __future__ import annotations

import gzip
import pathlib
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

import outside_calendar as oc
from availability import BusinessAvailability, TimeRange, WeeklyAvailability
from availability_engine import compute_slots
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-2222-4333-8444-555555555555"
OWNER = "user-owner"
FEED_URL = "https://calendar.google.com/calendar/ical/me%40example.com/private-0123456789abcdef9f3a/basic.ics"


# ─── Sample calendar ─────────────────────────────────────────────────

VTZ = b"""BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:STANDARD
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
END:DAYLIGHT
END:VTIMEZONE
"""


def _ics(*events: bytes) -> bytes:
    return (b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n" + VTZ
            + b"".join(events) + b"END:VCALENDAR\r\n")


WEEKLY = b"""BEGIN:VEVENT
UID:weekly-1
DTSTART;TZID=America/New_York:20261001T100000
DTEND;TZID=America/New_York:20261001T110000
RRULE:FREQ=WEEKLY;COUNT=4
EXDATE;TZID=America/New_York:20261008T100000
SUMMARY:Private session with Dana
LOCATION:12 Secret Lane
DESCRIPTION:Dana's notes
END:VEVENT
"""
FREE = b"""BEGIN:VEVENT
UID:free-1
DTSTART:20261002T150000Z
DTEND:20261002T160000Z
TRANSP:TRANSPARENT
END:VEVENT
"""
CANCELLED = b"""BEGIN:VEVENT
UID:cancel-1
DTSTART:20261003T150000Z
DTEND:20261003T160000Z
STATUS:CANCELLED
END:VEVENT
"""
ALL_DAY = b"""BEGIN:VEVENT
UID:allday-1
DTSTART;VALUE=DATE:20261005
DTEND;VALUE=DATE:20261006
END:VEVENT
"""
FLOATING = b"""BEGIN:VEVENT
UID:float-1
DTSTART:20261006T090000
DTEND:20261006T093000
END:VEVENT
"""
OUTLOOK_FREE = b"""BEGIN:VEVENT
UID:ms-free
DTSTART:20261009T150000Z
DTEND:20261009T160000Z
X-MICROSOFT-CDO-BUSYSTATUS:FREE
END:VEVENT
"""

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _parse(ics: bytes, tz="America/Chicago", **kw):
    return oc.parse_busy_blocks(ics, tz_name=tz, now=NOW, **kw)


# ─── Parsing ─────────────────────────────────────────────────────────

def test_parse_expands_rrule_and_honours_exdate():
    starts = [b["starts_at"] for b in _parse(_ics(WEEKLY))]
    # 4 weekly occurrences, 10am New York (14:00Z in October), minus the
    # EXDATE on Oct 8.
    assert starts == ["2026-10-01T14:00:00Z", "2026-10-15T14:00:00Z", "2026-10-22T14:00:00Z"]


def test_parse_skips_free_and_cancelled_events():
    blocks = _parse(_ics(FREE, CANCELLED, OUTLOOK_FREE))
    assert blocks == []


def test_parse_all_day_blocks_the_whole_local_day():
    [b] = _parse(_ics(ALL_DAY))
    assert b["all_day"] is True
    # Midnight to midnight in the business zone (Chicago, CDT = UTC-5).
    assert (b["starts_at"], b["ends_at"]) == ("2026-10-05T05:00:00Z", "2026-10-06T05:00:00Z")


def test_parse_floating_time_is_read_in_the_business_zone():
    [b] = _parse(_ics(FLOATING), tz="America/Chicago")
    assert b["starts_at"] == "2026-10-06T14:00:00Z"
    [b_utc] = _parse(_ics(FLOATING), tz="UTC")
    assert b_utc["starts_at"] == "2026-10-06T09:00:00Z"


def test_parse_keeps_only_times_never_details():
    for b in _parse(_ics(WEEKLY)):
        assert set(b) == {"uid_hash", "starts_at", "ends_at", "all_day"}
        assert "weekly-1" not in b["uid_hash"]           # hashed, not the raw UID
    text = repr(_parse(_ics(WEEKLY)))
    for secret in ("Dana", "Secret Lane", "notes"):
        assert secret not in text


def test_parse_honours_the_horizon_and_the_block_cap():
    daily = b"""BEGIN:VEVENT
UID:daily
DTSTART:20261001T160000Z
DTEND:20261001T170000Z
RRULE:FREQ=DAILY
END:VEVENT
"""
    blocks = _parse(_ics(daily))
    assert len(blocks) == 59            # Oct 1 .. Nov 28, inside now+60d
    assert len(_parse(_ics(daily), max_blocks=5)) == 5


def test_parse_refuses_garbage_in_plain_words():
    with pytest.raises(oc.FeedError) as e:
        oc.parse_busy_blocks(b"BEGIN:VCALENDAR\r\nthis is not ical", tz_name="UTC", now=NOW)
    assert "calendar" in e.value.message.lower()


# ─── SSRF guard: URL rules ───────────────────────────────────────────

def test_webcal_becomes_https():
    assert oc.normalize_feed_url("webcal://p01-caldav.icloud.com/published/2/ABC") \
        == "https://p01-caldav.icloud.com/published/2/ABC"


@pytest.mark.parametrize("url", [
    "http://calendar.google.com/x.ics",          # not https
    "ftp://calendar.google.com/x.ics",
    "file:///etc/passwd",
    "https://user:pw@calendar.google.com/x.ics",  # credentials
    "https://calendar.google.com:8443/x.ics",     # non-default port
    "https://127.0.0.1/x.ics",                    # IP literal
    "https://[::1]/x.ics",
    "https://169.254.169.254/latest/meta-data/",
    "https://localhost/x.ics",
    "https://metadata.google.internal/computeMetadata/v1/",
    "https://printer.local/x.ics",
    "not a url",
])
def test_bad_urls_are_refused(url):
    with pytest.raises(oc.FeedError):
        oc.normalize_feed_url(url)


@pytest.mark.parametrize("addr", [
    "10.0.0.5", "172.16.3.4", "192.168.1.1", "127.0.0.1", "0.0.0.0",
    "169.254.169.254",          # cloud metadata (link-local)
    "100.100.100.200",          # Alibaba metadata (CGNAT)
    "100.64.0.1", "224.0.0.1", "240.0.0.1", "255.255.255.255",
    "::1", "::", "fe80::1", "fc00::1", "fd00:ec2::254", "ff02::1",
    "::ffff:127.0.0.1",         # IPv4-mapped
    "::ffff:10.0.0.1",
    "64:ff9b::a00:1",           # NAT64 → 10.0.0.1
    "2002:a00:1::1",            # 6to4 → 10.0.0.1
    "not-an-ip",
])
def test_private_and_special_addresses_are_blocked(addr):
    assert oc.address_blocked(addr) is True


@pytest.mark.parametrize("addr", ["8.8.8.8", "142.250.72.14", "2607:f8b0:4004:800::200e"])
def test_public_addresses_pass(addr):
    assert oc.address_blocked(addr) is False


# ─── SSRF guard: the fetch ───────────────────────────────────────────

def _r(status, content=b"", headers=None):
    return (status, content, headers or {})


class _Net:
    """Fake DNS + HTTP. `dns` maps host → addresses; `routes` maps
    (connected address, Host header, path) → httpx.Response."""

    def __init__(self, monkeypatch, dns, routes):
        self.dns, self.routes, self.requests = dns, routes, []
        monkeypatch.setattr(oc, "_resolve_host", self._resolve)
        monkeypatch.setattr(oc, "_make_client", self._client)

    def _resolve(self, host):
        if host not in self.dns:
            import socket
            raise socket.gaierror("nx")
        return self.dns[host]

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.url.host, request.headers.get("host"), request.url.path)
        if key not in self.routes:
            return httpx.Response(599)
        status, content, headers = self.routes[key]
        # A real transport hands back an unread stream; so does this.
        return httpx.Response(status, headers=headers, stream=httpx.ByteStream(content))

    def _client(self):
        return httpx.Client(transport=httpx.MockTransport(self._handler),
                            follow_redirects=False)


GOOD_ICS = _ics(WEEKLY)


def test_fetch_pins_the_checked_address_and_keeps_the_hostname(monkeypatch):
    net = _Net(monkeypatch, {"calendar.google.com": ["142.250.72.14"]}, {
        ("142.250.72.14", "calendar.google.com", "/cal/basic.ics"):
            _r(200, content=GOOD_ICS),
    })
    assert oc.fetch_feed("webcal://calendar.google.com/cal/basic.ics") == GOOD_ICS
    [req] = net.requests
    assert req.url.host == "142.250.72.14"                 # connected to what we checked
    assert req.headers["host"] == "calendar.google.com"     # routed by name
    assert req.extensions.get("sni_hostname") == "calendar.google.com"  # TLS by name


def test_fetch_refuses_a_host_that_resolves_private(monkeypatch):
    net = _Net(monkeypatch, {"evil.example.com": ["10.0.0.5"]}, {})
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://evil.example.com/cal.ics")
    assert e.value.message == oc.MSG_PRIVATE
    assert net.requests == []                                # never connected


def test_fetch_refuses_a_host_with_any_private_answer(monkeypatch):
    """A public AND a private answer is what DNS rebinding looks like."""
    _Net(monkeypatch, {"rebind.example.com": ["8.8.8.8", "169.254.169.254"]}, {})
    with pytest.raises(oc.FeedError):
        oc.fetch_feed("https://rebind.example.com/cal.ics")


def test_fetch_refuses_a_redirect_to_a_private_address(monkeypatch):
    net = _Net(monkeypatch, {
        "cal.example.com": ["93.184.216.34"],
        "internal.example.com": ["192.168.0.10"],
    }, {
        ("93.184.216.34", "cal.example.com", "/feed.ics"):
            _r(302, headers={"location": "https://internal.example.com/admin"}),
    })
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/feed.ics")
    assert e.value.message == oc.MSG_PRIVATE
    assert len(net.requests) == 1                            # the private hop never happened


def test_fetch_refuses_a_redirect_to_a_metadata_ip_literal(monkeypatch):
    _Net(monkeypatch, {"cal.example.com": ["93.184.216.34"]}, {
        ("93.184.216.34", "cal.example.com", "/feed.ics"):
            _r(301, headers={"location": "https://169.254.169.254/latest/meta-data/"}),
    })
    with pytest.raises(oc.FeedError):
        oc.fetch_feed("https://cal.example.com/feed.ics")


def test_fetch_refuses_a_redirect_down_to_http(monkeypatch):
    _Net(monkeypatch, {"cal.example.com": ["93.184.216.34"]}, {
        ("93.184.216.34", "cal.example.com", "/feed.ics"):
            _r(302, headers={"location": "http://cal.example.com/feed.ics"}),
    })
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/feed.ics")
    assert e.value.message == oc.MSG_NOT_HTTPS


def test_fetch_follows_a_safe_redirect_and_stops_after_three(monkeypatch):
    routes = {("93.184.216.34", "cal.example.com", f"/r{i}"):
              _r(302, headers={"location": f"/r{i + 1}"}) for i in range(5)}
    _Net(monkeypatch, {"cal.example.com": ["93.184.216.34"]}, routes)
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/r0")
    assert e.value.message == oc.MSG_REDIRECTS

    routes[("93.184.216.34", "cal.example.com", "/r2")] = _r(200, content=GOOD_ICS)
    assert oc.fetch_feed("https://cal.example.com/r0") == GOOD_ICS


def test_fetch_caps_size_even_when_compressed(monkeypatch):
    bomb = gzip.compress(b"BEGIN:VCALENDAR\r\n" + b"X" * (oc.MAX_BYTES + 10))
    _Net(monkeypatch, {"cal.example.com": ["93.184.216.34"]}, {
        ("93.184.216.34", "cal.example.com", "/big.ics"):
            _r(200, content=bomb, headers={"content-encoding": "gzip"}),
        ("93.184.216.34", "cal.example.com", "/small.ics"):
            _r(200, content=gzip.compress(GOOD_ICS),
                           headers={"content-encoding": "gzip"}),
    })
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/big.ics")
    assert e.value.message == oc.MSG_TOO_BIG
    assert oc.fetch_feed("https://cal.example.com/small.ics") == GOOD_ICS


def test_fetch_requires_a_vcalendar_and_explains_http_errors(monkeypatch):
    _Net(monkeypatch, {"cal.example.com": ["93.184.216.34"]}, {
        ("93.184.216.34", "cal.example.com", "/page"):
            _r(200, content=b"<html>Sign in</html>"),
        ("93.184.216.34", "cal.example.com", "/gone.ics"): _r(404),
        ("93.184.216.34", "cal.example.com", "/login.ics"): _r(401),
    })
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/page")
    assert e.value.message == oc.MSG_NOT_ICS
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/gone.ics")
    assert e.value.message == oc.MSG_GONE
    with pytest.raises(oc.FeedError) as e:
        oc.fetch_feed("https://cal.example.com/login.ics")
    assert e.value.message == oc.MSG_AUTH


def test_errors_and_masks_never_carry_the_secret():
    masked = oc.mask_url(FEED_URL)
    assert masked == "calendar.google.com ····9f3a"
    assert "private-0123" not in masked
    for msg in (oc.MSG_PRIVATE, oc.MSG_NOT_ICS, oc.MSG_GONE, oc.MSG_AUTH, oc.MSG_TOO_BIG):
        assert "http" not in msg.replace("https://", "")


# ─── A tiny PostgREST for the two tables ─────────────────────────────

class FakeDB:
    def __init__(self, missing=False):
        self.feeds: dict = {}
        self.blocks: dict = {}
        self.missing = missing
        self.fail_upsert = False
        self.calls: list = []

    @staticmethod
    def _q(path):
        parts = urlsplit(path)
        return parts.path.lstrip("/"), dict(parse_qsl(parts.query))

    @staticmethod
    def _ts(v):
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

    def _block_match(self, row, q):
        for k in ("business_id", "feed_id"):
            if k in q and row[k] != q[k][3:]:
                return False
        if "starts_at" in q and not self._ts(row["starts_at"]) < self._ts(q["starts_at"][3:]):
            return False
        if "ends_at" in q and not self._ts(row["ends_at"]) > self._ts(q["ends_at"][3:]):
            return False
        return True

    def rest(self, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        table, q = self._q(path)
        if self.missing:
            return 404, None
        if table == "calendar_feeds":
            return self._feeds(method, q, body)
        if table == "calendar_busy_blocks":
            return self._blocks(method, q, body)
        raise AssertionError(path)

    def _feeds(self, method, q, body):
        def match(r):
            if "id" in q and r["id"] != q["id"][3:]:
                return False
            if "business_id" in q and r["business_id"] != q["business_id"][3:]:
                return False
            return True
        if method == "GET":
            rows = [dict(r) for r in self.feeds.values() if match(r)]
            if "or" in q and "next_sync_at" in q["or"]:
                cutoff = self._ts(q["or"].split("next_sync_at.lte.")[1].rstrip(")"))
                rows = [r for r in rows if not r.get("next_sync_at")
                        or self._ts(r["next_sync_at"]) <= cutoff]
            return 200, rows
        if method == "POST":
            if any(r["business_id"] == body["business_id"] and r["url_hash"] == body["url_hash"]
                   for r in self.feeds.values()):
                return 409, None
            row = {"id": str(uuid.uuid4()), "busy_count": 0, "failure_count": 0,
                   "last_synced_at": None, "last_error": None, "next_sync_at": None,
                   "sync_lock_until": None, "created_at": "2026-09-30T12:00:00Z", **body}
            self.feeds[row["id"]] = row
            return 201, [dict(row)]
        if method == "PATCH":
            rows = [r for r in self.feeds.values() if match(r)]
            if "or" in q:           # the claim
                cutoff = self._ts(q["or"].split("sync_lock_until.lt.")[1].rstrip(")"))
                rows = [r for r in rows if not r.get("sync_lock_until")
                        or self._ts(r["sync_lock_until"]) < cutoff]
            for r in rows:
                r.update(body)
            return 200, [dict(r) for r in rows]
        if method == "DELETE":
            for k in [k for k, r in self.feeds.items() if match(r)]:
                del self.feeds[k]
            return 204, None
        raise AssertionError(method)

    def _blocks(self, method, q, body):
        if method == "GET":
            return 200, [dict(r) for r in self.blocks.values() if self._block_match(r, q)]
        if method == "POST":
            if self.fail_upsert:
                return 500, None
            for row in body:
                self.blocks[(row["feed_id"], row["uid_hash"], row["starts_at"])] = dict(row)
            return 201, None
        if method == "DELETE":
            if "or" in q:           # sweep of other runs
                run = q["or"].split("sync_run.neq.")[1].rstrip(")")
                doomed = [k for k, r in self.blocks.items()
                          if r["feed_id"] == q["feed_id"][3:] and r.get("sync_run") != run]
            else:
                doomed = [k for k, r in self.blocks.items() if self._block_match(r, q)]
            for k in doomed:
                del self.blocks[k]
            return 204, None
        raise AssertionError(method)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(oc, "_rest", fake.rest)
    monkeypatch.setattr(oc, "_absent_until", 0.0)
    monkeypatch.setattr(oc, "business_timezone", lambda biz: "America/New_York")
    return fake


def _feed(db, url=FEED_URL, **extra):
    row = {"id": str(uuid.uuid4()), "business_id": BIZ, "label": "Google Calendar",
           "url": url, "url_hash": oc.url_hash(url), "provider": "google",
           "status": "pending", "busy_count": 0, "failure_count": 0,
           "last_synced_at": None, "last_error": None, "next_sync_at": None,
           "sync_lock_until": None, "created_at": "2026-09-30T12:00:00Z", **extra}
    db.feeds[row["id"]] = row
    return row


# ─── Sync ────────────────────────────────────────────────────────────

def test_sync_is_idempotent_and_sweeps_what_disappeared(db, monkeypatch):
    feed = _feed(db)
    ics = {"body": _ics(WEEKLY, ALL_DAY)}
    monkeypatch.setattr(oc, "fetch_feed", lambda url: ics["body"])

    assert oc.sync_feed(feed, now=NOW) == {"ok": True, "busy_count": 4}
    first = sorted((k[1], k[2]) for k in db.blocks)
    assert len(first) == 4
    assert db.feeds[feed["id"]]["status"] == "ok"
    assert db.feeds[feed["id"]]["sync_lock_until"] is None          # claim released

    assert oc.sync_feed(db.feeds[feed["id"]], now=NOW)["ok"]         # same feed again
    assert sorted((k[1], k[2]) for k in db.blocks) == first          # no duplicates

    ics["body"] = _ics(WEEKLY)                                       # the all-day event was deleted
    oc.sync_feed(db.feeds[feed["id"]], now=NOW)
    assert len(db.blocks) == 3
    assert not any(r["all_day"] for r in db.blocks.values())
    assert db.feeds[feed["id"]]["busy_count"] == 3


def test_a_failed_write_keeps_the_last_good_blocks_and_backs_off(db, monkeypatch):
    feed = _feed(db)
    monkeypatch.setattr(oc, "fetch_feed", lambda url: _ics(WEEKLY))
    oc.sync_feed(feed, now=NOW)
    assert len(db.blocks) == 3

    db.fail_upsert = True
    out = oc.sync_feed(db.feeds[feed["id"]], now=NOW)
    assert out["ok"] is False
    assert len(db.blocks) == 3                                       # nothing swept
    row = db.feeds[feed["id"]]
    assert row["status"] == "error" and row["failure_count"] == 1
    assert row["last_error"] == oc.MSG_SAVE


def test_a_broken_feed_records_plain_words_and_backs_off(db, monkeypatch):
    feed = _feed(db, failure_count=2)

    def boom(url):
        raise oc.FeedError(oc.MSG_GONE)
    monkeypatch.setattr(oc, "fetch_feed", boom)
    out = oc.sync_feed(feed, now=NOW)
    assert out == {"ok": False, "error": oc.MSG_GONE}
    row = db.feeds[feed["id"]]
    assert row["last_error"] == oc.MSG_GONE and row["failure_count"] == 3
    assert row["next_sync_at"] == oc._iso_z(NOW + timedelta(minutes=60))
    assert [oc.backoff_minutes(n) for n in (1, 2, 3, 4, 5, 6, 9)] == [15, 30, 60, 120, 240, 360, 360]


def test_one_sync_at_a_time_per_feed(db, monkeypatch):
    feed = _feed(db, sync_lock_until=oc._iso_z(NOW + timedelta(seconds=60)))
    monkeypatch.setattr(oc, "fetch_feed", lambda url: pytest.fail("fetched while claimed"))
    assert oc.sync_feed(feed, now=NOW) == {"ok": False, "skipped": "already syncing"}


def test_the_scheduler_tick_never_raises(db, monkeypatch):
    _feed(db)
    _feed(db, url=FEED_URL + "?b")

    def explode(feed, now=None, **kw):
        raise RuntimeError("anything at all")
    monkeypatch.setattr(oc, "sync_feed", explode)
    assert oc.sync_due(now=NOW) == 2
    import asyncio
    asyncio.run(oc.sync_due_tick())


def test_not_set_up_before_the_migration(monkeypatch):
    fake = FakeDB(missing=True)
    monkeypatch.setattr(oc, "_absent_until", 0.0)

    def rest(method, path, body=None, prefer=None):
        status, data = fake.rest(method, path, body, prefer)
        oc._mark_absent()                        # what the real _rest does on a 404
        return status, data
    monkeypatch.setattr(oc, "_rest", rest)
    assert oc.list_feeds(BIZ)["available"] is False
    calls = len(fake.calls)
    assert oc.busy_blocks_between(BIZ, NOW, NOW + timedelta(days=1)) == []
    assert len(fake.calls) == calls              # remembered; no hammering
    with pytest.raises(oc.NotSetUp):
        oc.connect_feed(BIZ, FEED_URL)


# ─── The booking paths ───────────────────────────────────────────────

def _nyc(**kw):
    base = dict(timezone="America/New_York",
                weekly=WeeklyAvailability(mon=[TimeRange(start="08:00", end="17:00")]),
                slot_granularity_min=60, lead_time_min=0)
    base.update(kw)
    return BusinessAvailability(**base)


def _mon_slots(av, busy):
    return [s["start_local"] for s in compute_slots(
        availability=av, existing_bookings=[], offering_duration_min=60,
        from_date=date(2026, 9, 14), to_date=date(2026, 9, 14),
        now=datetime(2026, 9, 14, 6, 0, tzinfo=ZoneInfo("America/New_York")),
        busy_blocks=busy)]


def test_a_slot_overlapping_a_busy_block_is_not_offered():
    # 10:30-11:15 Eastern busy = 14:30-15:15Z.
    busy = [{"starts_at": "2026-09-14T14:30:00Z", "ends_at": "2026-09-14T15:15:00Z"}]
    starts = _mon_slots(_nyc(), busy)
    assert "2026-09-14T10:00:00" not in starts and "2026-09-14T11:00:00" not in starts
    assert "2026-09-14T09:00:00" in starts and "2026-09-14T12:00:00" in starts


def test_busy_ignores_capacity_and_all_day_closes_the_day():
    busy = [{"starts_at": "2026-09-14T14:00:00Z", "ends_at": "2026-09-14T15:00:00Z"}]
    assert "2026-09-14T10:00:00" not in _mon_slots(_nyc(concurrent_capacity=3), busy)
    all_day = [{"starts_at": "2026-09-14T04:00:00Z", "ends_at": "2026-09-15T04:00:00Z",
                "all_day": True}]
    assert _mon_slots(_nyc(concurrent_capacity=3), all_day) == []
    assert len(_mon_slots(_nyc(), [])) == 9       # nothing connected: unchanged


def _busy_1430(db):
    """One outside busy block, Mon Sep 14 2026 14:30-15:15Z."""
    feed = _feed(db)
    db.blocks[(feed["id"], "h", "2026-09-14T14:30:00Z")] = {
        "business_id": BIZ, "feed_id": feed["id"], "uid_hash": "h",
        "starts_at": "2026-09-14T14:30:00Z", "ends_at": "2026-09-14T15:15:00Z", "all_day": False}
    return feed


def test_a_client_cannot_book_a_busy_time(db, monkeypatch):
    import booking_widget_router as bw
    import sb_clients
    _busy_1430(db)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])  # no bookings at all
    assert bw._check_public_slot_available(BIZ, "2026-09-14T14:00:00Z", 60) is False
    assert bw._check_public_slot_available(BIZ, "2026-09-14T15:15:00Z", 60) is True  # touches only
    assert bw._check_public_slot_available("other-biz", "2026-09-14T14:00:00Z", 60) is True


def test_every_client_booking_door_uses_the_public_guard():
    """book-anon (which the agent site and Site Concierge ride) and the
    known-customer book both refuse outside-busy times."""
    import inspect
    import agent_site
    import booking_widget_router as bw
    for fn in (bw.book_anon, bw.book):
        src = inspect.getsource(fn)
        assert "_check_public_slot_available(" in src, fn.__name__
        assert "_check_slot_available(" not in src.replace("_check_public_slot_available(", ""), fn.__name__
    assert "book_anon(" in inspect.getsource(agent_site.walkin_book)


# ─── Practitioner-made bookings go through, and say so ───────────────
#
# Someone moving in from Calendly already has "Jane, Tue 3pm" on the
# Google Calendar they linked, because Calendly wrote it there. Entering
# Jane here (by hand, through Chief, or as a weekly series) must not
# clash with Jane.

def test_the_practitioner_guard_ignores_outside_busy(db, monkeypatch):
    import booking_widget_router as bw
    import sb_clients
    _busy_1430(db)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    assert bw._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 60) is True


def _chief_booking_env(monkeypatch):
    import booking_widget_router as bw
    import chief_booking_actions as cba
    import sb_clients
    created = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])   # no bookings
    monkeypatch.setattr(bw, "_bookings_module", lambda b: {"id": "mod1", "archetype_params": {}})
    monkeypatch.setattr(bw, "_maybe_denormalize_offering",
                        lambda b, m, oid, qp, data: {**data, "duration_min_at_booking": 60})
    monkeypatch.setattr(bw, "_create_appointment",
                        lambda b, m, data, created_by="x": created.append(data) or {"id": "bk1", "data": data})
    monkeypatch.setattr(cba, "_resolve_offering", lambda b, a: {"offering": {
        "id": "off1", "name": "Cut", "duration_min": 60, "is_active": True}})
    monkeypatch.setattr(cba, "_resolve_contact", lambda b, a: {"contact": {"id": "c1", "name": "Jane"}})
    return cba, created


def test_chief_books_over_an_outside_busy_time_and_says_so(db, monkeypatch):
    _busy_1430(db)
    cba, created = _chief_booking_env(monkeypatch)
    out = cba._create_booking_sync({"id": BIZ}, {
        "contact_id": "c1", "offering_id": "off1", "appointment_at": "2026-09-14T14:30:00Z"})
    assert created, "the practitioner's own booking must go through"
    assert out["result"] and out["label"]
    assert "also busy on your other calendar" in out["result"]
    assert out["outside_calendar_busy"] is True

    quiet = cba._create_booking_sync({"id": BIZ}, {
        "contact_id": "c1", "offering_id": "off1", "appointment_at": "2026-09-14T17:00:00Z"})
    assert "other calendar" not in quiet["result"] and quiet["outside_calendar_busy"] is False


def test_chief_reschedules_onto_an_outside_busy_time_and_says_so(db, monkeypatch):
    import booking_widget_router as bw
    import sb_clients
    _busy_1430(db)
    cba, _ = _chief_booking_env(monkeypatch)
    monkeypatch.setattr(bw, "_mirror_booking_session", lambda b, e: None)
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active",
        "data": {"appointment_at": "2026-09-14T18:00:00Z", "customer_name": "Jane",
                 "duration_min_at_booking": 60}}})
    moved = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: moved.append(p) or [{"id": "bk1"}])
    out = cba._reschedule_booking_sync({"id": BIZ}, {
        "booking_id": "bk1", "new_appointment_at": "2026-09-14T14:30:00Z"})
    assert any("module_entries" in p for p in moved)
    assert out["label"] == "Jane"
    assert out["result"].startswith("moved to") and "also busy on your other calendar" in out["result"]


def test_a_weekly_series_books_busy_weeks_and_names_them(db, monkeypatch):
    from datetime import time as _t
    import booking_series as bs
    cba, created = _chief_booking_env(monkeypatch)
    from availability import BusinessAvailability
    monkeypatch.setattr(bs, "_business_availability",
                        lambda b: (BusinessAvailability(), "UTC"))
    monkeypatch.setattr(bs, "_series_entries",
                        lambda b, s, active_only=True, from_iso=None: [])
    feed = _feed(db)
    # Busy the 2nd and 3rd Tuesdays at 15:00Z (Calendly already wrote Jane there).
    for day in ("2027-04-13", "2027-04-20"):
        db.blocks[(feed["id"], "jane", f"{day}T15:00:00Z")] = {
            "business_id": BIZ, "feed_id": feed["id"], "uid_hash": "jane",
            "starts_at": f"{day}T15:00:00Z", "ends_at": f"{day}T16:00:00Z", "all_day": False}
    res = bs.create_series(BIZ, offering={"id": "off1", "name": "Cut", "duration_min": 60},
                           contact=None, customer_name="Jane", weekday=1, at=_t(15, 0),
                           tz_name="UTC", start_from=date(2027, 4, 6), count=4)
    assert res["ok"] and len(res["booked"]) == 4 and res["skipped"] == []
    assert len(created) == 4
    assert res["also_busy_elsewhere"] == ["Apr 13", "Apr 20"]
    assert res["summary"] == ("4 booked. Heads up: Apr 13 and Apr 20 are also busy "
                              "on your other calendar.")

    single = bs.create_series(BIZ, offering={"id": "off1", "name": "Cut", "duration_min": 60},
                              contact=None, customer_name="Jane", weekday=1, at=_t(15, 0),
                              tz_name="UTC", start_from=date(2027, 4, 13), count=1)
    assert single["summary"] == "1 booked. Heads up: that time is also busy on your other calendar."


def test_the_public_slot_endpoint_subtracts_busy_times(db, monkeypatch):
    import availability_router as ar
    import sb_clients
    feed = _feed(db)
    db.blocks[(feed["id"], "h", "2027-03-01T15:00:00Z")] = {
        "business_id": BIZ, "feed_id": feed["id"], "uid_hash": "h",
        "starts_at": "2027-03-01T15:00:00Z", "ends_at": "2027-03-01T16:00:00Z", "all_day": False}
    settings = {"availability": {"timezone": "UTC", "slot_granularity_min": 60,
                                 "weekly": {"mon": [{"start": "14:00", "end": "17:00"}]}}}

    def get(path):
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": OWNER, "settings": settings}]
        if path.startswith("/offerings"):
            return [{"id": "off-1", "duration_min": 60}]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(ar, "_rate_limit", lambda *a: None)
    app = FastAPI()
    app.include_router(ar.router)
    r = TestClient(app).get(f"/availability/{BIZ}/slots",
                            params={"offering_id": "off-1", "from": "2027-03-01", "to": "2027-03-01"})
    assert r.status_code == 200, r.text
    starts = [s["start_utc"][:16] for s in r.json()["slots"]]
    assert starts == ["2027-03-01T14:00", "2027-03-01T16:00"]


# ─── Endpoints: owner-gated, secret stays secret ─────────────────────

@pytest.fixture
def api(db, monkeypatch):
    import calendar_feeds_router as cfr
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [{"owner_id": OWNER}] if path.startswith("/businesses") else [])
    app = FastAPI()
    app.include_router(cfr.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(
        id=OWNER, email="o@example.com", role="authenticated")
    return app


def test_connect_list_sync_remove_and_the_url_never_comes_back(api, db, monkeypatch):
    monkeypatch.setattr(oc, "fetch_feed", lambda url: _ics(WEEKLY))
    c = TestClient(api)
    r = c.post(f"/availability/{BIZ}/calendar-feeds", json={"url": FEED_URL.replace("https", "webcal", 1)})
    assert r.status_code == 200, r.text
    feed = r.json()["feed"]
    assert feed["masked_url"] == "calendar.google.com ····9f3a"
    assert feed["provider"] == "google" and feed["status"] == "ok" and feed["busy_count"] == 3

    listed = c.get(f"/availability/{BIZ}/calendar-feeds")
    assert listed.status_code == 200 and listed.json()["available"] is True
    for resp in (r, listed):
        assert "private-0123456789abcdef" not in resp.text
        assert '"url"' not in resp.text

    dup = c.post(f"/availability/{BIZ}/calendar-feeds", json={"url": FEED_URL})
    assert dup.status_code == 409

    s = c.post(f"/availability/{BIZ}/calendar-feeds/{feed['id']}/sync")
    assert s.status_code == 200 and s.json()["sync"]["skipped"] == "just synced"

    blocks = c.get(f"/availability/{BIZ}/busy-blocks", params={"from": "2026-10-01", "to": "2026-10-31"})
    assert blocks.status_code == 200
    assert [b["starts_at"] for b in blocks.json()["blocks"]][0] == "2026-10-01T14:00:00Z"
    assert set(blocks.json()["blocks"][0]) == {"starts_at", "ends_at", "all_day"}

    d = c.delete(f"/availability/{BIZ}/calendar-feeds/{feed['id']}")
    assert d.status_code == 200
    assert db.feeds == {} and db.blocks == {}


def test_a_link_that_cannot_be_read_is_refused_and_not_saved(api, db, monkeypatch):
    def refuse(url):
        raise oc.FeedError(oc.MSG_PRIVATE, retryable=False)
    monkeypatch.setattr(oc, "fetch_feed", refuse)
    r = TestClient(api).post(f"/availability/{BIZ}/calendar-feeds", json={"url": FEED_URL})
    assert r.status_code == 400 and r.json()["detail"] == oc.MSG_PRIVATE
    assert db.feeds == {}


def test_every_route_is_owner_only(api, db):
    api.dependency_overrides[require_user] = lambda: AuthedUser(
        id="someone-else", email="x@example.com", role="authenticated")
    c = TestClient(api)
    feed = _feed(db)
    for method, path, kw in (
        ("get", f"/availability/{BIZ}/calendar-feeds", {}),
        ("post", f"/availability/{BIZ}/calendar-feeds", {"json": {"url": FEED_URL}}),
        ("post", f"/availability/{BIZ}/calendar-feeds/{feed['id']}/sync", {}),
        ("delete", f"/availability/{BIZ}/calendar-feeds/{feed['id']}", {}),
        ("get", f"/availability/{BIZ}/busy-blocks", {}),
    ):
        assert getattr(c, method)(path, **kw).status_code == 403, (method, path)
    assert feed["id"] in db.feeds


def test_ids_that_are_not_uuids_never_reach_a_query(api, db):
    c = TestClient(api)
    assert c.get("/availability/not-a-uuid&or=(x)/calendar-feeds").status_code == 404
    bad = c.delete(f"/availability/{BIZ}/calendar-feeds/x&or=(id.not.is.null)")
    assert bad.status_code == 404
    assert not any("or=(id" in path for _, path, _ in db.calls)


# ─── The older /public/booking/{slug} page (settings.booking) ────────

def _legacy_site(monkeypatch):
    import public_site
    booking = {"enabled": True, "available_days": [1, 2, 3, 4, 5, 6, 7],
               "hours": {"start": "09:00", "end": "17:00"}, "buffer_minutes": 0,
               "session_types": ["Cut"], "durations": {"Cut": 60}}

    async def sb(client, path):
        if path.startswith("/business_sites"):
            return [{"business_id": BIZ}]
        if path.startswith("/businesses"):
            return [{"name": "Shop", "settings": {"booking": booking}}]
        return []
    monkeypatch.setattr(public_site, "_sb", sb)
    monkeypatch.setattr(public_site, "_check_rate", lambda slug: True)
    return public_site


def test_the_older_booking_page_hides_and_refuses_busy_times(db, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    ps = _legacy_site(monkeypatch)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    feed = _feed(db)
    start, end = f"{tomorrow}T10:30:00Z", f"{tomorrow}T11:15:00Z"
    db.blocks[(feed["id"], "h", start)] = {
        "business_id": BIZ, "feed_id": feed["id"], "uid_hash": "h",
        "starts_at": start, "ends_at": end, "all_day": False}

    out = asyncio.run(ps.booking_slots("shop", days=2))
    day = next(d for d in out["slots"] if d["date"] == tomorrow.isoformat())
    assert "10:00" not in day["times"] and "11:00" not in day["times"]
    assert "09:00" in day["times"] and "12:00" in day["times"]

    req = ps.BookingSubmission(name="Dana", email="dana@example.com", session_type="Cut",
                               date=tomorrow.isoformat(), time="10:00")
    with pytest.raises(HTTPException) as e:
        asyncio.run(ps.booking_submit("shop", req))
    assert e.value.status_code == 409
