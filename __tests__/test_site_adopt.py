"""site_adopt — a hand-built site becomes the system's own.

What these pin:

  * the words on a page: markup, scripts and serve-time tokens gone
  * the record is written from the live pages, saved APPROVED with a
    bumped revision, and stamped so it happens once per change of words
  * a current record costs nothing (no model call); no key is fail-soft;
    a lost save is reported, never claimed
  * site_sync schedules the record after an install AND when the pages
    are already current (a site installed before this existed)
  * Chief's site block names the builder, the pages, the record and the
    verbs; the prompt teaches it
  * site_health stops reading the replaced build's gates
  * a builder job is refused for a hand-built site (Chief verb + endpoint)
  * the served page carries the Studio edit-mode listener
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import site_adopt  # noqa: E402


@pytest.fixture(autouse=True)
def _no_claim_settle(monkeypatch):
    """The claim re-reads after a beat in production; tests never wait."""
    monkeypatch.setattr(site_adopt, "CLAIM_SETTLE_S", 0)

HOME = """<!doctype html><html><head><title>KMJ</title>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@700&amp;family=Work+Sans:wght@400" rel="stylesheet">
<style>body{font-family:'Work Sans',sans-serif;color:#0b0b0b;background:#f5f1ea}h1{color:#c8102e}</style>
<script>window.x = 1;</script></head><body>
<!-- {{GALLERY_SECTION}} -->
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<h1 data-override-target="home.hero.h1">Elevate Your Vision, Amplify Your Impact</h1>
<p>A solutionist practice. Coaching for founders &amp; leaders.</p>
<a class="cta" href="/contact">Book a discovery call</a>
<p>Write to {{BUSINESS_EMAIL}}</p>
</body></html>"""
ABOUT = "<html><body><h1>About Kevin</h1><p>Ten years in ministry.</p></body></html>"


def _row(**over):
    row = {"id": "row-1", "business_id": "biz-1", "slug": "kmj-creative-solutions",
           "html_content": HOME,
           "site_config": {"html_source": "manual", "manual_hash": "h1",
                           "manual_installed_at": "2026-09-03T14:00:00+00:00",
                           "site_pages": ["home", "about"],
                           "generated_pages": {"about": ABOUT},
                           "custom_domain": "kmjcreate.com",
                           "design_spec": {"text": "old composed spec", "status": "approved",
                                           "revision": 3}}}
    row.update(over)
    return row


class _DB:
    def __init__(self, row, business=None):
        self.row = row
        self.business = business or {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach"}
        self.patches = []

    def get(self, path):
        if path.startswith("/business_sites"):
            return [self.row] if self.row else []
        if path.startswith("/businesses"):
            return [self.business]
        return []

    def patch(self, path, body):
        self.patches.append((path, body))
        if self.row is not None and "site_config" in body:
            self.row["site_config"] = body["site_config"]
        return [self.row]


def _wire(monkeypatch, db):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    return db


# ─── the words ────────────────────────────────────────────────────────

def test_page_text_is_the_copy_a_visitor_reads():
    text = site_adopt.page_text(HOME)
    assert "Elevate Your Vision, Amplify Your Impact" in text
    assert "Coaching for founders & leaders." in text
    assert "Book a discovery call" in text
    assert "window.x" not in text and "font-family" not in text
    assert "{{" not in text and "GALLERY_SECTION" not in text
    assert "<" not in text
    assert site_adopt.page_text("") == ""


def test_pages_follow_site_order_home_first():
    pages = site_adopt.pages_of(_row())
    assert list(pages) == ["home", "about"]
    fonts, hexes = site_adopt.style_facts(pages)
    assert fonts[:2] == ["Bricolage Grotesque", "Work Sans"]
    assert "#c8102e" in hexes and "#0b0b0b" in hexes


def test_the_text_digest_ignores_a_css_only_change():
    a = site_adopt.text_digest(site_adopt.pages_of(_row()))
    b = site_adopt.text_digest(site_adopt.pages_of(_row(html_content=HOME.replace("#c8102e", "#000000"))))
    c = site_adopt.text_digest(site_adopt.pages_of(_row(html_content=HOME.replace("Elevate", "Raise"))))
    assert a == b and a != c


def test_prompt_carries_every_page_and_the_style_facts():
    user = site_adopt.build_user_prompt({"name": "KMJ Creative Solutions"}, _row(),
                                        site_adopt.pages_of(_row()))
    assert "LIVE ADDRESS: https://kmjcreate.com" in user
    assert "INSTALLED: 2026-09-03" in user
    assert "===== PAGE / =====" in user and "===== PAGE /about =====" in user
    assert "Ten years in ministry." in user
    assert "fonts: Bricolage Grotesque, Work Sans" in user
    assert "OBSERVED ON THE SITE" in site_adopt._SYSTEM and "TRUTH LAW" in site_adopt._SYSTEM


# ─── the record ───────────────────────────────────────────────────────

def test_adopt_writes_the_record_from_the_live_pages(monkeypatch):
    db = _wire(monkeypatch, _DB(_row()))
    import spec_author
    seen = {}

    def fake_llm(system, user, business_id, image_urls=None, mark_urls=None):
        seen.update(system=system, user=user, biz=business_id)
        return "1. OVERVIEW\n=====\nA solutionist practice site."
    monkeypatch.setattr(spec_author, "_call_llm", fake_llm)
    monkeypatch.setattr(spec_author, "_model", lambda: "claude-test")

    out = site_adopt.adopt("biz-1")
    assert out["ok"] and out["status"] == "adopted" and out["revision"] == 4
    assert seen["biz"] == "biz-1" and "Elevate Your Vision" in seen["user"]
    cfg = db.patches[-1][1]["site_config"]
    spec = cfg["design_spec"]
    assert spec["status"] == "approved" and spec["revision"] == 4
    assert spec["source"] == "adopted" and spec["text"].startswith("1. OVERVIEW")
    assert cfg["adopted"]["hash"] == "h1" and cfg["adopted"]["pages"] == ["home", "about"]
    assert cfg["adopted"]["text_hash"] == out["text_hash"]
    assert "adopting" not in cfg          # the claim is cleared by the record
    # the path's "Built <date>" is the install, not the moment of writing
    assert cfg["html_generated_at"] == "2026-09-03T14:00:00+00:00"
    # the second pass is free
    monkeypatch.setattr(spec_author, "_call_llm", lambda *a, **k: pytest.fail("paid twice"))
    again = site_adopt.adopt("biz-1")
    assert again == {"ok": True, "status": "current", "text_hash": out["text_hash"]}


def test_adopt_is_fail_soft(monkeypatch):
    import spec_author
    # not hand-built
    db = _wire(monkeypatch, _DB(_row(site_config={"html_source": "module-composer"})))
    assert site_adopt.adopt("biz-1") == {"ok": False, "error": "not_hand_built"}
    # no row
    _wire(monkeypatch, _DB(None))
    assert site_adopt.adopt("biz-1") == {"ok": False, "error": "no_site"}
    # author unavailable (no key) → nothing written
    db = _wire(monkeypatch, _DB(_row()))
    monkeypatch.setattr(spec_author, "_call_llm", lambda *a, **k: None)
    assert site_adopt.adopt("biz-1") == {"ok": False, "error": "author_unavailable"}
    # only the claim stamp landed — no record, nothing that reads as adopted
    assert not [p for p in db.patches if "adopted" in p[1]["site_config"]]
    # …and that claim holds for the TTL, so a retry a moment later yields
    monkeypatch.setattr(spec_author, "_call_llm", lambda *a, **k: "1. OVERVIEW")
    assert site_adopt.adopt("biz-1")["status"] == "claimed_elsewhere"
    # a lost save is reported, never claimed
    db = _wire(monkeypatch, _DB(_row()))
    monkeypatch.setattr(spec_author, "_patch_site_config",
                        lambda *a, **k: (_ for _ in ()).throw(spec_author.SpecSaveFailed("lost")))
    assert site_adopt.adopt("biz-1") == {"ok": False, "error": "save_failed"}
    # an unexpected exception never escapes
    monkeypatch.setattr(site_adopt, "pages_of", lambda row: (_ for _ in ()).throw(RuntimeError("boom")))
    out = site_adopt.adopt("biz-1")
    assert out["ok"] is False and "RuntimeError" in out["error"]


def test_one_replica_writes_the_record(monkeypatch):
    """Two replicas boot together and both schedule a pass; the first live
    deploy paid twice. A claim stamp lets exactly one proceed."""
    import spec_author
    from datetime import datetime, timedelta, timezone
    paid = []
    monkeypatch.setattr(spec_author, "_call_llm",
                        lambda *a, **k: paid.append(1) or "1. OVERVIEW\n=====\nrecord")
    # A fresh claim by ANOTHER replica for the same words → skip, no call
    db = _wire(monkeypatch, _DB(_row()))
    digest = site_adopt.text_digest(site_adopt.pages_of(db.row))
    db.row["site_config"]["adopting"] = {
        "at": datetime.now(timezone.utc).isoformat(), "text_hash": digest, "token": "other"}
    out = site_adopt.adopt("biz-1")
    assert out == {"ok": True, "status": "claimed_elsewhere", "text_hash": digest}
    assert paid == [] and db.patches == []
    # A stale claim (older than the TTL) is ignored: this replica claims and writes
    db.row["site_config"]["adopting"] = {
        "at": (datetime.now(timezone.utc) - timedelta(seconds=site_adopt.CLAIM_TTL_S + 5)).isoformat(),
        "text_hash": digest, "token": "other"}
    out = site_adopt.adopt("biz-1")
    assert out["ok"] and out["status"] == "adopted" and paid == [1]
    assert db.patches[0][1]["site_config"]["adopting"]["text_hash"] == digest   # the claim
    assert "adopting" not in db.patches[-1][1]["site_config"]                   # cleared
    # The re-read after the beat sees another replica's token → yield
    db2 = _wire(monkeypatch, _DB(_row()))
    real_read = site_adopt._read_row

    def usurped(biz):
        r = real_read(biz)
        if r and (r["site_config"].get("adopting") or {}).get("token"):
            r["site_config"]["adopting"]["token"] = "someone-else"
        return r
    monkeypatch.setattr(site_adopt, "_read_row", usurped)
    out = site_adopt.adopt("biz-1")
    assert out["status"] == "claimed_elsewhere" and paid == [1]
    # A claim that cannot be written never blocks the record (fail-open)
    import sb_clients
    db3 = _wire(monkeypatch, _DB(_row()))
    monkeypatch.setattr(site_adopt, "_read_row", real_read)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: (_ for _ in ()).throw(RuntimeError("down")) if "adopting" in json.dumps(b) and "adopted" not in json.dumps(b) else db3.patch(p, b))
    out = site_adopt.adopt("biz-1")
    assert out["status"] == "adopted" and paid == [1, 1]


def test_schedule_skips_a_current_record_and_the_off_switch(monkeypatch):
    started = []
    monkeypatch.setattr(site_adopt.threading, "Timer",
                        lambda d, fn: types.SimpleNamespace(start=lambda: started.append(d),
                                                            daemon=False, name=""))
    monkeypatch.delenv("SITE_ADOPT", raising=False)
    cfg = _row()["site_config"]
    assert site_adopt.schedule("biz-1", cfg) is True
    cfg["adopted"] = {"hash": "h1", "text_hash": "t"}
    assert site_adopt.schedule("biz-1", cfg) is False
    cfg["adopted"] = {"hash": "stale", "text_hash": "t"}
    assert site_adopt.schedule("biz-1", cfg) is True
    monkeypatch.setenv("SITE_ADOPT", "off")
    assert site_adopt.schedule("biz-1", cfg) is False
    assert started == [5.0, 5.0]


def test_site_sync_schedules_the_record_after_install_and_when_current(monkeypatch):
    import site_sync
    calls = []
    monkeypatch.setattr(site_adopt, "schedule", lambda biz, cfg, delay=5.0: calls.append((biz, cfg.get("manual_hash"))))
    monkeypatch.setenv("SITE_CHECK", "off")
    mod = types.SimpleNamespace(SLUG="kmj-creative-solutions", BUSINESS_ID="biz-1",
                                render_pages=lambda: {"home": "<h>", "about": "<a>"})
    db = _wire(monkeypatch, _DB({"id": "row-1", "business_id": "biz-1", "html_content": "x",
                                 "site_config": {"html_source": "module-composer"}}))
    assert site_sync.sync_site(mod) == "installed"
    digest = db.row["site_config"]["manual_hash"]
    assert calls == [("biz-1", digest)]
    assert site_sync.sync_site(mod) == "current"
    assert calls == [("biz-1", digest), ("biz-1", digest)]


# ─── what the rest of the system says ─────────────────────────────────

def test_chief_site_block_names_the_builder_the_pages_and_the_verbs(monkeypatch):
    import chief_of_staff as cos
    site = _row()
    site["site_config"]["adopted"] = {"at": "2026-09-05T12:00:00+00:00", "hash": "h1", "text_hash": "t"}
    site["site_config"]["design_spec"] = {"text": "rec", "status": "approved", "revision": 4, "source": "adopted"}
    site["site_config"]["last_site_check"] = {"ok": True, "checked_at": "2026-09-04T19:40:00+00:00",
                                              "summary": "All clear.", "findings": []}
    block = cos._format_site_info({"site": {"slug": "kmj-creative-solutions", "status": "published",
                                            "site_config": site["site_config"]}})
    assert "Built by: the Solutionist System, hand-built edition (installed 2026-09-03)" in block
    assert "Pages: home, about" in block
    assert "Blueprint rev 4 on file, written from the live pages (adopted 2026-09-05)" in block
    assert "NEVER offer rebuild_site" in block and "edit_site_text" in block
    assert "Last site check (2026-09-04 19:40): All clear." in block
    assert "Custom domain: kmjcreate.com" in block
    # a composed site keeps its usual lines only
    plain = cos._format_site_info({"site": {"slug": "royal", "status": "published",
                                            "site_config": {"html_source": "module-composer"}}})
    assert "hand-built" not in plain
    # before the record exists, say so
    site["site_config"].pop("adopted")
    assert "Design record: not written yet" in cos._format_site_info(
        {"site": {"slug": "k", "status": "published", "site_config": site["site_config"]}})


def test_the_prompt_teaches_the_hand_built_site():
    import chief_prompt
    src = inspect.getsource(chief_prompt)
    assert "A HAND-BUILT SITE" in src
    assert "NEVER emit rebuild_site, refine or compose_directions for it" in src


def test_site_health_stops_reading_the_replaced_builds_gates(monkeypatch):
    import chief_of_staff as cos
    import sb_clients
    cfg = _row()["site_config"]
    cfg.update({"quality_report": {"checks": [{"name": "old_gate", "ok": False, "detail": "stale"}]},
                "dro_failure": {"detail": "no brief"},
                "previous_compose": {"html": "x"},
                "adopted": {"at": "2026-09-05", "hash": "h1", "text_hash": "t"},
                "design_spec": {"text": "rec", "status": "approved", "revision": 4, "source": "adopted"}})
    row = {"site_config": cfg, "html_content": HOME, "status": "published"}
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [row])
    out = asyncio.run(cos.handle_site_health(None, {"id": "biz-1", "settings": {}}, {}))
    assert out["signal"]["issues"] == 0, out["result"]
    assert "hand-built edition installed 2026-09-03" in out["result"]
    assert "design record on file (Blueprint rev 4" in out["result"]
    assert "old_gate" not in out["result"] and "design brief" not in out["result"]
    assert "banked" not in out["result"]
    # the live checks still apply
    row["status"] = "draft"
    out2 = asyncio.run(cos.handle_site_health(None, {"id": "biz-1", "settings": {}}, {}))
    assert out2["signal"]["issues"] == 1 and "not published" in out2["result"]
    # a composed site is untouched by this
    row["site_config"] = {"html_source": "module-composer",
                          "quality_report": {"checks": [{"name": "old_gate", "ok": False, "detail": "x"}]}}
    row["status"] = "published"
    out3 = asyncio.run(cos.handle_site_health(None, {"id": "biz-1", "settings": {}}, {}))
    assert "gate 'old_gate'" in out3["result"]


def test_a_builder_job_is_refused_for_a_hand_built_site(monkeypatch):
    import chief_of_staff as cos
    import chief_jobs
    db = _wire(monkeypatch, _DB(_row()))
    queued = []

    async def fake_enqueue(client, **kw):
        queued.append(kw["kind"])
        return {"id": "job-1"}
    monkeypatch.setattr(chief_jobs, "enqueue", fake_enqueue)
    biz = {"id": "biz-1", "owner_id": "u1"}
    out = asyncio.run(cos.handle_enqueue_job(None, biz, {"kind": "rebuild_site"}))
    assert out["result"].startswith("Not started — this site is the hand-built edition")
    assert "edit_site_text" in out["result"] and queued == []
    for kind in ("compose_directions", "refine_section"):
        assert "Not started" in asyncio.run(cos.handle_enqueue_job(None, biz, {"kind": kind}))["result"]
    # a job that is not a build still runs
    assert asyncio.run(cos.handle_enqueue_job(None, biz, {"kind": "author_spec"}))["job_id"] == "job-1"
    assert queued == ["author_spec"]
    # a composed site builds as before
    db.row["site_config"] = {"html_source": "module-composer"}
    assert asyncio.run(cos.handle_enqueue_job(None, biz, {"kind": "rebuild_site"}))["job_id"] == "job-1"


def test_the_rebuild_endpoint_refuses_too(monkeypatch):
    import chief_jobs
    from fastapi import HTTPException
    _wire(monkeypatch, _DB(_row()))

    async def fake_sb(client, method, path, *a, **k):
        return [{"id": "biz-1"}]
    monkeypatch.setattr(chief_jobs, "_sb", fake_sb)
    session = types.SimpleNamespace(user=types.SimpleNamespace(id="u1"))
    req = chief_jobs._RebuildReq(business_id="biz-1")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(chief_jobs.rebuild_site_endpoint(req, session))
    assert ei.value.status_code == 409 and "hand-built" in str(ei.value.detail)


def test_the_served_page_carries_the_studio_edit_listener(monkeypatch):
    import public_site
    monkeypatch.setattr("agents.override_system.override_resolver.resolve_html_overrides",
                        lambda html, biz: html)
    out = public_site._apply_manual_source(HOME, "biz-1", {})
    assert "__solutionistEditModeReady" in out
    assert "Elevate Your Vision" in out
    # idempotent across a second serve of the same html
    assert out.count("__solutionistEditModeReady = true") == 1
    assert public_site._apply_manual_source(out, "biz-1", {}).count("__solutionistEditModeReady = true") == 1
