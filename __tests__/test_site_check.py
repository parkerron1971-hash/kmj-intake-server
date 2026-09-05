"""site_check — the system looks at the live site the way a person does.

What these pin, without a browser in the test run:

  * which pages get checked (home always; a secondary page only when
    the site has it; the custom domain when one is connected)
  * measurements become plain-language findings, ranked, deduplicated
  * the vision judge's JSON is tolerated loosely and shaped strictly
  * a run with no browser, or no site, says so and never raises
  * the report lands on the site row and an event on the spine
  * Chief: check_site is registered, taught, and queues the job;
    site_health reads the last report back
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_check  # noqa: E402


def test_pages_home_always_secondary_only_when_present_custom_domain_wins(monkeypatch):
    import sb_clients
    row = {"id": "row-1", "slug": "kmj-creative-solutions", "html_content": "<html>",
           "site_config": {"custom_domain": "kmjcreate.com",
                           "generated_pages": {"about": "<a>", "contact": "<c>", "services": ""}}}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [row])
    _row, urls = site_check.site_pages("biz-1")
    assert urls == ["https://kmjcreate.com/", "https://kmjcreate.com/about", "https://kmjcreate.com/contact"]
    row2 = {"id": "row-2", "slug": "royal-barbers", "html_content": "<html>", "site_config": {}}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [row2])
    assert site_check.site_pages("biz-2")[1] == ["https://royal-barbers.mysolutionist.app/"]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": "r", "html_content": None}])
    assert site_check.site_pages("biz-3")[1] == []


def test_measurements_become_findings_people_can_read():
    page = {"url": "https://kmjcreate.com/about",
            "widths": {"390": {"overflow_x": True, "scroll_width": 612, "broken_images": ["kevin.webp"],
                               "empty_headings": 1, "leftover_tokens": ["{{BUSINESS_EMAIL}}"],
                               "overlaps": [{"a": 'img.photo ""', "b": 'h1 "The work"', "y": 300}]},
                       "1440": {"overflow_x": False, "broken_images": [], "empty_headings": 0,
                                "leftover_tokens": [], "overlaps": []}},
            "failed_requests": ["404 https://x/logo.webp"]}
    f = site_check.findings_from_geometry(page)
    whats = [x["what"] for x in f]
    assert "Something is wider than the screen, so the page scrolls sideways." in whats
    assert "An image did not load." in whats
    assert "A heading has no text in it." in whats
    assert "Placeholder text is showing instead of real content." in whats
    assert "Two things are sitting on top of each other." in whats
    assert "Something the page asked for came back missing." in whats
    assert all(x["where"].startswith("/about") for x in f)
    assert {x["severity"] for x in f} == {"high", "medium"}


def test_a_page_that_failed_to_load_is_one_clear_finding():
    page = {"url": "https://kmjcreate.com/", "widths": {"1440": {"error": "TimeoutError: 30000ms"}}}
    f = site_check.findings_from_geometry(page)
    assert len(f) == 1 and f[0]["severity"] == "high" and "did not load" in f[0]["what"]


def test_vision_json_is_parsed_loosely_and_shaped_strictly():
    text = ('Here you go:\n{"findings":[{"severity":"HIGH","width":"1440","what":"The photo sits below the headline.","where":"About hero"},'
            '{"severity":"weird","what":"Nav is fine"},{"what":""},"junk"],"summary":"one thing"}')
    f = site_check.parse_vision(text, "/about")
    assert f[0] == {"severity": "high", "width": 1440, "source": "vision",
                    "what": "The photo sits below the headline.", "where": "/about: About hero"}
    assert f[1]["severity"] == "medium" and f[1]["width"] == 0
    assert len(f) == 2
    assert site_check.parse_vision("no json here", "/") == []
    assert site_check.parse_vision("{not json", "/") == []


def _wire(monkeypatch, row, pages_result):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [row])
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: patches.append((p, b)))
    monkeypatch.setattr(site_check, "inspect_pages", lambda urls, widths=site_check.WIDTHS, screenshots=True: pages_result)
    monkeypatch.setattr(site_check, "_store_shots", lambda biz, run_id, pages: ["biz/hand/check-x/00.jpg"])
    events = []
    import event_spine
    monkeypatch.setattr(event_spine, "emit", lambda *a, **k: events.append((a, k)) or True)
    return patches, events


ROW = {"id": "row-1", "slug": "kmj-creative-solutions", "html_content": "<html>",
       "site_config": {"custom_domain": "kmjcreate.com", "generated_pages": {"about": "<a>"}, "html_source": "manual"}}


def test_run_files_the_report_on_the_site_row_and_the_spine(monkeypatch):
    clean = {"overflow_x": False, "broken_images": [], "empty_headings": 0, "leftover_tokens": [], "overlaps": []}
    pages = [{"url": "https://kmjcreate.com/", "widths": {"390": clean, "1440": clean}, "shots": {}, "console_errors": [], "failed_requests": []},
             {"url": "https://kmjcreate.com/about", "widths": {"390": clean,
                      "1440": {**clean, "overlaps": [{"a": "img", "b": "h1", "y": 1}]}}, "shots": {}, "console_errors": [], "failed_requests": []}]
    patches, events = _wire(monkeypatch, ROW, pages)
    report = site_check.run("biz-1", reason="deploy", vision=False)
    assert report["ok"] is True
    assert len(report["findings"]) == 1
    assert report["summary"] == "1 thing to look at, across 2 pages."
    assert report["screenshots"] == ["biz/hand/check-x/00.jpg"]
    path, body = patches[0]
    assert path == "/business_sites?id=eq.row-1"
    assert body["site_config"]["last_site_check"]["summary"] == report["summary"]
    assert body["site_config"]["html_source"] == "manual"          # nothing else on the row touched
    assert events and events[0][0][0] == "site_check_completed"
    assert events[0][1]["data"]["findings"] == 1


def test_run_with_nothing_wrong_says_all_clear(monkeypatch):
    clean = {"overflow_x": False, "broken_images": [], "empty_headings": 0, "leftover_tokens": [], "overlaps": []}
    pages = [{"url": "https://kmjcreate.com/", "widths": {"390": clean, "1440": clean}, "shots": {}, "console_errors": [], "failed_requests": []}]
    _wire(monkeypatch, ROW, pages)
    report = site_check.run("biz-1", vision=False)
    assert report["ok"] and report["findings"] == []
    assert report["summary"] == "All clear — nothing out of place on 1 page."


def test_no_browser_and_no_site_are_honest_not_fatal(monkeypatch):
    patches, _ = _wire(monkeypatch, ROW, None)
    r = site_check.run("biz-1", vision=False)
    assert r["ok"] is False and r["error"] == "no_browser"
    assert patches and patches[0][1]["site_config"]["last_site_check"]["error"] == "no_browser"
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    r2 = site_check.run("biz-9", vision=False)
    assert r2["ok"] is False and r2["error"] == "no_site"


def test_site_check_off_switch(monkeypatch):
    monkeypatch.setenv("SITE_CHECK", "off")
    r = site_check.run("biz-1")
    assert r["error"] == "disabled"


def test_describe_reads_like_a_person():
    rep = {"checked_at": "2026-09-04T19:30:00+00:00", "summary": "1 thing to look at, across 2 pages.",
           "findings": [{"what": "The photo sits below the headline.", "where": "/about: hero"}]}
    d = site_check.describe(rep)
    assert d.startswith("Last site check (2026-09-04 19:30): 1 thing to look at")
    assert "• The photo sits below the headline. (/about: hero)" in d
    assert site_check.describe(None) == "No site check has run yet."


# ─── Chief ───────────────────────────────────────────────────────────

def test_check_site_is_registered_classified_taught_and_a_job_kind():
    import chief_of_staff as cos
    import action_registry
    import chief_jobs
    import chief_prompt
    assert cos.ACTION_HANDLERS["check_site"] is cos.handle_check_site
    assert action_registry.reversibility("check_site") == "A"
    assert '"type":"check_site"' in inspect.getsource(chief_prompt)
    assert "site_check" in chief_jobs.KIND_META


def test_check_site_queues_the_job_and_says_where_the_report_lands(monkeypatch):
    import chief_of_staff as cos
    import chief_jobs
    calls = []

    async def fake_enqueue(client, **kw):
        calls.append(kw)
        return {"id": "job-1"}
    monkeypatch.setattr(chief_jobs, "enqueue", fake_enqueue)
    out = asyncio.run(cos.handle_check_site(None, {"id": "biz-1", "owner_id": "u-1"}, {}))
    assert not out.get("failed")
    assert out["result"] == "queued" and out["job_id"] == "job-1"
    assert calls[0]["kind"] == "site_check" and calls[0]["params"] == {"vision": True, "reason": "chief"}
    assert calls[0]["user_id"] == "u-1"
    assert "site health" in out["label"]

    async def dedupe(client, **kw):
        return {"id": "job-1", "deduped": True}
    monkeypatch.setattr(chief_jobs, "enqueue", dedupe)
    out2 = asyncio.run(cos.handle_check_site(None, {"id": "biz-1", "owner_id": "u-1"}, {"vision": False}))
    assert out2["result"] == "already running"


def test_site_health_reads_the_last_check_back(monkeypatch):
    import chief_of_staff as cos
    import sb_clients
    row = {"site_config": {"last_site_check": {"ok": True, "checked_at": "2026-09-04T19:30:00+00:00",
                                               "summary": "1 thing to look at, across 2 pages.",
                                               "findings": [{"what": "The photo sits below the headline.",
                                                             "where": "/about: hero", "severity": "high"}]}},
           "html_content": "<html>", "status": "published"}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [row])
    out = asyncio.run(cos.handle_site_health(None, {"id": "biz-1", "settings": {}}, {}))
    assert out["signal"]["issues"] == 1
    assert "seen on the live site: The photo sits below the headline." in out["result"]
    assert "Last site check (2026-09-04 19:30)" in out["result"]
    row["site_config"]["last_site_check"] = {"ok": True, "checked_at": "2026-09-04T19:40:00+00:00",
                                             "summary": "All clear — nothing out of place on 2 pages.", "findings": []}
    out2 = asyncio.run(cos.handle_site_health(None, {"id": "biz-1", "settings": {}}, {}))
    assert out2["signal"]["issues"] == 0
    assert "last visual check found nothing out of place" in out2["result"]


def test_job_runner_dispatches_site_check(monkeypatch):
    import chief_jobs
    seen = {}
    fake = types.SimpleNamespace(run=lambda biz, reason, vision, progress_cb=None: seen.update(
        biz=biz, reason=reason, vision=vision) or {"ok": True, "summary": "All clear", "findings": []})
    monkeypatch.setitem(sys.modules, "site_check", fake)
    out = chief_jobs._execute_kind("site_check", "biz-1", {"reason": "chief", "vision": False}, "job-1")
    assert seen == {"biz": "biz-1", "reason": "chief", "vision": False}
    assert out["summary"] == "All clear"
