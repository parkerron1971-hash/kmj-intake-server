"""The work log parses and answers "have we built this?"; the unfinished-work
watcher sorts open PRs correctly and lists what is pending."""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import unfinished_work as uw
import worklog as wl

NOW = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)

ENTRY = """---
title: Calendar feeds block booking slots
date: 2026-09-26
agent: Claude Code (Claude Opus 5)
asked: "keep Calendly and have it work around it"
status: waiting on Kevin
prs: [kmj-intake-server#1059]
migrations: [supabase/APPLY-2026-09-26-calendar-feeds.sql (pending)]
left_undone: ["apply the calendar-feeds migration"]
decisions: ["read-only iCal feeds, no OAuth"]
---
Paste a Google or Outlook calendar link and its busy times close booking slots.
"""


def test_every_real_log_entry_parses():
    files = [p for p in (ROOT / "worklog").glob("*.md") if p.name.lower() != "readme.md"]
    assert files, "the work log has entries"
    for p in files:
        e = wl.parse_entry(p.read_text(encoding="utf-8"), "kmj-intake-server", str(p))
        assert e and e["title"] and e["date"] and e["status"], p.name


def test_parse_entry():
    e = wl.parse_entry(ENTRY, "kmj-intake-server", "worklog/x.md")
    assert e["status"] == "waiting on kevin" and not e["done"]
    assert e["prs"] == ["kmj-intake-server#1059"]
    assert e["left_undone"] == ["apply the calendar-feeds migration"]
    assert wl.parse_entry("no front matter here", "r", "p") is None


def test_search_answers_have_we_built_this():
    e = wl.parse_entry(ENTRY, "kmj-intake-server", "worklog/x.md")
    other = wl.parse_entry(ENTRY.replace("Calendar feeds block booking slots", "Refund flow")
                           .replace("Paste a Google", "Refunds go"), "r", "p")
    hits = wl.search([other, e], "do we have something for calendar busy times?")
    assert hits[0]["title"] == "Calendar feeds block booking slots"
    assert wl.search([e], "") == []


def pr(**kw):
    base = {"number": 1, "title": "A change", "draft": False, "mergeable_state": "clean",
            "created_at": (NOW - timedelta(days=2)).isoformat()}
    base.update(kw)
    return base


def test_classify():
    assert uw.classify(pr(), ["success", "skipped"], NOW) == ["ready"]
    assert uw.classify(pr(mergeable_state="behind"), ["success"], NOW) == ["behind"]
    assert uw.classify(pr(mergeable_state="dirty"), ["success"], NOW) == ["conflicts"]
    assert uw.classify(pr(mergeable_state="blocked"), ["failure"], NOW) == ["failing"]
    assert uw.classify(pr(mergeable_state="blocked"), ["", "success"], NOW) == ["checking"]
    assert uw.classify(pr(title="News draft: X"), ["success"], NOW) == ["news"]
    old = pr(created_at=(NOW - timedelta(days=40)).isoformat())
    assert uw.classify(old, ["success"], NOW) == ["ready", "stale"]


def test_pending_migrations():
    md = ("| `supabase/APPLY-2026-10-02-a.sql` | x | **PENDING.** Verify |\n"
          "| `supabase/APPLY-2026-09-29-b.sql` | y | **APPLIED 2026-09-29** |\n")
    assert uw.pending_migrations(md) == ["supabase/APPLY-2026-10-02-a.sql"]


def test_render_lists_each_bucket():
    item = {"repo": "solutionist-studio", "number": 994, "title": "Chief speaks first",
            "url": "https://x/994", "created_at": "2026-09-26"}
    r = {"generated_at": NOW.isoformat(), "ready": [item], "updated": [], "news": [],
         "conflicts": [], "failing": [], "draft": [], "checking": [], "stale": [item],
         "migrations": ["supabase/APPLY-x.sql"],
         "work_log_open": [{"title": "Calendar feeds", "date": "2026-09-26",
                            "status": "waiting on kevin", "left_undone": ["apply migration"]}],
         "errors": []}
    body = uw.render(r)
    assert "Ready for your yes" in body and "[app #994](https://x/994)" in body
    assert "`supabase/APPLY-x.sql`" in body and "check whether applied" in body and "left undone: apply migration" in body
    assert "Open 14+ days" in body
