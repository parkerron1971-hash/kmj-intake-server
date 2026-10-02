"""Chief's eyes on a reference website (2026-09-22).

Kevin: "can it see a website that I wanted to kinda get my website
design from" — it could not. Chief now runs the Design Session's own
reference study (screenshots at 390/1440 read by a vision model), saved
to the same design notes the Blueprint and the builder read; the quick
brief's pasted sites get the same study; every one of these page loads
goes through the public-only guarded browser.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_registry
import chief_reference_actions as ref
import website_image_references as wir

LOVED = {"url": "https://calm.example/", "verdict": "love", "studied_at": "2026-09-22T20:00:00+00:00",
         "rules": ["hairline dividers; one accent doing one job", "big quiet headline over open space"],
         "bans": [],
         "taste": {"ground": {"value": "light", "confidence": 0.9},
                   "density": {"value": "spacious", "confidence": 0.8},
                   "carrier": {"value": "type", "confidence": 0.7}}}


def _run(action, monkeypatch, entry=LOVED, dossier=None):
    import discovery
    calls = []

    def study(business_id, url, verdict, why=""):
        calls.append((business_id, url, verdict, why))
        return {**entry, "url": url, "verdict": verdict}
    monkeypatch.setattr(discovery, "study_reference", study)
    monkeypatch.setattr(discovery, "get_dossier", lambda b: dossier)
    out = asyncio.run(ref.handle_study_website(None, {"id": "biz-1"}, action))
    return out, calls


def test_chief_studies_a_site_and_says_only_what_the_study_saw(monkeypatch):
    out, calls = _run({"url": "calm.example", "why": "so calm"}, monkeypatch)
    assert calls == [("biz-1", "https://calm.example/", "love", "so calm")]
    assert not out.get("failed") and out["label"] == "Studied calm.example"
    text = out["result"]
    assert "background: light" in text and "spacing: spacious" in text
    assert "hairline dividers" in text
    assert "Design Session, your Blueprint and the site builder" in text


def test_a_disliked_site_is_saved_as_a_look_to_avoid(monkeypatch):
    entry = {**LOVED, "rules": [], "bans": ["no parallax"]}
    out, calls = _run({"url": "https://busy.example", "verdict": "hate"}, monkeypatch, entry)
    assert calls[0][2] == "hate"
    assert "What to avoid: no parallax" in out["result"]


def test_a_page_it_could_not_see_is_a_failure_not_a_description(monkeypatch):
    entry = {"url": "x", "verdict": "love", "error": "could not capture (bot-blocked, dead link, or timeout)"}
    out, _ = _run({"url": "https://blocked.example"}, monkeypatch, entry)
    assert out["failed"] and "could not see" in out["result"].lower()
    assert "The feel" not in out["result"]


@pytest.mark.parametrize("url", ["http://localhost/admin", "http://10.0.0.5/", "http://169.254.169.254/latest",
                                 "https://user:pw@example.com/", "file:///etc/passwd", "http://intranet.internal/"])
def test_a_private_address_is_refused_before_anything_loads(url, monkeypatch):
    out, calls = _run({"url": url}, monkeypatch)
    assert out["failed"] and calls == []


def test_the_daily_limit_holds(monkeypatch):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    dossier = {"artifacts": {"references": [{"url": f"https://s{i}.example/", "studied_at": now}
                                            for i in range(ref.DAILY_STUDIES)]}}
    out, calls = _run({"url": "https://one-more.example"}, monkeypatch, dossier=dossier)
    assert out["failed"] and calls == []


def test_it_is_a_registered_class_a_write_with_a_handler():
    import chief_of_staff
    assert action_registry.effect("study_website") == action_registry.WRITE
    assert action_registry.reversibility("study_website") == "A"
    assert chief_of_staff.ACTION_HANDLERS["study_website"] is ref.handle_study_website


def test_it_is_not_offered_to_outside_agents():
    import mcp_server
    assert "study_website" not in mcp_server.WRITE_TOOL_SCHEMAS


def test_the_prompt_tells_chief_it_can_see_a_site():
    import chief_prompt
    src = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")
    assert "You CAN look at a public website" in src and '"type":"study_website"' in src


# ── the study's screenshots go through the guarded browser ──────────────

def test_discovery_screenshots_use_the_guarded_capture(monkeypatch):
    import discovery
    seen = []
    monkeypatch.setattr(wir, "capture_viewports_sync", lambda url, widths, h: seen.append((url, widths)) or [b"a", b"b"])
    assert discovery._screenshot_url("https://calm.example/") == [b"a", b"b"]
    assert seen == [("https://calm.example/", (390, 1440))]


def test_a_refused_address_is_a_failed_capture_not_a_crash(monkeypatch):
    import discovery

    def refuse(url, widths, h):
        raise ValueError("Private or reserved network addresses cannot be captured.")
    monkeypatch.setattr(wir, "capture_viewports_sync", refuse)
    assert discovery._screenshot_url("https://sneaky.example/") is None


def test_brand_learn_from_url_refuses_a_private_address():
    import brand_engine
    out = brand_engine.learn_from_url("biz-1", "http://127.0.0.1:8080/")
    assert out["ok"] is False
    out = brand_engine.learn_from_url("biz-1", "http://localhost/")
    assert out["ok"] is False


# ── the quick brief's pasted sites get the same study ─────────────────

def test_brief_sites_are_studied_once_into_the_design_notes(monkeypatch):
    import discovery
    import site_composer
    studied = []
    monkeypatch.setattr(discovery, "get_dossier", lambda b: {"artifacts": {"references": [
        {"url": "https://done.example/", "rules": ["x"]},
        {"url": "https://failed.example/", "error": "timeout"}]}})
    monkeypatch.setattr(discovery, "study_reference",
                        lambda b, u, v, w="": studied.append((u, v, w)) or {"url": u})
    ctx = {"site_prefs": {"inspiration_urls": ["https://done.example/", "https://failed.example/",
                                               "https://new.example/", "https://fourth.example/"],
                          "inspiration_notes": "warm and simple"}}
    site_composer._study_inspiration_sites("biz-1", ctx)
    assert studied == [("https://failed.example/", "love", "warm and simple"),
                       ("https://new.example/", "love", "warm and simple")]


def test_a_brief_without_sites_studies_nothing(monkeypatch):
    import discovery
    import site_composer
    monkeypatch.setattr(discovery, "study_reference", lambda *a, **k: pytest.fail("studied"))
    site_composer._study_inspiration_sites("biz-1", {"site_prefs": {}})
    site_composer._study_inspiration_sites("biz-1", {})


# ── the builder's look tool photographs a page instead of failing ─────

def test_the_builder_looks_at_a_reference_page_as_a_screenshot(monkeypatch):
    import builder_loop as bl
    import builder_v2 as v2
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "")
    box = bl.ToolBox({}, "biz-1", "REFERENCES: https://calm.example/ (loved)\n- https://x/a.jpg", "")
    monkeypatch.setattr(wir, "capture_viewports_sync", lambda url, widths, h: [b"jpeg"])
    page = box.look("https://calm.example/")
    assert page[1]["type"] == "image" and page[1]["source"]["type"] == "base64"
    assert "never copy" in page[0]["text"]
    img = box.look("https://x/a.jpg")
    assert img[1]["source"] == {"type": "url", "url": "https://x/a.jpg"}


def test_a_reference_page_that_will_not_open_is_text_not_a_crash(monkeypatch):
    import builder_loop as bl

    def boom(*a):
        raise ValueError("no")
    monkeypatch.setattr(wir, "capture_viewports_sync", boom)
    box = bl.ToolBox({}, "biz-1", "https://calm.example/", "")
    out = box.look("https://calm.example/")
    assert len(out) == 1 and "could not be opened" in out[0]["text"]
