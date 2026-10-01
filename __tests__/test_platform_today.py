"""Mission Control → Today: one problem shows once, people come first,
and a broken source costs its own line — never the page.

The queue replaced eighteen panels' worth of attention signals. Its
promises are the ones the old Overview broke: the hourly watcher that
wrote the same sentence three times now counts as one item; a stale
pending row from last week is not today's news; setup gaps (missing env
keys) are parked rather than paging; and a Stripe timeout drops the
coupon line while everything else still renders.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import platform_today as pt

NOW = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)


def _row(title, hours_ago, agent=None, status="pending"):
    return {"title": title, "agent": agent, "status": status,
            "created_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_normalize_collapses_numbers_and_latest_tail():
    a = pt.normalize_finding("11 server errors in the last hour (latest: Job gate 4:10)")
    b = pt.normalize_finding("10 server errors in the last hour (latest: sb_clients GET)")
    assert a == b == "# server errors in the last hour"


def test_repeats_count_once_and_newest_wording_wins():
    rows = [
        _row("Hermes: 13 outbound SMS stuck at 'sent' > 24h", 1, "hermes"),
        _row("Hermes: 12 outbound SMS stuck at 'sent' > 24h", 2, "hermes"),
        _row("Hermes: 13 outbound SMS stuck at 'sent' > 24h", 3, "hermes"),
    ]
    groups, stale = pt.group_findings(rows, NOW)
    assert stale == 0
    assert len(groups) == 1
    assert groups[0]["seen"] == 3
    assert groups[0]["title"].startswith("13 outbound")


def test_old_pending_rows_are_not_todays_news():
    groups, stale = pt.group_findings([_row("Watchdog: db slow", 48, "watchdog")], NOW)
    assert groups == [] and stale == 1


def test_resolved_rows_are_ignored():
    groups, stale = pt.group_findings([_row("x", 1, "hermes", status="done")], NOW)
    assert groups == [] and stale == 0


def test_agent_falls_back_to_title_prefix():
    groups, _ = pt.group_findings([_row("Watchdog: 11 server errors in the last hour", 1)], NOW)
    assert groups[0]["agent"] == "watchdog"


def test_missing_env_keys_park_instead_of_paging():
    item = pt.classify_finding({"agent": "watchdog", "seen": 4, "latest_at": NOW, "first_at": NOW,
                                "title": "Meta Ads (Pixel + CAPI) is missing env keys: META_PIXEL_ID"})
    assert item["parked"] is True


def test_server_errors_go_to_sentry():
    item = pt.classify_finding({"agent": "watchdog", "seen": 1, "latest_at": NOW, "first_at": NOW,
                                "title": "11 server errors in the last hour (latest: x)"})
    assert item["tone"] == "red"
    assert item["action"]["href"].startswith("https://")
    assert "(latest" not in item["title"]


def test_unanswered_customer_text_is_a_people_item():
    item = pt.classify_finding({"agent": "hermes", "seen": 3, "latest_at": NOW, "first_at": NOW,
                                "title": "1 customer text unanswered for 4+ hours"})
    assert item["lanes"] == ["people"]
    assert "3×" in item["detail"]


def test_rank_people_then_money_then_systems_worst_first():
    items = [
        {"id": "sys", "lanes": ["systems"], "tone": "red"},
        {"id": "money", "lanes": ["money"], "tone": "amber"},
        {"id": "people-blue", "lanes": ["people"], "tone": "blue"},
        {"id": "people-red", "lanes": ["people", "money"], "tone": "red"},
    ]
    assert [i["id"] for i in pt.rank(items)] == ["people-red", "people-blue", "money", "sys"]


def test_read_restates_the_queue():
    needs = [
        {"title": "Creative Genius's renewal didn't go through", "lanes": ["people", "money"]},
        {"title": "13 texts stuck", "lanes": ["systems"]},
    ]
    read = pt.compose_read(needs, [])
    assert read["headline"].startswith("One thing touches real people")
    assert "creative genius" in read["body"]


def test_read_when_quiet_mentions_parked():
    read = pt.compose_read([], [{"title": "Meta keys"}])
    assert "Nothing needs you" in read["headline"]
    assert "parked" in read["body"]


def test_coverage_reports_sentry_from_env(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://x@o.ingest.sentry.io/1")
    assert next(c for c in pt.coverage() if c["id"] == "backend_errors")["covered"]
    monkeypatch.delenv("SENTRY_DSN")
    assert not next(c for c in pt.coverage() if c["id"] == "backend_errors")["covered"]


def test_a_failing_source_costs_only_its_own_line(monkeypatch):
    """Every source down at once still returns a page, naming what's missing."""
    import platform_console as pc

    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(pc, "subscriptions_summary", boom)
    monkeypatch.setattr(pc, "_recent_merged_prs", boom)
    monkeypatch.setattr(pt, "_practitioners", boom)
    monkeypatch.setattr(pt, "_count", boom)
    monkeypatch.setattr(pt, "_get", boom)
    monkeypatch.setattr(pt, "_platform_posts_pending", boom)
    monkeypatch.setattr(pt, "_traffic", boom)
    monkeypatch.setattr(pt, "_coupons", boom)
    monkeypatch.setattr(pt, "_anchor_health", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pt, "_spend", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    class Owner:
        id = "00000000-0000-0000-0000-000000000001"

    out = asyncio.run(pt.build_today(Owner()))
    assert out["ok"] is True
    assert out["needs_you"] == []
    for name in ("subscriptions", "coupons", "findings", "traffic", "ships"):
        assert name in out["sources_failed"]
    assert out["read"]["headline"]


def test_payment_issue_is_featured_and_drafts_through_chief(monkeypatch):
    import platform_console as pc

    async def subs(**k):
        return {"payment_issues": [{"business_id": "b1", "business_name": "Creative Genius",
                                    "status": "past_due"}],
                "trial_ending_soon": [], "by_status": {}, "mrr_cents": 0}

    async def nothing(*a, **k):
        return []

    async def zero(*a, **k):
        return 0

    async def none(*a, **k):
        return None

    monkeypatch.setattr(pc, "subscriptions_summary", subs)
    monkeypatch.setattr(pc, "_recent_merged_prs", nothing)
    monkeypatch.setattr(pt, "_practitioners", lambda c: none())
    monkeypatch.setattr(pt, "_count", zero)
    monkeypatch.setattr(pt, "_get", nothing)
    monkeypatch.setattr(pt, "_platform_posts_pending", zero)
    monkeypatch.setattr(pt, "_traffic", none)
    monkeypatch.setattr(pt, "_coupons", none)
    monkeypatch.setattr(pt, "_anchor_health", lambda: {"providers": []})
    monkeypatch.setattr(pt, "_spend", lambda: {"today_cents": 120, "cap_cents": 5000})

    class Owner:
        id = "00000000-0000-0000-0000-000000000001"

    out = asyncio.run(pt.build_today(Owner()))
    first = out["needs_you"][0]
    assert first["featured"] is True
    assert first["kind"] == "payment"
    assert "Creative Genius" in first["action"]["chief"]
    assert out["pulse"]["ai_spend_today_cents"] == 120
