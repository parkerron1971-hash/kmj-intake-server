"""One calendar of everything that goes out (2026-10-09, the Reach plan's step 1).

GET /marketing/{business_id}/calendar?month=YYYY-MM: a business's desk posts
and its Outreach emails and texts in one month, on its own clock. A read that
fails is named, never an empty month.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import business_marketing as bm  # noqa: E402
import business_marketing_calendar as cal  # noqa: E402
import business_marketing_store as store  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
CHI = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc)


def run(x):
    return asyncio.run(x)


@pytest.fixture(autouse=True)
def no_offers(monkeypatch):
    monkeypatch.setattr(cal, "_offers", lambda bid, first, following: [])


def test_a_month_starts_at_the_business_local_midnight():
    first, start, end = cal.month_bounds("2026-11", CHI)
    assert first.isoformat() == "2026-11-01"
    assert start == datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)      # CDT: UTC-5
    assert end == datetime(2026, 12, 1, 6, 0, tzinfo=timezone.utc)        # CST after the change: UTC-6
    first, start, end = cal.month_bounds("2026-12", CHI)
    assert end == datetime(2027, 1, 1, 6, 0, tzinfo=timezone.utc)         # December runs into January
    for bad in ("2026-13", "2026-1", "26-10", "", "2026-10-01"):
        with pytest.raises(ValueError):
            cal.month_bounds(bad, CHI)


def campaign(status="running", start="2026-10-10T15:00:00+00:00", **over):
    return {"id": "11111111-2222-4333-8444-555555555555", "name": "Come back", "status": status, "start_at": start,
            "touches": [
                {"channel": "email", "offset_days": 0, "subject": "It has been a while", "body": "Hi {{first_name}}, " + "x" * 300,
                 "completed_at": "2026-10-10T15:05:00+00:00"},
                {"channel": "sms", "offset_days": 3, "body": "Open chairs Thursday {{link}}"},
                {"channel": "email", "offset_days": 9, "subject": "Last call", "body": "One more note."},
                {"channel": "email", "offset_days": 30, "subject": "Next month", "body": "Out of this month."},
            ], **over}


def test_each_touch_on_its_day_and_how_it_stands():
    _, start, end = cal.month_bounds("2026-10", CHI)
    items = cal.touch_items(campaign(), {0: 41, 1: 12}, start, end, NOW)
    assert [(i["kind"], i["touch"], i["state"], i["sent"]) for i in items] == [
        ("email", 0, "sent", 41), ("text", 1, "sending", 12), ("email", 2, "planned", 0)]
    assert items[0]["subject"] == "It has been a while" and len(items[0]["preview"]) <= cal.PREVIEW
    assert items[0]["preview"].endswith("…") and "subject" not in items[1]
    assert items[1]["at"] == "2026-10-13T15:00:00+00:00"
    paused = cal.touch_items(campaign(status="paused"), {}, start, end, NOW)
    assert [i["state"] for i in paused] == ["sent", "paused", "paused"]
    assert cal.touch_items(campaign(status="draft"), {}, start, end, NOW) == []
    assert cal.touch_items(campaign(start=None), {}, start, end, NOW) == []


def test_the_month_puts_posts_and_outreach_in_time_order(monkeypatch):
    post = {"id": "p1", "business_id": BIZ, "status": "approved", "caption": "Fresh fades", "run_at": "2026-10-12T16:00:00+00:00",
            "targets": [{"platform": "instagram", "connection_id": "c1", "username": "fade"}]}

    async def posts(bid, start, end):
        assert bid == BIZ and start == datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc)
        return [post]

    monkeypatch.setattr(cal, "_posts", posts)
    monkeypatch.setattr(cal, "_campaigns", lambda bid: ([campaign()], {"11111111-2222-4333-8444-555555555555": {0: 41}}))
    out = run(cal.month(BIZ, "2026-10", tz=CHI, now=NOW))
    assert out["month"] == "2026-10" and out["time_zone"] == "America/Chicago"
    assert out["sources"] == {"posts": "loaded", "campaigns": "loaded", "offers": "loaded"}
    assert [(i["kind"], i["at"][:10]) for i in out["items"]] == [
        ("email", "2026-10-10"), ("post", "2026-10-12"), ("text", "2026-10-13"), ("email", "2026-10-19")]
    assert out["items"][1]["post"]["accounts"] == ["Instagram"] and "provider_account_id" not in repr(out)


def test_a_read_that_fails_is_named_never_an_empty_month(monkeypatch):
    async def down(bid, start, end):
        raise store.StoreUnavailable("down")

    monkeypatch.setattr(cal, "_posts", down)
    monkeypatch.setattr(cal, "_campaigns", lambda bid: ([campaign()], {}))
    out = run(cal.month(BIZ, "2026-10", tz=CHI, now=NOW))
    assert out["sources"] == {"posts": "unavailable", "campaigns": "loaded", "offers": "loaded"}
    assert out["items"] and all(i["kind"] != "post" for i in out["items"])

    async def none(bid, start, end):
        return []

    monkeypatch.setattr(cal, "_posts", none)
    monkeypatch.setattr(cal, "_campaigns", lambda bid: (None, {}))
    out = run(cal.month(BIZ, "2026-10", tz=CHI, now=NOW))
    assert out["sources"] == {"posts": "loaded", "campaigns": "unavailable", "offers": "loaded"} and out["items"] == []


def test_a_month_at_its_row_limit_is_a_floor(monkeypatch):
    async def many(bid, start, end):
        return [{"id": f"p{i}", "status": "approved", "run_at": "2026-10-12T16:00:00+00:00", "targets": []}
                for i in range(cal.POSTS_LIMIT)]

    monkeypatch.setattr(cal, "_posts", many)
    monkeypatch.setattr(cal, "_campaigns", lambda bid: ([], {}))
    assert run(cal.month(BIZ, "2026-10", tz=CHI, now=NOW))["sources"]["posts"] == "partial"


def test_the_reads_are_this_business_s_and_never_a_draft(monkeypatch):
    seen = []

    def get(path):
        seen.append(path)
        return [] if path.startswith("/campaigns") else []

    monkeypatch.setattr(cal.sb_clients, "sb_get_as_service", get)
    rows, sent = cal._campaigns(BIZ)
    assert rows == [] and seen and f"business_id=eq.{BIZ}" in seen[0]
    assert "status=in.(running,paused,completed)" in seen[0] and "start_at=not.is.null" in seen[0]


def test_the_route_is_a_viewer_read():
    routes = {r.path: r for r in bm.router.routes}
    route = routes["/marketing/{business_id}/calendar"]
    assert route.methods == {"GET"}
    src = pathlib.Path(bm.__file__).read_text(encoding="utf-8")
    body = src[src.index("async def calendar_route("):src.index("# ── results")]
    assert "business_access('viewer')" in body and "business_tz, biz" in body


def test_an_offer_shows_on_the_day_it_starts_and_ends(monkeypatch):
    async def none(bid, start, end):
        return []

    monkeypatch.setattr(cal, "_posts", none)
    monkeypatch.setattr(cal, "_campaigns", lambda bid: ([], {}))
    monkeypatch.setattr(cal, "_offers", lambda bid, first, following: [
        {"id": "o1", "code": "FIRST10", "title": "$10 off your first visit", "status": "on",
         "starts_on": "2026-10-13", "ends_on": "2026-11-01"}])
    out = run(cal.month(BIZ, "2026-10", tz=CHI, now=NOW))
    assert [(i["kind"], i["edge"], i["at"]) for i in out["items"]] == [("offer", "starts", "2026-10-13T14:00:00+00:00")]
    nov = run(cal.month(BIZ, "2026-11", tz=CHI, now=NOW))
    assert [(i["edge"], i["code"]) for i in nov["items"]] == [("ends", "FIRST10")]
    monkeypatch.setattr(cal, "_offers", lambda bid, first, following: None)
    assert run(cal.month(BIZ, "2026-10", tz=CHI, now=NOW))["sources"]["offers"] == "unavailable"
