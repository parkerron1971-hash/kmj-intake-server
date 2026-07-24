"""
test_discovery.py — Revamp Phase 1: the ONE dossier.

Pins the pure parts: merge semantics (recon never clobbers what the
practitioner said), the reference-study failure contract (recorded
facts, never silent gaps), and the Director-side digest.
"""
from unittest import mock

import discovery
from spec_author import build_user_prompt


# ─── merge semantics ─────────────────────────────────────────────────

def test_recon_never_clobbers_practitioner_answers():
    existing = discovery._empty_dossier()
    existing["taste"]["ground"] = {"value": "light", "source": "flipped"}
    existing["taste"]["tone"] = {"value": "serious", "source": "recon"}
    existing["identity"]["one_liner"] = {"value": "I coach founders",
                                          "source": "asked"}
    fresh = discovery._empty_dossier()
    fresh["taste"]["ground"] = {"value": "dark", "source": "recon"}
    fresh["taste"]["tone"] = {"value": "playful", "source": "recon"}
    fresh["identity"]["one_liner"] = {"value": "recon guess",
                                       "source": "recon"}
    out = discovery.merge_recon(existing, fresh)
    # flipped + asked survive; recon-sourced updates
    assert out["taste"]["ground"]["value"] == "light"
    assert out["identity"]["one_liner"]["value"] == "I coach founders"
    assert out["taste"]["tone"]["value"] == "playful"


def test_merge_unions_work_by_url_and_fills_empty_artifacts():
    existing = discovery._empty_dossier()
    existing["artifacts"]["work"] = [{"url": "https://x/a.png", "note": "a"}]
    fresh = discovery._empty_dossier()
    fresh["artifacts"]["brand_mark_url"] = "https://x/mark.png"
    fresh["artifacts"]["work"] = [{"url": "https://x/a.png", "note": "dupe"},
                                   {"url": "https://x/b.png", "note": "b"}]
    out = discovery.merge_recon(existing, fresh)
    assert out["artifacts"]["brand_mark_url"] == "https://x/mark.png"
    urls = [w["url"] for w in out["artifacts"]["work"]]
    assert urls == ["https://x/a.png", "https://x/b.png"]   # deduped


def test_merge_never_removes_practitioner_avoids():
    existing = discovery._empty_dossier()
    existing["truth"]["colors_avoid"] = [
        {"color": "red", "why": "old bad logo", "source": "asked"}]
    fresh = discovery._empty_dossier()
    fresh["truth"]["colors_avoid"] = [
        {"color": "neon green", "why": None, "source": "recon"}]
    out = discovery.merge_recon(existing, fresh)
    colors = {a["color"] for a in out["truth"]["colors_avoid"]}
    assert colors == {"red", "neon green"}


# ─── the reference-study failure contract (Footnote B) ───────────────

def test_study_reference_records_capture_failure_loudly(monkeypatch):
    monkeypatch.setattr(discovery, "_screenshot_url", lambda url: None)
    saved = {}
    monkeypatch.setattr(discovery, "get_dossier",
                        lambda biz: discovery._empty_dossier())
    monkeypatch.setattr(discovery, "save_dossier",
                        lambda biz, d: saved.update(d) or True)
    entry = discovery.study_reference("biz", "https://blocked.example",
                                      "love", "clean")
    assert "error" in entry and "could not capture" in entry["error"]
    refs = saved["artifacts"]["references"]
    assert refs and refs[0]["url"] == "https://blocked.example"
    assert refs[0]["verdict"] == "love"


def test_study_reference_replaces_prior_entry_for_same_url(monkeypatch):
    d = discovery._empty_dossier()
    d["artifacts"]["references"] = [{"url": "https://x.com", "verdict": "hate"}]
    saved = {}
    monkeypatch.setattr(discovery, "_screenshot_url", lambda url: None)
    monkeypatch.setattr(discovery, "get_dossier", lambda biz: d)
    monkeypatch.setattr(discovery, "save_dossier",
                        lambda biz, dd: saved.update(dd) or True)
    discovery.study_reference("biz", "https://x.com", "love")
    refs = saved["artifacts"]["references"]
    assert len(refs) == 1 and refs[0]["verdict"] == "love"


# ─── the Director's view ─────────────────────────────────────────────

def test_dossier_digest_empty_when_nothing_useful():
    assert discovery.dossier_digest(None) == ""
    assert discovery.dossier_digest(discovery._empty_dossier()) == ""


def test_dossier_digest_and_prompt_section():
    d = discovery._empty_dossier()
    d["identity"]["brand_persona"] = {"value": ["bold", "warm", "faithful"],
                                       "source": "asked"}
    d["taste"]["ground"] = {"value": "dark", "source": "inferred-confirmed",
                             "confidence": 0.9}
    digest = discovery.dossier_digest(d)
    assert "bold" in digest and "inferred-confirmed" in digest
    p = build_user_prompt("D", [], discovery=digest)
    assert "THE DISCOVERY DOSSIER" in p
    assert "outrank" in p                      # provenance weighting taught
    p2 = build_user_prompt("D", [])
    assert "THE DISCOVERY DOSSIER" not in p2   # absent when empty
